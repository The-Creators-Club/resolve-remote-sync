"""Where a fleet job's (root, rel_path) pair lands on THIS computer.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §4.1, phase 0 (2026-08-29).

A job's inputs never carry an absolute path, and the reason is the whole
premise of this repo turned around: the project tree IS spelled the same
everywhere (`P:\\`, by explicit decision), and the two roots a Timeline Cards
job needs are NOT. The vault is `X:\\` on creator-1, `/vault` inside the
Timeline Cards container and a UNC path on the wire; the footage share needs
its own mapping to be usable at all. So a path on the wire would be correct on
exactly one machine, and silently wrong on the rest.

Three roots, by name:

    tree    the canonical project tree -- config `local_root`, the one root
            every machine already has and the only one that is not new here.
    vault   config `jobs_vault_root` (Timeline Cards' canvases, transcripts
            and script docs). Blank = this machine has no vault.
    media   config `jobs_media_root` (the footage share, where it is mounted
            separately from the tree). Blank = no media root here.

A machine that cannot place a root does not report it as a mount, is never
offered a job that requires it, and refuses one that arrives anyway. Absent is
"no capability" and never a guess -- the same rule the whole companion follows
for a seam it does not have.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ccsync.jobpaths")

TREE = "tree"
VAULT = "vault"
MEDIA = "media"
ROOT_KEYS = {VAULT: "jobs_vault_root", MEDIA: "jobs_media_root"}


class JobPathError(ValueError):
    """A job's inputs cannot be placed on this machine. The runner turns this
    into a job FAILURE with the sentence in it, never into a traceback: the
    admin who submitted it has to be able to read why.

    `retryable` (bug-comp-media-3/-8, 2026-09-25): True, the default, is "not
    HERE" (a root this machine lacks, which another machine may have); False
    is a fault in the job itself (a NUL byte, an out_stem that names a
    directory), which every machine in the fleet would refuse the same way,
    so handing it on only buys each of them a cooldown."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = bool(retryable)


