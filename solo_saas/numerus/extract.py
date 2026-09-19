"""從一段財經文字裡抽出「宣稱」與「輸入」。

範圍(scope)刻意訂成**一個段落**,因為要執行的規則本來就是這樣寫的:
    produce_batch._AMOUNT_DISCIPLINE:「必須在同一段講出本金與百分比,讓觀眾自己就能算得出來」
那條規則今天只活在 prompt 層 —— 期望不是規則,失效時靜默(memory verification-that-cannot-fail 第零種)。
這個模組是把它降到可執行層的第一步。
"""

import re

from .zhnum import (
    UNIT_AMOUNT, UNIT_MONTH, UNIT_MULTIPLE, UNIT_PCT, UNIT_YEAR, parse_numbers,
)

# 左側語境窗:一個數字前面這麼多字元之內出現的詞,才算修飾它
_WINDOW = 12

# --- 語境詞表 -------------------------------------------------------------
# 「這個金額是一個結論」的訊號。沒有這些詞的金額不當宣稱處理(例:舉例用的本金)。
# 🔴 分成兩類,因為它們**能對應的算式完全不同**。
# 這一刀是這支工具能不能用的關鍵:不分類的話,窮舉的候選算式會多到什麼都對得上
# —— 那正是 fact_pool_unit_blindspot.md 第 3 節「池越大守門越弱」的同一個詛咒,
# 只是這次密度不是來自事實池,而是來自我自己列的算式。
# 差額動詞再分「賺」與「虧」。分不開的話,「即便經歷三成下跌,反而**多賺**
# 一百八十二萬」會被拿去跟「本金×回撤 30% = 30 萬」比對 —— 那兩個量根本無關。
CLAIM_GAIN = ("多賺", "賺到", "賺了", "省下", "獲利", "成長到")
CLAIM_LOSS = ("少賺", "賠掉", "虧掉", "賠了", "多繳", "吃掉", "多花", "損失")
CLAIM_DIFF = CLAIM_GAIN + CLAIM_LOSS + ("差距", "相差", "整整差", "差了")
CLAIM_LEVEL = ("剩下", "只剩", "滾到", "變成", "拿回", "領到", "累積到")
CLAIM_CTX = CLAIM_DIFF + CLAIM_LEVEL

# 比較句:「比致伸多賺了三十四萬兩千元」的對照組數字在**別句**,同句算不出來。
COMPARE_CTX = ("比", "相較", "相比", "對比")

# 過程中的低點,不是期末值。用期末報酬率去算它必然對不上 —— 那是儀器的錯不是作者的。
TRANSIENT_CUE = ("一度", "曾經", "過程中", "最慘", "谷底", "最低點", "高峰", "最糟")

KIND_DIFF = "diff"     # 差額 / 獲利 / 成本 —— 不可能是終值
KIND_LEVEL = "level"   # 終值 / 帳戶餘額

PRINCIPAL_CTX = ("本金", "投入", "投資", "月投", "每月投", "每個月投", "每月存", "存入",
                 "一次投", "單筆投", "梭哈", "起始資金", "拿出")

# 定期定額 vs 單筆:同樣是「本金」,算式完全不同,一定要分開
RECURRING_CTX = ("月投", "每月", "每個月", "定期定額", "每年投", "每年存")

RATE_CTX = ("年化", "報酬", "總報酬", "報酬率", "殖利率", "績效", "漲幅",
            "成長", "年報酬", "累積報酬", "費率", "內扣")

# 🔴🔴 這一刀是整支工具最貴的一刀:**年化 ≠ 總報酬**。
# 實測 922 支旁白:第一版把兩者混成一個 rates 池,於是「年化 43.7%、十年後變成
# 3,742 萬」被算成「本金×(1+43.7%)=143.7 萬」,再拿這個自己造的數字去指控稿子。
# 32 筆 CONTRADICTED 裡有一大半是這麼來的 —— 儀器自己算錯,然後說作者在編。
# ⇒ 年化只有**同句有年數**時才能用(要複利);沒有年數就什麼都別算,落到 BARE。
ANNUAL_CTX = ("年化",)
KIND_ANNUAL = "annual"
KIND_TOTAL = "total"

# 🔴 回撤 / 跌幅**不是**報酬率,不能跟報酬率相減。
# 但也不能像第一版那樣直接丟掉:丟掉之後「總報酬 223%、最大回撤 70%、投入一百萬
# 剩三十萬」會拿 223% 去算,反而更冤枉。回撤要有自己的算式:本金×(1−回撤)。
DRAWDOWN_CTX = ("回撤", "跌掉", "跌幅", "腰斬", "下跌", "最大跌", "套牢", "虧損幅度",
                "縮水", "蒸發", "暴跌", "崩跌", "最慘", "虧損近")

