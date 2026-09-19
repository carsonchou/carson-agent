# -*- coding: utf-8 -*-
"""對照幀 harness — 直接呼叫正式碼 concept_visuals.render_concept_chart 出圖。

用法: python render_pairs.py <輸出目錄>
      python render_pairs.py <輸出目錄> --sheet <before目錄>   # 額外產 before|after 併排圖

刻意不做任何自己的繪圖:圖完全由正式碼產生,所以 before/after 的差異只可能來自正式碼改動。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

YT = Path(r"D:\carson-agent\youtube_channel")
sys.path.insert(0, str(YT / "scripts"))
# CVIS_DIR=<目錄> 可指定改用另一份 concept_visuals.py(產 before 幀用)。
# 一定要印出實際載到的檔案路徑:否則「before 跟 after 長得一樣」時分不出是改動沒效果
# 還是兩次都載到同一份(memory wrong-baseline-measures-the-design)。
if os.environ.get("CVIS_DIR"):
    sys.path.insert(0, os.environ["CVIS_DIR"])
import concept_visuals as cvis  # noqa: E402

print("[render_pairs] concept_visuals <-", cvis.__file__)

# 🔴 concept_visuals 用 `Path(__file__).parent.parent/"STUDIO"` 找真價格 CSV 與體檢事實庫。
# 副本放在別的目錄時那個相對路徑指到不存在的地方 → **所有真資料圖一律回 None**,
# 對照幀會全空而且看起來像「改壞了」。這裡把資料來源指回正式機絕對路徑,不動繪圖邏輯。
cvis._FACTS_CACHE = YT / "STUDIO" / "tw_facts_cache"
cvis._CHECKUP_FACTS = (__import__("json").loads(
    (YT / "STUDIO" / "stock_checkup_facts.json").read_text(encoding="utf-8"))
    or {}).get("results") or {}
assert cvis._FACTS_CACHE.exists() and cvis._CHECKUP_FACTS, "真資料來源接不上"

W, H = 1920, 1080
ACCENT = (255, 209, 102)

# (檔名, 個股, 圖種, reveal, 旁白文字)
# 3714/2485 = P0 離群值受害者;2610/2330 = 陰性對照(本來就正常,修完不可以變差)
# fundamentals/drawdown/history = 其他圖種,證明改動沒有波及(步驟1)或有一致受益(步驟2)
JOBS = [
    ("val_3714_r10", "3714", "valuation", 1.00, "富采 3714 目前本益比落在自身歷史什麼位置"),
    ("val_3714_r06", "3714", "valuation", 0.625, "富采 3714 目前本益比落在自身歷史什麼位置"),
    ("val_2485_r10", "2485", "valuation", 1.00, "兆赫 2485 目前本益比落在自身歷史什麼位置"),
    ("val_1536_r10", "1536", "valuation", 1.00, "和大 1536 目前本益比落在自身歷史什麼位置"),
    ("val_2610_r10", "2610", "valuation", 1.00, "華航 2610 目前本益比落在自身歷史什麼位置"),
    ("val_2330_r10", "2330", "valuation", 1.00, "台積電 2330 目前本益比落在自身歷史什麼位置"),
    ("fund_3714_r10", "3714", "fundamentals", 1.00, "富采 3714 這幾年的營收與 EPS 走勢"),
    ("fund_2610_r10", "2610", "fundamentals", 1.00, "華航 2610 這幾年的營收與 EPS 走勢"),
    ("dd_2485_r10", "2485", "drawdown", 1.00, "兆赫 2485 期間最大回撤曾高達多少"),
    ("dd_3714_r06", "3714", "drawdown", 0.625, "富采 3714 期間最大回撤曾高達多少"),
    ("hist_2330_r10", "2330", "history", 1.00, "台積電 2330 完整真實走勢"),
    ("trend_2610_r10", "2610", "trend", 1.00, "華航 2610 這一段一路往上漲"),
    # dca 是本片第 4 段實際用到的圖種(真資料)。步驟 1 沒列到它(改的是 _valuation,
    # 波及範圍用其他 4 種圖種已經證完);步驟 2 改的是全部真資料 drawer,所以補進來。
    ("dca_3714_r10", "3714", "dca", 1.00, "富采 3714 每月定期定額的實際平均成本"),
    ("dca_2330_r10", "2330", "dca", 1.00, "台積電 2330 每月定期定額的實際平均成本"),
    # candle / crosssec 是另外兩個「真資料但第一版重皮漏掉」的圖種(和 dca 同一批漏網)。
    # 補進來才證得出重皮覆蓋到全部真資料 drawer,而不是只覆蓋到我剛好想起來的那幾個。
    ("candle_3714_r10", "3714", "candle", 1.00, "富采 3714 近一年的實際 K 線"),
    ("candle_2330_r10", "2330", "candle", 1.00, "台積電 2330 近一年的實際 K 線"),
    # crosssec 不看個股(畫的是全市場分佈),但 ctx.real 仍要有值才進得去,故仍給代號。
    ("xsec_dd_r10", "2330", "crosssec", 1.00, "全市場最大回撤分佈：多少檔曾經腰斬"),
    ("xsec_uw_r10", "2330", "crosssec", 1.00, "全市場最長套牢期分佈"),
]


def render_all(out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for name, code, force, reveal, text in JOBS:
        dest = out / f"{name}.png"
        img = cvis.render_concept_chart(W, H, text, ACCENT, seed=f"s_{name}",
                                        dest=str(dest), force=force,
                                        fallback_ticker=code, reveal=reveal)
        print(("  OK  " if img is not None else "  None") + f" {name}")
        if img is not None:
            made.append(name)
    return made


def make_sheets(before: Path, after: Path, names: list[str]) -> None:
    """before|after 上下併排(1920x2160),加左上角標籤。"""
    from PIL import Image, ImageDraw
    sheets = after.parent / after.name.replace("_after", "_對照")
    sheets.mkdir(parents=True, exist_ok=True)
    for n in names:
        bp, ap = before / f"{n}.png", after / f"{n}.png"
        if not (bp.exists() and ap.exists()):
            print(f"  跳過 {n}(before/after 不成對)")
            continue
        b, a = Image.open(bp).convert("RGB"), Image.open(ap).convert("RGB")
        c = Image.new("RGB", (W, H * 2), (0, 0, 0))
        c.paste(b, (0, 0))
        c.paste(a, (0, H))
        d = ImageDraw.Draw(c)
        for y, lab, col in ((8, "BEFORE", (255, 110, 110)), (H + 8, "AFTER", (120, 240, 170))):
            d.rectangle([8, y, 190, y + 46], fill=(0, 0, 0))
            d.text((20, y + 12), lab, fill=col)
        c.save(sheets / f"{n}.jpg", quality=92)
        print("  sheet ->", n)


if __name__ == "__main__":
    outdir = Path(sys.argv[1]).resolve()
    names = render_all(outdir)
    if "--sheet" in sys.argv:
        make_sheets(Path(sys.argv[sys.argv.index("--sheet") + 1]).resolve(), outdir, names)
    print("done", outdir)
