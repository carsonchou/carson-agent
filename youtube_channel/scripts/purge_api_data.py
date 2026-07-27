#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purge_api_data.py — 【合規控制】刪除逾期的第三方 YouTube API 資料。

為什麼要有這支(2026-07-28 稽核發現):
  YouTube API Services Developer Policies **III.E.4.d** 要求:透過 API 取得並儲存的資料,
  必須在 30 天內刷新或刪除。本產線用官方 `search.list` 取得他人影片的**公開 metadata**
  (標題/頻道名/觀看數)做選題研究,寫成報告存在 STUDIO/REPORTS/。

  舊狀況是**不合規的**:清除邏輯只存在 intel_dept.purge_stale_reports(),而它
  ①只掃 `*_競品情報.md` 一種檔名 → `*_異常爆款.md`(outlier_scan 產出,同樣含他人頻道
    標題/頻道名)**從來沒被清過**;
  ②掛在每週六才跑的 intel_dept 上 → 就算掃得到,最壞也可能拖到第 37 天才刪。
  實測 2026-07-28:逾 30 天未清的第三方報告共 17 份(異常爆款 9 + 競品情報 8),
  最舊到 2026-06-16。這是真實的政策違規,不只是文件問題。

  故獨立成一支**每日**跑的合規控制:清乾淨、可稽核、與產生資料的部門解耦
  (產生的人不負責刪,是這個洞的根因)。純本機檔案刪除,**不耗任何 API 配額**。

保留期為什麼設 25 天而不是 30:留 5 天安全邊際,萬一某天排程沒跑(電腦關機/lock 殘留)
也不會立刻越線。政策是上限不是目標。

不清什麼:`*_爆款獵手.md` 是**自家頻道**資料(從 quality_scores.json 算,非 API 取得的
他人資料),不受 III.E.4.d 規範,保留供長期成長分析。

用法:
  python scripts/purge_api_data.py            # 執行清除
  python scripts/purge_api_data.py --dry-run  # 只列出會刪什麼,不動檔
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "STUDIO" / "REPORTS"

# 含「透過 API 取得的他人公開 metadata」的報告檔名樣式(III.E.4.d 規範對象)
THIRD_PARTY_PATTERNS = (
    "*_競品情報.md",    # intel_dept — search.list 找同題材影片
    "*_異常爆款.md",    # outlier_scan — search.list 找高倍率爆款
)
RETENTION_DAYS = 25

# 🔴 2026-07-28 二修(獨立審查抓到第一版漏掉的):同類第三方資料還躺在兩個 **JSON** 裡,
# 而它們**沒有任何刪除或刷新機制**——只有在產生它的部門重跑時才被覆寫,而 intel_dept 是
# 每週六才跑。只要連續幾週沒跑(電腦關機/job 失敗),就會靜默超過 30 天。
#   · STUDIO/outliers.json — outlier_scan.py:169 寫,含 id/title/**channel**/views(他人頻道名)
#   · STUDIO/intel.json    — intel_dept.py:143 寫,含 "channel": "LuxAlgo" 等他人頻道名
# 這跟這支腳本一開始要修的根因**一模一樣**(產生的人不負責刪)。而改寫後的 _privacy.md 已經
# 對外承諾「30 天自動清除」,那份是要當公開 URL 送 Google 稽核的 → 不補完就是不實陳述。
# 用**檔案 mtime** 判齡(這兩個檔是整份覆寫,mtime 即該批資料的取得時間)。
# 消費端(parasite_titles.py:60-80、trend_hijack)讀取都包在 try/except 內,缺檔不會壞。
THIRD_PARTY_JSONS = ("outliers.json", "intel.json")


def purge(days: int = RETENTION_DAYS, dry_run: bool = False) -> tuple[int, list]:
    """刪除檔名日期早於 cutoff 的第三方資料報告。回 (刪除數, 檔名清單)。
    檔名格式為 YYYY-MM-DD_*.md,ISO 日期可直接字串比較(同 intel_dept 既有慣例)。"""
    if not REPORTS.is_dir():
        return 0, []
    cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)).strftime("%Y-%m-%d")
    hit = []
    for pat in THIRD_PARTY_PATTERNS:
        for p in REPORTS.glob(pat):
            if p.name[:10] < cutoff:
                hit.append(p)
    # 第三方 metadata 的 JSON(見 THIRD_PARTY_JSONS 註解):用 mtime 判齡
    import time as _time
    cutoff_ts = _time.time() - days * 86400
    for fn in THIRD_PARTY_JSONS:
        jp = ROOT / "STUDIO" / fn
        try:
            if jp.exists() and jp.stat().st_mtime < cutoff_ts:
                hit.append(jp)
        except OSError:
            pass
    n = 0
    for p in hit:
        if dry_run:
            n += 1
            continue
        try:
            p.unlink()
            n += 1
        except OSError as e:
            print(f"[warn] 刪不掉 {p.name}: {e}", file=sys.stderr)
    return n, [p.name for p in hit]


def main() -> int:
    ap = argparse.ArgumentParser(description="合規控制:刪除逾期的第三方 YouTube API 資料(III.E.4.d)")
    ap.add_argument("--days", type=int, default=RETENTION_DAYS,
                    help=f"保留天數(預設 {RETENTION_DAYS};政策上限 30,留 5 天安全邊際)")
    ap.add_argument("--dry-run", action="store_true", help="只列出會刪什麼,不實際刪除")
    args = ap.parse_args()

    n, names = purge(args.days, args.dry_run)
    tag = "[dry-run] 會刪" if args.dry_run else "已刪除"
    print(f"{tag} {n} 份逾 {args.days} 天的第三方 API 資料報告")
    for nm in names[:20]:
        print(f"   - {nm}")
    if len(names) > 20:
        print(f"   ... 另 {len(names) - 20} 份")
    if n and not args.dry_run:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from ops import log_ops
            log_ops("合規", f"清除逾 {args.days} 天第三方 API 資料 {n} 份(Dev Policies III.E.4.d)")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
