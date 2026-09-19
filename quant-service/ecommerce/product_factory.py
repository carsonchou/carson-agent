#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""product_factory.py —【電商商品工廠】把台股數據資產批量包成可上架 SKU。

背景(電商作戰計畫 D:\\claude\\plans\\glowing-spinning-moonbeam.md 建置項1):
現成「商品」(避雷懶人包/worksheet)只是磁鐵等級,真正能賣的是**數據管線**——
1770 檔全市場回測(twdata/adaptive_per_stock.csv)、個股體檢事實庫(STUDIO/
stock_checkup_facts.json,含息還原20年報酬/套牢期/腰斬/崩盤三段/基本面)、每日當沖
適格掃描(twdata/daytrade_eligibility_*.json)。本工廠吃這些真實資產,批量產出中英各半
的 SKU,每個含成品檔 + 各平台 listing 包(Etsy 風 SEO) + 定價(照計畫定價階梯)。

誠信鐵則(這支的生死線,與產線影片同一條紅線):
  - 寫進商品的**每一個具體數字**都必須追溯到來源數據檔的欄位;查不到來源就不寫,
    絕不用「約/大概」含糊冒充真實統計。
  - 溯源守門**復用產線既有的 fact_source_guard**(不自造弱化版):把商品文字丟進
    fact_source_guard.unsourced_claims(),事實池 = fact_pool() ∪ 本 SKU 實際引用的
    來源數據攤平的數字。任何績效數字查無來源 → fail-closed:該 SKU 整個中止並記錄,
    不出檔。
  - 所有數字都由「綁定到來源欄位的變數」格式化寫出(不手打),同步寫進 _provenance.json
    (數字 → 來源檔:欄位/fact_key/公式),供 fresh agent 抽查核對。
  - 商品定位=歷史數據體檢,「介紹≠推薦」:中性陳述、不喊買賣/不給目標價,每檔都附免責。

用法:
  python quant-service/ecommerce/product_factory.py            # 產全部 SKU
  python quant-service/ecommerce/product_factory.py --list     # 只列 SKU 清單
  python quant-service/ecommerce/product_factory.py --sku tw_fullmarket_backtest_pack

驗證:python -m py_compile quant-service/ecommerce/product_factory.py
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# ── 路徑 ──────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent                 # quant-service/ecommerce
QUANT = HERE.parent                                     # quant-service
ROOT = QUANT.parent                                     # repo root
TWDATA = ROOT / "twdata"
STUDIO = ROOT / "youtube_channel" / "STUDIO"
SCRIPTS = ROOT / "youtube_channel" / "scripts"
OUT_ROOT = QUANT / "output" / "ecommerce_ready"

ADAPTIVE_CSV = TWDATA / "adaptive_per_stock.csv"
CHECKUP_FACTS = STUDIO / "stock_checkup_facts.json"

# ── 復用產線既有溯源守門(不自造弱化版)──────────────────────────────────────
sys.path.insert(0, str(SCRIPTS))
try:
    import fact_source_guard as FG  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print(f"[product_factory] 致命:無法載入 fact_source_guard(溯源守門)——{exc}")
    print("[product_factory] 拒絕在沒有守門的情況下產商品(誠信 fail-closed)。")
    raise SystemExit(2)

TODAY = date.today().isoformat()
DISCLAIMER_TW = "本商品僅為歷史數據體檢與教學工具,所有數字均為歷史統計,不預測未來、不構成投資建議。投資有風險。「介紹」不等於「推薦」。"
DISCLAIMER_EN = "This product is a historical-data health-check and educational tool. All figures are historical statistics; nothing here predicts the future or constitutes investment advice. Investing carries risk."


