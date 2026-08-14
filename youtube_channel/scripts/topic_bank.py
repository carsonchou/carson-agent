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
    # ↓↓ 2026-07 成長衝刺(growth_sprint_plan.md B 段實據)：台股/ETF/0050×定投對比×回測打臉直覺＝
    # 全頻道 reach 天花板(450-855v，遠高於其他題材)的已驗證贏家脈絡，**刻意放在第一位**——
    # gen_topics 每次呼叫至少第一輪(round 0，一定會執行)就會分到這個子領域，放大這條線的產出頻率。
    "台股大盤與ETF·數據拆穿（0050/006208/00878/00929、定期定額vs一次All in、大盤擇時、恐慌指數抄底、殖利率與填息——"
    "用回測與歷史數據拆穿迷思、幫小白避雷，不喊單、不報明牌。★這是本頻道實證的頭號贏家題材，"
    "務必多出幾題，但每題要換不同的比較錨點/情境/數字組合(不要每題都套同一種『一次十萬 vs 每月三千』的講法，"
    "換成不同金額、不同標的組合、不同時間長度，避免變成同一支片的換句話說)）",
    # ↓↓ 加密量化核心（2026-07 A3 擴廣度：不只網格，網格經實證是弱項關鍵字，別再獨佔題庫）
    "網格交易（設定/參數/上下限/等差等比/無限網格/單邊行情/適用幣種/常見錯誤——與其他子領域輪流出題，別佔題庫大宗）",
    "定投 DCA 與再平衡（原理/微笑曲線/買在高點/分批紀律/vs一次買/標的選擇/多久再平衡一次調倉划算）",
    "資金控管與槓桿風險（單筆風險上限怎麼算/槓桿爆倉數學/合約vs現貨/保證金追繳/倉位越大越危險的真實案例）",
    "交易成本與心理陷阱（手續費滑價侵蝕報酬的實際數字/過度交易代價/FOMO追高/報復性交易/確認偏誤怎麼騙自己）",
    "回測與數據方法論（過擬合/前視偏差/生存者偏差/樣本外/交易成本/夏普卡瑪MDD/勝率vs盈虧比/期望值）",
    "風控與心法（停損/部位管理/Kelly/馬丁危險/複利72法則/情緒紀律/破產風險）",
    "工具與派網 Pionex（機器人類型/手續費/安全/API/被動收入實作）",
    "市場觀念與避坑（趨勢vs震盪/被動收入迷思/新手韭菜陷阱/槓桿風險）",
    "小白恐懼與避雷（怕被割/怕虧光/怕被套/自動交易是不是騙局/機器人會不會偷跑/新手最常踩的雷）",
    "我幫你試·實測避雷（我用回測先幫你試這機器人這策略、揭露沒人告訴你的坑、安全用法怎麼設）",
    # ↓↓ 台股全市場（2026-07 A3 擴廣度：從「大盤/個股/實戰」3類再拆細，覆蓋除權息/存股/財報/籌碼/當沖/情緒/新手常見錯誤，個股也能講，但只做數據不喊單不報明牌）
    "台股除權息與存股（填權息機率數據/股利政策解讀/存股vs存ETF長期報酬比較/左手領息右手賠價差/存股稅務眉角）",
    "台股財報體檢（毛利率營益率淨利率三率怎麼看/EPS成長是不是真成長/負債比與現金流量地雷/財報常見造假手法辨識）",
    "台股籌碼分析（法人買賣超怎麼解讀/主力進出/融資融券餘額意義/券商分點觀察/內部人持股變化該不該當訊號）",
    "台股當沖與波段比較（當沖賠錢率的真實數據/隔日沖風險/波段vs當沖績效回測/當沖手續費與稅制划不划算）",
    "台股大盤情緒與產業輪動（恐慌貪婪指數/VIX與台股連動/類股輪動規律/景氣燈號怎麼用在進出場）",
    "台股新手常見錯誤（開戶手續費比較/下單方式誤區/零股交易眉角/盤中零股vs定盤交易/證交稅與二代健保常見誤解）",
    "台股個股與選股·方法拆解（台積電/權值股/航運/AI股「會不會買、會不會套」用回測＋財報三率＋籌碼法人分析、選股方法拆解、AI選股神器打假——只做數據分析與避雷，絕不喊單、不報明牌、不喊目標價、不保證會漲）",
    "台股實戰·避雷（當沖/隔日沖九成賠的數據、除權息填不填息、融資融券斷頭風險、財報三率體檢、籌碼法人動向、看到綠燈全出場對不對——用歷史數據幫小白先踩雷，不喊單、不報明牌）",
    # ↓↓ 通用量化觀念（2026-07 A3 新增：複利/風險/回撤/夏普/過擬合/倖存者偏差/前視偏差獨立出題，換角度講，別每支都套「回測XX年」同句式）
    "通用量化觀念·換角度講（複利效應的真實威力與誤解/最大回撤MDD代表什麼/夏普比率怎麼解讀/樣本外驗證為什麼重要/過擬合的真實案例/倖存者偏差怎麼騙你/前視偏差是什麼——用生活化比喻、故事、提問句包裝，不要每支都用『回測X年數據』開頭）",
    # ↓↓ 誠實避雷·拆穿神話（2026-07 A3 新增：獨立成類，別只附掛在其他分類底下）
    "拆穿穩賺神話（保證獲利話術怎麼辨識/老師帶單陷阱結構/明牌群組真相/AI自動選股神器打假/龐氏騙局常見話術/穩賺不賠廣告詞背後的數學——誠實拆解，不點名特定平台個人、不喊單、不報明牌）",
    # ↓↓ 第二變現支柱「聰明用 AI」（2026-07；誠實比較各省錢法＋揭露共享帳號被 ban 風險，一律避雷角度、資訊比較非推銷）
    "AI省錢·聰明用 AI（官方訂閱 vs 第三方共享合租 vs 走 API vs 免費額度 誠實比較、Claude/ChatGPT/Gemini 便宜怎麼用、共享帳號會不會被官方停用、值不值——一律拆穿/實測/幫你試/揭露風險，資訊比較非推銷，絕不喊「快買/最划算/穩用」）",
    # ↓↓ AI×交易招牌 franchise（2026-07；我真的用 Claude Code 開/跑 AI 系統=對手抄不出的護城河）
    "AI公司揭密·Claude Code 實測（我用 Claude Code 開/跑 AI 系統經營頻道與量化的 behind-the-scenes 揭密、AI 選股/寫 bot/自動化的真實與盲點、樣本外打臉照抄那些瘋傳暴利策略——揭密/實測/避雷角度，不喊單、不報明牌、不保證收益）",
    # ↓↓ 2026-07 台股比重修正新增（實測195支影片Top5全台股，補上明確缺口的3個台股角度；
    # 延續現有措辭風格：只做數據拆解、不喊單、不報明牌、不喊目標價、不保證會漲）
    "台股槓桿ETF陷阱（00631L/正2/反1這類槓桿與反向ETF——用回測拆解波動耗損(volatility decay)如何長期侵蝕報酬、"
    "「長期持有正2」的迷思、槓桿ETF只適合短期波段不適合存股的數據證明——不喊單、不報明牌、不喊目標價、不保證會漲）",
    "台股退休試算·長期報酬模擬（用0050/大盤/00878等台股長期歷史報酬回推「準備退休金要存多久/每月要投多少」、"
    "4%法則在台股適不適用、通膨侵蝕退休金的真實數字、不同報酬假設下的試算差異——用回測與試算表拆解，不報明牌、不保證會漲）",
    "台股停利vs續抱獨立分析（設停利點賣出 vs 續抱不賣，用歷史數據回測兩種紀律的長期績效差異、"
    "『賣飛』的心理代價與真實機會成本、停利點怎麼設才不會賣在起漲點——只做數據拆解，不喊單、不報明牌、不保證會漲）",
]

