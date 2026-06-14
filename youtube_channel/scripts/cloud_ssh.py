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


def put(local: str, remote: str):
    c = _client(); sf = c.open_sftp()
    # 確保遠端目錄存在
    rd = os.path.dirname(remote)
    if rd:
        _mkdirs(sf, rd)
    sf.put(local, remote)
    print(f"[put] {local} -> {remote}")
    sf.close(); c.close()


def _mkdirs(sf, path):
    parts = path.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            sf.stat(cur)
        except IOError:
            sf.mkdir(cur)


def putdir(local_dir: str, remote_dir: str):
    c = _client(); sf = c.open_sftp()
    _mkdirs(sf, remote_dir)
    base = Path(local_dir)
    n, skip = 0, 0
    SKIP = ("__pycache__", ".git", ".pyc", ".venv")
    for f in base.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(base).as_posix()
        if any(s in rel for s in SKIP):
            continue
        rpath = f"{remote_dir}/{rel}"
        try:
            _mkdirs(sf, os.path.dirname(rpath))
            sf.put(str(f), rpath)
            n += 1
        except Exception as e:  # noqa: BLE001
            skip += 1
            print(f"  [skip] {rel}: {e}")
    print(f"[putdir] {local_dir} -> {remote_dir}（{n} 檔，跳過 {skip}）")
    sf.close(); c.close()


if __name__ == "__main__":
    if not IP or not PW:
        print("缺 DROPLET_IP / DROPLET_PW 環境變數", file=sys.stderr); sys.exit(2)
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(1)
    if a[0] == "run":
        sys.exit(run(a[1]))
    elif a[0] == "put":
        put(a[1], a[2])
    elif a[0] == "putdir":
        putdir(a[1], a[2])
    else:
        print("未知指令", file=sys.stderr); sys.exit(1)
