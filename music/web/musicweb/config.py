"""Paths and runtime settings for the web half. Env vars override every value.

Split out of the standalone music-tagger's single `config.py` when the project
was folded in (2026-08-10). The index-time settings (ffmpeg, CLAP, window
sizes) live in `music/indexer/music_index/config.py`, which imports the shared
paths from here so writer and reader can never disagree about where the
database is.
"""
import os
import re
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent        # music/web/musicweb
WEB_DIR = PKG_DIR.parent                         # music/web
MUSIC_DIR = WEB_DIR.parent                       # music/

STATIC_DIR = WEB_DIR / 'static'
SCHEMA_PATH = WEB_DIR / 'schema.sql'
MIGRATIONS_DIR = WEB_DIR / 'migrations'

# ---------------------------------------------------------------- share roots
# The one share this library has, and where it is mounted per host. The base
# rig indexes off W:; every editor machine sees the same tree at P:, next to
# P:\Assets\B-roll Archive. The P: root is deliberately hardcoded fleet-wide
# (CLAUDE.md: "a configurable drive letter is explicitly deferred") -- these
# are two fixed mount points, not a setting.
SHARE = 'music'
BASE_RIG_ROOT = Path(r'W:\Creators_Club\Assets\Music')
EDITOR_ROOT = Path(r'P:\Assets\Music')


def _default_share_root():
    """Where this host has the library. Env wins, then W:, then P:.

    Probed rather than configured because the two hosts are distinguishable by
    the mount itself, and a wrong guess is loud (every file 404s) rather than
    silent. MUSIC_ROOT is still honoured: it predates the share model, is what
    DEPLOY.md documents, and is what the tests point at a temp directory.
    """
    env = os.environ.get('MUSIC_SHARE_ROOT') or os.environ.get('MUSIC_ROOT')
    if env:
        return Path(env)
    return BASE_RIG_ROOT if BASE_RIG_ROOT.is_dir() else EDITOR_ROOT


MUSIC_ROOT = _default_share_root()

# MUSIC_-prefixed, because this app is mounted INSIDE the dashboard container
# and shares its environment with b-roll (which namespaces everything as
# BROLL_*) and with run.sh. A bare DATA_ROOT there is a name collision waiting
# to happen. The unprefixed name stays as a fallback: it predates the mount and
# is what the dashboard's test conftest pins.
DATA_ROOT = Path(os.environ.get('MUSIC_DATA_ROOT')
                 or os.environ.get('DATA_ROOT')
                 or WEB_DIR / 'data')
DB_PATH = DATA_ROOT / 'music.db'

# ------------------------------------------------------------- preview proxies
# Port step 6. One 128k mp3 per track, so a remote editor previewing a cue over
# Tailscale pulls ~2 MB instead of a 60 MB wav (199 of 376 files are wav).
# Resolve is unaffected: it reads the ORIGINAL from P: directly, never over
# HTTP, so nothing downstream is degraded by a lossy preview.
#
# Named by TRACK ID, not by rel_path -- b-roll's `proxies/{id}.mp4` layout, and
# for the same reason: a rename in the library changes rel_path but not the id,
# so the proxy survives it. That also means there is deliberately NO database
# column for the proxy; existence on disk is the whole record, which keeps the
# generator crash-safe (nothing to roll back) and the reader trivial.
PROXY_KBPS = int(os.environ.get('MUSIC_PROXY_KBPS', '128'))
PROXY_EXT = '.mp3'
PROXIES_DIR = Path(os.environ.get('MUSIC_PROXIES_DIR') or DATA_ROOT / 'proxies')


def proxy_path(track_id):
    """Where this track's preview proxy would live. May not exist.

    int() is not decoration: this builds a filesystem path, and a track id that
    reached here as a string from anywhere other than the router's `int` type
    hint must never be able to contribute a path separator.
    """
    return PROXIES_DIR / f'{int(track_id)}{PROXY_EXT}'

# The Resolve half lives in the companion now (port step 8, 2026-08-10):
# ccsync_companion/music_worker.py and music_server.py, reached by the BROWSER
# on 127.0.0.1:8899. Nothing here talks to Resolve, and nothing here should --
# this process runs on the NAS, where 127.0.0.1 is the NAS.

# The indexer is deliberately NOT part of the web deployment: it needs a GPU,
# ffmpeg, and the library on a local mount, none of which the NAS container
# has. Only two routes touch it (drag-and-drop ingest, and the on-demand
# waveform fallback) and both import it through add_indexer_to_path() so a
# web-only checkout answers them with a clear error instead of failing to
# start. Port step 7 replaces ingest with a queued handoff to the base rig.
INDEXER_DIR = Path(os.environ.get('MUSIC_INDEXER_DIR', MUSIC_DIR / 'indexer'))

HOST = os.environ.get('MUSIC_HOST') or os.environ.get('HOST', '127.0.0.1')
PORT = int(os.environ.get('MUSIC_PORT') or os.environ.get('PORT', '8790'))


