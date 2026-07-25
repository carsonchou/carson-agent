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
import shutil
import subprocess
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
# 個股體檢系列 EP 編號的**單一真相來源**：{slug: ep_n}。EP 號在「發布時」按「已發布集數 max+1」
# 編定(見 _next_checkup_ep / _apply_checkup_ep),不再於種題/產製階段寫死——那會讓 EP 號跟著
# 「種題進度」跳號(觀眾看到 EP1→下一支卻是 EP40)。這支帳本讓「發一支進一號、永不跳」可確定性推導,
# 且不受 quality_scores 裡殘留的舊 EP 數字污染(存量待發片的 title 仍帶舊號)。
CHECKUP_EP_LEDGER = PROJECT_ROOT / "STUDIO" / "checkup_ep_ledger.json"
PUBLISH_PRIORITY = PROJECT_ROOT / "STUDIO" / "publish_priority.json"  # 選填：礦脈/新片優先旗標(slug清單)
PUBLISH_SKIP = PROJECT_ROOT / "STUDIO" / "publish_skip.json"  # 選填：跳過發布清單({slug:理由})，可逆
IG_LEDGER = PROJECT_ROOT / "STUDIO" / "ig_ledger.json"
FB_LEDGER = PROJECT_ROOT / "STUDIO" / "fb_ledger.json"
THREADS_LEDGER = PROJECT_ROOT / "STUDIO" / "threads_ledger.json"
TIKTOK_LEDGER = PROJECT_ROOT / "STUDIO" / "tiktok_ledger.json"
TIKTOK_UPLOAD_SCRIPT = PROJECT_ROOT / "scripts" / "tiktok_upload.py"
# tiktok_upload.py 需 playwright，.venv 沒裝 → 一律走「系統 python」，路徑寫法比照
# local_cron.py 的 SYS_PY 常數(找不到才用 which 後援，絕不硬編死路徑導致找不到就整段爆掉)。
_SYS_PY_HARDCODED = Path(r"C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe")
SHORT_TO_LONG = PROJECT_ROOT / "STUDIO" / "short_to_long.json"  # 選填：slug→長片slug或youtu.be，短→長導流
SHORT_TO_SHORT = PROJECT_ROOT / "STUDIO" / "short_to_short.json"  # 選填：本機待上架短片slug→已發布短片slug，短→短同系列連看

# Shorts 專用 hashtag：描述不含 #shorts 時補進去，讓 YouTube 歸類進 Shorts shelf。
# 注意：upload_one 以字串串接（description + _SHORTS_HASHTAGS），故此處必須是「字串」不可為 list，
# 否則 str + list 會 TypeError（這正是先前 NameError／崩潰的修補）。
_SHORTS_HASHTAGS = "\n\n" + " ".join(["#Shorts", "#量化交易", "#Pionex", "#自動交易"])

# 訂閱鉤標準化：價值承諾句，不是光禿禿求訂閱(誠信鐵則：不誇大、不保證收益)。
# 2026-07-15 競品逆向:頭部頻道(股添樂/股乾爹/阿格力)簡介第一句無例外都是 credential 背書,
# 直接回答「憑什麼信你」——我們的 credential 是真的:全市場 1841 檔回測引擎(對手沒有)。
_SUBSCRIBE_HOOK = ("🔔 我用 Python 把台股 1841 檔全部跑過回測——訂閱看每週全市場實測、"
                   "拆穿話術陷阱，不誇大只看真數據")
# 一鍵訂閱參數：帶 ?sub_confirmation=1 的頻道連結會直接跳出訂閱確認框，省掉「找頻道→再點訂閱」
# 兩步流失。2026-07-17 加：訂閱轉換是 YPP 唯一瓶頸(46/1000)，描述那句 credential 本來只是
# 不可點的純文字，等於叫人訂閱卻不給按鈕。
_SUB_CONFIRM_PARAM = "?sub_confirmation=1"


def _subscribe_hook(cfg: dict | None = None) -> str:
    """訂閱鉤文案；有 channel_handle 就附一鍵訂閱連結，取不到就退純文字(fail-open，不擋發布)。"""
    handle = ((cfg or {}).get("channel_handle") or "").lstrip("@")
    if not handle:
        return _SUBSCRIBE_HOOK
    return f"{_SUBSCRIBE_HOOK}\n👉 https://www.youtube.com/@{handle}{_SUB_CONFIRM_PARAM}"


# ── 系列化訂閱鉤(2026-07-19 訂閱轉換診斷落地)────────────────────────────────
# 通用訂閱鉤講「每週全市場實測」是泛泛承諾;連載片(如台股真相實驗室)應該給**這個系列**的具體
# 訂閱理由——「訂了會固定拿到什麼」。數字(還有幾組沒拆)必須真實可查、不可變空頭誘餌:直接複用
# ep0_engine 已做過誠信稽核的『未拍真回測組數』(語意去重後的保守下界,used_keys ∪ episodes[].key
# 都算進去,不會灌水),算不出來就 fail-open 退通用鉤,絕不擋發布、絕不編數字。
_TW_LAB_SERIES_NAME = "台股真相實驗室"


