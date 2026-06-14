# upload_all.ps1 - Upload all rendered mp4 in output/ to YouTube as PRIVATE drafts.
# (ASCII-only on purpose: PowerShell 5.1 on a zh-TW system misreads UTF-8 .ps1 as Big5.)
#
# Usage (run inside youtube_channel):
#   .\scripts\upload_all.ps1            # dry-run preview (does NOT upload)
#   .\scripts\upload_all.ps1 -Go        # really upload (default privacy = private)
#   .\scripts\upload_all.ps1 -Go -Privacy unlisted
#
# Requires Google OAuth set up (client_secrets.json in project root; first run
# opens a browser once for you to click "Allow"). See 05_Google上架授權設定.md.

param(
  [switch]$Go,
  [string]$Privacy = "private"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

$mp4s = Get-ChildItem (Join-Path $root "output") -Filter *.mp4 -ErrorAction SilentlyContinue
if (-not $mp4s) {
  Write-Host "No mp4 found in output\ - nothing to upload."
  exit 0
}

Write-Host ("Found {0} video(s):" -f $mp4s.Count)
foreach ($f in $mp4s) {
  $slug = [IO.Path]::GetFileNameWithoutExtension($f.Name)
  $sizeMB = [math]::Round($f.Length / 1MB, 2)
  Write-Host ("  - {0}  ({1} MB)" -f $slug, $sizeMB)
  $pyArgs = @("scripts\upload_youtube.py", $slug, "--privacy", $Privacy)
  if (-not $Go) { $pyArgs += "--dry-run" }
  & $py @pyArgs
  Write-Host ("-" * 60)
}

if (-not $Go) {
  Write-Host ""
  Write-Host "DRY-RUN preview only (nothing uploaded). Add -Go to really upload:"
  Write-Host "  .\scripts\upload_all.ps1 -Go"
} else {
  Write-Host ""
  Write-Host ("Done. All uploaded as privacy={0}. Check YouTube Studio, then set public manually." -f $Privacy)
}
