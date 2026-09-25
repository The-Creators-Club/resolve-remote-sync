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


# -- res-fleet-3: section 4b, a destination this machine does not sync -------


def _plan(*rels):
    """The shape app._synced_project_rels() hands in: every Projects-relative
    path this machine syncs, borrowed subtrees included."""
    return list(rels)


def test_a_move_into_a_project_this_machine_does_not_sync_is_trashed(tmp_path):
    """res-fleet-3 / HAND_MOVES_ON_THE_SERVER.md section 4b: the dashboard
    picks its target machines from the SOURCE project's ticks, so a move
    between two projects reaches machines that do not sync the destination.
    `mkdir(parents=True)` there built a directory with no `.ccsync-project`
    marker - invisible to fixer.list_project_dirs, to the manifest and to both
    lanes - and the MOVES history said that computer had followed."""
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(_cmd())
    ledger = file_moves.FileMoveLedger(tmp_path / "state" / "file_moves.json")

    ok, detail, paths = file_moves.apply_move(
        cmd, str(root), ledger, project_rels=_plan(DRONE))

    assert ok is True, "nothing failed: the file is safe, just not here"
    assert detail == file_moves.DETAIL_NOT_SYNCED_HERE
    assert paths is None, "nothing to relink Resolve to"
    # It is NOT at the old path, NOT at the new one, and the destination
    # project directory was never created.
    assert not (root / "Projects" / DRONE / "B-roll" / "A001_0512.braw").exists()
    assert not (root / "Projects" / ANIMALS).exists()
    # It IS in the lane B trash, under its own project path, recoverable.
    trashed = list((root / file_moves.TRASH_DIR_NAME).rglob("A001_0512.braw"))
    assert len(trashed) == 1
    assert trashed[0].read_bytes() == b"braw"
    assert DRONE.split("/")[-1] in str(trashed[0])


def _card_dump(root):
    """An upload-only machine part-way through a card dump: the server has
    A001 (lane A got it up before the owner moved the folder), A002 is still
    only here. The proxy is lane B's."""
    card = root / "Projects" / DRONE / "Card_07"
    (card / "Proxy").mkdir(parents=True)
    (card / "A001.mov").write_bytes(b"uploaded")
    (card / "A002.mov").write_bytes(b"never reached the server")
    (card / "Proxy" / "A001.mp4").write_bytes(b"proxy")
    return card


def _card_cmd():
    return file_moves.parse_command(_cmd(
        from_rel="Card_07", to_rel="Card_07", is_dir=True))


def test_4b_never_trashes_a_folder_holding_originals_the_server_may_not_have(tmp_path):
    """logic-plans-3 (2026-09-24): section 4b moved the WHOLE local folder
    into `.ccsync-trash`, including originals lane A had not uploaded yet.
    Lane A never walks the trash, prune_trash deleted them a fortnight later,
    and the answer said the machine had followed. With no server listing to
    prove otherwise, a folder holding any lane A original stays put.

    Review round (2026-09-24): and the answer is NOT ok. An ok answer is a
    done move, whose lane A exclusion lapses after a day, after which lane A
    re-uploaded every original in the folder to the path the admin cleared.
    Not-ok is recorded `retrying`, which keeps RES-1's exclusion open."""
    root = _tree(tmp_path)
    card = _card_dump(root)
    ledger = file_moves.FileMoveLedger(tmp_path / "state" / "file_moves.json")

    ok, detail, paths = file_moves.apply_move(
        _card_cmd(), str(root), ledger, project_rels=_plan(DRONE))

    assert (card / "A002.mov").read_bytes() == b"never reached the server"
    assert (card / "A001.mov").exists()
    assert not list((root / file_moves.TRASH_DIR_NAME).rglob("*.mov")), (
        "an original the server may not hold went to the trash")
    assert ok is False and paths is None
    assert detail == file_moves.DETAIL_4B_CANNOT_LIST
    assert not (root / "Projects" / ANIMALS).exists()


