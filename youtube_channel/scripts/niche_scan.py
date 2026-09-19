#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""niche_scan.py — 【第二頻道·利基可攻佔掃描器】用真 YouTube 數據選主題,不靠猜。

## 這支解決什麼
要開第二個頻道,「做什麼主題」是唯一真正重要的決定——選錯主題,產線再強也是白做
(主頻道實測:幣圈題材 32 觀看 vs 台股 84~162,同一條產線差 3~5 倍)。
但網路上的「2026 最賺利基」清單全是 SEO 農場文(跑出「韓國無人機表演」「復古雷鬼專輯」),
不能拿來下這種決定。

本檔沿用 keyword_winnability.py 已驗證的核心觀念——**決定價值的不是「這個主題多大」,
是「需求 ÷ 競爭」**——把它從「單一檔股票」放大到「整個利基」,並補上第二頻道真正要問的問題:

    「在這個主題裡,一個沒人認識的新頻道,有沒有機會贏?」

## 兩次搜尋,量四件事(每個利基 200 配額單位)
A. SERP 模式 (order=relevance,不限日期) = 觀眾真的搜下去看到什麼
   → 競爭密度:前 N 名裡大頻道(訂閱≥10萬)佔比、大媒體/新聞台佔比
   → 寡佔度:前 N 名由幾個不同頻道瓜分(去重頻道數 ÷ N,越低=少數人霸佔)
B. 近 12 個月 order=viewCount = 這個利基最近的天花板在哪、誰打下來的
   → 需求上限:觀看中位數 / 前段觀看
   → 突破證據:訂閱 < BREAKOUT_SUB 的小頻道,有片觀看÷訂閱 ≥ 3(衝出訂閱牆)
   → 新血證據:頻道成立 < 24 個月卻打進榜的比例
   → 長片友善:時長 ≥ 8 分鐘的比例(只有長片觀看分鐘算進 YPP 4000 小時)

## 綜合分怎麼算(全部可從輸出欄位自己重算,不是黑箱)
    winnable = 40×突破率 + 25×新血率 + 20×(1-大頻道佔比) + 15×長片率
再乘上需求係數 demand_mult = clamp(log10(觀看中位數/1000), 0.4, 1.6)。
**不對「有多少人搜」下猜測**(那個數字拿不到),只用拿得到的:誰在上面、他們多大、多新。

## 誠信
所有數字直接來自 YouTube Data API,原始 raw 一併存進快取檔可覆核。
沒抓到資料的利基標 n/a,**不補估計值**。

## 配額
每個利基 2 次 search.list = 200 單位(videos/channels.list 批次各 1 單位可忽略)。
30 個利基 = 6,000 單位。實測本頻道日配額 >=18,000(memory yt-quota-budget-2026-07),
上架一支約 2,050 → 安全。結果永久快取,同一利基不重複探(除非 --refresh)。

用法:
  python scripts/niche_scan.py --list                # 看候選利基清單
  python scripts/niche_scan.py --probe 10            # 探 10 個還沒探過的利基
  python scripts/niche_scan.py --probe 30 --region US --lang en   # 英文市場
  python scripts/niche_scan.py --report              # 排行表(已探過的)
  python scripts/niche_scan.py --report --csv out.csv
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
CACHE = STUDIO / "niche_scan.json"

TOP_N = 25                 # 每次搜尋取的名次深度
BIG_SUB = 100_000          # 「大頻道」門檻
BREAKOUT_SUB = 30_000      # 「小頻道」門檻——第二頻道一年內構得到的規模
BREAKOUT_RATIO = 3.0       # 觀看÷訂閱 ≥3 = 衝出訂閱牆(沿用 outlier_scan.py 的定義)
NEW_CH_MONTHS = 24         # 「新頻道」門檻
LONG_SEC = 8 * 60          # 長片門檻(YPP 觀看分鐘只算長片)
QUOTA_PER_SEARCH = 100

