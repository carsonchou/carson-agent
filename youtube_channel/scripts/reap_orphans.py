#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reap_orphans.py — 殭屍程序清理安全網(Windows)。

只針對「單例服務」:tunnel_up / fileserver_local / 決策中心 web_center server。
這幾個若因任何 bug 重複累積,只保留最新的幾個、砍掉舊的重複份。
tunnel --ensure 的爆增根因已在 tunnel_up.py 修掉,這支是額外安全網——防未來任何累積。

鐵律(避免誤殺):
- 絕不碰 local_cron(排程器本體)、produce_batch/make_video/quality_score/daily_publish/
  hybrid_render/news_dept 等產片發布 job、或任何不在白名單特徵內的程序。
- 只保留每個服務「最新 N 個」,砍其餘;剛 spawn 的新程序一定在最新 N 內→不會被誤殺。
- 全程 log,可查收了什麼。

排程:cron 每 30 分跑一次。手動:python scripts/reap_orphans.py [--dry-run]
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):  # noqa: ARG001
        pass

# 單例服務特徵字 → 保留最新幾個(父子暫態故留 2)
SINGLETONS = {
    "tunnel_up.py": 2,
    "fileserver_local.py": 2,
    "web_center": 2,  # 決策中心 server.py(用 web_center 路徑特徵,不誤殺其他 server.py)
}
# 白名單:命中這些字的程序一律不碰(排程器本體+產片發布 job)
NEVER_KILL = ("local_cron", "produce_batch", "make_video", "quality_score",
              "daily_publish", "hybrid_render", "news_dept", "render_", "reap_orphans")


def _ps(cmd: str) -> str:
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                              capture_output=True, text=True, timeout=30).stdout
    except Exception as e:  # noqa: BLE001
        print(f"[reap] powershell 失敗:{e}", file=sys.stderr)
        return ""


def _list_python():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "ForEach-Object { \"$($_.ProcessId)`t$($_.CreationDate.Ticks)`t$($_.CommandLine)\" }")
    procs = []
    for line in _ps(ps).splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        try:
            procs.append((int(parts[0].strip()), int(parts[1].strip()), parts[2]))
        except Exception:  # noqa: BLE001
            continue
    return procs


def main() -> int:
    dry = "--dry-run" in sys.argv
    procs = _list_python()
    reaped = []
    for feat, keep in SINGLETONS.items():
        group = [p for p in procs if feat in p[2] and not any(k in p[2] for k in NEVER_KILL)]
        group.sort(key=lambda p: -p[1])  # 建立時間新→舊
        for pid, _ticks, _cmd in group[keep:]:  # 留最新 keep 個,其餘砍
            reaped.append((feat, pid))
            if not dry:
                _ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    total = len(procs)
    if reaped:
        msg = f"收掉 {len(reaped)} 個重複程序(python 總數 {total}→{total - len(reaped)}):" + \
              ", ".join(f"{f}#{p}" for f, p in reaped[:20])
        log_ops("殭屍清理", msg)
        print(f"[reap]{'(dry)' if dry else ''} {msg}")
    else:
        print(f"[reap] 無重複單例程序,乾淨(python 總數 {total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
