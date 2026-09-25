"""Wave 2 of the 2026-09-24 hunt's fix pass, group c-sync (2026-09-25).

bug-comp-rclone-2, bug-comp-rclone-3, bug-comp-syncthing-1..4 and
bug-comp-core-5 (chunk 1); logic-sync-truth-3, bug-comp-rclone-4/-5,
bug-comp-syncthing-5/-6/-7 and logic-plans-5 (chunk 2). Nothing here starts a thread against a real Syncthing,
rclone, Resolve or Tk.
"""

from __future__ import annotations

import errno
import tempfile
from pathlib import Path
from types import SimpleNamespace

from ccsync_companion import file_moves, manifest
from ccsync_companion.sync import lane_guard
from ccsync_companion.sync.rclone_lane import RcloneLane
from ccsync_companion.sync.sequencer import Sequencer
from ccsync_companion.sync.syncthing_admin import STIGNORE_LINES, SyncthingAdmin

GB = 1024 ** 3


# -- bug-comp-rclone-2: followed moves never reach the cumulative counter ----

def test_sub_eager_followed_moves_do_not_fill_the_slow_leak_counter(tmp_path):
    breaker = lane_guard.LaneBBreaker(tmp_path / "breaker.json", {})
    probe_calls = []

    def probe():
        probe_calls.append(1)
        return 20

    # Twelve passes of 20 trashed files, every one of them placed by the
    # server somewhere else in the tree. Below the eager threshold (25), so
    # the probe is never spent -- the known figure is what must count.
    for _ in range(12):
        assert breaker.note_pass("2026/FF5/P", 20, 0, 100,
                                 relocation_probe=probe, known_relocated=20) is None
    assert breaker.report()["deletes"] == 0
    # Two real deletions afterwards are two, not "a slow leak of 202".
    assert breaker.note_pass("2026/FF5/P", 2, 0, 100, relocation_probe=probe) is None
    assert not breaker.tripped
    assert breaker.report()["deletes"] == 2


def test_the_known_figure_is_clamped_and_never_double_counted(tmp_path):
    breaker = lane_guard.LaneBBreaker(tmp_path / "breaker.json", {})
    # A figure larger than the pass cannot talk the counter below zero.
    assert breaker.note_pass("s", 3, 0, 0, known_relocated=99) is None
    assert breaker.report()["deletes"] == 0
    # 60 trashed, 10 placed by the server, and the probe (which counts those
    # 10 again plus 5 found in the scope) answers 15: 45 real deletions, under
    # the per-pass cap of 50, and the counter holds 45, not 35 -- the server's
    # 10 are not taken off twice.
    assert breaker.note_pass("s", 60, 0, 0, relocation_probe=lambda: 15,
                             known_relocated=10) is None
    assert breaker.report()["deletes"] == 45


def test_a_mixed_known_and_probe_pass_over_the_eager_threshold_still_probes(tmp_path):
    # Review round (2026-09-25): 30 trashed, 10 of them moved to another
    # project and located by the server, 20 re-rendered at the same path (only
    # the probe sees those). The RAW count (30) is over the eager threshold
    # (25); discounting the 10 first used to leave 20, under it, and the probe
    # never ran, so the 20 stayed on the cumulative counter for good.
    breaker = lane_guard.LaneBBreaker(tmp_path / "breaker.json", {})
    calls = []

    def probe():
        calls.append(1)
        return 30

    assert breaker.note_pass("s", 30, 0, 0, relocation_probe=probe,
                             known_relocated=10) is None
    assert calls == [1]
    assert breaker.report()["deletes"] == 0


def test_a_pass_under_the_eager_threshold_still_skips_the_probe(tmp_path):
    # Control: a raw count under the threshold keeps the probe lazy.
    breaker = lane_guard.LaneBBreaker(tmp_path / "breaker.json", {})
    calls = []
    assert breaker.note_pass("s", 24, 0, 0,
                             relocation_probe=lambda: calls.append(1) or 24,
                             known_relocated=4) is None
    assert calls == []
    assert breaker.report()["deletes"] == 20


def test_the_lane_hands_the_servers_placements_to_the_breaker():
    seen = {}

    class _Breaker:
        def note_pass(self, scope, deleted, moved_bytes, local_proxies,
                      relocation_probe=None, known_relocated=0):
            seen["known"] = known_relocated
            return None

    lane = RcloneLane.__new__(RcloneLane)
    lane.direction = "down"
    lane.name = "B"
    lane.breaker = _Breaker()
    lane._server_relocated_count = 7
    lane._last_backup_dir = None
    lane._backup_dir_bytes = lambda: 0
    assert lane._account_pass(SimpleNamespace(deleted=9), "Projects/x", 0) is False
    assert seen["known"] == 7


# -- bug-comp-rclone-3: the free-space park ----------------------------------

def test_a_parked_floor_says_the_current_free_space(tmp_path):
    latch = lane_guard.DiskFloorLatch(tmp_path / "floor.json", {})
    assert latch.check(10 * GB) is not None
    reason = latch.check(25 * GB)
    assert "25 GB free" in reason
    assert "10 GB" not in reason
    assert "40 GB" in reason          # what it is actually waiting for
    assert latch.report()["reason"] == reason
    assert latch.parked
    # Still under the floor: the plain sentence, with today's figure.
    assert latch.check(12 * GB) == ("this drive has 12 GB free, and proxy download "
                                     "needs 20 GB")
    assert latch.check(41 * GB) is None and not latch.parked


def test_the_disk_pressure_prune_works_towards_the_clear_threshold_while_parked(tmp_path):
    latch = lane_guard.DiskFloorLatch(tmp_path / "floor.json", {})
    lane = SimpleNamespace(disk_floor=latch)
    target = RcloneLane._prune_free_target
    assert target(lane) == 20 * GB
    latch.check(10 * GB)
    assert target(lane) == 40 * GB
    assert target(SimpleNamespace(disk_floor=None)) == 0


def test_a_prune_to_the_clear_threshold_releases_the_park(tmp_path):
    """End to end: 10 GB free, three 10 GB recovery batches. Pruned to the
    1x floor the park never cleared; pruned to the target it does."""
    latch = lane_guard.DiskFloorLatch(tmp_path / "floor.json", {})
    root = tmp_path / "root"
    trash = root / lane_guard.TRASH_DIR_NAME
    for i, stamp in enumerate(("20260901-100000", "20260902-100000", "20260903-100000")):
        (trash / stamp).mkdir(parents=True)
        (trash / stamp / "f.mp4").write_bytes(b"x")
    free = {"v": 10 * GB}
    latch.check(free["v"])

    real_remove = lane_guard._remove_tree

    def remove(path, size, why):
        free["v"] += 15 * GB
        return real_remove(path, size, why)

    lane = SimpleNamespace(disk_floor=latch)
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(lane_guard, "_remove_tree", remove)
    try:
        lane_guard.prune_trash(str(root), max_age_days=0, max_bytes=0,
                               min_free_bytes=RcloneLane._prune_free_target(lane),
                               free_bytes_fn=lambda _p: free["v"])
    finally:
        mp.undo()
    assert free["v"] >= 40 * GB
    assert latch.check(free["v"]) is None


