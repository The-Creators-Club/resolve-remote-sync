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
        self.accept_raises = set()
        self.status_by_slug = {}
        self.status_calls = []
        self.ignore_calls = []
        self.versioning_calls = []
        self.completion_calls = []
        # slug -> needBytes the SERVER still needs from us (AUDIT_2 P5)
        self.completion_need_bytes = {}
        self.paused_state = {}
        self.my_id = "SELF-DEVICE"
        self.folder_devices = {}
        self.max_folder_concurrency_calls = []

    def set_folder_paused(self, folder_id, paused):
        self.pause_calls.append((folder_id, paused))
        self.paused_state[folder_id] = paused
        self.events.append(("pause", folder_id, paused))

    def ensure_max_folder_concurrency(self, value):
        """What replaces the pause scheme's pacing (AUDIT_2 P4/C-1)."""
        self.max_folder_concurrency_calls.append(value)
        return True

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
        if folder_id in self.accept_raises:
            raise RuntimeError("set_ignores timed out; folder left paused")
        self.pending.pop(folder_id, None)
        return {}

    def set_ignores(self, folder_id, lines):
        self.ignore_calls.append((folder_id, list(lines)))
        return {}

    def ensure_versioning(self, folder_id, folder=None):
        self.versioning_calls.append(folder_id)
        return True

    def get_config(self):
        return {
            "folders": [
                {
                    "id": fid,
                    "paused": paused,
                    "devices": [{"deviceID": d} for d in self.folder_devices.get(fid, [])],
                }
                for fid, paused in self.paused_state.items()
            ]
        }

    def system_status(self):
        return {"myID": self.my_id}

    def completion(self, folder_id, device_id):
        self.completion_calls.append((folder_id, device_id))
        value = self.completion_need_bytes.get(folder_id, 0)
        need = value() if callable(value) else value
        return {"needBytes": need}

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


def test_stop_during_lane_c_pause_sweep_never_leaves_a_folder_stuck_paused():
    """Regression (AUDIT §4): stop()/pause() used to run _unpause_all()
    BEFORE the worker had actually stopped, so an in-flight _lane_c_turn
    sweep (pausing every OTHER selected project) could re-pause a folder
    right after the unpause-everything sweep already ran -- leaving it
    stuck paused until the next launch. Fires stop() from inside the
    sweep loop itself (mid-iteration) and asserts every folder ends up
    unpaused, with the sweep never reaching a later folder.

    Pinned to lane_c_pause_scheme="rotate": there IS no pause sweep under
    the new default (AUDIT_2 P4), but the scheme is still selectable, so the
    ordering guarantee it depends on still has to hold."""
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        _item("s-b", "2026/FF5/Bravo", 1),
        _item("s-c", "2026/FF5/Charlie", 2),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin, lane_c_pause_scheme="rotate")

    stopped_thread: dict[str, threading.Thread] = {}
    orig_pause = admin.set_folder_paused

    def hooked(folder_id, paused):
        orig_pause(folder_id, paused)
        # Fire exactly while Alpha's lane-C sweep is mid-loop pausing
        # Bravo -- setting the stop event here is synchronous on the
        # WORKER's own thread, so the sweep's next iteration (Charlie) is
        # guaranteed to observe it rather than racing a separate thread.
        if folder_id == "s-b" and paused and "t" not in stopped_thread:
            seq._stop_event.set()
            t = threading.Thread(target=seq.stop, daemon=True)
            t.start()
            stopped_thread["t"] = t

    admin.set_folder_paused = hooked

    seq.start()
    assert _wait_until(lambda: "t" in stopped_thread, timeout=3.0)
    stopped_thread["t"].join(timeout=5.0)

    # The sweep must have bailed before ever touching Charlie.
    assert ("s-c", True) not in admin.pause_calls

    # Nothing selected may be left stuck paused -- the LAST recorded call
    # for every slug that was touched must be an unpause.
    for slug in ("s-a", "s-b", "s-c"):
        calls_for = [p for s, p in admin.pause_calls if s == slug]
        if calls_for:
            assert calls_for[-1] is False, f"{slug} left paused: {calls_for}"


# -- invalid selection items (AUDIT D-4) -----------------------------------------------------


def test_process_project_skips_item_with_null_rel_path():
    """A dashboard row whose rel_path is None (e.g. an orphaned selection --
    LEFT JOIN yields NULL) must never reach the path join, where
    str(None) == "None" would build "Projects/None" and move a real
    directory there."""
    items = [{"slug": "s-a", "rel_path": None, "position": 0, "active": True}]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    time.sleep(0.2)
    seq.stop()

    assert lane_a.calls == []
    assert lane_b.calls == []


