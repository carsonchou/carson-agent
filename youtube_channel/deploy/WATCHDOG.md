# LocalCronWatchdog — 排程器的看門狗(Windows 排程工作,不在 git 裡)

2026-09-03 建立。**這份檔案是它唯一的紀錄**:Windows 排程工作不受版控,重灌或換機不會跟著走。

## 它補的洞
`scripts/local_cron.py` 是整套產線唯一的排程器(常駐,讀 `deploy/crontab.txt`)。
在此之前:**它死了沒有任何東西會拉起來,而且重開機後也沒有任何東西會啟動它**
(`run_studio_bg.vbs` / `啟動本機工作室.bat` 都是手動雙擊,14 支 `QuantArsen_*` 排程全部 Disabled)。
失敗是靜音的——不會有錯誤訊號,只會「今天沒發片」。

⚠️ 所以這支排程工作**同時也是本機唯一的開機自啟**,不要當成「只是備援」而低估。

## 排程工作設定(重灌後照這個重建)
| 項目 | 值 |
|------|-----|
| 名稱 | `LocalCronWatchdog` |
| 動作 | `youtube_channel\.venv\Scripts\pythonw.exe scripts\local_cron_watchdog.py` |
| 工作目錄 | `D:\carson-agent\youtube_channel` |
| 觸發 | ①登入時 ②時間觸發,兩者都每 5 分鐘無限重複 |
| 設定 | `MultipleInstances=IgnoreNew`、`StartWhenAvailable`、電池上照跑、`ExecutionTimeLimit=15 分鐘` |
| 身分 | 目前使用者、Interactive |

四個容易踩錯的地方:
1. **不可只掛「登入時」觸發**。使用者早就登入了,那個觸發要到下次登入才生效,`NextRunTime` 會是空的——**註冊成功但永遠不會跑**。必須再加一個時間觸發。(2026-09-03 實測踩到)
2. `-RepetitionDuration ([TimeSpan]::MaxValue)` 會產生非法 XML(`P99999999DT23H59M59S`)註冊失敗;無限重複要把 `Repetition.Duration` 設成 `$null`。
3. **名字刻意不用 `QuantArsen_*` 前綴**。那 14 支是 6/14 搬本機前的舊機制、全部 Disabled(它們跑同一批腳本,啟用等於每天發兩次片、燒兩份配額)。同前綴的話,將來任何人為了停舊機制打一句「停掉全部 `QuantArsen_*`」會把看門狗一起靜靜關掉。
4. `ExecutionTimeLimit` 不可設 5 分鐘。`DETACHED_PROCESS` **不會**讓子程序脫離 job object(實測用 `IsProcessInJob` 確認),Task Scheduler 逾時砍任務是走 job object → 會連帶砍掉剛拉起來的 local_cron,而 alert 檔已經寫了 "restarted" = **報告成功但東西死了**。15 分鐘對最壞路徑(~171 秒)有足夠餘裕。

## 判準與行為
判活看 `STUDIO/local_cron.lock` 的 mtime(local_cron 每圈約 20 秒更新),**不是看程序在不在**——卡死的程序在工作管理員裡看起來一模一樣。

| 心跳 | 有沒有 local_cron 程序 | 動作 |
|------|------------------------|------|
| 新鮮(0 ≤ age < 180s) | — | 什麼都不做,零輸出零寫檔 |
| 陳舊(含負數) | 沒有 | 拉起來,回讀 45 秒確認心跳恢復,推播 |
| 陳舊 | 有 | **不動手**,寫 alert + 推播,等人決定要不要殺 |
| 查詢失敗 | — | 當作有在跑,不動手 |

## 手動操作
```powershell
Get-ScheduledTask -TaskName LocalCronWatchdog | Get-ScheduledTaskInfo   # 上次跑、下次跑
Start-ScheduledTask -TaskName LocalCronWatchdog                          # 立刻跑一次
```
```
.venv\Scripts\python.exe scripts\local_cron_watchdog.py --status   # 只印現況,不動手
```
產出:`logs/local_cron_watchdog.log`(只在有動作時寫)、`logs/local_cron_boot.log`(被拉起來那個實例的 stderr)、`STUDIO/local_cron_watchdog_alert.json`(現在有問題)、`STUDIO/local_cron_watchdog_push.json`(推播冷卻)。