def test_4b_a_folder_it_could_not_triage_stays_excluded_past_a_day(tmp_path):
    """logic-plans-3 review (2026-09-24): the whole path, as app.py records
    it. The not-ok answer becomes a `retryable` ledger row, and a retryable
    row's exclusion outlives EXCLUDE_WINDOW_SECONDS, so lane A does not put
    Card_07 back on the NAS under the project it was moved out of."""
    root = _tree(tmp_path)
    _card_dump(root)
    clock = [1_000_000.0]
    ledger = file_moves.FileMoveLedger(tmp_path / "state" / "file_moves.json",
                                       now=lambda: clock[0])
    move = _card_cmd()

    ok, detail, _ = file_moves.apply_move(
        move, str(root), ledger, project_rels=_plan(DRONE),
        server_files=lambda _rel: None)
    assert ok is False
    entry = ledger.record_attempt_failed(move, detail)
    assert entry["state"] == file_moves.STATE_RETRYABLE

    clock[0] += file_moves.EXCLUDE_WINDOW_SECONDS * 3
    assert "Card_07" in ledger.recent_excludes(f"Projects/{DRONE}")


def test_4b_a_moved_proxy_folder_holds_no_original(tmp_path):
    """logic-plans-3 review: lane A skips anything under a `Proxy` component
    at ANY depth of the tree path. The folder's own name counts, so a moved
    Proxy dir of .mov files owes lane A nothing and goes whole without a
    listing; judged by the path under the folder alone, its .movs looked
    like originals and sat at the old path for ever."""
    root = _tree(tmp_path)
    proxy_dir = root / "Projects" / DRONE / "B-roll" / "Proxy"
    (proxy_dir / "A009.mov").write_bytes(b"a proxy in a .mov wrapper")
    move = file_moves.parse_command(_cmd(
        from_rel="B-roll/Proxy", to_rel="B-roll/Proxy", is_dir=True))

    ok, detail, _ = file_moves.apply_move(
        move, str(root), None, project_rels=_plan(DRONE))

    assert ok is True and detail == file_moves.DETAIL_NOT_SYNCED_HERE
    assert not proxy_dir.exists()


def test_4b_folds_the_server_listing_once_per_folder(tmp_path, monkeypatch):
    """logic-plans-3 review: the listing is folded into a set once, not once
    per local file (a card dump of thousands of clips was millions of NFC
    folds on the reporter thread)."""
    root = _tree(tmp_path)
    card = _card_dump(root)
    for n in range(40):
        (card / f"B{n:03}.mov").write_bytes(b"x" * (n + 1))
    listing = {(f"B{n:03}.mov", n + 1) for n in range(40)} | {("other.mov", 1)}
    calls = [0]
    real = file_moves._cmp_key

    def counting(path):
        calls[0] += 1
        return real(path)

    monkeypatch.setattr(file_moves, "_cmp_key", counting)
    file_moves.apply_move(_card_cmd(), str(root), None, project_rels=_plan(DRONE),
                          server_files=lambda _rel: listing)

    local_files = 43
    assert calls[0] <= 2 * (len(listing) + local_files), calls[0]


def test_4b_with_a_server_listing_trashes_only_what_the_server_holds(tmp_path):
    """logic-plans-3: given the server's files at the destination, the ones it
    holds go to the trash (recoverable from the server too) and the local-only
    original stays where lane A will upload it."""
    root = _tree(tmp_path)
    card = _card_dump(root)
    asked = []

    def server_files(dest_rel):
        asked.append(dest_rel)
        return {("A001.mov", len(b"uploaded")), ("Proxy/A001.mp4", len(b"proxy"))}

    ok, detail, paths = file_moves.apply_move(
        _card_cmd(), str(root), None, project_rels=_plan(DRONE),
        server_files=server_files)

    assert asked == [ANIMALS + "/Card_07"]
    assert ok is True and paths is None
    assert (card / "A002.mov").read_bytes() == b"never reached the server"
    assert not (card / "A001.mov").exists()
    trashed = {p.name for p in (root / file_moves.TRASH_DIR_NAME).rglob("*") if p.is_file()}
    assert trashed == {"A001.mov", "A001.mp4"}
    assert "kept 1 file" in detail and "trashed 2" in detail


def test_4b_a_same_name_file_of_another_size_is_not_the_servers_copy(tmp_path):
    root = _tree(tmp_path)
    card = _card_dump(root)

    file_moves.apply_move(
        _card_cmd(), str(root), None, project_rels=_plan(DRONE),
        server_files=lambda _rel: {("A001.mov", 1), ("A002.mov", 2)})

    assert (card / "A001.mov").exists() and (card / "A002.mov").exists()


