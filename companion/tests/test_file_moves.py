"""Dashboard-driven file moves, companion half (docs/FILE_MOVES.md)."""
from __future__ import annotations

from pathlib import Path

from ccsync_companion import file_moves
from ccsync_companion.app import CompanionApp
from ccsync_companion.sync.rclone_lane import DIRECTION_UP, RcloneLane

DRONE = "2026/Base Drone"
ANIMALS = "2026/FF5/Animals"


def _cmd(move_id=1, **over):
    cmd = {
        "id": move_id, "from_slug": "d", "from_project_rel": DRONE,
        "from_rel": "B-roll/A001_0512.braw", "to_slug": "a", "to_project_rel": ANIMALS,
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
    (broll / "A002_0513.braw").write_bytes(b"other")
    return root


# -- the command ------------------------------------------------------------


def test_parse_command_refuses_anything_that_could_leave_the_tree():
    assert file_moves.parse_command(_cmd()) is not None
    assert file_moves.parse_command(_cmd(from_rel="../../etc/passwd")) is None
    assert file_moves.parse_command(_cmd(to_project_rel="C:/Windows")) is None
    assert file_moves.parse_command(_cmd(from_rel="/abs")) is None or \
        file_moves.parse_command(_cmd(from_rel="/abs"))["from_rel"] == "abs"
    assert file_moves.parse_command(_cmd(id="x")) is None
    assert file_moves.parse_command("nope") is None
    parsed = file_moves.parse_command(_cmd(from_rel="B-roll\\A001_0512.braw"))
    assert parsed["from_rel"] == "B-roll/A001_0512.braw"


# -- the move -----------------------------------------------------------------


def test_a_file_moves_with_its_proxy_and_nothing_else(tmp_path):
    root = _tree(tmp_path)
    ok, detail, paths = file_moves.apply_move(file_moves.parse_command(_cmd()), str(root))
    assert ok, detail
    assert "1 proxy" in detail
    dest = root / "Projects" / ANIMALS / "Interviewees" / "Pangolin"
    assert (dest / "A001_0512.braw").read_bytes() == b"braw"
    assert (dest / "Proxy" / "A001_0512.mp4").exists()
    assert not (root / "Projects" / DRONE / "B-roll" / "A001_0512.braw").exists()
    assert (root / "Projects" / DRONE / "B-roll" / "A002_0513.braw").exists()
    assert paths == (str(root / "Projects" / DRONE / "B-roll" / "A001_0512.braw"),
                     str(dest / "A001_0512.braw"))


def test_a_folder_moves_whole(tmp_path):
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(_cmd(from_rel="B-roll", to_rel="Interviewees/Pangolin/B-roll",
                                        is_dir=True))
    ok, detail, paths = file_moves.apply_move(cmd, str(root))
    assert ok, detail
    assert (root / "Projects" / ANIMALS / "Interviewees" / "Pangolin" / "B-roll" / "Proxy"
            / "A001_0512.mp4").exists()
    assert not (root / "Projects" / DRONE / "B-roll").exists()


def test_nothing_here_is_a_successful_answer_and_a_clash_is_a_refusal(tmp_path):
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(_cmd(from_rel="B-roll/never_here.braw",
                                        to_rel="Interviewees/never_here.braw"))
    ok, detail, paths = file_moves.apply_move(cmd, str(root))
    assert ok and paths is None and "nothing at the old path" in detail

    clash = root / "Projects" / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw"
    clash.parent.mkdir(parents=True)
    clash.write_bytes(b"mine")
    ok, detail, paths = file_moves.apply_move(file_moves.parse_command(_cmd()), str(root))
    assert not ok and "already exists" in detail
    # NOTHING deleted, nothing overwritten.
    assert clash.read_bytes() == b"mine"
    assert (root / "Projects" / DRONE / "B-roll" / "A001_0512.braw").read_bytes() == b"braw"


def test_a_folder_is_never_moved_into_itself(tmp_path):
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(_cmd(from_rel="B-roll", to_project_rel=DRONE,
                                        to_rel="B-roll/inside", is_dir=True))
    ok, detail, _ = file_moves.apply_move(cmd, str(root))
    assert not ok and "into itself" in detail
    assert (root / "Projects" / DRONE / "B-roll" / "A001_0512.braw").exists()


# -- the ledger ---------------------------------------------------------------


def test_the_ledger_survives_a_restart_and_keeps_the_old_path_out_of_lane_a(tmp_path):
    clock = [1000.0]
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: clock[0])
    move = file_moves.parse_command(_cmd())
    ledger.record(move, ok=True, detail="moved")
    again = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: clock[0])
    assert again.entry(1)["ok"] is True
    # The old path is excluded for a day after an applied move...
    assert again.recent_excludes(f"Projects/{DRONE}") == ["B-roll/A001_0512.braw"]
    assert again.recent_excludes(f"projects/{DRONE.lower()}") == ["B-roll/A001_0512.braw"]
    assert again.recent_excludes(f"Projects/{ANIMALS}") == []
    # A whole-tree run (subpath=None) is the same answer one level up:
    # relative to local_root, so with the tree's top component on
    # (bug-hunt-2026-09-03 comp-sync-3).
    assert again.recent_excludes(None) == [f"Projects/{DRONE}/B-roll/A001_0512.braw"]
    # ...and not longer: the file is no longer there to be re-uploaded.
    clock[0] += file_moves.EXCLUDE_WINDOW_SECONDS + 1
    assert again.recent_excludes(f"Projects/{DRONE}") == []


