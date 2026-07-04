#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""賈維斯 Web 版後端 — 服務 orb 前端 + 把瀏覽器聽到的話接到大腦/電腦操控/嗓音。

瀏覽器負責「耳朵」(Chrome Web Speech API，可靠、免費、免裝模型) 與「畫面」(Three.js orb)；
這支後端負責「大腦＋手腳＋嘴」：
  POST /ask   {text}        → 先試電腦操控(computer.route)，沒命中走分流大腦(ask_brain) → {reply, kind}
  GET  /tts?text=...        → edge-tts 生成磁性男聲 mp3 回傳(瀏覽器播放並讓 orb 跟著脈動)
  GET  /                    → orb 前端頁

跑：python jarvis/web/server.py  → 開 http://127.0.0.1:8788
能力 = 我之前做好的那套(聊天快路/全能腦/看螢幕/開程式/控音量媒體…)，這裡只是換成瀏覽器當門面。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
JARVIS_DIR = HERE.parent
sys.path.insert(0, str(JARVIS_DIR))

# 從 livekit/.env 批次載入所有缺少的 API key
_lk_env = JARVIS_DIR / "livekit" / ".env"
if _lk_env.exists():
    for _ln in _lk_env.read_text(encoding="utf-8").splitlines():
        if "=" in _ln and not _ln.startswith("#"):
            _k, _v = _ln.split("=", 1)
            _k = _k.strip()
            if _k and not os.environ.get(_k):
                os.environ[_k] = _v.strip()

# 從 watch skill .env 補載 GROQ_API_KEY
_watch_env = Path.home() / ".config" / "watch" / ".env"
if _watch_env.exists() and not os.environ.get("GROQ_API_KEY"):
    for _ln in _watch_env.read_text(encoding="utf-8").splitlines():
        if _ln.startswith("GROQ_API_KEY=") and not _ln.startswith("#"):
            os.environ["GROQ_API_KEY"] = _ln.split("=", 1)[1].strip()
            break

import computer  # noqa: E402  手腳：電腦操控 + 語音意圖路由
import jarvis as J  # noqa: E402  大腦：ask_brain（聊天快路 / 全能腦分流）

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8788

# ── 持久對話記憶 ──────────────────────────────────────────────
HISTORY_FILE = JARVIS_DIR / ".jarvis_history.json"

def _load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            rows = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return [(r["u"], r["a"]) for r in rows if isinstance(r, dict)]
        except Exception:
            pass
    return []

def _save_history(h: list) -> None:
    try:
        HISTORY_FILE.write_text(
            json.dumps([{"u": u, "a": a} for u, a in h], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass

HISTORY: list[tuple[str, str]] = _load_history()
_VOICE = os.environ.get("JARVIS_VOICE", "zh-CN-YunjianNeural")
_RATE = os.environ.get("JARVIS_RATE", "-8%")
_PITCH = os.environ.get("JARVIS_PITCH", "-13Hz")

# ── 專案記憶注入（載入全部 .md）──────────────────────────────────
_MEMORY_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "D:/claude")) / "projects" / "D--carson-agent" / "memory"

# ── Brain live-sync: SSE 客戶端 + 檔案監控 ────────────────────
_brain_sse_clients: list[queue.Queue] = []
_brain_sse_lock = threading.Lock()
_brain_hash: str = ""

def _brain_mtime_hash() -> str:
    """掃描所有影響 brain-data 的目錄/檔案，回傳 8 字元 hash。"""
    _ROOT = JARVIS_DIR.parent
    watch_dirs = [
        _MEMORY_DIR,
        _ROOT / "youtube_channel",
        _ROOT / "pionex_crypto",
        _ROOT / "twdata",
        _ROOT / "docs",
        _ROOT / "trading_bot",
        JARVIS_DIR / "plugins" / "loaded",
    ]
    parts: list[str] = []
    for d in watch_dirs:
        try:
            if d and d.exists():
                for f in sorted(d.rglob("*.md")):
                    parts.append(f"{f.stat().st_mtime:.0f}")
                for f in sorted(d.rglob("*.json")):
                    parts.append(f"{f.stat().st_mtime:.0f}")
        except Exception:
            pass
    log = JARVIS_DIR / "self_improve" / "reflection_log.jsonl"
    try:
        parts.append(f"{log.stat().st_mtime:.0f}")
    except Exception:
        pass
    return hashlib.md5("\n".join(parts).encode()).hexdigest()[:8]

def _start_brain_watcher() -> None:
    global _brain_hash
    _brain_hash = _brain_mtime_hash()
    def _watch():
        global _brain_hash
        while True:
            time.sleep(10)
            try:
                h = _brain_mtime_hash()
                if h != _brain_hash:
                    _brain_hash = h
                    print(f"[brain-sync] 檔案異動 → 廣播 SSE (v={h})", flush=True)
                    with _brain_sse_lock:
                        for q in _brain_sse_clients[:]:
                            try:
                                q.put_nowait(h)
                            except Exception:
                                pass
            except Exception:
                pass
    threading.Thread(target=_watch, daemon=True, name="brain-watcher").start()

