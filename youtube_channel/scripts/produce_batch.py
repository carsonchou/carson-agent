#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""produce_batch.py — 自動補產（創作靈感+影片+Shorts部門）。

用 Claude API 寫新腳本 → 免費 Edge TTS 配音 → 渲染成片，把片庫補到目標量。
與每日上架排程接成無限迴圈：補產填庫、上架排程(含審核)出貨。

用法：python scripts\\produce_batch.py [--shorts 4] [--long 1] [--target 15]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops import log_ops
import audit_video
import studio_common as sc  # 共用地基:PERSONA/評分卡禁用骨架 is_banned_skeleton/topic_gate
OUT = ROOT / "output"
# 跨平台 venv python 路徑（Windows: Scripts/python.exe；Linux/雲端: bin/python）
_py_win = ROOT / ".venv" / "Scripts" / "python.exe"
_py_nix = ROOT / ".venv" / "bin" / "python"
PY = _py_win if _py_win.exists() else (_py_nix if _py_nix.exists() else Path(sys.executable))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"  # 便宜、寫腳本夠用

GUARD = ("誠信鐵則：不編造個人損益、不保證收益、不喊單、絕不用『保證賺/穩賺不賠/一定賺』等詞；"
         "聯盟軟推＋風險聲明；教學與觀念為主。頻道＝量化阿森｜Carson Quant，繁體中文，"
         "主題＝量化／自動交易（網格、定投、派網 Pionex、回測、風控）。")

# 量化內容嚴謹標準（蒸餾自 domain-quant-trading skill）：確保用語/公式正確、避開錯誤觀念，
# 內容紮實可信＝頻道差異化。寫到相關主題時務必正確引用，不確定就不要硬講數字。
QUANT_STANDARD = (
    "【量化內容嚴謹標準｜務必正確，這是頻道專業度的命脈】\n"
    "・指標定義要正確：夏普比率=(報酬-無風險利率)/報酬標準差，>1.5 算好；最大回撤=峰值到谷值最大跌幅，<20% 較健康；"
    "卡瑪比率=年化報酬/最大回撤，>1 較佳；勝率高不等於賺，要搭配盈虧比看期望值(期望值=勝率×平均獲利-敗率×平均虧損)。\n"
    "・策略本質要講對：趨勢跟蹤在震盪市虧、均值回歸/網格在單邊趨勢市虧——這就是網格遇單邊行情會賠的根因，別講反。\n"
    "・回測五大陷阱要講對(這是高價值題材)：①過度擬合(參數對歷史過度優化，回測夏普>3常是假的)②前視偏差(用到未來數據，信號要延遲一天)"
    "③生存者偏差(只用現存股票會高估)④忽略交易成本(手續費~0.1%+滑價~0.2%，高換手會被吃光)⑤沒做樣本外測試(資料要切訓練/驗證/測試)。\n"
    "・風控觀念：單筆停損約2%、單一策略不超過總資金20%、Kelly 公式 f*=(p×b-q)/b 實務用 Half-Kelly。\n"
    "・誠實：歷史績效不代表未來；舉例用『假設/示意』，不暗示真實獲利。")

# 爆款腳本心法（蒸餾自 31 支繁中/英文對標競品實證，見 STUDIO/script_playbook.md）。
# 把市場領袖驗證過的鉤子/比喻/誠實護城河/置入手法寫進每一支腳本，這是頻道的差異化武器。
# 注意：這只是「預設/種子」。實際每次製作會即時讀 STUDIO/competitor_playbook.md（競品情報部會更新它），
# 讀不到才退回這份預設 —— 確保競品 playbook 一更新，下一支腳本就吃到最新版。
_DEFAULT_PLAYBOOK = (
    "【爆款腳本心法｜蒸餾自 31 支繁中/英文對標競品實證，務必融入】\n"
    "・開場鉤子（前 2 秒就要，禁制式問候，擇一套用）：①反差去推銷「這不是喊單頻道，我只做能回測驗證的東西」"
    "（Terry 661K 最毒招，先否定自己→可信度爆表）②反共識先破後立「大家都說網格穩賺？我用回測打臉這句」"
    "（懶錢包 102萬）③精確數字+括號懸念「這組網格參數回測勝率 87%（但有個代價你必須知道）」（Rayner 1.79M）"
    "④挑釁反問「你的網格機器人，是設計來盤整賺錢、還是趁你睡覺把本金歸零？」⑤暴利數字+懷疑「這支 bot 標 900% ROI…"
    "是真的還是僥倖？我幫你拆」。\n"
    "・生活化比喻（faceless 無真人魅力，比喻＝記憶命脈；固定同一套世界觀貫穿全頻道）：網格交易＝菜市場大媽／開雜貨店"
    "（便宜囤貨、貴了出貨，賺價差不賭漲跌）；定投 DCA＝每月往存錢罐丟零錢／搭手扶梯慢慢上樓；過擬合＝背考古題背到滾瓜爛熟、"
    "上考場一換題就掛；複利＝滾雪球；最大回撤＝雲霄飛車半路的那段下坡。能用比喻就別丟術語。\n"
    "・差異化硬度：講參數／結論一律用『回測數據』背書（呼應量化定位）；對手全靠個人經驗截圖、無系統化回測，這是你的護城河。\n"
    "・誠實護城河（賽道最稀缺、最圈粉）：主動揭露回撤／勝率／『這策略我也會虧的情況是…』『全市場回測只約 35% 標的會賺，所以要選』；"
    "對手通病＝只曬贏單、報喜不報憂、標題說被動收入內容卻是高槓桿合約——你反著做就贏信任。\n"
    "・Pionex 置入：把『用派網機器人執行這套』寫進『如何實際操作』的必經步驟裡（不是硬插廣告）；片尾單一明確 CTA，全片只收割一次。\n"
    "・結構節奏：先秀成品（回測曲線／結果畫面）再回頭教；同一組乾淨數字（如本金 1 萬＋某參數）從頭走到尾降認知負擔；零廢話、高資訊密度。")

# 完整 A–L 競品心法種子（tracked，會隨 repo 上雲端；STUDIO/ 被 gitignore 拿不到，故種子必須在此）。
SEED_FILE = ROOT / "scripts" / "competitor_playbook_seed.md"


def _seed_playbook() -> str:
    """讀 tracked 的完整 A–L 種子；讀不到才退回上面的精簡內嵌版。"""
    try:
        if SEED_FILE.exists():
            txt = SEED_FILE.read_text(encoding="utf-8").strip()
            if txt:
                return txt
    except Exception:
        pass
    return _DEFAULT_PLAYBOOK


# 每次製作即時讀的競品 playbook 外部檔（競品情報部更新它 → 下次製作自動吃最新版）。
PLAYBOOK_FILE = ROOT / "STUDIO" / "competitor_playbook.md"


_PB_STAMPED = False  # 每個 process 只蓋一次指紋章，避免洗版 log


def _stamp_playbook(txt: str, source: str) -> None:
    """在 cron.log 蓋指紋章：讓你從雲端 log 就看得出這輪製作讀到哪一版 playbook。"""
    global _PB_STAMPED
    if _PB_STAMPED:
        return
    _PB_STAMPED = True
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", txt)
    latest = max(dates) if dates else "無日期"
    try:
        log_ops("讀心法", f"來源={source}｜{len(txt)}字｜最新招式={latest}")
    except Exception:
        pass


def load_playbook() -> str:
    """每次製作即時讀競品 playbook：有外部檔且非空就用它（吃最新更新），否則退回完整 A–L 種子。"""
    try:
        if PLAYBOOK_FILE.exists():
            txt = PLAYBOOK_FILE.read_text(encoding="utf-8").strip()
            if txt:
                _stamp_playbook(txt, "競品外部檔")
                return txt
    except Exception:
        pass
    seed = _seed_playbook()
    _stamp_playbook(seed, "種子退回")
    return seed


# 進修部門每週產的洞察（資料驅動），製作時即時讀來補強。
TRAINING_FILE = ROOT / "STUDIO" / "training_insights.md"


def load_training() -> str:
    """讀本週進修洞察（製作/選題相關），有就回傳一段提示、沒有回空字串。"""
    try:
        if TRAINING_FILE.exists():
            txt = TRAINING_FILE.read_text(encoding="utf-8").strip()
            if txt:
                return "\n\n【本週進修重點｜資料驅動，務必融入】\n" + txt
    except Exception:
        pass
    return ""


