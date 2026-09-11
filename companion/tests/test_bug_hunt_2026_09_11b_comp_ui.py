"""Regression tests for the 2026-09-11b bug hunt, comp-ui territory (CR-251).

This hunt was OF the CR-233..248 fix pass, so most of these pin a fix that
landed half of itself: an Explorer-restart re-add that inherited the startup
backoff and the terminal "stop the refresh loops" verdict, a relaunch ceiling
that counts each relaunch twice, and copy that names the wrong remedy.

Nothing here builds a real Tk root, touches a real tray or calls Resolve: the
Windows icon is driven through `_Win32.get()` and the `on_register_failure`
hook, and the Settings window through a stubbed `ui_dispatch.dispatch`, as
conftest's `_no_real_tk_windows` guard requires. Nothing here is Windows-only
in what it imports (`ctypes.get_last_error` is stubbed for the macOS release
runner).
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path

import pytest

from ccsync_companion import popup, settings_window, supervisor, tray, tray_native


# -- the Windows icon doubles ------------------------------------------------


class _Shell:
    """Shell_NotifyIconW that refuses NIM_ADD `fail` times, then accepts."""

    def __init__(self, fail: int) -> None:
        self.fail = fail
        self.calls = 0

    def Shell_NotifyIconW(self, action, data):  # noqa: N802 - the Win32 name
        self.calls += 1
        return 0 if self.calls <= self.fail else 1


class _Nid(ctypes.Structure):
    """Enough of NOTIFYICONDATAW for byref() to accept it."""

    _fields_ = [("uFlags", ctypes.c_uint), ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p), ("szTip", ctypes.c_wchar * 128)]


class _User32:
    @staticmethod
    def DefWindowProcW(*a):  # noqa: N802 - the Win32 name
        raise AssertionError("the TaskbarCreated branch must handle the message")


class _Api:
    def __init__(self, shell) -> None:
        self.shell32 = shell
        self.user32 = _User32()


def _windows_icon(monkeypatch, shell, slept):
    icon = tray_native._WindowsIcon("ccsync", None, "starting")
    monkeypatch.setattr(icon, "_nid", lambda: _Nid())
    monkeypatch.setattr(icon, "_icon_handle", lambda: 0)
    monkeypatch.setattr(tray_native._Win32, "get", staticmethod(lambda: _Api(shell)))
    monkeypatch.setattr("time.sleep", slept.append)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    return icon


# -- comp-ui-1 / regression-7 ------------------------------------------------


class _App:
    config: dict = {}

    def _notify_tray(self, *a, **k):
        raise AssertionError("the tray is exactly what is broken here")


def test_a_failed_explorer_re_add_does_not_kill_the_refresh_loops(monkeypatch, tmp_path):
    """comp-ui-1: an Explorer restart is recoverable and the loops are not.

    `_ccsync_stop` means "this icon is dead, stop refreshing it" and nothing
    clears it; a later TaskbarCreated broadcast re-adds the icon, and the
    editor then has a tray whose colour, tooltip and menu are frozen at the
    moment of the failure - green while dead.
    """
    slept: list[float] = []
    icon = _windows_icon(monkeypatch, _Shell(fail=10_000), slept)
    app = _App()
    app.config = {"log_path": str(tmp_path / "companion.log")}
    icon.on_register_failure = (
        lambda detail, fatal=True: tray._report_windows_icon_failure(
            app, icon, detail, fatal=fatal))
    icon._taskbar_created_msg = 0xC123
    icon._added = True

    assert icon._on_message(0, 0xC123, 0, 0) == 0

    assert icon._register_error, "the diagnostic still has to be recorded"
    assert getattr(icon, "_ccsync_stop", False) is False, (
        "a recoverable re-add failure must leave the refresh and pulse loops "
        "running: the next TaskbarCreated can still succeed")


def test_a_first_registration_that_never_succeeds_still_stops_the_loops(
        monkeypatch, tmp_path):
    """comp-ui-1: run()'s arm is terminal - the pump is dead there."""
    slept: list[float] = []
    icon = _windows_icon(monkeypatch, _Shell(fail=10_000), slept)
    monkeypatch.setattr(icon, "_create_window", lambda: None)
    monkeypatch.setattr(icon, "_pump", lambda: None)
    app = _App()
    app.config = {"log_path": str(tmp_path / "companion.log")}
    icon.on_register_failure = (
        lambda detail, fatal=True: tray._report_windows_icon_failure(
            app, icon, detail, fatal=fatal))

    icon.run()

    assert icon.registered is False
    assert getattr(icon, "_ccsync_stop", False) is True


