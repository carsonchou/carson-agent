"""驗算引擎。

🔴 設計上最重要的一個決定:**只在「算得出來、而且怎麼算都對不上」時才開口。**

理由寫在 youtube_channel/docs/fact_pool_unit_blindspot.md:
上一代的做法是拿數字去比對一個全域事實池,結果有兩個結構性的死法 ——
  ① 規模詛咒:池越大越容易撞到鄰居,「37萬」被「37.1%」佐證,守門在替假數字背書
  ② 裸金額偵測器實測誤殺 8/21 = 38%(人數、外幣新聞、拆穿別人、合法成數算術)
這裡完全不碰事實池。判準改成**文本內部的算術一致性**:
一個金額如果和同一段裡作者自己給的本金、報酬率、年數怎麼算都對不起來,那不是查無來源,是編的。

所以:
  - 候選算式**窮舉且從寬**(單筆/定期定額、年化/總報酬、單一/兩者相減),只要對上任何一種就放行
  - 對不上任何一種,才叫 CONTRADICTED —— 這是有證明的指控
  - 算不出來就誠實說算不出來(BARE),不當成指控
"""

from .extract import KIND_ANNUAL, KIND_DIFF, KIND_LEVEL, extract

TOLERANCE = 0.25   # 相對誤差 25% 以內算對得上。刻意放寬:寧可放過,不要冤枉。

CONTRADICTED = "CONTRADICTED"   # 🔴 有算術矛盾,是實證的編造
BARE = "BARE"                   # ⚠️ 裸金額:同段沒有本金,觀眾無從驗算(違反 _AMOUNT_DISCIPLINE)
CONSISTENT = "CONSISTENT"       # ✅ 對得上至少一種合理算法


class Finding:
    __slots__ = ("verdict", "claim", "candidates", "implied_principal", "note")

    def __init__(self, verdict, claim, candidates, implied_principal=None, note=""):
        self.verdict = verdict
        self.claim = claim
        self.candidates = candidates          # [(說明, 值)]
        self.implied_principal = implied_principal
        self.note = note


MAX_ANNUAL_RATE = 2.0   # 年化 200% 以上不當年化解讀(那通常是「總報酬 8644%」被誤讀成年化)
MAX_YEARS = 60.0


def _compoundable(r, n):
    """這組 (年化, 年數) 能不能拿去複利。擋掉會溢位、也擋掉物理上不合理的解讀。"""
    return n is not None and 0 < n <= MAX_YEARS and abs(r) <= MAX_ANNUAL_RATE


def _fv_lump(p, r, n):
    return p * (1 + r) ** n


def _fv_monthly(c, r, n_years):
    """每月投入 c、年化 r、n 年的終值。r=0 時退化成單純累加。"""
    months = int(round(n_years * 12))
    if abs(r) < 1e-12:
        return c * months
    m = r / 12.0
    return c * (((1 + m) ** months - 1) / m)


