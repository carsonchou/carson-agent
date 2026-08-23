#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""輪詢 SLEEP(4C3CTKI1BFM)的處理狀態直到完成或失敗。每 10 分鐘一次。"""
import pathlib, sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube.force-ssl"]
VID = "4C3CTKI1BFM"
cr = Credentials.from_authorized_user_file(str(CH2/"token.json"), SCOPES)
if not cr.valid and cr.expired and cr.refresh_token: cr.refresh(Request())
yt = build("youtube","v3",credentials=cr,cache_discovery=False)
for i in range(36):                       # 最多 6 小時
    items = yt.videos().list(part="status,contentDetails,processingDetails",
                             id=VID).execute().get("items", [])
    if not items:
        print("B-GONE 影片查不到(可能被移除)", flush=True); break
    st = items[0]["status"]; pd = items[0].get("processingDetails", {})
    us, ps = st.get("uploadStatus"), pd.get("processingStatus")
    dur = items[0]["contentDetails"].get("duration")
    if us == "processed":
        print(f"B-PROCESSED 時長 {dur}", flush=True); break
    if us in ("rejected", "failed") or ps == "failed":
        print(f"B-FAILED upload={us} processing={ps} "
              f"reason={st.get('rejectionReason')} {pd.get('processingFailureReason')}",
              flush=True); break
    print(f"B-WAIT {i*10} 分 upload={us} processing={ps} dur={dur}", flush=True)
    time.sleep(600)
