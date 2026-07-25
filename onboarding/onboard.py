"""onboard.py -- Windows onboarding wizard GUI (tkinter).

Builds to onboard.exe via build_onboard.spec (PyInstaller). Deliberately
thin: page layout, tkinter widgets, and wiring only -- every real decision
(HTTP calls, subprocess invocations, parsing, file writes) lives in
steps.py, which is unit tested without a display (see tests/test_steps.py).
This module itself has no automated tests, per the same "GUI can't sensibly
be unit tested" reasoning the companion's own popup.py documents.

Flow (Back/Next through a single window, frames swapped in place):

    1. Welcome   -- what this does + installer/bundled-companion versions.
    2. Role      -- EDITOR (remote) or BASE rig; sets the dashboard-URL
                    default (tailnet vs LAN) and which pages follow.
    3. Tailscale -- EDITOR ONLY: must be installed + joined before the
                    dashboard (on the tailnet) is reachable. "Check
                    connection" gates Next.
    4. Sign in   -- TrueNAS username/password; verify_account() is the
                    install gate. Failure does NOT advance.
    5. Install   -- clean-slate removal of every previous-version trace
                    (steps.build_cleanup_plan/execute_cleanup), config +
                    identity written FIRST, then:
                      editor: run_bootstrap() (P: torn down + remounted,
                              tools installed, companion -> BinDir)
                      base:   install_companion() + autostart + launch;
                              drive mappings deliberately untouched.
    6. Finish    -- editor: Syncthing device ID + SSH public key w/ Copy
                    buttons; base: success + dashboard link.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path
from tkinter import ttk
import tkinter as tk
from typing import Callable, Optional

import steps
from ccsync_companion import theme

logging.basicConfig(level=logging.INFO, format="[onboard] %(message)s")
log = logging.getLogger("onboard")

WINDOW_TITLE = "CCSYNC.EXE — onboarding"
WINDOW_SIZE = "660x560"


def _label(parent, text, **kw):
    kw.setdefault("bg", theme.BG)
    kw.setdefault("fg", theme.TEXT)
    kw.setdefault("font", theme.mono(10))
    kw.setdefault("justify", "left")
    kw.setdefault("anchor", "w")
    return tk.Label(parent, text=text, **kw)


def _heading(parent, text):
    lbl = tk.Label(parent, text=f"► {text}", bg=theme.BG, fg=theme.RED,
                    font=theme.mono(13, bold=True), justify="left", anchor="w")
    lbl.pack(anchor="w", pady=(0, 4))
    tk.Label(parent, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w", pady=(0, 10))
    return lbl


def _entry(parent, textvariable, width=40, show=None):
    kwargs = dict(
        textvariable=textvariable, font=theme.mono(10), width=width,
        bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.RED,
        relief="flat", highlightthickness=1,
        highlightbackground=theme.RED_DIM, highlightcolor=theme.RED,
    )
    if show is not None:
        kwargs["show"] = show
    return tk.Entry(parent, **kwargs)


class OnboardWizard:
    """Owns the Tk root, the swapped-in-place page frame, and the state
    accumulated as the editor moves through the flow."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.configure(bg=theme.BG)
        self.root.minsize(560, 480)

        # -- accumulated state --------------------------------------------
        self.role_var = tk.StringVar(value="editor")
        self.dashboard_url_var = tk.StringVar(value=steps.DEFAULT_DASHBOARD_URL)
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.local_root_var = tk.StringVar(value=steps.DEFAULT_LOCAL_ROOT)
        self.status_var = tk.StringVar(value="")

        self.verified_username: Optional[str] = None
        self.identity_token: Optional[str] = None
        self.verified_role: Optional[str] = None
        self.report_token: str = ""
        self.bootstrap_output: str = ""
        self.device_id: Optional[str] = None
        self.pub_key: str = ""
        # Non-fatal problems that still mean "this machine is NOT ready":
        # a hard-capability miss in the bootstrap (no rclone, no Syncthing,
        # no device ID) or a missing SSH key. The Finish page reports them
        # instead of DONE -- see show_finish (INST-5, INST-22).
        self.install_warnings: list[str] = []
        self._installing = False
        self._local_root_trace: Optional[str] = None

        self.container = tk.Frame(self.root, bg=theme.BG, padx=22, pady=18)
        self.container.pack(fill="both", expand=True)

        self.page_frame: Optional[tk.Frame] = None
        self.show_welcome()

    # -- page scaffolding -----------------------------------------------

    def _new_page(self) -> tk.Frame:
        if self.page_frame is not None:
            self.page_frame.destroy()
        frame = tk.Frame(self.container, bg=theme.BG)
        frame.pack(fill="both", expand=True)
        self.page_frame = frame
        return frame

    def _nav_bar(self, frame, back: Optional[Callable] = None, next_: Optional[Callable] = None,
                 next_label: str = "NEXT", next_enabled: bool = True):
        bar = tk.Frame(frame, bg=theme.BG)
        bar.pack(side="bottom", fill="x", pady=(16, 0))
        if back is not None:
            theme.neon_button(tk, bar, "BACK", back, primary=False).pack(side="left")
        if next_ is not None:
            btn = theme.neon_button(tk, bar, next_label, next_ if next_enabled else (lambda: None), primary=True)
            btn.pack(side="right")
            if not next_enabled:
                btn.config(state="disabled", fg=theme.MUTED)
            return btn
        return None

    def _safe_after(self, fn: Callable[[], None]) -> None:
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    # -- page 1: welcome --------------------------------------------------

    def show_welcome(self) -> None:
        frame = self._new_page()
        _heading(frame, "WELCOME")
        _label(frame, "This installer sets up (or refreshes) this machine for Creators\n"
                       "Club editing: it removes every trace of older CCSync versions,\n"
                       "remounts the project drive, installs the current companion app\n"
                       "(which updates itself from the dashboard from now on), and\n"
                       "signs it in.\n\n"
                       "You'll need the TrueNAS username and password Alex set up\n"
                       "for you -- nothing else. Safe to re-run any time.",
               wraplength=560).pack(anchor="w", pady=(0, 14))

        try:
            from ccsync_companion import config as _cfg_mod
            bundled = _cfg_mod.VERSION
        except Exception:
            bundled = "?"
        _label(frame, f"installer v{steps.INSTALLER_VERSION} — bundles companion v{bundled}",
               fg=theme.MUTED, font=theme.mono(9)).pack(anchor="w", pady=(0, 8))

        self._nav_bar(frame, back=None, next_=self.show_role, next_label="NEXT")

    # -- page 2: role --------------------------------------------------

    def show_role(self) -> None:
        frame = self._new_page()
        _heading(frame, "STEP 1 — WHAT IS THIS MACHINE?")
        _label(frame, "Pick the role for this computer. If you're not Alex, it's\n"
                       "almost certainly a remote editor.",
               wraplength=560).pack(anchor="w", pady=(0, 12))

        def _radio(parent, text, value, subtitle):
            row = tk.Frame(parent, bg=theme.BG)
            row.pack(anchor="w", fill="x", pady=(0, 10))
            rb = tk.Radiobutton(
                row, text=text, variable=self.role_var, value=value,
                command=self._on_role_changed,
                bg=theme.BG, fg=theme.TEXT, selectcolor=theme.FIELD,
                activebackground=theme.BG, activeforeground=theme.RED,
                font=theme.mono(11, bold=True), anchor="w",
            )
            rb.pack(anchor="w")
            _label(row, subtitle, fg=theme.MUTED, font=theme.mono(9),
                   wraplength=540).pack(anchor="w", padx=(24, 0))

        _radio(frame, "REMOTE EDITOR", "editor",
               "You edit from elsewhere. Installs Tailscale, the sync tools,\n"
               "and maps the P: project drive (re-created fresh).")
        _radio(frame, "BASE RIG (Alex's machine)", "base",
               "This machine sits on the studio LAN and works directly off the\n"
               "NAS. Installs only the companion app -- no sync tools, and your\n"
               "P:/T: drive mappings are NOT touched.")

        adv = tk.Frame(frame, bg=theme.BG)
        adv.pack(anchor="w", pady=(8, 8))
        _label(adv, "dashboard url (advanced, leave default unless told otherwise):",
               fg=theme.MUTED, font=theme.mono(9)).pack(anchor="w")
        _entry(adv, self.dashboard_url_var, width=44).pack(anchor="w", pady=(4, 0))

        self._nav_bar(frame, back=self.show_welcome, next_=self._on_role_next, next_label="NEXT")

    def _on_role_changed(self) -> None:
        """Swap the role-default dashboard URL / local root in, but only when
        the current value is still one of the defaults (a hand-edited value
        is never clobbered)."""
        role = self.role_var.get()
        url_defaults = {steps.DEFAULT_DASHBOARD_URL, steps.DEFAULT_BASE_DASHBOARD_URL}
        if self.dashboard_url_var.get().strip() in url_defaults:
            self.dashboard_url_var.set(
                steps.DEFAULT_BASE_DASHBOARD_URL if role == "base" else steps.DEFAULT_DASHBOARD_URL)
        root_defaults = {steps.DEFAULT_LOCAL_ROOT, steps.DEFAULT_BASE_LOCAL_ROOT}
        if self.local_root_var.get().strip() in root_defaults:
            self.local_root_var.set(
                steps.DEFAULT_BASE_LOCAL_ROOT if role == "base" else steps.DEFAULT_LOCAL_ROOT)

    def _on_role_next(self) -> None:
        self._on_role_changed()  # ensure defaults match the final choice
        if self.role_var.get() == "base":
            self.show_signin()
        else:
            self.show_tailscale()

    # -- page 3: tailscale (editor only) --------------------------------------------------

    def show_tailscale(self) -> None:
        frame = self._new_page()
        _heading(frame, "STEP 2 — JOIN THE NETWORK")
        _label(frame, "The project server lives on a private Tailscale network.\n"
                       "Install Tailscale and sign in with the invite link Alex sent\n"
                       "you, then come back here and check the connection.",
               wraplength=560).pack(anchor="w", pady=(0, 14))

        installed = steps.tailscale_installed()
        install_status = "Tailscale: INSTALLED" if installed else "Tailscale: NOT INSTALLED"
        install_color = theme.GREEN if installed else theme.AMBER
        status_lbl = _label(frame, install_status, fg=install_color, font=theme.mono(10, bold=True))
        status_lbl.pack(anchor="w", pady=(0, 10))

        btn_row = tk.Frame(frame, bg=theme.BG)
        btn_row.pack(anchor="w", pady=(0, 14))
        theme.neon_button(tk, btn_row, "INSTALL TAILSCALE (winget)",
                           self._on_install_tailscale, primary=False).pack(side="left", padx=(0, 12))
        theme.neon_button(tk, btn_row, "OPEN DOWNLOAD PAGE",
                           lambda: webbrowser.open("https://tailscale.com/download/windows"),
                           primary=False).pack(side="left")

        self.conn_status_lbl = _label(frame, "", fg=theme.MUTED)
        self.conn_status_lbl.pack(anchor="w", pady=(6, 6))

        theme.neon_button(tk, frame, "CHECK CONNECTION", self._on_check_connection,
                           primary=True).pack(anchor="w", pady=(4, 4))

        self._next_btn = self._nav_bar(frame, back=self.show_role, next_=self.show_signin,
                                        next_label="NEXT", next_enabled=False)

    def _on_install_tailscale(self) -> None:
        self.conn_status_lbl.config(text="installing via winget… this opens its own window", fg=theme.AMBER)

        def _worker():
            import subprocess
            try:
                subprocess.run(
                    ["winget", "install", "--id", "Tailscale.Tailscale", "-e",
                     "--accept-source-agreements", "--accept-package-agreements"],
                )
                msg, color = "winget install finished -- sign in to Tailscale, then Check connection", theme.GREEN
            except Exception as exc:
                msg, color = f"winget install failed: {exc} -- try the download page instead", theme.RED
            self._safe_after(lambda: self.conn_status_lbl.config(text=msg, fg=color))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_check_connection(self) -> None:
        self.conn_status_lbl.config(text="checking…", fg=theme.MUTED)

        def _worker():
            up = steps.tailscale_up()
            reachable = steps.dashboard_reachable(self.dashboard_url_var.get()) if up else False

            def _ui():
                if up and reachable:
                    self.conn_status_lbl.config(text="connected -- dashboard reachable", fg=theme.GREEN)
                    if self._next_btn is not None:
                        self._next_btn.config(state="normal", fg=theme.RED, command=self.show_signin)
                elif up and not reachable:
                    self.conn_status_lbl.config(
                        text="tailscale is up, but the dashboard isn't reachable yet -- wait a few seconds and retry",
                        fg=theme.AMBER)
                else:
                    self.conn_status_lbl.config(
                        text="tailscale isn't joined yet -- open the Tailscale tray icon and sign in",
                        fg=theme.RED)

            self._safe_after(_ui)

        threading.Thread(target=_worker, daemon=True).start()

    # -- page 3: sign in (the gate) --------------------------------------------------

    def show_signin(self) -> None:
        frame = self._new_page()
        _heading(frame, "STEP 3 — SIGN IN")
        _label(frame, "Enter the TrueNAS username and password Alex set up for you.\n"
                       "This is checked against the dashboard right now -- if it\n"
                       "doesn't match, the install will not proceed.",
               wraplength=560).pack(anchor="w", pady=(0, 14))

        form = tk.Frame(frame, bg=theme.BG)
        form.pack(anchor="w", pady=(0, 8))
        _label(form, "username:").grid(row=0, column=0, sticky="w", pady=(0, 8))
        _entry(form, self.username_var, width=30).grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 8))
        _label(form, "password:").grid(row=1, column=0, sticky="w")
        _entry(form, self.password_var, width=30, show="*").grid(row=1, column=1, sticky="w", padx=(10, 0))

        self.signin_status_lbl = _label(frame, "", fg=theme.RED, wraplength=560)
        self.signin_status_lbl.pack(anchor="w", pady=(12, 0))

        back = self.show_role if self.role_var.get() == "base" else self.show_tailscale
        self._nav_bar(frame, back=back, next_=self._on_verify, next_label="VERIFY & CONTINUE")

    def _on_verify(self) -> None:
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username or not password:
            self.signin_status_lbl.config(text="username and password are both required")
            return
        self.signin_status_lbl.config(text="verifying against the dashboard…", fg=theme.MUTED)

        def _worker():
            result = steps.verify_account(self.dashboard_url_var.get(), username, password)

            def _ui():
                if not result.get("ok"):
                    self.signin_status_lbl.config(
                        text=f"sign-in failed: {result.get('error') or 'unknown error'}", fg=theme.RED)
                    self.password_var.set("")
                    return
                self.verified_username = result.get("username") or username
                self.identity_token = result.get("token")
                self.verified_role = result.get("role")
                self.report_token = result.get("report_token") or ""
                self.show_install()

            self._safe_after(_ui)

        threading.Thread(target=_worker, daemon=True).start()

    # -- page 4: install --------------------------------------------------

    def show_install(self) -> None:
        frame = self._new_page()
        role = self.role_var.get()
        _heading(frame, f"STEP 4 — INSTALL  (signed in as {self.verified_username})")
        if role == "base":
            _label(frame, "This removes every trace of older CCSync versions, installs\n"
                           "the current companion app, and signs it in. Your P:/T: drive\n"
                           "mappings are NOT touched. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))
        else:
            _label(frame, "This removes every trace of older CCSync versions, remounts\n"
                           "your P: project drive fresh, installs Tailscale/rclone/\n"
                           "Syncthing (if needed) and the companion app. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))

        if self.verified_role and self.verified_role != role:
            _label(frame, f"note: the dashboard says this account is '{self.verified_role}' but you "
                           f"picked '{role}' -- the account's role wins once the companion signs in.",
                   fg=theme.AMBER, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(0, 8))

        form = tk.Frame(frame, bg=theme.BG)
        form.pack(anchor="w", pady=(0, 10))
        _label(form, "project tree root:" if role == "base" else "local sync folder:").grid(
            row=0, column=0, sticky="w")
        _entry(form, self.local_root_var, width=34).grid(row=0, column=1, sticky="w", padx=(10, 0))
        if role == "base":
            _label(frame, "The Creators_Club folder on the NAS mapping this machine edits\n"
                           "from (default T:\\Creators_Club).",
                   fg=theme.MUTED, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(2, 10))
        else:
            _label(frame, "Point this at a drive with room to spare (proxies + anything you\n"
                           "add land here) -- doesn't have to be C:.",
                   fg=theme.MUTED, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(2, 10))

        # INST-21: the value below is forced into config.toml AND handed to
        # windows_bootstrap.ps1 as -LocalRoot, where a nonexistent drive is a
        # hard abort under EAP=Stop -- after clean-slate has already removed
        # the working install. Validate before the button is even clickable.
        self.local_root_error_lbl = _label(frame, "", fg=theme.RED, font=theme.mono(9),
                                            wraplength=560)
        self.local_root_error_lbl.pack(anchor="w", pady=(0, 6))

        self.install_btn = theme.neon_button(tk, frame, "BEGIN INSTALL", self._on_begin_install, primary=True)
        self.install_btn.pack(anchor="w", pady=(0, 10))

        # One trace for the wizard's lifetime -- the callback reads whichever
        # widgets the current page bound, so re-entering this page must not
        # stack another copy of it.
        if self._local_root_trace is None:
            self._local_root_trace = self.local_root_var.trace_add(
                "write", lambda *_a: self._revalidate_local_root())
        self._revalidate_local_root()

        log_frame = tk.Frame(frame, bg=theme.FIELD, highlightthickness=1, highlightbackground=theme.RED_DIM)
        log_frame.pack(fill="both", expand=True, pady=(0, 4))
        self.log_text = tk.Text(log_frame, bg=theme.FIELD, fg=theme.TEXT, font=theme.mono(8),
                                 relief="flat", wrap="word", height=14, state="disabled",
                                 insertbackground=theme.RED)
        scroll = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._install_back_btn = self._nav_bar(frame, back=self.show_signin, next_=None)

    def _append_log(self, text: str) -> None:
        def _ui():
            self.log_text.config(state="normal")
            self.log_text.insert("end", text if text.endswith("\n") else text + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self._safe_after(_ui)

    def _local_root_problem(self) -> Optional[str]:
        return steps.validate_local_root(self.local_root_var.get(), self.role_var.get())

    def _revalidate_local_root(self) -> None:
        """Enable/disable BEGIN INSTALL from the local_root field's validity,
        with the reason shown inline. Never runs once the install has
        started (the button is disabled for a different reason then)."""
        if self._installing:
            return
        problem = self._local_root_problem()
        try:
            if problem:
                self.local_root_error_lbl.config(text=f"✖ {problem}")
                self.install_btn.config(state="disabled", fg=theme.MUTED)
            else:
                self.local_root_error_lbl.config(text="")
                self.install_btn.config(state="normal", fg=theme.RED)
        except tk.TclError:
            pass  # page swapped out from under the trace

    def _on_begin_install(self) -> None:
        if self._installing:
            return
        problem = self._local_root_problem()
        if problem:
            self._revalidate_local_root()
            return
        self._installing = True
        self.install_btn.config(state="disabled", fg=theme.MUTED)
        if self._install_back_btn is not None:
            self._install_back_btn.config(state="disabled", fg=theme.MUTED)
        self._append_log("starting install…")

        worker = self._worker_base if self.role_var.get() == "base" else self._worker_editor
        threading.Thread(target=worker, daemon=True).start()

    def _clean_slate(self, role: str) -> None:
        """Shared clean-slate phase: enumerate + remove every trace of
        previous installs. Warnings are logged, never fatal."""
        self._append_log("removing traces of previous CCSync versions…")
        plan = steps.build_cleanup_plan(role, self.local_root_var.get().strip() or None)
        warnings = steps.execute_cleanup(plan, self._append_log)
        for warning in warnings:
            self._append_log(f"WARNING: {warning}")
        self._append_log("clean slate done.")

    def _write_config_and_identity(self, role: str) -> None:
        """Config + identity land on disk BEFORE anything launches the
        companion, so its very first start is already configured and
        signed in."""
        steps.ensure_config(
            role,
            editor_name=self.verified_username,
            dashboard_url=self.dashboard_url_var.get().strip(),
            dashboard_token=self.report_token,
            local_root=self.local_root_var.get().strip() or None,
        )
        self._append_log(f"config written (mode={role}).")
        if self.identity_token:
            steps.write_identity(self.verified_username, self.identity_token, role=self.verified_role)
            self._append_log(
                f"companion identity written (role={self.verified_role or 'editor'}) "
                f"-- it will already be signed in."
            )

    def _worker_editor(self) -> None:
        try:
            if steps.installer_on_forbidden_drive():
                self._append_log(
                    "this installer is running from P: or a network share -- the "
                    "install is about to unmount that drive out from under itself "
                    "(and running it off the NAS locks the file for everyone). "
                    "Copy onboard.exe to your Desktop and run it from there."
                )
                self._safe_after(lambda: self._install_failed())
                return

            self.install_warnings = []

            self._append_log("checking SSH key…")
            try:
                pub_path = steps.ensure_ssh_key()
                self.pub_key = steps.read_pubkey(pub_path)
                self._append_log(f"SSH public key ready: {pub_path}")
            except steps.SshKeyError as exc:
                # Not fatal -- everything except lanes A/B still installs --
                # but the editor must not be told they're done (INST-22).
                self.pub_key = ""
                self.install_warnings.append(f"no SSH key: {exc}")
                self._append_log(f"WARNING: {exc}")

            self._clean_slate("editor")
            self._write_config_and_identity("editor")

            # Locate the bundled companion exe; the bootstrap installs it to
            # the canonical %LOCALAPPDATA%\ccsync\bin, registers autostart,
            # launches it, and confirms it stays running.
            companion_src = None
            try:
                companion_src = steps.find_companion_exe()
                self._append_log(f"found bundled companion app: {companion_src}")
            except FileNotFoundError as exc:
                self._append_log(
                    f"companion app not bundled with this installer ({exc}) -- "
                    f"bootstrap will continue without it; install it manually later."
                )

            tailnet_host = steps.dashboard_host(self.dashboard_url_var.get())
            self._append_log(f"running bootstrap for editor '{self.verified_username}'…")
            exit_code, output = steps.run_bootstrap(
                editor_name=self.verified_username,
                dashboard_token=self.report_token,
                tailnet_host=tailnet_host,
                local_root=self.local_root_var.get().strip() or None,
                dashboard_url=self.dashboard_url_var.get(),
                companion_exe_source=companion_src,
            )
            self.bootstrap_output = output
            self._append_log(output)

            # A non-zero exit is now ALSO how the bootstrap reports a
            # hard-capability miss (no rclone, no Syncthing, no device ID).
            # Those are not retryable -- re-running produces the identical
            # result -- so they go to the Finish page in its "NOT ready"
            # state rather than looping the editor on RETRY INSTALL (INST-5).
            capability_problems = steps.bootstrap_capability_warnings(output)
            self.install_warnings.extend(capability_problems)
            if exit_code != 0 and not capability_problems:
                self._append_log(f"bootstrap exited with code {exit_code} -- see log above.")
                self._safe_after(lambda: self._install_failed())
                return
            if capability_problems:
                self._append_log(
                    f"bootstrap completed with {len(capability_problems)} capability "
                    "warning(s) -- this machine is NOT ready to sync yet."
                )

            self.device_id = steps.parse_device_id(output)
            self._safe_after(self.show_finish)
        except Exception as exc:
            log.exception("install worker failed")
            self._append_log(f"install failed: {exc}")
            self._safe_after(lambda: self._install_failed())

    def _worker_base(self) -> None:
        try:
            self._clean_slate("base")
            self._write_config_and_identity("base")

            self._append_log("installing companion app…")
            exe = steps.install_companion()
            self._append_log(f"companion installed: {exe}")
            steps.register_companion_autostart(exe)
            self._append_log("autostart registered.")
            if steps.launch_companion(exe):
                self._append_log("companion launched and running (check your tray).")
            else:
                self._append_log(
                    "WARNING: companion did not stay running -- start it by hand "
                    f"({exe}) and check ~/.ccsync/companion.log."
                )
            self._safe_after(self.show_finish_base)
        except Exception as exc:
            log.exception("base install worker failed")
            self._append_log(f"install failed: {exc}")
            self._safe_after(lambda: self._install_failed())

    def _install_failed(self) -> None:
        self._installing = False
        self.install_btn.config(text="[ RETRY INSTALL ]", state="normal", fg=theme.RED)
        if self._install_back_btn is not None:
            self._install_back_btn.config(state="normal", fg=theme.MUTED)

    # -- page 5: finish --------------------------------------------------

    def show_finish(self) -> None:
        frame = self._new_page()
        warnings = list(self.install_warnings)
        if warnings:
            # The install got far enough to be worth keeping, but something
            # this machine NEEDS is missing. Saying DONE here is how an
            # editor ends up waiting weeks for a sync that can never start
            # (INST-5) -- so say the opposite, first and loudest.
            _heading(frame, f"COMPLETED WITH {len(warnings)} WARNING(S) — NOT READY YET")
            _label(frame, "This machine is NOT ready to sync. Do not tell Alex you're\n"
                           "set up until the problems below are fixed -- send him this\n"
                           "list instead. Everything else installed fine, so re-running\n"
                           "the installer once the cause is sorted will finish the job.",
                   fg=theme.AMBER, wraplength=560).pack(anchor="w", pady=(0, 10))
            for warning in warnings[:6]:
                _label(frame, f"  • {warning}", fg=theme.RED, font=theme.mono(9),
                       wraplength=560).pack(anchor="w", pady=(0, 2))
            _label(frame, "", font=theme.mono(4)).pack(anchor="w")
        else:
            _heading(frame, "DONE — SEND THESE TWO VALUES TO YOUR ADMIN")
            _label(frame, "Nothing syncs and no project will be shared with you until Alex\n"
                           "approves both of these. The companion is installed, signed in as\n"
                           f"{self.verified_username}, and will start automatically next login.",
                   wraplength=560).pack(anchor="w", pady=(0, 16))

        device_id_display = self.device_id or "(not found automatically -- open http://127.0.0.1:8384, "
        if not self.device_id:
            device_id_display += "Actions > Show ID)"
        self._labeled_copy_field(frame, "Syncthing device ID:", device_id_display)

        pub_display = self.pub_key or "(no SSH public key found -- check ~/.ssh/ccsync_ed25519.pub)"
        self._labeled_copy_field(frame, "SSH public key:", pub_display)

        _label(frame, "One more step: right-click the tray icon → \"Sign in…\" is already\n"
                       "done for you, but nothing downloads until Alex approves the two\n"
                       "values above.", fg=theme.MUTED, font=theme.mono(9),
               wraplength=560).pack(anchor="w", pady=(6, 0))
        _label(frame, "Send these to your admin to finish signup.", fg=theme.AMBER,
               font=theme.mono(10, bold=True)).pack(anchor="w", pady=(10, 0))

        self._nav_bar(frame, back=None, next_=self.root.destroy, next_label="CLOSE")

    def show_finish_base(self) -> None:
        frame = self._new_page()
        _heading(frame, "DONE — BASE RIG READY")
        _label(frame, "The companion app is installed, signed in as\n"
                       f"{self.verified_username}, and will start automatically at login.\n\n"
                       "No sync lanes run on this machine (it works directly off the\n"
                       "NAS); the tray still watches your Resolve timeline for media\n"
                       "outside the project tree, and future companion updates arrive\n"
                       "as a one-click prompt in the tray.",
               wraplength=560).pack(anchor="w", pady=(0, 16))

        _label(frame, f"dashboard: {self.dashboard_url_var.get().strip()}",
               fg=theme.MUTED, font=theme.mono(10)).pack(anchor="w", pady=(0, 10))

        self._nav_bar(frame, back=None, next_=self.root.destroy, next_label="CLOSE")

    def _labeled_copy_field(self, parent, label_text, value):
        block = tk.Frame(parent, bg=theme.BG)
        block.pack(anchor="w", fill="x", pady=(0, 12))
        _label(block, label_text, fg=theme.MUTED).pack(anchor="w")

        row = tk.Frame(block, bg=theme.BG)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        var = tk.StringVar(value=value)
        entry = tk.Entry(row, textvariable=var, font=theme.mono(10), width=52,
                          bg=theme.FIELD, fg=theme.TEXT, relief="flat",
                          highlightthickness=1, highlightbackground=theme.RED_DIM,
                          highlightcolor=theme.RED, state="readonly",
                          readonlybackground=theme.FIELD)
        entry.pack(side="left", fill="x", expand=True)

        def _copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(value)

        theme.neon_button(tk, row, "COPY", _copy, primary=False).pack(side="left", padx=(8, 0))

    # -- entrypoint --------------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    OnboardWizard().run()


if __name__ == "__main__":
    main()
