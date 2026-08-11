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
# 2026-08-11 改版:頻道 7/2 已轉型台股新手避雷+個股體檢連載,但線上簡介/關鍵字
# 還是 2026-06 的幣圈定位(派網/網格/加密貨幣)——搜尋來的台股觀眾點進頻道頁
# 看到「加密貨幣返佣」,信任與訂閱動機直接斷。數字紀律:簡介只寫**不會過期**的
# 事實(1925 檔計畫/13 項體檢表),不寫「已體檢 N 檔」這種快照數字(會過期變謊話,
# 同 ep0 汰舊機制的教訓)。
ABOUT = """歡迎來到「量化阿森｜Carson Quant」。

這個頻道只做一件事：把台股流傳的每一句「常識」，拿真實歷史資料回測一遍，拆開來講清楚。
不喊單、不報明牌、不保證收益——只用數據說話。

你會在這裡看到：
・個股體檢系列：台股 1925 檔一檔一集，同一份 13 項體檢表跑到底——營收、獲利、配息、崩盤時到底跌多深。介紹不是推薦，數據攤開，你自己判斷。
・台股真相實驗室：「長期一定賺」「停利落袋為安」「跌深加碼」……逐條用真回測驗證，打臉或證實都照登。
・定期定額實測：0050、0056、高股息 ETF，用十年以上的真實資料算給你看，不是理論。
・新手避雷：「穩賺」話術、AI 選股神器、各種割韭菜套路——我先幫你試，你別送死。

適合：剛開始投資台股、常被各種說法搞混、不想再被話術割韭菜的你。

⚠️ 重要聲明
本頻道所有內容皆為資料整理與知識分享，不構成任何投資建議，也不代表任何買賣推薦。
投資有風險，過去績效不代表未來表現。請自行做足功課，並為自己的每一個決策負責。

📌 部分連結為聯盟推薦連結，透過它註冊我可能獲得返佣，對你不會有額外費用，是否使用完全由你決定。

新片每天更新。訂閱之後，你的清單裡每天會多一檔台股的完整體檢。"""

# 頻道關鍵字：多字詞用引號。保留「回測/定投/量化」(跨主題通用),移除派網/網格/
# 加密貨幣/交易機器人(已非主軸;仍有零星幣圈短片,但關鍵字要押在成長主軸上)。
KEYWORDS = '台股 個股體檢 0050 0056 高股息ETF 定期定額 存股 台股回測 回測 ETF 新手投資 投資避雷 量化 定投 "Carson Quant" 量化阿森'

# 未訂閱者預告片:頻道首頁對陌生訪客自動播放的影片=第一印象。EP0/系列說明片是
# 實測訂閱轉換最高格式(tw_lab EP0:171觀看3訂閱=17.5/千,均值3倍);現任預告片
# 還是 07-05 的 TradingView 開播(舊主軸,85 觀看)。
UNSUBSCRIBED_TRAILER = "4Tp2ElI8Q5g"  # 台股真相實驗室｜已經拆完14集(2026-07-31)


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
    if UNSUBSCRIBED_TRAILER:
        bs["channel"]["unsubscribedTrailer"] = UNSUBSCRIBED_TRAILER

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
