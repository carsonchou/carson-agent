#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_playlists 正式模式的離線模擬器 —— 不連網、不碰正式機任何檔案。

為什麼不自己抄一份 insert 迴圈來測:抄本會跟著產線一起漂,而漂掉的時候測試照樣綠
(memory fix-breaks-its-own-instrument)。這支是**把 scripts/build_playlists.py 的原始碼
直接 exec 起來跑真的 main()**,只把會寫盤/連網的出口換掉。

🔴 2026-09-14 修正(總督導裁決,結案條件④):本支第一版**只導了一個出口**,
main() 結尾的 log_ops 沒攔,於是每跑一輪就往正式機 STUDIO/ops_log.txt append 一行
「雙主軸分群完成:AI×交易+73, 台股量化+133, EP實測+32(本次額度用罄)」——
那一行同時謊報三件事(分群做了、片加進去了、額度用完了),而那幾輪根本沒連網、沒插任何片。
ops_log.txt 是全廠「單一心跳時間軸」,daily_check / daily_health / hr_dept / cloud_status /
control_center 都在讀它做判斷,所以那不是「多幾行日誌」,是餵假心跳。
而 .gitignore 忽略整個 STUDIO/ ⇒ git status --porcelain **看不見**,要靠 sha1+size+mtime 才看得到。
教訓(memory web-center-test-prod-misfire 同形):**隔離邊界是「被呼叫函式的整個依賴集合」,
不是「我想到的那一個」。**

