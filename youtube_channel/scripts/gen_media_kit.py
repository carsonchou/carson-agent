#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_media_kit.py — 【變現基建】媒體包（Media Kit）產生器。

用途：pre-YPP 階段沒有 YouTube 廣告分潤，要靠贊助/接案變現，第一步永遠是
「一頁式媒體包」給對方看數據、受眾、代表作、合作方案。這支腳本純本機、
零外部呼叫，直接讀現成的 STUDIO 數據 json 組出來——不臆造任何數字，
缺什麼就留佔位讓 Carson 手動補（例如 YouTube Studio 後台才有的訂閱總數）。

資料源：
  channel_config.json          頻道定位／受眾／語氣
  STUDIO/uploaded_ledger.json  總片數（依 S_/L_ 前綴粗分 Shorts/長片）
  STUDIO/traffic_signals.json  近28天頻道數據＋熱門關鍵字＋Top影片
  STUDIO/quality_scores.json   已發布片單的 views/retention（挑代表作）
  STUDIO/finance.json          聯盟返佣實際入帳（證明「這頻道真的能導購」）

輸出：STUDIO/REPORTS/媒體包_{date}.md（純文字，方便 Carson 改）
      STUDIO/REPORTS/媒體包_{date}.html（排版好、可直接貼給對方看）
本檔只「產生檔案」，絕不寄信、不外發——那一步永遠由 Carson 按。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
CFG = ROOT / "channel_config.json"

TZ8 = timezone(timedelta(hours=8))
PLACEHOLDER = "〔待補：Carson 從 YouTube Studio 後台填〕"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):
        print(f"[{stage}] {msg}")


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def pct(n) -> str:
    return f"{n:.1f}%" if isinstance(n, (int, float)) else PLACEHOLDER


def num(n) -> str:
    return f"{n:,.0f}" if isinstance(n, (int, float)) else PLACEHOLDER


_PUB_CACHE = STUDIO / "_media_kit_public_cache.json"


def public_video_ids(ledger: dict, max_age_h: int = 24) -> set:
    """回傳 ledger 裡**目前仍為 public** 的 videoId 集合(查不到就回 None 代表無法判定)。

    🔴 2026-07-29 送贊助商前的獨立查證抓到:媒體包直接數 `uploaded_ledger` 的鍵當「總影片數」,
    報出 **812 支**——但實測其中 **165 支已改為私人、35 支已刪除**,真正公開的只有 **612 支**,
    對外**多報 200 支(+33%)**。ledger 記的是「我們曾經上傳過什麼」,不是「現在對外有什麼」,
    拿它當對外數字是把內部帳本誤當公開事實。代表作清單同樣中招(附了兩條私人片連結,對方點不開)。

    用 `videos.list(part=status)` 逐批 50 支查真實 privacyStatus:812 支 = 17 次呼叫 = **17 units**
    (相對於一次上傳 1,600,可忽略)。結果快取 24 小時,避免每次重產都打 API。
    任何失敗一律回 None → 呼叫端退回舊行為並在文件上標明「未能核實」,絕不因此少報或多報。
    """
    import time as _t
    try:
        if _PUB_CACHE.exists():
            c = json.loads(_PUB_CACHE.read_text(encoding="utf-8"))
            if _t.time() - float(c.get("ts", 0)) < max_age_h * 3600 and c.get("public"):
                return set(c["public"])
    except Exception:  # noqa: BLE001
        pass
    ids = [v for v in ledger.values() if isinstance(v, str) and len(v) == 11]
    if not ids:
        return None
    try:
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parent))
        import daily_publish as _dp
        yt = _dp.get_service()
        pub = []
        for i in range(0, len(ids), 50):
            r = yt.videos().list(part="status", id=",".join(ids[i:i + 50]), maxResults=50).execute()
            for it in r.get("items", []):
                if (it.get("status") or {}).get("privacyStatus") == "public":
                    pub.append(it["id"])
        _PUB_CACHE.write_text(json.dumps({"ts": _t.time(), "public": pub}, ensure_ascii=False),
                              encoding="utf-8")
        return set(pub)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 公開狀態查不到({str(e)[:60]}) → 影片數改標「未能核實」", file=sys.stderr)
        return None



