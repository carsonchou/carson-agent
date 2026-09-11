#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_crosscheck_regression.py — 定期證明**互查**還抓得到它的三個已知失效。

## 為什麼存在(2026-09-11)

`watch_crosscheck.py` 上線當天(09-10)就被獨立驗證抓到三個失效,而三個**全部往「不叫」倒**:

| 代號 | 失效 | 沉默的原因 |
|---|---|---|
| **M1** | 互查自己寫進 log 的告警行,長得**完全像一筆排程讀數** | 下一次互查把「我昨天叫過」讀成「昨天有排程跑」 |
| **M2** | `[MANUAL]` 註記**隔天**才追加 ⇒ 日期不相等 ⇒ 相鄰降級不發生 | 註記行只帶「我被寫下的時間」,不帶「我在指誰」 |
| **M3** | 互查收尾寫在 `try/finally` **外面** ⇒ `main()` 丟例外時控制流走不到 | 整天不執行,而且沒有任何訊號 |

M1 的因果鏈是**閉合的**:會有人補跑,正是因為那天有哨沉默 ⇒ 那天互查必然叫過
⇒ 那天的 log 必然多出那一行。09-10 躲過純粹因為 18:05 補跑時互查還沒上線。

### 🔴 2026-09-11 追加的第四個:M1c —— **M1 只修了兩端裡的一端**

`6aadb844` 給 `xchk_broken()`(收尾自己爆掉時的最後一道留痕)加了一條寫進 `LOG` 的路,
而那一行**沒有帶 `[XCHK] ` 前綴** ⇒ 它以 `[` + 時間戳開頭 ⇒ 命中 `_TS`、躲過
`_SKIP_PREFIXES` ⇒ 同伴把它讀成「今天有一筆排程讀數」而閉嘴。
因果鏈同樣閉合:`xchk_broken()` 觸發的前提正是「今天沒有真讀數」。

**為什麼本檔當時沒抓到**:M1 那兩格用 `pref = after.XCHK_PREFIX` **自己合成**語料
⇒ 驗的是「互查收到一行已經加對前綴的字串時,判得對不對」,
沒有任何一格問過「哨那邊到底有沒有加」。⇒ M1c 改成拿 `xchk_broken()`
**真的落到檔案裡的位元組**當語料。
⚠️ 演習那條路**結構上**驗不到:`SELFTEST` 會加 `[DRILL] `,那本來就在 `_SKIP_PREFIXES` 裡。

⇒ 而三個都修完了之後,還是需要有東西**定期證明它們沒有回來**:
memory `gate-blind-while-target-evolves`「閘門上線後要有東西定期證明它還抓得到已知案例」。
同一條 memory 的另一半:**陽性對照要用真案例,不要用合成 fixture** ——
所以本檔的語料一律從 `docs/ops/*-watch.log` 的**真內容**截出來,只在尾巴接一行。

## 這支檢查什麼、不檢查什麼
- 檢查:`crosscheck()` 的判決(叫 / 靜音),以及三支哨 `__main__` 的**控制流**。
- 控制流那一段**不做替身**:直接 `exec` 三支哨檔案裡那段 `if __name__` 的**原文**,
  其餘全換 stub。受測物因此是磁碟上真的那幾行,不是重打的一份。
- 不檢查:哨自己的判準(那是 `watch_drill_regression.py` 的事)。
- 不碰正式 log:語料寫到 `tempfile.mkdtemp()`,`WATCHES[*]["log"]` 改指過去。

## 陰性對照
三支都正常跑到 due ⇒ **必須靜音**。少了這一格,「該叫的都叫了」和「這條檢查恆叫」分不開。

## 已知還沒好的(母體③,照實列在這裡,不要當成已修)
- 補跑**沒帶** `WATCH_MANUAL=1` 時,M2 那個形狀**依然靜音**。本檔把它當成
  「期待靜音」記錄下來 —— 它是現況,不是通過。
- 🔴 **相鄰規則已經廢掉**(2026-09-11):它在產線真實行序下**永遠不觸發** ⇒ 靜音。
  現在是「每一則 `[MANUAL]` 註記認領同一天的一筆讀數,不看位置」,見 M1b 那一節。
  剩下的不健全:同一天兩筆補跑只配一則註記時,仍會剩一筆被當成排程讀數 ⇒ 仍靜音;
  出口是 `WATCH_MANUAL=1`(那條路上讀數行自己說得出它是誰)。

## 用法
    python scripts/watch_crosscheck_regression.py
    python scripts/watch_crosscheck_regression.py --before <dir>
        # <dir> 內有動手前備份的 watch_crosscheck.py(命名 xchk.before.py)與
        # <哨名>.before.py,則額外跑「修之前」那幾欄,把病灶重現出來並排。
        # 沒給就跳過那幾欄,並在輸出裡講明跳過了。

## 輸出
正向輸出:**每次跑都寫一行** `docs/ops/watch-crosscheck-regression.log`,全過也寫
—— 「沒有輸出」因此永遠是異常(和三支哨自己同一個設計)。
exit 0 = 全部符合期待;1 = 有一格不符合(代表**互查壞了**,不是產線壞了);
2 = 語料建不起來(真 log 的長相變了 ⇒ 本檔的假設過期,先來改本檔)。
"""
from __future__ import annotations

import datetime
import importlib.util
import inspect
import io
import pathlib
import random
import shutil
import sys
import tempfile
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
OPS = REPO / "docs" / "ops"
LOG = OPS / "watch-crosscheck-regression.log"

LOGS = {"seeding": OPS / "seeding-watch.log",
        "narration": OPS / "narration-compliance-watch.log",
        "quota": OPS / "quota-ceiling-watch.log"}
WATCH_FILES = [("seeding_watch", "seeding"),
               ("narration_compliance_watch", "narration"),
               ("quota_ceiling_watch", "quota")]

# 判決時刻。兩個都要,因為 due_date 會因為「過沒過今天的 at+GRACE」而不同,
# 而 M1 / M2 各自只在其中一邊現形。
NOW_LATE = datetime.datetime(2026, 9, 11, 9, 0)    # 已過 08:00/08:10 ⇒ seeding/narration due=09-11
NOW_EARLY = datetime.datetime(2026, 9, 11, 7, 30)  # 還沒過 ⇒ 三支 due 都是 09-10


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# 🔴 2026-09-11:原本有 10 格是 `rows.append(...)` 而**沒有 print** ⇒ 讀者看到 10 行、
#    看到「20/20」。計分和印出必須是同一個動作,否則這支尺自己就是「檢查不會失敗」的一種:
#    看不到的格子沒有人能查證。所有格子一律走 add()。
def load_mut_src(src, name, tmpdir):
    """把改壞的原文寫成暫存檔再載進來 —— 模組層級的突變只能這樣做。

    和 `load()` 的差別:`load()` 載磁碟上的正本,這支載的是**故意改壞的副本**,
    而且一定寫在 tmpdir 裡,不准落在 repo(memory `write-truncates-before-it-fails`)。
    """
    q = tmpdir / (name + ".py")
    q.write_text(src, encoding="utf-8")
    return load(q, name)


def add(rows, name, expect, got, ok):
    rows.append((name, expect, got, ok))
    print(f"  {name:38s} 期待 {expect} / 實得 {got}  {'PASS' if ok else '🔴FAIL'}")


# 🔴 格數本身也要斷言:少了一格(某個 continue 提早跳掉、某個分支沒進去)在舊版會印成
#    「N/N 符合期待」,和真的全過長得一模一樣。這兩個數字改動時要連同理由一起改。
#    這兩個數一律**跑出來**,不要用加法推(推錯過兩次,而推錯的表現是「格數斷言自己過了」)。
#    2026-09-11:M4 一口氣多五格 × 三支哨 = +15,M1b 排列對照 +1 ⇒ 64→80 / 61→77,
#    兩個都是跑完之後抄下來的。
#    2026-09-11 下午:M0 簽章對照 +2、M1c 真輸出 +3 × 三支哨 = +9 ⇒ 80→91 / 77→88。
#    這兩個數同樣是**各跑一次抄下來的**(12:00 印 88、12:01 印 91),不是 77+11 加出來的
#    —— 加法在這裡推錯過兩次,而推錯的表現是「格數斷言自己過了」。
#    2026-09-11 12:04/12:05:M4 (6b) 補 (6) 自己的翻面突變 +3 ⇒ 88→91 / 91→94,一樣是抄的。
#    2026-09-11 12:16/12:17:M4 (10)(11) 回讀身分 +2 × 三支哨 = +6,
#    M5「notes」那格從**只在失敗時才存在**改成無條件一列 × 9 = +9
#    ⇒ 91→106 / 94→109。兩個數各跑一次抄下來的(12:16 印 106、12:17 印 109)。
#    ⚠️ 這兩個數今天已經換過三輪(77/80 → 88/91 → 91/94 → 106/109):
#       引用時請連時間一起引,只有最後一輪是現況。
EXPECT_ROWS = {True: 109, False: 106}   # key = 有沒有給 --before


# 🔴 2026-09-10~09-11 真的活在正式機上的那一版 `last_sched_date()` 迴圈,逐字保存。
# 它只降級「緊接在上一行」的那筆讀數,而產線每一次人工補跑的真實行序是
#     讀數 → 同一次執行 finally 寫的 [XCHK] 告警 → (之後) [MANUAL] 註記
# ⇒ 中間那行把 prev_was_sched 打掉 ⇒ 降級永不觸發 ⇒ **靜音**,且和更早那版逐位相同。
# 留著它是為了當**陽性對照**:新規則要能在同一份語料上叫出來,而這一版必須靜音。
# ⚠️ 不要「順手更新」這段字 —— 它是歷史紀錄,不是活的碼。
HIST_ADJACENT = """    sched = []
    manual_dates = []
    prev_was_sched = False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_SKIP_PREFIXES):
            prev_was_sched = False
            continue
        m = _MANUAL_TS.match(line)
        if m:
            manual_dates.append(m.group(1))
            if prev_was_sched and sched and sched[-1] == m.group(1):
                sched.pop()
            prev_was_sched = False
            continue
        m = _TS.match(line)
        if m:
            sched.append(m.group(1))
            prev_was_sched = True
        else:
            prev_was_sched = False
