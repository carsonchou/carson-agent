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
         "主題＝量化／自動交易（網格、定投、派網 Pionex、回測、風控）。"
         "★【絕不捏造史實·誠信命脈】個股具體價位/歷史高低點/特定日期漲跌若非確定為真,"
         "一律用『假設你套在高點』『假設從某價位』這種**假設語氣**,絕不把可能錯的具體數字斷言成史實"
         "(例:別說『台積電2023高點1000元』這類可能造假的個股史實——寧可用假設情境或不提具體數字)。")

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
    "・結構節奏：先秀成品（回測曲線／結果畫面）再回頭教；同一組乾淨數字（如本金 1 萬＋某參數）從頭走到尾降認知負擔；零廢話、高資訊密度。\n"
    "・以上競品案例的具體數字/比喻只是示範『這招長怎樣』，套用到本頻道自己的稿子時，數字與比喻都要換成自己的、"
    "別逐字複製別人的例句（尤其別每支都用同一個比喻，見下方『近期已用比喻』清單）。")

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


# ── P3 時事題保底配額(2026-07 破局計畫)──
# 現況雷:_rank 把 hotspot/breakout/intel 時事新聞題一律排在乾淨題之後,143 支 hotspot + 9 支
# breakout 長期被墊底餓死,拿不到演算法對時事的加速。改法:不動 _rank 排序本身(乾淨題仍優先、
# 不誤殺贏家公式產出),而是在每批(main() 用 _set_batch_plan 設定)保留固定名額給時事題
# (~30%、至少 2 支;批次 <2 支不保底),配額只在「庫存確實有時事題」時才生效,沒有就照原排序
# 自然落回乾淨題——只是給時事題保底配額,不是完全翻轉排序。
_NEWS_SRC = ("news", "hotspot", "breakout", "intel")
_BATCH_PLAN = {}   # kind -> {"total": int, "quota": int}；main() 開跑前設定,沒設定=配額0(行為等同修改前)
_BATCH_STATE = {}  # kind -> {"pulled": int, "news_pulled": int}


def _set_batch_plan(kind, total):
    """每批補產開始前呼叫一次,設定這一批(共 total 支 kind)要保底幾支時事題。
    規則:~30%、至少 2 支;批次 total<2 時不保底(避免單支長片被硬塞時事)；quota 不超過 total。"""
    total = max(0, int(total or 0))
    quota = max(2, round(total * 0.3)) if total >= 2 else 0
    quota = min(quota, total)
    _BATCH_PLAN[kind] = {"total": total, "quota": quota}
    _BATCH_STATE[kind] = {"pulled": 0, "news_pulled": 0}


# ── 2026-07 台股比重修正:題材桶保底配額 ──
# 現況雷:即使 topic_bank 產題端已依 studio_common.TOPIC_BUCKET_WEIGHTS 加權出題,若題庫存量
# 本身還沒清乾淨(舊題目台股佔比極低),抽題當下若只靠 _rank() 的候選池內排序,候選池台股本來就
# 稀薄時排序再優先也沒用、批次還是會被非台股題填滿名額。故在抽題這一層再加一道保底配額,跟
# _set_batch_plan(時事題)同一套模式、彼此獨立共存(不互相取代)：main() 開跑前呼叫 _set_bucket_plan
# 設定這批 tw_stock/crypto/ai_tools 各要保底幾支,pull_topic() 每次抽題先看配額還沒吃滿的桶、
# 桶內仍照既有 _rank() 排序取最優;配額吃滿或該桶候選池已空,才落回原本排序自然選。
_BUCKET_PLAN = {}   # kind -> {"tw_stock": int, "crypto": int, "ai_tools": int}
_BUCKET_STATE = {}  # kind -> {"tw_stock": int, "crypto": int, "ai_tools": int}


def _set_bucket_plan(kind, total):
    """依 sc.TOPIC_BUCKET_WEIGHTS 設定這批(kind,共 total 支)台股/加密/AI工具保底配額。
    規則同 topic_bank._bucket_quota(兩處刻意保持一致，一邊改權重、兩邊同步生效):
    total<3 全歸 tw_stock,不硬拆三桶;total>=3 時 crypto/ai_tools 各自至少保底 1 支
    (比重×小基數捨去成 0 會讓這兩桶被結構性歸零，故設下限，除非整批 total<3)，
    其餘名額(含配額外剩下的)全歸 tw_stock(主力)——這是「保底」不是「上限」，tw_stock
    候選不夠配額時,pull_topic 自然會落回其他桶或原排序,不會硬卡住不出片。"""
    total = max(0, int(total or 0))
    if total < 3:
        plan = {"tw_stock": total, "crypto": 0, "ai_tools": 0}
    else:
        remaining = total
        plan = {}
        for b in ("crypto", "ai_tools"):
            w = sc.TOPIC_BUCKET_WEIGHTS.get(b, 0)
            q = max(1, round(total * w))
            q = min(q, remaining - 1)  # 至少留 1 支給 tw_stock
            plan[b] = max(0, q)
            remaining -= plan[b]
        plan["tw_stock"] = max(0, remaining)
    _BUCKET_PLAN[kind] = plan
    _BUCKET_STATE[kind] = {"tw_stock": 0, "crypto": 0, "ai_tools": 0}


def pull_topic(kind):
    """從 STUDIO/topic_bank.json 取一個未用、符合格式的題目並標記為已用；無則回 None。
    讀寫一律走 topic_bank.load_bank/save_bank(原子寫+.bak 救命),避免併發寫互毀把整庫洗掉(2026-07 根因修復)。
    2026-07 P3:若本 kind 這一批(_set_batch_plan 設定)時事配額還沒吃滿、且庫存確實有時事題,
    優先從時事候選(仍照 _rank 排序取最優)挑；配額吃滿或庫存沒時事題,就照原本排序邏輯自然選。"""
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
    # 2026-07 成長衝刺:加密爆倉/網格新聞蹭熱本週已達上限(≤2支,見 studio_common.is_liquidation_hijack)
    # → 直接從候選池濾掉,不讓它有機會被選到(產線層強制擋,不是靠運氣);未達上限則不影響正常排序。
    if _sc.check_topic_frequency("news_liquidation", cap=2):
        cand = [t for t in cand if not _sc.is_liquidation_hijack(
            (t.get("title", "") or "") + (t.get("angle", "") or ""))]
    # 治本:①乾淨題優先於新聞旁路來源題(修「回測/你的」讓幣圈恐慌題誤命中 _NUM_KW 插隊贏過乾淨題的 bug)
    #       ②同組內再靠「數字戳破直覺」會紅題(完播高)優先;工具教學/純新聞題排後、自然餓死
    # 2026-07 成長衝刺(growth_sprint_plan.md B 段):台股/ETF/0050×定投對比×回測打臉直覺＝
    # 全頻道 reach 天花板(450-855v)的已驗證贏家脈絡,獨立設 winner 優先層級,僅次於旗艦題,
    # 優先於一般 SEO/NUM 排序——放大這條產線資源會自然多分配到它。
    _WINNER_KW = ("0050", "0056", "00878", "00929", "006208", "定投", "定期定額", "ETF",
                  "存股", "大盤", "台股", "All in", "all in", "ALL IN", "一次投入", "一次all",
                  "回測打臉", "無腦買", "vs")
    def _rank(t):
        _ta = (t.get("title", "") or "") + (t.get("angle", "") or "")
        src = str(t.get("source", "")).lower()
        flag = 0 if str(t.get("category", "")) in FLAGSHIP_CATS else 1  # 旗艦題最優先自動產(破圈押注·稽核B修:原本被墊底餓死)
        winner = 0 if any(k in _ta for k in _WINNER_KW) else 1  # 贏家脈絡優先(2026-07 成長衝刺放大)
        news_src = 1 if src in ("news", "hotspot", "breakout", "intel") else 0
        depri = 1 if t.get("deprioritized") else 0  # A5:含輸家詞的題被降權排最後
        seo = 0 if _seo_hit(_ta) else 1             # A2:含高意圖搜尋詞的題優先
        num = 0 if any(k in _ta for k in _NUM_KW) else 1
        return (flag, winner, news_src, depri, seo, num)
    cand.sort(key=_rank)
    if not cand:
        return None
    chosen = None
    state = _BATCH_STATE.setdefault(kind, {"pulled": 0, "news_pulled": 0})
    plan = _BATCH_PLAN.get(kind) or {}
    quota = plan.get("quota", 0)
    state["pulled"] += 1
    if quota and state["news_pulled"] < quota:
        news_cand = [t for t in cand if str(t.get("source", "")).lower() in _NEWS_SRC]
        if news_cand:
            chosen = news_cand[0]  # 時事候選內仍照 _rank 排序取最優,不是隨機抓
    # 2026-07 台股比重修正:時事配額沒選中時,再看 bucket 配額——用「平滑加權輪詢(smooth WRR)」
    # 決定這次優先挑哪個桶,而不是每次都固定先查 tw_stock 再查 crypto/ai_tools。
    # 根因(已用小批次實測抓到):固定順序每次都先查 tw_stock,只要 tw_stock 候選池還有貨、
    # 配額還沒滿就一定贏,會導致 tw_stock 把批次前段名額整個吃光,等真正輪到 crypto/ai_tools
    # 檢查時,批次名額可能已經被(時事配額+tw_stock)用完,保底配額變成看得到吃不到。
    # smooth WRR(cw 累加器每輪 +=配額、選中者扣總權重)讓三桶交錯分布在整批次裡，
    # 不會全擠在批次頭尾；已達自己配額(或被時事配額提前吃到超過配額)的桶會被移出 active、
    # 剩餘權重自動只在還沒達標的桶之間比例分配,不會因為前面時事配額picks已提前貢獻某桶
    # 而重複超配。
    # 沿用同一支 _bucket_of 現場分類:題目自己有 bucket 欄位(topic_bank 產題端已寫入)就直接用,
    # 沒有(舊題庫存量、或外部模組 add_topics 尚未跑過新版)才現場呼叫 classify_topic_bucket。
    def _bucket_of(t):
        b = t.get("bucket")
        if b in ("tw_stock", "crypto", "ai_tools", "general"):
            return b
        return _sc.classify_topic_bucket(t.get("title", ""), t.get("angle", ""), t.get("category", ""))
    bstate = _BUCKET_STATE.setdefault(kind, {"taken": {}, "cw": {}})
    bplan = _BUCKET_PLAN.get(kind) or {}
    taken = bstate.setdefault("taken", {})
    cw = bstate.setdefault("cw", {})
    if chosen is None and bplan:
        active = {b: q for b, q in bplan.items() if q > taken.get(b, 0)}
        if active:
            for b in active:
                cw[b] = cw.get(b, 0) + active[b]
            total_active = sum(active.values())
            for b in sorted(active.keys(), key=lambda x: -cw[x]):  # 這輪 WRR 最該輪到的桶優先試
                b_cand = [t for t in cand if _bucket_of(t) == b]
                if b_cand:
                    chosen = b_cand[0]  # cand 已照 _rank 排序,篩選後仍保留桶內最優先的相對順序
                    cw[b] = cw.get(b, 0) - total_active
                    break
    if chosen is None:
        chosen = cand[0]
    if str(chosen.get("source", "")).lower() in _NEWS_SRC:
        state["news_pulled"] += 1
    _chosen_bucket = _bucket_of(chosen)
    if _chosen_bucket in ("tw_stock", "crypto", "ai_tools"):  # 不論走哪個分支選中,都記進 bucket 計數,後續抽題才準
        taken[_chosen_bucket] = taken.get(_chosen_bucket, 0) + 1
    if not chosen.get("bucket"):
        chosen["bucket"] = _chosen_bucket  # 補記錄,讓舊題目一經抽中就補齊 bucket 欄位供日後稽核
    chosen["used"] = True
    try:
        _tb.save_bank(bank)  # 原子寫,不再直接覆蓋
    except Exception:
        pass
    return chosen


