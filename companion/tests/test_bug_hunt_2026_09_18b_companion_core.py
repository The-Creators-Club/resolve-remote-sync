"""The tenth hunt's companion-core highs (2026-09-18b).

All four are about the fixes made the same morning - CR-283Y's section 4b
branch, CR-283's dashboard-version gate and CR-282B's lane-B relocation note -
so every test here drives the real `apply_move` / `_apply_file_moves` path
rather than a stand-in for it.
"""
from __future__ import annotations

import json
import os
import threading
import time

from ccsync_companion import file_moves

DRONE = "2026/Base Drone"
ANIMALS = "2026/FF5/Animals"


def _cmd(move_id=1, **over):
    cmd = {
        "id": move_id, "from_slug": "d", "from_project_rel": DRONE,
        "from_rel": "B-roll/A001_0512.braw", "to_slug": "a",
        "to_project_rel": ANIMALS,
        "to_rel": "Interviewees/Pangolin/A001_0512.braw", "is_dir": False,
        "requested_by": "owen", "requested_at": "2026-08-27T10:00:00+00:00",
    }
    cmd.update(over)
    return cmd


def _tree(tmp_path):
    root = tmp_path / "Creators_Club"
    broll = root / "Projects" / DRONE / "B-roll"
    (broll / "Proxy").mkdir(parents=True)
    (broll / "A001_0512.braw").write_bytes(b"braw")
    (broll / "Proxy" / "A001_0512.mp4").write_bytes(b"proxy")
    return root


def _trashed(root):
    return list((root / file_moves.TRASH_DIR_NAME).rglob("*.braw"))


# -- comp-sync-1: an empty plan is "cannot tell", never "syncs nothing" -----


def test_an_empty_plan_moves_the_file_normally_instead_of_trashing_it(tmp_path):
    """comp-sync-1: `_synced_project_rels` returns `[]`, not None, for any
    managed companion whose sequencer has an empty selection (an editor
    between projects, or one whose admin has just cleared the ticks). Against
    an empty list every destination read as "not synced here", so section 4b
    trashed every file the machine was told to move - with no relink and an
    ok=True answer - and prune_trash deleted it a fortnight later."""
    root = _tree(tmp_path)
    ok, detail, paths = file_moves.apply_move(
        file_moves.parse_command(_cmd()), str(root), None, project_rels=[])

    assert ok is True and detail.startswith("moved")
    assert paths is not None, "an empty plan must take the pre-4b path"
    assert not _trashed(root)
    assert (root / "Projects" / ANIMALS / "Interviewees" / "Pangolin"
            / "A001_0512.braw").read_bytes() == b"braw"


def test_a_move_within_the_project_holding_the_file_is_never_trashed(tmp_path):
    """comp-sync-1: the worst shape of the same bug. Source and destination
    are one project - the project this machine is holding the file in - so
    "the destination is not synced here" cannot be true of it whatever the
    plan says."""
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(
        _cmd(to_project_rel=DRONE, to_rel="B-roll/Selects/A001_0512.braw"))
    ok, detail, paths = file_moves.apply_move(
        cmd, str(root), None, project_rels=["2026/Something Else"])

    assert ok is True and detail.startswith("moved") and paths is not None
    assert not _trashed(root)
    assert (root / "Projects" / DRONE / "B-roll" / "Selects"
            / "A001_0512.braw").exists()


def test_a_source_the_plan_does_not_account_for_takes_the_pre_4b_path(tmp_path):
    """comp-sync-1: this machine is holding the file in a project its plan
    does not name, which proves the plan is not the whole truth about this
    disk. Trashing on that evidence is a guess; following the move is not."""
    root = _tree(tmp_path)
    ok, detail, paths = file_moves.apply_move(
        file_moves.parse_command(_cmd()), str(root), None,
        project_rels=["2026/Somewhere Else"])

    assert ok is True and detail.startswith("moved") and paths is not None
    assert not _trashed(root)


