#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""binge_report.py — 追劇鏈成效報告:對比佈署前後的連播訊號(只報告,不動產線)。

## 為什麼要有這支(2026-08-22)
追劇鏈 2026-08-21 開始鋪(225 支長片、環狀、帶連播軌),佈署前的基準已存
STUDIO/binge_baseline.json(28 天:PLAYLIST 來源 49 觀看/131 分鐘、RELATED 1119/2529)。
沒有對比報告的話,一週後只能憑感覺說「好像有用」——本專案的鐵律是
優化任何東西之前先驗它動了什麼(memory yt-quality-score-not-predictive)。

## 判讀口徑(寫死,防未來的自己動歪)
- 對比視窗:佈署日(08-21)之後的 N 天 vs 基準檔裡同長度的舊視窗**平均日值**。
  兩邊不等長就換算成「每日」再比(memory yt-analytics-lag-false-alarm:等長才可比)。
- 看三個訊號,方向都該向上:
    PLAYLIST 來源觀看(點了連播軌的人)
    RELATED_VIDEO 來源觀看(影片間關聯被強化)
    每觀看秒數(接著看的人看得比較久)
- Analytics 延遲 2~4 天:endDate 錨在 today-3,不夠 4 天完整資料就直說「還不能比」。
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

DEPLOY = date(2026, 8, 21)
BASELINE = ROOT / "STUDIO" / "binge_baseline.json"


def main() -> int:
    import yt_analytics as ya
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    b_src = base.get("sources", {})
    b_days = 28

    end = date.today() - timedelta(days=3)
    start = DEPLOY + timedelta(days=1)          # 佈署當天混雜,從隔天起算
    n_days = (end - start).days + 1
    if n_days < 4:
        print(f"佈署後完整資料只有 {n_days} 天(<4),還不能比。等到 {DEPLOY + timedelta(days=8)} 再看。")
        return 0

    svc = ya._service()
    r = svc.reports().query(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        dimensions="insightTrafficSourceType",
        metrics="views,estimatedMinutesWatched", sort="-views", maxResults=25).execute()
    cur = {row[0]: (row[1], row[2]) for row in (r.get("rows") or [])}

    print(f"追劇鏈成效(佈署 {DEPLOY};佈署後 {start}~{end} 共 {n_days} 天 vs 舊 28 天基準,皆換算每日)\n")
    print(f"{'來源':<16}{'基準/日':>10}{'現在/日':>10}{'變化':>9}")
    for k in ("PLAYLIST", "RELATED_VIDEO", "YT_CHANNEL", "SUBSCRIBER", "YT_SEARCH"):
        bv = (b_src.get(k, [0, 0])[0]) / b_days
        cv = cur.get(k, (0, 0))[0] / n_days
        chg = f"{100 * (cv - bv) / bv:+.0f}%" if bv else ("新增" if cv else "—")
        print(f"{k:<16}{bv:>10.1f}{cv:>10.1f}{chg:>9}")
    # 每觀看秒數(全來源)
    b_tot_v = sum(v[0] for v in b_src.values())
    b_tot_m = sum(v[1] for v in b_src.values())
    c_tot_v = sum(v[0] for v in cur.values())
    c_tot_m = sum(v[1] for v in cur.values())
    if b_tot_v and c_tot_v:
        print(f"\n每觀看秒數:基準 {60 * b_tot_m / b_tot_v:.0f}s → 現在 {60 * c_tot_m / c_tot_v:.0f}s")
    print("\n判讀:PLAYLIST/RELATED/每觀看秒數三軸都升 = 鏈在起作用;"
          "只有一軸動 = 繼續觀察;都沒動 = 一週後檢討鏈的位置與文案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
