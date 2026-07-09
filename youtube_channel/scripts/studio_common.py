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
    # 勝率高卻虧:含數字型(9X/8X)與中文型(九成/八成)
    r"勝率\s*(9\d|8\d|9成|8成|九成|八成).{0,10}(卻虧|還虧|破產|虧光|還在虧)",
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
                     "馬丁格爾", "凱利", "夏普", "微笑曲線")
_SK_LIFE_METAPHOR = ("賓士", "手搖", "便當", "一頓", "一杯", "一台", "一輛", "一年", "一個月薪")
_SKELETON_FREQ_FILE = "skeleton_freq_state.json"


def _skeleton_family(title: str) -> str:
    """粗粒度『濫用家族指紋』:動作詞+生活比喻詞命中(不看數字/其餘措辭)。
    兩者皆無命中則回空字串("" = 非已知濫用家族,不參與頻率上限,避免誤殺一般題)。"""
    t = title or ""
    action = next((w for w in _SK_ACTION_WORDS if w in t), "")
    life = next((w for w in _SK_LIFE_METAPHOR if w in t), "")
    if not action and not life:
        return ""
    return f"{action}|{life}"


def check_skeleton_frequency(title: str, cap: int = 3, window_days: int = 7) -> bool:
    """True = 該標題所屬『濫用家族』近 window_days 天已達週上限,應擋下/要求換家族。
    只讀 STUDIO/skeleton_freq_state.json(由 record_skeleton_produced 寫入的時間戳);
    非已知家族(_skeleton_family 回空)一律放行(不誤殺)。"""
    fam = _skeleton_family(title)
    if not fam:
        return False
    st = load_json_safe(STUDIO / _SKELETON_FREQ_FILE, {}) or {}
    events = st.get(fam) or []
    cutoff = time.time() - window_days * 86400
    recent = [e for e in events if isinstance(e, (int, float)) and e >= cutoff]
    return len(recent) >= cap


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
    "【頻道定位(置頂·所有內容的靈魂)】量化阿森=敢說真話、只認數據的量化玩家,專門拆穿"
    "「台股全市場(大盤/ETF/個股/選股/當沖/存股/財報/籌碼)」與「加密量化(網格/定投)」兩界的割韭菜神話,"
    "幫小白避雷、不賣夢;台股什麼都能講(個股也能),但角度一律數據分析/回測/拆穿/避雷/教學,"
    "絕不喊單、不報明牌、不喊目標價、不保證會漲會賺;開場常用誠實反差鉤(『別人賣你發財夢,我先用回測把坑踩死給你看』)。"
    "個別內容若是回測就標明是回測、不假稱丟真錢實盤(但不必自稱沒錢)。\n"
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
            if t:
                ex.append(f"「{t}」完播{round(ap)}%" if isinstance(ap, (int, float)) else f"「{t}」")
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


if __name__ == "__main__":
    print("has_llm_key:", has_llm_key())
    print(evidence_block())
