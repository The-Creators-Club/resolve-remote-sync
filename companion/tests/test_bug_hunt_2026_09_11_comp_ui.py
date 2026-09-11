"""Regression tests for the 2026-09-11 bug hunt, comp-ui territory (CR-235).

Nothing here builds a real Tk root or touches a real tray: the Windows icon
is exercised through its own seams (`_add_icon`'s Shell_NotifyIcon call and
the `on_register_failure` hook), and the Settings window through a stubbed
`tkinter`, exactly the way conftest's `_no_real_tk_windows` guard requires.
"""

from __future__ import annotations

import ctypes
import json
import logging
from pathlib import Path

import pytest

from ccsync_companion import supervisor, tray, tray_native


# -- comp-ui-1: a tray icon that will not register ---------------------------


class _FakeShell:
    """Shell_NotifyIconW that refuses NIM_ADD `fail` times, then accepts."""

    def __init__(self, fail: int) -> None:
        self.fail = fail
        self.calls = 0

    def Shell_NotifyIconW(self, action, data):  # noqa: N802 - the Win32 name
        self.calls += 1
        return 0 if self.calls <= self.fail else 1


def _windows_icon(monkeypatch, shell, slept):
    icon = tray_native._WindowsIcon("ccsync", None, "starting")
    monkeypatch.setattr(icon, "_nid", lambda: _Nid())
    monkeypatch.setattr(icon, "_icon_handle", lambda: 0)
    monkeypatch.setattr(tray_native._Win32, "get", staticmethod(lambda: _Api(shell)))
    monkeypatch.setattr("time.sleep", slept.append)
    # ctypes.get_last_error exists only on Windows; the companion suite also
    # runs on the macOS release runner (release-macos 2026-09-11 went red on
    # exactly this), and what these tests exercise is the retry schedule,
    # not GetLastError.
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    return icon


class _Nid(ctypes.Structure):
    """Enough of NOTIFYICONDATAW for byref() to accept it."""

    _fields_ = [("uFlags", ctypes.c_uint), ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p), ("szTip", ctypes.c_wchar * 128)]


class _Api:
    def __init__(self, shell) -> None:
        self.shell32 = shell


def test_a_tray_icon_that_will_not_register_retries_with_backoff(monkeypatch, caplog):
    """comp-ui-1: at login Explorer's notification area can be a minute away.

    Six half-second tries (three seconds) is not that minute, and until now
    every one of them was silent.
    """
    slept: list[float] = []
    shell = _FakeShell(fail=7)
    icon = _windows_icon(monkeypatch, shell, slept)
    with caplog.at_level(logging.WARNING, logger="ccsync_companion.tray_native"):
        icon._add_icon(attempts=tray_native._NIM_ADD_STARTUP_ATTEMPTS)

    assert icon._added is True
    # It waited for longer than the old fixed 6 x 0.5 s schedule...
    assert sum(slept) > 6 * tray_native._NIM_ADD_RETRY_DELAY
    # ...backing off rather than hammering, and capped.
    assert slept == sorted(slept)
    assert max(slept) <= tray_native._NIM_ADD_MAX_DELAY
    # ...and said so every time, at WARNING, where an admin reading the log
    # after "my tray icon is missing" will find it.
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 7
    assert "tray icon" in warnings[0].getMessage()


def test_a_registration_that_never_succeeds_announces_itself(monkeypatch):
    """comp-ui-1: run() used to log once and return, and nothing read that."""
    slept: list[float] = []
    icon = _windows_icon(monkeypatch, _FakeShell(fail=10_000), slept)
    monkeypatch.setattr(icon, "_create_window", lambda: None)
    monkeypatch.setattr(icon, "_pump", lambda: None)
    announced: list[str] = []
    icon.on_register_failure = announced.append

    icon.run()

    assert icon.registered is False
    assert announced and "NIM_ADD" in announced[0]
    assert icon._stopped.is_set()


