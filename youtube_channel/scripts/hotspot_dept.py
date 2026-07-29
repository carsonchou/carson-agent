#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hotspot_dept.py — 【白帽漏洞①｜搶首發熱點偵測】

蹭時效熱點＝免費流量，誰先發誰吃光那波搜尋。本部門與 news_dept 分工：
  - news_dept：抓「幣圈/總經大新聞」→ 判一則最大 → 立刻產片＋即時發布（爆炸性事件即時路）。
  - hotspot_dept（本檔）：撒更廣的網，特別盯【Pionex/交易所『新功能·更新』】＋次級熱點 →
    產一批『搶首發』角度題目，**插隊到題庫最前面**，produce_batch 下一批優先做。
    定位＝把熱點轉成「可立刻量產」的題目緩衝，不即時發（避免和 news_dept 撞車洗版）。

來源：Google News RSS（免金鑰）。已用過的熱點不重複（hotspot_seen.json）。
誠信鐵則：只根據新聞已知事實，不誇大、不預測漲跌、不喊單、不保證收益。
用法：python scripts/hotspot_dept.py [--max 5] [--dry]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
SEEN = STUDIO / "hotspot_seen.json"
TW = timezone(timedelta(hours=8))
import studio_common as sc   # 共用地基：PERSONA / has_llm_key / evidence_block
MODEL = "claude-haiku-4-5-20251001"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

