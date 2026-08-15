"""Sequencer policy costs and the lane re-arm, from the 2026-08-14 bug hunt.

Three findings, one theme -- *the sequencer must not write when a read will
do, and must not leave a lane it drives latched off*:

  * SYNC-1: managed mode stops BOTH rclone lanes on sign-out but only lane A
    was ever re-armed, so lane B (whose entire drive is run_once() from here)
    was dead for the life of the process after one sign-out/sign-in;
  * SYNC-6: the per-turn folder policy POSTed the full .stignore and fetched
    the folder config twice, every project, every pass, forever;
  * SYNC-7: the between-passes unpause sweep issued a config-mutating PATCH
    per selected project, unconditionally, under a default pause scheme that
    never pauses anything.

Deliberately self-contained fakes rather than test_sequencer.py's: what is
asserted here is REQUEST COUNTS, so the double has to be explicit about which
endpoints it offers (an admin that predates get_folders/get_ignores is a
supported shape -- both are consulted with getattr).
"""

from __future__ import annotations

import urllib.error

import pytest

from ccsync_companion.sync.sequencer import Sequencer
from ccsync_companion.sync.syncthing_admin import STIGNORE_LINES


# -- fakes -----------------------------------------------------


class FakeLane:
    def __init__(self, name="lane", arm_raises=False):
        self.name = name
        self.calls: list = []
        self.arm_calls = 0
        self._arm_raises = arm_raises

    def arm(self):
        self.arm_calls += 1
        if self._arm_raises:
            raise RuntimeError("boom")

    def run_once(self, subpath=None):
        self.calls.append(subpath)


class LaneWithoutArm(FakeLane):
    """A lane adapter from before arm() existed -- `arm` is optional on the
    LaneAdapter contract and is consulted with getattr."""

    arm = None


class FakeAdmin:
    """Records every call; folder state is scriptable per folder id."""

    def __init__(self, folders=None, ignores=None):
        # id -> {"paused": bool, "versioning": {...}, "ignoreDelete": bool}
        self.folders = dict(folders or {})
        # id -> what GET /rest/db/ignores reports (absent = complete)
        self.ignores = dict(ignores or {})
        self.get_folders_calls = 0
        self.get_folder_calls: list = []
        self.get_ignores_calls: list = []
        self.set_ignores_calls: list = []
        self.pause_calls: list = []
        self.versioning_calls: list = []
        self.ignore_delete_calls: list = []
        self.confirmed_calls: list = []
        self.get_folders_raises = False
        self.set_ignores_raises = False
        self.unconfirmed: set = set()

    # -- reads
    def get_folders(self):
        self.get_folders_calls += 1
        if self.get_folders_raises:
            raise RuntimeError("syncthing unreachable")
        return [dict(cfg, id=fid) for fid, cfg in self.folders.items()]

    def get_folder(self, folder_id):
        self.get_folder_calls.append(folder_id)
        if folder_id not in self.folders:
            raise urllib.error.HTTPError("http://x", 404, "Not Found", None, None)
        return dict(self.folders[folder_id], id=folder_id)

    def get_ignores(self, folder_id):
        self.get_ignores_calls.append(folder_id)
        value = self.ignores.get(folder_id, list(STIGNORE_LINES))
        if isinstance(value, Exception):
            raise value
        return {"ignore": value, "expanded": []}

    # -- writes
    def set_ignores(self, folder_id, lines):
        self.set_ignores_calls.append((folder_id, list(lines)))
        if self.set_ignores_raises:
            raise RuntimeError("config write timed out")
        self.ignores[folder_id] = list(lines)
        self.unconfirmed.discard(folder_id)

    def set_folder_paused(self, folder_id, paused):
        self.pause_calls.append((folder_id, paused))
        self.folders.setdefault(folder_id, {})["paused"] = paused

    def ensure_versioning(self, folder_id, folder=None):
        self.versioning_calls.append((folder_id, folder))
        return False

    def ensure_ignore_delete(self, folder_id, folder=None):
        self.ignore_delete_calls.append((folder_id, folder))
        return False

    def ignores_confirmed(self, folder_id):
        return folder_id not in self.unconfirmed

    def note_ignores_confirmed(self, folder_id):
        self.confirmed_calls.append(folder_id)
        self.unconfirmed.discard(folder_id)


class AdminWithoutGetFolders(FakeAdmin):
    """An admin from before get_folders existed (SYNC-7 consults it with
    getattr for exactly this shape)."""

    get_folders = None


class AdminWithoutGetIgnores(FakeAdmin):
    """Ditto for the read half of SYNC-6."""

    get_ignores = None


class FakeSelection:
    def __init__(self, selection=None, enabled=True, cached=None):
        self.selection = selection
        self.enabled = enabled
        self.cached = cached

    def get(self):
        return self.selection, "live"

    def load_cached(self):
        return self.cached


class NoopSharedFolders:
    def reconcile(self):
        return {}


def _item(slug, rel_path, position=0):
    return {
        "slug": slug, "label": rel_path, "rel_path": rel_path,
        "position": position, "active": True,
    }


