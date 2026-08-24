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


def strip_chapters(d: str):
    """移除既有章節區塊,回 (剩餘描述, 是否有移除)。只吃『連續的時間戳行』+緊鄰的標題行,
    其他內容一字不動——描述裡的正文若剛好某行以數字開頭也不會被誤傷(要求 m:ss 格式)。"""
    lines = (d or "").splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^0:00\s", ln)), None)
    if start is None:
        return d, False
    end = start
    while end + 1 < len(lines) and re.match(r"^\d+:\d{2}(?::\d{2})?\s", lines[end + 1]):
        end += 1
    s2 = start
    if s2 > 0 and re.match(r"^[📖⏱]\s*章節\s*$", lines[s2 - 1].strip()):
        s2 -= 1
    rest = lines[:s2] + lines[end + 1:]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(rest)).strip(), True


def transform(desc: str, slug: str, fix_existing: bool = False) -> str:
    """線上描述 → 新描述。冪等:重跑第二次不再變。

    ## fix_existing(2026-08-17)
    2026-08-12 那批回填用的舊 build_chapters_block 有兩個錯,實測 90 支已補的片裡
    **63 支章節時間是錯的,最大偏 -64 秒**,而且集中在流量最高的片(台半 1934 觀看、
    聯鈞 956、00878 785…,合計近 30 天 9,260 次觀看)。兩個根因:
      ①漏加片頭 INTRO_DURATION(全體早 3 秒,這個無感)
      ②旁白對不到句子時**用等分估算編出時間點**(這個要命,觀眾點章節跳錯一分鐘)
    產生端已換成 chapters.build(對不齊就整組不出)。開 fix_existing 會先移除線上舊章節
    再貼新的;新版產不出章節時**保留舊的不動**——寧可留一組偏 3 秒的,也不要把章節拔光。
    """
    d = desc or ""
    d = d.replace("**Hashtags：**", "").replace("**Hashtags:**", "")
    d = re.sub(r"#[Ss]horts\s*", "", d)
    if fix_existing and "0:00" in d:
        blk_new = up.build_chapters_block(slug, OUT / f"{slug}.md")
        if blk_new:
            body, removed = strip_chapters(d)
            if removed:
                d = body.rstrip() + "\n\n" + blk_new
    elif "0:00" not in d:
        blk = up.build_chapters_block(slug, OUT / f"{slug}.md")
        if blk:
            d = d.rstrip() + "\n\n" + blk
    return d[:4990]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的更新(預設 dry-run)")
    ap.add_argument("--max", type=int, default=20, help="本輪最多更新支數(每支 50 units)")
    ap.add_argument("--fix-existing", action="store_true",
                    help="取代線上既有章節(修 2026-08-12 那批的錯時間戳)")
    args = ap.parse_args()

    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    longs = [(s, v) for s, v in led.items()
             if s.startswith("L_") and (OUT / f"{s}.md").exists()
             and (OUT / f"{s}.wordtimes.json").exists()]
    # 依近 30 天觀看排序:錯章節傷的是**正在被看**的片,先修有人看的那些。
    try:
        import yt_analytics as ya
        from datetime import date, timedelta
        svc = ya._service()
        vmap = {}
        if svc is not None:
            rr = svc.reports().query(
                ids="channel==MINE", startDate=(date.today() - timedelta(days=30)).isoformat(),
                endDate=date.today().isoformat(), dimensions="video", metrics="views",
                sort="-views", maxResults=200).execute()
            vmap = {r0[0]: r0[1] for r0 in (rr.get("rows") or [])}
        longs.sort(key=lambda sv: -vmap.get(sv[1], 0))
    except Exception:  # noqa: BLE001
        vmap = {}
    print(f"候選:{len(longs)} 支已發布長片(本地有 md+wordtimes)"
          f"{';依近 30 天觀看排序' if vmap else ''}")

    import daily_publish as dp
    yt = dp.get_service()
    # fix 模式用**獨立**的 done 名單:舊名單那 90 支正是要修的對象,共用會全被跳過。
    done_mark = STUDIO / ("desc_chapters_fixed.json" if args.fix_existing
                          else "desc_chapters_done.json")
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
            new_desc = transform(sn.get("description", ""), slug, fix_existing=args.fix_existing)
            if new_desc == sn.get("description", ""):
                done.add(vid)
                continue
            if not args.apply:
                old_ch = re.findall(r"^(\d+:\d{2}(?::\d{2})?)\s", sn.get("description") or "", re.M)
                new_ch = re.findall(r"^(\d+:\d{2}(?::\d{2})?)\s", new_desc, re.M)
                print(f"[dry] 觀看{vmap.get(vid, 0):>5}  {slug[:38]}  "
                      f"章節 {len(old_ch)}→{len(new_ch)}  {old_ch[:3]} → {new_ch[:3]}")
                changed += 1
                continue
            # 動的是**已經對外**的內容:先把原 snippet 原封存檔,任何時候可還原。
            # (2026-08-12 那批沒存,所以這次要修時只能靠重算比對,無法直接回滾。)
            bk = STUDIO / "desc_backup"
            bk.mkdir(exist_ok=True)
            (bk / f"{vid}.json").write_text(
                json.dumps(items[0]["snippet"], ensure_ascii=False, indent=1), encoding="utf-8")
            sn["description"] = new_desc
            yt.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            done.add(vid)
            changed += 1
            print(f"[ok] {slug[:44]} 已更新")
            time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {slug[:36]}:{str(exc)[:100]}", file=sys.stderr)
            if "quota" in str(exc).lower():
                print("[quota] 停止本輪(冪等)", file=sys.stderr)
                break
    if args.apply:
        done_mark.write_text(json.dumps(sorted(done)), encoding="utf-8")
        log_ops("包裝回填", f"描述章節回填 {changed} 支(累計完成 {len(done)})")
    print(f"{'更新' if args.apply else '將更新'} {changed} 支")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
