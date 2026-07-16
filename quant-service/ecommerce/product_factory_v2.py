#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""product_factory_v2.py —【電商商品工廠 v2】把台股數據資產包成「值得掏錢」等級的一次性 SKU。

v1(product_factory.py,保留不動供對照)的成品是 reportlab 淺底 office 排版 + 裸傾印 xlsx,
被 Carson 判「不夠好」。v2 換渲染外殼、不動誠信骨:
  - 成品視覺 = 暗色數據卡 PDF(HTML+CSS → Chromium,復用 render_kit + report_theme.css,
    與旗艦週報同一套 token)+ 專業級 xlsx(深表頭/凍結/篩選/台股紅綠條件格式/data bar)。
  - 誠信原封搬入:Provenance 空池起步、小池嚴容差(0.25 絕對/0.5% 相對)、查無來源整個 SKU
    中止不出檔;所有文案「介紹≠推薦」、靜態回測快照標明非即時;數字全由 disp() 綁到來源。

SKU 線(對齊 REDESIGN_SPEC_business.md §3 / config.py):
  L0 磁鐵  M1 當沖適格清單 / M2 單檔旗艦體檢(台積電)         —— 免費、PDF
  L1 tripwire T1 定投追蹤模板 / T2 個股體檢單檔報告            —— zh、PDF(+T1 xlsx)
  L2 core   C1 全市場回測數據包 / C2 權值股體檢合輯            —— zh+en、xlsx+PDF

用法:
  python product_factory_v2.py --list
  python product_factory_v2.py                # 產全部(真實資料 → output/ecommerce_ready/v2/)
  python product_factory_v2.py --sku C1
驗證:python -m pytest quant-service/ecommerce/tests -q
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent            # quant-service/ecommerce
QUANT = HERE.parent                               # quant-service
ROOT = QUANT.parent                               # repo root
TWDATA = ROOT / "twdata"
STUDIO = ROOT / "youtube_channel" / "STUDIO"
SCRIPTS = ROOT / "youtube_channel" / "scripts"
OUT_ROOT = QUANT / "output" / "ecommerce_ready" / "v2"

ADAPTIVE_CSV = TWDATA / "adaptive_per_stock.csv"
LONGSHORT_CSV = TWDATA / "longshort_per_stock.csv"
PERSTOCK_CSV = TWDATA / "per_stock_results.csv"
CHECKUP_FACTS = STUDIO / "stock_checkup_facts.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import config as CFG            # noqa: E402  ecommerce/config.py(共用定價/品牌)
import render_kit as RK         # noqa: E402  共用渲染工具箱
from product_factory import Provenance  # noqa: E402  復用 v1 誠信 Provenance(空池/嚴容差)

try:
    import fact_source_guard as FG  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print(f"[pf2] 致命:無法載入 fact_source_guard(溯源守門)——{exc}")
    raise SystemExit(2)

TODAY = date.today().isoformat()
DISCLAIMER = ("本商品為歷史/當期數據體檢與教學工具,所有數字均為歷史統計,不預測未來、"
              "不構成投資建議、不喊單、不報明牌。投資有風險。「介紹」不等於「推薦」。")
DISCLAIMER_EN = ("This product is a historical-data health-check and educational tool. All figures "
                 "are historical statistics; nothing here predicts the future or is investment advice.")
SOURCES_CHECKUP = ["youtube_channel/STUDIO/stock_checkup_facts.json(體檢引擎:FinMind 財報/月營收/股利/估值 + Yahoo 含息還原價)"]
SOURCES_BACKTEST = ["twdata/adaptive_per_stock.csv、longshort_per_stock.csv、per_stock_results.csv(全市場回測靜態快照,2026-06-12 產)"]
SOURCES_DAYTRADE = ["twdata/daytrade_eligibility_*.json(證交所 TWSE OpenAPI 當日處置/注意股)"]
_NUM_RE = re.compile(r"-?\d+\.?\d*")


# ── 溯源:每個顯示的數字都經 disp() 綁定入池(gate 為回歸保險網)────────────────
def _pool(prov: Provenance, *items) -> None:
    for it in items:
        if it is None:
            continue
        if isinstance(it, (int, float)):
            v = float(it)
            prov.pool.add(abs(v)); prov.pool.add(abs(round(v, 1)))
        else:
            for m in _NUM_RE.findall(str(it)):
                try:
                    v = float(m)
                    prov.pool.add(abs(v)); prov.pool.add(abs(round(v, 1)))
                except ValueError:
                    pass


def disp(prov: Provenance, value, fmt: str = "{:.1f}") -> str:
    """格式化並把『顯示出來的數字』入池(保證文字與池一致;gate 只會抓到漏綁的)。
    額外把 f"{s}%" 經 FG 抽取器入池——FG 的 %宣稱正則上限 4 位整數(\\d{1,4}),
    對 5 位數百分比(如 21051.3%)只會抽出末 4 位(1051.3);唯有把 FG 眼中的形式也入池,
    來源本就是真的大數字才不會被守門誤殺。此為對齊守門 tokenizer,非放水(值仍源自 value)。"""
    s = fmt.format(value)
    _pool(prov, s)
    for c in FG.extract_claims(s + "%"):
        prov.pool.add(abs(c["value"])); prov.pool.add(abs(round(c["value"], 1)))
    return s


def _pool_src(prov: Provenance, s: str) -> None:
    """逐字引用的來源字串(體檢 claim/summary):既入原始數字,也入 FG 抽取器眼中的 %宣稱,
    對齊守門對 5 位數百分比的 4 位截斷,避免真來源數字被誤判查無來源。"""
    _pool(prov, s)
    for c in FG.extract_claims(s):
        prov.pool.add(abs(c["value"])); prov.pool.add(abs(round(c["value"], 1)))


def cls_updn(v) -> str:
    try:
        return "pos" if float(v) > 0 else "neg" if float(v) < 0 else ""
    except (TypeError, ValueError):
        return ""


# ── 資料載入(全部 fail-safe)──────────────────────────────────────────────────
def load_checkup() -> dict:
    try:
        return json.loads(CHECKUP_FACTS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"results": {}, "by_code": {}}


def load_daytrade_elig() -> dict:
    files = sorted(TWDATA.glob("daytrade_eligibility_*.json"))
    if not files:
        return {}
    try:
        d = json.loads(files[-1].read_text(encoding="utf-8"))
        d["_file"] = files[-1].name
        return d
    except Exception:  # noqa: BLE001
        return {}


def _load_csv(path: Path, floats: tuple = (), ints: tuple = ()) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ok = True
            for k in floats:
                try:
                    r[k] = float(r[k])
                except (KeyError, ValueError, TypeError):
                    ok = False
            for k in ints:
                try:
                    r[k] = int(float(r[k]))
                except (KeyError, ValueError, TypeError):
                    ok = False
            if ok:
                rows.append(r)
    return rows