## 🔴 「commit 了」和「跑起來的行為變了」,對常駐程序隔著一次重啟

2026-09-09 實據:`local_cron.py` 的輪替修法 08:58 / 09:06 commit,而跑著的程序
**PID 62004/60672 起於 09-08 08:21:56** ⇒ **磁碟上修好了,記憶體裡還是舊碼。**
當天 12:45:20 那次觸發走的仍是舊路徑:2,691,191 bytes → **129 bytes**,無 `.1`,
`local_cron.log` 798 行同時段紀錄裡「輪替/歸零/truncate」**零命中** —— 它動手時不出聲。
🔴 而在那之前,已經有人對外報告過「炸彈拆了」。

**判準(一句話,可機械套用)**:

> 改的東西是被**每次重讀**的(`crontab.txt`、資料檔、`.env`),
> 還是**啟動時載入一次**的(模組 / 程式碼)?
> 後者一律要問:**哪個程序在跑它、什麼時候啟動的、那個時間在我的 commit 之前還是之後?**

```powershell
Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
  Sort-Object CreationDate |
  ForEach-Object { "{0,-6} {1:MM-dd HH:mm:ss} {2}" -f $_.ProcessId, $_.CreationDate, $_.CommandLine }
```

⚠️ **`local_cron` 舊碼不代表它派出去的 job 是舊碼**:`run_job()` 用 `Popen` 每次開**新行程**
⇒ job 腳本一律載當下磁碟上的碼。**只有 `local_cron.py` 自己會卡在舊版。**

⚠️ 同一天掃出**第二個**,而且更久:`quant-service/brain_alpha/status_pane.py --every 300`
(PID 35716/41704)起於 **09-01 21:44**,`:143` 的 `import brain_auto` 被 `sys.modules` 快取住
⇒ 它顯示的數字是 8 天前那版 `brain_auto` 算的。**只讀不寫,所以不毀資料 ——
但那是一個看起來完全正常、而且會說謊的儀表板。**
同族:memory `omniroute-usage-failover`(設定改了而跑到一半的程序讀不到,結論也是只能重啟)。

## 🔴 安全重啟 `local_cron`(2026-09-09 實跑驗過)

**不要自己 `Popen` 拉。把它殺掉,然後等 watchdog。**

```powershell
Stop-Process -Id <local_cron 的兩個 PID> -Force     # .venv + system launcher 是一對,兩個都殺
# 之後什麼都不用做,watchdog 每 5 分鐘一輪,自己會拉
```

實錄(空窗 12:46:05 → 12:52:59,約 **7 分鐘**):
```
[12:52:59] [watchdog] 心跳 421.2 秒沒更新、也沒有 local_cron 程序 → 拉起排程器。
[12:53:02] [watchdog] 已啟動,心跳恢復,pid=660
[12:52:59] ⏰ 偵測到上次心跳停在 09-09 12:45,啟動後將補跑斷檔關鍵任務
```

- 空窗上限 ≈ **180 秒陳舊門檻 + 最多 5 分鐘 watchdog 週期**。
- 斷檔 >180 秒會**自動回掃補跑白名單**:`daily_publish` / `quality_score` /
  `stock_checkup_daily` / `produce_batch`(`local_cron.py:492`)。非白名單是 `*/3`~`*/5` 的高頻 job,
  程式碼註解明寫「天生高頻,不需補」。
- ⚠️ **不要 kill 完馬上自己起**:`_lock_fresh()` 判準是鎖檔 <60 秒,太早起的新實例會
  **靜默自殺**,只印一句聽起來很正常的「另一個 local_cron 已在跑」。走 watchdog 天然避開。
- 挑時間:避開整點/半點那些非高頻 job(見 `crontab.txt`)。

### 🔴 驗收判準:「重啟了」不算通過,要證明**新碼在執行**

`State=Ready` 不算、`LastTaskResult=0` 不算、PID 換新了也**不算**(那只證明重啟了)。
而且「檔案沒被歸零」更不算 —— 沒到門檻本來就不會歸零(**不會叫的檢查**)。

