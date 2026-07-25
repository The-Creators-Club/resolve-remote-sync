"""Common adapter interface for the three sync lanes.

SPEC.md: "Three lanes behind a common adapter interface ... so engines are
swappable per the SPEC's benchmark." Keep this interface small and
engine-agnostic — nothing here should assume rclone or Syncthing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
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
