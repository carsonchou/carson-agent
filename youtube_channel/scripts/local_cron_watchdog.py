#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local_cron_watchdog.py — 排程器死了就把它拉回來。

## 為什麼(2026-09-03)
`local_cron.py` 是整套 YT 產線唯一的排程器(雲端 droplet 停權後改本機常駐)。
它死了**沒有任何東西會把它拉起來**,而且是靜音的:窗格關掉、程序被殺、
重開機之後不會有錯誤訊號,只會「今天沒發片」——要等到有人回頭看才發現。
14 支 `QuantArsen_*` Windows 排程都是 Disabled,那是 6/14 搬本機前的舊機制,
**刻意保持關閉**(它們跑的是同一批腳本,打開等於每天發兩次片、燒兩份配額)。
所以補救不是啟用它們,是這支 watchdog。

## 判準:心跳鎖的 mtime,不是「程序在不在」
`local_cron.py` 每圈(約 20 秒)`_touch_lock()` 更新 `STUDIO/local_cron.lock` 的
mtime。**程序活著不代表迴圈還在轉**——卡死的程序在工作管理員裡看起來一模一樣。

## 三種情況,只有一種會動手
| 心跳 | 有沒有 local_cron 程序 | 動作 |
|------|------------------------|------|
| 新鮮(0 ≤ age < 180s) | — | 什麼都不做 |
| 陳舊(含 age < 0) | **沒有** | 拉起來(唯一會動手的情況) |
| 陳舊 | **有** | **不動手**,寫告警 + 推播 |

第三種是卡死或半死,故意不處理:那個程序隨時可能自己恢復,而兩個迴圈同時
活著就會**雙發**(`daily_publish.py` 的 `uploaded_ledger.json` 是發布後才寫的
檔案台帳、沒有程序鎖,兩個實例會挑到同一批 slug 各發一次)。要不要殺它交給人。

## 🔴 防雙發到底靠什麼(2026-09-03 獨立驗證員糾正)
本檔原本宣稱「local_cron 的 `_lock_fresh()` 是第二道保險」——**那是錯的**:
watchdog 要心跳 ≥180 秒才出手,而 `_lock_fresh()` 判活門檻是 60 秒,兩個門檻
**零重疊**,watchdog 出手的每一次那道保險必定已經失效。教訓是:看到「有個鎖」
就當成保險,而沒有把兩個門檻的數字擺在一起比。

## 查不到就不動手
查程序失敗一律當作「有在跑」,絕不盲目重啟(沿用 brain_miner_watchdog 的
fail-safe;那支 2026-09-01 因為比對名單漏了自己拉起來的 wrapper,每 20 分鐘
多拉一個,實測疊到 9 個互相 429)。
判「查詢失敗」用**正向 sanity check**:watchdog 自己就是 python 程序,查詢結果
至少要有一行含 python,零行就是這條管道壞了——不去猜 returncode。
(舊版寫成 `rc != 0 and not stdout`,兩個條件同時成立才算失敗;而 wmic 在
Windows 24H2 起是可移除元件,退化時最可能的表現正是「rc≠0 + stdout 有話」
—— 最可能發生的故障剛好落在最危險的那一格,會盲目重啟。)

## 用法
    pythonw.exe scripts\\local_cron_watchdog.py            # 排程用(無視窗)
    python.exe  scripts\\local_cron_watchdog.py --status   # 只印現況,不動手
    python.exe  scripts\\local_cron_watchdog.py --dry-run  # 印出會做什麼,不動手
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
TARGET = ROOT / "scripts" / "local_cron.py"
LOCK = ROOT / "STUDIO" / "local_cron.lock"
LOG = ROOT / "logs" / "local_cron_watchdog.log"
BOOTLOG = ROOT / "logs" / "local_cron_boot.log"        # 被拉起來那個實例的 stderr
ALERT = ROOT / "STUDIO" / "local_cron_watchdog_alert.json"
PUSH_STATE = ROOT / "STUDIO" / "local_cron_watchdog_push.json"

STALE_SEC = 180           # local_cron 每 ~20 秒更新一次;180 秒 = 連續漏 9 次才算死
VERIFY_SEC = 45           # 拉起後最多等多久確認心跳真的恢復
PUSH_COOLDOWN_SEC = 3600  # 同一種狀況一小時內只推一次(排程每 5 分鐘跑)
NO_WINDOW = 0x08000000    # CREATE_NO_WINDOW:pythonw 底下不帶這個,每 5 分鐘閃一次黑窗
MARK = "local_cron.py"    # 指令列特徵("local_cron_watchdog.py" 不含這個子字串)


