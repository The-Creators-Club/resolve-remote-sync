"""Timeline-clip path classification for the watcher.

Per SPEC.md's watcher spec, every clip path found on the current timeline is
classified as one of:

  OK           — under local_root (case-insensitive on Windows), spelled
                 canonically (or no canonical prefix is configured).
  NON_CANONICAL— under local_root but spelled with the LOCAL root instead of
                 the canonical prefix -> healthy here, offline fleet-wide;
                 auto-relinkable (the file exists). See the constant.
  OUT_OF_TREE  — exists on disk but outside local_root -> popup candidate.
  FOREIGN      — not canonical, not in the tree, not on disk: another
                 machine's private path -> warn-once, unfixable here. See
                 the constant.
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

That last clause is why anything touching the CANONICAL PREFIX goes through
canon.py instead: on a macOS editor the prefix is still "P:\\" (Resolve
reaches it through its Mapped Mount preference) while the host is posix, so
the prefix must be compared with ntpath and translated to local_root before
it is ever handed to the filesystem — os.path.exists("P:\\Projects\\x") is
False on every Mac, healthy or broken.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import subprocess
import threading
import time
from typing import Callable, Optional

from . import canon

OK = "OK"
OUT_OF_TREE = "OUT_OF_TREE"
BAD_PREFIX = "BAD_PREFIX"
MISSING = "MISSING"
# The two classes the 2026-08-12 "Energy Transition" incident showed were
# conflated into OK and MISSING respectively (200+ silently-broken clips):
#
# NON_CANONICAL -- under local_root, so the file is HERE and healthy, but
#   spelled with the local root (`F:\Creators_Club\...`) instead of the
#   canonical prefix (`P:\...`). Playable on this machine, offline on every
#   other one. The file exists locally, so the fix is a pure ReplaceClip to
#   canon.local_to_canonical's spelling -- no copy, safe to automate. Never
#   produced on the base rig (there local_root IS the canonical prefix, so
#   every in-tree path is already canonical), and never produced when no
#   canonical prefix is configured.
NON_CANONICAL = "NON_CANONICAL"
# FOREIGN -- not canonical, not in this tree, and NOT on disk: a path from
#   some other machine's private namespace (another editor's local_root
#   spelling, their Z:\ archive drive, a Desktop file). It will never sync
#   and never come online here, unlike MISSING -- which stays reserved for
#   canonical-prefix paths whose file simply isn't downloaded (the designed
#   steady state on a remote rig). Nothing on THIS machine can fix a FOREIGN
#   clip (there is no file to copy), so it warns rather than popping the
#   fixer.
FOREIGN = "FOREIGN"

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


# share name -> (stamp, local path or None). `net share` spawns a process;
# the target of a share changes ~never, so cache generously.
_share_cache: dict[str, tuple[float, Optional[str]]] = {}
_SHARE_CACHE_TTL_SECONDS = 60.0
_UNC_RE = re.compile(r"^\\\\([^\\]+)\\([^\\]+)(.*)$")


def _local_share_target(share: str) -> Optional[str]:
    """The local directory behind a share of THIS machine, via `net share
    <name>`. None when the share is unknown or the output unparseable (the
    labels are localized; the path itself is recognizable as <drive>:\\...)."""
    now = time.monotonic()
    cached = _share_cache.get(share.lower())
    if cached is not None and now - cached[0] < _SHARE_CACHE_TTL_SECONDS:
        return cached[1]
    target: Optional[str] = None
    try:
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        proc = subprocess.run(
            ["net", "share", share], capture_output=True, encoding="utf-8",
            errors="replace", timeout=10, creationflags=creationflags,
        )
        if proc.returncode == 0:
            # Locale-proof parse: `net share` labels are localized, but the
            # value we want is the first thing shaped like an absolute
            # local path on its own field.
            for line in proc.stdout.splitlines():
                m = re.search(r"([A-Za-z]:\\\S(?:.*\S)?)\s*$", line.strip())
                if m:
                    target = m.group(1)
                    break
    except Exception:
        target = None
    _share_cache[share.lower()] = (now, target)
    return target


def _delooped(resolved: str) -> str:
    """Translate a UNC path whose host is THIS machine back to the shared
    directory's local path.

    The editors' P: is a LOOPBACK SHARE mapping (\\\\localhost\\CCSync_P ->
    local_root; b29a263 made that the primary mapping for the Explorer
    label), so realpath("P:\\...") answers \\\\localhost\\CCSync_P\\... --
    which IS local_root in disguise, but string-matches nothing. Untranslated
    it made every canonically-relinked clip read as BAD_PREFIX the moment
    0.4.10 started storing P:\\ paths (2026-07-26). Non-UNC and remote-host
    paths come back unchanged."""
    m = _UNC_RE.match(str(resolved))
    if not m or os.name != "nt":
        return resolved
    host, share, rest = m.group(1), m.group(2), m.group(3)
    local_names = {"localhost", "127.0.0.1", "::1"}
    computer = os.environ.get("COMPUTERNAME", "")
    if computer:
        local_names.add(computer.lower())
    if host.lower() not in local_names:
        return resolved
    target = _local_share_target(share)
    if not target:
        return resolved
    return target.rstrip("\\/") + rest


def _is_under(norm_path: str, norm_root: str, sep: str) -> bool:
    if not norm_root:
        return False
    if norm_path == norm_root:
        return True
    root_with_sep = norm_root if norm_root.endswith(sep) else norm_root + sep
    return norm_path.startswith(root_with_sep)


def _fn_key(fn) -> str:
    return getattr(fn, "__qualname__", repr(fn))


def _prefix_resolves_under_root(
    canonical_prefix: str,
    norm_root: str,
    plat,
    sep: str,
    resolve: Callable[[str], str],
    posix_drive_prefix: bool = False,
    root_present_fn: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Does the canonical prefix itself (P:\\, /Volumes/CreatorsClub) resolve
    to somewhere under local_root? Cached for _PREFIX_CACHE_TTL_SECONDS.

    `posix_drive_prefix` says the prefix is a Windows drive root while the
    host is posix (a macOS editor: canonical_prefix stays "P:\\", Resolve
    reaches it through its Mapped Mount preference). realpath() cannot answer
    there -- there is no drive namespace, so "P:\\" resolves RELATIVE TO THE
    CWD -- which would either compare unequal and storm BAD_PREFIX over every
    clip, or raise and be swallowed by the fail-open guard below, permanently
    masking a genuinely broken install. The honest signal on that host is
    whether the local tree is present at all; `root_present_fn` is the seam a
    future root-guard can veto through (default os.path.isdir).
    """
    key = (
        str(canonical_prefix), norm_root, sep, _fn_key(resolve),
        bool(posix_drive_prefix), _fn_key(root_present_fn),
    )
    now = time.monotonic()
    with _prefix_cache_lock:
        cached = _prefix_cache.get(key)
        if cached is not None and now - cached[0] < _PREFIX_CACHE_TTL_SECONDS:
            return cached[1]
    if posix_drive_prefix:
        present = root_present_fn if root_present_fn is not None else os.path.isdir
        try:
            healthy = bool(present(norm_root))
        except Exception:
            healthy = True  # same fail-open ethos as the probe below
        with _prefix_cache_lock:
            _prefix_cache[key] = (now, healthy)
        return healthy
    try:
        healthy = _is_under(_norm(_delooped(resolve(canonical_prefix)), plat), norm_root, sep)
        if not healthy:
            # Filesystem-identity fallback: on setups where the loopback
            # share can't be translated (localized `net share`, exotic
            # mappings), the prefix root and local_root being the SAME
            # directory is still provable by stat identity.
            try:
                healthy = os.path.samefile(str(canonical_prefix), str(norm_root))
            except OSError:
                pass
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
    root_present_fn: Optional[Callable[[str], bool]] = None,
) -> str:
    """Classify a single clip path. Never raises.

    `exists_fn` and `is_windows` are injectable for tests so both Windows-
    and posix-style paths can be exercised from either host OS. They default
    to os.path.exists and the real host platform. `root_present_fn` is only
    consulted on the posix + drive-style-prefix path (a macOS editor) -- see
    _prefix_resolves_under_root.
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
        # In the tree -- but stored under which SPELLING? A local_root
        # spelling in a shared project is offline on every other machine
        # (NON_CANONICAL's constant). On the base rig local_root IS the
        # prefix, so is_canonical answers True for every in-tree path and
        # this stays OK.
        if canonical_prefix and not canon.is_canonical(path, canonical_prefix):
            return NON_CANONICAL
        return OK

    # Membership in the canonical prefix is judged in the PREFIX's spelling,
    # not the host's: on a Mac the prefix is still "P:\" and posixpath would
    # neither fold its case nor its separators (canon.plat_for).
    on_prefix = bool(canonical_prefix) and canon.is_canonical(path, canonical_prefix)

    # A canonical path is a fleet-portable STRING, never a local one: on
    # posix nothing can stat "P:\Projects\x", so exists() would answer False
    # for every clip in the project and the whole timeline would misclassify.
    # Probe the file where it physically lives instead.
    local_twin = None
    posix_drive_prefix = on_prefix and not windows and canon.is_drive_style(canonical_prefix)
    if posix_drive_prefix:
        local_twin = canon.canonical_to_local(path, local_root, canonical_prefix)

    try:
        exists = bool(check_exists(local_twin if local_twin else path))
    except Exception:
        exists = False

    if on_prefix:
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
            if _prefix_resolves_under_root(canonical_prefix, norm_root, plat, sep, resolve,
                                           posix_drive_prefix, root_present_fn):
                return MISSING
            return BAD_PREFIX
        if local_twin:
            # The twin IS under local_root by construction, and it exists:
            # the clip is downloaded and correctly addressed. There is
            # nothing for realpath to add (and on posix it cannot answer for
            # "P:\" at all).
            return OK
        if norm_root:
            try:
                real = _norm(_delooped(resolve(path)), plat)
            except Exception:
                real = norm_path
            if _is_under(real, norm_root, sep):
                return OK
            # The clip exists on the canonical prefix and the PREFIX itself
            # is healthy (loopback share / subst landing on local_root):
            # this is the designed steady state, not a broken mapping.
            if _prefix_resolves_under_root(canonical_prefix, norm_root, plat, sep, resolve,
                                           posix_drive_prefix, root_present_fn):
                return OK
        # Exists (the mapping resolves to something real) but not under
        # local_root -- a genuinely broken mapping (wrong subst/mount
        # target, or local_root isn't configured at all) -> warn.
        return BAD_PREFIX

    if exists:
        return OUT_OF_TREE

    # Not canonical, not in the tree, not on disk: another machine's private
    # namespace (see FOREIGN's constant). NOT MISSING -- that class is
    # reserved for canonical-prefix paths whose file simply isn't synced,
    # and conflating the two silenced every warning the 2026-08-12 incident
    # should have raised.
    return FOREIGN