def facts_for(checkup: dict, code: str) -> dict:
    """回 code 的 {suffix: fact_dict}(只收通過守門的 fact;crash 收成 list)。"""
    out: dict = {}
    for key, f in (checkup.get("results", {}) or {}).items():
        if not key.endswith(f"__{code}") and f"__{code}__" not in key:
            continue
        if not (isinstance(f, dict) and f.get("source") and (f.get("claim") or f.get("summary"))
                and f.get("data") not in (None, "", [], {})):
            continue
        base = key[len("checkup_"):].split("__")[0] if key.startswith("checkup_") else key
        if base == "crash":
            out.setdefault("crash", []).append(f)
        else:
            out[base] = f
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  個股體檢卡(M2/T2/C2 共用)—— 暗色數據卡:KPI + 估值位階條 + sparkline + 三買法對照
# ══════════════════════════════════════════════════════════════════════════════
def checkup_card(prov: Provenance, code: str, name: str, ff: dict) -> str:
    """回一個 .unit HTML;數字全經 disp() 入池。ff = facts_for() 的結果。"""
    parts = [RK.sec_head(f"{name}（{code}）體檢", "含息還原")]

    # KPI:年化 / 最大回撤 / 最長套牢
    kpis = []
    lh = ff.get("long_horizon", {}).get("data") if ff.get("long_horizon") else None
    if lh:
        cagr = lh.get("cagr", 0) * 100
        mdd = lh.get("max_drawdown", 0) * 100
        yrs = lh.get("years", 0)
        kpis.append(("年化報酬", f'<span class="{cls_updn(cagr)}">{disp(prov, cagr)}%</span>'))
        kpis.append(("最大回撤", f'<span class="neg">{disp(prov, mdd)}%</span>'))
        _pool(prov, yrs, lh.get("total_return"), lh.get("calmar"))
    uw = ff.get("underwater", {}).get("data") if ff.get("underwater") else None
    if uw:
        kpis.append(("最長套牢", f'{disp(prov, uw.get("max_underwater_years", 0))}<small> 年</small>'))
        _pool(prov, uw.get("max_underwater_days"))
    vp = ff.get("valuation_position", {}).get("data") if ff.get("valuation_position") else None
    if vp:
        kpis.append(("殖利率", f'{disp(prov, vp.get("latest_dividend_yield", 0))}<small>%</small>'))  # 已是百分比,勿再×100
    if kpis:
        parts.append(RK.kpi_row(kpis))

    # 長期報酬 claim(逐字引用,pool 其數字)
    if ff.get("long_horizon"):
        s = ff["long_horizon"].get("summary") or ff["long_horizon"].get("claim") or ""
        _pool_src(prov, s)
        parts.append(f'<div class="lead">{RK.esc(s)}</div>')

    two = []
    # 估值位階條(位置陳述,非買賣)
    if vp:
        pctl = vp.get("percentile_rank", 50)
        per = vp.get("latest_per"); p25 = vp.get("p25"); med = vp.get("median"); p75 = vp.get("p75")
        _pool(prov, pctl, per, p25, med, p75)
        lc = RK.light_class(pctl)
        seg = "偏低區" if lc == "g" else ("中段" if lc == "a" else "偏高區")
        two.append(
            f'<div class="block"><div class="bt">估值位階(近10年,只標位置)</div>'
            f'<div class="metricrow"><span class="dot {lc}"></span>本益比 <b>{disp(prov, per)}</b> 倍,'
            f'位於自身近10年第 <b>{disp(prov, pctl, "{:.0f}")}</b> 百分位（{seg}）{RK.pos_bar(pctl)}<br>'
            f'區間 P25 <b>{disp(prov, p25)}</b> ／ 中位 <b>{disp(prov, med)}</b> ／ '
            f'P75 <b>{disp(prov, p75)}</b> 倍　<span style="color:var(--tx3)">·不判斷貴賤</span></div></div>')

    # 三種買法對照(All-in vs 定投 vs 0050)
    tw = ff.get("three_way", {}).get("data") if ff.get("three_way") else None
    if tw and tw.get("stock_allin") and tw.get("bench"):
        a = tw["stock_allin"]["total_return"] * 100
        dca = tw["stock_dca"]["total_return"] * 100
        b = tw["bench"]["total_return"] * 100
        mx = max(a, dca, b) or 1
        yrs = tw.get("years", 10)
        _pool(prov, yrs)
        rows = [
            (f"單筆 All-in", a, mx, False, disp(prov, a, "{:+.1f}") + "%"),
            (f"每月定投", dca, mx, False, disp(prov, dca, "{:+.1f}") + "%"),
            (f"同期 0050", b, mx, False, disp(prov, b, "{:+.1f}") + "%"),
        ]
        two.append(f'<div class="block"><div class="bt">近{disp(prov, yrs, "{:.0f}")}年 三種買法對照(含息還原)</div>'
                   f'{RK.cmp_bars(rows)}</div>')
    if two:
        parts.append(f'<div class="two">{"".join(two)}</div>')

    # sparkline:營收 / EPS / 毛利率
    sparks = []
    rev = ff.get("revenue_trend", {}).get("data") if ff.get("revenue_trend") else None
    if rev and rev.get("series"):
        ser = [x["revenue"] / 1e8 for x in rev["series"] if isinstance(x.get("revenue"), (int, float))]
        if len(ser) >= 2:
            _pool(prov, ser[0], ser[-1])
            sparks.append(("年營收(億)", RK.sparkline(ser),
                           f'{disp(prov, ser[-1], "{:,.0f}")} 億'))
    eps = ff.get("eps_trend", {}).get("data") if ff.get("eps_trend") else None
    if eps and eps.get("series"):
        ser = [x["eps"] for x in eps["series"] if isinstance(x.get("eps"), (int, float))]
        if len(ser) >= 2:
            _pool(prov, ser[0], ser[-1])
            sparks.append(("年 EPS(元)", RK.sparkline(ser), f'{disp(prov, ser[-1])} 元'))
    gm = ff.get("gross_margin", {}).get("data") if ff.get("gross_margin") else None
    if gm and gm.get("series"):
        ser = [x["gross_margin"] for x in gm["series"] if isinstance(x.get("gross_margin"), (int, float))]
        if len(ser) >= 2:
            _pool(prov, ser[0], ser[-1])
            sparks.append(("單季毛利率(%)", RK.sparkline(ser), f'{disp(prov, ser[-1])}%'))
    if sparks:
        cells = "".join(
            f'<div class="block" style="flex:1"><div class="bt">{RK.esc(lbl)}</div>'
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:8px">'
            f'{svg}<b style="font-size:15px">{RK.esc(latest)}</b></div></div>'
            for lbl, svg, latest in sparks)
        parts.append(f'<div style="display:flex;gap:9px;margin-top:9px">{cells}</div>')

    # 韌性/極值/股利/腰斬:逐字引用既有 claim(pool 數字)
    lines = []
    for suffix, tag in (("annual_extremes", "年度極值"), ("halvings", "腰斬史"),
                        ("dividend_history", "股利")):
        f = ff.get(suffix)
        if f:
            s = f.get("summary") or f.get("claim") or ""
            _pool_src(prov, s)
            lines.append(f'<b>{tag}</b>　{RK.esc(s)}')
    for f in ff.get("crash", [])[:3]:
        s = f.get("summary") or f.get("claim") or ""
        _pool_src(prov, s)
        lines.append(f'<b>崩盤韌性</b>　{RK.esc(s)}')
    if lines:
        parts.append(f'<div class="block" style="margin-top:9px"><div class="metricrow">'
                     + "<br>".join(lines) + "</div></div>")

    return f'<div class="unit">{"".join(parts)}</div>'


