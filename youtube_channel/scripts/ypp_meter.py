# -*- coding: utf-8 -*-
"""ypp_meter.py — YPP 兩道閘門的每日真實進度計量（append-only）。

## 為什麼需要這支

2026-08-25 盤點發現：**主頻道的 YPP 進度沒有可信的單一來源。**
- memory 兩份互相衝突（`yt-ypp-gap-anatomy` 寫 430/4000，被 `yt-search-capture-engine`
  的「月時數 13→695」標為推翻）
- 整個 repo `grep estimatedMinutesWatched` 零命中 → **從來沒有落檔過**

於是「還差多遠」這個決定要不要繼續全押的關鍵問題，沒有人能回答。這支負責回答它。

## ⚠️ 這是替身值，不是官方 YPP 計數

YPP 的「有效公開觀看時數」是 Google 內部計算的，唯一權威在 YouTube Studio > 營利。
本檔用 Analytics API 的 `estimatedMinutesWatched` 當替身，兩者會有差距
（官方會扣掉無效流量、非公開影片等）。

**照 memory `yt-search-capture-engine-2026-08` 的教訓：拿替身值分析前先驗替身等不等於真值。**
所以輸出一律標明這是估算，且建議每隔一段時間人工比對一次 Studio 的官方數字。

## 三個必須避開的坑（都是踩過的）

1. **靜默壞資料**（memory `yt-quota-partial-failure-silent-bad-data`）：
   gather_stats 曾經把 403 用 except 吞掉，`len(rows)` 被當成頻道影片數寫進快照，
   同型壞值重複三次沒人發現。→ 本檔 **fail-closed**：任何欄位拿不到就寫 null +
   記錄失敗原因，**絕不寫一個看起來正常的數字**。
2. **Shorts 灌水**（memory `yt-shorts-not-converting-2026-08`）：
   Shorts 觀看**不計入** YPP 的 4000 小時（政策事實）。拿總時數當進度會高估＝畫大餅。
   → 閘門用 `creatorContentType==videoOnDemand`，總量另外記供對照。
3. **Analytics 延遲**（memory `yt-analytics-lag-false-alarm`）：
   延遲 2~4 天。→ 本檔實測資料到哪一天並記進每筆紀錄，斜率計算用實際天數不用日曆天。

## 配額

Analytics API 有**自己的配額池**，不吃 Data API 的 10,000/天
（memory `yt-api-quota-structural-overrun` 講的超支是 Data API）。
本檔只有訂閱數走 Data API `channels.list`（**單價 1**），由 quota_meter 自動記帳。

## 用法

    python scripts/ypp_meter.py            # 量測 + 落檔 + 印進度
    python scripts/ypp_meter.py --show     # 只讀歷史算斜率，不打任何 API
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "STUDIO" / "ypp_meter.jsonl"

# YPP 門檻（政策事實）
GATE_HOURS = 4000        # 近 365 天有效公開觀看時數（長片路徑）
GATE_SUBS = 1000         # 訂閱者
GATE_SHORTS_VIEWS = 10_000_000   # 近 90 天 Shorts 觀看（另一條替代路徑）

TW = timezone(timedelta(hours=8))


def tw_today() -> date:
    return datetime.now(TW).date()


# ────────────────────────── 量測 ──────────────────────────

def _minutes(days: int, content_type: str | None):
    """回傳 (minutes, views) 或 (None, None)。None = 拿不到，呼叫端必須當失敗處理。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import yt_analytics
    except Exception as e:  # noqa: BLE001
        return None, None, f"import yt_analytics failed: {e}"
    # 繞過當日快取：計量器要的是當下真值，不是別的部門今天早上抓的
    os.environ["YA_NO_CACHE"] = "1"
    try:
        r = yt_analytics.channel_summary(days=days, content_type=content_type)
    except Exception as e:  # noqa: BLE001
        return None, None, f"channel_summary raised: {e}"
    if r is None:
        return None, None, "channel_summary returned None (無 token / API 失敗)"
    return r.get("minutes"), r.get("views"), None


def _data_through():
    """實測 Analytics 資料到哪一天（延遲 2~4 天）。回傳 ISO 日期或 None。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import yt_analytics
        ya = yt_analytics._service()
        if ya is None:
            return None, "無 analytics token"
        end = tw_today()
        start = end - timedelta(days=12)
        r = ya.reports().query(
            ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
            metrics="views", dimensions="day", sort="day",
        ).execute()
        rows = r.get("rows") or []
        if not rows:
            return None, "近 12 天無 day 維度資料"
        return rows[-1][0], None
    except Exception as e:  # noqa: BLE001
        return None, f"data_through 查詢失敗: {e}"


def _subscribers():
    """走 Data API channels.list（單價 1，quota_meter 自動記帳）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import daily_publish
        # ⚠️ get_service() 在 token 失效時會呼叫 flow.run_local_server()——那會**開瀏覽器
        #    並無限期阻塞**，在 cron 裡等於這支永遠不結束。所以先自己確認 token 可用，
        #    不可用就 fail-closed 回報，絕不讓它走進互動流程。
        if not daily_publish.TOKEN.exists():
            return None, None, f"token 不存在: {daily_publish.TOKEN}（跑 auth 流程後再試）"
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        cr = Credentials.from_authorized_user_file(
            str(daily_publish.TOKEN), daily_publish.SCOPES)
        if not cr.valid:
            if cr.expired and cr.refresh_token:
                cr.refresh(Request())      # 靜默續期，不需要人
            else:
                return None, None, "token 失效且無 refresh_token（需人工重新授權）"
        yt = daily_publish.get_service()
        r = yt.channels().list(part="statistics", mine=True).execute()
        items = r.get("items") or []
        if not items:
            return None, None, "channels.list 回傳空 items"
        st = items[0].get("statistics", {})
        subs = st.get("subscriberCount")
        vids = st.get("videoCount")
        if subs is None:
            return None, None, "statistics 無 subscriberCount（可能被隱藏）"
        return int(subs), (int(vids) if vids is not None else None), None
    except Exception as e:  # noqa: BLE001
        return None, None, f"channels.list 失敗: {e}"


