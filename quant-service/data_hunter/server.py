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

import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def do_GET(self):
        if self.path in ("/", "/index.html", ""):
            self.path = "/dashboard.html"
        return super().do_GET()

    def end_headers(self):
        # state.json 不要被快取
        if self.path.startswith("/state.json"):
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
