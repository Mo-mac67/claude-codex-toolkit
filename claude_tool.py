# -*- coding: utf-8 -*-
r"""
claude_tool.py — Claude Code + Codex all-in-one toolkit
=======================================================
Backup, restore, migrate, convert, export and search your AI-coding chat
history across Anthropic Claude Code and OpenAI Codex. Portable across
machines and accounts. Self-contained single file, no required dependencies.

Interactive:      python claude_tool.py
Non-interactive:  python claude_tool.py backup
                  python claude_tool.py verify <backup>
                  python claude_tool.py search "<text>"
                  python claude_tool.py export claude|codex
                  python claude_tool.py migrate
                  python claude_tool.py switch [codex|claude] [profile]
                  python claude_tool.py switch codex --save [name]
                  python claude_tool.py switch --list

Everything is non-destructive: the tool only writes NEW files; it never
deletes your chats. (Retention pruning of old *backups* is opt-in.)

Author: Mo Bamzadeh — https://github.com/Mo-mac67
License: MIT
"""
import argparse, base64, getpass, hashlib, html, json, os, re, shutil
import subprocess, sys, time, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

# ------------------------------------------------------------------ paths ---
HOME        = Path.home()
SCRIPT_DIR  = Path(__file__).resolve().parent
BACKUP_ROOT = SCRIPT_DIR                       # backups live next to this script
CLAUDE_DIR  = HOME / ".claude"
CODEX_DIR   = HOME / ".codex"
GEMINI_DIR  = HOME / ".gemini"
CRED_FILES  = [".codex/auth.json", ".codex/cap_sid", ".codex/installation_id",
               ".claude.json", ".claude.json.backup"]
CONFIG_PATH = BACKUP_ROOT / "cct_config.json"
CRYPTO_META = "cct_crypto.json"
MANIFEST    = "MANIFEST.sha256"
DEFAULTS    = {"compress": False, "keep_last": 0, "encrypt": False,
               "cloud_remote": "", "include_tools": True}
TOOL_TRUNC  = 4000                              # max chars kept per tool block

# ---------------------------------------------------------------- helpers ---
def ts_now():  return datetime.now().strftime("%Y-%m-%d_%H%M%S")
def iso_now(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def uuid7():
    """time-ordered uuid (v7) like Codex uses"""
    b = bytearray(int(time.time() * 1000).to_bytes(6, "big") + os.urandom(10))
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024: return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.0f} PB"

def sha256_file(fp, buf=1 << 20):
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        while (chunk := f.read(buf)):
            h.update(chunk)
    return h.hexdigest()

def copytree(src, dst):
    src, dst = Path(src), Path(dst)
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

def dir_size(d):
    return sum(f.stat().st_size for f in Path(d).rglob("*") if f.is_file())

def is_noise(txt):
    """system-reminders / command wrappers that aren't real conversation text"""
    t = txt.lstrip()
    return t.startswith(("<system-reminder", "<local-command", "<command-name",
                         "<command-message", "<command-args", "Caveat:"))

# ----------------------------------------------------------------- config ---
def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg

def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

# --------------------------------------------------------------- crypto -----
def _load_cryptography():
    try:
        from cryptography.fernet import Fernet                       # noqa
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa
        from cryptography.hazmat.primitives import hashes            # noqa
        return Fernet, PBKDF2HMAC, hashes
    except Exception:
        print("  'cryptography' not installed. Install with: pip install cryptography")
        return None

def _derive_key(password, salt, iters=200_000):
    Fernet, PBKDF2HMAC, hashes = _load_cryptography()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))

def get_backup_password(confirm=False):
    pw = os.environ.get("CCT_BACKUP_PASSWORD")
    if pw:
        return pw
    if not sys.stdin.isatty():
        return None
    pw = getpass.getpass("  Encryption password: ")
    if confirm and pw != getpass.getpass("  Confirm password: "):
        print("  Passwords do not match."); return None
    return pw or None

def encrypt_creds(dest_dir, password):
    lib = _load_cryptography()
    if not lib or not password:
        print("  Skipped encryption (no cryptography lib or no password)."); return False
    Fernet = lib[0]
    salt = os.urandom(16)
    fkey = Fernet(_derive_key(password, salt))
    done = []
    for rel in CRED_FILES:
        p = Path(dest_dir) / rel
        if p.exists():
            enc = fkey.encrypt(p.read_bytes())
            p.with_suffix(p.suffix + ".enc").write_bytes(enc)
            p.unlink()
            done.append(rel)
    if done:
        (Path(dest_dir) / CRYPTO_META).write_text(json.dumps(
            {"salt": base64.b64encode(salt).decode(), "iters": 200_000, "files": done},
            indent=2), encoding="utf-8")
        print(f"  Encrypted {len(done)} login file(s).")
    return True

def decrypt_creds(src_dir, password):
    meta_p = Path(src_dir) / CRYPTO_META
    if not meta_p.exists():
        return True   # nothing encrypted
    lib = _load_cryptography()
    if not lib:
        return False
    if not password:
        password = get_backup_password()
    if not password:
        print("  This backup's login files are encrypted; password required."); return False
    Fernet = lib[0]
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    fkey = Fernet(_derive_key(password, base64.b64decode(meta["salt"]), meta.get("iters", 200_000)))
    try:
        for rel in meta["files"]:
            enc = Path(src_dir) / (rel + ".enc")
            if enc.exists():
                (Path(src_dir) / rel).write_bytes(fkey.decrypt(enc.read_bytes()))
    except Exception as e:
        print(f"  Decryption failed (wrong password?): {e}"); return False
    print("  Login files decrypted.")
    return True