# 🔴 這一句在句子裡「虧」的味道。有味道但拿不到回撤數字時,終值宣稱一律不指控。
# 理由:「從高峰縮水到只剩下不到二十八萬」對得起來的算式是本金×(1−回撤),
# 而回撤數字不在這一句裡。此時拿同句的**正報酬率**去算 120.4 萬再指控作者,
# 是儀器在替自己找一個能算的算式,不是在檢查作者。
# ⚠️ 這裡**不能**放「只剩」「賠掉」:那些是宣稱動詞,不是虧損語境。
# 放進來的話 pos-1(「最後你的帳戶只剩四百萬」)會從 CONTRADICTED 掉成 BARE
# —— 把唯一一種真的抓得到的東西關掉了。實測踩過一次。
LOSS_CUE = DRAWDOWN_CTX + ("海嘯", "金融風暴")

# 「腰斬」= 跌一半。中文財經口語的固定用法,沒有伴隨百分比時就是這個意思。
HALVED_PCT = 50.0

# 🔴 範圍(scope)= **句**,不是段。
# _AMOUNT_DISCIPLINE 原文寫的是「同一段」,但實測產線 922 支旁白發現:
# 一句旁白動輒五十字、一段塞十幾個不相干的數字,用段當範圍會把 A 句的本金
# 配到 B 句的金額上,產生**沒有根據的指控**。
# 往窄切的代價是漏抓(落到 BARE = 只報告),往寬切的代價是冤枉人。
# 這兩種錯的嚴重度不對等,所以往窄切。
_RX_PARA = re.compile("[。!?！？;；\n]+")


class Claim:
    """一個待驗算的金額宣稱,連同它所在段落抽到的全部輸入。"""

    __slots__ = ("amount", "raw", "segment", "kind", "principal", "recurring",
                 "rates", "drawdowns", "gains", "loss_ctx", "doubled", "is_loss",
                 "comparative", "transient", "vague_loss",
                 "years", "months", "multiples")

    def __init__(self, amount, raw, segment, kind):
        self.amount = amount        # 元
        self.raw = raw
        self.segment = segment
        self.kind = kind            # KIND_DIFF / KIND_LEVEL
        self.principal = None       # 元(單筆)或每期投入(定期定額)
        self.recurring = False
        self.rates = []             # [(百分點, KIND_ANNUAL/KIND_TOTAL)]
        self.drawdowns = []         # 回撤幅度(百分點,一律取正)
        self.gains = []             # 同句已宣告的獲利金額
        self.loss_ctx = False       # 這句在講「虧」
        self.doubled = False        # 「翻 N 倍」——中文本身就有歧義
        self.is_loss = False        # 這個宣稱本身在講「虧了多少」
        self.comparative = False    # 「比 X 多賺 N」——對照組數字不在同句
        self.transient = False      # 「一度只剩」——過程低點,不是期末值
        self.vague_loss = False     # 「腰斬再腰斬」——虧了,但虧多少是不定值
        self.years = None
        self.months = None
        self.multiples = []

    def __repr__(self):
        return "Claim(%r, %s, P=%r, rec=%s, rates=%r, dd=%r, y=%r)" % (
            self.raw, self.kind, self.principal, self.recurring,
            self.rates, self.drawdowns, self.years)


def _left(text, pos):
    return text[max(0, pos - _WINDOW):pos]


def _has(ctx_words, window):
    return any(w in window for w in ctx_words)


def _nearest(ctx_words, window):
    """語境窗裡最靠近數字的那個詞的位置。都沒有回 -1。"""
    return max([window.rfind(w) for w in ctx_words] or [-1])


def _claim_kind(window):
    """看語境窗裡**最靠近數字**的那個動詞決定類別。都沒有就不是宣稱。"""
    best, best_pos = None, -1
    for w in CLAIM_DIFF:
        i = window.rfind(w)
        if i > best_pos:
            best, best_pos = KIND_DIFF, i
    for w in CLAIM_LEVEL:
        i = window.rfind(w)
        if i > best_pos:
            best, best_pos = KIND_LEVEL, i
    return best


def segments(text):
    """切句。句號/驚嘆/問號/分號/換行都算句界。"""
    return [s for s in (p.strip() for p in _RX_PARA.split(text)) if s]


