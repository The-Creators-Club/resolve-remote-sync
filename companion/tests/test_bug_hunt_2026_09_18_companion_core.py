"""The ninth fleet hunt's companion-core mediums and lows (2026-09-18, CR-283).

One section per finding, in the fix pass's letter order, each test named for
the behaviour it pins with the finding id in its docstring. Nothing here
touches Resolve, Explorer, the network or a real Tk root: every seam used is
one the product already injects.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from ccsync_companion.sync.syncthing_lane import SyncthingLane


# -- comp-sync-2 / comp-sync-6: the path-missing heal -------------------------


def _path_missing_lane(tmp_path, folders, posts, expected_folder_ids):
    """A lane whose Syncthing answers `folders` and records every POST.

    Shaped like `test_syncthing_lane._path_missing_lane`, but the folder list
    is the caller's, so a machine whose SELECTION names none of them can be
    built (comp-sync-2).
    """
    cfg_xml = tmp_path / "config.xml"
    cfg_xml.write_text(
        "<configuration><gui><apikey>k</apikey></gui></configuration>", encoding="utf-8")

    def http_get(url, api_key, timeout):
        if url.endswith("/rest/config"):
            return {"folders": folders}
        if "/rest/db/status" in url:
            return {"state": "error", "error": "folder path missing"}
        if url.endswith("/rest/system/status"):
            return {"myID": "ME"}
        return {}

    def http_post(url, api_key, timeout):
        posts.append(url)
        return {}

    return SyncthingLane(api_key="k", config_xml_path=cfg_xml, http_get=http_get,
                         http_post=http_post, expected_folder_ids=expected_folder_ids)


def test_the_heal_runs_on_a_machine_whose_selection_names_no_project(tmp_path):
    """comp-sync-2: an editor between projects, whose only path-missing folder
    is a shared asset library, is the machine CR-278's docstring was written
    for - and was the one machine the early return made the heal unreachable
    on."""
    root = tmp_path / "Luts"
    (root / ".stfolder").mkdir(parents=True)
    folders = [{"id": "assets-luts", "path": str(root), "paused": False,
                "devices": [{"deviceID": "ME"}, {"deviceID": "NAS"}]}]
    posts: list = []
    lane = _path_missing_lane(tmp_path, folders, posts, expected_folder_ids=[])

    status = lane.check_once()

    assert len(posts) == 1
    assert posts[0].endswith("/rest/db/scan?folder=assets-luts")
    # And the no-selection verdict is untouched: nothing was checked, so
    # nothing is claimed.
    assert "no project folders to check yet" in (status.detail or "")


def test_a_config_read_that_fails_still_answers_no_project_folders(tmp_path):
    """comp-sync-2: the heal's config read moved above the no-selection
    return, so a Syncthing that will not answer /rest/config must not turn
    that branch into a lane error."""
    cfg_xml = tmp_path / "config.xml"
    cfg_xml.write_text(
        "<configuration><gui><apikey>k</apikey></gui></configuration>", encoding="utf-8")

    def http_get(url, api_key, timeout):
        if url.endswith("/rest/config"):
            raise RuntimeError("config unavailable")
        if url.endswith("/rest/system/status"):
            return {"myID": "ME"}
        return {}

    lane = SyncthingLane(api_key="k", config_xml_path=cfg_xml, http_get=http_get,
                         http_post=lambda *a: {}, expected_folder_ids=[])
    status = lane.check_once()
    assert status.state == "idle"
    assert "no project folders to check yet" in (status.detail or "")


def test_the_heal_reads_the_folders_own_marker_name(tmp_path):
    """comp-sync-6: `markerName` is a per-folder config field and the marker
    was a plain file before Syncthing 1.0."""
    root = tmp_path / "Luts"
    root.mkdir()
    (root / ".stfolder-custom").write_text("marker", encoding="utf-8")
    folders = [{"id": "assets-luts", "path": str(root), "paused": False,
                "markerName": ".stfolder-custom",
                "devices": [{"deviceID": "ME"}, {"deviceID": "NAS"}]}]
    posts: list = []
    lane = _path_missing_lane(tmp_path, folders, posts, expected_folder_ids=["assets-luts"])
    lane.check_once()
    assert len(posts) == 1


def test_a_home_relative_folder_path_is_expanded_before_the_marker_test(tmp_path, monkeypatch):
    """comp-sync-6: Syncthing stores the path as configured, `~` included."""
    home = tmp_path / "home"
    root = home / "Luts"
    (root / ".stfolder").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    folders = [{"id": "assets-luts", "path": "~/Luts", "paused": False,
                "devices": [{"deviceID": "ME"}, {"deviceID": "NAS"}]}]
    posts: list = []
    lane = _path_missing_lane(tmp_path, folders, posts, expected_folder_ids=["assets-luts"])
    lane.check_once()
    assert len(posts) == 1


# -- live-5: a computer with nothing ticked is fine, on every machine ---------


class _TrayApp:
    """The slice of CompanionApp that compute_overall_color reads."""

    def __init__(self, mode="editor"):
        self.config = {"dashboard_url": "", "mode": mode}
        self.config_problems: list[str] = []
        self._require_login = True
        self._sync_enabled = True
        self.identity = type("_Id", (), {"valid": lambda self: True,
                                         "username": "alex"})()

    def is_paused(self):
        return False

    def effective_mode(self):
        return self.config["mode"]


def _idle3():
    from ccsync_companion.sync.base import LaneStatus
    return [LaneStatus(name=n, state="idle")
            for n in ("lane_a_video_up", "lane_b_proxy_down", "lane_c_syncthing")]


def test_an_editor_machine_with_nothing_ticked_is_green():
    """live-5: alex/Razer, mode editor, nothing ticked, everything working -
    an amber icon since 2026-09-17. The owner's rule, stated twice: a
    computer having nothing ticked is FINE."""
    from ccsync_companion.tray import compute_overall_color
    guard = {"blocked": {"reason": "no_selection",
                         "detail": "No projects are ticked for this computer"}}
    assert compute_overall_color(_idle3(), _TrayApp(), guard) == "green"


def test_the_nothing_ticked_line_is_not_a_warning():
    """live-5: the sentence stays, the fault glyph goes."""
    from ccsync_companion.tray import _blocked_line
    line = _blocked_line({"blocked": {
        "reason": "no_selection",
        "detail": "No projects are ticked for this computer"}})
    assert line == "No projects are ticked for this computer"
    assert "⚠" not in line


def test_a_real_blockage_is_still_amber_and_still_warns():
    """live-5 must not soften anything else."""
    from ccsync_companion.tray import _blocked_line, compute_overall_color
    guard = {"blocked": {"reason": "transport_offline",
                         "detail": "This computer cannot reach the server"}}
    assert compute_overall_color(_idle3(), _TrayApp(), guard) == "orange"
    assert (_blocked_line(guard) or "").startswith("⚠")


# -- comp-ui-2 / comp-ui-3 / comp-ui-4: the Windows tray icon ----------------
#
# Doubles in the shape of `test_bug_hunt_2026_09_11b_comp_ui`'s, plus the two
# timer calls comp-ui-2 needs. Nothing here touches Explorer: the seam is
# Shell_NotifyIconW, which the product already reaches through _Win32.get().

import ctypes  # noqa: E402 - after the module docstring block above


class _Shell:
    """Shell_NotifyIconW that refuses NIM_ADD `fail` times, then accepts."""

    def __init__(self, fail: int) -> None:
        self.fail = fail
        self.calls = 0

    def Shell_NotifyIconW(self, action, data):  # noqa: N802 - the Win32 name
        self.calls += 1
        return 0 if self.calls <= self.fail else 1


class _Nid(ctypes.Structure):
    _fields_ = [("uFlags", ctypes.c_uint), ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p), ("szTip", ctypes.c_wchar * 128)]


class _User32:
    def __init__(self):
        self.timers: list[tuple] = []
        self.killed: list[tuple] = []
        self.destroyed_icons: list = []

    def DefWindowProcW(self, *a):  # noqa: N802 - the Win32 name
        raise AssertionError("the branch under test must handle the message")

    def SetTimer(self, hwnd, timer_id, ms, proc):  # noqa: N802
        self.timers.append((hwnd, timer_id, ms))
        return timer_id

    def KillTimer(self, hwnd, timer_id):  # noqa: N802
        self.killed.append((hwnd, timer_id))
        return 1

    def DestroyIcon(self, hicon):  # noqa: N802
        self.destroyed_icons.append(hicon)
        return 1


class _Api:
    def __init__(self, shell, user32=None) -> None:
        self.shell32 = shell
        self.user32 = user32 or _User32()


def _windows_icon(monkeypatch, shell, user32=None):
    from ccsync_companion import tray_native
    icon = tray_native._WindowsIcon("ccsync", None, "starting")
    monkeypatch.setattr(icon, "_nid", lambda: _Nid())
    monkeypatch.setattr(icon, "_icon_handle", lambda: 0)
    api = _Api(shell, user32)
    monkeypatch.setattr(tray_native._Win32, "get", staticmethod(lambda: api))
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    return icon, api


def test_a_failed_re_add_keeps_trying_until_explorer_takes_it(monkeypatch):
    """comp-ui-2: one late Explorer left the editor with no icon, no menu, no
    Settings and no Quit for the life of the process, because the only other
    caller of _add_icon is the next TaskbarCreated broadcast - which the
    branch's own comment says may be never."""
    from ccsync_companion import tray_native
    shell = _Shell(fail=10_000)
    icon, api = _windows_icon(monkeypatch, shell)
    icon.on_register_failure = lambda detail, fatal=True: None
    icon._taskbar_created_msg = 0xC123
    icon._added = True

    assert icon._on_message(7, 0xC123, 0, 0) == 0
    assert api.user32.timers, "a failed re-add must arm a retry"
    assert api.user32.timers[0][1] == tray_native._CCSYNC_READD_TIMER_ID
    assert api.user32.timers[0][2] == tray_native._NIM_READD_RETRY_MS

    # A minute later Explorer is still not ready: one attempt, still armed.
    before = shell.calls
    assert icon._on_message(7, tray_native._WM_TIMER,
                            tray_native._CCSYNC_READD_TIMER_ID, 0) == 0
    assert shell.calls == before + 1, "one NIM_ADD per tick, not the flat six"
    assert icon._added is False
    assert api.user32.killed == []

    # And the minute Explorer takes it, the icon is back and the timer stops.
    shell.fail = 0
    assert icon._on_message(7, tray_native._WM_TIMER,
                            tray_native._CCSYNC_READD_TIMER_ID, 0) == 0
    assert icon._added is True
    assert api.user32.killed == [(7, tray_native._CCSYNC_READD_TIMER_ID)]


