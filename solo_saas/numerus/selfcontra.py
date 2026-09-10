# -*- coding: utf-8 -*-
"""同稿自相矛盾:一支稿子對**同一標的、同一指標、同一策略**給出兩個不一樣的值。

為什麼是這一題(而不是「這個數字對不對」):
    比對外部事實庫的守門已經被自己的事實庫餵到失效
    (memory `yt-fact-guard-pool-saturation`:全域池 38,231 個數字,
     隨機 400 個百分比通過率 100%)。
    **這支不查外部事實,只查同一份文件內部一不一致** ——
    沒有事實庫、沒有 LLM、沒有網路,所以那個失效模式對它結構上不成立。

它只報告,不阻斷。升級成閘門的條件見 GATE_UPGRADE_CRITERIA.md,目前一條都不成立。

🔴 這支的每一條規則都是從**真實語料的誤報**倒推出來的,不是想出來的。
   規則旁邊的註解寫的是「哪一支稿子逼出了這條」——因為下一個人想放寬它時,
   需要知道放寬會把哪一支放回來。
"""

import re

from .zhnum import UNIT_PCT, parse_numbers

# 主體:對照組 0050。觀眾最會去查的就是這一格(memory `yt-period-swap-integrity`)。
SUBJECT_ALIASES = ("0050", "元大台灣50", "元大臺灣50", "元大台灣五十", "元大臺灣五十")

SEG = re.compile(r"[。!?！？;；\n]+")

# --- 量度 -----------------------------------------------------------------
# 離數字最近的那一個贏,而且**長的優先**。
# 「年化報酬 23%」若讓「報酬」贏,年化就被判成總報酬。
_METRIC_PAT = [
    ("annual", ("年化報酬率", "年化報酬", "年化")),
    # 🔴「最大虧損」是啟碁 6285 那支逼出來的:少了它,
    #    「年化二十二點九趴,最大虧損三十三點八趴」的 33.8 會被當成第二個年化值。
    ("dd", ("最大回撤", "最大虧損", "最大跌幅", "回撤", "跌幅", "虧損", "腰斬")),
    ("total", ("總報酬率", "總報酬", "累積報酬", "報酬率", "報酬", "漲幅")),
    ("delta", ("落後", "領先", "差距", "多賺", "少賺", "相差")),
    ("other", ("卡瑪", "殖利率", "波動", "標準差", "勝率", "毛利率", "折價",
               "配息", "本益比", "股息")),
]
# ⚠️ 這張表裡**不准放數量詞**(只有/剩/贏/輸/高達…)。
#    我加過「只有」,當場靜默放掉兩個已知真陽性 —— 3081 和 6223 兩支的句子都是
#    「年化報酬**只有**百分之十點一」,量度詞被夾在中間就再也配不到 annual。
#    抓到它的唯一原因是拿真案例當陽性對照。
_RX_METRIC = re.compile("|".join(
    re.escape(w) for _k, ws in _METRIC_PAT for w in ws))
_WORD2KIND = {w: k for k, ws in _METRIC_PAT for w in ws}

# --- 策略 -----------------------------------------------------------------
# 🔴 這是誤報的**最大單一來源**:同一支 0050 的「一次投入」和「定期定額」
#    本來就該是兩個不同的數字,把它們湊在一起比,得到的是一整批假陽性
#    (0050定投vs一次Allin、當沖手續費、S_0050定投10年、達明4585…)。
#
# 只分兩桶,而且**沒有標記的算 lump**:
#   一次投入 / 買進持有 / 長抱 —— 對一支 ETF 來說是同一件事,合成 lump。
#   定期定額 —— 現金流不同,是真的另一個數。
# ⚠️ 曾經把 allin 和 hold 分開,結果當場放掉真陽性旺矽 6223:
#    同一稿裡「買進持有 0050 年化 23.1%」對上「改 All in 0050 年化 11.4%」,
#    分兩桶就變成「各講各的」。對單筆買進的 ETF,那兩個詞指的是同一件事。
_STRATEGY_PAT = [
    ("dca", ("定期定額", "定額投資", "定投", "每月扣款", "月月扣", "每月固定投入",
             "月底扣款", "分批投入")),
    ("lump", ("一次all in", "一次 all in", "all-in", "all in", "allin",
              "buy & hold", "buy&hold",
              "一次性投入", "一次性將", "一次投入", "單筆投入", "一次投入",
              "買進持有", "長抱", "無腦買", "不動如山")),
]
_RX_STRATEGY = re.compile("|".join(
    re.escape(w) for _k, ws in _STRATEGY_PAT for w in ws))
