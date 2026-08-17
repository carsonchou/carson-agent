#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rerender_jitter_fix.py — 重渲未發布長片庫存,吃掉畫面抖動修復。

## 為什麼(2026-08-17,兩位真實觀眾同時回報)
「畫面會一直抖」「為什麼畫面一直晃」——留言在 712 觀看和 290 觀看的個股體檢長片下,
那是本頻道搜尋流量的主力。逐幀量測坐實:zoompan 的 x/y 含 `iw/zoom/2`,zoom 隨時間
變動時整數取整讓**整幅畫面**位移 1~2px。掃描庫存 20/28 支中招。
渲染端已修並驗證(同一支片 10.0% → 0.0%),本支負責讓**已渲好的庫存**也吃到修正。

順帶吃到同批修的另一件事:卡片邊界對齊改成單調遞增搜尋。舊版遇到連續兩段旁白開頭
相同就對到同一句 → 靜默退回 per_seg 等分 → 畫面比旁白早十幾秒。等分不是無害的退路。

## 只做未發布的
已發布的片重上架會失去 videoId／觀看數／搜尋排名——搜尋排名正是本頻道唯一在成長的
資產,拿它換掉一個「有點晃」不划算。已發布的抖動只能認,並已在留言區向觀眾說明。

## 安全設計
- 渲到 `{slug}.__rr.mp4`,**驗證通過才** rename 覆蓋:過程中原檔始終完整,
  發布排程隨時挑走都拿得到能播的檔。
- 驗證三關:檔案 >1MB、有視訊軌、抖動率 <5%(修好的片實測 0%)。任一不過保留原檔。
- done 名單冪等,可隨時中斷續跑。
"""
from __future__ import annotations

import argparse
import json
import subprocess
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
DONE = ROOT / "STUDIO" / "rerender_jitter_done.json"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import audit_video as av

    led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    cands = sorted([p.stem for p in OUT.glob("L_*.mp4")
                    if p.stem not in led and p.stem not in done
                    and (OUT / f"{p.stem}.mp3").exists()])
    print(f"未發布長片 {len(cands)} 支待重渲(已完成 {len(done)})", flush=True)
    if args.dry_run:
        for s in cands[:args.max]:
            print("  ", s[:50])
        return 0

    ok = fail = 0
    for slug in cands[:args.max]:
        tmp = OUT / f"{slug}.__rr.mp4"
        t0 = time.time()
        print(f"\n▶ {slug[:46]}", flush=True)
        try:
            r = subprocess.run([str(PY), "-u", str(ROOT / "scripts" / "make_video.py"),
                                "--slug", slug, "-o", str(tmp)],
                               cwd=str(ROOT), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=3600)
            if r.returncode != 0 or not tmp.exists():
                print(f"  ✗ 渲染失敗 rc={r.returncode} {(r.stderr or '')[-160:]}", flush=True)
                fail += 1
                tmp.unlink(missing_ok=True)
                continue
            dur, has_v, has_a = av._probe(tmp)
            size = tmp.stat().st_size
            h, tot = av._frame_jitter(tmp, dur, points=6)
            rate = h / tot if tot else 0.0
            if size < 1024 * 1024 or not has_v or not has_a:
                print(f"  ✗ 產物異常 {size // 1024}KB v={has_v} a={has_a},保留原檔", flush=True)
                fail += 1
                tmp.unlink(missing_ok=True)
                continue
            if rate >= 0.05:
                print(f"  ✗ 仍有抖動 {h}/{tot}={rate * 100:.1f}%,保留原檔", flush=True)
                fail += 1
                tmp.unlink(missing_ok=True)
                continue
            old = OUT / f"{slug}.mp4"
            old.unlink(missing_ok=True)
            tmp.rename(old)
            done.add(slug)
            DONE.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
            ok += 1
            print(f"  ✅ {dur:.0f}s {size / 1e6:.1f}MB 抖動{rate * 100:.1f}% "
                  f"({time.time() - t0:.0f}s)", flush=True)
        except subprocess.TimeoutExpired:
            print("  ✗ 逾時 1 小時", flush=True)
            fail += 1
            tmp.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {str(exc)[:140]}", flush=True)
            fail += 1
            tmp.unlink(missing_ok=True)
    print(f"\n完成:成功 {ok} / 失敗 {fail} / 累計 {len(done)}", flush=True)
    try:
        from ops import log_ops
        log_ops("抖動重渲", f"重渲 {ok} 支(失敗 {fail},累計 {len(done)})")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
