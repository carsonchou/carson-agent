#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_bounds.py — 用現行碼把每一支的每一段掃過,看版面斷言會不會叫。

比 lint_short 快(不用 ffmpeg 抽幀),而且測的是**現行碼會畫出什麼**
而不是「已經渲好的檔長什麼樣」—— 兩個問題不一樣,兩個都要問。
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import make_short as M                                        # noqa: E402

FAMOUS = ["ego_depletion", "bystander_effect", "implicit_bias_test",
          "sleep_memory", "romantic_red"]


def main():
    plt = M._plt()
    bad = 0
    for kind, v in ([("row", r) for r in range(19)] +
                    [("slug", s) for s in FAMOUS]):
        D = M.collect(**{kind: v})
        D["_fs"] = M.fit_sizes(plt, D)
        hit = False
        for n, _ in M.build_script(D):
            for t in [i * 1.0 for i in range(13)]:
                try:
                    M.render(plt, n, t, 12.0, D)
                except SystemExit as e:
                    print(f"{D['key']:20s} {n} t={t:.0f}s  {str(e)[:90]}")
                    hit = True
                    break
            if hit:
                break
        bad += 1 if hit else 0
    print(f"\n現行碼會越界的:{bad}/24")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
