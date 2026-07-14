#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fact_source_guard.py — 數字溯源守門(誠信硬地板)。

**為什麼要有這支(2026-07-13 品保實案)**
頻道定位是「用真回測拆穿割韭菜神話,每個結論都有數據卡佐證」。但實測抓到長片
`L_財報季毛利率成長股…` 通篇講「根據臺股十年資料,勝率只有百分之三十一」「百分之六十七的
個股財報前三個月就反映」——查遍 tw_stock_facts / backtest_cards / scripts,**根本沒有
「毛利率選股回測」這個引擎**,數字全是 LLM 編的(還在三段給出 31/57/54 三個互相矛盾的勝率)。

**既有守門為什麼擋不住**
1. `fact_guard.py` 的績效規則只認阿拉伯數字 `\\d+%`;而 `produce_batch.py` 為了 TTS 唸法
   刻意把數字轉成中文(「百分之八十二」而非「82%」)——註解甚至明寫「也讓真數字不落進
   fact_guard 的阿拉伯數字誤判」。**等於產線從設計上繞過了自己的守門。**
2. fact_guard 的 docstring 寫「或搭 daily_publish 攔」,但 `daily_publish.py` 從來沒引用過
   fact_flags——「攔」這個動作**根本不存在**,偵測到也只是記一筆,片照發。

**這支的判準(跟 fact_guard 互補,不重複)**
fact_guard 問「這句話看起來像不像捏造」(句型規則);
本支問「**這個數字查不查得到來源**」(溯源比對):
  - 從逐字稿抽出所有「績效類數字」(百分比/倍數,阿拉伯與中文唸法都抓)
  - 跟事實庫(`STUDIO/tw_stock_facts.json` + `backtest_cards.json`)裡真實算出來的數字比對
  - 對不上 → **無憑據**(unsourced)。有誠實揭露語境(示意/假設/號稱/拆穿…)才放行。

⚠️ 不能用「有沒有數字」當判準——真實回測的數字也唸成中文百分比,那樣會連好片一起殺。
唯一正確的判準是**溯源**。

用法:
  python scripts/fact_source_guard.py --report            # 只報告(看擋下來會傷多大),不擋
  python scripts/fact_source_guard.py --report --recent 30
  from fact_source_guard import unsourced_claims          # 給 daily_publish 當發布前閘門
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"

# 事實庫(真實回測算出來的數字才准講)
FACT_FILES = ["tw_stock_facts.json", "backtest_cards.json", "tw_facts_computed.json",
              "tw_universe_facts.json"]

# 數字比對容差:口播會四捨五入(813.7% → 「百分之八百一十三」),容差要夠寬但不能寬到失效。
TOL_ABS = 1.0      # 絕對容差(百分點)
TOL_REL = 0.02     # 相對容差 2%(大數字用,如 813.7 vs 823.1 → 差 9.4 > 813.7*0.02=16.3? 否 → 仍算相符)
# ⚠️ 上面那組容差刻意「寬」:目的是抓「憑空生成、事實庫裡連個影子都沒有」的數字,
# 不是抓四捨五入誤差。抓錯誤數字(813.7 講成 823.1)是另一個問題,交 fact_guard/人工。

_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}

# 誠實揭露語境:同句內有這些 → 不是「本片斷言的事實」,是示意/假設/或在拆穿別人的宣稱 → 放行。
# 與 fact_guard._HEDGE 同一套精神(拆穿誇大回測是本頻道的常態合理題材)。
HEDGE = ("示意", "假設", "僅供參考", "僅為教學", "不代表未來", "非保證", "模擬情境",
         "純假設", "範例數字", "僅供示範", "歷史不代表", "舉例來說", "僅是舉例",
         "號稱", "聲稱", "宣稱", "拆穿", "揭穿", "破解", "陷阱", "迷思", "騙點閱",
         "唬爛", "誇大", "話術", "騙局", "以為", "別再信", "怎麼可能",
         # 以下三類是實測(2026-07-13)抓到的誤判來源,不是捏造斷言,放行:
         # ①數學恆等式(虧50%要賺100%才打平)——算得出來,不需要回測佐證
         "才能打平", "才能回本", "需要賺", "才回得來",
         # ②風險承受度的假設性門檻(「能承受至少30%的帳面虧損」)——是建議不是史實斷言
         "承受", "忍受", "扛得住", "撐得住",
         # ③明講是情境模擬(「5種市場情境實測」這類片會說「市場一路下跌30%」)
         "情境", "想像一下", "極端狀況")

