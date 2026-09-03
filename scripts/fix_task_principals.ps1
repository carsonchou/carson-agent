#Requires -RunAsAdministrator
# fix_task_principals.ps1 — 兩支排程任務改 S4U(不論登入與否都執行),含立即驗收。
# 為什麼:兩任務原為 InteractiveToken=僅互動登入時執行,而本機無 AutoAdminLogon——
# 無人值守重開機後看門狗與天花板守望一起死(premises.md 已證偽條)。
# 用法:Carson 在系統管理員 PowerShell 跑本檔(裝 RAM 那趟,按一次 UAC)。
$ErrorActionPreference = "Stop"
$tasks = @("LocalCronWatchdog", "carson-quota-ceiling-watch")
$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\User" -LogonType S4U -RunLevel Limited

foreach ($t in $tasks) {
    Set-ScheduledTask -TaskName $t -Principal $principal | Out-Null
    $lt = ((Export-ScheduledTask -TaskName $t) -split "`n" | Select-String "LogonType") -join ""
    Write-Host ("[OK] {0} -> {1}" -f $t, $lt.Trim())
}

# 立即驗收①:S4U 上下文下 ntfy 真的送得出去(最可能壞的那條,當場驗)
Write-Host "`n[驗收] 建臨時 S4U 任務實測 ntfy..."
$a = New-ScheduledTaskAction -Execute "D:\carson-agent\youtube_channel\.venv\Scripts\python.exe" -Argument "D:\carson-agent\scripts\ntfy_s4u_test.py"
Remove-Item "D:\carson-agent\docs\ops\principal_fix_ntfy_test.txt" -ErrorAction SilentlyContinue  # 防上次殘檔造成假 PASS
Register-ScheduledTask -TaskName "NtfyS4UTest_temp" -Action $a -Principal $principal | Out-Null
Start-ScheduledTask -TaskName "NtfyS4UTest_temp"
Start-Sleep -Seconds 20
Unregister-ScheduledTask -TaskName "NtfyS4UTest_temp" -Confirm:$false
$res = Get-Content "D:\carson-agent\docs\ops\principal_fix_ntfy_test.txt" -ErrorAction SilentlyContinue
Write-Host ("[驗收①結果] {0}" -f ($res -join " "))
if ($res -match "sent=True") { Write-Host "[PASS] ntfy 在 S4U 下活著,手機應剛收到一則「[驗收] S4U 上下文 ntfy 實測」" }
else { Write-Host "[FAIL] ntfy 在 S4U 下沒送出去 —— 不要重開機收工,先回報任一 session 處理(這正是這次修法最怕的洞)" }

Write-Host "`n[驗收②留待重開機] 裝完 RAM 重開機後,任一 session 先跑:"
Write-Host "  Get-ScheduledTaskInfo LocalCronWatchdog,carson-quota-ceiling-watch | Format-List TaskName,LastRunTime"
Write-Host "  兩者 LastRunTime 都在重開機之後 + local_cron 心跳活著 = 真驗收通過(見 premises.md 該條)"
