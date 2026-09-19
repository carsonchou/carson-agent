#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""驗收自己的驗收:把偵測器弄壞之後,verify.py **必須變紅**。

用法:cd youtube_channel && .venv/Scripts/python.exe tests/prompt_leak/self_test.py

為什麼要有這支(2026-09-03 第四輪):
驗證員實測前一版 verify.py 有兩個單一參數,各自都能在偵測器**完全停擺**的情況下
讓驗收全綠;而 `output/` 是空的時候四條檢查也全 PASS(印了「母體 0 支」卻沒斷言)。
一個「把被測物弄壞也不會變紅」的測試,和沒有測試是同一件事 ——
這正是同一天在 daily_health 上花五輪修的那個病,只是搬到了測試那一側。

正控制組 + 四個攻擊都在**暫存副本**上進行,不會動到 repo 裡的任何檔案。
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path.cwd()
PY = ROOT / ".venv" / "Scripts" / "python.exe"
fails = 0


def run_in(sandbox):
    r = subprocess.run([str(PY), "-X", "utf8", "tests/prompt_leak/verify.py"],
                       cwd=sandbox, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    tail = [ln for ln in (r.stdout or "").splitlines() if "FAIL" in ln or ln.startswith("合計")]
    return r.returncode, out, tail


def sandbox():
    # 🔴 沙箱必須放在 **repo 內**:verify.py 的三版對照跑 `git show ... cwd=".."`,
    # 沙箱在 /tmp 的話 `..` 不是 repo → 三版全部取不到 → 檢查三為了錯的理由變紅,
    # 於是攻擊看起來被擋下來了,實際上是**假通過**(第一版就是這樣,攻擊二的
    # 兩個 FAIL 全是 git 取不到,實質檢查其實全 PASS)。
    d = Path(tempfile.mkdtemp(prefix=".selftest_", dir=str(ROOT)))
    (d / "scripts").mkdir()
    (d / "tests" / "prompt_leak").mkdir(parents=True)
    for f in ROOT.glob("scripts/*.py"):
        shutil.copy2(f, d / "scripts" / f.name)
    shutil.copy2(ROOT / "tests/prompt_leak/verify.py", d / "tests/prompt_leak/verify.py")
    (d / "output").mkdir()
    for f in ROOT.glob("output/*.voice.txt"):
        shutil.copy2(f, d / "output" / f.name)
    (d / "STUDIO").mkdir(exist_ok=True)
    for name in ("stock_checkup_facts.json", "uploaded_ledger.json", "stock_checkup_backlog.json"):
        src = ROOT / "STUDIO" / name
        if src.exists():
            shutil.copy2(src, d / "STUDIO" / name)
    return d


def attack(label, mutate, expect_fail=True, want=None):
    """want:期望看到的那一條 FAIL 標籤。

    🔴 只看退出碼不夠 —— 那是同一個病爬到最高一層。驗證員在 produce_batch 最前面塞一個
    和偵測完全無關的 `raise`,verify 因 SyntaxError 紅了,self_test 就判「攻擊被擋」。
    **「攻擊沒生效」「防禦有效」「被測物整個崩了」三者在退出碼上長得一模一樣。**
    所以要斷言**紅在對的那一條**上。
    """
    global fails
    d = sandbox()
    mutate(d)
    rc, out, tail = run_in(d)
    ok = (rc != 0) if expect_fail else (rc == 0)
    if ok and want:
        ok = any(want in ln and "FAIL" in ln for ln in out.splitlines())
    if expect_fail and "Traceback" in out:
        ok = False           # verify 自己崩了不算「攻擊被擋」
    fails += 0 if ok else 1
    print(f"  {'PASS' if ok else '**FAIL**'}  {label}｜verify 退出碼 {rc}"
          f"(期望 {'非 0' if expect_fail else '0'})"
          + (f"｜需紅在「{want}」" if want else ""))
    for ln in tail[:3]:
        print(f"        {ln.strip()[:110]}")
    shutil.rmtree(d, ignore_errors=True)


def patch(d, old, new):
    f = d / "scripts" / "produce_batch.py"
    s = f.read_text(encoding="utf-8")
    assert old in s, f"攻擊目標字串不存在:{old[:40]}"
    f.write_text(s.replace(old, new, 1), encoding="utf-8")


def gut_hard_directive(d):
    """把整個 _HARD_DIRECTIVE 換掉,不是只換第一個分支。

    🔴 第一版只把 `"嚴禁|` 換成 `"絕不可能出現的詞|`,而後面的
    `禁止|不准|不得|不要|…` 全部還在 —— 詞表根本沒被削弱,於是「攻擊二沒被擋下」
    這個結論本身是假的。**攻擊沒生效和防禦有效,在輸出上長得一模一樣。**
    """
    f = d / "scripts" / "produce_batch.py"
    s = f.read_text(encoding="utf-8")
    m = re.search(r'_HARD_DIRECTIVE = re\.compile\((?:\s*"[^"]*")+\s*\)', s)
    assert m, "找不到 _HARD_DIRECTIVE 定義"
    f.write_text(s[:m.start()] + '_HARD_DIRECTIVE = re.compile("絕不可能出現的詞")'
                 + s[m.end():], encoding="utf-8")


print("把偵測器弄壞之後,verify.py 必須變紅:\n")
# 🔴 正控制組:不動任何東西,verify 必須是綠的。沒有它的話,沙箱哪天少複製一個檔,
# 四個攻擊會**同時假 PASS**,而輸出跟現在一模一樣。`expect_fail=False` 這個參數
# 上一版就存在,但**從頭到尾沒被呼叫過** —— 一個沒被呼叫的正控制組等於沒有。
attack("正控制組:什麼都不改(沙箱本身要是健康的)", lambda d: None, expect_fail=False)
attack("攻擊一:_LEAK_DEL = 1.01(什麼都不刪)",
       lambda d: patch(d, "_LEAK_DEL = 0.90", "_LEAK_DEL = 1.01"),
       want="實際刪除的句型")
attack("攻擊二:_HARD_DIRECTIVE 縮成 1 個詞(語料幾乎清空)",
       gut_hard_directive, want="語料路徑活著")
attack("攻擊三:output/ 清空(母體 0 支)",
       lambda d: [f.unlink() for f in (d / "output").glob("*.voice.txt")],
       want="母體 >= 700 支")
attack("攻擊四:保護清單放寬成 `.`(偵測變差而前一版完全不叫)",
       lambda d: patch(d, "_LEAK_PROTECTED = re.compile(",
                       '_LEAK_PROTECTED = re.compile(".")\n_UNUSED = re.compile('),
       want="保護清單沒有把真指令一起豁免")

print(f"\n合計 FAIL={fails}(正控制組要綠、四個攻擊都要被擋下來)")
raise SystemExit(1 if fails else 0)
