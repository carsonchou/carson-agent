#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""desc_chapters_backfill.py — 已發布長片描述回填:章節時間戳+清除格式殘留。

## 為什麼(2026-08-12 成長包裝)
個股體檢長片是常青搜尋資產(靠個股名長尾搜尋持續曝光),但線上描述:
①零章節——YouTube 把章節切成 key moments 進 Google 索引(可深連到某一章),
  對搜尋型頻道是免費的複利曝光面;
②殘留「**Hashtags：**」markdown 原字面 + 長片誤標 #Shorts。
產製端已修(upload_youtube.assemble_metadata),本支補線上存量。

## 安全設計
- **只動 description(附加/清殘),不動標題/不重生內容**:先 GET 完整 snippet,
  只改 description 欄位後整包 update(未帶欄位不清空的 videos.update 標準手法)。
- 已含「0:00」的片跳過(冪等,不重覆附加)。
- 預設 dry-run 只印 diff;--apply 才真的動。每支 50 quota units,--max 預設 20。
- 章節產生重用 upload_youtube.build_chapters_block(產線同一份,不重刻)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"

import upload_youtube as up  # noqa: E402

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):
        pass


def transform(desc: str, slug: str) -> str:
    """線上描述 → 新描述。冪等:重跑第二次不再變。"""
    d = desc or ""
    d = d.replace("**Hashtags：**", "").replace("**Hashtags:**", "")
    d = re.sub(r"#[Ss]horts\s*", "", d)
    if "0:00" not in d:
        blk = up.build_chapters_block(slug, OUT / f"{slug}.md")
        if blk:
            d = d.rstrip() + "\n\n" + blk
    return d[:4990]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的更新(預設 dry-run)")
    ap.add_argument("--max", type=int, default=20, help="本輪最多更新支數(每支 50 units)")
    args = ap.parse_args()

    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    longs = [(s, v) for s, v in led.items()
             if s.startswith("L_") and (OUT / f"{s}.md").exists()
             and (OUT / f"{s}.wordtimes.json").exists()]
    print(f"候選:{len(longs)} 支已發布長片(本地有 md+wordtimes)")

    import daily_publish as dp
    yt = dp.get_service()
    done_mark = STUDIO / "desc_chapters_done.json"
    done = set(json.loads(done_mark.read_text(encoding="utf-8"))) if done_mark.exists() else set()

    changed = 0
    for slug, vid in longs:
        if changed >= args.max:
            print(f"[quota] 已達本輪上限 {args.max},其餘下次續(冪等)")
            break
        if vid in done:
            continue
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            items = r.get("items", [])
            if not items:
                done.add(vid)
                continue
            sn = items[0]["snippet"]
            new_desc = transform(sn.get("description", ""), slug)
            if new_desc == sn.get("description", ""):
                done.add(vid)
                continue
            if not args.apply:
                has_ch = "0:00" in new_desc and "0:00" not in (sn.get("description") or "")
                print(f"[dry] {slug[:40]} → {'+章節' if has_ch else ''}"
                      f"{' 清殘留' if '**Hashtags' in (sn.get('description') or '') or '#Shorts' in (sn.get('description') or '') else ''}")
                changed += 1
                continue
            sn["description"] = new_desc
            yt.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            done.add(vid)
            changed += 1
            print(f"[ok] {slug[:44]} 已更新")
            time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {slug[:36]}:{str(exc)[:100]}", file=sys.stderr)
    if args.apply:
        done_mark.write_text(json.dumps(sorted(done)), encoding="utf-8")
        log_ops("包裝回填", f"描述章節回填 {changed} 支(累計完成 {len(done)})")
    print(f"{'更新' if args.apply else '將更新'} {changed} 支")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
