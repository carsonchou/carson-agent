# -*- coding: utf-8 -*-
"""
google_auth_setup.py - Google OAuth2 one-time authentication
Run: python scripts/google_auth_setup.py
"""

import sys
from pathlib import Path

CREDENTIALS_PATH = Path(__file__).parent / "google_credentials.json"
TOKEN_PATH = Path(__file__).parent / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("[ERROR] Missing packages. Run:")
        print("   python -m pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    if not CREDENTIALS_PATH.exists():
        print(f"[ERROR] Credentials file not found: {CREDENTIALS_PATH}")
        sys.exit(1)

    print("[INFO] Starting Google OAuth2 flow...")
    print("       Browser will open. Login and authorize access.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json())
    print(f"[OK] Auth complete. Token saved to: {TOKEN_PATH}")
    print()
    print("You can now use /morning in Claude Code.")


if __name__ == "__main__":
    main()