def _has_control(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _configured(cfg: dict[str, Any], key: str) -> Optional[Path]:
    raw = str((cfg or {}).get(key, "") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser()
    except (TypeError, ValueError):
        log.warning("job paths: %s is not a usable path (%r)", key, raw)
        return None


def roots(cfg: dict[str, Any]) -> dict[str, Path]:
    """The roots this machine can actually place RIGHT NOW.

    Existence is checked, not just configuration: an external drive that is
    unplugged, or a mapped drive whose `subst` did not run at login, is a root
    this machine does not have -- and reporting it anyway is how a job gets
    claimed by a machine that then cannot read a single file.
    """
    out: dict[str, Path] = {}
    tree = _configured(cfg, "local_root")
    if tree is not None and tree.exists():
        out[TREE] = tree
    for name, key in ROOT_KEYS.items():
        path = _configured(cfg, key)
        if path is not None and path.exists():
            out[name] = path
    return out


def mounts(cfg: dict[str, Any]) -> list[str]:
    """Root NAMES for the capabilities report, in a stable order."""
    have = roots(cfg)
    return [name for name in (TREE, VAULT, MEDIA) if name in have]


def resolve(cfg: dict[str, Any], root: str, rel_path: str) -> Path:
    """(root, rel_path) -> an absolute path on this machine.

    Raises JobPathError when the root is unknown here, when `rel_path` is not
    relative, or when it climbs out of the root. That last check is not
    theatre: the queue is written by an authenticated admin, but "a path from
    the network that a background service opens" is exactly the shape that
    should never be assembled without one, and a `..` in a hand-written
    submission is a typo we should refuse rather than obey.
    """
    name = str(root or "").strip().lower()
    have = roots(cfg)
    if name not in have:
        raise JobPathError(
            f"this machine has no {name or '(unnamed)'} root configured or "
            f"reachable (it has: {', '.join(sorted(have)) or 'none'})")
    raw = str(rel_path or "").strip().replace("\\", "/")
    if not raw:
        raise JobPathError("the job named no path inside the root")
    # bug-comp-media-8 (2026-09-25): a NUL made Path.resolve raise a plain
    # ValueError ("embedded null character"), which the runner's handlers did
    # not catch -- so the job was claimed, dropped with no result, re-offered
    # when its lease ran out, and dropped by the next machine, each one
    # earning the lease-expiry cooldown. Refused HERE, in words, and not
    # retryable: the same bytes are unplaceable on every machine.
    if _has_control(raw):
        raise JobPathError(
            f"{rel_path!r} has a control character in it, which no file "
            f"system here can open", retryable=False)
    # The RAW value decides, before any stripping: `/vault/2026/...` is how
    # the Timeline Cards container spells the vault, and silently reading it
    # as relative would put the work in the wrong place on every machine that
    # is not that container.
    if raw.startswith("/") or os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        raise JobPathError(
            f"a job's path must be RELATIVE to its root, and {rel_path!r} is "
            f"absolute (docs/TIMELINE-CARDS-INTO-CCSYNC.md section 4.1)")
    rel = raw.strip("/")
    try:
        base = have[name].resolve()
        target = (base / rel).resolve()
    except (OSError, ValueError) as exc:
        # bug-comp-media-8: whatever else the platform's resolve refuses
        # becomes the sentence the admin reads, never an escape past the
        # runner. An OSError may be this machine's share having a bad moment,
        # so it stays retryable; a ValueError is the path's own shape.
        raise JobPathError(
            f"{rel_path!r} cannot be placed under the {name} root ({exc})",
            retryable=isinstance(exc, OSError)) from exc
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise JobPathError(
            f"{rel_path!r} climbs out of the {name} root") from exc
    return target


# Characters that make a NAME into something else. Only the forward slash
# does that on EVERY machine: it is a separator on Windows, macOS and the
# dashboard's Linux engine alike, so a stem holding one is refused for the
# whole fleet.
#
# review round (2026-09-25): the first cut refused ':' and '\' fleet-wide
# too, and that turned a name the fleet COULD make into a permanent failure.
# Both are Windows-only hazards: '\' is a separator and a drive colon makes
# `out_dir / stem` throw out_dir away (any other colon is an NTFS alternate
# data stream). Resolve allows ':' in a clip name, Cards sends the multicam
# name as the stem unsanitised, and on HEAD a stem like 'Q&A: Ruskin' failed
# RETRYABLY on Windows, a Mac could write it, and once the budget ran out
# the job pinned onto the dashboard's Linux engine, which writes it fine.
# db.fail_job turns retryable=False straight into FAILED (no Mac turn, no
# pin), so those two are "not HERE" on Windows and nothing at all elsewhere.
_STEM_FORBIDDEN_EVERYWHERE = ("/",)
_STEM_FORBIDDEN_ON_WINDOWS = ("\\", ":")


def safe_stem(stem: str, windows: Optional[bool] = None) -> str:
    """A job's `out_stem` -> the same string, or JobPathError.

    bug-comp-media-3 (2026-09-25): `resolve` refuses an absolute or climbing
    `rel_path`/`out_rel`, and the stem was then appended after it with no
    check at all -- `C:/Windows/Temp/x` replaced the output directory, `..`
    climbed out of it, and a multicam called `Interview 1/2` put its proxy in
    a folder nobody made (a RETRYABLE failure that toured the fleet). The
    stem is a file NAME, and the page looks for exactly that name, so it is
    refused rather than rewritten: a sanitised name is a file the page will
    never find, and the refusal names the clip.

    Empty or dot names, a '/' and a control character are wrong on every
    machine (retryable=False). A '\' or ':' is wrong only on Windows
    (`windows` defaults to this machine), where it is retryable so a Mac or
    the dashboard's pinned engine can still write the file.
    """
    value = str(stem or "")
    if (not value.strip() or value.strip() in (".", "..")
            or any(ch in value for ch in _STEM_FORBIDDEN_EVERYWHERE)
            or _has_control(value)):
        raise JobPathError(
            f"the output name {stem!r} is not a plain file name (no "
            f"slashes, control characters or dot names), so this job "
            f"cannot be written on any machine", retryable=False)
    if windows is None:
        windows = os.name == "nt"
    if windows and any(ch in value for ch in _STEM_FORBIDDEN_ON_WINDOWS):
        raise JobPathError(
            f"the output name {stem!r} has a backslash or a colon in it, "
            f"which Windows cannot use in a file name; a Mac or the "
            f"server can still make it", retryable=True)
    return value
