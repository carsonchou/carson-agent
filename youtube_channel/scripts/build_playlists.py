#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_playlists.py — 把已發布影片依【雙主軸系列】分群，建/補 YouTube 播放清單。

跟 organize_dept.py（依主題分四桶：網格/定投/回測/風控）不同，這支是依「連載系列」
分群，目的是把外部最大爆款池（AI×交易）與本頻道主場（台股量化）串成 binge-watch
播放清單，衝觀眾的 session time：
  ①AI×交易（AI/Claude/量化/自動交易/bot/程式）
  ②台股量化（台股/台灣/0050/0056/00878/00929/006208/大盤/加權/存股/除權息/台積電；不含裸 ETF 避免誤抓 BTC ETF）
  ③EP實測（EP/實測/機器人跑——招牌實驗格式 franchise）
一支影片只歸最主的一群（依上面順序，第一個命中者；沒命中任何關鍵字就不強塞）。

正式寫入用 YouTube Data API v3 playlists.insert / playlistItems.insert 建立與補充，
OAuth 沿用既有 token.json（force-ssl 權限，同 organize_dept.py / decision_dept.yt_service，
不重造一份 OAuth 邏輯）。

安全預設：--dry-run 只讀本機 STUDIO/uploaded_ledger.json 做分群統計、印出「每群會建
什麼清單、加哪些片」，完全不連網、不需要 token、不呼叫任何 YouTube 寫入 API。
正式建立/補充播放清單才會連網（對外發布動作，需 Carson 確認過才跑非 dry-run）。

用法：python scripts/build_playlists.py --dry-run
      python scripts/build_playlists.py            # 正式建立/補充播放清單
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"
PLAYLISTS_STATE = STUDIO / "playlists.json"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass

# 雙主軸系列分群規則（依序，第一個命中者；一支只歸最主的一群，不強塞多群）。
BUCKETS = [
    ("AI×交易", ["AI", "Claude", "量化", "自動交易", "bot", "程式"]),
    ("台股量化", ["台股", "台灣", "0050", "0056", "00878", "00929", "006208",
              "大盤", "加權", "存股", "除權息", "台積電"]),
    ("EP實測", ["EP", "實測", "機器人跑"]),
]


def classify(text: str):
    """依 slug 文字命中的關鍵字歸類（比照 organize_dept.py 的 classify 慣例）。
    沒命中任何系列關鍵字 → 回傳 None，不強塞進任何清單。"""
    t = (text or "").lower()
    for name, kws in BUCKETS:
        if any(k.lower() in t for k in kws):
            return name
    return None


