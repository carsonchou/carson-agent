#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_truncation.py — 【唯讀稽核】P0 品質災難盤點(2026-07-13)。

背景：QC 實測發現 L_0056高股息月月配十年少賺18倍回測拆穿股息再投入(已發布,videoId
4MfqI0b6Ci8)——旁白 mp3 長 218.9 秒,成品 mp4 只有 61.7 秒,旁白後面 ~72% 內容從沒被
剪進畫面就發布出去。這支腳本掃 output/ 下**所有** mp4,比對成品時長 vs 對應旁白(mp3)
時長,揪出同類「斷尾壞檔」，並交叉 STUDIO/uploaded_ledger.json 標出哪些已發布到 YouTube。

**唯讀**：只探測、只印報告，絕不改動/刪除任何檔案。

判定：
  ratio = mp4 時長 / mp3 時長
  ratio < 0.9  → 疑似截斷(旁白沒剪完)
  ratio > 1.5(且 mp4 比「音檔+intro+outro(7s)」多出 >5s) → 反向異常(尾巴空黑/多餘靜幀)
  0.9 <= ratio <= 1.5 → 正常(intro 3s + outro 4s 本就會讓 mp4 略長於旁白，屬預期)

用法：
  python scripts/audit_truncation.py                # 印報告
  python scripts/audit_truncation.py --json out.json # 同時把完整結果落 JSON
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

TRUNC_RATIO = 0.9   # mp4/mp3 < 此值 = 疑似截斷(旁白沒剪完)
TAIL_RATIO = 1.5    # mp4/mp3 > 此值 = 疑似反向異常(尾巴空黑)
INTRO_OUTRO_PAD = 7.0  # INTRO_DURATION(3.0)+OUTRO_DURATION(4.0)，算「多長算異常」時扣掉這段正常開銷


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def probe_duration(path: Path) -> float:
    """回傳媒體檔時長(秒)；探測失敗回 0.0。純唯讀，不寫任何檔案。

    🔴 2026-08-29 改用 ffprobe:原本走 `ffmpeg -i` 解 stderr 的 Duration——那會讓 ffmpeg
    去 demux/解析整個檔頭,單檔約 0.5~1s。output/ 有 1,090 支 mp4(加上對應 mp3 = 2,180 次
    子程序),整輪要跑 20~35 分鐘,而且工具是「全掃完才印」→ 實際上**沒有人會等它跑完**,
    等於這道稽核長期形同不存在。ffprobe 只讀 container metadata,同一批快一個量級,
    快到可以每天排程跑。ffprobe 不在 PATH 時仍退回原本的 ffmpeg -i 解析。
    """
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=25)
        v = float((r.stdout or "").strip() or 0)
        if v > 0:
            return v
    except Exception:  # noqa: BLE001
        pass
    try:
        ff = _ffmpeg_exe()
        out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=25)
        txt = out.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
        return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def load_ledger() -> dict:
    p = STUDIO / "uploaded_ledger.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def audit_all() -> list[dict]:
    """掃 output/ 下所有 <slug>.mp4，比對 <slug>.mp3。回傳每支的稽核結果(dict list)。
    衍生檔(如 *_ytcta.mp4)沒有同名 mp3 陪同，天然被跳過，不會誤判。"""
    ledger = load_ledger()
    rows = []
    for mp4 in sorted(OUT.glob("*.mp4")):
        slug = mp4.stem
        mp3 = OUT / f"{slug}.mp3"
        if not mp3.exists():
            continue  # 找不到對應旁白(多半是 _ytcta 等衍生檔)，無從比對，略過
        vdur = probe_duration(mp4)
        adur = probe_duration(mp3)
        video_id = ledger.get(slug)
        if adur <= 0 or vdur <= 0:
            rows.append({"slug": slug, "video_dur": vdur, "audio_dur": adur,
                        "ratio": None, "status": "探測失敗", "video_id": video_id})
            continue
        ratio = vdur / adur
        expected = adur + INTRO_OUTRO_PAD
        if ratio < TRUNC_RATIO:
            status = "截斷"
        elif ratio > TAIL_RATIO and (vdur - expected) > 5.0:
            status = "尾巴空黑"
        else:
            status = "正常"
        rows.append({"slug": slug, "video_dur": round(vdur, 2), "audio_dur": round(adur, 2),
                    "ratio": round(ratio, 3), "status": status, "video_id": video_id})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="唯讀稽核：掃 output/ 所有 mp4 vs 對應旁白 mp3 時長比對")
    ap.add_argument("--json", default=None, help="另存完整結果 JSON 的路徑")
    args = ap.parse_args()

    rows = audit_all()
    checked = [r for r in rows if r["status"] != "探測失敗"]
    bad = [r for r in rows if r["status"] not in ("正常",)]
    published_bad = [r for r in bad if r.get("video_id")]

    print("=" * 72)
    print(f"[audit_truncation] 稽核完成：共 {len(rows)} 支有旁白可比對的 mp4")
    print(f"  正常：{len(checked) - len([r for r in bad if r['status'] != '探測失敗'])} 支")
    print(f"  異常：{len(bad)} 支(含探測失敗)")
    print(f"  其中已發布到 YouTube：{len(published_bad)} 支")
    print("=" * 72)

    if bad:
        print("\n[異常清單]（依比值由低到高排序，越低越嚴重）")
        for r in sorted(bad, key=lambda r: (r["ratio"] if r["ratio"] is not None else -1)):
            pub = f"  ⚠️已發布 videoId={r['video_id']}" if r.get("video_id") else "  (未發布)"
            print(f"  [{r['status']:6s}] {r['slug'][:50]:50s} "
                 f"影片={r['video_dur']:>7}s 旁白={r['audio_dur']:>7}s 比值={r['ratio']}{pub}")

    if published_bad:
        print("\n[P0：已發布但異常的影片，需要 Carson 決定是否下架/重發]")
        for r in published_bad:
            print(f"  - {r['slug']} | videoId={r['video_id']} | {r['status']} | "
                 f"比值={r['ratio']} | 影片{r['video_dur']}s vs 旁白{r['audio_dur']}s")

    if not bad:
        print("\n[audit_truncation] 零截斷/零異常。")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完整結果已寫出：{args.json}")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
