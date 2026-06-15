#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intel_sync.py — 本機每日大量競品學習 → 推 playbook 回雲端工廠。

雲端 IP 會被 YouTube 429 限流，故把重活(每天看大量競品)放本機跑(住宅 IP)，
學完把 STUDIO/competitor_playbook.md + competitor_analysis.md SFTP 推回 droplet，
雲端發片工廠下一輪製作即時吸收(produce_batch.load_playbook 讀的就是這檔)。

用法：python scripts/intel_sync.py [--max-learn 100] [--pace 2.5] [--no-push]
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
_py_win = ROOT / ".venv" / "Scripts" / "python.exe"
_py_nix = ROOT / ".venv" / "bin" / "python"
PY = _py_win if _py_win.exists() else (_py_nix if _py_nix.exists() else Path(sys.executable))


def run_learn(max_learn, pace):
    """本機跑 intel_dept 深度學習(衝量)。"""
    cmd = [str(PY), str(SCRIPTS / "intel_dept.py"), "--max-learn", str(max_learn), "--pace", str(pace)]
    print(f"[sync] 本機學習：{' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def push_to_cloud():
    """把 playbook + analysis 推回雲端工廠（SFTP，冪等覆蓋）。"""
    cfg = ROOT / "cloud.json"
    if not cfg.exists():
        print("[sync] 無 cloud.json，略過推雲端（本機學習已保存）。"); return False
    try:
        import paramiko
    except Exception:
        print("[sync] 無 paramiko，略過推雲端。"); return False
    c = json.loads(cfg.read_text(encoding="utf-8"))
    ip, user, pw = c["ip"], c.get("user", "root"), c["password"]
    rroot = c.get("remote_root", "/root/yt")
    files = [
        (ROOT / "STUDIO" / "competitor_playbook.md", f"{rroot}/STUDIO/competitor_playbook.md"),
        (ROOT / "competitor_analysis.md", f"{rroot}/competitor_analysis.md"),
    ]
    try:
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(ip, username=user, password=pw, timeout=30)
        sf = cli.open_sftp()
        for local, remote in files:
            if local.exists():
                sf.put(str(local), remote)
                print(f"[sync] 推上雲端：{local.name} -> {remote}（{local.stat().st_size} B）")
        sf.close(); cli.close()
        print("[sync] 雲端工廠已更新，下一輪製作即吸收。")
        return True
    except Exception as e:
        print(f"[sync] 推雲端失敗（本機學習已保存，不影響）：{e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-learn", type=int, default=100)
    ap.add_argument("--pace", type=float, default=2.5)
    ap.add_argument("--no-push", action="store_true", help="只學不推雲端")
    a = ap.parse_args()
    run_learn(a.max_learn, a.pace)
    if not a.no_push:
        push_to_cloud()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
