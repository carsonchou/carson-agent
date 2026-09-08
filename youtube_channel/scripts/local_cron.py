#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local_cron.py — 本機工作室排程器（取代雲端 crontab，讓整套 YT 產線在這台 Windows 電腦跑）。

背景：雲端 droplet 因欠費停權→改在本機跑。這支是常駐程序：
  - 讀 deploy/crontab.txt 的排程（＝雲端同步版），每 60 秒檢查哪些 job 到點就跑。
  - 把 `/root/yt/run.sh scripts/X.py args` 翻譯成本機 `.venv python scripts/X.py args`。
  - 先把專案根 .env 載入環境（OPENROUTER/GEMINI/PEXELS…金鑰），子程序才吃得到。
  - 只跑「本機能跑」的 job；雲端專屬（fileserver.sh/self_heal.sh/純 shell 備份）自動略過。
    ⚠️ 2026-07-28 更正:本行原本寫「flock 自動略過」——**與實作不符**,SKIP_MARKERS 從來沒有
    收 "flock"(見下方定義)。後果:crontab 的 `*/15 flock -n /tmp/hr_cloud.lock hybrid_render
    --max 20` 在本機**照跑且完全沒有鎖**(flock 是 Linux 指令,Windows 上不存在),每 15 分鐘
    疊加一個實例 → 實測 09:40 同時 20 個 hybrid_render + 16 個 make_video + 27 個 ffmpeg,
    15.7GB 記憶體剩 0.4GB,產線連續 MemoryError / ffmpeg 逾時、當天渲染全滅。
    **修法沒有加進 SKIP_MARKERS**(hybrid_render 是本機真正的渲染器,produce_batch 都帶
    --no-render,略過它等於停掉渲染),而是讓 hybrid_render **自己單例化**(見該檔 _acquire_proc_lock)。
    教訓:cron 行裡任何 Linux-only 的防護(flock/timeout/setsid…)搬到本機都是**靜默失效**,
    防護要做在腳本自己身上。
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
from datetime import datetime, timedelta
from pathlib import Path

# 🔴 排程器可能被三種方式啟動,而它們給的 stdout 編碼不同:
#   ① run_studio_bg.vbs 的 WshShell.Run(無重導向)② 人工在終端機跑
#   ③ **local_cron_watchdog 的 `Popen(stdout=<開好的檔>)`** ← 這個在 Windows 上預設 cp950
# ③ 那條路 2026-09-08 第一次被真的行使,結果排程器印 `▶` 就 UnicodeEncodeError 死掉。
# 這裡先把自己的 stdout 釘成 utf-8,不要依賴啟動者剛好設對(`:162` 只幫子程序設)。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
# 🔴 需要 playwright 的腳本必須用「系統 python」跑(.venv 沒裝 playwright)。
# 根因:local_cron 一律用 VENV_PY→tiktok_upload import playwright 失敗靜默跳過→TikTok 從沒真發過(2026-07-11 抓到)。
import shutil as _shutil
SYS_PY = Path(r"C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe")
if not SYS_PY.exists():
    _w = _shutil.which("python")
    SYS_PY = Path(_w) if _w else VENV_PY  # 找不到系統 python 就退回 venv(至少不崩)
