"""Sequencer tests: fake lanes/admin/selection client, fast intervals, no
real sleeping beyond small polling waits -- in the style of
test_reporter.py's threaded fault-isolation tests."""

from __future__ import annotations

import tempfile
import threading
import time
import urllib.error
from pathlib import Path

import pytest

from ccsync_companion.sync.sequencer import (
    STATE_NO_SELECTION,
    STATE_PAUSED,
    STATE_STOPPED,
    Sequencer,
)
from ccsync_companion.sync.syncthing_admin import PARTIAL_IGNORE_LINES, STIGNORE_LINES


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
        # Slugs whose accept_folder() blows up where the real one does: in
        # the set_ignores that FOLLOWS the folder-config write.
        self.accept_raises = set()
        # Slugs whose set_ignores fails outright (a config write that
        # exceeds config_write_timeout is the documented trigger).
        self.ignore_raises = set()
        # What GET /rest/db/ignores reports per folder. A slug ABSENT from
        # this dict models the normal state -- a folder Syncthing has and
        # that is correctly filtered; tests opt in to the broken states
        # (None = no .stignore at all, [] = empty, a short list = partial).
        self.folder_ignores = {}
        self.get_ignores_calls = []
        self.get_ignores_raises = set()
        self.get_ignores_404 = set()
        self.status_by_slug = {}
        self.status_calls = []
        self.ignore_calls = []
        self.versioning_calls = []
        self.ignore_delete_calls = []
        # Slugs whose ensure_ignore_delete PATCH fails (a config write that
        # exceeds config_write_timeout, same as ignore_raises).
        self.ignore_delete_raises = set()
        self.completion_calls = []
        # slug -> needBytes the SERVER still needs from us (AUDIT_2 P5)
        self.completion_need_bytes = {}
        self.paused_state = {}
        self.my_id = "SELF-DEVICE"
        self.folder_devices = {}
        self.max_folder_concurrency_calls = []
        # Mirrors SyncthingAdmin._ignores_unconfirmed.
        self._ignores_unconfirmed = set()

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
        """Mirrors syncthing_admin.accept_folder's REAL ordering: the folder
        config is POSTed first (the /rest/db/ignores endpoint addresses an
        existing folder, so it cannot come first), then ignores, then the
        unpause.

        The fake used to raise BEFORE popping `pending`, unlike the real
        admin -- which is the only reason
        test_failed_accept_leaves_the_folder_paused passed: every later pass
        saw the folder still pending and re-entered the accept path instead
        of the release path the bug actually lives on (B14)."""
        self.accept_calls.append(
            {
                "folder_id": folder_id,
                "label": label,
                "local_path": local_path,
                "offered_by_device_id": offered_by_device_id,
            }
        )
        self._ignores_unconfirmed.add(folder_id)
        self.pending.pop(folder_id, None)   # the folder now EXISTS...
        self.paused_state[folder_id] = True  # ...paused, and unfiltered
        self.folder_ignores[folder_id] = None  # ...with no .stignore yet
        self.events.append(("accept", folder_id))
        if folder_id in self.accept_raises:
            raise RuntimeError("set_ignores timed out; folder left paused")
        self.set_ignores(folder_id, list(STIGNORE_LINES))
        self.set_folder_paused(folder_id, False)
        return {}

    def set_ignores(self, folder_id, lines):
        self.ignore_calls.append((folder_id, list(lines)))
        self.events.append(("ignores", folder_id))
        if folder_id in self.ignore_raises:
            raise RuntimeError("config write timed out")
        self.folder_ignores[folder_id] = list(lines)
        self._ignores_unconfirmed.discard(folder_id)
        return {}

    def get_ignores(self, folder_id):
        self.get_ignores_calls.append(folder_id)
        self.events.append(("get_ignores", folder_id))
        if folder_id in self.get_ignores_404:
            raise urllib.error.HTTPError("http://x", 404, "Not Found", None, None)
        if folder_id in self.get_ignores_raises:
            raise RuntimeError("syncthing unreachable")
        if folder_id not in self.folder_ignores:
            return {"ignore": list(STIGNORE_LINES), "expanded": []}
        return {"ignore": self.folder_ignores[folder_id], "expanded": []}

    def ignores_confirmed(self, folder_id):
        return folder_id not in self._ignores_unconfirmed

    def ensure_versioning(self, folder_id, folder=None):
        self.versioning_calls.append(folder_id)
        return True

    def ensure_ignore_delete(self, folder_id, folder=None):
        """delete-protection (2026-08-11): the per-turn retrofit that stops a
        folder applying a delete another device made."""
        self.ignore_delete_calls.append(folder_id)
        if folder_id in self.ignore_delete_raises:
            raise RuntimeError("config write timed out")
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


# local_root must EXIST. _clone_structure() refuses to mkdir anything under a
# tree that is not mounted (the external-SSD guard: on a Mac an absent
# /Volumes/<SSD> would have the whole project scaffolding built on the boot
# disk instead), so a sequencer pointed at a path nobody created reads as a
# disconnected drive and skips the clone. Nothing is ever written here -- the
# clone is either faked outright or short-circuits on the blank `remote`.
_FAKE_LOCAL_ROOT = str(Path(tempfile.gettempdir()) / "ccsync-tests-sequencer-root")
Path(_FAKE_LOCAL_ROOT).mkdir(parents=True, exist_ok=True)


