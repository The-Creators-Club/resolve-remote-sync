"""Common adapter interface for the three sync lanes.

SPEC.md: "Three lanes behind a common adapter interface ... so engines are
swappable per the SPEC's benchmark." Keep this interface small and
engine-agnostic — nothing here should assume rclone or Syncthing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

STATE_IDLE = "idle"
STATE_SYNCING = "syncing"
STATE_ERROR = "error"
STATE_PAUSED = "paused"


@dataclass
class LaneStatus:
    name: str
    state: str = STATE_IDLE
    queued: int = 0
    transferring: int = 0
    last_error: Optional[str] = None
    last_sync: Optional[datetime] = None
    detail: str = ""
    # Per-project (subtree) run + live transfer stats, groundwork for a
    # sequencer built separately (see sync/rclone_lane.py).
    current_project: Optional[str] = None
    bytes_done: Optional[int] = None
    bytes_total: Optional[int] = None
    speed_bps: Optional[float] = None
    eta_seconds: Optional[float] = None
    # Per-file rclone --stats "transferring" entries, live during a run —
    # see sync/rclone_lane.py:_handle_stderr_line. Each dict:
    # {"name","direction","bytes_done","bytes_total","percentage",
    #  "speed_bps","eta_seconds"}. Empty when idle or between stats ticks.
    transfers: list = field(default_factory=list)
    # -- the liveness contract (SYS-1, resilience sweep 2026-08-28) --------
    #
    # A state may not be reported green or amber without evidence that it is
    # moving. CR-91 is what a lane without it costs: `state=syncing,
    # transferring=1, last_error=NULL` for 2 h 20 m, indistinguishable on the
    # fleet page from a lane that was working, while the editor downloaded
    # nothing at all.
    #
    # `progress_token` changes whenever real work happened (bytes and files
    # moved, plus the project they moved for), so the dashboard can red a
    # non-terminal state whose token has not moved. Bytes, NOT wall clock: a
    # genuinely slow 40 GB original over a thin uplink must not read as a
    # hang. None while nothing is running.
    progress_token: Optional[str] = None
    # When this lane entered its current `state`. Stamped by __post_init__ /
    # __setattr__ below rather than at each of the ~30 assignment sites,
    # every one of which would otherwise be a place to forget it.
    state_since: Optional[datetime] = None

    def __post_init__(self) -> None:
        # Stamped here, not in __setattr__, for the construction case:
        # __init__ assigns every field in declaration order, so a stamp made
        # while assigning `state` would be overwritten a moment later by the
        # state_since default. A value that WAS passed is kept, which is what
        # keeps `LaneStatus(**vars(other))` -- the snapshot copy every
        # status() returns -- from re-dating a state it merely copied.
        if self.state_since is None:
            object.__setattr__(self, "state_since", datetime.now(timezone.utc))

    def __setattr__(self, name, value):
        if name == "state" and getattr(self, "state", None) != value:
            object.__setattr__(self, "state_since", datetime.now(timezone.utc))
        object.__setattr__(self, name, value)


class LaneAdapter(ABC):
    """One sync lane (A, B, or C). Implementations must never raise out of
    start()/stop()/status() — failures belong in LaneStatus.last_error."""

    name: str = "lane"

    @abstractmethod
    def start(self) -> None:
        """Begin whatever background activity this lane needs (threads,
        watchdog observers, periodic timers). Idempotent."""

    @abstractmethod
    def stop(self) -> None:
        """Stop all background activity. Idempotent."""

    @abstractmethod
    def status(self) -> LaneStatus:
        """Current status snapshot. Must be cheap/non-blocking."""

    def run_once(self) -> LaneStatus:
        """Force one synchronous pass right now ("Sync now" tray action).
        Default implementation just returns the current status; adapters
        that support an on-demand pass should override this."""
        return self.status()
