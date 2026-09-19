# -*- coding: utf-8 -*-
"""render_kit.py — 電商 v2 共用渲染工具箱(暗色數據卡 PDF 元件 + Playwright 印製)。

單一事實來源:視覺 token 全讀 `report_theme.css`(與旗艦週報 weekly_report_v2 同一份),
確保一次性 SKU 成品與訂閱週報視覺完全一致。管線=HTML+CSS → headless Chromium → page.pdf
(print_background 印深色底、A4 紙張、繁中系統字型),分頁沿用週報實證的
JS 量測法(把 unit 依序塞進 .page 直到裝滿再開新頁)。

⚠️ 紙張(2026-07-16 修,VERIFY_REPORT_phase3b B1):`.page` 是 A4 幾何(210×297mm),但舊版
只給 `prefer_css_page_size=True` 而 HTML 從未宣告 `@page` → Chromium 無 CSS 頁面尺寸可
「prefer」,退回預設紙張 US Letter(612×792pt)。每頁 297mm≈842pt 灌進 792pt → 溢出約 50pt,
`page-break-after:always` 把那條溢出(含頁尾)推成一張整頁空白 ⇒ 全 8 支 SKU「每張內容頁後跟
一張空白頁」(C2 18 頁裡 9 頁空白)。修法雙保險:html_doc() 宣告 `@page{size:A4;margin:0}`
+ render_pdf() 明給 `format="A4"`。改動任一處前先跑 tests/test_render_kit_pdf.py(釘死空白頁=0)。

多語:頁殼字串(頁尾/頁碼/免責標題/封面聲明)全走 `_L[lang]`,不再硬編中文——英文版 SKU 要收
US$35/39,框架字串漏中文 = 對國際買家的交付缺陷(phase3b B3)。新增語系只需擴 _L。

誠信:本工具箱只負責「把已綁定來源的數字排進 HTML」,不產生任何統計數字。gate_text() 把
HTML 標籤剝掉(SVG/CSS 數字都在屬性裡,一併移除),只留可見文字供 fact_source_guard 複驗。
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
THEME_CSS = HERE / "report_theme.css"

_NUM_RE = re.compile(r"-?\d+\.?\d*")

# ── 頁殼語系字串(單一事實來源:所有頁殼中文都從這裡取,不硬編)──────────────────
_L = {
    "zh": {
        "html_lang": "zh-Hant",
        "disc_badge": "介紹 ≠ 推薦",
        "cover_total": lambda: '封面 · 共 <span class="pagetotal"></span> 頁',
        "cover_strip": ("本商品為<b>歷史/當期數據彙整與教學工具</b>,中性陳述、不喊買賣、不報明牌。"),
        "disc_title": "免責與資料來源",
        "disc_src_label": "資料來源",
        "src_join": "；",
        "gate_note": ("　每個績效數字經溯源守門(fail-closed)驗證,查無來源的段落不會出現在成品。"),
    },
    "en": {
        "html_lang": "en",
        "disc_badge": "Description ≠ recommendation",
        "cover_total": lambda: 'Cover · <span class="pagetotal"></span> pages',
        "cover_strip": ("This product is a <b>historical/current-data compilation and educational tool</b>. "
                        "Neutral statements only: no buy/sell calls, no stock tips."),
        "disc_title": "Disclaimer & Data Sources",
        "disc_src_label": "Sources",
        "src_join": "; ",
        "gate_note": ("　Every performance figure passes a fail-closed provenance gate; any passage whose "
                      "numbers cannot be traced back to a source file is withheld from the product."),
    },
}


def L(lang: str) -> dict:
    """取語系字串包(未知語系退回 zh,不炸)。"""
    return _L.get(lang, _L["zh"])


def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def load_css() -> str:
    return THEME_CSS.read_text(encoding="utf-8")


def gate_text(units: list[str]) -> str:
    """剝掉 HTML 標籤,只留可見文字(SVG 座標/CSS 數字在屬性內會被一併移除)。"""
    return re.sub(r"<[^>]+>", " ", "\n".join(units))


def pct_cls(v) -> tuple[str, str]:
    """台股色:正=紅(pos)、負=綠(neg)。回 (顯示字串, class)。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—", ""
    return (f"{v:+.1f}%", "pos" if v > 0 else "neg" if v < 0 else "")