def _tw_lab_series_hook(cfg: dict | None = None) -> str | None:
    """台股真相實驗室專屬訂閱鉤;存量算不出來(<1 組)回 None → 呼叫端退通用鉤。"""
    try:
        import ep0_engine
        inv = ep0_engine.inventory("tw_lab") or {}
        ready = int(inv.get("ready", 0) or 0)
        if ready < 1:
            return None
        base = (f"🔔 訂閱追《{_TW_LAB_SERIES_NAME}》——我手上還有 {ready} 組已經跑好的台股真回測還沒拆，"
                f"一集拆一組，訂閱才收得到下一組數字，不誇大只看真數據")
        handle = ((cfg or {}).get("channel_handle") or "").lstrip("@")
        if handle:
            return f"{base}\n👉 https://www.youtube.com/@{handle}{_SUB_CONFIRM_PARAM}"
        return base
    except Exception:  # noqa: BLE001
        return None


def _ensure_subscribe_hook(description: str, cfg: dict | None = None,
                           slug: str = "", title: str = "") -> str:
    """確保每支發布片描述都有清楚的『訂閱理由』句(價值承諾，非空喊)+ 一鍵訂閱連結。

    2026-07-19:連載片給**系列專屬**訂閱鉤(具體理由=這系列還有幾組真回測沒拆,訂閱才收得到);
    非連載片維持通用 credential 鉤。系列鉤的數字由 ep0_engine 誠信稽核過的存量算出,fail-open。

    🔴 2026-07-17 修去重誤判：舊碼用 `if "訂閱" in description` 去重，但描述裡含逐字稿——
    同日 produce_batch 的 CTA 改成「一律明講『訂閱』二字」後，**每支片的描述都會命中這個判斷**，
    導致這句 credential 背書(競品逆向驗證過:頭部頻道簡介第一句無例外都是 credential)
    永遠不再被加上 = 好心的去重直接廢掉整個機制。改成比對「一鍵訂閱連結」是否已存在，
    那才是這個函式真正負責產出的東西。"""
    hook = None
    if _TW_LAB_SERIES_NAME in (slug + " " + title) or "臺股真相實驗室" in (slug + " " + title):
        hook = _tw_lab_series_hook(cfg)
    if not hook:
        hook = _subscribe_hook(cfg)
    if (_SUB_CONFIRM_PARAM in description or _SUBSCRIBE_HOOK in description
            or f"訂閱追《{_TW_LAB_SERIES_NAME}》" in description):
        return description
    return f"{description}\n\n{hook}"


def _short_to_long_mapped(slug: str, ledger: dict) -> str:
    """查 short_to_long.json 是否有『真配對』的長片連結(不含頻道退路)。
    拆出來供 _long_link_for(描述用，允許退回頻道連結)與導流留言(只在真有配對時才提長片，
    否則改用訂閱鉤，避免留言講「完整拆解看這裡」卻只是連去頻道首頁的空話)共用。"""
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
    return ""


def _long_link_for(slug: str, cfg: dict, ledger: dict) -> str:
    """Shorts 導流連結：優先 short_to_long.json 指定的對應長片，否則退回頻道連結（軟導流）。"""
    mapped = _short_to_long_mapped(slug, ledger)
    if mapped:
        return mapped
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
    # 2026-07-18 移除 2 句空頭誘餌:「留言『數據』我私你」「留言『表』我發你」——都承諾私訊交付
    # 回測數據/實測表,但交付機制從未運作(comment_dept:293 自認 tg_leads 累計 0 筆)、且很多片
    # 根本沒真數據可給=用**不存在的**東西當誘餌(同 produce_batch CTA 池那句)。其餘互動句(設定/
    # 回撤/踩坑/評分)純誘導討論、無交付承諾,保留。
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
    # 2026-07-17:原文寫「先追蹤，不然找不回來」——這區塊的目的就是轉訂閱，卻用 IG 語彙
    # 講「追蹤」，而 YouTube 按鈕上寫的是「訂閱」，觀眾不知道要按哪個鍵(同批修正見
    # produce_batch._CTA_WORD_FIXES)。
    "下支我要公開一個 90% 人都設錯的參數——先訂閱，不然找不回來 👇",
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


def _engage_comment_text(slug: str, vid: str, cfg: dict, ledger: dict) -> str:
    """組『提問 + 導流』留言文案：Shorts 若有 short_to_long.json 真配對的長片就導去長片，
    否則(含長片本身)接訂閱鉤——不用 _long_link_for 的頻道退路，避免留言講「完整拆解看這裡」
    卻只是連去頻道首頁的空話(那個退路留給描述欄用即可)。"""
    q = _ENGAGE_QS[sum(ord(c) for c in vid) % len(_ENGAGE_QS)]
    if slug.startswith("S_"):
        link = _short_to_long_mapped(slug, ledger)
        if link:
            return f"{q}\n\n📺 想看完整拆解？我把長片連結放這 👉 {link}"
    return f"{q}\n\n{_subscribe_hook(cfg)}"


