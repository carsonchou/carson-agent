#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""補跑今天沒產滿的長片額度。

## 為什麼(2026-08-31 實帳)

清晨網路層斷線,所有 LLM 供應商連不上:

    [08-31 05:37] 決策部門｜⚠️ 所有 LLM 供應商都失敗:gemini: HTTPSConnectionPool(...)
    [08-31 05:47] 寄生標題｜⚠️ 所有 LLM 供應商都失敗:groq: HTTPSConnectionPool(...)
    [08-31 06:07] 補產部門｜⚠️ long 連續失敗,跳過      ← 主力產線整批放棄

主力的 `06:07 --long 8` 一支都沒產就跳過,而且**沒有任何重試**。當天排程只從
12:30 那輪拿到 2 支,對上 8 支/天的發布 = 淨流失。到 09:00 網路早就好了。

現有的 stall_watchdog 補不到這個洞:它看的是「最後一次有動」的時戳,
門檻是**好幾天**;單一批次掛掉、隔天又正常,它從頭到尾不會叫。

## 為什麼不能只是再排一次 --long 8

produce_batch 的 `--long N` 是「這輪產 N 支」,不是「補到 N 支」。
好日子再跑一次就變成雙倍產量 —— 白燒題目(每支抽中即標 used)和 LLM 錢。

所以這支先**數今天實際成稿幾支**,只補差額;夠了就安靜結束。

## 兩道保險

·**不重複跑**:偵測到已經有 produce_batch 在跑就直接結束(06:07 那輪可能跑好幾小時,
  memory 記過「9.5 小時只生出 5 支」),否則兩個實例會互搶題目。
·**只補差額**:差額 <=0 就不呼叫,零成本。

用法:`python scripts/produce_catchup.py [--target 8] [--dry]`
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPS = ROOT / "STUDIO" / "ops_log.txt"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass


# 🔴 下面三個計數的「範圍」故意不一致,**不要統一它**(2026-09-04 實測):
#   made / started / completed → **要**濾「補產部門｜」
#   done(produced_today)      → **絕對不可以**濾部門,且「：L_」不可拿掉
# 成功訊號寫在「補產·雲端」(produce_batch.py:6192,在 if no_render: 分支內),
# 「補產部門」底下 0 筆;ep_teaser.py:97 也寫「已備妥待渲染」(23 筆),靠「：L_」擋掉。
# 加了部門過濾 → done 恆為 0 → 這個告警**每天都響** → 三天內沒人再看它,
# 等於把警報親手關掉。
# 根因:ops_log 第一欄不是「哪個模組寫的」,是「產線走到哪一步」——
# produce_batch.py 一支就用了 19 個標籤(補產部門/補產·雲端/補產·重生/…),
# 拿它當模組過濾器,在成功路徑上必定落空。
_DEPT = "補產部門｜"


def _batch_tally(day: str):
    """今天到現在,主力批次的開跑/收工/產量。回 (started, completed, made_sum)。

    量的是 produce_batch 自己寫的兩行(:6598 開始 / :6605 完成),不是全廠成稿數。
    差別很重要:--ep0 那條排程(crontab:199/200,每月 4 次 —— local_cron.py:243-244 用 AND 語意不是標準 cron 的 OR,
    # 「1-7,15-21 * 3」= 週三**且**日期落在那兩段;實測 08-12/08-19/08-26/09-02)會經 :6192 寫
    「補產·雲端｜已備妥待渲染：L_」污染全廠成稿數,卻在 :6368 提前 return、
    寫不到 :6605 —— 08-19 就是這樣讓舊版判準靜音了一整天。
    """
    if not OPS.exists():
        return 0, 0, 0
    started = completed = made = 0
    pre = "[" + day + " "
    for ln in OPS.read_text(encoding="utf-8", errors="replace").splitlines():
        if not (ln.startswith(pre) and _DEPT in ln):
            continue
        if "開始補產" in ln:
            started += 1
        elif "完成 補產" in ln:
            completed += 1
            m = re.search(r"完成 補產(\d+)支", ln)
            if m:
                made += int(m.group(1))
    return started, completed, made


