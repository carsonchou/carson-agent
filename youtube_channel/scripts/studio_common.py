# -*- coding: utf-8 -*-
"""studio_common.py — 全部門共用地基（2026-07-02 部門昇華）。

提供三樣所有 LLM 部門統一用的東西：
  1. PERSONA         — 含新定位(怕被割小白×實測避雷·軟性)的共用人設,貼進各部門 prompt。
  2. has_llm_key()   — 任一供應商 key 即可(取代散落的 ANTHROPIC 死關卡)。
  3. evidence_block()— 讀 traffic_signals/quality_scores/completion_signals,產一段
                       「本頻道實證」few-shot 文字,注入任何寫題/寫稿/選題 prompt,
                       讓真數據橫向流動(修好各部門憑空發想的破口)。
純讀檔、零外部相依、防缺檔;import 這支不會有循環相依。
"""
from __future__ import annotations
import json
import os
import random
import re as _re
import threading
import time
from difflib import SequenceMatcher as _SeqMatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"


_PATH_LOCKS: dict = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(p) -> threading.Lock:
    """回傳某路徑的專屬 threading.Lock(同進程內對同檔序列化寫入)。"""
    key = str(p)
    with _PATH_LOCKS_GUARD:
        lk = _PATH_LOCKS.get(key)
        if lk is None:
            lk = _PATH_LOCKS[key] = threading.Lock()
        return lk