def test_a_dropped_toast_says_what_it_dropped(monkeypatch, caplog):
    """comp-ui-1: the four safety latches all arrive as tray toasts."""
    icon = tray_native._WindowsIcon("ccsync", None, "starting")
    icon._added = False
    icon._register_error = "Shell_NotifyIcon(NIM_ADD) failed"
    with caplog.at_level(logging.WARNING, logger="ccsync_companion.tray_native"):
        icon.notify("Proxy download has stopped itself: too many deletions.")

    text = " ".join(r.getMessage() for r in caplog.records)
    assert "too many deletions" in text
    assert "DROPPED" in text


def test_the_failure_is_reported_and_stops_the_refresh_loops(tmp_path, caplog):
    """comp-ui-1: visible in the LOG at ERROR and in the report.

    The report channel is the existing `sync_guard.crashes` block - a crash
    file, the one thing the companion already puts on every report tick and
    in build_diagnostics. No new wire field, so a dashboard one release
    behind is unaffected.
    """
    from ccsync_companion import crash_report

    class _App:
        config = {"log_path": str(tmp_path / "companion.log")}

        def _notify_tray(self, *a, **k):
            raise AssertionError("the tray is exactly what is broken here")

    icon = tray_native._WindowsIcon("ccsync", None, "starting")
    with caplog.at_level(logging.ERROR, logger="ccsync_companion.tray"):
        tray._report_windows_icon_failure(_App(), icon, "NIM_ADD failed 12 times")

    assert getattr(icon, "_ccsync_stop", False) is True
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    files = sorted((tmp_path / "crashes").glob("*.json"))
    assert files, "the failure must reach the report, not just the log"
    report = json.loads(files[-1].read_text(encoding="utf-8"))
    assert report["exception"]["type"] == "TrayIconUnavailable"
    assert crash_report.crash_summary(_App.config)["count"] == 1


def test_start_tray_wires_the_failure_hook_on_windows(monkeypatch):
    """comp-ui-1: the hook is useless if start_tray does not attach it."""
    calls: list[str] = []
    monkeypatch.setattr(tray.ui_dispatch, "uses_main_thread", lambda: False)
    # comp-ui-1 (2026-09-11b): the hook now carries `fatal` -- whether the
    # pump is gone for good or Explorer can still hand the icon back.
    monkeypatch.setattr(tray, "_report_windows_icon_failure",
                        lambda app, icon, detail, fatal=True: calls.append(detail))
    icon = _StubIcon()
    monkeypatch.setattr(tray.tray_backend, "Icon", lambda *a, **k: icon)
    monkeypatch.setattr(tray, "_tray_snapshot", lambda app: {"color": "green"})
    monkeypatch.setattr(tray, "_icon_image_cached", lambda color: None)
    monkeypatch.setattr(tray, "_tooltip_text", lambda snap: "")
    monkeypatch.setattr(tray, "_build_menu", lambda app, snap: None)
    monkeypatch.setattr(tray, "_menu_fingerprint", lambda snap: ())

    started = tray.start_tray(object(), refresh_interval=9999, pulse_interval=9999)

    assert started is icon
    assert callable(icon.on_register_failure)
    icon.on_register_failure("NIM_ADD failed")
    assert calls == ["NIM_ADD failed"]


class _StubIcon:
    on_register_failure = None

    def __init__(self) -> None:
        self.name = "ccsync"
        self.icon = None
        self.title = ""
        self.menu = None

    def run(self) -> None:
        pass

    def stop(self) -> None:
        pass


# -- comp-ui-2 / res-companion-4: the relaunch ceiling ------------------------


PID = 4242
NOW = 1_700_000_000.0


def _marker(pid: int = PID) -> dict:
    return {"pid": pid, "version": "0.9.70", "started": "2026-09-11T10:00:00"}


def test_the_ceiling_survives_a_history_file_that_cannot_be_written():
    """comp-ui-2: `decide`'s cap was a pure function of a file both whose
    read and whose write swallow every error."""
    prior = [NOW - 300, NOW - 1200, NOW - 2400]
    # The file is empty (unwritable), but the count came in on argv.
    argv = supervisor.supervisor_argv(
        Path("x.exe"), PID, Path("c"), Path("s"), prior=prior)
    parsed = supervisor._parse(argv[1:])
    assert parsed["prior"] == sorted(prior)
    assert supervisor.decide(3, _marker(), PID, supervisor.merge_history([], prior),
                             NOW).relaunch is False