# 績效語境詞:數字附近有這些才算「績效宣稱」(否則 2016 年、每月 5000 元、10 年 都會被誤抓)
PERF_CTX = ("報酬", "獲利", "勝率", "成功率", "命中率", "回撤", "虧損", "賠", "賺",
            "年化", "績效", "夏普", "卡瑪", "波動", "漲", "跌", "翻倍", "倍",
            "總報酬", "累積", "複利", "終值", "機率", "比例", "佔比")


def _cn_num_to_float(s: str) -> float | None:
    """把中文數字唸法轉成 float:八百一十三點七 → 813.7;三十一 → 31;六十七 → 67。
    只處理口播會出現的量級(個/十/百/千),夠用且不過度工程。"""
    s = s.strip()
    if not s:
        return None
    intpart, _, decpart = s.partition("點")
    total = 0
    cur = 0
    got = False
    i = 0
    while i < len(intpart):
        ch = intpart[i]
        if ch in _CN_DIGIT:
            cur = _CN_DIGIT[ch]
            got = True
        elif ch == "十":
            cur = cur if cur else 1
            total += cur * 10
            cur = 0
            got = True
        elif ch == "百":
            cur = cur if cur else 1
            total += cur * 100
            cur = 0
            got = True
        elif ch == "千":
            cur = cur if cur else 1
            total += cur * 1000
            cur = 0
            got = True
        else:
            return None
        i += 1
    total += cur
    if not got:
        return None
    val = float(total)
    if decpart:
        frac = ""
        for ch in decpart:
            if ch in _CN_DIGIT:
                frac += str(_CN_DIGIT[ch])
            else:
                break
        if frac:
            val += float("0." + frac)
    return val


# 百分比:阿拉伯(34.9% / 百分之34.9) 與 中文(百分之三十四點九)
_RX_PCT_ARABIC = re.compile(r"(?:百分之\s*)?(\d{1,4}(?:\.\d+)?)\s*%|百分之\s*(\d{1,4}(?:\.\d+)?)")
_RX_PCT_CN = re.compile(r"百分之([零一二三四五六七八九十百千兩點]+)")

# 🔴 2026-07-13 用產線剛產的新片實測抓到的破口:
# 「回測顯示...其實**七成**被手續費吃掉」「一年就少賺**三十八萬**」——
# 舊版只抓百分比,中文**成數**(七成/九成)與**金額**(三十八萬)完全在雷達外,
# 於是這支「當沖手續費」片(該主題根本沒有回測引擎、就在事實引擎的無資料黑名單裡)
# 頂著「回測顯示」的假掛名,被守門判定「可發布」。編造的兩種最常見說法都漏掉了。
# ⚠️ 只收「明確成數」(七成/九成=具體統計宣稱),**不收**口語模糊量詞。
# 實測:把「多數/大半/一半/幾乎都」也當數字,會誤擋「多數人根本撐不過中間的波動」
# 「為什麼多數人領股息反而輸掉複利」——那是口語修辭,不是統計宣稱,擋它只是找碴。
# 「超過七成當沖客年報酬不到10%」才是真正需要憑據的統計句。
_CN_QUANT_PCT = {
    "十成": 100.0, "九成": 90.0, "八成": 80.0, "七成": 70.0, "六成": 60.0,
    "五成": 50.0, "四成": 40.0, "三成": 30.0, "兩成": 20.0, "二成": 20.0, "一成": 10.0,
}
_RX_CN_QUANT = re.compile("(" + "|".join(sorted(_CN_QUANT_PCT, key=len, reverse=True)) + ")")

# 「假掛名」偵測(最狠也最準的一條):句子明講「回測顯示/根據回測/實測」——這是在宣稱
# 「這數字是我實際跑出來的」——但該數字事實庫查無來源 ⇒ 假借實測之名編造,比一般編造更嚴重
# (頻道招牌就是「用真回測拆穿割韭菜神話」)。金額(三十八萬)在一般句子裡可能只是本金舉例
# (「每天當沖兩百萬」),誤擋成本高;但只要落在「回測顯示」的掛名句裡,就必須有憑據。
_ATTRIBUTION = ("回測顯示", "根據回測", "回測結果", "回測資料顯示", "實測顯示", "實測結果",
                "數據顯示", "統計顯示", "資料顯示", "歷史資料顯示", "根據數據", "根據統計")
_RX_NUM_IN_ATTR = re.compile(r"([零一二三四五六七八九十百千兩點]{1,8}|\d+(?:\.\d+)?)\s*(萬|億|倍|次|檔|支|%)")


