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
from pathlib import Path, PureWindowsPath

PKG_DIR = Path(__file__).resolve().parent        # music/web/musicweb
WEB_DIR = PKG_DIR.parent                         # music/web
MUSIC_DIR = WEB_DIR.parent                       # music/

STATIC_DIR = WEB_DIR / 'static'
SCHEMA_PATH = WEB_DIR / 'schema.sql'
MIGRATIONS_DIR = WEB_DIR / 'migrations'

# ---------------------------------------------------------------- share roots
# The one share this library has, and where it is mounted per host.
#
# Its place INSIDE the tree is fixed by the product: <tree>/Assets/Music, the
# same leaf the companion, the dashboard and the b-roll archive agree on. WHERE
# THE TREE IS is a per-site fact -- on an editor machine it is the canonical
# prefix (P:\ by fleet decision, CLAUDE.md: "a configurable drive letter is
# explicitly deferred"), and an indexing host that maps the NAS share somewhere
# else says so with MUSIC_LIBRARY_ROOT.
#
# Until 2026-08-17 this file hardcoded ONE studio's indexing mount --
# W:\Creators_Club\Assets\Music -- and PROBED for it, so a second customer's
# base rig would have silently fallen through to the editor path
# (docs/COMMERCIAL_READINESS.md item 11). There is no literal drive or tree
# name left here.
SHARE = 'music'
LIBRARY_REL = Path('Assets') / 'Music'
CANONICAL_PREFIX = os.environ.get('CCSYNC_CANONICAL_PREFIX', '').strip() or 'P:\\'
# "P:", "P:\", "P:/" -- a bare drive root, mirroring
# ccsync_companion/canon.py's is_drive_style() (that module is the canon for
# this rule; it is not importable from here, the web app ships without the
# companion checked out, so the regex is duplicated rather than shared).
_DRIVE_STYLE_RE = re.compile(r'^[A-Za-z]:[\\/]?$')


def _join_canonical(prefix, rel):
    """prefix / rel, joined in the PREFIX's own spelling -- never the host's.

    pathlib.Path is native-flavoured: on a POSIX host (the dashboard
    container in production) `Path('P:\\')` does not split on backslash, so
    joining it against Assets/Music produced the corrupted
    'P:\\/Assets/Music' instead of 'P:\\Assets\\Music' -- every site whose
    canonical_prefix is a drive letter got a broken editor-facing path
    the moment this ran somewhere other than Windows.

    canon.py calls a drive-spelled canonical string exactly this: "a
    fleet-portable STRING in WINDOWS spelling that must never be handed to
    the local filesystem" on a host it isn't native to. So a drive-style
    prefix is always joined with PureWindowsPath when the host isn't Windows
    -- which also means the result is symbolic there (no .mkdir()/.exists()),
    correctly so: there is no real P:\\ to operate on outside Windows either
    way. A POSIX-shaped prefix (a Mac base rig's /Volumes/... mount) and a
    drive-style prefix running on the Windows host it is actually native to
    both keep plain pathlib.Path, which already joins them correctly and
    stays a real, operable path.
    """
    if _DRIVE_STYLE_RE.match(str(prefix).strip()) and os.name != 'nt':
        return PureWindowsPath(prefix) / rel
    return Path(prefix) / rel


EDITOR_ROOT = _join_canonical(CANONICAL_PREFIX, LIBRARY_REL)


def _default_share_root():
    """Where this host has the library: env, else the editor mount.

    MUSIC_LIBRARY_ROOT is the name to use. MUSIC_SHARE_ROOT and MUSIC_ROOT are
    accepted for the deployments and docs that already set them (MUSIC_ROOT
    predates the share model, DEPLOY.md documents it, and the tests point it
    at a temp directory).

    An INDEXING host -- the machine with the GPU, which maps the NAS share on
    its own letter -- must set one of them. It used to be guessed from the
    existence of a specific drive, which is only ever right for one fleet.
    """
    env = (os.environ.get('MUSIC_LIBRARY_ROOT')
           or os.environ.get('MUSIC_SHARE_ROOT')
           or os.environ.get('MUSIC_ROOT'))
    if env:
        return Path(env)
    return EDITOR_ROOT


MUSIC_ROOT = _default_share_root()

# MUSIC_-prefixed, because this app is mounted INSIDE the dashboard container
# and shares its environment with b-roll (which namespaces everything as
# BROLL_*) and with run.sh. A bare DATA_ROOT there is a name collision waiting
# to happen. The unprefixed name stays as a fallback: it predates the mount and
# is what the dashboard's test conftest pins.
DATA_ROOT = Path(os.environ.get('MUSIC_DATA_ROOT')
                 or os.environ.get('DATA_ROOT')
                 or WEB_DIR / 'data')
# MUSIC_DB_PATH names the file directly, for the case DATA_ROOT cannot express:
# a base rig draining a copy pulled down from the NAS, whose proxies and staging
# still belong under the local data root (2026-08-17, COMMERCIAL_READINESS.md
# item 14 -- the indexer's require_db_path() refuses to guess when neither this
# nor --db is set).
DB_PATH = Path(os.environ.get('MUSIC_DB_PATH') or DATA_ROOT / 'music.db')

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


