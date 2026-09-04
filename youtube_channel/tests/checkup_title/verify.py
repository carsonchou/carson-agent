#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""代號去重改寫的驗收:敵意輸入要被擋,真實資料一筆都不准被誤擋。

用法:cd youtube_channel && .venv/Scripts/python.exe tests/checkup_title/verify.py

背景:`c7a9c8e6`(09-01)加的三行 `re.sub` 少了 `import re`,**寫了三天跑了零次**
(每次 NameError,09-02/09-03 種題全掛),`eed3ca25` 才補上 —— 明天 05:50 是它第一次真的執行。
而改寫之後**沒有任何閘門**:`is_banned_skeleton` / `exact_dup` / `skeleton_dup` /
`numbers_sourced_to_fact` 全部在改寫之前跑完,改寫後的版本沒有任何東西看過就進題庫。

⚠️ 誤擋比誤放貴:誤放是一支怪標題的片,誤擋是**種題再次歸零** —— 那正是剛修好的東西。
所以第二項(零誤擋)比第一項重要。
"""
import json
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, "scripts")
import collections  # noqa: E402
import stock_checkup_daily as scd  # noqa: E402  借它的 _UNIT_AFTER,不另寫一份

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STUDIO = Path("STUDIO")
fails = 0


def check(label, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(f"  {'PASS' if cond else '**FAIL**'}  {label}{('  ' + extra) if extra else ''}")


# 🔴 2026-09-04:**不要在這裡再寫一份改寫演算法。**
# 第一版是自己複製一份、只從產線借 `_UNIT_AFTER` 常數 —— 那樣有人改了產線正規式,
# 這支測試仍然會對著自己那份通過,而那正是 memory `yt-duplicate-impl-gate-bypass`
# (同一件事兩份實作,產線走沒閘門那份),也是這兩天反覆踩到的同一個坑。
# 改成**把產線原文抽出來 exec**:測的就是明天 05:50 會跑的那些位元組。
_SRC = Path("scripts/stock_checkup_daily.py").read_text(encoding="utf-8")
_A = _SRC.index("        hook = title\n")
_B = _SRC.index("        n = tb._norm(title)  #")
BLOCK = compile(textwrap.dedent(_SRC[_A:_B]), "<produce-path>", "exec")
print(f"(測試執行的是產線原文 {_SRC[:_A].count(chr(10)) + 1}~{_SRC[:_B].count(chr(10))} 行,"
      f"{_B - _A} 個位元組)")


def rewrite(hook_title, code, name):
    """跑**產線原文**。回 (改寫前標題, 最終標題, 被擋下時產線印出來的理由)。

    ⚠️ 不要為了讓測試好寫,就請產線多留一個變數(第一版就是這樣加了 `_would_be`,
    pyflakes 立刻從綠變紅:`assigned to but never used`)。**產線不該為測試而存在。**
    而且不需要 —— 產線那行 print 裡的 `title` 就是「本來會改成什麼」,
    後面還接著 `少了=/多了=/句首懸空連接詞`。收集 print 就有全部資訊。
    (一把從上線第一天就在說謊的 lint,下次真的有 undefined name 時沒有人會看它。)
    """
    said = []
    ns = {"re": re, "collections": collections, "_UNIT_AFTER": scd._UNIT_AFTER,
          "title": hook_title, "name": name, "code": code,
          "rejected": collections.Counter(),
          "print": lambda *a, **k: said.append(" ".join(str(x) for x in a))}
    exec(BLOCK, ns, ns)                      # noqa: S102  刻意執行產線原文
    pre = ns["_mk"](ns["_hook_pre"])
    blocked = ns["rejected"].get("rewrite_broke_number", 0) > 0
    return pre, ns["title"], (said[0] if (blocked and said) else None)


# ── 一、四種敵意輸入必須被擋 ─────────────────────────────────────────────────
print("【一】敵意輸入:改寫會弄壞數字,新閘門必須擋下並退回未改寫版")
facts = json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))["results"]
# 挑一組真事實當溯源母體(用它自己的代號當敵意值,才construct 得出「代號=統計數字」)
CASES = [
    ("2330", "台積電", "抱20年報酬2330%", "代號=真統計數字 → 數字被刪、留懸空的 %"),
    ("2330", "台積電", "報酬2330.5%不到你想的", "代號=小數整數部 → (?!\\d) 擋不住小數點"),
    ("2303", "聯電", "2303 vs 2303 對決十年誰贏", "代號出現兩次 → count=1 沒限制住"),
    ("2024", "億光", "2024年大跌40%你敢接嗎", "代號=年份 → 年份被吃掉"),
]
for code, name, hook, why in CASES:
    before, final, blocked = rewrite(hook, code, name)
    safe = (final == before)      # 最終標題等於未改寫版 = 那個真數字保住了
    print(f"\n   {why}")
    print(f"     改寫前:{before}")
    print(f"     最終  :{final}"
          + ("   ← 收斂器擋下,退回未改寫版" if blocked else
             "   ← 正規式本身就沒動它" if safe else "   ← 已改寫"))
    check(f"{why[:14]}… 真數字保住", safe)

# ── 二、407 筆真實已種題:零誤擋 ─────────────────────────────────────────────
print("\n【二】真實已種題:被改寫的那些必須全部通過新閘門(誤擋比誤放貴)")
bank = json.loads((STUDIO / "topic_bank.json").read_text(encoding="utf-8"))
rows = bank if isinstance(bank, list) else bank.get("topics", bank.get("items", []))
seeded = [t for t in rows if str(t.get("source", "")) == "stock_checkup_daily"
          and str(t.get("fact_key", "")).startswith("checkup_")]
bl = json.loads((STUDIO / "stock_checkup_backlog.json").read_text(encoding="utf-8"))
uni = {str(r["code"]): r.get("name", "") for r in (bl if isinstance(bl, list) else bl.get("items", []))
       if isinstance(r, dict) and r.get("code")}

n_rw = n_block = 0
blocked_rows = []
for t in seeded:
    title, fk = str(t.get("title", "")), str(t.get("fact_key", ""))
    m = re.search(r"__(\d{4})", fk)
    if not m:
        continue
    code = m.group(1)
    name = uni.get(code, "")
    hook = title
    for pre in (f"個股體檢{name}{code}：", f"個股體檢{code}："):
        if hook.startswith(pre):
            hook = hook[len(pre):]
            break
    before, final, blocked = rewrite(hook, code, name)
    if before == final and not blocked:
        continue
    n_rw += 1
    if blocked:
        n_block += 1
        blocked_rows.append((title, blocked))   # blocked 裡放的是「本來會改成什麼」

print(f"     已種題 {len(seeded)} 筆;會被改寫 {n_rw} 筆;收斂器擋下 {n_block} 筆")
for a, b in blocked_rows:
    print(f"       擋:{a[:52]}")
    print(f"          產線給的理由:{b.strip()[:96]}")
check("會被改寫的筆數 >= 60(改寫確實在動,不是空跑)", n_rw >= 60, f"實得 {n_rw}")
# 🔴 判準是「零**誤**擋」而不是「零擋下」。驗證員乾跑的 77 筆是拿**舊碼**跑的,
# 而舊碼沒有「句首懸空」這一道 —— 拿它當「必須全部通過」的基準,
# 會逼我把一個真陽性拿掉。菱生 2369 就是那一筆:`(2369) vs 0050十年對決` 去掉代號
# 會變成標題以「：vs 0050」開頭。退回只多印 7 個字元,不退回是一個讀起來壞掉的標題。
# 判準改成「產線自己說得出理由」:訊息裡要嘛列出少了/多了哪些數字,要嘛標明句首懸空。
# 這樣測試不必**再實作一次**判準 —— 第一版在這裡放了一份 DANGLE 正規式,
# 那是第三份實作(產線一份、rewrite() 一份、這裡一份)。
check("被擋下的每一筆,產線都說得出理由",
      all(("句首懸空" in b) or ("少了={}" not in b) for _a, b in blocked_rows),
      f"擋下 {n_block} 筆,全部可解釋" if blocked_rows else "沒有擋下任何一筆")

# ── 三、切塊邊界:_norm 到 append 之間不准再動 title ─────────────────────────
print("\n【三】切塊邊界(現在缺口 0,但那是約定不是保證)")
import ast as _ast
_tree = _ast.parse(_SRC)
_seg = _SRC[_B:_SRC.index("        new_recs.append(rec)")]
_stores = [n.id for n in _ast.walk(_ast.parse(textwrap.dedent(_seg)))
           if isinstance(n, _ast.Name) and isinstance(n.ctx, _ast.Store) and n.id == "title"]
check("`n = tb._norm(title)` 到 `new_recs.append` 之間沒有對 title 的 Store",
      not _stores, f"發現 {len(_stores)} 處")

print(f"\n合計 FAIL={fails}")
raise SystemExit(1 if fails else 0)
