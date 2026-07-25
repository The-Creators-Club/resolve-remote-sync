from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ccsync_dashboard import health

NOW = "2026-07-24T12:00:00+00:00"
RECENT = "2026-07-24T11:59:00+00:00"      # 1 min ago
OLD = "2026-07-24T11:30:00+00:00"         # 30 min ago


def editor(**overrides):
    base = dict(
        completion=100.0, need_items=0, connected=True, last_connected_at=RECENT,
        completion_updated_at=RECENT, syncthing_reachable=True, lanes=(), now=NOW,
    )
    base.update(overrides)
    return health.editor_status(**base)


def test_green_when_synced_and_idle():
    assert editor() == health.GREEN
    assert editor(lanes=[{"state": "idle"}, {"state": "paused"}]) == health.GREEN


def test_amber_when_behind_or_syncing():
    assert editor(completion=62.0, need_items=42) == health.AMBER
    assert editor(lanes=[{"state": "syncing"}]) == health.AMBER
    # behind but offline only briefly -> still amber, not red
    assert editor(completion=62.0, need_items=42, connected=False,
                  last_connected_at=RECENT) == health.AMBER


def test_red_on_lane_error():
    assert editor(lanes=[{"state": "idle"}, {"state": "error"}]) == health.RED


def test_red_when_offline_long_and_behind():
    assert editor(completion=62.0, need_items=42, connected=False,
                  last_connected_at=OLD) == health.RED
    assert editor(completion=62.0, need_items=42, connected=False,
                  last_connected_at=None) == health.RED
    # offline but fully synced -> green (nothing owed either way)
    assert editor(connected=False, last_connected_at=OLD) == health.GREEN


def test_red_when_completion_stale_while_syncthing_up():
    assert editor(completion_updated_at=OLD) == health.RED
    # not stale if Syncthing itself is down -- banner covers that case
    assert editor(completion_updated_at=OLD, syncthing_reachable=False) == health.GREEN


def test_rollups_and_precedence():
    assert health.worst([]) == health.GREEN
    assert health.project_status(["green", "amber", "green"]) == health.AMBER
    assert health.fleet_status(["amber", "red"]) == health.RED
    assert health.worst(["green", "unknown-nonsense"]) == health.GREEN


def test_lane_chip_status():
    assert health.lane_chip_status({"state": "idle", "received_at": RECENT}, NOW) == health.GREEN
    assert health.lane_chip_status({"state": "syncing", "received_at": RECENT}, NOW) == health.AMBER
    assert health.lane_chip_status({"state": "error", "received_at": RECENT}, NOW) == health.RED
    # companion silent for 15+ min -> red regardless of last state
    assert health.lane_chip_status({"state": "idle", "received_at": OLD}, NOW) == health.RED
    fresh_enough = "2026-07-24T11:50:00+00:00"  # 10 min ago, under the 15-min cutoff
    assert health.lane_chip_status({"state": "idle", "received_at": fresh_enough}, NOW) == health.GREEN