def test_an_unapplied_move_holds_its_exclusion_open(tmp_path):
    """RES-1 (resilience sweep 2026-08-28): the copy is still AT the old path
    (that is why the move failed), so letting the 24 h window lapse is letting
    lane A -- which never deletes -- put it back on the NAS at the path the
    admin cleared."""
    clock = [1000.0]
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: clock[0])
    move = file_moves.parse_command(_cmd())
    ledger.record_attempt_failed(move, "open in Resolve")
    clock[0] += file_moves.EXCLUDE_WINDOW_SECONDS * 10
    assert ledger.recent_excludes(f"Projects/{DRONE}") == ["B-roll/A001_0512.braw"]


def test_a_failure_is_retried_on_a_schedule_and_then_blocked(tmp_path):
    clock = [1000.0]
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: clock[0])
    move = file_moves.parse_command(_cmd())
    entry = ledger.record_attempt_failed(move, "open in Resolve")
    assert entry["state"] == file_moves.STATE_RETRYABLE and entry["attempts"] == 1
    # Not due yet, due after ten minutes, then hourly.
    assert ledger.retry_due(entry) is False
    clock[0] += file_moves.RETRY_FIRST_SECONDS + 1
    assert ledger.retry_due(ledger.entry(1)) is True
    entry = ledger.record_attempt_failed(move, "open in Resolve")
    assert ledger.retry_due(entry) is False
    clock[0] += file_moves.RETRY_INTERVAL_SECONDS + 1
    assert ledger.retry_due(ledger.entry(1)) is True
    # The cap: it gives up rather than trying for ever, and says so.
    for _ in range(file_moves.RETRY_MAX_ATTEMPTS):
        clock[0] += file_moves.RETRY_INTERVAL_SECONDS + 1
        entry = ledger.record_attempt_failed(move, "open in Resolve")
    assert entry["state"] == file_moves.STATE_BLOCKED
    assert entry["next_attempt_at"] is None
    assert ledger.retry_due(entry) is False
    # Blocked still holds the old path out of lane A: the copy is still there.
    assert ledger.recent_excludes(f"Projects/{DRONE}") == ["B-roll/A001_0512.braw"]


def test_the_week_long_ceiling_also_gives_up(tmp_path):
    clock = [1000.0]
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: clock[0])
    move = file_moves.parse_command(_cmd())
    ledger.record_attempt_failed(move, "open in Resolve")
    clock[0] += file_moves.RETRY_MAX_SECONDS + 1
    entry = ledger.record_attempt_failed(move, "open in Resolve")
    assert entry["state"] == file_moves.STATE_BLOCKED and entry["attempts"] == 2


def test_the_ledger_knows_which_move_took_a_path_away(tmp_path):
    """RES-10: what turns a MISSING clip into a one-click relink."""
    clock = [1000.0]
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: clock[0])
    move = file_moves.parse_command(_cmd())
    ledger.record(move, ok=True, detail="moved",
                  paths=(r"D:\CC\Projects\old\clip.braw", r"D:\CC\Projects\new\clip.braw"),
                  relink_pending=True)
    assert ledger.moved_to(r"d:\cc\projects\OLD\clip.braw")["id"] == 1
    assert ledger.moved_to(r"D:\CC\Projects\other\clip.braw") is None
    assert [e["id"] for e in ledger.pending_relinks()] == [1]
    ledger.clear_relink_pending(1)
    assert ledger.pending_relinks() == []
    # ...and it stops being offered after a month.
    ledger.record(move, ok=True, detail="moved",
                  paths=(r"D:\CC\Projects\old\clip.braw", r"D:\CC\Projects\new\clip.braw"))
    clock[0] += file_moves.RELINK_WINDOW_SECONDS + 1
    assert ledger.moved_to(r"D:\CC\Projects\old\clip.braw") is None