# ── 視覺元件(全部吐 HTML 片段;數字入池由呼叫端負責)──────────────────────────
def sparkline(series: list[float], w: int = 132, h: int = 34) -> str:
    """inline SVG 金線 sparkline:polyline + 面積漸層 + 末點金點。series 需 ≥2 點。"""
    pts = [p for p in series if isinstance(p, (int, float))]
    if len(pts) < 2:
        return '<span class="mut" style="font-size:10px">—</span>'
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    n = len(pts)
    coords = []
    for i, v in enumerate(pts):
        x = round(i / (n - 1) * (w - 6) + 3, 1)
        y = round(h - 4 - (v - lo) / rng * (h - 8), 1)
        coords.append((x, y))
    line = " ".join(f"{x},{y}" for x, y in coords)
    area = f"3,{h-3} " + line + f" {coords[-1][0]},{h-3}"
    ex, ey = coords[-1]
    gid = f"gf{abs(hash(tuple(pts))) % 100000}"
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="vertical-align:middle">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#E3B93E" stop-opacity="0.28"/>'
        f'<stop offset="1" stop-color="#E3B93E" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="{area}" fill="url(#{gid})"/>'
        f'<polyline points="{line}" fill="none" stroke="#E3B93E" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{ex}" cy="{ey}" r="2.6" fill="#E3B93E"/></svg>')


def light_class(pctl: float) -> str:
    """估值位階燈號(只標位置非買賣):≤60 綠 g / 60–95 琥珀 a / ≥95 紅 r。"""
    try:
        p = float(pctl)
    except (TypeError, ValueError):
        return "a"
    return "g" if p <= 60 else ("a" if p < 95 else "r")


def pos_bar(pctl: float) -> str:
    """位階條:track + IQR 帶(P25–P75 固定映射)+ 目前值 marker(pctl%)。純位置陳述。"""
    try:
        p = max(0.0, min(100.0, float(pctl)))
    except (TypeError, ValueError):
        p = 50.0
    return (f'<span class="pbar"><span class="band" style="left:25%;width:50%"></span>'
            f'<span class="mk" style="left:{p:.0f}%"></span></span>')


def cmp_bars(rows: list[tuple]) -> str:
    """三種買法對照橫條。rows=[(label, value, maxval, is_red, value_text)];
    寬度=value/maxval,同基準才可比。value_text 由呼叫端格式化(已入池)。"""
    out = ['<div class="cmp">']
    for label, value, maxval, is_red, vtext in rows:
        w = 0.0
        try:
            w = max(0.0, min(100.0, float(value) / float(maxval) * 100)) if maxval else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            w = 0.0
        fill = "fill red" if is_red else "fill"
        out.append(
            f'<div class="row"><div class="lb">{esc(label)}</div>'
            f'<div class="track"><div class="{fill}" style="width:{w:.1f}%"></div></div>'
            f'<div class="vn">{esc(vtext)}</div></div>')
    out.append('</div>')
    return "".join(out)


def kpi_row(items: list[tuple]) -> str:
    """KPI mini-tile 橫排。items=[(caption, value_html)]。"""
    tiles = "".join(
        f'<div class="kpi"><div class="k">{esc(cap)}</div><div class="v">{val}</div></div>'
        for cap, val in items)
    return f'<div class="kpis">{tiles}</div>'


def dense_table(headers: list[tuple], rows: list[list[str]]) -> str:
    """密表。headers=[(label, align)] align in {l, r};rows 內 cell 已是安全 HTML(呼叫端 esc)。"""
    ths = "".join(f'<th class="{"l" if a=="l" else ""}">{esc(h)}</th>' for h, a in headers)
    trs = []
    for r in rows:
        tds = "".join(r)
        trs.append(f"<tr>{tds}</tr>")
    return (f'<table class="grid"><thead><tr>{ths}</tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>')


def sec_head(title: str, badge: str = "") -> str:
    b = f'<span class="tier b">{esc(badge)}</span>' if badge else ""
    return f'<div class="sec-hd"><span class="sn">·</span><h2>{esc(title)}</h2>{b}</div>'


# ── 頁面殼(封面 / 內頁模板 / 免責 / 分頁 JS)——沿用週報實證版 ──────────────────
def cover_page(brand: dict, title_lines: list[str], kicker: str, subtitle: str,
               stats: list[tuple], price_line: str, badge_txt: str, lang: str = "zh") -> str:
    lz = L(lang)
    stats_html = "".join(
        f'<div class="cstat"><div class="k">{esc(k)}</div>'
        f'<div class="v">{v}</div></div>' for k, v in stats)
    h1 = "<br>".join(esc(t) if i == 0 else f'<span class="thin">{esc(t)}</span>'
                     for i, t in enumerate(title_lines))
    return f'''<section class="page cover">
  <div class="frame"></div>
  <div class="inner">
    <div class="runhead">
      <div class="brand"><span class="logo"></span><b>{esc(brand["name_zh"])}</b>&nbsp;{esc(brand["name_en"])}</div>
      <div class="eyebrow">{esc(kicker)}</div>
    </div>
    <div class="masthead">
      <div class="kick">{esc(kicker)}</div>
      <h1>{h1}</h1>
      <div class="sub">{esc(subtitle)}</div>
      <div class="cover-stats">{stats_html}</div>
      <div class="cover-strip"><span class="badge">{esc(badge_txt)}</span>
        <span class="txt">{lz["cover_strip"]}</span></div>
      <div class="price-line">{esc(price_line)}</div>
    </div>
    <div class="runfoot"><span>{esc(brand["name_zh"])} {esc(brand["name_en"])}</span>
      <span class="disc">{esc(lz["disc_badge"])}</span><span>{lz["cover_total"]()}</span></div>
  </div>
</section>'''


