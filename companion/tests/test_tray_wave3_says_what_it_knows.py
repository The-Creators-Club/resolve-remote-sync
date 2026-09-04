"""Wave 3 of the usability + resilience sweep 2026-09-03: "the machine says
what it knows".

Every fact here was already computed somewhere on the editor's own computer
and rendered nowhere they would ever look: the file lane A will never upload
(SYNC-109), where the recovery copies are (SYNC-112), a Resolve call that has
been wedged for twenty minutes (RES-22), the dead-link counts (RES-5), a
running YouTube download (CYT-1) and the way to stop it (CYT-14), the browser
sign-in waiting on a person (CYT-15), why a b-roll clip failed (CMEDIA-10), a
fleet job an admin forced onto this machine (CMEDIA-13), which setting is not
set up (APP-5), whether "Sync now" did anything (APP-6), a credential the
server has revoked (APP-8), how to restart (APP-13), why "Open my sync drive"
did nothing (APP-14) and how old the sync plan is (SYNC-110).

The app getters this consumes are C2's (app.py); every one is stubbed here and
read through getattr on the tray side, so a companion without them renders one
line fewer rather than raising.
"""

from __future__ import annotations

import time

import pytest

from ccsync_companion.sync.base import LaneStatus


def _status(name="a", state="idle", **kw):
    return LaneStatus(name=name, state=state, **kw)


class _FakeIdentity:
    def __init__(self, username="alex"):
        self._username = username

    def valid(self):
        return self._username is not None

    @property
    def username(self):
        return self._username


class _FakeApp:
    """The tray's whole view of an app, plus the wave-3 getters."""

    def __init__(self, config=None, identity=None, **attrs):
        self.config = dict(config or {"dashboard_url": ""})
        self.log_path = "x.log"
        self.identity = identity if identity is not None else _FakeIdentity()
        self.config_problems: list[str] = []
        self._require_login = True
        self._sync_enabled = True
        self.notices: list[str] = []
        self.paused = False
        for key, value in attrs.items():
            setattr(self, key, value)

    def lane_statuses(self):
        return [_status()]

    def is_paused(self):
        return self.paused

    def _notify_tray(self, msg, title=""):
        self.notices.append(msg)


@pytest.fixture()
def tray(monkeypatch):
    """The tray module with _spawn made synchronous, so an action's balloon
    has happened by the time the test looks. Every action goes through
    _spawn (the tray's message loop is the one thread nothing may block),
    which makes it the seam."""
    from ccsync_companion import tray as tray_mod

    monkeypatch.setattr(tray_mod, "_spawn", lambda app, label, fn: fn())
    return tray_mod


@pytest.fixture()
def opened(monkeypatch):
    """What the platform opener was asked to open."""
    from ccsync_companion import tray as tray_mod

    seen: list[str] = []
    monkeypatch.setattr(tray_mod, "_open_log", lambda path: seen.append(str(path)))
    return seen


def _labels(menu):
    return [str(item.text) for item in menu.items]


def _snap(**over):
    base = {"problems": False, "signed_in": True, "paused": False,
            "statuses": [], "sync_guard": {}}
    base.update(over)
    return base


# -- SYNC-109: the file that will not upload -------------------------------


def test_the_skipped_line_names_the_file_and_both_sizes():
    from ccsync_companion.tray import _skipped_exists_line

    guard = {"skipped_exists": {"count": 3, "samples": [
        {"path": "2026/CCT/old.mov", "local_size": 1, "server_size": 2,
         "at": "2026-09-01T10:00:00Z"},
        {"path": "2026/CCT/A001_C003.mov", "local_size": 4_200_000_000,
         "server_size": 3_100_000_000, "at": "2026-09-03T10:00:00Z"},
    ]}}
    line = _skipped_exists_line(guard)
    # The NEWEST, where the lane recorded a time -- not whichever rclone
    # happened to list first.
    assert "A001_C003.mov" in line and "old.mov" not in line
    assert "yours 3.9 GB" in line and "the server's 2.9 GB" in line
    assert "Rename yours" in line
    # No em dash anywhere an editor reads (owner's rule, 2026-08-18).
    assert "—" not in line