def _clause(text: str, i: int, j: int) -> str:
    """命中點所在的同一子句(以 。！？，、\\n 分界)。跨句的誠實揭露詞不該救援本句斷言。"""
    seps = "。！？\n"
    left = max((text.rfind(c, 0, i) for c in seps), default=-1)
    cands = [p for p in (text.find(c, j) for c in seps) if p != -1]
    right = min(cands) if cands else len(text)
    return text[left + 1: right]


def extract_claims(text: str) -> list[dict]:
    """抽出所有『績效類百分比宣稱』:{value, raw, clause}。非績效語境(年份/金額/年數)不抽。"""
    text = text or ""
    claims: list[dict] = []
    seen_spans: set[tuple[int, int]] = set()

    def _add(val, raw, i, j):
        if val is None:
            return
        if (i, j) in seen_spans:
            return
        cl = _clause(text, i, j)
        # 必須在「績效語境」裡才算宣稱(否則 2016/10年/5000元 全被誤抓)
        if not any(w in cl for w in PERF_CTX):
            return
        seen_spans.add((i, j))
        claims.append({"value": float(val), "raw": raw, "clause": cl.strip()[:90]})

    for m in _RX_PCT_ARABIC.finditer(text):
        raw = m.group(0)
        num = m.group(1) or m.group(2)
        try:
            _add(float(num), raw, *m.span())
        except Exception:  # noqa: BLE001
            pass
    for m in _RX_PCT_CN.finditer(text):
        _add(_cn_num_to_float(m.group(1)), m.group(0), *m.span())
    # 中文成數:「七成被手續費吃掉」「九成散戶會虧」——換算成百分比一樣要溯源
    for m in _RX_CN_QUANT.finditer(text):
        _add(_CN_QUANT_PCT[m.group(1)], m.group(0), *m.span())
    # 假掛名:「回測顯示…少賺三十八萬」——句子自稱是實測結果,那就必須查得到那個數字
    for attr in _ATTRIBUTION:
        start = 0
        while True:
            i = text.find(attr, start)
            if i < 0:
                break
            start = i + len(attr)
            cl = _clause(text, i, start)
            if any(h in cl for h in HEDGE):
                continue
            for m in _RX_NUM_IN_ATTR.finditer(cl):
                raw = m.group(0)
                tok = m.group(1)
                val = float(tok) if re.fullmatch(r"\d+(?:\.\d+)?", tok) else _cn_num_to_float(tok)
                if val is None:
                    continue
                if _sourced_hint(val):   # 已在事實庫→不重複列
                    continue
                claims.append({"value": float(val), "raw": raw,
                               "clause": ("【假掛名·" + attr + "】" + cl.strip())[:100]})
    return claims


def _sourced_hint(val: float) -> bool:
    """給 extract_claims 內部用的輕量溯源(避免同一數字被百分比規則與假掛名規則重複列)。"""
    try:
        return _sourced(val, fact_pool())
    except Exception:  # noqa: BLE001
        return False


def _walk_numbers(obj) -> set[float]:
    """把事實庫裡所有數值(含字串裡的數字)攤平成一個集合,當『可佐證數字池』。"""
    pool: set[float] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            pool |= _walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            pool |= _walk_numbers(v)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        pool.add(abs(float(obj)))
    elif isinstance(obj, str):
        for tok in re.findall(r"-?\d+(?:\.\d+)?", obj):
            try:
                pool.add(abs(float(tok)))
            except Exception:  # noqa: BLE001
                pass
    return pool


def _derived_numbers(entry) -> set[float]:
    """同一組事實內部數字的『合法衍生值』:兩兩差值 + 相對比例(%)。

    2026-07-14 實戰誤擋修正:題庫反轉上線後 LLM 真的在用真數據了,但它會做合法算術——
    「All in 1050% vs 定投 479.5% → 少賺 570.5%」(差值)、「少賺近 54%」(比例)。
    這些衍生數字不在原始池裡,守門就把「用真數據做的正確減法」當編造擋掉(實測晨批
    17 支被擋 5 支,其中 3 支是這種誤擋)。
    只在**同一組事實內部**做衍生(衍生計算幾乎都發生在同組,如 All in vs DCA 的差);
    跨組不做(組合爆炸且極少見,寧可漏放不亂放)。"""
    nums = sorted(_walk_numbers(entry))
    out: set[float] = set()
    n = len(nums)
    if n < 2 or n > 40:  # 單數字無衍生;超大 entry(異常)不擴,防池爆
        return out
    for i in range(n):
        for j in range(i + 1, n):
            a, b = nums[i], nums[j]
            out.add(round(abs(b - a), 1))            # 差值:1050-479.5=570.5
            if b > 0:
                out.add(round(abs(b - a) / b * 100, 1))  # 相對比例:(1050-479.5)/1050=54.3%
    return out


