# -*- coding: utf-8 -*-
"""旁白數字上畫面的 fail-closed 閘門(方案 B,2026-09-19)。

問題:旁白是中文數字(「負的百分之六十九點八」)。把它轉回 -69.8 再印在畫面上,
等於憑一次字串轉換就宣稱「這是我們算出來的事實」—— 沒有閘門就是誠信紅線
(memory yt-integrity-fabricated-stats-fix)。concept_visuals.py:955 那條註解
「旁白是中文數字,模糊轉換有印錯數字的風險,絕不走那條」講的就是這件事;
本模組不是推翻它,是給它一道**精確比對**的閘門:比不中就不印。

失敗形態清單(先於本模組寫成,不得回頭修改):
docs/ops/2026-09-19_主頻道畫面改版提案_wF-p8/實作驗收/步驟3_失敗形態清單.md

判定順序(對應清單 ①~⑥):
  1. 解析這一刻字幕 cue 的中文數字 → (值, 單位)        解析不出 → 不印(④)
  2. 以**逐欄位列舉的固定表示法**換算事實庫的值,
     round(顯示值, 旁白小數位) == 旁白值 才算中          沒中 → 不印(②⑤)
  3. 通過驗證的相異候選 >= 2                              → 不印(③)
  4. 唯一候選 vs 這一幀圖說自己的數字,同單位不同值        → 不印(①)
沒過任何一關 → decide() 回 Blocked(reason),呼叫端退 CTA/字卡版面,絕不印。

本檔零 rng、零網路、零檔案寫入;所有數字只從事實庫與圖說來。
自測: python narration_number_gate.py
"""
from __future__ import annotations

import math
import re
from typing import NamedTuple, Optional


def _round(v: float, nd: int) -> float:
    """四捨五入。**不能用內建 round** —— 它是銀行家捨入:round(4.5)=4,
    於是旁白「四年半」被我的解析器讀成 4 年時,會跟事實庫的 4.5 年**比中**,
    閘門反而替一個解析錯誤背書。半數一律進位,邊界上寧可比不中(fail-closed)。"""
    f = 10 ** nd
    return math.copysign(math.floor(abs(v) * f + 0.5) / f, v)

# --------------------------------------------------------------------------- #
# 1. 中文數字 → 數值
# --------------------------------------------------------------------------- #

_DIGIT = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
          "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNIT = {"十": 10, "百": 100, "千": 1000}
_NUM_CHARS = "".join(_DIGIT) + "".join(_UNIT) + "點"
# 單位詞列在 regex 尾組才會被抽:沒列到的(萬元、檔…)一律抽不出來 → 自動 fail-closed(形態②)
_SPOKEN_RE = re.compile(
    r"(負的|負|正的)?\s*(百分之)?\s*([" + _NUM_CHARS + r"]+|\d+(?:\.\d+)?)\s*"
    r"(億元|百分點|元|億|年|天|倍|%)?")


def cn_int(s: str) -> Optional[int]:
    """中文整數 → int。支援「二十八」「兩百八十八」「一千六百四十」「二零二二」。"""
    if not s:
        return None
    if all(c in _DIGIT for c in s) and not any(c in _UNIT for c in s):
        # 逐字唸法(「二零二二」=2022、「三二一」=321);單字「五」也走這條
        return int("".join(str(_DIGIT[c]) for c in s))
    total, cur = 0, 0
    for c in s:
        if c in _DIGIT:
            cur = _DIGIT[c]
        elif c in _UNIT:
            total += (cur or 1) * _UNIT[c]
            cur = 0
        else:
            return None
    return total + cur


def cn_to_float(s: str):
    """中文數字(可含「點」) → (值, 小數位數)。轉不出來回 None。
    小數位數要回傳:比對時 round 到**旁白唸出的位數**,多一位少一位都算沒中。"""
    if re.fullmatch(r"\d+(?:\.\d+)?", s or ""):
        frac = len(s.split(".")[1]) if "." in s else 0
        return float(s), frac
    if "點" in s:
        head, _, tail = s.partition("點")
        h = cn_int(head) if head else 0
        if h is None or not tail or any(c not in _DIGIT for c in tail):
            return None
        return float(f"{h}.{''.join(str(_DIGIT[c]) for c in tail)}"), len(tail)
    v = cn_int(s)
    return None if v is None else (float(v), 0)


class Spoken(NamedTuple):
    raw: str          # 原字串(「負的百分之六十九點八」)
    value: float      # -69.8
    frac: int         # 旁白唸到小數第幾位
    unit: str         # "%" / "元" / "年" / "天" / "倍" / "億元"


