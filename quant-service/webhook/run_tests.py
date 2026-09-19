# -*- coding: utf-8 -*-
"""run_tests.py — 一鍵跑電商金流 webhook 單元測試。

pytest（推薦，任務要求）：
  python -m pytest quant-service/webhook/tests -q
標準庫 unittest（無 pytest 依賴，等價）：
  python quant-service/webhook/run_tests.py
全部不連外網、不寫正式檔（tmp 路徑 + 注入假 adder/sender + dry_run 紀律）。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tests"))       # 讓測試 import _util
sys.path.insert(0, str(HERE.parent))          # quant-service，讓 import webhook.* 可用

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(HERE / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
