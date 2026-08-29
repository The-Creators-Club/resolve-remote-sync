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
    admin who submitted it has to be able to read why."""


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
    rel = str(rel_path or "").strip().replace("\\", "/").strip("/")
    if not rel:
        raise JobPathError("the job named no path inside the root")
    if os.path.isabs(rel) or (len(rel) > 1 and rel[1] == ":"):
        raise JobPathError(
            f"a job's path must be RELATIVE to its root, and {rel_path!r} is "
            f"absolute (docs/TIMELINE-CARDS-INTO-CCSYNC.md section 4.1)")
    base = have[name].resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise JobPathError(
            f"{rel_path!r} climbs out of the {name} root") from exc
    return target