# -- bug-comp-syncthing-1: a proxy that will not follow ---------------------

def _move(move_id=7):
    return {"id": move_id, "from_project_rel": "2026/FF5", "from_rel": "A001.mov",
            "to_project_rel": "2026/FF5", "to_rel": "Selects/A001.mov",
            "is_dir": False, "requested_by": "your administrator"}


def _locked_proxy(monkeypatch):
    real = Path.replace

    def replace(self, target):
        if self.parent.name == "Proxy":
            raise PermissionError(errno.EACCES, "WinError 32: in use", str(self))
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace)


def test_a_locked_proxy_does_not_turn_a_moved_original_into_a_failed_move(
        tmp_path, monkeypatch):
    project = tmp_path / "Projects" / "2026" / "FF5"
    (project / "Proxy").mkdir(parents=True)
    (project / "A001.mov").write_bytes(b"footage")
    (project / "Proxy" / "A001.mp4").write_bytes(b"proxy")
    ledger = file_moves.FileMoveLedger(tmp_path / "state")
    _locked_proxy(monkeypatch)

    ok, detail, paths = file_moves.apply_move(_move(), str(tmp_path), ledger=ledger)

    assert ok is True
    assert paths == (str(project / "A001.mov"), str(project / "Selects" / "A001.mov"))
    assert (project / "Selects" / "A001.mov").is_file()
    assert "1 proxy file(s) were in use" in detail
    assert (project / "Proxy" / "A001.mp4").is_file()     # left, not lost


def test_a_redelivery_after_an_old_builds_failed_attempt_still_relinks(tmp_path):
    """The row a 0.9.77 attempt left: intent paths, state retryable, the
    original already at the new path. The redelivery must answer with the
    paths, not "nothing at the old path"."""
    project = tmp_path / "Projects" / "2026" / "FF5"
    (project / "Selects").mkdir(parents=True)
    (project / "Selects" / "A001.mov").write_bytes(b"footage")
    ledger = file_moves.FileMoveLedger(tmp_path / "state")
    move = _move()
    src, dest = str(project / "A001.mov"), str(project / "Selects" / "A001.mov")
    ledger.record_intent(move, src, dest)
    ledger.record_attempt_failed(move, "could not move it on this machine: [Errno 32]")
    assert ledger.entry(move["id"])["state"] == file_moves.STATE_RETRYABLE

    ok, detail, paths = file_moves.apply_move(move, str(tmp_path), ledger=ledger)

    assert ok is True and paths == (src, dest)
    assert "interrupted" in detail


def test_a_failed_row_for_other_paths_is_not_evidence(tmp_path):
    project = tmp_path / "Projects" / "2026" / "FF5"
    (project / "Selects").mkdir(parents=True)
    (project / "Selects" / "A001.mov").write_bytes(b"footage")
    ledger = file_moves.FileMoveLedger(tmp_path / "state")
    move = _move()
    ledger.record_intent(move, str(project / "Other.mov"), str(project / "Elsewhere.mov"))
    ledger.record_attempt_failed(move, "nope")
    ok, detail, paths = file_moves.apply_move(move, str(tmp_path), ledger=ledger)
    assert ok is True and paths is None
    # ui-copy-4 (owed round): "computer" in the answer an editor reads.
    assert detail == "nothing at the old path on this computer"


# -- bug-comp-syncthing-2 / -3: borrowing honours the tick's mode ------------

_ROOT = Path(tempfile.gettempdir()) / "ccsync-tests-w2-c-sync-root"
_ROOT.mkdir(parents=True, exist_ok=True)


class _Lane:
    name = "fake"

    def run_once(self, subpath=None):
        return None


class _Selection:
    enabled = True

    def __init__(self, items):
        self.items = items

    def get(self):
        return self.items, "live"

    def load_cached(self):
        return list(self.items)


class _NoSharedFolders:
    def folder_ids(self):
        return []

    def reconcile(self, *a, **kw):
        return None


def _seq(items, admin=None, halted=None):
    return Sequencer(
        _Lane(), _Lane(), admin or _Admin(), _Selection(items),
        {"local_root": str(_ROOT), "shared_folders_enabled": False},
        shared_folders=_NoSharedFolders(), halted=halted,
    )


def _borrower(mode="full", covered=False):
    return {"slug": "s-borrower", "label": "Borrower", "rel_path": "2026/FF5/Borrower",
            "position": 0, "active": True, "sync_mode": mode,
            "includes": [{"subpath": "2026/FF5/Lender/Interviewees",
                          "sub_rel": "Interviewees", "lender_slug": "s-lender",
                          "lender_label": "2026/FF5/Lender", "covered": covered}]}


def _lender(mode):
    return {"slug": "s-lender", "label": "Lender", "rel_path": "2026/FF5/Lender",
            "position": 1, "active": True, "sync_mode": mode}


def test_an_upload_only_borrower_borrows_nothing():
    seq = _seq([_borrower("upload_only")])
    seq._update_known_selection([_borrower("upload_only")])
    assert seq.borrowed_lenders() == {}
    assert seq._borrowed_includes("s-borrower") == []
    assert "2026/FF5/Lender/Interviewees" not in seq.known_rels()


def test_a_full_borrower_of_an_upload_only_lender_gets_the_subtree():
    # The dashboard (up to 0.7.58) marks the include covered because the
    # lender is ticked, in any mode.
    items = [_borrower("full", covered=True), _lender("upload_only")]
    seq = _seq(items)
    seq._update_known_selection(items)
    subs = [i["subpath"] for i in seq._borrowed_includes("s-borrower")]
    assert subs == ["2026/FF5/Lender/Interviewees"]
    lenders = seq.borrowed_lenders()
    assert lenders["s-lender"]["subs"] == ["Interviewees"]
    # ...and an uncovered include (a fixed dashboard) arrives at the same place.
    items = [_borrower("full", covered=False), _lender("upload_only")]
    seq._update_known_selection(items)
    assert [i["subpath"] for i in seq._borrowed_includes("s-borrower")] == subs


def test_a_full_lender_still_covers_its_borrower():
    items = [_borrower("full", covered=True), _lender("full")]
    seq = _seq(items)
    seq._update_known_selection(items)
    assert seq._borrowed_includes("s-borrower") == []
    assert seq.borrowed_lenders() == {}
    # Uncovered but under a FULL selected rel: still dropped.
    items = [_borrower("full", covered=False), _lender("full")]
    seq._update_known_selection(items)
    assert seq._borrowed_includes("s-borrower") == []


