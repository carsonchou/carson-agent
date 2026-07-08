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


def topic_gate(title: str, recent=None, thr: float = 0.72) -> bool:
    """True = 該題應被擋下:①命中禁用骨架,或 ②與 recent 任一標題的語意骨架相似度 >= thr。
    recent:近期已發布/已入庫標題清單(比對語意重複);不傳則只擋禁用骨架。"""
    if is_banned_skeleton(title):
        return True
    ns = _norm_skeleton(title)
    if not ns:
        return False
    for r in (recent or []):
        try:
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
