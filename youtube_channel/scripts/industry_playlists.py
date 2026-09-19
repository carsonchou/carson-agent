#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""industry_playlists.py — 把個股影片依【產業】自動歸進 27 條播放清單。

## 為什麼要有這支(跟既有兩支的差別,別再造第四支)
- `build_playlists.py`   依「雙主軸系列」關鍵字互斥分 3 桶,狀態 STUDIO/playlists.json
- `playlist_engine.py`   台股真相實驗室 franchise 4 條清單,狀態 STUDIO/playlist_engine.json
- **本支**               依 twstock 產業別分 27 條,狀態 STUDIO/industry_playlists.json

⚠️ 三支各用各的狀態檔是**刻意的**:`build_playlists.py` 每次執行會用「只含自己 3 個桶」
的全新 dict **整檔覆寫** STUDIO/playlists.json。共用狀態檔會被它砍掉。
(這個坑 playlist_engine.py 的註解已經記過一次,不要重蹈。)

## 為什麼是 27 條而不是 34 條
全市場 1925 檔分 34 個 twstock 產業,但其中 8 個不到 20 檔
(貿易百貨19/電器電纜17/油電燃氣12/橡膠11/水泥7/造紙7/玻璃陶瓷5/農業科技4)。
一條播放清單只放 4 支片沒有意義,故合併成「小型傳產」→ 26 + 1 = **27 條**。
分界線 MERGE_MIN=20 寫在 STUDIO/industry_map.json 產生時,要改就重產那份。

## 🔴 只建有片的清單
不預先建 27 條空清單。個股體檢系列目前只做了 6 支(backlog 還有 1925 檔),
先建 27 條空的等於在頻道上掛 27 個空殼,對觀眾是雜訊、對演算法沒有好處。
**有第一支片才建那條清單**,清單隨系列長大自己長出來。

## 🔴 代號比對必須同時命中代號與股名
只用 `\\d{4}` 抓代號會誤判:實際 slug 裡有「3000元同本金」「回測夏普比3599」
「勝率93卻虧光破產機率公式一秒戳破假象1271」——那些四位數是文案數字與雜湊尾碼,
不是股票代號。故規則是 **代號 AND 股名 都出現**才算命中,寧可漏抓不可錯掛。

## 配額
playlists.insert / playlistItems.insert 各 **50 單位**;list 各 1 單位。
系列做滿 1925 檔時,光加片就要 96,250 單位 → 必須分日跑,用 `--max` 控。
預設 --max 40(2,000 單位),對日配額 >=18,000 是安全的。

用法:
  python scripts/industry_playlists.py                 # dry-run(不連網、不寫入)
  python scripts/industry_playlists.py --apply         # 正式建立/補充
  python scripts/industry_playlists.py --apply --max 40
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 配額計量(全域 patch HttpRequest.execute,只掛一次;壞掉不影響本腳本)
try:
    import quota_meter as _qm; _qm.install()
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
IND_MAP = STUDIO / "industry_map.json"
UPLOADED = STUDIO / "uploaded_ledger.json"
STATE = STUDIO / "industry_playlists.json"      # 本支專用,勿與其他兩支共用
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TW = timezone(timedelta(hours=8))

TITLE_FMT = "{ind}｜個股體檢"
DESC_FMT = ("{ind}類股的逐檔體檢。每支片用公開財報與價格資料做同一套檢查,"
            "不推薦買賣、不喊目標價。\n\n量化阿森 Carson Quant")


def now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S")


