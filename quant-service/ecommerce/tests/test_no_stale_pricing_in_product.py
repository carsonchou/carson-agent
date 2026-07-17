"""成品不得出現停售方案或非牌價 —— 定價的單一事實來源必須貫徹到最後一哩(買家眼前)。

這個 codebase 反覆中招的病:config 改了,但下游各自有一份 → 產物還在賣舊價/停售方案,
而且不同步時**零告警**。已知現場(全部修過,本測試防它們復發):
  1. make_landing.py       把 NT$99/149/1290 寫死在 HTML
  2. webhook/config.py     SUBSCRIPTION_TIERS 自己一份 → 付 49 的人 tier 判 unknown
  3. listing_templates.py  無條件印年繳 → 要貼到 Portaly 商品頁的文案在賣停售方案
  4. pinterest_pin_gen     pin 圖燒死 "NT$99–149 / 月" → 對外廣告不存在的價格
  5. weekly_report_v2      **週報封面**無條件印年繳 → 每份寄給訂閱者的報告都在推銷停售方案

本測試從**成品端**驗(不是從程式碼端),因為病灶總是「程式看起來對、產物是錯的」。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ECOM = Path(__file__).resolve().parents[1]
if str(_ECOM) not in sys.path:
    sys.path.insert(0, str(_ECOM))

import config as CFG          # noqa: E402
import weekly_report_v2 as W  # noqa: E402


def _cover_text(tier: str = "full") -> str:
    """只組封面,不渲染 PDF(快)。"""
    state = W.load_state()
    html = W._cover_html(state, [], "2026-W29(測試)", tier)
    return re.sub(r"<[^>]+>", " ", html)


def test_cover_hides_disabled_annual():
    """年繳 enabled=False → 封面不得出現它(每份寄出去的報告都是門面)。"""
    ann = CFG.SUBSCRIPTION.get("annual") or {}
    txt = _cover_text()
    if ann.get("enabled") is False:
        assert ann["name_zh"] not in txt, "年繳已停售,封面卻還在推銷"
        assert str(ann.get("ntd_year", "")) not in txt, "封面印了停售方案的價格"


def test_cover_prices_come_from_single_source():
    """封面印的價格必須逐值等於 config —— 不得有第二份定價。"""
    txt = _cover_text()
    for key in ("basic", "full"):
        price = CFG.SUBSCRIPTION[key]["ntd_month"]
        assert f"NT${price}" in txt, f"{key} 的牌價 NT${price} 沒出現在封面(定價分岔?)"


def test_cover_has_no_stale_price_literals():
    """封面不得出現任何『不是現行牌價』的訂閱價數字(擋舊價殘留)。"""
    txt = _cover_text()
    live = {str(CFG.SUBSCRIPTION["basic"]["ntd_month"]), str(CFG.SUBSCRIPTION["full"]["ntd_month"])}
    for m in re.finditer(r"NT\$(\d+)\s*/\s*月", txt):
        assert m.group(1) in live, f"封面出現非牌價的月費 NT${m.group(1)}(現行:{live})"


def test_cover_numbers_are_bound_to_provenance():
    """封面印的檔數/類數也要進存證 —— 「每個數字可回查」不因它在封面而豁免。"""
    from product_factory import Provenance
    state = W.load_state()
    prov = Provenance()
    W._cover_html(state, [], "2026-W29(測試)", "full", prov=prov)
    fields = {r["field"] for r in prov.records}
    assert {"scanned_stocks_n", "sectors_n"} <= fields, f"封面數字未綁存證,實得 {fields}"
    for r in prov.records:
        assert r.get("source"), "封面存證未標來源"
