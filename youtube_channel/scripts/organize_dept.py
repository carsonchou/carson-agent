#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""organize_dept.py — 【④ 頻道整理部】自動把已上架影片歸入主題播放清單。

依 slug/標題關鍵字把影片分到「網格 / 定投 / 回測數據 / 觀念風控」播放清單；
清單不存在就建立；已在清單內就跳過（去重）。用 force-ssl 權限，真的會寫入頻道。
輸出：STUDIO/REPORTS/{date}_頻道整理.md
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"; LEDGER = STUDIO / "uploaded_ledger.json"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass

# 播放清單規則：標題或 slug 命中關鍵字就歸類（依序，第一個命中者）
BUCKETS = [
    ("網格交易策略", ["網格", "格子", "等差", "等比", "區間", "單邊"]),
    ("定投 DCA", ["定投", "dca", "定期定額", "分批", "攤平"]),
    ("回測與數據", ["回測", "樣本", "過擬合", "夏普", "最大回撤", "勝率", "期望值", "盈虧比"]),
    ("量化觀念與風控", ["複利", "72法則", "風控", "風險", "馬丁", "觀念", "心法"]),
]


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def classify(text):
    t = (text or "").lower()
    for name, kws in BUCKETS:
        if any(k.lower() in t for k in kws):
            return name
    return "量化觀念與風控"  # 預設桶


def main() -> int:
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2
    led = {}
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    except Exception:
        pass
    if not isinstance(led, dict) or not led:
        print("[info] 尚無已上架影片，無需整理。"); return 0

    # 既有播放清單
    pl_map = {}
    try:
        resp = yt.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for it in resp.get("items", []):
            pl_map[it["snippet"]["title"]] = it["id"]
    except Exception as e:
        print(f"[warn] 取播放清單失敗：{e}", file=sys.stderr)

    def ensure_playlist(name):
        if name in pl_map:
            return pl_map[name]
        try:
            r = yt.playlists().insert(part="snippet,status", body={
                "snippet": {"title": name, "description": f"量化阿森 ｜ {name} 系列"},
                "status": {"privacyStatus": "public"}}).execute()
            pl_map[name] = r["id"]; return r["id"]
        except Exception as e:
            print(f"[warn] 建立清單「{name}」失敗：{e}", file=sys.stderr); return None

    def items_in(plid):
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
        except Exception:
            pass
        return ids

    added, skipped, summary = 0, 0, {}
    cache = {}
    for slug, vid in led.items():
        bucket = classify(slug)
        plid = ensure_playlist(bucket)
        if not plid:
            continue
        if plid not in cache:
            cache[plid] = items_in(plid)
        if vid in cache[plid]:
            skipped += 1
            continue
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": plid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            cache[plid].add(vid); added += 1
            summary[bucket] = summary.get(bucket, 0) + 1
        except Exception as e:
            print(f"[warn] 加入清單失敗 {slug}：{e}", file=sys.stderr)

    date = tw_today(); REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ④ 頻道整理報告｜{date}", "",
         f"> 自動歸類播放清單。新加入 {added} 支、已在清單跳過 {skipped} 支。", "", "## 各清單新增"]
    for k, v in summary.items():
        L.append(f"- {k}：+{v}")
    if not summary:
        L.append("-（無新增，影片皆已歸類）")
    L += ["", "## 現有播放清單", *[f"- {n}" for n in pl_map]]
    (REPORTS / f"{date}_頻道整理.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("頻道整理", f"歸類完成 新增{added} 跳過{skipped}")
    print(f"[ok] 頻道整理完成：新增 {added} 支到播放清單，跳過 {skipped} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
