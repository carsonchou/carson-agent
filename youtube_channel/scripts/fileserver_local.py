#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fileserver_local.py — 本機唯讀檔案伺服器,只吐 output/ 下的 .mp4 / .jpg 給公網抓(給 IG Reels 用)。

刻意縮小暴露面(資安):只認 `/<slug>.mp4` 或 `/<slug>.cover.jpg` 這種單層檔名,
對應到 output/ 下實際存在的檔案才回 200;其餘一律 403。不列目錄、不吐任何
.env/.json/.py/子路徑/`..`。支援 HTTP Range(Meta 可能分段抓影片)。

用法：python scripts/fileserver_local.py [--port 8888]
"""
from __future__ import annotations
import argparse
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

# 只允許單層 `slug.mp4` 或 `slug.cover.jpg`(slug 不可含 / 或 ..)
ALLOWED = re.compile(r"^/([^/]+\.(?:mp4|jpg))$")
CONTENT_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg"}


class Handler(BaseHTTPRequestHandler):
    server_version = "FileserverLocal/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 — 精簡 log,只印路徑+狀態
        print(f"[fileserver] {self.address_string()} - {fmt % args}")

    def _resolve(self):
        """回傳 (path, name) 合法且存在就給 Path,否則 None。"""
        path = urlparse(self.path).path
        m = ALLOWED.match(unquote(path))
        if not m:
            return None
        name = m.group(1)
        fp = (OUT / name).resolve()
        # 防 .. 逃逸:resolve 後必須仍在 OUT 底下
        try:
            fp.relative_to(OUT.resolve())
        except ValueError:
            return None
        if not fp.is_file():
            return None
        return fp

    def do_GET(self):
        fp = self._resolve()
        if fp is None:
            self.send_error(403, "Forbidden")
            return
        size = fp.stat().st_size
        ctype = CONTENT_TYPES.get(fp.suffix.lower(), "application/octet-stream")
        range_header = self.headers.get("Range")
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                start_s, end_s = m.groups()
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with fp.open("rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
        # 無 Range → 整檔回傳
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with fp.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_HEAD(self):
        fp = self._resolve()
        if fp is None:
            self.send_error(403, "Forbidden")
            return
        size = fp.stat().st_size
        ctype = CONTENT_TYPES.get(fp.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8888)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"[fileserver] 供檔 {OUT} → 0.0.0.0:{args.port}(唯讀,只允許 .mp4/.jpg)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
