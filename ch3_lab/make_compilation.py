#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_compilation.py — 把多集組成一支有結構的長片。

## 為什麼這是最大的槓桿
YPP 要 4,000 小時 = 240,000 分鐘。算式很殘忍:

  1.7 分鐘的片、每次觀看貢獻 1.3 分 → 需要 **184,615 次觀看**
  10 分鐘的片、每次觀看 3.5 分(主頻道實測)→ 需要 **68,571 次觀看**

同一批內容,只因為片長不同,需要的流量差 **2.6 倍**。而片長是這裡唯一
完全由我決定的變數 —— 流量不是。

## 但這不能是灌水
把同一件事講久一點會殺掉留存,那反而更糟(觀看時數 = 觀看數 × 停留時間,
灌水兩邊都輸)。所以合輯是**真的多給東西**:一支片講 5 個發現,每個都有
自己的主張、數字、判決。觀眾多留 5 倍是因為多看了 5 件事。

順帶解決兩個問題:
- **模板化**:一支片內含 5 種不同的結局與敘事,不再是「同一套版型換數字」
- **開場**:合輯的開場可以先拋出最強的那個落差當鉤子,而不是從第一個
  發現慢慢講起

## 誠信
不重算任何數字 —— 每一段都直接沿用該集已通過審核的旁白與畫面邏輯。
合輯自己只加「串場」,而串場**不做任何數字宣稱**。

用法:
  python make_compilation.py --bucket fail --limit 5
  python make_compilation.py --bucket fail --limit 5 --script-only
