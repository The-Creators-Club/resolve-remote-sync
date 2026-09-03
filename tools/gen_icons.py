"""Redraw every raster icon in the repo from the ONE brand mark.

    companion\\.venv\\Scripts\\python.exe tools\\gen_icons.py [--check] [--mark PATH]

Source: companion/src/ccsync_companion/assets/cc_mark_white.png -- the Creators
Club mark, white on transparency (theme.PRODUCT_MARK_ASSET; owner's ruling
2026-08-18, "the CC mark is the product brand"). Everything below is that one
file tinted and scaled, so a brand change is one asset swap and one command.

Why this exists (2026-09-03): the shipped icon.ico / icon.png / favicon.png
were "April's" pre-composed mark baked onto an OPAQUE BLACK SQUARE, so the
Start Menu, the taskbar and the browser tab all showed a black tile with the
mark in it -- against Windows 11's light Start Menu that reads as a bug. The
tray and the popup windows had already moved to tinting cc_mark_white.png's
alpha channel (tray._make_icon_image, theme.window_icon_png_b64); these files
were the last ones still carrying the ground. They are tinted here the SAME
way -- a solid RGB wearing the mark's own alpha, via putalpha rather than a
paste-through-mask, because pasting blends the RGB against the transparent
canvas and leaves the anti-aliased rim a dark red that composites as a black
halo over a light title bar (theme.py has the long version).

Two deliberate exceptions to "transparent everywhere":

  * the MASKABLE PWA pair. The maskable spec has the launcher crop the icon to
    whatever shape it likes and fill nothing: a transparent maskable icon is
    an icon with holes in it. They keep an opaque ground, but it is the brand
    red with the mark in white, never the old black square, and the mark is
    scaled to clear the 80% safe circle.
  * static/icons/icon-180.png (the apple-touch-icon) and icon.svg are NOT
    written here and stay with tools/make_icons.js: iOS composites a
    transparent apple-touch-icon onto black, which is the very tile we are
    removing.

Pillow only (it is in the companion venv; the dashboard venv has no PIL, which
is why the PWA sizes are pinned in dashboard/tests/test_pwa.py from the IHDR
rather than drawn there). --check re-renders into memory and reports which
committed files are stale, without writing.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MARK = ROOT / "companion" / "src" / "ccsync_companion" / "assets" / "cc_mark_white.png"

# theme.RGB_RED / theme.RED. One spelling of "brand red" per repo: a second is
# how palettes drift apart (2026-08-11).
RED = (255, 33, 64)
WHITE = (255, 255, 255)

# The mark is WIDE (its alpha bbox is 512x244, edge to edge) and every target
# here is SQUARE, so it is centred with a margin rather than stretched. 0.92 of
# the width for the app/tab icons -- a mark that touches the edge looks clipped
# once Windows draws a selection box around it.
COVER_ANY = 0.92
# 0.60 for the maskable pair: Android crops to a circle of 80% diameter, so the
# mark's half-diagonal must clear 0.4 of the box. sqrt(1 + 0.4658**2) = 1.103,
# so a width of 0.72 is the limit and 0.60 leaves room for a launcher that
# crops harder than the spec.
COVER_MASKABLE = 0.60

# Supersample factor: draw at 4x the target and LANCZOS down once, so a 16 px
# icon is a proper area average of the 512 px mark rather than a resize of a
# resize.
SUPERSAMPLE = 4

# LANCZOS on a 1-2 px stroke gives back a stroke that is mostly-transparent
# everywhere, and at 16/24/32 px the "//" mark simply disappears in the Start
# Menu. A gain on the alpha channel puts the weight back without touching the
# geometry. Only the small sizes need it; anything from 48 px up is drawn as it
# was designed.
SMALL_ALPHA_GAIN = 1.35
SMALL_MAX = 32

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)      # the exe icon (build.spec)
FAVICON_ICO_SIZES = (16, 32, 48)                # the browser tab / bookmark bar


def _mark_alpha(path: Path) -> Image.Image:
    """The mark's alpha channel, cropped to its own ink. Greyscale, any size.

    Cropped rather than used whole because the source's transparent margin is
    not symmetric, and centring a bbox is the only way to get the same optical
    position at every scale."""
    with Image.open(path) as src:
        alpha = src.convert("RGBA").getchannel("A")
    box = alpha.getbbox()
    if box is None:
        raise SystemExit(f"{path} has no visible pixels: it is not a mark")
    return alpha.crop(box)


def _compose(ink: Image.Image, size: int, colour: tuple, cover: float,
             ground: tuple | None = None) -> Image.Image:
    """`ink` (a greyscale mask) painted `colour` on a `size` square.

    ground=None leaves the rest of the square fully transparent; a ground tuple
    fills it opaque (the maskable case)."""
    big = size * SUPERSAMPLE
    width = max(1, int(round(big * cover)))
    height = max(1, int(round(width * ink.height / ink.width)))
    scaled = ink.resize((width, height), Image.LANCZOS)

    mask = Image.new("L", (big, big), 0)
    mask.paste(scaled, ((big - width) // 2, (big - height) // 2))
    mask = mask.resize((size, size), Image.LANCZOS)
    if size <= SMALL_MAX:
        mask = mask.point(lambda a: min(255, int(a * SMALL_ALPHA_GAIN)))

    if ground is None:
        out = Image.new("RGBA", (size, size), (*colour, 255))
        out.putalpha(mask)
        return out
    # Opaque ground: the mark's alpha is a blend factor between the two solid
    # colours, so the anti-aliased rim lands between them instead of fading to
    # nothing (which on a coloured ground would read as a dark fringe).
    out = Image.new("RGBA", (size, size), (*ground, 255))
    out.paste(Image.new("RGBA", (size, size), (*colour, 255)), (0, 0), mask)
    return out


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _ico_bytes(ink: Image.Image, sizes) -> bytes:
    """A multi-size .ico with EVERY size drawn from the mark.

    Pillow's ICO writer will happily derive the smaller frames itself from one
    image, but then the 16 px frame is a plain downscale of the 256 and gets
    none of the alpha gain above -- which is exactly the size the Start Menu
    and the tab strip use. append_images hands it real frames instead."""
    frames = [_compose(ink, s, RED, COVER_ANY) for s in sorted(sizes, reverse=True)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="ICO",
                   sizes=[(s, s) for s in sorted(sizes)],
                   append_images=frames[1:])
    return buffer.getvalue()


def targets(ink: Image.Image) -> list:
    """(relative path, bytes, description) for every file this tool owns."""
    out = []

    def png(rel: str, size: int, colour=RED, cover=COVER_ANY, ground=None, note=""):
        out.append((rel, _png_bytes(_compose(ink, size, colour, cover, ground)),
                    note or f"{size}x{size} transparent"))

    # -- the companion: the exe icon (Start Menu, taskbar, Explorer) and the
    # window/popup fallback theme.icon_path() still names.
    out.append(("companion/src/ccsync_companion/assets/icon.ico",
                _ico_bytes(ink, ICO_SIZES),
                "ico " + ",".join(str(s) for s in ICO_SIZES) + " transparent"))
    png("companion/src/ccsync_companion/assets/icon.png", 512)

    # -- the browser tabs. The .svg favicons beside these already draw the mark
    # with no ground and are left alone.
    png("dashboard/static/favicon.png", 512)
    out.append(("dashboard/static/favicon.ico", _ico_bytes(ink, FAVICON_ICO_SIZES),
                "ico " + ",".join(str(s) for s in FAVICON_ICO_SIZES) + " transparent"))
    png("broll/web/static/favicon.png", 512)

    # -- the PWA icons the dashboard manifest names. purpose "any" is shown as
    # drawn, so transparency is correct; purpose "maskable" is cropped and
    # therefore keeps a ground (see the module docstring).
    png("dashboard/static/icons/icon-192.png", 192)
    png("dashboard/static/icons/icon-512.png", 512)
    for size in (192, 512):
        png(f"dashboard/static/icons/icon-{size}-maskable.png", size,
            colour=WHITE, cover=COVER_MASKABLE, ground=RED,
            note=f"{size}x{size} white mark on the brand red (maskable safe zone)")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report stale files, write nothing")
    parser.add_argument("--mark", default=str(MARK),
                        help="the white-on-transparent mark to draw from")
    args = parser.parse_args(argv)

    ink = _mark_alpha(Path(args.mark))
    stale = 0
    for rel, data, note in targets(ink):
        path = ROOT / rel
        current = path.read_bytes() if path.is_file() else None
        if args.check:
            # Byte equality is fair here (one writer, one Pillow), but a
            # mismatch is only ever reported, never acted on.
            if current != data:
                print(f"  STALE   {rel}")
                stale += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"  wrote   {rel}  ({note}, {len(data)} bytes)")
    if args.check:
        print("icons are stale: " + str(stale) if stale else "icons are current")
        return 1 if stale else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
