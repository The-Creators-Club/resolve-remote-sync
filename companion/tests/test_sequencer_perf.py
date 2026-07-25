"""Sequencer performance behaviours from AUDIT_2 §4: concurrent lanes A/B
(C-1/P7), the conditional structure clone (C-3/P10), the lane C pause scheme
(P4), throttled selection reads (P11) and orphan-.partial REPORTING (P8/P15/
C-7).

Shares the fakes in test_sequencer.py rather than re-inventing them, so
there is exactly one FakeAdmin/FakeLane whose behaviour has to stay honest.
"""

from __future__ import annotations

import threading

from ccsync_companion.sync.sequencer import Sequencer
from test_sequencer import (  # noqa: E402  (sibling test module, not a package)
    FakeAdmin,
    FakeLane,
    FakeSelectionClient,
    _build,
    _cfg,
    _item,
    _stop_all_sequencers,  # noqa: F401  -- autouse fixture, imported for reuse
    _wait_until,
)


# -- lanes A and B run concurrently (AUDIT_2 C-1/P7) ------------------------


class _BlockingLane:
    """A lane whose run_once blocks until released, recording entry so a
    test can prove two lanes were in flight at the same moment."""

    def __init__(self, name, events):
        self.name = name
        self.events = events
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def run_once(self, subpath=None):
        self.calls.append(subpath)
        self.events.append((self.name, subpath))
        self.entered.set()
        self.release.wait(timeout=5.0)


def test_lane_a_and_lane_b_run_at_the_same_time():
    """AUDIT_2 C-1/P7: lane A is up-only and lane B is down-only over
    disjoint file sets in separate rclone processes, and the tailnet is full
    duplex -- so serializing them left downstream idle for the whole of a
    40 GB upload and vice versa (up to 50% of pass wall clock)."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    lane_a = _BlockingLane("lane_a", admin.events)
    lane_b = _BlockingLane("lane_b", admin.events)
    seq = Sequencer(lane_a, lane_b, admin, selection, _cfg(), folder_status_poll_seconds=0.02)

    seq.start()
    try:
        # Both must be INSIDE run_once simultaneously -- neither is released.
        assert lane_a.entered.wait(timeout=3.0)
        assert lane_b.entered.wait(timeout=3.0)
    finally:
        lane_a.release.set()
        lane_b.release.set()
        seq.stop()


def test_concurrent_lanes_can_be_turned_off():
    """The knob exists because upstream and downstream now compete for the
    editor's CPU and disk; with it off the old strict serialization is back."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    lane_a = _BlockingLane("lane_a", admin.events)
    lane_b = _BlockingLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection, _cfg(concurrent_lanes=False),
        folder_status_poll_seconds=0.02,
    )

    seq.start()
    try:
        assert lane_a.entered.wait(timeout=3.0)
        # Lane B must NOT have started while lane A is still inside run_once.
        assert not lane_b.entered.wait(timeout=0.3)
        lane_a.release.set()
        assert lane_b.entered.wait(timeout=3.0)
    finally:
        lane_a.release.set()
        lane_b.release.set()
        seq.stop()