def test_the_retry_never_writes_a_crash_report(monkeypatch, tmp_path):
    """comp-ui-3: an Explorer crash-loop wrote one TrayIconUnavailable file
    per broadcast, and _prune keeps twenty, so the transient failures deleted
    the real crash reports. A failure the process recovers from by itself is
    a warning, not a crash."""
    from ccsync_companion import crash_report, tray
    written: list = []
    monkeypatch.setattr(crash_report, "write_report",
                        lambda payload, cfg=None: written.append(payload))

    class _Icon:
        pass

    icon = _Icon()
    tray._report_windows_icon_failure(
        object(), icon, "Explorer said no", fatal=False)
    assert written == []
    assert getattr(icon, "_ccsync_stop", False) is False

    tray._report_windows_icon_failure(object(), icon, "nothing worked", fatal=True)
    assert len(written) == 1
    assert written[0]["exception"]["type"] == "TrayIconUnavailable"
    assert icon._ccsync_stop is True


def test_the_recoverable_wording_does_not_send_the_editor_to_a_restart(monkeypatch, caplog):
    """comp-ui-3: the sentence contradicted the fix that made the failure
    non-fatal."""
    from ccsync_companion import crash_report, tray
    monkeypatch.setattr(crash_report, "write_report", lambda *a, **k: None)
    with caplog.at_level("WARNING", logger="ccsync.tray"):
        tray._report_windows_icon_failure(object(), object(), "busy", fatal=False)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "re-added automatically" in text
    assert "Sign out and back in" not in text


