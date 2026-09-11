"""Bug hunt 2026-09-11b, comp-app (CR-250): the fix pass hunted.

One section per finding, in the ledger's order. Nothing here touches a real
Resolve, a real Tk root, a real clock or a real socket: the watchdog policy is
called through its own hatch, the media pool is a stub, and the file-move
paths are built under the app's own local_root.

The helpers come from the previous hunt's file (same territory, same fakes):
the tests directory is on sys.path for the whole suite, and duplicating a
LaneWatchdog fake is how two of them drift apart.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from ccsync_companion import file_moves as file_moves_mod
from ccsync_companion import machine as machine_mod
from ccsync_companion.app import (
    LANE_WATCHDOG_MAX_RESTARTS_PER_HOUR,
    CompanionApp,
)

from test_bug_hunt_2026_09_11_comp_app import (  # noqa: E402
    _app,
    _consolidate_app,
    _Clock,
    _FakeApp,
    _watchdog,
)


# -- res-companion-1: the crash-resume must be REACHED ----------------------
#
# The `applying` intent row is written before the first filesystem call so a
# companion killed between `src.replace(dest)` and `record()` can finish the
# job on the redelivered command. `_apply_file_moves` short-circuited on the
# ledger row instead, and answered `ok=False, state=None`, which the dashboard
# reads as "answered, a failure is an answer" and retires for ever.


def _moved_cmd(move_id=11):
    return {"id": move_id, "from_slug": "d", "from_project_rel": "2026/Drone",
            "from_rel": "B-roll/A001.braw", "to_slug": "a",
            "to_project_rel": "2026/Animals", "to_rel": "Pangolin/A001.braw",
            "is_dir": False, "requested_by": "alex",
            "requested_at": "2026-09-11T10:00:00+00:00"}


def _move_paths(app, cmd):
    root = Path(str(app.config["local_root"])) / "Projects"
    src = root / Path(*cmd["from_project_rel"].split("/")) / Path(*cmd["from_rel"].split("/"))
    dest = root / Path(*cmd["to_project_rel"].split("/")) / Path(*cmd["to_rel"].split("/"))
    return src, dest


def _no_resolve(app):
    app._relink_moved = lambda old, new, is_dir: ""


def test_a_move_interrupted_after_the_rename_is_finished_on_redelivery(tmp_path):
    """The kill between `src.replace(dest)` and `record()`: the ledger holds
    an `applying` row, the bytes are at the new path, and the command comes
    round again on the next report."""
    app = _app(tmp_path)
    _no_resolve(app)
    cmd = _moved_cmd()
    src, dest = _move_paths(app, cmd)
    src.parent.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"braw")
    app.file_moves.record_intent(file_moves_mod.parse_command(cmd), str(src), str(dest))

    app._apply_file_moves({"commands": {"file_moves": [cmd]}})

    (answer,) = app._file_move_results()
    assert answer["ok"] is True, answer
    assert "interrupted" in answer["detail"], answer
    entry = app.file_moves.entry(cmd["id"])
    assert entry["state"] == file_moves_mod.STATE_DONE
    # An `applying` row is one of `recent_excludes`'s unresolved states, so
    # leaving it behind muzzles lane A on that path for ever.
    assert file_moves_mod.STATE_APPLYING not in str(entry["state"])


def test_a_move_interrupted_before_the_rename_is_applied_on_redelivery(tmp_path):
    """The worse half: the intent row landed and the file never moved. The
    old code answered "applying it on this machine", the dashboard stamped
    applied_at, and the editor's copy diverged from the server's in silence."""
    app = _app(tmp_path)
    _no_resolve(app)
    cmd = _moved_cmd(12)
    src, dest = _move_paths(app, cmd)
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"braw")
    app.file_moves.record_intent(file_moves_mod.parse_command(cmd), str(src), str(dest))

    app._apply_file_moves({"commands": {"file_moves": [cmd]}})

    (answer,) = app._file_move_results()
    assert answer["ok"] is True, answer
    assert dest.exists() and not src.exists()
    assert app.file_moves.entry(cmd["id"])["state"] == file_moves_mod.STATE_DONE


def test_a_move_being_applied_when_the_drive_goes_out_is_not_retired(tmp_path):
    """Still `applying`, and the drive is gone before the redelivery: the
    answer must be "retrying", never a verdict."""
    app = _app(tmp_path)
    _no_resolve(app)
    cmd = _moved_cmd(13)
    src, dest = _move_paths(app, cmd)
    app.file_moves.record_intent(file_moves_mod.parse_command(cmd), str(src), str(dest))
    app._root_absent = True

    app._apply_file_moves({"commands": {"file_moves": [cmd]}})

    (answer,) = app._file_move_results()
    assert answer["ok"] is False and answer["state"] == "retrying"


# -- comp-app-2: one answer per outage, not one per report ------------------


def test_the_drive_is_out_answer_is_not_repeated_on_every_report(tmp_path):
    """comp-sync-20's answer matches `applied_at IS NULL` every time, so the
    dashboard logged a WARNING per move per report - about 60,000 lines for
    one editor away for a week - into the log an admin opens to find out why
    something else went wrong."""
    app = _app(tmp_path)
    app._root_absent = True
    resp = {"commands": {"file_moves": [_moved_cmd(14)]}}

    app._apply_file_moves(resp)
    assert len(app._file_move_results()) == 1

    for _ in range(10):
        app._apply_file_moves(resp)
    assert app._file_move_results() == [], "the same answer rode every report"


def test_a_long_outage_still_re_answers_so_a_lost_report_is_not_final(tmp_path):
    app = _app(tmp_path)
    app._root_absent = True
    resp = {"commands": {"file_moves": [_moved_cmd(15)]}}
    app._apply_file_moves(resp)
    app._file_move_results()

    app._file_move_drive_answered_at[15] -= (
        CompanionApp.FILE_MOVE_DRIVE_ANSWER_SECONDS + 1.0)
    app._apply_file_moves(resp)
    assert len(app._file_move_results()) == 1


def test_the_drive_coming_back_ends_the_outage(tmp_path):
    app = _app(tmp_path)
    app._root_absent = True
    resp = {"commands": {"file_moves": [_moved_cmd(16)]}}
    app._apply_file_moves(resp)
    app._file_move_results()

    app._root_absent = False
    # A report while the drive is back: any command at all ends the episode.
    app._apply_file_moves({"commands": {"file_moves": [_moved_cmd(99)]}})
    app._file_move_results()
    app._root_absent = True
    app._apply_file_moves(resp)
    assert len(app._file_move_results()) == 1, "a new outage is a new answer"


# -- comp-app-3 / comp-app-4 / comp-app-5: the watchdog's own policy --------


def test_the_hourly_ceiling_is_reachable_within_the_hour(tmp_path, caplog):
    """comp-app-3: `60 * 2**len(recent)` spaced the sixth attempt past the
    hour, so `len(recent)` never reached the ceiling and a permanently dead
    thread was restarted for ever (97 times in a simulated day). The ceiling
    branch - "this needs a human, not another restart" - was dead code."""
    app = _FakeApp()
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock)
    caplog.set_level(logging.WARNING, logger="ccsync.app")

    for _ in range(60):  # one hour of ticks
        watchdog.check()
        clock.advance(60.0)

    assert app.sequencer.starts == LANE_WATCHDOG_MAX_RESTARTS_PER_HOUR, (
        "the backoff must let the ceiling be reached inside its own window")
    assert any("is the ceiling" in r.message for r in caplog.records), (
        "the branch that makes the fault visible never ran")


def test_a_clock_that_steps_backwards_does_not_restart_on_every_tick(tmp_path):
    """comp-app-4: `_load_record` learned the skew tolerance and the policy
    that reads those events did not, so ten minutes of NTP correction emptied
    `recent` and restarted the dead thread every 60 s with no backoff and no
    ceiling."""
    app = _FakeApp()
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock)
    assert watchdog.check() == ["sequencer"]

    clock.t -= 600.0  # an NTP step, a VM resume, a dual-boot RTC
    restarted = []
    for _ in range(10):
        restarted += watchdog.check()
        clock.advance(60.0)
    assert restarted == [], "every stored event read as 'in the future'"
    assert app.sequencer.starts == 1


def test_the_hold_off_does_not_write_a_warning_every_tick(tmp_path, caplog):
    """comp-app-5: the per-tick JSON write went and the per-tick WARNING
    stayed, so the 5 MB rotating log still loses the day's other evidence."""
    app = _FakeApp()
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock)
    caplog.set_level(logging.WARNING, logger="ccsync.app")

    for _ in range(60):
        watchdog.check()
        clock.advance(60.0)

    held = [r for r in caplog.records if "NOT restarting" in r.message]
    # One per CHANGE of answer: five growing waits and the ceiling, against
    # the 55 ticks that each wrote their own line.
    assert len(held) <= LANE_WATCHDOG_MAX_RESTARTS_PER_HOUR + 1, (
        f"{len(held)} hold-off warnings in one hour")
    assert held, "the editor's log must still say the thread is down"


