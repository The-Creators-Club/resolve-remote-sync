"""System tray icon (tray_native + Pillow) — Component 4 of SPEC.md's
companion app.

Only imported inside a try/except ImportError in app.py's run loop, so the
app still runs headless (console status logging only) if these aren't
installed — same fallback pattern as the b-roll companion's tray.py, which
this app absorbed and retired on 2026-08-10 (its server now lives in
broll_server.py; there is no second tray app any more).

Install with: pip install ccsync-companion[tray]

The backend is `tray_native`, ours, not pystray (2026-08-17,
docs/COMMERCIAL_READINESS.md item 3): pystray is LGPLv3 and this app is frozen
single-file by PyInstaller, which conveys it without the relinking freedom §4
requires — and this file used to monkeypatch its win32 internals besides.
CCSYNC_TRAY_BACKEND=pystray still swaps it back for a dev machine that wants
to A/B a rendering difference; it is inert in the frozen build and pystray is
no longer a dependency, so it does nothing unless someone installs it by hand.
"""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from PIL import Image, ImageDraw  # noqa: F401  (ImportError here is by design)

from . import config as config_mod
from . import proxy_history
from . import reporter as reporter_mod
from . import root_guard as root_guard_mod
from . import resolve_bridge
from . import site as site_mod
from . import ui_copy
from . import ui_dispatch
from . import upgrade as upgrade_mod
from . import ytdl_cookies
from . import ytdl_executor
from . import ytdlp_manager
from .sync.base import STATE_ERROR, STATE_PAUSED, STATE_SYNCING, LaneStatus

if TYPE_CHECKING:
    from .app import CompanionApp

log = logging.getLogger("ccsync.tray")


def _pick_backend():
    """tray_native, or pystray for a developer who explicitly asked.

    The escape hatch is dev-only by construction and says so twice: it refuses
    in a frozen build (sys.frozen), which is the case the LGPL problem was
    ever about, and pystray is not in any dependency list any more, so on a
    machine that has not pip-installed it by hand the variable does nothing.
    """
    if os.environ.get("CCSYNC_TRAY_BACKEND", "").strip().lower() == "pystray":
        if getattr(sys, "frozen", False):
            log.warning("CCSYNC_TRAY_BACKEND=pystray ignored: the frozen build "
                        "does not ship pystray (LGPL — see tray_native.py)")
        else:
            try:
                import pystray  # type: ignore[import-not-found]

                log.warning("using the pystray tray backend (dev escape hatch)")
                return pystray
            except ImportError:
                log.warning("CCSYNC_TRAY_BACKEND=pystray but pystray is not "
                            "installed — falling back to tray_native")
    from . import tray_native

    return tray_native


tray_backend = _pick_backend()

# Re-exported from tray_native, which owns the Win32 half now: these are the
# taskbar-geometry rules item 21 established, and the tests that pin them read
# them here.
from .tray_native import (  # noqa: E402
    _anchor_clear_of_taskbar,
    _clamp_menu_anchor,
    _taskbar_geometry,
)

from . import theme

# Deliberately DARKER than theme.RGB_GREEN / RGB_AMBER: the neon palette is
# tuned for near-black UI panels, but since the borderless mark (2026-08-10)
# the icon sits straight on the taskbar, and Windows' light-grey taskbar
# washed the neon green and amber out. Red is already dark enough to keep.
COLOR_GREEN = (24, 190, 98)
COLOR_ORANGE = (216, 140, 18)
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


def _is_base_rig(app: "CompanionApp") -> bool:
    """Is this machine the base rig -- the one whose local_root IS the NAS
    share, so it has no sync lanes by design?

    EITHER source says so, deliberately. effective_mode() answers with the
    signed-in role, which the dashboard derives from its ADMIN list rather
    than from the machine (api.py's /login): an office machine sitting on the
    NAS whose owner is not an admin is told role="editor" while its own
    config.toml says mode="base" and its lanes are down. Same monotonic
    direction as _apply_identity_role(): a machine that says it does not sync
    stays that way whatever the server says.
    """
    try:
        if str(getattr(app, "config", {}).get("mode", "") or "").strip().lower() == "base":
            return True
    except Exception:
        pass
    try:
        return str(app.effective_mode() or "").strip().lower() == "base"
    except Exception:
        return False


# APP-1 (usability sweep 2026-09-04): which `sync_guard.blocked` reasons mean
# something is BROKEN rather than merely stopped. The three below are the ones
# an editor cannot resolve by looking at the machine: a clock that is out makes
# lane B exit 0 having transferred nothing, a restarted lane and a dead sync
# engine both look exactly like "idle" from every other signal the icon reads.
_BLOCKED_RED_REASONS = frozenset({"clock_skew", "lane_stalled", "syncthing_down"})
# ...and the ones that are vacuously true on the base rig, whose tree IS the
# server tree. Colouring the base rig amber for these would re-open the
# 2026-08-19 owner's call below (a permanent amber teaches the admin to ignore
# amber); every other reason still colours it.
_BLOCKED_BASE_RIG_EXEMPT = frozenset({"no_selection", "folders_unfiltered"})


def compute_overall_color(
    statuses: list[LaneStatus],
    app: "CompanionApp | None" = None,
    guard: Optional[dict] = None,
) -> str:
    """red (any lane error) / orange (not syncing, or syncing) / green.

    GREEN NOW MEANS SOMETHING. It used to mean only "no lane is in the error
    state and none is mid-transfer" -- so a companion that was not signed in,
    was paused, or had sync disabled entirely showed a green icon above three
    lines reading `OK`, which is the universal signal for "everything is
    fine" while literally nothing synced (AUDIT_2 UX-1/UX-2). The icon must
    never be green unless this machine is signed in, unpaused, correctly
    configured and caught up.

    ONE carve-out (2026-08-19): on the base rig "caught up" is vacuously
    true -- see the sync_enabled branch below.

    `guard` is the sync_guard snapshot (APP-1, sweep 2026-09-04). Five things
    used to decide this colour and none of them was the one place that already
    knows why nothing is syncing: a machine whose reporter had been 401'd for a
    week, whose clock was 40 minutes out, or whose lane C engine was dead sat
    at a steady green above a tooltip saying "up to date", with the reason
    reachable only by right-clicking. Optional so the four-arg-free callers in
    the tests and any older caller keep working; absent means "no guard read",
    never "nothing is blocking".
    """
    if any(s.state == STATE_ERROR for s in statuses):
        return "red"
    if app is not None:
        try:
            if getattr(app, "config_problems", None):
                return "red"
            if getattr(app, "_root_absent", False):
                # Orange, not red: nothing is broken and nothing is lost --
                # the drive is out, and plugging it back in resumes sync on
                # its own. Same visual as paused, which is what it is.
                return "orange"
            if not _identity_is_valid(app) and getattr(app, "_require_login", True):
                return "orange"
            if app.is_paused():
                return "orange"
            if not getattr(app, "_sync_enabled", True) and not _is_base_rig(app):
                # "Sync is off" is amber on an EDITOR machine (UX-1 above:
                # nothing arrives and nothing leaves), but on the base rig it
                # is the correct, permanent configuration -- its tree IS the
                # server tree, there is nothing to sync and nothing that could
                # ever catch up. The tooltip has always said "up to date"
                # there; only the icon disagreed, so the one machine the admin
                # looks at all day sat at a steady amber that could never
                # clear and taught them to ignore amber (2026-08-19, owner's
                # call: the base rig is green unless something is wrong).
                return "orange"
        except Exception:
            log.exception("compute_overall_color: app state read failed")
            return "orange"
    # APP-1 (2026-09-04). AFTER the app branches, because every reason those
    # cover (paused, not signed in, drive gone) also appears in _BLOCKED_ORDER
    # and they must not answer twice; BEFORE "a lane is moving bytes", because
    # a blocked machine transferring one leftover file is still blocked.
    blocked_reason = ""
    try:
        blocked = (guard or {}).get("blocked") or {}
        if isinstance(blocked, dict):
            blocked_reason = str(blocked.get("reason") or "")
    except Exception:
        log.exception("compute_overall_color: guard read failed")
        blocked_reason = ""
    if blocked_reason:
        if not (blocked_reason in _BLOCKED_BASE_RIG_EXEMPT
                and app is not None and _is_base_rig(app)):
            return "red" if blocked_reason in _BLOCKED_RED_REASONS else "orange"
    if any(s.state == STATE_SYNCING for s in statuses):
        return "orange"
    return "green"


def should_pulse(color_name: str, statuses: list[LaneStatus]) -> bool:
    """Does the mark BREATHE at this color, or sit still?

    A pulse means exactly two things and nothing else: work is happening
    (amber + a lane mid-transfer) or something is broken (red). Every other
    amber -- paused, signed out, drive unplugged, sync disabled, not set up --
    is STEADY amber, because those are states the editor is already in and
    often chose, and an icon that breathes at them all day is the kind of
    motion people learn to stop seeing. Green NEVER pulses: it is the one
    color that must mean "signed in, unpaused, configured and caught up" and
    nothing about it is in progress (AUDIT_2 UX-1, unchanged by this).
    """
    if color_name == "red":
        return True
    return color_name == "orange" and any(s.state == STATE_SYNCING for s in statuses)


def _color_rgb(color_name: str) -> tuple[int, int, int]:
    return {"green": COLOR_GREEN, "orange": COLOR_ORANGE, "red": COLOR_RED}.get(color_name, COLOR_GREEN)


class _MenuOpenGuard:
    """Answers "is the tray's context menu open RIGHT NOW?"

    The refresh and pulse loops must defer EVERY tray mutation (icon,
    tooltip, menu) while the user is looking at the menu -- mutating any of
    them mid-open is what produced the random hover hangs of 2026-07-26
    (icon/tooltip NIM_MODIFYs force redraws under the cursor, and the old
    backend's menu rebuild DestroyMenu()d the handle being displayed).

    The flag is the PROCESS-WIDE ui_state.menu_open, and it is process-wide
    for a second reason: the menu's highlight repaints run through a Python
    window procedure that needs the GIL, so resolve_bridge defers its
    GIL-holding fusionscript calls while it is set (a single Resolve poll
    froze the hover highlight for a second-plus, 2026-07-26).

    Since 2026-08-17 this class no longer INSTALLS anything -- it used to
    monkeypatch pystray's TrackPopupMenuEx to learn the answer. tray_native's
    Icon sets and clears the very same Event around the popup itself, on
    Windows and (new) on macOS through NSMenu's delegate, so install() is
    kept only because start_tray() and its tests call it.
    """

    def __init__(self) -> None:
        from . import ui_state

        self._open = ui_state.menu_open

    @property
    def flag(self):
        """The Event to hand tray_native.Icon(menu_open_flag=...)."""
        return self._open

    def install(self) -> None:
        return None

    def is_open(self) -> bool:
        return self._open.is_set()


# One rendered image per (color, brightness level) -- regenerating the
# identical 64x64 PIL image (and the win32 HICON the backend derives from it)
# every refresh tick was pure GDI churn, and the pulse below would repeat that
# eight times every three seconds forever. Every frame of every color is
# rendered at most once per process.
_ICON_IMAGE_CACHE: dict = {}

# The tray mark, white-on-transparent so it can be tinted per status. Shipped
# by build.spec's datas; assets/icon.png and icon.ico are the same mark for
# window/exe use and are NOT interchangeable with this one (they are already
# colored and pre-composed).
#
# ONE name for the tray and the window title bar: theme.WINDOW_ICON_ASSET is
# the product's neutral mark, and theme.brand_logo_override() ($CCSYNC_BRAND_
# LOGO) is how a site wears its own instead. Keeping a second literal here is
# how the two ended up differing before (2026-08-17,
# docs/COMMERCIAL_READINESS.md item 10).
MARK_ASSET = theme.WINDOW_ICON_ASSET

# The mark fills the canvas. No tile, no border (2026-08-10, by request): the
# icon IS the mark, silhouette constant, color carrying the status. The mark's
# own canvas is square with the wide logo centered, so it never touches the
# top/bottom edges anyway.
MARK_BOX = 64
MARK_OFFSET = (64 - MARK_BOX) // 2

# The pulse: one breath every ~3 s in 8 steps. Slow and shallow on purpose --
# this sits in a taskbar all day, and anything faster reads as an alarm.
PULSE_PERIOD = 3.0
PULSE_STEPS = 8
PULSE_FLOOR = 0.45      # dimmest frame; with no backing tile the mark sits
                        # straight on the taskbar, so it must never dim to
                        # where it reads as gone rather than breathing


def _pulse_levels(steps: int = PULSE_STEPS, floor: float = PULSE_FLOOR) -> tuple:
    """Mark brightness for each frame of one breath.

    A cosine, not a sawtooth: the turn at each end has to be soft or the
    animation snaps from bright to dim and reads as a flicker. Rounded because
    these are cache keys (see _icon_image_cached) -- equal frames must hash
    equal.
    """
    return tuple(
        round(floor + (1.0 - floor) * (0.5 - 0.5 * math.cos(2 * math.pi * i / steps)), 3)
        for i in range(steps)
    )


PULSE_LEVELS = _pulse_levels()


def _mark_asset_path():
    """Where the tray mark lives in this build, or None. Its own function
    so a test can point it somewhere else (and so the fallback below is
    reachable). theme.window_mark_path() rather than asset_path(MARK_ASSET)
    so a site's $CCSYNC_BRAND_LOGO reaches the tray and the title bar
    together."""
    return theme.window_mark_path()


# Decoded + downscaled once per source path: a 512x512 PNG through LANCZOS is
# milliseconds, but it would otherwise be paid once per pulse frame per color.
_MARK_MASK_CACHE: dict = {}


def _mark_alpha_mask(size: int = MARK_BOX):
    """The mark's alpha channel at `size`x`size`, or None if this build has no
    such asset.

    None is a supported answer, not an error: _make_icon_image falls back to
    the old chevrons. An old frozen build (published before the asset was in
    datas) and a stripped checkout both land here, and the tray coming up
    matters more than what is drawn in it.
    """
    path = _mark_asset_path()
    key = (str(path) if path is not None else None, size)
    if key in _MARK_MASK_CACHE:
        return _MARK_MASK_CACHE[key]
    mask = None
    if path is not None:
        try:
            with Image.open(path) as src:
                mask = (src.convert("RGBA")
                           .resize((size, size), Image.LANCZOS)
                           .getchannel("A"))
        except Exception:
            log.warning("tray mark asset unreadable at %s -- falling back to the "
                        "chevron glyph", path, exc_info=True)
            mask = None
    _MARK_MASK_CACHE[key] = mask
    return mask


def _icon_image_cached(color_name: str, level: float = 1.0):
    key = (color_name, round(float(level), 3))
    image = _ICON_IMAGE_CACHE.get(key)
    if image is None:
        # setdefault, not a plain store: the refresh loop and the pulse ticker
        # both reach for a color's frames the first time it appears, and two
        # threads rendering it at once would leave one of them holding an
        # image the cache does not contain -- i.e. an icon.icon that never
        # compares identical to the cached frame again, and a second render on
        # every subsequent miss. Whoever stores first wins and both callers
        # return THAT object (the loser's image is simply dropped).
        image = _ICON_IMAGE_CACHE.setdefault(key, _make_icon_image(key[0], key[1]))
    return image


def _pulse_frames(color_name: str) -> tuple:
    """One whole breath for `color_name`, every frame already cached."""
    return tuple(_icon_image_cached(color_name, level) for level in PULSE_LEVELS)


def _dim(rgb: tuple, level: float) -> tuple:
    """`rgb` scaled toward black. level is clamped to (0..1]."""
    scale = max(0.0, min(1.0, float(level)))
    return tuple(max(0, min(255, int(round(channel * scale)))) for channel in rgb)


def _make_icon_image(color_name: str, level: float = 1.0):
    """The product mark alone, tinted the status color, on transparency.

    No tile and no border (2026-08-10, by request): the icon IS the mark, the
    silhouette stays constant, and only its color/brightness carries status.
    `level` dims the tint; the alpha channel never changes, so a breathing
    icon reads as the same shape getting quieter, not a shape flickering in
    and out.

    Falls back to the bare chevron glyph when the mark asset is missing; see
    _mark_alpha_mask.
    """
    c = _dim(_color_rgb(color_name), level)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))

    mask = _mark_alpha_mask()
    if mask is None:
        _draw_chevrons(ImageDraw.Draw(img), c)
        return img
    # Tint by pasting a solid color THROUGH the mark's own alpha: the asset is
    # white-on-transparent precisely so this works at any color without
    # touching its anti-aliased edges.
    img.paste(Image.new("RGBA", mask.size, (*c, 255)),
              (MARK_OFFSET, MARK_OFFSET), mask)
    return img


def _draw_chevrons(draw, c: tuple) -> None:
    """The original status glyph (▲ upload over ▼ download, with a soft glow),
    kept as the no-asset fallback."""
    up = [(20, 27), (32, 13), (44, 27)]     # ▲ upload chevron
    down = [(20, 37), (32, 51), (44, 37)]   # ▼ download chevron

    # glow pass: fat translucent strokes under the crisp ones
    for pts in (up, down):
        draw.line(pts, fill=(*c, 70), width=11, joint="curve")
    for pts in (up, down):
        draw.line(pts, fill=(*c, 255), width=5, joint="curve")


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


