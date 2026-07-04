# -*- coding: utf-8 -*-
r"""
claude_tool.py — Claude Code + Codex all-in-one manager
=======================================================
Backup, restore, migrate, and convert your AI-coding chat history between
Anthropic Claude Code and OpenAI Codex — portable across machines & accounts.

Run:             python claude_tool.py            (interactive menu)
Non-interactive: python claude_tool.py backup

Menu: backup now / restore any version / install software / convert chats
      Claude<->Codex so they appear in each app's projects & chats.
Everything is non-destructive: only NEW files are written, nothing deleted.

Author: Mo Bamzadeh — https://github.com/Mo-mac67
License: MIT
"""
import json, os, re, shutil, subprocess, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

HOME        = Path.home()
SCRIPT_DIR  = Path(__file__).resolve().parent
BACKUP_ROOT = SCRIPT_DIR                     # backups live next to this script
CLAUDE_DIR  = HOME / ".claude"
CODEX_DIR   = HOME / ".codex"
CRED_FILES  = [".codex/auth.json", ".codex/cap_sid", ".codex/installation_id",
               ".claude.json", ".claude.json.backup"]

def ts_now():   return datetime.now().strftime("%Y-%m-%d_%H%M%S")
def iso_now():  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def uuid7():
    """time-ordered uuid (v7) like Codex uses"""
    b = bytearray(int(time.time() * 1000).to_bytes(6, "big") + os.urandom(10))
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

def copytree(src, dst):
    if os.name == "nt":
        subprocess.run(["robocopy", str(src), str(dst), "/E", "/R:1", "/W:1", "/XJ",
                        "/NFL", "/NDL", "/NP", "/NJH", "/NJS"], capture_output=True)
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=False)

def ask(prompt, default=""):
    try:
        v = input(prompt).strip()
        return v if v else default
    except EOFError:
        return default

# ---------------------------------------------------------------- backup ----
def do_backup():
    dest = BACKUP_ROOT / f"backup_{ts_now()}"
    dest.mkdir(parents=True, exist_ok=True)
    print(f"  -> {dest}")
    if CLAUDE_DIR.exists(): copytree(CLAUDE_DIR, dest / ".claude")
    if CODEX_DIR.exists():  copytree(CODEX_DIR,  dest / ".codex")
    for f in (".claude.json", ".claude.json.backup"):
        if (HOME / f).exists(): shutil.copy2(HOME / f, dest / f)
    for helper in ("RESTORE.ps1", "claude_tool.py"):
        if (BACKUP_ROOT / helper).exists():
            shutil.copy2(BACKUP_ROOT / helper, dest / helper)
    n = sum(1 for _ in dest.rglob("*") if _.is_file())
    mb = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) / 1e6
    print(f"  DONE: {n} files, {mb:.0f} MB")

# --------------------------------------------------------------- restore ----
def list_backups():
    pats = ("backup_", "claude_", "codex_")
    return sorted([d for d in BACKUP_ROOT.iterdir()
                   if d.is_dir() and d.name.startswith(pats)], reverse=True)

def do_restore():
    backups = list_backups()
    if not backups:
        print("  No backups found. | بک‌آپی پیدا نشد."); return
    print("\n  Available versions | نسخه‌های موجود:")
    for i, b in enumerate(backups, 1):
        mb = sum(f.stat().st_size for f in b.rglob("*") if f.is_file()) / 1e6
        print(f"   {i:2}) {b.name}   ({mb:.0f} MB)")
    pick = ask("  Which version? (number) | کدوم نسخه؟ : ")
    if not pick.isdigit() or not (1 <= int(pick) <= len(backups)):
        print("  Cancelled. | لغو شد."); return
    src = backups[int(pick) - 1]
    full = ask("  Restore original account login too? y = full clone / "
               "Enter = chats only, keep current login\n"
               "  لاگین اکانت اصلی هم برگرده؟ (y = کلون کامل / Enter = فقط چت‌ها): ").lower() == "y"

    saved = {}
    if not full:
        for rel in CRED_FILES:
            p = HOME / rel
            if p.exists(): saved[rel] = p.read_bytes()

    if (src / ".claude").exists(): print("  -> .claude ..."); copytree(src / ".claude", CLAUDE_DIR)
    if (src / ".codex").exists():  print("  -> .codex ...");  copytree(src / ".codex",  CODEX_DIR)
    for f in (".claude.json", ".claude.json.backup"):
        if (src / f).exists(): shutil.copy2(src / f, HOME / f)

    if not full:
        for rel, data in saved.items():
            p = HOME / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        print("  Current login kept; chats/history restored. | لاگین فعلی حفظ شد؛ چت‌ها برگشتن.")
    else:
        print("  Full clone done (incl. original login). | کلون کامل انجام شد.")
    print("  Restart Claude Code / Codex. | اپ‌ها رو ببند و باز کن.")

# -------------------------------------------------------------- software ----
def which(x): return shutil.which(x) is not None

