#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quota_meter.py — YouTube Data API 配額計量器(全產線唯一一份帳)。

## 為什麼要有這支
在這之前**整條產線沒有任何配額計量**:每天照樣跑到撞上 403 才知道爆了,而且爆掉的
那一刻已經是「某支腳本吃光、後面全部餓死」的狀態——實測 403 集中在 09:00(179 次),
15:00 之後幾乎歸零。原因是兩件事疊在一起:

1. **時區錯配**:配額在**太平洋時間午夜**重置,換算台北是 **15:00~16:00**(夏令時間會差
   一小時)。但排程是照台北的日曆日排的,所以台北 00:00~15:00 這段跑的所有工作,
   花的其實是**昨天**那份配額的尾巴。早上的工作永遠在吃剩菜。
2. **單價極不對稱**,而排程對此毫無感覺:
   `videos.list` 1 / `videos.update` 50 / `captions.insert` 400 /
   **`captions.update` 450** / **`videos.insert` 1600**。
   最大兇手是字幕重傳:12 支 × 450 = **5,400,一支腳本吃掉半天配額**。

## 設計
掛在 `daily_publish.get_service()` 這個**唯一的**建構點上,用 monkeypatch 攔
`HttpRequest.execute()`,依 URI 路徑 + HTTP method 查價。好處是**所有腳本自動被計量**,
不必逐一改呼叫端(改呼叫端一定會漏,而漏掉的那支就是下次吃光配額的那支)。

帳本以**太平洋日期**分桶(跟配額重置對齊,不是台北日曆日)。

## 執法(預設關閉)
`YT_QUOTA_ENFORCE=1` 才會在超過預算時擋下呼叫。預設只記帳不擋——價目表是照官方文件寫的,
但在拿真實一天的資料驗證它之前就拿它去擋人,等於用一張沒對過帳的表去停產線。
先觀測、後執法。超過 80% 會推 ntfy 提醒。

用法:
  python scripts/quota_meter.py              # 看今天(太平洋日)花了多少、花在哪
  python scripts/quota_meter.py --days 7     # 看近 7 個配額日
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STATE = ROOT / "STUDIO" / "quota_meter.json"
# 🔴 2026-08-28:實測撞牆點 **19,645**(08-27 那天花到這裡開始被拒,而且被拒了 935 次
# / 45,491 units —— 撞牆後所有排程還在照跑,每次都是白打)。
# 原本寫 10000 是**猜的**,而且比真值低一倍 → 預留額度用它去算,結果是
# 「補件工作被我自己的假天花板擋死,而真配額還有一半沒用」。
# 這裡改成實測值當預設;`effective_limit()` 仍會用帳本推出來的上下界覆蓋它,
# 所以之後 YouTube 若調整配額,不必再改這個常數。
DAILY_LIMIT = int(os.environ.get("YT_QUOTA_LIMIT", "19645"))
WARN_AT = float(os.environ.get("YT_QUOTA_WARN", "0.80"))
ENFORCE = os.environ.get("YT_QUOTA_ENFORCE", "") == "1"
# 這個 process 必須**留給後面更重要的工作**多少 units。預設 0 = 不留(行為完全不變),
# 由 cron 行逐個 job 設定 opt-in。設計理由見下面 _execute 的註解。
RESERVE = int(os.environ.get("YT_QUOTA_RESERVE", "0"))


class QuotaExhausted(RuntimeError):
    """預算用完(只有 YT_QUOTA_ENFORCE=1 時才會丟)。"""


# ── 價目表(官方 Quota Calculator;沒列到的一律當 1,寫進 unknown 供事後補) ──────────
# key = (資源路徑, HTTP method)。路徑取 /youtube/v3/ 之後那一段。
_COST = {
    ("videos", "GET"): 1,
    ("videos", "PUT"): 50,
    ("videos", "POST"): 1600,
    ("videos", "DELETE"): 50,          # 2026-08-25 補:原本落到 unknown 只記 1
    ("videos/rate", "POST"): 50,
    ("channelBanners/insert", "POST"): 50,   # 2026-08-25 補:原本連 head fallback 都接不到
    ("channelBanners", "POST"): 50,
    ("captions", "GET"): 50,
    ("captions", "POST"): 400,
    ("captions", "PUT"): 450,
    ("captions", "DELETE"): 50,
    ("thumbnails/set", "POST"): 50,
    ("playlists", "GET"): 1,
    ("playlists", "POST"): 50,
    ("playlists", "PUT"): 50,
    ("playlists", "DELETE"): 50,
    ("playlistItems", "GET"): 1,
    ("playlistItems", "POST"): 50,
    ("playlistItems", "PUT"): 50,
    ("playlistItems", "DELETE"): 50,
    ("channelSections", "GET"): 1,
    ("channelSections", "POST"): 50,
    ("channelSections", "PUT"): 50,
    ("channelSections", "DELETE"): 50,
    ("channels", "GET"): 1,
    ("channels", "PUT"): 50,
    ("subscriptions", "GET"): 1,
    ("commentThreads", "GET"): 1,
    ("commentThreads", "POST"): 50,
    ("comments", "GET"): 1,
    ("comments", "POST"): 50,
    ("comments", "PUT"): 50,
    ("comments", "DELETE"): 50,
    ("search", "GET"): 100,          # ← 一次 100,是最容易無聲吃光配額的端點
    ("videoCategories", "GET"): 1,
    ("i18nLanguages", "GET"): 1,
}