def test_4b_a_file_that_lands_during_the_listing_is_never_binned(tmp_path):
    """logic-plans-3 round 2 (2026-09-25): the triage snapshot is taken
    before a listing of up to two minutes. When every snapshotted file was
    on the server, the old code moved the WHOLE folder into the trash, and a
    clip that landed in it during the listing (a card dump still copying)
    went with it, never checked against the server, gone in 14 days."""
    root = _tree(tmp_path)
    card = root / "Projects" / DRONE / "Card_07"
    card.mkdir(parents=True)
    (card / "A001.mov").write_bytes(b"uploaded")

    def server_files(_rel):
        (card / "A002.mov").write_bytes(b"landed during the listing")
        return {("A001.mov", len(b"uploaded"))}

    ok, detail, paths = file_moves.apply_move(
        _card_cmd(), str(root), None, project_rels=_plan(DRONE),
        server_files=server_files)

    assert (card / "A002.mov").read_bytes() == b"landed during the listing"
    trashed = {p.name for p in (root / file_moves.TRASH_DIR_NAME).rglob("*") if p.is_file()}
    assert trashed == {"A001.mov"}
    assert ok is True and paths is None
    assert detail != file_moves.DETAIL_NOT_SYNCED_HERE
    assert "kept 1 file" in detail and "A002.mov" in detail


def test_4b_a_file_rewritten_during_the_listing_is_not_the_servers_copy(tmp_path):
    """logic-plans-3 round 2: the size matched before the listing is the
    size that was compared; a file that grew since stays for lane A."""
    root = _tree(tmp_path)
    card = root / "Projects" / DRONE / "Card_07"
    card.mkdir(parents=True)
    (card / "A001.mov").write_bytes(b"part")

    def server_files(_rel):
        (card / "A001.mov").write_bytes(b"part and the rest of it")
        return {("A001.mov", len(b"part"))}

    ok, _detail, _ = file_moves.apply_move(
        _card_cmd(), str(root), None, project_rels=_plan(DRONE),
        server_files=server_files)

    assert ok is True
    assert (card / "A001.mov").read_bytes() == b"part and the rest of it"


def test_4b_a_folder_the_server_holds_whole_leaves_no_husk(tmp_path):
    """logic-plans-3 round 2: binned file by file, the emptied tree is
    removed with rmdir, and the answer is still the plain not-synced-here
    one, as when the folder went whole."""
    root = _tree(tmp_path)
    card = _card_dump(root)
    (card / "A002.mov").unlink()

    ok, detail, _ = file_moves.apply_move(
        _card_cmd(), str(root), None, project_rels=_plan(DRONE),
        server_files=lambda _rel: {("A001.mov", len(b"uploaded")),
                                   ("Proxy/A001.mp4", len(b"proxy"))})

    assert ok is True and detail == file_moves.DETAIL_NOT_SYNCED_HERE
    assert not card.exists()
    trashed = {p.name for p in (root / file_moves.TRASH_DIR_NAME).rglob("*") if p.is_file()}
    assert trashed == {"A001.mov", "A001.mp4"}


def test_4b_a_failed_server_listing_is_not_evidence(tmp_path):
    root = _tree(tmp_path)
    card = _card_dump(root)

    def broken(_rel):
        raise OSError("rclone is not there")

    ok, detail, _ = file_moves.apply_move(
        _card_cmd(), str(root), None, project_rels=_plan(DRONE), server_files=broken)

    assert ok is False and detail == file_moves.DETAIL_4B_CANNOT_LIST
    assert (card / "A002.mov").exists() and (card / "A001.mov").exists()


def test_4b_still_trashes_a_folder_that_holds_no_original(tmp_path):
    """A folder of proxies and sidecars owes lane A nothing, so it goes whole,
    as it always did."""
    root = _tree(tmp_path)
    folder = root / "Projects" / DRONE / "Card_07"
    (folder / "Proxy").mkdir(parents=True)
    (folder / "Proxy" / "A001.mp4").write_bytes(b"proxy")

    ok, detail, _ = file_moves.apply_move(
        _card_cmd(), str(root), None, project_rels=_plan(DRONE))

    assert ok is True and detail == file_moves.DETAIL_NOT_SYNCED_HERE
    assert not folder.exists()


