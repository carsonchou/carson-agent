# -*- coding: utf-8 -*-
"""
tunnel.py — 讓手機在外面也能連進看板（公網通道），把公網 URL 寫進 tunnel_url.txt（前端 QR 讀）

固定網址(推薦)：ngrok 免費靜態網域——設 env NGROK_AUTHTOKEN 與 NGROK_DOMAIN(免費帳號給一個)，
                URL 永不變、QR 永遠有效。
無帳號備選：cloudflared 免費快速通道——URL 每次啟動會變(前端 QR 自動反映)。

＊需先裝好 ngrok 或 cloudflared(裝到 D 槽)。開著這支＋app.py，手機掃 QR 就能連。
用法：python tunnel.py            （自動挑 ngrok(有token) 或 cloudflared）
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL_FILE = HERE / "tunnel_url.txt"
PORT = int(os.getenv("DH_PORT", "8899"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _write_url(url: str) -> None:
    try:
        URL_FILE.write_text(url.strip(), encoding="utf-8")
        print(f"[tunnel] 公網 URL → {url}")
        print(f"[tunnel] 已寫入 {URL_FILE.name}，看板「📱手機開」會出公網 QR")
    except Exception as e:
        print(f"[tunnel] 寫入 URL 失敗：{e}")


def _run_and_capture(cmd: list[str], pattern: str) -> None:
    """啟動通道行程、從輸出抓 URL 寫檔，並持續掛著(關掉即斷)。"""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    got = False
    try:
        for line in proc.stdout:                       # type: ignore
            line = line.rstrip()
            if line:
                print("  " + line)
            m = re.search(pattern, line)
            if m and not got:
                _write_url(m.group(0))
                got = True
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            if URL_FILE.exists():
                URL_FILE.unlink()      # 斷線清掉，QR 不再顯示過期公網網址
        except Exception:
            pass


def main() -> None:
    token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    domain = os.getenv("NGROK_DOMAIN", "").strip()
    ngrok = shutil.which("ngrok")
    cf = shutil.which("cloudflared")

    if token and domain and ngrok:
        print(f"[tunnel] ngrok 固定網域 {domain}（URL 不變）")
        try:
            subprocess.run([ngrok, "config", "add-authtoken", token], check=False)
        except Exception:
            pass
        _write_url(f"https://{domain}")
        _run_and_capture([ngrok, "http", f"--domain={domain}", str(PORT)],
                         r"https://[^\s]+")
    elif cf:
        print("[tunnel] cloudflared 快速通道（URL 每次會變，前端 QR 自動反映）")
        _run_and_capture([cf, "tunnel", "--url", f"http://localhost:{PORT}"],
                         r"https://[a-z0-9-]+\.trycloudflare\.com")
    else:
        print("[tunnel] 找不到 ngrok / cloudflared。請擇一裝到 D 槽後重跑：")
        print("  固定網址(推薦)：ngrok（免費帳號給一個靜態網域）→ 設 NGROK_AUTHTOKEN、NGROK_DOMAIN")
        print("  免帳號       ：cloudflared（quick tunnel，URL 會變）")
        print("  裝好後：python tunnel.py")


if __name__ == "__main__":
    main()