PLAYWRIGHT_SCRIPTS = {"tiktok_upload.py", "community_post.py"}  # 這些走系統 python(需 playwright);其餘照 VENV_PY
CRONTAB = ROOT / "deploy" / "crontab.txt"
LOG = ROOT / "logs" / "local_cron.log"
ERRLOG = ROOT / "logs" / "job_stderr.log"    # 子程序 stderr 導這裡(補 DEVNULL 盲區:job 靜默失敗可事後查 traceback)
# 🔴 2026-09-08:子程序 stdout 原本是 `subprocess.DEVNULL`,而 `parse_jobs()`(見 :219 的正則)
# 又把 crontab 每一行寫的 `>> /root/yt/logs/cron.log 2>&1` **切掉並忽略**(那是 droplet 時代的路徑,
# 本機 logs/cron.log 根本不存在)⇒ **每一個排程 job 的 stdout 都進黑洞**。
# 後果不是「少了些除錯訊息」,是**整類「印一行紅字就算告警」的閘門在排程上結構性靜默**:
# 閘門有沒有叫、叫了什麼,事後在磁碟上完全查不到(見 docs/ops/2026-09-08_gate_health_inventory.md 第〇節)。
# ⚠️ 為什麼另開一個檔而不是併進 ERRLOG:ERRLOG 已經 4.3MB、上限 5MB,
# 而 stdout 的量體遠大於 stderr(produce_batch 這種會狂印)⇒ 併進去會把 traceback 的歷史提早擠掉,
# 那是拿一個現有的鑑識能力去換一個新的。兩個檔各自截斷,互不吃對方的額度。
# ⚠️ **一支腳本一個檔**,不是共用一個 `job_stdout.log`。獨立驗證實測(2026-09-08):
# 同一分鐘兩支 job 各自對同一個檔開 append handle,Windows 下**兩個 handle 各有自己的檔案指標**
# (不像 POSIX `O_APPEND` 保證每次寫入都到當下真正的檔尾)⇒ 先開的會被後開的蓋過去,
# 連續三次重跑一致地只剩 A=13 行 / B=199 行,而且出現 `[A] line 12[B] line 0` 這種**拼接行**。
# 🔴 拼接行最壞的地方不是掉資料,是**它看起來像某一支的合法輸出** —— 讀 log 的人會把 B 的內容
# 當成 A 印的。crontab 同分鐘多支很常見(08:00 有 8 支)⇒ 共用一個檔會讓這件事天天發生。
# (同一個缺陷 `ERRLOG` 本來就有,那是既有問題、本次不動它;但沒有理由把它複製到新檔案上。)
OUTDIR = ROOT / "logs" / "jobout"


def _outlog_for(script: str) -> Path:
    """該腳本專屬的 stdout 檔。副作用:順便讓「這支閘門今天叫了什麼」變成一個可以直接開的檔案。"""
    return OUTDIR / (Path(script).stem + ".log")
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


# 🔴 2026-09-03 單例保護升級:心跳鎖擋不住雙發。
# 原本只靠 _lock_fresh()(啟動時檢查心跳 60 秒內有沒有被更新),兩個問題:
#   (1) 它**只在啟動時檢查一次** —— 迴圈卡住 >180 秒被 watchdog 判定死掉、拉起
#       第二個,舊的之後又自己恢復,就會有兩個迴圈同時活著;
#   (2) local_cron_watchdog 出手的門檻是心跳 ≥180 秒,而這裡判活是 60 秒,
#       **兩個門檻零重疊** —— watchdog 每一次出手,這道「保險」必定已經失效。
# 雙發的代價:daily_publish 的 uploaded_ledger.json 是發布後才寫的檔案台帳、
# 沒有程序鎖,兩個實例會挑到同一批 slug 各發一次 = 每天發兩次片、燒兩份配額。
# 改用作業系統層的獨占鎖:第二個實例拿不到鎖當場退出,而持有者不管是正常退出、
# 崩潰還是被 kill,**OS 都會自動釋放** —— 不需要判斷 pid 死活,也沒有陳舊門檻。
# 呼應本檔開頭那條教訓:防護要做在腳本自己身上(flock 那種 Linux-only 的防護
# 搬到本機是靜默失效的)。
SINGLETON = ROOT / "STUDIO" / "local_cron.singleton"
_singleton_fh = None          # 必須整個程序生命週期握著,不能關、不能重開