# ── 併發安全 JSON I/O(2026-07 修:多支腳本 cron 併發直接 write_text 覆蓋 STUDIO json,
#    寫到一半被別支讀成殘檔→回空→存回小檔→整檔被洗。topic_bank 已中招。統一走這裡治本)──
def save_json_atomic(path, data, keep_bak: bool = True) -> None:
    """原子寫 JSON:先寫 .tmp → os.replace 原子替換,讀者永遠看到完整檔(消除併發寫互毀)。
    keep_bak:覆蓋前把現有好檔備份成 .bak(本機無 backups 安全網的救命)。path 可為 str/Path。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _path_lock(p):  # 同進程內對同檔序列化(消除 thread 級 os.replace 互撞)
        # tmp 帶 pid+thread 唯一化:跨進程併發寫者不共用同一 .tmp(否則 Windows os.replace 互撞)。
        tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if keep_bak:
            try:
                if p.exists() and p.stat().st_size > 2:
                    import shutil
                    shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
            except Exception:  # noqa: BLE001
                pass
        # os.replace 重試+抖動:Windows 下目標檔被別進程讀者/寫者短暫佔用會 PermissionError(WinError32)。
        last = None
        for i in range(10):
            try:
                os.replace(tmp, p)  # 同目錄原子替換
                return
            except PermissionError as e:  # noqa: PERF203
                last = e
                time.sleep(0.05 + random.random() * 0.15 * (i + 1))
        try:  # 徹底失敗:清掉自己的 tmp 別留垃圾,再拋(呼叫端多已有防呆)
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise last


def load_json_safe(path, default=None):
    """讀 JSON;主檔壞掉(併發寫殘/損毀)→退回 .bak;都不行→回 default。
    斷開『讀到殘檔→回空→存回小檔洗掉整檔』的併發資料流失鏈。"""
    p = Path(path)
    for cand in (p, p.with_suffix(p.suffix + ".bak")):
        try:
            if cand.exists():
                return json.loads(cand.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return default


# ── 濫用模板硬禁 + 語意去重(2026-07 止血:news/hotspot/breakout 從即時新聞生成
#    「XX億爆倉·你的網格機器人為什麼還活著」「勝率9X卻虧光·破產機率公式」等套語,
#    繞過題庫去重直接產片、彼此又高度雷同→洗版稀釋頻道、訓練壞演算法、踩 inauthentic。
#    _too_similar(0.82) 去數字後尾巴不同攔不到,故在此做「抽掉幣種/血詞/機構再比」的語意去重)──
BANNED_SKELETONS = [_re.compile(p) for p in (
    r"爆倉.{0,14}(還活|還撐|沒被|為什麼還|怎麼還|還敢|還在)",
    # 換皮救援(獨立驗證找到的縫):換血詞(血洗/崩盤/清算/歸零/暴跌)但保留「生存 clickbait」尾巴=一樣是洗版
    r"(爆倉|血洗|崩盤|清算|歸零|暴跌|狂洩|狂瀉).{0,14}(還活著|憑什麼不死|怎麼沒死|還沒歸零|怎麼還沒死|還敢開|為什麼還活)",
    # 2026-07 成長衝刺補洞:原規則要求「還撐/還活」才算,漏掉裸「撐得住嗎」(無「還」字)這款實測完播殺手
    # (見『X億爆倉…你的網格撐得住嗎』實例,完播僅24-39%)——補上不含「還」的「撐得住」尾巴。
    r"(爆倉|血洗|崩盤|清算|歸零|暴跌|狂洩|狂瀉|空單|空軍).{0,14}(撐得住|撐不住)",
    # 勝率高卻虧:含數字型(9X/8X)與中文型(九成/八成)——原順序「勝率9X」
    r"勝率\s*(9\d|8\d|9成|8成|九成|八成).{0,10}(卻虧|還虧|破產|虧光|還在虧)",
    # 2026-07 成長衝刺補洞:實測發現真實洗版是反過來的順序「87%勝率」(數字在前),原規則漏抓、
    # 導致 2026-07-07 單日 5 支近乎同題「XX%勝率陷阱」互打分散曝光——補反序比對。
    r"(9\d|8\d)\s*%.{0,6}勝率.{0,14}(卻虧|還虧|破產|虧光|還在虧|竟虧|實盤.{0,6}虧)",
    r"破產機率公式.{0,8}(一秒|戳破|暴露|揭|拆穿)",
)]


def _norm_title_dup(t: str) -> str:
    """去數字/標點/空白,保留語意骨架(與 produce_batch._norm_title_dup 同慣例,自帶一份免循環相依)。"""
    return _re.sub(r"[0-9０-９%/、，。！？!?…\s\-_]+", "", t or "")


def _norm_skeleton(t: str) -> str:
    """在 _norm_title_dup 上再抽掉幣種名/血詞/機構名,讓「同骨架不同新聞」的題正規化後撞在一起。
    例:『比特幣暴跌18億爆倉…網格為什麼還活著』與『以太血洗65億爆倉…網格為什麼還活著』→ 同骨架。"""
    t = t or ""
    t = _re.sub(r"比特幣|比特币|BTC|以太坊?|以太幣|ETH|ETF|微策略|MSTR|貝萊德|幣安|Coinbase|Ripple", "", t)
    t = _re.sub(r"爆倉|爆仓|血洗|暴跌|暴漲|暴涨|歸零|归零|清算|爆雷|狂洩|狂掃|崩盤|崩千點|狂瀉|逃亡", "", t)
    return _norm_title_dup(t)


def is_banned_skeleton(title: str) -> bool:
    """標題是否命中被濫用的洗版骨架(硬禁,Carson 定奪直接砍)。"""
    return any(p.search(title or "") for p in BANNED_SKELETONS)


# ── 事件識別維度(P3 破局計畫:_norm_skeleton 抽掉幣種+血詞後,「不同事件同動作」
#    如『BTC-ETF-上市』vs『BTC-暴跌』會塌縮成同一骨架被 topic_gate 誤判重複,連帶吃掉
#    trend_hijack 改寫題。修法:粗分類新聞事件屬性當第二維度——兩者都有明確且不同的事件標籤
#    時不視為重複(即使去骨架後文字相似);同一事件(標籤相同或雙方都無標籤)才繼續比骨架相似度,
#    真正的『同事件同句式洗版』(如換血詞的爆倉還活著)仍會被擋 )──
_EVENT_CATS = (
    ("EVT_LISTING", r"上市|掛牌|通過|核准|批准|放行|開放交易|新增交易對|IPO"),
    ("EVT_CRASH", r"暴跌|崩盤|崩千點|狂瀉|閃崩|重挫|急殺|插針"),
    ("EVT_LIQUIDATION", r"爆倉|爆仓|血洗|清算|強平|歸零|归零"),
    ("EVT_SURGE", r"暴漲|暴涨|噴出|創高|創新高|突破"),
    ("EVT_HACK", r"駭客|盜幣|盗币|被盜|遭駭|漏洞"),
    ("EVT_REGULATION", r"監管|管制|禁令|SEC|立法|課稅|課税"),
    ("EVT_WHALE", r"鯨魚|大戶|機構買|機構賣|巨鯨"),
)


def _event_tag(t: str) -> str:
    """粗分類新聞事件屬性(供 topic_gate 保留『事件識別』維度);無命中回空字串(視為無特定事件,
    不因此鬆綁去重——雙方都無標籤時仍照骨架相似度判斷)。"""
    t = t or ""
    for tag, pat in _EVENT_CATS:
        if _re.search(pat, t):
            return tag
    return ""


def topic_gate(title: str, recent=None, thr: float = 0.72) -> bool:
    """True = 該題應被擋下:①命中禁用骨架,或 ②與 recent 任一標題的語意骨架相似度 >= thr
    (且雙方事件標籤相同或至少一方無標籤——不同新聞事件不互判重複)。
    recent:近期已發布/已入庫標題清單(比對語意重複);不傳則只擋禁用骨架。"""
    if is_banned_skeleton(title):
        return True
    ns = _norm_skeleton(title)
    if not ns:
        return False
    tag = _event_tag(title)
    for r in (recent or []):
        try:
            r_tag = _event_tag(r)
            if tag and r_tag and tag != r_tag:
                continue  # P3:兩者都有明確且不同的事件標籤 → 不同新聞事件,不判重複
            if _SeqMatch(None, ns, _norm_skeleton(r)).ratio() >= thr:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def recent_titles(n: int = 80) -> list:
    """近期已發布/已產出的標題清單(給 topic_gate 做語意去重比對用)。
    來源:quality_scores.json 的 published/pending(含 title),取最後 n 筆;無檔回空。"""
    out = []
    q = load_json_safe(STUDIO / "quality_scores.json", {}) or {}
    if isinstance(q, dict):
        for key in ("published", "pending"):
            for x in (q.get(key) or []):
                if isinstance(x, dict):
                    t = x.get("title") or x.get("slug")
                    if t:
                        out.append(str(t))
    return out[-n:] if n else out


# ── P2 滾動骨架頻率上限(2026-07 破局計畫:BANNED_SKELETONS 只擋舊幣圈洗版樣板;
#    「定投×少賺一臺賓士」這類新洗版每次換不同數字/不同包裝措辭,_too_similar(0.82) 與
#    topic_gate 的全文骨架相似度都因措辭差異攔不到,近批複製到 5+ 支。用「動作詞+生活比喻詞」
#    抽出比全文相似度更粗的『家族指紋』,對近 7 天內同家族設每週上限,超過就要求換家族。
#    只有命中已知濫用家族(動作/比喻詞)的標題才計入,一般標題不受影響、不誤殺贏家公式單支)──
_SK_ACTION_WORDS = ("定投", "網格", "複利", "停損", "停利", "回測", "存股", "當沖",
                     "馬丁格爾", "凱利", "夏普", "微笑曲線",
                     "勝率")  # 2026-07 成長衝刺:補「87%勝率陷阱」這款反序洗版家族(見上方 BANNED_SKELETONS 補洞說明)
_SK_LIFE_METAPHOR = ("賓士", "手搖", "便當", "一頓", "一杯", "一台", "一輛", "一年", "一個月薪")
_SKELETON_FREQ_FILE = "skeleton_freq_state.json"


def _skeleton_family(title: str) -> str:
    """粗粒度『濫用家族指紋』:動作詞 + 生活比喻詞(不看數字/其餘措辭)。
    非濫用家族回空字串("" = 不參與頻率上限)。

    🔴 2026-07-13 修一個把頻道鎖死的 bug:
    原本「只有動作詞、沒有生活比喻詞」也算一個家族(如「回測|」),而上限是每週 2 支。
    但 _SK_ACTION_WORDS 裡的「回測/定投/存股/停利/複利/當沖」**正是本頻道的核心詞彙**
    (頻道定位就是「用真回測拆穿割韭菜神話」),一天要產 18 支。實測 state:
        「回測|」32/2   「網格|」12/2   「複利|」6/2   「定投|」6/2
    → 台股題目逐一被擋死(「0050定投…回測」「高股息…複利滾存」「台積電…停利」全中),
      長片產製連續失敗、當批 0 支(YPP 唯一路徑直接斷掉)。題材配重倒向台股後更嚴重。

    這個上限的**原意**(見上方註解)是擋「定投 × 少賺一臺賓士」這種**同一生活比喻換數字重包裝**
    的洗版——signature 是「動作詞 **+** 生活比喻詞」。只有動作詞 = 這就是頻道的題材本身,
    不是洗版,不該被上限鎖。真正的重複由 _too_similar / skeleton_dup_any / 內容級 dedup 去抓。

    改:**必須有生活比喻詞**才算濫用家族(有無動作詞都算);只有動作詞 → 回空(不受限)。
    """
    t = title or ""
    action = next((w for w in _SK_ACTION_WORDS if w in t), "")
    life = next((w for w in _SK_LIFE_METAPHOR if w in t), "")
    if not life:
        return ""   # 無生活比喻詞 = 不是「換數字重包裝同一比喻」的洗版樣態 → 不參與週上限
    return f"{action}|{life}"


def check_skeleton_frequency(title: str, cap: int = 2, window_days: int = 7) -> bool:
    """True = 該標題所屬『濫用家族』近 window_days 天已達週上限,應擋下/要求換家族。
    只讀 STUDIO/skeleton_freq_state.json(由 record_skeleton_produced 寫入的時間戳);
    非已知家族(_skeleton_family 回空)一律放行(不誤殺)。
    2026-07 成長衝刺:cap 原為 3,實測「同核心比喻/數字題一週上限 1-2 支」才夠緊(見
    growth_sprint_plan.md D 段:2026-07-07 單日 5 支近乎同題互打),下修為 2。"""
    fam = _skeleton_family(title)
    if not fam:
        return False
    st = load_json_safe(STUDIO / _SKELETON_FREQ_FILE, {}) or {}
    events = st.get(fam) or []
    cutoff = time.time() - window_days * 86400
    recent = [e for e in events if isinstance(e, (int, float)) and e >= cutoff]
    return len(recent) >= cap


# ── 通用『主題頻率上限』helper(2026-07 成長衝刺:給非標題骨架的分類用,例如「加密爆倉/網格
#    新聞蹭熱」這種完播殺手,要用『分類標籤』而非標題文字算頻率——news_dept/hotspot_dept/
#    produce_batch.pull_topic 共用同一份 state,不論走哪條產線路徑,同一週上限都算在一起)──
_TOPIC_FREQ_FILE = "topic_freq_state.json"


def check_topic_frequency(tag: str, cap: int = 2, window_days: int = 7) -> bool:
    """True = 指定 tag(如 "news_liquidation")近 window_days 天已達 cap 次數上限,應擋下。
    tag 為空一律放行。"""
    if not tag:
        return False
    st = load_json_safe(STUDIO / _TOPIC_FREQ_FILE, {}) or {}
    events = st.get(tag) or []
    cutoff = time.time() - window_days * 86400
    recent = [e for e in events if isinstance(e, (int, float)) and e >= cutoff]
    return len(recent) >= cap


def record_topic_produced(tag: str) -> None:
    """tag 對應主題確定產出後呼叫,記一筆時間戳(供 check_topic_frequency 計數)。
    自帶清理:超過 30 天的舊紀錄丟棄。tag 為空不記錄。"""
    if not tag:
        return
    st = load_json_safe(STUDIO / _TOPIC_FREQ_FILE, {}) or {}
    cutoff = time.time() - 30 * 86400
    events = [e for e in (st.get(tag) or []) if isinstance(e, (int, float)) and e >= cutoff]
    events.append(time.time())
    st[tag] = events
    save_json_atomic(STUDIO / _TOPIC_FREQ_FILE, st)


# ── 加密爆倉/網格新聞蹭熱分類器(2026-07 成長衝刺:實測完播殺手,近一週重複約 6 支、
#    完播僅 24-39%,見 growth_sprint_plan.md C 段)。news_dept/hotspot_dept/produce_batch.pull_topic
#    共用同一個判斷式,搭配 check_topic_frequency("news_liquidation", cap=2) 設週上限。──
_LIQUIDATION_RE = _re.compile(
    r"爆倉|爆仓|血洗|清算|斷頭|断头|歸零|归零|空單|空军|空軍|網格.{0,6}(撐得住|撐不住|還活著|還撐)")


def is_liquidation_hijack(text: str) -> bool:
    """標題/新聞重點是否屬『加密爆倉/清算新聞蹭熱』完播殺手類型(純新聞恐慌轉述,非個人化反直覺鉤子)。"""
    return bool(_LIQUIDATION_RE.search(text or ""))


def record_skeleton_produced(title: str) -> None:
    """標題確定產出/入庫後呼叫,記一筆時間戳到所屬濫用家族(供 check_skeleton_frequency 計數)。
    非已知家族(_skeleton_family 回空)不記錄。自帶清理:超過 30 天的舊紀錄丟棄,state 檔不會無限長大。"""
    fam = _skeleton_family(title)
    if not fam:
        return
    st = load_json_safe(STUDIO / _SKELETON_FREQ_FILE, {}) or {}
    cutoff = time.time() - 30 * 86400
    events = [e for e in (st.get(fam) or []) if isinstance(e, (int, float)) and e >= cutoff]
    events.append(time.time())
    st[fam] = events
    save_json_atomic(STUDIO / _SKELETON_FREQ_FILE, st)


def skeleton_similar(a: str, b: str, thr: float = 0.78) -> bool:
    """P2 補強:『同模板換數字/題材名』複製偵測——用去數字+去題材名/血詞後的骨架(_norm_skeleton)
    比對相似度(補 _too_similar 只去數字、topic_gate 只用於 crypto 來源的缺口)。
    沿用 P3 的事件識別維度:兩者都有明確且不同的事件標籤時不視為重複。"""
    na, nb = _norm_skeleton(a), _norm_skeleton(b)
    if not na or not nb:
        return False
    ta, tb = _event_tag(a), _event_tag(b)
    if ta and tb and ta != tb:
        return False
    try:
        return _SeqMatch(None, na, nb).ratio() >= thr
    except Exception:  # noqa: BLE001
        return False


def skeleton_dup_any(title: str, existing, thr: float = 0.78) -> bool:
    """title 是否與 existing(標題清單)中任一標題骨架相似(見 skeleton_similar)。"""
    return any(skeleton_similar(title, e, thr) for e in (existing or []))


# ── 共用人設(軟性新定位;各部門把這段貼進自己的 system/prompt 開頭)──
PERSONA = (
    "你服務的頻道是「量化阿森 Carson Quant」——繁體中文、faceless 的自動交易/量化教學頻道。\n"
    "【頻道定位(置頂·所有內容的靈魂,一句話版本·盡量原句沿用)】"
    "量化阿森=用真回測拆穿割韭菜神話的量化玩家,每個結論都用數據卡佐證。\n"
    "延伸:專門拆穿"
    "「台股全市場(大盤/ETF/個股/選股/當沖/存股/財報/籌碼)」與「加密量化(網格/定投)」兩界的割韭菜神話,"
    "幫小白避雷、不賣夢;台股什麼都能講(個股也能),但角度一律數據分析/回測/拆穿/避雷/教學,"
    "絕不喊單、不報明牌、不喊目標價、不保證會漲會賺;開場常用誠實反差鉤(『別人賣你發財夢,我先用回測把坑踩死給你看』)。"
    "個別內容若是回測就標明是回測、不假稱丟真錢實盤(但不必自稱沒錢)。\n"
    "【簽名視覺與收尾(記憶點,強化可辨識度)】每支片的核心論點都要有數據卡佐證"
    "(數據卡本身是視覺,由渲染引擎產出,文案端只需點明『這是有數據卡佐證的結論』,別自己畫蛇添足編假數字);"
    "片尾固定收尾金句,盡量原句沿用:『故事會騙人,數據不會——我是量化阿森,每個結論都有數據卡佐證,我們下支見。』\n"
    "【受眾方向(軟性、重點之一非唯一)】多照顧「想被動賺、但怕被割的投資小白」;好用的角度是"
    "「我先幫你試、別自己送死」——用回測替小白試機器人與做法,情緒先戳恐懼(被割/被套/會不會虧光)"
    "再給安心(我回測過、這坑先幫你踩)。\n"
    "【語言】能白話就白話,術語順手翻人話(回測=拿歷史行情跑一遍、夏普=賺得穩不穩、網格=機器人低買高賣、"
    "複利=利滾利);但不必為白話犧牲該有的乾貨,原本的量化/實測/進階內容照樣做,只是多這條路。\n"
    "【誠信鐵則】不編造損益、不保證收益、不喊單;躺賺/穩賺/一天賺X 等誇大詞一律不用(會被限流)。"
)

_PROVIDERS = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY")


def has_llm_key() -> bool:
    """任一 LLM 供應商 key 即算有(實際呼叫由 _llm_shim 改道 OpenRouter)。"""
    return any(os.environ.get(k, "").strip() for k in _PROVIDERS)


def _load(name, default):
    p = STUDIO / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:
        return default


def evidence_block(max_chars: int = 900) -> str:
    """產「本頻道實證」few-shot 文字:近期真實高/低完播題材 + 贏家關鍵字 + 完播訊號。
    給選題/寫題/寫稿 prompt 注入,讓決策向已驗證高完播傾斜。無資料則回空字串。"""
    lines = []
    ts = _load("traffic_signals.json", {})
    if isinstance(ts, dict):
        win = ts.get("win_keywords") or []
        weak = ts.get("weak_keywords") or []
        if win:
            lines.append("・已驗證高流量/高完播的題材關鍵字(優先靠向):" + "、".join(map(str, win[:10])))
        if weak:
            lines.append("・表現差的題材(少碰或改角度):" + "、".join(map(str, weak[:8])))
        tv = ts.get("top_videos") or []
        ex = []
        for v in tv[:6]:
            t = str(v.get("slug") or v.get("title") or "").replace("S_", "")[:22]
            ap = v.get("avg_pct")
            # 健全性檢查:完播率理應落在 0-100 區間,壞值(資料源出錯/被手動改壞)不該原封不動
            # 包成「已驗證實證數據」餵進 LLM prompt——那正是模型會照抄進逐字稿的「真數據」來源，
            # 壞掉的話反而變成放大版的捏造數字。
            ap_ok = isinstance(ap, (int, float)) and not isinstance(ap, bool) and 0 <= ap <= 100
            if t:
                ex.append(f"「{t}」完播{round(ap)}%" if ap_ok else f"「{t}」")
        if ex:
            lines.append("・近期實際表現較好的片:" + "；".join(ex))
    cs = _load("completion_signals.json", {})
    if isinstance(cs, dict):
        hi = cs.get("high_topics") or cs.get("high") or []
        lo = cs.get("low_topics") or cs.get("low") or []
        if hi:
            lines.append("・高完播題材:" + "、".join(map(str, hi[:6])))
        if lo:
            lines.append("・低完播題材(避雷/改做):" + "、".join(map(str, lo[:6])))
    # 品管:抓幾個真實高分/低分標題當正反例
    q = _load("quality_scores.json", {})
    if isinstance(q, dict):
        pend = [x for x in (q.get("pending") or []) if isinstance(x, dict) and x.get("score") is not None]
        pend.sort(key=lambda x: x.get("score", 0), reverse=True)
        good = [x.get("title", "")[:20] for x in pend[:2] if x.get("score", 0) >= 80]
        bad = [x.get("title", "")[:20] for x in pend[-2:] if x.get("score", 100) < 60]
        if good:
            lines.append("・品管高分範例(這方向對):" + "、".join(good))
        if bad:
            lines.append("・品管低分範例(別學):" + "、".join(bad))
    if not lines:
        return ""
    out = "【本頻道實證數據(用真數據導向,別憑空發想)】\n" + "\n".join(lines)
    return out[:max_chars]


# ── 題材配重系統(2026-07 台股比重修正)──
# 實測依據:Carson 用 YT Data/Analytics API 實測 195 支公開影片,Top5(48h觀看854/821/732/666/659)
# 全是台股題材(0050/台積電/00878/ETF回測比較),Bottom5(0觀看,掛47-54小時)3支是加密貨幣
# (BTC暴跌/加密網格/AI選股)。但 STUDIO/topic_bank.json 現存 430 個未用題目裡,台股類別加總不到
# 3%(市場觀念 309題裡混雜大量加密內容、真正台股類別只個位數)。round-robin 式的『每輪出一組』
# 是均分邏輯,完全沒往台股加權——這是產出鏈的根因之一,故在此新增可調參數化的桶配重,
# topic_bank(產題存檔)與 produce_batch(抽題配額)共用同一份規則,任何一端改權重都同步生效。
#
# 比重設計:台股 78%(頭號實證贏家,主力)、加密 10%(不歸零——頻道 DNA 之一+Pionex 聯盟返佣要用,
# 且爆款也需要跨題材素材避免演算法判定內容單一)、AI×交易/工具 12%(第二變現支柱:AI省錢+
# Claude Code揭密兩條 franchise,也是對手抄不出的護城河,要顧但不必是主力)。
# 之後有更多分眾實測數據,直接改這個 dict 即可,不用動呼叫端邏輯。
TOPIC_BUCKET_WEIGHTS = {"tw_stock": 0.78, "crypto": 0.10, "ai_tools": 0.12}  # 總和=1.0

# ai_tools 專屬品牌/工具詞——命中即回傳 ai_tools,不論同段文字是否也含台股/加密詞(這是獨立的
# 變現支柱:即使內容是『我用 Claude Code 分析台積電』也算 AI 公司揭密 franchise,不算 tw_stock)。
# 刻意不用裸字「AI」當關鍵字、也不對「AI選股/AI策略/AI操盤」這類詞觸發——那些是加密圈常見的
# 『AI選股神器』話術題,屬 crypto/general 陣營,不是本頻道 AI 工具/Claude Code 揭密這條線
# (混進來會稀釋 ai_tools 桶的精準度,詳見 classify_topic_bucket 說明)。
_BUCKET_AI_TOOLS_KW = (
    "Claude Code", "ChatGPT", "Claude Pro", "GPT Plus", "GPT-4", "Gemini Advanced",
    "AI訂閱", "共享帳號", "合租帳號", "共享合租", "API串接", "OpenRouter", "DeepSeek",
    "AI省錢", "AI公司揭密", "PremLogin", "大型語言模型", "AI開發", "AI寫程式",
    "AI自動化系統", "AI跑頻道", "AI跑量化", "prompt工程", "AI工具比較", "AI助理", "Claude",
)
# tw_stock / crypto 各分「專有名詞(strong,權重2)」「泛用詞(weak,權重1)」——分數高者勝出。
# strong 是具體標的代號/公司名(訊號最硬),weak 是該市場慣用但較泛用的詞彙。
_BUCKET_TW_STRONG = (
    "0050", "0056", "00878", "00929", "00919", "00940", "00631L", "006208", "00713", "00733",
    "台積電", "台灣50",
)
_BUCKET_TW_WEAK = (
    "台股", "臺股", "存股", "除權息", "填息", "籌碼", "財報", "毛利率", "營益率",
    "當沖", "隔日沖", "波段", "法人買賣超", "融資", "融券", "權值股", "大盤", "加權指數",
    "開戶", "零股", "證交稅", "退休金", "退休試算", "正2", "反1", "槓桿ETF",
    # 2026-07-13 實測補漏:分類器把「高股息ETF月配vs年配複利滾存10年差多少」判成 general,
    # 逃出台股桶=不受配額保護。高股息/配息/定期定額/ETF 這些正是本頻道最核心的台股詞彙,
    # 原本竟然一個都不在清單裡(只有除權息/填息),導致一大票真台股題被漏掉。
    # 這些詞加密圈也會用(如「比特幣定期定額」),但 crypto STRONG 權重 2 > 這裡的 weak 權重 1,
    # 真的講幣的題目仍會正確落到 crypto 桶,不會被誤搶。
    "高股息", "股息", "配息", "月配", "季配", "年配", "月月配", "殖利率", "配股",
    "ETF", "市值型", "指數型", "定期定額", "定投", "定期投資", "扣款",
    "複利", "滾存", "停利", "微笑曲線", "單筆投入", "All-in", "All in",
    # 2026-07-15「個股體檢」新系列(scripts/stock_checkup_facts.py):鴻海/聯發科/長榮/
    # 中華電/國泰金等個股名不在 STRONG 清單(那份只收 0050 系列與台積電)，沒有這行
    # 這些題目會落到 general 桶、逃出 tw_stock 每日配額保護。只加台股上市公司專名
    # 與系列名「個股體檢」——刻意不加「套牢/腰斬」這類通用詞，那些幣圈/美股題目也會用，
    # 加了會在 tie-break 時把真正的 crypto 題目誤判成 tw_stock(regression risk)。
    "個股體檢", "鴻海", "聯發科", "長榮", "中華電", "國泰金",
)
_BUCKET_CRYPTO_STRONG = (
    "比特幣", "比特币", "BTC", "以太坊", "以太幣", "以太币", "ETH", "山寨幣", "迷因幣",
    "狗狗幣", "幣安", "Coinbase", "Kraken", "Tether", "USDT", "USDC", "Circle",
    "Pi Network", "Pi幣", "MiCA",
)
_BUCKET_CRYPTO_WEAK = (
    "網格", "派網", "Pionex", "穩定幣", "加密貨幣", "加密幣", "加密", "區塊鏈",
    "挖礦", "礦企", "永續合約", "合約槓桿", "槓桿合約", "爆倉", "清算", "歸零",
    "空投", "幣圈", "鏈上", "冷錢包", "熱錢包", "質押",
)


def classify_topic_bucket(title: str, angle: str = "", category: str = "") -> str:
    """把一個題目歸到 tw_stock/crypto/ai_tools/general 四桶之一,供 topic_bank 產題存檔與
    produce_batch 抽題配額共用同一套規則(改一處、兩端同步生效)。

    規則(依序判斷,先中先贏):
    1. 先查 ai_tools 專屬品牌/工具詞(見 _BUCKET_AI_TOOLS_KW)——命中即回傳 ai_tools。
    2. 否則用「專有名詞(strong,權重2)+泛用詞(weak,權重1)」分別給 tw_stock 與 crypto 計分,
       分數高者勝出;兩邊都 >0 且打平時偏向 tw_stock(目前要放大的主力,曖昧題就近拉台股,
       這也呼應實測:許多舊題目掛「市場觀念」類別但內文其實混雜台股/加密,曖昧不決時不該平白
       流失可歸類為台股的題目)。
    3. 兩邊都 0 分(無特定資產標的的通用量化觀念/拆穿神話/風控心法等)→ general,不強塞三桶。
    """
    text = f"{title or ''} {angle or ''} {category or ''}"
    if any(k in text for k in _BUCKET_AI_TOOLS_KW):
        return "ai_tools"
    tw_score = 2 * sum(1 for k in _BUCKET_TW_STRONG if k in text) + sum(1 for k in _BUCKET_TW_WEAK if k in text)
    cr_score = 2 * sum(1 for k in _BUCKET_CRYPTO_STRONG if k in text) + sum(1 for k in _BUCKET_CRYPTO_WEAK if k in text)
    if tw_score == 0 and cr_score == 0:
        return "general"
    return "tw_stock" if tw_score >= cr_score else "crypto"


if __name__ == "__main__":
    print("has_llm_key:", has_llm_key())
    print(evidence_block())


# ── 記憶體守門(2026-08-20 事故)────────────────────────────────────────────
# 重渲那批 8 支**全部**失敗,錯誤碼 3221226091(FATAL_USER_CALLBACK_EXCEPTION)
# 與 1073807364(DBG_TERMINATE_PROCESS)。查下去不是程式壞掉——
# **可用實體記憶體只剩 805 MB / 16 GB**,被 node(40 個進程 3.5GB)與多個
# claude session(3GB)吃光,而長片渲染要 1~2GB。
# memory yt-healthcheck-concurrency 記過同型事故(15.7GB 被吃到 0.4GB,當天渲染全滅)。
# 沒有守門的話,每支片都會跑到一半才崩:浪費十幾分鐘 CPU 又什麼都沒產出,
# 而且失敗看起來像「渲染壞了」,會把人引去查錯的地方。
# 放在 studio_common 是為了讓所有渲染路徑共用同一份判準
# (memory yt-duplicate-impl-gate-bypass:閘門兩份,產線會走沒閘門的那份)。
RENDER_MIN_FREE_MB = 2000


def free_mem_mb():
    """可用實體記憶體(MB)。查不到回 None —— **不判定,不阻擋**
    (工具查不到不等於記憶體不足,fail-open)。"""
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _MS()
        st.dwLength = ctypes.sizeof(_MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullAvailPhys / (1024 * 1024))
    except Exception:  # noqa: BLE001
        pass
    return None


def render_mem_ok(min_mb=None):
    """回 (是否可以渲染, 可用MB)。查不到記憶體時一律放行。"""
    need = RENDER_MIN_FREE_MB if min_mb is None else min_mb
    m = free_mem_mb()
    return (True, m) if m is None else (m >= need, m)
