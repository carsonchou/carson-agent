#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analytics_recorrect.py — E2 低報校正確認(YouTube 官方 2026/6/30-7/7 觀看資料低報,官方正修)。

不另開會加打配額的重抓路徑(Carson 交代:別現在狂打 API)——northstar.py 本就每天 09:05 例行重抓
yt_analytics.channel_summary(近28天滾動),它的每日快取(STUDIO/analytics_cache,key 含當天日期)
本來就會在 YouTube 修好後的「下一次例行呼叫」自然拿到上修後的真值,不需要這支腳本主動打 API。

這支腳本純粹是唯讀確認 + 一次性通知:每天跑一次(見 deploy/crontab.txt),RECORRECT_AFTER 前
直接跳過(不讀檔不打 API,省資源);之後每天檢查「當天已由 northstar.py 例行產生好」的
STUDIO/northstar.json——一旦 UNRELIABLE_WINDOW(northstar.py 定義)已完全滾出 7d/28d 趨勢視窗
(trend.unreliable_window_excluded == 0),代表低報期的殘留影響已自然清除,推一次 ntfy 給 Carson
+ 寫 marker 檔案,之後永久跳過(idempotent,不會每天重複推播)。

用法:python scripts/analytics_recorrect.py(手動測試也安全,不會打 API)
"""
from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):  # noqa: ARG001
        pass

# 給 YouTube 官方修復留緩衝(低報窗官方自承結束於 2026/7/7,+1週保守值,可視官方公告調整)。
RECORRECT_AFTER = "2026-07-14"
MARKER = STUDIO / "analytics_recorrect_done.json"


def main() -> int:
    if MARKER.exists():
        print("[analytics_recorrect] 已確認過校正生效,略過(idempotent,不重複推播)")
        return 0
    today = date.today().isoformat()
    if today < RECORRECT_AFTER:
        print(f"[analytics_recorrect] 還沒到 {RECORRECT_AFTER},略過(不打 API、不做事)")
        return 0
    try:
        ns = json.loads((STUDIO / "northstar.json").read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[analytics_recorrect] northstar.json 讀不到,等下次例行(北極星 09:05)產出後再檢查:{e}")
        return 0
    tr = ns.get("trend", {}) or {}
    excluded = tr.get("unreliable_window_excluded") or 0
    if excluded > 0:
        print(f"[analytics_recorrect] 不可靠窗仍有 {excluded} 筆快照在 7d/28d 視窗內,尚未完全滾出,繼續等。"
              "northstar.py 每天例行重抓,YouTube 修好後下次例行呼叫會自然拿到上修真值,不需額外打 API。")
        return 0
    # 不可靠窗已完全滾出 7d/28d 視窗:低報期的殘留影響已自然清除,通知 Carson + 標記完成
    msg = ("校正確認:YouTube 官方低報窗(2026/6/30-7/7)已完全滾出 7d/28d 趨勢視窗,"
           "northstar/growth_agent 現在看到的是乾淨資料。可以把 northstar.py 的 UNRELIABLE_WINDOW_* "
           "常數與跳過邏輯、growth_agent.py 的 WINDOW_DECLINE_BUFFER_PCT 豁免整段移除了。")
    print(f"[analytics_recorrect] {msg}")
    log_ops("低報校正確認", msg)
    try:
        from notify import push
        push("量化阿森｜低報校正確認", msg[:190], tag="white_check_mark")
    except Exception as ex:  # noqa: BLE001
        print(f"[analytics_recorrect] ntfy 失敗:{ex}", file=sys.stderr)
    try:
        MARKER.write_text(json.dumps({"done": True, "confirmed_at": today}, ensure_ascii=False), encoding="utf-8")
    except Exception as ex:  # noqa: BLE001
        print(f"[analytics_recorrect] marker 寫入失敗(下次會重跑無害):{ex}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