build_playlists.main() 依賴集合裡**所有會寫盤/對外的出口**,每一個都答三件事:
**路徑常數叫什麼 / 有沒有被導開 / 有沒有對應的斷言**(總督導 2026-09-14 §3,現況為當日實查):

  ① STUDIO/playlists.json
     路徑常數:build_playlists.PLAYLISTS_STATE(寫入點是 main() 結尾的 .write_text 整檔覆寫)
     導開:exec 完立刻 mod.PLAYLISTS_STATE = 暫存副本
     斷言:_snapshot_studio 前後比對(playlists.json 在 WATCHED 裡,連 sha1 一起比)
  ② STUDIO/ops_log.txt  【本次新修的缺陷】
     路徑常數:ops.OPS(寫入點是 ops.log_ops 裡的 OPS.open("a");同一函式還會 OPS.parent.mkdir)
     導開:**兩層** —— 保險層 fake_ops.OPS → 暫存檔;意圖層 log_ops 攔掉只記進 ops_calls
     斷言:(a) assert fake_ops.OPS != REAL_OPS_LOG;(b) 被測模組的 log_ops 必須 is 我們那個假的;
            (c) _snapshot_studio 前後比對;(d) run_all.py 另用**位元組偏移量**量正式機新增段落
  ③ YouTube API(憑證檔 + 連網)
     路徑常數:decision_dept.yt_service(build_playlists 在 ensure_playlist 內 import)
     導開:sys.modules["decision_dept"] 換成假模組,回傳 FakeYT(全離線)
     斷言:FakeYT 只實作真的會被呼叫的那幾支,沒實作的呼叫會 AttributeError 當場炸,不靜默回空
  ④ 對外寫入:playlistItems().insert / playlists().insert(公開播放清單)
     路徑常數:無(走 ③ 的 service 物件)
     導開:FakeYT 只記在記憶體的 inserted / _items
     斷言:run_all.py 的 ①②③④ 全部拿 inserted 當判準;真跑過就會有網路例外
  ⑤ STUDIO/uploaded_ledger.json
     路徑常數:build_playlists.LEDGER —— **唯讀,全檔沒有寫入點**
     導開:故意不導(「09-17 那一輪會插哪些片」本來就該由真帳本決定)
     斷言:在 WATCHED 裡,_snapshot_studio 前後比 sha1 ⇒ 它要是被寫了會當場翻紅
  ⑥ stdout / stderr
     路徑常數:無  導開:redirect 到 StringIO,不落盤  斷言:判準直接讀回傳的 stdout/stderr
  ⑦ sys.path / sys.argv(build_playlists.py 開頭會 sys.path.insert(scripts/))
     不是寫盤,是全域副作用  導開:跑完在 finally 裡原樣還原  斷言:無(還原是無條件的)

  以上之外,build_playlists.py 全檔 grep open( / write_text / write_bytes / .write( /
  json.dump / os.replace / mkdir 沒有其他命中;ops.py 只 import datetime 與 pathlib。

🔴 不准只信這份清單:每次 simulate() 前後會對 STUDIO/ 直屬檔做一次快照比對
(全部檔案的 size+mtime_ns,加上四個重點檔的 sha1),有任何差異就丟 IsolationLeak。
下一次有人加了新的寫盤相依,會在這裡當場翻紅,而不是安靜地污染正式機。

mutate 參數收一個 (str)->str 的函式,用來做突變列:改完的原始碼跑出來如果測試還是綠,
表示那條判準根本沒在看那段程式碼。
"""
import hashlib
import importlib.util
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
OPS_SRC = BASE / "scripts" / "ops.py"
STUDIO = BASE / "STUDIO"
REAL_STATE = STUDIO / "playlists.json"
REAL_OPS_LOG = STUDIO / "ops_log.txt"               # 🔴 正式機心跳時間軸,本支絕不能碰到

# 重點檔另外比 sha1(size+mtime 有可能同秒同大小地被改掉)。
WATCHED = ["ops_log.txt", "playlists.json", "uploaded_ledger.json", "playlist_engine.json"]


class IsolationLeak(AssertionError):
    """模擬跑完之後,正式機 STUDIO/ 有檔案被動到。"""


def _snapshot_studio():
    """STUDIO/ 直屬檔的 (size, mtime_ns),重點檔另加 sha1。不遞迴 —— 本路徑只寫得到直屬層。"""
    snap = {}
    for p in sorted(STUDIO.glob("*")):
        if not p.is_file():
            continue
        st = p.stat()
        sha = None
        if p.name in WATCHED:
            sha = hashlib.sha1(p.read_bytes()).hexdigest()
        snap[p.name] = (st.st_size, st.st_mtime_ns, sha)
    return snap


def _diff_studio(before, after):
    names = sorted(set(before) | set(after))
    out = []
    for n in names:
        b, a = before.get(n), after.get(n)
        if b != a:
            out.append(f"{n}: 前={b} 後={a}")
    return out


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


def simulate(privacy=None, max_add=10, default_privacy="public", mutate=None,
             intercept_log_ops=True):
    """回傳 dict:inserted / videos_list_calls / ops_calls / ops_file_lines / stdout / stderr / rc / src。

    兩層隔離(總督導 2026-09-14 §2 第二段),缺一不可:
      保險層 = ops.OPS 指到暫存檔(哪天有人繞過 log_ops 直接開 OPS 寫,也還在暫存)
      意圖層 = log_ops 本身攔掉(呼叫只記進 ops_calls)
    intercept_log_ops=False 只拿掉**意圖層**,保險層照舊 ⇒ 真的 ops.log_ops 會把行寫進
    **暫存檔**,正式機零寫入。那就是 §2 第三段的陽性對照:
      證明①沒攔的時候真的會寫(不是本來就不會寫);②量新增段落的量法看得見新增。
    """
    src = SRC.read_text(encoding="utf-8")
    if mutate is not None:
        src = mutate(src)

    state = json.loads(REAL_STATE.read_text(encoding="utf-8"))
    yt = FakeYT(state, privacy or {}, default_privacy)

    tmpdir = Path(tempfile.mkdtemp(prefix="bp_sim_"))
    tmp_state = tmpdir / "playlists.json"
    shutil.copy2(REAL_STATE, tmp_state)

    ops_calls = []

    fake_dd = types.ModuleType("decision_dept")
    fake_dd.yt_service = lambda *a, **k: yt

    # 🔴 兩層隔離。保險層:ops.OPS 指到暫存檔。意圖層:log_ops 攔掉。
    tmp_ops = tmpdir / "ops_log.txt"
    fake_ops = types.ModuleType("ops")
    fake_ops.OPS = tmp_ops
    fake_ops.tail = lambda n=40: ""
    if intercept_log_ops:
        fake_ops.log_ops = lambda stage, msg: ops_calls.append((stage, msg))
    else:
        # 陽性對照:載入**真的** scripts/ops.py(不手抄一份寫檔邏輯進儀器 ——
        # memory fix-breaks-its-own-instrument),只把它的 OPS 常數指到暫存檔。
        _spec = importlib.util.spec_from_file_location("ops_real_for_sim", OPS_SRC)
        _real_ops = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real_ops)
        _real_ops.OPS = tmp_ops
        fake_ops.log_ops = _real_ops.log_ops

    # 🔴 §2 第二段要求的那一行斷言:被測模組看到的 ops 路徑不可以是真的那個。
    # (memory web-center-test-prod-misfire:同族第二次出事,第一版與第二版的差別只有這一行。)
    assert fake_ops.OPS.resolve() != REAL_OPS_LOG.resolve(), \
        f"ops.OPS 指到正式機心跳檔了:{fake_ops.OPS}"

    saved_dd = sys.modules.get("decision_dept")
    saved_ops = sys.modules.get("ops")
    sys.modules["decision_dept"] = fake_dd
    sys.modules["ops"] = fake_ops
    saved_argv = sys.argv
    saved_path = list(sys.path)

    before = _snapshot_studio()

    mod = types.ModuleType("bp_under_test")
    mod.__file__ = str(SRC)
    out, err = io.StringIO(), io.StringIO()
    try:
        exec(compile(src, str(SRC), "exec"), mod.__dict__)
        mod.PLAYLISTS_STATE = tmp_state          # 🔴 會覆寫真 playlists.json 的那一行,指到暫存

        # 🔴 儀器自檢:確認被測模組綁到的真的是假 log_ops。
        # build_playlists 的 import 包在 try/except 裡,失敗會**靜默**退回 no-op stub ——
        # 那樣也不會寫盤,但原因是錯的(等於沒測到攔截)。這裡要它說出來。
        if getattr(mod, "log_ops", None) is not fake_ops.log_ops:
            raise IsolationLeak(
                "被測模組的 log_ops 不是假的那個(可能 import ops 失敗退回 no-op stub,"
                "或 build_playlists 改了取得日誌的方式)⇒ 攔截沒成立,不要相信本輪結果。")

        sys.argv = ["build_playlists.py", "--max", str(max_add)]
        with redirect_stdout(out), redirect_stderr(err):
            rc = mod.main()
    finally:
        sys.argv = saved_argv
        sys.path[:] = saved_path
        for name, saved in (("decision_dept", saved_dd), ("ops", saved_ops)):
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved
        # 暫存的 ops_log 要在砍掉暫存目錄之前讀出來 —— 陽性對照的證據就是這幾行。
        ops_file_lines = (tmp_ops.read_text(encoding="utf-8").splitlines()
                          if tmp_ops.exists() else [])
        shutil.rmtree(tmpdir, ignore_errors=True)

    changed = _diff_studio(before, _snapshot_studio())
    if changed:
        raise IsolationLeak(
            "模擬跑完之後正式機 STUDIO/ 有檔案被動到 —— 依賴集合裡有沒導走的寫盤出口:\n  "
            + "\n  ".join(changed)
            + "\n(同一時間正式排程也在寫 STUDIO 會造成一樣的畫面;可以用 mtime 對 jobout 排除,"
              "但**預設當成洩漏**,不要預設是別人寫的。)")

    return {"inserted": [v for _, v in yt.inserted],
            "videos_list_calls": yt.videos_list_calls,
            "ops_calls": ops_calls,
            "ops_file_lines": ops_file_lines,
            "stdout": out.getvalue(), "stderr": err.getvalue(), "rc": rc, "src": src}
