#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fact_guard.py — 捏造史實守門(誠信安全網)。

品保 agent 發現:贏家格式量產偶爾捏造個股具體價位/歷史(如「台積電2023高點1000元」=假),
而 quality_score/audit_video 抓不到事實錯。這支用規則偵測「高風險事實句」:
  ①個股名(台積電/聯發科/鴻海/台G/0050…) 緊鄰 具體價格(數字+元/塊) 或 特定年份高低點斷言。
  ②(P5-b 補強)不掛個股名也危險的「憑空精確績效數字」:回測N檔/勝率X%/報酬Y%/N次操作
    這類看似嚴謹但 LLM 常憑空生成的統計語句(如「回測500檔只有34.9%會賺」「812%程式碼回測」
    「當沖1000次」——這三句就是品保實測溜過舊版守門的真案例)。有誠實揭露語境(示意/假設/
    僅供參考/不代表未來…)在附近才放行,避免誤殺合理教學表述(如「假設你定投10年」)。
命中→寫 STUDIO/fact_flags.json + ntfy 提醒人工複查(或搭 daily_publish 攔)。**只旗標不刪**(誤判成本高)。

用法:python scripts/fact_guard.py [--notify] [--recent N]
"""
from __future__ import annotations
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
import studio_common as sc

# 個股/標的名(講具體價位史實最危險的);ETF 代號也算(價位斷言一樣會錯)
_STOCK = r"(台積電|臺積電|聯發科|鴻海|台達電|大立光|中華電|國泰|富邦|元大|0050|0056|00878|00929|006208|00919|00940|台G|護國神山)"
# 高風險事實句:個股名 + 12字內 + (具體價/年份高低點斷言)
_RISK = [
    re.compile(_STOCK + r".{0,12}?\d{2,}\s*(元|塊|點)"),          # 個股+具體價位(台積電…1000元)
    re.compile(_STOCK + r".{0,12}?20\d\d.{0,6}?(高點|低點|最高|最低|崩|漲到|跌到)"),  # 個股+某年高低點斷言
    re.compile(r"20\d\d.{0,6}?(高點|最高).{0,8}?\d{2,}\s*(元|塊)"),  # 某年高點XXX元
]

# P5-b:不需掛個股名也危險的「憑空精確績效數字」——回測N檔/勝率X%/報酬Y%/N次操作。
# 品保實測溜過舊版守門的三個真案例:「回測500檔只有34.9%會賺」「812%程式碼回測」「當沖1000次」。
# 允許少量字元間隔(.{0,N})+ 順序不拘(數字在前或動詞在前都抓),因為真實口語稿常寫
# 「500檔標的上跑回測」「只有34.9%真的賺錢」這種數字與動詞分開、順序顛倒的自然句。
_RISK_PERF = [
    re.compile(r"(回測|測試|模擬|驗證|統計)(過|了)?.{0,4}?\d{2,}\s*(檔|支|個|項|筆|種)"),      # 回測500檔
    re.compile(r"\d{2,}\s*(檔|支|個|項|筆|種).{0,10}?(回測|測試|模擬|驗證|統計)"),             # 500檔…跑回測
    re.compile(r"(勝率|成功率|命中率|會賺|會贏|會漲)\s*(高達|僅|只有|為)?.{0,2}?\d+\.?\d*\s*%"),  # 勝率34.9%／只有34.9%會賺
    re.compile(r"\d+\.?\d*\s*%.{0,6}?(會賺|會贏|會漲|勝率|成功率|命中率|賺錢|獲利|正報酬)"),   # 34.9%真的賺錢／34.9%長期會賺
    re.compile(r"(報酬率?|獲利|年化|績效)\s*(高達|達|為)?.{0,2}?\d{2,}\.?\d*\s*%"),            # 年化812%／報酬達812%
    re.compile(r"\d{2,}\.?\d*\s*%.{0,4}?(的)?(報酬|獲利|績效|程式碼|策略)"),                    # 812%程式碼／812%報酬
    re.compile(r"(當沖|交易|下單|進出場|操作)\s*\d{3,}\s*次"),                                 # 當沖1000次
    re.compile(r"\d{3,}\s*次.{0,6}?(當沖|交易|下單|進出場|操作|回測)"),                        # 1000次當沖
    # A2(2026-07 頻道整頓計畫)補強:非台股題(crypto/AI)常見的憑空捏造句式——
    # 「回測過去三次，平均虧損23%」「夏普從2.8掉到0.6」這類看似嚴謹的績效轉折/回撤數字。
    re.compile(r"(平均)?\s*(虧損|回撤|最大回撤)\s*(達|為|高達|僅|只有)?.{0,2}?\d{1,3}\.?\d*\s*%"),  # 平均虧損23%
    re.compile(r"\d{1,3}\.?\d*\s*%.{0,6}?(虧損|回撤)"),                                          # 23%虧損
    re.compile(r"夏普\s*(值|比率)?\s*(從|由|高達)?\s*\d+\.?\d*\s*(→|->|到|變成|降到|掉到|剩)\s*\d+\.?\d*"),  # 夏普2.8→0.6
    re.compile(r"(回測|測試)(過去)?\s*[0-9一二三四五六七八九十]{1,3}\s*次"),                      # 回測過去三次
    re.compile(r"[0-9一二三四五六七八九十]{1,3}\s*次.{0,6}?(回測|測試)"),                        # 三次回測
]

# 誠實揭露語境(命中詞附近有這些字→視為「示意/假設」或「拆穿/破解他人誇大宣稱」的誠實表述,
# 非本片自己捏造的斷言,放行不誤殺)。後半段對齊 audit_video.py 的 DEBUNK 語境判斷,
# 因為本頻道「拆穿誇大回測神話」是常態合理教學題材(如拆解「812%程式碼回測」為什麼是騙點閱的)。
_HEDGE = ("示意", "假設", "僅供參考", "僅為教學", "不代表未來", "非保證", "模擬情境",
          "純假設", "抽樣", "範例數字", "僅供示範", "歷史不代表", "僅供評估", "舉例來說",
          "僅是舉例", "若你", "若有",
          "號稱", "聲稱", "宣稱", "拆穿", "揭穿", "破解", "陷阱", "迷思", "騙點閱",
          "唬爛", "誇大", "話術", "騙局", "以為", "別再信", "怎麼可能", "真的假的",
          "不是我編的", "不是編的", "真實回測")

# P6(2026-07 誠信漏洞修補):中文數字/模糊量詞版的「憑空績效斷言」——舊版 _RISK_PERF 只認
# 阿拉伯數字 \d+%,品保實測抓到旗艦片用「九成回測都虧錢」「AI策略虧光光」這種中文口語斷言
# 完全繞過守門(voice_text 由 LLM 把標題的「90%」唸成「九成」,規則抓不到)。
# ①模糊量詞(九成/八成/…/一半/大半/多數/絕大多數/幾乎都)+ 績效動詞(虧/賺/賠/翻倍…),同句(不跨。！？)。
_CN_QUANT = r"(九成|八成|七成|六成|五成|四成|三成|兩成|一成|大半|多數|絕大多數|幾乎都|幾乎全|一半)"
_PERF_WORD = r"(虧錢|虧損|虧掉|虧光|賠錢|賠光|倒賠|翻倍|翻了.{0,2}倍|賺.{0,2}倍|不賺|穩賺|穩賠|會賺|會虧|會賠)"
_RISK_CN = [
    re.compile(_CN_QUANT + r"[^。！？]{0,10}?" + _PERF_WORD),  # 九成回測都虧錢／多數人會虧
    re.compile(_PERF_WORD + r"[^。！？]{0,10}?" + _CN_QUANT),  # 虧掉九成本金／虧損超過三成
]
# ②不掛量詞也是無憑據絕對斷言的句式:虧光(光)/賠光(光)/翻N倍/賺N倍/勝率高達。
_RISK_CN_ABS = [
    re.compile(r"(虧光光|虧光|賠光光|賠光|全虧|血本無歸)"),
    re.compile(r"翻(了)?\s*[0-9一二三四五六七八九十]+\s*倍|賺(了)?\s*[0-9一二三四五六七八九十]+\s*倍"),
    re.compile(r"勝率\s*(高達|竟達|居然高達)\s*[0-9一二三四五六七八九十百]+"),
]
# 「有無真數據佐證」閘門:整篇逐字稿只要出現過阿拉伯數字或口語化「百分之XX」,就視為有具體
# 數據撐腰,P6 規則不誤標(如「百分之十九點八…不是我編的」是真實回測口播,只是唸法沒用阿拉伯數字)。
# 真正危險的樣態是全篇連一個具體數字都沒有,純靠形容詞堆出「聽起來像實測」的錯覺
# (品保實案「九成回測都虧錢」「AI策略虧光光」通篇零數據)。
_HAS_REAL_DATA = re.compile(r"\d|百分之[零一二三四五六七八九十點]+")


def _clause_around(text: str, i: int, j: int) -> str:
    """取出命中片語所在的「同一子句」(以。！？分界),避免跨句誤救。
    品保實案:「九成回測都虧錢！假設你用AI寫出一套策略…」的「假設」其實是下一句的鋪陳提問,
    不該讓它救援上一句已經用驚嘆號斷言完的捏造績效——舊版 ±20 字視窗會被這種鄰句誠實揭露詞誤救。"""
    left = max((text.rfind(c, 0, i) for c in "。！？"), default=-1)
    right_cands = [p for p in (text.find(c, j) for c in "。！？") if p != -1]
    right = min(right_cands) if right_cands else len(text)
    return text[left + 1: right]


def _flags_for(text: str):
    text = text or ""
    hits = []
    for rx in _RISK:
        for m in rx.finditer(text):
            hits.append(m.group(0)[:40])
    for rx in _RISK_PERF:
        for m in rx.finditer(text):
            i, j = m.span()
            if any(h in _clause_around(text, i, j) for h in _HEDGE):
                continue  # 同句內有「示意/假設/僅供參考」等誠實揭露 → 放行,非誤殺對象
            hits.append(m.group(0)[:40])
    for rx in _RISK_CN + _RISK_CN_ABS:
        for m in rx.finditer(text):
            i, j = m.span()
            if any(h in _clause_around(text, i, j) for h in _HEDGE):
                continue  # 同句內有誠實揭露詞 → 放行
            # 「有無真數據佐證」閘門(P6):只看命中點「附近」(前後約120字)是否有具體數字佐證,
            # 不能整篇任一角落出現一個不相干數字(如開場提年份/股號)就讓全篇模糊量詞斷言免疫——
            # 那正是品保實案「九成回測都虧錢」這類捏造句,溜過守門的真實迴歸風險。
            near = text[max(0, i - 120): j + 120]
            if _HAS_REAL_DATA.search(near):
                continue
            hits.append(m.group(0)[:40])
    return hits


def flags_for(text: str):
    """對外可呼叫版(A2:produce_batch.py 借用同一套判準做生成期重生判斷，不重複維護規則)。"""
    return _flags_for(text)


def main() -> int:
    n = 40
    if "--recent" in sys.argv:
        try:
            n = int(sys.argv[sys.argv.index("--recent") + 1])
        except Exception:  # noqa: BLE001
            pass
    voices = sorted(OUT.glob("S_*.voice.txt"), key=lambda f: -f.stat().st_mtime)[:n]
    voices += sorted(OUT.glob("L_*.voice.txt"), key=lambda f: -f.stat().st_mtime)[:10]
    flagged = {}
    for f in voices:
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        # P7(2026-07 誠信漏洞修補):過去只查 voice.txt(旁白逐字稿),標題/描述(.md)完全沒被
        # 掃到——捏造績效數字若寫進標題或 YouTube 描述而非旁白,舊版守門完全無感。
        # 同 slug 的 .md(標題+描述)一併併入同一次檢查,不重複維護規則。
        md = f.with_name(f.stem.replace(".voice", "") + ".md")
        if md.exists():
            try:
                txt += "\n" + md.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
        hits = _flags_for(txt)
        if hits:
            flagged[f.stem] = hits[:4]
    sc.save_json_atomic(STUDIO / "fact_flags.json", {"updated": time.strftime("%Y-%m-%d %H:%M"), "flagged": flagged})
    if flagged:
        print(f"[fact_guard] ⚠️ {len(flagged)} 支疑似捏造個股史實,建議人工複查:")
        for slug, hits in list(flagged.items())[:10]:
            print(f"  - {slug[:36]}｜可疑句:{hits}")
    else:
        print("[fact_guard] ✅ 近期產片無高風險個股史實斷言")
    if "--notify" in sys.argv and flagged:
        try:
            import notify
            notify.push("量化阿森｜捏造史實守門",
                        f"⚠️ {len(flagged)} 支疑似編個股價位/史實,發佈前複查:\n"
                        + "\n".join(list(flagged.keys())[:6]), tag="warning")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ntfy 失敗:{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
