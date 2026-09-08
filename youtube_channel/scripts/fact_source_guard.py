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
    # 🔴 2026-09-08:stderr 沒一起 reconfigure,--regress 的紅字警告在 cp950 主控台變成亂碼
    # ——這道閘門自己吃過「叫聲到不了讀者」的虧(48f85da6),告警印不出來等於沒印。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"

# 事實庫(真實回測算出來的數字才准講)
FACT_FILES = ["tw_stock_facts.json", "backtest_cards.json", "tw_facts_computed.json",
              "tw_universe_facts.json", "stock_checkup_facts.json"]

# 數字比對容差:口播會四捨五入(813.7% → 「百分之八百一十三」),容差要夠寬但不能寬到失效。
TOL_ABS = 1.0      # 絕對容差(百分點)
TOL_REL = 0.02     # 相對容差 2%(大數字用,如 813.7 vs 823.1 → 差 9.4 > 813.7*0.02=16.3? 否 → 仍算相符)
# ⚠️ 上面那組容差刻意「寬」:目的是抓「憑空生成、事實庫裡連個影子都沒有」的數字,
# 不是抓四捨五入誤差。抓錯誤數字(813.7 講成 823.1)是另一個問題,交 fact_guard/人工。
#
# 🔴 2026-07-14 規模詛咒實案(三支編造片繞過守門發上線):全市場軍火入池後(89.1% 輸給
# 0050、唐鋒 -89.9、嘉澤 38.9、飆股 60%…),池從 431 → 1154,舊編造數字全部「撞上鄰居」:
#   「AI機器人 90% 回測虧損」→ 撞 89.1   「少賺 38 萬」→ 撞 38.9   任何 60 → 撞 60.0
# 教訓:**池愈大,寬容差愈危險**。兩道補強(下方 _sourced_strict 與整十數規則):
# ①假掛名句(「回測顯示…」宣稱自己實測)必須**精確**對上(嚴容差)——真引用 89.1 就該講
#   89.1,講 90 = 湊整編造。②整十數(30/40/60/70/80/90)且無近似詞 → 嚴容差(編造者
#   最愛湊整;真數據極少剛好整十,若真是 60.0 嚴容差照樣過)。
TOL_STRICT_ABS = 0.25
TOL_STRICT_REL = 0.005


def _sourced_strict(val: float, pool: set) -> bool:
    for f in pool:
        if abs(f - val) <= max(TOL_STRICT_ABS, f * TOL_STRICT_REL):
            return True
    return False

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
# 🔴 2026-07-17 補比較語境詞:「十年差434%」「高出56%」「落後636%」是比較結果宣稱,但若整句
#    沒有「報酬/賺」等詞,舊 PERF_CTX 會判定「非績效語境」→ 這個 % 根本不被抽取 → 守門看不到就放行
#    (實案:S_0050…差434 標題純「差434%」漏抽漏擋)。兩類補進來:
#    ①比較動詞(差/高出/落後…,多與 _CMP_VERB_RX 重疊)→ 讓「比較結果數字」本身被抽到、交 _is_comparison_result 攔。
#    ②比較對照詞(對/比)→ 讓比較句的**兩個操作數**(「461.8%對455.9%」)也被抽到——否則只抽到差值、
#      抽不到操作數,會把「會算給你看」的誠實片(461.8-455.9=5.9)誤殺(實案:S_EP6…差5.9 真片)。
#    加進來只擴大「會被檢查/可當算料」的數字,判定本身一字未放寬。
PERF_CTX = ("報酬", "獲利", "勝率", "成功率", "命中率", "回撤", "虧損", "賠", "賺",
            "年化", "績效", "夏普", "卡瑪", "波動", "漲", "跌", "翻倍", "倍",
            "總報酬", "累積", "複利", "終值", "機率", "比例", "佔比",
            # 🔴 2026-09-08 補基本面類(主頻道線裁示 C)。舊表沒有這幾個詞 ⇒ 子句不算「績效語境」
            # ⇒ extract_claims 直接 return ⇒ **連宣稱都不產生** ⇒ 守門看不到 ⇒ 靜默 fail-open。
            # 實測(91 支真實候選):2,659 個百分比 token 裡 141 個(5.3%)的子句不含任何 PERF_CTX 詞,
            # 而那些子句的關鍵字分佈正是 **殖利率 28 / 營收 26 / 成長 18 / 毛利 16 / 股利 14** ——
            # 恰好是 2026-09-06 捏造事故的品項清單(模板命令依序講營收→EPS→毛利→股利,
            # FinMind 斷料時 LLM 補洞)。獨立驗證員用較寬的正則量到 225/2,852 = 7.9%,
            # 幅度不同但關鍵字分佈幾乎同一組。
            # ⚠️ 這一步只讓它們**被抽出來**;抽出來之後擋不擋是池飽和的問題(另一件事)。
            "殖利率", "配息", "股利", "股息", "營收", "毛利", "淨利", "每股", "EPS",
            "年增", "月增", "季增", "成長",
            "差", "高出", "高於", "低於", "落後", "領先", "多出", "少出", "拉開", "甩開",
            "對", "比")


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
# 🔴 2026-07-28 位數 bug 修復(實測坐實):舊版寫 `\d{1,4}`,遇到 5 位數以上的百分比會**從中間
# 開始匹配**——「總報酬 34527.6%」被抽成 **4527.6**(開頭的 3 被吃掉)。這條在本頻道不是邊緣案例:
# 個股體檢講的就是 20 年長期報酬,台股 20 年破 10000% 很常見(智邦 34527.6%、川湖 7774%…)。
# 兩個方向都有害:①真值被截斷 → 池裡查無此數 → **誤擋合格影片**(實測 L_個股體檢智邦2345 正因此
# 被擋在發布外);②截斷後的殘值若剛好撞到池裡不相干的數 → 反而變成**假憑據放行**。
# 修法:①位數**完全不設上限**(`\d+`)②加 (?<!\d) 負向後查,禁止從數字中間起匹配。
# 🔴 2026-07-28 二修(獨立審查抓到我第一版的錯):第一版寫 `\d{1,7}`,對 8 位以上的百分比
# (如 `123456789%`)會**整個抽不到** → 不產生宣稱 → **靜默通過誠信閘(fail-open)**。
# 舊的 `\d{1,4}` 至少還吐個殘值 4527.6、池裡查無 → 擋下(fail-closed)。
# 也就是說我的「修復」在極端輸入上把 fail-closed 變成了 fail-open——**這是唯一絕不可以
# fail-open 的地方**。位數上限本身就是這個 bug 的來源,不該用另一個上限去修,改用 `\d+`。
_RX_PCT_ARABIC = re.compile(r"(?:百分之\s*)?(?<!\d)(\d+(?:\.\d+)?)\s*%|百分之\s*(?<!\d)(\d+(?:\.\d+)?)")
_RX_PCT_CN = re.compile(r"百分之([零一二三四五六七八九十百千兩點]+)")

