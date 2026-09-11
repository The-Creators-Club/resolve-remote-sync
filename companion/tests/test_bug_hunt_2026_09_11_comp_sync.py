"""Regression tests for the 2026-09-11 bug hunt, comp-sync territory
(CR-234): the sync engine, the file-move half and the drive reminder.

Every test here fails at git HEAD 40f931a and passes with the fix beside it.
Nothing in this file may reach a live Resolve: the media-pool walk is driven
through an injected `get_media_pool_items`, the same way test_watcher.py
drives the watcher.
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
import unicodedata
from pathlib import Path

import pytest

from ccsync_companion import drive_reminder as drive_reminder_mod
from ccsync_companion import file_moves, selection as selection_mod, watcher as watcher_mod
from ccsync_companion.sync import lane_guard, shared_folders as shared_mod
from ccsync_companion.sync import syncthing_supervisor as supervisor_mod
from ccsync_companion.sync.repath import ProjectRepather, RepathLedger
from ccsync_companion.sync.syncthing_lane import SyncthingLane
from ccsync_companion.watcher import TimelineWatcher

from conftest import make_timeline_item


# -- comp-sync-1: a failed latch write is retried, and it is SAID ----------


def _unwritable(path: Path):
    """A state path whose directory cannot be created: the write fails, the
    latch is in memory only, and at HEAD nothing anywhere said so."""
    blocker = path.parent
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory", encoding="utf-8")
    return path


def test_a_breaker_that_cannot_write_its_latch_says_so_and_retries(tmp_path):
    state = _unwritable(tmp_path / "blocked" / "lane_b_breaker.json")
    breaker = lane_guard.LaneBBreaker(state)

    assert breaker.trip("the NAS listed empty") is True
    report = breaker.report()
    assert report["tripped"] is True
    # At HEAD _write_json's False was dropped on the floor: no field, no
    # retry, and a tray restart cleared the breaker.
    assert report["persist_failed"] is True
    assert report["persist_error"]

    # The home volume comes back: the next report retries and the latch
    # reaches the disk without anything else happening.
    state.parent.unlink()
    breaker._persist_last_try = 0.0
    again = breaker.report()
    assert "persist_failed" not in again
    assert json.loads(state.read_text(encoding="utf-8"))["tripped"] is True


def test_the_halt_reports_a_failed_persist_too(tmp_path):
    halt = lane_guard.HaltState(_unwritable(tmp_path / "blocked" / "sync_halt.json"))
    halt.engage("an admin stopped the fleet", lane_guard.HALT_SCOPE_FLEET)
    assert halt.report()["persist_failed"] is True


def test_the_latch_tmp_file_is_process_unique(tmp_path):
    """Two companions overlapping across a self-upgrade must not be able to
    replace each other's half-written tmp into a live latch."""
    seen: list[str] = []
    real = Path.write_text

    def spy(self, *a, **kw):
        seen.append(self.name)
        return real(self, *a, **kw)

    Path.write_text = spy
    try:
        lane_guard._write_json(tmp_path / "x.json", {"a": 1})
    finally:
        Path.write_text = real
    assert seen and seen[0] == f"x.json.{os.getpid()}.tmp"


# -- comp-sync-2: the backoff clamps the EXPONENT --------------------------


def test_the_folder_problem_backoff_does_not_overflow():
    problems = shared_mod.FolderProblems(now=lambda: 0.0)
    for _ in range(1024):
        problems.note("assets-luts", "LUT library", "not-offered")
    # At HEAD: OverflowError, raised inside a method documented as never
    # raising, and both managers' reconcile died with it.
    entry = problems.note("assets-luts", "LUT library", "not-offered")
    assert entry["next_attempt"] == pytest.approx(shared_mod.PROBLEM_RETRY_MAX_SECONDS)


def test_the_supervisor_backoff_does_not_overflow():
    assert supervisor_mod.backoff_seconds(1025) == supervisor_mod.BACKOFF_CAP_SECONDS
    assert supervisor_mod.backoff_seconds(10 ** 6) == supervisor_mod.BACKOFF_CAP_SECONDS


def test_a_corrupt_attempt_count_is_clamped_on_load(tmp_path):
    state = tmp_path / "syncthing_supervisor.json"
    state.write_text(json.dumps({"attempts": 10 ** 12}), encoding="utf-8")
    sup = supervisor_mod.SyncthingSupervisor(state_path=state)
    assert sup._attempts <= supervisor_mod.MAX_ATTEMPTS_TRACKED
    assert supervisor_mod.backoff_seconds(sup._attempts) == supervisor_mod.BACKOFF_CAP_SECONDS