def test_the_failure_hook_takes_a_one_argument_callable(monkeypatch, tmp_path):
    """comp-ui-1: `fatal` is optional on the hook, so a hook written against
    the older signature (every caller outside this package) still works."""
    seen: list[str] = []
    icon = tray_native._WindowsIcon("ccsync", None, "starting")
    icon.on_register_failure = seen.append

    icon._announce_failure("boom", fatal=False)

    assert seen == ["boom"]


# -- comp-ui-2 / regression-16 -----------------------------------------------


def test_the_explorer_re_add_keeps_the_short_schedule(monkeypatch):
    """comp-ui-2: `_add_icon` runs on the PUMP thread for a re-add.

    The comment above `_NIM_ADD_STARTUP_ATTEMPTS` promises the re-add keeps
    the flat schedule "where a two-minute sleep would freeze the tray"; only
    the attempt COUNT stayed short, and the inherited backoff blocked the
    window procedure for 15.5 s - no menu, no quit, no NIM_MODIFY.
    """
    slept: list[float] = []
    icon = _windows_icon(monkeypatch, _Shell(fail=10_000), slept)
    icon.on_register_failure = None
    icon._taskbar_created_msg = 0xC123

    # Through the real call site: the TaskbarCreated branch of the window
    # procedure, which is what runs on the pump thread.
    assert icon._on_message(0, 0xC123, 0, 0) == 0

    assert sum(slept) <= 3.0, (
        "the re-add blocks the message pump for as long as it sleeps")
    # The startup path is the one allowed to back off, and still does.
    startup: list[float] = []
    icon2 = _windows_icon(monkeypatch, _Shell(fail=10_000), startup)
    monkeypatch.setattr(icon2, "_create_window", lambda: None)
    monkeypatch.setattr(icon2, "_pump", lambda: None)
    icon2.run()
    assert sum(startup) > 60.0


# -- comp-ui-3: the relaunch ceiling counts each relaunch once ----------------


PID = 4242
# Deliberately NOT an exactly representable "%.3f" value: every supervisor
# test used 1_700_000_000.0, which round-trips through supervisor_argv
# unchanged and hid this entirely.
NOW = 1_700_000_000.123456


def _marker(pid: int = PID) -> dict:
    return {"pid": pid, "version": "0.9.71", "started": "2026-09-11T10:00:00"}


def test_a_relaunch_is_counted_once_not_once_per_source():
    """comp-ui-3: the file keeps full `time.time()` precision and the argv
    copy is truncated to milliseconds, so the union of the two sources held
    two floats per relaunch and the ceiling fired after two of three."""
    history = [NOW - 300.000777]
    argv = supervisor.supervisor_argv(
        Path("x.exe"), PID, Path("c"), Path("s"), prior=history)
    prior = supervisor._parse(argv[1:])["prior"]

    merged = supervisor.merge_history(history, prior)

    assert len(merged) == 1, "one relaunch, two spellings of the same stamp"