def _post_engage_comment(yt, vid, slug, ledger=None):
    """發布後自動在自己影片留一則導流留言(提問 + 對應長片連結或訂閱鉤)，衝前一小時互動信號
    順便把觀眾往下一步導。失敗 soft、不影響上架。
    註(已查證 2026-07)：YouTube Data API v3 沒有『置頂留言』端點——commentThreads/comments
    資源(insert/list/update)都沒有 isPinned 之類可寫欄位，置頂是 YouTube Studio 網頁/App
    限定操作，官方文件(developers.google.com/youtube/v3/docs/commentThreads)未提供對應方法。
    退而求其次：把留言內容本身的導流做到最好，置頂仍要你自己在 Studio 點一下。"""
    try:
        text = _engage_comment_text(slug, vid, up.load_channel_config(), ledger or {})
        yt.commentThreads().insert(part="snippet", body={"snippet": {
            "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": text}}}}).execute()
        print(f"[engage] 已留導流留言：{text[:24]}…")
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


# ── 系列連載完整性(2026-07-17 建)──────────────────────────────────────────
# 為什麼要有這道:find_candidates 只照「品質分數 desc」排,對「同一個系列的片該按集數順序發」
# 完全無知。實測(2026-07-17 庫存複驗)兩個真實破口:
#   ①【個股體檢】EP1(94)/EP2(84)/EP5(94) 三支待發、一支都還沒發過。照純分數排,佇列實際順序是
#     EP5 → EP1 → EP2(EP5 與 EP1 同 94 分,由 mtime 新到舊決勝,EP5 較新故插到最前)——
#     系列會用「EP5」開播,首集就斷裂。
#   ②【台股真相實驗室】EP1-EP8 已發布,待發的 EP8(94) 是**第二支 EP8**(集數撞號),
#     照純分數排它會排在 EP9(86)/EP10(79) 前面先發 → 觀眾看到集數倒退。
# 系列的追更動機是訂閱的核心引擎(EP.0 開播預告 3-5% vs Shorts 0.062%),集數斷裂/跳號/撞號
# 直接殺掉「訂了會固定拿到下一集」這個承諾。
#
# 這道只做兩件事,兩件都是「暫緩(hold)」不是「丟棄」——片子留在 output/ 原地不動,
# 下一輪 daily_publish 重算候選時,前一集發掉了後一集自然遞補:
#   ①集數已發布過 → 不重發(擋撞號)
#   ②同系列只放行「已達品質門檻的集數裡編號最小的那一支」(擋跳號)
# ⚠️ 刻意只讓「已達門檻(score >= min_score)」的集數擋順序:台股真相實驗室 EP3(70分,reject)
#    永遠不會被 main() 放行,若讓它擋順序會把 EP9/EP10 永久餓死。品質 gate 不放寬,
#    但也不讓「發不出去的片」變成整個系列的路障。
# 全程 fail-open:任何例外一律回原清單(照舊行為),絕不因為這道新閘讓產線停擺。
_EP_NUM_RE = __import__("re").compile(r"EP\s*\.?\s*(\d{1,3})(?!\d)")
_CK_EP_RE = __import__("re").compile(r"個股體檢\s*EP\s*\.?\s*(\d{1,3})(?!\d)")


def _slug_titles() -> dict:
    """{slug: title} — 讀 quality_scores 的 published+pending(已發布片的標題只有這裡有)。"""
    d = load_json_safe(QSCORES, default={}) or {}
    out = {}
    for it in (d.get("published") or []) + (d.get("pending") or []):
        if isinstance(it, dict) and it.get("slug") and it.get("title"):
            out[it["slug"]] = it["title"]
    return out


def _tw_lab_member_slugs() -> set:
    """台股真相實驗室的成員名單(權威來源=引擎自己的 state)。
    不能只靠標題認系列:實測 19 支裡有 7 支標題根本沒帶「真相實驗室」四個字
    (如「EP3｜大盤長抱 vs 跌破年線就跑…」),只比對標題會漏認一半成員。"""
    d = load_json_safe(PROJECT_ROOT / "STUDIO" / "tw_lab_state.json", default={}) or {}
    return {e.get("slug") for e in (d.get("episodes") or []) if isinstance(e, dict) and e.get("slug")}


# ── 個股體檢連載：EP 編號在「發布時」按已發布集數 +1 編定 ─────────────────────────
# 為什麼在這裡編號、而不是種題/產製時編：EP 號原本由 stock_checkup_daily._next_ep_number 在
# 「種題」當下寫死(掃題庫最大號 +1),而題庫每天種一檔就 +1、種到 EP39,但實際只發布了 EP1、EP7
# ——EP 號跟著「種題進度」跳號,觀眾看到 EP1 下一支卻可能是 EP40,連載追劇/播放清單全斷。
# 改成：種題/產製一律**不寫 EP 數字**(只留系列名「個股體檢」),發布時才按「已發布 EP max+1」掛號,
# 於是「發一支進一號、永不跳」。narration 早已不唸編號(靠「下一集輪到某某」串連,見 produce_batch
# _checkup_finalize),片頭卡/縮圖的標題在此改號前生成,故三者一致。
_CK_SERIES = "個股體檢"
_CK_EP_IN_TITLE = __import__("re").compile(r"個股體檢\s*EP\s*\.?\s*(\d+)")