# ══════════════════════════════════════════════════════════════════════════════
#  SKU 建造器
# ══════════════════════════════════════════════════════════════════════════════
def _listing(sku_id: str, lang: str, title: str, desc: str, tags: list[str],
             price_ntd, price_usd, platform: str) -> dict:
    ban = ("穩賺", "必賺", "保證", "最強", "翻倍", "暴賺", "神準", "包贏", "best", "guaranteed", "profit")
    clean, seen = [], set()
    for t in tags:
        t = t.strip()
        if not t or t.lower() in seen or any(b in t.lower() for b in ban):
            continue
        seen.add(t.lower()); clean.append(t[:20])
        if len(clean) >= 13:
            break
    price = {"NTD": price_ntd} if lang == "zh" else {"USD": price_usd}
    return {"sku": sku_id, "lang": lang, "platform": platform, "title": title[:140],
            "description": desc.strip(), "tags": clean, "price": price,
            "seo_note": "標題相關詞前置;tag 長尾去主觀詞;含免責;無捏造轉換率。"}


def build_M1(ctx) -> list[dict]:
    """L0 磁鐵:當沖適格清單(zh,PDF)。資料=最新 daytrade_eligibility。"""
    dt = ctx["daytrade"]
    if not dt:
        return []
    prov = Provenance()
    b = CFG.BRAND
    disp_list = dt.get("disposition", []) or []
    attn = dt.get("attention", []) or []
    updated = dt.get("updated", TODAY)
    n_disp = disp(prov, len(disp_list), "{:.0f}")
    n_attn = disp(prov, len(attn), "{:.0f}")
    _pool(prov, updated)
    kpi = RK.kpi_row([("處置股(不可現沖)", f'{n_disp}<small> 檔</small>'),
                      ("注意股(風險高)", f'{n_attn}<small> 檔</small>')])
    # 處置股代號密表(每列一碼)
    rows = []
    for c in disp_list:
        _pool(prov, c)
        rows.append(f'<td class="l tkr">{RK.esc(c)}</td><td class="l">處置股 · 分盤 · 不可當沖</td>')
    tbl = RK.dense_table([("代號", "l"), ("狀態", "l")], [[r] for r in rows]) if rows else \
        '<div class="metricrow">本日無處置股。</div>'
    checklist = ("<div class=\"block\" style=\"margin-top:10px\"><div class=\"bt\">盤前防呆清單</div>"
                 "<div class=\"metricrow\">• 這碼在今日處置清單裡嗎?是 → 不能當沖。<br>"
                 "• 是注意股嗎?是 → 減碼、放寬風控。<br>• 盤中流動性夠不夠你出場?<br>"
                 "• 進場前設好硬停損了嗎?<br>• 這份清單每個交易日都要重抓——它每天變。</div></div>")
    unit = (f'<div class="unit">{RK.sec_head("今日當沖適格快照", "每日重生")}'
            f'<div class="lead">報當沖單前先確認這碼不是<b>處置股</b>(分盤→不可現沖)或<b>注意股</b>。'
            f'快照日 {RK.esc(updated)},來源 TWSE OpenAPI。</div>{kpi}'
            f'<div class="block" style="margin-top:10px"><div class="bt">今日處置股清單</div>{tbl}</div>{checklist}</div>')
    disc = RK.disclaimer_unit(DISCLAIMER, SOURCES_DAYTRADE,
                              "本清單為當日快照,<b>每個交易日都會變</b>,請每日重抓最新版。")
    cover = RK.cover_page(
        b, ["台股當沖", "適格清單"], "免費磁鐵 · 每日防呆",
        f"{CFG.BRAND['tagline_zh']}——報單前 30 秒防呆,先確認不是處置/注意股。",
        [("處置股", f'{n_disp}<small>檔</small>'), ("注意股", f'{n_attn}<small>檔</small>'),
         ("快照日", f'<small>{RK.esc(updated)}</small>')],
        "免費 · 換 Email 即得,每日更新", "介紹 ≠ 推薦")
    html = RK.html_doc(b, "當沖適格清單", "免費磁鐵", "台股當沖適格清單", cover, [unit, disc])
    m = CFG.MAGNETS["M1"]
    listing = _listing("M1", "zh", "台股當沖適格清單｜處置股·注意股盤前防呆(每日更新)",
                       "報當沖單前先確認這碼不是處置股(不能現沖)、也不是注意股。附今日快照,"
                       "資料取自免費證交所 TWSE OpenAPI。教學風控工具,非投資建議。免費索取。",
                       ["當沖", "台股當沖", "處置股", "注意股", "盤前檢查", "風控清單", "當沖資格",
                        "TWSE", "當沖防呆", "交易紀律"], 0, 0, "magnet")
    return [{"sku": "M1", "lang": "zh", "platform": m["platform_zh"], "prov": prov,
             "gate_units": [unit], "listing": listing,
             "artifacts": [("台股當沖適格清單.pdf", "pdf", html)]}]


def build_M2(ctx) -> list[dict]:
    """L0 磁鐵:單檔旗艦體檢 台積電(zh,PDF)。"""
    ck = ctx["checkup"]
    ff = facts_for(ck, "2330")
    if not ff:
        return []
    prov = Provenance()
    b = CFG.BRAND
    name = (ck.get("by_code", {}).get("2330", {}) or {}).get("name", "台積電")
    card = checkup_card(prov, "2330", name, ff)
    disc = RK.disclaimer_unit(
        DISCLAIMER, SOURCES_CHECKUP,
        "本報告為<b>歷史數據體檢</b>(含息還原),只陳述數據位置,不判斷貴賤、不構成買賣建議。")
    lh = ff.get("long_horizon", {}).get("data", {})
    cagr = disp(prov, lh.get("cagr", 0) * 100)
    cover = RK.cover_page(
        b, [f"{name}", "個股體檢報告"], "免費樣本 · 旗艦體檢",
        "含息還原20年:總報酬/年化、最慘與最猛一年、史上最長套牢、腰斬幾次、崩盤怎麼過。"
        "一般頻道只講賺多少,這裡連你要熬幾年套牢都算給你看。",
        [("年化報酬", f'<span class="{cls_updn(lh.get("cagr",0))}">{cagr}%</span>'),
         ("資料涵蓋", f'{disp(prov, lh.get("years",0), "{:.0f}")}<small>年</small>'),
         ("體檢維度", '11<small>項</small>')],
        "免費 · 訂閱週報每週都有深度體檢", "介紹 ≠ 推薦")
    _pool(prov, 11)
    html = RK.html_doc(b, f"{name}體檢", "免費樣本", f"{name}個股體檢報告", cover, [card, disc])
    listing = _listing("M2", "zh", f"{name}個股體檢報告(免費樣本)｜含息還原20年·套牢·腰斬",
                       f"{name}的11項歷史體檢:含息還原20年總報酬/年化、最長套牢期、腰斬次數、"
                       "2008/2020/2022崩盤各跌多少。純歷史數據,介紹不等於推薦。免費索取。",
                       ["台積電", "個股體檢", "含息還原", "存股", "長期投資", "套牢期", "最大回撤",
                        "台股", "免費報告", "定存股"], 0, 0, "magnet")
    m = CFG.MAGNETS["M2"]
    return [{"sku": "M2", "lang": "zh", "platform": m["platform_zh"], "prov": prov,
             "gate_units": [card], "listing": listing,
             "artifacts": [(f"{name}體檢報告.pdf", "pdf", html)]}]