def test_a_reconcile_whose_note_raises_still_does_not_raise(tmp_path, monkeypatch):
    """The except arm must not re-enter the thing that just threw."""
    class Boom:
        def get_folder(self, folder_id):
            raise RuntimeError("syncthing said no")

    mgr = shared_mod.SharedFolderManager(
        Boom(), tmp_path, folders=[("assets-luts", "Assets/Luts", "LUT library")],
        root_present_fn=lambda: True)
    monkeypatch.setattr(mgr._problems, "note",
                        lambda *a, **k: (_ for _ in ()).throw(OverflowError("boom")))
    assert mgr.reconcile() == {"assets-luts": "error"}


# -- comp-sync-3 / comp-sync-19: the folder problems reach the editor ------


def _lane(problems):
    return SyncthingLane(
        base_url="http://127.0.0.1:8384", api_key="k",
        expected_folder_ids_fn=lambda: [],
        shared_folder_problems_fn=lambda: problems,
        http_get=lambda path: {} if path.endswith("ping") else {"folders": []},
    )


def test_an_editor_with_no_ticked_projects_still_hears_about_the_lut_library():
    sentence = ("Assets/Luts (LUT library) has not been shared with this computer "
                "yet. Ask your admin to approve it.")
    status = _lane([sentence]).check_once()
    # At HEAD the empty-expected branch returned above the SYNC-101 block and
    # the sentence reached nothing at all.
    assert sentence in (status.detail or "")


def test_more_than_one_folder_problem_is_counted():
    status = _lane(["first problem.", "second problem.", "third problem."]).check_once()
    assert "first problem." in (status.detail or "")
    assert "+2 more" in (status.detail or "")


# -- comp-sync-5 / 6 / 17: the repath ledger -------------------------------


class _RepathAdmin:
    def __init__(self, folders, paused=None):
        self.folders = dict(folders)
        self.paused = dict(paused or {})
        self.calls: list[tuple] = []

    def get_config(self):
        return {"folders": [{"id": fid, "path": p, "paused": self.paused.get(fid, False)}
                            for fid, p in self.folders.items()]}

    def set_folder_paused(self, folder_id, paused):
        self.calls.append(("paused", folder_id, paused))
        self.paused[folder_id] = paused

    def set_folder_path(self, folder_id, path, label=None):
        self.calls.append(("path", folder_id, path, label))
        self.folders[folder_id] = path


def _sel(slug, rel):
    return {"slug": slug, "rel_path": rel, "position": 0, "active": True}


