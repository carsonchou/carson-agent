# -*- coding: utf-8 -*-
"""notify.py — 把訊息推到老闆手機/信箱（給每日大檢查等用）。

支援多種後端，有設定才送（都沒設＝靜默 no-op）：
  1) ntfy.sh（最簡單·免帳號免金鑰）：design_system.json 的 "ntfy_topic" 或環境變數 NTFY_TOPIC。
     手機裝 ntfy app → 訂閱該 topic 即收推播。
  2) Gmail SMTP：環境變數 GMAIL_USER + GMAIL_APP_PW（Google 帳號設「應用程式密碼」），寄到 GMAIL_TO(預設=自己)。
  3) 自訂 webhook（Discord/Slack）：環境變數 NOTIFY_WEBHOOK。
用法：from notify import push; push("標題", "內文")
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "STUDIO" / "design_system.json"


def _ntfy_topic():
    v = os.environ.get("NTFY_TOPIC", "").strip()
    if v:
        return v
    try:
        return (json.loads(DESIGN.read_text(encoding="utf-8")).get("ntfy_topic") or "").strip()
    except Exception:
        return ""


def push(title: str, body: str, tag: str = "robot") -> bool:
    """推播一則訊息。任一後端成功即回 True；都沒設定回 False。"""
    sent = False
    import requests

    topic = _ntfy_topic()
    if topic:
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                          headers={"Title": title.encode("utf-8"), "Tags": tag}, timeout=20)
            sent = True
        except Exception:
            pass

    hook = os.environ.get("NOTIFY_WEBHOOK", "").strip()
    if hook:
        try:
            requests.post(hook, json={"content": f"**{title}**\n{body}"[:1900]}, timeout=20)
            sent = True
        except Exception:
            pass

    gu, gp = os.environ.get("GMAIL_USER", "").strip(), os.environ.get("GMAIL_APP_PW", "").strip()
    if gu and gp:
        try:
            import smtplib
            from email.mime.text import MIMEText
            to = os.environ.get("GMAIL_TO", gu).strip()
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = title
            msg["From"] = gu
            msg["To"] = to
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25) as s:
                s.login(gu, gp.replace(" ", ""))
                s.sendmail(gu, [to], msg.as_string())
            sent = True
        except Exception:
            pass

    return sent
