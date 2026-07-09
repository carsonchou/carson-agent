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
]

# 誠實揭露語境(命中詞附近有這些字→視為「示意/假設」或「拆穿/破解他人誇大宣稱」的誠實表述,
# 非本片自己捏造的斷言,放行不誤殺)。後半段對齊 audit_video.py 的 DEBUNK 語境判斷,
# 因為本頻道「拆穿誇大回測神話」是常態合理教學題材(如拆解「812%程式碼回測」為什麼是騙點閱的)。
_HEDGE = ("示意", "假設", "僅供參考", "僅為教學", "不代表未來", "非保證", "模擬情境",
          "純假設", "抽樣", "範例數字", "僅供示範", "歷史不代表", "僅供評估", "舉例來說",
          "僅是舉例", "若你", "若有",
          "號稱", "聲稱", "宣稱", "拆穿", "揭穿", "破解", "陷阱", "迷思", "騙點閱",
          "唬爛", "誇大", "話術", "騙局", "以為", "別再信", "怎麼可能", "真的假的")


def _flags_for(text: str):
    text = text or ""
    hits = []
    for rx in _RISK:
        for m in rx.finditer(text):
            hits.append(m.group(0)[:40])
    for rx in _RISK_PERF:
        for m in rx.finditer(text):
            i, j = m.span()
            window = text[max(0, i - 20): j + 20]
            if any(h in window for h in _HEDGE):
                continue  # 附近有「示意/假設/僅供參考」等誠實揭露 → 放行,非誤殺對象
            hits.append(m.group(0)[:40])
    return hits


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