# ── 題材桶對照(2026-07 台股比重修正)：每個 CATEGORIES 項目對應到 studio_common.classify_topic_bucket
# 的哪一桶。用途：main() 依 TOPIC_BUCKET_WEIGHTS 決定「這次要多花幾輪從哪個桶的子領域出題」，
# 藉此在生成階段就結構性拉高台股比例，而不只是候選池排序層面的優先(那在候選池本身稀薄時無效)。
# 注意：這是「出題方向」的桶，跟每筆實際存檔的 bucket 欄位不同——存檔時仍用 classify_topic_bucket()
# 現場判斷 LLM 實際產出的 title/angle/category(LLM 有時會跑題，不能盲信這裡的方向標籤)。
_TW = "tw_stock"
_CR = "crypto"
_AI = "ai_tools"
_GN = "general"
CATEGORY_BUCKET_MAP = [
    _TW,  # 0  台股大盤與ETF·數據拆穿
    _CR,  # 1  網格交易
    _CR,  # 2  定投DCA與再平衡
    _GN,  # 3  資金控管與槓桿風險
    _GN,  # 4  交易成本與心理陷阱
    _GN,  # 5  回測與數據方法論
    _GN,  # 6  風控與心法
    _CR,  # 7  工具與派網Pionex
    _GN,  # 8  市場觀念與避坑
    _GN,  # 9  小白恐懼與避雷
    _GN,  # 10 我幫你試·實測避雷
    _TW,  # 11 台股除權息與存股
    _TW,  # 12 台股財報體檢
    _TW,  # 13 台股籌碼分析
    _TW,  # 14 台股當沖與波段比較
    _TW,  # 15 台股大盤情緒與產業輪動
    _TW,  # 16 台股新手常見錯誤
    _TW,  # 17 台股個股與選股·方法拆解
    _TW,  # 18 台股實戰·避雷
    _GN,  # 19 通用量化觀念·換角度講
    _GN,  # 20 拆穿穩賺神話
    _AI,  # 21 AI省錢·聰明用AI
    _AI,  # 22 AI公司揭密·Claude Code實測
    _TW,  # 23 台股槓桿ETF陷阱(新增)
    _TW,  # 24 台股退休試算(新增)
    _TW,  # 25 台股停利vs續抱(新增)
]
assert len(CATEGORY_BUCKET_MAP) == len(CATEGORIES), "CATEGORY_BUCKET_MAP 要跟 CATEGORIES 一一對應"

