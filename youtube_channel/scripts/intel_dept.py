#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intel_dept.py — 【⑯ 競品情報部】盯同類頻道在紅什麼。

用 YouTube Search API 搜量化/網格/Pionex/定投等關鍵字 → 找近期高觀看競品影片 →
抽出標題公式與熱度，產情報報告餵給 ③靈感／⑪決策。誠實：search 耗 quota，唯讀。
輸出：STUDIO/REPORTS/{date}_競品情報.md ＋ STUDIO/intel.json
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"; ORDERS = STUDIO / "production_orders.json"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass

DEFAULT_KW = ["網格交易", "Pionex 教學", "定投策略", "量化交易", "加密貨幣 被動收入", "網格機器人"]


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def main() -> int:
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2
    # 關鍵字：優先用決策部門的偏好
    kws = list(DEFAULT_KW)
    try:
        if ORDERS.exists():
            pk = json.loads(ORDERS.read_text(encoding="utf-8")).get("preferred_keywords") or []
            kws = (pk + kws)[:8]
    except Exception:
        pass
    log_ops("競品情報", f"搜尋 {len(kws)} 組關鍵字…")
    seen, vids = set(), []
    for kw in kws[:6]:
        try:
            r = yt.search().list(q=kw, part="snippet", type="video", order="viewCount",
                                 maxResults=8, relevanceLanguage="zh-Hant", regionCode="TW").execute()
            for it in r.get("items", []):
                vid = it["id"].get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    vids.append({"id": vid, "title": it["snippet"]["title"][:70],
                                 "channel": it["snippet"]["channelTitle"][:30], "kw": kw})
        except Exception as e:
            print(f"[warn] 搜尋「{kw}」失敗：{e}", file=sys.stderr)
    # 補觀看數
    ids = [v["id"] for v in vids][:50]
    stats = {}
    for i in range(0, len(ids), 50):
        try:
            rr = yt.videos().list(part="statistics", id=",".join(ids[i:i+50])).execute()
            for it in rr.get("items", []):
                stats[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0))
        except Exception:
            pass
    for v in vids:
        v["views"] = stats.get(v["id"], 0)
    vids.sort(key=lambda x: x["views"], reverse=True)
    top = vids[:15]
    date = tw_today()
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑯ 競品情報報告｜{date}", "",
         "> 同類頻道近期高觀看影片（依觀看排序）。誠實：YouTube Search 結果，唯讀、耗少量 quota。", "",
         "## 熱門競品 Top（標題＝可借鏡的角度/鉤子）"]
    for v in top:
        L.append(f"- 👁 {v['views']:>8,}｜{v['title']}　—　@{v['channel']}（搜:{v['kw']}）")
    if not top:
        L.append("-（本次未取得資料，可能 quota 或網路問題）")
    # 簡單情報洞察
    L += ["", "## 情報洞察（規則式）"]
    if top:
        avg = sum(v["views"] for v in top) // max(1, len(top))
        L.append(f"- 競品前段觀看均值約 {avg:,}，可見此題材有量；我們衝量＋差異化（誠實實測角度）切入。")
        L.append("- 借鏡高觀看標題的『數字/反直覺/痛點』結構，但內容守誠信鐵則（不喊單、不保證）。")
    (REPORTS / f"{date}_競品情報.md").write_text("\n".join(L), encoding="utf-8")
    (STUDIO / "intel.json").write_text(json.dumps(
        {"date": date, "top": top}, ensure_ascii=False, indent=2), encoding="utf-8")
    log_ops("競品情報", f"完成 競品 {len(top)} 支 → {date}_競品情報.md")
    print(f"[ok] 競品情報完成：收集 {len(top)} 支競品影片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
