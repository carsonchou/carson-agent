#!/usr/bin/env python
"""台股數據獵手 MCP Server — FastMCP stdio transport

Claude Code 用法：
  在 D:\claude\claude_mcp_settings.json 加入：
  {
    "mcpServers": {
      "taiwan-stock-hunter": {
        "command": "D:\\\\ClawWork\\\\.venv\\\\Scripts\\\\python.exe",
        "args": ["D:\\\\carson-agent\\\\quant-service\\\\data_hunter\\\\mcp_server.py"]
      }
    }
  }
  重啟 Claude Code 後生效。
"""
import json
import sys
import pathlib

ROOT  = pathlib.Path(__file__).parent
QUANT = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(QUANT))

from fastmcp import FastMCP
import query
import realtime_quote
import news as news_mod
import ai_agents

STATE_FILE = ROOT / "state.json"
ZONES_FILE = ROOT / "state_zones.json"

mcp = FastMCP("台股數據獵手")


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {"error": "掃描尚未執行，請先啟動桌面捷徑（台股數據獵手.lnk）"}


def _load_zones() -> dict:
    try:
        return json.loads(ZONES_FILE.read_text("utf-8"))
    except Exception:
        return {"error": "交易專區尚未產出，請先啟動桌面捷徑"}


# ── Tool 1：全市場脈搏 ──────────────────────────────────────────────────────

@mcp.tool()
def market_pulse() -> dict:
    """全市場溫度：大盤閘、市場溫度計、強弱榜 Top5、今日訊號數、波段候選數。
    資料來自已算好的 state.json，毫秒返回。先呼叫這個掌握整體市況。"""
    d = _load_state()
    if "error" in d:
        return d
    gauge_keys = ("temperature", "label", "breadth", "avg_rsi", "adv", "dec", "nh", "nl")
    return {
        "ts":     d.get("ts"),
        "date":   d.get("date"),
        "source": d.get("source"),
        "index":  d.get("index"),
        "gauge": {k: d["gauge"][k] for k in gauge_keys if k in d.get("gauge", {})},
        "strong_top5": d.get("strong", [])[:5],
        "weak_top5":   d.get("weak",   [])[:5],
        "signals": {
            "long_total":  d.get("signals", {}).get("long_total",  0),
            "short_total": d.get("signals", {}).get("short_total", 0),
            "long_top3":   d.get("signals", {}).get("long",  [])[:3],
            "short_top3":  d.get("signals", {}).get("short", [])[:3],
        },
        "wave_candidates": len(d.get("wave_top", [])),
        "sectors": d.get("sectors", [])[:6],
    }


# ── Tool 2：搜尋股票 ───────────────────────────────────────────────────────

@mcp.tool()
def search(q: str) -> list:
    """搜尋台股代號或名稱（模糊比對）。
    q 可以是代號（2330）、名稱（台積電）或關鍵字。回傳 [{code, name, industry}]。"""
    return query.search_stocks(q, limit=10)


# ── Tool 3：個股完整分析 ────────────────────────────────────────────────────

@mcp.tool()
def analyze_stock(code: str, live: bool = False) -> dict:
    """個股完整分析：技術指標、籌碼面、基本面、個股健診、操作訊號。
    code 可輸入代號（2330）或中文名稱（台積電）。
    live=True 使用即時價（較慢，約 6 秒）。"""
    r = query.analyze_stock(code, live=live)
    if not r.get("ok"):
        return r
    keep = [
        "ok", "code", "name", "industry",
        "price", "chg", "rsi", "score", "st",
        "signal", "side", "reason", "stop", "tp1", "tp2",
        "pe", "pb", "dividend_yield", "eps_ttm", "rev_yoy", "gross_margin",
        "foreign_net", "trust_net", "consec_buy_days", "chip_confirm",
        "retail_exit", "smart_money",
        "wave_score", "dual_frame", "drawdown_60",
        "health",
    ]
    return {k: r[k] for k in keep if k in r}


# ── Tool 4：交易專區選股 ────────────────────────────────────────────────────

@mcp.tool()
def zone_picks(style: str = "all") -> dict:
    """交易專區選股，已從全市場 ~1900 檔預先篩選。
    style = daytrade（當沖）/ swing（短線）/ longterm（長線）/ all（全部）。
    回傳各風格 Top10 候選，含具名 setup 和操作卡（進場/停損/目標）。"""
    d = _load_zones()
    if "error" in d:
        return d
    styles = ["daytrade", "swing", "longterm"] if style == "all" else [style]
    result = {}
    for s in styles:
        cands = d.get(s, {}).get("cands", [])[:10]
        result[s] = [
            {k: c[k] for k in ("code", "name", "price", "chg", "zscore", "setups", "play")
             if k in c}
            for c in cands
        ]
    return result


# ── Tool 5：即時五檔報價 ────────────────────────────────────────────────────

@mcp.tool()
def get_quote(code: str) -> dict:
    """個股即時五檔委買委賣 + 成交價（MIS 延遲約 20 秒）。
    code 請輸入純數字代號（如 2330）。"""
    try:
        return realtime_quote.fetch_quote(code)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Tool 6：個股新聞 ───────────────────────────────────────────────────────

@mcp.tool()
def get_news(code: str) -> list:
    """個股最新新聞（Google News RSS，5 分鐘快取）。
    code 可輸入代號或名稱。回傳 [{title, url, pub}]。"""
    try:
        resolved = query._resolve_code(code) or code
        hits = query.search_stocks(resolved, limit=1)
        name = hits[0]["name"] if hits else resolved
        items = news_mod.load_news(name, resolved)
        return [
            {"title": i.get("title"), "url": i.get("url"), "pub": i.get("published")}
            for i in (items or [])[:8]
        ]
    except Exception as e:
        return [{"error": str(e)}]


# ── Tool 7：每日持股研究摘要 ─────────────────────────────────────────────────

@mcp.tool()
def daily_research(codes: list = None) -> dict:
    """每日持股研究摘要（Anthropic 金融 agent 範例的台股版）：對每檔持股講今天發生什麼、
    對它是好是壞、該注意什麼（誠實避雷，不喊買賣不喊目標價）。
    codes 不傳時讀 Carson 的看板持股(dh_portfolio)+自選(dh_watch)；傳 list 則只分析這些代號。
    回傳 {date, ts, market:{tone,one_line,international}, holdings:[...], actions_note}。"""
    return ai_agents.research_agent(codes)


# ── Tool 8：財報/法說 AI 解讀 ────────────────────────────────────────────────

@mcp.tool()
def analyze_financials(code: str = "", text: str = "") -> dict:
    """財報/法說 AI 解讀（Anthropic 金融 agent 範例的台股版第2支）：抓管理層真正想強調什麼、
    3個利多、3個警訊(最重要在前)、對持有這檔的人的實質影響（誠實避雷，不喊買賣不喊目標價）。
    text 有內容時走「貼文模式」(貼財報/法說逐字稿優先分析)；text 空只給 code 時走「自動模式」
    (用最新財報數據自動組摘要分析)。financials 欄位一律為真實數據，非 LLM 生成。"""
    return ai_agents.filing_agent(code, text)


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()  # stdio transport
