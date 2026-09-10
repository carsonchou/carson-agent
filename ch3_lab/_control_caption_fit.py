#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`cap_fit()` 的對照 —— 副標字級被自己的寬度收一次。

🔴 **這不是一道閘門,是一個修法。** 它不擋任何東西,它把字縮小。
   所以它要證的和閘門不一樣,要證三件:
   ① 對**現在放得下的那 59 個副標**是 no-op(修法不可以順手改動沒壞的東西)
   ② 對真的那一個越界案例(`if_then_plans` 的 weight 副標,實測左緣 **0.0154**)有效
   ③ **fail-closed 的後路沒有被拿掉** —— `fit()` 有 20pt 地板,
      長到 20pt 還放不下時,安全區守門仍然要炸。
      (不然這個修法就變成「把守門變成靜音」,那比不修更糟。)

⚠️ 母體是**全部 20 集 × 3 個副標位置 = 60 個副標**,不是新增的 6 集(memory `gate-verification-population`:
   改動的差集不是定義域)。
"""
import json
import pathlib
import sys

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib                                        # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                          # noqa: E402
import make_reel as M                                    # noqa: E402

#: 🔴 **這份清單就是這個修法的定義。**
CASES = [
    {"kind": "negative",
     "label": "現在放得下的 59 個副標(母體 20 集 × 3 個副標位置 = 60):cap_fit 算出的字級必須和修法前逐一相同(no-op)"},
    {"kind": "negative",
     "label": "全部 20 集、三個副標位置,套用後左右緣都在安全區內"},
    {"kind": "positive",
     "label": "真案例 if_then_plans/weight:修法前左緣 0.0154 越界,修法後收進安全區"},
    {"kind": "positive",
     "label": "長到 20pt 地板還放不下的副標:cap_fit 縮不動 ⇒ 安全區守門仍須判定越界"},
]

#: 三個副標位置的參數,和 render_scene 裡逐字一致。
POS = {"belief": dict(base=104, wrap=16, body_w="bold", cap=40, cap_w="normal"),
       "weight": dict(base=72, wrap=22, body_w="normal", cap=46, cap_w="bold"),
       "turn": dict(base=None, wrap=None, body_w=None, cap=42, cap_w="normal")}

FACTS = pathlib.Path(r"D:\carson-agent\ch3_lab\facts\rechecked_episodes.json")
CX = M.CAP_CX
ok = []


def say(good, msg):
    ok.append(good)
    print(f"  {'✓' if good else '🔴'} {msg}")


def body_fs(text, p):
    lines = [x for x in M.balanced(text, p["wrap"]) if x.strip()]
    return min(M.fit(plt, ln, p["base"], M.SAFE_X - (1 - M.SAFE_X), p["body_w"])
               for ln in lines)


def main():
    eps = json.loads(FACTS.read_text(encoding="utf-8"))["episodes"]
    print(f"母體:{len(eps)} 集(全部,不是新增的 6 集)")
    print(f"副標中心 CAP_CX={CX:.4f} 上限 CAP_MAX_FRAC={M.CAP_MAX_FRAC:.4f} "
          f"(= 2 × min({CX:.2f}−{M.MARGIN}, {M.SAFE_X}−{CX:.2f}))")

    noop, changed, over_after = 0, [], []
    print("\n【陰性 ①②】逐集逐位置:")
    for E in eps:
        r = E.get("reel") or {}
        caps = r.get("captions") or {}
        for name, p in POS.items():
            text = caps.get(name)
            if not text:
                continue
            before = p["cap"] if name == "turn" else M.sub_fs(body_fs(r[name], p),
                                                              p["cap"])
            after = M.cap_fit(plt, text, before, p["cap_w"])
            w = M.measure_w(plt, text, after, p["cap_w"])
            lo, hi = CX - w / 2, CX + w / 2
            if after == before:
                noop += 1
            else:
                changed.append((E["slug"], name, before, after))
            if not (lo >= M.MARGIN and hi <= M.SAFE_X):
                over_after.append((E["slug"], name, lo, hi))
    say(len(changed) == 1 and changed[0][:2] == ("if_then_plans", "weight"),
        f"no-op 的副標 {noop} 個;被改動的只有 "
        f"{[(c[0], c[1], f'{c[2]}→{c[3]}pt') for c in changed]}")
    say(not over_after, f"套用後仍越界的副標:{over_after or '無'}")

    print("\n【陽性 ③】真案例 if_then_plans/weight —— 修法前後對照:")
    E = next(e for e in eps if e["slug"] == "if_then_plans")
    text = E["reel"]["captions"]["weight"]
    p = POS["weight"]
    b = M.sub_fs(body_fs(E["reel"]["weight"], p), p["cap"])
    wb = M.measure_w(plt, text, b, "bold")
    a = M.cap_fit(plt, text, b, "bold")
    wa = M.measure_w(plt, text, a, "bold")
    print(f"    修法前 {b}pt 左緣 {CX - wb / 2:.4f}(界線 {M.MARGIN})")
    print(f"    修法後 {a}pt 左緣 {CX - wa / 2:.4f}")
    say(CX - wb / 2 < M.MARGIN, "修法前確實越界(這個對照本身抓得到問題)")
    say(CX - wa / 2 >= M.MARGIN and a < b, "修法後收進安全區,而且字級真的變小了")

    print("\n【陽性 ④】地板之下 —— 修法**不可以**把守門變成靜音:")
    longcap = "and here is who measured it and exactly how they did it twice over"
    a2 = M.cap_fit(plt, longcap, 46, "bold")
    w2 = M.measure_w(plt, longcap, a2, "bold")
    print(f"    {len(longcap)} 字的副標:cap_fit 縮到 {a2}pt(fit 的地板是 20pt),"
          f"左緣 {CX - w2 / 2:.4f}")
    say(a2 <= 20 and (CX - w2 / 2) < M.MARGIN,
        "縮不動了,而且仍然越界 ⇒ 安全區守門會炸,fail-closed 的後路還在")

    print()
    print("結論:", "✓ no-op 成立、真案例修掉了、而且沒有把守門變靜音" if all(ok)
          else "🔴 對照失敗 —— 這個修法不算數")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
