"""System tray icon (pystray + Pillow) — Component 4 of SPEC.md's companion
app.

Only imported inside a try/except ImportError in app.py's run loop, so the
app still runs headless (console status logging only) if these aren't
installed — same fallback pattern as the b-roll companion's tray.py, which
this app absorbed and retired on 2026-08-10 (its server now lives in
broll_server.py; there is no second tray app any more).

Install with: pip install ccsync-companion[tray]
"""

from __future__ import annotations

import logging
import math
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
from . import ui_dispatch
from . import upgrade as upgrade_mod
from .sync.base import STATE_ERROR, STATE_PAUSED, STATE_SYNCING, LaneStatus

if TYPE_CHECKING:
    from .app import CompanionApp

log = logging.getLogger("ccsync.tray")

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
            if getattr(app, "_root_absent", False):
                # Orange, not red: nothing is broken and nothing is lost --
                # the drive is out, and plugging it back in resumes sync on
                # its own. Same visual as paused, which is what it is.
                return "orange"
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
                # ...and while we are the only thing standing between pystray
                # and user32, fix where the menu lands (see
                # _with_clamped_anchor). Positioning is adjusted BEFORE the
                # flag is set: nothing about it can block the open.
                args = _with_clamped_anchor(args)
                flag.set()
                try:
                    result = original(*args, **kwargs)
                finally:
                    flag.clear()
                _after_popup_menu(args, result)
                return result

            win.TrackPopupMenuEx = tracked
            win._ccsync_menu_open_flag = flag
        except Exception:
            log.debug("menu-open guard unavailable", exc_info=True)

    def is_open(self) -> bool:
        return self._open.is_set()


def _last_win32_error() -> int:
    """GetLastError(), or 0 if it can't be read. Only meaningful straight
    after a failed call."""
    try:
        import ctypes

        return int(ctypes.GetLastError())  # type: ignore[attr-defined]
    except Exception:
        return 0


def _after_popup_menu(args: tuple, result) -> None:
    """What pystray does not do once TrackPopupMenuEx returns.

    Two things, both invisible before this. pystray declares the function
    with no restype and no errcheck, so a FAILED call -- the handle was
    destroyed under it, or CreatePopupMenu hit the 10k USER-object quota --
    is indistinguishable from the user pressing Escape, and both are
    silence. A right-click that does nothing is the single most-reported
    tray symptom, so it gets a log line even at the cost of one per
    dismissal.

    And MSDN's TrackPopupMenu note: post WM_NULL to the owner window
    afterwards, or the menu can fail to dismiss on the following click.
    Best-effort -- a diagnostic must never be the thing that breaks the pump.
    """
    if not result:
        log.warning(
            "tray menu failed to open or was dismissed immediately "
            "(TrackPopupMenuEx returned %r, GetLastError=%d)",
            result, _last_win32_error(),
        )
    try:
        hwnd = args[4] if len(args) > 4 else None
        if hwnd:
            from pystray import _win32  # type: ignore[attr-defined]

            _win32.win32.PostMessage(hwnd, 0x0000, 0, 0)  # WM_NULL
    except Exception:
        log.debug("post-menu WM_NULL failed", exc_info=True)


# -- the menu that opens BEHIND an auto-hide taskbar ------------------------
#
# Item 21, reported on the base rig against v0.5.0 (Windows 11, taskbar set to
# auto-hide): the menu opens instantly now, and its bottom edge -- the Quit
# item -- sits under the taskbar.
#
# pystray anchors it at the raw cursor position from GetCursorPos with
# TPM_RIGHTALIGN | TPM_BOTTOMALIGN (pystray/_win32.py:215), i.e. "put the
# menu's bottom-right corner exactly HERE". Here is wherever the pointer was
# when it right-clicked the tray icon, which is inside the taskbar band, so
# the menu's bottom lands mid-taskbar by construction. Windows normally
# rescues that: TrackPopupMenuEx keeps the menu inside the monitor's WORK
# AREA, and with a docked, always-visible taskbar the work area stops at the
# taskbar's inner edge, so the menu is nudged clear of it. An auto-hide bar is
# excluded from the work area (it reserves one pixel, not its height), so the
# work area is the whole screen, nothing is violated, and the currently-raised
# topmost taskbar draws over the last item or two.
#
# v0.5.0 did not cause this -- it exposed it. Item 20's menu opened seconds
# late, mid-GIL-blackout, or not at all; where the thing you finally got landed
# was nobody's top complaint. Timing changes nothing about positioning rules:
# the same TPM flags at the same cursor point produced the same geometry
# before, on the fraction of right-clicks that opened at all.
#
# So: if the anchor point is inside the taskbar, move it to the taskbar's inner
# edge and align the menu so it grows AWAY from the bar. Everything here is
# best-effort -- a positioning nicety must never be the reason a menu fails to
# open, which is the bug this file just spent item 20 climbing out of.

