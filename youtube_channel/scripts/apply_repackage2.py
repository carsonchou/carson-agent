#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_repackage2.py — 舊片重新包裝【第二批 10 支】上線(標題+描述誠信修正+縮圖)。

已過獨立驗證 V2:9 支標題照 batch2 核准、6ZKYektBd_Q 拿掉無實據的「回測」、6 支描述清捏造數字。
標題/縮圖讀自 STUDIO/_repackage_batch2.json;描述 find→replace 為 V2 給的精準字串。

安全同批1:--dry 唯讀檢視;--apply 才寫。描述替換沒對上或改完仍殘留旗標數字→放棄改描述(只改標題),
不推可疑版本。每支 old→new 記 STUDIO/repackage_apply_log.json(可還原);全程讀回驗證。
6ZKYektBd_Q 縮圖底條含「回測揭穿」需重製,故本腳本預設跳過它的縮圖(SKIP_THUMB),標題/描述照上。
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
BATCH = STUDIO / "_repackage_batch2.json"
LOG = STUDIO / "repackage_apply_log.json"
TW = timezone(timedelta(hours=8))
MAX_TITLE = 100

# V2 修正:6ZKYektBd_Q 標題拿掉無實據的「回測」
TITLE_OVERRIDE = {
    "6ZKYektBd_Q": "你的定投「停利點」可能設錯了——破解停利迷思 #Shorts",
}
# 6ZKY 縮圖已用乾淨新標題重製(無「回測」),不再跳過
SKIP_THUMB = set()

# 描述要清的查無憑據「數字」(改完不得殘留)。只認具體捏造數字,不認「回測/夏普」這類正常詞
# (它們在 hashtag/CTA/誠實語境也會出現,誤當旗標會反而擋掉清理)。
DESC_FLAGS = {
    "soRZ3WicqWQ": ["150%", "500 組", "500組"],
    "6ZKYektBd_Q": ["終值差60%", "終值差 60%", "回測10年", "回測 10 年"],
    "ZODoMHEeYJk": ["0.63", "1.18"],
    "_YuaVFxaSvA": ["終值差60%", "10年終值差60"],
    "n1cTFJgO0BE": ["3 年回測", "3年回測"],
    "KT9OnT7Bud0": ["76%", "68%"],
    "bOGKN0eo15Y": ["年化30%", "回撤50%"],
}
# V2 精準 find→replace(左=線上實際整句,右=誠實版;保留 CTA/聯盟區塊)
DESC_EDITS = {
    "soRZ3WicqWQ": [
        ("網格間距 0.1% vs 0.5% vs 1.5%，回測勝率差 150%。我用真實 500 組參數測試拆穿間距陷阱，教你算出自己幣種的甜蜜點。",
         "網格間距 0.1% vs 0.5% vs 1.5%，差一點點，績效可能差很多。我拆穿間距陷阱，教你算出自己幣種的甜蜜點。")
    ],
    "6ZKYektBd_Q": [
        ("定投停利點設錯代價多大？真實回測10年數據，停利點差1%終值差60%。教你用歷史數據找到屬於自己的甜蜜點，避免高點被套、低點割肉。",
         "定投停利點設錯，代價可能不小。停利點怎麼設，長期下來差很多。教你思考屬於自己的停利邏輯，避免高點被套、低點割肉。")
    ],
    "ZODoMHEeYJk": [
        ("定投夏普0.63 vs 網格夏普1.18，差異在趨勢vs盤整的策略失效條件。",
         "兩者的差異，在於趨勢vs盤整下各自的策略失效條件。")
    ],
    "_YuaVFxaSvA": [
        ("定投停利點差1個百分比，10年終值差60%？用真實回測數據拆穿停利迷思。告訴你停利點應該怎麼設。",
         "定投到底要不要設停利點？其實「不停利」也可能是更好的答案。這支帶你想清楚停利的邏輯。")
    ],
    "n1cTFJgO0BE": [
        ("本影片用 3 年回測數據揭露格距設定如何直接影響報酬，以及為什麼 ATR 動態調整才能適應市場波動。",
         "本影片帶你看格距設定如何直接影響報酬，以及為什麼 ATR 動態調整才能適應市場波動。")
    ],
    "KT9OnT7Bud0": [
        ("同本金 1 萬元實測 45 天。AI 勝率 76% vs 人工 68%，但極端行情下兩者皆可虧損。",
         "同本金 1 萬元實測 45 天。結果可能出乎你的意料，且極端行情下兩者皆可虧損。")
    ],
    "bOGKN0eo15Y": [
        ("年化30%但回撤50%，你真的抱得住？卡瑪比率教你用一組數字判斷策略健康度。",
         "報酬很漂亮，但回撤很深，你真的抱得住？卡瑪比率教你用一組數字判斷策略健康度。")
    ],
}