def _load_project_memory() -> str:
    parts = []
    if _MEMORY_DIR.exists():
        for fpath in sorted(_MEMORY_DIR.glob("*.md")):
            try:
                parts.append(fpath.read_text(encoding="utf-8"))
            except Exception:
                pass
    if not parts:
        return ""
    return "## 你的長期專案記憶\n\n" + "\n\n---\n\n".join(parts)

_PROJECT_MEMORY = _load_project_memory()

# ── 插件系統（熱載入，自我優化寫入插件後無需重啟）──────────────────
sys.path.insert(0, str(JARVIS_DIR))
try:
    from plugins.loader import load_all as _load_plugins, PluginBundle
    _plugins: PluginBundle = _load_plugins()
except Exception as _pe:
    print(f"[warn] 插件載入失敗：{_pe}")
    class PluginBundle:  # type: ignore[no-redef]
        tools: list = []; impls: dict = {}; knowledge: str = ""; mtime: float = 0.0
        extra_apps: dict = {}; extra_sites: dict = {}
    _plugins = PluginBundle()

def _refresh_plugins() -> None:
    """比對 mtime，有新插件就熱載入。"""
    global _plugins
    try:
        plugin_dir = JARVIS_DIR / "plugins" / "loaded"
        if not plugin_dir.exists():
            return
        mtimes = [f.stat().st_mtime for f in plugin_dir.iterdir() if f.is_file()]
        latest = max(mtimes) if mtimes else 0.0
        if latest <= _plugins.mtime:
            return
        from plugins.loader import load_all as _la
        _plugins = _la()
    except Exception:
        pass