def _is_checkup_title(title: str) -> bool:
    """本片是否屬於『個股體檢』連載(唯一標記＝標題含系列名『個股體檢』；產製端保證保留系列名、
    只去掉 EP 數字)。散落的個股片(力積電/廣達…)標題都帶此四字,故一併納入連號。"""
    t = title or ""
    # 🔴 EP0/系列說明片豁免(2026-07-25):它雖含系列名『個股體檢』,但是系列「說明片」不是正片——
    # 不可掛 EP 號、也不可被 _next_checkup_ep 當一集計數。否則標題會標「個股體檢EP14」而旁白正說
    # 「這支不是第幾集」=標題與旁白自相矛盾=前門片說謊(誠信紅線)。通用簽名＝EP0 標題結尾『規則
    # 先講死』(ep0_engine._title 的 tw_lab/checkup 各式皆帶),或 checkup EP0 特有『個股體檢系列』。
    # 正片標題(台積電2330體檢報告…/個股體檢【世界5347】…/個股體檢EP1…)絕不含這兩者。
    if "規則先講死" in t or "個股體檢系列" in t:
        return False
    return _CK_SERIES in t


def _strip_checkup_ep(title: str) -> str:
    """去掉標題裡的系列名+EP 數字,留下乾淨鉤子(供重新掛號)。只動 4 字『個股體檢』與其 EP 數字,
    不誤傷『體檢報告』這種一般詞。"""
    re_ = __import__("re")
    t = title or ""
    t = re_.sub(r"[\s｜|·:：]*個股體檢\s*EP\s*\.?\s*\d+", "", t)   # 個股體檢EP2 / 個股體檢 EP1
    t = re_.sub(r"[\s｜|·:：]*個股體檢", "", t)                     # 裸系列名
    t = re_.sub(r"[\s｜|·]*EP\s*\.?\s*\d+(?!\d)", "", t)           # 殘留 EPn
    return t.strip(" ｜|·:：，,、-　\t")


def _apply_checkup_ep(title: str, ep_n: int, maxlen: int = 98) -> str:
    """把標題重新掛成連載後綴『…｜個股體檢EP{n}』(對齊已公開的 EP1 格式)。冪等：重複套用結果不變。
    先剝掉任何既有系列/EP 標記再掛,故對前綴式(個股體檢EP2鴻海…)或後綴式(…｜個股體檢EP2)輸入都一致。
    hook 過長時截斷 hook(不截後綴),保證 EP 號一定留在 100 字上限內。"""
    hook = _strip_checkup_ep(title)
    suffix = f"｜{_CK_SERIES}EP{int(ep_n)}"
    room = maxlen - len(suffix)
    if room > 0 and len(hook) > room:
        hook = hook[:room].rstrip(" ｜|·:：，,、-　\t")
    return f"{hook}{suffix}"


def _load_checkup_ep_ledger() -> dict:
    d = load_json_safe(CHECKUP_EP_LEDGER, default={}) or {}
    if not isinstance(d, dict):
        return {"assigned": {}}
    d.setdefault("assigned", {})
    return d


def _next_checkup_ep() -> int:
    """下一集 EP＝已發布個股體檢集數的最大號 +1(確定性推導,免計數器 drift)。
    真相來源＝checkup_ep_ledger(發布時逐支寫入);另掃 quality_scores 已發布標題當**保底**,
    抓在本帳本建立之前就已公開、或手動發布的集數(但排除已在帳本內的 slug,避免存量待發片
    quality_scores 裡的舊 EP 數字污染 max)。掃不到＝0 → 第一集 EP1。"""
    led = _load_checkup_ep_ledger()
    assigned = led.get("assigned") or {}
    max_ep = 0
    for v in assigned.values():
        try:
            max_ep = max(max_ep, int(v))
        except Exception:  # noqa: BLE001
            pass
    try:  # 保底：掃 quality_scores 已發布標題,抓帳本建立前就上線的集數(EP1/EP7)。兩道防污染:
        #     ①排除已在帳本內的 slug(帳本權威)；②只認**真的在 uploaded_ledger** 的 slug——
        #     存量待發片的 quality_scores title 仍帶舊 EP 數字(EP20/23…),但它們不在 ledger,不算數。
        qs = load_json_safe(QSCORES, default={}) or {}
        real_pub = load_json_safe(LEDGER, default={}) or {}
        for it in (qs.get("published") or []):
            if not isinstance(it, dict):
                continue
            slug = it.get("slug")
            if slug in assigned or slug not in real_pub:
                continue
            m = _CK_EP_IN_TITLE.search(str(it.get("title", "")))
            if m:
                max_ep = max(max_ep, int(m.group(1)))
    except Exception:  # noqa: BLE001
        pass
    # ep_floor:Carson 權威錨點(線上已到 EPn → 設 n+1)。防舊跳號 bug 記進 ledger 的高號、或保底
    # 掃到「已理順前的舊 EP 號」污染 max,把下一集壓到 floor 以下。發布後 ledger 自然連號超過 floor。
    floor = int(led.get("ep_floor", 0) or 0)
    return max(max_ep + 1, floor)