def test_repath_still_runs_strictly_before_both_lanes():
    """The one ordering that must survive concurrency (AUDIT_2 C-1): a lane
    A that started before repather.reconcile() re-uploads the stale local
    tree to the NAS's dead old path."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    events = admin.events

    class _Repather:
        def reconcile(self, sel):
            events.append(("repath", tuple(i.get("slug") for i in sel)))
            return []

    lane_a = FakeLane("lane_a", events)
    lane_b = FakeLane("lane_b", events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection, _cfg(),
        folder_status_poll_seconds=0.02, repather=_Repather(),
    )

    seq.start()
    assert _wait_until(lambda: lane_a.calls and lane_b.calls, timeout=3.0)
    seq.stop()

    first_a = next(i for i, e in enumerate(events) if e[0] == "lane_a")
    first_b = next(i for i, e in enumerate(events) if e[0] == "lane_b")
    repaths = [i for i, e in enumerate(events) if e[0] == "repath"]
    assert repaths, events
    assert repaths[0] < first_a
    assert repaths[0] < first_b


def test_both_lanes_finish_before_the_next_project_starts():
    """Joined, not fired and forgotten: an un-joined lane B would still be
    writing into the project directory while the next project's repath
    moves it."""
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: ("lane_a", "Projects/2026/FF5/Bravo") in events, timeout=3.0)
    seq.stop()

    bravo = events.index(("lane_a", "Projects/2026/FF5/Bravo"))
    assert ("lane_b", "Projects/2026/FF5/Alpha") in events[:bravo]


# -- conditional structure clone (AUDIT_2 C-3/P10) --------------------------


def _clone_spy(calls):
    def _clone(**kwargs):
        calls.append(kwargs.get("subpath"))
        return 0

    return _clone


def test_structure_clone_runs_on_the_first_pass_then_skips():
    """clone_directory_tree is a full `lsf --dirs-only -R` over SFTP plus a
    mkdir loop -- ~1.5 s and an SSH handshake per project per pass, and it
    creates nothing at all in steady state."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    calls: list = []
    lane_a = FakeLane("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection,
        _cfg(structure_clone_every_n_passes=10),
        folder_status_poll_seconds=0.02, clone_tree_fn=_clone_spy(calls),
    )

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 4, timeout=5.0)
    seq.stop()

    assert calls == ["Projects/2026/FF5/Alpha"], calls
    assert len(lane_a.calls) > len(calls)


def test_structure_clone_every_n_passes_still_re_runs():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    calls: list = []
    lane_a = FakeLane("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection,
        _cfg(structure_clone_every_n_passes=2),
        folder_status_poll_seconds=0.02, clone_tree_fn=_clone_spy(calls),
    )

    seq.start()
    assert _wait_until(lambda: len(calls) >= 2, timeout=5.0)
    seq.stop()
    # Every other pass, not every pass.
    assert len(lane_a.calls) >= 2 * len(calls) - 1


def test_a_repath_forces_the_structure_clone_immediately():
    """A repath means the project directory moved, so whatever the cached
    structure said is now about the wrong path."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    calls: list = []

    class _AlwaysRepaths:
        def reconcile(self, sel):
            return [i.get("slug") for i in sel]

    lane_a = FakeLane("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection,
        _cfg(structure_clone_every_n_passes=100),
        folder_status_poll_seconds=0.02, clone_tree_fn=_clone_spy(calls),
        repather=_AlwaysRepaths(),
    )

    seq.start()
    assert _wait_until(lambda: len(calls) >= 3, timeout=5.0)
    seq.stop()
    assert len(calls) >= 3  # forced every pass, despite every_n=100


# -- lane C pause scheme (AUDIT_2 P4) ---------------------------------------


def test_default_scheme_never_pauses_another_project_s_folder():
    """P4: the rotation scheme cost N(N-1) config commits per pass
    (~1000/hour at N=6), a full folder rescan on every unpause (~180 tree
    walks/hour competing with lanes A and B for IOPS), silently rewrote
    unrelated folder fields on each PATCH, and left every non-current
    project unable to send its small latency-sensitive files for up to
    ~50 minutes."""
    items = [
        _item("s-a", "2026/FF5/Alpha", 0),
        _item("s-b", "2026/FF5/Bravo", 1),
        _item("s-c", "2026/FF5/Charlie", 2),
    ]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 3, timeout=5.0)
    seq.stop()

    assert [c for c in admin.pause_calls if c[1] is True] == []


def test_default_scheme_still_unpauses_folders_left_paused_by_an_older_version():
    """With the scheme off, the unpause sweeps are the ONLY thing that
    releases a folder a crashed rotate-scheme pass (or an older companion)
    left paused -- and a stuck-paused folder means lane C carries nothing at
    all for that project."""
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items, cached=items)
    admin = FakeAdmin()
    admin.paused_state = {"s-a": True, "s-b": True}
    seq, lane_a, lane_b, events = _build(selection, admin, sequencer_idle_seconds=0.05)

    seq.start()
    assert _wait_until(
        lambda: ("s-a", False) in admin.pause_calls and ("s-b", False) in admin.pause_calls,
        timeout=3.0,
    )
    seq.stop()
    for slug in ("s-a", "s-b"):
        assert admin.paused_state[slug] is False


def test_rotate_scheme_restores_the_old_pausing_behaviour():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin, lane_c_pause_scheme="rotate")

    seq.start()
    assert _wait_until(lambda: ("s-b", True) in admin.pause_calls, timeout=3.0)
    seq.stop()


def test_unknown_pause_scheme_falls_back_to_none_not_to_rotate():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, _a, _b, _e = _build(selection, admin, lane_c_pause_scheme="whatever")
    assert seq.lane_c_pause_scheme == "none"


def test_max_folder_concurrency_replaces_the_pause_scheme():
    """Syncthing's own pacing: the same "one project at a time" I/O for zero
    config commits, zero folder restarts and zero rescans."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: admin.max_folder_concurrency_calls, timeout=3.0)
    seq.stop()
    assert admin.max_folder_concurrency_calls[0] == 2


