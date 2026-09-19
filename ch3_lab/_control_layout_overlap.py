#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`make_reel.layout_guard()` 的對照 —— 安全區(個體)+ 兩兩重疊(關係)。

🔴 **這道守門有兩段,量的是兩種東西:**
   · 安全區:每個元素**自己**的四個邊 ⇒ 個體
   · 重疊:元素**兩兩之間**的交集 ⇒ 關係
   逐元素檢查對重疊是**結構性盲**的,而且它會回**全綠**。
   所以陽性對照最重要的一格不是「重疊被抓到」,是
   **「同一張圖上,安全區全綠而重疊叫了」** —— 兩段真的在量不同的東西。

真案例 = `marshmallow_test` 第三列(已上線的片實測兩欄相撞 22×10 畫素):
  what 「everything measured at the same time」 × value 「β = 0.05」
  (檢查清單上寫的「everything measured at t」是錯誤訊息裡 `[:24]` 的截斷)

⚠️ **不用合成矩形。** 這條的難點正是「真實字串的實際寬度」,
   fixture 只證明得了 fixture。
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
from make_rechecked import twist_rows, val_str           # noqa: E402

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative",
     "label": "全部 20 集的真表格,用現行兩欄算術排版 ⇒ layout_guard 全程安靜"},
    {"kind": "positive",
     "label": "真案例 marshmallow_test「everything measured at the same time」×"
              "「β = 0.05」,左欄字級改用**全幅**寬度算(= 不知道右欄存在,"
              "出事那版的形狀)⇒ 重疊必須叫,**而安全區對同一張圖全綠**"},
    {"kind": "positive",
     "label": "真字串放大到溢出畫面右緣 ⇒ 安全區那一段必須叫"
              "(兩段各自都要能獨立產生輸出)"},
]

FACTS = pathlib.Path(r"D:\carson-agent\ch3_lab\facts\rechecked_episodes.json")
ok = []


def say(good, msg):
    ok.append(good)
    print(f"  {'✓' if good else '🔴'} {msg}")


