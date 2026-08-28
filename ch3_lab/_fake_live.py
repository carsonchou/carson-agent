# -*- coding: utf-8 -*-
"""用假的 Google API 跑一次 retitle.py --apply --live 的控制流。

不是為了測 API,是為了**讓新寫的 exit-code 程式碼真的被執行一次**。
上一版就是因為沒跑過,`bad` 沒初始化都沒人發現。
"""
import json, pathlib, sys, types
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

meta = {o.get("slug") or o["dir"]: o
        for o in json.loads((ROOT / "publish_meta.json").read_text("utf-8"))}
led = json.loads((ROOT / "uploaded.json").read_text("utf-8"))
updated = []

class Exec:
    def __init__(self, v): self.v = v
    def execute(self): return self.v

class Videos:
    def list(self, part, id):
        o = next((m for k, m in meta.items() if led.get(k) == id), None)
        return Exec({"items": [{"snippet": {
            "title": "OLD TITLE", "description": "OLD DESC",
            "tags": ["x"], "categoryId": "27",
            "defaultLanguage": "en", "defaultAudioLanguage": "en"}}]}
            if o else {"items": []})
    def update(self, part, body):
        updated.append((body["id"], body["snippet"]))
        return Exec({})

class Channels:
    def list(self, part, mine): return Exec(
        {"items": [{"id": "UCbo4EytWhZ7zAGSoIPioJ5g", "snippet": {}}]})

class YT:
    def videos(self): return Videos()
    def channels(self): return Channels()

import retitle
retitle.quota.can = lambda c: True
retitle.quota.spend = lambda c, l="": 0
sys.modules["google.oauth2.credentials"] = types.SimpleNamespace(
    Credentials=types.SimpleNamespace(
        from_authorized_user_file=lambda *a, **k: types.SimpleNamespace(
            valid=True, expired=False, refresh_token=None)))
sys.modules["google.auth.transport.requests"] = types.SimpleNamespace(
    Request=object)
sys.modules["googleapiclient.discovery"] = types.SimpleNamespace(
    build=lambda *a, **k: YT())
sys.argv = ["retitle.py", "--apply", "--live"]
orig = (ROOT / "publish_meta.json").read_text("utf-8")
try:
    rc = retitle.main()
finally:
    (ROOT / "publish_meta.json").write_text(orig, encoding="utf-8")
print(f"\n>>> exit code = {rc}")
print(f">>> 實際送出 update 的 videoId: {[v for v, _ in updated]}")
fam = {led[k] for k, o in meta.items() if o.get('kind') == 'famous' and k in led}
print(f">>> 其中屬於名案的: {[v for v, _ in updated if v in fam] or '無'}")
