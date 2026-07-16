"""pytest 前置：把 tests 目錄與 quant-service 掛上 sys.path，讓 `import _util`
與 `import webhook.*` 在 pytest 與 unittest 兩種跑法下都可用（tests 非 package）。"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_QS = _HERE.parents[1]                 # quant-service
for p in (str(_HERE), str(_QS)):
    if p not in sys.path:
        sys.path.insert(0, p)