def fresh():
    fig = plt.figure(figsize=(M.W / 100, M.H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def guard(name, ax, fig):
    """跑 layout_guard,回 (有沒有叫, 訊息)。"""
    try:
        M.layout_guard(name, ax, fig)
        return None
    except SystemExit as e:
        return str(e)
    finally:
        plt.close(fig)


def lay_table(ax, rows, nf_mode="real"):
    """照 render_scene 的 turn 分支逐字排一張表。

    nf_mode="real" = 現行算術(左欄寬度**扣掉右欄之後**才算)
    nf_mode="fullwidth" = 出事那版的形狀(左欄用全幅寬度算,不知道右欄存在)
    """
    lefts = [r["label"] for r in rows]
    whats = [r["what"] for r in rows]
    vals = [val_str(r["es_kind"], r["es"], r.get("es_is_max", False))
            for r in rows
            if r.get("es") is not None and r.get("es_kind")] or ["x"]
    vw = max(M.measure_w(plt, v, 46) for v in vals)
    left_max = max(0.24, M.SAFE_X - vw - 0.04)
    if nf_mode == "real":
        lf = min(M.fit(plt, w, 40, left_max - 0.06, "bold") for w in lefts if w)
        nf = min(M.fit(plt, w, 34, left_max - 0.06, "normal")
                 for w in whats if w)
    else:                                   # 全幅:和主文用同一個常數
        full = M.SAFE_X - (1 - M.SAFE_X)
        lf = min(M.fit(plt, w, 40, full, "bold") for w in lefts if w)
        nf = min(M.fit(plt, w, 34, full, "normal") for w in whats if w)
    n = len(rows)
    gap = min(0.125, 0.50 / n)          # 逐字同 render_scene
    top = 0.60 + (n - 1) * gap / 2
    for i, x in enumerate(rows):
        y = top - i * gap
        ax.text(0.06, y + 0.022, x["label"], ha="left", va="center",
                fontsize=lf, color=M.DIM, weight="bold")
        ax.text(0.06, y - 0.020, x["what"], ha="left", va="center",
                fontsize=nf, color=M.FG, weight="normal")
        if x.get("es") is not None and x.get("es_kind"):
            ax.text(M.SAFE_X, y,
                    val_str(x["es_kind"], x["es"], x.get("es_is_max", False)),
                    ha="right", va="center", fontsize=46, color=M.FG,
                    weight="bold")
    return lf, nf, vw, left_max


def main():
    eps = json.loads(FACTS.read_text(encoding="utf-8"))["episodes"]

    print(f"【陰性】{len(eps)} 集的真表格,現行算術:")
    noisy = []
    for E in eps:
        fig, ax = fresh()
        lay_table(ax, twist_rows(E), "real")
        msg = guard(f"turn/{E['slug']}", ax, fig)
        if msg:
            noisy.append((E["slug"], msg.replace("\n", " ")[:110]))
    say(not noisy, f"叫出來的集數:{noisy or '無'}")

    print("\n【陽性 ①】真案例 marshmallow_test —— 左欄不知道右欄存在:")
    E = next(e for e in eps if e["slug"] == "marshmallow_test")
    rows = twist_rows(E)
    fig, ax = fresh()
    lf, nf, vw, left_max = lay_table(ax, rows, "fullwidth")
    print(f"    左欄字級 nf={nf}(現行算術會給 "
          f"{min(M.fit(plt, w, 34, left_max - 0.06, 'normal') for w in [r['what'] for r in rows] if w)})"
          f",右欄 vw={vw:.4f} 佔 {M.SAFE_X - vw:.4f}~{M.SAFE_X}")
    # 先問個體那一段:它看得到嗎?
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    out_of_zone = []
    for ob in list(ax.texts):
        bb = ob.get_window_extent(renderer=rend)
        for v, lo, hi in ((bb.x0 / M.W, M.MARGIN, M.SAFE_X),
                          (bb.x1 / M.W, M.MARGIN, M.SAFE_X),
                          (bb.y0 / M.H, M.SAFE_LO, M.SAFE_HI),
                          (bb.y1 / M.H, M.SAFE_LO, M.SAFE_HI)):
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                out_of_zone.append((ob.get_text()[:24], round(v, 4)))
    msg = guard("turn/marshmallow_test", ax, fig)
    print(f"    layout_guard 回:{(msg or '(安靜)').replace(chr(10), ' ')[:120]}")
    say(msg is not None and "文字重疊" in msg, "重疊那一段叫了")
    say(not out_of_zone,
        f"🔴 而**逐元素安全區對同一張圖全綠**(出界的元素:{out_of_zone or '無'})"
        f" —— 個體檢查看不到這一類")
    # 🔴 守門是**碰到第一對就中止**,所以它叫的未必是清單上那一對。
    #    要另外問清單上那一對本身撞不撞 —— 不然這一格證的是「有東西撞」,
    #    不是「那個真案例撞」。
    fig2, ax2 = fresh()
    lay_table(ax2, rows, "fullwidth")
    fig2.canvas.draw()
    r2 = fig2.canvas.get_renderer()
    box = {ob.get_text(): ob.get_window_extent(renderer=r2)
           for ob in ax2.texts}
    A = box["everything measured at the same time"]
    B = box["β = 0.05"]
    ox = min(A.x1, B.x1) - max(A.x0, B.x0)
    oy = min(A.y1, B.y1) - max(A.y0, B.y0)
    plt.close(fig2)
    print(f"    清單上那一對本身:交集 {ox:.0f}×{oy:.0f} 畫素")
    say(ox > 2 and oy > 2,
        "清單上那一對真字串(everything measured at the same time × β = 0.05)"
        "本身確實相交")

    print("\n【陽性 ②】安全區那一段自己也要能叫:")
    fig, ax = fresh()
    ax.text(0.06, 0.5, rows[2]["what"], ha="left", va="center",
            fontsize=46, color=M.FG, weight="normal")
    msg2 = guard("turn/safe-zone", ax, fig)
    print(f"    layout_guard 回:{(msg2 or '(安靜)').replace(chr(10), ' ')[:120]}")
    say(msg2 is not None and "越出安全區" in msg2, "安全區那一段叫了")

    print()
    print("結論:", "✓ 兩段各自都會叫、對真表格都安靜,而且關係那段抓得到"
                   "個體那段結構性看不到的東西" if all(ok)
          else "🔴 對照失敗 —— 這道守門不算數")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
