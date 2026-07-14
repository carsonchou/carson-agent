#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""playlist_engine.py — 台股真相實驗室連載 franchise 的播放清單自動管理引擎。

為什麼要有這支（跟既有 build_playlists.py 的差異）
----------------------------------------------------
build_playlists.py 是依「雙主軸系列」（AI×交易 / 台股量化 / EP實測）互斥分桶，
且已在 deploy/crontab.txt 排程（`build_playlists.py --max 40`，每晚由
scripts/local_cron.py 讀 crontab.txt 在本機執行），狀態存 STUDIO/playlists.json。

本支是為了剛上線的「台股真相實驗室」連載 franchise（EP1-3 已產出）而寫，鎖定
四條**核心**播放清單（見 PLAYLIST_DEFS），分類規則不同、且**一支片可進多個
清單**（非互斥）。若沿用 STUDIO/playlists.json 當狀態檔，build_playlists.py
每次執行都會用「只含自己 3 個桶」的全新 dict 整檔覆寫（見該檔 main() 尾端
`PLAYLISTS_STATE.write_text(json.dumps(state, ...))`），會把本引擎寫入的 4 個
桶狀態砍掉。因此本引擎改用**獨立狀態檔** STUDIO/playlist_engine.json，避免
互相打架；YouTube 端播放清單本身不受影響（--sync 的冪等判斷一律以
playlistItems.list 從 API 讀回真實成員做準，不只信本機狀態檔，見 sync_playlist()）。

四條核心播放清單
----------------
①「台股真相實驗室｜真回測連載」— slug 含「真相實驗室」（涵蓋「臺股真相實驗室」
   「台股真相實驗室」，因中間 5 字子字串相同）
②「0050/ETF 定期定額實驗」— slug 含 0050/0056/00878/006208/定期定額/定投
③「EP 自動交易實測」— slug 同時含「EP」與「實測」
④「新手避雷·迷思拆穿」— slug 含 拆穿/迷思/避雷/陷阱

OAuth / API 沿用既有正式機 token（不重造 OAuth 邏輯）
------------------------------------------------------
與 organize_dept.py / build_playlists.py 相同做法：`from decision_dept import
yt_service`（token_manage.json，scope=youtube.force-ssl，涵蓋播放清單讀寫）。
daily_publish.py 的 upload_one() 已自帶另一份同 scope 的已認證 service，掛勾時
直接重用該 service（見 add_to_playlists()），不重新認證。

quota 紀律
----------
playlists.list=1、playlists.insert=50、playlistItems.list=1（分頁每頁仍算 1）、
playlistItems.insert=50。--sync 單次最多新增 --max（預設 60，約 3000 quota）支，
超過留到下次再跑，印出「本次加了 N 支、剩 M 支下次續」。

安全預設
--------
--dry-run：完全不連網、不需要 token，只讀本機 STUDIO/uploaded_ledger.json 印出
「會建哪些清單、哪些片會加進哪」的計畫。
只會建立播放清單／加入影片，絕不刪除、絕不改動影片本身。

用法
----
    python scripts/playlist_engine.py --ensure --sync --dry-run   # 先看計畫
    python scripts/playlist_engine.py --ensure --sync             # 正式執行
    python scripts/playlist_engine.py --sync --max 30             # 只同步，本次上限 30 支
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"
STATE_PATH = STUDIO / "playlist_engine.json"  # 獨立狀態檔，見檔頭說明（避免跟 build_playlists.py 互撞）

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):
        pass

try:
    from studio_common import save_json_atomic, load_json_safe
except Exception:  # noqa: BLE001
    import json as _json

    def load_json_safe(path, default=None):
        p = Path(path)
        try:
            if p.exists():
                return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
        return default

    def save_json_atomic(path, data, keep_bak: bool = True):
        Path(path).write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 四條核心播放清單定義：key（狀態檔用）／title（YouTube 上顯示名）／description
# （含頻道定位語＋訂閱理由，誠信鐵則：不喊單、不保證收益）／match（分類規則）
# --------------------------------------------------------------------------- #

