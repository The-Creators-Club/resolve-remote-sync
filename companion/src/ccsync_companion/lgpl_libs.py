"""Where the companion's LGPL libraries are loaded from, and how to replace one.

GL-32 / CR-375 (2026-10-07, docs/PRELAUNCH_REVIEW_2026-10-06.md, COM-H3).
psycopg2 is LGPL-3.0-or-later, and the companion is a single-file PyInstaller
exe. Frozen into the archive, psycopg2, libpq and OpenSSL are unpacked to a
fresh temp directory on every launch, so nobody could swap in their own
build without rebuilding our exe, which is what LGPL section 4 forbids. (The
same reason pystray left the build, see build.spec.)

Since this change `build.spec` keeps psycopg2 OUT of the analysed archive and
ships the package as plain files under `ccsync_lib/` in the bundle (a
directory, byte-identical to the wheel's). `activate()` puts two directories on
`sys.path` ahead of everything the exe imports from:

  1. the user directory, `~/.ccsync/lib` (or the `CCSYNC_LGPL_LIB_DIR`
     environment variable): drop a `psycopg2/` package built from modified
     source here and it is the copy that loads, no rebuild and no
     re-signing of anything of ours;
  2. the bundled `ccsync_lib/` directory.

Because psycopg2 is not in the PYZ archive, the ordinary path finder does the
search and an earlier entry wins. In a source checkout (the dev venv, tests)
nothing is added: pip's psycopg2 is found on sys.path as it always was.

The Cards engine is the only importer and does so lazily, so `activate()` is
called before the engine is imported (`timeline_cards_role.load_engine`) and
from `app` start-up. It is idempotent and never raises: a failure here must
never stop a fleet syncing.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Under "ccsync.", not __name__: setup_logging() only attaches handlers to
# "ccsync", so a module logger named anything else is discarded (B8,
# test_shutdown_guard; GL-32, CR-375, 2026-10-07).
log = logging.getLogger("ccsync.lgpl_libs")

ENV_VAR = "CCSYNC_LGPL_LIB_DIR"
BUNDLED_SUBDIR = "ccsync_lib"


def user_lib_dir() -> Path:
    """The directory a user drops a replacement library into."""
    override = os.environ.get(ENV_VAR, "").strip()
    if override:
        return Path(override)
    return Path.home() / ".ccsync" / "lib"


def bundled_lib_dir() -> Path | None:
    """`<_MEIPASS>/ccsync_lib` in a frozen build, else None."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    return Path(base) / BUNDLED_SUBDIR


def search_dirs() -> list[Path]:
    """Directories to put on sys.path, most preferred first. Only ones that
    exist: an absent user directory is the normal case."""
    out: list[Path] = []
    try:
        user = user_lib_dir()
        if user.is_dir():
            out.append(user)
    except OSError:
        pass
    bundled = bundled_lib_dir()
    if bundled is not None and bundled.is_dir():
        out.append(bundled)
    return out


def activate() -> list[str]:
    """Prepend the replaceable-library directories to sys.path. Returns the
    entries added (empty when there was nothing to do)."""
    added: list[str] = []
    try:
        dirs = search_dirs()
        # Insert in reverse so dirs[0] ends up first on the path.
        for d in reversed(dirs):
            s = str(d)
            if s in sys.path:
                sys.path.remove(s)
            sys.path.insert(0, s)
        added = [str(d) for d in dirs]
        user = user_lib_dir()
        if added and str(user) in added and "psycopg2" not in sys.modules:
            if (user / "psycopg2").exists():
                log.info("lgpl_libs: loading psycopg2 from the user "
                         "directory %s (replaces the bundled copy)", user)
    except Exception:                                          # noqa: BLE001
        log.debug("lgpl_libs.activate failed", exc_info=True)
    return added