def _record_checkup_ep(slug: str, ep_n: int) -> None:
    """發布成功後把 slug→ep_n 寫進連載帳本(同一批下一支即讀到、拿到 +1，保證批內也連號)。"""
    try:
        led = _load_checkup_ep_ledger()
        led.setdefault("assigned", {})[slug] = int(ep_n)
        led["updated"] = tw_today()
        save_json_atomic(CHECKUP_EP_LEDGER, led)
    except Exception as e:  # noqa: BLE001 — 帳本寫入失敗不可拖累已成功的發布
        print(f"[checkup-ep] 連載帳本寫入失敗 {slug}: {e}", file=sys.stderr)


def _series_of(slug: str, title: str, lab_slugs: set):
    """回 (系列名, 集數) 或 (None, None)＝不是已知連載系列(不受這道閘影響)。

    個股體檢**刻意不在此登記**：它的 EP 號改為發布時才掛(見 _next_checkup_ep),產製階段標題不帶
    EP 數字,天生就是「發一支進一號」連號,不需要這道順序閘擋跳號;而存量待發片的 quality_scores
    標題還殘留舊 EP 數字,若在此認號反而會用**舊號**排序、擋錯片。故這道閘只管台股真相實驗室。"""
    if slug in lab_slugs or "真相實驗室" in title:
        m = _EP_NUM_RE.search(title)
        if m:
            return "台股真相實驗室", int(m.group(1))
    return None, None


def _series_order_gate(slugs: list, ledger: dict, qmap: dict, qmin: int) -> tuple[list, dict]:
    """同系列強制依集數順序發 + 不重發已發布過的集數。回 (keep, held{slug: 原因})。"""
    try:
        titles = _slug_titles()
        lab = _tw_lab_member_slugs()
        # 已發布過的集數(用真標題認;認不出來就跳過=保守不擋)
        pub_eps: dict = {}
        for s in ledger:
            t = titles.get(s)
            if not t:
                continue
            name, n = _series_of(s, t, lab)
            if name:
                pub_eps.setdefault(name, set()).add(n)
        groups: dict = {}
        for s in slugs:
            name, n = _series_of(s, titles.get(s, ""), lab)
            if name:
                groups.setdefault(name, []).append((n, s))
        held: dict = {}
        for name, items in groups.items():
            for n, s in items:
                if n in pub_eps.get(name, set()):
                    held[s] = f"{name} EP{n} 已發布過(撞號,不重發)"
            rest = [(n, s) for n, s in items if s not in held]
            ok = [(n, s) for n, s in rest
                  if isinstance(qmap.get(s), (int, float)) and qmap[s] >= qmin]
            if not ok:
                continue
            lowest = min(n for n, _ in ok)
            for n, s in rest:
                if n > lowest:
                    held[s] = f"{name} 等 EP{lowest} 先發(維持追更集數順序)"
        if held:
            print(f"[series] 系列順序閘:暫緩 {len(held)} 支(留在 output/,前一集發掉就自動遞補)")
            for s, why in list(held.items())[:8]:
                print(f"    - {s[:44]}｜{why}")
        return [s for s in slugs if s not in held], held
    except Exception as e:  # noqa: BLE001
        print(f"[series] 系列順序閘異常，本輪不擋({e})", file=sys.stderr)
        return slugs, {}