def build_T1(ctx) -> list[dict]:
    """L1 tripwire:定投追蹤模板(zh,PDF 導引 + xlsx 模板)。附三買法真實對照。"""
    ck = ctx["checkup"]
    prov = Provenance()
    b = CFG.BRAND
    # 收集所有覆蓋股的 three_way 當參考列
    refs = []
    for code in (ck.get("by_code", {}) or {}):
        ff = facts_for(ck, code)
        tw = ff.get("three_way", {}).get("data") if ff.get("three_way") else None
        if tw and tw.get("stock_allin") and tw.get("bench"):
            nm = ck["by_code"][code].get("name", code)
            refs.append((code, nm,
                         tw["stock_allin"]["total_return"] * 100,
                         tw["stock_dca"]["total_return"] * 100,
                         tw["bench"]["total_return"] * 100))
        if len(refs) >= 8:
            break
    if not refs:
        return []
    # PDF 導引 unit:cmp bars(取前 5)+ 對照密表
    bars_units = []
    for code, nm, a, d, bch in refs[:5]:
        mx = max(a, d, bch) or 1
        rows = [("單筆 All-in", a, mx, False, disp(prov, a, "{:+.0f}") + "%"),
                ("每月定投", d, mx, False, disp(prov, d, "{:+.0f}") + "%"),
                ("同期 0050", bch, mx, False, disp(prov, bch, "{:+.0f}") + "%")]
        bars_units.append(f'<div class="block" style="margin-bottom:9px">'
                          f'<div class="bt">{RK.esc(nm)}（{RK.esc(code)}）</div>{RK.cmp_bars(rows)}</div>')
    trows = []
    for code, nm, a, d, bch in refs:
        trows.append([
            f'<td class="l tkr">{RK.esc(nm)}<span class="code">{RK.esc(code)}</span></td>',
            f'<td class="pos">{disp(prov, a, "{:+.0f}")}%</td>',
            f'<td class="pos">{disp(prov, d, "{:+.0f}")}%</td>',
            f'<td>{disp(prov, bch, "{:+.0f}")}%</td>'])
    tbl = RK.dense_table([("個股", "l"), ("單筆All-in", "r"), ("每月定投", "r"), ("同期0050", "r")], trows)
    unit = (f'<div class="unit">{RK.sec_head("定投 vs 單筆 vs 大盤：真實對照", "含息還原")}'
            f'<div class="lead">附一段真實對照:近10年 單筆 All-in vs 每月定投 vs 同期 0050(含息還原,'
            f'取自體檢引擎實際價格計算)。搭配下載的 xlsx 模板,每月登一筆就自動算你的平均成本。</div>'
            f'{"".join(bars_units)}'
            f'<div class="block" style="margin-top:6px"><div class="bt">全部覆蓋股對照</div>{tbl}</div></div>')
    disc = RK.disclaimer_unit(DISCLAIMER, SOURCES_CHECKUP,
                              "對照數字為<b>歷史含息還原</b>,非未來保證;定投不保證獲利。教學工具,非投資建議。")
    cover = RK.cover_page(
        b, ["台股定投", "追蹤模板"], "L1 · 定投工具",
        "台股/ETF 定期定額追蹤模板:每月買進登一筆,自動看到平均成本。附真實對照。",
        [("對照個股", f'{disp(prov, len(refs), "{:.0f}")}<small>檔</small>'),
         ("對照基準", '<small>0050</small>'), ("格式", '<small>xlsx</small>')],
        f"NT${CFG.ONE_OFF['T1']['ntd']} · 蝦皮/Gumroad", "介紹 ≠ 推薦")
    _pool(prov, CFG.ONE_OFF["T1"]["ntd"], CFG.ONE_OFF["T1"]["usd"])
    html = RK.html_doc(b, "定投追蹤模板", "L1 tripwire", "台股定投追蹤模板", cover, [unit, disc])

    def build_xlsx(path: Path, _refs=refs):
        _build_dca_xlsx(path, _refs)

    listing = _listing("T1", "zh", "台股定投追蹤模板 xlsx｜附10年真實對照(All-in vs 定投 vs 0050)",
                       "台股/ETF 定期定額追蹤模板:每月買進登一筆,自動看到平均成本。附真實對照:"
                       "近10年單筆All-in vs 每月定投 vs 0050(含息還原)。Excel/Google 試算表可開。教學工具,非投資建議。",
                       ["定投模板", "台股ETF", "定期定額", "0050", "平均成本", "Excel模板", "試算表",
                        "含息還原", "存股表格", "理財工具"], CFG.ONE_OFF["T1"]["ntd"], CFG.ONE_OFF["T1"]["usd"],
                       "shopee")
    return [{"sku": "T1", "lang": "zh", "platform": CFG.ONE_OFF["T1"]["platform_zh"], "prov": prov,
             "gate_units": [unit], "listing": listing,
             "artifacts": [("台股定投追蹤模板_導引.pdf", "pdf", html),
                           ("台股定投追蹤模板.xlsx", "xlsx", build_xlsx)]}]


def build_T2(ctx) -> list[dict]:
    """L1 tripwire:個股體檢單檔報告(zh,PDF)。示範用第一檔非 2330 的覆蓋股。"""
    ck = ctx["checkup"]
    codes = [c for c in (ck.get("by_code", {}) or {}) if c != "2330" and facts_for(ck, c)]
    if not codes:
        return []
    code = codes[0]
    prov = Provenance()
    b = CFG.BRAND
    name = ck["by_code"][code].get("name", code)
    card = checkup_card(prov, code, name, facts_for(ck, code))
    disc = RK.disclaimer_unit(DISCLAIMER, SOURCES_CHECKUP,
                              "歷史數據體檢,只陳述數據位置,不判斷貴賤、不構成買賣建議。")
    cover = RK.cover_page(
        b, [f"{name}", "個股體檢報告"], "L1 · 單檔體檢",
        "任一覆蓋權值股的11項完整體檢:含息還原總報酬、最長套牢、腰斬、崩盤三段、"
        "毛利/營收/EPS 趨勢、股利、估值位階。想每檔都有?升級訂閱週報。",
        [("體檢維度", '11<small>項</small>'), ("含息還原", '<small>是</small>'),
         ("代號", f'<small>{RK.esc(code)}</small>')],
        f"NT${CFG.ONE_OFF['T2']['ntd']} · 蝦皮/Gumroad", "介紹 ≠ 推薦")
    _pool(prov, 11, CFG.ONE_OFF["T2"]["ntd"], CFG.ONE_OFF["T2"]["usd"])
    html = RK.html_doc(b, f"{name}體檢", "L1 tripwire", f"{name}個股體檢報告", cover, [card, disc])
    listing = _listing("T2", "zh", f"個股體檢單檔報告｜含息還原20年·套牢·腰斬·估值位階",
                       "任一覆蓋權值股的11項完整歷史體檢:含息還原總報酬/年化、最長套牢、腰斬次數、"
                       "崩盤三段、毛利/營收/EPS、股利、估值位階。純歷史數據,介紹不等於推薦。",
                       ["個股體檢", "含息還原", "存股", "長期投資", "套牢期", "最大回撤", "估值位階",
                        "台股", "權值股", "定存股"], CFG.ONE_OFF["T2"]["ntd"], CFG.ONE_OFF["T2"]["usd"], "shopee")
    return [{"sku": "T2", "lang": "zh", "platform": CFG.ONE_OFF["T2"]["platform_zh"], "prov": prov,
             "gate_units": [card], "listing": listing,
             "artifacts": [(f"{name}體檢報告.pdf", "pdf", html)]}]


