# Changelog

## 0.2.0 — 2026-07-04

Big feature release (Waves 1–3).

### Added
- **Compression** — backups can be stored as a single `.zip` (`compress` setting).
- **Retention** — optional `keep_last` prunes old backups automatically (off by default).
- **Integrity manifests** — every backup gets a `MANIFEST.sha256`; `verify` command / menu re-checks it.
- **Token encryption** — login files (`.codex/auth.json`, `.claude.json`, …) can be encrypted
  in backups with a password (Fernet + PBKDF2). Password via `CCT_BACKUP_PASSWORD` env or prompt.
- **Cloud upload** — push a backup to Google Drive / OneDrive / S3 via `rclone`.
- **Tool-call preservation** — conversions now embed tool-use/tool-result activity as readable
  fenced text (toggle with `include_tools`).
- **Markdown / HTML export** — export any Claude or Codex session to a shareable file.
- **Full-text search** — search all chats (and optionally all backups) across both formats.
- **Experimental Gemini CLI reader** — export/convert Gemini sessions (best-effort).
- **Settings** — persisted in `cct_config.json`.
- **GUI** — `claude_tool_gui.py` (Tkinter) with tabs for every action.
- **Packaging** — `pyproject.toml`, `pip install .`, console scripts `cct` and `cct-gui`.
- **CI** — GitHub Actions runs the pytest suite on Linux + Windows, Python 3.9/3.11/3.12.
- **Tests** — `tests/test_toolkit.py` covering extraction, conversion round-trips,
  manifests, compression, retention, export, search and encryption.

## 0.1.0 — 2026-07-04

Initial release: timestamped non-destructive backup, portable account-safe restore,
software bootstrap, and bidirectional Claude Code ↔ Codex chat conversion.
