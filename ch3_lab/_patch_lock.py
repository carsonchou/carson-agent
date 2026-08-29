# -*- coding: utf-8 -*-
"""render_pipeline 加單一實例鎖。

## 為什麼(2026-08-30 又踩一次)
我用 `cmd &` 起了一個 ep0 的渲染,以為它隨父程序死掉了,其實沒有。
接著用正規的背景任務又起一個。兩個實例寫**同一個** `frames/`,
互相刪對方的影格,最後產出:

    音軌 65.1 秒,影像 13.8 秒(414 幀)

而且 `render_and_mux` **回報成功**(mp4 檔在、大小 1.4MB),只有最後
`frames.rmdir()` 丟了一個 FileNotFoundError 才露餡。如果那行不存在,
我會拿一支前 14 秒之後全黑的片去發布。

08-29 已經踩過同一件事(兩個編排腳本渲同一批 Shorts,8/14 失敗),
那次的修法是在**外層 shell 腳本**加鎖 —— 修在呼叫端,所以換一個
呼叫端就沒有了。這次修在渲染管線本身。

## 鎖的判準
`kill -0` 在 Windows 認不得 PID(memory 記過),所以用**活性證明**:
鎖檔記 PID 與時間;若鎖存在且 `frames/` 在最近 90 秒內有變動,
就認定對方還活著。沒有活性證明的舊鎖直接接管 —— 「超時 = 死亡」
這種只看時間的判準本身也出過事(hybrid_render 判長片死亡那次),
所以這裡是「超時 **而且** 沒有活動」才接管。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "render_pipeline.py"

LOCK = '''

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

'''

HOOK = '''    lock = _claim(out)
'''

CHECK = '''    # 🔴 影格數必須配得上音軌長度。兩個實例互刪影格時,mux **照樣成功**
    #    ——ffmpeg 拿到幾張就編幾張,不會抱怨少了 1500 張。實測產出
    #    「音軌 65.1 秒、影像 13.8 秒」而函式回報完成。
    #    完成訊號必須配一個成敗證明,這就是那個證明。
    want = sum(int(durs[n] * FPS) for n, _ in segs)
    if abs(idx - want) > FPS:
        lock.unlink(missing_ok=True)
        raise SystemExit(
            f"⛔ 影格數對不上:畫了 {idx} 張,應該是 {want} 張"
            f"({idx / FPS:.1f}s vs {want / FPS:.1f}s)。"
            f"通常是兩個實例寫同一個 frames/。不 mux。")
'''


def main():
    s = P.read_text(encoding="utf-8")
    if "_claim" in s:
        print("已經打過了"); return 0

    s = s.replace("def tts(out, segs,", LOCK.strip("\n") + "\n\n\ndef tts(out, segs,", 1)

    anchor = ('    import imageio.v2 as iio\n'
              '    frames = out / "frames"\n')
    assert anchor in s, "找不到 render_and_mux 開頭"
    s = s.replace(anchor, HOOK + anchor, 1)

    mux = "    voice = out / \"voice.wav\""
    assert mux in s, "找不到混音段"
    s = s.replace(mux, CHECK + "\n" + mux, 1)

    tail = "    frames.rmdir()\n    return mp4, idx / FPS"
    assert tail in s, "找不到收尾"
    s = s.replace(tail, "    frames.rmdir()\n    lock.unlink(missing_ok=True)\n"
                        "    return mp4, idx / FPS", 1)

    P.write_text(s, encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("render_pipeline 已加鎖 + 影格數驗證,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
