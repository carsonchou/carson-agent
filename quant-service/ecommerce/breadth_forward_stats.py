#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""breadth_forward_stats.py —【S1 事實檔產生器】把 26 年全市場廣度 → 未來 20 日大盤表現的
分桶統計,預先算好存成 twdata/breadth_forward_stats.json。週報只讀這個檔,不在出報告時重算。

── 這個檔在回答什麼問題 ──────────────────────────────────────────────────────
「市場溫度高/低,能不能拿來擇時?」——這是 S1 頂上那個溫度計最自然會被問的問題,
而我們從來沒回答過。REVIEW_weekly_value 判 S1 只有 4 分(「讀完不會改變任何動作」),
唯一能救它的就是回答這題。所以先去把答案算出來,再決定怎麼寫。

── 為什麼算的是 breadth 而不是「溫度」本身(這是誠信的核心,不是技術細節)──────
官方溫度 = 0.30*rsi + 0.25*breadth + 0.15*adr + 0.20*nhnl + 0.10*vol(scan.py:968),
其中 **vol 成分需要成交量**,而:
  · twdata/cache 有 Volume,但每檔只有 ~170 根 ≈ 8 個月 → 20 日前瞻只剩 ~7 個獨立期,無意義;
  · twdata/cache_adj 有 1923 檔 × 最早 2000-01-04,但**只有 Close 欄** → 算不出 vol 成分。
若硬用 cache_adj 去「重建溫度」,會做出一個**看起來像溫度、成分卻不同**的東西 —— 實測過
這個陷阱:重建值 45.2/45.5 vs 官方 45.4 看似完美命中,內部 adv/dec 卻是 57/65 vs 官方
1060/588(樣本 125 檔 vs 1925 檔),只是加權後互相抵銷。**頭條對得上、成分全錯**是最危險的假象。

所以本檔**不重建溫度**,改算溫度的一個**成分**:站上 20MA 的個股佔比(breadth)。
它只需要 Close → cache_adj 給得起 26 年;它是溫度權重第二大的成分(0.25);
而且它自己就是一個定義明確、業界通用的廣度指標,不需要冒充別人。
**代價要講白**:本檔算出的 breadth 與 S1 頂上當期的 breadth **定義不同**(見 caveats)——
呈現時必須明說,絕不可讓讀者以為這是在對頂上那個數字做回測。