# From pystray._util.win32 (repeated, not imported: this module must stay
# importable on macOS, where there is no win32 shim to import them from).
_TPM_LEFTALIGN = 0x0000
_TPM_CENTERALIGN = 0x0004
_TPM_RIGHTALIGN = 0x0008
_TPM_TOPALIGN = 0x0000
_TPM_VCENTERALIGN = 0x0010
_TPM_BOTTOMALIGN = 0x0020
# LEFT/TOP are zero, so an alignment is SET by clearing the other bits on its
# axis -- an OR alone cannot express them, and cannot undo pystray's
# RIGHT|BOTTOM either (which is exactly wrong for a top or left taskbar).
_TPM_HALIGN_MASK = _TPM_CENTERALIGN | _TPM_RIGHTALIGN
_TPM_VALIGN_MASK = _TPM_VCENTERALIGN | _TPM_BOTTOMALIGN

_ABM_GETTASKBARPOS = 0x00000005
_ABE_LEFT = 0
_ABE_TOP = 1
_ABE_RIGHT = 2
_ABE_BOTTOM = 3


def _clamp_menu_anchor(x: int, y: int, flags: int, taskbar_rect, taskbar_edge: int):
    """(x, y, flags) moved out of `taskbar_rect`, or unchanged.

    `taskbar_rect` is (left, top, right, bottom) in screen pixels and
    `taskbar_edge` one of the ABE_* constants. An anchor OUTSIDE the rect is
    returned untouched: it is only the click that lands on the bar itself
    (i.e. every tray right-click) that needs help, and a second monitor's
    cursor position must not be dragged to the primary taskbar's edge.

    The alignment flag is rewritten, not or-ed on. pystray passes
    RIGHT|BOTTOM, which is right for a bottom or right taskbar and precisely
    backwards for a top or left one -- there the menu would grow back into
    the bar it was just moved out of.

    Pure and total: no ctypes, no logging, and it never raises.
    """
    try:
        left, top, right, bottom = (int(v) for v in taskbar_rect)
        x, y, flags = int(x), int(y), int(flags)
        edge = int(taskbar_edge)
    except Exception:
        return x, y, flags
    if not (left <= x <= right and top <= y <= bottom):
        return x, y, flags
    if edge == _ABE_BOTTOM:
        return x, top, (flags & ~_TPM_VALIGN_MASK) | _TPM_BOTTOMALIGN
    if edge == _ABE_TOP:
        return x, bottom, (flags & ~_TPM_VALIGN_MASK) | _TPM_TOPALIGN
    if edge == _ABE_LEFT:
        return right, y, (flags & ~_TPM_HALIGN_MASK) | _TPM_LEFTALIGN
    if edge == _ABE_RIGHT:
        return left, y, (flags & ~_TPM_HALIGN_MASK) | _TPM_RIGHTALIGN
    return x, y, flags   # an edge we don't know is an edge we don't touch