def test_the_rclone_server_listing_reads_lane_as_own_format():
    seen = []

    def run(cmd, timeout):
        seen.append(cmd)
        return "8;A001.mov\n5;Proxy/A001.mp4\nnot a line\n"

    listing = file_moves.rclone_server_files("rclone", "nas", "/mnt/tank/Creators_Club",
                                             run_fn=run)
    assert listing(ANIMALS + "/Card_07") == {("A001.mov", 8), ("Proxy/A001.mp4", 5)}
    assert seen[0][-1].endswith("Projects/" + ANIMALS + "/Card_07")
    assert file_moves.rclone_server_files("rclone", "nas", "/r",
                                          run_fn=lambda c, t: None)("x") is None


def test_the_rclone_server_listing_asks_where_lane_a_uploads(tmp_path):
    """logic-plans-3 review: the listing must name the same remote directory
    lane A copies that folder INTO, or "the server holds it" is a question
    about the wrong place. Compared against build_up_command's own remote
    side for the same run root, not against a hand-built string."""
    from ccsync_companion.sync import rclone_lane

    seen = []
    listing = file_moves.rclone_server_files(
        "rclone", "nas", "/mnt/tank/Creators_Club/",
        run_fn=lambda cmd, timeout: seen.append(cmd) or "")
    listing(ANIMALS + "/Card_07")

    rules = tmp_path / "filter_up.txt"
    rclone_lane.write_filter_file(rclone_lane.build_filter_rules_up(), rules)
    up = rclone_lane.build_up_command(
        "rclone", str(tmp_path), "nas", "/mnt/tank/Creators_Club/", rules,
        subpath=f"Projects/{ANIMALS}/Card_07")
    assert seen[0][-1] == up[3]


def test_the_trashed_outcome_is_recorded_with_its_own_word(tmp_path):
    """res-fleet-3: `ok` and the sentence are the wire as it was - a dashboard
    that drops the word still records the move as done with an honest detail -
    and the WORD is what lets the project page say "trashed locally"."""
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(_cmd())
    ledger = file_moves.FileMoveLedger(tmp_path / "state" / "file_moves.json")

    ok, detail, _paths = file_moves.apply_move(
        cmd, str(root), ledger, project_rels=_plan(DRONE))
    ledger.record(cmd, ok, detail, state=file_moves.STATE_NOT_SYNCED_HERE)

    entry = ledger.entry(cmd["id"])
    assert entry["state"] == file_moves.STATE_NOT_SYNCED_HERE
    assert entry["ok"] is True
    assert entry["detail"] == file_moves.DETAIL_NOT_SYNCED_HERE
    # ...and it survives a restart, so a redelivery re-answers the same way.
    again = file_moves.FileMoveLedger(tmp_path / "state" / "file_moves.json")
    assert again.entry(cmd["id"])["state"] == file_moves.STATE_NOT_SYNCED_HERE


def test_a_move_into_a_BORROWED_folder_is_carried_out_normally(tmp_path):
    """res-fleet-3's other end (comp-sync-4): a borrowed subtree is on this
    disk, and judging by the selection alone would trash a file that has a
    perfectly good home here. The plan map is
    `sequencer.rel_to_slug_with_borrowed()`, whose borrowed keys are the
    LENDER's subpath."""
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(_cmd())
    borrowed_sub = ANIMALS + "/Interviewees"

    ok, detail, paths = file_moves.apply_move(
        cmd, str(root), None, project_rels=_plan(DRONE, borrowed_sub))

    assert ok is True and detail.startswith("moved")
    assert paths is not None
    assert (root / "Projects" / ANIMALS / "Interviewees" / "Pangolin"
            / "A001_0512.braw").read_bytes() == b"braw"
    assert not list((root / file_moves.TRASH_DIR_NAME).rglob("*.braw"))


def test_the_rest_of_a_lenders_project_is_still_not_synced_here(tmp_path):
    """res-fleet-3: borrowing one folder of a project does not put the rest of
    it on this disk."""
    root = _tree(tmp_path)
    cmd = file_moves.parse_command(_cmd(to_rel="Camera B/A001_0512.braw"))
    ok, detail, _ = file_moves.apply_move(
        cmd, str(root), None, project_rels=_plan(DRONE, ANIMALS + "/Interviewees"))
    assert ok is True and detail == file_moves.DETAIL_NOT_SYNCED_HERE


