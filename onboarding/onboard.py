"""onboard.py -- onboarding wizard GUI (tkinter), Windows AND macOS.

Builds to onboard.exe via build_onboard.spec, and to CCSync Onboarding.app
via build_onboard_macos.spec (PyInstaller, on a Mac). Deliberately thin:
page layout, tkinter widgets, and wiring only -- every real decision
(HTTP calls, subprocess invocations, parsing, file writes) lives in
steps.py, which is unit tested without a display (see tests/test_steps.py).
This module itself has no automated tests, per the same "GUI can't sensibly
be unit tested" reasoning the companion's own popup.py documents.

Flow (Back/Next through a single window, frames swapped in place):

    0. Licence   -- the EULA, ACCEPT/DECLINE. DECLINE closes the installer;
                    ACCEPT records ~/.ccsync/eula_accepted.json, which the
                    companion gates its sync lanes on. Skipped when this
                    machine already accepted this version of the document
                    (2026-08-17, COMMERCIAL_READINESS.md item 3).
    1. Welcome   -- what this does + installer/bundled-companion versions.
    2. Role      -- "I'm a remote editor" or "I'm physically connected to
                    the server/NAS" (the `base` role internally), both
                    platforms; sets the dashboard-URL default (tailnet vs
                    LAN) and which pages follow. NOT a question about being
                    THE base rig: a site can have a whole office of machines
                    on the NAS (2026-08-19). Today's studio machine is
                    Windows, but the commercial deployments this is built
                    for can run a Mac there too, so it is asked everywhere.
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
import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk
from typing import Callable, Optional

import steps
from ccsync_companion import theme

logging.basicConfig(level=logging.INFO, format="[onboard] %(message)s")
log = logging.getLogger("onboard")

IS_MACOS = steps.IS_MACOS

# How often the main thread drains the worker->UI queue. Small enough that a
# status label never feels laggy, large enough not to spin (see _safe_after).
UI_PUMP_MS = 50

WINDOW_TITLE = "CCSYNC.APP: onboarding" if IS_MACOS else "CCSYNC.EXE: onboarding"
WINDOW_SIZE = "660x560"
TAILSCALE_DOWNLOAD_URL = ("https://tailscale.com/download/mac" if IS_MACOS
                          else "https://tailscale.com/download/windows")
# Example path shown next to the local-root field; role-independent on macOS.
LOCAL_ROOT_EXAMPLE = (f"/Volumes/YourSSD/{steps.NEUTRAL_TREE_NAME}" if IS_MACOS
                      else f"D:\\{steps.NEUTRAL_TREE_NAME}")


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

        # Worker->UI handoff. Started here, before any page can spawn a
        # thread, so no result can be queued against a pump that is not
        # running yet (see _safe_after / _start_ui_pump).
        self._ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._start_ui_pump()

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
        # The dashboard's site manifest (GET /api/v1/site), fetched once the
        # sign-in proves we can reach it. Everything tenant-shaped this
        # installer used to have compiled in -- the NAS Syncthing device ID,
        # the rclone remote name and SSH port, the NAS-side tree root -- comes
        # from here since 2026-08-17 (WP0). {} against an older dashboard,
        # and every consumer falls back rather than failing.
        self.site: dict = {}
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
        # What the editor typed before normalise_dashboard_url put a scheme on
        # it, kept only so the next page can show the rewrite (OPS-6).
        self._url_rewritten_from: Optional[str] = None

        self.container = tk.Frame(self.root, bg=theme.BG, padx=22, pady=18)
        self.container.pack(fill="both", expand=True)

        self.page_frame: Optional[tk.Frame] = None

        # UX-13 / OPS-6 (resilience sweep 2026-08-28). Closing this window is
        # a supported thing to do everywhere EXCEPT between _clean_slate and
        # the end of the bootstrap, where it leaves a machine with no
        # companion, no tree drive and no autostart. The handler is registered
        # before any page exists so there is no window in which the default
        # (destroy everything, silently) applies.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._interrupted = steps.read_install_breadcrumb()

        # The licence comes before everything, including the welcome text --
        # it is what the editor is agreeing to by installing at all
        # (2026-08-17, COMMERCIAL_READINESS.md item 3). It shows itself only
        # when this machine has not already accepted the bundled version.
        # Unless the last run of this wizard never finished, in which case the
        # editor is told that first (UX-13).
        if self._interrupted is not None:
            self.show_interrupted()
        else:
            self.show_eula()

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

    def _start_ui_pump(self) -> None:
        """Drain the worker->UI queue on the main thread, forever.

        MUST be called from the thread that owns the Tk root, and it re-arms
        itself from inside its own callback, so every `after()` in this
        wizard is created on the main thread. See _safe_after for why that
        is not a detail.
        """
        def _drain() -> None:
            while True:
                try:
                    fn = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception:
                    log.exception("a wizard UI update failed")
            try:
                self.root.after(UI_PUMP_MS, _drain)
            except Exception:
                # The root is gone (window closed) -- nothing left to update.
                pass

        self.root.after(UI_PUMP_MS, _drain)

    def _safe_after(self, fn: Callable[[], None]) -> None:
        """Run `fn` on the main thread. Safe from any thread.

        This used to be `self.root.after(0, fn)` straight from the worker,
        which is fine on Windows/Tk 8.6 and is why it shipped. On macOS with
        Tk 9 it is WORSE than an error: `after()` from a non-main thread
        raises nothing and the callback never runs (verified on Tcl/Tk 9.0.3,
        2026-08-04). Every background result in this wizard arrives through
        here -- the Tailscale check, sign-in, the bootstrap run, both finish
        pages -- so on a Mac all eleven of them silently vanished and the
        wizard sat on "checking..." forever with nothing in any log (MAC-8).

        Only queue.put() crosses the thread boundary now; the Tk call that
        runs `fn` is made by the pump, on the main thread.
        """
        self._ui_queue.put(fn)

    # -- page -1: the interrupted install (UX-13 / OPS-6) -------------------

    def show_interrupted(self) -> None:
        """What the wizard opens on when ~/.ccsync/state/install_in_progress.json
        is still there: the previous run was closed (or the machine rebooted)
        between the clean slate and the end of the install, so this computer
        has no companion and no tree drive and nothing else would have said so.
        """
        frame = self._new_page()
        _heading(frame, "THE LAST INSTALL DID NOT FINISH")
        started = ""
        if isinstance(self._interrupted, dict):
            started = str(self._interrupted.get("started_at") or "")
        when = f"\n\nIt started at {started}." if started else ""
        _label(frame,
               "This computer was part-way through an install when the wizard\n"
               "closed. Until it is finished, there is no CCSync app and no\n"
               f"{self._drive_letter()} drive on this machine, so nothing is syncing."
               f"{when}\n\n"
               "Finishing the install is safe and is the only thing that fixes\n"
               "it. You will be asked for your sign-in again.",
               wraplength=560).pack(anchor="w", pady=(0, 14))

        bar = tk.Frame(frame, bg=theme.BG)
        bar.pack(side="bottom", fill="x", pady=(16, 0))
        theme.neon_button(tk, bar, "CLOSE", self.root.destroy,
                          primary=False).pack(side="left")
        theme.neon_button(tk, bar, "FINISH THE INSTALL", self._on_finish_the_install,
                          primary=True).pack(side="right")

    def _on_finish_the_install(self) -> None:
        # The breadcrumb is NOT cleared here: it is cleared when an install
        # actually reaches a finish page. Clearing it on the click would lose
        # the record all over again if this run is closed too.
        self.show_eula()

    def _on_close_request(self) -> None:
        """WM_DELETE_WINDOW. Free everywhere except mid-install, where closing
        is the OPS-6 half-installed machine and the editor is asked first."""
        if not self._installing:
            self.root.destroy()
            return
        try:
            close_anyway = messagebox.askyesno(
                "CCSync onboarding",
                steps.install_close_warning(self._drive_letter()),
                default="no", icon="warning", parent=self.root)
        except Exception:
            log.exception("could not ask about closing mid-install -- staying open")
            return
        if not close_anyway:
            return
        # The bootstrap outlives this process otherwise: it is a PowerShell
        # (or bash) child that keeps mapping drives and writing config into a
        # machine whose wizard is gone, and races the re-run that fixes it.
        try:
            if steps.terminate_bootstrap():
                log.warning("closed mid-install -- terminated the bootstrap child")
        except Exception:
            log.exception("could not terminate the bootstrap child")
        self.root.destroy()

    # -- page 0: the licence ----------------------------------------------

    def show_eula(self) -> None:
        """The licence agreement, and the only place it is ever read.

        2026-08-17, docs/COMMERCIAL_READINESS.md item 3. The wizard runs
        before the companion is installed, so it is the only party that can
        take consent before anything syncs; ACCEPT writes
        ~/.ccsync/eula_accepted.json (steps.record_eula_acceptance), which the
        companion's eula.py reads and gates its sync lanes on.

        Skipped when this machine already holds an acceptance at least as new
        as the bundled document -- re-running the installer is meant to be
        safe and routine, and making an editor re-read the same agreement
        every time teaches them to click past it. A bumped EULA-VERSION
        marker brings the page back.
        """
        if steps.eula_accepted():
            log.info("licence already accepted on this machine -- skipping that page")
            self.show_welcome()
            return

        frame = self._new_page()
        _heading(frame, "LICENCE AGREEMENT")
        _label(frame,
               "Read the agreement below. ACCEPT records your agreement on this\n"
               "machine and continues; DECLINE closes the installer and nothing\n"
               "is changed.",
               wraplength=560).pack(anchor="w", pady=(0, 10))

        box = tk.Frame(frame, bg=theme.FIELD, highlightthickness=1,
                       highlightbackground=theme.RED_DIM)
        box.pack(fill="both", expand=True, pady=(0, 4))
        text_widget = tk.Text(box, bg=theme.FIELD, fg=theme.TEXT, font=theme.mono(8),
                              relief="flat", wrap="word", height=16,
                              insertbackground=theme.RED)
        scroll = tk.Scrollbar(box, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scroll.set)
        text_widget.insert("1.0", steps.EULA_TEXT or (
            "The licence document is missing from this build of the installer.\n\n"
            "Ask your administrator for a copy before continuing -- accepting\n"
            "here records that you agreed to an agreement this installer could\n"
            "not show you."
        ))
        # Read-only AFTER the insert: a disabled Text refuses writes from the
        # program too, so ordering is not cosmetic.
        text_widget.config(state="disabled")
        text_widget.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        _label(frame, f"version {steps.EULA_VERSION or '?'}",
               fg=theme.MUTED, font=theme.mono(9)).pack(anchor="w", pady=(6, 0))

        bar = tk.Frame(frame, bg=theme.BG)
        bar.pack(side="bottom", fill="x", pady=(16, 0))
        theme.neon_button(tk, bar, "DECLINE", self._on_eula_decline,
                          primary=False).pack(side="left")
        theme.neon_button(tk, bar, "ACCEPT", self._on_eula_accept,
                          primary=True).pack(side="right")

    def _on_eula_decline(self) -> None:
        log.info("licence DECLINED -- closing the installer without changing anything")
        self.root.destroy()

    def _on_eula_accept(self) -> None:
        try:
            path = steps.record_eula_acceptance()
            log.info("licence v%s accepted -- recorded in %s", steps.EULA_VERSION, path)
        except Exception:
            # Do not trap the editor on page 0 over an unwritable ~/.ccsync:
            # the install writes config.toml and identity.json into that same
            # directory minutes later and fails loudly there, with a log the
            # editor can send on. The companion's own gate is what notices a
            # missing record.
            log.exception("could not record the licence acceptance -- continuing")
        self.show_welcome()

    # -- page 1: welcome --------------------------------------------------

    def show_welcome(self) -> None:
        frame = self._new_page()
        _heading(frame, "WELCOME")
        if IS_MACOS:
            welcome_text = (
                "This installer sets up (or refreshes) this Mac for shared\n"
                "editing: it removes every trace of older CCSync versions,\n"
                "installs the sync tools and the current companion app (which\n"
                "updates itself from the dashboard from now on), signs it in,\n"
                f"and points DaVinci Resolve's {self._drive_letter()}:\\ mapping at your local copy\n"
                "of the project tree.\n\n"
                "You'll need the TrueNAS username and password your admin set\n"
                "up for you -- nothing else. Safe to re-run any time."
            )
        else:
            welcome_text = (
                "This installer sets up (or refreshes) this machine for shared\n"
                "editing: it removes every trace of older CCSync versions,\n"
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
        # OPS-7 (resilience sweep 2026-08-28): before the first page that
        # decides anything, refuse a run under an account that is not the one
        # signed in. Everything below installs per-user, and the failure is
        # silent: the wizard reports success, and the editor logs back into
        # their own profile to find nothing.
        if self._wrong_profile_refusal():
            return
        frame = self._new_page()
        _heading(frame, "STEP 1: HOW IS THIS MACHINE CONNECTED?")
        # NOT "are you THE base rig?" any more (2026-08-19, owner's call): a
        # site can have any number of machines wired straight to the NAS -- a
        # whole office of them -- so the question is how THIS computer reaches
        # the footage, which is also the only thing the answer changes.
        _label(frame, "Pick how this computer reaches the footage. Any number of\n"
                       "machines can sit on the studio network and work straight\n"
                       "off the NAS.",
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
            _radio(frame, "I'M A REMOTE EDITOR", "editor",
                   "You edit from elsewhere. Installs the sync tools and points\n"
                   f"Resolve's {self._drive_letter()}:\\ mapping at your local copy of the project tree.")
            _radio(frame, "I'M PHYSICALLY CONNECTED TO THE SERVER/NAS", "base",
                   "This machine is on the studio network and works directly off\n"
                   "the NAS share mounted under /Volumes. Installs only the\n"
                   "companion app - no sync tools, and your NAS mounts are NOT\n"
                   "touched.")
        else:
            _radio(frame, "I'M A REMOTE EDITOR", "editor",
                   "You edit from elsewhere. Installs Tailscale, the sync tools,\n"
                   f"and maps the {self._drive_letter()}: project drive (re-created fresh).")
            _radio(frame, "I'M PHYSICALLY CONNECTED TO THE SERVER/NAS", "base",
                   "This machine is on the studio network and works directly off\n"
                   "the NAS. Installs only the companion app - no sync tools, and\n"
                   f"your {self._drive_letter()}: drive mappings are NOT touched.")

        adv = tk.Frame(frame, bg=theme.BG)
        adv.pack(anchor="w", pady=(8, 8))
        # REQUIRED since 2026-08-17: there is no compiled-in dashboard
        # address any more (WP0), so this is the one thing an editor must be
        # given by their admin besides their account.
        _label(adv, "dashboard url (REQUIRED -- your admin gives you this):",
               fg=theme.MUTED, font=theme.mono(9)).pack(anchor="w")
        _entry(adv, self.dashboard_url_var, width=44).pack(anchor="w", pady=(4, 0))
        self.role_status_lbl = _label(frame, "", fg=theme.RED, wraplength=560)
        self.role_status_lbl.pack(anchor="w", pady=(6, 0))

        self._nav_bar(frame, back=self.show_welcome, next_=self._on_role_next, next_label="NEXT")

    def _wrong_profile_refusal(self) -> bool:
        """True when this page drew a refusal instead of the role question.

        Probed ONCE: the answer cannot change while the wizard is open, and
        the probe shells out. A probe that fails or cannot tell returns None
        from steps.default_console_user and nothing is said -- refusing on
        "could not check" would lock people out of their own install
        (and macOS has no credential-prompt path that could switch accounts).
        """
        if getattr(self, "_profile_checked", False):
            return bool(getattr(self, "_profile_refusal", ""))
        self._profile_checked = True
        try:
            self._profile_refusal = steps.console_user_mismatch(
                steps.default_console_user(), steps.current_user()) or ""
        except Exception:
            log.exception("could not compare the running account with the signed-in one")
            self._profile_refusal = ""
        if not self._profile_refusal:
            return False
        log.error("refusing to install: %s", self._profile_refusal)
        frame = self._new_page()
        _heading(frame, "WRONG ACCOUNT")
        _label(frame, self._profile_refusal, fg=theme.RED, wraplength=560).pack(
            anchor="w", pady=(0, 14))
        _label(frame, "Nothing on this computer has been changed.",
               fg=theme.MUTED, font=theme.mono(9), wraplength=560).pack(
            anchor="w", pady=(0, 10))
        bar = tk.Frame(frame, bg=theme.BG)
        bar.pack(side="bottom", fill="x", pady=(16, 0))
        theme.neon_button(tk, bar, "CLOSE", self.root.destroy, primary=True).pack(side="right")
        return True

    def _site(self) -> Optional[dict]:
        """The fetched manifest, or None so steps falls back to the cached one.
        {} would mean "this site publishes nothing", which is not the same
        thing on a second run (installer-onboard-tools-3/4, 2026-08-21)."""
        return self.site or None

    def _drive_letter(self) -> str:
        """This site's tree drive letter. Before the manifest is fetched this
        is the cached one (a second run) or the P default (a first run) -- the
        pages that render before sign-in cannot know better."""
        return steps.site_drive_letter(self._site())

    def _root_defaults(self) -> set:
        """Every value the local-root field could hold WITHOUT having been
        hand-edited: the two role defaults on this site, the neutral prefill a
        first run seeds before any manifest is known (installer-onboard-tools-4),
        and the pre-2026-08-17 legacy default."""
        return {
            steps.LEGACY_DEFAULT_LOCAL_ROOT,
            steps.DEFAULT_BASE_LOCAL_ROOT,
            steps.default_local_root(),
            steps.default_base_local_root(),
            steps.default_local_root(site=self._site()),
            steps.default_base_local_root(site=self._site()),
            # The neutral prefill: site_tree_name() with no manifest at all.
            steps.default_local_root(site={}),
        }

    def _on_role_changed(self) -> None:
        """Swap the role-default dashboard URL / local root in, but only when
        the current value is still one of the defaults (a hand-edited value
        is never clobbered)."""
        role = self.role_var.get()
        url_defaults = {steps.DEFAULT_DASHBOARD_URL, steps.DEFAULT_BASE_DASHBOARD_URL}
        if self.dashboard_url_var.get().strip() in url_defaults:
            self.dashboard_url_var.set(
                steps.DEFAULT_BASE_DASHBOARD_URL if role == "base" else steps.DEFAULT_DASHBOARD_URL)
        # LEGACY_DEFAULT_LOCAL_ROOT is in the set on purpose: a machine whose
        # field still holds the pre-2026-08-17 default has not been
        # hand-edited either, and clobbering it is the intended behaviour.
        if self.local_root_var.get().strip() in self._root_defaults():
            self.local_root_var.set(
                steps.default_base_local_root(site=self._site()) if role == "base"
                else steps.default_local_root(site=self._site()))

    def _normalise_dashboard_url_field(self) -> str:
        """Put a scheme on what was typed and write the result back into the
        field (OPS-6, 2026-09-04).

        The admin says "the dashboard is nas.tail26290e.ts.net" and the editor
        types exactly that. urlopen answers ValueError("unknown url type"),
        which every caller here swallowed, so the wizard said "not reachable
        yet, wait a few seconds" forever and nothing anywhere said "put
        https:// in front". Writing it BACK is the point: the editor sees what
        is actually being tried, and it is the same string that goes into
        config.toml, so the companion cannot end up with the unusable form.
        """
        typed = self.dashboard_url_var.get().strip()
        fixed = steps.normalise_dashboard_url(typed)
        if fixed and fixed != typed:
            self.dashboard_url_var.set(fixed)
            # Said on the NEXT page, not this one: this one is about to be
            # swapped out, and an editor who never sees the rewrite cannot
            # correct a wrong guess (https for a name, http for an address).
            self._url_rewritten_from = typed
        return fixed

    def _on_role_next(self) -> None:
        self._on_role_changed()  # ensure defaults match the final choice
        self._normalise_dashboard_url_field()
        if not self.dashboard_url_var.get().strip():
            # Refuse here rather than three pages later on an opaque
            # "dashboard isn't reachable": nothing in this installer knows
            # the address any more, and saying so by name is the whole point
            # of removing the default (WP0, 2026-08-17).
            self.role_status_lbl.config(
                text="dashboard url is required -- ask your admin for it "
                     "(e.g. http://<your-dashboard>:8480)")
            return
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

        self._dashboard_url_note(frame)

        self.conn_status_lbl = _label(frame, "", fg=theme.MUTED, wraplength=560)
        self.conn_status_lbl.pack(anchor="w", pady=(6, 6))

        theme.neon_button(tk, frame, "CHECK CONNECTION", self._on_check_connection,
                           primary=True).pack(anchor="w", pady=(4, 4))

        self._next_btn = self._nav_bar(frame, back=self.show_role, next_=self.show_signin,
                                        next_label="NEXT", next_enabled=False)

    def _dashboard_url_note(self, frame) -> None:
        """The address every check on this page uses, and what it was typed as
        when the wizard put a scheme on it (OPS-6). Shown on both pages that
        can fail because of it, so "not reachable" is never the first hint
        that the address is not what the editor thinks it is."""
        url = self.dashboard_url_var.get().strip()
        if not url:
            return
        _label(frame, f"dashboard: {url}", fg=theme.MUTED,
               font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(0, 2))
        if self._url_rewritten_from:
            _label(frame,
                   f"(you typed '{self._url_rewritten_from}', which has no http:// or "
                   "https:// in front. Go Back and edit it if the one above is wrong.)",
                   fg=theme.AMBER, font=theme.mono(9), wraplength=560).pack(
                anchor="w", pady=(0, 4))

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
        if not self.dashboard_url_var.get().strip():
            self.conn_status_lbl.config(
                text="no dashboard url set -- go Back and enter the one your admin gave you",
                fg=theme.RED)
            return
        self.conn_status_lbl.config(text="checking…", fg=theme.MUTED)

        def _worker():
            up = steps.tailscale_up()
            # OPS-6 (2026-09-04): the probe, not the boolean. "wait a few
            # seconds and retry" was printed for a typo'd hostname too, which
            # is a wait that never ends -- and for a missing scheme, which is
            # not a network problem at all.
            probe = (steps.dashboard_probe(self.dashboard_url_var.get()) if up
                     else {"ok": False, "message": ""})

            def _ui():
                if up and probe.get("ok"):
                    self.conn_status_lbl.config(text="connected: the dashboard is answering",
                                                fg=theme.GREEN)
                    if self._next_btn is not None:
                        self._next_btn.config(state="normal", fg=theme.RED, command=self.show_signin)
                elif up:
                    self.conn_status_lbl.config(
                        text=str(probe.get("message") or "the dashboard is not reachable yet"),
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

        self._dashboard_url_note(frame)
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
        if not self.dashboard_url_var.get().strip():
            self.signin_status_lbl.config(
                text="no dashboard url set -- go Back to the role page and enter "
                     "the one your admin gave you; nothing can be verified without it")
            return
        # The base-rig path never sees the tailscale page, so this is where a
        # scheme-less address would otherwise surface as "sign-in failed:
        # unknown url type" (OPS-6, 2026-09-04).
        self._normalise_dashboard_url_field()
        self.signin_status_lbl.config(text="verifying against the dashboard…", fg=theme.MUTED)

        def _worker():
            result = steps.verify_account(self.dashboard_url_var.get(), username, password)
            # The one moment this process is known to be able to reach the
            # dashboard, and still on a worker thread: take the site manifest
            # now so the install has it (and the companion gets its cached
            # copy) without a second round trip. Never fatal -- {} means an
            # older dashboard, and every consumer has a fallback.
            site = steps.fetch_site(self.dashboard_url_var.get()) if result.get("ok") else {}

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
                self.site = site or {}
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
                else:
                    self.picked_role = None
                # UNCONDITIONALLY, not only when the role changed
                # (installer-onboard-tools-4, 2026-08-21). The prefill was
                # computed in __init__, before this machine had ever seen a
                # site manifest, so on a FIRST run it says C:\CCSync while a
                # hand-run windows_bootstrap.ps1 on the next machine would use
                # C:\<tree_name>. _on_role_changed only replaces a value that
                # is still one of the defaults, so a hand-edited path is safe.
                self._on_role_changed()
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
                           f"the current companion app, and signs it in. Your {self._drive_letter()}: drive\n"
                           "mappings are NOT touched. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))
        elif IS_MACOS:
            _label(frame, "This removes every trace of older CCSync versions, installs\n"
                           "rclone/Syncthing (if needed) and the companion app, and points\n"
                           f"Resolve's {self._drive_letter()}:\\ mapping at your sync folder. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))
        else:
            _label(frame, "This removes every trace of older CCSync versions, remounts\n"
                           f"your {self._drive_letter()}: project drive fresh, installs Tailscale/rclone/\n"
                           "Syncthing (if needed) and the companion app. Safe to re-run.",
                   wraplength=560).pack(anchor="w", pady=(0, 10))

        if self.picked_role and self.picked_role != role:
            _label(frame, f"note: you picked '{self.picked_role}', but the dashboard says this "
                           f"account is '{role}' -- so this is a '{role}' install. That is the "
                           f"account's role, which the companion obeys anyway, and only the "
                           f"'editor' install unmaps and re-creates the {self._drive_letter()}: drive.",
                   fg=theme.AMBER, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(0, 8))

        form = tk.Frame(frame, bg=theme.BG)
        form.pack(anchor="w", pady=(0, 10))
        _label(form, "project tree root:" if role == "base" else "local sync folder:").grid(
            row=0, column=0, sticky="w")
        _entry(form, self.local_root_var, width=34).grid(row=0, column=1, sticky="w", padx=(10, 0))
        if role == "base" and IS_MACOS:
            # "the project tree", not one customer's tree name (2026-08-17,
            # COMMERCIAL_READINESS.md item 11) -- the wizard cannot know it
            # here, and the seeded value in the box already shows it.
            _label(frame, "The project-tree folder on the NAS share this machine edits\n"
                           f"from (e.g. {steps.default_base_local_root(site=self._site())}) --\n"
                           "mount the share first if it isn't under /Volumes yet.",
                   fg=theme.MUTED, font=theme.mono(9), wraplength=560).pack(anchor="w", pady=(2, 10))
        elif role == "base":
            _label(frame, "The project-tree folder on the NAS mapping this machine\n"
                           "edits from (the drive your admin mapped to the NAS share).",
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
        self.local_root_error_lbl.pack(anchor="w", pady=(0, 2))

        # UX-14: a separate, AMBER line -- this one never disables the button.
        # A nearly-full drive installs perfectly well and fills up days later
        # during the first proxy pass, which is the whole reason it has to be
        # said here rather than refused here.
        self.local_root_space_lbl = _label(frame, "", fg=theme.AMBER, font=theme.mono(9),
                                           wraplength=560)
        self.local_root_space_lbl.pack(anchor="w", pady=(0, 6))

        btn_row = tk.Frame(frame, bg=theme.BG)
        btn_row.pack(anchor="w", pady=(0, 10))
        self.install_btn = theme.neon_button(tk, btn_row, "BEGIN INSTALL", self._on_begin_install, primary=True)
        self.install_btn.pack(side="left")
        # OPS-5: the log is the only record of what happened, and the person
        # who needs it is usually on the other end of a message from the
        # editor. One click puts the whole file on the clipboard.
        self.copy_log_btn = theme.neon_button(tk, btn_row, "COPY LOG", self._on_copy_log,
                                              primary=False)
        self.copy_log_btn.pack(side="left", padx=(12, 0))

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

        # OPS-5: name the file on the page itself. "Send them this list"
        # (show_finish) is only actionable if the editor can find the list.
        log_path = steps.install_log_path()
        self.log_path_lbl = _label(
            frame,
            f"log file: {log_path}" if log_path is not None
            else "log file: could not be created (your home folder is not writable), "
                 "so use COPY LOG before closing this window",
            fg=theme.MUTED, font=theme.mono(8), wraplength=560)
        self.log_path_lbl.pack(anchor="w", pady=(0, 4))

        # This page has no NEXT, so _nav_bar's return value is None -- which is
        # what made the "disable BACK while installing" guard below dead code
        # (clicking BACK mid-_clean_slate destroyed the log widget under the
        # worker thread, whose next _append_log raised TclError into an
        # invisible handler). Take the BACK widget from _last_back_btn instead.
        self._nav_bar(frame, back=self.show_signin, next_=None)
        self._install_back_btn = self._last_back_btn

    def _append_log(self, text: str) -> None:
        # OPS-5 (2026-09-04): to disk FIRST, on the calling thread. The widget
        # write is queued to the main thread, and the failures worth reading
        # are the ones where that main thread never runs again.
        steps.append_install_log(text)

        def _ui():
            self.log_text.config(state="normal")
            self.log_text.insert("end", text if text.endswith("\n") else text + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self._safe_after(_ui)

    def _on_copy_log(self) -> None:
        """Whole log to the clipboard (OPS-5). The file when there is one --
        it holds the python-level lines the widget never sees -- else whatever
        the widget has, which is better than nothing on a machine that could
        not open the file in the first place."""
        text = steps.read_install_log()
        if not text:
            try:
                text = self.log_text.get("1.0", "end").strip()
            except tk.TclError:
                text = ""
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._flash_button(self.copy_log_btn, "COPY LOG")

    def _flash_button(self, button, restore_label: str) -> None:
        """Say COPIED for a second and change back (OPS-25). On the pages
        whose whole purpose is copying something, a button that does nothing
        visible reads as a button that did nothing."""
        try:
            button.config(text="[ COPIED ]")
        except tk.TclError:
            return

        def _restore():
            try:
                button.config(text=f"[ {restore_label} ]")
            except tk.TclError:
                pass  # the page moved on, which is the same as restored

        self.root.after(1200, _restore)

    def _local_root_problem(self) -> Optional[str]:
        return steps.validate_local_root(self.local_root_var.get(), self._effective_role(),
                                         site=self._site())

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
            # Only when the path is otherwise good: two lines about one empty
            # or impossible field is noise (UX-14).
            space = ("" if problem else
                     (steps.local_root_space_warning(self.local_root_var.get()) or ""))
            self.local_root_space_lbl.config(text=space)
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
        # UX-13 / OPS-6: the breadcrumb goes down BEFORE the first destructive
        # act, not after it. Everything from here to a finish page is a window
        # in which a closed wizard leaves no companion and no tree drive.
        crumb = steps.write_install_breadcrumb(f"clean_slate:{role}")
        if crumb is None:
            self._append_log(
                "WARNING: could not record that an install is in progress "
                "(~/.ccsync/state is not writable). If this window closes "
                "before it finishes, nothing will tell you to re-run it."
            )
        self._append_log("removing traces of previous CCSync versions…")
        if IS_MACOS:
            plan = steps.build_cleanup_plan_macos()
            warnings = steps.execute_cleanup_macos(plan, self._append_log)
        else:
            plan = steps.build_cleanup_plan(role, self.local_root_var.get().strip() or None,
                                           site=self._site())
            # smb_unc so the unmount gate can recognise THIS site's NAS share
            # as somebody else's mapping, not just any non-loopback UNC
            # (COMMERCIAL_READINESS.md item 9, 2026-08-17).
            warnings = steps.execute_cleanup(
                plan, self._append_log,
                smb_unc=str(self.site.get("smb_unc") or ""),
            )
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
            # _site(), not self.site: {} after a failed fetch_site must fall
            # back to the CACHED manifest rather than to the literal default
            # prefix (bug-hunt-2026-09-03 install-onboard-1).
            site=self._site(),
        )
        self._append_log(f"config written (mode={role}).")
        if self.identity_token:
            steps.write_identity(self.verified_username, self.identity_token, role=self.verified_role)
            self._append_log(
                f"companion identity written (role={self.verified_role or 'editor'}) "
                f"-- it will already be signed in."
            )

    def _offer_ssh_key(self) -> None:
        """Send this computer's public key up for the admin to approve
        (OPS-2, 2026-09-04).

        Best effort by design, and it changes nothing about the rest of the
        install: the Finish page still prints the key to send by hand, and a
        dashboard too old to have the route simply 404s. What it buys is the
        common case -- the admin created the account without a key (which
        they can now do) and a click on Settings, Users finishes the job with
        nothing to copy or paste.
        """
        if not self.pub_key or not self.identity_token:
            return
        import socket

        try:
            machine = socket.gethostname()
        except Exception:  # noqa: BLE001 - a name is a nicety here
            machine = ""
        result = steps.submit_ssh_key(
            self.dashboard_url_var.get(), self.verified_username,
            self.identity_token, self.pub_key, machine)
        if result.get("ok"):
            self._append_log("SSH public key sent to the dashboard: your admin approves "
                             "it on the Users page.")
        else:
            self._append_log(f"could not send the SSH key to the dashboard "
                             f"({result.get('error')}) - send it to your admin from the "
                             f"last page instead.")

    def _worker_editor(self) -> None:
        try:
            if steps.installer_on_forbidden_drive(self._site()):
                self._append_log(
                    f"this installer is running from {self._drive_letter()}: or a network share -- the "
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
            self._offer_ssh_key()

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
            self._append_log(
                "this is the long part (a few minutes, up to half an hour on a slow "
                "connection). Every step it takes appears below as it happens.")
            exit_code, output = steps.run_bootstrap(
                editor_name=self.verified_username,
                dashboard_token=self.report_token,
                tailnet_host=tailnet_host,
                local_root=self.local_root_var.get().strip() or None,
                dashboard_url=self.dashboard_url_var.get(),
                companion_exe_source=companion_src,
                site=self._site(),
                # OPS-4 (2026-09-04): line by line, as the child prints it.
                # The whole install used to be captured to a pipe and dumped
                # in one block at the end, so the editor watched an empty
                # window with both buttons disabled for anything up to half an
                # hour with no way to tell working from hung.
                on_line=self._append_log,
            )
            self.bootstrap_output = output

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
            mapping_problem = steps.resolve_mapping_warning(output, self._site())
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

    def _install_finished(self) -> None:
        """Both finish pages, and only them. The install ran to the end, so
        the machine is whole again even when it carries warnings -- the
        breadcrumb means "half-installed", not "not perfect" (UX-13)."""
        self._installing = False
        self._interrupted = None
        steps.clear_install_breadcrumb()

    def show_finish(self) -> None:
        self._install_finished()
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
            # OPS-25 (2026-09-04): the heading counts every warning and the
            # list showed six, so a seventh vanished with nothing saying so --
            # on the one page whose instruction is "send them this list".
            # Truncating is still right (the page has a fixed height and the
            # rest of it is the two values the admin needs), but silence about
            # it is not, and the log now holds all of them.
            for warning in steps.finish_warning_lines(warnings):
                _label(frame, f"  • {warning}", fg=theme.RED, font=theme.mono(9),
                       wraplength=560).pack(anchor="w", pady=(0, 2))
            _label(frame, "", font=theme.mono(4)).pack(anchor="w")
        else:
            _heading(frame, "DONE: SEND THESE TWO VALUES TO YOUR ADMIN")
            _label(frame, "Nothing syncs and no project will be shared with you until your\n"
                           "admin approves both of these. The companion is installed, signed\n"
                           f"in as {self.verified_username}, and will start automatically next login.",
                   wraplength=560).pack(anchor="w", pady=(0, 16))

        # OPS-25 (2026-09-04): the placeholder is instructions to the EDITOR,
        # and [ COPY ] used to put it on the clipboard, from where it was
        # pasted into the message to the admin as if it were an ID. A field
        # holding no value has nothing to copy, and says so on the button.
        device_id_display, device_id_copyable = steps.finish_copy_field(
            self.device_id,
            "(not found automatically - open http://127.0.0.1:8384, Actions > Show ID)")
        self._labeled_copy_field(frame, "Syncthing device ID:", device_id_display,
                                 copyable=device_id_copyable)

        pub_display, pub_copyable = steps.finish_copy_field(
            self.pub_key, "(no SSH public key found - check ~/.ssh/ccsync_ed25519.pub)")
        self._labeled_copy_field(frame, "SSH public key:", pub_display,
                                 copyable=pub_copyable)

        icon_hint = ("the CCSync menu-bar icon's \"Sign in…\"" if IS_MACOS
                     else "right-click the tray icon → \"Sign in…\"")
        _label(frame, f"One more step: {icon_hint} is already\n"
                       "done for you, but nothing downloads until your admin approves the\n"
                       "two values above.", fg=theme.MUTED, font=theme.mono(9),
               wraplength=560).pack(anchor="w", pady=(6, 0))
        _label(frame, "Send these to your admin to finish signup.", fg=theme.AMBER,
               font=theme.mono(10, bold=True)).pack(anchor="w", pady=(10, 0))

        self._finish_log_note(frame)
        self._nav_bar(frame, back=None, next_=self.root.destroy, next_label="CLOSE")

    def _finish_log_note(self, frame) -> None:
        """Name the install log on the way out (OPS-5). This window is about
        to be closed and everything it showed goes with it; the file is what
        the admin can be asked for a week later."""
        path = steps.install_log_path()
        if path is None:
            return
        _label(frame, f"install log: {path}", fg=theme.MUTED, font=theme.mono(8),
               wraplength=560).pack(anchor="w", pady=(10, 0))

    def show_finish_base(self) -> None:
        self._install_finished()
        frame = self._new_page()
        _heading(frame, "DONE: CONNECTED TO THE NAS")
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

        self._finish_log_note(frame)
        self._nav_bar(frame, back=None, next_=self.root.destroy, next_label="CLOSE")

    def _labeled_copy_field(self, parent, label_text, value, copyable: bool = True):
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
            self._flash_button(btn, "COPY")

        btn = theme.neon_button(tk, row, "COPY" if copyable else "NOTHING TO COPY",
                                _copy if copyable else (lambda: None), primary=False)
        if not copyable:
            btn.config(state="disabled", fg=theme.MUTED)
        btn.pack(side="left", padx=(8, 0))

    # -- entrypoint --------------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    # OPS-5 (usability + resilience sweep 2026-09-04): open the run's log file
    # before the first window exists, and put python's own logging in it too.
    # A frozen windowed build has no stderr (console=False in both specs), so
    # until now every log.exception in this process was written to nowhere at
    # all -- including the ones from the worker thread that decide whether an
    # install finished.
    log_path = steps.start_install_log()
    if log_path is not None:
        try:
            handler = logging.FileHandler(str(log_path), encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s [onboard] %(message)s"))
            logging.getLogger().addHandler(handler)
        except OSError:
            pass  # the wizard installs with or without a log
        log.info("onboarding wizard (installer %s) starting; log file: %s",
                 steps.INSTALLER_VERSION, log_path)
    OnboardWizard().run()


if __name__ == "__main__":
    main()