# -- bug-comp-syncthing-4: nothing the sequencer does unpauses under a halt --

class _Admin:
    def __init__(self):
        self.pause_calls: list[tuple[str, bool]] = []
        self.paused_state: dict[str, bool] = {}

    def set_folder_paused(self, folder_id, paused):
        self.pause_calls.append((folder_id, paused))
        self.paused_state[folder_id] = paused

    def get_folders(self):
        return [{"id": fid, "paused": p} for fid, p in self.paused_state.items()]

    def get_config(self):
        return {"folders": self.get_folders()}

    def get_ignores(self, folder_id):
        return {"ignore": list(STIGNORE_LINES), "expanded": []}

    def ensure_max_folder_concurrency(self, value):
        return True


def test_a_late_verify_does_not_release_a_folder_the_halt_paused():
    halted = {"v": False}
    admin = _Admin()
    seq = _seq([_lender("full")], admin=admin, halted=lambda: halted["v"])
    # The halt lands while the old worker is still inside a slow call, and
    # pauses the folder; the worker then comes back to its verify.
    halted["v"] = True
    admin.paused_state["s-lender"] = True
    seq._verify_current_folder_unpaused("s-lender")
    assert admin.paused_state["s-lender"] is True
    assert ("s-lender", False) not in admin.pause_calls
    assert seq._set_paused("s-lender", False) is False
    # Once the halt is lifted the same call works.
    halted["v"] = False
    seq._verify_current_folder_unpaused("s-lender")
    assert admin.paused_state["s-lender"] is False


def test_accept_folder_leaves_the_folder_paused_when_a_halt_arrived_meanwhile():
    admin = SyncthingAdmin.__new__(SyncthingAdmin)
    calls = []
    admin._ignores_unconfirmed = set()
    admin._write_request = lambda method, path, body=None: calls.append((method, path))
    admin.set_ignores = lambda folder_id, lines: calls.append(("ignores", folder_id))
    admin.set_folder_paused = lambda folder_id, paused: calls.append(("paused", paused))

    halted = {"v": False}

    def ignores(folder_id, lines):
        calls.append(("ignores", folder_id))
        halted["v"] = True          # the halt engages during the slow write

    admin.set_ignores = ignores
    admin.accept_folder("s-x", "2026/X", "/tmp/x", "DEV",
                        release_ok=lambda: not halted["v"])
    assert ("paused", False) not in calls
    # Without the predicate (an older caller) the unpause is unchanged.
    calls.clear()
    admin.accept_folder("s-y", "2026/Y", "/tmp/y", "DEV")
    assert calls[-1] == ("paused", False)


def test_the_sequencer_hands_accept_folder_its_halt_predicate():
    seen = {}

    class _Accepting(_Admin):
        def pending_folders(self):
            return {"s-lender": {"offeredBy": {"DEV": {}}}}

        def accept_folder(self, folder_id, label, local_path, offered_by_device_id,
                          ignore_lines=None, release_ok=None):
            seen["release_ok"] = release_ok

    halted = {"v": False}
    seq = _seq([_lender("full")], admin=_Accepting(), halted=lambda: halted["v"])
    assert seq._maybe_auto_accept("s-lender", "2026/FF5/Lender") is True
    assert seen["release_ok"]() is True
    halted["v"] = True
    assert seen["release_ok"]() is False


# -- bug-comp-core-5: a drive pulled mid-scan --------------------------------

def test_a_scan_the_drive_vanished_under_is_discarded(tmp_path, monkeypatch):
    present = iter([True, False])
    cache = manifest.ManifestCache({"local_root": str(tmp_path)},
                                   root_present_fn=lambda: next(present))
    good = {"2026/FF5/P": {"n_originals": 40, "bytes_originals": 4, "n_proxies": 40,
                           "bytes_proxies": 4, "truncated": False,
                           "originals": None, "proxies": None}}
    cache._cache = dict(good)
    zeros = {"2026/FF5/P": {**good["2026/FF5/P"], "n_originals": 0, "n_proxies": 0}}
    monkeypatch.setattr(manifest, "scan_local_manifest",
                        lambda *a, **kw: dict(zeros))
    cache.refresh_once()
    assert cache.get() == good


def test_a_scan_with_the_drive_still_there_replaces_the_cache(tmp_path, monkeypatch):
    cache = manifest.ManifestCache({"local_root": str(tmp_path)},
                                   root_present_fn=lambda: True)
    fresh = {"2026/FF5/P": {"n_originals": 1}}
    monkeypatch.setattr(manifest, "scan_local_manifest", lambda *a, **kw: dict(fresh))
    cache.refresh_once()
    assert cache.get() == fresh


# ===========================================================================
# Chunk 2 of 2 (2026-09-25): logic-sync-truth-3, bug-comp-rclone-4/-5,
# bug-comp-syncthing-5/-6/-7, logic-plans-5. (logic-sync-truth-4 is
# bug-comp-rclone-3 above: test_a_prune_to_the_clear_threshold_releases_the_park.)
# ===========================================================================

import fnmatch
import json
import unicodedata

from ccsync_companion import selection as selection_mod
from ccsync_companion.selection import SelectionClient
from ccsync_companion.sync import rclone_lane as rl
from ccsync_companion.sync import shared_folders
from ccsync_companion.sync import syncthing_admin
from ccsync_companion.sync import syncthing_lane
from ccsync_companion.sync.base import STATE_SYNCING
from ccsync_companion.sync.syncthing_admin import ASSET_STIGNORE_LINES, LUTS_FOLDER_ID

_NFC_NAME = "Matej Šimalčík"
_NFD_NAME = unicodedata.normalize("NFD", _NFC_NAME)


# -- bug-comp-rclone-4: NFC folding at the two sites CR-90 missed ------------

def test_express_attributes_a_macs_nfd_path_to_its_nfc_project(tmp_path):
    assert _NFD_NAME != _NFC_NAME
    path = str(tmp_path / "Projects" / "2026" / "FF5" / _NFD_NAME / "Footage" / "a.mov")
    got = rl._project_rel_for_path(str(tmp_path), path, [f"2026/FF5/{_NFC_NAME}"])
    # The dashboard's spelling comes back, because it becomes the NAS subpath.
    assert got == f"Projects/2026/FF5/{_NFC_NAME}"


def test_a_ticked_project_spelled_nfd_on_disk_is_not_a_stray(tmp_path, monkeypatch):
    (tmp_path / "local").mkdir()
    lane = RcloneLane(direction=rl.DIRECTION_UP, local_root=str(tmp_path / "local"),
                      remote="nas", remote_root="CC", state_dir=tmp_path / "state")
    lane.known_rels_fn = lambda: [f"2026/FF5/{_NFC_NAME}"]
    on_disk = str(tmp_path / "local" / "Projects" / "2026" / "FF5" / _NFD_NAME)
    monkeypatch.setattr(rl, "scan_project_markers", lambda root: {"slug-1": on_disk})
    monkeypatch.setattr(rl, "_dir_size_bytes", lambda d, *a, **kw: 123)
    report = lane._refresh_stray_projects()
    assert report is not None and report["count"] == 0