"""


def block(path):
    """取出 `if __name__ == "__main__":` 起到檔尾的**原文**。"""
    text = io.open(path, encoding="utf-8").read()
    key = 'if __name__ == "__main__":'
    if key not in text:
        raise KeyError(f"{path.name} 裡找不到 {key}")
    return text[text.index(key):]


class _Err:
    """友善的假 stderr:永遠可寫,`encoding` 是 `utf-8`(什麼都編得進去)。

    ⚠️ 2026-09-11 更正一句**已經不成立的**文件:這裡原本寫「沒有 `encoding` 屬性」,
       而下面第一行就是 `encoding = "utf-8"`。文件寫的不變量比程式碼**寬**,
       而讀的人會照文件去推論(例如以為 `getattr(sys.stderr, "encoding", None)`
       在這個 stub 上會走 fallback 分支 —— 不會)。
       同形狀:memory `static-reading-vs-runtime-behaviour`。

    🔴 2026-09-11:**本類別自己是一個「不可能失敗的檢查」**(memory
    verification-that-cannot-fail)。舊版 M3 兩格斷言 `"[XCHK-BROKEN]" in err`,
    用的就是它 —— 而正式機的 stderr 是 `pythonw.exe` 給的:要嘛 `None`,
    要嘛 `encoding='cp950'`。兩種都不會讓那行字出現,而這個 stub 兩種都不重現
    ⇒ **產線靜默,而測試全綠**。所以下面補了 `_ErrCp950` 與 stderr_mode="none"。
    """

    encoding = "utf-8"

    def __init__(self):
        self.buf = ""

    def write(self, s):
        self.buf += s

    def flush(self):
        pass


class _ErrCp950(_Err):
    """重現獨立驗證實測到的那一支:`pythonw` 有繼承 handle 時 encoding 是 cp950。

    cp950 編不了 emoji ⇒ 寫入時拋 UnicodeEncodeError。而本 repo 的例外訊息到處帶 🔴。
    """

    encoding = "cp950"

    def write(self, s):
        s.encode("cp950")          # 編不了就拋 —— 這是實測行為,不是模擬
        self.buf += s


def _make_err(mode):
    return {"ok": _Err, "cp950": _ErrCp950, "none": lambda: None}[mode]()


def func_src(path, name):
    """取出 `def name(` 起、到下一個頂層敘述為止的**原文**。

    和 `block()` 同一個理由:測的是磁碟上那份位元組,不是我重打一次的版本。
    """
    text = io.open(path, encoding="utf-8").read()
    key = "def " + name + "("
    if key not in text:
        raise KeyError(path.name + " 裡找不到 " + key)
    lines = text[text.index(key):].split(chr(10))
    out = [lines[0]]
    for ln in lines[1:]:
        if ln and not ln[0].isspace():
            break
        out.append(ln)
    return chr(10).join(out)


def xchk_broken_trial(fsrc, stderr_mode, log_path, what=None, selftest=False,
                      temp_to=None):
    """exec 真的 `xchk_broken` 原文,回 `(log 內容, 它拋出來的東西, stderr 內容, 回傳值)`。

    log 一律寫到**暫存目錄**,不是 repo 裡的常駐 log —— 演習不可以往真 log 追加行。
    `what` 預設帶一個含 emoji 的例外:cp950 編不了它,那正是要驗的那一格。

    `temp_to`:把第三條備援路(`%TEMP%`)導到指定目錄。**一定要給**,否則演習會往
    真的 `%TEMP%` 寫檔,而那是別人的地盤。做法是設 `tempfile.tempdir` ——
    `gettempdir()` 會把結果快取住,只改環境變數在第二次呼叫之後就沒用了。

    🔴 第四個回傳值是 `xchk_broken()` **自己的回傳值**(留成痕的那個路徑,或 None)。
       少了它,斷言只能寫成「沒拋例外 + log 裡有那個字串」,而那個條件連「把
       `[XCHK-BROKEN]` 這個標記改名」這種突變都殺不掉(第四輪驗證【3/5】實測:
       改名之後 log 照樣落 172 bytes,而那一格照樣說「突變被殺掉」)。
    """
    if what is None:
        what = RuntimeError("🔴 模擬:record 自己爆了")
    err = _make_err(stderr_mode)
    # `pathlib` 要在 exec 的全域裡 —— 三支哨都在模組層 import 它,而 xchk_broken 的
    # 第三條備援路用得到。不給的話那條路會靜靜少掉一條,而測試看起來照樣綠。
    g = {"datetime": datetime, "pathlib": pathlib,
         "sys": types.SimpleNamespace(stderr=err),
         "LOG": log_path, "SELFTEST": selftest, "print": print}
    exec(compile(fsrc, "<xchk_broken>", "exec"), g)
    raised, ret = None, None
    saved_tmp = tempfile.tempdir
    if temp_to is not None:
        temp_to.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(temp_to)
    try:
        ret = g["xchk_broken"](what)
    except BaseException as e:     # noqa: BLE001 —— 「它有沒有拋」本身就是受測結果
        raised = e
    finally:
        tempfile.tempdir = saved_tmp
    try:
        # 🔴 `errors="replace"` 不是裝飾:這支尺的突變列會故意把寫入端改成 cp950,
        #    落地的就是**解不開的位元組**。沒有 `errors=` 的話這裡拋 UnicodeDecodeError,
        #    而它不是 OSError ⇒ 從 `xchk_broken_trial` 逃出去 ⇒ **整份回歸當場中斷**,
        #    一格紅的變成一份 traceback(memory `fix-breaks-its-own-instrument`:
        #    修法打壞自己的量尺)。except 一併放寬,是因為「讀不出來」在這裡永遠只代表
        #    受測結果,不代表測試環境壞了。
        got = (log_path.read_text(encoding="utf-8", errors="replace")
               if log_path.exists() else "")
    except (OSError, UnicodeDecodeError, ValueError):
        # 演習會故意把主 log 做成**目錄**(驗第二條備援路)⇒ 這裡讀不到是預期的,
        # 意思就是「主通道沒東西」,不是測試環境壞了。
        got = ""
    return got, raised, ("" if err is None else err.buf), ret


def _stub_watch_crosscheck(calls, xchk_exc):
    """做出 `watch_crosscheck` 的替身。

    🔴 **抽到模組層是為了讓簽章對照拿得到它**(2026-09-11,獨立驗證指出):
       這支尺的賣點是「exec 磁碟上的真原文」,但真原文呼叫的是**我手寫的替身**,
       而那份替身的簽章從來沒有被機械地和真貨比對過。上一次同形狀的事故是
       真呼叫點多一個參數 ⇒ 20 格裡有 13 格量到的是「替身跟不上」而不是控制流,
       而 commit 訊息照樣寫 20/20(memory `fix-breaks-its-own-instrument`)。
       現在 M0 那一節用 `inspect.signature` 把兩邊釘在一起。
    """

    def crosscheck_tail(rc, self_key, record, alert, now=None, on_broken=None):
        # 🔴 `on_broken` 一定要在簽章裡,而且要**記下來**:呼叫端忘了傳的話,
        #    最後一道留痕就退回本模組那條守衛版 stderr —— 在 pythonw 下等於沒有留痕。
        #    2026-09-11 實測:這個 stub 少了 on_broken 參數時,三支哨的呼叫直接 TypeError,
        #    被 finally 的 except 吞成 rc=4 ⇒ 「互查被呼叫 0 次」。所以這格會翻面,不是恆過。
        # ⚠️ 參數名 `self_key` 是**跟著真貨抄的**,不是隨手取的 —— M0 那格比的是
        #    整個 `inspect.signature`,名字不一樣就會紅(三支哨目前用位置傳,
        #    所以名字錯今天不會出事;但「今天不會出事」不是不變量)。
        calls.append((rc, self_key, on_broken))
        if xchk_exc:
            raise xchk_exc
        return rc

    stub = types.ModuleType("watch_crosscheck")
    stub.crosscheck_tail = crosscheck_tail
    stub.manual_prefix = lambda: ""
    return stub


def control_flow_trial(src, main_rc=0, main_exc=None, xchk_exc=None, iso=None,
                       stderr_mode="ok"):
    """exec 一段真的 `__main__` 原文,回 `.calls / .exc / .err / .broken`。

    `stderr_mode` 決定假 stderr 的形狀("ok" / "cp950" / "none");預設 "ok" 是
    **最不像正式機**的那一種,所以要靠呼叫端明講,不要靠預設值。
    `broken` 記 `xchk_broken()` 被呼叫幾次 —— 收尾自己壞掉時的留痕現在走它,不走 stderr。
    """
    calls, err, broken = [], _make_err(stderr_mode), []

    stub = _stub_watch_crosscheck(calls, xchk_exc)
    saved = sys.modules.get("watch_crosscheck")
    sys.modules["watch_crosscheck"] = stub

    fake_sys = types.SimpleNamespace(
        stderr=err, argv=["regression"],
        exit=lambda c=0: (_ for _ in ()).throw(SystemExit(c)))

    def _main():
        if main_exc:
            raise main_exc
        return main_rc

    g = {"__name__": "__main__", "sys": fake_sys, "main": _main,
         "record": lambda *a, **k: None, "alert": lambda *a, **k: None,
         "say": lambda *a, **k: None, "swallow_epilogue": lambda: None,
         "SELFTEST": iso is not None, "SELFTEST_MODE": "up", "DRILL_FACT_MODES": (),
         "_drill_setup": lambda *a: None, "_drill_teardown": lambda: iso,
         "xchk_broken": lambda what: broken.append(what),
         "print": lambda *a, **k: (k["file"].write(" ".join(map(str, a)) + chr(10))
                                  if k.get("file") is err else None)}
    out = None
    try:
        exec(compile(src, "<main-block>", "exec"), g)
    except BaseException as exc:      # noqa: BLE001 —— 逃出來的東西本身就是受測結果
        out = exc
    finally:
        if saved is not None:
            sys.modules["watch_crosscheck"] = saved
        else:
            sys.modules.pop("watch_crosscheck", None)
    return types.SimpleNamespace(calls=calls, exc=out, broken=broken,
                                 err=("" if err is None else err.buf))


class Corpus:
    """從真 log 截語料。真 log 的長相變了就 raise —— 那代表本檔的假設過期了。"""

    def __init__(self):
        self.raw = {}
        for key, path in LOGS.items():
            self.raw[key] = [ln for ln in path.read_text(encoding="utf-8",
                                                         errors="replace").splitlines() if ln.strip()]
        self.read_s = self._find("seeding", lambda ln: ln.startswith("[2026-09-10 18:05]"))
        self.note_s = self._find("seeding", lambda ln: ln.startswith("[MANUAL]"))
        self.read_n = self._find("narration", lambda ln: ln.startswith("[2026-09-10 18:05]"))
        self.note_n = self._find("narration", lambda ln: ln.startswith("[MANUAL]"))
        body = self._find("seeding", lambda ln: "守望互查:有哨沉默了" in ln)
        self.xchk_body = body.split("] ", 1)[1]

    def _find(self, key, pred):
        hits = [ln for ln in self.raw[key] if pred(ln)]
        if not hits:
            raise KeyError(f"{LOGS[key].name}:找不到語料所需的行(真 log 長相變了)")
        return hits[-1]

    def upto(self, key, prefix):
        idx = [i for i, ln in enumerate(self.raw[key]) if ln.startswith(prefix)]
        if not idx:
            raise KeyError(f"{LOGS[key].name}:找不到以 {prefix!r} 開頭的行")
        return list(self.raw[key][:max(idx) + 1])

    def quota_ok(self):
        """quota 09-10 15:20 正常跑過 —— 三個情境都不動它,它是設計唯一的支點。"""
        return [ln for ln in self.raw["quota"] if not ln.startswith(("[DRILL]", "[XCHK]"))]


def make_runner(tmpdir):
    def run(mod, logs, now, self_key="seeding"):
        for key, lines in logs.items():
            path = tmpdir / f"{key}.log"
            path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
            mod.WATCHES[key]["log"] = path
        return mod.crosscheck(self_key, now=now)
    return run


def main():
    argv = sys.argv[1:]
    before_dir = None
    if "--before" in argv:
        before_dir = pathlib.Path(argv[argv.index("--before") + 1])

    now_stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="xchk-regress-"))
    try:
        try:
            c = Corpus()
        except KeyError as exc:
            record(f"[{now_stamp}] 🔴 互查回歸:**語料建不起來** —— {exc}。"
                   f"這代表真 log 的長相變了、本檔的假設過期,先來改本檔,不要當成互查壞了。")
            return 2

        after = load(REPO / "scripts" / "watch_crosscheck.py", "xchk_after")
        before = None
        if before_dir:
            cand = before_dir / "xchk.before.py"
            if cand.exists():
                before = load(cand, "xchk_before")
            else:
                print(f"⚠️ --before 給了 {before_dir},但裡面沒有 xchk.before.py ⇒ 跳過「修之前」欄")

        run = make_runner(tmpdir)
        rows = []          # (名稱, 期待, 實得, 通過?)

        def case(name, mod, logs, now, expect):
            ok, msg = run(mod, logs, now)
            got = "靜音" if ok else "叫"
            rows.append((name, expect, got, got == expect))
            print(f"  {name:38s} 期待 {expect:2s} / 實得 {got:2s}  "
                  f"{'PASS' if got == expect else '🔴FAIL'}")
            return msg

        quota = c.quota_ok()

        # ---- M0:量尺自己的替身,簽章必須和真貨對得上 ----
        # 🔴 這一節量的不是產線,是**本檔自己**。M3 的賣點是「exec 磁碟上的真原文」,
        #    但那段原文呼叫到的 `watch_crosscheck` 是我手寫的替身 ——
        #    替身跟不上真貨時,M3 每一格量到的都是「替身壞了」,而它們照樣印 PASS/FAIL,
        #    分不出是哪一件事。上一次同形狀:真呼叫點多一個參數 ⇒ 20 格有 13 格量錯,
        #    而 commit 照樣寫 20/20(memory `fix-breaks-its-own-instrument`)。
        print("M0 替身簽章 vs 真貨(替身跟不上時,M3 每一格量到的都是替身,不是控制流)")
        _stub = _stub_watch_crosscheck([], None)
        for _fn in ("crosscheck_tail", "manual_prefix"):
            _sig_s = str(inspect.signature(getattr(_stub, _fn)))
            _sig_r = str(inspect.signature(getattr(after, _fn)))
            add(rows, f"M0 stub.{_fn} 簽章 == 真貨", _sig_r, _sig_s, _sig_s == _sig_r)

        # ---- M1:互查自己的告警行 ----
        print("M1 互查自己寫的告警行(語料=真 log 截到 09-10 補跑+註記,尾巴接一次非演習告警)")
        for tag, mod, pref in [("修之前(無前綴)", before, ""),
                               ("修之後([XCHK] 前綴)", after, after.XCHK_PREFIX)]:
            if mod is None:
                print(f"  {'M1 ' + tag:38s} 跳過(沒給 --before)")
                continue
            logs = {"seeding": c.upto("seeding", "[MANUAL]")
                    + [f"{pref}[2026-09-11 09:00] {c.xchk_body}"],
                    "narration": c.upto("narration", "[MANUAL]")
                    + [f"{pref}[2026-09-11 09:00] {c.xchk_body}"],
                    "quota": quota}
            case("M1 " + tag, mod, logs, NOW_LATE, "靜音" if mod is before else "叫")

        # ---- M1b:降級規則對「[XCHK] 行的位置」必須免疫 ----
        # 🔴 這一節是第三輪獨立驗證【2/5】的產物,而它抓到的是**我的語料排除掉了唯一會
        #    出事的排列**。上面 M1 的語料是「讀數 → [MANUAL] 註記 → 隔天的 XCHK」,
        #    而產線真實行序是「讀數 → 同一次執行 finally 寫的 XCHK → (之後)註記」。
        #    舊的相鄰降級被中間那行打掉 ⇒ 靜音,且和修之前逐位相同。實測(問 last_sched_date):
        #        讀數→註記→XCHK  ⇒ ('2026-09-09','2026-09-10')  會叫
        #        讀數→XCHK→註記  ⇒ 舊碼 ('2026-09-10','2026-09-10') ← **靜音**
        #    ⚠️ 判準必須用 NOW_EARLY(due=09-10):用 NOW_LATE 時 due=09-11,不管有沒有
        #    降級都會叫 ⇒ 這一節會變成恆過。上面 M1 兩格用 NOW_LATE,正是它漏掉的原因之一。
        print("M1b 降級對 [XCHK] 行的位置免疫(語料=真 log,三種位置,NOW_EARLY)")
        xchk_same_run = f"{after.XCHK_PREFIX}[2026-09-10 18:05] {c.xchk_body}"
        xchk_prev_day = xchk_same_run.replace("2026-09-10 18:05", "2026-09-09 18:05")

        def m1b_logs(order):
            out = {"quota": quota}
            for key, note in (("seeding", c.note_s), ("narration", c.note_n)):
                head = c.upto(key, "[2026-09-10 18:05]")
                if order == "note_then_xchk":       # 我原本語料的形狀
                    out[key] = head + [note, xchk_same_run]
                elif order == "xchk_between":       # 🔴 產線真實形狀
                    out[key] = head + [xchk_same_run, note]
                elif order == "xchk_both_sides":    # 前一天也叫過、這次也叫過
                    out[key] = [xchk_prev_day] + head + [xchk_same_run, note]
                else:
                    raise AssertionError(order)
            return out

        m1b_verdicts = {}
        for order, label in (("note_then_xchk", "註記在 XCHK 之前"),
                             ("xchk_between", "XCHK 夾在讀數與註記之間(產線)"),
                             ("xchk_both_sides", "讀數前後都有 XCHK 行")):
            m1b_verdicts[order] = case(f"M1b {label}", after,
                                       m1b_logs(order), NOW_EARLY, "叫")
        # 三格判決一致還不夠 —— 連**告警內文**都要逐字相同,否則「同判決」可能是兩個
        # 不同理由碰巧撞到同一個字。不變量宣稱「輸出只依賴每個日期有幾筆讀數、幾則註記」,
        # 那就拿輸出本身來對。
        _uniq = set(m1b_verdicts.values())
        add(rows, "M1b 三種位置的告警內文逐字相同", "一致",
            "一致" if len(_uniq) == 1 else f"分岔 {len(_uniq)} 種", len(_uniq) == 1)

        # 常駐突變列:承重的是 last_sched_date() 尾巴那段「註記認領同一天的一筆讀數」。
        # 把認領拆掉 ⇒ 09-10 那筆不再被降級 ⇒ 「產線」那一格必須翻成靜音。
        # 少了這一列,「三格都叫」和「這三格恆叫」分不開(memory load-bearing-line-needs-mutation)。
        _claim = ("    for _d in manual_dates:" + chr(10)
                  + "        for _i in range(len(sched) - 1, -1, -1):" + chr(10)
                  + "            if sched[_i] == _d:" + chr(10)
                  + "                del sched[_i]" + chr(10)
                  + "                break" + chr(10))
        _src = (REPO / "scripts" / "watch_crosscheck.py").read_text(encoding="utf-8")
        if _claim not in _src:
            raise KeyError("突變找不到「註記認領」那段 —— last_sched_date() 改過了,先來改本檔")
        mut_claim = load_mut_src(_src.replace(_claim, "    pass" + chr(10)),
                                 "xchk_mut_claim", tmpdir)
        case("突變 拆掉註記認領 ⇒ 產線行序翻靜音", mut_claim,
             m1b_logs("xchk_between"), NOW_EARLY, "靜音")

        # 🔴 陽性對照,用**真案例的原碼**不是合成突變(memory gate-blind-while-target-evolves
        #    「陽性對照要用真案例」)。下面 HIST_ADJACENT 是 2026-09-10~09-11 真的活在正式機上
        #    的那一版 last_sched_date():「只降級**緊接在上一行**的那筆」。它必須在產線行序
        #    (讀數→XCHK→註記)下靜音、在我原本那個語料行序下照樣叫 —— 兩格合起來才說明
        #    「不是那一版壞掉,是我的語料選了它會過的那一排」。
        #    ⚠️ 這一段刻意不參數化:哪天 last_sched_date() 又改寫,下面的 `not in` 會擋住,
        #    逼下一個人自己判斷歷史對照還適不適用,而不是靜靜地量到別的東西。
        HIST_NEW = ("    for _d in manual_dates:" + chr(10) + "        for _i in range")
        if HIST_NEW not in _src:
            raise KeyError("歷史對照:認領那段不在了 ⇒ 本檔的歷史對照過期,先來改本檔")
        hist = load_mut_src(_src[:_src.index("    sched = []")] + HIST_ADJACENT
                            + _src[_src.index("    return (sched[-1] if sched else None,"):],
                            "xchk_hist_adjacent", tmpdir)
        case("歷史對照 相鄰版·產線行序 ⇒ 當年真的靜音", hist,
             m1b_logs("xchk_between"), NOW_EARLY, "靜音")
        case("歷史對照 相鄰版·我原本的語料行序 ⇒ 照樣叫", hist,
             m1b_logs("note_then_xchk"), NOW_EARLY, "叫")

        # 🔴 排列對照 —— 這一列補的是一句**曾經是假的**話。`watch_crosscheck.py` 的註解
        #    寫著「⇒ 回歸有一列洗牌對照釘住它」,而 2026-09-11 grep「洗牌 / shuffle /
        #    random」**零命中**:那一列從來沒有存在過。宣稱守衛存在而它不存在,比沒有守衛
        #    更糟 —— 下一個人會信那句話,然後在那個不變量上疊東西(memory
        #    `verification-that-cannot-fail` 第零種:期望不是規則,失效靜默)。
        #
        #    ⚠️ 補的時候順手量到:那句註解宣稱的不變量**本身太寬**。整份 log 亂序洗
        #    (含讀數行)⇒ 300 次量出 **91 種**不同內文,因為 `sched[-1]` 取的是
        #    「檔案裡最後出現」的讀數,不是日期最大的那筆。真的成立的是**窄版**:
        #    讀數行保持時序,而 `[XCHK]` 行與 `[MANUAL]` 註記行插在**任何位置**,
        #    判決與告警內文都逐字相同 —— 那正是 09-11 那個修法真正買到的東西。
        #    整個插入格 3,422 種 09-11 全跑過一次:判決全「叫」、內文 **1 種**(45 秒)。
        #    常駐列抽 150 種(~2 秒),seed 寫死 ⇒ 哪天翻紅,同一組位置重跑得出來。
        _rng = random.Random(20260911)
        _perm_heads = {k: c.upto(k, "[2026-09-10 18:05]") for k in ("seeding", "narration")}
        _perm_notes = {"seeding": c.note_s, "narration": c.note_n}
        _pn = min(len(v) for v in _perm_heads.values())
        _grid = [(i, j) for i in range(_pn + 1) for j in range(_pn + 2)]
        _pairs = [(_pn, _pn + 1)] + _rng.sample(_grid, 149)   # 第一個=M1b「產線」那格的形狀
        _base_msg = m1b_verdicts["xchk_between"]
        _perm_bad = None
        for _i, _j in _pairs:
            _logs = {"quota": quota}
            for _k in ("seeding", "narration"):
                _v = list(_perm_heads[_k])
                _v.insert(_i, xchk_same_run)
                _v.insert(_j, _perm_notes[_k])
                _logs[_k] = _v
            _ok, _msg = run(after, _logs, NOW_EARLY)
            if _ok or _msg != _base_msg:       # 判決翻靜音、或內文和基準分岔,都算破
                _perm_bad = ((_i, _j), "翻成靜音" if _ok else "內文分岔")
                break
        add(rows, "M1b 排列 150 種插入位置 判決與內文全相同", "全相同",
            "全相同" if _perm_bad is None else f"{_perm_bad[0]}{_perm_bad[1]}",
            _perm_bad is None)

        # ---- M1c:三支哨**實際寫出來的那一行**,拿去餵互查 ----
        # 🔴 2026-09-11:兩名獨立驗證者各自抓到同一個洞,而洞在**本檔**。
        #    上面 M1 用 `pref = after.XCHK_PREFIX` 自己**合成**那一行 ⇒ 它驗的是
        #    「互查收到一行已經正確加過前綴的字串時,處理得對不對」。
        #    真正沒人驗的是另一半:**三支哨到底有沒有加那個前綴**。答案是沒有 ——
        #    `6aadb844` 起,產線那行以 `[` + 時間戳開頭 ⇒ 命中 `watch_crosscheck.py:117`
        #    的 `_TS`、躲過 `:136` 的 `_SKIP_PREFIXES` ⇒ 同伴把它當成今天的一筆排程讀數
        #    ⇒ 那天**閉嘴**。而 `xchk_broken()` 會被觸發的前提正是「今天沒有真讀數」,
        #    因果鏈是閉合的:它一出現,就一定出現在最需要有人叫的那一天。
        # ⚠️ 演習(`watch_drill_regression.py`)**結構上**驗不到這個形狀:`SELFTEST` 會加
        #    `[DRILL] `,那本來就在 `_SKIP_PREFIXES` 裡 ⇒ drill 路徑長不出產線那一行的長相。
        #    「有一支演習在跑」因此不構成這件事被蓋到的理由。
        # ⇒ 唯一作法:真的去跑 `xchk_broken()`,拿它**落到檔案裡的位元組**當語料,
        #   而不是拿我重打一次的版本(同 `block()`/`func_src()` 的理由)。
        print("M1c 哨真的寫出來的那一行(非合成語料)不准被互查算成讀數")
        _m1c = pathlib.Path(tempfile.mkdtemp(prefix="xchk_line_"))
        # 突變目標:三支哨裡那個字面前綴。這裡寫死字面是刻意的 —— 它是**被改的對象**,
        # 不是斷言的依據;斷言用的是 `after.XCHK_PREFIX`(見下面第一格)。
        # 找不到時不 assert,改成紅格:assert 會把一格紅變成整份 traceback。
        _PREF_SRC = '"[XCHK] " + ("[DRILL] " if SELFTEST else "")'
        # 回讀的身分來源。突變列拿它當目標,所以三支哨那行刻意寫成**單行**。
        _UNIQ_SRC = ('"#" + LOG.stem + ":" + _pid + ":" '
                     '+ datetime.datetime.now().strftime("%H%M%S.%f")')
        try:
            _head = {k: c.upto(k, "[2026-09-09") for k in ("seeding", "narration")}
            for fname, key in WATCH_FILES:
                fsrc = func_src(REPO / "scripts" / f"{fname}.py", "xchk_broken")

                def _first_line(src_, tag, _key=key):
                    got, raised, _e, _r = xchk_broken_trial(
                        src_, "none", _m1c / f"{_key}_{tag}.log",
                        temp_to=_m1c / f"{_key}_{tag}_t")
                    if raised is not None or not got.strip():
                        return None
                    return got.strip().splitlines()[0]

                real = _first_line(fsrc, "real")
                ok = real is not None and real.startswith(after.XCHK_PREFIX)
                add(rows, f"M1c {key} 真輸出以 XCHK_PREFIX 開頭",
                    f"startswith {after.XCHK_PREFIX!r}",
                    (real[:10] + "…") if real else "跑不出那一行", ok)

                if real is None:
                    add(rows, f"M1c {key} 真 XCHK 行不算讀數 ⇒ 必須叫", "叫", "語料取不到", False)
                    add(rows, f"M1c {key} 突變 拿掉前綴 ⇒ 必須翻成靜音", "靜音", "語料取不到", False)
                    continue

                case(f"M1c {key} 真 XCHK 行不算讀數 ⇒ 必須叫", after,
                     {"seeding": _head["seeding"] + [real],
                      "narration": _head["narration"] + [real],
                      "quota": quota}, NOW_LATE, "叫")

                # 陰性對照:把那個字面前綴拿掉,同一份語料必須**翻成靜音**。
                # 少了這一列,上一格和「這一格恆叫」分不開(memory
                # `load-bearing-line-needs-mutation`)。
                # ⚠️ 這一格的「靜音」靠的是 `xchk_broken()` 蓋的是**真實時鐘**的日期,
                #    而 NOW_LATE 是 2026-09-11 ⇒ 只要真實日期 ≥ 09-11 就成立(日期只會往前),
                #    不是靠語料裡寫死的時間。
                bare = (None if _PREF_SRC not in fsrc else _first_line(
                    fsrc.replace(_PREF_SRC, '("[DRILL] " if SELFTEST else "")'), "mut"))
                if bare is None:
                    add(rows, f"M1c {key} 突變 拿掉前綴 ⇒ 必須翻成靜音", "靜音",
                        "突變沒生效(原文裡找不到那個字面前綴)"
                        if _PREF_SRC not in fsrc else "突變語料取不到", False)
                    continue
                case(f"M1c {key} 突變 拿掉前綴 ⇒ 必須翻成靜音", after,
                     {"seeding": _head["seeding"] + [bare],
                      "narration": _head["narration"] + [bare],
                      "quota": quota}, NOW_LATE, "靜音")
        finally:
            shutil.rmtree(_m1c, ignore_errors=True)

        # ---- M2:註記隔天才追加 ----
        print("M2 註記行隔天才追加(晚上補跑、隔天早上回來註記)")
        late = {"seeding": c.upto("seeding", "[2026-09-10 18:05]")
                + [c.note_s.replace("2026-09-10 18:05", "2026-09-11 09:40")],
                "narration": c.upto("narration", "[2026-09-10 18:05]")
                + [c.note_n.replace("2026-09-10 18:05", "2026-09-11 09:40")],
                "quota": quota}
        if before:
            case("M2 修之前", before, late, NOW_EARLY, "靜音")
        # 🔴 這一格是**還沒好**的:不帶環境變數的補跑,M2 依然靜音。期待寫「靜音」是記錄現況。
        case("M2 修之後·不帶 WATCH_MANUAL(未修)", after, late, NOW_EARLY, "靜音")

        env = {}
        for key, prefix in [("seeding", "[2026-09-10 18:05]"), ("narration", "[2026-09-10 18:05]")]:
            lines = c.upto(key, prefix)
            lines[-1] = "[MANUAL] " + lines[-1]     # WATCH_MANUAL=1 ⇒ 前綴打在讀數行本身
            env[key] = lines
        env["quota"] = quota
        case("M2 修之後·WATCH_MANUAL=1", after, env, NOW_EARLY, "叫")

        # ---- 突變測試:證明上面那幾格**不是恆過** ----
        # 「修之前」那幾欄要 --before 才有,而沒人給時就等於少了陰性。這一段不需要備份檔:
        # 直接載入第二份現行模組,只動一個常數,看那一格會不會**翻**。
        # 🔴 這一段還糾正過我自己一次:我原本以為 M1 承重在 `_SKIP_PREFIXES`,
        #    突變 `_SKIP_PREFIXES=()` 判決**沒變**,突變 `XCHK_PREFIX=""` 才翻 ——
        #    承重的是「前綴把時間戳擠出行首」,不是那張表。
        print("突變測試(不需要 --before:證明 M1 那格不是恆過)")
        mut = load(REPO / "scripts" / "watch_crosscheck.py", "xchk_mutant")
        mut.XCHK_PREFIX = ""          # 唯一的突變:互查不再給自己的行打前綴
        m1_logs = {"seeding": c.upto("seeding", "[MANUAL]")
                   + [f"[2026-09-11 09:00] {c.xchk_body}"],
                   "narration": c.upto("narration", "[MANUAL]")
                   + [f"[2026-09-11 09:00] {c.xchk_body}"],
                   "quota": quota}
        case("突變 XCHK_PREFIX='' ⇒ M1 必須翻成靜音", mut, m1_logs, NOW_LATE, "靜音")
        mut2 = load(REPO / "scripts" / "watch_crosscheck.py", "xchk_mutant2")
        mut2._SKIP_PREFIXES = ()      # 對照:這個常數**不承重**,判決不該變
        case("對照 _SKIP_PREFIXES=() ⇒ 判決不該變(仍叫)", mut2,
             {"seeding": c.upto("seeding", "[MANUAL]")
              + [f"{after.XCHK_PREFIX}[2026-09-11 09:00] {c.xchk_body}"],
              "narration": c.upto("narration", "[MANUAL]")
              + [f"{after.XCHK_PREFIX}[2026-09-11 09:00] {c.xchk_body}"],
              "quota": quota}, NOW_LATE, "叫")

        # ---- 曾經的「相鄰收緊代價」:現在是缺陷關閉的證據 ----
        # 🔴 2026-09-11:下面那格**曾經期待「靜音」**,並在檔頭被我記成「收緊的已知代價、
        #    邊角情況」。第三輪獨立驗證【2/5】證明那不是邊角是主線,規則改成行序無關的
        #    認領 ⇒ 這一格翻回「叫」。**期待值從靜音改成叫的那一刻就是缺陷關閉點**;
        #    哪天有人又把「只降級緊鄰那筆」加回去,這一格會自己翻紅。
        print("註記指的讀數不緊鄰(中間插一行演習)⇒ 認領不看位置,必須照樣叫")
        gap = {"seeding": c.upto("seeding", "[2026-09-09")
               + [c.read_s, "[DRILL] [2026-09-10 19:00] 演習行插在中間", c.note_s],
               # narration 這裡必須正常,否則它自己就會讓整句判成「叫」,把 seeding 那格遮掉
               "narration": c.upto("narration", "[2026-09-09") + ["[2026-09-10 07:10] 語料:排程真的跑了"],
               "quota": quota}
        if before:
            case("不緊鄰 修之前(鬆規則 ⇒ 叫)", before, gap, NOW_EARLY, "叫")
        case("不緊鄰 修之後(認領不看位置 ⇒ 叫)", after, gap, NOW_EARLY, "叫")

        # ---- M5:check_schedule() 的四個判準 ----
        # 🔴 第三輪獨立驗證【4/5】:上一代 check_schedule() **在 2026-09-10 那場事故本身
        #    上是綠的** —— 它治「常數漂了」,事故是「該跑沒跑」,而證據(LastRunTime、
        #    NumberOfMissedRuns)就在同一趟 PowerShell 拿得到的欄位裡,它一個都沒問。
        #
        # 這一節餵的是**合成 dump**,而不是去正式機造一個同名工作 / 停用工作 / 塞過期
        # EndBoundary —— 那是寫正式機,不是驗證該付的代價。合成的只是「儀器讀到的那串字」,
        # 判準本身是磁碟上真的那一份 judge_schedule()。
        #
        # 🔴 每一格都配一列**舊判準對照**:光證明「新判準會叫」不構成修好了,還要證明
        #    舊判準在同一份 dump 上是**綠的**,否則「我修了 E/F/H/I」和「這四格本來就會叫」
        #    分不開(memory load-bearing-line-needs-mutation)。舊判準逐字保存在
        #    watch_crosscheck.old_judge_schedule()。
        print("M5 排程檢查的四個判準(合成 dump;每格並排舊判準,證明它當時是綠的)")
        SW = {"at": datetime.time(7, 0), "task": "carson-seeding-watch"}
        NOW_S = datetime.datetime(2026, 9, 11, 9, 0)      # due = 2026-09-11 07:00
        T_OK = "TRIG=True|2026-09-06T07:00:00+08:00||MSFT_TaskDailyTrigger|"
        FRESH = "INFO=2026-09-11T07:00:01|0|0"
        # 🔴 這一行是 2026-09-11 02:46 從**活的**排程唯讀讀到的真值,不是我編的:
        #    carson-seeding-watch State=Ready LastRun=09/09 07:00 Missed=1 rc=0
        STALE = "INFO=2026-09-09T07:00:01|1|0"

        def dump(count="1", states=("Ready",), trigs=(T_OK,), info=FRESH, paths=("\\",)):
            out = [f"COUNT={count}"]
            for pa in paths:
                out.append(f"PATH={pa}")
            for st in states:
                out.append(f"STATE={st}")
            out += list(trigs) + [info]
            return out

        M5_CASES = [
            # (名稱, dump, 新判準該不該叫, 舊判準該不該綠)
            ("M5-H 真事故 09-10 漏跑(活的排程真值)",
             dump(info=STALE), True, True),
            ("M5 陰性對照 一切正常",
             dump(), False, True),
            ("M5-E 同名工作兩個(Ready + Disabled)",
             dump(count="2", states=("Ready", "Disabled"), paths=("\\", "\\Foo")), True, True),
            ("M5-F State=Unknown(工作損壞)",
             dump(states=("Unknown",)), True, True),
            ("M5-I EndBoundary 已過期",
             dump(trigs=("TRIG=True|2026-09-06T07:00:00+08:00|2026-09-08T00:00:00+08:00"
                         "|MSFT_TaskDailyTrigger|",)), True, True),
            ("M5-I 陰性 EndBoundary 在未來",
             dump(trigs=("TRIG=True|2026-09-06T07:00:00+08:00|2027-01-01T00:00:00+08:00"
                         "|MSFT_TaskDailyTrigger|",)), False, True),
            ("M5-I EndBoundary 讀不懂 ⇒ 往叫倒",
             dump(trigs=("TRIG=True|2026-09-06T07:00:00+08:00|???|MSFT_TaskDailyTrigger|",)),
             True, True),
            ("M5 觸發器 Enabled=False",
             dump(trigs=("TRIG=False|2026-09-06T07:00:00+08:00||MSFT_TaskDailyTrigger|",)),
             True, False),
            ("M5 LastRunTime 空(從來沒跑過)",
             dump(info="INFO=|0|0"), True, True),
        ]
        for name, d, want_fire, want_old_green in M5_CASES:
            probs, notes = after.judge_schedule(SW, d, NOW_S)
            add(rows, name, "叫" if want_fire else "靜音",
                "叫" if probs else "靜音", bool(probs) == want_fire)
            green = after.old_judge_schedule(SW, d)
            add(rows, "└ 舊判準對照", "綠" if want_old_green else "叫",
                "綠" if green else "叫", green == want_old_green)
            # 🔴 2026-09-11 獨立驗證(fresh-context)抓到:這一格原本寫成
            #       `if not notes: add(..., False)`
            #    三個毛病疊在一起,而且**它通過時連一列都不產生**:
            #      ① 違反本檔 :106 自己立的規矩(「所有格子一律走 add()」)——
            #         看不到的格子沒有人能查證,而 77/91 這種數字也永遠不會包含它。
            #      ② `watch_crosscheck.py:442` 的 `notes.append(...)` 是**無條件**的
            #         (不在任何分支裡)⇒ `not notes` 結構上不可能為真 ⇒ 這格是死碼。
            #      ③ 就算真的翻了,先炸的是 `EXPECT_ROWS` 的格數斷言,訊息會說
            #         「你改了本檔卻沒改 EXPECT_ROWS」⇒ **把真因蓋掉**。
            #    改成無條件一列,而且斷言的是**有內容的東西**:那行常數回讀帶不帶得出
            #    `task` 名。它會在有人把 :442 挪進分支、或改掉那行格式時翻紅。
            add(rows, "└ notes 要帶得出常數回讀(task 名)", f"含 {SW['task']}",
                f"含 {SW['task']}" if any(SW["task"] in n for n in notes)
                else f"notes={len(notes)} 列但沒有",
                any(SW["task"] in n for n in notes))

        # LogonTrigger:照印、不判(這是修(二) 上線後唯一的掛鉤點)
        logon = dump(trigs=(T_OK, "TRIG=True|2026-09-11T02:00:00+08:00||"
                                  "MSFT_TaskLogonTrigger|PT5M"))
        probs, notes = after.judge_schedule(SW, logon, NOW_S)
        add(rows, "M5 LogonTrigger 不參與判定(不誤叫)", "靜音",
            "叫" if probs else "靜音", not probs)
        add(rows, "M5 LogonTrigger 必須被照印出來", "有 Logon",
            "有 Logon" if any("Logon" in n for n in notes) else "被吃掉",
            any("Logon" in n for n in notes))
        # 🔴 而「填了 logon_delay 就變斷言」這個掛鉤本身也要驗 —— 否則它是死碼,
        #    修(二) 上線那天填進去也不會有人知道它沒作用。
        sw2 = dict(SW, logon_delay="PT15M")
        probs2, _ = after.judge_schedule(sw2, logon, NOW_S)
        add(rows, "M5 logon_delay 填了但排程是 PT5M ⇒ 必須叫", "叫",
            "叫" if probs2 else "靜音", bool(probs2))
        sw3 = dict(SW, logon_delay="PT5M")
        probs3, _ = after.judge_schedule(sw3, logon, NOW_S)
        add(rows, "M5 logon_delay 對得上 ⇒ 靜音(陰性)", "靜音",
            "叫" if probs3 else "靜音", not probs3)

        # ---- 陰性對照 ----
        print("陰性對照(三支都正常跑到 due ⇒ 必須靜音,否則每天誤叫)")
        good = {"seeding": c.upto("seeding", "[2026-09-09") + ["[2026-09-11 07:00] 語料:排程真的跑了"],
                "narration": c.upto("narration", "[2026-09-09") + ["[2026-09-11 07:10] 語料:排程真的跑了"],
                "quota": quota + ["[2026-09-10 15:20] 語料:排程真的跑了"]}
        case("陰性對照 全部正常", after, good, NOW_LATE, "靜音")

        # ---- M3:控制流 ----
        print("M3 控制流(exec 三支哨檔案裡 __main__ 的原文,main() 丟例外)")
        for fname, key in WATCH_FILES:
            src = block(REPO / "scripts" / f"{fname}.py")
            try:
                r = control_flow_trial(src, main_exc=RuntimeError("模擬:main() 炸了"))
            except NameError as ne:
                add(rows, f"M3 {key} 原文 exec", "可 exec", f"NameError:{ne}", False)
                print(f"  🔴 {fname}:__main__ 原文 exec 不起來({ne})—— "
                      f"那段程式碼改了,**先來補本檔的 stub**,不是產線壞了")
                continue
            _ob = r.calls[0][2] is not None if r.calls else False
            ok = len(r.calls) == 1 and isinstance(r.exc, RuntimeError) and _ob
            add(rows, f"M3 {key} main()丟例外→互查仍執行且帶 on_broken", "1 次+有",
                f"{len(r.calls)} 次+{'有' if _ob else '沒有'}", ok)

            r = control_flow_trial(src, main_rc=0)
            ok = len(r.calls) == 1 and isinstance(r.exc, SystemExit) and r.exc.code == 0
            add(rows, f"M3 {key} 正常路徑 rc=0", "0", str(getattr(r.exc, "code", r.exc)), ok)

            # 🔴 2026-09-11 改斷言:舊版查的是 `"[XCHK-BROKEN]" in err`,而 err 是永遠
            #    可寫的 _Err ⇒ 產線靜默時它照樣 PASS(見 _Err 的 docstring)。
            #    現在查的是「有沒有呼叫 xchk_broken(寫 log 檔)」**且 stderr 一個字都沒寫**,
            #    而且假 stderr 用排程實況 None,不是那個友善的。
            r = control_flow_trial(src, main_exc=RuntimeError("根因"),
                                   xchk_exc=RuntimeError("互查自己炸了"), stderr_mode="none")
            ok = (isinstance(r.exc, RuntimeError) and str(r.exc) == "根因"
                  and len(r.broken) == 1 and r.err == "")
            add(rows, f"M3 {key} 兩邊都炸→根因不被取代(stderr=None)", "根因+留痕1",
                f"{str(r.exc)}+留痕{len(r.broken)}", ok)

            r = control_flow_trial(src, main_rc=0, xchk_exc=RuntimeError("互查自己炸了"),
                                   stderr_mode="none")
            ok = (isinstance(r.exc, SystemExit) and r.exc.code == 4
                  and len(r.broken) == 1 and r.err == "")
            add(rows, f"M3 {key} 只有互查炸→rc=4 且留痕(stderr=None)", "4+留痕1",
                f"{getattr(r.exc, 'code', r.exc)}+留痕{len(r.broken)}", ok)

            if key == "seeding":
                r = control_flow_trial(src, main_rc=0, iso=False)
                ok = isinstance(r.exc, SystemExit) and r.exc.code == 9
                add(rows, "M3 seeding 演習隔離失敗 rc=9 不被互查覆蓋", "9",
                    str(getattr(r.exc, "code", r.exc)), ok)

        # ---- M4:最後一道留痕本身,在**正式機的 stderr 形狀**下重驗 ----
        # 🔴 這一節是獨立驗證新-1 的產物。被驗的不是「有沒有出聲」,是「出聲那條路在
        #    pythonw 底下到不到得了人眼前」。舊版把它交給 stderr,而那裡兩種形狀都到不了:
        #    排程無 console ⇒ sys.stderr is None ⇒ 靜默 no-op;有 handle ⇒ cp950 編不了 🔴。
        print("M4 最後一道留痕(exec 三支哨檔案裡 xchk_broken 的原文,主通道=log 檔)")
        _xb_tmp = pathlib.Path(tempfile.mkdtemp(prefix="xchk_broken_"))
        try:
            for fname, key in WATCH_FILES:
                path = REPO / "scripts" / f"{fname}.py"
                src = block(path)
                # (1) __main__ 必須交給 xchk_broken,而不是自己 print 到 stderr
                r = control_flow_trial(src, main_rc=0, xchk_exc=RuntimeError("互查自己炸了"),
                                       stderr_mode="ok")
                ok = len(r.broken) == 1 and r.err == ""
                add(rows, f"M4 {key} __main__ 走 xchk_broken 不走 stderr", "留痕1+stderr空",
                    f"留痕{len(r.broken)}+stderr{len(r.err)}字", ok)

                fsrc = func_src(path, "xchk_broken")
                # (2) 排程實況:sys.stderr is None ⇒ 主通道仍要落地
                got, raised, _, ret = xchk_broken_trial(
                    fsrc, "none", _xb_tmp / f"{key}_none.log",
                    temp_to=_xb_tmp / f"{key}_t2")
                ok = (raised is None and "[XCHK-BROKEN]" in got
                      and ret == _xb_tmp / f"{key}_none.log")
                add(rows, f"M4 {key} stderr=None 仍寫進 log 且回傳主通道", "log有+回傳主",
                    ("log 有" if "[XCHK-BROKEN]" in got else "log 空")
                    + f"/回傳{ret}/拋{raised!r}", ok)

                # (3) 有 handle 的實況:cp950 遇到 🔴。不准拋(在 finally 裡拋會取代 main()
                #     的根因),log 要落地,而 stderr 那條要看到被 replace 掉的問號。
                got, raised, errbuf, ret = xchk_broken_trial(
                    fsrc, "cp950", _xb_tmp / f"{key}_950.log",
                    temp_to=_xb_tmp / f"{key}_t3")
                ok = raised is None and "[XCHK-BROKEN]" in got and "?" in errbuf
                add(rows, f"M4 {key} stderr=cp950 帶emoji 不拋且 log 落地", "不拋+log有+替換",
                    f"拋{raised!r}+{'log有' if '[XCHK-BROKEN]' in got else 'log空'}"
                    f"+{'替換' if '?' in errbuf else '無替換'}", ok)

                # (4) 常駐突變列:承重的是 xchk_broken 裡 `encoding=utf-8` 那一行。
                #     把它改成 cp950,emoji 就編不進去、被最後那個 except 吞掉 ⇒ log 必須變空。
                #     少了這一列,「log 落地」和「這兩格恆過」分不開
                #     (memory load-bearing-line-needs-mutation)。
                _q = chr(34)
                mut = fsrc.replace("encoding=" + _q + "utf-8" + _q,
                                   "encoding=" + _q + "cp950" + _q)
                assert mut != fsrc, "突變沒生效:xchk_broken 裡找不到 encoding=utf-8"
                got, raised, _, ret = xchk_broken_trial(
                    mut, "none", _xb_tmp / f"{key}_mut.log",
                    temp_to=_xb_tmp / f"{key}_t4")
                # 🔴 斷言收緊(第四輪驗證【3/5】):原本是「沒拋 + log 裡沒有那個標記字串」,
                #    而 5/5 個不相干的突變也都滿足它 —— 最糟的是「把標記改個名」:
                #    log 照樣落 172 bytes,而這一格照樣說「突變被殺掉」。
                #    改成三件一起要:不拋 + log **整份是空的** + 回傳值是 None。
                # ⚠️ 2026-09-11 更正上面那句的**因果**(獨立驗證【2/4】抓到,不是我自己看出來的):
                #    原本寫「改名那種突變因此自己出局(它的 got != "")」—— 那是**錯的**。
                #    本格餵進去的突變自己就是 cp950,`got` 一定是 `""`,和標記叫什麼名字無關
                #    ⇒ 本格對「改名」完全不敏感。真正殺掉改名突變的是 (2)(3)(5)(6),
                #    那四格斷言 `"[XCHK-BROKEN]" in got`。本格殺的是**編碼**,只殺編碼。
                #    (memory `load-bearing-line-needs-mutation`:指錯是哪一行承重,
                #     等於照錯因去修 —— 一個字都沒修到。)
                ok = raised is None and got == "" and ret is None
                add(rows, f"M4 {key} 突變 log 編碼→上一格必須翻面", "不拋+log全空+回傳None",
                    f"拋{raised!r}+{'全空' if got == '' else f'{len(got)}字'}+回傳{ret}", ok)
                # ── (5)~(9) 第四輪驗證【2/5】:退路與回讀 ──────────────────────
                # 【2/5】的指控:舊版「寫完就算數」,而且第一條路失敗時退到 stderr ——
                # 和剛剛失敗的那條 log 通道**同一個失敗點**,在 pythonw 底下整條靜默。
                # 下面五格把新的三條路(主 log → 同目錄 .broken.log → %TEMP%)和
                # 「寫完回讀」各自釘住,而且每一格都配一個會翻面的突變。

                # (5) `docs/ops/` 整個寫不進去(父層是一個**檔案**)⇒ ①② 同時死,
                #     必須落到**換了磁碟區**的第三條路,而且要說得出前兩條為什麼死。
                blocked_dir = _xb_tmp / f"{key}_block"
                blocked_dir.write_text("我是檔案不是目錄", encoding="utf-8")
                t5 = _xb_tmp / f"{key}_t5"
                got, raised, _, ret = xchk_broken_trial(
                    fsrc, "none", blocked_dir / "x.log", temp_to=t5)
                landed = ret.read_text(encoding="utf-8") if ret is not None else ""
                ok = (raised is None and ret is not None
                      and ret.parent != blocked_dir            # 真的換了地方
                      and "[XCHK-BROKEN]" in landed
                      and "退到備援路徑" in landed)            # 主通道為什麼沒有,寫在活著那份裡
                add(rows, f"M4 {key} 目錄整個不可寫 ⇒ 落到 %TEMP% 並註明退路",
                    "換路+留痕+註明",
                    f"回傳{ret}/{'有痕' if '[XCHK-BROKEN]' in landed else '無痕'}"
                    f"/{'有註明' if '退到備援路徑' in landed else '沒註明'}/拋{raised!r}", ok)

                # (6) 只有主 log 那一個檔壞掉(它是個目錄)⇒ 同目錄的 `.broken.log` 接住,
                #     **不必**跨磁碟區。這一格和 (5) 分開,是因為它們治的是不同的壞法。
                dir_as_log = _xb_tmp / f"{key}_asdir.log"
                dir_as_log.mkdir(parents=True, exist_ok=True)
                got, raised, _, ret = xchk_broken_trial(
                    fsrc, "none", dir_as_log, temp_to=_xb_tmp / f"{key}_t6")
                landed = ret.read_text(encoding="utf-8") if ret is not None else ""
                ok = (raised is None and ret is not None
                      and ret == dir_as_log.with_suffix(".broken.log")
                      and "[XCHK-BROKEN]" in landed)
                add(rows, f"M4 {key} 主 log 壞掉 ⇒ 同目錄 .broken.log 接住",
                    "落在 .broken.log", f"回傳{ret}/拋{raised!r}", ok)

                # (6b) 🔴 (6) 自己的翻面突變:只把**第二條路**從清單裡拿掉(%TEMP% 那條留著)。
                #      少了這一列,(6) 和「這一格恆過」分不開 —— 下面的 (7) 砍的是
                #      第二和第三條**一起**,它殺得掉 (5) 卻殺不掉「(6) 其實是被 %TEMP%
                #      接住而我看錯」這種讀法(memory `load-bearing-line-needs-mutation`:
                #      綠燈的測試不區分是哪個改動讓它變綠)。
                #      翻面的長相是「還是有留痕,但**落錯地方**」,不是「沒留痕」——
                #      所以斷言要盯**落在哪裡**,不是盯有沒有落。
                mut6 = fsrc.replace('cands = [LOG, LOG.with_suffix(".broken.log")]',
                                    "cands = [LOG]")
                if mut6 == fsrc:
                    add(rows, f"M4 {key} 突變 砍掉 .broken.log 那條 ⇒ 上一格必須翻面",
                        "落到別處", "突變沒生效(找不到 cands 那行)", False)
                else:
                    dir_as_log6 = _xb_tmp / f"{key}_asdir6.log"
                    dir_as_log6.mkdir(parents=True, exist_ok=True)
                    got, raised, _, ret = xchk_broken_trial(
                        mut6, "none", dir_as_log6, temp_to=_xb_tmp / f"{key}_t6b")
                    landed = ret.read_text(encoding="utf-8") if ret is not None else ""
                    ok = (raised is None and ret is not None
                          and ret != dir_as_log6.with_suffix(".broken.log")
                          and "[XCHK-BROKEN]" in landed)
                    add(rows, f"M4 {key} 突變 砍掉 .broken.log 那條 ⇒ 上一格必須翻面",
                        "留痕但落到別處", f"回傳{ret}/拋{raised!r}", ok)

                # (7) 突變:把備援清單砍回只剩主通道 ⇒ (5) 必須翻面成「完全沒留痕」。
                #     少了這一列,(5) 和「這一格恆過」分不開。
                mut7 = fsrc.replace('cands = [LOG, LOG.with_suffix(".broken.log")]',
                                    "cands = [LOG]")
                mut7 = mut7.replace(
                    'cands.append(pathlib.Path(_tf.gettempdir()) / "carson-watch-xchk-broken.log")',
                    "pass")
                assert mut7 != fsrc and "cands = [LOG]" in mut7, "突變 7 沒生效:備援清單改過了"
                got, raised, _, ret = xchk_broken_trial(
                    mut7, "none", blocked_dir / "x.log", temp_to=_xb_tmp / f"{key}_t7")
                ok = raised is None and ret is None
                add(rows, f"M4 {key} 突變 砍掉備援清單 ⇒ 上一格必須翻面", "回傳None",
                    f"回傳{ret}/拋{raised!r}", ok)

                # (8) 突變:寫進去的是空字串(模擬「write 沒拋例外但那行沒落地」)。
                #     🔴 **回讀就是為了這個而存在的** ⇒ 三條路全部要判定失敗、回傳 None。
                mut8 = fsrc.replace("f.write(line + chr(10))", 'f.write("")')
                assert mut8 != fsrc, "突變 8 沒生效:找不到寫入那行"
                got, raised, _, ret = xchk_broken_trial(
                    mut8, "none", _xb_tmp / f"{key}_m8.log", temp_to=_xb_tmp / f"{key}_t8")
                ok = raised is None and ret is None and "[XCHK-BROKEN]" not in got
                add(rows, f"M4 {key} 突變 寫入變空 ⇒ 回讀必須抓到", "回傳None",
                    f"回傳{ret}/log{len(got)}字/拋{raised!r}", ok)

                # (9) 🔴 陰性對照,(8) 的另一半:同樣把寫入變空,**再把回讀拆掉**。
                #     這就是舊版的行為 ⇒ 它會**謊報成功**(回傳一個路徑,而 log 是空的)。
                #     這一列在證明 (8) 量到的是回讀,不是別的東西。
                mut9 = mut8.replace(
                    'raise IOError("寫完回讀找不到自己那行:" + str(path))', "pass")
                assert mut9 != mut8, "突變 9 沒生效:找不到回讀的 raise"
                got, raised, _, ret = xchk_broken_trial(
                    mut9, "none", _xb_tmp / f"{key}_m9.log", temp_to=_xb_tmp / f"{key}_t9")
                ok = raised is None and ret is not None and "[XCHK-BROKEN]" not in got
                add(rows, f"M4 {key} 陰性 拆掉回讀 ⇒ 空 log 也回報成功(舊版行為)",
                    "回傳路徑+log空", f"回傳{ret}/log{len(got)}字", ok)

                # (10)(11) 🔴 回讀必須認得出「**我**寫的那行」,不是「有一行長這樣」。
                #   2026-09-11 第五輪獨立驗證 (a-1):原本是 `if line not in tail`,而
                #   `line` 跨哨之間可能逐字相同(`stamp` 只到分鐘、`repr(OSError)` 不含檔名、
                #   第三條路的檔名三支共用)⇒ A 寫成功就能讓 B 的回讀通過。
                #   佈景:**先讓一次正常呼叫把一行落進同一個 log**,再用「寫入變空」跑第二次。
                _fp = _xb_tmp / f"{key}_fp.log"
                xchk_broken_trial(fsrc, "none", _fp, temp_to=_xb_tmp / f"{key}_t10a")
                got, raised, _, ret = xchk_broken_trial(
                    mut8, "none", _fp, temp_to=_xb_tmp / f"{key}_t10")
                add(rows, f"M4 {key} 回讀 log 裡已有別人那行 + 自己沒寫 ⇒ 仍須判失敗",
                    "回傳None", f"回傳{ret}/拋{raised!r}",
                    raised is None and ret is None)

                #   配對突變:把 `_uniq` 釘成常數 = 回到「這一行不帶本次呼叫的身分」。
                #   於是第二次的識別和第一次逐字相同 ⇒ 回讀在 tail 裡找得到 ⇒ **假陽性重現**:
                #   它回報留痕成功,而它這一次一個位元組都沒寫。
                #   🔴 少了這一列,上一列的綠和「這格恆綠」分不開(memory
                #      `load-bearing-line-needs-mutation`)。
                mut10 = fsrc.replace(_UNIQ_SRC, '"#FIXED"')
                assert mut10 != fsrc, "突變 10 沒生效:找不到 _uniq 的字面"
                mut11 = mut10.replace("f.write(line + chr(10))", 'f.write("")')
                assert mut11 != mut10, "突變 11 沒生效:找不到寫入那行"
                _fp2 = _xb_tmp / f"{key}_fp2.log"
                xchk_broken_trial(mut10, "none", _fp2, temp_to=_xb_tmp / f"{key}_t11a")
                got, raised, _, ret = xchk_broken_trial(
                    mut11, "none", _fp2, temp_to=_xb_tmp / f"{key}_t11")
                add(rows, f"M4 {key} 突變 _uniq 釘成常數 ⇒ 上一格必須翻成假陽性",
                    "回傳主通道(謊報成功)", f"回傳{ret}/拋{raised!r}",
                    raised is None and ret == _fp2)
        finally:
            shutil.rmtree(_xb_tmp, ignore_errors=True)

        bad = [r for r in rows if not r[3]]
        n = len(rows)
        want_n = EXPECT_ROWS[bool(before)]
        if n != want_n:
            # 這一格治的是「格子靜靜消失」——它在舊版會印成 N/N 符合期待。
            msg = (f"🔴 格數不對:實得 {n} 格,期待 {want_n} 格"
                   f"(--before {'有' if before else '沒有'}給)。要嘛少跑了幾格、"
                   f"要嘛你改了本檔而沒有一起改 EXPECT_ROWS。**在這裡停,不要看下面的比率。**")
            record(f"[{now_stamp}] {msg}")
            print(msg)
            return 1
        skipped = "" if before else "(未給 --before ⇒ 「修之前」欄跳過,病灶重現這次沒做)"
        if bad:
            record(f"[{now_stamp}] 🔴 互查回歸 {n - len(bad)}/{n} 符合期待 —— **互查壞了**"
                   f"(不是產線壞了):" + "；".join(f"{r[0]}:期待{r[1]}實得{r[2]}" for r in bad)
                   + f"。設計與已知邊界見 scripts/watch_crosscheck.py 的 docstring。{skipped}")
            print(f"{chr(10)}🔴 {n - len(bad)}/{n} 符合期待,失敗:{[r[0] for r in bad]}")
            return 1
        record(f"[{now_stamp}] ✅ 互查回歸 {n}/{n} 符合期待"
               f"(M0 替身簽章 2、"
               f"M1c 哨真輸出 × 3 支 × 3 格(前綴 + 必須叫 + 拿掉前綴翻靜音)、"
               f"M1 前綴、M1b 行序不變量 × 3 + 內文逐字對照 + 排列 150 種 1 + 突變 1"
               f" + 歷史相鄰版陽性對照 2、"
               f"M2 WATCH_MANUAL、M5 排程判準 E/F/H/I × 9 + 舊判準並排 9 + LogonTrigger 4、"
               f"M3 控制流 × 3 支、M4 最後一道留痕 × 3 支 × 10 格"
               f"(主通道 3 + 備援路 2 + 突變 4 + 拆掉回讀的陰性 1)、陰性對照 1;"
               f"其中『M2 不帶環境變數』那格記錄的是**已知未修**的現況 —— "
               f"『不緊鄰』那格已於 09-11 從靜音翻回叫,不再是未修)。{skipped}")
        print(f"{chr(10)}✅ {n}/{n} 符合期待{skipped}")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def record(line):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + chr(10))
    try:
        print(line)
    except UnicodeEncodeError:      # cp950 主控台:log 是主要輸出通道,print 可以失敗
        print(line.encode("ascii", "replace").decode())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
