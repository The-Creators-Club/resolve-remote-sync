"""Paths and runtime settings. Env vars override every value.

Everything is `YTDL_`-prefixed because this app is mounted INSIDE the dashboard
container and shares one environment with the dashboard, with b-roll (`BROLL_*`)
and with music (`MUSIC_*`). A bare DATA_ROOT there is a name collision waiting
to happen.

The values are read at import time and the defaults are POSIX, because the
deployed host is the container: `/ytdl-data`, `/projects`, `/data/dashboard.db`.
On a Windows dev box nothing at those paths exists, so every one of them is set
by the caller (tests point them at a temp tree). Nothing here touches the disk
at import -- see ensure_data_root() for why that matters to the mount.
"""
import os
import re
import unicodedata
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent        # ytdl/web/ytdlweb
WEB_DIR = PKG_DIR.parent                         # ytdl/web

STATIC_DIR = WEB_DIR / 'static'
SCHEMA_PATH = WEB_DIR / 'schema.sql'
MIGRATIONS_DIR = WEB_DIR / 'migrations'

# The ONLY tree this app writes to that is its own: ytdl.db lives here, and so
# does claude_cli's cwd. In the container it is a 3000:3000 rw volume.
DATA_ROOT = Path(os.environ.get('YTDL_DATA_ROOT') or WEB_DIR / 'data')
DB_PATH = DATA_ROOT / 'ytdl.db'

# The Projects tree, mounted rw in the container. Downloads land at
# <PROJECTS_ROOT>/<project label>/Youtube/<term_dir>/ -- which sync then
# distributes, so an editor sees P:\Projects\<label>\Youtube\<term>.
PROJECTS_ROOT = Path(os.environ.get('YTDL_PROJECTS_ROOT') or WEB_DIR / 'data' / 'projects')

# The DASHBOARD's database, opened READ-ONLY for the ticked-projects query
# (projects.py). Unset = standalone dev; the app still runs, it just has no
# real project list to offer. It is deliberately not a default path: guessing
# at one and finding some other sqlite file would be worse than saying so.
DASH_DB = os.environ.get('YTDL_DASH_DB') or ''

# yt-dlp cookies. A cookies.txt FILE, never cookiesfrombrowser: there is no
# browser in the container and no profile for uid 3000 to read. This is the
# escape hatch for YouTube bot-checking the NAS IP (see DEPLOY.md).
COOKIES_FILE = os.environ.get('YTDL_COOKIES_FILE') or ''

# HOME/CLAUDE_CONFIG_DIR for the `claude` subprocess ONLY (claude_cli._env).
# uid 3000 has no passwd entry in the slim image, so claude needs to be told
# where its credentials live -- but exporting HOME globally in run.sh would
# change it for the dashboard, ffmpeg and everything else in the container.
CLAUDE_HOME = os.environ.get('YTDL_CLAUDE_HOME') or '/claude-home'
CLAUDE_BIN = os.environ.get('YTDL_CLAUDE_BIN') or 'claude'
CLAUDE_MODEL = os.environ.get('YTDL_CLAUDE_MODEL') or 'sonnet'
CLAUDE_TIMEOUT = int(os.environ.get('YTDL_CLAUDE_TIMEOUT') or '180')

# The container ships ffmpeg at /opt/ffmpeg (same bind mount music/web's ingest
# uses). Passed to yt-dlp as ffmpeg_location; None means "whatever is on PATH",
# which is what a dev box wants.
FFMPEG_DIR = os.environ.get('YTDL_FFMPEG_DIR') or ('/opt/ffmpeg'
                                                   if os.path.isdir('/opt/ffmpeg') else '')

# Seconds between downloads. Pacing, not politeness: bulk anonymous downloads
# from one NAS IP are what triggers YouTube's bot checks. Tests set it to 0.
DOWNLOAD_PAUSE = float(os.environ.get('YTDL_DOWNLOAD_PAUSE') or '3')

# How many search terms a job may ever run. Claude is asked for 8-12 + 8-12,
# so this is a ceiling on a bad day rather than a normal limit.
MAX_TERMS = int(os.environ.get('YTDL_MAX_TERMS') or '24')

# Standalone dev only: who the API thinks you are when no dashboard gate has
# injected the header. Never set on a deployed host.
DEV_USER = os.environ.get('YTDL_DEV_USER') or ''