def _taskbar_geometry():
    """((left, top, right, bottom), edge) for the primary taskbar, or None.

    SHAppBarMessage(ABM_GETTASKBARPOS) reports the bar's SHOWN rectangle even
    while an auto-hide bar is hidden off-screen, which is the whole point:
    that rectangle is the region the raised bar will cover, and the region the
    menu has to clear.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _APPBARDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT),
                ("lParam", wintypes.LPARAM),
            ]

        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(_APPBARDATA)
        if not ctypes.windll.shell32.SHAppBarMessage(  # type: ignore[attr-defined]
            _ABM_GETTASKBARPOS, ctypes.byref(data)
        ):
            return None
        rect = (int(data.rc.left), int(data.rc.top),
                int(data.rc.right), int(data.rc.bottom))
        return rect, int(data.uEdge)
    except Exception:
        log.debug("taskbar geometry unavailable", exc_info=True)
        return None


def _anchor_clear_of_taskbar(x: int, y: int, flags: int):
    """_clamp_menu_anchor against the live taskbar; the originals on any
    failure -- no geometry, a shell that will not answer, a pystray we no
    longer recognise. The menu opens where it opened before, which is the
    version of this bug we can live with."""
    try:
        geometry = _taskbar_geometry()
        if geometry is None:
            return x, y, flags
        rect, edge = geometry
        return _clamp_menu_anchor(x, y, flags, rect, edge)
    except Exception:
        log.debug("taskbar anchor adjustment skipped", exc_info=True)
        return x, y, flags


def _with_clamped_anchor(args: tuple) -> tuple:
    """pystray calls TrackPopupMenuEx(hmenu, flags, x, y, hwnd, None) with
    every argument positional (pystray/_win32.py:215). Any other shape --
    a test calling it bare, a pystray that has moved to keywords -- is passed
    through untouched rather than guessed at."""
    try:
        if len(args) < 4:
            return args
        flags, x, y = args[1], args[2], args[3]
        new_x, new_y, new_flags = _anchor_clear_of_taskbar(x, y, flags)
        if (new_x, new_y, new_flags) == (x, y, flags):
            return args
        return (args[0], new_flags, new_x, new_y) + tuple(args[4:])
    except Exception:
        log.debug("menu anchor left as pystray asked for it", exc_info=True)
        return args


# -- the menu swap: build new, swap, THEN destroy old -----------------------
#
# pystray's win32 _update_menu DestroyMenu()s the live handle FIRST, rebuilds
# ~30 items plus a submenu, and only then publishes the new handle. For that
# whole window `_menu_handle` names a destroyed HMENU, and a right-click
# arriving inside it hands that to TrackPopupMenuEx, which returns 0 and
# shows nothing (silently -- see _after_popup_menu above). Worse, it is
# called from two threads that know nothing of each other: our refresh loop
# on every `icon.menu = ...`, and pystray's own _base.Icon.__call__ /
# _base._handler on the PUMP thread after every left-click and every menu
# selection. Two of those interleaving DestroyMenu the same handle twice and
# leak the other one's; at the 10 000-handle USER quota CreatePopupMenu
# starts failing, `_menu_handle` goes None, and right-click does nothing at
# all until the companion is restarted.
#
# So: one lock, build first, swap, destroy last, and never destroy anything
# the icon is still pointing at. The residual race is a right-click that read
# `_menu_handle` microseconds before a swap, instead of one landing anywhere
# inside a whole rebuild.
_MENU_SWAP_LOCK = threading.Lock()

# Sentinel for "no menu has been built yet" -- None is a legitimate menu.
_NO_MENU_BUILT = object()


def _destroy_menu(handle) -> None:
    """DestroyMenu, looked up at call time so a pystray without the win32
    shim (or a test standing in for it) degrades to a no-op."""
    try:
        from pystray import _win32  # type: ignore[attr-defined]

        _win32.win32.DestroyMenu(handle)
    except Exception:
        log.debug("DestroyMenu(%r) failed", handle, exc_info=True)


def _atomic_update_menu(icon, stock=None) -> None:
    """pystray's Icon._update_menu, reordered so the handle is always live.

    Falls back to `stock` (the wrapped original) whenever the internals this
    depends on aren't there -- same fail-open posture as _MenuOpenGuard.
    """
    create = getattr(icon, "_create_menu", None)
    if create is None:
        if stock is not None:
            stock(icon)
        return
    with _MENU_SWAP_LOCK:
        menu = getattr(icon, "menu", None)
        previous = getattr(icon, "_ccsync_built_menu", _NO_MENU_BUILT)
        if previous is menu and getattr(icon, "_menu_handle", None) is not None:
            # pystray calls update_menu() after every left-click and every
            # menu selection, with the menu object untouched, so it can
            # re-render dynamic items. _build_menu renders a SNAPSHOT -- even
            # the Pause checkmark closes over a captured bool -- so an
            # identical menu object can only produce an identical menu, and
            # rebuilding it is pure USER-object churn. Identity changes only
            # when _refresh_loop's fingerprint really moved.
            return
        callbacks: list = []
        try:
            handle = create(menu, callbacks)
        except Exception:
            log.warning("tray menu rebuild failed -- keeping the menu already shown",
                        exc_info=True)
            return
        if not handle and menu:
            # CreatePopupMenu failed (the classic cause is the USER-object
            # quota this reordering exists to stop leaking into). The old
            # handle still works; a menu one refresh out of date beats none.
            # A falsy `menu` is a different thing -- pystray's _create_menu
            # returns None for one by contract -- and is published below.
            log.warning("tray menu rebuild produced no handle -- keeping the previous menu")
            return
        old = getattr(icon, "_menu_handle", None)
        icon._menu_handle = (handle, callbacks) if handle else None
        icon._ccsync_built_menu = menu
        if old:
            _destroy_menu(old[0])


class _MenuSwapGuard:
    """Installs _atomic_update_menu over pystray's win32 backend.

    Install-once, win32-only, never-raise -- the same shape and the same
    reasoning as _MenuOpenGuard above. On any other backend, or a pystray
    whose internals have moved, this is a no-op and the stock behavior
    stands.
    """

    def install(self) -> None:
        try:
            if sys.platform != "win32":
                return
            from pystray import _win32  # type: ignore[attr-defined]

            icon_cls = _win32.Icon
            if getattr(icon_cls, "_ccsync_atomic_menu_swap", False):
                return
            stock = icon_cls._update_menu

            def _update_menu(self) -> None:
                _atomic_update_menu(self, stock)

            icon_cls._update_menu = _update_menu
            icon_cls._ccsync_atomic_menu_swap = True
        except Exception:
            log.debug("atomic menu swap unavailable", exc_info=True)


# One rendered image per (color, brightness level) -- regenerating the
# identical 64x64 PIL image (and the win32 HICON pystray derives from it)
# every refresh tick was pure GDI churn, and the pulse below would repeat that
# eight times every three seconds forever. Every frame of every color is
# rendered at most once per process.
_ICON_IMAGE_CACHE: dict = {}

# The tray mark, white-on-transparent so it can be tinted per status. Shipped
# by build.spec's datas; assets/icon.png and icon.ico are the same mark for
# window/exe use and are NOT interchangeable with this one (they are already
# colored and pre-composed).
MARK_ASSET = "cc_mark_white.png"

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
    """Where cc_mark_white.png lives in this build, or None. Its own function
    so a test can point it somewhere else (and so the fallback below is
    reachable)."""
    return theme.asset_path(MARK_ASSET)


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
    """The Creators Club mark alone, tinted the status color, on transparency.

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