── 方法 ────────────────────────────────────────────────────────────────────
1. 讀 twdata/cache_adj/*.csv(含息還原收盤價),要求每檔 ≥ MIN_BARS 根才納入;
2. 每個交易日:站上自身 20MA 的檔數 ÷ 當日有效檔數 = breadth%;有效檔數 < MIN_UNIVERSE 的日子丟掉;
3. 對每一天,取 0050 之後 FWD_DAYS 個交易日的報酬(含息還原);
4. 依 breadth 分桶,算每桶的:樣本天數、不重疊獨立期數、未來報酬中位數、上漲機率;
5. 一併算全期基準,讓讀者能自己比「有差嗎」。

用法:
  python quant-service/ecommerce/breadth_forward_stats.py              # 重算並寫檔
  python quant-service/ecommerce/breadth_forward_stats.py --dry-run    # 只印不寫
驗證:python -m pytest quant-service/ecommerce/tests/test_breadth_forward_stats.py -q
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
QUANT = HERE.parent
ROOT = QUANT.parent
CACHE_ADJ = ROOT / "twdata" / "cache_adj"
OUT_FILE = ROOT / "twdata" / "breadth_forward_stats.json"

MA_WIN = 20            # 站上幾日均線
FWD_DAYS = 20          # 前瞻幾個交易日
MIN_BARS = 300         # 個股至少要有幾根才納入(太短的算不出穩定 20MA)
MIN_UNIVERSE = 200     # 當日有效檔數低於此 → 該日不採用(早年上市檔數少)
BENCH = "0050_TW"      # 大盤代理(與 data_hunter/scan.py 的 INDEX_CODE 同一檔)
BUCKETS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]

SOURCE_DESC = ("twdata/cache_adj/*.csv(含息還原收盤價,Close-only)"
               "；大盤代理 0050_TW 同源")
METHOD_DESC = (f"每個交易日計算「收盤價 > 自身 {MA_WIN} 日均線」的個股佔比(=breadth)，"
               f"再取 0050 其後 {FWD_DAYS} 個交易日的含息還原報酬，依 breadth 分桶統計。"
               f"個股需 ≥{MIN_BARS} 根、當日有效檔數需 ≥{MIN_UNIVERSE} 才採計。")
CAVEAT_DESC = ("本統計的 breadth 由 cache_adj 的『含息還原收盤價』重算，"
               "與週報 S1 當期顯示的 breadth（data_hunter 掃描器以原始價、當日全市場即時計算）"
               "**定義與資料源皆不同**，兩者數值不可互相對照；"
               "本統計亦不含市場溫度的 RSI/ADR/新高低/量能等其他成分，"
               "**不是對『市場溫度』這個指標本身做回測**。")


def _load_closes() -> dict:
    """讀 cache_adj → {code: {date: close}}。壞檔/太短的直接略過(不炸)。"""
    import pandas as pd
    out = {}
    files = sorted(glob.glob(str(CACHE_ADJ / "*.csv")))
    for f in files:
        try:
            df = pd.read_csv(f, usecols=["Date", "Close"])
            if len(df) < MIN_BARS:
                continue
            s = pd.Series(df["Close"].values, index=pd.to_datetime(df["Date"]))
            s = s[~s.index.duplicated(keep="last")].astype(float)
            out[Path(f).stem] = s
        except Exception:  # noqa: BLE001
            continue
    return out


def compute(closes: dict | None = None) -> dict:
    """回傳事實檔 dict。資料不足 → 回 {"ok": False, "error": ...},呼叫端據此降級。"""
    import pandas as pd

    closes = _load_closes() if closes is None else closes
    if not closes or BENCH not in closes:
        return {"ok": False, "error": f"cache_adj 無可用資料或缺大盤代理 {BENCH}"}

    px = pd.DataFrame(closes).sort_index()
    ma = px.rolling(MA_WIN).mean()
    valid = px.notna() & ma.notna()
    n_valid = valid.sum(axis=1)
    breadth = ((px > ma) & valid).sum(axis=1) / n_valid.replace(0, pd.NA) * 100
    breadth = breadth[n_valid >= MIN_UNIVERSE].dropna()
    if len(breadth) < FWD_DAYS * 10:
        return {"ok": False, "error": f"breadth 序列僅 {len(breadth)} 天,樣本不足"}

    b = closes[BENCH].reindex(breadth.index).ffill()
    fwd = (b.shift(-FWD_DAYS) / b - 1) * 100
    df = pd.DataFrame({"breadth": breadth, "fwd": fwd}).dropna()
    if df.empty:
        return {"ok": False, "error": "前瞻報酬序列為空"}

    rows = []
    for lo, hi in BUCKETS:
        sub = df[(df.breadth >= lo) & (df.breadth < hi)]
        if len(sub) < FWD_DAYS:            # 不重疊獨立期 < 1 → 不出數字,誠實標樣本不足
            rows.append({"lo": lo, "hi": hi, "n_days": int(len(sub)), "n_independent": 0,
                         "median_fwd_pct": None, "up_rate_pct": None, "insufficient": True})
            continue
        rows.append({
            "lo": lo, "hi": hi,
            "n_days": int(len(sub)),
            "n_independent": int(len(sub) // FWD_DAYS),
            "median_fwd_pct": round(float(sub.fwd.median()), 2),
            "up_rate_pct": round(float((sub.fwd > 0).mean() * 100), 1),
            "insufficient": False,
        })
    baseline = {
        "n_days": int(len(df)),
        "n_independent": int(len(df) // FWD_DAYS),
        "median_fwd_pct": round(float(df.fwd.median()), 2),
        "up_rate_pct": round(float((df.fwd > 0).mean() * 100), 1),
    }
    ups = [r["up_rate_pct"] for r in rows if not r["insufficient"]]
    # 「中間桶與基準差多少」必須由資料算出,不可由文案手打:手打的數字守門看不見
    # (它不是 %宣稱),但那正是「gate 抓不到的硬編碼數字」——本專案已為此吃過虧。
    mids = [r for r in rows if not r["insufficient"] and r["lo"] >= 20 and r["hi"] <= 80]
    mid_dev = (round(max(abs(r["up_rate_pct"] - baseline["up_rate_pct"]) for r in mids), 1)
               if mids else None)
    return {
        "ok": True,
        "generated_at": date.today().isoformat(),
        "indicator": f"站上{MA_WIN}日均線的個股佔比(breadth)",
        "benchmark": "元大台灣50(0050)",
        "forward_days": FWD_DAYS,
        "period_start": str(df.index[0].date()),
        "period_end": str(df.index[-1].date()),
        "n_stocks": int(px.shape[1]),
        "source": SOURCE_DESC,
        "method": METHOD_DESC,
        "caveat": CAVEAT_DESC,
        "buckets": rows,
        "baseline": baseline,
        # 以下兩個「差多少」都由資料算出、不是文案手打(呈現層直接引用並綁 provenance)
        "spread_pct_points": round(max(ups) - min(ups), 1) if len(ups) >= 2 else None,
        "middle_max_dev_pct_points": mid_dev,   # 中間桶(20~80%)與全期基準的最大差距
        "n_middle_buckets": len(mids),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="S1 breadth→前瞻報酬 事實檔產生器")
    ap.add_argument("--dry-run", action="store_true", help="只印摘要不寫檔")
    args = ap.parse_args()
    print(f"[breadth] 讀 {CACHE_ADJ}…(1900+ 檔,約需 1-2 分鐘)")
    doc = compute()
    if not doc.get("ok"):
        print(f"[breadth] ✗ 算不出來:{doc.get('error')}(不寫檔;週報會降級,不會編數字)")
        return 1
    print(f"[breadth] 期間 {doc['period_start']} ~ {doc['period_end']}｜{doc['n_stocks']} 檔｜"
          f"{doc['baseline']['n_days']} 天({doc['baseline']['n_independent']} 個獨立 {FWD_DAYS} 日期)")
    for r in doc["buckets"]:
        if r["insufficient"]:
            print(f"  breadth {r['lo']}~{r['hi']}%: 樣本不足({r['n_days']} 天)")
        else:
            print(f"  breadth {r['lo']}~{r['hi']}%: {r['n_days']:5d} 天 / {r['n_independent']:3d} 期"
                  f"｜中位 {r['median_fwd_pct']:+.2f}%｜上漲 {r['up_rate_pct']:.1f}%")
    bl = doc["baseline"]
    print(f"  全期基準           : {bl['n_days']:5d} 天 / {bl['n_independent']:3d} 期"
          f"｜中位 {bl['median_fwd_pct']:+.2f}%｜上漲 {bl['up_rate_pct']:.1f}%")
    print(f"  桶間最大差距:{doc['spread_pct_points']} 個百分點")
    if args.dry_run:
        print("[breadth] --dry-run,不寫檔")
        return 0
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT_FILE)          # 原子寫入,與工作室其餘寫檔紀律一致
    print(f"[breadth] ✅ 已寫 {OUT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