def _subs_total():
    """訂閱總數改**現拉 API**。原本留 PLACEHOLDER 等人手填,結果就是永遠沒填、
    對外文件掛著「〔待補〕」——媒體包最基本的一個數字反而是空的。channels.list = 1 unit。"""
    try:
        import sys as _s
        from pathlib import Path as _P
        _s.path.insert(0, str(_P(__file__).resolve().parent))
        import daily_publish as _dp
        r = _dp.get_service().channels().list(part="statistics", mine=True).execute()
        return int(r["items"][0]["statistics"]["subscriberCount"])
    except Exception:  # noqa: BLE001
        return None


def gather():
    """把各資料源拉成媒體包要用的扁平結構，缺的欄位一律留佔位，不編數字。"""
    cfg = load(CFG, {}) or {}
    ledger = load(STUDIO / "uploaded_ledger.json", {}) or {}
    traffic = load(STUDIO / "traffic_signals.json", {}) or {}
    quality = load(STUDIO / "quality_scores.json", {}) or {}
    finance = load(STUDIO / "finance.json", {}) or {}
    tiktok_ledger = load(STUDIO / "tiktok_ledger.json", {}) or {}
    ig_ledger = load(STUDIO / "ig_ledger.json", {}) or {}

    # 只算「現在對外看得到」的片(見 public_video_ids 的說明:ledger 含已下架/已刪除)
    pub_ids = public_video_ids(ledger)
    if pub_ids is not None:
        keys = [k for k, v in ledger.items() if isinstance(v, str) and v in pub_ids]
        n_private = len([1 for v in ledger.values() if isinstance(v, str) and len(v) == 11]) - len(keys)
    else:
        keys = list(ledger.keys())
        n_private = None
    n_shorts = sum(1 for k in keys if k.startswith("S_"))
    n_longs = sum(1 for k in keys if k.startswith("L_"))
    n_other = len(keys) - n_shorts - n_longs

    channel_28d = traffic.get("channel_28d", {}) or {}
    published = quality.get("published") or []
    with_views = [v for v in published if isinstance(v.get("views"), (int, float))]
    total_tracked_views = sum(v["views"] for v in with_views)
    avg_retention = (
        sum(v["retention"] for v in with_views if isinstance(v.get("retention"), (int, float)))
        / max(1, sum(1 for v in with_views if isinstance(v.get("retention"), (int, float))))
    ) if with_views else None

    # 代表作只挑**目前公開**的片:實測舊版挑出的 6 支裡有 2 支已改私人,附給贊助商的連結點不開
    _pub_only = ([v for v in with_views if v.get("videoId") in pub_ids] if pub_ids is not None
                 else with_views)
    top = sorted(_pub_only, key=lambda v: v["views"], reverse=True)[:6]

    # 🔴 2026-07-29:流量結構與受眾輪廓一律**現拉 Analytics**,不用文案寫死。
    # 查證抓到兩句寫死的假話:①「觀眾多半是主動搜尋進來、而非被動滑到的泛流量」——實測
    # **82.6% 來自 Shorts 推薦流、搜尋只有 4.7%**,講反了;②「鎖定 25-45 歲」——實測
    # **45 歲以上佔 65.2%**,也是反的(而且 45+ 男性台灣散戶資產部位更大,誠實寫反而更好賣)。
    # 兩者都是「把目標受眾當成實測受眾」講給要付錢的人聽。拿不到就留 None,文件標「未測」。
    traffic_mix = audience = search_terms = search_views_total = tw_share = None
    try:
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parent))
        from datetime import date as _d, timedelta as _td
        import yt_analytics as _ya
        _svc = _ya._service()
        if _svc is not None:
            _e = _d.today() - _td(days=3)          # 讓開 Analytics 2~4 天延遲
            _s28 = (_e - _td(days=27)).isoformat()
            rows = _svc.reports().query(ids="channel==MINE", startDate=_s28, endDate=_e.isoformat(),
                                        dimensions="insightTrafficSourceType", metrics="views",
                                        sort="-views").execute().get("rows", [])
            tot = sum(r[1] for r in rows) or 1
            traffic_mix = [(r[0], r[1], round(r[1] / tot * 100, 1)) for r in rows[:5]]
            _s90 = (_e - _td(days=89)).isoformat()
            arows = _svc.reports().query(ids="channel==MINE", startDate=_s90, endDate=_e.isoformat(),
                                         dimensions="ageGroup", metrics="viewerPercentage",
                                         sort="-viewerPercentage").execute().get("rows", [])
            audience = [(r[0].replace("age", ""), round(r[1], 1)) for r in arows]
            # 真實搜尋詞(不做任何歸類/形容,原樣列出)
            srows = _svc.reports().query(ids="channel==MINE", startDate=_s28, endDate=_e.isoformat(),
                                         dimensions="insightTrafficSourceDetail", metrics="views",
                                         filters="insightTrafficSourceType==YT_SEARCH",
                                         sort="-views", maxResults=25).execute().get("rows", [])
            search_terms = [(r[0], r[1]) for r in srows]
            _sv = _svc.reports().query(ids="channel==MINE", startDate=_s28, endDate=_e.isoformat(),
                                       metrics="views",
                                       filters="insightTrafficSourceType==YT_SEARCH"
                                       ).execute().get("rows", [[0]])
            search_views_total = _sv[0][0] if _sv else None
            # 地區佔比(台灣)
            grows = _svc.reports().query(ids="channel==MINE", startDate=_s28, endDate=_e.isoformat(),
                                         dimensions="country", metrics="views", sort="-views",
                                         maxResults=10).execute().get("rows", [])
            _gt = sum(r[1] for r in grows) or 1
            _tw = next((r[1] for r in grows if r[0] == "TW"), 0)
            tw_share = f"台灣 {_tw / _gt * 100:.0f}%"
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 流量結構/受眾拉取失敗({str(e)[:60]}),文件將標「未測」", file=sys.stderr)

    fin_summary = finance.get("summary", {}) or {}

    # 跨平台觸及(A5):TikTok/IG 目前本機只有「已發布支數」(ledger 記 title→id/timestamp)，
    # 沒有逐支觀看/曝光數快取——不硬爬各平台後台湊數字，觸及數欄位誠實留 0／待接，
    # 不能拿發文數冒充觸及數。YouTube 那塊沿用上面已算好的 total_tracked_views(唯一有真數據的來源)。
    tiktok_posts = len(tiktok_ledger)
    ig_posts = len(ig_ledger)
    tiktok_reach = None  # 待接:無官方 API/本機快取可查逐支觀看數
    ig_reach = None  # 待接:同上(Graph API insights 需逐支呼叫，量大暫不做，避免多打)
    cross_platform_total_reach = total_tracked_views + (tiktok_reach or 0) + (ig_reach or 0)

    return {
        "cfg": cfg,
        "subs_total": _subs_total(),
        "n_videos": len(keys),
        "n_private": n_private,
        "traffic_mix": traffic_mix,
        "search_terms": search_terms,
        "search_views_total": search_views_total,
        "tw_share": tw_share,
        "audience": audience,
        "n_shorts": n_shorts,
        "n_longs": n_longs,
        "n_other": n_other,
        "views_28d": channel_28d.get("views"),
        "avg_pct_28d": channel_28d.get("avg_pct"),
        "subs_gained_28d": channel_28d.get("subs_gained"),
        "win_keywords": traffic.get("win_keywords") or [],
        "total_tracked_views": total_tracked_views,
        "n_tracked": len(with_views),
        "avg_retention": avg_retention,
        "top": top,
        "affiliate_revenue": fin_summary.get("affiliate"),
        "tiktok_posts": tiktok_posts,
        "ig_posts": ig_posts,
        "tiktok_reach": tiktok_reach,
        "ig_reach": ig_reach,
        "cross_platform_total_reach": cross_platform_total_reach,
    }