def ensure_data_root():
    """Create DATA_ROOT. Called from startup, deliberately NOT at import.

    Doing this at module scope made an unwritable data root fail during
    `import musicweb.main`, which the dashboard mount reports as ABSENT --
    "the music tree was never shipped" -- when the truth is DEGRADED, "the
    tree is here and its data root is not usable by this container's uid".
    Those are different operator problems and the mount is built to tell them
    apart, so the import must not be the thing that fails.
    """
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return DATA_ROOT


def ensure_proxies_dir():
    """Create PROXIES_DIR. Called by the generator, deliberately NOT at import.

    Same rule as ensure_data_root() above, and the same failure it avoids: a
    mkdir at module scope turns an unwritable data root into an ImportError,
    which the dashboard mount reports as ABSENT ("the music tree was never
    shipped") when the truth is DEGRADED ("the tree is here, its data root is
    not usable by this container's uid").

    The reader never calls this. Serving is a pure existence check
    (`proxy_path(id).is_file()`), so a host with no proxies dir at all just
    falls back to the originals rather than failing.
    """
    PROXIES_DIR.mkdir(parents=True, exist_ok=True)
    return PROXIES_DIR


def add_indexer_to_path():
    """Put music/indexer on sys.path. -> True if it is checked out here."""
    if not INDEXER_DIR.is_dir():
        return False
    if str(INDEXER_DIR) not in sys.path:
        sys.path.insert(0, str(INDEXER_DIR))
    return True


# ---------------------------------------------------------------- facet order
# /api/facets returns categories as JSON keys and the frontend renders them in
# key order, so the order is load-bearing. It used to come from vocab.py, but
# vocab.py is the indexer's tuning surface and is not shipped with the web
# tree -- so the membership comes from the database and only the ORDER lives
# here. Anything the indexer grows that is not listed is appended
# alphabetically rather than dropped.
CATEGORY_ORDER = ['genre', 'mood', 'instrument', 'use_case', 'texture']
AXIS_ORDER = ['arousal', 'valence', 'tension', 'organic']


# ------------------------------------------------------- (share, rel_path)
# b-roll's load-bearing rule is that the database never stores absolute paths:
# every asset is (share, rel_path), translated to a real path at the edge.
# That is what lets the library move, or be mounted at a different letter per
# host, without invalidating a 376-row index.
#
# The validation below mirrors ccsync_companion/broll_server.py's
# _split_components/_validate_components deliberately -- the two now translate
# the same kind of pair, and a rule enforced in one and not the other is how a
# traversal gets served. Anything that would escape the share root raises;
# nothing here silently returns a path outside it.
SHARE_ROOTS = {SHARE: MUSIC_ROOT}

_DRIVE_RE = re.compile(r'^[A-Za-z]:')


class UnknownShareError(ValueError):
    """Raised when a share has no root on this host."""


class PathTraversalError(ValueError):
    """Raised when rel_path is not relative, or tries to escape the root."""


def share_root(share=SHARE):
    """Local root for a share name.

    Reads SHARE_ROOTS at call time rather than closing over it, so a host (or
    a test) can repoint a share without re-importing the package.
    """
    try:
        return SHARE_ROOTS[share]
    except KeyError:
        raise UnknownShareError(f'no root configured for share {share!r}') from None


def _split_components(rel_path):
    # rel_path is documented as forward-slash relative; a stray backslash from
    # something that used native separators is treated as the same boundary.
    return [p for p in rel_path.replace('\\', '/').split('/') if p not in ('', '.')]


def _validate_components(parts):
    for part in parts:
        if part == '..':
            raise PathTraversalError("path traversal rejected: '..' in rel_path")
        # Defence in depth: a drive letter smuggled in as a segment ("C:") is
        # not a directory name, and Path.joinpath would re-anchor on it.
        if part.endswith(':'):
            raise PathTraversalError(f'invalid path segment {part!r} in rel_path')


def safe_join(root, rel_path):
    """root / rel_path, or raise. `root` is explicit for the indexer's --root."""
    if not rel_path or not str(rel_path).strip():
        raise PathTraversalError('empty rel_path')
    norm = str(rel_path).replace('\\', '/')
    # An absolute rel_path is a contradiction, and joinpath would honour it and
    # hand back a path with nothing to do with the share.
    if norm.startswith('/') or _DRIVE_RE.match(norm):
        raise PathTraversalError(f'rel_path must be relative, got {rel_path!r}')

    parts = _split_components(norm)
    _validate_components(parts)
    if not parts:
        raise PathTraversalError('empty rel_path after normalisation')

    root = Path(root)
    path = root.joinpath(*parts)
    # Last line of defence: a symlink or a component the checks above did not
    # anticipate must not land outside the root. strict=False, because the
    # caller is often asking about a file that is legitimately missing.
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        raise PathTraversalError(
            f'rel_path escapes the share root: {rel_path!r}') from None
    return path


def resolve_path(share, rel_path):
    """(share, rel_path) -> an absolute path under this host's share root."""
    return safe_join(share_root(share), rel_path)
