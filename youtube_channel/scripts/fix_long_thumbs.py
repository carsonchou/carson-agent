#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_long_thumbs.py — 把「已發布長片」的直式縮圖換成正確的 16:9。

## 為什麼(2026-07-28 稽核發現)
`make_cover.py:50` 寫死 `W, H = 1080, 1920`(直式 9:16)且沒有長短片分支,而 daily_publish
優先呼叫它 → **所有長片都拿到直式縮圖**。YouTube 長片縮圖規格是 16:9,傳直式會被補黑邊塞進
16:9 框、實際內容只佔中間一小條,在搜尋結果與首頁列表幾乎看不清 = **點擊率被結構性壓死**。
實測:已發布長片 42 支是直式、只有 8 支橫式。
產製端已修(commit 932c668:依格式選產生器 + 比例檢查),但**那只影響之後產的片**;
已經在線上的 42 支要靠這支補。

## 為什麼值得補(不是所有舊片都值得動)
一般片約 4 天就停止成長(memory yt-video-lifespan-4days),改舊片多半沒用。
**但個股體檢不同**:它靠個股名/代號的長尾搜尋持續拿曝光(近28天搜尋詞 top20 幾乎全是個股名),
是**常青片**——縮圖改好,之後每一次搜尋曝光的點擊率都受益。故預設優先修個股體檢。

## 安全設計
- `thumbnails.set` 只換圖,**保留 videoId / 觀看數 / 排名**(純贏,不是重新上傳)
- 每支 50 units;預設 `--max 10`(500 units)避免撞爆每日配額(最壞日已用到 99.4%)
- 原檔一律先備份到 assets/thumbnails/_portrait_backup/
- 預設 dry-run,要 `--apply` 才真的動

用法:
  python scripts/fix_long_thumbs.py                 # 只列出會改哪些(不動任何東西)
  python scripts/fix_long_thumbs.py --apply --max 10
  python scripts/fix_long_thumbs.py --apply --all    # 不限個股體檢,所有直式長片
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
THUMBS = ROOT / "assets" / "thumbnails"
BACKUP = THUMBS / "_portrait_backup"
LEDGER = STUDIO / "uploaded_ledger.json"


