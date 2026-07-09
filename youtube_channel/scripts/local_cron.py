#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local_cron.py — 本機工作室排程器（取代雲端 crontab，讓整套 YT 產線在這台 Windows 電腦跑）。

背景：雲端 droplet 因欠費停權→改在本機跑。這支是常駐程序：
  - 讀 deploy/crontab.txt 的排程（＝雲端同步版），每 60 秒檢查哪些 job 到點就跑。
  - 把 `/root/yt/run.sh scripts/X.py args` 翻譯成本機 `.venv python scripts/X.py args`。
  - 先把專案根 .env 載入環境（OPENROUTER/GEMINI/PEXELS…金鑰），子程序才吃得到。
  - 只跑「本機能跑」的 job；雲端專屬（fileserver.sh/self_heal.sh/flock/純 shell 備份）自動略過。
  - 每個 job 各自 subprocess、非阻塞、逾時保護、寫 logs/local_cron.log。電腦睡著/關機時該時段的 job 會漏（本機跑的先天限制）。

用法：
  .venv\\Scripts\\python.exe scripts\\local_cron.py            # 常駐跑（Ctrl+C 停）
  .venv\\Scripts\\python.exe scripts\\local_cron.py --once      # 只把「現在這分鐘該跑的」跑一次就結束（測試用）
  .venv\\Scripts\\python.exe scripts\\local_cron.py --list      # 印出解析到的排程表，不執行
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
CRONTAB = ROOT / "deploy" / "crontab.txt"
LOG = ROOT / "logs" / "local_cron.log"
ERRLOG = ROOT / "logs" / "job_stderr.log"    # 子程序 stderr 導這裡(補 DEVNULL 盲區:job 靜默失敗可事後查 traceback)
LOCK = ROOT / "STUDIO" / "local_cron.lock"   # 心跳鎖：避免多實例雙發(排程loop每圈更新mtime)


def _lock_fresh() -> bool:
    """另一個 local_cron 是否還活著(鎖檔 60 秒內被更新過=活)。"""
    try:
        if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < 60:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _touch_lock():
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# 雲端專屬、本機不跑的關鍵字（純 shell / 需公網 / 已無意義）。
# 注意：hybrid_render 保留（本機要渲染）；--cloud 是本機渲染路徑要保留，只在下方濾掉 --pc（SFTP 推雲端）。
# IG 引流已解封(2026-07-06):ig_backfill/ig_health_check/ig_token_refresh 本機跑
# (IG token 已在 .env、公網 URL 由 tunnel_up.py 常駐供給)。fileserver 仍 skip=改由 tunnel_up.py 起本機版。
SKIP_MARKERS = ("fileserver", "self_heal", "multipost_upload", "cover_backfill",
                "backups/", "mkdir -p", "date +")


def load_env() -> dict:
    """把專案根 .env 併進 os.environ 的副本，回傳給子程序用。"""
    env = dict(os.environ)
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("LLM_PROVIDER", "openrouter")
    return env


def _log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    print(line, flush=True)


def _cron_field_match(field: str, val: int) -> bool:
    """支援 *  、 a,b 、 a-b 、 */n 、 a-b/n 。"""
    if field == "*":
        return True
    for part in field.split(","):
        step = 1
        rng = part
        if "/" in part:
            rng, s = part.split("/", 1)
            step = int(s)
        if rng == "*":
            lo, hi = None, None
        elif "-" in rng:
            a, b = rng.split("-", 1)
            lo, hi = int(a), int(b)
        else:
            lo = hi = int(rng)
        if lo is None:  # */n
            if val % step == 0:
                return True
        else:
            if lo <= val <= hi and (val - lo) % step == 0:
                return True
    return False


def parse_jobs():
    """解析 crontab.txt → [(min,hour,dom,mon,dow, [py_args...], raw)]。只留本機能跑的 python job。"""
    jobs = []
    if not CRONTAB.exists():
        return jobs
    for raw in CRONTAB.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("SHELL") or s.startswith("PATH"):
            continue
        m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$", s)
        if not m:
            continue
        mi, ho, dom, mon, dow, cmd = m.groups()
        if any(k in cmd for k in SKIP_MARKERS):
            continue
        # 抽出 scripts/X.py 及其參數（run.sh scripts/X.py args >> log）
        mm = re.search(r"(scripts/[A-Za-z0-9_]+\.py)(.*?)(?:\s*>>|\s*2>|\s*$)", cmd)
        if not mm:
            continue
        script = mm.group(1)
        args = mm.group(2).strip()
        arglist = args.split() if args else []
        # 本機渲染：hybrid_render 的 --cloud 其實是「本機檔案+本機鎖渲染待辦」的純本機路徑(run_cloud→make_video)，
        # 必須保留(拿掉會變成無旗標→hybrid_render 印「請指定」直接退出＝什麼都不渲染)。只濾掉 --pc(SFTP 推雲端模式)。
        if "hybrid_render.py" in script:
            arglist = [a for a in arglist if a != "--pc"]
            if "--cloud" not in arglist:
                arglist.insert(0, "--cloud")
        jobs.append((mi, ho, dom, mon, dow, [script] + arglist, s))
    return jobs


