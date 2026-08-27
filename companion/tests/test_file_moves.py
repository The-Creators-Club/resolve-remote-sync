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
    ledger.record(move, ok=False, detail="destination exists")
    again = file_moves.FileMoveLedger(tmp_path / "state", now=lambda: clock[0])
    assert again.entry(1)["ok"] is False
    # Applied or refused, the old path is excluded for a day...
    assert again.recent_excludes(f"Projects/{DRONE}") == ["B-roll/A001_0512.braw"]
    assert again.recent_excludes(f"projects/{DRONE.lower()}") == ["B-roll/A001_0512.braw"]
    assert again.recent_excludes(f"Projects/{ANIMALS}") == []
    assert again.recent_excludes(None) == []
    # ...and not longer.
    clock[0] += file_moves.EXCLUDE_WINDOW_SECONDS + 1
    assert again.recent_excludes(f"Projects/{DRONE}") == []


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

    def _notify_tray(self, msg, title="x"):
        self.toasts.append((title, msg))

    def _relink_moved(self, old, new, is_dir):
        self.relinks.append((old, new, is_dir))
        return "2 Resolve clip(s) relinked"

    def _queue_file_move_answer(self, move_id, ok, detail):
        CompanionApp._queue_file_move_answer(self, move_id, ok, detail)

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
    assert stub.relinks == []
    assert clash.read_bytes() == b"mine"
    assert "needs attention" in stub.toasts[-1][0]
    # The old path is still kept out of lane A while the admin sorts it out.
    assert stub.file_moves.recent_excludes(f"Projects/{DRONE}") == ["B-roll/A001_0512.braw"]


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