# -- comp-app-6: a lane that is disabled by config is not a lane -----------


def test_sync_now_does_not_run_a_lane_this_machine_has_disabled(tmp_path):
    """`_start_lanes` never starts lane B when `lane_b_enabled=false` (direct
    NAS access) - and "Sync now" called `run_once()` on it anyway, a full
    rclone pull onto a machine whose whole configuration says it reads the
    proxies off the share, and named it in the toast."""
    app = _app(tmp_path, lane_b_enabled=False)
    app._managed = False
    ran: list[str] = []
    for lane in app.lanes:
        lane.run_once = (lambda name=getattr(lane, "name", ""):
                         (lambda subpath=None: ran.append(name)))()

    verdict = app.sync_now()

    assert verdict["accepted"] is True
    assert not any("lane_b" in name for name in ran), ran
    assert not any("lane_b" in name for name in verdict["lanes"]), verdict


def test_sync_now_still_runs_lane_b_where_it_is_enabled(tmp_path):
    app = _app(tmp_path, lane_b_enabled=True)
    app._managed = False
    ran: list[str] = []
    for lane in app.lanes:
        lane.run_once = (lambda name=getattr(lane, "name", ""):
                         (lambda subpath=None: ran.append(name)))()

    verdict = app.sync_now()
    assert any("lane_b" in name for name in ran), ran
    assert any("lane_b" in name for name in verdict["lanes"]), verdict


