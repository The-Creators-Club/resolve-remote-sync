"""bug-comp-app-1 (2026-09-24): a halt's paused project folders must stay
paused through every later sequencer stop()/pause() in the same process, and
a restart with the halt still persisted must put them back.

A REAL Sequencer against a fake SyncthingAdmin: the halt's own suite used a
sequencer double whose stop() was a no-op, which is exactly why the release
in stop()/pause() was never seen. Nothing here starts a sequencer thread,
touches Syncthing, rclone or Tk.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ccsync_companion.app import CompanionApp
from ccsync_companion.sync.sequencer import Sequencer
from ccsync_companion.sync.syncthing_admin import STIGNORE_LINES

_ROOT = Path(tempfile.gettempdir()) / "ccsync-tests-halt-holds-root"
_ROOT.mkdir(parents=True, exist_ok=True)


class _Lane:
    name = "fake"

    def run_once(self, subpath=None):
        return None


class _Admin:
    def __init__(self):
        self.pause_calls: list[tuple[str, bool]] = []
        self.paused_state: dict[str, bool] = {}

    def set_folder_paused(self, folder_id, paused):
        self.pause_calls.append((folder_id, paused))
        self.paused_state[folder_id] = paused

    def get_folders(self):
        return [{"id": fid, "paused": p} for fid, p in self.paused_state.items()]

    def get_ignores(self, folder_id):
        return {"ignore": list(STIGNORE_LINES), "expanded": []}

    def ensure_max_folder_concurrency(self, value):
        return True


class _NoSharedFolders:
    """The asset libraries have their own halt coverage (CR-48); kept out of
    the way so these assertions are about project folders alone."""

    def folder_ids(self):
        return []

    def reconcile(self, *a, **kw):
        return None


class _Selection:
    enabled = True

    def __init__(self, items):
        self.items = items

    def get(self):
        return self.items, "live"

    def load_cached(self):
        return list(self.items)


def _items():
    return [
        {"slug": "s-a", "label": "A", "rel_path": "2026/FF5/Alpha", "position": 0,
         "active": True},
        {"slug": "s-b", "label": "B", "rel_path": "2026/FF5/Bravo", "position": 1,
         "active": True},
    ]


def _sequencer(admin, halted, items=None):
    seq = Sequencer(
        _Lane(), _Lane(), admin, _Selection(items if items is not None else _items()),
        {"local_root": str(_ROOT), "shared_folders_enabled": False},
        shared_folders=_NoSharedFolders(),
        halted=halted,
    )
    return seq


def test_stop_and_pause_leave_every_folder_paused_while_halted():
    admin = _Admin()
    state = {"halted": False}
    seq = _sequencer(admin, lambda: state["halted"])
    # What a pass leaves behind: the selection is known, _last_selection set.
    seq._update_known_selection(_items())

    # The halt: stop the sequencer, pause every folder.
    state["halted"] = True
    seq.stop()
    for folder_id in seq.halt_folder_ids():
        admin.set_folder_paused(folder_id, True)
    admin.pause_calls.clear()

    # Tray Quit / self-upgrade / Resolve-exit restart (stop), tray Pause and
    # the drive being pulled (pause): none may release a folder.
    seq.stop()
    seq.pause()
    assert [c for c in admin.pause_calls if c[1] is False] == []
    assert admin.paused_state == {"s-a": True, "s-b": True}

    # Lifting the halt still releases them through the filtered path.
    state["halted"] = False
    seq.release_for_halt()
    assert admin.paused_state["s-a"] is False
    assert admin.paused_state["s-b"] is False


def test_a_predicate_that_cannot_answer_keeps_the_folders_paused():
    admin = _Admin()
    seq = _sequencer(admin, lambda: 1 / 0)
    seq._update_known_selection(_items())
    admin.paused_state = {"s-a": True, "s-b": True}
    seq.pause()
    assert admin.pause_calls == []


def _managed_app(tmp_path, admin, seq=None) -> CompanionApp:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, Any] = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": True,
        "lane_b_enabled": False,
    }
    app = CompanionApp(cfg)
    app.syncthing_admin = admin
    app.sequencer = seq if seq is not None else _sequencer(
        admin, lambda: app.halt.active)
    return app


def test_the_halt_holds_through_the_apps_own_stop_paths(tmp_path):
    admin = _Admin()
    app = _managed_app(tmp_path, admin)
    app.sequencer._update_known_selection(_items())
    app._managed = True

    app.halt_all_sync("the NAS is being rebuilt")
    assert admin.paused_state == {"s-a": True, "s-b": True}
    admin.pause_calls.clear()

    # shutdown()'s stop call, and the drive guard's pause.
    app._stop_lanes()
    app._root_pause_lanes()
    assert [c for c in admin.pause_calls if c[1] is False] == []
    assert admin.paused_state == {"s-a": True, "s-b": True}


def test_a_restart_with_a_persisted_halt_re_pauses_the_folders(tmp_path):
    admin = _Admin()
    first = _managed_app(tmp_path, admin)
    first.halt_all_sync("stopped from the tray on this machine")

    # What the outgoing (older) build did in its shutdown: released one.
    admin.paused_state = {"s-a": False, "s-b": True}
    admin.pause_calls.clear()

    revived = _managed_app(tmp_path, admin)
    assert revived.halt.active
    # A fresh sequencer knows no selection; only selection.json does.
    assert revived.sequencer.expected_folder_slugs() == []
    revived._start_lanes()
    _join_repause(revived)

    assert revived._lanes_started is False
    # Only the running one is written: the paused one costs nothing.
    assert admin.pause_calls == [("s-a", True)]
    assert admin.paused_state == {"s-a": True, "s-b": True}


def _join_repause(app, timeout=10.0):
    thread = getattr(app, "_halt_repause_thread", None)
    if thread is not None:
        thread.join(timeout)
        assert not thread.is_alive()


def test_a_halt_engaged_before_the_sequencer_ever_ran_pauses_the_projects(tmp_path):
    """bug-comp-app-1 review (2026-09-24): the EULA gate, a config problem
    or nobody signed in keeps the sequencer from ever running while the
    reporter still delivers a fleet halt. halt_folder_ids() then names no
    project at all, and the halt paused nothing but the asset libraries."""
    admin = _Admin()
    admin.paused_state = {"s-a": False, "s-b": False}
    app = _managed_app(tmp_path, admin)
    assert app.sequencer.expected_folder_slugs() == []

    app.halt_all_sync("fleet halt", scope="fleet")

    assert admin.paused_state == {"s-a": True, "s-b": True}


def test_lifting_a_halt_after_a_restart_releases_what_the_restart_re_paused(tmp_path):
    """bug-comp-app-1 review (2026-09-24): the restart re-pauses from the
    cached selection, but release_for_halt released _last_selection, which a
    sequencer that never ran does not have. With the lanes still refused on
    another gate (the tray's Pause), nothing released them: yet Pause is the
    button that deliberately leaves lane C running."""
    admin = _Admin()
    first = _managed_app(tmp_path, admin)
    first.halt_all_sync("stopped from the tray on this machine")
    admin.paused_state = {"s-a": False, "s-b": False}

    revived = _managed_app(tmp_path, admin)
    revived._paused = True
    revived._start_lanes()
    _join_repause(revived)
    assert admin.paused_state == {"s-a": True, "s-b": True}

    ok, _message = revived.release_halt(by="tray")
    assert ok
    _join_repause(revived)
    assert revived._lanes_started is False  # still refused: the tray's Pause
    assert admin.paused_state == {"s-a": False, "s-b": False}


def test_the_halt_release_fallback_still_holds_an_unfiltered_folder(tmp_path):
    """The release from the cached selection goes through the same ignores
    check as _startup_unpause: a folder with no .stignore stays paused."""
    admin = _Admin()
    admin.paused_state = {"s-a": True, "s-b": True}
    real_get = admin.get_ignores
    admin.get_ignores = lambda fid: ({"ignore": [], "expanded": []}
                                     if fid == "s-b" else real_get(fid))
    seq = _sequencer(admin, lambda: False)
    seq.stop()  # a never-run, stopped sequencer: its stop latch is set
    seq.release_for_halt()
    assert admin.paused_state == {"s-a": False, "s-b": True}


def test_starting_the_lanes_does_not_wait_on_a_hung_syncthing(tmp_path):
    """bug-comp-app-1 review (2026-09-24): the re-pause runs on the startup
    path, ahead of the tray and the reporter. Against a Syncthing that hangs
    it must not hold them up."""
    import threading

    release = threading.Event()

    class _HungAdmin(_Admin):
        def get_folders(self):
            release.wait(30)
            return super().get_folders()

    admin = _HungAdmin()
    first = _managed_app(tmp_path, _Admin())
    first.halt_all_sync("stopped from the tray on this machine")
    admin.paused_state = {"s-a": False, "s-b": False}

    revived = _managed_app(tmp_path, admin)
    caller = threading.Thread(target=revived._start_lanes, daemon=True)
    caller.start()
    caller.join(3.0)
    hung = caller.is_alive()
    release.set()
    caller.join(10.0)
    _join_repause(revived)
    assert not hung
    assert admin.paused_state == {"s-a": True, "s-b": True}


def test_no_halt_means_no_re_pause(tmp_path):
    admin = _Admin()
    admin.paused_state = {"s-a": False}
    app = _managed_app(tmp_path, admin)
    assert not app.halt.active
    assert app._reassert_halt_pause() == 0
    assert admin.pause_calls == []


# -- round 2 (2026-09-25) -----------------------------------------------------

def _borrowing_items():
    items = _items()
    items[0]["includes"] = [{
        "subpath": "2026/FF5/Lender/Interviewees", "sub_rel": "Interviewees",
        "lender_slug": "s-l",
    }]
    return items


class _LenderAdmin(_Admin):
    """A Syncthing that also carries the lender folder s-l, already accepted
    and restricted the way BorrowedFolderManager leaves it."""

    def __init__(self):
        super().__init__()
        from ccsync_companion.sync.borrowed_folders import local_path_for
        from ccsync_companion.sync.syncthing_admin import restricted_ignore_lines
        self._lender_path = local_path_for(str(_ROOT), "2026/FF5/Lender")
        self._lender_ignores = restricted_ignore_lines(["Interviewees"])

    def get_folder(self, folder_id):
        return {"id": folder_id, "path": self._lender_path,
                "paused": self.paused_state.get(folder_id, False)}

    def get_ignores(self, folder_id):
        if folder_id == "s-l":
            return {"ignore": list(self._lender_ignores), "expanded": []}
        return super().get_ignores(folder_id)

    def set_ignores(self, folder_id, lines):
        raise AssertionError("the lender's ignores were already restricted")

    def ensure_versioning(self, folder_id, folder=None):
        return False

    def ensure_ignore_delete(self, folder_id, folder=None):
        return False


def test_lifting_a_halt_after_a_restart_releases_the_borrowed_lender_too(tmp_path):
    """bug-comp-app-1 round 2 (2026-09-25): the restart re-pause pauses the
    lender folders it derives from selection.json, but release_for_halt's
    borrowed reconcile read the ADOPTED lender map, empty in a sequencer that
    never ran. The projects came back; the lender stayed paused for as long
    as the tray's Pause held."""
    admin = _LenderAdmin()
    items = _borrowing_items()

    def _app():
        app = _managed_app(tmp_path, admin, seq=None)
        app.sequencer = _sequencer(admin, lambda: app.halt.active, items=items)
        return app

    first = _app()
    first.halt_all_sync("stopped from the tray on this machine")
    admin.paused_state = {"s-a": False, "s-b": False, "s-l": False}

    revived = _app()
    revived._paused = True
    revived._start_lanes()
    _join_repause(revived)
    assert admin.paused_state == {"s-a": True, "s-b": True, "s-l": True}

    ok, _message = revived.release_halt(by="tray")
    assert ok
    assert revived._lanes_started is False  # still refused: the tray's Pause
    assert admin.paused_state == {"s-a": False, "s-b": False, "s-l": False}
    # Lent for the one reconcile, not adopted.
    assert revived.sequencer.borrowed_lenders() == {}


def test_the_lender_release_still_holds_an_unrestricted_lender(tmp_path):
    """The fallback goes through the manager's own restricted-ignores check:
    a lender whose .stignore cannot be confirmed restricted stays paused."""
    admin = _LenderAdmin()
    admin.paused_state = {"s-a": True, "s-b": True, "s-l": True}
    admin._lender_ignores = []  # not restricted, and the re-assert fails below

    def _refuse(folder_id, lines):
        raise OSError("Syncthing refused the write")

    admin.set_ignores = _refuse
    seq = _sequencer(admin, lambda: False, items=_borrowing_items())
    seq.stop()
    seq.release_for_halt()
    assert admin.paused_state == {"s-a": False, "s-b": False, "s-l": True}


def test_a_halt_whose_folder_list_cannot_be_read_writes_each_folder_once(tmp_path):
    """bug-comp-app-1 round 2 (2026-09-25): with the list unreadable the
    re-pause names every folder unfiltered, and halt_all_sync wrote each one
    a second time on the reporter thread: N x 30 s + 5 s + N x 30 s against a
    Syncthing that hangs."""

    class _NoListAdmin(_Admin):
        def get_folders(self):
            raise OSError("Syncthing is not answering")

    admin = _NoListAdmin()
    app = _managed_app(tmp_path, admin)
    app.sequencer._update_known_selection(_items())

    app.halt_all_sync("fleet halt", scope="fleet")

    assert admin.pause_calls == [("s-a", True), ("s-b", True)]
