#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quota_meter.py — YouTube Data API 配額計量器(全產線唯一一份帳)。

## 為什麼要有這支
在這之前**整條產線沒有任何配額計量**:每天照樣跑到撞上 403 才知道爆了,而且爆掉的
那一刻已經是「某支腳本吃光、後面全部餓死」的狀態——實測 403 集中在 09:00(179 次),
15:00 之後幾乎歸零。原因是兩件事疊在一起:

1. **時區錯配**:配額在**太平洋時間午夜**重置,換算台北是 **15:00~16:00**(夏令時間會差
   一小時)。但排程是照台北的日曆日排的,所以台北 00:00~15:00 這段跑的所有工作,
   花的其實是**昨天**那份配額的尾巴。早上的工作永遠在吃剩菜。
2. **單價極不對稱**,而排程對此毫無感覺:
   `videos.list` 1 / `videos.update` 50 / `captions.insert` 400 /
   **`captions.update` 450** / **`videos.insert` 1600**。
   最大兇手是字幕重傳:12 支 × 450 = **5,400,一支腳本吃掉半天配額**。

## 設計
掛在 `daily_publish.get_service()` 這個**唯一的**建構點上,用 monkeypatch 攔
`HttpRequest.execute()`,依 URI 路徑 + HTTP method 查價。好處是**所有腳本自動被計量**,
不必逐一改呼叫端(改呼叫端一定會漏,而漏掉的那支就是下次吃光配額的那支)。

帳本以**太平洋日期**分桶(跟配額重置對齊,不是台北日曆日)。

## 執法(預設關閉)
`YT_QUOTA_ENFORCE=1` 才會在超過預算時擋下呼叫。預設只記帳不擋——價目表是照官方文件寫的,
但在拿真實一天的資料驗證它之前就拿它去擋人,等於用一張沒對過帳的表去停產線。
先觀測、後執法。超過 80% 會推 ntfy 提醒。

用法:
  python scripts/quota_meter.py              # 看今天(太平洋日)花了多少、花在哪
  python scripts/quota_meter.py --days 7     # 看近 7 個配額日
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STATE = ROOT / "STUDIO" / "quota_meter.json"
DAILY_LIMIT = int(os.environ.get("YT_QUOTA_LIMIT", "10000"))
WARN_AT = float(os.environ.get("YT_QUOTA_WARN", "0.80"))
ENFORCE = os.environ.get("YT_QUOTA_ENFORCE", "") == "1"
# 這個 process 必須**留給後面更重要的工作**多少 units。預設 0 = 不留(行為完全不變),
# 由 cron 行逐個 job 設定 opt-in。設計理由見下面 _execute 的註解。
RESERVE = int(os.environ.get("YT_QUOTA_RESERVE", "0"))


class QuotaExhausted(RuntimeError):
    """預算用完(只有 YT_QUOTA_ENFORCE=1 時才會丟)。"""


# ── 價目表(官方 Quota Calculator;沒列到的一律當 1,寫進 unknown 供事後補) ──────────
# key = (資源路徑, HTTP method)。路徑取 /youtube/v3/ 之後那一段。
_COST = {
    ("videos", "GET"): 1,
    ("videos", "PUT"): 50,
    ("videos", "POST"): 1600,
    ("videos/rate", "POST"): 50,
    ("captions", "GET"): 50,
    ("captions", "POST"): 400,
    ("captions", "PUT"): 450,
    ("captions", "DELETE"): 50,
    ("thumbnails/set", "POST"): 50,
    ("playlists", "GET"): 1,
    ("playlists", "POST"): 50,
    ("playlists", "PUT"): 50,
    ("playlists", "DELETE"): 50,
    ("playlistItems", "GET"): 1,
    ("playlistItems", "POST"): 50,
    ("playlistItems", "PUT"): 50,
    ("playlistItems", "DELETE"): 50,
    ("channelSections", "GET"): 1,
    ("channelSections", "POST"): 50,
    ("channelSections", "PUT"): 50,
    ("channelSections", "DELETE"): 50,
    ("channels", "GET"): 1,
    ("channels", "PUT"): 50,
    ("subscriptions", "GET"): 1,
    ("commentThreads", "GET"): 1,
    ("commentThreads", "POST"): 50,
    ("comments", "GET"): 1,
    ("comments", "POST"): 50,
    ("comments", "PUT"): 50,
    ("comments", "DELETE"): 50,
    ("search", "GET"): 100,          # ← 一次 100,是最容易無聲吃光配額的端點
    ("videoCategories", "GET"): 1,
    ("i18nLanguages", "GET"): 1,
}