# ---------------------------------------------------------------- manifest --
def write_manifest(d):
    d = Path(d)
    lines = []
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.name != MANIFEST:
            lines.append(f"{sha256_file(f)} *{f.relative_to(d).as_posix()}")
    (d / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)

def verify_manifest(d):
    d = Path(d)
    mp = d / MANIFEST
    if not mp.exists():
        print("  No MANIFEST.sha256 in this backup."); return False
    expected = {}
    for line in mp.read_text(encoding="utf-8").splitlines():
        if " *" in line:
            h, rel = line.split(" *", 1); expected[rel] = h
    changed = missing = ok = 0
    for rel, h in expected.items():
        f = d / rel
        if not f.exists(): missing += 1; print(f"   MISSING  {rel}")
        elif sha256_file(f) != h: changed += 1; print(f"   CHANGED  {rel}")
        else: ok += 1
    present = {f.relative_to(d).as_posix() for f in d.rglob("*")
               if f.is_file() and f.name != MANIFEST}
    extra = present - set(expected)
    for rel in sorted(extra): print(f"   EXTRA    {rel}")
    good = (changed == 0 and missing == 0)
    print(f"  Verify: {ok} ok, {changed} changed, {missing} missing, {len(extra)} extra "
          f"-> {'INTACT' if good else 'PROBLEMS'}")
    return good

# --------------------------------------------------------------- compress ---
def zip_dir(d, delete_after=False):
    d = Path(d)
    zpath = d.with_suffix(".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in d.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(d.parent).as_posix())
    if delete_after:
        shutil.rmtree(d, ignore_errors=True)
    print(f"  Compressed -> {zpath.name} ({human(zpath.stat().st_size)})")
    return zpath

# ---------------------------------------------------------------- backup ----
def apply_retention(keep_last):
    if not keep_last or keep_last <= 0:
        return
    snaps = sorted([p for p in BACKUP_ROOT.iterdir()
                    if p.name.startswith("backup_")], key=lambda p: p.name, reverse=True)
    for old in snaps[keep_last:]:
        if old.is_dir(): shutil.rmtree(old, ignore_errors=True)
        else: old.unlink(missing_ok=True)
        print(f"  Retention: removed {old.name}")

def do_backup(cfg=None):
    cfg = cfg or load_config()
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

    if cfg.get("encrypt"):
        encrypt_creds(dest, get_backup_password())

    n = write_manifest(dest)
    print(f"  Manifest: {n} files hashed.")
    print(f"  DONE: {n} files, {human(dir_size(dest))}")

    if cfg.get("compress"):
        zpath = zip_dir(dest, delete_after=True)
        dest = zpath
    if cfg.get("cloud_remote"):
        cloud_upload(dest, cfg["cloud_remote"])
    apply_retention(cfg.get("keep_last", 0))
    return dest

# --------------------------------------------------------------- restore ----
def list_snapshots():
    items = []
    for p in BACKUP_ROOT.iterdir():
        if p.name.startswith(("backup_", "claude_", "codex_")):
            if p.is_dir() or p.suffix == ".zip":
                items.append(p)
    return sorted(items, key=lambda p: p.name, reverse=True)

def _restore_from_dir(src, full):
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
        print("  Current login kept; chats/history restored. | لاگین فعلی حفظ شد.")
    else:
        print("  Full clone done (incl. original login). | کلون کامل انجام شد.")

def do_restore():
    snaps = list_snapshots()
    if not snaps:
        print("  No backups found. | بک‌آپی پیدا نشد."); return
    print("\n  Available versions | نسخه‌های موجود:")
    for i, b in enumerate(snaps, 1):
        tag = "zip" if b.suffix == ".zip" else "dir"
        size = b.stat().st_size if b.suffix == ".zip" else dir_size(b)
        print(f"   {i:2}) [{tag}] {b.name}   ({human(size)})")
    pick = ask("  Which version? (number) | کدوم نسخه؟ : ")
    if not pick.isdigit() or not (1 <= int(pick) <= len(snaps)):
        print("  Cancelled. | لغو شد."); return
    chosen = snaps[int(pick) - 1]
    full = ask("  Restore original account login too? y = full clone / "
               "Enter = chats only, keep current login\n"
               "  لاگین اکانت اصلی هم برگرده؟ (y = کلون کامل / Enter = فقط چت‌ها): ").lower() == "y"

    tmp = None
    src = chosen
    if chosen.suffix == ".zip":
        tmp = BACKUP_ROOT / f".extract_{ts_now()}"
        with zipfile.ZipFile(chosen) as z: z.extractall(tmp)
        inner = [p for p in tmp.iterdir() if p.is_dir()]
        src = inner[0] if len(inner) == 1 else tmp
    if (src / CRYPTO_META).exists():
        if not decrypt_creds(src, get_backup_password()):
            print("  Continuing without login files.");
    _restore_from_dir(src, full)
    if tmp: shutil.rmtree(tmp, ignore_errors=True)
    print("  Restart Claude Code / Codex. | اپ‌ها رو ببند و باز کن.")

# ------------------------------------------------------------------ cloud ---
def have_rclone(): return shutil.which("rclone") is not None

def cloud_upload(path, remote):
    if not have_rclone():
        print("  rclone not installed. Get it at https://rclone.org/downloads/ and run "
              "`rclone config` to add a remote (Drive/OneDrive/S3)."); return False
    path = Path(path)
    dst = f"{remote}:cct-backups/{path.name}"
    print(f"  Uploading to {dst} ...")
    if path.is_dir():
        r = subprocess.run(["rclone", "copy", str(path), dst, "-P"])
    else:
        r = subprocess.run(["rclone", "copyto", str(path), dst, "-P"])
    ok = (r.returncode == 0)
    print("  Upload complete." if ok else "  Upload failed.")
    return ok

# ------------------------------------------- profiles / account switching ---
# A "profile" is a saved copy of ONE app's login files, so you can flip
# between accounts in seconds. Chats are never touched — they live outside
# the credential files and stay on disk whichever account is active.
APP_CREDS = {
    "codex":  [".codex/auth.json", ".codex/cap_sid", ".codex/installation_id"],
    "claude": [".claude.json", ".claude.json.backup"],
}
APP_NAMES = {"codex": "Codex", "claude": "Claude Code"}

def _jwt_claims(tok):
    try:
        p = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    except Exception:
        return {}

def account_label(app, base=None):
    """Best-effort account e-mail from an app's live (or backed-up) login files.
    Returns None when not logged in / files absent."""
    base = Path(base) if base else HOME
    try:
        if app == "codex":
            d = json.loads((base / ".codex" / "auth.json").read_text(encoding="utf-8"))
            email = _jwt_claims((d.get("tokens") or {}).get("id_token", "")).get("email")
            return email or ("API key" if d.get("OPENAI_API_KEY") else "unknown")
        d = json.loads((base / ".claude.json").read_text(encoding="utf-8"))
        return (d.get("oauthAccount") or {}).get("emailAddress") or "unknown"
    except Exception:
        return None

def _profile_root(app): return BACKUP_ROOT / "profiles" / app

def profile_list(app):
    root = _profile_root(app)
    return sorted([p for p in root.iterdir() if p.is_dir()]) if root.exists() else []

def profile_account(pdir):
    try:
        return json.loads((Path(pdir) / "profile.json").read_text(encoding="utf-8")).get("account")
    except Exception:
        return None

def profile_save(app, name=None):
    """Copy the app's live login files into profiles/<app>/<name>."""
    label = account_label(app)
    if label is None:
        print(f"  {APP_NAMES[app]}: not logged in — nothing to save. | لاگین نیستی.")
        return None
    name = name or re.sub(r"[^A-Za-z0-9._@-]+", "_", label)
    dest = _profile_root(app) / name
    n = 0
    for rel in APP_CREDS[app]:
        src = HOME / rel
        if src.exists():
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out); n += 1
    if not n:
        print(f"  {APP_NAMES[app]}: no login files found."); return None
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "profile.json").write_text(json.dumps(
        {"app": app, "account": label, "saved": iso_now()}, indent=2), encoding="utf-8")
    print(f"  Profile saved: {APP_NAMES[app]} / {name}  ({label}) | پروفایل ذخیره شد.")
    return dest

