# -*- coding: utf-8 -*-
"""
Simple Tkinter GUI for the Claude + Codex Toolkit.
Run:  python claude_tool_gui.py     (or  cct-gui  if pip-installed)

Thin wrapper over claude_tool.py — every action calls the same tested
functions the CLI uses; prints are mirrored into the log pane.
"""
import importlib.util, queue, sys, threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except Exception:                                   # headless / no Tk
    print("Tkinter is not available in this Python. GUI cannot start.")
    sys.exit(1)

_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("claude_tool", _here / "claude_tool.py")
ct = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ct)


class _StdoutTee:
    """mirror stdout lines into a thread-safe queue for the log widget"""
    def __init__(self, q): self.q, self._orig = q, sys.stdout
    def write(self, s):
        self.q.put(s)
        try: self._orig.write(s)
        except Exception: pass
    def flush(self):
        try: self._orig.flush()
        except Exception: pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Claude + Codex Toolkit")
        self.geometry("880x640")
        self.q = queue.Queue()
        self.done_q = queue.Queue()          # callbacks to run on the UI thread
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._tab_backup(nb); self._tab_restore(nb); self._tab_accounts(nb)
        self._tab_migrate(nb); self._tab_convert(nb); self._tab_export(nb)
        self._tab_search(nb); self._tab_settings(nb)
        self.log = tk.Text(self, height=10, bg="#0d1117", fg="#e6edf3", insertbackground="#fff")
        self.log.pack(fill="both", expand=False, padx=8, pady=8)
        self.after(120, self._drain)

    # -- helpers ------------------------------------------------------------
    def _run(self, fn, done=None):
        def worker():
            tee = _StdoutTee(self.q); old = sys.stdout; sys.stdout = tee
            try: fn()
            except Exception as e: print(f"  ERROR: {e}")
            finally:
                sys.stdout = old; self.q.put("\n")
                if done: self.done_q.put(done)
        threading.Thread(target=worker, daemon=True).start()

    def _drain(self):
        try:
            while True: self.log.insert("end", self.q.get_nowait()); self.log.see("end")
        except queue.Empty: pass
        try:
            while True: self.done_q.get_nowait()()
        except queue.Empty: pass
        self.after(120, self._drain)

    def _sessions(self, key):
        return ct.ADAPTERS[key]["list"]()

    def _fill_list(self, lb, items, key):
        lb.delete(0, "end")
        for it in items: lb.insert("end", ct.ADAPTERS[key]["label"](it))

    # -- tabs ---------------------------------------------------------------
    def _tab_backup(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Backup")
        ttk.Label(f, text="Full timestamped backup of .claude + .codex, using your saved settings.",
                  wraplength=760).pack(anchor="w", padx=10, pady=10)
        ttk.Button(f, text="Backup now", command=lambda: self._run(lambda: ct.do_backup())).pack(anchor="w", padx=10)

    def _tab_restore(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Restore")
        self.rb_list = tk.Listbox(f, height=12); self.rb_list.pack(fill="both", expand=True, padx=10, pady=8)
        self.rb_snaps = []
        def refresh():
            self.rb_snaps = ct.list_snapshots()
            self.rb_list.delete(0, "end")
            for s in self.rb_snaps:
                tag = "zip" if s.suffix == ".zip" else "dir"
                self.rb_list.insert("end", f"[{tag}] {s.name}")
        self.full = tk.BooleanVar(value=False)
        bar = ttk.Frame(f); bar.pack(fill="x", padx=10)
        ttk.Button(bar, text="Refresh", command=refresh).pack(side="left")
        ttk.Checkbutton(bar, text="Full clone (restore original login too)", variable=self.full).pack(side="left", padx=10)
        def do():
            sel = self.rb_list.curselection()
            if not sel: return messagebox.showinfo("Restore", "Select a backup first.")
            chosen = self.rb_snaps[sel[0]]
            if not messagebox.askyesno("Restore", f"Restore {chosen.name}?"): return
            self._run(lambda: self._restore(chosen))
        ttk.Button(bar, text="Restore selected", command=do).pack(side="left")
        refresh()

    def _restore(self, chosen):
        import zipfile, shutil
        src, tmp = chosen, None
        if chosen.suffix == ".zip":
            tmp = ct.BACKUP_ROOT / f".extract_{ct.ts_now()}"
            with zipfile.ZipFile(chosen) as z: z.extractall(tmp)
            inner = [p for p in tmp.iterdir() if p.is_dir()]
            src = inner[0] if len(inner) == 1 else tmp
        if (src / ct.CRYPTO_META).exists():
            ct.decrypt_creds(src, ct.get_backup_password())
        ct._restore_from_dir(src, self.full.get())
        if tmp: shutil.rmtree(tmp, ignore_errors=True)
        print("  Restart Claude Code / Codex.")

    def _tab_accounts(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Accounts")
        ttk.Label(f, text="Fast user switch — save each account's login once, then flip between "
                          "accounts in seconds. Chats are never touched.",
                  wraplength=800).pack(anchor="w", padx=10, pady=(8, 2))
        self.acc = {}
        for app in ("codex", "claude"):
            lf = ttk.LabelFrame(f, text=ct.APP_NAMES[app]); lf.pack(fill="both", expand=True, padx=10, pady=5)
            cur = ttk.Label(lf, text="Current: ?"); cur.pack(anchor="w", padx=8, pady=(4, 2))
            lb = tk.Listbox(lf, height=4); lb.pack(fill="both", expand=True, padx=8, pady=2)
            bar = ttk.Frame(lf); bar.pack(fill="x", padx=8, pady=(2, 6))
            ttk.Button(bar, text="Save current login as profile",
                       command=lambda a=app: self._acc_save(a)).pack(side="left")
            ttk.Button(bar, text="Switch to selected",
                       command=lambda a=app: self._acc_switch(a)).pack(side="left", padx=6)
            ttk.Button(bar, text="Delete selected",
                       command=lambda a=app: self._acc_delete(a)).pack(side="left")
            ttk.Button(bar, text="Refresh", command=self._acc_refresh).pack(side="left", padx=6)
            self.acc[app] = {"cur": cur, "lb": lb, "profiles": []}
        self._acc_refresh()

    def _acc_refresh(self):
        for app, w in self.acc.items():
            cur = ct.account_label(app)
            w["cur"].config(text=f"Current: {cur or 'not logged in'}")
            w["profiles"] = ct.profile_list(app)
            w["lb"].delete(0, "end")
            for p in w["profiles"]:
                acc = ct.profile_account(p)
                mark = "   <- current" if acc and acc == cur else ""
                w["lb"].insert("end", f"{p.name}   ({acc or '?'}){mark}")

    def _acc_pick(self, app):
        w = self.acc[app]; sel = w["lb"].curselection()
        if not sel:
            messagebox.showinfo("Accounts", "Select a profile first."); return None
        return w["profiles"][sel[0]]

    def _acc_save(self, app):
        self._run(lambda: ct.profile_save(app), done=self._acc_refresh)

    def _acc_switch(self, app):
        p = self._acc_pick(app)
        if not p: return
        if not messagebox.askyesno("Switch", f"Switch {ct.APP_NAMES[app]} to '{p.name}'?\n"
                                   "The current login is saved automatically first."): return
        self._run(lambda: ct.profile_switch(app, p.name), done=self._acc_refresh)

    def _acc_delete(self, app):
        p = self._acc_pick(app)
        if not p: return
        if not messagebox.askyesno("Delete", f"Delete profile '{p.name}'?\n"
                                   "(only the saved login copy — no chats)"): return
        self._run(lambda: ct.profile_delete(app, p.name), done=self._acc_refresh)

    def _tab_migrate(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Migrate")
        ttk.Label(f, justify="left", wraplength=800, text=(
            "Move to a NEW account without losing chats — chats live on disk, not in the account.\n\n"
            "1)  Prepare: full backup + current login saved as a profile.\n"
            "2)  Log into the new account yourself  —  Codex: `codex logout` then `codex login`;"
            "  Claude Code: run `claude`, then /logout (it re-opens the login flow).\n"
            "3)  Verify: accounts changed, every chat still there; the new login is saved as a "
            "profile so you can switch back anytime (Accounts tab).")
        ).pack(anchor="w", padx=10, pady=8)
        self.mig_var = tk.StringVar(value="both")
        row = ttk.Frame(f); row.pack(anchor="w", padx=10)
        for lbl, val in (("Codex", "codex"), ("Claude Code", "claude"), ("Both", "both")):
            ttk.Radiobutton(row, text=lbl, value=val, variable=self.mig_var).pack(side="left", padx=(0, 8))
        bar = ttk.Frame(f); bar.pack(anchor="w", padx=10, pady=10)
        ttk.Button(bar, text="1. Prepare (backup + save login)", command=self._mig_prepare).pack(side="left")
        ttk.Button(bar, text="3. Verify migration", command=self._mig_verify).pack(side="left", padx=8)
        self.mig_state = None

    def _mig_apps(self):
        v = self.mig_var.get()
        return ["codex", "claude"] if v == "both" else [v]

    def _mig_prepare(self):
        apps = self._mig_apps()
        def job():
            before = ct.migrate_prepare(apps)
            self.mig_state = (apps, before)
            print("\n  Now log into the NEW account, then press '3. Verify migration'.")
        self._run(job, done=self._acc_refresh)

    def _mig_verify(self):
        if not self.mig_state:
            return messagebox.showinfo("Migrate", "Run step 1 (Prepare) first.")
        apps, before = self.mig_state
        def job():
            if ct.migrate_finish(apps, before):
                print("\n  [DONE] Migration complete — switch accounts anytime in the Accounts tab.")
        self._run(job, done=self._acc_refresh)

    def _tab_convert(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Convert")
        self.dir_var = tk.StringVar(value="claude>codex")
        top = ttk.Frame(f); top.pack(fill="x", padx=10, pady=6)
        ttk.Radiobutton(top, text="Claude Code -> Codex", value="claude>codex",
                        variable=self.dir_var, command=self._conv_refresh).pack(side="left")
        ttk.Radiobutton(top, text="Codex -> Claude Code", value="codex>claude",
                        variable=self.dir_var, command=self._conv_refresh).pack(side="left", padx=10)
        self.conv_list = tk.Listbox(f, selectmode="extended", height=12)
        self.conv_list.pack(fill="both", expand=True, padx=10, pady=6)
        ttk.Button(f, text="Convert selected", command=self._do_convert).pack(anchor="w", padx=10, pady=(0, 8))
        self._conv_refresh()

    def _conv_refresh(self):
        self.conv_src = self.dir_var.get().split(">")[0]
        self.conv_items = self._sessions(self.conv_src)
        self._fill_list(self.conv_list, self.conv_items, self.conv_src)

    def _do_convert(self):
        src, dst = self.dir_var.get().split(">")
        picks = [self.conv_items[i] for i in self.conv_list.curselection()]
        if not picks: return messagebox.showinfo("Convert", "Select one or more chats.")
        inc = ct.load_config().get("include_tools", True)
        self._run(lambda: [ct.convert_file(src, dst, f, inc) for f in picks])

    def _tab_export(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Export")
        self.ex_src = tk.StringVar(value="claude"); self.ex_fmt = tk.StringVar(value="md")
        top = ttk.Frame(f); top.pack(fill="x", padx=10, pady=6)
        for lbl, val in (("Claude", "claude"), ("Codex", "codex")):
            ttk.Radiobutton(top, text=lbl, value=val, variable=self.ex_src, command=self._ex_refresh).pack(side="left")
        ttk.Radiobutton(top, text="Markdown", value="md", variable=self.ex_fmt).pack(side="left", padx=(20, 0))
        ttk.Radiobutton(top, text="HTML", value="html", variable=self.ex_fmt).pack(side="left")
        self.ex_list = tk.Listbox(f, selectmode="extended", height=12)
        self.ex_list.pack(fill="both", expand=True, padx=10, pady=6)
        ttk.Button(f, text="Export selected", command=self._do_export).pack(anchor="w", padx=10, pady=(0, 8))
        self._ex_refresh()

    def _ex_refresh(self):
        self.ex_items = self._sessions(self.ex_src.get())
        self._fill_list(self.ex_list, self.ex_items, self.ex_src.get())

    def _do_export(self):
        picks = [self.ex_items[i] for i in self.ex_list.curselection()]
        if not picks: return messagebox.showinfo("Export", "Select one or more chats.")
        src, fmt = self.ex_src.get(), self.ex_fmt.get()
        self._run(lambda: [ct.export_file(src, f, fmt) for f in picks])

    def _tab_search(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Search")
        top = ttk.Frame(f); top.pack(fill="x", padx=10, pady=8)
        self.q_entry = ttk.Entry(top); self.q_entry.pack(side="left", fill="x", expand=True)
        self.inc_bk = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="incl. backups", variable=self.inc_bk).pack(side="left", padx=6)
        ttk.Button(top, text="Search",
                   command=lambda: self._run(lambda: ct.search_all(self.q_entry.get(), self.inc_bk.get()))
                   ).pack(side="left")

    def _tab_settings(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Settings")
        cfg = ct.load_config()
        self.s_compress = tk.BooleanVar(value=cfg["compress"])
        self.s_encrypt  = tk.BooleanVar(value=cfg["encrypt"])
        self.s_tools    = tk.BooleanVar(value=cfg["include_tools"])
        self.s_keep     = tk.StringVar(value=str(cfg["keep_last"]))
        self.s_remote   = tk.StringVar(value=cfg["cloud_remote"])
        ttk.Checkbutton(f, text="Compress backups to .zip", variable=self.s_compress).pack(anchor="w", padx=10, pady=4)
        ttk.Checkbutton(f, text="Encrypt login tokens (needs CCT_BACKUP_PASSWORD env or prompt)",
                        variable=self.s_encrypt).pack(anchor="w", padx=10, pady=4)
        ttk.Checkbutton(f, text="Keep tool activity in conversions", variable=self.s_tools).pack(anchor="w", padx=10, pady=4)
        row = ttk.Frame(f); row.pack(anchor="w", padx=10, pady=4)
        ttk.Label(row, text="Keep last N backups (0 = keep all): ").pack(side="left")
        ttk.Entry(row, textvariable=self.s_keep, width=6).pack(side="left")
        row2 = ttk.Frame(f); row2.pack(anchor="w", padx=10, pady=4)
        ttk.Label(row2, text="rclone remote (blank = off): ").pack(side="left")
        ttk.Entry(row2, textvariable=self.s_remote, width=24).pack(side="left")
        def save():
            keep = int(self.s_keep.get()) if self.s_keep.get().isdigit() else 0
            ct.save_config({"compress": self.s_compress.get(), "encrypt": self.s_encrypt.get(),
                            "include_tools": self.s_tools.get(), "keep_last": keep,
                            "cloud_remote": self.s_remote.get().strip()})
            print("  Settings saved.")
        ttk.Button(f, text="Save settings", command=save).pack(anchor="w", padx=10, pady=8)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
