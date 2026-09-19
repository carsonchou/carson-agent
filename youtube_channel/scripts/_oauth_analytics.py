# -*- coding: utf-8 -*-
"""重新授權 YouTube token，加 yt-analytics.readonly（看完播率/留存曲線）。
本機跑(需瀏覽器)：會開 Google 登入頁，請用『量化阿森』頻道的 Google 帳號登入並同意。
保留原 youtube.force-ssl(上傳不壞)。完成後 token_manage.json 更新，舊的備份成 .bak。"""
import shutil, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",      # 保留:上傳/縮圖/管理
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # 新增:看完播率/留存/流量來源
]
cs = ROOT / "client_secrets.json"
tok = ROOT / "token_manage.json"

if not cs.exists():
    print("[FATAL] 找不到 client_secrets.json"); sys.exit(1)
if tok.exists():
    shutil.copy(str(tok), str(tok) + ".bak")
    print("✓ 已備份舊 token → token_manage.json.bak")

print("\n即將開啟瀏覽器…請用『量化阿森』頻道的 Google 帳號登入並同意(會多一個『查看 YouTube Analytics』權限)。\n")
flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
creds = flow.run_local_server(port=0, prompt="consent")
tok.write_text(creds.to_json(), encoding="utf-8")

print("\n[ok] 授權完成！新 token scopes:")
for s in json.load(open(tok)).get("scopes", []):
    print("   ·", s)
print("\n👉 完成後跟我說一聲『好了』，我會把新 token 推到雲端，並馬上抓你的完播率/留存數據。")