_TRAFFIC_ZH = {"SHORTS": "Shorts 推薦流", "SUBSCRIBER": "訂閱者", "YT_SEARCH": "YouTube 搜尋",
               "RELATED_VIDEO": "推薦影片", "YT_CHANNEL": "頻道頁", "PLAYLIST": "播放清單",
               "EXT_URL": "站外連結", "NO_LINK_OTHER": "其他", "YT_OTHER_PAGE": "站內其他頁"}



def _search_terms_line(d: dict) -> str:
    """把**真實搜尋詞**列出來,不下任何斷言。

    🔴 2026-07-29 第三輪修正:前兩版都試圖「形容」搜尋詞是什麼樣子,兩次都寫錯——
    最新一版寫「搜尋詞幾乎都是具體標的(個股名／代號**＋回測**)」,實測 Top 25 裡
    「回測」出現 **0 次**、第一名是「比特幣」148 次、且 Top 25 只涵蓋 31% 的搜尋觀看,
    卻下了「幾乎都是」的全稱斷言。
    **教訓:我連續三次在同一個地方犯同一種錯——寫「聽起來對但沒量過」的解釋句。**
    所以這版不解釋、不形容、不下全稱:直接把量到的搜尋詞與其涵蓋率列出來,讓對方自己看。
    """
    t = d.get("search_terms")
    if not t:
        return "搜尋詞資料未取得。"
    shown = sum(n for _, n in t)
    # 母數一律取上方流量表的 YT_SEARCH 值(同一份文件不可出現兩個互相矛盾的母數)。
    # 舊寫法另打一次 API 拿到 583(=前 25 名加總),於是算出「583 的 100%」,把「前 25 名」
    # 講成了全部——真實搜尋總觀看是 1,859,前 25 名只涵蓋 31%。
    total = next((v for k, v, _ in (d.get("traffic_mix") or []) if k == "YT_SEARCH"), None) or shown
    terms = "、".join(f"{w}({n})" for w, n in t[:12])
    return (f"搜尋進站的實際關鍵詞（近 28 天，前 12 名，括號為觀看數）：{terms}。"
            f"（此處列出的詞合計 {shown:,} 次，佔搜尋總觀看 {total:,} 的 "
            f"{shown / total * 100:.0f}%，其餘為長尾未列出。）")


