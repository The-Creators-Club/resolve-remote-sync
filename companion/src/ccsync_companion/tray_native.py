"""The companion's own system-tray backend — no pystray.

ORIGINAL IMPLEMENTATION. Written 2026-08-17 for docs/COMMERCIAL_READINESS.md
item 3 straight from the Win32 (Shell_NotifyIconW / TrackPopupMenuEx /
CreateIconIndirect) and AppKit (NSStatusBar / NSMenu) API documentation. It is
NOT derived from, translated from, or copied out of pystray or any other
LGPL/GPL project: pystray is LGPLv3, this binary is frozen single-file by
PyInstaller, and a single-file freeze of an LGPL library is conveying it
without the relinking freedom §4 requires. The old tray.py additionally
monkeypatched pystray's win32 internals (its TrackPopupMenuEx wrapper and a
replacement Icon._update_menu), which made the derivative-work reading
stronger still. Both are gone; what is left below is written against the
public OS APIs, which are facts about Windows and macOS, not anyone's code.

What it deliberately is NOT: a general-purpose tray library. It implements
exactly the surface tray.py uses --

    Icon(name, image, title, menu=..., menu_open_flag=...)
        .icon      = <PIL image>      (settable from any thread)
        .title     = <str>            (settable from any thread)
        .menu      = <Menu>           (settable from any thread)
        .notify(message, title=None)
        .run() / .run_detached() / .stop()
    Menu(*items) with Menu.SEPARATOR, .items
    MenuItem(text, action, enabled=True, checked=None, default=False,
             visible=True) with .text/.submenu/.enabled/.checked/.action

-- and nothing else. Adding to it is cheaper than depending on a library
whose licence we cannot satisfy.

Two design changes from what pystray did, both of which delete a class of bug
this repo has already paid for:

1. THE POPUP MENU IS BUILT AT RIGHT-CLICK TIME AND DESTROYED WHEN IT CLOSES.
   pystray kept a live HMENU and rebuilt it on every `icon.menu = ...`,
   DestroyMenu()ing the handle FIRST -- from two threads that knew nothing of
   each other -- so a right-click landing mid-rebuild got a destroyed handle,
   TrackPopupMenuEx returned 0, and nothing appeared (2026-07-26 freezes, and
   the USER-object leak behind them). Here `icon.menu` is a plain attribute:
   assigning it costs nothing, cannot race, and the HMENU exists only for the
   fraction of a second the menu is on screen, on the thread that shows it.
2. THE MENU-OPEN FLAG IS SET BY THE BACKEND ITSELF. tray.py's refresh and
   pulse loops must not touch the icon while the menu is up (a NIM_MODIFY
   under an open menu forces a repaint beneath the cursor -- the 2026-07-26
   hover hangs), and resolve_bridge defers its GIL-holding fusionscript calls
   for the same reason. That signal used to come from monkeypatching pystray;
   now the Icon sets the caller-supplied Event around the popup itself, and
   the macOS side sets it from NSMenu's delegate, which pystray gave us no way
   to do at all.
"""

from __future__ import annotations

import logging
import struct
import sys
import threading
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.tray.native")


# -- the platform-independent menu model ------------------------------------


class MenuItem:
    """One row of the tray menu.

    `action` is either a callable invoked as action(icon, item) -- the shape
    tray.py's handlers already have -- or a Menu, which makes this a submenu.
    `checked` may be a bool or a callable(item) -> bool; a non-None value is
    what makes the row a checkbox at all (an unchecked checkbox and a plain
    row are different things on both platforms).
    """

    __slots__ = ("text", "action", "submenu", "enabled", "checked",
                 "default", "visible", "is_separator")

    def __init__(self, text, action=None, enabled: bool = True,
                 checked=None, default: bool = False, visible: bool = True,
                 _separator: bool = False) -> None:
        self.text = text
        if isinstance(action, Menu):
            self.submenu: Optional[Menu] = action
            self.action = None
        else:
            self.submenu = None
            self.action = action
        self.enabled = enabled
        self.checked = checked
        self.default = default
        self.visible = visible
        self.is_separator = _separator

    def label(self) -> str:
        text = self.text() if callable(self.text) else self.text
        return "" if text is None else str(text)

    def is_checked(self) -> Optional[bool]:
        if self.checked is None:
            return None
        try:
            return bool(self.checked(self) if callable(self.checked) else self.checked)
        except Exception:
            log.debug("menu item %r: checked() raised", self.label(), exc_info=True)
            return False

    def is_enabled(self) -> bool:
        try:
            return bool(self.enabled(self) if callable(self.enabled) else self.enabled)
        except Exception:
            return True

    def is_visible(self) -> bool:
        try:
            return bool(self.visible(self) if callable(self.visible) else self.visible)
        except Exception:
            return True

    def __call__(self, icon=None):
        """Invoke the action, the way pystray's MenuItem did.

        Kept because _build_menu's handlers are (icon, item) callables and the
        tray tests reach them by calling the item; nothing in the backends
        goes through here.
        """
        if self.action is None:
            return None
        return self.action(icon, self)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<MenuItem {self.label()!r}>"


class Menu:
    """An ordered list of MenuItems. `items` is public because the tests and
    _menu_fingerprint read it."""

    #: Filled in below the class body -- a MenuItem cannot exist before
    #: MenuItem does, and Menu must exist before MenuItem can hold one.
    SEPARATOR: "MenuItem"

    __slots__ = ("items",)

    def __init__(self, *items) -> None:
        self.items = tuple(i for i in items if i is not None)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def rendered(self) -> list[MenuItem]:
        """The items actually worth drawing: invisible ones dropped, and
        leading/trailing/doubled separators collapsed.

        The collapse is not cosmetic. Half of tray.py's sections are
        conditional (`*upgrade_items`, `*lut_items`, `*proxy_items`...) and
        carry their own trailing separator, so on a quiet machine the raw
        list contains runs of them; a menu that opens with a horizontal rule
        looks broken.
        """
        out: list[MenuItem] = []
        for item in self.items:
            if not item.is_visible():
                continue
            if item.is_separator:
                if not out or out[-1].is_separator:
                    continue
            out.append(item)
        while out and out[-1].is_separator:
            out.pop()
        return out