# A3 擴廣度：把 CATEGORIES 切成小群組，main() 每輪只指定 1 群組出題（round-robin）。
# 根因：先前單次全量丟給 LLM 選，靠 evidence_block 的「已驗證贏家關鍵字」(回測/網格)
# 強烈引導，模型仍會習慣性收斂回同一窄圈；改成「本輪只准從這幾個子領域出題」用結構
# 硬性分散，不再只靠 prompt 軟性建議。
_GROUP_SIZE = 3
CATEGORY_GROUPS = [CATEGORIES[i:i + _GROUP_SIZE] for i in range(0, len(CATEGORIES), _GROUP_SIZE)]

# 2026-07 台股比重修正：CATEGORY_GROUPS 依桶分組，main() 改成「先決定這批要花幾輪出哪個桶
# 的題，再在該桶內部 round-robin 子領域」，取代舊版單一 round-robin(那是均分邏輯，沒有加權)。
CATEGORY_GROUPS_BY_BUCKET = {
    b: [
        [CATEGORIES[i] for i in idxs[j:j + _GROUP_SIZE]]
        for j in range(0, len(idxs), _GROUP_SIZE)
    ]
    for b, idxs in {
        b2: [i for i, bb in enumerate(CATEGORY_BUCKET_MAP) if bb == b2]
        for b2 in (_TW, _CR, _AI, _GN)
    }.items()
}


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


_CC = None
_CC_TRIED = False


def _to_trad(t):
    """簡體→繁體正規化(僅用於去重比對字串,不改動實際儲存的標題)。LLM 偶爾滑成簡體時,
    簡繁字形不同會讓 _norm() 誤判成不同標題、放行近乎重複的題目進題庫。OpenCC 沒裝就原樣回
    (與 produce_batch.py 的 _to_traditional 同一容錯策略,不中斷產線)。"""
    global _CC, _CC_TRIED
    if not _CC_TRIED:
        _CC_TRIED = True
        try:
            from opencc import OpenCC
            _CC = OpenCC("s2twp")
        except Exception:  # noqa: BLE001
            _CC = None
    if _CC is None:
        return t
    try:
        return _CC.convert(t)
    except Exception:  # noqa: BLE001
        return t