def test_merge_history_is_a_union_and_stays_bounded():
    merged = supervisor.merge_history([NOW - 10, NOW - 20], [NOW - 20, NOW - 30])
    assert merged == [NOW - 30, NOW - 20, NOW - 10]
    assert len(supervisor.merge_history(list(range(100)), list(range(100)))) <= 20


def test_a_clock_that_steps_backwards_does_not_forgive_the_relaunches():
    """comp-ui-2: `0 <= now - t` made every recent relaunch invisible after
    an NTP correction or a resume that moved the wall clock back."""
    recent = [NOW + 300, NOW + 1200, NOW + 2400]   # stamps "in the future"
    assert supervisor.decide(3, _marker(), PID, recent, NOW).relaunch is False


def test_main_carries_the_history_to_the_relaunched_companion(tmp_path):
    crash = tmp_path / "crashes"
    state = tmp_path / "state"
    exe = tmp_path / "bin" / "ccsync-companion.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    crash.mkdir()
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")
    argv = supervisor.supervisor_argv(exe, PID, crash, state, prior=[NOW - 100])[1:]

    supervisor.main(argv, waiter=lambda pid: 3, pid_alive=lambda pid: False,
                    spawn=lambda *a, **k: None, sleep_fn=lambda s: None,
                    clock=lambda: NOW)

    note = json.loads((crash / supervisor.RELAUNCH_NOTE_FILENAME).read_text(encoding="utf-8"))
    assert note["attempt"] == 2
    assert note["history"] == [NOW - 100, NOW]


def test_a_history_that_cannot_be_written_is_logged_loudly(tmp_path, monkeypatch):
    crash = tmp_path / "crashes"
    state = tmp_path / "state"
    exe = tmp_path / "bin" / "ccsync-companion.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    crash.mkdir()
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")
    monkeypatch.setattr(supervisor, "write_history", lambda *a, **k: False)

    supervisor.main(supervisor.supervisor_argv(exe, PID, crash, state)[1:],
                    waiter=lambda pid: 3, pid_alive=lambda pid: False,
                    spawn=lambda *a, **k: None, sleep_fn=lambda s: None,
                    clock=lambda: NOW)

    text = (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")
    assert "could not record this relaunch" in text


def test_write_history_reports_whether_it_wrote(tmp_path):
    assert supervisor.write_history(tmp_path / "state", [NOW]) is True
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    assert supervisor.write_history(blocked / "state", [NOW]) is False


def test_start_supervisor_hands_on_the_count_it_was_relaunched_with(tmp_path, monkeypatch):
    """res-companion-4: the chain is supervisor -> companion -> supervisor,
    so the companion is the only place the count can be carried through."""
    from ccsync_companion import crash_report

    cfg = {"log_path": str(tmp_path / "companion.log")}
    crash_report._reset_for_tests()
    crash_report.note_relaunch_history([NOW - 100, NOW - 200])
    recorded: list[list[str]] = []
    monkeypatch.setattr(supervisor, "spawn_for",
                        lambda pid, exe, crash, state, **kw: recorded.append(kw.get("prior")) or object())

    crash_report.start_supervisor(cfg)

    assert recorded == [sorted([NOW - 100, NOW - 200])]
    crash_report._reset_for_tests()


# -- comp-ui-3: the doubled "FOR YOUR ADMIN" ---------------------------------


def test_the_fixer_s_could_not_save_line_is_not_garbled():
    from ccsync_companion import popup, ui_copy

    text = popup.IGNORE_FOLDER_FAILED
    assert ui_copy.DIAGNOSTICS in text
    assert "ADMINFOR YOUR ADMIN" not in text
    assert text.count("FOR YOUR ADMIN") == 1
    assert text.endswith(".")
    assert " - " in text or "-" not in text  # no em dash, and no bare hyphen run
    assert "—" not in text


# -- comp-ui-4: the (s) plurals ----------------------------------------------


def test_no_visible_string_in_the_tray_or_settings_says_s_in_brackets():
    """comp-ui-4: the UX-10 scan read app.py and popup.py only, and one of
    the exact sentences it pins lives in tray.py."""
    import ast

    src = Path(tray.__file__).resolve().parent
    for name in ("tray.py", "settings_window.py"):
        path = src / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None and isinstance(node.body[0], ast.Expr):
                    docstrings.add(id(node.body[0].value))
        logs = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "log"):
                for arg in node.args:
                    for sub in ast.walk(arg):
                        logs.add(id(sub))
        bad = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and id(n) not in docstrings and id(n) not in logs
               and "(s)" in n.value]
        assert not bad, (f"{name} still says {bad} to an editor: "
                         f"ui_copy.count(n, noun) writes a real plural.")