def _pacific_date(now_utc=None):
    """配額重置對齊的日期＝**太平洋日期**(不是台北日曆日)。

    優先用 zoneinfo;Windows 上常常沒裝 tzdata 會直接丟例外,所以備援自己算美國 DST
    (3 月第 2 個週日 02:00 起 UTC-7,11 月第 1 個週日 02:00 止,其餘 UTC-8)。"""
    u = now_utc or _dt.datetime.now(_dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return u.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # noqa: BLE001
        pass

    def _nth_sunday(year, month, nth):
        d = _dt.date(year, month, 1)
        d += _dt.timedelta(days=(6 - d.weekday()) % 7)      # 該月第一個週日
        return d + _dt.timedelta(days=7 * (nth - 1))

    y = u.year
    start = _dt.datetime.combine(_nth_sunday(y, 3, 2), _dt.time(10), _dt.timezone.utc)   # 02:00 PST
    end = _dt.datetime.combine(_nth_sunday(y, 11, 1), _dt.time(9), _dt.timezone.utc)     # 02:00 PDT
    off = -7 if start <= u < end else -8
    return (u + _dt.timedelta(hours=off)).date().isoformat()


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"days": {}}


def _save(d):
    try:
        import studio_common as sc
        sc.save_json_atomic(STATE, d)
    except Exception:  # noqa: BLE001
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def cost_of(uri, method):
    """依 URI + method 查價。回 (op 名稱, units)。查不到回 (op, 1) 並標成 unknown。"""
    from urllib.parse import urlparse
    u = urlparse(uri or "")
    path = (u.path or "").strip("/")
    if "youtubeanalytics" in (u.netloc or "") or path.startswith("v2/reports"):
        return ("analytics(獨立配額)", 0)      # Analytics 是**另一份**配額,不吃 Data API
    if "/youtube/v3/" in "/" + path:
        res = path.split("youtube/v3/", 1)[1]
    else:
        res = path
    m = (method or "GET").upper()
    if (res, m) in _COST:
        return (f"{res}.{m.lower()}", _COST[(res, m)])
    head = res.split("/")[0]
    if (head, m) in _COST:
        return (f"{head}.{m.lower()}", _COST[(head, m)])
    return (f"unknown:{res}.{m.lower()}", 1)