# 🔴 2026-07-22 #13 產生端根治·趴/百分點盲區(實測坐實):舊版只抓「%/百分之」,但口語/書面的
# 「趴」(18趴)、「個百分點」(差314個百分點)都不帶這兩個前綴 → 整類滑過守門(元大台灣50 描述「差430趴」、
# 我重產 All-in 片「314個百分點」都落在這盲區)。這兩種是 % 的同義變體,一樣是績效宣稱、一樣要溯源。
# 只補「趴」與「(個)百分點」,不碰「倍/夏普/填息」(非%指標,溯源邏輯不同,#13④另處理)。
# 靠 extract_claims 的 PERF_CTX 語境限制 + seen_spans 去重,避免誤抓「這一點/重點」等非數字語境。
_RX_PCT_PA_ARABIC = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:趴|個?百分點|个?百分点)")  # 同上,位數不設上限
# 單字數字+趴 加負向 lookbehind:「這一趴/那一趴/第一趴」是口語(這方面),不是 1%,排除;多字數字(十八/三百一十四)照抓
_RX_PCT_PA_CN = re.compile(r"(?<![這那哪第])([零一二三四五六七八九十百千兩])\s*(?:趴|個?百分點|个?百分点)|([零一二三四五六七八九十百千兩點]{2,})\s*(?:趴|個?百分點|个?百分点)")

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
    # 🔴 2026-07-28:先移除千分位逗號。`(?<!\d)` 只擋「數字後面接數字」,擋不住逗號——
    # `1,234.5%` 會從逗號後面起匹配、抽成 234.5(和 34527.6→4527.6 是同一個「從中間切」的病,
    # 只是分隔符不同)。抽出錯值 → 池裡查無 → 誤擋合格片;或殘值撞到池裡的數 → 假憑據放行。
    # 只清「數字,數字」這種千分位,不動一般中文頓號或句讀。
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
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
    # #13 趴/百分點(% 的同義變體):「18趴」「差314個百分點」「三百一十四個百分點」——一樣要溯源
    for m in _RX_PCT_PA_ARABIC.finditer(text):
        try:
            _add(float(m.group(1)), m.group(0), *m.span())
        except Exception:  # noqa: BLE001
            pass
    for m in _RX_PCT_PA_CN.finditer(text):
        _add(_cn_num_to_float(m.group(1) or m.group(2)), m.group(0), *m.span())
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
                # 假掛名數字的預過濾必須用**嚴容差**——寬容差會讓「38萬」在抽取階段就撞上
                # 池裡的 38.9 被丟掉,後面的 assertion 嚴檢根本看不到它(2026-07-14 實案)。
                # 🔴 2026-07-17 單位化(A):這道預過濾是交接書「逃逸#2」的所在——
                # 「少賺38萬」(金額)撞上池裡不相干的 38.9(百分比)就被丟掉,宣稱根本不會產生。
                # 改成同單位子池後,金額只跟金額比 → 事實庫沒有個人損益級距的金額 → 存活到判定被擋。
                if _sourced_unit(float(val), raw, fact_pool(), True):
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


_SCOPED_CACHE: dict = {}


def fact_pool_for(slug: str, refresh: bool = False):
    """依影片主題**收窄**的事實池;認不出主題就回 None(呼叫端退回全域池)。

    🔴 2026-08-27 實測:全域 `fact_pool()` 已經長到 **33,885 個數字**
    (472 檔股票 × 每檔數十個)。拿隨機數去查:
        隨機三位數 → **100%** 找得到「憑據」
        隨機四位數 → 99%
    也就是說模型隨便編一個報酬率,守門幾乎必然替它背書。
    實例:昇陽半導體 8028 的旁白鉤子寫「總報酬竟然高達百分之九百三十」,
    而該股真值是 **740.2%**(同一份稿子的事實區就印著)——930 撞到池裡
    某支**不相干股票**的 930.54 而被放行。愛普 6531 同型(1743.9% → 寫成 2164%)。

    這不是新 bug,是**隨事實庫變大而失效**:本檔 2026-07-14 的註解記著
    「池從 431 爆到 3156 → 任何編造數字都找得到鄰居 → 守門變漏勺」,
    當時的修法是把衍生池獨立出去,但**基礎池本身**後來長了 78 倍,同一個病復發。
    所以 memory 記的「無憑據 15%→5%」那個 5% 是假的 —— 它反映的是
    「幾乎所有數字都通得過」,不是「只有 5% 有問題」。

    正解與期間偷換同一條:**A 與 B 要並排,必須來自同一組事實**。
    一支講 8028 的片,它的數字只能拿 8028 的事實當憑據。

    (0050 對照數字不必另外加白名單:checkup_three_way__<code> 的 claim 本來就
     寫在該股自己的事實裡,收窄後仍在池內。)
    """
    import re as _re
    if not slug:
        return None
    key = slug
    if key in _SCOPED_CACHE and not refresh:
        return _SCOPED_CACHE[key]
    if "個股體檢" not in slug:
        _SCOPED_CACHE[key] = None
        return None
    codes = _re.findall(r"(\d{4})", slug)
    if not codes:
        _SCOPED_CACHE[key] = None
        return None
    try:
        raw = json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))
        results = raw.get("results") or {}
    except Exception:  # noqa: BLE001
        _SCOPED_CACHE[key] = None
        return None
    # slug 裡的四位數不只代號(「存20年賺6100」也會中)→ 取**真的有事實**的那個
    pool = set()
    for c in codes:
        keys = [k for k in results if k.endswith("__" + c)]
        if not keys:
            continue
        for k in keys:
            pool |= _walk_numbers(results[k])
        break
    if not pool:
        _SCOPED_CACHE[key] = None
        return None
    _SCOPED_CACHE[key] = pool
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
    """這個數字在事實庫裡找得到(容差內)嗎?(無單位版,保留作 fail-open 退路)"""
    for f in pool:
        if abs(f - val) <= max(TOL_ABS, f * TOL_REL):
            return True
    return False


def _sourced_unit(val: float, raw: str, pool: set[float], strict: bool) -> bool:
    """**單位感知溯源(2026-07-17 上線,即觀測模式量到的「變數A」)。**

    治什麼:數字撞到**無關單位**的鄰居就被判「有憑據」——
      實案①「多賺 37 萬」(金額)撞池裡的 36.8/37.1(百分比);
      實案②已發布片口播台積電總報酬「8285.2%」(真值 8728.8%),被 8358.0/8433.0 佐證。
    改法:金額只跟金額比、百分比只跟百分比比(同單位子池),容差政策一字不動。

    🔴 **能力邊界——不要以為守門已經好了(這道只補一個洞):**
      ✅ 治得了:數字**已經被抽取出來**、但撞到無關單位鄰居而誤判有憑據。
      ❌ 治不了:**壓根沒進抽取器**的宣稱——一般句的金額(無「回測顯示」這類假掛名詞)
         完全在雷達外(交接書逃逸#1,刻意取捨)。EP1「反而多賺三十七萬」就是這種,**本道抓不到**。
      ❌ 治不了:被 **HEDGE 救援**的整句(EP6「假設每月投入1萬…多吃掉3.2萬」),
         以及**子句無 PERF_CTX 詞**就不算績效宣稱(「吃掉」不在表內)。這兩道都在單位判定**之前**。
      ⇒ EP1/EP6 那類「無假掛名詞的金額宣稱」**本道擋不住**,別把它當成已修。

    🔴 **單調收緊(structurally monotone)——2026-07-17 上線前實測抓到的近失事故:**
      第一版寫成「直接改用同單位子池判定」,結果 **9 支原本被擋的片變成放行** ——
      包含「AI策略回測勝率90」「當沖勝率80」這些正是 2026-07-14 事故、被整十數規則擋下的編造片。
      根因在**本檔自己**:`_UNIT_PCT_FRACTION` 會把 `year_return: 0.7973` ×100 = 79.73 放進 pct 子池,
      但 79.73 **從來不在無單位池裡**(那裡只有 0.7973)——**單位化憑空製造了新憑據**,反而把守門放寬。
      故本函式定義為 **`舊判定 AND 單位判定`**:單位化**只能拿掉憑據,永遠不能新增**。
      這樣「只能收緊或中性」是**結構上保證**的,不必賭我的單位推斷完全正確
      (推斷錯而多給憑據 → 被 AND 吃掉;推斷錯而少給憑據 → 就是觀測要量的誤殺)。

    fail-open:單位池建不起來/不可信 → 退回舊的無單位行為。**守門自己壞掉絕不可以害停產。**
    """
    old = _sourced_strict(val, pool) if strict else _sourced(val, pool)
    if not old:
        return False          # 舊的就判無憑據 → 維持,單位化不可能把它救回來
    try:
        tp = typed_fact_pool()
        # 單位池不可信(建置失敗、事實庫壞掉)→ 退回舊行為,而不是把全部片judged成無憑據
        if sum(len(v) for v in tp.values()) < 10 or len(tp.get("pct", ())) < 10:
            raise RuntimeError("typed pool 太小/不可信")
        # 🔴 2026-08-31 億/萬換算不對稱(實案:穩懋3105「一百八十三點三億元」被判查無來源,
        # 而 revenue_trend 事實白紙黑字寫著 183.3億元)。
        # 池那側 _units_from_string 對「億」是 `amount_wan ← v × 10000`(183.3億 → 1,833,000);
        # 宣稱這側 _unit_of_claim 只回單位、**不換算**,拿 183.3 去找 1,833,000 → 永遠找不到。
        # 兩個方向都錯:①真的億元金額一律判無憑據(fail-closed 擋發布)
        # ②反過來,某個**萬元**事實若剛好等於 183.3,編造的「183.3億」會被當成有憑據放行。
        # 這裡照池那側的同一條規則換算,讓兩邊講同一種單位。
        _u = _unit_of_claim(raw)
        _v = val * 10000.0 if (_u == "amount_wan" and "億" in (raw or "")) else val
        return _sourced_typed(_v, _u, tp, strict)[0]
    except Exception:  # noqa: BLE001
        return old


