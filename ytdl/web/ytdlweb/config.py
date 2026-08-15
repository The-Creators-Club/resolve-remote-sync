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
import logging
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

# The candidate ceilings the editor may pick between, and what a search gets
# when it names none. NOT env-overridable on purpose: the same four numbers are
# the SPA's dropdown and the API's allow-list, and migration 006's column
# default is DEFAULT_MAX_CANDIDATES written out in SQL -- a per-container
# override would let a job be created with a cap no other layer accepts.
# (tests/test_db.py and tests/test_static_app.py pin all three together.)
#
# 100 is reasoned, not round. On 2026-08-11 one search expanded to 24 terms ->
# 336 candidates and YouTube began refusing the NAS's IP outright partway
# through the metadata pass, at **112 metadata calls** -- the only measured
# point at which the fleet has ever been cut off. A default search therefore
# sits just under the one threshold in evidence, which also means it degrades
# safely: if the cookies expire or the PO-token sidecar hiccups, the requests
# drift back towards anonymous and the volume behind them is still under what
# an authenticated IP was blocked for. 400 stays on the menu for a genuinely
# thin topic, as a choice somebody made rather than something that happened.
CANDIDATE_CAPS = (50, 100, 200, 400)
DEFAULT_MAX_CANDIDATES = 100

# The longest video a SEARCH job will keep selected (admin request,
# 2026-08-14): b-roll harvesting wants clips, and an hour-long documentary is
# an hour of download + disk for footage nobody scrubs. A mechanical drop in
# the filter phase, same soft semantics as a Claude verdict -- the card stays
# in the manifest, deselected with a note, and an editor who genuinely wants
# it can re-tick it. Pasted-link jobs are untouched on purpose: they skip the
# filter phase entirely, and skipping a video someone deliberately pasted
# would contradict the paste.
MAX_DURATION_SECONDS = int(os.environ.get('YTDL_MAX_DURATION') or '1800')

# Metadata enrichment pacing. The enrich phase is the one that got the IP
# blocked: it ran through a ThreadPoolExecutor with 4 workers and NO delay, so
# 112 calls went out in well under a minute -- which is what looked robotic,
# cookies or no cookies (DEPLOY.md, "Volume is still the trigger").
#
#   YTDL_ENRICH_WORKERS  how many metadata fetches may be in flight at once.
#     2, not 4: enough to keep a slow extract_info from stalling the phase,
#     few enough that a burst of retries cannot fan out.
#   YTDL_ENRICH_PAUSE    seconds between REQUESTS across the whole pool (not
#     per worker -- ytsearch.enrich holds one gate, so the ceiling is 1/pause
#     requests a second whatever YouTube's latency does). 0.75 s = 80
#     requests/minute; the blocked burst was roughly three to six times that.
#     At the default 100-candidate cap it costs ~75 s of pacing, so the whole
#     enrich phase lands near where a 336-candidate unpaced one used to.
ENRICH_WORKERS = int(os.environ.get('YTDL_ENRICH_WORKERS') or '2')
ENRICH_PAUSE = float(os.environ.get('YTDL_ENRICH_PAUSE') or '0.75')

# Search pacing -- the hole the enrich pacing above left open, found the hard
# way (2026-08-11, second block of the same day). With enrichment paced and the
# candidate cap in force, a full search STILL bot-checked while a pasted link
# downloaded fine, because `_phase_search` fires one flat search per term
# back to back with no delay at all: ~24 requests, in a couple of seconds, to
# YouTube's SEARCH endpoint rather than the player API. One paste is one
# request, which is exactly why the URL box kept working.
#
# The worker's own docstring used to say "24 flat searches is not the volume in
# question". It was wrong; this is the evidence.
#
# 2 s, deliberately slower than ENRICH_PAUSE: search is the cheaper call to
# slow down (24 of them, not 100) and the more scrutinised endpoint. 24 terms
# costs ~48 s, on a phase that already waits on Claude for the term list.
SEARCH_PAUSE = float(os.environ.get('YTDL_SEARCH_PAUSE') or '2')

# Standalone dev only: who the API thinks you are when no dashboard gate has
# injected the header. Never set on a deployed host.
DEV_USER = os.environ.get('YTDL_DEV_USER') or ''

# Standalone dev only: 'slug=label,slug2=label2' so the project picker has
# something to offer with no dashboard database in reach.
DEV_PROJECTS = os.environ.get('YTDL_DEV_PROJECTS') or ''

# ------------------------------------------- requester-first downloads (0.8.0)
# docs/YTDL_LOCAL_DOWNLOAD.md. The requester's own companion downloads their
# clips from their residential IP, and the NAS worker becomes the fallback
# executor. Phase 1 (this) is the server half; with no 0.8.0 companion in the
# fleet, nothing here ever fires.

# The SPA's dispatch switch, and the ONLY switch this feature has (plan §10).
# Default OFF: deployed with the flag down, the behaviour is byte-for-byte
# today's, which is what makes phase 1 safe to soak on the live dashboard.
# It gates the browser probe, not the endpoints below -- the fleet token is
# what guards those, and a companion can only act on a job id the SPA gave it.
LOCAL_DOWNLOAD = (os.environ.get('YTDL_LOCAL_DOWNLOAD') or '') == '1'

# How long a claim is good for, and how often the holder must say it is alive.
# 180/30 ship as the plan's numbers: three heartbeats' worth of slack, so one
# missed beat (a suspended laptop, a busy tray) does not cost the lease, and a
# genuinely dead holder is reclaimed in at most three minutes.
LEASE_SECONDS = int(os.environ.get('YTDL_LEASE_SECONDS') or '180')
HEARTBEAT_SECONDS = int(os.environ.get('YTDL_HEARTBEAT_SECONDS') or '30')

