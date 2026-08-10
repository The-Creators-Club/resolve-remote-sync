"""Optional system tray icon (pystray + Pillow).

Only imported inside a try/except ImportError in server.run(), so the app
still runs headless (console logs only) if these aren't installed. Install
with: pip install broll-companion[tray]
"""

from __future__ import annotations

import threading

import pystray  # noqa: F401  (raises ImportError here if missing — by design)
from PIL import Image, ImageDraw


def _make_icon_image():
    img = Image.new("RGB", (64, 64), "black")
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=(214, 39, 40))
    draw.text((24, 24), "B", fill="white")
    return img


def start_tray(server) -> "pystray.Icon":
    """Start a tray icon with a Quit action. Returns the Icon (call .stop())."""

    def on_quit(icon, _item) -> None:
        icon.stop()
        server.shutdown()

    menu = pystray.Menu(pystray.MenuItem("Quit BRoll Companion", on_quit))
    icon = pystray.Icon("broll-companion", _make_icon_image(), "BRoll Companion", menu)
    thread = threading.Thread(target=icon.run, daemon=True)
    thread.start()
    return icon
