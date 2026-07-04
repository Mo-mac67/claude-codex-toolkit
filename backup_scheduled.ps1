# ============================================================================
#  backup_scheduled.ps1 — Full, timestamped backup of Claude Code + Codex
#  Backups are written NEXT TO THIS SCRIPT. Register with Task Scheduler.
#  Each run = a new timestamped folder (never overwrites).
# ============================================================================
$ErrorActionPreference = 'Continue'
$root     = $PSScriptRoot
$userHome = $env:USERPROFILE
$ts       = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$dest     = Join-Path $root "backup_$ts"
$log      = Join-Path $root 'backup_log.txt'

function LogB($m){ "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File $log -Append -Encoding utf8 }

New-Item -ItemType Directory $dest -Force | Out-Null
LogB "=== BACKUP START -> $dest  (home: $userHome) ==="

if (Test-Path "$userHome\.claude") { robocopy "$userHome\.claude" "$dest\.claude" /E /R:1 /W:1 /XJ /NFL /NDL /NP /NJH /NJS | Out-Null }
if (Test-Path "$userHome\.codex")  { robocopy "$userHome\.codex"  "$dest\.codex"  /E /R:1 /W:1 /XJ /NFL /NDL /NP /NJH /NJS | Out-Null }
foreach ($f in @('.claude.json', '.claude.json.backup')) {
    if (Test-Path "$userHome\$f") { Copy-Item "$userHome\$f" "$dest\$f" -Force -EA SilentlyContinue }
}
foreach ($helper in @('RESTORE.ps1','claude_tool.py')) {
    if (Test-Path "$root\$helper") { Copy-Item "$root\$helper" "$dest\$helper" -Force -EA SilentlyContinue }
}

$n  = (Get-ChildItem $dest -Recurse -File -Force -EA SilentlyContinue | Measure-Object).Count
$sz = (Get-ChildItem $dest -Recurse -File -Force -EA SilentlyContinue | Measure-Object Length -Sum).Sum
LogB "BACKUP DONE: $n files, $([math]::Round($sz/1MB,1)) MB"
