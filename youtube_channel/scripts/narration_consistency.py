#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""narration_consistency.py — 旁白**內部一致性**檢查(不需要事實庫)。

🔴🔴 **狀態:方法成立,這份實作不堪用。不要接進任何閘門。** 🔴🔴
2026-09-08 實測:待發 82 支抓到 8 支,**逐支看下來 8 支幾乎全是誤報**(見檔尾「失敗分析」)。
`--selftest` 全綠只證明它在**我挑的句子**上會動,不證明它在真實旁白上準 ——
這正是「合成 fixture 過關 ≠ 真實語料可用」那一課。本檔目前的用途只有兩個:
①保存勤誠 8210 那個**方法**(它是真的)②記錄為什麼鄰近度配對做不到,給下一版當規格。


**為什麼要有這支(2026-09-08,勤誠 8210 實案)**
旁白說:「過去將近**十九年**,創造了高達百分之**三千九百**的總報酬。換算成年化報酬率,
這是驚人的百分之**三十點九**。」

    年化 30.9% 複利 18.6 年 = 14,865%   ← 與事實卡 14,766.3% 相符
    而總報酬 3,900% 反推年化只有 21.9%  ← 與同一句自己寫的 30.9% 不符

**兩個數字在同一段旁白裡,而它們算不起來。不需要事實卡就抓得到這個錯。**

🔴 **這正是它的價值所在:它不需要知道「這是哪一檔」。**
`per_stock_fact_gate` 要先 `resolve_code(slug)` 認出主體,所以 slug 沒代號的片
(Shorts / ETF / 大盤 / 系列彙總)結構上查不了 —— 實測待發 80 支裡 53 支(66%)認不出代號。
**本檢查對那 53 支同樣有效,因為它只需要旁白本身。**

⚠️ **能力邊界 —— 它只證明「講錯」,不證明「講對」。**
算得起來不代表數字是真的:兩個數字可以**一起錯得很一致**(例如整組都抄錯同一檔)。
⇒ 本檢查是 `fact_source_guard` / `per_stock_fact_gate` 溯源檢查的**補充,不是替代**,三道並存。

⚠️ **容差刻意寬。** 口語會說「將近十九年」(真值 18.6)、「三千九百」(真值 14,766)。
年數只要差 0.4 年,複利推算的總報酬就會差三成 —— 所以門檻不是抓四捨五入,
是抓**量級級別的矛盾**。勤誠那支是 **3.8 倍**,那才是本檢查該抓的量級。

用法:
  python scripts/narration_consistency.py --selftest        # 陽性/陰性對照
  python scripts/narration_consistency.py --slug <slug>
  python scripts/narration_consistency.py --scan            # 掃待發庫存
  from narration_consistency import check_text               # 給閘門用
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "output"

# 中文數字轉換沿用 fact_source_guard(同一套口播唸法,不另抄一份 —— 另抄一份正是
# 合規哨漂掉的成因,見 954e283c)
try:
    from fact_source_guard import _cn_num_to_float as _cn2f
except Exception:  # noqa: BLE001
    def _cn2f(s):  # 後備:載不到就只認阿拉伯數字(寧可少抓,不可以誤抓)
        return None

# ── 抽取:百分比 / 年數 / 倍數 ────────────────────────────────────────────────
# 🔴 字元類要含「萬/億」,否則正則只吃得到「一萬**四千七百六十六**」的後半 = 4766。
# 解析函式支援萬級**而正則抓不到**,是兩層各自正確、合起來錯的典型 —— selftest 修了 _val
# 之後陰性對照還是紅的,就是卡在這裡。
_NUM = r"(?:\d+(?:\.\d+)?|[零一二三四五六七八九十百千萬億兩點]+)"


