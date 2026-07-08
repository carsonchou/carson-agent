#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parasite_titles.py — 【白帽漏洞②｜寄生標題產生器】

蹭別人的流量池：競品爆款一紅，2 小時內出一支『同主題 + 我們的誠實/反方角度』，
吃它的長尾搜尋與推薦欄寄生。本檔吃 STUDIO/intel.json（競品情報部撈的高觀看競品）
＋ competitor_analysis.md 最新拆解，用 Claude 產一批『寄生 + 好奇缺口』題目灌進題庫，
produce_batch 之後自動把它們做成片。

寄生不是抄：守誠信鐵則，用我們的回測數據/誠實護城河做出差異化反方觀點，不誤導不喊單。
用法：python scripts/parasite_titles.py [--count 8] [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
INTEL = STUDIO / "intel.json"
OUTLIERS = STUDIO / "outliers.json"
ANALYSIS = ROOT / "competitor_analysis.md"
import studio_common as sc   # 共用地基：PERSONA / has_llm_key / evidence_block
MODEL = "claude-haiku-4-5-20251001"   # 要創意＋懂寄生分寸，用較強模型

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

try:
    from produce_batch import GUARD
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森(網格/定投/派網/回測/風控)。"


# AI×交易題材白名單：頻道最大外部爆款池（Vibe Coding／手搓量化／AI 選股／自動交易），
# 命中就加權優先排到前面（不是砍掉其他，只是排序優先，見下方 _top_competitors 的 sort）。
_AI_TRADE_KW = ("ai", "claude", "chatgpt", "vibe coding", "自動交易", "手搓", "程式")


def _is_ai_trading(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in _AI_TRADE_KW)


def _top_competitors(n=15):
    """寄生標的＝優先用 outlier_scan 抓的『異常爆款』（觀看÷訂閱衝出訂閱牆＝被驗證會爆的格式），
    再補 intel.json 的高觀看競品。去重，最多回 n 支。
    加權：AI×交易題材(AI/Claude/ChatGPT/Vibe Coding/自動交易/手搓/程式) 命中的優先排到最前面
    （stable sort，同批內原本的相對順序不變，只是把 AI×交易 那批往前提，不砍其他題材）。"""
    picks, seen = [], set()
    # 1) 異常爆款優先（1of10 訊號）
    try:
        d = json.loads(OUTLIERS.read_text(encoding="utf-8"))
        for o in d.get("outliers", []):
            t = o.get("title", "")
            if t and t not in seen:
                seen.add(t)
                picks.append((f"[爆款×{o.get('ratio','?')}] {t}", o.get("channel", ""), o.get("views", 0)))
    except Exception:
        pass
    # 2) 補 intel.json 高觀看競品
    try:
        d = json.loads(INTEL.read_text(encoding="utf-8"))
        for t in d.get("top", []):
            ti = t.get("title", "")
            if ti and ti not in seen:
                seen.add(ti)
                picks.append((ti, t.get("channel", ""), t.get("views", 0)))
    except Exception:
        pass
    picks.sort(key=lambda p: not _is_ai_trading(p[0]))  # AI×交易 優先，stable 保留原序
    return picks[:n]


def _analysis_tail(chars=2500):
    """讀 competitor_analysis.md 末段（最新自動學習的拆解），給 Claude 抓最新爆款角度。"""
    try:
        return ANALYSIS.read_text(encoding="utf-8")[-chars:]
    except Exception:
        return ""


def gen(count, comps, tail):
    comp_lines = "\n".join(f"- 👁{v:,}｜{t}　@{c}" for t, c, v in comps) or "（暫無情報）"
    prompt = f"""{sc.PERSONA}

你是量化阿森頻道（量化/自動交易/網格/定投/派網Pionex/風控，繁中 faceless）的【寄生流量選題官】。{GUARD}

{sc.evidence_block()}

【寄生流量心法】競品爆款影片＝現成的流量池。我們要出『同主題、但用我們的誠實/反方/回測角度』的影片，
吃它的長尾搜尋與推薦欄寄生。關鍵：
- 差異化主軸＝「小白怕被割 → 我用回測拆給你看有沒有雷」：對手講「這機器人穩賺/這功能超神」→ 我們講「我用回測幫你試，到底有沒有雷、新手會不會被割」；對手只曬贏單→我們補回測勝率真相與翻車情況。
- 【若寄生標的屬 Vibe Coding／手搓量化／Python 自動交易／用 AI 寫策略 題材(當前最大流量池,務必優先寄生)】走這條對齊高爆款的公式：對手講「我用 AI／Python 寫出一個會賺的交易機器人」→ 我們講「我真的照他方法拿 AI 手搓一個，實測能不能跑、不會 coding 的新手能不能複製、有沒有藏坑」。標題公式：①「我用 ChatGPT／Cursor 手搓一個交易機器人，結果…」②「不會寫程式也能手搓量化？我用回測給你看」③「Python 自動交易是不是智商稅？我回測跑了 X 天」④「AI 幫我寫策略回測勝率 X%，但有個致命問題」。守誠信鐵則：數字要真、不保證收益、不喊單。
- 好奇缺口（Curiosity Gap）：標題拋懸念逼點開，但片裡『真的有答案』，不准標題殺人（封面講A內容講B會被降推）。
- 可埋熱門幣種/工具名（BTC、Pionex、ETF…）蹭搜尋，但不得碰瓷造謠、不冒充對方。
- 靠向上面『本頻道實證數據』已驗證會爆的角度與關鍵字。

以下是近期『高觀看競品影片』（你的寄生標的，挑最相關的題材切入）：
{comp_lines}

以下是competitor_analysis.md最新拆解片段（抓最新爆款角度與鉤子）：
{tail}

請產出 {count} 個『寄生 + 好奇缺口』影片題目，要求：
- 緊貼上面競品的熱門題材，但角度是我們的誠實/反方/回測差異化，不是換句話說抄。
- 標題有強點擊慾但不誇大、不保證收益、不喊單。
- 多數 short，約 1/5 可給 long（深度反方拆解）。

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"寄生標題","angle":"一句話：蹭哪個競品題材＋我們的差異化反方角度","category":"網格交易/定投DCA/回測數據/風控心法/工具派網/市場觀念 擇一","format":"short 或 long"}}]"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    txt = llm.complete(prompt, 2500, json_mode=True)
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    items = []
    for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
        try:
            items.append(json.loads(om.group(0)))
        except Exception:
            continue
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8, help="本輪要產幾個寄生題目")
    ap.add_argument("--dry", action="store_true", help="只產、印出，不寫題庫")
    args = ap.parse_args()
    if not sc.has_llm_key():
        print("[FATAL] 無任何 LLM 供應商 API key", file=sys.stderr); return 2

    comps = _top_competitors()
    if not comps:
        print("[寄生] intel.json 無競品資料（競品情報部尚未跑？），改用 analysis 拆解產題。")
    tail = _analysis_tail()
    try:
        picks = gen(args.count, comps, tail)
    except Exception as exc:  # noqa: BLE001
        log_ops("寄生標題", f"⚠️ 產題失敗：{str(exc)[:70]}")
        print(f"[FATAL] 產題失敗：{exc}", file=sys.stderr); return 3

    picks = [p for p in picks if (p.get("title") or "").strip()][:args.count]
    if not picks:
        print("[寄生] 沒產出可用題目。"); return 0

    if args.dry:
        for p in picks:
            print(f"[dry] {p.get('title','')}\n      角度：{p.get('angle','')[:70]}　[{p.get('format','short')}]")
        return 0

    from topic_bank import add_topics
    # front=True：outlier 驗證過的寄生題搶首發（這些是已被市場證明會爆的題型，優先做）
    added = add_topics(picks, source="parasite", front=True)
    log_ops("寄生標題", f"寄生競品爆款 → 題庫新增 {added} 題")
    print(f"[ok] 寄生標題：{added} 個蹭流量題目已進題庫，produce_batch 之後自動做成片。")
    for p in picks:
        print(f"   🪝 {p['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