def test_known_rels_excludes_invalid_or_inactive_items():
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        {"slug": "s-b", "rel_path": None, "position": 1, "active": True},
        {"slug": "s-c", "rel_path": "2026/FF5/Charlie", "position": 2, "active": False},
        {"slug": "s-d", "rel_path": 123, "position": 3, "active": True},
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: seq.known_rels() != [])
    seq.stop()

    assert seq.known_rels() == ["2026/FF5/Alpha"]
    assert "Projects/2026/FF5/Charlie" not in [c for c in lane_a.calls]


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


# -- thread lifecycle (AUDIT_2 L-1) -----------------------------------------


def test_start_never_spawns_a_second_sequencer_thread():
    """AUDIT_2 L-1 [reproduced live]: stop() joins with timeout=10, which an
    in-flight 40 GB lane A run always outlasts. start() then cleared
    _stop_event and spawned thread #2 alongside the still-looping #1. Both
    drove _lane_c_turn, so Syncthing folders flipped paused/unpaused several
    times a second, _in_lane_c_turn was corrupted by whichever thread wrote
    last, and rotation collapsed. Every subsequent sign-out/sign-in added
    another permanent thread."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5  # keep the turn open so the thread stays busy
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: seq.current_slug == "s-a", timeout=3.0)
    first = seq._thread

    # Simulate the sign-out -> sign-in whose stop() join timed out: the
    # thread is still alive when start() is called again.
    seq.start()
    assert seq._thread is first

    live = [t for t in threading.enumerate() if t.name == "ccsync-sequencer" and t.is_alive()]
    assert len(live) == 1
    seq.stop()


# -- accept failures must not be unpaused (AUDIT_2 L-3) ---------------------


def test_failed_accept_leaves_the_folder_paused():
    """test_syncthing_admin.py asserts accept_folder leaves a folder paused
    when set_ignores fails. Its own caller broke that guarantee 1 ms later by
    unpausing unconditionally -- and since the folder then leaves
    pending_folders(), NOTHING ever retried the ignores, so lane C indexed
    and offered every .braw/.mov original for the life of the install."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.pending = {"s-a": {"offeredBy": {"DEVICE-1": {}}}}
    admin.accept_raises.add("s-a")
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    # Let several passes go by: the turn must never unpause it, and neither
    # may the leak-recovery sweeps that run between passes.
    assert _wait_until(lambda: len(admin.accept_calls) >= 3, timeout=5.0)
    # Snapshot BEFORE stop(), whose own sweep is a separate concern.
    during_the_passes = list(admin.pause_calls)
    seq.stop()

    unpauses = [c for c in during_the_passes if c == ("s-a", False)]
    # At most the single pre-lane unpause of the FIRST pass, i.e. before the
    # first accept attempt could reveal the problem. Never once the folder is
    # known to have landed without its ignores.
    assert len(unpauses) <= 1, during_the_passes
    # No ignores/versioning reassertion either -- the folder isn't usable.
    assert admin.ignore_calls == []
    # And the pass moved on rather than dying.
    assert lane_a.calls