def _acquire_singleton() -> bool:
    """拿到獨占鎖回 True;被另一個實例握著回 False(本實例該退出)。

    ⚠️ 方向是 fail-open:意外(msvcrt 拿不到、權限問題)一律回 True 繼續跑。
    「沒有排程器」比「短暫雙發」嚴重得多 —— 前者是整條產線靜音停擺,
    後者還有 watchdog 的 cron_procs 那一層擋。只有明確的「鎖被別人握著」才退出。
    """
    global _singleton_fh
    try:
        import msvcrt
    except Exception:  # noqa: BLE001
        return True
    # 🔴 開檔和上鎖必須拆成兩個 try(2026-09-03 第二個驗證員打穿):
    # 擠在同一個 try 時,`except OSError: return False` 會把「檔案根本打不開」
    # 誤判成「鎖被別人握著」——而 PermissionError / FileExistsError 都是 OSError
    # 子類。實測四種都中:防毒或備份程式用 share=0 開著、檔案被設唯讀屬性、
    # 這個路徑變成目錄、STUDIO 變成檔案導致 mkdir 失敗。後果是**每一個實例都退出**,
    # 而且前三種是持久的 = 每次重啟都退出 = 產線永久停擺,log 還會寫「另一個
    # local_cron 持有單例鎖」把人送去抓一個不存在的程序。
    try:
        SINGLETON.parent.mkdir(parents=True, exist_ok=True)
        fh = open(SINGLETON, "a+")     # 不可用 write_text:那會重開檔案、鬆開鎖
    except Exception:  # noqa: BLE001
        return True                    # 開不了檔 ≠ 別人握著 → fail-open,照樣跑
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return False                   # 只有這裡是真的「被別人握著」
    except Exception:  # noqa: BLE001
        return True                    # 其他意外:fail-open
    _singleton_fh = fh                 # 綁在模組上,避免被 GC 關掉而鬆鎖
    return True

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
    # 🔴 2026-09-08:這一行 `print` 曾經**弄死整個排程器**。
    # 實據:08:12:58 watchdog 第一次真的行使「拉起」那條路徑,它用 `Popen(stdout=<開好的檔>)`
    # 啟動 local_cron,那個檔 handle 在 Windows 上預設 **cp950** ⇒ 印 `▶`(U+25B6)直接
    # `UnicodeEncodeError`;而例外處理裡又去 `_log("✗ 啟動失敗 …")` 印 `✗`(U+2717)**再炸一次**,
    # 於是 08:15:19 第一支到點的 job 就把排程器整個帶走(113 個 job 全停)。
    # 諷刺兩處:①:162 幫**子程序**設了 `PYTHONIOENCODING=utf-8`,卻沒幫自己設
    # ②本函式**先寫檔(utf-8,安全)再 print**,所以 log 檔那行寫進去了、程序才死在下一行。
    # ⇒ 兩層都補:reconfigure 讓輸出正確;try/except 讓「印不出來」**永遠不可能**弄死排程器。
    # 這是排程器,它的職責是把 job 跑起來 —— 記錄失敗絕不可以升級成服務中斷。
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001
        pass


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
        # 一次性排程守衛(2026-08-22 審核指出):cron 的欄位裡**沒有年**,所以
        # `20 15 22 8 *`(只該跑 2026-08-22 那一次)明年 8/22 會原封不動再放一次,
        # 全靠人記得回來刪那一行——而人不會記得。行尾標 `# ONESHOT=YYYY-MM-DD`
        # 就只在那天生效,過期自動失效(行留著當紀錄,也不用擔心忘了刪)。
        # 真 cron 那邊 `#` 之後由 shell 當註解吃掉,兩邊行為一致。
        _os = re.search(r"#\s*ONESHOT=(\d{4}-\d{2}-\d{2})", cmd)
        if _os and _os.group(1) != datetime.now().strftime("%Y-%m-%d"):
            continue
        if any(k in cmd for k in SKIP_MARKERS):
            continue
        # 行內環境變數前綴(`VAR=x /root/yt/run.sh scripts/X.py …`)。
        # 🔴 2026-08-25:原本這裡**只抽 scripts/X.py 和參數**,`VAR=x` 前綴被整段丟掉——
        # 真 cron 是交給 sh 執行、吃得到那個變數,本機 runner 吃不到 → 同一份 crontab
        # 兩邊行為不一樣,而且是**靜默**的(沒有錯誤、只是設定沒生效)。配額預留
        # (YT_QUOTA_RESERVE)正是靠這個機制,漏掉就等於整個保護沒裝。
        # 只掃**註解之前**那一段:行尾的 `# ONESHOT=2026-08-28` 長得跟環境變數一模一樣,
        # 原本只是因為它後面沒有空白、剛好被 lookahead 濾掉 —— 那是靠運氣不是靠設計
        # (有人手滑在行尾多打一個空格,ONESHOT 就會被當環境變數注入子程序)。
        _envscan = cmd.split("#", 1)[0]
        jenv = {k: v for k, v in
                re.findall(r"(?:^|\s)([A-Z][A-Z0-9_]*)=(\S+)(?=\s)", _envscan)
                if k != "ONESHOT"}
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
        jobs.append((mi, ho, dom, mon, dow, [script] + arglist, s, jenv))
    return jobs


