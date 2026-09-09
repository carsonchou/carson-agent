"""中文數字 → (數值, 單位) 解析。

只用標準庫。這一層要處理的東西比想像中髒:
    三十七萬 / 四百萬 / 八百零三萬 / 3.2萬 / 百分之三百八十六 / 24.5% / 三成 / 7.3倍
而且**單位判定比數值判定更重要** —— 「一百二十萬人」是人數不是錢,
把它當金額就會產生 fact_pool_unit_blindspot.md 記載的那種誤殺。
"""

import re

# --- 中文數字字元表 -------------------------------------------------------
_DIGIT = {
    "零": 0, "〇": 0, "○": 0,
    "一": 1, "壹": 1, "二": 2, "貳": 2, "兩": 2, "三": 3, "參": 3,
    "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陸": 6,
    "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
_SMALL_UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_BIG_UNIT = {"萬": 10 ** 4, "万": 10 ** 4, "億": 10 ** 8, "亿": 10 ** 8}

_CN_CHARS = "".join(_DIGIT) + "".join(_SMALL_UNIT) + "".join(_BIG_UNIT) + "点點."


def cn_to_num(s):
    """把純中文數字串轉成 float。認不得回 None。

    支援 十五 / 三十七 / 一百二十 / 八百零三 / 兩千五百 / 三點五。
    不支援也不該支援:年份唸法(二〇二六)——那由呼叫端用單位排除。
    """
    s = s.strip()
    if not s:
        return None

    # 小數帶量級:三點二萬 / 一點五億 —— 尾巴的萬/億是倍率,不是小數的一部分
    if s[-1] in _BIG_UNIT and any(d in s[:-1] for d in ("點", "点", ".")):
        head = cn_to_num(s[:-1])
        return None if head is None else head * _BIG_UNIT[s[-1]]

    # 小數:三點五 / 3點5
    for dot in ("點", "点", "."):
        if dot in s:
            head, _, tail = s.partition(dot)
            h = cn_to_num(head) if head else 0.0
            if h is None:
                return None
            frac = ""
            for ch in tail:
                if ch in _DIGIT:
                    frac += str(_DIGIT[ch])
                elif ch.isdigit():
                    frac += ch
                else:
                    return None
            if not frac:
                return None
            return h + float("0." + frac)

    if re.fullmatch(r"\d+", s):
        return float(s)

    # 逐位唸法:「六三九點八」= 639.8、「一二〇」= 120。
    # 產線 TTS 很愛這樣寫百分比。不處理的話 cn_to_num 會讓後面的位蓋掉前面的位,
    # 「六三九」變成 9 —— 而 9.8% 跟 639.8% 都算得出東西,所以錯得靜悄悄。
    if len(s) >= 2 and all(ch in _DIGIT for ch in s):
        return float("".join(str(_DIGIT[ch]) for ch in s))

    total = 0.0      # 已結算的「萬/億」段落
    section = 0.0    # 當前段落(< 萬)
    digit = None     # 待處理的個位數

    for ch in s:
        if ch in _DIGIT:
            digit = _DIGIT[ch]
        elif ch.isdigit():
            digit = (0 if digit is None else digit) * 10 + int(ch)
        elif ch in _SMALL_UNIT:
            u = _SMALL_UNIT[ch]
            # 「十五」開頭省略的一
            section += (1 if digit is None else digit) * u
            digit = None
        elif ch in _BIG_UNIT:
            u = _BIG_UNIT[ch]
            section += (digit or 0)
            digit = None
            if section == 0:
                section = 1  # 「萬」單獨出現視為 1 萬
            total += section * u
            section = 0.0
        else:
            return None

    section += (digit or 0)
    val = total + section
    return float(val) if (total or section or s in _DIGIT) else None


# --- 單位分類 -------------------------------------------------------------
# 🔴 這張表是誤殺的主要來源,每一條都要有理由。
# 判準:這個數字如果被當成「績效金額」拿去驗算,會不會冤枉一句合法的話?
UNIT_PCT = "pct"           # 百分比 / 成 —— 可入算式
UNIT_AMOUNT = "amount"     # 新台幣金額 —— 可入算式(被驗算的對象)
UNIT_MULTIPLE = "multiple"  # 倍 —— 可入算式
UNIT_YEAR = "year"         # 年 —— 可入算式(期間)
UNIT_MONTH = "month"       # 月 —— 可入算式(期間)
UNIT_COUNT = "count"       # 人/檔/支/次/家 —— **一律不入算式**
UNIT_FX = "fx"             # 外幣金額 —— **一律不入算式**(幣別不同,算不起來)
UNIT_BARE = "bare"         # 沒有單位

# 順序有意義:先匹配長的後綴,「萬人」必須贏過「萬」
_SUFFIX = [
    # (後綴, 單位, 相對「元」或「%」的倍率)
    ("億人", UNIT_COUNT, 1.0), ("萬人", UNIT_COUNT, 1.0), ("人", UNIT_COUNT, 1.0),
    ("萬人次", UNIT_COUNT, 1.0), ("人次", UNIT_COUNT, 1.0),
    ("萬檔", UNIT_COUNT, 1.0), ("檔", UNIT_COUNT, 1.0), ("支", UNIT_COUNT, 1.0),
    ("次", UNIT_COUNT, 1.0), ("家", UNIT_COUNT, 1.0), ("間", UNIT_COUNT, 1.0),
    ("位", UNIT_COUNT, 1.0), ("名", UNIT_COUNT, 1.0), ("筆", UNIT_COUNT, 1.0),
    ("天", UNIT_COUNT, 1.0), ("日", UNIT_COUNT, 1.0), ("週", UNIT_COUNT, 1.0),
    ("億鎂", UNIT_FX, 1.0), ("萬鎂", UNIT_FX, 1.0), ("鎂", UNIT_FX, 1.0),
    ("億美元", UNIT_FX, 1.0), ("萬美元", UNIT_FX, 1.0), ("美元", UNIT_FX, 1.0),
    ("美金", UNIT_FX, 1.0), ("日圓", UNIT_FX, 1.0), ("歐元", UNIT_FX, 1.0),
    ("億元", UNIT_AMOUNT, 1e8), ("億", UNIT_AMOUNT, 1e8),
    ("萬元", UNIT_AMOUNT, 1e4), ("萬", UNIT_AMOUNT, 1e4),
    ("千元", UNIT_AMOUNT, 1e3),
    ("元", UNIT_AMOUNT, 1.0), ("塊", UNIT_AMOUNT, 1.0),
    ("成", UNIT_PCT, 10.0),          # 三成 = 30%
    ("趴", UNIT_PCT, 1.0), ("%", UNIT_PCT, 1.0), ("％", UNIT_PCT, 1.0),
    ("倍", UNIT_MULTIPLE, 1.0),
    ("年", UNIT_YEAR, 1.0), ("個月", UNIT_MONTH, 1.0), ("月", UNIT_MONTH, 1.0),
]

_SIGN_CHARS = "負−–-"      # 負 − – -(給 in 用;「-」放最後,進字元類才不會變成範圍)
# 🔴 負號在「百分之」**兩側都會出現**:「負百分之七十七點三」/「百分之負七十四點七」。
# 只在後面留位置的話,前面那個「負」會讓引擎把「負百」吃成一個數字(百=100),
# 剩下的「分之七十七點三」就變成沒有單位的裸數 —— 整個百分比靜靜消失。
_SIGN_CLS = "[" + _SIGN_CHARS + "]?"
_NUM_BODY = (_SIGN_CLS + r"(?:百分之)?" + _SIGN_CLS +
             r"(?:[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?|["
             + _CN_CHARS + r"]+)")
_SUFFIX_ALT = "|".join(re.escape(s) for s, _, _ in _SUFFIX)
_RX_NUM = re.compile(r"(" + _NUM_BODY + r")(" + _SUFFIX_ALT + r")?")


class Num:
    """一個從文字裡抽出來的數字,帶單位、原文與位置。"""

    __slots__ = ("value", "unit", "raw", "start", "end")

    def __init__(self, value, unit, raw, start, end):
        self.value = value      # amount 一律正規化成「元」;pct 一律正規化成「百分點」
        self.unit = unit
        self.raw = raw
        self.start = start
        self.end = end

    def __repr__(self):
        return "Num(%r, %s, %r)" % (self.value, self.unit, self.raw)


# 產線 TTS 把「712%」唸成/寫成「七百一十二百分之」——後綴倒裝。
# 🔴 替換必須**等長**(百分之→%??),因為 extract 用 start 位移取左語境窗,
#    一旦位移對不上,語境詞會配到別的數字上,那比抽不到還糟。
_RX_PCT_POSTFIX = re.compile(r"(?<=[" + _CN_CHARS + r"0-9])百分之")


def parse_numbers(text):
    """掃一段文字,回傳 [Num]。認不得的數字直接丟掉(寧可少抽,不要抽錯)。"""
    text = _RX_PCT_POSTFIX.sub("%　　", text)
    out = []
    for m in _RX_NUM.finditer(text):
        body, suf = m.group(1), m.group(2) or ""
        if not body:
            continue

        neg = False
        while body and body[0] in _SIGN_CHARS:
            neg, body = True, body[1:]
        is_pct_prefix = body.startswith("百分之")
        core = body[3:] if is_pct_prefix else body

        # 🔴 負號有三種寫法,實測全部都在產線稿子裡出現過:
        #   「報酬負百分之八十七點四」/「報酬是負的百分之十五點八」/「百分之負七十四點七」/「-52.6%」
        # 前兩種負號在數字**前面**(隔著「的」),第三種在「百分之」**後面**。
        # 只認其中一種的儀器,會把正確的算術(100萬×0.126=12.6萬)判成編造。
        while core and core[0] in _SIGN_CHARS:
            neg, core = True, core[1:]
        core = core.replace(",", "")

        # 🔴 只有「萬/億」而沒有任何位數的字串不是數字。
        # cn_to_num("萬") 會回 10000(「萬單獨出現視為 1 萬」那條),
        # 於是產線裡的「萬元」「破億」被抽成一個憑空的金額,再被拿去指控稿子。
        # 實測長相:`[CONTRADICTED] 萬元`——原文根本沒有那個數。
        # ⚠️ 判準不能寫成「沒有 _DIGIT 就丟」:那會連「十年」「百萬」一起丟掉
        #    (實測害 pos-2 從 CONTRADICTED 掉成 BARE)。十/百/千是位數,萬/億是量級詞。
        if not any(c in _DIGIT or c in _SMALL_UNIT or c.isdigit() for c in core):
            continue

        # 年份唸法(二〇二六年 / 2026年)不是期間,排除
        if suf == "年" and re.fullmatch(r"(?:19|20)\d{2}", core):
            continue
        if suf == "年" and len(core) == 4 and all(c in "零〇○一二三四五六七八九" for c in core):
            continue

        val = cn_to_num(core)
        if val is None:
            continue

        if is_pct_prefix:
            unit, scale = UNIT_PCT, 1.0
        elif suf:
            unit, scale = next((u, k) for s, u, k in _SUFFIX if s == suf)
        elif core and core[-1] in _BIG_UNIT:
            # 「三十七萬」——萬/億 被數字本體吃掉了,後面沒有後綴剩下。
            # 在財經語境裡,一個裸的「萬/億」量級數字就是金額(37萬 = 37萬元)。
            # ⚠️ 這條只在**沒有其他後綴**時生效:「一百二十萬人」的 人 先贏,仍是 count。
            unit, scale = UNIT_AMOUNT, 1.0
        else:
            unit, scale = UNIT_BARE, 1.0

        # 🔴 負號只套用在百分比上。
        # 不套用在金額上:金額前的「-」多半是 TPK-KY 這種連字號,認了反而製造新的錯。
        # 前文只看三個字,才容得下「是負的百分之十五點八」而不會撈到隔壁句的負號。
        if unit == UNIT_PCT and (neg or "負" in text[max(0, m.start() - 3):m.start()]
                                 or (m.start() > 0 and text[m.start() - 1] in "-−–")):
            val = -val

        out.append(Num(val * scale, unit, m.group(0), m.start(), m.end()))
    return out