def classify_lane_error(last_error: Optional[str], root_absent: bool = False) -> str:
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
        return ("Your Creators Club drive is disconnected, so syncing is paused. "
                "Plug it back in and it resumes on its own -- nothing was deleted.")
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
    status: LaneStatus, paused: bool, problems: bool, root_absent: bool = False
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
        return f"{label}: PAUSED — drive disconnected"
    if problems:
        return f"{label}: NOT SYNCING (this machine isn't set up yet)"
    if paused:
        return f"{label}: PAUSED"
    if status.state == STATE_ERROR:
        return (f"{label}: PROBLEM. "
                f"{classify_lane_error(status.last_error, root_absent=root_absent)}")
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


# -- "the icon started, but is anyone seeing it?" (macOS) --------------------
#
# MAC-7. pystray reports success as soon as the NSStatusItem exists, and on a
# full menu bar that is a lie: macOS hands the item a frame in the menu bar
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
    # master=root, NOT the default root. A Tk variable binds to the
    # interpreter of its master, and on macOS the default root is
    # ui_dispatch's hidden one -- a DIFFERENT interpreter from this dialog.
    # Masterless, the Entry wrote "alex" into this root's PY_VAR0 while
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
        root.title("CCSYNC.EXE: Resolve scripting is down")
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
        return f"Resolve: not connected right now — {reason}"
    return f"Resolve: NOT CONNECTED this session — {reason}"


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
    _get("dashboard_url", lambda: _dashboard_url(app), "")
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
    _get("p_swap_available", lambda: (getattr(app, "p_swap_available", None) or (lambda: False))(), False)
    _get("p_mode", lambda: (getattr(app, "p_mapping_mode", None) or (lambda: "none"))(), "none")
    snap["color"] = compute_overall_color(statuses, app)
    _get("pulse", lambda: should_pulse(snap["color"], statuses), False)
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
        snap["problems"], snap.get("root_absent"),
        snap["sequencer_line"], snap["current_project_line"],
        snap.get("resolve_line"),
        snap["setup_name"], (snap["upgrade_info"] or {}).get("version"),
        snap["dashboard_url"], snap["color"],
        tuple(sorted(p.get("slug", "") for p in snap.get("removable", []))),
        snap.get("p_swap_available"), snap.get("p_mode"),
        # The stray-LUT count decides whether the "N LUTs only on this
        # machine" item exists at all, and on an otherwise-idle machine
        # nothing else here moves when a LUT is dropped into Resolve's own
        # folder -- so without this the whole shared-LUT onboarding item was
        # unreachable until something unrelated changed, and lingered after
        # share_stray_luts took the count back to 0 (UI-3, 2026-08-11).
        int(snap.get("stray_luts") or 0),
        _proxy_fingerprint(snap.get("proxy_gap")),
    )