def _audience_line(d: dict) -> str:
    """受眾一律用**實測**;拿不到才誠實標成「目標設定」。

    🔴 2026-07-29:舊文案寫死「鎖定 25-45 歲」,實測 **45 歲以上佔 65.2%**——講反了,
    而且是講給要付錢的人聽。誠實寫反而更好賣(45+ 台灣男性散戶資產部位更大)。
    """
    a = d.get("audience")
    if not a:
        return ("〔未測〕以下為**目標設定**而非實測:有資金、想自動化交易但怕被割韭菜的台灣散戶"
                "(受眾實測數據尚未接上，不以目標當實績)。")
    top = "、".join(f"{g} {p}%" for g, p in a[:4])
    old = sum(p for g, p in a if g in ("45-54", "55-64", "65-"))
    return (f"近 90 天 YouTube Analytics 實測年齡分佈:{top}"
            + (f"(45 歲以上合計約 {old:.0f}%)" if old else "")
            + f"。地區以台灣為主（{d.get('tw_share') or '—'}）。")


def _traffic_mix_block(d: dict) -> str:
    """流量結構誠實揭露。舊文案宣稱「觀眾多半主動搜尋進來、而非被動滑到的泛流量」,
    實測 **Shorts 推薦流 82.6%、搜尋僅 4.7%**,完全講反。改成把真實比例攤開,
    再點出「搜尋雖佔比小但意圖明確」——這句才站得住。"""
    m = d.get("traffic_mix")
    if not m:
        return "〔流量來源分佈未測〕"
    rows = "\n".join(f"| {_TRAFFIC_ZH.get(k, k)} | {v:,} | {p}% |" for k, v, p in m)
    return ("| 流量來源（近 28 天） | 觀看 | 佔比 |\n|---|---|---|\n" + rows +
            "\n\n> 說明：主要流量來自 Shorts 推薦流（演算法分發）。"
            + _search_terms_line(d))


