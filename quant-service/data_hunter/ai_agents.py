# -*- coding: utf-8 -*-
"""
ai_agents.py — 台股數據獵手 AI agent 共用地基（Anthropic 金融 agent 範例的台股版）

批1：research_agent 每日持股研究摘要（讀持股→彙整技術/籌碼/基本面/新聞/大盤→LLM 白話摘要）。
批2/3（申報解析、估值模型…）將重用本檔的 ask() / save_state() / load_state()，
地基要維持乾淨可擴充：不要在這裡加任何單一 agent 專屬邏輯以外的耦合。

紅線：禁止喊買賣、禁止目標價（PERSONA + system prompt 雙重約束）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import pathlib
from datetime import datetime

HERE = pathlib.Path(__file__).resolve().parent
_YT_SCRIPTS = HERE.parents[1] / "youtube_channel" / "scripts"
if str(_YT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_YT_SCRIPTS))
import llm  # noqa: E402  共用 LLM 路由（youtube_channel/scripts/llm.py）

PREFS_FILE = HERE / "prefs.json"          # 跨裝置同步 prefs（同 server.py PREFS_FILE）
MARKET_STATE_FILE = HERE / "state.json"   # 全市場掃描快照（scan.py / loop.py 產出）

PERSONA = "你是量化阿森的內部研究助理：只認數據、誠實避雷、警訊優先、不喊單不喊目標價、術語翻白話。"


# ── 簡轉繁安全網（抄 youtube_channel/scripts/produce_batch.py:560 _to_traditional）──
def _to_traditional(d):
    """把字串/list/dict 中的中文轉繁體（OpenCC s2twp）。沒裝 opencc 或轉換出錯就原樣回，絕不拋例外。"""
    try:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
    except Exception:
        return d

    def conv(x):
        if isinstance(x, str):
            return cc.convert(x)
        if isinstance(x, list):
            return [conv(i) for i in x]
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        return x

    try:
        return conv(d)
    except Exception:
        return d


def ask(prompt: str, *, system: str = "", json_mode: bool = True,
        temperature: float = 0.2, max_tokens: int = 2500):
    """組合 system+prompt 呼叫 llm.complete()。

    json_mode=True：回傳 dict；解析失敗回 {"_raw": 原文, "_error": "json parse failed"}（不拋例外）。
    json_mode=False：回傳簡轉繁後的純文字字串。
    低溫(<=0.2) 會自動吃 llm.py 的磁碟快取，同 prompt 免重打。
    """
    full = f"{system.strip()}\n\n{prompt.strip()}" if system.strip() else prompt
    text = llm.complete(full, max_tokens=max_tokens, json_mode=json_mode, temperature=temperature)
    if not json_mode:
        return _to_traditional(text)
    try:
        m = re.search(r"\{.*\}", text, re.S)
        obj = json.loads(m.group(0) if m else text)
        return _to_traditional(obj)
    except Exception:
        return {"_raw": text, "_error": "json parse failed"}


# ── state_<name>.json 原子讀寫（抄 fundamentals.py:86 _atomic_write_json）──
def _state_path(name: str) -> pathlib.Path:
    return HERE / f"state_{name}.json"


def save_state(name: str, obj) -> None:
    path = _state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_state(name: str) -> dict:
    path = _state_path(name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"data": {}, "ts": 0}


def _load_market_state() -> dict:
    try:
        return json.loads(MARKET_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _portfolio_codes(limit: int = 20) -> list[str]:
    """讀 prefs.json 的 dh_portfolio(記帳交易) + dh_watch(自選) 抽出股票代號清單（去重、上限 limit 檔）。

    dh_portfolio/dh_watch 在 prefs.json 裡存的是 JSON 字串（dashboard.html localStorage 存法），
    要先 json.loads 兩層：
      dh_portfolio = {"cash":.., "txns":[{code,side("buy"/"sell"),shares,price,...}], "dividends":[...], "snapshots":[...]}
        持股＝逐筆買加賣減後 shares>0 的 code（不需算加權成本，這裡只要代號清單）。
      dh_watch = [{"code":.., "name":..}, ...]
    """
    prefs = _load_prefs()
    data = prefs.get("data", {}) or {}
    codes: list[str] = []
    seen: set[str] = set()

    def _add(c):
        c = (c or "").strip()
        if c and c not in seen:
            seen.add(c)
            codes.append(c)

    try:
        pf = json.loads(data.get("dh_portfolio") or "{}")
        shares_by_code: dict[str, float] = {}
        for t in (pf.get("txns") or []):
            c = (t.get("code") or "").strip()
            if not c:
                continue
            sh = float(t.get("shares") or 0)
            if t.get("side") == "sell":
                shares_by_code[c] = shares_by_code.get(c, 0.0) - sh
            else:
                shares_by_code[c] = shares_by_code.get(c, 0.0) + sh
        for c, sh in shares_by_code.items():
            if sh > 1e-9:
                _add(c)
    except Exception:
        pass

    try:
        watch = json.loads(data.get("dh_watch") or "[]")
        for w in (watch or []):
            if isinstance(w, dict):
                _add(w.get("code"))
    except Exception:
        pass

    return codes[:limit]


def _dedupe_codes(codes, limit: int = 20) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in (codes or []):
        c = (c or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= limit:
            break
    return out


# ── 批1：每日持股研究摘要 ────────────────────────────────────────────────────
def research_agent(codes=None) -> dict:
    """每日持股研究摘要：讀持股 → 蒐集技術/籌碼/基本面/新聞 + 大盤脈搏 → LLM 白話摘要 → 存檔。

    codes=None 時讀 prefs.json 的 dh_portfolio/dh_watch；傳 list 則直接用（去重、上限 20 檔）。
    持股為空回 {"error":"無持股","holdings":[]} 且照樣可跑（不炸）。
    LLM 失敗/回不合格 JSON 時仍組出合法 schema（today/impact/watch 空字串），價格/漲跌一律用
    query.analyze_stock 的即時真值覆蓋，不讓 LLM 亂編。
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    ts = int(time.time())

    code_list = _portfolio_codes(limit=20) if codes is None else _dedupe_codes(codes, limit=20)

    if not code_list:
        out = {"error": "無持股", "holdings": [], "date": date_str, "ts": ts}
        save_state("research", out)
        return out

    try:
        import query
    except Exception:
        query = None
    try:
        import news
    except Exception:
        news = None

    per_stock = []
    for code in code_list:
        row = {"code": code, "name": code, "price": None, "chg": None, "health": {}}
        a = None
        if query is not None:
            try:
                a = query.analyze_stock(code)
            except Exception:
                a = None
        if a and a.get("ok"):
            row["name"] = a.get("name") or code
            row["price"] = a.get("price")
            row["chg"] = a.get("chg")
            row["health"] = a.get("health") or {}
            row["consec_buy_days"] = a.get("consec_buy_days")
            row["rev_yoy"] = a.get("rev_yoy")
            row["eps_ttm"] = a.get("eps_ttm")

        news_items = []
        if news is not None:
            try:
                news_items = news.load_news(row["name"], code, offline=False, limit=5) or []
            except Exception:
                news_items = []
        row["news"] = news_items
        per_stock.append(row)

    market_state = _load_market_state()
    gauge = market_state.get("gauge", {}) or {}
    strong = market_state.get("strong", []) or []
    weak = market_state.get("weak", []) or []
    sectors = market_state.get("sectors", []) or []

    twse_idx, intl_idx = [], []
    try:
        import realtime_quote
        try:
            twse_idx = realtime_quote.fetch_indices() or []
        except Exception:
            twse_idx = []
        try:
            intl_idx = realtime_quote.fetch_international() or []
        except Exception:
            intl_idx = []
    except Exception:
        pass

    context = _build_context(date_str, gauge, strong, weak, sectors, twse_idx, intl_idx, per_stock)

    system = (
        PERSONA
        + "你在做每日盯盤摘要，對每檔持股講：今天發生什麼、對它是好是壞、我該注意什麼。"
        + "禁止喊買賣、禁止目標價。只輸出 JSON。"
    )
    schema_hint = (
        "請只輸出合格 JSON（不要加任何說明文字/markdown code fence），schema：\n"
        '{"market":{"tone":"偏多/偏空/中性","one_line":"一句話總結大盤","international":"國際盤對台股的影響"},'
        '"holdings":[{"code":"股票代號","today":"今天發生什麼","impact":"對這檔是好是壞",'
        '"watch":"該注意什麼"}, ...每檔持股各一筆],'
        '"actions_note":"整體提醒(不喊買賣不喊目標價)"}'
    )
    prompt = context + "\n\n" + schema_hint

    try:
        llm_out = ask(prompt, system=system, json_mode=True, temperature=0.2, max_tokens=2500)
    except Exception as e:
        llm_out = {"_raw": "", "_error": f"llm failed: {type(e).__name__}: {e}"}

    if not isinstance(llm_out, dict):
        llm_out = {}

    market_llm = llm_out.get("market") or {}
    if not isinstance(market_llm, dict):
        market_llm = {}
    holdings_llm = llm_out.get("holdings") or []
    holdings_by_code: dict[str, dict] = {}
    if isinstance(holdings_llm, list):
        for h in holdings_llm:
            if isinstance(h, dict) and h.get("code"):
                holdings_by_code[str(h["code"])] = h

    holdings_out = []
    for row in per_stock:
        code = row["code"]
        llm_h = holdings_by_code.get(code) or {}
        health = row.get("health") or {}
        holdings_out.append({
            "code": code,
            "name": row.get("name") or code,
            # 價格/漲跌一律用 analyze_stock 的即時真值覆蓋，別讓 LLM 亂編
            "price": row.get("price"),
            "chg_pct": row.get("chg"),
            "grade": health.get("grade") if isinstance(health, dict) else None,
            "today": llm_h.get("today") or "",
            "impact": llm_h.get("impact") or "",
            "watch": llm_h.get("watch") or "",
            "news_ref": [n.get("title") for n in (row.get("news") or [])[:5] if isinstance(n, dict) and n.get("title")],
        })

    out = {
        "date": date_str,
        "ts": ts,
        "market": {
            "tone": market_llm.get("tone") or "中性",
            "one_line": market_llm.get("one_line") or "",
            "international": market_llm.get("international") or "",
        },
        "holdings": holdings_out,
        "actions_note": llm_out.get("actions_note") or "",
    }

    save_state("research", out)
    return out


