# -*- coding: utf-8 -*-
"""輪詢 backfill 進度:ig_ledger 已發數 + 程序在不在 + log 尾。"""
import json, sys, os
from pathlib import Path
YT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
cfg = json.load(open(YT / "cloud.json", encoding="utf-8"))
import paramiko
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(cfg["ip"], username=cfg.get("user", "root"), password=cfg["password"], timeout=30)
RR = "/root/yt"
def run(cmd, t=30):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace").rstrip()
print("ig_ledger 已發:", run(f"{RR}/.venv/bin/python -c \"import json,os;p='{RR}/STUDIO/ig_ledger.json';print(len(json.load(open(p))) if os.path.exists(p) else 0)\""))
print("程序:", run("pgrep -af ig_backfill.py | grep -v pgrep || echo DONE"))
print("log 尾:\n", run(f"tail -8 {RR}/logs/ig_backfill.log 2>/dev/null || echo NO_LOG"))
c.close()
