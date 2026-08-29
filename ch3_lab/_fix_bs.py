# -*- coding: utf-8 -*-
"""把 heredoc 吃掉反斜線留下的退格字元(0x08)改回字面上的 \\b。

⚠️ **這支必須用 Write 工具建檔,不能用 heredoc 執行** ——
用 heredoc 的話,替換字串 b"\\\\b" 會被 shell 再吃一次變成 b"\\b" = 0x08,
於是變成拿 0x08 取代 0x08 的無操作。我今天就這樣白修了一次。
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BS = bytes([0x08])
REPL = bytes([0x5C, 0x62])          # 反斜線 + b,用碼點寫,不寫字面量

for name in ("make_lineup.py",):
    p = pathlib.Path(__file__).resolve().parent / name
    raw = p.read_bytes()
    n = raw.count(BS)
    if n:
        p.write_bytes(raw.replace(BS, REPL))
    print(f"{name}: 修掉 {n} 個退格字元")
