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
            now["frames"] = M.frame_digest(plt, D, durs) if durs else None
            for k in now:
                if json.dumps(now[k], sort_keys=True) != \
                        json.dumps(was.get(k), sort_keys=True):
                    why.append(k)
        if why:
            print(f"{key}\t{','.join(why)}")


if __name__ == "__main__":
    main()
