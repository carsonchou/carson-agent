# -*- coding: utf-8 -*-
"""principal 修正驗收:在排程任務的新(S4U)上下文裡實測 ntfy 送不送得出去。
結果寫進 docs/ops/principal_fix_ntfy_test.txt(正向輸出:成敗都留檔)。"""
import sys, pathlib, datetime
sys.path.insert(0, r"D:\carson-agent\youtube_channel\scripts")
OUT = pathlib.Path(r"D:\carson-agent\docs\ops\principal_fix_ntfy_test.txt")
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
try:
    from notify import push
    ok = push("[驗收] S4U 上下文 ntfy 實測", "排程新上下文送出;收到這則=通道在 S4U 下活著,可忽略")
    OUT.write_text(f"[{now}] sent={ok}\n", encoding="utf-8")
except Exception as e:
    OUT.write_text(f"[{now}] sent=False error={e!r}\n", encoding="utf-8")
