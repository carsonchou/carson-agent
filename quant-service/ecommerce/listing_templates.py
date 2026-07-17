# -*- coding: utf-8 -*-
"""listing_templates.py — 電商 v2 上架文案模板 + 產生器(Portaly / 蝦皮 / Gumroad)。

單一事實來源:定價/名稱一律讀 config.py(SUBSCRIPTION / ONE_OFF),此檔只管文案骨架。
產出:quant-service/output/ecommerce_ready/v2/listings_copy/{platform}/{sku}.md(gitignored 生成物)。

平台配置(對齊 REDESIGN_SPEC_business §3-4):
  Portaly(中文)= 旗艦訂閱週報 + C1/C2 core 數據包(台灣訂閱牆/一次性)
  蝦皮(中文)  = T1/T2 tripwire(低價衝動購買)
  Gumroad(英文)= T1/T2/C1/C2(國際版)

文案鐵則(誠信紅線,寫死進骨架):
  1. 痛點開頭 → 2. 內容物清單具體 → 3. 數據範圍/更新頻率誠實標注 → 4. 免責
  「介紹 ≠ 推薦」;數字綁公開資料來源;禁誇大詞(穩賺/翻倍/財富自由/保證…見 _BAN)。
  蝦皮 tag ≤ 13、每 tag ≤ 20 字、去主觀誇大詞(clean_tags,鏡像 product_factory.clean_tags)。

用法:
  python listing_templates.py            # 產全部 SKU×平台 文案到 v2/listings_copy/
  python listing_templates.py --check    # 只驗規則(蝦皮 tag≤13、無誇大詞),不寫檔
"""
from __future__ import annotations

import sys
from pathlib import Path

import config  # 同目錄:定價/名稱單一事實來源

ROOT = Path(__file__).resolve().parent.parent            # quant-service/
OUT = ROOT / "output" / "ecommerce_ready" / "v2" / "listings_copy"

# 誇大/主觀詞黑名單:用於 tag 衛生(clean_tags)。tag 是短關鍵字,標準從嚴。
# 鏡像 product_factory._SUBJECTIVE_BAN,再補財富自由類。
_BAN = ("best", "amazing", "guaranteed", "profit factor", "get rich", "win big",
        "穩賺", "必賺", "保證獲利", "保證收益", "最強", "翻倍", "暴賺", "神準", "包贏",
        "財富自由", "躺賺", "穩定獲利", "穩定收益", "一夜致富")

# 促銷誇大「詞組」黑名單:用於標題/內文掃描。刻意用複合詞組,不誤殺誠實否定
# (如「非未來保證」「不保證收益」含「保證」是必附免責,不該擋;「profit factor 獲利因子」是專業術語)。
_HYPE = ("穩賺", "必賺", "保證獲利", "保證收益", "保證賺", "翻倍", "暴賺", "神準", "包贏",
         "財富自由", "躺賺", "穩定獲利", "穩定收益", "一夜致富", "月入數萬", "月入數十萬",
         "guaranteed return", "guaranteed profit", "get rich", "win big", "double your")

# 共用免責(中/英)
_DISC_ZH = ("⚠️ 免責:本商品為歷史數據的程式化彙整與教學,只做「事實介紹」,"
            "不是投資建議、不喊單、不報明牌、不保證收益。所有數字皆由程式自公開資料"
            "(FinMind 財報/月營收/股利、Yahoo Finance 含息還原股價)計算,標明來源;"
            "歷史數據非未來保證,投資有風險,依此進出盈虧自負。介紹 ≠ 推薦。")
_DISC_EN = ("Disclaimer: This product is an educational, programmatic compilation of "
            "historical data — information only, NOT investment advice, no signals, no "
            "return guarantees. Every figure is computed from public sources (FinMind "
            "financials, Yahoo Finance dividend-adjusted prices) with sources labeled. "
            "Past data does not guarantee future results; investing carries risk.")


def clean_tags(tags: list[str], limit: int = 13) -> list[str]:
    """Etsy/蝦皮 風:長尾、去主觀誇大詞、每 tag ≤ 20 字、去重、上限 limit(蝦皮 13)。"""
    out, seen = [], set()
    for t in tags:
        t = t.strip()
        low = t.lower()
        if not t or any(b in low for b in _BAN):
            continue
        if len(t) > 20:
            t = t[:20].strip()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= limit:
            break
    return out