_RX_OVER = re.compile(r"(超過|逾|突破|至少|不只)\s*$")   # 「超過五百」:真值須 ≥ 宣稱值
_RX_NEAR = re.compile(r"(近|約|將近|大約|差不多|快要)\s*$")  # 「近60%」:真值在 ±15% 內
# 🔴 2026-09-08 對稱性缺口(抽樣 10 支裡 1 支的誤擋成因):_RX_OVER 有「超過/逾/突破/至少/不只」、
# _RX_NEAR 有「近/約/將近/大約」,**唯獨沒有「小於」那一邊**。
# ⇒「東台抱20年總報酬**不到80%**」(真值 78.7%,這句陳述完全正確)必然被判無憑據。
# 方向與 over 相反:真值須 ≤ 宣稱值,且不可低太多(否則「不到80%」拿真值 3% 來背書也算過)。
_RX_UNDER = re.compile(r"(不到|未達|不足|還不到|低於|不滿|沒超過|沒有超過)\s*$")


_RX_IS_QUANT = re.compile(r"[一二三四五六七八九十兩]成")


def _approx_kind(clause: str, raw: str) -> str:
    """看數字前面的字,判斷這是精確宣稱還是口語近似:'over'/'near'/''。
    2026-07-14:LLM 用真數據時常口語化——「總報酬**超過**百分之五百」(真值 589)、
    「少賺**近**60%」(真值 54.3)。這不是編造,是修辭;但方向要對:
    「超過X」要求池中真的有 ≥X 的數(說「超過90」而真值只有 82 = 說謊,照擋)。"""
    # 🔴 2026-09-08:成數(七成/八成)**本身就是近似表達**,它的近似性在數字自己身上,
    # 不在它前面 —— 舊碼只看數字前綴,所以「投資組合**跌了八成**」(真值 -83.8%)拿不到
    # 任何豁免而被擋。抽樣 10 支裡有 3 支的誤擋是這一條。放在前綴判斷之前,
    # 但「超過七成」這種前綴仍優先(下面命中 over 會覆蓋),方向資訊比模糊近似更精確。
    i = clause.find(raw)
    if i <= 0:
        return "near" if _RX_IS_QUANT.search(raw or "") else ""
    prefix = clause[max(0, i - 6): i]
    if _RX_UNDER.search(prefix):
        return "under"
    if _RX_OVER.search(prefix):
        return "over"
    if _RX_NEAR.search(prefix):
        return "near"
    return "near" if _RX_IS_QUANT.search(raw or "") else ""


# ── 比較結果數字(2026-07-17,交接書「標題層 +56% 相對差冒充總報酬」的根因修復)──────────
# 「少賺58%」「高出56%」「差434%」這種數字,宣稱的是**兩個東西之間的關係**(A 比 B 多賺/高出/差 X%),
# 不是一個獨立的事實數字。舊碼把它們當獨立數字,拿「扁平事實池裡剛好有個一樣的數」背書就放行——
# 但池裡有 3777 個**無單位**數,幾乎任何兩位數都撞得到鄰居(實測「高出56%」撞到池裡不相干的 56.0
# 就放行,而真實關係是 0056=377.9% vs 00878=230.8% → 實際高出 63.7%;56 是把相對差算錯/錯印成
# 另一個值)。這正是交接書講的同一物種:數字「存在於某處」,但**語意是錯的**。
# 判準改成:比較結果數字**只能由文本內真實操作數算得出來**(差 / 兩個方向的相對比),否則無憑據。
# 🔴 2026-09-08 修「緊貼」限制(獨立驗證員實測坐實,主頻道線裁示 B):
# 舊版要求比較動詞**緊貼**在數字前(中間只准接副詞),於是中間插一個**對照物**就整條失效:
#     「這檔的績效落後31%」      → 擋
#     「這檔的績效落後**大盤**31%」→ **放行**
#     「它的報酬高出31%」        → 擋
#     「它的報酬高出**大盤與0050整整**31%」→ **放行**
# 而財經旁白寫「落後大盤 X%」比寫「落後 X%」自然得多 ⇒ 這條規則實際攔截力遠低於帳面。
# 實測背景:它是**唯一**真的在擋百分比的規則(91 支真實候選裡被擋的 54 個百分比,54 個全來自它;
# 溯源路徑擋下 0 個),所以它可以被一句話繞開,等於百分比型完全沒有守門。
# 修法:動詞與數字之間允許一個 1~8 字的「對照物」(大盤 / 0050 / 加權指數 / 台積電…)。
# ⚠️ 兩個刻意的收斂,避免把**操作數**誤判成比較結果(那會誤擋真片):
#   ①對照物不得含「的」——擋掉「少賺**的幅度**是823%」這種(823 是操作數不是關係值)。
#   ②**單字「差」不參與對照物形式**(只保留緊貼形式)——否則「**誤差**範圍大概是31%」會命中。
#   ③視窗從 9 字放寬到 14 字(容得下動詞+副詞+對照物),不再放寬。
_CMP_ADV = r"(?:整整|了|約|近|達|高達|足足|竟|還|多|只|大約|將近)*"
_CMP_VERBS_ADJ = (r"(少賺|多賺|高出|多出|少出|落後|領先|贏過|勝過|輸給|超車|拉開|甩開|多領|少領|"
                  r"差距達|差距|相差|差了|竟差|差)")
# 對照物形式不收單字「差」(見上 ②)
_CMP_VERBS_OBJ = (r"(少賺|多賺|高出|多出|少出|落後|領先|贏過|勝過|輸給|超車|拉開|甩開|多領|少領|"
                  r"差距達|差距|相差|差了|竟差)")