def _cfg(**overrides):
    cfg = {
        "local_root": _FAKE_LOCAL_ROOT,
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
    assert call["local_path"] == str(Path(_FAKE_LOCAL_ROOT) / "Projects" / "2026/FF5/Alpha")
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
    # SYNC-116 (sweep 2026-09-04): the editor-facing sentence, not
    # "no selection (dashboard unreachable, no cache)".
    assert detail == "Waiting for the server: this computer has no plan saved yet"


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


def test_process_project_skips_item_with_null_slug(caplog):
    """The slug becomes the SYNCTHING FOLDER ID. `str(item.get("slug"))`
    turned a NULL slug into the literal id "None", so every pause/unpause/
    set_ignores/status call of that turn addressed a folder called "None" --
    and "None" then stuck around forever as a key in the bookkeeping dicts."""
    items = [{"slug": None, "rel_path": "2026/FF5/Alpha", "position": 0, "active": True}]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    with caplog.at_level("WARNING", logger="ccsync.sync.sequencer"):
        seq.start()
        time.sleep(0.2)
        seq.stop()

    assert lane_a.calls == []
    assert lane_b.calls == []
    assert admin.pause_calls == []
    assert admin.ignore_calls == []
    assert seq.expected_folder_slugs() == []
    assert seq.known_rels() == []
    assert any("slug=None" in r.getMessage() for r in caplog.records), caplog.records


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
    and offered every .braw/.mov original for the life of the install.

    Now runs against a FakeAdmin with the real accept ordering, so the folder
    really does leave `pending` on the failed accept: every pass after the
    first takes the "already accepted" path, which is where B14 lived. The
    ignores never land here (ignore_raises), so the folder must stay paused
    through every turn AND every leak-recovery sweep."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.pending = {"s-a": {"offeredBy": {"DEVICE-1": {}}}}
    admin.accept_raises.add("s-a")   # half-accept: folder exists, unfiltered
    admin.ignore_raises.add("s-a")   # ...and every retry of the ignores fails too
    seq, lane_a, lane_b, events = _build(selection, admin, sequencer_idle_seconds=0.02)

    seq.start()
    # Let several passes go by: the turn must never unpause it, and neither
    # may the leak-recovery sweeps that run between passes.
    assert _wait_until(lambda: len(lane_a.calls) >= 3, timeout=5.0)
    # Snapshot BEFORE stop(), whose own sweep is a separate concern.
    during_the_passes = list(admin.pause_calls)
    seq.stop()

    assert ("s-a", False) not in during_the_passes, during_the_passes
    assert admin.paused_state["s-a"] is True
    # The per-turn re-assert is the ONLY retry a half-accepted folder gets
    # (it has left pending_folders() for good), so it must keep trying.
    assert admin.ignore_calls, "nothing ever retried the ignores"
    # And the pass moved on rather than dying.
    assert lane_a.calls


def test_half_accepted_folder_is_only_released_once_its_ignores_land():
    """B14: accept_folder POSTs the folder config BEFORE set_ignores, so a
    failed set_ignores leaves a folder that exists, carries no .stignore and
    is gone from pending_folders(). The next pass then saw "not pending" and
    read that as "fine", discarded the latch and unpaused it. The release
    must wait for a set_ignores that actually returned."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.pending = {"s-a": {"offeredBy": {"DEVICE-1": {}}}}
    admin.accept_raises.add("s-a")  # only the accept fails; the retry succeeds
    seq, lane_a, lane_b, events = _build(selection, admin, sequencer_idle_seconds=0.02)

    seq.start()
    assert _wait_until(lambda: ("s-a", False) in admin.pause_calls, timeout=5.0)
    seq.stop()

    # The folder was never unpaused before the ignores landed.
    first_unpause = events.index(("pause", "s-a", False))
    first_ignores = events.index(("ignores", "s-a"))
    assert first_ignores < first_unpause, events[:first_unpause + 1]
    assert admin.ignores_confirmed("s-a")


def test_a_failed_ignores_reassert_never_unpauses_the_folder():
    """B5: _reassert_folder_policy caught every non-404 from set_ignores with
    a bare log.exception and returned normally, so _lane_c_turn could not
    tell and unpaused a `sendreceive` folder whose .stignore was not known to
    be in place -- lane C then indexes and offers every .braw/.mov original
    and the whole Proxy/ tree bidirectionally, duplicating lanes A/B and
    propagating any local video delete to the NAS and every other editor.

    A config write that merely exceeds config_write_timeout is enough; the
    codebase documents those routinely outlast the read timeout."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()  # nothing pending: accepted long ago
    admin.paused_state["s-a"] = True  # and left paused by the previous run
    admin.ignore_raises.add("s-a")
    # SYNC-6 (2026-08-14): the re-assert reads first, so the folder has to
    # actually BE missing its patterns for the failing write to be attempted.
    admin.folder_ignores["s-a"] = None
    seq, lane_a, lane_b, events = _build(selection, admin, sequencer_idle_seconds=0.02)

    seq.start()
    assert _wait_until(lambda: len(admin.ignore_calls) >= 3, timeout=5.0)
    during_the_passes = list(admin.pause_calls)
    seq.stop()

    assert ("s-a", False) not in during_the_passes, during_the_passes
    assert admin.paused_state["s-a"] is True
    # Fault isolation is intact: lanes A/B still ran, the loop did not die.
    assert lane_a.calls


# -- delete protection (2026-08-11, docs/delete-protection-ignoredelete.md) --
#
# The per-turn retrofit that lands ignoreDelete on folders accepted by an
# older companion or by hand: one PATCH on the first turn after the upgrade,
# silence after. Advisory, exactly like versioning -- a missing ignoreDelete
# is a delete-safety gap, not a lane-direction violation, so blocking the
# unpause on it would stop lane C for a folder whose ignores are fine.


def test_reassert_folder_policy_ensures_ignore_delete():
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    assert seq._reassert_folder_policy("s-a") is True
    assert admin.ignore_delete_calls == ["s-a"]


def test_a_failing_ignore_delete_does_not_block_the_unpause():
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    admin.ignore_delete_raises.add("s-a")
    admin.folder_ignores["s-a"] = None   # SYNC-6: read-first, so give it a reason to write
    seq, lane_a, lane_b, events = _build(selection, admin)

    assert seq._reassert_folder_policy("s-a") is True
    assert admin.ignore_calls == [("s-a", list(STIGNORE_LINES))]


def test_ignore_delete_404_is_not_configured_here_not_a_failure():
    """A 404 means the editor has not been offered that folder at all -- there
    is nothing to protect and nothing to run unfiltered."""
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    def not_here(folder_id, folder=None):
        raise urllib.error.HTTPError("http://x", 404, "Not Found", None, None)

    admin.ensure_ignore_delete = not_here

    assert seq._reassert_folder_policy("s-a") is True


def test_pending_folders_failure_is_fail_closed():
    """B14: "can't tell whether this folder needs accepting" used to return
    True, releasing a folder a previous turn had deliberately latched paused
    on the strength of one failed GET."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()

    def boom():
        raise RuntimeError("syncthing unreachable")

    admin.pending_folders = boom
    seq, lane_a, lane_b, events = _build(selection, admin, sequencer_idle_seconds=0.02)

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 2, timeout=5.0)
    during_the_passes = list(admin.pause_calls)
    seq.stop()

    assert ("s-a", False) not in during_the_passes, during_the_passes
    # Nothing is re-asserted on a folder whose state we could not read.
    assert admin.ignore_calls == []
    assert lane_a.calls


def test_a_clean_turn_clears_the_ignores_latch():
    """A latched slug is excluded from every leak-recovery unpause sweep, so
    the latch has to be released the moment a set_ignores actually lands --
    otherwise one bad pass strands the folder paused for the life of the
    process."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._ignores_unconfirmed.add("s-a")  # latched by an earlier failed pass

    seq.start()
    assert _wait_until(lambda: ("s-a", False) in admin.pause_calls, timeout=5.0)
    seq.stop()

    assert seq._ignores_unconfirmed == set()


def test_a_turn_repairs_the_ignores_and_versioning_of_a_folder_it_never_accepted():
    """AUDIT_2 L-3/P6/DEL-6: nothing in the codebase ever set ignores or
    versioning on a folder it did not itself accept, so a folder accepted by
    an older companion or by hand in the Syncthing GUI stayed un-ignored (and
    unversioned) forever.

    SYNC-6 (2026-08-14): the re-assert now READS the folder's .stignore first
    and writes only when a pattern is actually missing -- so this drives the
    hand-accepted folder (an empty .stignore) rather than the steady state.
    The steady state costing no write at all is pinned in
    test_sync_sequencer_policy.py."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()  # nothing pending: the folder was accepted long ago
    admin.folder_ignores["s-a"] = []   # ...by hand, with no patterns at all
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


# -- startup ignores verification ------------------------------------------
#
# Neither latch that protects a half-filtered folder survives the process, so
# a companion killed between accept_folder's config write and its set_ignores
# came back up knowing nothing and _unpause_all released a `sendreceive`
# folder with no .stignore -- lane C then offers every .braw/.mov original
# and the whole Proxy/ tree bidirectionally until that project's first turn.


def _first(events, wanted):
    """Index of `wanted` in the shared event list, or None."""
    return events.index(wanted) if wanted in events else None


def test_startup_verifies_ignores_and_releases_a_clean_folder():
    """A folder that verifies clean must proceed exactly as before: released
    by the startup leak-recovery sweep, not held back until its first turn."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    admin.paused_state["s-a"] = True  # left paused by a crashed previous run
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: ("s-a", False) in admin.pause_calls, timeout=3.0)
    seq.stop()

    assert admin.get_ignores_calls[0] == "s-a"
    # The GET came first, and the release happened on the STARTUP sweep --
    # before the first turn's re-assert, which is the pre-existing behaviour
    # this must not regress.
    assert _first(events, ("get_ignores", "s-a")) < _first(events, ("pause", "s-a", False))
    ignores_idx = _first(events, ("ignores", "s-a"))
    assert ignores_idx is None or _first(events, ("pause", "s-a", False)) < ignores_idx