def test_a_genuinely_unticked_project_is_still_a_stray(tmp_path, monkeypatch):
    (tmp_path / "local").mkdir()
    lane = RcloneLane(direction=rl.DIRECTION_UP, local_root=str(tmp_path / "local"),
                      remote="nas", remote_root="CC", state_dir=tmp_path / "state")
    lane.known_rels_fn = lambda: [f"2026/FF5/{_NFC_NAME}"]
    other = str(tmp_path / "local" / "Projects" / "2026" / "FF5" / "Other")
    monkeypatch.setattr(rl, "scan_project_markers", lambda root: {"slug-2": other})
    monkeypatch.setattr(rl, "_dir_size_bytes", lambda d, *a, **kw: 123)
    report = lane._refresh_stray_projects()
    assert report["count"] == 1 and report["paths"] == [other]


# -- bug-comp-rclone-5: a trashed file is a deletion, not also a transfer -----

def test_a_trash_only_pass_transfers_nothing():
    tally = rl.RcloneRunTally()
    for i in range(12):
        tally.feed_record({"level": "info", "msg": "Moved (server-side)",
                           "object": f"Proxy/{i}.mov"})
        tally.feed_record({"level": "info", "msg": "Moved into backup dir",
                           "object": f"Proxy/{i}.mov"})
    result = tally.result()
    assert (result.transferred, result.deleted) == (0, 12)
    assert result.completed_files == []


def test_a_mixed_pass_counts_each_file_once():
    tally = rl.RcloneRunTally()
    tally.feed_record({"level": "info", "msg": "Copied (new)", "object": "Proxy/new.mov"})
    tally.feed_record({"level": "info", "msg": "Proxy/old.mov: Moved into backup dir",
                       "object": "Proxy/old.mov"})
    tally.feed_record({"level": "info", "msg": "gone.mov: Deleted", "object": "gone.mov"})
    result = tally.result()
    assert (result.transferred, result.deleted) == (1, 2)
    assert result.completed_files == ["Proxy/new.mov"]


# -- bug-comp-syncthing-5: no backslash escapes in a Windows .stignore -------

def test_windows_negations_escape_with_classes_not_backslashes():
    sub = "Interviews [raw]/{b-roll}"
    lines = syncthing_admin.restricted_ignore_lines([sub], windows=True)
    negation = "!/Interviews [[]raw]/[{]b-roll[}]"
    assert negation in lines and negation + "/**" in lines
    assert not any("\\" in line for line in lines if line.startswith("!"))
    # The class form still names the folder LITERALLY under glob rules.
    assert fnmatch.fnmatchcase(sub, negation[2:])
    assert not fnmatch.fnmatchcase("Interviews r/b-roll", negation[2:])


def test_the_default_follows_this_machines_platform(monkeypatch):
    monkeypatch.setattr(syncthing_admin.os, "name", "nt")
    assert syncthing_admin.escape_ignore_glob("A [1]") == "A [[]1]"
    monkeypatch.setattr(syncthing_admin.os, "name", "posix")
    assert syncthing_admin.escape_ignore_glob("A [1]") == "A \\[1\\]"


def test_a_plain_name_is_unchanged_on_both_platforms():
    for windows in (True, False):
        assert syncthing_admin.escape_ignore_glob("2026/FF5/Interviewees",
                                                  windows=windows) == "2026/FF5/Interviewees"


# -- bug-comp-syncthing-6: the cached plan belongs to one editor -------------

_PLAN_A = [{"slug": "a-proj", "label": "2026/FF5/A", "rel_path": "2026/FF5/A",
            "position": 0, "active": True}]


def _client(tmp_path, who, http_get):
    cfg = {"editor_name": "x", "dashboard_url": "http://dash.example.com",
           "dashboard_token": "tok", "selection_fetch_ttl": 0.001}
    return SelectionClient(cfg, tmp_path, http_get=http_get,
                           editor_name_fn=lambda: who["name"])


def test_the_next_person_never_runs_the_previous_persons_cached_plan(tmp_path):
    who = {"name": "alice"}
    answer = {"fail": False}

    def http_get(url, headers, timeout):
        if answer["fail"]:
            raise OSError("dashboard restarting")
        return {"selection": list(_PLAN_A)}

    client = _client(tmp_path, who, http_get)
    assert client.get() == (_PLAN_A, "live")
    assert json.loads((tmp_path / "selection.json").read_text("utf-8"))["editor"] == "alice"

    who["name"] = "bob"
    answer["fail"] = True
    fresh = _client(tmp_path, who, http_get)          # a restart, as bob
    assert fresh.get() == (None, "none")
    assert fresh.load_cached() is None
    # ...but a reader that only PAUSES may still see it.
    assert fresh.load_cached(any_editor=True) == _PLAN_A


def test_the_same_person_still_falls_back_to_the_cache(tmp_path):
    who = {"name": "alice"}
    answer = {"fail": False}

    def http_get(url, headers, timeout):
        if answer["fail"]:
            raise OSError("down")
        return {"selection": list(_PLAN_A)}

    _client(tmp_path, who, http_get).get()
    answer["fail"] = True
    assert _client(tmp_path, who, http_get).get() == (_PLAN_A, "cache")
    who["name"] = ""                                   # no identity yet
    assert _client(tmp_path, who, http_get).get() == (_PLAN_A, "cache")


def test_a_cache_from_before_the_key_is_still_read(tmp_path):
    (tmp_path / "selection.json").write_text(
        json.dumps({"fetched_at": "2026-09-01T00:00:00+00:00",
                    "response": {"selection": _PLAN_A}}), encoding="utf-8")

    def http_get(url, headers, timeout):
        raise OSError("down")

    assert _client(tmp_path, {"name": "bob"}, http_get).get() == (_PLAN_A, "cache")


def test_an_identical_plan_for_a_new_person_still_rewrites_the_owner(tmp_path):
    who = {"name": "alice"}

    def http_get(url, headers, timeout):
        return {"selection": list(_PLAN_A)}

    client = _client(tmp_path, who, http_get)
    client.fetch(force=True)
    who["name"] = "bob"
    client.fetch(force=True)
    assert json.loads((tmp_path / "selection.json").read_text("utf-8"))["editor"] == "bob"


