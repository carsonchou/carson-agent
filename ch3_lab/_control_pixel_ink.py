#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""影像層 §2「黑底黑字」的對照 —— 量的是**真的落在畫面上的像素**。

🔴 **歷史事故:整批片渲染成功、時長正確、mp4 產得出來,而畫面上一個字都沒有。**
   (滿版軸沒鎖 set_xlim(0,1),ax.plot 自動縮放把文字裁到畫面外。)
   **任何自動檢查都不報錯** —— 這是最貴的那一種失敗:管線回報成功。

⚠️ **不可以量顏色常數。** FG=#E8EAED / BG=#0E1116 從頭到尾都是對的,
   出事的是像素。所以這支讀的是像素,不是讀程式碼。

🔴 **讀的是 mp4,不是 frames/。** 原本這支讀 reels/<slug>/frames/*.png,
   而 render_pipeline.py:305-307 mux 完就把整個 frames/ 刪掉 ⇒ 那個前提是死的。
   改讀 mp4 反而更對:**mp4 才是會被看到的那個東西**,frames/ 只是中間產物。
   代價是真幀走過 libx264/yuv420p,而陽性對照是就地重畫的原始幀 ⇒
   兩邊不同管線就不可比。所以:
   ① 陽性對照**也過同一組編碼參數**(-c:v libx264 -pix_fmt yuv420p -crf 20)再量;
   ② 另加一格對照,證明「從 mp4 量」和「就地重畫量」對同一幀給出同一個數
      —— 不然「壓縮把畫面量胖了」和「畫面真的有字」分不開。

⚠️ **要避開淡入中的幀。** ease() 讓元素在揭露後 0.5~0.8 秒是半透明的,
   在那些時刻量會得到一個**正當**的低值。取樣點取每一段的後段。

⚠️ **地板不是我挑一個好看的數字。** 它要落在「真幀的分佈」與「兩個陽性對照」
   之間的空隙裡,而兩邊的實測值都印出來給人看。空隙不夠大就是這支不算數。

⚠️ **E 取自 reels/<slug>/facts.json,不是 rechecked_episodes.json。**
   make_reel 在渲染前先跑 caption(E, k) 把副標寫進 E(make_reel.py:872),
   落在 reels/ 的那份是**那次渲染真正用的**那一份。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import wave

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                       # noqa: E402
from scipy import ndimage                                # noqa: E402
import matplotlib                                        # noqa: E402
matplotlib.use("Agg")
import imageio.v2 as iio                                 # noqa: E402
import make_reel as M                                    # noqa: E402
from render_pipeline import SEG_GAP                      # noqa: E402
from make_rechecked import twist_rows                    # noqa: E402

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative",
     "label": "六支**已 mux 的 mp4**,每段取後段兩個時刻(避開 ease 淡入):"
              "非背景像素比例都在地板之上 ⇒ 畫面上真的有字"},
    {"kind": "negative",
     "label": "同一批真幀:有字的像素和背景的色距都 ≥ 60 ⇒ 不是黑底黑字"},
    {"kind": "negative",
     "label": "**儀器橋接**:同一個 (slug, 段, 幀號),"
              "「從 mp4 解出來」與「就地用同一份 facts.json 重畫」量到的墨水比例"
              "要對得上(相對差 < 30%)⇒ 拿 mp4 當量具不會把空畫面量成有字"},
    {"kind": "positive",
     "label": "把**四個油墨顏色**(FG/DIM/ACCENT/HOT)全部設成 BG 重畫同一幀,"
              "**過同一組編碼參數**再量 ⇒ 非背景像素比例必須掉到地板之下。"
              "⚠️ 只塌 FG **不算** —— 實測只塌 FG 還剩 3.23%(DIM 的副標、"
              "ACCENT 的數值、HOT 的判決色塊都還在),那樣的陽性對照是假的"},
    {"kind": "positive",
     "label": "文字被平移出畫面(座標變換壞掉那一類)⇒ 非背景像素比例必須"
              "掉到地板之下;**而且**同一個變異在 layout_guard 沒被繞過時"
              "必須先炸(縱深:這一類壞法有兩道守門,不是只有像素這一道)"},
    {"kind": "negative",
     "label": "🔴 **判決卡要單獨量。** 那張卡是**深字壓在 HOT 色塊上**"
              "(make_reel.py:828 寫死 #0E1116)⇒ 整張畫面的「非背景像素比例」"
              "會把整塊橘色算成油墨(實測 14~27%),字消失了也照樣及格。"
              "所以另外量**色塊內部**有多少深色像素 ⇒ 六支都要在地板之上"},
    {"kind": "positive",
     "label": "把判決卡的字改成和色塊同色(HOT)⇒ 色塊還在、整體比例還是 20% 上下,"
              "而**卡內深色像素比例**必須掉到地板之下。"
              "這一格證的是:上面那個整體指標對這一種壞法是盲的"},
    {"kind": "positive",
     "label": "🔴 **會踩到這把尺自己弱點的對照**:verdict 段裡放一個 ACCENT 元素,"
              "同時把卡上的字塗成 HOT(=字全部消失)⇒ 仍然必須被抓到。"
              "舊規則(門檻 45 + 全域外接框)在這一格會**漏掉**它:ACCENT 距 HOT 只有 29,"
              "外接框從 417px 被撐到 968px,卡內深色從 0.00% 被灌成 55.91% ⇒ 真陽性變綠燈。"
              "這一格同時用舊規則跑一次,證明**承重的是哪兩行**"},
    {"kind": "negative",
     "label": "⑧ 的反向對照:verdict 段裡有 ACCENT 但**字還在** ⇒ **不該**被抓到,"
              "而且讀數要回到真卡的量級。少了這一格,「收緊門檻修好了」和"
              "「收緊門檻把真卡也切掉了」分不開"},
]

SIX = ["study_techniques", "how_to_remember_what_you_read", "focus_techniques",
       "if_then_plans", "learning_styles", "pomodoro"]
ROOT = pathlib.Path(r"D:\carson-agent\ch3_lab")
BG = np.array([0x0E, 0x11, 0x16], dtype=np.int16)
HOT = np.array([0xF5, 0xA5, 0x4E], dtype=np.int16)   # 判決卡的色塊,和 make_reel.HOT 同值
TOL = 12          # 和背景差這麼多以內,算背景(壓縮/抗鋸齒的雜訊)
CONT_FLOOR = 60   # 色距地板:#E8EAED vs #0E1116 的實際色距遠大於此
CARD_TOL = 20     # 判決卡色塊的認定門檻(切比雪夫)
#: 🔴 **色彩門檻要對調色盤裡的每一個其他顏色算一次距離,不能只對背景算。**
#:    這裡原本是 45,而 ACCENT(#FFC23D)對 HOT(#F5A54E)的切比雪夫距只有 **29**
#:    ⇒ verdict 段裡任何 ACCENT 元素都會被算成卡片、把外接框撐大、
#:    把背景像素灌進「卡內深色比例」⇒ **方向往假綠**(實測:字全部消失的那一幀
#:    從 0.00% 被灌成 55.91%,真陽性變綠燈)。
#:    這批片沒踩到,只因為 ACCENT 只出現在 ask 段、卡只出現在 verdict 段 ——
#:    那是**內容的巧合,不是儀器的正確**。
INKS = {"FG": "#E8EAED", "DIM": "#8A9099", "ACCENT": "#FFC23D", "BG": "#0E1116"}
ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20"]
ok = []


def say(good, msg):
    ok.append(good)
    print(f"  {'✓' if good else '🔴'} {msg}")


def ink(img):
    """回 (非背景像素比例, 有字像素相對背景的平均色距)。"""
    a = np.asarray(img, dtype=np.int16)[:, :, :3]
    dist = np.abs(a - BG).max(axis=2)
    mask = dist > TOL
    return mask.mean(), (float(dist[mask].mean()) if mask.any() else 0.0)


def card_ink(img):
    """判決卡**內部**的深色像素比例。

    整張畫面的指標對這張卡是盲的:卡是 HOT 色塊 + 深色字,色塊本身就佔
    14~27% 的「非背景像素」⇒ 字全部消失,整體指標一動也不動。
    這裡先用 HOT 找出色塊的外接框,再問框內有多少像素**離 BG 比離 HOT 近**。
    回 (卡內深色比例, 卡佔畫面比例);沒有卡的段回 (None, 0.0)。
    """
    a = np.asarray(img, dtype=np.int16)[:, :, :3]
    d_hot = np.abs(a - HOT).max(axis=2)
    card = d_hot < CARD_TOL
    if card.mean() < 0.01:
        return None, 0.0
    # 🔴 兩道,各修一種壞法:
    #    ① CARD_TOL 收到 20 —— 擋「別的油墨色走樣成 HOT」(ACCENT 距 29)
    #    ② 只取最大連通元件 —— 擋「畫面別處有一塊也長得像 HOT」,
    #       不管那塊離 HOT 多近。①治色、②治位置,少一道就少一種。
    lab, n = ndimage.label(card)
    if n > 1:
        sizes = ndimage.sum(card, lab, range(1, n + 1))
        card = lab == (int(np.argmax(sizes)) + 1)
    ys, xs = np.where(card)
    box = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    near_bg = np.abs(box - BG).max(axis=2)
    near_hot = np.abs(box - HOT).max(axis=2)
    return float((near_bg < near_hot).mean()), float(card.mean())


def _card_ink_legacy(img):
    """**只給對照用,不要拿它量東西。** 這是 2026-09-11 修掉的那一版
    (門檻 45 + 全域外接框)。留著是為了讓 ⑧ 那一格能證明
    「承重的是 CARD_TOL 和最大連通元件那兩行」——
    綠燈的測試不區分是哪個改動讓它變綠,所以要有一列改壞會翻面的。"""
    a = np.asarray(img, dtype=np.int16)[:, :, :3]
    d_hot = np.abs(a - HOT).max(axis=2)
    card = d_hot < 45
    if card.mean() < 0.01:
        return None, 0.0
    ys, xs = np.where(card)
    box = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    near_bg = np.abs(box - BG).max(axis=2)
    near_hot = np.abs(box - HOT).max(axis=2)
    return float((near_bg < near_hot).mean()), float(card.mean())


def seg_bounds(slug):
    """每一段在時間軸上的 (起幀, 迄幀, 段長) —— 和 render_and_mux 同一套算術。"""
    out = ROOT / "reels" / slug
    idx, b = 0, {}
    for n in M.SEGS:
        with wave.open(str(out / f"seg_{n}.wav")) as w:
            dur = w.getnframes() / w.getframerate() + SEG_GAP
        k = int(dur * M.FPS)
        b[n] = (idx, idx + k, dur)
        idx += k
    return b


def want_index(i0, i1, frac):
    return min(i1 - 1, i0 + int((i1 - i0) * frac))


def pull(slug, idxs):
    """從 mp4 解出指定幀號(串流讀,不把整支載進記憶體)。"""
    mp4 = ROOT / "reels" / slug / f"{slug}_reel.mp4"
    if not mp4.exists():
        return {}
    need, got, last = set(idxs), {}, max(idxs)
    rd = iio.get_reader(str(mp4))
    try:
        for i, im in enumerate(rd):
            if i in need:
                got[i] = np.asarray(im)
            if i >= last:
                break
    finally:
        rd.close()
    return got


def load_E(slug):
    """那次渲染真正用的 E(副標已經被 caption() 寫進去了)。"""
    return json.loads((ROOT / "reels" / slug / "facts.json")
                      .read_text(encoding="utf-8"))


def redraw(slug, name, t, dur, E=None):
    """用同一份 facts.json 就地重畫一幀。"""
    E = E or load_E(slug)
    ctx = {"plt": M._plt(), "E": E, "rows": twist_rows(E)}
    return M.render_scene(name, t, dur, ctx)


def through_codec(img):
    """把一張影格過一次和產線一模一樣的編碼參數,再解回來。"""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        iio.imwrite(d / "f000000.png", img)
        subprocess.run(["ffmpeg", "-y", "-framerate", str(M.FPS),
                        "-i", str(d / "f%06d.png")] + ENC + [str(d / "x.mp4")],
                       check=True, capture_output=True)
        rd = iio.get_reader(str(d / "x.mp4"))
        try:
            return np.asarray(rd.get_next_data())
        finally:
            rd.close()


def main():
    missing = [s for s in SIX
               if not (ROOT / "reels" / s / f"{s}_reel.mp4").exists()]
    if missing:
        print(f"🔴 這幾支還沒有 mp4,這支不能跑:{missing}")
        return 1

    print("【調色盤邊距】卡片門檻 CARD_TOL = "
          f"{CARD_TOL},每一個其他油墨色到 HOT 的切比雪夫距:")
    margins = {}
    for nm, hx in INKS.items():
        c = np.array([int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)],
                     dtype=np.int16)
        margins[nm] = int(np.abs(c - HOT).max())
        print(f"    {nm:<7} {hx}  距 HOT {margins[nm]}")
    worst_ink = min(margins, key=margins.get)
    say(margins[worst_ink] > CARD_TOL,
        f"最近的那一個({worst_ink},距 {margins[worst_ink]})仍在門檻之外 "
        f"⇒ 沒有別的油墨色會被算成卡片")

    print(chr(10) + "【陰性 ①②】六支的 mp4,每段後段兩個時刻:")
    rows, bounds = [], {}
    for slug in SIX:
        b = seg_bounds(slug)
        bounds[slug] = b
        want = {want_index(i0, i1, f): (n, f)
                for n, (i0, i1, _) in b.items() for f in (0.85, 0.97)}
        got = pull(slug, sorted(want))
        for i in sorted(want):
            if i not in got:
                print(f"    🔴 {slug} f{i:06d} 解不出來")
                continue
            r, c = ink(got[i])
            rows.append((slug, want[i][0], i, r, c))
    ratios = [r[3] for r in rows]
    conts = [r[4] for r in rows]
    lo = min(rows, key=lambda r: r[3])
    print(f"    母體 {len(rows)} 張真幀(六支 × 五段 × 兩個時刻)")
    print(f"    非背景像素比例:最低 {min(ratios):.4%} "
          f"中位 {np.median(ratios):.4%} 最高 {max(ratios):.4%}")
    print(f"    最低那張:{lo[0]}/{lo[1]} f{lo[2]:06d}")
    print(f"    有字像素的色距:最低 {min(conts):.1f} 中位 {np.median(conts):.1f}")

    print("\n【陰性 ③】儀器橋接 —— 同一幀,mp4 解出來 vs 就地重畫:")
    bridge = []
    for slug in SIX:
        n = "turn"
        i0, i1, dur = bounds[slug][n]
        i = want_index(i0, i1, 0.85)
        a = pull(slug, [i]).get(i)
        b_img = redraw(slug, n, (i - i0) / M.FPS, dur)
        ra, _ = ink(a)
        rb, _ = ink(b_img)
        rel = abs(ra - rb) / max(rb, 1e-9)
        bridge.append((slug, ra, rb, rel))
        print(f"    {slug:<30} mp4 {ra:.4%}  重畫 {rb:.4%}  相對差 {rel:.1%}")

    print("\n【陽性 ④】四個油墨顏色全部塌成 BG,再過同一組編碼參數:")
    slug, name = SIX[0], "turn"
    i0, i1, dur = bounds[slug][name]
    t = (want_index(i0, i1, 0.85) - i0) / M.FPS
    keep = (M.FG, M.DIM, M.ACCENT, M.HOT)
    only_fg = None
    try:
        M.FG = M.BG
        only_fg, _ = ink(through_codec(redraw(slug, name, t, dur)))
        M.DIM = M.ACCENT = M.HOT = M.BG
        r_fg, c_fg = ink(through_codec(redraw(slug, name, t, dur)))
    finally:
        M.FG, M.DIM, M.ACCENT, M.HOT = keep
    print(f"    只塌 FG:{only_fg:.4%} ← **這樣是不夠的**,"
          f"DIM/ACCENT/HOT 的字還在")
    print(f"    四個都塌:{r_fg:.4%}(色距 {c_fg:.1f})")

    print("\n【陽性 ⑤】文字被平移出畫面(座標變換壞掉那一類),"
          "再過同一組編碼參數:")
    import matplotlib.axes
    orig_text = matplotlib.axes.Axes.text

    def shifted(self, x, y, s, *a, **k):
        return orig_text(self, x + 1.5, y, s, *a, **k)

    keep_guard = M.layout_guard
    try:
        matplotlib.axes.Axes.text = shifted
        # 先繞過才拿得到那一幀。⚠️ 仍要 draw() —— render_scene 靠 layout_guard
        # 那一次 draw 才有 renderer,直接換成 no-op 會在 buffer_rgba() 炸掉。
        M.layout_guard = lambda nm, ax, fig: fig.canvas.draw()
        r_xl, c_xl = ink(through_codec(redraw(slug, name, t, dur)))
        M.layout_guard = keep_guard                # 放回去,看它會不會先炸
        try:
            redraw(slug, name, t, dur)
            depth = None
        except SystemExit as e:
            depth = str(e).replace(chr(10), " ")[:90]
    finally:
        matplotlib.axes.Axes.text = orig_text
        M.layout_guard = keep_guard
    print(f"    {slug}/{name}:非背景像素比例 {r_xl:.4%}(色距 {c_xl:.1f})")
    print(f"    同一個變異,layout_guard 沒被繞過時:{depth or '🔴 沒炸'}")
    # ⚠️ 歷史事故的機制(ax.plot 觸發自動縮放、set_xlim 沒鎖)在**這支渲染器
    #    上結構性不可能** —— render_scene 只畫 ax.text 和一個 Rectangle,
    #    沒有任何會被自動縮放的 artist,所以拿掉 set_xlim 實測是 no-op
    #    (3.84%,和好幀一樣)。⇒ 對照要重現的是**結果**(畫面上沒有字),
    #    不是那一次的機制。這一行是負面結果的紀錄,不是刪掉了事。

    print(chr(10)+"【陰性 ⑥】判決卡內部 —— 整體指標對這張卡是盲的,單獨量:")
    cards = []
    for slug in SIX:
        i0, i1, dur = bounds[slug]["verdict"]
        i = want_index(i0, i1, 0.9)
        img = pull(slug, [i])[i]
        ci, frac = card_ink(img)
        whole, _ = ink(img)
        cards.append((slug, ci, frac, whole))
        print(f"    {slug:<30} 卡佔畫面 {frac:.2%} | 整體油墨 {whole:.2%} "
              f"| 卡內深色 {ci if ci is None else format(ci, '.2%')}")

    print(chr(10)+"【陽性 ⑦】把判決卡的字改成和色塊同色(HOT):")
    slug7 = SIX[0]
    i0, i1, dur7 = bounds[slug7]["verdict"]
    t7 = (want_index(i0, i1, 0.9) - i0) / M.FPS
    import matplotlib.axes
    o_text = matplotlib.axes.Axes.text

    def hot_text(self, x, y, s_, *a, **k):
        if k.get("color") == "#0E1116":
            k["color"] = M.HOT
        return o_text(self, x, y, s_, *a, **k)

    try:
        matplotlib.axes.Axes.text = hot_text
        bad = through_codec(redraw(slug7, "verdict", t7, dur7))
    finally:
        matplotlib.axes.Axes.text = o_text
    ci7, frac7 = card_ink(bad)
    whole7, _ = ink(bad)
    print(f"    {slug7}/verdict:卡佔畫面 {frac7:.2%} | 整體油墨 {whole7:.2%} "
          f"| 卡內深色 {ci7 if ci7 is None else format(ci7, '.2%')}")

    print(chr(10)+"【陽性⑧ / 陰性⑧b】verdict 段裡出現 ACCENT —— 這把尺自己的弱點:")

    def _verdict_frame(kill_card_text, add_accent):
        """就地重畫一張 verdict:可選(a)把卡上的字塗成 HOT=字全消失、
        (b)在卡片之外放一個 ACCENT 元素。兩者都過同一組編碼參數。"""
        ctx8 = {"plt": M._plt(), "E": load_E(slug7),
                "rows": twist_rows(load_E(slug7))}
        o8 = matplotlib.axes.Axes.text
        seen = {"n": 0}

        def patched(self, x, y, s_, *a, **k):
            if k.get("color") == "#0E1116":
                seen["n"] += 1
                if seen["n"] == 1 and add_accent:
                    o8(self, M.CAP_CX, M.SAFE_HI - 0.04, "tell me below",
                       ha="center", va="center", fontsize=44,
                       color=M.ACCENT, weight="bold", zorder=3)
                if kill_card_text:
                    k["color"] = M.HOT
            return o8(self, x, y, s_, *a, **k)

        try:
            matplotlib.axes.Axes.text = patched
            return through_codec(M.render_scene("verdict", t7, dur7, ctx8))
        finally:
            matplotlib.axes.Axes.text = o8

    img8 = _verdict_frame(True, True)     # 該被抓:字沒了,而且有 ACCENT
    img8b = _verdict_frame(False, True)   # 不該被抓:字還在,只是有 ACCENT
    ci8, fr8 = card_ink(img8)
    ci8b, fr8b = card_ink(img8b)
    ci8_old, fr8_old = _card_ink_legacy(img8)
    ci8b_old, fr8b_old = _card_ink_legacy(img8b)
    print(f"    字沒了+有 ACCENT:現行 {ci8:.2%}(卡佔 {fr8:.2%}) | "
          f"舊規則 {ci8_old:.2%}(卡佔 {fr8_old:.2%})")
    print(f"    字還在+有 ACCENT:現行 {ci8b:.2%}(卡佔 {fr8b:.2%}) | "
          f"舊規則 {ci8b_old:.2%}(卡佔 {fr8b_old:.2%})")

    # 地板落在「真幀最低」與「兩個陽性最高」之間的空隙裡。
    worst_pos = max(r_fg, r_xl)
    floor = (min(ratios) + worst_pos) / 2
    gap = min(ratios) / worst_pos if worst_pos > 0 else float("inf")
    print(f"\n地板 = {floor:.4%}(真幀最低 {min(ratios):.4%} 與陽性最高 "
          f"{worst_pos:.4%} 的中間;真幀是陽性的 {gap:.1f} 倍)")
    say(gap >= 3, "真幀與壞掉的幀之間有 3 倍以上的空隙 ⇒ 這個地板分得開兩者")
    say(min(ratios) > floor, f"六支的真幀全部在地板之上(最低 {min(ratios):.4%})")
    say(min(conts) >= CONT_FLOOR,
        f"有字像素的色距全部 ≥ {CONT_FLOOR}(最低 {min(conts):.1f}) ⇒ 不是黑底黑字")
    worst_bridge = max(bridge, key=lambda x: x[3])
    say(worst_bridge[3] < 0.30,
        f"mp4 和就地重畫對得上(最差 {worst_bridge[0]} 相對差 "
        f"{worst_bridge[3]:.1%})⇒ 用 mp4 當量具沒有把畫面量胖")
    say(r_fg < floor, f"四色全塌那一幀掉到地板之下({r_fg:.4%})⇒ 抓得到「黑底黑字」")
    say(only_fg is not None and only_fg > floor,
        f"而只塌 FG **抓不到**({only_fg:.4%},在地板之上)"
        f" ⇒ 這個陽性對照的強度是必要的,不是我挑好看的")
    say(r_xl < floor, f"文字被平移出畫面那一幀掉到地板之下({r_xl:.4%})")
    say(bool(depth), "同一個變異 layout_guard 會先炸 ⇒ 這一類壞法有兩道,不是一道")

    real_card = [c[1] for c in cards if c[1] is not None]
    card_floor = (min(real_card) + ci7) / 2 if ci7 is not None else min(real_card) / 2
    print(chr(10)+f"卡內地板 = {card_floor:.2%}(真卡最低 {min(real_card):.2%} 與陽性 "
          f"{0 if ci7 is None else ci7:.2%} 的中間)")
    say(len(real_card) == len(SIX),
        f"六支都找得到判決卡({len(real_card)}/{len(SIX)})")
    say(min(real_card) > card_floor,
        f"六支的卡內深色像素都在地板之上(最低 {min(real_card):.2%})⇒ 卡上真的有字")
    say(ci7 is not None and ci7 < card_floor,
        f"字改成 HOT 之後卡內深色掉到 {0 if ci7 is None else ci7:.2%} ⇒ 這格抓得到")
    say(abs(whole7 - max(c[3] for c in cards if c[0] == slug7)) < 0.06,
        f"而**整體指標幾乎沒動**({whole7:.2%} vs 真卡 "
        f"{[c[3] for c in cards if c[0] == slug7][0]:.2%})"
        f" ⇒ 證明整體那一格對這種壞法是盲的,⑥ 不是多餘的")

    real7 = [c[1] for c in cards if c[0] == slug7][0]
    say(ci8 is not None and ci8 < card_floor,
        f"⑧ verdict 裡有 ACCENT 時,字消失**照樣抓得到**({ci8:.2%} < 地板 "
        f"{card_floor:.2%})")
    say(ci8_old is not None and ci8_old > card_floor,
        f"⑧ 而**舊規則(門檻 45 + 全域外接框)會漏掉它**({ci8_old:.2%},在地板之上)"
        f" ⇒ 承重的是 CARD_TOL 和最大連通元件那兩行,改壞會翻面")
    say(ci8b is not None and ci8b > card_floor and abs(ci8b - real7) < 0.03,
        f"⑧b 反向對照:字還在時讀數回到真卡的量級"
        f"({ci8b:.2%} vs 真卡 {real7:.2%})⇒ 收緊門檻沒有把真卡切掉")

    print()
    print("結論:", "✓ 真幀有字、而兩種「沒有字」都抓得到" if all(ok)
          else "🔴 對照失敗 —— 這格不算數")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