def test_the_ceiling_still_allows_three_relaunches_through_the_whole_chain():
    """comp-ui-3: the chain is supervisor -> companion -> supervisor, and
    every hop doubled the count, so MAX_RELAUNCHES was reached on the second
    relaunch and `note["attempt"]` said "3 of 3" on it."""
    history: list[float] = []
    now = NOW
    relaunches = 0
    for _ in range(supervisor.MAX_RELAUNCHES + 1):
        decision = supervisor.decide(-1073741819, _marker(), PID, history, now)
        if not decision.relaunch:
            break
        relaunches += 1
        history = supervisor.merge_history(history, [now])
        # The relaunched companion hands the count back on argv, truncated.
        argv = supervisor.supervisor_argv(
            Path("x.exe"), PID, Path("c"), Path("s"), prior=history)
        history = supervisor.merge_history(
            history, supervisor._parse(argv[1:])["prior"])
        now += 1.000111

    assert relaunches == supervisor.MAX_RELAUNCHES


# -- regression-12 / res-companion-3: the interrupted self-upgrade ------------


def test_the_supervisor_puts_a_half_swapped_exe_back(tmp_path, monkeypatch):
    """res-companion-3: a self-upgrade killed between the two os.replace
    calls leaves no `ccsync-companion.exe`, only `<exe>.old`. The supervisor
    is the one awake process outside the companion; it used to log "nothing
    to relaunch" and exit, and the machine synced nothing until a human
    renamed the file."""
    crash = tmp_path / "crashes"
    state = tmp_path / "state"
    crash.mkdir()
    exe = tmp_path / "ccsync-companion.exe"
    old = tmp_path / "ccsync-companion.exe.old"
    old.write_bytes(b"the previous build")
    (crash / "running.marker").write_text('{"pid": %d}' % PID, encoding="utf-8")
    spawned: list = []

    class _Child:
        pid = 99

    rc = supervisor.main(
        [supervisor.FLAG, str(PID), "--exe", str(exe),
         "--crash-dir", str(crash), "--state-dir", str(state)],
        waiter=lambda pid: -1073741819,
        pid_alive=lambda pid: False,
        spawn=lambda argv, cwd, env: (spawned.append(argv), _Child())[1],
        sleep_fn=lambda s: None,
        clock=lambda: NOW,
    )

    assert rc == 0
    assert exe.is_file() and exe.read_bytes() == b"the previous build"
    assert not old.exists()
    assert spawned and spawned[0][0] == str(exe)


def test_the_restore_never_touches_a_live_exe(tmp_path):
    """The rename must only ever fill a HOLE: an `.old` beside a companion
    that is on disk is the ordinary post-upgrade state (cleanup_old_exe
    deletes it on the next start) and renaming over it would downgrade the
    machine."""
    exe = tmp_path / "ccsync-companion.exe"
    exe.write_bytes(b"the current build")
    (tmp_path / "ccsync-companion.exe.old").write_bytes(b"the previous build")

    assert supervisor.restore_interrupted_upgrade(exe, lambda msg: None) is False
    assert exe.read_bytes() == b"the current build"


# -- regression-21: the relaunch note is a file too ---------------------------


def test_a_relaunch_note_that_cannot_be_written_says_so(tmp_path):
    """regression-21: `merge_history`'s "second source that does not need a
    filesystem" reaches the relaunched companion only through this file, and
    it was written with a bare `pass` and a plain write_text - so a directory
    where `relaunched.json` cannot be written lost the ceiling silently."""
    crash = tmp_path / "crashes"
    crash.mkdir()
    (crash / supervisor.RELAUNCH_NOTE_FILENAME).mkdir()

    assert supervisor.write_relaunch_note(crash, {"attempt": 1}) is False
    # And the happy path still round-trips.
    ok_dir = tmp_path / "ok"
    assert supervisor.write_relaunch_note(ok_dir, {"attempt": 2}) is True
    assert supervisor.read_relaunch_note(ok_dir)["attempt"] == 2


# -- comp-ui-4: the copy names an action the editor can take ------------------


_PERSIST_FAILED = {
    "lane_b_breaker": {"tripped": True, "persist_failed": True,
                       "persist_error": "could not write C:/x/lane_b_breaker.json"},
}