def extract(text):
    """回傳 [Claim]。抽不到宣稱就回空 list —— 沒有宣稱不是問題,不要硬造。"""
    claims = []
    for seg in segments(text):
        nums = parse_numbers(seg)

        # 先把這一段的「輸入」蒐齊,宣稱共用同一組
        principal = None
        recurring = False
        rates = []
        drawdowns = []
        years = None
        months = None
        multiples = []

        for n in nums:
            win = _left(seg, n.start)
            # 「本金」也可能長在數字**後面**:「剩下的四十六點三萬本金」
            right = seg[n.end:n.end + 3]
            # 🔴 誰離數字近誰說了算。「同期投入零零五零,你卻能賺到七百二十七點五萬」
            # 裡的「投入」隔著一個代號,真正修飾這個數字的是「賺到」。
            # 不比距離的話,獲利會被當成本金,整句的算式全部歪掉。
            if n.unit == UNIT_AMOUNT and (
                    ("本金" in right)
                    or (_has(PRINCIPAL_CTX, win)
                        and _nearest(PRINCIPAL_CTX, win) > _nearest(CLAIM_CTX, win))):
                # 同段出現多個本金時取第一個(通常是主線那個)
                if principal is None:
                    principal = n.value
                    recurring = _has(RECURRING_CTX, win)
            elif n.unit == UNIT_PCT:
                # 🔴 修飾語也可能在數字**右邊**:「將近百分之七十的暴跌」。
                # 只看左邊會把它當成總報酬,算出 170 萬再去指控「只剩三十萬」。
                # 右窗要在逗號處截斷,否則「總報酬百分之三百八十六，最大回撤…」
                # 會讓 386% 被隔壁子句的「回撤」汙染 —— 那是反方向的同一個錯。
                rwin = re.split("[,,、]", seg[n.end:n.end + 8])[0]
                if _has(DRAWDOWN_CTX, win) or _has(DRAWDOWN_CTX, rwin):
                    drawdowns.append(abs(n.value))
                    continue
                kind = KIND_ANNUAL if _has(ANNUAL_CTX, win) else KIND_TOTAL
                # 沒有語境詞的百分比也收 —— 「年化 24.5% vs 16.9%」的第二個沒有詞
                rates.append((n.value, kind, _has(RATE_CTX, win)))
            elif n.unit == UNIT_YEAR and years is None:
                years = n.value
            elif n.unit == UNIT_MONTH and months is None:
                months = n.value
            elif n.unit == UNIT_MULTIPLE:
                multiples.append(n.value)

        # ⚠️ 這裡曾經寫「腰斬沒帶百分比時就是 50%」,實測是**淨傷害**:
        # 「腰斬再腰斬」是 75%、「三次腰斬」是 87.5%,補一個 50 進去等於替
        # 一句算得對的話造一個算不對的答案,把誠實的 BARE 變成冤枉的指控。
        # 一輪掃描新增 11 筆誤殺,全部來自這一條。⇒ 腰斬只當虧損語境,不給值。

        # 只要有任何一個百分比帶語境詞,就相信這一段的百分比是報酬率
        rate_vals = [(v, k) for v, k, _ in rates]
        if not any(flag for _, _, flag in rates):
            rate_vals = []
        # 🔴 去重。同一個報酬率在一句裡被覆述兩次(「高達 135.9 趴,報酬百分之
        # 一百三十五點九」)不構成「對照組」,但第一版的 len(rates)>=2 會誤判成
        # 有對照組,於是差額只准是「兩案之差 = 0」,再指控作者編了 135.9 萬。
        seen, deduped = set(), []
        for v, k in rate_vals:
            key = (round(v, 6), k)
            if key not in seen:
                seen.add(key)
                deduped.append((v, k))
        rate_vals = deduped

        # 同句已宣告的獲利金額 ——「當年獲利六十三萬,帳面累積到一百六十三萬」
        # 這種串接寫法,終值的底是「本金＋獲利」而不是本金。
        # ⚠️ 比較句的獲利不算:「比致伸多賺三十四萬」是兩檔之差,
        # 加到本金上不會得到任何真實的帳戶餘額。
        gains = [n.value for n in nums
                 if n.unit == UNIT_AMOUNT
                 and _claim_kind(_left(seg, n.start)) == KIND_DIFF
                 and not _has(COMPARE_CTX, _left(seg, n.start))]
        loss_ctx = _has(LOSS_CUE, seg)
        # 「腰斬」沒有自己的百分比時是不定值(腰斬再腰斬=75%、三次腰斬=87.5%),
        # 同句就算有別人的回撤數字也不能拿來頂替。
        vague_loss = "腰斬" in seg and not _has(("腰斬百分之", "腰斬約"), seg)

        for n in nums:
            if n.unit != UNIT_AMOUNT:
                continue
            win = _left(seg, n.start)
            kind = _claim_kind(win)
            if kind is None:
                continue
            # 「金額從五千元變成一萬元」——這是在換參數,不是在宣告結果。
            # 「變成」是 LEVEL 動詞,不擋的話一萬元會被當成三十年後的終值。
            if "從" in win and "變成" in win and win.index("從") < win.index("變成"):
                continue
            if principal is not None and abs(n.value - principal) < 1e-9:
                continue  # 本金自己不是宣稱
            c = Claim(n.value, n.raw, seg, kind)
            c.principal, c.recurring = principal, recurring
            c.rates, c.years, c.months, c.multiples = rate_vals, years, months, multiples
            c.drawdowns, c.gains, c.loss_ctx = drawdowns, gains, loss_ctx
            c.doubled = "翻" in win
            c.is_loss = _nearest(CLAIM_LOSS, win) > _nearest(CLAIM_GAIN, win)
            c.comparative = _has(COMPARE_CTX, win)
            c.transient = _has(TRANSIENT_CUE, seg)
            c.vague_loss = vague_loss
            claims.append(c)
    return claims
