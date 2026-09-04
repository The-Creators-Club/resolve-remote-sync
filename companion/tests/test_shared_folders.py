"""sync/shared_folders: the fleet-wide asset libraries on an editor.

The property these tests exist to protect is the same one the sequencer's
own tests protect for project folders: a `sendreceive` folder must never go
online without its .stignore, because it then indexes and offers everything
under it in both directions.
"""
from __future__ import annotations

import urllib.error

import pytest

from ccsync_companion.sync import shared_folders
from ccsync_companion.sync.syncthing_admin import ASSET_STIGNORE_LINES, LUTS_FOLDER_ID


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "nope", {}, None)


class FakeAdmin:
    def __init__(self, folder=None, ignores=None, pending=None):
        self.folder = folder
        self.ignores = ignores
        self.pending = pending or {}
        self.calls: list[tuple] = []

    def get_folder(self, folder_id):
        if self.folder is None:
            raise _http_error(404)
        return dict(self.folder)

    def get_ignores(self, folder_id):
        if self.ignores is None:
            return {"ignore": None}
        return {"ignore": list(self.ignores)}

    def set_ignores(self, folder_id, lines):
        self.calls.append(("set_ignores", folder_id, tuple(lines)))
        self.ignores = list(lines)

    def set_folder_paused(self, folder_id, paused):
        self.calls.append(("set_paused", folder_id, paused))
        if self.folder is not None:
            self.folder["paused"] = paused

    def set_folder_path(self, folder_id, path, label=None):
        self.calls.append(("set_path", folder_id, path))
        if self.folder is not None:
            self.folder["path"] = path

    def ensure_versioning(self, folder_id, folder=None):
        self.calls.append(("ensure_versioning", folder_id))
        return False

    def ensure_ignore_delete(self, folder_id, folder=None):
        """Same no-write-when-already-set shape as the real one, so a healthy
        folder still reconciles to "ok" (delete-protection, 2026-08-11)."""
        self.calls.append(("ensure_ignore_delete", folder_id))
        return (folder or {}).get("ignoreDelete") is not True

    def pending_folders(self):
        return self.pending

    def accept_folder(self, folder_id, label, local_path, device_id, ignore_lines=None):
        self.calls.append(("accept", folder_id, local_path, device_id, tuple(ignore_lines or ())))
        return {}

    def names(self):
        return [c[0] for c in self.calls]


# Every test drives ONE folder, so the manager is scoped to the LUT library
# rather than to the whole SHARED_ASSET_FOLDERS list: a second library must
# not be able to change what these assertions mean.
ONLY_LUTS = [(LUTS_FOLDER_ID, "Assets/Luts", "Assets/Luts (LUT library)")]


def _manager(admin, tmp_path):
    return shared_folders.SharedFolderManager(admin, tmp_path, folders=ONLY_LUTS)


def test_healthy_folder_costs_no_config_writes(tmp_path):
    """Steady state must be reads only: every config write restarts and
    rescans the folder in Syncthing."""
    admin = FakeAdmin(
        folder={"id": LUTS_FOLDER_ID, "paused": False,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts"),
                "versioning": {"type": "staggered"}, "ignoreDelete": True},
        ignores=list(ASSET_STIGNORE_LINES),
    )
    result = _manager(admin, tmp_path).reconcile()
    assert result[LUTS_FOLDER_ID] == "ok"
    assert [c for c in admin.names()
            if c not in ("ensure_versioning", "ensure_ignore_delete")] == []


def test_accepts_the_servers_offer(tmp_path):
    admin = FakeAdmin(pending={LUTS_FOLDER_ID: {"offeredBy": {"DEVICE-1": {}}}})
    result = _manager(admin, tmp_path).reconcile()

    assert result[LUTS_FOLDER_ID] == "accepted"
    accept = next(c for c in admin.calls if c[0] == "accept")
    assert accept[3] == "DEVICE-1"
    # Accepted with the ASSET ignore list, not the project one.
    assert accept[4] == tuple(ASSET_STIGNORE_LINES)
    # And the directory exists before Syncthing takes the folder online.
    assert (tmp_path / "Assets" / "Luts").is_dir()


def test_an_unoffered_folder_is_not_an_error(tmp_path):
    """Routine before the dashboard's first provision cycle reaches this
    device, and permanent on a machine the server hasn't shared it with."""
    admin = FakeAdmin(pending={})
    assert _manager(admin, tmp_path).reconcile()[LUTS_FOLDER_ID] == "not-offered"
    assert admin.calls == []


