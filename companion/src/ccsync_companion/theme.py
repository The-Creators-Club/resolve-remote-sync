"""The visual theme — neon-red terminal aesthetic shared by the popup dialog
and the tray icon (a WRITE.EXE-style look). The MARK it paints is site data,
not a compiled-in logo: see WINDOW_ICON_ASSET / brand_logo_override.

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


def asset_path(name: str):
    """Path to a file in assets/, or None if this build hasn't got it.

    Works both from source (assets/ next to this file) and from a frozen
    onefile build (extracted under sys._MEIPASS -- see build.spec's datas,
    which lists each shipped file explicitly).

    None rather than a raise, and every caller must treat it that way: an
    asset is decoration, and a frozen build published BEFORE a given file was
    added to datas will not have it (2026-08-10, when the tray icon started
    reading cc_mark_white.png)."""
    from pathlib import Path

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "ccsync_companion" / "assets" / name)
    candidates.append(Path(__file__).resolve().parent / "assets" / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def icon_path():
    """Path to the OLD pre-composed logo PNG, or None.

    Deliberately still points at assets/icon.png (April's already-coloured,
    already-composed mark) rather than being repointed at the new white mark:
    it names a *file on disk*, which is what a caller wanting to hand a path
    to something outside Tk needs, and test_tray pins asset_path("icon.png")
    == icon_path(). Since 2026-08-11 the window icon prefers the tinted new
    mark and this is only its fallback -- see window_icon_png_b64."""
    return asset_path("icon.png")


# The window icon is the SAME white-on-transparent mark the tray tints per
# status (tray.MARK_ASSET), not the pre-composed icon.png -- one mark for the
# taskbar, the title bar and the tray, differing only in colour (2026-08-11).
#
# WHICH mark is an indirection as of 2026-08-17
# (docs/COMMERCIAL_READINESS.md item 10). The default is the product's own
# neutral mark; cc_mark_white.png -- one studio's logo -- is still shipped and
# still selectable, but a build no longer wears it by default:
#
#     CCSYNC_BRAND_LOGO=cc_mark_white.png      a file inside assets/
#     CCSYNC_BRAND_LOGO=C:\brand\acme.png      any white-on-transparent PNG
#
# Env rather than config.toml because both the tray and the popups need it
# before (and without) a config load, and because the installer that brands a
# fleet is the thing that sets machine environment. It must be
# WHITE-ON-TRANSPARENT: everything below tints the alpha channel, so a
# pre-coloured logo comes out as a solid red blob.
BRAND_LOGO_ENV = "CCSYNC_BRAND_LOGO"
PRODUCT_MARK_ASSET = "ccsync_mark.png"
WINDOW_ICON_ASSET = PRODUCT_MARK_ASSET

# 128 px, not the asset's native 512: Windows scales an iconphoto down to
# 16/32/48 (96 on a 200% display) and every root that gets one holds the
# decoded bitmap for its lifetime, so 512 would be 1 MB per window for pixels
# nobody ever sees.
WINDOW_ICON_SIZE = 128


def brand_logo_override():
    """$CCSYNC_BRAND_LOGO resolved to a real file, or None.

    A bare name is looked up in assets/ (so a site can select the mark this
    build already ships); anything with a separator is taken as a path. An
    override that names a file that is not there is IGNORED rather than fatal
    -- a wrong logo path must not stop an editor's tray coming up."""
    import os
    from pathlib import Path

    raw = str(os.environ.get(BRAND_LOGO_ENV, "") or "").strip().strip('"')
    if not raw:
        return None
    if "/" not in raw and "\\" not in raw:
        return asset_path(raw)
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_file() else None


def window_mark_path():
    """Where the white mark lives in this build, or None. Its own function so
    a test can point it elsewhere (and so the icon.png fallback below is
    reachable)."""
    return brand_logo_override() or asset_path(WINDOW_ICON_ASSET)


# Rendered at most once per (asset, colour, size) per process: apply_window_icon
# runs for every popup and every tray window, and a LANCZOS downscale of a
# 512x512 PNG per dialog is pure waste. Same precedent as tray._MARK_MASK_CACHE.
_WINDOW_ICON_CACHE: dict = {}


def window_icon_png_b64(color: tuple = RGB_RED, size: int = WINDOW_ICON_SIZE):
    """The mark tinted `color`, as a base64 PNG string -- or None if this build
    has no such asset (or Pillow cannot read it).

    Base64 rather than a file because a tinted image has no file: Tk 8.6's
    PhotoImage(data=...) takes a base64 PNG directly, which avoids both a temp
    file and PIL.ImageTk (an import the frozen build has never shipped, so
    build.spec has never been proven to carry it).

    The tint is a solid colour wearing the mark's own alpha -- the asset is
    white-on-transparent precisely so this works at any colour without touching
    its anti-aliased edges (the same technique as tray._make_icon_image).
    putalpha rather than paste-through-a-mask, though: paste blends the RGB
    channels against the transparent canvas too, leaving the soft rim a dark
    red that reads as a black halo once Windows composites the icon over a
    light title bar. This way every pixel is the brand red and only the alpha
    varies.

    None is a supported answer, not an error: an old frozen build published
    before cc_mark_white.png was in build.spec's datas lands here, and
    apply_window_icon falls back to icon.png.
    """
    path = window_mark_path()
    key = (str(path) if path is not None else None, tuple(color), int(size))
    if key in _WINDOW_ICON_CACHE:
        return _WINDOW_ICON_CACHE[key]

    data = None
    if path is not None:
        try:
            import base64
            import io

            from PIL import Image

            with Image.open(path) as src:
                mask = (src.convert("RGBA")
                           .resize((size, size), Image.LANCZOS)
                           .getchannel("A"))
            image = Image.new("RGBA", (size, size), (*tuple(color), 255))
            image.putalpha(mask)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            data = base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            # Pillow absent/broken or the file unreadable. Not a log call:
            # theme is imported by headless paths that have no logger set up,
            # and the caller already degrades to icon.png.
            data = None
    _WINDOW_ICON_CACHE[key] = data
    return data


def _window_icon_image(tk_module, root):
    """The PhotoImage for this root's window icon, or None if this build has
    nothing to show.

    The fallback chain, in order: the new mark tinted brand red -> the old
    pre-composed icon.png -> nothing. Both steps are conditional on the build
    actually carrying the asset, and the base64 route degrades to the file
    route on any Tk that cannot decode PNG data (Tk < 8.6).
    """
    data = window_icon_png_b64()
    if data is not None:
        try:
            return tk_module.PhotoImage(data=data, master=root)
        except Exception:
            pass
    path = icon_path()
    if path is None:
        return None
    return tk_module.PhotoImage(file=str(path), master=root)


def apply_window_icon(tk_module, root) -> None:
    """Set the product mark, in brand red, as this window's
    title-bar/taskbar icon.

    Best-effort and never raises: an icon is decoration, and none of the
    popups may die over it (headless test runs have no display at all). The
    PhotoImage is parked on the root so it outlives this call -- Tk drops an
    icon whose image gets garbage-collected, and each Tk root needs its own
    image (a PhotoImage is bound to the interpreter that made it).

    RGB_RED, not the dashboard favicon's #CC0000: this is the one red the rest
    of the companion's chrome is painted in, and a second spelling of "brand
    red" in here is how palettes drift apart (2026-08-11)."""
    try:
        image = _window_icon_image(tk_module, root)
        if image is None:
            return
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
