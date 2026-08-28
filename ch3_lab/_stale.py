#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_stale.py — 列出「現行程式/資料會渲出不一樣的東西」的那幾支 Short。

判準跟 `publish_shorts.visual_stale` 同一組:旁白逐字比 + 畫面計畫比 +
**用現行碼重畫 9 幀的雜湊**比。手寫白話句改了會被前兩項抓到,寫死的
y 座標改了(頻道標記 0.915 → 0.900)只有第三項抓得到。

輸出一行一個 key,給 shell 迴圈吃。
"""
import json
import pathlib
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import make_short as M                                        # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
FAMOUS = ["ego_depletion", "bystander_effect", "implicit_bias_test",
          "sleep_memory", "romantic_red"]


def main():
    # 🔴 預設**只列還沒發布的**。已發布的 Short 也會被判陳舊(畫面確實
    #    跟現行碼不一樣了),但重渲它們沒有意義 —— Short 的畫面沒有
    #    `thumbnails.set` 那種原地換的路,只能重新上傳,而重新上傳會丟掉
    #    videoId、發布時間與已累積的觀看時數。
    #    把它們留在清單裡的真正代價是:「輸出為空才算乾淨」這條判準
    #    **以後永遠不會成立**,而那會訓練我忽略這支的輸出 —— 跟一個
    #    恆真的警告一樣糟。要看全部用 --all。
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="連已發布的一起列(預設只列待發布的)")
    a = ap.parse_args()
    led = ROOT / "uploaded_shorts.json"
    pub = json.loads(led.read_text(encoding="utf-8")) if led.exists() else {}
    skipped = []
    plt = M._plt()
    for kind, v in ([("row", r) for r in range(19)] +
                    [("slug", s) for s in FAMOUS]):
        D = M.collect(**{kind: v})
        key = D["key"]
        out = ROOT / "shorts" / key
        why = []
        for n, txt in M.build_script(D):
            f = out / f"narr_{n}.txt"
            if not f.exists() or f.read_text(encoding="utf-8") != txt:
                why.append(f"narr_{n}")
        vj = out / "visual.json"
        if not vj.exists():
            why.append("no-visual.json")
        else:
            was = json.loads(vj.read_text(encoding="utf-8"))
            now = M.visual_plan(plt, D)
            durs = {}
            for f in out.glob("seg_*.wav"):
                with wave.open(str(f)) as w:
                    durs[f.stem[4:]] = w.getnframes() / w.getframerate()
            D["_fs"] = now["fs"]
            try:
                now["frames"] = M.frame_digest(plt, D, durs) if durs else None
            except SystemExit as e:
                # ⚠️ 不包的話,一支觸發版面斷言就會**中止整支程式**,後面
                #    沒檢查的集數一行都不會印 —— 而這支的輸出是拿去餵
                #    shell 迴圈的:清單被截斷 = 被截掉的那幾支不會重渲,
                #    而且看起來像「沒問題」。publish_shorts 早就包了。
                why.append(f"現行碼會越界({str(e)[:40]})")
                print(f"{key}\t{','.join(why)}")
                continue
            # ⚠️ 要比**兩邊的鍵集合**。只走 now 的鍵,漏得掉「舊 visual.json
            #    有、現行碼已經拿掉」的殘留欄位;publish_shorts 是整包
            #    json.dumps 比對,比得出來。少報的方向正好是最危險的那個。
            for k in set(now) | set(was):
                if json.dumps(now.get(k), sort_keys=True) != \
                        json.dumps(was.get(k), sort_keys=True):
                    why.append(k)
        if why:
            if key in pub and not a.all:
                skipped.append(key)
                continue
            print(f"{key}\t{','.join(why)}")
    if skipped:
        # 印到 stderr:stdout 要能直接餵 shell 迴圈
        print(f"({len(skipped)} 支已發布的也陳舊,重渲無意義,已略過:"
              f"{', '.join(skipped)})", file=sys.stderr)


if __name__ == "__main__":
    main()