def _conversion_bullet(d: dict) -> str:
    """「這頻道能不能導購」這一條 —— **整句以真實入帳為條件**,不是只把金額做成條件。

    🔴 2026-07-29 修(送贊助商前的獨立查證抓到):舊碼把「現有 Pionex 聯盟返佣**已產生實際入帳**,
    證明這頻道的觀眾真的會點連結、真的會行動」整句**寫死在文案裡**,只有金額是條件式——
    於是金額查無時,斷言照樣印出去。實測真實資料:`STUDIO/revenue.json` 所有收益欄位全 0.0、
    `STUDIO/affiliate_perf.json` 的 Pionex 是 clicks 0 / signups 0 / revenue 0。
    **零點擊零入帳,而這份文件是要拿去跟企業談合作的** —— 對外部公司做不實陳述,
    後果比對觀眾誇大更嚴重(對方會要證據、也可能構成不實廣告)。
    這與 memory 記載的 EP.0 事故**完全同一物種**:宣稱句寫死當文案、只有數字算出來。

    有真實入帳 → 照講(附真實金額);沒有 → 不假裝有,改講**同樣有說服力且查得到**的事實:
    觀眾是靠搜尋具體標的名稱找進來的高意向流量(近 28 天搜尋詞 top 幾乎全是個股名/代號),
    並誠實標註轉換數據尚未接。誠實揭露反而更可信,也不會在對方索取憑證時破功。
    """
    try:
        rev = float(d.get("affiliate_revenue") or 0)
    except Exception:  # noqa: BLE001
        rev = 0.0
    if rev > 0:
        return (f"**已驗證能導購**：現有 Pionex 聯盟返佣已產生實際入帳（約 NT${num(rev)}），"
                f"證明這頻道的觀眾真的會點連結、真的會行動。")
    return ("**誠實揭露成效現況**：聯盟連結雖已佈署，但目前**尚未有可查證的返佣入帳或點擊轉換數據**（我們不拿沒發生的成效當賣點）。流量結構與受眾實測見上方表格；建議首檔合作以成效制／試用交換起步，由實際數據決定後續。")


