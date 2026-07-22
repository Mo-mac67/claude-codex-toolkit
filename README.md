# Claude + Codex Toolkit

**Backup, restore, migrate, convert, export & search** your AI-coding chat
history across [Claude Code](https://claude.com/claude-code) (Anthropic) and
[Codex](https://openai.com/codex) (OpenAI) — portable across machines and accounts.

Single self-contained Python file, **no required dependencies**. Optional extras
(`cryptography` for token encryption, `rclone` for cloud) are loaded lazily.

Born from a real incident: a disk cleanup wiped months of Codex sessions with no
local recovery possible (SSD TRIM, no restore points). Never again.

[![CI](https://github.com/Mo-mac67/claude-codex-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/Mo-mac67/claude-codex-toolkit/actions)

## Features

- **Timestamped full backups** of `~/.claude`, `~/.claude.json` and `~/.codex` —
  every run makes a new `backup_YYYY-MM-DD_HHMMSS`; nothing is ever overwritten.
- **Migrate wizard** — change the account behind Claude Code and/or Codex
  without losing a single chat: safety backup → current login saved as a
  profile → you log into the new account → the wizard verifies every chat
  survived and saves the new login too.
- **Quick user switch** — save each account's login once as a named *profile*,
  then flip between accounts in seconds (CLI menu, `switch` command, or the
  GUI's Accounts tab). The login being replaced is auto-saved first, so
  switching is always reversible. Chats are never touched.
- **Portable, account-safe restore** — copy a backup to any machine/account and
  restore. Default keeps the target's current login (no account conflicts); a
  full-clone mode restores the original credentials too. Works from folders or `.zip`.
- **Compression** — store snapshots as a single `.zip`.
- **Retention** — optionally keep only the last N backups (off by default).
- **Integrity manifests** — `MANIFEST.sha256` in every backup; verify anytime.
- **Token encryption** — encrypt login files inside a backup with a password
  (Fernet + PBKDF2). Password via `CCT_BACKUP_PASSWORD` env var or prompt.
- **Cloud upload** — push a backup to Google Drive / OneDrive / S3 via `rclone`.
- **Chat conversion (both directions)** — Claude Code ⇄ Codex. Converted chats
  appear natively in the target app's projects/chats. Tool-use/tool-result
  activity is preserved as readable text.
- **Export** — any session to Markdown or HTML for archiving/sharing.
- **Full-text search** — across all live chats and (optionally) all backups.
- **Software bootstrap** — checks & installs Node.js / Claude Code / Codex CLI.
- **GUI** — a Tkinter front-end with a tab for every action.
- **Non-destructive** — the tool only writes new files; it never deletes chats.

## Install

Zero-install (just the file):

```bash
python claude_tool.py
```

Or via pip (adds `cct` and `cct-gui` commands):

```bash
pip install .            # from a clone
pip install ".[crypto]"  # + token encryption support
```

## Usage

Interactive menu:

```
1) Full backup now                8) Verify a backup (checksums)
2) Restore a version              9) Upload a backup to cloud
3) Check/install software        10) Settings
4) Convert Claude Code -> Codex  11) Migrate to a new account
5) Convert Codex -> Claude Code  12) Switch user (saved profiles)
6) Export chats (Markdown/HTML)
7) Search all chat history
```

Command line:

```bash
python claude_tool.py backup                 # non-interactive (schedulers)
python claude_tool.py verify backup_2026-...  # check a backup's checksums
python claude_tool.py search "postgres migration" --backups
python claude_tool.py export codex --html
python claude_tool.py migrate                 # account-migration wizard
python claude_tool.py switch --list           # show logins + saved profiles
python claude_tool.py switch codex --save     # save current Codex login
python claude_tool.py switch codex work@corp.com   # flip to that profile
python claude_tool_gui.py                     # GUI
```

### Switching / migrating accounts

Chats are **local files**, not part of your account — so changing accounts
never deletes them. Two tools build on that:

- **Migrate wizard** (menu 11 / `migrate` / GUI *Migrate* tab) for a one-time
  move: it backs everything up, keeps the old login as a profile, waits while
  you log into the new account, then verifies the account changed and every
  session is still there.
- **User switch** (menu 12 / `switch` / GUI *Accounts* tab) for day-to-day
  flipping between saved logins ("profiles"). Profiles store only the small
  credential files (`.codex/auth.json`, `.claude.json`, …) under
  `profiles/<app>/<name>` next to the script. For Claude Code the profile file
  also carries some app state, since Claude keeps both in `.claude.json`.
  Restart the app after a switch.

### Scheduled backups (Windows)

`backup_scheduled.ps1` writes a timestamped backup next to itself. Register it
with Task Scheduler, e.g. 3×/week:

```powershell
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "X:\Your Backup\backup_scheduled.ps1"'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Wednesday,Friday -At '12:00pm'
Register-ScheduledTask -TaskName 'Claude+Codex Backup' -Action $action -Trigger $trigger
```

For encrypted scheduled backups, set `CCT_BACKUP_PASSWORD` in the task's
environment and turn on `encrypt` in Settings.

## How chat conversion works

| Direction | What happens |
|---|---|
| Claude → Codex | Rewritten as a Codex `rollout-*.jsonl` (same structure Codex's own external-import produces) and registered in `session_index.jsonl` with a `[Claude]` prefix. |
| Codex → Claude | Rewritten as a Claude Code project session (`~/.claude/projects/<cwd-slug>/<uuid>.jsonl`) with a valid parent-uuid chain, tagged `[Codex]`. |

Only the **conversation text** (plus tool activity as readable blocks) is
carried across — native tool objects differ between apps and are intentionally
not reconstructed.

> ⚠️ Formats were reverse-engineered from real session files (July 2026,
> Claude Code 2.x / Codex 0.14x). App updates may change them — open an issue
> if a conversion breaks. The Gemini CLI reader is experimental.

## Security

Backups — and the `profiles/` folder used by user switching — contain **login
tokens** (`.codex/auth.json`, `.claude.json`). Keep them on a trusted drive,
enable token encryption for backups, and never commit `backup_*` or `profiles/`
(the shipped `.gitignore` blocks both).

## Development

```bash
pip install ".[dev]"
python -m pytest -q
```

## License

MIT — fork away. © 2026 Mo-mac67