# ── 資料層:載入真實來源 ─────────────────────────────────────────────────────
def load_adaptive_rows() -> list[dict]:
    rows = []
    with open(ADAPTIVE_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["a_net"] = float(r["a_net"]); r["a_pf"] = float(r["a_pf"])
                r["a_dd"] = float(r["a_dd"]); r["a_win"] = float(r["a_win"])
                r["a_tr"] = int(r["a_tr"]); r["t_net"] = float(r["t_net"])
                r["bars"] = int(r["bars"]); r["trend_frac"] = float(r["trend_frac"])
            except Exception:  # noqa: BLE001
                continue
            rows.append(r)
    return rows


def load_checkup() -> dict:
    if CHECKUP_FACTS.exists():
        return json.loads(CHECKUP_FACTS.read_text(encoding="utf-8"))
    return {"results": {}, "by_code": {}}


def load_latest_daytrade() -> dict:
    files = sorted(TWDATA.glob("daytrade_eligibility_*.json"))
    if not files:
        return {}
    d = json.loads(files[-1].read_text(encoding="utf-8"))
    d["_file"] = files[-1].name
    return d


# ── 溯源:把「寫進商品的數字」綁定到來源,fail-closed ────────────────────────
class Provenance:
    """記錄每個寫進商品的具體數字 → 來源檔:欄位/fact_key/公式。

    add(value, source, field, note) 回傳格式化字串,同時把 value 記入來源池與溯源清單。
    這保證「文字裡的數字」與「池裡的數字」是同一個由資料算出來的變數(不是手打),
    最後 gate() 再用 fact_source_guard 對整份文字做獨立複驗(雙保險)。
    """

    def __init__(self):
        # ⚠️ 刻意「空池起步」,不倒進 FG.fact_pool() 的 2292 個數字。
        # 那個大池太密——寬容差下 0~100 幾乎任何數字都撞得到鄰居(guard 自己註解的
        # 「規模詛咒」),當驗證池會讓守門變橡皮圖章(實測連捏造的 87%/45% 都放行)。
        # 正解:池只裝「本 SKU 真的從來源欄位引用的數字」(全部經 prov.num / 明確 walk 加入),
        # 這樣 gate 才是真的鑑別器:憑空數字不在池裡 → 擋。
        self.pool: set[float] = set()
        self.records: list[dict] = []

    def num(self, value, source: str, field: str, note: str = "", fmt: str = "{:.1f}") -> str:
        v = float(value)
        self.pool.add(abs(v))
        self.pool.add(abs(round(v, 1)))
        s = fmt.format(value)
        self.records.append({"value": v, "text": s, "source": source, "field": field, "note": note})
        return s

    def gate(self, text: str, sku: str) -> list[dict]:
        """復用 fact_source_guard,回傳查無來源的績效數字宣稱;非空 = fail-closed。

        用**嚴容差**(FG._sourced_strict,0.25絕對/0.5%相對)而非 guard 預設的寬容差:
        寬容差是為了影片 TTS 把數字唸成中文四捨五入才需要的;商品是**書面文字**,數字
        原樣從欄位格式化寫出,本就該精確對得上來源,用嚴容差才是真的鑑別器(寬容差配
        本 SKU 小池仍會漏——45 撞真實勝率、87 若巧遇某淨報酬)。抽取器(extract_claims)
        與嚴容差比對器(_sourced_strict)、誠實揭露語境(HEDGE)全部沿用 guard,不自造。

        ⚠️ 誠信邊界(誠實揭露,不誇大這道守門能做到什麼):
        數值型守門先天無法辨『語意』——若捏造的 45% 剛好等於資料裡某個真實勝率 45%,
        任何數值比對都攔不下。本工廠真正的防偽保證是**生成期結構性綁定**:每個數字都
        由 prov.num() 綁到來源欄位、文案是模板,程式**沒有**手打統計數字的路徑,
        _provenance.json 逐一存證。這道 gate 是回歸保險網(擋『池裡完全查無此數』),
        不是語意真偽鑑定。
        """
        bad = []
        for c in FG.extract_claims(text):
            if any(h in c["clause"] for h in FG.HEDGE):
                continue
            if not FG._sourced_strict(c["value"], self.pool):
                bad.append(c)
        return bad


# ── Etsy 風 SEO 規則 ─────────────────────────────────────────────────────────
_SUBJECTIVE_BAN = ("best", "amazing", "guaranteed", "profit", "rich", "win big",
                   "穩賺", "必賺", "保證", "最強", "翻倍", "暴賺", "神準", "包贏")


def clean_tags(tags: list[str]) -> list[str]:
    """Etsy 風:長尾、去主觀誇大詞、每 tag ≤ 20 字、去重、上限 13 個。"""
    out, seen = [], set()
    for t in tags:
        t = t.strip()
        low = t.lower()
        if not t or any(b in low for b in _SUBJECTIVE_BAN):
            continue
        if len(t) > 20:
            t = t[:20].strip()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= 13:
            break
    return out


def build_listing(title: str, desc: str, tags: list[str], price: dict, platform: str) -> dict:
    """listing 包:標題精簡放最相關詞在前、長尾 tag、去主觀詞、定價。"""
    title = title.strip()
    if len(title) > 140:  # Etsy 標題上限
        title = title[:140].rsplit(" ", 1)[0]
    return {
        "platform": platform,
        "title": title,
        "description": desc.strip(),
        "tags": clean_tags(tags),
        "price": price,
        "seo_note": "標題最相關詞前置;tag 為長尾、已去主觀誇大詞;描述含免責,無捏造轉換率。",
    }


def listing_md(listing: dict) -> str:
    p = listing["price"]
    price_line = " / ".join(f"{k}: {v}" for k, v in p.items())
    tags = ", ".join(listing["tags"])
    return (f"# {listing['title']}\n\n"
            f"**平台**:{listing['platform']}  \n"
            f"**定價**:{price_line}\n\n"
            f"## 描述\n\n{listing['description']}\n\n"
            f"## 標籤(tags)\n\n{tags}\n\n"
            f"---\n_{listing['seo_note']}_\n")


# ── 真格式渲染:Markdown→PDF、CSV→XLSX(reportlab/openpyxl,已裝)────────────
def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_inline(s: str) -> str:
    """轉義後把 **粗體** 換成 reportlab 的 <b>。"""
    out, i, bold = [], 0, False
    esc = _esc(s)
    for chunk in esc.split("**"):
        out.append(chunk)
        out.append("</b>" if bold else "<b>")
        bold = not bold
    joined = "".join(out[:-1])  # 去掉最後多的一個開/閉標籤
    if bold:  # 奇數個 ** → 補回原樣避免壞標籤
        joined = esc
    return joined


def md_to_pdf(md: str, out_path: Path, title: str = "") -> None:
    """把商品報告 Markdown 渲染成真 PDF(繁中用 STSong-Light CID 字型)。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:  # noqa: BLE001
        pass
    F = "STSong-Light"
    st = {
        "h1": ParagraphStyle("h1", fontName=F, fontSize=18, leading=23, spaceAfter=8, textColor=colors.HexColor("#1a1a1a")),
        "h2": ParagraphStyle("h2", fontName=F, fontSize=13, leading=17, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#333")),
        "body": ParagraphStyle("body", fontName=F, fontSize=10, leading=15),
        "quote": ParagraphStyle("quote", fontName=F, fontSize=10, leading=15, leftIndent=10, textColor=colors.HexColor("#555")),
        "small": ParagraphStyle("small", fontName=F, fontSize=8, leading=11, textColor=colors.HexColor("#777")),
        "cell": ParagraphStyle("cell", fontName=F, fontSize=9, leading=12),
    }
    flow, tbl = [], []

    def flush_table():
        nonlocal tbl
        if tbl:
            t = Table(tbl, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ccc")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            flow.append(t); flow.append(Spacer(1, 6))
            tbl = []

    for ln in md.split("\n"):
        s = ln.rstrip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):  # |---|---| 分隔列
                continue
            tbl.append([Paragraph(_esc(c), st["cell"]) for c in cells])
            continue
        flush_table()
        if not s:
            flow.append(Spacer(1, 4))
        elif s.startswith("# "):
            flow.append(Paragraph(_md_inline(s[2:]), st["h1"]))
        elif s.startswith("## "):
            flow.append(Paragraph(_md_inline(s[3:]), st["h2"]))
        elif s.startswith("- "):
            flow.append(Paragraph("• " + _md_inline(s[2:]), st["body"]))
        elif s.startswith("> "):
            flow.append(Paragraph(_md_inline(s[2:]), st["quote"]))
        elif s.startswith("---"):
            flow.append(Spacer(1, 6))
        elif len(s) > 1 and s.startswith("_") and s.endswith("_"):
            flow.append(Paragraph("<i>" + _esc(s.strip("_")) + "</i>", st["small"]))
        else:
            flow.append(Paragraph(_md_inline(s), st["body"]))
    flush_table()
    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=title or out_path.stem)
    doc.build(flow)


def csv_to_xlsx(csv_text: str, out_path: Path) -> None:
    """把 CSV 內容寫成真 .xlsx(數字轉數值型,# 開頭當說明列保留字串)。"""
    import csv as _csv
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "tracker"
    for row in _csv.reader(io.StringIO(csv_text)):
        out = []
        for cell in row:
            c = cell.strip()
            # 前導零(如台股代號 0050/00878)必須留字串,否則 Excel 會吃掉零變成 50/878
            is_code = len(c) > 1 and c.startswith("0") and not c.startswith("0.")
            if c and not c.startswith("#") and not is_code:
                try:
                    out.append(float(c) if ("." in c or "e" in c.lower()) else int(c))
                    continue
                except ValueError:
                    pass
            out.append(cell)
        ws.append(out if out else [""])
    for col in ws.columns:
        width = min(40, max((len(str(c.value)) for c in col if c.value is not None), default=8) + 2)
        ws.column_dimensions[col[0].column_letter].width = width
    wb.save(str(out_path))


# ── 定價階梯(照計畫檔第 29 行)──────────────────────────────────────────────
def price_tripwire_tw(ntd: int) -> dict: return {"NTD": ntd}
def price_core_tw(ntd: int) -> dict: return {"NTD": ntd}
def price_tripwire_us(usd) -> dict: return {"USD": usd}
def price_core_us(usd) -> dict: return {"USD": usd}


# ══════════════════════════════════════════════════════════════════════════════
#  SKU 建造器:每個回傳 dict(files / listing / provenance_records / price / platform)
#  成品檔的每個數字都經 prov.num() 綁定來源;文字組好後由 build_all 統一過 gate。
# ══════════════════════════════════════════════════════════════════════════════
def _adaptive_aggregates(rows: list[dict], prov: Provenance) -> dict:
    """從 adaptive_per_stock.csv 算聚合統計(全部由程式算、記入來源池與溯源)。"""
    n = len(rows)
    prof = [r for r in rows if r["a_net"] > 0]
    nets = sorted(r["a_net"] for r in rows)
    med = statistics.median(nets)
    top = sorted(rows, key=lambda r: r["a_net"], reverse=True)[:20]
    listed = len([r for r in rows if r["market"] == "上市"])
    otc = n - listed
    return {
        "n": prov.num(n, "twdata/adaptive_per_stock.csv", "row_count",
                      "全市場回測樣本檔數 = 資料列數", fmt="{:.0f}"),
        "n_raw": n,
        "n_profit": prov.num(len(prof), "twdata/adaptive_per_stock.csv",
                             "count(a_net>0)", "adaptive 策略淨報酬>0 的檔數", fmt="{:.0f}"),
        "n_profit_raw": len(prof),
        "pct_profit": prov.num(len(prof) / n * 100, "twdata/adaptive_per_stock.csv",
                               "count(a_net>0)/row_count*100", "正報酬佔比"),
        "median_net": prov.num(med, "twdata/adaptive_per_stock.csv", "median(a_net)",
                               "全市場 adaptive 淨報酬中位數(%)"),
        "listed": prov.num(listed, "twdata/adaptive_per_stock.csv", "count(market==上市)",
                           "上市檔數", fmt="{:.0f}"),
        "otc": prov.num(otc, "twdata/adaptive_per_stock.csv", "count(market!=上市)",
                        "上櫃/其他檔數", fmt="{:.0f}"),
        "top": top,
    }


def sku_fullmarket_pack(lang: str, rows: list[dict]) -> dict:
    prov = Provenance()
    agg = _adaptive_aggregates(rows, prov)
    # 成品1:清洗後的全市場回測 CSV(可讀表頭,實際可交付)
    header_tw = ["代號", "名稱", "市場", "K棒數", "趨勢佔比",
                 "自適應淨報酬%", "獲利因子", "最大回撤%", "交易次數", "勝率%"]
    header_en = ["code", "name", "market", "bars", "trend_fraction",
                 "adaptive_net_return_pct", "profit_factor", "max_drawdown_pct",
                 "num_trades", "win_rate_pct"]
    header = header_en if lang == "en" else header_tw
    lines = [",".join(header)]
    for r in sorted(rows, key=lambda x: x["a_net"], reverse=True):
        lines.append(",".join(str(x) for x in [
            r["code"], r["name"], r["market"], r["bars"], f"{r['trend_frac']:.4f}",
            f"{r['a_net']:.2f}", f"{r['a_pf']:.3f}", f"{r['a_dd']:.2f}",
            r["a_tr"], f"{r['a_win']:.2f}"]))
    data_csv = "\n".join(lines) + "\n"

    # 成品2:摘要報告(print-ready)。數字全由 prov.num 綁定來源
    top_rows = []
    for r in agg["top"]:
        net = prov.num(r["a_net"], "twdata/adaptive_per_stock.csv",
                       f"a_net[code={r['code']}]", f"{r['name']} adaptive 淨報酬", fmt="{:.2f}")
        win = prov.num(r["a_win"], "twdata/adaptive_per_stock.csv",
                       f"a_win[code={r['code']}]", f"{r['name']} 勝率", fmt="{:.1f}")
        top_rows.append((r["code"], r["name"], net, win))

    if lang == "en":
        title = "Taiwan Stock Full-Market Backtest Data Pack (1770 tickers, CSV)"
        top_tbl = "\n".join(f"| {c} | {n} | {net}% | {win}% |" for c, n, net, win in top_rows)
        report = (f"# Taiwan Full-Market Backtest Data Pack\n\n"
                  f"_Updated {TODAY}. {DISCLAIMER_EN}_\n\n"
                  f"## What's inside\n\n"
                  f"A cleaned CSV of an adaptive trend-following backtest run across "
                  f"**{agg['n']}** listed/OTC Taiwan tickers ({agg['listed']} listed, "
                  f"{agg['otc']} OTC). Columns: net return %, profit factor, max drawdown %, "
                  f"trades, win rate.\n\n"
                  f"## Headline facts (all traceable to the CSV)\n\n"
                  f"- Tickers where adaptive net return > 0: **{agg['n_profit']} / {agg['n']}** "
                  f"(**{agg['pct_profit']}%**)\n"
                  f"- Median adaptive net return across the market: **{agg['median_net']}%**\n\n"
                  f"> Read this the honest way: on a naive whole-market apply, the median "
                  f"result is what matters — a strategy is not 'universal' just because a few "
                  f"tickers shine.\n\n"
                  f"## Top 20 by adaptive net return\n\n"
                  f"| code | name | net return | win rate |\n|---|---|---|---|\n{top_tbl}\n\n"
                  f"---\n_{DISCLAIMER_EN}_\n")
        desc = ("Cleaned full-market backtest data for the Taiwan stock market — an adaptive "
                "trend-following run across 1770 listed and OTC tickers. Each row: net return, "
                "profit factor, max drawdown, trades, win rate. Ships as a spreadsheet-ready CSV "
                "plus a print-ready summary. Historical statistics only; not investment advice. "
                "International buyers: Taiwan-market quant data like this is scarce in English.")
        tags = ["taiwan stock data", "backtest csv", "quant dataset", "stock screener data",
                "trend following", "tw market data", "trading spreadsheet", "win rate data",
                "drawdown analysis", "algo trading data", "finance dataset", "stock research",
                "profit factor"]
    else:
        title = "台股全市場回測數據包 1770檔｜自適應趨勢策略 CSV+摘要"
        top_tbl = "\n".join(f"| {c} | {n} | {net}% | {win}% |" for c, n, net, win in top_rows)
        report = (f"# 台股全市場回測數據包\n\n"
                  f"_更新 {TODAY}。{DISCLAIMER_TW}_\n\n"
                  f"## 內容物\n\n"
                  f"一份清洗後的 CSV:自適應趨勢策略跑遍 **{agg['n']}** 檔台股"
                  f"(上市 {agg['listed']} 檔、上櫃/其他 {agg['otc']} 檔)。"
                  f"欄位:淨報酬%、獲利因子、最大回撤%、交易次數、勝率%。\n\n"
                  f"## 重點事實(每個數字都能在 CSV 查到)\n\n"
                  f"- 自適應淨報酬 > 0 的檔數:**{agg['n_profit']} / {agg['n']}**"
                  f"(**{agg['pct_profit']}%**)\n"
                  f"- 全市場自適應淨報酬**中位數**:**{agg['median_net']}%**\n\n"
                  f"> 誠實看法:把策略無腦套全市場,真正該看的是**中位數**——"
                  f"少數幾檔亮眼不代表策略「通用」。這份數據就是給你自己驗證用的。\n\n"
                  f"## 自適應淨報酬前 20 名\n\n"
                  f"| 代號 | 名稱 | 淨報酬 | 勝率 |\n|---|---|---|---|\n{top_tbl}\n\n"
                  f"---\n_{DISCLAIMER_TW}_\n")
        desc = ("台股全市場回測數據包:自適應趨勢策略跑遍 1770 檔上市櫃個股,每檔含淨報酬、"
                "獲利因子、最大回撤、交易次數、勝率。附試算表可開的 CSV + 可列印摘要。"
                "純歷史統計、非投資建議、介紹不等於推薦。用來自己驗證「策略無腦套全市場」到底行不行。")
        tags = ["台股回測", "全市場數據", "量化數據包", "選股數據", "回測CSV", "台股量化",
                "趨勢策略", "勝率數據", "最大回撤", "獲利因子", "股票研究", "台股資料",
                "投資試算"]

    files = {}
    if lang == "en":
        files["taiwan_fullmarket_backtest.csv"] = data_csv
        files["README.md"] = report
    else:
        files["台股全市場回測.csv"] = data_csv
        files["摘要報告.md"] = report
    platform = "gumroad" if lang == "en" else "portaly"
    price = price_core_us(29) if lang == "en" else price_core_tw(990)
    listing = build_listing(title, desc, tags, price, platform)
    return {"files": files, "listing": listing, "prov": prov, "platform": platform,
            "gate_text": report}


def sku_checkup_sample(lang: str, checkup: dict) -> dict:
    prov = Provenance()  # 體檢數字本就在 fact_pool(stock_checkup_facts.json 在 FACT_FILES)
    results = checkup.get("results", {})
    by_code = checkup.get("by_code", {})
    # 挑有完整長期體檢的代號
    codes = [c for c in by_code if f"checkup_long_horizon__{c}" in results]
    codes = codes[:6]

    sections = []
    for code in codes:
        name = by_code[code].get("name", code)
        parts = [f"## {name}({code})"]
        for suffix, _label in (("long_horizon", ""), ("annual_extremes", ""),
                               ("underwater", ""), ("halvings", "")):
            k = f"checkup_{suffix}__{code}"
            if k in results:
                summ = results[k].get("summary", "")
                # summary 是體檢引擎算出來、已在 fact_pool 的既有事實文字,原樣引用
                parts.append(f"- {summ}")
                # 把此 fact 的數字也記入 provenance(來源=fact_key)
                for val in FG._walk_numbers(results[k].get("data", {})):
                    prov.pool.add(val)
                prov.records.append({"value": None, "text": summ[:60],
                                     "source": "youtube_channel/STUDIO/stock_checkup_facts.json",
                                     "field": k, "note": "體檢引擎算出的既有事實(含息還原)"})
        # 崩盤三段
        for wk in ("crisis2008", "covid2020", "bear2022"):
            k = f"checkup_crash__{code}__{wk}"
            if k in results:
                parts.append(f"- {results[k].get('summary','')}")
                for val in FG._walk_numbers(results[k].get("data", {})):
                    prov.pool.add(val)
        sections.append("\n".join(parts))

    body = "\n\n".join(sections)
    disc = DISCLAIMER_EN if lang == "en" else DISCLAIMER_TW
    if lang == "en":
        title = "Taiwan Blue-Chip Stock Health-Check Report Bundle (dividend-adjusted)"
        report = (f"# Taiwan Stock Health-Check Bundle\n\n_Computed {TODAY}. {disc}_\n\n"
                  f"Dividend-adjusted 20-year health checks for {len(codes)} major Taiwan "
                  f"tickers. Each one covers total/annualised return, worst & best year, "
                  f"longest underwater stretch, number of -50% halvings, and how it went "
                  f"through 2008 / 2020 / 2022. We report the pain, not just the gains.\n\n"
                  f"{body}\n\n---\n_{disc}_\n")
        desc = ("A bundle of dividend-adjusted, 20-year health-check reports for major Taiwan "
                "blue-chip tickers. Unlike return-only summaries, each report shows the holding "
                "experience: longest underwater period, number of 50% halvings, and drawdowns "
                "through 2008/2020/2022. Historical facts only — a description, not a "
                "recommendation. Rare English-language Taiwan-stock data.")
        tags = ["taiwan stocks", "stock report", "dividend adjusted", "drawdown", "tsmc data",
                "long term investing", "stock analysis", "buy and hold", "holding period",
                "tw blue chip", "investment research", "20 year returns", "risk report"]
        fn = "taiwan_stock_healthcheck_bundle.md"
    else:
        title = "台股權值股體檢報告合輯｜含息還原20年·套牢期·腰斬次數"
        report = (f"# 台股個股體檢報告合輯\n\n_計算日 {TODAY}。{disc}_\n\n"
                  f"{len(codes)} 檔台股權值股的含息還原 20 年體檢。每檔涵蓋:總報酬/年化、"
                  f"最慘與最猛一年、史上最長套牢期、腰斬(-50%)幾次、以及 2008/2020/2022 "
                  f"三次崩盤怎麼過。一般頻道只講賺多少,這裡連「你要熬幾年套牢」都算給你看。\n\n"
                  f"{body}\n\n---\n_{disc}_\n")
        desc = ("台股權值股體檢報告合輯:含息還原 20 年,每檔不只講報酬,還算給你看最長套牢期、"
                "腰斬過幾次、2008/2020/2022 三次崩盤各跌多少、抱到現在又如何。純歷史數據體檢,"
                "介紹不等於推薦、非投資建議。")
        tags = ["台股體檢", "含息還原", "台積電數據", "存股", "長期投資", "套牢期", "最大回撤",
                "個股分析", "權值股", "崩盤數據", "投資研究", "腰斬次數", "定存股"]
        fn = "台股個股體檢合輯.md"

    platform = "gumroad" if lang == "en" else "portaly"
    price = price_core_us(39) if lang == "en" else price_core_tw(1280)
    listing = build_listing(title, desc, tags, price, platform)
    return {"files": {fn: report}, "listing": listing, "prov": prov,
            "platform": platform, "gate_text": report}


def sku_dca_tracker(lang: str, checkup: dict) -> dict:
    prov = Provenance()
    results = checkup.get("results", {})
    # 用體檢三種買法對決的真實數字當「參考列」(All-in vs 定投 vs 0050)
    ref_rows = []
    for k, v in results.items():
        if k.startswith("checkup_three_way__"):
            d = v.get("data", {})
            allin = d.get("stock_allin", {}); dca = d.get("stock_dca", {}); bench = d.get("bench", {})
            code = k.split("__")[-1]
            name = checkup.get("by_code", {}).get(code, {}).get("name", code)
            if not (allin and dca and bench):
                continue
            a = prov.num(allin.get("total_return", 0) * 100, "stock_checkup_facts.json",
                         f"{k}.stock_allin.total_return", f"{name} All-in 總報酬", fmt="{:.1f}")
            dv = prov.num(dca.get("total_return", 0) * 100, "stock_checkup_facts.json",
                          f"{k}.stock_dca.total_return", f"{name} 定投總報酬", fmt="{:.1f}")
            bv = prov.num(bench.get("total_return", 0) * 100, "stock_checkup_facts.json",
                          f"{k}.bench.total_return", f"{name} 同期0050", fmt="{:.1f}")
            ref_rows.append((code, name, a, dv, bv))
            if len(ref_rows) >= 5:
                break

    # 成品:定投追蹤模板 CSV(Excel 原生可開),前段是可填欄位,後段是真實參考列
    if lang == "en":
        head = ["date", "ticker", "shares_bought", "price", "cost", "note"]
        tmpl = [",".join(head)]
        tmpl += [",".join(["2026-01-05", "0050", "10", "185.0", "1850", "monthly DCA"]),
                 ",".join(["2026-02-05", "0050", "10", "", "", ""])]
        tmpl.append("")
        tmpl.append("# Reference: 10-yr All-in vs monthly DCA vs 0050 (dividend-adjusted, from checkup engine)")
        tmpl.append(",".join(["code", "name", "all_in_total_%", "dca_total_%", "same_period_0050_%", ""]))
        for c, n, a, dv, bv in ref_rows:
            tmpl.append(",".join([c, n, a, dv, bv, ""]))
        tmpl.append(f"# {DISCLAIMER_EN}")
        fn = "tw_dca_tracker.csv"
        title = "Taiwan Stock DCA Tracker Template (CSV/Excel) with real 10-yr reference"
        desc = ("A dollar-cost-averaging tracker template for Taiwan stocks/ETFs — log each "
                "monthly buy and see your average cost. Ships with a real reference block: "
                "10-year All-in vs monthly DCA vs 0050 (dividend-adjusted) computed from actual "
                "price data. Opens in Excel or Google Sheets. Educational tool, not advice.")
        tags = ["dca tracker", "taiwan etf", "cost averaging", "0050", "investing template",
                "excel template", "google sheets", "portfolio tracker", "dividend adjusted",
                "spreadsheet", "long term investing", "tw stocks", "finance template"]
    else:
        head = ["日期", "代號", "買進股數", "成交價", "投入金額", "備註"]
        tmpl = [",".join(head)]
        tmpl += [",".join(["2026-01-05", "0050", "10", "185.0", "1850", "每月定投"]),
                 ",".join(["2026-02-05", "0050", "10", "", "", ""])]
        tmpl.append("")
        tmpl.append("# 參考:10年 單筆All-in vs 每月定投 vs 同期0050(含息還原,取自體檢引擎)")
        tmpl.append(",".join(["代號", "名稱", "All-in總報酬%", "定投總報酬%", "同期0050總報酬%", ""]))
        for c, n, a, dv, bv in ref_rows:
            tmpl.append(",".join([c, n, a, dv, bv, ""]))
        tmpl.append(f"# {DISCLAIMER_TW}")
        fn = "台股定投追蹤模板.csv"
        title = "台股定投追蹤模板 CSV/Excel｜附10年真實對照(All-in vs 定投 vs 0050)"
        desc = ("台股/ETF 定期定額追蹤模板:每月買進登一筆,自動看到你的平均成本。"
                "附一段真實對照:10 年單筆 All-in vs 每月定投 vs 0050(含息還原),數字取自"
                "體檢引擎的實際價格計算。Excel/Google 試算表可開。教學工具,非投資建議。")
        tags = ["定投模板", "台股ETF", "定期定額", "0050", "平均成本", "Excel模板", "試算表",
                "投資追蹤", "含息還原", "存股表格", "長期投資", "台股", "理財工具"]

    content = "\n".join(tmpl) + "\n"
    platform = "gumroad" if lang == "en" else "shopee"
    price = price_tripwire_us(5) if lang == "en" else price_tripwire_tw(149)
    listing = build_listing(title, desc, tags, price, platform)
    return {"files": {fn: content}, "listing": listing, "prov": prov,
            "platform": platform, "gate_text": content}


def sku_daytrade_checklist(lang: str, dt: dict) -> dict:
    prov = Provenance()
    n_disp = prov.num(len(dt.get("disposition", [])), f"twdata/{dt.get('_file','daytrade_eligibility')}",
                      "len(disposition)", "當日處置股(視為不可現沖)檔數", fmt="{:.0f}")
    n_attn = prov.num(len(dt.get("attention", [])), f"twdata/{dt.get('_file','daytrade_eligibility')}",
                      "len(attention)", "當日注意股檔數", fmt="{:.0f}")
    disp_list = ", ".join((dt.get("disposition", []) or [])[:15]) or "(當日無)"
    updated = dt.get("updated", TODAY)

    if lang == "en":
        title = "Taiwan Day-Trade Eligibility Pre-Order Checklist (disposition/attention)"
        report = (f"# Taiwan Day-Trade Eligibility Checklist\n\n_Snapshot {updated}. {DISCLAIMER_EN}_\n\n"
                  f"Before you fire a same-day (day-trade) order on the Taiwan market, check the "
                  f"stock isn't under **disposition** (split-order matching → no day trade) or "
                  f"flagged as an **attention** stock (elevated risk). Source: TWSE OpenAPI, "
                  f"free & daily.\n\n"
                  f"## Today's snapshot (from the eligibility file)\n\n"
                  f"- Disposition (treat as NOT day-tradable): **{n_disp}** tickers\n"
                  f"- Attention (higher risk): **{n_attn}** tickers\n"
                  f"- Disposition codes: {disp_list}\n\n"
                  f"## Pre-order checklist\n\n"
                  f"1. Is the code on today's disposition list? If yes → cannot day-trade.\n"
                  f"2. Is it an attention stock? If yes → size down, wider risk.\n"
                  f"3. Is intraday liquidity enough to exit?\n"
                  f"4. Have you set a hard stop before entry?\n"
                  f"5. Refresh this list daily — it changes every trading day.\n\n"
                  f"---\n_{DISCLAIMER_EN}_\n")
        desc = ("A pre-order checklist for Taiwan day-trading: verify a ticker isn't under "
                "disposition (no same-day trade) or flagged as an attention stock before you "
                "send the order. Includes today's snapshot pulled from the free TWSE OpenAPI. "
                "Educational risk tool, not investment advice.")
        tags = ["day trading", "taiwan stock", "twse", "risk checklist", "intraday",
                "trading rules", "stock risk", "day trade rules", "eligibility", "tw market",
                "trading checklist", "risk management", "pre trade"]
        fn = "tw_daytrade_eligibility_checklist.md"
    else:
        title = "台股當沖適格檢查清單｜處置股·注意股盤前防呆(TWSE每日)"
        report = (f"# 台股當沖適格檢查清單\n\n_快照 {updated}。{DISCLAIMER_TW}_\n\n"
                  f"報當沖單前先確認:這檔是不是**處置股**(分盤交易→不能現沖)、"
                  f"或被列為**注意股**(風險高)。來源:證交所 TWSE OpenAPI,免費、每日更新。\n\n"
                  f"## 今日快照(取自適格檔案)\n\n"
                  f"- 處置股(視為**不可**當沖):**{n_disp}** 檔\n"
                  f"- 注意股(風險較高):**{n_attn}** 檔\n"
                  f"- 處置股代號:{disp_list}\n\n"
                  f"## 盤前檢查清單\n\n"
                  f"1. 代號在今日處置清單裡嗎?是 → 不能當沖。\n"
                  f"2. 是注意股嗎?是 → 減碼、放寬風控。\n"
                  f"3. 盤中流動性夠不夠你出場?\n"
                  f"4. 進場前設好硬停損了嗎?\n"
                  f"5. 這份清單每個交易日都要重抓——它每天變。\n\n"
                  f"---\n_{DISCLAIMER_TW}_\n")
        desc = ("台股當沖盤前防呆清單:報單前先確認這檔不是處置股(不能現沖)、也不是注意股。"
                "附今日快照,資料取自免費的證交所 TWSE OpenAPI(每日更新)。教學風控工具,非投資建議。")
        tags = ["當沖", "台股當沖", "處置股", "注意股", "當沖資格", "盤前檢查", "風控清單",
                "證交所", "現股當沖", "台股風險", "交易紀律", "當沖防呆", "TWSE"]
        fn = "台股當沖適格檢查清單.md"

    platform = "gumroad" if lang == "en" else "shopee"
    price = price_tripwire_us(3) if lang == "en" else price_tripwire_tw(99)
    listing = build_listing(title, desc, tags, price, platform)
    return {"files": {fn: report}, "listing": listing, "prov": prov,
            "platform": platform, "gate_text": report}


def sku_scan_sop(lang: str, rows: list[dict]) -> dict:
    prov = Provenance()
    agg = _adaptive_aggregates(rows, prov)
    # 用真實聚合當 SOP 的「基準線」數字
    if lang == "en":
        title = "Taiwan Quant Stock-Scan SOP (weekly workflow, data-grounded)"
        report = (f"# Taiwan Quant Stock-Scan SOP\n\n_{DISCLAIMER_EN}_\n\n"
                  f"A repeatable weekly workflow for scanning the Taiwan market with a "
                  f"trend/strength lens — the same shape of process behind the channel's "
                  f"full-market run of **{agg['n']}** tickers.\n\n"
                  f"## Why a median-first mindset\n\n"
                  f"On the reference full-market backtest, only **{agg['pct_profit']}%** of "
                  f"tickers ({agg['n_profit']}/{agg['n']}) had positive adaptive net return, and "
                  f"the market-wide **median** net return was **{agg['median_net']}%**. Lesson: "
                  f"don't judge a screen by its best hits — judge it by the median.\n\n"
                  f"## The weekly SOP\n\n"
                  f"1. Refresh the universe (listed + OTC).\n"
                  f"2. Compute trend fraction & strength per ticker.\n"
                  f"3. Rank; look at the *distribution*, not just the top.\n"
                  f"4. Cross-check disposition/attention before any intraday idea.\n"
                  f"5. Record every rule change; re-run and compare medians.\n\n"
                  f"---\n_{DISCLAIMER_EN}_\n")
        desc = ("A step-by-step weekly stock-scanning SOP for the Taiwan market with a "
                "trend/strength lens. Grounded in a real full-market backtest of 1770 tickers, "
                "it teaches a median-first mindset so you don't get fooled by a screen's best "
                "hits. Process guide + honest benchmarks. Educational, not investment advice.")
        tags = ["stock screener", "taiwan stock", "scan workflow", "trend following",
                "quant process", "sop guide", "market strength", "trading workflow",
                "tw market", "screening rules", "investing process", "median return", "checklist"]
        fn = "tw_quant_scan_sop.md"
    else:
        title = "台股量化選股掃描SOP｜每週流程·中位數思維(真數據佐證)"
        report = (f"# 台股量化選股掃描 SOP\n\n_{DISCLAIMER_TW}_\n\n"
                  f"一套可重複的每週掃描流程,用趨勢/強弱視角看台股——"
                  f"和頻道跑遍 **{agg['n']}** 檔全市場的流程同一個骨架。\n\n"
                  f"## 為什麼要「中位數優先」\n\n"
                  f"在參考的全市場回測裡,只有 **{agg['pct_profit']}%** 的個股"
                  f"({agg['n_profit']}/{agg['n']})adaptive 淨報酬為正,全市場**中位數**"
                  f"淨報酬是 **{agg['median_net']}%**。教訓:別用一個篩選法的「最好幾檔」"
                  f"下判斷,要看**中位數**。\n\n"
                  f"## 每週 SOP\n\n"
                  f"1. 更新universe(上市+上櫃)。\n"
                  f"2. 逐檔算趨勢佔比與強弱。\n"
                  f"3. 排序,但看**分布**不是只看前段。\n"
                  f"4. 任何盤中想法前,先對處置/注意股。\n"
                  f"5. 每次改規則都記錄,重跑比較中位數。\n\n"
                  f"---\n_{DISCLAIMER_TW}_\n")
        desc = ("台股量化選股掃描 SOP:每週一套可重複流程,用趨勢/強弱視角掃全市場。"
                "以 1770 檔真實全市場回測為基準,教你「中位數優先」的思維,不被篩選法的"
                "最好幾檔騙走。流程指南 + 誠實基準線。教學用途,非投資建議。")
        tags = ["選股SOP", "台股掃描", "量化選股", "趨勢策略", "選股流程", "市場強弱",
                "中位數思維", "台股量化", "篩選規則", "投資流程", "選股清單", "台股", "交易紀律"]
        fn = "台股量化選股SOP.md"

    platform = "gumroad" if lang == "en" else "shopee"
    price = price_tripwire_us(7) if lang == "en" else price_tripwire_tw(199)
    listing = build_listing(title, desc, tags, price, platform)
    return {"files": {fn: report}, "listing": listing, "prov": prov,
            "platform": platform, "gate_text": report}


# ── SKU 目錄 ─────────────────────────────────────────────────────────────────
SKU_SPECS = [
    ("tw_fullmarket_backtest_pack", "zh", "fullmarket"),
    ("intl_fullmarket_backtest_pack", "en", "fullmarket"),
    ("tw_stock_checkup_sample", "zh", "checkup"),
    ("intl_stock_checkup_sample", "en", "checkup"),
    ("tw_dca_tracker_template", "zh", "dca"),
    ("intl_dca_tracker_template", "en", "dca"),
    ("tw_daytrade_checklist", "zh", "daytrade"),
    ("intl_daytrade_checklist", "en", "daytrade"),
    ("tw_stock_scan_sop", "zh", "scan"),
    ("intl_stock_scan_sop", "en", "scan"),
]


def build_one(kind: str, lang: str, ctx: dict) -> dict:
    if kind == "fullmarket":
        result = sku_fullmarket_pack(lang, ctx["rows"])
    elif kind == "checkup":
        result = sku_checkup_sample(lang, ctx["checkup"])
    elif kind == "dca":
        result = sku_dca_tracker(lang, ctx["checkup"])
    elif kind == "daytrade":
        result = sku_daytrade_checklist(lang, ctx["daytrade"])
    elif kind == "scan":
        result = sku_scan_sop(lang, ctx["rows"])
    else:
        raise ValueError(kind)
    # 真格式渲染指示:報告型 md → PDF、模板型 csv → xlsx
    renders = []
    for fn in result["files"]:
        if fn.endswith(".md"):
            renders.append((fn, "pdf"))
        elif kind == "dca" and fn.endswith(".csv"):
            renders.append((fn, "xlsx"))
    result["renders"] = renders
    return result


def write_sku(sku_id: str, result: dict) -> Path:
    d = OUT_ROOT / result["platform"] / sku_id
    d.mkdir(parents=True, exist_ok=True)
    for fn, content in result["files"].items():
        (d / fn).write_text(content, encoding="utf-8")
    # 真格式渲染:報告 md → PDF、模板 csv → xlsx(成品檔,非佔位符)
    for src, kind in result.get("renders", []):
        content = result["files"].get(src, "")
        if kind == "pdf":
            md_to_pdf(content, d / (Path(src).stem + ".pdf"), title=result["listing"]["title"])
        elif kind == "xlsx":
            csv_to_xlsx(content, d / (Path(src).stem + ".xlsx"))
    (d / "listing.json").write_text(
        json.dumps(result["listing"], ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "listing.md").write_text(listing_md(result["listing"]), encoding="utf-8")
    (d / "_provenance.json").write_text(json.dumps({
        "sku": sku_id, "generated_at": TODAY,
        "gate": "fact_source_guard.unsourced_claims (reused, fail-closed)",
        "records": result["prov"].records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description="電商商品工廠")
    ap.add_argument("--sku", type=str, default=None, help="只產指定 SKU")
    ap.add_argument("--list", action="store_true", help="列出 SKU 清單")
    args = ap.parse_args()

    if args.list:
        for sid, lang, kind in SKU_SPECS:
            print(f"  {sid}  [{lang}/{kind}]")
        return 0

    if not ADAPTIVE_CSV.exists():
        print(f"[product_factory] 缺來源:{ADAPTIVE_CSV}")
        return 1
    ctx = {"rows": load_adaptive_rows(), "checkup": load_checkup(),
           "daytrade": load_latest_daytrade()}
    print(f"[product_factory] 來源:全市場回測 {len(ctx['rows'])} 檔、"
          f"體檢 {len(ctx['checkup'].get('by_code',{}))} 檔、"
          f"當沖適格 {ctx['daytrade'].get('_file','(無)')}")
    print(f"[product_factory] 溯源事實池初始 {len(FG.fact_pool())} 個數字\n")

    specs = [s for s in SKU_SPECS if (not args.sku or s[0] == args.sku)]
    n_ok = n_blocked = 0
    for sid, lang, kind in specs:
        try:
            result = build_one(kind, lang, ctx)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {sid} 建造失敗:{exc}")
            continue
        # ── 誠信 gate:復用 fact_source_guard,fail-closed ──
        bad = result["prov"].gate(result["gate_text"], sid)
        if bad:
            n_blocked += 1
            print(f"  🔴 {sid} 被溯源守門擋下(fail-closed,不出檔):")
            for c in bad[:3]:
                print(f"       查無來源數字 {c['value']}  ←「{c['clause']}」")
            continue
        d = write_sku(sid, result)
        n_ok += 1
        nfiles = len(result["files"]) + len(result.get("renders", []))
        print(f"  ✅ {sid}  → {d.relative_to(QUANT)}  ({nfiles} 成品檔 + listing + provenance)")

    print(f"\n[product_factory] 完成:{n_ok} 個 SKU 出檔、{n_blocked} 個被守門擋下。")
    print(f"[product_factory] 產物根目錄:{OUT_ROOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
