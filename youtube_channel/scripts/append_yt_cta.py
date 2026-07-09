#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""append_yt_cta.py — 給 IG/TikTok 版影片接「訂閱量化阿森 YouTube」片尾卡(3 秒)。

YT 原片不動;只產衍生檔 output/<slug>_ytcta.mp4 給跨平台上傳用。
用 ffmpeg concat:原片 + 3 秒 CTA 卡(assets/cta_yt_endcard.png,scale 對齊原片解析度+補靜音)。
失敗一律回原片路徑,不阻斷跨發。
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "output"
CTA_PNG = ROOT / "assets" / "cta_yt_endcard.png"
CTA_SEC = 3.0


def _ff(name):
    import shutil
    return shutil.which(name) or name


def _probe(mp4: Path):
    """回 (width, height, fps) 或 None。"""
    try:
        r = subprocess.run([_ff("ffprobe"), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,r_frame_rate",
                            "-of", "json", str(mp4)], capture_output=True, text=True, timeout=30)
        s = json.loads(r.stdout)["streams"][0]
        num, den = (s["r_frame_rate"].split("/") + ["1"])[:2]
        fps = round(float(num) / float(den)) or 30
        return int(s["width"]), int(s["height"]), fps
    except Exception:  # noqa: BLE001
        return None


def append_cta(slug: str) -> Path:
    """回加了片尾卡的 mp4 路徑;任何問題退回原片(不阻斷跨發)。"""
    src = OUT / f"{slug}.mp4"
    dst = OUT / f"{slug}_ytcta.mp4"
    if not src.exists():
        return src
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    if not CTA_PNG.exists():
        try:
            import make_cta_card
            make_cta_card.make()
        except Exception:  # noqa: BLE001
            return src
    info = _probe(src)
    if not info:
        return src
    W, H, fps = info
    ff = _ff("ffmpeg")
    # 原片(v+a) + 3秒卡(scale對齊+靜音) → concat
    af = (f"[1:v]scale={W}:{H},setsar=1,fps={fps},format=yuv420p[card];"
          f"[0:v][0:a][card][2:a]concat=n=2:v=1:a=1[v][a]")
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src),
           "-loop", "1", "-t", str(CTA_SEC), "-i", str(CTA_PNG),
           "-f", "lavfi", "-t", str(CTA_SEC), "-i", "anullsrc=r=44100:cl=stereo",
           "-filter_complex", af, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return dst
        print(f"[cta] ffmpeg 失敗,退回原片:\n{r.stderr[-300:]}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[cta] 例外,退回原片:{e}", file=sys.stderr)
    return src


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else None
    if not slug:
        print("用法:python scripts/append_yt_cta.py <slug>", file=sys.stderr); sys.exit(2)
    p = append_cta(slug)
    print(f"[cta] 產出:{p.name}")