_POOL_CACHE: set[float] | None = None


def fact_pool(refresh: bool = False) -> set[float]:
    """事實庫裡「真的算出來過」的所有數字。空集合=事實庫還沒建起來(呼叫端要當心,別誤擋全部)。"""
    global _POOL_CACHE  # noqa: PLW0603
    if _POOL_CACHE is not None and not refresh:
        return _POOL_CACHE
    pool: set[float] = set()
    for fn in FACT_FILES:
        p = STUDIO / fn
        if not p.exists():
            continue
        try:
            pool |= _walk_numbers(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    _POOL_CACHE = pool
    return pool


_DERIVED_CACHE: set[float] | None = None


def derived_pool(refresh: bool = False) -> set[float]:
    """同組事實的衍生值池(差值/比例),**與原始池分開**。

    ⚠️ 2026-07-14 血淚教訓:第一版把衍生值直接倒進全域池,池從 431 爆到 3156——
    40 組事實兩兩差+比例幾乎鋪滿 0~100 整數空間,**任何編造數字都找得到鄰居**,
    實測連「勝率31%」「少賺38萬」這些已知編造全放行,守門變漏勺。
    正解:衍生池獨立,**只在「差值語境」的宣稱**(少賺/多賺/差距…)才查它;
    一般宣稱只查原始池。語境限縮讓衍生池的密度不至於掏空守門。"""
    global _DERIVED_CACHE  # noqa: PLW0603
    if _DERIVED_CACHE is not None and not refresh:
        return _DERIVED_CACHE
    out: set[float] = set()
    for fn in FACT_FILES:
        p = STUDIO / fn
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            entries = data.get("results") or data.get("backtests") or {}
            if isinstance(entries, dict):
                for entry in entries.values():
                    out |= _derived_numbers(entry)
        except Exception:  # noqa: BLE001
            pass
    _DERIVED_CACHE = out
    return out


# 差值語境:句子明確在講「兩者之差」時,才允許查衍生池
_DIFF_CTX = ("少賺", "多賺", "差距", "相差", "差了", "竟差", "差多少", "少領", "多領",
             "少了", "多了", "落後", "領先", "差幅")


def _sourced(val: float, pool: set[float]) -> bool:
    """這個數字在事實庫裡找得到(容差內)嗎?"""
    for f in pool:
        if abs(f - val) <= max(TOL_ABS, f * TOL_REL):
            return True
    return False


_RX_OVER = re.compile(r"(超過|逾|突破|至少|不只)\s*$")   # 「超過五百」:真值須 ≥ 宣稱值
_RX_NEAR = re.compile(r"(近|約|將近|大約|差不多|快要)\s*$")  # 「近60%」:真值在 ±15% 內


def _approx_kind(clause: str, raw: str) -> str:
    """看數字前面的字,判斷這是精確宣稱還是口語近似:'over'/'near'/''。
    2026-07-14:LLM 用真數據時常口語化——「總報酬**超過**百分之五百」(真值 589)、
    「少賺**近**60%」(真值 54.3)。這不是編造,是修辭;但方向要對:
    「超過X」要求池中真的有 ≥X 的數(說「超過90」而真值只有 82 = 說謊,照擋)。"""
    i = clause.find(raw)
    if i <= 0:
        return ""
    prefix = clause[max(0, i - 6): i]
    if _RX_OVER.search(prefix):
        return "over"
    if _RX_NEAR.search(prefix):
        return "near"
    return ""


def _sourced_approx(val: float, kind: str, pool: set[float]) -> bool:
    """近似詞的方向性溯源:over → 存在 p∈[val, val*1.6];near → 存在 p 於 val±15%。"""
    if kind == "over":
        return any(val <= p <= val * 1.25 for p in pool)  # 1.6 太寬會語義錯配,收到 1.25
    if kind == "near":
        return any(abs(p - val) <= val * 0.15 for p in pool)
    return False


def unsourced_claims(text: str, pool: set[float] | None = None) -> list[dict]:
    """回傳『查無來源的績效數字宣稱』。空 list = 全部數字都溯源得到(或本來就沒講數字)。

    放行條件(任一):
      - 同句有誠實揭露語境(示意/假設/號稱/拆穿…)→ 不是本片的事實斷言
      - 數字在事實庫容差內找得到(含同組衍生值:差/比例)→ 有憑據
      - 口語近似詞且方向正確(「超過500」而池有 589;「近60」而池有 54.3)→ 修辭非編造
    """
    pool = fact_pool() if pool is None else pool
    claims = extract_claims(text)
    # 「文本內已溯源的原始數字」——差值驗算的合法原料。
    # ⚠️ 2026-07-14 二次教訓:第一版預建全域衍生池(所有組差值/比例),池爆到 2880 個、
    # 0.1 步進幾乎連續 → 「少賺38萬」都找得到鄰居,守門變漏勺。
    # 正解:衍生值只有在**組成它的兩個原始數字就在同一篇文本裡**才算合法算術——
    # 「All in 1050% vs 定投479.5%,少賺570.5%」三個數字同場;單獨冒出的「少賺38萬」沒有原料,擋。
    grounded = sorted({c["value"] for c in claims if _sourced(c["value"], pool)})

    def _diff_ok(val: float, loose: bool) -> bool:
        tol_rel = 0.15 if loose else 0.02
        for i in range(len(grounded)):
            for j in range(i + 1, len(grounded)):
                d = abs(grounded[j] - grounded[i])
                if d <= 0:
                    continue
                if abs(d - val) <= max(1.0, d * tol_rel):          # 差值:1050-479.5=570.5
                    return True
                r = d / grounded[j] * 100                           # 比例:570.5/1050=54.3%
                if abs(r - val) <= max(1.0, r * tol_rel):
                    return True
        return False

    bad = []
    for c in claims:
        if any(h in c["clause"] for h in HEDGE):
            continue
        if _sourced(c["value"], pool):
            continue
        kind = _approx_kind(c["clause"], c["raw"])
        in_diff = any(w in c["clause"] for w in _DIFF_CTX)
        # 差值語境 → 文本內驗算(組成數字必須在場);帶近似詞(「少賺近60%」)放寬到 ±15%
        if in_diff and _diff_ok(c["value"], loose=bool(kind)):
            continue
        # 口語近似詞 → 方向性查原始池,但**只限大數值(>100,報酬率類)**:
        # 「總報酬超過500%」(真值589)是修辭;「超過七成當沖客」(≤100,人群統計)沒有這種豁免
        # ——實測 over 對小數值會撞上池裡不相干的 82 之類,語義錯配放水。
        if kind and c["value"] > 100 and _sourced_approx(c["value"], kind, pool):
            continue
        bad.append(c)
    return bad


def slug_text(slug: str) -> str:
    """一支片的全部文字(旁白逐字稿 + 標題/描述 .md)——捏造數字兩邊都可能出現。"""
    parts = []
    for suffix in (".voice.txt", ".md"):
        p = OUT / f"{slug}{suffix}"
        if p.exists():
            try:
                parts.append(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                pass
    return "\n".join(parts)


def check_slug(slug: str, pool: set[float] | None = None) -> list[dict]:
    return unsourced_claims(slug_text(slug), pool)


def main() -> int:
    recent = 40
    if "--recent" in sys.argv:
        try:
            recent = int(sys.argv[sys.argv.index("--recent") + 1])
        except Exception:  # noqa: BLE001
            pass
    pool = fact_pool()
    print(f"[fact_source_guard] 事實庫可佐證數字池:{len(pool)} 個")
    if len(pool) < 10:
        print("[fact_source_guard] ⚠️ 事實庫太小(<10 個數字)——現在若開啟硬擋,"
              "會把幾乎所有片都擋掉(產線停擺)。先把 tw_facts_engine 的真實回測灌進事實庫。")

    voices = sorted(OUT.glob("S_*.voice.txt"), key=lambda f: -f.stat().st_mtime)[:recent]
    voices += sorted(OUT.glob("L_*.voice.txt"), key=lambda f: -f.stat().st_mtime)[:10]
    n_bad = 0
    rows = []
    for f in voices:
        slug = f.stem.replace(".voice", "")
        bad = check_slug(slug, pool)
        if bad:
            n_bad += 1
            rows.append((slug, bad))
    print(f"[fact_source_guard] 掃 {len(voices)} 支,{n_bad} 支含『查無來源的績效數字』"
          f"({n_bad * 100 // max(1, len(voices))}%)")
    for slug, bad in rows[:12]:
        print(f"\n  ✗ {slug[:44]}")
        for c in bad[:3]:
            print(f"      無憑據數字 {c['value']}  ←「{c['clause']}」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