def test_startup_leaves_a_folder_with_no_stignore_paused():
    """The exact restart gap: accept_folder POSTed the folder config, the
    process died before set_ignores, and the next launch's leak-recovery
    sweep would have unpaused an unfiltered sendreceive folder."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    admin.paused_state["s-a"] = True
    admin.folder_ignores["s-a"] = None  # folder exists, no .stignore at all
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: ("s-a", False) in admin.pause_calls, timeout=3.0)
    seq.stop()

    # Released only AFTER a set_ignores that actually landed -- never by the
    # startup sweep.
    assert _first(events, ("ignores", "s-a")) < _first(events, ("pause", "s-a", False))


def test_startup_leaves_a_folder_with_partial_ignores_paused():
    """A .stignore that predates a pattern the current build considers
    load-bearing is not "filtered enough": without the .partial pair (B12) a
    39 GB orphaned rclone partial is offered to every other editor."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    admin.paused_state["s-a"] = True
    admin.folder_ignores["s-a"] = [
        line for line in STIGNORE_LINES if line not in PARTIAL_IGNORE_LINES
    ]
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: ("s-a", False) in admin.pause_calls, timeout=3.0)
    seq.stop()

    assert _first(events, ("ignores", "s-a")) < _first(events, ("pause", "s-a", False))


def test_startup_ignores_fetch_error_is_fail_closed():
    """Same posture as _maybe_auto_accept: waiting one rotation for a folder
    whose filtering we could not read is cheap, putting an unfiltered
    sendreceive folder online is not."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    admin.paused_state["s-a"] = True
    admin.get_ignores_raises.add("s-a")
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: ("s-a", False) in admin.pause_calls, timeout=3.0)
    seq.stop()

    assert _first(events, ("ignores", "s-a")) < _first(events, ("pause", "s-a", False))


def test_startup_ignores_verification_is_a_bounded_one_get_per_folder():
    """One GET per selected folder AT STARTUP, before anything is released --
    not per pass.

    SYNC-6 (2026-08-14) added a per-TURN read as well, which REPLACED the
    unconditional per-turn .stignore rewrite: the steady-state cost of a turn
    is now a read and no config write, which is what the second assertion
    pins."""
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin, sequencer_idle_seconds=0.02)

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 6, timeout=5.0)
    seq.stop()

    assert admin.get_ignores_calls[:2] == ["s-a", "s-b"], admin.get_ignores_calls
    assert admin.ignore_calls == [], "a complete .stignore must never be rewritten"


@pytest.mark.parametrize(
    "fetched, expect_latched",
    [
        (None, True),                                   # no .stignore at all
        ([], True),                                     # empty .stignore
        (["(?i)*.braw"], True),                         # nowhere near complete
        (list(STIGNORE_LINES), False),                  # exactly right
        (list(STIGNORE_LINES) + ["(?i)*.tmp"], False),  # extra lines are fine
    ],
)
def test_startup_verification_latch_matrix(fetched, expect_latched):
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    admin.folder_ignores["s-a"] = fetched
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq._verify_startup_ignores(items)

    assert (seq._ignores_unconfirmed == {"s-a"}) is expect_latched


def test_startup_verification_stays_quiet_about_folders_not_configured_locally():
    """A 404 means the editor has not been offered that folder yet: there is
    nothing to run unfiltered, and latching it would put a WARNING per
    selected-but-unaccepted folder in the log on every launch."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    admin.get_ignores_404.add("s-a")
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq._verify_startup_ignores(items)

    assert seq._ignores_unconfirmed == set()


def test_startup_verification_skips_invalid_items_and_survives_an_old_admin():
    items = [{"slug": None, "rel_path": "2026/FF5/Alpha", "position": 0, "active": True}]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq._verify_startup_ignores(items)
    assert admin.get_ignores_calls == []      # never addresses a folder id "None"
    assert seq._ignores_unconfirmed == set()

    admin.get_ignores = None                  # an admin double predating the getter
    seq._verify_startup_ignores([_item("s-a", "2026/FF5/Alpha", 0)])
    assert seq._ignores_unconfirmed == set()


# -- bookkeeping is bounded ------------------------------------------------


def test_bookkeeping_is_pruned_when_a_project_leaves_the_selection():
    """These are keyed by slug and were append-only, so every project an
    editor ever ticked stayed in memory for the life of the process -- and a
    stale _ignores_unconfirmed entry PERMANENTLY excluded that slug from
    every leak-recovery unpause sweep, so re-ticking the project left its
    folder stuck paused with nothing left to release it."""
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq._ignores_unconfirmed = {"s-gone", "s-a"}
    seq._clone_ages = {"s-gone": 3, "s-a": 2}
    seq._orphan_ages = {"s-gone": 3, "s-a": 2}

    seq._update_known_selection([_item("s-a", "2026/FF5/Alpha", 0)])

    assert seq._ignores_unconfirmed == {"s-a"}
    assert set(seq._clone_ages) == {"s-a"}
    assert set(seq._orphan_ages) == {"s-a"}

    # ...and the de-selected slug is no longer held back from the sweeps.
    seq._unpause_all([
        _item("s-gone", "2026/FF5/Gone", 0),
        _item("s-a", "2026/FF5/Alpha", 1),
    ])
    assert ("s-gone", False) in admin.pause_calls
    assert ("s-a", False) not in admin.pause_calls


