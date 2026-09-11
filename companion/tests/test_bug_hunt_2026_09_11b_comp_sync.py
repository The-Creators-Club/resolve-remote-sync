"""Regression tests for the 2026-09-11b bug hunt, comp-sync territory
(CR-249): the fix pass OF the morning's fix pass.

Every test here fails at git f1eeb42 and passes with the fix beside it.
Nothing reaches a live Resolve, a real Syncthing or the network: the two
security-4 tests bind 127.0.0.1 only.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ccsync_companion import file_moves
from ccsync_companion.sync import lane_guard, rclone_lane as rclone_mod
from ccsync_companion.sync import shared_folders as shared_mod
from ccsync_companion.sync import syncthing_admin as admin_mod
from ccsync_companion.sync import syncthing_lane as lane_c_mod
from ccsync_companion.sync.rclone_lane import (
    DIRECTION_DOWN,
    RcloneLane,
    build_filter_rules_down,
    build_filter_rules_up,
    path_matches_lane_a_filter,
)


# -- comp-sync-b-1: the abandoned-lane-B latch set after the clear ---------


class _GateLock:
    """A drop-in for the sequencer's lock whose Nth acquire on the CALLING
    thread first lets the lane B thread finish. That is the whole of
    comp-sync-b-1: the window between `thread.is_alive()` and the latch
    write, made deterministic instead of waited for."""

    def __init__(self, inner, owner, on_nth, before):
        self._inner = inner
        self._owner = owner
        self._on_nth = on_nth
        self._before = before
        self._count = 0

    def acquire(self, *a, **k):
        if threading.current_thread() is self._owner:
            self._count += 1
            if self._count == self._on_nth:
                self._before()
        return self._inner.acquire(*a, **k)

    def release(self):
        return self._inner.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def test_a_lane_b_that_ends_inside_the_latch_window_does_not_latch_for_ever(monkeypatch):
    from test_sequencer import FakeAdmin, FakeSelectionClient, _build

    import ccsync_companion.sync.sequencer as sequencer_mod

    seq, _lane_a, lane_b, _events = _build(FakeSelectionClient([]), FakeAdmin())

    # The abort path, with the waiting taken out of it.
    monkeypatch.setattr(sequencer_mod, "lane_b_join_timeout", lambda budget: 0.0)
    monkeypatch.setattr(sequencer_mod, "LANE_B_ABORT_JOIN_SECONDS", 0.0)

    let_b_finish = threading.Event()
    b_done = threading.Event()

    def slow_run_once(subpath=None):
        lane_b.calls.append(subpath)
        let_b_finish.wait(5.0)

    lane_b.run_once = slow_run_once

    def _release_b_then_continue():
        # The sequencer is about to write the latch. The wedged pass ends
        # NOW, runs its own clear, and only then does the write land.
        let_b_finish.set()
        assert b_done.wait(5.0)

    original_clear = seq._clear_lane_b_abandoned

    def _clear_and_mark(*a, **k):
        try:
            return original_clear(*a, **k)
        finally:
            b_done.set()

    monkeypatch.setattr(seq, "_clear_lane_b_abandoned", _clear_and_mark)
    # Acquires on the sequencer's own thread: 1 = the _lane_b_subpath write,
    # 2 = the latch write this finding is about.
    seq._lock = _GateLock(seq._lock, threading.current_thread(), 2,
                          _release_b_then_continue)

    seq._run_lanes_a_and_b("Projects/2026/FF5/Wedged", budget=None)

    # At f1eeb42 the clear ran first and the set second, so the latch was on
    # for the life of the process and no proxy ever downloaded again.
    assert seq.lane_b_abandoned_subpath() is None
    seq._run_lanes_a_and_b("Projects/2026/FF5/Next", budget=None)
    assert "Projects/2026/FF5/Next" in lane_b.calls


def test_a_latch_whose_thread_has_died_is_not_honoured():
    """Belt and braces for the same defect: a latch left behind by a thread
    that is gone must not stop the next turn's lane B."""
    from test_sequencer import FakeAdmin, FakeSelectionClient, _build

    seq, _lane_a, lane_b, _events = _build(FakeSelectionClient([]), FakeAdmin())
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    seq._note_lane_b_abandoned("Projects/2026/FF5/Wedged", dead, None)

    seq._run_lanes_a_and_b("Projects/2026/FF5/Next", budget=None)
    assert lane_b.calls == ["Projects/2026/FF5/Next"]


# -- regression-4: the stale-subpath gate is the ROTATION's, not the lane's -


