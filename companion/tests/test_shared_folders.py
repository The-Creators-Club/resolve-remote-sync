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