def test_lane_a_keeps_a_moved_away_path_out_of_its_run(tmp_path):
    lane = RcloneLane(
        DIRECTION_UP, local_root=str(tmp_path), remote="nas", remote_root="root",
        state_dir=tmp_path / "state",
        extra_excludes_fn=lambda subpath: ["B-roll/A001_0512.braw"]
        if subpath == f"Projects/{DRONE}" else [],
    )
    lane._build_command(subpath=f"Projects/{DRONE}")
    rules = Path(lane._filter_file).read_text(encoding="utf-8").splitlines()
    assert "- /B-roll/A001_0512.braw" in rules
    assert rules.index("- /B-roll/A001_0512.braw") < rules.index("- **")
    lane._build_command(subpath=f"Projects/{ANIMALS}")
    rules = Path(lane._filter_file).read_text(encoding="utf-8").splitlines()
    assert "- /B-roll/A001_0512.braw" not in rules


# -- the app: once per move, answered every time it is asked ------------------


class _Stub:
    def __init__(self, tmp_path):
        self.root = _tree(tmp_path)
        self.config = {"local_root": str(self.root), "canonical_prefix": "P:\\"}
        self._root_absent = False
        self.file_moves = file_moves.FileMoveLedger(tmp_path / "state")
        self._file_move_answers = []
        self.toasts = []
        self.relinks = []
        self.relink_text = "2 Resolve clip(s) relinked"

    def _notify_tray(self, msg, title="x"):
        self.toasts.append((title, msg))

    def _relink_moved(self, old, new, is_dir):
        self.relinks.append((old, new, is_dir))
        return self.relink_text

    def _relink_moved_result(self, old, new, is_dir):
        return CompanionApp._relink_moved_result(self, old, new, is_dir)

    def _relink_pending_moves(self):
        CompanionApp._relink_pending_moves(self)

    def _queue_file_move_answer(self, move_id, ok, detail, state=None, attempts=0,
                                relink_pending=False):
        CompanionApp._queue_file_move_answer(self, move_id, ok, detail, state=state,
                                             attempts=attempts,
                                             relink_pending=relink_pending)

    def _file_move_results(self):
        return CompanionApp._file_move_results(self)

    def apply(self, resp):
        CompanionApp._apply_file_moves(self, resp)


def test_the_app_moves_once_relinks_and_answers_every_redelivery(tmp_path):
    stub = _Stub(tmp_path)
    resp = {"commands": {"file_moves": [_cmd()]}}
    stub.apply(resp)
    assert (stub.root / "Projects" / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw").exists()
    assert len(stub.relinks) == 1 and stub.relinks[0][2] is False
    (answer,) = stub._file_move_results()
    assert answer["id"] == 1 and answer["ok"] is True
    assert "moved" in answer["detail"] and "2 Resolve clip(s) relinked" in answer["detail"]
    assert stub._file_move_results() == []          # drained
    assert "file moved" in stub.toasts[-1][0]

    # Redelivered (the report that carried the answer was lost): answered
    # from the ledger, nothing moved again, nothing relinked again.
    stub.apply(resp)
    assert len(stub.relinks) == 1
    (answer,) = stub._file_move_results()
    assert answer["id"] == 1 and answer["ok"] is True


def test_the_app_reports_a_refusal_and_deletes_nothing(tmp_path):
    stub = _Stub(tmp_path)
    clash = stub.root / "Projects" / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw"
    clash.parent.mkdir(parents=True)
    clash.write_bytes(b"mine")
    stub.apply({"commands": {"file_moves": [_cmd()]}})
    (answer,) = stub._file_move_results()
    assert answer["ok"] is False and "already exists" in answer["detail"]
    # RES-1: an answer that does NOT retire the command server-side.
    assert answer["state"] == "retrying" and answer["attempts"] == 1
    assert stub.relinks == []
    assert clash.read_bytes() == b"mine"
    assert "needs attention" in stub.toasts[-1][0]
    # The old path is still kept out of lane A while the admin sorts it out.
    assert stub.file_moves.recent_excludes(f"Projects/{DRONE}") == ["B-roll/A001_0512.braw"]


def test_a_blocked_move_is_retried_until_it_works_then_answered_as_blocked(tmp_path):
    """RES-1 (resilience sweep 2026-08-28): a move Resolve was holding used to
    latch on the first PermissionError and re-answer the same failure for
    ever. It is retried on a schedule now, and it succeeds the moment the
    obstruction goes."""
    clock = [1000.0]
    stub = _Stub(tmp_path)
    stub.file_moves = file_moves.FileMoveLedger(tmp_path / "state2", now=lambda: clock[0])
    clash = stub.root / "Projects" / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw"
    clash.parent.mkdir(parents=True)
    clash.write_bytes(b"mine")
    resp = {"commands": {"file_moves": [_cmd()]}}
    stub.apply(resp)
    assert stub._file_move_results()[0]["state"] == "retrying"

    # Asked again before the retry is due: answered, not re-attempted.
    stub.apply(resp)
    (answer,) = stub._file_move_results()
    assert answer["state"] == "retrying" and answer["attempts"] == 1

    # The obstruction goes and the retry falls due: it moves.
    clash.unlink()
    clock[0] += file_moves.RETRY_FIRST_SECONDS + 1
    stub.apply(resp)
    (answer,) = stub._file_move_results()
    assert answer["ok"] is True
    assert (stub.root / "Projects" / ANIMALS / "Interviewees" / "Pangolin"
            / "A001_0512.braw").read_bytes() == b"braw"

    # And one that never clears is answered `blocked`, not silence.
    blocked = _Stub(tmp_path / "second")
    blocked.file_moves = file_moves.FileMoveLedger(tmp_path / "state3", now=lambda: clock[0])
    other = blocked.root / "Projects" / ANIMALS / "Interviewees" / "Pangolin" / "A001_0512.braw"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"mine")
    for _ in range(file_moves.RETRY_MAX_ATTEMPTS):
        clock[0] += file_moves.RETRY_INTERVAL_SECONDS + 1
        blocked.apply(resp)
    (answer,) = blocked._file_move_results()
    assert answer["ok"] is False and answer["state"] == "blocked"
    assert any("blocked" in t[0] for t in blocked.toasts)