def do_software():
    print("\n  Software status | وضعیت نرم‌افزارها:")
    for exe, name in [("node", "Node.js"), ("npm", "npm"), ("claude", "Claude Code"),
                      ("codex", "Codex CLI"), ("winget", "winget"), ("git", "Git")]:
        print(f"   {'[OK]      ' if which(exe) else '[missing] '}{name}")
    if not which("node") and os.name == "nt":
        if ask("  Install Node.js via winget? | نصب Node.js؟ (y/n): ").lower() == "y":
            subprocess.run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                            "--accept-source-agreements", "--accept-package-agreements"])
    if not which("claude"):
        if ask("  Install Claude Code? | نصب Claude Code؟ (y/n): ").lower() == "y":
            subprocess.run(["npm", "install", "-g", "@anthropic-ai/claude-code"], shell=(os.name == "nt"))
    if not which("codex"):
        if ask("  Install Codex CLI? | نصب Codex CLI؟ (y/n): ").lower() == "y":
            subprocess.run(["npm", "install", "-g", "@openai/codex"], shell=(os.name == "nt"))
    print("  Done. Desktop apps: install from official sites. | تمام.")

# --------------------------------------------- chat format helpers ----------
def claude_slug(cwd):  # C:\Users\x\Desktop -> C--Users-x-Desktop  (verified)
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)

def claude_extract(fp):
    """[(role, text, ts)] from a Claude Code session jsonl"""
    out, cwd = [], None
    for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
        try: o = json.loads(line)
        except Exception: continue
        if o.get("isSidechain") or o.get("isMeta"): continue
        cwd = cwd or o.get("cwd")
        t = o.get("type")
        if t not in ("user", "assistant"): continue
        m = o.get("message") or {}
        c = m.get("content")
        if isinstance(c, str): txt = c
        elif isinstance(c, list):
            txt = "\n".join(b.get("text", "") for b in c
                            if isinstance(b, dict) and b.get("type") == "text")
        else: continue
        txt = txt.strip()
        if not txt or txt.startswith("<"): continue   # skip system-reminders etc.
        out.append((("user" if t == "user" else "assistant"), txt,
                    o.get("timestamp") or iso_now()))
    return out, (cwd or str(HOME))

def codex_extract(fp):
    """[(role, text, ts)] from a Codex rollout jsonl"""
    out, cwd, started = [], None, None
    for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
        try: o = json.loads(line)
        except Exception: continue
        p = o.get("payload") or {}
        if o.get("type") == "session_meta":
            cwd, started = p.get("cwd"), p.get("timestamp"); continue
        if o.get("type") != "response_item" or p.get("type") != "message": continue
        role = p.get("role")
        txt = "\n".join(b.get("text", "") for b in (p.get("content") or [])
                        if isinstance(b, dict) and b.get("type") in ("input_text", "output_text"))
        txt = txt.strip()
        if txt and role in ("user", "assistant"):
            out.append((role, txt, o.get("timestamp") or iso_now()))
    return out, (cwd or str(HOME)), started

# --------------------------------------------- Claude -> Codex --------------
def c2x_one(fp):
    msgs, cwd = claude_extract(fp)
    if not msgs:
        print(f"   skipped (no text messages): {fp.name}"); return False
    sid, now = uuid7(), datetime.now()
    day_dir = CODEX_DIR / "sessions" / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    out = day_dir / f"rollout-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{sid}.jsonl"
    title = ("[Claude] " + msgs[0][1].replace("\n", " ")[:48]).strip()

    L = []
    L.append({"timestamp": iso_now(), "type": "session_meta", "payload": {
        "session_id": sid, "id": sid, "timestamp": iso_now(), "cwd": cwd,
        "originator": "Codex Desktop", "cli_version": "0.142.5", "source": "vscode",
        "model_provider": "openai",
        "base_instructions": {"text": "Imported conversation from Claude Code."},
        "multi_agent_version": "v1"}})
    L.append({"timestamp": iso_now(), "type": "event_msg", "payload": {
        "type": "task_started", "turn_id": "external-import-turn-1",
        "started_at": int(time.time()), "model_context_window": None,
        "collaboration_mode_kind": "default"}})
    for role, txt, ts in msgs:
        if role == "user":
            L.append({"timestamp": ts, "type": "event_msg", "payload": {
                "type": "user_message", "message": txt, "local_images": [], "text_elements": []}})
            L.append({"timestamp": ts, "type": "response_item", "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": txt}]}})
        else:
            L.append({"timestamp": ts, "type": "event_msg", "payload": {
                "type": "agent_message", "message": txt, "phase": None, "memory_citation": None}})
            L.append({"timestamp": ts, "type": "response_item", "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": txt}]}})
    out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in L) + "\n", encoding="utf-8")
    with (CODEX_DIR / "session_index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": sid, "thread_name": title,
                            "updated_at": iso_now()}, ensure_ascii=False) + "\n")
    print(f"   [OK] {title}  ({len(msgs)} messages)")
    return True