_WORD2STRAT = {w: k for k, ws in _STRATEGY_PAT for w in ws}
DEFAULT_STRATEGY = "lump"

# --- 熄火條件 -------------------------------------------------------------
# ① 列舉句:「X 三種買法對決:ALL IN / 定期定額 / 0050:…ALL IN 538.6%(年化 20.4%)…」
#    0050 只是清單裡的最後一項,後面的數字全是**別人的**。這種句子沒有可靠的
#    歸屬線索,整句放掉比猜好。(富邦金 2881、雷科 6207、湧德 3689 都是這一型)
_RX_ENUM = re.compile(r"[兩二三四五]種買法|分別表現|分別為|對決[：:]")

# ② 轉換句:「年化報酬會從 16.9 提升到 19.2」「年化報酬略降至 8.8」——
#    兩個值是同一句話裡的前後,不是矛盾。(美股ETF定期定額vs臺股0050、財報季毛利率)
_RX_TRANSITION = re.compile(
    r"提升到|提高到|增加到|上升到|拉到|拉高到|降到|降至|下降到|掉到|變成|跳到|"
    r"提升至|下修到|修正到")

# ③ 模糊值:「兩成多」「約兩成」「百分之八起跳」——這是口語的量級,不是一個讀數。
#    模糊值**不能單獨造成一次標記**,只能當旁證。(禾伸堂 3026、友達 2409、美股ETF)
#    ⚠️ 判準只認「這個數字本身粗」,不認「句子裡有個約字」:
#       「年化報酬約為百分之十點一」是精確宣稱,把它當模糊會放掉台積電那支真陽性。
_RX_VAGUE_TAIL = re.compile(r"^(?:多|出頭|起跳|左右|上下)")
# 比較下界/上界也不是讀數:「它的長期年化報酬率也**遠高於**百分之三點六」
# 那句話沒有宣稱 0050 年化是 3.6%,它宣稱的是「比 3.6% 高」。(大同 2371)
_RX_BOUND = re.compile(r"高於|低於|超過|不到|不足|至少|最少|多於|少於|大於|小於")

# ④ 資料來源不是主體:「在 2010-2015 年的 0050 歷史資料中…年化報酬率達到 20%」
#    —— 20% 是那個 AI 策略的,0050 只是資料來源。(AI策略回測那支)
_RX_AS_DATASOURCE = re.compile(r"^(?:歷史資料|資料|數據|走勢|報價|行情)")

# ⑤ 別人的名字:「而台積電的報酬率假設為 500%,年化報酬假設為 30%」
#    —— 30% 掛在台積電名下。代碼邊界抓不到中文名。(華邦電 2344)
_RX_FOREIGN_NAME = re.compile(
    r"[一-鿿]{2,4}(?=的(?:報酬|年化|總報酬|績效|表現))")

# 省略式比較句:「安勤的**年化報酬率**高達 24.8,**而 0050 則是** 11.7」——
# 量度詞只講一次,掛在前一個實體上,後面那個實體靠一個繫詞接過去。
# 🔴 這一格是有代價的:量度詞必須落在主體提及**之後**那條規則(它擋掉了
#    553.2pp 的天文數字誤報)會連這種句子一起擋掉,而安勤 3479 是真陽性。
#    出口開在「連接詞本身」上而不是「距離」上 —— 因為
#    「0050**同期**百分之五百七十四點七」的距離一樣短,但「同期」是時間修飾語,
#    它後面接的是總報酬;「則是」是繫詞,它接的是前面那個量度。
_ELLIPSIS_LINK = frozenset((
    "則是", "則為", "則只有", "則", "是", "為", "只有", "有",
    "來到", "達到", "則來到", "則達到", "剩", "剩下", "則剩"))

WINDOW = 40   # 從主體提及處往右最多看幾個字找量度標記
TOL = 1.0     # 百分點;小於等於這個差距不算兩個值


class Reading(object):
    """一筆讀數:誰、什麼指標、什麼策略、多少、出自哪一句。"""

    __slots__ = ("value", "strategy", "sentence", "vague")

    def __init__(self, value, strategy, sentence, vague):
        self.value = value
        self.strategy = strategy
        self.sentence = sentence
        self.vague = vague

    def __repr__(self):
        return "Reading(%.2f, %s, vague=%s)" % (
            self.value, self.strategy, self.vague)