def test_a_real_4b_move_is_still_trashed(tmp_path):
    """The fix must not retire section 4b: a machine that DOES sync the source
    and does not sync the destination still trashes its copy rather than
    building an invisible orphan (CR-283Y)."""
    root = _tree(tmp_path)
    ok, detail, paths = file_moves.apply_move(
        file_moves.parse_command(_cmd()), str(root), None,
        project_rels=[DRONE])

    assert ok is True and detail == file_moves.DETAIL_NOT_SYNCED_HERE
    assert paths is None
    assert len(_trashed(root)) == 1
    assert not (root / "Projects" / ANIMALS).exists()
    # comp-sync-1: and the proxy goes with it, rather than being trashed on
    # its own in a different batch by lane B's next pass.
    assert not (root / "Projects" / DRONE.replace("/", os.sep) / "B-roll"
                / "Proxy" / "A001_0512.mp4").exists()
    assert len(list((root / file_moves.TRASH_DIR_NAME).rglob("A001_0512.mp4"))) == 1


# -- comp-sync-2 / res-companion-1: the trash path is not a relink target ---


class _Sequencer:
    def __init__(self, rels):
        self._rels = rels

    def rel_to_slug_with_borrowed(self):
        return {rel: "s" for rel in self._rels}


def _stub(tmp_path, root, rels=(DRONE,)):
    from ccsync_companion import app as app_mod

    answers: list = []

    class _Stub:
        config = {"local_root": str(root)}
        _root_absent = False
        sequencer = _Sequencer(list(rels))

        def __init__(self):
            self.file_moves = file_moves.FileMoveLedger(tmp_path / "state")

        def _relink_moved_result(self, *a):
            raise AssertionError("nothing moved to a path Resolve should follow")

        def _notify_tray(self, *a, **k):
            pass

        def _queue_file_move_answer(self, move_id, ok, detail, state=None,
                                    attempts=0, relink_pending=False):
            answers.append({"id": move_id, "ok": ok, "detail": detail,
                            "state": state, "relink_pending": relink_pending})

        _apply_file_moves = app_mod.CompanionApp._apply_file_moves

    return _Stub(), answers


def test_the_4b_completion_row_carries_no_path_into_the_trash(tmp_path):
    """comp-sync-2 = res-companion-1: `record()` copies `old_local` and
    `new_local` forward from the previous row when `paths` is falsy, so the
    4b completion row inherited the INTENT row's `.ccsync-trash` destination.
    `moved_to()` skips `applying` rows only, so the watcher's RES-10 hook then
    offered the editor a one-click relink of Resolve into the trash - which
    prune_trash deletes on its age rule, taking every relinked clip offline
    for good."""
    root = _tree(tmp_path)
    src = str(root / "Projects" / DRONE.replace("/", os.sep) / "B-roll"
              / "A001_0512.braw")
    stub, answers = _stub(tmp_path, root)

    stub._apply_file_moves({"commands": {"file_moves": [_cmd()]},
                            "dashboard_version": "0.7.50"})

    assert answers[0]["detail"] == file_moves.DETAIL_NOT_SYNCED_HERE
    entry = stub.file_moves.entry(1)
    assert entry["state"] == file_moves.STATE_NOT_SYNCED_HERE
    assert file_moves.TRASH_DIR_NAME not in str(entry.get("new_local") or "")
    assert not entry.get("new_local")
    # ...and the two readers that offer the relink do not see it at all.
    assert stub.file_moves.moved_to(src) is None
    assert stub.file_moves.pending_relinks() == []
    # The exclusion is the one thing that must survive: lane A never deletes,
    # so the old path stays out of the next pass.
    assert stub.file_moves.recent_excludes(f"Projects/{DRONE}")


def test_a_not_synced_here_row_is_never_offered_as_a_relink(tmp_path):
    """comp-sync-2, belt and braces: even a row that somehow holds paths (an
    older build's ledger, read after an upgrade) must not be offered, because
    `not_synced_here` means the file went to the trash."""
    ledger = file_moves.FileMoveLedger(tmp_path / "state")
    cmd = file_moves.parse_command(_cmd())
    ledger.record(cmd, True, file_moves.DETAIL_NOT_SYNCED_HERE,
                  state=file_moves.STATE_NOT_SYNCED_HERE,
                  paths=(r"d:\cc\Projects\old\clip.braw",
                         r"d:\cc\.ccsync-trash\20260918\clip.braw"),
                  relink_pending=True)

    assert ledger.moved_to(r"d:\cc\Projects\old\clip.braw") is None
    assert ledger.pending_relinks() == []


# -- comp-app-1: a dashboard rollback is forgotten within one report --------