def test_a_terminal_registration_failure_frees_the_window(monkeypatch):
    """comp-ui-4: the happy path frees the HWND, its per-instance class and
    every cached HICON in _pump's finally; run()'s error arm returned with all
    of them held for the life of the process."""
    icon, api = _windows_icon(monkeypatch, _Shell(fail=10_000))
    monkeypatch.setattr(icon, "_create_window", lambda: None)
    icon._hwnd = 4242
    icon._hicon_cache[1] = (object(), 99)
    icon.on_register_failure = lambda detail, fatal=True: None
    stopped_when_torn_down = []
    real_teardown = icon._teardown

    def _watched_teardown():
        stopped_when_torn_down.append(icon._stopped.is_set())
        real_teardown()

    monkeypatch.setattr(icon, "_teardown", _watched_teardown)

    icon.run()

    assert icon._hwnd is None
    assert icon._hicon_cache == {}
    assert api.user32.destroyed_icons == [99]
    # ...and before _stopped, or a stop() waiter returns while the window
    # is still alive.
    assert stopped_when_torn_down == [False]


# -- res-companion-4 / CR-279: a wedged thread is retired, not duplicated ----


def test_a_retired_media_tree_thread_exits_instead_of_looping(monkeypatch):
    """res-companion-4: _start_media_tree_thread CLEARS the shared stop
    event, so an orphaned thread went on looping once it unblocked - two
    walkers of one media pool, both reaching apply_relinks and Resolve. The
    loop is driven unbound here: no CompanionApp, no threads, no Resolve."""
    import threading

    from ccsync_companion.app import CompanionApp

    class _Stub:
        def __init__(self):
            self._media_tree_stop_event = threading.Event()
            self._media_tree_generation = 4
            self.media_tree_refresh_interval = 0.0
            self.passes = 0
            self.rebinds = 0
            self.resumes = 0

        def _refresh_media_tree_once(self):
            self.passes += 1
            # The watchdog retires this thread while it is inside the pass,
            # which is where a wedge happens.
            self._media_tree_generation += 1

        def _refresh_p_mapping_mode(self):
            pass

        def retry_loopback_bind(self):
            self.rebinds += 1

        def _resume_broll_proxy_upgrades(self):
            # comp-app-2 (2026-09-18b mediums): the loop calls this every
            # tick now, beside retry_loopback_bind.
            self.resumes += 1

    stub = _Stub()
    CompanionApp._media_tree_loop(stub, generation=4)
    assert stub.passes == 1, "the retired thread must not start another pass"

    # ...and a thread that is still the current one keeps going until the
    # stop event, exactly as before.
    stub2 = _Stub()
    stub2._refresh_media_tree_once = lambda: (
        setattr(stub2, "passes", stub2.passes + 1),
        stub2._media_tree_stop_event.set())[0]
    CompanionApp._media_tree_loop(stub2, generation=4)
    assert stub2.passes == 1


