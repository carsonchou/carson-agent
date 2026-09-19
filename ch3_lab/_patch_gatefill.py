# -*- coding: utf-8 -*-
"""把 Shorts 的發布閘門收成單一入口,而且**每一道擋下都補件**。

## 獨立驗證抓到的不對稱
`cta_gate` 擋掉一支會從候補補一支上來(而且補進來的會再跑一次閘門);
`visual_stale` 擋掉一支就**直接讓 todo 少一支,不補**。

後果不是少發一支而已:排序把名案排在最前面,所以只要前面幾支被畫面
閘門擋住,後面 ep012–ep018 那幾支**乾淨的片就永遠輪不到**。實測明天
16:25 只發得出 1 支(排程要 2 支)、22:25 也只發得出 1 支(要 3 支)。

一個「補了不檢查」、一個「檢查了不補」——同一個位置的鏡像問題,
而我上一次只修了前者。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "publish_shorts.py"

OLD_START = "    todo = todo[:a.limit]\n    if not todo:"
OLD_END = '''        for key, probs in vunknown:
            if probs:
                print(f"   {key:<22}已知缺陷:{probs[0]}")
            else:
                print(f"   {key:<22}四個邊都量過,沒有越界 ✓"
                      f"(但仍非「畫面是最新版」的證明)")'''

NEW = '''    # ── 閘門 + 補件:**單一入口** ────────────────────────────────
    # 🔴 舊版 cta_gate 擋了會補件、visual_stale 擋了不補。後果不是少發
    #    一支:排序把名案排在最前面,前幾支被畫面閘門擋住之後,
    #    ep012–ep018 那幾支乾淨的片**永遠輪不到**。實測明天 16:25 只發
    #    得出 1 支(排程要 2)、22:25 只發得出 1 支(要 3)。
    #    一個補了不檢查、一個檢查了不補 —— 同一個位置的鏡像問題,
    #    而我上一次只修了前者。
    def _gate(batch):
        """所有發布前閘門跑一遍。回傳 ({key: 理由}, 無法判斷的)。"""
        bad = {}
        for k, why in cta_gate(batch, _LONGS_PUB, _LONGS_ALL):
            bad[k] = why
        ch, unk = visual_stale(batch)
        for k, w in ch:
            bad.setdefault(k, f"畫面已跟現行碼不同(差在 {w})")
        return bad, unk

    pool = todo
    todo, rest = pool[:a.limit], pool[a.limit:]
    blocked_all, vunknown = {}, []
    for _round in range(12):          # 有界:候補用完或名額補滿就停
        bad, vunknown = _gate(todo)
        if not bad:
            break
        blocked_all.update(bad)
        todo = [o for o in todo if o["key"] not in bad]
        if not rest:
            break
        while len(todo) < a.limit and rest:
            todo.append(rest.pop(0))
    if blocked_all:
        print("⛔ 這幾支被閘門擋下(已從候補補件):")
        for k_, why in blocked_all.items():
            print(f"   {k_:<22}{why}")
    if not todo:
        print("沒有待上傳的 Short")
        return 0
    if vunknown:
        print("❗ 這幾支沒有畫面計畫檔(舊版渲的)。算不出它當時的計畫,"
              "所以改成**直接量檔案**:")
        for key, probs in vunknown:
            if probs:
                print(f"   {key:<22}已知缺陷:{probs[0]}")
            else:
                print(f"   {key:<22}四個邊都量過,沒有越界 ✓"
                      f"(但仍非「畫面是最新版」的證明)")'''


def main():
    s = P.read_text(encoding="utf-8")
    if "def _gate(batch):" in s:
        print("已經打過了"); return 0
    i = s.index(OLD_START)
    j = s.index(OLD_END) + len(OLD_END)
    s = s[:i] + NEW + s[j:]
    P.write_text(s, encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("閘門與補件已收成單一入口,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