def test_a_dashboard_rollback_stops_the_state_word(tmp_path):
    """comp-app-1: `_note_dashboard_version` only WROTE the remembered
    version, so a companion that had once seen 0.7.50 kept putting
    `not_synced_here` on the wire after the deploy was rolled back to 0.7.49 -
    whose `FileMoveResultIn.state` Literal 422s the WHOLE report (lanes,
    presence, alarms, jobs) every thirty seconds, for ever, with no shedding
    path on either side. An absent key means a dashboard older than the one
    that started sending it, which is what the docstring always said."""
    from ccsync_companion import app as app_mod

    root = _tree(tmp_path)
    stub, answers = _stub(tmp_path, root)

    stub._apply_file_moves({"commands": {"file_moves": [_cmd()]},
                            "dashboard_version": "0.7.50"})
    assert answers[0]["state"] == file_moves.STATE_NOT_SYNCED_HERE
    assert app_mod._dashboard_knows_state_word(stub) is True

    # The rollback: the same companion, the same process, a reply from 0.7.49
    # (which sends no `dashboard_version` at all) redelivering the command.
    answers.clear()
    stub._apply_file_moves({"commands": {"file_moves": [_cmd()]}})

    assert app_mod._note_dashboard_version(stub, {}) == ""
    assert app_mod._dashboard_knows_state_word(stub) is False
    assert answers[0]["state"] is None, (
        "a word 0.7.49 has never heard of is a 422 for the whole report")
    assert answers[0]["ok"] is True
    assert answers[0]["detail"] == file_moves.DETAIL_NOT_SYNCED_HERE


def test_a_reply_that_is_not_a_dict_leaves_the_memory_alone(tmp_path):
    """comp-app-1: forgetting is about a dashboard that ANSWERED without the
    key. A reply we could not read at all says nothing either way."""
    from ccsync_companion import app as app_mod

    class _Bare:
        pass

    bare = _Bare()
    app_mod._note_dashboard_version(bare, {"dashboard_version": "0.7.50"})
    assert app_mod._note_dashboard_version(bare, None) == "0.7.50"
    assert app_mod._dashboard_knows_state_word(bare) is True


# -- res-companion-2: two writer threads, one ledger ------------------------