def _proxy_fingerprint(gap: Optional[dict]) -> tuple:
    """The parts of the proxy gap that change which LINES the menu has.

    `left` is deliberately NOT in here. It ticks down once per finished clip
    -- potentially every few seconds on a fast machine -- and every change
    would rebuild the menu, which on the win32 backend DestroyMenu()s a menu
    the user may have open (freeze) and re-resolves their click against the
    new callback list (wrong action). The live number goes in the TOOLTIP,
    which is a plain NIM_MODIFY and safe at any time -- the same split
    _progress_bucket() makes for transfer progress.
    """
    if not isinstance(gap, dict):
        return ()
    return (
        int(gap.get("missing") or 0),
        int(gap.get("braw") or 0),
        bool(gap.get("encoding")),
        bool(gap.get("can_generate")),
    )


# Windows truncates a tray tooltip at ~127 characters, so the proxy suffix
# is only added while the whole string stays comfortably under that: a
# half-eaten "· 12 need pro" reads like a bug, and this line is the LEAST
# important thing the tooltip can say.
TOOLTIP_LIMIT = 120


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
        return "CCSync: PAUSED — your drive is disconnected"
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
            return _with_proxy_suffix(" · ".join(parts), snap)[:127]
    return _with_proxy_suffix("CCSync: up to date", snap)


