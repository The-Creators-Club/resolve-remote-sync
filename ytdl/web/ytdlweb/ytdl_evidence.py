"""Evidence of whether YouTube downloads actually WORK, per path.

docs/YTDL_RESILIENCE_PLAN.md WP5 (2026-08-26). `/ytdl/api/health` used to
answer `cookies: bool(config.COOKIES_FILE)` -- a configuration echo that stayed
green through CR-80 while every download failed. What this module holds is the
outcome of the last real attempt on each path (anonymous / cookies), recorded
by the worker as it goes, so health can report evidence instead of settings.

Interface contract (shared by worker.py, routes_api.py and the canary):

    record(path, ok, error=None, video_id=None, source='download')
    snapshot() -> {path: {'ok', 'error', 'at', 'video_id', 'source'}}

`path` is PATH_ANONYMOUS or PATH_COOKIES. Never raises: a bookkeeping failure
must not fail a download.

The snapshot is also mirrored to <DATA_ROOT>/ytdl_evidence.json, because the
dashboard container restarts for reasons that have nothing to do with YouTube
(an image update, a compose edit, the nightly), and evidence that blanks on
every restart is evidence an operator cannot trust the absence of: a blank
health pip would mean "nothing tried yet" and "restarted since the last
attempt" indistinguishably. Best effort in both directions -- an unwritable
data root costs the persistence, never the download.
"""
import copy
import json
import logging
import os
import threading
import time
from pathlib import Path

from ytdlweb import config

log = logging.getLogger(__name__)

PATH_ANONYMOUS = 'anonymous'
PATH_COOKIES = 'cookies'
PATHS = (PATH_ANONYMOUS, PATH_COOKIES)

# The file name lives beside ytdl.db in the app's own data root -- the one tree
# this app owns and the only one guaranteed writable by uid 3000.
STATE_FILENAME = 'ytdl_evidence.json'

_lock = threading.Lock()
_last = {}
_loaded = False


def _state_path():
    """Where the mirror lives. A function, not a constant, so tests can point
    it at a tmp tree and so a DATA_ROOT rebound after import is honoured."""
    return Path(config.DATA_ROOT) / STATE_FILENAME


def _save_locked():
    """Write the mirror. CALLER HOLDS `_lock`. Never raises.

    Atomic rename via a sibling temp file: health reads this on a cold start,
    and a torn write would be a JSON error at exactly the moment somebody is
    trying to find out why downloads stopped. Same-directory temp, because
    os.replace is only atomic within a filesystem.
    """
    path = _state_path()
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(_last, indent=1, sort_keys=True),
                       encoding='utf-8')
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 - persistence is a nicety
        log.debug('ytdl evidence not persisted (%s: %s)', type(exc).__name__, exc)
        try:
            tmp.unlink()
        except OSError:
            pass


def _load_locked():
    """Read the mirror once, on first use. CALLER HOLDS `_lock`. Never raises.

    LAZY, not at import: config.DATA_ROOT may not exist yet when this module is
    first imported (ensure_data_root() runs at startup/mount, deliberately not
    at import -- see config.ensure_data_root), and an import that touched the
    disk would turn an unwritable data root into an ImportError the mount
    reports as ABSENT.

    In-memory always wins: anything already recorded in this process is newer
    than the file by construction, so a load can only fill gaps.
    """
    global _loaded
    _loaded = True
    try:
        raw = json.loads(_state_path().read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - absent, empty, or garbage all mean "no evidence"
        return
    if not isinstance(raw, dict):
        return
    for key, val in raw.items():
        if key in _last or not isinstance(val, dict):
            continue
        _last[str(key)] = {
            'ok': bool(val.get('ok')),
            'error': str(val.get('error') or '')[:300],
            'at': float(val.get('at') or 0),
            'video_id': str(val.get('video_id') or ''),
            'source': str(val.get('source') or 'download'),
        }


def record(path, ok, error=None, video_id=None, source='download'):
    """The outcome of one real attempt on `path`. Never raises."""
    try:
        with _lock:
            if not _loaded:
                _load_locked()
            _last[str(path)] = {
                'ok': bool(ok),
                'error': (str(error)[:300] if error else ''),
                'at': time.time(),
                'video_id': str(video_id or ''),
                'source': str(source or 'download'),
            }
            _save_locked()
    except Exception:  # noqa: BLE001 - bookkeeping must never fail a download
        pass


def snapshot():
    """A copy of the last outcome per path. {} before any attempt.

    Never raises: this is on the /api/health request path, and health that
    500s is worse than health that says nothing.
    """
    try:
        with _lock:
            if not _loaded:
                _load_locked()
            return copy.deepcopy(_last)
    except Exception:  # noqa: BLE001
        return {}


def reset():
    """Tests only. Forgets the evidence in memory AND the on-disk mirror.

    Both, because "cleared" has to mean cleared: leaving the file behind (or
    leaving _loaded False) would let the next snapshot() re-read the very
    evidence the test just discarded, and the failure would land in whichever
    test ran after it.
    """
    global _loaded
    with _lock:
        _last.clear()
        _loaded = True
        try:
            _state_path().unlink()
        except OSError:
            pass
        except Exception:  # noqa: BLE001
            pass


JAR_NONE = 'none'          # no YTDL_COOKIES_FILE, or the path does not exist
JAR_EMPTY = 'empty'        # the file holds only comments / header lines (CR-80's parked state)
JAR_PRESENT = 'present'    # at least one cookie line


def cookie_jar_state(path):
    """What the configured cookies.txt actually holds. Never raises.

    CR-80 (2026-08-26) parked the NAS's flagged jar as its two Netscape header
    lines with YTDL_COOKIES_FILE still set, so "a path is configured" says
    nothing about whether there is a session to try. A header-only jar is
    JAR_EMPTY and the cookies path is simply not attempted.
    """
    try:
        if not path:
            return JAR_NONE
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    return JAR_PRESENT
        return JAR_EMPTY
    except OSError:
        return JAR_NONE
    except Exception:  # noqa: BLE001
        return JAR_NONE