def _gated_lane(tmp_path, current):
    lane = RcloneLane(
        direction="down", local_root=str(tmp_path), remote="nas",
        remote_root="/tree", state_dir=tmp_path / "state",
        cfg={"local_root": str(tmp_path)},
    )
    spawned: list[tuple] = []
    lane._build_command = lambda *a, **k: spawned.append(a) or ["rclone"]
    lane.subpath_still_current = lambda subpath: subpath == current
    return lane, spawned


def test_a_consolidate_pass_is_not_dropped_by_the_rotations_subpath(tmp_path):
    """CONSOLIDATE / FIX ALL call run_once on the SAME lane object the
    sequencer holds. At f1eeb42 the gate dropped their proxy pull whenever
    the rotation's last turn was on another project."""
    lane, spawned = _gated_lane(tmp_path, "Projects/Now")

    status = lane.run_once("Projects/Then")

    assert spawned, "the consolidate pass must still reach the spawn"
    assert "rotation" not in (status.detail or "")


def test_a_rotation_pass_for_a_stale_subpath_is_still_dropped(tmp_path):
    lane, spawned = _gated_lane(tmp_path, "Projects/Now")

    status = lane.run_once("Projects/Then", rotation_pass=True)

    assert spawned == []
    assert "rotation" in (status.detail or "")


def test_the_sequencer_marks_its_own_passes_as_rotation_passes():
    from test_sequencer import FakeAdmin, FakeSelectionClient, _build

    seq, _lane_a, lane_b, _events = _build(FakeSelectionClient([]), FakeAdmin())
    seen: list[dict] = []

    def run_once(subpath=None, max_duration_seconds=None, rotation_pass=False):
        seen.append({"subpath": subpath, "rotation_pass": rotation_pass})

    lane_b.run_once = run_once
    seq._run_lanes_a_and_b("Projects/2026/FF5/Now", budget=None)

    assert seen and seen[0]["rotation_pass"] is True


# -- comp-sync-b-3 / res-companion-3: the in-flight deletion credit --------


def _breaker(tmp_path):
    return lane_guard.LaneBBreaker(tmp_path / "lane_b_breaker.json")


def test_deletions_after_a_pass_that_never_finished_still_reach_the_account(tmp_path):
    breaker = _breaker(tmp_path)
    # Pass 1 trashes 50 proxies and then dies on an exception above
    # _account_pass, so note_pass is never called.
    breaker.note_deletes_in_flight(50)
    assert breaker.report()["deletes"] == 50

    # Pass 2 starts from zero and legitimately trashes 40.
    breaker.begin_pass()
    breaker.note_deletes_in_flight(40)
    breaker.note_pass("Projects/2026", deleted=40, moved_bytes=0)

    # At f1eeb42 the stale credit swallowed all 40.
    assert breaker.report()["deletes"] == 90


def test_a_running_total_below_the_credit_is_read_as_a_new_run(tmp_path):
    """The same protection for a lane that never calls begin_pass (an older
    caller, or a run whose spawn path was replaced in a test)."""
    breaker = _breaker(tmp_path)
    breaker.note_deletes_in_flight(50)
    breaker.note_deletes_in_flight(40)
    assert breaker.report()["deletes"] == 90


class _FakeProc:
    def __init__(self, lines, returncode=0):
        self.stderr = iter(lines)
        self._returncode = returncode

    def wait(self, timeout=None):
        return self._returncode


def test_lane_b_clears_the_in_flight_credit_before_it_spawns(tmp_path):
    (tmp_path / "local").mkdir()
    breaker = _breaker(tmp_path)
    at_spawn: list[int] = []

    def factory(cmd, **kwargs):
        at_spawn.append(breaker._in_flight_credited)
        return _FakeProc(['{"level":"info","msg":"rclone starting"}\n'])

    lane = RcloneLane(
        direction=DIRECTION_DOWN, local_root=str(tmp_path / "local"), remote="nas",
        remote_root="Creators_Club", state_dir=tmp_path / "state",
        popen_factory=factory, breaker=breaker,
    )
    breaker.note_deletes_in_flight(50)   # the dead pass's credit

    lane.run_once()

    assert at_spawn == [0], "a run must start its in-flight account at zero"


# -- comp-sync-b-2: an `applying` intent row is not a completed move -------


def _move(move_id=7):
    return {
        "id": move_id, "from_project_rel": "2026/FF5", "from_rel": "A/clip.mov",
        "to_project_rel": "2026/FF5", "to_rel": "B/clip.mov", "is_dir": False,
    }