def _pacific_date(now_utc=None):
    """配額重置對齊的日期＝**太平洋日期**(不是台北日曆日)。

    優先用 zoneinfo;Windows 上常常沒裝 tzdata 會直接丟例外,所以備援自己算美國 DST
    (3 月第 2 個週日 02:00 起 UTC-7,11 月第 1 個週日 02:00 止,其餘 UTC-8)。"""
    u = now_utc or _dt.datetime.now(_dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return u.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # noqa: BLE001
        pass

    def _nth_sunday(year, month, nth):
        d = _dt.date(year, month, 1)
        d += _dt.timedelta(days=(6 - d.weekday()) % 7)      # 該月第一個週日
        return d + _dt.timedelta(days=7 * (nth - 1))

    y = u.year
    start = _dt.datetime.combine(_nth_sunday(y, 3, 2), _dt.time(10), _dt.timezone.utc)   # 02:00 PST
    end = _dt.datetime.combine(_nth_sunday(y, 11, 1), _dt.time(9), _dt.timezone.utc)     # 02:00 PDT
    off = -7 if start <= u < end else -8
    return (u + _dt.timedelta(hours=off)).date().isoformat()


def _load():
    """回帳本 dict。可能帶兩個底線開頭的旗標(`_save` 會剝掉,不會寫進檔案):

    · `_from_bak`   —— 正本解不開,這份是從 .bak 救回來的(最多舊一次寫入)
    · `_unreadable` —— 正本和 .bak 都解不開,**這份是空殼不是空帳本**

    🔴 2026-09-03 為什麼要分這兩件事:原本不管什麼錯都回 `{"days": {}}`,
    於是「檔案寫到一半」和「今天還沒開始花」長得**一模一樣**。而 `remaining()` 讀到
    空帳本會算出「今天花了 0」= 配額全滿,發布閘門就放行一整批 —— 也就是說
    帳本壞掉的後果不是停擺,是**超發**,發到一半 403、半批成功卻回報成功
    (memory `yt-quota-partial-failure-silent-bad-data` 記過這個事故)。
    一個管花費的閘門,「我不知道」必須等於「先別花」,不能等於「隨便花」。

    「檔案不存在」**不再**直接回空帳本。🔴 2026-09-03 獨立驗證抓到:
    原本 `if not STATE.exists(): return {"days": {}}` 排在 `.bak` 退路**前面**,
    於是「正本被刪掉但 .bak 還在」會回一份空帳本 → `remaining()` 算出 19,645
    → 閘門授權 9 支長片、超發 18,287 units。**一個為了 fail-closed 而寫的函式,
    自己留了一條 fail-open 的分支。**
    分辨方法就在旁邊沒被用:**第一次跑不會有 .bak**,所以 `.bak` 存不存在
    正好把「第一次跑」和「正本掉了」分得開。順序改成:
    正本 → .bak → 兩個都沒有才是第一次跑 → 兩個都在但都壞才是 _unreadable。

    ⚠️ 隔壁有 `studio_common.load_json_safe`(主檔壞 → 退 .bak → 回 default),
    做的是同一件事的前半段,而且它的 docstring 就寫著要斷開「讀到殘檔→回空→存回小檔
    洗掉整檔」這條鏈。這裡**沒有**直接用它,理由只有一個:它回 `default` 時,
    「檔案根本不存在」和「兩份都壞掉」給出**一模一樣**的回傳值 —— 而這支的整個 fail-closed
    就建立在這兩者必須分得開。不要「順手」把這段整理成 `load_json_safe`,那會無聲拿掉
    `remaining()` 的 fail-closed。(要整理的話,該做的是升級 `load_json_safe` 讓它回報
    來源,那支有 22 個檔案在用,是另一件事、另一個爆炸半徑。)"""
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    bak = STATE.with_suffix(STATE.suffix + ".bak")   # save_json_atomic 每次覆蓋前留的
    if bak.exists():
        try:
            d = json.loads(bak.read_text(encoding="utf-8"))
            d["_from_bak"] = True
            print("[quota] ⚠️ 帳本正本%s,已改用 %s(可能少最後一次寫入)"
                  % ("不存在" if not STATE.exists() else "解不開", bak.name),
                  file=sys.stderr)
            return d
        except Exception:  # noqa: BLE001
            pass
    if not STATE.exists() and not bak.exists():
        return {"days": {}}          # 正本與 .bak 都沒有 = 第一次跑,合法的空帳本
    print("[quota] 🔴 帳本正本與 .bak 都用不了 —— remaining() 會 fail-closed 回 0",
          file=sys.stderr)
    return {"days": {}, "_unreadable": True}


def _save(d):
    d = {k: v for k, v in d.items() if not str(k).startswith("_")}   # 旗標不落地
    try:
        import studio_common as sc
        sc.save_json_atomic(STATE, d)
    except Exception:  # noqa: BLE001
        try:
            # 🔴 2026-09-03 這裡原本是 `STATE.write_text(...)` —— **直接寫最終路徑,非原子**,
            # 而它正是半截檔唯一的產生途徑。觸發條件不是罕見情況:`save_json_atomic` 在
            # Windows 上對 `os.replace` 重試 10 次 `PermissionError` 之後就重拋,而那個
            # PermissionError 的成因**就是目標檔被別的行程佔用** —— 也就是說原子保證
            # 在爭用時失效,而爭用正是它存在的理由。四條線共用這個 repo,爭用是常態。
            # 退路不能拿掉(見下面那層的理由),所以**把退路也做成原子的**:
            # 自帶 tmp + os.replace,不依賴 studio_common 也能保持「讀者永遠看到完整檔」。
            STATE.parent.mkdir(parents=True, exist_ok=True)
            # 檔名帶 pid+thread:跨行程靠 pid、同行程雙執行緒靠 thread id
            # (studio_common 的 _path_lock 在這條退路外面,保護不到)。
            tmp = STATE.with_suffix(STATE.suffix + f".tmp2.{os.getpid()}.{threading.get_ident()}")
            try:
                tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, STATE)
            except Exception:
                try:
                    tmp.unlink()          # 別留垃圾
                except Exception:  # noqa: BLE001
                    pass
                raise
        except Exception:  # noqa: BLE001
            # 🔴 這一層絕對不能省。`_charge_once` 是在 `_orig_next` **之前**呼叫的,
            # 也就是說寫檔失敗會讓**影片連傳都沒傳出去**;一般呼叫則是在 finally 裡炸,
            # 例外會取代正常 return,API 明明成功了呼叫端卻收到錯誤。
            # 計量器是純觀測元件,卻因為 b55669b 攔了 next_chunk 而落在上傳的前置關鍵路徑上。
            # 記不到帳最多是帳本少一筆;讓發布停下來是完全不成比例的代價。
            pass