# --------------------------------------------- Codex -> Claude --------------
def x2c_one(fp):
    msgs, cwd, _ = codex_extract(fp)
    if not msgs:
        print(f"   skipped (no text messages): {fp.name}"); return False
    sid = str(uuid.uuid4())
    proj = CLAUDE_DIR / "projects" / claude_slug(cwd)
    proj.mkdir(parents=True, exist_ok=True)
    out, L, prev = proj / f"{sid}.jsonl", [], None
    base = {"isSidechain": False, "userType": "external", "cwd": cwd,
            "sessionId": sid, "version": "2.1.170", "gitBranch": ""}
    for role, txt, ts in msgs:
        u = str(uuid.uuid4())
        if role == "user":
            L.append({**base, "parentUuid": prev, "type": "user",
                      "message": {"role": "user", "content": "[Codex] " + txt if not prev else txt},
                      "uuid": u, "timestamp": ts})
        else:
            L.append({**base, "parentUuid": prev, "type": "assistant",
                      "message": {"id": "msg_import_" + u[:12], "type": "message",
                                  "role": "assistant", "model": "codex-import",
                                  "content": [{"type": "text", "text": txt}],
                                  "stop_reason": "end_turn", "stop_sequence": None,
                                  "usage": {"input_tokens": 0, "output_tokens": 0,
                                            "cache_creation_input_tokens": 0,
                                            "cache_read_input_tokens": 0}},
                      "requestId": "req_import", "uuid": u, "timestamp": ts})
        prev = u
    out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in L) + "\n", encoding="utf-8")
    print(f"   [OK] -> {out.parent.name}{os.sep}{out.name}  ({len(msgs)} messages)")
    return True

# --------------------------------------------- pickers ----------------------
def pick_and_run(items, label_fn, action, what):
    if not items:
        print("  Nothing found. | چیزی پیدا نشد."); return
    print(f"\n  {what}:")
    for i, it in enumerate(items, 1):
        print(f"   {i:3}) {label_fn(it)}")
    sel = ask("  Numbers (e.g. 1,3) or all | شماره‌ها یا all: ")
    if not sel: print("  Cancelled. | لغو شد."); return
    idx = range(len(items)) if sel.lower() == "all" else \
          [int(x) - 1 for x in re.findall(r"\d+", sel) if 0 < int(x) <= len(items)]
    ok = sum(1 for i in idx if action(items[i]))
    print(f"  {ok} converted. Restart the target app to see them. | "
          f"{ok} مورد تبدیل شد؛ اپ مقصد رو ببند و باز کن.")

def claude_sessions():
    root = CLAUDE_DIR / "projects"
    if not root.exists(): return []
    return sorted(root.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

def codex_sessions():
    root = CODEX_DIR / "sessions"
    if not root.exists(): return []
    return sorted(root.rglob("rollout-*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

def claude_label(f):
    first = ""
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[:25]:
            o = json.loads(line)
            if o.get("type") == "user" and not o.get("isSidechain"):
                c = o.get("message", {}).get("content")
                first = c if isinstance(c, str) else next(
                    (b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"), "")
                if first and not first.startswith("<"): break
                first = ""
    except Exception: pass
    d = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
    return f"{d}  [{f.parent.name[:28]}]  {first.replace(chr(10),' ')[:55]}"

def codex_label(f):
    first = ""
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[:25]:
            o = json.loads(line)
            p = o.get("payload") or {}
            if o.get("type") == "event_msg" and p.get("type") == "user_message":
                first = p.get("message", ""); break
    except Exception: pass
    d = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
    return f"{d}  {first.replace(chr(10),' ')[:70]}"

# --------------------------------------------- menu -------------------------
MENU = """
==========================================================
   Claude + Codex Toolkit
==========================================================
  1) Full backup now (new timestamp)      | بک‌آپ کامل الان
  2) Restore a version (you pick)         | بازگردانی نسخه
  3) Check/install software               | بررسی/نصب نرم‌افزارها
  4) Convert chats: Claude Code -> Codex  | تبدیل چت کلاد به کدکس
  5) Convert chats: Codex -> Claude Code  | تبدیل چت کدکس به کلاد
  0) Exit                                 | خروج
"""

def main():
    if len(sys.argv) > 1:            # non-interactive: python claude_tool.py backup
        if sys.argv[1].lower() == "backup":
            do_backup(); return
    while True:
        print(MENU)
        ch = ask("  Choice | انتخاب: ")
        if   ch == "1": do_backup()
        elif ch == "2": do_restore()
        elif ch == "3": do_software()
        elif ch == "4": pick_and_run(claude_sessions(), claude_label, c2x_one,
                                     "Claude Code chats (newest first) | چت‌های Claude Code")
        elif ch == "5": pick_and_run(codex_sessions(), codex_label, x2c_one,
                                     "Codex chats (newest first) | چت‌های Codex")
        elif ch == "0": break

if __name__ == "__main__":
    main()
