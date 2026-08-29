# -*- coding: utf-8 -*-
"""Shorts 旁白:家族集不能用單數講。

`build_script` 的第三段對有原始效果量的集數唸的是:

    「The original study measured 0.59 on 660 people.
      The replication measured 0.07 on 12,871.」

對 FReD 單列是對的 —— 那真的就是一篇對一篇。但家族集的 0.59 / 0.07 是
**6 種做法、12 次重測的中位數**,唸成「the original study / the
replication」等於宣稱有那麼一篇研究,而它不存在。

每個數字都溯源得到,守門一個都不會擋 —— 這正是 memory 記的
「期間偷換」同型:數字真的,框架是錯的,而錯的方向讓故事更乾淨。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "make_short.py"

OLD = """    return [
        ("q", f"{D['question']}"),
        ("nums", f"The original study measured {D['say_o']} on "
                 f"{D['n_o']:,} people. "
                 f"The replication measured {D['say_r']} on {D['n_r']:,}."),
        ("end", end_line(D, "both papers")),
    ]"""

NEW = '''    if D.get("k_distinct"):
        # 家族集:先講**有幾種做法、重測幾次**,再講中位數,而且明講
        # 那是「typical」。少了 typical 這個字,同一句話就變成宣稱
        # 有一篇量到 0.59 的研究。
        return [
            ("q", f"{D['question']}"),
            ("nums", f"{D['k_distinct']} different setups. {D['k']} "
                     f"replications, on {D['n_r']:,} people. "
                     f"The typical original measured {D['say_o']}. "
                     f"The typical replication measured {D['say_r']}."),
            ("end", end_line(D, "every paper")),
        ]
    return [
        ("q", f"{D['question']}"),
        ("nums", f"The original study measured {D['say_o']} on "
                 f"{D['n_o']:,} people. "
                 f"The replication measured {D['say_r']} on {D['n_r']:,}."),
        ("end", end_line(D, "both papers")),
    ]'''


def main():
    s = P.read_text(encoding="utf-8")
    if "k_distinct" in s and "different setups" in s:
        print("已經打過了"); return 0
    assert OLD in s, "找不到 nums 那段"
    P.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("Shorts 旁白已分軌,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