def test_an_intent_row_is_never_offered_as_a_completed_move(tmp_path):
    ledger = file_moves.FileMoveLedger(tmp_path)
    old_local = str(tmp_path / "A" / "clip.mov")
    new_local = str(tmp_path / "B" / "clip.mov")
    ledger.record_intent(_move(), old_local, new_local)

    # At f1eeb42 both of these answered as though the file had moved, so a
    # crash in the rename window sent Resolve at a path that does not exist.
    assert ledger.pending_relinks() == []
    assert ledger.moved_to(old_local) is None


def test_the_finished_move_is_still_offered(tmp_path):
    ledger = file_moves.FileMoveLedger(tmp_path)
    old_local = str(tmp_path / "A" / "clip.mov")
    new_local = str(tmp_path / "B" / "clip.mov")
    move = _move()
    ledger.record_intent(move, old_local, new_local)
    ledger.record(move, True, "moved", paths=(old_local, new_local),
                  relink_pending=True)

    assert [e["id"] for e in ledger.pending_relinks()] == [move["id"]]
    assert (ledger.moved_to(old_local) or {}).get("new_local") == new_local


# -- regression-6: the case-only rename takes its proxies with it ----------


def _case_only_tree(tmp_path):
    root = tmp_path / "Projects" / "2026" / "FF5"
    (root / "Proxy").mkdir(parents=True)
    (root / "clip.mov").write_text("original", encoding="utf-8")
    (root / "Proxy" / "clip.mov").write_text("proxy", encoding="utf-8")
    return {
        "id": 11, "from_project_rel": "2026/FF5", "from_rel": "clip.mov",
        "to_project_rel": "2026/FF5", "to_rel": "Clip.mov", "is_dir": False,
    }


def test_a_case_only_rename_renames_the_proxy_beside_it(tmp_path):
    move = _case_only_tree(tmp_path)
    proxy_dir = tmp_path / "Projects" / "2026" / "FF5" / "Proxy"

    ok, detail, paths = file_moves.apply_move(move, str(tmp_path))

    assert ok, detail
    names = sorted(p.name for p in proxy_dir.iterdir())
    # At f1eeb42 the original was renamed and the proxy was left at the old
    # spelling, so lane B re-downloaded one and trashed the other.
    assert names == ["Clip.mov"]
    assert "proxy" in detail


# -- comp-sync-b-4: the staging name must not reach the NAS ---------------


def test_the_rename_staging_name_is_refused_by_both_lane_a_doors(tmp_path, monkeypatch):
    src = tmp_path / "clip.mov"
    src.write_text("x", encoding="utf-8")
    dest = tmp_path / "Clip.mov"

    # The shape that leaves the staging name on the editor's disk: Resolve
    # holds a handle, so the second replace AND the restore both fail
    # (WinError 32 on both).
    real_replace = Path.replace
    calls: list[int] = []

    def flaky(self, target):
        calls.append(1)
        if len(calls) == 1:
            return real_replace(self, target)
        raise OSError(32, "the file is in use by another process")

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(OSError):
        file_moves._rename_case_only(src, dest)
    monkeypatch.undo()
    staged = next(p for p in tmp_path.iterdir() if p.name.startswith(".ccsync-move-"))

    rel = f"Projects/2026/FF5/{staged.name}"
    assert path_matches_lane_a_filter(rel) is False

    rules = build_filter_rules_up()
    assert rclone_mod.MOVE_STAGING_EXCLUDE_RULE in rules
    first_include = next(i for i, r in enumerate(rules) if r.startswith("+"))
    assert rules.index(rclone_mod.MOVE_STAGING_EXCLUDE_RULE) < first_include

    down = build_filter_rules_down()
    assert rclone_mod.MOVE_STAGING_EXCLUDE_RULE in down
    assert down.index(rclone_mod.MOVE_STAGING_EXCLUDE_RULE) < next(
        i for i, r in enumerate(down) if r.startswith("+"))


# -- comp-sync-b-5: a halt holds the asset libraries too -------------------


class _OfferingAdmin:
    def __init__(self):
        self.accepted: list[str] = []

    def get_folder(self, folder_id):
        raise urllib.error.HTTPError("http://x", 404, "no", {}, None)

    def pending_folders(self):
        return {"assets-luts": {"offeredBy": {"DEVICE-1": {}}}}

    def accept_folder(self, folder_id, label, local_path, device_id, ignore_lines=None):
        self.accepted.append(folder_id)


def test_a_halt_holds_a_new_asset_library_offer(tmp_path):
    admin = _OfferingAdmin()
    mgr = shared_mod.SharedFolderManager(
        admin, tmp_path, folders=[("assets-luts", "Assets/Luts", "LUT library")],
        halted=lambda: True, root_present_fn=lambda: True)

    assert mgr.reconcile() == {"assets-luts": shared_mod.OUTCOME_HALTED}
    # At f1eeb42 accept_folder ran and ended in an unpause, so the machine
    # started syncing a new library while every other lane was stopped.
    assert admin.accepted == []


