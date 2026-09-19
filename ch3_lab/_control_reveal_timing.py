#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`make_reel.reveal_guard()` 的對照 —— 揭露時序:同一刻,畫面 vs 旁白。

🔴 **這條量的是關係。** 旁白逐字正確(稿子檢查全綠)、畫面數字在事實庫裡
   查得到(事實庫檢查全綠),而觀眾**同一刻**聽到 minus 0.05、看到 r = 0.28。
   已上線的片六支中招。逐軌檢查對這一類是結構性盲的。

🔴 **兩條真事故都是「聽得到、看不到」。** 所以主不變量是 (A):
   旁白唸過的數字,那一列必須已經在畫面上。清單上的 (B)(畫面不准超前)
   也留著,但它在這條產線上**幾乎走不到** —— `ats` 是從 `cue` 算出來的,
   而且有 `max(a, prev)` 單向閂,只會把揭露往後推。
   ⇒ (B) 的陽性對照必須明說它證的是**守門的判斷**,不是產線的可達路徑
   (memory `verification-that-cannot-fail`:證不了會失敗的檢查等於沒有檢查)。

⚠️ **錨點的坑,實測過的**:把 (B) 錨在「那一列的**數字**被唸到的時刻」,
   會對 20 集裡的 15 集誤報 —— 因為產線的設計是「cue 一唸到就揭露,
   數字在同一句稍後才唸出來」,實測 49 列的提前量中位 2.52 秒、最大 7.59 秒。
   ⇒ (B) 錨在**那一列自己的 cue**。