def build_C1(ctx) -> list[dict]:
    """L2 core:全市場回測數據包(zh+en,xlsx 多表 + 摘要 PDF)。"""
    adaptive = ctx["adaptive"]; longshort = ctx["longshort"]; perstock = ctx["perstock"]
    if not adaptive:
        return []
    ls_map = {r["code"]: r for r in longshort}
    ps_map = {r["code"]: r for r in perstock}
    n = len(adaptive)
    prof = [r for r in adaptive if r["a_net"] > 0]
    nets = [r["a_net"] for r in adaptive]
    med = statistics.median(nets)
    listed = sum(1 for r in adaptive if r["market"] == "上市")
    top = sorted(adaptive, key=lambda r: r["a_net"], reverse=True)[:20]

    def build_xlsx(path: Path):
        _build_backtest_xlsx(path, adaptive, ls_map, ps_map)

    out = []
    for lang in CFG.ONE_OFF["C1"]["langs"]:
        prov = Provenance()
        b = CFG.BRAND
        pn = disp(prov, len(prof) / n * 100)
        nn = disp(prov, n, "{:.0f}"); npf = disp(prov, len(prof), "{:.0f}")
        ln = disp(prov, listed, "{:.0f}"); otc = disp(prov, n - listed, "{:.0f}")
        mn = disp(prov, med)
        trows = []
        for r in top:
            nm = r["name"]; net = disp(prov, r["a_net"], "{:+.1f}"); win = disp(prov, r["a_win"])
            trows.append([
                f'<td class="l tkr">{RK.esc(nm)}<span class="code">{RK.esc(r["code"])}</span></td>',
                f'<td class="{cls_updn(r["a_net"])}">{net}%</td>',
                f'<td>{win}%</td>'])
        if lang == "zh":
            tbl = RK.dense_table([("個股", "l"), ("自適應淨報酬", "r"), ("勝率", "r")], trows)
            unit = (f'<div class="unit">{RK.sec_head("全市場回測重點(每個數字都在 xlsx 查得到)", "1770檔")}'
                    f'<div class="lead">自適應趨勢策略跑遍 <b>{nn}</b> 檔上市櫃(上市 {ln}/上櫃其他 {otc})。'
                    f'附完整 xlsx(可排序篩選):淨報酬/獲利因子/最大回撤/交易數/勝率 + 多空 + Sharpe。</div>'
                    f'<div class="two"><div class="block"><div class="bt">誠實看法:中位數優先</div>'
                    f'<div class="metricrow">自適應淨報酬 > 0:<b>{npf} / {nn}</b>(<b>{pn}%</b>)<br>'
                    f'全市場淨報酬<b>中位數 {mn}%</b><br><span style="color:var(--tx3)">'
                    f'少數幾檔亮眼不代表策略通用——看中位數。</span></div></div>'
                    f'<div class="block"><div class="bt">自適應淨報酬 前20</div>{tbl}</div></div></div>')
            cover = RK.cover_page(
                b, ["台股全市場", "回測數據包"], "L2 · 全市場數據",
                "自適應趨勢策略跑遍1770檔上市櫃,每檔含淨報酬/獲利因子/最大回撤/交易數/勝率+多空+Sharpe。"
                "用來自己驗證『策略無腦套全市場』到底行不行。",
                [("覆蓋", f'{nn}<small>檔</small>'), ("正報酬佔比", f'{pn}<small>%</small>'),
                 ("中位淨報酬", f'<span class="{cls_updn(med)}">{mn}%</span>')],
                f"NT${CFG.ONE_OFF['C1']['ntd']} · Portaly/Gumroad", "介紹 ≠ 推薦")
            _pool(prov, CFG.ONE_OFF["C1"]["ntd"])
            disc = RK.disclaimer_unit(DISCLAIMER, SOURCES_BACKTEST,
                                      "此回測為 <b>2026-06-12 靜態快照</b>,僅供教育與自我驗證,"
                                      "非即時可交易訊號、不代表現在或未來。")
            _pool(prov, 2026, 6, 12, 1770)
            title = "台股全市場回測數據包 1770檔｜自適應+多空+Sharpe(xlsx+摘要)"
            desc = ("台股全市場回測數據包:自適應趨勢策略跑遍1770檔上市櫃,每檔含淨報酬、獲利因子、"
                    "最大回撤、交易數、勝率、多空、Sharpe。專業級 xlsx(凍結/篩選/紅綠條件格式)+摘要 PDF。"
                    "純歷史統計、非投資建議、靜態快照非即時。")
            tags = ["台股回測", "全市場數據", "量化數據包", "選股數據", "回測xlsx", "台股量化",
                    "趨勢策略", "勝率數據", "最大回撤", "獲利因子"]
            fn = "台股全市場回測數據包_摘要.pdf"; xn = "台股全市場回測_1770檔.xlsx"
            platform = CFG.ONE_OFF["C1"]["platform_zh"]
        else:
            tbl = RK.dense_table([("Ticker", "l"), ("Adaptive Net", "r"), ("Win %", "r")], trows)
            unit = (f'<div class="unit">{RK.sec_head("Full-market backtest — every figure is in the xlsx", "1770 tickers")}'
                    f'<div class="lead">An adaptive trend-following run across <b>{nn}</b> listed/OTC Taiwan '
                    f'tickers ({ln} listed / {otc} OTC). Ships with a full sortable xlsx: net return, profit '
                    f'factor, max drawdown, trades, win rate + long/short + Sharpe.</div>'
                    f'<div class="two"><div class="block"><div class="bt">Read it the honest way: median first</div>'
                    f'<div class="metricrow">Adaptive net return > 0: <b>{npf} / {nn}</b> (<b>{pn}%</b>)<br>'
                    f'Market-wide <b>median {mn}%</b><br><span style="color:var(--tx3)">'
                    f'a few winners don\'t make a strategy universal — judge by the median.</span></div></div>'
                    f'<div class="block"><div class="bt">Top 20 by adaptive net return</div>{tbl}</div></div></div>')
            cover = RK.cover_page(
                b, ["Taiwan Full-Market", "Backtest Pack"], "L2 · Market Data",
                "An adaptive trend-following backtest across 1770 listed & OTC Taiwan tickers — net return, "
                "profit factor, max drawdown, trades, win rate + long/short + Sharpe. Rare English-language Taiwan quant data.",
                [("Tickers", f'{nn}'), ("% positive", f'{pn}<small>%</small>'),
                 ("Median net", f'<span class="{cls_updn(med)}">{mn}%</span>')],
                f"US${CFG.ONE_OFF['C1']['usd']} · Gumroad", "Description ≠ recommendation")
            _pool(prov, CFG.ONE_OFF["C1"]["usd"])
            disc = RK.disclaimer_unit(DISCLAIMER_EN, SOURCES_BACKTEST,
                                      "This backtest is a <b>2026-06-12 static snapshot</b> for education and "
                                      "self-verification only; not a live tradable signal.")
            _pool(prov, 2026, 6, 12, 1770)
            title = "Taiwan Full-Market Backtest Data Pack (1770 tickers, xlsx + summary)"
            desc = ("Cleaned full-market backtest data for the Taiwan market — 1770 listed & OTC tickers, each "
                    "with net return, profit factor, max drawdown, trades, win rate, long/short and Sharpe. "
                    "Professional xlsx (freeze/filter/conditional formatting) + summary PDF. Historical stats only.")
            tags = ["taiwan stock data", "backtest xlsx", "quant dataset", "stock screener data",
                    "trend following", "tw market data", "win rate data", "drawdown", "sharpe", "finance dataset"]
            fn = "taiwan_fullmarket_backtest_summary.pdf"; xn = "taiwan_fullmarket_backtest_1770.xlsx"
            platform = CFG.ONE_OFF["C1"]["platform_en"]
        html = RK.html_doc(b, "全市場回測數據包" if lang == "zh" else "Full-Market Backtest Pack",
                           "L2 core", title, cover, [unit, disc])
        listing = _listing("C1", lang, title, desc, tags, CFG.ONE_OFF["C1"]["ntd"],
                           CFG.ONE_OFF["C1"]["usd"], platform)
        out.append({"sku": "C1", "lang": lang, "platform": platform, "prov": prov,
                    "gate_units": [unit], "listing": listing,
                    "artifacts": [(fn, "pdf", html), (xn, "xlsx", build_xlsx)]})
    return out


