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
    # 順帶實測跨 session 程序可見性:S4U(session 0)下看不看得到互動 session 的 local_cron。
    # ≥2 行=跨 session 可見,watchdog 的雙發疑慮出清;0 行/None=看不到,要回報(危險格)。
    try:
        import local_cron_watchdog as wd
        procs = wd.cron_procs()
        vis = "None(查詢失敗)" if procs is None else str(len(procs))
    except Exception as e:
        vis = f"error={e!r}"
    OUT.write_text(f"[{now}] sent={ok} cron_procs_visible={vis}\n", encoding="utf-8")
except Exception as e:
    OUT.write_text(f"[{now}] sent=False error={e!r}\n", encoding="utf-8")
