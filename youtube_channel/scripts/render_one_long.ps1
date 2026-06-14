# render_one_long.ps1 - render a single long video by slug (TTS if needed + make_video landscape + Pexels).
# ASCII-only on purpose (PS 5.1 on zh-TW misreads UTF-8 .ps1).
param([Parameter(Mandatory=$true)][string]$Slug)

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$mp4 = Join-Path $root "output\$Slug.mp4"
$mp3 = Join-Path $root "output\$Slug.mp3"

if (Test-Path $mp4) { Write-Host "skip (exists): $Slug"; exit 0 }

if (-not (Test-Path $mp3)) {
  & $py scripts\tts_edge.py "output\$Slug.voice.txt"
}

$pex = [Environment]::GetEnvironmentVariable("PEXELS_API_KEY", "User")
if ($pex) { $env:PEXELS_API_KEY = $pex }

& $py scripts\make_video.py --slug $Slug

if (Test-Path $mp4) { Write-Host ("DONE: {0}  {1} MB" -f $Slug, [math]::Round((Get-Item $mp4).Length / 1MB, 1)) }
else { Write-Host "FAIL: $Slug" }