def _factguard_gate(slugs: list) -> tuple[list, dict]:
    """誠信硬地板(2026-07-13 建):把『績效數字查無來源』的片擋在發布之外。

    為什麼要有這道:品保實測抓到產線會編造統計數字冒充真實回測(如長片宣稱「根據臺股十年資料，
    毛利率成長選股勝率只有百分之三十一」——根本沒有這個回測引擎),而頻道定位正是「用真回測拆穿
    割韭菜神話」。既有 fact_guard.py 的 docstring 寫著「或搭 daily_publish 攔」,但這個「攔」
    從來沒接上——偵測到只記一筆,片照發。這裡就是把那條線接起來。

    fail-closed:數字溯源不到就不發(可逆——補上真實回測依據或改示意語氣後即可重發)。
    但『守門自己壞掉』時要 fail-open:事實庫太小(數字池 <10)會讓所有片都像無憑據,
    那是事實庫沒建好、不是片有問題,此時放行並大聲警告,不能把整條產線鎖死。
    """
    blocked: dict = {}
    try:
        import fact_source_guard as fsg
    except Exception as e:  # noqa: BLE001
        print(f"[factguard] 載入失敗，本輪不擋({e})", file=sys.stderr)
        return slugs, blocked
    pool = fsg.fact_pool()
    if len(pool) < 10:
        print(f"[factguard] ⚠️ 事實庫數字池只有 {len(pool)} 個——守門會誤擋全部，本輪放行不擋。"
              "請先把真實回測灌進 STUDIO/tw_stock_facts.json。", file=sys.stderr)
        return slugs, blocked
    keep = []
    for s in slugs:
        bad = fsg.check_slug(s, pool)
        if bad:
            blocked[s] = [{"value": c["value"], "clause": c["clause"]} for c in bad[:3]]
        else:
            keep.append(s)
    if blocked:
        print(f"[factguard] 🔴 擋下 {len(blocked)} 支『績效數字查無來源』的片(不發布):")
        for s, hits in list(blocked.items())[:6]:
            print(f"    - {s[:40]}｜無憑據 {hits[0]['value']}:「{hits[0]['clause'][:44]}」")
        try:
            sc_mod = __import__("studio_common")
            sc_mod.save_json_atomic(PROJECT_ROOT / "STUDIO" / "factguard_blocked.json",
                                    {"updated": tw_today(), "blocked": blocked})
        except Exception:  # noqa: BLE001
            pass
        try:
            import notify
            notify.push("量化阿森｜誠信守門攔截",
                        f"🔴 {len(blocked)} 支片『數字查無來源』被擋下不發布。"
                        f"補真實回測依據或改示意語氣後才可發。", tag="rotating_light")
        except Exception:  # noqa: BLE001
            pass
    return keep, blocked


def find_candidates(ledger: dict) -> list:
    # 高分先發：Shorts(衝YPP)優先，組內依品質分數由高到低；其次長片同理。
    qmap, qmin = load_quality()
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

    # 誠信硬地板:績效數字溯源不到的片,一律不進候選(在排序/配額之前就擋掉)
    shorts, _b1 = _factguard_gate(shorts)
    longs, _b2 = _factguard_gate(longs)

    # 系列連載完整性:同系列強制照集數順序發(擋跳號/撞號)。只暫緩、不丟棄,見 _series_order_gate。
    shorts, _h1 = _series_order_gate(shorts, ledger, qmap, qmin)
    longs, _h2 = _series_order_gate(longs, ledger, qmap, qmin)

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
    # 🔴 2026-07-15 修「長片永遠輪不到」:原本 shorts + longs 直接串接,--max 12 的名額
    # 全被 Shorts 吃光——長片(YPP 4000 小時 watch time 的唯一現實路徑)被結構性擠出佇列,
    # 實測 94 分的旗艦長片在佇列躺了一整天發不出去。
    # 🔴 2026-07-17 三修「--max 1 批把長片切掉」:二修版把長片插在 shorts[0] 之後(merged[1]),
    # 但每日三批是 09:15 --max 1 / 11:00 --max 1 / 18:30 --max 3——兩個 --max 1 批只取
    # merged[0],永遠是短片,長片實際只有 18:30 那批發得掉 → 實測配比 4短1長。
    # 翻轉成長片優先的理由,**承重的是政策事實不是統計**:
    #   ①【政策·硬事實】Shorts 觀看**不計入** YPP 的 4,000 watch hours。本頻道標準路徑
    #     66hr/4000=1.7%,已比 Shorts 路徑 25k/1000萬=0.25% 近 7 倍——長片是唯一同時餵
    #     「訂閱」與「觀看時數」的格式。這條不受樣本大小影響。
    #   ②【統計·僅供參考,n 小勿當定論】Analytics creatorContentType 90d:Shorts 訂閱轉換
    #     約 0.080%;長片 0.43–0.96%(n=13,且單片 ijCNjwEDRnc 一支就佔長片訂閱的 64%,
    #     拿掉它剩 0.43%)。方向顯著(去離群值後雙比例 z=3.81, p=0.0001)但**倍數不穩(5–12x)**。
    #   ⚠️ 因果警告:長片觀眾是自我選擇的;把 Short 觀眾推去看長片**不會自動繼承**這個轉換率。
    # 目標配比翻轉成 2短3長。
    # 排法:「1 長 + 2 短」循環(長片打頭)。每批各自重算候選(已發布的在 ledger 內會被排除),
    # 故當日實際取用序列 = merged 前 5 名依批次大小切分:
    #   09:15 max1 -> L1 | 11:00 max1 -> L2(重算後 merged[0]) | 18:30 max3 -> L3,S1,S2
    #   = 每天 3 長 2 短,正好命中目標配比。
    # 退化:長片庫存不足時 while 迴圈自然只排短片(反之亦然),不會空手或崩潰。
    LONG_PER_CYCLE, SHORT_PER_CYCLE = 1, 2
    merged = []
    li = si = 0
    while li < len(longs) or si < len(shorts):
        for _ in range(LONG_PER_CYCLE):
            if li < len(longs):
                merged.append(longs[li]); li += 1
        for _ in range(SHORT_PER_CYCLE):
            if si < len(shorts):
                merged.append(shorts[si]); si += 1
    return merged


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