def cost_of(uri, method):
    """依 URI + method 查價。回 (op 名稱, units)。查不到回 (op, 1) 並標成 unknown。"""
    from urllib.parse import urlparse
    u = urlparse(uri or "")
    path = (u.path or "").strip("/")
    if "youtubeanalytics" in (u.netloc or "") or path.startswith("v2/reports"):
        return ("analytics(獨立配額)", 0)      # Analytics 是**另一份**配額,不吃 Data API
    if "/youtube/v3/" in "/" + path:
        res = path.split("youtube/v3/", 1)[1]
    else:
        res = path
    m = (method or "GET").upper()
    if (res, m) in _COST:
        return (f"{res}.{m.lower()}", _COST[(res, m)])
    # captions/{id} 的 GET = **下載字幕**,官方 200,不是 captions.list 的 50。
    # 必須擋在 head fallback 之前:否則會撿到 ("captions","GET")=50,
    # 那是一個「看起來合理的錯價」,比記成 unknown 更難被發現。
    if res.startswith("captions/") and m == "GET":
        return ("captions.download", 200)
    head = res.split("/")[0]
    if (head, m) in _COST:
        return (f"{head}.{m.lower()}", _COST[(head, m)])
    return (f"unknown:{res}.{m.lower()}", 1)


_HTTP2API = {"GET": "list", "POST": "insert", "PUT": "update", "DELETE": "delete"}


def audit_tables():
    """跟 quota_budget.COST 對帳,回傳不一致清單 [(api_method, meter價, budget價)]。

    兩張表刻意不合併(key 空間不同:這裡是 HTTP 路徑+動詞,那裡是官方 API method 名),
    但**必須對得起來**——價格分歧會讓「事前估」與「事後量」永遠兜不攏,
    而那正是本專案踩過的「同一件事兩份實作」事故的形狀。"""
    try:
        import quota_budget
        b = dict(quota_budget.COST)
    except Exception:  # noqa: BLE001
        return []
    diffs = []
    for (res, m), units in _COST.items():
        api = _HTTP2API.get(m, m.lower())
        if res.endswith("/set"):
            name = res.replace("/", ".")
        elif res.endswith("/insert"):
            name = res.replace("/", ".")
        elif res.endswith("/rate"):
            name = res.replace("/", ".")
        else:
            name = f"{res}.{api}"
        if name in b and b[name] != units:
            diffs.append((name, units, b[name]))
    diffs.append(("captions.download", 200, b.get("captions.download")))
    return [d for d in diffs if d[2] is not None and d[1] != d[2]]


def _is_quota_rejected(exc):
    """這次失敗是不是「配額已用罄,請求被拒絕」?

    🔴 2026-08-26 修:原本記在 `finally`,理由寫「403 照樣扣配額」——那對**一般**失敗
    (500、逾時、權限錯)是對的,對 `quotaExceeded` 則是**錯的**:配額已經沒了,
    請求根本沒被執行,不會再扣。而這類失敗在配額用罄後會**大量**發生
    (實測 job_stderr 裡 463 次),全部被當成消耗記進帳本 →
    08-25 記到 18,914/10,000 = 189%,看起來像「上限其實有 18,914」,
    但那是被失敗呼叫灌出來的。差點拿這個數字去推翻「上限 10,000」。
    通則:**量一個東西之前,先確認你量的是不是它**。"""
    t = str(exc)
    return "quotaExceeded" in t or "exceeded your" in t and "quota" in t


def _quota_reject_kind(exc) -> str:
    """這次失敗是哪一種配額拒絕?回 "" / "daily" / "other"。

    "daily" = 每日總量用罄 —— **唯一**該拿來校準天花板的那種。
    "other" = 某個端點自己的配額計量(和每日總量是不同的計量對象)。

    真實樣本(`logs/job_stderr.log`,2026-09-05 兩位 fresh-context 驗證員
    各自實抓並獨立重數,**非杜撰、非 stub**):
      · 1,425 行 `403` `'domain': 'youtube.quota', 'reason': 'quotaExceeded'`
        (playlistItems 900 / videos 397 / commentThreads 55 / comments 34 /
         thumbnails.set 33 / playlists 5 / channels 1,加總吻合)→ "daily"
      · 2 行 `429` `'domain': 'global', 'reason': 'rateLimitExceeded'`(:11730-11731)
        訊息「Quota exceeded for quota metric 'Search Queries' and limit
        'Search Queries per day'」→ Search 端點專屬 → "other"
      · `insufficientPermissions` 4 行 / `videoNotFound` 2 行 → ""
      · `dailyLimitExceeded` / `uploadLimitExceeded` 全 repo **0 命中** ——
        ⚠️ 這只代表「現存這份 log 沒看到」,**沒查過 log 是否曾輪替,
        不能推論從未發生**。它們落到 "",行為與現狀相同。

    ⚠️ 判定順序:先判 "other"。現有樣本中沒有任何一行會同時命中兩者
    (那 2 行既不含字面 `quotaExceeded`、也不是「exceeded your … quota」),
    順序是防將來訊息改版的預防設計,**不是在修一個現存的碰撞**。
    """
    t = str(exc)
    if "rateLimitExceeded" in t:
        return "other"
    if "quotaExceeded" in t or ("exceeded your" in t and "quota" in t):
        return "daily"
    return ""


