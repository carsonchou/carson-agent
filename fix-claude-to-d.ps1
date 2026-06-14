# ============================================================
#  Link C:\Users\User\.claude  ->  D:\.claude  (Claude only)
#  RUN AFTER fully closing the current Claude session.
#  Run in PowerShell:
#     powershell -ExecutionPolicy Bypass -File D:\carson-agent\fix-claude-to-d.ps1
# ============================================================
$ErrorActionPreference = 'Stop'
$ts   = Get-Date -Format 'yyyyMMdd-HHmmss'
$hc   = "$env:USERPROFILE\.claude"
$main = "D:\.claude"

Write-Host "==== Link Claude config to D: ====" -ForegroundColor Cyan

# 0) Claude must be closed
if (Get-Process -Name claude -ErrorAction SilentlyContinue) {
    Write-Host "[ABORT] Claude is still running. Close this Claude session first." -ForegroundColor Red
    pause; exit 1
}

# 1) main env must exist and be the BIG one
if (-not (Test-Path -LiteralPath $main)) { Write-Host "[ABORT] $main not found" -F Red; pause; exit 1 }
$mainCount = (Get-ChildItem -LiteralPath $main -Recurse -Force -EA SilentlyContinue | Measure-Object).Count
Write-Host "Main env D:\.claude items = $mainCount"
if ($mainCount -lt 500) { Write-Host "[ABORT] D:\.claude too small ($mainCount), refuse" -F Red; pause; exit 1 }

# 2) handle C shadow .claude
if (Test-Path -LiteralPath $hc) {
    $it = Get-Item -LiteralPath $hc -Force
    if (($it.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Write-Host "C:\Users\User\.claude already a link, skip."
    } else {
        $hcCount = (Get-ChildItem -LiteralPath $hc -Recurse -Force -EA SilentlyContinue | Measure-Object).Count
        if ($hcCount -gt 1000) { Write-Host "[ABORT] C .claude unexpectedly large ($hcCount)" -F Red; pause; exit 1 }
        if (Test-Path -LiteralPath "$hc\projects") {
            $null = robocopy "$hc\projects" "$main\projects" /E /XO /R:0 /W:0 /NFL /NDL /NJH /NJS
            Write-Host "merged shadow projects into main env"
        }
        Rename-Item -LiteralPath $hc -NewName ".claude.bak-$ts"
        Write-Host "C shadow renamed to .claude.bak-$ts"
        cmd /c mklink /J "$hc" "$main" | Out-Null
        $chk = Get-Item -LiteralPath $hc -Force
        if (($chk.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { Write-Host "OK: junction C:\...\.claude => D:\.claude" -F Green }
        else { Write-Host "[WARN] junction failed; backup kept at .claude.bak-$ts" -F Red }
    }
} else { Write-Host "C .claude not present, will just create junction"; cmd /c mklink /J "$hc" "$main" | Out-Null }

# 3) .claude.json -> symlink to D (dev mode is ON)
$hj = "$env:USERPROFILE\.claude.json"
$dj = "$main\.claude.json"
if (Test-Path -LiteralPath $hj) {
    $hjit = Get-Item -LiteralPath $hj -Force
    if (($hjit.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
        try {
            if (-not (Test-Path -LiteralPath $dj)) { Copy-Item -LiteralPath $hj -Destination $dj -Force }
            Rename-Item -LiteralPath $hj -NewName ".claude.json.bak-$ts"
            New-Item -ItemType SymbolicLink -Path $hj -Target $dj | Out-Null
            Write-Host "OK: .claude.json => symlink to D:\.claude\.claude.json" -F Green
        } catch { Write-Host "[WARN] .claude.json symlink failed: $($_.Exception.Message)" -F Yellow }
    } else { Write-Host ".claude.json already a link, skip." }
}

Write-Host ""
Write-Host "DONE. Reopen Claude and run:  `$env:CLAUDE_CONFIG_DIR  (should show D:\.claude)" -ForegroundColor Green
Write-Host "Backups (delete after verifying): .claude.bak-$ts , .claude.json.bak-$ts" -ForegroundColor DarkGray
pause
