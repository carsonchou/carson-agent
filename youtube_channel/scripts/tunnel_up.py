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
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 本檔常以無 console 方式常駐(vbs/pythonw/排程),此時 spawn console 子程序
# (fileserver/cloudflared)Windows 會為每個各開一個黑窗 → 一律帶 CREATE_NO_WINDOW。
_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}

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
        cwd=str(ROOT), **_NO_WINDOW,
    )


def _start_cloudflared(exe: str) -> subprocess.Popen:
    return subprocess.Popen(
        [exe, "tunnel", "--url", f"http://localhost:{FILESERVER_PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(ROOT), **_NO_WINDOW,
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
        # 保活:輪詢 cloudflared/fileserver 是否還活著,掛了就重起;並定期重蓋 ts(否則 tunnel 活著但 ts 變舊→下游誤判不通)
        _cyc = 0
        while True:
            time.sleep(10)
            _cyc += 1
            if _cyc % 24 == 0:  # 每 ~4 分鐘重蓋一次 ts(同 URL·刷新新鮮度)
                _write_tunnel_json(url)
            if cf.poll() is not None:
                print("[tunnel_up] cloudflared 掛了,重起中…", file=sys.stderr)
                break
            if fs.poll() is not None:
                print("[tunnel_up] fileserver 掛了,重起中…", file=sys.stderr)
                fs = _start_fileserver()
                time.sleep(1)


def _fresh_and_reachable(max_age: int = 900) -> bool:
    """tunnel_url.json 夠新(<max_age 秒)且公網 URL 真的連得上 → 視為健康。"""
    import json
    import urllib.request
    try:
        d = json.loads(TUNNEL_JSON.read_text(encoding="utf-8"))
        if (time.time() - int(d.get("ts", 0))) > max_age:
            return False
        base = d.get("base")
        if not base:
            return False
        req = urllib.request.Request(base, method="HEAD")
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:  # 4xx(如 fileserver 對根路徑回 403)=伺服器有回應=tunnel 通
        return e.code < 500
    except Exception:  # noqa: BLE001  連線錯/逾時/5xx=真的不通
        return False


def _fresh(max_age: int = 900) -> bool:
    """只看 tunnel_url.json 夠不夠新(<max_age 秒)。ts 新=run_forever 還活著在每~4 分重蓋 ts
    (且它內圈會自動重啟掛掉的 cloudflared)→視為健康,不再查 URL 可達性。
    ⚠️根因修:cloudflared quick-tunnel 邊緣常抖,HEAD 逾時/5xx 會讓 _fresh_and_reachable 誤判
    不健康→每次 ensure 都 spawn 新 run_forever 卻不清舊的→tunnel/fileserver 程序 20 分一對爆增
    (實測一夜堆到 150 個)。改成只看新鮮度即可,tunnel 真死時 ts 會過期(~15 分)才重起。"""
    import json
    try:
        d = json.loads(TUNNEL_JSON.read_text(encoding="utf-8"))
        return (time.time() - int(d.get("ts", 0))) <= max_age
    except Exception:  # noqa: BLE001
        return False


def _reachable_retry(base: str, tries: int = 3) -> bool:
    """對 tunnel URL 做 HEAD,容忍 cloudflared 邊緣抖動:重試 tries 次,任一次通(<500 或 4xx)就算可達。
    避免單次 HEAD 逾時就誤判死掉→誤殺一個其實還活著的 tunnel。"""
    import urllib.request
    import urllib.error
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(base, method="HEAD"), timeout=8) as r:
                return r.status < 500
        except urllib.error.HTTPError as e:  # 4xx=伺服器有回應=通
            return e.code < 500
        except Exception:  # noqa: BLE001
            if i < tries - 1:
                time.sleep(3)
    return False


def _kill_stale_tunnels() -> None:
    """換 tunnel 前先殺掉現有 tunnel_up(run_forever)+fileserver_local 程序(除自己),
    避免 spawn 新的又不清舊的→程序爆增(先前一夜堆到 150 個的根因)。Windows best-effort。"""
    import os
    me = os.getpid()
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'tunnel_up|fileserver_local' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=20, **_NO_WINDOW).stdout
        for tok in out.split():
            try:
                pid = int(tok.strip())
                if pid != me:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True, timeout=10, **_NO_WINDOW)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def ensure() -> None:
    """cron 自癒:tunnel 新鮮(ts<900s)且可達(HEAD 帶重試容忍)→無需動作;否則先殺舊 tunnel/fileserver
    (防爆增)再 detached 起一個常駐 run_forever。平衡:救 IG(死 tunnel 會被替換)又不爆增(換前先清)。"""
    import json
    healthy = False
    try:
        d = json.loads(TUNNEL_JSON.read_text(encoding="utf-8"))
        fresh = (time.time() - int(d.get("ts", 0))) <= 900
        base = d.get("base")
        if fresh and base and _reachable_retry(base):
            healthy = True
    except Exception:  # noqa: BLE001
        healthy = False
    if healthy:
        print("[tunnel_up] tunnel 健康(新鮮+可達),無需動作")
        return
    print("[tunnel_up] tunnel 不健康(過期或不可達),先殺舊 tunnel/fileserver 再重啟…")
    _kill_stale_tunnels()  # 換之前先清舊的,防程序爆增
    kw = {}
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP:脫離父程序,cron 子程序結束也不會收掉 tunnel
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    logf = open(ROOT / "logs" / "tunnel_up.log", "a", encoding="utf-8", errors="replace")
    subprocess.Popen([sys.executable, str(ROOT / "scripts" / "tunnel_up.py")],
                     cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT, **kw)
    print("[tunnel_up] 已 detached 啟動常駐 tunnel")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只起一次抓到 URL 就結束(測試用)")
    ap.add_argument("--ensure", action="store_true", help="cron 自癒:不健康才 detached 重啟常駐")
    args = ap.parse_args()
    if args.ensure:
        ensure()
        raise SystemExit(0)
    if args.once:
        url = run_once()
        raise SystemExit(0 if url else 1)
    run_forever()


if __name__ == "__main__":
    main()
