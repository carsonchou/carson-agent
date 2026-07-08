# One-time setup: auto background render on PC logon (safe dual-mode PC side).
# Low priority, no window, auto-restart on crash. PC on = accelerate; PC off = cloud fallback still runs.
$ErrorActionPreference = "Stop"
$py   = "D:\carson-agent\youtube_channel\.venv\Scripts\pythonw.exe"
$scr  = "D:\carson-agent\youtube_channel\scripts\hybrid_render.py"
$work = "D:\carson-agent\youtube_channel"

if (-not (Test-Path $py))  { Write-Host "ERROR: pythonw not found: $py"; exit 1 }
if (-not (Test-Path $scr)) { Write-Host "ERROR: script not found: $scr"; exit 1 }

$arg = '"' + $scr + '" --pc --loop --interval 600'
$action   = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory $work
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit ([TimeSpan]::Zero)
$settings.Priority = 7

Register-ScheduledTask -TaskName "CarsonQuant_PCRender" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "CarsonQuant_PCRender"
Start-Sleep -Seconds 4
$t = Get-ScheduledTask -TaskName "CarsonQuant_PCRender"
Write-Host ("TASK STATE: " + $t.State)
Write-Host ("pythonw procs: " + (Get-Process pythonw -ErrorAction SilentlyContinue | Measure-Object).Count)
Write-Host "DONE. Auto-renders on every logon. To remove: Unregister-ScheduledTask -TaskName CarsonQuant_PCRender -Confirm:`$false"