# ── P1 鉤子留存:把 retention_insights.json 的完播診斷回灌進 HOOK 生成 prompt(2026-07 破局計畫)──
# 現況雷:diagnose 有查出「7/10 支熱門片開頭 12-20% 流失最兇」,但診斷從沒回灌產線,HOOK_RULES
# 只有靜態規則、吃不到最新一批真實數據。這裡讓每次寫稿都讀最新診斷結論;檔不在/壞掉就優雅跳過
# (不影響產線,HOOK_RULES 的靜態規則仍在)。
RETENTION_FILE = ROOT / "STUDIO" / "retention_insights.json"


def _retention_insight():
    """讀 STUDIO/retention_insights.json 的完播診斷結論,組成一段注入 HOOK 生成 prompt 的文字。
    檔不存在/JSON壞/沒有 verdict → 回空字串,呼叫端直接不注入(優雅跳過,不影響其他片)。"""
    try:
        if not RETENTION_FILE.exists():
            return ""
        d = json.loads(RETENTION_FILE.read_text(encoding="utf-8"))
        verdict = str(d.get("verdict", "")).strip()
        if not verdict:
            return ""
        early = d.get("early_drops")
        analyzed = d.get("analyzed")
        stat = f"(最新一輪 {analyzed} 支熱門片中 {early} 支開頭流失最兇)" if (
            isinstance(early, int) and isinstance(analyzed, int) and analyzed) else ""
        return (f"\n【★真實完播診斷{stat}·retention_insights.json(務必照此修正,別再犯)】{verdict}——"
                "第一句(前3秒)必須是最大數字/反直覺結論本身，不是鋪陳、不是暖場問句、"
                "更不能跟段落1旁白逐字重複；結論先講，背景與鋪陳全部往後放。")
    except Exception:  # noqa: BLE001
        return ""


# ── A1 去同質化:近期已用比喻/CTA 輕量記錄(2026-07 頻道整頓計畫)──
# 現況實證:151 稿裡 15% 用同一個「過度擬合＝背考古題」比喻(用爛22次)、77% 結尾套同一句 CTA——
# 因為 HOOK_RULES/playbook 給的是固定範例，LLM 傾向逐字照抄。修法：不動 studio_common(其他 agent 在改)，
# 直接掃「最近已產出的旁白檔」抽出已用過的比喻/結尾，動態組一段「近期已用、禁止再用」清單注入 prompt；
# 純讀檔、輕量、缺檔優雅跳過，不需要額外維護一份新的持久化狀態檔(已產出的檔案本身就是紀錄)。
_KNOWN_METAPHORS = {
    "背考古題": "過度擬合＝背考古題(已用爛，禁用，換新比喻或直接白話講、不用比喻)",
    "菜市場大媽": "網格＝菜市場大媽(已用多次，盡量換)",
    "雜貨店": "網格＝開雜貨店(已用多次，盡量換)",
    "存錢罐": "定投＝存錢罐(已用多次，盡量換)",
    "手扶梯": "定投＝手扶梯(已用多次，盡量換)",
    "滾雪球": "複利＝滾雪球(已用多次，盡量換)",
    "雲霄飛車": "最大回撤＝雲霄飛車(已用多次，盡量換)",
    "一台賓士": "少賺的錢＝一台賓士(已用爛，3天內連撞5支，禁用，換新比喻或直接講具體金額差距)",
}

# ── A1c 已知濫用比喻「硬擋」(2026-07-13 抓包：軟性 prompt 提示擋不住 LLM 用同義變體復發——
#    「背考古題」被禁後隔天原句復發於另一支：「等於考古題先看過答案再背」，字面不同但核心詞沒變；
#    「一台賓士」3 天內連撞 5 支不同影片)。這層是「已知累犯，永久硬擋」，跟下面 _body_too_similar
#    (近期任何新出現的重複句型，動態、有時間窗)是兩層互補防線。
#    ★核心設計：故意取比原詞更短的「核心關鍵字」(如「考古題」而非「背考古題」、「賓士」而非「一台賓士」)，
#    這樣不管 LLM 怎麼倒裝語序、加什麼修飾詞包裝，只要核心詞還在文字裡就用子字串比對攔下來——
#    不需要真的做語意相似度，比對變體最省成本又最不會漏。要加新的累犯比喻，直接把核心詞加進這個 tuple。
NOTORIOUS_METAPHOR_KEYWORDS = (
    "考古題", "賓士", "菜市場大媽", "雜貨店", "存錢罐", "手扶梯", "滾雪球", "雲霄飛車",
)


def _notorious_metaphor_hit(text: str):
    """硬擋：旁白是否命中『已知濫用比喻』的核心關鍵字——不管怎麼換句話講、語序怎麼變，
    只要核心詞還在文字裡就攔下來(純子字串比對，見上方 NOTORIOUS_METAPHOR_KEYWORDS 說明)。
    命中回傳該關鍵字(供 log 訊息用)，沒命中回 None。"""
    if not text:
        return None
    for kw in NOTORIOUS_METAPHOR_KEYWORDS:
        if kw in text:
            return kw
    return None