def _triage(day: str):
    """回 (呼叫失敗次數, 閘門擋稿次數)。只用來在推播裡給一句方向,不是判定。

    兩個關鍵字都會外洩到別的部門(⛔ 另有 10 筆在切片漏斗/誠信事故,
    連續失敗 另有 6 筆在渲染隔離),所以這兩個**要**濾部門。
    ⚠️ ops_log 分不出「連續失敗」是例外還是設計內拒絕(那個區別只在
    job_stderr.log 的 [err 行),所以這是啟發式不是判定,措辭不可以斷言成因。

    ⚠️ gate 只認「⛔」不認「fail-closed」。實測補產部門底下
    「有 fail-closed 但無 ⛔」= 0 筆,目前不會漏;但 daily_health.py:141-143
    的口徑是兩者皆認,**兩份報告未來可能對同一天給出不同的 gate 數**。
    要對齊時改這裡,不要改 daily_health(它服務的是另一個問題)。
    """
    if not OPS.exists():
        return 0, 0
    fail = gate = 0
    pre = "[" + day + " "
    for ln in OPS.read_text(encoding="utf-8", errors="replace").splitlines():
        if not (ln.startswith(pre) and _DEPT in ln):
            continue
        if "連續失敗" in ln:
            fail += 1
        if "⛔" in ln:
            gate += 1
    return fail, gate


def produced_today(day: str) -> int:
    """今天成稿的長片數。數 ops_log 的「已備妥待渲染」行 —— 那是產線自己寫的完成訊號,
    比數 output/*.voice.txt 的 mtime 可靠(那些檔會被後續工序改寫,實測 08-30 會多報四倍)。"""
    if not OPS.exists():
        return 0
    n = 0
    pat = re.compile(r"^\[" + re.escape(day) + r" ")
    for ln in OPS.read_text(encoding="utf-8", errors="replace").splitlines():
        if pat.match(ln) and "已備妥待渲染" in ln and "：L_" in ln:
            n += 1
    return n