⚠️ **不用合成字串**:cue、數字、旁白全部取自 rechecked_episodes.json。
"""
import json
import pathlib
import sys

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib                                        # noqa: E402
matplotlib.use("Agg")
import make_reel as M                                    # noqa: E402
from make_rechecked import twist_rows, val_str           # noqa: E402

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative",
     "label": "全部 20 集的 turn 段,整段每 0.5 秒取樣一次 ⇒ **reveal_guard** 全程安靜。"
              "⚠️ 這條只判 reveal_guard:render_scene 裡別的守門叫出來要**另外列出**"
              "(不算這條的成績,但也不准吞掉 —— 實測 backfire_effect 的字幕守門"
              "在 HEAD 版就會叫,是既有狀況不是這輪造成的)"},
    {"kind": "positive",
     "label": "(A) 真案例形狀:把**最後一列**的 cue 換成旁白裡**它自己那個數字之後**的一段真話"
              "(逐字抄的,列序不變 ⇒ 上游那道列序守門不會先攔下來)"
              "⇒ 旁白唸到它的數字時那一列還沒出現(缺口 ≥ 1.5 秒,才是事故的形狀"
              "—— 挪 25 個字元只造出 0.35 秒,那是產線的提前量,不是事故)。"
              "**凡是造得出這個形狀的集數,一集都不准漏。**"},
    {"kind": "positive",
     "label": "(B) 把某一列的值提前掛到真圖上(值、cue、旁白都取自真集)"
              "⇒ 它的 cue 還沒被唸到,必須叫。"
              "⚠️ 這一格證的是**守門的判斷**,不是產線走得到"},
    {"kind": "negative",
     "label": "@start 背景基準列與 display_only 列**豁免**"
              "(兩個都是產線既有的明示宣告,不是沉默)⇒ 不准因為它們而叫"},
]

MARK = "_control_reveal_timing.py 的 CASES"
FACTS = pathlib.Path(r"D:\carson-agent\ch3_lab\facts\rechecked_episodes.json")
ok = []


def say(good, msg):
    ok.append(good)
    print(f"  {'✓' if good else '🔴'} {msg}")


def turn_dur(E):
    """turn 段的估長,用產線自己那個估計式(字數 ÷ 2.6)。

    ⚠️ 這是**估**的 —— 真值來自 seg_turn.wav,而對照要能在渲染之前跑。
       真值那一份由 render_scene 裡的 reveal_guard 逐幀把關,不靠這裡。
    """
    return max(4.0, len(E["reel"]["turn"].split()) / 2.6)


def sweep(E, rows, step=0.5):
    """整段每 step 秒跑一次 render_scene(turn),回第一個叫出來的訊息。"""
    dur = turn_dur(E)
    ctx = {"plt": M._plt(), "E": E, "rows": rows}
    t = 0.0
    while t < dur:
        try:
            M.render_scene("turn", t, dur, ctx)
        except SystemExit as e:
            # reveal_guard 自己的訊息帶這個記號 ⇒ 分得出是不是這條在叫。
            who = "reveal" if MARK in str(e) else "other"
            return (who, f"t={t:.1f}s {e}")
        t += step
    return None


def revealable(rows):
    return [i for i, x in enumerate(rows)
            if x.get("es") is not None and x.get("es_kind")
            and (x.get("cue") or "").strip() != "@start"
            and not x.get("display_only")]


def main():
    eps = json.loads(FACTS.read_text(encoding="utf-8"))["episodes"]

    print(f"【陰性 ①】{len(eps)} 集的 turn 段,每 0.5 秒取樣:")
    noisy, other = [], []
    for E in eps:
        r = sweep(E, twist_rows(E))
        if r:
            (noisy if r[0] == "reveal" else other).append(
                (E["slug"], r[1].replace(chr(10), " ")[:120]))
    say(not noisy, f"reveal_guard 叫出來的集數:{noisy or '無'}")
    print(f"    ⚠️ 別的守門叫出來的(不算這條,但列出來):{other or '無'}")

    print(chr(10) + "【陽性 ②】(A) 把最後一列的 cue 換到它自己那個數字之後:")
    fired, missed, skipped = [], [], []
    for E in eps:
        rows = twist_rows(E)
        turn_txt = E["reel"]["turn"]
        cand = revealable(rows)
        if not cand:
            skipped.append((E["slug"], "沒有可揭露列")); continue
        iN = cand[-1]
        x = rows[iN]
        val = val_str(x["es_kind"], x["es"], x.get("es_is_max", False))
        nums = M.NUM_RE.findall(val.split(" = ")[-1])
        # 那個數字被唸到的時刻;cue 要挪到**它之後 1.5 秒以上**,
        # 才真的造出「聽得到、看不到」的窗口。
        tab = M._spk_table(turn_txt)
        spk_all = max(1, tab[-1])
        dur = turn_dur(E)
        def t_of(k):
            return tab[max(0, min(k, len(tab) - 1))] / spk_all * dur
        q = max([turn_txt.find(nm) + len(nm) for nm in nums] or [-1])
        if q < 0:
            skipped.append((E["slug"], "值的數字在旁白裡找不到")); continue
        want = t_of(q) + 1.5 + 0.35          # 0.35 = 產線的提前量,要扣回去
        qc = next((k for k in range(q, len(turn_txt)) if t_of(k) >= want), None)
        prev_pos = (turn_txt.find((rows[cand[-2]].get("cue") or "").strip())
                    if len(cand) > 1 else -1)
        cue = turn_txt[qc:qc + 25].lstrip() if qc is not None else ""
        if qc is None or len(cue) < 8 or turn_txt.find(cue) <= prev_pos:
            skipped.append((E["slug"], "數字之後不足 1.5 秒,造不出缺口")); continue
        bad = [dict(r) for r in rows]
        bad[iN]["cue"] = cue
        r = sweep(E, bad)
        if r and r[0] == "reveal":
            fired.append(E["slug"])
        elif r:
            skipped.append((E["slug"], "別的守門先攔:" + r[1][:40]))
        else:
            missed.append((E["slug"], x.get("label"), val, cue[:20]))
    n = len(fired) + len(missed)
    print(f"    造得出這個形狀的 {n} 集;叫了 {len(fired)},漏了 {len(missed)}")
    print(f"    跳過 {len(skipped)} 集:{[k[1][:24] for k in skipped]}")
    if missed:
        print(f"    🔴 漏掉的:{missed}")
    say(len(fired) >= 1, f"至少一集被抓到(叫了的:{fired[:6]}…)")
    say(not missed, "造得出這個形狀的集數**一集都沒漏** —— 這條不是只對某一集成立")

    print(chr(10) + "【陽性 ③】(B) 把一列的值提前掛到真圖上(t=0,cue 還沒唸到):")
    b_fired, b_skip = [], []
    for E in eps:
        rows = twist_rows(E)
        cand = revealable(rows)
        if not cand:
            b_skip.append(E["slug"]); continue
        x = rows[cand[-1]]                       # 最後一列 = cue 在最後面
        dur = turn_dur(E)
        if E["reel"]["turn"].find((x.get("cue") or "").strip()) <= 0:
            b_skip.append(E["slug"]); continue
        plt = M._plt()
        fig = plt.figure(figsize=(M.W / 100, M.H / 100), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.text(0.5, 0.5,
                val_str(x["es_kind"], x["es"], x.get("es_is_max", False)),
                alpha=1.0)
        try:
            M.reveal_guard("turn", 0.0, dur, ax, {"E": E, "rows": rows})
        except SystemExit:
            b_fired.append(E["slug"])
        plt.close(fig)
    print(f"    叫了 {len(b_fired)}/{len(eps) - len(b_skip)} 集"
          f"(跳過 {len(b_skip)} 集:沒有可揭露列或 cue 就在開頭)")
    say(len(b_fired) >= (len(eps) - len(b_skip)) * 0.8,
        "(B) 真的會判超前 —— 它不是一段永遠不會叫的程式碼")

    print(chr(10) + "【陰性 ④】豁免那兩類不准變成誤擋:")
    n_start = sum(1 for E in eps for x in twist_rows(E)
                  if (x.get("cue") or "").strip() == "@start")
    n_disp = sum(1 for E in eps for x in twist_rows(E) if x.get("display_only"))
    print(f"    母體裡 @start 列 {n_start} 個、display_only 列 {n_disp} 個")
    say(n_start + n_disp > 0,
        "豁免路徑在母體裡真的走得到(不是一段永遠不執行的程式碼)")
    say(not noisy, "而①那一輪對它們全程安靜 ⇒ 豁免沒有變成誤擋")

    print()
    print("結論:", "✓ 對現況安靜、對「那一列還沒出現」會叫、豁免沒誤擋" if all(ok)
          else "🔴 對照失敗 —— 這道守門不算數")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
