#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cloud_ssh.py — 佈署用 SSH 小工具（密碼/IP 由環境變數帶入，不寫進檔案）。

環境變數：DROPLET_IP, DROPLET_PW（必要），DROPLET_USER（預設 root）
用法：
  python cloud_ssh.py run "<remote shell command>"      # 執行並串流輸出
  python cloud_ssh.py put <local_path> <remote_path>    # 上傳檔案(SFTP)
  python cloud_ssh.py putdir <local_dir> <remote_dir>   # 上傳整個目錄
"""
from __future__ import annotations
import os, sys, stat
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import paramiko

IP = os.environ.get("DROPLET_IP", "").strip()
PW = os.environ.get("DROPLET_PW", "").strip()
USER = os.environ.get("DROPLET_USER", "root").strip()


def _client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(IP, username=USER, password=PW, timeout=30)
    return c


def run(cmd: str) -> int:
    c = _client()
    chan = c.get_transport().open_session()
    chan.get_pty()
    chan.exec_command(cmd)
    out = b""
    while True:
        if chan.recv_ready():
            data = chan.recv(4096)
            sys.stdout.buffer.write(data); sys.stdout.flush()
        if chan.exit_status_ready() and not chan.recv_ready():
            break
    # 收尾
    while chan.recv_ready():
        sys.stdout.buffer.write(chan.recv(4096))
    rc = chan.recv_exit_status()
    c.close()
    return rc


def run_detached(cmd: str) -> None:
    """Fire-and-forget：不開 PTY，不等待背景程序結束。
    cmd 應自帶 setsid nohup ... </dev/null >>log 2>&1 &，
    使背景程序在 channel 關閉後不被 SIGHUP 殺掉。
    """
    c = _client()
    # 不呼叫 get_pty()，避免 channel 關閉時 SIGHUP 殺掉 nohup 子程序
    _stdin, stdout, _stderr = c.exec_command(cmd, timeout=15)
    try:
        stdout.read()   # 讀完 & 前景輸出（含 "triggered"），確認啟動訊號
    except Exception:
        pass
    c.close()


# ── 這台 droplet 的 SFTP subsystem 壞掉(paramiko sf.put/sf.get 對任何路徑都 ENOENT)。
# ── 改走 exec channel + base64(純 ASCII 免跳脫),並用 md5 驗證,失敗會 raise(不再靜默假成功)。
def _exec(cmd: str, timeout: int = 180):
    """在 exec channel(不開 pty,輸出乾淨)跑一條命令,回 (rc, stdout_bytes, stderr_bytes)。"""
    c = _client()
    try:
        _in, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read(); e = err.read()
        rc = out.channel.recv_exit_status()
        return rc, o, e
    finally:
        c.close()


def _q(s: str) -> str:
    """安全單引號包住任意字串給遠端 shell。"""
    return "'" + s.replace("'", "'\\''") + "'"


def put(local: str, remote: str):
    import base64, hashlib
    data = open(local, "rb").read()
    b64 = base64.b64encode(data).decode()
    rd = os.path.dirname(remote); tmp = remote + ".b64tmp"
    if rd:
        rc, _o, e = _exec(f"mkdir -p {_q(rd)}")
        if rc != 0:
            raise RuntimeError(f"put mkdir 失敗: {e.decode(errors='replace')[:160]}")
    _exec(f": > {_q(tmp)}")
    CH = 80000  # 每塊 b64 <ARG_MAX,分塊 append(可傳任意大小)
    for i in range(0, len(b64), CH):
        rc, _o, e = _exec(f"printf %s {_q(b64[i:i+CH])} >> {_q(tmp)}")
        if rc != 0:
            raise RuntimeError(f"put 分塊寫入失敗: {e.decode(errors='replace')[:160]}")
    # decode 到 .new 再 mv(同檔系統原子替換,避免 cron/import 讀到寫一半的檔)
    rc, o, e = _exec(f"base64 -d {_q(tmp)} > {_q(remote)}.new && mv -f {_q(remote)}.new {_q(remote)} && rm -f {_q(tmp)} && md5sum {_q(remote)} | cut -d' ' -f1")
    md5_remote = o.decode(errors="replace").strip().split("\n")[-1].strip()
    md5_local = hashlib.md5(data).hexdigest()
    if rc != 0 or md5_remote != md5_local:
        raise RuntimeError(f"put 驗證失敗 rc={rc} 本機md5={md5_local} 遠端md5={md5_remote} err={e.decode(errors='replace')[:160]}")
    print(f"[put] {os.path.basename(local)} -> {remote}  OK(md5={md5_local[:8]})")


def get(remote: str, local: str):
    import base64
    Path(os.path.dirname(local) or ".").mkdir(parents=True, exist_ok=True)
    rc, o, e = _exec(f"base64 -w0 {_q(remote)}")
    if rc != 0:
        raise RuntimeError(f"get 失敗: {e.decode(errors='replace')[:160]}")
    data = base64.b64decode(o.replace(b"\n", b"").replace(b"\r", b""))
    open(local, "wb").write(data)
    print(f"[get] {remote} -> {local}  OK({len(data)}B)")


def putdir(local_dir: str, remote_dir: str):
    base = Path(local_dir); n, skip = 0, 0
    SKIP = ("__pycache__", ".git", ".pyc", ".venv")
    for f in base.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(base).as_posix()
        if any(s in rel for s in SKIP):
            continue
        try:
            put(str(f), f"{remote_dir}/{rel}")
            n += 1
        except Exception as ex:  # noqa: BLE001
            skip += 1
            print(f"  [skip] {rel}: {ex}")
    print(f"[putdir] {local_dir} -> {remote_dir}（{n} 檔，跳過 {skip}）")


if __name__ == "__main__":
    if not IP or not PW:
        print("缺 DROPLET_IP / DROPLET_PW 環境變數", file=sys.stderr); sys.exit(2)
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(1)
    if a[0] == "run":
        sys.exit(run(a[1]))
    elif a[0] == "detached":
        run_detached(a[1])
    elif a[0] == "get":
        get(a[1], a[2])
    elif a[0] == "put":
        put(a[1], a[2])
    elif a[0] == "putdir":
        putdir(a[1], a[2])
    else:
        print("未知指令", file=sys.stderr); sys.exit(1)
