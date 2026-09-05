#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""beachhead_tracker.py — 外部分發灘頭指標:每日記錄「非訂閱者來源」觀看。

## 為什麼(2026-08-13,memory yt-subscriber-feed-pollution)
解剖實測:頻道「爆款」觀看 88~96% 來自訂閱者 feed(157 人重複看)——外部分發≈0。
總觀看/總訂閱這類指標全被老訂戶污染;**頻道成長的唯一北極星=非訂閱者來源的觀看**
(搜尋+推薦+首頁+Shorts feed+外部)。本工具每日把它拆出來寫進 ops_log 與
STUDIO/beachhead_history.jsonl,讓每個 session/report 都看得到灘頭有沒有動。

唯讀 Analytics;fail-open(API 失敗只記警告,不影響任何產線)。

## 孿生檔(2026-09-05)
`yt_ch2/scripts/beachhead_tracker.py` 是本檔的舊版,逐字相同,**刻意沒有跟著改**:
副頻道已於 09-05 裁決收線(`docs/subchannel-verdict-2026-09-05.md`, bc7e2bce),
本機找不到它的 `STUDIO/beachhead_history.jsonl` 與 logs。
⇒ 兩支從今天起分岔。要拿 ch2 的資料做跨頻道比較時,**它的分鐘是「沒量」不是 0**。
(形狀同 memory `yt-duplicate-impl-gate-bypass`:同一段程式兩份,下一個人 grep 會拿到兩個答案。)
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "STUDIO" / "beachhead_history.jsonl"

import yt_analytics as ya  # noqa: E402

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):
        pass