def load_ledger() -> dict:
    if not LEDGER.exists():
        return {}
    try:
        d = json.loads(LEDGER.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def group_videos(ledger: dict) -> dict:
    groups = {name: [] for name, _ in BUCKETS}
    for slug, vid in ledger.items():
        bucket = classify(slug)
        if bucket:
            groups[bucket].append((slug, vid))
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                     help="只分群統計、印出結果，不連網、不需要 token、不呼叫任何 YouTube 寫入 API")
    ap.add_argument("--max", type=int, default=40, dest="max_add",
                     help="本次最多新增幾支影片進播放清單（跨三群共用額度）——playlistItems.insert 一次耗 50 quota，"
                          "與 daily_publish 上傳共用同一組每日 10000 quota，設上限防一次跑光擋到當天上架；"
                          "未加完的下次跑（cron 每日一次）自然接續補（items_in 會跳過已加過的，冪等）")
    args = ap.parse_args()

    ledger = load_ledger()
    if not ledger:
        print("[info] STUDIO/uploaded_ledger.json 無資料，無法分群。")
        return 0

    groups = group_videos(ledger)
    total = sum(len(v) for v in groups.values())
    unmatched = len(ledger) - total

    if args.dry_run:
        print("[dry-run] 雙主軸系列播放清單分群（不連網、不呼叫任何 YouTube 寫入 API）")
        for name, items in groups.items():
            print(f"\n[{name}] {len(items)} 支")
            for slug, vid in items[:10]:
                print(f"   - {slug} ({vid})")
            if len(items) > 10:
                print(f"   ... 還有 {len(items) - 10} 支")
        print(f"\n[dry-run] 總計歸類 {total} 支，未命中任何系列關鍵字（不強塞）{unmatched} 支，"
              f"帳上共 {len(ledger)} 支。")
        return 0

    # ---- 正式模式：建立/補充 YouTube 播放清單（force-ssl 權限，真的會寫入頻道）----
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr)
        return 2

    pl_map = {}
    try:
        resp = yt.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for it in resp.get("items", []):
            pl_map[it["snippet"]["title"]] = it["id"]
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 取播放清單失敗：{e}", file=sys.stderr)

    def ensure_playlist(name):
        if name in pl_map:
            return pl_map[name]
        try:
            r = yt.playlists().insert(part="snippet,status", body={
                "snippet": {"title": name, "description": f"量化阿森 ｜ {name} 系列"},
                "status": {"privacyStatus": "public"}}).execute()
            pl_map[name] = r["id"]
            return r["id"]
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 建立清單「{name}」失敗：{e}", file=sys.stderr)
            return None

    def items_in(plid):
        ids = set()
        try:
            tok = None
            while True:
                r = yt.playlistItems().list(part="contentDetails", playlistId=plid,
                                             maxResults=50, pageToken=tok).execute()
                for it in r.get("items", []):
                    ids.add(it["contentDetails"]["videoId"])
                tok = r.get("nextPageToken")
                if not tok:
                    break
        except Exception:
            pass
        return ids

    # ⚠️ 必須先載入既有內容再更新,**不可以從空 dict 開始**:本函式結尾是
    # `PLAYLISTS_STATE.write_text(...)` **整檔覆寫**,而迴圈可能提前 break
    # (--max 用完或撞配額)→ 沒輪到的群組會直接從檔案裡消失。
    # 消費者是 binge_chain(每天 17:05 讀 playlists.json 取 playlist_id 做「接著看下一集」),
    # 而本腳本每週四才跑一次 → 一次截斷會讓那些系列斷鏈整整一週。
    # playlist_engine.py:15 的註解早就警告過這個檔「會被只含 3 個桶的全新 dict 整檔覆寫」。
    try:
        state = json.loads(PLAYLISTS_STATE.read_text(encoding="utf-8")) or {}
        if not isinstance(state, dict):
            state = {}
    except Exception:  # noqa: BLE001
        state = {}
    budget = max(0, args.max_add)
    quota_capped = False
    for name, items in groups.items():
        if not items:
            continue
        plid = ensure_playlist(name)
        if not plid:
            continue
        existing = items_in(plid)
        added = 0
        for slug, vid in items:
            if vid in existing:
                continue
            if budget <= 0:
                quota_capped = True
                break
            try:
                yt.playlistItems().insert(part="snippet", body={"snippet": {
                    "playlistId": plid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
                existing.add(vid)
                added += 1
                budget -= 1
            except Exception as e:  # noqa: BLE001
                print(f"[warn] 加入清單失敗 {slug}：{e}", file=sys.stderr)
                if "quota" in str(e).lower():
                    print("[quota] 停止本輪(冪等,下個配額日接著跑)", file=sys.stderr)
                    # ⚠️ 只 break 內層的話,外層還會走完剩下每個群組,而每組開頭的
                    # ensure_playlist / items_in 都會再打一次 API;而且 quota_capped
                    # 沒被設 → log_ops 會把「被配額截斷的一輪」報成正常完成。
                    quota_capped = True
                    break
        state[name] = {"playlist_id": plid, "video_ids": sorted(existing)}
        print(f"[ok] {name}：清單 {plid}，本次新增 {added} 支，共 {len(existing)} 支。")
        if quota_capped:
            print(f"[info] 已達本次上限 --max {args.max_add}，其餘留待下次補（cron 每日一次會自動接續）。")
            # 撞到 --max 或配額線就整支停:budget 是**跨群組共用**的,再進下一個群組
            # 也插不進任何東西,只會白打一次 ensure_playlist + items_in。
            break

    PLAYLISTS_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_txt = ", ".join(f"{k}+{len(v['video_ids'])}" for k, v in state.items())
    log_ops("播放清單", f"雙主軸分群完成：{summary_txt}" + ("（本次額度用罄，餘量待下次）" if quota_capped else ""))
    print(f"[ok] 已寫入 {PLAYLISTS_STATE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