# ── 大腦視覺化資料（/brain-data）────────────────────────────────────────
def _build_brain_data() -> dict:
    """匯入全專案知識：記憶 / YouTube / Pionex / 台股 / 文件 / Jarvis 插件 / 對話記錄。"""
    import re as _re
    from collections import Counter as _Counter
    nodes: list[dict] = []
    edges: list[dict] = []
    nid = 0
    eid = 0
    _ROOT = JARVIS_DIR.parent  # D:\carson-agent

    def add(title: str, cat: str, detail: str = "") -> int:
        nonlocal nid
        nodes.append({"id": nid, "title": title[:50], "cat": cat, "detail": detail[:200]})
        nid += 1
        return nid - 1

    def link(a: int, b: int):
        nonlocal eid
        if a != b:
            edges.append({"id": eid, "a": a, "b": b})
            eid += 1

    def md_title(path) -> str:
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                t = line.lstrip("#").strip()
                if t:
                    return t
        except Exception:
            pass
        return path.stem

    # ── 1. MEMORY FILES ────────────────────────────────────────
    mem_hub = add("記憶系統", "記憶", "Jarvis 長期記憶庫")
    cat_map = {"user": "關於我", "feedback": "行為準則", "project": "進行中專案", "reference": "參考資源"}
    mem_ids: list[int] = []
    if _MEMORY_DIR.exists():
        for fp in sorted(_MEMORY_DIR.glob("*.md")):
            if fp.name == "MEMORY.md":
                continue
            try:
                txt = fp.read_text(encoding="utf-8", errors="ignore")
                title = md_title(fp)
                m = _re.search(r"type:\s*(\w+)", txt)
                cat = cat_map.get(m.group(1) if m else "", "記憶")
                i = add(title, cat, txt[:200].replace("\n", " "))
                link(mem_hub, i)
                mem_ids.append(i)
            except Exception:
                pass

    # ── 2. YOUTUBE 頻道 ────────────────────────────────────────
    yt_dir = _ROOT / "youtube_channel"
    yt_hub = add("YouTube 量化阿森", "YouTube", "faceless AI 交易教學頻道")
    yt_ids: list[int] = []
    if yt_dir.exists():
        # 頻道設定文件 (01~06 + README)
        for fp in sorted(yt_dir.glob("0*.md")) + list(yt_dir.glob("README.md")):
            try:
                i = add(md_title(fp), "YouTube", "")
                link(yt_hub, i); yt_ids.append(i)
            except Exception:
                pass
        # 競品分析
        for fp in yt_dir.glob("competitor*.md"):
            try:
                i = add(md_title(fp), "競品研究", "")
                link(yt_hub, i); yt_ids.append(i)
            except Exception:
                pass
        # STUDIO playbooks
        studio = yt_dir / "STUDIO"
        if studio.exists():
            for fp in studio.glob("*.md"):
                try:
                    i = add(md_title(fp), "YouTube", "")
                    link(yt_hub, i); yt_ids.append(i)
                except Exception:
                    pass
        # 影片腳本 output/
        out_dir = yt_dir / "output"
        if out_dir.exists():
            scripts_hub = add("影片腳本庫", "YouTube", "已產出的所有影片腳本")
            link(yt_hub, scripts_hub)
            prev = scripts_hub
            for fp in sorted(out_dir.glob("*.md"))[:40]:
                try:
                    title = fp.stem.replace("_", " ")[:45]
                    i = add(title, "影片腳本", "")
                    link(scripts_hub, i)
                    if prev != scripts_hub:
                        link(prev, i)
                    prev = i
                    yt_ids.append(i)
                except Exception:
                    pass

    # ── 3. PIONEX / 量化交易機器人 ─────────────────────────────
    pionex_dir = _ROOT / "pionex_crypto"
    trade_hub = add("量化交易", "量化交易", "Pionex 自動交易機器人")
    trade_ids: list[int] = []
    if pionex_dir.exists():
        for fp in sorted(pionex_dir.glob("*.py")):
            stem = fp.stem.replace("_", " ")
            i = add(stem, "量化交易", "")
            link(trade_hub, i); trade_ids.append(i)
        for fp in sorted(pionex_dir.glob("*.json")):
            if fp.name.startswith("bot"):
                i = add(fp.stem.replace("_", " "), "量化交易", "")
                link(trade_hub, i); trade_ids.append(i)
    # trading_bot docs
    tbot_dir = _ROOT / "trading_bot"
    if tbot_dir.exists():
        for fp in tbot_dir.glob("*.md"):
            i = add(md_title(fp), "量化交易", "")
            link(trade_hub, i); trade_ids.append(i)

    # ── 4. 台股回測 ───────────────────────────────────────────
    tw_dir = _ROOT / "twdata"
    tw_hub = add("台股回測", "台股", "全市場 1841 支台股策略回測")
    tw_ids: list[int] = []
    if tw_dir.exists():
        for fp in sorted(tw_dir.glob("*.md")):
            i = add(md_title(fp), "台股", "")
            link(tw_hub, i); tw_ids.append(i)

    # ── 5. 文件 / docs ────────────────────────────────────────
    docs_dir = _ROOT / "docs"
    doc_hub = add("專案文件", "文件", "策略說明與工具文件")
    doc_ids: list[int] = []
    if docs_dir.exists():
        for fp in sorted(docs_dir.glob("*.md")):
            i = add(md_title(fp), "文件", "")
            link(doc_hub, i); doc_ids.append(i)

    # ── 6. JARVIS 插件知識 ─────────────────────────────────────
    plugin_dir = JARVIS_DIR / "plugins" / "loaded"
    jarvis_hub = add("Jarvis AI", "AI 工具", "語音助理核心")
    if plugin_dir.exists():
        for fp in plugin_dir.glob("knowledge_*.md"):
            try:
                i = add(md_title(fp), "插件知識", "")
                link(jarvis_hub, i)
            except Exception:
                pass
        for fp in plugin_dir.glob("tool_*.json"):
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
                i = add(d.get("name", fp.stem), "AI 工具", d.get("description", "")[:150])
                link(jarvis_hub, i)
            except Exception:
                pass

    # ── 7. 反思日誌高頻話題 ────────────────────────────────────
    log_path = JARVIS_DIR / "self_improve" / "reflection_log.jsonl"
    kw_hub = add("高頻對話", "對話記錄", "Jarvis 最常被問的話題")
    link(jarvis_hub, kw_hub)
    if log_path.exists():
        kws = ["BTC","比特幣","台股","Pionex","YouTube","Claude",
               "截圖","音量","PowerShell","Python","策略","回測",
               "機器人","定投","網格","影片","腳本","配音"]
        cnt: dict[str, int] = _Counter()
        for ln in log_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[-300:]:
            try:
                entry = json.loads(ln)
                for kw in kws:
                    if kw in entry.get("user_input", ""):
                        cnt[kw] += 1
            except Exception:
                pass
        for topic, c in cnt.most_common(12):
            if c >= 2:
                i = add(f"{topic}", "對話記錄", f"被問過 {c} 次")
                link(kw_hub, i)

    # ── 8. 跨類別橋接 ─────────────────────────────────────────
    # 主要 hub 之間的關係鏈
    hub_links = [
        (yt_hub, trade_hub),    # YouTube 靠 Pionex 返佣變現
        (trade_hub, tw_hub),    # 量化交易 ↔ 台股回測
        (tw_hub, doc_hub),      # 台股回測 → 文件
        (doc_hub, trade_hub),   # 文件 ↔ 交易
        (mem_hub, yt_hub),      # 記憶 ↔ YouTube 策略
        (mem_hub, trade_hub),   # 記憶 ↔ 交易
        (jarvis_hub, mem_hub),  # Jarvis ↔ 記憶
        (jarvis_hub, yt_hub),   # Jarvis ↔ YouTube（自動產片）
        (kw_hub, trade_hub),    # 高頻話題 ↔ 交易
        (kw_hub, yt_hub),       # 高頻話題 ↔ YouTube
    ]
    for a, b in hub_links:
        link(a, b)

    # 記憶節點 → 對應主題 hub（關鍵字比對）
    kw_to_hub = {
        "youtube": yt_hub, "YouTube": yt_hub, "頻道": yt_hub,
        "pionex": trade_hub, "Pionex": trade_hub, "量化": trade_hub, "交易": trade_hub,
        "台股": tw_hub, "回測": tw_hub,
        "jarvis": jarvis_hub, "賈維斯": jarvis_hub,
    }
    for n in nodes[:]:
        if n["cat"] in ("關於我", "行為準則", "進行中專案", "參考資源", "記憶"):
            txt = (n["title"] + " " + n["detail"]).lower()
            for kw, hub in kw_to_hub.items():
                if kw.lower() in txt:
                    link(n["id"], hub)
                    break

    # ── 9. fallback 若完全空 ───────────────────────────────────
    if len(nodes) <= 3:
        for t, c in [("BTC 超級趨勢策略","量化交易"),("派網網格機器人","量化交易"),
                     ("YouTube 量化阿森","YouTube"),("Jarvis 語音助理","AI 工具"),
                     ("台股全市場回測","台股"),("Claude 記憶系統","記憶")]:
            add(t, c)

    return {"nodes": nodes, "edges": edges,
            "generated_at": __import__("datetime").datetime.now().isoformat()}