def _match_truth_lab(slug: str) -> bool:
    """2026-07-14 實測修:slug 有長度上限,系列名掛在標題尾端會被**截斷**——
    已發布的 EP1 slug 是「…差434臺股真相」、EP6 是「…臺股真相實」,「實驗室」被切掉,
    原規則 `"真相實驗室" in slug` 永遠 match 不到 → truth_lab 清單 0 支、franchise 連播斷鏈。
    放寬為「臺股真相/台股真相」子字串(頻道無其他用此字樣的非系列片)。"""
    return ("真相實驗室" in slug) or ("臺股真相" in slug) or ("台股真相" in slug)


def _match_etf_dca(slug: str) -> bool:
    kws = ("0050", "0056", "00878", "006208", "定期定額", "定投")
    return any(k in slug for k in kws)


def _match_ep_live(slug: str) -> bool:
    return "EP" in slug and "實測" in slug


def _match_debunk(slug: str) -> bool:
    kws = ("拆穿", "迷思", "避雷", "陷阱")
    return any(k in slug for k in kws)


PLAYLIST_DEFS: list[dict] = [
    {
        "key": "truth_lab",
        "title": "台股真相實驗室｜真回測連載",
        "description": (
            "量化阿森｜台股真相實驗室：用真實回測數字拆穿「一次All in vs 定期定額」"
            "「高股息 vs 大盤」這類台股常見說法，每集同一套規則檢驗不同標的，讓你自己"
            "判斷該不該相信。誠信鐵則：不喊單、不推薦特定商品、不保證未來收益，數字全部"
            "可自行回測驗證。訂閱追蹤完整連載，把每一集拆穿的真相串起來看。"
        ),
        "match": _match_truth_lab,
    },
    {
        "key": "etf_dca",
        "title": "0050/ETF 定期定額實驗",
        "description": (
            "量化阿森｜0050、0056、00878、006208 等台股 ETF 的定期定額 vs All-in 真回測"
            "比較。不推薦特定商品、不保證未來報酬，每支影片的數字都可自行回測覆核。"
            "訂閱看完整實驗系列，找出真正適合自己的存股節奏。"
        ),
        "match": _match_etf_dca,
    },
    {
        "key": "ep_live_test",
        "title": "EP 自動交易實測",
        "description": (
            "量化阿森｜把交易機器人真金白銀（或模擬倉，影片內會明確標示）丟到市場上，"
            "逐集公開帳戶損益，賺賠都誠實揭露，不是曬單而是給你看『這套規則實際會發生"
            "什麼』。不保證收益、不構成投資建議。訂閱看完整實測連載，跟著一起驗證。"
        ),
        "match": _match_ep_live,
    },
    {
        "key": "beginner_debunk",
        "title": "新手避雷·迷思拆穿",
        "description": (
            "量化阿森｜新手最容易踩的量化/交易迷思與陷阱，用數據和回測拆穿似是而非的"
            "說法，不製造恐慌、不誇大風險，只提醒你先看清楚遊戲規則再進場。誠信鐵則："
            "不喊單、不保證收益。訂閱幫自己避開下一個坑。"
        ),
        "match": _match_debunk,
    },
]

_DEF_BY_KEY = {d["key"]: d for d in PLAYLIST_DEFS}


def classify(slug: str) -> list[str]:
    """回傳 slug 命中的所有播放清單 key（可多個，非互斥）。"""
    return [d["key"] for d in PLAYLIST_DEFS if d["match"](slug)]


# --------------------------------------------------------------------------- #
# 本機資料讀寫
# --------------------------------------------------------------------------- #


def load_ledger() -> dict:
    d = load_json_safe(LEDGER, default={})
    return d if isinstance(d, dict) else {}


def load_state() -> dict:
    d = load_json_safe(STATE_PATH, default={})
    return d if isinstance(d, dict) else {}


def save_state(state: dict) -> None:
    save_json_atomic(STATE_PATH, state)


def group_videos(ledger: dict) -> dict[str, list[tuple[str, str]]]:
    groups: dict[str, list[tuple[str, str]]] = {d["key"]: [] for d in PLAYLIST_DEFS}
    for slug, vid in ledger.items():
        for key in classify(slug):
            groups[key].append((slug, vid))
    return groups


# --------------------------------------------------------------------------- #
# YouTube API 輔助（真跑才 import，dry-run 完全不碰）
# --------------------------------------------------------------------------- #


