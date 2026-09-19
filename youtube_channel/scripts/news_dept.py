#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""news_dept.py — 金融時事部：抓即時財經/加密新聞 → 判斷有無值得做的大事 → 立刻產相關 Short。

蹭時事＝免費流量。有重大金融時事就**繞過排程立刻產片**（呼叫 produce_batch --topic）。
新聞來源用 Google News RSS（免金鑰）。已報過的時事不重複（news_seen.json）。
誠信鐵則：只講新聞已知事實，不誇大、不預測漲跌、不喊單、不保證收益。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import studio_common as sc  # noqa: E402  共用地基：PERSONA、has_llm_key、evidence_block
STUDIO = ROOT / "STUDIO"
SEEN = STUDIO / "news_seen.json"
TW = timezone(timedelta(hours=8))
PY = sys.executable

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):
        pass

# 與頻道相關的查詢（加密/量化/總經對交易的影響）。
# ── 台股化：加台股大事查詢（保留既有加密查詢，只加不刪），讓時事部也能寄生台股熱點。
# 2026-08-20:移除三條純幣圈查詢(比特幣/加密監管/幣安穩定幣)。抓進來也會被
# _CRYPTO_NEWS_CAP=0 擋掉,留著只是白打 RSS 並稀釋候選池。總經那條保留
# (Fed/CPI 影響台股,是台股時事的題源)。
QUERIES = ["美聯儲 OR 升息 OR 降息 OR CPI",
           "台股 OR 加權指數 大跌 OR 大漲 OR 崩", "除權息 OR 當沖 OR 融資斷頭 OR 跌停",
           "0050 OR 台股ETF OR 高股息", "台積電 OR 護國神山 財報 OR 法說"]
FRESH_HOURS = 18
# 🔴 2026-08-01 從 8 降到 1。原本 8 是「防爆衝的安全上限、幾乎不會卡到」——問題正是它從不卡到。
# 實測(等長 7 天視窗,錨在最後有資料的 07-28):
#   ·頻道總觀看 9,122 → 6,262(**-31%**),而**損失 100% 集中在 Shorts 推薦流**
#     (SHORTS 6,696 → 3,074,-54%);同期搜尋 +95%、訂閱者 +14%、相關影片 +121% 全在漲。
#   ·同一視窗 Shorts 發布量**增加** 41%(22 → 31 支),但每支平均觸及**掉 67%**(304 → 99)。
#     發更多、拿更少 = 演算法降權的典型形狀,而不是內容剛好都不紅。
#   ·本部門在該視窗發了 **18 支(2.6/日)**,佔全頻道發布量 38%,全部是 Shorts;
#     而它繞過 daily_publish 的「1 長 2 短」配比控制,是那個配比被打掉的主因
#     (設計是每天 3 長 2 短,實際變成 4.4 短 2.6 長)。
#   ·~~而且本部門是全頻道表現最差的一條流:近 14 支裡 13 支幣圈、平均 28.7 觀看
#     (唯一那支台股題 101),標題近乎重複(「比特幣暴跌X%!網格參數這樣設」出現 6 次以上)。~~
#   🔴 2026-09-05 推翻上面這半句(獨立驗證員,全歷史 157 支對 565 支):
#     「全頻道表現最差」已經不成立,現在它是全頻道**最好**的 Shorts 類別。
#         進 Analytics Top-200 的機率  時事 26.8%(42/157) vs 其他 Shorts 10.1%(57/565)
#         = **2.65 倍**,且已逼近長片的 35.7%。
#     為什麼結論翻了:上面那句寫於 2026-08-01,母體是「近 14 支、其中 13 支幣圈」。
#     後來 :96 把 _CRYPTO_NEWS_CAP 砍到 0、題材整批換成台股,**組成完全變了**。
#     同一段的後半句(「唯一那支台股題 101」)其實就預告了這個結果,只是沒人回頭改結論。
#     ⇒ 這是「判準沒改,改的是母體」——舊結論會安靜地活下去,因為沒有東西會叫。
#
#   ⚠️ **但停產的裁示不因此改變,而正確的理由是這個**(2026-09-05 督導代 Carson):
#     時事片贏在**觸及**,不贏在**分鐘**,而綁定約束(YPP 4,000 小時)的幣別是分鐘。
#         進榜者每支觀看分鐘中位   時事 105.9 vs 其他 Shorts 108.0  ← 幾乎相同,還略低
#         全母體每支觀看分鐘(區間) 時事 33.1~66.0 / 其他 13.6~57.5 ← 大幅重疊,分不出高下
#                                  長片 320.5~515.4                ← 差一個數量級
#     根因:Shorts 的 avg_dur 被格式鎖死在 18~19 秒,長片是 118 秒。
#     多拿到的觀看次數,乘上一個小 6.6 倍的匯率,就被吃掉了。
#     ⇒ **時事片是好 Shorts,而好 Shorts 換不到 YPP 分鐘。**
#     日後若有人拿「時事片明明有量」要求復原,答案就在這一段:有量是真的,不夠用也是真的。
# 結論:在一個已經不分發你的 feed 裡,繼續灌最差且高度重複的那一批,是在加深降權。
# 降到 1:保留「有大事能即時反應」這個能力(那才是本部門的價值),但停止洗版。
# ⚠️ 這條要跟上面的幣圈每日封頂(_CRYPTO_NEWS_CAP=2)一起看:MAX_PER_DAY=1 之後幣圈封頂
#    多半不會再觸發,那是預期的——先卡總量,幣圈封頂變成第二道保險。
# 2026-08-01 Carson 拍板改 3(我原本設 1)。保留判斷依據供日後檢視:
# 實測本部門近 7 天是 **2.6 支/日**(18 支;單日最高 07-28 的 5 支),
# 所以 3 這個值**只卡得到爆量那天**,日常量幾乎不受限制——洗版的減量會很小。
# 若之後 Shorts feed 沒有回升,這個數字是第一個該再往下調的旋鈕。
MAX_PER_DAY = 3