**要讓那條路徑真的被走一次**,並且**兩個方向都要有對照**:

| | 舊碼(12:45:20 實測) | 新碼(重啟後實測) |
|---|---|---|
| 檔案 | 2,691,191 → **129 bytes** | 移到 `<stem>.1.log`,填充標記完好 |
| `.1` 檔 | **不存在** | 存在 |
| `local_cron.log` | **零行** | 出現「🔄 …已輪替到…」 |

做法:把某支 `*/5` job 的 `logs/jobout/<stem>.log` **先備份到 `_safety/`,再 append 一段
帶標記的填充**推過門檻,等它下一輪派工。**用 append 不用覆寫** —— 那樣 `.1` 裡會同時有
原內容和標記,證明的是「搬走」而不只是「有個新檔」。

**實測結果(2026-09-09 13:15:19,`telegram_command`,三格全過)**:

```
.1 檔          2,451,047 bytes ← 與加料後的大小逐位相同,一個 byte 都沒少
.1 的開頭      ===== [2026-09-09 12:45:17] scripts/telegram_command.py =====
                ↑ 是**原本的 job header**,不是我的填充 ⇒ 證明是搬走,不是產生一個新檔
新檔第一行     ===== [輪替 2026-09-09 13:15:19] 上一段 2,451,047 bytes 已移到
                telegram_command.1.log,此檔從這裡重新開始 =====
local_cron.log [2026-09-09 13:15:19] 🔄 telegram_command.log 到 2,451,047 bytes,
                已輪替到 telegram_command.1.log(保留一代,未刪除內容)
```

⇒ **兩條留痕通道都響了**(新檔第一行 + ops log),而**同一個門檻在 30 分鐘前由舊碼跨過時
是 2,691,191 → 129 bytes、無 `.1`、零留痕**。同一支檔案、同一個門檻、相隔半小時,
兩種完全相反的結果 —— 這就是「新碼在執行」的證據。

⚠️ 那個 `.1` 裡大部分是測試填充,可以直接刪;下一次輪替也會自然蓋掉它。
原始內容在 `_safety/telegram_command.jobout.2026-09-09_pre-rotate-test.log`。

---

# 主頻道守望排程(2026-09-06 建;Windows 排程工作不受版控,重灌照這裡重建)

昨晚(09-04→05)兩支 session-local monitor **隨 session 撞 429 一起死掉,全盲七小時**。
⇒ **哨必須在排程層,不能靠 session。** 這三支都是那個教訓的產物。

| 名稱 | 腳本 | 時間 | 它在防什麼 |
|---|---|---|---|
| `carson-quota-ceiling-watch` | `scripts\quota_ceiling_watch.py` | 每天 15:20 | 配額天花板變化(基建線 09-02 建) |
| **`carson-seeding-watch`** | `scripts\seeding_watch.py` | **每天 07:00** | 種題例外(-1)、連續 K≥5 個 0、**上游基本面斷料** |
| **`carson-narration-compliance-watch`** | `scripts\narration_compliance_watch.py` | **每天 07:10** | 收束句與業務介紹兩條模板規則的**遵守率** |

共同設定:`youtube_channel\.venv\Scripts\pythonw.exe`、`WorkingDirectory=D:\carson-agent`、
`MultipleInstances=IgnoreNew`、`StartWhenAvailable`、電池上照跑、`ExecutionTimeLimit=15 分鐘`。

## 註冊當下的驗收(2026-09-06 02:10)

**「State=Ready」和「LastTaskResult=0」都不是證據。** 真正的證據是 **log 長出新行**:

```
Start-ScheduledTask 兩支 → 等 25 秒
  seeding-watch.log             9 行 → 10 行   [02:10] ✅ 正常｜…｜上游 09-03 缺0%、09-05 缺0%
  narration-compliance-watch.log 5 行 →  6 行   [02:10] ⏳ 樣本不足只報不判(n=0 < 8)
  NextRunTime  07:00 / 07:10 —— **不是空的**
```

