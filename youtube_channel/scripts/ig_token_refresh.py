#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ig_token_refresh.py — 續期 IG 長效 token(免 App Secret)。
IG 長效 token 60 天到期,每週跑一次續成新的 60 天,把新 token 寫回 .env。
graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=...
"""
from __future__ import annotations
import os, re, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def _read_env_token() -> str:
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if tok:
        return tok
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if line.replace("export ", "").startswith("IG_ACCESS_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def _write_env_token(new_tok: str) -> None:
    txt = ENV.read_text(encoding="utf-8")
    if re.search(r"^(export )?IG_ACCESS_TOKEN=.*$", txt, re.M):
        txt = re.sub(r"^(export )?IG_ACCESS_TOKEN=.*$", f"IG_ACCESS_TOKEN={new_tok}", txt, count=1, flags=re.M)
    else:
        txt = txt.rstrip("\n") + f"\nIG_ACCESS_TOKEN={new_tok}\n"
    ENV.write_text(txt, encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except Exception:
        pass


def main() -> int:
    tok = _read_env_token()
    if not tok:
        print("[FATAL] 找不到 IG_ACCESS_TOKEN", file=sys.stderr); return 1
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": tok}, timeout=30)
    d = r.json()
    new = d.get("access_token")
    if not new:
        print(f"[FAIL] 續期失敗：{str(d)[:200]}", file=sys.stderr)
        log_ops("IG續期", f"⚠️ 失敗：{str(d.get('error', d))[:60]}")
        return 1
    if new != tok:
        _write_env_token(new)
    exp_days = round(int(d.get("expires_in", 0)) / 86400, 1)
    print(f"[ok] IG token 已續期，有效 {exp_days} 天")
    log_ops("IG續期", f"token 已續期，剩 {exp_days} 天")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
