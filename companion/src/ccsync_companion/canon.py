"""Canonical-vs-local path spelling — the one place that knows the rules.

Fleet path canon is `P:\\` (SPEC's path canon): every Resolve project database
in the fleet stores `P:\\Projects\\...` strings, because that is the ONLY
spelling that resolves on every machine. A Windows editor gets there with a
real drive (subst / a loopback share); a macOS editor has no drive namespace
at all and gets there via Resolve's own "Mapped Mount" preference, with the
tree physically at local_root (e.g. /Volumes/T7/Creators_Club).

So on macOS a canonical path is a fleet-portable STRING in WINDOWS spelling
that must never be handed to the local filesystem:

  * compare/split it with ntpath, whatever the host is -- posixpath.normcase
    is a no-op, so `P:\\Projects\\x` and `p:/projects/x` would not compare
    equal and `dirname` would answer the whole string;
  * translate it to local_root/... for any existence probe
    (canonical_to_local);
  * write it back to Resolve in canonical spelling, backslashes and all
    (local_to_canonical) -- a `P:\\Projects/2026/x.braw` emitted by joining
    with the host separator travels to the rest of the fleet.

canonical_prefix stays "P:\\" on a macOS editor. The base rig is the identity
case: canonical_prefix == local_root, and every function here must be a
no-op-shaped pass-through for it.

Stdlib only, pure, never raises -- so it is fully unit-testable from either
host OS.
"""

from __future__ import annotations

import ntpath
import os
import re
from typing import Optional

# "P:", "P:\", "P:/" -- a bare drive root, which is what canonical_prefix is
# on every editor rig in the fleet.
_DRIVE_STYLE_RE = re.compile(r"^[A-Za-z]:[\\/]?$")
# Any drive-rooted spelling: "P:\Projects\x", "p:/projects/x", "P:".
_DRIVE_ROOTED_RE = re.compile(r"^[A-Za-z]:")
_SEP_SPLIT_RE = re.compile(r"[\\/]+")


def is_drive_style(prefix) -> bool:
    """Is this canonical prefix a bare Windows drive root ("P:\\")?

    The interesting consequence is on posix: such a prefix names nothing the
    local filesystem can answer for, so neither exists() nor realpath() may
    be pointed at it (paths.py).
    """
    return bool(_DRIVE_STYLE_RE.match(str(prefix or "").strip()))


def plat_for(path_or_prefix):
    """The path module that understands THIS string's spelling.

    ntpath for anything drive-rooted or backslash-separated, else the host's
    os.path. On Windows os.path IS ntpath, so this changes nothing there; on
    posix it is what makes `P:\\Projects\\x` fold case and separators instead
    of being treated as one long filename.
    """
    text = str(path_or_prefix or "")
    if _DRIVE_ROOTED_RE.match(text.strip()) or "\\" in text:
        return ntpath
    return os.path


def _norm(path, plat) -> str:
    return plat.normcase(plat.normpath(str(path)))


def _is_under(path, root, plat) -> bool:
    if not root:
        return False
    norm_path, norm_root = _norm(path, plat), _norm(root, plat)
    if norm_path == norm_root:
        return True
    sep = plat.sep
    # The separator matters: "P:\Creators_ClubExtra" is not under
    # "P:\Creators_Club".
    return norm_path.startswith(norm_root if norm_root.endswith(sep) else norm_root + sep)


def is_canonical(path, canonical_prefix) -> bool:
    """Is `path` spelled on the canonical prefix (case- and separator-blind)?

    Judged in the PREFIX's spelling, so `p:/projects/x` counts as being under
    `P:\\` on a Mac just as it does on Windows.
    """
    if not path or not canonical_prefix:
        return False
    return _is_under(path, canonical_prefix, plat_for(canonical_prefix))


def _root_base(local_root: str) -> str:
    """local_root with any trailing separator trimmed -- unless trimming it
    would re-root the join ("P:\\" -> "P:" makes os.path.join produce the
    DRIVE-RELATIVE "P:Projects\\x"; "/" -> "" loses the root entirely)."""
    root = str(local_root)
    stripped = root.rstrip("\\/")
    if not stripped or stripped.endswith(":"):
        return root
    return stripped


def canonical_to_local(path, local_root, canonical_prefix) -> Optional[str]:
    """`P:\\Projects\\X\\a.braw` -> `<local_root>/Projects/X/a.braw`, in the
    HOST's spelling -- the form a filesystem probe can actually answer.

    None when `path` isn't on the canonical prefix (nothing to translate), or
    when either root is unset. Never the path to store in Resolve: that is
    always the canonical one (see local_to_canonical).
    """
    if not (path and local_root and canonical_prefix):
        return None
    plat = plat_for(canonical_prefix)
    if not _is_under(path, canonical_prefix, plat):
        return None
    # normpath (not normcase) folds separators while KEEPING the case of the
    # file name -- the probe may land on a case-sensitive volume.
    rest = plat.normpath(str(path))[len(plat.normpath(str(canonical_prefix))):]
    parts = [part for part in _SEP_SPLIT_RE.split(rest) if part]
    return os.path.join(_root_base(local_root), *parts)


def local_to_canonical(dest_path, local_root, canonical_prefix) -> str:
    """The path to STORE IN RESOLVE for a file physically at `dest_path`.

    The relative part is worked out in the HOST's spelling (that is where the
    file actually lives) and re-joined onto the prefix in the PREFIX's
    spelling -- backslashes for `P:\\`, on macOS too, or the project stops
    being portable the moment it travels.

    Falls back to the physical path when no prefix is configured or the file
    isn't under local_root; when canonical_prefix IS local_root (the base
    rig) this is the identity.
    """
    physical = str(dest_path)
    prefix = str(canonical_prefix or "").strip()
    if not prefix:
        return physical
    try:
        rel = os.path.relpath(physical, str(local_root))
    except ValueError:
        return physical  # different drives -- not under local_root
    if rel == "." or rel.startswith(".."):
        return physical
    parts = [part for part in _SEP_SPLIT_RE.split(rel) if part]
    if not parts:
        return physical
    sep = plat_for(prefix).sep
    return prefix.rstrip("\\/") + sep + sep.join(parts)
