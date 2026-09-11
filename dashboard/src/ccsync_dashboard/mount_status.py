"""What the four optional mounts decided at boot, where anything can read it.

DDIAG-7 (usability + resilience sweep 2026-09-03): `/broll`, `/music`, `/ytdl`
and `/cards` each compute a careful tri-state with a sentence of reason ("the
vault root is not mounted (/vault)", "the checkout did not import
(ModuleNotFoundError: ...)"). Until now that sentence went to the container log
and to the authenticated health route only, and on the page the topbar link
simply DISAPPEARED: an editor asks where B-ROLL has gone and the owner has no
page that answers. The self-diagnosis registry (wave 4) exists so that a
refusal does not end in a log nobody opens, and the four biggest refusals the
dashboard makes at boot were not in it.

This is deliberately a MODULE-LEVEL registry rather than something on
`app.state`: the alert checks and the notice writers that read it run on the
collector thread with a Settings and a connection in hand and no app object,
exactly as `ai_backend`'s provider lookup and `fleet_auth`'s stamp switch are
module globals for the same reason. One dashboard process serves one app; a
test that builds several calls `reset()` between them.

Nothing here raises and nothing here logs: it is written from inside the boot
block, which must never be able to stop the dashboard starting.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

# name -> (status, detail). The statuses are the mounts' own strings
# (mounted / absent / degraded / disabled), NOT a fifth vocabulary invented
# here: `ui.py` and the health route compare against broll.MOUNTED and
# friends, and a translation layer is one more place for the two to disagree.
_LOCK = threading.Lock()
_STATE: dict[str, tuple[str, str]] = {}

# The four this dashboard mounts, in boot order. Exported so a reader can tell
# "not mounted" from "never recorded" -- a dashboard too old to record, or one
# that died before the boot block reached that line.
NAMES = ("broll", "music", "ytdl", "cards")


# res-fleet-2 (2026-09-11): name -> the data root that mount is serving, as
# the mount itself resolved it. Recorded so the collector can re-probe it
# every cycle with one `os.path.isdir`, with no import, no database and no
# app object: the tri-state used to be computed ONCE inside `create_app` and
# then rendered for the life of the container as a statement about now, so a
# NAS export that flapped at 03:00 left B-ROLL and MUSIC advertised, every
# request under them failing, and nothing anywhere saying why.
_ROOTS: dict[str, str] = {}

# Names this process downgraded at runtime, with the verdict they held
# before, so a root that comes back restores exactly what the boot recorded
# rather than a sentence invented here.
_RUNTIME_DEGRADED: dict[str, tuple[str, str]] = {}

# The runtime verdict for a mount whose root has gone. DEGRADED, never
# ABSENT: the ASGI sub-app IS mounted in this process and will answer, it is
# the data underneath it that is not there.
DEGRADED = "degraded"
MOUNTED = "mounted"


def record(name: str, status: str, detail: str) -> None:
    """Remember one mount's verdict. Never raises."""
    try:
        with _LOCK:
            _STATE[str(name)] = (str(status or ""), str(detail or ""))
    except Exception:  # noqa: BLE001 - a diagnostic must not break a boot
        pass


def record_root(name: str, root: str) -> None:
    """Remember the data root one mount is serving, for `recheck`. Never
    raises: this is called from inside the boot block."""
    try:
        with _LOCK:
            if str(root or ""):
                _ROOTS[str(name)] = str(root)
    except Exception:  # noqa: BLE001 - a diagnostic must not break a boot
        pass


def recheck(is_dir: Callable[[str], bool] | None = None) -> dict[str, tuple[str, str]]:
    """Re-probe every recorded data root and fold the answer into the verdicts.

    res-fleet-2 (2026-09-11). Called once per collector cycle, BEFORE the
    notice writer reads the snapshot. Cheap by contract: one `is_dir` per
    mount, nothing imported, nothing opened, no database - it runs on the
    collector's single thread beside enforce.

    A root that has gone downgrades a MOUNTED verdict to degraded with the
    reason. A root that comes back restores the boot verdict, and ONLY for a
    mount this function itself downgraded: a mount that failed at boot was
    never mounted into this process's ASGI app, so "the directory is there
    again" is not "the page works again", and saying so would hide the one
    thing the admin has to do (restart the dashboard). A probe that cannot
    answer changes nothing - "could not read" is never "it is gone".

    Returns the names it changed, name -> the new (status, detail).
    """
    probe = is_dir or os.path.isdir
    changed: dict[str, tuple[str, str]] = {}
    with _LOCK:
        for name, root in list(_ROOTS.items()):
            entry = _STATE.get(name)
            if entry is None:
                continue
            status, detail = entry
            try:
                present = bool(probe(root))
            except Exception:  # noqa: BLE001 - cannot tell is not gone
                continue
            if not present and status == MOUNTED:
                _RUNTIME_DEGRADED[name] = (status, detail)
                new = (DEGRADED,
                       f"the folder it serves is not there any more ({root}). "
                       f"Every request to that page will fail until the "
                       f"server's bind mount is back.")
                _STATE[name] = new
                changed[name] = new
            elif present and name in _RUNTIME_DEGRADED:
                new = _RUNTIME_DEGRADED.pop(name)
                _STATE[name] = new
                changed[name] = new
    return changed


def snapshot() -> dict[str, tuple[str, str]]:
    """A copy of every recorded verdict: name -> (status, detail).

    A copy, not the live dict: the readers are on the collector thread and the
    ytdl feature gate rewrites its entry from a request thread whenever the
    site switch flips.
    """
    with _LOCK:
        return dict(_STATE)


def get(name: str) -> tuple[str, str] | None:
    """One mount's (status, detail), or None if nothing recorded it."""
    with _LOCK:
        return _STATE.get(name)


def reset() -> None:
    """Forget everything. For tests, and for a second create_app in one
    process -- otherwise the previous app's verdicts outlive it."""
    with _LOCK:
        _STATE.clear()
        _ROOTS.clear()
        _RUNTIME_DEGRADED.clear()