def _seq(admin, lane_a=None, lane_b=None, selection=None, **cfg):
    config = {
        "local_root": "",
        "selection_poll_interval": 0.02,
        "sequencer_idle_seconds": 0.02,
        "project_rotation_seconds": 1.0,
    }
    config.update(cfg)
    return Sequencer(
        lane_a if lane_a is not None else FakeLane("lane_a"),
        lane_b if lane_b is not None else FakeLane("lane_b"),
        admin,
        selection if selection is not None else FakeSelection(),
        config,
        folder_status_poll_seconds=0.02,
        shared_folders=NoopSharedFolders(),
    )


# ===========================================================================
# SYNC-1: the sequencer un-latches the lanes it drives
# ===========================================================================


def test_start_arms_both_rclone_lanes():
    """Lane B has no other way back: run_once() from here IS its whole drive,
    and app._stop_lanes() stops it on every sign-out."""
    lane_a, lane_b = FakeLane("lane_a"), FakeLane("lane_b")
    seq = _seq(FakeAdmin(), lane_a=lane_a, lane_b=lane_b)

    seq.start()
    try:
        assert lane_a.arm_calls == 1
        assert lane_b.arm_calls == 1
    finally:
        seq.stop()


def test_a_second_start_while_running_arms_nothing():
    """start() refuses to spawn a second sequencer thread (AUDIT_2 L-1); the
    arming must sit behind that same guard, not in front of it."""
    lane_a, lane_b = FakeLane("lane_a"), FakeLane("lane_b")
    seq = _seq(FakeAdmin(), lane_a=lane_a, lane_b=lane_b)

    seq.start()
    try:
        seq.start()
        assert lane_b.arm_calls == 1
    finally:
        seq.stop()


def test_a_lane_that_cannot_be_armed_does_not_stop_the_sequencer():
    """`arm` is not part of the LaneAdapter contract, and a lane that throws
    must not cost the editor every OTHER lane."""
    lane_a = LaneWithoutArm("lane_a")
    lane_b = FakeLane("lane_b", arm_raises=True)
    seq = _seq(FakeAdmin(), lane_a=lane_a, lane_b=lane_b)

    seq.start()
    try:
        assert seq._thread is not None and seq._thread.is_alive()
        assert lane_b.arm_calls == 1
    finally:
        seq.stop()


# ===========================================================================
# SYNC-6: the per-turn folder policy reads before it writes
# ===========================================================================


def test_a_complete_stignore_costs_one_read_and_no_write():
    admin = FakeAdmin(folders={"s-a": {"paused": False}})
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True

    assert admin.get_ignores_calls == ["s-a"]
    assert admin.set_ignores_calls == [], "steady state must not rewrite .stignore"


def test_a_missing_pattern_is_still_re_asserted():
    """The retry path L-3/P6 exists for: a folder accepted by an older
    companion or by hand carries no ignores at all."""
    admin = FakeAdmin(folders={"s-a": {"paused": False}}, ignores={"s-a": None})
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True

    assert admin.set_ignores_calls == [("s-a", list(STIGNORE_LINES))]


def test_a_partial_stignore_is_re_asserted():
    admin = FakeAdmin(
        folders={"s-a": {"paused": False}},
        ignores={"s-a": [line for line in STIGNORE_LINES if "Proxy" not in line]},
    )
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True
    assert admin.set_ignores_calls == [("s-a", list(STIGNORE_LINES))]


def test_a_read_that_fails_counts_as_missing():
    """B5's fail-closed posture survives the read-first change: not knowing
    means writing, and a write that then fails still leaves the folder
    paused."""
    admin = FakeAdmin(
        folders={"s-a": {"paused": False}},
        ignores={"s-a": RuntimeError("syncthing unreachable")},
    )
    admin.set_ignores_raises = True
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is False
    assert admin.set_ignores_calls == [("s-a", list(STIGNORE_LINES))]


def test_a_404_on_the_read_is_not_a_failure_and_writes_nothing():
    """The folder is not configured on this machine at all, so there is
    nothing to run unfiltered -- and a WARNING per project per pass for every
    folder the editor has not been offered yet is the L-11 log flood."""
    admin = FakeAdmin()
    admin.ignores["s-a"] = urllib.error.HTTPError("http://x", 404, "Not Found", None, None)
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True
    assert admin.set_ignores_calls == []
    assert admin.get_folder_calls == []


def test_a_confirmed_read_clears_the_half_accepted_latch():
    """SYNC-6's own regression: with the write skipped, nothing else would
    ever clear a latch set by an accept whose set_ignores timed out after
    Syncthing had applied it -- and a latched folder is excluded from every
    leak-recovery unpause sweep."""
    admin = FakeAdmin(folders={"s-a": {"paused": False}})
    admin.unconfirmed.add("s-a")
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True

    assert admin.confirmed_calls == ["s-a"]
    assert admin.ignores_confirmed("s-a") is True


