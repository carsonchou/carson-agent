#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_qa_sample.py — 每週抽 3 支近期發布片,產一張「人眼 10 秒抽檢圖」。

## 為什麼(2026-08-12)
字幕錯位事故證明「渲染完成≠片是好的」:scene/凍結指標量像素不量畫面(memory
yt-visual-root-cause-per-seg),截斷殘骸 mp3 渲出的片 mp4/mp3 長度一致照樣放行。
機器閘門補得再多,總有下一種「靜默地少做一件事」。這支把抽檢成本壓到人眼 10 秒:
每週抽 3 支已發布片,各抽 6 格畫面拼成一張大圖,附機器探針(片長/語速/檔案大小/
亮度),Carson 掃一眼就能抓到黑畫面/字幕錯位/圖表崩版這類事故。

產出:STUDIO/REPORTS/<date>_每週抽檢.jpg + 同名 .md(探針數據)。
排程:每週日 08:00(deploy/crontab.txt)。唯讀抽樣,不動產線。
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
CJK = re.compile(r"[一-鿿]")

from audit_video import _probe, _ffmpeg_exe  # noqa: E402

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):
        pass


def pick_samples(n=3):
    """近 7 天發布的優先(用本地 mp4 mtime 近似);不足就往回補。"""
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    cands = []
    for slug in led:
        mp4 = OUT / f"{slug}.mp4"
        if mp4.exists():
            cands.append((mp4.stat().st_mtime, slug))
    cands.sort(reverse=True)
    recent = cands[:30]
    random.shuffle(recent)
    return [s for _, s in recent[:n]]


def probe_info(slug: str) -> dict:
    mp4 = OUT / f"{slug}.mp4"
    dur, has_v, has_a = _probe(mp4)
    info = {"slug": slug, "dur": dur, "has_v": has_v, "has_a": has_a,
            "size_mb": round(mp4.stat().st_size / 1e6, 1)}
    vt = OUT / f"{slug}.voice.txt"
    mp3 = OUT / f"{slug}.mp3"
    if vt.exists() and mp3.exists():
        adur, _, _ = _probe(mp3)
        cjk = len(CJK.findall(vt.read_text(encoding="utf-8")))
        info["rate"] = round(cjk / adur, 2) if adur else None
        info["ratio"] = round(dur / adur, 2) if adur else None
    return info


def main() -> int:
    from PIL import Image, ImageDraw
    day = date.today().isoformat()
    samples = pick_samples()
    if not samples:
        print("無可抽樣的已發布成片")
        return 0
    ff = _ffmpeg_exe()
    tiles, notes = [], []
    tw, th = 426, 240
    for slug in samples:
        inf = probe_info(slug)
        notes.append(inf)
        mp4 = OUT / f"{slug}.mp4"
        row = []
        for k in range(6):
            t = inf["dur"] * (k + 0.5) / 6
            fp = STUDIO / "REPORTS" / f"_qa_tmp_{k}.png"
            subprocess.run([ff, "-y", "-ss", str(int(t)), "-i", str(mp4),
                            "-frames:v", "1", "-s", f"{tw}x{th}", str(fp)],
                           capture_output=True,
                           **({"creationflags": 0x08000000} if sys.platform == "win32" else {}))
            try:
                img = Image.open(fp).convert("RGB")
            except Exception:  # noqa: BLE001
                img = Image.new("RGB", (tw, th), (60, 0, 0))  # 抽不到=紅格,本身就是警訊
            row.append(img)
            fp.unlink(missing_ok=True)
        tiles.append((slug, row))

    from PIL import ImageFont
    try:  # PIL 預設點陣字型是 latin-1,塞中文直接炸;正黑體是 Windows 內建
        font = ImageFont.truetype(r"C:\Windows\Fonts\msjh.ttc", 18)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    pad, header = 6, 34
    W = 6 * tw + 7 * pad
    H = len(tiles) * (th + header + pad) + pad
    sheet = Image.new("RGB", (W, H), (16, 18, 24))
    dr = ImageDraw.Draw(sheet)
    y = pad
    for slug, row in tiles:
        inf = next(n for n in notes if n["slug"] == slug)
        flag = ""
        if inf.get("rate") and inf["rate"] > 6.5:
            flag += " 🔴語速異常"
        if inf.get("ratio") and inf["ratio"] < 0.9:
            flag += " 🔴疑截斷"
        if not inf["has_a"]:
            flag += " 🔴無音軌"
        dr.text((pad, y + 8),
                f"{slug[:52]}  {inf['dur']:.0f}s {inf['size_mb']}MB "
                f"語速{inf.get('rate', '?')}字/s{flag}",
                fill=(255, 80, 80) if flag else (200, 205, 215), font=font)
        y += header
        x = pad
        for img in row:
            sheet.paste(img, (x, y))
            x += tw + pad
        y += th + pad

    outp = STUDIO / "REPORTS" / f"{day}_每週抽檢.jpg"
    sheet.save(outp, quality=85)
    md = [f"# 每週抽檢 {day}", "", f"抽檢圖:{outp.name}(人眼掃:黑畫面/字幕錯位/圖表崩版)", ""]
    for n in notes:
        md.append(f"- `{n['slug'][:48]}` {n['dur']:.0f}s / {n['size_mb']}MB / "
                  f"語速 {n.get('rate', '?')} 字/s / 音畫比 {n.get('ratio', '?')}")
    (STUDIO / "REPORTS" / f"{day}_每週抽檢.md").write_text("\n".join(md), encoding="utf-8")
    log_ops("抽檢部門", f"每週抽檢完成:{len(tiles)} 支 → {outp.name}")
    print(f"[ok] {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