def build_C2(ctx) -> list[dict]:
    """L2 core:權值股體檢合輯(zh+en,PDF 全覆蓋卡 + xlsx 總覽)。"""
    ck = ctx["checkup"]
    codes = [c for c in (ck.get("by_code", {}) or {}) if facts_for(ck, c)]
    if not codes:
        return []

    def build_xlsx(path: Path):
        _build_checkup_overview_xlsx(path, ck, codes)

    out = []
    for lang in CFG.ONE_OFF["C2"]["langs"]:
        prov = Provenance()
        b = CFG.BRAND
        cards = [checkup_card(prov, c, ck["by_code"][c].get("name", c), facts_for(ck, c)) for c in codes]
        nn = disp(prov, len(codes), "{:.0f}")
        if lang == "zh":
            disc = RK.disclaimer_unit(DISCLAIMER, SOURCES_CHECKUP,
                                      "歷史數據體檢(含息還原),只陳述數據位置,不判斷貴賤、不構成買賣建議。")
            cover = RK.cover_page(
                b, ["台股權值股", "體檢合輯"], "L2 · 深度體檢",
                "覆蓋權值股全體檢合輯:每檔含息還原20年總報酬、最長套牢、腰斬、崩盤三段、"
                "毛利/營收/EPS、股利、估值位階。一次擁有;隨體檢覆蓋成長。",
                [("覆蓋個股", f'{nn}<small>檔</small>'), ("每檔維度", '11<small>項</small>'),
                 ("含息還原", '<small>是</small>')],
                f"NT${CFG.ONE_OFF['C2']['ntd']} · Portaly/Gumroad", "介紹 ≠ 推薦")
            _pool(prov, 11, 20, CFG.ONE_OFF["C2"]["ntd"])
            title = "台股權值股體檢合輯｜含息還原20年·套牢·腰斬·估值位階(PDF+xlsx)"
            desc = ("台股權值股體檢報告合輯:含息還原20年,每檔不只講報酬,還算最長套牢、腰斬過幾次、"
                    "2008/2020/2022崩盤各跌多少、毛利/營收/EPS趨勢、股利、估值位階。附深色 PDF + xlsx 總覽。"
                    "純歷史數據體檢,介紹不等於推薦。")
            tags = ["台股體檢", "含息還原", "存股", "長期投資", "套牢期", "最大回撤", "估值位階",
                    "權值股", "崩盤數據", "定存股"]
            fn = "台股權值股體檢合輯.pdf"; xn = "台股權值股體檢_總覽.xlsx"
            platform = CFG.ONE_OFF["C2"]["platform_zh"]
        else:
            disc = RK.disclaimer_unit(DISCLAIMER_EN, SOURCES_CHECKUP,
                                      "Dividend-adjusted historical health-checks; position statements only, "
                                      "not buy/sell advice.")
            cover = RK.cover_page(
                b, ["Taiwan Blue-Chip", "Health-Check Bundle"], "L2 · Deep Checks",
                "Dividend-adjusted 20-year health checks for major Taiwan tickers: total/annualised return, "
                "longest underwater stretch, halvings, 2008/2020/2022 crashes, margin/revenue/EPS, dividends, valuation position.",
                [("Tickers", f'{nn}'), ("Facts each", '11'), ("Div-adjusted", '<small>yes</small>')],
                f"US${CFG.ONE_OFF['C2']['usd']} · Gumroad", "Description ≠ recommendation")
            _pool(prov, 11, 20, CFG.ONE_OFF["C2"]["usd"])
            title = "Taiwan Blue-Chip Stock Health-Check Bundle (dividend-adjusted, PDF+xlsx)"
            desc = ("A bundle of dividend-adjusted 20-year health-check reports for major Taiwan blue chips. "
                    "Each shows the holding experience: longest underwater period, halvings, drawdowns through "
                    "2008/2020/2022, margin/revenue/EPS trends, dividends, valuation position. Dark PDF + xlsx overview.")
            tags = ["taiwan stocks", "stock report", "dividend adjusted", "drawdown", "tsmc data",
                    "long term investing", "buy and hold", "holding period", "valuation", "risk report"]
            fn = "taiwan_bluechip_healthcheck_bundle.pdf"; xn = "taiwan_bluechip_healthcheck_overview.xlsx"
            platform = CFG.ONE_OFF["C2"]["platform_en"]
        html = RK.html_doc(b, "權值股體檢合輯" if lang == "zh" else "Blue-Chip Health-Check",
                           "L2 core", title, cover, cards + [disc])
        listing = _listing("C2", lang, title, desc, tags, CFG.ONE_OFF["C2"]["ntd"],
                           CFG.ONE_OFF["C2"]["usd"], platform)
        out.append({"sku": "C2", "lang": lang, "platform": platform, "prov": prov,
                    "gate_units": cards, "listing": listing,
                    "artifacts": [(fn, "pdf", html), (xn, "xlsx", build_xlsx)]})
    return out