def _is_wall(b) -> bool:
    """這一天算不算「撞到牆」。`_scan()` 取上界、裁帳本決定保護哪一天,**必須共用這一個判準**。

    🔴 2026-09-02 抽出來的理由(基建線驗證員 T6 實測到的可重現 FAIL):
    原本兩邊各寫一份,裁切端是 `rejected_calls and not unreliable`、
    取上界端是 `rejected_calls and sp`,**差一個「spent 非零」**。
    後果是 spent=0 但有被拒的日子——整日停權、resumable 被拒後 `_unrecord` 歸零、
    或雙機共用同一份配額被另一台吃光(Mac+MSI 是真實配置)——會被裁切端
    **當成牆保護起來**,而 `_scan()` 根本不採用它:真牆被裁、假牆化石化,
    天花板無聲從 26,001 回落 19,645。**我要治的病原樣復活,只因為兩份判準差一個條件。**
    (同型:memory `yt-duplicate-impl-gate-bypass` —— 閘門兩份,產線走沒閘門那份。)

    spent=0 為什麼不算牆:牆的值**就是**當天的成功花費。spent=0 代表那天一 unit 都沒花成,
    那不是「一道 0 units 的牆」,是根本沒量到牆在哪。"""
    # 🔴 2026-09-05:只有「每日總量用罄」算牆。舊資料沒有分類欄位,
    # **缺席時退回舊判準**,否則 08-27/28/29/31 四個撞牆日全部失去 wall 身分、
    # ceil 消失、effective_limit 掉到 floor。
    # (tests/quota_alarm/ 下五支手造的 day dict 也只帶 rejected_calls,
    #  有真實檔案在依賴這條 fallback,不只是理論上成立。)
    _rj = b.get("rejected_daily_calls")
    if _rj is None:
        _rj = b.get("rejected_calls", 0)
    return bool(int(_rj or 0)
                and int(b.get("spent", 0) or 0)
                and not b.get("unreliable"))


def _load_bearing_days(days) -> set:
    """裁帳本時**不能裁掉**的日子 —— 所有估計式承重點的聯集。

    這支存在的理由是:承重點不只一個,而且會增加。`32b1c2f3` 只保護了「日期最近的牆」,
    而 `cefa9ba8` 早它 3 分鐘就讓 `floor_since` 變成第二個承重點 ——
    **同一段裁切迴圈,兩個承重點只保護了一個**,結果 eff 無聲掉 4,999 units。
    所以保護清單不再散落在 `record()` 裡,集中到這裡;之後誰再加一個承重點,
    只要沒有把它加進這個聯集,就會重演同一件事。

    目前三個消費者:
      · `_scan()` 的 ceil        → 日期**最近**的牆(校準要跟得上調降)
      · `_scan()` 的 floor_since → 該牆之後 spent 最高的那天
      · `daily_health` 的 `_ref` → 數值**最高**的牆(告警不該跟著爛狀態滑下去)

    最後那個選擇器和第一個**刻意不同**,兩邊都有寫下來的理由(取最近會讓舊牆永久壓住
    估計值;取最高會讓配額砍半後第二天起新的爛狀態變成正常、警報自己關掉自己)。
    共用的是**謂詞** `_is_wall`(「這天算不算牆」只有一個事實);**選擇器**因消費者而異
    是合法的。這裡要做的不是統一選擇器,是讓保留策略認得**每一個**選擇器要的那天。"""
    keep = set()
    _, _, _, ceil_day, since_day = _scan(days)
    keep.update(k for k in (ceil_day, since_day) if k)
    walls = [(int(v.get("spent", 0) or 0), k) for k, v in days.items() if _is_wall(v)]
    if walls:
        keep.add(max(walls)[1])          # 數值最高的牆(給 daily_health._ref)
    return keep