# pystray spelled its separator '- - - -' and the companion's tests read
# `str(item.text)`; keeping the same text keeps them honest about what a
# separator row is without giving them a reason to care.
Menu.SEPARATOR = MenuItem("- - - -", None, enabled=False, _separator=True)


# -- Windows ----------------------------------------------------------------
#
# Everything below is Shell_NotifyIconW and friends, per MSDN. The notable
# constraints, none of them obvious:
#
#  * The notification icon needs an ordinary (never-shown) window, NOT a
#    message-only one: HWND_MESSAGE windows do not receive broadcasts, and the
#    "TaskbarCreated" broadcast is the only way to learn that Explorer
#    restarted and dropped every tray icon in the session. Without it the
#    companion silently vanishes from the tray until it is restarted.
#  * The window procedure runs on whichever thread pumps messages, so
#    everything menu-related happens there and nowhere else.
#  * NOTIFYICONDATAW's cbSize is validated against a small set of known
#    sizes; ctypes' natural alignment reproduces the MSVC layout (976 bytes on
#    x64), and _check_struct_sizes below says so out loud if a future Python
#    ever disagrees.

_WM_APP = 0x8000
_CCSYNC_WM_TRAY = _WM_APP + 1     # our NOTIFYICONDATA uCallbackMessage
_CCSYNC_WM_QUIT_TRAY = _WM_APP + 2  # stop() -> the pump thread

_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_NULL = 0x0000
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONUP = 0x0205
_WM_LBUTTONDBLCLK = 0x0203

_NIM_ADD = 0x00000000
_NIM_MODIFY = 0x00000001
_NIM_DELETE = 0x00000002

_NIF_MESSAGE = 0x00000001
_NIF_ICON = 0x00000002
_NIF_TIP = 0x00000004
_NIF_INFO = 0x00000010

_NIIF_NONE = 0x00000000

_TPM_LEFTALIGN = 0x0000
_TPM_CENTERALIGN = 0x0004
_TPM_RIGHTALIGN = 0x0008
_TPM_TOPALIGN = 0x0000
_TPM_VCENTERALIGN = 0x0010
_TPM_BOTTOMALIGN = 0x0020
_TPM_RETURNCMD = 0x0100
_TPM_RIGHTBUTTON = 0x0002
# LEFT/TOP are zero, so an alignment is SET by clearing the other bits on its
# axis -- an OR alone cannot express them, and cannot undo a RIGHT|BOTTOM
# either (which is exactly wrong for a top or left taskbar).
_TPM_HALIGN_MASK = _TPM_CENTERALIGN | _TPM_RIGHTALIGN
_TPM_VALIGN_MASK = _TPM_VCENTERALIGN | _TPM_BOTTOMALIGN

_ABM_GETTASKBARPOS = 0x00000005
_ABE_LEFT = 0
_ABE_TOP = 1
_ABE_RIGHT = 2
_ABE_BOTTOM = 3

_MIIM_STATE = 0x00000001
_MIIM_ID = 0x00000002
_MIIM_SUBMENU = 0x00000004
_MIIM_STRING = 0x00000040
_MIIM_FTYPE = 0x00000100

_MFT_STRING = 0x00000000
_MFT_SEPARATOR = 0x00000800

_MFS_ENABLED = 0x00000000
_MFS_GRAYED = 0x00000003
_MFS_CHECKED = 0x00000008
_MFS_DEFAULT = 0x00001000

_CS_HREDRAW = 0x0002
_CS_VREDRAW = 0x0001
_BI_RGB = 0
_DIB_RGB_COLORS = 0
_SM_CXSMICON = 49
_SM_CYSMICON = 50

_ERROR_CLASS_ALREADY_EXISTS = 1410

# Shell_NotifyIcon fails transiently while Explorer is starting or busy; MSDN
# recommends retrying NIM_ADD rather than treating the first failure as final.
_NIM_ADD_RETRIES = 6
_NIM_ADD_RETRY_DELAY = 0.5


def _clamp_menu_anchor(x: int, y: int, flags: int, taskbar_rect, taskbar_edge: int):
    """(x, y, flags) moved out of `taskbar_rect`, or unchanged.

    Item 21 (v0.5.0, Windows 11, taskbar set to auto-hide): the menu's bottom
    edge -- the Quit item -- sat UNDER the taskbar. The anchor is the cursor
    position, which for a tray right-click is inside the taskbar band, and the
    alignment says "put the menu's bottom-right corner exactly here". Windows
    normally rescues that by keeping the menu inside the monitor WORK AREA,
    but an auto-hide bar is excluded from the work area (it reserves one
    pixel, not its height), so nothing is violated and the raised, topmost bar
    draws over the last item or two.

    `taskbar_rect` is (left, top, right, bottom) in screen pixels and
    `taskbar_edge` one of the ABE_* constants. An anchor OUTSIDE the rect is
    returned untouched: it is only the click that lands on the bar itself
    that needs help, and a second monitor's cursor position must not be
    dragged to the primary taskbar's edge.

    The alignment flag is rewritten, not or-ed on: RIGHT|BOTTOM is right for a
    bottom or right taskbar and precisely backwards for a top or left one --
    there the menu would grow back into the bar it was just moved out of.

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
    failure -- no geometry, or a shell that will not answer. The menu then
    opens where it opened before, which is the version of this bug we can
    live with: a positioning nicety must never be the reason a menu fails to
    open at all."""
    try:
        geometry = _taskbar_geometry()
        if geometry is None:
            return x, y, flags
        rect, edge = geometry
        return _clamp_menu_anchor(x, y, flags, rect, edge)
    except Exception:
        log.debug("taskbar anchor adjustment skipped", exc_info=True)
        return x, y, flags