# -- live-1: the tray's own fallback reads the file, not the guard -----------


def test_a_recovered_or_old_stall_is_not_why_this_machine_is_not_syncing():
    """live-1: `sync_guard.blocked` falls back to reading lane_stall.json
    when the guard carries no `stalled` section, and the FILE keeps the
    record for ever as evidence. ruskin's tray was red for a week over one
    upload killed on 2026-09-11."""
    from datetime import datetime, timedelta, timezone

    from ccsync_companion.app import CompanionApp
    from ccsync_companion.sync import rclone_lane

    class _Stub:
        def __init__(self, record):
            self._record = record

        def _lane_stall_record(self):
            return dict(self._record)

    fresh = {"lane": "A", "seconds": 1500, "killed": True,
             "at": datetime.now(timezone.utc).isoformat()}
    answer = CompanionApp._blocked_candidate(_Stub(fresh), "lane_stalled", {})
    assert answer is not None, "a stall from a minute ago is still current"

    recovered = dict(fresh, recovered_at=datetime.now(timezone.utc).isoformat())
    assert CompanionApp._blocked_candidate(_Stub(recovered), "lane_stalled", {}) is None

    old = dict(fresh, at=(datetime.now(timezone.utc) - timedelta(
        seconds=rclone_lane.LANE_STALL_MAX_AGE_SECONDS + 60)).isoformat())
    assert CompanionApp._blocked_candidate(_Stub(old), "lane_stalled", {}) is None


# -- CR-280: a frozen Python with no CA bundle -------------------------------


def test_the_process_is_pointed_at_a_ca_bundle_when_it_has_none(tmp_path, monkeypatch):
    """CR-280: every HTTPS download from the frozen macOS companion fails
    `unable to get local issuer certificate`, so ffmpeg, ffprobe, deno and
    yt-dlp's checksum list can none of them be fetched and requester-first
    YouTube downloads have never run on a Mac."""
    from ccsync_companion import sidecar_tools

    bundle = tmp_path / "cert.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
    monkeypatch.setattr(sidecar_tools, "CA_BUNDLE_CANDIDATES", (str(bundle),))
    monkeypatch.setattr(sidecar_tools.sys, "frozen", True, raising=False)

    env: dict = {}
    assert sidecar_tools.ensure_ca_bundle(env) == str(bundle)
    assert env["SSL_CERT_FILE"] == str(bundle)
    assert env["SSL_CERT_DIR"] == str(bundle.parent)


def test_an_environment_that_already_names_a_bundle_always_wins(tmp_path, monkeypatch):
    """CR-280: a site that pins its own trust store is not overridden."""
    from ccsync_companion import sidecar_tools

    monkeypatch.setattr(sidecar_tools.sys, "frozen", True, raising=False)
    env = {"SSL_CERT_FILE": "/etc/mine/roots.pem"}
    assert sidecar_tools.ensure_ca_bundle(env) is None
    assert env["SSL_CERT_FILE"] == "/etc/mine/roots.pem"


def test_no_bundle_anywhere_is_a_warning_not_a_refusal_to_start(monkeypatch):
    """CR-280: a companion that cannot find one must still run."""
    from ccsync_companion import sidecar_tools

    monkeypatch.setattr(sidecar_tools, "CA_BUNDLE_CANDIDATES", ())
    monkeypatch.setattr(sidecar_tools, "ca_bundle_path", lambda: None)
    monkeypatch.setattr(sidecar_tools.sys, "frozen", True, raising=False)
    env: dict = {}
    assert sidecar_tools.ensure_ca_bundle(env) is None
    assert "SSL_CERT_FILE" not in env


# -- comp-app-2 / comp-app-5: the relaunch ceiling's own file ----------------


