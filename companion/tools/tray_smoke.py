"""Prove the in-house tray backend actually paints an icon and a menu.

The unit tests in companion/tests/test_tray.py are headless by design -- they
must never open a real window, because Windows pytest here happily spawns real
Tk dialogs when a fixture is bypassed. So NOTHING in the suite proves that
Shell_NotifyIconW puts pixels on the taskbar or that TrackPopupMenuEx draws a
menu. This does, by hand, in five seconds.

    companion\\.venv\\Scripts\\python.exe companion\\tools\\tray_smoke.py

It shows a second CCSync-coloured icon beside whatever tray the running
companion already owns, waits ~5 s (right-click it to see the menu; clicking
an item prints to stdout), removes it and exits.

Deliberately inert: it imports ccsync_companion.tray_native ONLY -- not app.py,
not broll_server -- so it opens no sockets (port 8899 stays the running
companion's), touches no config, and reads no state. Running it against a live
companion is safe.

Written 2026-08-17 for docs/COMMERCIAL_READINESS.md item 3.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ccsync_companion import tray_native  # noqa: E402


def _test_image(rgb=(24, 190, 98)):
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 6, 58, 58), fill=rgb + (255,))
    draw.line((20, 32, 30, 42), fill=(255, 255, 255, 255), width=6)
    draw.line((30, 42, 46, 22), fill=(255, 255, 255, 255), width=6)
    return image


def main() -> int:
    clicked: list[str] = []

    def on_click(icon, item):
        clicked.append(item.label())
        print(f"clicked: {item.label()}", flush=True)

    # "Click me" FIRST so the keyboard drive below is one Down + Enter; the
    # disabled label and the separator that would normally lead a CCSync menu
    # follow it, and still exercise MFS_GRAYED / MFT_SEPARATOR.
    menu = tray_native.Menu(
        tray_native.MenuItem("Click me", on_click),
        tray_native.Menu.SEPARATOR,
        tray_native.MenuItem("tray_smoke — this is not the companion", None,
                             enabled=False),
        tray_native.MenuItem("Checked item", on_click, checked=lambda item: True),
        tray_native.MenuItem("Submenu", tray_native.Menu(
            tray_native.MenuItem("Nested", on_click),
        )),
    )

    problems = tray_native._check_struct_sizes()
    for problem in problems:
        print(f"STRUCT PROBLEM: {problem}", flush=True)

    icon = tray_native.Icon("ccsync-tray-smoke", _test_image(), "tray_smoke", menu=menu)
    print(f"backend: {type(icon).__name__}", flush=True)
    icon.run_detached()
    time.sleep(1.0)

    added = getattr(icon, "_added", None)
    hwnd = getattr(icon, "_hwnd", None)
    hicon = icon._icon_handle() if hasattr(icon, "_icon_handle") else None
    print(f"hwnd={hwnd!r} added={added!r} hicon={hicon!r}", flush=True)

    icon.title = "tray_smoke — tooltip updated"
    icon.icon = _test_image((216, 140, 18))
    print("swapped colour + tooltip; right-click the icon now", flush=True)

    menu_items = _inspect_popup(icon, menu)
    _drive_the_menu(icon)

    time.sleep(2.0)
    icon.stop()
    time.sleep(0.5)
    print(f"stopped; clicked={clicked}", flush=True)

    ok = (bool(hwnd) and added is True and bool(hicon) and not problems
          and menu_items and menu_items[0] == "Click me")
    print("RESULT:", "PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


def _inspect_popup(icon, menu) -> list[str]:
    """Build the real HMENU and read it back out of USER32.

    GetMenuItemCount/GetMenuStringW answer from the shell's own copy of the
    menu, so a label that comes back is a label InsertMenuItemW really stored
    -- which is the half of "does the menu work" that does not need a human
    with a mouse.
    """
    import ctypes
    from ctypes import wintypes

    if not hasattr(icon, "_build_popup"):
        return []
    user32 = ctypes.windll.user32
    user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
    user32.GetMenuItemCount.restype = ctypes.c_int
    user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT,
                                      wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
    user32.GetMenuStringW.restype = ctypes.c_int
    user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
    user32.GetSubMenu.restype = wintypes.HMENU

    callbacks: dict = {}
    handle = icon._build_popup(menu, callbacks)
    if not handle:
        print("popup: CreatePopupMenu FAILED", flush=True)
        return []
    count = user32.GetMenuItemCount(handle)
    labels = []
    for index in range(count):
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(handle, index, buffer, 256, 0x0400)  # MF_BYPOSITION
        labels.append(buffer.value)
    submenu = user32.GetSubMenu(handle, count - 1)
    print(f"popup: {count} items {labels!r}; last has submenu={bool(submenu)}",
          flush=True)
    ctypes.windll.user32.DestroyMenu(handle)
    return labels


def _drive_the_menu(icon) -> None:
    """Open the real popup by posting the tray's own click message, then pick
    the first item from the keyboard.

    If the callback fires, TrackPopupMenuEx entered its modal loop with a
    populated menu -- i.e. it painted. Best-effort: SetForegroundWindow can be
    refused when another process owns the foreground, in which case the keys
    go nowhere and this proves nothing either way, so the printout says which
    happened rather than asserting.
    """
    import ctypes

    if not hasattr(icon, "_hwnd") or not icon._hwnd:
        return
    user32 = ctypes.windll.user32
    WM_RBUTTONUP = 0x0205
    VK_DOWN, VK_RETURN, VK_ESCAPE = 0x28, 0x0D, 0x1B
    KEYEVENTF_KEYUP = 0x0002

    user32.PostMessageW(icon._hwnd, tray_native._CCSYNC_WM_TRAY, 0, WM_RBUTTONUP)
    time.sleep(1.0)
    print(f"menu_open flag while displayed: {icon._menu_open.is_set()}", flush=True)
    # Two routes, because which one lands depends on whether Windows let us
    # take the foreground. keybd_event goes through the real input queue (and
    # needs the foreground); posting WM_KEYDOWN to our own window puts the key
    # in the pump thread's queue, which is exactly where TrackPopupMenuEx's
    # modal loop is reading from.
    WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
    for key in (VK_DOWN, VK_RETURN):
        user32.keybd_event(key, 0, 0, 0)
        user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.15)
    if icon._menu_open.is_set():
        for key in (VK_DOWN, VK_RETURN):
            user32.PostMessageW(icon._hwnd, WM_KEYDOWN, key, 0)
            user32.PostMessageW(icon._hwnd, WM_KEYUP, key, 0)
            time.sleep(0.15)
    time.sleep(0.5)
    if icon._menu_open.is_set():
        # Still up: the keystrokes went somewhere else. Escape it rather than
        # leaving a modal menu on a machine nobody is sitting at.
        user32.keybd_event(VK_ESCAPE, 0, 0, 0)
        user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
        user32.PostMessageW(icon._hwnd, 0x001F, 0, 0)  # WM_CANCELMODE


if __name__ == "__main__":
    raise SystemExit(main())
