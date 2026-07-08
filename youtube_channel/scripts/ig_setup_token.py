#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ig_setup_token.py — 把新拿到的 IG token 驗證+落地。
用法:python scripts/ig_setup_token.py <你在Meta後台產的IG access token>

它會:①打 graph.instagram.com/me 驗 token 有效、抓 IG user id + username
       ②(可選)試把短效換長效(需 IG_APP_SECRET 環境變數,沒有就跳過)
       ③把 IG_USER_ID + IG_ACCESS_TOKEN 寫進 .env(upsert,不動其他行)
只印遮罩(末4碼)+帳號名,完整 token 不顯示。
"""
from __future__ import annotations
import os, re, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
IG = "https://graph.instagram.com"


def _upsert(txt: str, key: str, val: str) -> str:
    if re.search(rf"^(export )?{key}=.*$", txt, re.M):
        return re.sub(rf"^(export )?{key}=.*$", f"{key}={val}", txt, count=1, flags=re.M)
    return txt.rstrip("\n") + f"\n{key}={val}\n"


def _read_tmp() -> str:
    """從 STUDIO/.ig_token_tmp.txt 讀 token(browser_evaluate 存的,可能被 JSON 包字串)。"""
    import json as _json
    p = ROOT / "STUDIO" / ".ig_token_tmp.txt"
    if not p.exists():
        return ""
    raw = p.read_text(encoding="utf-8", errors="replace").strip()
    try:
        raw = _json.loads(raw)  # 若是 "IGAA..." JSON 字串
    except Exception:
        pass
    return str(raw).strip().strip('"').strip()


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--from-tmp":
        tok = _read_tmp()
        if not tok or len(tok) < 20 or tok == "NOT_FOUND":
            print("[FATAL] 暫存檔沒有有效 token(NOT_FOUND 或太短)", file=sys.stderr)
            return 2
    elif len(sys.argv) < 2 or len(sys.argv[1]) < 20:
        print("用法:python scripts/ig_setup_token.py <IG access token>  或  --from-tmp", file=sys.stderr)
        return 2
    else:
        tok = sys.argv[1].strip()

    # 可選:短效→長效(需 IG_APP_SECRET)
    secret = os.environ.get("IG_APP_SECRET", "").strip()
    if secret:
        try:
            r = requests.get(f"{IG}/access_token", params={
                "grant_type": "ig_exchange_token", "client_secret": secret,
                "access_token": tok}, timeout=30)
            d = r.json()
            if d.get("access_token"):
                tok = d["access_token"]
                print(f"[ok] 已換長效 token,有效約 {round(int(d.get('expires_in',0))/86400)} 天")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 換長效失敗(用原 token 續):{str(e)[:80]}")

    # 驗證 + 抓 user id / username
    try:
        r = requests.get(f"{IG}/me", params={
            "fields": "id,username,account_type", "access_token": tok}, timeout=30)
        d = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 連 graph.instagram.com 失敗:{e}", file=sys.stderr)
        return 1
    if "id" not in d:
        print(f"[FATAL] token 無效或非 Instagram-Login token:{str(d)[:200]}", file=sys.stderr)
        print("      (ig_reels_upload 用 graph.instagram.com,請確認產的是『Instagram API with Instagram Login』的 token)", file=sys.stderr)
        return 1
    uid, uname, atype = d["id"], d.get("username", "?"), d.get("account_type", "?")

    # 寫 .env
    txt = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    txt = _upsert(txt, "IG_USER_ID", uid)
    txt = _upsert(txt, "IG_ACCESS_TOKEN", tok)
    ENV.write_text(txt if txt.endswith("\n") else txt + "\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except Exception:
        pass

    print(f"\n✅ token 有效!帳號=@{uname}（{atype}）  IG_USER_ID={uid}")
    print(f"   已寫進 .env:IG_ACCESS_TOKEN(…{tok[-4:]}) + IG_USER_ID={uid}")
    if uname.lower() != "carson_quant" and uname != "?":
        print(f"   ⚠️ 注意:帳號名是 @{uname},不是 carson_quant——確認是你要發的那個帳號")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
