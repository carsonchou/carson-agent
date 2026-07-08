#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""topic_bank.py — 【題庫引擎】先擴題庫再衝量。

由 ③創作靈感＋⑯競品 的精神，用 Claude 一次產出「跨子領域、彼此不同角度」的題目庫，
跟既有影片＋既有題庫去重，存 STUDIO/topic_bank.json。produce_batch 之後從題庫抽題產片，
保證放量時不會做出一堆重複片（避免 YouTube 懲罰重複低值內容）。

每個題目：{id, title, angle(獨特切入鉤子), category, format(short/long), used(bool)}

用法：
  python scripts/topic_bank.py                 # 補到預設 50 個未用題目
  python scripts/topic_bank.py --target 80     # 補到 80 個未用題目
"""
from __future__ import annotations

import argparse
import hashlib
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
BANK = STUDIO / "topic_bank.json"
import studio_common as sc   # 共用地基：PERSONA / has_llm_key / evidence_block
MODEL = "claude-haiku-4-5-20251001"   # 擴題庫一次性、要創意與廣度，用較強模型

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass

# 量化嚴謹標準（與 produce_batch 一致，確保題庫題目正確）
try:
    from produce_batch import QUANT_STANDARD, GUARD
except Exception:  # noqa: BLE001
    QUANT_STANDARD = ""
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森(網格/定投/派網/回測/風控)。"

CATEGORIES = [
    "網格交易（設定/參數/上下限/等差等比/無限網格/單邊行情/適用幣種/常見錯誤）",
    "定投 DCA（原理/微笑曲線/買在高點/分批紀律/vs一次買/標的選擇）",
    "回測與數據（過擬合/前視偏差/生存者偏差/樣本外/交易成本/夏普卡瑪MDD/勝率vs盈虧比/期望值）",
    "風控與心法（停損/部位管理/Kelly/馬丁危險/複利72法則/情緒紀律/破產風險）",
    "工具與派網 Pionex（機器人類型/手續費/安全/API/被動收入實作）",
    "市場觀念與避坑（趨勢vs震盪/被動收入迷思/新手韭菜陷阱/槓桿風險）",
    "小白恐懼與避雷（怕被割/怕虧光/怕被套/自動交易是不是騙局/機器人會不會偷跑/新手最常踩的雷）",
    "我幫你試·實測避雷（我用回測先幫你試這機器人這策略、揭露沒人告訴你的坑、安全用法怎麼設）",
    # ↓↓ 台股全市場開放（2026-07 數據實證贏家；招牌回測/財報/籌碼分析＋避雷角度，個股也能講，但只做數據不喊單不報明牌）
    "台股大盤與ETF·數據拆穿（0050/006208/00878/00929、大盤擇時、恐慌指數抄底、定期定額vs一次All in、殖利率與填息——用回測與歷史數據拆穿迷思、幫小白避雷，不喊單、不報明牌）",
    "台股個股與選股·方法拆解（台積電/權值股/航運/AI股「會不會買、會不會套」用回測＋財報三率＋籌碼法人分析、選股方法拆解、AI選股神器打假——只做數據分析與避雷，絕不喊單、不報明牌、不喊目標價、不保證會漲）",
    "台股實戰·避雷（當沖/隔日沖九成賠的數據、除權息填不填息、融資融券斷頭風險、財報三率體檢、籌碼法人動向、看到綠燈全出場對不對——用歷史數據幫小白先踩雷，不喊單、不報明牌）",
    # ↓↓ 第二變現支柱「聰明用 AI」（2026-07；誠實比較各省錢法＋揭露共享帳號被 ban 風險，一律避雷角度、資訊比較非推銷）
    "AI省錢·聰明用 AI（官方訂閱 vs 第三方共享合租 vs 走 API vs 免費額度 誠實比較、Claude/ChatGPT/Gemini 便宜怎麼用、共享帳號會不會被官方停用、值不值——一律拆穿/實測/幫你試/揭露風險，資訊比較非推銷，絕不喊「快買/最划算/穩用」）",
    # ↓↓ AI×交易招牌 franchise（2026-07；我真的用 Claude Code 開/跑 AI 系統=對手抄不出的護城河）
    "AI公司揭密·Claude Code 實測（我用 Claude Code 開/跑 AI 系統經營頻道與量化的 behind-the-scenes 揭密、AI 選股/寫 bot/自動化的真實與盲點、樣本外打臉照抄那些瘋傳暴利策略——揭密/實測/避雷角度，不喊單、不報明牌、不保證收益）",
]


def existing_titles():
    out = set()
    for f in OUT.glob("*.md"):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            t = first.replace("# 🎬", "").replace("#", "").strip()
            if t:
                out.add(t)
        except Exception:
            pass
    return out


_BAK = BANK.with_suffix(".json.bak")


def load_bank():
    """讀題庫。主檔壞掉(併發寫到一半/損毀)→退回 .bak 上一版好檔,而非靜默回 []（回 [] 會讓下一次 save 把整個題庫洗掉，本 bug 的根因）。"""
    for p in (BANK, _BAK):
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, list):
                    if p is _BAK:
                        log_ops("題庫引擎", "⚠️ 主題庫檔損毀,已從 .bak 救回")
                    return d
            except Exception:  # noqa: BLE001
                continue
    return []


def save_bank(bank):
    """原子寫 + 保留上一版 .bak。
    根因修復：原本 write_text 直接覆蓋=非原子,寫到一半被別支 load_bank 讀到殘缺 JSON→回[]→存回小題庫→**整庫被洗**。
    改用 tmp + os.replace(同目錄原子替換),讀者永遠看到完整檔;另存上一版當 .bak 救命(本機 backups 被 SKIP、無其他安全網)。"""
    BANK.parent.mkdir(parents=True, exist_ok=True)
    tmp = BANK.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 覆蓋前把現有好檔備份成 .bak(救命用)
        if BANK.exists() and BANK.stat().st_size > 2:
            import shutil
            shutil.copy2(BANK, _BAK)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, BANK)  # 原子替換,消除「讀到寫一半殘檔」的競態


def _norm(t):
    return re.sub(r"[\s，。！？、：；…·\-—()（）]+", "", (t or "")).lower()


def add_topics(items, source="", front=False):
    """把外部模組（熱點/寄生/切片漏斗）產的題目併入題庫，與既有題庫＋既有影片去重。
    items: list of dict，每筆至少 {title}；可帶 angle/category/format/parent/news/priority。
    source: 標記來源（hotspot/parasite/funnel…），方便日後分析哪條漏斗有效。
    front: True＝插隊到題庫最前面（produce_batch 下批優先抽到，給『搶首發』用）。
    回傳實際新增題數。"""
    bank = load_bank()
    have = {_norm(t.get("title", "")) for t in bank} | {_norm(t) for t in existing_titles()}
    # 2026-07 止血洗版:①全來源硬禁兩大濫用骨架(爆倉還活著/勝率9X破產公式);
    # ②幣圈/新聞來源才做語意去重(抽掉幣種/血詞後比),避免誤殺台股「0050 vs 0056」這類正常比較題。
    _crypto_src = str(source).lower() in ("hotspot", "breakout", "news", "intel")
    _recent_gate = ([t.get("title", "") for t in bank] + list(existing_titles())) if _crypto_src else None
    _blocked = 0
    new_recs = []
    for t in items:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        if sc.is_banned_skeleton(title):
            _blocked += 1
            continue
        if _crypto_src and sc.topic_gate(title, _recent_gate):
            _blocked += 1
            continue
        n = _norm(title)
        if n in have:
            continue
        have.add(n)
        if _crypto_src:
            _recent_gate.append(title)
        rec = {
            "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
            "title": title,
            "angle": (t.get("angle") or "").strip(),
            "category": (t.get("category") or "").strip(),
            "format": "long" if str(t.get("format", "")).lower().startswith("l") else "short",
            "used": False,
        }
        if source:
            rec["source"] = source
        for k in ("parent", "news", "priority"):
            if t.get(k):
                rec[k] = t[k]
        new_recs.append(rec)
    if new_recs:
        bank = (new_recs + bank) if front else (bank + new_recs)
        save_bank(bank)
    if _blocked:
        print(f"[topic_gate] 擋下 {_blocked} 題洗版/濫用骨架(來源={source or '?'})")
    return len(new_recs)


def gen_topics(need, avoid_titles):
    if not sc.has_llm_key():
        raise RuntimeError("無任何 LLM 供應商 API key")
    cats = "\n".join(f"  - {c}" for c in CATEGORIES)
    avoid = "、".join(list(avoid_titles)[:80])
    prompt = f"""{sc.PERSONA}

