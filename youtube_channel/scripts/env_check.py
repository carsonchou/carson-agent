#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_check.py — 快速健檢 .env 裡的對外憑證是否真的能用(不回顯任何密鑰值)。

檢查:
  1) .env 每個 key 有沒有重複行(髒 .env 會讓解析取錯值)
  2) TG_MAGNET_TOKEN → Telegram getMe(bot 活著嗎?username 對不對?)
  3) GMAIL_ADDRESS + GMAIL_APP_PASSWORD → SMTP 登入(贊助信寄得出去嗎?)

只印「✓/✗ + 是什麼」,絕不印 token/密碼本身。
用法:python scripts/env_check.py
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
ENVF = ROOT / ".env"


def load_env():
    env, keys = {}, []
    if ENVF.exists():
        for ln in ENVF.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k.strip()] = v.strip()
                keys.append(k.strip())
    return env, keys


def main() -> int:
    if not ENVF.exists():
        print("✗ 找不到 .env")
        return 1
    env, keys = load_env()

    # 1) 重複行
    dups = {k: c for k, c in Counter(keys).items() if c > 1}
    print("① 重複 key:", dups if dups else "無 ✓")

    # 2) TG bot
    tok = env.get("TG_MAGNET_TOKEN", "")
    if not tok:
        print("② TG_MAGNET_TOKEN: ✗ 未設")
    else:
        import json
        import urllib.request
        try:
            r = json.loads(urllib.request.urlopen(
                f"https://api.telegram.org/bot{tok}/getMe", timeout=15).read())
            if r.get("ok"):
                u = r["result"].get("username", "?")
                match = "✓ 與 CTA 相符" if u == "CarsonQuant_message_bot" else "⚠️ 與 CTA(@CarsonQuant_message_bot)不符!"
                print(f"② TG bot: ✓ 活著 @{u}  {match}")
            else:
                print(f"② TG bot: ✗ getMe 失敗 {str(r)[:100]}")
        except Exception as e:  # noqa: BLE001
            print(f"② TG bot: ✗ 連線失敗 {e}")

    # 3) Gmail SMTP
    addr = env.get("GMAIL_ADDRESS", "")
    pw = env.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not addr or not pw:
        print("③ Gmail SMTP: ✗ GMAIL_ADDRESS / GMAIL_APP_PASSWORD 未設完整")
    elif not pw.isascii() or len(pw) != 16:
        print(f"③ Gmail SMTP: ⚠️ 密碼格式怪(去空格後長度 {len(pw)}、純ASCII={pw.isascii()});"
              "Gmail App Password 應為 16 碼半形小寫字母")
    else:
        import smtplib
        try:
            # local_hostname 強制 localhost:避免 EHLO 送出中文電腦名導致 ascii 編碼錯(與帳密無關)
            s = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20, local_hostname="localhost")
            s.login(addr, pw)
            s.quit()
            print(f"③ Gmail SMTP: ✓ 登入成功({addr})——贊助信寄得出去")
        except Exception as e:  # noqa: BLE001
            print(f"③ Gmail SMTP: ✗ 登入失敗 {str(e)[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
