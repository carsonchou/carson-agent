"""紙張尺寸回歸:所有 PDF 渲染路徑都必須真的印成 A4,且不得產生空白頁。

這個 bug 已經在**兩條獨立的渲染路徑**各犯一次(phase3b B1 = SKU 工廠 render_kit;
REVIEW_weekly_value #4 = 旗艦週報 weekly_report_v2),根因相同:
CSS 的 `.page` 用 A4 幾何(210×297mm),但沒有 `@page{size:A4}` 宣告時,
Chromium 的 `prefer_css_page_size=True` 沒東西可 prefer → **靜默退回 Letter**
(612×792pt,比 A4 的 842pt 矮 50pt)→ 每張 .page 溢出 50pt,被 `page-break-after:always`
推成一張整頁空白 → 買家收到一半是空白頁的商品(旗艦 full 曾 24 頁裡 11 頁空白)。

防線是雙保險(缺一即復發):CSS `@page{size:A4;margin:0}` + `page.pdf(format="A4")`。
本測試對**每一條渲染路徑**斷言那兩道防線都在,免得第三條路徑再踩同一顆雷。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ECOM = Path(__file__).resolve().parents[1]      # quant-service/ecommerce
if str(_ECOM) not in sys.path:
    sys.path.insert(0, str(_ECOM))

# 所有會呼叫 page.pdf() 的渲染路徑,新增渲染器請一併加進來
_RENDERERS = [
    _ECOM / "weekly_report_v2.py",     # 旗艦訂閱週報
    _ECOM / "render_kit.py",           # SKU 工廠共用工具箱
    _ECOM / "mockup" / "render.py",    # 樣張渲染器(會被拿來當範本抄,故也要對)
]
_STYLESHEETS = [_ECOM / "report_theme.css"]


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def test_every_render_path_pins_a4_format():
    """每個 page.pdf() 呼叫都要顯式給 format="A4" —— 不能只靠 prefer_css_page_size。

    只認「真的呼叫」:參數區必須有 path=(Playwright 的 page.pdf 一定要給輸出路徑)。
    否則 docstring 裡寫到「page.pdf (…)」這種散文也會被當成呼叫誤報。
    """
    missing, checked = [], 0
    for f in _RENDERERS:
        s = _src(f)
        for m in re.finditer(r"\.pdf\s*\(", s):
            call = s[m.start():m.start() + 400]      # 取這個呼叫的參數區
            if "path=" not in call:                  # 不是真呼叫(散文/註解)
                continue
            checked += 1
            if 'format="A4"' not in call and "format='A4'" not in call:
                line = s[:m.start()].count("\n") + 1
                missing.append(f"{f.name}:{line}")
    assert checked >= len(_RENDERERS), \
        f"只掃到 {checked} 個 page.pdf 呼叫,少於渲染器數量 {len(_RENDERERS)} —— 掃描器可能失效"
    assert not missing, (
        f"這些 page.pdf() 沒釘 format=\"A4\",會靜默退回 Letter 印出空白頁:{missing}")


def test_stylesheets_declare_at_page_a4():
    """CSS 必須宣告 @page{size:A4} —— 這是 prefer_css_page_size 的前提。"""
    for css in _STYLESHEETS:
        s = _src(css)
        assert re.search(r"@page\s*\{[^}]*size\s*:\s*A4", s), \
            f"{css.name} 缺 @page{{size:A4}} → prefer_css_page_size 無效,退回 Letter"


def test_a4_geometry_and_paper_agree():
    """.page 用 210mm×297mm(A4)才對 —— 幾何與紙張不一致正是空白頁的來源。"""
    s = _src(_ECOM / "report_theme.css")
    m = re.search(r"\.page\s*\{[^}]*width\s*:\s*(\d+)mm[^}]*height\s*:\s*(\d+)mm", s)
    assert m, ".page 找不到 width/height 宣告"
    assert (m.group(1), m.group(2)) == ("210", "297"), \
        f".page 幾何 {m.group(1)}×{m.group(2)}mm 不是 A4(210×297),與 @page size:A4 打架"