def _log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    print(line, flush=True)


def heartbeat_age() -> float | None:
    """鎖檔幾秒前被更新過。None = 鎖檔不存在或讀不到。可能為負(時鐘回撥)。"""
    try:
        if not LOCK.exists():
            return None
        return time.time() - LOCK.stat().st_mtime
    except Exception:  # noqa: BLE001
        return None


def _fresh(age: float | None) -> bool:
    """🔴 負數不算新鮮:時鐘回撥或 mtime 被設到未來時 age < 0,舊版寫 `age < STALE_SEC`
    會成立 → 永遠 noop → watchdog 永久失明,而且不會有任何訊號。"""
    return age is not None and 0 <= age < STALE_SEC


def cron_procs() -> list[str] | None:
    """指令列含 local_cron.py 的 python 程序。None = 查詢失敗(fail-safe 用)。

    tasklist 看不到參數會誤判,一定要查 command line(wmic 優先,失敗退 CIM)。
    ⚠️ 單一個 local_cron 正常就會回 2 筆:venv 的轉發 stub + 真直譯器(父子)。
    """
    for cmd in (
        ["wmic", "process", "where", "name like '%python%'", "get", "commandline"],
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" "
         "| Select-Object -ExpandProperty CommandLine"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                               creationflags=NO_WINDOW)
        except Exception:  # noqa: BLE001
            continue
        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        # 正向 sanity check:自己就是 python 程序,查得到東西就一定有 python 那幾行。
        if not any("python" in ln.lower() for ln in lines):
            continue                      # 這條管道壞了 → 換下一條
        return [ln for ln in lines if MARK in ln and "watchdog" not in ln]
    return None                           # 兩條管道都壞 → 查詢失敗,不動手


