#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_search_thumbs.py — 用現行產生器重做「個股體檢」已發布片的縮圖並重傳。

## 為什麼(2026-08-23 診斷)
近 28 天流量拆解:YT_SEARCH 佔 21.5% 觀看但 **40% 的觀看時數**,而搜尋詞
**全部是赤裸的股票名**(金像電/藥華藥/康舒/光聖/世芯ky/聯茂…)。也就是說個股體檢不是
「內容片」,是**台股個股的搜尋佔位**——搜尋結果裡那張縮圖就是點擊決策點,而且是**常青**的
(不像一般片 4 天就死,它靠個股名長尾持續拿曝光)。

實際抓線上縮圖來看,抓到活的缺陷:
  藥華藥(近28天時數第 4 名)→ 主標印「**【藥華藥**」,括號開了沒關;
                              第二行「但暴跌76.2%你敢」,句子斷在半路。
  台半 / 金像電(08-17 之後產的)→「270%獲利!」「台半5425」,完整漂亮。
差別在 `make_thumbnails._force_stock_identity` 的排版清理是 **2026-08-17** 才上的,
之前產的縮圖還原封不動掛在線上。已發布體檢長片 82 支,其中大多數在那之前。

## 為什麼重傳是純賺
`thumbnails.set` **只換圖**,保留 videoId / 觀看數 / 搜尋排名(memory yt-video-lifespan-4days)
——不是重新上傳,沒有任何既有成績會被歸零。

## 安全
- 重產後**先自檢**:兩行主標必須(a)不含殘缺括號 (b)看得出是哪一檔(股名或代號在圖上)。
  不過就跳過該支,不上傳(寧可留舊圖,也不要換上一張更糟的)。
- 舊圖先備份到 assets/thumbnails/_pre_refresh/。
- 50 units/支,預設 --max 30(1,500 units),排每日 cron 慢慢換完;冪等(換過的記檔)。

用法:
  python scripts/refresh_search_thumbs.py                  # dry-run,列出會換哪些+自檢結果
  python scripts/refresh_search_thumbs.py --apply --max 30
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
THUMBS = ROOT / "assets" / "thumbnails"
BACKUP = THUMBS / "_pre_refresh"
DONE = STUDIO / "search_thumb_refresh_done.json"


def _title_of(slug):
    """標題以本機 .md 第一行為準(零配額)。格式是 `# 🎬 <標題>`——前綴要剝乾淨,
    不然餵給排版邏輯的就是「🎬」,產出的預覽會騙人(實測踩過)。"""
    import re as _re
    p = ROOT / "output" / f"{slug}.md"
    if not p.exists():
        return None
    try:
        first = p.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except Exception:  # noqa: BLE001
        return None
    return _re.sub(r"^#\s*🎬?\s*", "", first).strip() or None


def _selfcheck(slug, title):
    """回 (ok, 原因, l1, l2)。用產生器本尊算出會印的兩行,再驗它乾不乾淨。"""
    import make_thumbnails as mt
    import re as _re
    cfg = mt._force_stock_identity(dict(mt._heuristic(slug, title)), slug, title)
    l1 = str(cfg.get("l1") or "")
    l2 = str(cfg.get("l2") or "")
    both = l1 + l2
    if any(c in both for c in "【】") or l1.endswith(("(", "（", "[", "「")):
        return False, "殘缺括號", l1, l2
    if "個股體檢" in both:
        return False, "主標被系列前綴佔掉(那不是這支片的識別)", l1, l2
    m = _re.search(r"個股體檢([一-鿿]{2,6}?)(\d{4})", slug)
    if m:
        name, code = m.group(1), m.group(2)
        if name not in both and code not in both:
            return False, "圖上看不出是哪一檔(搜尋來的人認不出)", l1, l2
    return True, "", l1, l2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=30, dest="mx")
    args = ap.parse_args()

    import daily_publish as dp
    import make_thumbnails as mt

    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    titles = {}
    try:
        titles = {s: (STUDIO / "slug_titles.json") and {} for s in []}
    except Exception:  # noqa: BLE001
        pass

    cands = [(s, v) for s, v in led.items()
             if isinstance(v, str) and len(v) == 11 and s.startswith("L_")
             and "個股體檢" in s and v not in done]
    print(f"已發布個股體檢長片 {sum(1 for s,v in led.items() if isinstance(v,str) and s.startswith('L_') and '個股體檢' in s)} 支;"
          f"尚未換過縮圖 {len(cands)} 支\n")
    if not cands:
        print("都換過了(冪等)。")
        return 0

    yt = dp.get_service() if args.apply else None
    n = skip = err = 0
    for slug, vid in cands[:args.mx if args.mx else len(cands)]:
        # 標題以線上為準(本機 .md 可能與線上不同步);dry-run 時用 slug 當替身即可
        # 標題優先讀本機 .md(零配額且與線上一致);沒有才退回 API。
        # ⚠️ 不可拿 slug 當標題替身——slug 會把 % 洗掉,dry-run 會產出跟實際不同的預覽。
        title = _title_of(slug)
        if not title:
            if not args.apply:
                print(f"[skip] {vid} 本機無標題檔,dry-run 無法預覽 {slug[:30]}")
                skip += 1
                continue
            try:
                title = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"]["title"]
            except Exception as exc:  # noqa: BLE001
                print(f"[err] {vid} 取標題失敗:{str(exc)[:80]}")
                err += 1
                if "quota" in str(exc).lower():
                    break
                continue
        ok, why, l1, l2 = _selfcheck(slug, title)
        if not ok:
            print(f"[skip] {vid} 自檢不過({why}) l1={l1!r} l2={l2!r}")
            skip += 1
            continue
        if not args.apply:
            print(f"[dry] {vid} l1={l1!r} l2={l2!r}  {slug[:34]}")
            n += 1
            continue
        p = THUMBS / f"{slug}.jpg"
        try:
            if p.exists():
                BACKUP.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, BACKUP / f"{slug}.jpg")
            mt.make_auto(slug, title, force=True)          # 用現行邏輯重產
            if not p.exists():
                print(f"[skip] {vid} 重產後找不到圖檔")
                skip += 1
                continue
            from googleapiclient.http import MediaFileUpload
            yt.thumbnails().set(videoId=vid,
                                media_body=MediaFileUpload(str(p), mimetype="image/jpeg")).execute()
            done.add(vid)
            DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
            n += 1
            print(f"✅ {vid} 已換 l1={l1!r} l2={l2!r}  {slug[:30]}")
        except Exception as exc:  # noqa: BLE001
            err += 1
            print(f"[err] {vid} {str(exc)[:110]}")
            if "quota" in str(exc).lower():
                print("配額用盡,停止(冪等,下次接著換)")
                break
    print(f"\n換好 {n} / 自檢跳過 {skip} / 失敗 {err};還剩 {len(cands)-n} 支")
    if args.apply and n:
        try:
            from ops import log_ops
            log_ops("搜尋縮圖翻新", f"重做 {n} 支體檢片縮圖(股名代號上圖,還剩 {len(cands)-n})")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