def profile_switch(app, name):
    """Swap the app's live login for a saved profile. The login that is being
    replaced is auto-saved first, so switching is always reversible."""
    src = _profile_root(app) / name
    if not (src / "profile.json").exists() and \
       not any((src / rel).exists() for rel in APP_CREDS[app]):
        print(f"  Profile not found: {name} | پروفایل پیدا نشد."); return False
    if account_label(app) is not None:
        profile_save(app)                              # keep a way back
    for rel in APP_CREDS[app]:                         # true swap: clear, then copy
        live = HOME / rel
        if live.exists(): live.unlink()
        f = src / rel
        if f.exists():
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, live)
    print(f"  {APP_NAMES[app]} -> '{name}'  ({account_label(app) or '?'}). "
          f"Restart the app. | سوییچ شد؛ برنامه رو ببند و باز کن.")
    return True

def profile_delete(app, name):
    d = _profile_root(app) / name
    if d.exists():
        shutil.rmtree(d); print(f"  Deleted profile {name}. | حذف شد."); return True
    print("  Profile not found. | پیدا نشد."); return False

# ------------------------------------------------------------- migrate ------
def migrate_status(apps):
    return {a: {"account": account_label(a), "n": len(ADAPTERS[a]["list"]())} for a in apps}

def migrate_prepare(apps, backup=True):
    """Wizard steps 1+2: safety backup + save current logins as profiles."""
    before = migrate_status(apps)
    for a in apps:
        print(f"  {APP_NAMES[a]:11}: {before[a]['account'] or 'not logged in'}"
              f"  ({before[a]['n']} sessions)")
    if backup:
        print("\n  Taking a full safety backup ... | بک‌آپ کامل ...")
        do_backup()
    for a in apps:
        if before[a]["account"]: profile_save(a)
    return before