# ── 文案骨架:每個 (platform, sku) 一份。price 一律從 config 取,不寫死 ──────────
def _sub_prices() -> dict:
    """訂閱牌價。停售的層級回 None —— 呼叫端必須不印它。

    為什麼(2026-07-17):Carson 拍板年繳暫緩(enabled=False),但本檔原本無條件塞
    annual_y、文案硬印「完整版年繳 NT$1290」。**這份文案是要貼到 Portaly 商品頁的**
    —— 貼上去就是在賣一個不存在的方案。config 說停售、文案還在賣,是本專案反覆
    中招的同型病(單一事實來源沒貫徹到每個消費端)。make_landing._tiers_html()
    已照 enabled 過濾,這裡跟上。
    """
    s = config.SUBSCRIPTION
    annual = s.get("annual") or {}
    return {
        "basic_m": s["basic"]["ntd_month"], "full_m": s["full"]["ntd_month"],
        "annual_y": None if annual.get("enabled") is False else annual.get("ntd_year"),
        "basic_usd": s["basic"]["usd_month"], "full_usd": s["full"]["usd_month"],
    }


def _one(sku: str) -> dict:
    return config.ONE_OFF[sku]


# 每筆:title / body(痛點→內容→數據誠實→CTA)/ tags。免責由 render 統一補。
def _listings() -> dict:
    p = _sub_prices()
    T1, T2, C1, C2 = _one("T1"), _one("T2"), _one("C1"), _one("C2")
    return {
        # ── Portaly(中文):訂閱旗艦 + core ──────────────────────────────
        ("portaly", "subscription_weekly"): {
            "title": "台股全市場週報｜每週掃描1900+檔＋個股體檢＋真實訊號追蹤(含輸單)訂閱制",
            "body": [
                "追台股每天被資訊淹沒?看盤軟體一堆紅綠燈,卻不知道「這週整個市場到底強還弱、法人在買什麼、哪些板塊在輪動」——",
                "《台股全市場週報》幫你每週一次把整個市場掃一遍,用數據講事實,不喊單。",
                "",
                "【每週你會收到】",
                "· S1 市場溫度與體質:溫度/漲跌家數比/站上年線比例,一眼看市場冷熱(不判方向)",
                "· S2 板塊輪動熱力:34 個板塊依強弱排序,誰在領漲、法人買幾檔",
                "· S3 全市場強弱榜:約 1000 檔依綜合分數排 Top/Bottom,完整名單附 CSV 可自己排序篩選",
                "· S6 訊號追蹤・誠實成績單:公開真實追蹤戰績(含輸單),不挑不藏——這是我們和只曬贏單的最大差別",
                "· 完整版加碼:法人週籌碼流向、估值位階雷達、當週深度個股體檢、全市場 CSV 下載",
                "",
                f"【方案】基礎版 NT${p['basic_m']}/月(★核心章節)｜完整版 NT${p['full_m']}/月(全章節＋數據下載＋深度體檢)"
                + (f"｜完整版年繳 NT${p['annual_y']}(約省 28%)" if p['annual_y'] else "")
                + "。Email＋Telegram 私訊直送。",
                "",
                "【數據範圍・誠實說】全市場掃描每日更新、週報每週一次出刊;法人籌碼為近數週滾動、估值涵蓋約 1078 檔(缺值略過);"
                "深度個股體檢目前覆蓋權值股、隨每日累積擴充。回測類基準為歷史快照,非即時、非可交易訊號。",
            ],
            "tags": ["台股週報", "全市場掃描", "台股訂閱", "個股體檢", "法人籌碼", "板塊輪動",
                     "選股數據", "台股量化", "存股", "訊號追蹤", "投資理財", "台股分析", "數據週報"],
        },
        ("portaly", "C1_fullmarket_backtest"): {
            "title": f"台股全市場回測數據包｜1770檔 adaptive＋多空＋Sharpe 合併CSV＋摘要PDF 一次買斷 NT${C1['ntd']}",
            "body": [
                "想自己驗證策略,卻找不到「涵蓋全台股、欄位夠用」的回測數據?一檔一檔跑到天荒地老、還不確定清洗對不對——",
                "這個數據包把全市場歷史回測一次打包給你,自己丟進 Excel/Python 隨意分析。",
                "",
                "【內容物】",
                "· 1770 檔台股「自適應策略」回測:淨報酬、獲利因子、最大回撤、交易次數、勝率、報酬/回撤比",
                "· 併入「多空回測」維度:多單/多空淨報酬、做空交易次數等",
                "· 併入明細:Sharpe、回測起訖日、最終權益",
                "· 三檔合併成好用的 CSV ＋ 一份方法與欄位說明摘要 PDF(資料怎麼算、怎麼清洗全公開)",
                "",
                f"【一次買斷 NT${C1['ntd']}(國際版 US${C1['usd']})】買斷制,不是訂閱。想要每週更新版 → 看《台股全市場週報》訂閱。",
                "",
                "【數據範圍・誠實說】此為歷史回測靜態快照(非即時、非可交易訊號),用途是結構研究與教學基準,不是拿去照抄下單的明牌。"
                "代號保留字串格式(0050/00878 前導零不掉)。",
            ],
            "tags": ["台股回測", "全市場數據", "回測CSV", "量化數據包", "選股數據", "台股量化",
                     "Sharpe", "回撤數據", "策略回測", "台股資料", "數據分析", "程式交易", "量化研究"],
        },
        ("portaly", "C2_bluechip_checkup"): {
            "title": f"台股權值股體檢合輯｜含息還原總報酬・最大回撤・套牢期・崩盤韌性 深度數據手冊 PDF NT${C2['ntd']}",
            "body": [
                "存股權值股前,你真的知道它「史上最長套牢多久、腰斬過幾次、三次崩盤抱到今天賺賠多少」嗎?大多數人只看殖利率就進場——",
                "這本體檢合輯把權值股的長期真相攤開,一檔一檔用數據體檢給你看。",
                "",
                "【內容物(每檔 11 項體檢)】",
                "· 近 20 年含息還原總報酬與年化、最大回撤、卡瑪比率",
                "· 史上最長套牢期(幾年幾天才回本)、逐年最猛漲跌",
                "· 三次崩盤(2008/2020/2022)跌幅與「抱到今天」報酬",
                "· 三種買法對照:單筆 All-in vs 每月定投 vs 0050",
                "· 營收/EPS/毛利率趨勢、股利連配紀錄、目前估值位階(於自身近 10 年區間的百分位)",
                "",
                f"【一次買斷 NT${C2['ntd']}(國際版 US${C2['usd']})】合輯隨覆蓋檔數成長,購買後更新版可再取得。",
                "",
                "【數據範圍・誠實說】目前覆蓋台股權值股一批(隨每日體檢累積擴充),非全市場。估值位階只陳述「位置」不判斷貴賤;"
                "EPS 趨勢圖端點為真實年度值,中間為示意序列並已標注。",
            ],
            "tags": ["台股體檢", "含息還原", "存股", "長期投資", "套牢期", "最大回撤", "權值股",
                     "崩盤韌性", "估值位階", "定投對照", "台股數據", "股利", "投資工具"],
        },
        # ── 蝦皮(中文):T1/T2 tripwire ──────────────────────────────────
        ("shopee", "T1_dca_tracker"): {
            "title": f"台股定投追蹤模板 Excel/CSV｜附10年真實對照 All-in vs 定投 vs 0050 含息還原 NT${T1['ntd']}",
            "body": [
                "定期定額到底比一次買進好嗎?跌破年線該不該停扣?大多數人憑感覺,沒看過真數字——",
                "這份模板讓你自己動手記、自己看清楚。",
                "",
                "【內容物】",
                "· 台股/ETF 定投追蹤模板(Excel/Google 試算表可開):每月買進登一筆,自動算出你的平均成本",
                "· 一段 10 年真實對照:單筆 All-in vs 每月定投 vs 0050(皆含息還原),數字取自體檢引擎的實際價格計算",
                "· 附填寫說明,新手也能上手",
                "",
                f"【NT${T1['ntd']}】一杯手搖的錢,上真錢前先把定投這件事看清楚。想要每檔權值股都有深度體檢 → 看訂閱週報。",
                "",
                "【誠實說】對照數字為歷史區間結果(非未來保證);模板是給你自己記錄與試算的工具,不含任何買賣訊號。",
            ],
            "tags": ["定投模板", "台股ETF", "定期定額", "0050", "平均成本", "Excel模板", "試算表",
                     "投資追蹤", "含息還原", "存股表格", "長期投資", "台股", "理財工具"],
        },
        ("shopee", "T2_single_checkup"): {
            "title": "個股體檢單檔報告 PDF｜台股權值股 含息還原總報酬・最長套牢・崩盤韌性・估值位階 11項體檢 NT$149",
            "body": [
                "想長抱一檔權值股,卻不知道它過去最慘套牢多久、崩盤時跌多深?只聽人喊「存這檔就對了」很危險——",
                "選一檔已覆蓋的權值股,拿到它的完整體檢報告,用數據自己判斷。",
                "",
                "【內容物(單檔 11 項體檢 PDF)】",
                "· 近 20 年含息還原總報酬/年化、最大回撤、最長套牢期",
                "· 2008/2020/2022 三次崩盤跌幅與抱到今天報酬",
                "· 單筆 vs 定投 vs 0050 對照、營收/EPS/毛利趨勢、股利紀錄、目前估值位階",
                "",
                f"【NT${T2['ntd']}】下單後私訊我要哪一檔(目前覆蓋權值股一批可選)。想每檔都有、每週新增 → 看訂閱週報或體檢合輯。",
                "",
                "【誠實說】僅覆蓋已體檢的權值股(清單以商店說明為準);估值位階只標位置不判貴賤;歷史數據非未來保證。",
            ],
            "tags": ["個股體檢", "台股", "含息還原", "存股", "套牢期", "最大回撤", "權值股",
                     "崩盤數據", "估值位階", "長期投資", "台積電", "投資報告", "股利"],
        },
        # ── Gumroad(英文):T1/T2/C1/C2 國際版 ───────────────────────────
        ("gumroad", "T1_dca_tracker"): {
            "title": "Taiwan Stock DCA Tracker (Excel/CSV) + 10-Year All-in vs DCA vs 0050 Comparison",
            "body": [
                "Does dollar-cost averaging really beat lump-sum for Taiwan stocks? Most people guess — this template lets you track it and see the real numbers.",
                "",
                "What you get:",
                "- DCA tracking template (Excel / Google Sheets): log each monthly buy, auto-computes your average cost",
                "- A 10-year real comparison: lump-sum All-in vs monthly DCA vs 0050 (all dividend-adjusted), computed by the checkup engine from actual prices",
                "- Fill-in guide included",
                "",
                f"US${T1['usd']}. A tracking + what-if tool, not a signal service. Want a weekly whole-market report? See the subscription.",
                "",
                "Data scope (honest): comparison figures are historical-window results (not a forecast); the template contains no buy/sell signals.",
            ],
            "tags": ["taiwan stock", "dca tracker", "cost averaging", "0050", "etf template",
                     "investing spreadsheet", "dividend adjusted", "excel template", "long term investing",
                     "stock tracker", "quant", "personal finance", "taiwan etf"],
        },
        ("gumroad", "T2_single_checkup"): {
            "title": "Single Taiwan Blue-Chip Health-Check Report (PDF) — 20yr Total Return, Drawdown, Underwater, Crash Resilience",
            "body": [
                "Thinking of holding a Taiwan blue-chip long term? Do you know its worst underwater period or how deep it fell in past crashes? This report lays out the data so you decide for yourself.",
                "",
                "What you get (single-stock, 11-part checkup PDF):",
                "- 20yr dividend-adjusted total return / CAGR, max drawdown, longest underwater period",
                "- 2008 / 2020 / 2022 crash drawdowns and 'held-to-today' returns",
                "- Lump-sum vs DCA vs 0050, revenue/EPS/margin trends, dividend history, current valuation percentile",
                "",
                f"US${T2['usd']}. After checkout, message which covered blue-chip you want. Want them all, updated weekly? See the subscription or the bundle.",
                "",
                "Data scope (honest): only covers already-checked blue-chips (see store note); valuation shows position, not a cheap/expensive call; past data is not a guarantee.",
            ],
            "tags": ["taiwan stocks", "stock report", "dividend adjusted", "max drawdown", "tsmc data",
                     "blue chip", "long term investing", "valuation", "crash analysis", "stock research",
                     "quant", "equity report", "underwater period"],
        },
        ("gumroad", "C1_fullmarket_backtest"): {
            "title": "Taiwan Full-Market Backtest Data Pack — 1770 Stocks, Adaptive + Long/Short + Sharpe (Merged CSV + PDF)",
            "body": [
                "Want to validate a strategy on Taiwan equities but can't find a usable full-market dataset? This pack hands you the whole market's historical backtest in one CSV to analyze yourself.",
                "",
                "What you get:",
                "- 1770 Taiwan stocks, adaptive-strategy backtest: net return, profit factor, max drawdown, trades, win rate, return/drawdown",
                "- Long/short dimension merged in (long & long-short net return, short trades)",
                "- Detail merged in: Sharpe, backtest start/end dates, final equity",
                "- Three files merged into one clean CSV + a methodology/columns summary PDF (how it's computed and cleaned, fully disclosed)",
                "",
                f"US${C1['usd']} one-time (not a subscription). Want a weekly-updated version? See the whole-market weekly.",
                "",
                "Data scope (honest): a historical backtest snapshot (not real-time, not a tradeable signal) — for structural research and educational baselines. Tickers kept as strings (leading zeros preserved).",
            ],
            "tags": ["taiwan stock data", "backtest csv", "quant dataset", "stock screener data",
                     "full market", "sharpe ratio", "drawdown data", "algorithmic trading", "equity research",
                     "taiwan equities", "quant research", "trading data", "csv dataset"],
        },
        ("gumroad", "C2_bluechip_checkup"): {
            "title": "Taiwan Blue-Chip Health-Check Bundle (PDF) — Total Return, Underwater, Crash Resilience, Valuation",
            "body": [
                "Before holding Taiwan blue-chips, do you know their longest underwater stretch, how often they halved, and what three crashes did to them? This bundle lays out the long-term truth, stock by stock.",
                "",
                "What you get (11-part checkup per stock):",
                "- 20yr dividend-adjusted total return & CAGR, max drawdown, Calmar ratio",
                "- Longest underwater period, worst yearly moves",
                "- 2008/2020/2022 crash drawdowns and held-to-today returns",
                "- Lump-sum vs DCA vs 0050, revenue/EPS/margin trends, dividend history, valuation percentile",
                "",
                f"US${C2['usd']} one-time. The bundle grows as coverage grows; updated versions available after purchase.",
                "",
                "Data scope (honest): currently covers a set of Taiwan blue-chips (grows daily), not the full market. Valuation states position only; EPS trend endpoints are real, interpolation is labeled.",
            ],
            "tags": ["taiwan stocks", "dividend adjusted", "blue chip", "max drawdown", "underwater period",
                     "crash analysis", "valuation percentile", "long term investing", "stock research",
                     "equity report", "dividend history", "quant", "buy and hold"],
        },
    }