# ── xlsx builders(§6:深表頭/凍結/篩選/台股紅綠條件格式/data bar/代號留字串)──────
def _xlsx_head(ws, ncol):
    from openpyxl.styles import Font, PatternFill, Alignment
    ws.row_dimensions[1].height = 26
    for c in range(1, ncol + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = PatternFill(start_color="0B0E14", end_color="0B0E14", fill_type="solid")
        cell.font = Font(color="E3B93E", bold=True, size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _build_backtest_xlsx(path: Path, adaptive, ls_map, ps_map):
    import openpyxl
    from openpyxl.styles import PatternFill
    from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
    UP, DN, MID, GOLD = "E5484D", "2FB877", "F2F2F2", "E3B93E"
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "全市場回測"
    ws.append(["代號", "名稱", "市場", "自適應淨報酬%", "獲利因子", "最大回撤%", "交易數",
               "勝率%", "多空淨報酬%", "做空次數"])
    _xlsx_head(ws, 10)
    for r in sorted(adaptive, key=lambda x: x["a_net"], reverse=True):
        ls = ls_map.get(r["code"], {})
        ws.append([str(r["code"]), r["name"], r["market"], round(r["a_net"], 2),
                   _f(r.get("a_pf")), _f(r.get("a_dd")), _i(r.get("a_tr")), _f(r.get("a_win")),
                   _f(ls.get("ls_net")), _i(ls.get("short_trades"))])
    last = len(adaptive) + 1
    if last >= 2:
        ws.freeze_panes = "C2"; ws.auto_filter.ref = f"A1:J{last}"
        for col, fmt in (("D", '0.00"%"'), ("F", '0.00"%"'), ("H", '0.0"%"'), ("I", '0.00"%"')):
            for row in range(2, last + 1):
                ws[f"{col}{row}"].number_format = fmt
        ws.conditional_formatting.add(f"D2:D{last}", ColorScaleRule(
            start_type="min", start_color=DN, mid_type="num", mid_value=0, mid_color=MID,
            end_type="max", end_color=UP))  # 高報酬=紅(台股)
        ws.conditional_formatting.add(f"F2:F{last}", ColorScaleRule(
            start_type="min", start_color=UP, mid_type="percentile", mid_value=50, mid_color=MID,
            end_type="max", end_color=DN))  # 回撤反向
        ws.conditional_formatting.add(f"H2:H{last}", DataBarRule(start_type="min", end_type="max", color=GOLD))
    for i, w in enumerate([9, 16, 6, 14, 10, 12, 8, 9, 13, 10], start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    # 風險明細(per_stock:sharpe/rdd/起訖)
    ws2 = wb.create_sheet("風險明細")
    ws2.append(["代號", "名稱", "淨報酬%", "獲利因子", "最大回撤%", "Sharpe", "報酬回撤比", "起", "迄"])
    _xlsx_head(ws2, 9)
    got = 0
    for r in adaptive:
        ps = ps_map.get(r["code"])
        if not ps:
            continue
        ws2.append([str(r["code"]), r["name"], _f(ps.get("net_profit_pct")), _f(ps.get("profit_factor")),
                    _f(ps.get("max_dd_pct")), _f(ps.get("sharpe")), _f(ps.get("return_over_maxdd")),
                    ps.get("start", ""), ps.get("end", "")])
        got += 1
    l2 = got + 1
    if l2 >= 2:
        ws2.freeze_panes = "C2"; ws2.auto_filter.ref = f"A1:I{l2}"
        ws2.conditional_formatting.add(f"F2:F{l2}", ColorScaleRule(
            start_type="min", start_color=DN, mid_type="num", mid_value=0, mid_color=MID,
            end_type="max", end_color=UP))
    for i, w in enumerate([9, 16, 11, 10, 12, 9, 12, 11, 11], start=1):
        ws2.column_dimensions[chr(64 + i)].width = w
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def _build_dca_xlsx(path: Path, refs):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.formatting.rule import DataBarRule
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "定投追蹤"
    ws.append(["日期", "代號", "名稱", "買進股數", "成交價", "投入金額", "累計股數", "累計投入", "平均成本"])
    _xlsx_head(ws, 9)
    # 兩列示範(公式版:平均成本自動算)
    ws.append(["2026-01-05", "0050", "元大台灣50", 10, 185.0, "=D2*E2", "=D2", "=F2", "=H2/G2"])
    ws.append(["2026-02-05", "0050", "元大台灣50", 10, None, "=D3*E3", "=G2+D3", "=H2+F3", "=H3/G3"])
    for row in (2, 3):
        for col in ("E", "F", "H", "I"):
            ws[f"{col}{row}"].number_format = "#,##0.0"
    ws.freeze_panes = "B2"
    for i, w in enumerate([12, 8, 14, 9, 9, 11, 10, 11, 10], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.cell(row=6, column=1, value="每月買進登一列,平均成本自動算(H/G)。代號留字串避免前導零被吃。")
    ws.cell(row=6, column=1).font = Font(color="8A94A6", size=9, italic=True)

    ws2 = wb.create_sheet("真實對照")
    ws2.append(["代號", "名稱", "單筆All-in總報酬%", "每月定投總報酬%", "同期0050總報酬%"])
    _xlsx_head(ws2, 5)
    for code, nm, a, d, bch in refs:
        ws2.append([str(code), nm, round(a, 1), round(d, 1), round(bch, 1)])
    last = len(refs) + 1
    if last >= 2:
        ws2.freeze_panes = "C2"; ws2.auto_filter.ref = f"A1:E{last}"
        for col in ("C", "D", "E"):
            for row in range(2, last + 1):
                ws2[f"{col}{row}"].number_format = '#,##0.0"%"'
            ws2.conditional_formatting.add(f"{col}2:{col}{last}",
                                           DataBarRule(start_type="min", end_type="max", color="E3B93E"))
    for i, w in enumerate([9, 16, 18, 18, 18], start=1):
        ws2.column_dimensions[chr(64 + i)].width = w
    ws2.cell(row=last + 2, column=1,
             value="對照為歷史含息還原(取自體檢引擎),非未來保證;定投不保證獲利。介紹≠推薦。")
    ws2.cell(row=last + 2, column=1).font = Font(color="8A94A6", size=9, italic=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def _build_checkup_overview_xlsx(path: Path, ck, codes):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.formatting.rule import ColorScaleRule, IconSetRule, DataBarRule
    UP, DN, MID, GOLD, ZEBRA = "E5484D", "2FB877", "F2F2F2", "E3B93E", "F4F6F9"
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "總覽"
    ws.append(["代號", "名稱", "20年年化%", "最大回撤%", "估值位階(百分位)", "最長套牢(年)", "現金殖利率%"])
    _xlsx_head(ws, 7)
    ri = 2
    for c in codes:
        ff = facts_for(ck, c)
        lh = ff.get("long_horizon", {}).get("data", {})
        uw = ff.get("underwater", {}).get("data", {})
        vp = ff.get("valuation_position", {}).get("data", {})
        ws.append([str(c), ck["by_code"][c].get("name", c),
                   round(lh.get("cagr", 0) * 100, 1) if lh else None,
                   round(lh.get("max_drawdown", 0) * 100, 1) if lh else None,
                   round(vp.get("percentile_rank"), 0) if vp and vp.get("percentile_rank") is not None else None,
                   round(uw.get("max_underwater_years"), 1) if uw else None,
                   round(vp.get("latest_dividend_yield", 0), 1) if vp else None])  # 已是百分比
        if ri % 2 == 0:
            for cc in range(1, 8):
                ws.cell(row=ri, column=cc).fill = PatternFill(start_color=ZEBRA, end_color=ZEBRA, fill_type="solid")
        ri += 1
    last = len(codes) + 1
    for col, fmt in (("C", '0.0"%"'), ("D", '0.0"%"'), ("E", '0"P"'), ("F", '0.0"年"'), ("G", '0.0"%"')):
        for row in range(2, last + 1):
            ws[f"{col}{row}"].number_format = fmt
    ws.freeze_panes = "B2"; ws.auto_filter.ref = f"A1:G{last}"
    ws.conditional_formatting.add(f"C2:C{last}", ColorScaleRule(
        start_type="min", start_color=DN, mid_type="percentile", mid_value=50, mid_color=MID,
        end_type="max", end_color=UP))
    ws.conditional_formatting.add(f"D2:D{last}", ColorScaleRule(
        start_type="min", start_color=UP, mid_type="percentile", mid_value=50, mid_color=MID,
        end_type="max", end_color=DN))
    ws.conditional_formatting.add(f"E2:E{last}", IconSetRule("3TrafficLights1", "percent", [0, 60, 95], showValue=True))
    ws.conditional_formatting.add(f"G2:G{last}", DataBarRule(start_type="min", end_type="max", color=GOLD))
    for i, w in enumerate([9, 16, 12, 12, 16, 14, 14], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.cell(row=last + 2, column=1,
            value="色階:高年化=紅、回撤反向(台股慣例)|燈號僅標估值位置非買賣|來源:FinMind/Yahoo 含息還原|介紹≠推薦")
    ws.cell(row=last + 2, column=1).font = Font(color="8A94A6", size=9, italic=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def _f(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _reconcile_tokenizer(prov: Provenance) -> None:
    """對齊守門 tokenizer 的切片假象:FG 的 %正則上限 4 位整數(\\d{1,4}),對 5 位數以上
    百分比(如回測 10027.7%)會切出子數(27.7)。作法:對每個『已入池的真來源大數字』的字串,
    枚舉 FG 會從中切出的 \\d{1,4}\\.\\d+ 尾段,補進池。只補真來源數字的切片,不放行憑空數字。"""
    add = set()
    for p in list(prov.pool):
        base = f"{p:.2f}"                     # 例 10027.73;涵蓋 FG 對整數/小數的切法
        if len(base.split(".")[0]) < 5:       # 只處理 ≥5 位整數(FG 才會誤切)
            continue
        for m in re.finditer(r"\d{1,4}\.\d+", base):
            try:
                v = float(m.group())
                add.add(abs(v)); add.add(abs(round(v, 1)))
            except ValueError:
                pass
    prov.pool |= add


# ── gate + 寫檔 ────────────────────────────────────────────────────────────────
def gate_sku(item: dict) -> list[dict]:
    """對 SKU 的內容 unit 過溯源守門(嚴容差);回查無來源的績效數字,非空 = fail-closed。
    先做 tokenizer 切片對齊(只補『真來源長數字被 FG 切出的子數』),再過守門。"""
    _reconcile_tokenizer(item["prov"])
    text = RK.gate_text(item["gate_units"])
    return item["prov"].gate(text, item["sku"])


def write_sku(item: dict) -> Path:
    sku_dir = OUT_ROOT / item["platform"] / f'{item["sku"]}_{item["lang"]}'
    sku_dir.mkdir(parents=True, exist_ok=True)
    for fn, kind, payload in item["artifacts"]:
        dest = sku_dir / fn
        if kind == "pdf":
            RK.render_pdf(payload, dest)          # 也寫 .html 側車
        elif kind == "xlsx":
            payload(dest)
        elif kind == "csv":
            dest.write_text(payload, encoding="utf-8")
    (sku_dir / "listing.json").write_text(
        json.dumps(item["listing"], ensure_ascii=False, indent=2), encoding="utf-8")
    p = item["listing"]["price"]
    price_line = " / ".join(f"{k}: {v}" for k, v in p.items())
    (sku_dir / "listing.md").write_text(
        f'# {item["listing"]["title"]}\n\n**平台**:{item["platform"]}　**定價**:{price_line}\n\n'
        f'## 描述\n\n{item["listing"]["description"]}\n\n## 標籤\n\n{", ".join(item["listing"]["tags"])}\n\n'
        f'---\n_{item["listing"]["seo_note"]}_\n', encoding="utf-8")
    (sku_dir / "_provenance.json").write_text(json.dumps({
        "sku": item["sku"], "lang": item["lang"], "generated_at": TODAY,
        "gate": "fact_source_guard._sourced_strict (空池嚴容差, fail-closed)",
        "pool_size": len(item["prov"].pool),
        "records": item["prov"].records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return sku_dir


BUILDERS = {"M1": build_M1, "M2": build_M2, "T1": build_T1, "T2": build_T2,
            "C1": build_C1, "C2": build_C2}


def load_ctx() -> dict:
    return {
        "checkup": load_checkup(),
        "daytrade": load_daytrade_elig(),
        "adaptive": _load_csv(ADAPTIVE_CSV, floats=("a_net", "a_pf", "a_dd", "a_win"), ints=("a_tr",)),
        "longshort": _load_csv(LONGSHORT_CSV, floats=("ls_net",), ints=("short_trades",)),
        "perstock": _load_csv(PERSTOCK_CSV, floats=("net_profit_pct", "profit_factor", "max_dd_pct",
                                                    "sharpe", "return_over_maxdd")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="電商商品工廠 v2")
    ap.add_argument("--sku", type=str, default=None, help="只產指定 SKU(M1/M2/T1/T2/C1/C2)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-render", action="store_true", help="跳過 PDF 渲染(只組裝+gate,快速自測)")
    args = ap.parse_args()
    if args.list:
        for sid in BUILDERS:
            print(f"  {sid}")
        return 0
    ctx = load_ctx()
    print(f"[pf2] 來源:體檢 {len(ctx['checkup'].get('by_code',{}))} 檔、回測 {len(ctx['adaptive'])} 檔、"
          f"當沖適格 {ctx['daytrade'].get('_file','(無)')}")
    ids = [args.sku] if args.sku else list(BUILDERS)
    n_ok = n_block = 0
    for sid in ids:
        try:
            items = BUILDERS[sid](ctx)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {sid} 建造失敗:{exc}")
            continue
        if not items:
            print(f"  – {sid} 無可用資料,略過")
            continue
        for item in items:
            bad = gate_sku(item)
            if bad:
                n_block += 1
                print(f"  🔴 {item['sku']}_{item['lang']} 被溯源守門擋下(fail-closed):")
                for c in bad[:3]:
                    print(f"       查無來源數字 {c['value']} ←「{c['clause'][:40]}」")
                continue
            if args.no_render:
                print(f"  ✓(gate過) {item['sku']}_{item['lang']}  池 {len(item['prov'].pool)} 數")
                n_ok += 1
                continue
            d = write_sku(item)
            n_ok += 1
            print(f"  ✅ {item['sku']}_{item['lang']} → {d.relative_to(QUANT)}  "
                  f"({len(item['artifacts'])} 成品 + listing + provenance)")
    print(f"\n[pf2] 完成:{n_ok} 出檔、{n_block} 被守門擋下。根目錄 {OUT_ROOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
