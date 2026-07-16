#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intel_dept.py — 【⑯ 競品情報部】用官方 YouTube Data API 看同類題材近期在紅什麼。

只做一件事：官方 search.list 找量化/網格/Pionex/定投等題材的高觀看影片 →
依觀看排序，產出「標題／頻道／觀看數」情報報告供選題參考。

⚠️ 2026-07-17 起：本部門不再下載、轉錄或儲存任何他人頻道的影片內容。
原「B 段自動深度學習」(yt-dlp 抓字幕／抓音訊 → Whisper 轉錄 → LLM 拆解 →
回寫 competitor_playbook.md／competitor_analysis.md) 已整段移除，連帶移除
已看清單 intel_seen.json。本檔現在只呼叫官方 API 的 search.list 與
videos.list 讀取公開 metadata（標題／頻道名／觀看數），不觸碰影片內容本身。
此限制是頻道存續紅線（API 專案停權＝全自動化停擺），請勿加回下載能力。

輸出：STUDIO/REPORTS/{date}_競品情報.md、STUDIO/intel.json
用法：python scripts/intel_dept.py [--no-learn]
"""
from __future__ import annotations
import argparse, json, sys
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

# 核心競品題材 + 鄰近題材（理財/ETF/被動收入/AI）。
# ── 小白/避雷/防詐關鍵字對齊 sc.PERSONA 軟性新定位，撈到「怕被割小白」向的角度。
# 注意：outlier_scan.py 也 import 這份 DEFAULT_KW，改動前先確認該處仍相容。
DEFAULT_KW = ["Vibe Coding 交易", "手搓 量化", "Python 自動交易", "用 AI 寫 交易程式",
              "Cursor 寫 策略", "ChatGPT 寫 量化", "程式交易 新手",
              "網格交易", "Pionex 教學", "派網 機器人", "定投策略", "DCA 定期定額", "量化交易",
              "加密貨幣 被動收入", "網格機器人", "資金費率 套利", "交易機器人 實測", "幣安 合約 教學",
              "ChatGPT 交易", "AI 量化 交易", "Python 量化", "回測 策略", "TradingView 策略",
              "加密貨幣 投資", "ETF 定投", "被動收入 投資", "技術分析 教學", "波段 當沖 教學",
              "穩定幣 理財", "套利 教學", "交易策略 回測",
              # 小白 × 避雷 × 防詐（新定位語彙）
              "交易機器人 詐騙", "自動交易 被割", "投資 避雷", "新手 投資 教學",
              "加密貨幣 詐騙 避雷", "量化 韭菜", "機器人 交易 該不該碰", "投資 新手 踩雷",
              # 台股搜尋詞（打通 outlier_scan→parasite_titles 台股寄生鏈；niche 已含「股/etf」放行，只缺搜尋詞）
              "台股 當沖", "0050 定期定額", "大盤 回測", "除權息 存股", "高股息 ETF", "台積電 回測"]

# 輕量情報固定參數（維持移除前 --no-learn 路徑的完全相同 quota 成本）：
# 6 組關鍵字 × search.list(100 units) = 600 units + videos.list 統計約 1-2 units。
KW_CAP, PER_KW, ORDER = 6, 8, "viewCount"


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def purge_stale_reports(days: int = 30) -> int:
    """刪除逾期的競品情報報告，回傳刪除數。

    YouTube API Services Developer Policies 要求儲存的 API 資料在 30 天內刷新或刪除。
    報告內含他人頻道的公開 metadata（標題/頻道/觀看數），屬受規範的 API 資料，逾期即刪。
    檔名為 YYYY-MM-DD_競品情報.md，ISO 日期可直接字串比較。
    """
    cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)).strftime("%Y-%m-%d")
    n = 0
    for p in REPORTS.glob("*_競品情報.md"):
        if p.name[:10] < cutoff:
            try:
                p.unlink(); n += 1
            except OSError:
                pass
    return n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="競品情報部：官方 YouTube API 輕量情報報告（不下載/不儲存他人影片內容）")
    ap.add_argument("--no-learn", action="store_true",
                    help="(已無作用，保留給既有排程相容)深度學習/下載能力已於 2026-07-17 移除，本檔恆為輕量情報")
    args = ap.parse_args()
    if args.no_learn:
        print("[info] --no-learn 已無作用：下載/轉錄能力已移除，本檔只走官方 API 讀公開 metadata。")

    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2
    kws = list(DEFAULT_KW)
    try:
        if ORDERS.exists():
            pk = json.loads(ORDERS.read_text(encoding="utf-8")).get("preferred_keywords") or []
            kws = list(dict.fromkeys(pk + kws))  # 偏好關鍵字優先、去重保留全部
    except Exception:
        pass
    kw_cap = min(len(kws), KW_CAP)
    log_ops("競品情報", f"搜尋 {kw_cap} 組關鍵字（官方 API, order={ORDER}, per={PER_KW}）…")
    found, vids = set(), []
    for kw in kws[:kw_cap]:
        try:
            r = yt.search().list(q=kw, part="snippet", type="video", order=ORDER,
                                 maxResults=PER_KW, relevanceLanguage="zh-Hant", regionCode="TW").execute()
            for it in r.get("items", []):
                vid = it["id"].get("videoId")
                if vid and vid not in found:
                    found.add(vid)
                    vids.append({"id": vid, "title": it["snippet"]["title"][:70],
                                 "channel": it["snippet"]["channelTitle"][:30], "kw": kw})
        except Exception as e:
            print(f"[warn] 搜尋「{kw}」失敗：{e}", file=sys.stderr)
    ids = [v["id"] for v in vids]
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
    top = vids[:15]      # 報告只列最熱前 15
    date = tw_today()
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑯ 競品情報報告｜{date}", "",
         "> 同類題材近期高觀看影片（依觀看排序）。誠實：官方 YouTube Data API search.list 結果，",
         "> 唯讀公開 metadata（標題/頻道/觀看數）、不下載也不儲存任何影片內容，耗少量 quota。", "",
         "## 熱門題材 Top（標題＝可借鏡的角度/鉤子）"]
    for v in top:
        L.append(f"- 👁 {v['views']:>8,}｜{v['title']}　—　@{v['channel']}（搜:{v['kw']}）")
    if not top:
        L.append("-（本次未取得資料，可能 quota 或網路問題）")
    L += ["", "## 情報洞察（規則式）"]
    if top:
        avg = sum(v["views"] for v in top) // max(1, len(top))
        L.append(f"- 前段觀看均值約 {avg:,}，可見此題材有量；我們衝量＋差異化（誠實實測角度）切入。")
        L.append("- 借鏡高觀看標題的『數字/反直覺/痛點』結構，但內容守誠信鐵則（不喊單、不保證）。")
    (REPORTS / f"{date}_競品情報.md").write_text("\n".join(L), encoding="utf-8")
    (STUDIO / "intel.json").write_text(json.dumps({"date": date, "top": top}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    purged = purge_stale_reports()
    log_ops("競品情報", f"完成 {len(top)} 支 → {date}_競品情報.md（官方 API 唯讀）"
                        + (f"；清除逾 30 天報告 {purged} 份" if purged else ""))
    print(f"[ok] 競品情報完成：報告 top {len(top)} 支（候選 {len(vids)} 支，官方 API 唯讀 metadata）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