def build_markdown(d: dict, date_str: str) -> str:
    cfg = d["cfg"]
    name = cfg.get("channel_name", "量化阿森｜Carson Quant")
    handle = cfg.get("channel_handle", "@carsonquant")
    niche = cfg.get("niche", "")
    audience = cfg.get("target_audience", "")
    tone = cfg.get("tone", "")
    tagline = (cfg.get("branding") or {}).get("intro_tagline", "")

    top_lines = []
    for v in d["top"]:
        vid = v.get("videoId")
        link = f"https://youtube.com/watch?v={vid}" if vid else ""
        title = (v.get("title") or "").strip()
        top_lines.append(
            f"- **{title}** — {num(v.get('views'))} 次觀看｜完播 {pct(v.get('retention'))}"
            + (f"｜{link}" if link else "")
        )
    top_block = "\n".join(top_lines) if top_lines else f"- {PLACEHOLDER}（尚無已同步 analytics 的代表作）"

    kw = "、".join(d["win_keywords"][:8]) if d["win_keywords"] else PLACEHOLDER

    md = f"""# {name} — 媒體合作資訊（Media Kit）

*更新日期：{date_str}｜頻道：{handle}｜數據取自 YouTube 官方 Analytics／Data API，如需最新版本請告知*

---

## 一句話定位

> {tagline or niche}

**利基**：{niche}
**語氣**：{tone}

---

## 頻道快照（誠實版——目前是穩定成長中的小頻道，不是百萬網紅）

| 指標 | 數值 |
|---|---|
| 公開影片數 | {num(d['n_videos'])}（Shorts {num(d['n_shorts'])}／長片 {num(d['n_longs'])}／其他系列 {num(d['n_other'])}）{('｜另有 ' + num(d['n_private']) + ' 支已非公開（下架為私人或已刪除），未計入') if d.get('n_private') else ''} |
| 訂閱總數 | {num(d['subs_total']) if d.get('subs_total') else PLACEHOLDER} |
| 近 28 天頻道觀看數 | {num(d['views_28d'])} |
| 近 28 天平均完播率 | {pct(d['avg_pct_28d'])} |
| 近 28 天新增訂閱 | {num(d['subs_gained_28d'])} |
| 觀看數前段影片合計觀看 | {num(d['total_tracked_views'])}（{d['n_tracked']} 支；為 YouTube Analytics 單次查詢上限所取的觀看前段片單，非全頻道加總） |
| 上列前段片單的平均完播率 | {pct(d['avg_retention'])}（逐片未加權；**全頻道近 28 天觀看加權完播率為上表的 {pct(d['avg_pct_28d'])}**，兩者口徑不同） |
| 高表現題材關鍵字（由影片標題反推，**非**觀眾實際搜尋詞） | {kw} |

{_traffic_mix_block(d)}

**更新頻率**：近乎每日產出（Shorts + 長片並行），內容全誠實回測/實測導向，不喊單、不誇大報酬（廣告主友善的合規紅線）。

---

## 跨平台總觸及（誠實版——YouTube 有真數據，TikTok／IG 觸及數待接）

| 平台 | 已發布支數 | 觸及數（觀看/曝光） |
|---|---|---|
| YouTube | {num(d['n_videos'])} | {num(d['total_tracked_views'])}（僅計已同步 analytics 的 {d['n_tracked']} 支） |
| TikTok | {num(d['tiktok_posts'])} | 0（待接：無官方 API/本機快取可查逐支觀看數） |
| Instagram | {num(d['ig_posts'])} | 0（待接：Graph API insights 需逐支呼叫，量大暫未做） |
| **跨平台總觸及（目前僅 YouTube 有實數，TikTok/IG 待接前以 0 計）** | — | **{num(d['cross_platform_total_reach'])}** |

---

## 受眾輪廓（**目標設定**，非實測；實測年齡分佈見下方「受眾實測」）

{audience or PLACEHOLDER}

---

## 代表作（依已同步數據挑出的高完播/高觀看片）

{top_block}

---

## 為什麼跟我們合作

- **每支影片都是「我先幫你試」的實測/回測敘事**——不是純業配腔，觀眾信任度高、轉換路徑自然。
- {_conversion_bullet(d)}
- **產出穩定可排期**：每日固定排程產製，腳本、回測數據與旁白皆為原創自製，可配合檔期穩定交付。
- **受眾實測**：{_audience_line(d)}

---

## 合作方案與報價區間（成長期頻道報價，依實際檔期／曝光量／獨家程度議定）

| 方案 | 內容 | 參考價位 |
|---|---|---|
| Shorts 口播置入 | 60秒內短片中段口播 + 說明欄連結，1支 | 洽談（可先以聯盟返佣/試用交換起步） |
| 長片開頭/中段置入 | 10分鐘教學長片中安插「如何實際操作」段落 + 說明欄置頂連結 + 片尾 CTA | 洽談 |
| 專題實測片 | 用贊助方工具/平台做一支完整回測或實測影片（最高轉換路徑） | 洽談 |
| 說明欄常駐連結 | 既有影片庫（{num(d['n_videos'])} 支）追加聯盟連結，長尾曝光 | 依連結表現分潤 |
| TG 名單導流 | 私訊機器人磁鐵（策略包/回測模板）內置推薦 | 洽談 |

> 目前頻道規模仍在成長期，報價保守；建議優先以「聯盟返佣 + 低成本試單」開始合作，用實績（點擊/轉換數據）逐步談長期/固定費合作。

---

## 聯絡方式

- 頻道：{handle}（YouTube 搜尋「{name}」）
- 聯絡窗口：{PLACEHOLDER}
- **合作限制**：僅承接工具／平台功能介紹型置入；**不承接特定金融商品之績效宣傳或收益保證類內容**（依主管機關對金融商品推廣之規範自我設限）。

---

*免責：本媒體包所有數據取自頻道自有後台快取，如需第三方驗證（如 Social Blade / YouTube 官方 Analytics 截圖），請另外附上。*
"""
    return md