def test_the_skipped_line_survives_the_old_plain_string_samples():
    """Every build before this sweep put `rclone check --differ`'s raw
    relative paths in `samples`. The line names the file; it just cannot name
    two sizes nobody recorded."""
    from ccsync_companion.tray import _skipped_exists_line

    line = _skipped_exists_line(
        {"skipped_exists": {"count": 1, "samples": ["2026/CCT/A001.mov"]}})
    assert "(e.g. A001.mov)" in line and "yours " not in line


def test_the_skipped_line_is_silent_at_zero():
    from ccsync_companion.tray import _skipped_exists_line

    assert _skipped_exists_line({}) is None
    assert _skipped_exists_line({"skipped_exists": {"count": 0}}) is None


def test_the_tooltip_lists_up_to_three_skipped_files():
    from ccsync_companion.tray import _tooltip_text

    tip = _tooltip_text(_snap(sync_guard={"skipped_exists": {
        "count": 9, "samples": [f"2026/CCT/A00{n}.mov" for n in range(1, 6)]}}))
    assert "A001.mov" in tip and "A003.mov" in tip
    assert "A004.mov" not in tip
    assert len(tip) <= 127


def test_open_the_folder_the_skipped_file_is_in(tray, opened, tmp_path):
    (tmp_path / "2026" / "CCT").mkdir(parents=True)
    app = _FakeApp({"local_root": str(tmp_path)})
    tray.action_open_skipped_folder(app, {"sync_guard": {
        "skipped_exists": {"count": 1, "samples": ["2026/CCT/A001.mov"]}}})
    assert opened == [str(tmp_path / "2026" / "CCT")]


def test_open_the_skipped_folder_says_why_with_no_root(tray):
    app = _FakeApp({"local_root": ""})
    tray.action_open_skipped_folder(app, {"sync_guard": {
        "skipped_exists": {"count": 1, "samples": ["2026/CCT/A001.mov"]}}})
    assert app.notices and "does not know where your sync folder is" in app.notices[0]


# -- SYNC-112: the recovery folder -----------------------------------------


def test_the_trash_line_names_the_folder_the_count_and_the_retention():
    from ccsync_companion.tray import _trash_line

    line = _trash_line({"trash": {"bytes": 13_000_000_000, "count": 318,
                                  "path": "/vol/tree/.ccsync-trash",
                                  "max_age_days": 30}})
    assert "/vol/tree/.ccsync-trash" in line
    assert "318 files" in line and "12.1 GB" in line
    assert "older than 30 days are removed automatically" in line


def test_the_trash_line_falls_back_to_the_folder_name_and_the_default():
    from ccsync_companion.tray import _trash_line

    line = _trash_line({"trash": {"bytes": 2 << 30, "count": 4}})
    assert ".ccsync-trash" in line and "14 days" in line


def test_the_trash_line_is_silent_below_a_gigabyte():
    from ccsync_companion.tray import _trash_line

    assert _trash_line({"trash": {"bytes": 5_000_000, "count": 2}}) is None


def test_open_the_recovery_folder(tray, opened, tmp_path):
    trash = tmp_path / ".ccsync-trash"
    trash.mkdir()
    tray.action_open_trash(_FakeApp({"local_root": str(tmp_path)}))
    assert opened == [str(trash)]