# 🔴 2026-07-30 幣圈新聞每日封頂。實測(同齡區間 24~96h 比較,避開「老片累積多」的量尺陷阱):
#   幣圈/網格 Shorts 平均 32 觀看(n=9) vs 台股觀念 Shorts 162(n=2)、其他台股 84(n=3)。
#   而本部門近 14 支裡 **13 支是幣圈(93%)**,唯一那支台股題拿到 101 觀看——是 14 支裡最高的。
# 為什麼 QUERIES 已經 4 幣圈 + 4 台股卻還是 93%:幣圈新聞的**數量**遠大於台股新聞,
#   彙整後的標題池被幣圈淹沒,LLM 挑「最大條的」就一直挑到幣圈。**平衡查詢不會產生平衡輸出。**
# 既有的 is_liquidation_hijack 週上限只抓「爆倉/清算」——那 13 支裡只有 1 支帶「爆倉」,
#   等於幾乎全數漏過。所以這裡把範圍放寬到「幣圈新聞」整類,並改成**每日**上限。
# 不是禁掉:幣圈是 Pionex 聯盟的內容基礎(說明欄放邀請碼),斷掉會斷變現線。
# 達標後的處理=把幣圈標題**從池子濾掉**,讓 LLM 去挑最大的台股新聞(而不是整輪放棄浪費產能);
#   濾完真的沒東西才跳過該輪。
# 界線刻意畫在「**幣圈資產**新聞」,不含「網格」這個技法:
#   ①「爆倉/清算」在台股新聞也會出現(融資相關),放進來會在達標後誤濾掉合法台股題
#     ——而且爆倉/清算本來就有 is_liquidation_hijack 那道週上限在管,不需重複。
#   ②「網格」是 Pionex 的產品、也是變現內容的核心;實測那支「Fed放鷹…**臺股**網格避雷」
#     拿到 49 觀看,比幣圈平均(32)好——技法本身沒問題,是幣圈資產題材拖累表現。
_CRYPTO_NEWS_RE = re.compile(r"比特幣|BTC|以太幣|ETH|加密貨幣|加密|幣安|穩定幣|山寨幣|幣圈")
# 🔴 2026-08-20 幣圈時事片封頂 2 → 0(完全停產)。依據是樣本夠大的實測:
#   近一個多月發布滿 7 天的 Shorts,依題材看觀看中位數——
#       台股時事 n= 29  中位 97
#       ETF     n= 82  中位 60
#       幣圈    n=177  中位 **14**      ← 台股時事的 1/7,而且 177 支樣本沒有僥倖空間
#       其他    n=154  中位 6
#   長片同期:個股體檢 144 / 台股時事 123 / ETF 70 / 幣圈 **19**。
#   兩種格式、兩批獨立樣本都指同一個方向,而本檔上面的舊註解其實早就寫過結論
#   (「技法本身沒問題,是幣圈資產題材拖累表現」),只是當時封頂留在 2 沒有歸零。
#   ⚠️ 停的是**幣圈資產**題材,不是網格技法——網格是 Pionex 變現內容的核心,
#   照樣可以用台股標的做(舊註解實測「臺股網格避雷」49 觀看 > 幣圈平均 32)。
#   要恢復請先拿新數據推翻上面的分佈,不要只憑「幣圈有熱度」的直覺。
_CRYPTO_NEWS_CAP = 0      # 幣圈時事片已停產(見上方實測)


