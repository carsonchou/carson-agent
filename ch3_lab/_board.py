#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_board.py — 渲染 / 驗證 / 發布的即時狀態板。給 herdr 的大格子用。

一眼要能答三個問題:哪幾支還沒渲、哪幾支還沒驗、還剩多少配額。
"""
import json
import pathlib
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(R))

_DUR = {}


def dur(p):
    k = (str(p), p.stat().st_mtime)
    if k in _DUR:
        return _DUR[k]
    try:
        v = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)
    except Exception:                                        # noqa: BLE001
        v = 0.0
    _DUR[k] = v
    return v


def main():
    code = max((R / n).stat().st_mtime for n in
               ("make_reel.py", "render_pipeline.py", "make_rechecked.py"))
    led_s = json.loads((R / "uploaded_shorts.json").read_text("utf-8"))
    led_l = json.loads((R / "uploaded.json").read_text("utf-8"))

    print(time.strftime("  ch3 render/verify board    %H:%M:%S"))
    try:
        import quota
        print(f"  配額 {quota.remaining():,} / {quota.DAILY:,}"
              f"    長片 {quota.LONG}  短片 {quota.SHORT}  縮圖 {quota.THUMB}")
    except Exception as e:                                   # noqa: BLE001
        print(f"  配額讀不到:{e}")

    print()
    print("  短片                    片長   碼   驗證")
    ok_band = fresh_n = verified = 0
    for d in sorted((R / "reels").iterdir()):
        if not d.is_dir():
            continue
        mp4 = d / f"{d.name}_reel.mp4"
        if not mp4.exists():
            print(f"  {d.name:22}    --   --   渲染中")
            continue
        fresh = mp4.stat().st_mtime >= code
        fresh_n += fresh
        vf = d / "VERIFIED"
        st = "未驗證"
        if vf.exists():
            try:
                stamp = float(vf.read_text("utf-8").split()[0])
                if abs(mp4.stat().st_mtime - stamp) <= 2:
                    st = "已驗證"
                    verified += 1
                else:
                    st = "標記過期"
            except Exception:                                # noqa: BLE001
                st = "標記壞了"
        if f"reel_{d.name}" in led_s:
            st += " · 已上線"
        dd = dur(mp4)
        band = "" if 35 <= dd <= 50 else "  ⛔超帶"
        ok_band += 35 <= dd <= 50
        print(f"  {d.name:22} {dd:5.1f}s  {'新' if fresh else '舊'}   "
              f"{st}{band}")

    nf = sum(1 for d in (R / "eps_rechecked").iterdir()
             if d.is_dir() and (d / f"{d.name}.mp4").exists()
             and (d / f"{d.name}.mp4").stat().st_mtime >= code)
    print()
    print(f"  短片:{fresh_n}/14 最新碼   {ok_band}/14 在帶內   "
          f"{verified}/14 已驗證")
    print(f"  長片:{nf}/14 最新碼")
    print(f"  已上線:長 {len(led_l)}  短 {len(led_s)}")


if __name__ == "__main__":
    main()
