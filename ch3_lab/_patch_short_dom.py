# -*- coding: utf-8 -*-
"""make_short 加第四條取材路徑:跨領域(domains)。

Shorts 是這條線的補給瓶頸:長片庫存夠 15 天,Shorts 只夠 1.8 天。
而 10,000 小時法則是需求分數第一名(24,311,第二名的 2.3 倍),
它的 Short 是目前單位成本最高的一支。

## 畫面為什麼要另外畫
現有的 `nums` 那一景是「大數字 → 箭頭 → 大數字」,那是為**一個效果量
對一個效果量**設計的。跨領域集沒有那兩個數字,它有五條橫條。
硬套會印出「None → None」。

直式反而更適合條狀圖:五條橫條由上而下排,手機上一眼看完。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "make_short.py"

COLLECT = '''    dm = ROOT / "eps_domain" / str(slug) / "facts.json"
    if dm.exists():
        from make_episode import CARD_TEXT, TONE_META
        E = json.loads(dm.read_text(encoding="utf-8"))
        T = E["test"]
        pc = _plain(f"eps_domain/{slug}")
        tone = E.get("tone", "shrunk_real")
        worst = min(T["domains"], key=lambda x: x["pct"])
        return {
            "key": slug,
            "question": pc["spoken"],
            "claim_lines": pc["lines"],
            "has_original": False,
            "es_o": None, "es_r": None,
            "n_o": None, "n_r": None,
            "say_o": None, "say_r": None,
            "domains": T["domains"], "worst": worst,
            "card": "Practice is not the whole story.",
            "tone": tone,
            "color": BUCKET_COLOR[TONE_META[tone]["bucket"]],
            "has_full": _has_full(f"eps_domain/{slug}"),
            "source": T["title"][:60],
        }

'''

SCRIPT = '''    if D.get("domains"):
        from make_domains import say_pct
        doms = D["domains"]
        return [
            ("q", D["question"]),
            ("nums",
             "Here is how much of the difference in performance it "
             "actually explains. "
             + " ".join(f"{d['name'].capitalize()}, {say_pct(d)}."
                        for d in doms)),
            ("end", end_line(D, "the paper")),
        ]
'''

RENDER = '''    elif name == "nums" and D.get("domains"):
        # 直式的橫條圖。滿格 = 表現的全部差異,上色 = 練習解釋掉的部分。
        from make_domains import fmt_pct
        ax.text(0.5, 0.86, "how much practice explains", ha="center",
                va="center", fontsize=fs.get("sub", 46), color=DIM)
        for i, d in enumerate(D["domains"]):
            if t < 0.4 + i * 1.5:
                continue
            b = ease(min(1.0, (t - 0.4 - i * 1.5) / 0.6))
            y = 0.74 - i * 0.10
            hot = d is D["worst"]
            ax.text(0.36, y, d["name"], ha="right", va="center", fontsize=44,
                    color=col if hot else FG, weight="bold", alpha=b)
            ax.add_patch(plt.Rectangle((0.40, y - 0.018), 0.30, 0.036,
                                       color="#252C36", alpha=b))
            ax.add_patch(plt.Rectangle((0.40, y - 0.018),
                                       d["pct"] / 100 * 0.30, 0.036,
                                       color=col, alpha=b))
            ax.text(0.72, y, fmt_pct(d), ha="left", va="center", fontsize=40,
                    color=col if hot else DIM, weight="bold", alpha=b)
        if t > 8.0:
            q = ease(min(1.0, (t - 8.0) / 0.8))
            for i, ln in enumerate(wrap(D["card"], 20)[:2]):
                ax.text(0.5, 0.30 - i * 0.05, ln, ha="center", va="top",
                        fontsize=fs.get("card", 58), color=FG, alpha=q,
                        weight="bold")
'''


def main():
    s = P.read_text(encoding="utf-8")
    if "eps_domain" in s:
        print("已經打過了"); return 0

    a1 = '    lu = ROOT / "eps_lineup" / str(slug) / "facts.json"'
    assert a1 in s, "找不到 lineup 取材分支"
    s = s.replace(a1, COLLECT + a1, 1)

    a2 = '    if D["es_o"] is None:\n'
    assert a2 in s, "找不到 build_script 分支點"
    s = s.replace(a2, SCRIPT + a2, 1)

    a3 = '    elif name == "nums":'
    assert a3 in s, "找不到 nums 場景"
    s = s.replace(a3, RENDER + a3, 1)

    # 字級量測:跨領域集不走 es_o / es_r 那組,補一個不會炸的預設
    a4 = '    fs["big"] = fit(plt'
    assert a4 in s
    s = s.replace('    if D["es_o"] is None:\n        head =',
                  '    if D.get("domains"):\n'
                  '        fs["sub"] = fit(plt, "how much practice explains", 46)\n'
                  '    elif D["es_o"] is None:\n        head =', 1)

    P.write_text(s, encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("make_short 已支援 domains,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