# 標題禁用的專有名詞(見 add_topics 裡的說明)。刻意只放「一般觀眾不會懂、且我們
# 自己的規則早就禁止在片頭出現」的統計術語;像「回撤」「年化」這種已經被本頻道
# 標題大量使用且觀眾看得懂的詞不列入。
_JARGON_TITLE = ("卡瑪", "夏普", "標準差", "貝塔", "CAGR", "索提諾", "波動率",
                 "Sharpe", "Calmar", "Sortino")


def _norm(t):
    t = _to_trad(t or "")
    return re.sub(r"[\s，。！？、：；…·\-—()（）]+", "", t).lower()


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
        # 🔴 2026-08-14 術語閘(裝在題庫寫入層,所有生產者共用):標題帶專有名詞
        # (卡瑪/夏普/標準差/波動率…)對本頻道受眾=陌生人直接滑走,LONG_RULES ⓐ 早就
        # 禁止,但那條規則只作用在**寫稿階段**——標題一旦帶術語進了題庫,寫稿時只能照著寫。
        # 一次性清理實測:題庫裡累積 42 題術語題,來自 **12 個不同部門**
        # (auto_winner/hotspot/growth_agent/facts_engine/funnel…),不是單一管線的問題,
        # 所以閘門要裝在這個所有人都會經過的入口。
        # ⚠️ 只擋**標題**;內文要解釋這些概念完全可以(講的時候用白話即可)。
        if any(j in title for j in _JARGON_TITLE):
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
        _angle = (t.get("angle") or "").strip()
        _cat = (t.get("category") or "").strip()
        rec = {
            "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
            "title": title,
            "angle": _angle,
            "category": _cat,
            "format": "long" if str(t.get("format", "")).lower().startswith("l") else "short",
            "used": False,
            "bucket": sc.classify_topic_bucket(title, _angle, _cat),
        }
        if source:
            rec["source"] = source
        # tw_lab_key/tw_lab_next_key：台股真相實驗室 franchise 用來記「這題對應事實庫哪一組真回測」，
        # produce_batch.py 靠這個 key 精準抓那一組數字注入寫稿 prompt(不是靠關鍵字模糊比對)——
        # 沒有這個透傳，題目一旦從題庫抽出來就跟原始事實斷了連結。
        # 🔴 2026-07-17 fact_key 補進透傳(治長片編數字的根因之一)：這行原本漏了 fact_key，
        # 導致**任何**走 add_topics 的來源都會被無聲剝掉 fact_key——winner_amplifier
        # build_bank_records() 明明驗證過 `fk in facts` 才寫 rec["fact_key"]，卻在 add_topics
        # 這裡被丟掉,那段驗證等於死碼。唯二有 fact_key 的來源(facts_engine/stock_checkup_daily)
        # 是因為它們**繞過 add_topics**直接 save_bank 才活下來。fact_key 由呼叫端負責驗證
        # (winner_amplifier 已驗;沿用既有透傳慣例,不在題庫層再載事實庫增加耦合)。
        for k in ("parent", "news", "priority", "tw_lab_key", "tw_lab_next_key", "fact_key"):
            if t.get(k):
                rec[k] = t[k]
        new_recs.append(rec)
    if new_recs:
        bank = (new_recs + bank) if front else (bank + new_recs)
        save_bank(bank)
    if _blocked:
        print(f"[topic_gate] 擋下 {_blocked} 題洗版/濫用骨架(來源={source or '?'})")
    return len(new_recs)