def _fetch(query: str):
    url = (f"https://news.google.com/rss/search?q={quote(query)}+when:1d"
           "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=25) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return []
    now = datetime.now(timezone.utc)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("pubDate") or ""
        if not title:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt and (now - dt) > timedelta(hours=FRESH_HOURS):
                continue
        except Exception:
            pass
        src = it.findtext("{http://news.google.com/}source") or ""
        out.append({"title": re.sub(r"\s+-\s+[^-]+$", "", title), "src": src})
    return out


def _load_seen():
    try:
        return json.loads(SEEN.read_text(encoding="utf-8")) if SEEN.exists() else {"ids": [], "dates": []}
    except Exception:
        return {"ids": [], "dates": []}


def _save_seen(seen):
    seen["ids"] = seen["ids"][-300:]
    seen["dates"] = seen["dates"][-30:]
    SEEN.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")


def _today_count(seen) -> int:
    today = datetime.now(TW).strftime("%Y-%m-%d")
    return sum(1 for d in seen.get("dates", []) if d == today)


def _judge(headlines: list[str]) -> dict:
    """請 Claude 從新聞標題中挑出『最值得做、且和量化/加密交易相關』的時事，產出影片角度。"""
    joined = "\n".join(f"- {h}" for h in headlines[:25])
    ev = sc.evidence_block()
    prompt = f"""{sc.PERSONA}
以上是頻道人設(含軟性新定位:照顧怕被割的小白)。你現在是這個頻道的【金融時事編輯】(主攻 Shorts)。
{(ev + chr(10) + chr(10)) if ev else ""}以下是最近的財經/加密新聞標題：
{joined}

判斷其中有沒有「**真正撼動市場、非做不可**」的大事。**門檻要很高，寧可不做也不要做小事**——
✅ 才算重要：比特幣單日 ±8% 以上劇烈波動、爆倉/清算規模上億、Fed 利率決議、CPI 爆表、
   現貨 ETF 重大進展(通過/大額流入流出)、頂級交易所爆雷/倒閉/被駭、國家級重大監管或禁令、Pionex 重大新功能。
   ★台股情境同樣夠格：加權指數單日重挫/崩盤或創歷史新高、財報季爆雷(重大財報遠低於預期/財測下修)、
   除權息旺季(大量除權息、填息貼息討論)、當沖警示(當沖佔比爆量/主管機關示警)、台積電重大財報或法說會。
❌ 不做（回 worthy=false）：日常 1-3% 波動、分析師喊單、例行報導、小幣消息、重複舊聞、純預測性內容、個股喊進喊出。
若有夠格的大事，挑**最重大**的一則，產出影片角度。
【台股角度守則】台股題材一律走「大盤/ETF/當沖避雷·數據拆解」——大盤重挫講風控與定投別恐慌殺、
除權息講填息機率的數據真相、當沖講九成賠的統計避雷；**個股(含台積電)只做數據分析，不喊買賣、不報目標價**。
【避雷框架(核心切角)】大事發生時，正是小白最容易『追高被套、恐慌殺在低點、被詐騙盤/山寨喊單收割』的時刻——
角度請走「這種行情下，小白最容易在此時被割/追高，我帶你怎麼避雷、機器人/網格/風控怎麼幫你不情緒化操作」，
把時事連到頻道的量化/網格/風控觀點，情緒先戳恐懼(會不會又被割)再給安心(這樣做才穩)。
誠信鐵則：只根據標題已知事實，不誇大、不預測漲跌、不喊單、不保證收益。**有疑慮就回 worthy=false**。
【標題公式(務必遵守，否則會被系統退回重寫)】① 必含具體數字/金額/百分比；② 用「損失框架」或「對比/懸念」(如 剩多少、差在哪、vs、你猜)勝過平鋪；
③ **嚴禁**下列已被玩爛的洗版套語(命中一律不採用、換角度重寫)：「(XX億)爆倉…你的網格機器人為什麼還活著/還撐得住」、「勝率9X卻虧光…破產機率公式一秒戳破」這類千篇一律的恐慌模板。要有記憶點、跟別支不重複。
④ ★2026-07 成長衝刺實測(加密爆倉/清算類新聞務必遵守)：**絕不能把新聞事件原封不動當標題/角度**
   (例如單純轉述「XX億爆倉」「空單/空軍歸零」這種天文數字恐慌事實，完播實測僅 24-39%)——
   angle 必須把這則新聞**轉譯成觀眾能代入的個人化反直覺對比或具體後果**(例如：這種單邊行情下，
   常見的網格參數/定投設定會怎樣、跟平常說的「機器人穩賺」有什麼落差)，且結論要能接一個回測/數據觀點，
   不能只停在恐慌情緒轉述。若想不出這種轉譯角度，寧可判 worthy=false，不要硬做。

只輸出 JSON：{{"worthy":true/false,"news":"觸發的新聞重點一句","title":"有點擊慾的影片標題","angle":"切入點：把時事連到量化/網格/風控+小白避雷的觀點"}}"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    txt = llm.complete(prompt, 800, json_mode=True)
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:  # LLM 沒吐 JSON(偶發)→安全默認不做,別炸(對齊 prompt「有疑慮回 false」)
        return {"worthy": False}
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001  JSON 壞掉也一樣安全收尾
        return {"worthy": False}


def main() -> int:
    if not sc.has_llm_key():
        print("[FATAL] 無任何 LLM 供應商 API key", file=sys.stderr)
        return 2
    seen = _load_seen()
    if _today_count(seen) >= MAX_PER_DAY:
        print(f"[時事] 今日已蹭 {MAX_PER_DAY} 支，達上限，跳過。")
        return 0

    headlines = []
    for q in QUERIES:
        headlines += _fetch(q)
    # 去重 + 濾掉已報過的
    uniq, ids_now = [], set()
    for h in headlines:
        hid = hashlib.md5(h["title"].encode("utf-8")).hexdigest()[:10]
        if hid in seen["ids"] or hid in ids_now:
            continue
        ids_now.add(hid)
        uniq.append(h)
    if not uniq:
        print("[時事] 無新鮮新聞。")
        return 0

    # 零成本關鍵字預篩:門檻本來就極高(多數批次全 worthy=false),沒有標題含「大事」字眼就別燒 LLM
    BIG_KW = re.compile(r"暴跌|暴漲|崩盤|爆倉|清算|閃崩|腰斬|歷史新高|跳水|重挫|飆漲|Fed|FOMC|聯準|升息|降息|CPI|通膨|ETF|SEC|監管|禁令|破產|倒閉|駭|被盜|脫鉤|清盤|Pionex|派網|除權息|當沖|加權|萬[點八九]|跌停|漲停|斷頭|融資|法說|財報|財測|護國神山|台股|大盤|00940|00919|00929|00878|投信|外資|買超|賣超|升評|降評|停牌|護盤|\d{2,}\s*%|\$?\d[\d,]{4,}", re.I)
    hot = [h for h in uniq if BIG_KW.search(h["title"])]
    if not hot:
        seen["ids"].extend(ids_now); _save_seen(seen)
        print(f"[時事] {len(uniq)} 則新聞無「大事」關鍵字，零成本略過(不燒 LLM)。")
        return 0

    # 幣圈每日封頂(見檔頭 _CRYPTO_NEWS_CAP 說明):達標就把幣圈標題濾出池子,
    # 讓 LLM 去挑最大的台股新聞。放在 LLM 判斷**之前**,才真的能改變它挑什麼。
    if sc.check_topic_frequency("news_crypto", cap=_CRYPTO_NEWS_CAP, window_days=1):
        _n0 = len(hot)
        hot = [h for h in hot if not _CRYPTO_NEWS_RE.search(h["title"])]
        print(f"[時事] 幣圈今日已達 {_CRYPTO_NEWS_CAP} 支上限 → 池子 {_n0}→{len(hot)} 則"
              f"(只留非幣圈;實測幣圈 Shorts 平均 32 觀看 vs 台股題 84~162)")
        if not hot:
            seen["ids"].extend(ids_now); _save_seen(seen)
            log_ops("時事部", f"幣圈已達每日上限({_CRYPTO_NEWS_CAP}支)且無非幣圈大事，本輪不產片")
            print("[時事] 幣圈已達上限、又沒有非幣圈的大事 → 本輪不產片(把產能讓給台股題)。")
            return 0

    # 產標題若命中洗版骨架/與近期語意重複→重判(最多 3 次),仍不行就不產(2026-07 止血新聞旁路洗版)
    hot_titles = [h["title"] for h in hot]
    recent = sc.recent_titles(80)
    d: dict = {}
    for attempt in range(3):
        try:
            d = _judge(hot_titles)
        except Exception as exc:  # noqa: BLE001
            log_ops("時事部", f"⚠️ 判斷失敗：{str(exc)[:70]}")
            print(f"[FATAL] 判斷失敗：{exc}", file=sys.stderr)
            return 3
        _t = d.get("title") or ""
        if not d.get("worthy") or not _t:
            break  # 不夠份量,不必重判
        if not sc.topic_gate(_t, recent):
            break  # 過閘,採用
        print(f"[時事] 標題撞洗版骨架/語意重複,重判({attempt + 1}/3)：{_t[:36]}")
        d = {}  # 迴圈跑完仍空=放棄本次

    # 不論是否採用，都把這批標題記為已看（避免下次重判同批）
    seen["ids"].extend(ids_now)

    if not d.get("worthy") or not d.get("title"):
        _save_seen(seen)
        log_ops("時事部", "本次無夠份量時事(或標題卡洗版閘)，未產片")
        print("[時事] 無夠份量的大事、或標題過不了洗版閘，不產片。")
        return 0

    title, angle = d["title"], d.get("angle", "")
    # 2026-07 成長衝刺(growth_sprint_plan.md C 段實測)：加密爆倉/清算新聞蹭熱是完播殺手
    # (近一週重複約 6 支，完播僅 24-39%)，設週上限 ≤2 支——本週已達上限就不產(不管這則多即時)，
    # 把曝光/產能讓給 B 段贏家脈絡(台股/ETF/定投對比)。同一個週上限計數器由
    # studio_common.check_topic_frequency/record_topic_produced 統一管理，跟 produce_batch.make_one
    # 對 topic_bank 內時事題的把關共用同一份 state,不論走哪條產線路徑都算在一起。
    if sc.is_liquidation_hijack(title + " " + (d.get("news", "") or "")) and \
            sc.check_topic_frequency("news_liquidation", cap=2):
        _save_seen(seen)
        log_ops("時事部", f"⚠️ 加密爆倉/網格新聞本週已達上限(≤2支)，跳過完播殺手：{title[:36]}")
        print(f"[時事] 加密爆倉/清算類新聞本週已達上限，跳過（不是不重要，是別再洗版完播殺手）：{title[:40]}")
        return 0
    print(f"[時事] 命中：{d.get('news','')[:50]} → 產片《{title[:40]}》")
    if "--dry" in sys.argv:
        print(f"[dry] 角度：{angle[:80]}（測試模式，不實際產片）")
        return 0
    # 立刻產 1 支並『即時發布』（繞過排程，消息面要快）
    rc = subprocess.run([PY, "scripts/produce_batch.py", "--topic", title, "--angle", angle, "--publish"],
                        cwd=str(ROOT)).returncode
    if rc == 0:
        seen["dates"].append(datetime.now(TW).strftime("%Y-%m-%d"))
        # 幣圈計數:只有真的產出才記一筆,供上面的每日封頂計算(記在共用計數器,
        # 和 produce_batch 的 news_liquidation 是不同 tag,不互相干擾)。
        if _CRYPTO_NEWS_RE.search(f"{title} {d.get('news', '') or ''}"):
            try:
                sc.record_topic_produced("news_crypto")
            except Exception:  # noqa: BLE001  記帳失敗不該讓已產出的片流程炸掉
                pass
        log_ops("時事部", f"蹭時事產片：{title[:40]}")
    _save_seen(seen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
