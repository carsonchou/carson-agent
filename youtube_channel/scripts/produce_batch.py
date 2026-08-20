#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""produce_batch.py — 自動補產（創作靈感+影片+Shorts部門）。

用 Claude API 寫新腳本 → 免費 Edge TTS 配音 → 渲染成片，把片庫補到目標量。
與每日上架排程接成無限迴圈：補產填庫、上架排程(含審核)出貨。

用法：python scripts\\produce_batch.py [--shorts 4] [--long 1] [--target 15]
"""
from __future__ import annotations

import argparse
import hashlib
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
# 黑窗彈跳修復(2026-08-07,Carson 截圖抓到):這支被 local_cron 用 CREATE_NO_WINDOW
# 無視窗啟動,但它自己內部起的子程序(TTS/渲染)沒帶同一個旗標——Windows 的規則是
# 「父程序沒有主控台時,子程序若沒指定旗標會自己新開一個可見主控台」,所以每次配音
# /渲染就跳一個黑窗。_run_tts 對每支腳本都會呼叫,是最高頻的觸發點。
# 同一支修法先前在 local_cron.py 用過(見 memory studio-black-window-popups-fix),
# 這裡是同一個坑在另一個呼叫點重演,不是新問題。
_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"  # 便宜、寫腳本夠用

# 🔴 2026-07-17「裸金額」實測(語料 335 支全掃,見 docs/fact_pool_unit_blindspot.md 同日更正段):
# 「多賺三十七萬」這種**沒講本金、沒講百分比的金額結論**是誠信破口的集中地,原因有三,全部實測過:
#   ①**結構上不可能有憑據**:五個事實庫的 amount 子池只有 14 個值、全是營收級距(最小≈416億),
#     沒有任何「個人損益級距」的數字 → 金額宣稱永遠查無來源,不是守門不夠強。
#   ②**發布端守門碰不到它**:金額只有落在「回測顯示…」這類假掛名句才會被 fact_source_guard 抽取;
#     裸講(EP1「反而多賺三十七萬」)連宣稱都不會產生,直接放行。**= 誠實標來源的被查,不標的過關。**
#   ③**規模詛咒已飽和**:池今天 2446→3777,實測 37/38/87/180/230/430/803 萬**全部** _sourced_strict=True
#     (撞上不相干的百分比)。池只會越長越大 → 守門端已經救不回來,只能從產製端治。
# 而且不只是「查無源」——實測**裸金額連稿子自己的百分比都對不起來**:
#   S_複利20年:稿子自己說「月投三千、年化百分之十、二十年」→ 實質終值 ≈162萬,稿子卻講「只剩四百萬」。
#   S_0050定投10年:稿子自己說「年化24.5% vs 16.9%」→ 一百萬本金差 418萬,稿子卻講「少賺803萬」。
#   S_0050定期定額10年:稿子自己說「815% vs 380%」→ 要湊出「少賺180萬」得本金41.4萬(荒謬)。
# → LLM 是**獨立於它拿到的真數據**另外生一個順口的金額,不是算錯,是編。
# 治法(本規則):**金額結論必須同場講出本金與百分比**,讓它可被觀眾與守門雙向驗算。
# 這不是新發明——TW_LAB_RULES 早在 2026-07-14 就對「差值/百分比」立過同一條(「不准只裸講差值」),
# 而且那條的理由寫得很清楚:**講出兩邊原始數字「才有震撼感與可驗證性」**——內容價值是**正向**的,
# 不是犧牲。本規則只是把那條從 tw_lab 單一 franchise + 百分比,推廣到全 franchise + 金額。
# ⚠️ 刻意只做**產製端 prompt 規則,不做 gate**:實測「裸金額」偵測器誤殺率 38%(21 flag 誤 8)
# (「全臺一百二十萬**人**」是人數不是錢、「虧掉五億鎂」是爆倉新聞不是回測、「號稱滾到千萬」是在拆穿
# 別人的宣稱、「最大回撤三成→三百萬少一百萬」是合法算術)——**當 gate 會誤擋合法內容,當 prompt 規則
# 零誤殺風險**(它只是引導生成,不擋任何東西)。這與交接書「別把元/年/分加進單位表」是同一個教訓。
_AMOUNT_DISCIPLINE = (
    "★【金額績效必須可驗算·裸金額零容忍】講到「多賺/少賺/賠掉/剩下 N 萬」這類**金額結論**時,"
    "**必須在同一段講出本金與百分比**,讓觀眾自己就能算得出來"
    "(例:「投入一百萬,報酬百分之三百八十六,等於多賺三百八十六萬」)。"
    "**嚴禁裸講金額**(只說「反而多賺三十七萬」卻沒交代本金與報酬率)——"
    "①觀眾有本金才有比例感,兩邊數字攤開才有震撼感與可驗證性;"
    "②系統的事實庫只有百分比/報酬率,**沒有任何個人損益金額**,裸金額查無憑據=編造。"
    "算不出來、或手上沒有本金數字時,**就只講百分比**(百分比可溯源),不要硬掰一個金額湊畫面感。"
    "金額要跟你講的百分比**算得起來**才准講(對不起來就是編的,寧可不講)。")

GUARD = ("誠信鐵則：不編造個人損益、不保證收益、不喊單、絕不用『保證賺/穩賺不賠/一定賺』等詞；"
         "聯盟軟推＋風險聲明；教學與觀念為主。頻道＝量化阿森｜Carson Quant，繁體中文，"
         "主題＝量化／自動交易（網格、定投、派網 Pionex、回測、風控）。"
         "★【絕不捏造史實·誠信命脈】個股具體價位/歷史高低點/特定日期漲跌若非確定為真,"
         "一律用『假設你套在高點』『假設從某價位』這種**假設語氣**,絕不把可能錯的具體數字斷言成史實"
         "(例:別說『台積電2023高點1000元』這類可能造假的個股史實——寧可用假設情境或不提具體數字)。"
         # 2026-07-17:見上方 _AMOUNT_DISCIPLINE 註解。裸金額是「不編造個人損益」這條老鐵則的
         # 最大破口——它結構上無法溯源,而且實測連稿子自己的百分比都對不起來。
         + _AMOUNT_DISCIPLINE)

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
    "是真的還是僥倖？我幫你拆」。"
    "⚠️ 以上五句是**句式範本不是文案庫**：嚴禁逐字照抄，必須換成本片主題的標的與數字"
    "（實測有台股個股體檢片開場被逐字抄成「你的網格機器人…」——與主題無關＝罐頭簽名＋幣圈詞留存毒藥）。\n"
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


def queue_size(kind=None):
    """片庫量＝『未發布』已成片(mp4)或已備妥待渲染(voice.txt)的去重 slug 數。

    kind: None=全部;"short"=只算 S_ 開頭;"long"=只算 L_ 開頭(2026-07-17 加,
    供分格式 target gate 用——短片堆滿不該把稀缺的長片一起停產)。
    ⚠️排除已發布(在 uploaded_ledger 內)的——否則已發布舊片堆在 output 沒清，
    會讓計數爆滿、誤判『庫存已滿』而停止補產（曾因此整個產線停擺）。
    ⚠️2026-07-17 修:排除 `_ytcta` 副本(append_yt_cta.py 給 IG/TikTok 接片尾卡的跨平台
    匯出檔,YT 原片不動)——它們不是待發的 YT 影片。舊碼把它們算進庫存,實測 320 支「庫存」
    裡 269 支(84%)是 ytcta 衍生檔、其中 239 支原片早就發布了,真庫存只有 51 支。
    output/ 的其他消費者(daily_publish/stall_watchdog/tiktok_upload/ig_backfill/
    build_short_to_long)本來就都排除它,只有這裡漏了 → 產能決策全部失真。"""
    published = set()
    try:
        lp = ROOT / "STUDIO" / "uploaded_ledger.json"
        if lp.exists():
            published = set(json.loads(lp.read_text(encoding="utf-8")).keys())
    except Exception:
        pass
    # 🔴 2026-07-30 再扣一類「永遠不會發」的:publish_skip.json 的跳過名單。
    # 實測(短片):queue_size 看到 55,真正過得了發布端閘門的只有 **11** 支——高估 5 倍。
    # 差額主因就是這份名單:77 支裡有 48 支正落在這個「庫存」集合內,而它們的理由都是
    # 永久性的(跨平台 _ytcta 衍生檔、2026-07-14「信口捏數(38萬/90% 查無來源)」事故片、
    # 命中 is_banned_skeleton 禁用洗版骨架、與已入庫題目數字/主題高度重複)。
    # 後果:補產拿 55 去比目標 12 → 判定「短片達標」而停手,但真實 11 支**低於**目標
    #   → **該補的時候不補**。這正是本函式註解已經記過的失效模式(已發布舊片堆積→誤判滿→
    #   整個產線停擺),只是換了一個新來源。
    # 只扣「便宜且確定」的兩類(帳本、跳過名單);不在這裡跑 audit/品質分,那要對每支片
    #   跑 ffmpeg,會把一個計數函式變成幾分鐘的工作。
    skipped = set()
    try:
        _sp = ROOT / "STUDIO" / "publish_skip.json"
        if _sp.exists():
            _d = json.loads(_sp.read_text(encoding="utf-8")) or {}
            _sl = _d.get("slugs") if isinstance(_d, dict) else None
            if isinstance(_sl, dict):
                skipped = set(_sl.keys())
            elif isinstance(_sl, list):
                skipped = set(_sl)
    except Exception:  # noqa: BLE001  讀不到就當空集合=行為回到修改前,不會更糟
        pass
    # 再扣「已經被評為退件」的:理由**早就存在 quality_scores.json 裡**(score 低於門檻、
    # 或 audit 抓到禁語等硬傷),讀一個 JSON 就有,不必在計數函式裡對每支片跑 ffmpeg。
    # 刻意**不扣** score=None 的「未評分」:那是暫時狀態(LLM 停機時新片評不出分),
    # 片子本身沒問題,重評後就會變成可發庫存——把它當缺貨會催出不必要的產能。
    rejected = set()
    try:
        _qp = ROOT / "STUDIO" / "quality_scores.json"
        if _qp.exists():
            _q = json.loads(_qp.read_text(encoding="utf-8")) or {}
            _min = _q.get("min_score")
            _min = float(_min) if isinstance(_min, (int, float)) else None
            for _it in (_q.get("pending") or []):
                if not isinstance(_it, dict):
                    continue
                _s = _it.get("slug")
                if not _s:
                    continue
                if _it.get("status") in ("reject", "rejected_manual", "degraded"):
                    rejected.add(_s); continue
                _v = _it.get("score")
                if isinstance(_v, (int, float)) and not isinstance(_v, bool) \
                        and _min is not None and _v < _min:
                    rejected.add(_s)
    except Exception:  # noqa: BLE001  讀不到就當空集合=退回修改前行為,不會更糟
        pass
    slugs = set()

    def _add(slug):
        # 用 `in` 不用 endswith:實測 output 下存在 `_ytcta_ytcta` 雙重後綴的檔,
        # endswith 抓得到單層卻漏掉疊層(同日在 quality_score.all_slugs 修過同一個坑)。
        if "_ytcta" in slug or slug in skipped or slug in rejected:
            return
        slugs.add(slug)

    pats = {"short": ("S_",), "long": ("L_",), None: ("S_", "L_")}[kind]
    for p in pats:
        for f in OUT.glob(f"{p}*.mp4"):
            _add(f.stem)
        for f in OUT.glob(f"{p}*.voice.txt"):
            _add(f.name[:-len(".voice.txt")])
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


# ── 事實層去重(2026-07-17 建)────────────────────────────────────────────────
# 現況破口(2026-07-17 庫存複驗實測):既有去重**全都在包裝層**——_too_similar 比標題、
# _ending/_body_too_similar 比旁白句、skeleton_dup_any 比標題骨架、_notorious_metaphor_hit
# 比比喻——沒有任何一道在問「這支片講的是不是**同一個事實**」。
# 實測題庫 1736 題裡 78 題帶 fact_key,其中 **26 個 fact_key 各掛著 2-3 個題目**,例如
# allin_vs_dca_0050_10y 一個 key 掛 3 題:
#   ①「0050一次All in vs定期定額10年結果大公開！年化24.7% vs 16.9%」
#   ②「定期定額0050最慘賠22.6% vs All in賠33.8%！哪種適合你？」
#   ③「『定期定額比較穩』是錯的？0050數據顛覆認知」
# 三題措辭天差地遠(包裝層每一道都放行),但講的是**同一組回測**。`used` 旗標是**逐題**的、
# 不是逐 fact_key,所以同一個 key 的第 2、3 題照樣會被抽出來各產一支 → 這就是「換殼不換內容」
# 的產製端源頭(實測 EP 機器人日記 7 支只講 2 個事實、26天1.76% 一個事實產了 8 支)。
# 這道在抽題階段就把「同 fact_key 已產過(且還在 window 內)」的題移出候選池 → 自然換下一題。
# 為什麼是 window 不是永久封鎖:事實會隨資料更新(as_of)有新答案,隔一季拿新資料重測同一組
# 是合理的連載素材(對齊 tw_lab_engine 每季 reset used_keys 的設計),那不是換殼。
# 抽不到題不會停產:pull_topic 回 None → call_claude 自由生題(見 1586 行),不會產出重複片。
_FACT_REUSE_WINDOW_DAYS = 90


def _fact_dedup(cand, bank):
    """濾掉『同 fact_key 近期已產過』的候選題,回過濾後的 cand。
    fail-open:任何例外一律回原 cand——去重壞掉可以接受,把產線弄停不行。"""
    try:
        now = time.time()
        win = _FACT_REUSE_WINDOW_DAYS * 86400
        blocked = set()
        for t in bank:
            fk = str(t.get("fact_key", "") or "")
            if not fk or not t.get("used"):
                continue
            ua = t.get("used_at")
            # used_at 缺=舊題庫(標 used 時還沒記時間戳)→ 視為近期,保守擋掉。
            # 這正是現在要治的那批(題庫全是近一個月的),新題從這版起都會帶 used_at。
            if not isinstance(ua, (int, float)) or (now - ua) < win:
                blocked.add(fk)
        if not blocked:
            return cand
        out = [t for t in cand if str(t.get("fact_key", "") or "") not in blocked]
        if len(out) < len(cand):
            log_ops("補產部門", f"事實層去重:{len(cand) - len(out)} 題的 fact_key 近期已產過,換題避免換殼不換內容")
        return out
    except Exception:  # noqa: BLE001
        return cand


def _legacy_fact_filter(cand):
    """濾掉『fact_key 指向已退役 legacy 事實』的候選題,回過濾後的 cand。

    根因(2026-07-17 legacy 事實庫退役):STUDIO/tw_stock_facts.json(舊 tw_stock_data.py 產)與
    tw_facts_computed.json 是同一組回測的兩份快照,但 legacy 用的是 `today - years*366` 的
    **滾動窗、每天重算** → 同一個 key 的數字每天漂移,且每筆都**沒有 period/source 欄位**
    (實測 legacy 5 組全部 period=''、source='';computed 50 組全部有)→ 依頻道紅線「數字必須
    可溯源」,legacy 的數字結構上本來就不該過誠信 gate。

    為什麼上面的 _fact_dedup 擋不到:它比的是 fact_key **字串**且只擋「同 key 近期已產過」。
    legacy 與 computed 是**同一組回測的兩個名字**(allin_vs_dca_0050_10y ↔ dca_vs_allin__0050__10y),
    兩邊各自獨立判斷 → 各產一支、數字還不一樣(年化 24.5% vs 24.0%)。實測題庫裡指向 legacy 的
    題共 9 題,其中 7 題 used=False 可被抽中,標題還把漂移數字寫死了(如「All in年化10.1%」——
    今天 legacy 自己已經變成 10.2%,對不回來)。_fact_dedup 目前只是**剛好**擋掉其中 3 題
    (那 3 個 key 剛好有一題 used 且在 90 天窗內),窗一過就全部復活 → 必須照 key 永久擋。

    fail-open(三層):
      ①只擋「真的已被 computed 取代」的 key——computed 對應版本不在(缺檔/算不出來)就不擋,
        寧可用舊數字也不要讓題庫餓死;
      ②任何例外一律回原 cand;
      ③只收緊不放寬:7 題 / 1772 題,不會餓死產線(抽不到還有 call_claude 自由生題)。
    """
    try:
        import tw_facts_engine
        merged = _load_tw_facts() or {}
        results = merged.get("results") or {}
        if not results:
            return cand
        # retired = legacy key 已被 drop_superseded_legacy 拿掉、且 computed 對應版本確實還在
        retired = {lk for lk, ck in tw_facts_engine.LEGACY_SUPERSEDED_BY.items()
                   if lk not in results and ck in results}
        if not retired:
            return cand
        out = [t for t in cand if str(t.get("fact_key", "") or "") not in retired]
        if len(out) < len(cand):
            log_ops("補產部門", f"legacy 事實退役:{len(cand) - len(out)} 題的 fact_key 指向"
                                f"已退役的滾動窗事實庫(數字每天漂移、無 period/source 無法溯源),"
                                f"改抽 computed 的題")
        return out
    except Exception:  # noqa: BLE001
        return cand


def _ep_topic_like(t):
    """這個候選題會不會被 call_claude 的 is_ep 判定吃進「EP 實測系列」。
    判定條件刻意與該處(見 call_claude 的 is_ep)保持一模一樣,兩邊漂移的話 guard 就會有破口。"""
    cat = str(t.get("category", "") or "")
    if cat in ("AI省錢", "AI工具比較", "AI公司揭密"):
        return False
    if any(k in cat for k in ("實測", "實驗")):
        return True
    return any(k in str(t.get("title", "") or "") for k in ("EP", "實測", "實驗"))


def _ep_stale_filter(cand, kind="short"):
    """EP 事實 guard：ep_data 的真數字沒更新 → 把會被當成 EP 的候選題濾掉,這批自然抽別的題。
    這是「不產」而不是「換個標題再產一支」：EP 系列報的是單一真實帳戶,事實沒動就沒有新的一集。
    擋在選題層(而不是寫稿後)有兩個好處：不燒 LLM token、且 pull_topic 會直接挑到別的乾淨題,
    產線量不受影響(實測題庫 740 個未用短片候選中只有 88 個會命中,約 12%)。
    pionex 帶進新數字 → 指紋改變 → fact_is_fresh 回 True → EP 題自動恢復,不需人工解封。
    fail-open：guard 自己壞掉一律回原 cand——去重壞掉可以接受,把產線弄停不行。

    🔴 2026-07-17 只對 short 生效(修長片路徑的誤殺)。根因＝本檔上面那句「判定條件刻意與
    call_claude 的 is_ep 保持一模一樣,兩邊漂移的話 guard 就會有破口」——實際上真的漂了,而且
    是反方向的破口:is_ep 第一個條件就是 `kind == "short"`(EP 實測 franchise 是純 Shorts 系列,
    長片根本不會套 EP_RULES/ep_engine),但 _ep_topic_like 沒有這個條件,於是長片路徑也被這道
    guard 篩。後果:個股體檢系列標題是「個股體檢EP7台積電2330：…」,含「EP」→ 命中
    _ep_topic_like → 被「pionex 帳戶數字沒更新」這個**完全無關**的理由擋掉。而個股體檢綁的是
    checkup_ 前綴 fact_key(FinMind 基本面),跟 pionex 帳戶毫無關係,是全頻道**唯一可持續的
    有憑據長片題源**。實測(sim_pull):明天 8 支長片需求裡有憑據題被抽中 0 支,19 題候選被這道
    誤殺,產線只好全抽 auto_winner 的無憑據題 → 寫稿時編數字 → 渲染完才被發布端擋。
    對 short 的保護力完全不變(is_ep 只在 short 觸發,那裡才是這道 guard 真正該守的地方)。"""
    if kind != "short":
        return cand
    try:
        import ep_engine
        if ep_engine.fact_is_fresh():
            return cand
        out = [t for t in cand if not _ep_topic_like(t)]
        if len(out) < len(cand):
            log_ops("補產部門", f"EP事實未更新(ep_data 的 day/return_pct 與已產過的同一組),"
                                f"{len(cand) - len(out)} 題 EP 候選跳過,改抽別的題")
        return out
    except Exception:  # noqa: BLE001
        return cand


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
    # 2026-07-17 事實層去重:同一個 fact_key 近期已產過就換題(見 _fact_dedup 的根因說明)
    cand = _fact_dedup(cand, bank)
    # 2026-07-17 legacy 事實退役:fact_key 指向滾動窗舊事實庫的題一律不抽(見 _legacy_fact_filter)。
    # 排在 _fact_dedup 之後:那道只擋「同 key 近期已產過」,擋不到「同一組回測的另一個名字」。
    cand = _legacy_fact_filter(cand)
    # 2026-07-17 EP 事實 guard:EP 題沒有 fact_key,上面那道擋不到(見 _ep_stale_filter 的根因說明)
    # 帶 kind:EP 實測 franchise 只在 short 觸發(call_claude 的 is_ep 第一個條件就是 kind=="short"),
    # 長片路徑套這道只會誤殺「個股體檢EPn」這種同樣含 EP 但綁 checkup_ fact_key 的有憑據長片題。
    cand = _ep_stale_filter(cand, kind)
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
        # 2026-07-15「個股體檢」系列(Carson拍板高優先，1900檔一天一集規模化排隊)：LLM生的
        # category/title不保證帶「個股體檢」字樣(topics_from_facts.py讓LLM自由生category)，
        # 但fact_key是確定性寫死的checkup_前綴(見stock_checkup_daily.py種題)，用它判斷才可靠。
        # 獨立成一層(高於一般winner、低於旗艦)：實測只併進winner層會跟0050/0056等winner題平手，
        # 平手由題庫插入順序決定→體檢集被舊winner題卡住斷更(2026-07-15實跑抓到:--long 1抽到0056題)。
        _fk = str(t.get("fact_key", ""))
        checkup = 0 if _fk.startswith("checkup_") else 1
        if checkup == 0 and flag == 1:
            # 體檢題彼此之間不再比winner/seo等tie-break——後面那些key會打亂集數順序
            # (實測:EP7標題含00878命中_WINNER_KW排到EP2鴻海前面)。全部歸零讓sort穩定性
            # 保留題庫插入順序=種題順序=集數順序，觀眾看到的連載才不會EP7先於EP2。
            return (flag, 0, 0, 0, 0, 0, 0)
        winner = 0 if any(k in _ta for k in _WINNER_KW) else 1  # 贏家脈絡優先(2026-07 成長衝刺放大)
        news_src = 1 if src in ("news", "hotspot", "breakout", "intel") else 0
        depri = 1 if t.get("deprioritized") else 0  # A5:含輸家詞的題被降權排最後
        seo = 0 if _seo_hit(_ta) else 1             # A2:含高意圖搜尋詞的題優先
        num = 0 if any(k in _ta for k in _NUM_KW) else 1
        return (flag, checkup, winner, news_src, depri, seo, num)
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
    chosen["used_at"] = time.time()  # 供 _fact_dedup 判斷「同 fact_key 是否近期已產過」的時間窗
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
    # 2026-07-18 移除「想要完整回測數據?留言『數據』我私你」——它是池裡唯一「承諾交付東西」的 CTA,
    # 但:①交付機制從未運作(comment_dept:293 自認 post_cta_comment 沒被排程呼叫過、tg_leads 累計 0 筆)
    # ②很多用它的片根本沒做那個回測=用**不存在的**完整回測資料當誘餌(全頻道 112 支中鏢)。
    # 這是系統性空頭誘餌(誘導互動卻從不兌現),與頻道誠信定位衝突。其餘 12 句純互動誘導、無此問題,保留。
    # (若日後要做誠實 lead magnet:先建真交付機制 + 確保用此句的片有真回測,再加回。)
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


# 🔴 保護清單:這些是「每支片都該有」的必要用語(免責揭露 / CTA 結構 / 誠信語境),
# 絕不可因為「跨檔重複出現」就被列進禁用清單餵給 LLM——那會叫 LLM 別再講免責聲明。
# 2026-07-13 實測:n-gram 抽出的禁用清單裡赫然有「代表未來」(來自法定必要的
# 「歷史回測、不代表未來」)、「人留言告」「是哪種留」等切碎片段。把「代表未來」告訴 LLM
# 「這句用過了別再用」,等於誘導它把免責聲明拿掉——去重 bug 會直接變成誠信事故。
_PHRASE_PROTECTED = (
    "不代表未來", "代表未來", "歷史回測", "回測資料", "僅供參考", "投資建議", "不構成",
    "非保證", "獲利保證", "示意", "假設", "留言", "訂閱", "追蹤", "分享", "按讚",
    "百分之", "年化", "報酬", "回撤", "本金", "數據", "資料",
)


def _is_protected_phrase(g: str) -> bool:
    """這個片語是不是必要用語(或其片段)?是就不准進禁用清單。"""
    return any(p in g or g in p for p in _PHRASE_PROTECTED)


def _extract_repeated_ngrams(texts, n=6, min_count=4):
    """跨檔統計重複出現的 n 字中文片語，回傳『出現在 >= min_count 個不同檔案』的片語
    (跨檔重複＝真正被反覆套用的『特色短語』；單檔內自己重複不算)。輕量字元 n-gram，不做完整斷詞。

    2026-07-13 修:原本 n=4/min_count=3 太寬鬆,抽出來的是「酬百分之」「人留言告」這種
    切碎的無意義片段(而非真正的比喻/特色句),既擋不到真正的重複比喻(「少賺一台賓士」漏抓),
    又會把免責聲明的片段列進禁用。改成 n=6(6字以上才可能是有語意的短句)、min_count=4
    (要真的常出現),並過濾掉保護清單。
    """
    from collections import Counter
    file_grams = []
    for t in texts:
        chars_only = re.sub(r"[^一-鿿]", "", t or "")
        file_grams.append({chars_only[i:i + n] for i in range(max(len(chars_only) - n + 1, 0))})
    counter = Counter()
    for grams in file_grams:
        counter.update(grams)
    return [g for g, c in counter.items() if c >= min_count and not _is_protected_phrase(g)]


# 「比較型比喻」:少賺/多賺一台賓士、等於一棟房、相當於三支iPhone……
# 這family 是實測抓到的重複大戶(「少賺一台賓士」3 天內用在 5 支不同影片),但它不含
# 「就像/好比」等比喻標記詞,_extract_metaphor_sentences 抓不到,n-gram 也切碎抓不準。
_RX_COMPARE_METAPHOR = re.compile(
    r"(少賺|多賺|少領|等於|相當於|換得|買得起|夠買)\s*[一二三四五兩幾\d]+\s*(台|臺|輛|棟|間|支|隻|杯|年)\s*[^\s，。!！?？、]{1,6}"
)


def _extract_compare_metaphors(text: str):
    """抽出「少賺一台賓士」這類比較型比喻(標的物才是重點,如『賓士』『房』)。"""
    return [m.group(0).strip() for m in _RX_COMPARE_METAPHOR.finditer(text or "")]


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
        hit.update(_extract_metaphor_sentences(t))   # 含「就像/好比/等於是」的比喻句
        hit.update(_extract_compare_metaphors(t))    # 「少賺一台賓士」family(3天撞5支的元兇)
    # 🔴 2026-07-13:_extract_repeated_ngrams 這個來源刻意**不用**。
    # 它抓的是「跨檔重複出現的片段」,但這個頻道**該重複的東西正好也跨檔重複**——實測它抽出:
    #   「量化阿森下支」「蹤量化阿森下」← 招牌片尾(追蹤量化阿森,下支繼續)
    #   「每月定期定額」            ← 頻道核心題材本身
    #   「代表未來」                ← 法定必要的免責聲明「歷史回測、不代表未來」
    #   「人留言告」「是哪種留」    ← 切碎的無語意片段
    # 把這些餵給 LLM 說「用過了別再用」= 叫它拿掉免責聲明、拿掉招牌片尾、不准再講定期定額。
    # n-gram 分不出「招牌」與「偷懶重複」——招牌本來就該每支都出現。去重要抓的是**比喻與包裝**,
    # 不是「常出現的字串」。精準度優先:誤擋的代價(誠信事故/品牌斷裂)遠高於漏擋一個比喻。
    return {h for h in hit if h and not _is_protected_phrase(h)}


def _loads_lenient(txt):
    """把 LLM 回應解析成 dict;**被 token 上限截斷的 JSON 也盡量救回來**。回不了就 None。

    2026-07-13 實案:長片產製吐「[err long 第2次] LLM 回應非 JSON」→ 該批 0 支長片。
    根因不是模型講廢話,是**輸出撞 token 上限被硬切**——JSON 少了結尾的括號/引號,
    舊碼 `re.search(r"\\{.*\\}")` 找不到閉合的 }，就把整段**已經花錢生出來、內容其實完好的**
    2000+ 字旁白全部丟掉重來。長片是 YPP 唯一路徑,一次失敗=當天少一支,不能這樣浪費。

    策略:①先照原樣抓完整 JSON ②抓不到就從第一個 { 開始,自動補上未閉合的字串/括號再解析
    (截斷通常只斷在最後一個欄位,前面的 title/voice_text 多半是完整的,救得回來)。
    """
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            pass  # 抓到了但解不開(內部截斷/壞跳脫)→ 走下面的修復
    i = txt.find("{")
    if i < 0:
        return None
    s = txt[i:]
    # 逐字掃描,用**括號堆疊**記住每一層該補什麼(不能只算深度——陣列要補 ] 不是 }),
    # 並記錄是否斷在字串/跳脫字元中間。
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in "}]" and stack:
                stack.pop()
    repaired = s
    if esc:                      # 尾巴斷在跳脫字元 → 砍掉它(否則補完引號仍是壞跳脫)
        repaired = repaired[:-1]
    if in_str:                   # 尾巴斷在字串中間 → 先把引號補起來
        repaired += '"'
    repaired += "".join(reversed(stack))   # 由內而外補回未閉合的括號(型別要對)
    for cand in (repaired, re.sub(r",\s*([}\]])", r"\1", repaired)):  # 順手清尾逗號
        try:
            return json.loads(cand)
        except Exception:  # noqa: BLE001
            continue
    return None


def _self_repeated_metaphor(text, thr=0.72):
    """🔴 片內比喻自我重複——去重機制的盲區(2026-07-13 用實產長片抓到)。

    既有 dedup 全是**跨影片**比對(近 N 支用過的別再用),但**同一支片裡把同一個比喻講兩次**
    完全沒查。實產的 9.2 分長片實測:
        「這就像專注撿零錢卻忽略眼前的金礦」
        「這就像你專注撿零錢，卻忽略了眼前的金礦」   ← 同一個比喻,只加了「你」和逗號
    這正是內容審查點名的「換人物/換包裝重講同一件事」的殘留形態:觀眾聽第二次就知道在灌水。

    判準:抽出全片比喻句,兩兩比相似度(先去掉你/的/了/，等虛詞再比,避免換皮騙過);
    任兩句 >= thr 即判定自我重複 → 觸發重寫。回 True = 有問題。
    """
    from difflib import SequenceMatcher
    ms = _extract_metaphor_sentences(text or "")
    if len(ms) < 2:
        return False
    def _norm(s):  # 去虛詞/標點,讓「這就像你專注撿零錢，卻忽略了…」與「這就像專注撿零錢卻忽略…」對齊
        return re.sub(r"[你我他的了，、。：；\s]", "", s)
    norm = [_norm(m) for m in ms]
    for i in range(len(norm)):
        for j in range(i + 1, len(norm)):
            if not norm[i] or not norm[j]:
                continue
            if SequenceMatcher(None, norm[i], norm[j]).ratio() >= thr:
                return True
    return False


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
【★爆款標題句式(2026-07-15 競品逆向·對7個台股頭部頻道實查歸納,硬性)】
賽道全樣本共同特徵:**標題必帶具體代碼**(0050/00878/0056/006208/2330…)+**比較/反差句式**
(「存5張能贏幾個人?」「不香了?」「這樣做 vs 那樣做」),核心是製造「你可能落後別人/常識
可能是錯的」的認知落差——不是教學語氣。
實證:阿格力「00878上百萬股東,存5張能贏幾個人?」36K 觀看;卡哇KAWA 連 tag 都塞滿代碼。
- 標題**只要題材有具體標的就必須把代碼寫進標題**(演算法與搜尋抓得到「00878」,抓不到「迷思」
  這種抽象詞);「拆穿XX迷思」這種寫法降權使用,改寫成「代碼+動作+數字+比較」。
- 比較敘事優先:「你 vs 別人」「A做法 vs B做法誰對」,不用「教你怎麼做」的說教框架。
【★Shorts 標題三條硬規(2026-07-28 本頻道真數據回歸·非猜測,只留統計顯著的)】
資料:173 支 Shorts 的真實觀看(YouTube Analytics 近180天)+API 真發布日,只取發布滿4天者;
為排除「6月幣圈期 vs 7月台股期」的時間偏誤,以下數字全部是**只看 7 月同期 n=134** 的結果。
① **禁止**把「網格/機器人/派網/比特幣/BTC/爆倉/加密」這類幣圈機器人詞放進 Shorts 標題。
   實測:標題含「網格」觀看中位數 89 vs 149(0.60x, n=29/105, p=0.009);含「機器人」95 vs 147
   (0.65x, n=27, p=0.039);含「比特幣/BTC」94.5 vs 146.5(0.65x, n=18, p=0.033)。
   拆成 07-01~08 / 07-09~16 / 07-17~24 三個時段各自重算,幣圈標題全部落後(94vs243、66vs147、
   92vs158),不是單片帶偏。機制:幣圈題材完播中位數只有 35.5%,非幣圈 47.2%——標題一出現幣圈詞,
   陌生觀眾直接判定「跟我無關」而滑走,完播垮掉演算法就不推。
   ★工具(派網/機器人/參數)只能在旁白後段當「解法的執行步驟」出現,**永遠不進標題**。
② **標題要有台股具體標的**(0050/0056/00878/2330/台積電/四位數代號)或「定期定額/定投」這類
   台股動作詞:含台股代號 165 vs 102(1.62x, n=55/79, p=0.004);含 0050 161.5 vs 107.5
   (1.50x, n=48, p=0.026);含「定期定額/定投」190 vs 110.5(1.72x, n=36, p=0.015)。
   若題材本來就不是個股(通用投資觀念),不用硬塞代號——通用觀念題中位數 149,與台股題(173.5)
   統計上分不出高下(p=0.44),真正被壓的只有幣圈題(88)。
③ **Shorts 標題不要出現「EP數字」**。實測含 EPn 的 15 支:觀看中位數 78 vs 142(0.55x,p=0.005),
   且這 15 支合計帶來 **0 個訂閱**(非 EP 片每千觀看 0.57 訂閱)。系列連載感要靠片尾懸念與播放清單,
   不是靠把集數編號寫在標題把陌生人擋在門外(陌生人不知道 EP1~EP9 在講什麼,不會從第 10 集開始追)。
④ 提醒(避免把力氣花錯地方):標題「有沒有阿拉伯數字/有沒有百分比/有沒有問號/有沒有 vs」在本頻道
   實測**都分不出高下**(全部 p>0.25),標題長度與觀看也無相關(spearman -0.05)。真正拉開差距的是
   **題材選擇**與**完播率**(完播≥50% 的片觀看中位數 222 vs 107,2.07x,p=0.003)。
   所以:句式微調到此為止,把力氣放在「題材別選幣圈」與「前3秒留住人」。
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
1b. ★★硬性(2026-08-11 留存曲線實測·目前最大的完播殺手)：**開場禁止寫成「短碎句連發」**。
   實例(近7天觀看最高的台半5425，1744 觀看)開場是：
       「這檔股票。十八年總報酬兩百七十趴。年化七點三趴。」
   三個沒有主詞的數據碎片連發，唸出來像在念報表。該片留存曲線：
       第 17 秒 0.82 → 第 28 秒 **0.46**，一口氣掉 44%，之後再也沒回來。
   全庫掃描近 40 支長片，**9 支(24%)** 是這種碎句開場。
   規則：**開場前兩句每句都必須是「有主詞、能獨立看懂」的完整句子**，
   單句中文字數不得少於 15 字。數字要「長在句子裡」(例:「台半這檔股票，
   十八年抱下來總報酬 270%，聽起來很香」)，**不可以自己斷成一句**
   (例:「十八年總報酬兩百七十趴。」← 這樣是錯的)。
   也嚴禁開場把同一組數字用「中文數字」講一次、再用「阿拉伯數字」講一次。
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
   「你的設定是哪種?留言告訴我」／「你會怎麼選?留言告訴我你的答案」／「猜到答案了嗎?留言公布你的猜測」／
   「這招你敢用嗎?留言說說你的顧慮」／也可以自己想一句更貼合本片主題的問句，只要能引導留言互動就算數。
   (2026-07-18 從示例移除「想要完整回測數據?留言『數據』我私你」:承諾私訊交付但交付機制從未運作、
    且多數片沒真回測=空頭誘餌;別再示範給 LLM 照抄。要引導互動用上面純討論型句子,不要承諾交付不存在的東西。)
4b. ★片內訂閱鉤(所有片必留·輕量·接在留言鉤後,不取代留言鉤):留言鉤之後補一句 ≤25 字的訂閱鉤。**硬性要求三件事**：
   ①**必須明確出現「訂閱」二字**——YouTube 按鈕上寫的就是「訂閱」，講「追蹤／關注／追更」是 IG／抖音語彙，
     觀眾聽完不知道要按哪個鍵(實測本頻道 62% 的 Shorts 只講「追蹤」，這是錯字級的低級失誤)。
   ②理由必須是**內容價值承諾**——講清楚訂閱之後會拿到什麼具體東西(下一支要拆什麼、下一組數字何時給)。
     **嚴禁**用「不然演算法不會再推你／別讓演算法把你刷走」這類平台操弄的威脅語氣當理由：那是在幫平台
     講話，不是給觀眾好處，而且跟本頻道「誠實、幫你先踩坑」的人設互斥。
   ③**每支換不同措辭**，不要每支都套同一句(實測 19% 的片逐字重複同一句，傷「誠實」賣點)。
   **漏掉訂閱鉤、或只講「追蹤」沒講「訂閱」＝不合格。**
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
★★★【前 30 秒生死線·2026-08-06 留存實測,最高優先】
   實測本頻道長片的觀眾留存(YouTube Analytics audienceWatchRatio,換算成絕對秒數):
     第 15 秒 0.85~0.89(守得住,比短片還好) → **第 30 秒只剩 0.42~0.54**
   也就是**一半的觀眾在第 15 到 30 秒之間離開**。逐字對照最差那支(個股體檢聯鈞,
   30 秒剩 0.42),那 15 秒裡塞了三件事:
     ①「卡瑪比率只有零點二四」——開場就丟術語(全長片 35% 犯這條)
     ②「接續上一段提到的…」——講稿接縫,觀眾根本不知道有「上一段」(26% 犯)
     ③ 把鉤子剛講過的總報酬和年化**原樣再講一次**(33% 犯)
   而留存最好那支(第 30 秒 0.66)開場只做一件事:給一個**可代入的具體比較**
   ——「同樣是定期定額 0050,光是扣款日的選擇,十年後竟然可以差到**一臺機車的錢**」。
   所以前 30 秒(約前 160 個字)**硬規則**:
   ⓐ **禁止任何專有名詞**(卡瑪比率／夏普／標準差／波動率／貝塔／CAGR…)。要講風險
      就用生活話:「最慘的時候資產剩不到兩成」勝過「最大回撤百分之八十六」。
   ⓑ **禁止重述鉤子已經講過的數字**。鉤子講過的,正文換個角度深化,不要原樣覆誦。
   ⓒ **禁止「接續上一段／承上／前面提到」這類接縫語**——那是我們切段落留下的疤。
   ⓓ 一句話最多一個數字;開場兩句話裡**不要出現第三個百分比**。
   ⓔ 最好的開場是「一個可代入的具體比較」:把抽象報酬換算成觀眾生活裡的東西
      (一臺機車／一年房租／幾個月薪水),再進數據。

★★【段落型態留存實測·2026-08-12(83 支已發布長片,逐段留存×句時間戳對映,scripts/retention_segments.py)】
   各段落型態的「相對流失速度」(1.0=同片平均,越大=觀眾走得越快):
     風險/免責句 **1.60x**|訂閱CTA 1.31x|比喻故事 1.09x|回測 1.02x|解說 0.96x|**財報數字 0.87x**
   由此的硬規則:
   ⓕ **風險提醒只出現一次、集中在片尾、一句話**。正文中禁止散撒「可能遇到資產大幅縮水的
      風險」「投資前務必評估自身風險承受能力」這類 hedging 句——實測它們是全片掉人最快的
      段落型態(1.60x)。片尾那句照舊必須有(誠信生死線),但正文不重複。
   ⓖ **說教總結句是懸崖製造機**:「關鍵不在於…而是要評估…」(36x 懸崖)「這就是長期持有
      最現實的考驗」(26x)「最真實的寫照」(45x)——這類把數據拉回人生大道理的收束句,
      觀眾一聽就知道「重點講完了」直接關片。收束一律用**具體數字對比**收,不用道理收。
   ⓗ **禁止空泛的「一定要看到最後」**(24x 懸崖)。要留人用具體 payoff:「最後會給你
      這 20 年每次崩盤的實際回本天數」——說得出東西才留得住人,說不出就別承諾。
   ⓘ 比喻(就像打折採購/雲霄飛車)實測不留人(1.09x),每片最多一個,且不放在段落開頭。
   ⓙ 觀眾最不走的是**密集真數字**段(財報 0.87x)——猶豫要塞道理還是塞數字時,永遠塞數字。

★★★【ⓚ 鉤子之後**禁止任何節目預告與頻道自我介紹**·2026-08-19 留存曲線實測】
   拉台半 5425 的逐點留存曲線(elapsedVideoTimeRatio × audienceWatchRatio):
     第 1% 0.93 → 第 3% 0.83 → **第 5% 0.47** → 第 10% 0.29
   該片 490 秒,換算成絕對時間 = **觀眾在第 15 到 25 秒之間走掉一半**,
   而且 relativeRetentionPerformance 全程只有 0.24~0.40(同長度影片中排後段)。
   逐字對照 08-18 那批新片,那 20 秒裡一律是這三句:
     「今天,我將用最真實的資料,帶你體檢這家公司,揭露…」   ← 預告要做什麼
     「量化阿森頻道的目標,就是用資料幫你拆解市場迷思…」     ← 頻道自我介紹
     「在今天的個股體檢系列中,我們將深入分析…」            ← 再預告一次
   開場鉤子那兩句已經修好了(0.93/0.83 守得很漂亮),**人是死在鉤子之後的鋪陳**。
   觀眾已經點進來了,不需要被告知這支影片要講什麼、也不想聽頻道介紹——
   每一句「接下來我要告訴你」都是在推遲兌現,而推遲就是流失。
   硬規則:鉤子(前兩句)講完,**下一句就必須是內容本身**。
   ⓚ-1 禁止「今天我將/我們將帶你/看完這支影片你會知道/接下來我要告訴你」這類預告句。
   ⓚ-2 禁止任何頻道自我介紹(「量化阿森頻道的目標是…」「本頻道用資料…」)。
   ⓚ-3 禁止「首先,我們來認識一下這次的主角」這類過場句——直接開講就是了。
   ⓚ-4 要預告就用**具體的東西**當誘餌(規則ⓗ),而且放在鉤子裡,不另外開一句。
   判準:把第 3~6 句唸出來,如果它們拿掉之後資訊完全沒少,那就是鋪陳,必須拿掉。

★★★【ⓜ 講 0050 對照**必須在同一句標明年數**·2026-08-20 實測 81% 的片犯這條】
   個股體檢的事實有兩組期間,而且**期間不同**:
     ·「上市以來/近 20 年」的總報酬(long_horizon)——這組**沒有** 0050 對照數字
     ·「近 10 年」的三種買法對決(three_way)——0050 的數字**只存在於這組**
   模型很自然會拿前者的個股報酬,配上後者的 0050 報酬,中間寫「同期」。實際踩到的:
     聯鈞:「20 年總報酬 4322.4%…**同期**買進持有 0050 的總報酬是 685.3%」
           → 685.3% 是**10 年**的數字,20 年的 0050 我們根本沒算
     豐泰:「存 20 年…同期 0050 多賺七倍」
           → 20 年豐泰其實賺 1031%(0050 反而輸);10 年那組豐泰是 **-6.7%**
   每個數字都是真的,但**期間被偷換**,效果是**低估 0050**、讓個股顯得比實際好。
   這跟頻道「誠實實測」的定位正好相反,而且觀眾質疑的方向恰恰是反的
   (「0050 相同期間含息報酬差不多」)——等於在他們最會檢查的地方出錯。
   硬規則:
   ⓜ-1 只要句子裡出現 0050 的對照數字,**同一句**就必須寫出是哪段期間
        (「**近十年**,同期 0050 的總報酬是 719.9%」)。年數寫在前一句不算
        ——觀眾聽到那一句的當下就要知道在比什麼期間。
   ⓜ-2 要講 20 年的個股數字,就整段都用 20 年那組,**不要提 0050**(那組沒有對照)。
   ⓜ-3 兩組都想講可以,但要分開講清楚:
        「近二十年這檔賺 1031%;而在資料共同起點之後的近十年,它是 -6.7%,同期 0050 是 719.9%」

"""


EP_RULES = """
【★回測 EP 系列·續集鐵律（本支為「我用回測往死裡測機器人／AI」系列，這是頻道爆款招牌，逐條照走）】
- ★誠實反差鉤（招牌·開場常用）：適時用「別人賣你發財夢，我先用回測把這坑踩死給你看」這類反差當開場——只認數據不賣夢，是本頻道的信任招牌；本支是回測就標明是回測、別假稱丟真錢實盤（但不要自稱沒錢）。
- 前 1.5 秒必含「時間或金錢錨」：第一句就出現「Day X／第 X 天」或「本金 X 萬」，讓陌生人一眼認出這是回測進度。
- 世界觀一致：延續「我用回測往死裡測機器人／AI」的第一人稱設定（是回測、不是真錢實盤），本金、天數、餘額前後連貫，像同一場回測實驗的續集。
- 結尾除 loop 外，必留「續集鉤(cliffhanger)」：最後拋一個未解懸念預告下一集（例「但第 X 天發生一件事，下集見」），再接一個「二選一留言題」逼觀眾選邊（例「你會停損還是加碼？留言告訴我」）。
- **★訂閱追更鉤(EP 系列專屬·合併成一句·2026-07-22 依 audience 數據精簡)**：cliffhanger 之後、留言題之前,補**一句**把懸念綁到「不訂閱=看不到結局」的內容 FOMO 訂閱理由——例「第 X 天帳戶發生的事我只在下集講,想知道結局就訂閱追下一集,不然這結局你看不到」。**只留這一句**:原本「訂閱追更鉤 + FOMO 續集鉤」兩句是重複的訂閱訴求,而 audience 實測 98.3% 觀看來自未訂閱者(堆兩句沒把訂閱提上去)+ 官方影片明說「冗長結尾拖掉往下看的人」→ 合併成一句,訂閱轉換靠「說清楚訂閱拿到什麼(結局)」而非堆句數。損失綁「看不到結局」的**內容價值**,**不要**寫「演算法不會再推你」(平台操弄語氣、且觀眾按的是追蹤不是訂閱,按不到正確的鍵)。留言題與這句訂閱鉤各一句、兩者都要。
- **★開頭 3 秒回顧上集懸念(承接前情,franchise 連貫)**：第一句在丟時間/金錢錨的同時,用半句話回顧上一集結尾的懸念(如「上集第 X 天那根長黑K之後…」),讓追更觀眾無縫接上、新觀眾也秒懂這是系列回測續集(若有『前情提要』段落請照它給的上集資訊回顧)。
- **★系列導流不佔結尾旁白(2026-07-22 精簡)**：「其他 EP 都在播放清單一次追完」這種系列導流,**不要寫進結尾旁白**——放影片描述(已有 playlist 連結)或 YouTube end screen(Studio 手動指向下一集/播放清單)。原因:官方影片明說冗長結尾拖掉往下看的人;結尾旁白只留「續集鉤指名下一集 + 一句訂閱 + 留言題 + loop」四件,導流走非旁白管道更省結尾時長、也是官方點名的推薦入口。
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

# 2026-07-15任務(Carson拍板)：「個股體檢」系列——單獨介紹一隻股票講基本面，台股1900多檔一隻發一集，
# 10分鐘長片。見 stock_checkup_facts.py(價格面：報酬/套牢/腰斬) + stock_fundamentals.py(基本面：
# 營收/EPS/毛利/股利/估值位置)。這裡是「一集結構模板」，與 TW_LAB_RULES 同一套疊加機制(在 TW_STOCK_RULES
# 之外再疊一層更嚴格的順序規範)，不取代 TW_STOCK_RULES 的招牌語氣，只加結構順序與「介紹≠推薦」硬規。
TW_STOCK_CHECKUP_RULES = """
【★「個股體檢」系列·10分鐘長片結構模板(逐段照走，順序不可打亂)】
- 系列定位：量化阿森=數據體檢師，不是選股老師。每集單獨介紹一檔台股，**只陳述公開數據，不推薦、不喊單**。
  「介紹一家公司」跟「叫你買」是兩件事，本系列只做前者——這條是本系列生死線，比任何一集的爆點都重要。
- ★片頭必帶系列名(但**不要**帶集數編號)：片名或旁白開場其中一處要自然帶出「個股體檢」系列名，
  不必生硬複誦。集數(EP幾)**一律不寫**——連載編號在發布時按已發布集數自動連號決定(寫死會跳號)，
  標題與旁白都不得出現「EP幾／第幾集」；片尾接下一集只用「下一集輪到某某」點名，不用集數。
- 五段固定順序(每段都要有，不可省略任何一段，可依內容多寡調整字數配比但順序不可換)：
  ①【公司是誰】用本次注入的產業分類(FinMind官方分類，非猜測)講一句「這家公司是做什麼的」，
     不誇大、不下「護城河很深/前景無限」這類無憑據評語，純陳述所屬產業。
  ②【基本面數據】依序講：近年營收趨勢(是成長還是衰退，用注入的年增率數字)→EPS序列(賺錢能力有沒有變化)→
     毛利率(近幾季走勢，穩定/上升/下滑)→股利發放史(連續配息幾年+近5年平均殖利率，沒有配息紀錄就老實說沒有)。
  ③【價格體檢】沿用 TW_STOCK_RULES 的持有體驗數據(20年報酬/最大回撤/套牢期/腰斬次數)，講「拿著這檔股票
     真實會經歷什麼」，痛點感是這段的重點(套牢幾年/腰斬幾次這類具體數字最能勾住)。
  ④【估值位置】只講本次注入的「目前本益比在自己近10年歷史區間的第幾百分位」，
     **絕對禁止**接著評論「所以現在貴/便宜/該不該買/是不是好買點」——講完百分位數字立刻轉場，
     把判斷權完全留給觀眾。這是本段最容易失守的地方，逐字檢查有沒有不小心滑出「現在便宜」這類語氣詞。
  ⑤【誠實結尾】三件事都要有(順序：風險揭露 → 留言互動題 → 下集點名)：
     a. 風險揭露：這集只是數據陳述，不構成投資建議，投資有賺有賠，自己做功課。
     b. 留言互動題：問觀眾對這檔股票的數據有什麼看法/最意外哪個數字。
     c. 下集點名：用本次注入的「下一檔候選」自然帶出「下一集要體檢哪一檔」，製造追更懸念，
        不劇透下一集的具體數字。
- ★★反模板差異度(2026-08-12,YPP 生存級):YouTube 2025-07-15 的 inauthentic content
  政策明文否決「模板化、影片之間變化極小、可大規模複製」的量產內容——本系列一檔一集
  同一份體檢表,**結構同質是變現申請的直接風險**。緩解硬規:
  a. 每檔的**開場與敘事主軸由「本檔最異常的那一個數據」決定**:這檔是「套牢九年」的
     故事、那檔是「毛利率雪崩」的故事、另一檔是「殖利率陷阱」的故事——先找出 13 項
     事實裡最反直覺/最極端的一項,整集圍繞它展開,其他事實當配角補充。
  b. 各段的深淺比例隨主軸調整:主軸相關的段講深講滿,不相關的段一句帶過——
     **13 項事實是素材庫,不是逐項唸稿的檢查表**。
  c. 開場句式不得與近期片雷同(參考注入的近期片開頭),同款「你知道嗎/你有沒有想過」
     連續出現就換一種進場方式(直接丟最異常數字/場景代入/引述市場說法再打臉皆可)。
  1. 財報數字(營收/EPS/毛利率/股利/本益比)一律只能用本次注入的真實數據，一個字都不能自己換算或估計。
  2. 「介紹≠推薦」鐵律：全片不得出現「這支值得買/該進場/該加碼/現在是好時機/目標價」等任何推薦性語句，
     即使是隱晦暗示(如「聰明的投資人都在關注這支」)也不行。
  3. 估值位置只講「第幾百分位」這個事實，不判斷貴賤——連「相對便宜」「處於高檔」這種聽起來中性但暗示
     判斷的詞都不用，只講數字本身。
"""

TW_LAB_RULES = """
【★台股真相實驗室 franchise·訂閱轉換診斷落地(2026-07-13,逐條照走)】
- 診斷根因(見 tw_lab_engine.py 檔頭)：全站 588 支片 20326 觀看只換 27 訂閱(0.133%)；表現最好的
  8 支片結尾各講各的、只說「追蹤」不說「訂閱」、理由是空泛的「不然演算法不會再推你」——觀眾聽完
  不知道訂閱等於訂閱到什麼。本 franchise 用「有固定形狀、可預期下一集會拿到什麼」的常態連載解決。
- ★命名與集數：本片是「台股真相實驗室」系列一集，題目與集數(EP 幾)以本次注入的
  【★台股真相實驗室系列連貫設定】區塊為準——那裡有上集回顧/本集定位/下集懸念，務必照它給的走，
  片名或旁白開場/結尾其中一處要自然帶出系列名稱與 EP 數字(不必生硬複誦，融入語氣即可)。
- ★開場「你猜」框題：前 2 秒先把比較兩邊丟出來、用「你猜」或反問句吊懸念，**不要在前 5 秒就爆數字**
  (例「一次all in跟每月定期定額，10年後你猜差多少？」)，數字留到中段揭曉才有懸念張力。
- ★數字只能用本次注入的【★本集唯一指定實證數據】那一組，不得混用其他標的/期間的數字湊細節。
- ★講「差多少/差距」時**必須連同兩邊的原始數字一起講**(例「一邊 813%、一邊 379%,差了 434%」),
  不准只裸講差值——①觀眾有兩邊數字才有震撼感與可驗證性 ②發布守門(fact_source_guard)的差值
  驗算要求組成數字同場,裸講差值會被判無憑據擋下不發(2026-07-14 實測)。
- ★結尾三件事都要有(順序：留言題 → 訂閱鉤 → 下集預告，各自一句，不要合併成一句敷衍帶過)：
  ①留言互動題(對這集數字的看法/選邊)
  ②系列訂閱鉤——**必須明確出現「訂閱」二字**(不是只用「追蹤」)，理由是本系列已經排好一整組
  台股真回測要拆、訂閱是唯一會收到下一組數字通知的方式，不用「不然演算法不推你」這種操弄語氣
  ③下集預告——用本次注入區塊給的「下一集題材」懸念句，不洩露具體數字答案。
- 誠信：全部數字標「歷史回測，非未來保證」；不喊單、不報明牌、不喊目標價、不保證獲利；
  不得把「你猜」包裝成保證答案或明牌。
"""

# 台股真相實驗室·**長片**變體(2026-07-19 訂閱轉換診斷落地)——為什麼長片要另一套規則:
#   短片版 TW_LAB_RULES 命令「數字只能用【本集唯一指定實證數據】那一組」,那是 30-45 秒單一數字
#   的正確作法;但長片(A4 LONG_RULES:每 60 秒要一個新數據點、4-5 個深段)拿單一事實只能靠贅字灌水
#   → 低完播 → 反而換不到訂閱(實測 18-20% 完播的長片 0 訂閱)。故長片改走【多事實 bundle】:
#   以本集主軸比較為脊椎,搭配 produce_batch._tw_facts_context 已注入的【本片實證數據】多組**同題材真
#   回測**充實各深段。誠信不放寬、只是把「唯一一組」放寬成「注入的這幾組真數字」——一個字都不能自己編。
TW_LAB_LONG_RULES = """
【★台股真相實驗室 franchise·長片變體(2026-07-19 訂閱轉換診斷落地,逐條照走)】
- 本片是「台股真相實驗室」系列的一集**長片**(8-10 分鐘)。系列連貫設定(上集回顧/本集定位/下集懸念/
  訂閱鉤)以本次注入的【★台股真相實驗室系列連貫設定】區塊為準,務必照它走。
- ★脊椎=標題那個比較:整支片圍繞標題點名的那一組主軸比較展開(那也是【本片實證數據】區塊裡最相關的
  那一條)。其餘注入的真回測數字**不是拿來混題**,是拿來把主軸的各個面向講深講透(對照組、不同期間、
  不同標的的同類現象、反直覺的延伸),讓每個深段都有**真數字**撐,不是靠形容詞灌水。
- ★數字硬規(誠信命脈,長片最容易翻車):所有具體績效數字(報酬率/年化/回撤/差距/勝率/百分位…)**一律
  只能出自本次注入的【本片實證數據】與【系列連貫設定】區塊**。注入區塊沒有的數字,寧可不講也**絕不
  自己編、不自己換算、不自己估**(例:注入給你年化,就不要自己乘出「十年總報酬」;要嘛用注入的總報酬、
  要嘛不講)。這條牴觸任何「講得更具體」的衝動時,以這條為準。
- ★標題與開場的「差距數字」(少賺X%、差X趴、多賺X倍)只能是【本集主軸實證數據】兩個原始數字**實際
  相減/相除算出**的值(連「趴」和中文數字寫法都算),嚴禁湊一個沒算過的整數;全片同一個差距數字、標題
  與正文一致;標題若寫年數就用那個年數的那組數字(近10年/近12年別混)。(此條另有確定性守門硬擋,見
  _fix_tw_lab_title_fabrication:標題含查無憑據的數字會被自動換成不含編造差值的安全標題。)
- ★講「差多少/差距」必須連同兩邊原始數字一起講(例「一邊 813%、一邊 379%,差了 434%」),不准裸講差值
  ——①觀眾要兩邊數字才有震撼與可驗證 ②發布守門 fact_source_guard 的差值驗算要求組成數字同場,裸講差值
  會被判無憑據擋下不發。
- ★深段結構沿用 A4 LONG_RULES:4-5 個各自展開的深段,每段一個子面向、段內走「具體真數據→原理→反直覺
  轉折/對比」的完整弧線,段間用承接語。嚴禁清單體一句帶過。
- ★結尾三件事都要有(順序:留言題 → 系列訂閱鉤 → 下集預告,各一句不敷衍):①對本集數字的看法/選邊
  ②**明確出現「訂閱」二字**(不是只用「追蹤」),理由=本系列已排好一整組台股真回測要拆、訂閱是唯一會
  收到下一組數字通知的方式(不用「不然演算法不推你」這種操弄語氣)③用注入區塊給的下一集題材懸念,不洩數字。
- 誠信:全部數字標「歷史回測,非未來保證」;不喊單、不報明牌、不喊目標價、不保證獲利;不得把「你猜」
  包裝成保證答案或明牌。介紹/驗證一個講法 ≠ 推薦任何操作。
"""


NO_FACTS_INTEGRITY_RULES = """
【★誠信硬規則·本題在事實庫查無對應的真回測數據可引用·A2】
- 本片主題沒有對應的真實回測資料檔可查證,**嚴禁把任何具體精確的績效數字講成『真的測過的歷史事實』**——
  包括但不限於「回測過去N次」「平均虧損X%」「夏普值從X掉到Y」「勝率X%變Y%」「報酬率X%」這類看似嚴謹、
  其實是憑空編造的統計語句。這是頻道誠信的命脈：捏造數據被戳破,比不夠聳動更傷頻道。
- 想用數字加強說服力可以,但一律用**「假設」「示意」「打個比方」「模擬情境」**這種明確語氣講可能性
  (例:「假設你連虧三次,帳戶可能只剩六成,這只是打個比方」),不能用肯定句暗示這是你真的回測出來的結果。
- 只講原理、不給精確數字也完全可以，比硬湊一個聽起來很專業的假數字更安全、更誠實。
- 例外：若本片是「回測 EP 系列」的第一人稱模擬實驗(本金/餘額/第幾天這種進度敘事)，
  只要維持「這是我自己做的回測模擬、不是真錢實盤」的語氣，不算違反本條(那是承認的模擬敘事，不是假裝的歷史事實)。
"""

# 🔴 2026-07-17 破口修復配套:走台股路徑但事實庫**查無對應數據**時,光加 NO_FACTS_INTEGRITY_RULES
# 不夠——TW_STOCK_RULES 還留在同一份 prompt 裡命令「開場前 3 秒直接砸台股具體神話數字」
# (範例就是「當沖九成畢業」)、「回測打臉:例某擇時法回測20年少賺60%」,兩條規則會**互相矛盾**,
# LLM 很可能跟著更具體、更前面的那條走(同 A1c「軟性提示擋不住 LLM、已知累犯要硬擋」的教訓)。
# 故本區塊明講「上面那條本支不適用」,把矛盾**顯式解掉**,而不是留兩條打架的指示讓模型自己選。
TW_NO_FACTS_OVERRIDE = """
【⚠️ 本支無事實·**推翻上面台股格式裡所有「給具體數字」的要求**(本條優先於上述全部格式規則)】
- 本題在事實庫(tw_stock_facts / tw_facts_computed / stock_checkup_facts)**查無任何可引用的真回測數據**。
- 因此上面台股招牌格式的「開場前 3 秒直接砸台股具體神話數字」「回測打臉：例某擇時法回測 20 年少賺 60%」
  這類**要求你講出具體數字的指示,本支一律不適用**——照做就只能自己編,那是頻道紅線(編造被戳破=封台級傷害)。
- 開場改用**不含具體績效數字**的鉤子:純觀念反直覺、提問句、場景痛點、常見誤解破除皆可
  (例:「當沖到底能不能賺?先別急著看勝率,先算你付出去的成本」)。
- 真要提數字,一律用「假設/示意/打個比方/舉例來說」明講是舉例,**不可講成回測結果或歷史統計**。
- **寧可整支不給任何精確數字,也絕不編**。沒數據就把觀念講透——那比硬湊一個聽起來很專業的假數字誠實得多。
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
- 收尾:訂閱鉤(想看這套 AI 公司下一步/翻車實錄，**明講「訂閱」二字**，別用「追蹤」)。
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
# 2026-07-13:tw_facts_engine.py 用真實含息還原股價批次算出的 40 組事實(定投vs單筆/扣款日效應/
# 停利vs續抱/高股息vs市值型/槓桿ETF長抱/擇時vs傻抱/錯過最佳N天/崩盤加碼vs停損)。
TW_FACTS_COMPUTED = ROOT / "STUDIO" / "tw_facts_computed.json"
# 2026-07-15「個股體檢」系列:stock_checkup_facts.py 算的任意個股20年體檢事實
# (checkup_long_horizon__2330 這類 key)。同樣併入餵料端,理由跟下面同一段一致——
# fact_source_guard.FACT_FILES 已經看得到這份檔案，寫稿 LLM 不併進來就會出現
# 「守門擋得住、卻永遠產不出個股體檢下集」的窘境，系列就斷連載。
STOCK_CHECKUP_FACTS = ROOT / "STUDIO" / "stock_checkup_facts.json"
STOCK_CHECKUP_BACKLOG = ROOT / "STUDIO" / "stock_checkup_backlog.json"

_RX_CHECKUP_CODE = re.compile(r"__([0-9]{4,6}[A-Z]?)(?:__|$)")


def _checkup_extract_code(fact_key: str):
    """從 fact_key(如 checkup_revenue_trend__2317 或 checkup_crash__2317__crisis2008)
    抓出股票代號。抓不到回 None(呼叫端靜默不注入系列設定，不影響一般台股題正常產出)。"""
    m = _RX_CHECKUP_CODE.search(fact_key or "")
    return m.group(1) if m else None


def _checkup_next_name(code, by_code=None):
    """回傳下一集要點名的「名稱（代號）」字串；找不到回空字串。
    優先看題庫裡「下一個真的會被抽到的未用體檢題」(pull_topic 對 checkup 層是照插入順序出，
    所以題庫第一個未用體檢題=實際下一集)，跟片尾承諾一致才誠信；題庫沒有別檔的未用體檢題
    (隊伍見底)才退回 backlog 的下一個待體檢代號(明天 daily 會種它)。"""
    if by_code is None:
        try:
            by_code = (json.loads(STOCK_CHECKUP_FACTS.read_text(encoding="utf-8")) or {}).get("by_code") or {}
        except Exception:  # noqa: BLE001
            by_code = {}
    try:
        import topic_bank as _tb_ck
        for t in _tb_ck.load_bank():
            _tfk = str(t.get("fact_key", ""))
            if (not t.get("used") and _tfk.startswith("checkup_")
                    and _checkup_extract_code(_tfk) not in (None, code)):
                _ncode = _checkup_extract_code(_tfk)
                _nname = (by_code.get(_ncode) or {}).get("name", _ncode)
                return f"{_nname}（{_ncode}）"
    except Exception:  # noqa: BLE001
        pass
    try:
        bl = json.loads(STOCK_CHECKUP_BACKLOG.read_text(encoding="utf-8"))
        items = bl.get("items") if isinstance(bl, dict) else bl
        for it in (items or []):
            if it.get("code") != code and not it.get("done") and not it.get("skip"):
                return f"{it.get('name', it.get('code', ''))}（{it.get('code', '')}）"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _checkup_progress():
    """回傳 (已完成檔數, 全市場檔數)。任何一項算不出來就回 (0, 0) → 呼叫端整句不加。

    ⚠️ 誠信:這兩個數字**每次從真實檔案現算**,不可寫死也不可用約略值——
    「已體檢 N 檔」是對觀眾的事實宣稱,寫死的話某天就會變成假話
    (見 memory yt-integrity-methodology-claims-blindspot:EP.0 把假話寫死在表裡繞過守門)。
    來源:STUDIO/stock_checkup_facts.json 的 by_code(已算出事實的檔數)
          STUDIO/stock_checkup_backlog.json 的全市場名單長度
    """
    try:
        _sd = ROOT / "STUDIO"
        facts = json.loads((_sd / "stock_checkup_facts.json").read_text(encoding="utf-8"))
        done = len(facts.get("by_code") or {})
        bl = json.loads((_sd / "stock_checkup_backlog.json").read_text(encoding="utf-8"))
        # backlog 的鍵是 items(不是 rows),而且檔案自帶 n_total —— 優先用它自己算好的數字。
        if isinstance(bl, dict):
            total = int(bl.get("n_total") or 0) or len(bl.get("items") or [])
        else:
            total = len(bl or [])
    except Exception:  # noqa: BLE001
        return (0, 0)
    if done < 1 or total < done:
        return (0, 0)
    return (done, total)


def _checkup_finalize(result, next_name):
    """個股體檢片產出後的確定性補強(同 _ai_savings_desc_block 的「確定性附加，保證不被 LLM 吞」
    慣例)——2026-07-15 實跑 EP2 抓到：模板雖注入，LLM 仍把片尾下集點名寫成自由發揮的
    「高股息ETF盲點」(下一集實際是聯發科)，且漏掉留言互動題。regenerate 不可行——長片重生
    會重新 pull_topic 抽到下一題，EP 順序整個亂掉——所以缺什麼就確定性補上一句，不重生。
    只在缺的時候補，LLM 已寫好的不重複。"""
    v = str(result.get("voice_text", "") or "").rstrip()
    if not v:
        return result
    nx = (next_name or "").split("（")[0].strip()
    # 先拆掉片尾「編出來的下集預告」：LLM(尤其 densify 的收尾段)常自由發揮「下集我們探討XXX」，
    # 跟系列實際下一集不符=對觀眾的假承諾。檢查範圍=正文最後30%(EP2實跑抓到假預告落在倒數第5句,
    # 只查最後3句會漏)，只拆「有下集措辭但沒點到真下集標的」的句子，正文前段不動。
    if nx:
        parts = re.split(r"(?<=[。！？])", v)
        total = len(v)
        kept, offset = [], 0
        for sent in parts:
            in_tail = total > 0 and (offset / total) >= 0.7
            offset += len(sent)
            if (in_tail and any(k in sent for k in ("下集", "下一集", "下週", "下期"))
                    and nx not in sent):
                continue  # 假下集預告,拆掉(正確的下面會補)
            kept.append(sent)
        v = "".join(kept).rstrip()
    tail_bits = []
    if "留言" not in v:
        tail_bits.append("留言告訴我，這集哪個數字最讓你意外。")
    if nx and nx not in v:
        tail_bits.append(f"下一集個股體檢，輪到{nx}上體檢台，訂閱頻道才不會錯過。")
    elif "訂閱" not in v:
        tail_bits.append("訂閱頻道，下一集體檢報告出爐第一時間收到。")
    # ── 全市場連載承諾(2026-08-06 訂閱實測)───────────────────────────────────
    # 為什麼要多這一句:體檢片有 **49% 流量來自搜尋**,而搜尋來的人**幾乎不訂閱**
    # (金像電那支搜尋排第 1、351 觀看、**0 訂閱**;76% 的體檢片訂閱數是 0)。
    # 原因很直白——他為了「金像電」而來,拿到答案就走;片尾告訴他「下一集輪到旺矽」,
    # 那跟他無關,不構成訂閱理由。
    # 對搜尋訪客真正有說服力的是:**他自己手上那幾檔遲早會輪到**。
    # 而這件事是真的:backlog 有全台股名單,已完成數從事實庫算得出來。
    # ⚠️ 誠信:數字**當場從真實檔案算**,絕不寫死(見 memory yt-integrity-methodology-claims)。
    #    算不出來就整句不加,不用約略值糊弄。
    _done, _total = _checkup_progress()
    if _done and _total and "全台股" not in v and "整個台股" not in v:
        tail_bits.append(
            f"這個系列會把全台股{_total}檔一檔一檔體檢完，目前完成{_done}檔，"
            f"你手上那幾檔遲早會輪到，訂閱就不會錯過自己的股票。")
    if tail_bits:
        result["voice_text"] = v + ("" if v.endswith(("。", "！", "？")) else "。") + "".join(tail_bits)
    elif v != str(result.get("voice_text", "") or "").rstrip():
        result["voice_text"] = v
    return result


def _checkup_context(topic):
    """組『個股體檢』系列的本集設定區塊(代號/名稱/產業/集數/下一集候選)，供 TW_STOCK_CHECKUP_RULES
    搭配注入。讀不到任一來源就回空字串，呼叫端不阻斷正常產出(降級成普通台股格式，只是少了系列感)。"""
    if not topic:
        return ""
    code = _checkup_extract_code(str(topic.get("fact_key", "")))
    if not code:
        return ""
    try:
        d = json.loads(STOCK_CHECKUP_FACTS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    by_code = d.get("by_code") or {}
    rec = by_code.get(code)
    if not rec:
        return ""
    name = rec.get("name", code)
    industry = (rec.get("profile") or {}).get("industry", "")
    # 🔴 EP 集數改由「發布時」按已發布集數自動連號(見 daily_publish._next_checkup_ep):產製階段一律
    # 不給、也不可寫死集數編號。舊法用 by_code 序位當集數餵給 LLM,LLM 把它寫進標題→燒進 slug/片頭卡,
    # 但那個號跟著「種題/算事實進度」跑、不跟「發布進度」跑=跳號(觀眾看 EP1 下一支卻 EP40)。這裡改成
    # 明確叫 LLM **不要**寫集數;narration 本來就不唸集數(靠下方「下一集輪到某某」串連),故無縫。
    next_name = _checkup_next_name(code, by_code)
    lines = [f"\n【本集個股體檢設定】", f"- 本集標的：{name}（{code}）"]
    if industry:
        lines.append(f"- 所屬產業(FinMind官方分類，非猜測)：{industry}")
    lines.append("- 集數編號：**不要**在標題或旁白寫死「EP幾／第幾集」——集數於發布時自動連號決定；"
                 "片名與開場只需自然帶出系列名「個股體檢」即可(例：『…｜個股體檢』)。")
    if next_name:
        lines.append(f"- 下一集候選(片尾點名用，勿劇透數字)：{next_name}")
    lines.append("- 誠信提醒：本段設定僅供敘事使用，所有財務數字仍以【本片實證數據】區塊為準，不得自創。")
    return "\n".join(lines)


def _normalize_checkup_title(title: str, code=None, name=None) -> str:
    """個股體檢標題的確定性正規化:①去掉 EP 數字(編號改由發布時掛,見 daily_publish);②把系列名
    「個股體檢」擺到**最前面**(前綴式)。為什麼要前綴:slug 由 slugify(標題前段)產生,系列名在尾端
    (…｜個股體檢)會被截掉→slug 不含「個股體檢」→playlist_engine._match_stock_checkup 認不到→連載
    片不進「個股體檢」播放清單,追劇連播斷。前綴式讓 slug 一定帶系列名,播放清單自動歸類。
    發布時 daily_publish._apply_checkup_ep 會把前綴剝掉、改掛成公開用的後綴式「…｜個股體檢EPn」
    (對齊已公開的 EP1 格式),故公開標題品質不變,但 slug/片頭卡都帶系列名、無編號。
      '鴻海…｜個股體檢EP2'   → '個股體檢鴻海…'
      '個股體檢EP2鴻海2317：' → '個股體檢鴻海2317：'
      '力積電…(無系列名)'    → '個股體檢力積電…'(順帶補上品牌,發布/播放清單都認得)
    只動 4 字『個股體檢』與其 EP 數字,不誤傷『體檢報告』這種一般詞。

    ③標的醒目化(2026-07-19 Carson:『標題要讓人家知道我在講這隻股票、要明顯一點』):給了 code/name
    就把『【名稱 代號】』提到鉤子最前,觀眾一眼看出本集講哪支;鉤子開頭若已是裸代號(00878存股…)先去掉
    避免與前綴重複;冪等(已【】開頭不重加);發布端 _strip_checkup_ep 只剝系列名/EP、不碰【】,故此前綴
    會原樣保留進線上標題『【名稱 代號】…｜個股體檢EPn』。code/name 取自本集 checkup fact 的確定性資料,
    無(舊調用/取不到)則退回原行為,不影響既有片。"""
    t = title or ""
    t = re.sub(r"[\s｜|·:：]*個股體檢\s*EP\s*\.?\s*\d+", "", t)   # 個股體檢EP2 / 個股體檢 EP1
    t = re.sub(r"[\s｜|·:：]*個股體檢", "", t)                     # 裸系列名(待會補到最前面)
    t = re.sub(r"[\s｜|·]*\bEP\s*\.?\s*\d+(?!\d)", "", t)         # 殘留裸 EPn
    hook = t.strip(" ｜|·:：，,、-　\t")
    if code:
        code = str(code).strip()
        nm = str(name).strip() if name else ""
        # 原鉤子開頭是裸代號/裸名稱/名稱代號連寫 → 去掉,避免與【】前綴重複(從長到短比對,先吃連寫)
        for lead in (f"{nm}{code}", f"{code}{nm}", code, nm):
            if lead and hook.startswith(lead):
                hook = hook[len(lead):].lstrip(" ：:，,、-　！!。")
                break
        tag = f"【{nm} {code}】" if (nm and nm != code) else f"【{code}】"
        if code and not hook.startswith("【"):   # 冪等:已加過【】就不重加
            hook = f"{tag}{hook}"
    return f"個股體檢{hook}" if hook else "個股體檢"


def _load_tw_facts():
    """讀真回測事實庫。檔不存在/壞掉 → 回 None，呼叫端靜默跳過。

    🔴 2026-07-13 閉合迴圈(這是誠信問題的最後一哩):
    原本只讀 tw_stock_facts.json——裡面**只有 5 組**事實,產線卻要一天生 14-18 支台股影片。
    事實不夠用 → LLM 只能編(品保實測抓到長片憑空生出「毛利率選股勝率31%」等整套假統計)。
    現在把 tw_facts_engine 算出的 40 組真事實一起餵給寫稿 LLM。

    ⚠️ 沒有這一步的話,新的 40 組事實「只有發布守門(fact_source_guard)看得到、寫稿的 LLM
    看不到」——結果會是:LLM 照樣編 → 守門照樣擋 → 擋得住,但永遠產不出好片。
    餵料端(這裡)與守門端(fact_source_guard.FACT_FILES)必須讀同一組事實庫,才是完整的解。
    """
    merged = None
    for p in (TW_FACTS, TW_FACTS_COMPUTED, STOCK_CHECKUP_FACTS):
        try:
            if not p.exists():
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                continue
            if merged is None:
                merged = dict(d)
                continue
            # results 合併(computed 的 key 不與舊的衝突;真衝突時保留舊的手工事實優先)
            base = dict(merged.get("results") or merged.get("backtests") or {})
            extra = dict(d.get("results") or d.get("backtests") or {})
            for k, v in extra.items():
                base.setdefault(k, v)
            merged["results"] = base
            merged.setdefault("as_of", d.get("as_of", ""))
            merged.setdefault("disclaimer", d.get("disclaimer", ""))
        except Exception:  # noqa: BLE001
            continue

    # 🔴 2026-07-17 事實庫退役第2步:legacy(tw_stock_facts.json)與 computed 是同一組回測的兩份
    #   快照但窗口不同、數字互斥(legacy 大盤長抱 10.2%/20.1年 vs computed 5.7%/29年,結論相反)。
    #   上面的 setdefault 合併擋不住——兩邊 key 命名不同(allin_vs_dca_0050_10y vs
    #   dca_vs_allin__0050__10y),永遠不會撞在一起,於是**兩個互斥的答案同時進了寫稿素材池**,
    #   LLM 挑到哪個全看運氣 → 已發布 Jad4_8skToo 與 ogQukwzFn1s 對同一題給出相反結論。
    #   這裡用 key 對 key 的顯式映射把已被取代的 legacy 剔掉,讓寫稿端結構上拿不到過期那份。
    #   fail-open:computed 缺檔/該組算不出來時 legacy 原樣保留(見 drop_superseded_legacy),
    #   且整段包 try——這支是產線主幹,絕不可因為事實庫小問題讓 06:07 整批產不出來。
    if merged and isinstance(merged.get("results"), dict):
        try:
            import tw_facts_engine
            merged["results"] = tw_facts_engine.drop_superseded_legacy(merged["results"])

            # as_of 誠信修正(同一次退役發現的既有 bug):上面的迴圈用第一份檔(legacy)整個 dict 當底,
            # 所以 merged["as_of"] 一直是 **legacy 的日期**,但注入 prompt 的數字幾乎全是 computed 的。
            # _tw_facts_context() 會把它印成「資料截至 {as_of}」餵給寫稿 LLM → 旁白就會對觀眾
            # 宣告一個**比實際資料還新的日期**(實測:標 2026-07-17,但 computed 資料其實只到 07-13)。
            # legacy 停排程凍結後這個日期會永遠停在 2026-07-17,錯得更久 → 非修不可。
            # 修法:只採計「真的還有事實活下來」的檔的 as_of,取其中**最舊**的一個——寧可低報新鮮度,
            # 也不可宣告一個沒有資料支撐的日期(高報=對觀眾說謊,低報只是保守)。
            survivors = set(merged["results"])
            as_ofs = []
            for _p in (TW_FACTS, TW_FACTS_COMPUTED, STOCK_CHECKUP_FACTS):
                try:
                    if not _p.exists():
                        continue
                    _d = json.loads(_p.read_text(encoding="utf-8"))
                    _keys = set(_d.get("results") or _d.get("backtests") or {})
                    _a = str(_d.get("as_of") or "")
                    if _a and (_keys & survivors):
                        as_ofs.append(_a)
                except Exception:  # noqa: BLE001
                    continue
            if as_ofs:
                merged["as_of"] = min(as_ofs)
        except Exception:  # noqa: BLE001
            pass
    return merged


def _tw_facts_context(facts, topic):
    """把 tw_stock_facts 挑與本題材相關的真數字，拼成一段可注入寫稿 prompt 的實證區塊。
    無 facts / 挑不到相關 → 回空字串，呼叫端不注入（台股題照 TW_STOCK_RULES 產示意數字）。"""
    if not facts or not isinstance(facts, dict):
        return ""
    text = (str(topic.get("title", "")) + " " + str(topic.get("category", "")) +
            " " + str(topic.get("angle", ""))) if topic else ""
    as_of = str(facts.get("as_of", ""))
    lines = []
    cand = facts.get("results") or facts.get("backtests") or {}
    # 2026-07-15「個股體檢」專屬路徑：一集要講完基本面5組+價格面8組共13組事實，且**只能是
    # 本集標的自己的**——走通用 keyword 路徑有兩個坑：①上限6條會把 dict 尾端的基本面事實全部
    # 切掉(價格面8組在前) ②LLM生的category若含「台股」會觸發_pick_all把別檔股票的事實整批混入。
    # 故 checkup 題改用 fact_key 的代號做確定性過濾(checkup_xxx__{code} / __{code}__)，全給不設6條限。
    _ck_code = None
    if topic and str(topic.get("fact_key", "")).startswith("checkup_"):
        _ck_code = _checkup_extract_code(str(topic.get("fact_key", "")))
    if _ck_code and isinstance(cand, dict):
        for key, item in cand.items():
            if not isinstance(item, dict) or not item.get("summary"):
                continue
            if key.endswith(f"__{_ck_code}") or f"__{_ck_code}__" in key:
                desc = str(item.get("desc") or item.get("label") or key)
                lines.append(f"  ·{desc}：{item['summary']}")
        lines = lines[:16]  # 安全上限(一檔最多13組，這只是保險)
    elif isinstance(cand, dict):
        # 各項回測結果都掛在 facts 下（由 tw_stock_data.py 產）；抓不到的項為 None，跳過不用。
        # 🔴 2026-07-17 相關性修復（假憑據的完美形式）：
        # 舊碼 `_pick_all = any(k in text for k in ("台股","大盤","0050","存股","ETF"))` 是一張
        # 「題材泛台股就全給」的毯子,**把每組事實自己帶的 keywords 比對整個短路掉**。實測後果:
        # 題目只要出現「台股/存股/ETF」任一個字 → 無視相關性硬塞 dict 前 6 條(恰好全是 dca_vs_allin)
        # → 「0056 月月配」「00631L 槓桿」「發薪日扣款」通通拿到「0050 一次All in vs 定期定額」的數字。
        # 這是**假憑據的完美形式**:數字是真的、溯得到源、fact_source_guard 查了說「有憑據」,
        # **但它跟那支片毫無關係**,而 prompt 裡還有一塊【本片實證數據】幫它背書。
        # 實測題庫有 28 支正在吃這種假憑據(當沖勝率/填息天數/AI選股/應收帳款周轉率…全拿 0050 定投數字)。
        #
        # 修法**不是新發明一套比對**,而是把既有機制的短路拿掉:50 組事實**全部**自帶 keywords
        # (由算出該組事實的引擎 curate),讓事實自己認領題目。這與 _densify_long 的
        # _split_facts_for_segments(病灶A 修復,見上面那支的 docstring ③)**同一套判準**——
        # 那支早就在逐段分配時用「keywords 命中數排序 + 標的鎖定」,只是 prompt 注入這層一直沒跟上。
        # 另外把 lines[:6] 從「切 dict 插入順序」改成「命中數排序後才截斷」——原本等於「留前 6 條」
        # 而不是「留最相干的 6 條」,即使比對對了也會被插入順序洗掉。
        # topic=None(自由生題路徑,text 為空)沒有題目文字可比對 → 維持原本全給,不動那條路。
        _pick_all = not text.strip()
        scored = []
        for key, item in cand.items():
            if not isinstance(item, dict):
                continue
            desc = str(item.get("desc") or item.get("label") or key)
            summary = item.get("summary")
            if not summary:
                continue
            # 題材過濾：讓每組事實用自己的 keywords 認領題目（命中越多＝越貼題）
            _hits = sum(1 for kw in (item.get("keywords") or [])
                        if isinstance(kw, str) and kw in text)
            if _pick_all or _hits:
                scored.append((_hits, f"  ·{desc}：{summary}"))
        scored.sort(key=lambda x: -x[0])  # 穩定排序:命中數相同者維持原順序
        lines = [s for _, s in scored[:6]]  # 限量：最多 6 條，避免撐爆 token
    if not lines:
        return ""
    body = "\n".join(lines)
    return (f"\n【本片實證數據（台股歷史回測，非未來保證；資料截至 {as_of}）】\n{body}\n"
            "（以上為真實歷史回測數字，旁白引用時務必標明是『歷史回測、不代表未來』；"
            "不得據此喊單/報明牌/喊目標價/保證獲利。抓不到的數字寧可用示意也不編造。）")


# 台股真相實驗室實跑抓到的真 bug(2026-07-13 自驗證時發現)：LLM 拿到「富邦台50(006208)」的正確
# 數字，卻在 title/voice_text 把標的寫成「0050」(0050 是 prompt 裡出現頻率最高的範例代號，模型
# 習慣性滑過去)——數字沒錯但標的名稱錯，等於把 006208 的報酬講成 0050 的，是不精確的事實陳述。
# 只在「這組事實的 desc/claim 根本沒提到 0050」時才判定是誤植(避免誤傷真的比較兩者的比較類事實，
# 如「高股息0056 vs 市值型0050」本來就該同時出現兩個代號)。
_TW_LAB_SYMBOL_DISPLAY = {
    "006208": "006208", "00878": "00878", "0056": "0056", "00631L": "00631L",
    "2330": "台積電", "TWII": "大盤",
}


def _fix_tw_lab_symbol_mislabel(result, fact):
    """事實標的不是 0050、事實本身也沒提到 0050，但產出文字裡出現「0050」→ 判定是滑誤植，
    整片(title/voice_text/description)一律把「0050」換成事實真正的標的顯示名。找不到明確
    標的代號、或事實本身就含 0050(比較類事實)則不動，避免誤傷。"""
    if not fact:
        return result
    fact_text = str(fact.get("desc", "")) + str(fact.get("claim", "")) + str(fact.get("symbol", ""))
    if "0050" in fact_text:
        return result  # 事實本身就講 0050(如比較類)，不誤判
    真代號 = None
    for code in ("006208", "00878", "0056", "00631L", "2330", "TWII"):
        if code in fact_text:
            真代號 = code
            break
    if not 真代號:
        return result
    display = _TW_LAB_SYMBOL_DISPLAY.get(真代號, 真代號)
    for field in ("title", "voice_text", "description"):
        v = result.get(field)
        if isinstance(v, str) and "0050" in v:
            result[field] = v.replace("0050", display)
    return result


def _fix_tw_lab_title_fabrication(result, fact):
    """台股真相實驗室標題誠信安全網(2026-07-19 訂閱轉換·長片變體落地時實測抓到):
    LLM 在標題湊一個沒算過的差距整數是**已知累犯**——dca_vs_allin 這組連兩次生成都吐「少賺430%」,
    但真實差距是 321.7 分點(697.4% vs 375.7%);純 prompt 提示擋不住(同 tw_lab 診斷『軟性提示擋不住
    LLM,已知累犯要硬擋』)。故照本檔既有『確定性後處理』模式(對齊 _fix_tw_lab_symbol_mislabel/
    _checkup_finalize)硬擋:標題若含發布守門 fact_source_guard 查無憑據的數字,就換成由本集主軸事實
    desc 生成的確定性安全標題(不含任何編造差值,仍含標的/主題可搜尋)。
    fail-open:任何例外或無 desc 素材一律保留原標題——下游 fact_source_guard 仍會 fail-closed 擋下,
    絕不會因為這道沒生效就漏發假數字(安全網,不是唯一防線)。短片/長片同樣適用:只在標題真的含編造
    數字時才觸發,乾淨標題(常態)完全不動,故不影響短片既有行為。"""
    try:
        import fact_source_guard as _fsg
        title = str(result.get("title", ""))
        if not title or not _fsg.unsourced_claims(title):
            return result  # 標題乾淨(常態)→ 不動
        desc = str((fact or {}).get("desc") or "").strip()
        if not desc:
            return result  # 無安全標題素材 → 保留原標題交給發布守門 fail-closed
        safe = f"{desc}？回測揭真相"  # 與 tw_lab_engine.build_topic 同格式,由真事實生成、零編造
        result["_title_fabrication_fixed"] = {"old": title, "new": safe}
        result["title"] = safe
    except Exception:  # noqa: BLE001
        pass
    return result


def _fix_tw_lab_desc_fabrication(result, fact):
    """台股真相實驗室『描述』誠信安全網(2026-07-19 #26，補 _fix_tw_lab_title_fabrication 的漏)：
    標題安全網只清洗 title，但 LLM 在 description 同樣編造差值數字——dca_vs_allin 那支標題被硬擋
    後、描述又編了一個「竟差 430% 報酬」(真值 321.7 分點)，發布守門 fact_source_guard 對描述一樣
    fail-closed，整支被擋下發不出去。描述是多句跨行 SEO 文字，不能像標題那樣逐句刪：句級清洗會誤刪
    「兩者差 X 個百分點」這種**跨句比較**的真數字句(單句看不到 697.4/375.7 兩個 operand→誤判無憑據)。
    故照標題同款『確定性整段重生』：描述一旦含查無憑據數字，就換成由真事實 desc + 已清洗 title 生成的
    安全描述(關鍵字鉤子+不含任何編造差值+訂閱 CTA+風險聲明，全部確定性、零 LLM)。
    ★ 自檢：安全版本身再過一次 unsourced_claims，連安全版都命中(鉤子素材帶了數字)就 fail-open 保留原
    描述交給發布守門擋——絕不因這道而漏放假數字。乾淨描述(數字都有憑據，常態)零命中→byte-identical
    完全不動，不影響短片/既有行為。"""
    try:
        import fact_source_guard as _fsg
        desc = str(result.get("description", ""))
        if not desc or not _fsg.unsourced_claims(desc):
            return result  # 描述乾淨(常態)→ byte-identical 不動
        topic_desc = str((fact or {}).get("desc") or "").strip()
        title = str(result.get("title", "")).strip()  # 此時 title 已過 _fix_title_fabrication，乾淨
        hook = topic_desc or (title.split("｜")[0].split("？")[0] if title else "") or "本集用真實回測拆解關鍵差異"
        safe = (
            f"{hook}？臺股真相實驗室用真實回測資料給它判決，判決由數字算出、不由立場定。\n\n"
            "看完你將知道：兩種策略的實際績效比較、風險指標的差異、以及該如何依自身風險承受度做選擇。\n\n"
            "訂閱《臺股真相實驗室》，下一集繼續用真回測，拆解一條你以為天經地義的投資常識。\n\n"
            "⚠️ 風險聲明：本影片為資訊與觀念分享，不構成任何投資建議。過去績效不代表未來表現，"
            "回測不含手續費與滑價，投資請自行承擔決策後果。"
        )
        if _fsg.unsourced_claims(safe):
            return result  # 連安全版都命中(鉤子素材帶數字)→ fail-open 保留原描述交給發布守門
        result["_desc_fabrication_fixed"] = {"old": desc[:120]}
        result["description"] = safe
    except Exception:  # noqa: BLE001
        pass
    return result


# ── 病灶A根因(2026-07-13 長片內容審查實測)：_tw_facts_context 只挑最多 6 條相關事實組成
# 一份「文字區塊」，而舊版 _densify_long 把這同一份文字**原封不動塞進每一段 deep-segment prompt**——
# 4-5 段全部拿到一模一樣的 2-6 組數字，LLM 除了換比喻/換人物重講同一組數字，沒有別的素材可用，
# 這正是「813%/24.7%/-33.8% vs 380%/16.9%/-22.6% 用『反直覺的是』重複10次以上」的根因。
# 修法：_densify_long 逐段各自分配「本段專屬事實」，同一個 fact key 全片最多被引用 2 次
# (body 段落各自最多引用 1 次不重複 + 結尾小結综合引用 1 次＝鋪陳+收尾)。
# ── 病灶A主題鎖定：標的代號白名單。實跑抓到的真實 bug——標題「0050定期定額 vs 美股ETF」，
# 但事實 hidiv_0056_vs_0050(高股息0056 vs 0050)因為 keywords 裡有「0050」也被判為同主題，
# 逐段分配時被派給後段，LLM 就老實地整段寫 0056 高股息 → 影片後 40% 悄悄變成另一支片的主題
# (正是這次要修的症狀本身)。修法：標題若明確點名了標的代號，事實裡若出現「標題沒點名的其他
# 標的」，一律降級成 extension(延伸比較，全片最多 1 段且篇幅 ≤15%)，不得當本片主線事實。
_FACT_SYMBOLS = ("0050", "0056", "00878", "00929", "006208", "00631L", "2330", "TWII", "台積電")


def _symbols_in(text):
    return {s for s in _FACT_SYMBOLS if s in (text or "")}


def _relevant_facts_list(facts, topic):
    """把 tw facts 挑成與本題相關(primary)/不相關(extension)兩份清單，每項含 key/desc/summary/keywords。
    供 _densify_long 逐段分配專屬事實、做主題鎖定用。

    ★ 病灶A主題鎖定(兩道)：
    ①只用 topic 的 title+angle 比對，不看 category——category="台股" 太粗，會讓 45 組事實整包
      都算「同主題」(等於沒鎖題)。
    ②標的鎖定(實跑抓到的真 bug)：標題若點名了具體標的(如 0050)，凡是牽涉到標題沒點名的其他
      標的(0056/00878/2330…)的事實，一律降級為 extension——否則逐段分配會把 0056 高股息的
      事實派給某一段，那段就整段變成另一支片的主題(影片後段悄悄跑題的根因)。
    ③primary 依關鍵字命中數排序(命中越多＝越貼題)，讓最貼題的事實優先分配給前面的主力深段。
    標題完全比對不到任何關鍵字時(泛用題、沒有明確比較對象)才退回「全部當 primary」——那種情況
    本來就沒有主題可鎖，不算鬆綁。"""
    primary, extension = [], []
    if not facts or not isinstance(facts, dict):
        return primary, extension
    text = (str(topic.get("title", "")) + " " + str(topic.get("angle", ""))) if topic else ""
    cand = facts.get("results") or facts.get("backtests") or {}
    if not isinstance(cand, dict):
        return primary, extension
    entries = []
    for key, item in cand.items():
        if not isinstance(item, dict):
            continue
        summary = item.get("summary")
        if not summary:
            continue
        entries.append({"key": str(key), "desc": str(item.get("desc") or item.get("label") or key),
                        "summary": str(summary), "keywords": item.get("keywords") or []})
    if not entries or not text.strip():
        return entries, []
    title_syms = _symbols_in(text)
    scored = []
    for e in entries:
        kws = [kw for kw in e["keywords"] if isinstance(kw, str)]
        hits = sum(1 for kw in kws if kw in text)
        # 事實本身牽涉到哪些標的(看 key+desc+keywords，涵蓋 hidiv_0056_vs_0050 這種 key 帶標的的情況)
        fact_syms = _symbols_in(e["key"] + " " + e["desc"] + " " + " ".join(kws))
        off_topic_syms = bool(title_syms) and bool(fact_syms - title_syms)
        if hits and not off_topic_syms:
            scored.append((hits, e))
        else:
            extension.append(e)
    if not scored:
        return entries, []  # 沒有任何貼題事實(標題無可比對關鍵字)→ 退回寬鬆行為，不硬卡住產線
    scored.sort(key=lambda x: -x[0])  # 命中關鍵字越多＝越貼題，優先分配給主力深段
    primary = [e for _, e in scored]
    return primary, extension


# ── 病灶A：全片重複轉場詞硬上限(2026-07-13)——「反直覺的是」這類轉場句只要還在同一份稿子裡
# 被啟用超過上限次數，就是「同一組數字換比喻/換人物重講」的鐵證。軟性 prompt 提示擋不住 LLM
# 復發(同 A1c 「考古題」教訓)，故用確定性文字後處理硬上限，第 cap+1 次起直接替換掉，不再靠運氣。
_TRANSITION_ALT_POOL = ("更耐人尋味的是，", "數字攤開來看，", "但真正該注意的是，",
                        "拆開來看才發現，", "值得玩味的是，", "換個角度看，")


def _cap_repeated_phrase(text, phrase, cap, alt_pool=_TRANSITION_ALT_POOL):
    """全片同一個轉場詞出現次數硬性上限：超過 cap 次，第 cap+1 次起輪替換成替代詞，
    確定性文字處理、不靠 LLM 自律(對齊 A1c『已知累犯硬擋』的設計精神)。

    ★ 連帶吃掉前面的程度副詞(更/還/也/但/而)：實跑抓到的 bug——原文是「更反直覺的是」，
    只換掉「反直覺的是」會變成「更」+「更耐人尋味的是」＝「更更耐人尋味的是」的疊字結巴，
    TTS 會照念出來。故用 regex 把前綴副詞一起納入比對範圍，替換時整段換掉、不留殘字。"""
    if not text or not phrase or phrase not in text:
        return text
    pat = re.compile(r"[更還也但而]?" + re.escape(phrase))
    matches = list(pat.finditer(text))
    if len(matches) <= cap:
        return text
    out, last, n = [], 0, 0
    for m in matches:
        n += 1
        out.append(text[last:m.start()])
        out.append(m.group(0) if n <= cap else alt_pool[(n - cap - 1) % len(alt_pool)])
        last = m.end()
    out.append(text[last:])
    return "".join(out)


# 🔴 2026-07-13:題材配重對「自由發揮」路徑完全無效的破口。
# call_claude 是 `topic = topic_override or pull_topic(kind)`,pull_topic 抽不到就回 None,
# 註解明寫「題庫空了才自由發揮」→ LLM 隨便生。而題庫現存 430 個未用題目裡**台股不到 3%**,
# 於是配額要台股 → 題庫沒台股題 → 落回自由發揮 → LLM 生出加密網格題。
# 實測:--long 1 的配額是 {tw_stock:1, crypto:0},實際產出 `L_加密網格滑價吃掉50%利潤`
# (而且那支還編造「實測發現47%訂單失效」被誠信守門擋下 → 整支長片白產)。
# 等於今天做的台股配重(78%)對長片——YPP 唯一路徑——**完全沒有作用**。
# 修:題庫抽不到時,把「本支必須是哪個題材」**直接下令給 LLM**,不讓它自由發揮。
_BUCKET_DIRECTIVE = {
    "tw_stock": (
        "\n【本支題材硬性指定:台股】必須寫台股題材,而且**只能寫下面這幾類我們真的有回測數據的**:"
        "定期定額vs單筆All-in、扣款日效應(月初/月中/月底)、停利vs續抱、高股息(0056/00878)vs"
        "市值型(0050/006208)、槓桿ETF長抱(00631L)、擇時vs長抱、錯過最佳N天、崩盤加碼vs恐慌賣。"
        "標的限:0050/006208/0056/00878/00631L/2330台積電/加權大盤。"
        "\n⚠️ 不得寫加密貨幣(比特幣/以太幣/網格/派網/爆倉)或 AI 工具題——實測數據顯示台股題觀看是"
        "幣圈題的數十倍,這是產線配重的硬性要求。"
        "\n🔴【無資料主題·絕對禁止】以下主題我們**沒有任何回測引擎**,寫了就只能編數字(實測已抓到"
        "『毛利率選股勝率31%』『現金流量表連續衰退87%機率爆雷』這類全編的假統計,一律被誠信守門"
        "擋下、整支片白產):**毛利率/營益率選股勝率、財報公布前後股價反應機率、現金流量表爆雷機率、"
        "本益比/淨值比估值選股、ROE/營收成長選股、當沖真實勝率統計、融資融券斷頭統計、"
        "個股填息機率天數統計**——以及任何『某某指標選股勝率 X%』的宣稱。碰到這些主題請直接換題。"
        "\n數字一律只用 tw_stock_facts / tw_facts_computed 的真實回測,查不到就用示意語氣,絕不編造。"),
    "crypto": (
        "\n【本支題材硬性指定:加密貨幣】必須寫加密貨幣題材(比特幣/以太幣/網格/派網/風控)。"
        "數字只能用 backtest_cards 的真實回測,查不到就不給具體數字(用示意/假設語氣),絕不編造。"),
    "ai_tools": (
        "\n【本支題材硬性指定:AI 工具】必須寫 AI×交易/AI 工具題材(Claude Code/ChatGPT/AI 省錢/"
        "AI 寫策略的真實坑)。不得憑空生成績效統計數字。"),
}


def _wanted_bucket(kind):
    """本批配額還沒吃滿的桶(台股優先)。回 None = 本批沒設配額 or 都吃滿了。"""
    bplan = _BUCKET_PLAN.get(kind) or {}
    if not bplan:
        return None
    taken = (_BUCKET_STATE.get(kind) or {}).get("taken", {}) or {}
    for b in ("tw_stock", "ai_tools", "crypto"):   # 台股優先吃配額
        if int(bplan.get(b, 0)) > int(taken.get(b, 0)):
            return b
    return None


def _record_bucket_taken(kind, title):
    """自由發揮路徑產出後,把實際題材記進配額(否則配額只認題庫抽的,自由發揮的不算,配重會失準)。"""
    try:
        b = sc.classify_topic_bucket(title or "")
        if b in ("tw_stock", "crypto", "ai_tools"):
            st = _BUCKET_STATE.setdefault(kind, {"taken": {}, "cw": {}})
            st.setdefault("taken", {})[b] = st.get("taken", {}).get(b, 0) + 1
    except Exception:  # noqa: BLE001
        pass


def call_claude(kind, avoid, topic_override=None):
    orders = load_orders()
    # 時事優先：有指定題目（金融時事）就用它，否則從題庫抽；題庫空了才「照配額指定題材」自由發揮
    topic = topic_override or pull_topic(kind)
    # 2026-08-17:把來源長片 slug 一路帶到 make_one(它的作用域裡沒有 topic 變數)。
    # 用途見 make_one 寫 {slug}.parent.txt 的說明:切片片的數字要對照它自己的來源長片。
    _parent_slug = str((topic or {}).get("parent") or "") if isinstance(topic, dict) else ""
    assign = ""
    if not topic and not topic_override:
        _wb = _wanted_bucket(kind)
        if _wb:
            assign = _BUCKET_DIRECTIVE[_wb]   # 題庫沒貨→不放任自由發揮,硬性指定題材
    if topic and topic_override:
        if str(topic.get("fact_key", "")).startswith("checkup_"):
            # 個股體檢重生路徑(make_one 鎖同一題重生時走 topic_override 傳回來)：用題庫派發框架,
            # 不能套下面的「金融時事」框架(那會誤導 LLM 以為是新聞題,語氣跑掉)。
            assign = (f"\n【本支指定題目（個股體檢系列，務必照此主題寫，標題可潤飾更有點擊慾）】："
                      f"{topic.get('title','')}　切入點：{topic.get('angle','')}")
        else:
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
    # 🔴 2026-08-04 再縮:playbook 3200→1600、training 1200→400。
    # 理由是**產能不是品味**:實測長片提示 16,461 字 ≈ 10,300 tokens,加上 max_tokens
    # 後合計約 13,500,而 Groq 免費層單一請求必須塞進「每分鐘 token 桶」
    # (llama-3.3-70b 是 12,000)→ 請求**直接被拒**(Request too large),不是慢,是沒送出去。
    # 長片產能長期 1~2 支/日、08-03 整天 0 支,根因就在這裡。
    # 砍的是「參考資料」(競品心法/進修洞察)不是「內容規則與事實」——後者是誠信與品質的
    # 承重牆,寧可少參考也不動它。縮後提示約 14,000 字 ≈ 8,800 tokens,配 max_tokens 2800
    # 合計約 11,600,留約 3% 餘裕。
    _pbmax = int(os.environ.get("LLM_PB_CHARS", "1600"))
    playbook = (load_playbook() or "")[:_pbmax]   # 每支腳本即時讀最新競品 playbook(限長)
    training = (load_training() or "")[:400]       # 每週進修洞察(限長)
    avoid_block = "\n".join(f"  · {t}" for t in (avoid or [])[:30]) if avoid else "  （無）"
    hook_rules = HOOK_RULES if kind == "short" else LONG_RULES
    # 🔬 A/B 實驗:開場結構(2026-08-19 建)。詳見 _ab_arm() 的說明。
    if kind != "short":
        _arm, _extra = _ab_arm(str((topic or {}).get("title") or topic_override or ""))
        hook_rules = hook_rules + _extra
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
    # 台股真相實驗室 franchise(2026-07-13 訂閱轉換診斷落地)：題目由 tw_lab_engine 派發(category
    # 命中系列名，topic_bank 種題或 --tw-lab CLI 都會標這個 category)→ 追加系列鐵律 + 集數前情提要 +
    # 本集唯一指定的真回測數字(比一般 is_tw_stock 關鍵字比對更精準：這裡是引擎明確指定的那一組，
    # 不會混題)。刻意不要求 `not topic_override`(EP 系列才有這限制)，讓 --tw-lab/topic_override
    # 兩條路徑都能觸發，方便自驗證與未來手動補產。
    is_tw_lab = bool(topic) and str(topic.get("category", "")) == "台股真相實驗室"
    _tw_lab_ep_no = None
    _tw_lab_actual_key = ""  # 供 result["_tw_lab_key"] 用(不能只信 topic.get，備援路徑會換一組)
    _tw_lab_fact_used = {}  # 供產出後做「標的誤植」安全網比對用(見 _fix_tw_lab_symbol_mislabel)
    if is_tw_lab:
        # 2026-07-19 訂閱轉換診斷:franchise 正片改走長片(見 tw_lab_engine.FRANCHISE_FORMAT)。
        # 長片用多事實 bundle 撐深段(TW_LAB_LONG_RULES + 下面 fact_data_block(long_mode=True) 只當脊椎、
        # 其餘深段吃 is_tw_stock 那條已注入的 _tw_facts_context 多組真回測);短片維持單一事實鐵律,
        # 走 TW_LAB_RULES,byte-identical 零變化。
        _tw_lab_long = (kind == "long")
        hook_rules = hook_rules + (TW_LAB_LONG_RULES if _tw_lab_long else TW_LAB_RULES)
        try:
            import tw_lab_engine
            _tlst = tw_lab_engine.load_state()
            _facts_all, _tl_as_of = tw_lab_engine._load_facts()
            _tl_key = topic.get("tw_lab_key") or ""
            _tl_fact = _facts_all.get(_tl_key) or {}
            if not _tl_fact:
                # 題目來自題庫但沒帶 tw_lab_key(舊題/透傳漏了)→備援：直接向引擎要下一組，
                # 不讓整個 franchise 因為單一欄位缺失而退化成沒有真數據的空片。
                _tl_key, _tl_fact, _, _ = tw_lab_engine.pick_next(_tlst)
                _tl_fact = _tl_fact or {}
            _tl_next_key = topic.get("tw_lab_next_key") or ""
            _tl_next_fact = _facts_all.get(_tl_next_key) or {}
            if not _tl_next_fact and _tl_key:
                _tl_next_key, _tl_next_fact = tw_lab_engine.next_after(_tl_key, _tlst)
                _tl_next_fact = _tl_next_fact or {}
            assign += tw_lab_engine.context_block(_tlst, _tl_key, _tl_fact, _tl_next_key, _tl_next_fact)
            assign += tw_lab_engine.fact_data_block(_tl_key, _tl_fact, _tl_as_of, long_mode=_tw_lab_long)
            _tw_lab_ep_no = int(_tlst.get("current_ep", 0) or 0) + 1
            _tw_lab_actual_key = _tl_key
            _tw_lab_fact_used = _tl_fact
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
    # 2026-07-15「個股體檢」：fact_key 帶 checkup_ 前綴的題天生就是台股個股題，強制走台股路徑——
    # 不能只靠標題關鍵字判斷(實測「南亞科…DRAM股的真相」一個 _twkw 都沒中,會漏套模板+被誤掛
    # NO_FACTS_INTEGRITY_RULES「本題無真實數據」——它明明有13組真事實)。
    is_checkup = bool(topic) and str(topic.get("fact_key", "")).startswith("checkup_")
    is_tw_stock = is_checkup or (topic is not None and (
        any(k in str(topic.get("category", "")) for k in _twkw)
        or any(k in str(topic.get("title", "")) for k in _twkw)))
    facts_ctx = ""  # A4:長片分段深寫要把真數據帶進每一段,故把 tw facts 區塊獨立留一份
    _facts_raw = None  # 病灶A(2026-07-13):原始 facts dict 也留一份,供 _densify_long 逐段分配專屬事實
    _checkup_next = ""  # 供產出後確定性補強片尾(見 _checkup_finalize)
    if is_tw_stock:
        hook_rules = hook_rules + TW_STOCK_RULES
        # 真數據引擎：讀 STUDIO/tw_stock_facts.json，挑與題材相關的真回測數字注入寫稿 prompt。
        # 檔不存在/讀不到/無關聯數字 → 靜默跳過，改由下面的「零事實 → 落誠信守門」接手（不崩）。
        _tw_inject = ""  # 先綁定:原本只在 try 內賦值,_load_tw_facts 一拋例外就 NameError
        try:
            _facts = _load_tw_facts()
            _facts_raw = _facts
            _tw_inject = _tw_facts_context(_facts, topic)
            if _tw_inject:
                assign += _tw_inject
                facts_ctx = _tw_inject
        except Exception:  # noqa: BLE001
            pass
        # 2026-07-15「個股體檢」系列：疊加10分鐘長片結構模板 + 本集設定(代號/產業/集數/下一集點名)。
        # fact_key 前綴 checkup_ 是本系列專屬命名(見 stock_checkup_facts.py/stock_fundamentals.py)，
        # 不會誤傷其他台股題(那些 fact_key 是 tw_facts_engine/tw_lab_engine 的其他前綴)。
        if is_checkup:
            hook_rules = hook_rules + TW_STOCK_CHECKUP_RULES
            try:
                _ck_inject = _checkup_context(topic)
                if _ck_inject:
                    assign += _ck_inject
                _checkup_next = _checkup_next_name(
                    _checkup_extract_code(str(topic.get("fact_key", ""))) or "")
            except Exception:  # noqa: BLE001
                pass
        # 🔴 2026-07-17 破口修復:走台股路徑但**實際一條事實都沒注入**時,必須落到誠信守門。
        # 根因(2026-07-17 實跑抓到):舊碼是 `if is_tw_stock:` / `else:` 二分——只要 title/category
        # 含 _twkw 任一關鍵字就走台股分支,拿到 TW_STOCK_RULES「開場前3秒直接砸台股具體神話數字」
        # 的命令;但事實庫**根本沒有當沖資料**(四個事實庫全查無當沖/勝率證據)→ _tw_facts_context
        # 回空字串 → 什麼都沒注入,而 else 分支的 NO_FACTS_INTEGRITY_RULES **永遠輪不到**
        # → 等於「命令 LLM 砸具體數字 + 不給它任何數字」= **產線在教 LLM 編數字**。
        # 實測:題庫 8 支未用當沖長片題全中此路徑,標題自帶「勝率90%/1000次回測/10萬筆交易數據」
        # 等捏造統計。而 _BUCKET_DIRECTIVE 早把「當沖真實勝率統計」列為🔴絕對禁止——但那只擋
        # 「題庫抽不到→自由生題」那條路,題庫抽得到的這條路沒擋 → **同一件事一條路禁、一條路命令**。
        # 這道就是把那個矛盾補平:判準用「**實際有沒有拿到事實**」(而非關鍵字黑名單),
        # 所以個股體檢那種真的有 FinMind 事實的題不會被誤殺(它們 _tw_inject 非空,不進這裡)。
        if not _tw_inject:
            hook_rules = hook_rules + NO_FACTS_INTEGRITY_RULES + TW_NO_FACTS_OVERRIDE
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
    # 標籤格式化(2026-07-24 治「自動產製長片被硬塞 #Shorts 首標→搜尋 reach 自殺」):短片必掛 #Shorts
    # (它就是 Short);長片嚴禁掛——長片靠搜尋流量,#Shorts 會被 YouTube 當短片處理、扼殺搜尋 reach。
    if kind == "long":
        _ht_example = '["#台股","#定期定額","#..."]'
        _ht_rule = ("hashtags 規則：給 4-6 個「精準且利基相關」的標籤（**長片嚴禁 #Shorts**——長片靠搜尋流量，"
                    "掛 #Shorts 會被 YouTube 當短片處理、扼殺搜尋 reach；第一個放最核心的可搜尋詞，如標的代號／"
                    "主題詞），不要硬塞 20 個——精準勝過熱門，乾淨又利於演算法分類。")
    else:
        _ht_example = '["#Shorts","#量化交易","#..."]'
        _ht_rule = ("hashtags 規則：給 4-6 個「精準且利基相關」的標籤(第一個必為 #Shorts)，不要硬塞 20 個——"
                    "精準勝過熱門，乾淨又利於演算法分類。")
    prompt = f"""你是量化阿森頻道的專業腳本寫手。{GUARD}
{QUANT_STANDARD}
{playbook}{training}
請產生{spec}{assign}{bias}
{TITLE_FORMULA}
【SEO 長尾(能自然融入就融入,別硬塞犧牲鉤子)】標題或說明前段盡量含 1 個觀眾真的會搜的詞,例如:{"、".join(SEO_TERMS[:12])}。
【★雙軌標題·另外產出 seo_suffix(2026-07 常青搜尋流量修復)】title 欄位維持現有規則(鉤子優先,不要因為這條而改寫 title)。
另外再產出一個獨立的 seo_suffix 欄位:8-14 字的「搜尋詞組」,是觀眾真的會在 YouTube 搜尋框打的字(不是鉤子句),
必須含至少一個具體標的代號(0050/0056/00878/00929/006208/2330…)或明確主題詞(定期定額/存股/回測/ETF比較/網格機器人怎麼設…)
＋一個動作詞(比較/回測/10年回測/怎麼選/怎麼設定/教學)，例如:「0056 vs 00919 十年比較」「0050 定期定額 10年回測」「網格機器人 怎麼設定」。
★誠信硬規:seo_suffix 提到的標的/主題**必須是本支影片 voice_text 裡真的有講到的**,絕不能為了塞關鍵字提到片中沒出現的標的;
沒有適合的搜尋詞就把 seo_suffix 留空字串,不要硬湊。seo_suffix 不含 %、不含「倍/萬/億」等績效數字用語(那是 title/voice_text 的事,不是搜尋詞)。
{hook_rules}
【配音友善·務必遵守（影響聽感與留存）】voice_text 要口語、**短句為主（每句約 15-25 字就用句號斷開）**；
少用括號/破折號/冒號/刪節號；數字盡量寫成口語念法（如「百分之八」別寫「8%」、「一萬元」別寫「$10000」、「零點五」別寫「0.5」）；
一句話別塞太多數據（最多一個數字），讓人聽得清、TTS 念得順、斷點自然。
【高點擊標題框架，擇一套用且自然】：⓪小白避雷型（新增選項，適合就用）：「新手別碰X，我回測幫你試過了」「我回測『丟10萬給X』，結果…」「X 是不是坑/詐騙？我用回測拆給你看」「新手把錢丟給機器人會不會被割？」——恐懼+我先幫你試（是回測、不假稱真錢）。①精確數字＋懸念②「如何…」具體承諾（含時間/數字）③「你一直做錯」揭錯④「真相揭露」⑤反直覺結論。能放具體數字就放、越精確越好；標題要有好奇缺口但不誇大、不保證收益。★長尾可搜尋（繞過低權重的搜尋流量入口）：盡量用觀眾真的會搜的關鍵字並放在標題開頭（如「派網網格 怎麼設」「Pionex vs 幣安」「定投買在高點會虧嗎」）——長片尤其要走這種可搜尋寫法；理財誇大詞（躺賺／穩賺／一天賺X）一律不用，會被限流。
請避免重複以下已有題目（換切角可以，換字重說同主題不行）：
{avoid_block}
⚠️【語言鐵律】全程一律「繁體中文（台灣用字）」，**嚴禁任何簡體字**（例：要寫「網格、帳戶、獲利、為什麼、機器」，不可寫「网格、账户、获利、为什么、机器」）。標題、旁白、說明、小標全部繁體。
只輸出 JSON（不要任何其他文字、不要 markdown 圍欄），格式：
{{"title":"有點擊慾的標題","seo_suffix":"8-14字搜尋詞組(含標的代號或主題詞+動作詞,只能用片中真的講到的標的/主題;沒有合適的就留空字串)","voice_text":"完整旁白逐字稿(口語、適合中文TTS)","segments":[{{"heading":"段落小標","broll":["english keyword","english keyword"]}}],"description":"YouTube 說明欄：前 3 行＝①核心可搜尋關鍵字短語②一句鉤子摘要③價值承諾(看完能拿走什麼)；接 1-2 句補充、自然含關鍵字與同義詞(別硬塞)；**再加一行變現漏斗 CTA：『📩 私訊 Telegram @CarsonQuant_message_bot 打「回測」，免費領新手回測避雷檢核表』**(Telegram bot 會自動把檢核表送到觀眾手上+養名單再自然導向 Pionex；比「留言領」更能真的交付資源、也把觀眾沉澱成可觸及的名單)；結尾含風險聲明『投資有風險，不構成投資建議』","hashtags":{_ht_example}}}
{_ht_rule}"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    # 長片要吐 2600+ 中文字的 voice_text(中文 token 貴),3500 會被截斷成短長片(A4 根因之一)。
    # 2026-07-13:6500 又不夠了——實測長片產製吐 "[err long 第2次] LLM 回應非 JSON" 直接 0 支。
    # 根因同一個:輸出撞 token 上限被截斷 → JSON 少了結尾的 } → 下面的 re.search 抓不到 → 整支作廢。
    # 資訊密度規則上線後內容更長更容易撞。拉到 8000(DeepSeek 輸出上限附近)並加截斷修復。
    # 🔴 2026-08-04 長片 8000 → 3200。這個數字**不是品質旋鈕,是產能開關**。
    # Groq 免費層限制是「每分鐘 token 桶」,而且**單一請求的 (輸入 + max_tokens) 也必須
    # 塞得進那個桶**:llama-3.3-70b 是 12,000/分。長片提示約 6,000 tokens,
    # 配 max_tokens=8000 → 約 14,000 > 12,000 → 請求**直接被拒**(Request too large),
    # 不是慢、是根本沒送出去。長片產能長期只有 1~2 支/日、08-03 整天 0 支,就是這樣來的。
    #
    # 原本要 8000 是為了配推理型模型 gpt-oss-120b(它先燒掉一大半 token 在我們丟掉的
    # reasoning 上)。改用 llama 後不需要那個緩衝:實測 llama 每 token 產出 1.18 個中文字,
    # 要 2600 字約需 2200 tokens,3200 已有 45% 餘裕。
    # ⚠️ 要往上調之前先算:輸入 + max_tokens 必須 < 該模型的每分鐘桶,否則整批產不出來。
    # 2026-08-04 晚:2800 → 7000(長片)。前面把它砍到 2800 的唯一理由是「要塞進 Groq
    # 免費層的 12,000 每分鐘桶」;現在長片這種大請求走 OpenRouter(Carson 已儲值),
    # 那個桶的限制不存在了,而 2800 反而變成新的瓶頸——實測各模型在 2800 上限下
    # 最多只寫到 2,088 中文字,**卡在長度 gate 的 2200 門檻**,於是無限「重生或補寫」,
    # 20 分鐘 5 次嘗試 0 產出且不報錯。
    # ⚠️ 要再調小之前先確認長片走哪個供應商:若哪天改回免費層,這裡必須連同提示一起重新算。
    _maxtok = 7000 if kind == "long" else 2000
    txt = llm.complete(prompt, _maxtok, json_mode=True)  # 強制合格 JSON
    obj = _loads_lenient(txt)
    if obj is None:
        raise ValueError("LLM 回應非 JSON")
    result = _to_traditional(obj)  # 安全網：簡轉繁(台灣用字),防 DeepSeek 偶爾出簡體
    if not topic and not topic_override:
        # 自由發揮路徑:把實際產出的題材記進配額(否則配額只認題庫抽的,自由發揮的不計,配重失準)
        _record_bucket_taken(kind, result.get("title", ""))
    result["_is_ep"] = bool(is_ep)  # 供 make_one 判斷是否為 EP 正片 → 產出成功後遞增 EP 引擎
    result["_is_tw_lab"] = bool(is_tw_lab)  # 供 make_one 判斷是否為台股真相實驗室正片 → 產出成功後遞增系列引擎
    if is_tw_lab:
        result["_tw_lab_key"] = _tw_lab_actual_key or (topic.get("tw_lab_key") or "")
        result["_tw_lab_ep"] = _tw_lab_ep_no
        result = _fix_tw_lab_symbol_mislabel(result, _tw_lab_fact_used)
        result = _fix_tw_lab_title_fabrication(result, _tw_lab_fact_used)  # 標題編造數字→確定性換安全標題
        result = _fix_tw_lab_desc_fabrication(result, _tw_lab_fact_used)   # #26 描述編造數字→確定性換安全描述
    result["_is_tw_stock"] = bool(is_tw_stock)  # A2:供 make_one 判斷本片是否有 tw_stock_facts 真數據佐證
    if is_checkup:
        result["_is_checkup"] = True
        result["_ck_topic"] = topic  # 供 make_one 鎖題重生:所有品質 gate 的重生都重寫「同一集」,
        #                              絕不再 pull_topic 抽下一題(EP2-EP4被連環燒掉的事故根因)
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
        result = _densify_long(result, facts_ctx, bool(is_tw_stock), facts=_facts_raw, topic=topic)
    # 個股體檢：確定性補強片尾(缺留言鉤/下集點名/訂閱鉤才補,LLM寫好的不重複;見 _checkup_finalize 檔頭)。
    # 🔴 必須放在 _densify_long **之後**——那支會整篇重建 voice_text,放前面補的片尾會被洗掉
    # (2026-07-15 實跑EP5抓到:補強放 densify 前,產出片尾又變自由發揮的假下集預告)。
    if is_checkup:
        result = _checkup_finalize(result, _checkup_next)
    # A/B 分組跟著結果帶出去,make_one 寫成 sidecar。
    # ⚠️ 必須放在**這裡**(call_claude 的結尾),不能放進 _densify_long——
    # 那支的簽章是 (d, facts_ctx, is_tw, facts, topic),**沒有 kind 也沒有 topic_override**,
    # 在裡面寫會 NameError 被 try 吞掉 → sidecar 永遠不寫、而且完全不報錯。
    # 這正是上面 _parent_slug 註解記過的同一個坑,我第一版又踩了一次:
    # 分組記錄照常累積(組 prompt 時就呼叫過),但對不回任何一支影片,實驗等於白做。
    # seed 也必須跟組 prompt 那次**完全一致**,否則同一支片會分到不同組。
    try:
        if kind != "short":
            result["_ab_arm"] = _ab_arm(
                str((topic or {}).get("title") or topic_override or ""))[0]
    except Exception:  # noqa: BLE001
        pass
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
    lines += ["## 🏁 結尾（OUTRO）", "", "**旁白：** 訂閱量化阿森，我們下支見。", "", "---", "",
              "## 📝 YouTube 影片描述", "",
              d.get("description", "量化交易教學與觀念分享。投資有風險，不構成投資建議。"), "",
              f"**Hashtags：** {' '.join(d.get('hashtags') or ['#量化交易', '#自動交易'])}", ""]
    # 風險聲明結構性保底(2026-08-05)。上面 description 的**預設值**含風險聲明,但模型有給
    # description 時就用模型的——模型漏寫,.md 就沒有,audit_video 判「缺風險聲明」退件。
    # 實測:一夜產 9 支長片,其中 2 支就是栽在這裡(換 gemini-2.5-flash 後更常漏)。
    # 下游雖有「事後補寫再重審」的補救,但那是先違規再修;讓稿子**出生就帶著**它更乾淨,
    # 而且這句話本來就該在每支片裡。判斷條件與 audit_video 一致(含「風險」或
    # 「不構成投資建議」即可),不重複補。
    _body = "\n".join(lines)
    if "風險" not in _body and "不構成投資建議" not in _body:
        _body += "\n⚠️ 投資有風險，本影片為資訊與觀念分享，不構成投資建議。\n"
    return _body


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
            subprocess.run([str(kpy), "scripts/tts_kokoro.py", vp], cwd=str(ROOT), **_NO_WINDOW)
        except Exception as _e:  # noqa: BLE001
            log_ops("配音", f"⚠️ Kokoro 呼叫失敗({_e})，退回 edge：{slug}")
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        log_ops("配音", f"⚠️ Kokoro 配音失敗，退回 edge：{slug}")
    if _tts_engine() == "minimax":
        subprocess.run([str(PY), "scripts/tts_minimax.py", vp], cwd=str(ROOT), **_NO_WINDOW)
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        log_ops("配音", f"⚠️ MiniMax 配音失敗，退回 edge：{slug}")
    _ds = _design()  # Edge 聲音/語速吃 design_system(換聲音只改設定檔)
    subprocess.run([str(PY), "scripts/tts_edge.py", vp,
                    "--voice", _ds.get("edge_voice", "zh-TW-YunJheNeural"),
                    "--rate", _ds.get("edge_rate", "+12%")], cwd=str(ROOT), **_NO_WINDOW)


def _run_render(args, env, timeout=720):
    """跑 make_video，逾時就連同子程序(ffmpeg)整組殺掉 —— 防殭屍 ffmpeg 卡死整批製作。"""
    kw = {"cwd": str(ROOT), "env": env, **_NO_WINDOW}
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


# ══════════════════════════════════════════════════════════════════════════
# ── 常青搜尋流量修復(2026-07)：雙軌標題 + SEO 描述首段 + 精準 tags ──
# 現況雷:標題全走「獵奇鉤」(你猜對了嗎/差434%),沒有一支接得到「0050 定期定額」
# 「0056 00919 比較」這種每天有人搜的詞——搜尋流量是常青的(發布後持續進人),
# 對 <100 訂閱的頻道尤其重要(feed 不推時的保底流量)。三段修法(全部 fail-open,
# 任一步失敗都退回原樣,絕不擋產線)：
#   ①雙軌標題:鉤子(title,規則不變)+「|」+ seo_suffix(LLM 另外產出的搜尋詞組)
#   ②描述首段(搜尋權重最高的位置)自動加一句含關鍵字的自然語言摘要,純「前插」不動既有內容
#   ③從標題/旁白抽標的代號+主題詞,併入既有 hashtags 機制(不改動既有機制本身)
# ══════════════════════════════════════════════════════════════════════════

# 已知標的代號白名單(頻道常提到的台股/ETF)——刻意用白名單而非任意 4-6 位數字正則,
# 避免把年份(2026)/百分比(3450)/金額 誤判成股票代號。
_KNOWN_SYMBOLS = ("0050", "0056", "00878", "00929", "006208", "00631L", "00713", "00919",
                  "2330", "2317", "2454", "1101")

# tags/描述都會用到的主題詞白名單(觀眾真的會搜的動作詞/主題詞)。
_SEO_THEME_KW = ("定期定額", "定投", "存股", "回測", "10年回測", "ETF比較", "ETF怎麼選",
                  "網格機器人", "網格交易", "派網", "Pionex", "夏普比率", "最大回撤",
                  "All in", "all in", "一次投入", "除權息", "填息", "當沖", "台股ETF", "大盤")


def _validate_seo_suffix(suffix: str, voice_text: str) -> str:
    """驗證 LLM 產出的 seo_suffix 品質與誠信,不過任一關就回空字串(呼叫端 fail-open,不擋產線)。
    規則:①長度合理(4-20字,官方建議8-14字但不死卡) ②不含 %/倍/萬/億等績效數字用語
    (那些要溯源,不該混進純搜尋詞組,見 fact_source_guard.py 的判準) ③誠信:suffix 裡至少一個
    標的代號或主題詞,必須真的出現在本支旁白裡——不准為了塞關鍵字提到片中沒講到的標的。"""
    s = (suffix or "").strip()
    if not s or not (4 <= len(s) <= 20):
        return ""
    if re.search(r"[%％]|[0-9]+\s*倍|[0-9]+\s*萬|[0-9]+\s*億", s):
        return ""
    hits = [k for k in (_KNOWN_SYMBOLS + _SEO_THEME_KW) if k in s]
    if not hits:
        return ""
    vt = voice_text or ""
    if not any(k in vt for k in hits):
        return ""  # suffix 提到的標的/主題查無本片旁白佐證 → 誠信擋下,退回無 suffix
    return s


def _apply_seo_dual_title(d: dict) -> dict:
    """雙軌標題組稿:hook(現有 title)+『|』+ 已驗證的 seo_suffix。
    fail-open:seo_suffix 缺失/驗證不過/核心字已跟 hook 重複/組完超過 YouTube 100 字上限
    → 原樣回傳純鉤子標題,絕不犧牲鉤子或截斷語意。"""
    try:
        hook = str(d.get("title", "") or "")
        suffix = _validate_seo_suffix(str(d.get("seo_suffix", "") or ""), d.get("voice_text", ""))
        if not suffix:
            return d
        _core = re.sub(r"[^0-9A-Za-z一-鿿]", "", suffix)
        _hook_core = re.sub(r"[^0-9A-Za-z一-鿿]", "", hook)
        if _core and _core in _hook_core:
            return d  # 搜尋詞的核心字已經在鉤子裡了,拼接只是重複,不加
        combined = f"{hook} | {suffix}"
        if len(combined) > 100:
            return d  # 超過 YouTube 標題上限,寧可退回純鉤子
        d["title"] = combined
        d["_seo_suffix_used"] = suffix
    except Exception:  # noqa: BLE001
        pass
    return d


def _extract_seo_tags(title: str, voice_text: str) -> list:
    """從標題/旁白抽『標的代號』+『主題詞』當精準 tags(白名單比對,不誤抓年份/金額)。
    fail-open:抽不到就回空 list,呼叫端只是不併入,不影響既有 hashtags 機制。"""
    try:
        text = f"{title or ''} {voice_text or ''}"
        out = [k for k in _KNOWN_SYMBOLS if k in text]
        out += [k for k in _SEO_THEME_KW if k in text and k not in out]
        return out[:10]
    except Exception:  # noqa: BLE001
        return []


def _build_seo_desc_line(d: dict) -> str:
    """組一句 SEO 首段(描述第一行,YouTube 搜尋權重最高的位置),含觀眾真的會搜的關鍵詞。
    來源優先序:①已驗證過誠信的 seo_suffix ②標題/旁白命中的 SEO_TERMS。抽不到東西就回空字串,
    呼叫端 fail-open 不加這行(不誤導、不硬塞)。"""
    try:
        kws = []
        su = d.get("_seo_suffix_used") or ""
        if su:
            kws.append(su)
        for k in _seo_hit((d.get("title", "") or "") + (d.get("voice_text", "") or "")[:300]):
            # 已被 seo_suffix(或先前收錄的詞)整句涵蓋 → 不重複列(例如 seo_suffix 是
            # 「0056 00919 十年比較」，_seo_hit 又命中子字串「0056」，不需要再列一次)。
            if k not in kws and not any(k in existing for existing in kws):
                kws.append(k)
        if not kws:
            return ""
        kw_text = "、".join(kws[:3])
        # 🔴 2026-07-28:舊版把同一串關鍵詞在一句話裡塞兩次——
        # 「【友達2409 20年回測、存股、大盤】本片用真回測拆解友達2409 20年回測、存股、大盤,…」
        # 讀起來像垃圾訊息,而**搜尋是本頻道長片唯一有效的發現引擎**(實測近28天搜尋詞 top20
        # 幾乎全是個股名/代號),description 前段正是搜尋結果的摘要,塞詞反而有 keyword-stuffing
        # 的反效果。改成關鍵詞只出現一次(留在句首的【】裡,搜尋權重不變),後半寫成人話。
        _lead = kws[0]
        # 2026-08-12 問答式檢索升級:描述首行盡量是「含具體數字的完整結論句」——
        # 官方 Ask YouTube(對話式搜尋)已上線,語意問答時代「一句講出答案」比關鍵詞堆疊值錢;
        # 對傳統搜尋這行也是搜尋結果摘要。做法=**直接引用**旁白裡第一句帶數字的陳述句
        # (已過全部誠信閘門的原文,不重寫不改寫=零編造風險);抽不到才退回通用句。
        _concl = ""
        for _s in re.split(r"[。!?！？\n]", (d.get("voice_text") or "")[:800]):
            _s = _s.strip()
            if (len(_s) >= 12 and not _s.endswith(("嗎", "呢"))
                    and re.search(r"[0-9〇一二三四五六七八九十百千萬億]+(?:%|％|倍|年|趴|萬|元)", _s)):
                _concl = _s[:70]
                break
        if _concl:
            return f"【{kw_text}】{_concl}。完整回測過程與數據來源都在影片裡，看完你能自己判斷。"
        return (f"【{kw_text}】用真實歷史回測數字拆解{_lead}，"
                f"完整過程與數據來源都在影片裡，看完你能自己判斷該怎麼配置。")
    except Exception:  # noqa: BLE001
        return ""


def apply_seo_uplift(d: dict) -> dict:
    """常青搜尋流量修復總入口:make_one 在標題/內容都定案後、寫檔前呼叫一次。
    三步驟彼此獨立、各自 fail-open——任一步出錯都不影響其他步驟與既有產線,
    絕不因為 SEO 加值失敗而擋下整支片。"""
    try:
        d = _apply_seo_dual_title(d)
    except Exception:  # noqa: BLE001
        pass
    try:
        _line = _build_seo_desc_line(d)
        if _line:
            _desc = d.get("description", "") or ""
            d["description"] = _line + "\n\n" + _desc if _desc else _line
    except Exception:  # noqa: BLE001
        pass
    try:
        _extra_tags = _extract_seo_tags(d.get("title", ""), d.get("voice_text", ""))
        if _extra_tags:
            _tags = d.get("hashtags") or []
            _have = {str(x).lstrip("#") for x in _tags}
            for k in _extra_tags:
                if k not in _have:
                    _tags.append(k)
                    _have.add(k)
            d["hashtags"] = _tags
    except Exception:  # noqa: BLE001
        pass
    return d


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
    # ⚠️ 碎句開場的判定**刻意不放這裡**:_weak_hook 只掛在 Shorts 的重生迴圈,
    #    而短片節奏本來就快、句子短,套用長片的 12 字門檻會大量誤殺。
    #    碎句 gate 改放在 _long_bad(見 _long_fragmented_hook),只作用於長片。
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


# 病灶A：資訊密度硬指標(2026-07-13 長片內容審查實測修復)。實測抓到的兩個具體症狀：
# ①一支後半段 40% 篇幅整段跑題(標題講高股息月配,第17段起整段切成2022 All in 0050,用另一支影片的
#   同一組數據湊時長)②同一組核心數字(813%/24.7%/-33.8% vs 380%/16.9%/-22.6%)用「反直覺的是」
#   反覆重講10次以上,只換人物/比喻包裝,實際資訊密度只剩全片1/3。
# gate 只管長度不管密度是根因——本函式在長度達標之外，額外查「內容是不是灌水湊出來的」：
# ①每60秒(≈300中文字,沿用全專案5字/秒估時慣例)窗口至少要有1個『這個窗口才第一次出現』的
#   具體數字,超過45%窗口完全沒有新數字＝判定灌水(填充/贅述撐時長,不是真的展開新內容)。
# ②全片是否有10字以上的片語逐字重複出現>=3次(治「同一組數字換包裝重講10次」的鐵證：
#   換比喻/換人物但核心數字片語不變，n-gram 還是抓得到)。
# 任一命中就回 True，供 make_one 併入既有 A4 長度 gate 的重生迴圈(fail-closed：重生4次仍
# 不達標就整支不輸出，寧可少一支長片也不讓灌水稿冒充「真8-10分鐘資訊密度長片」發出去)。
def _long_content_padding(voice_text):
    """病灶A資訊密度硬檢查：偵測『字數達標但其實是灌水撐出來的』長片(重複數字/片語、
    整段內容零新資訊)。太短的稿子交給既有 _long_underlength 判，這裡不重複判。"""
    t = (voice_text or "").strip()
    n = _long_chinese_chars(t)
    if n < 900:  # 太短的稿子交給 _long_underlength(2000字門檻)判；窗口數太少時比例雜訊大，不在此重複判
        return False
    win_chars = 300  # 5字/秒 * 60秒 ≈ 每60秒一個窗口
    num_pat = re.compile(r"[0-9０-９]+(?:\.[0-9]+)?|[零一二三四五六七八九十百千萬億兩]{2,}"
                         r"|[一二三四五六七八九十兩](?=[趴倍億萬元年個次成分點%])")
    windows = [t[i:i + win_chars] for i in range(0, len(t), win_chars)]
    # 結尾殘段(<半個窗口)常是收尾/CTA、本就不必然帶新數字，排除在比例計算外，避免誤判
    windows = [w for w in windows if len(w) >= win_chars * 0.5] or windows
    seen_nums, empty_windows = set(), 0
    for w in windows:
        nums = num_pat.findall(w)
        fresh = [x for x in nums if x not in seen_nums]
        if not fresh:
            empty_windows += 1
        seen_nums.update(nums)
    if len(windows) >= 3 and (empty_windows / len(windows)) > 0.45:
        return True
    from collections import Counter
    chars_only = re.sub(r"[^一-鿿0-9]", "", t)
    n_gram = 10
    grams = Counter(chars_only[i:i + n_gram] for i in range(max(len(chars_only) - n_gram + 1, 0)))
    return any(c >= 3 for c in grams.values())


# 病灶A 跑題偵測用的「題材叢集」：同一叢集的詞＝同一個影片主題。
# ★設計依據(用 21 支現存長片實測校準出來的，不是憑感覺設規則)：
# ①「本片標的以外的代號出現很多次」**不能**當跑題訊號——本頻道主力就是對比型內容(0056 vs 0050、
#   台積電 vs 大盤)，對照組本來就會被大量提及。實測用這條會誤殺 3 支正常的對比片(誤殺＝fail-closed
#   不出片，代價比漏抓高)。故此條已移除，只保留下面的「題材被換掉」。
# ②真正的跑題訊號是**題材整段被換掉**：標題講「0050 定投 vs 美股 ETF」，中後段卻整段在講
#   「高股息月配息、領息 vs 賺價差」——那是另一支影片的主題(這正是本次修復的證物)。
# ③題材若是本片標的「天生自帶」的(0056/00878/00929 本來就是高股息 ETF、00631L 本來就是槓桿)，
#   那講該題材完全合理，不算跑題 → 用 _SYMBOL_IMPLIED_THEMES 排除，避免誤殺高股息片。
_THEME_CLUSTERS = (
    ("高股息", "月配息", "月月配", "領股息", "配息", "股息", "殖利率", "除權息", "填息"),
    ("當沖",),
    ("槓桿", "正2"),
    ("網格",),
)
# 標的天生自帶的題材(講它=本來就該講,不算跑題)
_SYMBOL_IMPLIED_THEMES = {
    "0056": "高股息", "00878": "高股息", "00929": "高股息", "00631L": "槓桿",
}


def _long_topic_drift(voice_text, title, max_share=0.12):
    """病灶A主題鎖定 gate：偵測『影片後段悄悄變成另一支片的主題』(確定性判準，不靠 LLM 自評)。

    實跑抓到的真實症狀(本次修復的直接證物)：標題「0050 定期定額 vs 美股ETF」，中後段卻連續數段
    整段在講「0056 高股息月配息 / 領息 vs 賠價差」——那是另一支影片的主題，用別支片的內容湊時長。

    判準：把旁白依段落切開，找出「被一個**標題與本片標的都不涉及**的題材叢集主導」的實質段落
    (該叢集密集出現 >= 4 次，且該段還提到了屬於那個題材的外來標的；或密集到 >= 6 次)，
    這些跑題段合計篇幅 > max_share(12%) ＝整支判定跑題。允許順帶一提的延伸比較，但不許變成主線。

    刻意不擋的情況(實測校準，避免誤殺正常片)：對照組標的被大量提及(對比片的本質)、
    高股息片講股息、槓桿片講槓桿、以及只在片尾順帶提一句別的標的。"""
    t = (voice_text or "").strip()
    title_syms = _symbols_in(title)
    if not t or not title_syms:
        return False
    paras = [p for p in t.split("\n") if p.strip()]
    if len(paras) < 3:
        return False
    # 本片「天生就該講」的題材＝標題明講的 + 標題標的自帶的
    own_themes = {_SYMBOL_IMPLIED_THEMES[s] for s in title_syms if s in _SYMBOL_IMPLIED_THEMES}
    total = sum(_long_chinese_chars(p) for p in paras) or 1
    drift_chars = 0
    for p in paras:
        if _long_chinese_chars(p) < 100:  # 太短的段(片尾聲明/CTA)不判，順帶提一句不算跑題
            continue
        for cluster in _THEME_CLUSTERS:
            if cluster[0] in own_themes or any(term in title for term in cluster):
                continue  # 本片本來就該講這個題材
            hits = sum(p.count(term) for term in cluster)
            if hits < 4:
                continue
            # 段內是否出現「屬於這個外來題材的標的」(如高股息題材的 0056/00878)＝題材真的被換掉的佐證
            themed_foreign = any(
                s in p for s, th in _SYMBOL_IMPLIED_THEMES.items()
                if th == cluster[0] and s not in title_syms)
            if themed_foreign or hits >= 6:
                drift_chars += _long_chinese_chars(p)
                break
    return (drift_chars / total) > max_share


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
    """誠信自癒:組稿後跑守門,對含旗標的深段各重寫一次(把捏造/未標示數字改成 facts 真數字或假設語氣、
    中文念法)。回傳(修過的 bodies, 殘留旗標數)。守門讀不到就原樣回。

    🔴 2026-07-17 長片產能白燒根因:本函式(產製端自癒)以前只問 fact_guard,但發布端
    daily_publish._factguard_gate 是用 **fact_source_guard** 擋——兩道用不同判準,而且剛好
    互補不到:fact_guard 只認阿拉伯數字 `\\d+%`,長片卻一律寫中文唸法(「百分之八十」,見
    _LONG_DATA_DISCIPLINE ③,那是為了 TTS)→ **產製端結構上看不見發布端會擋什麼**,
    片整支渲染完才在發布前被打掉。實案:L_AI策略回測勝率90…(「國外研究發現…八成是過度擬合」)、
    L_AI策略回測贏大盤…(「年化報酬高達百分之八十」)兩支長片全片渲染完才被擋,佔當時長片庫存 18%。
    這裡把發布端那把尺接進來,讓自癒跟守門同一個判準——**不放寬任何 gate**,是要求產製端達標。
    """
    try:
        import fact_guard, llm
    except Exception:  # noqa: BLE001
        return bodies, 0
    # 事實庫數字池太小 = 守門自己壞掉(會誤判全部無憑據),照 daily_publish 的 fail-open 慣例不擋。
    try:
        import fact_source_guard as fsg
        _pool = fsg.fact_pool()
        if len(_pool) < 10:
            _pool = None
    except Exception:  # noqa: BLE001
        fsg, _pool = None, None

    def _unsourced(text):
        if not (fsg and _pool):
            return []
        try:
            return fsg.unsourced_claims(text, _pool)
        except Exception:  # noqa: BLE001
            return []

    for _round in range(2):
        remaining = 0
        for k, para in enumerate(bodies):
            hits = fact_guard.flags_for(para)
            banned = _promo_banned_hits(para)
            unsourced = _unsourced(para)
            if not hits and not banned and not unsourced:
                continue
            # 重寫不得讓段落縮水,但本函式也被 hook/小結(短文本)複用——固定門檻 100 字會讓
            # 短文本的修正稿一律被判定失敗丟棄(hook 只有 ~60 字,等於 hook 永遠治不好)。
            # 改成相對原段落的比例,對正常深段仍是原本的 100 字門檻,對短文本才放行。
            _min_keep = min(100, max(20, int(_long_chinese_chars(para) * 0.6)))
            try:
                _issue = (f"疑似捏造/未標示數字:{hits[:6]}；" if hits else "") + \
                         (f"誇大保證禁語:{banned}(必刪);" if banned else "") + \
                         (f"**查無來源的績效數字:{[c['value'] for c in unsourced[:4]]}**"
                          f"——事實庫裡根本沒有這些數字(例:「{unsourced[0]['clause'][:28]}」),"
                          "發布端會直接擋掉整支片。必須擇一處理:①刪掉 ②換成下面 facts 的真數字 "
                          "③改寫成明講的假設語氣(「假設」「打個比方」「示意」開頭)。"
                          "尤其**嚴禁掛名不實**——沒有這個研究就不要寫「國外研究發現」「回測顯示」;"
                          if unsourced else "")
                hp = (
                    f"你是量化阿森頻道的長片腳本寫手。{GUARD}\n以下段落被守門抓到問題:{_issue}。"
                    "請重寫這一段,維持一樣的長度與子主題,但:把不是下面 facts 給的精確數字全部拿掉或"
                    "改成『假設/示意』語氣、絕不虛構股價點位、所有數字改中文口語念法、講績效百分比時點明歷史回測不代表未來;"
                    "**絕不出現穩賺/穩賺不賠/保證獲利/包賺/零風險等禁語**(要拆迷思改用『以為很安全』)。\n"
                    f"{facts_ctx}\n{integrity}{_LONG_DATA_DISCIPLINE}\n"
                    "只輸出重寫後的完整段落純文字,不要JSON/小標/前後綴。\n\n【原段落】\n" + para
                )
                fixed = _fix_artifacts(_to_traditional(llm.complete(hp, 1800).strip()))
                if fixed and _long_chinese_chars(fixed) >= _min_keep:
                    bodies[k] = fixed
                    if (fact_guard.flags_for(fixed) or _promo_banned_hits(fixed)
                            or _unsourced(fixed)):
                        remaining += 1
                else:
                    remaining += 1
            except Exception:  # noqa: BLE001
                remaining += 1
        if remaining == 0:
            break
    return bodies, remaining


def _densify_long(d, facts_ctx, is_tw, facts=None, topic=None):
    """A4 真長片內容引擎·分段深寫：治「LLM 一次寫不出 2600 字、只吐 ~1000 字冒充長片」的根因。
    做法：保留原稿開場 HOOK(前 3 句),對每個 segment 各發一次 LLM,把該子主題寫成 ~470 字的深段
    (①具體數據/案例情境切入 →②原理解釋 →③反直覺轉折或對比,段首帶承接語),最後補一段對比/實測小結。
    每段只要寫 ~470 字模型都做得到,4-5 段自然堆到 2200-2600 字。台股題每段可各引不同真數字,
    非台股題一律示意/假設語氣(誠信不變)。任何失敗靜默回原稿,不中斷產線。

    病灶A修復(2026-07-13 長片內容審查實測)：舊版把同一份 facts_ctx(最多6條相同事實文字)
    原封不動塞進每一段 prompt，LLM 只能對同一組數字換比喻/換人物重講(『反直覺的是』洗10次)。
    現改逐段分配「本段專屬事實」——primary(與題材相關)事實池每條只分給一個 body 段落，
    同一個 fact key 全片最多再被結尾小結引用一次(鋪陳+收尾＝上限2次)；池不夠時，中後段最多
    分配 1 個 extension(非本題材)事實做『延伸比較』，強制帶轉場語且字數壓低以符合全片篇幅≤15%。"""
    try:
        import llm
        segs = d.get("segments") or []
        if len(segs) < 3:
            return d  # 段數太少撐不出長片密度,交給 make_one 的重生機制
        title = d.get("title", "") or ""
        voice = d.get("voice_text", "") or ""
        integrity = TW_STOCK_RULES if is_tw else NO_FACTS_INTEGRITY_RULES
        sents = [s for s in re.split(r"(?<=[。！？!?])", voice) if s.strip()]
        hook = _take_hook(sents)  # 保留原稿三步框架 HOOK 開場(依字數取,非盲目取3句)
        # ── 病灶A：主題鎖定+事實分配 ──
        primary_pool, extension_pool = _relevant_facts_list(facts, topic)
        used_keys = []
        n_segs = len(segs)
        ext_assigned = False  # 全片最多 1 個延伸比較段落(篇幅上限靠字數預算壓低+事後裁切雙重把關)
        ext_seg_indexes = set()
        bodies, prev = [], "開場鉤子"
        for i, seg in enumerate(segs, 1):
            heading = ((seg.get("heading") if isinstance(seg, dict) else str(seg)) or f"重點{i}")
            # 逐段挑一個「本段專屬、還沒被其他段引用過」的 primary 事實；primary 池用完才考慮 extension。
            seg_fact = next((f for f in primary_pool if f["key"] not in used_keys), None)
            is_extension_seg = False
            if seg_fact is None and extension_pool and not ext_assigned and i >= max(2, n_segs - 1):
                seg_fact = extension_pool[0]
                is_extension_seg = True
                ext_assigned = True
            if seg_fact:
                used_keys.append(seg_fact["key"])
            if seg_fact:
                fact_line = (f"\n【本段專屬事實(本段只准引用這一條,不得重複其他段落已引用過的數字/結論)】\n"
                             f"  ·{seg_fact['desc']}：{seg_fact['summary']}\n")
            else:
                fact_line = ("\n【本段無新事實可引用】本段不得重複前面段落已經講過的任何具體數字/結論——"
                             "只能做原理解釋、情境延伸或明確的『延伸比較』分析，不能複述已用過的百分比/倍數。\n")
            # 主題鎖定：**每一段**都掛(不只延伸段)。實跑抓到的 bug——只在延伸段講「別跑題」，
            # 一般深段沒被告知本片主題，拿到什麼事實就整段寫什麼，後段整段變成另一支片的主題。
            topic_lock_note = (
                f"\n★主題鎖定(硬性)：本片主題是「{title}」。這一段**必須是在講這個主題**，"
                "只能圍繞本片主題的標的與比較對象展開；**嚴禁**把段落寫成另一個標的/另一支影片的主題"
                "(例如本片講 0050 對比美股 ETF，就不可以整段跑去講 0056 高股息月配、也不可以整段變成"
                "在講其他標的的優劣)。若本段拿到的事實與本片主題不完全吻合，就只把它當『一句話的旁證』"
                "帶過，主線仍必須回到本片主題。\n")
            char_budget = "520-620"
            if is_extension_seg:
                topic_lock_note = (
                    f"\n★主題鎖定：本片主題是「{title}」，這一段引用的事實屬於**不同主題**的延伸比較，"
                    "**開頭第一句務必用『延伸比較』式轉場**(例如「換個角度看/延伸比較一下/如果換成另一種做法」)，"
                    "全段只能是簡短的對比延伸，最後一句必須把話題**收回本片主題**，"
                    "絕不能變成本片主要論述、絕不能偷換掉本片主題。\n")
                char_budget = "260-340"  # 壓低字數，確保延伸段落全片佔比≤15%
                ext_seg_indexes.add(len(bodies))  # 記下即將寫入的 index(下方 append 前先記)
            prompt = (
                f"你是量化阿森頻道的專業長片腳本寫手。{GUARD}\n{QUANT_STANDARD}\n"
                f"這是長片《{title}》的第 {i} 段,子主題:「{heading}」。只寫這一段旁白,**務必寫滿 {char_budget} 中文字**"
                "(這是長片深段,字數不夠會被打回,寧可多給細節也不要少寫)。\n"
                "務必有完整弧線且每一步都展開講透:①用具體數據或案例情境切入(不是空泛開場,給場景/數字/人物處境)"
                " →②解釋為什麼會這樣的原理(講清機制、別只下結論) →③一個反直覺轉折,或跟另一種做法的具體對比,"
                "並補一句這對觀眾的實際意義。段首用一句自然承接語接上文"
                f"(上一段講的是「{prev[:30]}」)。嚴禁清單體一句帶過。\n"
                "★資訊密度鐵律：本段**不得重複**前面任何段落已經講過的具體數字/結論,只能換句話講——"
                "『反直覺的是』這類轉場句全片最多出現 2 次,本段若前面已用過同組數字/結論就不要再換個比喻/"
                "換個人物重講一次,那是灌水;本段一定要帶出**新的**資訊或角度,講不出新東西就把這段寫短一點、"
                "誠實地做承轉,不要硬湊字數重複前段。\n"
                f"{fact_line}{topic_lock_note}"
                f"{integrity}{_LONG_DATA_DISCIPLINE}\n"
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
            elif is_extension_seg:
                ext_seg_indexes.discard(len(bodies))  # 這段沒寫成功，取消預記的 index
        if len(bodies) < 3:
            return d  # 深寫沒成功湊到 3 段,回原稿讓 gate 決定重生/fail-closed
        # 主題鎖定篇幅上限(≤15%)：延伸比較段落若實際佔比仍超標，直接砍掉這段——寧可少一段也不跑題。
        total_body_chars = sum(_long_chinese_chars(b) for b in bodies)
        if ext_seg_indexes and total_body_chars:
            _ei = next(iter(ext_seg_indexes))
            if _ei < len(bodies):
                _ext_chars = _long_chinese_chars(bodies[_ei])
                if len(bodies) > 3 and (_ext_chars / total_body_chars) > 0.15:
                    bodies.pop(_ei)
        # top-up:總量還沒到目標時,挑最短的 1-2 段就地加深(續補細節/對比),把長度穩穩推過門檻。
        # 病灶A：加深時不再注入 facts_ctx(避免重新引入其他段已用過的相同事實文字)，只要求深挖
        # 既有內容的原理/情境/對比，不引入新的精確數字，維持「不重複」鐵律。
        def _cur_total():
            return _long_chinese_chars(hook) + sum(_long_chinese_chars(b) for b in bodies)
        _tu = 0
        while _cur_total() < LONG_TARGET_CHARS and _tu < 2 and bodies:
            _tu += 1
            _idx = min(range(len(bodies)), key=lambda k: _long_chinese_chars(bodies[k]))
            try:
                tp = (
                    f"你是量化阿森頻道的長片腳本寫手。{GUARD}\n以下是長片《{title}》的一個段落,請把它"
                    "『加深擴寫』到 560-680 中文字:補更多原理細節、情境舉例、或這件事對觀眾的實際意義,"
                    "維持同一子主題與口語短句,不要改變立場、**不要引入新的精確數字/百分比、不要湊贅字重複句**。\n"
                    f"{integrity}{_LONG_DATA_DISCIPLINE}\n只輸出擴寫後的完整段落純文字,不要JSON/小標/前後綴。\n\n"
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
        # (這是 fact key 允許的『第二次引用』位置——鋪陳在 body、收尾在此小結，上限2次由此自然成立)
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
            # 進場條件交給 _long_fact_heal 自己判(它對乾淨段落會直接 continue、不燒 LLM)。
            # 以前這裡先用 fact_guard_flags 篩一次,等於把「中文唸法的無憑據數字」擋在自癒之外
            # ——那正是發布端會擋的東西(見 _long_fact_heal docstring)。
            if _summary:
                _summary = _long_fact_heal([_summary], facts_ctx, integrity, title)[0][0]
        except Exception:  # noqa: BLE001
            _summary = ""
        # hook 來自 call_claude 主草稿,偶爾也帶禁語/未標示數字 → 一併過自癒(保證整支進審核零禁語)
        # 實案兩支被擋的長片,無憑據數字就是落在 hook(「年化報酬高達百分之八十」)。
        if hook:
            hook = _long_fact_heal([hook], facts_ctx, integrity, title)[0][0]
        parts = ([hook] if hook else []) + bodies + ([_summary] if _summary and _long_chinese_chars(_summary) >= 80 else [])
        new_voice = "\n".join(p for p in parts if p)
        # 病灶A：全片『反直覺的是』硬上限2次，確定性後處理，不靠 LLM 自律(對齊 A1c 硬擋精神)
        new_voice = _cap_repeated_phrase(new_voice, "反直覺的是", 2)
        if _long_chinese_chars(new_voice) > _long_chinese_chars(voice):
            d["voice_text"] = new_voice
            d["_densified"] = True
            d["_fact_keys_used"] = used_keys  # 供自驗/稽核查『用了哪些 fact key、有沒有重複』
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] A4 長片分段深寫失敗,放行原稿：{str(exc)[:80]}", file=sys.stderr)
    if _parent_slug:
        d["_parent_slug"] = _parent_slug
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
        # 7000 → 3200:同上,輸入+max_tokens 必須塞進每分鐘桶(見 _maxtok 的說明)。
        # 加深要吐 2600+ 字 ≈ 2200 tokens(llama 實測 1.18 字/token),3200 夠且有餘裕。
        txt = llm.complete(prompt, 7000, json_mode=True)  # 同上:走 OpenRouter 後不再受免費層桶限制
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


def _bump_tw_lab(d, slug):
    """台股真相實驗室正片產出成功 → 遞增系列狀態(集數+1、標記本集事實 key 已用、EP>=10 收官升季)。
    純本地檔，失敗不影響出片。"""
    try:
        import tw_lab_engine
        st = tw_lab_engine.load_state()
        rec = {"key": d.get("_tw_lab_key", ""), "title": d.get("title", ""), "slug": slug}
        new_st = tw_lab_engine.bump_episode(st, rec, persist=True)
        log_ops("台股真相實驗室", f"EP 遞增 → S{new_st.get('season')} EP{new_st.get('current_ep')} 已記錄：{slug[:28]}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] tw_lab bump 略過：{str(exc)[:80]}", file=sys.stderr)


# LLM 偶發疊字守門(實測 574 支中 5 支出「演演算法」;非 code bug、是模型 stutter,但會被 TTS 念出來)。
# 只列「絕不可能是正確疊字」的術語→修回,不碰「剛剛/常常」等正確疊字,零誤傷。
_ARTIFACT_FIXES = {
    "演演算法": "演算法", "機機器人": "機器人", "網網格": "網格", "回回測": "回測",
    "複複利": "複利", "停停損": "停損", "定定投": "定投", "槓槓桿": "槓桿", "手手續費": "手續費",
    # 程度副詞疊字(_cap_repeated_phrase 換轉場詞時可能與原文的「更/還」相接產生;已在該函式吃掉
    # 前綴副詞治本,這裡留一道最後安全網,確保任何路徑都不會把疊字結巴念進 TTS)
    "更更": "更", "還還": "還", "但但": "但",
}


# ── 旁白清理(2026-08-06)────────────────────────────────────────────────────
# 為什麼:voice.txt **就是 TTS 的輸入**,裡面有什麼就念什麼。掃描 419 支已產旁白:
#   markdown 殘留(`**粗體**`、`1. 2. 3.` 清單) **43 支 = 10.3%**
#   括號舞台指示(「(轉場語氣)」)4 支、講稿結構外洩(「講完開場鉤子」「第一段」)9 支
# 實例:`1. **錢能放超過十年**→優先選0050` —— 這是**把文件念出來**,不是說話;
# 還有一支旁白直接念出「(以中文口語念出) 好,講完開場鉤子,我們來看看具體資料」。
# 十支裡有一支這樣,而且觀眾聽得出來——這是「影片很爛」最直接的成因之一。
#
# 原本的 _fix_artifacts 只是一張字面替換表,不處理這些結構性殘留。
# ⚠️ 只清「表現形式」,不動任何內容字句:不刪句子、不改數字。唯一整段移除的是
#    舞台指示與講稿結構語,那些本來就不該被念出來。
_STAGE_RE = re.compile(r"[（(][^）)]{0,26}?(念出|口語|語氣|停頓|畫面|旁白|配音|音效|轉場|插入|字幕)[^）)]{0,26}?[）)]")
# 段落接縫語(2026-08-06 留存實測):長片在**第 15 秒到 30 秒之間掉掉一半觀眾**
# (聯鈞體檢那支 0.85→0.42、00878 那支 0.89→0.54),而那 15 秒逐字對出來正好是
#   「…卡瑪比率只有零點二四。**接續上一段提到的超高報酬神話**,我們來仔細看看…」
# 「接續上一段」是**講稿的接縫**,觀眾根本不知道有「上一段」——那是我們把 segments
# 切開來寫留下的疤。全長片 112 支裡 **29 支(26%)** 在前 25% 出現這類話。
# 這類詞整段移除不會傷內容(它本來就只是連接詞),所以放在清理器裡最安全。
_META_RE = re.compile(r"(講完開場鉤子[，,、]?|開場鉤子[，,、]?|以下是[^。，]{0,10}[：:]|"
                      r"第[一二三四五六七八九十]段[，,、：:]|段落[一二三四五][，,、：:]|"
                      r"接續上一?段[^，。]{0,12}[，,]?|承上[，,]|如前所述[，,]?|"
                      r"前面提到[的過]?[，,]?|上一段[提說]到[的過]?[，,]?|"
                      # 2026-08-11 庫存掃描補:真實汙染樣態是「上一段我們看到X，」「前面我們
                      # 看到X，」這類**完整接縫子句**(未發布 38 支裡 9 支中招),舊表只抓
                      # 「上一段提到」接不到。統一規則:段落自指(上一段/上一節/前一段)起頭、
                      # 到最近逗號為止的整個子句一起移除——觀眾沒有「段」的概念,這種子句
                      # 只可能是講稿接縫,整句拿掉不傷內容。
                      r"[上前]一[段節][^，。]{0,26}[，,]|前面我們[看提說]到[^，。]{0,26}[，,]?)")
_LIST_NUM = {"1": "第一，", "2": "第二，", "3": "第三，", "4": "第四，", "5": "第五，"}
# 空泛的「留下來」哀求句(2026-08-12 留存實測 24x 懸崖:「這支影片你一定要看到最後」)。
# 只殺**空泛版**(整句是哀求、講不出會給什麼);「最後會給你完整回測」這種帶具體 payoff 的
# end-reward 預告是留存工具,不殺——所以 pattern 錨定「(一定/記得/千萬)要…看到最後/看完」
# 這個祈使結構,並吃掉該句其餘部分(它整句都是 filler)。
_PLEA_RE = re.compile(r"[^。！？!?\n]{0,30}(?:一定要|記得|千萬要|千萬別錯過)[^。！？!?\n]{0,10}"
                      r"(?:看到最後|看到結尾|看完(?:這支)?影片|別走開)[^。！？!?\n]{0,15}[。！？!?]?")


# ── 片中訂閱鉤(2026-08-06 留存×CTA 位置實測)──────────────────────────────
# 實測 112 支長片:**101 支把第一次訂閱呼籲放在影片的 90%~100% 處**,中位數 98%。
# 而留存曲線顯示影片播到 90% 時只剩 0.05~0.38 的觀眾
# → **我們在 62%~95% 的人已經離開之後才開口要訂閱。**
# 影片走到 30~40% 時留存還有 0.5~0.6,同一句話放在那裡聽得到的人多 2~10 倍。
#
# 為什麼做成確定性插入而不是寫進提示:結尾訂閱鉤的規則早就寫在 LONG_RULES 裡,
# 實測遵從度還是讓 101/112 擠在結尾。這種「每支都該有、位置固定」的東西,
# 用程式保證比用提示請求可靠(同 _LOOP_HOOK_POOL 的判斷)。
#
# 誠信:不寫「演算法不會再推你」這類平台操弄語氣(本檔 1248 行已明令禁止),
# 只講「訂閱能拿到什麼」。也不假裝有結局懸念——長片不是連載。
_MID_SUB_POOL = [
    "如果這個數字跟你原本想的不一樣，這個頻道每天用真實回測拆一個台股迷思，訂閱就不會錯過。",
    "會這樣拆數據的頻道不多，我每天挑一個台股說法用真回測驗一次，訂閱可以跟著看。",
    "這種算法你在別的地方不太會看到。我固定用真實回測拆台股迷思，訂閱就能一直收到。",
    "先講一句：後面還有更反直覺的部分。這個頻道專門用真數據拆台股說法，訂閱不會漏掉。",
]
_SUB_WORD = re.compile(r"訂閱")


def _insert_mid_sub_hook(text, slug=""):
    """在旁白約 35% 處插入一句訂閱鉤(長片專用)。已經有早期訂閱呼籲就不插。"""
    if not isinstance(text, str) or len(text) < 900:
        return text
    # 前 60% 已經有訂閱呼籲 → 不重複插
    early = text[: int(len(text) * 0.6)]
    if _SUB_WORD.search(early):
        return text
    target = int(len(text) * 0.35)
    # 找最接近 35% 的句尾(只在句號/問號/驚嘆號後切,不切在句子中間)
    best, bestd = None, len(text)
    for m in re.finditer(r"[。！？!?]", text):
        d = abs(m.end() - target)
        if d < bestd:
            best, bestd = m.end(), d
    if best is None or best <= 0 or best >= len(text):
        return text
    h = int(hashlib.md5((slug or text[:40]).encode("utf-8")).hexdigest(), 16)
    line = _MID_SUB_POOL[h % len(_MID_SUB_POOL)]
    return text[:best] + "\n\n" + line + "\n\n" + text[best:]


_AB_EXP = "opening_v1"          # 實驗代號;換實驗時改這個,舊分組自動失效不會混在一起
_AB_B_RULES = """

════════════════════════════════════════════════════════════
🔬【本支影片走 B 組開場規範·覆蓋上面任何衝突的開場指示】
鉤子(前兩句)講完之後,**下一句必須直接是內容本身**。具體禁止:
  ✗「今天我將／我們將帶你體檢…」「看完這支影片你會知道…」  ← 預告要做什麼
  ✗「量化阿森頻道的目標是…」「本頻道用資料…」              ← 頻道自我介紹
  ✗「首先,我們來認識一下這次的主角…」                      ← 過場句
把這三種句子完全刪掉,直接從第一個真數據開講。
判準:第 3~6 句拿掉之後如果資訊完全沒少,那就是該刪的鋪陳。
════════════════════════════════════════════════════════════
"""


def _ab_arm(seed_text: str):
    """開場結構 A/B 分組。回 (arm, 要追加到 prompt 的字串)。

    ## 為什麼要做實驗而不是直接改規則(2026-08-19)
    留存 22.3%、平均只看 115 秒,是 BROWSE(首頁推薦)基線為 0 的直接原因。
    留存曲線把斷崖定位在第 15~25 秒,而那裡逐字對照就是「節目預告+頻道自我介紹」。
    看起來因果很清楚——但同一天我用**觀察性數據**驗了四個同樣「看起來很清楚」的假說,
    三個被推翻,其中「前 40 秒端出對比數字」還是**反向**的(見 _long_no_early_contrast)。
    真長片彼此的混淆變數(片長、題材、發布日競爭、股票熱度)比效果本身還大,
    再怎麼切都切不出因果。所以這次改用隨機分組實驗。

    ## 設計
    · 隨機化:拿題目標題做 md5,取末位奇偶分組——同一支片重生時分組不變(可重現),
      而標題與留存無關,所以這個分派對結果是中性的。
    · A 組(對照)= 現行 LONG_RULES 原樣;B 組 = 追加「鉤子後禁止鋪陳」硬規範。
    · 分組寫進 STUDIO/ab_experiment.json,發布後由 scripts/ab_report.py 比對真實留存。
    · **只作用於長片**:Shorts 沒有這個結構問題。
    · 關掉方式:設環境變數 AB_OPENING=off。實驗結束後把這裡整段拿掉,別留著長灰。
    """
    import hashlib as _h
    import os as _os
    if _os.environ.get("AB_OPENING", "").strip().lower() == "off":
        return "off", ""
    arm = "B" if int(_h.md5((seed_text or "").encode("utf-8")).hexdigest()[-1], 16) % 2 else "A"
    try:
        from pathlib import Path as _P
        import json as _j
        f = _P(__file__).resolve().parent.parent / "STUDIO" / "ab_experiment.json"
        d = _j.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        d.setdefault(_AB_EXP, {})[(seed_text or "")[:80]] = arm
        f.write_text(_j.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return arm, (_AB_B_RULES if arm == "B" else "")


def _long_no_early_contrast(voice_text):
    """⛔ **實測反向,故意不接進 _long_bad**。保留這支是為了記住這個失敗的假說。

    我從正反例(留存 44.1% 的 0056 vs 22.3% 的台半)推論「前 40 秒要端出對比數字」,
    看起來很有道理。拿全部 91 支真長片(>5 分鐘,已控制片長混淆)回頭驗:
        符合這條的 n=76 → 留存中位 21.6%、平均觀看 116s
        違反這條的 n=15 → 留存中位 **25.0%**、平均觀看 **141s**
    **違反的反而比較好。** 如果當時沒驗就接上去,會擋掉留存較高的那批片。

    有數據支持的只有一條(而且現有規則ⓓ已經涵蓋):開場前 60 字(約 15 秒)塞
    **3 個以上**數字的片留存 18.1%,明顯低於 0~2 個的 21.5~22.3%;而 0/1/2 個之間沒有差別。

    教訓同 memory yt-quality-score-not-predictive:任何「聽起來很合理」的內容判準,
    上線前先拿它去分割真實留存數據,而且要控制片長(留存 vs 片長 r=-0.675,不控制會全錯)。

    ## 原始推論(留作紀錄)
    留存最好與最差的長片,逐點比對留存曲線,差別不在有沒有鋪陳,在**多快給出對比**:
        留存 44.1%(0056,919 觀看):第5% 0.84 → 第49% 0.46
            25 秒「0056 總報酬 397.2%」/ 32 秒「同期 0050 是 986.5%」
        留存 22.3%(台半 5425)     :第5% 0.47 → 第20% 0.18
            33 秒還在「這家公司是做二極體與車用半導體的隱形冠軍…」
    一個是「你以為的答案錯了,證據在這」,另一個是「讓我先介紹這家公司」。

    ## 判準
    前 180 字(中文語速約 4.5 字/秒 ≈ 前 40 秒)裡,要有 **2 個以上帶單位的數字**
    (%／倍／年),阿拉伯數字與中文唸法都算——旁白一律是中文唸法,只認阿拉伯數字會全誤判。
    只有一個數字不算對比(「賺了 270%」不是對比,「賺 270%,同期 0050 賺 716%」才是)。
    """
    import re as _re
    z = (voice_text or "")[:180]
    n = len(_re.findall(r"\d+(?:\.\d+)?\s*(?:%|％|倍|年)", z))
    n += len(_re.findall(r"百分之[零一二三四五六七八九十百千點]+", z))
    n += len(_re.findall(r"[零一二三四五六七八九十百千點]{2,}\s*(?:倍|年)", z))
    return n < 2


def _long_mixed_period(voice_text, slug=""):
    """旁白拿「不同期間的兩個數字」當同期對比 → 回 True(不合格)。

    ## 為什麼(2026-08-20 實測,64 支已發布片中招)
    個股體檢的事實庫裡有兩組期間不同的報酬:
        long_horizon = 上市以來/近 20 年(例:聯鈞 20 年 4322.4%)
        three_way    = **近 10 年**(共同起點才能跟 0050 比;例:聯鈞 459.4% / 0050 685.3%)
    模型很容易拿 long_horizon 的個股報酬,配上 three_way 的 0050 報酬,中間寫「同期」:
        「20 年賺 4322%…**同期** 0050 總報酬 685.3%」   ← 685.3% 其實是 10 年的
        「存 20 年…同期 0050 多賺七倍」(豐泰)           ← 20 年豐泰其實賺 1031%,0050 反而輸
    數字每一個都是真的,但**期間被偷換**,效果是**低估 0050**——讓個股顯得比實際好。
    這跟頻道「誠實實測」的定位完全相反,而且觀眾的質疑正好是反方向
    (「0050 相同期間含息報酬差不多」),等於在他們最會檢查的地方出錯。

    ## 判準:提到 0050 對照就必須標明期間
    只看「同期/同一段時間」+ 0050 出現的句子:那句(或緊鄰的前一句)裡必須有年數。
    有標年數就放行——「**十年**總報酬還輸給同期 0050」是完全正確的講法,
    台半那支片裡兩種寫法都有,對的那句不該被擋。
    fail-closed 但只擋沒標期間的,不影響正確表述。
    """
    import re as _re
    t = voice_text or ""
    sents = _re.split(r"(?<=[。!?！？])", t)
    for i, s in enumerate(sents):
        if not _re.search(r"同期|同一段時間|同樣的時間", s):
            continue
        if not _re.search(r"0050|零零五零|臺灣五零|台灣五十|臺灣五十|臺灣50|台灣50", s):
            continue
        # ⚠️ 只看**這一句本身**,不看前一句。第一版把前一句也算進去,結果
        # 「聯鈞**二十年**總報酬 4322.4%。有趣的是,同期 0050 是 685.3%」被放行了
        # ——而前一句那個「二十年」正是問題本身(685.3% 其實是 10 年的)。
        # 觀眾聽到對照那一句時就必須知道是哪段期間,所以年數要在同一句裡。
        if not _re.search(r"[\d零一二三四五六七八九十]{1,3}(?:點[\d零一二三四五六七八九]+)?\s*年", s):
            return True
    return False


def _long_preamble(voice_text):
    """鉤子之後還在鋪陳 → 回 True(不合格)。

    ## 為什麼(2026-08-19 留存曲線實測)
    台半 5425 的逐點留存(elapsedVideoTimeRatio × audienceWatchRatio):
        第 1% 0.93 → 第 3% 0.83 → **第 5% 0.47** → 第 10% 0.29
    片長 490 秒,換算成絕對時間 = **第 15~25 秒之間走掉一半**;
    relativeRetentionPerformance 全程 0.24~0.40(同長度影片中排後段)。
    而開場鉤子其實**已經修好了**(0.93/0.83 守得很漂亮,規則ⓐ~ⓔ 生效),
    人是死在鉤子後面那段。逐字對照 08-18 那批新片,三支全是同一個形狀:
        16.0s「今天,我將用最真實的資料,帶你體檢這家公司,揭露…」
        25.4s「量化阿森頻道的目標,就是用資料幫你拆解市場迷思…」
        32.8s「在今天的個股體檢系列中,我們將深入分析…」
    連續三句都在講「這支影片等一下要做什麼」,佔掉 15~40 秒——正是斷崖的位置。

    ## ⚠️ 證據等級:弱(留著是因為它擋的是明確的內容缺陷,不是因為統計證明)
    拿它去分割 91 支真長片的實際留存,違反這條的只有 **n=2**,統計上驗不出差異
    (符合 21.7% vs 違反 20.9%)。同一輪驗證裡,另一個看起來更有道理的假說
    (「前 40 秒要端出對比數字」)實測是**反向**的,見 _long_no_early_contrast。
    所以這條保留的理由是「連續三句節目預告 + 頻道自我介紹佔掉 20 秒」本身就是缺陷,
    而且它只命中 10% 的片(誤殺面小);**不是**因為數據證明它有效。
    如果之後累積到 n>15 仍看不出差異,就該把它拿掉。

    ## 判準:為什麼看 60~300 字而不是從頭看
    「今天我們要拆解一檔個股」當**鉤子第一句**是合法的(勤誠那支就這樣開場,
    留存正常)。違規的是鉤子講完之後**還在預告**。前 60 字≈前 15 秒=鉤子區,
    跳過不查;60~300 字≈15~50 秒,那段本來就該是內容。
    命中 2 句以上才判違規——單獨一句可能是合法的承接。
    """
    import re as _re
    zone = (voice_text or "")[60:300]
    pats = (r"今天[,，]?\s*我(?:將|要|會)", r"我們將(?:帶你|深入|用)", r"帶你(?:體檢|拆解|看看)",
            r"看完這支影片", r"這支影片(?:會|將|要)", r"接下來我(?:要|會|們要)告訴你",
            r"頻道的目標", r"量化阿森(?:頻道|就用|將用)", r"本頻道(?:用|將|會)",
            r"首先[,，]\s*我們來(?:認識|看看|了解)", r"在今天的[^。]{0,12}(?:系列|影片)中")
    return sum(1 for p in pats if _re.search(p, zone)) >= 2


def _long_fragmented_hook(voice_text):
    """長片開場碎句判定:前兩句只要有一句短於 12 個中文字 = 碎片,回 True(不合格)。

    ## 為什麼(2026-08-11 留存曲線實測)
    近7天觀看最高的台半5425(1744 觀看)開場是:
        「這檔股票。十八年總報酬兩百七十趴。年化七點三趴。」
    三個沒有主詞的數據碎片連發,唸出來像在念報表。該片留存曲線:
        第 17 秒 0.82 → 第 28 秒 **0.46**,一口氣掉 44%,之後再也沒回來。
    近 60 支長片掃描,**53%** 是這種開場(聯亞「這檔股票。」、金像電「金像電。」…)。

    ## 為什麼既有的 gate 全部漏接
    ·_weak_hook 只掛在 Shorts 的重生迴圈,長片那條**完全沒有開場品質檢查**
    ·_weak_hook 的判準是「有沒有數字/衝突詞」——碎句兩者都有,照樣放行
    ·「禁止重述鉤子數字」比對的是「鉤子區 vs 下一段」,碎片在鉤子**內部**,比不出來

    ## 判準
    數字要「長在句子裡」才算完整敘述(例:「台半這檔股票,十八年抱下來總報酬270%」),
    自己斷成一句就是碎片(例:「十八年總報酬兩百七十趴。」)。
    12 字是分界:低於這個長度的中文句子講不完一件有主詞的事。
    只看前兩句——開場之後的短句是正常節奏,不該擋。
    """
    import re as _r
    body = (voice_text or "").replace("\n", " ").strip()
    if not body:
        return False
    parts = [p for p in body.split("。") if p.strip()]
    if not parts:
        return False

    # 判準:看**開場前 40 個中文字裡斷了幾句**。
    # 碎句的本質是「短時間內斷太多次」,不是單一句子多短——
    # 「這檔股票。十八年總報酬兩百七十趴。年化七點三趴。」40字內斷 3 次以上;
    # 好開場「同樣是定期定額0050,光是扣款日的選擇,十年後竟然可以差到一臺機車的錢。」
    # 同樣 40 字內只斷 1 次。
    # ⚠️ 這個判準取代過先前兩版(純字數門檻、語意詞表):
    #    ·純字數會誤殺「但你可能撐不過中間那段」(11字但是好句)
    #    ·語意詞表會放行「你知道嗎。」(含「你」卻仍是碎句)
    #    斷句密度直接對應「唸起來像不像念報表」這個真實症狀,不需要猜語意。
    head40 = ""
    for ch in body:
        head40 += ch
        if len(_r.findall(r"[一-鿿]", head40)) >= 40:
            break
    breaks = len([p for p in head40.split("。") if p.strip()])
    return breaks >= 3


def _take_hook(sents, min_chars=45, max_sents=6):
    """從原稿句子取出「一個完整的開場鉤子」——依中文字數取,不是盲目取前 3 句。

    ## 為什麼(2026-08-11 留存實測)
    舊寫法 `"".join(sents[:3])` 假設「前 3 句 = 一個完整鉤子」,但 LLM 常把開場寫成
    短碎句,於是取到的是三個沒有主詞的數據片段。實例(台半5425,近7天觀看最高 1744):
        「這檔股票。十八年總報酬兩百七十趴。年化七點三趴。」
    這串當開場唸出來,而下一句又把同樣的數字用阿拉伯數字重講一次。
    該片留存曲線:第 17 秒 0.82 → 第 28 秒 **0.46**(一口氣掉 44%),正好落在這裡。
    全庫掃描:近 40 支長片有 **9 支(24%)** 是這種碎句開場。

    ⚠️ 這也是為什麼先前「禁止重述鉤子數字」的規則沒攔到——那條比對的是
    「鉤子區 vs 下一段」,而這裡是**鉤子自己內部就是碎片**,比對不出來。

    取法:累積到 min_chars 個中文字才收手,最多不超過 max_sents 句
    (避免遇到超長段落時把整段正文都吃進鉤子)。
    """
    if not sents:
        return ""
    import re as _re
    out, n = [], 0
    for s in sents[:max_sents]:
        out.append(s)
        n += len(_re.findall(r"[一-鿿]", s))
        if n >= min_chars:
            break
    return "".join(out).strip()


def _clean_narration(text):
    """把 LLM 的「文件式」輸出洗成「說出來會順」的旁白。只清形式,不動內容。"""
    if not isinstance(text, str) or not text:
        return text
    t = text
    t = _STAGE_RE.sub("", t)                              # (轉場語氣) 這類舞台指示
    t = _META_RE.sub("", t)                               # 講稿結構外洩
    t = _PLEA_RE.sub("", t)                               # 空泛「一定要看到最後」(24x 留存懸崖)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t, flags=re.S)    # **粗體** → 粗體(內容保留)
    t = re.sub(r"__(.+?)__", r"\1", t, flags=re.S)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)           # ## 標題
    t = re.sub(r"(?m)^\s{0,3}[-*•]\s+", "", t)       # - 條列
    t = re.sub(r"(?m)^\s{0,3}([1-5])[.、)]\s+",
               lambda m: _LIST_NUM[m.group(1)], t)        # 1. → 第一，
    t = re.sub(r"(?m)^\s{0,3}\d{1,2}[.、)]\s+", "", t)  # 其餘編號直接拿掉
    t = t.replace("→", "，").replace("⇒", "，").replace("~", "到")
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _fix_artifacts(text):
    if not isinstance(text, str):
        return text
    for a, b in _ARTIFACT_FIXES.items():
        if a in text:
            text = text.replace(a, b)
    return text


# loop 結尾硬性保底(完播工程 2026-07-14):HOOK_RULES ④已提示 LLM「結尾呼應開頭數字,誘導
# 重看」(頻道最高完播片曾被重看到 200~372%,loop=實測最大流量槓桿之一),但跟訂閱鉤一樣是
# prompt 裡的軟規則、遵從度約半——診斷(ffmpeg 抽樣+人眼看片)也看到多支片開頭丟數字、結尾
# 卻只有平鋪 CTA,完全沒呼應。改法同訂閱鉤保底:LLM 有自己呼應開頭就不動;漏掉才在結尾
# (訂閱鉤之前)把開頭那句原句嵌回結尾,保證每片都有 loop 誘因。
# 注意:配音友善規則要求數字寫成中文口語(「八十一萬」而非「81萬」、「百分之八」而非「8%」),
# 靠 \d+ regex 抓數字在真實 voice_text 上幾乎抓不到——改抓「開頭第一~二個分句」當可逐字
# 引用的鉤子片段,不依賴數字格式,只要開頭有實質內容就能呼應。
_LOOP_HOOK_POOL = [
    "不確定的話，回開頭再聽一次「{hook}」，答案其實早就藏在裡面。",
    "把這句記起來：「{hook}」，回頭重聽一次開頭，你會發現破綻早就埋好了。",
    "這就是「{hook}」的答案，回開頭對一次你剛剛猜的，看你差多少。",
    "如果這個結果讓你意外，回開頭再聽一次「{hook}」，一切從第一句就寫好了。",
]
_LOOP_SENT_SPLIT_RE = re.compile(r"[。！？.!?]")


def _ensure_loop_hook(text, key):
    """LLM 漏 loop 呼應時,結尾補一句把開頭那個鉤子片段原句嵌回去(有呼應就不動)。
    key 用來輪替措辭。開頭抓不到有意義片段(太短/空)就不硬湊,直接放行。"""
    if not isinstance(text, str) or not text.strip():
        return text
    parts = [p.strip() for p in _LOOP_SENT_SPLIT_RE.split(text) if p.strip()]
    if not parts:
        return text
    hook = parts[0]
    if len(hook) < 4 and len(parts) > 1:  # 第一分句真的太短才併第二句,避免破壞可辨識度
        hook = (hook + parts[1]).strip()
    hook = hook[:26]  # 太長截斷,避免補句本身變超長
    if len(hook) < 4:
        return text  # 開頭太短抓不到有意義的鉤子片段,不硬湊
    check_key = hook[:6]
    # 完播節奏修復同批順手修(2026-07-15,獨立驗收抓到本保底 4 支非系列片 2 支沒補到、
    # 50% 失效):舊版在「整段扣掉開頭 60 字後的全文」找 check_key,但金融腳本整支都圍
    # 繞同一主題,中段自然會重複出現同組詞彙(不是刻意呼應開頭)——check_key 只有 6 字,
    # 太容易被中段的巧合重複命中,誤判成「已呼應」就跳過,實際結尾根本沒有真正回開頭的
    # 那句。根因不是產出時序也不是條件分支漏判,是「找的範圍」不對:語意上「結尾呼應開頭」
    # 該只看結尾附近,不是全文找有沒有巧合重複。改法:窗口收斂到「最後 ~140 字」(且不早於
    # 第 60 字,避免短文本時尾段窗口反吃到開頭本身、自己比對自己)。
    tail_start = max(60, len(text) - 140)
    tail = text[tail_start:]
    if check_key in tail:
        return text  # 結尾已呼應開頭(逐字或近似),尊重原文不重複
    import hashlib
    i = int(hashlib.md5((key or "x").encode("utf-8")).hexdigest(), 16) % len(_LOOP_HOOK_POOL)
    return text.rstrip() + " " + _LOOP_HOOK_POOL[i].format(hook=hook)


# 訂閱鉤硬性保底:0.29% 轉換是頻道最大瓶頸,訂閱鉤是軟規則(LLM 遵從度約半)。
# LLM 有自然寫訂閱鉤就用它(不動);漏掉才在結尾補一句(依 title 輪替避免全一樣),保證每片 100% 有。
# 🔴 2026-07-17 重寫(2026-07-13 已診斷對但只修了 tw_lab 池=2% 產出，這裡是吃 98% 的一般池)：
# 實測 120 支 voice.txt：Shorts 片尾只有 38% 出現「訂閱」二字，62% 講「追蹤」——那是 IG 語彙，
# YouTube 的按鈕上寫的是「訂閱」，觀眾聽完不知道要按哪。舊四句還全用「不然演算法不會再推你」
# 這種平台操弄威脅語氣當理由，而不是內容價值。
# (旁證：長片有 89% 明講「訂閱」、轉換也明顯較高——但那組統計 n 小且被單片主導，
#  只當方向參考，別當因果定論；改用「訂閱」本來就是錯字級的低級失誤，不需要統計背書。)
# 新池三要素(比照已驗證的 _TW_LAB_SUB_HOOK_POOL)：①明講「訂閱」二字 ②理由=具體價值承諾
# 而非威脅 ③講得出可辨識的產出。句數 4→6 降低罐頭感(實測 19% 逐字重複)。
_SUB_HOOK_POOL = [
    "下一支我繼續拿回測拆神話，訂閱才收得到，不用自己回來找。",
    "這種『我先幫你試、你不用送死』的實測我會一直做，訂閱一下，下支數字出來直接推給你。",
    "訂閱我，每支都是自己跑完回測才敢講，下一個被吹爆的策略照樣拆給你看。",
    "喜歡這種拿數據拆迷思的，訂閱之後，下一組真實數字公布時會主動通知你。",
    "想知道下一個神話是真是假？訂閱起來，我跑完回測第一時間告訴你。",
    "訂閱量化阿森，下支一樣先自己踩過坑，再把數字攤開給你看。",
]
# 🔴 收緊成只認「訂閱」二字(比照 _TW_LAB_SUB_CUES)。舊 cues 把「追蹤/關注/別錯過」都算通過，
# 等於對那 62% 只講追蹤的片，這道保底 gate 根本沒開——這正是診斷抓到的問題本身。
_SUB_CUES = ("訂閱",)

# 台股真相實驗室 franchise 專屬訂閱鉤池(2026-07-13 訂閱轉換診斷落地)：
# 診斷發現全站頂流片(588~855 觀看)結尾清一色只講「追蹤」、理由是「不然演算法不會再推你」
# ——語彙跟 YouTube 按鈕本身寫的「訂閱」對不上、理由是平台操弄語氣不是內容價值。
# 這個池子①一律明講「訂閱」二字②理由=系列已排好一整組真回測、訂閱才收得到下一組③點名系列名稱。
_TW_LAB_SUB_HOOK_POOL = [
    "台股真相實驗室這系列我已經排好一整組台股真回測要拆，訂閱才會在下一組數字公布時通知你。",
    "這是台股真相實驗室的固定企劃，一集一組真回測，訂閱就等於訂閱到下一組數字，不會漏掉。",
    "喜歡這種台股數據拆解，訂閱一下，台股真相實驗室下一集還有一組數字等你猜。",
    "台股真相實驗室還有好幾組台股迷思沒拆，訂閱之後每集都會主動推給你，不用自己來找。",
]
# 台股真相實驗室要求的是「訂閱」這個明確動作字樣，比一般片的 _SUB_CUES(含「追蹤」等鬆散同義詞)
# 更嚴格——正是診斷抓到的問題本身(只講追蹤、不講訂閱)，所以這裡故意不接受「追蹤」代替判定通過。
_TW_LAB_SUB_CUES = ("訂閱",)


# LLM 講錯字時的定點修正表(2026-07-17)：YouTube 按鈕上寫的是「訂閱」，講「追蹤／關注」
# 是 IG／抖音語彙。這裡**只列明確的 CTA 片語**，不做通則替換——「持續追蹤這個數字」「追蹤這檔股票」
# 是正常用法，通則替換會改出「持續訂閱這個數字」這種語意錯誤。表外的寫法(如「追蹤頻道」)
# 不匹配就走附加保底，fail-safe。
_CTA_WORD_FIXES = (
    ("先追蹤", "先訂閱"), ("記得追蹤", "記得訂閱"), ("追蹤我", "訂閱我"),
    ("追蹤一下", "訂閱一下"), ("追蹤起來", "訂閱起來"), ("快追蹤", "快訂閱"),
    ("追蹤量化阿森", "訂閱量化阿森"), ("關注我", "訂閱我"), ("記得關注", "記得訂閱"),
)


def _ensure_sub_hook(text, key, pool=None, cues=None):
    """LLM 漏訂閱鉤時結尾補一句(有寫就不動);key 用來輪替措辭。
    pool/cues 給 franchise 專屬需求覆寫(如台股真相實驗室要求字面一定要有「訂閱」二字)。"""
    if not isinstance(text, str) or not text.strip():
        return text
    _pool = pool or _SUB_HOOK_POOL
    _cues = cues or _SUB_CUES
    # 只掃尾段(比照 _ensure_loop_hook 的 tail 寫法)：訂閱鉤的作用位置在結尾，
    # 掃全文會被中段順口提到的「訂閱」誤判成已寫、於是不補(實測誤判 2 例)。
    tail_start = max(0, len(text) - 140)
    tail = text[tail_start:]
    if any(c in tail for c in _cues):
        return text  # 結尾已有訂閱鉤,尊重原文不重複
    # 🔴 尾段講了「追蹤/關注」卻沒講「訂閱」＝**講錯字**，不是漏講。此時**改寫該詞**優於附加一句：
    # 附加會產出「…記得追蹤我，下支見。 訂閱起來，我跑完回測第一時間告訴你。」兩句 CTA 並存，
    # 冗長又語意打架(實測 33% 的稿會落入這條路徑)。prompt 已同步硬性要求明講「訂閱」，
    # 這條路徑會隨新稿自然縮小，屬過渡期修補。
    fixed_tail, hit = tail, False
    for wrong, right in _CTA_WORD_FIXES:
        if wrong in fixed_tail:
            fixed_tail, hit = fixed_tail.replace(wrong, right), True
    if hit:
        return text[:tail_start] + fixed_tail
    import hashlib
    i = int(hashlib.md5((key or "x").encode("utf-8")).hexdigest(), 16) % len(_pool)
    return text.rstrip() + " " + _pool[i]


def make_one(kind, no_render=False, topic_override=None, script_override=None):
    _ex = existing_titles()
    # script_override:稿子已經確定性組好(EP.0 開播預告,見 ep0_engine.py),跳過 LLM 直接進後段
    # (配音/渲染/發布共用同一條路)。搭 topic_override 一起傳,下面的重生型 gate 都被
    # `not topic_override` 守著會自動跳過——EP.0 刻意比正常長片短、KPI 是訂閱不是完播,
    # 不該被長片長度/標題重複那幾道 gate 重生掉。
    d = dict(script_override) if script_override else call_claude(kind, _ex, topic_override)
    # 🔴 個股體檢系列鎖題(2026-07-15 實跑抓到嚴重事故)：make_one 所有品質 gate 的「重生」都是
    # 再 call_claude 一次,而 call_claude 沒帶 topic_override 時=pull_topic 抽**下一題**——
    # 系列題標題共用「個股體檢EPn…」骨架是刻意品牌,skeleton_dup 把它當洗版觸發重生,一口氣
    # 燒掉 EP2/EP3/EP4(標 used 沒產出),最後產出 EP5,集數大亂。修法：第一次抽到體檢題後,
    # 把該題鎖進 topic_override,之後所有 gate 重生都重寫**同一集**(call_claude 的 checkup
    # override 分支用題庫派發框架,不會誤套時事語氣)。
    _is_ck = bool(d.get("_is_checkup"))
    if _is_ck and not topic_override and d.get("_ck_topic"):
        topic_override = d.get("_ck_topic")
    # 硬防近似重複：標題與既有太像就重生(時事 topic_override 不擋)；連續 3 次都重複則跳過
    # 個股體檢豁免標題 gate：系列骨架天生相似(每集不同標的、數字種題時已溯源驗證,無洗版風險)；
    # 內文品質 gate(長度/密度/跑題/弱鉤)不豁免,照走(重生時已鎖同一題)。
    if _is_ck:
        pass
    elif not topic_override:
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
               or _self_repeated_metaphor(d.get("voice_text", ""))   # 片內同一比喻講兩次=灌水
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
    # 這裡做兩層 gate 把關：①長度不達標(<2000字 或 預估<8分,偶發波動) ②病灶A資訊密度不達標
    # (字數達標但其實是同一組數字/片語灌水重複撐出來的、或整段跑題)——任一項不達標就整支重生
    # (最多4次,每次都是一支已深寫+已自癒的新草稿);4 次都不達標就 **fail-closed 不輸出這支**
    # (return None),絕不把短長片/灌水長片冒充「真8-10分鐘資訊密度長片」發出去
    # (寧可今天少一支長片,也不砸招牌，誠信優先於產量)。
    # (舊 _expand_long_script 整篇重寫易縮水且繞過自癒,已從長片路徑移除;函式保留供他處備援。)
    if kind == "long" and not topic_override:
        def _long_bad(_d):
            """長片四道 gate(任一不過就重生)：①長度 ②資訊密度(灌水重複) ③主題鎖定(後段跑題)
            ④開場碎句(2026-08-11 新增,見下)。回傳不合格原因字串，合格回空字串。"""
            _v = _d.get("voice_text", "")
            if _long_underlength(_v):
                return "長度不足"
            if _long_content_padding(_v):
                return "資訊密度不足(同組數字/片語重複灌水撐時長)"
            if _long_topic_drift(_v, _d.get("title", "")):
                return "主題跑題(後段整段變成另一支片的主題)"
            # ④ 開場碎句(2026-08-11 留存曲線實測,目前量到最大的完播殺手)
            # 台半5425(近7天觀看最高 1744)開場:「這檔股票。十八年總報酬兩百七十趴。年化七點三趴。」
            # 留存 17秒 0.82 → 28秒 **0.46**,一口氣掉 44%。近60支長片有 53% 犯這條。
            # ⚠️ 為什麼長片一直沒擋到:_weak_hook 只掛在 Shorts 那條重生迴圈,
            #    長片這裡原本**完全沒有開場品質檢查**,碎句因此一路通到發布。
            if _long_fragmented_hook(_v):
                return "開場碎句(前兩句有短於12字的無主詞碎片,唸起來像念報表)"
            # ④b 鉤子之後還在鋪陳(2026-08-19 留存曲線實測:第 15~25 秒走掉一半,
            # 而鉤子本身守得住 0.93/0.83 —— 死在後面連續三句節目預告+頻道自我介紹)。
            if _long_preamble(_v):
                return "鉤子後仍在鋪陳(節目預告/頻道自介佔掉15~40秒,實測留存斷崖就在這)"
            # ④c 期間偷換(2026-08-20:64 支已發布片中招)。個股體檢的 long_horizon 是
            # 20 年、three_way 是 10 年,拿前者的個股報酬配後者的 0050 報酬寫「同期」,
            # 數字都真但期間錯,效果是**低估 0050**——正好在觀眾最會檢查的地方出錯。
            if _long_mixed_period(_v):
                return "期間偷換(拿20年個股報酬配10年0050報酬寫『同期』,講0050對照時必須標明年數)"
            # ⑤ 開場罐頭錯位(2026-08-12 抓到:高力8996 體檢片開場逐字抄了 playbook 示範句
            # 「你的網格機器人…」——與主題無關=跨片重複的罐頭簽名(YPP inauthentic 風險)
            # +幣圈詞開場(留存實測毒藥)。開場 60 字含幣圈工具詞而標題沒有 → 重生。
            _t60 = _v[:60]
            _ttl = _d.get("title", "")
            # ⑥ 正文散撒風險 hedging(2026-08-13):留存實測 hedging 句是全片掉人最快的
            # 段落型態(1.60x),規則ⓕ已要求「片尾一句就好」但 prompt 遵從度約半——實測
            # 新批仍有 3 句散在正文。用 gate 不用文字手術(重生零毀損風險):正文 10%~80%
            # 區間出現 >1 句免責樣板 → 重生。(片尾的必須保留,不在檢查區間。)
            _mid = _v[int(len(_v) * 0.10):int(len(_v) * 0.80)]
            _HEDGE = ("風險承受能力", "務必評估", "自行評估風險", "不構成投資建議",
                      "投資前請", "並自行承擔")
            _hn = sum(_mid.count(h) for h in _HEDGE)
            if _hn > 1:
                return f"正文散撒風險hedging({_hn}句在10%~80%區間,留存殺手1.60x,集中片尾一句即可)"
            _CRYPTO_FAM = ("網格", "機器人", "bot", "比特幣", "BTC", "加密", "派網")
            # 標題側額外認「AI選股/神器」:實測「AI選股神器慘賠60%」片開場講「AI選股機器人」
            # 完全切題,但標題不含機器人二字——家族要含工具的同義題面詞,否則誤傷。
            _TITLE_FAM = _CRYPTO_FAM + ("AI選股", "神器", "自動交易")
            if any(k in _t60 for k in _CRYPTO_FAM) and not any(k in _ttl for k in _TITLE_FAM):
                return "開場罐頭錯位(開場含幣圈工具詞但標題主題無關,疑逐字抄示範鉤)"
            return ""
        _lk = 0
        # 每次重生都是一次完整的 LLM 大呼叫(約 US$0.01、耗時數分鐘)。這些迴圈原本
        # **完全不記錄是哪一道閘門觸發的**——實測 `--long 1` 連燒 4 次大呼叫、
        # 每次都產出 2,000~3,000 字的合格長稿,卻始終沒有成品,而 log 一片空白。
        # 先讓它可見:記下每次重生的原因與次數,才知道是哪一道 gate 在過度開火。
        while _long_bad(d) and _lk < 4:
            _lk += 1
            log_ops("補產·重生", f"A4長片第{_lk}次重生:{_long_bad(d)}｜{d.get('title','')[:20]}")
            d = call_claude(kind, _ex, topic_override)
        _why = _long_bad(d)
        if _why:
            _n = _long_chinese_chars(d.get("voice_text", ""))
            log_ops("補產部門", f"⛔ A4長片重生4次後仍{_why}(約{_n}字),fail-closed不輸出假長片:{d.get('title','')[:24]}")
            print(f"[skip] long {_why}({_n}字),fail-closed 不輸出:{d.get('title','')[:24]}")
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
            _r = ("結尾與近期雷同" if _ending_too_similar(d.get("voice_text", ""), _recent_ends_l)
                  else "內文與近期雷同" if _body_too_similar(d.get("voice_text", ""), _recent_bodies_l)
                  else "命中濫用比喻")
            log_ops("補產·重生", f"A1b長片第{_lc}次重生:{_r}｜{d.get('title','')[:20]}")
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
    # loop 結尾硬性保底(完播工程 2026-07-14):只對非系列 Shorts 補——EP/台股真相實驗室
    # 已有自己的「下集懸念」續集鉤(角色不同,不疊加);長片節奏不同,loop 重播是 Shorts feed
    # 專屬機制(90.9% 流量來自 Shorts feed),不套用長片。要在訂閱鉤之前補,讓結尾順序是
    # 「呼應開頭數字→訂閱鉤」。
    # ⚠️ 2026-07-17 認知修正:loop/完播工程買到的是**觀看**不是訂閱(實測完播 80-101% 的
    # 14 支片 = 0 訂閱)。這段保底仍值得留(Shorts 的曝光靠它),但別再期待它帶訂閱。
    if kind == "short" and not d.get("_is_ep") and not d.get("_is_tw_lab"):
        d["voice_text"] = _ensure_loop_hook(d.get("voice_text", ""), d.get("title", ""))
    # 訂閱鉤硬性保底:LLM 漏掉就結尾補一句(直攻 0.29% 轉換瓶頸;有寫就不動)
    # 台股真相實驗室要求字面一定要有「訂閱」二字(比一般片的鬆散判定更嚴格,見診斷根因)。
    if d.get("_is_tw_lab"):
        d["voice_text"] = _ensure_sub_hook(d.get("voice_text", ""), d.get("title", ""),
                                            pool=_TW_LAB_SUB_HOOK_POOL, cues=_TW_LAB_SUB_CUES)
    else:
        d["voice_text"] = _ensure_sub_hook(d.get("voice_text", ""), d.get("title", ""))
    # 常青搜尋流量修復(2026-07):標題/旁白都定案後才做 SEO 加值(雙軌標題+描述首段+精準tags),
    # 確保 seo_suffix 誠信驗證吃到的是「最終會發布的旁白」。三步驟各自 fail-open,見 apply_seo_uplift。
    d = apply_seo_uplift(d)
    # 確定性安全網(2026-07-24):長片絕不帶 #Shorts——寫檔前的唯一總入口後、切 slug 前機械剝除,
    # 就算 LLM 沒遵守 prompt 的「長片嚴禁 #Shorts」也擋得掉(記憶:別只靠 LLM 遵守,加確定性防線)。
    # 只剝 shorts/short 標籤,其餘可搜尋 tags 原樣保留;短片不動(它本該掛 #Shorts)。
    if kind == "long":
        d["hashtags"] = [h for h in (d.get("hashtags") or [])
                         if str(h).lstrip("#").strip().lower() not in ("shorts", "short")]
    # 個股體檢連載:標題定案後、切 slug 前,確定性正規化成「個股體檢{鉤子}」前綴式且無 EP 數字。
    # EP 號改由發布時按已發布集數 max+1 掛(daily_publish._apply_checkup_ep),故產製端不留號→片頭卡/
    # slug 皆無編號、且都帶系列名(slug 帶系列名才進得了播放清單連播)。發布時再掛號、改後綴式公開標題,
    # 三處(YT標題/封面/slug衍生)一致、且「發一支進一號、永不跳」。見 _normalize_checkup_title。
    if d.get("_is_checkup") and d.get("title"):
        # 抽本集標的 code/name(確定性,同 _ck_setup_block 來源)給標題醒目化;取不到就退回原正規化
        _ck_tp = d.get("_ck_topic") or {}
        _ck_code = _checkup_extract_code(str(_ck_tp.get("fact_key", ""))) if _ck_tp else None
        _ck_name = None
        if _ck_code:
            try:
                _cd = json.loads(STOCK_CHECKUP_FACTS.read_text(encoding="utf-8"))
                _ck_name = (_cd.get("by_code") or {}).get(_ck_code, {}).get("name")
            except Exception:  # noqa: BLE001
                pass
        d["title"] = _normalize_checkup_title(d["title"], code=_ck_code, name=_ck_name)
    slug = slugify(d["title"], prefix)
    if (OUT / f"{slug}.voice.txt").exists() or (OUT / f"{slug}.mp4").exists():
        # 撞名有兩種完全不同的情況,不能一律改名硬產:
        #  ①【已經有成品】同一個標題早就產完過 → 再產一支就是同片兩份。2026-07 實錄:
        #    「S_0050一次Allinvs每月三千十年差434臺股回」原版 + 3501 + 9235 = 同一支片三份。
        #    → 乾淨跳過不產。最後一道防線偵測到「已產過」就該停手,不是產第二份。
        #  ②【上次做到一半死掉】.voice.txt 還在但沒有成品(TTS/渲染失敗) → 這是呼叫端
        #    `for t in range(2)` 重試路徑的正常狀態(EP/台股真相實驗室/時事/EP.0 都鎖同一題重試,
        #    標題必然一樣)。改名讓重試寫得出新檔;改成跳過會讓這些重試永遠失敗。→ 維持原本改名。
        # 「成品」的定義隨模式不同:--no-render(雲端/正式排程走這條)只產到 .mp3,渲染是之後
        # hybrid_render 的事,故有 .mp3 就算完成;本機全渲染模式才看 .mp4。
        try:
            if no_render:
                _done = (OUT / f"{slug}.mp3").exists()
            else:
                _mp4 = OUT / f"{slug}.mp4"
                _done = _mp4.exists() and _mp4.stat().st_size > 100 * 1024
        except Exception:  # noqa: BLE001
            _done = False  # 判不出來就當沒成品 → 沿用舊行為改名,fail-open 不擋產線
        if _done:
            # ⚠️ 前綴是必要的:決策中心健康掃描只認 ⚠️/FAIL/失敗/錯誤/FATAL(見下方跳過補產的說明)
            log_ops("補產部門", f"⚠️ 同標題已有成品,跳過不產第二份:{slug[:30]}")
            print(f"[skip] 同標題已有成品，跳過不產第二份：{slug}", file=sys.stderr)
            return None
        slug = f"{slug}{int(time.time()) % 10000}"
    # 落檔前洗掉「文件式」殘留(見 _clean_narration 的說明)。voice.txt 就是 TTS 的輸入,
    # 這裡有什麼就念什麼——實測 419 支已產旁白裡 10.3% 帶 markdown 清單/粗體,
    # 還有幾支直接把「(以中文口語念出)」「講完開場鉤子」念給觀眾聽。
    # 寫進 d 再落檔,讓 build_md 產的 .md 與 voice.txt 內容一致(字幕/選圖都吃得到乾淨版)。
    d["voice_text"] = _clean_narration(d.get("voice_text", ""))
    if slug.startswith("L_"):
        # 長片專用:在 35% 處補一句訂閱鉤(見 _insert_mid_sub_hook 的實測說明)。
        # 短片太短、結尾 CTA 幾乎人人聽得到,不需要。
        d["voice_text"] = _insert_mid_sub_hook(d["voice_text"], slug)
    # 🔴 2026-08-17 切片片的數字必須對照**它自己的來源長片**,不能只對照全事實庫。
    # 事故:B41_vS97LO8 說「聯鈞定期定額報酬 -37%」(長片實為 +656.4%,-38.3% 是回撤),
    # 而 fact_source_guard 判定「有來源」放行——因為事實庫有幾千個數字,任何兩位數幾乎
    # 都命中,那道閘只擋得住離譜數字,擋不住**張冠李戴**。切片場景有精確解:切片是從
    # 某支長片切出來的,它的每個數字都該在那支長片裡。這裡把來源長片 slug 落成 sidecar,
    # 讓發布前的稽核(audit_funnel_shorts.py)能精確比對,不必再靠標題模糊配對。
    # ⚠️ make_one 的作用域裡**沒有** topic 變數(它在 call_claude 內部),第一版寫成
    # `(topic or {}).get("parent")` 會 NameError 被 try 吞掉=永遠不寫 sidecar 的靜默失效。
    # 改由 call_claude 把來源 slug 放進 d["_parent_slug"] 帶出來。
    try:
        _par = d.get("_parent_slug") or ""
        if _par:
            (OUT / f"{slug}.parent.txt").write_text(str(_par), encoding="utf-8")
        _arm = d.get("_ab_arm") or ""
        if _arm:
            (OUT / f"{slug}.ab.txt").write_text(str(_arm), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
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
        if mp3_ok and d.get("_is_tw_lab"):
            _bump_tw_lab(d, slug)  # 台股真相實驗室正片產出成功 → 遞增系列引擎
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
    if ok and d.get("_is_tw_lab"):
        _bump_tw_lab(d, slug)  # 台股真相實驗室正片產出成功 → 遞增系列引擎
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
    ap.add_argument("--tw-lab", action="store_true",
                     help="立刻產 1 支「台股真相實驗室」系列正片（由 tw_lab_engine 依序派下一組真回測事實，繞過題庫）")
    ap.add_argument("--ep0", default=None, metavar="SERIES",
                     help="立刻產 1 支系列開播預告 EP.0（確定性模板,不走 LLM;系列代號見 ep0_engine.py --list）")
    ap.add_argument("--belief", default=None, metavar="ID",
                     help="立刻產「台股流言終結者」迷思終結片（確定性模板,不走 LLM;ID 見 belief_buster_engine.py --list;"
                          "填 all 產全部 3 支）")
    args = ap.parse_args()
    if getattr(args, "format_focus", False):
        os.environ["FORMAT_FOCUS"] = "1"  # D2:本批短片走最強格式模板

    # 系列開播預告 EP.0：實測全頻道訂閱轉換最高的格式(3-5%,比 Shorts 高 50-80 倍)。
    # 稿子由 ep0_engine 確定性組好(不走 LLM,故不需 LLM 金鑰)，承諾的數字全部由題庫真實存量
    # 算出來；存量不足 build_script 會 fail-closed 回 None → 這裡直接中止，不產空頭支票。
    if getattr(args, "ep0", None):
        import ep0_engine
        _d0 = ep0_engine.build_script(args.ep0)
        if not _d0:
            return 2  # 理由已由 ep0_engine 印到 stderr(未知系列 / 存量不足)
        _tov = ep0_engine.build_topic(args.ep0)
        slug_made = None
        for t in range(2):
            try:
                slug_made = make_one("long", no_render=args.no_render,
                                     topic_override=_tov, script_override=_d0)
                if slug_made:
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"[err EP.0 第{t+1}次] {exc}", file=sys.stderr)
        _nm = ep0_engine.SERIES[args.ep0]["name"]
        log_ops("開播預告", f"{'已產出' if slug_made else '⚠️ 失敗'}：{_nm} EP.0")
        print(f"[{'ok' if slug_made else 'FAIL'}] {_nm} EP.0：{_d0['title'][:40]}")
        print(f"[存量佐證] {_d0['_ep0_inventory']['detail']}")
        # 汰舊(2026-08-11):EP0 的「已播出 N 集」是產片當下快照,舊版未發布=數字過期=
        # 發出去對觀眾說謊。實測 3 支 stale checkup EP0(13集/28集/…)疊在庫存 11 天。
        # 產新**成功後**才汰舊(失敗保留舊版,寧stale勿斷貨);只動未發布(不在 ledger)、
        # 搬進 _retired_ep0/ 可還原,不是刪除。
        _sig = ep0_engine.SERIES[args.ep0].get("slug_sig")
        if slug_made and _sig:
            try:
                _led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _led = None   # ledger 讀不到就不汰舊(分不清誰已發布,寧可不動)
            if _led is not None:
                _ret = OUT / "_retired_ep0"
                # ⚠️ 不可用 name.split(".") 取 slug:標題帶小數(「5.7年報酬」)slug 就含點。
                _olds = {p.name[:-len(".voice.txt")] for p in OUT.glob(_sig + "*.voice.txt")}
                _olds |= {p.name[:-len(".mp4")] for p in OUT.glob(_sig + "*.mp4")}
                for _old in _olds:
                    if _old == slug_made or _old in _led:
                        continue
                    _ret.mkdir(exist_ok=True)
                    for _ext in (".md", ".voice.txt", ".mp3", ".mp4", ".jpg", ".png"):
                        _p = OUT / (_old + _ext)
                        if _p.exists():
                            _p.rename(_ret / _p.name)
                    print(f"[EP0汰舊] 已退役過期版:{_old[:44]}")
                    log_ops("開播預告", f"汰舊過期 EP0:{_old[:40]}")
        if slug_made and args.publish and not args.no_render:
            _publish_now(slug_made)
        return 0 if slug_made else 3

    # 台股流言終結者：立刻產迷思終結片(確定性模板,不走 LLM;每個數字由 belief_buster_engine
    # 從 tw_facts_computed 的真 fact_key 算出、判決由真回測數字決定)。走與 EP.0 完全相同的
    # script_override 路徑(配音/渲染共用同一條既有產線,不另造產線)。存量/事實缺失時
    # build_script 會 fail-closed 回 None → 該支跳過。刻意**不接 --publish**：本 franchise 首批
    # 一律人眼驗過畫面(渲染期假數字/渐进揭露)再由 Carson 定奪發布,不自動上架。
    if getattr(args, "belief", None):
        import belief_buster_engine as bbe
        _bids = bbe.BELIEF_ORDER if args.belief == "all" else [args.belief]
        _made = []
        for _bid in _bids:
            _db = bbe.build_script(_bid)
            if not _db:
                print(f"[FAIL] 台股流言終結者 {_bid}:build_script 回 None(事實缺失/未知迷思)", file=sys.stderr)
                continue
            _tovb = bbe.build_topic(_bid)
            _slug = None
            for t in range(2):
                try:
                    _slug = make_one("long", no_render=args.no_render,
                                     topic_override=_tovb, script_override=_db)
                    if _slug:
                        break
                except Exception as exc:  # noqa: BLE001
                    print(f"[err 流言終結者 {_bid} 第{t+1}次] {exc}", file=sys.stderr)
            _v = (_db.get("_belief_verdict") or {}).get("verdict", "?")
            log_ops("流言終結者", f"{'已產出' if _slug else '⚠️ 失敗'}：{_bid}（判決 {_v}）")
            print(f"[{'ok' if _slug else 'FAIL'}] 流言終結者 {_bid}（判決 {_v}）：{_db['title'][:38]}")
            if _slug:
                _made.append(_slug)
                try:
                    bbe.bump_state(_bid, _slug)
                except Exception:  # noqa: BLE001
                    pass
        print(f"[流言終結者] 完成 {len(_made)}/{len(_bids)} 支：{'、'.join(_made) or '無'}")
        return 0 if _made else 3

    # 台股真相實驗室：立刻產 1 支系列正片，事實由 tw_lab_engine 依贏家關鍵字排序依序派發。
    if getattr(args, "tw_lab", False):
        if not _has_llm_key():
            print("[FATAL] 找不到任一 LLM 供應商金鑰(OPENROUTER/ANTHROPIC/DEEPSEEK/GEMINI/GROQ)。", file=sys.stderr)
            return 2
        import tw_lab_engine
        _tov = tw_lab_engine.build_topic()
        if not _tov:
            print("[FATAL] 台股真相實驗室事實庫是空的(STUDIO/tw_stock_facts.json / tw_facts_computed.json 都讀不到)。",
                  file=sys.stderr)
            return 2
        # 2026-07-19:franchise 已改走長片(tw_lab_engine.FRANCHISE_FORMAT),CLI 一律照題目自帶的 format
        # 走,不再寫死 "short"(否則長片題會被硬產成短片,反而回到換不到訂閱的老路)。
        _tl_kind = _tov.get("format", "short")
        slug_made = None
        for t in range(2):
            try:
                slug_made = make_one(_tl_kind, no_render=args.no_render, topic_override=_tov)
                if slug_made:
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"[err 台股真相實驗室第{t+1}次] {exc}", file=sys.stderr)
        log_ops("台股真相實驗室", f"{'已產出' if slug_made else '⚠️ 失敗'}：{_tov.get('title','')[:40]}")
        print(f"[{'ok' if slug_made else 'FAIL'}] 台股真相實驗室：{_tov.get('title','')[:40]}")
        if slug_made and args.publish and not args.no_render:
            _publish_now(slug_made)
        return 0 if slug_made else 3

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

    # 🔴 2026-07-17 分格式 gate:舊碼 `q >= args.target` 是**不分格式的全批 kill-switch**——
    # 短片堆滿會連長片一起停產,而長片才是稀缺高價值格式(**硬理由**:只有長片算 YPP 的
    # 4,000 watch hours,Shorts 觀看一秒都不計;訂閱轉換長片也明顯較高,但那組統計 n 小
    # 被單片主導、只當方向參考)。
    # 改成各自獨立判斷:短片滿只停短片、長片滿只停長片,兩者都滿才早退。
    # target 依發布配比切(每天發 2短3長,各留約 30 天緩衝):short 40% / long 60%。
    q = queue_size()
    tgt_short = max(1, round(args.target * 0.4))
    tgt_long = max(1, args.target - tgt_short)
    q_short, q_long = queue_size("short"), queue_size("long")
    print(f"目前片庫：{q} 支(短 {q_short}/{tgt_short}、長 {q_long}/{tgt_long}) / 總目標 {args.target}")
    if q_short >= tgt_short and args.shorts:
        print(f"[skip] 短片庫存已達標({q_short}/{tgt_short})，本次不補短片。", file=sys.stderr)
        args.shorts = 0
    if q_long >= tgt_long and args.long:
        print(f"[skip] 長片庫存已達標({q_long}/{tgt_long})，本次不補長片。", file=sys.stderr)
        args.long = 0
    if not args.shorts and not args.long:
        # 🔴 早退必須「叫得出聲」:local_cron.py:199 用 stdout=DEVNULL,早退只 print 到 stdout
        # 會被吃掉、exit 0 被記成「✓ 完成」——2026-07-17 06:07 就是這樣整批歸零卻回報成功
        # (log 顯示啟動與完成同一秒)。故一律同時走 stderr(進 job_stderr.log)與 log_ops
        # (進決策中心),讓「沒產」看得見。
        msg = f"片庫充足（短 {q_short}/{tgt_short}、長 {q_long}/{tgt_long}），本次不補產。"
        print(msg)
        print(f"[skip] {msg}", file=sys.stderr)
        # ⚠️ 前綴是必要的:決策中心的健康掃描只認 ⚠️/FAIL/失敗/錯誤/FATAL 這幾個關鍵字,
        # 訊息不含任何一個就不會被列成異常 = 又是一次「查得到但不會叫」。
        log_ops("補產部門", f"⚠️ 跳過補產（短 {q_short}/{tgt_short}、長 {q_long}/{tgt_long} 皆達標）")
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

    # 台股真相實驗室：每批開跑前先把接下來幾集的真回測事實種進題庫(category=台股真相實驗室)，
    # 讓 pull_topic() 日常補產時能自然抽到本系列，不必每次都靠 --tw-lab 手動觸發。已種過的事實
    # key 不重複種(tw_lab_engine 自己追蹤)，失敗靜默跳過不影響本批正常出片。
    # 2026-07-19:franchise 改走長片(tw_lab_engine.FRANCHISE_FORMAT)後,seed 的是**長片**題並 front
    # 插隊——n 從 6 降到 2,把長片產製名額讓給 Carson 指定「一天一部」的個股體檢連載(d2fca80),
    # 避免 tw_lab 前插把 checkup 每日那部擠掉。每批 2 支 tw_lab 長片攻訂閱已足夠。
    try:
        import tw_lab_engine
        tw_lab_engine.seed_topic_bank(2)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 台股真相實驗室種題略過：{str(exc)[:80]}", file=sys.stderr)

    # P3:本批開跑前設定時事題保底配額(短片/長片各自算;quota=0 時行為與修改前完全相同)
    _set_batch_plan("short", args.shorts)
    _set_batch_plan("long", args.long)
    # 2026-07 台股比重修正:本批開跑前也設定題材桶保底配額(短片/長片各自算,跟時事配額
    # 彼此獨立、互不覆蓋——pull_topic() 內先看時事配額,沒中才看桶配額,兩層可疊加)。
    _set_bucket_plan("short", args.shorts)
    _set_bucket_plan("long", args.long)

    log_ops("補產部門", f"開始補產（庫存 {q}/{args.target}）…")
    # 🔴 2026-07-17 長片先跑:批次被外力中斷時後跑的會全滅——2026-07-16 實錄
    # exit 1073807364(DBG_TERMINATE_PROCESS,疑似電腦睡眠)砍掉整批,當時短片先跑、
    # 長片只成功 2/4。長片是稀缺高價值格式(是 YPP watch hours 的唯一來源、訂閱轉換也較高),
    # 中斷時該優先保住它,故長片先產、短片墊後。
    made = sum(1 for _ in range(args.long) if attempt("long"))
    made += sum(1 for _ in range(args.shorts) if attempt("short"))
    log_ops("補產部門", f"完成 補產{made}支，片庫{queue_size()}支")
    print(f"本次補產 {made} 支，片庫現 {queue_size()} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