def test_a_truncated_history_is_never_what_a_kill_leaves_behind(tmp_path):
    """comp-app-2: the supervisor exists because machines die abruptly, and
    its own ceiling file was the one state file still written in place. A
    power cut inside the write left half a JSON object, read_history answered
    [] and the build that could not stay up got three more relaunches an
    hour."""
    from ccsync_companion import supervisor

    state = tmp_path / "state"
    assert supervisor.write_history(state, [1.0, 2.0]) is True
    path = state / supervisor.HISTORY_FILENAME
    assert json.loads(path.read_text(encoding="utf-8"))["relaunches"] == [1.0, 2.0]
    assert not list(state.glob("*.tmp")), "the temp file is renamed, not left"

    # The write is atomic: what a reader sees is the old file or the new one,
    # never a truncated one. Pinned through the one seam a test can hold -
    # os.replace is what makes that true, and nothing else here may write the
    # destination.
    source = Path(supervisor.__file__).read_text(encoding="utf-8")
    body = source.split("def write_history", 1)[1].split("\ndef ", 1)[0]
    assert "os.replace(tmp, path)" in body
    assert "HISTORY_FILENAME).write_text" not in body


def test_one_bad_stamp_costs_one_stamp_not_the_ceiling(tmp_path):
    """comp-app-5: merge_history skips a bad item and keeps the rest; its
    reader did the opposite, for the same list."""
    from ccsync_companion import supervisor

    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / supervisor.HISTORY_FILENAME).write_text(
        json.dumps({"relaunches": [1.0, None, 3.0]}), encoding="utf-8")
    assert supervisor.read_history(state) == [1.0, 3.0]

    # ...and a file that is not JSON at all is still no history.
    (state / supervisor.HISTORY_FILENAME).write_text('{"relaun', encoding="utf-8")
    assert supervisor.read_history(state) == []


# -- comp-app-1: the editing-proxy resume is not part of the relink pass -----


def test_the_editing_proxy_resume_runs_with_resolve_closed(tmp_path, monkeypatch):
    """comp-app-1 + comp-app-2: `proxy_relink_enabled = false` is a supported
    config key, and the resume of a stand-in's editing proxy was the third
    statement inside the relink pass's try. comp-app-1 gave it its own
    statement but left it at the TAIL of _refresh_media_tree_once, below the
    two early returns (get_media_pool_items() not ok, and an ignored
    project), so a closed or ignored Resolve still stranded the row at
    `pending` for ever. Driven through the real media-tree LOOP with Resolve
    answering not-ok, which is the call site that was wrong: on the old code
    nothing resumes."""
    import threading

    from ccsync_companion import app as app_mod

    resumed: list = []
    monkeypatch.setattr(app_mod.broll_server_mod, "resume_pending_upgrades",
                        lambda cfg: resumed.append(cfg))
    monkeypatch.setattr(app_mod.resolve_bridge, "get_media_pool_items",
                        lambda: {"ok": False, "reason": "resolve is closed"})

    class _Stub:
        config = {"proxy_relink_enabled": False, "local_root": str(tmp_path)}
        _ignored_resolve_projects: tuple = ()
        media_tree_refresh_interval = 0.0

        def __init__(self):
            self._media_tree_lock = threading.Lock()
            self._media_tree_cache: dict = {}
            self._media_tree_generation = 0
            self._media_tree_heartbeat = 0.0
            self._media_tree_stop_event = threading.Event()

        def _maybe_recover_stale_bridge(self):
            pass

        def _refresh_p_mapping_mode(self):
            # One pass only: this is the last thing the loop does before the
            # two piggy-backed ticks, so stopping here still exercises them.
            self._media_tree_stop_event.set()

        def retry_loopback_bind(self):
            pass

        def _local_root_is_broken(self):
            return False

        _media_tree_loop = app_mod.CompanionApp._media_tree_loop
        _refresh_media_tree_once = app_mod.CompanionApp._refresh_media_tree_once
        _resume_broll_proxy_upgrades = app_mod.CompanionApp._resume_broll_proxy_upgrades

    stub = _Stub()
    stub._media_tree_loop(generation=0)

    assert len(resumed) == 1, (
        "the resume needs no Resolve connection and must not sit behind one")


def test_the_resume_still_waits_for_a_local_root(tmp_path, monkeypatch):
    """comp-app-1: the download lands under local_root, so that gate came
    with it when the call was hoisted."""
    from ccsync_companion import app as app_mod

    resumed: list = []
    monkeypatch.setattr(app_mod.broll_server_mod, "resume_pending_upgrades",
                        lambda cfg: resumed.append(cfg))

    class _Broken:
        config: dict = {}

        def _local_root_is_broken(self):
            return True

        _resume_broll_proxy_upgrades = app_mod.CompanionApp._resume_broll_proxy_upgrades

    _Broken()._resume_broll_proxy_upgrades()
    assert resumed == []


# -- comp-app-6: the toast names the repair that shipped beside it -----------