class Contradiction(object):
    """同一標的 + 同一指標 + 同一策略,兩個以上的精確值。

    🔴 `low` / `high` 是**這次指控的理由** —— 造成 spread 的那兩筆讀數本身。
       原本這裡只留 spread 和全部 readings,於是「它憑哪兩個數字叫的」沒有落檔,
       而**判決和理由會分開失效**:2026-09-10 總督導查 ALL-IN0050 那支,
       判決對(稿子真的自相矛盾)而理由錯(我配的是十年 vs 十三年,
       正是我自己定義的誤報型)。只驗判決量出來的精確率,不代表你以為的東西。
    """

    __slots__ = ("metric", "strategy", "spread", "readings", "low", "high")

    def __init__(self, metric, strategy, spread, readings, low, high):
        self.metric = metric
        self.strategy = strategy
        self.spread = spread
        self.readings = readings
        self.low = low
        self.high = high

    def __repr__(self):
        return "Contradiction(%s/%s, %.2f vs %.2f = %.1fpp, n=%d)" % (
            self.metric, self.strategy, self.low.value, self.high.value,
            self.spread, len(self.readings))


def _metric_of(left):
    """左語境裡**最靠近數字**的量度標記,長詞優先。"""
    last = None
    for m in _RX_METRIC.finditer(left):
        if last is None or m.end() >= last.end():
            last = m
    return _WORD2KIND[last.group(0)] if last else None


def _strategy_of(prefix):
    """數字**之前**最後一個策略標記;沒有就是 lump。"""
    last = None
    for m in _RX_STRATEGY.finditer(prefix):
        if last is None or m.end() >= last.end():
            last = m
    return _WORD2STRAT[last.group(0)] if last else DEFAULT_STRATEGY


def _entity_marks(seg, subject_aliases, foreign_tokens):
    """句子裡的實體提及:(位置, 是不是主體)。排序後,數字歸最後一個提及。"""
    marks = []
    subj_spans = []
    for alias in subject_aliases:
        for m in re.finditer(re.escape(alias), seg):
            subj_spans.append((m.start(), m.end()))
    # 主體提及後面緊接著「歷史資料/數據」= 它是資料來源,不是這句話的主角
    for s, e in subj_spans:
        marks.append((s, not _RX_AS_DATASOURCE.match(seg[e:e + 8].lstrip("的 "))))
    # 別的四~六碼代號:「0050 年化 24.7%,但 0056 只有 17.2%」—— 17.2 不是 0050 的
    for m in re.finditer(r"(?<!\d)\d{4,6}(?!\d)", seg):
        if not any(s <= m.start() < e for s, e in subj_spans):
            marks.append((m.start(), False))
    # 別人的中文名(台積電的報酬率…)
    for m in _RX_FOREIGN_NAME.finditer(seg):
        if any(m.start() < e and s < m.end() for s, e in subj_spans):
            continue          # 「元大台灣五十的年化報酬」——那是主體自己
        # 🔴 緊貼在主體後面的詞是**修飾主體的**,不是另一個實體。
        #    「0050**在同期**的總報酬達到 420.8,年化報酬率 31.2」——
        #    「在同期」長得跟一個名字一樣,舊版把 31.2 判給它,整支稿子的
        #    三個 0050 年化值(21.2/31.2/49.5)只剩一個,矛盾就消失了。
        #    這是我自己的修法造出來的漏報,靠回跑全語料比對前後差異抓到的。
        if any(0 <= m.start() - e <= 4 for _s, e in subj_spans):
            continue
        marks.append((m.start(), False))
    for tok in foreign_tokens:
        marks += [(m.start(), False) for m in re.finditer(re.escape(tok), seg)]
    marks.sort()
    return marks


def _metric_right(right):
    """數字**右邊**的量度標記:「百分之三十三點八**的最大回撤**」。

    🔴 只讓「的/之」當連接詞,不准跨標點。
       若容許逗號,「總報酬百分之七百一十五點三,年化報酬率…」的 715.3
       會被右邊那個「年化」認領,製造一個 715 的年化報酬。
    (鴻準 2354、豐泰 9910 就是被左邊的「年化報酬率」認領的 33.8% 最大回撤)
    """
    m = re.match(r"[的之]", right)
    body = right[m.end():] if m else right
    mm = _RX_METRIC.match(body)
    return _WORD2KIND[mm.group(0)] if mm else None