def test_open_the_recovery_folder_prefers_the_apps_own_path(tray, opened, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    app = _FakeApp({"local_root": str(tmp_path)}, trash_path=lambda: str(elsewhere))
    tray.action_open_trash(app)
    assert opened == [str(elsewhere)]


def test_open_the_recovery_folder_says_why_when_it_cannot(tray, opened, tmp_path):
    gone = tmp_path / "not-here"
    app = _FakeApp({"local_root": str(gone)})
    tray.action_open_trash(app)
    assert opened == []
    assert app.notices and str(gone / ".ccsync-trash") in app.notices[0]


def test_open_the_recovery_folder_says_why_with_no_root_at_all(tray):
    app = _FakeApp({"local_root": ""})
    tray.action_open_trash(app)
    assert app.notices and "does not know where your sync folder is" in app.notices[0]


# -- RES-22 / RES-5: what Resolve is doing ---------------------------------


def test_a_wedged_call_is_never_connected():
    from ccsync_companion.tray import resolve_bridge_line

    line = resolve_bridge_line({"connected": True, "ever_connected": True},
                               health={"wedged_seconds": 1200,
                                       "wedged_call": "ImportMedia"})
    assert line == "Resolve: not answering for 1200 s (ImportMedia)"


def test_a_short_call_is_still_connected():
    from ccsync_companion.tray import resolve_bridge_line

    assert resolve_bridge_line({"connected": True},
                               health={"wedged_seconds": 3}) == "Resolve: connected"


def test_the_wedge_falls_back_to_the_bridges_own_record():
    from ccsync_companion.tray import resolve_wedge

    assert resolve_wedge({}, {"call": "GetMediaPool", "seconds": 90.0}) == {
        "seconds": 90.0, "call": "GetMediaPool"}
    assert resolve_wedge({}, {"call": "GetMediaPool", "seconds": 2.0}) == {}
    assert resolve_wedge(None, None) == {}


def test_a_wedged_bridge_is_amber_not_green():
    from ccsync_companion.tray import compute_overall_color

    assert compute_overall_color([], None, None) == "green"
    assert compute_overall_color([], None, None, resolve_wedged=True) == "orange"


def test_the_snapshot_colours_amber_while_a_call_is_wedged():
    from ccsync_companion import tray as tray_mod

    app = _FakeApp(resolve_health=lambda: {"wedged_seconds": 300,
                                           "wedged_call": "ImportMedia"},
                   resolve_bridge_state=lambda: {"connected": True,
                                                 "ever_connected": True})
    snap = tray_mod._tray_snapshot(app)
    assert snap["color"] == "orange"
    assert snap["resolve_line"] == "Resolve: not answering for 300 s (ImportMedia)"


def test_the_resolve_line_carries_the_counts_that_are_not_zero():
    from ccsync_companion.tray import resolve_bridge_line

    line = resolve_bridge_line({"connected": True},
                               health={"out_of_tree": 3, "missing": 2,
                                       "bad_prefix": 0})
    assert line == "Resolve: connected - 3 clips outside the tree, 2 missing"


def test_the_resolve_line_shows_two_counts_and_the_tooltip_the_rest():
    from ccsync_companion.tray import _tooltip_text, resolve_bridge_line

    health = {"out_of_tree": 3, "missing": 2, "bad_prefix": 4,
              "proxy_attach": {"failed": 12}}
    line = resolve_bridge_line({"connected": True}, health=health)
    assert line.count(",") == 1
    tip = _tooltip_text(_snap(resolve_health=health))
    assert "4 on the wrong drive" in tip and "12 proxies not attached" in tip


def test_no_counts_leaves_the_line_and_the_tooltip_as_they_were():
    from ccsync_companion.tray import _tooltip_text, resolve_bridge_line

    assert resolve_bridge_line({"connected": True}, health={}) == "Resolve: connected"
    assert _tooltip_text(_snap(resolve_health={})) == "CCSync: up to date"


# -- CYT-1 / CYT-14: the local YouTube download ----------------------------


def _downloading_app(**attrs):
    return _FakeApp(ytdl_progress=lambda: {"running": True, "total": 12,
                                           "done": 2, "failed": 0,
                                           "speed_bps": 4_200_000,
                                           "bytes_done": 38, "bytes_total": 100},
                    **attrs)


def test_a_running_download_is_a_tray_line_and_a_tooltip_entry():
    from ccsync_companion import tray as tray_mod

    app = _downloading_app()
    snap = tray_mod._tray_snapshot(app)
    assert snap["ytdl_line"] == "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)"
    assert snap["ytdl_line"] in _labels(tray_mod._build_menu(app, snap))
    assert tray_mod._tooltip_text(snap) == (
        "CCSync: downloading YouTube clip 3/12 (4.2 MB/s, 38%)")


def test_the_download_line_goes_away_when_it_ends():
    from ccsync_companion import tray as tray_mod

    app = _FakeApp(ytdl_progress=lambda: {"running": False})
    snap = tray_mod._tray_snapshot(app)
    assert snap["ytdl_line"] is None
    assert not any("YouTube" in label for label in _labels(
        tray_mod._build_menu(app, snap)))
    assert tray_mod._tooltip_text(snap) == "CCSync: up to date"


def test_the_stop_item_exists_only_while_a_download_runs():
    from ccsync_companion import tray as tray_mod

    app = _downloading_app()
    assert "► Stop the YouTube download" in _labels(
        tray_mod._build_menu(app, tray_mod._tray_snapshot(app)))
    idle = _FakeApp(ytdl_progress=lambda: {"running": False})
    assert "► Stop the YouTube download" not in _labels(
        tray_mod._build_menu(idle, tray_mod._tray_snapshot(idle)))


def test_stopping_the_download_hands_it_back_and_says_so(tray):
    stopped: list[int] = []
    app = _downloading_app(cancel_local_downloads=lambda: stopped.append(1) or 3)
    tray.action_stop_youtube_download(app)
    assert stopped == [1]
    assert app.notices == ["Stopped. The server will download the clips this "
                           "computer did not finish."]


def test_a_failed_stop_says_so_instead_of_claiming_success(tray):
    def _boom():
        raise RuntimeError("no")

    app = _downloading_app(cancel_local_downloads=_boom)
    tray.action_stop_youtube_download(app)
    assert app.notices and "could not stop" in app.notices[0]


def test_the_download_moves_the_menu_fingerprint_per_clip_not_per_tick():
    """The line carries a speed and a percentage that move every tick, and
    rebuilding the menu under an editor's cursor twice a second is what
    _progress_bucket exists to avoid."""
    from ccsync_companion.tray import _ytdl_menu_key

    assert _ytdl_menu_key("Downloading YouTube clip 3/12 (4.2 MB/s, 38%)") == \
        _ytdl_menu_key("Downloading YouTube clip 3/12 (1.1 MB/s, 61%)")
    assert _ytdl_menu_key("Downloading YouTube clip 3/12 (4.2 MB/s)") != \
        _ytdl_menu_key("Downloading YouTube clip 4/12 (4.2 MB/s)")


# -- CYT-15: the browser sign-in -------------------------------------------


def test_the_sign_in_line_counts_down():
    from ccsync_companion.tray import ytdl_login_line

    assert ytdl_login_line(None) is None
    assert ytdl_login_line({"waiting": False}) is None
    assert ytdl_login_line({"waiting": True, "seconds_left": 240.4}) == (
        "Waiting for you to finish signing in in the browser (240 s left)")
    assert ytdl_login_line({"waiting": True, "seconds_left": None}) == (
        "Waiting for you to finish signing in in the browser")


def test_the_login_progress_callback_takes_both_shapes():
    from ccsync_companion import tray as tray_mod

    try:
        tray_mod._login_progress(60.0, 540.0, "waiting")
        assert tray_mod.ytdl_login_line(tray_mod._YTDL_LOGIN).endswith("(540 s left)")
        tray_mod._login_progress("Edge is opening. Sign in to YouTube")
        assert tray_mod._YTDL_LOGIN["waiting"] is True
    finally:
        tray_mod._clear_ytdl_login()
    assert tray_mod._YTDL_LOGIN is None


def test_the_sign_in_passes_progress_and_the_line_reaches_the_menu(tray, monkeypatch):
    from ccsync_companion import ytdl_browser_login

    seen: dict = {}

    class _Browser:
        name = "Edge"

    def _run(*, browser, progress=None, **kw):
        progress(30.0, 570.0, "waiting")
        seen["line"] = tray.ytdl_login_line(tray._YTDL_LOGIN)
        return ytdl_browser_login.Outcome(True, "signed in", cookies_written=4)

    app = _FakeApp()
    tray._youtube_sign_in(app, runner=_run, finder=lambda: _Browser())
    assert seen["line"] == (
        "Waiting for you to finish signing in in the browser (570 s left)")
    # ...and the line is gone once the flow ends, whichever way it ended.
    assert tray._YTDL_LOGIN is None


def test_a_timed_out_sign_in_says_what_to_do_next(tray):
    from ccsync_companion import ytdl_browser_login

    class _Browser:
        name = "Edge"

    app = _FakeApp()
    tray._youtube_sign_in(
        app,
        runner=lambda **kw: ytdl_browser_login.Outcome(
            False, "the sign-in did not finish in time - nothing saved; try again"),
        finder=lambda: _Browser())
    assert "try again from" in app.notices[-1]
    assert "did not finish in time" in app.notices[-1]


def test_the_sign_in_survives_a_login_module_without_the_progress_seam(tray):
    from ccsync_companion import ytdl_browser_login

    class _Browser:
        name = "Edge"

    def _run(*, browser):  # no `progress` keyword at all
        return ytdl_browser_login.Outcome(True, "signed in", cookies_written=1)

    app = _FakeApp()
    tray._youtube_sign_in(app, runner=_run, finder=lambda: _Browser())
    assert app.notices[-1] == "signed in"


# -- CMEDIA-10 / CMEDIA-13: indexing and fleet work ------------------------


def test_a_failed_clip_names_itself_and_its_reason():
    from ccsync_companion.tray import _ingest_lines

    lines = _ingest_lines({"total": 40, "done": 37, "failed": 3, "gate": "idle"},
                          failures=[{"name": "A001_C003.mov",
                                     "error": "the source file is not on this "
                                              "machine any more"}])
    assert lines == ["3 b-roll clip(s) could not be indexed: A001_C003.mov "
                     "(the source file is not on this machine any more), and 2 more"]


def test_one_failure_says_no_and_n_more():
    from ccsync_companion.tray import _ingest_lines

    lines = _ingest_lines({"total": 4, "done": 3, "failed": 1},
                          failures=[{"name": "b.mov", "error": "a tier refusal"}])
    assert lines == ["1 b-roll clip(s) could not be indexed: b.mov (a tier refusal)"]


def test_without_the_reasons_the_old_sentence_stands():
    from ccsync_companion.tray import _ingest_lines

    assert _ingest_lines({"total": 4, "done": 3, "failed": 1}) == [
        "1 b-roll clip(s) could not be indexed. See the log"]


def test_the_failure_line_reaches_the_menu():
    from ccsync_companion import tray as tray_mod

    app = _FakeApp(
        broll_ingest_view=lambda: {"total": 40, "done": 37, "failed": 3},
        broll_failed_items=lambda: [{"name": "A001.mov", "error": "no such file"}])
    labels = _labels(tray_mod._build_menu(app, tray_mod._tray_snapshot(app)))
    assert any("could not be indexed: A001.mov (no such file)" in label
               for label in labels)


def test_a_forced_job_says_who_asked_for_it():
    from ccsync_companion.tray import jobs_forced_line

    assert jobs_forced_line(None) is None
    assert jobs_forced_line({"current": {"kind": "whisper"}}) is None
    assert jobs_forced_line({"current": {
        "kind": "whisper",
        "forced_reason": "your admin asked for it now"}}) == (
        "CCSync is transcribing for the fleet while you work because your admin "
        "asked for it now")
    assert jobs_forced_line({"current": {
        "kind": "proxy-480p", "forced_reason": "the queue was empty"}}).startswith(
        "CCSync is transcoding for the fleet")


def test_the_forced_job_line_reaches_the_menu():
    from ccsync_companion import tray as tray_mod

    app = _FakeApp(jobs_status=lambda: {"current": {
        "kind": "peaks", "forced_reason": "your admin asked for it now"}})
    labels = _labels(tray_mod._build_menu(app, tray_mod._tray_snapshot(app)))
    assert any(label.startswith("CCSync is transcoding for the fleet")
               for label in labels)


# -- APP-5 / SYNC-110: the lane lines --------------------------------------


def test_the_lane_line_names_the_setting_that_is_not_set_up():
    from ccsync_companion.tray import _format_lane_line_from

    detail = ("NOT SYNCING: this machine isn't fully set up -- remote_root is "
              "blank, so rclone would target the remote's default directory")
    line = _format_lane_line_from(_status("lane_a_video_up", detail=detail),
                                  paused=False, problems=True)
    assert line.startswith("Uploads (your footage")
    assert "remote_root is blank" in line
    assert "isn't set up yet" not in line


def test_the_lane_line_takes_the_sentence_from_the_app_when_it_has_one():
    from ccsync_companion.tray import _format_lane_line_from

    line = _format_lane_line_from(_status("lane_a_video_up"), paused=False,
                                  problems=True,
                                  problem_detail="editor_name is blank")
    assert line.endswith("NOT SYNCING: editor_name is blank")


def test_a_config_problem_nobody_wrote_down_keeps_the_old_sentence():
    from ccsync_companion.tray import _format_lane_line_from

    line = _format_lane_line_from(_status("lane_a_video_up"), paused=False,
                                  problems=True)
    assert "this machine isn't set up yet" in line


def test_the_named_problem_is_capped_so_a_menu_stays_readable():
    from ccsync_companion.tray import _named_config_problem

    assert len(_named_config_problem("", "x" * 400)) <= 180


def test_a_lane_on_a_day_old_plan_says_so():
    from ccsync_companion.tray import _format_lane_line_from

    line = _format_lane_line_from(_status("lane_a_video_up"), paused=False,
                                  problems=False,
                                  plan_age_seconds=3 * 86400 + 10)
    assert line == ("Uploads (your footage → server): up to date (sync plan "
                    "from 3 days ago: the dashboard has not answered since)")


def test_a_fresh_or_unknown_plan_age_says_nothing():
    from ccsync_companion.tray import _format_lane_line_from

    for age in (None, 0, 3600, "junk"):
        line = _format_lane_line_from(_status("lane_a_video_up"), paused=False,
                                      problems=False, plan_age_seconds=age)
        assert "sync plan from" not in line


def test_the_snapshot_reads_the_plan_age_off_the_app():
    from ccsync_companion import tray as tray_mod

    app = _FakeApp(plan_fetched_at=time.time() - 2 * 86400)
    age = tray_mod._tray_snapshot(app)["plan_age_seconds"]
    assert age is not None and age > 86400


# -- APP-6 / APP-8 / APP-13 / APP-14: the actions --------------------------


def test_sync_now_says_what_it_started(tray):
    app = _FakeApp(sync_now=lambda: {"accepted": True,
                                     "lanes": ["originals up", "proxies down"]})
    tray.action_sync_now(app)
    assert app.notices == ["Sync requested: originals up, proxies down"]


def test_sync_now_says_why_it_did_not(tray):
    app = _FakeApp(sync_now=lambda: {
        "accepted": False,
        "reason": "this computer works straight off the server, so there is "
                  "nothing to sync"})
    tray.action_sync_now(app)
    assert app.notices[0].startswith("Not now: this computer works straight off")


def test_sync_now_on_an_older_companion_stays_silent(tray):
    app = _FakeApp(sync_now=lambda: None)
    tray.action_sync_now(app)
    assert app.notices == []


def test_a_rejected_credential_offers_the_way_back_in():
    from ccsync_companion import tray as tray_mod

    guard = {"reporter": {"consecutive_failures": 12, "last_status": "HTTP 401"}}
    app = _FakeApp(sync_guard=lambda: guard)
    snap = tray_mod._tray_snapshot(app)
    assert snap["signed_in"] is True and snap["credential_rejected"] is True
    labels = _labels(tray_mod._build_menu(app, snap))
    assert "► Sign in again (the server rejected this computer's sign-in)" \
        in labels
    line = tray_mod._reporter_line(guard)
    assert line.startswith("⚠ The server rejected this computer's sign-in")


def test_a_healthy_reporter_offers_no_second_sign_in():
    from ccsync_companion import tray as tray_mod

    app = _FakeApp(sync_guard=lambda: {"reporter": {"consecutive_failures": 0}})
    snap = tray_mod._tray_snapshot(app)
    assert snap["credential_rejected"] is False
    assert not any("Sign in again" in label for label
                   in _labels(tray_mod._build_menu(app, snap)))


def test_a_server_error_that_is_not_a_refusal_is_not_a_sign_in_prompt():
    from ccsync_companion.tray import credential_rejected

    assert credential_rejected({"reporter": {"consecutive_failures": 40,
                                             "last_status": "HTTP 502"}}) is False


def test_restart_is_always_offered_and_runs_the_one_restart(tray, monkeypatch):
    from ccsync_companion import settings_window

    called: list[str] = []
    monkeypatch.setattr(settings_window, "action_restart_now",
                        lambda app: called.append("restart"))
    app = _FakeApp()
    labels = _labels(tray._build_menu(app))
    assert "Restart CCSync" in labels
    tray._build_menu(app)  # the item is built at right-click time, every time
    tray.action_restart_app(app)
    assert called == ["restart"]


def test_open_my_sync_drive_says_why_when_there_is_no_drive(tray, opened):
    app = _FakeApp({"local_root": ""})
    tray.action_open_sync_drive(app)
    assert opened == []
    assert app.notices == ["This computer has no sync drive set up yet: open "
                           "Settings, THIS COMPUTER."]


def test_open_my_sync_drive_says_why_when_the_drive_is_gone(tray, opened, tmp_path):
    gone = tmp_path / "unplugged"
    app = _FakeApp({"local_root": str(gone)})
    tray.action_open_sync_drive(app)
    assert opened == []
    assert app.notices and str(gone) in app.notices[0]
    assert "plug it back in" in app.notices[0].lower()


def test_open_my_sync_drive_still_opens_a_drive_that_is_there(tray, opened, tmp_path):
    tray.action_open_sync_drive(_FakeApp({"local_root": str(tmp_path)}))
    assert opened == [str(tmp_path)]


# -- the whole snapshot stays cheap and safe -------------------------------


def test_every_new_getter_may_be_absent_or_broken():
    """A companion whose app has none of C2's getters renders one line fewer,
    and one that raises from all of them still gets a snapshot: _tray_snapshot
    wraps every read, because the render path is where nothing may fail."""
    from ccsync_companion import tray as tray_mod

    def _boom():
        raise RuntimeError("nope")

    bare = tray_mod._tray_snapshot(_FakeApp())
    broken = tray_mod._tray_snapshot(_FakeApp(
        resolve_health=_boom, size_mismatch_samples=_boom, jobs_status=_boom,
        broll_failed_items=_boom, plan_fetched_at=_boom,
        config_problem_detail=_boom, ytdl_login_progress=_boom))
    for snap in (bare, broken):
        assert snap["color"] == "green"
        assert snap["skipped_samples"] == []
        assert snap["broll_failures"] == []
        assert snap["jobs_status"] == {}
        assert snap["plan_age_seconds"] is None
        assert snap["problem_detail"] == ""
        assert tray_mod._tooltip_text(snap) == "CCSync: up to date"
        _labels(tray_mod._build_menu(_FakeApp(), snap))


def test_no_em_dash_in_anything_this_wave_renders():
    """Owner's rule, 2026-08-18. Every string an editor reads here."""
    from ccsync_companion import tray as tray_mod

    app = _downloading_app(
        broll_ingest_view=lambda: {"total": 3, "done": 1, "failed": 2},
        broll_failed_items=lambda: [{"name": "a.mov", "error": "no such file"}],
        jobs_status=lambda: {"current": {"kind": "whisper",
                                         "forced_reason": "an admin asked"}},
        resolve_health=lambda: {"out_of_tree": 3, "missing": 2, "bad_prefix": 1},
        resolve_bridge_state=lambda: {"connected": True, "ever_connected": True},
        sync_guard=lambda: {"trash": {"bytes": 2 << 30, "count": 9},
                            "skipped_exists": {"count": 2,
                                               "samples": ["a/b.mov"]},
                            "reporter": {"consecutive_failures": 12,
                                         "last_status": "HTTP 403"}})
    snap = tray_mod._tray_snapshot(app)
    texts = [*_labels(tray_mod._build_menu(app, snap)),
             tray_mod._tooltip_text(snap),
             tray_mod._trash_line(snap["sync_guard"]) or "",
             tray_mod._skipped_exists_line(snap["sync_guard"]) or "",
             tray_mod._reporter_line(snap["sync_guard"]) or ""]
    assert not [text for text in texts if "—" in text]