# 🔴 2026-09-08 同日二修(獨立驗證員抓到的誤擋,四句可重跑):
#   「它落後大盤指數**報酬是**100%」「這檔股票落後加權指數**報酬**31%」
#   「這檔的總報酬領先0050**同期報酬**50%」「我們的策略贏過大盤**同期年化**12%」
# —— 這四句舊版放行、第一版新規則**擋**。機制:對照物把「被比較方**自己的**績效值」
# 吞進去了 ⇒ 那個數字是**操作數**不是關係值(0050 同期報酬 50% 講的是 0050,不是差距)。
# 收斂①「不得含『的』」擋不到它們(本來就沒有「的」)。
# 修法:對照物不得含**指標名詞**(報酬/年化/勝率…)也不得含「是」——
# 有指標名詞時,數字歸屬於那個指標而不是比較關係,語意上本來就該當操作數。
# ⚠️ 副作用是「落後大盤**績效**31%」這種歧義句回到舊行為(放行)。刻意的:
# 誤擋會停產(歷史事故),而歧義句本來就分不出 31 是差距還是大盤自己的值 ——
# **不確定時往舊行為靠,不要往「擋」靠。**
_CMP_METRIC = ("報酬", "年化", "勝率", "成功率", "命中率", "回撤", "殖利率", "績效",
               "波動", "夏普", "卡瑪", "配息", "股利", "股息", "營收", "毛利", "淨利",
               "EPS", "每股", "是")
_CMP_OBJ = r"(?:(?:[一-鿿0-9A-Za-z](?<!的)){1,8})"
_CMP_VERB_RX = re.compile(_CMP_VERBS_ADJ + r"\s*" + _CMP_ADV + r"\s*$")
_CMP_VERB_OBJ_RX = re.compile(_CMP_VERBS_OBJ + r"\s*" + _CMP_ADV + r"\s*"
                              + _CMP_OBJ + r"\s*" + _CMP_ADV + r"\s*$")
_CMP_WINDOW = 14


def _is_comparison_result(clause: str, raw: str) -> bool:
    """這個數字是不是**比較動詞之後的關係結果值**(而非獨立事實)。

    兩種形式都算:①緊貼(「落後 31%」)②動詞與數字之間隔一個對照物(「落後大盤 31%」)。
    視窗只看數字前 14 個字,避免把同句別處的比較詞誤扣到不相干的絕對數字上
    (「All in 823%…少賺的幅度」裡的 823 不是比較結果,是操作數,不能被擋)。"""
    i = clause.find(raw)
    if i <= 0:
        return False
    pre = clause[max(0, i - _CMP_WINDOW): i]
    if _CMP_VERB_RX.search(pre):
        return True                      # 緊貼形式:行為與 2026-09-08 之前完全相同
    m = _CMP_VERB_OBJ_RX.search(pre)
    if not m:
        return False
    # 對照物裡出現指標名詞 ⇒ 這個數字歸屬於該指標(= 被比較方的操作數),不是關係結果值
    obj = pre[m.end(1):]
    if any(w in obj for w in _CMP_METRIC):
        return False
    return True


def _rel_derivable(val: float, operands: list, loose: bool) -> bool:
    """val 是否 = 某一對操作數的『差值 / 相對比(除以任一方)』。

    兩個方向都算:「A 比 B 高出 X%」的基準可能是較大方 A 也可能是較小方 B,(A-B)/A 與 (A-B)/B
    都是合法算法。舊 _diff_ok 只除以較大方(grounded[j]),會誤殺「0056 高出 00878 63.7%」這種
    **以基準(較小方)計的真句**——那不是編造,是正確的相對差。容差沿用 production 寬容差
    (1.0 / 2%,帶口語近似詞放寬 15%)。呼叫端須先把 val 自身從 operands 排除,避免自我循環湊數。
    ⚠️ 方向只能是**要求算得出來才放行**;算不出來一律當無憑據擋下(fail-safe 拿掉數字,不新增憑據)。"""
    tol_rel = 0.15 if loose else TOL_REL
    n = len(operands)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = operands[i], operands[j]
            d = abs(a - b)
            if d <= 0:
                continue
            if abs(d - val) <= max(TOL_ABS, d * tol_rel):                 # 差值:1050-479.5=570.5
                return True
            for base in (a, b):                                          # 相對比(兩向):除以 A 或 B
                if base > 0:
                    r = d / base * 100
                    if abs(r - val) <= max(TOL_ABS, r * tol_rel):
                        return True
    return False


def _unit_subpool(raw: str, pool: set[float]) -> set:
    """近似詞豁免(「總報酬超過500%」)要查的池:同單位子池 **∩ 原池**。

    交集是刻意的:同 _sourced_unit 的理由——單位子池含 ×100 正規化後的新值,
    直接拿去給豁免路徑查會**新增憑據=放寬**。取交集保證這條豁免只會比原本更嚴。
    壞掉 → 退回無單位池(fail-open)。
    """
    try:
        tp = typed_fact_pool()
        if sum(len(v) for v in tp.values()) < 10 or len(tp.get("pct", ())) < 10:
            raise RuntimeError("typed pool 太小/不可信")
        return set(tp.get(_unit_of_claim(raw), ())) & pool
    except Exception:  # noqa: BLE001
        return pool


