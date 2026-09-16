#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_captions_sync.py — 重傳已發布長片的 CC 字幕(修時間軸不同步)。

## 為什麼(2026-08-17,真實觀眾回報)
兩位觀眾在留言區反映「字幕跟解說不同步」。追查 make_video.write_srt_for_slug 發現
上傳的字幕檔有兩個疊加的錯:
  ①用 **mp4 總長度**(含片頭 3s + 片尾)分配字幕,但旁白只佔中間 → 越後面偏差越大
  ②**沒有片頭位移**,字幕 0s 起跑而語音 3s 才開始 → 全片系統性早 3 秒
而且用的是估算時間軸,沒用 TTS 已經產出的逐句真實時間戳(wordtimes)。
產生端已修;本支負責把**已經上傳的錯字幕**換掉。

## 排序:搜尋流量優先
本頻道搜尋是唯一在成長的外部來源(08-11→08-13 +42%),搜尋詞 Top20 全是股票名。
字幕不同步傷的正是這些常青片的觀看體驗 → 依 Analytics 觀看數由高到低修。

## 安全設計
- 只處理**本機有 wordtimes** 的片(否則產不出真時間軸,重傳沒意義)。
- 先 captions.list 找既有軌(50 units),有就 update、沒有就 insert。
- done 名單冪等;--max 控配額(每支約 450~500 units)。
- 預設 dry-run。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 2026-09-16:上架優先,字幕維運讓路(Carson裁決)。setdefault不蓋掉cron/手動已明講
# 的值,只補「沒人設」這個缺口——09-16 18:30發布因配額被本腳本手動執行吃光而收斂
# 成1支,根因是手動執行不帶RESERVE,繞過了quota_meter._reserve_guard的保護。
os.environ.setdefault("YT_QUOTA_RESERVE", "23650")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

OUT = ROOT / "output"
DONE = ROOT / "STUDIO" / "caption_resync_done.json"
DRIFT_FIXED = ROOT / "STUDIO" / "caption_drift_fixed.json"