def test_a_move_applied_with_no_project_open_stays_a_pending_relink(tmp_path):
    """RES-10: "Resolve not relinked (not open)" is not "there was nothing to
    relink". The move is revisited on every project change until a media pool
    walk actually matches."""
    stub = _Stub(tmp_path)
    stub.relink_text = "Resolve not relinked (not open)"
    stub.apply({"commands": {"file_moves": [_cmd()]}})
    (answer,) = stub._file_move_results()
    assert answer["ok"] is True and answer["relink_pending"] is True
    assert [e["id"] for e in stub.file_moves.pending_relinks()] == [1]

    # The editor opens the project the clips are in: it matches and retires.
    stub.relink_text = "2 Resolve clip(s) relinked"
    stub._relink_pending_moves()
    assert stub.file_moves.pending_relinks() == []
    assert len(stub.relinks) == 2
    (answer,) = stub._file_move_results()
    assert answer["ok"] is True and "relinked" in answer["detail"]


def test_a_missing_drive_defers_rather_than_answers(tmp_path):
    stub = _Stub(tmp_path)
    stub._root_absent = True
    stub.apply({"commands": {"file_moves": [_cmd()]}})
    assert stub._file_move_results() == []
    assert stub.file_moves.entry(1) is None
    assert (stub.root / "Projects" / DRONE / "B-roll" / "A001_0512.braw").exists()


def test_the_answers_ride_the_report(tmp_path):
    from ccsync_companion.reporter import DashboardReporter

    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)
        return {}

    cfg = {"editor_name": "owen", "dashboard_url": "http://dash.example.com",
           "dashboard_token": "tok123", "dashboard_report_interval": 60}
    answers = [[{"id": 1, "ok": True, "detail": "moved"}], []]
    reporter = DashboardReporter(lambda: [], cfg, http_post=fake_post,
                                 get_file_moves_applied=lambda: answers.pop(0))
    reporter.post_once()
    reporter.post_once()
    assert calls[0]["file_moves_applied"] == [{"id": 1, "ok": True, "detail": "moved"}]
    assert "file_moves_applied" not in calls[1]


def test_malformed_and_absent_commands_are_ignored(tmp_path):
    stub = _Stub(tmp_path)
    stub.apply({"commands": {"file_moves": [{"id": 3, "from_rel": "../x"}, "junk"]}})
    stub.apply({"commands": {}})
    stub.apply("not a dict")
    assert stub._file_move_results() == []


# -- SYNC-11: the exclusion across the Mac/NAS Unicode boundary ---------------

# The dashboard's from_rel is NFC; the same file on a Mac's own disk is NFD,
# and rclone matches an exclude rule against the bytes it reads off the disk.
_NFC_REL = "Interviewees/Matej Šimalčík/A002_07161726_C048.braw"
_NFD_REL = "Interviewees/Matej Šimalčík/A002_07161726_C048.braw"


