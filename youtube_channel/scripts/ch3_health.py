#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ch3_health.py — ch3 的每日健檢 + 帳本備份的排程包裝器。

## 為什麼要這支 wrapper
`local_cron` **只認 `youtube_channel/scripts/` 底下的 python 檔**,crontab 裡
寫 `../ch3_lab/health.py` 或原始 shell 指令都不會被解析、也不會跑 ——
而且是**靜默**不跑,不會有任何錯誤訊息。這個坑 ch3_publish.py 也踩過,
所以它才在這個目錄裡。

做兩件事:
1. 跑 `ch3_lab/health.py`(有事才推播)
2. 備份三本帳(`uploaded*.json`)+ 發布清單

## 為什麼帳本要備份
`uploaded*.json` 是**唯一**防止重傳的東西。弄丟等於把已經上線的片再發一次
—— 那不只浪費配額,還會在頻道上留下重複影片,而 YouTube 對重複內容的
態度跟模板化量產是同一條線。主頻道 04:15 備份 STUDIO,ch3 跟同一個節奏。

用法(排程用):
  python scripts/ch3_health.py
"""
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent   # D:\carson-agent
CH3 = ROOT / "ch3_lab"
PY = ROOT / "youtube_channel" / ".venv" / "Scripts" / "python.exe"
KEEP_DAYS = 14


def backup():
    """帳本備份。保留 14 份,舊的刪掉。"""
    dst = CH3 / "_backup" / datetime.now().strftime("%Y%m%d")
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for pat in ("uploaded*.json", "publish_meta.json"):
        for f in CH3.glob(pat):
            shutil.copy2(f, dst / f.name)
            n += 1
    olds = sorted((CH3 / "_backup").iterdir(), reverse=True)[KEEP_DAYS:]
    for o in olds:
        shutil.rmtree(o, ignore_errors=True)
    print(f"  備份 {n} 個檔 → {dst}(保留最近 {KEEP_DAYS} 份,"
          f"清掉 {len(olds)} 份舊的)")


def main():
    print(f"=== ch3 健檢 {datetime.now():%Y-%m-%d %H:%M} ===")
    try:
        backup()
    except Exception as e:                                    # noqa: BLE001
        # 備份失敗不該擋掉健檢 —— 但也不能靜默,那是這條線最常見的失敗形態。
        print(f"  ⛔ 備份失敗:{str(e)[:80]}")
    # 縮圖補件:`thumbnails.set` 有速率限制(跟配額是兩回事),一次推 11 支
    # 會有七支吃 429。所以每天補 3 支讓它自己收斂 —— 主頻道的
    # `thumb_backfill --scavenge` 是同一個作法。
    tb = CH3 / "thumb_backfill.py"
    if tb.exists():
        rt = subprocess.run([str(PY), str(tb), "--max", "3"], cwd=str(ROOT),
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        for ln in (rt.stdout or "").splitlines():
            if ln.strip() and ("✓" in ln or "⛔" in ln or "不同步" in ln
                               or "補上" in ln):
                print(f"  {ln.strip()}")

    # 觀看數快照:**一個數字不是趨勢**。2026-08-29 發現 ep001 的 Short 有
    # 107 次觀看(全頻道其餘 0~9),但手上只有一個時間點的值,分不出
    # 「新片沒人看」與「新片才 8 小時」。每天存一筆,才回答得了改版有沒有用。
    # 配額:每 50 支 1 單位。
    sv = CH3 / "snapshot_views.py"
    if sv.exists():
        rs = subprocess.run([str(PY), str(sv)], cwd=str(ROOT),
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        for ln in (rs.stdout or "").splitlines():
            if "快照" in ln:
                print(f"  {ln.strip()}")

    r = subprocess.run([str(PY), str(CH3 / "health.py")], cwd=str(ROOT),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print(r.stdout[-2000:])
    if r.stderr.strip():
        print(r.stderr[-600:])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