def test_the_persist_failure_line_does_not_recommend_a_restart():
    """comp-ui-4: "Restarting CCSync would clear it" sits where every other
    BLOCKING advisory puts the remedy, and a restart is exactly what drops
    the latch this line exists to protect (docs/SYNC_SAFETY.md: only a human
    clears one)."""
    line = tray._persist_failed_line(_PERSIST_FAILED)

    assert line is not None
    assert "cannot save its safety state" in line
    assert "lane_b_breaker.json" in line
    assert "Restarting CCSync would clear it" not in line
    assert "COPY DIAGNOSTICS FOR YOUR ADMIN" in line
    assert " -- " not in line and "\u2014" not in line


# -- comp-ui-5: the Quit confirmation ----------------------------------------


def test_the_quit_confirmation_reads_as_english_with_no_batch_total():
    """comp-ui-5: popup's progress publisher coerces a missing `total` to 0,
    and the comp-ui-4 plural pass left the two halves joined as "CCSync is
    copying file 3 files in." - at the one moment the product is asking the
    editor to make a careful choice."""
    text = tray.quit_confirm_text({"index": 3, "total": 0})

    assert "files in." not in text
    assert "(s)" not in text
    # The known-total sentences are unchanged.
    assert "of 12 files into" in tray.quit_confirm_text({"index": 3, "total": 12})
    assert "1 file into" in tray.quit_confirm_text({"total": 1})


# -- comp-ui-6: the tray MENU fingerprint ------------------------------------


_SHARED = ["The shared LUT library is not reachable on this computer (P: is not mapped)"]
_REPATHS = [{"old": "2026/CCT/Old Name", "new": "2026/CCT/New Name",
             "at": "2026-09-11T09:00:00+00:00", "relinked": False}]


def test_settings_only_advisories_do_not_rebuild_the_tray_menu():
    """comp-ui-6: `_persist_failed_line`, `_shared_folders_line` and
    `_repath_line` have exactly one caller in the repo,
    settings_window._lane_advisories; every advisory line left the tray menu
    (tray.py's _build_menu comment). Their entries in `_guard_fingerprint`
    bought nothing and cost a full _build_menu plus HMENU teardown whenever
    a repath list or a persist flag moved."""
    base = tray._guard_fingerprint({})

    assert base == tray._guard_fingerprint(
        {"lane_b_breaker": {"persist_failed": True}})
    assert base == tray._guard_fingerprint({"shared_folder_problems": _SHARED})
    assert base == tray._guard_fingerprint({"repath_events": _REPATHS})
    # The things that ARE menu lines still move it.
    assert base != tray._guard_fingerprint(
        {"lane_b_breaker": {"tripped": True, "reason": "too many deletions"}})


# -- comp-ui-7: the Settings lock --------------------------------------------


class _CountingLock:
    def __init__(self) -> None:
        self.held = False
        self.releases = 0

    def acquire(self, blocking=True):
        self.held = True
        return True

    def locked(self):
        return self.held

    def release(self):
        self.releases += 1
        self.held = False


def test_show_settings_never_releases_a_lock_another_window_took(monkeypatch):
    """comp-ui-7: `threading.Lock.locked()` has no owner. The comp-ui-6 fix
    gave the inner path its own release, so a failed build released the lock
    and show_settings' handler released it AGAIN - and whoever took it in
    between (a second Settings click, the watcher's popup) now runs beside a
    third tk.Tk root, which is the CR-93 shape."""
    from ccsync_companion import ui_dispatch

    lock = _CountingLock()

    def _boom(app, held_lock, closer):
        def _close():
            # What _release_and_close does, then the race: another window
            # takes the lock in the microseconds before the handler runs.
            held_lock.release()
            held_lock.acquire()

        closer[0] = _close
        raise RuntimeError("the display went away mid-build")

    monkeypatch.setattr(settings_window, "_build_settings_window", _boom)
    monkeypatch.setattr(ui_dispatch, "dispatch", lambda fn: fn())

    class _StubApp:
        _popup_active_lock = lock

    settings_window.show_settings(_StubApp())

    assert lock.releases == 1, "the second release belongs to another window"
    assert lock.held is True


# -- comp-resolve-b-1: FIX ALL must not count a rehearsal as bytes copied -----