def test_a_blocked_repath_stops_saying_so_once_the_folder_is_where_it_belongs(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Old"
    old.mkdir(parents=True)
    admin = _RepathAdmin({"s1": str(old)})

    def refuse(src, dst):
        raise OSError("Resolve is holding it")

    r = ProjectRepather(admin, str(tmp_path), move_fn=refuse, state_dir=tmp_path / "state")
    r.reconcile([_sel("s1", "2026/New")])
    assert [(e["slug"], e["moved"]) for e in r.ledger.events()] == [("s1", False)]
    assert admin.paused["s1"] is True

    # The admin undoes the rename on the NAS: the folder is at the expected
    # path again and nothing is wrong with this project any more.
    r.reconcile([_sel("s1", "2026/Old")])
    assert r.ledger.events() == []
    # ...and the folder the blocked branch deliberately left paused is
    # unpaused with it, or "says blocked" becomes "says fine, syncs nothing".
    assert admin.paused["s1"] is False


def test_a_rotation_pause_is_not_unpaused_by_the_clearing_path(tmp_path):
    """The sequencer pauses all but the current project by design. Only a
    BLOCKED project may be unpaused here."""
    here = tmp_path / "Projects" / "2026" / "Here"
    here.mkdir(parents=True)
    admin = _RepathAdmin({"s1": str(here)}, paused={"s1": True})
    r = ProjectRepather(admin, str(tmp_path), state_dir=tmp_path / "state")
    r.reconcile([_sel("s1", "2026/Here")])
    assert admin.calls == []


def test_the_pending_relink_walk_is_throttled(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Old"
    old.mkdir(parents=True)
    admin = _RepathAdmin({"s1": str(old)})
    walks: list[tuple] = []

    def relink(old_local, new_local):
        walks.append((old_local, new_local))
        return False, "Resolve not relinked (not open)"

    r = ProjectRepather(admin, str(tmp_path), state_dir=tmp_path / "state",
                        relink_fn=relink)
    r.reconcile([_sel("s1", "2026/New")])
    walks.clear()
    # One sequencer pass is 1 + N reconciles; at HEAD each one walked the
    # media pool once per pending event.
    for _ in range(7):
        r.reconcile([_sel("s1", "2026/New")])
    assert walks == []


def test_two_repaths_in_the_same_millisecond_can_both_retire(tmp_path):
    ledger = RepathLedger(tmp_path, now=lambda: 1_000_000.0)
    a = ledger.record("s1", "/old/a", "/new/a", "moved", relinked=None)
    b = ledger.record("s2", "/old/b", "/new/b", "moved", relinked=None)
    assert a["id"] != b["id"]
    ledger.mark_relinked(b["id"], True, slug="s2", old="/old/b")
    assert [e["slug"] for e in ledger.pending_relinks()] == ["s1"]


# -- comp-sync-7: a lane B the rotation walked away from -------------------


def test_no_second_lane_b_is_started_while_one_is_abandoned():
    from test_sequencer import FakeAdmin, FakeSelectionClient, _build

    seq, lane_a, lane_b, _events = _build(FakeSelectionClient([]), FakeAdmin())
    seq._lane_b_abandoned = "Projects/2026/FF5/Wedged"
    seq._run_lanes_a_and_b("Projects/2026/FF5/Next", budget=None)
    assert lane_a.calls == ["Projects/2026/FF5/Next"]
    # At HEAD this queued another thread on the held _run_lock, one per
    # project turn, unbounded.
    assert lane_b.calls == []

    seq._clear_lane_b_abandoned()
    seq._run_lanes_a_and_b("Projects/2026/FF5/Next", budget=None)
    assert lane_b.calls == ["Projects/2026/FF5/Next"]


def test_a_queued_pass_for_a_stale_subpath_is_dropped(tmp_path):
    from ccsync_companion.sync.rclone_lane import RcloneLane

    lane = RcloneLane(
        direction="down", local_root=str(tmp_path), remote="nas",
        remote_root="/tree", state_dir=tmp_path / "state",
        cfg={"local_root": str(tmp_path)},
    )
    spawned: list[tuple] = []
    lane._build_command = lambda *a, **k: spawned.append(a) or ["rclone"]
    lane.subpath_still_current = lambda subpath: subpath == "Projects/Now"

    # regression-4 (2026-09-11b): the gate is the ROTATION's, so the
    # sequencer's own passes say so. A consolidate calling run_once on this
    # same lane object is not a queued rotation pass and is not dropped.
    status = lane.run_once("Projects/Then", rotation_pass=True)
    assert spawned == []
    assert "rotation" in (status.detail or "")


# -- comp-sync-8 / 16: the drive reminder ---------------------------------


def _reminder(tmp_path, clock=time.time):
    sent: list[str] = []
    r = drive_reminder_mod.DriveReminder(
        notify_fn=lambda message, title: sent.append(message),
        drive_phrase_fn=lambda: "Your drive",
        interval=0.0,
        state_path=tmp_path / "drive_unfinished.json",
        clock=clock,
    )
    return r, sent


def test_a_remembered_wedge_is_not_replayed_at_a_drive_that_is_simply_gone(tmp_path):
    first, _sent = _reminder(tmp_path)
    first.begin_state("not_answering", "still not answering")

    # Next start: the drive is in the editor's bag, i.e. ABSENT.
    second, sent = _reminder(tmp_path)
    assert second.resume_remembered("absent") is False
    assert second.active is False
    assert sent == []


def test_a_remembered_wedge_is_kept_while_the_drive_is_still_wedged(tmp_path):
    first, _sent = _reminder(tmp_path)
    first.begin_state("not_answering", "still not answering")
    second, sent = _reminder(tmp_path)
    assert second.resume_remembered("not_answering") is True
    assert sent and "not answering" in sent[0]


def test_a_new_episode_never_inherits_the_last_ones_mute(tmp_path):
    # The wall clock frozen: at HEAD episode identity was a time.time() float
    # and Windows ticks at 15.6 ms, so this is the shape that happened in the
    # field and made test_drive_reminder.py flap.
    r, _sent = _reminder(tmp_path, clock=lambda: 1000.0)
    r.begin_state("not_answering", "still not answering")
    assert r.mute_episode() is True
    assert r.reminders_muted is True
    r.clear()
    r.begin_state("not_answering", "still not answering")
    assert r.reminders_muted is False


# -- comp-sync-10: not-offered was three situations ------------------------


def test_a_read_failure_is_not_ask_your_admin(tmp_path):
    class Flaky:
        def get_folder(self, folder_id):
            raise RuntimeError("404 not found")

        def pending_folders(self):
            raise RuntimeError("connection refused")

    mgr = shared_mod.SharedFolderManager(
        Flaky(), tmp_path, folders=[("assets-luts", "Assets/Luts", "LUT library")],
        root_present_fn=lambda: True)
    assert mgr.reconcile() == {"assets-luts": shared_mod.OUTCOME_ASK_FAILED}
    sentence = mgr.problems()[0]
    assert "Ask your admin" not in sentence
    assert "could not ask the sync engine" in sentence


# -- comp-sync-11 / 12 / 18 + res-companion-1: file moves ------------------


def _move(from_rel="A001.mov", to_rel="A001.mov", from_project="2026/FF5",
          to_project="2026/FF5", is_dir=False, move_id=7):
    return {"id": move_id, "from_project_rel": from_project, "from_rel": from_rel,
            "to_project_rel": to_project, "to_rel": to_rel, "is_dir": is_dir,
            "requested_by": "your administrator"}


NFC_NAME = unicodedata.normalize("NFC", "Matej \u0160imal\u010d\u00edk.mov")
NFD_NAME = unicodedata.normalize("NFD", NFC_NAME)


def _fake_resolve(monkeypatch, clip_path, replaced):
    """The media-pool walk, injected. No live Resolve is ever reached: the
    two module attributes relink_moved uses are replaced on the real modules
    (conftest's _no_live_resolve rules the rest out)."""
    from ccsync_companion import canon as canon_mod
    from ccsync_companion import resolve_bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "get_media_pool_items",
                        lambda: {"ok": True, "items": [{"file_path": clip_path}]})
    monkeypatch.setattr(bridge_mod, "resolve_media_pool_item", lambda item: object())
    monkeypatch.setattr(bridge_mod, "replace_clip",
                        lambda clip, path, source="": replaced.append(path) or {"ok": True})
    monkeypatch.setattr(canon_mod, "canonical_to_local", lambda p, root, prefix: p)
    monkeypatch.setattr(canon_mod, "local_to_canonical", lambda p, root, prefix: p)


def test_a_moved_clip_relinks_even_when_resolve_spells_it_decomposed(tmp_path, monkeypatch):
    """CR-90's class, in the function added by the same fix pass that fixed
    moved_to(). The dashboard's from_rel is NFC; a Mac's Resolve answers NFD,
    so the walk matched nothing, the pending relink never retired, and the
    toast's promise was never kept."""
    project = tmp_path / "Projects" / "2026" / "FF5"
    old_local = str(project / NFC_NAME)
    new_local = str(project / "Selects" / NFC_NAME)
    replaced: list[str] = []
    _fake_resolve(monkeypatch, str(project / NFD_NAME), replaced)

    matched, detail = file_moves.relink_moved(
        old_local, new_local, str(tmp_path), "P:\\", is_dir=False)
    assert matched is True, detail
    assert replaced == [new_local]


def test_a_moved_folder_relinks_its_decomposed_children(tmp_path, monkeypatch):
    old_dir = str(tmp_path / "Projects" / "2026" / unicodedata.normalize("NFC", "Šimal"))
    new_dir = str(tmp_path / "Projects" / "2026" / "Moved")
    clip = os.path.join(unicodedata.normalize("NFD", old_dir), NFD_NAME)
    replaced: list[str] = []
    _fake_resolve(monkeypatch, clip, replaced)

    matched, _detail = file_moves.relink_moved(
        old_dir, new_dir, str(tmp_path), "P:\\", is_dir=True)
    assert matched is True
    # The tail keeps the disk's own spelling: this path is written into
    # Resolve, and only the bytes on disk open a file.
    assert replaced == [os.path.join(new_dir, NFD_NAME)]


def test_a_case_only_rename_is_actually_applied(tmp_path):
    project = tmp_path / "Projects" / "2026" / "FF5"
    project.mkdir(parents=True)
    (project / "clip.mov").write_text("footage", encoding="utf-8")

    ok, detail, paths = file_moves.apply_move(
        _move(from_rel="clip.mov", to_rel="Clip.mov"), str(tmp_path))
    assert ok is True, detail
    # At HEAD: (True, "already where the server has it", None) -- the ledger
    # said done, nothing moved, and lane A recreated the old spelling on the
    # NAS a day later.
    assert paths is not None
    names = sorted(p.name for p in project.iterdir())
    assert names == ["Clip.mov"]
    assert (project / "Clip.mov").read_text(encoding="utf-8") == "footage"


def test_a_decomposed_proxy_follows_its_original(tmp_path):
    project = tmp_path / "Projects" / "2026" / "FF5"
    (project / "Proxy").mkdir(parents=True)
    (project / NFC_NAME).write_text("original", encoding="utf-8")
    (project / "Proxy" / NFD_NAME).write_text("proxy", encoding="utf-8")

    moved = file_moves.move_proxy_siblings(project / NFC_NAME, project / "moved" / NFC_NAME)
    assert moved == 1
    assert (project / "moved" / "Proxy" / NFD_NAME).is_file()


def test_a_move_interrupted_before_the_ledger_row_is_finished_on_redelivery(tmp_path):
    """res-companion-1: the companion is killed between the rename and
    record(). At HEAD the redelivered command answered "nothing at the old
    path", relink_pending stayed False, and the clip was offline for ever."""
    state = tmp_path / "state"
    state.mkdir()
    project = tmp_path / "Projects" / "2026" / "FF5"
    project.mkdir(parents=True)
    (project / "A001.mov").write_text("footage", encoding="utf-8")
    move = _move(to_project="2026/FF5/Selects")

    ledger = file_moves.FileMoveLedger(state)
    boom = RuntimeError("power cut")

    real = file_moves.move_proxy_siblings

    def die(src, dest):
        raise boom

    file_moves.move_proxy_siblings = die
    try:
        with pytest.raises(RuntimeError):
            file_moves.apply_move(move, str(tmp_path), ledger=ledger)
    finally:
        file_moves.move_proxy_siblings = real

    # The file HAS moved and the intent row is the only record of it.
    assert (project / "Selects" / "A001.mov").is_file()
    assert ledger.entry(move["id"])["state"] == file_moves.STATE_APPLYING
    assert ledger.moved_to(str(project / "A001.mov")) is not None

    # The next process is redelivered the command and finishes the job.
    resumed = file_moves.FileMoveLedger(state)
    ok, detail, paths = file_moves.apply_move(move, str(tmp_path), ledger=resumed)
    assert ok is True
    assert paths == (str(project / "A001.mov"), str(project / "Selects" / "A001.mov"))
    assert "interrupted" in detail


def test_a_machine_that_never_held_the_file_still_answers_nothing_here(tmp_path):
    """The resume arm must not fire on `dest exists` alone: another machine's
    move is not ours to relink."""
    state = tmp_path / "state"
    project = tmp_path / "Projects" / "2026" / "FF5"
    (project / "Selects").mkdir(parents=True)
    (project / "Selects" / "A001.mov").write_text("footage", encoding="utf-8")
    ledger = file_moves.FileMoveLedger(state)
    ok, detail, paths = file_moves.apply_move(
        _move(to_project="2026/FF5/Selects"), str(tmp_path), ledger=ledger)
    assert (ok, paths) == (True, None)
    assert detail == "nothing at the old path on this machine"


# -- comp-sync-13: the re-armed relink offer --------------------------------


def test_a_refused_relink_is_not_re_offered_on_every_poll(tmp_path):
    clip = tmp_path / "root" / "Projects" / "a.mov"
    clip.parent.mkdir(parents=True)
    clip.touch()
    offered: list[dict] = []
    watcher = TimelineWatcher(
        local_root=str(tmp_path / "root"),
        canonical_prefix="P:\\",
        on_non_canonical=lambda items: offered.extend(items),
        get_timeline_items=lambda: {"ok": True, "message": "", "project_name": "",
                                    "items": [make_timeline_item(str(clip))]},
    )
    watcher.poll_once()
    assert len(offered) == 1
    # RES-19's rearm after every failed relink, on the 3 s poll: at HEAD each
    # poll re-offered the path and app.py appended it again behind a 15 min
    # limiter that was refusing to drain the list.
    for _ in range(20):
        watcher.rearm_non_canonical(str(clip), "a.mov")
        watcher.poll_once()
    assert len(offered) == 1

    watcher._rearm_clock = lambda: time.monotonic() + watcher_mod.REARM_COOLDOWN_SECONDS + 1
    watcher.poll_once()
    assert len(offered) == 2


def test_the_refused_relink_book_is_capped_at_the_source(tmp_path):
    """comp-app-4: the report caps `non_canonical_refused` at 50, but the
    dict it is built from grew to the size of a media pool -- on exactly the
    machine (a wrong canonical_prefix) that produces refusals in bulk."""
    watcher = TimelineWatcher(
        local_root=str(tmp_path / "root"),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "message": "", "project_name": "",
                                    "items": []},
    )
    for index in range(watcher_mod.MAX_NON_CANONICAL_REFUSED + 25):
        watcher.rearm_non_canonical(str(tmp_path / f"clip{index}.mov"), f"clip{index}.mov")

    kept = watcher.non_canonical_refused()
    assert len(kept) == watcher_mod.MAX_NON_CANONICAL_REFUSED
    # Oldest out first: the newest refusals are the ones a surface is about
    # to name.
    assert kept[-1]["name"] == f"clip{watcher_mod.MAX_NON_CANONICAL_REFUSED + 24}.mov"
    assert all(entry["name"] != "clip0.mov" for entry in kept)


