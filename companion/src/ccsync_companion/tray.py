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


def _build_menu(app: "CompanionApp") -> "pystray.Menu":
    statuses = app.lane_statuses()
    lane_items = [
        pystray.MenuItem(_format_lane_line(s), None, enabled=False) for s in statuses
    ]

    def on_sync_now(icon, item):
        threading.Thread(target=app.sync_now, daemon=True).start()

    def on_toggle_pause(icon, item):
        app.toggle_pause()

    def on_open_log(icon, item):
        _open_log(app.log_path)

    def on_quit(icon, item):
        icon.stop()
        app.shutdown()

    return pystray.Menu(
        *lane_items,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sync now", on_sync_now),
        pystray.MenuItem(
            "Pause sync", on_toggle_pause, checked=lambda item: app.is_paused()
        ),
        pystray.MenuItem("Open log", on_open_log),
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