def test_fix_all_credits_no_bytes_for_a_rehearsal(tmp_path, monkeypatch):
    """comp-resolve-b-1: `fixer_dry_run` (RES-15) answers
    {"ok": True, "dry_run": True} and copies nothing. comp-resolve-2 taught
    run_consolidation, count_copied and app.py's toast that; the FIX ALL loop
    every editor actually presses still did `if outcome.get("ok"):
    batch_done += file_total`, so the bar filled at full speed and the ETA
    read off nonsense on the one run whose entire purpose is a trustworthy
    screen."""
    src = tmp_path / "A001_C003.mov"
    src.write_bytes(b"x" * 4096)
    rows = [{"file_path": str(src), "suggested_dest": "2026/CCT/Media",
             "clip_name": "A001_C003.mov", "media_pool_items": []}]
    monkeypatch.setattr(popup.fixer, "is_placeholder", lambda path: False)
    published: list[dict] = []

    results = popup.perform_fix_all(
        rows, {}, str(tmp_path),
        fix_clip_fn=lambda *a, **k: {"ok": True, "dry_run": True,
                                     "message": "rehearsal"},
        state_fn=published.append,
    )

    assert results[0]["dry_run"] is True
    final = published[-1]
    assert final["batch_bytes_done"] == 0, "nothing was copied"
    assert final["fixed"] == 0
    assert final["rehearsal"] == 1
    assert final["failed"] == 0
    # A real copy is still counted.
    published.clear()
    popup.perform_fix_all(
        rows, {}, str(tmp_path),
        fix_clip_fn=lambda *a, **k: {"ok": True},
        state_fn=published.append,
    )
    assert published[-1]["batch_bytes_done"] == 4096
    assert published[-1]["fixed"] == 1
    assert published[-1]["rehearsal"] == 0


# ============================================================================
# Hand-off wave (2026-09-11b): comp-app's owed repair button, and tests-5's
# "drive the PUBLIC entry point" for the persist-failed line.
# ============================================================================


class _SettingsApp:
    """Enough app for build_settings_model's THIS COMPUTER section."""

    config: dict = {}

    def effective_mode(self) -> str:
        return "editor"


def _computer_snapshot() -> dict:
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
        "ytdl_local_downloads": False,
        "ytdlp_status": {},
    }


def _this_computer(monkeypatch, unreadable: bool):
    from ccsync_companion import machine as machine_mod

    monkeypatch.setattr(machine_mod, "machine_id_unreadable",
                        lambda *a, **k: unreadable)
    sections = settings_window.build_settings_model(
        _computer_snapshot(), _SettingsApp())
    section = next(s for s in sections if s.title == "THIS COMPUTER")
    return section.items


def test_an_unreadable_id_file_gets_a_repair_button_in_settings(monkeypatch):
    """comp-app-8's owed half. comp-app-5 was right to stop re-minting over a
    machine.json it cannot read and left the condition NO EXIT: `machine_id()`
    answered "" for ever, the reporter cached that, and the loss showed only
    when somebody renamed the computer. comp-app-8 added the accessor, the
    repair and a once-per-process tray line; the button a human presses is
    this one."""
    items = _this_computer(monkeypatch, unreadable=True)
    labels = [getattr(item, "label", "") for item in items]
    texts = [getattr(item, "text", "") for item in items]

    assert "GIVE THIS COMPUTER A NEW ID" in labels
    warning = next(t for t in texts if "id file" in t)
    assert "cannot recognise this computer again if you rename it" in warning
    assert "Syncing is not affected" in warning
    assert "—" not in warning and "(s)" not in warning


def test_a_readable_id_file_offers_nothing(monkeypatch):
    """CONTROL: the button is an answer to a fault, not furniture. A healthy
    machine.json must never be offered a new id - `remint` refuses a file it
    can read, and a button that can only say "nothing changed" teaches
    editors to press it."""
    items = _this_computer(monkeypatch, unreadable=False)
    assert "GIVE THIS COMPUTER A NEW ID" not in [
        getattr(item, "label", "") for item in items]


