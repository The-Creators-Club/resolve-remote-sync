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
  MISSING      — doesn't exist on disk, whether or not it's under the
                 canonical prefix. This is the DESIGNED steady state on a
                 remote editor rig: lane A is upload-only, so a video
                 original legitimately lives only on the NAS and was never
                 downloaded here -- every clip Resolve has ever cut in
                 renders this way, on a perfectly healthy install. A
                 canonical-prefix path that simply isn't present locally is
                 therefore NOT treated as a mapping problem (that used to
                 fire a tray notification per distinct clip -- see
                 AUDIT.md §5's BAD_PREFIX-storm finding); only a path that
                 resolves to somewhere real but wrong (above) does. Not in
                 SPEC.md's three-way list explicitly, but the watcher needs
                 *some* answer for this case rather than silently mis-filing
                 it as OUT_OF_TREE (which would trigger an unfixable popup
                 for a file that's simply gone/not yet synced).

Windows case-insensitivity and separator differences ('/' vs '\\') are
handled the same way resolve_bridge.py does it: os.path.normcase(os.path.
normpath(...)) — normcase folds case AND normalizes separators to '\\' on
Windows, and is a no-op beyond normpath on posix.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
from typing import Callable, Optional

OK = "OK"
OUT_OF_TREE = "OUT_OF_TREE"
BAD_PREFIX = "BAD_PREFIX"
MISSING = "MISSING"


def _norm(path: str, platform_module=os.path) -> str:
    return platform_module.normcase(platform_module.normpath(str(path)))


def _is_under(norm_path: str, norm_root: str, sep: str) -> bool:
    if not norm_root:
        return False
    if norm_path == norm_root:
        return True
    root_with_sep = norm_root if norm_root.endswith(sep) else norm_root + sep
    return norm_path.startswith(root_with_sep)


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
        # On a correctly-mapped machine (subst P: -> local_root) canonical-
        # prefix paths are the HEALTHY state: realpath resolves the subst
        # drive, landing under local_root -> OK.
        if not exists:
            # DESIGNED steady state on a remote editor rig (see the module
            # docstring): the prefix itself is fine -- there's simply
            # nothing local to check yet (lane A never downloads
            # originals). This is deliberately indistinguishable from a
            # genuinely unmapped P: drive (both fail exists()) -- that
            # ambiguity is the tradeoff for not raising a mapping-health
            # notification per not-yet-synced clip. A mapping that resolves
            # to the WRONG target (below) is still caught, because that
            # case is only detectable once something actually exists there.
            return MISSING
        if norm_root:
            resolve = realpath_fn if realpath_fn is not None else os.path.realpath
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