def gen_topics(need, avoid_titles, bias_keywords=None, category_focus=None):
    """category_focus: 若給 list[str]（CATEGORY_GROUPS 其中一組），本輪**只**從這幾個
    子領域出題，用結構硬性分散廣度；不給則退回舊行為（全 CATEGORIES 讓模型自己平衡，
    供 growth_watchdog/growth_agent/weekly_winners 等既有呼叫方相容）。"""
    if not sc.has_llm_key():
        raise RuntimeError("無任何 LLM 供應商 API key")
    use_cats = category_focus if category_focus else CATEGORIES
    cats = "\n".join(f"  - {c}" for c in use_cats)
    avoid = "、".join(list(avoid_titles)[:80])
    # A5 飛輪:把每週贏家分析出的高流量關鍵字塞進偏好,主動多產贏家型別題
    # A3 擴廣度修正:原本「優先靠向」語氣太強，會讓模型每題都硬塞同一詞(如「回測」)、
    # 收斂回同一窄圈；改成「可穿插但別每題都塞同一味」，廣度交給 category_focus 結構把關。
    bias_line = ""
    if bias_keywords:
        bias_line = ("\n- 本週實證贏家關鍵字（可穿插參考，但**不要每題都塞同一個詞、也別因此讓題目全擠回同一子領域**）："
                     + "、".join(str(k) for k in list(bias_keywords)[:10]))
    focus_line = (
        f"\n- **本輪限定只從上面這幾個子領域出題**（衝題庫廣度用，其他子領域這輪先不要出）。"
        if category_focus else ""
    )
    prompt = f"""{sc.PERSONA}

你是量化阿森頻道的選題總監（量化/自動交易教學，繁中）。{GUARD}
{QUANT_STANDARD}

{sc.evidence_block()}

請產出 {need} 個**彼此角度不同、不重複**的影片題目，平均分布在這些子領域：
{cats}

要求：{bias_line}{focus_line}
- ★2026-07 成長衝刺實據(growth_sprint_plan.md)：全頻道 reach 天花板(450-855v)集中在「台股/ETF/0050×
  定投對比×回測打臉直覺」這條線，出到這個子領域時務必多給幾個變體(不同標的組合/不同金額/不同期間)，
  這是目前最值得放大的贏家脈絡。
- ★同一實據也發現「加密爆倉/清算新聞蹭熱」（例如「XX億爆倉」「網格撐得住嗎」這類純恐慌轉述）完播僅
  24-39%、是完播殺手且已洗版過量——**這輪不要再生這種純新聞恐慌轉述類的題目**（涉及爆倉/清算/斷頭/
  歸零/空單事件時，一律要求轉譯成觀眾能代入的反直覺對比或回測結論，不能只是恐慌事實轉述）。
- 延續本頻道贏家定位（真回測/實測拆穿割韭菜神話、用數據卡佐證、台股與加密量化教育），但**句式與詞彙要換花樣**：別每題都用「回測」開頭或當關鍵字，同義動作可輪流用「實測／驗證／攤開數據／打臉迷思／揭曉／拆解／體檢」；敘事手法也要輪流用提問句、場景痛點、數字對比、故事包裝、迷思破除、比較懸念，不要每支都同一套路。
- 每題一個**獨特切入點**，不要同一觀念換句話說。
- 標題要有點擊慾但不誇大、不保證收益、不喊單；理財誇大詞（躺賺／穩賺／保證／一天賺X）一律不用——**「拆穿穩賺神話」這類子領域也一樣**，可以引用『被拆穿的話術詞』但一定要有明確拆穿語境（例如打上「」引號、緊接「打臉／拆穿／揭穿／騙局／迷思」等字），絕不能把「穩賺」「保證」直接當成你自己在教的方法或策略去包裝（例如「教你挑出穩賺策略」這種寫法禁止）。
- **至少 1/3 題目用「可搜尋長尾」措辭**（繞過低權重的搜尋流量入口）：用觀眾真的會搜的關鍵字、放標題開頭，對齊三類有搜尋量題型——①回答問題（「除權息前該不該賣」）②教具體技能（「Pionex 第一次設定」）③評測比較（「存股vs存ETF 新手選哪個」）。long（長片）尤其優先給可搜尋題。
- 多數給 short（Shorts），約 1/4 給 long（深度長片）。
- **避免重複以下既有題目**：{avoid}

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"標題","angle":"一句話獨特切入點","category":"填上你選的子領域關鍵字(如：台股籌碼分析/通用量化觀念/拆穿穩賺神話/定投DCA...)，取子領域名稱前2~6字即可","format":"short 或 long"}}]"""
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


