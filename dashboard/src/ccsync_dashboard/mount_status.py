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

import threading

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


def record(name: str, status: str, detail: str) -> None:
    """Remember one mount's verdict. Never raises."""
    try:
        with _LOCK:
            _STATE[str(name)] = (str(status or ""), str(detail or ""))
    except Exception:  # noqa: BLE001 - a diagnostic must not break a boot
        pass


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
