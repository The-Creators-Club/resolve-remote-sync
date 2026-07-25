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
from typing import TYPE_CHECKING

import pystray  # noqa: F401  (raises ImportError here if missing — by design)
from PIL import Image, ImageDraw

from . import config as config_mod
from .sync.base import STATE_ERROR, STATE_SYNCING, LaneStatus

if TYPE_CHECKING:
    from .app import CompanionApp

log = logging.getLogger("ccsync.tray")

from . import theme

COLOR_GREEN = theme.RGB_GREEN
COLOR_ORANGE = theme.RGB_AMBER
COLOR_RED = theme.RGB_RED


def compute_overall_color(statuses: list[LaneStatus]) -> str:
    """green (all OK) / orange (something syncing) / red (any lane error)."""
    if any(s.state == STATE_ERROR for s in statuses):
        return "red"
    if any(s.state == STATE_SYNCING for s in statuses):
        return "orange"
    return "green"


def _color_rgb(color_name: str) -> tuple[int, int, int]:
    return {"green": COLOR_GREEN, "orange": COLOR_ORANGE, "red": COLOR_RED}.get(color_name, COLOR_GREEN)


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


def _format_lane_line(status: LaneStatus) -> str:
    label = status.name.replace("_", " ")
    if status.state == STATE_ERROR:
        return f"{label}: ERROR — {status.last_error}"
    if status.state == STATE_SYNCING:
        return f"{label}: syncing ({status.queued} queued)"
    if status.state == "paused":
        return f"{label}: paused"
    return f"{label}: OK" + (f" ({status.detail})" if status.detail else "")