# -- logic-plans-5: an untick the dashboard could not place is not "done" ----
#
# Review round (2026-09-25): the first fix widened to the person when the
# hostname was missing from `machines`. The real case is a renamed PC in
# SYS-18a's deferred-adoption window, where the NEW name IS registered (the
# refused report still upserts it), so that test never fired. These build the
# dashboard's actual answer for that window: `machines` names both computers,
# the machine-scoped DELETE removed nothing, and the tick stands under the
# old name (visible only in the person's union).

def _untick_client(tmp_path, monkeypatch, answers, person=None):
    monkeypatch.setattr(selection_mod, "_machine_name", lambda: "NEW-PC")
    gets = []

    def http_get(url, headers, timeout):
        gets.append(url)
        if isinstance(person, Exception):
            raise person
        return person

    client = _client(tmp_path, {"name": "alice"}, http_get)
    calls = []

    def fake_delete(url):
        calls.append(url)
        return answers[len(calls) - 1]

    monkeypatch.setattr(client, "_delete_selection", fake_delete)
    return client, calls, gets


_NOTHING_HERE = (True, "unticked",
                 {"changed": False, "machines": ["OLD-PC", "NEW-PC"], "selection": []}, 200)


def test_a_renamed_pc_whose_tick_stands_under_its_old_name_is_refused(tmp_path, monkeypatch):
    client, calls, gets = _untick_client(
        tmp_path, monkeypatch, [_NOTHING_HERE],
        person={"selection": [{"slug": "a-proj"}]})
    ok, message = client.untick("a-proj")
    assert not ok
    assert "NEW-PC" in message and "renamed" in message
    assert "—" not in message
    # Never widened: the person's other computers keep their tick.
    assert calls == ["http://dash.example.com/api/v1/selection/alice/a-proj?machine=NEW-PC"]
    assert gets == ["http://dash.example.com/api/v1/selection/alice"]


def test_a_forgotten_hostname_is_not_widened_to_the_person(tmp_path, monkeypatch):
    # The first fix's case (hostname missing from `machines`), which also
    # covers a computer an admin just forgot (CR-76): no person-wide DELETE.
    unknown = (True, "unticked",
               {"changed": False, "machines": ["OLD-PC"], "selection": []}, 200)
    client, calls, _gets = _untick_client(
        tmp_path, monkeypatch, [unknown], person={"selection": [{"slug": "a-proj"}]})
    ok, _message = client.untick("a-proj")
    assert not ok
    assert len(calls) == 1


def test_a_tick_already_gone_everywhere_is_still_unticked(tmp_path, monkeypatch):
    # Control: the tray's plan was stale and the tick is gone for every
    # computer. Nothing can bring the project back, so the delete may go on.
    client, calls, gets = _untick_client(
        tmp_path, monkeypatch, [_NOTHING_HERE], person={"selection": []})
    assert client.untick("a-proj") == (True, "unticked")
    assert len(calls) == 1 and len(gets) == 1


def test_cannot_tell_whether_another_computer_holds_it_is_refused(tmp_path, monkeypatch):
    client, calls, _gets = _untick_client(
        tmp_path, monkeypatch, [_NOTHING_HERE], person=OSError("down"))
    ok, message = client.untick("a-proj")
    assert not ok and "could not be asked" in message
    assert len(calls) == 1


def test_an_answer_without_changed_is_not_evidence(tmp_path, monkeypatch):
    # Control: a dashboard too old to send `changed` keeps the old answer and
    # is never asked the second question.
    old_dash = (True, "unticked", {"machines": ["NEW-PC"], "selection": []}, 200)
    client, calls, gets = _untick_client(
        tmp_path, monkeypatch, [old_dash], person={"selection": [{"slug": "a-proj"}]})
    assert client.untick("a-proj") == (True, "unticked")
    assert len(calls) == 1 and gets == []


def test_a_machine_scoped_removal_that_worked_asks_nothing_more(tmp_path, monkeypatch):
    worked = (True, "unticked",
              {"changed": True, "machines": ["NEW-PC"], "selection": []}, 200)
    client, calls, gets = _untick_client(
        tmp_path, monkeypatch, [worked], person={"selection": [{"slug": "a-proj"}]})
    assert client.untick("a-proj") == (True, "unticked")
    assert len(calls) == 1 and gets == []


# -- bug-comp-syncthing-7: re-pointing the LUT library ----------------------

class _LutAdmin:
    def __init__(self, path, paused=False):
        self.folder = {"id": LUTS_FOLDER_ID, "paused": paused, "path": path,
                       "versioning": {"type": "staggered"}, "ignoreDelete": True}
        self.calls = []

    def get_folder(self, folder_id):
        return dict(self.folder)

    def get_ignores(self, folder_id):
        return {"ignore": list(ASSET_STIGNORE_LINES)}

    def set_ignores(self, folder_id, lines):
        self.calls.append(("set_ignores",))

    def set_folder_paused(self, folder_id, paused):
        self.calls.append(("set_paused", paused))
        self.folder["paused"] = paused

    def set_folder_path(self, folder_id, path, label=None):
        self.calls.append(("set_path", path))
        self.folder["path"] = path

    def ensure_versioning(self, folder_id, folder=None):
        return False

    def ensure_ignore_delete(self, folder_id, folder=None):
        return False


_ONLY_LUTS = [(LUTS_FOLDER_ID, "Assets/Luts", "Assets/Luts (LUT library)")]


def test_a_repointed_library_carries_its_files_and_marker(tmp_path):
    old = tmp_path / "old_root" / "Assets" / "Luts"
    (old / ".stfolder").mkdir(parents=True)
    (old / "show.cube").write_text("LUT", encoding="utf-8")
    new_root = tmp_path / "new_root"
    new_root.mkdir()
    admin = _LutAdmin(str(old))
    moves = []

    def move(src, dst):
        moves.append((src, dst))
        import shutil
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)

    manager = shared_folders.SharedFolderManager(admin, new_root, folders=_ONLY_LUTS,
                                                 move_dir=move)
    assert manager.reconcile()[LUTS_FOLDER_ID] == "repaired"
    want = shared_folders.local_path_for(new_root, "Assets/Luts")
    assert moves == [(str(old), want)]
    assert (Path(want) / "show.cube").exists() and (Path(want) / ".stfolder").is_dir()
    # Paused BEFORE the path changed, released after, with the ignores confirmed.
    assert admin.calls[:2] == [("set_paused", True), ("set_path", want)]
    assert ("set_paused", False) in admin.calls
    assert manager.problems() == []