def _escape_menu_label(text: str) -> str:
    """Windows menu strings are not literals: '&' introduces a mnemonic (and
    swallows itself), and a tab starts the right-hand accelerator column. Both
    appear in editor-facing strings by accident, never on purpose."""
    return text.replace("&", "&&").replace("\t", " ")


class _Win32:
    """The ctypes bindings, built once and lazily.

    argtypes/restypes are declared for every call: on 64-bit Windows a handle
    left as the default c_int is truncated, which is the classic
    silently-does-nothing ctypes bug.
    """

    _instance: Optional["_Win32"] = None

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        LRESULT = ctypes.c_ssize_t
        self.LRESULT = LRESULT
        self.WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("style", wintypes.UINT),
                ("lpfnWndProc", self.WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        class MENUITEMINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("fMask", wintypes.UINT),
                ("fType", wintypes.UINT),
                ("fState", wintypes.UINT),
                ("wID", wintypes.UINT),
                ("hSubMenu", wintypes.HMENU),
                ("hbmpChecked", wintypes.HBITMAP),
                ("hbmpUnchecked", wintypes.HBITMAP),
                ("dwItemData", ctypes.c_void_p),
                ("dwTypeData", wintypes.LPWSTR),
                ("cch", wintypes.UINT),
                ("hbmpItem", wintypes.HBITMAP),
            ]

        class ICONINFO(ctypes.Structure):
            _fields_ = [
                ("fIcon", wintypes.BOOL),
                ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP),
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        self.WNDCLASSEX = WNDCLASSEX
        self.NOTIFYICONDATAW = NOTIFYICONDATAW
        self.MENUITEMINFOW = MENUITEMINFOW
        self.ICONINFO = ICONINFO
        self.BITMAPINFOHEADER = BITMAPINFOHEADER

        u, g, s, k = self.user32, self.gdi32, self.shell32, self.kernel32
        u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEX)]
        u.RegisterClassExW.restype = wintypes.ATOM
        u.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.CreateWindowExW.restype = wintypes.HWND
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.DestroyWindow.restype = wintypes.BOOL
        # GetMessageW/TranslateMessage/DispatchMessageW take a pointer to an
        # MSG that is declared inside the pump (it is needed nowhere else), so
        # their argtypes are deliberately left undeclared and byref() is
        # passed straight through -- ctypes only type-checks what you tell it
        # to. GetMessageW's restype is NOT BOOL: it returns -1 on failure, and
        # that is the value the pump must not mistake for a message.
        u.GetMessageW.restype = ctypes.c_int
        u.DispatchMessageW.restype = LRESULT
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
        u.PostMessageW.restype = wintypes.BOOL
        u.PostQuitMessage.argtypes = [ctypes.c_int]
        u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        u.RegisterWindowMessageW.restype = wintypes.UINT
        u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        u.GetCursorPos.restype = wintypes.BOOL
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SetForegroundWindow.restype = wintypes.BOOL
        u.CreatePopupMenu.argtypes = []
        u.CreatePopupMenu.restype = wintypes.HMENU
        u.DestroyMenu.argtypes = [wintypes.HMENU]
        u.DestroyMenu.restype = wintypes.BOOL
        u.InsertMenuItemW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.BOOL,
                                      ctypes.POINTER(MENUITEMINFOW)]
        u.InsertMenuItemW.restype = wintypes.BOOL
        u.TrackPopupMenuEx.argtypes = [wintypes.HMENU, wintypes.UINT,
                                       ctypes.c_int, ctypes.c_int,
                                       wintypes.HWND, ctypes.c_void_p]
        u.TrackPopupMenuEx.restype = ctypes.c_int
        u.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
        u.CreateIconIndirect.restype = wintypes.HICON
        u.DestroyIcon.argtypes = [wintypes.HICON]
        u.DestroyIcon.restype = wintypes.BOOL
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.GetSystemMetrics.restype = ctypes.c_int

        g.CreateDIBSection.argtypes = [wintypes.HDC,
                                       ctypes.POINTER(BITMAPINFOHEADER),
                                       wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT,
                                   wintypes.UINT, ctypes.c_void_p]
        g.CreateBitmap.restype = wintypes.HBITMAP
        g.DeleteObject.argtypes = [wintypes.HANDLE]
        g.DeleteObject.restype = wintypes.BOOL

        s.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                        ctypes.POINTER(NOTIFYICONDATAW)]
        s.Shell_NotifyIconW.restype = wintypes.BOOL

        k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k.GetModuleHandleW.restype = wintypes.HMODULE

    @classmethod
    def get(cls) -> "_Win32":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def _check_struct_sizes() -> list[str]:
    """Complaints about any struct whose ctypes layout does not match the size
    the OS validates against, or [] when all is well.

    Shell_NotifyIcon rejects a NOTIFYICONDATAW whose cbSize is not one of the
    handful of sizes Windows knows, and the failure mode is a tray icon that
    simply never appears with no other symptom -- so the mismatch is worth a
    named check rather than an afternoon.
    """
    if sys.platform != "win32":
        return []
    problems = []
    try:
        import ctypes

        api = _Win32.get()
        pointer_size = struct.calcsize("P")
        expected_nid = 976 if pointer_size == 8 else 956
        expected_mii = 80 if pointer_size == 8 else 48
        actual_nid = ctypes.sizeof(api.NOTIFYICONDATAW)
        actual_mii = ctypes.sizeof(api.MENUITEMINFOW)
        if actual_nid != expected_nid:
            problems.append(
                f"NOTIFYICONDATAW is {actual_nid} bytes, expected {expected_nid}")
        if actual_mii != expected_mii:
            problems.append(
                f"MENUITEMINFOW is {actual_mii} bytes, expected {expected_mii}")
    except Exception as exc:  # pragma: no cover - only on a broken ctypes
        problems.append(f"could not measure the tray structs: {exc}")
    return problems


