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


def mono(size: int = 10, bold: bool = False) -> tuple:
    """Monospace font tuple for tkinter, per-platform."""
    family = "Consolas" if sys.platform == "win32" else (
        "Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono"
    )
    return (family, size, "bold") if bold else (family, size)


def style_combobox(ttk_module) -> str:
    """Register and return a dark ttk Combobox style name ("CC.TCombobox").

    Uses the 'clam' theme as the base — the only built-in theme whose
    Combobox honours fieldbackground on all platforms.
    """
    style = ttk_module.Style()
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
