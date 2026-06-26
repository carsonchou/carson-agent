# -*- coding: utf-8 -*-
"""賈維斯的三大工具 —— 給 LiveKit agent.py 用（影片裡的 superpowers）。

    from tools import search_web, scrape_url, send_email
然後把它們掛到 Agent(tools=[search_web, scrape_url, send_email])。

工具本體都是標準 Python（Firecrawl REST + Gmail SMTP），跟 LiveKit 版本無關，照著金鑰填就會動。
只有最外層的 @function_tool 裝飾器是 livekit-agents 提供的；若你的 SDK 版本 import 路徑不同，
在資料夾跑 `claude` 一句「修正 function_tool 的 import 對齊我的 livekit-agents 版本」即可。
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

import requests

try:
    from livekit.agents import function_tool, RunContext
except Exception:  # 沒裝 livekit 時也能單獨 import 測試工具本體
    def function_tool(*a, **k):
        def deco(fn):
            return fn
        return deco
    RunContext = object  # type: ignore


# ── 1) 上網查（Firecrawl Search）──────────────────────────────
@function_tool()
async def search_web(context: "RunContext", query: str) -> str:
    """上網查即時資訊並回傳前幾筆重點。用於新聞、價格、查證等需要最新資料的問題。"""
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not key:
        return "我這邊還沒設好上網查資料的金鑰，先沒辦法查。"
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"query": query, "limit": 5},
            timeout=25,
        )
        data = r.json()
        items = data.get("data") or data.get("results") or []
        if not items:
            return f"查了「{query}」但沒找到明確結果。"
        out = []
        for it in items[:5]:
            title = it.get("title") or it.get("url") or ""
            desc = it.get("description") or it.get("snippet") or ""
            out.append(f"{title}：{desc}".strip("："))
        return " 。 ".join(out)[:1200]
    except Exception as e:  # noqa: BLE001
        return f"查資料的時候出了點狀況：{str(e)[:60]}"


# ── 2) 抓網頁內容（Firecrawl Scrape）──────────────────────────
@function_tool()
async def scrape_url(context: "RunContext", url: str) -> str:
    """抓某個網址的內文（markdown）回來，用於老闆指定某頁要你讀重點時。"""
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not key:
        return "還沒設好抓網頁的金鑰。"
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"]},
            timeout=30,
        )
        md = (r.json().get("data") or {}).get("markdown") or ""
        return md[:2000] if md else "這頁抓不到內容。"
    except Exception as e:  # noqa: BLE001
        return f"抓網頁出了點狀況：{str(e)[:60]}"


# ── 3) 寄 Email（Gmail SMTP，需 App 密碼）─────────────────────
@function_tool()
async def send_email(context: "RunContext", to: str, subject: str, body: str) -> str:
    """用老闆的 Gmail 寄一封信。寄出前 agent 應已口頭跟老闆確認過收件人、主旨、內容。"""
    user = os.environ.get("GMAIL_ADDRESS", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not user or not pw:
        return "還沒設好寄信的 Gmail 帳號或 App 密碼，先沒辦法寄。"
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        return f"好，信已經寄給 {to} 了。"
    except Exception as e:  # noqa: BLE001
        return f"寄信失敗：{str(e)[:80]}"


# 單獨測試工具本體（不經 LiveKit）：python tools.py
if __name__ == "__main__":
    import asyncio
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(asyncio.get_event_loop().run_until_complete(search_web(None, "比特幣 現在價格")))
