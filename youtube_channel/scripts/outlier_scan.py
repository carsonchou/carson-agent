#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""outlier_scan.py — 【1of10 自架版｜異常爆款偵測】

爆款的真訊號不是「絕對觀看高」，而是「觀看數遠超過自己頻道的訂閱基數」——
代表這支片衝出了訂閱牆、被演算法主動推送＝一個被驗證會爆的格式。1of10.com 就是賣這個。
本檔用 YouTube API 自己算：搜 niche 競品 → 取 觀看數÷訂閱數 的 outlier 倍率 →
挑出真正的異常爆款，寫 STUDIO/outliers.json（給 parasite_titles 當優先寄生彈藥）＋一份報告。

outlier 倍率 = viewCount / subscriberCount。≥3＝衝出訂閱牆，≥10＝病毒級。
搭配近 N 天內發布（抓新鮮、可搶的爆款）＋最低絕對觀看（濾掉小頻道雜訊）。
用法：python scripts/outlier_scan.py [--days 120] [--min-ratio 3] [--min-views 20000] [--top 20]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
OUTLIERS = STUDIO / "outliers.json"
TW = timezone(timedelta(hours=8))

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

try:
    from intel_dept import DEFAULT_KW
except Exception:  # noqa: BLE001
    DEFAULT_KW = ["網格交易", "Pionex 教學", "派網 機器人", "定投策略", "量化交易",
                  "網格機器人", "交易機器人 實測", "AI 量化 交易", "回測 策略"]


# niche 過濾：標題須含至少一個「金融/交易/加密」詞，濾掉關鍵字誤抓的雜訊（如 bot→遊戲短片）。
# 刻意不收 bare bot/trade 這種歧義詞，避免遊戲/科技誤判。
NICHE = ("交易", "量化", "網格", "网格", "定投", "dca", "派網", "派网", "pionex", "幣", "币",
         "比特", "以太", "btc", "eth", "crypto", "加密", "合約", "合约", "期貨", "期货", "外匯", "外汇",
         "cfd", "回測", "回测", "策略", "投資", "投资", "理財", "理财", "被動收入", "被动收入", "股",
         "基金", "etf", "ea ", "因子", "機器學習", "机器学习", "套利", "資金費率", "资金费率",
         "trading", "backtest", "quant", "forex", "黃金", "黄金")