def test_the_unreadable_id_toast_says_where_the_repair_is(tmp_path, monkeypatch):
    """comp-app-6: comp-app-8 shipped a warning and a repair button in one
    pass, and the warning's copy told the editor to mail their log and wait
    for their admin. It must name Settings, without reading as an
    instruction to press it (the button's own comment: a one-click identity
    change is not a decision to take from a notification)."""
    from ccsync_companion import app as app_mod, machine as machine_mod

    said: list[str] = []
    monkeypatch.setattr(machine_mod, "machine_id_unreadable", lambda *a, **k: True)
    monkeypatch.setattr(machine_mod, "machine_path",
                        lambda *a, **k: Path("machine.json"))

    class _Stub:
        _machine_id_warned = False
        config: dict = {}

        def _notify_tray(self, body, title=None):
            said.append(body)

        _warn_if_machine_id_is_unreadable = (
            app_mod.CompanionApp._warn_if_machine_id_is_unreadable)

    stub = _Stub()
    stub._warn_if_machine_id_is_unreadable()
    assert len(said) == 1
    body = said[0]
    assert "Settings" in body
    assert "Send your log to your admin" not in body
    assert "—" not in body, "no em dashes in copy an editor reads"

    # Still once per process.
    stub._warn_if_machine_id_is_unreadable()
    assert len(said) == 1


# -- comp-app-3: "we are withholding a build" is not "there is nothing" ------


def _older_version() -> str:
    from ccsync_companion import config as config_mod

    parts = [int(p) for p in config_mod.VERSION.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] > 0:
            parts[index] -= 1
            return ".".join(str(p) for p in parts)
    raise AssertionError("VERSION has no older neighbour")


def test_a_withheld_build_does_not_retire_the_standing_refusal(tmp_path):
    """comp-app-3: `api._upgrade_info` returns None in four states in which a
    package EXISTS and is being withheld (retracted, needs a newer dashboard,
    wrong arch, unknown platform). comp-ytdl-jobs-1 reads a reply with no
    `upgrade` key as "nothing is being refused", so in all four the chip and
    the `upgrade_refused` alert went out on a machine that is refusing to
    upgrade and will never be offered anything again."""
    from ccsync_companion import upgrade as upgrade_mod

    manager = upgrade_mod.UpgradeManager({"dashboard_url": "http://dash.example"},
                                         floor_file=tmp_path / "upgrade_floor.json")
    manager._note_refusal(_older_version(), "signature did not verify")
    assert manager.refusal() is not None

    for _ in range(3):
        manager.note_report_response({"ok": True, "upgrade_none_reason": "retracted"})
    assert manager.refusal() is not None, (
        "a dashboard that says it is withholding a build has not said there "
        "is nothing to take")

    # ...and comp-ytdl-jobs-1's own case is untouched: a plain reply with no
    # offer and no reason still retires the refusal.
    manager.note_report_response({"ok": True})
    assert manager.refusal() is None


# -- comp-ui-1: a toast raised before the icon existed is not lost -----------


def test_toasts_raised_during_registration_arrive_when_the_icon_does(monkeypatch):
    """comp-ui-1: the first registration backs off for up to 105 s and run()
    does not reach the message pump until it returns, so app.py's +3 s
    post-upgrade and crash-loop-rollback sentences - the one line that
    explains a silent downgrade - were logged as DROPPED and discarded. Any
    safety latch that trips in that window went the same way."""
    from ccsync_companion import tray_native

    shell = _Shell(fail=2)
    icon, _api = _windows_icon(monkeypatch, shell)
    shown: list = []
    monkeypatch.setattr(icon, "_modify", lambda **kw: shown.append(kw.get("info")))

    icon.notify("Update complete. Now running v0.9.75.", "CC Sync")
    assert shown == [], "there is no icon to show it on yet"

    icon._add_icon(attempts=6)

    assert icon._added is True
    assert len(shown) == 1
    assert "Update complete" in shown[0][0]


def test_the_held_toasts_are_bounded_and_oldest_first(monkeypatch):
    """comp-ui-1: an editor coming back to a registered icon wants the last
    few sentences, not a minute and a half of them."""
    from ccsync_companion import tray_native

    icon, _api = _windows_icon(monkeypatch, _Shell(fail=10_000))
    for n in range(tray_native._PENDING_TOAST_MAX + 3):
        icon.notify(f"line {n}")
    assert len(icon._pending_toasts) == tray_native._PENDING_TOAST_MAX
    assert icon._pending_toasts[0][0] == "line 3"


# -- comp-ui-5: a rehearsal's progress screen ------------------------------