def migrate_finish(apps, before):
    """Wizard last step: verify accounts changed and every chat survived,
    then save the new login as a profile too."""
    ok = True
    after = migrate_status(apps)
    for a in apps:
        o, n = before[a], after[a]
        print(f"\n  {APP_NAMES[a]}:")
        print(f"    account : {o['account'] or '—'}  ->  {n['account'] or '—'}")
        note = "[OK] all chats intact" if n["n"] >= o["n"] else "[!] FEWER sessions than before"
        print(f"    sessions: {o['n']} -> {n['n']}   {note}")
        if n["n"] < o["n"]: ok = False
        if not n["account"] or n["account"] == o["account"]:
            print("    [!] account unchanged — log into the NEW account, then verify again."
                  " | اکانت عوض نشده؛ اول با اکانت جدید وارد شو.")
            ok = False
        else:
            profile_save(a)                            # new login is switchable too
    return ok

def do_migrate():
    print("""
  ============== Migrate wizard | ویزارد تعویض اکانت ==============
  Change account WITHOUT losing chats. Chats live on disk, not in the
  account: we back everything up, keep your current login as a profile,
  you log into the new account, then we verify every chat survived.
  چت‌ها روی دیسک‌ان نه توی اکانت؛ بک‌آپ می‌گیریم، لاگین فعلی رو نگه
  می‌داریم، با اکانت جدید وارد می‌شی و آخرش سلامت چت‌ها چک می‌شه.""")
    ch = ask("\n  App | برنامه:  1) Codex  2) Claude Code  3) both [3]: ").strip()
    apps = {"1": ["codex"], "2": ["claude"]}.get(ch, ["codex", "claude"])
    print("\n  Step 1+2/4 — backup & save current login | بک‌آپ + ذخیره لاگین فعلی")
    before = migrate_prepare(apps)
    print("\n  Step 3/4 — log into the NEW account | با اکانت جدید وارد شو:")
    if "codex" in apps:
        print("    Codex      : codex logout   then   codex login")
        if ask("    Run those two commands here now? (y/n) | همینجا اجرا بشه؟ : ").lower() == "y":
            subprocess.run(["codex", "logout"], shell=(os.name == "nt"))
            subprocess.run(["codex", "login"],  shell=(os.name == "nt"))
    if "claude" in apps:
        print("    Claude Code: run `claude`, then /logout — it re-opens the login flow.")
    while True:
        if ask("\n  Enter = verify now / q = cancel | اینتر = بررسی، q = لغو: ").lower() == "q":
            print("  Cancelled. The wizard changed nothing. | لغو شد."); return
        print("\n  Step 4/4 — verify | بررسی نهایی")
        if migrate_finish(apps, before):
            print("\n  [DONE] Migration complete — old & new logins saved as profiles;")
            print("  switch anytime via 'Switch user'. | تمام شد؛ با «سوییچ یوزر» می‌تونی برگردی.")
            return
        if ask("  Verify again? (y = again / Enter = exit) | دوباره؟ : ").lower() != "y":
            return

# --------------------------------------------- chat format: shared model ----
# A conversation is a list of dicts: {"role","text","ts","kind"}  kind: text|tool
def _trunc(s):
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    return s if len(s) <= TOOL_TRUNC else s[:TOOL_TRUNC] + "\n... (truncated)"

def render_tool_use(name, inp):  return f"[tool-use: {name}]\n```\n{_trunc(inp)}\n```"
def render_tool_out(out):        return f"[tool-result]\n```\n{_trunc(out)}\n```"

def claude_slug(cwd):  # C:\Users\x\Desktop -> C--Users-x-Desktop  (verified)
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)