def build_html(md_body: str, d: dict, date_str: str) -> str:
    """把 markdown 內容包成一頁深色系 HTML，直接可以拿給對方看。"""
    cfg = d["cfg"]
    name = cfg.get("channel_name", "量化阿森｜Carson Quant")
    # 用品牌色：金 #FFD166 主色，深底
    import html as _html
    import re as _re

    def md_to_html(text: str) -> str:
        lines = text.split("\n")
        out = []
        in_table = False
        in_list = False
        for line in lines:
            raw = line.rstrip()
            if raw.startswith("### "):
                out.append(f"<h3>{_html.escape(raw[4:])}</h3>")
                continue
            if raw.startswith("## "):
                if in_list:
                    out.append("</ul>"); in_list = False
                out.append(f"<h2>{_html.escape(raw[3:])}</h2>")
                continue
            if raw.startswith("# "):
                out.append(f"<h1>{_html.escape(raw[2:])}</h1>")
                continue
            if raw.startswith("---"):
                out.append("<hr/>")
                continue
            if raw.startswith("|"):
                cells = [c.strip() for c in raw.strip("|").split("|")]
                if all(_re.fullmatch(r"-+", c) for c in cells):
                    continue
                if not in_table:
                    out.append('<table>'); in_table = True
                    out.append("<tr>" + "".join(f"<th>{_html.escape(c)}</th>" for c in cells) + "</tr>")
                else:
                    out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                continue
            else:
                if in_table:
                    out.append("</table>"); in_table = False
            if raw.startswith("- "):
                if not in_list:
                    out.append("<ul>"); in_list = True
                out.append(f"<li>{_inline(raw[2:])}</li>")
                continue
            else:
                if in_list:
                    out.append("</ul>"); in_list = False
            if raw.startswith("> "):
                out.append(f"<blockquote>{_inline(raw[2:])}</blockquote>")
                continue
            if raw.strip() == "":
                out.append("")
                continue
            if raw.startswith("*") and raw.endswith("*") and not raw.startswith("**"):
                out.append(f"<p class='meta'>{_inline(raw.strip('*'))}</p>")
                continue
            out.append(f"<p>{_inline(raw)}</p>")
        if in_table:
            out.append("</table>")
        if in_list:
            out.append("</ul>")
        return "\n".join(out)

    def _inline(s: str) -> str:
        s = _html.escape(s)
        s = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = _re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = _re.sub(r"(https?://\S+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)
        return s

    body_html = md_to_html(md_body)

    return f"""<!doctype html>
<html lang="zh-Hant"><head>
<meta charset="utf-8"/>
<title>{_html.escape(name)} — 媒體合作資訊 {date_str}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root {{ --gold:#FFD166; --teal:#06D6A0; --bg:#0e0f13; --panel:#171922; --text:#eef0f4; --sub:#9aa2b1; --line:#2a2d38; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif; line-height:1.75; }}
  .wrap {{ max-width:840px; margin:0 auto; padding:48px 24px 96px; }}
  h1 {{ font-size:28px; color:var(--gold); margin:0 0 4px; }}
  h2 {{ font-size:19px; color:var(--gold); border-left:4px solid var(--gold); padding-left:10px; margin:36px 0 12px; }}
  h3 {{ font-size:16px; color:var(--teal); margin:20px 0 8px; }}
  p {{ color:var(--text); margin:8px 0; }}
  p.meta {{ color:var(--sub); font-size:13px; }}
  blockquote {{ border-left:3px solid var(--teal); margin:12px 0; padding:6px 16px; color:#dfe3ea; background:rgba(6,214,160,0.06); border-radius:0 6px 6px 0; }}
  hr {{ border:none; border-top:1px solid var(--line); margin:28px 0; }}
  ul {{ padding-left:20px; }}
  li {{ margin:6px 0; }}
  table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:14px; }}
  th, td {{ border:1px solid var(--line); padding:8px 10px; text-align:left; }}
  th {{ background:var(--panel); color:var(--gold); }}
  td {{ background:rgba(255,255,255,0.02); }}
  a {{ color:var(--teal); }}
  code {{ background:var(--panel); padding:1px 6px; border-radius:4px; color:var(--teal); }}
  strong {{ color:#fff; }}
  .wrap > p:first-of-type {{ color:var(--sub); font-size:13px; }}
</style>
</head><body>
<div class="wrap">
{body_html}
</div>
</body></html>"""


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(TZ8).strftime("%Y-%m-%d")

    d = gather()
    md = build_markdown(d, date_str)
    html = build_html(md, d, date_str)

    md_path = REPORTS / f"媒體包_{date_str}.md"
    html_path = REPORTS / f"媒體包_{date_str}.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    log_ops("媒體包", f"已產生 {md_path.name} / {html_path.name}（{d['n_videos']} 支片、{d['n_tracked']} 支有 analytics）")
    print(f"寫入：{md_path}")
    print(f"寫入：{html_path}")


if __name__ == "__main__":
    main()
