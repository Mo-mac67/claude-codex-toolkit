# ============================================================================
#  RESTORE.ps1  —  Restore Claude Code + Codex from this backup
# ----------------------------------------------------------------------------
#  HOW TO USE (on ANY machine / ANY account):
#    1. Copy a backup folder (backup_YYYY-MM-DD_HHMMSS) onto the target machine.
#    2. Right-click this RESTORE.ps1 (inside that folder) -> "Run with PowerShell"
#       OR in a PowerShell window run:
#           powershell -ExecutionPolicy Bypass -File "<path>\RESTORE.ps1"
#
#  DEFAULT behaviour: restores ALL your chats/history/memory into the current
#  user, but KEEPS the machine's current login (so it works with a DIFFERENT
#  account and never fights over the sign-in).
#
#  -FullRestore : also restore the ORIGINAL account's login/credentials
#                 (use only when cloning onto the same account).
# ============================================================================
param(
    [string]$BackupDir = $PSScriptRoot,
    [switch]$FullRestore
)
$ErrorActionPreference = 'Continue'
$userHome = $env:USERPROFILE

Write-Host "=================================================="
Write-Host " Restoring FROM : $BackupDir"
Write-Host " Restoring INTO : $userHome"
Write-Host " Mode           : $(if($FullRestore){'FULL (incl. original login)'}else{'DATA-ONLY (keeps current login)'})"
Write-Host "=================================================="

# account-specific files that we normally must NOT clobber on a different account
$credFiles = @('.codex\auth.json', '.codex\cap_sid', '.codex\installation_id', '.claude.json', '.claude.json.backup')

# 1) Save the target machine's current login files (so we can keep them)
$safe = Join-Path $userHome (".restore_prev_login_" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
if (-not $FullRestore) {
    foreach ($cf in $credFiles) {
        if (Test-Path "$userHome\$cf") {
            $d = Split-Path "$safe\$cf"; if (-not (Test-Path $d)) { New-Item -ItemType Directory $d -Force | Out-Null }
            Copy-Item "$userHome\$cf" "$safe\$cf" -Force -EA SilentlyContinue
        }
    }
}

# 2) Restore the data folders (merge, never delete existing)
if (Test-Path "$BackupDir\.claude") { Write-Host "-> restoring .claude ..."; robocopy "$BackupDir\.claude" "$userHome\.claude" /E /R:1 /W:1 /XJ /NFL /NDL /NP /NJH /NJS | Out-Null }
if (Test-Path "$BackupDir\.codex")  { Write-Host "-> restoring .codex ...";  robocopy "$BackupDir\.codex"  "$userHome\.codex"  /E /R:1 /W:1 /XJ /NFL /NDL /NP /NJH /NJS | Out-Null }
foreach ($f in @('.claude.json', '.claude.json.backup')) {
    if (Test-Path "$BackupDir\$f") { Copy-Item "$BackupDir\$f" "$userHome\$f" -Force -EA SilentlyContinue }
}

# 3) Unless -FullRestore, put the CURRENT account's login back on top
if (-not $FullRestore) {
    foreach ($cf in $credFiles) {
        if (Test-Path "$safe\$cf") { Copy-Item "$safe\$cf" "$userHome\$cf" -Force -EA SilentlyContinue }
    }
    Write-Host ""
    Write-Host "Kept this machine's current login. Your chats/history are restored."
    Write-Host "(The original account's credentials are still in the backup; rerun with -FullRestore to use them.)"
} else {
    Write-Host ""
    Write-Host "FULL restore done, including original account login."
}

Write-Host ""
Write-Host "DONE. Close and reopen Claude Code / Codex to see the restored history."
