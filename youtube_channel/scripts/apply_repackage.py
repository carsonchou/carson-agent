#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_repackage.py — 一晚拉流量:把「舊片重新包裝」上線(標題+縮圖+描述誠信修正)。

已過獨立驗證(V agent):5 支標題照 staging 核准、6m1bsChDZHw 標題改用誠實版(拿掉不存在的「回測打臉」)、
6 張縮圖核准、3 支描述要清掉查無憑據的數字。

安全:
  預設 --dry:唯讀抓 6 支現況(title+完整 description)+ 確認縮圖存在,不寫任何東西。
  --apply:才真的 videos.update(part=snippet,保留 categoryId/tags,只改 title/description)
          + thumbnails.set;每支 old→new 記到 STUDIO/repackage_apply_log.json(可還原);全程讀回驗證。
認證沿用 decision_dept.yt_service(token_manage.json / youtube.force-ssl)。
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
LOG = STUDIO / "repackage_apply_log.json"
TW = timezone(timedelta(hours=8))
MAX_TITLE = 100

# ── 上線計畫(標題來自 staging，6m1bsChDZHw 用 V 的誠實修正版)──
TITLES = {
    "6m1bsChDZHw": "ETF剛回血就追高？小心這個時間點最容易套牢 #Shorts",
    "uHKyjwSAP6I": "回測跑贏大盤的AI策略，一到實盤就翻車？過度擬合的殘酷真相 #Shorts",
    "GyS_wmPncn0": "定投「停利」還是「一直抱」？同報酬率下複利終值差3倍，選錯少賺一半 #Shorts",
    "bQlB4BDc-5M": "幣價暴跌時，網格機器人到底該停還是續跑？一個數字決定 #Shorts",
    "rrALOIaZk6c": "手續費只差0.1%，10年後報酬差多少？多數人都算漏這筆 #Shorts",
    "AjYEwtF6joE": "真金白銀跑網格60天，5000 USDT最後剩多少？逐筆算給你 #Shorts",
}
ORDER = ["6m1bsChDZHw", "uHKyjwSAP6I", "GyS_wmPncn0", "bQlB4BDc-5M", "rrALOIaZk6c", "AjYEwtF6joE"]
THUMB_DIR = ROOT / "assets" / "thumbnails" / "repackage"

# 台積電縮圖修正(縮圖引擎 bug:硬套 BTC 卡→改乾淨版)。只換縮圖,不動標題/描述。
THUMBFIX = ["8OFW6A8oFNg", "NkYBmO9-Duw", "1rXKJ8JCaRc", "cd62Ywob9-M", "Oc00vHarDoo", "vjHu1vq98pg"]
THUMBFIX_DIR = ROOT / "assets" / "thumbnails" / "repackage_fix"

# 描述要清掉的「查無憑據數字」片語(dry 標出命中;--apply 後這些一律不得殘留)。
DESC_FLAGS = {
    "6m1bsChDZHw": ["X%", "2.2億", "回測顯示", "回測資料", "歷史回測"],
    "uHKyjwSAP6I": ["87%", "87 %", "60%", "60 %"],
    "rrALOIaZk6c": ["22%", "9%", "22 %", "9 %"],
}

# 描述誠信修正:精準字串替換(左=線上實際文字,右=誠實版;移除捏造/佔位符數字,保留 CTA/聯盟區塊)。
DESC_EDITS = {
    "6m1bsChDZHw": [
        ("ETF資金迴流 2.2億美元 追高後果 回測資料 網格交易 定投策略 小白避雷",
         "ETF追高後果 網格交易 定投策略 小白避雷"),
        ("ETF資金迴流，小白追高前先看回測：一個月平均虧X%。看完這支，你學會用網格或定投分批進場，避免被套。",
         "ETF剛回血，很多小白就急著追高。追在反彈高點最容易套牢——看完這支，你學會用網格或定投分批進場，避免被套。"),
        ("歷史回測顯示，情緒回暖不等於穩賺，用機器人低買高賣或定投攤平，反而安全。",
         "情緒回暖不等於穩賺，用機器人低買高賣或定投攤平分批進場，不追高才穩。"),
    ],
    "uHKyjwSAP6I": [
        ("回測87%勝率的AI策略，實盤竟虧掉60%本金？我用Python完整拆解過度擬合陷阱與樣本外測試的生存法則。",
         "回測時跑贏大盤的AI策略，一到實盤卻翻車？我用Python完整拆解過度擬合陷阱與樣本外測試的生存法則。"),
    ],
    "rrALOIaZk6c": [
        ("加了0.1%手續費，年化報酬從22%掉到9%？換手率才是真正的殺手。",
         "加了0.1%手續費，長期年化報酬會被侵蝕多少？換手率才是真正的殺手。"),
    ],
}


def edited_desc(vid: str, desc: str):
    """套用 DESC_EDITS;回 (new_desc, changed, unmatched, residual_flags)。"""
    new = desc
    unmatched = []
    for find, repl in DESC_EDITS.get(vid, []):
        if find in new:
            new = new.replace(find, repl)
        else:
            unmatched.append(find)
    residual = [f for f in DESC_FLAGS.get(vid, []) if f in new]
    return new, (new != desc), unmatched, residual


def tw_now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _svc():
    from decision_dept import yt_service
    return yt_service()