def drive_absent_phrase(root_state: Any = "") -> str:
    """"drive disconnected" / "the drive is mounted at the wrong place" /
    "the drive is not answering" - the parenthetical every line uses while
    the tree is gone (SYNC-105, sweep 2026-09-04).

    One helper because the editor gets all of them within a second (balloon,
    tray line, tooltip, three lane lines), and on ROOT_MISPLACED five of the
    six said "disconnected" about a drive that is plugged in."""
    text = str(root_state or "")
    if text == root_guard_mod.ROOT_MISPLACED:
        return "the drive is mounted at the wrong place"
    if text == root_guard_mod.ROOT_NOT_ANSWERING:
        return "the drive is not answering"
    return "drive disconnected"


def classify_lane_error(last_error: Optional[str], root_absent: bool = False,
                        root_state: Any = "") -> str:
    """Turn rclone's verbatim stderr tail into something actionable.

    rclone_lane surfaces f"rclone exited {rc}" plus the last 300 chars of
    stderr straight into the tray, which is unreadable and suggests no
    action (AUDIT_2 UX-16). The raw text stays in the log and in
    Copy diagnostics."""
    text = str(last_error or "").lower()
    if root_absent:
        # EVERY lane error means the same thing while the tree is gone, and
        # none of the wordings below is the truth. The one that actively
        # misleads is lane C's marker-missing message: unplugging an external
        # SSD takes every .stfolder with it, so Syncthing reports exactly what
        # it reports when the editor DELETED a project -- and the advice
        # ("untick it on the dashboard") would unshare a project that is
        # perfectly intact, sitting on a drive in the editor's bag. Nothing in
        # here is a reason to act; plugging the drive back in is.
        if str(root_state) == root_guard_mod.ROOT_MISPLACED:
            # SYNC-105: it IS plugged in. "Plug it back in" is advice that
            # reproduces the fault - the empty folder left behind has to go
            # first, which is what the dialog says.
            return (f"{site_mod.drive_phrase(capitalised=True)} is mounted at the "
                    f"wrong place, so syncing is paused. Nothing was deleted. See "
                    f"the CCSync window for what to do.")
        return (f"{site_mod.drive_phrase(capitalised=True)} is disconnected, so "
                f"syncing is paused. Plug it back in and it resumes on its own "
                f"-- nothing was deleted.")
    if not text:
        return f"Something went wrong. {ui_copy.DIAGNOSTICS}."
    if "sync engine" in text:
        # SYNC-17 (2026-08-18): the supervisor's own sentence, already
        # written for an editor ("the sync engine (Syncthing) is not running
        # on this machine -- restarting it"). Passed through verbatim so the
        # tray line, the dashboard chip and the log agree word for word; the
        # generic fallback below turned eighteen hours of a dead sync engine
        # into "Something went wrong".
        return str(last_error)
    if "syncthing not running" in text:
        # The same state seen by a lane built without a supervisor (a bare
        # lane in a test, or a companion whose supervisor failed to
        # construct). Say the same thing, minus the promise to fix it.
        return ("The sync engine (Syncthing) is not running on this machine, so "
                "audio, graphics, subtitles and project files are not syncing. "
                f"Restart this machine, or {ui_copy.DIAGNOSTICS}.")
    if "marker missing" in text:
        # The editor deleted a project's local folder while it was still
        # ticked -- routine when cycling projects, and nothing was lost
        # (the server copy is untouched). Say what to do, not PROBLEM.
        return ("A project folder was deleted on this machine while still ticked. "
                f"Untick it on the dashboard, or use {ui_copy.remove_project()}.")
    if "made no progress" in text or "did not exit" in text:
        # SYNC-104 (sweep 2026-09-04): the SYNC-1 stall watchdog kills the
        # wedged child and writes its own sentence into last_error. No branch
        # matched it, so the lane line said "Something went wrong" while
        # _stalled_line three rows below told the true story. Same words as
        # _stalled_line, per this repo's "the tray line, the chip and the log
        # agree word for word" rule.
        return ("This lane stopped moving and was restarted. If it keeps "
                "happening, check the drive is connected.")
    if any(k in text for k in ("no space", "enospc", "disk full", "not enough space")):
        return "Your disk is full. Free up space and it will resume."
    if any(k in text for k in (
        "permission denied", "auth", "handshake", "publickey", "unable to authenticate",
    )):
        return ("The server rejected this machine's login. "
                f"{ui_copy.DIAGNOSTICS}.")
    if any(k in text for k in (
        "timeout", "timed out", "no route", "connection refused", "connection reset",
        "network", "unreachable", "dial tcp", "lookup", "eof",
    )):
        return "Can't reach the server. Check the Tailscale tray icon is connected."
    return f"Something went wrong. {ui_copy.DIAGNOSTICS}."


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
    root_absent = False
    if app is not None:
        try:
            problems = bool(getattr(app, "config_problems", None))
        except Exception:
            pass
        try:
            paused = bool(app.is_paused())
        except Exception:
            pass
        try:
            root_absent = bool(getattr(app, "_root_absent", False))
        except Exception:
            pass
    return _format_lane_line_from(
        status, paused=paused, problems=problems, root_absent=root_absent
    )


def _format_lane_line_from(
    status: LaneStatus, paused: bool, problems: bool, root_absent: bool = False,
    root_state: Any = "",
) -> str:
    """_format_lane_line with the app state already snapshotted -- what the
    menu build actually uses, so rendering never calls back into app."""
    label = lane_label(status.name)
    # Pause is checked FIRST: no lane ever sets state="paused" (the sequencer
    # owns pause, the lanes don't know), so after clicking Pause all three
    # lines still read as normal (AUDIT_2 UX-2).
    #
    # A disconnected sync drive outranks even the not-set-up line: it is the
    # only state here the editor can fix in five seconds, and calling it
    # "this machine isn't set up" would send them to their admin instead of
    # to the cable.
    if root_absent:
        # SYNC-105: which of the three ways it is gone, not "disconnected"
        # for all of them.
        return f"{label}: PAUSED ({drive_absent_phrase(root_state)})"
    if problems:
        return f"{label}: NOT SYNCING (this machine isn't set up yet)"
    if paused:
        return f"{label}: PAUSED"
    if status.state == STATE_ERROR:
        return (f"{label}: PROBLEM. "
                f"{classify_lane_error(status.last_error, root_absent=root_absent, root_state=root_state)}")
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


def _site_dashboard_url() -> str:
    """The dashboard URL the SITE publishes (GET /api/v1/site ->
    `dashboard_url`), from the cached manifest. It is the address the admin
    says browsers should use -- since the dashboard went https-only
    (DASH_COOKIE_SECURE=1, 2026-08-31) it is the only address a login WORKS
    on, while config.toml's `dashboard_url` stays the reporting address.
    Blank when no manifest is cached or it names no URL; never raises."""
    try:
        from . import site as site_mod

        got = site_mod.cached_site()
        url = str((got or {}).get("dashboard_url", "") or "").strip()
        return url if url.lower().startswith(("http://", "https://")) else ""
    except Exception:
        return ""


def _dashboard_url(app: "CompanionApp") -> str:
    """What "Open dashboard" opens: the site manifest's browse URL when one
    is published, else config.toml's `dashboard_url` exactly as before.
    (2026-08-31: every editor's tray click opened the http reporting
    address and met "this dashboard is configured for https only".)"""
    return (_site_dashboard_url()
            or str(getattr(app, "config", {}).get("dashboard_url", "")).strip())


def _open_dashboard(url: str, app: Optional["CompanionApp"] = None) -> bool:
    """Open the dashboard in the default browser. Returns whether it launched.

    webbrowser.open() returns False -- no exception, no log line -- when no
    browser could be launched, so until 2026-08-16 a click that did nothing
    (an editor: "Open dashboard isn't opening the dashboard") left NOTHING in
    the log to distinguish "the browser opened a tab that then timed out"
    from "nothing was launched at all". Now the attempt and its outcome are
    logged, and a launch failure tells the editor instead of staying silent.
    """
    log.info("tray: opening dashboard %s", url)
    try:
        import webbrowser

        launched = bool(webbrowser.open(url))
    except Exception:
        log.exception("failed to open dashboard at %s", url)
        launched = False
    if not launched:
        log.warning("tray: no browser could be launched for %s", url)
        if app is not None:
            _notify(app, f"Couldn't open a browser. The dashboard is at {url}")
    return launched


def _identity_status_label(app: "CompanionApp") -> str:
    identity = getattr(app, "identity", None)
    if identity is not None and identity.valid():
        return f"Signed in as {identity.username}"
    return "NOT SIGNED IN"


# -- "the icon started, but is anyone seeing it?" (macOS) --------------------
#
# MAC-7. Creating the NSStatusItem succeeds long before anyone sees it, and on
# a full menu bar that is a lie: macOS hands the item a frame in the menu bar
# row and then never draws it, because the space it was given is the notch (or
# the dead zone left of it). Measured on a 16" MBP, menu bar full, screen
# 1728x1117 with the notch spanning x 771..956 -- four items placed at once
# landed on x = 812, 774, 736 and 698, and not one was rendered. The log said
# "tray icon started", the editor saw nothing, and there was no other symptom.
#
# So the companion checks where its own icon actually landed and says so.

PLACEMENT_VISIBLE = "visible"
PLACEMENT_NOTCH = "hidden-notch"
PLACEMENT_OFF_MENU_BAR = "hidden-off-menu-bar"

# A status item that macOS has not placed in the menu bar row at all sits well
# below it (an unplaced item reports y = -37 on a 1117pt screen).
MENU_BAR_BAND = 2.0


def classify_status_item_placement(
    frame: tuple[float, float, float, float],
    screen_height: float,
    notch: Optional[tuple[float, float]] = None,
    menu_bar_height: float = 37.0,
) -> str:
    """Is this status item frame one the editor can actually see?

    `frame` is (x, y, width, height) in AppKit screen coordinates (origin
    bottom-left), `notch` is (left_x, right_x) or None on a notchless Mac.

    Anything at or right of the notch's right edge is in the drawn part of the
    menu bar. Anything to the LEFT of it is not -- including items that clear
    the notch entirely, which is the counter-intuitive part and the reason
    this is a named function with tests rather than an inline `if`.
    """
    _x, y, _w, _h = frame
    if y < screen_height - (MENU_BAR_BAND * menu_bar_height):
        return PLACEMENT_OFF_MENU_BAR
    if notch is not None and _x < notch[1]:
        return PLACEMENT_NOTCH
    return PLACEMENT_VISIBLE


def _darwin_menu_bar_geometry(icon) -> Optional[tuple]:
    """(frame, screen_height, notch) for `icon`'s status item, or None.

    Read-only AppKit access; the caller runs it on the main thread.
    """
    try:
        import AppKit

        item = getattr(icon, "_status_item", None)
        window = item.button().window() if item is not None else None
        if window is None:
            return None
        rect = window.frame()
        frame = (float(rect.origin.x), float(rect.origin.y),
                 float(rect.size.width), float(rect.size.height))
        screen = AppKit.NSScreen.mainScreen()
        screen_height = float(screen.frame().size.height)
        notch = None
        try:
            # macOS 12+, and only on a notched display: the two areas flanking
            # the camera housing. The gap between them IS the notch.
            left = screen.auxiliaryTopLeftArea()
            right = screen.auxiliaryTopRightArea()
            if left is not None and right is not None:
                notch = (float(left.origin.x + left.size.width),
                         float(right.origin.x))
        except Exception:
            notch = None
        return frame, screen_height, notch
    except Exception:
        log.debug("could not read the tray icon's placement", exc_info=True)
        return None


def _report_icon_placement(app: "CompanionApp", icon) -> None:
    """Log (and toast) if the icon macOS just accepted is not being drawn."""
    geometry = _darwin_menu_bar_geometry(icon)
    if geometry is None:
        return
    frame, screen_height, notch = geometry
    placement = classify_status_item_placement(frame, screen_height, notch)
    if placement == PLACEMENT_VISIBLE:
        log.debug("tray icon placed at x=%.0f y=%.0f -- on the drawn menu bar",
                  frame[0], frame[1])
        return
    log.warning(
        "TRAY ICON IS NOT VISIBLE: macOS put it at x=%.0f y=%.0f (%s%s), which it "
        "does not draw. The menu bar is full. Free a slot -- System Settings -> "
        "Control Center, set something to 'Don't Show in Menu Bar', or quit a menu "
        "bar app -- then restart CCSync. Everything else is running normally; only "
        "the icon and its menu are unreachable.",
        frame[0], frame[1], placement,
        "" if notch is None else ", display notch spans x %.0f..%.0f" % notch,
    )
    _notify(app, "CCSync is running, but the menu bar is full so its icon can't be "
                 "shown. Free a menu bar slot and restart CCSync.")


def _schedule_icon_placement_check(app: "CompanionApp", icon, delay: float = 3.0) -> None:
    """Check once, a few seconds in.

    The frame is not final the instant run_detached() returns -- an item reads
    as (0, -37) for the first ~200 ms while macOS is still placing it, so an
    immediate check would report every icon as broken. AppKit is read on the
    main thread through ui_dispatch, like every other AppKit touch here.
    """
    def _check() -> None:
        try:
            ui_dispatch.dispatch(lambda: _report_icon_placement(app, icon))
        except Exception:
            # Shutdown beat us to it, or there is no dispatcher. A diagnostic
            # must never be the thing that takes the companion down.
            log.debug("tray icon placement check did not run", exc_info=True)

    timer = threading.Timer(delay, _check)
    timer.daemon = True
    timer.start()


def _notify(app: "CompanionApp", msg: str) -> None:
    try:
        app._notify_tray(msg, site_mod.notify_title())
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
    """Caller holds the popup lock; ui_dispatch decides WHERE the root gets
    built -- this thread on Windows, the main thread on macOS. The lock stays
    on the caller's side (see _show_sign_in_dialog): dispatch is a transport,
    not a second lock."""
    ui_dispatch.dispatch(lambda: _build_sign_in_dialog(app))