你是量化阿森頻道的選題總監（量化/自動交易教學，繁中）。{GUARD}
{QUANT_STANDARD}

{sc.evidence_block()}

請產出 {need} 個**彼此角度不同、不重複**的影片題目，平均分布在這些子領域：
{cats}

要求：
- **靠向上面『本頻道實證數據』已驗證會爆/高完播的題材與關鍵字**（尤其「數字戳破直覺」「我幫你試」「怕被割避雷」這類已被證明有效的角度），別憑空發想。
- 每題一個**獨特切入點**（反直覺結論／痛點場景／數字實測／破除迷思／比較懸念），不要同一觀念換句話說。
- 標題要有點擊慾但不誇大、不保證收益、不喊單；理財誇大詞（躺賺／穩賺／一天賺X）一律不用。
- **至少 1/3 題目用「可搜尋長尾」措辭**（繞過低權重的搜尋流量入口）：用觀眾真的會搜的關鍵字、放標題開頭，對齊三類有搜尋量題型——①回答問題（「派網網格機器人怎麼設」）②教具體技能（「Pionex 第一次設定」）③評測比較（「Pionex vs 幣安 新手選哪個」）。long（長片）尤其優先給可搜尋題。
- 多數給 short（Shorts），約 1/4 給 long（深度長片）。
- **避免重複以下既有題目**：{avoid}

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"標題","angle":"一句話獨特切入點","category":"網格交易/定投DCA/回測數據/風控心法/工具派網/市場觀念/小白避雷/我幫你試實測 擇一","format":"short 或 long"}}]"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    txt = llm.complete(prompt, 4000, json_mode=True)
    # 先試完整陣列；截斷時退而逐一撿出完整的 {...} 物件，不整批報廢
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
    ap.add_argument("--target", type=int, default=50, help="題庫要維持的未用題目數")
    args = ap.parse_args()

    bank = load_bank()
    unused = [t for t in bank if not t.get("used")]
    have_norms = {_norm(t.get("title", "")) for t in bank} | {_norm(t) for t in existing_titles()}
    need = args.target - len(unused)
    if need <= 0:
        print(f"題庫已有 {len(unused)} 個未用題目（≥目標 {args.target}），無需補充。")
        return 0

    log_ops("題庫引擎", f"擴題庫：目標未用 {args.target}，現 {len(unused)}，需補 {need}…")
    print(f"擴題庫中：要補 {need} 個（現有未用 {len(unused)}）…")

    added = 0
    rounds = 0
    while added < need and rounds < 8:
        rounds += 1
        batch = gen_topics(min(need - added + 3, 15), have_norms | set())
        for t in batch:
            title = (t.get("title") or "").strip()
            if not title:
                continue
            n = _norm(title)
            if n in have_norms:
                continue  # 去重
            have_norms.add(n)
            bank.append({
                "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
                "title": title,
                "angle": (t.get("angle") or "").strip(),
                "category": (t.get("category") or "").strip(),
                "format": "long" if str(t.get("format", "")).lower().startswith("l") else "short",
                "used": False,
            })
            added += 1
            if added >= need:
                break
        save_bank(bank)

    unused_now = sum(1 for t in bank if not t.get("used"))
    by_fmt = {}
    for t in bank:
        if not t.get("used"):
            by_fmt[t["format"]] = by_fmt.get(t["format"], 0) + 1
    log_ops("題庫引擎", f"完成 新增{added} 題，現未用 {unused_now}（short {by_fmt.get('short',0)}/long {by_fmt.get('long',0)}）")
    print(f"[ok] 新增 {added} 題，題庫現有未用 {unused_now} 個"
          f"（short {by_fmt.get('short',0)} / long {by_fmt.get('long',0)}）→ {BANK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
