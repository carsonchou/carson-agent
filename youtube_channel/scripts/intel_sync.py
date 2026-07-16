#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intel_sync.py — 【已停用】原「本機大量競品學習 → 推 playbook 回雲端」入口。

2026-07-17 合規清理：本檔原本呼叫 intel_dept.py --max-learn 在本機大量下載他人頻道的
字幕/音訊做競品學習(違反 YouTube ToS，頻道存續風險)，再把學來的 competitor_analysis.md
SFTP 推回雲端工廠。該能力已整段移除：

  - intel_dept.py 的 yt-dlp 下載/Whisper 轉錄/deep_learn 已刪除，只留官方 API 輕量情報。
  - --max-learn / --pace 參數已不存在，本檔原本的呼叫方式已無對應功能。
  - Windows 排程 QuantArsen_IntelLearn 已 Disabled。
  - 抓來的資料(intel_seen.json、competitor_analysis.md、playbook 自動增補區)已清除。

本檔保留為明確 no-op：舊排程/舊捷徑若仍指向這裡，會印訊息並正常結束(exit 0)，不做任何事。
⚠️ 請勿把下載能力加回來——「產線不下載/不儲存他人頻道內容」是送 Google 配額稽核的承諾。
確認無人再呼叫後即可整檔刪除。
"""
from __future__ import annotations
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> int:
    print("[no-op] intel_sync 已停用：競品下載/轉錄學習能力已於 2026-07-17 移除(YouTube ToS 合規)。")
    print("        競品情報改由 scripts/intel_dept.py 走官方 API 產輕量報告(唯讀公開 metadata)。")
    print("        本檔不再執行任何動作，也不再推送任何檔案到雲端。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