def test_a_folder_removed_from_syncthing_stops_being_tracked_as_paused():
    """_paused_by_us is the only record of a folder this sequencer paused, so
    it is deliberately NOT pruned against the selection -- but a folder that
    no longer exists in Syncthing cannot be left paused, and retrying it on
    every project boundary forever is pure noise."""
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    def gone(folder_id, paused):
        raise urllib.error.HTTPError("http://x", 404, "Not Found", None, None)

    admin.set_folder_paused = gone
    seq._paused_by_us.add("s-gone")
    seq._release_paused_folders()

    assert seq._paused_by_us == set()


# -- SYNC-2: the sweeps must not release what the verification skipped ------
#
# _verify_startup_ignores skips items _item_is_valid rejects, but _unpause_all
# swept by RAW slug -- so the one folder class nothing ever checked was also
# the one released unconditionally. The dashboard ships such rows routinely:
# fetch_selections is a LEFT JOIN, so an archived project arrives as
# {"slug": ..., "rel_path": None, "active": False} -- a real, possibly
# unfiltered Syncthing folder with an unusable selection row.


def _archived(slug):
    """What the dashboard's LEFT JOIN emits for a project record that is
    gone: a live slug with no rel_path."""
    return {"slug": slug, "rel_path": None, "position": 0, "active": False}


def test_unpause_all_never_releases_an_item_it_cannot_validate():
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq._unpause_all([_archived("s-archived"), _item("s-a", "2026/FF5/Alpha", 1)])

    assert ("s-a", False) in admin.pause_calls
    assert ("s-archived", False) not in admin.pause_calls, admin.pause_calls


def test_an_archived_project_keeps_its_ignores_latch():
    """The full SYNC-2 sequence: a folder is correctly latched paused after a
    set_ignores timeout, an admin then archives the project, and the latch --
    pruned against the VALID slugs only -- was erased, so the next sweep
    released an unfiltered sendreceive folder (the L-3 outcome)."""
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._ignores_unconfirmed = {"s-a"}

    seq._update_known_selection([_archived("s-a")])
    assert seq._ignores_unconfirmed == {"s-a"}

    seq._unpause_all([_archived("s-a")])
    assert admin.pause_calls == []

    # ...and it still drains when the project leaves the selection entirely,
    # which is what the pruning was written for.
    seq._update_known_selection([])
    assert seq._ignores_unconfirmed == set()


# -- SYNC-8: a stop inside the startup verification ------------------------


def test_a_stop_during_startup_verification_latches_the_folders_it_never_reached():
    """Verification is one GET per folder at up to the read timeout each, so
    a quit/sign-out/config-reload lands inside it routinely -- and both sweeps
    that follow run over the WHOLE selection. Folders 2..N were never checked,
    so they must not be released."""
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        _item("s-b", "2026/FF5/Bravo", 1),
        _item("s-c", "2026/FF5/Charlie", 2),
    ]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()

    seq, lane_a, lane_b, events = _build(selection, admin)

    def stop_after_the_first(folder_id):
        admin.get_ignores_calls.append(folder_id)
        seq._stop_event.set()   # the quit arrives mid-verification
        return {"ignore": list(STIGNORE_LINES), "expanded": []}

    admin.get_ignores = stop_after_the_first

    seq._verify_startup_ignores(items)

    assert admin.get_ignores_calls == ["s-a"]
    assert seq._ignores_unconfirmed == {"s-b", "s-c"}

    seq._unpause_all(items)
    assert ("s-b", False) not in admin.pause_calls
    assert ("s-c", False) not in admin.pause_calls


def test_a_stop_before_the_verification_starts_latches_everything():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._stop_event.set()

    seq._verify_startup_ignores(items)

    assert admin.get_ignores_calls == []
    assert seq._ignores_unconfirmed == {"s-a", "s-b"}


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


# -- the tree has to actually be mounted (root_guard.py's defence in depth) --


def _clone_spy_sequencer(local_root, calls):
    admin = FakeAdmin()
    selection = FakeSelectionClient([])
    return Sequencer(
        FakeLane("lane_a", admin.events), FakeLane("lane_b", admin.events),
        admin, selection, _cfg(local_root=local_root),
        folder_status_poll_seconds=0.02,
        clone_tree_fn=lambda **kwargs: calls.append(kwargs) or 0,
    )


def test_the_structure_clone_refuses_when_local_root_is_not_mounted(tmp_path):
    """clone_directory_tree ends in a local `mkdir -p` loop. Against an
    absent local_root -- a macOS editor's external SSD unplugged -- it would
    build the whole project scaffolding on the machine's internal disk, at
    exactly the path lane B then syncs into."""
    calls: list[dict] = []
    seq = _clone_spy_sequencer(str(tmp_path / "not-mounted"), calls)

    seq._clone_structure("Projects/2026/FF5/Alpha")

    assert calls == []


def test_the_structure_clone_runs_when_local_root_is_there(tmp_path):
    calls: list[dict] = []
    root = tmp_path / "mounted"
    root.mkdir()
    seq = _clone_spy_sequencer(str(root), calls)

    seq._clone_structure("Projects/2026/FF5/Alpha")

    assert len(calls) == 1
    assert calls[0]["subpath"] == "Projects/2026/FF5/Alpha"


def test_a_blank_local_root_never_clones(tmp_path):
    calls: list[dict] = []
    seq = _clone_spy_sequencer("", calls)
    seq._clone_structure("Projects/2026/FF5/Alpha")
    assert calls == []


# -- the 2026-08-21 hunt ----------------------------------------------------


class _StatusLane(FakeLane):
    """A lane that answers with a LaneStatus, like the real adapters, and
    reports what its last run moved."""

    def __init__(self, name, events, state, moved=0):
        super().__init__(name, events)
        self.state = state
        self.moved = moved

    def run_once(self, subpath=None):
        super().run_once(subpath)
        from ccsync_companion.sync.base import LaneStatus

        return LaneStatus(name=self.name, state=self.state)

    def last_run_moved(self):
        return self.moved


def test_the_lane_c_wait_is_a_short_settle_when_nothing_is_being_paused():
    """ops-efficiency-3: the 600 s wait is load-bearing only under the
    "rotate" scheme, where the next project's turn would pause this folder
    mid-transfer. With the default scheme Syncthing paces lane C itself, and
    the wait just parked the whole sequencer -- so lane B proxies for every
    project behind a big backlog arrived up to N x 600 s late."""
    admin = FakeAdmin()
    seq, _a, _b, _e = _build(FakeSelectionClient(selection=[]), admin,
                             project_rotation_seconds=600.0)
    assert seq._lane_c_wait_budget() == 30.0

    rotating, _a2, _b2, _e2 = _build(
        FakeSelectionClient(selection=[]), FakeAdmin(),
        project_rotation_seconds=600.0, lane_c_pause_scheme="rotate")
    assert rotating._lane_c_wait_budget() == 600.0


