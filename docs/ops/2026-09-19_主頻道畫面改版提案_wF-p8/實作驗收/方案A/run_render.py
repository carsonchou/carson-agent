# -*- coding: utf-8 -*-
"""沙箱端到端渲染 runner。

用法: python run_render.py <slug> <輸出mp4絕對路徑>

必須從沙箱 youtube_channel 目錄跑(cwd)。開頭的隔離斷言是硬性的:
venv 的 .pth / sitecustomize 會把 prod scripts 塞進 sys.path,沙箱缺哪個模組就靜默
載 prod 那份(dispatch.md「沙箱驗證必須用執行期證據斷言隔離」)。所以每個關鍵模組
都印出 __file__ 並斷言落在沙箱內,斷言不過就直接死,不准繼續渲。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SB = Path(__file__).resolve().parent / "youtube_channel"
os.chdir(str(SB))
sys.path.insert(0, str(SB / "scripts"))

os.environ["PROGRESSIVE_REVEAL"] = "1"
os.environ.pop("PEXELS_API_KEY", None)

import make_video as mv            # noqa: E402
import render_ffmpeg as rf         # noqa: E402
import concept_visuals as cvis     # noqa: E402

for m in (mv, rf, cvis):
    p = Path(m.__file__).resolve()
    print(f"[隔離] {m.__name__} <- {p}")
    assert str(p).lower().startswith(str(SB).lower()), f"{m.__name__} 載到沙箱外: {p}"
print(f"[隔離] PROJECT_ROOT = {mv.PROJECT_ROOT}")
assert str(Path(mv.PROJECT_ROOT).resolve()).lower() == str(SB).lower(), "PROJECT_ROOT 不在沙箱"

slug, out = sys.argv[1], sys.argv[2]
assert "carson-agent" not in out.replace("\\", "/"), "輸出路徑不可落在正式 repo 內"
t0 = time.time()
rc = mv.main(["--slug", slug, "-o", out])
el = time.time() - t0
print(f"[渲染] rc={rc} 耗時={el:.1f}s -> {out}")
print(f"[渲染] mp4存在={Path(out).exists()} 大小={Path(out).stat().st_size if Path(out).exists() else 0}")
sys.exit(0 if rc == 0 else 1)
