"""comp-app-core-2 (2026-08-21): the macOS tray backend must not touch AppKit
from tray.py's worker threads.

_refresh_loop assigns icon.title every 2 s and icon.menu on every fingerprint
change; _pulse_loop assigns icon.icon up to 8x every 3 s. Both are plain
daemon threads. NSStatusItem, its button and NSMenu are main-thread only --
pystray's darwin backend marshalled exactly these three through
performSelectorOnMainThread and the rewrite dropped it, so every Mac has been
mutating AppKit off-thread: Main Thread Checker territory, and in practice
intermittent menu-bar corruption or a crash inside AppKit with no traceback.

Runs on any platform: _DarwinIcon imports AppKit lazily, and the hop itself is
a seam this holds. (Nothing here can prove the REAL hop works -- that needs a
Mac -- but it can prove the setters go through it rather than around it.)
"""

from __future__ import annotations

import pytest

from ccsync_companion import tray_native


class _FakeButton:
    def __init__(self):
        self.images = []
        self.tooltips = []

    def setImage_(self, image):
        self.images.append(image)

    def setToolTip_(self, text):
        self.tooltips.append(text)


class _FakeStatusItem:
    def __init__(self):
        self._button = _FakeButton()
        self.menus = []

    def button(self):
        return self._button

    def setMenu_(self, menu):
        self.menus.append(menu)


def _icon():
    """A _DarwinIcon with a live status item and a hop that QUEUES rather than
    runs, so "did this happen on the caller's thread?" is observable."""
    icon = tray_native._DarwinIcon("ccsync", image=None, title="starting")
    icon._status_item = _FakeStatusItem()
    queued = []
    icon._to_main = queued.append
    return icon, queued


def test_the_tooltip_is_set_on_the_main_thread():
    icon, queued = _icon()
    icon.title = "Syncing 4 of 12"
    assert icon._status_item.button().tooltips == [], (
        "setToolTip_ ran on the caller's thread")
    assert len(queued) == 1
    queued[0]()
    assert icon._status_item.button().tooltips == ["Syncing 4 of 12"]


def test_the_icon_image_is_set_on_the_main_thread():
    icon, queued = _icon()
    icon.icon = object()
    assert len(queued) == 1
    assert icon.icon is not None       # the attribute itself is not deferred


def test_rebinding_the_menu_is_marshalled_too():
    """The worst case: the NSMenu the user is tracking replaced under them."""
    icon, queued = _icon()
    icon.menu = object()
    assert len(queued) == 1
    assert icon._status_item.menus == []


def test_the_hop_runs_inline_when_there_is_no_appkit():
    """Never lose a tray update to the marshalling itself: a hop that cannot
    be made falls back to what the code did before this existed."""
    ran = []
    tray_native._darwin_on_main_thread(lambda: ran.append(True))
    assert ran == [True]


def test_the_hop_never_raises():
    tray_native._darwin_on_main_thread(lambda: 1 / 0)


def test_stop_removes_the_status_item_on_the_main_thread():
    """bug-hunt-2026-09-03 comp-ui-5: stop() is reachable from the Quit item
    (main thread) AND from app.shutdown() on a worker (SIGTERM, self-upgrade),
    where removeStatusItem_ inline is the same off-main AppKit touch the three
    setters above were fixed for."""
    icon, queued = _icon()
    item = icon._status_item
    removed = []
    icon._remove_status_item = removed.append

    icon.stop()

    assert removed == [], "removeStatusItem_ ran on the caller's thread"
    assert len(queued) == 1
    queued[0]()
    assert removed == [item]


def test_stop_does_not_wait_for_the_runloop_to_drain():
    """The hop is async, so a shutdown that waited on it would hang whenever
    the main thread is parked (a modal dialog's tkwait, MAC-11)."""
    icon, queued = _icon()
    icon._remove_status_item = lambda item: None

    icon.stop()

    assert icon._stopped.is_set()
    assert icon._status_item is None
    assert len(queued) == 1


def test_stop_with_no_status_item_queues_nothing():
    icon, queued = _icon()
    icon._status_item = None

    icon.stop()

    assert queued == []
    assert icon._stopped.is_set()
