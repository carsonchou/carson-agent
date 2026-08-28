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
# 🔴 2026-08-28:實測撞牆點 **19,645**(08-27 那天花到這裡開始被拒,而且被拒了 935 次
# / 45,491 units —— 撞牆後所有排程還在照跑,每次都是白打)。
# 原本寫 10000 是**猜的**,而且比真值低一倍 → 預留額度用它去算,結果是
# 「補件工作被我自己的假天花板擋死,而真配額還有一半沒用」。
# 這裡改成實測值當預設;`effective_limit()` 仍會用帳本推出來的上下界覆蓋它,
# 所以之後 YouTube 若調整配額,不必再改這個常數。
DAILY_LIMIT = int(os.environ.get("YT_QUOTA_LIMIT", "19645"))
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
    ("videos", "DELETE"): 50,          # 2026-08-25 補:原本落到 unknown 只記 1
    ("videos/rate", "POST"): 50,
    ("channelBanners/insert", "POST"): 50,   # 2026-08-25 補:原本連 head fallback 都接不到
    ("channelBanners", "POST"): 50,
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
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            # 🔴 這一層絕對不能省。`_charge_once` 是在 `_orig_next` **之前**呼叫的,
            # 也就是說寫檔失敗會讓**影片連傳都沒傳出去**;一般呼叫則是在 finally 裡炸,
            # 例外會取代正常 return,API 明明成功了呼叫端卻收到錯誤。
            # 計量器是純觀測元件,卻因為 b55669b 攔了 next_chunk 而落在上傳的前置關鍵路徑上。
            # 記不到帳最多是帳本少一筆;讓發布停下來是完全不成比例的代價。
            pass


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
    # captions/{id} 的 GET = **下載字幕**,官方 200,不是 captions.list 的 50。
    # 必須擋在 head fallback 之前:否則會撿到 ("captions","GET")=50,
    # 那是一個「看起來合理的錯價」,比記成 unknown 更難被發現。
    if res.startswith("captions/") and m == "GET":
        return ("captions.download", 200)
    head = res.split("/")[0]
    if (head, m) in _COST:
        return (f"{head}.{m.lower()}", _COST[(head, m)])
    return (f"unknown:{res}.{m.lower()}", 1)


_HTTP2API = {"GET": "list", "POST": "insert", "PUT": "update", "DELETE": "delete"}


def audit_tables():
    """跟 quota_budget.COST 對帳,回傳不一致清單 [(api_method, meter價, budget價)]。

    兩張表刻意不合併(key 空間不同:這裡是 HTTP 路徑+動詞,那裡是官方 API method 名),
    但**必須對得起來**——價格分歧會讓「事前估」與「事後量」永遠兜不攏,
    而那正是本專案踩過的「同一件事兩份實作」事故的形狀。"""
    try:
        import quota_budget
        b = dict(quota_budget.COST)
    except Exception:  # noqa: BLE001
        return []
    diffs = []
    for (res, m), units in _COST.items():
        api = _HTTP2API.get(m, m.lower())
        if res.endswith("/set"):
            name = res.replace("/", ".")
        elif res.endswith("/insert"):
            name = res.replace("/", ".")
        elif res.endswith("/rate"):
            name = res.replace("/", ".")
        else:
            name = f"{res}.{api}"
        if name in b and b[name] != units:
            diffs.append((name, units, b[name]))
    diffs.append(("captions.download", 200, b.get("captions.download")))
    return [d for d in diffs if d[2] is not None and d[1] != d[2]]


def _is_quota_rejected(exc):
    """這次失敗是不是「配額已用罄,請求被拒絕」?

    🔴 2026-08-26 修:原本記在 `finally`,理由寫「403 照樣扣配額」——那對**一般**失敗
    (500、逾時、權限錯)是對的,對 `quotaExceeded` 則是**錯的**:配額已經沒了,
    請求根本沒被執行,不會再扣。而這類失敗在配額用罄後會**大量**發生
    (實測 job_stderr 裡 463 次),全部被當成消耗記進帳本 →
    08-25 記到 18,914/10,000 = 189%,看起來像「上限其實有 18,914」,
    但那是被失敗呼叫灌出來的。差點拿這個數字去推翻「上限 10,000」。
    通則:**量一個東西之前,先確認你量的是不是它**。"""
    t = str(exc)
    return "quotaExceeded" in t or "exceeded your" in t and "quota" in t