def _push(reason: str, title: str, body: str) -> None:
    """推到 Carson 手機。告警只寫進 JSON 檔沒有人會看=不會叫的檢查。

    🔴 冷卻狀態存在**獨立**的 push_state.json,不跟 alert 檔共用。
    舊版共用 alert 檔,而 `write_alert()` 剛把 epoch 設成 now、reason 字彙又跟
    推播 key 是兩套,實測結果:hung/failed 冷卻從不生效(每 5 分鐘炸一次手機),
    restarted 冷卻永遠生效(唯一代表「產線出過事」的那則**一次也沒送出過**)。
    """
    try:
        st = json.loads(PUSH_STATE.read_text(encoding="utf-8")) if PUSH_STATE.exists() else {}
    except Exception:  # noqa: BLE001
        st = {}
    rec = st.get(reason, 0)
    if not isinstance(rec, dict):          # 舊格式是裸 epoch,原地升級不清狀態
        rec = {"ts": float(rec or 0), "n": 1 if rec else 0, "last": float(rec or 0)}
    now = time.time()
    # 🔴 計數要能歸零,而歸零的判準是「**距離上一次事件**多久」,不是「距離視窗開始」。
    # 只看視窗會把「相隔兩小時各出事一次」算成連續第 2 次(實測 FAIL)——
    # 那是兩件獨立事故,推成 crash-loop 就是誤報,而誤報會賠掉這則推播的可信度。
    broken = now - float(rec.get("last", rec.get("ts", 0))) >= PUSH_COOLDOWN_SEC
    n = 1 if broken else int(rec.get("n", 0)) + 1
    cooling = (not broken) and now - float(rec.get("ts", 0)) < PUSH_COOLDOWN_SEC

    # 🔴 2026-09-03 crash-loop 靜默降頻(基建線沙箱實測 V2:第二次重啟零通知)。
    # 舊版在冷卻期內直接 `return`,**連被擋都不記 log**。於是 crash-loop 長這樣:
    # 每次救援都成功、log 全記錄但沒有人讀、Carson 每小時收到一則不含次數的孤立推播
    # —— 迴圈完全不可見。「重啟了 1 次」和「這小時重啟了 20 次」是**兩件事**,
    # 而舊版把它們推成同一則。
    #
    # ⚠️ 沒有照「N>=2 就送升級推播」做:排程每 5 分鐘跑一次,持續 crash-loop
    # 會變成每小時 12 則 —— 那正是今晚一整條線在治的「叫太多所以等於不會叫」
    # (docs/ops/2026-09-03_quota_alarm_closure.md)。改用**倍增階梯**:
    # 只在 n = 2/4/8/16/32… 送,每一則都代表「迴圈比上次嚴重一倍」= 真的有新資訊,
    # 而推播次數只隨 log2 成長(24 次/2 小時 → 6 則,不是 24 則也不是舊版的 2 則)。
    # 冷卻視窗到期那一次也一定要送,而且**同樣要帶次數**:迴圈跨過整點不代表它結束了,
    # 舊版在那裡會送出一則不含次數的孤立推播,看起來像剛發生的單一事故。
    escalate = n >= 2 and ((n & (n - 1)) == 0 or not cooling)
    if cooling and not escalate:
        st[reason] = {"ts": rec.get("ts", 0), "n": n, "last": now}   # 次數要累積,否則階梯永遠到不了
        try:
            PUSH_STATE.parent.mkdir(parents=True, exist_ok=True)
            PUSH_STATE.write_text(json.dumps(st), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        # 被擋也要留痕:靜默 return 讓「冷卻中」和「沒發生」在 log 裡長得一模一樣。
        _log(f"[watchdog] 推播冷卻中,累積第 {n} 次({reason})——下個倍增點才會升級推播")
        return
    if escalate:
        title = f"🔴 排程器連續第 {n} 次({reason})"
        body = (f"這是連續第 {n} 次同因事件,不是單一事故 —— 疑似 crash-loop。\n\n"
                + body)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from notify import push  # noqa: PLC0415
        ok = push(title, body, tag="rotating_light")
    except Exception as e:  # noqa: BLE001
        _log(f"[watchdog] 推播失敗:{e}")
        return
    if not ok:
        _log("[watchdog] 推播沒送出去(後端未設定或回非 2xx)——不記冷卻,下輪重試")
        return                            # 沒送出就不記冷卻,否則等於自己靜音一小時
    # 升級推播**不重置 ts**:重置會讓冷卻視窗跟著往後滑,階梯就永遠停在 n=2。
    # 只有正常(非冷卻期)那次才開新視窗、把次數歸 1。
    st[reason] = {"ts": rec.get("ts", 0) if (escalate and cooling) else now,
                  "n": n, "last": now}
    try:
        PUSH_STATE.parent.mkdir(parents=True, exist_ok=True)
        PUSH_STATE.write_text(json.dumps(st), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    _log(f"[watchdog] 推播已送出({reason},第 {n} 次{'·升級' if escalate else ''})")


def write_alert(payload: dict) -> None:
    payload.setdefault("epoch", time.time())
    try:
        ALERT.parent.mkdir(parents=True, exist_ok=True)
        ALERT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def clear_alert() -> None:
    """只清「現在有問題」這個標記,**不動** push_state(那是冷卻,清掉會變洗版)。"""
    try:
        if ALERT.exists():
            ALERT.unlink()
    except Exception:  # noqa: BLE001
        pass


def decide(force_procs: bool = False) -> tuple[str, dict]:
    """回傳 (動作, 事實)。動作 ∈ {noop, start, hung, unknown}。"""
    age = heartbeat_age()
    facts: dict = {
        "heartbeat_age_sec": None if age is None else round(age, 1),
        "stale_threshold_sec": STALE_SEC,
        "lock": str(LOCK),
    }
    if _fresh(age):
        if force_procs:                   # --status 要看得到現在有幾個迴圈活著
            p = cron_procs()
            facts["procs_found"] = None if p is None else len(p)
            facts["note"] = "單一實例正常就是 2 筆(venv stub + 真直譯器)"
        return "noop", facts

    procs = cron_procs()
    facts["procs_found"] = None if procs is None else len(procs)
    if procs is None:
        return "unknown", facts           # 查不到 → 當作有在跑,不動手
    if procs:
        facts["procs"] = procs[:4]
        facts["note"] = "單一實例正常就是 2 筆(venv stub + 真直譯器)"
        return "hung", facts              # 程序在但心跳停 → 交給人,絕不多拉一個
    return "start", facts


def start_cron() -> int | None:
    """拉起排程器,回傳**鎖檔裡的真 pid**(不是 Popen 給的 venv 轉發 stub pid)。

    None = 沒起來,或起來了但心跳沒恢復(啟動即崩)。
    """
    exe = VENV_PYW if VENV_PYW.exists() else VENV_PY
    before = None
    try:
        before = LOCK.stat().st_mtime if LOCK.exists() else None
    except Exception:  # noqa: BLE001
        pass
    try:
        BOOTLOG.parent.mkdir(parents=True, exist_ok=True)
        # 過大先截斷(照 local_cron.run_job 對 job_stderr.log 的同一套寫法)。
        # 父端開檔傳給 Popen,子程序繼承 fd 後父端關閉不影響子寫入。
        try:
            if BOOTLOG.exists() and BOOTLOG.stat().st_size > 5_000_000:
                BOOTLOG.write_text("", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        bootf = open(BOOTLOG, "a", encoding="utf-8")
        bootf.write(f"\n===== [{datetime.now():%Y-%m-%d %H:%M:%S}] watchdog 拉起 =====\n")
        bootf.flush()
        subprocess.Popen(
            [str(exe), str(TARGET)], cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=bootf,                                  # 啟動即崩要留得下 traceback
            creationflags=NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0),
        )
        bootf.close()
    except Exception as e:  # noqa: BLE001
        _log(f"[watchdog] 拉起失敗:{e}")
        return None
    # 回頭確認心跳真的恢復 —— Popen 成功只代表程序被建立,不代表迴圈在轉。
    deadline = time.time() + VERIFY_SEC
    while time.time() < deadline:
        time.sleep(3)
        try:
            if LOCK.exists():
                mt = LOCK.stat().st_mtime
                if (before is None or mt > before) and _fresh(time.time() - mt):
                    # 🔴 `_touch_lock()` 是 write_text(先截斷再寫),回讀撞上那個
                    # 瞬間會拿到空字串 → pid=0。舊版直接 return None,產生「拉起後
                    # 心跳沒恢復」的假失敗推播(實測 3 秒就回,沒等滿 45 秒)。
                    # 拿到 0 要繼續等下一輪,不是判死。
                    pid = int(LOCK.read_text(encoding="utf-8").strip() or 0)
                    if pid:
                        return pid
        except Exception:  # noqa: BLE001
            pass
    return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只印現況,不動手")
    ap.add_argument("--dry-run", action="store_true", help="印出會做什麼,不動手")
    args = ap.parse_args()

    peek = args.status or args.dry_run
    action, facts = decide(force_procs=peek)

    if peek:
        print(json.dumps({"action": action, **facts}, ensure_ascii=False, indent=2))
        return 0

    if action == "noop":
        clear_alert()
        return 0                          # 正常情況零輸出、零寫檔
    if action == "unknown":
        _log("[watchdog] 查程序失敗(兩條管道都沒回出 python 行)→ 當作有在跑,不動手。")
        return 0
    if action == "hung":
        _log(f"[watchdog] 🔴 心跳停了 {facts['heartbeat_age_sec']} 秒但程序還在"
             f"({facts['procs_found']} 筆)→ 不自動處理,需要人判斷是否殺掉重啟。")
        write_alert({"at": datetime.now().isoformat(timespec="seconds"),
                     "reason": "hung", **facts})
        _push("hung", "🔴 排程器卡死",
              f"local_cron 程序還在但心跳停了 {facts['heartbeat_age_sec']} 秒"
              f"(查到 {facts['procs_found']} 筆指令列,單一實例正常就是 2 筆)。"
              "watchdog 不自動處理(怕兩個迴圈同時活著=雙發),需要人決定是否殺掉重啟。")
        return 2
    # action == "start"
    _log(f"[watchdog] 心跳 {facts['heartbeat_age_sec']} 秒沒更新、也沒有 local_cron "
         f"程序 → 拉起排程器。")
    pid = start_cron()
    if pid is None:
        _log("[watchdog] 🔴 拉起後心跳沒恢復(啟動即崩?)→ 產線現在沒有排程器。")
        write_alert({"at": datetime.now().isoformat(timespec="seconds"),
                     "reason": "failed", **facts})
        _push("failed", "🔴 排程器拉不起來",
              "local_cron 死了,watchdog 拉起後心跳沒有恢復,產線現在沒有排程器。"
              "看 youtube_channel/logs/local_cron_boot.log 的 traceback。")
        return 1
    _log(f"[watchdog] 已啟動,心跳恢復,pid={pid}")
    write_alert({"at": datetime.now().isoformat(timespec="seconds"),
                 "reason": "restarted", "new_pid": pid, **facts})
    _push("restarted", "⚠️ 排程器被重啟",
          f"local_cron 死了(心跳停 {facts['heartbeat_age_sec']} 秒),watchdog 已拉起 "
          f"pid={pid} 並確認心跳恢復,它會補跑斷檔期間的發布/評分/個股/產製。"
          "要查為什麼死掉:youtube_channel/logs/local_cron_watchdog.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
