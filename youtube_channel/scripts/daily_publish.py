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
from studio_common import save_json_atomic, load_json_safe
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
PUBLISH_PRIORITY = PROJECT_ROOT / "STUDIO" / "publish_priority.json"  # 選填：礦脈/新片優先旗標(slug清單)
PUBLISH_SKIP = PROJECT_ROOT / "STUDIO" / "publish_skip.json"  # 選填：跳過發布清單({slug:理由})，可逆
IG_LEDGER = PROJECT_ROOT / "STUDIO" / "ig_ledger.json"
FB_LEDGER = PROJECT_ROOT / "STUDIO" / "fb_ledger.json"
THREADS_LEDGER = PROJECT_ROOT / "STUDIO" / "threads_ledger.json"
SHORT_TO_LONG = PROJECT_ROOT / "STUDIO" / "short_to_long.json"  # 選填：slug→長片slug或youtu.be，短→長導流
SHORT_TO_SHORT = PROJECT_ROOT / "STUDIO" / "short_to_short.json"  # 選填：本機待上架短片slug→已發布短片slug，短→短同系列連看

# Shorts 專用 hashtag：描述不含 #shorts 時補進去，讓 YouTube 歸類進 Shorts shelf。
# 注意：upload_one 以字串串接（description + _SHORTS_HASHTAGS），故此處必須是「字串」不可為 list，
# 否則 str + list 會 TypeError（這正是先前 NameError／崩潰的修補）。
_SHORTS_HASHTAGS = "\n\n" + " ".join(["#Shorts", "#量化交易", "#Pionex", "#自動交易"])


def _long_link_for(slug: str, cfg: dict, ledger: dict) -> str:
    """Shorts 導流連結：優先 short_to_long.json 指定的對應長片，否則退回頻道連結（軟導流）。"""
    try:
        if SHORT_TO_LONG.exists():
            m = json.loads(SHORT_TO_LONG.read_text(encoding="utf-8"))
            tgt = (m.get(slug) or "").strip()
            if tgt.startswith("http"):
                return tgt
            if tgt and ledger.get(tgt):  # tgt 是已上架長片 slug
                return f"https://youtu.be/{ledger[tgt]}"
    except Exception:  # noqa: BLE001
        pass
    handle = (cfg.get("channel_handle") or "").lstrip("@")
    return f"https://www.youtube.com/@{handle}" if handle else ""


def _short_link_for(slug: str, ledger: dict) -> str:
    """Short→Short 同系列/同題材連看：short_to_short.json 指定的對應「已發布」Short，
    查無或該片尚未真的在 ledger 裡（防資料過期）就回空字串——不像 _long_link_for 有
    頻道連結退路，因為這是加購欄位，沒有就乾脆不加這行，不製造死連結。"""
    try:
        if SHORT_TO_SHORT.exists():
            m = json.loads(SHORT_TO_SHORT.read_text(encoding="utf-8"))
            tgt = (m.get(slug) or "").strip()
            if tgt and ledger.get(tgt):  # tgt 必須是已上架 Short slug，否則不給連結
                return f"https://youtu.be/{ledger[tgt]}"
    except Exception:  # noqa: BLE001
        pass
    return ""


