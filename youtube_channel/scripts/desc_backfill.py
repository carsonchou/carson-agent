#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""desc_backfill.py — 存量已發布片描述回填『系列連播』導流連結。

背景（為什麼要有這支）
----------------------
頻道已發布 646+ 支片，描述都是發布當下各寫各的，彼此孤立、沒有互相導流。
昨天剛建好「台股真相實驗室」franchise（EP1 已上線）+ playlist_engine.py 的
四條核心播放清單（真相實驗室 / ETF定投 / EP實測 / 避雷拆穿）。把存量片的描述
補上一行「這支其實屬於哪個連載系列，點進去接著看」＝免費的 watch time／訂閱轉換
放大器，不用重新產一支新片。

做法
----
1. 從 STUDIO/uploaded_ledger.json 取全部已發布片（slug→videoId）。
2. 依觀看數高到低排序（觀看數來自 STUDIO/quality_scores.json 的 published 清單
   的 views 欄位；查無觀看數的片，退回用台帳收錄順序反過來當『新到舊』代理——
   台帳是 append-only，越後面寫入＝越晚發布，不需要真的去讀早已可能被清掉的
   本機 output/*.mp4 mtime）。
3. 用 scripts/playlist_engine.py 既有的 classify() 分類規則，挑該支片『最相關』
   的一個播放清單（沒命中任何清單的片直接跳過，不強塞；命中多個時取
   playlist_engine.PLAYLIST_DEFS 宣告順序中最前面那個──該順序即引擎作者定義的
   優先序：真相實驗室旗艦系列優先，其次 ETF 定投、EP 實測，最後新手避雷）。
4. videos.list 拿現有描述（1 quota）→ 若已含任一播放清單連結（含本引擎的
   「📚 全系列連播」標記）就跳過，不重複插入（冪等）。
5. 否則在描述『開頭第一行之後』插入導流行，绝不刪改原描述任何一個字
   （含 Pionex 聯盟連結／免責聲明）→ videos.update 寫回（50 quota）。

誠信／安全紅線
--------------
- 只「插入」，絕不刪改原描述任何內容：apply_promo() 內部會把插入的區塊拿掉、
  還原回原文比對一致，不一致就整支跳過（防呆，理論上不該發生）。
- 寫回前後長度檢查：新描述長度必須 ≥ 原描述，且不得超過 YouTube 5000 字上限；
  異常就跳過該支，不勉強塞。
- 冪等：已處理過的 slug 記進 STUDIO/desc_backfill_state.json 的 done，
  之後重跑不會重複打 API；已經含清單連結的片一律跳過並記為 done。

quota 紀律
----------
每支 ~51 quota（1 videos.list + 50 videos.update）。--max 預設 30（≈1530 quota，
YouTube 每日配額 10000 內留給 daily_publish/playlist_engine 等其他 job 共用）。
遇到 403 quotaExceeded 優雅停止，狀態已即時逐支落地，下次接續跑。

用法
----
    python scripts/desc_backfill.py --dry-run           # 只印計畫，不連網、不需要 token
    python scripts/desc_backfill.py --max 30            # 正式跑，本輪最多處理 30 支
"""
from __future__ import annotations

import argparse
import sys
import time
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
LEDGER = STUDIO / "uploaded_ledger.json"
QSCORES = STUDIO / "quality_scores.json"
STATE_PATH = STUDIO / "desc_backfill_state.json"

MAX_DESC_LEN = 5000  # YouTube 描述長度硬上限（超過就不插，不能靠截斷原內容來塞）
PROMO_LABEL = "📚 全系列連播"


# --------------------------------------------------------------------------- #
# 本機資料讀寫
# --------------------------------------------------------------------------- #

def load_ledger() -> dict:
    d = load_json_safe(LEDGER, default={})
    return d if isinstance(d, dict) else {}


def load_state() -> dict:
    d = load_json_safe(STATE_PATH, default={})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("done", {})
    return d


def save_state(state: dict) -> None:
    save_json_atomic(STATE_PATH, state)


def _views_map() -> dict:
    """videoId -> views（來自 quality_scores.json 的 published 清單）；查無回空 dict。"""
    d = load_json_safe(QSCORES, default={}) or {}
    out = {}
    for it in (d.get("published") or []):
        if isinstance(it, dict) and it.get("videoId") and isinstance(it.get("views"), (int, float)):
            out[it["videoId"]] = it["views"]
    return out


def ranked_candidates(ledger: dict) -> list[tuple[str, str, float | None]]:
    """回傳 [(slug, videoId, views_or_None)]，觀看數高到低排；查無觀看數的片併到後段，
    以台帳（append-only）收錄順序反過來當『新到舊』代理。"""
    vmap = _views_map()
    with_views, without_views = [], []
    for slug, vid in ledger.items():
        v = vmap.get(vid)
        if v:
            with_views.append((slug, vid, v))
        else:
            without_views.append((slug, vid, None))
    with_views.sort(key=lambda t: -t[2])
    without_views.reverse()  # 台帳越後面＝越晚寫入＝越晚發布
    return with_views + without_views


# --------------------------------------------------------------------------- #
# 播放清單選擇 + 插入邏輯（純函式，皆可離線單元驗證）
# --------------------------------------------------------------------------- #

def choose_playlist(slug: str, ple_state: dict) -> tuple[str, str] | None:
    """依 playlist_engine 的分類規則挑『最相關』的一個清單，回傳 (title, playlist_id)。
    命中多個時取 PLAYLIST_DEFS 宣告順序最前面那個；沒命中或該清單還沒有 playlist_id
    （--ensure 還沒跑過）一律回 None（不強塞、不臆造連結）。"""
    keys = ple.classify(slug)
    for key in keys:  # PLAYLIST_DEFS 宣告順序＝優先序，classify() 回傳順序與其一致
        plid = ple_state.get(key, {}).get("playlist_id")
        if plid:
            return ple._DEF_BY_KEY[key]["title"], plid
    return None


def promo_line(title: str, plid: str) -> str:
    return f"{PROMO_LABEL}｜{title}：https://www.youtube.com/playlist?list={plid}"


def already_has_promo(description: str, ple_state: dict) -> bool:
    """冪等判斷：描述已含本引擎標記，或已含任一四條核心清單的連結，就視為已處理過。"""
    if PROMO_LABEL in description:
        return True
    for d in ple.PLAYLIST_DEFS:
        plid = ple_state.get(d["key"], {}).get("playlist_id")
        if plid and f"list={plid}" in description:
            return True
    return False


def apply_promo(original: str, promo: str) -> str | None:
    """把導流行插入描述『第一行之後』，絕不刪改原內容。

    做法：以第一個換行切開 first/rest，插入 first\\n\\n{promo}\\n\\nrest；插入前先
    驗證「拿掉插入區塊能還原回原文」（reconstructed == original），驗不過就回 None
    （呼叫端據此跳過該支，這是防呆，正常情況不該發生）。也順帶把「候選描述長度
    是否 ≥ 原描述」的檢查做在這裡，方便單元測試一次覆蓋。
    """
    first, sep, rest = original.partition("\n")
    if sep:
        candidate = f"{first}\n\n{promo}\n\n{rest}"
        reconstructed = first + "\n" + rest
    else:
        candidate = f"{first}\n\n{promo}" if original else promo
        reconstructed = first
    if reconstructed != original:
        return None
    if len(candidate) < len(original):
        return None
    return candidate


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="把系列連播播放清單連結回填進存量已發布片描述（冪等、只插入不刪改）。")
    ap.add_argument("--max", type=int, default=30, help="本輪最多處理幾支(~51 quota/支，預設30≈1530 quota)")
    ap.add_argument("--dry-run", action="store_true", help="只印計畫，不連網、不需要 token、不打任何 API")
    args = ap.parse_args()

    ledger = load_ledger()
    if not ledger:
        print("[info] STUDIO/uploaded_ledger.json 無資料，無事可做。")
        return 0

    ple_state = ple.load_state()
    state = load_state()
    done = state["done"]

    cands = ranked_candidates(ledger)
    plan = []
    for slug, vid, views in cands:
        if slug in done:
            continue
        picked = choose_playlist(slug, ple_state)
        if not picked:
            continue  # 沒命中任何清單，不強塞
        plan.append((slug, vid, views, picked))
        if len(plan) >= args.max:
            break

    total_hit = sum(1 for slug, vid, _ in cands if slug not in done and choose_playlist(slug, ple_state))
    print(f"[info] 台帳共 {len(ledger)} 支｜已處理過 {len(done)} 支｜"
          f"命中清單且待回填 {total_hit} 支｜本輪上限 {args.max} → 排入 {len(plan)} 支。")

    if args.dry_run:
        print("\n[dry-run] 不連網、不需要 token、不打任何 API，只印計畫：")
        for i, (slug, vid, views, (title, plid)) in enumerate(plan[:10], 1):
            v_disp = f"{views:.0f}" if isinstance(views, (int, float)) else "無觀看數據(用發布新舊排序)"
            print(f"  {i}. {slug[:40]}\n"
                  f"     videoId={vid}｜views={v_disp}\n"
                  f"     → 插入「{title}」導流：list={plid}")
        if len(plan) > 10:
            print(f"  ... 還有 {len(plan) - 10} 支（本輪計畫共 {len(plan)} 支）")
        return 0

    if not plan:
        print("[ok] 沒有待回填的片（全數已處理，或都沒命中任何清單）。")
        return 0

    from decision_dept import yt_service
    from googleapiclient.errors import HttpError
    yt = yt_service()

    n_ok, n_skip = 0, 0
    quota_hit = False
    for slug, vid, views, (title, plid) in plan:
        try:
            resp = yt.videos().list(part="snippet", id=vid).execute()  # 1 quota
            items = resp.get("items") or []
            if not items:
                print(f"[skip] {slug[:30]}：videos.list 查無此片(videoId={vid})，跳過")
                n_skip += 1
                continue
            snippet = items[0]["snippet"]
            desc = snippet.get("description", "") or ""
            if already_has_promo(desc, ple_state):
                print(f"[skip] {slug[:30]}：描述已含清單連結，冪等跳過")
                done[slug] = {"videoId": vid, "reason": "already_has_link", "date": time.strftime("%Y-%m-%d")}
                save_state(state)
                continue
            promo = promo_line(title, plid)
            new_desc = apply_promo(desc, promo)
            if new_desc is None or len(new_desc) < len(desc) or len(new_desc) > MAX_DESC_LEN:
                reason = "插入後超過5000字上限" if (new_desc and len(new_desc) > MAX_DESC_LEN) else "插入一致性檢查沒過"
                print(f"[skip] {slug[:30]}：{reason}，防呆跳過（不動原描述）")
                n_skip += 1
                continue
            snippet["description"] = new_desc
            yt.videos().update(part="snippet", body={"id": vid, "snippet": snippet}).execute()  # 50 quota
            done[slug] = {"videoId": vid, "playlist": title, "date": time.strftime("%Y-%m-%d")}
            save_state(state)
            n_ok += 1
            print(f"[ok] {slug[:30]} → 已插入「{title}」導流（原{len(desc)}→新{len(new_desc)}字）")
        except HttpError as exc:
            msg = str(exc)
            status = getattr(exc.resp, "status", None)
            if status == 403 and ("quota" in msg.lower() or "exceeded" in msg.lower()):
                print(f"[info] YouTube API 配額用罄，優雅停止（本輪已完成 {n_ok} 支）。", file=sys.stderr)
                log_ops("描述回填", f"配額用罄優雅停止，本輪已回填{n_ok}支")
                quota_hit = True
                break
            print(f"[warn] {slug[:30]} 失敗：{msg[:120]}", file=sys.stderr)
            n_skip += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {slug[:30]} 例外：{str(exc)[:120]}", file=sys.stderr)
            n_skip += 1

    remain = sum(1 for slug, vid, _ in cands if slug not in done and choose_playlist(slug, ple_state))
    extra = "（配額用罄，明日續）" if quota_hit else ""
    log_ops("描述回填", f"本輪回填{n_ok}支 跳過{n_skip}支 剩{remain}支{extra}")
    print(f"\n[done] 本輪回填 {n_ok} 支，跳過 {n_skip} 支，剩 {remain} 支下次續。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