def _published() -> dict:
    """slug → videoId(只認 11 碼 YouTube id)。"""
    out: dict = {}
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[fatal] 讀不到 ledger:{e}", file=sys.stderr)
        return out

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and len(v) == 11:
                    out[k] = v
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def _targets(only_checkup: bool) -> list:
    """回 [(slug, videoId, (w,h))],只挑『已發布長片 且 縮圖是直式』。"""
    from PIL import Image
    pub = _published()
    out = []
    for slug, vid in pub.items():
        if not slug.startswith("L_"):
            continue
        p = THUMBS / f"{slug}.jpg"
        if not p.exists():
            continue
        try:
            w, h = Image.open(p).size
        except Exception:  # noqa: BLE001
            continue
        if w > h:
            continue                      # 已是橫式,不動
        if only_checkup and "體檢" not in slug:
            continue
        out.append((slug, vid, (w, h)))
    # 個股體檢優先(常青搜尋片,改縮圖持續受益)
    out.sort(key=lambda x: (0 if "體檢" in x[0] else 1, x[0]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="把已發布長片的直式縮圖換成 16:9")
    ap.add_argument("--apply", action="store_true", help="真的重產並上傳(預設只列出)")
    ap.add_argument("--max", type=int, default=10, dest="mx",
                    help="本次最多處理幾支(每支 50 quota units;預設 10)")
    ap.add_argument("--all", action="store_true",
                    help="不限個股體檢,處理所有直式長片(預設只做常青的個股體檢)")
    args = ap.parse_args()

    tg = _targets(only_checkup=not args.all)
    print(f"待修正的已發布長片(直式縮圖):{len(tg)} 支"
          f"{'(僅個股體檢)' if not args.all else '(全部)'}")
    for slug, vid, (w, h) in tg[:args.mx]:
        print(f"   {w}x{h}  {vid}  {slug[:46]}")
    if len(tg) > args.mx:
        print(f"   ... 另 {len(tg) - args.mx} 支(本次 --max {args.mx} 不做)")
    if not args.apply:
        print(f"\n[dry-run] 未改動任何東西。要真的執行:--apply --max {args.mx}"
              f"(耗 {min(len(tg), args.mx) * 50} quota units)")
        return 0

    BACKUP.mkdir(parents=True, exist_ok=True)
    import make_thumbnails as mt
    from googleapiclient.http import MediaFileUpload
    # 直接重用 daily_publish.get_service():它讀 token_manage.json + client_secrets.json,
    # 與產線上架走的是**同一組憑證與 scope**(自己另外呼叫 upload_youtube.get_authenticated_service
    # 要傳 client_secrets/token_path 兩個 keyword,容易傳錯成另一組 token)。
    import daily_publish as dp
    yt = dp.get_service()

    qs = {}
    try:
        _q = json.loads((STUDIO / "quality_scores.json").read_text(encoding="utf-8"))
        for it in (_q.get("published") or []):
            if isinstance(it, dict) and it.get("slug"):
                qs[it["slug"]] = it.get("title") or it["slug"]
    except Exception:  # noqa: BLE001
        pass

    ok = fail = 0
    for slug, vid, (w, h) in tg[:args.mx]:
        p = THUMBS / f"{slug}.jpg"
        try:
            shutil.copy2(p, BACKUP / f"{slug}.jpg")     # 先備份原直式圖
            p.unlink()                                   # make_auto 遇既有檔會 skip
            mt.make_auto(slug, qs.get(slug, slug))
            from PIL import Image
            nw, nh = Image.open(p).size
            if nw <= nh:
                raise RuntimeError(f"重產後仍非橫式({nw}x{nh})")
            yt.thumbnails().set(videoId=vid,
                                media_body=MediaFileUpload(str(p), mimetype="image/jpeg")).execute()
            ok += 1
            print(f"[ok] {w}x{h} → {nw}x{nh}  {vid}  {slug[:44]}")
        except Exception as e:  # noqa: BLE001
            fail += 1
            # 🔴 2026-07-28 修回滾 bug(紅線驗證抓到):舊條件多了 `and not p.exists()`,
            # 導致兩條主要失敗路徑**都走不到回滾**——(a) 重產出仍是直式(主動 raise)時 p 已存在;
            # (b) 上傳失敗(403/網路/配額)時 p 也已存在。後果比「沒回滾」更陰:本機檔案已變橫式
            # 而 YouTube 上還是直式 → 下次再跑,`_targets()` 的 `if w > h: continue` 會把它濾掉
            # → **這支片永久從待修清單消失、線上永遠留著直式縮圖,而且沒有任何錯誤留存**。
            # 配額中途用罄時會整批這樣靜默漏掉。改成:失敗一律用備份覆蓋回去(不管 p 在不在)。
            bk = BACKUP / f"{slug}.jpg"
            if bk.exists():
                try:
                    shutil.copy2(bk, p)                  # 失敗一律回滾原圖,保證下次還撿得到
                except Exception as e2:  # noqa: BLE001
                    print(f"[warn] 回滾失敗 {slug[:36]}:{str(e2)[:60]};原圖仍在 {bk}", file=sys.stderr)
            print(f"[fail] {slug[:44]}:{str(e)[:90]}", file=sys.stderr)
    print(f"\n完成:成功 {ok} / 失敗 {fail};耗約 {ok * 50} quota units。原圖備份在 {BACKUP}")
    if ok:
        try:
            from ops import log_ops
            log_ops("縮圖修正", f"已發布長片直式→16:9 共 {ok} 支(thumbnails.set,保留觀看數)")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
