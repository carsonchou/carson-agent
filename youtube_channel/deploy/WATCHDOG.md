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