def _build_sign_in_dialog(app: "CompanionApp") -> None:
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
    root.title(site_mod.notify_title("sign in"))
    theme.apply_window_icon(tk, root)
    root.attributes("-topmost", True)
    root.configure(bg=theme.BG, padx=18, pady=14)

    tk.Label(root, text="► SIGN IN", bg=theme.BG, fg=theme.RED,
             font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
    tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
    # APP-10 / SYNC-114 (sweep 2026-09-04): no storage vendor's name in an
    # editor's sentence, and a first-run editor has no other source for
    # where this login comes from - hence the second line.
    tk.Label(root,
             text=(f"Enter the username and password you use to sign in to "
                   f"{site_mod.product_name()}. This verifies that this "
                   f"computer is yours."),
             bg=theme.BG, fg=theme.MUTED, font=theme.mono(9), justify="left", anchor="w",
             wraplength=360).pack(anchor="w", pady=(6, 2))
    tk.Label(root, text="Ask your admin if you do not have one yet.",
             bg=theme.BG, fg=theme.MUTED, font=theme.mono(9), justify="left", anchor="w",
             wraplength=360).pack(anchor="w", pady=(0, 10))

    form = tk.Frame(root, bg=theme.BG)
    form.pack(anchor="w", fill="x")

    tk.Label(form, text="username:", bg=theme.BG, fg=theme.TEXT, font=theme.mono(10)).grid(
        row=0, column=0, sticky="w", pady=(0, 6))
    # master=root, NOT the default root. A Tk variable binds to the
    # interpreter of its master, and on macOS the default root is
    # ui_dispatch's hidden one -- a DIFFERENT interpreter from this dialog.
    # Masterless, the Entry wrote the typed username into this root's PY_VAR0 while
    # .get() read the hidden root's empty PY_VAR0, so a filled-in form
    # failed with "username and password are both required" (MAC-6).
    username_var = tk.StringVar(master=root)
    username_entry = tk.Entry(form, textvariable=username_var, font=theme.mono(10), width=28,
                               bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.RED,
                               relief="flat", highlightthickness=1,
                               highlightbackground=theme.RED_DIM, highlightcolor=theme.RED)
    username_entry.grid(row=0, column=1, sticky="w", pady=(0, 6), padx=(8, 0))

    tk.Label(form, text="password:", bg=theme.BG, fg=theme.TEXT, font=theme.mono(10)).grid(
        row=1, column=0, sticky="w")
    password_var = tk.StringVar(master=root)
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
    ui_dispatch.run_dialog(root)


def _on_sign_out(app: "CompanionApp") -> None:
    try:
        app.sign_out()
    except Exception:
        log.exception("sign_out() failed")


def _youtube_sign_in(app: "CompanionApp", runner: Optional[Any] = None,
                     finder: Optional[Any] = None) -> None:
    """One click: a private browser window on Google's sign-in, and the
    cookies file written for the editor when it completes.

    2026-08-17: replaces "go export a cookies.txt and pick it" as the
    primary path (why OAuth cannot do this, and why a fresh private profile
    is the right shape, is ytdl_browser_login's docstring). The file picker
    is still reachable -- as the fallback when no Chromium browser exists on
    this machine, and under Advanced for the editor who manages their own
    export. `runner`/`finder` are the test seams; the browser flow blocks
    this tray worker thread for as long as the sign-in takes, which is fine:
    _spawn gives every action its own thread and the tray keeps ticking."""
    from . import ytdl_browser_login

    find = finder or ytdl_browser_login.find_browser
    try:
        browser = find()
    except Exception:  # noqa: BLE001
        log.exception("ytdl sign-in: browser discovery failed")
        browser = None
    if browser is None:
        _notify(app, "No Edge/Chrome found for the one-click sign-in: choose an exported "
                     "cookies.txt instead")
        _install_youtube_cookies(app)
        return
    _notify(app, f"{browser.name} is opening. Sign in to YouTube in that window; "
                 "it closes by itself when you're done")
    run = runner or ytdl_browser_login.run
    try:
        outcome = run(browser=browser)
    except Exception:  # noqa: BLE001 -- run() never raises, but the seam might
        log.exception("ytdl sign-in: browser flow crashed")
        # CYT-4: the cookies item is a Settings row now, not an Advanced
        # submenu entry, and the route is ui_copy's to spell.
        _notify(app, "The sign-in window failed unexpectedly. Try "
                     f"{ui_copy.YOUTUBE_COOKIES} instead.")
        return
    if outcome.ok:
        log.info("ytdl sign-in: %d cookies written", outcome.cookies_written)
    _notify(app, outcome.message)


def _install_youtube_cookies(app: "CompanionApp", picker: Optional[Any] = None) -> None:
    """Ask for a cookies.txt and install it for the local YouTube downloader.

    A native file picker, not a themed form: there is nothing to type, only a
    file to choose, and askopenfilename is the one dialog every editor already
    knows. `picker` is the test seam -- it returns a path or "" (cancelled).
    The actual validate-and-copy is ytdl_cookies.install, so this function is
    only the GUI around it and stays out of the test's way.

    bug-hunt-2026-09-03 comp-ui-1: the docstring used to claim there was no Tk
    root here (only "a native modal"), and the code built one six lines below
    it on the tray worker thread -- outside ui_dispatch, so the interpreter was
    pinned for the life of the process (CR-93) and, on macOS, Tk-Aqua was
    touched off the main thread. The picker now goes through
    ui_dispatch.dispatch + release_root like every other root in this package,
    and takes `_popup_active_lock` for the sibling-Tk-root hazard (AUDIT_2
    CORE-H8). No caller holds that lock: both entry points are tray._spawn
    workers (action_youtube_cookies_file, _youtube_sign_in's fallback) and the
    Settings window releases its hold before spawning either."""
    from . import ytdl_cookies

    if picker is None:
        lock = getattr(app, "_popup_active_lock", None)
        if lock is not None and not lock.acquire(blocking=False):
            _notify(app, "Another CCSync window is already open. Close it first.")
            return
        try:
            import tkinter as tk
            from tkinter import filedialog

            def _ask() -> Any:
                root = tk.Tk()
                try:
                    root.withdraw()
                    root.attributes("-topmost", True)
                    return filedialog.askopenfilename(
                        parent=root,
                        title="Choose your exported YouTube cookies.txt",
                        filetypes=[("cookies.txt", "*.txt"), ("All files", "*.*")],
                    )
                finally:
                    ui_dispatch.release_root(root, "the YouTube cookies picker")

            chosen = ui_dispatch.dispatch(_ask)
        except Exception as exc:
            log.warning("youtube cookies: file picker unavailable (%s)", exc)
            _notify(app, "Couldn't open the file chooser. Set ytdl_cookies_file in "
                         "config.toml instead.")
            return
        finally:
            if lock is not None:
                lock.release()
    else:
        chosen = picker()

    if not chosen:
        return  # cancelled
    ok, message = ytdl_cookies.install(chosen)
    _notify(app, message)


def _youtube_warning_line(snap: dict) -> str:
    """The disabled menu line for a dead YouTube session. One string so the
    balloon and the menu never disagree."""
    h = snap.get("ytdl_cookies_health") or {}
    if h.get("status") == ytdl_cookies.STATUS_EXPIRED:
        return "⚠ YouTube sign-in has expired: age-restricted clips will fall back to the server"
    # CR-80 (2026-08-26). A FLAGGED account is not a rotated one and the editor
    # must not be sent to re-export the same session: the cookies still
    # authenticate, YouTube has simply decided it will not play video for them.
    # Downloads keep working (the executor falls back to anonymous, plan WP3),
    # so the line says that rather than reading as an outage.
    if ytdl_cookies.ACCOUNT_FLAG_SIGNATURE in str(h.get("reason") or "").lower():
        return ("⚠ YouTube is refusing your signed-in session: downloads are "
                "continuing without it")
    # CYT-5 (usability sweep 2026-09-04): a stale record with nothing since is
    # a week-old opinion, not news. Cookied downloads are rare (the jar is a
    # fallback since WP3), so this line could otherwise stand for months over
    # a session nobody has tried -- and a warning that never retires is one
    # the editor learns to read past.
    if h.get("aged"):
        stamp = str(h.get("at") or "")[:10]
        return ("YouTube sign-in has not been used since "
                + (stamp or "the last download") + ". Sign in again if you need it")
    return "⚠ YouTube sign-in no longer works (Google rotated the session). Sign in again"


def _maybe_warn_youtube_session(app: "CompanionApp", snap: dict) -> None:
    """Balloon ONCE per transition into stale/expired; the menu line carries
    it after that. Remembered on the app object, not on disk: a restart may
    warn again, and that is fine -- the state is still true."""
    status = (snap.get("ytdl_cookies_health") or {}).get("status")
    bad = status in (ytdl_cookies.STATUS_STALE, ytdl_cookies.STATUS_EXPIRED)
    last = getattr(app, "_yt_session_warned", None)
    if bad and last != status:
        try:
            setattr(app, "_yt_session_warned", status)
        except Exception:  # noqa: BLE001 -- a fake app without __dict__
            pass
        # CYT-4: "tray menu > Sign in to YouTube again" named nothing that
        # exists; the row moved into Settings on 2026-08-27.
        _notify(app, _youtube_warning_line(snap) + f" ({ui_copy.YOUTUBE_SIGN_IN} again)")
    elif not bad and last is not None:
        try:
            setattr(app, "_yt_session_warned", None)
        except Exception:  # noqa: BLE001
            pass


def _ytdl_attested(app: "CompanionApp") -> bool:
    """Has the signed-in editor accepted the download terms on this machine?

    Never raises: the tray snapshot is built on the refresh thread and a
    missing state dir must cost a tick mark, not the menu."""
    from . import ytdl_attestation

    try:
        who = getattr(app, "editor_identity", lambda: None)()
        return ytdl_attestation.accepted(who)
    except Exception:
        log.debug("ytdl attestation state unreadable", exc_info=True)
        return False


def _show_youtube_terms_dialog(app: "CompanionApp", confirm=None) -> None:
    """Show the rights/ToS notice and record acceptance on THIS machine.

    COMMERCIAL_READINESS.md item 2 (2026-08-17). The web UI records the
    editor's acceptance server-side and gates the browser; this is the
    per-machine half, and it is what the local executor's capability probe
    reads (ytdl_executor.REASON_NOT_ATTESTED). An editor who never opens this
    still gets their clips -- the server downloads them, which is the designed
    fallback -- so the failure mode of ignoring it is slowness, not breakage.

    askokcancel, not a themed form: there is nothing to type, and the native
    modal is the one dialog every editor already knows. `confirm` is the test
    seam and returns True/False.

    bug-hunt-2026-09-03 comp-ui-1: askokcancel needs a parent, and the parent
    built here IS one of this process's Tk roots -- the old docstring said
    otherwise. It goes through ui_dispatch + release_root and takes
    `_popup_active_lock`, for the reasons in _install_youtube_cookies.
    """
    from . import ytdl_attestation

    who = getattr(app, "editor_identity", lambda: None)()
    if not str(who or "").strip():
        _notify(app, "Sign in first: the record has to say who accepted "
                     "these terms.")
        return

    if ytdl_attestation.accepted(who):
        _notify(app, f"You already accepted the YouTube terms "
                     f"({ytdl_attestation.TEXT_VERSION}) on this machine.")
        return

    body = f"{ytdl_attestation.NOTICE_TEXT}\n\nAccepting as: {who}"
    if confirm is None:
        lock = getattr(app, "_popup_active_lock", None)
        if lock is not None and not lock.acquire(blocking=False):
            _notify(app, "Another CCSync window is already open. Close it first.")
            return
        try:
            import tkinter as tk
            from tkinter import messagebox

            def _ask() -> Any:
                root = tk.Tk()
                try:
                    root.withdraw()
                    root.attributes("-topmost", True)
                    return messagebox.askokcancel(
                        ytdl_attestation.TITLE, body, parent=root, icon="warning",
                        default="cancel")
                finally:
                    ui_dispatch.release_root(root, "the YouTube terms dialog")

            agreed = ui_dispatch.dispatch(_ask)
        except Exception as exc:
            # NO FALLBACK TO "ACCEPT". A dialog that could not be shown is a
            # notice nobody read, and recording agreement to text that was
            # never displayed is the one outcome this feature must not have.
            log.warning("youtube terms: dialog unavailable (%s)", exc)
            _notify(app, "Couldn't show the YouTube terms. Open the "
                         "downloader in the dashboard and accept them there.")
            return
        finally:
            if lock is not None:
                lock.release()
    else:
        agreed = bool(confirm(ytdl_attestation.TITLE, body))

    if not agreed:
        return
    _ok, message = ytdl_attestation.accept(who)
    # The menu picks the tick up on its next refresh tick, the same way
    # _install_youtube_cookies' state does -- there is no push here and adding
    # one would mean a tray redraw from a dialog thread.
    _notify(app, message)


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
                     f"broken. {ui_copy.DIAGNOSTICS}.")


def _show_update_dialog_locked(app: "CompanionApp", info: dict) -> bool:
    """Caller holds the popup lock (see _show_update_dialog); ui_dispatch
    only decides which thread builds the root -- this one on Windows, the
    main one on macOS."""
    return ui_dispatch.dispatch(lambda: _build_update_dialog(app, info))


def _build_update_dialog(app: "CompanionApp", info: dict) -> bool:
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
        ui_dispatch.run_dialog(root)
    except Exception as exc:
        log.warning("update dialog failed (%s) -- NOT applying the update", exc)
        _notify(app, "Couldn't open the update window, so nothing was changed. "
                     "Restart CCSync and try again.")
        return False

    return bool(confirmed["value"])


def show_scripting_warning(app: "CompanionApp") -> bool:
    """Warn that Resolve is open but not accepting scripting connections.

    Driven by app._maybe_warn_scripting_dead on a timer, NOT by a menu click
    -- the only dialog in this file the editor did not ask for. That is
    deliberate: it is the one failure they cannot see (Resolve looks fine;
    every companion feature that needs it is dead) and the one that does not
    heal on its own.

    Returns True if the editor asked to stop being warned. Never raises: a
    warning that takes the tray thread down would cost more than the state
    it is warning about.
    """
    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        # Another CCSync window owns Tk (the fixer, an update offer). Say it
        # in the tray and let the next interval try again -- this warning
        # repeats by design, so a skipped round costs nothing, while queueing
        # it would drop a stale nag on screen minutes after the fact.
        log.info("scripting warning: another CCSync window is open -- notifying instead")
        _notify(app, resolve_bridge.NO_SCRIPTING_MESSAGE)
        return False
    try:
        return _show_scripting_warning_locked(app)
    finally:
        if lock is not None:
            lock.release()


def _show_scripting_warning_locked(app: "CompanionApp") -> bool:
    """Caller holds the popup lock (see show_scripting_warning); ui_dispatch
    only decides which thread builds the root."""
    return bool(ui_dispatch.dispatch(lambda: _build_scripting_warning_dialog(app)))