def test_the_offer_is_accepted_once_the_halt_is_over(tmp_path):
    admin = _OfferingAdmin()
    mgr = shared_mod.SharedFolderManager(
        admin, tmp_path, folders=[("assets-luts", "Assets/Luts", "LUT library")],
        halted=lambda: False, root_present_fn=lambda: True)

    assert mgr.reconcile() == {"assets-luts": "accepted"}
    assert admin.accepted == ["assets-luts"]


# -- security-4: the Syncthing API key does not follow a redirect ---------


class _RedirectingHandler(BaseHTTPRequestHandler):
    leaked: list[str] = []

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/leak"):
            _RedirectingHandler.leaked.append(self.headers.get("X-API-Key") or "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(302)
        self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/leak")
        self.end_headers()

    def log_message(self, *a):  # keep pytest output clean
        return


@pytest.fixture()
def redirecting_server():
    _RedirectingHandler.leaked = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_admin_helper_refuses_a_redirect_rather_than_resend_the_key(redirecting_server):
    with pytest.raises(urllib.error.HTTPError) as caught:
        admin_mod.http_request("GET", f"{redirecting_server}/rest/config",
                               "SECRET-KEY", timeout=5.0)
    assert caught.value.code in (301, 302, 303, 307, 308)
    assert _RedirectingHandler.leaked == []


def test_the_lane_c_helper_refuses_a_redirect_rather_than_resend_the_key(redirecting_server):
    with pytest.raises(urllib.error.HTTPError):
        lane_c_mod.default_http_get(f"{redirecting_server}/rest/db/status",
                                    "SECRET-KEY", 5.0)
    assert _RedirectingHandler.leaked == []


# -- hand-off wave (regression-19, comp-app -> comp-sync): the relink toast ----


def _fake_resolve(monkeypatch, clip_paths, ok=True):
    """The media-pool walk, injected. No live Resolve is reached: the module
    attributes `relink_moved` uses are replaced on the real modules and
    conftest's `_no_live_resolve` rules the rest out."""
    from ccsync_companion import canon as canon_mod
    from ccsync_companion import resolve_bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "get_media_pool_items",
                        lambda: {"ok": True,
                                 "items": [{"file_path": p} for p in clip_paths]})
    monkeypatch.setattr(bridge_mod, "resolve_media_pool_item", lambda item: object())
    monkeypatch.setattr(bridge_mod, "replace_clip",
                        lambda clip, path, source="": {"ok": ok,
                                                       "message": "refused"})
    monkeypatch.setattr(canon_mod, "canonical_to_local", lambda p, root, prefix: p)
    monkeypatch.setattr(canon_mod, "local_to_canonical", lambda p, root, prefix: p)


@pytest.mark.parametrize("count, expected", [(1, "1 Resolve clip relinked"),
                                             (3, "3 Resolve clips relinked")])
def test_the_relink_answer_the_editor_reads_has_a_real_plural(
        tmp_path, monkeypatch, count, expected):
    """regression-19's owed half. comp-sync-11 folded app.py's own sentence
    into `relink_moved`, so this detail is what the RELINK IT dialog's toast
    and the pending-relink answer now show an editor - and it still said
    "N Resolve clip(s) relinked" (owner's rule, 2026-08-18: no "(s)" in copy
    an editor reads)."""
    old_dir = str(tmp_path / "Projects" / "2026" / "FF5")
    new_dir = str(tmp_path / "Projects" / "2026" / "FF5 Moved")
    clips = [os.path.join(old_dir, f"A00{i}.mov") for i in range(count)]
    _fake_resolve(monkeypatch, clips)

    matched, detail = file_moves.relink_moved(
        old_dir, new_dir, str(tmp_path), "P:\\", is_dir=True)

    assert matched is True
    assert detail == expected
    assert "(s)" not in detail


def test_the_refused_half_of_the_relink_answer_is_still_reported(tmp_path, monkeypatch):
    """The `failed` tail is unchanged: a clip Resolve will not let us repoint
    is not something another pass fixes, so the sentence must still say so."""
    old_dir = str(tmp_path / "Projects" / "2026" / "FF5")
    _fake_resolve(monkeypatch, [os.path.join(old_dir, "A001.mov")], ok=False)

    matched, detail = file_moves.relink_moved(
        old_dir, str(tmp_path / "Moved"), str(tmp_path), "P:\\", is_dir=True)

    assert matched is True
    assert detail == "0 Resolve clips relinked, 1 could not be"