def test_a_folder_that_never_settles_does_not_hold_the_whole_rotation():
    clock = {"now": 0.0}

    def fake_now():
        clock["now"] += 5.0
        return clock["now"]

    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 7          # never reaches zero
    lane_a = FakeLane("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, FakeSelectionClient(selection=[]),
        _cfg(project_rotation_seconds=600.0), folder_status_poll_seconds=0.001,
        now=fake_now,
    )
    seq._wait_for_folder_sync("s-a", ["s-a"])
    # 30 s of settle at 5 s a tick, not 600.
    assert len(admin.status_calls) <= 8


def test_the_idle_wait_backs_off_only_while_nothing_is_moving():
    """ops-efficiency-2: a steady-state pass costs 3 rclone processes, 2
    recursive SFTP listings and 3 local walks per project, every 60 s, to
    discover that nothing changed."""
    seq, _a, _b, _e = _build(FakeSelectionClient(selection=[]), FakeAdmin(),
                             sequencer_idle_seconds=60.0)
    assert seq._idle_seconds() == 60.0
    seq._note_pass_finished()
    assert seq._idle_seconds() == 120.0
    seq._note_pass_finished()
    assert seq._idle_seconds() == 300.0
    seq._note_pass_finished()
    assert seq._idle_seconds() == 300.0, "the backoff is capped"

    # A pass that actually moved something is back to the normal cadence...
    seq._pass_moved = 3
    seq._note_pass_finished()
    assert seq._idle_seconds() == 60.0

    # ...and so is a tray trigger, a watcher event or a selection change.
    seq._pass_moved = 0
    seq._note_pass_finished()
    seq._note_pass_finished()
    assert seq._idle_seconds() > 60.0
    seq.trigger_pass_now()
    assert seq._idle_seconds() == 60.0


def test_a_selection_change_ends_the_backoff():
    seq, _a, _b, _e = _build(FakeSelectionClient(selection=[]), FakeAdmin(),
                             sequencer_idle_seconds=60.0)
    seq._note_pass_finished()
    assert seq._idle_seconds() == 120.0
    seq._update_known_selection([_item("s-a", "2026/FF5/Alpha", 0)])
    assert seq._idle_seconds() == 60.0


def test_both_lanes_failing_ends_the_pass_instead_of_asking_every_project():
    """ops-efficiency-4: a laptop off the tailnet spends contimeout x retries
    per lane per project -- ~45 minutes of doomed subprocesses for ten
    projects, then starts again 60 s later."""
    from ccsync_companion.sync.base import STATE_ERROR

    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1),
             _item("s-c", "2026/FF5/Charlie", 2)]
    admin = FakeAdmin()
    lane_a = _StatusLane("lane_a", admin.events, STATE_ERROR)
    lane_b = _StatusLane("lane_b", admin.events, STATE_ERROR)
    seq = Sequencer(
        lane_a, lane_b, admin, FakeSelectionClient(selection=items),
        _cfg(), folder_status_poll_seconds=0.02,
    )
    seq._update_known_selection(items)
    seq._run_pass(items)

    assert lane_a.calls == ["Projects/2026/FF5/Alpha"]
    assert lane_b.calls == ["Projects/2026/FF5/Alpha"]


def test_one_failing_lane_is_not_an_offline_machine():
    from ccsync_companion.sync.base import STATE_ERROR, STATE_IDLE

    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    admin = FakeAdmin()
    lane_a = _StatusLane("lane_a", admin.events, STATE_IDLE)
    lane_b = _StatusLane("lane_b", admin.events, STATE_ERROR)
    seq = Sequencer(
        lane_a, lane_b, admin, FakeSelectionClient(selection=items),
        _cfg(), folder_status_poll_seconds=0.02,
    )
    seq._update_known_selection(items)
    seq._run_pass(items)

    assert len(lane_a.calls) == 2


def test_the_halt_scope_includes_the_shared_asset_folders():
    """sync-safety-2: a fleet halt pressed over a mass rename in the B-roll
    archive left the archive, music and LUT folders syncing on every machine
    while every tray said nothing was."""
    class _Shared:
        def folder_ids(self):
            return ["ccsync-assets-luts", "ccsync-assets-broll"]

        def reconcile(self):
            return {}

    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    admin = FakeAdmin()
    seq = Sequencer(
        FakeLane("lane_a", admin.events), FakeLane("lane_b", admin.events),
        admin, FakeSelectionClient(selection=items), _cfg(),
        shared_folders=_Shared(),
    )
    seq._update_known_selection(items)
    assert seq.halt_folder_ids() == ["s-a", "ccsync-assets-luts", "ccsync-assets-broll"]
    # ...and lane C's "am I behind" list is deliberately NOT widened.
    assert seq.expected_folder_slugs() == ["s-a"]


def test_releasing_a_halt_keeps_an_unfiltered_folder_paused():
    """sync-safety-4: the halt's release PATCHed paused:false onto every
    folder it had paused, including one deliberately left paused because its
    .stignore never landed -- putting an unfiltered sendreceive folder
    online."""
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    admin = FakeAdmin()
    admin.paused_state = {"s-a": True, "s-b": True}
    admin._ignores_unconfirmed.add("s-b")
    seq, _a, _b, _e = _build(FakeSelectionClient(selection=items), admin)
    seq._update_known_selection(items)

    seq.release_for_halt()

    released = [fid for fid, paused in admin.pause_calls if paused is False]
    assert "s-a" in released
    assert "s-b" not in released


def test_each_pass_asks_lane_b_to_check_the_remote_root():
    """sync-safety-5: in managed mode every pass names a project subpath, so
    the breaker's marker-directory rule never ran at all."""
    probes = []

    class _LaneB(FakeLane):
        def check_remote_root(self):
            probes.append(1)
            return True

    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    admin = FakeAdmin()
    seq = Sequencer(
        FakeLane("lane_a", admin.events), _LaneB("lane_b", admin.events),
        admin, FakeSelectionClient(selection=items), _cfg(),
    )
    seq.start()
    assert _wait_until(lambda: probes)
    seq.stop()
    assert probes


# -- borrowed folders (SHARED_FOLDERS_PLAN.md WP2) --------------------------


def _inc(subpath, lender_slug, sub_rel, covered=False):
    lender_rel = subpath[: -(len(sub_rel) + 1)]
    return {"subpath": subpath, "sub_rel": sub_rel, "lender_slug": lender_slug,
            "lender_label": lender_rel, "covered": covered}


def _borrower_item(includes):
    item = _item("s-borrower", "2026/FF5/Elections", 0)
    item["includes"] = includes
    return item


def test_include_runs_lanes_after_the_projects_own(monkeypatch):
    items = [_borrower_item([
        _inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
             "s-lender", "Interviewees/Aha Chu"),
    ])]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    borrowed = "Projects/2026/FF5/Civil Defence/Interviewees/Aha Chu"
    assert _wait_until(lambda: ("lane_a", borrowed) in events)
    seq.stop()

    own = "Projects/2026/FF5/Elections"
    a_calls = [e for e in events if e[0] == "lane_a"]
    assert a_calls.index(("lane_a", own)) < a_calls.index(("lane_a", borrowed))
    assert ("lane_b", borrowed) in events


