"""Timeline-clip path classification for the watcher.

Per SPEC.md's watcher spec, every clip path found on the current timeline is
classified as one of:

  OK           — under local_root (case-insensitive on Windows).
  OUT_OF_TREE  — exists on disk but outside local_root -> popup candidate.
  BAD_PREFIX   — starts with the canonical shared prefix (e.g. "P:\\") AND
                 exists on disk (the mapping resolves to *something*) but
                 that something is not under local_root -> a genuinely
                 broken mapping (subst/mount pointing at the wrong target)
                 -> mapping-health warning (tray notification, not popup).
  MISSING      — doesn't exist on disk, and THE PREFIX ITSELF RESOLVES
                 correctly. This is the DESIGNED steady state on a remote
                 editor rig: lane A is upload-only, so a video original
                 legitimately lives only on the NAS and was never downloaded
                 here -- every clip Resolve has ever cut in renders this
                 way, on a perfectly healthy install. A canonical-prefix
                 path that simply isn't present locally is therefore NOT
                 treated as a mapping problem (that used to fire a tray
                 notification per distinct clip -- see AUDIT.md §5's
                 BAD_PREFIX-storm finding). Not in SPEC.md's three-way list
                 explicitly, but the watcher needs *some* answer for this
                 case rather than silently mis-filing it as OUT_OF_TREE
                 (which would trigger an unfixable popup for a file that's
                 simply gone/not yet synced).

The prefix, not the file, is what decides between MISSING and BAD_PREFIX
for a non-existent canonical-prefix path. Returning MISSING whenever the
file was absent -- regardless of whether the prefix resolved -- made the
mapping-health warning unreachable for its PRIMARY failure: `subst P:`
never ran at login, or the Mac Mapped Mount is unset. Every clip then
classified MISSING, so there were zero warnings and zero tray
notifications while every clip in the project was offline (AUDIT_2 L-15).
One realpath() on the prefix answers it; _prefix_resolves() caches that so
it costs one syscall per poll rather than one per clip.

Windows case-insensitivity and separator differences ('/' vs '\\') are
handled the same way resolve_bridge.py does it: os.path.normcase(os.path.
normpath(...)) — normcase folds case AND normalizes separators to '\\' on
Windows, and is a no-op beyond normpath on posix.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import threading
import time
from typing import Callable, Optional

OK = "OK"
OUT_OF_TREE = "OUT_OF_TREE"
BAD_PREFIX = "BAD_PREFIX"
MISSING = "MISSING"

# How long a prefix-resolution probe is reused. The watcher polls every 3s
# and a timeline can carry hundreds of clips, so this turns "one realpath()
# per clip" into "one realpath() per poll" while still noticing a `subst P:`
# that lands (or breaks) within a couple of seconds.
_PREFIX_CACHE_TTL_SECONDS = 2.0
_prefix_cache: dict[tuple, tuple[float, bool]] = {}
_prefix_cache_lock = threading.Lock()


def clear_prefix_cache() -> None:
    """Drop the memoised prefix probes. For tests, and for any caller that
    knows the mapping just changed."""
    with _prefix_cache_lock:
        _prefix_cache.clear()


def _norm(path: str, platform_module=os.path) -> str:
    return platform_module.normcase(platform_module.normpath(str(path)))


def _is_under(norm_path: str, norm_root: str, sep: str) -> bool:
    if not norm_root:
        return False
    if norm_path == norm_root:
        return True
    root_with_sep = norm_root if norm_root.endswith(sep) else norm_root + sep
    return norm_path.startswith(root_with_sep)


def _prefix_resolves_under_root(
    canonical_prefix: str,
    norm_root: str,
    plat,
    sep: str,
    resolve: Callable[[str], str],
) -> bool:
    """Does the canonical prefix itself (P:\\, /Volumes/CreatorsClub) resolve
    to somewhere under local_root? Cached for _PREFIX_CACHE_TTL_SECONDS."""
    key = (str(canonical_prefix), norm_root, sep, getattr(resolve, "__qualname__", repr(resolve)))
    now = time.monotonic()
    with _prefix_cache_lock:
        cached = _prefix_cache.get(key)
        if cached is not None and now - cached[0] < _PREFIX_CACHE_TTL_SECONDS:
            return cached[1]
    try:
        healthy = _is_under(_norm(resolve(canonical_prefix), plat), norm_root, sep)
    except Exception:
        # The probe itself failed (not "the mapping is wrong"). Don't cry
        # wolf: a raising realpath must never produce a warning per clip.
        healthy = True
    with _prefix_cache_lock:
        _prefix_cache[key] = (now, healthy)
    return healthy


def classify_path(
    path: str,
    local_root: str,
    canonical_prefix: str,
    exists_fn: Optional[Callable[[str], bool]] = None,
    is_windows: Optional[bool] = None,
    realpath_fn: Optional[Callable[[str], str]] = None,
) -> str:
    """Classify a single clip path. Never raises.

    `exists_fn` and `is_windows` are injectable for tests so both Windows-
    and posix-style paths can be exercised from either host OS. They default
    to os.path.exists and the real host platform.
    """
    windows = is_windows if is_windows is not None else (os.name == "nt")
    plat = ntpath if windows else posixpath
    check_exists = exists_fn if exists_fn is not None else os.path.exists

    if not path or not str(path).strip():
        return MISSING

    norm_path = _norm(path, plat)
    norm_root = _norm(local_root, plat) if local_root else ""
    sep = plat.sep

    if norm_root and _is_under(norm_path, norm_root, sep):
        return OK

    try:
        exists = bool(check_exists(path))
    except Exception:
        exists = False

    norm_prefix = _norm(canonical_prefix, plat) if canonical_prefix else ""
    if norm_prefix and norm_path.startswith(norm_prefix):
        resolve = realpath_fn if realpath_fn is not None else os.path.realpath
        # On a correctly-mapped machine (subst P: -> local_root) canonical-
        # prefix paths are the HEALTHY state: realpath resolves the subst
        # drive, landing under local_root -> OK.
        if not exists:
            if not norm_root:
                return MISSING
            # Probe the PREFIX, not the file. A prefix that resolves under
            # local_root means the mapping is fine and the file is simply
            # not downloaded -- the designed steady state on a remote editor
            # rig (see the module docstring). A prefix that does NOT resolve
            # there is the mapping failure SPEC component 2 requires a
            # warning for, and it is by far the most common one: `subst P:`
            # didn't run at login (AUDIT_2 L-15).
            if _prefix_resolves_under_root(canonical_prefix, norm_root, plat, sep, resolve):
                return MISSING
            return BAD_PREFIX
        if norm_root:
            try:
                real = _norm(resolve(path), plat)
            except Exception:
                real = norm_path
            if _is_under(real, norm_root, sep):
                return OK
        # Exists (the mapping resolves to something real) but not under
        # local_root -- a genuinely broken mapping (wrong subst/mount
        # target, or local_root isn't configured at all) -> warn.
        return BAD_PREFIX

    if exists:
        return OUT_OF_TREE

    return MISSING