# ── 反思日誌（供自我優化引擎分析）────────────────────────────────────
_REFLECT_LOG = JARVIS_DIR / "self_improve" / "reflection_log.jsonl"

def _log_reflection(user_input: str, reply: str, kind: str, response_ms: int,
                    tools_called: list | None = None, tool_errors: list | None = None) -> None:
    try:
        import datetime as _dt
        entry = {
            "ts": _dt.datetime.now().isoformat(),
            "user_input": user_input[:200],
            "reply": reply[:300],
            "kind": kind,
            "response_ms": response_ms,
            "tools_called": tools_called or [],
            "tool_errors": tool_errors or [],
            "reply_len": len(reply),
        }
        _REFLECT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _REFLECT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        lines = _REFLECT_LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) > 2000:
            _REFLECT_LOG.write_text("\n".join(lines[-1500:]) + "\n", encoding="utf-8")
    except Exception:
        pass

# ── 金融資料工具（Binance/TWSE/Pionex/Alternative.me，全部免費無 key）────
def _get_crypto_price(symbol: str) -> str:
    """Binance 公開 API，不需任何 key，50ms 延遲。"""
    import requests as _req
    sym = symbol.upper().replace("/", "").replace("-", "")
    if not sym.endswith("USDT") and not sym.endswith("BTC") and not sym.endswith("BUSD"):
        sym = sym + "USDT"
    try:
        r = _req.get(f"https://api.binance.com/api/v3/ticker/24hr", params={"symbol": sym}, timeout=8)
        d = r.json()
        if "code" in d:
            # try without USDT suffix
            sym2 = symbol.upper().replace("/", "").replace("-", "")
            r2 = _req.get(f"https://api.binance.com/api/v3/ticker/24hr", params={"symbol": sym2 + "USDT"}, timeout=8)
            d = r2.json()
        price = float(d["lastPrice"])
        change = float(d["priceChangePercent"])
        high = float(d["highPrice"])
        low = float(d["lowPrice"])
        vol = float(d["volume"])
        return (f"{sym} 報價：{price:,.4f} USDT，"
                f"24h 漲跌 {change:+.2f}%，"
                f"高 {high:,.4f} / 低 {low:,.4f}，"
                f"成交量 {vol:,.0f}")
    except Exception as e:
        return f"查不到 {symbol}：{e}"

def _get_tw_stock(stock_id: str) -> str:
    """TWSE mis 即時報價（盤中 5 秒更新，無需 key），注意限速 3 req/5s。"""
    import requests as _req
    sid = stock_id.strip()
    try:
        r = _req.get(
            "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
            params={"ex_ch": f"tse_{sid}.tw", "json": 1, "delay": 0},
            timeout=8, headers={"Referer": "https://mis.twse.com.tw/"}
        )
        data = r.json().get("msgArray", [{}])[0]
        price = data.get("z", data.get("y", "N/A"))
        name = data.get("n", sid)
        high = data.get("h", "N/A")
        low = data.get("l", "N/A")
        vol = data.get("v", "N/A")
        chg = data.get("ud", "")
        return f"{name}（{sid}）現價 {price} 元，最高 {high}，最低 {low}，成交量 {vol}張"
    except Exception as e:
        # fallback: TWSE OpenAPI 日資料
        try:
            import datetime
            today = datetime.date.today().strftime("%Y%m%d")
            r2 = _req.get(
                "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
                params={"response": "json", "date": today, "stockNo": sid},
                timeout=8
            )
            d2 = r2.json()
            rows = d2.get("data", [])
            if rows:
                last = rows[-1]
                return f"台股 {sid} 最新日收盤：{last[6]} 元（{last[0]}）"
        except Exception:
            pass
        return f"查不到台股 {sid}：{e}"