def tw_now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _svc():
    from decision_dept import yt_service
    return yt_service()


def load_plan():
    d = json.loads(BATCH.read_text(encoding="utf-8"))
    items = d["items"] if isinstance(d, dict) and "items" in d else d
    plan = []
    for it in items:
        vid = it["video_id"]
        plan.append({
            "vid": vid,
            "new_title": TITLE_OVERRIDE.get(vid, it["new_title"])[:MAX_TITLE],
            "thumb": ROOT / it["thumbnail_path"],
        })
    return plan


def edited_desc(vid, desc):
    new = desc
    unmatched = []
    for find, repl in DESC_EDITS.get(vid, []):
        if find in new:
            new = new.replace(find, repl)
        else:
            unmatched.append(find)
    residual = [f for f in DESC_FLAGS.get(vid, []) if f in new]
    return new, (new != desc), unmatched, residual


def fetch(svc, ids):
    out = {}
    for i in range(0, len(ids), 50):
        r = svc.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            out[it["id"]] = it["snippet"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    plan = load_plan()
    ids = [p["vid"] for p in plan]
    svc = _svc()
    snaps = fetch(svc, ids)
    print(f"[apply_repackage2] {'APPLY' if args.apply else 'DRY'}  {len(snaps)}/{len(ids)} 支\n")

    for p in plan:
        vid = p["vid"]; sn = snaps.get(vid)
        print("=" * 66)
        if not sn:
            print(f"[{vid}] ❌ 抓不到"); continue
        nd, dch, unm, resid = edited_desc(vid, sn.get("description", ""))
        print(f"[{vid}]")
        print(f"  標題舊: {sn.get('title','')}")
        print(f"  標題新: {p['new_title']}")
        print(f"  縮圖:   存在={p['thumb'].is_file()}  {'(跳過-需重製)' if vid in SKIP_THUMB else ''}")
        if vid in DESC_EDITS:
            print(f"  描述: 會改={dch}  沒對上={unm}  改後殘留旗標={resid}")

    if not args.apply:
        print("\n[dry] 未寫任何東西。加 --apply 上線。")
        return 0

    log = []
    if LOG.exists():
        try:
            log = json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []
    from googleapiclient.http import MediaFileUpload
    dt = dd = dc = 0
    for p in plan:
        vid = p["vid"]; sn = snaps.get(vid)
        if not sn:
            continue
        old_t = sn.get("title", ""); new_t = p["new_title"]
        old_d = sn.get("description", "")
        new_d, dch, unm, resid = edited_desc(vid, old_d)
        if dch and (unm or resid):
            print(f"[skip 描述] {vid}: 沒對上={unm} 殘留={resid}", file=sys.stderr)
            new_d, dch = old_d, False
        if (old_t != new_t) or dch:
            try:
                body = dict(sn); body["title"] = new_t
                if dch:
                    body["description"] = new_d
                svc.videos().update(part="snippet", body={"id": vid, "snippet": body}).execute()
                if old_t != new_t:
                    log.append({"ts": tw_now(), "video_id": vid, "field": "title", "old": old_t, "new": new_t}); dt += 1
                    print(f"[ok 標題] {vid}")
                if dch:
                    log.append({"ts": tw_now(), "video_id": vid, "field": "description", "old": old_d, "new": new_d}); dd += 1
                    print(f"[ok 描述] {vid}")
            except Exception as e:
                print(f"[err update] {vid}: {str(e)[:120]}", file=sys.stderr)
        if vid not in SKIP_THUMB and p["thumb"].is_file():
            try:
                svc.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(p["thumb"]))).execute()
                log.append({"ts": tw_now(), "video_id": vid, "field": "thumbnail", "new": str(p["thumb"])}); dc += 1
                print(f"[ok 縮圖] {vid}")
            except Exception as e:
                print(f"[err 縮圖] {vid}: {str(e)[:120]}", file=sys.stderr)
        time.sleep(0.5)

    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[apply] 標題 {dt}、描述 {dd}、縮圖 {dc} 已上線。log→{LOG.name}")
    time.sleep(2)
    back = fetch(svc, ids)
    print("\n[讀回驗證]")
    for p in plan:
        vid = p["vid"]; sn2 = back.get(vid, {})
        cur = sn2.get("title", "?"); ok = cur == p["new_title"]
        resid = [f for f in DESC_FLAGS.get(vid, []) if f in sn2.get("description", "")]
        print(f"  {vid}: {'✅' if ok and not resid else '⚠️'} {cur[:44]}{('  殘留'+str(resid)) if resid else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
