#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_live_thumbs.py — 直接看**線上**縮圖有沒有被黑邊夾住(直式圖塞進 16:9)。

## 為什麼要另外寫一支(fix_long_thumbs 為什麼看不到)
`fix_long_thumbs.py` 是拿 `assets/thumbnails/{slug}.jpg` 的尺寸判斷直式/橫式。
問題是本機那批檔案**後來被重新產生過**(現在全是 1280x720 橫式),而 YouTube 上掛的
仍然是當初上傳的那張直式圖 → 腳本回報「待修 0 支」,完全是假陰性。
**要看線上實況就得看線上那張圖。**

好消息:縮圖圖檔可以從 `https://i.ytimg.com/vi/<id>/maxresdefault.jpg` 直接抓,
**不吃 YouTube Data API 配額**(不是 API 端點,是 CDN 靜態檔)。

## 判定方式
直式圖被塞進 16:9 的框 → 左右兩側被補成黑柱(pillarbox)。
量左右各 12% 寬度的平均亮度,兩側都很暗(<18/255)且中間明顯更亮 → 判定被夾住。
本頻道縮圖本來就是深色風格,所以門檻取得保守,而且要求「兩側都暗 + 中間亮度是側邊的 2 倍以上」,
避免把整張都很暗的正常橫圖誤判。

用法:
  python scripts/audit_live_thumbs.py            # 掃全部已發布長片,只報告
  python scripts/audit_live_thumbs.py --limit 80
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
OUT = STUDIO / "live_thumb_audit.json"


def _fetch(vid):
    """回 PIL Image;maxres 不存在就退 hqdefault(YouTube 對舊片不一定產 maxres)。"""
    from PIL import Image
    for name in ("maxresdefault", "hqdefault", "mqdefault"):
        url = f"https://i.ytimg.com/vi/{vid}/{name}.jpg"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if len(data) < 2000:      # YouTube 對不存在的規格回一張很小的佔位圖
                continue
            return Image.open(BytesIO(data)).convert("L"), name
        except Exception:  # noqa: BLE001
            continue
    return None, None


def _pillarboxed(img):
    """左右被黑柱夾住 → (True, 左均, 右均, 中均)。"""
    w, h = img.size
    px = img.load()
    band = max(int(w * 0.12), 4)
    step = max(h // 60, 1)

    def avg(x0, x1):
        vals = [px[x, y] for y in range(0, h, step) for x in range(x0, x1, max((x1 - x0) // 12, 1))]
        return sum(vals) / max(len(vals), 1)

    left, right = avg(0, band), avg(w - band, w)
    mid = avg(int(w * 0.40), int(w * 0.60))
    hit = left < 18 and right < 18 and mid > max(left, right) * 2 + 8
    return hit, round(left, 1), round(right, 1), round(mid, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    longs = [(s, v) for s, v in led.items()
             if isinstance(v, str) and len(v) == 11 and s.startswith("L_")]
    longs.sort(key=lambda sv: (0 if "體檢" in sv[0] else 1, sv[0]))
    if args.limit:
        longs = longs[:args.limit]
    print(f"掃 {len(longs)} 支已發布長片的**線上**縮圖(不吃 API 配額)…\n")

    bad, ok, miss = [], 0, 0
    for i, (slug, vid) in enumerate(longs, 1):
        img, kind = _fetch(vid)
        if img is None:
            miss += 1
            continue
        hit, l, r, m = _pillarboxed(img)
        if hit:
            bad.append({"slug": slug, "vid": vid, "src": kind,
                        "left": l, "right": r, "mid": m})
            if len(bad) <= 12:
                print(f"  🔴 {vid} 左{l:>5} 右{r:>5} 中{m:>6}  {slug[:40]}")
        else:
            ok += 1
        if i % 100 == 0:
            print(f"   …已掃 {i}/{len(longs)}")

    print(f"\n結果:被黑邊夾住(直式圖) **{len(bad)}** 支 / 正常 {ok} 支 / 抓不到圖 {miss} 支")
    OUT.write_text(json.dumps({"bad": bad, "ok": ok, "miss": miss},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"名單寫入 {OUT.name}(供 fix_long_thumbs 依此重傳)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