def test_no_plan_at_all_keeps_the_old_behaviour(tmp_path):
    """res-fleet-3: None is not an empty plan. An unmanaged companion has no
    sequencer, and reading that as "nothing is synced here" would trash every
    moved file on a machine whose whole tree is local - which is also what
    keeps the positional signature every existing caller uses working."""
    root = _tree(tmp_path)
    ok, detail, paths = file_moves.apply_move(
        file_moves.parse_command(_cmd()), str(root))
    assert ok is True and detail.startswith("moved") and paths is not None


def test_the_app_answers_a_not_synced_destination_with_its_own_state_word(tmp_path):
    """res-fleet-3, through the real command path: the answer keeps ok=True
    and the sentence (a 0.7.49 dashboard reads both unchanged) and ADDS
    `state: not_synced_here`, which is what lets the project page say
    "trashed locally" instead of "moved"."""
    from ccsync_companion import app as app_mod

    root = _tree(tmp_path)
    answers: list = []

    class _Sequencer:
        def rel_to_slug_with_borrowed(self):
            return {DRONE: "d"}

    class _Stub:
        config = {"local_root": str(root)}
        _root_absent = False
        sequencer = _Sequencer()

        def __init__(self):
            self.file_moves = file_moves.FileMoveLedger(
                tmp_path / "state" / "file_moves.json")

        def _relink_moved_result(self, *a):            # never reached here
            raise AssertionError("nothing moved to a path Resolve should follow")

        def _notify_tray(self, *a, **k):
            pass

        def _queue_file_move_answer(self, move_id, ok, detail, state=None,
                                    attempts=0, relink_pending=False):
            answers.append({"id": move_id, "ok": ok, "detail": detail,
                            "state": state})

        _apply_file_moves = app_mod.CompanionApp._apply_file_moves

    stub = _Stub()
    stub._apply_file_moves({"commands": {"file_moves": [_cmd()]},
                            "dashboard_version": "0.7.50"})

    assert answers == [{"id": 1, "ok": True,
                        "detail": file_moves.DETAIL_NOT_SYNCED_HERE,
                        "state": file_moves.STATE_NOT_SYNCED_HERE}]
    assert not (root / "Projects" / ANIMALS).exists()
    assert list((root / file_moves.TRASH_DIR_NAME).rglob("A001_0512.braw"))

    # ...and a redelivery re-answers with the same word rather than a plain
    # "moved", which is what the dashboard records the second time.
    answers.clear()
    stub._apply_file_moves({"commands": {"file_moves": [_cmd()]},
                            "dashboard_version": "0.7.50"})
    assert answers[0]["state"] == file_moves.STATE_NOT_SYNCED_HERE


# The five words `FileMoveResultIn.state` accepted BEFORE res-fleet-3's
# dashboard half (dashboard/src/ccsync_dashboard/api.py). Copied rather than
# imported: the dashboard is a separate package with its own venv, and this
# suite runs on machines that have never installed it. `file_moves_applied`
# is not one of ReportIn's tolerant sections, so an unknown word here is not
# a dropped field - it is a 422 for the WHOLE report, every thirty seconds,
# until somebody upgrades the dashboard.
PRE_RES_FLEET_3_STATES = frozenset(
    {"done", "failed", "retrying", "blocked", "applying"})


def _answers_from(reply, tmp_path):
    from ccsync_companion import app as app_mod

    root = _tree(tmp_path)
    answers: list = []

    class _Sequencer:
        def rel_to_slug_with_borrowed(self):
            return {DRONE: "d"}

    class _Stub:
        config = {"local_root": str(root)}
        _root_absent = False
        sequencer = _Sequencer()

        def __init__(self):
            self.file_moves = file_moves.FileMoveLedger(
                tmp_path / "state" / "file_moves.json")

        def _relink_moved_result(self, *a):
            raise AssertionError("nothing moved to a path Resolve should follow")

        def _notify_tray(self, *a, **k):
            pass

        def _queue_file_move_answer(self, move_id, ok, detail, state=None,
                                    attempts=0, relink_pending=False):
            answers.append({"id": move_id, "ok": ok, "detail": detail,
                            "state": state})

        _apply_file_moves = app_mod.CompanionApp._apply_file_moves

    stub = _Stub()
    payload = {"commands": {"file_moves": [_cmd()]}}
    payload.update(reply)
    stub._apply_file_moves(payload)
    return answers, stub, root