# 盯時效熱點的查詢：①Pionex/交易所新功能(這類『搶首發』最甜，新功能=幾乎沒人做)
# ②幣圈/工具次級熱點(news_dept 沒即時發的也能進題庫量產)。
QUERIES = [
    "Pionex 派網 新功能 OR 更新", "幣安 OR OKX OR Bybit 新功能 OR 上線",
    "交易所 機器人 OR 量化 新功能", "比特幣 OR 以太幣 走勢 OR 大漲 OR 大跌",
    "加密貨幣 ETF OR 監管 OR 政策", "AI 交易 OR 量化 工具 新",
    "Vibe Coding OR AI寫程式 交易 OR 量化", "Python 自動交易 OR 量化 教學 新",
    # ── 台股化：加台股時事熱點(財報季/除權息/當沖/大盤)，寄生台股搜尋紅利。
    "台股 財報季 OR 除權息 OR 當沖", "台股 崩 OR 大盤創新高 OR 加權指數",
]
FRESH_HOURS = 30   # 比 news_dept(18h)寬：題庫是緩衝、可容稍舊但仍有搜尋紅利的熱點


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def _fetch(query: str):
    url = (f"https://news.google.com/rss/search?q={quote(query)}+when:2d"
           "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=25) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return []
    now = datetime.now(timezone.utc)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("pubDate") or ""
        if not title:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt and (now - dt) > timedelta(hours=FRESH_HOURS):
                continue
        except Exception:
            pass
        out.append({"title": re.sub(r"\s+-\s+[^-]+$", "", title), "q": query})
    return out


def _load_seen():
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8"))) if SEEN.exists() else set()
    except Exception:
        return set()


def _save_seen(seen):
    try:
        SEEN.write_text(json.dumps(sorted(seen)[-500:], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _judge(headlines, want):
    """請 LLM 從新聞標題挑出『可搶首發、和量化/網格/派網相關』的熱點，每則產出可立刻製作的題目。"""
    joined = "\n".join(f"- {h}" for h in headlines[:30])
    prompt = f"""{sc.PERSONA}

你是量化阿森頻道（量化/自動交易/網格/定投/派網Pionex/風控，繁中，主攻 Shorts）的【搶首發選題官】。
以下是近兩天的財經/加密/交易工具新聞標題：
{joined}

{sc.evidence_block()}

任務：挑出最多 {want} 則「值得搶首發做 Shorts 蹭流量」的熱點。優先順序：
1) Pionex/交易所『新功能·新機器人·重大更新』——這類幾乎沒人做，搶首發紅利最大。
2) 幣圈大行情、ETF/監管進展、重要量化/AI 交易工具。
3) ★台股時事熱點：大盤重挫/創新高、財報季爆雷、除權息旺季、當沖警示——台股在地共鳴、搜尋量大。
   台股角度一律走「大盤/ETF/當沖避雷·數據拆解」；個股(含台積電)只做數據分析，不喊買賣、不報目標價。
每則都要把熱點**連到頻道的量化/網格/派網/風控觀點**（例：新功能怎麼用來跑網格、這行情下網格/定投會怎樣）。
【小白避雷視角】對新功能/新工具，優先切「新功能=也可能是新割韭菜的方式」——用小白怕被割的角度：這功能真有用還是包裝話術？新手該不該碰？怎麼用才不會被割？（既戳恐懼又給安心，比純吹新功能更會爆）。
選題時**參考上面『本頻道實證數據』的贏家題材/關鍵字**，靠向已驗證會爆的角度。
誠信鐵則：只用標題已知事實，不誇大、不預測漲跌、不喊單、不保證收益。沒夠份量的就少給，寧缺勿濫。

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"news":"觸發的新聞重點一句","title":"有點擊慾的影片標題(繁中、不誇大)","angle":"切入點：把熱點連到量化/網格/派網/風控，或小白避雷視角"}}]"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    txt = llm.complete(prompt, 1500, json_mode=True)
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        items = []
        for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
            try:
                items.append(json.loads(om.group(0)))
            except Exception:
                continue
        return items



# 🔴 2026-07-29 流量修復:幣圈題在源頭封頂。
# 實測(近14天已發布 Shorts):幣圈題 60 支**平均觀看 36**,非幣圈 121 支**平均觀看 93**——差 2.6 倍。
# 而題庫 2,518 個未用題裡有 1,153 個(46%)是幣圈,其中 **788 個來自本部門**(每 3 小時跑一次,
# 專撈加密新聞)。等於產線近一半產能被灌進「平均只有 36 觀看」的題材,擠掉台股題。
# 對應的流量後果:近 7 天 SHORTS 來源觀看 7,416 → 3,831(**-48%**),而同期搜尋 +56%、訂閱者 +12%
# ——跌的全部集中在 Shorts,而 Shorts 正是被幣圈題稀釋的那一塊。
#
# **不是禁掉**:幣圈是本頻道既有題材,也是 Pionex 聯盟的內容基礎(說明欄 640/641 支都放邀請碼),
# 完全不做會斷掉變現線。改成**封頂佔比**:每輪最多 1/4 是幣圈題,其餘名額讓給台股/通用觀念題。
# 若本輪撈到的全是幣圈,寧可少收幾則,也不要整輪都灌幣圈(少收的名額下輪自然補上)。
_CRYPTO_KW = ("網格", "機器人", "派網", "比特幣", "BTC", "btc", "爆倉", "加密", "幣圈",
              "Pionex", "以太", "ETH", "合約", "山寨")
_CRYPTO_MAX_RATIO = 0.25


def _is_crypto(p) -> bool:
    t = f"{p.get('title', '')} {p.get('angle', '')} {p.get('q', '')}"
    return any(k in t for k in _CRYPTO_KW)


def _cap_crypto(picks: list) -> list:
    """把本輪選中的熱點裡的幣圈題壓到 <=25%(見上方說明)。順序維持原本的優先序。"""
    if not picks:
        return picks
    cap = max(1, int(len(picks) * _CRYPTO_MAX_RATIO))
    out, n_cry, dropped = [], 0, 0
    for p in picks:
        if _is_crypto(p):
            if n_cry >= cap:
                dropped += 1
                continue
            n_cry += 1
        out.append(p)
    if dropped:
        print(f"[熱點] 幣圈題封頂:本輪 {len(picks)} 則中丟棄 {dropped} 則幣圈題"
              f"(保留 {n_cry}/{cap};實測幣圈 Shorts 平均觀看 36 vs 非幣圈 93)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=5, help="本輪最多撈幾則熱點進題庫")
    ap.add_argument("--dry", action="store_true", help="只判斷、印出，不寫題庫")
    args = ap.parse_args()
    if not sc.has_llm_key():
        print("[FATAL] 無任何 LLM 供應商 API key", file=sys.stderr); return 2

    seen = _load_seen()
    raw = []
    for q in QUERIES:
        raw += _fetch(q)
    # 去重 + 濾掉看過的
    uniq, ids_now = [], set()
    for h in raw:
        hid = hashlib.md5(h["title"].encode("utf-8")).hexdigest()[:10]
        if hid in seen or hid in ids_now:
            continue
        ids_now.add(hid)
        uniq.append(h)
    if not uniq:
        print("[熱點] 無新鮮熱點。"); return 0

    try:
        picks = _judge([h["title"] for h in uniq], args.max)
    except Exception as exc:  # noqa: BLE001
        log_ops("熱點偵測", f"⚠️ 判斷失敗：{str(exc)[:70]}")
        print(f"[FATAL] 判斷失敗：{exc}", file=sys.stderr); return 3

    seen |= ids_now  # 不論採不採用，這批標題都記為看過，避免下次重判
    picks = [p for p in picks if (p.get("title") or "").strip()][:args.max]
    picks = _cap_crypto(picks)
    if not picks:
        _save_seen(seen)
        log_ops("熱點偵測", "本輪無夠份量熱點，未進題庫")
        print("[熱點] 無夠份量熱點，不進題庫。"); return 0

    if args.dry:
        for p in picks:
            print(f"[dry] {p.get('title','')}\n      觸發：{p.get('news','')[:50]}｜角度：{p.get('angle','')[:60]}")
        return 0

    from topic_bank import add_topics
    items = [{"title": p["title"], "angle": p.get("angle", ""),
              "category": "市場觀念", "format": "short",
              "news": p.get("news", ""), "priority": "hotspot"} for p in picks]
    added = add_topics(items, source="hotspot", front=True)  # 插隊：搶首發要快
    _save_seen(seen)
    log_ops("熱點偵測", f"搶首發熱點 {added} 則插隊進題庫（優先量產）")
    print(f"[ok] 熱點偵測：{added} 則『搶首發』題目已插隊進題庫最前面，下批優先製作。")
    for p in picks:
        print(f"   ⚡ {p['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