def test_the_unfiltered_line_counts_properly():
    line_one = tray._unfiltered_line({"folders_unfiltered": ["a"]})
    line_two = tray._unfiltered_line({"folders_unfiltered": ["a", "b"]})
    assert "1 project is not sharing yet" in line_one
    assert "2 projects are not sharing yet" in line_two
    assert "(s)" not in line_one + line_two


def test_the_quit_confirmation_counts_properly():
    assert "1 file into" in tray.quit_confirm_text({"total": 1})
    assert "12 files into" in tray.quit_confirm_text({"total": 12})
    assert "of 12 files into" in tray.quit_confirm_text({"index": 3, "total": 12})
    assert "(s)" not in tray.quit_confirm_text({"index": 3, "total": 12})


# -- comp-ui-5: the macOS Quit alert must not block the main thread ----------


def test_quit_asks_off_the_main_thread_on_macos(monkeypatch):
    """comp-ui-5: on macOS a tray action runs on the main thread, which is
    also ui_dispatch's pump."""
    spawned: list[str] = []
    monkeypatch.setattr(tray, "_spawn",
                        lambda app, label, fn: spawned.append(label))
    monkeypatch.setattr(tray.ui_dispatch, "uses_main_thread", lambda: True)
    icon = _StubIcon()
    stopped: list[bool] = []
    icon.stop = lambda: stopped.append(True)   # type: ignore[method-assign]

    tray.quit_from_menu(object(), icon)

    assert spawned == ["Quit"]
    assert stopped == [], "the confirmation must not have run inline"


def test_quit_runs_inline_where_the_pump_is_not_the_caller(monkeypatch):
    monkeypatch.setattr(tray.ui_dispatch, "uses_main_thread", lambda: False)
    monkeypatch.setattr(tray, "_confirm_quit_while_copying", lambda app: False)
    monkeypatch.setattr(tray, "_spawn",
                        lambda app, label, fn: pytest.fail("no thread here"))
    icon = _StubIcon()
    stopped: list[bool] = []
    icon.stop = lambda: stopped.append(True)   # type: ignore[method-assign]

    tray.quit_from_menu(object(), icon)

    assert stopped == [], "the editor said keep copying"


# -- comp-ui-6: a Settings window that fails half-built ----------------------


def test_a_settings_window_that_fails_mid_build_is_destroyed(monkeypatch):
    """comp-ui-6: the lock was released and the root left on screen."""
    from ccsync_companion import settings_window

    destroyed: list[str] = []

    class _Root:
        def title(self, *a):
            raise OSError("the session went away")

        def destroy(self):
            destroyed.append("destroy")

        def after_cancel(self, job):
            pass

    class _Lock:
        def __init__(self):
            self.held = False

        def acquire(self, blocking=True):
            self.held = True
            return True

        def locked(self):
            return self.held

        def release(self):
            self.held = False

    import tkinter

    # Applied AFTER conftest's _no_real_tk_windows guard, so this wins and no
    # real window is ever built.
    monkeypatch.setattr(tkinter, "Tk", lambda *a, **k: _Root())
    lock = _Lock()

    class _App:
        _popup_active_lock = lock

    # Through show_settings, because that is where the guard lives: the root
    # has to be built in the function ui_dispatch.dispatch is handed
    # (test_tk_interpreter_hygiene).
    monkeypatch.setattr(settings_window, "tray_mod", _Tray())
    settings_window.show_settings(_App())

    assert destroyed == ["destroy"], "the half-built root must not stay on screen"
    assert lock.held is False


