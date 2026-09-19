# apply_logon_trigger.ps1 -- fix (2): add an AtLogOn trigger (5 min delay) to the two
# watch tasks that missed their 07:00/07:10 run on 2026-09-10.
#
# WHY XML AND NOT Set-ScheduledTask -Trigger:
#   Set-ScheduledTask -Trigger REPLACES the whole trigger set. Passing only the new
#   trigger would silently delete the daily CalendarTrigger -- the same shape as
#   memory `write-truncates-before-it-fails`. Editing the exported XML preserves the
#   original CalendarTrigger BY CONSTRUCTION: we only insert one element.
#
# ASCII-only on purpose (memory `write-tool-ps1-needs-bom`).
# Baseline XMLs were exported to *.before.xml BEFORE any change.
# Run with -Apply to actually change anything; without it, dry run only.

param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$sp  = Split-Path -Parent $MyInvocation.MyCommand.Path
$sid = 'S-1-5-21-639895186-3528793508-2951188905-1001'

$targets = @('carson-seeding-watch','carson-narration-compliance-watch')

# STAGGERED ON PURPOSE (independent verification 2026-09-11, item 3-5).
# The first draft gave BOTH targets Delay=PT5M. On a logon-recovery day they would
# start in the same second, flattening the 10-minute gap the daily schedule has
# (07:00 / 07:10). Whichever finishes first calls the cross-check while the other
# has not written its reading line yet -> it reports its neighbour as silent.
# That is one FALSE push per recovery day, landing right next to the real signal,
# and alert fatigue eats real signals (3-1). Keep these two apart.
# NOTE: the fix_plan 1.1 remedy ("write your own line first") only cures the
# caller's own cell; it cannot cure the neighbour's cell. Staggering does.
$delay = @{
    'carson-seeding-watch'             = 'PT5M'
    'carson-narration-compliance-watch' = 'PT15M'
}

# quota is NOT touched: it runs 15:20, far from the logon window, and it is the only
# pivot the cross-check design has. Record its fingerprint so "untouched" is provable.
$quotaBefore = (Get-FileHash "$sp\carson-quota-ceiling-watch.before.xml" -Algorithm SHA256).Hash

foreach ($t in $targets) {
    $before = Get-Content "$sp\$t.before.xml" -Raw
    if ($before -match '<LogonTrigger>') { Write-Output "$t : already has LogonTrigger, skip"; continue }
    if ($before -notmatch '</Triggers>') { throw "$t : no </Triggers> in exported XML" }

    if (-not $delay.ContainsKey($t)) { throw "$t : no stagger delay defined -- ABORT" }
    $logon = @"
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$sid</UserId>
      <Delay>$($delay[$t])</Delay>
    </LogonTrigger>
"@

    $after = $before -replace '(?s)(\s*)</Triggers>', ("`r`n" + $logon + "  </Triggers>")
    Set-Content "$sp\$t.after.xml" -Value $after -Encoding UTF8

    # assert the calendar trigger survived the edit, BEFORE registering anything
    foreach ($must in '<CalendarTrigger>','<StartBoundary>','<ScheduleByDay>','<DaysInterval>1</DaysInterval>') {
        if ($after -notmatch [regex]::Escape($must)) { throw "$t : edit ate $must -- ABORT" }
    }
    $sb = ([regex]'<StartBoundary>([^<]+)</StartBoundary>').Match($before).Groups[1].Value
    if ($after -notmatch [regex]::Escape($sb)) { throw "$t : StartBoundary $sb missing after edit -- ABORT" }
    # the stagger itself is an assertion, not a comment
    if ($after -notmatch [regex]::Escape("<Delay>$($delay[$t])</Delay>")) { throw "$t : stagger delay missing -- ABORT" }
    Write-Output "$t : dry-run ok, StartBoundary $sb preserved, LogonTrigger Delay=$($delay[$t]) inserted"

    if (-not $Apply) { continue }

    Register-ScheduledTask -TaskName $t -Xml $after -User $sid -Force | Out-Null

    # READ BACK from the live scheduler -- not from our own string
    $rb = Export-ScheduledTask -TaskName $t
    Set-Content "$sp\$t.readback.xml" -Value $rb -Encoding UTF8
    $ok = ($rb -match '<LogonTrigger>') -and ($rb -match [regex]::Escape($sb)) -and ($rb -match '<ScheduleByDay>')
    $n  = (Get-ScheduledTask -TaskName $t).Triggers.Count
    Write-Output "$t : APPLIED  readback_ok=$ok triggers=$n (expect 2)"
    if (-not $ok) { throw "$t : READBACK FAILED -- restore from $t.before.xml immediately" }
}

# prove quota was not touched
$q = Export-ScheduledTask -TaskName 'carson-quota-ceiling-watch'
Set-Content "$sp\carson-quota-ceiling-watch.now.xml" -Value $q -Encoding UTF8
$quotaNow = (Get-FileHash "$sp\carson-quota-ceiling-watch.now.xml" -Algorithm SHA256).Hash
Write-Output "quota sha256 before=$quotaBefore now=$quotaNow same=$($quotaBefore -eq $quotaNow)"
