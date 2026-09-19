#requires -version 5.1
<#
herdr 現場健檢:一次列出所有窗格,標出哪些 shell 窗格已經跑完可以關掉。

用法:
    powershell -ExecutionPolicy Bypass -File D:\carson-agent\scripts\herdr_doctor.ps1

判斷閒置的方式是看窗格最後一行是不是裸的 PowerShell 提示字元。
不要改用「隔幾秒採樣兩次比對有無變化」——每分鐘刷新一次的狀態板在
短間隔內看起來是靜止的,會被誤判成死掉的窗格。
#>

$ErrorActionPreference = 'Stop'
$herdr = if ($env:HERDR_BIN_PATH) { $env:HERDR_BIN_PATH } else { 'herdr' }

try {
    # 取指令輸出這一步也要包在 try 裡:herdr 不在 PATH 時,& 會丟終止性例外,
    # 攔不到就變成一整串英文呼叫堆疊,而不是下面那句看得懂的提示。
    $raw = & $herdr pane list 2>&1 | Out-String
    $panes = ($raw | ConvertFrom-Json).result.panes
} catch {
    Write-Host "herdr pane list 讀不到或解析失敗:" -ForegroundColor Red
    Write-Host $raw
    exit 1
}

$idle = @()
$rows = foreach ($p in $panes) {
    $isAgent = -not [string]::IsNullOrWhiteSpace($p.agent)

    if ($isAgent) {
        $kind   = 'agent'
        $state  = $p.agent_status
        $advice = '保留'
    } else {
        $tail = (& $herdr pane read $p.pane_id --source recent-unwrapped --lines 6 2>&1 | Out-String)
        $last = ($tail -split "`n" | Where-Object { $_.Trim() -ne '' } | Select-Object -Last 1)
        $kind = 'shell'
        if ([string]::IsNullOrWhiteSpace($tail)) {
            # 讀不到任何內容,不能當成還在跑,也不能當成閒置——標出來讓人自己看。
            $state  = '讀不到'
            $advice = '待查'
        } elseif ($last -match 'PS [A-Za-z]:\\[^>]*>\s*$') {
            $state  = '閒置'
            $advice = '可關'
            $idle  += $p.pane_id
        } else {
            $state  = '有輸出'
            $advice = '保留'
        }
    }

    [PSCustomObject]@{
        Pane  = $p.pane_id
        Kind  = $kind
        State = $state
        Cwd   = $p.cwd
        建議  = $advice
    }
}

$rows | Format-Table -AutoSize

$os   = Get-CimInstance Win32_OperatingSystem
$free = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
Write-Host ("可用記憶體 {0} GB / 共 {1} GB" -f $free, [math]::Round($os.TotalVisibleMemorySize / 1MB, 2))

if ($idle.Count -gt 0) {
    Write-Host ""
    Write-Host "跑完可關的窗格($($idle.Count) 個):" -ForegroundColor Yellow
    # 一行一個指令。串接兩個以上的 close 會被 Claude Code 的 auto-mode 分類器擋掉。
    foreach ($id in $idle) { Write-Host "  herdr pane close $id" }
} else {
    Write-Host ""
    Write-Host "沒有閒置窗格。" -ForegroundColor Green
}