def due(job, now: datetime) -> bool:
    mi, ho, dom, mon, dow, _, _ = job
    # cron dow: 0/7=Sun..6=Sat；python weekday(): Mon=0..Sun=6 → 轉換
    py = now.weekday()
    cron_dow = 0 if py == 6 else py + 1
    return (_cron_field_match(mi, now.minute) and _cron_field_match(ho, now.hour)
            and _cron_field_match(dom, now.day) and _cron_field_match(mon, now.month)
            and (_cron_field_match(dow, cron_dow) or _cron_field_match(dow, py)))


def _wait_and_log(proc: subprocess.Popen, script: str):
    """背景執行緒等 job 跑完，寫一行成功/失敗到 log(不擋主排程迴圈)。"""
    try:
        rc = proc.wait()
        if rc == 0:
            _log(f"✓ 完成 {script}")
        else:
            _log(f"✗ 失敗 {script}（exit {rc}，詳見 job_stderr.log）")
    except Exception as exc:  # noqa: BLE001
        _log(f"✗ 監控失敗 {script}: {exc}")


def run_job(pyargs, env):
    script = pyargs[0]
    try:
        # 子程序 stderr 導到 job_stderr.log(取代 DEVNULL):job 靜默失敗會留 traceback 可事後查。
        # 檔過大(>5MB)先截斷,避免無限長。父端開檔傳給 Popen,子程序繼承 fd 後父端關閉不影響子寫入。
        ERRLOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            if ERRLOG.exists() and ERRLOG.stat().st_size > 5_000_000:
                ERRLOG.write_text("", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        errf = open(ERRLOG, "a", encoding="utf-8")
        errf.write(f"\n===== [{datetime.now():%Y-%m-%d %H:%M:%S}] {' '.join(pyargs)} =====\n")
        errf.flush()
        proc = subprocess.Popen([str(VENV_PY), script] + pyargs[1:], cwd=str(ROOT), env=env,
                                 stdout=subprocess.DEVNULL, stderr=errf)
        errf.close()  # 子程序已繼承 fd,父端關閉安全
        _log(f"▶ 啟動 {' '.join(pyargs)}")
        # 非阻塞：另開背景執行緒等它跑完再補一行成功/失敗(job 常跑數分鐘，不能卡住排程迴圈)。
        threading.Thread(target=_wait_and_log, args=(proc, script), daemon=True).start()
    except Exception as exc:  # noqa: BLE001
        _log(f"✗ 啟動失敗 {script}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只跑此刻該跑的一次就結束")
    ap.add_argument("--list", action="store_true", help="印排程表不執行")
    args = ap.parse_args()

    jobs = parse_jobs()
    if args.list:
        print(f"解析到 {len(jobs)} 個本機 job：")
        for j in jobs:
            print(f"  {j[0]} {j[1]} {j[2]} {j[3]} {j[4]}  {' '.join(j[5])}")
        return 0

    if _lock_fresh():
        _log("另一個 local_cron 已在跑(心跳鎖 60s 內),本實例退出避免雙發。")
        return 0
    _touch_lock()

    env = load_env()
    if args.once:
        now = datetime.now()
        n = 0
        for j in jobs:
            if due(j, now):
                run_job(j[5], env); n += 1
        _log(f"--once：本分鐘跑了 {n} 個 job")
        return 0

    _log(f"本機工作室排程器啟動：{len(jobs)} 個 job（Ctrl+C 停）。LLM={env.get('LLM_PROVIDER')}")
    last_min = None
    # bug 修復(2026-07-09)：jobs 原本只在啟動時 parse 一次，crontab.txt 之後的改動(如新增
    # tiktok_upload 跨發排程)在本實例存活期間永遠不會生效，只能靠人手動重啟才會吃到——
    # 排程「看起來對」實際上不會跑，很難察覺。改成每分鐘連同 .env 一起重讀 crontab.txt。
    while True:
        now = datetime.now()
        cur = now.strftime("%Y%m%d%H%M")
        _touch_lock()            # 每圈更新心跳鎖(讓其他實例知道我還活著)
        if cur != last_min:      # 每分鐘只判定一次
            last_min = cur
            env = load_env()     # 每分鐘重讀 .env（金鑰換了即生效）
            jobs = parse_jobs()  # 每分鐘重讀 crontab.txt（排程改動免重啟即生效）
            for j in jobs:
                if due(j, now):
                    run_job(j[5], env)
        time.sleep(20)


if __name__ == "__main__":
    raise SystemExit(main())