def test_a_repoint_with_nothing_to_carry_is_a_problem_until_the_marker_exists(tmp_path):
    admin = _LutAdmin(str(tmp_path / "nowhere" / "Luts"))
    now = {"t": 0.0}
    manager = shared_folders.SharedFolderManager(admin, tmp_path, folders=_ONLY_LUTS,
                                                 now=lambda: now["t"])
    assert manager.reconcile()[LUTS_FOLDER_ID] == "marker-missing"
    want = shared_folders.local_path_for(tmp_path, "Assets/Luts")
    assert Path(want).is_dir()                       # created, for Syncthing
    assert not (Path(want) / ".stfolder").exists()   # but never the marker
    # The next pass sees matching paths; it used to answer "ok" and clear
    # the problem while the library synced nothing.
    now["t"] += 10_000
    assert manager.reconcile()[LUTS_FOLDER_ID] == "marker-missing"
    assert manager.problems() and "Assets/Luts" in manager.problems()[0]
    assert "—" not in manager.problems()[0]
    # Syncthing (or an admin) puts the marker there: the problem clears.
    (Path(want) / ".stfolder").mkdir()
    now["t"] += 10_000
    assert manager.reconcile()[LUTS_FOLDER_ID] == "ok"
    assert manager.problems() == []


def test_a_repoint_onto_an_absent_root_changes_nothing(tmp_path):
    admin = _LutAdmin(str(tmp_path / "old" / "Luts"))
    manager = shared_folders.SharedFolderManager(
        admin, tmp_path / "unplugged", folders=_ONLY_LUTS, root_present_fn=lambda: True)
    assert manager.reconcile()[LUTS_FOLDER_ID] == "error"
    assert not any(c[0] == "set_path" for c in admin.calls)
    assert not (tmp_path / "unplugged").exists()


def test_the_sequencer_hands_the_shared_manager_a_mover():
    from ccsync_companion.sync.repath import _default_move
    seq = Sequencer(_Lane(), _Lane(), _Admin(), _Selection([]),
                    {"local_root": str(_ROOT)})
    assert seq.shared_folders._move_dir is _default_move


class _ForeignCache(_Selection):
    """A cache written for the previous person: refused unless asked for
    by a reader that only pauses."""

    def load_cached(self, any_editor=False):
        return list(self.items) if any_editor else None


def test_the_halt_repause_still_pauses_the_previous_persons_folders():
    item = {"slug": "prev-proj", "label": "2026/FF5/Prev", "rel_path": "2026/FF5/Prev",
            "position": 0, "active": True}
    admin = _Admin()
    admin.paused_state["prev-proj"] = False      # still configured, still running
    seq = Sequencer(_Lane(), _Lane(), admin, _ForeignCache([item]),
                    {"local_root": str(_ROOT), "shared_folders_enabled": False},
                    shared_folders=_NoSharedFolders())
    assert "prev-proj" in seq.halt_folder_ids_to_repause()


# -- logic-sync-truth-3: lane C with nobody to sync with ---------------------

def _lane_c(conns):
    lane = syncthing_lane.SyncthingLane(base_url="http://127.0.0.1:1", api_key="k",
                                        expected_folder_ids=["proj-1"])
    folders = [{"id": "proj-1", "devices": [{"deviceID": "ME"}, {"deviceID": "NAS"}]}]

    def fake_get(path):
        if path == "/rest/system/ping":
            return {"ping": "pong"}
        if path == "/rest/system/connections":
            return conns["payload"]
        if path == "/rest/config":
            return {"folders": folders}
        if path.startswith("/rest/db/status"):
            return {"needTotalItems": 40}
        if path == "/rest/system/status":
            return {"myID": "ME"}
        if path.startswith("/rest/db/completion"):
            return {"needItems": 0, "needBytes": 0}
        if path == "/rest/cluster/pending/folders":
            return {}
        raise OSError(path)

    lane._get = fake_get
    return lane


def test_owed_files_with_no_peer_say_so_and_carry_a_still_token():
    conns = {"payload": {"connections": {"NAS": {"connected": False}},
                         "total": {"inBytesTotal": 100, "outBytesTotal": 50}}}
    lane = _lane_c(conns)
    first = lane.check_once()
    assert first.state == STATE_SYNCING and first.queued == 40
    assert "not connected to the server" in first.detail and "40" in first.detail
    assert first.progress_token == "c:150"
    # Nothing moves, so the token does not either: the dashboard's stall rule
    # can now fire for lane C.
    assert lane.check_once().progress_token == "c:150"


def test_a_connected_lane_moves_its_token_and_claims_nothing_odd():
    conns = {"payload": {"connections": {"NAS": {"connected": True, "type": "tcp-client"}},
                         "total": {"inBytesTotal": 100, "outBytesTotal": 50}}}
    lane = _lane_c(conns)
    first = lane.check_once()
    assert "not connected" not in first.detail
    conns["payload"]["total"]["inBytesTotal"] = 9_000
    assert lane.check_once().progress_token != first.progress_token


def test_an_unreadable_connection_list_claims_nothing():
    lane = _lane_c({"payload": None})
    real = lane._get

    def failing(path):
        if path == "/rest/system/connections":
            raise OSError("older Syncthing")
        return real(path)

    lane._get = failing
    status = lane.check_once()
    assert status.state == STATE_SYNCING
    assert "not connected" not in (status.detail or "")
    assert status.progress_token is None


# == OWED round (2026-09-25): items other groups left for c-sync =============



import time as _time

from ccsync_companion import drive_reminder as _dr
from ccsync_companion.sync.base import LaneStatus as _LaneStatus


# -- logic-sync-truth-6 (b): the recurring drive reminder is for uploads -----

class _Balloons:
    def __init__(self):
        self.sent = []

    def __call__(self, message, title):
        self.sent.append(message)


def _drive(tmp_path, interval=0.05):
    notes = _Balloons()
    reminder = _dr.DriveReminder(
        notify_fn=notes, drive_phrase_fn=lambda: "Your Studio drive",
        interval=interval, state_path=tmp_path / "state" / _dr.STATE_FILENAME)
    return reminder, notes


def _wait_for_more_reminders(reminder, than=0, seconds=0.5):
    deadline = _time.monotonic() + seconds
    while _time.monotonic() < deadline and reminder.reminders_sent <= than:
        _time.sleep(0.02)


def _summary(*statuses):
    work = _dr.unfinished_work(list(statuses))
    return work.summary(), work.lanes


def test_a_download_only_episode_warns_once_and_does_not_recur(tmp_path):
    summary, lanes = _summary(
        _LaneStatus(name="lane_b_proxy_down", state="syncing", transferring=3),
        _LaneStatus(name="lane_c_syncthing", state="syncing", queued=14,
                    direction="down"))
    assert summary == "3 proxy downloads and 14 other file downloads"
    reminder, notes = _drive(tmp_path)
    try:
        reminder.begin(summary, lanes=lanes)
        _wait_for_more_reminders(reminder)
        # The first warning, and nothing after it: nothing owed is footage
        # whose only copy is on the drive.
        assert len(notes.sent) == 1
        assert "disconnected before syncing finished" in notes.sent[0]
        assert reminder.reminders_sent == 0
        assert reminder.active and reminder.summary == summary
        # Settings then says no reminder is coming instead of offering to
        # mute one.
        assert reminder.reminders_muted
    finally:
        reminder.clear()