def test_an_id_check_that_raises_does_not_cost_the_whole_settings_window(monkeypatch):
    """The check runs on the window's 2 s refresh timer. `machine_id_unreadable`
    never raises today; the model builder must not depend on that."""
    from ccsync_companion import machine as machine_mod

    def _boom(*a, **k):
        raise OSError("the state directory went away")

    monkeypatch.setattr(machine_mod, "machine_id_unreadable", _boom)
    sections = settings_window.build_settings_model(
        _computer_snapshot(), _SettingsApp())

    assert [s.title for s in sections][0] == "THIS COMPUTER"
    assert settings_window.machine_id_unreadable() is False


def _repair(monkeypatch, confirm: bool, minted: str = "abc123"):
    """Drive action_repair_machine_id through tray._spawn, inline."""
    from ccsync_companion import machine as machine_mod
    from ccsync_companion import popup as popup_mod

    calls = {"confirm": 0, "remint": 0}
    notices: list[str] = []

    def _confirm(title, body, ok_label="PROCEED"):
        calls["confirm"] += 1
        calls["body"] = body
        calls["ok_label"] = ok_label
        return confirm

    def _remint(*a, **k):
        calls["remint"] += 1
        return minted

    monkeypatch.setattr(popup_mod, "confirm_dialog", _confirm)
    monkeypatch.setattr(machine_mod, "remint", _remint)
    monkeypatch.setattr(tray, "_spawn", lambda app, label, fn: fn())
    monkeypatch.setattr(tray, "_notify", lambda app, msg: notices.append(msg))
    settings_window.action_repair_machine_id(_SettingsApp())
    return calls, notices


def test_the_repair_asks_first_and_never_reminds_on_a_cancel(monkeypatch):
    """An id change is the one act here that cannot be undone from inside the
    product: the old id is only in the bytes remint sets aside. A cancel must
    reach `remint` not at all."""
    calls, notices = _repair(monkeypatch, confirm=False)

    assert calls["confirm"] == 1
    assert calls["remint"] == 0
    assert notices == []


def test_the_repair_reminds_and_says_so(monkeypatch):
    calls, notices = _repair(monkeypatch, confirm=True)

    assert calls["remint"] == 1
    assert notices and "new id" in notices[0]
    assert "—" not in notices[0]
    # The dialog says what is kept: the unreadable bytes may hold an id an
    # admin can still recover by hand.
    assert "keep the unreadable file beside it" in calls["body"]


def test_a_repair_that_changed_nothing_does_not_render_as_done(monkeypatch):
    """`remint` answers "" when the new file could not be written, and the id
    it already has when the file became readable in between. Neither is
    "done" (the CR-233 "could not check must never render as OK" rule)."""
    _calls, notices = _repair(monkeypatch, confirm=True, minted="")

    assert notices and "did not change" in notices[0]


def test_the_persist_failure_line_reaches_the_settings_window(monkeypatch):
    """tests-5: every assertion about this line went through
    `tray._persist_failed_line` directly, so a fix that kept the helper and
    stopped calling it - the shape tests-5 names - was invisible. This one
    drives the public entry point, `settings_window._lane_advisories`, which
    is the ONLY caller in the repo and what build_settings_model renders.

    Ranked too: comp-sync-1 tagged it BLOCKING because the latch it warns
    about is one a restart silently drops, and SYNC-118's cap can only hide
    it if the tier is wrong."""
    entries = settings_window._lane_advisories(_PERSIST_FAILED)
    severities = {text: severity for severity, text in entries}
    line = next((t for t in severities if "cannot save its safety state" in t),
                None)

    assert line is not None, "the producer is no longer called from Settings"
    assert severities[line] == settings_window.BLOCKING
    lines, _hidden = settings_window.rank_advisories(entries, show_all=False)
    assert any("cannot save its safety state" in item.text for item in lines), (
        "a BLOCKING advisory cannot be one the cap hides")