def _sourced_approx(val: float, kind: str, pool: set[float]) -> bool:
    """近似詞的方向性溯源:over → p∈[val, val*1.25];near → p 於 val±15%;under → p∈[val*0.75, val]。"""
    if kind == "under":
        return any(val * 0.75 <= p <= val for p in pool)
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
    grounded = sorted({c["value"] for c in claims
                       if _sourced_unit(c["value"], c["raw"], pool, False)})
    # 比較結果數字的操作數只收**嚴容差直接溯源**的真事實(不靠假見證進池),當「會算給你看」的原料。
    grounded_strict = sorted({c["value"] for c in claims
                              if _sourced_unit(c["value"], c["raw"], pool, True)})

    def _diff_ok_strict(val: float) -> bool:
        """嚴容差版文本內差值(給假掛名句用):組成數字同場 + 精度 max(0.25, 0.5%)。"""
        for i in range(len(grounded)):
            for j in range(i + 1, len(grounded)):
                dd = abs(grounded[j] - grounded[i])
                if dd > 0 and abs(dd - val) <= max(TOL_STRICT_ABS, dd * TOL_STRICT_REL):
                    return True
                if dd > 0 and grounded[j] > 0:
                    rr = dd / grounded[j] * 100
                    if abs(rr - val) <= max(TOL_STRICT_ABS, rr * TOL_STRICT_REL):
                        return True
        return False

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
        kind = _approx_kind(c["clause"], c["raw"])
        # 🔴 規模詛咒補強(2026-07-14,三支編造片繞過守門的實案):
        # ①假掛名句(【假掛名·回測顯示】)宣稱「這數字是我實測的」→ 必須**精確**對上(嚴容差)。
        #   真引用 89.1% 就該講 89.1,講「90」= 湊整編造(90 撞 89.1 的寬容差正是漏洞)。
        # ②整十數(30/40/50/60/70/80/90)且無近似詞 → 嚴容差。編造者最愛湊整;
        #   真數據極少剛好整十(若池裡真有 60.0,嚴容差照樣通過,不誤傷)。
        is_attr = c["clause"].startswith("【假掛名")
        is_round10 = (c["value"] % 10 == 0 and 10 <= c["value"] <= 100 and not kind)
        if is_attr:
            # 假掛名句 = 宣稱「這是我實測的數字」:嚴容差。唯一豁免 = **嚴容差版文本內差值**
            # (「回測顯示差距達434%」而文內就有 813.7 與 379.9,433.8≈434 精度 0.25 內 → 合法算術;
            # 「少賺38萬」文內湊不出 38±0.25 的精確差 → 編造照擋)。寬容差差值豁免仍然不給
            # (實測 38 曾被寬容差 1.0 的差值撈回)。
            if _sourced_unit(c["value"], c["raw"], pool, True) or _diff_ok_strict(c["value"]):
                continue
            bad.append(c)
            continue
        # 🔴 比較結果數字(交接書「標題層 +56% 相對差冒充總報酬」根因):「少賺58%」「高出56%」「差434%」
        # 宣稱的是**兩者關係**,不是獨立事實。改成只能由文本內真實操作數算得出來(差/兩向相對比,
        # 嚴容差操作數且排除自身),算不出來 = 無憑據。舊碼在 line「_sourced_unit(...False)」用扁平池
        # 同數字見證放行(3777 個無單位數幾乎每個兩位數都撞得到)——那正是假憑據來源。這條攔在其前面,
        # 讓比較數字**繞不過**關係驗證。fail-safe 方向只擋下發布、絕不新增憑據。
        if _is_comparison_result(c["clause"], c["raw"]):
            _ops = [o for o in grounded_strict
                    if abs(o - c["value"]) > max(TOL_STRICT_ABS, o * TOL_STRICT_REL)]
            if _rel_derivable(c["value"], _ops, loose=bool(kind)):
                continue
            bad.append(c)
            continue
        if is_round10:
            if _sourced_unit(c["value"], c["raw"], pool, True):
                continue
        elif _sourced_unit(c["value"], c["raw"], pool, False):
            continue
        in_diff = any(w in c["clause"] for w in _DIFF_CTX)
        # 差值語境 → 文本內驗算(組成數字必須在場);帶近似詞(「少賺近60%」)放寬到 ±15%
        if in_diff and _diff_ok(c["value"], loose=bool(kind)):
            continue
        # 口語近似詞 → 方向性查原始池,但**只限大數值(>100,報酬率類)**:
        # 「總報酬超過500%」(真值589)是修辭;「超過七成當沖客」(≤100,人群統計)沒有這種豁免
        # ——實測 over 對小數值會撞上池裡不相干的 82 之類,語義錯配放水。
        # 🔴 2026-09-08 拿掉 `and c["value"] > 100`(主頻道線督導裁示)。
        # 舊註解的理由是「over 對小數值會撞上池裡不相干的 82 之類,語義錯配放水」——
        # ⚠️ **那個理由只在全域池(42,134 個數字)上成立**;在收窄池(中位 173 個)上不成立,
        # 而收窄池是這條線的方向。代價已量:全域池下擋片數 20→(見下方 commit 訊息實測),
        # 收窄池下把抽樣 10 支裡的 4 支誤擋全部清掉。
        if kind and _sourced_approx(c["value"], kind, _unit_subpool(c["raw"], pool)):
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


# ============================================================================
# 觀測模式(2026-07-17 建)——「只報不擋」,零風險量測單位盲區
# ============================================================================
# 🔴 被觀測的病(見 docs/fact_pool_unit_blindspot.md,本檔實測複驗過):
#   fact_pool() 把五個事實庫攤平成 2446 個**無單位 float**。_sourced()/_sourced_strict()
#   只做純數值比對 → 「多賺 37 萬」(金額)撞上池裡的「36.8 / 37.1」(百分比)就被判「有憑據」。
#   **這不是漏看,是看見了並替假數字背書**,比漏網嚴重。
#
# 本區塊做什麼:**完全不改變放行/擋下的判定**,只額外記錄一個影子判定——
#   「如果池帶單位、而且只跟**同單位子池**比對,這個宣稱會不會被擋?」
#
# 實驗設計(重要):影子判定**刻意沿用production 一模一樣的容差政策**
#   (假掛名/整十數 → 嚴容差;其餘 → 寬容差)、一樣的 HEDGE、一樣的 PERF_CTX 語境閘。
#   **唯一被改動的變數就是「單位」**。這樣觀測到的差異才能歸因於單位盲區本身,
#   而不是「順手把容差也收緊了」造成的混淆。
#
# 安全合約(這段跑在 daily_publish 發布路徑上):
#   ①任何例外一律吞掉(fail-open)——觀測壞掉絕不可影響守門;
#   ②自我熔斷:累計耗時超 _OBS_TIME_BUDGET 或連續出錯 → 本行程自動停止觀測;
#   ③只 append 小行到 STUDIO/pool_observe.jsonl,有檔案大小上限;
#   ④環境變數 FACT_POOL_OBSERVE=0 可完全關閉。
# ⚠️ 這裡的單位是**守門端「猜」的**,只能拿來當觀測/決策依據。真要收緊,單位必須由
#   事實庫產生端(tw_facts_engine / stock_checkup_facts)寫入時就標註,否則會製造
#   第二個 drift 源(同 legacy 事實庫的教訓)。

OBSERVE_LOG = STUDIO / "pool_observe.jsonl"
_OBS_LOG_MAX_BYTES = 5 * 1024 * 1024
_OBS_TIME_BUDGET = 2.0          # 每個行程最多花這麼多秒觀測,超過就熄火
_obs_spent = 0.0
_obs_errors = 0
_obs_dead = False

# ---- 事實庫欄位 → 單位(依 2026-07-17 實際 schema 盤點,非臆測)-------------
# 報酬類欄位存的是**小數**(total_return 8.045 = 804.5%),要 ×100 才是百分比
_UNIT_PCT_FRACTION = {
    "total_return", "cagr", "max_drawdown", "return", "year_return", "fwd3y_return",
    "yoy", "trough_drawdown", "drawdown", "hold_through_return", "reinvest_total_return",
    "spend_total_return", "reinvest_vs_spend_gap", "ttm_dividend_yield",
    "total_return_since_listing", "cagr_since_listing", "win_rate", "dca_return",
    "allin_return", "benchmark_return", "crash_drawdown", "recovery_return",
}
# 這些欄位本身就已經是百分比數值(gross_margin 53.2 = 53.2%)
_UNIT_PCT_PERCENT = {
    "year_return_pct", "fwd3y_return_pct", "gross_margin", "operating_margin",
    "net_margin", "roe", "roa", "dividend_yield_pct",
}
_UNIT_DURATION_YEAR = {"years", "years_since_listing", "n_full_years", "years_underwater",
                       "years_covered_n", "duration_years", "period_years"}
_UNIT_YEAR_LABEL = {"year", "years_covered", "start_year", "end_year", "peak_year",
                    "trough_year", "listing_year"}
_UNIT_RATIO = {"calmar", "sharpe", "sortino", "pe", "pb", "per", "pbr", "correlation",
               "corr", "beta"}
_UNIT_COUNT = {"n_bars", "n_sample", "n_forward_missing", "n_ttm_distributions",
               "num_trades", "n_facts", "n_stocks", "n_halvings", "n_events", "count"}
_UNIT_PRICE_TWD = {"latest_price", "peak_price", "trough_price", "from_peak_price",
                   "halved_price", "eps", "cash_dividend", "stock_dividend", "price",
                   "close", "open", "high", "low"}
_UNIT_AMOUNT_TWD = {"revenue", "net_income", "operating_income", "market_cap"}