def _val(tok: str):
    """中文/阿拉伯唸法 → float。

    🔴 `fact_source_guard._cn_num_to_float` 的 docstring 明寫「只處理個/十/百/千」——
    於是「百分之**一萬**四千七百六十六」會被讀成 **4766**。本頻道講的正是高報酬個股
    (勤誠 14,766%、台積電 8,285%、智邦 34,527%),萬級唸法天天出現 ⇒ 少了這一段,
    **一句完全正確的旁白會被算成 3.5 倍矛盾而誤擋**(第一版 selftest 的陰性對照就是這樣掛的)。
    ⚠️ 這裡**本地補**,不去改 `fact_source_guard` —— 那支的解析結果會改變另外兩道閘門的判定,
    而本次規格只加一道新檢查,不動既有的。
    """
    tok = (tok or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", tok):
        return float(tok)
    for unit, scale in (("億", 100000000.0), ("萬", 10000.0)):
        if unit in tok:
            hi, _, lo = tok.partition(unit)
            h = _cn2f(hi) if hi else 1.0
            if h is None:
                return None
            rest = _val(lo) if lo else 0.0
            return h * scale + (rest or 0.0)
    return _cn2f(tok)


_RX_ANNUAL = re.compile(
    r"年化(?:報酬)?(?:率)?[^0-9零一二三四五六七八九十百千兩點%]{0,6}?"
    r"(?:百分之\s*)?(" + _NUM + r")\s*%?")
# 🔴 `(?<!年化)` 是必要的:「年化報酬率」裡面含「報酬率」,少了它會把**年化值當成總報酬**
# 抓進來,於是「年化 30.9%」自己跟自己比 → 恆定誤報(selftest 第一版兩個陰性對照就是這樣掛的)。
_RX_TOTAL = re.compile(
    r"(?<!年化)(?:總報酬|總回報|報酬率|回報率|累積報酬)"
    r"[^0-9零一二三四五六七八九十百千兩點%]{0,8}?"
    r"(?:百分之\s*)?(" + _NUM + r")\s*%?")
# 🔴 中文語序有兩種,少一種就漏掉一半:
#   關鍵詞在前:「總報酬 3900%」        → _RX_TOTAL
#   數值在前  :「百分之三千九百的總報酬」→ _RX_TOTAL_PRE
# 勤誠 8210 那個實案正是後者 —— 第一版只寫了前者,陽性對照當場抓不到。
_RX_TOTAL_PRE = re.compile(
    r"(?:百分之\s*)?(" + _NUM + r")\s*%?\s*的?\s*"
    r"(?<!年化)(?:總報酬|總回報|累積報酬)")
_RX_ANNUAL_PRE = re.compile(
    r"年化(?:報酬)?(?:率)?[^0-9零一二三四五六七八九十百千兩點%]{0,14}?"
    r"(?:百分之\s*)?(" + _NUM + r")\s*%?")
_RX_YEARS = re.compile(r"(?:近|約|將近|過去|長抱|抱|持有|上市以來)?\s*(" + _NUM + r")\s*年")
_RX_TIMES = re.compile(r"(?:翻了|變成|成長|放大)?\s*(" + _NUM + r")\s*倍")

# 這個窗口是「同一段話」的近似:旁白一句約 40~70 字,前後各 150 字≈同一小節
WINDOW = 150

# 🔴 門檻:比值超過這個倍數才算矛盾。
# 為什麼是 2.0 而不是更嚴:年數的口語四捨五入(18.6 → 「將近十九年」)在複利下就會讓
# 推算總報酬差三成;年化 30.9% 少報一位小數也會差幾個百分點。2.0 容得下全部這類噪音,
# 而勤誠那支是 3.8 倍 —— 本檢查要抓的是**量級矛盾**,不是精度。
RATIO_TOL = 2.0
# 倍數關係(總報酬 8285.2% ↔ 翻了 83.85 倍)兩種讀法只差 1,容差用相對值
TIMES_TOL_REL = 0.25


_SENT_SEPS = "。！？!?；;" + chr(10)   # chr(10)=換行,避免這行被 heredoc 吃掉反斜線(踩過)


def _sentence_span(text: str, pos: int):
    """pos 所在的**同一句**(以句號類分界)。

    🔴 2026-09-08 第一版用「前後 150 字」當窗口,實測待發 81 支**抓出 29 支(36%)**,
    而逐一看幾乎都是配對配錯 —— 窗口把**不同主體/不同期間**的數字湊成一對
    (「年化 1.0% 複利 1.0 年」「總報酬 1.0%」這種明顯是把別句的殘值當操作數)。
    一個 36% 命中率的檢查不是嚴格,是壞掉:它會把真問題淹沒在雜訊裡。
    ⇒ 收緊成同一句。**寧可少抓,不可以誤抓** —— 這道檢查的價值在於「抓到就是確定的」,
    那個確定性一旦沒了,它就只是另一個要人工複核的清單。

    🔴 但「同一句」又太緊:勤誠那個實案的兩個數字**跨了一個句號**
    (「…總報酬。換算成年化報酬率,這是…三十點九。」)⇒ 同句配對抓不到它。
    ⇒ 邊界訂在**本句 + 前後各一句**:容得下「講完總報酬,下一句換算年化」這個固定講法,
    又不會跨到別的主體/期間去。
    """
    lo = max((text.rfind(c, 0, pos) for c in _SENT_SEPS), default=-1) + 1
    cands = [q for q in (text.find(c, pos) for c in _SENT_SEPS) if q != -1]
    hi = min(cands) if cands else len(text)
    # 往前後各再吃一句
    lo2 = max((text.rfind(c, 0, max(lo - 1, 0)) for c in _SENT_SEPS), default=-1) + 1
    cands2 = [q for q in (text.find(c, min(hi + 1, len(text))) for c in _SENT_SEPS) if q != -1]
    hi2 = min(cands2) if cands2 else len(text)
    return lo2, hi2


def _near(text: str, pos: int, rx: re.Pattern):
    """在 pos 所在的**同一句**裡找 rx 的命中值,依距離排序。"""
    lo, hi = _sentence_span(text, pos)
    seg = text[lo:hi]
    out = []
    for m in rx.finditer(seg):
        v = _val(m.group(1))
        if v is not None:
            out.append((abs((lo + m.start()) - pos), v, m.group(0)))
    out.sort(key=lambda x: x[0])
    return out


def check_text(text: str) -> list[dict]:
    """回傳旁白內部算不起來的數對。空 list = 沒抓到矛盾(**不等於數字是對的**)。"""
    text = (text or "").replace(",", "")
    found: list[dict] = []
    seen: set = set()

    # 關係一:年化 ^ 年數 ↔ 總報酬(複利)。兩種語序都掃。
    _tot_hits = list(_RX_TOTAL.finditer(text)) + list(_RX_TOTAL_PRE.finditer(text))
    for m in _tot_hits:
        R = _val(m.group(1))
        if R is None or R <= 0:
            continue
        ann = _near(text, m.start(), _RX_ANNUAL) or _near(text, m.start(), _RX_ANNUAL_PRE)
        yrs = _near(text, m.start(), _RX_YEARS)
        if not ann or not yrs:
            continue
        # 🔴 唯一性條件(2026-09-08 第三版):同一段裡若出現**多個**年化候選或多個總報酬候選,
        # 就無法確定哪個配哪個 —— 個股體檢旁白最常見的形狀正是「本檔 vs 0050」兩組數字並排,
        # 硬配會把兩個**各自正確**的數字湊成一個假矛盾。
        # 實測:±150 字窗口 29 支 → 相鄰句 16 支 → 加這條 → 見下方掃描結果。
        # **寧可少抓不可誤抓**:這道檢查的全部價值在於「抓到就是確定的」。
        _lo, _hi = _sentence_span(text, m.start())
        _seg = text[_lo:_hi]
        if len({round(v, 3) for v in
                (_val(x.group(1)) for x in _RX_ANNUAL.finditer(_seg)) if v is not None}) > 1:
            continue
        _tot_in_seg = {round(v, 3) for v in
                       ([_val(x.group(1)) for x in _RX_TOTAL.finditer(_seg)] +
                        [_val(x.group(1)) for x in _RX_TOTAL_PRE.finditer(_seg)]) if v is not None}
        if len(_tot_in_seg) > 1:
            continue
        r = ann[0][1]
        # 年數挑「最接近且落在合理區間」的那個(避免抓到「2008年」這種年份)
        n = next((v for _, v, _ in yrs if 1.0 <= v <= 60.0), None)
        # 合理值域護欄:年化 <0.5% 或 >100% 多半是抓到殘值/別的東西;總報酬 <5% 同理。
        # (實測誤報樣態:「年化 1.0% 複利 1.0 年」「總報酬 1.0%」)
        if n is None or r is None or not (0.5 <= r <= 100.0) or R < 5.0 or n < 2.0:
            continue
        implied = ((1.0 + r / 100.0) ** n - 1.0) * 100.0
        if implied <= 0 or R <= 0:
            continue
        ratio = max(implied / R, R / implied)
        if ratio > RATIO_TOL:
            k = ("compound", round(R, 2), round(r, 2), round(n, 2))
            if k in seen:
                continue
            seen.add(k)
            found.append({
                "kind": "年化×年數 ↔ 總報酬",
                "stated_total": R, "annual": r, "years": n,
                "implied_total": round(implied, 1), "ratio": round(ratio, 2),
                "clause": text[max(0, m.start() - 70): m.start() + 60].replace("\n", " "),
                "why": (f"年化 {r}% 複利 {n} 年 = {implied:,.1f}%,而旁白說總報酬 {R}%"
                        f"(差 {ratio:.1f} 倍)"),
            })

    # 關係二:總報酬 ↔ 倍數(8285.2% ↔ 翻了 83.85 倍;兩種讀法差 1,容差吸收)
    for m in _tot_hits:
        R = _val(m.group(1))
        if R is None or R <= 0:
            continue
        tms = _near(text, m.start(), _RX_TIMES)
        if not tms:
            continue
        x = tms[0][1]
        if x is None or x <= 0:
            continue
        for expect in (R / 100.0, R / 100.0 + 1.0):      # 兩種合理讀法任一符合就放行
            if abs(x - expect) <= max(TIMES_TOL_REL * max(expect, 1.0), 0.5):
                break
        else:
            k = ("times", round(R, 2), round(x, 2))
            if k in seen:
                continue
            seen.add(k)
            found.append({
                "kind": "總報酬 ↔ 倍數",
                "stated_total": R, "stated_times": x,
                "implied_times": round(R / 100.0 + 1.0, 2),
                "ratio": round(max(x, R / 100.0 + 1.0) / max(min(x, R / 100.0 + 1.0), 1e-9), 2),
                "clause": text[max(0, m.start() - 70): m.start() + 60].replace("\n", " "),
                "why": f"總報酬 {R}% 等於 {R/100.0+1.0:.2f} 倍,而旁白說 {x} 倍",
            })
    return found


# ── 陽性/陰性對照(沒有對照的檢查,和恆定輸出無法區分)────────────────────────
_POS = [
    ("勤誠8210·實案", "過去將近十九年,創造了高達百分之三千九百的總報酬。"
                      "換算成年化報酬率,這是驚人的百分之三十點九。"),
    ("合成·倍數矛盾", "近二十年含息還原總報酬 8285.2%,100 萬變成約 8385 萬,翻了 5 倍。"),
]
_NEG = [
    ("勤誠·正確版", "過去將近十九年,創造了高達百分之一萬四千七百六十六的總報酬。"
                    "換算成年化報酬率,這是驚人的百分之三十點九。"),
    ("台積電·真實句", "近二十年含息還原總報酬 8285.2%,100 萬變成約 8385 萬,翻了 83.85 倍。"),
    ("口語近似·年數四捨五入", "近十年總報酬 730%,年化報酬率大約 23.6%。"),
    ("只有一個數字", "這檔股票近二十年的總報酬是百分之四百五十七點三。"),
    ("沒有數字", "長期投資最難的不是選股,是抱得住。"),
]


def selftest() -> int:
    bad = 0
    print("[selftest] 陽性對照(必須抓到):")
    for name, t in _POS:
        hits = check_text(t)
        ok = bool(hits)
        bad += (not ok)
        print(f"  {'✅' if ok else '🔴'} {name}" + (f" → {hits[0]['why']}" if hits else " → 沒抓到"))
    print("[selftest] 陰性對照(必須放行):")
    for name, t in _NEG:
        hits = check_text(t)
        ok = not hits
        bad += (not ok)
        print(f"  {'✅' if ok else '🔴'} {name}" + ("" if ok else f" → 誤報 {hits[0]['why']}"))
    print(f"[selftest] {'全部通過' if not bad else f'🔴 {bad} 項不符'}")
    return 0 if not bad else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    import fact_source_guard as fsg
    if "--slug" in sys.argv:
        slug = sys.argv[sys.argv.index("--slug") + 1]
        hits = check_text(fsg.slug_text(slug))
        for h in hits:
            print(f"🔴 {h['kind']}:{h['why']}\n   「{h['clause'][:80]}」")
        print(f"[narration_consistency] {slug[:44]}:{len(hits)} 處內部矛盾")
        return 1 if hits else 0
    if "--scan" in sys.argv:
        slugs = fsg.pending_slugs()
        n_bad = 0
        for s in slugs:
            t = fsg.slug_text(s)
            if not t:
                continue
            hits = check_text(t)
            if hits:
                n_bad += 1
                print(f"🔴 {s[:46]}｜{hits[0]['why']}")
        print(f"[narration_consistency] 掃 {len(slugs)} 支,{n_bad} 支有內部矛盾")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# ══════════════════════════════════════════════════════════════════════════════
# 失敗分析(2026-09-08)—— 為什麼鄰近度配對做不到,給下一版當規格
# ══════════════════════════════════════════════════════════════════════════════
# 收斂過程(每一步都用同一份待發語料量):
#   ±150 字窗口          → 抓 29/82 支
#   相鄰一句             → 抓 16/82 支
#   + 唯一性(段內只准一個年化候選、一個總報酬候選) → 抓  8/82 支
#
# 而那 8 支**逐支看下來幾乎全是誤報**,兩個主要形狀:
#
# ① **年數抓錯**(最主要)。旁白句裡有一堆數字後面接「年」——「二零一六年」「十年」「六年」,
#    而 _RX_YEARS 只做了 1~60 的值域過濾,擋不掉「共同起點 2016 年」被切成 16、
#    或別句的「六年」。實例:上海商銀「總報酬 139.4%、年化 9.1%」——那是 **10 年**的正確組合
#    (139.4% ÷ 10 年 ≈ 9.1%),而配對抓到 years=6.0 → 假矛盾。聯電、嘉澤同型。
#    ⇒ **這三支旁白本身是對的,是我的抽取器製造了矛盾。**
#
# ② **「X倍」被當成「總報酬 X%」**。「總報酬接近**十倍**」被讀成總報酬 10.0%,
#    再跟「十倍」比 → 假矛盾。加密網格那支的「報酬率高達**九倍**」同型。
#
# 🔴 共同根因:**鄰近度不是語意關係**。這條線的旁白最常見的結構就是
# 「本檔 X% vs 0050 Y%」「All-in A% vs 定期定額 B%」——**兩組各自正確的數字並排**,
# 任何靠距離配對的做法都會把它們湊成一對。而 09-08 的教訓正好是同一個形狀:
# 我把 checkup_crash 的三個崩盤視窗壓平成一筆,也是「看起來在一起就當成一件事」。
#
# ⇒ **下一版的規格不是調容差,是換綁定方式:**
#   (a) 只接受**固定模板**:事實卡的講法是「總報酬 X%(年化 Y%、最大回撤 Z%)」,
#       正確的旁白會照抄這個結構 —— 只在這個模板命中時才判,其餘一律不判(低召回、高精確)。
#   (b) 年數必須來自**與總報酬同一個逗號子句**,而且要能對上「近X年/X.X年」這種明確期間詞,
#       不可以吃「二零一六年」這種日期。
#   (c) 「倍」與「%」要分開抽,不可以共用 _NUM 後就靠上下文猜。
#   (d) 驗收改成:**對真實語料的精確率**(抓到的裡面有幾支真的是矛盾),
#       不是 selftest 綠不綠。合成 fixture 全綠而真實語料 0/8,那個 selftest 沒有資訊量。
