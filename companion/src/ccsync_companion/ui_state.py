"""Cross-thread UI-interaction flag: is the tray menu open right now?

Why this exists (2026-07-26): with the tray menu open, every mouse-move
highlight is delivered as a window message to pystray's Python window
procedure -- a ctypes callback that must acquire the GIL to run. A
fusionscript (Resolve API) call holds the GIL for its FULL native duration,
routinely a second or more on a large project, so each watcher poll froze
the menu highlight for exactly that long. The tray sets `menu_open` around
the native TrackPopupMenuEx call (see tray._MenuOpenGuard); the Resolve
entry points in resolve_bridge defer while it is set.

Deliberately dependency-free (no tkinter, no pystray) so anything may
import it, including headless paths.
"""

from __future__ import annotations

import threading
import time

# Set while the tray's context menu is open. Nobody but the tray writes it.
menu_open = threading.Event()


def wait_while_menu_open(max_wait: float = 8.0, slice_seconds: float = 0.2) -> None:
    """Sleep in small slices while the tray menu is open, at most `max_wait`.

    The cap is a backstop only -- the flag is cleared in a finally around
    the native menu call, but a wedged flag must never be able to stop the
    watcher or media scans outright. Returns immediately when the menu is
    closed (the overwhelmingly common case), so callers can put this in
    front of every Resolve call unconditionally."""
    waited = 0.0
    while menu_open.is_set() and waited < max_wait:
        time.sleep(slice_seconds)
        waited += slice_seconds