def _sys_python() -> Path:
    """回傳能跑 playwright 的系統 python(.venv 沒裝 playwright，tiktok_upload.py 需要它)。
    寫法比照 local_cron.py 的 SYS_PY 常數：優先常見安裝路徑，找不到用 which('python') 後援，
    再找不到才退回目前的 venv python(至少不整段崩，但 TikTok 那步預期會因缺 playwright 而優雅失敗)。"""
    if _SYS_PY_HARDCODED.exists():
        return _SYS_PY_HARDCODED
    w = shutil.which("python")
    return Path(w) if w else Path(sys.executable)


def _tiktok_crosspost(slug: str) -> None:
    """把一支 Short 跨發到 TikTok(spawn 系統 python 跑 tiktok_upload.py --slug)。

    失敗隔離(關鍵)：整段包 try/except + subprocess timeout；TikTok 掛掉／session 過期／
    playwright 報錯，一律不得中斷或影響已完成的 YouTube+IG 發布——只印一行 log 就返回。
    去重：tiktok_upload.py 內部 --slug 模式本身不查 ledger，所以這裡先淺查一次
    STUDIO/tiktok_ledger.json，已發過(例如被 crontab 補發安全網搶先跑過)就不重發；
    成功後由 tiktok_upload.py 自己把 slug 寫回 ledger，供其他呼叫端(cron 補發)去重。
    可用 env TIKTOK_IN_PIPELINE=0 整條關掉(預設開，方便除錯/隔離問題)。"""
    import os
    if os.environ.get("TIKTOK_IN_PIPELINE", "1") == "0":
        return
    try:
        led = json.loads(TIKTOK_LEDGER.read_text(encoding="utf-8")) if TIKTOK_LEDGER.exists() else {}
    except Exception:  # noqa: BLE001
        led = {}
    if slug in led:
        print(f"[tiktok] {slug} 已在 ledger(補發安全網搶先跑過)，跳過重發")
        return
    try:
        py = _sys_python()
        proc = subprocess.run(
            [str(py), str(TIKTOK_UPLOAD_SCRIPT), "--slug", slug],
            cwd=str(PROJECT_ROOT), timeout=170,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        out = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        if proc.returncode == 0:
            print(f"[tiktok] 已跨發 {slug}")
            log_ops("上架部門", f"TikTok 跨發成功：{slug}")
        elif ("session" in out.lower() and "過期" in out) or "尚未登入" in out or "重新開瀏覽器登入" in out:
            print(f"[tiktok] {slug} session 過期／尚未登入，已跳過(不影響YT/IG)", file=sys.stderr)
            log_ops("上架部門", f"TikTok session 過期，跳過 {slug}（不影響YT/IG，請重登 tiktok_state.json）")
        else:
            tail = out.strip()[-200:]
            print(f"[tiktok] {slug} 跨發失敗(不影響YT/IG)：{tail}", file=sys.stderr)
            log_ops("上架部門", f"TikTok 跨發失敗 {slug}：{tail[:120]}（不影響YT/IG）")
    except subprocess.TimeoutExpired:
        print(f"[tiktok] {slug} 逾時(170s)，已跳過(不影響YT/IG)", file=sys.stderr)
        log_ops("上架部門", f"TikTok 跨發逾時，跳過 {slug}（不影響YT/IG）")
    except Exception as exc:  # noqa: BLE001 — TikTok 這步絕不能拖累 YT/IG 主流程
        print(f"[tiktok] {slug} 跨發例外(不影響YT/IG)：{str(exc)[:150]}", file=sys.stderr)
        log_ops("上架部門", f"TikTok 跨發例外 {slug}：{str(exc)[:100]}（不影響YT/IG）")


def upload_one(yt, slug: str, privacy: str) -> str:
    cfg = up.load_channel_config()
    meta = up.assemble_metadata(slug=slug, md_path=OUTPUT / f"{slug}.md", channel_config=cfg, append_affiliate=True)
    meta = up.enforce_youtube_limits(meta)
    is_short = slug.startswith("S_")

    # 個股體檢連載：EP 號在此(發布時)按「已發布集數 max+1」掛上,不在種題/產製時寫死(治跳號,見上方
    # _next_checkup_ep 區塊)。只認長片且標題帶系列名「個股體檢」的片;散落個股片(力積電/廣達…標題同樣
    # 帶此四字)一併納入連號。改後的 meta["title"] 之後同時流向 YT 標題、封面(make_cover 用同一 title)、
    # SEO 檔名,三者一致;成功上傳後才寫連載帳本(見函式尾),同批下一支即讀到 +1。冪等:重跑不會重複掛號。
    _ck_ep = None
    if not is_short and _is_checkup_title(meta.get("title", "")):
        _ck_ep = _next_checkup_ep()
        meta["title"] = _apply_checkup_ep(meta["title"], _ck_ep)
        meta = up.enforce_youtube_limits(meta)  # 掛號後再過一次長度上限(理論上已 <=98,保險)
        print(f"[checkup-ep] {slug} → 連載 EP{_ck_ep}｜{meta['title']}")

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

    # 描述訂閱鉤標準化：每支發布片(短+長)都要有清楚的『訂閱理由』句(價值承諾,非光禿禿求訂閱)。
    # 連載片(台股真相實驗室)給系列專屬鉤(還有幾組沒拆,訂閱才拿得到);故帶 slug/title 供判系列。
    meta["description"] = _ensure_subscribe_hook(meta["description"], cfg,
                                                 slug=slug, title=meta.get("title", ""))[:5000]

    # Shorts 用 #Shorts 加進標題尾端（字數允許時）；長片 categoryId 用教育(27)
    title = meta["title"]
    if is_short and "#shorts" not in title.lower() and len(title) <= 90:
        title = title + " #Shorts"
    category_id = "28" if is_short else "27"  # Shorts=科技(28), Long=教育(27)

    # 確定性安全網(2026-07-24):長片絕不帶 #Shorts 標籤——YouTube 會據此當短片處理、扼殺長片搜尋流量。
    # 這是上 YouTube 前的最後一道:涵蓋「produce 端修法之前已生成的 backlog .md」(舊產物仍帶 #Shorts)
    # 與任何漏網;短片不動(它本該掛 #Shorts)。根因修在 produce_batch,此處是 belt-and-suspenders。
    _tags = meta.get("tags", []) or []
    if not is_short:
        _tags = [t for t in _tags if str(t).lstrip("#").strip().lower() not in ("shorts", "short")]

    body = {
        "snippet": {
            "title": title,
            "description": meta["description"],
            "tags": _tags,
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
    if _ck_ep is not None:  # 個股體檢連載：上傳成功才記帳(同批下一支讀到 +1；EP1/EP7 已由 bootstrap 記入)
        _record_checkup_ep(slug, _ck_ep)
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
            # 入列補掛佇列(thumb_backfill.py 每天 15:10 quota 重置後補上,治裸奔片)
            try:
                _pt_path = PROJECT_ROOT / "STUDIO" / "pending_thumbs.json"
                _pt = load_json_safe(_pt_path, default={}) or {}
                _pt.setdefault("pending", {})
                _pt.setdefault("done", {})
                if vid not in _pt["done"]:
                    _pt["pending"][vid] = {"slug": slug, "added": tw_today(), "src": "publish"}
                    save_json_atomic(_pt_path, _pt)
            except Exception as _e3:  # noqa: BLE001
                print(f"[warn] pending_thumbs 入列失敗 {slug}: {_e3}", file=sys.stderr)
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
    ap.add_argument("--series", default=None, choices=["checkup"],
                    help="只發指定連載系列(checkup=個股體檢)。配 --max 1 = 每天發一部個股體檢連載"
                         "(EP 號由發布時自動連號,見 _next_checkup_ep)。其餘系列/一般片本輪跳過。")
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

    # --series checkup:只留個股體檢連載片(識別＝標題含系列名「個股體檢」,由產製端 _normalize_checkup_title
    # 對 checkup_ fact_key 片保證掛上,見 produce_batch;等價於 fact_key 判定,且不誤收無關個股片)。
    # 供「每天發一部個股體檢」排程:daily_publish.py --series checkup --max 1。
    if args.series == "checkup":
        _titles = _slug_titles()

        def _title_of(s):
            t = _titles.get(s, "")
            if not t:
                try:
                    t = (OUTPUT / f"{s}.md").read_text(encoding="utf-8", errors="replace").splitlines()[0]
                except Exception:  # noqa: BLE001
                    t = ""
            return t
        _before = len(cands)
        cands = [s for s in cands if _is_checkup_title(_title_of(s))]
        print(f"[series] --series checkup：候選 {_before}→{len(cands)} 支(只發個股體檢連載)")
        if not cands:
            print("[series] 目前沒有待發的個股體檢連載成片(output/ 無或全已發布)。")

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
            _post_engage_comment(yt, vid, slug, ledger)  # 首小時互動：提問+長片/訂閱導流(置頂需你在Studio點)
            try:  # 播放清單即時歸類（台股真相實驗室/ETF定投/EP實測/避雷拆穿）；失敗絕不擋發布
                import playlist_engine as _ple
                _added = _ple.add_to_playlists(yt, slug, vid)
                if _added:
                    print(f"[playlist] {slug} 已歸類進：{', '.join(_added)}")
            except Exception as _e:  # noqa: BLE001
                print(f"[warn] playlist_engine 掛勾略過（{slug}）：{_e}", file=sys.stderr)
            results.append((slug, vid, "ok"))
            if slug.startswith("S_") and not args.no_ig and ig_done < args.ig_max:
                _ig_crosspost(slug)
                ig_done += 1
            if slug.startswith("S_"):
                # TikTok 排在 YouTube(+IG)成功之後才觸發；外層再包一層 try/except 雙重保險
                # （理論上 _tiktok_crosspost 內部已全接，這裡只是不讓任何漏網例外反噬主流程）。
                try:
                    _tiktok_crosspost(slug)
                except Exception as _e:  # noqa: BLE001
                    print(f"[warn] TikTok 跨發外層例外（不影響YT/IG，已忽略）：{_e}", file=sys.stderr)
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