def existing_titles():
    out = []
    # 按修改時間倒序：最近生成的在前面，讓 avoid[:N] 優先涵蓋近期題材
    for f in sorted(OUT.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            t = first.replace("# 🎬", "").strip()
            if t:
                out.append(t)
        except Exception:
            pass
    # 從已上架 ledger 讀標題，防止每日重複生成近似題材
    ledger_path = ROOT / "STUDIO" / "uploaded_ledger.json"
    if ledger_path.exists():
        try:
            import re as _re
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            for slug_key in ledger:
                title = _re.sub(r"^[SL]_", "", slug_key)
                title = _re.sub(r"\d{3,5}$", "", title)
                if title:
                    out.append(title)
        except Exception:
            pass
    return out


def queue_size():
    """片庫量＝『未發布』已成片(mp4)或已備妥待渲染(voice.txt)的去重 slug 數。
    ⚠️排除已發布(在 uploaded_ledger 內)的——否則已發布舊片堆在 output 沒清，
    會讓計數爆滿、誤判『庫存已滿』而停止補產（曾因此整個產線停擺）。"""
    published = set()
    try:
        lp = ROOT / "STUDIO" / "uploaded_ledger.json"
        if lp.exists():
            published = set(json.loads(lp.read_text(encoding="utf-8")).keys())
    except Exception:
        pass
    slugs = set()
    for f in OUT.glob("S_*.mp4"):
        slugs.add(f.stem)
    for f in OUT.glob("L_*.mp4"):
        slugs.add(f.stem)
    for f in OUT.glob("S_*.voice.txt"):
        slugs.add(f.name[:-len(".voice.txt")])
    for f in OUT.glob("L_*.voice.txt"):
        slugs.add(f.name[:-len(".voice.txt")])
    return len(slugs - published)


def slugify(title, prefix):
    # 移除半形與全形標點/空白，保留中英數字，檔名乾淨且不過長
    s = re.sub(r'[\\/:*?"<>|\s,.!;:~`@#$%^&*()\[\]{}+=\'。、！？；：「」『』（）【】〈〉《》…．·｜｜，－—‧]+', "", title)[:26]
    return f"{prefix}_{s}"


def load_orders():
    p = ROOT / "STUDIO" / "production_orders.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def pull_topic(kind):
    """從 STUDIO/topic_bank.json 取一個未用、符合格式的題目並標記為已用；無則回 None。
    讀寫一律走 topic_bank.load_bank/save_bank(原子寫+.bak 救命),避免併發寫互毀把整庫洗掉(2026-07 根因修復)。"""
    try:
        import topic_bank as _tb
        import studio_common as _sc
        bank = _tb.load_bank()
    except Exception:
        return None
    if not bank:
        return None
    # 2026-06-27 完播率校正 + 2026-07-02 小白重定位:怕被割的新手向(恐懼/避雷/實測)優先;硬核公式(破產/勝率/夏普,完播10-31%)不在此列
    _NUM_KW = ("新手", "小白", "被割", "被套", "詐騙", "是不是坑", "會不會虧", "安全嗎", "我丟", "我拿",
               "機器人幫我", "踩雷", "別碰", "該不該", "幫你試",
               "定投", "做錯", "無腦", "買在高點", "停利", "微笑", "複利", "72法則", "連輸",
               "停損", "10年", "終值", "實測", "差幾", "虧多少", "幾倍", "回測")
    cand = [t for t in bank if not t.get("used") and t.get("format", "short") == kind]
    # 2026-07 止血:濾掉殘留的洗版濫用骨架題(爆倉還活著/勝率9X破產公式)
    cand = [t for t in cand if not _sc.is_banned_skeleton(t.get("title", ""))]
    # 治本:①乾淨題優先於新聞旁路來源題(修「回測/你的」讓幣圈恐慌題誤命中 _NUM_KW 插隊贏過乾淨題的 bug)
    #       ②同組內再靠「數字戳破直覺」會紅題(完播高)優先;工具教學/純新聞題排後、自然餓死
    def _rank(t):
        _ta = (t.get("title", "") or "") + (t.get("angle", "") or "")
        src = str(t.get("source", "")).lower()
        flag = 0 if str(t.get("category", "")) in FLAGSHIP_CATS else 1  # 旗艦題最優先自動產(破圈押注·稽核B修:原本被墊底餓死)
        news_src = 1 if src in ("news", "hotspot", "breakout", "intel") else 0
        depri = 1 if t.get("deprioritized") else 0  # A5:含輸家詞的題被降權排最後
        seo = 0 if _seo_hit(_ta) else 1             # A2:含高意圖搜尋詞的題優先
        num = 0 if any(k in _ta for k in _NUM_KW) else 1
        return (flag, news_src, depri, seo, num)
    cand.sort(key=_rank)
    if cand:
        t = cand[0]
        t["used"] = True
        try:
            _tb.save_bank(bank)  # 原子寫,不再直接覆蓋
        except Exception:
            pass
        return t
    return None


HOOK_RULES = """
【受眾方向（2026-07-02 新增·偏好非硬性）】多服務一種人：**想被動賺、但怕被割的投資小白**（這是重點方向之一，不是唯一）。
- **能白話就白話**：術語盡量翻成人話（回測=拿歷史行情跑一遍、夏普=賺得穩不穩、網格=機器人低買高賣），第一次出現的名詞順手一句解釋；不必為了白話犧牲該有的乾貨。
- 有一個很好用的角度＝**「我先幫你試、別自己送死」**：阿森用回測往死裡測機器人與做法（是回測、不是真錢實盤，別假稱丟真錢），恐懼（被割/被套/會不會虧光）→安心（我回測過、這坑先幫你踩）。適合就用，不強迫每支都套。
- 開頭痛點多用小白聽得懂的講法勝過丟參數細節。
【完播率＝唯一KPI·鐵律（直接決定流量，逐條遵守）】
0. ★黃金 30 秒三段式開場骨架（這支片的脊椎，務必照走，蒸餾自 179 萬觀看爆款公式）：
   ①前 3 秒「恐懼/痛點」——丟一個『陌生人也立刻懂』的具體損失或反直覺真相，要帶精確數字。範例：「靠感覺進出的散戶，九成在賠錢。」
   ②中段「希望」——點出有個『可回測驗證』的方法能避開，但先不給全部答案，留好奇缺口。
   ③後段「解法」——這時才給做法；工具(派網/參數/設定)只當『解法的執行步驟』帶出，絕不是開頭主題。
1. 第一句(前1秒)就砸出最驚人的「具體數字＋直覺衝突」，0 開場白、0 自我介紹。已驗證爆款範例：
   ·「停損設百分之二，連輸十次，帳戶只剩六成一，你猜多少？」
   ·「同一個策略，切點不同，夏普值差一倍。」
   ·「勝率八成七，帳戶卻還在虧。」
2. 製造「好奇缺口」：開頭丟反直覺結論或數字謎題，**答案留到最後一句才揭曉**，逼觀眾看到底。
3. 全程快節奏、每句一個衝擊點、不鋪陳不繞圈；寧可短(二十到三十秒)也不稀釋。
4. 結尾用一句反轉或重磅數字收（不要平淡總結），**接一句『留言鉤』CTA**(「你的設定是哪種?留言告訴我」或「想要完整回測數據?留言『數據』我私你」)——留言在 Shorts 演算法權重比訂閱高,別只喊訂閱。
4b. ★片內訂閱鉤(所有片必留·輕量·接在留言鉤後,不取代留言鉤):留言鉤之後補一句 ≤20 字的追更式訂閱鉤,綁「系列連續性」而非硬喊——例「這是我回測系列一支,想看下支回測拆什麼先追蹤,不然演算法不會再推你」。訂閱轉換是頻道最大瓶頸(0.29%),但要輕、綁在追更正當性上,別變成討厭的硬喊訂閱。**這是硬性要求:每支結尾『留言鉤+訂閱鉤』兩句都必帶,漏掉訂閱鉤=不合格。**
4c. ★連看鉤(拉 session watchtime·2026演算法核心信號):片尾最後一句用懸念指向同類主題的另一支,把單片觀眾導成連看——例「連停損都不會設?先去看我那支『連輸十次剩多少』再回來」。session 連看時長比單片完播更能沉澱頻道權重。
5. 用具體數字戳破直覺錯誤——但**務必包進「你的__設錯了／你以為X其實Y」的個人具體情境**，不是抽象公式說教(實測:「停損連輸只剩61%,你猜多少」372%重看 vs 抽象「破產機率公式」只10%、看6秒就劃走)。
★陌生人優先（演算法肯不肯推給陌生人的關鍵）：開頭嚴禁丟派網設定／參數細節／小眾術語——沒追蹤過你的人根本不在乎參數，先用『痛點或反直覺結論』把他勾進來，工具一律延後到後段「怎麼做」才出現。
【★完播率實測·爆款 DNA（用你頻道真實 analytics 驗證 2026-06-27，每支至少中兩個開關）】
① 懸念缺口：開頭丟數字謎題／反直覺結論，**答案壓到最後一秒才揭曉**——誘導重看(你最高完播的片都被重看到 200~372%，loop 就是流量)。
② 第二人稱互動：「你的」「你猜」「你以為」「你是不是」把觀眾拉進故事，不是站著講知識。
③ 具體可想像情境：用「一萬元／連輸10次／10年／差3倍」這種有畫面的數字，禁抽象術語與公式名。
④ ★loop 結尾(2026演算法:重看=流量,你最高完播片就是被重看到372%):最後一句呼應/接回開頭第一句,讓結尾自然循環回開頭,觀眾不知不覺重看。例:開頭「連輸十次剩多少?你猜」→結尾「…六成一,回去看你猜對沒」。
★ 對仗金句(至少一句·可截圖轉發):全片至少寫一句結構對稱的對仗/排比金句(例「便宜囤貨,貴了出貨」「不是賺多少,是活多久」「新手賠在追高,老手賠在重倉」),放在轉折或收尾,做成觀眾想截圖轉發、也強化記憶的記憶點。
★ 目標長度 30-45 秒(2026 演算法實證甜蜜點):15秒以下已死(要 100% 完播才過關),30-45秒只要 65% 完播就被推廣。但每 3-4 秒要有新衝擊點/轉折,否則像 EP.0 那樣 47秒只剩 26% 完播。**完播率門檻:30秒內要 65%、30-60秒要 50%,過不了演算法直接停推**。
★ 首選題材(實測高完播)：定投生活化(做錯/無腦買/買在高點/停利/微笑曲線)、停損連敗、複利終值、回測往死裡測機器人的進度。
★ 死亡題材(實測低完播,別碰)：抽象公式說教(破產機率/勝率/夏普「比率」)、純蹭新聞、工具設定教學、選擇指南。
★ 5大鉤子結構(2026 faceless 實證·Paddy Galloway 33億Shorts研究,擇一開場):①大膽斷言「九成人定投都做錯,因為一個沒人講的步驟」②好奇缺口「有個定投陷阱,連十年老手都中」③微故事「我把一萬丟進機器人,三十天後我傻了」④視覺衝擊(開場第一幀就是最大數字/前後對比)⑤直接提問「你是不是也以為定投買在高點一定虧?」。
★ 標題=可搜尋關鍵字(2026 Shorts 搜尋輪播回歸):用觀眾真的會搜的詞(「定投買在高點會虧嗎」勝過「POV:定投時」)。
★ 鐵律目標 VVSA(看完vs滑走)≥70%:前 3 秒滑走率 >40% 這支就死,所以第一句必須是最強的那句,別鋪陳。
6. 誠信不變：不編造損益、不保證收益、不喊單。
7. ★講白話去術語（對完播最直接·2026頂級創作者實證）：術語一律換口語白話——「回測」說「拿歷史行情跑一遍」、「夏普值」說「賺得穩不穩」、「網格套利」說「機器人低買高賣賺價差」、「最大回撤」說「最慘賠多少」、「停利」說「賺夠了就跑」。第一次出現的專有名詞當場用一句白話解釋，寧可囉唆也不要讓陌生人聽不懂而滑走。
"""


LONG_RULES = """
【長片成長鐵律（8-10 分鐘長片專用，蒸餾自 MrBeast／DecodingYT／Greyson 等成長頻道實證）】
★ Intro 三步框架（前 30 秒決定留存，務必照走）：
   ①目標：一句話講「看完你能拿走什麼」，帶具體數字承諾（例「這條網格參數讓回撤少一半」）。
   ②障礙：點出多數人卡在哪、為什麼直覺會做錯（製造好奇缺口）。
   ③解法預告：暗示我有可回測驗證的解法，但先不全給——留到正文逐步揭曉。
★ end reward 防跳出：開頭就預告「最後會給一個 ◯◯（checklist／反直覺數字／完整回測）」，把人拉到最後一刻。
★ 標題＝可搜尋長尾（長片靠搜尋流量起家、不吃帳號權重）：用觀眾真的會搜的詞、關鍵字放開頭。三類有搜尋量題型：
   ①回答問題（「派網網格機器人怎麼設」）②教具體技能（「Pionex 第一次設定教學」）③評測比較（「Pionex vs 幣安 新手選哪個」）。
★ 相對留存：每個段落轉折都要給「繼續看下去的理由」，不鋪陳不繞圈；先秀成品（回測曲線／結果畫面）再回頭教。
★ 主題一致：緊扣單一受眾（想自動化又怕被割的上班族散戶），別離題到不同客群，否則演算法會重置對你的辨識、燒掉累積。
★ 對仗金句（至少一句·可截圖轉發）：正文轉折或結尾至少放一句結構對稱的對仗/排比金句（例「便宜囤貨，貴了出貨」「新手賠在追高，老手賠在重倉」「不是賺多少，是活多久」），做成觀眾想截圖轉發的記憶點，強化本片被分享的機率。
6. 誠信不變：不編造損益、不保證收益、不喊單；理財誇大詞（躺賺／穩賺／一天賺X）一律不用（會被演算法限流）。
"""


EP_RULES = """
【★回測 EP 系列·續集鐵律（本支為「我用回測往死裡測機器人／AI」系列，這是頻道爆款招牌，逐條照走）】
- ★誠實反差鉤（招牌·開場常用）：適時用「別人賣你發財夢，我先用回測把這坑踩死給你看」這類反差當開場——只認數據不賣夢，是本頻道的信任招牌；本支是回測就標明是回測、別假稱丟真錢實盤（但不要自稱沒錢）。
- 前 1.5 秒必含「時間或金錢錨」：第一句就出現「Day X／第 X 天」或「本金 X 萬」，讓陌生人一眼認出這是回測進度。
- 世界觀一致：延續「我用回測往死裡測機器人／AI」的第一人稱設定（是回測、不是真錢實盤），本金、天數、餘額前後連貫，像同一場回測實驗的續集。
- 結尾除 loop 外，必留「續集鉤(cliffhanger)」：最後拋一個未解懸念預告下一集（例「但第 X 天發生一件事，下集見」），再接一個「二選一留言題」逼觀眾選邊（例「你會停損還是加碼？留言告訴我」）。
- **★訂閱追更鉤(EP 系列專屬,直攻訂閱瓶頸)**：cliffhanger 之後、留言題之前,補一句自然的訂閱理由——「這是 EP{X},想知道結局就訂閱追下一集,別錯過」。系列有「追更」正當性,訂閱轉換遠高於一般片(本頻道實證:回測避雷企劃 EP.0 一支就帶 9 訂閱,是爆款短片的 30 倍效率;訂閱=YPP 唯一瓶頸)。留言題與訂閱追更鉤各一句、兩者都要,別互相取代。
- ★續集鉤懸念綁「不訂閱=錯過結局的具體損失」FOMO:把 cliffhanger 的懸念直接綁到訂閱按鈕的即時損失——例「第 X 天帳戶發生的事我只在下集講,現在不追蹤,下次演算法就不會再推你、你就看不到結局」。FOMO(怕錯過)比「請訂閱」有效數倍。
- **★開頭 3 秒回顧上集懸念(承接前情,franchise 連貫)**：第一句在丟時間/金錢錨的同時,用半句話回顧上一集結尾的懸念(如「上集第 X 天那根長黑K之後…」),讓追更觀眾無縫接上、新觀眾也秒懂這是系列回測續集(若有『前情提要』段落請照它給的上集資訊回顧)。
- **★片尾全頻道導流 CTA(把單片流量導成整個系列追更)**：結尾除 loop、續集鉤、訂閱追更鉤外,再補一句「其他實驗 EP1 到 EP{n-1} 都在播放清單,一次追完」的導流句,把單支觀眾導去看整個 EP 系列播放清單(集數以『前情提要』段落給的為準)。
- 用回測進度數字（本金／餘額／報酬%／第幾天）當骨架；畫面會把這些數字做成 HUD 計數器，**旁白務必把這些數字清楚念出來**，否則畫面湊不到數字。
- ★季線連載感(讓 EP 像一季有終點的連續劇,拉追更):每集用一句點出「本季賭注/累計狀態」——本金起點、目前累計報酬、這季的成敗線(如「只要跌破本金這回測就算失敗」),讓追更的人感覺在追一個有結局的故事、不是散裝單集;若『前情提要』段落有季/累計資訊,以它為準。
"""


DEBUNK_RULES = """
【★《拆穿》招牌格式（競品拆解類必走·頻道的打假招牌 franchise，逐條照走）】
- 定位：量化阿森=只認數據、敢說真話的散戶代言人，用回測拆穿割韭菜神話、幫小白避雷；只拆數字與方法，不人身攻擊、不碰瓷造謠、不反過來喊單。
- 命名：短片標題用「《拆穿》｜{神話一句}」；長片用「《拆穿》EP{n}｜{神話}——真回測三刀」。同系列統一收進「拆穿系列」播放清單。
- 開場逐字骨架（前 3 秒）：①點名神話＋具體數字（例「這支『812%程式碼』被 190 萬人看過」）②誠實反差鉤（招牌·例「別人吹它能賺，我照著用回測往死裡跑，虧 33%——今天拆給你看」）。
- 三幕結構：神話（對手宣稱什麼）→ 真回測三刀（①過擬合：漂亮曲線是不是硬湊參數湊出來的②手續費滑價：把成本算進去還剩多少③倖存者偏差：只秀贏的、沒秀死掉那批；擇 1-3 刀往死裡砍）→ 避雷結論（新手到底該怎麼閃）。
- 結尾：留言鉤「下支拆哪個神話？留言點題」＋ 訂閱追更鉤（綁系列連續性、別硬喊）＋ 連看鉤，最後可 loop 回開頭那個神話數字。
- 誠信：只拆對手公開的數字與方法，對事不對人；自己的回測結果不誇大、不保證收益、不喊單。
"""


CURRICULUM_RULES = """
【★指標/策略教學 EP 格式（TradingView 全攻略課程·由淺入深·逐條照走）】
- 定位：量化阿森教技術指標/策略，但絕不當聖杯——教你怎麼看 → 用回測驗證真實勝率 → 揭露它什麼時候會騙你。這是「誠實技術教學」，跟《拆穿》同一套 DNA。
- 命名：標題含指標/策略名＋可搜尋詞（例「RSI 是什麼？3 分鐘看懂＋回測揭真相」「MACD 黃金交叉能賺嗎？回測 10 年打臉」）。
- 開場前 3 秒：點名這集教什麼＋一個反差鉤（例「大家都用 RSI 抄底，但我回測 10 年發現它在這種行情會害死你」）。
- 三段結構（務必照走）：①教學：3 句白話講清「它在算什麼、怎麼看」，新手也懂、用生活比喻②回測驗證：「但它真的能賺嗎？」用回測講真實勝率/報酬/回撤，別當神器③陷阱：「它什麼時候會騙你」——講清失效情境（均線在震盪市被巴、RSI 在單邊行情鈍化、指標背離的假訊號）。
- 誠信：教學用語與公式務必正確、不確定不硬講；回測數字用「示意/假設」不暗示真實獲利；不喊單、不保證收益。
- 結尾：留言鉤「下集想學哪個指標/策略？留言點題」＋ 訂閱追更鉤（系列連續性）＋ 連看鉤（指向同系列上/下一集）。
"""


TW_STOCK_RULES = """
【★台股招牌爆款格式（台股/大盤/ETF/個股題材必走·逐條照走）】
- 定位：量化阿森=只認數據、幫台股小白避雷的散戶代言人。用台股歷史回測與真實數據拆神話，**只做數據/財報/籌碼分析，絕不喊單、不報明牌、不喊目標價、不保證會漲會賺**（喊單=限流+砸信譽的紅線，零例外）。
- 開場前 3 秒：直接砸台股具體神話數字＋恐懼/反直覺，0 開場白、0 自我介紹。範例：「ALL IN 0050，十年真能賺一千八百萬？」「無腦存股，結果套在一萬八千點山頂」「當沖九成畢業，你以為你是那一成？」——先痛點/反直覺勾住陌生人，數據壓後面才給。
- 五種必爆骨架擇一（可與《拆穿》疊加）：
   ①回測打臉：你以為穩賺的做法，用台股 10～20 年歷史回測，其實少賺一大截／甚至跑輸大盤（例：某擇時法回測 20 年少賺 60%）。
   ②爆倉被套鬼故事：先講恐懼（空軍 X 億歸零／存股套在山頂／當沖畢業），情緒先行，再用數據解釋為什麼會這樣。
   ③神話數字三刀拆：把一個嚇人的報酬數字拆成——過度擬合（曲線硬湊）／成本沒算（手續費、證交稅、滑價）／倖存者偏差（只秀活下來那批）。
   ④反直覺對比：定期定額 vs 一次 All in、0050 vs 台積電、高股息(0056/00878) vs 市值型(0050)、大盤擇時 vs 長抱不動——用真回測數字比給你看。
   ⑤陷阱揭露：除權息填不填息、當沖稅費吃掉多少、融資斷頭怎麼發生、財報三率話術、殖利率陷阱（賺股息賠價差）。
- ★數據鐵律：一律用台股歷史回測／真實數據說話，抓不到數據就用「示意」講清楚是示意，不暗示真實獲利。個股只做數據/財報/籌碼客觀分析，**絕不喊「會漲、快買、目標價 X 元、這支穩賺」**。
- 在地語彙加權（讓台股觀眾秒認是自己人）：大盤、加權指數、0050、0056、00878、00929、006208、存股、當沖、除權息、填息、融資、法人、外資、投信、護國神山、萬八山頂——自然帶入。
- 避雷收尾＋loop 呼應開頭那個神話數字＋訂閱鉤（硬性：留言鉤＋追更式訂閱鉤兩句都要）。收尾定調「我先幫你用數據試過，別自己送死」，不喊單、只給避雷結論。
- 誠信：所有回測/數據標「歷史回測，非未來保證」；不編造精確數字、不保證收益、不喊單、不報明牌。
"""

AI_SAVINGS_RULES = """
【★「聰明用 AI」誠實比較格式（AI省錢/便宜用AI/共享帳號題材必走·逐條照走）】
- 定位：量化阿森=幫你避雷的數據宅。用「我全試過」的誠實比較,拆穿「便宜用 AI」各種省錢法的真實成本與風險——**這是資訊比較,不是推銷**。
- 開場前 3 秒：砸痛點/反直覺（如「Claude 一個月一百鎂太貴？」「便宜共享帳號真能省八成、但會不會被 ban？」）勾住,0 開場白。
- 核心必講：把便宜用 AI 分成幾種方法（官方訂閱／第三方共享合租／走 API／免費額度）,每種**老實講成本＋風險**。第三方共享（如 PremLogin）**務必明講**：非官方、帳號可能被官方停用,想省錢的自己評估風險——不是叫人快買。
- ★誠信鐵律：**絕不說「快去買、最划算快搶、穩賺、一定能用」**；共享帳號一律標「第三方·非官方·可能被停用·自負」。角度=拆穿/實測/幫你試/避雷,守住避雷品牌。你賣的是資訊價值,不是騙小白。
- 收尾：給「要穩就走官方、要省又能扛風險就自己評估」的中性建議＋訂閱鉤＋導 TG「打省AI領便宜用AI全攻略」。
"""

FLAGSHIP_CATS = {"AI公司揭密"}

AI_COMPANY_RULES = """
【★「AI 公司揭密」旗艦揭密格式(獨家護城河·逐條照走)】
- 定位:量化阿森本人真的用 Claude Code 開了一整間全自動 AI 公司(多個 AI 部門+量化+決策中心+自我優化飛輪)經營這個頻道。全世界幾乎沒人有這種真實系統,揭密它的運作與翻車=天然高分享性。
- 開場前 3 秒:丟本系統一個真實反直覺數字(從【本系統真實數據】拿),例:「我讓 AI 開的公司自己跑,產出上百支片,但真正紅的沒幾支——為什麼?」
- 核心:誠實揭運作(部門怎麼分工、飛輪怎麼自己選題)+誠實揭限制/翻車(AI 會擺爛/選錯/想洗版被我擋)。**反造神**:不吹「AI 全自動躺賺」,講真實的難。
- 誠信鐵律:不喊單、不報明牌、不保證收益、不誇大頻道規模;講的都是可查證的真實數字。護城河=我真的在跑這套,不是空談概念。
- 收尾:訂閱鉤(想看這套 AI 公司下一步/翻車實錄先追蹤)。
★【本題專注·嚴禁混題/編數字(旗艦最常翻車,務必守)】:①**只講「這個題目」本身的故事**,絕不硬塞「87%勝率回測」「過度擬合」「網格機器人」這類與本題無關的通用避雷內容來湊字數——那會變成兩題混在一起的四不像。②數字**只能用【本系統真實數據】給的**(訂閱37是『訂閱數』,絕不可曲解成『507支只有37支能用』);沒給的數字寧可不講也絕不編造。
"""


def _system_facts():
    """組『本系統真實數據』一段注入旗艦 prompt(真憑實據不虛構;缺檔靜默略過)。"""
    facts = []
    S = ROOT / "STUDIO"
    try:
        q = json.loads((S / "quality_scores.json").read_text(encoding="utf-8"))
        pub = len(q.get("published", []) or [])
        if pub:
            facts.append(f"這套 AI 系統至今已產出並發布約 {pub} 支影片")
    except Exception:  # noqa: BLE001
        pass
    try:
        ts = json.loads((S / "traffic_signals.json").read_text(encoding="utf-8"))
        win = ts.get("win_keywords") or []
        if win:
            facts.append("飛輪自動分析出目前高流量的題材關鍵字:" + "、".join(map(str, win[:6])))
    except Exception:  # noqa: BLE001
        pass
    try:
        yp = json.loads((S / "ypp_progress.json").read_text(encoding="utf-8"))
        e = (yp.get("early") or {}).get("subs") or {}
        if e.get("cur") is not None:
            facts.append(f"目前訂閱 {e['cur']}、離 YPP 提前解鎖級還差 {e.get('gap')}(誠實現況,不美化)")
    except Exception:  # noqa: BLE001
        pass
    if not facts:
        return ""
    return "\n【本系統真實數據(旗艦片用真憑實據,絕不虛構;講不出來的就別編)】\n- " + "\n- ".join(facts)


CHCFG = ROOT / "channel_config.json"


def _ai_savings_cfg():
    """讀 channel_config.ai_savings。缺/壞 → None(呼叫端靜默跳過,不影響其他片)。"""
    try:
        c = json.loads(CHCFG.read_text(encoding="utf-8"))
        s = c.get("ai_savings")
        return s if isinstance(s, dict) and s.get("affiliates") else None
    except Exception:  # noqa: BLE001
        return None


def _is_ai_savings_topic(topic):
    """題目是否屬『聰明用 AI』franchise(category 命中 或 標題含便宜用AI關鍵字)。"""
    s = _ai_savings_cfg()
    if not topic or not s:
        return False
    if any(c in str(topic.get("category", "")) for c in s.get("franchise_categories", [])):
        return True
    _kw = ("便宜用 AI", "便宜用AI", "共享帳號", "共享 AI", "AI 省錢", "AI省錢", "省錢用 AI",
           "Claude 便宜", "ChatGPT 便宜", "Gemini 便宜", "拼車", "合租", "便宜共享")
    return any(k in str(topic.get("title", "")) for k in _kw)


def _ai_savings_desc_block():
    """組 franchise 片描述要附加的『誠實比較 + 聯盟連結 + 揭露語』(確定性,不靠 LLM 排版,保證揭露不被吞)。"""
    s = _ai_savings_cfg()
    if not s:
        return ""
    lines = ["", "──────────", "💡 便宜用 AI 的方法（我全試過·誠實比較,非推銷）："]
    for a in s.get("affiliates", []):
        label = a.get("label") or a.get("name", "")
        url = (a.get("url") or "").strip()
        lines.append(f"・{label}：{url}" if url else f"・{label}")
    disc = s.get("disclaimer", "")
    if disc:
        lines += ["", disc]
    return "\n".join(lines)


TW_FACTS = ROOT / "STUDIO" / "tw_stock_facts.json"


def _load_tw_facts():
    """讀 STUDIO/tw_stock_facts.json（真回測數據）。檔不存在/壞掉 → 回 None，呼叫端靜默跳過。"""
    try:
        if not TW_FACTS.exists():
            return None
        return json.loads(TW_FACTS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _tw_facts_context(facts, topic):
    """把 tw_stock_facts 挑與本題材相關的真數字，拼成一段可注入寫稿 prompt 的實證區塊。
    無 facts / 挑不到相關 → 回空字串，呼叫端不注入（台股題照 TW_STOCK_RULES 產示意數字）。"""
    if not facts or not isinstance(facts, dict):
        return ""
    text = (str(topic.get("title", "")) + " " + str(topic.get("category", "")) +
            " " + str(topic.get("angle", ""))) if topic else ""
    as_of = str(facts.get("as_of", ""))
    lines = []
    # 各項回測結果都掛在 facts 下（由 tw_stock_data.py 產）；抓不到的項為 None，跳過不用。
    # 用關鍵字挑與題材相關的項，題材泛台股則全給（限量避免 prompt 爆）。
    _pick_all = any(k in text for k in ("台股", "大盤", "0050", "存股", "ETF")) or not text.strip()
    cand = facts.get("results") or facts.get("backtests") or {}
    if isinstance(cand, dict):
        for key, item in cand.items():
            if not isinstance(item, dict):
                continue
            desc = str(item.get("desc") or item.get("label") or key)
            summary = item.get("summary")
            if not summary:
                continue
            # 題材過濾：對比類題材（All in/定投/高股息/擇時）挑對應項，泛台股全給
            _match = _pick_all or any(
                kw in text for kw in (item.get("keywords") or []) if isinstance(kw, str))
            if _match:
                lines.append(f"  ·{desc}：{summary}")
    if not lines:
        return ""
    lines = lines[:6]  # 限量：最多 6 條，避免撐爆 token
    body = "\n".join(lines)
    return (f"\n【本片實證數據（台股歷史回測，非未來保證；資料截至 {as_of}）】\n{body}\n"
            "（以上為真實歷史回測數字，旁白引用時務必標明是『歷史回測、不代表未來』；"
            "不得據此喊單/報明牌/喊目標價/保證獲利。抓不到的數字寧可用示意也不編造。）")


def call_claude(kind, avoid, topic_override=None):
    orders = load_orders()
    # 時事優先：有指定題目（金融時事）就用它，否則從題庫抽；題庫空了才自由發揮
    topic = topic_override or pull_topic(kind)
    assign = ""
    if topic and topic_override:
        assign = (f"\n【🔥金融時事·優先製作，務必照此主題】：{topic.get('title','')}　切入點：{topic.get('angle','')}"
                  "（這是即時財經時事：緊扣新聞點，再連到頻道的量化/網格/派網/風控觀點；"
                  "只講已知事實、不誇大、不預測價格漲跌、不喊單、不保證收益）")
    elif topic:
        assign = (f"\n【本支指定題目（題庫派發，務必照此主題寫，標題可潤飾更有點擊慾）】："
                  f"{topic.get('title','')}　切入點：{topic.get('angle','')}")
    bias = ""
    if orders:
        pk = "、".join(orders.get("preferred_keywords", [])[:8])
        pm = "；".join(orders.get("produce_more", [])[:6])
        av = "、".join(orders.get("avoid_topics", [])[:8])
        if pk or pm:
            bias = f"\n【決策部門指令】優先方向：{pm}。偏好關鍵字：{pk}。" + (f"避免題材：{av}。" if av else "")
    if kind == "short":
        spec = ("一支 30–45 秒直式 Shorts(2026 演算法甜蜜點;15秒以下已死,因為要 100% 完播才過得了門檻)。"
                "voice_text 150–220 字、前 2 秒就是鉤子、講清一個觀念但每 3-4 秒一個新衝擊點/轉折維持完播、"
                "結尾用留言鉤『你是哪種?留言告訴我』或『想要完整回測數據?留言「數據」我私你』(留言權重比訂閱高)。segments 給 2 段。")
    else:
        spec = ("一支 8–10 分鐘長片。voice_text 1300–1700 字（HOOK→正文 4–5 段→軟性 CTA 訂閱+派網→下集預告）。"
                "segments 給 4–5 段。")
    # playbook/training/avoid 限長：原本 playbook 近萬字，會撐爆 token(成本高、Groq 免費版直接 413)。
    # 取前段(最重要的爆款心法在前)即可，省 token 又不破品質。可用 LLM_PB_CHARS 調整。
    _pbmax = int(os.environ.get("LLM_PB_CHARS", "3200"))
    playbook = (load_playbook() or "")[:_pbmax]   # 每支腳本即時讀最新競品 playbook(限長)
    training = (load_training() or "")[:1200]      # 每週進修洞察(限長)
    avoid_block = "\n".join(f"  · {t}" for t in (avoid or [])[:30]) if avoid else "  （無）"
    hook_rules = HOOK_RULES if kind == "short" else LONG_RULES
    # 實測 EP 系列(爆款招牌)：短片且題目屬實測/實驗類 → 追加續集鐵律(前1.5秒錨數字+cliffhanger+留言題+念出HUD數字)
    _epkw = ("EP", "實測", "實驗")
    is_ep = (kind == "short" and not topic_override and topic
             and str(topic.get("category", "")) not in ("AI省錢", "AI工具比較", "AI公司揭密")  # 這幾類 franchise 標題常含「實測」,不進 EP 實測系列(會誤編 EP 號)
             and (
        any(k in str(topic.get("category", "")) for k in ("實測", "實驗"))
        or any(k in str(topic.get("title", "")) for k in _epkw)))
    if is_ep:
        hook_rules = hook_rules + EP_RULES
        # EP franchise 引擎：讀 ep_data 補上集前情 + 遞增 EP 號，塞進本支製作指派（讓 call_claude 知道上集講什麼）
        try:
            import ep_engine
            _epst = ep_engine.load_state()
            _next_ep = int(_epst.get("current_ep", 0) or 0) + 1
            assign += ep_engine.next_episode_context(_epst)
            assign += f"\n【本支為 EP{_next_ep}｜標題務必含「EP{_next_ep}」字樣與時間或金錢錨】"
        except Exception:  # noqa: BLE001
            pass
    # 《拆穿》招牌 franchise：題目屬競品拆解/打假神話類 → 追加《拆穿》格式（點名神話+誠實反差鉤+真回測三刀+避雷結論）
    _dbkw = ("拆穿", "神話", "揭穿", "打假", "揭露真相")
    is_debunk = (topic is not None and (
        any(k in str(topic.get("category", "")) for k in ("拆穿", "打假"))
        or any(k in str(topic.get("title", "")) for k in _dbkw)))
    if is_debunk:
        hook_rules = hook_rules + DEBUNK_RULES
    # 指標/策略教學 EP（TradingView 全攻略課程）→ 追加教學格式（教學+回測驗證+陷阱）；與《拆穿》不重疊
    is_curriculum = (topic is not None and not is_debunk and
                     any(k in str(topic.get("category", "")) for k in ("指標教學", "策略回測")))
    if is_curriculum:
        hook_rules = hook_rules + CURRICULUM_RULES
    # 台股招牌格式：題目屬台股/大盤/ETF/個股類 → 追加台股爆款格式（可與《拆穿》疊加，不互斥）
    _twkw = ("台股", "大盤", "ETF", "個股", "當沖", "存股", "0050", "00878", "00929", "006208", "加權", "除權息", "籌碼")
    is_tw_stock = (topic is not None and (
        any(k in str(topic.get("category", "")) for k in _twkw)
        or any(k in str(topic.get("title", "")) for k in _twkw)))
    if is_tw_stock:
        hook_rules = hook_rules + TW_STOCK_RULES
        # 真數據引擎：讀 STUDIO/tw_stock_facts.json，挑與題材相關的真回測數字注入寫稿 prompt。
        # 檔不存在/讀不到/無關聯數字 → 靜默跳過，台股題照樣用 TW_STOCK_RULES 產（標示意數字），不崩。
        try:
            _facts = _load_tw_facts()
            _tw_inject = _tw_facts_context(_facts, topic)
            if _tw_inject:
                assign += _tw_inject
        except Exception:  # noqa: BLE001
            pass
    # 「聰明用 AI」franchise（第二變現支柱）：追加誠實比較寫稿格式（禁快去買、揭露 ban 風險）
    is_ai_savings = _is_ai_savings_topic(topic)
    if is_ai_savings:
        hook_rules = hook_rules + AI_SAVINGS_RULES
    # A1 旗艦:AI公司揭密 franchise → 疊揭密格式 + 注入本系統真實數字(獨家護城河、反造神、真憑實據)
    is_flagship = bool(topic) and str(topic.get("category", "")) in FLAGSHIP_CATS
    if is_flagship:
        hook_rules = hook_rules + AI_COMPANY_RULES
        assign += _system_facts()
    # D2 格式 All-in:FORMAT_FOCUS=1 時,短片(非旗艦/非時事)強制走最強格式模板
    if os.environ.get("FORMAT_FOCUS") == "1" and kind == "short" and not is_flagship and not topic_override:
        hook_rules = hook_rules + WINNING_FORMAT
    prompt = f"""你是量化阿森頻道的專業腳本寫手。{GUARD}
{QUANT_STANDARD}
{playbook}{training}
請產生{spec}{assign}{bias}
{TITLE_FORMULA}
【SEO 長尾(能自然融入就融入,別硬塞犧牲鉤子)】標題或說明前段盡量含 1 個觀眾真的會搜的詞,例如:{"、".join(SEO_TERMS[:12])}。
{hook_rules}
【配音友善·務必遵守（影響聽感與留存）】voice_text 要口語、**短句為主（每句約 15-25 字就用句號斷開）**；
少用括號/破折號/冒號/刪節號；數字盡量寫成口語念法（如「百分之八」別寫「8%」、「一萬元」別寫「$10000」、「零點五」別寫「0.5」）；
一句話別塞太多數據（最多一個數字），讓人聽得清、TTS 念得順、斷點自然。
【高點擊標題框架，擇一套用且自然】：⓪小白避雷型（新增選項，適合就用）：「新手別碰X，我回測幫你試過了」「我回測『丟10萬給X』，結果…」「X 是不是坑/詐騙？我用回測拆給你看」「新手把錢丟給機器人會不會被割？」——恐懼+我先幫你試（是回測、不假稱真錢）。①精確數字＋懸念②「如何…」具體承諾（含時間/數字）③「你一直做錯」揭錯④「真相揭露」⑤反直覺結論。能放具體數字就放、越精確越好；標題要有好奇缺口但不誇大、不保證收益。★長尾可搜尋（繞過低權重的搜尋流量入口）：盡量用觀眾真的會搜的關鍵字並放在標題開頭（如「派網網格 怎麼設」「Pionex vs 幣安」「定投買在高點會虧嗎」）——長片尤其要走這種可搜尋寫法；理財誇大詞（躺賺／穩賺／一天賺X）一律不用，會被限流。
請避免重複以下已有題目（換切角可以，換字重說同主題不行）：
{avoid_block}
⚠️【語言鐵律】全程一律「繁體中文（台灣用字）」，**嚴禁任何簡體字**（例：要寫「網格、帳戶、獲利、為什麼、機器」，不可寫「网格、账户、获利、为什么、机器」）。標題、旁白、說明、小標全部繁體。
只輸出 JSON（不要任何其他文字、不要 markdown 圍欄），格式：
{{"title":"有點擊慾的標題","voice_text":"完整旁白逐字稿(口語、適合中文TTS)","segments":[{{"heading":"段落小標","broll":["english keyword","english keyword"]}}],"description":"YouTube 說明欄：前 3 行＝①核心可搜尋關鍵字短語②一句鉤子摘要③價值承諾(看完能拿走什麼)；接 1-2 句補充、自然含關鍵字與同義詞(別硬塞)；**再加一行變現漏斗 CTA：『📩 私訊 Telegram @CarsonQuant_message_bot 打「回測」，免費領新手回測避雷檢核表』**(Telegram bot 會自動把檢核表送到觀眾手上+養名單再自然導向 Pionex；比「留言領」更能真的交付資源、也把觀眾沉澱成可觸及的名單)；結尾含風險聲明『投資有風險，不構成投資建議』","hashtags":["#Shorts","#量化交易","#..."]}}
hashtags 規則：給 4-6 個「精準且利基相關」的標籤(第一個必為 #Shorts)，不要硬塞 20 個——精準勝過熱門，乾淨又利於演算法分類。"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    txt = llm.complete(prompt, 3500, json_mode=True)  # 強制合格 JSON
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("LLM 回應非 JSON")
    result = _to_traditional(json.loads(m.group(0)))  # 安全網：簡轉繁(台灣用字),防 DeepSeek 偶爾出簡體
    result["_is_ep"] = bool(is_ep)  # 供 make_one 判斷是否為 EP 正片 → 產出成功後遞增 EP 引擎
    # 「聰明用 AI」franchise：把誠實比較表+聯盟連結+揭露語確定性附加到描述本體(保證揭露不被 LLM 吞)。
    # 只在 is_ai_savings 片生效；非 franchise 片 result["description"] 完全不含 premlogin。
    if is_ai_savings:
        _blk = _ai_savings_desc_block()
        if _blk:
            result["description"] = (result.get("description", "") or "").rstrip() + "\n" + _blk
    # A2 SEO:把標題/角度命中的高意圖搜尋詞併進 tags(去重,助搜尋分類;上限由 assemble_metadata 守 500 字元)
    _seo = _seo_hit((result.get("title", "") or "") + (topic.get("angle", "") if topic else ""))
    if _seo:
        _tags = result.get("hashtags") or []
        _have = {str(x).lstrip("#") for x in _tags}
        for k in _seo:
            if k not in _have:
                _tags.append(k)
        result["hashtags"] = _tags
    return result


def _to_traditional(d):
    """把產出的所有中文欄位轉成繁體中文(台灣用字)。OpenCC 有裝就用 s2twp；沒裝就原樣回。
    為什麼：DeepSeek 等中文模型偶爾滑成簡體，繁中頻道不能出簡體(觀感差+像對岸AI量產)。"""
    try:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
    except Exception:
        return d  # 沒裝 opencc 就靠 prompt 約束(已加語言鐵律)

    def conv(x):
        if isinstance(x, str):
            return cc.convert(x)
        if isinstance(x, list):
            return [conv(i) for i in x]
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        return x
    return conv(d)


def _has_llm_key():
    """只要任一 LLM 供應商金鑰存在就能產片(走 llm.py 路由),不再死綁 Anthropic。"""
    return any(os.environ.get(k, "").strip() for k in
               ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"))


def build_md(d):
    title = d["title"]
    voice = d.get("voice_text", "")
    lines = [f"# 🎬 {title}", "", "> 頻道：量化阿森｜Carson Quant｜自動產製", "", "---", "",
             "## ⚡ HOOK（0-5 秒）", "", f"**旁白：** {voice[:55]}", "",
             "**建議畫面：** stock market chart、trading screen", "", "## 📦 主體", ""]
    segs = d.get("segments") or [{"heading": "重點", "broll": ["finance", "chart"]}]
    for i, seg in enumerate(segs, 1):
        kws = "、".join(seg.get("broll") or ["finance", "data"])
        lines += [f"### 段落 {i}：{seg.get('heading', '重點')}", "",
                  f"**旁白：** {seg.get('heading', '')}", "",
                  f"**建議畫面 / B-roll：** {kws}", ""]
    lines += ["## 🏁 結尾（OUTRO）", "", "**旁白：** 追蹤量化阿森，我們下支見。", "", "---", "",
              "## 📝 YouTube 影片描述", "",
              d.get("description", "量化交易教學與觀念分享。投資有風險，不構成投資建議。"), "",
              f"**Hashtags：** {' '.join(d.get('hashtags') or ['#量化交易', '#自動交易'])}", ""]
    return "\n".join(lines)


def _design():
    try:
        return json.loads((ROOT / "STUDIO" / "design_system.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tts_engine():
    return (_design().get("tts_engine") or "edge").lower()


def _run_tts(slug):
    """配音：依 design_system 選引擎；MiniMax(付費自然音)失敗自動退回免費 edge，不中斷生產。"""
    vp = f"output/{slug}.voice.txt"
    mp3 = OUT / f"{slug}.mp3"
    if _tts_engine() == "kokoro":
        # Kokoro 用獨立 venv(_ttsenv)。跨平台尋 python：Windows Scripts\python.exe / *nix bin/python，
        # 找不到就退回主 PY；整段 try 包起來，任何失敗都不中斷生產、往下走 edge。
        try:
            _kw = ROOT / "_ttsenv" / "Scripts" / "python.exe"
            _kn = ROOT / "_ttsenv" / "bin" / "python"
            kpy = _kw if _kw.exists() else (_kn if _kn.exists() else PY)
            subprocess.run([str(kpy), "scripts/tts_kokoro.py", vp], cwd=str(ROOT))
        except Exception as _e:  # noqa: BLE001
            log_ops("配音", f"⚠️ Kokoro 呼叫失敗({_e})，退回 edge：{slug}")
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        log_ops("配音", f"⚠️ Kokoro 配音失敗，退回 edge：{slug}")
    if _tts_engine() == "minimax":
        subprocess.run([str(PY), "scripts/tts_minimax.py", vp], cwd=str(ROOT))
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        log_ops("配音", f"⚠️ MiniMax 配音失敗，退回 edge：{slug}")
    _ds = _design()  # Edge 聲音/語速吃 design_system(換聲音只改設定檔)
    subprocess.run([str(PY), "scripts/tts_edge.py", vp,
                    "--voice", _ds.get("edge_voice", "zh-TW-YunJheNeural"),
                    "--rate", _ds.get("edge_rate", "+12%")], cwd=str(ROOT))


def _run_render(args, env, timeout=720):
    """跑 make_video，逾時就連同子程序(ffmpeg)整組殺掉 —— 防殭屍 ffmpeg 卡死整批製作。"""
    kw = {"cwd": str(ROOT), "env": env}
    if os.name == "posix":
        kw["start_new_session"] = True  # 自成 process group，逾時可整組 kill
    p = subprocess.Popen([str(PY)] + args, **kw)
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        log_ops("補產·渲染", f"⚠️ 渲染逾時 {timeout}s 強制中止：{args[2] if len(args) > 2 else ''}")
        print(f"[TIMEOUT] 渲染逾時，強制中止 {timeout}s", file=sys.stderr)
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)  # 連 ffmpeg 子程序一起殺
            else:
                p.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass


def _norm_title_dup(t):
    import re as _r
    return _r.sub(r"[0-9\uff10-\uff19%/\u3001\uff0c\u3002\uff01\uff1f!?\u2026\s\-_]+", "", t or "")


# ── 贏家公式評分卡(2026-07·用 198 支有數據片回歸出的標題必備元素,把散在 HOOK_RULES 的原則升級成可打分)──
# A 具體數字(必) B 損失框架(虧光/剩多少,實證優於「賺多少」) C 對比/懸念(vs/差多少/你猜) D 生活比喻(加分) E 禁用骨架(一票否決)
_TF_A = re.compile(r"[0-9０-９%]|[十百千萬億兆]")
_TF_B = re.compile(r"虧光|剩多少|賠|爆|清醒|嚇醒|虧|歸零|套牢|血本|慘|畢業|少賺")
_TF_C = re.compile(r"vs|VS|對比|差多少|差在哪|你猜|還是|多久|幾倍|哪個|真能|其實|竟")
_TF_D = re.compile(r"賓士|手搖|便當|一頓|一杯|一台|一輛|一年|一個月薪")

TITLE_FORMULA = (
    "【贏家標題公式(實證·務必命中)】① 必含具體數字/金額/百分比(十萬、87%、10年);"
    "② 用『損失框架』(虧光/剩多少/賠/清醒)勝過『賺多少』——實證高完播都走這味;"
    "③ 加『對比或懸念』(vs、差多少、差在哪、你猜、幾倍);④ 能綁生活比喻更好(一台賓士、一杯手搖);"
    "⑤ 嚴禁玩爛的洗版套語(『XX億爆倉…網格為什麼還活著』『勝率9X卻虧光…破產機率公式一秒戳破』)。"
)

# A2 SEO 搜尋霸權:高意圖台股/量化搜尋詞;標題自然含≥1 個(放前段)吃長尾搜尋流量(長期複利、不靠爆推)。
SEO_TERMS = [
    "0050定投", "0056", "00878", "00929", "006208", "定期定額", "除權息", "填息", "存股",
    "網格機器人", "派網網格", "回測", "台股ETF", "大盤", "當沖", "停損停利", "夏普比率",
    "比特幣定投", "定投回測", "ETF怎麼選", "台積電",
]


def _seo_hit(text: str):
    """回傳標題/角度命中的 SEO 詞(供 tags 併入與選題加權)。"""
    t = text or ""
    return [k for k in SEO_TERMS if k in t]


WINNING_FORMAT = """
【★格式 All-in(FORMAT_FOCUS·30天只磨這個最強格式,務必嚴格照走)】
這是本頻道數據回歸出的最強爆發格式(實證:十萬vs三千676v、複利虧光476v/68%、丟十萬30天454v/68%):
- 骨架:①開頭丟兩個具體金額/數字做對比(如「一次丟十萬 vs 每月三千」「套在1000元 vs 停損」)
  ②中段用損失框架講後果(剩多少/虧光/差多少/少賺幾成),不是講賺多少
  ③答案(那個嚇人的數字)壓到最後一句才揭曉,逼看到底
- 台股或回測題材優先;30-45秒;voice 150-200字;segments 給 2 段;每3-4秒一個衝擊點
- 標題必含具體數字+對比詞(vs/差多少)+懸念,絕不用洗版套語
"""


def title_formula_score(title: str) -> int:
    """贏家公式打分(供重生門檻+每週贏家分析用)。滿分 110;禁用骨架 -100 一票否決。"""
    t = title or ""
    s = 0
    if _TF_A.search(t):
        s += 40
    if _TF_B.search(t):
        s += 30
    if _TF_C.search(t):
        s += 30
    if _TF_D.search(t):
        s += 10
    if sc.is_banned_skeleton(t):
        s -= 100
    return s


def _title_weak(title: str) -> bool:
    """標題是否不達贏家公式門檻(觸發重生):命中禁用骨架、或缺具體數字、或(損失框架與對比懸念都缺)。"""
    t = title or ""
    if sc.is_banned_skeleton(t):
        return True
    has_a = bool(_TF_A.search(t))
    # 損失框架(B)/對比懸念(C)/生活比喻(D)任一即算有強鉤——避免誤殺「每月多存…多一臺賓士」這種獲利+生活比喻的真贏家
    has_bcd = bool(_TF_B.search(t) or _TF_C.search(t) or _TF_D.search(t))
    return (not has_a) or (not has_bcd)


def _too_similar(title, existing, thr=0.82):
    """標題與既有任一過於近似(去數字/標點後相似度>=thr)＝重複，硬擋。"""
    from difflib import SequenceMatcher
    nt = _norm_title_dup(title)
    if not nt:
        return False
    for e in existing:
        if SequenceMatcher(None, nt, _norm_title_dup(e)).ratio() >= thr:
            return True
    return False


def _has_second_person(text):
    """開頭是否直接對觀眾說話(你/妳)——痛點第二人稱把觀眾拉進故事(你的/你是不是/你以為/你猜/你有沒有 都含「你」)。"""
    t = text or ""
    return ("\u4f60" in t) or ("\u59b3" in t)  # 你 / 妳


def _weak_hook(voice_text):
    """第一句(前1秒)弱鉤子判定(保守·沿用重生上限≤2)：
    ·原規則：第一句既無數字、又無衝突詞＝弱。
    ·新增痛點第二人稱：開頭一兩句完全沒對觀眾說話(你/妳)時，若又沒有衝突詞撐場＝弱。
      刻意保守——只要有衝突詞(卻/居然/差/剩/爆…)就算沒第二人稱也放行，避免誤殺
      『同一個策略…夏普值差一倍』這類無「你」但很強的金句鉤。純加法：原本擋下的絕不會因此變放行。"""
    import re as _r
    body = (voice_text or "").replace("\n", " ")
    head = body.split("\u3002")[0]  # 第一句：管數字/衝突(前1秒最強那句)
    head2 = "\u3002".join(body.split("\u3002")[:2])  # 前一兩句：管第二人稱
    if not head:
        return True
    has_num = bool(_r.search(r"[0-9\uff10-\uff19]|[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u842c\u5169\u534a\u500d\u6210]", head))
    conflict = ["\u537b","\u9084","\u7adf","\u5c45\u7136","\u5dee","\u8667","\u5269","\u7206","\u7834","\u6c92\u60f3\u5230",
                "\u5176\u5be6","\u771f\u76f8","\u70ba\u4ec0\u9ebc","\u932f","\u9676\u6c70","\u8b8a\u6210","\u96e3\u9053"]
    has_conf = any(w in head for w in conflict)
    has_you = _has_second_person(head2)
    # 保守：有衝突詞就不算弱；沒衝突詞時，數字與第二人稱缺一即弱
    # (等於在原「無數字」外，多擋「有數字但整段都不對觀眾說話」的乾巴巴陳述)
    return (not has_conf) and ((not has_num) or (not has_you))


def _impact_density(voice_text, max_sec_per_beat=7.0):
    """衝擊密度粗估：平均幾秒才一個斷句/衝擊點，太稀疏(>門檻秒)＝拖沓，觸發一次重生。
    以每分鐘約 300 字(每秒約 5 字)估時長；斷句以句末/逗/頓/分號計。門檻放寬(7秒)只擋明顯拖沓，別誤殺正常片。"""
    import re as _r
    t = (voice_text or "").strip()
    n_chars = len(_r.findall(r"[\u4e00-\u9fff]", t))  # 純中文字數估時長，排除標點空白
    if n_chars < 40:
        return False  # 太短的片不估密度，避免誤殺
    est_sec = n_chars / 5.0  # 每秒約 5 字
    beats = len(_r.findall(r"[\u3002\uff01\uff1f\uff0c\u3001\uff1b!?,;]", t))  # 句末+逗+頓+分號都算一個節拍
    beats = max(beats, 1)
    return (est_sec / beats) > max_sec_per_beat


def _bump_ep(d, slug):
    """EP 正片產出成功 → 遞增 EP 引擎狀態（集數+1、記錄本集、EP>=10 收官升季）。純本地檔，失敗不影響出片。"""
    try:
        import ep_engine
        st = ep_engine.load_state()
        metrics = {"slug": slug, "title": d.get("title", "")}
        new_st = ep_engine.bump_episode(st, metrics, persist=True)
        log_ops("EP引擎", f"EP 遞增 → S{new_st.get('season')} EP{new_st.get('current_ep')} 已記錄：{slug[:28]}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] EP bump 略過：{str(exc)[:80]}", file=sys.stderr)


# LLM 偶發疊字守門(實測 574 支中 5 支出「演演算法」;非 code bug、是模型 stutter,但會被 TTS 念出來)。
# 只列「絕不可能是正確疊字」的術語→修回,不碰「剛剛/常常」等正確疊字,零誤傷。
_ARTIFACT_FIXES = {
    "演演算法": "演算法", "機機器人": "機器人", "網網格": "網格", "回回測": "回測",
    "複複利": "複利", "停停損": "停損", "定定投": "定投", "槓槓桿": "槓桿", "手手續費": "手續費",
}


def _fix_artifacts(text):
    if not isinstance(text, str):
        return text
    for a, b in _ARTIFACT_FIXES.items():
        if a in text:
            text = text.replace(a, b)
    return text


# 訂閱鉤硬性保底:0.29% 轉換是頻道最大瓶頸,訂閱鉤是軟規則(LLM 遵從度約半)。
# LLM 有自然寫訂閱鉤就用它(不動);漏掉才在結尾補一句(依 title 輪替避免全一樣),保證每片 100% 有。
_SUB_HOOK_POOL = [
    "想看我下支回測拆什麼神話？先追蹤，不然演算法不會再推你。",
    "這種『幫你先踩坑』的回測我會一直做，追蹤一下、別錯過下一支。",
    "喜歡就先追蹤，下支我拆更狠的，別讓演算法把你刷走。",
    "覺得有用就追蹤我，下一支一樣用回測幫你試給你看。",
]
_SUB_CUES = ("訂閱", "追蹤", "追更", "別錯過", "鈴鐺", "按個訂", "關注")


def _ensure_sub_hook(text, key):
    """LLM 漏訂閱鉤時結尾補一句(有寫就不動);key 用來輪替措辭。"""
    if not isinstance(text, str) or not text.strip():
        return text
    if any(c in text for c in _SUB_CUES):
        return text  # LLM 已寫訂閱鉤,尊重原文不重複
    import hashlib
    i = int(hashlib.md5((key or "x").encode("utf-8")).hexdigest(), 16) % len(_SUB_HOOK_POOL)
    return text.rstrip() + " " + _SUB_HOOK_POOL[i]


def make_one(kind, no_render=False, topic_override=None):
    _ex = existing_titles()
    d = call_claude(kind, _ex, topic_override)
    # 硬防近似重複：標題與既有太像就重生(時事 topic_override 不擋)；連續 3 次都重複則跳過
    if not topic_override:
        _tries = 0
        # 近似重複 或 標題不達贏家公式(缺數字/損失框架與對比懸念皆缺/命中禁用骨架)→重生(共用上限 3)
        while (_too_similar(d.get("title", ""), _ex) or _title_weak(d.get("title", ""))) and _tries < 3:
            _tries += 1
            d = call_claude(kind, _ex, topic_override)
        if _too_similar(d.get("title", ""), _ex):
            log_ops("補產部門", f"\u26a0\ufe0f 近似重複連3次,跳過:{d.get('title','')[:28]}")
            return None
        if _title_weak(d.get("title", "")):
            log_ops("補產部門", f"標題重生3次仍弱(放行最後版·分{title_formula_score(d.get('title',''))}):{d.get('title','')[:26]}")
    prefix = "S" if kind == "short" else "L"
    # 硬擋弱鉤子+衝擊密度(只對 Shorts；時事 topic_override 不擋)：
    #   ①弱鉤子=前1秒沒數字/衝突、或開頭整段不對觀眾說話(痛點第二人稱)
    #   ②衝擊密度=平均 >7 秒才一個斷句(明顯拖沓)
    #   兩者共用同一重生上限(≤2)，用完就放行最後一版，絕不無限重生卡死產線。
    if kind == "short" and not topic_override:
        _hk = 0
        while (_weak_hook(d.get("voice_text", "")) or _impact_density(d.get("voice_text", ""))) and _hk < 2:
            _hk += 1
            d = call_claude(kind, _ex, topic_override)
    # 疊字守門:修 LLM 偶發 stutter(voice_text/title/description/段落小標),一次覆蓋 voice.txt 與 md
    for _k in ("voice_text", "title", "description"):
        if _k in d:
            d[_k] = _fix_artifacts(d[_k])
    for _seg in d.get("segments", []) or []:
        if isinstance(_seg, dict) and "heading" in _seg:
            _seg["heading"] = _fix_artifacts(_seg["heading"])
    # 訂閱鉤硬性保底:LLM 漏掉就結尾補一句(直攻 0.29% 轉換瓶頸;有寫就不動)
    d["voice_text"] = _ensure_sub_hook(d.get("voice_text", ""), d.get("title", ""))
    slug = slugify(d["title"], prefix)
    if (OUT / f"{slug}.voice.txt").exists() or (OUT / f"{slug}.mp4").exists():
        slug = f"{slug}{int(time.time()) % 10000}"
    (OUT / f"{slug}.voice.txt").write_text(d["voice_text"], encoding="utf-8")
    (OUT / f"{slug}.md").write_text(build_md(d), encoding="utf-8")

    _run_tts(slug)

    # 雲端模式：只產腳本＋配音，渲染交給 PC 端 render_watcher（混合架構）。
    if no_render:
        mp3_ok = (OUT / f"{slug}.mp3").exists()
        log_ops("補產·雲端", f"{'已備妥待渲染' if mp3_ok else '配音失敗'}：{slug}")
        print(f"[{'queued' if mp3_ok else 'FAIL'}] {kind} {slug}（待 PC 渲染）")
        if mp3_ok and d.get("_is_ep"):
            _bump_ep(d, slug)  # EP 正片(非預告)產出成功 → 遞增 EP 引擎
        return slug if mp3_ok else None

    env = os.environ.copy()
    if kind == "short":
        # Shorts 保留 PEXELS → render_ffmpeg 走混合(數據段圖表卡 + 情境段 b-roll 動態影片)
        _run_render(["scripts/make_video.py", "--slug", slug, "--width", "1080", "--height", "1920", "--fps", "15"], env, timeout=1200)
    else:
        _run_render(["scripts/make_video.py", "--slug", slug], env, timeout=2400)  # 長片渲染久，給 40 分鐘
    ok = (OUT / f"{slug}.mp4").exists() and (OUT / f"{slug}.mp4").stat().st_size > 100 * 1024
    if ok:  # 產製即審核：壞片/違規早發現
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{'；'.join(reasons)[:60]}")
            _FATAL = ("片長過短", "無視訊軌", "無音軌", "檔案過小")
            if any(any(tag in r for tag in _FATAL) for r in reasons):
                # 結構性壞片（0s/無影音軌）：清除佔位檔案，讓 queue_size 正確，觸發重試
                for ext in (".mp4", ".mp3", ".voice.txt"):
                    try:
                        (OUT / f"{slug}{ext}").unlink(missing_ok=True)
                    except Exception:
                        pass
                log_ops("補產·品管", f"結構性壞片已清除：{slug}")
                ok = False
            elif "缺風險聲明" in " ".join(reasons):
                # 唯一缺失：在 md 末尾補聲明即可，不需退件
                try:
                    md_path = OUT / f"{slug}.md"
                    md_text = md_path.read_text(encoding="utf-8")
                    if "風險" not in md_text and "不構成投資建議" not in md_text:
                        md_path.write_text(md_text.rstrip() + "\n\n投資有風險，不構成投資建議。", encoding="utf-8")
                    passed, reasons = audit_video.audit(slug)
                    if not passed:
                        log_ops("補產·合規", f"自動補風險聲明後仍未過：{slug}")
                except Exception:
                    pass
    if ok and d.get("_is_ep"):
        _bump_ep(d, slug)  # EP 正片(非預告)產出成功 → 遞增 EP 引擎
    print(f"[{'ok' if ok else 'FAIL'}] {kind} {slug}")
    return slug if ok else None


def _publish_now(slug: str):
    """消息面即時發布（過審才發）。重用 daily_publish 的上傳/ledger，繞過每日排程。"""
    try:
        import daily_publish as dp
    except Exception as exc:  # noqa: BLE001
        log_ops("時事發布", f"⚠️ 無法載入發布模組：{str(exc)[:60]}")
        return
    try:
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("時事發布", f"審核未過未發：{slug}｜{'；'.join(reasons)[:50]}")
            print(f"[時事發布] 審核未過，未發布：{slug}")
            return
        priv = "public"  # 時事要即時公開；若老闆設了全域隱私則遵循
        try:
            bp = ROOT / "STUDIO" / "boss_directives.json"
            if bp.exists():
                v = json.loads(bp.read_text(encoding="utf-8")).get("privacy")
                if v in ("public", "unlisted", "private"):
                    priv = v
        except Exception:
            pass
        yt = dp.get_service()
        vid = dp.upload_one(yt, slug, priv)
        led = dp.load_ledger(); led[slug] = vid; dp.save_ledger(led)
        log_ops("時事發布", f"時事片即時發布 https://youtu.be/{vid}")
        print(f"[時事發布] 已即時發布：https://youtu.be/{vid}")
    except Exception as exc:  # noqa: BLE001
        log_ops("時事發布", f"⚠️ 即時發布失敗：{str(exc)[:70]}")
        print(f"[時事發布] 失敗：{exc}", file=sys.stderr)


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載入,直跑沒有→LLM 找不到 key)。setdefault 不覆蓋 cron 環境。"""
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--format-focus", action="store_true",
                    help="D2:短片強制走最強格式模板(金額對比+損失框架),30天衝流量用")
    ap.add_argument("--flagship", action="store_true",
                    help="旗艦:--topic 搭此旗標→走 AI公司揭密揭密格式+注入本系統真實數字")
    ap.add_argument("--shorts", type=int, default=4)
    ap.add_argument("--long", type=int, default=1)
    ap.add_argument("--target", type=int, default=15)
    ap.add_argument("--no-render", action="store_true",
                    help="雲端模式：只產腳本+配音，渲染交給 PC 端 render_watcher")
    ap.add_argument("--topic", default=None, help="指定題目（金融時事優先製作，繞過排程/題庫，立刻產 1 支）")
    ap.add_argument("--angle", default=None, help="切入點（搭配 --topic）")
    ap.add_argument("--publish", action="store_true", help="產完立刻發布（時事片用：消息面要即時上架，不等排程）")
    ap.add_argument("--manual", action="store_true", help="手動補產：照 --shorts/--long 數量，不被人事部員額覆蓋")
    args = ap.parse_args()
    if getattr(args, "format_focus", False):
        os.environ["FORMAT_FOCUS"] = "1"  # D2:本批短片走最強格式模板

    # 🔥 金融時事優先：給了 --topic 就立刻產 1 支相關 Short，不管排程/片庫上限。
    if args.topic:
        if not API_KEY:
            print("[FATAL] 找不到 ANTHROPIC_API_KEY 環境變數。", file=sys.stderr)
            return 2
        slug_made = None
        _tov = {"title": args.topic, "angle": args.angle or ""}
        if getattr(args, "flagship", False):
            _tov["category"] = "AI公司揭密"  # 觸發 is_flagship→AI_COMPANY_RULES+_system_facts 真數據注入
        for t in range(2):
            try:
                slug_made = make_one("short", no_render=args.no_render, topic_override=_tov)
                if slug_made:
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"[err 時事第{t+1}次] {exc}", file=sys.stderr)
        log_ops("時事製作", f"{'已產出時事片' if slug_made else '⚠️ 時事片失敗'}：{args.topic[:40]}")
        print(f"[{'ok' if slug_made else 'FAIL'}] 金融時事 Short：{args.topic[:40]}")
        # 消息面要即時：產完立刻發布（仍過審核閘門；只在有真的渲染出檔時）
        if slug_made and args.publish and not args.no_render:
            _publish_now(slug_made)
        return 0 if slug_made else 3

    # 員額即產能：人事部在 headcount.json 設的 ②Shorts／①影片 員額 = 每日產出量（加員額＝加產能）。
    # --manual（特助手動補產 N 支）時跳過員額覆蓋，照指定數量產。
    hc_path = ROOT / "STUDIO" / "headcount.json"
    if hc_path.exists() and not args.manual:
        try:
            hc = json.loads(hc_path.read_text(encoding="utf-8"))
            if isinstance(hc.get("②"), int):
                args.shorts = max(0, hc["②"])
            if isinstance(hc.get("①"), int):
                args.long = max(0, hc["①"])
            print(f"[info] 依人事部員額編制 → 今日產出 Shorts {args.shorts} 支、長片 {args.long} 支")
        except Exception:
            pass

    bpath = ROOT / "STUDIO" / "boss_directives.json"
    if bpath.exists():
        try:
            if json.loads(bpath.read_text(encoding="utf-8")).get("paused"):
                print("[info] 老闆已暫停全自動，今日不補產。")
                return 0
        except Exception:
            pass

    if not API_KEY:
        print("[FATAL] 找不到 ANTHROPIC_API_KEY 環境變數。", file=sys.stderr)
        return 2

    q = queue_size()
    print(f"目前片庫：{q} 支 / 目標 {args.target}")
    if q >= args.target:
        print("片庫充足，本次不補產。")
        return 0

    def attempt(kind):
        for t in range(2):  # 自我修復：失敗自動重試一次
            try:
                if make_one(kind, no_render=args.no_render):
                    return True
            except Exception as exc:  # noqa: BLE001
                print(f"[err {kind} 第{t+1}次] {exc}", file=sys.stderr)
        log_ops("補產部門", f"⚠️ {kind} 連續失敗，跳過")
        return False

    log_ops("補產部門", f"開始補產（庫存 {q}/{args.target}）…")
    made = sum(1 for _ in range(args.shorts) if attempt("short"))
    made += sum(1 for _ in range(args.long) if attempt("long"))
    log_ops("補產部門", f"完成 補產{made}支，片庫{queue_size()}支")
    print(f"本次補產 {made} 支，片庫現 {queue_size()} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
