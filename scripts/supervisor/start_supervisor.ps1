#requires -version 5.1
<#
啟動一個督導 agent,代表 Carson 監督並強化指定的 session。

用法:
    powershell -ExecutionPolicy Bypass -File D:\carson-agent\scripts\supervisor\start_supervisor.ps1 `
        -SessionName "main ch." -TargetPane "w9:p1"

督導的職責寫在同目錄的 supervisor_brief.md,改那份就會改變所有督導的行為。
#>

param(
    [Parameter(Mandatory = $true)][string]$SessionName,
    [Parameter(Mandatory = $true)][string]$TargetPane
)

$ErrorActionPreference = 'Stop'
$brief = Join-Path $PSScriptRoot 'supervisor_brief.md'

if (-not (Test-Path $brief)) {
    Write-Host "找不到職責簡報:$brief" -ForegroundColor Red
    exit 1
}

# -Encoding UTF8 不能省:PowerShell 5.1 預設用系統 ANSI 讀檔,繁中機器上會把簡報解成 Big5 亂碼。
$body = Get-Content $brief -Raw -Encoding UTF8

$prompt = @"
你督導的 session 是「$SessionName」,它的 herdr 窗格是 $TargetPane。

$body
"@

Write-Host "啟動督導:$SessionName(目標窗格 $TargetPane)" -ForegroundColor Cyan
claude --dangerously-skip-permissions $prompt
