#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_reel.py — 35~45 秒的直式短片。**取代 14~26 秒那一版。**

## 為什麼重做
2026-08-31 從 Analytics 與 videos.list 量到的:

| 量到的 | 值 | 讀法 |
|---|---|---|
| Shorts feed 佔流量 | 131 / 141 | 系統**有**在推,管道是通的 |
| 平均看完百分比 | 64.6 ~ 79.3% | 留存不差 |
| 平均每次觀看 | 約 13 秒 | 20 秒的片,在按觀看時間排序的池子裡墊底 |
| 289 次觀看換到 | **0 留言、0 分享、1 個讚** | ← 真正的問題 |

Shorts 的分發靠前一批曝光回收到的訊號決定要不要放大。回收到接近零,
它就不放大 —— **所以再發 45 支只會再拿 289 次觀看,供給從來不是瓶頸。**

三個改動,每一個都有機制:
1. **35~45 秒**(2026 演算法用觀看時間取代滑走率,甜蜜點 30~45 秒)。
   65% 留存的 20 秒片交出 13 秒;55% 留存的 40 秒片交出 22 秒。
2. **結尾問一個外行答得出來的問題** —— 289 次觀看 0 則留言,是因為片子
   從頭到尾沒有邀請任何人回應。
3. **開場是觀眾本來就相信的那句話**,不是論文語言。你不可能對一個
   你從沒相信過的說法感到被騙。

## 人設紅線
講述者是「去把兩篇論文讀完的那個人」——**那是真的**。所以語氣可以有立場,
事實不可以有立場;**不准編造個人史**(「我以前也相信」是關於一個不存在的人
的假話)。文案在 `facts/rechecked_episodes.json` 的 `reel` 欄位,逐集手寫,
而且照樣過數字溯源:想講的數字不是結構化欄位就升格,不放寬閘門。

用法:
  python make_reel.py --slug hot_hand --script-only
  python make_reel.py --slug hot_hand
  python make_reel.py --all