def test_missing_ignores_are_re_asserted(tmp_path):
    admin = FakeAdmin(
        folder={"id": LUTS_FOLDER_ID, "paused": False,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts")},
        ignores=["(?i)*.braw"],   # a fragment of the list
    )
    assert _manager(admin, tmp_path).reconcile()[LUTS_FOLDER_ID] == "repaired"
    assert ("set_ignores", LUTS_FOLDER_ID, tuple(ASSET_STIGNORE_LINES)) in admin.calls


def test_a_paused_folder_is_released(tmp_path):
    admin = FakeAdmin(
        folder={"id": LUTS_FOLDER_ID, "paused": True,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts")},
        ignores=list(ASSET_STIGNORE_LINES),
    )
    assert _manager(admin, tmp_path).reconcile()[LUTS_FOLDER_ID] == "repaired"
    assert ("set_paused", LUTS_FOLDER_ID, False) in admin.calls


def test_a_paused_folder_with_unreadable_ignores_stays_paused(tmp_path):
    """Fail closed. Waiting is cheap; putting an unfiltered sendreceive
    folder online is not."""
    class Unreadable(FakeAdmin):
        def get_ignores(self, folder_id):
            raise RuntimeError("boom")

    admin = Unreadable(
        folder={"id": LUTS_FOLDER_ID, "paused": True,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts")},
    )
    _manager(admin, tmp_path).reconcile()
    assert ("set_paused", LUTS_FOLDER_ID, False) not in admin.calls


def test_a_folder_pointed_elsewhere_is_re_pointed(tmp_path):
    admin = FakeAdmin(
        folder={"id": LUTS_FOLDER_ID, "paused": False, "path": "D:\\somewhere\\else"},
        ignores=list(ASSET_STIGNORE_LINES),
    )
    assert _manager(admin, tmp_path).reconcile()[LUTS_FOLDER_ID] == "repaired"
    want = shared_folders.local_path_for(tmp_path, "Assets/Luts")
    assert ("set_path", LUTS_FOLDER_ID, want) in admin.calls


def test_a_folder_without_ignore_delete_gets_it(tmp_path):
    """delete-protection (2026-08-11, docs/delete-protection-ignoredelete.md):
    this library auto-shares to the whole fleet with no tick to opt out of, so
    one editor deleting a LUT must not take it off the NAS and off every other
    machine. Retrofit, reusing the config already fetched."""
    admin = FakeAdmin(
        folder={"id": LUTS_FOLDER_ID, "paused": False,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts"),
                "versioning": {"type": "staggered"}},   # accepted before the flag existed
        ignores=list(ASSET_STIGNORE_LINES),
    )
    assert _manager(admin, tmp_path).reconcile()[LUTS_FOLDER_ID] == "repaired"
    assert ("ensure_ignore_delete", LUTS_FOLDER_ID) in admin.calls


def test_a_failing_ignore_delete_never_stops_the_reconcile(tmp_path):
    """Delete protection is a policy retrofit, not a lane-direction rule: a
    folder whose PATCH fails must still be released, ignores permitting."""
    class Failing(FakeAdmin):
        def ensure_ignore_delete(self, folder_id, folder=None):
            raise RuntimeError("config write timed out")

    admin = Failing(
        folder={"id": LUTS_FOLDER_ID, "paused": True,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts")},
        ignores=list(ASSET_STIGNORE_LINES),
    )
    assert _manager(admin, tmp_path).reconcile()[LUTS_FOLDER_ID] == "repaired"
    assert ("set_paused", LUTS_FOLDER_ID, False) in admin.calls


def test_reconcile_never_raises(tmp_path):
    class Broken(FakeAdmin):
        def get_folder(self, folder_id):
            raise RuntimeError("syncthing is down")

    assert Broken().__class__  # sanity
    result = shared_folders.SharedFolderManager(
        Broken(), tmp_path, folders=ONLY_LUTS).reconcile()
    assert result[LUTS_FOLDER_ID] == "error"


def test_failures_log_once_per_streak(tmp_path, caplog):
    """A server that never offers the folder must not produce a warning per
    pass forever."""
    class Broken(FakeAdmin):
        def get_folder(self, folder_id):
            raise RuntimeError("syncthing is down")

    manager = shared_folders.SharedFolderManager(Broken(), tmp_path, folders=ONLY_LUTS)
    with caplog.at_level("WARNING"):
        manager.reconcile()
        manager.reconcile()
        manager.reconcile()
    assert sum("reconcile failed" in r.message for r in caplog.records) == 1


# -- the halt owns these folders too (sync-safety-2, 2026-08-21) ------------


def test_a_paused_shared_folder_is_not_released_while_syncing_is_halted(tmp_path):
    """The halt pauses lane C folders through Syncthing's REST API, and this
    reconcile runs once per sequencer pass -- so without the halt check the
    B-roll archive, the music library and the LUTs came straight back online
    while every tray said nothing was syncing."""
    admin = FakeAdmin(
        folder={"id": LUTS_FOLDER_ID, "paused": True,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts"),
                "versioning": {"type": "staggered"}, "ignoreDelete": True},
        ignores=list(ASSET_STIGNORE_LINES),
    )
    manager = shared_folders.SharedFolderManager(
        admin, tmp_path, folders=ONLY_LUTS, halted=lambda: True)
    manager.reconcile()
    assert ("set_paused", LUTS_FOLDER_ID, False) not in admin.calls

    manager._halted = lambda: False
    manager.reconcile()
    assert ("set_paused", LUTS_FOLDER_ID, False) in admin.calls


def test_a_halt_check_that_throws_leaves_the_folder_paused(tmp_path):
    admin = FakeAdmin(
        folder={"id": LUTS_FOLDER_ID, "paused": True,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts"),
                "versioning": {"type": "staggered"}, "ignoreDelete": True},
        ignores=list(ASSET_STIGNORE_LINES),
    )

    def boom():
        raise RuntimeError("no halt state")

    manager = shared_folders.SharedFolderManager(
        admin, tmp_path, folders=ONLY_LUTS, halted=boom)
    manager.reconcile()
    assert ("set_paused", LUTS_FOLDER_ID, False) not in admin.calls


def test_the_manager_can_name_its_folders_for_the_halt(tmp_path):
    manager = _manager(FakeAdmin(), tmp_path)
    assert manager.folder_ids() == [LUTS_FOLDER_ID]
    assert shared_folders.SharedFolderManager(
        FakeAdmin(), tmp_path).folder_ids() == [
            folder_id for folder_id, _rel, _label in shared_folders.SHARED_ASSET_FOLDERS]


# -- SYNC-6: the drive is out --------------------------------------------------


def test_reconcile_does_nothing_at_all_while_the_tree_is_absent(tmp_path):
    """SYNC-6 (resilience sweep 2026-08-28): the sequencer calls this at its
    loop head, BEFORE any root check. On a Mac whose SSD is unplugged,
    _accept's mkdir(parents=True) builds
    /Volumes/SAMDISK/Creators_Club/Assets/Luts on the BOOT disk -- the ghost
    directory root_guard.probe_root exists to detect, which then makes macOS
    mount the real drive as "/Volumes/SAMDISK 1" permanently -- and points a
    Syncthing folder at it."""
    admin = FakeAdmin(pending={LUTS_FOLDER_ID: {"offeredBy": {"DEVICE-1": {}}}})
    gone = tmp_path / "Volumes" / "SAMDISK"  # never created
    mgr = shared_folders.SharedFolderManager(admin, gone, folders=ONLY_LUTS)
    assert mgr.reconcile() == {}
    assert admin.calls == []
    assert not gone.exists()


def test_the_root_check_is_the_injected_one_and_an_unanswerable_probe_is_absent(tmp_path):
    admin = FakeAdmin(pending={LUTS_FOLDER_ID: {"offeredBy": {"DEVICE-1": {}}}})

    def _boom():
        raise RuntimeError("the volume did not answer")

    mgr = shared_folders.SharedFolderManager(
        admin, tmp_path, folders=ONLY_LUTS, root_present_fn=_boom)
    # tmp_path IS a directory, so only the injected predicate can produce this.
    assert mgr.reconcile() == {}
    assert admin.calls == []


def test_accept_refuses_the_mkdir_if_the_drive_goes_out_mid_reconcile(tmp_path):
    """The second half of the guard: root_present() is answered at the loop
    head, the mkdir check immediately before the mkdir."""
    admin = FakeAdmin(pending={LUTS_FOLDER_ID: {"offeredBy": {"DEVICE-1": {}}}})
    gone = tmp_path / "Volumes" / "SAMDISK"
    mgr = shared_folders.SharedFolderManager(
        admin, gone, folders=ONLY_LUTS, root_present_fn=lambda: True)
    assert mgr.reconcile()[LUTS_FOLDER_ID] == "error"
    assert [c for c in admin.names() if c == "accept"] == []
    assert not gone.exists()


# -- SYNC-101: a failure is kept, not logged once ---------------------------

class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_a_library_the_server_never_shared_is_kept_as_a_problem(tmp_path):
    """SYNC-101 (sweep 2026-09-03): `not-offered` used to be a DEBUG line and
    a discarded dict, so an editor whose LUT library never arrived had
    nothing anywhere to read."""
    admin = FakeAdmin(pending={})       # nothing offered to this device
    mgr = shared_folders.SharedFolderManager(admin, tmp_path, folders=ONLY_LUTS)
    assert mgr.reconcile()[LUTS_FOLDER_ID] == "not-offered"
    problems = mgr.problems()
    assert len(problems) == 1
    assert "Assets/Luts (LUT library)" in problems[0]
    assert "Ask your admin" in problems[0]
    assert "—" not in problems[0]      # no em dash in editor copy
    assert mgr.problem_entries()[0]["outcome"] == "not-offered"


def test_a_kept_problem_is_retried_on_a_backoff_and_clears_on_success(tmp_path):
    clock = _Clock()
    admin = FakeAdmin(pending={})
    mgr = shared_folders.SharedFolderManager(
        admin, tmp_path, folders=ONLY_LUTS, now=clock)
    assert mgr.reconcile()[LUTS_FOLDER_ID] == "not-offered"
    first = len(admin.calls)

    # Straight away: the answer stands, and no second pending-folders read.
    assert mgr.reconcile()[LUTS_FOLDER_ID] == "not-offered"
    assert mgr.problems()
    assert len(admin.calls) == first

    # Past the backoff, and by then the admin has approved the share.
    clock.t += shared_folders.PROBLEM_RETRY_FIRST_SECONDS + 1
    admin.pending = {LUTS_FOLDER_ID: {"offeredBy": {"DEVICE-1": {}}}}
    assert mgr.reconcile()[LUTS_FOLDER_ID] == "accepted"
    assert mgr.problems() == []


def test_a_persistent_problem_reaches_the_log_in_the_editor_s_words(tmp_path, caplog):
    """Routine before the first provision cycle, permanent afterwards: the
    third attempt is where DEBUG stops being the right level."""
    clock = _Clock()
    admin = FakeAdmin(pending={})
    mgr = shared_folders.SharedFolderManager(
        admin, tmp_path, folders=ONLY_LUTS, now=clock)
    with caplog.at_level("WARNING"):
        for _ in range(3):
            mgr.reconcile()
            clock.t += shared_folders.PROBLEM_RETRY_MAX_SECONDS
    assert sum("has not been shared with this computer" in r.message
               for r in caplog.records) == 1


def test_a_folder_that_stays_paused_unfiltered_is_a_problem_not_an_ok(tmp_path):
    class Unreadable(FakeAdmin):
        def get_ignores(self, folder_id):
            raise RuntimeError("syncthing did not answer")

    admin = Unreadable(
        folder={"id": LUTS_FOLDER_ID, "paused": True,
                "path": shared_folders.local_path_for(tmp_path, "Assets/Luts")},
    )
    mgr = shared_folders.SharedFolderManager(admin, tmp_path, folders=ONLY_LUTS)
    assert mgr.reconcile()[LUTS_FOLDER_ID] == "unfiltered"
    assert ("set_paused", LUTS_FOLDER_ID, False) not in admin.calls
    assert "filter list" in mgr.problems()[0]


def test_a_reconcile_that_raises_is_kept_with_its_reason(tmp_path):
    class Broken(FakeAdmin):
        def get_folder(self, folder_id):
            raise RuntimeError("syncthing is down")

    mgr = shared_folders.SharedFolderManager(Broken(), tmp_path, folders=ONLY_LUTS)
    assert mgr.reconcile()[LUTS_FOLDER_ID] == "error"
    assert "syncthing is down" in mgr.problems()[0]
