#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""news_dept.py — 金融時事部：抓即時財經/加密新聞 → 判斷有無值得做的大事 → 立刻產相關 Short。

蹭時事＝免費流量。有重大金融時事就**繞過排程立刻產片**（呼叫 produce_batch --topic）。
新聞來源用 Google News RSS（免金鑰）。已報過的時事不重複（news_seen.json）。
誠信鐵則：只講新聞已知事實，不誇大、不預測漲跌、不喊單、不保證收益。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
SEEN = STUDIO / "news_seen.json"
TW = timezone(timedelta(hours=8))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
# 省 credits：挑時事是分類工作，haiku 已足夠（影片腳本本來也是 haiku 產）。原 sonnet 一天跑12次太貴。
MODEL = "claude-haiku-4-5-20251001"
PY = sys.executable

try:
    from ai_budget import call_ai as _call_ai
    _USE_BUDGET = True
except ImportError:
    _USE_BUDGET = False

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):
        pass

# 與頻道相關的查詢（加密/量化/總經對交易的影響）。
QUERIES = ["比特幣 OR 以太幣 OR 加密貨幣", "美聯儲 OR 升息 OR 降息 OR CPI", "比特幣 ETF OR 加密 監管", "幣安 OR 交易所 OR 穩定幣"]
FRESH_HOURS = 18
MAX_PER_DAY = 8  # 安全上限(防爆衝/bug 洗版)，非品質限制；真正重要的事很少一天 >5 件，所以幾乎不會卡到


def _fetch(query: str):
    url = (f"https://news.google.com/rss/search?q={quote(query)}+when:1d"
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
        src = it.findtext("{http://news.google.com/}source") or ""
        out.append({"title": re.sub(r"\s+-\s+[^-]+$", "", title), "src": src})
    return out


def _load_seen():
    try:
        return json.loads(SEEN.read_text(encoding="utf-8")) if SEEN.exists() else {"ids": [], "dates": []}
    except Exception:
        return {"ids": [], "dates": []}


def _save_seen(seen):
    seen["ids"] = seen["ids"][-300:]
    seen["dates"] = seen["dates"][-30:]
    SEEN.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")


def _today_count(seen) -> int:
    today = datetime.now(TW).strftime("%Y-%m-%d")
    return sum(1 for d in seen.get("dates", []) if d == today)


def _judge(headlines: list[str]) -> dict:
    """請 Claude 從新聞標題中挑出『最值得做、且和量化/加密交易相關』的時事，產出影片角度。"""
    joined = "\n".join(f"- {h}" for h in headlines[:25])
    prompt = f"""你是量化阿森頻道（量化/自動交易/網格/定投/派網Pionex/風控，繁中，主攻 Shorts）的【金融時事編輯】。
以下是最近的財經/加密新聞標題：
{joined}

判斷其中有沒有「**真正撼動市場、非做不可**」的大事。**門檻要很高，寧可不做也不要做小事**——
✅ 才算重要：比特幣單日 ±8% 以上劇烈波動、爆倉/清算規模上億、Fed 利率決議、CPI 爆表、
   現貨 ETF 重大進展(通過/大額流入流出)、頂級交易所爆雷/倒閉/被駭、國家級重大監管或禁令、Pionex 重大新功能。
❌ 不做（回 worthy=false）：日常 1-3% 波動、分析師喊單、例行報導、小幣消息、重複舊聞、純預測性內容。
若有夠格的大事，挑**最重大**的一則，產出影片角度（把時事連到頻道的量化/網格/風控觀點）。
誠信鐵則：只根據標題已知事實，不誇大、不預測漲跌、不喊單、不保證收益。**有疑慮就回 worthy=false**。

只輸出 JSON：{{"worthy":true/false,"news":"觸發的新聞重點一句","title":"有點擊慾的影片標題","angle":"切入點：把時事連到量化/網格/風控的觀點"}}"""
    if _USE_BUDGET:
        txt = _call_ai(prompt, MODEL, max_tokens=800, use_cache=True)
        if txt is None:
            raise RuntimeError("AI 呼叫失敗（無 API key 或網路錯誤）")
    else:
        body = {"model": MODEL, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]}
        import requests
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"}, json=body, timeout=90)
        r.raise_for_status()
        txt = r.json()["content"][0]["text"]
    return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))


def main() -> int:
    if not API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr)
        return 2
    seen = _load_seen()
    if _today_count(seen) >= MAX_PER_DAY:
        print(f"[時事] 今日已蹭 {MAX_PER_DAY} 支，達上限，跳過。")
        return 0

    headlines = []
    for q in QUERIES:
        headlines += _fetch(q)
    # 去重 + 濾掉已報過的
    uniq, ids_now = [], set()
    for h in headlines:
        hid = hashlib.md5(h["title"].encode("utf-8")).hexdigest()[:10]
        if hid in seen["ids"] or hid in ids_now:
            continue
        ids_now.add(hid)
        uniq.append(h)
    if not uniq:
        print("[時事] 無新鮮新聞。")
        return 0

    try:
        d = _judge([h["title"] for h in uniq])
    except Exception as exc:  # noqa: BLE001
        log_ops("時事部", f"⚠️ 判斷失敗：{str(exc)[:70]}")
        print(f"[FATAL] 判斷失敗：{exc}", file=sys.stderr)
        return 3

    # 不論是否採用，都把這批標題記為已看（避免下次重判同批）
    seen["ids"].extend(ids_now)

    if not d.get("worthy") or not d.get("title"):
        _save_seen(seen)
        log_ops("時事部", "本次無夠份量時事，未產片")
        print("[時事] 無夠份量的大事，不產片。")
        return 0

    title, angle = d["title"], d.get("angle", "")
    print(f"[時事] 命中：{d.get('news','')[:50]} → 產片《{title[:40]}》")
    if "--dry" in sys.argv:
        print(f"[dry] 角度：{angle[:80]}（測試模式，不實際產片）")
        return 0
    # 立刻產 1 支並『即時發布』（繞過排程，消息面要快）
    rc = subprocess.run([PY, "scripts/produce_batch.py", "--topic", title, "--angle", angle, "--publish"],
                        cwd=str(ROOT)).returncode
    if rc == 0:
        seen["dates"].append(datetime.now(TW).strftime("%Y-%m-%d"))
        log_ops("時事部", f"蹭時事產片：{title[:40]}")
    _save_seen(seen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
