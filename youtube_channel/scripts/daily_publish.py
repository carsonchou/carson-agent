#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_publish.py — 每日全自動上架。

每日挑出尚未上傳的成片(Shorts 優先衝 YPP)，公開上傳 + 設縮圖(若有) +
更新台帳(防重複) + 寫每日上架匯報。受 YouTube API 每日配額限制(約6支)，
遇配額用罄會優雅停止並於明日續傳。

用 youtube.force-ssl(token_manage.json) 一把搞定上傳/縮圖/公開。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import upload_youtube as up  # 重用 metadata 組裝
from ops import log_ops
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"
TOKEN = PROJECT_ROOT / "token_manage.json"
OUTPUT = PROJECT_ROOT / "output"
THUMBS = PROJECT_ROOT / "assets" / "thumbnails"
LEDGER = PROJECT_ROOT / "STUDIO" / "uploaded_ledger.json"
REPORTS = PROJECT_ROOT / "STUDIO" / "REPORTS"
QSCORES = PROJECT_ROOT / "STUDIO" / "quality_scores.json"


_ENGAGE_QS = [
    "你的網格參數都怎麼設？留言區聊聊你的設定 👇",
    "這題你站哪邊？同意的 +1，有不同看法的留言戰起來 👇",
    "你踩過這個坑嗎？分享一下慘痛經驗，我看能不能幫你拆 👇",
    "想看完整實測數據的留言『+1』，夠多我就出深度版 👇",
    "你會怎麼做？留言告訴我，下支可能就拍你的問題 👇",
    "猜猜最後是賺還是賠？留言你的答案，揭曉在置頂 👇",
]


def _post_engage_comment(yt, vid, slug):
    """發布後自動在自己影片留一則引戰提問，衝前一小時互動信號。失敗 soft、不影響上架。
    註：API 不開放『置頂』(Studio 限定)，留言會發、置頂請你在 Studio 點一下。"""
    try:
        q = _ENGAGE_QS[sum(ord(c) for c in vid) % len(_ENGAGE_QS)]
        yt.commentThreads().insert(part="snippet", body={"snippet": {
            "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": q}}}}).execute()
        print(f"[engage] 已留首小時提問：{q[:18]}…")
    except Exception as exc:  # noqa: BLE001
        print(f"[engage] 留言略過（{str(exc)[:50]}）", file=sys.stderr)


def load_quality():
    """讀品質評分：回 ({slug:score}, min_score)。沒檔就回 ({}, 0)＝不擋(fail-open)。"""
    try:
        d = json.loads(QSCORES.read_text(encoding="utf-8"))
        m = {}
        for it in d.get("pending", []) + d.get("published", []):
            if it.get("score") is not None:
                m[it["slug"]] = it["score"]
        return m, int(d.get("min_score", 0))
    except Exception:
        return {}, 0