"""
import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from make_rechecked import (CJK, NUM_RE, _collect, load,   # noqa: E402
                            twist_rows, val_str)
#: 安全區是**實測**出來的,而且只有一份 —— 從 make_short 匯入,不要再抄一份。
#: (這條線上「同一個常數兩份實作」已經第九次。)
from make_short import (UI_RIGHT, UI_BOTTOM, UI_TOP,       # noqa: E402
                        MARGIN, SAFE_X, SAFE_LO, SAFE_HI)

W, H, FPS = 1080, 1920, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"
ACCENT, HOT = "#FFC23D", "#F5A54E"

SEGS = ("belief", "weight", "turn", "verdict", "ask")

_FIT = {}


def fit(plt, text, base, max_frac, weight="bold"):
    """字級用量的不是挑的。**一定要快取** —— 沒快取的話每一格畫面都會
    重開一張 1080×1920 的 figure,實測會讓渲染看起來像當掉
    (九分鐘零產出、記憶體每秒漲 9 MB)。"""
    ck = (text, base, round(max_frac, 4), weight)
    if ck in _FIT:
        return _FIT[ck]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    t = ax.text(0.5, 0.5, text, ha="center", va="center",
                fontsize=base, weight=weight)
    fig.canvas.draw()
    frac = t.get_window_extent(renderer=fig.canvas.get_renderer()).width / W
    plt.close(fig)
    out = base if (frac <= max_frac or frac == 0) \
        else max(20, int(base * max_frac / frac))
    _FIT[ck] = out
    return out


_MW = {}


def measure_w(plt, text, fs, weight="bold"):
    """這段字在這個字級下**實際**佔畫面寬度的幾分之幾。

    🔴 原本我用 `fit(...)/base*max_frac` 去反推寬度 —— 那是錯的:`fit` 回傳
       的是**字級**,而且當字串本來就塞得下時它原封不動回傳 base,於是反推
       出來的「寬度」永遠等於 max_frac(上限),不是實際寬度。
       後果是欄寬算太窄,兩欄擠在一起 —— facial feedback 實測重疊 53x7 畫素。
       要寬度就去量寬度,不要拿另一個量的回傳值去換算。
    """
    ck = (text, fs, weight)
    if ck in _MW:
        return _MW[ck]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    t = ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=fs,
                weight=weight)
    fig.canvas.draw()
    w = t.get_window_extent(renderer=fig.canvas.get_renderer()).width / W
    plt.close(fig)
    _MW[ck] = w
    return w


def balanced(s, n):
    """平衡斷句 —— 每一行盡量一樣長,不要有孤字行也不要有超長行。

    🔴 舊版有一個會**把標題壓到看不見**的 bug。它先貪婪算出需要 k 行,
       再用平均字數當目標重排,而重排那一趟寫著 `len(out) < k - 1`:
       一旦已經產出 k-1 行,剩下的詞**全部倒進最後一行**。
       實測 marshmallow 的開場被斷成
       `['A', 'four-year-old', 'who waits for', 'the', 'marshmallow does better in life.']`
       —— 兩個孤字行,末行 32 字元(目標是 16)。而 `fit()` 是拿**最長那行**
       去反推字級,所以整句被壓到 30pt,比同一畫面寫死 40pt 的副標還小。

       **三道守門全部看不見**:安全區逐元素驗四個邊(每一行都在界內)、
       重疊守門驗兩兩相交(行與行不重疊)、第 0 幀守門只驗「每個字都出現」
       (每個字都在)。錯的是**它們合起來的樣子** —— 這是這條線第 N 次
       踩到同一個形狀。

    改法:不要猜目標寬度。先貪婪求出需要幾行 k,再從「最長的那個詞」開始
    把寬度一格一格放寬,取**第一個仍然只用 k 行**的寬度 —— 那就是能塞進
    k 行的最窄寬度,而最窄寬度等價於最平均的分行。
    """
    words = s.split()
    if not words:
        return [""]

    def greedy(width):
        out, line = [], ""
        for w in words:
            if line and len(line) + len(w) + 1 > width:
                out.append(line); line = w
            else:
                line = (line + " " + w).strip()
        if line:
            out.append(line)
        return out

    k = len(greedy(n))
    if k <= 1:
        return greedy(n)
    lo = max(len(w) for w in words)
    for width in range(lo, max(lo, len(s)) + 1):
        cand = greedy(width)
        if len(cand) <= k:
            return cand
    return greedy(n)


def build_script(E):
    r = E.get("reel")
    if not r:
        raise SystemExit(
            f"⛔ {E['slug']} 沒有 `reel` 文案。**不要用舊的 say_* 頂替** ——"
            f"那是給 2 分半長片寫的,塞進 40 秒的短片會變成唸稿。")
    missing = [k for k in SEGS if not r.get(k)]
    if missing:
        raise SystemExit(f"⛔ {E['slug']} 的 reel 缺 {missing}")
    return [(k, r[k]) for k in SEGS]


def audit(E, segs):
    ok = set()
    _collect(E, ok)
    for v in list(ok):
        ok.add(v.replace(",", ""))
    bad = [(n, num) for n, t in segs for num in NUM_RE.findall(t)
           if num not in ok and num.replace(",", "") not in ok]
    if bad:
        raise SystemExit(
            f"⛔ 短片文案裡有溯源不到的數字:{bad}\n"
            f"   白名單只收結構化欄位。想講就把它升格成欄位,不要放寬閘門。")
    lang = [(n, CJK.search(t).group()) for n, t in segs if CJK.search(t)]
    if lang:
        raise SystemExit(f"⛔ 文案裡有中文:{lang} —— 這是英文頻道,TTS 會唸出來。")
    print(f"  數字溯源 ✓（{len(ok)} 個結構化可用值）  輸出語言 ✓")


#: 🔴 副標的字級寫死,而主標是**量出來**的變數 —— 兩者無關,所以只要主標
#:    被一行長句壓下來,主從關係就反過來。實測 hot_hand 的 weight 卡主標
#:    47pt、副標 46pt,而副標還是 bold + 琥珀色、主標是 normal + 暗灰:
#:    看起來副標才是重點。守門只驗「主標有沒有比副標小」,47 > 46 所以不叫。
#:    副標一律跟著主標走,取上限與比例的較小者。
def sub_fs(title_fs, cap):
    return max(22, min(cap, int(title_fs * 0.72)))


def render_scene(name, t_now, dur, ctx):
    plt, E, rows = ctx["plt"], ctx["E"], ctx["rows"]
    r = E["reel"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ease = lambda x: 1 - (1 - max(0.0, min(1.0, x))) ** 3

    def block(text, mid, base, wrap_n, col=FG, weight="bold", alpha=1.0):
        """一整段字,**整段一起出現**,而且以**區塊中心**定位。

        🔴 原本是「從 top 往下排 + 寫死的行高」,兩個問題:
           · 行高寫死 0.052 而字級是量出來的變數 —— 兩者無關,所以區塊
             實際多高我算不出來,底下那行副標只能用猜的位置放,
             抽幀就看到標題與副標之間空一個洞。
           · 從 top 往下排 → 行數少的時候整塊黏在上緣,安全區下半空著。
        改成:行高跟著字級走,區塊以中心對齊,回傳實際的上下緣讓呼叫端
        把副標貼在它下面。
        """
        lines = balanced(text, wrap_n)
        # 🔴 **最長的那一行不一定是最寬的那一行。** 用 `max(lines, key=len)`
        #    挑一行去量,等於假設字元數就是寬度 —— 而大寫、W/M 這類寬字母、
        #    數字都會讓一行比更長的另一行還寬。實測:mozart 的開場左緣量到
        #    0.019(界線 0.02)、marshmallow 的判決卡右緣 0.864(界線 0.86),
        #    兩支都是被沒被量到的那一行撐出去的。
        #    **每一行都量,取最小的那個字級。**
        fs = min(fit(plt, ln, base, SAFE_X - (1 - SAFE_X), weight)
                 for ln in lines if ln.strip())
        lh = fs * 1.30 / 1382.0          # 點 → 圖形高度比例(dpi 100, 19.2in)
        top = mid + (len(lines) - 1) * lh / 2
        for i, ln in enumerate(lines):
            ax.text(0.5 - (UI_RIGHT / 2), top - i * lh, ln, ha="center",
                    va="center", fontsize=fs, color=col, weight=weight,
                    alpha=alpha)
        return top + lh / 2, top - (len(lines) - 1) * lh - lh / 2, fs

    if name == "belief":
        # 🔴 **第 0 幀就要是完整的一句話。** alpha 從 1 開始,不淡入。
        _, bot, tfs = block(r["belief"], 0.62, 104, 16)
        ax.text(0.5 - (UI_RIGHT / 2), bot - 0.055, "you have heard this one",
                ha="center", va="center", fontsize=sub_fs(tfs, 40),
                color=DIM, weight="normal")

    elif name == "weight":
        _, bot, tfs = block(r["weight"], 0.62, 72, 22, DIM, "normal")
        ax.text(0.5 - (UI_RIGHT / 2), bot - 0.06, "so somebody checked",
                ha="center", va="center", fontsize=sub_fs(tfs, 46),
                color=ACCENT, weight="bold",
                alpha=ease((t_now - 1.0) / 0.8))

    elif name == "turn":
        # 數字逐個出現 —— 這一段最長(約 14 秒),畫面不能不動。
        ax.text(0.5 - (UI_RIGHT / 2), SAFE_HI - 0.03, "what came back",
                ha="center", va="center", fontsize=42, color=DIM,
                weight="normal")
        n = max(1, len(rows))
        # 🔴 **爆點不要比旁白早二十秒出現。** 列是照時間均分揭露的,跟旁白
        #    唸到哪裡無關 —— 實測 hot_hand 的 +13 在畫面上掛了 5 秒之後,
        #    旁白才唸到「minus 8」,而 +13 那句要到下一段(verdict)才唸。
        #    這支自己的註解寫著「旁白與畫面講不同的事,是這條線最貴的那種錯」。
        #    沒有逐列的時間戳可以對齊,但至少可以做一件事:
        #    **把標了 hot 的那一列押到這一段的最後**。
        # 🔴 上面那個修法**錯了,而且比原本更糟**。把 hot 排到最後,等於
        #    讓它後面那一列往前遞補 —— 於是兩列各自出現在對方的旁白時段上。
        #    獨立驗證逐格量到:已上線的 Dunning-Kruger 在 t≈26~35 秒畫面上
        #    只有 `r = 0.28`,而旁白正在唸「minus 0.05」 ——
        #    **我宣稱修好的那個洞原封不動,我只是換了一列掉進去。**
        #    stanford_prison 的爆點(獄卒被指示扮兇)從頭到尾沒和它的旁白
        #    同框過;sugar_hyperactivity 同形狀。六支中招。
        #
        #    根因不是排序,是**揭露時間從頭到尾都是猜的**:列照時間均分,
        #    跟旁白唸到哪裡無關。三次修法(押後 hot、押後位置、再排序)
        #    都在猜,而猜的方向每次都不一樣。
        #
        #    改成從旁白文字本身對出來:每一列帶一個 `cue`,是 turn 旁白裡的
        #    **逐字子字串**;揭露時間 = 該 cue 的字元位置比例 × 這一段長度。
        #    對不到就中止 —— 不猜、不退回均分。
        turn_txt = (r.get("turn") or "").strip()
        cues, pos = [], []
        for i, x in enumerate(rows):
            c = (x.get("cue") or "").strip()
            if not c:
                raise SystemExit(
                    f"⛔ {E['slug']} twist_rows[{i}] 沒有 cue —— "
                    f"揭露時間就只能用猜的,而猜過三次錯三次。\n"
                    f"   cue 要是 turn 旁白裡逐字抄出來的一小段,"
                    f"標出「這一列是唸到這裡的時候出現的」。\n"
                    f"   旁白:{turn_txt[:120]}")
            if c == "@start":
                # 背景列:整段從頭就在(它是別的列拿來比的基準),
                # 不宣稱跟旁白同步 —— 明講「從頭就在」比假裝對得上誠實。
                cues.append(c); pos.append(-1); continue
            k = turn_txt.find(c)
            if k < 0:
                raise SystemExit(
                    f"⛔ {E['slug']} twist_rows[{i}] 的 cue 在 turn 旁白裡"
                    f"逐字找不到:「{c}」\n   旁白:{turn_txt[:160]}")
            cues.append(c); pos.append(k)
        bad = [i for i in range(len(pos) - 1) if pos[i] >= pos[i + 1] >= 0]
        if bad:
            raise SystemExit(
                f"⛔ {E['slug']} 表格的列順序跟旁白唸到的順序對不上"
                f"(第 {bad} 列之後就反了)。\n"
                f"   位置:{pos}  cues:{cues}\n"
                f"   正解是把事實庫裡的列**照旁白的順序重排**,"
                f"不是在畫面上偷偷換位置。")
        gap = min(0.125, 0.50 / n)
        top = 0.60 + (n - 1) * gap / 2
        lefts = [str(x.get("label") or x.get("year") or "") for x in rows]
        whats = [x["what"] for x in rows]
        # 🔴 欄寬要從**數值欄實際佔多寬**倒推,不要各挑一個看起來夠用的
        #    數字:守門實測抓到「everything measured at t」×「β = 0.05」
        #    重疊 22×10 畫素 —— 兩欄各自都「差不多塞得下」,合起來就撞。
        vals = [val_str(x["es_kind"], x["es"], x.get("es_is_max", False))
                for x in rows
                if x.get("es") is not None and x.get("es_kind")] or ["x"]
        vw = max(measure_w(plt, v, 46) for v in vals)
        left_max = max(0.24, SAFE_X - vw - 0.04)   # 0.04 是欄間淨空
        lf = min(fit(plt, w, 40, left_max - 0.06, "bold") for w in lefts if w)
        nf = min(fit(plt, w, 34, left_max - 0.06, "normal") for w in whats if w)
        # 早 0.35 秒讓字先站定,再被唸到 —— 晚到會看起來像沒跟上。
        ats, prev = [], 0.0
        for k in pos:
            a = (0.3 if k < 0 else
                 max(0.3, k / max(1, len(turn_txt)) * dur - 0.35))
            a = max(a, prev)          # 單調:列不會倒著出現
            ats.append(a); prev = a

        # 🔴 第一列的 cue 落在旁白中段時,**畫面在那之前是空的**。實測
        #    hot_hand 的 turn 段前 11.67 秒只有右上角一行標題 —— 44.6 秒的
        #    Short 有 26% 是空畫面,而且空在中段。這個格式整個改版的理由
        #    就是觀看時間,而空畫面是最直接的滑走理由。
        #    hungry_judges 45%、growth_mindset 32% 同型。
        #    補的東西不是新內容,是**旁白自己正在唸的那幾句** —— 它不會
        #    多講任何一件事,只是讓看的人跟得上聽的。
        # 🔴 導言只填了「第一列之前」那一段,而死時間有三種:第一列之前、
        #    **列與列之間**、以及**最後一列之後**。實測 14 支裡 8 支中招:
        #    facial_feedback 列間 14.1 秒、sugar_hyperactivity 16.3 秒、
        #    grit 尾段 12.5 秒、stanford_prison 第一列之前 18.4 秒。
        #    我上一版只修了自己手上那個病例(hot_hand 的第一種)。
        #
        #    改成整段都有:**把旁白正在唸的那一句顯示在表格下方**。
        #    它逐字取自旁白,不多講任何一件事;它把每一個空檔都填掉;
        #    而且 Shorts 有大量觀看是靜音的,字幕本身就是留存工具。
        import re as _re
        # 🔴 第一版寫 `[^.!?]+[.!?]+` —— 它把**小數點當成句號**。
        #    growth_mindset 的「p equals 0.634.」被切出一個叫「634.」的
        #    句子,停留 0.44 秒。是我自己剛加的「句子不准短於 0.9 秒」
        #    那道斷言把它擋下來的 —— 斷言擋的是我自己的 bug。
        #    句號要**後面接空白再接大寫**才算句尾;小數點兩側都是數字。
        _cuts = [0] + [m.end() for m in
                       _re.finditer(r'(?<=[.!?])\s+(?=["“(]?[A-Z])',
                                    turn_txt)]
        _sent = [(c, turn_txt[c:(_cuts[i + 1] if i + 1 < len(_cuts)
                                 else len(turn_txt))].strip())
                 for i, c in enumerate(_cuts)]
        _sent = [(k, t) for k, t in _sent if t]
        if not _sent:
            _sent = [(0, turn_txt)]
        _bounds = [(k / max(1, len(turn_txt))) * dur for k, _ in _sent]
        _cur = None
        for _j, (_st, _tx) in enumerate(_sent):
            _a = _bounds[_j]
            _b = _bounds[_j + 1] if _j + 1 < len(_bounds) else dur
            if _a <= t_now < _b:
                _cur = _tx
                break
        if _cur:
            # 🔴 上一版是**先放再祈禱**:用一個寫死的 0.16 猜區塊高度去算
            #    中心點,而區塊高度其實是跟著行數與字級長出來的。
            #    實測 hot_hand 的字幕上緣算到 0.642,而可用上緣是 0.619 ——
            #    是同一次加的重疊斷言把它擋下來的(擋的又是我自己的 bug)。
            #    改成**先量再放**:量出這段字要多高,再把它的上緣貼齊
            #    可用空間的上緣往下長。放不下就縮字級,縮到地板還放不下
            #    才中止 —— 不截字。
            _shown = [i for i, a in enumerate(ats) if t_now >= a]
            _low = (top - max(_shown) * gap - gap * 0.85) if _shown \
                else SAFE_HI - 0.06
            _room = _low - SAFE_LO
            _placed = False
            for _base, _wrap in ((46, 30), (40, 34), (34, 40), (28, 46)):
                _ln = balanced(_cur, _wrap)
                _fs = min(fit(plt, x, _base, SAFE_X - (1 - SAFE_X), "normal")
                          for x in _ln if x.strip())
                _lh = _fs * 1.30 / 1382.0
                _h = (len(_ln) - 1) * _lh + _lh      # 含上下半行的視覺高度
                if _h <= _room:
                    _mid = _low - _h / 2
                    _t_edge, _b_edge = block(_cur, _mid, _base, _wrap,
                                             DIM, "normal")[:2]
                    if _t_edge > _low + 0.006:
                        raise SystemExit(
                            f"⛔ {E['slug']} 字幕上緣 {_t_edge:.3f} 仍高於"
                            f"可用上緣 {_low:.3f} —— 量高度那段算錯了,"
                            f"不是文案的問題。句子:{_cur[:46]}")
                    if _b_edge < SAFE_LO - 0.006:
                        raise SystemExit(
                            f"⛔ {E['slug']} 字幕下緣 {_b_edge:.3f} 掉出"
                            f"安全區({SAFE_LO})。句子:{_cur[:46]}")
                    _placed = True
                    break
            if not _placed:
                raise SystemExit(
                    f"⛔ {E['slug']} 這一句字幕縮到 28pt 還放不進表格下方"
                    f"({_room:.3f} 的空間)。截字是不准的 —— 要縮的是"
                    f"事實庫裡的那一句,或讓那一列早一點出現。\n"
                    f"   句子:{_cur}")

        # 🔴 **靜止時間才是那個量。** 我原本的判準是「畫面上有沒有東西」,
        #    而 stanford_prison 通過了那個判準(有一列)卻靜止 17.7 秒。
        #    獨立驗證用的尺比我的好,所以把它寫成閘門。
        #    現在畫面每一句都會換,所以要驗的變成:**有沒有哪一句短到
        #    看不完**(閃一下就過去,比不動更糟)。
        _short = [(t[:40], round(b - a, 2))
                  for (t, a, b) in
                  ((_sent[j][1], _bounds[j],
                    _bounds[j + 1] if j + 1 < len(_bounds) else dur)
                   for j in range(len(_sent)))
                  if b - a < 0.9]
        if _short:
            raise SystemExit(
                f"⛔ {E['slug']} 有字幕句停留不到 0.9 秒:{_short}\n"
                f"   一閃而過的字比不動的畫面更糟 —— 把那一句併進前後句。")
        for i, x in enumerate(rows):
            at = ats[i]
            if t_now < at:
                continue
            b = ease((t_now - at) / 0.5)
            y = top - i * gap
            hot = bool(x.get("hot"))
            ax.text(0.06, y + 0.022, lefts[i], ha="left", va="center",
                    fontsize=lf, color=ACCENT if hot else DIM,
                    weight="bold", alpha=b)
            ax.text(0.06, y - 0.020, x["what"], ha="left", va="center",
                    fontsize=nf, color=FG if hot else DIM,
                    weight="normal", alpha=b)
            if x.get("es") is not None and x.get("es_kind"):
                ax.text(SAFE_X, y,
                        val_str(x["es_kind"], x["es"],
                                x.get("es_is_max", False)),
                        ha="right", va="center", fontsize=46,
                        color=ACCENT if hot else FG, weight="bold", alpha=b)

    elif name == "verdict":
        # 🔴 這一塊出過一個**看不見的**錯:色塊高度寫死 0.30、行距寫死
        #    0.064,而文字顏色 #0E1116 剛好等於背景色 BG。行數 >= 6 時
        #    整塊文字高 0.384 > 0.30,首尾兩行落到色塊外 —— **黑底黑字,
        #    直接消失**。實測 grit 的判決卡少了主詞「Grit matches」和那句
        #    防過度宣稱的但書「It still predicts things.」,而畫面上留下的
        #    殘句沒有主詞。判決卡停 7.8 秒,是全片最後被記住的一張。
        #
        #    三道守門全綠:安全區逐元素驗四個邊(溢出的行都在 0.24~0.91
        #    之內)、重疊守門驗兩兩相交(行與行不重疊)。**沒有任何一道在驗
        #    「文字有沒有在它自己的底色塊裡」。** 每個元素單獨都合法,
        #    錯的是它們合起來的樣子 —— 又一次。
        #
        #    改法:色塊跟著行數長,而且**斷言每一行都在色塊裡**,放不下就中止。
        lines = balanced(r["verdict"], 24)
        # 最長的一行不一定是最寬的 —— 每一行都量(第三個現場了)
        fs = min(fit(plt, ln, 62, SAFE_X - 0.12) for ln in lines if ln.strip())
        lh = fs * 1.30 / 1382.0
        pad = 0.035
        half = (len(lines) - 1) * lh / 2 + pad
        mid = 0.49
        y0, y1 = mid - half, mid + half
        if y0 < SAFE_LO or y1 > SAFE_HI:
            raise SystemExit(
                f"⛔ {E['slug']} 的判決卡 {len(lines)} 行放不進安全區"
                f"(色塊 {y0:.3f}~{y1:.3f},界線 {SAFE_LO}~{SAFE_HI})。\n"
                f"   要縮的是事實庫裡的 verdict,不是字級 —— 溢出的行會變成"
                f"黑底黑字,看不見。原文:{r['verdict'][:70]}")
        ax.add_patch(plt.Rectangle((0.04, y0), SAFE_X - 0.04, y1 - y0,
                                   color=HOT, zorder=1))
        for i, ln in enumerate(lines):
            y = mid + (len(lines) - 1) * lh / 2 - i * lh
            if not (y0 + lh * 0.4 <= y <= y1 - lh * 0.4):
                raise SystemExit(
                    f"⛔ {E['slug']} 判決卡第 {i + 1} 行掉出色塊"
                    f"(y={y:.3f},色塊 {y0:.3f}~{y1:.3f})—— 那一行會是"
                    f"黑底黑字。不出片。")
            ax.text((0.04 + SAFE_X) / 2, y, ln, ha="center", va="center",
                    fontsize=fs, color="#0E1116", weight="bold", zorder=2)

    else:                                            # ask
        _, bot, tfs = block(r["ask"], 0.64, 92, 16)
        ax.text(0.5 - (UI_RIGHT / 2), bot - 0.06, "tell me below",
                ha="center", va="center", fontsize=sub_fs(tfs, 50),
                color=ACCENT, weight="bold")
        ax.text(0.5 - (UI_RIGHT / 2), SAFE_LO + 0.02, "THEY RAN IT AGAIN",
                ha="center", va="center", fontsize=30, color=DIM,
                weight="bold")

    # ── 守門 ──
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    boxes = []
    for ob in list(ax.texts):
        bb = ob.get_window_extent(renderer=rend)
        for v, lo, hi, side in ((bb.x0 / W, MARGIN, SAFE_X, "左"),
                                (bb.x1 / W, MARGIN, SAFE_X, "右"),
                                (bb.y0 / H, SAFE_LO, SAFE_HI, "下"),
                                (bb.y1 / H, SAFE_LO, SAFE_HI, "上")):
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                raise SystemExit(
                    f"⛔ {name} 越出安全區:「{ob.get_text()[:24]}」"
                    f"{side}緣 {v:.3f}(允許 {lo:.2f}~{hi:.2f})"
                    f" —— 那個位置在真機上被 YouTube 的 UI 蓋住。")
        if (ob.get_alpha() or 1) >= 0.35:
            boxes.append((ob.get_text()[:24], bb))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ta, A), (tb, B) = boxes[i], boxes[j]
            ox = min(A.x1, B.x1) - max(A.x0, B.x0)
            oy = min(A.y1, B.y1) - max(A.y0, B.y0)
            if ox > 2 and oy > 2:
                raise SystemExit(f"⛔ {name} 文字重疊:「{ta}」×「{tb}」"
                                 f"{ox:.0f}×{oy:.0f} 畫素")
    # 第 0 幀不能是空的,也不能只有半句
    if t_now < 0.05 and name == "belief":
        shown = " ".join(o.get_text() for o in ax.texts
                         if (o.get_alpha() or 1) >= 0.9)
        for w in r["belief"].rstrip(".").split():
            if w.strip(".,") and w.strip(".,") not in shown:
                raise SystemExit(
                    f"⛔ 第 0 幀少了「{w}」—— Shorts 最值錢的就是那一幀,"
                    f"不能只出現半句話。")
    import numpy as np
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return plt


def one(slug, script_only=False):
    E = load(slug)
    segs = build_script(E)
    rows = twist_rows(E)
    words = sum(len(t.split()) for _, t in segs)
    print(f"[{slug}] {E['story_type_short']}")
    audit(E, segs)
    print(f"  文案 {words} 字 ≈ {words / 2.6:.0f} 秒")
    if script_only:
        for n, t in segs:
            print(f"  --- {n} ---\n  {t}")
        return 0
    out = ROOT / "reels" / slug
    out.mkdir(parents=True, exist_ok=True)
    for n, t in segs:
        (out / f"narr_{n}.txt").write_text(t, encoding="utf-8")
    (out / "facts.json").write_text(json.dumps(E, ensure_ascii=False,
                                               indent=1), encoding="utf-8")
    from render_pipeline import tts, render_and_mux
    tts(out, segs)
    mp4, dur = render_and_mux(out, segs, render_scene, f"{slug}_reel.mp4",
                              W, H, FPS,
                              ctx={"plt": _plt(), "E": E, "rows": rows})
    # 🔴 片長是這次改版的**處置本身**。渲完要量實際值,不能拿字數估算
    #    當完成 —— 「改了設定 ≠ 改了東西」這條在這條線上剛剛才踩過。
    if not (35 <= dur <= 50):
        # 🔴 這裡原本印 ⚠️。批次跑的時候我 grep 的是「完成|⛔」,
        #    所以 moral_licensing 55s、grit 54s 的警告**印出來了而我沒看到**。
        #    看不到的警告等於沒有警告 —— 改成 ⛔ 並回非零。
        print(f"  ⛔ {slug} 片長 {dur:.0f} 秒,不在 35~50 秒的設計帶(要改稿重渲)")
        print(f"完成 → {mp4}  ({dur:.0f}s)")
        return 1
    # 🔴 縮圖 = **開場卡**。這個格式刻意做成「第 0 幀就是完整的一句話」,
    #    而那句話正是要讓人停下來的東西 —— 它就該是頻道頁與搜尋結果裡
    #    看到的那一張。不抽中段:中段是表格,對還沒點進來的人沒有意義。
    #    抽 0.5 秒(避開第 0 幀可能的編碼暖機)。
    import subprocess as _sp
    th = out / "thumb.jpg"
    r = _sp.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(mp4),
                 "-frames:v", "1", "-q:v", "2", str(th)],
                capture_output=True, text=True)
    if r.returncode != 0 or not th.exists():
        raise SystemExit(f"⛔ {slug} 縮圖抽不出來:{r.stderr[:120]}")
    print(f"  縮圖 → {th.name}")
    print(f"完成 → {mp4}  ({dur:.0f}s)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()
    if a.all:
        src = json.loads((ROOT / "facts" / "rechecked_episodes.json")
                         .read_text(encoding="utf-8"))
        for e in src["episodes"]:
            one(e["slug"], a.script_only)
        return 0
    if not a.slug:
        ap.error("要 --slug 或 --all")
    return one(a.slug, a.script_only)


if __name__ == "__main__":
    sys.exit(main())