def _build_menu(app: "CompanionApp", snap: Optional[dict] = None) -> "pystray.Menu":
    if snap is None:
        snap = _tray_snapshot(app)
    statuses = snap["statuses"]
    lane_items = [
        pystray.MenuItem(
            _format_lane_line_from(
                s, paused=snap["paused"], problems=snap["problems"],
                root_absent=bool(snap.get("root_absent")),
            ),
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

    def on_share_luts(icon, item):
        _spawn(app, "Share LUTs", app.share_stray_luts)

    def on_make_proxies(icon, item):
        # _spawn like every other action: this one forces a full tree scan on
        # the generator's thread, and the tray must not wait for it.
        _spawn(app, "Make proxies now",
               getattr(app, "generate_proxies_now", None) or (lambda: None))

    def on_stop_proxies(icon, item):
        _spawn(app, "Stop making proxies",
               getattr(app, "stop_proxy_generation", None) or (lambda: None))

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
    # Present only while this machine holds LUTs the shared library doesn't.
    # Same conditional-item pattern as the upgrade offer above: it appears
    # when there is something to do and vanishes once there isn't.
    stray_luts = int(snap.get("stray_luts") or 0)
    lut_items = (
        [pystray.MenuItem(
            f"► {stray_luts} LUT{'s' if stray_luts != 1 else ''} only on this machine — "
            f"share with the team", on_share_luts,
        ), pystray.Menu.SEPARATOR]
        if stray_luts else []
    )
    # Missing proxies (proxy_gen.py). ADVISORY lines only -- no icon color,
    # no pulse (tray.py:78-85's stance): an original with no proxy is not a
    # fault, it is footage the rest of the fleet cannot see yet, and the
    # sentence has to say that rather than name a file format.
    proxy_gap = snap.get("proxy_gap") or {}
    proxy_missing = int(proxy_gap.get("missing") or 0)
    proxy_braw = int(proxy_gap.get("braw") or 0)
    proxy_encoding = bool(proxy_gap.get("encoding"))
    proxy_left = int(proxy_gap.get("left") or 0)
    proxy_lines: list[str] = []
    if proxy_encoding:
        # "stops when you're back" is the whole promise of the feature, and
        # it is the answer to the question this line provokes ("is that why
        # my machine is busy?"). The count is a bucketed rebuild, not a live
        # ticker -- see _proxy_fingerprint.
        proxy_lines.append(f"Making proxies… {proxy_left} left (stops when you're back)")
    elif proxy_missing:
        proxy_lines.append(
            f"{proxy_missing} clips have no proxy — other editors can't see them"
            if proxy_missing != 1 else
            "1 clip has no proxy — other editors can't see it"
        )
    if proxy_braw:
        # Named by format because it is the one gap the editor must act on
        # themselves: no ffmpeg build can decode BRAW, so this machine will
        # never fill it however long it sits idle.
        proxy_lines.append(
            f"{proxy_braw} BRAW clips need the Blackmagic Proxy Generator"
            if proxy_braw != 1 else
            "1 BRAW clip needs the Blackmagic Proxy Generator"
        )
    proxy_items = [pystray.MenuItem(line, None, enabled=False) for line in proxy_lines]
    # The two ACTIONS live under Advanced: "make them now" costs a full tree
    # walk plus hours of encoding, and neither is something to hit by accident
    # on the way to Pause (the same reasoning that moved Consolidate/Scan).
    proxy_actions = []
    if proxy_encoding:
        proxy_actions.append(pystray.MenuItem("Stop making proxies", on_stop_proxies))
    elif proxy_missing and proxy_gap.get("can_generate"):
        proxy_actions.append(pystray.MenuItem(
            "Make the missing proxies now (don't wait until I'm away)", on_make_proxies,
        ))

    # "nothing syncs until you do" is only TRUE when login is required. With
    # require_login=false the lanes are already running under editor_name, and
    # telling the editor otherwise sends them chasing a sign-in they don't
    # need -- the same check compute_overall_color() already makes.
    sign_in_label = (
        "► Sign in… (nothing syncs until you do)"
        if snap.get("require_login", True) else "Sign in…"
    )
    identity_items = [
        pystray.MenuItem(snap["identity_label"], None, enabled=False),
        pystray.MenuItem("Sign out", on_sign_out) if signed_in
        else pystray.MenuItem(sign_in_label, on_sign_in),
    ]

    problem_items = []
    if snap["problems"]:
        problem_items = [pystray.MenuItem(
            "⚠ NOT SET UP: nothing will sync (Copy diagnostics for your admin)",
            None, enabled=False,
        )]

    state_items = [
        pystray.MenuItem(line, None, enabled=False)
        for line in (snap["sequencer_line"], snap["current_project_line"],
                     snap.get("resolve_line"))
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
        *lut_items,
        *proxy_items,
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
            *proxy_actions,
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


def start_tray(
    app: "CompanionApp",
    refresh_interval: float = 2.0,
    pulse_interval: float = PULSE_PERIOD / PULSE_STEPS,
) -> "pystray.Icon":
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
        stable under the cursor.

    Pulse (2026-08-10): a second, faster thread breathes the mark while the
    snapshot says so (syncing, or broken -- see should_pulse). The two loops
    share one tuple and never both own the icon; see _pulse_loop."""

    first = _tray_snapshot(app)
    icon = pystray.Icon(
        "ccsync-companion",
        _icon_image_cached(first["color"]),
        _tooltip_text(first),
        menu=_build_menu(app, first),
    )
    guard = _MenuOpenGuard()
    guard.install()
    _MenuSwapGuard().install()
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
