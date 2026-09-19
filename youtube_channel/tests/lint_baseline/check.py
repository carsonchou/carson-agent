#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pyflakes 基準:對**變化**告警,不要求絕對乾淨。

用法:cd youtube_channel && .venv/Scripts/python.exe tests/lint_baseline/check.py

為什麼是「基準」而不是「零警告」:
`scripts/` 249 支檔目前有 91 則警告,絕大多數是死 import 與無佔位符 f-string(無害)。
要求絕對乾淨 → 沒有人修得完 → 這把尺從第一天就是紅的 → 紅色變成常態 → 真的有事時沒人看。
那正是 `import re` 在 `stock_checkup_daily.py` 活了三天跑了零次的機制。

🔴 **少一則也是 FAIL,這是刻意的。**
只對「新增」告警的基準會退化成「永遠忽略」:某一則被修好之後基準就永遠對不上,
下一個人會直接把基準覆蓋掉,而覆蓋的那一刻新增的那則也一起被吞了。
所以兩個方向都失敗,逼人**有意識地**更新基準並在 commit 訊息裡說明。

沒有 `--update` 旗標,也是刻意的:一個「把它變綠」的按鈕會被當成修法用。
要更新就照失敗訊息印出來的 JSON 手動改 —— 那一點摩擦就是讓人讀一眼的成本。
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]                      # youtube_channel/
BASELINE = HERE / "baseline.json"

if not (BASE / "scripts").is_dir():
    print(f"**FAIL** cwd 不對:找不到 {BASE / 'scripts'}。請 cd youtube_channel 再跑。")
    raise SystemExit(2)


def pyflakes(paths):
    """回 {相對路徑: [訊息, ...]}。訊息不含路徑,只留 行:欄: 內容。"""
    r = subprocess.run([sys.executable, "-m", "pyflakes", *[str(p) for p in paths]],
                       capture_output=True, cwd=str(BASE))
    if r.returncode not in (0, 1):           # pyflakes:0=乾淨 1=有警告,其餘=它自己壞了
        print(f"**FAIL** pyflakes 本身異常 rc={r.returncode}\n{r.stderr.decode('utf-8', 'replace')[:400]}")
        raise SystemExit(2)
    out = {}
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        # 🔴 不可以用 line.split(":", 1):Windows 的路徑是 `D:\...oo.py:33:1: msg`,
        # 那樣切出來的第一段是**磁碟機代號 D**,249 支檔會全部歸到同一個 key。
        # 第一版就是這樣寫的,而陽性對照(只查訊息文字)照樣 PASS ——
        # 抓到它的是「涉及 N 支檔」那行正向輸出印出「1」。
        m = re.match(r"^(.*?):(\d+):(\d+): (.*)$", line)
        if not m:
            print(f"**FAIL** pyflakes 輸出格式沒對上,無法歸檔:{line[:120]}")
            raise SystemExit(2)
        rel = Path(m.group(1)).as_posix()
        if rel.startswith(BASE.as_posix() + "/"):
            rel = rel[len(BASE.as_posix()) + 1:]
        out.setdefault(rel, []).append(f"{m.group(2)}:{m.group(3)}: {m.group(4)}")
    return out


# ── 🔴 陽性對照必須先跑:證明這個環境裡 pyflakes 真的會叫 ──────────────────
# 沒有這一步,「零差異」和「工具根本沒執行」在輸出上長得一模一樣。
# 用的就是 2026-09-04 早上那個真實 bug 的形狀:少了 import 的 re.sub。
with tempfile.TemporaryDirectory() as td:
    probe = Path(td) / "_probe.py"
    probe.write_text("""def f(s):
    return re.sub(r'x', '', s)
""", encoding="utf-8")
    got = pyflakes([probe])
    msgs = " ".join(m for v in got.values() for m in v)
    if "undefined name 're'" not in msgs:
        print("**FAIL** 陽性對照沒叫 —— pyflakes 在這個環境裡不會回報 undefined name。")
        print(f"        實得:{got or '(空)'}")
        print("        🔴 這種狀態下「零差異」不代表通過 —— 它代表什麼都沒驗。")
        raise SystemExit(2)
print("陽性對照 PASS:pyflakes 在本環境確實會回報 undefined name")

files = sorted((BASE / "scripts").glob("*.py"))
cur = pyflakes(files)
n_warn = sum(len(v) for v in cur.values())
print(f"掃描 scripts/*.py {len(files)} 支,警告 {n_warn} 則,涉及 {len(cur)} 支檔")

if not BASELINE.exists():
    BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"(基準不存在,已建立 {BASELINE.name} —— 請人工看過一遍再 commit)")
    raise SystemExit(0)

old = json.loads(BASELINE.read_text(encoding="utf-8"))
added, removed = [], []
for rel in sorted(set(old) | set(cur)):
    a, b = old.get(rel, []), cur.get(rel, [])
    for m in b:
        if b.count(m) > a.count(m) and (m, rel) not in added:
            added.extend([(m, rel)] * (b.count(m) - a.count(m)))
    for m in a:
        if a.count(m) > b.count(m) and (m, rel) not in removed:
            removed.extend([(m, rel)] * (a.count(m) - b.count(m)))

UNDEF = [x for x in added if "undefined name" in x[0]]
if UNDEF:
    print(f"\n🔴🔴 **新增 {len(UNDEF)} 個 undefined name —— 這一族會在執行時 NameError,而且平常不走那條路就沒人知道**")
    for m, rel in UNDEF:
        print(f"     {rel}:{m}")

if added:
    print(f"\n**FAIL** 新增 {len(added)} 則警告:")
    for m, rel in added:
        print(f"     + {rel}:{m}")
if removed:
    print(f"\n**FAIL** 少了 {len(removed)} 則警告 —— **這也是 FAIL,而且是刻意的**:")
    for m, rel in removed:
        print(f"     - {rel}:{m}")
    print("     修好了是好事,但基準必須有意識地更新。只對『新增』告警的基準會退化成")
    print("     『永遠忽略』:對不上之後有人整份覆蓋,新增的那則就跟著被吞掉。")

if added or removed:
    print(f"\n更新方式:確認上面每一條都是你有意造成的,再把 {BASELINE.name} 改成:")
    print(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True))
    print("並在 commit 訊息說明改了哪幾條、為什麼。**不要只是覆蓋。**")
    raise SystemExit(1)

print("PASS:與基準逐則相同(新增 0、減少 0)")