def _load_env():
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _views_map():
    """{videoId: 近 30 天觀看} —— 決定先修哪些片。失敗回空(退回字母序)。"""
    try:
        import yt_analytics as ya
        from datetime import date, timedelta
        svc = ya._service()
        if svc is None:
            return {}
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=30)).isoformat()
        r = svc.reports().query(ids="channel==MINE", startDate=start, endDate=end,
                                dimensions="video", metrics="views",
                                sort="-views", maxResults=200).execute()
        return {row[0]: row[1] for row in (r.get("rows") or [])}
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=12, help="本輪最多幾支(每支約 500 units)")
    ap.add_argument("--allowlist", type=str, default=None,
                     help="限定只處理清單內的 videoId(JSON陣列或{'videoIds':[...]}物件的檔路徑);"
                          "未給則沿用原行為,對全體候選依觀看數排序處理")
    args = ap.parse_args()

    _load_env()
    import make_video as mv
    import daily_publish as dp
    import upload_youtube as up

    led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    drift_fixed = set(json.loads(DRIFT_FIXED.read_text(encoding="utf-8"))) if DRIFT_FIXED.exists() else set()
    # 2026-09-15 修:候選判斷之前只認 caption_resync_done.json 這一份,漏讀
    # caption_drift_fixed.json(另一套獨立流程的完成紀錄)→ 該檔已修好但這裡沒記到的片
    # 會被誤判成「還沒修」而重傳一次。這裡只擴大「已完成」的判定範圍,寫回仍只寫 DONE
    # 自己這份帳,不動 caption_drift_fixed.json。
    already_done = done | drift_fixed
    views = _views_map()
    cands = [(s, v) for s, v in led.items()
             if s.startswith("L_") and v not in already_done
             and (OUT / f"{s}.wordtimes.json").exists() and (OUT / f"{s}.mp4").exists()]
    # 2026-09-15 加:--allowlist 把實際執行範圍鎖在人工核准的清單內,不讓工具照觀看數
    # 從全體候選(219支等級)裡抓——只做交集,done/wordtimes/mp4 檢查照舊全套跑,
    # allowlist 只是再多一層限制,不是取代前面的判斷。
    if args.allowlist:
        _al_raw = json.loads(Path(args.allowlist).read_text(encoding="utf-8"))
        _allow = set(_al_raw.get("videoIds", []) if isinstance(_al_raw, dict) else _al_raw)
        _before = len(cands)
        cands = [(s, v) for s, v in cands if v in _allow]
        print(f"[allowlist] {args.allowlist}:{len(_allow)} 支核准清單,候選 {_before}→{len(cands)}")
    # 觀眾**親口抱怨過**的片排最前面,不受觀看數排序影響。
    # 2026-08-17 踩到:台燿 6274 就是留言說「字幕跟解說不同步」的那支,但它只有 290 觀看,
    # 按觀看排序被排到十名外——先修的是沒人抱怨的片,而抱怨的人回來看發現還是錯的。
    # 名單格式:["videoId", ...],人工維護,修好了留著也無妨(done 名單會擋掉)。
    _pri_f = ROOT / "STUDIO" / "caption_priority.json"
    try:
        _pri = set(json.loads(_pri_f.read_text(encoding="utf-8"))) if _pri_f.exists() else set()
    except Exception:  # noqa: BLE001
        _pri = set()
    cands.sort(key=lambda sv: (0 if sv[1] in _pri else 1, -views.get(sv[1], 0)))
    print(f"待修長片:{len(cands)} 支(已完成 {len(already_done)});依近 30 天觀看排序")

    yt = dp.get_service()
    n = 0
    for slug, vid in cands:
        if n >= args.max:
            print(f"[quota] 達本輪上限 {args.max},其餘下次續(冪等)")
            break
        srt = mv.write_srt_for_slug(slug)
        if not srt or not Path(srt).exists():
            # 2026-09-15 修:原本這裡會 done.add(vid) 把 SRT 產生失敗也標成「已完成」,
            # 之後這支就再也不會被重試,而它其實根本沒被寫入新字幕(靜默漏補)。
            # 不標記 done,單純跳過,下次重跑會再試一次。
            print(f"  [warn] {slug[:36]} SRT 產生失敗,跳過且不標記 done(下次重跑會重試)", file=sys.stderr)
            continue
        head = Path(srt).read_text(encoding="utf-8").split("\n")[1] if Path(srt).read_text(encoding="utf-8") else ""
        print(f"  {slug[:36]} (觀看 {views.get(vid, 0)})  首條 {head}")
        if not args.apply:
            n += 1
            continue
        try:
            lst = yt.captions().list(part="id,snippet", videoId=vid).execute()
            tracks = [it for it in lst.get("items", [])
                      if it["snippet"].get("trackKind") != "ASR"]
            from googleapiclient.http import MediaFileUpload
            media = MediaFileUpload(str(srt), mimetype="application/octet-stream")
            if tracks:
                yt.captions().update(part="id", body={"id": tracks[0]["id"]},
                                     media_body=media).execute()
                act = "更新"
            else:
                up.upload_captions(yt, vid, srt)
                act = "新增"
            done.add(vid)
            n += 1
            print(f"    ✅ 已{act}")
            time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            print(f"    [warn] {str(exc)[:110]}", file=sys.stderr)
            if "quota" in str(exc).lower():
                # 配額用盡或撞到預留額度線 → 停在這裡(冪等,下個配額日接著跑)。
                # 不 break 的話會把剩下的候選全部空轉一遍,只是印一堆同樣的警告。
                print("[quota] 停止本輪(冪等)", file=sys.stderr)
                break
    if args.apply:
        DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
        try:
            from ops import log_ops
            log_ops("字幕修復", f"重傳同步字幕 {n} 支(累計 {len(done)})")
        except Exception:  # noqa: BLE001
            pass
    print(f"{'已修' if args.apply else '將修'} {n} 支")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
