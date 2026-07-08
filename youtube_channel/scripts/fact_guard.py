#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fact_guard.py — 捏造史實守門(誠信安全網)。

品保 agent 發現:贏家格式量產偶爾捏造個股具體價位/歷史(如「台積電2023高點1000元」=假),
而 quality_score/audit_video 抓不到事實錯。這支用規則偵測「高風險事實句」:
  個股名(台積電/聯發科/鴻海/台G/0050…) 緊鄰 具體價格(數字+元/塊) 或 特定年份高低點斷言。
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


def _flags_for(text: str):
    hits = []
    for rx in _RISK:
        for m in rx.finditer(text or ""):
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