def measure() -> dict:
    """量一次。任何欄位失敗 → 該欄位 None 並記進 errors，絕不編造。"""
    errors: list[str] = []
    rec: dict = {
        "ts": datetime.now(TW).isoformat(timespec="seconds"),
        "tw_date": tw_today().isoformat(),
    }

    through, err = _data_through()
    rec["data_through"] = through
    if err:
        errors.append(err)

    # 閘門用長片；總量與 Shorts 另外記供對照（別拿總量當進度＝畫大餅）
    for key, ctype, days in (
        ("longform_minutes_365", "videoOnDemand", 365),
        ("total_minutes_365", None, 365),
        ("shorts_views_90", "shorts", 90),
    ):
        mins, views, err = _minutes(days, ctype)
        if err:
            errors.append(f"{key}: {err}")
        if key == "shorts_views_90":
            rec[key] = views
        else:
            rec[key] = mins

    subs, vids, err = _subscribers()
    rec["subscribers"] = subs
    rec["video_count"] = vids
    if err:
        errors.append(err)

    rec["errors"] = errors
    # fail-closed 標記：任何一個閘門欄位缺失就標 partial，下游看到 partial 必須拒用
    rec["partial"] = any(
        rec.get(k) is None for k in ("longform_minutes_365", "subscribers")
    )
    return rec


# ────────────────────────── 落檔 / 讀取 ──────────────────────────

def append(rec: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


# ────────────────────────── 報告 ──────────────────────────

def _fmt_eta(per_day: float, remaining: float) -> str:
    if per_day <= 0:
        return "不會到達（目前斜率 ≤ 0）"
    days = remaining / per_day
    return f"約 {days:.0f} 天（{days/30.4:.1f} 個月）"


def report(recs: list[dict]) -> str:
    usable = [r for r in recs if not r.get("partial")]
    lines = ["=" * 62, "YPP 進度計量（⚠️ Analytics 估算值，非官方 YPP 計數）", "=" * 62]

    if not usable:
        lines.append("尚無可用紀錄（全部 partial 或空）。")
        if recs:
            lines.append(f"最後一筆的錯誤：{recs[-1].get('errors')}")
        return "\n".join(lines)

    cur = usable[-1]
    hrs = cur["longform_minutes_365"] / 60.0
    subs = cur["subscribers"]
    lines.append(f"資料日期      : {cur['tw_date']}（Analytics 資料到 {cur.get('data_through')}）")
    lines.append("")
    lines.append(f"長片觀看時數  : {hrs:>10,.0f} / {GATE_HOURS:,} 小時  "
                 f"({hrs/GATE_HOURS*100:5.1f}%)  還差 {GATE_HOURS-hrs:,.0f}")
    lines.append(f"訂閱者        : {subs:>10,} / {GATE_SUBS:,} 位      "
                 f"({subs/GATE_SUBS*100:5.1f}%)  還差 {GATE_SUBS-subs:,}")

    tot = cur.get("total_minutes_365")
    if tot:
        inflate = (tot / cur["longform_minutes_365"] - 1) * 100 if cur["longform_minutes_365"] else 0
        lines.append(f"（對照）總時數: {tot/60:>10,.0f} 小時 — 拿這個當進度會高估 {inflate:.0f}%")
    sv = cur.get("shorts_views_90")
    if sv is not None:
        lines.append(f"（對照）Shorts: {sv:>10,} / {GATE_SHORTS_VIEWS:,} 觀看（90天，替代路徑）")

    # 斜率：需要兩筆且間隔夠久才有意義
    lines.append("")
    if len(usable) < 2:
        lines.append("斜率：紀錄不足（需 ≥2 筆）。再跑幾天就會有 ETA。")
    else:
        first = usable[0]
        d0 = date.fromisoformat(first["tw_date"])
        d1 = date.fromisoformat(cur["tw_date"])
        span = (d1 - d0).days
        if span < 7:
            lines.append(f"斜率：觀測期只有 {span} 天，太短不算 ETA（≥7 天才算）。")
        else:
            dh = (cur["longform_minutes_365"] - first["longform_minutes_365"]) / 60.0
            ds = cur["subscribers"] - first["subscribers"]
            lines.append(f"觀測期 {span} 天：時數 +{dh:,.0f} 小時、訂閱 +{ds:,} 位")
            lines.append(f"  時數 ETA : {_fmt_eta(dh/span, GATE_HOURS-hrs)}")
            lines.append(f"  訂閱 ETA : {_fmt_eta(ds/span, GATE_SUBS-subs)}")
            lines.append("  → **兩道閘門要同時過**，看比較慢的那個。")

    skipped = len(recs) - len(usable)
    if skipped:
        lines.append("")
        lines.append(f"⚠️ 有 {skipped} 筆 partial 紀錄被排除（資料不完整，不參與計算）。")
    return "\n".join(lines)


def main() -> int:
    # Windows 主控台預設 cp950，印不出 ⚠️ 這類字元會直接 UnicodeEncodeError 中止。
    # cron 的 stdout 也走同一條，所以在入口一次修好。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    if "--show" in sys.argv:
        print(report(load()))
        return 0

    rec = measure()
    append(rec)
    if rec["partial"]:
        print("⚠️ 本次量測 partial（資料不完整），已如實落檔但不參與斜率計算：")
        for e in rec["errors"]:
            print("   -", e)
        print()
    print(report(load()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
