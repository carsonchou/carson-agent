#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zombie_sweep.py — 殭屍片(0 觀看舊片)清理引擎。

背景（為什麼要有這支）
----------------------
頻道已發布 628 支片，STUDIO/quality_scores.json 顯示其中 443 支(70%)在近 180 天
Analytics 視窗裡完全 0 觀看（yt_analytics.video_stats() 用 dimensions=video 查
YouTube Analytics，0 觀看的影片根本不會出現在回傳的 rows 裡 → views 欄位留 None，
語意上等於「近 180 天真的 0 觀看」，見 scripts/quality_score.py:340-354 與
scripts/yt_analytics.py:110-144）。對 YouTube 演算法，這是「這頻道很多內容沒人
看」的持續負訊號，會拖累新片的推薦。Carson 已授權野心模式全力運轉，操作可逆
（private 隨時能轉回 public），且同性質操作（斷尾片/編造片下架）已有兩次授權
先例（見 STUDIO/_private_batch_ids.json 相關腳本）。

做法（保守，別誤殺）
--------------------
1. 挑選標準：0 觀看 **且** 發布超過 14 天（給新片機會）。
2. 排除：
   - 台股真相實驗室系列（沿用 playlist_engine._match_truth_lab）
   - EP 系列（沿用 playlist_engine._match_ep_live）
   - STUDIO/zombie_sweep_keeplist.json 裡列的優先清單（Carson 手動維護的保護清單，
     slug 或 videoId 命中都算，永遠不動）
   - 已處理過的（STUDIO/zombie_sweep_state.json 的 done，冪等）
   - 發布日期拿不到的（fail-safe：不確定就不動）
3. 雙保險：
   ① dry-run 預設（不加 --apply 一律不寫入），--apply 才真的動
   ② 每支動之前 videos.list 再確認一次 viewCount==0（快取可能舊；有觀看就跳過並記錄）
   ③ 每支動作即時落地 state（誰、何時、原因），可逆清單留檔

quota 紀律（今日 quota 已爆的教訓：videos.list 讀取也會 403，見 logs/job_stderr.log）
------------------------------------------------------------------------------
- dry-run 完全不連網、不需要 token（只讀本機 quality_scores.json / state /
  keeplist / 已快取的 pubdate cache），與 desc_backfill.py 同慣例，今天 quota
  全滿時也能安全跑。
- --apply 才連網：先用 videos.list(part=snippet,statistics) 批次（50 支/次＝
  1 quota）幫候選池補「發布日期」快取（STUDIO/zombie_sweep_pubdate_cache.json，
  日期不會變，永久快取，跑過一次以後全頻道都不用再查）＋順便拿當下最新
  viewCount 做二次確認。videos.update（真正設 private）＝50 quota/支，--max
  預設 150（≈7500 quota，留餘量給 daily_publish/playlist_engine 等其他 job）。
- 遇 403 quotaExceeded 一律優雅停止（不管在補快取階段還是在寫入階段），已完成
  的部分照常落地 state，下次接續跑，絕不重複計費也絕不半途污染狀態。

用法
----
    python scripts/zombie_sweep.py                # dry-run（預設，不連網）
    python scripts/zombie_sweep.py --apply         # 正式跑，本輪最多處理 150 支
    python scripts/zombie_sweep.py --apply --max 50
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from studio_common import save_json_atomic, load_json_safe  # noqa: E402
import playlist_engine as ple  # noqa: E402

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):
        pass

STUDIO = ROOT / "STUDIO"
QSCORES = STUDIO / "quality_scores.json"
STATE_PATH = STUDIO / "zombie_sweep_state.json"
PUBDATE_CACHE_PATH = STUDIO / "zombie_sweep_pubdate_cache.json"
KEEPLIST_PATH = STUDIO / "zombie_sweep_keeplist.json"
PRIVATE_BATCH_PATH = STUDIO / "_private_batch_ids.json"

