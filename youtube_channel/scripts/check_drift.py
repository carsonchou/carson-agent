#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_drift.py — 比對本機 scripts/*.py 與雲端是否同步(防悄悄 drift)。

本機↔雲端腳本無版控,改一邊忘了同步另一邊會靜默分岔。這支用 md5 逐檔比對,列出不一致的檔。
用法:python scripts/check_drift.py   (需 cloud.json;會設 DROPLET_* 環境變數)
"""
from __future__ import annotations
import hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CLOUD_SSH = SCRIPTS / "cloud_ssh.py"


def _local_md5():
    out = {}
    for f in sorted(SCRIPTS.glob("*.py")):
        out[f.name] = hashlib.md5(f.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return out


def main() -> int:
    cfg_p = ROOT / "cloud.json"
    if not cfg_p.exists():
        print("無 cloud.json,無法比對。"); return 2
    c = json.loads(cfg_p.read_text(encoding="utf-8"))
    env = dict(os.environ, DROPLET_IP=c["ip"], DROPLET_PW=c["password"],
               DROPLET_USER=c.get("user", "root"), PYTHONIOENCODING="utf-8")
    rr = c.get("remote_root", "/root/yt")
    # 雲端逐檔 md5(先把 CRLF 正規化再算,和本機一致)
    remote_cmd = (f"cd {rr}/scripts && for f in *.py; do "
                  f"printf '%s %s\\n' \"$(sed 's/\\r$//' \"$f\" | md5sum | cut -d' ' -f1)\" \"$f\"; done")
    p = subprocess.run([sys.executable, str(CLOUD_SSH), "run", remote_cmd],
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    remote = {}
    for ln in (p.stdout or "").splitlines():
        parts = ln.strip().split()
        if len(parts) == 2 and len(parts[0]) == 32:
            remote[parts[1]] = parts[0]
    local = _local_md5()
    only_local = sorted(set(local) - set(remote))
    only_cloud = sorted(set(remote) - set(local))
    diff = sorted(f for f in (set(local) & set(remote)) if local[f] != remote[f])
    if not diff and not only_local and not only_cloud:
        print(f"✅ 本機與雲端 {len(local)} 支腳本完全同步。")
        return 0
    print("⚠ 本機↔雲端腳本不同步:")
    for f in diff:
        print(f"  ≠ {f}(內容不同)")
    for f in only_local:
        print(f"  ←只在本機 {f}")
    for f in only_cloud:
        print(f"  →只在雲端 {f}")
    print(f"\n共 {len(diff)} 檔內容不同、{len(only_local)} 只在本機、{len(only_cloud)} 只在雲端。")
    print("同步:python scripts/cloud_ssh.py put scripts/<檔> " + rr + "/scripts/<檔>(記得 MSYS_NO_PATHCONV=1)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