def _yt_playlists_by_title(yt) -> dict:
    """列出頻道現有播放清單（title -> id），供 ensure 判斷是否已存在（含非本引擎建的同名清單）。"""
    pl_map = {}
    try:
        tok = None
        while True:
            resp = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=tok).execute()
            for it in resp.get("items", []):
                pl_map[it["snippet"]["title"]] = it["id"]
            tok = resp.get("nextPageToken")
            if not tok:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 取播放清單清單失敗：{e}", file=sys.stderr)
    return pl_map


def _playlist_items(yt, plid: str) -> set | None:
    """讀回播放清單目前真實成員（videoId 集合）。--sync 的冪等判斷以此為準，不只信本機狀態檔。

    回傳 None 代表讀取本身失敗（例如 quota 用罄）——呼叫端必須把這種情況跟「清單本來就是空的」
    （回傳 set()）分開處理，絕不能把「讀失敗」誤當「目前沒有任何成員」寫回本機狀態檔，
    否則會把已同步過的紀錄洗成空的（曾發生：quota 用罄時 _playlist_items 靜默回空 set，
    state 的 video_ids 被整段覆寫成 []，雖然 YouTube 端播放清單本身沒事，但本機快取失真）。
    """
    ids = set()
    try:
        tok = None
        while True:
            r = yt.playlistItems().list(part="contentDetails", playlistId=plid, maxResults=50, pageToken=tok).execute()
            for it in r.get("items", []):
                ids.add(it["contentDetails"]["videoId"])
            tok = r.get("nextPageToken")
            if not tok:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 讀播放清單 {plid} 成員失敗：{e}", file=sys.stderr)
        return None
    return ids