"""
import argparse
import json
import pathlib
import subprocess
import sys
import wave

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"

TITLES = {
    "fail": ("{n} psychology findings that did not survive a bigger test",
             "Every one of these was published, cited, and repeated. Then a "
             "much larger team ran the same study again."),
    "mixed": ("{n} findings that are real — and much smaller than you were told",
              "Not debunked. Corrected. This is the outcome that gets covered "
              "worst, because it has no villain."),
    "held": ("{n} psychology findings that actually held up",
             "You have heard a lot about the ones that broke. These did not."),
    # 🔴 這一支的標題**不能**是「N 個沒撐住的發現」—— 它裡面有三集不是
    #    那個結局。標題賣的就是「結局不只一種」這件事本身,而那也正好是
    #    這個頻道跟所有「心理學都是假的」影片的差別。
    "rechecked": ("{n} famous psychology studies, and {n} different things "
                  "that happened when somebody checked",
                  "Not one story. The data were fine and the arithmetic was "
                  "not. The method fell over and the idea did not. The author "
                  "says you read him wrong. And one is still an argument."),
}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams.update({"text.color": FG, "axes.labelcolor": DIM,
                         "xtick.color": DIM, "ytick.color": DIM})
    return plt




def cut_before_close(d):
    """算出「該集去掉結語」的精確秒數。

    ## 為什麼要去掉結語
    結語講的是方法論(出版偏誤/小樣本會晃),那是**跨集共用**的一段話。
    單集裡它是對的;六集接成一支片,同一段話會**原封不動播三遍**。實測:
    六集 113 秒結語只有 3 種文字,佔 11.4 分鐘成片的 17%。那不是內容,
    那是重播,而且正中 YPP inauthentic 政策點名的「變化極小」。

    所以合輯把結語從各段拿掉,在片尾**講一次**。片子會短 1.9 分鐘 ——
    但觀眾在第 4 分鐘離開的話,片子是 9 分還 11 分都只拿到 4 分鐘。
    灌重播不會增加觀看時數,只會減少。

    ## 為什麼這個秒數是精確的不是估的
    用的是 make_episode 混音時**同一條公式**:每段畫面 = int((wav 長度
    + 0.7) × FPS) 幀。三集對照實測誤差 0.000 秒。
    """
    ## 為什麼是「全部減掉結語」而不是「照順序累加到結語前一段」
    #  v3 之後**段落順序每集不同**(ep008 實測是 hook→original→scale→
    #  replication…),寫死一張順序表去推位置遲早會推錯集。但結語固定在
    #  最後,所以「總長 − 結語長」跟順序無關 —— 加法可交換。這樣連新增
    #  段落都不會讓它算錯。
    close = d / "seg_close.wav"
    if not close.exists():
        return None                      # 沒有結語 → 不裁,整集照用
    total = 0.0
    for f in sorted(d.glob("seg_*.wav")):
        with wave.open(str(f)) as w:
            total += int((w.getnframes() / w.getframerate() + 0.7) * FPS) / FPS
    with wave.open(str(close)) as w:
        tail = int((w.getnframes() / w.getframerate() + 0.7) * FPS) / FPS
    cut = total - tail
    return cut if cut > 20 else None      # 裁完剩不到 20 秒 = 結構不對


def _mp4_of(i, d):
    """本體影片的路徑。`i` 是 FReD 的列號(int)或 rechecked 的 slug(str)。

    🔴 兩種集型共用這支合輯機器,而它原本到處寫死 `ep{i:03d}.mp4`。
       路徑組法散在四個地方,加第二種來源時漏掉一個就是「檔案不存在」
       —— 而 ffprobe 對不存在的檔案回空字串,`float("")` 才炸,
       錯誤訊息完全指不到真正的原因。集中成一支。
    """
    return d / (f"ep{i:03d}.mp4" if isinstance(i, int) else f"{i}.mp4")


def pick_rechecked(limit):
    """從 `eps_rechecked` 挑 —— 這批的賣點是**每一集的結局形狀都不一樣**。

    所以排序不是「落差由大到小」(那是 FReD 那批的邏輯,因為它們的結局
    只有一種),而是**刻意讓相鄰兩集的故事類型不同**:先講「原始分析有
    偏誤」,再講「方法倒了假說還活著」,再講「原作者說你們讀錯了」。
    連著兩集同一種形狀,就是我在自己做出模板化。
    """
    src = json.loads((ROOT / "facts" / "rechecked_episodes.json")
                     .read_text(encoding="utf-8"))
    by = {e["slug"]: e for e in src["episodes"]}
    got = []
    for d in sorted((ROOT / "eps_rechecked").glob("*")):
        E = by.get(d.name)
        if not E or not (d / f"{d.name}.mp4").exists():
            continue
        got.append((0.0, d.name, E, d))
    # 相鄰不同型:貪婪地每次挑一個跟上一個不同 story_type 的。
    out, pool = [], list(got)
    last = None
    while pool and len(out) < limit:
        nxt = next((x for x in pool if x[2]["story_type"] != last), pool[0])
        pool.remove(nxt)
        out.append(nxt)
        last = nxt[2]["story_type"]
    return out


def pick(bucket, limit):
    """挑出該 bucket 已產好的集數,依落差大小排序 —— 最戲劇性的放最前面當鉤子。"""
    if bucket == "rechecked":
        return pick_rechecked(limit)
    from make_episode import build_facts, TONE_META
    q = pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
    out = []
    for i, r in q.iterrows():
        d = ROOT / "eps" / f"ep{i:03d}"
        if not (d / f"ep{i:03d}.mp4").exists():
            continue
        F = build_facts(r)
        if TONE_META[F["tone"]]["bucket"] != bucket:
            continue
        gap = abs(abs(F["orig"]["es"]) - abs(F["repl"]["es"]))
        out.append((gap, i, F, d))
    out.sort(key=lambda x: -x[0])
    return out[:limit]


def card_question(i, F):
    """串場要唸的那句。取該集**已通過審核**的標題(publish_meta),砍掉會
    洩漏結果的後綴 —— 串場的工作是給下一段一個懸念,不是先講答案。"""
    if not isinstance(i, int):
        # rechecked:白話問句是手寫的、已經過 plain._valid(必須以問號
        # 結尾、不准有數字),直接用 —— 那正是串場卡要的東西,
        # 而且跟縮圖與 Short 開場是同一句(同一個問題只有一個說法)。
        import plain as _plain
        q = _plain.spoken(f"eps_rechecked/{i}", i)
        if not q:
            raise SystemExit(f"⛔ {i} 缺手寫白話句,串場卡不產")
        return q
    q = F["claim"].rstrip(". ")
    p = ROOT / "publish_meta.json"
    if p.exists():
        m = {o.get("dir"): o for o in json.loads(p.read_text(encoding="utf-8"))}
        o = m.get(f"eps/ep{i:03d}")
        if o:
            t = o["title"]
            # 🔴 標題的判決後綴有兩種接法:破折號(「… — It came back
            #    stronger.」)和句號(「…what you own? It came back
            #    stronger.」)。只砍破折號會讓第二種**在串場卡上先把結果
            #    講出來** —— 而串場卡存在的唯一理由就是製造懸念。
            #    有問號就切在問號,那是最可靠的界線。
            if "?" in t:
                t = t[:t.index("?") + 1]
            else:
                for sep in (" — ", " – ", " -- ", ". "):
                    if sep in t:
                        t = t.split(sep)[0]
                        break
            q = t.strip().rstrip(". ")
    return q if q.endswith("?") else f"The claim: {q}."


def build_script(bucket, items):
    """串場只負責銜接,**不做任何數字宣稱** —— 數字全在各集自己的段落裡。

    兩件事是為了合輯特別做的:
    - **每張串場卡唸出下一個主張**。原本只唸「Number 3」,那是 2 秒空白;
      唸出問題等於在每一段前面補一個小鉤子,而且每張卡都不一樣。
    - **方法論結語只在片尾講一次**。各集自己的結語已由 `cut_before_close`
      裁掉,原因見那支的說明。
    """
    from make_episode import say_num
    n = len(items)
    lead = items[0][2]
    if bucket == "rechecked":
        # 🔴 這一支的開場**不能**是「原始 X,重測 Y」—— 那是 FReD 那批的
        #    形狀,而這批裡有三集根本不是那個形狀(原始分析有偏誤、方法倒
        #    了假說還活著、至今仍有爭議)。用那個開場等於在片頭就把後面
        #    三集講錯。開場講的是這支片**為什麼跟你看過的那種不一樣**。
        types = []
        for _, _i, E, _d in items:
            if E["story_type_short"] not in types:
                types.append(E["story_type_short"])
        segs = [("intro",
                 f"You have heard that psychology has a replication crisis. "
                 f"What you have probably not heard is that the interesting "
                 f"part is not the studies that failed. "
                 f"Here are {n} famous findings, and {n} different things "
                 f"that happened when somebody checked. "
                 f"In one of them the original data were fine and the "
                 f"arithmetic was not. In another the method fell over and "
                 f"the idea behind it did not. In another the original author "
                 f"published a paper to say he had been misread. "
                 f"And one of them is still an open argument, which I will "
                 f"say plainly when we get there. "
                 f"Every number comes from the paper it is quoted from, and "
                 f"every paper is linked below.")]
        for k, (_, i, E, _d) in enumerate(items, 1):
            lead_in = "First." if k == 1 else f"Number {k}."
            segs.append((f"card{k}", f"{lead_in} {card_question(i, E)}"))
        segs.append(("outro",
                     "If there is one thing to take from this, it is that "
                     "\"it did not replicate\" is not one story. Sometimes the "
                     "finding was never there. Sometimes it was there and much "
                     "smaller than the headline. Sometimes the result was fine "
                     "and the analysis was not. Sometimes the argument is still "
                     "running, and the honest answer is that we do not know "
                     "yet. Anyone who tells you the whole field is fake is "
                     "doing the same thing they are accusing it of: picking "
                     "the result that makes the better story. "
                     "Every paper here is linked below, with the sentence each "
                     "number was taken from."))
        return segs
    segs = [("intro",
             f"In {lead['orig']['year']}, a study reported an effect of "
             f"{say_num(lead['orig']['es'])}. "
             f"When a far larger team ran the same study again, the number "
             f"came back {say_num(lead['repl']['es'])}. "
             f"That is the first of {n} findings in this video. "
             f"Every number comes from the published replication record, and "
             f"every paper is linked below.")]
    for k, (_, i, F, _d) in enumerate(items, 1):
        lead_in = "First." if k == 1 else f"Number {k}."
        segs.append((f"card{k}", f"{lead_in} {card_question(i, F)}"))
    segs.append(("outro",
                 "A bigger sample is not a guarantee of truth. But the filter "
                 "runs one way: a study that finds nothing is harder to publish "
                 "than one that finds something, so the first number to reach "
                 "print is drawn from the lucky tail. That is publication bias "
                 "— a property of the filter, not an accusation against anyone. "
                 "Every finding here came from the same public database, one "
                 "row each, with the original paper and the replication both "
                 "linked below. Nothing was estimated. And when a finding does "
                 "survive a larger test, it gets its own video too."))
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="fail",
                    choices=["fail", "mixed", "held", "rechecked"])
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()

    items = pick(a.bucket, a.limit)
    if len(items) < 2:
        print(f"⛔ {a.bucket} 只有 {len(items)} 集產好,不夠組合輯")
        return 1
    n = len(items)
    title = TITLES[a.bucket][0].format(n=n)
    print(f"[{a.bucket}] {title}")
    total = 0.0
    for gap, i, F, d in items:
        mp4 = _mp4_of(i, d)
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(mp4)],
                           capture_output=True, text=True)
        dur = float(r.stdout.strip())
        total += dur
        # rechecked 沒有「原始 es → 重測 es」這一對(它的重點就是結局
        # 形狀不只一種),印它自己那句判決。
        tail = (F["story_type_short"] if "story_type_short" in F
                else f"{F['orig']['es']:+.2f} → {F['repl']['es']:+.2f}")
        print(f"  {str(i):<18}{dur:>5.0f}s  {tail}")
    segs = build_script(a.bucket, items)
    print(f"\n主體 {total:.0f} 秒 = {total/60:.1f} 分,加串場約 "
          f"{(total + 45)/60:.1f} 分")
    if a.script_only:
        for k, t in segs:
            print(f"  --- {k} ---\n  {t}")
        return 0

    out = ROOT / "compilations" / a.bucket
    out.mkdir(parents=True, exist_ok=True)
    for k, t in segs:
        (out / f"narr_{k}.txt").write_text(t, encoding="utf-8")

    # 串場語音
    tts = out / "_tts_comp.py"
    names = tuple(k for k, _ in segs)
    tts.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        f"for n in {names!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        "    s, sr = k.create(t, voice='af_heart', speed=0.98, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<8}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(REPO / "_ttslab311" / "Scripts" / "python.exe"),
                    str(tts)], check=True, cwd=str(REPO))

    # 串場畫面
    plt = _plt()
    import imageio.v2 as iio
    clips = []
    for k, (gap, i, F, d) in enumerate(items, 1):
        card = out / f"card{k}"
        card.mkdir(exist_ok=True)
        with wave.open(str(out / f"seg_card{k}.wav")) as w:
            cd = w.getnframes() / w.getframerate() + 0.6
        for fi in range(int(cd * FPS)):
            fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
            fig.patch.set_facecolor(BG)
            ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
            ax.set_xlim(0, 1); ax.set_ylim(0, 1)
            ax.text(0.5, 0.72, f"{k}", ha="center", va="center", fontsize=200,
                    color="#1B222C", weight="bold")
            ax.text(0.5, 0.60, f"of {len(items)}", ha="center", fontsize=40,
                    color=DIM)
            # 唸什麼就寫什麼 —— 串場卡上讀得到下一段的主張,不是空白數字
            words, cur, rows = card_question(i, F).split(), "", []
            for wd in words:
                if len(cur) + len(wd) + 1 > 44:
                    rows.append(cur); cur = wd
                else:
                    cur = (cur + " " + wd).strip()
            rows.append(cur)
            for ri, ln in enumerate(rows[:4]):
                ax.text(0.5, 0.42 - ri * 0.09, ln, ha="center", va="center",
                        fontsize=46, color=FG, weight="bold")
            fig.canvas.draw()
            iio.imwrite(card / f"f{fi:05d}.png",
                        np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
            plt.close(fig)
        seg = out / f"card{k}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i",
                        str(card / "f%05d.png"), "-i", str(out / f"seg_card{k}.wav"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", str(seg)],
                       check=True, capture_output=True)
        for f in card.glob("*.png"):
            f.unlink()
        card.rmdir()
        clips.append(seg)
        # 該集去掉結語(理由見 cut_before_close)。裁不了就整集照用 ——
        # fail-safe 只能往「照原樣」倒,不能往「猜一個秒數」倒。
        src = _mp4_of(i, d)
        cut = cut_before_close(d)
        if cut:
            trimmed = out / f"body{k}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                            "-t", f"{cut:.3f}", "-c:v", "libx264", "-preset",
                            "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "160k", str(trimmed)],
                           check=True)
            clips.append(trimmed)
            print(f"  串場 {k}/{len(items)}  本體裁至 {cut:.1f}s(去結語)")
        else:
            clips.append(src)
            print(f"  串場 {k}/{len(items)}  ⚠️ 段落結構非預期,整集照用")

    # intro / outro
    for name in ("intro", "outro"):
        dd = out / name
        dd.mkdir(exist_ok=True)
        with wave.open(str(out / f"seg_{name}.wav")) as w:
            sd = w.getnframes() / w.getframerate() + 0.6
        lines = ([title] if name == "intro" else
                 ["Every number here is from", "the published record."])
        for fi in range(int(sd * FPS)):
            fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
            fig.patch.set_facecolor(BG)
            ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
            ax.set_xlim(0, 1); ax.set_ylim(0, 1)
            if name == "intro":
                cur, rows = "", []
                for wd in lines[0].split():
                    if len(cur) + len(wd) + 1 > 30:
                        rows.append(cur); cur = wd
                    else:
                        cur = (cur + " " + wd).strip()
                rows.append(cur)
                for ri, ln in enumerate(rows[:4]):
                    ax.text(0.5, 0.62 - ri * 0.10, ln, ha="center", va="center",
                            fontsize=58, color=FG, weight="bold")
            else:
                # 片尾放整份清單 —— 這是觀眾決定要不要再看一支的那一刻,
                # 給他看完整戰績比給他兩句標語有用。數字全部沿用各集事實庫。
                ax.text(0.06, 0.90, "WHAT YOU JUST WATCHED", fontsize=34,
                        color=DIM, weight="bold", va="center")
                for ri, (_g, _i, Fo, _dd) in enumerate(items):
                    y = 0.78 - ri * 0.115
                    cl = Fo["claim"].rstrip(".")
                    ax.text(0.06, y, f"{ri + 1}.", fontsize=34, color="#3C4450",
                            weight="bold", va="center")
                    ax.text(0.11, y, cl[:52] + ("…" if len(cl) > 52 else ""),
                            fontsize=32, color=FG, va="center")
                    ax.text(0.985, y,
                            f"{Fo['orig']['es']:+.2f}  →  {Fo['repl']['es']:+.2f}"
                            .replace("+", ""),
                            fontsize=34, color=DIM, weight="bold",
                            ha="right", va="center")
                    ax.plot([0.06, 0.985], [y - 0.055, y - 0.055],
                            color="#1B222C", lw=1.2)
            fig.canvas.draw()
            iio.imwrite(dd / f"f{fi:05d}.png",
                        np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
            plt.close(fig)
        seg = out / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i",
                        str(dd / "f%05d.png"), "-i", str(out / f"seg_{name}.wav"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", str(seg)],
                       check=True, capture_output=True)
        for f in dd.glob("*.png"):
            f.unlink()
        dd.rmdir()
        print(f"  {name} 完成")

    order = [out / "intro.mp4"] + clips + [out / "outro.mp4"]
    lst = out / "concat.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in order),
                   encoding="utf-8")

    # 剪接清單落檔。**章節時間戳只能從這裡算** —— 下游若自己重跑 pick()
    # 去推內容,只要期間有任何一集被重產或刪掉,算出來的就是另一支片的
    # 章節。這條線已經因為「同一件事兩份實作」出過七次錯,不再多一次。
    def _d(p):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(p)],
                           capture_output=True, text=True)
        return round(float(r.stdout.strip()), 3)

    rows, t = [], 0.0
    ep_of = {f"card{k}": it for k, it in enumerate(items, 1)}
    for p in order:
        d_s = _d(p)
        stem = p.stem
        rec = {"clip": p.name, "start": round(t, 3), "dur": d_s}
        if stem.startswith("body"):
            k = int(stem[4:])
            _g, i, F, _dd = ep_of[f"card{k}"]
            rec.update(row=i, claim=F["claim"], tone=F["tone"])
        elif stem.startswith("card"):
            _g, i, F, _dd = ep_of[stem]
            rec.update(row=i, kind="card")
        rows.append(rec)
        t += d_s

    final = out / f"{a.bucket}_compilation.mp4"
    # 🔴 manifest **最後才寫**。它是下游判斷「這份剪接清單配不配得上這支
    #    mp4」的唯一依據,所以在 mp4 產出之前就落檔,等於在重剪的整段
    #    期間留下一組「新清單 + 舊影片」——而那正是下游會拿來算章節的東西。
    #    先刪掉舊的:重剪失敗時寧可讓下游看到「沒有 manifest」而中止,
    #    也不要讓它看到一份對不上的。
    man = out / "manifest.json"
    if man.exists():
        man.unlink()
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", str(final)],
                   check=True, capture_output=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(final)],
                       capture_output=True, text=True)
    real = float(r.stdout.strip())
    tmp = man.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"bucket": a.bucket, "total": round(t, 3), "mp4_seconds": round(real, 3),
         "n": len(items), "title": title, "clips": rows},
        ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(man)            # 原子替換,不會留下半份
    print(f"完成 → {final}  ({real / 60:.1f} 分,manifest 記 {t / 60:.1f} 分)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