def test_the_bare_summary_app_py_passes_is_enough_to_tell(tmp_path):
    """app.py hands begin() the summary string alone; the lanes are read back
    from it, so the fix works without a change to the caller."""
    summary, _lanes = _summary(
        _LaneStatus(name="lane_b_proxy_down", state="syncing", transferring=1,
                    bytes_total=3_000_000_000, bytes_done=500_000_000))
    assert "GB left" in summary        # the byte clause must not read as a lane
    reminder, notes = _drive(tmp_path)
    try:
        reminder.begin(summary)
        _wait_for_more_reminders(reminder)
        assert reminder.reminders_sent == 0 and len(notes.sent) == 1
    finally:
        reminder.clear()


def test_an_owed_upload_still_recurs(tmp_path):
    summary, lanes = _summary(
        _LaneStatus(name="lane_a_video_up", state="syncing", transferring=2),
        _LaneStatus(name="lane_b_proxy_down", state="syncing", transferring=3))
    for kw in ({"lanes": lanes}, {}):
        reminder, _notes = _drive(tmp_path)
        try:
            reminder.begin(summary, **kw)
            _wait_for_more_reminders(reminder)
            assert reminder.reminders_sent >= 1
            assert not reminder.reminders_muted
        finally:
            reminder.clear()


def test_the_lanes_survive_a_restart_and_keep_the_decision(tmp_path):
    summary, lanes = _summary(
        _LaneStatus(name="lane_b_proxy_down", state="syncing", transferring=2))
    first, _ = _drive(tmp_path)
    first.begin(summary, lanes=lanes)
    first.suspend()
    record = json.loads((tmp_path / "state" / _dr.STATE_FILENAME).read_text("utf-8"))
    assert record["lanes"] == ["lane_b_proxy_down"]

    again, notes = _drive(tmp_path)
    try:
        assert again.resume_remembered("absent")
        # One reminder at startup (it stands in for the "Sync paused" balloon
        # this start would otherwise give), then no cadence.
        assert len(notes.sent) == 1 and again.reminders_sent == 1
        _time.sleep(0.25)
        assert again.reminders_sent == 1
    finally:
        again.clear()


def test_a_record_from_before_lanes_were_kept_is_read_by_its_summary(tmp_path):
    path = tmp_path / "state" / _dr.STATE_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"summary": "2 uploads and 14 other files",
                                "sentence": "x", "kind": "unfinished"}), "utf-8")
    reminder, _notes = _drive(tmp_path)
    try:
        assert reminder.resume_remembered("absent")
        startup = reminder.reminders_sent
        _wait_for_more_reminders(reminder, than=startup)
        assert reminder.reminders_sent > startup
    finally:
        reminder.clear()


def test_a_lane_this_module_cannot_name_keeps_reminding():
    assert _dr.owes_an_upload(None, "3 files")
    assert _dr.owes_an_upload(None, "1 proxy download and 3 files (1.0 GB left)")
    assert not _dr.owes_an_upload(
        None, "1 proxy download and 2 other file downloads (2.3 GB left)")
    assert _dr.owes_an_upload(None, "1 upload")
    assert not _dr.owes_an_upload(["lane_c_syncthing:down"], "1 upload")  # lanes decide
    assert _dr.owes_an_upload(["lane_b_proxy_down", "lane_x_new"], "")


def test_a_snooze_on_a_download_only_episode_starts_no_cadence(tmp_path):
    summary, lanes = _summary(
        _LaneStatus(name="lane_c_syncthing", state="syncing", queued=4,
                    direction="down"))
    reminder, _notes = _drive(tmp_path)
    try:
        reminder.begin(summary, lanes=lanes)
        assert reminder.mute_episode(0.001)
        _time.sleep(0.3)
        assert reminder.reminders_sent == 0
    finally:
        reminder.clear()


def test_the_wedged_drive_reminder_is_unchanged(tmp_path):
    reminder, _notes = _drive(tmp_path)
    try:
        reminder.begin_state("not_answering",
                             _dr.wedged_reminder("Your Studio drive"))
        _wait_for_more_reminders(reminder)
        assert reminder.reminders_sent >= 1
    finally:
        reminder.clear()


# -- logic-sync-truth-6 review round: lane C is TWO-WAY ----------------------
# Lane C carries every non-video file UP (a recorder WAV, a project file),
# and one whose only copy is on the pulled drive is as much at risk as the
# footage, so its upload direction recurs like lane A.

def test_a_lane_c_upload_keeps_reminding(tmp_path):
    """The reviewer's case: lane C syncing with direction 'up', queued 0."""
    summary, lanes = _summary(
        _LaneStatus(name="lane_c_syncthing", state="syncing", queued=0,
                    direction="up"))
    assert summary == "1 other file upload"
    assert lanes == ["lane_c_syncthing:up"]
    for kw in ({"lanes": lanes}, {}):          # app.py passes the bare summary
        reminder, notes = _drive(tmp_path)
        try:
            reminder.begin(summary, **kw)
            _wait_for_more_reminders(reminder)
            assert reminder.reminders_sent >= 1, kw
            assert not reminder.reminders_muted
            assert "1 other file upload still to go" in notes.sent[0]
        finally:
            reminder.clear()


def test_a_lane_c_episode_with_no_known_direction_keeps_reminding(tmp_path):
    # No peer (""), both ways at once ("both"), and a lane status from a
    # build that sets no direction: the upload half cannot be ruled out.
    for direction in ("", "both"):
        summary, lanes = _summary(
            _LaneStatus(name="lane_b_proxy_down", state="syncing", transferring=2),
            _LaneStatus(name="lane_c_syncthing", state="syncing", queued=9,
                        direction=direction))
        assert summary == "2 proxy downloads and 9 other files"
        assert _dr.owes_an_upload(lanes, summary)
        assert _dr.owes_an_upload(None, summary)
    # A 0.9.77 record says "other files" with no lanes: it may be an upload.
    assert _dr.owes_an_upload(None, "14 other files")
    assert _dr.owes_an_upload(None, "1 proxy download and 2 other files (2.3 GB left)")


def test_a_lane_c_download_alone_still_does_not_recur():
    summary, lanes = _summary(
        _LaneStatus(name="lane_c_syncthing", state="syncing", queued=1,
                    direction="down"))
    assert summary == "1 other file download"
    assert not _dr.owes_an_upload(lanes, summary)
    assert not _dr.owes_an_upload(None, summary)


