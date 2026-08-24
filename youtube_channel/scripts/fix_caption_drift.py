#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_caption_drift.py — 重傳「字幕跟聲音對不上」的舊字幕軌。

## 為什麼(2026-08-24 Carson 看片時回報)
`write_srt_for_slug` 在 **2026-08-17** 修好了兩個疊加的錯(見 make_video.py 該段註解):
  ①用 **mp4 總長**(含片頭 3s + 片尾)去分配字幕,但旁白只佔中間 → 越後面偏差越大
  ②**完全沒有片頭位移**,字幕從 0s 起跑而語音 3s 後才開始 → 全片系統性早 3 秒
現在會優先吃 TTS 的逐句真實時戳(`{slug}.wordtimes.json`)並補上 INTRO 位移。
實測現行產出:真實時戳 0.10s + INTRO 3.0s = SRT 00:00:03,100,分毫不差。

**但那只影響之後發布的片。** 08-17 之前發布的 167 支,YouTube 上掛的仍是舊字幕軌。
實測舊估算法的偏差:最大 **2.6~4.9 秒** —— 而燒進畫面的字幕早就在用真實時戳,
所以同一支片裡「燒錄字幕準、CC 字幕飄」,兩條同時出現,看起來就是對不上。

## 做法
1. 用現行邏輯重產 SRT(自動吃 wordtimes)
2. **自檢**:第一句的起始時間必須 ≈ wordtimes 第一句 t + INTRO(誤差 <0.3s)。
   不過就跳過——沒有時戳的片重產出來也只是估算版,花配額換一樣爛的東西沒意義。
3. `captions.list` 找出我們自己上傳的那條軌(排除 YouTube 自動產生的 ASR)
4. `captions.update` 換掉內容(保留同一條軌,不會多一條)

## 配額
list 50 + update 450 ≈ 500 units/支;117 支 ≈ 58,500 units → 分批跑,預設 --max 20
(1 萬 units,留給發布/縮圖/音軌)。**依觀看數由高到低修**,最多人看到的先修好。

用法:
  python scripts/fix_caption_drift.py                  # dry-run
  python scripts/fix_caption_drift.py --apply --max 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
DONE = STUDIO / "caption_drift_fixed.json"


def _selfcheck(slug):
    """回 (ok, 原因, srt路徑)。重產 SRT 並確認它真的用到了真實時戳。"""
    import make_video as mv
    wt = OUT / f"{slug}.wordtimes.json"
    if not wt.exists():
        return False, "沒有真實時戳(重產也只是估算版)", None
    srt = mv.write_srt_for_slug(slug)
    if not srt:
        return False, "SRT 產不出來", None
    try:
        marks = json.loads(wt.read_text(encoding="utf-8"))
        first = next(w for w in marks
                     if (w.get("text") or "").strip() and float(w.get("d", 0)) > 0)
        want = float(first["t"]) + float(getattr(mv, "INTRO_DURATION", 3.0))
        head = Path(srt).read_text(encoding="utf-8", errors="replace").split("\n")
        ts = next(l for l in head if "-->" in l)
        hh, mm, rest = ts.split(":")[0], ts.split(":")[1], ts.split(":")[2]
        got = int(hh) * 3600 + int(mm) * 60 + float(rest.split(" ")[0].replace(",", "."))
        if abs(got - want) > 0.3:
            return False, f"時間軸對不上(SRT {got:.2f}s vs 應為 {want:.2f}s)", None
    except Exception as exc:  # noqa: BLE001
        return False, f"自檢失敗 {str(exc)[:50]}", None
    return True, "", srt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=20, dest="mx")
    args = ap.parse_args()

    import daily_publish as dp
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    info = {}
    try:
        info = json.loads((STUDIO / "_true_views.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()

    cands = []
    for slug, vid in led.items():
        if not isinstance(vid, str) or len(vid) != 11 or not slug.startswith("L_"):
            continue
        if vid in done or not (OUT / f"{slug}.wordtimes.json").exists():
            continue
        cands.append((slug, vid, (info.get(vid) or {}).get("v", 0)))
    # 最多人看到的先修
    cands.sort(key=lambda x: -x[2])
    print(f"可修的已發布長片(有真實時戳、尚未修):{len(cands)} 支;本輪最多 {args.mx} 支\n")
    if not cands:
        print("都修完了(冪等)。")
        return 0

    yt = dp.get_service() if args.apply else None
    import upload_youtube as up
    n = skip = err = 0
    for slug, vid, views in cands[:args.mx]:
        ok, why, srt = _selfcheck(slug)
        if not ok:
            print(f"[skip] {vid} {why} {slug[:28]}")
            skip += 1
            continue
        if not args.apply:
            print(f"[dry] {vid} 觀看{views:>5} {slug[:34]}")
            n += 1
            continue
        try:
            r = yt.captions().list(part="snippet", videoId=vid).execute()
            mine = [c for c in r.get("items", [])
                    if c["snippet"].get("trackKind") != "ASR"]
            if not mine:
                print(f"[skip] {vid} 線上沒有我們上傳的字幕軌(只有自動字幕)")
                skip += 1
                continue
            from googleapiclient.http import MediaFileUpload
            media = MediaFileUpload(str(srt), mimetype="application/octet-stream",
                                    resumable=False)
            yt.captions().update(part="snippet", body={"id": mine[0]["id"]},
                                 media_body=media).execute()
            done.add(vid)
            DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
            n += 1
            print(f"✅ {vid} 觀看{views:>5} 字幕已重傳 {slug[:28]}")
        except Exception as exc:  # noqa: BLE001
            err += 1
            print(f"[err] {vid} {str(exc)[:110]}")
            if "quota" in str(exc).lower():
                print("配額用盡,停止(冪等,下次接著修)")
                break
    print(f"\n修好 {n} / 跳過 {skip} / 失敗 {err};還剩 {len(cands)-n} 支")
    if args.apply and n:
        try:
            from ops import log_ops
            log_ops("字幕重傳", f"修正 {n} 支字幕漂移(還剩 {len(cands)-n})")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