def _bucket_quota(need: int) -> dict:
    """依 sc.TOPIC_BUCKET_WEIGHTS 把這次要補的 need 題分配到 tw_stock/crypto/ai_tools 三桶
    (產題方向，不是硬性事後篩選——實際存檔 bucket 仍由 classify_topic_bucket 判斷真實產出)。
    規則：need 太小(<3)時全給 tw_stock(主力)，不硬拆三桶；need>=3 時 crypto/ai_tools 各自
    至少保底 1 題(比重*小基數捨去成 0 會讓這兩桶在小批次時被結構性歸零，故設下限)，
    剩下(含四捨五入誤差)全部歸給 tw_stock。"""
    if need <= 0:
        return {}
    if need < 3:
        return {"tw_stock": need}
    quotas = {}
    remaining = need
    for b in ("crypto", "ai_tools"):
        w = sc.TOPIC_BUCKET_WEIGHTS.get(b, 0)
        q = max(1, round(need * w))
        q = min(q, remaining - 1)  # 至少留 1 題給 tw_stock，避免極端小批被小桶吃光
        quotas[b] = max(0, q)
        remaining -= quotas[b]
    quotas["tw_stock"] = max(0, remaining)
    return quotas


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

    # 2026-07 台股比重修正：不再是單一 round-robin(均分)，改成先依桶配額決定「這批花幾輪
    # 出哪個桶的題」，桶內部再 round-robin 子領域(維持廣度，避免同桶內全擠在同一子領域)。
    quotas = _bucket_quota(need)
    added = 0
    added_by_bucket = {}
    rounds = 0
    for bucket, bneed in quotas.items():
        if bneed <= 0 or added >= need:
            continue
        groups = CATEGORY_GROUPS_BY_BUCKET.get(bucket) or CATEGORY_GROUPS
        b_added = 0
        b_round = 0
        # A3 擴廣度精神延續：輪數要能覆蓋完整一輪該桶的子領域群組，且留餘裕應付去重撞名。
        max_b_rounds = max(4, len(groups) * 2)
        while b_added < bneed and added < need and b_round < max_b_rounds:
            focus = groups[b_round % len(groups)]
            b_round += 1
            rounds += 1
            batch = gen_topics(min(bneed - b_added + 3, 15), have_norms | set(), category_focus=focus)
            for t in batch:
                title = (t.get("title") or "").strip()
                if not title:
                    continue
                n = _norm(title)
                if n in have_norms:
                    continue  # 去重
                have_norms.add(n)
                _angle = (t.get("angle") or "").strip()
                _cat = (t.get("category") or "").strip()
                actual_bucket = sc.classify_topic_bucket(title, _angle, _cat)  # 現場判斷實際產出,不盲信 focus 方向
                bank.append({
                    "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
                    "title": title,
                    "angle": _angle,
                    "category": _cat,
                    "format": "long" if str(t.get("format", "")).lower().startswith("l") else "short",
                    "used": False,
                    "bucket": actual_bucket,
                })
                added += 1
                b_added += 1
                added_by_bucket[actual_bucket] = added_by_bucket.get(actual_bucket, 0) + 1
                if added >= need or b_added >= bneed:
                    break
            save_bank(bank)

    unused_now = sum(1 for t in bank if not t.get("used"))
    by_fmt = {}
    for t in bank:
        if not t.get("used"):
            by_fmt[t["format"]] = by_fmt.get(t["format"], 0) + 1
    bucket_summary = "、".join(f"{k}{v}" for k, v in added_by_bucket.items())
    log_ops("題庫引擎", f"完成 新增{added} 題（{bucket_summary}），現未用 {unused_now}"
                        f"（short {by_fmt.get('short',0)}/long {by_fmt.get('long',0)}）")
    print(f"[ok] 新增 {added} 題（{bucket_summary}），題庫現有未用 {unused_now} 個"
          f"（short {by_fmt.get('short',0)} / long {by_fmt.get('long',0)}）→ {BANK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