⚠️ `NextRunTime` 為空是本檔上面記過的坑(只掛「登入時」觸發 ⇒ 註冊成功但永遠不會跑)。
這兩支用 `-Daily -At`,是時間觸發,已確認非空。

⚠️ 用 `pythonw` 表示 **stdout 是 None**。三支腳本都把 log 當主通道、print 包在可失敗的
`say()` 裡 —— 這個模式已由排程實跑證明可行(log 真的長出來了)。

## 演習
三支都有 `--selftest`,而且**每一條判準各自要有引爆輸入**:
```
python scripts\seeding_watch.py --selftest=err|zero|stale|upstream|all
python scripts\seeding_watch.py --selftest=unreadable|empty|upstream_ok   # 上游那條(09-08 加)
python scripts\narration_compliance_watch.py --selftest=summary|biz|both
python scripts\quota_ceiling_watch.py --selftest=up|down

# 2026-09-09 加(三支哨都有):推播失敗那兩條路徑的引信
#   pushfail  = push() 回 False(不拋例外那條)
#   pushraise = 推播後端丟例外那條
# 兩個都必須長出「吞掉但留痕」**與**「本輪收尾」兩行。
python scripts\seeding_watch.py              --selftest=pushfail|pushraise
python scripts\narration_compliance_watch.py --selftest=pushfail|pushraise
python scripts\quota_ceiling_watch.py        --selftest=pushfail|pushraise

# 2026-09-09 加(只有 quota):state 檔的四種形狀。
#   first=檔案不存在(陰性,不該報警) / keyless=合法 JSON 少鍵 / nullval=effective 是 null
#   broken=檔案在但不是合法 JSON
# ⚠️ 這四個模式的輸入是**真的寫成 state 檔**(`_drill_state()`),不是注入 `state_existed` 變數。
#   舊版直接注入 ⇒ `STATE.exists()` 那半段壞掉時演習照樣通過 = 空對照(驗證 §五)。
python scripts\quota_ceiling_watch.py --selftest=first|keyless|nullval|broken
```

### 🔴 引信是誰在按:`scripts\watch_drill_regression.py`(2026-09-09 加)

演習存在**不等於**有人會按。獨立驗證掃過 9 支 pythonw 排程、`crontab.txt` 與全 repo:
**零命中** —— 上面這些指令從來沒有任何東西定期跑過
(memory `gate-blind-while-target-evolves`:閘門上線後要有東西**定期證明它還抓得到已知案例**)。

```
python scripts\watch_drill_regression.py          # 12 格:陽性 9 + 陰性 3
python scripts\watch_drill_regression.py --list   # 只列會跑什麼
```

它每次跑都寫一行 `docs/ops/watch-drill-regression.log`(**全過也寫** ⇒ 沒有輸出永遠是異常),
失敗回 `rc=1` 並指名是哪一支的哪一個模式缺了哪個片語。
**它驗的是「留痕還會不會叫」,不是產線健康** —— 它紅了代表哨壞了,不是產線壞了。

陽性對照(2026-09-09 實測):把 `seeding_watch.swallow_epilogue()` 改成 `return` 之後,
它從 `12/12` 掉到 `10/12` 並回 `rc=1`、指名 `seeding_watch.py:pushfail(缺少期望片語:本輪收尾)`;
還原後回到 `12/12`。⇒ **這道回歸不是恆真的。**

⚠️ **還沒排程**:它目前只是「一個指令」,不是「一個引信」。
三支哨是 Windows 排程工作(不在 `crontab.txt` 裡),所以這支的家也該是 Windows 排程工作,
而**新增排程工作屬於另一類正式機變更,等 Carson 拍板**。核准後的註冊指令見
`docs/ops/2026-09-09_pythonw_stdio_correction.md` §六。
🔴 教訓:第一版 `seeding_watch` 只有一種 fixture,它引爆了 `-1` 那條而
「連續 0」那條**完全沒被走到** —— 而後者才是覆蓋歷史真實失效的那條。
**「哨叫了」不等於「每一條判準都會叫」。**

