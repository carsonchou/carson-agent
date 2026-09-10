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
- 相鄰規則收緊的**淨方向是往靜音倒**(見 `watch_crosscheck.py` docstring 的實測)。

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
import io
import pathlib
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
def add(rows, name, expect, got, ok):
    rows.append((name, expect, got, ok))
    print(f"  {name:38s} 期待 {expect} / 實得 {got}  {'PASS' if ok else '🔴FAIL'}")


# 🔴 格數本身也要斷言:少了一格(某個 continue 提早跳掉、某個分支沒進去)在舊版會印成
#    「N/N 符合期待」,和真的全過長得一模一樣。這兩個數字改動時要連同理由一起改。
EXPECT_ROWS = {True: 35, False: 32}   # key = 有沒有給 --before


def block(path):
    """取出 `if __name__ == "__main__":` 起到檔尾的**原文**。"""
    text = io.open(path, encoding="utf-8").read()
    key = 'if __name__ == "__main__":'
    if key not in text:
        raise KeyError(f"{path.name} 裡找不到 {key}")
    return text[text.index(key):]


class _Err:
    """友善的假 stderr:永遠可寫、沒有 encoding 屬性。

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


def xchk_broken_trial(fsrc, stderr_mode, log_path, what=None, selftest=False):
    """exec 真的 `xchk_broken` 原文,回 (log 內容, 它拋出來的東西, stderr 內容)。

    log 一律寫到**暫存目錄**,不是 repo 裡的常駐 log —— 演習不可以往真 log 追加行。
    `what` 預設帶一個含 emoji 的例外:cp950 編不了它,那正是要驗的那一格。
    """
    if what is None:
        what = RuntimeError("🔴 模擬:record 自己爆了")
    err = _make_err(stderr_mode)
    g = {"datetime": datetime, "sys": types.SimpleNamespace(stderr=err),
         "LOG": log_path, "SELFTEST": selftest, "print": print}
    exec(compile(fsrc, "<xchk_broken>", "exec"), g)
    raised = None
    try:
        g["xchk_broken"](what)
    except BaseException as e:     # noqa: BLE001 —— 「它有沒有拋」本身就是受測結果
        raised = e
    got = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return got, raised, ("" if err is None else err.buf)


def control_flow_trial(src, main_rc=0, main_exc=None, xchk_exc=None, iso=None,
                       stderr_mode="ok"):
    """exec 一段真的 `__main__` 原文,回 `.calls / .exc / .err / .broken`。

    `stderr_mode` 決定假 stderr 的形狀("ok" / "cp950" / "none");預設 "ok" 是
    **最不像正式機**的那一種,所以要靠呼叫端明講,不要靠預設值。
    `broken` 記 `xchk_broken()` 被呼叫幾次 —— 收尾自己壞掉時的留痕現在走它,不走 stderr。
    """
    calls, err, broken = [], _make_err(stderr_mode), []

    def crosscheck_tail(rc, key, record, alert, now=None, on_broken=None):
        # 🔴 `on_broken` 一定要在簽章裡,而且要**記下來**:呼叫端忘了傳的話,
        #    最後一道留痕就退回本模組那條守衛版 stderr —— 在 pythonw 下等於沒有留痕。
        #    2026-09-11 實測:這個 stub 少了 on_broken 參數時,三支哨的呼叫直接 TypeError,
        #    被 finally 的 except 吞成 rc=4 ⇒ 「互查被呼叫 0 次」。所以這格會翻面,不是恆過。
        calls.append((rc, key, on_broken))
        if xchk_exc:
            raise xchk_exc
        return rc

    stub = types.ModuleType("watch_crosscheck")
    stub.crosscheck_tail = crosscheck_tail
    stub.manual_prefix = lambda: ""
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

        # ---- 相鄰收緊的代價:量出來,不用猜 ----
        print("相鄰規則收緊的代價(註記指的讀數不緊鄰時,新碼比舊碼容易靜音)")
        gap = {"seeding": c.upto("seeding", "[2026-09-09")
               + [c.read_s, "[DRILL] [2026-09-10 19:00] 演習行插在中間", c.note_s],
               # narration 這裡必須正常,否則它自己就會讓整句判成「叫」,把 seeding 那格遮掉
               "narration": c.upto("narration", "[2026-09-09") + ["[2026-09-10 07:10] 語料:排程真的跑了"],
               "quota": quota}
        if before:
            case("收緊代價 修之前(往叫倒)", before, gap, NOW_EARLY, "叫")
        case("收緊代價 修之後(往靜音倒·已知)", after, gap, NOW_EARLY, "靜音")

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
                got, raised, _ = xchk_broken_trial(fsrc, "none", _xb_tmp / f"{key}_none.log")
                ok = raised is None and "[XCHK-BROKEN]" in got
                add(rows, f"M4 {key} stderr=None 仍寫進 log", "log 有",
                    ("log 有" if "[XCHK-BROKEN]" in got else "log 空") + f"/拋{raised!r}", ok)

                # (3) 有 handle 的實況:cp950 遇到 🔴。不准拋(在 finally 裡拋會取代 main()
                #     的根因),log 要落地,而 stderr 那條要看到被 replace 掉的問號。
                got, raised, errbuf = xchk_broken_trial(fsrc, "cp950", _xb_tmp / f"{key}_950.log")
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
                got, raised, _ = xchk_broken_trial(mut, "none", _xb_tmp / f"{key}_mut.log")
                ok = raised is None and "[XCHK-BROKEN]" not in got
                add(rows, f"M4 {key} 突變 log 編碼→上一格必須翻面", "log 空",
                    "log 空" if "[XCHK-BROKEN]" not in got else "log 有(斷言恆過)", ok)
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
               f"(M1 前綴、M2 WATCH_MANUAL、M3 控制流 × 3 支、M4 最後一道留痕 × 3 支"
               f"(含常駐突變列)、陰性對照 1;"
               f"其中『M2 不帶環境變數』與『收緊代價』兩格記錄的是**已知未修**的現況)。{skipped}")
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