def _build_scripting_warning_dialog(app: "CompanionApp") -> bool:
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("scripting warning dialog unavailable (%s) -- notifying instead", exc)
        _notify(app, resolve_bridge.NO_SCRIPTING_MESSAGE)
        return False

    silenced = {"value": False}
    body = (
        resolve_bridge.NO_SCRIPTING_MESSAGE + "\n\n"
        "Until then CCSync can't see your timeline, so it can't warn you about "
        "media outside your project folder, attach proxies, or send b-roll, "
        "music and YouTube clips to Resolve. Your files and your sync are not "
        "affected." + "\n\n"
        "Save your work first -- nothing here is urgent enough to lose a take over."
    )
    try:
        root = tk.Tk()
        root.title(site_mod.notify_title("Resolve scripting is down"))
        theme.apply_window_icon(tk, root)
        root.attributes("-topmost", True)
        root.configure(bg=theme.BG, padx=18, pady=14)

        tk.Label(root, text="► RESOLVE SCRIPTING IS DOWN", bg=theme.BG, fg=theme.RED,
                 font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
        tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
        tk.Label(root, text=body, bg=theme.BG, fg=theme.MUTED, font=theme.mono(9),
                 justify="left", anchor="w", wraplength=360).pack(anchor="w", pady=(6, 10))

        btn_bar = tk.Frame(root, bg=theme.BG)
        btn_bar.pack(anchor="e", pady=(12, 0))

        def _dismiss():
            root.destroy()

        def _silence():
            silenced["value"] = True
            root.destroy()

        # OK is the primary button, not "stop warning me": the action this
        # dialog wants is the restart, and an editor who cannot do it right
        # now should have to reach past the default to switch the warning off.
        theme.neon_button(tk, btn_bar, "STOP WARNING ME", _silence, primary=False).pack(
            side="left", padx=(0, 18))
        theme.neon_button(tk, btn_bar, "OK", _dismiss, primary=True).pack(side="left")
        root.bind("<Return>", lambda _e: _dismiss())
        root.protocol("WM_DELETE_WINDOW", _dismiss)
        ui_dispatch.run_dialog(root)
    except Exception as exc:
        log.warning("scripting warning dialog failed (%s) -- notifying instead", exc)
        _notify(app, resolve_bridge.NO_SCRIPTING_MESSAGE)
        return False

    return bool(silenced["value"])


def remove_blocker_body(rel: str, blockers: dict) -> str:
    """The dialog body for a removal the caught-up gate is refusing.

    Its own function so the wording is testable without Tk: what makes this
    dialog safe is that it NAMES what is still pending, and until item 9 the
    old one merely told the editor to go and check the dashboard themselves
    (2026-08-17)."""
    reasons = "\n".join(f"  · {r}" for r in (blockers.get("reasons") or []))
    return (
        f"'{rel}' is NOT ready to be removed.\n\n"
        f"{reasons}\n\n"
        "Deleting it now would destroy work that exists nowhere else. Leave CCSync "
        "running until this finishes, then try again.\n\n"
        "If you have to delete it anyway (a dead server, a full disk), type the "
        "project's folder name exactly to confirm:\n"
        f"    {rel.split('/')[-1]}"
    )


def _confirm_remove_project(app: "CompanionApp", slug: str, rel: str) -> None:
    """Confirm, then untick + unshare + delete a project's local copy (see
    app.remove_project_from_machine for the ordering guarantees). Runs on a
    tray worker thread; takes the popup lock like every other Tk dialog.

    Since 2026-08-17 (COMMERCIAL_READINESS.md item 9) this asks the app FIRST
    whether the project is caught up, and a project that is not can only be
    removed by typing its folder name -- the gate is in
    app.remove_project_from_machine, and this is the UI half of it."""
    from . import popup

    # The probe costs a remote listing, so say so before the menu appears to
    # do nothing for several seconds. The gate is checked AGAIN inside
    # remove_project_from_machine -- deliberately, not redundantly: an
    # editor can leave this dialog open for an hour, and what matters is
    # whether the project is caught up at the moment of the rmtree.
    _notify(app, "Checking whether this project's files have reached the server…")
    try:
        blockers = app.removal_blockers(slug)
    except Exception:
        log.exception("removal_blockers(%s) raised", slug)
        # Fails CLOSED, like the gate itself: a probe that raised tells us
        # nothing, and "nothing" is not "safe to delete".
        blockers = {"blocked": True, "reasons": ["CCSync could not check whether "
                                                 "your work has been uploaded"]}

    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    override = False
    try:
        if blockers.get("blocked"):
            typed = _ask_typed_confirmation_locked(
                app, site_mod.notify_title("project not ready to remove"),
                remove_blocker_body(rel, blockers), rel.split("/")[-1],
            )
            confirmed = typed
            override = bool(typed)
        else:
            body = (
                "Remove '" + rel + "' from THIS machine?" + "\n\n"
                "This unticks the project on the dashboard, stops syncing it here, "
                "and deletes the local copy to free disk space." + "\n\n"
                "CCSync has checked: everything on this machine has reached the "
                "server, so nothing will be lost." + "\n\n"
                "Tick the project again any time to sync it back."
            )
            confirmed = popup.confirm_dialog(
                site_mod.notify_title("remove project"),
                body,
                ok_label="REMOVE FROM THIS MACHINE",
            )
    finally:
        if lock is not None:
            lock.release()
    if not confirmed:
        return
    try:
        ok, message = app.remove_project_from_machine(slug, override=override)
    except Exception:
        log.exception("remove_project_from_machine(%s) raised", slug)
        _notify(app, f"Remove failed. {ui_copy.DIAGNOSTICS}.")
        return
    _notify(app, message if ok else f"Remove stopped: {message}")


def _ask_typed_confirmation_locked(
    app: "CompanionApp", title: str, body: str, expected: str
) -> bool:
    """Type-the-name confirmation. Caller holds the popup lock.

    Not popup.confirm_dialog with scarier wording: this dialog exists for the
    one action in the companion that destroys footage stored nowhere else, and
    a button is a button however it is labelled. Same Tk plumbing as
    _build_credentials_dialog."""
    return bool(ui_dispatch.dispatch(
        lambda: _build_typed_confirmation(app, title, body, expected)
    ))


def _build_typed_confirmation(
    app: "CompanionApp", title: str, body: str, expected: str
) -> bool:
    try:
        import tkinter as tk

        from . import theme
    except Exception as exc:
        log.warning("typed-confirmation dialog unavailable (%s)", exc)
        return False
    try:
        root = tk.Tk()
    except Exception as exc:
        log.warning("typed-confirmation dialog failed to open (%s)", exc)
        return False
    result = {"ok": False}
    root.title(title)
    theme.apply_window_icon(tk, root)
    root.attributes("-topmost", True)
    root.configure(bg=theme.BG, padx=18, pady=14)

    tk.Label(root, text=f"► {title}", bg=theme.BG, fg=theme.RED,
             font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
    tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
    tk.Label(root, text=body, bg=theme.BG, fg=theme.TEXT, font=theme.mono(10),
             justify="left", anchor="w", wraplength=520).pack(anchor="w", pady=(6, 10))

    typed_var = tk.StringVar(master=root)
    entry = tk.Entry(root, textvariable=typed_var, font=theme.mono(10), width=40,
                     bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.RED,
                     relief="flat", highlightthickness=1,
                     highlightbackground=theme.RED_DIM, highlightcolor=theme.RED)
    entry.pack(anchor="w")
    error_label = tk.Label(root, text="", bg=theme.BG, fg=theme.RED, font=theme.mono(9),
                           justify="left", anchor="w", wraplength=520)
    error_label.pack(anchor="w", pady=(8, 0))

    btn_bar = tk.Frame(root, bg=theme.BG)
    btn_bar.pack(anchor="e", pady=(12, 0))

    def _cancel():
        root.destroy()

    def _submit():
        if typed_var.get().strip() != expected:
            error_label.config(text=f"type exactly: {expected}")
            return
        result["ok"] = True
        root.destroy()

    theme.neon_button(tk, btn_bar, "CANCEL", _cancel, primary=False).pack(side="left", padx=(0, 18))
    theme.neon_button(tk, btn_bar, "DELETE ANYWAY", _submit, primary=True).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", _cancel)
    entry.focus_set()
    ui_dispatch.run_dialog(root)
    return result["ok"]


def _confirm_resume_disk_floor(app: "CompanionApp", reason: str) -> None:
    """Confirm, then clear the free-space park (SYS-5 / SYNC-7, resilience
    sweep 2026-08-28).

    Still a confirmation and not a bare action: the park exists because the
    drive is nearly full, and resuming without making room means rclone
    failing per file with ENOSPC, which is the noisy state the park replaced.
    It says what the automatic clear is, so an editor who has already deleted
    something knows they need not click at all."""
    from . import popup

    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    try:
        confirmed = popup.confirm_dialog(
            site_mod.notify_title("resume proxy download"),
            "CCSync stopped downloading proxies because:\n\n"
            f"  {reason}\n\n"
            "Your uploads never stopped. Proxy download starts again on its own as "
            "soon as there is enough room, so you only need this if you have just "
            "made space and do not want to wait.",
            ok_label="RESUME PROXY DOWNLOAD",
        )
    finally:
        if lock is not None:
            lock.release()
    if not confirmed:
        return
    ok, message = app.resume_lane_b()
    _notify(app, message if ok else f"Nothing to resume: {message}")


def _confirm_resume_lane_b(app: "CompanionApp", snap: dict) -> None:
    """Confirm, then clear the lane B breaker (item 9, 2026-08-17).

    A confirmation and not a bare action: resuming is the operator asserting
    that the server is in a state worth syncing FROM, which is the exact
    judgement the breaker could not make itself."""
    from . import popup

    guard = snap.get("sync_guard") or {}
    breaker = guard.get("lane_b_breaker") or {}
    floor = guard.get("disk_floor") or {}
    # The same button clears either park (SYS-5 / SYNC-7, resilience sweep
    # 2026-08-28), and the two need different words: the breaker's dialog asks
    # the editor to assert something about the SERVER, which is exactly the
    # wrong question to put in front of somebody whose disk is full.
    if not breaker.get("tripped") and floor.get("parked"):
        _confirm_resume_disk_floor(app, str(floor.get("reason") or "this drive is nearly full"))
        return
    reason = str(breaker.get("reason") or "a safety check failed")
    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    try:
        confirmed = popup.confirm_dialog(
            site_mod.notify_title("resume proxy download"),
            "CCSync stopped downloading proxies because:\n\n"
            f"  {reason}\n\n"
            "Only resume once your admin has confirmed the server is healthy. If it "
            "is not, resuming will move more of your local proxies into "
            ".ccsync-trash (they stay recoverable, but you will not see them in "
            "Resolve).",
            ok_label="RESUME PROXY DOWNLOAD",
        )
    finally:
        if lock is not None:
            lock.release()
    if not confirmed:
        return
    ok, message = app.resume_lane_b()
    _notify(app, message if ok else f"Nothing to resume: {message}")


def _confirm_halt(app: "CompanionApp") -> None:
    """Confirm, then STOP everything -- lanes A and B and every lane C folder
    (item 9). The dialog has to spell out how this differs from Pause, since
    the two items sit in the same menu."""
    from . import popup

    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    try:
        confirmed = popup.confirm_dialog(
            site_mod.notify_title("stop all syncing"),
            "Stop ALL syncing on this machine?\n\n"
            "This is stronger than Pause: uploads, proxy downloads AND the shared "
            "project files (Syncthing) all stop, and they STAY stopped after a "
            "restart until you start them again from the tray menu "
            "(Start syncing again).\n\n"
            "Nothing is deleted. Use this when something looks wrong and you want "
            "the files to stop moving.",
            ok_label="STOP ALL SYNCING",
        )
    finally:
        if lock is not None:
            lock.release()
    if not confirmed:
        return
    ok, message = app.halt_all_sync("stopped from the tray on this machine")
    _notify(app, message if ok else f"Could not stop syncing: {message}")


def _release_halt(app: "CompanionApp") -> None:
    ok, message = app.release_halt(by="tray")
    _notify(app, message)


def _canonical_letter(app: "CompanionApp") -> str:
    """This site's sync drive letter, for a sentence that needs a letter
    (SYNC-103). Defaults to P: exactly as app.canonical_drive_letter() does:
    every machine in the field is on it, and a dialog is not the place to
    discover that the manifest cannot be read."""
    try:
        return str(app.canonical_drive_letter() or "P:")
    except Exception:
        log.debug("could not read this site's drive letter", exc_info=True)
        return "P:"


def _confirm_grade_swap(app: "CompanionApp", to_server: bool) -> None:
    """Confirm, then remap P: (see app.swap_p_to_server/_to_local). Runs on
    a tray worker thread; takes the popup lock like every Tk dialog."""
    from . import popup

    lock = getattr(app, "_popup_active_lock", None)
    if lock is not None and not lock.acquire(blocking=False):
        _notify(app, "Another CCSync window is already open. Close it first.")
        return
    # SYNC-103 (sweep 2026-09-04), dialog half: the letter is site data, so a
    # second customer on Q: reads about Q:. canonical_drive_letter(), not
    # canonical_prefix_label(): this dialog is about a Windows drive letter,
    # and "swap your media drive to the server" would be a sentence about
    # nothing. The behaviour half (drive_swap taking the letter) is already in.
    letter = _canonical_letter(app)
    try:
        gap = "\n\n"
        if to_server:
            body = (
                f"Point {letter} at the SERVER's tree so Resolve streams "
                "full-resolution originals while you grade?" + gap +
                "Pause playback first. Frames come over the network, so scrubbing "
                "is only as fast as your connection." + gap +
                "In Resolve, set Playback > Proxy Handling > Prefer Camera "
                "Originals to actually use them." + gap +
                "Syncing is not affected. Swap back when you are done: "
                f"{ui_copy.finish_grading(letter)}."
            )
            confirmed = popup.confirm_dialog(site_mod.notify_title("grade from server"),
                                             body, ok_label=f"SWAP {letter} TO SERVER")
        else:
            body = (
                f"Point {letter} back at this machine's local copy (proxies)?" + gap +
                "Set Resolve's Playback > Proxy Handling back to Prefer Proxies."
            )
            confirmed = popup.confirm_dialog(site_mod.notify_title("back to proxies"),
                                             body, ok_label=f"SWAP {letter} BACK")
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
        _notify(app, f"The {letter} swap failed. {ui_copy.DIAGNOSTICS}.")
        return
    _notify(app, message if ok else f"Swap stopped: {message}")


def _ask_server_credentials(app: "CompanionApp") -> Optional[tuple[str, str]]:
    """Username+password dialog for the grade-swap's auth retry: the same
    server login the editor signs in to the dashboard with, username
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
    """Caller holds the popup lock (see _ask_server_credentials); ui_dispatch
    only decides which thread builds the root."""
    return ui_dispatch.dispatch(lambda: _build_credentials_dialog(app))


def _build_credentials_dialog(app: "CompanionApp") -> Optional[tuple[str, str]]:
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
    root.title(site_mod.notify_title("server login"))
    theme.apply_window_icon(tk, root)
    root.attributes("-topmost", True)
    root.configure(bg=theme.BG, padx=18, pady=14)

    tk.Label(root, text="► SERVER LOGIN", bg=theme.BG, fg=theme.RED,
             font=theme.mono(12, bold=True), justify="left", anchor="w").pack(anchor="w")
    tk.Label(root, text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM).pack(anchor="w")
    # APP-10 / SYNC-114: the server has whatever name the site manifest gives
    # it, and "the server" when it gives it none.
    tk.Label(root,
             text=(f"Windows needs your login for {site_mod.server_phrase()} to "
                   f"stream originals. Use the same username and password you "
                   f"sign in to {site_mod.product_name()} with. It is saved on "
                   f"this computer, so you will only be asked once."),
             bg=theme.BG, fg=theme.MUTED, font=theme.mono(9), justify="left", anchor="w",
             wraplength=360).pack(anchor="w", pady=(6, 10))

    form = tk.Frame(root, bg=theme.BG)
    form.pack(anchor="w", fill="x")

    tk.Label(form, text="username:", bg=theme.BG, fg=theme.TEXT, font=theme.mono(10)).grid(
        row=0, column=0, sticky="w", pady=(0, 6))
    username_var = tk.StringVar(master=root)   # see _build_sign_in_dialog
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
    password_var = tk.StringVar(master=root)   # see _build_sign_in_dialog
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
    ui_dispatch.run_dialog(root)
    return result[0]


def quit_confirm_text(copying: dict) -> str:
    """The sentence Quit shows while a FIX ALL copy is running (RES-8).

    A function of its own so the wording is testable without a display, and
    so both platforms say the same thing."""
    index = int(copying.get("index") or 0)
    total = int(copying.get("total") or 0)
    where = "of {0} file(s) into your synced folder".format(total) if total else "files in"
    counted = f"CCSync is copying file {index} {where}." if index else \
        f"CCSync is copying {total or 'some'} file(s) into your synced folder."
    return (counted + "\n\n"
            "Quitting now abandons the file it is on. The rest of the batch is not "
            "copied and Resolve is not repointed at it.\n\n"
            "Quit anyway?")


def _confirm_quit_while_copying(app: "CompanionApp") -> bool:
    """True when Quit may go ahead (RES-8, usability sweep 2026-09-04).

    Quit used to tear the process down mid-write(), leaving a multi-GB
    .ccsync-tmp that is reported an hour later, never deleted, with no
    filename and nothing the editor can do; if the kill lands between
    os.replace and ReplaceClip the copy exists and Resolve still points at
    the original.

    A NATIVE message box, not popup.confirm_dialog: the FIX ALL window is a
    live Tk root on ANOTHER thread and a second root in this process is the
    CORE-M3/CR-93 shape. Fails OPEN -- a Quit that silently does nothing is
    the worse bug, and the editor can always kill the process anyway.
    """
    from . import popup

    try:
        copying = popup.copy_in_progress()
    except Exception:
        log.exception("quit: could not read the copy state")
        return True
    if not copying:
        return True
    body = quit_confirm_text(copying)
    try:
        if sys.platform == "win32":
            import ctypes

            # MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
            answer = ctypes.windll.user32.MessageBoxW(
                None, body + "\n\n[ Yes ] quits. [ No ] keeps copying.", "CCSync",
                0x00000004 | 0x00000030 | 0x00010000 | 0x00040000,
            )
            return int(answer) == 6  # IDYES
        if sys.platform == "darwin":
            script = (
                'display alert "CCSync is still copying" message '
                + json.dumps(body)
                + ' buttons {"Quit anyway", "Keep copying"} '
                'default button "Keep copying" as critical'
            )
            proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
                ["/usr/bin/osascript", "-e", script],
                capture_output=True, text=True, timeout=120, check=False,
            )
            return "Quit anyway" in (proc.stdout or "")
    except Exception:
        log.exception("quit: could not ask about the copy in flight")
        return True
    return True


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
        _notify(app, f"'{label}' didn't work. {ui_copy.DIAGNOSTICS}.")


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


def _sync_line(snap: dict) -> str:
    """The one line "what is syncing" summary the reduced menu shows in place
    of the three lane lines + six advisory lines it used to carry
    (2026-08-27, the Settings-window split -- see settings_window.py). A
    glance at the tray gets ONE sentence; the detail that used to live in
    those lines moved to Settings, which is the click away that answers WHY.

    Priority order mirrors compute_overall_color()'s own hierarchy: a halt
    outranks a tripped breaker, which outranks "not set up", which outranks a
    disconnected drive, which outranks a plain pause, which outranks actually
    moving bytes, which outranks files merely queued.

    Takes the SNAPSHOT, not `app`, like _halt_line/_breaker_line beside it --
    this runs on every render and a snapshot read can never stall the way an
    app getter can (see _tray_snapshot's own docstring). Always returns a
    non-empty string -- unlike _sequencer_line/_current_project_line, "Sync:"
    is not a conditional line, it is the line.
    """
    guard = snap.get("sync_guard") or {}
    halt = guard.get("halt") or {}
    if halt.get("active"):
        return ("Sync: stopped by your admin" if halt.get("scope") == "fleet"
                else "Sync: stopped on this machine")
    if (guard.get("lane_b_breaker") or {}).get("tripped"):
        return "Sync: proxy download stopped (see Settings)"
    if snap.get("problems") or snap.get("eula_problem"):
        return "Sync: not set up yet"
    if snap.get("root_absent"):
        # SYNC-2 (resilience sweep 2026-08-28): a drive that is plugged in and
        # not answering is not "disconnected", and telling the editor it is
        # sends them to check a cable that is fine.
        # SYNC-105: ...and a drive mounted at the wrong path is not
        # disconnected either.
        phrase = drive_absent_phrase(snap.get("root_state"))
        owed = str(snap.get("root_unfinished") or "")
        if owed:
            return f"Sync: paused ({phrase}, {owed} still to go)"
        return f"Sync: paused ({phrase})"
    if snap.get("paused"):
        return "Sync: paused"
    # SYNC-15: anything the five branches above do not cover, in the words
    # the fleet grid uses. Every reason here is one an editor could otherwise
    # only find by reading their own log.
    blocked = guard.get("blocked") or {}
    if isinstance(blocked, dict) and blocked.get("detail"):
        return f"Sync: {blocked['detail']}"

    up = down = 0
    speed = 0.0
    for status in snap.get("statuses") or []:
        if status.state != STATE_SYNCING:
            continue
        count = int(status.transferring or status.queued or 0)
        # Lane C is "everything else, both ways" (LANE_LABELS) -- it carries
        # no up/down split of its own, so its activity counts toward BOTH
        # totals rather than inventing a third phrasing nobody asked for.
        if not status.name.endswith("_down"):
            up += count
        if not status.name.endswith("_up"):
            down += count
        if status.speed_bps:
            speed += float(status.speed_bps)

    if up or down:
        rate = _mb_per_s(speed) if speed else None
        suffix = f" · {rate}" if rate else ""
        if up and down:
            return f"Sync: up {up} · down {down} files{suffix}"
        if up:
            return f"Sync: uploading {up} file{'s' if up != 1 else ''}{suffix}"
        return f"Sync: downloading {down} file{'s' if down != 1 else ''}{suffix}"

    waiting = sum(int(status.queued or 0) for status in snap.get("statuses") or [])
    if waiting:
        return f"Sync: {waiting} file{'s' if waiting != 1 else ''} waiting"
    return "Sync: up to date"


def _mb_per_s(bps: Any) -> Optional[str]:
    """bytes/s -> '4.2 MB/s' (decimal megabytes, what a browser's download
    shelf shows), '0.3 MB/s' below a megabyte; None when yt-dlp said NA."""
    try:
        v = float(bps)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0:
        return None
    return f"{v / 1_000_000:.1f} MB/s"


def ytdl_download_line(progress: Optional[dict]) -> Optional[str]:
    """The state line for a local YouTube download, or None when there is
    none running. `progress` is ytdl_executor.progress()'s dict.

        Downloading YouTube clip 3/12 (4.2 MB/s, 38%)
        Downloading YouTube clip 3/12 (4.2 MB/s)        no total known (HLS)
        Downloading YouTube clip 3/12                   before the first update,
                                                        or merging
        Converting YouTube clip 3/12 to H.264           ffmpeg re-encoding a
                                                        clip Resolve could not
                                                        decode (CR-79)

    The count is "which clip is in flight", one-based: done + failed + 1,
    capped at the total, because "3/12" is what the owner asked for and
    "2 done of 12" is a different sentence. No em dash (owner's rule).
    """
    if not isinstance(progress, dict) or not progress.get("running"):
        return None
    try:
        total = int(progress.get("total") or 0)
        done = int(progress.get("done") or 0) + int(progress.get("failed") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return "Downloading YouTube clips"
    current = min(done + 1, total)
    if progress.get("phase") == "converting":
        # A re-encode has no bytes-per-second worth showing, and reading it
        # as a stalled download is the exact complaint CR-78 answered.
        return f"Converting YouTube clip {current}/{total} to H.264"
    bits = []
    rate = _mb_per_s(progress.get("speed_bps"))
    if rate:
        bits.append(rate)
    try:
        b_done = progress.get("bytes_done")
        b_total = progress.get("bytes_total")
        if b_done is not None and b_total:
            pct = max(0, min(100, int(100 * float(b_done) / float(b_total))))
            bits.append(f"{pct}%")
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    line = f"Downloading YouTube clip {current}/{total}"
    return f"{line} ({', '.join(bits)})" if bits else line


def resolve_bridge_line(state: Optional[dict]) -> Optional[str]:
    """One tray line for "is the Resolve bridge up, and has it EVER been?".

    None before anything has asked Resolve (nothing truthful to say yet) and
    None for a state dict we don't understand -- an unrecognised shape must
    cost a missing line, never a wrong one.

    The distinction that matters is `ever_connected`. A bridge that has never
    connected in this whole session is a broken install -- MAC-10's wrong
    modules path made every Resolve feature silently dead for hours -- while
    one that connected and then went is just Resolve being closed or
    restarted. The old tray said neither, which is why both incidents were
    diagnosed by hand instead of by looking (items 17 and 19).
    """
    if not isinstance(state, dict):
        return None
    connected = state.get("connected")
    if connected is None:
        return None
    if connected:
        return "Resolve: connected"
    reason = str(state.get("reason") or "no connection")
    if state.get("ever_connected"):
        return f"Resolve: not connected right now ({reason})"
    return f"Resolve: NOT CONNECTED this session ({reason})"


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
    # compute_overall_color() has always consulted this; the tooltip and the
    # menu did not, so an install running with require_login=false and three
    # healthy lanes was told "not signed in (nothing syncs)" while everything
    # synced perfectly.
    _get("require_login", lambda: bool(getattr(app, "_require_login", True)), True)
    _get("identity_label", lambda: _identity_status_label(app), "NOT SIGNED IN")
    _get("paused", lambda: bool(app.is_paused()), False)
    _get("problems", lambda: bool(getattr(app, "config_problems", None)), False)
    # The sync drive (root_guard.py): an unplugged external SSD is a PAUSE,
    # not a fault, and it has to say so on every lane line -- otherwise the
    # tray reports "PROBLEM ... a project folder was deleted on this machine"
    # for a project sitting safely on a drive in the editor's bag.
    _get("root_absent", lambda: bool(getattr(app, "_root_absent", False)), False)
    # ...and WHICH of the four answers it is (SYNC-2, resilience sweep
    # 2026-08-28): `absent` and `not_answering` both pause the lanes and need
    # different sentences, so the snapshot carries the state, not just a bool.
    _get("root_state",
         lambda: str(getattr(app, "_root_state", root_guard_mod.ROOT_UNKNOWN)),
         root_guard_mod.ROOT_UNKNOWN)
    # What the drive went out still owing ("2 uploads (2.3 GB left)"), or ""
    # (CR-92). Two attribute reads on the app; the tray shows it on the
    # Sync: line and the tooltip so the reminder balloon is not the only
    # place the sentence exists.
    _get("root_unfinished",
         lambda: str(getattr(app, "drive_unfinished_summary", lambda: "")() or ""), "")
    _get("dashboard_url", lambda: _dashboard_url(app), "")
    # Whether the "Sign in to YouTube (for downloads)…" item is offered at
    # all. TWO gates since 2026-08-17 (COMMERCIAL_READINESS.md items 2 + 3):
    # `ytdl_local_downloads` is this machine's own opt-out, folded into
    # ytdlp_manager.youtube_enabled along with the site manifest's
    # `youtube_download`; and signing IN needs the site's `youtube_unblock` on
    # top, because downloading as a live Google account is the piece the
    # vendor build does not ship enabled. False hides the item, matching the
    # sidecar manager doing nothing on that machine.
    _get("ytdl_local_downloads",
         lambda: ytdlp_manager.youtube_enabled(getattr(app, "config", {})), False)
    _get("ytdl_youtube_signin",
         lambda: (ytdlp_manager.youtube_enabled(getattr(app, "config", {}))
                  and ytdlp_manager.unblock_enabled()), False)
    # Whether the terms have been accepted on THIS machine by the signed-in
    # editor -- one small file read, the same cost as every other line here.
    _get("ytdl_attested",
         lambda: _ytdl_attested(app), False)
    # Is the LICENCE the thing stopping this machine syncing? One file read,
    # same as the line above. Non-empty puts the accept item in the menu --
    # the way back for an editor who declined or closed the dialog, and the
    # only route at all on a machine that upgraded before this build existed
    # (2026-08-18).
    _get("eula_problem",
         lambda: getattr(app, "eula_problem", lambda: None)() or "", "")
    # Is the editor's YouTube sign-in still working? Two small file reads
    # (ytdl_cookies.health): the status the executor recorded from yt-dlp's
    # own verdict, and the login cookies' expiry. "stale"/"expired" puts a
    # warning line in the menu, relabels the sign-in item and balloons ONCE
    # (2026-08-17, at the user's request: a rotated session used to fail
    # silently into the server fallback).
    _get("ytdl_cookies_health",
         lambda: (ytdl_cookies.health(getattr(app, "config", {}))
                  if snap.get("ytdl_youtube_signin") else {"status": "none"}),
         {"status": "none"})
    _get("sequencer_line", lambda: _sequencer_line(app), None)
    _get("current_project_line", lambda: _current_project_line(app), None)
    # Cheap by construction: resolve_bridge records this on the way out of
    # every enumeration, so the tray reads a cached bool. It must NEVER probe
    # Resolve from here -- a fusionscript call holds the GIL for its full
    # native duration and the render path is the one place that cannot pay
    # for one (see resolve_bridge.session_state / ui_state.menu_open).
    _get("resolve_line", lambda: resolve_bridge_line(
        (getattr(app, "resolve_bridge_state", None) or resolve_bridge.session_state)()
    ), None)
    # The YouTube download this machine is running, if any: a dict read
    # under the executor's own lock, no I/O (2026-08-25, the owner: "when it
    # is downloading a youtube clip it shows the information. Downloading:
    # x/x (xx mb/s)").
    _get("ytdl_line", lambda: ytdl_download_line(
        (getattr(app, "ytdl_progress", None) or ytdl_executor.progress)()
    ), None)
    _get("setup_name", lambda: (getattr(app, "setup_project_available", None) or (lambda: None))(), None)
    _get("upgrade_info", lambda: (getattr(app, "upgrade_available", None) or (lambda: None))(), None)
    _get("removable", lambda: (getattr(app, "removable_projects", None) or (lambda: []))(), [])
    # LUTs sitting in Resolve's own LUT folder that the shared library does
    # not have -- i.e. added the old way, on one machine only. Cached by the
    # app (the scan walks a directory), so this is a cheap read.
    _get("stray_luts", lambda: (getattr(app, "stray_lut_count", None) or (lambda: 0))(), 0)
    # Originals with no proxy beside them -- i.e. footage lane B can never
    # carry to anybody else (proxy_gen.py). Cached by the generator's own
    # thread, so this is a lock-guarded read of a dict and never a tree walk;
    # {} is the right default for a companion whose generator is absent,
    # because every consumer below treats it as "nothing to say".
    _get("proxy_gap", lambda: (getattr(app, "proxy_gap", None) or (lambda: {}))() or {}, {})
    # The b-roll batch this machine is indexing, if any (broll_ingest.py,
    # 2026-08-18). Same contract as proxy_gap above: the orchestrator's own
    # thread keeps it, so this is a lock-guarded dict read and never a probe,
    # and {} is the honest answer on a companion with no orchestrator.
    _get("broll_ingest",
         lambda: (getattr(app, "broll_ingest_view", None) or (lambda: {}))() or {}, {})
    # ...and the music batch beside it (docs/MUSIC_INGEST_PLAN.md 2). Two
    # separate sections, because the two run at the same time: music needs no
    # GPU, so it never waits for b-roll and b-roll never waits for it.
    _get("music_ingest",
         lambda: (getattr(app, "music_ingest_view", None) or (lambda: {}))() or {}, {})
    _get("p_swap_available", lambda: (getattr(app, "p_swap_available", None) or (lambda: False))(), False)
    # The CACHED classification, never a probe: p_mapping_mode() spawns
    # `net use P:` (plus a `subst` on a subst-mapped rig), and reading it here
    # every 2 s meant its 10 s memo expired and re-populated forever -- a
    # process fork on one tick in five, from the one place documented above as
    # where nothing may stall (COMP-CORE-6, 2026-08-14). The app refreshes the
    # cache on its slow media-tree tick and both swap actions invalidate it.
    _get("p_mode", lambda: (getattr(app, "p_mapping_mode_cached", None)
                            or getattr(app, "p_mapping_mode", None)
                            or (lambda: "none"))(), "none")
    # The two safety latches and the trash size (COMMERCIAL_READINESS.md
    # item 9, 2026-08-17). All cached reads -- the breaker and the halt are
    # in-memory objects, the trash summary is whatever lane B's last prune
    # cycle measured -- so none of them may stall the render path.
    _get("sync_guard", lambda: (getattr(app, "sync_guard", None) or (lambda: {}))() or {}, {})
    # Whether this machine is currently lent to the fleet, and until when
    # (TIMELINE-CARDS-INTO-CCSYNC.md section 10, 2026-08-30). A zero-I/O read
    # of the runner's own snapshot, like every other line here -- and "" on a
    # companion with no runner at all, which is what hides the menu item.
    _get("jobs_volunteer_until", lambda: _jobs_volunteer_until(app), "")
    # ...and how long a click lasts, which is both the label's number and the
    # test for whether the item exists at all: 0 on a companion with no job
    # runner, or one whose owner has turned fleet jobs off.
    _get("jobs_volunteer_minutes", lambda: _jobs_volunteer_minutes(app), 0)
    # The guard is already in the snapshot above, and _guard_fingerprint
    # already carries blocked['reason'] -- so APP-1's colour needs no new
    # plumbing and cannot go stale while the menu is open (2026-09-04).
    snap["color"] = compute_overall_color(statuses, app, snap.get("sync_guard"))
    _get("pulse", lambda: should_pulse(snap["color"], statuses), False)
    return snap


def _jobs_volunteer_until(app: "CompanionApp") -> str:
    """The ISO deadline the job runner is volunteering until, or "".

    status() is a zero-I/O lock-guarded read, which is the only kind of getter
    allowed on this path (COMP-CORE-6)."""
    runner = getattr(app, "job_runner", None)
    if runner is None:
        return ""
    return str((runner.status() or {}).get("volunteer_until") or "")


def _jobs_volunteer_minutes(app: "CompanionApp") -> int:
    """How many minutes one click lends this machine for -- 0 when there is
    nothing to lend (no runner, or `jobs_enabled = false`), which is what
    keeps the item out of the menu entirely."""
    runner = getattr(app, "job_runner", None)
    if runner is None or not getattr(runner, "enabled", False):
        return 0
    try:
        return max(0, int(float(getattr(runner, "volunteer_minutes", 30) or 0)))
    except (TypeError, ValueError):
        return 0


def _volunteer_label(snap: dict) -> str:
    """The menu item's two states, in the editor's own local time.

    An unparseable deadline still says something useful rather than crashing
    the menu: an unreadable timestamp is not a reason to hide a switch
    somebody is looking for."""
    minutes = int(snap.get("jobs_volunteer_minutes") or 0)
    until = str(snap.get("jobs_volunteer_until") or "")
    if not until:
        return f"⚡ Take fleet jobs now ({minutes} min)"
    try:
        when = datetime.fromisoformat(until).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return "⚡ Taking fleet jobs now (click to stop)"
    return f"⚡ Taking fleet jobs until {when} (click to stop)"


def _breaker_line(guard: dict) -> Optional[str]:
    """The one-line "proxy download is stopped" state, or None.

    Deliberately its own sentence rather than a suffix on lane B's line: an
    editor reading "PROBLEM" against a lane learns nothing they can act on,
    and the two facts that stop the support call -- nothing was deleted, your
    uploads are still running -- do not fit on a lane line."""
    breaker = (guard or {}).get("lane_b_breaker") or {}
    if not breaker.get("tripped"):
        return None
    reason = str(breaker.get("reason") or "a safety check failed")
    return f"⛔ PROXY DOWNLOAD STOPPED (safety): {reason}"


def _disk_line(guard: dict) -> Optional[str]:
    """"Not downloading proxies: this drive has 8 GB free", or None
    (SYS-5 / SYNC-7, resilience sweep 2026-08-28).

    Its own sentence rather than a suffix on lane B's line, for the breaker's
    reason: the two facts that stop the support call -- your uploads are still
    running, and it starts again by itself -- do not fit on a lane line."""
    floor = (guard or {}).get("disk_floor") or {}
    if not isinstance(floor, dict) or not floor.get("parked"):
        return None
    reason = str(floor.get("reason") or "this drive is nearly full")
    return (f"⚠ Not downloading proxies: {reason}. Uploads are still running; free "
            "up space and it starts again on its own")


def _blocked_line(guard: dict) -> Optional[str]:
    """The one sentence that answers "why is nothing syncing" (SYNC-15).

    Deliberately the LAST line rendered and often a repeat of one above it:
    the point of `sync_guard.blocked` is that the tray, the fleet grid and the
    "why isn't it syncing" question all read ONE ordered answer, so an editor
    on the phone to their admin is reading the same words. Suppressed when the
    reason is one the lane lines already carry unambiguously."""
    blocked = (guard or {}).get("blocked") or {}
    if not isinstance(blocked, dict):
        return None
    detail = str(blocked.get("detail") or "").strip()
    reason = str(blocked.get("reason") or "").strip()
    if not detail or not reason:
        return None
    if reason in _BLOCKED_REASONS_WITH_THEIR_OWN_LINE:
        return None
    return f"⚠ {detail}"


# Reasons whose sentence is already on a line of its own above (the halt, the
# breaker, the disk park, the unfiltered folders). Repeating them would make
# the Settings window say the same thing twice.
_BLOCKED_REASONS_WITH_THEIR_OWN_LINE = frozenset({
    "fleet_halt", "local_halt", "breaker_tripped", "disk_full",
    "folders_unfiltered", "clock_skew",
})


def _halt_line(guard: dict) -> Optional[str]:
    halt = (guard or {}).get("halt") or {}
    if not halt.get("active"):
        return None
    who = ("Your administrator stopped syncing for everyone"
           if halt.get("scope") == "fleet" else "Syncing is STOPPED on this machine")
    reason = str(halt.get("reason") or "")
    return f"⛔ {who}" + (f": {reason}" if reason else "")


def _trash_line(guard: dict) -> Optional[str]:
    """"How much is in trash" -- absent below a gigabyte.

    `.ccsync-trash` is where every file lane B removed still lives, and until
    item 9 nothing anywhere said how big it had grown. Under 1 GB it is noise
    on a menu that already has plenty."""
    trash = (guard or {}).get("trash") or {}
    try:
        total = int(trash.get("bytes") or 0)
    except (TypeError, ValueError):
        return None
    if total < (1 << 30):
        return None
    return (f"Recoverable files in .ccsync-trash: {human_bytes(total)} "
            f"({int(trash.get('count') or 0)} files)")


def _skipped_exists_line(guard: dict) -> Optional[str]:
    """Lane A's "same name, already on the server at a different size" count.

    The one silent data-loss shape on the upload lane: `copy
    --ignore-existing` will never replace it, so the re-export sits here
    forever with the lane showing green (item 9)."""
    skipped = (guard or {}).get("skipped_exists") or {}
    try:
        count = int(skipped.get("count") or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    return (f"⚠ {count} file{'s' if count != 1 else ''} on the server "
            f"{'have' if count != 1 else 'has'} the same name but a different size. "
            "Your newer version will NOT upload")


# A stall older than this is history, not news: the lane has had many
# healthy passes since, and the record is kept on disk for diagnostics
# rather than for the menu.
STALL_LINE_MAX_AGE_SECONDS = 24 * 3600


def _stalled_line(guard: dict) -> Optional[str]:
    """"Proxy download was stuck and had to be restarted" (SYNC-1, CR-91).

    The tray half of the stall watchdog. Until this, a lane whose rclone had
    wedged on a drive that stopped answering reported `syncing` forever and
    said nothing at all on the machine it was happening on -- the editor's
    own computer held no record that anything had been killed. Named as a
    drive problem because that is what it has always been in the field
    (a Mac's external SSD, a dropped network mapping)."""
    stalled = (guard or {}).get("stalled") or {}
    when = stalled.get("at")
    if not when:
        return None
    try:
        seconds = int(stalled.get("seconds") or 0)
    except (TypeError, ValueError):
        seconds = 0
    age = _stamp_age_seconds(when)
    if age is not None and age > STALL_LINE_MAX_AGE_SECONDS:
        return None
    lane = str(stalled.get("lane") or "").strip()
    what = {
        "A": "Uploading",
        "B": "Proxy download",
        "express": "The fast upload of new clips",
    }.get(lane, "Syncing")
    return (f"⚠ {what} stopped moving for {max(1, seconds // 60)} min and was "
            "restarted. If it keeps happening, check the drive is connected")


def _stamp_age_seconds(stamp: Any) -> Optional[int]:
    """Seconds since an ISO-8601 stamp, or None when it cannot be read.

    None, never 0: "could not tell" must not render as "just now" (CR-89)."""
    try:
        when = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        return max(0, int((datetime.now(timezone.utc) - when).total_seconds()))
    except Exception:
        return None


def _unfiltered_line(guard: dict) -> Optional[str]:
    """The projects whose sharing is parked because their filter list never
    landed (SYNC-5, resilience sweep 2026-08-28).

    Lane C reports `error` for this too, but the lane line names no project:
    this one does, because "which of my projects is not sharing" is the
    question, and the answer is an admin's job, not the editor's."""
    slugs = [str(s) for s in ((guard or {}).get("folders_unfiltered") or []) if s]
    if not slugs:
        return None
    shown = ", ".join(slugs[:3])
    if len(slugs) > 3:
        shown += f", +{len(slugs) - 3} more"
    return (f"⚠ {len(slugs)} project(s) are not sharing yet - waiting for their "
            f"filter list: {shown}")


def _conflicts_line(guard: dict) -> Optional[str]:
    """Syncthing conflict copies on this machine (UX-7).

    Advisory and never actioned from here: two people changed the same file,
    Syncthing kept both, and only a human can say which one is the work. The
    sentence names the file so the editor can find it in Explorer/Finder."""
    conflicts = (guard or {}).get("sync_conflicts") or {}
    try:
        count = int(conflicts.get("count") or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    paths = [str(p) for p in (conflicts.get("paths") or []) if p]
    example = f" (e.g. {paths[0].rsplit('/', 1)[-1]})" if paths else ""
    return (f"⚠ {count} file{'s' if count != 1 else ''} "
            f"{'were' if count != 1 else 'was'} edited on two machines at once, so "
            f"Syncthing kept both copies{example}. Nothing was lost: ask your admin "
            "which one to keep")


# Report cycles in a row that must fail before the tray says so (APP-1).
# ~10 intervals: at the normal 60 s cadence that is ten minutes, which is
# long enough that a NAS reboot or a laptop lid does not produce a line and
# short enough that a revoked token is named the same morning.
REPORTER_FAILURE_STREAK = 10


def _reporter_line(guard: dict) -> Optional[str]:
    """"The dashboard has not accepted a report for 3h", or None (APP-1,
    resilience sweep 2026-08-28).

    The failure this closes: a revoked per-editor token, or a typo in
    `dashboard_url`, left the lanes syncing and the tray green while the
    machine went dark on the fleet grid. Nothing on this computer said so.

    A rejected CREDENTIAL is named separately from an unreachable server,
    because they are different jobs: one is the editor's (sign in again), the
    other is their admin's."""
    health = (guard or {}).get("reporter") or {}
    if not isinstance(health, dict):
        return None
    try:
        streak = int(health.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        return None
    if streak < REPORTER_FAILURE_STREAK:
        return None
    status = str(health.get("last_status") or "")
    if status in ("HTTP 401", "HTTP 403"):
        # UX-1: "from this menu" was the old right-click menu; this line is
        # rendered inside the Settings window, where the button also lives.
        return ("⚠ The dashboard is refusing this computer's reports: your CCSync "
                f"sign-in was rejected. Sign in again: {ui_copy.SIGN_IN_SETTINGS}")
    since = reporter_mod.parse_server_time(health.get("last_success_at"))
    if since is None:
        return ("⚠ The dashboard has never accepted a report from this computer. "
                "Your work may not be visible to your admin. Copy diagnostics for them")
    age = max(0.0, time.time() - since)
    return (f"⚠ The dashboard has not accepted a report for "
            f"{proxy_history.human_duration(age)}, so your admin cannot see whether "
            "this computer is syncing")


def _clock_skew_line(guard: dict) -> Optional[str]:
    """"This computer's clock is 20 minutes behind the server" (APP-13/SYS-4).

    Not cosmetic: lane B passes rclone `--min-age`, and rclone ages a remote
    file against the LOCAL clock, so a slow clock makes every file on the NAS
    look like it was written in the future and the pass transfers nothing,
    exits 0, and reports idle and green."""
    skew = (guard or {}).get("clock_skew_seconds")
    try:
        value = float(skew)
    except (TypeError, ValueError):
        return None
    if abs(value) < 60:
        return None
    phrase = reporter_mod.skew_phrase(value)
    return (f"⚠ This computer's clock is {phrase} the server's. Sync will not work "
            "correctly until it is fixed")


def _ignored_line(guard: dict) -> Optional[str]:
    """"14 clip(s) skipped this session and still not syncing" (APP-2 / UX-4,
    resilience sweep 2026-08-28).

    IGNORE ALL / SKIP FOR NOW was permanent for the session, invisible, and
    honoured even by "Scan whole project" -- so an editor who cleared the
    dialog to get on with a cut had no way left to find out that 65 clips of
    theirs were never going to reach anyone. The line names the way back
    (the scan now clears the session set first, which is what makes that
    sentence true).

    The persisted folder ignores get a clause of their own rather than a
    line: they are a decision somebody made on purpose, not a warning.
    """
    health = (guard or {}).get("resolve_health") or {}
    if not isinstance(health, dict):
        return None
    try:
        session = int(health.get("ignored_this_session") or 0)
        folders = int(health.get("ignored_folders") or 0)
    except (TypeError, ValueError):
        return None
    parts: list[str] = []
    if session:
        parts.append(
            f"⚠ {session} clip(s) skipped this session and still not syncing - "
            "Settings > SCAN WHOLE PROJECT offers them again")
    if folders:
        parts.append(
            f"{folders} folder(s) are set to be left alone on this computer - "
            "Settings can undo that")
    return ". ".join(parts) if parts else None


def _crashes_line(guard: dict) -> Optional[str]:
    """"A background task failed" (APP-6).

    crash_report.py exists because "the tray stayed up with a dead lane" is
    the failure this fleet keeps hitting, and until the sweep the file it
    wrote was surfaced nowhere at all."""
    crashes = (guard or {}).get("crashes") or {}
    if not isinstance(crashes, dict):
        return None
    try:
        count = int(crashes.get("count") or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    return (f"⚠ A background task failed on this computer "
            f"({count} report{'s' if count != 1 else ''} saved). Copy diagnostics "
            "for your admin")


# Restarts of ONE background thread inside an hour that earn a tray line.
# The mirror of app.LANE_WATCHDOG_ADVISORY_RESTARTS, kept here as its own name
# so tray.py stays importable without app.py.
RESTART_ADVISORY_COUNT = 3


def _upgrade_line(guard: dict) -> Optional[str]:
    """"CCSync could not install the update N times" (REL-8, resilience sweep
    2026-08-28).

    Only once the machine has GIVEN UP: below the cap it is still retrying on
    its own back-off, and a line for every transient failure would train the
    editor to ignore this one. The cause is on the report and in diagnostics
    (an AV quarantine, a captive portal mangling the download, a full disk, a
    binary for the wrong architecture); what the editor can do about any of
    them is hand their admin the diagnostics."""
    info = (guard or {}).get("upgrade") or {}
    if not isinstance(info, dict):
        return None
    try:
        attempts = int(info.get("attempts") or 0)
    except (TypeError, ValueError):
        return None
    if attempts < upgrade_mod.MAX_UPGRADE_ATTEMPTS:
        return None
    version = str(info.get("version") or "").strip()
    target = f" to v{version}" if version else ""
    return (f"⚠ CCSync could not install the update{target} {attempts} times, so it "
            f"has stopped trying. {ui_copy.DIAGNOSTICS}")


def _reverted_line(guard: dict) -> Optional[str]:
    """"CCSync went back to the previous version" (APP-5 / REL-2).

    Says it where it stays readable: the toast raised at the rollback start
    is gone in ten seconds, and the machine is running an OLDER build than
    the fleet until an admin publishes a fix."""
    info = (guard or {}).get("upgrade") or {}
    if not isinstance(info, dict):
        return None
    bad = str(info.get("reverted_from") or "").strip()
    if not bad:
        return None
    return (f"⚠ The v{bad} update kept crashing, so CCSync went back to the "
            "previous version. Your admin has been told")


def _restarts_line(guard: dict) -> Optional[str]:
    """"CCSync keeps restarting its sync engine" (SYS-2).

    The watchdog self-heals a dead sequencer, which is the right behaviour and
    also exactly how a machine syncing in fits and starts stays invisible. One
    restart is not news; three inside an hour is a fault the editor should be
    able to hand to their admin without anyone noticing it by accident."""
    restarts = (guard or {}).get("restarts") or {}
    if not isinstance(restarts, dict):
        return None
    worst = 0
    for entry in restarts.values():
        if not isinstance(entry, dict):
            continue
        try:
            # count_1h absent (an older companion's record) reads as 0: "we
            # could not tell" must not render as an alarm either way round.
            count = int(entry.get("count_1h") or 0)
        except (TypeError, ValueError):
            continue
        worst = max(worst, count)
    if worst < RESTART_ADVISORY_COUNT:
        return None
    return (f"⚠ CCSync keeps restarting its sync engine ({worst} times in the "
            "last hour), so syncing is stopping and starting. Copy diagnostics "
            "for your admin")


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

    Deliberately coarser than the rendered text. It had to be under pystray,
    whose win32 backend DestroyMenu()d the live menu handle on every
    icon.menu assignment: a rebuild while the menu was open froze it, and the
    returned index was then resolved against the NEW callback list, i.e. a
    click could fire the WRONG item. tray_native builds the HMENU at
    right-click time and destroys it on close, so neither is possible any
    more -- but the fingerprint stays, because rebuilding ~40 menu items and
    their closures twice a second is work nobody needs either. Only on real
    state changes, not on every byte counted.

    REDUCED 2026-08-27 alongside the menu itself (the Settings-window split,
    settings_window.py): everything that used to have its own menu LINE or
    ACTION and moved wholly into Settings -- the sequencer/current-project/
    ytdl lines, every YouTube field, the removable-projects list, the
    grade-swap mode, and the proxy/ingest fingerprints -- came out of this
    tuple too, because none of it can change what the reduced MENU renders
    any more. Settings reads those same snapshot fields fresh on its own
    ~2s refresh instead of through this cache. What is left is exactly what
    still decides a menu ITEM's presence or label, including the Sync: line
    (_sync_line), which the guard/problems/paused/root_absent/statuses
    entries below already cover."""
    lanes = tuple(
        (s.name, s.state, str(s.detail or ""), str(s.last_error or ""),
         str(s.current_project or ""), bool(s.queued), _progress_bucket(s))
        for s in snap["statuses"]
    )
    return (
        lanes, snap["identity_label"], snap["signed_in"], snap["paused"],
        snap["problems"], snap.get("root_absent"), snap.get("root_unfinished"),
        snap.get("resolve_line"),
        snap["setup_name"], (snap["upgrade_info"] or {}).get("version"),
        snap["dashboard_url"],
        snap["color"],
        # The stray-LUT count decides whether the "N LUTs only on this
        # machine" item exists at all, and on an otherwise-idle machine
        # nothing else here moves when a LUT is dropped into Resolve's own
        # folder -- so without this the whole shared-LUT onboarding item was
        # unreachable until something unrelated changed, and lingered after
        # share_stray_luts took the count back to 0 (UI-3, 2026-08-11).
        int(snap.get("stray_luts") or 0),
        # The safety latches decide whether two ACTIONS exist at all
        # ("Resume proxy download", "Start syncing again") AND what the
        # Sync: line says, so they have to move the fingerprint or the menu
        # keeps offering the wrong one until something unrelated changes --
        # the same bug UI-3 was (item 9).
        _guard_fingerprint(snap.get("sync_guard")),
        # Same rule as the latch above: accepting the licence is the only
        # thing that changes on a machine parked behind that gate, so
        # without it here the accept item would still be in the menu after
        # the click that cleared it -- and the Sync: line would still say
        # "not set up yet" (UI-3's shape again, 2026-08-18).
        bool(snap.get("eula_problem")),
        # The volunteer item's presence AND its label (section 10,
        # 2026-08-30). Both halves have to be here: without the minutes the
        # item never appears on a machine whose runner starts late, and
        # without the deadline the label still says "Take fleet jobs now"
        # after the click that started the timer -- UI-3's shape again.
        int(snap.get("jobs_volunteer_minutes") or 0),
        str(snap.get("jobs_volunteer_until") or ""),
    )


def _guard_fingerprint(guard: Optional[dict]) -> tuple:
    """Coarse state of the breaker/halt/trash lines. Bucketed like every
    other counter here: the trash grows continuously and a rebuild per
    gigabyte is already generous."""
    guard = guard or {}
    breaker = guard.get("lane_b_breaker") or {}
    halt = guard.get("halt") or {}
    trash = guard.get("trash") or {}
    skipped = guard.get("skipped_exists") or {}
    try:
        trash_gb = int(int(trash.get("bytes") or 0) // (1 << 30))
    except (TypeError, ValueError):
        trash_gb = 0
    return (
        bool(breaker.get("tripped")), str(breaker.get("reason") or ""),
        bool(halt.get("active")), str(halt.get("scope") or ""),
        str(halt.get("reason") or ""), trash_gb,
        int(skipped.get("count") or 0),
        # SYNC-1: the stall line appears and disappears on its own (the
        # record ages out of the menu after a day), so without its stamp
        # here the line would linger, or never show, until something
        # unrelated moved the fingerprint -- UI-3's shape again.
        str((guard.get("stalled") or {}).get("at") or ""),
        # SYS-5/SYNC-7 and SYNC-15: the disk park adds the RESUME action (and
        # a line), and the blocked reason is a line -- a change in either has
        # to rebuild the menu or the item never appears.
        bool((guard.get("disk_floor") or {}).get("parked")),
        str((guard.get("blocked") or {}).get("reason") or ""),
    )


# How coarsely the two history-driven menu lines are allowed to move. Same
# trade _progress_bucket() makes: a rebuild is a small risk to a menu the
# user may have open, so "made today" steps in 25s (visible progress on a run
# of hundreds, ~20 rebuilds a night instead of 500) and the ETA in 15-minute
# steps (below that it is noise anyway -- one long clip moves it further).
MADE_TODAY_BUCKET = 25
ETA_BUCKET_SECONDS = 900


def _proxy_history(gap: Optional[dict]) -> dict:
    """The ledger block off a proxy gap, or {}. Never raises: an older
    generator (or one whose history failed to open) has no such key."""
    if not isinstance(gap, dict):
        return {}
    history = gap.get("history")
    return history if isinstance(history, dict) else {}


def _proxy_made_line(gap: Optional[dict]) -> str:
    """"Made 528 proxies today · 1.2 TB → 41 GB", or "" on a quiet day."""
    today = (_proxy_history(gap).get("today") or {})
    try:
        done = int(today.get("done") or 0)
        failed = int(today.get("failed") or 0)
    except (TypeError, ValueError):
        return ""
    if not done and not failed:
        return ""
    text = f"Made {done} proxies today" if done != 1 else "Made 1 proxy today"
    src, proxy = today.get("src_bytes") or 0, today.get("proxy_bytes") or 0
    if done and src and proxy:
        text += (f" · {proxy_history.human_bytes(src)} → "
                 f"{proxy_history.human_bytes(proxy)}")
    if failed:
        # Named, not hidden: a failure the editor never hears about is one
        # nobody re-shoots, re-downloads or reports.
        text += f" · {failed} failed" if failed != 1 else " · 1 failed"
    return text


def _proxy_eta_line(gap: Optional[dict]) -> str:
    """"About 2h 40m to go at this rate", or "" until the rate is known."""
    eta = _proxy_history(gap).get("eta_seconds")
    if not eta:
        return ""
    return f"About {proxy_history.human_duration(eta)} to go at this rate"


def proxy_advisory_lines(proxy_gap: Optional[dict]) -> list[str]:
    """The missing-proxy/encoding/BRAW/made-today lines, in order -- what the
    menu used to render under "proxy_items" and settings_window.py's SYNC
    LANES section renders now (2026-08-27). One function so the two callers
    can never say different things about the same gap."""
    proxy_gap = proxy_gap or {}
    proxy_missing = int(proxy_gap.get("missing") or 0)
    proxy_braw = int(proxy_gap.get("braw") or 0)
    proxy_encoding = bool(proxy_gap.get("encoding"))
    proxy_left = int(proxy_gap.get("left") or 0)
    lines: list[str] = []
    # Why it is NOT encoding, when the reason is another feature of this same
    # companion rather than a gap (2026-08-18): without this the menu says
    # "12 clips have no proxy" for an hour with nothing explaining why nothing
    # is happening about it.
    if not proxy_encoding and proxy_gap.get("blocked_reason"):
        lines.append(f"Proxies waiting: {proxy_gap['blocked_reason']}")
    if proxy_encoding:
        # "stops when you're back" is the whole promise of the feature, and
        # it is the answer to the question this line provokes ("is that why
        # my machine is busy?"). The count is a bucketed rebuild, not a live
        # ticker -- see _proxy_fingerprint.
        lines.append(f"Making proxies… {proxy_left} left (stops when you're back)")
        eta = _proxy_eta_line(proxy_gap)
        if eta:
            lines.append(eta)
    elif proxy_missing:
        lines.append(
            f"{proxy_missing} clips have no proxy: other editors can't see them"
            if proxy_missing != 1 else
            "1 clip has no proxy: other editors can't see it"
        )
    if proxy_braw:
        # Named by format because it is the one gap the editor must act on
        # themselves: no ffmpeg build can decode BRAW, so this machine will
        # never fill it however long it sits idle.
        lines.append(
            f"{proxy_braw} BRAW clips need the Blackmagic Proxy Generator"
            if proxy_braw != 1 else
            "1 BRAW clip needs the Blackmagic Proxy Generator"
        )
    # What this machine has MADE, from the ledger that survives restarts
    # (proxy_history.py). Last of the advisory lines because it is the only
    # one that is not asking for anything: everything above is a gap, this is
    # the work already done.
    proxy_made = _proxy_made_line(proxy_gap)
    if proxy_made:
        lines.append(proxy_made)
    return lines


def _ingest_lines(ingest: Optional[dict], label: str = "b-roll",
                  unit: str = "clip") -> list[str]:
    """The indexing lines for one kind, in the plan's words (BROLL 3.3).

    `label`/`unit` default to b-roll's words, so the b-roll call is the call
    it always was; music passes its own ("music", "track"). One function for
    both because the sentences ARE the same sentences -- what is happening,
    when it stops -- and two copies would drift the moment one was reworded.

    Advisory, like the proxy lines above and for the same reason: an editor
    whose machine is indexing has nothing to fix, and the sentence has to say
    what is happening and when it stops rather than name a stage. The VRAM
    refusal is the exception -- it IS something only they can fix, so it goes
    first and stays until the batch changes.
    """
    if not isinstance(ingest, dict) or not ingest:
        return []
    lines: list[str] = []
    warning = str(ingest.get("warning") or "")
    if warning:
        lines.append(warning)
    total = int(ingest.get("total") or 0)
    done = int(ingest.get("done") or 0)
    failed = int(ingest.get("failed") or 0)
    gate = str(ingest.get("gate") or "")
    percent = ingest.get("model_download_percent")

    if percent is not None:
        lines.append(f"Downloading the {label} indexing model… {int(percent)} %")
    elif gate == "running":
        tail = (" (stops when you're back)"
                if ingest.get("run_mode") != "foreground" else "")
        lines.append(f"Indexing {label}… {done} of {total}{tail}")
    elif gate in ("user-active", "resolve-open") and total:
        left = max(total - done - failed, 0)
        lines.append(f"{label.capitalize()} indexing waits until you're away: "
                     f"{left} {unit}s queued")
    elif gate == "paused" and total:
        lines.append(f"{label.capitalize()} indexing paused: "
                     f"{max(total - done - failed, 0)} {unit}s left")

    upload_left = int(ingest.get("upload_left") or 0)
    if ingest.get("upload_paused") and upload_left:
        lines.append(f"Uploading indexed {label} is paused: {upload_left} left")
    elif upload_left:
        lines.append(f"Uploading indexed {label}… {upload_left} {unit}(s) left")
    if failed and total:
        lines.append(f"{failed} {label} {unit}(s) could not be indexed. See the log")
    return lines


def _ingest_fingerprint(ingest: Optional[dict]) -> tuple:
    """The parts of the ingest state that change which LINES the menu has.

    NEVER the percentage, and the counts BUCKETED -- _proxy_fingerprint's rule
    and its reason: a rebuild per finished clip destroys a menu the editor may
    have open, and the live numbers belong in the tooltip, which is a plain
    NIM_MODIFY and safe at any time.
    """
    if not isinstance(ingest, dict) or not ingest:
        return ()
    total = int(ingest.get("total") or 0)
    done = int(ingest.get("done") or 0)
    return (
        str(ingest.get("gate") or ""),
        str(ingest.get("warning") or ""),
        bool(ingest.get("batch_uid")),
        bool(ingest.get("paused")),
        bool(ingest.get("upload_paused")),
        total,
        # In tens: enough movement to be worth a rebuild on a 400-clip batch,
        # not one per clip.
        done // 10,
        int(ingest.get("failed") or 0),
        # Present-or-not, not the number: the "Downloading the model" LINE
        # exists or it does not, and its percentage is tooltip material.
        ingest.get("model_download_percent") is not None,
        bool(int(ingest.get("upload_left") or 0)),
    )


def _with_ingest_suffix(text: str, snap: dict) -> str:
    """Append "· indexing b-roll 12/40" when there is room.

    The tooltip is where the LIVE count lives (the menu deliberately does not
    rebuild per clip -- see _ingest_fingerprint), so this is the one place an
    editor watches the number move.
    """
    for key, label in (("broll_ingest", "b-roll"), ("music_ingest", "music")):
        ingest = snap.get(key)
        if not isinstance(ingest, dict) or not ingest:
            continue
        percent = ingest.get("model_download_percent")
        if percent is not None:
            suffix = f" · fetching the {label} model {int(percent)}%"
        elif ingest.get("gate") == "running":
            suffix = (f" · indexing {label} {int(ingest.get('done') or 0)}/"
                      f"{int(ingest.get('total') or 0)}")
        else:
            continue
        # ONE suffix, whichever kind is working: the tooltip is 63 characters
        # on win32 and two of these would push the sync state -- the thing the
        # tooltip is for -- off the end.
        combined = text + suffix
        return combined if len(combined) <= TOOLTIP_LIMIT else text
    return text


def _proxy_fingerprint(gap: Optional[dict]) -> tuple:
    """The parts of the proxy gap that change which LINES the menu has.

    `left` is deliberately NOT in here. It ticks down once per finished clip
    -- potentially every few seconds on a fast machine -- and every change
    would rebuild the menu, which on the win32 backend DestroyMenu()s a menu
    the user may have open (freeze) and re-resolves their click against the
    new callback list (wrong action). The live number goes in the TOOLTIP,
    which is a plain NIM_MODIFY and safe at any time -- the same split
    _progress_bucket() makes for transfer progress.

    The two history lines are here BUCKETED, for exactly that reason: they
    are worth showing (a run of hundreds that never updates reads as a stuck
    companion) and not worth a rebuild per clip.
    """
    if not isinstance(gap, dict):
        return ()
    today = (_proxy_history(gap).get("today") or {})
    try:
        made = int(today.get("done") or 0) // MADE_TODAY_BUCKET
        failed = int(today.get("failed") or 0)
    except (TypeError, ValueError):
        made, failed = 0, 0
    eta = _proxy_history(gap).get("eta_seconds")
    try:
        eta_bucket = int(float(eta) // ETA_BUCKET_SECONDS) if eta else None
    except (TypeError, ValueError):
        eta_bucket = None
    return (
        int(gap.get("missing") or 0),
        int(gap.get("braw") or 0),
        bool(gap.get("encoding")),
        bool(gap.get("can_generate")),
        made,
        # NOT bucketed: failures are rare, and the first one of a night is
        # the whole point of the line.
        failed,
        eta_bucket,
        # Whether the ledger has anything in it at all: on a machine that
        # cannot generate, that is what decides whether the "Proxies this
        # machine has made…" item EXISTS, and a structural change nothing
        # hashes is an item that never appears (UI-3's family).
        bool(_proxy_history(gap).get("last_at")),
    )


# Windows truncates a tray tooltip at ~127 characters, so the proxy suffix
# is only added while the whole string stays comfortably under that: a
# half-eaten "· 12 need pro" reads like a bug, and this line is the LEAST
# important thing the tooltip can say.
TOOLTIP_LIMIT = 120


def _leading_percent(gap: Optional[dict]) -> Optional[int]:
    """The highest per-clip percentage among the encodes in flight, or None.

    None covers every "cannot say yet" -- an ffmpeg that has not emitted a
    progress block, a source with no probed duration, an older generator
    with no `encoding_detail` at all -- and the tooltip then simply omits it
    rather than showing a 0% that never moves.
    """
    if not isinstance(gap, dict):
        return None
    best: Optional[int] = None
    for entry in gap.get("encoding_detail") or ():
        if not isinstance(entry, dict):
            continue
        try:
            percent = entry.get("percent")
            if percent is None:
                continue
            value = int(percent)
        except (TypeError, ValueError):
            continue
        if best is None or value > best:
            best = value
    return best


def _with_proxy_suffix(text: str, snap: dict) -> str:
    """Append "· 12 need proxies" when there is room and nothing louder.

    The tooltip is where the LIVE count lives (the menu deliberately doesn't
    rebuild per clip -- see _proxy_fingerprint), so this is the one place an
    editor watches the number go down. `left` while encoding, `missing`
    otherwise: mid-run "12 need proxies" would be counting work already done.
    """
    gap = snap.get("proxy_gap")
    if not isinstance(gap, dict):
        return text
    if gap.get("encoding"):
        count = int(gap.get("left") or 0)
        suffix = f" · making {count} proxy file(s)" if count else " · making proxies"
        # The percentage of the clip that is FURTHEST ALONG. One number, not
        # four: the drain runs up to 4 wide and the tooltip has ~120
        # characters for everything, and "the next one lands soon" is what an
        # editor watching this actually wants to know.
        percent = _leading_percent(gap)
        if percent is not None:
            suffix += f", next at {percent}%"
    else:
        count = int(gap.get("missing") or 0)
        if count <= 0:
            return text
        suffix = f" · {count} need proxies" if count != 1 else " · 1 needs a proxy"
    combined = text + suffix
    return combined if len(combined) <= TOOLTIP_LIMIT else text


def _tooltip_text(snap: dict) -> str:
    """The hover tooltip: the LIVE numbers, updated every refresh (a title
    update is a plain Shell_NotifyIcon NIM_MODIFY -- unlike a menu rebuild
    it can never disturb an open menu). Windows truncates at ~127 chars.

    The proxy-gap suffix is added ONLY to the two calm endings (syncing, up
    to date): everything above them -- not set up, drive gone, not signed in,
    paused, a lane in PROBLEM -- is a state where nothing syncs at all, and
    appending "12 need proxies" to it would bury the sentence that matters."""
    if snap["problems"]:
        return "CCSync: NOT SET UP (nothing syncs)"
    if snap.get("root_absent"):
        owed = str(snap.get("root_unfinished") or "")
        if owed:
            # Windows truncates the tooltip at ~127 chars; the summary is
            # bounded (three lanes, one byte figure) but not short.
            return (f"CCSync: PAUSED ({drive_absent_phrase(snap.get('root_state'))}, "
                    f"{owed} still to go)")[:120]
        return f"CCSync: PAUSED ({drive_absent_phrase(snap.get('root_state'))})"
    if not snap["signed_in"] and snap.get("require_login", True):
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
            return _with_ingest_suffix(
                _with_proxy_suffix(" · ".join(parts), snap), snap)[:127]
    # APP-1 (2026-09-04): "up to date" is a CLAIM, and it was made without ever
    # reading the one field that knows better. Everything above this point is a
    # state the tooltip already described; anything left that sync_guard calls
    # blocked (a 401'd reporter, a clock 40 minutes out, a dead sync engine, a
    # project folder that moved) reached this line and was reported as caught
    # up. The detail is the same sentence the menu's Sync: line and the fleet
    # grid show, so there is one wording, not a third.
    blocked = (snap.get("sync_guard") or {}).get("blocked") or {}
    if isinstance(blocked, dict) and blocked.get("detail"):
        return f"CCSync: {blocked['detail']}"[:127]
    # Indexing SECOND, so on a machine doing both the proxy count (the older,
    # more familiar number) is the one that survives the length limit.
    return _with_ingest_suffix(_with_proxy_suffix("CCSync: up to date", snap), snap)


# -- shared actions (2026-08-27, the Settings-window split) -----------------
#
# Every action the OLD menu could trigger is now a plain function of `app`
# (plus whatever small extra it needs -- a URL, a slug, a snapshot for a
# confirm dialog's wording). _build_menu's (icon, item) closures and
# settings_window.py's button commands both call these directly, so there is
# exactly ONE place that knows what "Sync now" or "Remove a project" does --
# see settings_window.py for the other caller. Each one is exactly the body
# the old inline `on_*` closure had; nothing about WHAT they do changed here,
# only WHERE they live.


def action_sync_now(app: "CompanionApp") -> None:
    _spawn(app, "Sync now", app.sync_now)


def action_scan_whole_project(app: "CompanionApp") -> None:
    _spawn(app, "Scan whole project", app.scan_whole_project)


def action_consolidate_project(app: "CompanionApp") -> None:
    _spawn(app, "Bring an existing project's media in", app.consolidate_project)


def action_undo_last_relink(app: "CompanionApp") -> None:
    _spawn(app, "Undo the last clip-path change", app.undo_last_relink)


def action_share_luts(app: "CompanionApp") -> None:
    _spawn(app, "Share LUTs", app.share_stray_luts)


def action_make_proxies(app: "CompanionApp") -> None:
    # _spawn like every other action: this one forces a full tree scan on
    # the generator's thread, and the caller must not wait for it.
    _spawn(app, "Make proxies now",
           getattr(app, "generate_proxies_now", None) or (lambda: None))


def action_stop_proxies(app: "CompanionApp") -> None:
    _spawn(app, "Stop making proxies",
           getattr(app, "stop_proxy_generation", None) or (lambda: None))


def action_show_proxy_progress(app: "CompanionApp") -> None:
    # A WINDOW, not a toast (2026-08-18, at the owner's request): a six-
    # hour encode behind two lines of text is the "lack of feedback" this
    # answers. It opens on its own thread and never blocks this one.
    _spawn(app, "Show proxy progress",
           getattr(app, "show_proxy_progress", None) or (lambda: None))


def action_index_broll_now(app: "CompanionApp") -> None:
    _spawn(app, "Index b-roll now",
           getattr(app, "index_broll_now", None) or (lambda: None))


def action_pause_broll_ingest(app: "CompanionApp") -> None:
    _spawn(app, "Pause b-roll indexing",
           getattr(app, "pause_broll_ingest", None) or (lambda: None))


def action_resume_broll_ingest(app: "CompanionApp") -> None:
    _spawn(app, "Resume b-roll indexing",
           getattr(app, "resume_broll_ingest", None) or (lambda: None))


def action_cancel_broll_ingest(app: "CompanionApp") -> None:
    # CONFIRMED in the app (it opens a dialog), which is why it goes
    # through _spawn like every other action rather than running on the
    # message loop.
    _spawn(app, "Cancel the b-roll batch",
           getattr(app, "cancel_broll_ingest", None) or (lambda: None))


def action_show_ingest_progress(app: "CompanionApp") -> None:
    _spawn(app, "Show indexing progress",
           getattr(app, "show_ingest_progress", None) or (lambda: None))


def action_index_music_now(app: "CompanionApp") -> None:
    _spawn(app, "Index music now",
           getattr(app, "index_music_now", None) or (lambda: None))


def action_pause_music_ingest(app: "CompanionApp") -> None:
    _spawn(app, "Pause music indexing",
           getattr(app, "pause_music_ingest", None) or (lambda: None))


def action_resume_music_ingest(app: "CompanionApp") -> None:
    _spawn(app, "Resume music indexing",
           getattr(app, "resume_music_ingest", None) or (lambda: None))


def action_cancel_music_ingest(app: "CompanionApp") -> None:
    # CONFIRMED in the app (it opens a dialog), which is why it goes
    # through _spawn like every other action.
    _spawn(app, "Cancel the music batch",
           getattr(app, "cancel_music_ingest", None) or (lambda: None))


def action_show_music_ingest_progress(app: "CompanionApp") -> None:
    _spawn(app, "Show music indexing progress",
           getattr(app, "show_music_ingest_progress", None) or (lambda: None))


def action_proxy_history(app: "CompanionApp") -> None:
    # Rendering the report reads the ledger off disk, so it goes through
    # _spawn like every other action, and _open_log does the platform launch
    # (and the sanitized child env) exactly as it does for the log itself.
    _spawn(app, "Proxy history", lambda: _open_log(
        (getattr(app, "proxy_history_report", None) or (lambda: ""))()
    ))


def action_toggle_pause(app: "CompanionApp") -> None:
    # _spawn, not _guarded: this used to run ON the tray's message loop
    # (win32), and toggle_pause can hold sequencer/Syncthing config writes
    # for many seconds -- the whole tray froze until it returned (seen live
    # 2026-07-26). Still true from a Settings button command, which runs on
    # Tk's event loop.
    _spawn(app, "Pause/resume", app.toggle_pause)


def action_volunteer(app: "CompanionApp", snap: Optional[dict] = None) -> None:
    """Lend this machine to the fleet for a while, or take it back.

    _spawn like every other action: volunteer() itself is a lock and a clock,
    but the notification behind it is a Shell_NotifyIcon call and the tray's
    own message loop is the one thread nothing may block (2026-07-26)."""
    volunteering = bool((snap or {}).get("jobs_volunteer_until"))
    runner = getattr(app, "job_runner", None)
    if runner is None:
        return

    def switch() -> None:
        if volunteering:
            runner.volunteer(0)
            _notify(app, "Back to taking fleet jobs only while you are away.")
            return
        minutes = int((snap or {}).get("jobs_volunteer_minutes")
                      or getattr(runner, "volunteer_minutes", 30) or 30)
        runner.volunteer(None)
        _notify(app, f"Taking fleet jobs for the next {minutes} minutes, "
                     f"even while you work.")

    _spawn(app, "Volunteer", switch)


def action_resume_lane_b(app: "CompanionApp", snap: dict) -> None:
    # Confirm first: resuming is the operator asserting the server is
    # fine, and the breaker exists precisely because nothing else can
    # tell (item 9).
    _spawn(app, "Resume proxy download", lambda: _confirm_resume_lane_b(app, snap))


def action_halt_sync(app: "CompanionApp") -> None:
    _spawn(app, "Stop all syncing", lambda: _confirm_halt(app))


def action_release_halt(app: "CompanionApp") -> None:
    _spawn(app, "Start syncing again", lambda: _release_halt(app))


def action_open_dashboard(app: "CompanionApp", url: str) -> None:
    _spawn(app, "Open dashboard", lambda: _open_dashboard(url, app))


def action_open_log(app: "CompanionApp") -> None:
    _spawn(app, "Open log", lambda: _open_log(app.log_path))


def action_copy_diagnostics(app: "CompanionApp") -> None:
    _spawn(app, "Copy diagnostics for your admin", app.copy_diagnostics)


def action_open_sync_drive(app: "CompanionApp") -> None:
    _spawn(app, "Open my sync drive",
           lambda: _open_log(str(app.config.get("local_root", ""))))


def action_sign_in(app: "CompanionApp") -> None:
    _spawn(app, "Sign in", lambda: _show_sign_in_dialog(app))


def action_youtube_sign_in(app: "CompanionApp") -> None:
    _spawn(app, "Sign in to YouTube", lambda: _youtube_sign_in(app))


def action_youtube_cookies_file(app: "CompanionApp") -> None:
    _spawn(app, "YouTube cookies file", lambda: _install_youtube_cookies(app))


def action_youtube_terms(app: "CompanionApp") -> None:
    _spawn(app, "Accept YouTube Terms", lambda: _show_youtube_terms_dialog(app))


def action_sign_out(app: "CompanionApp") -> None:
    _spawn(app, "Sign out", lambda: _on_sign_out(app))


def action_update_now(app: "CompanionApp") -> None:
    _spawn(app, "Update now", lambda: _show_update_dialog(app))


def action_accept_licence(app: "CompanionApp") -> None:
    # force=True: this IS the editor asking again after declining or
    # closing the dialog, and the once-per-run gate must not eat it.
    _spawn(app, "Accept the licence agreement",
           lambda: app.prompt_licence_acceptance(force=True))


def action_setup_project(app: "CompanionApp") -> None:
    _spawn(app, "Set up project",
           lambda: getattr(app, "setup_current_project", lambda: None)())


def action_grade_swap(app: "CompanionApp", snap: dict) -> None:
    to_server = snap.get("p_mode") != "server"
    _spawn(app, "Grade swap", lambda: _confirm_grade_swap(app, to_server))


def action_remove_project(app: "CompanionApp", slug: str, rel: str) -> None:
    _spawn(app, "Remove project", lambda: _confirm_remove_project(app, slug, rel))


def _build_menu(app: "CompanionApp", snap: Optional[dict] = None) -> "tray_backend.Menu":
    """The right-click menu, reduced to what an editor needs WITHOUT opening
    a window (2026-08-27): who they are, whatever is blocking them, one line
    of sync state, Resolve's state, the handful of actions used every day,
    and Settings for everything else. The three lane lines, every advisory
    line, YouTube, Advanced and its submenu all moved to settings_window.py
    -- see its module docstring for where each one landed."""
    if snap is None:
        snap = _tray_snapshot(app)

    signed_in = snap["signed_in"]

    def on_sync_now(icon, item):
        action_sync_now(app)

    def on_toggle_pause(icon, item):
        action_toggle_pause(app)

    def on_volunteer(icon, item):
        action_volunteer(app, snap)

    def on_open_sync_drive(icon, item):
        action_open_sync_drive(app)

    def on_open_dashboard(icon, item):
        action_open_dashboard(app, snap["dashboard_url"])

    def on_open_settings(icon, item):
        from . import settings_window
        _spawn(app, "Settings", lambda: settings_window.show_settings(app))

    def on_quit(icon, item):
        # RES-8 (2026-09-04): ask BEFORE icon.stop(), which is the point of no
        # return -- it ends the message loop and the shutdown that follows
        # kills the copy thread inside write().
        if not _confirm_quit_while_copying(app):
            log.info("quit: the editor chose to let the copy finish")
            return
        icon.stop()
        _guarded(app, "Quit", app.shutdown)

    def on_sign_in(icon, item):
        action_sign_in(app)

    def on_sign_out(icon, item):
        action_sign_out(app)

    def on_update_now(icon, item):
        action_update_now(app)

    def on_accept_licence(icon, item):
        action_accept_licence(app)

    def on_setup_project(icon, item):
        action_setup_project(app)

    def on_share_luts(icon, item):
        action_share_luts(app)

    def on_resume_lane_b(icon, item):
        action_resume_lane_b(app, snap)

    def on_release_halt(icon, item):
        action_release_halt(app)

    dashboard_items = (
        [tray_backend.MenuItem("Open dashboard", on_open_dashboard)]
        if snap["dashboard_url"] else []
    )

    # "nothing syncs until you do" is only TRUE when login is required. With
    # require_login=false the lanes are already running under editor_name, and
    # telling the editor otherwise sends them chasing a sign-in they don't
    # need -- the same check compute_overall_color() already makes.
    sign_in_label = (
        "► Sign in… (nothing syncs until you do)"
        if snap.get("require_login", True) else "Sign in…"
    )
    # Signed in: the identity line alone -- Sign out lives in Settings (the
    # approved 2026-08-27 menu). Signed out: the prompt stays one click away,
    # because nothing syncs until it is answered.
    identity_items = [tray_backend.MenuItem(snap["identity_label"], None, enabled=False)]
    if not signed_in:
        identity_items.append(tray_backend.MenuItem(sign_in_label, on_sign_in))

    # -- the conditional block: blockers and prompts, in one bracketed group
    # (2026-08-27). Each of these used to carry its OWN trailing separator so
    # it could stand alone in the old, longer menu; now they are bracketed by
    # ONE pair of hard separators (see the Menu(...) call below) whether the
    # block is empty or full, so the shape never wobbles as items appear and
    # disappear.
    problem_items = []
    if snap["problems"]:
        problem_items = [tray_backend.MenuItem(
            "⚠ NOT SET UP: nothing will sync (Settings > COPY DIAGNOSTICS FOR YOUR ADMIN)",
            None, enabled=False,
        )]

    # THE ONE THING BLOCKING EVERYTHING (2026-08-18): present only while the
    # licence gate is live. Vanishes the moment it is accepted.
    licence_items = (
        [tray_backend.MenuItem("► Accept the licence agreement to start syncing…",
                               on_accept_licence)]
        if snap.get("eula_problem") else []
    )

    # Present only while the open Resolve project has no server-side root
    # (see project_setup.py) -- clicking opens the /project-setup deep link.
    # A blocker-ish onboarding prompt, so it stays in this block rather than
    # moving to Settings with the rest of the project-state lines.
    setup_name = snap["setup_name"]
    setup_items = (
        [tray_backend.MenuItem(f"Set up '{setup_name}' on the server…", on_setup_project)]
        if setup_name else []
    )

    # Present only while this machine holds LUTs the shared library doesn't.
    # A "something to do" prompt, same reasoning as setup_items above.
    stray_luts = int(snap.get("stray_luts") or 0)
    lut_items = (
        [tray_backend.MenuItem(
            f"► {stray_luts} LUT{'s' if stray_luts != 1 else ''} only on this machine: "
            f"share with the team", on_share_luts,
        )]
        if stray_luts else []
    )

    # The two safety-latch actions (COMMERCIAL_READINESS.md item 9,
    # 2026-08-17): the RESUME action exists only while the breaker is
    # tripped, and the halt-release item only while a LOCAL halt is active
    # (a FLEET halt offers no local release -- only the dashboard can clear
    # it, and an item that always answers "your administrator has to do
    # this" is worse than no item).
    guard = snap.get("sync_guard") or {}
    breaker_items = (
        [tray_backend.MenuItem("► Resume proxy download…", on_resume_lane_b)]
        if ((guard.get("lane_b_breaker") or {}).get("tripped")
            # ...and for a free-space park, through the SAME action (SYS-5 /
            # SYNC-7): from the editor's side both are "proxy download is
            # stopped and I have done something about it".
            or (guard.get("disk_floor") or {}).get("parked")) else []
    )
    halt_active = bool((guard.get("halt") or {}).get("active"))
    halt_is_fleet = (guard.get("halt") or {}).get("scope") == "fleet"
    halt_release_items = (
        [tray_backend.MenuItem("► Start syncing again", on_release_halt)]
        if halt_active and not halt_is_fleet else []
    )

    # The label is NOT "Update available" unconditionally: the dashboard
    # advertises whatever it publishes as `current`, newer or older (see
    # upgrade.py's "different, not newer"). This rig ran v0.4.5 while the
    # dashboard still published v0.4.3, and the tray offered "Update
    # available → v0.4.3 (install)" -- one click from a silent DOWNGRADE
    # that reintroduced a round of security fixes (seen live 2026-07-25).
    upgrade_info = snap["upgrade_info"]
    upgrade_items = (
        [tray_backend.MenuItem(upgrade_mod.offer_label(upgrade_info["version"]), on_update_now)]
        if upgrade_info else []
    )

    conditional_items = [
        *problem_items, *licence_items, *setup_items, *lut_items,
        *breaker_items, *halt_release_items, *upgrade_items,
    ]

    # "Use this machine NOW" (section 10, 2026-08-30). The admin's lever is a
    # forced job; this is the one the person sitting here pulls, and it is
    # deliberately theirs alone -- they are the one who knows whether they
    # mind their GPU being borrowed for the next half hour. Absent on a
    # companion with no job runner, or one with fleet jobs switched off.
    volunteering = bool(snap.get("jobs_volunteer_until"))
    volunteer_items = (
        [tray_backend.MenuItem(
            _volunteer_label(snap), on_volunteer,
            checked=(lambda on: lambda item: on)(volunteering),
        )]
        if int(snap.get("jobs_volunteer_minutes") or 0) else []
    )

    # One line of sync state plus Resolve's state -- the three lane lines and
    # every advisory line that used to sit here moved to Settings.
    state_items = [
        tray_backend.MenuItem(line, None, enabled=False)
        for line in (_sync_line(snap), snap.get("resolve_line"))
        if line
    ]

    return tray_backend.Menu(
        *identity_items,
        tray_backend.Menu.SEPARATOR,
        *conditional_items,
        tray_backend.Menu.SEPARATOR,
        *state_items,
        tray_backend.Menu.SEPARATOR,
        tray_backend.MenuItem("Sync now", on_sync_now),
        *volunteer_items,
        tray_backend.MenuItem(
            "▶ Resume syncing (currently PAUSED)" if snap["paused"] else "⏸ Pause syncing",
            on_toggle_pause, checked=(lambda paused: lambda item: paused)(snap["paused"]),
        ),
        tray_backend.MenuItem("Open my sync drive", on_open_sync_drive),
        *dashboard_items,
        tray_backend.MenuItem("Settings…", on_open_settings),
        tray_backend.Menu.SEPARATOR,
        tray_backend.MenuItem("Quit CCSync (stops syncing until you next sign in)", on_quit),
    )


def start_tray(
    app: "CompanionApp",
    refresh_interval: float = 2.0,
    pulse_interval: float = PULSE_PERIOD / PULSE_STEPS,
) -> "tray_backend.Icon":
    """Start the tray icon on a background thread. Returns the Icon (call
    .stop() to remove it).

    Refresh model (2026-07-26, after the right-click/hover freezes):
      - icon color and TOOLTIP update every `refresh_interval` seconds --
        both are plain Shell_NotifyIcon modifications, safe at any time, and
        the tooltip carries the live speed/ETA numbers;
      - the MENU is rebuilt only when its fingerprint changes. Under pystray
        that was a correctness requirement -- its win32 backend
        DestroyMenu()d the live handle on every icon.menu assignment, so the
        old rebuild-every-5s loop could destroy a menu the user had open
        (freeze) and then resolve the clicked index against the NEW callback
        list (wrong action). tray_native builds the HMENU at right-click
        time, so the fingerprint is now only about not doing pointless work.

    Pulse (2026-08-10): a second, faster thread breathes the mark while the
    snapshot says so (syncing, or broken -- see should_pulse). The two loops
    share one tuple and never both own the icon; see _pulse_loop."""

    first = _tray_snapshot(app)
    guard = _MenuOpenGuard()
    guard.install()
    try:
        icon = tray_backend.Icon(
            site_mod.notify_title(),
            _icon_image_cached(first["color"]),
            _tooltip_text(first),
            menu=_build_menu(app, first),
            # getattr, not guard.flag: several tests substitute a stand-in
            # guard, and a missing flag has a defined meaning (the backend
            # keeps an Event of its own that nothing else reads).
            menu_open_flag=getattr(guard, "flag", None),
        )
    except TypeError:
        # The pystray escape hatch (CCSYNC_TRAY_BACKEND=pystray) knows nothing
        # about menu_open_flag, and neither does a test's stand-in Icon. The
        # tray then behaves as it did before 2026-07-26: is_open() stays False
        # and the loops below update unconditionally.
        icon = tray_backend.Icon(
            site_mod.notify_title(),
            _icon_image_cached(first["color"]),
            _tooltip_text(first),
            menu=_build_menu(app, first),
        )
    last_fingerprint = _menu_fingerprint(first)
    last_color = first["color"]
    last_title = _tooltip_text(first)
    # The ONLY thing the two loops share: a (color, pulsing) tuple, rebound
    # whole by the refresh loop and read whole by the pulse loop. Rebinding one
    # name is atomic under the GIL, so the reader can never see a color from
    # one tick with the pulse flag from another, and no lock is needed for it.
    pulse_state = (first["color"], bool(first.get("pulse")))

    def _refresh_loop() -> None:
        nonlocal last_fingerprint, last_color, last_title, pulse_state
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
                _maybe_warn_youtube_session(app, snap)
                pulsing = bool(snap.get("pulse"))
                pulse_state = (snap["color"], pulsing)
                if pulsing:
                    # The pulse loop owns icon.icon while it runs, so this one
                    # keeps its hands off. last_color is cleared rather than
                    # remembered: the moment the pulse stops, the comparison
                    # below trips and restores the full-brightness frame over
                    # whatever brightness the animation was left on.
                    last_color = None
                elif snap["color"] != last_color:
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

    def _pulse_loop() -> None:
        """Breathe the mark, from pre-rendered frames, one thread for the lot.

        Quiescent by construction: while the state stays steady this assigns
        NOTHING (one frame on the falling edge, then not another until the
        next pulse) -- the refresh loop's color-change assignment is the only
        writer then, and the two never fight over icon.icon.

        Everything else here is _refresh_loop's rules: never touch the icon
        while the menu is open (a NIM_MODIFY under an open menu forces a
        redraw beneath the cursor -- the 2026-07-26 hover hangs), and stop
        when icon.stop() sets _ccsync_stop.
        """
        frames: tuple = ()
        frames_color = None
        step = 0
        while not getattr(icon, "_ccsync_stop", False):
            try:
                color, pulsing = pulse_state
                # The guard covers BOTH writes. It used to sit on the pulsing
                # branch only, so the falling-edge restore NIM_MODIFYed the
                # icon under an open menu -- a ~375 ms one-shot window for the
                # 2026-07-26 hover hang, contradicting this loop's own
                # docstring (UI-4, 2026-08-11). Skipping the write leaves
                # `step` set, so the restoring frame is simply painted on the
                # first pass after the menu closes.
                if guard.is_open():
                    pass
                elif not pulsing:
                    if step:
                        # ONE assignment on the falling edge, then silence.
                        # The refresh loop restores the steady frame too, but
                        # it can lose a hair-thin race with this thread's last
                        # frame (it publishes the new state, then assigns;
                        # we may already have read the old state and be about
                        # to paint). Whoever writes last writes the same
                        # cached full-brightness image, so the icon cannot be
                        # left stuck on a dim frame.
                        icon.icon = _icon_image_cached(color)
                        step = 0
                else:
                    if color != frames_color:
                        frames = _pulse_frames(color)
                        frames_color = color
                    if frames:
                        icon.icon = frames[step % len(frames)]
                        step += 1
            except Exception:
                log.exception("tray pulse failed")
            time.sleep(pulse_interval)

    refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    refresh_thread.start()
    pulse_thread = threading.Thread(target=_pulse_loop, daemon=True)
    pulse_thread.start()

    # `_ccsync_stop` was read by the loops above and ASSIGNED NOWHERE in the
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

    if ui_dispatch.uses_main_thread():
        # macOS: NSStatusItem is main-thread-only, so the icon cannot live on
        # a worker thread the way it does on Windows. run_detached() installs
        # it against the runloop that is ALREADY the main thread's -- the one
        # ui_dispatch.serve() is about to enter (Tk-Aqua drives NSApp). This
        # is the first-Mac-run spike: if the two runloops refuse to coexist,
        # nothing here silently papers over it.
        icon.run_detached()
        # ...and if they DO coexist but the menu bar has no room, say that too
        # rather than logging "tray icon started" over an invisible icon.
        _schedule_icon_placement_check(app, icon)
    else:
        icon_thread = threading.Thread(target=icon.run, daemon=True)
        icon_thread.start()
    return icon