def record(op, units):
    day = _pacific_date()
    d = _load()
    b = d.setdefault("days", {}).setdefault(day, {"spent": 0, "calls": 0, "by_op": {}})
    b["spent"] = int(b.get("spent", 0)) + int(units)
    b["calls"] = int(b.get("calls", 0)) + 1
    o = b.setdefault("by_op", {}).setdefault(op, {"units": 0, "calls": 0})
    o["units"] += int(units)
    o["calls"] += 1
    b["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    # 只留最近 30 個配額日,免得帳本無限長
    if len(d["days"]) > 30:
        for k in sorted(d["days"])[:-30]:
            d["days"].pop(k, None)
    _save(d)
    return b["spent"]


def spent(day=None):
    return int(_load().get("days", {}).get(day or _pacific_date(), {}).get("spent", 0))


def remaining(day=None):
    return max(0, DAILY_LIMIT - spent(day))


_warned = {"sent": False}


def _maybe_warn(total):
    if _warned["sent"] or total < DAILY_LIMIT * WARN_AT:
        return
    _warned["sent"] = True
    try:
        from notify import push
        push("YT 配額警戒",
             f"已用 {total}/{DAILY_LIMIT} units("
             f"{total * 100 // max(DAILY_LIMIT, 1)}%),配額日 {_pacific_date()}")
    except Exception:  # noqa: BLE001
        pass
    print(f"[quota] ⚠️ 已用 {total}/{DAILY_LIMIT}", file=sys.stderr)


def install(service=None):
    """把計量掛上去。回傳同一個 service(方便 `return install(build(...))` 直接串)。

    攔的是 `HttpRequest.execute` 這個**類別方法**,所以同一個 process 裡任何後續建出來的
    request 都會被算到——包含 googleapiclient 內部自己發的分頁請求。只掛一次(冪等)。"""
    try:
        from googleapiclient.http import HttpRequest
    except Exception:  # noqa: BLE001
        return service
    if getattr(HttpRequest, "_quota_metered", False):
        return service
    _orig = HttpRequest.execute

    def _execute(self, *a, **kw):
        op, units = cost_of(getattr(self, "uri", ""), getattr(self, "method", "GET"))
        # 🔴 **預留額度**:配額日的順序原本是反的——補件工作排 15:25~16:25 先把配額吃光,
        # 主線發布排 18:30 在後面餓死。而發布才是成長引擎(搜尋佔位),補件是修存量。
        # 作法刻意做在這裡、不是逐一改補件腳本的迴圈:那些腳本**本來就都**用
        #   `if "quota" in str(exc).lower(): break`
        # 收尾(冪等、下次接著跑),所以只要丟一個訊息含 "quota" 的例外,它們就會自己
        # 乾淨地停在額度線上——零迴圈改動,也不會有哪支腳本被漏改。
        # 預設 RESERVE=0(行為不變),由 cron 逐行 opt-in:
        #   15:25 的補件 → YT_QUOTA_RESERVE=9600(留給當天 18:30 的 5 支 + 隔天 1 支)
        #   23:00 的補件 → YT_QUOTA_RESERVE=1600(當天發布已完成,只需留隔天那 1 支)
        if units and RESERVE and remaining() - units < RESERVE:
            raise QuotaExhausted(
                f"quota reserve:{op} 需 {units} units,今日剩 {remaining()},"
                f"但要留 {RESERVE} 給發布 → 停在額度線上(冪等,下個配額日接著跑)")
        if units and ENFORCE and units > remaining():
            raise QuotaExhausted(f"quota exhausted:{op} 需 {units},今日剩 {remaining()}")
        try:
            return _orig(self, *a, **kw)
        finally:
            # 即使呼叫失敗(403/500)配額**照樣被扣**,所以記在 finally 而不是成功之後。
            if units:
                _maybe_warn(record(op, units))

    HttpRequest.execute = _execute
    HttpRequest._quota_metered = True
    return service


def _report(days=1):
    d = _load().get("days", {})
    for day in sorted(d)[-days:]:
        b = d[day]
        pct = b["spent"] * 100 // max(DAILY_LIMIT, 1)
        print(f"\n配額日 {day}(太平洋日;台北 15:00~16:00 換日)  "
              f"{b['spent']}/{DAILY_LIMIT} units = {pct}%  呼叫 {b.get('calls',0)} 次")
        for op, o in sorted(b.get("by_op", {}).items(), key=lambda kv: -kv[1]["units"])[:14]:
            print(f"   {o['units']:>6} units  ×{o['calls']:<4} {op}")
    if not d:
        print("還沒有任何記錄(計量器剛裝上,下一次 API 呼叫才會開始記帳)。")
        print(f"目前配額日:{_pacific_date()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()
    _report(args.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
