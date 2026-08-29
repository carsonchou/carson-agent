# -*- coding: utf-8 -*-
"""Shorts:修文字互相重疊,並把「重疊」加進守門。

## 抽幀才看得到的事
`nums` 那一景的下半:

    -0.87                    ← es_r,270pt
    the replication — 776 people   ← y=0.345
    It came back larger.           ← 判決卡 y=0.32,58pt

判決卡的字身往上長到 0.362,直接壓過 0.345 那行。**16 支已上線的
Short 全部都這樣**(ep007 實測),不是這次新集型才有的。

## 為什麼守門沒抓到
現有的斷言掃過每一個 text 與 patch,檢查它的四個邊有沒有超出安全區。
**逐個檢查邊界,永遠看不到兩個都在界內的東西壓在一起。**
這跟今天長片那張塌陷圖的字壓在座標軸標籤上是同一件事:
版面守門只有「出不出界」一個維度。

## 改了什麼
1. 版面:判決卡改用 va="top" 定位(可預測),下移到 0.335 / 0.285;
   `sub_r` 抬到 0.365、`es_r` 抬到 0.475,讓出空間。
2. 守門:加**兩兩相交**檢查。只比對 `ax.texts`(色塊本來就是背景,
   壓在色塊上是設計),而且要求水平方向也真的重疊 —— 只有垂直區間
   相交但左右錯開的兩行字並不會互相蓋住。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "make_short.py"

LAYOUT_OLD = """        if t > 2.6:
            q = ease(min(1.0, (t - 2.6) / 0.9))
            ax.text(0.5, 0.45, f"{D['es_r']:+.2f}".replace("+", ""),
                    ha="center", va="center", fontsize=fs.get("es_r2", 270),
                    color=col, alpha=q, weight="bold")
            ax.text(0.5, 0.345, f"the replication — {D['n_r']:,} people",
                    ha="center", fontsize=fs.get("sub", 46), color=col, alpha=q)
        if t > 4.4:
            q = ease(min(1.0, (t - 4.4) / 0.9))
            for i, ln in enumerate(wrap(D["card"], 20)[:2]):
                ax.text(0.5, 0.32 - i * 0.05, ln, ha="center",
                        fontsize=fs.get("card", 58), color=FG, alpha=q,
                        weight="bold")"""

LAYOUT_NEW = """        if t > 2.6:
            q = ease(min(1.0, (t - 2.6) / 0.9))
            ax.text(0.5, 0.475, f"{D['es_r']:+.2f}".replace("+", ""),
                    ha="center", va="center", fontsize=fs.get("es_r2", 270),
                    color=col, alpha=q, weight="bold")
            ax.text(0.5, 0.365, _lbl(D)[1], ha="center",
                    fontsize=fs.get("sub", 46), color=col, alpha=q)
        if t > 4.4:
            q = ease(min(1.0, (t - 4.4) / 0.9))
            # 🔴 用 va="top" 定位,位置才可預測。原本是預設的 baseline,
            #    字身往**上**長,於是「卡片在 0.32、標籤在 0.345」看起來
            #    有 0.025 的間距,實際上重疊 0.017。已上線的 16 支都中招。
            for i, ln in enumerate(wrap(D["card"], 20)[:2]):
                ax.text(0.5, 0.335 - i * 0.05, ln, ha="center", va="top",
                        fontsize=fs.get("card", 58), color=FG, alpha=q,
                        weight="bold")"""

SUBO_OLD = """            ax.text(0.5, 0.705, f"the original — {D['n_o']:,} people",
                    ha="center", fontsize=fs.get("sub", 46), color=DIM, alpha=q)"""
SUBO_NEW = """            ax.text(0.5, 0.705, _lbl(D)[0],
                    ha="center", fontsize=fs.get("sub", 46), color=DIM, alpha=q)"""

FS_OLD = """            f"the original — {D['n_o']:,} people",
            f"the replication — {D['n_r']:,} people"))"""
FS_NEW = """            *_lbl(D)))"""

# 標籤模板:家族集不能用單數。旁白那份已經改了,畫面這份**上一輪漏掉**
# —— 「同一句話三份只修最安靜的那份」的第二現場。
LABELS = '''
#: 對比兩行的標籤。**單數 / 複數兩套**:FReD 單列真的是一篇對一篇,
#: 家族集的 0.59 / 0.07 是 6 種做法、12 次重測的中位數,講成
#: 「the original / the replication」等於宣稱有那麼一篇研究。
#: ⚠️ 旁白那份(build_script)先改了,畫面這份漏掉 —— 同一個錯的第二個
#:    表面,而畫面那份是觀眾真的會盯著看的那個。
LBL_O = "the original — {n_o:,} people"
LBL_R = "the replication — {n_r:,} people"
LBL_O_FAM = "typical original — {k_distinct} setups"
LBL_R_FAM = "typical replication — {k} runs, {n_r:,} people"


def _lbl(D):
    """(上標籤, 下標籤)。有 k_distinct 就是家族集,用複數那套。"""
    if D.get("k_distinct"):
        return LBL_O_FAM.format(**D), LBL_R_FAM.format(**D)
    return LBL_O.format(**D), LBL_R.format(**D)

'''

OVERLAP = '''
    # 🔴 **兩兩相交**。上面那圈逐個檢查邊界,對「兩個都在界內但壓在一起」
    #    結構上是盲的 —— 判決卡壓在 the replication 那行上面,16 支已上線
    #    的 Short 全部都是,而守門一次都沒響過。
    #    只比 texts:壓在色塊上是設計(判決字就在色塊裡)。
    #    水平也要真的相交,否則左右錯開的兩行會被誤報。
    _boxes = []
    for _o in ax.texts:
        try:
            _b = _o.get_window_extent(renderer=_r)
        except TypeError:
            _b = _o.get_window_extent()
        if _o.get_alpha() is not None and _o.get_alpha() < 0.35:
            continue          # 還在淡入的不算 —— 它下一幀就滿版了
        _boxes.append((_o.get_text()[:24], _b))
    for _i in range(len(_boxes)):
        for _j in range(_i + 1, len(_boxes)):
            (_ta, _a), (_tb, _b2) = _boxes[_i], _boxes[_j]
            _ox = min(_a.x1, _b2.x1) - max(_a.x0, _b2.x0)
            _oy = min(_a.y1, _b2.y1) - max(_a.y0, _b2.y0)
            if _ox > 2 and _oy > 2:
                raise SystemExit(
                    f"⛔ 文字重疊:「{_ta}」和「{_tb}」重疊 "
                    f"{_ox:.0f}×{_oy:.0f} 畫素 —— 版面斷言只看得到出界,"
                    f"這種只有抽幀看得到,所以在這裡擋。")
'''


def main():
    s = P.read_text(encoding="utf-8")
    if "LBL_O_FAM" in s:
        print("已經打過了"); return 0

    anchor = "def build_script(D):"
    assert anchor in s
    s = s.replace(anchor, LABELS.lstrip("\n") + "\n" + anchor, 1)

    for old, new, what in ((LAYOUT_OLD, LAYOUT_NEW, "下半版面"),
                           (SUBO_OLD, SUBO_NEW, "上半標籤"),
                           (FS_OLD, FS_NEW, "字級量測")):
        assert old in s, f"找不到:{what}"
        s = s.replace(old, new, 1)

    tail = "    # 上面量框時已經 draw 過,不要再畫一次"
    assert tail in s
    s = s.replace(tail, OVERLAP.lstrip("\n") + "\n" + tail, 1)

    P.write_text(s, encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("版面已修 + 重疊守門已加,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
