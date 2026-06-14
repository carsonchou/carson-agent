"""
morning_fetch.py - 抓取 Gmail 和 Google Calendar 資料，輸出給早晨日報使用
"""

import os
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

CREDENTIALS_PATH = Path(__file__).parent / "google_credentials.json"
TOKEN_PATH = Path(__file__).parent / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def get_google_service(service_name, version):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        print(json.dumps({"error": "缺少 Google API 套件，請執行：python -m pip install google-auth-oauthlib google-api-python-client"}))
        sys.exit(1)

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
        else:
            print(json.dumps({"error": "Google 尚未認證，請先執行：python scripts/google_auth_setup.py"}))
            sys.exit(1)

    return build(service_name, version, credentials=creds)


def fetch_gmail_yesterday():
    """抓取昨天的重要/未讀郵件"""
    service = get_google_service("gmail", "v1")

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
    today = datetime.now().strftime("%Y/%m/%d")
    query = f"after:{yesterday} before:{today} (is:important OR is:starred OR is:unread)"

    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=15
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me",
            id=msg_ref["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        labels = msg.get("labelIds", [])

        emails.append({
            "subject": headers.get("Subject", "(無主旨)"),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "is_unread": "UNREAD" in labels,
            "is_important": "IMPORTANT" in labels,
            "is_starred": "STARRED" in labels,
            "snippet": msg.get("snippet", "")[:150],
        })

    return emails


def fetch_calendar_today():
    """抓取今天的 Google Calendar 行程"""
    service = get_google_service("calendar", "v3")

    now = datetime.utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    time_min = start_of_day.isoformat() + "Z"
    time_max = end_of_day.isoformat() + "Z"

    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = events_result.get("items", [])
    result = []

    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date", ""))
        end = event["end"].get("dateTime", event["end"].get("date", ""))

        # 格式化時間
        if "T" in start:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            start_str = start_dt.strftime("%H:%M")
        else:
            start_str = "全天"

        if "T" in end:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            end_str = end_dt.strftime("%H:%M")
        else:
            end_str = ""

        result.append({
            "title": event.get("summary", "(無標題)"),
            "start": start_str,
            "end": end_str,
            "location": event.get("location", ""),
            "description": (event.get("description", "") or "")[:100],
            "attendees_count": len(event.get("attendees", [])),
            "is_all_day": "T" not in event["start"].get("dateTime", ""),
        })

    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    output = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "yesterday": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "gmail": [],
        "calendar": [],
        "errors": []
    }

    try:
        output["gmail"] = fetch_gmail_yesterday()
    except SystemExit:
        raise
    except Exception as e:
        output["errors"].append(f"Gmail 錯誤：{str(e)}")

    try:
        output["calendar"] = fetch_calendar_today()
    except SystemExit:
        raise
    except Exception as e:
        output["errors"].append(f"Calendar 錯誤：{str(e)}")

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