class _Tray:
    @staticmethod
    def _notify(app, message):
        raise AssertionError("the window is what failed, not the lock")


# -- comp-ytdl-jobs-3: the ffmpeg sidecar that keeps failing ------------------


_SIDECAR_FAILING = {
    "sidecar": {"action": "failed", "consecutive_failures": 3,
                "cause": "github.com is unreachable"},
}


def test_a_failing_ffmpeg_install_reaches_the_tray_menu():
    """comp-ytdl-jobs-3: the consequence (no proxies, no fleet media work)
    is otherwise invisible, and the cause was in the log only."""
    line = tray.ytdlp_sidecar_line(_SIDECAR_FAILING)
    assert "cannot install ffmpeg" in line
    assert tray.ytdlp_sidecar_line({}) == ""
    assert tray.ytdlp_sidecar_line(None) == ""


def test_the_sidecar_line_moves_the_menu_fingerprint():
    """Otherwise it appears only when something unrelated changes, and
    lingers after the install works - UI-3's shape."""
    base = _menu_snapshot()
    with_warning = _menu_snapshot()
    with_warning["ytdlp_status"] = _SIDECAR_FAILING
    assert tray._menu_fingerprint(base) != tray._menu_fingerprint(with_warning)


def test_the_sidecar_line_is_in_the_settings_youtube_section():
    from ccsync_companion import settings_window

    snap = _menu_snapshot()
    snap["ytdl_local_downloads"] = True
    snap["ytdlp_status"] = _SIDECAR_FAILING
    sections = settings_window.build_settings_model(snap, _SettingsApp())
    texts = [getattr(item, "text", "")
             for section in sections for item in section.items]
    assert any("cannot install ffmpeg" in t for t in texts)


class _SettingsApp:
    config: dict = {}


def _menu_snapshot() -> dict:
    return {
        "statuses": [],
        "identity_label": "Signed in as owen",
        "signed_in": True,
        "paused": False,
        "problems": [],
        "setup_name": None,
        "upgrade_info": None,
        "dashboard_url": "http://nas",
        "color": "green",
        "ytdlp_status": {},
    }


# -- comp-sync-1: a safety latch that cannot write its own state -------------


_PERSIST_FAILED = {
    "lane_b_breaker": {"tripped": False, "persist_failed": True,
                       "persist_error": "could not write C:/x/lane_b_breaker.json"},
}


def test_a_latch_that_cannot_persist_gets_a_line():
    """comp-sync-1 (owed to comp-ui): a latch nobody can see saved is a
    latch a restart silently clears."""
    line = tray._persist_failed_line(_PERSIST_FAILED)
    assert line is not None
    assert "cannot save its safety state" in line
    assert "lane_b_breaker.json" in line
    # comp-ui-4 (2026-09-11b): it used to end "Restarting CCSync would clear
    # it", in the place every other BLOCKING advisory puts the remedy -- and
    # a restart is what drops the latch. It now says what a restart costs and
    # names an action the editor can take.
    assert "Restarting CCSync would clear it" not in line
    assert "COPY DIAGNOSTICS FOR YOUR ADMIN" in line
    # Absent when the disk is fine, which is how the happy path is spelled.
    assert tray._persist_failed_line({}) is None
    assert tray._persist_failed_line({"halt": {"active": True}}) is None


def test_all_three_latches_are_read_and_the_line_names_them_once():
    guard = {
        "lane_b_breaker": {"persist_failed": True, "persist_error": "e1"},
        "disk_floor": {"persist_failed": True, "persist_error": "e2"},
        "halt": {"persist_failed": True, "persist_error": "e3"},
    }
    line = tray._persist_failed_line(guard)
    assert line.count("restarting CCSync") == 1  # comp-ui-4 (2026-09-11b)
    for key in ("halt", "disk_floor"):
        assert tray._persist_failed_line({key: {"persist_failed": True,
                                                "persist_error": "e"}}) is not None


