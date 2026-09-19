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

STALE_READS = int(__import__("os").environ.get("FAKE_STALE", "0"))
store = {}          # 假的 YouTube 端狀態:update 寫進去,list 讀出來
reads = [0]


class Videos:
    """會真的保存寫入的假端點。

    🔴 只會回「舊值」的假 API 只能證明檢查**會叫**,證明不了它
    **叫得對**。回讀檢查有兩種壞法,一種不會叫(exit code 恆為 0),
    一種一定叫(緊接著 update 讀到快取)—— 兩種我都踩過,所以這裡
    兩個方向都要能演:預設寫入即可見,`FAKE_STALE=n` 則前 n 次批次
    讀故意回舊值,用來驗傳播延遲的重試真的有用。
    """

    def list(self, part, id):
        ids = id.split(",")
        if len(ids) > 1:                      # 批次回讀
            reads[0] += 1
            stale = reads[0] <= STALE_READS
            return Exec({"items": [
                {"id": v, "snippet": ({"title": "OLD TITLE",
                                       "description": "OLD DESC"}
                                      if stale or v not in store
                                      else store[v])}
                for v in ids]})
        o = next((m for k, m in meta.items() if led.get(k) == id), None)
        return Exec({"items": [{"snippet": store.get(ids[0], {
            "title": "OLD TITLE", "description": "OLD DESC",
            "tags": ["x"], "categoryId": "27",
            "defaultLanguage": "en", "defaultAudioLanguage": "en"})}]}
            if o else {"items": []})

    def update(self, part, body):
        updated.append((body["id"], body["snippet"]))
        store[body["id"]] = body["snippet"]
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