def _recent_voice_texts(n=15, pattern="*.voice.txt"):
    """讀最近 n 支已產出旁白的全文(mtime 倒序)；讀不到就整批優雅跳過，不中斷產線。"""
    out = []
    try:
        files = sorted(OUT.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)[:n]
        for f in files:
            try:
                out.append(f.read_text(encoding="utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return out


def _recent_metaphor_block(n=20):
    """近期(最新 n 支，短+長片都算)旁白裡動態抽出的『已用比喻/特色短語』→組一段『禁止再用』提示。
    2026-07-13 深化：改呼叫 _recent_used_phrases(定義於本檔後段)，不再只認 7 個硬編碼關鍵字——
    沒抽到任何東西就回空字串(不誤導、不硬塞)。"""
    hit = _recent_used_phrases(n)
    if not hit:
        return ""
    listed = sorted(hit, key=len, reverse=True)[:20]  # 限量避免撐爆 prompt，長句優先(資訊量較高)
    return ("\n【近期已用比喻/特色短語(A1去同質化，避免同質化，務必換一個新說法，不要再用下列任一個)】\n- "
            + "\n- ".join(listed))


def _recent_endings(n=15, tail_chars=100, pattern="S_*.voice.txt"):
    """近期已產出旁白的結尾片段(給結尾 CTA 相似度比對用)。tail_chars 從 50 放寬到 100(涵蓋完整 CTA)；
    pattern 預設只比 Shorts 自己，長片結構不同、要各自跟長片比時傳 "L_*.voice.txt"(2026-07-13 深化)。"""
    return [t.strip()[-tail_chars:] for t in _recent_voice_texts(n, pattern) if t.strip()]


def _ending_too_similar(text, recent, thr=0.72, tail_chars=100):
    """本支旁白結尾是否與『近期任一支』的結尾高度相似(=同一句 CTA 反覆重複，治 77% 同句問題)。
    tail_chars 從 50 放寬到 100(2026-07-13 深化)：50 字常只涵蓋連看鉤半句，接不到前面的留言鉤／
    訂閱鉤，真正重複的 CTA 反而漏比對；100 字能涵蓋完整的『留言鉤+訂閱鉤(+連看鉤)』三句組合。"""
    if not text:
        return False
    from difflib import SequenceMatcher
    tail = text.strip()[-tail_chars:]
    if not tail:
        return False
    for r in recent or []:
        try:
            if SequenceMatcher(None, tail, r).ratio() >= thr:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


# ── A1d CTA 範例池參數化(2026-07-13 治病灶A根因之一)：spec/HOOK_RULES 原本在 prompt 裡固定寫死
# 同一句「你是哪種?留言告訴我」當範例，LLM 高機率照抄——3天內5支不同影片撞同一句結尾正是這樣來的。
# 改成 ≥10 句可調池，每次呼叫只挑「近 _CTA_POOL_WINDOW 次沒被當過範例」的句子塞進 prompt，
# 範例本身先做到輪替，LLM 就算照抄也不會一直抄同一句。池子與視窗大小都是模組常數，方便之後調整。
CTA_ENDING_POOL = [
    "你的設定是哪種?留言告訴我",
    "想要完整回測數據?留言「數據」我私你",
    "你會怎麼選?留言告訴我你的答案",
    "猜到答案了嗎?留言公布你的猜測",
    "這招你敢用嗎?留言說說你的顧慮",
    "你會停損還是加碼?留言告訴我",
    "換成是你會選哪邊?留言戰一波",
    "你中過這個坑嗎?留言講講你的經驗",
    "這數字有嚇到你嗎?留言說說你的想法",
    "你猜下一步該怎麼做?留言告訴我",
    "換你操作會怎麼做?留言告訴我你的判斷",
    "這結果你猜對了嗎?留言公布你的戰績",
]
_CTA_POOL_WINDOW = 5  # 近 N 次生成不重複拿同一句當範例(可調)
_CTA_POOL_STATE_FILE = ROOT / "STUDIO" / "cta_pool_state.json"


def _cta_pool_sample(k=2):
    """從 CTA_ENDING_POOL(≥10句)挑 k 句當本次生成 prompt 的『範例』(只是示範句型給 LLM 參考，
    不是強制輸出字面值)，優先挑近 _CTA_POOL_WINDOW 次沒被當過範例的句子，避免同一句範例反覆
    出現在 prompt 裡讓 LLM 照抄。狀態存 STUDIO/cta_pool_state.json(只記最近用過的池索引佇列)；
    缺檔/壞檔/寫入失敗都優雅退回單純隨機挑，不影響產線。"""
    import random
    n = len(CTA_ENDING_POOL)
    k = min(k, n)
    try:
        state = sc.load_json_safe(_CTA_POOL_STATE_FILE, default={"recent": []}) or {"recent": []}
        recent_idx = [i for i in state.get("recent", []) if isinstance(i, int) and 0 <= i < n]
    except Exception:  # noqa: BLE001
        recent_idx = []
    recent_set = set(recent_idx[-_CTA_POOL_WINDOW:])
    candidates = [i for i in range(n) if i not in recent_set]
    if len(candidates) < k:  # 池子被近期用滿了(池子太小或視窗太大)→退回全池挑，不卡死
        candidates = list(range(n))
    picked = random.sample(candidates, k)
    try:
        recent_idx = (recent_idx + picked)[-max(_CTA_POOL_WINDOW * k, 20):]
        sc.save_json_atomic(_CTA_POOL_STATE_FILE, {"recent": recent_idx})
    except Exception:  # noqa: BLE001
        pass
    return [CTA_ENDING_POOL[i] for i in picked]


# ── A1b 內文去同質化深化(2026-07-13)：_too_similar 只擋標題、_ending_too_similar 只擋結尾，
# 都漏掉「旁白整篇的比喻/中段句型抄自己」這一層——實測同一批稿標題不同，但中段比喻、句型、
# CTA 結尾幾乎一樣，觀眾看第二支就膩。以下補「比喻/金句」與「中段句型」兩個維度，
# 全部沿用『命中就重生，重生超過上限就放行但記 log 標記』的既有模式，不做無限迴圈。

USED_PHRASES_FILE = ROOT / "STUDIO" / "used_phrases.json"
_METAPHOR_MARKERS = ("就像", "就好像", "好比", "等於是", "宛如", "＝", "彷彿")


def _split_sentences(text):
    """中文斷句：依句末標點(。！？!?)切，去空白/空句。供內文相似度比對共用的輕量工具。"""
    if not text:
        return []
    parts = re.split(r"[。！？!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def _extract_metaphor_sentences(text):
    """從一篇旁白裡挑出『比喻句』(含就像/好比/等於是/＝等標記詞的句子)，長度限制在
    6~40 字之間——太短沒資訊量(可能斷句誤切)、太長多半是整段被切壞，不是乾淨的比喻句。"""
    return [s for s in _split_sentences(text) if any(m in s for m in _METAPHOR_MARKERS) and 6 <= len(s) <= 40]


def _extract_repeated_ngrams(texts, n=4, min_count=3):
    """跨檔統計重複出現的 n 字(預設4字)以上中文片語，回傳『出現在 >= min_count 個不同檔案』的片語
    (跨檔重複＝真正被反覆套用的『特色短語』；單檔內自己重複不算)。輕量字元 n-gram，不做完整斷詞。"""
    from collections import Counter
    file_grams = []
    for t in texts:
        chars_only = re.sub(r"[^一-鿿]", "", t or "")
        file_grams.append({chars_only[i:i + n] for i in range(max(len(chars_only) - n + 1, 0))})
    counter = Counter()
    for grams in file_grams:
        counter.update(grams)
    return [g for g, c in counter.items() if c >= min_count]


def _recent_voice_files(n=20, pattern="*.voice.txt"):
    """讀最近 n 支已產出旁白的 (slug, 全文) 清單(mtime 倒序)；讀不到就整批優雅跳過，不中斷產線。"""
    out = []
    try:
        files = sorted(OUT.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)[:n]
        for f in files:
            try:
                out.append((f.name[: -len(".voice.txt")], f.read_text(encoding="utf-8", errors="replace")))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return out


def _recent_used_phrases(n=20):
    """動態抽取『近期已用比喻/特色短語』——取代原本只認 7 個硬編碼關鍵字(_KNOWN_METAPHORS)的做法。
    三路來源：①_KNOWN_METAPHORS 種子(保留，免舊比喻復辟)②近期旁白裡含比喻標記詞的句子
    ③跨檔重複出現(>=3 個不同檔案)的 4 字以上片語(抓『幾乎每支都出現』的特色短句/句型)。"""
    hit = set(_KNOWN_METAPHORS.values())
    texts = [t for _, t in _recent_voice_files(n, "*.voice.txt")]
    for t in texts:
        hit.update(_extract_metaphor_sentences(t))
    hit.update(_extract_repeated_ngrams(texts, n=4, min_count=3))
    return hit


def _body_too_similar(text, recent_texts, thr=0.85, min_len=10):
    """新旁白『整篇』與近期任一支是否有『局部』高度相似——逐句(chunk)比對，不是整篇平均，
    避免長片字數多，把某一句抄自己的相似度被稀釋掉(治『中段句型抄自己』，長短片都適用)。
    任一句與歷史任一句相似度 >= thr 就判定為重複，回傳 True 觸發重生。"""
    if not text:
        return False
    from difflib import SequenceMatcher
    new_sents = [s for s in _split_sentences(text) if len(s) >= min_len]
    if not new_sents:
        return False
    hist_sents = []
    for r in recent_texts or []:
        hist_sents.extend(s for s in _split_sentences(r) if len(s) >= min_len)
    if not hist_sents:
        return False
    for ns in new_sents:
        for hs in hist_sents:
            # 長度差太懸殊沒必要比(不可能高相似)，省掉多數無效的 SequenceMatcher 呼叫
            if abs(len(ns) - len(hs)) > max(len(ns), len(hs)) * 0.5:
                continue
            try:
                if SequenceMatcher(None, ns, hs).ratio() >= thr:
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _record_used_phrases(d, slug):
    """把本支已產出的比喻句 + CTA 結尾片段記進 STUDIO/used_phrases.json(持久化狀態，供未來稽核/
    人工複查『哪些短語已經用過』)。寫入一律走 studio_common.save_json_atomic(專案統一防併發洗檔的
    原子寫入工具)，不自己 open().write()。純附加、缺檔/壞檔靜默跳過，不影響產線。"""
    try:
        text = d.get("voice_text", "") or ""
        phrases = _extract_metaphor_sentences(text)
        tail = text.strip()[-100:]
        if tail:
            phrases.append(tail)
        if not phrases:
            return
        data = sc.load_json_safe(USED_PHRASES_FILE, default={"entries": []})
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            data = {"entries": []}
        today = time.strftime("%Y-%m-%d")
        for p in phrases:
            data["entries"].append({"phrase": p, "slug": slug, "date": today})
        data["entries"] = data["entries"][-2000:]  # 限量避免無界成長
        sc.save_json_atomic(USED_PHRASES_FILE, data)
    except Exception:  # noqa: BLE001
        pass


def _fabricated_perf_claim(text):
    """A2 誠信硬擋:本片旁白是否含疑似捏造的具體回測績效數字(回測N檔/勝率X%/報酬Y%/夏普轉折/虧損X%…)
    且附近無『示意/假設』等誠實揭露語境。重用 fact_guard.py 已有的規則(同一套判準，不重複維護)。
    只用於『非台股題(無真實 tw_stock_facts 佐證)』的重生判斷；fact_guard 模組載入失敗就靜默放行(不中斷產線)。"""
    try:
        import fact_guard
        return bool(fact_guard.flags_for(text))
    except Exception:  # noqa: BLE001
        return False


def _fabricated_perf_claim_d(d):
    """A2 誠信硬擋(P7 補強):併入標題+描述一起查,不只旁白。捏造績效數字若寫進標題/描述
    (而非旁白逐字稿),舊版只傳 voice_text 完全查不到——同一漏洞已在 fact_guard.py main() 修過,
    這裡是 produce_batch.py 自己的生成期檢查點,獨立補齊。"""
    blob = "\n".join([d.get("title", ""), d.get("description", ""), d.get("voice_text", "")])
    return _fabricated_perf_claim(blob)


HOOK_RULES = """
【受眾方向（2026-07-02 新增·偏好非硬性）】多服務一種人：**想被動賺、但怕被割的投資小白**（這是重點方向之一，不是唯一）。
- **能白話就白話**：術語盡量翻成人話（回測=拿歷史行情跑一遍、夏普=賺得穩不穩、網格=機器人低買高賣），第一次出現的名詞順手一句解釋；不必為了白話犧牲該有的乾貨。
- 有一個很好用的角度＝**「我先幫你試、別自己送死」**：阿森用回測往死裡測機器人與做法（是回測、不是真錢實盤，別假稱丟真錢），恐懼（被割/被套/會不會虧光）→安心（我回測過、這坑先幫你踩）。適合就用，不強迫每支都套。
- 開頭痛點多用小白聽得懂的講法勝過丟參數細節。
【完播率＝唯一KPI·鐵律（直接決定流量，逐條遵守）】
0. ★黃金 30 秒三段式開場骨架（這支片的脊椎，務必照走，蒸餾自 179 萬觀看爆款公式）：
   ①前 3 秒「恐懼/痛點」——丟一個『陌生人也立刻懂』的具體損失或反直覺真相，要帶精確數字。
      ★數字與情境每支都要自己重抽，禁止每支都套同一個數字(如固定用「九成」「87%」)——
      可以是七成三、六成一、三分之二、差2.3倍、少賺58%…從不同數字池、不同單位(百分比／倍數／金額／次數)抽，
      跟近期已產出的任一支都不可重複同一個數字或同一種講法。
   ②中段「希望」——點出有個『可回測驗證』的方法能避開，但先不給全部答案，留好奇缺口。
   ③後段「解法」——這時才給做法；工具(派網/參數/設定)只當『解法的執行步驟』帶出，絕不是開頭主題。
1. 第一句(前1秒)就砸出最驚人的「具體數字＋直覺衝突」，0 開場白、0 自我介紹。
   ★以下只是「句型結構」範例(讓你理解數字+衝突長怎樣)，**數字、動作、情境每支都必須換成不同的一組，
   嚴禁逐字照抄任何一句**——這是造成「151 支換句話說像同一支」的最大元凶，务必避免：
   ·句型A「【設定/動作】連續發生N次，結果只剩/少了多少，你猜多少？」
   ·句型B「同一個策略/參數，切換條件不同，某指標差多少倍/多少%。」
   ·句型C「某比率很高的數字，結果卻還是相反的下場。」
   每支從不同數字池(百分比、倍數、金額、天數/次數)、不同情境自己組一句全新的。
   ★硬性(2026-07 完播診斷回灌·別再犯)：第一句必須是「結論／最大數字」本身，不是暖場鋪陳或背景交代——
   嚴禁用「你知道嗎」「大家好」「今天要來跟大家聊聊」「什麼是○○」這種軟性提問／自我介紹當開場句；
   第一句也不得與後面段落1的旁白逐字重複(段落1可承接同一件事，但要換句、往下推進，不能複製貼上)。
1c. ★硬性(2026-07 成長衝刺實測·完播殺手 vs 贏家的關鍵差距)：**嚴禁把新聞事件原封不動當開場句**——
   殺手實例(完播僅24-39%，開頭 watchRatio 只 1.05 一路衰減)：「BTC暴漲前兆？8億空單即將爆倉！」
   「4.5億空軍一夜歸零！恐慌指數卻躺19？」「空頭爆倉4.58億！網格撐得住嗎？」——這類句子只是把新聞標題
   念一遍、丟給陌生人一個他無法代入的抽象天文數字，沒有「你」、沒有反直覺對比，觀眾看完第一句仍不知道
   這跟自己有什麼關係，秒滑。
   贏家實例(開頭 watchRatio 1.35-1.50，觀眾狂回看)：都是「具體反直覺數字＋跟觀眾切身相關的對比」
   （例：「同樣丟一萬，一次全押跟分12個月，10年後差多少？」），不是轉述外部新聞事件。
   遇到加密爆倉/清算/網格新聞這類時事題材，開場**必須先把新聞事件轉譯成觀眾能代入的反直覺對比或具體後果**
   （例如把「XX億爆倉」轉成「你的網格參數，遇到這種單邊行情會怎樣」的個人化反直覺問句），
   絕不能只是照抄新聞標題的天文數字當第一句；且該支結論要接一個真數字或回測結論收尾，不能只停在恐慌情緒。
1d. ★中段二次鉤(11-20% 處·完播狙擊 2026-07-13 回灌 retention_insights.json)：實測 10/10 支熱門片的
   最大流失點集中在影片 11%-20% 處(不是結尾、不是開頭第一秒)——開頭 3 秒鉤子撐住的人，若緊接著沒有新
   懸念接住，一樣會在這裡滑走。硬性要求：**緊接在開頭痛點句之後(第 2、3 句左右)必須插一句「反轉/加碼
   懸念」承接語**，句型例如「但這還不是最慘的」「真正的坑在後面」「這還沒完，更扯的在後面」「先別急，
   麻煩還在後面」「更可怕的是」——每支自選一句、意思要自己換句、不可逐字照抄，但語意都是『這件事比你
   想的更誇張/後面還有更關鍵的』，讓撐過開頭的觀眾有理由留到中段。
2. 製造「好奇缺口」：開頭丟反直覺結論或數字謎題，**答案留到最後一句才揭曉**，逼觀眾看到底。
2b. ★承諾-兌現鏈：答案不能太早揭曉(完播狙擊 2026-07-13)。開頭拋出的數字懸念，若答案在全片**前 30%**
   就講完＝觀眾提前拿到「拿了就走」的理由，完播會在那裡垮。硬性要求：「答案是／答案就是／答案揭曉／
   結果是／結果就是／真相是」這類明確揭曉句型，**不得出現在全片前 30% 的位置**——先留好奇缺口撐過中段，
   答案留到中後段或最後一句才完整給出，呼應鐵律 2 與 loop 結尾(④)的機制，揭一半留一半。
3. 全程快節奏、每句一個衝擊點、不鋪陳不繞圈；寧可短(二十到三十秒)也不稀釋。
4. 結尾用一句反轉或重磅數字收（不要平淡總結），**接一句『留言鉤』CTA**——留言在 Shorts 演算法權重比訂閱高,別只喊訂閱。
   ★留言鉤句型池(擇一或自創新句，**每支盡量換不同句子、禁止每支都套同一句**，近期已用過的優先避開)：
   「你的設定是哪種?留言告訴我」／「想要完整回測數據?留言『數據』我私你」／
   「你會怎麼選?留言告訴我你的答案」／「猜到答案了嗎?留言公布你的猜測」／
   「這招你敢用嗎?留言說說你的顧慮」／也可以自己想一句更貼合本片主題的問句，只要能引導留言互動就算數。
4b. ★片內訂閱鉤(所有片必留·輕量·接在留言鉤後,不取代留言鉤):留言鉤之後補一句 ≤20 字的追更式訂閱鉤,綁「系列連續性」而非硬喊(角度可以是追更/演算法推播/別錯過下一支等，**每支換不同措辭，不要每支都用同一句**)。訂閱轉換是頻道最大瓶頸(0.29%),但要輕、綁在追更正當性上,別變成討厭的硬喊訂閱。**這是硬性要求:每支結尾『留言鉤+訂閱鉤』兩句都必帶,漏掉訂閱鉤=不合格。**
4c. ★連看鉤(拉 session watchtime·2026演算法核心信號):片尾最後一句用懸念指向同類主題的另一支,把單片觀眾導成連看——依本片實際主題挑一支相關的舊片懸念帶出，別每支都套同一句話術。session 連看時長比單片完播更能沉澱頻道權重。
5. 用具體數字戳破直覺錯誤——但**務必包進「你的__設錯了／你以為X其實Y」的個人具體情境**，不是抽象公式說教(實測:「停損連輸只剩61%,你猜多少」372%重看 vs 抽象「破產機率公式」只10%、看6秒就劃走)。
★陌生人優先（演算法肯不肯推給陌生人的關鍵）：開頭嚴禁丟派網設定／參數細節／小眾術語——沒追蹤過你的人根本不在乎參數，先用『痛點或反直覺結論』把他勾進來，工具一律延後到後段「怎麼做」才出現。
【★完播率實測·爆款 DNA（用你頻道真實 analytics 驗證 2026-06-27，每支至少中兩個開關）】
① 懸念缺口：開頭丟數字謎題／反直覺結論，**答案壓到最後一秒才揭曉**——誘導重看(你最高完播的片都被重看到 200~372%，loop 就是流量)。
② 第二人稱互動：「你的」「你猜」「你以為」「你是不是」把觀眾拉進故事，不是站著講知識。
③ 具體可想像情境：用「一萬元／連輸10次／10年／差3倍」這種有畫面的數字，禁抽象術語與公式名。
④ ★loop 結尾(2026演算法:重看=流量,你最高完播片就是被重看到372%):最後一句呼應/接回開頭第一句,讓結尾自然循環回開頭,觀眾不知不覺重看。句型示範(數字自己換,不可照抄):開頭丟一個數字懸念問句,結尾用「答案揭曉+回去看你猜對沒」呼應同一個懸念。
★ 對仗金句(至少一句·可截圖轉發):全片至少寫一句結構對稱的對仗/排比金句(例「便宜囤貨,貴了出貨」「不是賺多少,是活多久」「新手賠在追高,老手賠在重倉」),放在轉折或收尾,做成觀眾想截圖轉發、也強化記憶的記憶點。
★ 目標長度 30-45 秒(2026 演算法實證甜蜜點):15秒以下已死(要 100% 完播才過關),30-45秒只要 65% 完播就被推廣。但每 3-4 秒要有新衝擊點/轉折,否則像 EP.0 那樣 47秒只剩 26% 完播。**完播率門檻:30秒內要 65%、30-60秒要 50%,過不了演算法直接停推**。
★ 首選題材(實測高完播)：定投生活化(做錯/無腦買/買在高點/停利/微笑曲線)、停損連敗、複利終值、回測往死裡測機器人的進度。
★ 死亡題材(實測低完播,別碰)：抽象公式說教(破產機率/勝率/夏普「比率」)、純蹭新聞、工具設定教學、選擇指南。
★ 5大鉤子結構(2026 faceless 實證·Paddy Galloway 33億Shorts研究,擇一開場):①大膽斷言「九成人定投都做錯,因為一個沒人講的步驟」②好奇缺口「有個定投陷阱,連十年老手都中」③微故事「我把一萬丟進機器人,三十天後我傻了」④視覺衝擊(開場第一幀就是最大數字/前後對比)⑤直接提問「你是不是也以為定投買在高點一定虧?」。（以上句子僅示範句型結構，數字與情境每支都要換成不同的一組，不可逐字複製。）
★ 標題=可搜尋關鍵字(2026 Shorts 搜尋輪播回歸):用觀眾真的會搜的詞(「定投買在高點會虧嗎」勝過「POV:定投時」)。
★ 鐵律目標 VVSA(看完vs滑走)≥70%:前 3 秒滑走率 >40% 這支就死,所以第一句必須是最強的那句,別鋪陳。
6. 誠信不變：不編造損益、不保證收益、不喊單。
7. ★講白話去術語（對完播最直接·2026頂級創作者實證）：術語一律換口語白話——「回測」說「拿歷史行情跑一遍」、「夏普值」說「賺得穩不穩」、「網格套利」說「機器人低買高賣賺價差」、「最大回撤」說「最慘賠多少」、「停利」說「賺夠了就跑」。第一次出現的專有名詞當場用一句白話解釋，寧可囉唆也不要讓陌生人聽不懂而滑走。
"""


LONG_RULES = """
【長片成長鐵律（8-10 分鐘長片專用，蒸餾自 MrBeast／DecodingYT／Greyson 等成長頻道實證）】
★★【A4 真長片引擎·2026-07 頻道整頓】實證問題：過去產出的「長片」實際只有 55-205 秒，
   本質是「比較長的短片」——這樣拿不到長片靠的搜尋流量／長 watch-time。本片必須是**真正的
   8-10 分鐘、資訊密度撐滿全長的長片**，不是把短片腳本硬拉長、也不是灌水贅字湊字數。
★ 深段結構（治「清單體」的核心規則，務必照走）：正文分 3-5 個**各自獨立展開的深段**，
   每段=一個子主題，段落內部要有完整弧線：①具體數據/案例切入 → ②解釋為什麼會這樣/原理
   → ③反直覺轉折或與另一做法的對比。**嚴禁**「第一個坑、第二個坑、第三個坑」這種一句話
   帶過的清單體條列——每個坑/每個重點都要用一整段展開講透，帶真數據或具體案例情境，
   不能只是條列標題。段落之間要有承接語（例如「講完這個，你可能會問…」「但這還沒完，更關鍵的是…」），
   讓正文像有敘事弧線的一篇文章，不是互相獨立的短片拼接。
★ Intro 三步框架（前 30 秒決定留存，務必照走）：
   ①目標：一句話講「看完你能拿走什麼」，帶具體數字承諾（例「這條網格參數讓回撤少一半」）。
   ②障礙：點出多數人卡在哪、為什麼直覺會做錯（製造好奇缺口）。
   ③解法預告：暗示我有可回測驗證的解法，但先不全給——留到正文逐步揭曉。
★ end reward 防跳出：開頭就預告「最後會給一個 ◯◯（checklist／反直覺數字／完整回測）」，把人拉到最後一刻。
★ 標題＝可搜尋長尾（長片靠搜尋流量起家、不吃帳號權重）：用觀眾真的會搜的詞、關鍵字放開頭。三類有搜尋量題型：
   ①回答問題（「派網網格機器人怎麼設」）②教具體技能（「Pionex 第一次設定教學」）③評測比較（「Pionex vs 幣安 新手選哪個」）。
★ 相對留存：每個段落轉折都要給「繼續看下去的理由」，不鋪陳不繞圈；先秀成品（回測曲線／結果畫面）再回頭教。
★ 對比/實測段（結尾前必有）：正文深段講完後，安排一段明確的「對比」或「實測」小結——
   把前面幾個深段的重點放在一起做具體比較（例：方法A vs 方法B 誰的回撤小、哪個情境選哪個），
   給觀眾一個可以直接拿走的結論，而不是講完就結束。
★ 主題一致：緊扣單一受眾（想自動化又怕被割的上班族散戶），別離題到不同客群，否則演算法會重置對你的辨識、燒掉累積。
★ 對仗金句（至少一句·可截圖轉發）：正文轉折或結尾至少放一句結構對稱的對仗/排比金句（例「便宜囤貨，貴了出貨」「新手賠在追高，老手賠在重倉」「不是賺多少，是活多久」），做成觀眾想截圖轉發的記憶點，強化本片被分享的機率。
★ 字數/時長硬性目標（A4 長度 gate 會檢查，不達標會重生或補寫）：voice_text 至少 2200 字、
   目標 2400-3000 字（對應真正 8-10 分鐘）。字數不是靠贅字湊，是靠上面「深段結構」每段真的展開講透
   自然撐出來的——寧可少一個深段但每段紮實，也不要湊出 5 段空洞條列。
6. 誠信不變：不編造損益、不保證收益、不喊單；理財誇大詞（躺賺／穩賺／一天賺X）一律不用（會被演算法限流）；
   台股題一律用 tw_stock_facts 真數據展開深段（不只用一次，每個相關深段都可各自引用不同一項真數字）；
   非台股題無真數據佐證，深段一樣要展開講透，但數字一律用「假設/示意」語氣（見 A2 誠信規則），不得暗示是真實回測出來的事實。
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

NO_FACTS_INTEGRITY_RULES = """
【★誠信硬規則·本題無真實回測數據佐證(非台股題,系統目前只有 tw_stock_facts.json 這一份真數據)·A2】
- 本片主題沒有對應的真實回測資料檔可查證,**嚴禁把任何具體精確的績效數字講成『真的測過的歷史事實』**——
  包括但不限於「回測過去N次」「平均虧損X%」「夏普值從X掉到Y」「勝率X%變Y%」「報酬率X%」這類看似嚴謹、
  其實是憑空編造的統計語句。這是頻道誠信的命脈：捏造數據被戳破,比不夠聳動更傷頻道。
- 想用數字加強說服力可以,但一律用**「假設」「示意」「打個比方」「模擬情境」**這種明確語氣講可能性
  (例:「假設你連虧三次,帳戶可能只剩六成,這只是打個比方」),不能用肯定句暗示這是你真的回測出來的結果。
- 只講原理、不給精確數字也完全可以，比硬湊一個聽起來很專業的假數字更安全、更誠實。
- 例外：若本片是「回測 EP 系列」的第一人稱模擬實驗(本金/餘額/第幾天這種進度敘事)，
  只要維持「這是我自己做的回測模擬、不是真錢實盤」的語氣，不算違反本條(那是承認的模擬敘事，不是假裝的歷史事實)。
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
        # A1d(2026-07-13)：範例句改從 CTA_ENDING_POOL 動態抽 2 句(近5次不重複)，
        # 不再固定寫死同一句『你是哪種?留言告訴我』——那正是3天內5支撞同句的根因之一。
        _cta_ex = _cta_pool_sample(2)
        spec = ("一支 30–45 秒直式 Shorts(2026 演算法甜蜜點;15秒以下已死,因為要 100% 完播才過得了門檻)。"
                "voice_text 150–220 字、前 2 秒就是鉤子、講清一個觀念但每 3-4 秒一個新衝擊點/轉折維持完播、"
                f"結尾用留言鉤(範例僅供參考句型,務必自創或換句,不要照抄)：『{_cta_ex[0]}』或『{_cta_ex[1]}』"
                "(留言權重比訂閱高)。segments 給 2 段。")
    else:
        spec = ("一支**真正**的 8–10 分鐘長片（A4真長片引擎：不是把短片拉長，資訊密度要撐滿全長）。"
                "voice_text **硬性要求至少 2200 字、目標 2600–3000 字**——低於 2000 字會被長度 gate 直接打回、"
                "整支重生或作廢(白做),所以務必一次寫足、寫滿全長。標題必須是**可搜尋長尾**(觀眾真的會搜的"
                "問題句/教學句/比較句,關鍵字放最前,例『0050 定期定額 vs 一次All in 十年回測』『派網網格機器人怎麼設』)。"
                "結構＝HOOK(前30秒三步框架:一句話講看完能拿走什麼+具體數字承諾→點出多數人卡在哪→暗示我有可回測驗證的解法但先不全給)→"
                "正文 4–5 個各自獨立展開的深段(每段一個子主題，**每段旁白至少 400 字**、段落內部要有「具體數據/案例→原理解釋→"
                "反直覺轉折或對比」的完整弧線，段落間要有承接語(如『講完這個你可能會問…』『但這還沒完,更關鍵的是…』)，"
                "嚴禁「第一個坑/第二個坑」這種清單體一句帶過——每個重點都用一整段展開講透)→"
                "把前面深段重點放一起做具體比較的對比/實測小結(給可帶走的結論)→軟性 CTA 訂閱+派網→下集預告。"
                "segments 給 4–5 段，每段標題對應一個真正展開的子主題。")
    # playbook/training/avoid 限長：原本 playbook 近萬字，會撐爆 token(成本高、Groq 免費版直接 413)。
    # 取前段(最重要的爆款心法在前)即可，省 token 又不破品質。可用 LLM_PB_CHARS 調整。
    _pbmax = int(os.environ.get("LLM_PB_CHARS", "3200"))
    playbook = (load_playbook() or "")[:_pbmax]   # 每支腳本即時讀最新競品 playbook(限長)
    training = (load_training() or "")[:1200]      # 每週進修洞察(限長)
    avoid_block = "\n".join(f"  · {t}" for t in (avoid or [])[:30]) if avoid else "  （無）"
    hook_rules = HOOK_RULES if kind == "short" else LONG_RULES
    hook_rules = hook_rules + _retention_insight()  # P1:把最新完播診斷結論回灌進 prompt(檔不在則優雅跳過)
    hook_rules = hook_rules + _recent_metaphor_block()  # A1:近期已用比喻清單,禁止再用(治「背考古題用爛22次」)
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
    facts_ctx = ""  # A4:長片分段深寫要把真數據帶進每一段,故把 tw facts 區塊獨立留一份
    if is_tw_stock:
        hook_rules = hook_rules + TW_STOCK_RULES
        # 真數據引擎：讀 STUDIO/tw_stock_facts.json，挑與題材相關的真回測數字注入寫稿 prompt。
        # 檔不存在/讀不到/無關聯數字 → 靜默跳過，台股題照樣用 TW_STOCK_RULES 產（標示意數字），不崩。
        try:
            _facts = _load_tw_facts()
            _tw_inject = _tw_facts_context(_facts, topic)
            if _tw_inject:
                assign += _tw_inject
                facts_ctx = _tw_inject
        except Exception:  # noqa: BLE001
            pass
    else:
        # A2 誠信(2026-07 頻道整頓計畫)：非台股題無真實 facts 佐證 → 硬性示意/假設語氣,
        # 禁止把捏造的具體績效數字講成真的回測過的事實(crypto/AI 題目前無真回測資料檔)。
        hook_rules = hook_rules + NO_FACTS_INTEGRITY_RULES
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
    # 長片要吐 2600+ 中文字的 voice_text,3500 token 會被截斷成短長片(A4 根因之一);長片給足 token
    _maxtok = 6500 if kind == "long" else 3500
    txt = llm.complete(prompt, _maxtok, json_mode=True)  # 強制合格 JSON
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("LLM 回應非 JSON")
    result = _to_traditional(json.loads(m.group(0)))  # 安全網：簡轉繁(台灣用字),防 DeepSeek 偶爾出簡體
    result["_is_ep"] = bool(is_ep)  # 供 make_one 判斷是否為 EP 正片 → 產出成功後遞增 EP 引擎
    result["_is_tw_stock"] = bool(is_tw_stock)  # A2:供 make_one 判斷本片是否有 tw_stock_facts 真數據佐證
    result["_is_flagship"] = bool(is_flagship)  # A2:旗艦片已有 AI_COMPANY_RULES 自己的數字紀律,不重複套 A2 重生
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
    # A4 真長片內容引擎(2026-07-13)：長片一次寫不出 2600 字(實測 LLM 只吐 ~1000 字冒充長片)是根因。
    # 改「分段深寫」——保留開場 HOOK,對每個 segment 各發一次 LLM 寫成 ~470 字深段,末尾補對比小結,
    # 串成真 8-10 分鐘資訊密度長片。台股題每段引真數據、非台股題示意語氣(誠信不變)。失敗回原稿。
    if kind == "long":
        result = _densify_long(result, facts_ctx, bool(is_tw_stock))
    return result


def _to_traditional(d):
    """把產出的所有中文欄位轉成繁體中文(台灣用字)。OpenCC 有裝就用 s2twp；沒裝就原樣回。
    為什麼：DeepSeek 等中文模型偶爾滑成簡體，繁中頻道不能出簡體(觀感差+像對岸AI量產)。"""
    try:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
    except Exception:
        return d  # 沒裝 opencc 就靠 prompt 約束(已加語言鐵律)

    # s2twp 過度在地化白名單修正:交易語境「参数」該是「參數」,s2twp 卻轉成軟體慣用的「引數」(配音聽起來怪)
    _TW_FIX = {"引數": "參數", "引數化": "參數化"}

    def conv(x):
        if isinstance(x, str):
            y = cc.convert(x)
            for a, b in _TW_FIX.items():
                if a in y:
                    y = y.replace(a, b)
            return y
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


def _split_voice(voice, n):
    """把完整旁白依句末標點切句、平均分成 n 段。
    給 build_md 讓每段概念卡拿到『該段真旁白』而非只有小標——概念卡靠 heading+narration 分類要畫哪張圖
    (網格/複利/回撤),只給小標訊號太薄常退回預設圖;分到真旁白句就能選對圖。也讓 md 字幕後備(voice.txt 缺時)是真旁白。"""
    sents = [s for s in re.split(r"(?<=[。！？!?])", voice or "") if s.strip()]
    if not sents or n <= 0:
        return [""] * max(n, 0)
    per = max(1, len(sents) // n)
    chunks, i = [], 0
    for k in range(n):
        if k == n - 1:
            chunks.append("".join(sents[i:]).strip())  # 最後一段收尾所有餘句
        else:
            chunks.append("".join(sents[i:i + per]).strip())
            i += per
    return chunks


def build_md(d):
    title = d["title"]
    voice = d.get("voice_text", "")
    lines = [f"# 🎬 {title}", "", "> 頻道：量化阿森｜Carson Quant｜自動產製", "", "---", "",
             "## ⚡ HOOK（0-5 秒）", "", f"**旁白：** {voice[:55]}", "",
             "**建議畫面：** stock market chart、trading screen", "", "## 📦 主體", ""]
    segs = d.get("segments") or [{"heading": "重點", "broll": ["finance", "chart"]}]
    seg_narr = _split_voice(voice, len(segs))  # 完整旁白平均分到各段(給概念卡選對圖)
    for i, seg in enumerate(segs, 1):
        kws = "、".join(seg.get("broll") or ["finance", "data"])
        narr = (seg_narr[i - 1] if i - 1 < len(seg_narr) else "") or seg.get("heading", "")
        lines += [f"### 段落 {i}：{seg.get('heading', '重點')}", "",
                  f"**旁白：** {narr}", "",
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
    t = _r.sub(r"[0-9\uff10-\uff19%/\u3001\uff0c\u3002\uff01\uff1f!?\u2026\s\-_]+", "", t or "")
    # \u4e2d\u6587\u6578\u5b57\u5beb\u6cd5(\u4e8c\u5341\u842c/\u4e8c\u5341\u5e74)\u8ddf\u963f\u62c9\u4f2f\u6578\u5b57(20\u842c/20\u5e74)\u662f\u540c\u7fa9\u8b8a\u9ad4\uff0c\u53ea\u6ffe\u963f\u62c9\u4f2f\u6578\u5b57\u6642\u5169\u8005\u5224\u6210\u4e0d\u540c\u6a19\u984c\u3001
    # \u8fd1\u4f3c\u91cd\u8907\u5075\u6e2c\u6293\u4e0d\u5230\u2014\u2014\u53ea\u6ffe\u300c\u5e36\u9032\u4f4d\u5b57(\u5341\u767e\u5343\u842c\u5104\u5146)\u7684\u6578\u8a5e\u7247\u6bb5\u300d\uff0c\u4e0d\u52d5\u55ae\u7368\u7684\u300c\u4e00/\u4e8c\u300d\u7b49\u5e38\u7528\u5b57\uff0c
    # \u907f\u514d\u8aa4\u50b7\u4e0d\u76f8\u95dc\u4f46\u525b\u597d\u90fd\u542b\u9019\u4e9b\u5b57\u7684\u6a19\u984c(\u5df2\u7528 207 \u652f\u771f\u5be6\u6a19\u984c\u5be6\u6e2c\uff0c0 \u7b46\u65b0\u589e\u8aa4\u5224)\u3002
    t = _r.sub(r"[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5169]*"
               r"[\u5341\u767e\u5343\u842c\u5104\u5146]+"
               r"[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5169]*", "", t)
    return t


# ── 贏家公式評分卡(2026-07·用 198 支有數據片回歸出的標題必備元素,把散在 HOOK_RULES 的原則升級成可打分)──
# A 具體數字(必) B 損失框架(虧光/剩多少,實證優於「賺多少」) C 對比/懸念(vs/差多少/你猜) D 生活比喻(加分) E 禁用骨架(一票否決)
_TF_A = re.compile(r"[0-9０-９%]|[十百千萬億兆]")
_TF_B = re.compile(r"虧光|剩多少|賠|爆|清醒|嚇醒|虧|歸零|套牢|血本|慘|畢業|少賺")
_TF_C = re.compile(r"vs|VS|對比|差多少|差在哪|你猜|還是|多久|幾倍|哪個|真能|其實|竟")
_TF_D = re.compile(r"賓士|手搖|便當|一頓|一杯|一台|一輛|一年|一個月薪")

TITLE_FORMULA = (
    "【贏家標題公式(實證·務必命中)】① 必含具體數字/金額/百分比(數字每支都要換,別每支都套同一個);"
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


# 2026-07 P1:純鋪陳/暖場式起手詞——第一句以這些開頭＝背景交代/自我介紹/軟性提問，不是結論前置。
# 只抓典型鋪陳起手詞，不碰「你猜/你以為/你的」這類已證實有效的第二人稱衝擊句(純加法,不誤傷)。
_PREAMBLE_OPENERS = (
    "你知道嗎", "你有沒有想過", "你有想過",
    "大家好", "各位好", "今天要跟大家", "今天來跟大家",
    "我們來聊聊", "我們今天", "先跟大家", "什麼是",
    "不知道大家", "相信大家都", "說到", "講到",
    "歡迎回來", "自我介紹一下",
)


def _is_preamble_open(head):
    """第一句是否為『鋪陳式暖場』(背景交代/自我介紹/軟性提問)，不是結論/數字直接開場。"""
    t = (head or "").strip()
    if not t:
        return False
    for p in _PREAMBLE_OPENERS:
        # 短詞(≤2字，如「說到／講到」)只認開頭，不做前10字子字串比對——子字串比對容易誤中
        # 中段才出現的強力鉤子句(如「……沒想到，說到底最慘的是……」)，觸發不必要的重生。
        if len(p) <= 2:
            if t.startswith(p):
                return True
        elif t.startswith(p) or p in t[:10]:
            return True
    return False


def _weak_hook(voice_text):
    """第一句(前1秒)弱鉤子判定(保守·沿用重生上限<=2)：
    ·原規則：第一句既無數字、又無衝突詞=弱。
    ·新增痛點第二人稱：開頭一兩句完全沒對觀眾說話(你/妳)時，若又沒有衝突詞撐場=弱。
      刻意保守——只要有衝突詞(卻/居然/差/剩/爆等)就算沒第二人稱也放行，避免誤殺
      同一個策略切點不同夏普值差一倍這類無「你」但很強的金句鉤。純加法：原本擋下的絕不會因此變放行。
    ·2026-07 新增(結論前置 gate)：即使有數字/衝突詞，若第一句仍是典型鋪陳起手詞(你知道嗎/大家好/
      今天要跟大家聊聊/什麼是某某等)=一樣算弱，擋純鋪陳問句開場——回應 retention_insights.json
      開頭12-20%流失最兇、別鋪陳的診斷。純加法：只多擋、不放行任何原本會被擋的片。
    ·2026-07 成長衝刺新增：裸新聞轉述開場(加密爆倉/清算等)實測完播僅24-39%，但原規則的
      「爆」字算衝突詞會誤放行——新增專判:第一句命中 is_liquidation_hijack 且沒有第二人稱/
      對比詞(vs/差/倍/你猜)時＝弱，強制要求轉譯成個人化反直覺對比才算過關。"""
    import re as _r
    body = (voice_text or "").replace("\n", " ")
    head = body.split("。")[0]  # 第一句：管數字/衝突(前1秒最強那句)
    head2 = "。".join(body.split("。")[:2])  # 前一兩句：管第二人稱
    if not head:
        return True
    has_num = bool(_r.search(r"[0-9０-９]|[一二三四五六七八九十百千萬兩半倍成]", head))
    conflict = ["卻", "還", "竟", "居然", "差", "虧", "剩", "爆", "破", "沒想到",
                "其實", "真相", "為什麼", "錯", "陶汰", "變成", "難道"]
    has_conf = any(w in head for w in conflict)
    has_you = _has_second_person(head2)
    # 保守：有衝突詞就不算弱；沒衝突詞時，數字與第二人稱缺一即弱
    # (等於在原「無數字」外，多擋「有數字但整段都不對觀眾說話」的乾巴巴陳述)
    weak_orig = (not has_conf) and ((not has_num) or (not has_you))
    if weak_orig or _is_preamble_open(head):
        return True
    # 裸新聞轉述開場專判：命中加密爆倉/清算類字眼、且完全沒有個人化對比(你/妳/vs/差/倍/你猜)
    # ＝只是把新聞標題念一遍，即使帶「爆」字滿足了上面 has_conf 也一樣視為弱鉤子。
    try:
        if sc.is_liquidation_hijack(head):
            _compare = _r.search(r"vs|VS|你猜|差[0-9一二三四五六七八九十]|[0-9一二三四五六七八九十]倍", head)
            if not has_you and not _compare:
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


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


# ── P2 完播狙擊:中段二次鉤 + 承諾-兌現鏈(2026-07-13·retention_insights.json 10/10 支最大流失落在
# 影片 11%-20% 處回灌)。字元位置概估時間位置(TTS 語速近似恆定，跟 _impact_density/_long_underlength
# 同一套「5字/秒」估時慣例保持一致)；只對 Shorts 查，跟既有 _weak_hook/_impact_density 同一重生上限。
_MID_TWIST_MARKERS = (
    "還不是最慘", "真正的坑", "更慘的還在後面", "這還沒完", "先別急",
    "重點來了", "更誇張的是", "還有更狠的", "才是關鍵", "才是重點",
    "更可怕的是", "接下來更扯", "但這才是開始", "還沒完", "更扯的在後面",
    "問題還沒完", "麻煩還在後面", "更痛的還在後面", "沒想到更慘的是",
    # 上面是完整句型範例；LLM 依規則要求「自己換句、不可逐字照抄」，逐字比對命中率極低會讓 gate
    # 形同虛設(2026-07-13 實產驗證抓到:兩支樣本都寫出真的轉折但沒撞中任一完整句型)。
    # 補一組更通用的轉折/揭密連接詞，只要中段窗口出現任一個，就代表確實有轉折語氣，不強求逐字句型。
    "但", "卻", "而是", "沒想到", "其實", "真正", "才是", "關鍵在", "關鍵是",
    "接下來更", "先別", "更慘", "更扯", "更誇張", "更可怕", "問題在", "重點是",
    "沒告訴你", "更痛的",
)


def _weak_mid_hook(voice_text):
    """中段二次鉤 gate(P2 完播狙擊)：11-20% 位置(開頭鉤子撐過之後)必須有一句『反轉/加碼懸念』
    承接語，讓撐過開頭 3 秒的人有理由留到中段，不是平鋪直敘一路講到結尾。
    用字元位置概估落點(涵蓋 30-45 秒短片的第 4-20 秒左右，比嚴格卡死 11%-20% 更寬鬆，避免
    句界切點剛好落在門檻外就誤殺)；命中任一轉折鉤詞即算通過。極短文本(<40字)不擋，避免誤殺。"""
    t = (voice_text or "").strip()
    n = len(t)
    if n < 40:
        return False
    lo, hi = int(n * 0.10), int(n * 0.45)
    window = t[lo:hi]
    return not any(m in window for m in _MID_TWIST_MARKERS)


_REVEAL_MARKERS = ("答案是", "答案就是", "答案揭曉", "結果是", "結果就是", "结果是", "真相是", "所以答案")


def _reveals_too_early(voice_text, frac=0.30):
    """承諾-兌現鏈 gate(P2 完播狙擊)：開頭拋的數字懸念，答案不能在全片前 30% 就完全揭曉——
    揭曉了觀眾就走。只抓明確揭曉句型(答案是/結果是/真相是等)出現在前 frac 比例的位置，
    不誤判單純數字或衝突詞(那些整段都可能出現，不代表『完整揭曉』)。"""
    t = (voice_text or "").strip()
    if not t:
        return False
    cut = max(1, int(len(t) * frac))
    head = t[:cut]
    return any(m in head for m in _REVEAL_MARKERS)


# A4 真長片引擎(2026-07-13 頻道整頓·收緊 gate + fail-closed)：實證問題＝現存 18 支 L_ 長片
# 中位僅 882 字、最高 1420、0 支達 2200 字目標——「長片引擎」實際只產「比較長的短片」，靠
# 搜尋/長 watch-time 拿不到流量(而長片是 10x 訂閱引擎、唯一瓶頸)。用中文字數＋估計時長雙門檻
# 擋不達標長片(沿用專案既有 5字/秒估時慣例，見 _impact_density)。
# 舊版硬底線刻意設在 1200 字/6分(低於 LONG_RULES 目標)、gate 形同虛設,只重生2次就放行假長片。
# 本次把硬底線拉到 2000 字/8 分(對齊「真 8-10 分鐘」),且改 fail-closed：重生+逐次補寫後仍不達
# 標就**不輸出**這支(return None),絕不再把短長片冒充長片發出去(誠信優先於產量)。
LONG_MIN_CHARS = 2000      # 中文字數硬底線(對應真 8 分鐘;2000字≈400秒≈6.7分純語音+畫面停頓才夠8分)
LONG_TARGET_CHARS = 2600   # 目標字數(對應 8-10 分鐘，供生成/補寫時參考)
LONG_MIN_EST_MIN = 8.0     # 估計時長硬底線(分鐘)


def _long_chinese_chars(voice_text):
    """純中文字數(排除標點/空白/英數)，估時長用；跟 _impact_density 同一套算法保持一致。"""
    import re as _r
    return len(_r.findall(r"[一-鿿]", voice_text or ""))


def _long_underlength(voice_text):
    """A4 長度 gate：字數 <LONG_MIN_CHARS(2000) 或 估計時長(以 5字/秒換算) <LONG_MIN_EST_MIN(8) 分＝不達標。
    任一項不達標就算 True，供 make_one 觸發重生/補寫/fail-closed 不輸出。"""
    n = _long_chinese_chars(voice_text)
    if n < LONG_MIN_CHARS:
        return True
    est_min = (n / 5.0) / 60.0
    return est_min < LONG_MIN_EST_MIN


# A4 分段深寫的數據誠信鐵律：分段要求「具體數據/案例」會誘導 LLM 虛構股價點位(實測抓到
# 「0050從90元跌到60元」「2022高點150元」這種捏造史實)。這段硬約束每個深寫 prompt 都掛,
# 把「能講成事實的數字」死鎖在 facts 給的那幾個,其餘一律假設語氣;且全用中文口語念法
# (百分之八十二,不寫 82%)——既合 TTS 慣例,也讓真數字不落進 fact_guard 的阿拉伯數字誤判。
_LONG_DATA_DISCIPLINE = (
    "\n【數據誠信·鐵律務必遵守】"
    "①你唯一能當成事實講的精確數字,只有上面實證數據區塊給的那幾個(總報酬、年化、最大回撤);"
    "沒給的一律不准自己生。"
    "②**嚴禁虛構任何股價、指數點位、某一年的高點或低點**——像「0050從九十元跌到六十元」"
    "「二零二二年高點一百五十元」「套在六百八十元」這類具體價位/點位全部禁止(系統沒有這些真實資料,"
    "講了就是捏造史實)。要舉例就用「假設」「打個比方」「示意」開頭,別講得像真的發生過。"
    "③所有數字一律用中文口語念法(百分之八十二點三、年化百分之二十四,不要寫成 82.3% 或 24.8%);"
    "講到具體績效百分比時,順帶點明這是歷史回測、不代表未來。"
    "④**嚴禁出現誇大/保證詞**:穩賺、穩賺不賠、保證獲利、保證收益、必賺、包賺、零風險、一定賺、"
    "穩定獲利、躺賺、閉著眼睛賺——就算是要拆穿『大家以為穩賺不賠』的迷思也不要寫出這四個字,"
    "改用『以為很安全』『以為不會賠』『以為包贏』這種說法(審核禁語不看語境,出現即違規)。"
)

# audit_video 的誇大/保證禁語(與 audit_video.BANNED 對齊);densify 產出後掃到就重寫,不讓假長片帶禁語進審核。
_PROMO_BANNED = ("保證賺", "保證獲利", "保證收益", "穩賺不賠", "穩賺", "必賺", "包賺", "零風險",
                 "一定賺", "一定獲利", "穩定獲利", "躺著就能賺", "閉著眼睛賺", "穩定月收", "保本保息", "穩定報酬率")


def _promo_banned_hits(text):
    return [w for w in _PROMO_BANNED if w in (text or "")]


def fact_guard_flags(text):
    """借 fact_guard 判準檢查一段文字有無疑似捏造/未標示數字;讀不到就回空(不擋)。"""
    try:
        import fact_guard
        return fact_guard.flags_for(text or "")
    except Exception:  # noqa: BLE001
        return []


def _long_fact_heal(bodies, facts_ctx, integrity, title):
    """誠信自癒:組稿後跑 fact_guard,對含旗標的深段各重寫一次(把捏造/未標示數字改成 facts 真數字或假設語氣、
    中文念法)。回傳(修過的 bodies, 殘留旗標數)。fact_guard 讀不到就原樣回。"""
    try:
        import fact_guard, llm
    except Exception:  # noqa: BLE001
        return bodies, 0
    for _round in range(2):
        remaining = 0
        for k, para in enumerate(bodies):
            hits = fact_guard.flags_for(para)
            banned = _promo_banned_hits(para)
            if not hits and not banned:
                continue
            try:
                _issue = (f"疑似捏造/未標示數字:{hits[:6]}；" if hits else "") + \
                         (f"誇大保證禁語:{banned}(必刪);" if banned else "")
                hp = (
                    f"你是量化阿森頻道的長片腳本寫手。{GUARD}\n以下段落被守門抓到問題:{_issue}。"
                    "請重寫這一段,維持一樣的長度與子主題,但:把不是下面 facts 給的精確數字全部拿掉或"
                    "改成『假設/示意』語氣、絕不虛構股價點位、所有數字改中文口語念法、講績效百分比時點明歷史回測不代表未來;"
                    "**絕不出現穩賺/穩賺不賠/保證獲利/包賺/零風險等禁語**(要拆迷思改用『以為很安全』)。\n"
                    f"{facts_ctx}\n{integrity}{_LONG_DATA_DISCIPLINE}\n"
                    "只輸出重寫後的完整段落純文字,不要JSON/小標/前後綴。\n\n【原段落】\n" + para
                )
                fixed = _fix_artifacts(_to_traditional(llm.complete(hp, 1800).strip()))
                if fixed and _long_chinese_chars(fixed) >= 100:
                    bodies[k] = fixed
                    if fact_guard.flags_for(fixed) or _promo_banned_hits(fixed):
                        remaining += 1
                else:
                    remaining += 1
            except Exception:  # noqa: BLE001
                remaining += 1
        if remaining == 0:
            break
    return bodies, remaining


def _densify_long(d, facts_ctx, is_tw):
    """A4 真長片內容引擎·分段深寫：治「LLM 一次寫不出 2600 字、只吐 ~1000 字冒充長片」的根因。
    做法：保留原稿開場 HOOK(前 3 句),對每個 segment 各發一次 LLM,把該子主題寫成 ~470 字的深段
    (①具體數據/案例情境切入 →②原理解釋 →③反直覺轉折或對比,段首帶承接語),最後補一段對比/實測小結。
    每段只要寫 ~470 字模型都做得到,4-5 段自然堆到 2200-2600 字。台股題每段可各引不同真數字,
    非台股題一律示意/假設語氣(誠信不變)。任何失敗靜默回原稿,不中斷產線。"""
    try:
        import llm
        segs = d.get("segments") or []
        if len(segs) < 3:
            return d  # 段數太少撐不出長片密度,交給 make_one 的重生機制
        title = d.get("title", "") or ""
        voice = d.get("voice_text", "") or ""
        integrity = TW_STOCK_RULES if is_tw else NO_FACTS_INTEGRITY_RULES
        sents = [s for s in re.split(r"(?<=[。！？!?])", voice) if s.strip()]
        hook = "".join(sents[:3]).strip() if sents else ""  # 保留原稿三步框架 HOOK 開場
        bodies, prev = [], "開場鉤子"
        for i, seg in enumerate(segs, 1):
            heading = ((seg.get("heading") if isinstance(seg, dict) else str(seg)) or f"重點{i}")
            prompt = (
                f"你是量化阿森頻道的專業長片腳本寫手。{GUARD}\n{QUANT_STANDARD}\n"
                f"這是長片《{title}》的第 {i} 段,子主題:「{heading}」。只寫這一段旁白,**務必寫滿 520-620 中文字**"
                "(這是長片深段,字數不夠會被打回,寧可多給細節也不要少寫)。\n"
                "務必有完整弧線且每一步都展開講透:①用具體數據或案例情境切入(不是空泛開場,給場景/數字/人物處境)"
                " →②解釋為什麼會這樣的原理(講清機制、別只下結論) →③一個反直覺轉折,或跟另一種做法的具體對比,"
                "並補一句這對觀眾的實際意義。段首用一句自然承接語接上文"
                f"(上一段講的是「{prev[:30]}」)。嚴禁清單體一句帶過。\n"
                f"{facts_ctx}\n{integrity}{_LONG_DATA_DISCIPLINE}\n"
                "【配音友善】口語、短句為主(每句約15-25字用句號斷開);少用括號/破折號/冒號。\n"
                "只輸出這一段旁白純文字——不要 JSON、不要小標、不要段號、不要任何前後綴或引號。"
            )
            try:
                para = llm.complete(prompt, 1800).strip()
            except Exception:  # noqa: BLE001
                continue
            para = _fix_artifacts(_to_traditional(para))
            if para and _long_chinese_chars(para) >= 120:
                bodies.append(para)
                prev = heading
        if len(bodies) < 3:
            return d  # 深寫沒成功湊到 3 段,回原稿讓 gate 決定重生/fail-closed
        # top-up:總量還沒到目標時,挑最短的 1-2 段就地加深(續補細節/對比),把長度穩穩推過門檻。
        def _cur_total():
            return _long_chinese_chars(hook) + sum(_long_chinese_chars(b) for b in bodies)
        _tu = 0
        while _cur_total() < LONG_TARGET_CHARS and _tu < 2 and bodies:
            _tu += 1
            _idx = min(range(len(bodies)), key=lambda k: _long_chinese_chars(bodies[k]))
            try:
                tp = (
                    f"你是量化阿森頻道的長片腳本寫手。{GUARD}\n以下是長片《{title}》的一個段落,請把它"
                    "『加深擴寫』到 560-680 中文字:補更多具體數據情境、原理細節、或與另一做法的對比,"
                    "維持同一子主題與口語短句,不要改變立場、不要湊贅字重複句。\n"
                    f"{facts_ctx}\n{integrity}{_LONG_DATA_DISCIPLINE}\n只輸出擴寫後的完整段落純文字,不要JSON/小標/前後綴。\n\n"
                    f"【原段落】\n{bodies[_idx]}"
                )
                _ex = _fix_artifacts(_to_traditional(llm.complete(tp, 1800).strip()))
                if _ex and _long_chinese_chars(_ex) > _long_chinese_chars(bodies[_idx]):
                    bodies[_idx] = _ex
                else:
                    break
            except Exception:  # noqa: BLE001
                break
        # 誠信自癒:分段深寫易誘導 LLM 具象化而編股價/落阿拉伯數字,組稿前先跑 fact_guard 逐段修乾淨
        bodies, _rem = _long_fact_heal(bodies, facts_ctx, integrity, title)
        if _rem:
            print(f"[warn] A4 長片誠信自癒後仍殘留 {_rem} 段旗標(交 make_one/fact_guard 續處理)", file=sys.stderr)
        # 對比/實測小結(結尾前必有):把前面深段重點放一起做具體比較,給可帶走的結論 + 軟性 CTA
        try:
            _sub = "\n".join(bodies)[:1400]
            sum_prompt = (
                f"你是量化阿森頻道的長片腳本寫手。{GUARD}\n"
                f"這是長片《{title}》的結尾小結旁白,約 360-460 中文字。任務:把前面幾段的重點放在一起做一個"
                "具體的對比/實測小結,給觀眾一個可以直接帶走的結論(哪種情境該選哪種做法),語氣定調"
                "「我先幫你用數據試過,別自己送死」;最後自然帶一句軟性訂閱鉤與一句下集/系列預告,"
                "不喊單、不保證收益。\n"
                f"{integrity}{_LONG_DATA_DISCIPLINE}\n【配音友善】口語短句。只輸出這段旁白純文字,不要JSON/小標/前後綴。\n"
                f"【前面各段重點摘要】\n{_sub}"
            )
            _summary = _fix_artifacts(_to_traditional(llm.complete(sum_prompt, 1300).strip()))
            if _summary and (fact_guard_flags(_summary) or _promo_banned_hits(_summary)):
                _summary = _long_fact_heal([_summary], facts_ctx, integrity, title)[0][0]
        except Exception:  # noqa: BLE001
            _summary = ""
        # hook 來自 call_claude 主草稿,偶爾也帶禁語/未標示數字 → 一併過自癒(保證整支進審核零禁語)
        if hook and (fact_guard_flags(hook) or _promo_banned_hits(hook)):
            hook = _long_fact_heal([hook], facts_ctx, integrity, title)[0][0]
        parts = ([hook] if hook else []) + bodies + ([_summary] if _summary and _long_chinese_chars(_summary) >= 80 else [])
        new_voice = "\n".join(p for p in parts if p)
        if _long_chinese_chars(new_voice) > _long_chinese_chars(voice):
            d["voice_text"] = new_voice
            d["_densified"] = True
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] A4 長片分段深寫失敗,放行原稿：{str(exc)[:80]}", file=sys.stderr)
    return d


def _expand_long_script(d, kind, topic_override):
    """A4 補寫：長片重生 LONG_RETRY_CAP 次仍不達標時，不再從零重來(重生也常一樣短)，
    改把既有草稿「加深」——針對既有段落各自展開更多真數據/案例/對比,補到目標字數,
    維持 HOOK 與收尾結構不動，只加深正文段落，同樣守 A2 誠信(台股用真數據/非台股用示意假設)。
    任何失敗都靜默放行原稿(不中斷產線)。"""
    try:
        import llm  # 共用路由，同 call_claude
        cur_voice = d.get("voice_text", "") or ""
        cur_title = d.get("title", "") or ""
        is_tw = bool(d.get("_is_tw_stock", False))
        integrity = TW_STOCK_RULES if is_tw else NO_FACTS_INTEGRITY_RULES
        cur_n = _long_chinese_chars(cur_voice)
        prompt = (
            f"你是量化阿森頻道的專業腳本寫手。{GUARD}\n{QUANT_STANDARD}\n"
            f"以下是一支長片草稿《{cur_title}》，但目前只有約 {cur_n} 中文字，遠低於真長片門檻"
            f"(需≥{LONG_TARGET_CHARS}字，對應 8-10 分鐘)。\n"
            "請把它『加深』成真正的長片——不是加贅字/重複句湊字數，而是把既有的每個段落"
            "**展開成有乾貨的深段**：每段補一個具體子主題＋真數據/回測情境/實測案例(不是清單體"
            "一句帶過)，段落之間要有承接語，維持原本 HOOK 開場與收尾(訂閱/下集預告)不變，"
            "只加深、擴寫正文段落。\n"
            f"{integrity}\n"
            "【配音友善】口語、短句為主(每句約15-25字用句號斷開)；少用括號/破折號/冒號；"
            "數字寫成口語念法。\n"
            "只輸出 JSON(不要任何其他文字/markdown圍欄)，格式："
            '{"voice_text":"展開加深後的完整旁白逐字稿"}\n\n'
            f"【原始草稿】\n{cur_voice}"
        )
        txt = llm.complete(prompt, 7000, json_mode=True)  # 加深要吐 2600+ 字,token 要給足否則被截斷
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return d
        expanded = _to_traditional(json.loads(m.group(0)))
        new_voice = _fix_artifacts(expanded.get("voice_text", "") or "")
        if new_voice and _long_chinese_chars(new_voice) > cur_n:
            d["voice_text"] = new_voice
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] A4 長片補寫失敗，放行原稿：{str(exc)[:80]}", file=sys.stderr)
    return d


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
        # 近似重複 或 標題不達贏家公式 或 同模板換數字複製(skeleton_dup) 或 濫用家族本週已達上限
        # (check_skeleton_frequency)→重生(共用上限 3);強制多樣性,堵「定投×賓士」這種新洗版
        while (_too_similar(d.get("title", ""), _ex) or _title_weak(d.get("title", ""))
               or sc.skeleton_dup_any(d.get("title", ""), _ex)
               or sc.check_skeleton_frequency(d.get("title", ""))) and _tries < 3:
            _tries += 1
            d = call_claude(kind, _ex, topic_override)
        if _too_similar(d.get("title", ""), _ex) or sc.skeleton_dup_any(d.get("title", ""), _ex):
            log_ops("補產部門", f"\u26a0\ufe0f 近似重複連3次,跳過:{d.get('title','')[:28]}")
            return None
        if sc.check_skeleton_frequency(d.get("title", "")):
            log_ops("補產部門", "骨架家族本週已達上限,跳過避免洗版:" + d.get("title", "")[:26])
            return None
        if _title_weak(d.get("title", "")):
            log_ops("補產部門", f"標題重生3次仍弱(放行最後版·分{title_formula_score(d.get('title',''))}):{d.get('title','')[:26]}")
    else:
        # 2026-07 成長衝刺：時事 topic_override 原本完全跳過骨架週上限與加密爆倉/清算頻率上限，
        # 是「加密爆倉/網格新聞蹭熱」近一週複製約 6 支、完播僅 24-39% 的破口之一。標題由新聞判斷官
        # 給死、不能像一般題重生換角度，故只做「本週已達上限就跳過本次不產」(不重生)；
        # news_dept 自身有每輪重試與下一輪排程機制，跳過不影響下一次抓新聞的機會。
        if sc.check_skeleton_frequency(d.get("title", "")):
            log_ops("補產部門", "骨架家族本週已達上限(時事題),跳過避免洗版:" + d.get("title", "")[:26])
            return None
        if sc.is_liquidation_hijack(d.get("title", "")) and sc.check_topic_frequency("news_liquidation", cap=2):
            log_ops("補產部門", "加密爆倉/網格新聞本週已達上限(≤2支),跳過避免完播殺手洗版:" + d.get("title", "")[:26])
            return None
    prefix = "S" if kind == "short" else "L"
    # 硬擋弱鉤子+衝擊密度+中段二次鉤缺失+提早揭曉+結尾CTA同質(只對 Shorts)：
    #   ①弱鉤子=前1秒沒數字/衝突、開頭整段不對觀眾說話(痛點第二人稱)、或裸新聞轉述開場(加密爆倉等)
    #   ②衝擊密度=平均 >7 秒才一個斷句(明顯拖沓)
    #   ④中段二次鉤缺失(P2 完播狙擊 2026-07-13)=11-20%位置沒有「反轉/加碼懸念」承接語，
    #     撐過開頭的觀眾在這裡沒有新理由留下(retention_insights.json 10/10 支最大流失處回灌)
    #   ⑤提早揭曉(P2 完播狙擊)=開頭懸念的答案在前 30% 就講完，觀眾拿了就走
    #   ③結尾CTA與近期任一支高度相似(A1去同質化,治「77%結尾同一句」)——只對常規題檢查,
    #     時事 topic_override 的題目本來就與常規題材不同源,不比對(避免誤殺)
    #   ⑥內文中段句型與近期任一支逐句(chunk)高度相似(A1b 深化 2026-07-13)——同樣只對常規題檢查
    #   前面共用同一重生上限(≤2)，用完就放行最後一版(超過上限就記 log 標記，不再無限重生卡死產線)；
    #   2026-07 成長衝刺：①弱鉤子/②衝擊密度改為時事 topic_override 也照查
    #   (裸新聞轉述開場正是完播殺手主因，時事片更該被這道閘擋，不能再豁免)；
    #   ④⑤同樣對時事題照查(中段拖沓/提早爆雷不分題材都會流失，不豁免)。
    if kind == "short":
        _hk = 0
        _recent_ends = _recent_endings(15, 100, "S_*.voice.txt")
        _recent_bodies = _recent_voice_texts(20, "S_*.voice.txt")
        while (_weak_hook(d.get("voice_text", "")) or _impact_density(d.get("voice_text", ""))
               or _weak_mid_hook(d.get("voice_text", "")) or _reveals_too_early(d.get("voice_text", ""))
               or (not topic_override and _ending_too_similar(d.get("voice_text", ""), _recent_ends))
               or (not topic_override and _body_too_similar(d.get("voice_text", ""), _recent_bodies))
               or _notorious_metaphor_hit(d.get("voice_text", ""))) and _hk < 2:
            _hk += 1
            d = call_claude(kind, _ex, topic_override)
        if not topic_override and (_ending_too_similar(d.get("voice_text", ""), _recent_ends)
                                    or _body_too_similar(d.get("voice_text", ""), _recent_bodies)):
            log_ops("補產部門", f"⚠️ A1b內文/CTA與近期重複度高·重生{_hk}次仍命中,已放行需人工複查:{d.get('title','')[:26]}")
        _nm = _notorious_metaphor_hit(d.get("voice_text", ""))
        if _nm:
            log_ops("補產部門", f"⚠️ A1c已知濫用比喻『{_nm}』重生{_hk}次仍命中,已放行需人工複查:{d.get('title','')[:26]}")
    # A4 真長片引擎(2026-07-13 收緊 gate + fail-closed)：長片 call_claude 內已做「分段深寫+誠信自癒」
    # (每段各發一次 LLM 寫深段、跑 fact_guard/禁語逐段修乾淨),單次就能穩定產 2400-3100 字的真長片。
    # 這裡只做長度 gate 把關：不達標(<2000字 或 預估<8分,偶發波動)就整支重生(最多4次,每次都是一支
    # 已深寫+已自癒的新草稿);4 次都不達標就 **fail-closed 不輸出這支**(return None),絕不把短長片
    # 冒充長片發出去——寧可今天少一支長片,也不砸「真 8-10 分鐘資訊密度」的招牌(誠信優先於產量)。
    # (舊 _expand_long_script 整篇重寫易縮水且繞過自癒,已從長片路徑移除;函式保留供他處備援。)
    if kind == "long" and not topic_override:
        _lk = 0
        while _long_underlength(d.get("voice_text", "")) and _lk < 4:
            _lk += 1
            d = call_claude(kind, _ex, topic_override)
        if _long_underlength(d.get("voice_text", "")):
            _n = _long_chinese_chars(d.get("voice_text", ""))
            log_ops("補產部門", f"⛔ A4長片重生4次後仍僅約{_n}字(<{LONG_MIN_CHARS}字/8分),fail-closed不輸出假長片:{d.get('title','')[:24]}")
            print(f"[skip] long 長度不足({_n}字),fail-closed 不輸出:{d.get('title','')[:24]}")
            return None
        # A1b 內文去同質化(2026-07-13 深化)：原本 _ending_too_similar 只給 Shorts 用，長片結尾 CTA
        # 一樣會反覆套同一句、中段句型也一樣會抄自己——長片各自跟長片比(結構跟 Shorts 不同不能互比)。
        # 獨立於長度 gate 的重生上限(≤2)：不跟長度 gate 搶 4 次預算，超過就放行但記 log 標記人工複查。
        _lc = 0
        _recent_ends_l = _recent_endings(15, 100, "L_*.voice.txt")
        _recent_bodies_l = _recent_voice_texts(20, "L_*.voice.txt")
        while (_ending_too_similar(d.get("voice_text", ""), _recent_ends_l)
               or _body_too_similar(d.get("voice_text", ""), _recent_bodies_l)
               or _notorious_metaphor_hit(d.get("voice_text", ""))) and _lc < 2:
            _lc += 1
            d = call_claude(kind, _ex, topic_override)
        if _ending_too_similar(d.get("voice_text", ""), _recent_ends_l) or _body_too_similar(d.get("voice_text", ""), _recent_bodies_l):
            log_ops("補產部門", f"⚠️ A1b長片內文/CTA與近期重複度高·重生{_lc}次仍命中,已放行需人工複查:{d.get('title','')[:26]}")
        _nm_l = _notorious_metaphor_hit(d.get("voice_text", ""))
        if _nm_l:
            log_ops("補產部門", f"⚠️ A1c長片已知濫用比喻『{_nm_l}』重生{_lc}次仍命中,已放行需人工複查:{d.get('title','')[:26]}")
    # A2 誠信硬擋(2026-07 頻道整頓計畫)：非台股題(無 tw_stock_facts 真數據佐證)、
    # 也非已有自己數字紀律的 EP/旗艦 franchise，若疑似捏造具體績效數字(回測N檔/勝率X%/報酬Y%/
    # 夏普轉折/虧損X% 等且無示意假設語境)→ 重生最多 2 次；仍命中就放行最後版但寫警告 log，
    # 供人工複查(誤判成本高，不做「靜默刪片」，跟現有 fact_guard 只旗標的精神一致)。
    if not d.get("_is_tw_stock", False) and not d.get("_is_ep", False) and not d.get("_is_flagship", False):
        _fk = 0
        while _fabricated_perf_claim_d(d) and _fk < 2:
            _fk += 1
            d = call_claude(kind, _ex, topic_override)
        if _fabricated_perf_claim_d(d):
            log_ops("補產部門", f"⚠️ A2疑似捏造績效數字·重生2次仍命中,已放行需人工複查:{d.get('title','')[:26]}")
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
    _record_used_phrases(d, slug)  # A1b:把本支已用比喻句/CTA 結尾記進 STUDIO/used_phrases.json(供稽核)
    sc.record_skeleton_produced(d["title"])  # 記骨架家族時間戳,供週上限(check_skeleton_frequency)計數
    if sc.is_liquidation_hijack(d.get("title", "")):
        sc.record_topic_produced("news_liquidation")  # 加密爆倉/網格新聞蹭熱週上限計數(2026-07 成長衝刺)

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
        _run_render(["scripts/make_video.py", "--slug", slug, "--fps", "30"], env, timeout=2400)  # 長片 30fps 順+渲染久給40分
    ok = (OUT / f"{slug}.mp4").exists() and (OUT / f"{slug}.mp4").stat().st_size > 100 * 1024
    if ok:  # 產製即審核：壞片/違規早發現
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{'；'.join(reasons)[:60]}")
            # P0 止血(2026-07-13)：「旁白疑似截斷」併入結構性壞片，同樣清掉重渲，
            # 不能讓斷尾片停在 quarantined 卻留著壞檔佔 queue_size。
            _FATAL = ("片長過短", "無視訊軌", "無音軌", "檔案過小", "旁白疑似截斷")
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
        if not _has_llm_key():
            print("[FATAL] 找不到任一 LLM 供應商金鑰(OPENROUTER/ANTHROPIC/DEEPSEEK/GEMINI/GROQ)。", file=sys.stderr)
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

    if not _has_llm_key():
        print("[FATAL] 找不到任一 LLM 供應商金鑰(OPENROUTER/ANTHROPIC/DEEPSEEK/GEMINI/GROQ)。", file=sys.stderr)
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

    # P3:本批開跑前設定時事題保底配額(短片/長片各自算;quota=0 時行為與修改前完全相同)
    _set_batch_plan("short", args.shorts)
    _set_batch_plan("long", args.long)
    # 2026-07 台股比重修正:本批開跑前也設定題材桶保底配額(短片/長片各自算,跟時事配額
    # 彼此獨立、互不覆蓋——pull_topic() 內先看時事配額,沒中才看桶配額,兩層可疊加)。
    _set_bucket_plan("short", args.shorts)
    _set_bucket_plan("long", args.long)

    log_ops("補產部門", f"開始補產（庫存 {q}/{args.target}）…")
    made = sum(1 for _ in range(args.shorts) if attempt("short"))
    made += sum(1 for _ in range(args.long) if attempt("long"))
    log_ops("補產部門", f"完成 補產{made}支，片庫{queue_size()}支")
    print(f"本次補產 {made} 支，片庫現 {queue_size()} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