def test_the_state_word_is_withheld_from_a_dashboard_that_would_422_on_it(tmp_path):
    """res-fleet-3, the wire half: a word an older dashboard does not know is
    not a dropped field, it is a 422 for the whole report - so 0.9.75 against
    a 0.7.49 dashboard would lose the lanes, the presence and the alarms of
    every machine, twice a minute, for one line on one page. The answer stays
    ok=True with the honest sentence, which every dashboard in the field
    already reads."""
    for reply in ({"dashboard_version": "0.7.49"},
                  {},                                  # older than the key
                  {"dashboard_version": "nightly"}):   # unrankable
        answers, _stub, root = _answers_from(reply, tmp_path / str(hash(str(reply))))
        assert len(answers) == 1
        assert answers[0]["ok"] is True
        assert answers[0]["detail"] == file_moves.DETAIL_NOT_SYNCED_HERE
        assert answers[0]["state"] is None
        assert answers[0]["state"] in (None, *PRE_RES_FLEET_3_STATES), (
            "this is what the pre-fix Literal would have to accept")
        # The file is still trashed and still not in a directory that is not
        # a project here: the WIRE is what is held back, never the fix.
        assert not (root / "Projects" / ANIMALS).exists()
        assert list((root / file_moves.TRASH_DIR_NAME).rglob("A001_0512.braw"))


def test_a_dashboard_that_knows_the_word_is_told(tmp_path):
    """res-fleet-3: and from 0.7.50 on, the project page can say "trashed
    locally" instead of "moved"."""
    for version in ("0.7.50", "0.7.51", "0.8.0"):
        answers, stub, _root = _answers_from(
            {"dashboard_version": version}, tmp_path / version)
        assert answers[0]["state"] == file_moves.STATE_NOT_SYNCED_HERE
        # The LEDGER records the word whatever the dashboard knows: it is this
        # machine's own record and nothing validates it.
        assert stub.file_moves.entry(1)["state"] == file_moves.STATE_NOT_SYNCED_HERE


def test_the_ledger_keeps_the_word_even_when_the_wire_cannot(tmp_path):
    """res-fleet-3: withholding the word from an old dashboard must not make
    this machine forget what it did - the redelivery has to answer the same
    way, and the day the dashboard is upgraded it should start saying so."""
    answers, stub, _root = _answers_from({"dashboard_version": "0.7.49"}, tmp_path)
    assert answers[0]["state"] is None
    assert stub.file_moves.entry(1)["state"] == file_moves.STATE_NOT_SYNCED_HERE

    answers.clear()
    stub._apply_file_moves({"commands": {"file_moves": [_cmd()]},
                            "dashboard_version": "0.7.50"})
    assert answers[0]["state"] == file_moves.STATE_NOT_SYNCED_HERE


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


def test_a_missing_drive_answers_retrying_and_decides_nothing(tmp_path):
    """comp-sync-20 (2026-09-11) changed the first half of this: the answer
    used to be SILENCE, and the dashboard expires a command after 7 days of
    "told and never answered" - so an editor away with the drive in their bag
    had the move quietly dropped. `retrying` is the v36 shape for "still
    working on it, do not retire this". The second half is unchanged and is
    the point: nothing is decided, nothing is recorded, the file is not
    touched, and `attempts` is not spent."""
    stub = _Stub(tmp_path)
    stub._root_absent = True
    stub.apply({"commands": {"file_moves": [_cmd()]}})
    (answer,) = stub._file_move_results()
    assert answer["ok"] is False and answer["state"] == "retrying"
    assert "sync drive" in answer["detail"]
    assert "attempts" not in answer
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


# -- SYNC-102: the relink sync/repath.py borrows -----------------------------

def test_relink_moved_repoints_the_pool_through_replace_clip(tmp_path, monkeypatch):
    """The whole-directory case a server-side project rename needs (SYNC-102,
    sweep 2026-09-03). Every write still goes through replace_clip, which is
    what takes the save point and writes the undo journal."""
    from ccsync_companion import resolve_bridge

    root = _tree(tmp_path)
    old = str(root / "Projects" / DRONE)
    new = str(root / "Projects" / "2026" / "Renamed")
    canonical_old = "P:" + chr(92) + chr(92).join(
        ["", "Projects"] + DRONE.split("/") + ["B-roll", "A001_0512.braw"])
    replaced: list[tuple] = []
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: {
        "ok": True,
        "items": [{"file_path": canonical_old},
                  {"file_path": "P:" + chr(92) + "Projects" + chr(92) + "Elsewhere"}],
    })
    monkeypatch.setattr(resolve_bridge, "resolve_media_pool_item", lambda item: object())
    monkeypatch.setattr(resolve_bridge, "replace_clip",
                        lambda clip, path, source=None: (replaced.append((path, source))
                                                         or {"ok": True}))

    matched, text = file_moves.relink_moved(old, new, str(root), "P:" + chr(92),
                                            is_dir=True)
    # regression-19 hand-off (2026-09-11b): a real plural, because this
    # sentence reaches the editor through the RELINK IT toast.
    assert matched is True and "1 Resolve clip relinked" in text
    assert len(replaced) == 1
    assert replaced[0][0].endswith(chr(92).join(["Renamed", "B-roll", "A001_0512.braw"]))
    assert replaced[0][1] == "file_move"


