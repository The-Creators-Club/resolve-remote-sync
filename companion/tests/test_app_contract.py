"""The readers the tray, the Settings window and the report ask (wave 3 of the
usability + resilience sweep, 2026-09-04).

Every function here is a CONTRACT: two renderers and the dashboard are coded
against these names. So each one gets three questions, and they are the three
that broke things in the field before:

  * does it EXIST (a renderer calling a name that is not there is a window
    that does not draw at all);
  * does it survive its producer being ABSENT (an older lane module, a
    companion built with no proxy generator, a sequencer that predates the
    method) -- absent must cost the line, never the window;
  * and does it say the right thing when the producer IS there.

Nothing here touches Resolve (conftest's `_no_live_resolve`), a real Tk root or
a network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ccsync_companion import app as app_mod
from ccsync_companion import drive_reminder as drive_reminder_mod
from ccsync_companion import resolve_journal, upgrade as upgrade_mod
from ccsync_companion.app import CompanionApp


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "poll_interval": 3,
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _app(tmp_path, **overrides) -> CompanionApp:
    return CompanionApp(_cfg(tmp_path, **overrides))


# The whole contract, by name. A rename that is not carried into the tray and
# the Settings window is a KeyError in a window an editor opened because
# something was already wrong (CR-93's lesson about which surfaces matter).
CONTRACT = (
    "sync_now", "sync_now_result", "trash_path", "trash_summary",
    "resolve_health", "config_problem_detail", "config_problem_details",
    "youtube_import_state", "ytdl_login_progress", "size_mismatch_samples",
    "shared_folder_problems", "repath_events", "broll_failed_items",
    "jobs_status", "jobs_gate", "stop_current_job", "cancel_local_downloads",
    "undo_last_fix_available", "undo_last_fix", "undo_last_fix_summary",
    "open_licence_dialog", "sign_in_again", "restart_self", "proxy_gaps",
    "stills_state", "plan_age_seconds",
)


def test_every_contract_function_exists_and_answers_with_no_producer(tmp_path):
    """A bare app: no sequencer, no job runner, no proxy generator, no lanes
    that have ever run. Every reader must answer, and none may raise."""
    app = _app(tmp_path)
    for name in CONTRACT:
        fn = getattr(app, name, None)
        assert callable(fn), f"{name} is missing from the app contract"
    assert app.plan_fetched_at is None or isinstance(app.plan_fetched_at, str)

    assert app.trash_path() is None
    assert app.trash_summary() is None
    assert app.size_mismatch_samples() == []
    assert app.shared_folder_problems() == []
    assert app.repath_events() == []
    assert app.broll_failed_items() == []
    # The job runner is built on every machine, so these two answer for real:
    # what must never happen is a raise or a None.
    assert isinstance(app.jobs_status(), dict)
    assert set(app.jobs_gate()) >= {"taking_work", "reason"}
    assert app.stop_current_job() in (True, False)
    # Likewise the proxy generator: an all-default answer, never a raise.
    assert set(app.proxy_gaps()) == {"capped", "low_space", "truncated"}
    assert app.stills_state() == {}
    assert app.ytdl_login_progress() is None
    assert app.plan_age_seconds() is None
    assert isinstance(app.resolve_health(), dict)
    assert isinstance(app.youtube_import_state(), dict)


def test_a_producer_that_raises_costs_the_line_and_nothing_else(tmp_path):
    """The rule every one of these obeys: log it, answer empty, keep the
    window. A reader that propagated would take down the surface an editor
    opened BECAUSE something was already wrong."""
    class _Angry:
        def __getattr__(self, name):
            def _boom(*a, **kw):
                raise RuntimeError("no")
            return _boom

    app = _app(tmp_path)
    app.sequencer = _Angry()
    app.job_runner = _Angry()
    app.proxy_generator = _Angry()
    app.broll_ingestor = _Angry()
    app._lane_a = _Angry()
    app.selection_client = _Angry()

    assert app.shared_folder_problems() == []
    assert app.repath_events() == []
    assert app.jobs_status() == {}
    assert app.jobs_gate() == {}
    assert app.stop_current_job() is False
    assert app.proxy_gaps() == {}
    assert app.broll_failed_items() == []
    assert app.size_mismatch_samples() == []
    assert app.plan_fetched_at is None
    assert app.plan_age_seconds() is None


# -- APP-6 --------------------------------------------------------------------

def test_sync_now_says_what_it_will_do(tmp_path):
    app = _app(tmp_path)                       # sync_enabled = false
    answer = app.sync_now()
    assert answer["accepted"] is False
    assert "straight off the server" in answer["reason"]
    assert answer["lanes"] == []


def test_sync_now_accepts_and_names_the_lanes(tmp_path):
    class _Lane:
        name = "lane_a_video_up"
        ran = 0

        def run_once(self):
            type(self).ran += 1

    app = _app(tmp_path)
    app._sync_enabled = True
    app._managed = False
    app.lanes = [_Lane()]
    answer = app.sync_now()
    assert answer["accepted"] is True
    assert answer["lanes"] == ["lane_a_video_up"]
    assert answer["reason"] == "Checking the server for changes now."
    assert _Lane.ran == 1


def test_sync_now_says_when_nothing_is_ticked(tmp_path):
    class _Selection:
        def get(self):
            return [], "live"

    class _Sequencer:
        triggered = 0

        def trigger_pass_now(self):
            type(self).triggered += 1

    app = _app(tmp_path)
    app._sync_enabled = True
    app._managed = True
    app.sequencer = _Sequencer()
    app.selection_client = _Selection()
    answer = app.sync_now()
    assert answer["accepted"] is False
    assert "Nothing is ticked" in answer["reason"]
    assert _Sequencer.triggered == 0, "a refused click must not start a pass"


# -- SYNC-112 -----------------------------------------------------------------

def test_trash_summary_counts_the_recovery_folder_and_names_the_retention(tmp_path):
    app = _app(tmp_path)
    batch = Path(app.config["local_root"]) / ".ccsync-trash" / "20260903-141201"
    batch.mkdir(parents=True)
    (batch / "A001.mov").write_bytes(b"x" * 2048)

    assert app.trash_path() == str(Path(app.config["local_root"]) / ".ccsync-trash")
    summary = app.trash_summary()
    assert summary["count"] == 1
    assert summary["bytes"] == 2048
    # The half the editor was never told: these copies expire.
    assert summary["retention_days"] > 0


def test_trash_summary_prefers_the_lanes_own_summary_when_it_has_one(tmp_path, monkeypatch):
    """C3's `lane_guard.trash_summary(root)` is the producer when it exists;
    the walk here is the fallback for a build without it."""
    app = _app(tmp_path)
    (Path(app.config["local_root"]) / ".ccsync-trash").mkdir(parents=True)
    monkeypatch.setattr(
        app_mod.lane_guard, "trash_summary",
        lambda root: {"count": 7, "bytes": 99, "oldest": None, "retention_days": 30},
        raising=False)
    summary = app.trash_summary()
    assert summary["count"] == 7
    assert summary["path"], "the fallback path must be filled in for the button"


# -- APP-5 --------------------------------------------------------------------

def test_config_problem_detail_carries_the_sentence_not_a_bool(tmp_path):
    app = _app(tmp_path)
    assert app.config_problem_detail() is None
    app.config_problems = ["remote_root is blank -- set the absolute NAS path"]
    assert "remote_root is blank" in app.config_problem_detail()
    assert app.config_problem_details() == app.config_problems


# -- SYNC-110 -----------------------------------------------------------------

def test_plan_fetched_at_comes_from_the_selection_client(tmp_path):
    class _Selection:
        def fetched_at(self):
            return "2026-09-01T10:00:00+00:00"

        def plan_age_seconds(self):
            return 3600.0

    app = _app(tmp_path)
    app.selection_client = _Selection()
    assert app.plan_fetched_at == "2026-09-01T10:00:00+00:00"
    assert app.plan_age_seconds() == 3600.0


# -- RES-3 / RES-11 / RES-17 / RES-19 ----------------------------------------

def test_resolve_health_carries_the_new_keys(tmp_path):
    app = _app(tmp_path)
    health = app.resolve_health()
    for key in ("connected", "project_open", "wedged_seconds", "wedged_call",
                "out_of_tree", "bad_prefix", "missing", "missing_clips",
                "non_canonical_refused", "proxy_attach", "proxy_gaps",
                "stills", "last_scan_at"):
        assert key in health, f"resolve_health lost {key}"
    # "we have not looked" is not "nothing is wrong".
    assert health["connected"] is None
    assert health["last_scan_at"] is None


def test_the_proxy_attach_verdict_is_kept_and_names_the_usual_cause(tmp_path):
    app = _app(tmp_path)
    app._note_proxy_attach({"relinked": 3, "failed": 12, "failures": ["A001.mov"],
                            "message": "repointed 3 proxy link(s), 12 refused"})
    attach = app.resolve_health()["proxy_attach"]
    assert attach["attached"] == 3 and attach["failed"] == 12
    assert "A001.mov" in attach["why"] and "timecode" in attach["why"]


def test_a_clean_proxy_attach_pass_carries_no_complaint(tmp_path):
    app = _app(tmp_path)
    app._note_proxy_attach({"relinked": 2, "failed": 0, "failures": []})
    assert app.resolve_health()["proxy_attach"]["why"] == ""


def test_the_stills_instruction_is_kept(tmp_path):
    app = _app(tmp_path)
    app._note_stills({
        "status": "format-unrecognised", "changed": False,
        "message": "Resolve's preference files are not in the expected shape",
        "path": "P:\\Assets\\Stills",
    })
    stills = app.resolve_health()["stills"]
    assert stills["ok"] is False
    assert "not in the expected shape" in stills["instruction"]


def test_stills_already_pointing_at_the_shared_folder_is_ok(tmp_path):
    app = _app(tmp_path)
    app._note_stills({"status": "already-present", "changed": False,
                      "message": "", "path": ""})
    assert app.resolve_health()["stills"]["ok"] is True


def test_proxy_gaps_carries_capped_low_space_and_truncated(tmp_path):
    class _Generator:
        def coverage(self):
            return {"capped": 3, "low_space": "only 4.1 GB free on P:",
                    "truncated": True}

    app = _app(tmp_path)
    app.proxy_generator = _Generator()
    gaps = app.proxy_gaps()
    assert gaps == {"capped": 3, "low_space": "only 4.1 GB free on P:",
                    "truncated": True}


def test_proxy_gaps_defaults_when_the_generator_is_older_than_the_keys(tmp_path):
    class _Generator:
        def coverage(self):
            return {"missing": 4}

    app = _app(tmp_path)
    app.proxy_generator = _Generator()
    assert app.proxy_gaps() == {"capped": 0, "low_space": "", "truncated": False}


def test_the_missing_and_refused_lists_come_from_the_watcher(tmp_path):
    app = _app(tmp_path)
    app.watcher.rearm_non_canonical("C:\\media\\A001.mov", "A001.mov")
    health = app.resolve_health()
    assert health["non_canonical_refused"] == [
        {"name": "A001.mov", "path": "C:\\media\\A001.mov"}]
    assert health["missing_clips"] == []


# -- CYT-3 / CYT-14 / CYT-15 --------------------------------------------------

def test_youtube_import_state_carries_the_reason(tmp_path):
    class _Importer:
        def status(self):
            return {"state": "no-project-match", "reason": "no folder yet",
                    "pending": 8, "last_import_at": "2026-09-04T08:00:00+00:00"}

    app = _app(tmp_path)
    app.youtube_importer = _Importer()
    assert app.youtube_import_state() == {
        "state": "no-project-match", "reason": "no folder yet",
        "pending": 8, "at": "2026-09-04T08:00:00+00:00"}


def test_the_report_carries_youtube_import_only_when_there_is_something_to_say(tmp_path):
    class _Importer:
        answer = {"state": "idle", "reason": "", "pending": 0, "last_import_at": None}

        def status(self):
            return dict(type(self).answer)

    app = _app(tmp_path)
    app.youtube_importer = _Importer()
    assert "youtube_import" not in app.sync_guard()

    _Importer.answer = {"state": "resolve-closed", "reason": "Resolve is closed",
                        "pending": 3, "last_import_at": None}
    guard = app.sync_guard()
    assert guard["youtube_import"]["state"] == "resolve-closed"
    assert guard["youtube_import"]["pending"] == 3


def test_the_youtube_sign_in_progress_is_stored_and_cleared(tmp_path):
    app = _app(tmp_path)
    assert app.ytdl_login_progress() is None
    app.note_ytdl_login_progress("waiting for you to finish signing in", 420.0)
    progress = app.ytdl_login_progress()
    assert progress["waiting"] == "waiting for you to finish signing in"
    assert progress["seconds_left"] == 420.0
    app.note_ytdl_login_progress("")
    assert app.ytdl_login_progress() is None


def test_cancel_local_downloads_calls_the_executor(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(app_mod.ytdl_executor_mod, "cancel_all", lambda: 2,
                        raising=False)
    assert app.cancel_local_downloads() == 2


# -- SYNC-109 / SYNC-101 / SYNC-102 ------------------------------------------

def test_size_mismatch_samples_prefers_the_lanes_rich_shape(tmp_path):
    class _Lane:
        def size_mismatch_samples(self):
            return [{"path": "A001_C003.mov", "local_size": 12, "server_size": 9}]

    app = _app(tmp_path)
    app._lane_a = _Lane()
    assert app.size_mismatch_samples() == [
        {"path": "A001_C003.mov", "local_size": 12, "server_size": 9}]


def test_size_mismatch_samples_falls_back_to_the_report_a_field_build_sends(tmp_path):
    class _Lane:
        def size_mismatch_report(self):
            return {"count": 3, "samples": ["A001_C003.mov"]}

    app = _app(tmp_path)
    app._lane_a = _Lane()
    assert app.size_mismatch_samples() == [
        {"path": "A001_C003.mov", "local_size": None, "server_size": None}]


def test_shared_folders_and_repaths_come_from_the_sequencer(tmp_path):
    class _Sequencer:
        def shared_folder_problems(self):
            return ["The LUT library is not shared with this computer yet."]

        def repath_events(self):
            return [{"old": "2026/FF5/Animals", "new": "2026/FF5/Wildlife",
                     "at": "2026-09-04T08:00:00+00:00", "relinked": True}]

    app = _app(tmp_path)
    app.sequencer = _Sequencer()
    assert app.shared_folder_problems() == [
        "The LUT library is not shared with this computer yet."]
    assert app.repath_events()[0]["new"] == "2026/FF5/Wildlife"


# -- CMEDIA-2 / 10 / 12 / 13 --------------------------------------------------

def test_broll_failed_items_carries_the_reason_not_a_count(tmp_path):
    class _Ingestor:
        def progress(self):
            return {"failed_items": [
                {"name": "A001.mov", "error": "the source file is not on this "
                                              "machine any more"}]}

    app = _app(tmp_path)
    app.broll_ingestor = _Ingestor()
    assert app.broll_failed_items() == [
        {"name": "A001.mov",
         "error": "the source file is not on this machine any more"}]


def test_the_jobs_gate_is_the_machines_own_verdict(tmp_path):
    class _Runner:
        state = "user_active"
        stopped = 0

        def status(self):
            return {"state": type(self).state, "job": None}

        def stop_current(self):
            type(self).stopped += 1
            return True

    app = _app(tmp_path)
    app.job_runner = _Runner()
    # `detail` rides beside the state code since CMEDIA-1: for `local_work`
    # it is the whole content of the answer (WHICH work of the editor's own),
    # and "" for a runner that offered no sentence.
    assert app.jobs_gate() == {"taking_work": False, "reason": "user_active",
                               "detail": ""}
    # An empty queue is an OPEN gate: reading it as a refusal is exactly the
    # confusion `GET /api/v1/jobs/<id>/why` exists to end.
    _Runner.state = "nothing_offered"
    assert app.jobs_gate()["taking_work"] is True
    assert app.stop_current_job() is True
    assert _Runner.stopped == 1


def test_the_capabilities_section_carries_the_gate(tmp_path):
    class _Runner:
        def status(self):
            return {"state": "resolve_open"}

    app = _app(tmp_path)
    app.job_runner = _Runner()
    section = app.job_capabilities()
    assert section["jobs_gate"] == {"taking_work": False, "reason": "resolve_open"}


# -- RES-13 / APP-8 / APP-9 / CR-120 -----------------------------------------

def test_undo_last_fix_reports_availability_and_delegates(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(resolve_journal, "describe_latest", lambda *a, **kw: "",
                        raising=False)
    assert app.undo_last_fix_available() is False

    monkeypatch.setattr(resolve_journal, "describe_latest",
                        lambda *a, **kw: '158 clip path(s) in "FF4 ROUGH", 14:22',
                        raising=False)
    assert app.undo_last_fix_available() is True
    assert "158 clip path(s)" in app.undo_last_fix_summary()

    called = []
    monkeypatch.setattr(app, "undo_last_relink", lambda: called.append(1))
    app.undo_last_fix()
    assert called == [1], "undo_last_fix is the alias, never a second undo"


def test_open_licence_dialog_forces_the_offer(tmp_path, monkeypatch):
    app = _app(tmp_path)
    seen = []
    monkeypatch.setattr(app, "prompt_licence_acceptance",
                        lambda force=False: seen.append(force))
    app.open_licence_dialog()
    assert seen == [True], "an editor asking again must not be eaten by the latch"


def test_sign_in_again_opens_the_existing_dialog(tmp_path, monkeypatch):
    from ccsync_companion import tray as tray_mod

    app = _app(tmp_path)
    seen = []
    monkeypatch.setattr(tray_mod, "_show_sign_in_dialog", lambda a: seen.append(a),
                        raising=False)
    app.sign_in_again()
    assert seen == [app]


def test_restart_self_is_the_alias_and_refuses_over_live_work(tmp_path, monkeypatch):
    app = _app(tmp_path)
    calls = []
    monkeypatch.setattr(upgrade_mod, "restart_self",
                        lambda request_shutdown: calls.append(request_shutdown) or True)

    monkeypatch.setattr(app, "_standing_down_would_kill_work",
                        lambda: "a CCSync window is open")
    assert app.restart_self() is False
    assert calls == [], "nothing restarts over a window or a copy in flight"

    monkeypatch.setattr(app, "_standing_down_would_kill_work", lambda: "")
    assert app.restart_self() is True
    assert calls == [app.shutdown]


# -- SYNC-120 -----------------------------------------------------------------

def test_a_wedged_drive_starts_a_reminder_episode(tmp_path, monkeypatch):
    """CR-92's reminders were gated on work having been owed at the moment the
    drive went, so a drive that WEDGES while the machine is up to date got one
    balloon and then silence, indefinitely -- the harder of the two failures,
    because a wedged drive looks fine."""
    app = _app(tmp_path)
    monkeypatch.setattr(app, "_unfinished_before_pause", lambda: None)
    monkeypatch.setattr(app, "_root_pause_lanes", lambda: None)
    monkeypatch.setattr(app, "_notify_tray", lambda *a, **kw: None)

    app._on_root_absent(app_mod.root_guard_mod.ROOT_NOT_ANSWERING)
    assert app._drive_reminder.active is True
    assert app._drive_reminder.remind_now() is True
    # ...and NOT as "still to go": nothing is owed, so the tray line is
    # unchanged.
    assert app.drive_unfinished_summary() == ""


def test_a_drive_that_is_then_unplugged_with_nothing_owed_stops_reminding(tmp_path,
                                                                         monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(app, "_unfinished_before_pause", lambda: None)
    monkeypatch.setattr(app, "_root_pause_lanes", lambda: None)
    monkeypatch.setattr(app, "_notify_tray", lambda *a, **kw: None)

    app._on_root_absent(app_mod.root_guard_mod.ROOT_NOT_ANSWERING)
    assert app._drive_reminder.active is True
    app._on_root_absent(app_mod.root_guard_mod.ROOT_ABSENT)
    assert app._drive_reminder.active is False


def test_the_jobs_block_reason_is_the_editors_own_work(tmp_path):
    """CMEDIA-1: the seam the proxy generator and the two ingestors already
    negotiate this machine's GPU over, extended to fleet work. Never the
    config gate `_proxy_block_reason` answers True for: a half-configured
    sync tree is not a reason to refuse a transcription, and True with no
    words would be a refusal nobody could explain."""
    app = _app(tmp_path)

    class _Ingestor:
        def __init__(self, reason=None):
            self.reason = reason

        def blocking_reason(self):
            return self.reason

    class _Generator:
        def __init__(self, encoding):
            self._encoding = encoding

        def gap(self):
            return {"encoding": self._encoding}

    app.broll_ingestor = _Ingestor()
    app.music_ingestor = _Ingestor()
    app.proxy_generator = _Generator(False)
    app.config_problems = ["local_root is not set"]
    assert app._jobs_block_reason() is False

    app.proxy_generator = _Generator(True)
    assert app._jobs_block_reason() == "waiting: making proxies"

    app.music_ingestor = _Ingestor("indexing music first")
    assert app._jobs_block_reason() == "indexing music first"

    app.broll_ingestor = _Ingestor("indexing b-roll first")
    assert app._jobs_block_reason() == "indexing b-roll first"

    # An ingestor that raises is not an answer, and must not be the reason a
    # machine takes no work forever: the next source is asked.
    class _Broken:
        def blocking_reason(self):
            raise RuntimeError("wedged")

    app.broll_ingestor = _Broken()
    assert app._jobs_block_reason() == "indexing music first"