def _build_context(date_str, gauge, strong, weak, sectors, twse_idx, intl_idx, per_stock) -> str:
    lines = [f"日期：{date_str}"]
    lines.append(
        f"大盤：溫度標籤={gauge.get('label', '—')}({gauge.get('temperature', '—')}) "
        f"廣度={gauge.get('breadth', '—')}% 平均RSI={gauge.get('avg_rsi', '—')}"
    )
    if strong:
        lines.append("強勢股前5：" + "、".join(f"{s.get('name')}({s.get('chg')}%)" for s in strong[:5] if isinstance(s, dict)))
    if weak:
        lines.append("弱勢股前5：" + "、".join(f"{s.get('name')}({s.get('chg')}%)" for s in weak[:5] if isinstance(s, dict)))
    if sectors:
        try:
            top_sec = sorted([s for s in sectors if isinstance(s, dict)],
                              key=lambda s: s.get("avg_chg") or 0, reverse=True)[:3]
        except Exception:
            top_sec = sectors[:3]
        lines.append("強勢板塊：" + "、".join(f"{s.get('name')}({s.get('avg_chg')}%)" for s in top_sec if isinstance(s, dict)))
    if intl_idx:
        lines.append("國際指數：" + "、".join(
            f"{i.get('name')}{i.get('chg_pct', i.get('chg', ''))}%" for i in intl_idx[:6] if isinstance(i, dict)))
    if twse_idx:
        lines.append("台股指數：" + "、".join(
            f"{i.get('name')}{i.get('chg_pct', i.get('chg', ''))}%" for i in twse_idx[:6] if isinstance(i, dict)))

    lines.append("")
    lines.append("持股清單：")
    for row in per_stock:
        health = row.get("health") or {}
        grade = health.get("grade", "—") if isinstance(health, dict) else "—"
        overall = health.get("overall", "—") if isinstance(health, dict) else "—"
        news_titles = "；".join(n.get("title", "") for n in (row.get("news") or [])[:5] if isinstance(n, dict))
        lines.append(
            f"- {row.get('name')}({row.get('code')})｜現價{row.get('price')}｜漲跌{row.get('chg')}%｜"
            f"健診{grade}({overall})｜法人連買{row.get('consec_buy_days', '—')}天｜"
            f"營收年增{row.get('rev_yoy', '—')}%｜近期新聞：{news_titles or '無'}"
        )
    return "\n".join(lines)