# ---- Claude Code ----
def claude_extract(fp, include_tools=True):
    msgs, cwd = [], None
    for line in Path(fp).read_text(encoding="utf-8", errors="replace").splitlines():
        try: o = json.loads(line)
        except Exception: continue
        if o.get("isSidechain") or o.get("isMeta"): continue
        cwd = cwd or o.get("cwd")
        t = o.get("type")
        if t not in ("user", "assistant"): continue
        m = o.get("message") or {}
        c = m.get("content")
        ts = o.get("timestamp") or iso_now()
        texts, tool_uses, tool_results = [], [], []
        if isinstance(c, str):
            texts.append(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                bt = b.get("type")
                if bt == "text":        texts.append(b.get("text", ""))
                elif bt == "tool_use":  tool_uses.append((b.get("name", "tool"), b.get("input", {})))
                elif bt == "tool_result":
                    rc = b.get("content", "")
                    if isinstance(rc, list):
                        rc = "\n".join(x.get("text", "") for x in rc if isinstance(x, dict))
                    tool_results.append(rc)
        body = "\n".join(x for x in texts if x).strip()
        if t == "user":
            if body and not is_noise(body):
                msgs.append({"role": "user", "text": body, "ts": ts, "kind": "text"})
            elif include_tools and tool_results and msgs and msgs[-1]["role"] == "assistant":
                for r in tool_results:
                    msgs.append({"role": "assistant", "text": render_tool_out(r), "ts": ts, "kind": "tool"})
        else:  # assistant
            if body:
                msgs.append({"role": "assistant", "text": body, "ts": ts, "kind": "text"})
            if include_tools:
                for name, inp in tool_uses:
                    msgs.append({"role": "assistant", "text": render_tool_use(name, inp), "ts": ts, "kind": "tool"})
    return msgs, {"cwd": cwd or str(HOME)}

def write_claude_session(msgs, cwd, tag="[Codex]"):
    sid = str(uuid.uuid4())
    proj = CLAUDE_DIR / "projects" / claude_slug(cwd)
    proj.mkdir(parents=True, exist_ok=True)
    out, L, prev, first = proj / f"{sid}.jsonl", [], None, True
    base = {"isSidechain": False, "userType": "external", "cwd": cwd,
            "sessionId": sid, "version": "2.1.170", "gitBranch": ""}
    for m in msgs:
        u = str(uuid.uuid4())
        text = m["text"]
        if m["role"] == "user":
            if first: text = f"{tag} {text}"
            L.append({**base, "parentUuid": prev, "type": "user",
                      "message": {"role": "user", "content": text}, "uuid": u, "timestamp": m["ts"]})
        else:
            L.append({**base, "parentUuid": prev, "type": "assistant",
                      "message": {"id": "msg_import_" + u[:12], "type": "message", "role": "assistant",
                                  "model": "imported", "content": [{"type": "text", "text": text}],
                                  "stop_reason": "end_turn", "stop_sequence": None,
                                  "usage": {"input_tokens": 0, "output_tokens": 0,
                                            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
                      "requestId": "req_import", "uuid": u, "timestamp": m["ts"]})
        prev = u; first = False
    out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in L) + "\n", encoding="utf-8")
    return out

# ---- Codex ----
def codex_extract(fp, include_tools=True):
    msgs, cwd = [], None
    for line in Path(fp).read_text(encoding="utf-8", errors="replace").splitlines():
        try: o = json.loads(line)
        except Exception: continue
        p = o.get("payload") or {}
        ts = o.get("timestamp") or iso_now()
        if o.get("type") == "session_meta":
            cwd = p.get("cwd"); continue
        if o.get("type") != "response_item": continue
        pt = p.get("type")
        if pt == "message":
            role = p.get("role")
            txt = "\n".join(b.get("text", "") for b in (p.get("content") or [])
                            if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")).strip()
            if txt and role in ("user", "assistant") and not is_noise(txt):
                msgs.append({"role": role, "text": txt, "ts": ts, "kind": "text"})
        elif include_tools and pt in ("function_call", "local_shell_call", "custom_tool_call"):
            name = p.get("name") or p.get("action") or pt
            args = p.get("arguments") or p.get("input") or p.get("command") or ""
            msgs.append({"role": "assistant", "text": render_tool_use(name, args), "ts": ts, "kind": "tool"})
        elif include_tools and pt in ("function_call_output", "custom_tool_call_output"):
            out = p.get("output")
            if isinstance(out, dict): out = out.get("content", out)
            msgs.append({"role": "assistant", "text": render_tool_out(out), "ts": ts, "kind": "tool"})
    return msgs, {"cwd": cwd or str(HOME)}

def write_codex_session(msgs, cwd, tag="[Claude]"):
    sid, now = uuid7(), datetime.now()
    day = CODEX_DIR / "sessions" / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    day.mkdir(parents=True, exist_ok=True)
    out = day / f"rollout-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{sid}.jsonl"
    title = (f"{tag} " + next((m["text"] for m in msgs if m["role"] == "user"), "imported")
             ).replace("\n", " ")[:56].strip()
    L = [{"timestamp": iso_now(), "type": "session_meta", "payload": {
            "session_id": sid, "id": sid, "timestamp": iso_now(), "cwd": cwd,
            "originator": "Codex Desktop", "cli_version": "0.142.5", "source": "vscode",
            "model_provider": "openai",
            "base_instructions": {"text": "Imported conversation."}, "multi_agent_version": "v1"}},
         {"timestamp": iso_now(), "type": "event_msg", "payload": {
            "type": "task_started", "turn_id": "external-import-turn-1",
            "started_at": int(time.time()), "model_context_window": None,
            "collaboration_mode_kind": "default"}}]
    for m in msgs:
        if m["role"] == "user":
            L.append({"timestamp": m["ts"], "type": "event_msg", "payload": {
                "type": "user_message", "message": m["text"], "local_images": [], "text_elements": []}})
            L.append({"timestamp": m["ts"], "type": "response_item", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": m["text"]}]}})
        else:
            L.append({"timestamp": m["ts"], "type": "event_msg", "payload": {
                "type": "agent_message", "message": m["text"], "phase": None, "memory_citation": None}})
            L.append({"timestamp": m["ts"], "type": "response_item", "payload": {
                "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": m["text"]}]}})
    out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in L) + "\n", encoding="utf-8")
    with (CODEX_DIR / "session_index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": sid, "thread_name": title, "updated_at": iso_now()},
                           ensure_ascii=False) + "\n")
    return out, title

