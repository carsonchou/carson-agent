#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_studio.py — 每天把關鍵 STUDIO json 複製一份存檔，補本機沒有 backups 的安全網。

只複製「壞了會很痛」的關鍵檔到 STUDIO/_snapshots/YYYY-MM-DD/，保留最近 7 天、舊的自動刪。
純標準庫、防缺檔(缺哪個就跳過那個，不中斷)。

用法：python scripts/snapshot_studio.py
"""
from __future__ import annotations
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
SNAP_ROOT = STUDIO / "_snapshots"
TW = timezone(timedelta(hours=8))
KEEP_DAYS = 7

# 關鍵檔：STUDIO 內的用檔名，ROOT 內的用相對路徑
KEY_FILES = [
    STUDIO / "uploaded_ledger.json",
    STUDIO / "boss_directives.json",
    STUDIO / "quality_scores.json",
    STUDIO / "topic_bank.json",
    STUDIO / "ep_data.json",
    # 🔴 2026-09-07 補入：已發布個股體檢片「憑什麼那樣說」的**唯一**憑據。
    # 7,742 組事實，每組含 claim/method/period/source/computed_at/raw data，
    # 198 支已發布片裡 177 支的那一組**還是當初那一組**(覆寫率 1/198)。
    # 為什麼之前不在這份清單：雲端 `crontab.txt:546` 的每日備份 `cp STUDIO/*.json`
    # 本來就涵蓋它，而那行是 `cd /root/yt` —— **droplet 2026-07-05 停權後就再沒跑過**
    # (`local_cron.py:9` 明文「純 shell 備份自動略過」，`backups/` 目錄不存在)。
    # 這支腳本是那個備份的本機替代品，但清單只搬了 7 個檔、漏掉事實庫
    # ⇒ **07-05 起事實庫零自動備份，零訊號**。
    # ⚠️ 2026-09-09 更新：**下面這段描述的三環都已經修掉了,別再照它下判斷。**
    #    原文(留著示範壞在哪):「寫入端 `merge_and_write` 是整檔 `write_text` 覆寫、無
    #    tmp→replace，讀取端 `_load_existing()` 的 `except: pass` 會把讀壞的檔靜默降級成
    #    空骨架再寫回去 ⇒ 一次失敗就從 7,742 組掉到剩幾組，而它照樣印「已寫入」。」
    #    現況:讀取端 fail-closed(`b5e69e69`/`9d289f83`)、寫入端 tmp→讀回比對→`os.replace`
    #    + 縮水下限 + 結構不變量、「已寫入」改成通過驗證後才印。
    # 🔴 但**這支腳本自己仍然是那條鏈上最後一道**:它是唯一的自動備份,
    #    而 `:109` 的 `rmtree(KEEP_DAYS=7 之外)` 是**執行刪除的那把刀**。
    #    2026-09-09 實測:7 個快照夾裡只有 2 個含這個檔(它 09-07 才進 KEY_FILES)
    #    ⇒ **復原窗口當時是 2 天不是 7 天**(每天自己長一天,約 09-14 補滿)。
    #    改 KEEP_DAYS 或改 KEY_FILES 之前先算一次「現在真正回溯得到幾天」,不要看常數。
    STUDIO / "stock_checkup_facts.json",
]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def _today() -> str:
    return datetime.now(TW).strftime("%Y-%m-%d")


def _prev_snapshot_dir(today: str):
    """回傳今天之前最近一份快照資料夾，沒有就回 None。"""
    if not SNAP_ROOT.exists():
        return None
    days = sorted(d for d in SNAP_ROOT.iterdir() if d.is_dir() and d.name < today)
    return days[-1] if days else None


def snapshot_once() -> int:
    dest = SNAP_ROOT / _today()
    dest.mkdir(parents=True, exist_ok=True)
    prev = _prev_snapshot_dir(_today())
    copied = 0
    for f in KEY_FILES:
        try:
            if f.exists():
                shutil.copy2(f, dest / f.name)
                copied += 1
                # 🔴 正向輸出：每次都印大小與「和上一份快照的差」。
                # 這些檔全都是「讀全檔 → merge → 整檔覆寫」的形狀，失敗形態是
                # **靜默縮水**(讀壞→空骨架→寫回)，rc=0、有檔案、有「已寫入」訊息，
                # 三個表面全部正常。體積是唯一會不一樣的東西。
                # 照 dispatch.md「規則要嘛是檢查，要嘛是期望」：不印數字的話，
                # 這種失敗和從沒發生過在 log 上長得一模一樣。
                # ⚠️ 這裡只印不擋 —— 備份腳本自己絕不可以因為判斷而少備份一個檔。
                try:
                    cur = f.stat().st_size
                    old = (prev / f.name).stat().st_size if prev and (prev / f.name).exists() else None
                    if old is None:
                        print(f"[size] {f.name}: {cur:,} bytes（無前一份可比）")
                    else:
                        d = cur - old
                        pct = (d / old * 100) if old else 0.0
                        mark = "  🔴 縮水超過一成" if old and d < 0 and abs(pct) >= 10 else ""
                        print(f"[size] {f.name}: {cur:,} bytes（前次 {old:,}，差 {d:+,} / {pct:+.1f}%）{mark}")
                except Exception:  # noqa: BLE001
                    pass
            else:
                print(f"[skip] 不存在，略過：{f.name}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 複製失敗 {f.name}: {e}", file=sys.stderr)
    print(f"[ok] 快照完成：{dest}（{copied}/{len(KEY_FILES)} 個檔）")
    return copied


def prune_old() -> int:
    """保留最近 KEEP_DAYS 天的快照資料夾，舊的刪掉。"""
    if not SNAP_ROOT.exists():
        return 0
    days = sorted([d for d in SNAP_ROOT.iterdir() if d.is_dir()], key=lambda d: d.name)
    removed = 0
    for d in days[:-KEEP_DAYS] if len(days) > KEEP_DAYS else []:
        try:
            shutil.rmtree(d)
            removed += 1
            print(f"[ok] 刪除過期快照：{d.name}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 刪除失敗 {d.name}: {e}", file=sys.stderr)
    return removed


def main() -> int:
    copied = snapshot_once()
    pruned = prune_old()
    log_ops("STUDIO快照", f"快照 {copied} 個檔，清掉 {pruned} 個過期資料夾")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