def _python_cmdlines() -> str:
    """所有 python 程序的**完整命令列**。

    要命令列不要映像檔名:tasklist 只給得到 python.exe,而本機同時跑著十幾支 python
    (local_cron / brain_alpha_cron / launcher+worker 配對…),分不出是哪一支。

    WMIC 先試、PowerShell 備援:WMIC 是**已棄用元件**,微軟正在從 Windows 移除。
    只留 WMIC 的話,它哪天消失 → except 吞掉 → 這道保險靜默失效而沒人知道
    (正是本專案一再踩到的「靜默失敗」形狀)。"""
    for cmd in (
        ["wmic", "process", "where", "name like '%python%'", "get", "commandline"],
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\""
         " | Select-Object -ExpandProperty CommandLine"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and len(r.stdout) > 40:
                return r.stdout
        except Exception:
            continue
    return ""


def already_running(needle: str = "produce_batch.py") -> bool:
    """已經有 produce_batch 在跑?兩個實例會互搶題目(每支抽中當下就標 used)。

    查不到程序清單時回 False(fail-open):漏跑一批的代價 > 偶爾撞車的代價,
    而撞車本身還有 produce_batch 自己的庫存上限擋著。"""
    return needle in _python_cmdlines()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=8, help="今天該有幾支長片成稿")
    ap.add_argument("--dry", action="store_true", help="只算不跑")
    args = ap.parse_args()

    day = dt.datetime.now().strftime("%m-%d")
    done = produced_today(day)
    gap = args.target - done
    print(f"[catchup] {day} 今日成稿長片 {done} / 目標 {args.target} → 差額 {gap}")

    if gap <= 0:
        print("[catchup] 已達標,不補跑。")
        return 0
    if already_running():
        print("[catchup] produce_batch 正在跑,跳過(避免兩個實例互搶題目)。")
        return 0
    if args.dry:
        print(f"[catchup] --dry:本來會跑 produce_batch --long {gap}")
        return 0

    # 🔴 主力批次歸零 / 沒跑到 —— 目前唯一會主動通知的地方(2026-09-04 督導線加)。
    # 為什麼需要:06:07 主力批次全滅時 produce_batch 仍 exit 0
    # (:6607 無條件 return 0,made 不參與回傳值),local_cron 又用 stdout=DEVNULL。
    # 本檔隨後把數字補滿,產出總數不動 —— 四道現存警報結構上全部叫不出來:
    #   ①cron exit code ②daily_health._supplies(讀昨天整日,09-04 的 _made=11)
    #   ③_cron_failures(數 Traceback,而例外被 attempt() 接住不外拋)
    #   ④llm.py 的 _hard(不含 HTTPSConnectionPool / getaddrinfo)
    # 近 30 天實測:20% 的早上主力批次產出 0(每週 1~2 次),而沒有人知道。
    #
    # 🔴 這段**必須在 08:45 那輪判,不可以延到 11:00**:08:45 這輪自己補產成功後
    # 也會寫一行「完成 補產N支」,把 made 加總推上去 —— 回測實測切點移到 11:00,
    # A 分支從 10 天掉到 8 天,08-31 與 09-04 全部變成不叫。
    # 「11:00 會自然重驗一次」是**錯的**,那輪對 A 在補產成功時恆不叫。
    #
    # 依賴(改動任何一項都要回來重驗):
    #   · 06:07 那輪帶 --shorts 0(crontab:169)。若改回帶短片,made 含短片,
    #     長片全滅而短片成功會讓 made>0 → 靜音。
    #   · 08:45 之前只有 06:07 一輪 produce_batch 寫完成行。這是 crontab 的
    #     巧合不是保證;若日後在 08:45 前加一輪,made 加總的語意就漂了。
    _started, _completed, _made = _batch_tally(day)
    _kind = None
    if _completed > 0 and _made == 0:
        _kind = "A"          # 跑完了,一支都沒產出
    elif _started == 0 and _completed == 0 and dt.datetime.now().hour >= 8:
        # 時間護欄:早於 08:00 手動跑本檔時,晨批本來就還沒開始,不判 C。
        _kind = "C"          # 主力批次今天根本沒被啟動
    # 刻意不做的分支:「有開始行但沒有完成行」(批次還在跑)。
    # 回測近 30 天會叫 7 次,其中 3 次是純誤報,而**誤報日剛好是產出最好的日子**
    # (08-25 產 20 支、08-30 產 25 支)—— 主力批次跑很久是常態
    # (本檔 docstring 記著「9.5 小時只生出 5 支」)。收緊版留給下一階段。

    if _kind:
        _hhmm = dt.datetime.now().strftime("%H:%M")
        if _kind == "A":
            _fail, _gate = 0, 0
            try:
                _fail, _gate = _triage(day)
            except Exception:  # noqa: BLE001
                pass
            if _fail > _gate:
                _sign = f"跡象:呼叫失敗 {_fail} 次、閘門擋掉 {_gate} 支 → 比較像連不上(網路或 LLM 供應商)。"
            elif _gate > 0:
                _sign = f"跡象:閘門擋掉 {_gate} 支、呼叫失敗 {_fail} 次 → 比較像稿被品質閘門擋下,不急。"
            else:
                _sign = "跡象:沒有失敗也沒有擋稿記錄 → 可能沒題可抽。(這個組合過去沒出現過,判讀僅供參考。)"
            _title = f"🆘 主力產線零產出({day} {_hhmm})"
            _body = (f"今天到現在,長片一支都沒做出來(今天該有 {args.target} 支)。\n"
                     f"本輪嘗試補 {gap} 支;若這輪也失敗,今天長片成稿為 0,發布端只能吃庫存。\n"
                     f"{_sign}\n"
                     f"細節:logs/job_stderr.log 搜 {day} 06:07;成因不確定時先看那裡,不要預設是網路。")
            _ops = f"❌ 主力批次歸零:{day} 完成行 {_completed} 筆、產出加總 0,本輪補 {gap} 支"
        else:
            _title = f"🆘 主力產線今天沒被啟動({day} {_hhmm})"
            _body = (f"到現在為止,今天的主力批次連開跑記錄都沒有(今天該有 {args.target} 支)。\n"
                     f"這不是產線做壞了,比較像排程器沒跑到 —— 機器睡著、重開機沒人登入、"
                     f"或撞到用量上限。\n"
                     f"本輪嘗試補 {gap} 支。細節:logs/local_cron.log 看今天有沒有 06:07 的啟動行。")
            _ops = f"❌ 主力批次沒被啟動:{day} 無開跑記錄,本輪補 {gap} 支"

        # 落檔在推播之前,而且整段包在 try 裡 ——
        # ops.py:13 的 OPS.parent.mkdir() 不在它自己的 try 內,會拋;
        # 而這一行診斷文字**絕對不可以有能力擋掉補產**(補產是本業,告警是附加的)。
        # ❌ 前綴是刻意選的:daily_check.py:213 的正則
        # (Traceback|FATAL|\[err|\[ERROR|❌|Error:|Exception)認得它,而**不認 ⚠️**,
        # 且 ops_log 在它的 LOGS(:42-46)裡、2MB 視窗涵蓋整個檔(現 1.32MB)。
        # ⚠️ 真正可靠的讀者是它寫出來的 STUDIO/REPORTS/*_大檢查.md(持久、可 grep),
        # **不是**那則每天都發、87% 總評都是 ⚠️ 的推播 —— 不要指望推播被看到。
        try:
            log_ops("補產部門", _ops)
        except Exception as _e:  # noqa: BLE001
            print(f"[catchup] 告警落檔失敗(不影響補產):{str(_e)[:120]}")
        try:
            import notify
            # tag 用 sos:全庫 15 種 tag 裡零呼叫點 ⇒ 本 repo 結構上發不出帶 sos 的訊息
            # ⇒ 它在通知列表裡不可能和既有訊息混淆。(實測 rotating_light 佔真實流量
            # 76%、warning 每天必發一則,兩者都會被淹沒。)
            _ok = notify.push(_title, _body, tag="sos")
            if not _ok:
                # 抄 local_cron_watchdog.py:186-188:沒送出去要留痕,
                # 否則「送出了沒人看」和「根本沒送出」在事後長得一模一樣。
                log_ops("補產部門", f"❌ 上一則告警推播沒送出去(後端未設定或回非 2xx):{day} {_hhmm}")
        except Exception as _e:  # noqa: BLE001
            # 落檔而不是只 print:正式機 local_cron 用 stdout=DEVNULL,print 等於丟掉。
            # 不補這行的話,「回非 2xx」會留痕、「拋例外」反而不留 —— 同一件事兩種死法
            # 只有一種看得見,而拋例外那條正是 notify.py:33 那個不在 try 裡的 import requests。
            print(f"[catchup] 告警推播失敗(不影響補產):{str(_e)[:120]}")
            try:
                log_ops("補產部門", f"❌ 上一則告警推播拋例外(不影響補產):{str(_e)[:120]}")
            except Exception:  # noqa: BLE001
                pass

    py = ROOT / ".venv" / "Scripts" / "python.exe"
    cmd = [str(py if py.exists() else sys.executable),
           str(ROOT / "scripts" / "produce_batch.py"),
           "--manual", "--format-focus", "--shorts", "0",
           "--long", str(gap), "--target", "150", "--no-render"]
    print("[catchup] 補跑:" + " ".join(cmd[1:]))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
