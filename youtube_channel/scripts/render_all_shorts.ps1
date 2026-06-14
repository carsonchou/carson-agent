# render_all_shorts.ps1 - re-render ALL shorts with concept charts, throttled parallel.
# ASCII-only on purpose (PS 5.1 on zh-TW misreads UTF-8 .ps1).
param([int]$Max = 4)

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

# Shorts use concept charts -> Pexels OFF.
Remove-Item Env:PEXELS_API_KEY -ErrorAction SilentlyContinue

$slugs = Get-ChildItem "output" -Filter "S_*.voice.txt" | ForEach-Object {
  ($_.Name -replace "\.voice\.txt$", "")
}

Write-Host ("re-render {0} shorts, max {1} concurrent" -f $slugs.Count, $Max)
$jobs = @()
foreach ($slug in $slugs) {
  # throttle
  while (($jobs | Where-Object { $_.State -eq 'Running' }).Count -ge $Max) {
    Start-Sleep -Seconds 5
    $jobs = $jobs | Where-Object { $_.State -eq 'Running' -or $_.HasMoreData }
  }
  Write-Host ("START: {0}" -f $slug)
  $j = Start-Job -ScriptBlock {
    param($py, $root, $slug)
    Set-Location $root
    $mp4 = Join-Path $root "output\$slug.mp4"
    Remove-Item $mp4 -ErrorAction SilentlyContinue
    $env:PEXELS_API_KEY = $null
    & $py scripts\make_video.py --slug $slug --width 1080 --height 1920 2>&1 | Out-Null
    if (Test-Path $mp4) { "DONE: $slug $([math]::Round((Get-Item $mp4).Length/1MB,1)) MB" }
    else { "FAIL: $slug" }
  } -ArgumentList $py, $root, $slug
  $jobs += $j
}

Write-Host "all launched; waiting for completion..."
$jobs | Wait-Job | Out-Null
$jobs | ForEach-Object { Receive-Job $_ } | ForEach-Object { Write-Host $_ }
$jobs | Remove-Job -Force -ErrorAction SilentlyContinue
Write-Host "ALL SHORTS DONE"