def candidates_for(c):
    """窮舉這一段的輸入能算出哪些數字。回傳 [(說明, 值)]。"""
    out = []
    n = c.years
    p = c.principal

    if p is None:
        return out

    lvl = (c.kind == KIND_LEVEL)   # 終值類
    dif = (c.kind == KIND_DIFF)    # 差額類

    # 🔴 年化只有在同句給了年數時才用得上(要複利)。沒年數就**整條丟掉** ——
    # 不能退化成「本金×(1+年化)」,那是拿年化當總報酬用,會算出一個假答案
    # 再拿它去指控作者。算不出來就該落到 BARE,那是誠實的結論。
    rates = [r / 100.0 for r, k in c.rates
             if k != KIND_ANNUAL or _compoundable(r / 100.0, n)]
    annual = set(round(r / 100.0, 12) for r, k in c.rates if k == KIND_ANNUAL)

    # 回撤有自己的算式:本金×(1−回撤) 是剩下的錢,本金×回撤 是虧掉的錢
    for d in set(c.drawdowns):
        dd = abs(d) / 100.0
        if lvl:
            out.append(("本金×(1−回撤 %.4g%%)" % (dd * 100), p * (1 - dd)))
        # 只有「虧了多少」才能用回撤算。「即便經歷三成下跌,你反而**多賺** 182.8 萬」
        # 的 182.8 萬跟回撤無關,拿 30 萬去比它就是在造假證據。
        if dif and c.is_loss:
            out.append(("本金×回撤 %.4g%%" % (dd * 100), p * dd))

    # 🔴 同段有對照組(兩個以上報酬率)時,差額宣稱**只能**是「兩案之差」。
    # 「跟對照組比你少賺 N 萬」不可能是「A 案自己賺了 N 萬」—— 那是兩個不同的量。
    # 不切這一刀,pos-2 的 803 萬會撞上「單案複利獲利 795 萬」而被放行(實測)。
    # 這是同一個教訓第三次出現:**每多列一條候選算式,這支工具就弱一分。**
    # 有對照組(兩個**不同**的報酬率)時,差額宣稱只能是「兩案之差」
    versus = dif and len(set(round(r, 12) for r in rates)) >= 2

    if c.recurring:
        invested = p * 12 * n if n else None   # 沒有年數就不推投入總額,不要硬湊
        # 沒有報酬率時不放「投入總額」進候選:它算得出來,但它不是終值。
        # 「分20年每月投5千,總投入120萬,最終成長到約1,800萬」——1,800 萬需要
        # 一個報酬率才算得出來,同句沒給就該說「算不出來」,不是說作者在編。
        if invested and lvl and rates:
            out.append(("投入總額", invested))
        if n:
            fvs = []
            for r in rates:
                if not _compoundable(r, n):
                    continue
                fv = _fv_monthly(p, r, n)
                fvs.append(fv)
                if lvl:
                    out.append(("定期定額終值 @%.4g%%" % (r * 100), fv))
                if invested and dif and not versus:
                    out.append(("定期定額獲利 @%.4g%%" % (r * 100), fv - invested))
            if dif:
                for i in range(len(fvs)):
                    for j in range(i + 1, len(fvs)):
                        out.append(("兩案終值差", abs(fvs[i] - fvs[j])))
        return out

    # 單筆
    for r in rates:
        is_annual = round(r, 12) in annual
        # ⚠️ versus 不擋這一條。實測「總報酬 78.5%、年化 6%、對照組 −87.4%,
        # 你賺到七十八萬五千元」被擋掉後只剩「兩案之差 165.9 萬」,於是一句正確的
        # 話被指控。versus 該擋的是**容易誤中的複利獲利**,不是最直白的本金×報酬。
        if dif and not is_annual:
            out.append(("本金×總報酬 %.4g%%" % (r * 100), p * r))
        if lvl and not is_annual:
            out.append(("本金×(1+總報酬) %.4g%%" % (r * 100), p * (1 + r)))
        if _compoundable(r, n):
            fv = _fv_lump(p, r, n)
            if lvl:
                out.append(("複利終值 @%.4g%% × %g年" % (r * 100, n), fv))
            if dif and not versus:
                out.append(("複利獲利 @%.4g%% × %g年" % (r * 100, n), fv - p))
    if len(rates) >= 2 and dif:
        for i in range(len(rates)):
            for j in range(i + 1, len(rates)):
                if round(rates[i], 12) not in annual and round(rates[j], 12) not in annual:
                    out.append(("兩總報酬差 × 本金", abs(rates[i] - rates[j]) * p))
                if _compoundable(rates[i], n) and _compoundable(rates[j], n):
                    out.append(("兩年化複利差 × 本金",
                                abs(_fv_lump(p, rates[i], n) - _fv_lump(p, rates[j], n))))
    for m in c.multiples:
        if lvl:
            out.append(("本金×%g倍" % m, p * m))
            # 「翻了兩倍」在中文裡同時被用成 ×2 和 ×3,兩種都是合法讀法。
            # 這是語言本身的歧義,不是作者算錯 —— 兩種都列,對上任一種就放行。
            if c.doubled:
                out.append(("本金×(%g+1)倍(翻倍的另一種讀法)" % m, p * (m + 1)))
        if dif:
            out.append(("本金×(%g倍−1)" % m, p * (m - 1)))

    # 串接寫法:「投入一百萬,當年獲利六十三萬,帳面累積到一百六十三萬」
    # 🔴 加**和**減都要列。中文把虧損講成正數:「賠掉八十七萬四千元,只剩下
    # 十二萬六千元」的算式是 100萬 − 87.4萬,只列加法會讓 15 句算得對的話被指控。
    for g in c.gains:
        if lvl and abs(g - c.amount) > 1e-9:
            out.append(("本金＋同句損益", p + g))
            out.append(("本金−同句損益", p - g))
            # 串接再一層:「累積到一百六十三萬,這一百六十三萬蒸發掉 33%」
            # 回撤的底是已累積的餘額,不是原始本金。
            for d in set(c.drawdowns):
                out.append(("(本金＋損益)×(1−回撤 %.4g%%)" % abs(d),
                            (p + g) * (1 - abs(d) / 100.0)))
    return out