def _hicon_from_image(image, size: Optional[tuple[int, int]] = None):
    """An HICON for a PIL image, via CreateIconIndirect.

    A 32-bpp top-down DIB section carries the alpha channel straight through,
    which is what the borderless mark needs on a light taskbar; the 1-bpp mask
    bitmap is required by ICONINFO even though a 32-bpp colour bitmap makes
    Windows ignore it, and it is zero-filled EXPLICITLY -- CreateBitmap(NULL)
    leaves the bits undefined, and on the paths where the mask is honoured
    that is a randomly-shredded icon.

    Returns None on any failure; the caller keeps whatever icon it had.
    """
    try:
        import ctypes

        api = _Win32.get()
        if size is None:
            width = api.user32.GetSystemMetrics(_SM_CXSMICON) or 16
            height = api.user32.GetSystemMetrics(_SM_CYSMICON) or 16
        else:
            width, height = size
        rgba = image.convert("RGBA")
        if rgba.size != (width, height):
            from PIL import Image as _Image

            rgba = rgba.resize((width, height), _Image.LANCZOS)
        bgra = rgba.tobytes("raw", "BGRA")

        header = api.BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(api.BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height          # negative => top-down, like PIL's rows
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = _BI_RGB

        bits = ctypes.c_void_p()
        hbm_color = api.gdi32.CreateDIBSection(
            None, ctypes.byref(header), _DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not hbm_color or not bits:
            log.debug("CreateDIBSection failed for the tray icon")
            return None
        ctypes.memmove(bits, bgra, len(bgra))

        mask_stride = ((width + 31) // 32) * 4
        zeros = (ctypes.c_byte * (mask_stride * height))()
        hbm_mask = api.gdi32.CreateBitmap(
            width, height, 1, 1, ctypes.cast(zeros, ctypes.c_void_p))

        info = api.ICONINFO()
        info.fIcon = True
        info.xHotspot = 0
        info.yHotspot = 0
        info.hbmMask = hbm_mask
        info.hbmColor = hbm_color
        hicon = api.user32.CreateIconIndirect(ctypes.byref(info))

        # CreateIconIndirect copies both bitmaps; ours are ours to free, and
        # not freeing them is a GDI leak once per pulse frame forever.
        api.gdi32.DeleteObject(hbm_color)
        api.gdi32.DeleteObject(hbm_mask)
        return hicon or None
    except Exception:
        log.debug("could not build a tray HICON", exc_info=True)
        return None


class _WindowsIcon:
    """The tray icon on Windows.

    Threading: run() owns the window and the message pump. `icon`, `title` and
    `menu` are assigned from tray.py's refresh/pulse threads; the first two
    reach the shell through Shell_NotifyIcon(NIM_MODIFY), which is a
    cross-process call that does not care which of OUR threads makes it, and
    the third is a plain attribute rebind read later by the pump thread. The
    menu itself is built and torn down entirely inside the pump thread.
    """

    def __init__(self, name: str, image=None, title: str = "", menu=None,
                 menu_open_flag: Optional[threading.Event] = None) -> None:
        self.name = name
        self._image = image
        self._title = title or ""
        self.menu = menu
        self._menu_open = menu_open_flag or threading.Event()
        self._hwnd = None
        self._hicon = None
        self._hicon_cache: dict[int, tuple[Any, Any]] = {}
        self._added = False
        self._running = threading.Event()
        self._stopped = threading.Event()
        self._wndproc_ref = None
        self._uid = 1
        self._taskbar_created_msg = 0
        self._detached_thread: Optional[threading.Thread] = None
        self._pump_thread_id: Optional[int] = None

    # -- the properties tray.py assigns ------------------------------------

    @property
    def icon(self):
        return self._image

    @icon.setter
    def icon(self, image) -> None:
        self._image = image
        if self._added:
            self._modify(icon=True)

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value or ""
        if self._added:
            self._modify(tip=True)

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        problems = _check_struct_sizes()
        for problem in problems:
            log.error("tray backend: %s -- the icon will probably not appear", problem)
        self._pump_thread_id = threading.get_ident()
        try:
            self._create_window()
            self._add_icon()
        except Exception:
            log.exception("the tray icon could not be created")
            self._stopped.set()
            return
        self._running.set()
        try:
            self._pump()
        finally:
            self._teardown()
            self._stopped.set()

    def run_detached(self) -> None:
        """Start the pump on a thread of its own and return.

        tray.py only takes this path on macOS, where the status item must live
        on the main thread; on Windows it exists so the two backends answer
        the same questions.
        """
        thread = threading.Thread(target=self.run, name="ccsync-tray", daemon=True)
        self._detached_thread = thread
        thread.start()
        self._running.wait(timeout=5.0)

    def stop(self) -> None:
        api = _Win32.get()
        hwnd = self._hwnd
        if not hwnd:
            self._stopped.set()
            return
        api.user32.PostMessageW(hwnd, _CCSYNC_WM_QUIT_TRAY, 0, 0)
        # Quit is a MENU item, so the usual caller of this is the pump thread
        # itself, from inside TrackPopupMenuEx's action callback. Waiting there
        # would block the very loop that has to process the message we just
        # posted -- five seconds of frozen tray on every Quit.
        if threading.get_ident() != self._pump_thread_id:
            self._stopped.wait(timeout=5.0)

    def notify(self, message: str, title: Optional[str] = None) -> None:
        """A balloon/toast from the tray icon.

        szInfo is 256 WCHARs INCLUDING the terminator and szInfoTitle 64;
        overlong text does not truncate, it makes the whole call fail, so it
        is cut here.
        """
        if not self._added:
            return
        self._modify(info=(str(message)[:250], str(title or self.name)[:60]))

    # -- window + icon -----------------------------------------------------

    def _create_window(self) -> None:
        import ctypes

        api = _Win32.get()
        hinstance = api.kernel32.GetModuleHandleW(None)
        # One class name per Icon instance: a second companion process (or a
        # tray restarted in-process by a test) must not collide with a class
        # this process already registered, and RegisterClassExW gives no way
        # to ask "is this the same class?".
        class_name = f"CCSyncTray_{id(self):x}"

        def wndproc(hwnd, msg, wparam, lparam):
            try:
                return self._on_message(hwnd, msg, wparam, lparam)
            except Exception:
                log.exception("tray window procedure failed")
                return api.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        # The WNDPROC must be kept alive for as long as the window: ctypes
        # callbacks are garbage-collected like anything else, and a collected
        # one is a crash inside USER32 with no Python traceback at all.
        self._wndproc_ref = api.WNDPROC(wndproc)

        cls = api.WNDCLASSEX()
        cls.cbSize = ctypes.sizeof(api.WNDCLASSEX)
        cls.style = _CS_HREDRAW | _CS_VREDRAW
        cls.lpfnWndProc = self._wndproc_ref
        cls.cbClsExtra = 0
        cls.cbWndExtra = 0
        cls.hInstance = hinstance
        cls.hIcon = None
        cls.hCursor = None   # the window is never shown; there is nothing to hover
        cls.hbrBackground = None
        cls.lpszMenuName = None
        cls.lpszClassName = class_name
        cls.hIconSm = None
        if not api.user32.RegisterClassExW(ctypes.byref(cls)):
            err = ctypes.get_last_error()
            if err != _ERROR_CLASS_ALREADY_EXISTS:
                raise OSError(f"RegisterClassExW failed (GetLastError={err})")

        # An ordinary, never-shown window rather than HWND_MESSAGE: a
        # message-only window receives no broadcasts, and "TaskbarCreated" --
        # the notice that Explorer restarted and dropped every tray icon -- is
        # a broadcast. Without it the companion disappears from the tray for
        # the rest of the session on any Explorer crash.
        self._hwnd = api.user32.CreateWindowExW(
            0, class_name, "CCSync", 0, 0, 0, 0, 0, None, None, hinstance, None)
        if not self._hwnd:
            raise OSError(f"CreateWindowExW failed (GetLastError={ctypes.get_last_error()})")
        self._taskbar_created_msg = api.user32.RegisterWindowMessageW("TaskbarCreated")

    def _nid(self):
        import ctypes

        api = _Win32.get()
        data = api.NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(api.NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = self._uid
        return data

    def _icon_handle(self):
        """The HICON for the current image, cached.

        Keyed on id() while HOLDING a reference to the image, so an id can
        never be recycled under the cache. tray.py hands out a small fixed set
        of pre-rendered images (one per colour and pulse level), so this
        settles at a couple of dozen handles and then stops allocating -- the
        pulse would otherwise build and leak an HICON eight times every three
        seconds forever.
        """
        image = self._image
        if image is None:
            return None
        cached = self._hicon_cache.get(id(image))
        if cached is not None:
            return cached[1]
        hicon = _hicon_from_image(image)
        if hicon:
            self._hicon_cache[id(image)] = (image, hicon)
        return hicon

    def _add_icon(self) -> None:
        import time

        import ctypes

        api = _Win32.get()
        data = self._nid()
        data.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        data.uCallbackMessage = _CCSYNC_WM_TRAY
        data.hIcon = self._icon_handle()
        data.szTip = self._title[:127]
        for attempt in range(_NIM_ADD_RETRIES):
            if api.shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data)):
                self._added = True
                return
            time.sleep(_NIM_ADD_RETRY_DELAY)
        raise OSError(
            "Shell_NotifyIcon(NIM_ADD) failed after "
            f"{_NIM_ADD_RETRIES} attempts (GetLastError={ctypes.get_last_error()})")

    def _modify(self, icon: bool = False, tip: bool = False, info=None) -> None:
        import ctypes

        api = _Win32.get()
        data = self._nid()
        flags = 0
        if icon:
            flags |= _NIF_ICON
            data.hIcon = self._icon_handle()
        if tip:
            flags |= _NIF_TIP
            data.szTip = self._title[:127]
        if info is not None:
            flags |= _NIF_INFO
            data.szInfo, data.szInfoTitle = info
            data.dwInfoFlags = _NIIF_NONE
        data.uFlags = flags
        if not api.shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(data)):
            # Explorer restarting is the ordinary cause and repairs itself on
            # the TaskbarCreated broadcast, so this is not a warning.
            log.debug("Shell_NotifyIcon(NIM_MODIFY) failed (flags=%#x)", flags)

    def _remove_icon(self) -> None:
        import ctypes

        api = _Win32.get()
        if not self._added:
            return
        data = self._nid()
        api.shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(data))
        self._added = False

    # -- messages ----------------------------------------------------------

    def _pump(self) -> None:
        import ctypes
        from ctypes import wintypes

        api = _Win32.get()

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
            ]

        msg = MSG()
        while True:
            got = api.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got == 0:      # WM_QUIT
                return
            if got == -1:     # the pump itself failed; nothing to recover to
                log.error("tray message pump failed (GetLastError=%d)",
                          ctypes.get_last_error())
                return
            api.user32.TranslateMessage(ctypes.byref(msg))
            api.user32.DispatchMessageW(ctypes.byref(msg))

    def _on_message(self, hwnd, msg, wparam, lparam):
        api = _Win32.get()
        if msg == _CCSYNC_WM_TRAY:
            # Classic (pre-version-4) callback shape, which is what we get by
            # never calling NIM_SETVERSION: wParam is the icon id and lParam
            # the mouse message. The coordinates come from GetCursorPos, not
            # from lParam, exactly as the documentation for this shape says.
            mouse = lparam & 0xFFFF
            if mouse in (_WM_RBUTTONUP, _WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                self._show_menu()
            return 0
        if msg == _CCSYNC_WM_QUIT_TRAY:
            self._remove_icon()
            api.user32.DestroyWindow(hwnd)
            return 0
        if msg == _WM_DESTROY:
            api.user32.PostQuitMessage(0)
            return 0
        if msg == _WM_CLOSE:
            api.user32.DestroyWindow(hwnd)
            return 0
        if self._taskbar_created_msg and msg == self._taskbar_created_msg:
            # Explorer restarted; every tray icon in the session is gone.
            log.info("Explorer restarted -- re-adding the CCSync tray icon")
            self._added = False
            try:
                self._add_icon()
            except Exception:
                log.warning("could not re-add the tray icon after an Explorer restart",
                            exc_info=True)
            return 0
        return api.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- the popup menu ----------------------------------------------------

    def _build_popup(self, menu: Menu, callbacks: dict):
        """An HMENU for `menu`; callbacks[id] = the MenuItem to invoke.

        Recursive for submenus. Returns None if CreatePopupMenu fails, which
        in practice means the process has hit the 10 000-object USER quota.
        """
        import ctypes

        api = _Win32.get()
        handle = api.user32.CreatePopupMenu()
        if not handle:
            return None
        for position, item in enumerate(menu.rendered()):
            info = api.MENUITEMINFOW()
            info.cbSize = ctypes.sizeof(api.MENUITEMINFOW)
            if item.is_separator:
                info.fMask = _MIIM_FTYPE
                info.fType = _MFT_SEPARATOR
            else:
                info.fMask = _MIIM_FTYPE | _MIIM_STATE | _MIIM_STRING
                info.fType = _MFT_STRING
                label = _escape_menu_label(item.label())
                buffer = ctypes.create_unicode_buffer(label)
                info.dwTypeData = ctypes.cast(buffer, api.wintypes.LPWSTR)
                info.cch = len(label)
                # The buffer must outlive InsertMenuItemW, which copies it;
                # holding it in the callbacks dict is the cheapest way to say
                # "not yet" to the garbage collector.
                callbacks[("buffer", position, id(handle))] = buffer
                state = _MFS_ENABLED
                if not item.is_enabled():
                    state |= _MFS_GRAYED
                if item.is_checked():
                    state |= _MFS_CHECKED
                if item.default:
                    state |= _MFS_DEFAULT
                info.fState = state
                if item.submenu is not None:
                    sub = self._build_popup(item.submenu, callbacks)
                    if sub:
                        info.fMask |= _MIIM_SUBMENU
                        info.hSubMenu = sub
                elif item.action is not None:
                    ident = len(callbacks) + 1000
                    while ident in callbacks:
                        ident += 1
                    callbacks[ident] = item
                    info.fMask |= _MIIM_ID
                    info.wID = ident
            if not api.user32.InsertMenuItemW(handle, position, True, ctypes.byref(info)):
                log.debug("InsertMenuItemW failed for %r", item)
        return handle

    def _menu_anchor(self):
        """(x, y, flags) for TrackPopupMenuEx, cursor position clamped clear
        of the taskbar."""
        import ctypes
        from ctypes import wintypes

        api = _Win32.get()
        point = wintypes.POINT()
        api.user32.GetCursorPos(ctypes.byref(point))
        flags = _TPM_RIGHTALIGN | _TPM_BOTTOMALIGN | _TPM_RIGHTBUTTON | _TPM_RETURNCMD
        return _anchor_clear_of_taskbar(int(point.x), int(point.y), flags)

    def _show_menu(self) -> None:
        import ctypes

        api = _Win32.get()
        menu = self.menu
        if not menu:
            return
        callbacks: dict = {}
        handle = self._build_popup(menu, callbacks)
        if not handle:
            log.warning("tray menu could not be created (GetLastError=%d) -- "
                        "the process may be out of USER objects",
                        ctypes.get_last_error())
            return
        x, y, flags = self._menu_anchor()
        # MSDN's TrackPopupMenu notes, both of them, both load-bearing: the
        # owner window must be foreground or the menu never dismisses on the
        # click that follows, and a WM_NULL has to be posted afterwards for
        # the same reason.
        api.user32.SetForegroundWindow(self._hwnd)
        self._menu_open.set()
        try:
            ctypes.set_last_error(0)
            chosen = api.user32.TrackPopupMenuEx(handle, flags, x, y, self._hwnd, None)
            error = ctypes.get_last_error()
        finally:
            self._menu_open.clear()
            api.user32.DestroyMenu(handle)
            api.user32.PostMessageW(self._hwnd, _WM_NULL, 0, 0)
        if not chosen:
            # With TPM_RETURNCMD a zero return is "cancelled" OR "failed", and
            # the two are only distinguishable by GetLastError. A right-click
            # that does nothing is the single most-reported tray symptom, so
            # the failing case is loud; a dismissal is not.
            if error:
                log.warning("tray menu failed to open (TrackPopupMenuEx=0, "
                            "GetLastError=%d)", error)
            else:
                log.debug("tray menu dismissed without a selection")
            return
        item = callbacks.get(chosen)
        if item is None or item.action is None:
            return
        try:
            item.action(self, item)
        except Exception:
            log.exception("tray menu action %r failed", item.label())

    def _teardown(self) -> None:
        api = _Win32.get()
        try:
            self._remove_icon()
        except Exception:
            log.debug("removing the tray icon failed", exc_info=True)
        for _image, hicon in self._hicon_cache.values():
            try:
                api.user32.DestroyIcon(hicon)
            except Exception:
                pass
        self._hicon_cache.clear()
        self._hwnd = None


# -- macOS ------------------------------------------------------------------


_DARWIN_HELPERS: Optional[tuple] = None


def _darwin_helper_classes():
    """(_Target, _MenuWatcher), the two ObjC classes the menu needs, defined
    exactly ONCE per process.

    Not inline in _build_nsmenu, which is where they naturally belong: the
    Objective-C runtime has one flat class namespace, and declaring a class
    whose name is already registered raises. The menu is rebuilt whenever the
    tray's fingerprint moves, i.e. many times an hour, so an inline definition
    works exactly once and then takes the tray down.
    """
    global _DARWIN_HELPERS
    if _DARWIN_HELPERS is not None:
        return _DARWIN_HELPERS

    import objc
    from Foundation import NSObject

    class CCSyncTrayTarget(NSObject):
        """The action target for one menu item. AppKit holds menu targets
        weakly, so the Icon keeps them alive in self._targets for as long as
        the menu is installed."""

        def initWithIcon_item_(self, icon, item):
            self = objc.super(CCSyncTrayTarget, self).init()
            if self is None:
                return None
            self._icon = icon
            self._item = item
            return self

        def invoke_(self, _sender):
            try:
                self._item.action(self._icon, self._item)
            except Exception:
                log.exception("tray menu action failed")

    class CCSyncTrayMenuWatcher(NSObject):
        """NSMenuDelegate, for the open/closed flag tray.py's refresh and pulse
        loops (and resolve_bridge's GIL-holding fusionscript calls) defer on.
        pystray offered no way to learn this on macOS at all, so until
        2026-08-17 the Mac tray updated straight through an open menu."""

        def initWithIcon_(self, icon):
            self = objc.super(CCSyncTrayMenuWatcher, self).init()
            if self is None:
                return None
            self._icon = icon
            return self

        def menuWillOpen_(self, _menu):
            self._icon._menu_open.set()

        def menuDidClose_(self, _menu):
            self._icon._menu_open.clear()

    _DARWIN_HELPERS = (CCSyncTrayTarget, CCSyncTrayMenuWatcher)
    return _DARWIN_HELPERS


def _darwin_on_main_thread(fn: Callable[[], Any]) -> None:
    """Run `fn` on the macOS main thread, without waiting for it.

    comp-app-core-2 (2026-08-21). Every AppKit object below is main-thread
    only, and tray.py drives them from worker threads: _refresh_loop assigns
    icon.title every 2 s and icon.menu on every fingerprint change,
    _pulse_loop assigns icon.icon up to 8x every 3 s. pystray's darwin
    backend wrapped exactly these three in a mainthread decorator and this
    rewrite dropped it, so the tray has been calling setImage_/setToolTip_/
    setMenu_ off-thread on every Mac: Main Thread Checker territory, and in
    practice intermittent menu-bar corruption or a crash inside AppKit with
    no Python traceback. Rebinding the menu while the user has it open is the
    worst of it -- the NSMenu they are tracking is replaced under them.

    ASYNC, not ui_dispatch.dispatch(): dispatch blocks the caller until the
    main thread pumps it, and that pump parks inside a modal dialog's tkwait
    (MAC-11) -- a tray refresh thread must never be able to wait on an open
    window. The main queue is drained by the same runloop Tk-Aqua is already
    spinning, and it preserves order, so the pulse's frames still arrive in
    the order they were produced.

    Falls back to running `fn` inline if the hop itself is unavailable: a
    tray that draws from the wrong thread is what we have today, and it beats
    a tray that stops drawing.
    """
    try:
        from Foundation import NSOperationQueue, NSThread

        if NSThread.isMainThread():
            fn()
            return
        NSOperationQueue.mainQueue().addOperationWithBlock_(fn)
    except Exception:
        log.debug("tray: could not marshal to the main thread", exc_info=True)
        try:
            fn()
        except Exception:
            log.debug("tray: the un-marshalled update failed too", exc_info=True)


class _DarwinIcon:
    """The menu-bar item on macOS, via NSStatusBar/NSStatusItem/NSMenu.

    NSStatusItem is main-thread-only, so run_detached() is the only supported
    entry point in practice: tray.py calls it from the thread that is about to
    become the UI runloop (Tk-Aqua drives NSApp), and the item then lives on
    that runloop with no thread of its own.

    `_status_item` is public-by-convention: tray.py's macOS placement check
    (MAC-7 -- "the icon started, but is anyone seeing it?") reads the item's
    button window frame through it. Keeping the name is what makes that code
    unchanged by this rewrite.
    """

    def __init__(self, name: str, image=None, title: str = "", menu=None,
                 menu_open_flag: Optional[threading.Event] = None) -> None:
        self.name = name
        self._image = image
        self._title = title or ""
        self.menu = menu
        self._menu_open = menu_open_flag or threading.Event()
        self._status_item = None
        self._delegate = None
        self._targets: list = []
        self._stopped = threading.Event()
        # The main-thread hop, per instance so a test can hold it
        # (comp-app-core-2, 2026-08-21). Assigned before anything can call
        # __setattr__'s `menu` branch below.
        self._to_main = _darwin_on_main_thread

    @property
    def icon(self):
        return self._image

    @icon.setter
    def icon(self, image) -> None:
        self._image = image
        self._apply_image()

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value or ""
        self._to_main(self._apply_title)

    def _apply_title(self) -> None:
        try:
            button = self._status_item.button() if self._status_item else None
            if button is not None:
                button.setToolTip_(self._title)
        except Exception:
            log.debug("could not set the menu bar tooltip", exc_info=True)

    def run_detached(self) -> None:
        import AppKit

        bar = AppKit.NSStatusBar.systemStatusBar()
        self._status_item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self._apply_image()
        button = self._status_item.button()
        if button is not None:
            button.setToolTip_(self._title)
        self._apply_menu()

    def run(self) -> None:
        """Only for symmetry with the Windows backend -- tray.py takes
        run_detached() on macOS because NSStatusItem must be created on the
        thread that owns the runloop."""
        self.run_detached()
        self._stopped.wait()

    def stop(self) -> None:
        try:
            import AppKit

            if self._status_item is not None:
                AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
        except Exception:
            log.debug("could not remove the menu bar item", exc_info=True)
        self._status_item = None
        self._stopped.set()

    def notify(self, message: str, title: Optional[str] = None) -> None:
        """User-visible notification.

        Through `osascript` rather than a framework call on purpose:
        NSUserNotification is deprecated and removed, and UserNotifications
        requires a signed, bundled application to deliver anything at all --
        which the companion is not today (it ships as a bare executable, see
        build.spec). A notification is a nicety; it must never be a reason the
        tray fails to start.
        """
        import subprocess

        def _quote(text: str) -> str:
            return str(text).replace("\\", "\\\\").replace('"', '\\"')

        script = (f'display notification "{_quote(message)}" '
                  f'with title "{_quote(title or self.name)}"')
        try:
            subprocess.run(["osascript", "-e", script], check=False,
                           capture_output=True, timeout=10)
        except Exception:
            log.debug("macOS notification failed", exc_info=True)

    # -- AppKit plumbing ---------------------------------------------------

    def _ns_image(self):
        import io

        import AppKit

        if self._image is None:
            return None
        buffer = io.BytesIO()
        self._image.convert("RGBA").save(buffer, format="PNG")
        data = AppKit.NSData.dataWithBytes_length_(buffer.getvalue(), buffer.tell())
        image = AppKit.NSImage.alloc().initWithData_(data)
        # The menu bar is 22pt tall on every Mac since 10.10; an unresized
        # 64px mark is drawn at 64pt and pushes everything else off the bar.
        image.setSize_(AppKit.NSMakeSize(20, 20))
        return image

    def _apply_image(self) -> None:
        self._to_main(self._apply_image_now)

    def _apply_image_now(self) -> None:
        try:
            if self._status_item is None:
                return
            button = self._status_item.button()
            if button is not None:
                button.setImage_(self._ns_image())
        except Exception:
            log.debug("could not set the menu bar image", exc_info=True)

    def _apply_menu(self) -> None:
        self._to_main(self._apply_menu_now)

    def _apply_menu_now(self) -> None:
        try:
            if self._status_item is None:
                return
            self._status_item.setMenu_(self._build_nsmenu(self.menu))
        except Exception:
            log.exception("could not build the macOS tray menu")

    def _build_nsmenu(self, menu):
        import AppKit

        if menu is None:
            return None

        _Target, _MenuWatcher = _darwin_helper_classes()
        targets: list = []

        def build(source):
            ns_menu = AppKit.NSMenu.alloc().init()
            ns_menu.setAutoenablesItems_(False)
            for item in source.rendered():
                if item.is_separator:
                    ns_menu.addItem_(AppKit.NSMenuItem.separatorItem())
                    continue
                ns_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    item.label(), None, "")
                ns_item.setEnabled_(bool(item.is_enabled()))
                checked = item.is_checked()
                if checked is not None:
                    ns_item.setState_(1 if checked else 0)
                if item.submenu is not None:
                    ns_item.setSubmenu_(build(item.submenu))
                elif item.action is not None:
                    target = _Target.alloc().initWithIcon_item_(self, item)
                    targets.append(target)
                    ns_item.setTarget_(target)
                    ns_item.setAction_("invoke:")
                ns_menu.addItem_(ns_item)
            return ns_menu

        root = build(menu)
        watcher = _MenuWatcher.alloc().initWithIcon_(self)
        targets.append(watcher)
        root.setDelegate_(watcher)
        self._targets = targets
        self._delegate = watcher
        return root

    def __setattr__(self, name, value):
        # `menu` is a plain attribute everywhere else; on macOS the NSMenu has
        # to be rebuilt when it is rebound, and doing that here keeps tray.py
        # identical on both platforms.
        super().__setattr__(name, value)
        if name == "menu" and getattr(self, "_status_item", None) is not None:
            self._apply_menu()


