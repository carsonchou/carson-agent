#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_short.py — 從已完成的集數剪一支直式 Short 當引流。

## 為什麼做 Shorts(以及它的代價)
記憶裡有一條硬事實:**Shorts 的觀看不計入 YPP 的 4,000 小時**,而且主頻道
實測 Shorts 的訂閱轉化只有長片的十分之一(0.05% vs 0.46%)。所以在一個
已經有觀眾的頻道上,Shorts 是錯的選擇。

但這個頻道現在是 **10 支片、2 次觀看、0 訂閱** —— 沒有任何分發管道。
YPP 是「有觀眾之後」的問題,現在的問題是**一個觀眾都沒有**。而 Shorts 是
零訂閱頻道唯一會被演算法主動推的格式。

所以定位很明確:**Short 負責被發現,長片負責累積時數**。Short 的說明第一行
就導到完整版,不是取代它。

## 誠信
數字與定調一律沿用該集的事實庫,不重算、不加強。Short 只是把同一個結論
講得更短 —— 它沒有版面放信賴區間,所以**也不做存在性斷言**,只呈現
「當年 X → 重測 Y」這個可驗證的對比,結論留給完整版。

用法:
  python make_short.py --slug ego_depletion
  python make_short.py --row 3
"""
import argparse
import itertools
import json
import pathlib
import subprocess
import sys
import wave

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
W, H, FPS = 1080, 1920, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"
BUCKET_COLOR = {"fail": "#F5A54E", "mixed": "#8FA3C8", "held": "#5FC98A"}

#: 開場卡的強調色。**刻意不用 BUCKET_COLOR** —— 那是判決色,在第一幀
#: 就上判決色等於在觀眾讀到主張之前先劇透結局。這支琥珀色只代表
#: 「這是一個被拿去重測的說法」,對五種定調都一樣。
ACCENT = "#FFC23D"
#: 開場那條標籤。它必須對**每一支**都成立 —— 這些主張全部來自已發表的
#: 原始研究(FReD 的每一列就是一則原始發現),所以「A STUDY FOUND」
#: 是事實陳述而不是修辭。資料裡真的找不到原始研究時改用中性字眼,
#: 見 render()。
KICKER, KICKER_FALLBACK = "A STUDY FOUND", "THE CLAIM"
#: 開場主張區塊的垂直預算與行距係數。
#: LINE_K:字級(pt)換算成畫面高度比例的行距 —— dpi=100 時 1pt = 1.389px,
#: 行距取 1.25 倍,除以 H=1920 得 0.000904。
#: BLOCK_H:主張可以佔的高度(0.34 ~ 0.72),下面要留給底線和下一段。
#: BLOCK_MID:主張區塊的垂直中心。
LINE_K, BLOCK_H, BLOCK_MID = 0.000904, 0.42, 0.545


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    return plt


#: Shorts 的 UI 覆蓋區。內容只能待在這塊裡面 ——
#  右邊是按讚/留言/分享那一欄,下面是標題列與頻道名。
SAFE_X, SAFE_LO, SAFE_HI = 0.86, 0.24, 0.93


def ease(x):
    return x * x * (3 - 2 * x)


def fit(plt, text, base, weight="bold", max_frac=None):
    """量出這段字在 base 字級下有多寬,太寬就回傳縮小後的字級。

    ## 為什麼要量而不是挑一個「應該可以」的數字
    我已經靠肉眼調過兩輪字級,兩輪都還是越界(實測右緣 0.897、0.899、
    0.908),每一輪都要重渲 24 支。問題在於**文案長度會變**:「23
    laboratories」和「105 independent effect sizes」放同一個位置,一個
    字級不可能同時對。

    所以改成量:文字寬度跟字級是線性的,在參考字級量一次就能反推
    合身的字級。這樣以後換任何文案都不會再越界。
    """
    m = max_frac if max_frac is not None else (SAFE_X - 0.5) * 2
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    t = ax.text(0.5, 0.5, text, ha="center", va="center",
                fontsize=base, weight=weight)
    fig.canvas.draw()
    bb = t.get_window_extent(renderer=fig.canvas.get_renderer())
    frac = bb.width / (W)
    plt.close(fig)
    if frac <= m or frac == 0:
        return base
    return max(24, int(base * m / frac))


def wrap(s, n):
    out, line = [], ""
    for w in s.split():
        if len(line) + len(w) + 1 > n:
            out.append(line); line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


def build_script(D):
    """三段,約 32 秒。刻意不下存在性結論 —— 那需要信賴區間,而這裡沒有版面。

    名案走另一條:統合分析**沒有單一「原始效果量」**,所以「X → Y」對比
    做不出來。但名案的故事本來就不是 X → Y —— 是「你聽過的說法」對上
    「量出來的數字」,而那個說法本身就是鉤子(意志力會用完、旁觀者效應)。
    對零訂閱頻道來說,這反而是唯一有人認得的題材。
    """
    if D["es_o"] is None:
        # k_word 有兩種:**會做事的**(laboratories / experiments)和
        # **統計單位**(independent effect sizes / samples)。後者不能接
        # 「tested it」——效果量不會測試東西。這不是語感問題,是把統合
        # 分析的結構講錯了。
        kw = D.get("k_word") or ""
        agent_like = any(x in kw for x in ("laborator", "experiment", "lab",
                                           "team", "studies", "replication"))
        if not D.get("k"):
            scale = f"It was tested again, on {D['n_r']:,} people. "
        elif agent_like:
            scale = f"{D['k']} {kw} tested it, on {D['n_r']:,} people. "
        else:
            scale = (f"It was pooled across {D['k']} {kw}, "
                     f"{D['n_r']:,} people in total. ")
        return [
            ("q", f"{D['question']}"),
            ("nums", scale + f"The effect came back {D['say_r']}."),
            ("end", end_line(D, "the paper")),
        ]
    return [
        ("q", f"{D['question']}"),
        ("nums", f"The original study measured {D['say_o']} on "
                 f"{D['n_o']:,} people. "
                 f"The replication measured {D['say_r']} on {D['n_r']:,}."),
        ("end", end_line(D, "both papers")),
    ]


def end_line(D, papers):
    """收尾那句。**只在完整版真的已經發布時才提它**。

    ## 為什麼這件事值得一個函式
    「完整版在本頻道」這句宣稱在一支 Short 裡有**三份**:說明欄、旁白、
    片尾卡的滿版大字。說明欄是發布時動態組的,旁白與片尾卡在渲染當下就
    烘進 mp4。實際踩過:`implicit_bias_test` 的長片因為畫面缺陷被轉成
    unlisted,我只把說明欄那一行拿掉,於是**假話被從最安靜的管道移除、
    留在最大聲的兩個** —— 觀眾停留的最後一個畫面仍然是滿版的
    「Full episode / on the channel」。

    這裡負責旁白與片尾卡那兩份;`publish_shorts.cta_gate` 負責「渲完之後
    長片才下架」那種渲染時無法預知的情況。兩層都要有:渲染時的條件判斷
    擋不住之後的狀態變化,發布時的閘門也救不回已經烘進去的字。
    """
    if D.get("has_full"):
        return (f"The full breakdown, with {papers} and the record it comes "
                f"from, is on the channel.")
    return ("Every number here comes from the FORRT Replication Database — "
            "one public row per finding.")


def visual_plan(plt, D):
    """這支片的畫面**會長什麼樣**,落成可比對的資料。

    ## 為什麼需要它
    陳舊檢查比的是**旁白內容**(只比 mtime 會誤擋 —— make_episode 的多數
    改動對 Short 沒影響)。但那條判準對「**畫面的碼改了、旁白一字沒動**」
    是全盲的:舊視覺的 mp4 會直接通過,然後被發出去。

    ## 為什麼不是雜湊程式碼
    我第一版想雜湊 `render`/`fit_sizes` 的原始碼。那會犯下跟 mtime 同一個
    毛病:**輸出中性的改動也會誤擋**。實例就在今天 —— 片尾卡改成看
    `has_full` 之後,五支名案的 `has_full` 全是 True,畫出來一個像素都沒變,
    但原始碼雜湊變了。

    所以記的是**產出的計畫**,不是產生它的程式:字級、片尾卡那兩行實際
    會寫什麼、判決句、顏色。碼怎麼改都行,只要畫出來一樣就算一樣 ——
    跟旁白那條判準同一個道理。
    """
    return {
        "fs": fit_sizes(plt, D),
        "end_card": (["Full episode", "on the channel"] if D.get("has_full")
                     else ["Every number", "from the record"]),
        "card": D["card"],
        "color": D["color"],
        "source": D["source"],
        # 開場卡:手寫兩行 + 標籤。**這是第一幀**,也就是這支片在 feed 裡
        # 的縮圖 —— 它變了就是換了一支片,一定要進計畫。
        "claim_lines": D["claim_lines"],
        "kicker": KICKER if D.get("has_original") else KICKER_FALLBACK,
        "accent": ACCENT,
        # ⚠️ 這幾個是**輸出語義**不是實作細節,所以放得進「計畫」:
        #    改 W/H 會讓它不再是直式(那是 YouTube 判定 Short 的條件),
        #    改安全區等於改「哪裡看得見」,改配色等於換一支片的外觀。
        #    這些改了而計畫不動的話,閘門就是瞎的。
        "canvas": [W, H, FPS],
        "palette": [BG, FG, DIM],
        "safe": [SAFE_X, SAFE_LO, SAFE_HI],
    }


#: 取樣點:每一段各取三個時間比例。固定不變,兩邊才算得出同一個值。
SAMPLE_AT = (0.05, 0.5, 0.92)


def frame_digest(plt, D, durs):
    """重畫幾個取樣幀再雜湊 —— 這是唯一連**幾何與時間**都蓋得到的判準。

    `visual_plan` 記的是文字與字級,對寫死的 y 座標、淡入時點、`ease()`
    完全免疫:把 `0.66` 改成 `0.70`,版面移了但計畫一個位元都不會變。
    而「內容掉進 UI 覆蓋區」正是這條線出過事的那一類。

    ## 為什麼是「重畫」不是「讀已渲好的檔」
    發布端要能**用現行碼算出同一個東西來比對**,否則這個雜湊只能證明
    「mp4 沒被換掉」,不能回答真正的問題:「現行碼渲出來會不會不一樣」。
    所以取樣點定成固定的時間比例,兩邊各自呼叫 `render()` 重畫 —— 9 個
    figure 約兩秒,而它蓋掉位置、時間、顏色、字型全部。

    縮到 32×32 灰階再雜湊:吸收抗鋸齒的微小差異,但任何**看得出來的**
    改動都會反映。

    ⚠️ pixel 雜湊受 matplotlib 與字型版本影響,**跨機器不可比**。渲染與
    比對都只在這台產線機上,所以可接受 —— 但哪天搬機器,預期它會全部
    回報「畫面變了」,那不是 bug。
    """
    import hashlib
    h = hashlib.md5()
    for n in sorted(durs):
        d = durs[n] + 0.5
        for frac in SAMPLE_AT:
            a = render(plt, n, d * frac, d, D)[:, :, :3].astype("int32")
            g = a.mean(axis=2)
            s0, s1 = g.shape[0] // 32, g.shape[1] // 32
            small = g[:s0 * 32, :s1 * 32].reshape(32, s0, 32, s1).mean(axis=(1, 3))
            h.update(small.round().astype("uint8").tobytes())
    return h.hexdigest()[:16]


def balance(text, n):
    """把 text 斷成剛好 n 行,**盡量等長**。斷不成回 None。

    標準的貪婪換行(`wrap`)在這裡會生出孤字:
    「WILLPOWER RUNS OUT AS YOU USE IT」斷四行是
    「WILLPOWER / RUNS OUT / AS YOU USE / IT」—— 最後一行一個「IT」。
    貪婪法把字塞滿每一行,剩下的自己一行,行數越少越明顯。

    這裡改成在所有可能的斷點裡挑「最長那行最短」的(同分再挑總參差
    最小的)。字數少(≤ 10 個字)、行數 ≤ 4,直接窮舉就好。
    """
    words = text.split()
    if n > len(words):
        return None
    best = None
    for cuts in itertools.combinations(range(1, len(words)), n - 1):
        idx = (0,) + cuts + (len(words),)
        lines = [" ".join(words[idx[i]:idx[i + 1]]) for i in range(n)]
        L = [len(x) for x in lines]
        key = (max(L), sum((x - sum(L) / n) ** 2 for x in L))
        if best is None or key < best[0]:
            best = (key, lines)
    return best[1]


def claim_layout(plt, D):
    """開場那句主張在**直式**畫面上要怎麼排:斷成幾行、多大、放哪。

    ## 為什麼不能直接用手寫的那兩行
    `plain_claims.json` 的兩行斷句是為 **16:9 縮圖**寫的 —— 那裡寬 1178px。
    直式 Short 扣掉右側按讚欄之後只剩 778px,同樣兩行硬塞進去,長的那幾支
    (「DRAINS YOUR SELF-CONTROL」)會被縮到**比上面那條標籤還小**,
    版面階層整個反過來:標籤變主角,主張變註解。

    有意義的是**那句話**,不是斷在哪。所以這裡把兩行接回一句,再依直式
    畫面重新斷 —— 字義不動,只動換行。

    ## 怎麼選斷點
    掃過所有可能的每行字數,挑「字級最大」的那個,限制是行數 ≤ 4、
    整塊高度塞得進 0.34~0.72。用挑的而不是寫死一個寬度:主張長度從
    9 字(WILLPOWER…)到 45 字都有,任何寫死的值都會有幾支被犧牲。
    """
    text = " ".join(D["claim_lines"])
    cands = []
    for n in (2, 3, 4):
        lines = balance(text, n)
        if lines is None:
            continue
        fs = min(fit(plt, ln, 140) for ln in lines)
        fs = min(fs, BLOCK_H / (n * LINE_K))            # 高度上限
        cands.append((lines, fs))
    top_fs = max(c[1] for c in cands)
    # 🔴 **不是挑字級最大的那個。** 只看字級的話永遠會挑到 4 行 ——
    #    字級被高度上限鎖住,行數越多每行越短、量出來的字級越大,
    #    於是「WILLPOWER RUNS OUT AS YOU USE IT」被斷成
    #    「… / AS YOU USE / IT」,最後一行只剩一個孤字。
    #    所以先用字級篩掉明顯太小的(< 92%),剩下的裡面挑**行數最少**,
    #    同分再挑「最後一行不會太短」的。
    def score(c):
        lines, fs = c
        longest = max(len(x) for x in lines)
        orphan = len(lines[-1]) < longest * 0.4      # 孤字結尾
        return (len(lines), orphan, -fs)
    lines, fs = min([c for c in cands if c[1] >= top_fs * 0.92], key=score)
    step = fs * LINE_K
    # 整塊**垂直置中在標籤條和底線之間**,不是從上往下貼。貼上緣會讓
    # 安全區下半空一大片,在 feed 裡看起來像沒東西。
    ys = [BLOCK_MID + (len(lines) - 1) / 2 * step - i * step
          for i in range(len(lines))]
    return {"lines": lines, "fs": round(fs, 1),
            "ys": [round(y, 4) for y in ys]}


def fit_sizes(plt, D):
    """每支片開渲前算一次合身字級。放在這裡而不是 render() 裡面,是因為
    render 每幀都會被呼叫(15 秒 × 30fps = 450 次),每次量一遍太貴。"""
    fs = {}
    # 開場卡的字級由**手寫的兩行**決定,不是旁白那句。旁白是唸的,
    # 這兩行是看的 —— 長度差很多(「WILLPOWER」vs「FEELING UNSURE
    # OF YOURSELF」),所以一定要量。
    fs["claim"] = claim_layout(plt, D)
    fs["kicker"] = fit(plt, KICKER, 46, max_frac=0.55)
    if D["es_o"] is None:
        head = (f"{D['k']} {D['k_word']}" if D.get("k") else "tested again")
        fs["head"] = min(fit(plt, ln, 88) for ln in wrap(head, 16)[:2])
        fs["n"] = fit(plt, f"{D['n_r']:,} people", 58)
    else:
        fs["sub"] = min(fit(plt, s, 46) for s in (
            f"the original — {D['n_o']:,} people",
            f"the replication — {D['n_r']:,} people"))
    if D["card"]:
        fs["card"] = min(fit(plt, ln, 58) for ln in wrap(D["card"], 20)[:2])
    fs["big"] = fit(plt, f"{D['es_r']:+.2f}".replace("+", ""), 300)
    # 🔴 對比那兩個大數字**原本寫死 240 / 270**,從來沒量過。
    #    「0.82」四個字塞得下,「-0.25」多一個負號就伸到 0.871、
    #    「-0.23」@270pt 伸到 0.917 —— 直接壓在按讚欄底下。
    #    而 19 集裡有一半的效果量是負的。這是「字級要用量的不是挑的」
    #    這條規則自己漏掉的兩個位置。
    fs["es_o"] = fit(plt, f"{D['es_o']:+.2f}".replace("+", ""), 240)         if D["es_o"] is not None else 240
    fs["es_r2"] = fit(plt, f"{D['es_r']:+.2f}".replace("+", ""), 270)
    # ⚠️ **每一段會上畫面的字都要納入**,漏一個就是漏一個越界點。
    #    第一版漏了來源那行:名案的是「FORRT Replication Database (FReD)」
    #    塞得下,FReD 那批多了「, OSF 2tbvd」就伸到 0.948 —— 同一個位置、
    #    同一個字級,只因為文案長度不同。這正是「量」而不是「挑」的理由。
    fs["src"] = fit(plt, D["source"], 34, weight="normal")
    fs["end"] = min(fit(plt, s, 76) for s in
                    ("Full episode", "on the channel",
                     "Every number", "from the record"))
    fs["meas"] = fit(plt, "the measured effect", 50, weight="normal")
    return fs


def render(plt, name, t, dur, D):
    fs = D.get("_fs") or {}
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    col = D["color"]

    if name == "q":
        # 🔴 **整句在第 0 幀就全部出現。**
        #
        # 上一版是逐行淡入,只有第一行在 t=0 不淡入 —— 我當時修的是
        # 「第一幀全黑」,但沒去看修完長什麼樣。實際抽出來的第一幀是
        # 一整片深色上一個孤零零的「Does」(ep004)、「Willpower」
        # (ego_depletion)。Shorts 的第一幀就是它在 feed 裡的縮圖,
        # 那一幀我拿去放了一個**連接詞**。
        #
        # 逐行揭露在長片成立(觀眾已經決定要看了),在 Shorts 是反的:
        # 觀眾在讀完之前就滑走了。所以這裡沒有揭露動畫,只有一條在
        # 主張下方掃出來的底線 —— 它不新增任何宣稱,純粹讓畫面不是死的。
        #
        # 而且這兩行跟**縮圖上那兩行是同一句**(來源 plain.py):feed 看到
        # 的和點進去看到的必須是同一支片。
        kick = KICKER if D.get("has_original") else KICKER_FALLBACK
        # 標籤條:滿版實色。這是整幀唯一的亮面,在一排彩色 Shorts 裡
        # 它是「這不是一支沒載入成功的影片」的訊號。
        # 左右邊界就是安全區本身(0.14 ~ 0.86)—— 第一版寫 0.10 起,
        # 當場被新加的色塊檢查擋下來:那 4% 正好落在按讚欄底下。
        ax.add_patch(plt.Rectangle((1 - SAFE_X, 0.775), 2 * SAFE_X - 1, 0.085,
                                   color=ACCENT, zorder=2))
        ax.text(0.5, 0.8175, kick, ha="center", va="center",
                fontsize=fs.get("kicker", 46), color="#0E1116",
                weight="bold", zorder=3)
        # 斷行與字級由 claim_layout 依**直式**版面算出來,不是沿用縮圖那兩行
        cl = fs["claim"]
        for _y, _ln in zip(cl["ys"], cl["lines"]):
            ax.text(0.5, _y, _ln, ha="center", va="center",
                    fontsize=cl["fs"], color=FG, weight="bold")
        # 底線掃出:0 → 滿寬,吃掉這一段前半。不帶資訊,所以晚出現無害。
        # 位置跟著主張區塊走,不能寫死 —— 行數 2~4 都可能。
        uy = cl["ys"][-1] - cl["fs"] * LINE_K * 0.85
        w = ease(min(1.0, max(0.0, (t - 0.45)) / 1.1))
        if w > 0:
            ax.plot([0.5 - 0.36 * w, 0.5 + 0.36 * w], [uy, uy],
                    color=ACCENT, lw=10, solid_capstyle="butt", zorder=2)
    elif name == "nums" and D["es_o"] is None:
        # 名案:沒有原始值可比,所以主體是「規模 → 量到的數字」而不是對比。
        if t > 0.3:
            q = ease(min(1.0, (t - 0.3) / 0.9))
            head = (f"{D['k']} {D['k_word']}" if D.get("k")
                    else "tested again")
            for i, ln in enumerate(wrap(head, 16)[:2]):
                ax.text(0.5, 0.83 - i * 0.062, ln, ha="center", va="center",
                        fontsize=fs.get("head", 88), color=FG, alpha=q,
                        weight="bold")
            ax.text(0.5, 0.70, f"{D['n_r']:,} people", ha="center",
                    va="center", fontsize=fs.get("n", 58), color=DIM, alpha=q)
        if t > 2.0:
            q = ease(min(1.0, (t - 2.0) / 0.9))
            ax.text(0.5, 0.505, f"{D['es_r']:+.2f}".replace("+", ""),
                    ha="center", va="center", fontsize=fs.get("big", 300),
                    color=col, alpha=q, weight="bold")
            ax.text(0.5, 0.385, "the measured effect", ha="center",
                    fontsize=fs.get("meas", 50), color=col, alpha=q)
        if t > 4.0 and D["card"]:
            q = ease(min(1.0, (t - 4.0) / 0.9))
            for i, ln in enumerate(wrap(D["card"], 20)[:2]):
                ax.text(0.5, 0.33 - i * 0.05, ln, ha="center",
                        fontsize=fs.get("card", 58), color=FG, alpha=q,
                        weight="bold")
    elif name == "nums":
        # 直式:上下對比而不是左右,手機上讀起來才順
        if t > 0.3:
            q = ease(min(1.0, (t - 0.3) / 0.9))
            ax.text(0.5, 0.80, f"{D['es_o']:+.2f}".replace("+", ""),
                    ha="center", va="center", fontsize=fs.get("es_o", 240),
                    color=DIM, alpha=q, weight="bold")
            ax.text(0.5, 0.705, f"the original — {D['n_o']:,} people",
                    ha="center", fontsize=fs.get("sub", 46), color=DIM, alpha=q)
        if t > 1.8:
            q = ease(min(1.0, (t - 1.8) / 0.9))
            ax.text(0.5, 0.60, "↓", ha="center", va="center", fontsize=100,
                    color=DIM, alpha=q)
        if t > 2.6:
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
                        weight="bold")
    else:
        # 🔴 片尾卡是觀眾停留的**最後一個畫面**,滿版大字。它跟旁白一樣
        #    只能在完整版真的已經發布時才提它 —— 理由見 end_line()。
        a, b = (("Full episode", "on the channel") if D.get("has_full")
                else ("Every number", "from the record"))
        ax.text(0.5, 0.66, a, ha="center",
                fontsize=fs.get("end", 76), color=FG, weight="bold")
        ax.text(0.5, 0.575, b, ha="center",
                fontsize=fs.get("end", 76), color=FG, weight="bold")
        ax.text(0.5, 0.45, D["source"], ha="center",
                fontsize=fs.get("src", 34), color=DIM)

    # 🔴 版面下緣 22% 與右緣 12% 是 Shorts 的 UI 覆蓋區(標題列、頻道名、
    #    按讚/留言/分享),頂端也有「Shorts」標籤與搜尋圖示。所有內容一律
    #    待在 SAFE_LO ~ SAFE_HI 之間。
    ax.text(0.5, 0.900, "THEY RAN IT AGAIN", ha="center", fontsize=36,
            color="#3C4450", weight="bold")

    # 🔴 **把安全區真的接上**。`SAFE_LO` / `SAFE_HI` 原本只是宣告在模組
    #    頂端,`fit()` 只用了 `SAFE_X`,垂直那兩個**從頭到尾沒有任何地方
    #    讀過** —— 寫了閘門沒接上等於沒有閘門,而且我當場就違規了一個
    #    (頻道標記在 0.945 > 0.93)。這跟 `EXPECT_CHANNEL` 是同一個病。
    #    改成掃過實際畫上去的每一個 text:越界就中止,不是印警告。
    #    這樣以後新增任何文字都會被自動檢查,不用記得去查。
    # ⚠️ 檢查的是**字的實際上下緣**,不是錨點。舊版只看 `get_position()`,
    #    於是頻道標記錨在 0.915(< SAFE_HI 0.93)一路過關,而它 36pt 的
    #    字身往上長到距頂 0.066 —— 獨立的 `lint_short` 量畫素才抓到。
    #    錨點過關而畫面越界,是「閘門只接上一半」的又一次:色塊那半
    #    今天才補,文字這半也一樣要看範圍而不是看點。
    #    半字高由字級推算:dpi=100 時 1pt = 100/72 px,除以 H=1920。
    # 🔴 量**實際的像素框**,不是從字級估。估法只看得到垂直方向,而且
    #    我今天為了它多寫了一段換算 —— 結果水平方向整個沒人管:
    #    對比那兩個大數字寫死 240/270 沒經過 fit(),`-0.23` 伸到 x=0.917,
    #    獨立的 lint_short 量畫素才抓到 4 支越界(其中 ep003 已經發出去了)。
    #    文字的垂直用估的、水平完全不查、色塊兩軸都查 —— 三個位置三種
    #    標準,那不是閘門是拼貼。
    #    畫完之後量一次,兩軸一起,文字與色塊同一套判準。
    fig.canvas.draw()
    _r = fig.canvas.get_renderer()
    for _o in list(ax.texts) + list(ax.patches):
        try:
            _bb = _o.get_window_extent(renderer=_r)
        except TypeError:
            _bb = _o.get_window_extent()
        _what = (_o.get_text()[:30] if hasattr(_o, "get_text") else str(_o)[:30])
        for _v, _lo, _hi, _ax in ((_bb.x0 / W, 1 - SAFE_X, SAFE_X, "左"),
                                  (_bb.x1 / W, 1 - SAFE_X, SAFE_X, "右"),
                                  (_bb.y0 / H, SAFE_LO, SAFE_HI, "下"),
                                  (_bb.y1 / H, SAFE_LO, SAFE_HI, "上")):
            if not (_lo - 1e-9 <= _v <= _hi + 1e-9):
                raise SystemExit(
                    f"⛔ 版面越界:「{_what}」{_ax}緣 {_v:.3f} 超出 "
                    f"[{_lo:.2f}, {_hi:.2f}] —— 那個位置在真機上被 UI 蓋住。")
    # 上面量框時已經 draw 過,不要再畫一次 —— 每支片 450 幀,多一次
    # 全畫布重繪就是把渲染時間加倍。
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


def _has_full(key):
    """該集的完整版是不是已經發布。渲染時只知道「發了沒」,不知道之後會不會
    被下架 —— 後者由 publish_shorts.cta_gate 在發布當下把關。"""
    import json as _j
    p = ROOT / "uploaded.json"
    if not p.exists():
        return False
    led = _j.loads(p.read_text(encoding="utf-8"))
    return bool(led.get(key) or led.get(f"eps_famous/{key}"))


def _plain(key):
    """本集的手寫白話主張。**缺就中止**。

    退回原本的論文語言等於這次改版沒發生,而且那種退化是靜默的:
    片子渲得出來、發得出去,只是開場那一幀沒人看得懂 —— 那正是這條線
    現在 10 支片 2 次觀看的原因。寧可少一支。
    """
    import plain
    v = plain.get(key)
    if not v:
        raise SystemExit(
            f"⛔ {key} 沒有手寫的白話主張(facts/plain_claims.json)——"
            f"不渲,免得又出一支開場是論文語言的片。")
    return v


def collect(slug=None, row=None):
    """從既有的事實庫組出 Short 需要的欄位 —— 不重算任何數字。"""
    from make_episode import (build_facts, say_num, CARD_TEXT, TONE_META)
    if row is not None:
        import pandas as pd
        q = pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
        F = build_facts(q.iloc[row])
        meta = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
        title = next(o["title"] for o in meta
                     if o.get("row") == row)
        pc = _plain(f"ep{row:03d}")
        return {
            "key": f"ep{row:03d}",
            # 🔴 旁白唸的那句是**手寫**的白話版,不是從標題切出來的。
            #    切標題切出來的東西長這樣:「Does scarcity-induced focus
            #    really lead to cognitive fatigue on subsequent cognitive
            #    control task?」—— 那是論文語言,在 Shorts 開場等於沒講。
            "question": pc["spoken"],
            "claim_lines": pc["lines"],
            "has_original": True,
            "es_o": F["orig"]["es"], "es_r": F["repl"]["es"],
            "n_o": F["orig"]["n"], "n_r": F["repl"]["n"],
            "say_o": say_num(F["orig"]["es"]), "say_r": say_num(F["repl"]["es"]),
            "card": CARD_TEXT[F["tone"]],
            "has_full": _has_full(f"eps/ep{row:03d}"),
            "color": BUCKET_COLOR[TONE_META[F["tone"]]["bucket"]],
            "source": F["source"],
        }
    eps = json.loads((ROOT / "facts" / "famous_episodes.json")
                     .read_text(encoding="utf-8"))["episodes"]
    E = next(e for e in eps if e["slug"] == slug)
    t, o = E["test"], E.get("original")
    # 🔴 **定調只有一個來源。** 這裡本來自己看信賴區間分三檔
    #    (跨零→fail、不跨零→held、沒有→mixed),那是**第二份實作** ——
    #    `publish_meta.famous_tone` 才是縮圖、標題、說明都在用的那份。
    #    兩份的差異不是理論問題:bystander_effect 沒有登記信賴區間,
    #    這裡判 mixed(灰色、沒有判決句),縮圖判 held(綠色、IT HELD UP)。
    #    同一支片,封面說撐住了、片子裡是灰的。
    #    這條線上「同一個計算兩份實作」已經是第九次。
    from publish_meta import famous_tone
    from make_famous import say_num as fsay
    from make_episode import CARD_TEXT, TONE_META
    tone = famous_tone(E)
    bucket = TONE_META[tone]["bucket"]
    card = CARD_TEXT[tone]
    if tone == "shrunk_real":
        # 🔴 `CARD_TEXT["shrunk_real"]` 是「Smaller — but still there.」——
        #    那句話**同時**斷言「比較小」和「仍然存在」,而名案這條線
        #    沒有原始效果量可以比(es_o 永遠是 None)。舊版程式的註解
        #    早就寫過這件事,我把定調收斂成單一來源時又把它放了回來。
        #    改成只講這一份統合分析自己說得出來的:測得到,但很弱。
        card = "It predicts — but weakly."
    # 🔴 唸的和畫面上的必須同一個精度。es=0.274 時畫面印 0.27、旁白唸
    #    「zero point two seven four」——同一支片自己對不上。統一到 2 位。
    es = round(t["es"], 2)
    pc = _plain(slug)
    return {
        "key": slug,
        "question": pc["spoken"],
        "claim_lines": pc["lines"],
        "has_original": bool(o),
        "es_o": None, "es_r": es,
        "n_o": o["cited_by_approx"] if o else None, "n_r": t["n"],
        "say_o": None, "say_r": fsay(es),
        "k": t.get("k"), "k_word": t.get("k_word", "studies"),
        "card": card, "color": BUCKET_COLOR[bucket], "tone": tone,
        "has_full": _has_full(slug),
        "source": "FORRT Replication Database (FReD)",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--row", type=int)
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()
    if a.slug is None and a.row is None:
        print("要指定 --slug 或 --row"); return 1

    D = collect(a.slug, a.row)
    segs = build_script(D)
    out = ROOT / "shorts" / D["key"]
    out.mkdir(parents=True, exist_ok=True)
    for n, txt in segs:
        (out / f"narr_{n}.txt").write_text(txt, encoding="utf-8")
    words = sum(len(t.split()) for _, t in segs)
    print(f"[{D['key']}] {D['question'][:60]}")
    gap = (f"{D['es_o']:+.2f} → " if D["es_o"] is not None
           else f"{D['k']} {D['k_word']} → " if D.get("k") else "")
    print(f"  稿 {words} 字   {gap}{D['es_r']:+.2f}   {D['card']}")
    if a.script_only:
        for n, t in segs:
            print(f"  --- {n} ---\n  {t}")
        return 0

    # TTS(每集獨立暫存腳本 —— 並行時寫死路徑會互相覆蓋)
    tts = out / "_tts_short.py"
    tts.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        f"for n in {tuple(n for n, _ in segs)!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        "    s, sr = k.create(t, voice='af_heart', speed=1.0, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<8}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(REPO / "_ttslab311" / "Scripts" / "python.exe"),
                    str(tts)], check=True, cwd=str(REPO))

    durs = {}
    for n, _ in segs:
        with wave.open(str(out / f"seg_{n}.wav")) as w:
            durs[n] = w.getnframes() / w.getframerate()
    total = sum(durs.values()) + 0.5 * len(segs)
    if total > 58:
        print(f"  ⚠️ {total:.0f} 秒 —— Shorts 上限 60 秒,會被當一般影片")

    plt = _plt()
    plan = visual_plan(plt, D)        # 畫面計畫落檔,供發布端比對
    D["_fs"] = plan["fs"]             # 合身字級算一次,render 每幀取用
    # visual.json **等幀渲完才寫** —— 它要帶實際畫面的雜湊,而且渲到一半
    # 掛掉時不該留下一份「宣稱這支片長這樣」的檔案。
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    import imageio.v2 as iio
    idx = 0
    for n, _ in segs:
        dur = durs[n] + 0.5
        for i in range(int(dur * FPS)):
            iio.imwrite(frames / f"f{idx:06d}.png", render(plt, n, i / FPS, dur, D))
            idx += 1
        print(f"  畫面 {n:<8}{dur:>6.1f}s")
    plan["frames"] = frame_digest(plt, D, durs)
    (out / "visual.json").write_text(
        json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8")

    voice = out / "voice.wav"
    with wave.open(str(voice), "wb") as w:
        first = True
        for n, _ in segs:
            with wave.open(str(out / f"seg_{n}.wav")) as s:
                if first:
                    w.setparams(s.getparams()); first = False
                w.writeframes(s.readframes(s.getnframes()))
                w.writeframes(b"\x00" * int(0.5 * s.getframerate() *
                                            s.getsampwidth() * s.getnchannels()))
    mp4 = out / f"{D['key']}_short.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frames / "f%06d.png"),
         "-i", str(voice), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(mp4)],
        check=True, capture_output=True)
    for f in frames.glob("*.png"):
        f.unlink()
    frames.rmdir()
    print(f"完成 → {mp4}  ({int(idx / FPS)}s, {W}x{H})")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