# -- comp-sync-14: the plan's age -------------------------------------------


def test_the_plan_stamp_advances_when_the_dashboard_answers_again(tmp_path, monkeypatch):
    monkeypatch.setattr(selection_mod, "STAMP_MIN_INTERVAL_SECONDS", 0.0)
    cfg = {"editor_name": "Owen", "dashboard_url": "http://dash.example.com",
           "dashboard_token": "tok123"}
    client = selection_mod.SelectionClient(cfg, tmp_path)
    response = {"selection": [{"slug": "p", "rel_path": "2026/FF5", "active": True}]}
    client._write_cache(response)
    first = json.loads((tmp_path / selection_mod.CACHE_FILENAME).read_text(
        encoding="utf-8"))["fetched_at"]
    time.sleep(0.01)
    client._write_cache(response)  # byte-identical: selection.json is NOT rewritten

    # A fresh process with the dashboard down reads the stamp off disk.
    fresh = selection_mod.SelectionClient(cfg, tmp_path)
    assert fresh.fetched_at() != first
    assert json.loads((tmp_path / selection_mod.CACHE_FILENAME).read_text(
        encoding="utf-8"))["fetched_at"] == first, "selection.json stays byte-stable"


# -- comp-sync-15: the recovery-folder line ---------------------------------