🔴 **第二個教訓(2026-09-08):上面全部都是「該叫的會不會叫」,而那只是一半。**
`upstream_ok` 是這批裡第一個**陰性對照**:沙箱裡放一份健康的事實庫,**期望它不叫**。
沒有這一格,「該叫的都叫了」和「這條判準恆叫」在證據上分不開。
⚠️ 它同時是唯一走完 `upstream_status()` 整條剖析路徑的模式 —— `upstream` 那個是直接注入
算好的 tuple,剖析那段一行都沒跑到。**引信引爆的是判準,還是只是引爆了你手寫的那個 fixture?**
⚠️ `unreadable`/`empty`/`upstream_ok` 會把 `FACTS` monkeypatch 到臨時沙箱,
收尾用正式機檔案的指紋前後比對斷言沒被動過(不一致 → rc=9)。
17MB 的 `STUDIO/stock_checkup_facts.json` **不參與任何演習**。
失敗形態、四項陽性對照與實測數字見 `docs/ops/2026-09-08_gate_health_inventory.md` §十一。

## 端到端推播驗證(2026-09-06 02:12)

獨立驗證員指出:排程那兩次跑的都是**健康分支**,所以
「`notify.push` 在 pythonw + Limited principal 下能不能真的送出」**零證據**。
若它在那個環境失敗,`alert()` 會靜靜地 `say(...)` 掉(而 `say` 在 pythonw 下無聲)
⇒ **log 有紅字而手機沒響** —— 正是昨晚那個病的變體。

已補測:臨時排程工作跑 `push_e2e_test.py`(同 pythonw、同 principal、同 WorkingDirectory):
```
[2026-09-06 02:12:57] push() 回傳 True  (✅ 有後端送出)
```
`notify.push` 只在後端真的回 2xx 時才回 True(08-30 修過:原本 403/404/5xx 全被當成功),
所以這是「真的送出」不是「沒丟例外」。臨時任務跑完即註銷。

### ✅ 2026-09-08:上面那個洞補上了(補的是「留痕」,不是「讓手機一定會響」)

09-06 這段點名的 **「log 有紅字而手機沒響」** 一直開著兩天。09-08 的修法:
三支的 `alert()` 不再把失敗交給 `say(...)`,改走 `swallowed()` **寫進各自的 log 檔**。
⚠️ 而且原本漏了**第二條路**:`push()` 回傳 True/False,**三支都沒看回傳值**
⇒ topic 沒設定、被封、所有後端都失敗(這些**不丟例外**)全部被安靜當成推播成功。
現在兩條都留痕。

🔴 **為什麼不能照 `auditability_coverage`(`8bfaa829`)那樣印到 stderr** —— 09-08 實測
(`DETACHED_PROCESS` 且不傳 std handle,重現無 console 的排程環境):

| 寫法 | 這三支的排程環境 |
|---|---|
| `sys.stdout` / `sys.stderr` | **兩個都是 `None`** |
| `print(msg, file=sys.stderr)` | **靜默 no-op**(`file=None` 退回 `sys.stdout`,而它也是 None) |
| `sys.stderr.write(msg)` | **`AttributeError`** —— 會弄垮哨本身 |
| 寫檔 | ✅ 有效 |

那個範本是給 `local_cron` 的 job 用的(stderr 落 `logs/job_stderr.log`);
這三支是 Windows 排程工作、`pythonw.exe`、**Actions 裡沒有任何重導向**。
⇒ **照抄會在唯一重要的那個環境裡完全靜默,而在互動終端測起來是好的。**
**通道的射程和判準一樣要重新量,不能繼承。** 失敗形態、對照與數字見
`docs/ops/2026-09-08_gate_health_inventory.md` §十二。

### ⚠️ 2026-09-09:要知道這一輪有沒有吞掉東西,看**收尾行**,不要 grep 判決行

獨立驗證(`docs/ops/2026-09-09_verify_bb7ea299.md` §一)實跑 3 支 × `pushfail`/`pushraise` 共 6 次得出:

**`record()` 先寫判決行,`alert()` 後推播** —— 所以**推播失敗發生在判決行已經寫完之後**,
判決行拿不到任何後綴。`grep` 判決行的人看到的是乾淨的「🎉 天花板上移…」/「🔴 種題…」。

