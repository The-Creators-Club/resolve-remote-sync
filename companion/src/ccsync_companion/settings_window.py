"""The Settings window -- everything the reduced tray menu no longer shows
(2026-08-27, the tray-menu-reduction pass; see tray.py's module docstring
and _build_menu's for what stayed).

Split into two layers on purpose, the same split popup.py's dialogs don't
need but this one does because it has to be UNIT TESTABLE without a display:

    build_settings_model(snap, app) -> list[Section]
        Pure. Turns a tray snapshot (tray._tray_snapshot's dict) into a list
        of Section objects -- headers, disabled Lines, and Buttons whose
        `on_click` is a bound, zero-arg callable. No tkinter import, no I/O
        beyond what `snap`/`app` already carry. Tests exercise this directly.

    show_settings(app) -> None
        Renders that model as a scrollable Tk window in the same "signature
        red CLI style" every dialog in this package uses (theme.py), and
        refreshes it from a fresh snapshot every ~2s. This half is what
        actually opens tkinter and is expected to be exercised only by a
        human or an end-to-end test with a real display.

Every button follows ONE rule, uniformly, because two Tk roots alive at once
is the sibling-Tk-root hazard AUDIT_2 CORE-M3/H8 describes (see
copy_diagnostics's docstring in app.py): a click closes THIS window,
releases its hold on `_popup_active_lock`, and only THEN spawns the actual
action on a worker thread via tray._spawn -- exactly the pattern
_confirm_remove_project already uses for a dialog opened from the tray menu.
This is deliberately uniform rather than case-by-case (a "Sync now" click
does not strictly need to close the window) because it is the one rule that
can never be wrong: every action here either opens no window at all (safe
either way) or opens one of the themed dialogs (unsafe with this window still
up), and treating all of them the same way is simpler than auditing each one
every time a new button is added here.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from . import config as config_mod
from . import tray as tray_mod
from . import upgrade as upgrade_mod
from . import ytdl_cookies

if TYPE_CHECKING:
    from .app import CompanionApp

log = logging.getLogger("ccsync.settings")


@dataclass
class Line:
    """A disabled, informational row. `style` picks the colour in the Tk
    renderer: "normal" (TEXT), "muted" (MUTED), "warning" (RED)."""

    text: str
    style: str = "normal"


@dataclass
class Button:
    """A clickable row. `on_click` is already bound to `app` (and to
    whatever snapshot-derived arguments it needs) -- callers never pass
    `app` again at click time."""

    label: str
    on_click: Callable[[], None]


@dataclass
class Section:
    title: str
    items: list  # list[Line | Button]


def _role_label(role: str) -> str:
    return "WIRED TO THE SERVER" if role == "base" else "REMOTE EDITOR"


def _mode_needs_restart(app: "CompanionApp") -> bool:
    """True once config.toml's `mode` on disk differs from the value THIS
    process started with -- the role switch writes the file but never
    mutates the live config (a live mutation would change `mode` while
    leaving every OTHER MODE_PROFILES-derived default, like
    lane_b_enabled, stale -- see config.py's MODE_PROFILES and
    app.py's __init__). A restart re-runs load_config() and picks up
    everything at once."""
    try:
        on_disk = config_mod.load_config(config_mod.CONFIG_PATH).get("mode", "editor")
        current = app.config.get("mode", "editor")
        return str(on_disk).strip().lower() != str(current).strip().lower()
    except Exception:
        log.exception("settings: could not check whether mode needs a restart")
        return False


def action_set_role(app: "CompanionApp", role: str) -> None:
    """Write config.toml's `mode` -- the COMPUTER's role since 2026-08-27
    (see app.effective_mode()'s docstring, MULTI_BASE_RIG_PLAN.md WP0/WP1).

    Switching TO "editor" (REMOTE EDITOR) is the dangerous direction on a
    machine whose local_root really is the live NAS share (the actual base
    rig): lane B would start a deleting `rclone sync` DOWNWARD onto it the
    moment a pass ran (AUDIT_2 CORE-C1) -- the one direction here that can
    destroy footage stored nowhere else. It is gated behind the same
    typed-word confirmation the project-removal gate uses (expected word
    "REMOTE"), which is why this function -- unlike every other Settings
    action -- takes the popup lock itself: it is called from a worker
    thread AFTER the Settings window has already closed and released its
    own hold on the lock (see the module docstring's "one rule").

    Switching TO "base" (WIRED TO THE SERVER) is always safe: on a real
    editor machine it just turns sync off, the same as unticking every
    project.
    """
    role = "base" if str(role).strip().lower() == "base" else "editor"
    if role == "editor":
        lock = getattr(app, "_popup_active_lock", None)
        if lock is not None and not lock.acquire(blocking=False):
            tray_mod._notify(app, "Another CCSync window is already open. Close it first.")
            return
        try:
            body = (
                "Switch this computer to REMOTE EDITOR?\n\n"
                "A REMOTE EDITOR computer syncs projects DOWN to its own "
                "drive. If this machine's synced folder is actually the "
                "live server share (the base rig), switching will start "
                "DELETING files from it the moment a proxy-download pass "
                "runs, because that lane syncs the server DOWN onto "
                "whatever this machine calls its own copy.\n\n"
                "If you are not sure this machine has its own separate "
                "copy of the project tree, do not do this.\n\n"
                'Type "REMOTE" to confirm:'
            )
            confirmed = tray_mod._ask_typed_confirmation_locked(
                app, "CCSYNC.EXE: switch to REMOTE EDITOR", body, "REMOTE",
            )
        finally:
            if lock is not None:
                lock.release()
        if not confirmed:
            return
    try:
        config_mod.set_value(config_mod.CONFIG_PATH, "mode", role)
    except Exception:
        log.exception("settings: could not write mode=%s to config.toml", role)
        tray_mod._notify(app, "Couldn't save that -- see the log.")
        return
    tray_mod._notify(
        app, f"This computer is now set to {_role_label(role)}. Takes effect "
             "the next time CCSync starts -- open Settings to restart now.")


def action_restart_now(app: "CompanionApp") -> None:
    """The same relaunch apply_upgrade uses after an install
    (upgrade.restart_self), without the download/swap -- the general
    "reload config.toml by starting over" path this app already has."""
    def _do() -> None:
        blocker = getattr(app, "_standing_down_would_kill_work", lambda: "")()
        if blocker:
            tray_mod._notify(
                app, "Can't restart while a CCSync window is open or media is "
                     "being copied in. Try again once it's done.")
            return
        try:
            upgrade_mod.restart_self(request_shutdown=app.shutdown)
        except Exception:
            log.exception("settings: restart_self failed")
    tray_mod._spawn(app, "Restart CCSync", _do)


def build_settings_model(snap: dict, app: "CompanionApp") -> list[Section]:
    """Pure: snapshot + app -> the sections the window renders. No tkinter."""
    sections: list[Section] = []

    # -- [ THIS COMPUTER ] ---------------------------------------------------
    current_role = app.effective_mode() if hasattr(app, "effective_mode") else "editor"
    computer_items: list = [
        Line(f"Machine name: {platform.node()}"),
        Line(f"Current role: {_role_label(current_role)}"),
        Button(
            "REMOTE EDITOR" + ("  (current)" if current_role != "base" else ""),
            lambda: action_set_role(app, "editor"),
        ),
        Line("  syncs projects to this computer's own drive", style="muted"),
        Button(
            "WIRED TO THE SERVER" + ("  (current)" if current_role == "base" else ""),
            lambda: action_set_role(app, "base"),
        ),
        Line("  works directly off the server share, so nothing is synced "
             "to it", style="muted"),
    ]
    if _mode_needs_restart(app):
        computer_items.append(Line(
            "The role above was changed and takes effect when CCSync next "
            "starts.", style="warning",
        ))
        computer_items.append(Button("RESTART CCSYNC NOW", lambda: action_restart_now(app)))
    computer_items.append(Line(str(snap.get("identity_label", ""))))
    if snap.get("signed_in"):
        computer_items.append(Button("SIGN OUT", lambda: tray_mod.action_sign_out(app)))
    else:
        computer_items.append(Button("SIGN IN…", lambda: tray_mod.action_sign_in(app)))
    sections.append(Section("THIS COMPUTER", computer_items))

    # -- [ SYNC LANES ] -------------------------------------------------------
    lane_items: list = [
        Line(tray_mod._format_lane_line_from(
            s, paused=bool(snap.get("paused")), problems=bool(snap.get("problems")),
            root_absent=bool(snap.get("root_absent")),
        ))
        for s in snap.get("statuses", [])
    ]
    for text in (snap.get("sequencer_line"), snap.get("current_project_line")):
        if text:
            lane_items.append(Line(text))
    guard = snap.get("sync_guard") or {}
    for text in (tray_mod._halt_line(guard), tray_mod._breaker_line(guard),
                 tray_mod._skipped_exists_line(guard), tray_mod._trash_line(guard)):
        if text:
            lane_items.append(Line(text, style="warning"))
    if snap.get("root_unfinished"):
        # CR-92: the drive went out with work owed. The balloon says it
        # every half hour; this is where it stays readable in between.
        lane_items.append(Line(
            f"Your drive was disconnected with {snap['root_unfinished']} still to "
            f"go - plug it back in to finish syncing", style="warning"))
    if snap.get("ytdl_line"):
        lane_items.append(Line(snap["ytdl_line"]))

    if (guard.get("lane_b_breaker") or {}).get("tripped"):
        lane_items.append(Button(
            "RESUME PROXY DOWNLOAD", lambda: tray_mod.action_resume_lane_b(app, snap)))
    halt_active = bool((guard.get("halt") or {}).get("active"))
    halt_is_fleet = (guard.get("halt") or {}).get("scope") == "fleet"
    if halt_active and not halt_is_fleet:
        lane_items.append(Button(
            "START SYNCING AGAIN", lambda: tray_mod.action_release_halt(app)))

    proxy_gap = snap.get("proxy_gap") or {}
    for text in tray_mod.proxy_advisory_lines(proxy_gap):
        lane_items.append(Line(text))
    proxy_missing = int(proxy_gap.get("missing") or 0)
    proxy_encoding = bool(proxy_gap.get("encoding"))
    if proxy_encoding:
        lane_items.append(Button(
            "STOP MAKING PROXIES", lambda: tray_mod.action_stop_proxies(app)))
        lane_items.append(Button(
            "SHOW PROXY PROGRESS", lambda: tray_mod.action_show_proxy_progress(app)))
    elif proxy_missing and proxy_gap.get("can_generate"):
        lane_items.append(Button(
            "MAKE PROXIES NOW (don't wait until I'm away)",
            lambda: tray_mod.action_make_proxies(app)))
    if proxy_gap.get("can_generate") or tray_mod._proxy_history(proxy_gap).get("last_at"):
        lane_items.append(Button(
            "PROXIES THIS MACHINE HAS MADE…", lambda: tray_mod.action_proxy_history(app)))

    broll = snap.get("broll_ingest") or {}
    for text in tray_mod._ingest_lines(broll):
        lane_items.append(Line(text))
    if broll.get("batch_uid"):
        if broll.get("paused"):
            lane_items.append(Button(
                "RESUME B-ROLL INDEXING", lambda: tray_mod.action_resume_broll_ingest(app)))
        else:
            if broll.get("gate") in ("user-active", "resolve-open"):
                lane_items.append(Button(
                    "INDEX B-ROLL NOW (don't wait until I'm away)",
                    lambda: tray_mod.action_index_broll_now(app)))
            lane_items.append(Button(
                "PAUSE B-ROLL INDEXING", lambda: tray_mod.action_pause_broll_ingest(app)))
        lane_items.append(Button(
            "SHOW B-ROLL INDEXING PROGRESS",
            lambda: tray_mod.action_show_ingest_progress(app)))
        lane_items.append(Button(
            "CANCEL THE B-ROLL BATCH…", lambda: tray_mod.action_cancel_broll_ingest(app)))

    music = snap.get("music_ingest") or {}
    for text in tray_mod._ingest_lines(music, "music", "track"):
        lane_items.append(Line(text))
    if music.get("batch_uid"):
        if music.get("paused"):
            lane_items.append(Button(
                "RESUME MUSIC INDEXING", lambda: tray_mod.action_resume_music_ingest(app)))
        else:
            if music.get("gate") in ("user-active", "resolve-open"):
                lane_items.append(Button(
                    "INDEX MUSIC NOW (don't wait until I'm away)",
                    lambda: tray_mod.action_index_music_now(app)))
            lane_items.append(Button(
                "PAUSE MUSIC INDEXING", lambda: tray_mod.action_pause_music_ingest(app)))
        lane_items.append(Button(
            "SHOW MUSIC INDEXING PROGRESS",
            lambda: tray_mod.action_show_music_ingest_progress(app)))
        lane_items.append(Button(
            "CANCEL THE MUSIC BATCH…", lambda: tray_mod.action_cancel_music_ingest(app)))

    sections.append(Section("SYNC LANES", lane_items))

    # -- [ YOUTUBE ] ------------------------------------------------------
    if snap.get("ytdl_local_downloads") or snap.get("ytdl_youtube_signin"):
        yt_items: list = []
        if snap.get("ytdl_local_downloads"):
            yt_items.append(Button(
                "Accept YouTube Terms ✓" if snap.get("ytdl_attested")
                else "Accept YouTube Terms…",
                lambda: tray_mod.action_youtube_terms(app),
            ))
        if snap.get("ytdl_youtube_signin"):
            yt_health = (snap.get("ytdl_cookies_health") or {}).get("status")
            yt_bad = yt_health in (ytdl_cookies.STATUS_STALE, ytdl_cookies.STATUS_EXPIRED)
            yt_signed_in = yt_health == ytdl_cookies.STATUS_OK
            if yt_bad:
                yt_items.append(Line(tray_mod._youtube_warning_line(snap), style="warning"))
                yt_label = "Sign in to YouTube again (session expired)…"
            elif yt_signed_in:
                yt_label = "YouTube: signed in ✓ (sign in again…)"
            else:
                yt_label = "Sign in to YouTube (for downloads)…"
            yt_items.append(Button(yt_label, lambda: tray_mod.action_youtube_sign_in(app)))
            yt_items.append(Button(
                "Use an exported cookies.txt…",
                lambda: tray_mod.action_youtube_cookies_file(app)))
        sections.append(Section("YOUTUBE", yt_items))

    # -- [ ADVANCED ] -------------------------------------------------------
    advanced_items: list = [
        Button("SCAN WHOLE PROJECT", lambda: tray_mod.action_scan_whole_project(app)),
        Button("BRING AN EXISTING PROJECT'S MEDIA INTO THE SYNCED FOLDER…",
               lambda: tray_mod.action_consolidate_project(app)),
        Button("UNDO THE LAST CLIP-PATH CHANGE CCSYNC MADE…",
               lambda: tray_mod.action_undo_last_relink(app)),
    ]
    if snap.get("p_swap_available"):
        advanced_items.append(Button(
            "FINISH GRADING: P: BACK TO LOCAL PROXIES"
            if snap.get("p_mode") == "server"
            else "GRADE FROM SERVER ORIGINALS (SWAP P:)…",
            lambda: tray_mod.action_grade_swap(app, snap),
        ))
    if not halt_active:
        advanced_items.append(Button(
            "STOP ALL SYNCING ON THIS MACHINE…", lambda: tray_mod.action_halt_sync(app)))
    for proj in snap.get("removable", []):
        slug = proj.get("slug", "")
        rel = proj.get("rel", "")
        label = (
            "REMOVE '" + rel.split("/")[-1] + "'"
            + (" (upload only)" if proj.get("upload_only") else "")
            + " FROM THIS MACHINE…"
        )
        advanced_items.append(Button(
            label, (lambda slug=slug, rel=rel: tray_mod.action_remove_project(app, slug, rel))))
    sections.append(Section("ADVANCED", advanced_items))

    # -- [ HELP ] -------------------------------------------------------
    help_items: list = [
        Button("COPY DIAGNOSTICS FOR YOUR ADMIN",
               lambda: tray_mod.action_copy_diagnostics(app)),
        Button("OPEN LOG", lambda: tray_mod.action_open_log(app)),
    ]
    upgrade_info = snap.get("upgrade_info")
    if upgrade_info:
        help_items.append(Button(
            upgrade_mod.offer_label(upgrade_info["version"]),
            lambda: tray_mod.action_update_now(app)))
    help_items.append(Line(f"ccsync-companion v{config_mod.VERSION}", style="muted"))
    sections.append(Section("HELP", help_items))

    return sections


# -- the Tk shell -------------------------------------------------------

_WINDOW_TITLE = "CCSYNC.EXE: SETTINGS"
_REFRESH_MS = 2000


def show_settings(app: "CompanionApp") -> None:
    """Open the Settings window. Takes `_popup_active_lock` like every other
    tk.Tk() site in this process (see the module docstring)."""
    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        tray_mod._notify(app, "Another CCSync window is already open. Close it first.")
        return

    def _build_and_show() -> None:
        _build_settings_window(app, lock)

    try:
        from . import ui_dispatch

        ui_dispatch.dispatch(_build_and_show)
    except Exception as exc:
        log.warning("settings window unavailable (%s)", exc)
        if lock is not None and lock.locked():
            lock.release()


def _build_settings_window(app: "CompanionApp", lock) -> None:
    try:
        import tkinter as tk
        from tkinter import ttk

        from . import theme
    except Exception as exc:
        log.warning("settings window: tkinter unavailable (%s)", exc)
        if lock is not None and lock.locked():
            lock.release()
        return

    try:
        root = tk.Tk()
    except Exception as exc:
        log.warning("settings window failed to open (%s)", exc)
        if lock is not None and lock.locked():
            lock.release()
        return

    state = {"closed": False}

    def _release_and_close() -> None:
        if state["closed"]:
            return
        state["closed"] = True
        try:
            root.after_cancel(refresh_job[0]) if refresh_job[0] is not None else None
        except Exception:
            pass
        try:
            root.destroy()
        finally:
            if lock is not None and lock.locked():
                lock.release()

    def _run(label: str, fn: Callable[[], None]) -> Callable[[], None]:
        # ONE rule for every button: close this window, release the lock,
        # THEN run the action on its own thread. See the module docstring.
        def _handler() -> None:
            _release_and_close()
            tray_mod._spawn(app, label, fn)
        return _handler

    root.title(_WINDOW_TITLE)
    theme.apply_window_icon(tk, root)
    root.configure(bg=theme.BG)
    root.geometry("720x640")
    root.minsize(560, 420)
    root.protocol("WM_DELETE_WINDOW", _release_and_close)
    root.bind("<Escape>", lambda _e: _release_and_close())

    canvas = tk.Canvas(root, bg=theme.BG, highlightthickness=0)
    vbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    body = tk.Frame(canvas, bg=theme.BG, padx=18, pady=14)
    body_window = canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")

    def _on_body_configure(_e=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event) -> None:
        canvas.itemconfigure(body_window, width=event.width)

    body.bind("<Configure>", _on_body_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event) -> None:
        delta = -1 if event.delta > 0 else 1
        canvas.yview_scroll(delta, "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _render(sections: list[Section]) -> None:
        for child in body.winfo_children():
            child.destroy()
        for section in sections:
            tk.Label(body, text=f"[ {section.title} ]", bg=theme.BG, fg=theme.RED,
                     font=theme.mono(11, bold=True), justify="left", anchor="w"
                     ).pack(anchor="w", pady=(14, 2))
            tk.Label(body, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM,
                     font=theme.mono(9)).pack(anchor="w")
            for item in section.items:
                if isinstance(item, Line):
                    fg = {"muted": theme.MUTED, "warning": theme.RED}.get(item.style, theme.TEXT)
                    tk.Label(body, text=item.text, bg=theme.BG, fg=fg, font=theme.mono(10),
                             justify="left", anchor="w", wraplength=660
                             ).pack(anchor="w", pady=(2, 0))
                elif isinstance(item, Button):
                    theme.neon_button(
                        tk, body, item.label, _run(item.label, item.on_click),
                    ).pack(anchor="w", pady=(4, 0))

    refresh_job: list = [None]

    def _refresh() -> None:
        if state["closed"]:
            return
        try:
            snap = tray_mod._tray_snapshot(app)
            _render(build_settings_model(snap, app))
        except Exception:
            log.exception("settings window: refresh failed")
        refresh_job[0] = root.after(_REFRESH_MS, _refresh)

    _refresh()
    try:
        from . import ui_dispatch

        ui_dispatch.run_dialog(root)
    finally:
        _release_and_close()