# The oldest yt-dlp an editor's machine may download with. yt-dlp rots -- the
# container's copy is fixable in one rebuild, and this is the equivalent lever
# for the fleet: raise it the day YouTube breaks the old one and every stale
# companion is refused its claim (403) and falls back to the server while its
# sidecar self-updates (plan §6).
#
# RANKED NUMERICALLY, not compared as a string (COMP-BROLL-9, 2026-08-14). The
# string rule is exact for yt-dlp's OWN output, whose fields are zero-padded --
# and this value is not yt-dlp's output, it is free text an operator types into
# the container's environment. One unpadded floor ('2026.8.5') sorts ABOVE
# every real '2026.08.xx' and even '2026.12.xx', so it 403s the claim of every
# machine in the fleet while each companion (which ranks numerically) concludes
# it has nothing to update: local downloads dead everywhere, and the only log
# line anywhere says somebody's yt-dlp is old. The companion now says so out
# loud when the two sides disagree; this is the side that stops it happening.
DEFAULT_MIN_YTDLP_VERSION = '2026.07.04'
MIN_YTDLP_VERSION = os.environ.get('YTDL_MIN_YTDLP_VERSION') or DEFAULT_MIN_YTDLP_VERSION

_VERSION_PART = re.compile(r'^\d+$')


def version_rank(version):
    """A dotted-numeric version as a tuple of ints, or None if it is not one.

    '2026.8.4' -> (2026, 8, 4), and (2026, 8, 4) < (2026, 8, 10) the way the
    releases actually went out. A nightly's '2026.07.04.123456' ranks after the
    release it follows, because a longer tuple with an equal prefix is greater.

    None -- deliberately strict -- for anything that is not all-numeric
    ('nightly', '2026.08.04-hotfix', ''). Truncating to the numeric prefix
    would rank a hotfix BELOW the release it patches, and the two callers of
    this both have a safe answer for "cannot rank" already. Never raises.

    Mirrors ccsync_companion.upgrade.parse_version, which is what the other end
    of this comparison uses; it is not imported because this app must run with
    no companion source in reach.
    """
    try:
        raw = str(version or '').strip()
        if raw[:1] in ('v', 'V'):
            raw = raw[1:]
        parts = raw.split('.')
        if not raw or not all(_VERSION_PART.match(p) for p in parts):
            return None
        return tuple(int(p) for p in parts)
    except Exception:                            # noqa: BLE001 - never raises
        return None


def _validated_floor(configured):
    """The fleet's yt-dlp floor, or the shipped default if it cannot be ranked.

    A floor nothing can rank is worse than no floor at all: it cannot let
    anybody through, so it silently turns every editor's downloads back to the
    server and looks exactly like "the whole fleet is running old yt-dlp". A
    typo in one env var must not be able to do that quietly, so the bad value
    is REFUSED (never used for a comparison, never published to the fleet by
    /api/config/ytdl-client) and the reason is logged at ERROR -- which is
    where an operator looks when local downloads stop happening.
    """
    if version_rank(configured) is not None:
        return str(configured).strip()
    logging.getLogger(__name__).error(
        'YTDL_MIN_YTDLP_VERSION=%r is not a dotted-numeric version, so nothing '
        'can be compared against it. Falling back to %s. Until it is fixed, '
        'the floor in force is the shipped one, NOT the value in the '
        'environment.', configured, DEFAULT_MIN_YTDLP_VERSION)
    return DEFAULT_MIN_YTDLP_VERSION


MIN_YTDLP_VERSION = _validated_floor(MIN_YTDLP_VERSION)

# The fleet token the companion already holds, deliberately NOT YTDL_-prefixed:
# it is the DASHBOARD's shared secret (`DASH_REPORT_TOKEN`), the same one the
# companion authenticates its status reports and package downloads with, and a
# second name for it would mean a second thing to rotate. Machine-to-machine
# only -- the browser session authorises humans, this authorises companions,
# and neither crosses into the other's lane (plan §8).
#
# FAIL CLOSED: unset means every fleet endpoint answers 403, never "open".
# The b-roll ingest gate's precedent, and the same reasoning -- a dashboard
# deployed without the secret must refuse machine callers, not trust them.
REPORT_TOKEN = os.environ.get('DASH_REPORT_TOKEN') or ''

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

# The MS-DOS device names Windows still reserves. A folder called `con` is
# created happily on the NAS (POSIX) and then gives every Windows editor a
# permanent per-item sync error on that project (YTDL-28, 2026-08-11) -- the
# reservation applies to the stem, before any dot, and is case-insensitive.
_RESERVED_NAMES = frozenset(
    {'CON', 'PRN', 'AUX', 'NUL'}
    | {f'COM{i}' for i in range(1, 10)}
    | {f'LPT{i}' for i in range(1, 10)})


def safe_term_dirname(term, fallback='search'):
    """A search term reduced to a directory name that survives NAS -> SMB.

    Three separate constraints, none of them optional:
      - traversal: no separators, no '..', no drive letters (safe_join
        re-validates, but a term that reached it as '../..' would 500 rather
        than just being filed oddly);
      - Windows: <>:"/\\|?* are illegal in a name, a trailing dot or space
        makes a directory Explorer cannot delete, and a reserved DEVICE name
        (CON, NUL, COM1...) is refused outright -- the NAS creates it happily
        and every Windows editor then carries a per-item sync error for that
        project until someone renames it there (YTDL-28, 2026-08-11);
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
    if not s:
        return fallback
    # The reservation is on the stem before the first dot ('nul.txt' is as
    # reserved as 'nul'), so the suffix goes there and not on the end.
    stem = s.split('.', 1)[0]
    if stem.upper() in _RESERVED_NAMES:
        s = stem + '_' + s[len(stem):]
    return s