# ---- Gemini CLI (experimental, read/export only) ----
def gemini_extract(fp, include_tools=True):
    msgs = []
    try:
        data = json.loads(Path(fp).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return msgs, {"cwd": str(HOME)}
    seq = data if isinstance(data, list) else data.get("messages") or data.get("history") or []
    for o in seq:
        if not isinstance(o, dict): continue
        role = o.get("role") or o.get("type") or ""
        role = "user" if str(role).lower() in ("user", "human") else "assistant"
        txt = o.get("text") or o.get("content") or o.get("message") or ""
        if isinstance(txt, list):
            txt = "\n".join(x.get("text", "") for x in txt if isinstance(x, dict))
        txt = (txt or "").strip()
        if txt and not is_noise(txt):
            msgs.append({"role": role, "text": txt, "ts": o.get("timestamp") or iso_now(), "kind": "text"})
    return msgs, {"cwd": str(HOME)}

def gemini_sessions():
    root = GEMINI_DIR / "tmp"
    if not root.exists(): return []
    return sorted(root.rglob("logs.json"), key=lambda f: f.stat().st_mtime, reverse=True)

# --------------------------------------------- session listing / labels -----
def claude_sessions():
    root = CLAUDE_DIR / "projects"
    return sorted(root.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True) if root.exists() else []

def codex_sessions():
    root = CODEX_DIR / "sessions"
    return sorted(root.rglob("rollout-*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True) if root.exists() else []

def _first_user(msgs): return next((m["text"] for m in msgs if m["role"] == "user"), "")

def claude_label(f):
    try: msgs, _ = claude_extract(f, include_tools=False)
    except Exception: msgs = []
    d = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
    return f"{d}  [{f.parent.name[:26]}]  {_first_user(msgs).replace(chr(10),' ')[:52]}"

def codex_label(f):
    try: msgs, _ = codex_extract(f, include_tools=False)
    except Exception: msgs = []
    d = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
    return f"{d}  {_first_user(msgs).replace(chr(10),' ')[:66]}"

def gemini_label(f):
    d = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
    return f"{d}  [gemini] {f.parent.name[:40]}"

ADAPTERS = {
    "claude": {"name": "Claude Code", "list": claude_sessions, "extract": claude_extract,
               "label": claude_label, "write": write_claude_session},
    "codex":  {"name": "Codex", "list": codex_sessions, "extract": codex_extract,
               "label": codex_label, "write": write_codex_session},
    "gemini": {"name": "Gemini CLI (experimental)", "list": gemini_sessions,
               "extract": gemini_extract, "label": gemini_label, "write": None},
}

# --------------------------------------------------------------- convert ----
def convert_file(src_key, dst_key, fp, include_tools=True):
    src, dst = ADAPTERS[src_key], ADAPTERS[dst_key]
    if not dst["write"]:
        print(f"   cannot write to {dst['name']}"); return False
    msgs, meta = src["extract"](fp, include_tools=include_tools)
    if not msgs:
        print(f"   skipped (no text messages): {Path(fp).name}"); return False
    tag = f"[{src['name'].split()[0]}]"
    if dst_key == "codex":
        out, title = dst["write"](msgs, meta["cwd"], tag=tag)
        print(f"   [OK] {title}  ({len(msgs)} msgs)")
    else:
        out = dst["write"](msgs, meta["cwd"], tag=tag)
        print(f"   [OK] -> {out.parent.name}{os.sep}{out.name}  ({len(msgs)} msgs)")
    return True

# ---------------------------------------------------------------- export ----
def export_file(src_key, fp, fmt="md"):
    src = ADAPTERS[src_key]
    msgs, meta = src["extract"](fp, include_tools=True)
    if not msgs:
        print(f"   skipped (empty): {Path(fp).name}"); return None
    outdir = BACKUP_ROOT / "exports"; outdir.mkdir(exist_ok=True)
    stem = Path(fp).stem
    title = _first_user(msgs).replace("\n", " ")[:70] or stem
    if fmt == "html":
        parts = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>",
                 "<style>body{font-family:system-ui,Segoe UI,Arial;max-width:820px;margin:2rem auto;"
                 "padding:0 1rem;line-height:1.5}.u{background:#eef}.a{background:#f6f6f6}"
                 "section{border-radius:8px;padding:.6rem 1rem;margin:.6rem 0}"
                 "h3{margin:.2rem 0;font-size:.85rem;color:#555}pre{white-space:pre-wrap;"
                 "background:#0d1117;color:#e6edf3;padding:.6rem;border-radius:6px;overflow:auto}</style>",
                 f"<h1>{html.escape(title)}</h1><p><em>{src['name']} · {meta['cwd']}</em></p>"]
        for m in msgs:
            who = "You" if m["role"] == "user" else "Assistant"
            body = html.escape(m["text"])
            body = re.sub(r"```(.*?)```", lambda x: "<pre>" + x.group(1) + "</pre>", body, flags=re.S)
            parts.append(f"<section class='{'u' if m['role']=='user' else 'a'}'>"
                         f"<h3>{who}</h3>{body.replace(chr(10),'<br>')}</section>")
        out = outdir / f"{stem}.html"; out.write_text("\n".join(parts), encoding="utf-8")
    else:
        lines = [f"# {title}", "", f"> {src['name']} · `{meta['cwd']}`", ""]
        for m in msgs:
            lines.append(f"### {'🧑 You' if m['role']=='user' else '🤖 Assistant'}")
            lines.append(""); lines.append(m["text"]); lines.append("")
        out = outdir / f"{stem}.md"; out.write_text("\n".join(lines), encoding="utf-8")
    print(f"   [OK] {out.name}")
    return out

# ---------------------------------------------------------------- search ----
def search_all(query, include_backups=False):
    if not query: return
    q = query.lower()
    hits = 0
    sources = [("claude", f) for f in claude_sessions()] + [("codex", f) for f in codex_sessions()]
    if include_backups:
        for snap in list_snapshots():
            if snap.is_dir():
                sources += [("claude", f) for f in (snap / ".claude" / "projects").glob("*/*.jsonl")]
                sources += [("codex", f) for f in (snap / ".codex" / "sessions").rglob("rollout-*.jsonl")]
    for key, fp in sources:
        try: msgs, meta = ADAPTERS[key]["extract"](fp, include_tools=False)
        except Exception: continue
        for m in msgs:
            if q in m["text"].lower():
                i = m["text"].lower().find(q)
                snip = m["text"][max(0, i - 40):i + 60].replace("\n", " ")
                print(f"  [{key}] {Path(fp).name}\n        …{snip}…")
                hits += 1
                break
    print(f"\n  {hits} session(s) matched '{query}'.")

# -------------------------------------------------------------- software ----
def which(x): return shutil.which(x) is not None

def do_software():
    print("\n  Software status | وضعیت نرم‌افزارها:")
    for exe, name in [("node", "Node.js"), ("npm", "npm"), ("claude", "Claude Code"),
                      ("codex", "Codex CLI"), ("git", "Git"), ("rclone", "rclone (cloud)"),
                      ("winget", "winget")]:
        print(f"   {'[OK]      ' if which(exe) else '[missing] '}{name}")
    if not which("node") and os.name == "nt":
        if ask("  Install Node.js via winget? (y/n): ").lower() == "y":
            subprocess.run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                            "--accept-source-agreements", "--accept-package-agreements"])
    if not which("claude") and ask("  Install Claude Code? (y/n): ").lower() == "y":
        subprocess.run(["npm", "install", "-g", "@anthropic-ai/claude-code"], shell=(os.name == "nt"))
    if not which("codex") and ask("  Install Codex CLI? (y/n): ").lower() == "y":
        subprocess.run(["npm", "install", "-g", "@openai/codex"], shell=(os.name == "nt"))
    print("  Done. | تمام.")

