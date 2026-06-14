#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_channel.py — 更新頻道個人資料(關於/描述/關鍵字/地區)為吻合主題。

用 youtube.force-ssl(token_manage.json)。注意：頻道「名稱」用 API 更新常不生效，
若名稱沒變請到 Studio→自訂→基本資訊改；描述/關鍵字可靠可改。
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"
TOKEN = PROJECT_ROOT / "token_manage.json"

TITLE = "量化阿森｜Carson Quant"
ABOUT = """歡迎來到「量化阿森｜Carson Quant」。

這個頻道只做一件事：把每一個交易策略和自動交易工具，拆開來講清楚。
不喊單、不報明牌、不保證收益——我們用邏輯和數據說話。

你會在這裡學到：
・策略拆解：網格、定投、馬丁等策略的運作邏輯，以及它們什麼時候會失效。
・派網實操：Pionex 自動交易機器人怎麼開、參數怎麼設、新手怎麼避坑。
・交易心法：倉位管理、風險控制、回撤心理，為什麼多數人會賠錢。
・回測實驗室：用真實數據驗證策略，公開勝率、最大回撤與限制。

適合：沒時間盯盤、想要有紀律可複製方法、不想再被話術割韭菜的你。

⚠️ 重要聲明
本頻道所有內容皆為交易知識與資訊分享，不構成任何投資建議，也不代表任何買賣推薦。
加密貨幣與自動交易具高風險，過去績效不代表未來表現。
請務必使用閒置資金、自行做足功課，並為自己的每一個決策負責。

📌 部分連結為聯盟推薦連結，透過它註冊我可能獲得返佣，對你不會有額外費用，是否使用完全由你決定。

新片每週更新。想跟上的話，記得訂閱並開啟小鈴鐺。"""

# 頻道關鍵字：多字詞用引號
KEYWORDS = '量化交易 自動交易 網格交易 "派網 Pionex" Pionex 定投 DCA 回測 加密貨幣 被動收入 交易機器人 風險管理 "Carson Quant" 量化阿森'


def get_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def main() -> int:
    yt = get_service()
    ch = yt.channels().list(part="brandingSettings,snippet", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        print("[FATAL] 找不到頻道。")
        return 1
    item = items[0]
    cid = item["id"]
    print(f"頻道 ID: {cid}")
    print(f"目前名稱: {item['snippet'].get('title')}")

    bs = item.get("brandingSettings", {}) or {}
    bs.setdefault("channel", {})
    # 保留現有名稱(API 改 title 不可靠且會讓整包更新失效)；名稱改在 Studio 做
    bs["channel"]["title"] = item["snippet"].get("title", TITLE)
    bs["channel"]["description"] = ABOUT
    bs["channel"]["keywords"] = KEYWORDS
    bs["channel"]["country"] = "TW"
    bs["channel"]["defaultLanguage"] = "zh-Hant"

    try:
        yt.channels().update(part="brandingSettings", body={"id": cid, "brandingSettings": bs}).execute()
        print("[ok] 頻道關於/描述/關鍵字/地區已更新。")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 更新失敗：{exc}")
        return 1

    # 驗證
    ch2 = yt.channels().list(part="brandingSettings,snippet", mine=True).execute()
    c2 = ch2["items"][0]
    print(f"更新後名稱: {c2['snippet'].get('title')}")
    print("更新後描述前60字:", (c2.get('brandingSettings', {}).get('channel', {}).get('description', '')[:60]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
