"""Timeline-clip path classification for the watcher.

Per SPEC.md's watcher spec, every clip path found on the current timeline is
classified as one of:

  OK           — under local_root (case-insensitive on Windows).
  OUT_OF_TREE  — exists on disk but outside local_root -> popup candidate.
  BAD_PREFIX   — starts with the canonical shared prefix (e.g. "P:\\") but
                 does not resolve to somewhere under local_root -> mapping-
                 health warning (tray notification, not popup).
  MISSING      — doesn't exist on disk and isn't under local_root or the
                 canonical prefix either (e.g. a truly offline/deleted
                 source). Not in SPEC.md's three-way list explicitly, but
                 the watcher needs *some* answer for this case rather than
                 silently mis-filing it as OUT_OF_TREE (which would trigger
                 an unfixable popup for a file that's simply gone).

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
        # drive, landing under local_root -> OK. A canonical path that
        # doesn't exist, or that resolves somewhere OTHER than local_root
        # (P: mapped to the wrong target), is a broken mapping -> warning.
        if exists and norm_root:
            resolve = realpath_fn if realpath_fn is not None else os.path.realpath
            try:
                real = _norm(resolve(path), plat)
            except Exception:
                real = norm_path
            if _is_under(real, norm_root, sep):
                return OK
        return BAD_PREFIX

    if exists:
        return OUT_OF_TREE

    return MISSING