# Standalone dev only: 'slug=label,slug2=label2' so the project picker has
# something to offer with no dashboard database in reach.
DEV_PROJECTS = os.environ.get('YTDL_DEV_PROJECTS') or ''

HOST = os.environ.get('YTDL_HOST') or '127.0.0.1'
PORT = int(os.environ.get('YTDL_PORT') or '8791')


def ensure_data_root():
    """Create DATA_ROOT. Called from startup and from the mount, NOT at import.

    Same rule as musicweb.config.ensure_data_root, and the same failure it
    avoids: a mkdir at module scope turns an unwritable data root into an
    ImportError, which the dashboard mount reports as ABSENT ("the ytdl tree
    was never shipped") when the truth is DEGRADED ("the tree is here and its
    data root is not usable by this container's uid"). Those are different
    operator problems and the mount is built to tell them apart.
    """
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return DATA_ROOT


# ------------------------------------------------------------- path safety
# The same rules musicweb.config enforces, for the same reason: a value that
# came off the wire (a project label, a search term) must not be able to
# contribute a path segment that escapes the root it is joined to.

_DRIVE_RE = re.compile(r'^[A-Za-z]:')


class PathTraversalError(ValueError):
    """Raised when a joined component is not relative, or escapes the root."""


def safe_join(root, *parts):
    """root / parts..., or raise. Parts may themselves contain '/' separators.

    `project_label` is a rel path ('2026/FF5/Energy Transition'), so this takes
    varargs rather than musicweb's single rel_path -- the caller writes
    safe_join(PROJECTS_ROOT, label, 'Youtube', term_dir) and every segment of
    every part is validated.
    """
    segs = []
    for part in parts:
        if part is None:
            continue
        norm = str(part).replace('\\', '/')
        # An absolute part is a contradiction, and joinpath would honour it and
        # hand back a path with nothing to do with the root.
        if norm.startswith('/') or _DRIVE_RE.match(norm):
            raise PathTraversalError(f'path component must be relative, got {part!r}')
        for seg in norm.split('/'):
            if seg in ('', '.'):
                continue
            if seg == '..':
                raise PathTraversalError("path traversal rejected: '..' in " + repr(part))
            # Defence in depth: a drive letter smuggled in as a segment ("C:")
            # is not a directory name, and Path.joinpath would re-anchor on it.
            if seg.endswith(':'):
                raise PathTraversalError(f'invalid path segment {seg!r} in {part!r}')
            segs.append(seg)
    if not segs:
        raise PathTraversalError('empty path after normalisation')

    root = Path(root)
    path = root.joinpath(*segs)
    # Last line of defence: a symlink or a component the checks above did not
    # anticipate must not land outside the root. strict=False, because the
    # caller is usually asking about a directory it is about to create.
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        raise PathTraversalError(
            f'path escapes the root: {parts!r}') from None
    return path


# Windows-forbidden characters plus the separators, because the folder this
# names is created on the NAS and then read over SMB by every editor. A term
# containing ':' would sync to a name Explorer cannot open.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TERM_BYTE_CAP = 80


def safe_term_dirname(term, fallback='search'):
    """A search term reduced to a directory name that survives NAS -> SMB.

    Three separate constraints, none of them optional:
      - traversal: no separators, no '..', no drive letters (safe_join
        re-validates, but a term that reached it as '../..' would 500 rather
        than just being filed oddly);
      - Windows: <>:"/\\|?* are illegal in a name, and a trailing dot or space
        makes a directory Explorer cannot delete;
      - length: NFS and SMB cap a NAME at 255 BYTES, and Chinese is 3 bytes a
        character, so the cap is counted in bytes and cut on a character
        boundary. 80 leaves room for the file names inside.
    """
    s = unicodedata.normalize('NFC', str(term or ''))
    s = _UNSAFE_CHARS.sub(' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = s.strip('. ')                       # Windows: no trailing dot or space
    if s in ('', '.', '..'):
        return fallback
    enc = s.encode('utf-8')
    if len(enc) > _TERM_BYTE_CAP:
        s = enc[:_TERM_BYTE_CAP].decode('utf-8', errors='ignore').strip().strip('. ')
    return s or fallback
