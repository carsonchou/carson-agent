#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_pipeline.py — 旁白 → 逐幀 → 混音成 mp4。**共用的那一份。**

## 為什麼抽出來
`make_episode.py`(1056 行)、`make_famous.py`(609)、`make_short.py`(729)
三支各自帶一份 TTS + 逐幀 + ffmpeg mux —— 同一段程式碼三份。
新增第四種集型時再抄一份,就是這條線今天修了一整天的那個病
(同一件事兩份實作,已經第九次)。所以新集型走這裡。

⚠️ **舊的三支還沒遷移過來。** 那是刻意的:它們正在產出已排程要發的片,
而重構它們的驗證成本(要比對 `_baseline/` 的產物確認位元級無變化)
比這次要交付的東西大。**這是已知的技術債,不是忘了。**

## 這裡負責什麼、不負責什麼
負責:把 `segs`(段名 → 旁白文字)變成 wav、呼叫呼叫端給的 `render_fn`
逐幀畫、接起來 mux 成 mp4。
不負責:畫面長什麼樣、稿子寫什麼、事實從哪來 —— 那些是各集型自己的事。
"""
import pathlib
import subprocess
import wave

import numpy as np

#: 每段旁白之後補的靜音。**跟 make_episode.SEG_GAP 是同一個值** ——
#: 從那裡匯入而不是自己寫一個,因為 `lint_episode.scene_bounds` 也讀它,
#: 三處算同一條時間軸。今天就因為它被寫死在一處而讓守門量錯 1.4 秒。
from make_episode import SEG_GAP          # noqa: E402


def _claim(out):
    """同一個輸出目錄只准一個渲染程序。回傳鎖檔路徑,拿不到就中止。"""
    import os
    import time
    lk = out / ".render.lock"
    if lk.exists():
        try:
            pid, ts = lk.read_text(encoding="utf-8").split()
            pid, ts = int(pid), float(ts)
        except Exception:
            pid, ts = -1, 0.0
        if pid == os.getpid():
            return lk
        frames = out / "frames"
        live = 0.0
        if frames.exists():
            for f in frames.glob("*.png"):
                live = max(live, f.stat().st_mtime)
        # 🔴 「舊」不等於「死」。只有**又舊又沒在動**才接管 ——
        #    只看時間的死亡判準已經害過一次(長片天生渲超過門檻被判死,
        #    分身互搶記憶體死亡螺旋)。
        if time.time() - max(ts, live) < 90:
            raise SystemExit(
                f"⛔ {out.name} 已經有一個渲染程序在跑(PID {pid},"
                f"{time.time() - max(ts, live):.0f} 秒前還有動作)。"
                f"不重複啟動 —— 兩個實例會互刪影格,產出音軌對不上畫面"
                f"而且**回報成功**。")
        print(f"  接管過期的鎖(PID {pid},靜止 "
              f"{time.time() - max(ts, live):.0f} 秒)")
    lk.write_text(f"{os.getpid()} {time.time()}", encoding="utf-8")
    return lk


def tts(out, segs, voice="am_michael", speed=0.98):
    """用 Kokoro(3.11 獨立 venv)把每段旁白轉成 seg_<name>.wav。

    🔴 暫存腳本要**每集一個獨立檔名**。舊版寫死 `_tts_ep.py`,三個 worker
    並行時會互相覆蓋:A 寫好指向 ep015 的腳本、B 覆蓋成 ep017,
    A 的子程序讀到 B 的內容 → 音檔產到別集去。實測 ep015 就是這樣掛的。
    """
    repo = pathlib.Path(__file__).resolve().parent.parent
    script = out / f"_tts_{out.name}.py"
    script.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        # 段落名從 segs 推導,不寫死:先前加了新段卻沒同步,整條線到混音
        # 階段才炸(seg_xxx.wav 不存在)。
        f"for n in {tuple(n for n, _ in segs)!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        f"    s, sr = k.create(t, voice='{voice}', speed={speed}, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<12}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(repo / "_ttslab311" / "Scripts" / "python.exe"),
                    str(script)], check=True, cwd=str(repo))


def durations(out, segs):
    """每段的實際長度(含段尾靜音)。時間軸的唯一來源。"""
    d = {}
    for n, _ in segs:
        with wave.open(str(out / f"seg_{n}.wav")) as w:
            d[n] = w.getnframes() / w.getframerate() + SEG_GAP
    return d


def render_and_mux(out, segs, render_fn, mp4_name, W, H, FPS, ctx=None):
    """逐幀畫 → 接音軌 → mux。

    `render_fn(name, t, dur, ctx)` 要回傳一張 (H, W, 3) 的 uint8 影格。
    **mp4 最後才寫** —— 中途被砍只會留下舊檔,不會留半截檔案
    (2026-08-29 兩個編排實例互殺時,19 支長片一支都沒損毀就是因為這個)。
    """
    lock = _claim(out)
    import imageio.v2 as iio
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    durs = durations(out, segs)
    idx = 0
    for n, _ in segs:
        dur = durs[n]
        for i in range(int(dur * FPS)):
            iio.imwrite(frames / f"f{idx:06d}.png",
                        render_fn(n, i / FPS, dur, ctx))
            idx += 1
        print(f"  畫面 {n:<12}{dur:>6.1f}s")

    # 🔴 影格數必須配得上音軌長度。兩個實例互刪影格時,mux **照樣成功**
    #    ——ffmpeg 拿到幾張就編幾張,不會抱怨少了 1500 張。實測產出
    #    「音軌 65.1 秒、影像 13.8 秒」而函式回報完成。
    #    完成訊號必須配一個成敗證明,這就是那個證明。
    # 🔴 **要數磁碟上真正有幾張,不是數迴圈跑了幾次。**
    #    `idx` 是自己的迴圈計數 —— 兩個實例互刪影格時,**每一個實例的 idx
    #    都是對的**,因為它確實畫了那麼多次;被刪掉的是檔案。
    #    所以這道守門對它要防的那件事結構上是盲的,而且它盲得很安靜:
    #    2026-08-30 anchoring 就這樣產出「影像 95.6 秒 / 音軌 121.5 秒」
    #    而守門全綠,我還抽了一幀看起來好好的(壞的是最後 26 秒)。
    #    「寫完檢查先問它驗的是什麼」——這一個驗的是我的意圖,不是結果。
    on_disk = len(list(frames.glob("*.png")))
    want = sum(int(durs[n] * FPS) for n, _ in segs)
    if abs(on_disk - want) > FPS:
        lock.unlink(missing_ok=True)
        raise SystemExit(
            f"⛔ 磁碟上只有 {on_disk} 張影格,應該是 {want} 張"
            f"({on_disk / FPS:.1f}s vs {want / FPS:.1f}s)。"
            f"幾乎一定是兩個實例寫同一個 frames/。不 mux。")
    if abs(idx - want) > FPS:
        lock.unlink(missing_ok=True)
        raise SystemExit(
            f"⛔ 影格數對不上:畫了 {idx} 張,應該是 {want} 張"
            f"({idx / FPS:.1f}s vs {want / FPS:.1f}s)。"
            f"通常是兩個實例寫同一個 frames/。不 mux。")

    voice = out / "voice.wav"
    with wave.open(str(voice), "wb") as w:
        first = True
        for n, _ in segs:
            with wave.open(str(out / f"seg_{n}.wav")) as s:
                if first:
                    w.setparams(s.getparams()); first = False
                w.writeframes(s.readframes(s.getnframes()))
                w.writeframes(b"\x00" * int(SEG_GAP * s.getframerate() *
                                            s.getsampwidth() * s.getnchannels()))
    mp4 = out / mp4_name
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frames / "f%06d.png"),
         "-i", str(voice), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(mp4)],
        check=True, capture_output=True)
    for f in frames.glob("*.png"):
        f.unlink()
    frames.rmdir()
    lock.unlink(missing_ok=True)
    return mp4, idx / FPS
