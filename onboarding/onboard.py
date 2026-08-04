"""onboard.py -- onboarding wizard GUI (tkinter), Windows AND macOS.

Builds to onboard.exe via build_onboard.spec, and to CCSync Onboarding.app
via build_onboard_macos.spec (PyInstaller, on a Mac). Deliberately thin:
page layout, tkinter widgets, and wiring only -- every real decision
(HTTP calls, subprocess invocations, parsing, file writes) lives in
steps.py, which is unit tested without a display (see tests/test_steps.py).
This module itself has no automated tests, per the same "GUI can't sensibly
be unit tested" reasoning the companion's own popup.py documents.

Flow (Back/Next through a single window, frames swapped in place):

    1. Welcome   -- what this does + installer/bundled-companion versions.
    2. Role      -- EDITOR (remote) or BASE rig, both platforms; sets the
                    dashboard-URL default (tailnet vs LAN) and which pages
                    follow. Today's studio base rig is Windows, but the
                    commercial deployments this is built for can run a Mac
                    as the base rig, so the question is asked everywhere.
    3. Tailscale -- EDITOR ONLY: must be installed + joined before the
                    dashboard (on the tailnet) is reachable. "Check
                    connection" gates Next. (winget install on Windows,
                    download page on macOS.)
    4. Sign in   -- TrueNAS username/password; verify_account() is the
                    install gate. Failure does NOT advance.
    5. Install   -- clean-slate removal of every previous-version trace
                    (steps.build_cleanup_plan/execute_cleanup, or their
                    _macos twins), config + identity written FIRST, then:
                      editor: run_bootstrap() (Windows: P: torn down +
                              remounted, tools installed, companion ->
                              BinDir; macOS: macos_bootstrap.sh -- tools,
                              LaunchAgents, Resolve Mapped Mount)
                      base:   install_companion() + autostart (HKCU Run
                              value on Windows, LaunchAgent on macOS) +
                              launch; drive mappings / NAS mounts untouched.
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

IS_MACOS = steps.IS_MACOS

WINDOW_TITLE = "CCSYNC.APP: onboarding" if IS_MACOS else "CCSYNC.EXE: onboarding"
WINDOW_SIZE = "660x560"
TAILSCALE_DOWNLOAD_URL = ("https://tailscale.com/download/mac" if IS_MACOS
                          else "https://tailscale.com/download/windows")
# Example path shown next to the local-root field; role-independent on macOS.
LOCAL_ROOT_EXAMPLE = "/Volumes/YourSSD/Creators_Club" if IS_MACOS else r"D:\Creators_Club"


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
        theme.apply_window_icon(tk, self.root)
        self.root.geometry(WINDOW_SIZE)
        self.root.configure(bg=theme.BG)
        self.root.minsize(560, 480)

        # -- accumulated state --------------------------------------------
        self.role_var = tk.StringVar(value="editor")
        self.dashboard_url_var = tk.StringVar(value=steps.DEFAULT_DASHBOARD_URL)
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.local_root_var = tk.StringVar(value=steps.default_local_root())
        self.status_var = tk.StringVar(value="")

        self.verified_username: Optional[str] = None
        self.identity_token: Optional[str] = None
        self.verified_role: Optional[str] = None
        # What the radio said before verify_account overrode it, kept only so
        # the install page can explain the switch (see show_install / B20).
        self.picked_role: Optional[str] = None
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

        self._last_back_btn = None
        self._install_back_btn = None

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
        """Returns the NEXT widget (or None when the page has no NEXT). The
        BACK widget is published on self._last_back_btn instead of returned --
        show_install needs a handle on it to disable it during the install, and
        reading it off this method's return value silently got None on exactly
        the page that has no NEXT button."""
        bar = tk.Frame(frame, bg=theme.BG)
        bar.pack(side="bottom", fill="x", pady=(16, 0))
        self._last_back_btn = None
        if back is not None:
            back_btn = theme.neon_button(tk, bar, "BACK", back, primary=False)
            back_btn.pack(side="left")
            self._last_back_btn = back_btn
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
        if IS_MACOS:
            welcome_text = (
                "This installer sets up (or refreshes) this Mac for Creators\n"
                "Club editing: it removes every trace of older CCSync versions,\n"
                "installs the sync tools and the current companion app (which\n"
                "updates itself from the dashboard from now on), signs it in,\n"
                "and points DaVinci Resolve's P:\\ mapping at your local copy\n"
                "of the project tree.\n\n"
                "You'll need the TrueNAS username and password your admin set\n"
                "up for you -- nothing else. Safe to re-run any time."
            )
        else:
            welcome_text = (
                "This installer sets up (or refreshes) this machine for Creators\n"
                "Club editing: it removes every trace of older CCSync versions,\n"
                "remounts the project drive, installs the current companion app\n"
                "(which updates itself from the dashboard from now on), and\n"
                "signs it in.\n\n"
                "You'll need the TrueNAS username and password your admin set\n"
                "up for you -- nothing else. Safe to re-run any time."
            )
        _label(frame, welcome_text, wraplength=560).pack(anchor="w", pady=(0, 14))

        try:
            from ccsync_companion import config as _cfg_mod
            bundled = _cfg_mod.VERSION
        except Exception:
            bundled = "?"
        _label(frame, f"installer v{steps.INSTALLER_VERSION}, bundles companion v{bundled}",
               fg=theme.MUTED, font=theme.mono(9)).pack(anchor="w", pady=(0, 8))

        self._nav_bar(frame, back=None, next_=self.show_role, next_label="NEXT")

    # -- page 2: role --------------------------------------------------

    def show_role(self) -> None:
        frame = self._new_page()
        _heading(frame, "STEP 1: WHAT IS THIS MACHINE?")
        _label(frame, "Pick the role for this computer. If this is not the studio\n"
                       "base rig, it is almost certainly a remote editor.",
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

        if IS_MACOS:
            _radio(frame, "REMOTE EDITOR", "editor",
                   "You edit from elsewhere. Installs the sync tools and points\n"
                   "Resolve's P:\\ mapping at your local copy of the project tree.")
            _radio(frame, "BASE RIG (the studio machine)", "base",
                   "This machine sits on the studio LAN and works directly off the\n"
                   "NAS share mounted under /Volumes. Installs only the companion\n"
                   "app -- no sync tools, and your NAS mounts are NOT touched.")
        else:
            _radio(frame, "REMOTE EDITOR", "editor",
                   "You edit from elsewhere. Installs Tailscale, the sync tools,\n"
                   "and maps the P: project drive (re-created fresh).")
            _radio(frame, "BASE RIG (the studio machine)", "base",
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
        root_defaults = {steps.DEFAULT_LOCAL_ROOT, steps.DEFAULT_BASE_LOCAL_ROOT,
                         steps.default_local_root(), steps.default_base_local_root()}
        if self.local_root_var.get().strip() in root_defaults:
            self.local_root_var.set(
                steps.default_base_local_root() if role == "base"
                else steps.default_local_root())

    def _on_role_next(self) -> None:
        self._on_role_changed()  # ensure defaults match the final choice
        if self.role_var.get() == "base":
            self.show_signin()
        else:
            self.show_tailscale()

    # -- page 3: tailscale (editor only) --------------------------------------------------

    def show_tailscale(self) -> None:
        frame = self._new_page()
        _heading(frame, "STEP 2: JOIN THE NETWORK")
        _label(frame, "The project server lives on a private Tailscale network.\n"
                       "Install Tailscale and sign in with the invite link your admin\n"
                       "sent you, then come back here and check the connection.",
               wraplength=560).pack(anchor="w", pady=(0, 14))

        installed = steps.tailscale_installed()
        install_status = "Tailscale: INSTALLED" if installed else "Tailscale: NOT INSTALLED"
        install_color = theme.GREEN if installed else theme.AMBER
        status_lbl = _label(frame, install_status, fg=install_color, font=theme.mono(10, bold=True))
        status_lbl.pack(anchor="w", pady=(0, 10))

        btn_row = tk.Frame(frame, bg=theme.BG)
        btn_row.pack(anchor="w", pady=(0, 14))
        if not IS_MACOS:
            # winget is Windows-only; on macOS the download page (a signed
            # .pkg, or the App Store build) is the supported route -- the
            # fleet's Macs do not have Homebrew.
            theme.neon_button(tk, btn_row, "INSTALL TAILSCALE (winget)",
                               self._on_install_tailscale, primary=False).pack(side="left", padx=(0, 12))
        theme.neon_button(tk, btn_row, "OPEN DOWNLOAD PAGE",
                           lambda: webbrowser.open(TAILSCALE_DOWNLOAD_URL),
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
                    icon_word = "menu-bar" if IS_MACOS else "tray"
                    self.conn_status_lbl.config(
                        text=f"tailscale isn't joined yet -- open the Tailscale {icon_word} icon and sign in",
                        fg=theme.RED)

            self._safe_after(_ui)

        threading.Thread(target=_worker, daemon=True).start()

    # -- page 3: sign in (the gate) --------------------------------------------------

    def show_signin(self) -> None:
        frame = self._new_page()
        _heading(frame, "STEP 3: SIGN IN")
        _label(frame, "Enter the TrueNAS username and password your admin set up\n"
                       "for you. This is checked against the dashboard right now -- if\n"
                       "it doesn't match, the install will not proceed.",
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
                # B20: the account's role -- not the radio button -- decides
                # which install runs, because only one of them is destructive.
                # Snap the radio to it here, BEFORE the install page renders,
                # so the role-keyed defaults (_on_role_changed's local_root
                # and dashboard URL) follow it too instead of seeding a base
                # rig's config.toml with an editor's C:\Creators_Club.
                picked = self.role_var.get()
                effective = steps.effective_install_role(picked, self.verified_role)
                if effective != picked:
                    self.picked_role = picked
                    self.role_var.set(effective)
                    self._on_role_changed()
                else:
                    self.picked_role = None
                self.show_install()

            self._safe_after(_ui)

        threading.Thread(target=_worker, daemon=True).start()

    # -- page 4: install --------------------------------------------------

    def _effective_role(self) -> str:
        """The role the install will actually run as. Belt-and-braces with the
        role_var snap in _on_verify: every destructive decision on this page
        goes through here, so the radio alone can never select the P:-teardown
        path on an account the dashboard verified as 'base' (B20)."""
        return steps.effective_install_role(self.role_var.get(), self.verified_role)

    def show_install(self) -> None:
        frame = self._new_page()
        role = self._effective_role()
        _heading(frame, f"STEP 4: INSTALL  (signed in as {self.verified_username})")
        if role == "base" and IS_MACOS:
            _label(frame, "This removes every trace of older CCSync versions, installs\n"
                           "the current companion app, and signs it in. Your NAS mounts\n"
                           "are NOT touched. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))
        elif role == "base":
            _label(frame, "This removes every trace of older CCSync versions, installs\n"
                           "the current companion app, and signs it in. Your P:/T: drive\n"
                           "mappings are NOT touched. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))
        elif IS_MACOS:
            _label(frame, "This removes every trace of older CCSync versions, installs\n"
                           "rclone/Syncthing (if needed) and the companion app, and points\n"
                           "Resolve's P:\\ mapping at your sync folder. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))
        else:
            _label(frame, "This removes every trace of older CCSync versions, remounts\n"
                           "your P: project drive fresh, installs Tailscale/rclone/\n"
                           "Syncthing (if needed) and the companion app. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))

        if self.picked_role and self.picked_role != role:
            _label(frame, f"note: you picked '{self.picked_role}', but the dashboard says this "
                           f"account is '{role}' -- so this is a '{role}' install. That is the "
                           f"account's role, which the companion obeys anyway, and only the "
                           f"'editor' install unmaps and re-creates the P: drive.",
                   fg=theme.AMBER, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(0, 8))

        form = tk.Frame(frame, bg=theme.BG)
        form.pack(anchor="w", pady=(0, 10))
        _label(form, "project tree root:" if role == "base" else "local sync folder:").grid(
            row=0, column=0, sticky="w")
        _entry(form, self.local_root_var, width=34).grid(row=0, column=1, sticky="w", padx=(10, 0))
        if role == "base" and IS_MACOS:
            _label(frame, "The Creators_Club folder on the NAS share this machine edits\n"
                           f"from (e.g. {steps.default_base_local_root()}) --\n"
                           "mount the share first if it isn't under /Volumes yet.",
                   fg=theme.MUTED, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(2, 10))
        elif role == "base":
            _label(frame, "The Creators_Club folder on the NAS mapping this machine edits\n"
                           "from (default T:\\Creators_Club).",
                   fg=theme.MUTED, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(2, 10))
        elif IS_MACOS:
            _label(frame, "Best on an external SSD, plugged in right now:\n"
                           f"{LOCAL_ROOT_EXAMPLE}. A folder in your home works too,\n"
                           "but proxies + anything you add land here -- leave room.",
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

        # This page has no NEXT, so _nav_bar's return value is None -- which is
        # what made the "disable BACK while installing" guard below dead code
        # (clicking BACK mid-_clean_slate destroyed the log widget under the
        # worker thread, whose next _append_log raised TclError into an
        # invisible handler). Take the BACK widget from _last_back_btn instead.
        self._nav_bar(frame, back=self.show_signin, next_=None)
        self._install_back_btn = self._last_back_btn

    def _append_log(self, text: str) -> None:
        def _ui():
            self.log_text.config(state="normal")
            self.log_text.insert("end", text if text.endswith("\n") else text + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self._safe_after(_ui)

    def _local_root_problem(self) -> Optional[str]:
        return steps.validate_local_root(self.local_root_var.get(), self._effective_role())

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

        # B20: the VERIFIED role, never the radio. _worker_editor's
        # _clean_slate("editor") sets unmount_p=True -- `subst P: /D` +
        # `net use P: /delete /y` -- and on the base rig P: is the real NAS
        # share mapping every P:\Projects\... clip path in Resolve resolves
        # through. A default-radio re-run there used to destroy it.
        role = self._effective_role()
        worker = self._worker_base if role == "base" else self._worker_editor
        self._append_log(f"role: {role}")
        threading.Thread(target=worker, daemon=True).start()

    def _clean_slate(self, role: str) -> None:
        """Shared clean-slate phase: enumerate + remove every trace of
        previous installs. Warnings are logged, never fatal."""
        self._append_log("removing traces of previous CCSync versions…")
        if IS_MACOS:
            plan = steps.build_cleanup_plan_macos()
            warnings = steps.execute_cleanup_macos(plan, self._append_log)
        else:
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

            # The bootstrap owns config.toml's seeding path and may have
            # written it itself (it only skips when the file already exists),
            # so re-assert the one key the wizard is authoritative on: the
            # verified username. Normally a no-op; tolerant of every failure.
            # This is the call site steps.finalize_config_identity was written
            # and tested for and had never actually been wired into.
            steps.finalize_config_identity(self.verified_username)

            # Exit 3 is how the bootstrap reports a hard-capability miss (no
            # rclone, no Syncthing, no device ID) after running to the end.
            # Those are not retryable -- re-running produces the identical
            # result -- so they go to the Finish page in its "NOT ready"
            # state rather than looping the editor on RETRY INSTALL (INST-5).
            #
            # Any OTHER non-zero exit is a terminating error part-way through,
            # and it can carry capability warnings with it: the rclone miss
            # fires long before the P: mapping block that then throws. Treating
            # "any capability warning" as proof of a soft failure told the
            # editor "everything else installed fine" while P: had been
            # unmounted and never recreated (B7). bootstrap_hard_failure keys
            # on the exit code, which is the signal that tells them apart.
            capability_problems = steps.bootstrap_capability_warnings(output)
            self.install_warnings.extend(capability_problems)
            # macOS only in practice (the marker never appears in the .ps1's
            # output): "quit Resolve and re-run" and friends belong on the
            # Finish page, not buried mid-log.
            mapping_problem = steps.resolve_mapping_warning(output)
            if mapping_problem:
                self.install_warnings.append(mapping_problem)
            if steps.bootstrap_hard_failure(exit_code, capability_problems):
                self._append_log(
                    f"bootstrap exited with code {exit_code} -- it stopped part-way "
                    f"through, so this install did NOT finish (only exit "
                    f"{steps.BOOTSTRAP_CAPABILITY_EXIT_CODE} means 'finished, but "
                    f"something is missing'). See the log above."
                )
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
            # PRE-FLIGHT, before anything destructive (B22). _clean_slate
            # taskkills the running companion, deletes all four ALL_RUN_VALUES
            # autostart entries and unlinks the binary; install_companion()
            # then raises FileNotFoundError when the exe was never bundled,
            # leaving the machine with no companion, no autostart and no
            # rollback -- and RETRY fails identically forever. The editor
            # worker already checks this first; do the same here.
            try:
                companion_src = steps.find_companion_exe()
            except FileNotFoundError as exc:
                self._append_log(
                    f"companion app not bundled with this installer ({exc}). "
                    "Nothing has been changed on this machine. Get a complete "
                    "CC_Sync package (onboard.exe next to ccsync-companion.exe) "
                    "and run that instead."
                )
                self._safe_after(lambda: self._install_failed())
                return
            self._append_log(f"found bundled companion app: {companion_src}")

            self._clean_slate("base")
            self._write_config_and_identity("base")

            self._append_log("installing companion app…")
            exe = steps.install_companion(src=companion_src)
            self._append_log(f"companion installed: {exe}")
            if IS_MACOS:
                # Autostart AND launch are one act on macOS: the LaunchAgent
                # has RunAtLoad, so loading it starts the companion -- the
                # same plist shape macos_bootstrap.sh writes for editors.
                plist = steps.write_companion_launch_agent(exe)
                self._append_log(f"autostart LaunchAgent written: {plist}")
                if steps.load_launch_agent(plist):
                    self._append_log("companion LaunchAgent loaded (check your menu bar).")
                else:
                    self._append_log(
                        "WARNING: could not load the LaunchAgent -- the companion "
                        "will start at your next login, or load it now with: "
                        f"launchctl bootstrap gui/$(id -u) \"{plist}\""
                    )
            else:
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
            _heading(frame, f"COMPLETED WITH {len(warnings)} WARNING(S): NOT READY YET")
            _label(frame, "This machine is NOT ready to sync. Do not tell your admin\n"
                           "you are set up until the problems below are fixed. Send them\n"
                           "this list instead. Everything else installed fine, so re-running\n"
                           "the installer once the cause is sorted will finish the job.",
                   fg=theme.AMBER, wraplength=560).pack(anchor="w", pady=(0, 10))
            for warning in warnings[:6]:
                _label(frame, f"  • {warning}", fg=theme.RED, font=theme.mono(9),
                       wraplength=560).pack(anchor="w", pady=(0, 2))
            _label(frame, "", font=theme.mono(4)).pack(anchor="w")
        else:
            _heading(frame, "DONE: SEND THESE TWO VALUES TO YOUR ADMIN")
            _label(frame, "Nothing syncs and no project will be shared with you until your\n"
                           "admin approves both of these. The companion is installed, signed\n"
                           f"in as {self.verified_username}, and will start automatically next login.",
                   wraplength=560).pack(anchor="w", pady=(0, 16))

        device_id_display = self.device_id or "(not found automatically -- open http://127.0.0.1:8384, "
        if not self.device_id:
            device_id_display += "Actions > Show ID)"
        self._labeled_copy_field(frame, "Syncthing device ID:", device_id_display)

        pub_display = self.pub_key or "(no SSH public key found -- check ~/.ssh/ccsync_ed25519.pub)"
        self._labeled_copy_field(frame, "SSH public key:", pub_display)

        icon_hint = ("the CCSync menu-bar icon's \"Sign in…\"" if IS_MACOS
                     else "right-click the tray icon → \"Sign in…\"")
        _label(frame, f"One more step: {icon_hint} is already\n"
                       "done for you, but nothing downloads until your admin approves the\n"
                       "two values above.", fg=theme.MUTED, font=theme.mono(9),
               wraplength=560).pack(anchor="w", pady=(6, 0))
        _label(frame, "Send these to your admin to finish signup.", fg=theme.AMBER,
               font=theme.mono(10, bold=True)).pack(anchor="w", pady=(10, 0))

        self._nav_bar(frame, back=None, next_=self.root.destroy, next_label="CLOSE")

    def show_finish_base(self) -> None:
        frame = self._new_page()
        _heading(frame, "DONE: BASE RIG READY")
        icon_word = "menu bar" if IS_MACOS else "tray"
        _label(frame, "The companion app is installed, signed in as\n"
                       f"{self.verified_username}, and will start automatically at login.\n\n"
                       "No sync lanes run on this machine (it works directly off the\n"
                       f"NAS); the {icon_word} still watches your Resolve timeline for\n"
                       "media outside the project tree, and future companion updates\n"
                       f"arrive as a one-click prompt in the {icon_word}.",
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