def spoken_numbers(text: str) -> list:
    """抽出這句旁白唸出來的數字。認不得單位的(萬元、檔、純年份…)不收 → fail-closed。"""
    out = []
    for m in _SPOKEN_RE.finditer(text or ""):
        neg, pct, body, unit = m.group(1), m.group(2), m.group(3), m.group(4)
        if pct or unit == "%":
            unit = "%"
        elif unit == "億元" or unit == "億":
            unit = "億元"
        elif unit not in ("元", "年", "天", "倍"):
            continue                      # 沒有可辨識單位 → 不收(形態②)
        got = cn_to_float(body)
        if got is None:
            continue
        v, frac = got
        if neg in ("負的", "負"):
            v = -v
        out.append(Spoken(m.group(0).strip(), v, frac, unit))
    return out


# --------------------------------------------------------------------------- #
# 2. 事實庫的固定表示法(形態⑤:逐欄位列舉,沒有容差參數)
# --------------------------------------------------------------------------- #

# 欄位名 → (單位, 顯示值 = 原值 * 係數, 旁白必須出現的指標詞)。沒列到的欄位一律不參與比對。
#
# 🔴 為什麼要有第三欄(指標詞):只比「數值+單位」會比中**語意無關的欄位**。
# 實測本片 216 個 cue:「這意味著如果你在這**一年**持有富採」比中了
# dividend_history.consecutive_years=1、「即使你抱了**五年多**」比中了
# underwater.max_underwater_years=4.5(四捨五入後都是 5)。兩句都不是在講那個欄位,
# 印出去就是拿一個真實欄位替一句無關的話背書。派工單要的是「完全吻合的**欄位**/值」,
# 所以欄位本身也要被旁白點名;點不到名 → 不印(fail-closed)。
_REPR = {
    # 比率欄位:事實庫存 -0.6981959…,畫面/旁白講 -69.8%
    "total_return": ("%", 100.0, ("總報酬",)),
    "cagr": ("%", 100.0, ("年化",)),
    "max_drawdown": ("%", 100.0, ("回撤",)),
    "return": ("%", 100.0, ("年度報酬", "年報酬")),
    "yoy": ("%", 100.0, ("年增",)),
    "drawdown": ("%", 100.0, ("腰斬", "回撤")),
    "avg_yield_5y": ("%", 100.0, ("殖利率",)),
    # 本來就是百分比的欄位
    "gross_margin": ("%", 1.0, ("毛利率",)),
    "latest_dividend_yield": ("%", 1.0, ("殖利率",)),
    # 元 / 年 / 天 / 倍 / 億元
    "eps": ("元", 1.0, ("每股盈餘", "EPS")),
    "cash_dividend": ("元", 1.0, ("現金股利", "配息")),
    "from_peak_price": ("元", 1.0, ("高點",)),
    "halved_price": ("元", 1.0, ("腰斬",)),
    "years": ("年", 1.0, ("上市以來", "年前", "區間", "期間")),
    "max_underwater_years": ("年", 1.0, ("套牢", "解套", "新高")),
    "max_underwater_days": ("天", 1.0, ("套牢", "解套", "新高")),
    "latest_per": ("倍", 1.0, ("本益比",)),
    "p25": ("倍", 1.0, ("本益比",)), "median": ("倍", 1.0, ("本益比",)),
    "p75": ("倍", 1.0, ("本益比",)),
    "revenue": ("億元", 1e-8, ("營收",)),
}


def _leaves(node, path=""):
    """把事實庫該檔的巢狀 dict/list 攤平成 (欄位名, 值, 完整路徑)。"""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, f"{path}[{i}]")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield path.rsplit(".", 1)[-1].split("[")[0], float(node), path


def match_fact(sp: Spoken, facts_for_code: dict, text: str = ""):
    """回這個旁白數字**完全吻合**的事實庫路徑;沒有回 None(形態②)。
    吻合定義:旁白點到這個欄位的指標詞、單位相同,且 _round(顯示值, 旁白小數位) == 旁白值。
    沒有容差參數 —— 有容差就等於退化成模糊比對(形態⑤)。"""
    for name, val, path in _leaves(facts_for_code):
        rep = _REPR.get(name)
        if rep is None or rep[0] != sp.unit:
            continue
        if not any(w in text for w in rep[2]):
            continue
        if _round(val * rep[1], sp.frac) == _round(sp.value, sp.frac):
            return path
    return None


# --------------------------------------------------------------------------- #
# 3. 閘門
# --------------------------------------------------------------------------- #

_CHART_NUM_RE = re.compile(r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|倍|元|億元|年|天)")


def chart_numbers(caption: str) -> list:
    """這一幀圖說自己印出來的數字(值, 單位)。圖說由 concept_visuals 從真資料現算。"""
    out = []
    for m in _CHART_NUM_RE.finditer(caption or ""):
        try:
            out.append((float(m.group(1).replace(",", "")), m.group(2)))
        except ValueError:
            continue
    return out


