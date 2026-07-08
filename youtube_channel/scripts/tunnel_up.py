#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tunnel_up.py — 起本機 fileserver + cloudflared quick tunnel,把公網 URL 寫進
STUDIO/tunnel_url.json 給 ig_reels_upload.py 讀(免費、免帳號,IG Reels 發布用)。

用法：
    python scripts/tunnel_up.py          # 常駐:起 fileserver+tunnel,掛了自動重起
    python scripts/tunnel_up.py --once   # 只起一次、抓到 URL 就結束(測試用)
"""
from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
STUDIO.mkdir(exist_ok=True)
TUNNEL_JSON = STUDIO / "tunnel_url.json"
FILESERVER_PORT = 8888

# cloudflared 免帳號單一 exe,先找 PATH,再找 winget 常見安裝路徑
CLOUDFLARED_CANDIDATES = [
    "cloudflared",
    r"C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe",
    r"D:\tools\cloudflared\cloudflared.exe",
]

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _find_cloudflared() -> str | None:
    for c in CLOUDFLARED_CANDIDATES:
        if shutil.which(c):
            return c
        if Path(c).is_file():
            return c
    return None


def _write_tunnel_json(base: str) -> None:
    import json
    TUNNEL_JSON.write_text(
        json.dumps({"base": base, "ts": int(time.time())}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[tunnel_up] 已寫入 {TUNNEL_JSON}: {base}")


def _start_fileserver() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "fileserver_local.py"),
         "--port", str(FILESERVER_PORT)],
        cwd=str(ROOT),
    )


def _start_cloudflared(exe: str) -> subprocess.Popen:
    return subprocess.Popen(
        [exe, "tunnel", "--url", f"http://localhost:{FILESERVER_PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(ROOT),
    )


def _wait_for_url(proc: subprocess.Popen, timeout: int = 30) -> str | None:
    """從 cloudflared 的合併輸出逐行讀,抓到 trycloudflare URL 就回傳。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            m = URL_RE.search(line)
            if m:
                return m.group(0)
        elif proc.poll() is not None:
            break
    return None


def run_once() -> str | None:
    exe = _find_cloudflared()
    if not exe:
        print("[tunnel_up][FATAL] 找不到 cloudflared,請先安裝", file=sys.stderr)
        return None
    fs = _start_fileserver()
    time.sleep(1)  # 讓 fileserver 先綁好 port
    cf = _start_cloudflared(exe)
    url = _wait_for_url(cf)
    if url:
        _write_tunnel_json(url)
    else:
        print("[tunnel_up][FATAL] 逾時沒抓到 trycloudflare URL", file=sys.stderr)
    cf.terminate()
    fs.terminate()
    return url


def run_forever() -> None:
    exe = _find_cloudflared()
    if not exe:
        print("[tunnel_up][FATAL] 找不到 cloudflared,請先安裝", file=sys.stderr)
        return
    fs = _start_fileserver()
    time.sleep(1)
    while True:
        cf = _start_cloudflared(exe)
        url = _wait_for_url(cf)
        if url:
            _write_tunnel_json(url)
        else:
            print("[tunnel_up] 沒抓到 URL,5 秒後重試", file=sys.stderr)
            cf.terminate()
            time.sleep(5)
            continue
        # 保活:輪詢 cloudflared/fileserver 是否還活著,掛了就重起
        while True:
            time.sleep(10)
            if cf.poll() is not None:
                print("[tunnel_up] cloudflared 掛了,重起中…", file=sys.stderr)
                break
            if fs.poll() is not None:
                print("[tunnel_up] fileserver 掛了,重起中…", file=sys.stderr)
                fs = _start_fileserver()
                time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只起一次抓到 URL 就結束(測試用)")
    args = ap.parse_args()
    if args.once:
        url = run_once()
        raise SystemExit(0 if url else 1)
    run_forever()


if __name__ == "__main__":
    main()