| 吞掉發生的時機 | 會出現在哪一行 |
|---|---|
| 判決行**之前**(例:state 讀不掉) | 判決行行尾 `｜⚠️ 本輪吞掉 N 件:…` |
| 判決行**之後**(推播失敗、`say()` 失敗) | 只出現在 `finally` 的 **`⚠️ 本輪收尾:吞掉 N 件`** |

⇒ **判準:`⚠️ 本輪收尾` 那行才是完整的。判決行只涵蓋一半。**

🔴 **這個排序是刻意的,不要「修」它。** `record()` 必須先寫 log 才推播 ——
否則 `say()` 真的吞掉時,連內容都一起丟了。所以要改的是**讀者的判準**(這一節),
不是把 `record()` 往後挪。判準只寫在人腦裡的話,下一個人一樣會 grep 判決行。

🔴 **附帶,同一份驗證查出來的:沒有任何東西會定期跑 `--selftest`。**
9 支 pythonw 排程、`deploy/crontab.txt`、repo 內全部掃過**零命中**。

✅ **2026-09-09 已處理一半**:演習清單已補上 `pushfail`/`pushraise` 與 quota 的四種 state 形狀
(見上面「演習」節),並新增 `scripts\watch_drill_regression.py` 把 12 格演習收成一個指令
+ 一行正向輸出 + 失敗時 `rc=1`(**含破壞測試證明它不是恆真的**)。
🔴 **另一半還沒處理**:那支腳本**還沒有被排進任何排程** ⇒ 引信仍然要人按。
新增排程工作屬於另一類正式機變更,**等 Carson 拍板**;註冊指令備妥在
`docs/ops/2026-09-09_pythonw_stdio_correction.md` §六。
⇒ 在它被排進去之前,**這一條仍然算在下一節的「還沒被證明」裡**。

## 🔴 兩件已知但**還沒被證明**的,不要算進「已完成」

1. ~~**`narration_compliance_watch` 的判定路徑一次都沒被真資料走到。**
   `RULE_DATE=2026-09-06` 而 09-06 目前產出 0 支 ⇒ 它每天只會吐 `⏳ 樣本不足`,
   **要等 ≥8 支 09-06 之後的片落地才有第一個真訊號。**~~
   ✅ **已被走到:2026-09-07 07:10 真事件(`LastTaskResult=1`)。** 這條在 09-07 就過期了,
   而沒人回頭改它 —— 直到 09-08 盤點時被當成「還沒做的事」讀了一次。
   ⚠️ 原句留著的教訓仍然成立:**「它跑起來了」≠「它現在會叫」**。
   ⚠️ 但這道哨的判準本身在 09-08 被量到已經漂了(收束句只認 1/5 種措辭),
   已改成從產線常數 import(`954e283c`)。**被真資料走到 ≠ 走對。**
2. **機器登出時的行為沒驗。** 三支都是 `LogonType=Interactive` / `RunLevel=Limited`
   ⇒ 推測只在 User 登入時才跑。和既有的 quota 哨一致(不是新風險),
   但**若哪天登出或切使用者,三個哨會一起靜默**。

## 為什麼不把這三支放進 `deploy/crontab.txt`(驗證員查出的硬理由)

`local_cron.py:227` 的抽取正則是 `(scripts/[A-Za-z0-9_]+\.py)`,而 `run_job` 用
`cwd=ROOT`,其中 `ROOT = D:\carson-agent\youtube_channel`(`:38`)。
⇒ crontab 裡寫 `scripts/seeding_watch.py` 會被解析成 **`youtube_channel\scripts\seeding_watch.py`**,
而這三支在 **repo 根的 `scripts\`** —— 那個路徑下沒有它們。
結果會是 **註冊成功、每天到點、每天靜默失敗**(stderr 進沒人讀的 `logs/job_stderr.log`)。

第二個理由更重要:**這三支是最後一道哨。**
走 crontab 等於把它們掛在 `LocalCronWatchdog → local_cron → crontab` 這條鏈下面,
而 **local_cron 死掉正是它們該偵測的那類事**。
**哨要和被監視的東西平行,不是它的下游。**