_BIG_MEDIA = ("東森", "非凡", "TVBS", "三立", "台視", "中視", "華視", "民視", "年代",
              "壹電視", "鏡新聞", "公視", "新聞", "News", "NEWS", "工商", "經濟日報",
              "財訊", "天下", "商周", "Yahoo", "moneydj", "鉅亨", "中天", "聯合報",
              "自由時報", "ETtoday", "CNN", "BBC", "CNBC", "Bloomberg", "Reuters",
              "Vice", "Discovery", "National Geographic")

# ── 候選利基 ────────────────────────────────────────────────────────────────
# 每項:(key, 中文名, [查詢詞], 標題過濾詞, 說明/為什麼它在名單上)
#
# ⚠️ 標題過濾詞為什麼是必要的(2026-08-14 敏感度實測,別拿掉):
#     同一個利基換個查詢詞,中位觀看可以差 3000 倍——
#       「保險」→ 中位觀看 1,697,350   「保險 解析」→ 559   「保險 業務 不會說」→ 312
#       「訂閱制」→ 702,929           「訂閱制 浪費 錢」→ 954
#     寬詞會撈到一堆只是碰巧含該詞的無關爆片(娛樂/新聞/影劇),
#     若不過濾,這張表量到的是「我查詢詞下得寬不寬」,不是「這個利基好不好」。
#     故:寬詞 + 高意圖詞各搜一次 → 去重合併 → **只留標題真的含利基詞的片**,
#     並記錄 pollution(被濾掉比例)讓污染程度本身可被看見。
# 刻意覆蓋「錢 / AI / 機率 / 知識 / 生活」五大塊,不預設答案——讓數據自己排序。
NICHES = [
    # ── 錢 ──
    ("scam_expose",   "投資詐騙揭露",     ["投資詐騙", "投資詐騙 手法 拆解"],
     ("詐騙", "詐騙集團", "假投資", "被騙", "騙局", "殺豬盤", "老鼠會", "吸金"), "受害金額巨大、社會需求高"),
    ("subscription",  "訂閱制/消費避雷",   ["訂閱制", "訂閱 取消 省錢"],
     ("訂閱", "月費", "續訂", "省錢", "亂花", "浪費", "退訂"), "受眾最廣、零法規風險、CPM高"),
    ("insurance",     "保險拆解",         ["保險", "保單 該不該買"],
     ("保險", "保單", "壽險", "醫療險", "實支實付", "儲蓄險", "意外險", "投資型保單"), "CPM 全站最高($30-60)、資訊極不對稱"),
    ("realestate",    "房地產/租屋",      ["買房", "租屋 房東 糾紛"],
     ("買房", "房價", "房貸", "租屋", "房東", "預售屋", "中古屋", "看房", "房地產"), "台灣人終身最大筆消費"),
    ("salary_career", "薪水職場/求職",     ["談薪水", "轉職 工程師 薪水"],
     ("薪水", "薪資", "年薪", "面試", "轉職", "求職", "職場", "履歷", "加薪"), "B2B 相鄰、CPM高"),
    ("sidehustle",    "副業實測",         ["副業", "在家賺錢 實測"],
     ("副業", "兼職", "賺錢", "收入", "被動收入", "接案", "斜槓"), "與誠實實測人設天然相容"),
    ("ecommerce_sell","電商賣家實務",      ["蝦皮 賣家", "電商 選品 教學"],
     ("蝦皮", "電商", "選品", "賣家", "開店", "網拍", "出貨", "代購"), "B2B 受眾、他自己做過"),
    ("tax",           "稅務/報稅",        ["報稅", "節稅 技巧"],
     ("報稅", "節稅", "所得稅", "扣除額", "稅務", "國稅局", "綜所稅", "遺產稅"), "季節性強但搜尋意圖極明確"),
    ("creditcard",    "信用卡/銀行優惠",   ["信用卡 回饋", "數位帳戶 利率"],
     ("信用卡", "回饋", "刷卡", "數位帳戶", "銀行", "現金回饋", "哩程"), "聯盟返佣天花板高"),
    # ── AI / 科技 ──
    ("ai_tools",      "AI 工具實測",      ["AI 工具", "ChatGPT 教學 技巧"],
     ("ai", "chatgpt", "claude", "gemini", "midjourney", "人工智慧", "提示詞", "prompt"), "成長最快但已擁擠,要看數據"),
    ("ai_build",      "AI 自製系統紀實",   ["用 AI 做出", "vibe coding 實作"],
     ("ai", "自動化", "vibe coding", "cursor", "自己做", "打造", "系統", "機器人", "agent"), "他真的做出 Jarvis/工作室,有畫面"),
    ("coding_learn",  "程式自學/轉職",     ["程式 自學", "轉職 工程師 心得"],
     ("程式", "coding", "工程師", "自學", "轉職", "python", "前端", "後端", "刷題"), "高黏著、可導課程"),
    ("3c_review",     "3C 開箱評測",      ["筆電 推薦", "手機 開箱 評測"],
     ("筆電", "手機", "開箱", "評測", "推薦", "iphone", "測試", "螢幕", "耳機"), "紅海對照組(拿來當基準線)"),
    ("security",      "資安/個資",        ["個資外洩", "手機 被駭 怎麼辦"],
     ("個資", "外洩", "資安", "駭客", "被駭", "密碼", "隱私", "木馬", "釣魚"), "恐懼驅動、搜尋意圖強"),
    # ── 機率 / 遊戲 ──
    ("case_odds",     "開箱賠率/博弈數學", ["開箱 期望值", "開箱網站 賠率"],
     ("開箱", "期望值", "賠率", "機率", "ev", "抽獎", "rtp", "飾品", "skin"), "他已抓 skin.club 全站 395 箱真賠率"),
    ("gacha",         "手遊抽卡期望值",    ["抽卡 機率", "課金 值不值得"],
     ("抽卡", "課金", "機率", "保底", "十連", "期望值", "儲值", "抽池"), "受眾大、年輕、CPM低"),
    ("lottery",       "彩券/運彩數學",     ["大樂透 機率", "運彩 賠率"],
     ("大樂透", "彩券", "威力彩", "運彩", "賠率", "中獎", "機率", "刮刮樂"), "數學可證偽、題材無限"),
    ("game_economy",  "遊戲經濟學",       ["遊戲 課金 商業模式", "手遊 怎麼賺錢"],
     ("遊戲", "手遊", "課金", "商業模式", "營收", "抽成", "廠商", "營運"), "拆解商業模式,非玩遊戲"),
    # ── 知識 / 紀實 ──
    ("biz_case",      "商業案例興衰史",    ["公司 倒閉 原因", "品牌 衰敗"],
     ("倒閉", "衰敗", "崩盤", "破產", "興衰", "帝國", "品牌", "企業", "為什麼會"), "faceless 主流打法(Real Engineering型)"),
    ("eng_disaster",  "工程災難分析",      ["工程 意外 原因", "大停電 原因"],
     ("停電", "事故", "災難", "崩塌", "爆炸", "工程", "失事", "原因", "斷電"), "他電機系,可講電網/變電所"),
    ("semiconductor", "半導體/台灣產業",   ["半導體 製程", "台積電 技術 解析"],
     ("半導體", "台積電", "晶片", "製程", "晶圓", "先進封裝", "asml", "nm", "光刻"), "台灣人天然優勢,英文市場更大"),
    ("geopolitics",   "地緣政治",         ["地緣政治", "台海 局勢 分析"],
     ("地緣", "局勢", "台海", "戰爭", "外交", "制裁", "軍事", "國際"), "高觀看但立場風險"),
    ("sci_trivia",    "冷知識科普",       ["冷知識", "科普 為什麼"],
     ("冷知識", "科普", "為什麼", "原理", "真相", "解密", "知識"), "紅海對照組"),
    ("truecrime",     "犯罪紀實/懸案",     ["懸案", "真實案件 重建"],
     ("懸案", "案件", "兇手", "命案", "犯罪", "失蹤", "真實", "重建", "審判"), "faceless 最大宗之一"),
    ("psychology",    "心理學/行為經濟",   ["行為經濟學", "心理學 效應"],
     ("心理", "行為經濟", "效應", "認知", "偏誤", "實驗", "人性", "決策"), "可與他的數據人設結合"),
    # ── 生活 ──
    ("fitness_sci",   "健身科學",         ["健身 增肌 科學", "訓練 課表 原理"],
     ("健身", "增肌", "訓練", "課表", "重訓", "肌肥大", "深蹲", "臥推", "減脂"), "他有 GymLog,真數據可用"),
    ("nutrition",     "營養/減脂",        ["減脂 飲食", "營養 迷思"],
     ("減脂", "減肥", "飲食", "營養", "熱量", "蛋白質", "斷食", "瘦身", "迷思"), "YMYL 風險要注意"),
    ("sleep_health",  "睡眠/健康數據",     ["睡眠 品質", "穿戴裝置 健康數據"],
     ("睡眠", "失眠", "深層", "手錶", "心率", "健康", "數據", "作息"), "可量化、裝置數據可實測"),
    ("food_cost",     "料理成本計算",      ["外食 成本", "自己煮 省多少"],
     ("外食", "自己煮", "成本", "省多少", "伙食", "菜錢", "便當", "物價"), "數字驅動、生活化"),
    ("car",           "汽機車",           ["買車 該注意", "電動車 值得買嗎"],
     ("買車", "汽車", "電動車", "機車", "車款", "試駕", "特斯拉", "油耗", "保養"), "高CPM、高客單"),
]

