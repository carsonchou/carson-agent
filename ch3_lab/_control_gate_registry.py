#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_registry 這支 meta 檢查自己的對照。**用今晚三輪的三個真形狀,不是合成 fixture。**

三個形狀是同一個病:**規則寫在一個不會產生輸出的位置。**
R1 存進沒人讀的欄位 / R2 只寫在錯誤訊息裡 / R3 只寫在 docstring。

做法:拿**真的模組原始碼**,把歷史上那個變異套回去,看偵測器叫不叫。
不用手寫一份 fixture —— fixture 只證明得了 fixture。

⚠️ 這支治不了的:**案例清單自己會過期**(memory `gate-blind-while-target-evolves`)。
   它需要定期用真案例證明它還抓得到。這件事沒有完結。
"""
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import gate_registry as gr  # noqa: E402

ROOT = pathlib.Path(r"D:\carson-agent\ch3_lab")

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative", "label": "現況的三道閘門:R1/R2/R3 都不該叫"},
    {"kind": "positive",
     "label": "R1 真形狀:CONTROL 宣告了但沒有任何地方讀它"
              "(= prereg_title 零讀取者)"},
    {"kind": "positive",
     "label": "R2 真形狀:訊息點名 display_only_why 而程式從來沒讀過它"
              "(= 規則只寫在錯誤訊息裡)"},
    {"kind": "positive",
     "label": "R3 真形狀:docstring 的產生區塊被換成一個被放棄的設計"
              "(= window_readout 的「唯一可靠的判準是數列數」)"},
]

ok = []


def say(tag, hit, want, msg=""):
    good = bool(hit) == want
    ok.append(good)
    print(f"  {'✓' if good else '🔴'} {tag}: "
          f"{'叫了' if hit else '沒叫'}" + (f" —— {str(msg)[:80]}" if hit else ""))


SRC = (ROOT / "make_reel.py").read_text(encoding="utf-8")

print("【陰性】現況的三道閘門,三個偵測器都不該叫:")
for gid in gr.GATES:
    g = gr.GATES[gid]
    s = (ROOT / f"{g['module']}.py").read_text(encoding="utf-8")
    h1, h2 = gr.detect_r1(s, gid), gr.detect_r2(s, gid)
    h3 = gr.detect_r3(ROOT / f"{g['module']}.py", gid)
    say(f"{gid} R1", h1, False, h1)
    say(f"{gid} R2", h2, False, h2)
    say(f"{gid} R3", h3, False, h3)

print("【陽性 R1】把 CONTROL 的所有讀取拿掉(宣告留著)——"
      "和 prereg_title 零讀取者同型:")
mut = SRC.replace("{CONTROL}", "(見對照腳本)")
say("make_reel 沒有人讀 CONTROL", gr.detect_r1(mut, "reel.orphan_value"),
    True, gr.detect_r1(mut, "reel.orphan_value"))

print("【陽性 R2】把 display_only_why 的讀取拿掉,訊息照樣點名它 ——"
      "和「規則只寫在錯誤訊息裡」同型:")
mut2 = SRC.replace("why = x.get('display_only_why')", "why = 'x'")
hit = gr.detect_r2(mut2, "reel.display_vs_facts")
say("訊息點名一個從來沒被讀過的欄位", hit, True, hit)

print("【陽性 R3】把產生區塊換成那個被放棄的設計 ——"
      "和 window_readout 的 docstring 同型:")
b, e = gr._marks("reel.orphan_value")
mut3 = re.sub(re.escape(b) + r".*?" + re.escape(e),
              b + "\n唯一可靠的判準是數列數:回的列數必須等於窗長。\n" + e,
              SRC, flags=re.S)
with tempfile.TemporaryDirectory() as td:
    p = pathlib.Path(td) / "make_reel.py"
    p.write_text(mut3, encoding="utf-8")
    hit = gr.detect_r3(p, "reel.orphan_value")
    say("docstring 描述一個被放棄的設計", hit, True, hit)

print()
print("結論:", "✓ 三個真形狀都抓得到,而且對現況不誤叫" if all(ok)
      else "🔴 有形狀抓不到 —— 這支 meta 檢查還沒做完")
sys.exit(0 if all(ok) else 1)