# ── 批2：財報/法說 AI 解讀 ────────────────────────────────────────────────────
FILING_TEXT_MAX = 12000


def _build_filing_auto_text(code: str, name: str, fnd: dict, rat: dict) -> str:
    """自動模式（只給代號、沒貼文）：用真實基本面/財務比率組一段數據摘要當 LLM 輸入。"""
    lines = [f"股票：{name or code}（{code}）— 以下為最新財務數據摘要（非逐字稿，供你解讀走勢）："]
    lines.append(
        f"EPS(近四季)={fnd.get('eps_ttm')} 營收年增YoY={fnd.get('rev_yoy')}% "
        f"毛利率={fnd.get('gross_margin')}% 營益率={fnd.get('op_margin')}%"
    )
    lines.append(
        f"流動比={rat.get('current_ratio')} 速動比={rat.get('quick_ratio')} 負債比={rat.get('debt_ratio')}% "
        f"利息保障倍數={rat.get('interest_cover')} 營運現金流={rat.get('op_cf')} 自由現金流FCF={rat.get('fcf')} "
        f"ROE(推估)={rat.get('roe')}%"
    )
    lines.append(
        f"本益比={fnd.get('pe')} 股價淨值比={fnd.get('pb')} 殖利率={fnd.get('dividend_yield')}%"
    )
    return "\n".join(lines)


