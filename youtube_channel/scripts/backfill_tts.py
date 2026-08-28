#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_tts.py — 補配音:把「有稿但沒音檔」和「稿比音檔新」的片救回渲染佇列。

## 為什麼(2026-08-29 的實際事故)
`rescue_redo.py` 救回 18 支稿,並且**正確地刪掉了舊的 mp3**(那些是用帶 prompt 洩漏的
旁白配的,不刪等於什麼都沒修)。結果渲染迴圈整整一小時零產出,日誌只寫:

    [cloud] 渲染 0/0 支

根因在 `hybrid_render.cloud_pending()`:

    mp3 = OUT / f"{slug}.mp3"
    if not mp3.exists():
        continue          # ← 缺音檔 = 靜默跳過,永遠不會被看見

**缺件被 `continue` 吞掉,不會壞、也不會叫**——那 18 支對整條產線變成隱形。
沒有任何一個階段負責「有 voice.txt 但沒 mp3 → 去把音檔配出來」。

## 第二個洞(同一個函式,還沒爆但遲早會)
`cloud_pending()` 比對 **mp3 vs mp4**(音檔比成片新 → 重渲),卻從不比對 **voice.txt vs mp3**。
也就是說:**稿改了、音檔沒重配**,渲染會拿舊音檔去配新稿,而且完全沒有警訊。
這正是洩漏救援的情境——當初若沒手動刪 mp3,救回來的 18 支會帶著洩漏旁白直接出廠。
所以這裡把判準補齊:`voice.txt` 比 `mp3` 新 = 音檔過期 = 必須重配。

## 用法
  python scripts/backfill_tts.py              # 列出缺音檔/音檔過期的
  python scripts/backfill_tts.py --apply
  python scripts/backfill_tts.py --apply --max 5
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

OUT = ROOT / "output"
MIN_MP3 = 50 * 1024  # 小於這個大小視同配音失敗(空檔/截斷)


def needs_tts():
    """回 [(slug, 原因)] —— 缺音檔,或音檔比稿舊(稿改過沒重配)。"""
    rows = []
    for vt in sorted(OUT.glob("*.voice.txt")):
        slug = vt.name[: -len(".voice.txt")]
        if not slug.startswith(("S_", "L_")):
            continue
        mp3 = OUT / f"{slug}.mp3"
        if not mp3.exists():
            rows.append((slug, "缺音檔"))
        elif mp3.stat().st_size < MIN_MP3:
            rows.append((slug, f"音檔過小({mp3.stat().st_size // 1024}KB)"))
        elif vt.stat().st_mtime > mp3.stat().st_mtime + 5:
            # 稿比音檔新 = 音檔是舊稿配的。渲染端不查這一層,不補會拿舊音檔配新稿。
            rows.append((slug, "音檔過期(稿較新)"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=100)
    args = ap.parse_args()

    rows = needs_tts()
    print(f"需要配音:{len(rows)} 支")
    for slug, why in rows[:30]:
        print(f"  [{why}] {slug[:52]}")
    if not args.apply:
        print("\n[dry-run] 未動。要真的配音:--apply")
        return 0

    import produce_batch as pb

    ok = fail = 0
    for slug, why in rows[: args.max]:
        t0 = time.time()
        try:
            pb._run_tts(slug)
        except Exception as e:  # noqa: BLE001
            print(f"❌ {slug[:40]} 例外 {str(e)[:60]}")
            fail += 1
            continue
        mp3 = OUT / f"{slug}.mp3"
        if mp3.exists() and mp3.stat().st_size >= MIN_MP3:
            ok += 1
            print(f"✅ {mp3.stat().st_size // 1024:>5}KB {time.time() - t0:5.1f}s  {slug[:44]}")
        else:
            fail += 1
            print(f"❌ 配音沒產出檔案  {slug[:44]}")

    print(f"\n配音成功 {ok} / 失敗 {fail}")
    if ok:
        print("渲染迴圈(hybrid_render --loop)下一輪就會撿起來。")
    try:
        from ops import log_ops

        log_ops("補配音", f"補 {ok} 支音檔(失敗 {fail});原因多為稿被改寫後音檔沒重配")
    except Exception:  # noqa: BLE001
        pass
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