# -- everywhere else --------------------------------------------------------


class _NullIcon:
    """No tray, but never a crash.

    Linux is not a supported client platform for the companion (no sidecars,
    no package channel, the Resolve bridge returns None) and there is no
    reason for the absence of a tray to stop the lanes from syncing. Every
    method is a no-op that logs once.
    """

    def __init__(self, name: str, image=None, title: str = "", menu=None,
                 menu_open_flag: Optional[threading.Event] = None) -> None:
        self.name = name
        self.icon = image
        self.title = title or ""
        self.menu = menu
        self._stopped = threading.Event()
        log.warning("no tray backend for platform %r -- the companion will run "
                    "with no tray icon", sys.platform)

    def run(self) -> None:
        self._stopped.wait()

    def run_detached(self) -> None:
        return None

    def stop(self) -> None:
        self._stopped.set()

    def notify(self, message: str, title: Optional[str] = None) -> None:
        log.info("tray notification (no tray backend): %s", message)


def Icon(name: str, image=None, title: str = "", menu=None,
         menu_open_flag: Optional[threading.Event] = None):
    """The tray icon for this platform.

    A function rather than a class so tray.py can keep calling
    `Icon(name, image, title, menu=...)` while the object it gets back is the
    platform's, and so a test can substitute it by assignment the way it
    always could.
    """
    if sys.platform == "win32":
        return _WindowsIcon(name, image, title, menu, menu_open_flag)
    if sys.platform == "darwin":
        return _DarwinIcon(name, image, title, menu, menu_open_flag)
    return _NullIcon(name, image, title, menu, menu_open_flag)


__all__ = ["Icon", "Menu", "MenuItem"]