def tw_today() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def get_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def load_ledger() -> dict:
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_ledger(d: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _norm(slug: str) -> str:
    import re as _re
    s = _re.sub(r"^[SL]_", "", slug)
    return _re.sub(r"\d{3,5}$", "", s)


def _char_sim(a: str, b: str) -> float:
    sa, sb = set(_norm(a)), set(_norm(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def find_candidates(ledger: dict) -> list:
    # Shorts(S_) 優先，其次長片(L_)；過濾已上傳與壞檔
    mp4s = sorted(OUTPUT.glob("S_*.mp4")) + sorted(OUTPUT.glob("L_*.mp4"))
    ledger_slugs = list(ledger.keys())
    out = []
    for f in mp4s:
        slug = f.stem
        if slug in ledger:
            continue
        if f.stat().st_size < 100 * 1024:  # 壞檔/空檔跳過
            continue
        # 近似重複檢查：「決策」系列豁免
        if "決策" not in slug:
            if any(_char_sim(slug, s) >= 0.68 for s in ledger_slugs):
                print(f"[dedup] {slug} 與已上架內容相似，跳過")
                continue
        out.append(slug)
    return out


def upload_one(yt, slug: str, privacy: str) -> str:
    cfg = up.load_channel_config()
    meta = up.assemble_metadata(slug=slug, md_path=OUTPUT / f"{slug}.md", channel_config=cfg, append_affiliate=True)
    meta = up.enforce_youtube_limits(meta)
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta.get("tags", []),
            "categoryId": "28",
            "defaultLanguage": "zh-Hant",
        },
        # Shorts 隱藏設定：不是兒童內容(保留留言/廣告/推薦) + 允許嵌入(站外流量是演算法加分訊號)
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    media = MediaFileUpload(str(OUTPUT / f"{slug}.mp4"), resumable=True, chunksize=4 * 1024 * 1024)
    # Shorts 關鍵：notifySubscribers=False —— Shorts 是冷啟動給陌生人測試，通知訂閱者(衝長片來的)
    # 會讓他們划走→完播率低→演算法判定沒人看→掐死推薦。
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media,
                             notifySubscribers=False)
    resp = None
    while resp is None:
        _status, resp = req.next_chunk()
    vid = resp["id"]
    thumb = THUMBS / f"{slug}.jpg"
    if thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 縮圖設定失敗 {slug}: {exc}", file=sys.stderr)
    return vid


def write_report(date: str, results: list, remaining: int, quota_hit: bool, privacy: str,
                 quarantined: list = None) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    quarantined = quarantined or []
    ok = [r for r in results if r[2] == "ok"]
    lines = [
        f"# 每日自動上架匯報｜{date}",
        "",
        f"> 工作室 · 總監管部門自動產出｜隱私={privacy}",
        "",
        f"## 今日上架 {len(ok)} 支",
        "",
        "| slug | 連結 | 狀態 |",
        "|---|---|---|",
    ]
    for slug, vid, st in results:
        link = f"https://youtu.be/{vid}" if vid else "—"
        lines.append(f"| {slug} | {link} | {st} |")
    lines += [
        "",
        f"## 片庫狀態",
        f"- 尚未上傳的成片庫存：約 **{remaining}** 支（約 {max(1, remaining)//6 + 1} 天上傳量）",
    ]
    if quota_hit:
        lines.append("- ⚠️ 今日 YouTube API 配額用罄，已自動停止，明日續傳。")
    if quarantined:
        lines += ["", f"## ⚠️ 審核部門攔下 {len(quarantined)} 支（未發布，待修）"]
        for slug, reasons in quarantined:
            lines.append(f"- **{slug}**：{'；'.join(reasons)}")
    lines += [
        "",
        "## 達標提醒（YPP）",
        "- 主攻 Shorts 衝 1000 萬觀看／訂閱 1000。Shorts 優先上架中。",
        "- 細部訂閱/觀看時數需接 Analytics scope 才能自動抓。",
        "",
        "> ⚠️ 內容遵守誠信鐵則：不編造損益、不保證收益。",
    ]
    (REPORTS / f"{date}_自動上架.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=6, help="今日最多上傳幾支(配額約6)")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    args = ap.parse_args()

    # 老闆控制台指令（暫停 / 隱私）
    bpath = PROJECT_ROOT / "STUDIO" / "boss_directives.json"
    if bpath.exists():
        try:
            boss = json.loads(bpath.read_text(encoding="utf-8"))
            if boss.get("paused"):
                print("[info] 老闆已暫停全自動，今日不上架。")
                return 0
            if boss.get("privacy") in ("public", "unlisted", "private"):
                args.privacy = boss["privacy"]
        except Exception:
            pass

    import audit_video  # 審核部門
    date = tw_today()
    ledger = load_ledger()
    cands = find_candidates(ledger)

    # 【審核部門】逐支品管+誠信把關 + 品質門檻；收集 PASS 直到達每日上限
    qmap, qmin = load_quality()
    todo, quarantined = [], []
    for slug in cands:
        ok, reasons = audit_video.audit(slug)
        if not ok:
            quarantined.append((slug, reasons))
            print(f"[審核未過] {slug}：{'; '.join(reasons)}")
            continue
        sc = qmap.get(slug)
        if sc is not None and qmin and sc < qmin:   # 品質低於門檻：不發布(只擋已評分的)
            quarantined.append((slug, [f"品質 {sc} 分 < 門檻 {qmin}"]))
            print(f"[品質未達門檻] {slug}：{sc} 分 < {qmin}，暫不發布")
            continue
        todo.append(slug)
        if len(todo) >= args.max:
            break

    if not todo:
        print("[info] 沒有通過審核且待上傳的新成片。")
        write_report(date, [], len(cands), False, args.privacy, quarantined)
        return 0

    yt = get_service()
    results = []
    quota_hit = False
    for slug in todo:
        try:
            vid = upload_one(yt, slug, args.privacy)
            ledger[slug] = vid
            save_ledger(ledger)
            print(f"[ok] {slug} -> https://youtu.be/{vid}")
            _post_engage_comment(yt, vid, slug)  # 首小時互動：自動發一則引戰提問(置頂需你在Studio點)
            results.append((slug, vid, "ok"))
        except HttpError as exc:
            msg = str(exc)
            print(f"[FAIL] {slug}: {msg[:160]}", file=sys.stderr)
            results.append((slug, None, msg[:90]))
            if "quota" in msg.lower() or "exceeded" in msg.lower():
                quota_hit = True
                break
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {slug}: {exc}", file=sys.stderr)
            results.append((slug, None, str(exc)[:90]))

    remaining = len(find_candidates(ledger))
    write_report(date, results, remaining, quota_hit, args.privacy, quarantined)
    n_ok = sum(1 for _, v, s in results if s == "ok")
    extra = "（配額用罄,明日續）" if quota_hit else ""
    log_ops("上架部門", f"上架{n_ok}支 隔離{len(quarantined)}支 剩庫存{remaining}{extra}")
    print(f"\n完成：上傳 {n_ok} 支，剩餘庫存 {remaining} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