def _unit_of_field(key: str):
    """欄位名 → 單位。回傳 (unit, scale);scale=100 表示要 ×100 轉成百分比。
    認不出來就回 (None, 1) —— **寧可不進子池,也不要猜錯汙染子池**。"""
    k = (key or "").lower()
    if k in _UNIT_PCT_FRACTION:
        return "pct", 100.0
    if k in _UNIT_PCT_PERCENT:
        return "pct", 1.0
    if k in _UNIT_DURATION_YEAR:
        return "duration_year", 1.0
    if k in _UNIT_YEAR_LABEL:
        return "year_label", 1.0
    if k in _UNIT_RATIO:
        return "ratio", 1.0
    if k in _UNIT_COUNT:
        return "count", 1.0
    if k in _UNIT_PRICE_TWD:
        return "price_twd", 1.0
    if k in _UNIT_AMOUNT_TWD:
        return "amount_twd", 1.0
    # 後綴啟發式(只收有把握的)
    if k.endswith("_pct"):
        return "pct", 1.0
    if k.endswith(("_return", "_cagr", "_drawdown", "_yield")):
        return "pct", 100.0
    if k.endswith("_price"):
        return "price_twd", 1.0
    if k.startswith("n_") or k.endswith("_count"):
        return "count", 1.0
    return None, 1.0


# 事實庫字串(claim/summary/desc/method)裡的「數字+單位」——這是**權威的口播版數字**
# (「總報酬 804.5%（年化 24.5%、最大回撤 -33.8%）」),比欄位名更貼近稿子會講的說法。
# ⚠️ 先把日期遮掉:_walk_numbers 會把 "2026-07-15" 剁成 2026/7/15 三個數丟進池
#    ——這正是池裡混進一堆無意義小整數的來源之一。
_RX_DATE_MASK = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_RX_NUM_UNIT_STR = re.compile(r"(-?\d+(?:\.\d+)?)\s*(%|倍|年|檔|支|次|筆|元|萬|億|分)")


