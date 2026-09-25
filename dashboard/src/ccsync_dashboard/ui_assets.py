"""Content-hashed static URLs and the service worker's precache list (UI port
R8, 2026-09-25; kept when the look switch was retired the same day).

The CC Terminal look is the dashboard's ONLY look since the owner's
2026-09-25 decision ("this is completely replacing the old one"): the group
overlay, the X-CC-UI headers, the preview cookie and the `ui_terminal_groups`
setting that lived in `ui_variant.py` are gone. What survives is the part that
was never about choosing a look:

* `asset_url(path)`: `/static/<path>?h=<content hash>`. A content hash, not
  VERSION: a same-version redeploy (a CSS hotfix, an OTA bundle) must still
  change the URL, or the service worker pairs new HTML with the cached old
  sheet. `static_files.CachedStaticFiles` marks a current-hash URL immutable
  and any other hash no-store.
* `precache_urls()`: what `/sw.js` precaches beyond its own list, from the
  same hash map.
"""
from __future__ import annotations

import hashlib
import mimetypes
import threading
from pathlib import Path

# .woff2 has no entry in Python 3.12's own table and python:3.12-slim ships no
# /etc/mime.types, so StaticFiles would send the fonts as text/plain (2.3).
mimetypes.add_type("font/woff2", ".woff2")

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
CC_DIR_NAME = "cc"

_lock = threading.RLock()
_asset_hashes: dict[str, str] = {}


def refresh() -> None:
    """Forget every cached hash (tests write static files; a restart does
    this for free)."""
    with _lock:
        _asset_hashes.clear()


def asset_hash(path: str) -> str:
    """sha256[:10] of a static file's bytes, "" when it does not exist."""
    path = str(path).lstrip("/")
    with _lock:
        cached = _asset_hashes.get(path)
    if cached is not None:
        return cached
    try:
        digest = hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]
    except OSError:
        digest = ""
    with _lock:
        _asset_hashes[path] = digest
    return digest


def asset_url(path: str) -> str:
    """`/static/<path>?h=<content hash>`, or the plain URL for a file this
    build does not have."""
    path = str(path).lstrip("/")
    digest = asset_hash(path)
    return f"/static/{path}?h={digest}" if digest else f"/static/{path}"


def cc_assets() -> list[str]:
    """Every file under static/cc/, as paths relative to static/."""
    root = STATIC_DIR / CC_DIR_NAME
    if not root.is_dir():
        return []
    return sorted(p.relative_to(STATIC_DIR).as_posix()
                  for p in root.rglob("*") if p.is_file())


def font_files() -> list[str]:
    root = STATIC_DIR / "fonts"
    if not root.is_dir():
        return []
    return sorted(p.relative_to(STATIC_DIR).as_posix()
                  for p in root.iterdir() if p.suffix == ".woff2")


# The shared scripts every page loads through asset_url() (shell.html). The
# worker's own PRECACHE names them at their PLAIN urls for the offline page's
# sake; the hashed twins are what a live page asks for.
SHARED_SCRIPTS: tuple[str, ...] = ("pwa.js", "htmx.min.js", "htmx_errors.js",
                                   "tab_memory.js")


def precache_urls() -> list[str]:
    """What sw.js precaches beyond its own list (R8): the hashed cc/ sheets
    and scripts, the hashed shared scripts, and the fonts at their PLAIN urls
    (a static sheet's url() cannot carry the hash, and caches.match matches
    the query string)."""
    urls = [asset_url(p) for p in cc_assets()
            if p.endswith((".css", ".js"))]
    urls += [asset_url(p) for p in SHARED_SCRIPTS if asset_hash(p)]
    urls += [f"/static/{p}" for p in font_files()]
    return urls