def test_rotate_scheme_does_not_touch_max_folder_concurrency():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    seq, lane_a, lane_b, events = _build(selection, admin, lane_c_pause_scheme="rotate")

    seq.start()
    assert _wait_until(lambda: lane_a.calls, timeout=3.0)
    seq.stop()
    assert admin.max_folder_concurrency_calls == []


def test_pacing_write_failure_never_stops_the_sequencer():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()

    def boom(value):
        raise RuntimeError("older syncthing, no such endpoint")

    admin.ensure_max_folder_concurrency = boom
    seq, lane_a, lane_b, events = _build(selection, admin)

    seq.start()
    assert _wait_until(lambda: lane_a.calls, timeout=3.0)
    seq.stop()


# -- selection.get() throttling (AUDIT_2 P11/L-5) ---------------------------


def test_lane_c_wait_loop_does_not_refetch_the_selection_every_tick():
    """selection.get() does a LIVE HTTP fetch and rewrites selection.json on
    every call, and the wait loop polls every 5 s for up to a 600 s turn:
    ~120 requests + 120 disk writes per project per pass per editor, i.e.
    ~1 req/s against the dashboard ON THE NAS while transfers run. The
    truncate-then-write is also how a killed companion leaves a zero-byte
    selection.json."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5  # park the pass inside the wait loop
    seq, lane_a, lane_b, events = _build(
        selection, admin, project_rotation_seconds=5.0, selection_poll_interval=60.0,
    )

    seq.start()
    assert _wait_until(lambda: admin.status_calls.count("s-a") >= 12, timeout=4.0)
    calls_after_12_polls = selection.get_calls
    seq.stop()

    # A dozen poll ticks must not be a dozen fetches: one per pass plus one
    # per project is the budget, and the loop itself contributes nothing.
    assert calls_after_12_polls <= 4, calls_after_12_polls


def test_selection_changes_are_still_noticed_once_the_throttle_expires():
    items = [_item("s-a", "2026/FF5/Alpha", 0), _item("s-b", "2026/FF5/Bravo", 1)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    admin.status_by_slug["s-a"] = 5
    seq, lane_a, lane_b, events = _build(
        selection, admin, project_rotation_seconds=5.0, selection_poll_interval=0.01,
    )

    seq.start()
    assert _wait_until(lambda: seq.current_slug == "s-a", timeout=3.0)
    # With a throttle shorter than the poll tick the wait loop keeps asking,
    # so a mid-turn selection change is still seen promptly. (0.01 rather
    # than a literal 0: every sequencer interval now goes through
    # config.coerce_numeric, which treats a non-positive value as the
    # hand-edited garbage validate_config() already flags and falls back to
    # the packaged default.)
    before = selection.get_calls
    assert _wait_until(lambda: selection.get_calls >= before + 2, timeout=3.0)
    seq.stop()


# -- orphan .partial files: REPORTED, never deleted (AUDIT_2 P8/P15/C-7) ----


class _LaneWithOrphans(FakeLane):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.orphan_calls: list = []

    def refresh_orphan_report(self, subpath=None):
        self.orphan_calls.append(subpath)
        return {"partials": {"count": 3, "bytes": 12}}


def test_orphan_partials_are_scanned_periodically_and_never_deleted():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    lane_a = _LaneWithOrphans("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection, _cfg(orphan_scan_every_n_passes=2),
        folder_status_poll_seconds=0.02,
    )

    seq.start()
    assert _wait_until(lambda: len(lane_a.orphan_calls) >= 2, timeout=5.0)
    seq.stop()

    assert lane_a.orphan_calls[0] == "Projects/2026/FF5/Alpha"
    # Scanned every other pass, and there is no delete path anywhere: C-7 is
    # explicit that reporting outranks the disk-hygiene gain.
    assert len(lane_a.calls) >= 2 * len(lane_a.orphan_calls) - 1


def test_orphan_scan_can_be_disabled():
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    lane_a = _LaneWithOrphans("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection, _cfg(orphan_scan_every_n_passes=0),
        folder_status_poll_seconds=0.02,
    )
    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 3, timeout=5.0)
    seq.stop()
    assert lane_a.orphan_calls == []


def test_structure_clone_zero_means_never_not_every_pass():
    """AUDIT_3 M-6. config.py's comment and config.example.toml both say
    "0 = never re-clone", but `int(cfg.get(..., 10) or 1)` turned a
    configured 0 into 1 -- so an operator disabling the per-project remote
    listing got it on EVERY pass, the exact opposite of what they asked
    for."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    calls: list = []
    lane_a = FakeLane("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection,
        _cfg(structure_clone_every_n_passes=0),
        folder_status_poll_seconds=0.02, clone_tree_fn=_clone_spy(calls),
    )

    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 4, timeout=5.0)
    seq.stop()

    assert seq.structure_clone_every_n_passes == 0
    assert calls == [], "0 must disable the clone entirely, first pass included"


