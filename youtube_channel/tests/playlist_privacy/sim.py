#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_playlists 正式模式的離線模擬器 —— 不連網、不碰真的 playlists.json。

為什麼不自己抄一份 insert 迴圈來測:抄本會跟著產線一起漂,而漂掉的時候測試照樣綠
(memory `fix-breaks-its-own-instrument`)。這支是**把 scripts/build_playlists.py 的原始碼
直接 exec 起來跑真的 main()**,只換掉兩個東西:
  ① sys.modules['decision_dept'] → 假的 yt_service(離線,把每次呼叫記下來)
  ② 模組的 PLAYLISTS_STATE → 暫存檔(🔴 main() 結尾會整檔覆寫它,絕不能指到真檔)
LEDGER 仍指向真的 STUDIO/uploaded_ledger.json —— 只讀,而且「09-17 那一輪會插哪些片」
本來就是由真帳本決定的。

`mutate` 參數收一個 (str)->str 的函式,用來做突變列:改完的原始碼跑出來如果測試還是綠,
表示那條判準根本沒在看那段程式碼。
"""
import io
import json
import shutil
import sys
import tempfile
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]          # youtube_channel/
SRC = BASE / "scripts" / "build_playlists.py"
REAL_STATE = BASE / "STUDIO" / "playlists.json"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class FakeYT:
    """只實作 build_playlists 真的會呼叫到的那幾支。不認得的呼叫要炸,不要靜默回空。"""

    def __init__(self, state, privacy, default_privacy):
        self._pl = {name: d["playlist_id"] for name, d in state.items()}
        self._items = {d["playlist_id"]: list(d.get("video_ids", [])) for d in state.values()}
        self._privacy = dict(privacy)
        self._default = default_privacy
        self.inserted = []          # [(playlist_id, video_id)] —— 依實際呼叫順序
        self.videos_list_calls = []  # [ids_in_that_call] —— 用來核 50 支/批

    # --- playlists() ---
    def playlists(self):
        outer = self

        class _P:
            def list(self, **kw):
                return _Resp({"items": [{"id": pid, "snippet": {"title": t}}
                                        for t, pid in outer._pl.items()]})

            def insert(self, **kw):
                title = kw["body"]["snippet"]["title"]
                pid = "PLFAKE_" + title
                outer._pl[title] = pid
                outer._items.setdefault(pid, [])
                return _Resp({"id": pid})
        return _P()

    # --- playlistItems() ---
    def playlistItems(self):
        outer = self

        class _PI:
            def list(self, **kw):
                ids = outer._items.get(kw["playlistId"], [])
                return _Resp({"items": [{"contentDetails": {"videoId": v}} for v in ids]})

            def insert(self, **kw):
                sn = kw["body"]["snippet"]
                pid, vid = sn["playlistId"], sn["resourceId"]["videoId"]
                outer._items.setdefault(pid, []).append(vid)
                outer.inserted.append((pid, vid))
                return _Resp({"id": "PLI_" + vid})
        return _PI()

    # --- videos() ---
    def videos(self):
        outer = self

        class _V:
            def list(self, **kw):
                ids = [i for i in kw["id"].split(",") if i]
                outer.videos_list_calls.append(ids)
                items = []
                for i in ids:
                    st = outer._privacy.get(i, outer._default)
                    if st is None:          # 模擬「這支 id 根本沒回來」
                        continue
                    items.append({"id": i, "status": {"privacyStatus": st}})
                return _Resp({"items": items})
        return _V()


def simulate(privacy=None, max_add=10, default_privacy="public", mutate=None):
    """回傳 dict:inserted / videos_list_calls / stdout / stderr / rc / src。"""
    src = SRC.read_text(encoding="utf-8")
    if mutate is not None:
        src = mutate(src)

    state = json.loads(REAL_STATE.read_text(encoding="utf-8"))
    yt = FakeYT(state, privacy or {}, default_privacy)

    fake_dd = types.ModuleType("decision_dept")
    fake_dd.yt_service = lambda *a, **k: yt
    saved_dd = sys.modules.get("decision_dept")
    sys.modules["decision_dept"] = fake_dd
    saved_argv = sys.argv

    tmpdir = Path(tempfile.mkdtemp(prefix="bp_sim_"))
    tmp_state = tmpdir / "playlists.json"
    shutil.copy2(REAL_STATE, tmp_state)

    mod = types.ModuleType("bp_under_test")
    mod.__file__ = str(SRC)
    out, err = io.StringIO(), io.StringIO()
    try:
        exec(compile(src, str(SRC), "exec"), mod.__dict__)
        mod.PLAYLISTS_STATE = tmp_state          # 🔴 改寫真檔的唯一一行,指到暫存
        sys.argv = ["build_playlists.py", "--max", str(max_add)]
        with redirect_stdout(out), redirect_stderr(err):
            rc = mod.main()
    finally:
        sys.argv = saved_argv
        if saved_dd is None:
            sys.modules.pop("decision_dept", None)
        else:
            sys.modules["decision_dept"] = saved_dd
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {"inserted": [v for _, v in yt.inserted],
            "videos_list_calls": yt.videos_list_calls,
            "stdout": out.getvalue(), "stderr": err.getvalue(), "rc": rc, "src": src}