def test_the_exclusion_is_emitted_in_both_unicode_spellings(tmp_path):
    """SYNC-11: one spelling excludes nothing on the platform the other one
    came from, and lane A then re-uploads the file to the path the admin just
    moved it away from."""
    assert _NFC_REL != _NFD_REL  # the pair really is two byte strings
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: 1000.0)
    ledger.record(file_moves.parse_command(_cmd(from_rel=_NFC_REL)), ok=True, detail="ok")
    got = ledger.recent_excludes(f"Projects/{DRONE}")
    assert set(got) == {_NFC_REL, _NFD_REL}


def test_an_ascii_path_is_still_one_rule(tmp_path):
    """The two spellings of an ASCII path are the same string: no duplicate."""
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: 1000.0)
    ledger.record(file_moves.parse_command(_cmd()), ok=True, detail="ok")
    assert ledger.recent_excludes(f"Projects/{DRONE}") == ["B-roll/A001_0512.braw"]


def test_every_exclusion_also_gets_the_directory_prune_form():
    """SYNC-11's other half: a move CAN name a directory (`is_dir`), and
    `- /Sub/Dir` alone is a directory-prune that is easy to get wrong."""
    from ccsync_companion.sync.rclone_lane import build_filter_rules_up

    rules = build_filter_rules_up(["B-roll/Gone"])
    assert "- /B-roll/Gone" in rules
    assert "- /B-roll/Gone/**" in rules
    # ...and both still come before the includes (first-match-wins).
    assert rules.index("- /B-roll/Gone/**") < rules.index("+ *.mov")


# -- comp-sync-3: the run root is a PREFIX, not an equal project rel ----------


def test_a_borrowed_subtree_run_still_carries_the_exclusion(tmp_path):
    """bug-hunt-2026-09-03 comp-sync-3: lane A over a borrowed include runs
    `Projects/<lender rel>/<sub rel>`, which can never equal a project rel.
    Demanding equality dropped every exclusion for that run, and lane A --
    which never deletes -- put the lender's file back at the path the admin
    had just cleared."""
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: 1000.0)
    ledger.record(file_moves.parse_command(_cmd()), ok=True, detail="ok")
    # The borrower syncs `<lender>/B-roll` alone.
    assert ledger.recent_excludes(f"Projects/{DRONE}/B-roll") == ["A001_0512.braw"]
    # A parent of the project is a run root too, and a sibling subtree is not.
    assert ledger.recent_excludes("Projects/2026") == [f"Base Drone/B-roll/A001_0512.braw"]
    assert ledger.recent_excludes(f"Projects/{DRONE}/Interviews") == []
    # A run root deeper than the moved file itself excludes nothing.
    assert ledger.recent_excludes(f"Projects/{DRONE}/B-roll/A001_0512.braw") == []


def test_the_run_root_matches_across_the_unicode_boundary(tmp_path):
    """The same CR-90 hazard SYNC-11 covers for the emitted path, on the
    matching side: a run root spelled NFD names the NFC project."""
    import unicodedata

    rel = "2026/Matej Šimalčík"
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: 1000.0)
    ledger.record(file_moves.parse_command(_cmd(from_project_rel=rel)),
                  ok=True, detail="ok")
    nfd_root = "Projects/" + unicodedata.normalize("NFD", rel)
    assert ledger.recent_excludes(nfd_root) == ["B-roll/A001_0512.braw"]


# -- comp-sync-2: the ledger lookup across the Mac/NAS Unicode boundary -------

SEP = "\\" if __import__("os").sep == "\\" else "/"


def test_a_moved_file_is_found_under_either_unicode_spelling(tmp_path):
    """bug-hunt-2026-09-03 comp-sync-2: the ledger records the dashboard's NFC
    path; the watcher asks about the path Resolve gave it, which on a Mac is
    NFD. Without folding, RES-10's one-click relink was never offered for any
    accented name and the clip looked like a mystery offline clip forever."""
    import unicodedata

    nfc = "D:" + SEP + "CC" + SEP + "Projects" + SEP + "2026" + SEP + "Matej Šimalčík" + SEP + "A002.braw"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    ledger = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: 1000.0)
    new = "D:" + SEP + "CC" + SEP + "Projects" + SEP + "2026" + SEP + "new" + SEP + "A002.braw"
    ledger.record(file_moves.parse_command(_cmd()), ok=True, detail="moved",
                  paths=(nfc, new), relink_pending=True)
    assert ledger.moved_to(nfc)["id"] == 1
    assert ledger.moved_to(nfd)["id"] == 1