_ENGAGE_QS = [
    # 互動型（讓人分享自己的設定/數據）
    "你的網格參數都怎麼設？留言區聊聊你的設定 👇",
    "想要完整回測數據？留言『數據』我私你 👇",
    "想看完整實測表？留言『表』我發你 👇",
    "同意的留言『+1』，不同意的說說你怎麼看 👇",
    "你現在的策略最大回撤是多少？留下數字，我看有沒有辦法壓低",
    "說說你踩過最貴的坑，讓大家參考，一起少虧點 💀",
    "這招你知道幾分？0-10 分留個數字，我統計結果下支公布",
    # 引戰型（製造討論、拉留言數）
    "這題你站哪邊？同意的 +1，有不同看法的留言戰起來 👇",
    "你踩過這個坑嗎？分享一下慘痛經驗，我看能不能幫你拆 👇",
    "你覺得網格最大的風險是什麼？A 爆倉 / B 套牢 / C 手續費吃光，留字母",
    "有沒有人靠這個真的賺到的？說說你的參數，不說數字沒人信 👇",
    # 懸念型（轉換成訂閱者）
    "下支我要公開一個 90% 人都設錯的參數——先追蹤，不然找不回來 👇",
    "想看完整實測數據的留言『+1』，夠多我就出深度版 👇",
    "你會怎麼做？留言告訴我，下支可能就拍你的問題 👇",
    "猜猜最後是賺還是賠？留言你的答案，揭曉在置頂 👇",
    # 台股/定投題材(對齊主軸)
    "你定投的是 0050 還是 0056？留言告訴我，下支我幫你回測哪個十年贏 👇",
    "台股這位置你是加碼、抱著、還是跑？A 加 / B 抱 / C 跑，留字母 👇",
    "你存股被套過最深幾成？留個數字，讓新手知道這條路真的會痛 👇",
    "除權息你都參加還是避開？留言你的做法，我用數據幫你驗對不對 👇",
    # AI 題材
    "你敢讓 AI 幫你選股/下單嗎？敢的 +1，不敢的說說你怕什麼 👇",
    "你一個月花多少錢在 AI 工具？留個數字，我出一支怎麼省的 👇",
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


def load_quality(_retried: bool = False):
    """讀品質評分：回 ({slug:score}, min_score)。
    fail-CLOSED：讀不到檔就先『觸發一次評分』再重讀；仍拿不到回空 map（main 會據此擋下未評分片，
    不再 fail-open 放行）。沿用『只收有效分數(score 非 None)』，未評分片本來就不會進 map。"""
    try:
        if not QSCORES.exists():
            raise FileNotFoundError(str(QSCORES))
        d = json.loads(QSCORES.read_text(encoding="utf-8"))
        m = {}
        for it in (d.get("pending") or []) + (d.get("published") or []):
            if isinstance(it, dict) and it.get("slug") and it.get("score") is not None:
                m[it["slug"]] = it["score"]
        return m, int(d.get("min_score", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        # 檔缺／壞檔：先觸發一次評分再重讀（只重試一次，避免遞迴爆掉）。
        if not _retried:
            try:
                import quality_score as _qs
                _qs.scan(rescore_ai=False)
                log_ops("上架部門", "quality_scores 缺失／壞檔，已觸發評分後重讀")
            except Exception as _e:  # noqa: BLE001
                log_ops("上架部門", f"觸發評分失敗（仍 fail-closed 擋未評分片）：{str(_e)[:60]}")
            return load_quality(_retried=True)
        log_ops("上架部門", f"品質評分讀取失敗，fail-closed 擋下未評分片：{str(exc)[:60]}")
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
    return load_json_safe(LEDGER, default={})


def save_ledger(d: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    save_json_atomic(LEDGER, d)


def _norm(slug: str) -> str:
    import re as _re
    s = _re.sub(r"^[SL]_", "", slug)
    return _re.sub(r"\d{3,5}$", "", s)


def _char_sim(a: str, b: str) -> float:
    sa, sb = set(_norm(a)), set(_norm(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def _load_priority_set() -> set:
    """讀『礦脈/新片優先』旗標(STUDIO/publish_priority.json，選填，查無就回空集合＝行為不變)。
    只影響排序位置，不繞過下游品質門檻/audit——沒分數的片仍會被 main() fail-closed 隔離。"""
    d = load_json_safe(PUBLISH_PRIORITY, default={}) or {}
    slugs = d.get("slugs") if isinstance(d, dict) else d
    if isinstance(slugs, dict):
        return set(slugs.keys())
    if isinstance(slugs, list):
        return set(slugs)
    return set()


def _load_skip_set() -> set:
    """讀『跳過發布』清單(STUDIO/publish_skip.json，選填，查無就回空集合＝行為不變)。
    可逆：把 slug 從 json 移除即恢復候選資格，不動實際 mp4 檔案。"""
    d = load_json_safe(PUBLISH_SKIP, default={}) or {}
    slugs = d.get("slugs") if isinstance(d, dict) else d
    if isinstance(slugs, dict):
        return set(slugs.keys())
    if isinstance(slugs, list):
        return set(slugs)
    return set()


def find_candidates(ledger: dict) -> list:
    # 高分先發：Shorts(衝YPP)優先，組內依品質分數由高到低；其次長片同理。
    qmap, _ = load_quality()
    priority = _load_priority_set()
    skip = _load_skip_set()
    shorts, longs, mtimes = [], [], {}
    for f in list(OUTPUT.glob("S_*.mp4")) + list(OUTPUT.glob("L_*.mp4")):
        slug = f.stem
        if slug.endswith("_ytcta"):
            continue  # IG/TikTok 片尾卡衍生檔(append_yt_cta 產),原片多半已上 YT,當新片發=重複發布已上線影片
        if slug in ledger or slug in skip:
            continue
        if f.stat().st_size < 100 * 1024:
            continue
        mtimes[slug] = f.stat().st_mtime
        (shorts if slug.startswith("S_") else longs).append(slug)

    def _key(s: str):
        # 有分數：一律照真分數 desc 排(維持原行為，已評高分的真好片永遠排該有的位置，
        # 優先旗標不會讓分數更低的片插隊到它前面)。
        # 沒分數(新產片還沒被 quality_score.py 掃到，qmap 裡連 key 都沒有)：不再預設 0分
        # (0 比任何已評分片、甚至已評的爛片都低，會被『埋』在候選清單最後)；改成獨立一群，
        # 該群整體排在所有『已評分』片之後(功能上無差別——main() 對沒分數的片一律 fail-closed
        # 隔離，不影響誰能實際發布)，但群內部依『優先旗標→mtime新到舊』排序，取代原本的檔案系統
        # 隨機順序，讓 winner_vein/新片在報表與審核序中最先被看見、不被舊庫存埋沒。
        score = qmap.get(s)
        has_score = score is not None
        return (
            0 if has_score else 1,
            -(float(score)) if has_score else 0.0,
            0 if s in priority else 1,
            -mtimes.get(s, 0.0),
        )

    shorts.sort(key=_key)
    longs.sort(key=_key)
    return shorts + longs


def _crosspost_one(slug: str, ledger_path: Path, module_name: str, tag: str) -> None:
    """跨發到單一平台(非致命;獨立台帳防重發)。IG/FB/Threads 共用此邏輯，各自失敗互不影響。"""
    try:
        led = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    except Exception:
        led = {}
    if slug in led:
        return
    try:
        mod = __import__(module_name)
        mid = mod.publish(slug)
        if mid:
            led[slug] = mid
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{tag}] 已發布 {slug} -> {mid}")
    except Exception as _e:  # noqa: BLE001
        print(f"[warn] {tag} 跨發失敗 {slug}: {_e}", file=sys.stderr)


def _ig_crosspost(slug: str) -> None:
    """把一支 Short 跨發到 IG Reels + FB Reels + Threads(公網影片庫存有值才跨發，各平台各自缺 key 自跳，互不影響)。"""
    import os
    base = os.environ.get("IG_VIDEO_BASE", "").strip()
    if not base:
        tf = PROJECT_ROOT / "STUDIO" / "tunnel_url.json"
        if tf.exists():
            try:
                base = json.loads(tf.read_text(encoding="utf-8")).get("base", "")
            except Exception:
                base = ""
    if not base:
        return
    # IG 為主(原行為);FB/Threads 是加購，各自缺 key 自己在 publish() 裡優雅跳過
    _crosspost_one(slug, IG_LEDGER, "ig_reels_upload", "ig")
    _crosspost_one(slug, FB_LEDGER, "fb_reels_upload", "fb")
    _crosspost_one(slug, THREADS_LEDGER, "threads_upload", "threads")


def upload_one(yt, slug: str, privacy: str) -> str:
    cfg = up.load_channel_config()
    meta = up.assemble_metadata(slug=slug, md_path=OUTPUT / f"{slug}.md", channel_config=cfg, append_affiliate=True)
    meta = up.enforce_youtube_limits(meta)
    is_short = slug.startswith("S_")

    # Shorts 必須有 #Shorts 才能進 Shorts shelf（YouTube 分類依據）
    if is_short and "#shorts" not in meta["description"].lower():
        meta["description"] = (meta["description"] + _SHORTS_HASHTAGS)[:5000]

    # 短→長導流：Shorts 描述頂端掛長片/頻道連結（建立連看閉環、把 Shorts 流量沉澱）
    if is_short:
        _ledger_now = load_ledger()
        _link = _long_link_for(slug, cfg, _ledger_now)
        if _link and _link not in meta["description"]:
            meta["description"] = (f"📺 完整策略拆解看這裡 👉 {_link}\n\n" + meta["description"])[:5000]
        # 短→短同系列/同題材連看：EP 實測系列接上一集、其餘接最像的已發布 Short（short_to_short.json，
        # 選填，查無就跳過不加行，不破壞上面既有的短→長導流）
        _slink = _short_link_for(slug, _ledger_now)
        if _slink and _slink not in meta["description"]:
            meta["description"] = (f"🔁 接續看同系列 👉 {_slink}\n\n" + meta["description"])[:5000]

    # Shorts 用 #Shorts 加進標題尾端（字數允許時）；長片 categoryId 用教育(27)
    title = meta["title"]
    if is_short and "#shorts" not in title.lower() and len(title) <= 90:
        title = title + " #Shorts"
    category_id = "28" if is_short else "27"  # Shorts=科技(28), Long=教育(27)

    body = {
        "snippet": {
            "title": title,
            "description": meta["description"],
            "tags": meta.get("tags", []),
            "categoryId": category_id,
            "defaultLanguage": "zh-Hant",
        },
        # 不是兒童內容(保留留言/廣告/推薦) + 允許嵌入(站外流量是演算法加分訊號)
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    # 檔名 SEO：送給 YouTube 的檔名用關鍵字名(非內部 slug)。零成本弱訊號優化;失敗降級回原檔,絕不擋上傳。
    _seo_mp4 = up.seo_asset_name(meta.get("title", slug), meta.get("tags"), "mp4", slug)
    _up_path, _cleanup_mp4 = up.link_as(OUTPUT / f"{slug}.mp4", _seo_mp4)
    resp = None
    try:
        media = MediaFileUpload(str(_up_path), resumable=True, chunksize=4 * 1024 * 1024)
        # Shorts 冷啟動給陌生人測試：notifySubscribers=False（通知訂閱者會拉高划走率→掐死推薦）
        # 長片 notifySubscribers=True：訂閱者觀看可累積觀看時數 + 訂閱信號
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media,
                                 notifySubscribers=not is_short)
        while resp is None:
            _status, resp = req.next_chunk()
    finally:
        _cleanup_mp4()   # 清關鍵字名硬連結(不動原 mp4);即使 MediaFileUpload/insert 拋例外也清
    vid = resp["id"]
    # 精準 SRT 字幕（演算法判主題＋中文金融術語正確；非致命）
    try:
        import make_video as _mv
        _srt = _mv.write_srt_for_slug(slug)
        if _srt and Path(_srt).exists():
            up.upload_captions(yt, vid, _srt,
                               upload_name=up.seo_asset_name(meta.get("title", slug), meta.get("tags"), "srt", slug))
    except Exception as _e:  # noqa: BLE001
        print(f"[caption] 字幕步驟略過（{str(_e)[:60]}）", file=sys.stderr)
    if slug.startswith(("L_", "S_")) and not (THUMBS / f"{slug}.jpg").exists():
        try:  # 高質感封面：科技機器人/真人手機(依主題自動選)+AI生圖+金字鉤子，失敗退回設計卡
            import make_cover as _mc
            _mc.make_cover(slug, meta.get("title", slug))
        except Exception as _e:
            print(f"[warn] make_cover 失敗，退回 make_thumbnails：{_e}", file=sys.stderr)
            try:
                import make_thumbnails as _mt
                _mt.make_auto(slug, meta.get("title", slug))
            except Exception as _e2:
                print(f"[warn] 自動生縮圖失敗 {slug}: {_e2}", file=sys.stderr)
    thumb = THUMBS / f"{slug}.jpg"
    if thumb.exists():
        _seo_jpg = up.seo_asset_name(meta.get("title", slug), meta.get("tags"), "jpg", slug)
        _tp, _cleanup_jpg = up.link_as(thumb, _seo_jpg)
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(_tp), mimetype="image/jpeg")).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 縮圖設定失敗 {slug}: {exc}", file=sys.stderr)
        finally:
            _cleanup_jpg()   # 清關鍵字名硬連結(不動原 jpg)
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
    ap.add_argument("--ig-max", type=int, default=8, help="每輪最多跨發幾支到 IG Reels")
    ap.add_argument("--no-ig", action="store_true", help="本輪不跨發 IG")
    args = ap.parse_args()

    # 老闆控制台指令（暫停 / 隱私 / 發布時段）
    bpath = PROJECT_ROOT / "STUDIO" / "boss_directives.json"
    if bpath.exists():
        try:
            boss = json.loads(bpath.read_text(encoding="utf-8"))
            if boss.get("paused"):
                print("[info] 老闆已暫停全自動，今日不上架。")
                return 0
            if boss.get("privacy") in ("public", "unlisted", "private"):
                args.privacy = boss["privacy"]
            # 黃金時段控制：publish_hours 設哪些小時（台灣時間）才允許發布
            # 建議設 [12,13,20,21,22]，對應午休 + 晚間高峰；未設則不限制
            allowed_hours = boss.get("publish_hours")
            if allowed_hours and not getattr(args, "force", False):
                tw_hour = datetime.now(timezone(timedelta(hours=8))).hour
                if tw_hour not in allowed_hours:
                    print(f"[info] 現在台灣時間 {tw_hour} 時，不在發布時段 {allowed_hours}，跳過。")
                    log_ops("上架部門", f"非發布時段（{tw_hour}時），跳過")
                    return 0
        except Exception:
            pass

    import audit_video  # 審核部門
    date = tw_today()
    ledger = load_ledger()
    cands = find_candidates(ledger)

    # 【審核部門】逐支品管+誠信把關 + 品質門檻(fail-CLOSED)；收集 PASS 直到達每日上限
    qmap, qmin = load_quality()
    # 硬地板：任何情況低於 FLOOR 一律不發；匯入失敗也要有保底地板，絕不放行到 0。
    try:
        from quality_score import FLOOR as _FLOOR
        floor = int(_FLOOR)
    except Exception:  # noqa: BLE001
        floor = 60
    todo, quarantined = [], []
    for slug in cands:
        ok, reasons = audit_video.audit(slug)
        if not ok:
            quarantined.append((slug, reasons))
            print(f"[審核未過] {slug}：{'; '.join(reasons)}")
            continue
        sc = qmap.get(slug)
        # fail-CLOSED ①：未評分(None／查無)一律不發（不再 fail-open 漏過）。
        if sc is None:
            quarantined.append((slug, ["未評分（無有效品質分）— fail-closed 不發，待重評"]))
            print(f"[未評分] {slug}：無品質分，暫不發布（fail-closed）")
            continue
        # fail-CLOSED ②：分數型別意外也擋（防呆，不讓下面比較拋例外）。
        try:
            scv = float(sc)
        except (TypeError, ValueError):
            quarantined.append((slug, [f"品質分數異常（{sc!r}）— fail-closed 不發"]))
            print(f"[分數異常] {slug}：{sc!r} 非數值，暫不發布")
            continue
        # fail-CLOSED ③：低於硬地板 FLOOR 一律不發（qmin=0 也不再等於放行）。
        if scv < floor:
            quarantined.append((slug, [f"品質 {sc} 分 < 硬地板 {floor}"]))
            print(f"[低於地板] {slug}：{sc} 分 < 地板 {floor}，不發布")
            continue
        # 較嚴門檻：min_score 若設得比地板高，從嚴（保留原本較嚴門檻邏輯）。
        if qmin and scv < qmin:
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
    ig_done = 0
    for slug in todo:
        try:
            vid = upload_one(yt, slug, args.privacy)
            ledger[slug] = vid
            save_ledger(ledger)
            print(f"[ok] {slug} -> https://youtu.be/{vid}")
            _post_engage_comment(yt, vid, slug)  # 首小時互動：自動發一則引戰提問(置頂需你在Studio點)
            results.append((slug, vid, "ok"))
            if slug.startswith("S_") and not args.no_ig and ig_done < args.ig_max:
                _ig_crosspost(slug)
                ig_done += 1
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