# --------------------------------------------------------------- settings ---
def _ask_bool(prompt, current):
    v = ask(prompt).strip().lower()
    if v in ("y", "yes"): return True
    if v in ("n", "no"):  return False
    return current   # blank = keep current

def do_settings():
    cfg = load_config()
    print("\n  Current settings | تنظیمات فعلی:")
    for k in DEFAULTS: print(f"   {k:14} = {cfg.get(k)}")
    print("  Enter = keep. | Enter = بدون تغییر")
    cfg["compress"]      = _ask_bool(f"  compress backups to zip? (y/n) [{cfg['compress']}]: ", cfg["compress"])
    kl = ask(f"  keep_last (0=keep all) [{cfg['keep_last']}]: ")
    if kl.isdigit(): cfg["keep_last"] = int(kl)
    cfg["encrypt"]       = _ask_bool(f"  encrypt login tokens in backups? (y/n) [{cfg['encrypt']}]: ", cfg["encrypt"])
    cfg["include_tools"] = _ask_bool(f"  keep tool activity in conversions? (y/n) [{cfg['include_tools']}]: ", cfg["include_tools"])
    cfg["cloud_remote"]  = ask(f"  rclone remote name (blank=keep) [{cfg['cloud_remote']}]: ") or cfg["cloud_remote"]
    save_config(cfg)
    print("  Saved to cct_config.json.")

# --------------------------------------------- pickers / menu ---------------
def pick(items, label_fn, what):
    if not items:
        print("  Nothing found. | چیزی پیدا نشد."); return []
    print(f"\n  {what}:")
    for i, it in enumerate(items, 1):
        print(f"   {i:3}) {label_fn(it)}")
    sel = ask("  Numbers (e.g. 1,3) or all | شماره‌ها یا all: ")
    if not sel: return []
    if sel.lower() == "all": return list(items)
    return [items[int(x) - 1] for x in re.findall(r"\d+", sel) if 0 < int(x) <= len(items)]

def menu_convert(src_key, dst_key):
    cfg = load_config()
    items = ADAPTERS[src_key]["list"]()
    chosen = pick(items, ADAPTERS[src_key]["label"],
                  f"{ADAPTERS[src_key]['name']} chats (newest first)")
    ok = sum(1 for f in chosen if convert_file(src_key, dst_key, f, cfg.get("include_tools", True)))
    if chosen: print(f"  {ok} converted. Restart the target app. | اپ مقصد رو باز کن.")

def menu_export():
    src_key = "claude" if ask("  Source: 1) Claude 2) Codex [1]: ") != "2" else "codex"
    fmt = "html" if ask("  Format: 1) Markdown 2) HTML [1]: ") == "2" else "md"
    items = ADAPTERS[src_key]["list"]()
    chosen = pick(items, ADAPTERS[src_key]["label"], f"{ADAPTERS[src_key]['name']} chats")
    n = sum(1 for f in chosen if export_file(src_key, f, fmt))
    if chosen: print(f"  Exported {n} to {BACKUP_ROOT / 'exports'}")