def test_invalid_includes_are_dropped_never_widened():
    bad = [
        {"subpath": "../../evil", "sub_rel": "evil", "lender_slug": "s-x"},
        {"subpath": "2026/FF5/CD/Proxy", "sub_rel": "Proxy", "lender_slug": "s-x"},
        {"subpath": "2026/FF5/CD/Sub", "sub_rel": "Other", "lender_slug": "s-x"},   # tail mismatch
        {"subpath": "just-one-segment", "sub_rel": "just-one-segment", "lender_slug": "s-x"},
        {"subpath": "2026/FF5/CD/Sub", "sub_rel": "Sub", "lender_slug": ""},
        "not a dict",
    ]
    items = [_borrower_item(bad)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._update_known_selection(items)
    assert seq._borrowed_includes("s-borrower") == []
    assert seq.borrowed_lenders() == {}


def test_include_under_a_selected_rel_is_skipped():
    inc = _inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
               "s-lender", "Interviewees/Aha Chu")
    items = [
        _borrower_item([inc]),
        _item("s-lender", "2026/FF5/Civil Defence", 1),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._update_known_selection(items)
    assert seq._borrowed_includes("s-borrower") == []
    # and a covered-marked include is skipped without a warning even when
    # the lender's rel spelling would not match
    covered = _borrower_item([_inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
                                   "s-lender", "Interviewees/Aha Chu", covered=True)])
    seq._update_known_selection([covered])
    assert seq._borrowed_includes("s-borrower") == []


def test_nested_includes_longest_prefix_wins():
    outer = _inc("2026/FF5/Civil Defence/Interviewees", "s-lender", "Interviewees")
    inner = _inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
                 "s-lender", "Interviewees/Aha Chu")
    items = [_borrower_item([outer, inner])]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._update_known_selection(items)
    subs = [i["subpath"] for i in seq._borrowed_includes("s-borrower")]
    assert subs == ["2026/FF5/Civil Defence/Interviewees"]


def test_known_rels_carries_borrowed_but_rel_to_slug_does_not():
    items = [_borrower_item([
        _inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
             "s-lender", "Interviewees/Aha Chu"),
    ])]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._update_known_selection(items)

    borrowed = "2026/FF5/Civil Defence/Interviewees/Aha Chu"
    assert borrowed in seq.known_rels()
    # rel_to_slug feeds _selected_project_rels (manifest + proxy scan scope):
    # the borrowed rel must NOT be in it
    assert borrowed not in seq.rel_to_slug
    assert seq.rel_to_slug_with_borrowed()[borrowed] == "s-borrower"


def test_halt_folder_ids_includes_borrowed_lenders():
    items = [_borrower_item([
        _inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
             "s-lender", "Interviewees/Aha Chu"),
    ])]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._update_known_selection(items)
    assert "s-lender" in seq.halt_folder_ids()
    # a SELECTED lender is already in the list via the selection itself
    items2 = [_borrower_item([]), _item("s-lender", "2026/FF5/Civil Defence", 1)]
    seq._update_known_selection(items2)
    assert seq.halt_folder_ids().count("s-lender") == 1


def test_borrowed_bookkeeping_pruned_with_the_borrower():
    items = [_borrower_item([
        _inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
             "s-lender", "Interviewees/Aha Chu"),
    ])]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._update_known_selection(items)
    seq._clone_ages["s-borrower::2026/FF5/Civil Defence/Interviewees/Aha Chu"] = 1
    seq._clone_ages["s-borrower"] = 1
    seq._update_known_selection([_item("s-other", "2026/FF5/Other", 0)])
    assert seq._clone_ages == {}


def test_notify_change_in_a_borrowed_dir_promotes_the_borrower():
    items = [_borrower_item([
        _inc("2026/FF5/Civil Defence/Interviewees/Aha Chu",
             "s-lender", "Interviewees/Aha Chu"),
    ])]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._update_known_selection(items)
    seq._wake_event.clear()
    # lane A's watchdog attributes a write in the borrowed dir to the
    # borrowed rel (longest known rel); the promotion must resolve it to
    # the BORROWER, whose turn runs the borrowed subpath
    seq.notify_change("Projects/2026/FF5/Civil Defence/Interviewees/Aha Chu")
    assert seq._wake_event.is_set()