def test_a_rehearsal_says_checking_and_moves_its_bar(tmp_path):
    """comp-ui-5: comp-resolve-b-1 stopped a rehearsal crediting bytes it
    never copied and left `batch_bytes_total` at the real 800 GB, so FIX ALL
    under `fixer_dry_run` drew a bar pinned at 0% with
    `Copying "A001_C012.braw": 0 B of 12.7 GB` beside it - on the run whose
    whole purpose (RES-15) is a screen an admin can trust."""
    from ccsync_companion import popup

    published: list[dict] = []
    rows = []
    for name in ("a.braw", "b.braw"):
        path = tmp_path / name
        path.write_bytes(b"x" * 1024)
        rows.append({"file_path": str(path), "clip_name": name,
                     "suggested_dest": "Footage/" + name, "media_pool_items": []})

    popup.perform_fix_all(
        rows, {}, str(tmp_path),
        fix_clip_fn=lambda *a, **k: {"ok": True, "dry_run": True,
                                     "message": "would copy"},
        state_fn=published.append)

    mid = [p for p in published if p.get("name")]
    assert mid, "the per-file publishes are the screen under test"
    # comp-ui-1 (2026-09-18b mediums): `mid[-1]`, deliberately. This caller
    # INJECTS its own copier, so the first-answer latch is what governs it and
    # its file 1 is still published as a real copy. The real fixer's first
    # file (the bug comp-ui-1 names) is pinned in
    # test_bug_hunt_2026_09_18b_companion_ui.py.
    later = mid[-1]
    assert later["rehearsing"] is True
    assert later["batch_bytes_total"] == 0, "there are no bytes to measure"
    assert popup.format_file_progress(
        "A001_C012.braw", 0, 12_700_000_000, None, None,
        rehearsal=True) == 'Checking "A001_C012.braw"'
    # ...and the real copy's wording is untouched.
    assert popup.format_file_progress(
        "A001_C012.braw", 0, 12_700_000_000, None, None).startswith('Copying ')
    # The summary keys the rehearsal block reads still arrive.
    final = published[-1]
    assert final["rehearsal"] == 2 and final["fixed"] == 0


# -- comp-sync-3: the trash relocation cannot overwrite, on any platform -----


def test_a_destination_that_appeared_mid_move_is_a_refusal_not_a_loss(tmp_path, monkeypatch):
    """comp-sync-3: `_move_out_of_trash`'s docstring promised that nothing
    here can overwrite, which was true on Windows only - POSIX rename(2)
    replaces the destination silently, so the copy lane B had just downloaded
    for the other project was destroyed by the trashed one, in a case the
    function's own contract called impossible."""
    import os as os_mod

    from ccsync_companion.sync.rclone_lane import RcloneLane

    src = tmp_path / "trash" / "gold.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"the trashed copy")
    dest = tmp_path / "ProjectB" / "gold.mp4"
    dest.parent.mkdir(parents=True)

    real_exists = Path.exists

    def _racing_exists(self):
        answer = real_exists(self)
        if self == dest and not answer:
            # Somebody else lands the file in the window between the check
            # and the move, which is the whole of comp-sync-3.
            dest.write_bytes(b"the fresh download")
        return answer

    monkeypatch.setattr(Path, "exists", _racing_exists)
    outcome = RcloneLane._move_out_of_trash(object(), src, dest, len(b"the trashed copy"))
    monkeypatch.undo()

    assert dest.read_bytes() == b"the fresh download", "the fresh copy survives"
    if os_mod.name != "nt":
        assert outcome == "kept"
        assert src.exists(), "and the trashed copy is still in the trash"


# -- comp-sync-4: a file moved into a BORROWED project has a home here -------


def test_a_file_moved_into_a_borrowed_folder_is_not_trashed(tmp_path):
    """comp-sync-4: `rel_to_slug` holds SELECTED projects only, on purpose
    (it is the manifest and proxy-scan scope), so a hand move into a project
    this machine borrows from resolved to None: the editor's copies went to
    the trash for 14 days and were downloaded again over the link, although
    the folder was right there."""
    from ccsync_companion import app as app_mod

    class _Sequencer:
        rel_to_slug = {"2026/FF5/Animals": "animals-2026"}

        def borrowed_lenders(self):
            return {"gala-2026": {"rel": "2026/FF5/Gala",
                                  "subs": ["Footage/Drone"],
                                  "borrowers": ["animals-2026"]}}

    class _Stub:
        sequencer = _Sequencer()
        _project_rel_for_slug = app_mod.CompanionApp._project_rel_for_slug
        _borrowed_rel_for_slug = app_mod.CompanionApp._borrowed_rel_for_slug

    stub = _Stub()
    # The selected project still answers, with or without a path.
    assert stub._project_rel_for_slug("animals-2026", "Proxy/a.mp4") == \
        app_mod.PROJECTS_PREFIX + "2026/FF5/Animals"
    # The lender answers for a file INSIDE the borrowed subtree...
    assert stub._project_rel_for_slug("gala-2026", "Footage/Drone/DJI_0001.MP4") == \
        app_mod.PROJECTS_PREFIX + "2026/FF5/Gala"
    # ...and not for the rest of the lender's project, which is not here.
    assert stub._project_rel_for_slug("gala-2026", "Footage/A-Cam/A001.mov") is None
    assert stub._project_rel_for_slug("gala-2026") is None
    assert stub._project_rel_for_slug("someone-elses-2026", "Footage/x.mov") is None


