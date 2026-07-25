"""Sequencer tests: fake lanes/admin/selection client, fast intervals, no
real sleeping beyond small polling waits -- in the style of
test_reporter.py's threaded fault-isolation tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ccsync_companion.sync.sequencer import STATE_NO_SELECTION, STATE_PAUSED, Sequencer


# -- fakes -----------------------------------------------------


class FakeLane:
    """Records run_once(subpath) calls into a shared events list, tagged by
    `name`, so tests can assert cross-lane/cross-project ordering."""

    def __init__(self, name, events, raise_on=None):
        self.name = name
        self.events = events
        self.raise_on = set(raise_on or [])
        self.calls = []

    def run_once(self, subpath=None):
        self.calls.append(subpath)
        self.events.append((self.name, subpath))
        if subpath in self.raise_on:
            raise RuntimeError(f"{self.name}: boom on {subpath}")


class FakeAdmin:
    """Records pause/accept calls; folder_status is scriptable per slug via
    `status_by_slug[slug]` -- either a constant int or a zero-arg callable
    returning the next needTotalItems value."""

    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.pause_calls = []
        self.pending = {}
        self.accept_calls = []
        self.status_by_slug = {}
        self.status_calls = []

    def set_folder_paused(self, folder_id, paused):
        self.pause_calls.append((folder_id, paused))
        self.events.append(("pause", folder_id, paused))

    def pending_folders(self):
        return dict(self.pending)

    def accept_folder(self, folder_id, label, local_path, offered_by_device_id):
        self.accept_calls.append(
            {
                "folder_id": folder_id,
                "label": label,
                "local_path": local_path,
                "offered_by_device_id": offered_by_device_id,
            }
        )
        self.pending.pop(folder_id, None)
        return {}

    def folder_status(self, folder_id):
        self.status_calls.append(folder_id)
        value = self.status_by_slug.get(folder_id, 0)
        need = value() if callable(value) else value
        return {"needTotalItems": need}


class FakeSelectionClient:
    def __init__(self, selection=None, source="live", cached=None, enabled=True):
        self.selection = selection
        self.source = source
        self.cached = cached
        self.enabled = enabled
        self.get_calls = 0

    def get(self):
        self.get_calls += 1
        return self.selection, self.source

    def load_cached(self):
        return self.cached

    def fetch(self):
        return self.selection


def _item(slug, rel_path, position, label=None):
    return {"slug": slug, "label": label or rel_path, "rel_path": rel_path, "position": position, "active": True}


def _cfg(**overrides):
    cfg = {
        "local_root": "/local",
        "selection_poll_interval": 0.02,
        "project_rotation_seconds": 5.0,
        "sequencer_idle_seconds": 0.02,
    }
    cfg.update(overrides)
    return cfg


def _build(selection_client, admin, **cfg_overrides):
    events = admin.events
    lane_a = FakeLane("lane_a", events)
    lane_b = FakeLane("lane_b", events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection_client, _cfg(**cfg_overrides),
        folder_status_poll_seconds=0.02,
    )
    return seq, lane_a, lane_b, events


def _wait_until(predicate, timeout=3.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture(autouse=True)
def _stop_all_sequencers():
    created = []
    orig_init = Sequencer.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        created.append(self)

    Sequencer.__init__ = tracking_init
    try:
        yield
    finally:
        Sequencer.__init__ = orig_init
        for seq in created:
            try:
                seq.stop()
            except Exception:
                pass


# -- ordering -----------------------------------------------------


def test_ordering_follows_positions():
    items = [
        _item("s-b", "2026/FF5/Bravo", 2),
        _item("s-a", "2026/FF5/Alpha", 0),
        _item("s-c", "2026/FF5/Charlie", 1),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 3)
    seq.stop()

    assert lane_a.calls[:3] == [
        "Projects/2026/FF5/Alpha",
        "Projects/2026/FF5/Charlie",
        "Projects/2026/FF5/Bravo",
    ]


def test_one_at_a_time_lane_calls_for_p2_only_after_p1_c_turn_ends():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 2)
    seq.stop()

    # Find index of Bravo's first lane_a event; everything for Alpha
    # (lane_a, lane_b, and its pause/unpause C-turn) must precede it.
    bravo_idx = next(i for i, e in enumerate(events) if e == ("lane_a", "Projects/2026/FF5/Bravo"))
    before = events[:bravo_idx]
    assert ("lane_a", "Projects/2026/FF5/Alpha") in before
    assert ("lane_b", "Projects/2026/FF5/Alpha") in before
    assert ("pause", "s-a", False) in before  # Alpha's C-turn unpause happened first


# -- folder_status polling -----------------------------------------------------


def test_need_total_items_reaching_zero_advances():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    remaining = iter([3, 2, 1, 0])
    admin.status_by_slug["s-a"] = lambda: next(remaining, 0)
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: "Projects/2026/FF5/Bravo" in lane_a.calls, timeout=3.0)
    seq.stop()

    assert admin.status_calls.count("s-a") >= 2


def test_rotation_budget_expiry_advances():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5  # never reaches 0
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=0.1)

    seq.start()
    assert _wait_until(lambda: "Projects/2026/FF5/Bravo" in lane_a.calls, timeout=3.0)
    seq.stop()


# -- auto-accept -----------------------------------------------------


def test_auto_accept_only_for_pending_selected_folder_with_correct_local_path():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.pending = {
        "s-a": {"offeredBy": {"DEVICE-1": {"time": "now", "label": "Alpha"}}},
        "unrelated-slug": {"offeredBy": {"DEVICE-2": {"time": "now", "label": "Other"}}},
    }
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: len(admin.accept_calls) >= 1)
    seq.stop()

    assert len(admin.accept_calls) == 1
    call = admin.accept_calls[0]
    assert call["folder_id"] == "s-a"
    assert call["local_path"] == str(Path("/local") / "Projects" / "2026/FF5/Alpha")
    assert call["offered_by_device_id"] == "DEVICE-1"
    assert all(c["folder_id"] != "unrelated-slug" for c in admin.accept_calls)


# -- pause/unpause scoping -----------------------------------------------------


def test_only_selected_folders_ever_touched_by_pause_unpause():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 2)
    seq.stop()

    touched = {slug for slug, _paused in admin.pause_calls}
    assert touched <= {"s-a", "s-b"}
    assert touched  # sanity: something was actually touched


def test_between_passes_unpauses_all_selected():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin, sequencer_idle_seconds=0.05)

    seq.start()
    # One unpause from the C-turn, then a second once the pass completes and
    # the idle-between-passes unpause-all runs.
    assert _wait_until(lambda: admin.pause_calls.count(("s-a", False)) >= 2, timeout=3.0)
    seq.stop()


# -- notify_change -----------------------------------------------------


def test_notify_change_promotes_non_current_selected_project_to_next():
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        _item("s-b", "2026/FF5/Bravo", 1),
        _item("s-c", "2026/FF5/Charlie", 2),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5  # keep Alpha "running" so we can promote mid-project
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: seq.current_slug == "s-a", timeout=3.0)
    seq.notify_change("Projects/2026/FF5/Charlie")

    assert _wait_until(lambda: seq.queue_slugs == ["s-c", "s-b"], timeout=2.0)
    seq.stop()


def test_notify_change_ignores_current_project():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: seq.current_slug == "s-a", timeout=3.0)
    before = seq.queue_slugs
    seq.notify_change("Projects/2026/FF5/Alpha")  # already current -> ignored
    time.sleep(0.1)
    assert seq.queue_slugs == before
    seq.stop()


# -- selection changes mid-pass -----------------------------------------------------


def test_selection_change_at_boundary_restarts_pass():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=list(items))
    admin = FakeAdmin()
    # Hold Alpha's C-turn open for a few poll ticks (~60ms @ 0.02s/tick) so
    # there's a reliable window to mutate the selection before the
    # between-projects recheck fires -- without this the fake calls all
    # resolve near-instantly and the test would race against the loop.
    countdown = iter([3, 2, 1, 0])
    admin.status_by_slug["s-a"] = lambda: next(countdown, 0)
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: "Projects/2026/FF5/Alpha" in lane_a.calls, timeout=3.0)
    # Simulate a dashboard change right after Alpha finishes and before
    # Bravo starts: Bravo is dropped, a new project Charlie takes its slot.
    selection.selection = [
        _item("s-c", "2026/FF5/Charlie", 0),
        _item("s-a", "2026/FF5/Alpha", 1),
    ]

    assert _wait_until(lambda: "Projects/2026/FF5/Charlie" in lane_a.calls, timeout=3.0)
    seq.stop()
    # Bravo must never have run -- it was removed before its turn came up.
    assert "Projects/2026/FF5/Bravo" not in lane_a.calls


# -- NO_SELECTION -----------------------------------------------------


def test_no_selection_when_client_returns_none_none():
    selection = FakeSelectionClient(selection=None, source="none", cached=None)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: seq.state == STATE_NO_SELECTION, timeout=2.0)
    time.sleep(0.05)
    detail = seq.status_detail()
    seq.stop()

    assert lane_a.calls == []
    assert lane_b.calls == []
    assert "dashboard unreachable" in detail


# -- pause/resume/stop -----------------------------------------------------


def test_pause_unpauses_all_and_blocks_steps():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5  # keep Alpha running so we can pause mid-project
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: seq.current_slug == "s-a", timeout=3.0)
    seq.pause()

    assert _wait_until(lambda: seq.state == STATE_PAUSED, timeout=2.0)
    # Both selected folders must have been unpaused by pause().
    assert ("s-a", False) in admin.pause_calls
    assert ("s-b", False) in admin.pause_calls

    calls_at_pause = len(lane_a.calls)
    time.sleep(0.15)
    assert len(lane_a.calls) == calls_at_pause  # no new steps while paused

    seq.stop()


def test_stop_unpauses_selected_folders():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: seq.current_slug == "s-a", timeout=3.0)
    seq.stop()

    assert ("s-a", False) in admin.pause_calls


# -- fault isolation -----------------------------------------------------


def test_lane_run_once_raising_does_not_kill_the_loop():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    events = []
    lane_a = FakeLane("lane_a", events, raise_on={"Projects/2026/FF5/Alpha"})
    lane_b = FakeLane("lane_b", events)
    seq = Sequencer(lane_a, lane_b, admin, selection, _cfg(), folder_status_poll_seconds=0.02)

    seq.start()
    assert _wait_until(lambda: "Projects/2026/FF5/Bravo" in lane_a.calls, timeout=3.0)
    seq.stop()

    assert "Projects/2026/FF5/Alpha" in lane_a.calls
    assert "Projects/2026/FF5/Bravo" in lane_a.calls


# -- disabled -----------------------------------------------------


def test_start_is_a_noop_when_selection_disabled():
    selection = FakeSelectionClient(selection=None, enabled=False)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    time.sleep(0.1)
    assert lane_a.calls == []
    assert seq._thread is None
    seq.stop()  # must not raise even though nothing started


# -- lane B kill switch (base rig with direct NAS access) ---------


def test_lane_b_disabled_skips_proxy_runs():
    selection = FakeSelectionClient([_item("p1", "2026/FF5/Energy Transition", 1)])
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin, lane_b_enabled=False)
    seq.start()
    assert _wait_until(lambda: lane_a.calls)
    assert _wait_until(lambda: seq.state in ("between_passes", "running", "no_selection"))
    seq.stop()
    assert lane_a.calls and not lane_b.calls


# -- structure clone (empty-dir replication on tick) -------------------------


def test_structure_clone_runs_before_lanes_for_each_project():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    events = admin.events
    lane_a = FakeLane("lane_a", events)
    lane_b = FakeLane("lane_b", events)

    def fake_clone(**kwargs):
        events.append(("clone", kwargs["subpath"]))
        return 3

    seq = Sequencer(
        lane_a, lane_b, admin, selection, _cfg(remote="r", remote_root="/root"),
        folder_status_poll_seconds=0.02, clone_tree_fn=fake_clone,
    )
    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 2)
    seq.stop()

    # For each project: clone strictly precedes that project's lane A run.
    for rel in ("Projects/2026/FF5/Alpha", "Projects/2026/FF5/Bravo"):
        clone_idx = events.index(("clone", rel))
        lane_idx = events.index(("lane_a", rel))
        assert clone_idx < lane_idx


def test_structure_clone_failure_does_not_stop_the_pass():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    events = admin.events
    lane_a = FakeLane("lane_a", events)
    lane_b = FakeLane("lane_b", events)

    def broken_clone(**kwargs):
        raise OSError("rclone exploded")

    seq = Sequencer(
        lane_a, lane_b, admin, selection, _cfg(),
        folder_status_poll_seconds=0.02, clone_tree_fn=broken_clone,
    )
    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 1)
    seq.stop()
    assert "Projects/2026/FF5/Alpha" in lane_a.calls