def _is_vague(seg, num):
    """這個讀數本身是不是粗略的量級詞 / 一個界線而不是一個值。"""
    if "成" in num.raw:                       # 兩成 / 三成多
        return True
    if _RX_VAGUE_TAIL.match(seg[num.end:num.end + 4]):
        return True
    return bool(_RX_BOUND.search(seg[max(0, num.start - 6):num.start]))


def readings_for(text, metric="annual",
                 subject_aliases=SUBJECT_ALIASES, foreign_tokens=()):
    """掃一份稿子,回傳掛在主體名下、屬於 `metric` 的百分比讀數。"""
    out = []
    _RX_ALIAS = re.compile("^(?:%s)" % "|".join(
        re.escape(a) for a in sorted(subject_aliases, key=len, reverse=True)))
    for seg in SEG.split(text):
        if not any(a in seg for a in subject_aliases):
            continue
        strats = set(_WORD2STRAT[m.group(0)]
                     for m in _RX_STRATEGY.finditer(seg.lower()))
        if _RX_ENUM.search(seg) and len(strats) >= 2:
            continue                          # 熄火條件 ①:列舉句
        marks = _entity_marks(seg, subject_aliases, foreign_tokens)
        for num in parse_numbers(seg):
            if num.unit != UNIT_PCT:
                continue
            if _RX_TRANSITION.search(seg[max(0, num.start - 8):num.start]):
                continue                      # 熄火條件 ②:轉換句的後半
            owners = [(pos, is_subj) for pos, is_subj in marks
                      if pos < num.start]
            if not owners or not owners[-1][1]:
                continue
            anchor = owners[-1][0]
            # 🔴 量度標記必須落在**主體提及之後**。
            #    少了這一條,「00713…年化 15.5,0050 同期 574.7」的 574.7 會被
            #    前一段的「年化」認領,而 574.7 是總報酬 —— 那支高股息全家族
            #    的稿子因此被報成 553.2pp 的天文數字。
            right_kind = _metric_right(seg[num.end:num.end + 8])
            if right_kind is not None:
                if right_kind != metric:
                    continue                  # 「…的最大回撤」——右邊贏
            else:
                left = seg[max(anchor, num.start - WINDOW):num.start]
                kind = _metric_of(left)
                if kind is None:
                    link = _RX_ALIAS.sub("", seg[anchor:num.start], count=1)
                    if link.strip("， 、:：") in _ELLIPSIS_LINK:
                        kind = _metric_of(seg[max(0, anchor - WINDOW):anchor])
                if kind != metric:
                    continue
            out.append(Reading(num.value,
                               _strategy_of(seg[:num.start].lower()),
                               seg.strip(),
                               _is_vague(seg, num)))
    return out


def find_contradictions(text, metric="annual",
                        subject_aliases=SUBJECT_ALIASES, foreign_tokens=(),
                        tol=TOL):
    """回傳 [Contradiction]。空 list = 這份稿子在這個指標上自洽(或只講了一次)。

    🔴 一次標記需要**兩個精確值**。模糊值(兩成多、八起跳)會被帶進 readings
       當旁證,但不能自己撐起一次指控 —— 口語的量級詞和讀數不是同一種東西。
    """
    by_strategy = {}
    for r in readings_for(text, metric, subject_aliases, foreign_tokens):
        by_strategy.setdefault(r.strategy, []).append(r)

    out = []
    for strategy, rs in sorted(by_strategy.items()):
        exact = [r for r in rs if not r.vague]
        if len(exact) < 2:
            continue
        lo = min(exact, key=lambda r: r.value)
        hi = max(exact, key=lambda r: r.value)
        spread = hi.value - lo.value
        if spread <= tol:
            continue
        # 🔴 lo/hi 一起帶走 = 指控要連理由落檔。只帶 spread 的話,
        #    「叫對但配錯對」在任何輸出裡都看不出來(2026-09-10 的教訓)。
        out.append(Contradiction(metric, strategy, spread, rs, lo, hi))
    out.sort(key=lambda c: -c.spread)
    return out


def foreign_tokens_from_filename(fname):
    """從檔名撈出這支片的主角,當成「不是主體」的實體標記。"""
    toks = set()
    for code in re.findall(r"(?<!\d)(\d{4})(?!\d)", fname):
        if code not in SUBJECT_ALIASES:
            toks.add(code)
    m = re.search(r"個股體檢([^\dA-Za-z]{2,4})", fname)
    if m:
        toks.add(m.group(1))
    return toks