def load_json(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def save_state(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


# ── 比對 ────────────────────────────────────────────────────────────────────
_CODE_RE = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")


def match_stock(slug: str, imap: dict) -> tuple[str, str, str] | None:
    """從 slug 找出它在講哪一檔。**代號與股名都要命中**——只看數字會誤判文案數字。

    回 (code, name, industry) 或 None。命中多檔時取股名最長的(最具體)。
    """
    hits = []
    for m in _CODE_RE.finditer(slug):
        code = m.group(1)
        info = imap.get(code)
        if not info:
            continue
        name = (info.get("name") or "").rstrip("*")   # twstock 有「國巨*」這種尾註
        if name and name in slug:
            hits.append((code, name, info["industry"]))
    if not hits:
        return None
    return max(hits, key=lambda h: len(h[1]))


def collect(imap: dict) -> dict[str, list[dict]]:
    """掃已發布影片,分產業。回 {產業: [{code,name,slug,video_id}]}"""
    uploaded = load_json(UPLOADED, {}) or {}
    by_ind: dict[str, list[dict]] = {}
    for slug, vid in uploaded.items():
        if not isinstance(vid, str) or not vid:
            continue
        hit = match_stock(slug, imap)
        if not hit:
            continue
        code, name, ind = hit
        by_ind.setdefault(ind, []).append(
            {"code": code, "name": name, "slug": slug, "video_id": vid})
    for v in by_ind.values():
        v.sort(key=lambda x: x["code"])
    return by_ind


# ── YouTube ─────────────────────────────────────────────────────────────────
def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def my_playlists(yt) -> dict[str, str]:
    """回 {標題: playlistId}。用來認領已存在的清單,避免重跑時建出重複清單。"""
    out, tok = {}, None
    while True:
        r = yt.playlists().list(part="snippet", mine=True, maxResults=50,
                                pageToken=tok).execute()
        for it in r.get("items", []):
            out[it["snippet"]["title"]] = it["id"]
        tok = r.get("nextPageToken")
        if not tok:
            break
    return out


def members(yt, pid: str) -> set[str]:
    """讀回清單真實成員。**冪等判斷一律以 API 為準**,不只信本機狀態檔。"""
    got, tok = set(), None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pid,
                                    maxResults=50, pageToken=tok).execute()
        for it in r.get("items", []):
            vid = (it.get("contentDetails") or {}).get("videoId")
            if vid:
                got.add(vid)
        tok = r.get("nextPageToken")
        if not tok:
            break
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="正式寫入(預設只 dry-run)")
    ap.add_argument("--max", type=int, default=40, help="本次最多加幾支片(控配額)")
    a = ap.parse_args()

    m = load_json(IND_MAP)
    if not m:
        print(f"[!] 找不到 {IND_MAP}。先用 ClawWork venv 從 data_hunter/universe.py 匯出。")
        return 1
    imap = m["map"]
    by_ind = collect(imap)

    total = sum(len(v) for v in by_ind.values())
    print(f"產業對照表:{m['n']} 檔 / {m['n_channels']} 個分類(合併門檻 <{m['merge_min']} 檔)")
    print(f"已發布影片中辨識出個股片:**{total} 支**,落在 {len(by_ind)} 個產業\n")
    if not by_ind:
        print("沒有任何可歸類的個股影片。個股體檢系列還沒開始發布的話這是正常的。")
        return 0

    for ind in sorted(by_ind, key=lambda k: -len(by_ind[k])):
        vids = by_ind[ind]
        print(f"  {ind:12s} {len(vids):>3d} 支  → 清單「{TITLE_FMT.format(ind=ind)}」")
        for v in vids[:6]:
            print(f"      {v['code']} {v['name']:6s} {v['video_id']}  {v['slug'][:44]}")
        if len(vids) > 6:
            print(f"      …另外 {len(vids)-6} 支")

    if not a.apply:
        print(f"\n--dry-run:未連網、未建立任何清單。要正式跑:--apply")
        print(f"預估配額:建 {len(by_ind)} 條清單 × 50 + 加 {total} 支片 × 50 "
              f"= {len(by_ind)*50 + total*50:,} 單位(本次上限 --max {a.max})")
        return 0

    yt = svc()
    have = my_playlists(yt)
    state = load_json(STATE, {}) or {}
    state.setdefault("playlists", {})
    added = created = 0

    for ind in sorted(by_ind, key=lambda k: -len(by_ind[k])):
        title = TITLE_FMT.format(ind=ind)
        pid = have.get(title) or state["playlists"].get(ind, {}).get("id")
        fresh = False
        if not pid:
            r = yt.playlists().insert(
                part="snippet,status",
                body={"snippet": {"title": title, "description": DESC_FMT.format(ind=ind),
                                  "defaultLanguage": "zh-Hant"},
                      "status": {"privacyStatus": "public"}}).execute()
            pid = r["id"]
            created += 1
            fresh = True
            print(f"  ＋建立清單「{title}」 {pid}")
        # 剛建好的清單查 playlistItems 會 404(YouTube 端最終一致性,實測踩到)。
        # 新清單本來就是空的,不必查——順便省配額。
        if fresh:
            cur = set()
        else:
            try:
                cur = members(yt, pid)
            except Exception as e:  # noqa: BLE001
                print(f"      ⚠️ 讀不到既有成員({str(e)[:70]}),本輪跳過此清單以免重複加入")
                continue
        for v in by_ind[ind]:
            if added >= a.max:
                break
            if v["video_id"] in cur:
                continue
            try:
                yt.playlistItems().insert(
                    part="snippet",
                    body={"snippet": {"playlistId": pid,
                                      "resourceId": {"kind": "youtube#video",
                                                     "videoId": v["video_id"]}}}).execute()
                added += 1
                print(f"      + {v['code']} {v['name']} → {title}")
            except Exception as e:  # noqa: BLE001
                print(f"      ✗ {v['code']} {v['name']} 加入失敗:{str(e)[:100]}")
        state["playlists"][ind] = {"id": pid, "title": title,
                                   "n": len(by_ind[ind]), "updated": now()}
        state["updated"] = now()
        save_state(state)          # 逐條落地:中途爆掉不會把已建的清單記錄整批丟掉
        if added >= a.max:
            print(f"\n  已達本次上限 --max {a.max},其餘留待下次(配額保護)")
            break

    state["updated"] = now()
    save_state(state)
    print(f"\n完成:新建 {created} 條清單、加入 {added} 支片。狀態 → {STATE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