def ensure_playlist_id(yt, key: str, state: dict, pl_map: dict) -> str | None:
    """確保 state[key] 有 playlist_id：先信 state，其次比對頻道現有同名清單，都沒有才新建。"""
    d = _DEF_BY_KEY[key]
    existing = state.get(key, {}).get("playlist_id")
    if existing:
        return existing
    if d["title"] in pl_map:
        plid = pl_map[d["title"]]
        state.setdefault(key, {})["playlist_id"] = plid
        return plid
    try:
        r = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": d["title"], "description": d["description"]},
            "status": {"privacyStatus": "public"},
        }).execute()
        plid = r["id"]
        pl_map[d["title"]] = plid
        state.setdefault(key, {})["playlist_id"] = plid
        return plid
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 建立清單「{d['title']}」失敗：{e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# --ensure：確保四條核心播放清單存在
# --------------------------------------------------------------------------- #


def cmd_ensure(dry_run: bool) -> int:
    state = load_state()
    if dry_run:
        print("[dry-run] --ensure 計畫（不連網、不需要 token）：")
        for d in PLAYLIST_DEFS:
            has_local = bool(state.get(d["key"], {}).get("playlist_id"))
            status = f"本機狀態已有 playlist_id={state[d['key']]['playlist_id']}（若頻道端已刪除會重建）" if has_local \
                else "本機未記錄 → 會先查頻道同名清單，查無才新建"
            print(f"  ① {d['title']}" if d["key"] == "truth_lab" else f"  - {d['title']}")
            print(f"      key={d['key']}｜{status}")
        return 0

    from decision_dept import yt_service
    yt = yt_service()
    pl_map = _yt_playlists_by_title(yt)
    for d in PLAYLIST_DEFS:
        before = state.get(d["key"], {}).get("playlist_id")
        pre_existed_on_channel = d["title"] in pl_map  # 呼叫 ensure_playlist_id 前先記錄，避免它內部寫入 pl_map 污染判斷
        plid = ensure_playlist_id(yt, d["key"], state, pl_map)
        if plid:
            action = "已存在（沿用）" if (before or pre_existed_on_channel) else "新建"
            print(f"[ok] {d['title']} -> playlist_id={plid}（{action}）")
        else:
            print(f"[FAIL] {d['title']} 建立/確認失敗", file=sys.stderr)
    save_state(state)
    log_ops("播放清單引擎", f"--ensure 完成：{', '.join(d['title'] for d in PLAYLIST_DEFS)}")
    print(f"[ok] 狀態已寫入 {STATE_PATH}")
    return 0


# --------------------------------------------------------------------------- #
# --sync：掃 ledger、依規則歸類、補進播放清單
# --------------------------------------------------------------------------- #


def cmd_sync(dry_run: bool, max_add: int) -> int:
    ledger = load_ledger()
    if not ledger:
        print("[info] STUDIO/uploaded_ledger.json 無資料，無法同步。")
        return 0
    groups = group_videos(ledger)
    total_matched_slots = sum(len(v) for v in groups.values())  # 含重複歸類（一片可進多清單）
    unmatched = sum(1 for slug in ledger if not classify(slug))

    if dry_run:
        print("[dry-run] --sync 計畫（不連網、不需要 token、不呼叫任何 YouTube 寫入 API）：")
        for d in PLAYLIST_DEFS:
            items = groups[d["key"]]
            print(f"\n[{d['title']}] {len(items)} 支")
            for slug, vid in items[:10]:
                print(f"   - {slug} ({vid})")
            if len(items) > 10:
                print(f"   ... 還有 {len(items) - 10} 支")
        print(f"\n[dry-run] 帳上共 {len(ledger)} 支，分類命中 {total_matched_slots} 個「片-清單」配對"
              f"（一片可進多清單），完全未命中任何清單關鍵字 {unmatched} 支（不強塞）。")
        print(f"[dry-run] 正式跑 --sync 時單次最多新增 {max_add} 支（跨四清單共用額度），"
              f"超過留到下次繼續（冪等：以 playlistItems.list 讀回真實成員判斷，重跑不會重複加）。")
        return 0

    from decision_dept import yt_service
    from googleapiclient.errors import HttpError
    yt = yt_service()
    state = load_state()
    pl_map = _yt_playlists_by_title(yt)

    def _is_quota_error(exc) -> bool:
        if isinstance(exc, HttpError) and getattr(exc.resp, "status", None) == 403:
            return "quotaexceeded" in str(exc).lower()
        return False

    budget = max(0, max_add)
    quota_capped = False
    quota_hit_hard = False  # 真的收到 API quotaExceeded（非本機 --max 預算用罄）：立刻停手，別再空燒 quota 打錯誤請求
    added_total = 0
    remain_total = 0
    for d in PLAYLIST_DEFS:
        items = groups[d["key"]]
        if not items:
            continue
        if quota_hit_hard:
            remain_total += sum(1 for _s, _v in items if _v not in state.get(d["key"], {}).get("video_ids", []))
            continue
        plid = ensure_playlist_id(yt, d["key"], state, pl_map)
        if not plid:
            print(f"[warn] 「{d['title']}」無 playlist_id，略過本清單同步。", file=sys.stderr)
            continue
        existing = _playlist_items(yt, plid)  # 真實成員，非本機狀態，冪等判斷以此為準
        if existing is None:
            # 讀取本身失敗（通常是 quota 用罄）：絕不能拿空集合誤判「目前沒有成員」，
            # 否則後面 state[...]["video_ids"] = sorted(existing) 會把本機已同步紀錄洗成空的。
            # 退回本機既有紀錄當本次 remaining 估計基準（僅供顯示，YouTube 端播放清單本身沒事），
            # 整個 def 直接跳過、不寫 state，等下次 quota 恢復後讀真值再補。
            print(f"[warn] 「{d['title']}」讀取播放清單成員失敗，本次略過同步（不觸碰本機狀態，避免洗掉既有紀錄）。",
                  file=sys.stderr)
            known = set(state.get(d["key"], {}).get("video_ids", []))
            remain_total += sum(1 for _s, _v in items if _v not in known)
            quota_capped = True
            quota_hit_hard = True
            continue
        added = 0
        remaining_here = 0
        for slug, vid in items:
            if vid in existing:
                continue
            if quota_hit_hard:
                remaining_here += 1
                continue
            if budget <= 0:
                quota_capped = True
                remaining_here += 1
                continue
            try:
                yt.playlistItems().insert(part="snippet", body={"snippet": {
                    "playlistId": plid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
                existing.add(vid)
                added += 1
                budget -= 1
            except Exception as e:  # noqa: BLE001
                if _is_quota_error(e):
                    print(f"[info] YouTube API 每日 quota 已用罄，優雅停止（{d['title']}／{slug}）。", file=sys.stderr)
                    quota_capped = True
                    quota_hit_hard = True
                    remaining_here += 1
                    continue
                print(f"[warn] 加入「{d['title']}」失敗 {slug}：{e}", file=sys.stderr)
        state.setdefault(d["key"], {})["playlist_id"] = plid
        state[d["key"]]["video_ids"] = sorted(existing)
        added_total += added
        remain_total += remaining_here
        print(f"[ok] {d['title']}：清單 {plid}，本次新增 {added} 支，共 {len(existing)} 支"
              + (f"（另有 {remaining_here} 支因額度用罄留待下次）" if remaining_here else "") + "。")

    save_state(state)
    if quota_capped:
        print(f"[info] 本次加了 {added_total} 支、剩 {remain_total} 支下次續（--max {max_add} 已用罄）。")
    else:
        print(f"[info] 本次加了 {added_total} 支，四清單已全數同步完畢，無待續。")
    log_ops("播放清單引擎", f"--sync 完成：本次新增 {added_total} 支"
            + (f"，剩 {remain_total} 支下次續" if quota_capped else ""))
    return 0


# --------------------------------------------------------------------------- #
# 掛勾用：單支影片上傳成功後即時歸類（供 daily_publish.py 呼叫）
# --------------------------------------------------------------------------- #


def add_to_playlists(yt, slug: str, video_id: str) -> list[str]:
    """單支影片即時歸類進命中的播放清單。供 daily_publish.py 在 upload_one() 成功後呼叫。

    設計成呼叫端只需一個 try/except 包住即可安全使用：
    - 內部對「每個清單」各自 try/except，一個清單失敗不影響其他清單。
    - 剛上傳的新片必然不在任何播放清單裡，因此不額外呼叫 playlistItems.list 確認
      （省 quota），只用本機狀態檔 video_ids 判斷是否已加過（防同一支被重複呼叫兩次）。
    - 重用呼叫端已認證好的 yt service（daily_publish.py 的 token_manage.json，
      scope=youtube.force-ssl，已含播放清單讀寫），不重新走 OAuth。

    回傳成功加入的清單標題清單（可能為空 list，代表沒命中任何清單或全部失敗）。
    """
    matched_keys = classify(slug)
    if not matched_keys:
        return []
    state = load_state()
    pl_map = None  # 延遲到真的需要新建清單時才查（省一次 quota）
    added_titles: list[str] = []
    for key in matched_keys:
        d = _DEF_BY_KEY[key]
        try:
            already = state.get(key, {}).get("video_ids", [])
            if video_id in already:
                continue
            plid = state.get(key, {}).get("playlist_id")
            if not plid:
                if pl_map is None:
                    pl_map = _yt_playlists_by_title(yt)
                plid = ensure_playlist_id(yt, key, state, pl_map)
            if not plid:
                continue
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": plid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
            state.setdefault(key, {}).setdefault("video_ids", [])
            if video_id not in state[key]["video_ids"]:
                state[key]["video_ids"].append(video_id)
            state[key]["playlist_id"] = plid
            added_titles.append(d["title"])
        except Exception as e:  # noqa: BLE001
            print(f"[warn] playlist_engine 單支歸類失敗（{d['title']}／{slug}）：{e}", file=sys.stderr)
    if added_titles:
        save_state(state)
    return added_titles


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(description="台股真相實驗室連載播放清單自動管理引擎。")
    ap.add_argument("--ensure", action="store_true", help="確保四條核心播放清單存在（不存在就建）")
    ap.add_argument("--sync", action="store_true", help="掃 uploaded_ledger.json 已發布影片，按規則歸類進清單（冪等）")
    ap.add_argument("--dry-run", action="store_true", help="只印計畫，不連網、不需要 token、不打任何 API")
    ap.add_argument("--max", type=int, default=60, dest="max_add",
                     help="--sync 單次最多新增幾支（跨四清單共用額度，預設 60≈3000 quota）")
    args = ap.parse_args()

    if not args.ensure and not args.sync:
        ap.print_help()
        return 0

    rc = 0
    if args.ensure:
        rc = cmd_ensure(args.dry_run) or rc
    if args.sync:
        rc = cmd_sync(args.dry_run, args.max_add) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