def _units_from_string(s: str, out: dict) -> None:
    s = _RX_DATE_MASK.sub(" ", s or "")
    for m in _RX_NUM_UNIT_STR.finditer(s):
        try:
            v = float(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        u = m.group(2)
        if u == "%":
            out.setdefault("pct", set()).add(abs(v))
        elif u == "倍":
            out.setdefault("multiple", set()).add(abs(v))
        elif u == "年":
            # 「2026年」是年份標籤;「10.0 年」是期間長度——兩者是不同單位,別混
            if v == int(v) and 1900 <= v <= 2100:
                out.setdefault("year_label", set()).add(abs(v))
            else:
                out.setdefault("duration_year", set()).add(abs(v))
        elif u in ("檔", "支", "次", "筆"):
            out.setdefault("count", set()).add(abs(v))
        elif u == "元":
            out.setdefault("price_twd", set()).add(abs(v))
        elif u == "萬":
            out.setdefault("amount_wan", set()).add(abs(v))
        elif u == "億":
            out.setdefault("amount_wan", set()).add(abs(v) * 10000.0)
        elif u == "分":
            out.setdefault("score", set()).add(abs(v))


def _walk_typed_numbers(obj, key: str, out: dict) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_typed_numbers(v, k, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_typed_numbers(v, key, out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        unit, scale = _unit_of_field(key)
        if unit:
            out.setdefault(unit, set()).add(abs(float(obj) * scale))
        else:
            out.setdefault("_unknown", set()).add(abs(float(obj)))
    elif isinstance(obj, str):
        _units_from_string(obj, out)


_TYPED_POOL_CACHE: dict | None = None


def typed_fact_pool(refresh: bool = False) -> dict:
    """帶單位的事實池:{unit: set[float]}。**與 fact_pool() 完全分開,不影響現行判定。**"""
    global _TYPED_POOL_CACHE  # noqa: PLW0603
    if _TYPED_POOL_CACHE is not None and not refresh:
        return _TYPED_POOL_CACHE
    out: dict = {}
    for fn in FACT_FILES:
        p = STUDIO / fn
        if not p.exists():
            continue
        try:
            _walk_typed_numbers(json.loads(p.read_text(encoding="utf-8")), "", out)
        except Exception:  # noqa: BLE001
            pass
    _TYPED_POOL_CACHE = out
    return out


# ---- 宣稱端:帶單位的影子抽取 ---------------------------------------------
_OBS_UNIT_SUFFIX = {
    "萬": "amount_wan", "億": "amount_wan", "元": "price_twd", "塊": "price_twd",
    "倍": "multiple", "年": "duration_year", "檔": "count", "支": "count",
    "次": "count", "筆": "count", "分": "score",
}
# ⚠️ 中文斷詞陷阱(2026-07-17 第一版實測踩到):「百分之九十」會被
#    `[…百…]{1,8}` 抓到「百」+ 後綴「分」→ 誤判成 score 單位的「100 分」,
#    於是每支正常講百分比的片都爆出假的「新增擋下」。兩道防線:
#    ①「分」加 lookbehind/lookahead 排除 百分之/百分點/分鐘;
#    ②下方 observe_claims() 會先算出百分比 pass 吃掉的 span,重疊者一律跳過。
#    ③「年」不可吃到「年化」(0050**年化**報酬 → 曾被解成「0050 年」這個期間宣稱)。
_RX_OBS_SUFFIXED = re.compile(
    r"([零一二三四五六七八九十百千兩點]{1,8}|\d+(?:\.\d+)?)\s*"
    r"(萬|億|元|塊|倍|年(?![化度])|檔|支|次|筆|(?<!百)分(?![之點鐘析]))")


def _unit_of_claim(raw: str) -> str:
    """現行 extract_claims() 產出的宣稱 → 單位。用於「只把池單位化、抽取器完全不動」的量測。"""
    r = raw or ""
    if "%" in r or "百分之" in r or "成" in r:
        return "pct"
    for suf, unit in (("億", "amount_wan"), ("萬", "amount_wan"), ("倍", "multiple"),
                      ("檔", "count"), ("支", "count"), ("次", "count")):
        if suf in r:
            return unit
    return "pct"


def observe_claims(text: str) -> list[dict]:
    """影子抽取:抽出**帶單位**的績效宣稱(含現行抽取器看不到的金額/元/年/倍)。

    比 extract_claims() 廣的地方,正是現行三道逃逸口:
      ①一般句的金額(現行只在「回測顯示」假掛名句內抽金額)
      ②「元/年/分」不在 _RX_NUM_IN_ATTR 單位表
      ③假掛名句的預過濾(_sourced_strict 撞無關百分比)會在抽取階段就丟掉宣稱
    語境閘(PERF_CTX)與 HEDGE 沿用 production,確保差異只來自「單位」這一個變數。
    """
    text = text or ""
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    pct_spans: list[tuple[int, int]] = []

    def _add(val, raw, unit, i, j):
        if val is None or (i, j) in seen:
            return
        cl = _clause(text, i, j)
        if not any(w in cl for w in PERF_CTX):
            return
        if any(h in cl for h in HEDGE):
            return
        seen.add((i, j))
        out.append({"value": float(val), "raw": raw, "unit": unit,
                    "clause": cl.strip()[:110],
                    "attr": any(a in cl for a in _ATTRIBUTION)})

    for m in _RX_PCT_ARABIC.finditer(text):
        num = m.group(1) or m.group(2)
        pct_spans.append(m.span())
        try:
            _add(float(num), m.group(0), "pct", *m.span())
        except Exception:  # noqa: BLE001
            pass
    for m in _RX_PCT_CN.finditer(text):
        pct_spans.append(m.span())
        _add(_cn_num_to_float(m.group(1)), m.group(0), "pct", *m.span())
    for m in _RX_CN_QUANT.finditer(text):
        pct_spans.append(m.span())
        _add(_CN_QUANT_PCT[m.group(1)], m.group(0), "pct", *m.span())
    for m in _RX_OBS_SUFFIXED.finditer(text):
        i, j = m.span()
        # 已被百分比 pass 吃掉的文字不再用後綴規則重解一次(「百分之九十」≠「一百分」)
        if any(i < pj and pi < j for pi, pj in pct_spans):
            continue
        tok, suf = m.group(1), m.group(2)
        val = float(tok) if re.fullmatch(r"\d+(?:\.\d+)?", tok) else _cn_num_to_float(tok)
        if val is None:
            continue
        unit = _OBS_UNIT_SUFFIX[suf]
        if suf == "億":
            val *= 10000.0
        if suf == "年" and val == int(val) and 1900 <= val <= 2100:
            unit = "year_label"
        _add(val, m.group(0), unit, *m.span())
    return out


def _sourced_typed(val: float, unit: str, tpool: dict, strict: bool) -> tuple[bool, list]:
    """同單位子池溯源。容差政策**與 production 相同**(strict 與否),只多了「單位」這個維度。"""
    sub = set(tpool.get(unit, ()))
    if unit == "multiple":
        # 合法衍生:總報酬 625.1% ⇔ 7.25 倍。不給這條,鴻海「7.3倍」會被誤殺(交接書已警告)
        sub |= {1.0 + p / 100.0 for p in tpool.get("pct", ()) if p > -100}
    if unit == "pct":
        sub |= {(m - 1.0) * 100.0 for m in tpool.get("multiple", ()) if m > 0}
    if not sub:
        return False, []
    ta, tr = (TOL_STRICT_ABS, TOL_STRICT_REL) if strict else (TOL_ABS, TOL_REL)
    hits = [p for p in sub if abs(p - val) <= max(ta, abs(p) * tr)]
    return bool(hits), sorted(hits)[:3]


def observe_pool_only(text: str, pool: set[float] | None = None) -> list[dict]:
    """量測 **A:只把池單位化,抽取器一個字都不動**(這才是交接書真正提的修法)。

    🔴 為什麼要跟 observe_text() 分開:第一版把兩件事混在一起量,結論會嚴重高估誤殺——
       observe_claims() 為了看見「37萬」把抽取面擴大到 元/年/檔/次(一般句也抽),
       那正是交接書標為 ❌ 錯誤修法 的東西(會抓到「分十次喝湯加鹽」這種比喻、
       「假設投入五十萬」這種本金舉例)。兩個變數一起動 = 歸因不了。
       本函式只動「單位」這一個變數:宣稱集合 = 現行 extract_claims() 原封不動的產出。
    """
    pool = fact_pool() if pool is None else pool
    tpool = typed_fact_pool()
    cur_bad = {round(c["value"], 4) for c in unsourced_claims(text, pool)}
    out = []
    for c in extract_claims(text):
        if any(h in c["clause"] for h in HEDGE):
            continue
        unit = _unit_of_claim(c["raw"])
        is_attr = c["clause"].startswith("【假掛名")
        strict = is_attr or (c["value"] % 10 == 0 and 10 <= c["value"] <= 100)
        ok, hits = _sourced_typed(c["value"], unit, tpool, strict)
        if not ok and round(c["value"], 4) not in cur_bad:
            out.append({"value": c["value"], "unit": unit, "raw": c["raw"],
                        "clause": c["clause"], "attr": is_attr,
                        "subpool_size": len(tpool.get(unit, ())),
                        "legacy_false_witness": sorted(
                            [p for p in pool if abs(p - c["value"])
                             <= max(TOL_STRICT_ABS, abs(p) * TOL_STRICT_REL)])[:3]})
    return out


def observe_text(text: str, pool: set[float] | None = None) -> dict:
    """影子判定 vs 現行判定的差異。**純計算,無副作用。**

    回傳兩組數字,別混用:
      newly_blocked      = A+B(池單位化 **且** 抽取面擴大)——上限值,含大量比喻/本金誤抓
      newly_blocked_pool = A(只把池單位化)——**決策要看這個**
    """
    pool = fact_pool() if pool is None else pool
    tpool = typed_fact_pool()
    cur_bad = {(round(c["value"], 4)) for c in unsourced_claims(text, pool)}
    newly, kept = [], []
    for c in observe_claims(text):
        strict = c["attr"] or (c["value"] % 10 == 0 and 10 <= c["value"] <= 100)
        ok, hits = _sourced_typed(c["value"], c["unit"], tpool, strict)
        rec = {"value": c["value"], "unit": c["unit"], "raw": c["raw"],
               "clause": c["clause"], "attr": c["attr"],
               "typed_sourced": ok, "typed_hits": hits,
               "current_flagged": round(c["value"], 4) in cur_bad,
               "subpool_size": len(tpool.get(c["unit"], ()))}
        if not ok and not rec["current_flagged"]:
            # 現行放行、單位化後會擋 → 這就是「若收緊會新增擋下」的那一筆
            legacy_hits = sorted([p for p in pool
                                  if abs(p - c["value"]) <= max(TOL_STRICT_ABS,
                                                                abs(p) * TOL_STRICT_REL)])[:3]
            rec["legacy_false_witness"] = legacy_hits   # 現行是被「哪些無關數字」佐證的
            newly.append(rec)
        elif ok:
            kept.append(rec)
    return {"newly_blocked": newly, "typed_ok": kept,
            "newly_blocked_pool": observe_pool_only(text, pool),
            "current_blocked": bool(cur_bad), "typed_blocked": bool(newly) or bool(cur_bad)}


def observe_slug(slug: str, pool: set[float] | None = None) -> dict:
    d = observe_text(slug_text(slug), pool)
    d["slug"] = slug
    return d


def _obs_write(rec: dict) -> None:
    try:
        if OBSERVE_LOG.exists() and OBSERVE_LOG.stat().st_size > _OBS_LOG_MAX_BYTES:
            return
        OBSERVE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with OBSERVE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _observe_hook(slug: str, pool, result) -> None:
    """掛在 check_slug 上的觀測鉤。**絕不 raise、絕不改 result、超支自動熄火。**"""
    global _obs_spent, _obs_errors, _obs_dead  # noqa: PLW0603
    if _obs_dead:
        return
    import os
    import time as _t
    if os.environ.get("FACT_POOL_OBSERVE", "1") == "0":
        _obs_dead = True
        return
    t0 = _t.time()
    try:
        d = observe_text(slug_text(slug), pool)
        # 只在**變數A**(只單位化池,交接書的正解)有差異時落一筆——那才是決策要的訊號。
        # 變數A+B(擴大抽取面)只記個數:實測 334 支語料會噴 85 支,絕大多數是比喻/本金誤抓,
        # 全寫進 log 只會把真訊號淹掉。
        if d["newly_blocked_pool"]:
            _obs_write({"ts": _t.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "delta", "slug": slug,
                        "current_blocked": bool(result), "typed_would_block": True,
                        "newly_blocked_pool": d["newly_blocked_pool"][:6],
                        "n_extended_only": len(d["newly_blocked"])})
    except Exception:  # noqa: BLE001
        _obs_errors += 1
        if _obs_errors >= 3:
            _obs_dead = True
    finally:
        _obs_spent += _t.time() - t0
        if _obs_spent > _OBS_TIME_BUDGET:
            _obs_dead = True


def check_slug(slug: str, pool: set[float] | None = None) -> list[dict]:
    out = unsourced_claims(slug_text(slug), pool)
    try:
        _observe_hook(slug, pool, out)     # 只記錄,不影響 out
    except Exception:  # noqa: BLE001
        pass
    return out


def pending_slugs() -> list[str]:
    """待發庫存(未發布、未被 publish_skip 擋)——複製 daily_publish.find_candidates 的選片條件。
    唯讀,不呼叫任何 API。"""
    led, skip = {}, set()
    try:
        led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    try:
        d = json.loads((STUDIO / "publish_skip.json").read_text(encoding="utf-8"))
        skip = set(d.get("slugs", {}) if isinstance(d, dict) else d)
    except Exception:  # noqa: BLE001
        pass
    out = []
    for f in list(OUT.glob("S_*.mp4")) + list(OUT.glob("L_*.mp4")):
        s = f.stem
        if s.endswith("_ytcta") or s in led or s in skip:
            continue
        if f.stat().st_size < 100 * 1024:
            continue
        out.append(s)
    return sorted(out)


def observe_report(slugs: list[str] | None = None) -> int:
    """--observe:只報不擋。回答『若現在就把池單位化收緊,會新增擋下哪幾支』。"""
    import time as _t
    pool = fact_pool()
    tpool = typed_fact_pool()
    slugs = pending_slugs() if slugs is None else slugs
    print(f"[observe] 無單位池:{len(pool)} 個")
    print("[observe] 單位化子池:" + "、".join(
        f"{u}={len(v)}" for u, v in sorted(tpool.items(), key=lambda x: -len(x[1]))))
    print(f"[observe] 待發庫存 {len(slugs)} 支\n")
    newly_a, newly_b, cur_blocked = [], [], 0
    for s in slugs:
        d = observe_slug(s, pool)
        if d["current_blocked"]:
            cur_blocked += 1
            continue
        if d["newly_blocked_pool"]:
            newly_a.append((s, d["newly_blocked_pool"]))
            print(f"  🔴 [A·只單位化池] 收緊後會新增擋下  {s[:46]}")
            for c in d["newly_blocked_pool"][:4]:
                print(f"      {c['raw']}  單位={c['unit']}(子池{c['subpool_size']}個)"
                      f"  ←「{c['clause'][:52]}」")
                if c.get("legacy_false_witness"):
                    print(f"         ⚠️ 現行是被這些**無關單位**的數字佐證的:"
                          f"{c['legacy_false_witness']}")
        if d["newly_blocked"]:
            newly_b.append(s)
    print(f"\n[observe] 現行擋下 {cur_blocked} 支")
    print(f"[observe] 變數A【只把池單位化,抽取器不動 = 交接書的正解】新增擋下 {len(newly_a)} 支")
    print(f"[observe] 變數A+B【併同擴大抽取面 = 交接書標的錯誤修法】新增擋下 {len(newly_b)} 支"
          f" ← 實測絕大多數是比喻/本金舉例的誤殺,別走這條")
    _obs_write({"ts": _t.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "summary",
                "n_slugs": len(slugs), "n_newly_blocked_pool_only": len(newly_a),
                "n_newly_blocked_extended": len(newly_b),
                "newly_pool_only": [s for s, _ in newly_a],
                "pool": {u: len(v) for u, v in tpool.items()}})
    return 0


REGRESSION_FILE = Path(__file__).resolve().parent / "fabrication_regression.json"


def regression_report() -> int:
    """跑 2026-07-13 捏造事故的原句語料,報「五句擋掉幾句」。

    🔴 為什麼要有這支:這道閘門正是為了擋那五句才存在的,而 2026-09-08 實測**五句全過**。
    **一個沒有失敗案例的閘門,沒有辦法證明任何修法有效** —— 有了它,之後每次改動都有一根
    具體的桿子:不是「看起來比較嚴了」,是「五句擋掉幾句」。

    ⚠️ **這支不接進 daily_workflow/daily_publish 的發布路徑**(刻意)。現在五句全過,
    接進去等於立刻停產。它是量尺不是閘門。
    ⚠️ 語料檔放 scripts/(進 git),不放 STUDIO/(整個目錄在 .gitignore) —— 見該檔 _position。

    回傳:0 = 全部擋下(語料清空);1 = 還有句子過得去;2 = 語料檔本身有問題。
    """
    if not REGRESSION_FILE.exists():
        print(f"[regress] ⚠️ 找不到語料檔 {REGRESSION_FILE} —— 無法證明閘門還抓得到已知案例。",
              file=sys.stderr)
        return 2
    try:
        data = json.loads(REGRESSION_FILE.read_text(encoding="utf-8"))
        cases = data["cases"]
    except Exception as exc:  # noqa: BLE001
        print(f"[regress] ⚠️ 語料檔讀不起來:{exc}", file=sys.stderr)
        return 2
    pool = fact_pool()
    print(f"[regress] 事實庫數字池 {len(pool)} 個;語料 {len(cases)} 句(全部 expect=block)")
    n_blocked = 0
    for c in cases:
        bad = unsourced_claims(c["text"], pool)
        ok = bool(bad) if c.get("expect", "block") == "block" else not bad
        n_blocked += bool(bad)
        print(f"  {'✅ 擋下' if bad else '🔴 放行'}  [{c['id']}] {c['text'][:34]}"
              + (f"  ← 無憑據 {[x['value'] for x in bad][:3]}" if bad else ""))
        if not ok and bad:
            print(f"      ⚠️ 這句 expect={c['expect']} 卻被擋 —— 誤擋,不要當成進步")
    n = len(cases)
    print(f"[regress] **{n_blocked}/{n} 擋下**"
          f"(2026-09-08 建立當下的基準是 0/{n};任何修法宣稱有效,先看這個數字有沒有動)")

    # ── 另一半:真陽性(擋對了,不可以放掉)──
    # 🔴 只有假陽性語料的閘門會被調得愈來愈鬆,只有真陽性語料的會被調得愈來愈嚴。兩半都要。
    tps = data.get("true_positives") or []
    n_kept = 0
    if tps:
        print(f"[regress] 真陽性 {len(tps)} 支(必須**仍然被擋**;它們只在收窄池下成立):")
    for tp in tps:
        pl = fact_pool_for(tp["slug"]) if tp.get("pool") == "scoped" else pool
        if not pl:
            print(f"  ⚠️ 無法驗證 [{tp['id']}] —— 收窄池建不起來(認不出主題或事實庫缺該檔)",
                  file=sys.stderr)
            continue
        hit = [round(c["value"], 4) for c in unsourced_claims(slug_text(tp["slug"]), pl)]
        ok = round(float(tp["value"]), 4) in hit
        n_kept += ok
        print(f"  {'✅ 仍擋下' if ok else '🔴 放掉了'}  [{tp['id']}] {tp['value']} "
              f"←「{tp['narration'][:40]}」  事實:{tp['fact'][:56]}")
    if tps:
        print(f"[regress] **真陽性 {n_kept}/{len(tps)} 仍被擋**")

    rc = 0
    if n_blocked < n:
        print(f"[regress] 🔴 還有 {n - n_blocked} 句過得去 —— 這道閘門擋不住它存在的理由。",
              file=sys.stderr)
        rc = 1
    if tps and n_kept < len(tps):
        print(f"[regress] 🔴 有 {len(tps) - n_kept} 支真陽性被放掉了 —— 這是回歸,"
              f"上一次修法把擋對的東西弄丟了。", file=sys.stderr)
        rc = 3
    return rc


def main() -> int:
    if "--regress" in sys.argv:
        return regression_report()
    if "--observe" in sys.argv:
        return observe_report()
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
