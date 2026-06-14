# batch_render.ps1 - Mass-produce videos with FREE edge-tts + make_video.
# Shorts (S_*) -> vertical 1080x1920 card style. Longs (L_*) -> landscape + Pexels.
# ASCII-only on purpose (PS 5.1 on zh-TW misreads UTF-8 .ps1).
#
# Usage:  .\scripts\batch_render.ps1            # render all S_* and L_* lacking mp4
#         .\scripts\batch_render.ps1 -Shorts 5  # only first 5 shorts

param([int]$Shorts = 999, [int]$Longs = 999)

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$pex = [Environment]::GetEnvironmentVariable("PEXELS_API_KEY", "User")

function Render-One($voicePath, [bool]$vertical, [bool]$usePexels) {
  $slug = ([IO.Path]::GetFileName($voicePath)) -replace "\.voice\.txt$", ""
  $mp4 = Join-Path $root "output\$slug.mp4"
  if (Test-Path $mp4) { Write-Host "  skip (exists): $slug"; return }
  & $py scripts\tts_edge.py "output\$slug.voice.txt" 2>&1 | Select-String "ok|FATAL" | Select-Object -Last 1
  if ($usePexels -and $pex) { $env:PEXELS_API_KEY = $pex } else { Remove-Item Env:PEXELS_API_KEY -ErrorAction SilentlyContinue }
  if ($vertical) {
    & $py scripts\make_video.py --slug $slug --width 1080 --height 1920 2>&1 | Select-String "完成|FATAL" | Select-Object -Last 1
  } else {
    & $py scripts\make_video.py --slug $slug 2>&1 | Select-String "完成|FATAL" | Select-Object -Last 1
  }
  if (Test-Path $mp4) { Write-Host ("  DONE: {0}  {1} MB" -f $slug, [math]::Round((Get-Item $mp4).Length / 1MB, 1)) }
  else { Write-Host "  FAIL: $slug" }
}

$sList = Get-ChildItem "output" -Filter "S_*.voice.txt" | Select-Object -First $Shorts
$i = 0
foreach ($f in $sList) { $i++; Write-Host ("=== SHORT {0}/{1} ===" -f $i, $sList.Count); Render-One $f.FullName $true $false }

$lList = Get-ChildItem "output" -Filter "L_*.voice.txt" | Select-Object -First $Longs
$i = 0
foreach ($f in $lList) { $i++; Write-Host ("=== LONG {0}/{1} ===" -f $i, $lList.Count); Render-One $f.FullName $false $true }

Write-Host "BATCH COMPLETE"