def test_structure_clone_disabled_still_runs_after_a_repath():
    """The forced path survives being disabled: a repath moved the project,
    so whatever structure exists locally is at the wrong path."""
    items = [_item("s-a", "2026/FF5/Alpha", 0)]
    selection = FakeSelectionClient(selection=items)
    admin = FakeAdmin()
    calls: list = []

    class _AlwaysRepaths:
        def reconcile(self, sel):
            return [i.get("slug") for i in sel]

    lane_a = FakeLane("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(
        lane_a, lane_b, admin, selection,
        _cfg(structure_clone_every_n_passes=0),
        folder_status_poll_seconds=0.02, clone_tree_fn=_clone_spy(calls),
        repather=_AlwaysRepaths(),
    )

    seq.start()
    assert _wait_until(lambda: len(calls) >= 2, timeout=5.0)
    seq.stop()
    assert calls[0] == "Projects/2026/FF5/Alpha"


# -- numeric config never kills construction (AUDIT_3 M-5) ------------------


def test_hand_edited_numeric_config_never_raises_in_the_constructor(caplog):
    """The Sequencer is built inside CompanionApp.__init__, so a bare
    float(cfg.get(...)) on a hand-edited value took the WINDOWED exe down
    with no tray and no log line. Every knob falls back to its packaged
    default instead (validate_config reports the bad value)."""
    selection = FakeSelectionClient(selection=[])
    admin = FakeAdmin()
    cfg = _cfg(
        selection_poll_interval="fast",
        project_rotation_seconds=None,
        sequencer_idle_seconds="",
        structure_clone_every_n_passes="never",
        lane_c_max_folder_concurrency="two",
        orphan_scan_every_n_passes=-5,
    )
    with caplog.at_level("ERROR", logger="ccsync.config"):
        seq = Sequencer(FakeLane("a", []), FakeLane("b", []), admin, selection, cfg)

    assert seq.selection_poll_interval == 60.0
    assert seq.project_rotation_seconds == 600.0
    assert seq.sequencer_idle_seconds == 60.0
    assert seq.structure_clone_every_n_passes == 10
    assert seq.lane_c_max_folder_concurrency == 2
    assert seq.orphan_scan_every_n_passes == 20
