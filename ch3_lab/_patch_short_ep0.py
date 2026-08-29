# -*- coding: utf-8 -*-
"""make_short 加第五條取材路徑:頻道戰績(ep0)。

Shorts 是補給瓶頸(長片夠 16 天、Shorts 只夠 2 天),而**戰績本身**是
這條線上最強的鉤子:25 個點、一眼看完、而且它是唯一一支在講「這個頻道
是什麼」而不是「某個效應怎麼了」的 Short。

資料全部沿用 `eps_lineup/ep0/facts.json`(EP0 渲染時落的檔),不重算 ——
點的顏色與數字都從 `make_ep0.group_of` 來,跟長片、跟片中的標籤同一份。
今晚已經因為「點用三桶、標籤用五類」而讓 13 顆橘點配「12 gone」。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "make_short.py"

COLLECT = '''    if str(slug) == "ep0":
        fj = ROOT / "eps_lineup" / "ep0" / "facts.json"
        if fj.exists():
            import make_ep0 as _E
            T = json.loads(fj.read_text(encoding="utf-8"))
            pc = _plain("eps_lineup/ep0")
            return {
                "key": "ep0",
                "question": pc["spoken"],
                "claim_lines": pc["claim_lines"] if "claim_lines" in pc
                               else pc["lines"],
                "has_original": False,
                "es_o": None, "es_r": None, "n_o": None, "n_r": None,
                "say_o": None, "say_r": None,
                "scoreboard": T,
                "card": f"{T['survived']} of {T['k']} held up.",
                "tone": "held",
                "color": BUCKET_COLOR["held"],
                "has_full": _has_full("eps_lineup/ep0"),
                "source": "FORRT Replication Database (FReD), OSF 2tbvd",
            }

'''

SCRIPT = '''    if D.get("scoreboard"):
        T = D["scoreboard"]
        return [
            ("q", D["question"]),
            ("nums",
             f"So far, {T['k']} of them, and {T['n_sum']:,} people in the "
             f"replications. {T['gone']} are gone. {T['shrunk']} came back "
             f"smaller but still there. {T['flipped']} went the other way. "
             f"And {T['survived']} held up."),
            ("end", end_line(D, "every paper")),
        ]
'''

RENDER = '''    elif name == "nums" and D.get("scoreboard"):
        # 每一集一個點,依判決上色。**顏色與分組從 make_ep0 匯入** ——
        # 長片、長片裡的標籤、這支 Short,三個表面一份分類。
        from make_ep0 import group_of, GROUP_COLOR, GROUP_LABEL, GROUP_ORDER
        from matplotlib.patches import Ellipse
        T = D["scoreboard"]
        ax.text(0.5, 0.87, f"{T['k']} claims, retested", ha="center",
                va="center", fontsize=fs.get("sb_head", 54), color=FG,
                weight="bold")
        ax.text(0.5, 0.815, f"{T['n_sum']:,} people", ha="center",
                va="center", fontsize=fs.get("sb_sub", 42), color=DIM)
        rows = sorted(T["rows"], key=lambda r: GROUP_ORDER[group_of(r)])
        cols, step = 5, 0.088
        x0, y0 = 0.5 - (cols - 1) * step / 2, 0.70
        for i, r in enumerate(rows):
            if t < 0.4 + i * 0.06:
                continue
            b = ease(min(1.0, (t - 0.4 - i * 0.06) / 0.4))
            # 直式畫布:圓要把**寬度**乘上 H/W(1.78),不是高度。
            ax.add_patch(Ellipse(
                (x0 + (i % cols) * step, y0 - (i // cols) * step * (W / H)),
                width=0.052 * (H / W) * (W / H), height=0.052,
                color=GROUP_COLOR[group_of(r)], alpha=b))
        if t > 2.4:
            b = ease(min(1.0, (t - 2.4) / 0.6))
            for i, (g, lab) in enumerate(GROUP_LABEL.items()):
                n = sum(1 for r in T["rows"] if group_of(r) == g)
                ax.text(0.5, 0.44 - i * 0.045, f"{n}  {lab}", ha="center",
                        va="center", fontsize=fs.get("sb_lab", 38),
                        color=GROUP_COLOR[g], weight="bold", alpha=b)
        if t > 7.0:
            b = ease(min(1.0, (t - 7.0) / 0.6))
            for i, ln in enumerate(wrap(D["card"], 20)[:2]):
                ax.text(0.5, 0.30 - i * 0.05, ln, ha="center", va="top",
                        fontsize=min(fs.get("card", 58), 52), color=FG,
                        alpha=b, weight="bold")
'''

SIZES = '''    if D.get("scoreboard"):
        T = D["scoreboard"]
        fs["sb_head"] = fit(plt, f"{T['k']} claims, retested", 54)
        fs["sb_sub"] = fit(plt, f"{T['n_sum']:,} people", 42)
        from make_ep0 import GROUP_LABEL, group_of
        fs["sb_lab"] = min(
            fit(plt, f"{sum(1 for r in T['rows'] if group_of(r) == g)}  {lab}",
                38) for g, lab in GROUP_LABEL.items())
'''


def main():
    s = P.read_text(encoding="utf-8")
    if "scoreboard" in s:
        print("已經打過了"); return 0

    a1 = '    dm = ROOT / "eps_domain" / str(slug) / "facts.json"'
    assert a1 in s, "找不到 domains 取材分支"
    s = s.replace(a1, COLLECT + a1, 1)

    a2 = '    if D.get("domains"):\n        from make_domains import say_pct'
    assert a2 in s, "找不到 build_script 的 domains 分支"
    s = s.replace(a2, SCRIPT + a2, 1)

    a3 = '    elif name == "nums" and D.get("domains"):'
    assert a3 in s, "找不到 render 的 domains 場景"
    s = s.replace(a3, RENDER + a3, 1)

    a4 = '    if D.get("domains"):\n        fs["sub"] = fit('
    assert a4 in s, "找不到字級量測的 domains 分支"
    s = s.replace(a4, SIZES + a4, 1)

    P.write_text(s, encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("make_short 已支援 ep0 戰績,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