def menu_verify():
    snaps = [s for s in list_snapshots() if s.is_dir()]
    chosen = pick(snaps, lambda s: f"{s.name} ({human(dir_size(s))})", "Backups to verify")
    for s in chosen: print(f"\n  {s.name}:"); verify_manifest(s)

def menu_cloud():
    cfg = load_config()
    remote = cfg.get("cloud_remote") or ask("  rclone remote name: ")
    if not remote: print("  No remote set."); return
    snaps = list_snapshots()
    chosen = pick(snaps, lambda s: s.name, "Backups to upload")
    for s in chosen: cloud_upload(s, remote)

def menu_switch():
    print("\n  Current logins | لاگین‌های فعلی:")
    for a in ("codex", "claude"):
        print(f"   {APP_NAMES[a]:11}: {account_label(a) or 'not logged in'}")
    ch = ask("  App | برنامه:  1) Codex  2) Claude Code [1]: ").strip()
    app = "claude" if ch == "2" else "codex"
    profs = profile_list(app)
    cur = account_label(app)
    print(f"\n  {APP_NAMES[app]} profiles | پروفایل‌ها:")
    for i, p in enumerate(profs, 1):
        acc = profile_account(p)
        mark = "   <- current | فعلی" if acc and acc == cur else ""
        print(f"   {i:2}) {p.name}  ({acc or '?'}){mark}")
    if not profs:
        print("   (none yet — save one first | هنوز پروفایلی نیست)")
    print("    s) save current login as a profile | ذخیره لاگین فعلی")
    if profs:
        print("    d) delete a profile | حذف پروفایل")
    sel = ask("  Switch to # / s / d | انتخاب: ").strip().lower()
    if sel == "s":
        name = ask("  Profile name (Enter = account e-mail) | اسم پروفایل: ").strip()
        profile_save(app, name or None)
    elif sel == "d" and profs:
        n = ask("  Delete which #? | حذف کدوم؟ : ")
        if n.isdigit() and 1 <= int(n) <= len(profs):
            profile_delete(app, profs[int(n) - 1].name)
    elif sel.isdigit() and 1 <= int(sel) <= len(profs):
        profile_switch(app, profs[int(sel) - 1].name)

MENU = """
==========================================================
   Claude + Codex Toolkit
==========================================================
  1) Full backup now                | بک‌آپ کامل الان
  2) Restore a version              | بازگردانی نسخه
  3) Check/install software         | بررسی/نصب نرم‌افزارها
  4) Convert: Claude Code -> Codex  | تبدیل چت کلاد به کدکس
  5) Convert: Codex -> Claude Code  | تبدیل چت کدکس به کلاد
  6) Export chats (Markdown/HTML)   | خروجی چت‌ها
  7) Search all chat history        | جستجوی تاریخچه
  8) Verify a backup (checksums)    | بررسی سلامت بک‌آپ
  9) Upload a backup to cloud       | آپلود ابری
 10) Settings                       | تنظیمات
 11) Migrate to a new account       | ویزارد تعویض اکانت
 12) Switch user (saved profiles)   | سوییچ سریع یوزر
  0) Exit                           | خروج
"""

def interactive():
    while True:
        print(MENU)
        ch = ask("  Choice | انتخاب: ")
        if   ch == "1": do_backup()
        elif ch == "2": do_restore()
        elif ch == "3": do_software()
        elif ch == "4": menu_convert("claude", "codex")
        elif ch == "5": menu_convert("codex", "claude")
        elif ch == "6": menu_export()
        elif ch == "7": search_all(ask("  Search text | متن جستجو: "),
                                   include_backups=ask("  include backups too? (y/n): ").lower() == "y")
        elif ch == "8": menu_verify()
        elif ch == "9": menu_cloud()
        elif ch == "10": do_settings()
        elif ch == "11": do_migrate()
        elif ch == "12": menu_switch()
        elif ch == "0": break

def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude + Codex Toolkit")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("backup")
    v = sub.add_parser("verify"); v.add_argument("path")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--backups", action="store_true")
    e = sub.add_parser("export"); e.add_argument("source", choices=["claude", "codex"]); e.add_argument("--html", action="store_true")
    sub.add_parser("migrate")
    sw = sub.add_parser("switch")
    sw.add_argument("app", nargs="?", choices=["codex", "claude"])
    sw.add_argument("profile", nargs="?")
    sw.add_argument("--save", nargs="?", const="", default=None, metavar="NAME")
    sw.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "backup":  do_backup()
    elif args.cmd == "verify": verify_manifest(Path(args.path))
    elif args.cmd == "search": search_all(args.query, include_backups=args.backups)
    elif args.cmd == "export":
        for f in ADAPTERS[args.source]["list"](): export_file(args.source, f, "html" if args.html else "md")
    elif args.cmd == "migrate": do_migrate()
    elif args.cmd == "switch":
        if args.list:
            for a in ("codex", "claude"):
                print(f"  {APP_NAMES[a]:11}: {account_label(a) or 'not logged in'}")
                for p in profile_list(a):
                    print(f"       {p.name}  ({profile_account(p) or '?'})")
        elif args.app and args.save is not None:
            profile_save(args.app, args.save or None)
        elif args.app and args.profile:
            profile_switch(args.app, args.profile)
        else:
            menu_switch()
    else: interactive()

if __name__ == "__main__":
    main()
