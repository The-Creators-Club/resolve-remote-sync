"""System tray icon (pystray + Pillow) — Component 4 of SPEC.md's companion
app.

Only imported inside a try/except ImportError in app.py's run loop, so the
app still runs headless (console status logging only) if these aren't
installed — same fallback pattern as broll-platform's companion/tray.py.

Install with: pip install ccsync-companion[tray]
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Optional

import pystray  # noqa: F401  (raises ImportError here if missing — by design)
from PIL import Image, ImageDraw

from . import config as config_mod
from . import resolve_bridge
from . import upgrade as upgrade_mod
from .sync.base import STATE_ERROR, STATE_PAUSED, STATE_SYNCING, LaneStatus

if TYPE_CHECKING:
    from .app import CompanionApp

log = logging.getLogger("ccsync.tray")

from . import theme

COLOR_GREEN = theme.RGB_GREEN
COLOR_ORANGE = theme.RGB_AMBER
COLOR_RED = theme.RGB_RED


# Editor-facing lane names. The wire/internal names are unchanged -- only
# what a human reads. "lane a video up: OK" is internal jargon with no
# legend anywhere in the product, so an editor could not know that lane C
# failing means their music won't arrive but their proxies still will
# (AUDIT_2 UX-12).
LANE_LABELS = {
    "lane_a_video_up": "Uploads (your footage → server)",
    "lane_b_proxy_down": "Proxies (server → you)",
    "lane_c_syncthing": "Everything else, both ways (audio, graphics, subs)",
}


def lane_label(name: str) -> str:
    return LANE_LABELS.get(name, str(name).replace("_", " "))


def _identity_is_valid(app: "CompanionApp") -> bool:
    identity = getattr(app, "identity", None)
    try:
        return identity is not None and identity.valid()
    except Exception:
        return False


def compute_overall_color(
    statuses: list[LaneStatus], app: "CompanionApp | None" = None
) -> str:
    """red (any lane error) / orange (not syncing, or syncing) / green.

    GREEN NOW MEANS SOMETHING. It used to mean only "no lane is in the error
    state and none is mid-transfer" -- so a companion that was not signed in,
    was paused, or had sync disabled entirely showed a green icon above three
    lines reading `OK`, which is the universal signal for "everything is
    fine" while literally nothing synced (AUDIT_2 UX-1/UX-2). The icon must
    never be green unless this machine is signed in, unpaused, correctly
    configured and caught up.
    """
    if any(s.state == STATE_ERROR for s in statuses):
        return "red"
    if app is not None:
        try:
            if getattr(app, "config_problems", None):
                return "red"
            if not _identity_is_valid(app) and getattr(app, "_require_login", True):
                return "orange"
            if app.is_paused():
                return "orange"
            if not getattr(app, "_sync_enabled", True):
                return "orange"
        except Exception:
            log.exception("compute_overall_color: app state read failed")
            return "orange"
    if any(s.state == STATE_SYNCING for s in statuses):
        return "orange"
    return "green"


def _color_rgb(color_name: str) -> tuple[int, int, int]:
    return {"green": COLOR_GREEN, "orange": COLOR_ORANGE, "red": COLOR_RED}.get(color_name, COLOR_GREEN)


class _MenuOpenGuard:
    """Answers "is the tray's context menu open RIGHT NOW?" on Windows.

    pystray's win32 backend shows the menu with a single blocking
    win32.TrackPopupMenuEx call on the message-loop thread. Wrapping that
    function with a flag gives the refresh thread a reliable open/closed
    signal, so it can defer EVERY tray mutation (icon, tooltip, menu) while
    the user is looking at the menu -- mutating any of them mid-open is
    what produced the random hover hangs (a menu rebuild DestroyMenu()s the
    handle being displayed; icon/tooltip NIM_MODIFYs force redraws under
    the cursor). On other backends install() is a no-op and is_open() stays
    False, preserving the old always-update behavior.

    The flag is the PROCESS-WIDE ui_state.menu_open: the menu's highlight
    repaints run through a Python window procedure that needs the GIL, so
    resolve_bridge defers its GIL-holding fusionscript calls while it is
    set (a single Resolve poll froze the hover highlight for a second-plus,
    2026-07-26)."""

    def __init__(self) -> None:
        from . import ui_state

        self._open = ui_state.menu_open

    def install(self) -> None:
        try:
            if sys.platform != "win32":
                return
            from pystray import _win32  # type: ignore[attr-defined]

            win = _win32.win32
            if getattr(win, "_ccsync_menu_open_flag", None) is not None:
                self._open = win._ccsync_menu_open_flag
                return
            original = win.TrackPopupMenuEx
            flag = self._open

            def tracked(*args, **kwargs):
                flag.set()
                try:
                    return original(*args, **kwargs)
                finally:
                    flag.clear()

            win.TrackPopupMenuEx = tracked
            win._ccsync_menu_open_flag = flag
        except Exception:
            log.debug("menu-open guard unavailable", exc_info=True)

    def is_open(self) -> bool:
        return self._open.is_set()


# One rendered image per color -- regenerating the identical 64x64 PIL image
# (and the win32 HICON pystray derives from it) every refresh tick was pure
# GDI churn.
_ICON_IMAGE_CACHE: dict = {}


def _icon_image_cached(color_name: str):
    image = _ICON_IMAGE_CACHE.get(color_name)
    if image is None:
        image = _make_icon_image(color_name)
        _ICON_IMAGE_CACHE[color_name] = image
    return image


def _make_icon_image(color_name: str):
    """Terminal-style tile: near-black rounded square, neon-red border, and a
    status-colored sync glyph (two chevrons) with a soft glow."""
    c = _color_rgb(color_name)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # tile + neon border
    draw.rounded_rectangle((3, 3, 61, 61), radius=12, fill=(*theme.RGB_BG, 255),
                           outline=(*theme.RGB_RED, 255), width=3)

    up = [(20, 27), (32, 13), (44, 27)]     # ▲ upload chevron
    down = [(20, 37), (32, 51), (44, 37)]   # ▼ download chevron

    # glow pass: fat translucent strokes under the crisp ones
    for pts in (up, down):
        draw.line(pts, fill=(*c, 70), width=11, joint="curve")
    for pts in (up, down):
        draw.line(pts, fill=(*c, 255), width=5, joint="curve")
    return img


def human_bytes(n: Optional[int]) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def human_duration(seconds: Optional[float]) -> str:
    try:
        secs = int(float(seconds or 0))
    except (TypeError, ValueError):
        return "?"
    if secs <= 0:
        return "<1 min"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"~{secs // 60} min"
    return f"~{secs // 3600}h {(secs % 3600) // 60}m"


def classify_lane_error(last_error: Optional[str]) -> str:
    """Turn rclone's verbatim stderr tail into something actionable.

    rclone_lane surfaces f"rclone exited {rc}" plus the last 300 chars of
    stderr straight into the tray, which is unreadable and suggests no
    action (AUDIT_2 UX-16). The raw text stays in the log and in
    Copy diagnostics."""
    text = str(last_error or "").lower()
    if not text:
        return "Something went wrong. Tray → Copy diagnostics for your admin."
    if "marker missing" in text:
        # The editor deleted a project's local folder while it was still
        # ticked -- routine when cycling projects, and nothing was lost
        # (the server copy is untouched). Say what to do, not PROBLEM.
        return ("A project folder was deleted on this machine while still ticked. "
                "Untick it on the dashboard, or use Advanced → Remove a project from this machine.")
    if any(k in text for k in ("no space", "enospc", "disk full", "not enough space")):
        return "Your disk is full. Free up space and it will resume."
    if any(k in text for k in (
        "permission denied", "auth", "handshake", "publickey", "unable to authenticate",
    )):
        return "The server rejected this machine's login. Tray → Copy diagnostics for your admin."
    if any(k in text for k in (
        "timeout", "timed out", "no route", "connection refused", "connection reset",
        "network", "unreachable", "dial tcp", "lookup", "eof",
    )):
        return "Can't reach the server. Check the Tailscale tray icon is connected."
    return "Something went wrong. Tray → Copy diagnostics for your admin."


def _format_lane_line(status: LaneStatus, app: "CompanionApp | None" = None) -> str:
    """One tray line per lane, in words an editor can act on.

    The word `OK` used to be the first thing on every line whatever the
    state -- including "nobody is signed in so nothing syncs" and "sync is
    disabled on this machine" -- because those states only ever wrote to
    LaneStatus.detail and left `state` at "idle" (AUDIT_2 UX-1). `OK` is now
    gone entirely: a lane says either what it is doing or why it is not.
    """
    paused = False
    problems = False
    if app is not None:
        try:
            problems = bool(getattr(app, "config_problems", None))
        except Exception:
            pass
        try:
            paused = bool(app.is_paused())
        except Exception:
            pass
    return _format_lane_line_from(status, paused=paused, problems=problems)


def _format_lane_line_from(status: LaneStatus, paused: bool, problems: bool) -> str:
    """_format_lane_line with the app state already snapshotted -- what the
    menu build actually uses, so rendering never calls back into app."""
    label = lane_label(status.name)
    # Pause is checked FIRST: no lane ever sets state="paused" (the sequencer
    # owns pause, the lanes don't know), so after clicking Pause all three
    # lines still read as normal (AUDIT_2 UX-2).
    if problems:
        return f"{label}: NOT SYNCING (this machine isn't set up yet)"
    if paused:
        return f"{label}: PAUSED"
    if status.state == STATE_ERROR:
        return f"{label}: PROBLEM. {classify_lane_error(status.last_error)}"
    detail = str(status.detail or "")
    if "sign in required" in detail.lower():
        return f"{label}: NOT SYNCING (sign in first)"
    if "sync disabled" in detail.lower() or "direct NAS access" in detail:
        return f"{label}: not used on this machine (it works straight off the NAS)"
    if detail.startswith("NOT SYNCING"):
        return f"{label}: NOT SYNCING (this machine isn't set up yet)"
    if status.state == STATE_SYNCING:
        # `queued` is set to 0 at the end of every run and incremented by
        # nothing, so the old "syncing (0 queued)" was a counter reading zero
        # while transferring -- while bytes_done/bytes_total/speed_bps/
        # eta_seconds were live and displayed nowhere (AUDIT_2 UX-11).
        parts = []
        if status.bytes_total:
            parts.append(f"{human_bytes(status.bytes_done)} of {human_bytes(status.bytes_total)}")
        elif status.bytes_done:
            parts.append(human_bytes(status.bytes_done))
        if status.speed_bps:
            parts.append(f"{human_bytes(int(status.speed_bps))}/s")
        if status.eta_seconds:
            parts.append(f"{human_duration(status.eta_seconds)} left")
        return f"{label}: syncing" + (f" ({' · '.join(parts)})" if parts else "…")
    if status.state == STATE_PAUSED:
        return f"{label}: PAUSED"
    if status.queued:
        return f"{label}: {status.queued} item(s) to go"
    return f"{label}: up to date" + (f" ({detail})" if detail else "")


def _open_log(log_path) -> None:
    if not str(log_path or "").strip():
        log.warning("nothing to open (no path configured)")
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(log_path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            # sanitized env: PYTHONHOME/PYTHON3HOME are pinned at this
            # process's _MEI dir for fusionscript, and must not be inherited
            # by anything we launch (AUDIT_2 CORE-M6).
            subprocess.run(["open", str(log_path)], check=False,
                           env=resolve_bridge.sanitized_child_env())
        else:
            subprocess.run(["xdg-open", str(log_path)], check=False,
                           env=resolve_bridge.sanitized_child_env())
    except Exception:
        log.exception("failed to open %s", log_path)


def _dashboard_url(app: "CompanionApp") -> str:
    return str(getattr(app, "config", {}).get("dashboard_url", "")).strip()


def _open_dashboard(url: str) -> None:
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        log.exception("failed to open dashboard at %s", url)


def _identity_status_label(app: "CompanionApp") -> str:
    identity = getattr(app, "identity", None)
    if identity is not None and identity.valid():
        return f"Signed in as {identity.username}"
    return "NOT SIGNED IN"


def _notify(app: "CompanionApp", msg: str) -> None:
    try:
        app._notify_tray(msg, "ccsync-companion")
    except Exception:
        log.debug("tray notify failed")


def _show_sign_in_dialog(app: "CompanionApp") -> None:
    """Small neon-themed tkinter dialog prompting username + password,
    calling app.sign_in(...) on submit.

    Takes `_popup_active_lock` like every other Tk root in this process.
    These two tray dialogs were the only ones that did NOT -- and the
    failure they hit ("tk.Tk() can raise or wedge Tcl when other Tk roots
    have run on sibling threads in this process", seen live 2026-07-25) is
    precisely the condition that lock exists to prevent (AUDIT_2 CORE-H8).
    """
    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    try:
        _show_sign_in_dialog_locked(app)
    finally:
        if lock is not None:
            lock.release()


def _show_sign_in_dialog_locked(app: "CompanionApp") -> None:
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("sign-in dialog unavailable (%s)", exc)
        _notify(app, "Couldn't open the sign-in window. Restart CCSync and try again.")
        return

    try:
        root = tk.Tk()
    except Exception as exc:
        log.warning("sign-in dialog failed to open (%s)", exc)
        _notify(app, "Couldn't open the sign-in window. Restart CCSync and try again.")
        return
    root.title("CCSYNC.EXE: sign in")
    theme.apply_window_icon(tk, root)
    root.attributes("-topmost", True)
    root.configure(bg=theme.BG, padx=18, pady=14)

    tk.Label(root, text="► SIGN IN", bg=theme.BG, fg=theme.RED,
             font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
    tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
    tk.Label(root, text="Enter your TrueNAS username and password to verify this machine.",
             bg=theme.BG, fg=theme.MUTED, font=theme.mono(9), justify="left", anchor="w",
             wraplength=360).pack(anchor="w", pady=(6, 10))

    form = tk.Frame(root, bg=theme.BG)
    form.pack(anchor="w", fill="x")

    tk.Label(form, text="username:", bg=theme.BG, fg=theme.TEXT, font=theme.mono(10)).grid(
        row=0, column=0, sticky="w", pady=(0, 6))
    username_var = tk.StringVar()
    username_entry = tk.Entry(form, textvariable=username_var, font=theme.mono(10), width=28,
                               bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.RED,
                               relief="flat", highlightthickness=1,
                               highlightbackground=theme.RED_DIM, highlightcolor=theme.RED)
    username_entry.grid(row=0, column=1, sticky="w", pady=(0, 6), padx=(8, 0))

    tk.Label(form, text="password:", bg=theme.BG, fg=theme.TEXT, font=theme.mono(10)).grid(
        row=1, column=0, sticky="w")
    password_var = tk.StringVar()
    password_entry = tk.Entry(form, textvariable=password_var, font=theme.mono(10), width=28,
                               show="*", bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.RED,
                               relief="flat", highlightthickness=1,
                               highlightbackground=theme.RED_DIM, highlightcolor=theme.RED)
    password_entry.grid(row=1, column=1, sticky="w", padx=(8, 0))

    error_label = tk.Label(root, text="", bg=theme.BG, fg=theme.RED, font=theme.mono(9),
                            justify="left", anchor="w", wraplength=360)
    error_label.pack(anchor="w", pady=(8, 0))

    btn_bar = tk.Frame(root, bg=theme.BG)
    btn_bar.pack(anchor="e", pady=(12, 0))

    def _cancel():
        root.destroy()

    def _submit():
        username = username_var.get().strip()
        password = password_var.get()
        if not username or not password:
            error_label.config(text="username and password are both required")
            return
        try:
            ok, error = app.sign_in(username, password)
        except Exception as exc:
            log.exception("sign_in() raised")
            error_label.config(text=f"sign-in failed: {exc}")
            return
        if ok:
            root.destroy()
        else:
            error_label.config(text=error or "sign-in failed")
            password_var.set("")

    theme.neon_button(tk, btn_bar, "CANCEL", _cancel, primary=False).pack(side="left", padx=(0, 18))
    theme.neon_button(tk, btn_bar, "SIGN IN", _submit, primary=True).pack(side="left")
    root.bind("<Return>", lambda _e: _submit())
    root.protocol("WM_DELETE_WINDOW", _cancel)
    username_entry.focus_set()
    root.mainloop()


def _on_sign_out(app: "CompanionApp") -> None:
    try:
        app.sign_out()
    except Exception:
        log.exception("sign_out() failed")


def _show_update_dialog(app: "CompanionApp") -> None:
    """Confirmation dialog for the one-click self-upgrade -- same tkinter
    plumbing as _show_sign_in_dialog, including the popup lock.

    ON DIALOG FAILURE THIS NOW ABORTS. It used to call app.apply_upgrade()
    directly, reasoning that the menu click was consent enough. But the
    dialog's own failure mode is "another Tk root has run on a sibling
    thread" -- i.e. the fixer popup is open, or was this session -- so the
    exact situation that triggered the fallback was the one where applying
    was most destructive: the exe is swapped, request_shutdown() fires, and
    the daemon FIX-ALL thread is killed mid-shutil.copy2 with no dialog ever
    shown to the editor (AUDIT_2 CORE-H8). An update the editor has to click
    twice is strictly better than one that eats an in-flight 60 GB copy.
    """
    try:
        info = app.upgrade_available()
    except Exception:
        log.exception("upgrade_available() failed")
        return
    if info is None:
        return

    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Can't update while a CCSync window is open. Close it and try again.")
        return
    try:
        confirmed = _show_update_dialog_locked(app, info)
    finally:
        if lock is not None:
            lock.release()
    if not confirmed:
        return
    # OUTSIDE the lock on purpose: app.apply_upgrade() refuses to swap the
    # exe while a CCSync window is open, and this dialog is one.
    # apply_upgrade() must also not raise out of this daemon thread -- an
    # escape kills the tray thread to invisible stderr, potentially while
    # the exe has been renamed aside (AUDIT_2 CORE-H7).
    try:
        app.apply_upgrade()
    except Exception:
        log.exception("apply_upgrade() raised")
        _notify(app, f"Update failed. You're still on v{config_mod.VERSION}, nothing is "
                     "broken. Tray → Copy diagnostics for your admin.")


def _show_update_dialog_locked(app: "CompanionApp", info: dict) -> bool:
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("update dialog unavailable (%s) -- NOT applying the update", exc)
        _notify(app, "Couldn't open the update window, so nothing was changed. "
                     "Restart CCSync and try again.")
        return False

    log.info("update dialog: opening for v%s", info.get("version"))
    syncing = False
    try:
        syncing = any(getattr(s, "state", "") == "syncing" for s in app.lane_statuses())
    except Exception:
        pass

    confirmed = {"value": False}
    # The dialog is the LAST thing shown before the exe is swapped, so it has
    # to agree with the menu item that opened it -- an offer of an OLDER
    # build must say so here too (see upgrade.offer_dialog_text).
    title, body, ok_label = upgrade_mod.offer_dialog_text(info["version"])
    heading = "► ROLL BACK COMPANION" if ok_label == "ROLL BACK" else "► UPDATE COMPANION"
    try:
        root = tk.Tk()
        root.title(title)
        theme.apply_window_icon(tk, root)
        root.attributes("-topmost", True)
        root.configure(bg=theme.BG, padx=18, pady=14)

        tk.Label(root, text=heading, bg=theme.BG, fg=theme.RED,
                 font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
        tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
        if syncing:
            body += "\n\nA sync is currently running. It will resume automatically after the restart."
        tk.Label(root, text=body, bg=theme.BG, fg=theme.MUTED, font=theme.mono(9),
                 justify="left", anchor="w", wraplength=360).pack(anchor="w", pady=(6, 10))

        btn_bar = tk.Frame(root, bg=theme.BG)
        btn_bar.pack(anchor="e", pady=(12, 0))

        def _cancel():
            root.destroy()

        def _go():
            confirmed["value"] = True
            root.destroy()

        theme.neon_button(tk, btn_bar, "CANCEL", _cancel, primary=False).pack(side="left", padx=(0, 18))
        theme.neon_button(tk, btn_bar, ok_label, _go, primary=True).pack(side="left")
        root.bind("<Return>", lambda _e: _go())
        root.protocol("WM_DELETE_WINDOW", _cancel)
        root.mainloop()
    except Exception as exc:
        log.warning("update dialog failed (%s) -- NOT applying the update", exc)
        _notify(app, "Couldn't open the update window, so nothing was changed. "
                     "Restart CCSync and try again.")
        return False

    return bool(confirmed["value"])


def _confirm_remove_project(app: "CompanionApp", slug: str, rel: str) -> None:
    """Confirm, then untick + unshare + delete a project's local copy (see
    app.remove_project_from_machine for the ordering guarantees). Runs on a
    tray worker thread; takes the popup lock like every other Tk dialog."""
    from . import popup

    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    try:
        body = (
            "Remove '" + rel + "' from THIS machine?" + "\n\n"
            "This unticks the project on the dashboard, stops syncing it here, "
            "and deletes the local copy to free disk space." + "\n\n"
            "The server's copy is NOT touched, and nothing you uploaded is lost. "
            "If you recently added footage, check the dashboard's TRANSFERS page "
            "shows no pending uploads for this machine first." + "\n\n"
            "Tick the project again any time to sync it back."
        )
        confirmed = popup.confirm_dialog(
            "CCSYNC.EXE: remove project",
            body,
            ok_label="REMOVE FROM THIS MACHINE",
        )
    finally:
        if lock is not None:
            lock.release()
    if not confirmed:
        return
    try:
        ok, message = app.remove_project_from_machine(slug)
    except Exception:
        log.exception("remove_project_from_machine(%s) raised", slug)
        _notify(app, "Remove failed. Tray → Copy diagnostics for your admin.")
        return
    _notify(app, message if ok else f"Remove stopped: {message}")


def _confirm_grade_swap(app: "CompanionApp", to_server: bool) -> None:
    """Confirm, then remap P: (see app.swap_p_to_server/_to_local). Runs on
    a tray worker thread; takes the popup lock like every Tk dialog."""
    from . import popup

    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    try:
        gap = "\n\n"
        if to_server:
            body = (
                "Point P: at the SERVER's tree so Resolve streams full-resolution "
                "originals while you grade?" + gap +
                "Pause playback first. Frames come over the network, so scrubbing "
                "is only as fast as your connection." + gap +
                "In Resolve, set Playback > Proxy Handling > Prefer Camera "
                "Originals to actually use them." + gap +
                "Syncing is not affected. Swap back from this menu when you're done."
            )
            confirmed = popup.confirm_dialog("CCSYNC.EXE: grade from server",
                                             body, ok_label="SWAP P: TO SERVER")
        else:
            body = (
                "Point P: back at this machine's local copy (proxies)?" + gap +
                "Set Resolve's Playback > Proxy Handling back to Prefer Proxies."
            )
            confirmed = popup.confirm_dialog("CCSYNC.EXE: back to proxies",
                                             body, ok_label="SWAP P: BACK")
    finally:
        if lock is not None:
            lock.release()
    if not confirmed:
        return
    try:
        ok, message = (app.swap_p_to_server() if to_server else app.swap_p_to_local())
        if to_server and not ok:
            from . import drive_swap

            if drive_swap.is_auth_failure(message):
                # Windows has no stored login for the server (the normal
                # state on a fresh install). Ask for it and retry -- on
                # success app.swap_p_to_server persists it to Credential
                # Manager, so this dialog appears once per machine.
                creds = _ask_server_credentials(app)
                if creds is None:
                    return  # editor cancelled; P: is already back on local
                ok, message = app.swap_p_to_server(*creds)
    except Exception:
        log.exception("grade swap raised")
        _notify(app, "The P: swap failed. Tray → Copy diagnostics for your admin.")
        return
    _notify(app, message if ok else f"Swap stopped: {message}")


def _ask_server_credentials(app: "CompanionApp") -> Optional[tuple[str, str]]:
    """Username+password dialog for the grade-swap's auth retry: the same
    TrueNAS login the editor signs in to the dashboard with, username
    prefilled from the verified identity. Returns None on cancel. Same Tk
    plumbing and popup lock as _show_sign_in_dialog."""
    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return None
    try:
        return _ask_server_credentials_locked(app)
    finally:
        if lock is not None:
            lock.release()


def _ask_server_credentials_locked(app: "CompanionApp") -> Optional[tuple[str, str]]:
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("credentials dialog unavailable (%s)", exc)
        _notify(app, "Couldn't open the login window. Restart CCSync and try again.")
        return None

    try:
        root = tk.Tk()
    except Exception as exc:
        log.warning("credentials dialog failed to open (%s)", exc)
        _notify(app, "Couldn't open the login window. Restart CCSync and try again.")
        return None
    result: list[Optional[tuple[str, str]]] = [None]
    root.title("CCSYNC.EXE: server login")
    theme.apply_window_icon(tk, root)
    root.attributes("-topmost", True)
    root.configure(bg=theme.BG, padx=18, pady=14)

    tk.Label(root, text="► SERVER LOGIN", bg=theme.BG, fg=theme.RED,
             font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
    tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
    tk.Label(root,
             text=("Windows needs your server login to stream originals. Enter the "
                   "same TrueNAS username and password you sign in with. It is "
                   "saved on this machine, so you'll only be asked once."),
             bg=theme.BG, fg=theme.MUTED, font=theme.mono(9), justify="left", anchor="w",
             wraplength=360).pack(anchor="w", pady=(6, 10))

    form = tk.Frame(root, bg=theme.BG)
    form.pack(anchor="w", fill="x")

    tk.Label(form, text="username:", bg=theme.BG, fg=theme.TEXT, font=theme.mono(10)).grid(
        row=0, column=0, sticky="w", pady=(0, 6))
    username_var = tk.StringVar()
    try:
        username_var.set(app.editor_identity() or "")
    except Exception:
        pass
    username_entry = tk.Entry(form, textvariable=username_var, font=theme.mono(10), width=28,
                               bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.RED,
                               relief="flat", highlightthickness=1,
                               highlightbackground=theme.RED_DIM, highlightcolor=theme.RED)
    username_entry.grid(row=0, column=1, sticky="w", pady=(0, 6), padx=(8, 0))

    tk.Label(form, text="password:", bg=theme.BG, fg=theme.TEXT, font=theme.mono(10)).grid(
        row=1, column=0, sticky="w")
    password_var = tk.StringVar()
    password_entry = tk.Entry(form, textvariable=password_var, font=theme.mono(10), width=28,
                               show="*", bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.RED,
                               relief="flat", highlightthickness=1,
                               highlightbackground=theme.RED_DIM, highlightcolor=theme.RED)
    password_entry.grid(row=1, column=1, sticky="w", padx=(8, 0))

    error_label = tk.Label(root, text="", bg=theme.BG, fg=theme.RED, font=theme.mono(9),
                            justify="left", anchor="w", wraplength=360)
    error_label.pack(anchor="w", pady=(8, 0))

    btn_bar = tk.Frame(root, bg=theme.BG)
    btn_bar.pack(anchor="e", pady=(12, 0))

    def _cancel():
        root.destroy()

    def _submit():
        username = username_var.get().strip()
        if not username or not password_var.get():
            error_label.config(text="username and password are both required")
            return
        result[0] = (username, password_var.get())
        root.destroy()

    theme.neon_button(tk, btn_bar, "CANCEL", _cancel, primary=False).pack(side="left", padx=(0, 18))
    theme.neon_button(tk, btn_bar, "CONNECT", _submit, primary=True).pack(side="left")
    root.bind("<Return>", lambda _e: _submit())
    root.protocol("WM_DELETE_WINDOW", _cancel)
    (password_entry if username_var.get() else username_entry).focus_set()
    root.mainloop()
    return result[0]


def _guarded(app: "CompanionApp", label: str, fn) -> None:
    """Run a tray action, logging anything it raises.

    Every tray callback used to spawn a bare threading.Thread with no
    try/except. consolidate_project in particular is not exception-safe, so
    clicking it could do nothing at all AND leave no log entry -- entirely
    indistinguishable from a dead tray (AUDIT_2 CORE-M9)."""
    try:
        fn()
    except Exception:
        log.exception("tray action %r failed", label)
        _notify(app, f"'{label}' didn't work. Tray → Copy diagnostics for your admin.")


def _spawn(app: "CompanionApp", label: str, fn) -> None:
    threading.Thread(
        target=_guarded, args=(app, label, fn), daemon=True,
        name=f"ccsync-tray-{label[:20]}",
    ).start()


def _sequencer_line(app: "CompanionApp") -> Optional[str]:
    """The sequencer computes exactly the strings an editor needs -- "syncing
    2026/CCT/… (2/5)", "no selection (dashboard unreachable, no cache)" --
    and they appeared in no tray line, no log line and nowhere on the
    dashboard (AUDIT_2 UX-4)."""
    getter = getattr(app, "sequencer_state", None)
    if getter is None:
        return None
    try:
        state, detail = getter()
    except Exception:
        log.exception("sequencer_state() failed")
        return None
    if not state and not detail:
        return None
    return f"Sync queue: {detail or state}"


def _current_project_line(app: "CompanionApp") -> Optional[str]:
    """The tray never said WHICH project was syncing, despite
    LaneStatus.current_project carrying it (AUDIT_2 UX-11)."""
    try:
        for status in app.lane_statuses():
            if status.state == STATE_SYNCING and status.current_project:
                return f"Now syncing: {status.current_project}"
    except Exception:
        log.exception("current-project line failed")
    return None


def _tray_snapshot(app: "CompanionApp") -> dict:
    """Everything the tray renders, gathered ONCE on the refresh thread.

    The menu build used to call app.lane_statuses(), is_paused(),
    upgrade_available() etc. inline -- so any of those stalling (a Syncthing
    config write holds locks for up to 30 s) stalled menu construction, and
    with the win32 backend that can stall the tray's message loop: the
    right-click freeze seen on 2026-07-26. Every getter here is wrapped; a
    failing one degrades to a default instead of taking the tray down."""
    try:
        statuses = app.lane_statuses()
    except Exception:
        log.exception("lane_statuses() failed")
        statuses = []
    snap: dict = {"statuses": statuses}

    def _get(name, fn, default):
        try:
            snap[name] = fn()
        except Exception:
            log.exception("%s failed", name)
            snap[name] = default

    identity = getattr(app, "identity", None)
    _get("signed_in", lambda: identity is not None and identity.valid(), False)
    _get("identity_label", lambda: _identity_status_label(app), "NOT SIGNED IN")
    _get("paused", lambda: bool(app.is_paused()), False)
    _get("problems", lambda: bool(getattr(app, "config_problems", None)), False)
    _get("dashboard_url", lambda: _dashboard_url(app), "")
    _get("sequencer_line", lambda: _sequencer_line(app), None)
    _get("current_project_line", lambda: _current_project_line(app), None)
    _get("setup_name", lambda: (getattr(app, "setup_project_available", None) or (lambda: None))(), None)
    _get("upgrade_info", lambda: (getattr(app, "upgrade_available", None) or (lambda: None))(), None)
    _get("removable", lambda: (getattr(app, "removable_projects", None) or (lambda: []))(), [])
    _get("p_swap_available", lambda: (getattr(app, "p_swap_available", None) or (lambda: False))(), False)
    _get("p_mode", lambda: (getattr(app, "p_mapping_mode", None) or (lambda: "none"))(), "none")
    snap["color"] = compute_overall_color(statuses, app)
    return snap


def _progress_bucket(status: LaneStatus) -> Optional[int]:
    """Tenths of progress for a syncing lane -- the granularity at which a
    menu rebuild is worth the (small) risk of touching a menu the user has
    open. The LIVE numbers move to the tooltip, which is always safe to
    update."""
    if status.state != STATE_SYNCING:
        return None
    if status.bytes_total:
        return int(min(status.bytes_done or 0, status.bytes_total) * 10 // status.bytes_total)
    if status.bytes_done:
        return int(status.bytes_done // (5 << 30))  # 5 GB steps with no known total
    return 0


def _menu_fingerprint(snap: dict) -> tuple:
    """Everything that should trigger a menu REBUILD when it changes.

    Deliberately coarser than the rendered text: pystray's win32 backend
    DestroyMenu()s the live menu handle on every icon.menu assignment, so a
    rebuild while the menu is open freezes it -- and with TPM_RETURNCMD the
    returned index is then resolved against the NEW callback list, i.e. a
    click can fire the WRONG item. Rebuilding only on real state changes
    (not every byte counted) makes that window rare instead of every 5 s."""
    lanes = tuple(
        (s.name, s.state, str(s.detail or ""), str(s.last_error or ""),
         str(s.current_project or ""), bool(s.queued), _progress_bucket(s))
        for s in snap["statuses"]
    )
    return (
        lanes, snap["identity_label"], snap["signed_in"], snap["paused"],
        snap["problems"], snap["sequencer_line"], snap["current_project_line"],
        snap["setup_name"], (snap["upgrade_info"] or {}).get("version"),
        snap["dashboard_url"], snap["color"],
        tuple(sorted(p.get("slug", "") for p in snap.get("removable", []))),
        snap.get("p_swap_available"), snap.get("p_mode"),
    )


def _tooltip_text(snap: dict) -> str:
    """The hover tooltip: the LIVE numbers, updated every refresh (a title
    update is a plain Shell_NotifyIcon NIM_MODIFY -- unlike a menu rebuild
    it can never disturb an open menu). Windows truncates at ~127 chars."""
    if snap["problems"]:
        return "CCSync: NOT SET UP (nothing syncs)"
    if not snap["signed_in"]:
        return "CCSync: not signed in (nothing syncs)"
    if snap["paused"]:
        return "CCSync: PAUSED"
    for status in snap["statuses"]:
        if status.state == STATE_ERROR:
            return f"CCSync: PROBLEM with {lane_label(status.name).split(' (')[0]}"
    for status in snap["statuses"]:
        if status.state == STATE_SYNCING:
            parts = ["CCSync: syncing"]
            if status.current_project:
                parts.append(str(status.current_project)[-40:])
            if status.speed_bps:
                parts.append(f"{human_bytes(int(status.speed_bps))}/s")
            if status.eta_seconds:
                parts.append(f"{human_duration(status.eta_seconds)} left")
            return " · ".join(parts)[:127]
    return "CCSync: up to date"


def _build_menu(app: "CompanionApp", snap: Optional[dict] = None) -> "pystray.Menu":
    if snap is None:
        snap = _tray_snapshot(app)
    statuses = snap["statuses"]
    lane_items = [
        pystray.MenuItem(
            _format_lane_line_from(s, paused=snap["paused"], problems=snap["problems"]),
            None, enabled=False,
        )
        for s in statuses
    ]

    signed_in = snap["signed_in"]

    def on_sync_now(icon, item):
        _spawn(app, "Sync now", app.sync_now)

    def on_scan_whole_project(icon, item):
        _spawn(app, "Scan whole project", app.scan_whole_project)

    def on_consolidate_project(icon, item):
        _spawn(app, "Bring an existing project's media in", app.consolidate_project)

    def on_toggle_pause(icon, item):
        # _spawn, not _guarded: menu callbacks run ON the tray's message
        # loop (win32), and toggle_pause can hold sequencer/Syncthing config
        # writes for many seconds -- the whole tray froze until it returned
        # (seen live 2026-07-26).
        _spawn(app, "Pause/resume", app.toggle_pause)

    def on_open_dashboard(icon, item):
        url = snap["dashboard_url"]
        _spawn(app, "Open dashboard", lambda: _open_dashboard(url))

    def on_open_log(icon, item):
        _spawn(app, "Open log", lambda: _open_log(app.log_path))

    def on_copy_diagnostics(icon, item):
        _spawn(app, "Copy diagnostics for your admin", app.copy_diagnostics)

    def on_open_project_folder(icon, item):
        _spawn(app, "Open my project folder",
               lambda: _open_log(str(app.config.get("local_root", ""))))

    def on_quit(icon, item):
        icon.stop()
        _guarded(app, "Quit", app.shutdown)

    def on_sign_in(icon, item):
        _spawn(app, "Sign in", lambda: _show_sign_in_dialog(app))

    def on_sign_out(icon, item):
        _spawn(app, "Sign out", lambda: _on_sign_out(app))

    def on_update_now(icon, item):
        _spawn(app, "Update now", lambda: _show_update_dialog(app))

    def on_setup_project(icon, item):
        _spawn(app, "Set up project",
               lambda: getattr(app, "setup_current_project", lambda: None)())

    def on_grade_swap(icon, item):
        to_server = snap.get("p_mode") != "server"
        _spawn(app, "Grade swap", lambda: _confirm_grade_swap(app, to_server))

    def on_remove_project(slug, rel):
        def handler(icon, item):
            _spawn(app, "Remove project", lambda: _confirm_remove_project(app, slug, rel))
        return handler

    dashboard_items = (
        [pystray.MenuItem("Open dashboard", on_open_dashboard)]
        if snap["dashboard_url"] else []
    )
    # Present only while the open Resolve project has no server-side root
    # (see project_setup.py) -- clicking opens the /project-setup deep link.
    setup_name = snap["setup_name"]
    setup_items = (
        [pystray.MenuItem(f"Set up '{setup_name}' on the server…", on_setup_project)]
        if setup_name else []
    )
    # Present only while the dashboard advertises a different published
    # version (see upgrade.py) -- the fingerprint-gated rebuild loop makes
    # this appear/disappear, same pattern as dashboard_items above.
    upgrade_info = snap["upgrade_info"]
    # The label is NOT "Update available" unconditionally: the dashboard
    # advertises whatever it publishes as `current`, newer or older (see
    # upgrade.py's "different, not newer"). This rig ran v0.4.5 while the
    # dashboard still published v0.4.3, and the tray offered "Update
    # available → v0.4.3 (install)" -- one click from a silent DOWNGRADE
    # that reintroduced a round of security fixes (seen live 2026-07-25).
    upgrade_items = (
        [pystray.MenuItem(
            upgrade_mod.offer_label(upgrade_info["version"]), on_update_now,
        ), pystray.Menu.SEPARATOR]
        if upgrade_info else []
    )
    identity_items = [
        pystray.MenuItem(snap["identity_label"], None, enabled=False),
        pystray.MenuItem("Sign out", on_sign_out) if signed_in
        else pystray.MenuItem("► Sign in… (nothing syncs until you do)", on_sign_in),
    ]

    problem_items = []
    if snap["problems"]:
        problem_items = [pystray.MenuItem(
            "⚠ NOT SET UP: nothing will sync (Copy diagnostics for your admin)",
            None, enabled=False,
        )]

    state_items = [
        pystray.MenuItem(line, None, enabled=False)
        for line in (snap["sequencer_line"], snap["current_project_line"])
        if line
    ]

    # Order per AUDIT_2 UX-17: who you are, then what is happening, then the
    # things you actually click, and `Update available…` NEVER adjacent to
    # Quit -- it used to sit directly above the one item you must never
    # mis-click. Consolidate/Scan are the two rarest and most dangerous
    # actions, so they move under Advanced.
    return pystray.Menu(
        *identity_items,
        pystray.Menu.SEPARATOR,
        *problem_items,
        *state_items,
        *lane_items,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sync now", on_sync_now),
        pystray.MenuItem(
            "▶ Resume syncing (currently PAUSED)" if snap["paused"] else "⏸ Pause syncing",
            on_toggle_pause, checked=(lambda paused: lambda item: paused)(snap["paused"]),
        ),
        pystray.MenuItem("Open my project folder", on_open_project_folder),
        *([
            pystray.MenuItem(
                "Finish grading: P: back to local proxies"
                if snap.get("p_mode") == "server"
                else "Grade from server originals (swap P:)…",
                on_grade_swap,
            )
        ] if snap.get("p_swap_available") else []),
        *dashboard_items,
        *setup_items,
        pystray.Menu.SEPARATOR,
        *upgrade_items,
        pystray.MenuItem("Copy diagnostics for your admin", on_copy_diagnostics),
        pystray.MenuItem("Open log", on_open_log),
        pystray.MenuItem("Advanced", pystray.Menu(
            pystray.MenuItem("Scan whole project", on_scan_whole_project),
            pystray.MenuItem(
                "Bring an existing project's media into the synced folder…",
                on_consolidate_project,
            ),
            *([pystray.Menu.SEPARATOR] if snap.get("removable") else []),
            *[
                pystray.MenuItem(
                    "Remove '" + proj["rel"].split("/")[-1] + "' from this machine…",
                    on_remove_project(proj["slug"], proj["rel"]),
                )
                for proj in snap.get("removable", [])
            ],
            pystray.MenuItem(f"ccsync-companion v{config_mod.VERSION}", None, enabled=False),
        )),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit CCSync (stops syncing until you next sign in)", on_quit),
    )


def start_tray(app: "CompanionApp", refresh_interval: float = 2.0) -> "pystray.Icon":
    """Start the tray icon on a background thread. Returns the Icon (call
    .stop() to remove it).

    Refresh model (2026-07-26, after the right-click/hover freezes):
      - icon color and TOOLTIP update every `refresh_interval` seconds --
        both are plain Shell_NotifyIcon modifications, safe at any time, and
        the tooltip carries the live speed/ETA numbers;
      - the MENU is rebuilt only when its fingerprint changes. pystray's
        win32 backend DestroyMenu()s the live menu handle on every icon.menu
        assignment, so the old rebuild-every-5s loop could destroy a menu
        the user had open (freeze) and then resolve the clicked index
        against the NEW callback list (wrong action). Rebuilding only on
        real state changes makes that window rare and keeps an open menu
        stable under the cursor."""

    first = _tray_snapshot(app)
    icon = pystray.Icon(
        "ccsync-companion",
        _icon_image_cached(first["color"]),
        _tooltip_text(first),
        menu=_build_menu(app, first),
    )
    guard = _MenuOpenGuard()
    guard.install()
    last_fingerprint = _menu_fingerprint(first)
    last_color = first["color"]
    last_title = _tooltip_text(first)

    def _refresh_loop() -> None:
        nonlocal last_fingerprint, last_color, last_title
        while not getattr(icon, "_ccsync_stop", False):
            try:
                # While the menu is open, touch NOTHING -- re-check on a
                # short interval so updates land right after it closes.
                if guard.is_open():
                    time.sleep(0.25)
                    continue
                snap = _tray_snapshot(app)
                if guard.is_open():
                    # Opened while we were gathering -- drop this tick.
                    time.sleep(0.25)
                    continue
                if snap["color"] != last_color:
                    icon.icon = _icon_image_cached(snap["color"])
                    last_color = snap["color"]
                title = _tooltip_text(snap)
                if title != last_title:
                    icon.title = title
                    last_title = title
                fingerprint = _menu_fingerprint(snap)
                if fingerprint != last_fingerprint:
                    icon.menu = _build_menu(app, snap)
                    last_fingerprint = fingerprint
            except Exception:
                log.exception("tray refresh failed")
            time.sleep(refresh_interval)

    refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    refresh_thread.start()

    # `_ccsync_stop` was read by the loop above and ASSIGNED NOWHERE in the
    # repo, so the 5 s refresh thread outlived icon.stop() and kept calling
    # app.lane_statuses() and assigning icon.menu on a dead icon through the
    # entire shutdown/self-upgrade window (AUDIT_2 §2-low). Wrap stop() so it
    # actually sets the flag.
    original_stop = icon.stop

    def _stop() -> None:
        try:
            icon._ccsync_stop = True
        except Exception:
            pass
        original_stop()

    icon.stop = _stop  # type: ignore[method-assign]

    icon_thread = threading.Thread(target=icon.run, daemon=True)
    icon_thread.start()
    return icon
