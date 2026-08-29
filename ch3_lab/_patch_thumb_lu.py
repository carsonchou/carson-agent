# -*- coding: utf-8 -*-
"""縮圖佐證行:lineup 這一類要講「幾次重測」,不要把判決講第二遍。

## 抽出來看才發現的
social_priming 的縮圖長這樣:

    READ A WORD / AND BEHAVE DIFFERENTLY
    [ NOT FOUND ]
    Retested on 12,871 people. Not found.

判決塊已經是滿版的 NOT FOUND,佐證行又寫一次 Not found. —— 版面上
**唯一能放獨特資訊的那一行被拿去複述判決**。而這一集真正與眾不同的是
「不是一篇沒重現,是 6 種做法、12 次重測、一次都沒有」。

現有的 SCALE 只有兩種措辭(重做 / 統合),兩種都是**單一效應**的說法,
沒有「一整個家族」這一種。所以加第三種,而且只在 kind=lineup 時用 ——
不是改掉現有兩種,那 24 支已經上線的縮圖不能動。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "make_thumbs.py"

OLD = """    key = ("shrunk_real_nocmp" if tone == "shrunk_real" and eo is None
           else ctone)
    sub = (SCALE[has_orig].format(n=int(n_r), k=f.get("k"),
                                  k_word=f.get("k_word") or "studies")
           + " " + OUTCOME[key])"""

NEW = """    key = ("shrunk_real_nocmp" if tone == "shrunk_real" and eo is None
           else ctone)
    if o.get("kind") == "lineup":
        # 🔴 家族集:判決塊已經寫了 NOT FOUND,這行**不再複述**。
        #    它要回答的是「憑什麼這麼說」——次數與人數,那才是新資訊。
        sub = (f"{f['k']} replications. {int(n_r):,} people. "
               f"{f['n_sig']} worked.")
    else:
        sub = (SCALE[has_orig].format(n=int(n_r), k=f.get("k"),
                                      k_word=f.get("k_word") or "studies")
               + " " + OUTCOME[key])"""


def main():
    s = P.read_text(encoding="utf-8")
    if 'o.get("kind") == "lineup"' in s:
        print("已經打過了"); return 0
    assert OLD in s, "找不到佐證行那段"
    P.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("make_thumbs 佐證行已分軌,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