def filing_agent(code: str = "", text: str = "") -> dict:
    """財報/法說 AI 解讀（Anthropic 金融 agent 範例的台股版第2支）。

    模式判定：text 非空 → 貼文模式(text 為主，貼上的財報/法說逐字稿)；
             text 空且有 code → 自動模式(用 fundamentals 的真實數據摘要當 text)。
    抓：①管理層真正想強調什麼 ②3個利多 ③3個警訊(最重要在前) ④對持有這檔的人的實質影響。
    financials 一律用 fundamentals/ratios 的真值填(不靠 LLM 編)；LLM 缺欄位用 .get 補空。
    全路徑 try/except 不炸；LLM/fundamentals/query 任一失敗都優雅降級，不阻塞。
    """
    code = (code or "").strip()
    text = (text or "").strip()
    ts = int(time.time())

    name = ""
    if code:
        try:
            import query
            resolved = query._resolve_code(code) or code
            code = resolved
            a = query.analyze_stock(code)
            if a and a.get("ok"):
                name = a.get("name") or ""
        except Exception:
            pass

    try:
        import fundamentals
    except Exception:
        fundamentals = None

    fin = {"eps_ttm": None, "rev_yoy": None, "gross_margin": None, "op_margin": None,
           "current_ratio": None, "debt_ratio": None, "fcf": None, "roe": None,
           "ratios_grade": {}}

    mode_auto = (not text) and bool(code)
    if fundamentals is not None and code:
        try:
            fnd = fundamentals.load_fundamentals(code, offline=True) or {}
        except Exception:
            fnd = {}
        try:
            # 自動模式（無貼文，靠這份數據當 LLM 輸入）值得多花一次網路抓最新；
            # 貼文模式只是要真值填 financials 顯示，讀快取即可，別為了顯示逼一次額外抓取。
            rat = fundamentals.load_financial_ratios(code, offline=not mode_auto) or {}
        except Exception:
            rat = {}
        fin.update({
            "eps_ttm": fnd.get("eps_ttm"), "rev_yoy": fnd.get("rev_yoy"),
            "gross_margin": fnd.get("gross_margin"), "op_margin": fnd.get("op_margin"),
            "current_ratio": rat.get("current_ratio"), "debt_ratio": rat.get("debt_ratio"),
            "fcf": rat.get("fcf"), "roe": rat.get("roe"),
            "ratios_grade": rat.get("grade") or {},
        })
        if mode_auto:
            text = _build_filing_auto_text(code, name, fnd, rat)

    if not text:
        out = {"code": code, "name": name, "ts": ts,
               "summary": "", "positives": [], "warnings": [],
               "holder_impact": "", "verdict_line": "缺財報內容，無法分析（請貼文字或給股票代號）",
               "financials": fin}
        save_state(f"filing_{code or 'adhoc'}", out)
        return out

    if len(text) > FILING_TEXT_MAX:
        text = text[:FILING_TEXT_MAX]

    system = (
        PERSONA
        + "你在讀一份財報/法說。抓：①管理層真正想強調什麼 ②3個利多 ③3個警訊(最重要在前) "
        + "④對持有這檔的人的實質影響。用白話，禁喊單、禁目標價。只輸出 JSON。"
    )
    schema_hint = (
        "請只輸出合格 JSON（不要加任何說明文字/markdown code fence），schema：\n"
        '{"summary":"3-4句管理層重點","positives":["利多1","利多2","利多3"],'
        '"warnings":["警訊1","警訊2","警訊3"],"holder_impact":"對持有這檔的人的實質影響(中性敘述)",'
        '"verdict_line":"一句話結論(不含買賣建議/目標價)"}'
    )
    prompt = f"股票：{name or code or '(未指定代號)'}\n\n財報/法說內容：\n{text}\n\n{schema_hint}"

    try:
        llm_out = ask(prompt, system=system, json_mode=True, temperature=0.2, max_tokens=2500)
    except Exception as e:
        llm_out = {"_raw": "", "_error": f"llm failed: {type(e).__name__}: {e}"}
    if not isinstance(llm_out, dict):
        llm_out = {}

    def _list3(key):
        v = llm_out.get(key)
        return [str(x) for x in v][:3] if isinstance(v, list) else []

    out = {
        "code": code, "name": name, "ts": ts,
        "summary": llm_out.get("summary") or "",
        "positives": _list3("positives"),
        "warnings": _list3("warnings"),
        "holder_impact": llm_out.get("holder_impact") or "",
        "verdict_line": llm_out.get("verdict_line") or "",
        "financials": fin,
    }

    save_state(f"filing_{code or 'adhoc'}", out)
    return out


if __name__ == "__main__":
    print(json.dumps(research_agent(), ensure_ascii=False, indent=2))
