# LocalCronWatchdog 沙箱雙胞胎測試(2026-09-03,基建線)

> 方法:註冊臨時任務 `LocalCronWatchdog_SandboxTest`(設定一比一抄正式,僅時間觸發器;LOCK/TARGET/LOG 全指 scratchpad 沙箱,假 cron 名 `local_cron_sb.py` 與正式 MARK 子字串雙向互斥)。沙箱設定經 verify-sandbox-task 兩輪驗證後掛載(它先抓到假 cron 的 SyntaxError 阻斷——heredoc 反斜線坑,memory 有記仍踩)。產線零接觸,測畢即拆。

## 界線聲明(督導原話,先讀這個再讀 PASS)

**這輪證明的是「看門狗醒著的時候有用」,證明不了「它會醒來」。** 登入/開機觸發面零覆蓋(非提權註冊 LogonTrigger 被拒);觀測窗口=下次重開機(RAM 安裝),見 premises.md。

## V1~V5

- **V1 PASS**:Task Scheduler 真觸發 ≥2 輪——11:20:29 首輪(心跳 None→start,log 有拉起紀錄)、11:25:30 次輪(LastRunTime,Result=0,noop 且 alert 檔被清=noop 路徑實跑)。
- **V2 PASS**:11:28:52 殺假 cron(venv stub+真直譯器父子對,恰為 watchdog 註解寫的「2 筆」)→ 11:30:29 輪心跳齡 ~100s<180 → noop(由 11:35:30 的「心跳 401.7 秒」回推 last touch=11:28:48,算術上證明該輪未動手)→ 11:35:30 拉回 pid=376、心跳續寫、LOCK=376。
- **V3(單獨講)——子程序活下來**:條件=ExecutionTimeLimit **30 秒**、`-Once`+PT5M 重複觸發、非提權、當前登入 session、pythonw 執行、子程序以 `CREATE_NO_WINDOW|DETACHED_PROCESS` 拉起。11:40:30 watchdog 拉起 pid=46124(60 秒首觸延遲使其卡在 verify 迴圈)→ 若活過 45 秒必留「心跳沒恢復」log+failed 推播,兩者皆無 → 於 30~45 秒間被排程器逾時終止 → **子程序 11:41:30 準時首觸、心跳連續 7 分鐘、11:45:30 輪見新鮮心跳 noop(兼證無雙生)**。⚠️ 這**不涵蓋**登入/開機觸發路徑;正式任務 PT15M vs VERIFY_SEC 45s,正常運作不會撞逾時,此結果覆蓋的是「watchdog 卡死被砍」的邊角。
- **V4 PASS**:排程環境(無 .env)ntfy 端到端送達——11:20:35 ntfy 訊息史查得「[沙箱測試,可忽略] ⚠️ 排程器被重啟」。**這是 ntfy 通道第一次被真事件證明活著**(此前只走過 [DRILL])。
- **V5 PASS**:`Unregister-ScheduledTask` 已拆(回查無);正式 `LocalCronWatchdog` 逐項與測前快照一致(pythonw+同腳本、IgnoreNew、PT15M、StartWhenAvailable、電池兩 flag false、logon+time 雙觸發皆 PT5M),測後仍在跑(11:47:58 Result=0)。

## 主發現(不是附註)

1. **crash-loop 通知靜默降頻(產線缺陷,V2 實測)**:`_push()` 同因推播 3600s 冷卻內**靜默丟棄、連被擋都不記 log**(watchdog:136-141)。crash-loop 形狀=排程器每幾分鐘死一次、每次救援成功、Carson 每小時只收一則不含次數的孤立推播——迴圈不可見,log 有全記錄但無人讀(dispatch §6 第零種)。修法方向(w9 的檔):**次數進推播內文**,N 遞增即新資訊放行。已登記 premises.md。
2. **正式任務觸發面盤點**:LogonTrigger 存在、Rep=PT5M、RunLevel=Limited、**LogonType=Interactive → 「重開機自動起來」實際依賴有人登入(或自動登入)**,純開機無登入不觸發。形狀=「設定存在、依賴登入、未被觀察」,非「設定錯」。

## 未驗清單(別把 PASS 讀成全覆蓋)

登入/開機觸發實際行為;睡眠喚醒補跑(StartWhenAvailable 只驗了設定在);逾時終止在 PT15M/正式條件下的重現;機器無自動登入時的開機空窗。