def _open_log(log_path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(log_path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(log_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(log_path)], check=False)
    except Exception:
        log.exception("failed to open log at %s", log_path)


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


def _show_sign_in_dialog(app: "CompanionApp") -> None:
    """Small neon-themed tkinter dialog prompting username + password,
    calling app.sign_in(...) on submit. Mirrors popup.confirm_dialog's
    plumbing (own Tk root, topmost, falls back to a log warning if no
    display is available). Runs on the tray callback thread -- same
    approach the existing popup dialogs use."""
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("sign-in dialog unavailable (%s)", exc)
        return

    root = tk.Tk()
    root.title("CCSYNC.EXE — sign in")
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
    plumbing as _show_sign_in_dialog. Runs on a tray daemon thread; the
    (blocking) download+swap happens here after the dialog closes."""
    try:
        info = app.upgrade_available()
    except Exception:
        log.exception("upgrade_available() failed")
        return
    if info is None:
        return

    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        # No display for a confirmation -- but the menu click itself was the
        # explicit consent, so proceed rather than strand the update.
        log.warning("update dialog unavailable (%s) -- applying update directly", exc)
        app.apply_upgrade()
        return

    log.info("update dialog: opening for v%s", info.get("version"))
    syncing = False
    try:
        syncing = any(getattr(s, "state", "") == "syncing" for s in app.lane_statuses())
    except Exception:
        pass

    confirmed = {"value": False}
    # The WHOLE dialog is best-effort: tk.Tk() can raise (or wedge Tcl) when
    # other Tk roots have run on sibling threads in this process -- seen
    # live 2026-07-25 as a silent no-op on "Update now" (the daemon thread
    # died to invisible stderr). The menu click is already explicit consent,
    # so any dialog failure falls through to applying the update directly.
    try:
        root = tk.Tk()
        root.title("CCSYNC.EXE — update")
        root.attributes("-topmost", True)
        root.configure(bg=theme.BG, padx=18, pady=14)

        tk.Label(root, text="► UPDATE COMPANION", bg=theme.BG, fg=theme.RED,
                 font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
        tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
        body = f"Update to v{info['version']}? The companion will restart itself."
        if syncing:
            body += "\n\nA sync is currently running — it will resume automatically after the restart."
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
        theme.neon_button(tk, btn_bar, "UPDATE", _go, primary=True).pack(side="left")
        root.bind("<Return>", lambda _e: _go())
        root.protocol("WM_DELETE_WINDOW", _cancel)
        root.mainloop()
    except Exception as exc:
        log.warning("update dialog failed (%s) -- applying update directly", exc)
        app.apply_upgrade()
        return

    if confirmed["value"]:
        app.apply_upgrade()


def _build_menu(app: "CompanionApp") -> "pystray.Menu":
    statuses = app.lane_statuses()
    lane_items = [
        pystray.MenuItem(_format_lane_line(s), None, enabled=False) for s in statuses
    ]

    identity = getattr(app, "identity", None)
    signed_in = identity is not None and identity.valid()

    def on_sync_now(icon, item):
        threading.Thread(target=app.sync_now, daemon=True).start()

    def on_scan_whole_project(icon, item):
        threading.Thread(target=app.scan_whole_project, daemon=True).start()

    def on_consolidate_project(icon, item):
        threading.Thread(target=app.consolidate_project, daemon=True).start()

    def on_toggle_pause(icon, item):
        app.toggle_pause()

    def on_open_dashboard(icon, item):
        _open_dashboard(_dashboard_url(app))

    def on_open_log(icon, item):
        _open_log(app.log_path)

    def on_quit(icon, item):
        icon.stop()
        app.shutdown()

    def on_sign_in(icon, item):
        threading.Thread(target=_show_sign_in_dialog, args=(app,), daemon=True).start()

    def on_sign_out(icon, item):
        threading.Thread(target=_on_sign_out, args=(app,), daemon=True).start()

    def on_update_now(icon, item):
        threading.Thread(target=_show_update_dialog, args=(app,), daemon=True).start()

    def on_setup_project(icon, item):
        threading.Thread(
            target=lambda: getattr(app, "setup_current_project", lambda: None)(),
            daemon=True,
        ).start()

    dashboard_items = (
        [pystray.MenuItem("Open dashboard", on_open_dashboard)]
        if _dashboard_url(app) else []
    )
    # Present only while the open Resolve project has no server-side root
    # (see project_setup.py) -- clicking opens the /project-setup deep link.
    setup_name = None
    try:
        _get_setup = getattr(app, "setup_project_available", None)
        if _get_setup is not None:
            setup_name = _get_setup()
    except Exception:
        log.exception("setup_project_available() failed")
    setup_items = (
        [pystray.MenuItem(f"Set up '{setup_name}' on the server…", on_setup_project)]
        if setup_name else []
    )
    # Present only while the dashboard advertises a different published
    # version (see upgrade.py) -- the 5s menu-rebuild loop makes this
    # appear/disappear live, same pattern as dashboard_items above.
    upgrade_info = None
    try:
        _get_upgrade = getattr(app, "upgrade_available", None)
        if _get_upgrade is not None:
            upgrade_info = _get_upgrade()
    except Exception:
        log.exception("upgrade_available() failed")
    upgrade_items = (
        [pystray.MenuItem(
            f"Update available → v{upgrade_info['version']} — Update now", on_update_now,
        )]
        if upgrade_info else []
    )
    identity_items = [
        pystray.MenuItem(_identity_status_label(app), None, enabled=False),
        pystray.MenuItem("Sign out", on_sign_out) if signed_in
        else pystray.MenuItem("Sign in…", on_sign_in),
    ]

    return pystray.Menu(
        pystray.MenuItem(f"ccsync-companion v{config_mod.VERSION}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        *identity_items,
        pystray.Menu.SEPARATOR,
        *lane_items,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sync now", on_sync_now),
        pystray.MenuItem("Scan whole project", on_scan_whole_project),
        pystray.MenuItem("Consolidate pre-existing project…", on_consolidate_project),
        pystray.MenuItem(
            "Pause sync", on_toggle_pause, checked=lambda item: app.is_paused()
        ),
        *dashboard_items,
        *setup_items,
        pystray.MenuItem("Open log", on_open_log),
        *upgrade_items,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )


def start_tray(app: "CompanionApp", refresh_interval: float = 5.0) -> "pystray.Icon":
    """Start the tray icon on a background thread. Returns the Icon (call
    .stop() to remove it). The icon color is refreshed every
    `refresh_interval` seconds from app.lane_statuses(); the menu is rebuilt
    lazily by pystray each time it's opened (dynamic menu factory)."""

    icon = pystray.Icon(
        "ccsync-companion",
        _make_icon_image(compute_overall_color(app.lane_statuses())),
        "ccsync-companion",
        menu=_build_menu(app),
    )
    # pystray re-evaluates a Menu built from a generator/callable lazily on
    # open in some backends but not all; rebuilding icon.menu on each refresh
    # keeps status lines fresh everywhere.

    def _refresh_loop() -> None:
        while not getattr(icon, "_ccsync_stop", False):
            try:
                statuses = app.lane_statuses()
                icon.icon = _make_icon_image(compute_overall_color(statuses))
                icon.menu = _build_menu(app)
            except Exception:
                log.exception("tray refresh failed")
            time.sleep(refresh_interval)

    refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    refresh_thread.start()

    icon_thread = threading.Thread(target=icon.run, daemon=True)
    icon_thread.start()
    return icon