def test_relink_moved_says_so_when_resolve_is_not_open(tmp_path, monkeypatch):
    from ccsync_companion import resolve_bridge

    monkeypatch.setattr(resolve_bridge, "get_media_pool_items",
                        lambda: {"ok": False, "message": "not open"})
    matched, text = file_moves.relink_moved("a", "b", str(tmp_path), "P:" + chr(92))
    assert matched is False and "not open" in text


def _4b_app_stub(tmp_path, root, config):
    from ccsync_companion import app as app_mod

    answers: list = []

    class _Sequencer:
        def rel_to_slug_with_borrowed(self):
            return {DRONE: "d"}

    class _Stub:
        _root_absent = False
        sequencer = _Sequencer()

        def __init__(self):
            self.config = dict(config, local_root=str(root))
            self.file_moves = file_moves.FileMoveLedger(tmp_path / "state")

        def _relink_moved_result(self, *a):
            raise AssertionError("nothing moved to a path Resolve should follow")

        def _notify_tray(self, *a, **k):
            pass

        def _queue_file_move_answer(self, move_id, ok, detail, state=None,
                                    attempts=0, relink_pending=False):
            answers.append({"id": move_id, "ok": ok, "detail": detail,
                            "state": state})

        _apply_file_moves = app_mod.CompanionApp._apply_file_moves

    return _Stub(), answers


def test_the_app_lists_the_server_through_lane_as_remote_for_4b(tmp_path, monkeypatch):
    """logic-plans-3 review (2026-09-24): `server_files` was built but never
    passed, so every machine took the no-listing branch. The app now asks
    through the configured rclone, remote and remote_root, and a folder the
    listing proves the server holds goes to the trash as a done move."""
    from ccsync_companion.sync import rclone_lane

    root = _tree(tmp_path)
    card = _card_dump(root)
    seen = []

    def lsf(cmd, timeout):
        seen.append(cmd)
        return "8;A001.mov\n24;A002.mov\n5;Proxy/A001.mp4\n"

    monkeypatch.setattr(rclone_lane, "_run_lsf", lsf)
    stub, answers = _4b_app_stub(tmp_path, root, {
        "rclone_path": "C:/tools/rclone.exe", "remote": "nas",
        "remote_root": "/mnt/tank/Creators_Club"})

    stub._apply_file_moves({"commands": {"file_moves": [_cmd(
        from_rel="Card_07", to_rel="Card_07", is_dir=True)]},
        "dashboard_version": "0.7.56"})

    assert seen and seen[0][0] == "C:/tools/rclone.exe"
    assert seen[0][-1] == f"nas:/mnt/tank/Creators_Club/Projects/{ANIMALS}/Card_07"
    assert answers[0]["ok"] is True
    assert not card.exists()


def test_the_app_answers_retrying_when_4b_cannot_list_the_server(tmp_path):
    """logic-plans-3 review: with no remote configured the listing is
    unavailable, and a folder holding originals is kept AND answered
    `retrying`, so its lane A exclusion does not lapse after a day."""
    root = _tree(tmp_path)
    card = _card_dump(root)
    stub, answers = _4b_app_stub(tmp_path, root, {})

    stub._apply_file_moves({"commands": {"file_moves": [_cmd(
        from_rel="Card_07", to_rel="Card_07", is_dir=True)]},
        "dashboard_version": "0.7.56"})

    assert answers[0]["ok"] is False and answers[0]["state"] == "retrying"
    assert answers[0]["detail"] == file_moves.DETAIL_4B_CANNOT_LIST
    assert (card / "A002.mov").exists()
    assert stub.file_moves.entry(1)["state"] == file_moves.STATE_RETRYABLE