def test_the_persist_failure_does_not_move_the_menu_fingerprint():
    """comp-ui-6 (2026-09-11b): this test asserted the opposite, on a comment
    that said the line was a MENU line. It is not: `_persist_failed_line`'s
    only caller in the repo is settings_window._lane_advisories, and every
    advisory line left the tray menu. The entry bought nothing and cost a
    full _build_menu (and its HMENU teardown) on every flap. See
    test_bug_hunt_2026_09_11b_comp_ui.py."""
    for key in ("lane_b_breaker", "disk_floor", "halt"):
        assert (tray._guard_fingerprint({})
                == tray._guard_fingerprint({key: {"persist_failed": True}}))


def test_the_persist_line_is_one_of_the_settings_advisories():
    from ccsync_companion import settings_window

    entries = settings_window._lane_advisories(_PERSIST_FAILED)
    assert any("cannot save its safety state" in text for _severity, text in entries)


# -- comp-sync-4: two producers that had no caller anywhere -------------------


_SHARED = ["The shared LUT library is not reachable on this computer (P: is not mapped)"]
_REPATHS = [{"old": "2026/CCT/Old Name", "new": "2026/CCT/New Name",
             "at": "2026-09-11T09:00:00+00:00", "relinked": False}]


def test_a_broken_shared_folder_gets_a_line():
    """comp-sync-4: SYNC-101's reader was computed every pass and read by
    nothing - not the tray, not the report."""
    line = tray._shared_folders_line({"shared_folder_problems": _SHARED})
    assert line is not None and "shared LUT library" in line
    assert tray._shared_folders_line({}) is None
    assert tray._shared_folders_line({"shared_folder_problems": []}) is None


def test_a_renamed_project_folder_gets_a_line():
    """comp-sync-4 / SYNC-102: the editor's project directory moved under
    them and every clip in the open Resolve project still points at the old
    canonical path."""
    line = tray._repath_line({"repath_events": _REPATHS})
    assert line is not None
    assert "New Name" in line and "Old Name" in line
    assert tray._repath_line({}) is None
    # A repath whose clips were relinked needs no sentence.
    assert tray._repath_line(
        {"repath_events": [{**_REPATHS[0], "relinked": True}]}) is None


def test_neither_section_moves_the_menu_fingerprint():
    """comp-ui-6 (2026-09-11b): both lines are Settings-only too, and
    Settings re-renders on its own 2 s timer. Nothing about them belongs in
    the TRAY MENU's fingerprint -- least of all the sentences, which carry
    absolute paths and would rebuild the menu on every machine that has
    one."""
    base = tray._guard_fingerprint({})
    assert base == tray._guard_fingerprint({"shared_folder_problems": _SHARED})
    assert base == tray._guard_fingerprint({"repath_events": _REPATHS})
    flat = str(tray._guard_fingerprint({"shared_folder_problems": _SHARED}))
    assert "not reachable on this computer" not in flat


def test_both_sections_are_settings_advisories():
    from ccsync_companion import settings_window

    guard = {"shared_folder_problems": _SHARED, "repath_events": _REPATHS}
    texts = [t for _severity, t in settings_window._lane_advisories(guard)]
    assert any("shared LUT library" in t for t in texts)
    assert any("New Name" in t for t in texts)


def test_the_snapshot_reads_both_producers():
    """comp-sync-4: the snapshot is where a tray line gets its data, and
    neither getter had a caller there."""
    class _App:
        config: dict = {}

        def lane_statuses(self):
            return []

        def shared_folder_problems(self):
            return list(_SHARED)

        def repath_events(self):
            return [dict(e) for e in _REPATHS]

    snap = tray._tray_snapshot(_App())
    assert snap["shared_folder_problems"] == _SHARED
    assert snap["repath_events"] == _REPATHS
    # ...and they reach the guard the advisory renderers read, even on a
    # companion whose sync_guard() predates them.
    assert (snap["sync_guard"] or {}).get("shared_folder_problems") == _SHARED
    assert (snap["sync_guard"] or {}).get("repath_events") == _REPATHS
