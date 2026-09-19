# -*- coding: utf-8 -*-
"""第四輪 before/after 端到端渲染驅動:兩支個股 × 兩份程式碼,依序跑。

BEFORE 沙箱 D:\\_sandbox_wFp8_B  = 現行正式碼(三支 scripts 的 sha256 與正式機逐位元相同)
AFTER  沙箱 D:\\_sandbox_wFp8_R4 = 加了語意白名單 + 折行修補

輸出 mp4 與 log 全部落在沙箱內,不進 repo。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = r"D:\carson-agent\youtube_channel\.venv\Scripts\python.exe"
RUNNER = str(HERE / "run_render.py")
LOGS = HERE / "render_logs"
LOGS.mkdir(exist_ok=True)

SLUGS = {
    "1560": "L_個股體檢中砂1560誰說個股一定贏大盤中砂近10年定",
    "2330": "L_個股體檢EP1台積電233020年翻84倍但你要先熬",
}
SANDBOX = {
    "before": Path(r"D:\_sandbox_wFp8_B"),
    "after": Path(r"D:\_sandbox_wFp8_R4"),
}

rows = []
for phase, sb in SANDBOX.items():
    for tk, slug in SLUGS.items():
        out = sb / "after" / f"{phase}_{tk}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        log = LOGS / f"{phase}_{tk}.txt"          # .txt:.gitignore 的 *.log 會靜默吃掉 .log
        t0 = time.time()
        with log.open("w", encoding="utf-8", errors="replace") as fh:
            rc = subprocess.run([PY, RUNNER, str(sb / "youtube_channel"), slug, str(out)],
                                stdout=fh, stderr=subprocess.STDOUT).returncode
        el = time.time() - t0
        sz = out.stat().st_size if out.exists() else 0
        rows.append((phase, tk, rc, round(el, 1), sz, str(out)))
        print(f"{phase}/{tk}: rc={rc} 耗時={el:.1f}s 大小={sz} -> {out}", flush=True)

print()
for r in rows:
    print(r)
sys.exit(0 if all(r[2] == 0 and r[4] > 0 for r in rows) else 1)