_NICHE_BY_KEY = {n[0]: n for n in NICHES}


def _title_hit(title, terms):
    t = (title or "").lower()
    return any(k.lower() in t for k in terms)


# ── API ─────────────────────────────────────────────────────────────────────
def _svc():
    """唯讀建服務。**絕不回寫 token**(沿用 keyword_winnability.py 的同一顆
    token_manage.json;走 upload_youtube 的 helper 會 invalid_scope 覆蓋產線憑證)。"""
    from keyword_winnability import _svc as _ks
    return _ks()


def _iso_months_ago(months):
    return (datetime.now(timezone.utc) - timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dur(iso):
    """PT1H2M3S → 秒。抓不到回 None(不猜)。"""
    if not iso:
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _search(yt, q, region, lang, order="relevance", after=None):
    kw = dict(q=q, part="snippet", type="video", maxResults=TOP_N,
              regionCode=region, order=order)
    if lang:
        kw["relevanceLanguage"] = lang
    if after:
        kw["publishedAfter"] = after
    r = yt.execute_search(kw) if hasattr(yt, "execute_search") else yt.search().list(**kw).execute()
    out = []
    for it in r.get("items", []):
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        if vid:
            out.append({"vid": vid, "cid": sn.get("channelId"),
                        "ch": sn.get("channelTitle", ""), "title": sn.get("title", "")})
    return out


def _hydrate(yt, rows):
    """批次補 videos.list(觀看/時長) 與 channels.list(訂閱/成立日/片數)。各 1 單位/50 筆。"""
    vids = [r["vid"] for r in rows if r.get("vid")]
    cids = sorted({r["cid"] for r in rows if r.get("cid")})
    vinfo, cinfo = {}, {}
    for i in range(0, len(vids), 50):
        r = yt.videos().list(part="statistics,contentDetails,snippet",
                             id=",".join(vids[i:i + 50])).execute()
        for it in r.get("items", []):
            st = it.get("statistics") or {}
            vinfo[it["id"]] = {
                "views": int(st.get("viewCount", 0)) if "viewCount" in st else None,
                "dur": _parse_dur((it.get("contentDetails") or {}).get("duration")),
                "pub": (it.get("snippet") or {}).get("publishedAt"),
            }
    for i in range(0, len(cids), 50):
        r = yt.channels().list(part="statistics,snippet", id=",".join(cids[i:i + 50])).execute()
        for it in r.get("items", []):
            st = it.get("statistics") or {}
            hidden = st.get("hiddenSubscriberCount")
            cinfo[it["id"]] = {
                "subs": None if hidden else int(st.get("subscriberCount", 0)),
                "vids": int(st.get("videoCount", 0)) if "videoCount" in st else None,
                "since": (it.get("snippet") or {}).get("publishedAt"),
            }
    for r in rows:
        r.update(vinfo.get(r["vid"], {}))
        r.update(cinfo.get(r.get("cid"), {}))
    return rows


# ── 指標 ────────────────────────────────────────────────────────────────────
_KANA = re.compile(r"[぀-ゟ゠-ヿ]")     # 平假名/片假名
_HANGUL = re.compile(r"[가-힯]")

try:                                    # 工作室已裝 OpenCC(簡轉繁安全網)
    from opencc import OpenCC as _OCC
    _S2T = _OCC("s2t")
except Exception:                       # noqa: BLE001
    _S2T = None


def _lang_ok(title):
    """濾掉日文/韓文/簡體。regionCode=TW + relevanceLanguage=zh-Hant **擋不住**這些
    (2026-08-14 實測:「副業」搜到的突破前三名全是日本頻道),不濾的話這張表量到的是
    日本 Shorts 生態,不是台灣市場。簡體判定=s2t 轉換後字串有變 → 原文含簡體字。"""
    t = title or ""
    if _KANA.search(t) or _HANGUL.search(t):
        return False
    if _S2T is not None and _S2T.convert(t) != t:
        return False
    return True


def _months_since(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return (datetime.now(timezone.utc) - d).days / 30.4


def _is_big_media(name):
    return any(k.lower() in (name or "").lower() for k in _BIG_MEDIA)


def _metrics(serp, hot):
    """serp = SERP 模式結果;hot = 近12個月最高觀看結果。回 dict,抓不到的欄位給 None。"""
    m = {}

    # ── 競爭面(從 SERP) ──
    subs = [r["subs"] for r in serp if r.get("subs") is not None]
    m["serp_n"] = len(serp)
    m["big_ch_pct"] = round(sum(1 for s in subs if s >= BIG_SUB) / len(subs), 3) if subs else None
    m["media_pct"] = round(sum(1 for r in serp if _is_big_media(r.get("ch"))) / len(serp), 3) if serp else None
    m["uniq_ch_pct"] = round(len({r["cid"] for r in serp if r.get("cid")}) / len(serp), 3) if serp else None
    m["serp_med_subs"] = int(statistics.median(subs)) if subs else None

    # ── 機會面(從近12個月熱門) ──
    hv = [r["views"] for r in hot if r.get("views") is not None]
    m["hot_n"] = len(hot)
    m["hot_med_views"] = int(statistics.median(hv)) if hv else None
    m["hot_max_views"] = max(hv) if hv else None

    small = [r for r in hot if r.get("subs") is not None and r["subs"] < BREAKOUT_SUB]
    m["small_ch_pct"] = round(len(small) / len(hot), 3) if hot else None
    brk = [r for r in small
           if r.get("views") and r.get("subs") and r["subs"] > 0
           and r["views"] / r["subs"] >= BREAKOUT_RATIO]
    m["breakout_n"] = len(brk)
    m["breakout_pct"] = round(len(brk) / len(hot), 3) if hot else None
    m["breakout_examples"] = [
        {"ch": r["ch"], "subs": r["subs"], "views": r["views"],
         "ratio": round(r["views"] / r["subs"], 1), "title": r["title"][:60]}
        for r in sorted(brk, key=lambda x: -x["views"] / x["subs"])[:3]
    ]

    ages = [_months_since(r.get("since")) for r in hot]
    ages = [a for a in ages if a is not None]
    m["new_ch_pct"] = round(sum(1 for a in ages if a < NEW_CH_MONTHS) / len(ages), 3) if ages else None

    durs = [r["dur"] for r in hot if r.get("dur")]
    m["long_pct"] = round(sum(1 for d in durs if d >= LONG_SEC) / len(durs), 3) if durs else None
    m["med_dur_sec"] = int(statistics.median(durs)) if durs else None

    # ── 綜合分 ──
    # 缺任一主成分就不給總分(標 None),不用 0 頂替——0 會被誤讀成「測過且很差」。
    # 樣本太少的不給分——n=3 算出來的「突破率 33%」是雜訊不是訊號。
    MIN_N = 8
    parts = (m["breakout_pct"], m["new_ch_pct"], m["big_ch_pct"], m["long_pct"])
    if m["hot_n"] < MIN_N or m["serp_n"] < MIN_N:
        m["demand_mult"] = None
        m["winnable"] = None
        m["nascore_reason"] = f"樣本不足(serp={m['serp_n']}, hot={m['hot_n']}, 需≥{MIN_N})"
        return m
    if all(p is not None for p in parts) and m["hot_med_views"]:
        base = (40 * m["breakout_pct"] + 25 * m["new_ch_pct"]
                + 20 * (1 - m["big_ch_pct"]) + 15 * m["long_pct"])
        mult = max(0.4, min(1.6, math.log10(max(m["hot_med_views"], 1) / 1000)))
        m["demand_mult"] = round(mult, 2)
        m["winnable"] = round(base * mult, 1)
    else:
        m["demand_mult"] = None
        m["winnable"] = None
    return m


# ── 快取 ────────────────────────────────────────────────────────────────────
def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(d):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CACHE)


def _collect(yt, queries, terms, region, lang, order, after):
    """兩個查詢詞(寬詞+高意圖詞)各搜一次 → 去重 → 只留標題含利基詞的片。
    回 (已過濾列表, pollution 比例)。pollution = 被濾掉的比例,越高代表這個詞越容易撈到雜訊。"""
    seen, pool = set(), []
    for q in queries:
        for r in _search(yt, q, region, lang, order=order, after=after):
            if r["vid"] not in seen:
                seen.add(r["vid"])
                pool.append(r)
    kept = [r for r in pool if _title_hit(r["title"], terms)]
    pol = round(1 - len(kept) / len(pool), 3) if pool else None
    return _hydrate(yt, kept), pol, len(pool)


def probe(n, region, lang, refresh):
    yt = _svc()
    db = _load()
    after = _iso_months_ago(12)
    done = 0
    for key, name, queries, terms, why in NICHES:
        slot = f"{key}@{region}"
        if slot in db and not refresh:
            continue
        if done >= n:
            break
        try:
            serp, pol_s, raw_s = _collect(yt, queries, terms, region, lang, "relevance", None)
            hot, pol_h, raw_h = _collect(yt, queries, terms, region, lang, "viewCount", after)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {name} 探測失敗:{e}", file=sys.stderr)
            continue
        m = _metrics(serp, hot)
        m["pollution_serp"] = pol_s
        m["pollution_hot"] = pol_h
        m["raw_pool"] = raw_s + raw_h
        db[slot] = {
            "key": key, "name": name, "why": why, "queries": queries, "terms": list(terms),
            "region": region, "lang": lang,
            "probed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metrics": m,
            "raw": {"serp": serp, "hot": hot},   # 原始資料留著可覆核
        }
        done += 1
        w = m["winnable"]
        print(f"  探完 {name:12s} winnable={w if w is not None else 'n/a':<6}"
              f" 樣本{m['serp_n']:>2d}/{m['hot_n']:<2d} 汙染{pol_s}/{pol_h}"
              f"  突破{m['breakout_pct']} 新血{m['new_ch_pct']} 大頻道{m['big_ch_pct']}"
              f" 中位觀看{m['hot_med_views']}")
        _save(db)
    print(f"\n已探 {done} 個利基,耗配額約 {done * 4 * QUOTA_PER_SEARCH} 單位。快取:{CACHE}")


def recompute(region):
    """從快取的原始資料重算指標,**零配額**。加兩道 2026-08-14 才發現必要的過濾:

      ① 語言:濾掉日/韓/簡體(見 _lang_ok)。原本前幾名的「突破證據」全是日本頻道。
      ② 格式:突破/新血/需求全部**只算長片**(≥8分鐘)。
         原本的冠軍是靠 Shorts 撐起來的——冷知識科普那支 535× 是 Shorts,該利基長片率僅 11%。
         但本頻道實測:Shorts 觀看不計入 YPP 4000 小時、且無一支 Short 帶進 >1 個訂閱
         (memory yt-subscription-conversion-format-mismatch / yt-format-pivot-longform)。
         用 Shorts 的爆紅證明「這個利基能贏」= 拿一把量不到目標的尺。
    另外獨立記 shorts_dep(短片依賴度)——它本身就是結論:這個利基的贏家是不是只在短片賽道。
    """
    db = _load()
    n = 0
    for slot, rec in db.items():
        if rec.get("region") != region or not rec.get("raw"):
            continue
        serp_all = [r for r in rec["raw"]["serp"] if _lang_ok(r.get("title"))]
        hot_all = [r for r in rec["raw"]["hot"] if _lang_ok(r.get("title"))]
        long_of = lambda rows: [r for r in rows if r.get("dur") and r["dur"] >= LONG_SEC]  # noqa: E731
        serp, hot = long_of(serp_all), long_of(hot_all)

        m = _metrics(serp, hot)
        m["lang_dropped_serp"] = len(rec["raw"]["serp"]) - len(serp_all)
        m["lang_dropped_hot"] = len(rec["raw"]["hot"]) - len(hot_all)
        m["shorts_dep"] = round(1 - len(hot) / len(hot_all), 3) if hot_all else None
        m["pollution_serp"] = (rec.get("metrics") or {}).get("pollution_serp")
        m["pollution_hot"] = (rec.get("metrics") or {}).get("pollution_hot")
        # 短片賽道的天花板另外留著對照(不進總分,但要看得見)
        sv = [r["views"] for r in hot_all if r.get("views") is not None]
        m["allfmt_med_views"] = int(statistics.median(sv)) if sv else None
        rec["metrics"] = m
        rec["recomputed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec["filters"] = "lang=zh-Hant-only, format=long-only(>=8min)"
        n += 1
    _save(db)
    print(f"已重算 {n} 個利基(零配額;語言+長片過濾)。")


def report(region, csv_path):
    db = _load()
    rows = [v for v in db.values() if v.get("region") == region]
    if not rows:
        print(f"[!] {region} 還沒有探測結果,先跑 --probe")
        return
    rows.sort(key=lambda r: (r["metrics"].get("winnable") is None,
                             -(r["metrics"].get("winnable") or 0)))
    filt = rows[0].get("filters", "(未過濾)")
    print(f"\n=== 第二頻道利基掃描 · {region} · {len(rows)} 個 ===")
    print(f"過濾:{filt}")
    print("winnable = [40×突破率 + 25×新血率 + 20×(1-大頻道率) + 15×長片率] × 需求係數")
    print("-" * 116)
    print(f"{'利基':14s}{'winnable':>9s}{'樣本':>7s}{'突破率':>8s}{'突破數':>7s}"
          f"{'新血率':>8s}{'大頻道率':>9s}{'媒體率':>8s}{'短片依賴':>9s}"
          f"{'長片中位觀看':>13s}{'全格式中位':>12s}{'SERP中位訂閱':>13s}")
    print("-" * 116)

    def f(x, pct=False):
        if x is None:
            return "n/a"
        return f"{x*100:.0f}%" if pct else f"{x:,}" if isinstance(x, int) else str(x)

    for r in rows:
        m = r["metrics"]
        print(f"{r['name']:14s}{f(m.get('winnable')):>9s}"
              f"{str(m.get('hot_n','?')):>7s}{f(m.get('breakout_pct'),1):>8s}"
              f"{f(m.get('breakout_n')):>7s}{f(m.get('new_ch_pct'),1):>8s}"
              f"{f(m.get('big_ch_pct'),1):>9s}{f(m.get('media_pct'),1):>8s}"
              f"{f(m.get('shorts_dep'),1):>9s}"
              f"{f(m.get('hot_med_views')):>13s}{f(m.get('allfmt_med_views')):>12s}"
              f"{f(m.get('serp_med_subs')):>13s}")

    print("\n── 突破證據(小頻道真的衝出訂閱牆的片,前三名利基) ──")
    for r in rows[:3]:
        ex = r["metrics"].get("breakout_examples") or []
        print(f"\n【{r['name']}】搜「{' / '.join(r.get('queries') or [r.get('query', '')])}」")
        if not ex:
            print("   (近12個月無小頻道突破案例)")
        for e in ex:
            print(f"   {e['ch']}({e['subs']:,}訂) → {e['views']:,}觀看 = {e['ratio']}× | {e['title']}")

    if csv_path:
        import csv as _csv
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = _csv.writer(fh)
            w.writerow(["key", "利基", "查詢詞", "winnable", "需求係數", "突破率", "突破數",
                        "小頻道率", "新血率", "大頻道率", "媒體率", "頻道分散度", "長片率",
                        "中位時長秒", "中位觀看", "最高觀看", "SERP中位訂閱",
                        "SERP樣本", "熱門樣本", "汙染率SERP", "汙染率熱門", "在名單上的理由"])
            for r in rows:
                m = r["metrics"]
                w.writerow([r["key"], r["name"], " / ".join(r.get("queries") or []),
                            m.get("winnable"), m.get("demand_mult"),
                            m.get("breakout_pct"), m.get("breakout_n"), m.get("small_ch_pct"),
                            m.get("new_ch_pct"), m.get("big_ch_pct"), m.get("media_pct"),
                            m.get("uniq_ch_pct"), m.get("long_pct"), m.get("med_dur_sec"),
                            m.get("hot_med_views"), m.get("hot_max_views"),
                            m.get("serp_med_subs"), m.get("serp_n"), m.get("hot_n"),
                            m.get("pollution_serp"), m.get("pollution_hot"), r["why"]])
        print(f"\nCSV 已寫:{csv_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--probe", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--recompute", action="store_true",
                    help="用快取原始資料重算(語言+長片過濾),不打 API")
    ap.add_argument("--region", default="TW")
    ap.add_argument("--lang", default="zh-Hant")
    ap.add_argument("--refresh", action="store_true", help="重探已探過的")
    ap.add_argument("--csv", default="")
    a = ap.parse_args()

    if a.list:
        print(f"候選利基 {len(NICHES)} 個(每個探測 400 配額單位):")
        for k, n, q, terms, why in NICHES:
            print(f"  {k:15s} {n:14s} 搜「{q[0]}」/「{q[1]}」— {why}")
        return
    if a.probe:
        probe(a.probe, a.region, a.lang, a.refresh)
    if a.recompute:
        recompute(a.region)
    if a.report:
        report(a.region, a.csv)
    if not (a.probe or a.report or a.recompute):
        ap.print_help()


if __name__ == "__main__":
    main()