def _implied_principal(c):
    """沒有本金時,反解「這個宣稱要成立,本金得是多少」。這是診斷資訊,不是指控。"""
    rates = [r / 100.0 for r, _ in c.rates]
    if not rates:
        return None
    if len(rates) >= 2:
        d = abs(rates[0] - rates[1])
        if d > 1e-9:
            return c.amount / d
    if abs(rates[0]) > 1e-9:
        return c.amount / rates[0]
    return None


def check_text(text):
    """對一段文字跑完整檢查,回傳 [Finding]。"""
    findings = []
    for c in extract(text):
        cands = candidates_for(c)
        if not cands:
            findings.append(Finding(
                BARE, c, [], _implied_principal(c),
                "同段沒有可用的本金,觀眾無法自行驗算"))
            continue
        # 🔴 比**大小**不比正負。中文把虧損講成正數:「賠掉八十七萬四千元」,
        # 而算式在負報酬率下算出來的是 -874,000。不取絕對值就會冤枉一句對的話。
        ok = any(abs(abs(c.amount) - abs(v)) <= TOLERANCE * max(abs(v), 1.0)
                 for _, v in cands)
        # 🔴 逃生門的前提是「算不出來」,不是「這句話聽起來在講虧損」。
        # 同句只要已經給了足以算出這個量的東西 —— 負報酬率、回撤幅度、或作者
        # 自己宣告的另一個損益金額 —— 那就不是算不出來,是**算不對**,逃生門不該開。
        # 實證:突變測試(拿真語料 209 條 CONSISTENT 逐條注入錯誤金額)顯示
        # 不切這一刀時,44 條注入的錯誤有一大半是被這三道逃生門吞掉的,
        # 而不是被工具想過之後放過的 —— 靈敏度 78.9%,叫不出聲的閘門等於沒有。
        # 「同句給了幅度」只認**負報酬率**和**回撤**,不認同句的損益金額。
        # 🔴 實測 4 個誤指控全出在把損益也算進來:
        #   「最終多賺九十八萬七千元,但過程中縮水到只剩三十四萬元」——
        #   98.7 萬是期末、34 萬是路徑中途,兩個不同的量,前者算不出後者。
        has_magnitude = bool(c.drawdowns) or any(r < 0 for r, _ in c.rates)
        if ok:
            findings.append(Finding(CONSISTENT, c, cands))
        elif c.kind == KIND_LEVEL and c.loss_ctx and not has_magnitude:
            # 這句在講虧,而幅度不在這句裡 ⇒ 算不出來,不是算不對。
            findings.append(Finding(
                BARE, c, cands, None,
                "同句在講虧損但沒有給幅度,無法驗算"))
        elif c.kind == KIND_LEVEL and c.vague_loss:
            # 🔴 這道門不吃 has_magnitude。「腰斬」語境下同句的回撤數字未必是
            # 這一檔的:「本金一百萬投入大同,面臨腰斬,資金變成五十萬,而 0050
            # 可能只下跌百分之二十」—— 那個 20% 屬於對照組,拿它去算大同就是造假證據。
            # 而 50 萬本身是對的(100 萬腰斬)。實測這一刀救回一個誤指控。
            findings.append(Finding(
                BARE, c, cands, None,
                "同句的「腰斬」沒有伴隨幅度,跌多少是不定值"))
        elif c.kind == KIND_LEVEL and c.transient and not has_magnitude:
            # 同上:路徑中途的低點只有回撤算得出來,期末的損益金額不行。
            # ⚠️ 但負報酬率行:「最慘的一年是二零零八年,報酬率是負百分之六十,
            # 到了年底只剩下四十萬」——「最慘的一年」是一個有明確報酬率的期間,
            # 不是「一度」「谷底」那種說不出在哪一天的點,年底餘額算得出來。
            findings.append(Finding(
                BARE, c, cands, None,
                "這是過程中的低點,期末報酬率算不出它"))
        elif c.comparative:
            findings.append(Finding(
                BARE, c, cands, None,
                "這是跟另一檔比較,對照組的數字不在同句"))
        else:
            findings.append(Finding(
                CONTRADICTED, c, cands, None,
                "與同段自己給的數字算不起來"))
    return findings


def worst(findings):
    """一段文字的總結論。給呼叫端當 exit code 用。"""
    if any(f.verdict == CONTRADICTED for f in findings):
        return CONTRADICTED
    if any(f.verdict == BARE for f in findings):
        return BARE
    return CONSISTENT