def test_successful_turn_reasserts_ignores_and_versioning_every_turn():
    """AUDIT_2 L-3/P6/DEL-6: nothing in the codebase ever set ignores or
    versioning on a folder it did not itself accept, so a folder accepted by
    an older companion or by hand in the Syncthing GUI stayed un-ignored (and
    unversioned) forever."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()  # nothing pending: the folder was accepted long ago
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: admin.ignore_calls, timeout=3.0)
    seq.stop()

    assert admin.ignore_calls[0][0] == "s-a"
    assert any("*.braw" in line for line in admin.ignore_calls[0][1])
    assert "s-a" in admin.versioning_calls


# -- lane C turn must not end mid-upload (AUDIT_2 P5) -----------------------


def test_turn_waits_for_outgoing_uploads_to_drain():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 0          # nothing left to DOWNLOAD...
    admin.folder_devices["s-a"] = ["SELF-DEVICE", "NAS-DEVICE"]
    remaining = iter([9000, 4000, 0])        # ...but plenty still to UPLOAD
    admin.completion_need_bytes["s-a"] = lambda: next(remaining, 0)
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: "Projects/2026/FF5/Bravo" in lane_a.calls, timeout=3.0)
    seq.stop()

    # The turn polled completion against the NAS device, not just db/status.
    assert ("s-a", "NAS-DEVICE") in admin.completion_calls
    assert ("s-a", "SELF-DEVICE") not in admin.completion_calls
    assert len(admin.completion_calls) >= 2


# -- notify_change starvation (AUDIT_2 L-10) --------------------------------


def test_notify_change_ignores_projects_already_done_this_pass():
    """Lane A's watchdog fires per write chunk, so a card ingest into
    project 1 of N re-prepended project 1 thousands of times a minute and
    the tail of the queue never got a turn."""
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        _item("s-b", "2026/FF5/Bravo", 1),
        _item("s-c", "2026/FF5/Charlie", 2),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-b"] = 5  # park the pass on Bravo
    seq, lane_a, lane_b, events = _build(selection, admin, project_rotation_seconds=5.0)

    seq.start()
    assert _wait_until(lambda: seq.current_slug == "s-b", timeout=3.0)

    # Alpha is already done this pass -- an ingest into it must NOT jump it
    # back ahead of Charlie, which has not run yet.
    for _ in range(20):
        seq.notify_change("Projects/2026/FF5/Alpha")
    time.sleep(0.1)
    assert seq.queue_slugs == ["s-c"]

    # A project that has NOT run yet is still promotable.
    seq.notify_change("Projects/2026/FF5/Charlie")
    time.sleep(0.05)
    assert seq.queue_slugs == ["s-c"]
    seq.stop()


# -- long lane A/B runs must not hold other folders paused (AUDIT_2 L-4) ----


def test_folders_paused_by_the_previous_turn_are_released_before_the_next_lanes():
    """project_rotation_seconds bounds only the lane C wait, so a 200 GB
    ingest can block inside lane A for hours. The only unpause sweep was the
    one between passes -- so projects 3..N stayed paused, i.e. lane C silently
    did not sync audio/GFX/AE/subs for them, for that entire time.

    Pinned to lane_c_pause_scheme="rotate" for the same reason as the stop-
    sweep test above: under the default scheme nothing is ever paused, so
    there is nothing to release -- but the release must still work for
    anyone who selects the old scheme."""
    order = []
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        _item("s-b", "2026/FF5/Bravo", 1),
        _item("s-c", "2026/FF5/Charlie", 2),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin(events=order)
    seq, lane_a, lane_b, events = _build(selection, admin, lane_c_pause_scheme="rotate")

    seq.start()
    assert _wait_until(lambda: "Projects/2026/FF5/Bravo" in lane_a.calls, timeout=3.0)
    seq.stop()

    # Alpha's turn paused Bravo and Charlie; both must be unpaused again
    # before Bravo's lane A starts, not merely at the end of the pass.
    bravo_lane_a = events.index(("lane_a", "Projects/2026/FF5/Bravo"))
    before = events[:bravo_lane_a]
    assert ("pause", "s-b", True) in before
    assert ("pause", "s-c", True) in before
    assert before.index(("pause", "s-c", False)) > before.index(("pause", "s-c", True))


def test_release_before_lanes_costs_nothing_when_no_folder_is_paused():
    """Each pause/unpause makes Syncthing commit its config and restart the
    folder, so the release must be scoped to what we actually paused."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq._release_paused_folders()
    assert admin.pause_calls == []


# -- expected_folder_slugs (AUDIT_2 L-6/UX-3 wiring) ------------------------


def test_expected_folder_slugs_exposes_the_live_selection():
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        {"slug": "s-bad", "rel_path": None, "position": 1, "active": True},
        _item("s-b", "2026/FF5/Bravo", 2),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    assert seq.expected_folder_slugs() == []  # nothing known before the first pass
    seq.start()
    assert _wait_until(lambda: seq.expected_folder_slugs(), timeout=3.0)
    slugs = seq.expected_folder_slugs()
    seq.stop()

    assert slugs == ["s-a", "s-b"]  # the invalid item never becomes a folder id


# -- rel_path containment (AUDIT_2 L-7) -------------------------------------


@pytest.mark.parametrize(
    "rel",
    ["../../../Windows/Temp/x", "2026/../../../evil", "\\evil", "/evil", "C:/evil", ".."],
)
def test_escaping_rel_paths_never_reach_a_lane(rel):
    """The same string becomes lane A's SOURCE path: `rclone copy C:\\
    nas:...` under the video filter would upload every video on the editor's
    C: drive to the NAS -- which lane A never deletes."""
    items = [{"slug": "s-a", "rel_path": rel, "position": 0, "active": True}]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    time.sleep(0.2)
    seq.stop()

    assert lane_a.calls == []
    assert lane_b.calls == []
    assert seq.expected_folder_slugs() == []


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


# -- one normalized rel_path everywhere (AUDIT_3 L-11) ----------------------


def test_a_trailing_slash_rel_path_still_builds_a_clean_subpath():
    """Every path the sequencer builds now comes from the same normalized,
    validated rel that repath.py agreed was safe -- so a dashboard rel with a
    trailing separator can't produce "Projects/2026/FF5/Alpha/" (which
    reaches lane A's source, the lane C accept path and _rel_to_slug)."""
    items = [{"slug": "s-a", "rel_path": "2026/FF5/Alpha/", "position": 0, "active": True}]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: lane_a.calls, timeout=3.0)
    seq.stop()

    assert lane_a.calls[0] == "Projects/2026/FF5/Alpha"
    assert seq.known_rels() == ["2026/FF5/Alpha"]
