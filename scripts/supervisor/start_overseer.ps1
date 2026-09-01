#requires -version 5.1
<#
總督導的開關。

這支腳本會停在提示等你按 y —— 在你按下去之前它不會啟動任何 agent,
不吃 token 也不吃記憶體。你沒空的時候就進這個窗格按 y,總督導才開始接手。

用法(窗格裡自動跑,平常不必手動下):
    powershell -ExecutionPolicy Bypass -File D:\carson-agent\scripts\supervisor\start_overseer.ps1
#>

$ErrorActionPreference = 'Stop'
$brief = Join-Path $PSScriptRoot 'overseer_brief.md'

Write-Host ""
Write-Host "  ┌────────────────────────────────────────────┐" -ForegroundColor DarkCyan
Write-Host "  │  總督導  ·  未啟用                          │" -ForegroundColor Cyan
Write-Host "  └────────────────────────────────────────────┘" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  啟用後它會做的事:" -ForegroundColor Gray
Write-Host "    · 管理左側與右側四個督導,糾正它們的低價值工作"
Write-Host "    · 跨線資源分配——產能是否壓在回報最高的那條線"
Write-Host "    · 撞車偵測——四條線共用同一個 repo 和同一個頻道"
Write-Host "    · 機器承載——記憶體、殭屍窗格"
Write-Host ""
Write-Host "  它的權限沒有攔截,等同你本人。職責寫在:" -ForegroundColor Gray
Write-Host "    $brief"
Write-Host ""

if (-not (Test-Path $brief)) {
    Write-Host "  找不到職責簡報,無法啟動。" -ForegroundColor Red
    exit 1
}

while ($true) {
    $answer = Read-Host "  按 y 啟用總督導(其他任何鍵維持關閉)"
    if ($answer -match '^[yY]') { break }
    Write-Host "  維持關閉。" -ForegroundColor DarkGray
    Write-Host ""
}

# -Encoding UTF8 不能省:PowerShell 5.1 預設用系統 ANSI 讀檔,繁中機器上簡報會變 Big5 亂碼。
$body = Get-Content $brief -Raw -Encoding UTF8

Write-Host ""
Write-Host "  總督導啟動中……" -ForegroundColor Green
claude --dangerously-skip-permissions $body