def _page_template(brand: dict, product: str, sub: str, lang: str = "zh") -> str:
    lz = L(lang)
    return f'''<template id="pagetpl"><section class="page">
  <div class="frame"></div>
  <div class="inner">
    <div class="runhead">
      <div class="brand"><span class="logo"></span><b>{esc(brand["name_zh"])}</b>&nbsp;{esc(product)}</div>
      <div class="eyebrow">{esc(sub)}</div>
    </div>
    <div class="flow"></div>
    <div class="runfoot"><span>{esc(brand["name_zh"])} {esc(brand["name_en"])} · {esc(product)}</span>
      <span class="disc">{esc(lz["disc_badge"])}</span>
      <span><span class="pageno"></span> / <span class="pagetotal"></span></span></div>
  </div>
</section></template>'''


def disclaimer_unit(disclaimer: str, sources: list[str], extra: str = "", lang: str = "zh") -> str:
    lz = L(lang)
    src = lz["src_join"].join(esc(s) for s in sources)
    sep, end = (":", "。") if lang == "zh" else (": ", ".")
    return (f'<div class="unit"><div class="disc-title">{esc(lz["disc_title"])}</div>'
            f'<div class="disc-body">{esc(disclaimer)}<br><br>{extra}</div>'
            f'<div class="disc-src"><b>{esc(lz["disc_src_label"])}</b>{sep}{src}{end}'
            f'{lz["gate_note"]}</div></div>')


_PAGINATE_JS = '''<script>
(function(){
  var src=document.getElementById('src'),host=document.getElementById('pages'),tpl=document.getElementById('pagetpl');
  var units=Array.prototype.slice.call(src.children),pageNo=1,cur=null,flow=null;
  function newPage(){var p=tpl.content.firstElementChild.cloneNode(true);host.appendChild(p);
    cur=p;flow=p.querySelector('.flow');pageNo++;p.querySelector('.pageno').textContent=pageNo;return p;}
  newPage();
  for(var i=0;i<units.length;i++){var u=units[i];flow.appendChild(u);
    if(flow.scrollHeight>flow.clientHeight+1){flow.removeChild(u);newPage();flow.appendChild(u);}}
  var total=host.querySelectorAll('.page').length;
  Array.prototype.forEach.call(document.querySelectorAll('.pagetotal'),function(e){e.textContent=total;});
  src.parentNode.removeChild(src);window.__paginated__=true;
})();
</script>'''


def html_doc(brand: dict, product: str, sub: str, title: str,
             cover_html: str, unit_htmls: list[str], lang: str = "zh") -> str:
    css = load_css()
    lz = L(lang)
    # @page 必須宣告:`.page` 是 A4 幾何,不宣告則 Chromium 用 Letter → 每頁溢出成空白頁(見檔頭)。
    return f'''<!doctype html><html lang="{lz["html_lang"]}"><head><meta charset="utf-8">
<title>{esc(title)}</title><style>@page{{size:A4;margin:0}}
{css}</style></head><body>
<div id="pages">{cover_html}</div>
{_page_template(brand, product, sub, lang)}
<div id="src" style="position:absolute;left:-99999px;top:0;width:186mm">{"".join(unit_htmls)}</div>
{_PAGINATE_JS}
</body></html>'''


def render_pdf(html: str, out_pdf: Path) -> Path:
    """HTML → A4 深色 PDF(等分頁 JS 跑完)。與 mockup/render.py 同款 Playwright 參數。

    `format="A4"` 與 html_doc() 的 `@page{size:A4}` 是**雙保險**:prefer_css_page_size 只在
    CSS 真的宣告了頁面尺寸時才有東西可 prefer,否則靜默退回 Letter(見檔頭 B1)。兩者都指 A4,
    無論誰先生效結果一致;拿掉任一個都會讓空白頁 bug 復發,故兩個都留。
    """
    from playwright.sync_api import sync_playwright
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        pg.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        pg.wait_for_function("window.__paginated__ === true", timeout=15000)
        pg.emulate_media(media="print")
        pg.pdf(path=str(out_pdf), format="A4", prefer_css_page_size=True, print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        br.close()
    return out_pdf