def test_two_threads_never_write_the_ledger_at_once(tmp_path, monkeypatch):
    """res-companion-2: CR-282B handed the LANE thread a writer
    (`record_relocation`) into a ledger that until today only the reporter
    thread wrote. Both `_save()`s wrote one fixed `file_moves.json.tmp` and
    promoted it, so interleaved they publish a truncated or doubly-written
    file - and `_load` runs once, at startup, so the damage is invisible until
    the restart after a crash, which is the ONE case the intent rows exist
    for. A ledger that reads back as `[]` un-muzzles lane A on every moved
    path, which is the single failure docs/FILE_MOVES.md exists to prevent."""
    ledger = file_moves.FileMoveLedger(tmp_path / "state")
    inside = []
    overlapped = []
    lock = threading.Lock()
    original = file_moves.FileMoveLedger._save

    def slow_save(self):
        with lock:
            inside.append(1)
            if len(inside) > 1:
                overlapped.append(1)
        time.sleep(0.01)
        try:
            original(self)
        finally:
            with lock:
                inside.pop()

    monkeypatch.setattr(file_moves.FileMoveLedger, "_save", slow_save)

    def relocations():
        for i in range(20):
            ledger.record_relocation(f"d:/old/{i}.braw", f"d:/new/{i}.braw")

    def records():
        for i in range(20):
            ledger.record(_cmd(move_id=100 + i), True, "moved")

    threads = [threading.Thread(target=relocations),
               threading.Thread(target=records)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not overlapped, "two threads were inside _save() at the same time"
    data = json.loads((tmp_path / "state" / file_moves.LEDGER_FILENAME)
                      .read_text(encoding="utf-8"))
    assert len(data["relocations"]) == 20
    assert len([e for e in data["entries"] if e["id"] >= 100]) == 20
    # ...and the restart that reads it back sees everything.
    again = file_moves.FileMoveLedger(tmp_path / "state")
    assert again.entry(119) is not None
    assert again.relocation_to("d:/old/19.braw", "d:/new/19.braw") is True


def test_the_ledger_tmp_file_is_unique_per_write(tmp_path):
    """res-companion-2: the lock covers the two threads of ONE companion. A
    second process on the same state directory (a supervisor relaunch racing
    the dying tray, CR-93's shape) is not covered by any lock, and a shared
    `file_moves.json.tmp` there publishes half a file as the ledger."""
    ledger = file_moves.FileMoveLedger(tmp_path / "state")
    first, second = ledger._tmp_path(), ledger._tmp_path()

    assert first != second
    assert str(os.getpid()) in first.name
    assert first.name.endswith(".tmp")
    ledger.record(_cmd(), True, "moved")
    assert not list((tmp_path / "state").glob("*.tmp"))


# -- comp-sync-3: the folder drag is the shape the feature exists for --------


def _folder_move(**over):
    cmd = _cmd(move_id=7, from_rel="Interviewees/Creator_Interviews",
               to_rel="B-roll/Creator_Interviews", is_dir=True)
    cmd.update(over)
    return cmd


def _lane_b_carried(tmp_path, names, dest_names=None):
    """Lane B's own work: the files are at the new path, the old directory is
    gone, and one relocation row exists per FILE (which is all lane B knows)."""
    root = tmp_path / "local" / "Projects"
    src = root / DRONE.replace("/", os.sep) / "Interviewees" / "Creator_Interviews"
    dest = root / ANIMALS.replace("/", os.sep) / "B-roll" / "Creator_Interviews"
    ledger = file_moves.FileMoveLedger(tmp_path / "state")
    dest.mkdir(parents=True)
    for name, landed in zip(names, dest_names or names):
        (dest / landed).write_bytes(b"x")
        ledger.record_relocation(str(src / name), str(dest / landed))
    return ledger, src, dest


def test_a_hand_moved_folder_is_relinked_on_lane_bs_per_file_evidence(tmp_path):
    """comp-sync-3: the collector describes a hand-moved FOLDER with one
    is_dir command naming the directory, while lane B writes one relocation
    row per file. `relocation_to`'s exact pair matched nothing, so apply_move
    answered "nothing at the old path on this machine" with no paths, app.py
    skipped the relink, and every clip under the folder stayed Media Offline
    while the MOVES history said this machine had followed."""
    ledger, src, dest = _lane_b_carried(tmp_path, ["A001.braw", "A002.braw"])

    ok, detail, paths = file_moves.apply_move(
        _folder_move(), str(tmp_path / "local"), ledger=ledger)

    assert ok is True
    assert paths == (str(src), str(dest)), (
        "the relink needs the directory pair, not None")
    assert "folder" in detail


def test_a_partly_followed_folder_is_not_relinked_as_if_it_were_complete(tmp_path):
    """comp-sync-3: one row under the source pointing somewhere else means
    the folder was only partly carried, and relinking the whole directory
    then repoints clips at paths that hold nothing."""
    ledger, src, dest = _lane_b_carried(
        tmp_path, ["A001.braw", "A002.braw"],
        dest_names=["A001.braw", "A002.braw"])
    # A third file lane B put somewhere else entirely.
    ledger.record_relocation(str(src / "A003.braw"),
                             str(tmp_path / "local" / "elsewhere" / "A003.braw"))

    ok, detail, paths = file_moves.apply_move(
        _folder_move(), str(tmp_path / "local"), ledger=ledger)

    assert ok is True
    assert paths is None
    assert "nothing at the old path" in detail


def test_an_emptied_source_folder_left_behind_is_not_a_refusal(tmp_path):
    """comp-sync-3, the other branch: lane B carries the FILES out and the
    husk of the source directory can survive, so src.exists() is still true
    and the destination check refused a move this machine had followed."""
    ledger, src, dest = _lane_b_carried(tmp_path, ["A001.braw"])
    (src / "sub").mkdir(parents=True)

    ok, detail, paths = file_moves.apply_move(
        _folder_move(), str(tmp_path / "local"), ledger=ledger)

    assert ok is True, detail
    assert paths == (str(src), str(dest))
    assert src.exists(), "nothing here deletes the husk"


def test_a_leftover_source_folder_that_still_holds_files_is_still_refused(tmp_path):
    """comp-sync-3: only an EMPTY leftover counts. A source that still holds
    files is a half-done move, and the destination refusal is the right
    answer there."""
    ledger, src, dest = _lane_b_carried(tmp_path, ["A001.braw"])
    src.mkdir(parents=True)
    (src / "A002.braw").write_bytes(b"x")

    ok, detail, paths = file_moves.apply_move(
        _folder_move(), str(tmp_path / "local"), ledger=ledger)

    assert ok is False
    assert "already exists" in detail