def test_the_lane_c_direction_survives_a_restart(tmp_path):
    summary, lanes = _summary(
        _LaneStatus(name="lane_c_syncthing", state="syncing", queued=5,
                    direction="up"))
    first, _ = _drive(tmp_path)
    first.begin(summary, lanes=lanes)
    first.suspend()
    record = json.loads((tmp_path / "state" / _dr.STATE_FILENAME).read_text("utf-8"))
    assert record["lanes"] == ["lane_c_syncthing:up"]
    again, _notes = _drive(tmp_path)
    try:
        assert again.resume_remembered("absent")
        startup = again.reminders_sent
        _wait_for_more_reminders(again, than=startup)
        assert again.reminders_sent > startup
    finally:
        again.clear()


# -- logic-sync-truth-6 (optional half): lane C says which way it moves -----

def _lane_c_owing(connected, need_down, need_up):
    conns = {"payload": {"connections": {"NAS": {"connected": connected}},
                         "total": {}}}
    lane = _lane_c(conns)
    real = lane._get

    def fake(path):
        if path.startswith("/rest/db/status"):
            return {"needTotalItems": need_down}
        if path.startswith("/rest/db/completion"):
            return {"needItems": need_up, "needBytes": need_up * 1000}
        return real(path)

    lane._get = fake
    return lane


def test_lane_c_names_its_direction():
    assert _lane_c_owing(True, 40, 0).check_once().direction == "down"
    # Both ways at once is not "down": the upload half is what the drive
    # reminder recurs on (review round).
    assert _lane_c_owing(True, 40, 3).check_once().direction == "both"
    status = _lane_c_owing(True, 0, 3).check_once()
    assert status.direction == "up" and "sending 3 file(s)" in status.detail
    # No peer: nothing moves either way, whatever is owed.
    assert _lane_c_owing(False, 0, 3).check_once().direction == ""
    # The snapshot copy every status() returns keeps it; an idle lane claims
    # none.
    assert _LaneStatus(**vars(status)).direction == "up"
    assert _lane_c_owing(True, 0, 0).check_once().direction == ""


# -- ui-copy-4: the move answers an editor reads say "computer" --------------

def test_the_file_move_answers_say_computer_not_machine_or_lane(tmp_path):
    # The shared vocabulary scan (docstrings, dict keys and log arguments
    # already subtracted), applied to this group's module.
    import test_sweep_2026_09_04_copy as _sweep
    offenders = [text for text in _sweep._sentences(Path(file_moves.__file__))
                 if _sweep._WORD_RE.search(text)]
    assert not offenders, offenders
    ok, detail, _paths = file_moves.apply_move(
        {"id": 1, "from_project_rel": "2026/FF5/A", "from_rel": "x.mov",
         "to_project_rel": "2026/FF5/A", "to_rel": "y.mov"}, str(tmp_path))
    assert ok and detail == "nothing at the old path on this computer"


# -- bug-dash-api-2: the proxy takes the moved file's NEW name ---------------

def _proxy_tree(tmp_path):
    root = tmp_path / "Projects" / "2026" / "FF5" / "P"
    (root / "Proxy").mkdir(parents=True)
    (root / "A001.braw").write_bytes(b"o")
    (root / "Proxy" / "A001.mov").write_bytes(b"p")
    return root


def test_a_renaming_move_renames_the_proxy(tmp_path):
    root = _proxy_tree(tmp_path)
    (root / "Sub").mkdir()
    ok, detail, _ = file_moves.apply_move(
        {"id": 2, "from_project_rel": "2026/FF5/P", "from_rel": "A001.braw",
         "to_project_rel": "2026/FF5/P", "to_rel": "Sub/Interview.braw"},
        str(tmp_path), project_rels=["2026/FF5/P"])
    assert ok and "1 proxy file(s)" in detail
    assert (root / "Sub" / "Proxy" / "Interview.mov").read_bytes() == b"p"
    assert not (root / "Sub" / "Proxy" / "A001.mov").exists()


def test_a_same_folder_rename_moves_the_proxy_too(tmp_path):
    root = _proxy_tree(tmp_path)
    ok, detail, _ = file_moves.apply_move(
        {"id": 3, "from_project_rel": "2026/FF5/P", "from_rel": "A001.braw",
         "to_project_rel": "2026/FF5/P", "to_rel": "Interview.braw"},
        str(tmp_path), project_rels=["2026/FF5/P"])
    assert ok and "1 proxy file(s)" in detail
    assert sorted(p.name for p in (root / "Proxy").iterdir()) == ["Interview.mov"]


def test_a_plain_move_keeps_the_proxy_name_and_never_overwrites(tmp_path):
    root = _proxy_tree(tmp_path)
    (root / "Sub" / "Proxy").mkdir(parents=True)
    (root / "Sub" / "Proxy" / "Interview.mov").write_bytes(b"theirs")
    assert file_moves.move_proxy_siblings(root / "A001.braw",
                                          root / "Sub" / "A001.braw") == 1
    assert (root / "Sub" / "Proxy" / "A001.mov").read_bytes() == b"p"
    (root / "Proxy" / "A001.mov").write_bytes(b"p2")
    # A renaming move onto a proxy that is already there leaves both alone.
    assert file_moves.move_proxy_siblings(root / "A001.braw",
                                          root / "Sub" / "Interview.braw") == 0
    assert (root / "Sub" / "Proxy" / "Interview.mov").read_bytes() == b"theirs"
    assert (root / "Proxy" / "A001.mov").read_bytes() == b"p2"


# -- logic-plans-1 (skew belt): a changed answer that still lists it --------

def test_a_changed_answer_that_still_lists_the_project_is_not_widened(
        tmp_path, monkeypatch):
    """A dashboard without its own logic-plans-1 fix materialised the bucket,
    removed this computer's copy and fell back to the bucket again. Widening
    then deleted every other computer's row for the project."""
    still = (True, "unticked", {"changed": True, "machines": ["NEW-PC"],
                                "selection": [{"slug": "a-proj"}]}, 200)
    client, calls, _gets = _untick_client(tmp_path, monkeypatch, [still])
    ok, message = client.untick("a-proj")
    assert not ok and "sync plan" in message
    assert "—" not in message
    assert len(calls) == 1                       # no person-wide DELETE


def test_the_pure_bucket_answer_still_widens(tmp_path, monkeypatch):
    for extra in ({"changed": False}, {}):
        still = (True, "unticked", {"machines": ["NEW-PC"],
                                    "selection": [{"slug": "a-proj"}], **extra}, 200)
        gone = (True, "unticked", {"selection": []}, 200)
        client, calls, _gets = _untick_client(tmp_path, monkeypatch, [still, gone])
        ok, _message = client.untick("a-proj")
        assert ok and len(calls) == 2 and "machine=" not in calls[1]


def test_a_case_change_through_a_move_renames_the_proxy_spelling(tmp_path):
    root = _proxy_tree(tmp_path)
    assert file_moves.move_proxy_siblings(root / "A001.braw",
                                          root / "Sub" / "a001.braw") == 1
    assert [p.name for p in (root / "Sub" / "Proxy").iterdir()] == ["a001.mov"]
