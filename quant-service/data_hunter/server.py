# -*- coding: utf-8 -*-
"""
server.py — 數據獵手看板伺服器（純標準庫，無相依）

開 http://127.0.0.1:8899 看深色 HUD 看板。
看板每 30 秒抓 state.json；state.json 由 scan.py / loop.py 在背景更新。

用法：
  python server.py            # 開在 8899
  python server.py 9000       # 自訂埠
  python server.py --scan     # 開站前先即時掃一輪(產出 state.json)
"""
from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
_INDICES_CACHE: dict = {}          # /api/indices 60 秒 module 快取

# SSE 監看的檔案（mtime 一變就推事件給所有連線的裝置）
_SSE_WATCH = {
    "state": HERE / "state.json",
    "prefs": HERE / "prefs.json",
    "daytrade": HERE / "state_daytrade.json",
    "zones": HERE / "state_zones.json",
    "research": HERE / "state_research.json",
    "filing": HERE / "state_filing_adhoc.json",
}
PREFS_FILE = HERE / "prefs.json"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"data": {}, "ts": 0}


def _lan_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"


_LOGIN_HTML = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>量化阿森 · 需要通行碼</title>
<body style="background:#0a0e15;color:#d3dae6;font-family:system-ui;display:flex;height:90vh;align-items:center;justify-content:center">
<form style="text-align:center"><div style="font-size:18px;margin-bottom:14px">量化阿森 · 數據獵手</div>
<input name=key type=password placeholder="通行碼" autofocus style="padding:10px 14px;border-radius:8px;border:1px solid #5a6678;background:#111823;color:#d3dae6;font-size:15px">
<button style="margin-left:8px;padding:10px 16px;border-radius:8px;border:1px solid #5a93bd;background:#5a93bd;color:#0a0e15;font-size:15px">進入</button>
<div style="color:#5a6678;font-size:12px;margin-top:14px">此看板含個人財務資料，需通行碼</div></form></body>"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def _handle_api(self, path: str, qs: dict) -> bool:
        """動態 API：/api/stock、/api/search、/api/analyst。命中回 True(已回應)，否則 False(交還靜態服務)。
        query/analyst 在 handler 內 import(而非模組頂層)，讓查價/分析失敗絕不拖垮靜態看板服務。"""
        if path == "/api/prefs":
            # 全狀態跨裝置同步：讀 prefs.json（庫存/自選/警示/設定…）
            self._send_json({"ok": True, **_load_prefs()})
            return True
        if path == "/api/netinfo":
            # 給前端 QR：區網 IP、埠、是否需要 key、tunnel 公網 URL
            key = os.getenv("DH_ACCESS_KEY", "").strip()
            tun = ""
            try:
                tf = HERE / "tunnel_url.txt"
                if tf.exists():
                    tun = tf.read_text(encoding="utf-8").strip()
            except Exception:
                tun = ""
            self._send_json({"ok": True, "lan_ip": _lan_ip(), "port": self.server.server_address[1],
                             "needs_key": bool(key), "tunnel_url": tun})
            return True
        if path == "/api/qr":
            # 伺服器端產 QR（segno 純 python，離線可跑；缺 segno → 降級回文字）
            data = (qs.get("data", [""])[0]).strip()
            try:
                import segno
                import io
                buf = io.BytesIO()
                segno.make(data, error="m").save(buf, kind="svg", scale=5, dark="#0a0e15", light="#d3dae6", border=2)
                body = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_json({"ok": False, "error": f"QR 產生失敗（可能未裝 segno）：{e}", "data": data}, status=500)
            return True
        if path == "/api/research":
            # 每日持股研究摘要：讀背景 worker（app.py research_worker）或手動觸發產生的 state_research.json
            try:
                import ai_agents
                r = ai_agents.load_state("research")
            except Exception as e:
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
                return True
            self._send_json({"ok": bool(r), **(r or {})})
            return True
        if path == "/api/fin_analyze":
            # 財報透視：讀最近一次 AI 解讀(state_filing_<code or adhoc>.json)；?code= 選填
            code = (qs.get("code", [""])[0] or "").strip()
            try:
                import ai_agents
                r = ai_agents.load_state(f"filing_{code or 'adhoc'}")
            except Exception as e:
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
                return True
            self._send_json({"ok": bool(r), **(r or {})})
            return True

        if path not in ("/api/stock", "/api/search", "/api/analyst", "/api/news",
                        "/api/quote", "/api/indices", "/api/zones", "/api/daytrade"):
            return False
        try:
            import query
        except Exception as e:                       # query 相依缺失 → 只影響 API，不影響看板
            self._send_json({"ok": False, "error": f"query 模組載入失敗：{e}"}, status=500)
            return True

        def _first(key: str) -> str:
            v = qs.get(key)
            return (v[0] if v else "").strip()

        try:
            if path == "/api/search":
                # 前端契約：直接回 JSON 陣列 [{code,name,industry}]；空 q 或出錯回 []（前端好迭代）
                q = _first("q")
                self._send_json(query.search_stocks(q) if q else [])
                return True

            if path == "/api/zones":
                # 交易專區(當沖/短線/長線)：讀盤後/背景產生的快取 zones.json
                try:
                    import zones
                    z = zones.load_zones()
                except Exception:
                    z = None
                self._send_json({"ok": bool(z), **(z or {})})
                return True

            if path == "/api/daytrade":
                # 盤中即時當沖決策：讀背景引擎產生的 state_daytrade.json（純讀檔不即時運算）
                try:
                    import daytrade_live
                    d = daytrade_live.load_daytrade()
                except Exception:
                    d = None
                self._send_json({"ok": bool(d), **(d or {})})
                return True

            if path == "/api/indices":
                # 大盤主要指數群 + 國際指數；60 秒 module 快取(避免每次輪詢重抓 yfinance)
                import time as _t
                global _INDICES_CACHE
                hit = _INDICES_CACHE.get("v")
                if hit and (_t.monotonic() - hit[0]) < 60:
                    self._send_json(hit[1]); return True
                from concurrent.futures import ThreadPoolExecutor
                twse = intl = []
                try:
                    import realtime_quote as _rq
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        ft = ex.submit(_rq.fetch_indices)
                        fi = ex.submit(_rq.fetch_international)
                        try: twse = ft.result(timeout=8.0) or []
                        except Exception: twse = []
                        try: intl = fi.result(timeout=10.0) or []
                        except Exception: intl = []
                except Exception:
                    pass
                payload = {"ok": True, "twse": twse, "intl": intl}
                _INDICES_CACHE["v"] = (_t.monotonic(), payload)
                self._send_json(payload); return True

            if path == "/api/quote":
                # 即時五檔/報價(證交所 MIS，免費約20秒延遲)：?code= 或 ?q=
                from concurrent.futures import ThreadPoolExecutor
                raw = _first("code") or _first("q")
                code = query._resolve_code(raw) or raw
                q = None; intraday = None
                try:
                    import realtime_quote
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        fq = ex.submit(realtime_quote.fetch_quote, code)
                        fi = ex.submit(realtime_quote.fetch_intraday, code)
                        try:
                            q = fq.result(timeout=8.0)
                        except Exception:
                            q = None
                        try:
                            intraday = fi.result(timeout=8.0)   # 分時走勢(慢一點沒關係)
                        except Exception:
                            intraday = None
                except Exception:
                    q = None
                self._send_json({"ok": bool(q), "quote": q, "intraday": intraday})
                return True

            if path == "/api/news":
                # 個股新聞(Google News RSS)：?code=&name=；有界抓取、短快取，抓不到回空陣列
                from concurrent.futures import ThreadPoolExecutor
                raw = _first("code") or _first("q")
                name = _first("name")
                code = query._resolve_code(raw) or raw
                if not name:
                    try:
                        name = query._meta(code)[0]
                    except Exception:
                        name = ""
                try:
                    import news
                    with ThreadPoolExecutor(max_workers=1) as ex:
                        items = ex.submit(news.load_news, name, code, False, 8).result(timeout=8.0)
                except Exception:
                    items = []
                self._send_json({"ok": True, "items": items or []})
                return True

            if path == "/api/analyst":
                # 金融分析團隊四維度：支援 ?code= 或 ?q=(名稱)。名稱先用 query._resolve_code 轉代號，
                # 再交 analyst.analyze_one(內含四維分析+綜合操作策略)。有界執行(~12s)避免慢網卡死。
                from concurrent.futures import ThreadPoolExecutor
                raw = _first("code") or _first("q")
                if not raw:
                    self._send_json({"ok": False, "error": "缺少 code 或 q"}, status=400)
                    return True
                code = query._resolve_code(raw) or raw
                import analyst
                with ThreadPoolExecutor(max_workers=1) as ex:
                    res = ex.submit(analyst.analyze_one, code).result(timeout=12.0)
                if res is None:
                    self._send_json({"ok": False, "error": f"{code} 無法取得資料"}, status=404)
                else:
                    self._send_json({"ok": True, **res}, status=200)
                return True

            # /api/stock：支援 ?code= 或 ?q=(名稱)；live=1 用即時價
            code = _first("code") or _first("q")
            if not code:
                self._send_json({"ok": False, "error": "缺少 code 或 q"}, status=400)
                return True
            live = _first("live") in ("1", "true", "yes")
            res = query.analyze_stock(code, live=live)
            self._send_json(res, status=200 if res.get("ok") else 404)
        except Exception as e:                        # 任意查詢例外都收斂成 JSON，server 不崩
            self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
        return True

    def _handle_stream(self) -> None:
        """SSE 真即時推播：監看 state/prefs/daytrade/zones 的 mtime，一變就推事件。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last: dict = {}
        hb = 0
        try:
            while True:
                for name, p in _SSE_WATCH.items():
                    try:
                        m = int(p.stat().st_mtime) if p.exists() else 0
                    except Exception:
                        m = 0
                    if last.get(name) != m:
                        last[name] = m
                        self.wfile.write(f"event: {name}\ndata: {m}\n\n".encode("utf-8"))
                        self.wfile.flush()
                hb += 1
                if hb >= 15:                       # 心跳防 proxy/tunnel 斷線
                    hb = 0
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _authed(self):
        """回 True(放行)/False(擋)/'set'(query 帶對的 key → 種 cookie)。未設 DH_ACCESS_KEY→全放行。"""
        key = os.getenv("DH_ACCESS_KEY", "").strip()
        if not key:
            return True
        if f"dhkey={key}" in (self.headers.get("Cookie", "") or ""):
            return True
        qs = parse_qs(urlsplit(self.path).query)
        if qs.get("key", [""])[0] == key:
            return "set"
        return False

    def _auth_gate(self) -> bool:
        """擋則回 True(已回應)。放行/需種cookie 由呼叫端續處理。"""
        au = self._authed()
        if au is True:
            return False
        key = os.getenv("DH_ACCESS_KEY", "").strip()
        if au == "set":
            self.send_response(302)
            self.send_header("Set-Cookie", f"dhkey={key}; Path=/; Max-Age=2592000; SameSite=Lax")
            self.send_header("Location", urlsplit(self.path).path or "/")
            self.end_headers()
            return True
        body = _LOGIN_HTML.encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        if self._auth_gate():
            return
        split = urlsplit(self.path)
        if split.path == "/api/stream":
            return self._handle_stream()
        if self._handle_api(split.path, parse_qs(split.query)):
            return
        if self.path in ("/", "/index.html", ""):
            self.path = "/dashboard.html"
        return super().do_GET()

    def do_POST(self):
        if self._auth_gate():
            return
        split = urlsplit(self.path)
        if split.path == "/api/research/run":
            # 立即跑一次每日持股研究摘要（LLM 有界執行；research_agent 內部已把 LLM/query/news
            # 失敗都收斂成合法 JSON，這裡只再包一層防意外例外，絕不因缺 LLM key 而 500）
            try:
                import ai_agents
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as ex:
                    res = ex.submit(ai_agents.research_agent).result(timeout=60.0)
                self._send_json({"ok": True, **res})
            except Exception as e:
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
            return
        if split.path == "/api/fin_analyze":
            # 財報透視：body {code?, text?}。有界執行(60s，貼文可能很長)；
            # ai_agents.filing_agent 內部已把 LLM/fundamentals/query 失敗都收斂成合法 JSON，
            # 這裡再包一層防意外例外，絕不因缺 LLM key 或壞輸入而 500。
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                code = str(body.get("code") or "").strip()
                text = str(body.get("text") or "")
                import ai_agents
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as ex:
                    res = ex.submit(ai_agents.filing_agent, code, text).result(timeout=60.0)
                self._send_json({"ok": True, **res})
            except Exception as e:
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
            return
        if split.path == "/api/prefs":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                cur = _load_prefs()
                data = cur.get("data", {})
                data.update(body.get("data", {}))            # 合併各 dh_* key
                ts = max(int(body.get("ts", 0)), int(cur.get("ts", 0)) + 1)
                _atomic_write(PREFS_FILE, json.dumps({"data": data, "ts": ts}, ensure_ascii=False))
                self._send_json({"ok": True, "ts": ts})
            except Exception as e:
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=400)
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    def end_headers(self):
        # state.json 與所有 .html 不要被快取(否則瀏覽器吃到舊版看板)
        p = self.path.split("?", 1)[0]
        if p.startswith("/state.json") or p.endswith(".html") or p in ("/", "/index.html", ""):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 安靜


def main():
    port = 8899
    do_scan = False
    for a in sys.argv[1:]:
        if a == "--scan":
            do_scan = True
        elif a.isdigit():
            port = int(a)

    if do_scan:
        try:
            import scan
            print("[server] 開站前先掃一輪…")
            scan.run_once(push=False)
        except Exception as e:
            print(f"[server] 預掃失敗（仍照常開站）：{e}")

    # 埠占用 → 自動 +1 重試(比照 app.py 捕捉 OSError)，最多試 10 個埠
    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            print(f"[server] 埠 {p} 已被占用，改試 {p + 1}…")
            continue
    if httpd is None:
        print(f"[server] 連續 10 個埠({port}-{port + 9})皆被占用，放棄。")
        return

    url = f"http://127.0.0.1:{port}/"
    print(f"[server] 數據獵手看板 → {url}")
    print("[server] Ctrl+C 結束")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 已停止")


if __name__ == "__main__":
    main()