def record(op, units, rejected=False, kind="daily"):
    """rejected=True:配額用罄被拒的呼叫 —— 記進獨立的桶,**不計入 spent**。
    帳本要能回答「今天真的花了多少」,而不是「今天發了幾個請求」。"""
    day = _pacific_date()
    d = _load()
    b = d.setdefault("days", {}).setdefault(day, {"spent": 0, "calls": 0, "by_op": {}})
    if rejected:
        b["rejected_units"] = int(b.get("rejected_units", 0)) + int(units)
        b["rejected_calls"] = int(b.get("rejected_calls", 0)) + 1
        # 🔴 2026-09-05:只有「每日總量用罄」才該拿來校準天花板。
        # 一律 +(0 或 1)而不是「只在 daily 時才寫這個 key」——
        # 否則 `_is_wall()` 的舊資料 fallback 會把「新資料、只有非總量拒絕」
        # 誤判成「舊資料、無分類」而退回舊判準,那正好把要防的 bug 放回來。
        # **「存在但為 0」和「不存在」是兩件事。**
        b["rejected_daily_calls"] = int(b.get("rejected_daily_calls", 0)) + (1 if kind == "daily" else 0)
        # 🔴 2026-09-05 加：被拒的呼叫原本只記兩個純量，op 被丟掉。
        # 後果不是「沒人去查」，是**帳本結構上記不下答案**——
        # 08-27~08-31 四個撞牆日的被拒單價是 48.7 / 425.0 / 1.0 / 10.5，
        # 差三個數量級，而那正是「這四道牆是不是同一道」的關鍵證據；
        # 沒有 op 分桶，那個問題永遠問不出答案
        # （docs/ops/2026-09-05_four_walls_explained.md）。
        # ⚠️ 刻意用獨立的 key：`by_op` 是 spent 的分解（實際消耗），
        # 被拒的不計入 spent，混進去會讓 by_op 加總與 spent 對不起來，
        # 而那個一致性是拆解上傳鏈成本的依據。
        _ro = b.setdefault("rejected_by_op", {}).setdefault(op, {"units": 0, "calls": 0})
        _ro["units"] += int(units)
        _ro["calls"] += 1
        b["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
        if d.get("_unreadable"):
            # 🔴 2026-09-03 獨立驗證抓到:守衛原本只加在下面那條 _save 上,
            # 而這個函式有**兩條** —— rejected 分支在這裡就 return 了,整個繞過保護。
            # 實測後果與下面那段一字不差:空殼被寫回正本,而 save_json_atomic 覆蓋前
            # 會把現在那份壞檔複製成 .bak,唯一還能救的備份被蓋掉。
            # 「同一件事兩份實作,只修了其中一份」—— 這個 commit 的前一版在訊息裡
            # 講的正是這個病,然後在同一個函式裡犯了它。
            print("[quota] 🔴 帳本讀不到,這筆被拒紀錄不寫回(避免覆蓋掉還能救的 .bak)",
                  file=sys.stderr)
            return int(b.get("spent", 0))
        _save(d)
        return int(b.get("spent", 0))
    b["spent"] = int(b.get("spent", 0)) + int(units)
    b["calls"] = int(b.get("calls", 0)) + 1
    o = b.setdefault("by_op", {}).setdefault(op, {"units": 0, "calls": 0})
    o["units"] += int(units)
    o["calls"] += 1
    b["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    # 只留最近 30 個配額日,免得帳本無限長。
    # 🔴 2026-09-02 例外:**最近一次撞牆那天不裁**。它是 `effective_limit()` 唯一的
    # 上界來源,而「被裁掉」不是任何訊號——只是資料掉了。原本會這樣壞:連續 30 天
    # 沒撞牆且日支出都低於 DAILY_LIMIT(產線停擺或淡季),ceil 老化消失、floor 也不夠高,
    # 天花板無聲回落到**猜的** 19,645,產線恢復那天就少發約 2.9 支長片而且沒有任何錯誤訊號。
    # 這是 08-26「擋人的是我的假天花板」第三次換皮出現。上限仍有界(至多 31 筆)。
    # 🔴 2026-09-03 原本只保護撞牆日,而 `effective_limit()` 自 cefa9ba8 起是
    # `max(ceil, floor_since)` —— **兩個來源,裁切只保護了第一個**。
    # 實測後果:36 天帳本、提額後某天成功花到 31,000(那天不是撞牆日,所以不受保護),
    # 它老化出 30 天窗被裁掉之後 eff 從 31,000 掉回 26,001,少 4,999 units
    # ≈ 2.3 支長片,而且零錯誤訊號。方向是**多擋人**,和 08-26「擋人的是我的假天花板」
    # 同科,也正是 32b1c2f3 自己要治的「資料被裁掉不是訊號」—— 治了 ceil,漏了 floor_since。
    # 保護清單改成向 `_load_bearing_days()` 問,不在這裡複製判準(上限至多 33 筆)。
    if len(d["days"]) > 30:
        _keep = _load_bearing_days(d["days"])
        for k in sorted(d["days"])[:-30]:
            if k not in _keep:
                d["days"].pop(k, None)
    if d.get("_unreadable"):
        # 🔴 帳本正本和 .bak 都解不開時,`_load()` 回的是空殼。這時候寫回去等於
        # 拿一份幾乎空的帳本覆蓋正本,而 save_json_atomic 覆蓋前會先把**現在那份壞檔**
        # 複製成 .bak —— 最後一份可能還救得回來的備份就被壞檔蓋掉了。
        # 少記一筆帳,遠比毀掉唯一的復原點便宜。
        print("[quota] 🔴 帳本讀不到,這一筆不寫回(避免覆蓋掉還能救的 .bak)", file=sys.stderr)
        return b["spent"]
    _save(d)
    return b["spent"]


def _unrecord(op, units, kind="daily"):
    """把一筆已記進 spent 的搬到 rejected 桶(分段上傳只能先收費後才知道結果)。"""
    day = _pacific_date()
    d = _load()
    b = d.get("days", {}).get(day)
    if not b:
        return
    b["spent"] = max(0, int(b.get("spent", 0)) - int(units))
    b["calls"] = max(0, int(b.get("calls", 0)) - 1)
    o = b.get("by_op", {}).get(op)
    if o:
        o["units"] = max(0, o.get("units", 0) - int(units))
        o["calls"] = max(0, o.get("calls", 0) - 1)
    b["rejected_units"] = int(b.get("rejected_units", 0)) + int(units)
    b["rejected_calls"] = int(b.get("rejected_calls", 0)) + 1
    b["rejected_daily_calls"] = int(b.get("rejected_daily_calls", 0)) + (1 if kind == "daily" else 0)
    # 與 record() 的 rejected 分支對稱 —— 漏掉這裡會讓 resumable 上傳
    # （videos.insert 1,600 units，全排程最大宗）**系統性缺席**於分桶，
    # 而缺席的方向剛好會讓「被拒的都是小額呼叫」看起來被證實。
    _ro = b.setdefault("rejected_by_op", {}).setdefault(op, {"units": 0, "calls": 0})
    _ro["units"] += int(units)
    _ro["calls"] += 1
    _save(d)


def _scan(days=None):
    """回 (floor, ceiling, floor_since, ceil_day, since_day):實測推出來的每日上限區間。

    · floor       = **曾經成功花到的最高值**(下界:至少有這麼多)
    · ceiling     = **第一次被拒時的花費水位**(上界:大約就在這裡撞牆)
    · floor_since = 同 floor,但**只算撞牆日(含)之後**的日子(給 effective_limit 用)
    前三者都可能是 None(還沒觀測到);後兩個是「這個上/下界取自哪一天」。

    🔴 2026-09-03 為什麼要回日期:裁帳本時得知道**哪幾天不能裁**,而那個判斷
    原本在 `record()` 裡各寫一份(只保護撞牆日),漏了 `floor_since` 取自的那天。
    參數 `days` 讓 `record()` 能拿「即將寫回去的那份」來問,不必再 `_load()` 一次,
    也就不必在那裡複製一份判準 —— 同一件事兩份實作是這個子系統的慣犯
    (`_is_wall` 就是為了同一個病被抽出來的)。

    🔴 2026-08-26 為什麼要有這支:`DAILY_LIMIT` 原本寫死 10000,而那個數字是**猜的**
    ——memory 裡兩份紀錄互相矛盾(一份說 10,000、一份說實測 ≥18,000)。
    我拿它算 `remaining()`,再拿 `remaining()` 去擋補件工作,整條推論建立在一個
    沒被驗證的常數上。實測結果:08-26 一天花掉 **11,222 units 全部成功、真 403 只有 1 次**,
    而同一天我的預留額度擋下 10 次 —— **擋人的是我的假天花板,不是 YouTube。**
    通則(這個 session 第四次):**拿一個數字去做決策之前,先確認它是量出來的還是猜的。**"""
    _days = days if days is not None else (_load().get("days") or {})
    floor = ceil = None
    _ceil_day = None   # 上界取自哪一天(要挑最近的那天,見下方說明)
    for day, b in _days.items():
        # 標記不可信的日子不能拿來校準:2026-08-25 是在「被拒的呼叫也算進 spent」
        # 那版計量下記的 18,914,把它當下界會讓天花板比真值高一倍。
        # 自我校準吃到污染資料,比寫死一個猜的常數更危險——它看起來像實測。
        if b.get("unreliable"):
            continue
        sp = int(b.get("spent", 0) or 0)
        if sp and (floor is None or sp > floor):
            floor = sp
        # 那天有被拒 → 撞牆點大約就是當天的成功花費(被拒的不算消耗)
        #
        # 🔴 2026-09-01 從 min(跨所有日子) 改成 **取最近一次撞牆那天**。
        # 原本取最小值,前提是「配額是固定的」——而它會變:08-27 在 19,645 撞牆、
        # 09-01 在 24,374 撞牆(Carson 的提額申請在這中間通過)。取 min 的結果是
        # **一道已經不存在的舊牆永久壓住估計值**,自我校準看起來在跑,實際上學不會調高。
        # 撞牆日的成功花費**依定義**就是當天的牆,所以最近那天最有代表性;
        # 用「最近」而不是「最大」,是因為配額也可能被調降,那時要跟著降下來。
        if _is_wall(b):
            if ceil is None or str(day) >= str(_ceil_day or ""):
                ceil, _ceil_day = sp, day
    # 撞牆日(含)之後才成功花到的最高值。effective_limit() 要用的是這個而不是全期 floor,
    # 理由見那支的 docstring。
    floor_since = None
    _since_day = None
    for day, b in _days.items():
        if b.get("unreliable") or (_ceil_day and str(day) < str(_ceil_day)):
            continue
        sp = int(b.get("spent", 0) or 0)
        if sp and (floor_since is None or sp > floor_since):
            floor_since, _since_day = sp, day
    return floor, ceil, floor_since, _ceil_day, _since_day


def observed():
    """回 (floor, ceiling) —— 見 `_scan()`。保留兩元組是因為外部有人在用
    (repo root 的 `scripts/quota_ceiling_watch.py` 就解成兩個值),不要改成三元組。"""
    floor, ceil, *_ = _scan()
    return floor, ceil


def effective_limit():
    """實際拿來算 remaining() 的上限。

    優先序:①觀測到的撞牆點(最緊的上界) ②曾成功花到的最高值(下界,至少有這麼多)
    ③設定值。**永遠不會低於實測到的下界** —— 用一個比實測還低的天花板去擋人,
    正是 08-26 那天發生的事。

    🔴 2026-09-02 修好一個潛伏的矛盾(基建線的 fresh-context 驗證員先看到,我複驗確認):
    原本是 `if ceil: return ceil`,**只要 ceil 存在就完全不看 floor**,和上面那句
    「永遠不會低於實測到的下界」直接打架。發作條件是提額核准之後——某天成功花超舊牆
    但沒撞到新牆,floor 升而 ceil 不動 → 回一道**已經不存在的舊牆**去擋工作,
    就是 08-26 那天「擋人的是我的假天花板」同一個病。
    (09-02 當下 floor == ceil == 26,001,所以這是潛伏不是正在發作。)

    但**不可以**照直覺寫成 `max(ceil, floor)`:配額也可能被**調降**,那時撞牆點會下移,
    而全期 floor 還留著調降前的舊高水位,會永久頂住估計值——那就是 08-27→09-01
    「取 min 學不會調高」的鏡像,同一種病換個方向。
    所以 floor 只採**撞牆日(含)之後**的:提額跟得上、降額也跟得下。"""
    floor, ceil, floor_since, *_ = _scan()
    if ceil:
        return max(ceil, floor_since or 0)
    if floor and floor > DAILY_LIMIT:
        return floor
    return DAILY_LIMIT


def spent(day=None):
    return int(_load().get("days", {}).get(day or _pacific_date(), {}).get("spent", 0))


# 🔴 2026-09-01 **撤銷**同日稍早把 ch3 支出扣進 remaining() 的改動(commit 0d0e37a0)。
# 那個改動建立在一個錯的前提上:「兩個頻道共用同一份配額」。
#
# 真相:**YouTube Data API 的每日配額是按 Google Cloud 專案算的**,不是按頻道也不是按帳號。
# 實查憑證的 client_id 前綴(= project number):
#     youtube_channel/  → claude-morning-report-498407(524513894332)  ← 本檔量的是這個
#     yt_ch2/           → quiet-hour-yt              (881902283633)
# 兩個不同專案 = 兩份互不相干的額度。扣掉對方的支出只會讓自己白白少發片。
#
# (是 ch3 那個 session 指出來的,而且它自己也照我的錯數字改過一版,remaining() 直接變 −4,081、
#  當天一支都發不了,已各自撤回。兩邊都在修一個不存在的問題。)
#
# ⚠️ 但這件事**曾經是真的**:`yt_ch2/client_secrets.old-project.json` 的 project 就是
# 524513894332 —— ch2/ch3 以前跟主頻道共用同一個專案,後來才遷出去。
# 設定會變,而變了之後這裡的假設就會**無聲地錯**。所以留下一道身分斷言:
# 量到的專案不是預期的那個就大聲說,不要默默用錯的帳本推論。
_EXPECT_PROJECT = "524513894332"


def measured_project():
    """本檔的帳實際上在量哪個 Cloud 專案(從 client_secrets 的 client_id 前綴讀)。

    配額是**按專案**算的,所以「這本帳屬於哪個專案」是它唯一的意義來源。
    讀不到回 None —— 呼叫端據此跳過檢查,不因為讀不到就擋人。"""
    try:
        d = json.loads((ROOT / "client_secrets.json").read_text(encoding="utf-8"))
        for k in ("installed", "web"):
            if k in d:
                return str(d[k].get("client_id", "")).split("-")[0] or None
    except Exception:  # noqa: BLE001
        pass
    return None


def assert_project():
    """專案身分變了就回警告字串(呼叫端負責印/推播);一致或讀不到回空字串。

    為什麼需要:ch2/ch3 曾與主頻道**共用**專案 524513894332(見 old-project.json),
    後來遷到 881902283633。哪天有人換回來,兩邊就真的共用一份額度了,
    而這本帳仍會以為整份都是自己的 → 兩邊一起撞牆而互相看不見。"""
    p = measured_project()
    if p and p != _EXPECT_PROJECT:
        return (f"⚠️ 配額帳本量的專案變了:預期 {_EXPECT_PROJECT}、實際 {p}。"
                f"配額按專案算,換專案等於換一份額度 —— 天花板與歷史帳都要重新校準,"
                f"而且要確認有沒有別的頻道跟你共用這個專案。")
    return ""


def remaining(day=None):
    """帳本讀不到時回 0(fail-closed)。

    🔴 2026-09-03 這一行是整個修法的重點。`spent()` 讀到空殼會回 0,於是
    `remaining()` 算出「今天一 unit 都沒花」= 配額全滿,發布閘門放行一整批。
    也就是說**帳本壞掉的後果不是停擺,是超發** —— 發到一半 403、半批成功卻回報成功。
    管花費的閘門,「我不知道」必須等於「先別花」。
    停下來是可回復的(明天再發),超發不是(影片已經上去了、配額已經燒掉了)。
    這個狀態不會靜音:`_load()` 會往 stderr 印,而 09:00 的 daily_health
    有「帳本讀不到」那條檢查會叫。"""
    if _load().get("_unreadable"):
        return 0
    return max(0, effective_limit() - spent(day))


_warned = {"sent": False}


def _maybe_warn(total):
    if _warned["sent"] or total < effective_limit() * WARN_AT:
        return
    _warned["sent"] = True
    # 🔴 2026-09-01 訊息改用 effective_limit() —— 上面的**判斷**本來就用它,
    # 但**顯示**印的是 DAILY_LIMIT 這個舊預設常數(19,645),
    # 於是實際 24,579/26,001 = 94% 會被印成「24579/19645 = 125%」。
    # 一個把 94% 說成 125% 的警報,只會訓練人以後不看它
    # (同日在 quota_budget 修過同型:永遠在響的警報等於沒有警報)。
    _lim = effective_limit()
    try:
        from notify import push
        push("YT 配額警戒",
             f"已用 {total}/{_lim} units("
             f"{total * 100 // max(_lim, 1)}%),配額日 {_pacific_date()}")
    except Exception:  # noqa: BLE001
        pass
    print(f"[quota] ⚠️ 已用 {total}/{_lim}({total * 100 // max(_lim, 1)}%)", file=sys.stderr)



# 單支長片的發布成本(2026-08-29 由當日 by_op 反推:videos.insert 1600 + captions.insert 400
# + thumbnails.set 50 + playlistItems.insert 50 + commentThreads.insert 50)。
PUBLISH_UNIT_COST = 2150


def _reserve_guard(op, units):
    """預留額度守門。**兩個呼叫端(_execute / _charge_once)共用這一份**——
    原本兩處各寫一份一模一樣的判斷式,而 2026-08-31 這一天已經踩了三次
    「同一件事兩份實作、只修了其中一份」,不再留第四個。

    判準是「這次花費**會不會讓還發得出的片數變少**」,不是「剩餘會不會低於 RESERVE」。

    舊判準 `remaining() - units < RESERVE` 在 reserve **還救得回來**時是對的
    (擋住就保得住)。但實測今天響了三次:配額剩 106、RESERVE 2200 —— 106 永遠湊不到
    2200,繼續擋救不回那個 reserve,只是讓 1 unit 的抓留言整個配額日都做不了
    (而抓留言是「知道觀眾想看什麼」的唯一管道)。

    新判準只在「擋住毫無收益」時放寬,擋得住的一個都沒放掉:
        剩 106 / 花 1              → 0 < min(0,1)=0  放行(本來就發不出)
        剩 2500 / RESERVE 2200 / 花 400 → 0 < min(1,1)=1  擋(擋住才保得住那支)
        剩 9000 / RESERVE 9600 / 花 400 → 4 < min(4,4)=4  放行(8600 仍發得出 4 支)
        剩 8700 / RESERVE 9600 / 花 400 → 3 < min(4,4)=4  擋
    """
    if not (units and RESERVE):
        return
    r = remaining()
    now_n = r // PUBLISH_UNIT_COST            # 現在還發得出幾支
    # ⚠️ 要 clamp:Python 的 floor division 會讓 (0-1)//2150 = **-1** 而不是 0,
    # 負數會讓下面的比較反過來(-1 < 0 成立)→ 配額歸零時反而擋在 reserve 訊息上,
    # 而那時該說話的是 ENFORCE 的「配額用盡」。自檢表 rem=0 那格抓到的。
    after_n = max(0, r - units) // PUBLISH_UNIT_COST  # 花下去之後還發得出幾支
    want_n = RESERVE // PUBLISH_UNIT_COST      # reserve 想保住幾支
    if after_n < min(now_n, want_n):
        raise QuotaExhausted(
            f"quota reserve:{op} 需 {units} units,今日剩 {r},"
            f"花下去只剩 {after_n} 支發布額度(要保住 {min(now_n, want_n)} 支)"
            f" → 停在額度線上(冪等,下個配額日接著跑)")

def install(service=None):
    """把計量掛上去。回傳同一個 service(方便 `return install(build(...))` 直接串)。

    攔的是 `HttpRequest.execute` 這個**類別方法**,所以同一個 process 裡任何後續建出來的
    request 都會被算到——包含 googleapiclient 內部自己發的分頁請求。只掛一次(冪等)。"""
    try:
        from googleapiclient.http import HttpRequest
    except Exception:  # noqa: BLE001
        return service
    if getattr(HttpRequest, "_quota_metered", False):
        return service
    _orig = HttpRequest.execute

    def _execute(self, *a, **kw):
        op, units = cost_of(getattr(self, "uri", ""), getattr(self, "method", "GET"))
        # 🔴 **預留額度**:配額日的順序原本是反的——補件工作排 15:25~16:25 先把配額吃光,
        # 主線發布排 18:30 在後面餓死。而發布才是成長引擎(搜尋佔位),補件是修存量。
        # 作法刻意做在這裡、不是逐一改補件腳本的迴圈:那些腳本**本來就都**用
        #   `if "quota" in str(exc).lower(): break`
        # 收尾(冪等、下次接著跑),所以只要丟一個訊息含 "quota" 的例外,它們就會自己
        # 乾淨地停在額度線上——零迴圈改動,也不會有哪支腳本被漏改。
        # 預設 RESERVE=0(行為不變),由 cron 逐行 opt-in:
        #   15:25 的補件 → YT_QUOTA_RESERVE=9600(留給當天 18:30 的 5 支 + 隔天 1 支)
        #   23:00 的補件 → YT_QUOTA_RESERVE=1600(當天發布已完成,只需留隔天那 1 支)
        _reserve_guard(op, units)
        if units and ENFORCE and units > remaining():
            raise QuotaExhausted(f"quota exhausted:{op} 需 {units},今日剩 {remaining()}")
        if getattr(self, "_quota_charged", False):
            return _orig(self, *a, **kw)      # 同一個 request 已由 next_chunk 收過費
        self._quota_charged = True
        try:
            r = _orig(self, *a, **kw)
        except Exception as exc:                      # noqa: BLE001
            # 一般失敗(500/逾時/權限)配額照樣被扣 → 記進 spent;
            # 但 quotaExceeded 是「配額已經沒了所以拒收」,不會再扣 → 記進 rejected 桶。
            if units:
                _k = _quota_reject_kind(exc)
                _maybe_warn(record(op, units, rejected=bool(_k), kind=_k))
            raise
        if units:
            _maybe_warn(record(op, units))
        return r

    HttpRequest.execute = _execute

    # 🔴 分段上傳(resumable)**不會走 execute()**,走的是 `next_chunk()` 迴圈。
    # daily_publish 上傳影片正是這條路(`MediaFileUpload(resumable=True, chunksize=4MB)`
    # + `while ...: req.next_chunk()`),而 videos.insert 是 **1,600 units、全排程最大宗**
    # (一天 6 支 = 9,600)。只攔 execute 的話,帳上會顯示發布花了 0,
    # 補件工作就會以為額度還很多 —— 整個預留機制反而變成幫兇。
    # 一次上傳會呼叫 next_chunk 很多次(每 4MB 一次),所以**只在第一次收費**,
    # 用 request 物件上的旗標記住(配額是按 request 算,不是按 chunk 算)。
    _orig_next = HttpRequest.next_chunk

    def _charge_once(self):
        # ⚠️ 順序有意義,別動:**先檢查 → 通過才設旗標 → 才記帳**。
        # 旗標若設在 raise 之前,同一個 request 被重試(或呼叫端 catch 後重跑)就會被當成
        # 「已收過費」直接放行 = 一次完全沒記帳的 1600 units 上傳。
        if getattr(self, "_quota_charged", False):
            return
        op, units = cost_of(getattr(self, "uri", ""), getattr(self, "method", "GET"))
        _reserve_guard(op, units)
        # ENFORCE 這道原本只寫在 `_execute` 裡 —— 而 resumable 上傳走的是這條路徑,
        # 等於「先觀測後執法」真的打開執法時,漏掉的正好是最大的那一筆。
        if units and ENFORCE and units > remaining():
            raise QuotaExhausted(f"quota exhausted:{op} 需 {units},今日剩 {remaining()}")
        self._quota_charged = True
        if units:
            _maybe_warn(record(op, units))

    def _next_chunk(self, *a, **kw):
        # 這裡是**先收費再上傳**(不能等結果,否則分段上傳每塊都要判一次)。
        # 若上傳因配額用罄被拒,把剛才記的那筆搬到 rejected 桶,別讓帳本灌水。
        _charge_once(self)
        try:
            return _orig_next(self, *a, **kw)
        except Exception as exc:                      # noqa: BLE001
            _k = _quota_reject_kind(exc)          # 只呼叫一次,存起來再用
            if _k:
                op, units = cost_of(getattr(self, "uri", ""), getattr(self, "method", "GET"))
                if units:
                    _unrecord(op, units, kind=_k)
            raise

    HttpRequest.next_chunk = _next_chunk
    HttpRequest._quota_metered = True
    return service


def _report(days=1):
    d = _load().get("days", {})
    for day in sorted(d)[-days:]:
        b = d[day]
        pct = b["spent"] * 100 // max(effective_limit(), 1)
        rj = b.get("rejected_units", 0)
        print(f"\n配額日 {day}(太平洋日;台北 15:00~16:00 換日)  "
              f"{b['spent']}/{effective_limit()} units = {pct}%  呼叫 {b.get('calls',0)} 次")
        if rj:
            print(f"   (另有 {rj} units / {b.get('rejected_calls',0)} 次因配額用罄被拒 —— "
                  f"**不計入實際消耗**,只代表撞牆後還在硬打)")
        for op, o in sorted(b.get("by_op", {}).items(), key=lambda kv: -kv[1]["units"])[:14]:
            print(f"   {o['units']:>6} units  ×{o['calls']:<4} {op}")
    if not d:
        print("還沒有任何記錄(計量器剛裝上,下一次 API 呼叫才會開始記帳)。")
        print(f"目前配額日:{_pacific_date()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()
    _report(args.days)
    d = audit_tables()
    if d:
        print("\n⚠️ 與 quota_budget.COST 價格不一致(事前估與事後量會永遠兜不攏,請修):")
        for name, a, b in d:
            print(f"   {name:<26} quota_meter={a}  quota_budget={b}")
    else:
        print("\n價目表與 quota_budget 對帳一致。")
    fl, ce = observed()
    _f = f"{fl:,}" if fl else "尚未觀測"
    _c = f"{ce:,}" if ce else "尚未觀測"
    print(f"\n每日上限:目前採用 {effective_limit():,}"
          f"(設定值 {DAILY_LIMIT:,} / 實測下界 {_f} / 撞牆點 {_c})")
    print("  ⚠️ 設定值是**猜的**;下界=曾經成功花到的最高值,撞牆點=第一次被拒時的水位。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