def test_the_trash_summary_carries_the_path_and_the_configured_retention(tmp_path):
    from ccsync_companion.sync.rclone_lane import RcloneLane

    lane = RcloneLane(
        direction="down", local_root=str(tmp_path), remote="nas",
        remote_root="/tree", state_dir=tmp_path / "state",
        cfg={"local_root": str(tmp_path), "trash_max_age_days": 3},
    )
    lane._maybe_prune_trash()
    trash = lane.trash_report()
    assert trash["max_age_days"] == 3
    assert trash["path"] == str(tmp_path / lane_guard.TRASH_DIR_NAME)


# -- comp-sync-22: the structure clone and the upload-only tick -------------


def test_an_upload_only_project_gets_no_structure_clone():
    from test_sequencer import FakeAdmin, FakeSelectionClient, _build, _item

    item = _item("up", "2026/FF5/Backed Up Shoot", 1)
    item["sync_mode"] = "upload_only"
    seq, _lane_a, _lane_b, _events = _build(FakeSelectionClient([item]), FakeAdmin())
    cloned: list[str] = []
    seq._maybe_clone_structure = lambda subpath, key, forced=False: cloned.append(subpath)
    seq._process_project(item, [item])
    assert cloned == []


# -- res-companion-5: deletions credited as the pass makes them -------------


def test_deletions_made_before_a_hard_kill_are_still_on_the_account(tmp_path):
    state = tmp_path / "lane_b_breaker.json"
    breaker = lane_guard.LaneBBreaker(state)
    # A pass emptying a scope, killed halfway: note_pass never runs.
    breaker.note_deletes_in_flight(30)

    after_the_kill = lane_guard.LaneBBreaker(state)
    assert after_the_kill.report()["deletes"] == 30


def test_an_in_flight_credit_is_not_counted_twice_by_the_finished_pass(tmp_path):
    breaker = lane_guard.LaneBBreaker(tmp_path / "lane_b_breaker.json")
    breaker.note_deletes_in_flight(4)
    breaker.note_deletes_in_flight(9)
    breaker.note_pass("Projects/2026/FF5", deleted=9, moved_bytes=0)
    assert breaker.report()["deletes"] == 9
    assert breaker.report()["last_pass_deletes"] == 9