def due(job, now: datetime) -> bool:
    mi, ho, dom, mon, dow = job[:5]
    # cron dow: 0/7=Sun..6=Sat；python weekday(): Mon=0..Sun=6 → 轉換
    # 2026-07-16 修:原本多了一個 `or match(dow, py)`(拿未換算的 python weekday 再比一次),
    # 導致 dow 限定的 job 每週多跑一天(如 `* * 1-5` 實際一~六都跑)。只比換算後的 cron_dow。
    py = now.weekday()
    cron_dow = 0 if py == 6 else py + 1
    return (_cron_field_match(mi, now.minute) and _cron_field_match(ho, now.hour)
            and _cron_field_match(dom, now.day) and _cron_field_match(mon, now.month)
            and _cron_field_match(dow, cron_dow))


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


def run_job(pyargs, env, jenv=None):
    script = pyargs[0]
    if jenv:
        env = {**env, **jenv}          # crontab 行內 `VAR=x` 前綴,per-job 覆蓋
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
        # stdout:一支腳本一個檔(見 OUTDIR 上方的說明),各自 2MB 上限。
        # 開檔失敗時退回 DEVNULL —— **絕不可以因為記 log 失敗就不跑 job**,
        # 排程器的職責是把 job 跑起來,記錄是附加價值不是前提。
        outf = None
        try:
            _op = _outlog_for(script)
            _op.parent.mkdir(parents=True, exist_ok=True)
            try:
                if _op.exists() and _op.stat().st_size > 2_000_000:
                    _op.write_text("", encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            outf = open(_op, "a", encoding="utf-8")
            outf.write(f"\n===== [{datetime.now():%Y-%m-%d %H:%M:%S}] {' '.join(pyargs)} =====\n")
            outf.flush()
        except Exception:  # noqa: BLE001
            outf = None
        _py = str(SYS_PY) if Path(script).name in PLAYWRIGHT_SCRIPTS else str(VENV_PY)
        # CREATE_NO_WINDOW(2026-07-14 修「一直跳黑頻」):排程器用 run_studio_bg.vbs 無視窗常駐後,
        # 父程序沒有 console → 每個到點 job 的子程序 Windows 11 會自動新開一個 Windows Terminal
        # 黑窗蓋在 Carson 畫面上,同一分鐘多個 job 到點就「一次跳好多個」。job 的 stdout/stderr
        # 本來就導 DEVNULL/檔案,不需要 console——CREATE_NO_WINDOW 讓子程序(含其孫程序鏈)無視窗。
        _flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        proc = subprocess.Popen([_py, script] + pyargs[1:], cwd=str(ROOT), env=env,
                                 stdout=(outf if outf is not None else subprocess.DEVNULL),
                                 stderr=errf,
                                 creationflags=_flags)
        errf.close()  # 子程序已繼承 fd,父端關閉安全
        if outf is not None:
            outf.close()
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

    if not _acquire_singleton():
        _log("另一個 local_cron 持有單例鎖,本實例退出避免雙發。")
        return 0
    if _lock_fresh():
        _log("另一個 local_cron 已在跑(心跳鎖 60s 內),本實例退出避免雙發。")
        return 0
    # 🔴 持久化心跳(2026-08-13 二修):昨晚的斷檔補跑只治「程序活著但機器睡」,今晨實錄
    # =機器醒來排程器被**重啟**(08:52 新 pid),_prev_dt 重置→補跑沒開火,06:40 評分再次
    # 被吞。LOCK mtime 每圈都在更新=天然的持久化心跳:啟動時先讀它(必須在下面
    # _touch_lock 覆寫 mtime **之前**),重啟/重開機後第一個分鐘刻就會對斷檔期補跑。
    _resume_from = None
    try:
        if LOCK.exists():
            _lm = datetime.fromtimestamp(LOCK.stat().st_mtime)
            if (datetime.now() - _lm).total_seconds() > 180:
                _resume_from = _lm
                _log(f"⏰ 偵測到上次心跳停在 {_lm:%m-%d %H:%M},啟動後將補跑斷檔關鍵任務")
    except Exception:  # noqa: BLE001
        pass
    _touch_lock()

    env = load_env()
    if args.once:
        now = datetime.now()
        n = 0
        for j in jobs:
            if due(j, now):
                run_job(j[5], env, j[7] if len(j) > 7 else None); n += 1
        _log(f"--once：本分鐘跑了 {n} 個 job")
        return 0

    _log(f"本機工作室排程器啟動：{len(jobs)} 個 job（Ctrl+C 停）。LLM={env.get('LLM_PROVIDER')}")
    last_min = None
    # bug 修復(2026-07-09)：jobs 原本只在啟動時 parse 一次，crontab.txt 之後的改動(如新增
    # tiktok_upload 跨發排程)在本實例存活期間永遠不會生效，只能靠人手動重啟才會吃到——
    # 排程「看起來對」實際上不會跑，很難察覺。改成每分鐘連同 .env 一起重讀 crontab.txt。
    _prev_dt = _resume_from or datetime.now()
    while True:
        now = datetime.now()
        cur = now.strftime("%Y%m%d%H%M")
        _touch_lock()            # 每圈更新心跳鎖(讓其他實例知道我還活著)
        if cur != last_min:      # 每分鐘只判定一次
            last_min = cur
            env = load_env()     # 每分鐘重讀 .env（金鑰換了即生效）
            jobs = parse_jobs()  # 每分鐘重讀 crontab.txt（排程改動免重啟即生效）
            # 🔴 斷檔補跑(2026-08-13):實錄 08-12 17:30~19:30 電腦睡眠兩小時,18:00 評分
            # 與 18:30 發布批(EP0 首發!)被無聲吞掉——本排程器只判「當下那分鐘」,錯過不補。
            # 補法:偵測心跳斷檔 >3 分鐘時,回掃斷檔期間每一分鐘的 due 任務,**只補白名單
            # 關鍵任務**(發布/評分/種題/產製),同一 job 只補一次;斷檔上限回掃 12 小時
            # (更久=隔天排程自己會跑,不重複)。非白名單(tg輪詢/渲染巡邏)天生高頻,不需補。
            _gap = (now - _prev_dt).total_seconds()
            if _gap > 180:
                _CRITICAL = ("daily_publish.py", "quality_score.py",
                             "stock_checkup_daily.py", "produce_batch.py")
                _from = max(_prev_dt, now - timedelta(hours=12))
                _t = _from + timedelta(minutes=1)
                _fired = set()
                while _t < now:
                    for j in jobs:
                        _script = j[5][0] if j[5] else ""
                        if (Path(_script).name in _CRITICAL and due(j, _t)
                                and tuple(j[5]) not in _fired):
                            _fired.add(tuple(j[5]))
                            _log(f"⏰ 斷檔補跑({_gap/60:.0f}分斷檔,原定 {_t:%H:%M}):{' '.join(j[5])[:60]}")
                            run_job(j[5], env, j[7] if len(j) > 7 else None)
                    _t += timedelta(minutes=1)
            _prev_dt = now
            for j in jobs:
                if due(j, now):
                    run_job(j[5], env, j[7] if len(j) > 7 else None)
        time.sleep(20)


if __name__ == "__main__":
    raise SystemExit(main())