def test_the_folder_config_is_fetched_once_for_both_ensure_calls():
    """Each ensure_* fetches its own config when it isn't handed one, which
    made a steady-state turn cost two identical GETs (SharedFolderManager
    already passes the fetched folder down -- this is the same shape)."""
    folder = {"paused": False, "versioning": {"type": "staggered"}, "ignoreDelete": True}
    admin = FakeAdmin(folders={"s-a": folder})
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True

    assert admin.get_folder_calls == ["s-a"]
    assert admin.versioning_calls[0][1] == dict(folder, id="s-a")
    assert admin.ignore_delete_calls[0][1] == dict(folder, id="s-a")


def test_an_unreadable_folder_config_falls_back_to_the_per_call_fetch():
    """Passing None restores the old behaviour: each ensure_* fetches for
    itself rather than being told a folder has no versioning at all."""
    class NoFolderRead(FakeAdmin):
        def get_folder(self, folder_id):
            self.get_folder_calls.append(folder_id)
            raise RuntimeError("syncthing unreachable")

    admin = NoFolderRead(folders={"s-a": {"paused": False}})
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True
    assert admin.versioning_calls == [("s-a", None)]
    assert admin.ignore_delete_calls == [("s-a", None)]


def test_an_admin_without_get_ignores_still_writes_every_turn():
    """A double (or an older admin) that cannot be read from must not end up
    NEVER asserting the ignores."""
    admin = AdminWithoutGetIgnores(folders={"s-a": {"paused": False}})
    seq = _seq(admin)

    assert seq._reassert_folder_policy("s-a") is True
    assert admin.set_ignores_calls == [("s-a", list(STIGNORE_LINES))]


# ===========================================================================
# SYNC-7: the unpause sweep reads once and writes only what is paused
# ===========================================================================


def test_the_sweep_does_not_patch_folders_that_are_already_running():
    admin = FakeAdmin(folders={"s-a": {"paused": False}, "s-b": {"paused": False}})
    seq = _seq(admin)

    seq._unpause_all([_item("s-a", "2026/FF5/Alpha"), _item("s-b", "2026/FF5/Bravo", 1)])

    assert admin.pause_calls == [], "a no-op PATCH still takes Syncthing's config lock"
    assert admin.get_folders_calls == 1, "one read for the whole sweep"


def test_the_sweep_still_releases_a_folder_that_is_paused():
    """Including one THIS sequencer never paused: accept_folder creates
    folders paused, and a previous run can die mid-pass."""
    admin = FakeAdmin(folders={"s-a": {"paused": True}, "s-b": {"paused": False}})
    seq = _seq(admin)

    seq._unpause_all([_item("s-a", "2026/FF5/Alpha"), _item("s-b", "2026/FF5/Bravo", 1)])

    assert admin.pause_calls == [("s-a", False)]


def test_a_folder_released_by_someone_else_leaves_our_bookkeeping():
    """Skipping the PATCH must not strand the slug in _paused_by_us, or
    _release_paused_folders would retry it at every project boundary for the
    life of the process."""
    admin = FakeAdmin(folders={"s-a": {"paused": False}})
    seq = _seq(admin)
    seq._paused_by_us.add("s-a")

    seq._unpause_all([_item("s-a", "2026/FF5/Alpha")])

    assert admin.pause_calls == []
    assert seq._paused_by_us == set()


def test_an_unreadable_folder_list_falls_back_to_the_blind_sweep():
    """A folder left paused is a project that silently syncs nothing, so not
    knowing has to fail towards the write."""
    admin = FakeAdmin(folders={"s-a": {"paused": False}})
    admin.get_folders_raises = True
    seq = _seq(admin)

    seq._unpause_all([_item("s-a", "2026/FF5/Alpha")])

    assert admin.pause_calls == [("s-a", False)]


def test_an_admin_without_get_folders_falls_back_to_the_blind_sweep():
    admin = AdminWithoutGetFolders(folders={"s-a": {"paused": False}})
    seq = _seq(admin)

    seq._unpause_all([_item("s-a", "2026/FF5/Alpha")])

    assert admin.pause_calls == [("s-a", False)]


def test_an_empty_or_unusable_selection_costs_no_read_at_all():
    admin = FakeAdmin(folders={"s-a": {"paused": True}})
    seq = _seq(admin)

    seq._unpause_all([])
    # SYNC-2: an archived project arrives with rel_path NULL and must not be
    # released -- and must not cost a read either.
    seq._unpause_all([{"slug": "s-a", "rel_path": None, "active": False}])

    assert admin.get_folders_calls == 0
    assert admin.pause_calls == []


def test_a_folder_whose_ignores_never_landed_is_never_released():
    """The L-3 exclusion outranks everything above it: an unfiltered
    sendreceive folder must not go online, read or no read."""
    admin = FakeAdmin(folders={"s-a": {"paused": True}})
    admin.unconfirmed.add("s-a")
    seq = _seq(admin)

    seq._unpause_all([_item("s-a", "2026/FF5/Alpha")])

    assert admin.pause_calls == []


@pytest.fixture(autouse=True)
def _no_stray_sequencers():
    """Nothing here starts a thread it does not stop, but a failed assertion
    inside a try/finally-less test would otherwise leak one into the rest of
    the run."""
    created: list = []
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
