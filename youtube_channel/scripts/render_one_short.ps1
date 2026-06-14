# render_one_short.ps1 - render a single SHORT by slug (vertical 1080x1920, concept charts, no Pexels).
# ASCII-only on purpose (PS 5.1 on zh-TW misreads UTF-8 .ps1).
param([Parameter(Mandatory=$true)][string]$Slug, [switch]$Force)

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$mp4 = Join-Path $root "output\$Slug.mp4"
$mp3 = Join-Path $root "output\$Slug.mp3"

if ((Test-Path $mp4) -and (-not $Force)) { Write-Host "skip (exists): $Slug"; exit 0 }
if ($Force) { Remove-Item $mp4 -ErrorAction SilentlyContinue }

if (-not (Test-Path $mp3)) {
  & $py scripts\tts_edge.py "output\$Slug.voice.txt"
}

# Shorts use concept charts -> ensure Pexels is OFF for this process.
Remove-Item Env:PEXELS_API_KEY -ErrorAction SilentlyContinue

& $py scripts\make_video.py --slug $Slug --width 1080 --height 1920

if (Test-Path $mp4) { Write-Host ("DONE: {0}  {1} MB" -f $Slug, [math]::Round((Get-Item $mp4).Length / 1MB, 1)) }
else { Write-Host "FAIL: $Slug" }
