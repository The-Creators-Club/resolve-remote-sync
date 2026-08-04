"""Creators Club visual theme — neon-red terminal aesthetic shared by the
popup dialog and the tray icon (matches the site's WRITE.EXE-style look).

Pure constants + tiny helpers; no tkinter/PIL imports at module level so the
headless paths never pay for them.
"""

from __future__ import annotations

import sys

# -- palette -----------------------------------------------------------------
BG = "#0a0a0d"          # near-black window background
PANEL = "#101014"       # slightly lifted panels / buttons
FIELD = "#16161c"       # input fields
RED = "#ff2140"         # neon brand red — primary accent
RED_HOT = "#ff5c73"     # hover / glow state
RED_DIM = "#7c1322"     # rules, borders, quiet accents
GREEN = "#2bff88"       # phosphor green — OK / go
AMBER = "#ffb02e"       # warnings / in-progress
TEXT = "#e8e8ea"        # primary text
MUTED = "#6f6f7a"       # secondary text

# RGB tuples for PIL (tray icon)
RGB_BG = (10, 10, 13)
RGB_RED = (255, 33, 64)
RGB_GREEN = (43, 255, 136)
RGB_AMBER = (255, 176, 46)

RULE = "─" * 72  # terminal divider line


def icon_path():
    """Path to the Creators Club logo PNG bundled with the package, or None.

    Works both from source (assets/ next to this file) and from a frozen
    onefile build (extracted under sys._MEIPASS -- see build.spec's datas)."""
    from pathlib import Path

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "ccsync_companion" / "assets" / "icon.png")
    candidates.append(Path(__file__).resolve().parent / "assets" / "icon.png")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def apply_window_icon(tk_module, root) -> None:
    """Set the Creators Club logo as this window's title-bar/taskbar icon.

    Best-effort and never raises: an icon is decoration, and none of the
    popups may die over it (headless test runs have no display at all). The
    PhotoImage is parked on the root so it outlives this call -- Tk drops an
    icon whose image gets garbage-collected, and each Tk root needs its own
    image (a PhotoImage is bound to the interpreter that made it)."""
    try:
        path = icon_path()
        if path is None:
            return
        image = tk_module.PhotoImage(file=str(path), master=root)
        root._ccsync_icon_image = image
        root.iconphoto(True, image)
    except Exception:
        pass


def mono(size: int = 10, bold: bool = False) -> tuple:
    """Monospace font tuple for tkinter, per-platform."""
    family = "Consolas" if sys.platform == "win32" else (
        "Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono"
    )
    return (family, size, "bold") if bold else (family, size)


def style_combobox(ttk_module, master=None) -> str:
    """Register and return a dark ttk Combobox style name ("CC.TCombobox").

    Uses the 'clam' theme as the base — the only built-in theme whose
    Combobox honours fieldbackground on all platforms.

    Pass the window's own root as `master`: a ttk style lives in ONE Tcl
    interpreter, and on macOS the default root is ui_dispatch's hidden one,
    so a masterless Style() would paint the hidden window's theme and leave
    this dialog's combobox in default grey.
    """
    style = ttk_module.Style(master)
    style.theme_use("clam")
    style.configure(
        "CC.TCombobox",
        fieldbackground=FIELD,
        background=PANEL,
        foreground=TEXT,
        arrowcolor=RED,
        bordercolor=RED_DIM,
        lightcolor=PANEL,
        darkcolor=PANEL,
        insertcolor=RED,
        selectbackground=RED_DIM,
        selectforeground=TEXT,
    )
    style.map(
        "CC.TCombobox",
        fieldbackground=[("readonly", FIELD), ("focus", FIELD)],
        bordercolor=[("focus", RED)],
    )
    return "CC.TCombobox"


def style_progressbar(ttk_module, master=None) -> str:
    """Register and return a dark determinate ttk Progressbar style name.

    Same 'clam' base as style_combobox for the same reason -- it is the only
    built-in theme that honours the trough/bar colours everywhere. Used by
    the fixer's per-file and overall bars (AUDIT_2 UX-9), which exist because
    a multi-GB copy over SMB previously showed no motion at all for twenty
    minutes and was indistinguishable from a hang.

    Takes `master` for the same interpreter reason as style_combobox.
    """
    style = ttk_module.Style(master)
    style.theme_use("clam")
    style.configure(
        "CC.Horizontal.TProgressbar",
        troughcolor=FIELD,
        background=RED,
        bordercolor=RED_DIM,
        lightcolor=RED,
        darkcolor=RED_DIM,
        thickness=10,
    )
    return "CC.Horizontal.TProgressbar"


def neon_button(tk_module, parent, text: str, command, primary: bool = True):
    """A flat terminal-style button: [ TEXT ] with a neon hover glow.

    primary=True -> brand red; False -> muted gray that reddens on hover.
    """
    fg = RED if primary else MUTED
    btn = tk_module.Button(
        parent,
        text=f"[ {text} ]",
        command=command,
        font=mono(10, bold=primary),
        fg=fg,
        bg=BG,
        activeforeground=RED_HOT,
        activebackground=BG,
        bd=0,
        relief="flat",
        cursor="hand2",
        highlightthickness=0,
    )
    btn.bind("<Enter>", lambda _e: btn.config(fg=RED_HOT))
    btn.bind("<Leave>", lambda _e: btn.config(fg=fg))
    return btn