def fetch(svc, ids):
    out = {}
    for i in range(0, len(ids), 50):
        r = svc.videos().list(part="snippet,status", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            out[it["id"]] = it["snippet"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的上線(否則只 dry 檢視)")
    ap.add_argument("--titles-thumbs-only", action="store_true", help="只改標題+縮圖，先不動描述")
    args = ap.parse_args()

    svc = _svc()
    snaps = fetch(svc, ORDER)
    print(f"[apply_repackage] {'APPLY' if args.apply else 'DRY'}  抓到 {len(snaps)}/{len(ORDER)} 支\n")

    for vid in ORDER:
        sn = snaps.get(vid)
        print("=" * 70)
        if not sn:
            print(f"[{vid}] ❌ 抓不到(非本頻道或已刪)")
            continue
        old_t = sn.get("title", "")
        new_t = TITLES[vid][:MAX_TITLE]
        desc = sn.get("description", "")
        thumb = THUMB_DIR / f"{vid}.jpg"
        print(f"[{vid}]")
        print(f"  標題舊: {old_t}")
        print(f"  標題新: {new_t}")
        print(f"  縮圖:   {thumb}  存在={thumb.is_file()}")
        # 描述誠信命中
        flags = DESC_FLAGS.get(vid, [])
        hits = [f for f in flags if f in desc]
        if flags:
            print(f"  描述需清片語: {flags}  實際命中={hits}")
        print(f"  描述現況(前 400 字):\n    " + desc[:400].replace("\n", "\n    "))

    if not args.apply:
        print("\n[dry] 以上為現況;未寫任何東西。看清描述後再加 --apply 上線。")
        return 0

    # ── 上線(先只做標題+縮圖，描述另議以免盲改)──
    log = []
    if LOG.exists():
        try:
            log = json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []
    from googleapiclient.http import MediaFileUpload
    done_t = done_c = done_d = 0
    for vid in ORDER:
        sn = snaps.get(vid)
        if not sn:
            continue
        old_t = sn.get("title", "")
        new_t = TITLES[vid][:MAX_TITLE]
        old_d = sn.get("description", "")
        new_d, d_changed, unmatched, residual = edited_desc(vid, old_d)
        # 誠信安全閘:描述替換沒對上、或改完仍殘留旗標數字→放棄改描述(只改標題),別推出還帶捏造數字的版本
        if d_changed and (unmatched or residual):
            print(f"[skip 描述] {vid}: unmatched={unmatched} residual={residual}(不推可疑描述)", file=sys.stderr)
            new_d, d_changed = old_d, False
        # 標題+描述合併一次 update(保留 categoryId/tags 等)
        need = (old_t != new_t) or d_changed
        if need:
            try:
                body_sn = dict(sn)
                body_sn["title"] = new_t
                if d_changed:
                    body_sn["description"] = new_d
                svc.videos().update(part="snippet", body={"id": vid, "snippet": body_sn}).execute()
                if old_t != new_t:
                    log.append({"ts": tw_now(), "video_id": vid, "field": "title", "old": old_t, "new": new_t})
                    done_t += 1
                    print(f"[ok 標題] {vid}")
                if d_changed:
                    log.append({"ts": tw_now(), "video_id": vid, "field": "description", "old": old_d, "new": new_d})
                    done_d += 1
                    print(f"[ok 描述] {vid}(清掉捏造數字)")
            except Exception as e:
                print(f"[err update] {vid}: {str(e)[:120]}", file=sys.stderr)
        # 縮圖
        thumb = THUMB_DIR / f"{vid}.jpg"
        if thumb.is_file():
            try:
                svc.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
                log.append({"ts": tw_now(), "video_id": vid, "field": "thumbnail", "new": str(thumb)})
                done_c += 1
                print(f"[ok 縮圖] {vid}")
            except Exception as e:
                print(f"[err 縮圖] {vid}: {str(e)[:120]}", file=sys.stderr)
        time.sleep(0.5)

    # ── 台積電縮圖修正(只換縮圖)──
    done_fix = 0
    for vid in THUMBFIX:
        f = THUMBFIX_DIR / f"{vid}.jpg"
        if not f.is_file():
            print(f"[skip 縮圖修正] {vid}: 找不到 {f}", file=sys.stderr)
            continue
        try:
            svc.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(f))).execute()
            log.append({"ts": tw_now(), "video_id": vid, "field": "thumbnail_fix", "new": str(f)})
            done_fix += 1
            print(f"[ok 縮圖修正] {vid}(拿掉誤套的 BTC 卡)")
        except Exception as e:
            print(f"[err 縮圖修正] {vid}: {str(e)[:120]}", file=sys.stderr)
        time.sleep(0.5)

    STUDIO.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[apply] 標題 {done_t} 支、描述 {done_d} 支、縮圖 {done_c} 支、台積電縮圖修正 {done_fix} 支已上線。log→{LOG.name}")

    # 讀回驗證:標題正確 + 描述不再殘留任何旗標數字
    time.sleep(2)
    back = fetch(svc, ORDER)
    print("\n[讀回驗證]")
    for vid in ORDER:
        sn2 = back.get(vid, {})
        cur = sn2.get("title", "?")
        ok = cur == TITLES[vid][:MAX_TITLE]
        resid = [f for f in DESC_FLAGS.get(vid, []) if f in sn2.get("description", "")]
        rtxt = f"  描述殘留旗標={resid}" if resid else ""
        print(f"  {vid}: {'✅' if ok and not resid else '⚠️'} {cur}{rtxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