def test_lane_b_asks_with_the_path_and_still_accepts_an_older_callable(tmp_path):
    """comp-sync-4: the wire between lane B and app.py is a callable, and an
    injected double that takes the slug alone must keep working."""
    from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, RcloneLane

    (tmp_path / "local").mkdir()
    asked: list = []

    def _two_args(slug, rel=""):
        asked.append((slug, rel))
        return "Projects/2026/FF5/Gala"

    lane = RcloneLane(direction=DIRECTION_DOWN, local_root=str(tmp_path / "local"),
                      remote="nas", remote_root="Creators_Club",
                      state_dir=tmp_path / "state", project_rel_fn=_two_args)
    place = {"project_slug": "gala-2026", "rel_path": "Footage/Drone/DJI_0001.MP4"}
    dest = lane._local_destination(place)
    assert dest is not None
    assert asked == [("gala-2026", "Footage/Drone/DJI_0001.MP4")]

    lane.project_rel_fn = lambda slug: "Projects/2026/FF5/Gala"
    assert lane._local_destination(place) == dest


# -- comp-sync-5: the CR-90 worked example, in the right bytes ---------------


def test_no_companion_source_file_carries_latin1_mojibake():
    """comp-sync-5: commit 34a3c8f re-encoded the accented example in the two
    comments whose only job is to document CR-90's NFC/NFD rule, by decoding
    UTF-8 as latin-1 and encoding it again. Harmless at runtime and fatal to
    the one worked example a future reader will look for - and evidence that
    an editing tool in that pass was not UTF-8 clean."""
    # The three sequences that corruption produces for S-caron, c-caron and
    # i-acute. Any of them in a source file means the same tool ran again.
    mojibake = ("\u00c5\u00a0", "\u00c4\u008d", "\u00c3\u00ad")
    root = Path(__file__).resolve().parent.parent / "src" / "ccsync_companion"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(bad in text for bad in mojibake):
            offenders.append(path.name)
    assert offenders == []


# -- comp-sync-5: the CR-90 worked example, in the right bytes ---------------


def test_no_companion_source_file_carries_latin1_mojibake():
    """comp-sync-5: commit 34a3c8f re-encoded the accented example in the two
    comments whose only job is to document CR-90's NFC/NFD rule, by decoding
    UTF-8 as latin-1 and encoding it again. Harmless at runtime and fatal to
    the one worked example a future reader will look for - and evidence that
    an editing tool in that pass was not UTF-8 clean."""
    # The three sequences that corruption produces for S-caron, c-caron and
    # i-acute. Any of them in a source file means the same tool ran again.
    mojibake = ("\u00c5\u00a0", "\u00c4\u008d", "\u00c3\u00ad")
    root = Path(__file__).resolve().parent.parent / "src" / "ccsync_companion"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(bad in text for bad in mojibake):
            offenders.append(path.name)
    assert offenders == []


# -- CR-283W / CR-283X: the two halves owed in by companion-media ------------


def test_a_refresh_only_pass_is_not_nothing_to_do(tmp_path):
    """comp-resolve-5's other half: `apply_relinks` answers `refreshed`, and
    the attach verdict kept only `relinked`/`failed` - so a pass that re-read
    the clips whose file changed under them (the phase 3 geometry check after
    a stand-in was replaced) said `attached: 0` and every surface read it as
    nothing having happened."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import settings_window

    class _Stub:
        _proxy_attach: dict = {}
        _note_proxy_attach = app_mod.CompanionApp._note_proxy_attach

    stub = _Stub()
    stub._note_proxy_attach({"relinked": 0, "failed": 0, "refreshed": 3})
    assert stub._proxy_attach["refreshed"] == 3

    # ...and the Settings window says so instead of drawing nothing.
    del settings_window


def test_a_stand_in_whose_proxy_gave_up_reaches_the_editor(monkeypatch):
    """comp-broll-tiers-5: an editor in that state is cutting on the 1080p
    preview believing it is the editing proxy, and the only trace was a log
    line and `GET /status`, which nothing they see reads."""
    from ccsync_companion import app as app_mod
    from ccsync_companion import broll_standins, tray

    monkeypatch.setattr(broll_standins, "given_up_upgrades", lambda: [
        {"local_path": "P:/x.mov", "rel_path": "x.mov",
         "upgrade_note": "the server gave up after 5 tries"}])

    class _Stub:
        standins_owed = app_mod.CompanionApp.standins_owed

    owed = _Stub().standins_owed()
    assert owed["count"] == 1 and "gave up" in owed["why"]

    phrases = tray.resolve_count_phrases({"standins_owed": owed})
    assert any("preview copy" in p for p in phrases)

    # Nothing owed is an EMPTY dict, which is what clears the line.
    monkeypatch.setattr(broll_standins, "given_up_upgrades", lambda: [])
    assert _Stub().standins_owed() == {}
    assert tray.resolve_count_phrases({"standins_owed": {}}) == []