MIN_AGE_DAYS = 14
DAILY_CAP_DEFAULT = 150  # videos.update 預算(50 quota/支 × 150 = 7500 quota，留餘量)


# --------------------------------------------------------------------------- #
# 本機資料讀寫（皆離線，dry-run 只用這些）
# --------------------------------------------------------------------------- #

def load_published() -> list[dict]:
    d = load_json_safe(QSCORES, default={}) or {}
    pub = d.get("published") or []
    return [p for p in pub if isinstance(p, dict) and p.get("videoId")]


def load_state() -> dict:
    d = load_json_safe(STATE_PATH, default={})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("done", {})
    return d


def save_state(state: dict) -> None:
    save_json_atomic(STATE_PATH, state)


def load_pubdate_cache() -> dict:
    d = load_json_safe(PUBDATE_CACHE_PATH, default={})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("pubdate", {})  # videoId -> "YYYY-MM-DD"(不會變，永久快取)
    return d


def save_pubdate_cache(cache: dict) -> None:
    cache["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_json_atomic(PUBDATE_CACHE_PATH, cache)


def load_keeplist() -> dict:
    """優先清單：Carson 手動維護，slug 或 videoId 命中都永遠不動。沒有就建一份空的。"""
    d = load_json_safe(KEEPLIST_PATH, default=None)
    if not isinstance(d, dict):
        d = {
            "note": "Carson 手動維護的保護清單：slug 或 videoId 列在這裡的片，"
                     "zombie_sweep 永遠不會設為 private，即使 0 觀看+已滿14天。",
            "slugs": [],
            "videoIds": [],
        }
        save_json_atomic(KEEPLIST_PATH, d)
    d.setdefault("slugs", [])
    d.setdefault("videoIds", [])
    return d


def load_private_batch_ids() -> list[str]:
    d = load_json_safe(PRIVATE_BATCH_PATH, default=[])
    return d if isinstance(d, list) else []


# --------------------------------------------------------------------------- #
# 純函式：分類/篩選（皆可離線單元測試）
# --------------------------------------------------------------------------- #

def is_franchise_protected(slug: str) -> str | None:
    """回傳命中的排除原因 key，沒命中回 None。"""
    if ple._match_truth_lab(slug):
        return "franchise_truth_lab"
    if ple._match_ep_live(slug):
        return "franchise_ep_live"
    return None


def is_keeplist_protected(slug: str, video_id: str, keeplist: dict) -> bool:
    return slug in keeplist.get("slugs", []) or video_id in keeplist.get("videoIds", [])


def parse_pubdate(published_at: str) -> date | None:
    """YouTube snippet.publishedAt 是 ISO8601（含或不含毫秒/Z），只需日期精度，
    取前 10 碼「YYYY-MM-DD」硬解析，比 datetime.fromisoformat 在 py3.9 更穩
    （3.9 對含 'Z'/毫秒位數的字串解析容易炸）。"""
    if not published_at or len(published_at) < 10:
        return None
    try:
        return datetime.strptime(published_at[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def build_offline_pool(published: list[dict], state: dict, keeplist: dict) -> tuple[list[dict], Counter]:
    """離線分類：回傳 (offline_pool, exclusion_counts)。offline_pool 是「0 觀看 + 不在
    任何保護名單 + 沒處理過」的候選（尚未套用 14 天門檻，因為那需要 pubdate）。"""
    done = state.get("done", {})
    pool: list[dict] = []
    counts: Counter = Counter()
    for p in published:
        vid = p["videoId"]
        slug = p.get("slug", "")
        if vid in done:
            counts["已處理過(done)"] += 1
            continue
        views = p.get("views")
        if views:  # truthy = >0
            counts["有觀看(views>0)"] += 1
            continue
        if is_keeplist_protected(slug, vid, keeplist):
            counts["優先清單保護"] += 1
            continue
        reason = is_franchise_protected(slug)
        if reason == "franchise_truth_lab":
            counts["台股真相實驗室系列(排除)"] += 1
            continue
        if reason == "franchise_ep_live":
            counts["EP系列(排除)"] += 1
            continue
        counts["offline_qualified"] += 1
        pool.append(p)
    return pool, counts


def split_by_pubdate(pool: list[dict], pubdate_cache: dict, today: date) -> tuple[list[dict], list[dict], list[dict]]:
    """把離線候選池依本機已快取的發布日期分三桶：(ready>=14天, too_new<14天, unknown無快取)。
    純離線（讀 pubdate_cache 這個本機檔，不連網），dry-run 也能用它給出真實數字
    （前提是曾經跑過一次 --apply 建過快取；第一次跑全部落 unknown，這是誠實結果）。"""
    ready, too_new, unknown = [], [], []
    pmap = pubdate_cache.get("pubdate", {})
    for p in pool:
        vid = p["videoId"]
        d_str = pmap.get(vid)
        if not d_str:
            unknown.append(p)
            continue
        try:
            pubd = datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            unknown.append(p)
            continue
        age = (today - pubd).days
        p2 = dict(p)
        p2["_pubdate"] = d_str
        p2["_age_days"] = age
        if age >= MIN_AGE_DAYS:
            ready.append(p2)
        else:
            too_new.append(p2)
    return ready, too_new, unknown


# --------------------------------------------------------------------------- #
# 網路輔助（只在 --apply 才 import/呼叫）
# --------------------------------------------------------------------------- #

def _is_quota_error(exc) -> bool:
    from googleapiclient.errors import HttpError
    if isinstance(exc, HttpError) and getattr(exc.resp, "status", None) == 403:
        return "quotaexceeded" in str(exc).lower() or "quota" in str(exc).lower()
    return False


def fetch_meta_batch(yt, video_ids: list[str]) -> tuple[dict, bool]:
    """批次 videos.list(part=snippet,statistics)，50 支/次＝1 quota。
    回傳 (meta: {videoId: {"publishedAt":..,"viewCount":..,"privacyStatus":..}}, quota_dead: bool)。
    quota_dead=True 代表本輪一撞到 403 quotaExceeded 就立刻停止繼續打（優雅停）。"""
    out = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        try:
            resp = yt.videos().list(part="snippet,statistics,status", id=",".join(chunk)).execute()  # 1 quota
        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                return out, True
            print(f"[warn] videos.list 批次失敗（非 quota）：{str(exc)[:120]}", file=sys.stderr)
            continue
        for it in resp.get("items", []):
            out[it["id"]] = {
                "publishedAt": it.get("snippet", {}).get("publishedAt", ""),
                "viewCount": int(it.get("statistics", {}).get("viewCount", 0) or 0),
                "privacyStatus": it.get("status", {}).get("privacyStatus", ""),
                "status": it.get("status", {}),
            }
    return out, False


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="0 觀看舊片(殭屍片)清理引擎：滿14天+0觀看+非系列片+非優先清單→設 private（可逆）。")
    ap.add_argument("--apply", action="store_true", help="真的呼叫 videos.update 寫入；不加則只 dry-run（預設，不連網）")
    ap.add_argument("--max", type=int, default=DAILY_CAP_DEFAULT, help=f"本輪最多處理幾支(50 quota/支，預設{DAILY_CAP_DEFAULT}≈7500 quota)")
    args = ap.parse_args()

    published = load_published()
    if not published:
        print("[info] STUDIO/quality_scores.json 無 published 資料，無事可做。")
        return 0

    state = load_state()
    keeplist = load_keeplist()
    pubdate_cache = load_pubdate_cache()
    today = date.today()

    pool, counts = build_offline_pool(published, state, keeplist)
    ready, too_new, unknown = split_by_pubdate(pool, pubdate_cache, today)

    print(f"[info] STUDIO/quality_scores.json 已發布共 {len(published)} 支")
    for k in ("有觀看(views>0)", "已處理過(done)", "優先清單保護",
              "台股真相實驗室系列(排除)", "EP系列(排除)"):
        if counts.get(k):
            print(f"   排除｜{k}：{counts[k]} 支")
    print(f"[info] 離線候選池(0觀看+非系列片+非優先清單+未處理過)：{len(pool)} 支")
    print(f"   → 發布日期已知且已滿{MIN_AGE_DAYS}天(最終候選)：{len(ready)} 支")
    print(f"   → 發布日期已知但未滿{MIN_AGE_DAYS}天(太新，保留)：{len(too_new)} 支")
    print(f"   → 發布日期未知(pubdate cache 沒有，fail-safe 排除，等 --apply 補建快取)：{len(unknown)} 支")

    if not args.apply:
        print("\n[dry-run] 不連網、不需要 token、不打任何 API，以下皆為本機既有快取算出的真實數字。")
        sample = ready[:10]
        if sample:
            print(f"\n[dry-run] 抽樣(最多10支，來自「已滿{MIN_AGE_DAYS}天最終候選」{len(ready)}支)：")
            for i, p in enumerate(sample, 1):
                print(f"  {i}. {p.get('slug', '')[:40]}\n"
                      f"     videoId={p['videoId']}｜views={p.get('views')}｜"
                      f"發布日={p.get('_pubdate')}(距今{p.get('_age_days')}天)")
        else:
            print(f"\n[dry-run] 目前 pubdate cache 尚無任何已知發布日期的候選"
                  f"（{'首次跑' if not pubdate_cache.get('pubdate') else '快取內沒有命中本輪離線候選池的項目'}），"
                  f"跑一次 --apply（會用讀取型 videos.list 幫候選池補建發布日期快取，"
                  f"quota 允許的話約 {(len(pool) + 49) // 50} 次呼叫）後，本 dry-run 就能顯示真實可清數字。")
        print(f"\n[dry-run] 本輪若跑 --apply --max {args.max}：最多寫入 {min(len(ready), args.max)} 支"
              f"（實際數字仍取決於 --apply 當下 videos.list 二次確認 viewCount==0 是否通過）。")
        return 0

    # -------------------- --apply：真的連網 -------------------- #
    from decision_dept import yt_service
    yt = yt_service()

    # Step A：幫「unknown」桶補建 pubdate 快取（讀取，1 quota/50支，順便拿當下 viewCount+privacyStatus）
    quota_dead = False
    live_meta: dict[str, dict] = {}
    if unknown:
        ids_need = [p["videoId"] for p in unknown]
        meta, quota_dead = fetch_meta_batch(yt, ids_need)
        live_meta.update(meta)
        for vid, m in meta.items():
            if m.get("publishedAt"):
                pubdate_cache["pubdate"][vid] = m["publishedAt"][:10]
        save_pubdate_cache(pubdate_cache)
        print(f"[info] 補建發布日期快取：{len(meta)}/{len(ids_need)} 支成功"
              + ("（撞到 quota 用罄，優雅停止本階段）" if quota_dead else ""))
        # 用剛補到的快取重新分桶一次
        ready, too_new, unknown = split_by_pubdate(pool, pubdate_cache, today)
        print(f"[info] 補建後：已滿{MIN_AGE_DAYS}天最終候選 {len(ready)} 支｜太新 {len(too_new)} 支｜仍未知 {len(unknown)} 支")

    ready.sort(key=lambda p: -(p.get("_age_days") or 0))  # 最舊的先清
    plan = ready[: max(0, args.max)]
    print(f"[info] 本輪計畫處理 {len(plan)} 支（上限 --max {args.max}）")

    n_ok, n_skip_views, n_skip_other = 0, 0, 0
    updated_ids: list[str] = []
    for p in plan:
        if quota_dead:
            break
        vid = p["videoId"]
        slug = p.get("slug", "")
        try:
            resp = yt.videos().list(part="status,statistics", id=vid).execute()  # 1 quota，動之前再確認一次
            items = resp.get("items") or []
            if not items:
                print(f"[skip] {slug[:30]}：videos.list 查無此片(videoId={vid})，跳過")
                n_skip_other += 1
                continue
            it = items[0]
            live_views = int(it.get("statistics", {}).get("viewCount", 0) or 0)
            status = dict(it.get("status", {}))
            priv = status.get("privacyStatus")
            if live_views > 0:
                print(f"[skip] {slug[:30]}：videos.list 重查有 {live_views} 觀看(快取已過期)，跳過並記錄")
                n_skip_views += 1
                continue
            if priv != "public":
                print(f"[skip] {slug[:30]}：目前已是 {priv}(非 public)，記為完成，跳過")
                state["done"][vid] = {"slug": slug, "date": today.isoformat(),
                                       "reason": f"already_{priv}", "views_at_time": live_views}
                save_state(state)
                continue
            status["privacyStatus"] = "private"
            yt.videos().update(part="status", body={"id": vid, "status": status}).execute()  # 50 quota
            state["done"][vid] = {"slug": slug, "date": today.isoformat(), "reason": "0view_14d+",
                                   "views_at_time": live_views, "published_at": p.get("_pubdate"),
                                   "age_days": p.get("_age_days"), "prev_privacy": "public"}
            save_state(state)
            updated_ids.append(vid)
            n_ok += 1
            print(f"[ok] {slug[:30]} → 已設 private(0觀看/{p.get('_age_days')}天前發布)")
        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                print(f"[info] YouTube API 配額用罄，優雅停止（本輪已完成 {n_ok} 支）。", file=sys.stderr)
                quota_dead = True
                break
            print(f"[warn] {slug[:30]} 失敗：{str(exc)[:120]}", file=sys.stderr)
            n_skip_other += 1

    # -------------------- 順手：_private_batch_ids.json 剩餘編造片 -------------------- #
    n_batch_ok = 0
    batch_ids = load_private_batch_ids()
    if batch_ids and not quota_dead:
        meta, qd2 = fetch_meta_batch(yt, batch_ids)
        for vid in batch_ids:
            m = meta.get(vid)
            if not m:
                print(f"[skip] _private_batch_ids {vid}：查無資料或 quota 用罄，跳過")
                continue
            if m["privacyStatus"] != "public":
                print(f"[skip] _private_batch_ids {vid}：已是 {m['privacyStatus']}，跳過")
                continue
            try:
                status = dict(m["status"])
                status["privacyStatus"] = "private"
                yt.videos().update(part="status", body={"id": vid, "status": status}).execute()  # 50 quota
                n_batch_ok += 1
                updated_ids.append(vid)
                print(f"[ok] _private_batch_ids {vid} → 已設 private")
            except Exception as exc:  # noqa: BLE001
                if _is_quota_error(exc):
                    print("[info] 處理 _private_batch_ids 時撞到 quota 用罄，優雅停止。", file=sys.stderr)
                    break
                print(f"[warn] _private_batch_ids {vid} 失敗：{str(exc)[:120]}", file=sys.stderr)
        if qd2:
            quota_dead = True

    # -------------------- 讀回驗證 -------------------- #
    if updated_ids:
        readback, _ = fetch_meta_batch(yt, updated_ids)
        confirmed = sum(1 for vid in updated_ids if readback.get(vid, {}).get("privacyStatus") == "private")
        print(f"[verify] 讀回確認 privacyStatus=private：{confirmed}/{len(updated_ids)}")

    remain = len(ready) - n_ok
    extra = "（配額用罄，明日續）" if quota_dead else ""
    log_ops("殭屍片清理", f"本輪設private {n_ok}支(+編造片{n_batch_ok}支) 有觀看跳過{n_skip_views}支 "
                          f"其他跳過{n_skip_other}支 剩{max(0, remain)}支{extra}")
    print(f"\n[done] 本輪設 private {n_ok} 支（+編造片批次 {n_batch_ok} 支），"
          f"有觀看跳過 {n_skip_views} 支，其他跳過 {n_skip_other} 支，剩 {max(0, remain)} 支下次續。{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