def _is_niche(title):
    t = (title or "").lower()
    return any(k in t for k in NICHE)


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def _iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def scan(yt, days, min_ratio, min_views, kw_cap, per):
    after = _iso_days_ago(days)
    found, cand = set(), []
    for kw in DEFAULT_KW[:kw_cap]:
        try:
            r = yt.search().list(q=kw, part="snippet", type="video", order="viewCount",
                                 maxResults=per, publishedAfter=after,
                                 relevanceLanguage="zh-Hant", regionCode="TW").execute()
            for it in r.get("items", []):
                vid = it["id"].get("videoId")
                if vid and vid not in found:
                    found.add(vid)
                    cand.append({"id": vid, "kw": kw})
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 搜尋「{kw}」失敗：{e}", file=sys.stderr)
    if not cand:
        return []

    # 批次抓影片 statistics + snippet
    ids = [c["id"] for c in cand]
    vinfo = {}
    for i in range(0, len(ids), 50):
        try:
            rr = yt.videos().list(part="statistics,snippet", id=",".join(ids[i:i+50])).execute()
            for it in rr.get("items", []):
                vinfo[it["id"]] = it
        except Exception as e:  # noqa: BLE001
            print(f"[warn] videos.list 失敗：{e}", file=sys.stderr)

    # 批次抓頻道 訂閱數
    chans = {vinfo[v]["snippet"]["channelId"] for v in vinfo}
    subs = {}
    chans = list(chans)
    for i in range(0, len(chans), 50):
        try:
            rr = yt.channels().list(part="statistics", id=",".join(chans[i:i+50])).execute()
            for it in rr.get("items", []):
                st = it.get("statistics", {})
                if not st.get("hiddenSubscriberCount", False):
                    subs[it["id"]] = int(st.get("subscriberCount", 0))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] channels.list 失敗：{e}", file=sys.stderr)

    out = []
    for vid, it in vinfo.items():
        sn, st = it["snippet"], it.get("statistics", {})
        title = sn.get("title", "")
        if not _is_niche(title):
            continue  # 濾掉關鍵字誤抓的非金融雜訊
        views = int(st.get("viewCount", 0))
        ch = sn["channelId"]
        s = subs.get(ch, 0)
        if views < min_views or s <= 0:
            continue
        ratio = round(views / s, 1)
        if ratio < min_ratio:
            continue
        out.append({
            "id": vid, "title": sn.get("title", "")[:80], "channel": sn.get("channelTitle", "")[:30],
            "views": views, "subs": s, "ratio": ratio,
            "published": sn.get("publishedAt", "")[:10],
            "url": f"https://youtu.be/{vid}",
        })
    out.sort(key=lambda x: x["ratio"], reverse=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120, help="只看近 N 天內發布（抓新鮮可搶的爆款）")
    ap.add_argument("--min-ratio", type=float, default=3.0, help="觀看÷訂閱 的最低 outlier 倍率（≥3 衝出訂閱牆）")
    ap.add_argument("--min-views", type=int, default=20000, help="最低絕對觀看（濾小頻道雜訊）")
    ap.add_argument("--top", type=int, default=20, help="最多留幾支進 outliers.json")
    ap.add_argument("--kw", type=int, default=8, help="搜尋幾組 niche 關鍵字（每組=100 配額單位，和 intel/上傳共用日配額，故節制）")
    ap.add_argument("--per", type=int, default=25, help="每組關鍵字抓幾筆")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2

    log_ops("爆款偵測", f"掃 outlier（近{args.days}天、倍率≥{args.min_ratio}、觀看≥{args.min_views:,}）…")
    outs = scan(yt, args.days, args.min_ratio, args.min_views, args.kw, args.per)[:args.top]
    if not outs:
        log_ops("爆款偵測", "本輪無符合條件的異常爆款")
        print("[outlier] 本輪沒抓到符合條件的異常爆款（可放寬 --min-ratio / --days）。")
        return 0

    if args.dry:
        for o in outs:
            print(f"[dry] ×{o['ratio']:>5}　👁{o['views']:>9,}　訂{o['subs']:>8,}　{o['title'][:36]}　@{o['channel']}")
        return 0

    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = {"date": tw_today(), "params": {"days": args.days, "min_ratio": args.min_ratio,
               "min_views": args.min_views}, "outliers": outs}
    OUTLIERS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    L = [f"# 🚀 異常爆款偵測（1of10 自架版）｜{tw_today()}", "",
         f"> 邏輯：觀看數÷訂閱數＝outlier 倍率（衝出訂閱牆＝演算法在推＝可寄生的爆款格式）。",
         f"> 條件：近 {args.days} 天、倍率 ≥{args.min_ratio}、觀看 ≥{args.min_views:,}。共 {len(outs)} 支。", "",
         "| 倍率 | 觀看 | 訂閱 | 標題 | 頻道 | 發布 |", "|---|---|---|---|---|---|"]
    for o in outs:
        L.append(f"| ×{o['ratio']} | {o['views']:,} | {o['subs']:,} | {o['title'][:40]} | @{o['channel']} | {o['published']} |")
    L += ["", "## 用法", "- 這些是被驗證會爆的格式 → `parasite_titles.py` 會優先拿來產『同主題＋誠實反方角度』的寄生題目。",
          "- 倍率越高＝越值得搶；想手動拆解某支可：`python scripts/shorts_funnel.py`（長片）或用 /watch 看它。"]
    (REPORTS / f"{tw_today()}_異常爆款.md").write_text("\n".join(L), encoding="utf-8")

    log_ops("爆款偵測", f"抓到 {len(outs)} 支異常爆款（最高 ×{outs[0]['ratio']}）→ outliers.json")
    print(f"[ok] 異常爆款偵測：{len(outs)} 支寫進 outliers.json（最高倍率 ×{outs[0]['ratio']}）。")
    for o in outs[:8]:
        print(f"   🚀 ×{o['ratio']}　{o['title'][:38]}　@{o['channel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