def main() -> int:
    svc = ya._service()
    if svc is None:
        print("[warn] analytics 不可用,跳過")
        return 0
    # Analytics 延遲 2~4 天:取「4 天前」單日做定錨(數據已穩),避免假警報(memory 教訓)
    day = (date.today() - timedelta(days=4)).isoformat()
    try:
        r = svc.reports().query(ids="channel==MINE", startDate=day, endDate=day,
                                dimensions="insightTrafficSourceType",
                                metrics="views,estimatedMinutesWatched",
                                sort="-views", maxResults=15).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 查詢失敗:{str(exc)[:100]}")
        return 0
    rows = r.get("rows") or []
    # 🔴 欄位順序守衛(2026-09-05)。x[1]=views 這個假設已經無聲地撐了 23 天;
    # x[2]=estimatedMinutesWatched 是這次才開始承重的,而它失效時完全沒有訊號
    # (兩個 metric 欄對調 → sources_minutes 會等於 sources、所有匯率變成 1.00,
    #  rc=0、jsonl 照寫、五個健康掃描判準一個都不響)。
    # 這段是照 09-05 實打一次 API 拿到的真實回應寫的,不是照文件憑空寫的:
    #   columnHeaders = [{"name":"insightTrafficSourceType","columnType":"DIMENSION",...},
    #                    {"name":"views","columnType":"METRIC","dataType":"INTEGER"},
    #                    {"name":"estimatedMinutesWatched","columnType":"METRIC","dataType":"INTEGER"}]
    _hdr = [h.get("name") if isinstance(h, dict) else None
            for h in (r.get("columnHeaders") or [])]
    _min_col_ok = len(_hdr) > 2 and _hdr[2] == "estimatedMinutesWatched"
    # 🔴 headers 對不上時不可以只把「分鐘」當可疑:同一份 headers 也是 x[1]=views 的唯一憑據。
    # 實測(獨立驗證 G5):兩個 metric 欄真的對調時,只守分鐘會照樣落盤 total=2987、
    # 寫出「非訂閱者觀看 2330/2987(78.0%)」——分鐘冒充觀看,而告警只講分鐘,
    # 主動把讀者的注意力導離出事的那一半,且冪等會把錯數字永久鎖死。
    # 但「拿不到 headers」和「headers 明講不是 views」要分開:前者沒有證據說 x[1] 錯了,
    # 硬性不落盤會賠掉本檔 23 天來唯一在做的事(fail-open);後者是正面反證,不能猜。
    _views_col_bad = len(_hdr) > 1 and _hdr[1] != "views"
    if rows and _views_col_bad:
        log_ops("灘頭指標", f"⚠️ {day} 觀看欄位對不上預期,本日不落盤(避免分鐘冒充觀看):{_hdr}")
        print(f"[warn] {day} columnHeaders 非預期,跳過:{_hdr}")
        return 0
    total = sum(x[1] for x in rows)
    sub = next((x[1] for x in rows if x[0] == "SUBSCRIBER"), 0)
    ext = total - sub
    detail = {x[0]: x[1] for x in rows if x[0] != "SUBSCRIBER"}
    # 🔴 2026-09-05:estimatedMinutesWatched 從 08-13 起就在查詢裡(metrics 第 2 欄),
    # 但落盤只讀 x[1](views),x[2] 從頭到尾沒被讀過——每天付錢拿了就扔。
    # 後果:分鐘/觀看的「匯率」無法用自家落盤資料驗證(09-05 三次量測 13.3x/9.6x/7.1x,
    # 數量級一致:一次 YT_SEARCH 觀看抵好幾次 SHORTS 觀看)。
    # 🔴 但 minutes_total **不等於 YPP 可計時數**:它含 SHORTS 那一列的分鐘,
    # 而 Shorts 不計入 4000 小時(memory yt-format-pivot-longform-2026-07)。
    # 要算 YPP 進度請從 sources_minutes 扣掉 SHORTS,或改用 long-form 過濾查詢。
    # ⚠️ 另:查詢是 sort=-views, maxResults=15,minutes_total 嚴格說是「觀看前 15 個來源」的和。
    # 實算 18 天:單日最多 11 個來源、歷來共出現 12 種,頭寸 4,目前不咬(偏低方向,砍的是尾巴)。
    # 舊列只有 2 欄時 _m() 回 0,不會炸;既有欄位一個都沒動,jsonl 向後相容。
    _bad_min = set()

    def _m(x):
        # x[2]=estimatedMinutesWatched。isinstance 守衛的理由:x[2] 從「取來就扔」變成
        # 「必須可加總」,第 3 欄若回 null/字串,sum() 會炸掉整支 —— 那會把本檔宣稱的
        # fail-open 收窄成 fail-closed(獨立驗證實測:x[2]=None 時改動前 rc=0、改動後 TypeError,
        # 且例外在包 API 的 try/except 之外,連觀看數那一半也一起沒了)。
        # 但「靜默記 0」本身也是病,所以踩到就記進 _bad_min,由 ops_log 顯性報出來。
        v = x[2] if (len(x) > 2 and _min_col_ok) else 0
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            if len(x) > 2:
                _bad_min.add(x[0])
            return 0
        return v

    mins_total = sum(_m(x) for x in rows)
    mins_sub = next((_m(x) for x in rows if x[0] == "SUBSCRIBER"), 0)
    detail_min = {x[0]: _m(x) for x in rows if x[0] != "SUBSCRIBER"}
    rec = {"date": day, "total": total, "subscriber": sub, "external": ext,
           "external_pct": round(ext / total * 100, 1) if total else 0.0,
           "sources": detail}
    # 分鐘四欄只在守衛通過時才放。守衛跳閘時**整組省略**,不放 0——
    # 「有鍵值為 0」和「真的看了 0 分鐘」在 jsonl 裡無法區分,而缺鍵可以。
    # 這也讓跳閘的列和 2026-09-06 之前那 18 列同形,讀取端一套 .get() 同時涵蓋兩者。
    if _min_col_ok:
        rec.update({"minutes_total": mins_total, "minutes_subscriber": mins_sub,
                    "minutes_external": mins_total - mins_sub,
                    "sources_minutes": detail_min})
    HIST.parent.mkdir(parents=True, exist_ok=True)
    # 冪等:同一天已記過就跳過(cron 重跑/補跑不會重覆)
    if HIST.exists():
        for ln in HIST.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(ln).get("date") == day:
                    print(f"[skip] {day} 已記錄")
                    return 0
            except Exception:  # noqa: BLE001
                continue
    with HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    top = "、".join(f"{k}:{v}" for k, v in sorted(detail.items(), key=lambda kv: -kv[1])[:3])
    # 分鐘/觀看的匯率直接寫進 log(前半段格式刻意不動,既有 grep 不會壞)。
    # ⚠️ 只有 top-3 非訂閱來源:不含 SUBSCRIBER、也不含第 4 名以後。
    # 要全量匯率還是得翻 jsonl 的 sources_minutes,log 這行是摘要不是帳。
    _head = f"{day} 非訂閱者觀看 {ext}/{total}({rec['external_pct']}%)｜{top}"
    if _min_col_ok:
        rate = "、".join(f"{k}:{(detail_min.get(k, 0) / v):.2f}" if v else f"{k}:—"
                        for k, v in sorted(detail.items(), key=lambda kv: -kv[1])[:3])
        log_ops("灘頭指標", _head + f"｜分鐘 {mins_total - mins_sub}/{mins_total}｜分鐘每觀看 {rate}")
    else:
        # 守衛跳閘的那天不要印「分鐘 0/0｜分鐘每觀看 …:0.00」——那和「量到 0」讀起來一樣。
        # 退回 08-13~09-05 的原格式(既有 grep 本來就吃這個)。
        log_ops("灘頭指標", _head)
    # 告警一律放在寫入之後(與冪等同側):否則補跑/手動 debug 每跑一次就多一條 ⚠️,
    # 而洗版的警報等於沒有警報(同 _llm_shim.py:25 的教訓)。實測連跑 3 次:舊寫法 3 條、現在 1 條。
    # 例外是上面 _views_col_bad 那條:那天沒有寫入、冪等不會 skip,所以它不會累積。
    if not _min_col_ok:
        log_ops("灘頭指標", f"⚠️ {day} 分鐘欄位對不上預期,本日省略分鐘四欄:{_hdr}")
    if _bad_min:
        log_ops("灘頭指標", f"⚠️ {day} 分鐘欄非數值,已當 0 計:{'、'.join(sorted(_bad_min))}")
    print(f"[ok] {day} 外部觀看 {ext}/{total} ({rec['external_pct']}%) → {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
