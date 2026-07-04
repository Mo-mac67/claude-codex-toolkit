# Claude + Codex Toolkit

**Backup, restore, migrate & convert your AI-coding chat history** between
[Claude Code](https://claude.com/claude-code) (Anthropic) and
[Codex](https://openai.com/codex) (OpenAI) — portable across machines and accounts.

Born out of a real incident: a cleanup accidentally wiped months of Codex chat
sessions with no local recovery possible (SSD TRIM + no restore points).
Never again. 🛡️

## Features

- **Timestamped full backups** of `~/.claude`, `~/.claude.json` and `~/.codex` —
  every run creates a new `backup_YYYY-MM-DD_HHMMSS` folder, nothing is ever overwritten.
- **Portable restore** — copy a backup folder to *any* machine and restore under
  *any* account: by default your chats/history come back while the target
  machine's current login is kept (no account conflicts). A full-clone mode
  restores the original credentials too.
- **Chat conversion (both directions)** — turn a Claude Code session into a
  Codex session and vice-versa. Converted chats appear natively in the target
  app's chats/projects list (text of the conversation; tool-call internals are
  intentionally not carried over).
- **Software bootstrap** — on a fresh machine the tool checks & installs
  Node.js, Claude Code and Codex CLI for you (Windows: winget + npm).
- **Self-contained snapshots** — the tool and the PowerShell restore script are
  copied into every backup folder, so each snapshot can restore itself.
- **Non-destructive by design** — the tool only ever *writes new files*.
  It never deletes anything.

## Quick start

```bash
# put claude_tool.py in the folder where you want backups to live, then:
python claude_tool.py
```

```
1) Full backup now (new timestamp)
2) Restore a version (you pick)
3) Check/install software
4) Convert chats: Claude Code -> Codex
5) Convert chats: Codex -> Claude Code
```

Non-interactive backup (great for schedulers):

```bash
python claude_tool.py backup
```

### Scheduled backups (Windows)

`backup_scheduled.ps1` is a robocopy-based equivalent of menu option 1.
Register it with Task Scheduler, e.g. 3×/week:

```powershell
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "X:\Your Backup\backup_scheduled.ps1"'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Wednesday,Friday -At '12:00pm'
Register-ScheduledTask -TaskName 'Claude+Codex Backup' -Action $action -Trigger $trigger
```

### Restoring on another machine / another account

1. Copy one `backup_...` folder to the target machine.
2. Run `python claude_tool.py` → option 2 (or right-click `RESTORE.ps1` → Run with PowerShell).
3. Choose **chats-only** (default — keeps the target's current sign-in, so a
   different/company account works fine) or **full clone**.

## How chat conversion works

| Direction | What happens |
|---|---|
| Claude → Codex | Session text is rewritten as a Codex `rollout-*.jsonl` (the same structure Codex's own external-import feature produces) and registered in `session_index.jsonl` with a `[Claude]` prefix. |
| Codex → Claude | Session text is rewritten as a Claude Code project session (`~/.claude/projects/<cwd-slug>/<uuid>.jsonl`) with a valid parent-uuid chain, so it shows up under the matching project. |

> ⚠️ Formats were reverse-engineered from real session files (July 2026,
> Claude Code 2.x / Codex 0.14x). App updates may change them — please open an
> issue if a conversion stops working.

## Security note

Backups contain your **login tokens** (`.codex/auth.json`, `.claude.json`).
Keep backup folders on a drive you trust, and treat them like passwords.

## License

MIT — fork away. © 2026 Mo Bamzadeh