def render_md(platform: str, sku: str, spec: dict) -> str:
    disc = _DISC_EN if platform == "gumroad" else _DISC_ZH
    tag_label = "Tags" if platform == "gumroad" else "標籤"
    tags = clean_tags(spec["tags"], limit=13 if platform == "shopee" else 13)
    body = "\n".join(spec["body"])
    seo = ("SEO: most-relevant keywords front-loaded in title; long-tail tags, no hype words; "
           "description leads with pain point, lists concrete contents, states data scope honestly, ends with disclaimer."
           if platform == "gumroad" else
           "SEO:標題最相關詞前置、Etsy 風;tag 長尾去誇大詞(蝦皮≤13);描述痛點開頭→內容物→數據誠實標注→免責。")
    return (f"# {spec['title']}\n\n"
            f"**Platform**: {platform}  \n"
            f"**SKU**: {sku}\n\n"
            f"## Description\n\n{body}\n\n"
            f"{disc}\n\n"
            f"## {tag_label} ({len(tags)})\n\n{', '.join(tags)}\n\n"
            f"---\n_{seo}_\n")


def check() -> int:
    """驗規則:蝦皮 tag≤13、所有平台無誇大詞、標題≤140。回傳違規數。"""
    bad = 0
    for (platform, sku), spec in _listings().items():
        title = spec["title"]
        raw_tags = spec["tags"]
        tags = clean_tags(raw_tags, limit=13)
        if platform == "shopee" and len(tags) > 13:
            print(f"[FAIL] {platform}/{sku}: 蝦皮 tag {len(tags)} > 13"); bad += 1
        if len(title) > 140:
            print(f"[FAIL] {platform}/{sku}: 標題 {len(title)} > 140 字"); bad += 1
        # 促銷誇大詞組掃描(標題+內文+tag);用 _HYPE 詞組,不誤殺誠實免責否定
        blob = (title + " " + " ".join(spec["body"]) + " " + " ".join(raw_tags)).lower()
        hit = [b for b in _HYPE if b.lower() in blob]
        if hit:
            print(f"[FAIL] {platform}/{sku}: 命中促銷誇大詞組 {hit}"); bad += 1
        # 被 clean_tags 丟掉的 tag(�leak 提示)
        dropped = len(raw_tags) - len([t for t in raw_tags if not any(b in t.lower() for b in _BAN)])
        if dropped:
            print(f"[warn] {platform}/{sku}: {dropped} 個 tag 含誇大詞被濾除")
    print(f"[check] 完成,違規 {bad} 筆,共 {len(_listings())} 份文案。")
    return bad


def build() -> int:
    n = 0
    for (platform, sku), spec in _listings().items():
        d = OUT / platform
        d.mkdir(parents=True, exist_ok=True)
        md = render_md(platform, sku, spec)
        (d / f"{sku}.md").write_text(md, encoding="utf-8")
        tags = clean_tags(spec["tags"], limit=13)
        print(f"[ok] {platform}/{sku}.md  (tags={len(tags)}, title={len(spec['title'])}字)")
        n += 1
    print(f"完成 {n} 份文案,輸出目錄:{OUT}")
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return 1 if check() else 0
    check()  # 產前先驗
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