def test_a_selected_lender_with_restricted_ignores_is_rewritten_before_unpause():
    """SHARED_FOLDERS_PLAN.md §3.3: the editor ticks a lender they were
    borrowing from. Its .stignore is still the borrowed-folder restriction,
    which PASSES the missing-lines superset test -- so without the
    is_restricted check the folder would come online syncing only the
    borrowed subtree while the tick promises the whole project."""
    from ccsync_companion.sync.syncthing_admin import restricted_ignore_lines

    items = [_item("s-lender", "2026/FF5/Civil Defence", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.folder_ignores["s-lender"] = restricted_ignore_lines(
        ["Interviewees/Aha Chu"])
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: ("s-lender", list(STIGNORE_LINES))
                       in [(c[0], c[1]) for c in admin.ignore_calls])
    seq.stop()
    assert admin.folder_ignores["s-lender"] == list(STIGNORE_LINES)


def test_startup_verify_latches_a_restricted_selected_folder():
    from ccsync_companion.sync.syncthing_admin import restricted_ignore_lines

    items = [_item("s-lender", "2026/FF5/Civil Defence", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.folder_ignores["s-lender"] = restricted_ignore_lines(
        ["Interviewees/Aha Chu"])
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq._verify_startup_ignores(items)
    assert seq._ignores_unconfirmed_for("s-lender")


def test_unconfirmed_slugs_publishes_the_ignores_latch():
    """SYNC-5 (resilience sweep 2026-08-28): the latch was reported nowhere.
    A folder deliberately kept paused because its .stignore never landed
    carried nothing on lane C, indefinitely -- one project that never syncs,
    green forever. This is the read side lane C and the report use."""
    admin = FakeAdmin()
    seq, _lane_a, _lane_b, _events = _build(FakeSelectionClient([]), admin)
    with seq._lock:
        seq._slug_to_item = {"s-a": _item("s-a", "2026/FF5/Alpha", 0),
                             "s-b": _item("s-b", "2026/FF5/Beta", 1)}
    assert seq.unconfirmed_slugs() == []

    seq._ignores_unconfirmed.add("s-b")
    assert seq.unconfirmed_slugs() == ["s-b"]

    # The admin's half-accepted-folder record counts too (B14), and a probe
    # that raises must not take the read down with it.
    admin._ignores_unconfirmed.add("s-a")
    assert seq.unconfirmed_slugs() == ["s-a", "s-b"]


def test_unconfirmed_slugs_never_raises_when_the_predicate_fails():
    admin = FakeAdmin()
    seq, _a, _b, _e = _build(FakeSelectionClient([]), admin)
    with seq._lock:
        seq._slug_to_item = {"s-a": _item("s-a", "2026/FF5/Alpha", 0)}

    def _boom(slug):
        raise RuntimeError("no")

    admin.ignores_confirmed = _boom
    assert seq.unconfirmed_slugs() == []


# -- SYS-2: the loop survives a bad pass, and says when it does not --------


def test_a_failing_pass_costs_one_pass_not_the_thread():
    """The whole of SYS-2's first half: before the sweep an OSError out of a
    pass (a mapped P: dropping mid-run) killed the thread with _state frozen
    at its last value, the reporter kept posting that state every 30 s, and
    the fleet grid showed a healthy machine that had not synced since."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    real = seq._run_pass
    calls: list[int] = []

    def flaky(sel):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("P:\\ went away mid-pass")
        return real(sel)

    seq._run_pass = flaky

    seq.start()
    assert _wait_until(lambda: len(calls) >= 2, timeout=5.0)
    assert seq._thread.is_alive()
    seq.stop()

    assert lane_a.calls, "the pass after the failure never ran"
    assert seq.loop_failures() == 1
    assert seq.last_error() == "OSError: P:\\ went away mid-pass"


def test_the_heartbeat_advances_while_the_loop_runs():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    seq, lane_a, _b, _e = _build(FakeSelectionClient(selection=items), FakeAdmin())

    seq.start()
    first = seq._heartbeat
    assert _wait_until(lambda: seq._heartbeat > first, timeout=5.0)
    seq.stop()

    # A stopped sequencer is not a wedged one: the watchdog must read 0.0 for
    # it, or every sign-out would look like the fault it exists to recover.
    assert seq.seconds_since_heartbeat() == 0.0
    assert seq.thread_died() is False


def test_a_paused_sequencer_reads_as_no_heartbeat_question_at_all():
    """_park_paused blocks for as long as the editor leaves sync paused;
    restarting it over that would be the watchdog inventing an outage."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    seq, _a, _b, _e = _build(FakeSelectionClient(selection=items), FakeAdmin())

    seq.start()
    seq.pause()
    assert _wait_until(lambda: seq.state == STATE_PAUSED, timeout=5.0)
    assert seq.seconds_since_heartbeat() == 0.0
    assert seq.thread_died() is False
    seq.stop()


def test_a_thread_that_dies_anyway_says_why_and_leaves_state_stopped():
    """The scaffolding around the loop can still fail. When it does, _state
    must reach STOPPED (it is in a finally now, not after the while) and the
    exception must be readable -- "restarted for no stated reason" is the
    shape this sweep exists to stop shipping."""
    seq, _a, _b, _e = _build(FakeSelectionClient(selection=[]), FakeAdmin())

    def boom():
        raise RuntimeError("startup unpause exploded")

    seq._startup_unpause = boom

    seq.start()
    assert _wait_until(lambda: not seq._thread.is_alive(), timeout=5.0)

    assert seq.state == STATE_STOPPED
    assert seq.thread_died() is True
    assert seq.last_error() == "RuntimeError: startup unpause exploded"


def test_a_failing_pass_writes_a_crash_report(monkeypatch):
    """A swallowed exception never reaches threading.excepthook, so the local
    crash file crash_report.py exists to write would not be written at all."""
    from ccsync_companion import crash_report

    seen: list[str] = []
    monkeypatch.setattr(crash_report, "handle",
                        lambda *a, **kw: seen.append(kw.get("thread", "?")))

    seq, _a, _b, _e = _build(FakeSelectionClient(selection=[]), FakeAdmin())

    def boom(*_a, **_k):
        raise OSError("selection read failed")

    seq._selection_get = boom

    seq.start()
    assert _wait_until(lambda: seen, timeout=5.0)
    seq.stop()

    assert seen[0] == "ccsync-sequencer"


# -- the bounded lane B join (SYNC-1, resilience sweep 2026-08-28, CR-91) ---


class _WedgedLaneB:
    """A lane B whose rclone hangs on a local read (the MAC-12 condition).
    It only ends when something aborts it."""

    def __init__(self) -> None:
        self.name = "lane_b"
        self.released = threading.Event()
        self.aborts: list = []
        self.stopped = False

    def run_once(self, subpath=None, max_duration_seconds=None):
        self.released.wait(10)

    def abort_run(self, why, seconds=0):
        self.aborts.append(why)
        self.seconds = seconds
        self.released.set()
        return True

    def stop(self):
        # Recorded so the test can prove the sequencer does NOT reach for it:
        # stop() latches the lane off for its whole thread generation.
        self.stopped = True

    def last_run_moved(self):
        return 0


def _lanes_ab_sequencer(lane_b, **cfg_overrides):
    admin = FakeAdmin()
    return Sequencer(
        FakeLane("lane_a", admin.events), lane_b, admin,
        FakeSelectionClient([]), _cfg(**cfg_overrides),
        folder_status_poll_seconds=0.02,
    )


def test_a_wedged_lane_b_does_not_freeze_the_project_rotation(monkeypatch):
    """CR-91: `thread.join()` had no timeout, for the stated (correct) reason
    that an un-joined lane B would write into a directory the next project's
    repath moves. A lane B whose child wedged therefore held the rotation
    forever -- lane A finishing released nothing."""
    from ccsync_companion.sync import sequencer as sequencer_mod

    monkeypatch.setattr(sequencer_mod, "lane_b_join_timeout", lambda budget: 0.05)
    monkeypatch.setattr(sequencer_mod, "LANE_B_ABORT_JOIN_SECONDS", 1.0)

    lane_b = _WedgedLaneB()
    seq = _lanes_ab_sequencer(lane_b)
    started = time.monotonic()
    seq._run_lanes_a_and_b("Projects/2026/FF5/Alpha", 5.0)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, "the rotation must not wait on a wedged lane B"
    assert lane_b.aborts, "the lane's rclone child must be ended"
    assert "did not finish" in lane_b.aborts[0]
    assert "Projects/2026/FF5/Alpha" in lane_b.aborts[0]
    assert lane_b.stopped is False, (
        "stop() would latch lane B off for the whole thread generation")
    assert lane_b.seconds >= 0, "the stall record gets the join timeout"


def test_the_bounded_join_names_the_wedged_lane_in_the_log(monkeypatch, caplog):
    from ccsync_companion.sync import sequencer as sequencer_mod

    monkeypatch.setattr(sequencer_mod, "lane_b_join_timeout", lambda budget: 0.05)
    monkeypatch.setattr(sequencer_mod, "LANE_B_ABORT_JOIN_SECONDS", 1.0)
    lane_b = _WedgedLaneB()
    seq = _lanes_ab_sequencer(lane_b)

    with caplog.at_level("WARNING", logger="ccsync.sync.sequencer"):
        seq._run_lanes_a_and_b("Projects/2026/FF5/Alpha", 5.0)

    assert any("lane B did not finish" in r.getMessage() for r in caplog.records)


def test_a_healthy_lane_b_is_joined_exactly_as_before(monkeypatch):
    """The bound must not change the normal path: both lanes run, both are
    joined, and nothing is aborted."""
    from ccsync_companion.sync import sequencer as sequencer_mod

    aborts: list = []

    class _QuickLaneB(FakeLane):
        def abort_run(self, why, seconds=0):
            aborts.append(why)
            return True

    admin = FakeAdmin()
    lane_b = _QuickLaneB("lane_b", admin.events)
    seq = Sequencer(
        FakeLane("lane_a", admin.events), lane_b, admin,
        FakeSelectionClient([]), _cfg(), folder_status_poll_seconds=0.02,
    )
    seq._run_lanes_a_and_b("Projects/2026/FF5/Alpha", 5.0)

    assert lane_b.calls == ["Projects/2026/FF5/Alpha"]
    assert not aborts


def test_the_join_timeout_sits_above_the_lanes_own_stall_ceiling():
    """Ordering matters: the lane kills its own wedged child first, and this
    join is the backstop. A timeout BELOW the lane's ceiling would cut short
    the legitimate case -- a SOFT cutoff letting a 40 GB original land."""
    from ccsync_companion.sync import rclone_lane
    from ccsync_companion.sync.sequencer import lane_b_join_timeout

    assert lane_b_join_timeout(600) > rclone_lane.hard_ceiling_seconds(600)
    # A missing budget still yields a real bound, never zero or infinity.
    assert lane_b_join_timeout(None) > 0


# -- wave 3 (2026-09-04): the machine says what it knows ----------------------
#
# SYNC-107 / SYNC-101 / SYNC-102. Every value here was already computed
# somewhere in this module and readable nowhere: the plan, the shared folders
# that failed, and the projects the server renamed under the editor's feet.


class _PlanLane(FakeLane):
    def __init__(self, name, events, state="syncing"):
        super().__init__(name, events)
        self._state = state

    def status(self):
        from ccsync_companion.sync.base import LaneStatus

        return LaneStatus(name=self.name, state=self._state)


def _plan_sequencer(tmp_path, selection, **cfg_overrides):
    admin = FakeAdmin()
    client = FakeSelectionClient(selection)
    lane_a = _PlanLane("lane_a", admin.events, state="syncing")
    lane_b = _PlanLane("lane_b", admin.events, state="idle")
    seq = Sequencer(
        lane_a, lane_b, admin, client,
        _cfg(log_path=str(tmp_path / "companion.log"), **cfg_overrides),
        folder_status_poll_seconds=0.02,
    )
    seq._update_known_selection(selection)
    return seq, admin


def _upload_only(slug, rel, position):
    item = _item(slug, rel, position)
    item["sync_mode"] = "upload_only"
    return item


def test_project_status_lists_the_plan_with_its_modes(tmp_path):
    """SYNC-107: the only enumeration of this machine's plan an editor could
    see was the stack of destructive buttons in ADVANCED, and "upload only"
    appeared nowhere except inside the label of the one that deletes it."""
    selection = [_item("s1", "2026/FF5/Animals", 0, label="Animals"),
                 _upload_only("s2", "2026/FF5/Cards", 1)]
    seq, _admin = _plan_sequencer(tmp_path, selection)
    with seq._lock:
        seq._current_slug = "s1"
        seq._current_position, seq._current_total = 1, 2
        seq._queue_slugs = ["s2"]
        seq._state = "running"

    rows = seq.project_status()
    assert [r["slug"] for r in rows] == ["s1", "s2"]
    assert rows[0]["label"] == "Animals"
    assert rows[0]["mode"] == "full" and rows[0]["state"] == "syncing"
    assert rows[0]["lanes"] == {"A": "syncing", "B": "idle", "C": "syncing"}
    assert rows[1]["mode"] == "upload_only" and rows[1]["state"] == "waiting"
    # The thing an upload-only editor has no other way to learn.
    assert "Proxies do not come down" in rows[1]["detail"]
    assert rows[1]["lanes"] == {"A": "waiting", "B": "off", "C": "off"}
    assert all("—" not in (r["detail"] or "") for r in rows)


def test_project_status_says_what_a_project_is_waiting_for(tmp_path):
    selection = [_item("s1", "2026/FF5/Animals", 0)]
    seq, _admin = _plan_sequencer(tmp_path, selection)
    seq._ignores_unconfirmed.add("s1")
    (row,) = seq.project_status()
    assert row["state"] == "blocked" and "filter list" in row["detail"]


def test_project_status_survives_a_lane_that_cannot_answer(tmp_path):
    selection = [_item("s1", "2026/FF5/Animals", 0)]
    seq, _admin = _plan_sequencer(tmp_path, selection)

    def _boom():
        raise RuntimeError("the lane is mid-restart")

    seq.lane_a.status = _boom
    with seq._lock:
        seq._current_slug = "s1"
        seq._state = "running"
    assert seq.project_status()[0]["lanes"]["A"] == "unknown"


def test_shared_folder_problems_come_from_both_managers(tmp_path):
    seq, _admin = _plan_sequencer(tmp_path, [])

    class _Manager:
        def __init__(self, texts):
            self.texts = texts

        def problems(self):
            return list(self.texts)

    seq.shared_folders = _Manager(["The LUT library has not been shared."])
    seq.borrowed_folders = _Manager(["2026/FF5/Lender has not been shared."])
    assert seq.shared_folder_problems() == [
        "The LUT library has not been shared.",
        "2026/FF5/Lender has not been shared.",
    ]

    class _Broken:
        def problems(self):
            raise RuntimeError("no")

    seq.shared_folders = _Broken()
    assert seq.shared_folder_problems() == ["2026/FF5/Lender has not been shared."]


def test_a_blocked_rename_reaches_the_project_line(tmp_path):
    """SYNC-102: a project whose folder could not be moved is one project
    quietly not syncing, and nothing anywhere said so."""
    selection = [_item("s1", "2026/FF5/Animals", 0)]
    seq, _admin = _plan_sequencer(tmp_path, selection)
    seq.repather.ledger.record("s1", "old", "new", "Animals is not syncing because "
                               "CC Sync could not move its folder.", relinked=None,
                               moved=False)
    (row,) = seq.project_status()
    assert row["state"] == "blocked"
    assert "could not move its folder" in row["detail"]
    assert [e["slug"] for e in seq.repath_events()] == ["s1"]

    # ...and the rename that finally worked clears it.
    seq.repather.ledger.record("s1", "old", "new", "moved", relinked=True, moved=True)
    assert seq.project_status()[0]["state"] != "blocked"


def test_the_repather_is_built_with_this_machine_s_state_and_relink(tmp_path):
    seq, _admin = _plan_sequencer(tmp_path, [])
    assert seq.repather.ledger._path == tmp_path / "state" / "repath_events.json"
    # The relink is file_moves', i.e. the one that takes a save point and
    # writes the undo journal (CLAUDE.md's media-pool rule).
    assert seq.repather._relink_fn == seq._relink_moved_project
    assert seq.repath_events() == []
