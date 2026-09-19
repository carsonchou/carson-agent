#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""app.py — 量化阿森 決策中心「原生 App 視窗」(pywebview 包 HUD 網頁)。

不是瀏覽器分頁：用 pywebview(WebView2/Edge Chromium 引擎,支援 WebGL/three.js)開一個
原生視窗。自己在 thread 起 server(自動找空 port,永不卡 port→永不打不開)。
"""
from __future__ import annotations
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import server as S  # 重用同一套 handler / 資料邏輯  # noqa: E402


def _start_server():
    ThreadingHTTPServer.allow_reuse_address = True
    srv = None
    port = None
    for p in range(8788, 8812):  # 自動找空 port,永不卡
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), S.H)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        return None
    try:
        S._maybe_refresh()  # 背景暖機
    except Exception:
        pass
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port


def main():
    port = _start_server()
    if port is None:
        print("[FATAL] 找不到可用 port", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{port}/"
    # 等 server 真的能回應(最多 ~6s),避免白屏
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1).read(10)
            break
        except Exception:
            time.sleep(0.2)
    try:
        import webview
        webview.create_window("量化阿森 · 決策中心", url, width=1680, height=980,
                              background_color="#05070e", min_size=(1100, 700))
        webview.start()  # 阻塞,直到關閉視窗
        return 0
    except Exception as e:  # pywebview 出問題 → 退回 Edge app 視窗(非分頁),最後才預設瀏覽器
        print(f"[warn] pywebview 失敗，改用 Edge app 視窗：{e}", file=sys.stderr)
        import os
        import subprocess
        edge = None
        for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if os.path.exists(c):
                edge = c
                break
        try:
            if edge:
                proc = subprocess.Popen([edge, f"--app={url}", "--window-size=1680,980",
                                         "--no-first-run", "--no-default-browser-check"])
                proc.wait()  # 視窗關掉前保持 server 存活
                return 0
        except Exception as e2:
            print(f"[warn] Edge app 也失敗：{e2}", file=sys.stderr)
        import webbrowser
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