class Decision(NamedTuple):
    ok: bool
    number: Optional[str]     # 要印在畫面上的字串,例如 "-69.8%"
    fact_path: Optional[str]  # 它的事實來源
    reason: str               # 擋下來的原因(形態編號),放行時是 "ok"


def _fmt(sp: Spoken) -> str:
    body = f"{sp.value:,.{sp.frac}f}"
    return body + ("%" if sp.unit == "%" else sp.unit)


def decide(cue_text: str, facts_for_code: dict, caption: str = "") -> Decision:
    """旁白當下這一句 → 該不該把數字印上畫面。任何一關沒過都回 ok=False。"""
    cands = spoken_numbers(cue_text)
    if not cands:
        return Decision(False, None, None, "④ 這句沒有解析得出的數字")

    hits = []
    for sp in cands:
        p = match_fact(sp, facts_for_code, cue_text)
        if p is not None:
            hits.append((sp, p))
    if not hits:
        return Decision(False, None, None, "② 事實庫沒有完全吻合的欄位")

    uniq = {(sp.value, sp.unit) for sp, _ in hits}
    if len(uniq) > 1:
        return Decision(False, None, None, f"③ 同一句有 {len(uniq)} 個通過驗證的數字,無法確定在唸哪個")

    sp, path = hits[0]
    for cv, cu in chart_numbers(caption):
        if cu == sp.unit and _round(cv, sp.frac) != _round(sp.value, sp.frac):
            return Decision(False, None, None,
                            f"① 圖說是 {cv}{cu},旁白是 {sp.value}{sp.unit},視窗不一致")
    return Decision(True, _fmt(sp), path, "ok")


# --------------------------------------------------------------------------- #
# 自測(形態 ①②③④ 各一格,外加放行的陰性對照)
# --------------------------------------------------------------------------- #

def _demo():
    facts = {
        "checkup_three_way__3714": {"stock_allin": {
            "total_return": -0.2809303518073678, "cagr": -0.0573659886151624,
            "max_drawdown": -0.6981959387610676}},
        "checkup_underwater__3714": {"max_underwater_years": 4.5, "max_underwater_days": 1640},
        "checkup_eps_trend__3714": {"series": [{"year": 2021, "eps": 3.21},
                                               {"year": 2025, "eps": -3.69}]},
    }
    assert cn_to_float("六十九點八") == (69.8, 1)
    assert cn_to_float("兩百八十八點六") == (288.6, 1)
    assert cn_to_float("一千六百四十") == (1640.0, 0)
    assert cn_to_float("三點二一") == (3.21, 2)

    d = decide("期間最大回撤曾高達負的百分之六十九點八。", facts)
    assert d.ok and d.number == "-69.8%" and "max_drawdown" in d.fact_path, d

    # ① 圖說視窗不同(漸進揭露重算成 -59.9%)
    d = decide("期間最大回撤曾高達負的百分之六十九點八。", facts,
               caption="3714 實際最大回撤 -59.9%(2021-01-06 → 2024-08-05)")
    assert not d.ok and d.reason.startswith("①"), d

    # ② 事實庫沒有這個欄位(訂閱 CTA 的進度數字 / 舉例的本金)
    d = decide("全台股1925檔一檔一檔體檢完，目前完成223檔。", facts)
    assert not d.ok and d.reason.startswith(("②", "④")), d
    d = decide("假設你投入一百萬，在最差的時候可能只剩下三十多萬。", facts)
    assert not d.ok, d

    # ③ 同一句兩個都對得上的數字
    d = decide("總報酬會是負的百分之二十八點一，年化報酬率為負的百分之五點七。", facts)
    assert not d.ok and d.reason.startswith("③"), d

    # ④ 沒有數字
    assert not decide("這對任何投資人來說都是極大的心理壓力。", facts).ok
    # ④ 解析不完整(「四年半」只讀到 4):半數進位讓它比不中 4.5,不會被閘門背書
    assert not decide("這家公司正處於史上最長套牢期，已經長達四年半。", facts).ok
    # 形態②的另一半:數字解析得出、單位也認得,但事實庫沒有這個值
    assert not decide("如果你在兩年前的高點單筆 All in 買入富採。", facts).ok
    # 指標詞沒被點名 → 不准拿語意無關的欄位背書(本片實測的兩個假陽性)
    assert not decide("這意味著如果你在這一年持有富採。", facts).ok
    assert not decide("即使你抱了五年多，不僅沒賺。", facts).ok

    # 陰性對照:圖說數字與旁白一致 → 照印
    d = decide("到現在已經一千六百四十天，都還沒創新高。", facts,
               caption="3714 史上最長套牢期 1640天")
    assert d.ok and d.number == "1,640天", d
    print("narration_number_gate 自測通過")


if __name__ == "__main__":
    _demo()