def record(op, units, rejected=False):
    """rejected=True:配額用罄被拒的呼叫 —— 記進獨立的桶,**不計入 spent**。
    帳本要能回答「今天真的花了多少」,而不是「今天發了幾個請求」。"""
    day = _pacific_date()
    d = _load()
    b = d.setdefault("days", {}).setdefault(day, {"spent": 0, "calls": 0, "by_op": {}})
    if rejected:
        b["rejected_units"] = int(b.get("rejected_units", 0)) + int(units)
        b["rejected_calls"] = int(b.get("rejected_calls", 0)) + 1
        b["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
        _save(d)
        return int(b.get("spent", 0))
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


def _unrecord(op, units):
    """把一筆已記進 spent 的搬到 rejected 桶(分段上傳只能先收費後才知道結果)。"""
    day = _pacific_date()
    d = _load()
    b = d.get("days", {}).get(day)
    if not b:
        return
    b["spent"] = max(0, int(b.get("spent", 0)) - int(units))
    b["calls"] = max(0, int(b.get("calls", 0)) - 1)
    o = b.get("by_op", {}).get(op)
    if o:
        o["units"] = max(0, o.get("units", 0) - int(units))
        o["calls"] = max(0, o.get("calls", 0) - 1)
    b["rejected_units"] = int(b.get("rejected_units", 0)) + int(units)
    b["rejected_calls"] = int(b.get("rejected_calls", 0)) + 1
    _save(d)


def observed():
    """回 (floor, ceiling):實測推出來的每日上限區間。

    · floor   = **曾經成功花到的最高值**(下界:至少有這麼多)
    · ceiling = **第一次被拒時的花費水位**(上界:大約就在這裡撞牆)
    兩者都可能是 None(還沒觀測到)。

    🔴 2026-08-26 為什麼要有這支:`DAILY_LIMIT` 原本寫死 10000,而那個數字是**猜的**
    ——memory 裡兩份紀錄互相矛盾(一份說 10,000、一份說實測 ≥18,000)。
    我拿它算 `remaining()`,再拿 `remaining()` 去擋補件工作,整條推論建立在一個
    沒被驗證的常數上。實測結果:08-26 一天花掉 **11,222 units 全部成功、真 403 只有 1 次**,
    而同一天我的預留額度擋下 10 次 —— **擋人的是我的假天花板,不是 YouTube。**
    通則(這個 session 第四次):**拿一個數字去做決策之前,先確認它是量出來的還是猜的。**"""
    d = _load()
    floor = ceil = None
    for day, b in (d.get("days") or {}).items():
        # 標記不可信的日子不能拿來校準:2026-08-25 是在「被拒的呼叫也算進 spent」
        # 那版計量下記的 18,914,把它當下界會讓天花板比真值高一倍。
        # 自我校準吃到污染資料,比寫死一個猜的常數更危險——它看起來像實測。
        if b.get("unreliable"):
            continue
        sp = int(b.get("spent", 0) or 0)
        if sp and (floor is None or sp > floor):
            floor = sp
        # 那天有被拒 → 撞牆點大約就是當天的成功花費(被拒的不算消耗)
        if int(b.get("rejected_calls", 0) or 0) and sp:
            ceil = sp if ceil is None else min(ceil, sp)
    return floor, ceil


def effective_limit():
    """實際拿來算 remaining() 的上限。

    優先序:①觀測到的撞牆點(最緊的上界) ②曾成功花到的最高值(下界,至少有這麼多)
    ③設定值。**永遠不會低於實測到的下界** —— 用一個比實測還低的天花板去擋人,
    正是 08-26 那天發生的事。"""
    floor, ceil = observed()
    if ceil:
        return ceil
    if floor and floor > DAILY_LIMIT:
        return floor
    return DAILY_LIMIT


def spent(day=None):
    return int(_load().get("days", {}).get(day or _pacific_date(), {}).get("spent", 0))


def remaining(day=None):
    return max(0, effective_limit() - spent(day))


_warned = {"sent": False}


def _maybe_warn(total):
    if _warned["sent"] or total < effective_limit() * WARN_AT:
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
        if getattr(self, "_quota_charged", False):
            return _orig(self, *a, **kw)      # 同一個 request 已由 next_chunk 收過費
        self._quota_charged = True
        try:
            r = _orig(self, *a, **kw)
        except Exception as exc:                      # noqa: BLE001
            # 一般失敗(500/逾時/權限)配額照樣被扣 → 記進 spent;
            # 但 quotaExceeded 是「配額已經沒了所以拒收」,不會再扣 → 記進 rejected 桶。
            if units:
                _maybe_warn(record(op, units, rejected=_is_quota_rejected(exc)))
            raise
        if units:
            _maybe_warn(record(op, units))
        return r

    HttpRequest.execute = _execute

    # 🔴 分段上傳(resumable)**不會走 execute()**,走的是 `next_chunk()` 迴圈。
    # daily_publish 上傳影片正是這條路(`MediaFileUpload(resumable=True, chunksize=4MB)`
    # + `while ...: req.next_chunk()`),而 videos.insert 是 **1,600 units、全排程最大宗**
    # (一天 6 支 = 9,600)。只攔 execute 的話,帳上會顯示發布花了 0,
    # 補件工作就會以為額度還很多 —— 整個預留機制反而變成幫兇。
    # 一次上傳會呼叫 next_chunk 很多次(每 4MB 一次),所以**只在第一次收費**,
    # 用 request 物件上的旗標記住(配額是按 request 算,不是按 chunk 算)。
    _orig_next = HttpRequest.next_chunk

    def _charge_once(self):
        # ⚠️ 順序有意義,別動:**先檢查 → 通過才設旗標 → 才記帳**。
        # 旗標若設在 raise 之前,同一個 request 被重試(或呼叫端 catch 後重跑)就會被當成
        # 「已收過費」直接放行 = 一次完全沒記帳的 1600 units 上傳。
        if getattr(self, "_quota_charged", False):
            return
        op, units = cost_of(getattr(self, "uri", ""), getattr(self, "method", "GET"))
        if units and RESERVE and remaining() - units < RESERVE:
            raise QuotaExhausted(
                f"quota reserve:{op} 需 {units} units,今日剩 {remaining()},"
                f"但要留 {RESERVE} 給發布 → 停在額度線上(冪等,下個配額日接著跑)")
        # ENFORCE 這道原本只寫在 `_execute` 裡 —— 而 resumable 上傳走的是這條路徑,
        # 等於「先觀測後執法」真的打開執法時,漏掉的正好是最大的那一筆。
        if units and ENFORCE and units > remaining():
            raise QuotaExhausted(f"quota exhausted:{op} 需 {units},今日剩 {remaining()}")
        self._quota_charged = True
        if units:
            _maybe_warn(record(op, units))

    def _next_chunk(self, *a, **kw):
        # 這裡是**先收費再上傳**(不能等結果,否則分段上傳每塊都要判一次)。
        # 若上傳因配額用罄被拒,把剛才記的那筆搬到 rejected 桶,別讓帳本灌水。
        _charge_once(self)
        try:
            return _orig_next(self, *a, **kw)
        except Exception as exc:                      # noqa: BLE001
            if _is_quota_rejected(exc):
                op, units = cost_of(getattr(self, "uri", ""), getattr(self, "method", "GET"))
                if units:
                    _unrecord(op, units)
            raise

    HttpRequest.next_chunk = _next_chunk
    HttpRequest._quota_metered = True
    return service


def _report(days=1):
    d = _load().get("days", {})
    for day in sorted(d)[-days:]:
        b = d[day]
        pct = b["spent"] * 100 // max(effective_limit(), 1)
        rj = b.get("rejected_units", 0)
        print(f"\n配額日 {day}(太平洋日;台北 15:00~16:00 換日)  "
              f"{b['spent']}/{effective_limit()} units = {pct}%  呼叫 {b.get('calls',0)} 次")
        if rj:
            print(f"   (另有 {rj} units / {b.get('rejected_calls',0)} 次因配額用罄被拒 —— "
                  f"**不計入實際消耗**,只代表撞牆後還在硬打)")
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
    d = audit_tables()
    if d:
        print("\n⚠️ 與 quota_budget.COST 價格不一致(事前估與事後量會永遠兜不攏,請修):")
        for name, a, b in d:
            print(f"   {name:<26} quota_meter={a}  quota_budget={b}")
    else:
        print("\n價目表與 quota_budget 對帳一致。")
    fl, ce = observed()
    _f = f"{fl:,}" if fl else "尚未觀測"
    _c = f"{ce:,}" if ce else "尚未觀測"
    print(f"\n每日上限:目前採用 {effective_limit():,}"
          f"(設定值 {DAILY_LIMIT:,} / 實測下界 {_f} / 撞牆點 {_c})")
    print("  ⚠️ 設定值是**猜的**;下界=曾經成功花到的最高值,撞牆點=第一次被拒時的水位。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