# -- regression-5: the twin comp-sync-11's own comment names ---------------


def test_the_apps_relink_matches_a_mac_spelling_of_the_same_name(tmp_path,
                                                                 monkeypatch):
    """CR-234 routed `file_moves.relink_moved` through `cmp_key` (NFC + case
    fold) and left `CompanionApp._relink_moved` on a bare normcase - and the
    FILE MOVE feature (the dialog, the pending-relink sweep, the apply path)
    goes through the unfixed twin. A clip with a diacritic never matched, so
    the pending relink never retired and the clip stayed Media Offline."""
    from ccsync_companion import resolve_bridge

    app = _app(tmp_path)
    name = unicodedata.normalize("NFC", "Matěj Šimalčík.mov")
    old_local = str(Path(str(app.config["local_root"])) / "Projects" / name)
    new_local = str(Path(str(app.config["local_root"])) / "Moved" / name)
    # Resolve on a Mac answers NFD; the ledger's old path is the dashboard's
    # NFC. The two are different byte strings and normcase folds neither.
    from_resolve = unicodedata.normalize("NFD", old_local)
    assert from_resolve != old_local

    replaced: list[Any] = []
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: {"ok": True, "items": [{"file_path": from_resolve}]})
    monkeypatch.setattr(resolve_bridge, "resolve_media_pool_item", lambda item: object())
    monkeypatch.setattr(resolve_bridge, "replace_clip",
                        lambda clip, path, source=None: (replaced.append((path, source))
                                                         or {"ok": True}))

    matched, text = app._relink_moved_result(old_local, new_local, False)

    assert matched is True and "relinked" in text
    assert len(replaced) == 1 and replaced[0][1] == "file_move"


# -- comp-app-7: the count the editor usually never sees -------------------


def test_the_consolidate_success_toast_says_how_many_were_copied(tmp_path,
                                                                 monkeypatch):
    """The conditional governed the WHOLE f-string, so the number appeared
    only when the editor had skipped something - the uncommon case. The
    common one said "Copy & upload finished." with nothing to compare against
    the count the rehearsal and failure branches both print."""
    results = [{"ok": True, "file_path": f"A{i:03d}.braw"} for i in range(3)]
    app, tray, _lanes = _consolidate_app(tmp_path, monkeypatch, results)

    app.consolidate_project()

    done = [msg for msg, _title in tray.notifications
            if "Copy & upload finished" in msg]
    assert done, tray.notifications
    assert "1 copied in" in done[0] or "copied in" in done[0], done


# -- comp-app-8: a corrupt machine.json is not a dead end ------------------


def test_an_unreadable_machine_file_is_reported_and_repairable(tmp_path):
    """comp-app-5 correctly stopped re-minting over an unreadable file and
    gave the condition no exit: "" for ever, one log line per process, no
    notice, nothing in the report, no affordance."""
    path = tmp_path / "machine.json"
    path.write_bytes(b"")

    assert machine_mod.machine_id(path) == ""
    assert machine_mod.machine_id_unreadable(path) is True

    minted = machine_mod.remint(path)

    assert minted and machine_mod.machine_id(path) == minted
    assert machine_mod.machine_id_unreadable(path) is False
    # The bytes that could not be read are KEPT: the id in them may still be
    # recoverable by hand, and a re-mint is not a licence to destroy them.
    kept = list(tmp_path.glob("machine.json.unreadable-*"))
    assert len(kept) == 1