def _get_market_overview() -> str:
    """BTC 主導地位 + 恐懼貪婪指數 + 總市值，免費無 key。"""
    import requests as _req
    parts = []
    # Fear & Greed
    try:
        r = _req.get("https://api.alternative.me/fng/", params={"limit": 1}, timeout=8)
        fg = r.json()["data"][0]
        parts.append(f"恐懼貪婪指數 {fg['value']}（{fg['value_classification']}）")
    except Exception:
        pass
    # BTC dominance + total market cap via CoinGecko keyless
    try:
        r2 = _req.get("https://api.coingecko.com/api/v3/global", timeout=10)
        d2 = r2.json()["data"]
        btc_dom = d2["market_cap_percentage"].get("btc", 0)
        total = d2["total_market_cap"].get("usd", 0)
        parts.append(f"BTC 主導率 {btc_dom:.1f}%，總市值 {total/1e12:.2f} 兆美元")
    except Exception:
        pass
    return "；".join(parts) if parts else "市場數據暫時無法取得"

# ── Jarvis 工具定義 ──────────────────────────────────────────────
_JARVIS_TOOLS = [
    {
        "name": "web_search",
        "description": (
            "搜尋網路取得最新資訊。呼叫時機：一般新聞/文章/不確定的事實/需要多個來源的資訊。"
            "不要呼叫：加密貨幣即時報價（用 get_crypto_price）、台股（用 get_tw_stock）、市場概況（用 get_market_overview）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜尋關鍵字（中英文均可）"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_crypto_price",
        "description": (
            "查加密貨幣即時報價（Binance 公開 API，毫秒級更新）。"
            "呼叫時機：老闆問任何幣的現價、漲跌、高低點。"
            "範例：BTC、ETH、SOL、BNB、XRP、DOGE、PEPE 等。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "幣種代號，如 BTC、ETHUSDT、SOL"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_tw_stock",
        "description": (
            "查台灣股票即時報價（TWSE，盤中每5秒更新）。"
            "呼叫時機：老闆問台股股價，如台積電、鴻海、大盤等。"
            "傳入股票代號，如 2330（台積電）、2317（鴻海）、0050（台灣50）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"stock_id": {"type": "string", "description": "台股代號，如 2330"}},
            "required": ["stock_id"],
        },
    },
    {
        "name": "get_market_overview",
        "description": (
            "取得加密市場總覽：BTC 主導率、總市值、恐懼貪婪指數。"
            "呼叫時機：老闆問整體市場狀況、BTC 佔比、市場情緒。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_powershell",
        "description": (
            "在老闆的 Windows 11 電腦上執行 PowerShell。"
            "呼叫時機：開程式、讀寫檔案、查系統、跑腳本、做任何電腦動作。"
            "不要呼叫：一般聊天或只是查資料。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell 命令"},
                "reason": {"type": "string", "description": "一句口語說明（給老闆聽的）"},
            },
            "required": ["command", "reason"],
        },
    },
    {
        "name": "open_url",
        "description": "在瀏覽器開啟網址。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整網址"},
                "label": {"type": "string", "description": "口語描述（念給老闆聽）"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "self_optimize",
        "description": (
            "分析我自己的對話日誌，找出弱點，生成程式碼補丁自我改進，然後重啟。"
            "呼叫時機：老闆說「去優化自己」「自我改善」「學習一下」「你去進化」，"
            "或者我自己判斷剛才連續出錯需要修正自身邏輯。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "為什麼現在觸發優化（一句話說明）"},
            },
            "required": [],
        },
    },
    {
        "name": "show_self_history",
        "description": (
            "查看我自我優化的歷史記錄——改了哪些東西、什麼時候改的。"
            "呼叫時機：老闆問「你之前優化了什麼」「改過什麼」。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _firecrawl_search(query: str) -> str:
    """Firecrawl 搜尋，fallback DuckDuckGo。"""
    import requests as _req
    fc_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if fc_key:
        try:
            r = _req.post(
                "https://api.firecrawl.dev/v1/search",
                headers={"Authorization": f"Bearer {fc_key}", "Content-Type": "application/json"},
                json={"query": query, "limit": 4},
                timeout=15,
            )
            items = (r.json().get("data") or [])[:4]
            snippets = []
            for item in items:
                title = item.get("title", "")
                desc = item.get("description", "")
                url = item.get("url", "")
                body = (item.get("markdown") or item.get("content") or "")[:400]
                line = f"【{title}】{desc or body}"
                if line.strip("【】"):
                    snippets.append(line)
            return "\n\n".join(snippets) if snippets else "搜尋無結果"
        except Exception as e:
            pass
    # DuckDuckGo fallback
    try:
        r = _req.get("https://api.duckduckgo.com/",
                     params={"q": query, "format": "json", "no_html": 1}, timeout=8)
        d = r.json()
        result = d.get("AbstractText") or d.get("Answer") or ""
        if not result and d.get("RelatedTopics"):
            result = (d["RelatedTopics"][0] or {}).get("Text", "")
        return result or "搜尋無結果"
    except Exception as e:
        return f"搜尋失敗：{e}"


import threading as _threading
_tl = _threading.local()

def _exec_tool(name: str, inp: dict) -> str:
    """執行 Jarvis tool call，回傳結果字串（同時追蹤 tools_called / tool_errors）。"""
    if not hasattr(_tl, "tools_called"):
        _tl.tools_called = []
        _tl.tool_errors = []
    _tl.tools_called.append(name)

    try:
        result = _exec_tool_impl(name, inp)
    except Exception as e:
        err = f"{name}:{e}"
        _tl.tool_errors.append(err)
        return f"工具執行失敗：{e}"

    if result.startswith("工具執行失敗") or result.startswith("查不到") or result.startswith("出錯"):
        _tl.tool_errors.append(f"{name}:{result[:60]}")
    return result


def _exec_tool_impl(name: str, inp: dict) -> str:
    if name == "web_search":
        return _firecrawl_search(inp.get("query", ""))
    if name == "get_crypto_price":
        return _get_crypto_price(inp.get("symbol", "BTC"))
    if name == "get_tw_stock":
        return _get_tw_stock(inp.get("stock_id", "2330"))
    if name == "get_market_overview":
        return _get_market_overview()
    if name == "run_powershell":
        try:
            out = computer.run_ps(inp.get("command", ""))
            return out or "（執行完畢，無輸出）"
        except Exception as e:
            return f"執行出錯：{e}"
    if name == "open_url":
        import webbrowser
        url = inp.get("url", "")
        if url:
            webbrowser.open(url)
        return f"已開啟 {inp.get('label', url)}"
    if name == "self_optimize":
        try:
            sys.path.insert(0, str(JARVIS_DIR))
            from self_improve import optimizer as _opt
            result = _opt.run_cycle(auto_restart=True, min_logs=3)
            return result
        except Exception as e:
            return f"自我優化失敗：{e}"
    if name == "show_self_history":
        try:
            sys.path.insert(0, str(JARVIS_DIR))
            from self_improve import optimizer as _opt
            return _opt.history_summary()
        except Exception as e:
            return f"讀取歷程失敗：{e}"
    # 插件工具實作（自我優化寫入的 impl_*.py）
    if name in _plugins.impls:
        try:
            return str(_plugins.impls[name](inp))
        except Exception as e:
            return f"插件工具 {name} 失敗：{e}"
    return f"未知工具：{name}"


def _web_fast_ask(text: str, history: list) -> str:
    """Anthropic API — adaptive thinking + prompt caching + 並行 tool 執行。"""
    import datetime
    import requests as _req
    from concurrent.futures import ThreadPoolExecutor, as_completed

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return "缺少 ANTHROPIC_API_KEY"
    now = datetime.datetime.now()
    wk = "一二三四五六日"[now.weekday()]

    # 熱載入插件（無需重啟）
    _refresh_plugins()
    extra_knowledge = _plugins.knowledge

    # ── 系統 prompt：穩定內容加 cache_control，省 90% token ──
    system_prompt = [
        {
            "type": "text",
            "text": (
                J.PERSONA
                + ("\n\n" + _PROJECT_MEMORY if _PROJECT_MEMORY else "")
                + ("\n\n## 自我進化補充知識\n\n" + extra_knowledge if extra_knowledge else "")
                + "\n\n你有三個工具：\n"
                  "• web_search — 呼叫時機：需要即時資訊（幣價/股價/新聞/天氣/不確定的事實）。不要呼叫：一般常識問答。\n"
                  "• run_powershell — 呼叫時機：需要開程式、讀寫檔案、查系統、跑腳本、做任何 computer.route 沒接住的電腦動作。\n"
                  "• open_url — 呼叫時機：老闆要求開特定網站。\n"
                  "鐵則：需要做事就直接呼叫工具，不要光說不練。做完簡短口語回報。"
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"現在時間：{now.year}年{now.month}月{now.day}日 星期{wk} {now.hour}點{now.minute}分。",
        },
    ]

    # 合併插件工具（動態擴充工具集）
    all_tools = _JARVIS_TOOLS + _plugins.tools

    msgs: list = []
    for u, a in history[-16:]:
        msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": text})

    model = os.environ.get("JARVIS_SMART_MODEL", "claude-opus-4-8")

    for _turn in range(5):
        try:
            r = _req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "prompt-caching-2024-07-31",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1200,
                    "thinking": {"type": "adaptive"},  # 自動決定是否深度推理
                    "tools": all_tools,
                    "system": system_prompt,
                    "messages": msgs,
                },
                timeout=60,
            )
            data = r.json()
        except Exception as e:
            return f"出錯：{e}"

        content = data.get("content") or []
        stop_reason = data.get("stop_reason", "end_turn")

        if stop_reason == "tool_use":
            tool_blocks = [b for b in content if b.get("type") == "tool_use"]
            # 並行執行所有工具（不一個一個等）
            tool_results = [None] * len(tool_blocks)
            with ThreadPoolExecutor(max_workers=max(1, len(tool_blocks))) as ex:
                futures = {
                    ex.submit(_exec_tool, b["name"], b.get("input", {})): i
                    for i, b in enumerate(tool_blocks)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        result_text = future.result()
                    except Exception as e:
                        result_text = f"工具執行失敗：{e}"
                    b = tool_blocks[idx]
                    tool_results[idx] = {
                        "type": "tool_result",
                        "tool_use_id": b["id"],
                        "content": result_text,
                    }
                    print(f"[tool] {b['name']} → {result_text[:80]}", flush=True)
            msgs.append({"role": "assistant", "content": content})
            msgs.append({"role": "user", "content": [r for r in tool_results if r]})
        else:
            # 過濾掉 thinking blocks，只取文字
            parts = [b.get("text", "") for b in content if b.get("type") == "text"]
            return " ".join(parts).strip() or "（無回應）"

    return "處理超時，請再說一次。"


_MD_STRIP = re.compile(r'`+[^`]*`+|`|\*{1,3}([^*]+)\*{1,3}|\*+|_{1,3}([^_]+)_{1,3}|_+|#+\s*')


def _strip_md(text: str) -> str:
    """去掉 markdown（backtick / 粗體 / 標題），TTS 念出來才順。"""
    t = _MD_STRIP.sub(lambda m: (m.group(1) or m.group(2) or ""), text)
    return re.sub(r'\s+', ' ', t).strip()


def think(text: str) -> dict:
    """一句話進來 → 決定怎麼回。先看是不是直接操控電腦，否則交給分流大腦。"""
    import time as _time
    text = (text or "").strip()
    if not text:
        return {"reply": "", "kind": "empty"}
    # 重置 thread-local tool 追蹤
    _tl.tools_called = []
    _tl.tool_errors = []
    t0 = _time.monotonic()

    # 負面反饋偵測：若老闆在更正上一句，補標記到最後一條日誌
    _NEGATIVE = re.compile(r"不對|你沒懂|聽錯|你不對|再說|什麼鬼|你在幹嘛|笨|錯了|不是這個|不是那個")
    _POSITIVE = re.compile(r"^(對|好|搞定|完美|不錯|讚|很好|就是這樣|就這樣|謝謝|棒)[啊喔哦！!。]?$")
    if HISTORY and _NEGATIVE.search(text):
        try:
            lines = _REFLECT_LOG.read_text(encoding="utf-8").splitlines()
            if lines:
                last = json.loads(lines[-1])
                last["negative_feedback"] = True
                lines[-1] = json.dumps(last, ensure_ascii=False)
                _REFLECT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass
    elif HISTORY and _POSITIVE.match(text):
        try:
            lines = _REFLECT_LOG.read_text(encoding="utf-8").splitlines()
            if lines:
                last = json.loads(lines[-1])
                last["positive_feedback"] = True
                lines[-1] = json.dumps(last, ensure_ascii=False)
                _REFLECT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass
    # 1) 直接操控電腦（開程式/音量/媒體/截圖/看螢幕/打字/視窗…）秒做
    try:
        hit = computer.route(text)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] route 出錯：{e!r}", file=sys.stderr)
        hit = None
    if hit:
        ms = int((_time.monotonic() - t0) * 1000)
        _log_reflection(text, hit[0], "action", ms)
        return {"reply": hit[0], "kind": "action"}
    # 2) 全部走帶工具的 agentic brain（搜網 + PowerShell + 全記憶）
    reply = _web_fast_ask(text, HISTORY)
    reply = _strip_md(reply)
    ms = int((_time.monotonic() - t0) * 1000)
    _log_reflection(text, reply, "chat", ms,
                    tools_called=list(getattr(_tl, "tools_called", [])),
                    tool_errors=list(getattr(_tl, "tool_errors", [])))
    HISTORY.append((text, reply))
    del HISTORY[:-20]       # 保留最近 20 輪
    _save_history(HISTORY)
    return {"reply": reply, "kind": "chat"}


def stt_groq(audio_bytes: bytes, content_type: str = "audio/webm") -> str:
    """用 Groq Whisper 將音訊轉文字，回傳識別文字。"""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY 未設定")
    import requests as _req
    ext = "webm" if "webm" in content_type else "wav" if "wav" in content_type else "mp3"
    r = _req.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": (f"audio.{ext}", audio_bytes, content_type)},
        data={"model": "whisper-large-v3-turbo"},  # 不鎖語言，自動偵測中英
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["text"].strip()


def gen_tts(text: str) -> bytes:
    import edge_tts
    out = os.path.join(tempfile.gettempdir(), "jarvis_web_tts.mp3")

    async def _g():
        c = edge_tts.Communicate(text, _VOICE, rate=_RATE, pitch=_PITCH)
        await c.save(out)
    asyncio.run(_g())
    return Path(out).read_bytes()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 安靜
        pass

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?")[0] == "/stt":
            try:
                n = int(self.headers.get("Content-Length", 0))
                audio = self.rfile.read(n)
                ctype = self.headers.get("Content-Type", "audio/webm")
                text = stt_groq(audio, ctype)
                self._send(200, json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"[STT 500] {type(e).__name__}: {e}", flush=True)
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return
        if self.path.split("?")[0] == "/ask":
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) or b"{}"
                data = json.loads(raw.decode("utf-8", errors="replace"))
                res = think(str(data.get("text", "")))
                print(f"🗣  {data.get('text','')!r}  →  [{res['kind']}] {res['reply'][:60]}", flush=True)
                self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"reply": f"後端出錯：{e}", "kind": "error"},
                                           ensure_ascii=False).encode("utf-8"))
            return
        self._send(404, b"{}")

    def _sse_brain(self):
        """SSE 端點：瀏覽器訂閱後，每當記憶/專案檔案異動即推送 update 事件。"""
        q: queue.Queue = queue.Queue()
        with _brain_sse_lock:
            _brain_sse_clients.append(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            # 送當前版本（初次連線）
            self.wfile.write(
                f"data: {json.dumps({'v': _brain_hash})}\n\n".encode()
            )
            self.wfile.flush()
            while True:
                try:
                    h = q.get(timeout=25)
                    self.wfile.write(
                        f"data: {json.dumps({'v': h, 'update': True})}\n\n".encode()
                    )
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _brain_sse_lock:
                try:
                    _brain_sse_clients.remove(q)
                except ValueError:
                    pass

    def _stream_ask(self, text: str):
        """SSE 串流：電腦指令秒回一包；chat 走 Anthropic streaming 邊生成邊送 chunk。"""
        import datetime, requests as _req
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def emit(data: dict):
            try:
                self.wfile.write(f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            except Exception:
                pass

        text = (text or "").strip()
        if not text:
            emit({"done": True}); return

        try:
            hit = computer.route(text)
        except Exception:
            hit = None
        if hit:
            emit({"chunk": hit[0], "kind": "action"})
            emit({"done": True}); return

        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            emit({"chunk": "缺少 ANTHROPIC_API_KEY", "kind": "error"})
            emit({"done": True}); return

        now = datetime.datetime.now()
        wk = "一二三四五六日"[now.weekday()]
        sysp = (J.PERSONA
                + ("\n\n" + _PROJECT_MEMORY if _PROJECT_MEMORY else "")
                + f"\n\n（現在時間：{now.year}年{now.month}月{now.day}日 星期{wk} "
                  f"{now.hour}點{now.minute}分；地點台灣）")
        msgs = []
        for u, a in HISTORY[-6:]:
            msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
        msgs.append({"role": "user", "content": text})

        full_reply = ""
        try:
            r = _req.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": J._FAST_MODEL, "max_tokens": 500, "stream": True,
                      "system": sysp, "messages": msgs},
                stream=True, timeout=30,
            )
            for raw in r.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                    if ev.get("type") == "content_block_delta":
                        chunk = ev.get("delta", {}).get("text", "")
                        if chunk:
                            full_reply += chunk
                            emit({"chunk": chunk})
                except Exception:
                    pass
        except Exception as e:
            emit({"chunk": f"出錯：{e}", "kind": "error"})

        HISTORY.append((text, full_reply))
        del HISTORY[:-8]
        emit({"done": True})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/ask-stream":
            q = parse_qs(urlparse(self.path).query)
            self._stream_ask(q.get("text", [""])[0])
            return
        if path == "/tts":
            q = parse_qs(urlparse(self.path).query)
            text = (q.get("text", [""])[0]).strip()
            if not text:
                self._send(400, b"no text", "text/plain")
                return
            try:
                self._send(200, gen_tts(text), "audio/mpeg")
            except Exception as e:  # noqa: BLE001
                self._send(500, str(e).encode("utf-8"), "text/plain")
            return
        if path == "/config":
            key = os.environ.get("DEEPGRAM_API_KEY", "")
            self._send(200, json.dumps({"deepgram_key": key}, ensure_ascii=False).encode("utf-8"))
            return
        if path in ("/", "/index.html"):
            try:
                self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                self._send(500, str(e).encode("utf-8"), "text/plain")
            return
        if path in ("/brain", "/brain.html"):
            try:
                self._send(200, (HERE / "brain.html").read_bytes(), "text/html; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                self._send(500, str(e).encode("utf-8"), "text/plain")
            return
        if path == "/brain-events":
            self._sse_brain()
            return
        if path == "/brain-data":
            try:
                self._send(200, json.dumps(_build_brain_data(), ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                self._send(500, str(e).encode("utf-8"), "text/plain")
            return
        self._send(404, b"not found", "text/plain")


if __name__ == "__main__":
    import threading, webbrowser
    fp = "全能" if J._FULL_POWER else "安全"
    print(f"賈維斯 Web 版：http://127.0.0.1:{PORT}   模式={fp}   (Ctrl-C 結束)")

    # 啟動自我優化觀察員（背景 daemon thread）
    try:
        sys.path.insert(0, str(JARVIS_DIR))
        from self_improve.watcher import start_watcher
        start_watcher(_REFLECT_LOG, threshold=25)
    except Exception as _e:
        print(f"[warn] watcher 啟動失敗：{_e}")

    _start_brain_watcher()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
