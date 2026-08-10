"""Path translation: (share, rel_path) -> local absolute path.

Per SPEC.md, the DB never stores absolute paths — every video is identified
by a logical share name plus a forward-slash relative path. This module maps
that pair to wherever the share is actually mounted on THIS machine.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional


class MountNotConfiguredError(Exception):
    """Raised when a share has no configured (or, on macOS, probeable) mount."""


class PathTraversalError(Exception):
    """Raised when rel_path attempts to escape the mount root (any '..' part)."""


def _split_components(rel_path: str) -> list[str]:
    # rel_path is documented as forward-slash relative; also tolerate a stray
    # backslash from a client that used native separators by treating it the
    # same as a path component boundary.
    normalized = rel_path.replace("\\", "/")
    return [part for part in normalized.split("/") if part not in ("", ".")]


def _validate_components(parts: list[str]) -> None:
    for part in parts:
        if part == "..":
            raise PathTraversalError(
                f"path traversal rejected: '..' component in rel_path"
            )
        # Defense in depth: reject a drive letter or similar smuggled in as
        # a path segment (e.g. "C:" as one of the '/'-split parts).
        if part.endswith(":"):
            raise PathTraversalError(f"invalid path segment '{part}' in rel_path")


def probe_darwin_mount(
    share: str, isdir: Optional[Callable[[str], bool]] = None
) -> Optional[str]:
    """Look for /Volumes/<share>, -1, -2 (Finder's collision-suffix convention).

    Returns the first candidate that exists as a directory, or None.

    `isdir` defaults to None (resolved to os.path.isdir at call time, not at
    import time) so tests can either monkeypatch os.path.isdir directly or
    inject a fake callable explicitly.
    """
    check = isdir if isdir is not None else os.path.isdir
    for candidate in (f"/Volumes/{share}", f"/Volumes/{share}-1", f"/Volumes/{share}-2"):
        if check(candidate):
            return candidate
    return None


def translate_path(
    share: str,
    rel_path: str,
    mounts: dict,
    platform: Optional[str] = None,
    isdir: Optional[Callable[[str], bool]] = None,
) -> str:
    """Translate (share, rel_path) to a local absolute path string.

    `platform` defaults to the real sys.platform; it's injectable so tests
    can exercise both Windows-style and macOS-style joining/probing from a
    single host OS. The returned string uses the separator appropriate for
    that platform — actual filesystem calls (e.g. os.path.isfile) should
    only be made against the real host's translation (the default).

    Raises MountNotConfiguredError or PathTraversalError; never silently
    returns a path outside the configured/probed root.
    """
    plat = platform if platform is not None else sys.platform

    if not rel_path or not rel_path.strip():
        raise PathTraversalError("empty rel_path")

    parts = _split_components(rel_path)
    _validate_components(parts)
    if not parts:
        raise PathTraversalError("empty rel_path after normalization")

    root = mounts.get(share)
    if root is None and plat == "darwin":
        root = probe_darwin_mount(share, isdir=isdir)
    if root is None:
        raise MountNotConfiguredError(f"no mount configured for share '{share}'")

    if plat.startswith("win"):
        # Normalize the configured root's separators, then append components
        # with backslashes. Leaves drive letters ("Y:\...") intact.
        root_norm = root.replace("/", "\\").rstrip("\\")
        return root_norm + "\\" + "\\".join(parts)

    # macOS/posix: normalize to forward slashes, preserve a leading '/'.
    root_norm = root.replace("\\", "/").rstrip("/")
    if root_norm == "":
        root_norm = "/"
    return root_norm + "/" + "/".join(parts)