def test_a_healthy_machine_file_is_never_reminted(tmp_path):
    path = tmp_path / "machine.json"
    first = machine_mod.machine_id(path)
    assert first
    assert machine_mod.machine_id_unreadable(path) is False
    assert machine_mod.remint(path) == first, "a live id is never replaced"


def test_the_editor_is_told_when_this_computer_cannot_read_its_id(tmp_path):
    app = _app(tmp_path)
    said: list[str] = []
    app._notify_tray = lambda msg, title=None: said.append(msg)
    path = machine_mod.machine_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{oops")

    app._warn_if_machine_id_is_unreadable()
    app._warn_if_machine_id_is_unreadable()

    assert len(said) == 1, said
    assert "id" in said[0].lower() and str(path.name) in said[0]


# -- regression-19: four editor-visible "(s)" plurals still shipped --------


def test_app_py_writes_real_plurals(tmp_path):
    """comp-ui-4's blanket scan named tray.py and settings_window.py only,
    and app.py went on toasting "3 clip(s)", "5 file(s)", "7 LUT(s)"."""
    from test_sweep_2026_09_04_copy import SRC, _visible_strings

    # The six toast/dialog phrases regression-19 names. The remaining "(s)"
    # in app.py are log lines, report `detail` strings and the diagnostics
    # block an admin pastes into a ticket - a different audience, and the
    # blanket loop belongs with whoever converts those.
    retired = (
        "clip(s) to ",
        "folder(s) are set to be left alone",
        "file(s) were checked",
        "other clip(s)",
        "LUT(s) on this computer",
        "LUT(s) with the team",
    )
    visible = _visible_strings(SRC / "app.py")
    bad = [t for t in visible for phrase in retired if phrase in t]
    assert not bad, (f"app.py says {bad} to an editor: "
                     f"ui_copy.count(n, noun) writes a real plural.")


# -- regression-20: the second trash-summary producer ----------------------


def test_the_trash_summary_uses_the_sites_own_retention(tmp_path, monkeypatch):
    """comp-sync-15 closed the tray line's producer and left this one, which
    is in the pinned app contract: "copies are kept 14 days" about a folder
    pruned at 3 is the wrong-deadline defect SYNC-112 exists to stop."""
    from ccsync_companion.sync import lane_guard

    app = _app(tmp_path, trash_max_age_days=3)
    trash = Path(str(app.config["local_root"])) / lane_guard.TRASH_DIR_NAME
    trash.mkdir(parents=True, exist_ok=True)
    seen: dict[str, Any] = {}

    def _summary(root, max_age_days=lane_guard.DEFAULT_TRASH_MAX_AGE_DAYS, **kw):
        seen["max_age_days"] = max_age_days
        return {"count": 1, "bytes": 10, "oldest": None,
                "retention_days": max_age_days}

    monkeypatch.setattr(lane_guard, "trash_summary", _summary)
    summary = app.trash_summary()

    assert seen["max_age_days"] == 3
    assert summary["retention_days"] == 3


def test_the_trash_summary_fallback_uses_it_too(tmp_path, monkeypatch):
    """The `getattr(lane_guard, "trash_summary", None)` fallback - an older
    lane_guard - hardcoded the default as well."""
    from ccsync_companion.sync import lane_guard

    app = _app(tmp_path, trash_max_age_days=3)
    trash = Path(str(app.config["local_root"])) / lane_guard.TRASH_DIR_NAME
    trash.mkdir(parents=True, exist_ok=True)
    monkeypatch.delattr(lane_guard, "trash_summary")
    monkeypatch.setattr(lane_guard, "trash_entries",
                        lambda root: [("batch", time.time(), 10)])

    assert app.trash_summary()["retention_days"] == 3


# -- res-companion-5: the answer queue is touched by two threads ----------


class _TripWire(list):
    """A list whose iteration (the filter step in `_queue_file_move_answer`)
    lets the reporter thread run its drain. Without a lock the filter then
    assigns the ALREADY DRAINED answers back and appends beside them."""

    def __init__(self, items, run):
        super().__init__(items)
        self._run = run
        self.armed = True

    def __iter__(self):
        if self.armed:
            self.armed = False
            self._run()
        return super().__iter__()


def test_an_answer_already_reported_is_not_resurrected(tmp_path):
    app = _app(tmp_path)
    drained: list[Any] = []
    threads: list[threading.Thread] = []

    def _drain_on_another_thread():
        thread = threading.Thread(
            target=lambda: drained.extend(app._file_move_results()))
        threads.append(thread)
        thread.start()
        time.sleep(0.2)          # long enough to reach the swap, or the lock

    sent = {"id": 1, "ok": True, "detail": "moved"}
    app._file_move_answers = _TripWire([sent], _drain_on_another_thread)
    CompanionApp._queue_file_move_answer(app, 2, True, "moved too")
    for thread in threads:
        thread.join(timeout=5)

    everything = list(drained) + list(app._file_move_answers)
    ids = [a["id"] for a in everything]
    assert sorted(ids) == [1, 2], f"an answer was lost or resurrected: {ids}"


# -- owed here by comp-broll-music (comp-broll-music-2) --------------------
#
# `prune_staging` deliberately keeps a drop that was staged and never run (it
# has no `ended_at`, so it is not FINISHED), and `_space_refusal` sends the
# editor to this button for the bytes it is keeping.


class _UnrunIngestor:
    def prune_staging(self, max_age_days=None):
        return {"removed": 0, "bytes": 0, "held": 0, "held_names": [],
                "held_unrun": 2}


def test_clear_finished_staging_explains_a_drop_that_was_never_run(tmp_path):
    app = _app(tmp_path)
    app.broll_ingestor = _UnrunIngestor()
    app.music_ingestor = None

    message = app.clear_finished_ingest_staging()

    assert "no finished staging to clear" not in message, message
    assert "never indexed" in message and "2 drops" in message


def test_clear_finished_staging_still_says_so_when_there_is_nothing(tmp_path):
    app = _app(tmp_path)
    app.broll_ingestor = None
    app.music_ingestor = None
    assert "no finished staging" in app.clear_finished_ingest_staging()


# -- owed here by comp-resolve (comp-resolve-b-2) --------------------------


def test_the_rate_limiters_hold_off_is_logged_once_per_cooldown(tmp_path,
                                                                monkeypatch,
                                                                caplog):
    """RES-19's watcher re-offers the held clips every 900 s for the life of
    the process, so the hold-off line repeated all afternoon about a queue
    that had not changed."""
    from ccsync_companion import resolve_bridge, resolve_journal

    app = _app(tmp_path)
    monkeypatch.setattr(resolve_bridge, "media_pool_item_is_reachable",
                        lambda item: True)
    monkeypatch.setattr(resolve_bridge, "current_project_name", lambda: "P")
    monkeypatch.setattr(resolve_journal, "allow_automatic",
                        lambda project, kind: False)
    caplog.set_level(logging.INFO, logger="ccsync.app")

    for i in range(5):
        app._handle_non_canonical(
            [{"file_path": rf"D:\Stock\A{i:05d}.mov", "media_pool_item": object()}])

    held = [r for r in caplog.records if "holding" in r.message]
    assert len(held) == 1, [r.message for r in held]


# -- owed here by comp-sync (comp-sync-b-2) -------------------------------


def test_a_pending_relink_whose_file_is_not_there_is_not_offered(tmp_path,
                                                                 monkeypatch):
    """The `applying` intent row is written BEFORE the rename and carries
    relink_pending, so a companion killed in between leaves a row that reads
    like a completed move. Repointing the pool at it would take a clip
    offline with no file behind it at all."""
    app = _app(tmp_path)
    asked: list[Any] = []
    app._relink_moved_result = lambda old, new, is_dir: (asked.append(new)
                                                         or (True, "relinked"))
    missing = str(Path(str(app.config["local_root"])) / "Projects" / "gone.mov")
    entry = {"id": 3, "old_local": "old.mov", "new_local": missing,
             "is_dir": False, "detail": "moved"}
    monkeypatch.setattr(app.file_moves, "pending_relinks", lambda: [entry])

    app._relink_pending_moves()
    assert asked == [], "a path that is not on disk is not a completed move"

    Path(missing).parent.mkdir(parents=True, exist_ok=True)
    Path(missing).write_bytes(b"x")
    app._relink_pending_moves()
    assert asked == [missing]


def test_the_relink_it_dialog_refuses_a_destination_that_is_not_there(tmp_path):
    app = _app(tmp_path)
    said: list[str] = []
    app._notify_tray = lambda msg, title=None: said.append(msg)
    app._relink_moved_result = lambda old, new, is_dir: (True, "relinked")
    entry = {"id": 4, "old_local": "old.mov", "is_dir": False,
             "new_local": str(Path(str(app.config["local_root"])) / "nope.mov")}

    app._show_moved_clip_dialog(entry, "A001.mov")

    assert said and "has not finished moving" in said[0]
    assert not app._popup_active_lock.locked()