def drop_proxy(track_id):
    """Delete the proxy sitting at `track_id`, if any. -> True if one went.

    THE ID IS REUSED (music-4, 2026-08-21). `tracks.id` is INTEGER PRIMARY KEY
    without AUTOINCREMENT, so SQLite hands a new insert max(rowid)+1: delete
    the highest row and the next track created takes its id -- and, because the
    proxy is chosen on existence alone, its 128k mp3 as well. Every editor
    previewing the new cue then heard the deleted one, with the right waveform
    and the right tags beside it, while `?original=1` and Resolve both played
    the right file. music_index/proxies.py has documented the hazard since the
    generator was written; the only broom was a manual base-rig --prune, and
    nothing at all swept the NAS's own /music-proxies -- which is where rows
    have been created since dashboard ingest landed (2026-08-18).

    So every path that FREES an id or CREATES a row at one drops the file with
    it. Best-effort by design: a proxy is a cache, and failing to remove one
    must never fail the write it belongs to.
    """
    try:
        path = proxy_path(track_id)
    except (TypeError, ValueError):
        return False
    try:
        path.unlink()
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        # A read-only proxies mount, or a Windows share holding the file open.
        # The reader's fallback is the original, so the worst case is bandwidth.
        return False

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

# ------------------------------------------------------- ingest credentials
# Who is allowed to write into the library, and it depends entirely on WHERE
# this app is running (COMMERCIAL_READINESS.md item 15, 2026-08-17):
#
#   mounted in the dashboard  the SPA drags-and-drops from a logged-in browser
#                             and the dashboard's login_gate has already run --
#                             the session IS the credential, and demanding a
#                             header the page cannot send would break ingest
#                             for the whole fleet.
#   standalone (uvicorn)      there is NO login in front of this app at all, so
#                             an open /api/ingest is "anyone who can reach the
#                             port can write files into the library and run
#                             ffmpeg on them". A token is REQUIRED, and an
#                             unset one closes the route rather than opening it
#                             (503) -- the same fail-closed rule b-roll's
#                             routes_ingest.py now follows.
#
# `set_login_gated(True)` is called by the dashboard's mount (music.py). It is
# NOT inferred from the environment: a host that merely has the variable set is
# not the same as a process that actually has the middleware wrapped around it.
_LOGIN_GATED = os.environ.get('MUSIC_LOGIN_GATED', '') == '1'


def set_login_gated(value=True):
    """Declare that a login gate wraps this app (the dashboard mount does)."""
    global _LOGIN_GATED
    _LOGIN_GATED = bool(value)


def login_gated():
    return _LOGIN_GATED


def ingest_token():
    """MUSIC_INGEST_TOKEN, or None. Read live so tests can set it per-test."""
    token = (os.environ.get('MUSIC_INGEST_TOKEN') or '').strip()
    return token or None


# ------------------------------------------------------- fleet ingest (2026-08-18)
# The OTHER ingest door (docs/MUSIC_INGEST_PLAN.md step 2): an editor's
# companion embeds a dropped track with the exported CLAP audio tower and
# reports the result under the fleet credentials the whole fleet already holds.
# No browser is involved, so the session cannot be the credential and these are
# read from the environment the dashboard container already sets.


def fleet_token():
    """DASH_REPORT_TOKEN, or None when it is unset.

    The shared secret every companion in the fleet already holds. FAIL-CLOSED
    (fleet_auth.require_fleet_token): None means every /api/fleet/ingest call
    is refused, because the alternative -- an unauthenticated route that writes
    `tracks` rows and re-scores the library -- is not a dev convenience, it is
    the whole write path.

    It is NOT an identity: every machine has the same one, so it proves "a
    fleet machine" and nothing about WHICH (H5, COMMERCIAL_READINESS.md item
    7). See fleet_auth.require_identity for the half that does.

    Read live, not bound at import, so a container restart with a rotated
    secret needs no code change.
    """
    token = (os.environ.get('DASH_REPORT_TOKEN') or '').strip()
    return token or None


def session_secret():
    """DASH_SESSION_SECRET, or None when it is unset.

    The key the dashboard signs its identity tokens with. Shared with the
    dashboard by ENVIRONMENT rather than by import: this app is deployed as its
    own tree and cannot see ccsync_dashboard.
    """
    secret = (os.environ.get('DASH_SESSION_SECRET') or '').strip()
    return secret or None


# How long a claim is good for, and how often the companion must say it is
# still alive. The ytdl and b-roll fleet routes' 300/30, because the failure
# they cover is identical: a machine switched off mid-batch has to release its
# lease without anyone pressing anything, and 10 missed heartbeats is a
# comfortable margin over a laptop lid closing for a minute.
LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 30

# A drop is a drag of files, not a library import. Well above the biggest
# observed drop (an 18-track album) and far below anything that would keep the
# single-worker container busy for minutes inside one request.
MAX_BATCH_ITEMS = 500

# Ceilings on one ingest request. The dashboard's body_size_gate only makes a
# DECLARATION check on /music/api/ingest (the multipart body is spooled past it
# on purpose -- buffering a dropped album is the memory problem that middleware
# exists to prevent), so nothing counted the files themselves: a single request
# could carry ten thousand parts, each one costing a staging write, an ffprobe
# and two library hashes on the single-worker container ("music ingest
# unbounded", COMMERCIAL_READINESS.md §C M-tier). Both are far above a real
# drag-and-drop -- the biggest observed drop is an 18-track album.
MAX_INGEST_FILES = 64
MAX_INGEST_TOTAL_BYTES = 512 * 1024 * 1024      # = the dashboard's declared ceiling
MAX_INGEST_FILE_BYTES = 512 * 1024 * 1024


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
