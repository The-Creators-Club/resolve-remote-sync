"""GL-22 / GL-23 (CR-370, 2026-10-07): a build that dies at start-up rolls back,
and Quit / Restart / self-upgrade wait for teardown.

PL-RES-03 (a failed start was never counted, exit 1 was never relaunched, the
2 s hand-off grace was shorter than a onefile extraction, no step launched the
built exe) and bug-comp-ui-1 (a repeat shutdown() returned at once, so the
process exited under a daemon teardown thread that was still stopping lanes).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import app as app_mod
from ccsync_companion import crash_report, startguard, supervisor
from ccsync_companion import upgrade as upgrade_mod

REPO = Path(__file__).resolve().parents[2]


# -- GL-23: the repeat shutdown() waits --------------------------------------


def _bare_app(teardown):
    app = object.__new__(app_mod.CompanionApp)
    app._shutdown_lock = threading.Lock()
    app._shutdown_started = False
    app._shutdown_done = threading.Event()
    app._shutdown_owner = None
    app._shutdown_teardown = teardown
    return app


def test_repeat_shutdown_waits_for_the_first_teardown_on_a_worker_thread():
    gate = threading.Event()
    entered = threading.Event()
    finished = threading.Event()

    def slow_teardown():
        entered.set()
        gate.wait(10)
        finished.set()

    app = _bare_app(slow_teardown)
    worker = threading.Thread(target=app.shutdown, daemon=True)
    worker.start()
    assert entered.wait(5)

    # run()'s finally on the main thread: it used to return at once.
    result = {}

    def main_thread_finally():
        app.shutdown()
        result["teardown_finished_first"] = finished.is_set()

    waiter = threading.Thread(target=main_thread_finally, daemon=True)
    waiter.start()
    time.sleep(0.3)
    assert waiter.is_alive(), "the repeat shutdown() returned while teardown was still running"
    gate.set()
    waiter.join(5)
    worker.join(5)
    assert result == {"teardown_finished_first": True}


def test_repeat_shutdown_is_bounded(monkeypatch):
    monkeypatch.setattr(app_mod, "SHUTDOWN_WAIT_SECONDS", 0.2)
    gate = threading.Event()
    entered = threading.Event()
    app = _bare_app(lambda: (entered.set(), gate.wait(10)))
    worker = threading.Thread(target=app.shutdown, daemon=True)
    worker.start()
    assert entered.wait(5)
    started = time.monotonic()
    app.shutdown()  # a wedged teardown must not hold the process for ever
    assert time.monotonic() - started < 5
    gate.set()
    worker.join(5)


def test_reentry_on_the_teardown_thread_does_not_deadlock():
    app = _bare_app(lambda: None)
    calls = []

    def reenter():
        app.shutdown()  # e.g. a signal handler landing mid-teardown
        calls.append("reentered")

    app._shutdown_teardown = reenter
    app.shutdown()
    assert calls == ["reentered"]
    assert app._shutdown_done.is_set()


def test_done_event_is_set_even_when_teardown_raises():
    def boom():
        raise RuntimeError("teardown blew up")

    app = _bare_app(boom)
    with pytest.raises(RuntimeError):
        app.shutdown()
    assert app._shutdown_done.is_set()


def test_a_real_companion_app_carries_the_done_event_from_init():
    src = (REPO / "companion" / "src" / "ccsync_companion" / "app.py").read_text(encoding="utf-8")
    assert "self._shutdown_done = threading.Event()" in src


# -- GL-22: startguard.begin counts a start that died before the lock ----------


@pytest.fixture()
def guard_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(startguard, "state_dir_for", lambda cfg=None: state)
    monkeypatch.setattr(startguard, "_fresh_build", False)
    return state


def _prior_attempt(state, *, pid, reached_lock=False, failed=0, version=None, fresh=True):
    state.mkdir(parents=True, exist_ok=True)
    (state / startguard.ATTEMPT_FILENAME).write_text(json.dumps({
        "version": version or upgrade_mod.config_mod.VERSION, "pid": pid, "at": time.time(),
        "reached_lock": reached_lock, "failed_starts": failed, "fresh_build": fresh,
    }), encoding="utf-8")


def test_first_launch_records_an_attempt_and_is_fresh_after_an_upgrade(guard_env):
    guard_env.mkdir(parents=True)
    (guard_env / "last_version.json").write_text(
        json.dumps({"version": "0.0.1", "starts": 1, "first_start_at": time.time()}),
        encoding="utf-8")
    assert startguard.begin([]) == "ok"
    attempt = json.loads((guard_env / startguard.ATTEMPT_FILENAME).read_text(encoding="utf-8"))
    assert attempt["pid"] == os.getpid() and attempt["reached_lock"] is False
    assert startguard.fresh_build() is True


def test_flagged_reentries_are_not_a_start(guard_env):
    for flag in ("--supervise", "--music-resolve-worker", "--setup-resolve-prefs", "--self-test"):
        assert startguard.begin([flag, "1"]) == "skip"
    assert not (guard_env / startguard.ATTEMPT_FILENAME).exists()


def test_a_dead_unlocked_attempt_is_a_failed_start_but_one_is_not_enough(guard_env):
    _prior_attempt(guard_env, pid=999_999_001)
    reverted = []
    out = startguard.begin([], alive=lambda pid: False,
                           revert=lambda *a, **k: reverted.append(1) or ("0.0.1", ""))
    assert out == "ok" and not reverted
    attempt = json.loads((guard_env / startguard.ATTEMPT_FILENAME).read_text(encoding="utf-8"))
    assert attempt["failed_starts"] == 1


def test_two_dead_unlocked_attempts_restore_the_previous_build(guard_env):
    _prior_attempt(guard_env, pid=999_999_001, failed=1)
    calls = []

    def fake_revert(state_dir, cfg=None, **kw):
        calls.append(state_dir)
        return "0.0.1", ""

    assert startguard.begin([], alive=lambda pid: False, revert=fake_revert) == "reverted"
    assert calls == [guard_env]


def test_a_refused_revert_starts_normally_and_says_why(guard_env):
    _prior_attempt(guard_env, pid=999_999_001, failed=1)
    out = startguard.begin([], alive=lambda pid: False,
                           revert=lambda *a, **k: ("", "there is no rollback copy"))
    assert out == "ok"
    assert "there is no rollback copy" in (guard_env / "startguard.log").read_text(encoding="utf-8")


def test_a_live_or_locked_previous_attempt_is_never_counted(guard_env):
    _prior_attempt(guard_env, pid=4242)  # a second copy still starting up
    startguard.begin([], alive=lambda pid: True)
    attempt = json.loads((guard_env / startguard.ATTEMPT_FILENAME).read_text(encoding="utf-8"))
    assert attempt["failed_starts"] == 0
    _prior_attempt(guard_env, pid=4242, reached_lock=True)  # a normal earlier run
    startguard.begin([], alive=lambda pid: False)
    attempt = json.loads((guard_env / startguard.ATTEMPT_FILENAME).read_text(encoding="utf-8"))
    assert attempt["failed_starts"] == 0


def test_reached_lock_does_not_clear_the_count_but_mark_booted_does(guard_env):
    startguard.begin([])
    path = guard_env / startguard.ATTEMPT_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["failed_starts"] = 1
    path.write_text(json.dumps(data), encoding="utf-8")
    startguard.reached_lock()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["reached_lock"] is True and data["failed_starts"] == 1
    startguard.mark_booted()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["booted"] is True and data["failed_starts"] == 0


def test_a_build_dying_in_init_after_the_lock_rolls_back(guard_env):
    """CR-370 / GL-22 overseer defect 2: lock reached, never booted, dead."""
    reverts = []

    def revert(state, cfg):
        reverts.append(1)
        return True, ""

    results = []
    for _ in range(3):
        results.append(startguard.begin([], alive=lambda pid: False, revert=revert,
                                        cfg={}, version="9.9.9"))
        startguard.reached_lock()  # passes the lock, then dies in __init__
        # the next launch must carry a different pid for the "dead" test
        path = guard_env / startguard.ATTEMPT_FILENAME
        d = json.loads(path.read_text(encoding="utf-8"))
        d["pid"] = 999999
        path.write_text(json.dumps(d), encoding="utf-8")
    assert reverts, results
    assert results[-1] == "reverted" or "reverted" in results


def test_a_duplicate_that_lost_the_lock_is_not_counted(guard_env):
    startguard.begin([], alive=lambda pid: False, version="9.9.9")
    startguard.reached_lock(got_lock=False)
    path = guard_env / startguard.ATTEMPT_FILENAME
    d = json.loads(path.read_text(encoding="utf-8"))
    d["pid"] = 999999
    path.write_text(json.dumps(d), encoding="utf-8")
    startguard.begin([], alive=lambda pid: False, version="9.9.9")
    assert json.loads(path.read_text(encoding="utf-8"))["failed_starts"] == 0


def test_a_booted_attempt_is_never_counted(guard_env):
    startguard.begin([], alive=lambda pid: False, version="9.9.9")
    startguard.reached_lock()
    startguard.mark_booted()
    path = guard_env / startguard.ATTEMPT_FILENAME
    d = json.loads(path.read_text(encoding="utf-8"))
    d["pid"] = 999999
    path.write_text(json.dumps(d), encoding="utf-8")
    startguard.begin([], alive=lambda pid: False, version="9.9.9")
    assert json.loads(path.read_text(encoding="utf-8"))["failed_starts"] == 0


def test_begin_never_raises(monkeypatch):
    def boom(cfg=None):
        raise OSError("no state dir")

    monkeypatch.setattr(startguard, "state_dir_for", boom)
    assert startguard.begin([]) == "ok"


def test_the_entry_points_call_begin_before_importing_the_app():
    for rel in ("companion/launcher.py", "companion/src/ccsync_companion/__main__.py"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert text.index("startguard") < text.index("app import run"), rel
        assert "--self-test" in text, rel


# -- GL-22: the "started" marker and the hand-off wait ---------------------------


class _Child:
    def __init__(self, pid, die_at=None, clock=None):
        self.pid = pid
        self._die_at = die_at
        self._clock = clock

    def poll(self):
        if self._die_at is not None and self._clock() >= self._die_at:
            return 1
        return None


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def test_handoff_waits_past_the_old_two_second_grace_for_the_started_marker(tmp_path):
    clock = _Clock()
    child = _Child(777, die_at=10.0, clock=clock)  # dies at import, well after 2 s
    code = upgrade_mod.watch_child_takeover(child, {}, clock, clock.sleep, state_dir=tmp_path)
    assert code == 1


def test_handoff_ends_on_the_started_marker(tmp_path):
    clock = _Clock()
    child = _Child(777)
    seen = []

    def sleeper(seconds):
        clock.sleep(seconds)
        if clock.t >= 5.0 and not seen:
            seen.append(1)
            (tmp_path / startguard.HANDOFF_FILENAME).write_text(
                json.dumps({"pid": 777}), encoding="utf-8")

    assert upgrade_mod.watch_child_takeover(child, {}, clock, sleeper, state_dir=tmp_path) is None
    assert 5.0 <= clock.t < upgrade_mod.HANDOFF_STARTED_WAIT_SECONDS


def test_onefile_marker_with_other_pid_but_ppid_equal_to_popen_pid_counts(tmp_path):
    """PyInstaller onefile: Popen.pid is the bootloader, the marker's pid is the
    Python child and its ppid is the bootloader (measured 2026-10-07)."""
    (tmp_path / startguard.HANDOFF_FILENAME).write_text(
        json.dumps({"pid": 57416, "ppid": 777}), encoding="utf-8")
    clock = _Clock()
    assert upgrade_mod.watch_child_takeover(
        _Child(777), {}, clock, clock.sleep, state_dir=tmp_path) is None
    assert clock.t < 5.0


def test_another_pids_marker_does_not_count(tmp_path):
    (tmp_path / startguard.HANDOFF_FILENAME).write_text(json.dumps({"pid": 1}), encoding="utf-8")
    clock = _Clock()
    assert upgrade_mod.watch_child_takeover(
        _Child(777), {}, clock, clock.sleep, state_dir=tmp_path) is None
    assert clock.t >= upgrade_mod.HANDOFF_STARTED_WAIT_SECONDS


def test_a_child_without_a_pid_keeps_the_legacy_grace():
    clock = _Clock()

    class NoPid:
        @staticmethod
        def poll():
            return None

    assert upgrade_mod.watch_child_takeover(NoPid(), {}, clock, clock.sleep) is None
    assert clock.t == pytest.approx(upgrade_mod.CHILD_TAKEOVER_GRACE_SECONDS, abs=0.2)


def test_note_started_names_this_pid(guard_env):
    assert startguard.note_started() is True
    assert startguard.read_started(guard_env)["pid"] == os.getpid()
    assert startguard.read_started(guard_env)["ppid"] == os.getppid()


def test_module_run_writes_the_marker_before_the_single_instance_wait():
    text = (REPO / "companion" / "src" / "ccsync_companion" / "app.py").read_text(encoding="utf-8")
    body = text[text.index("\ndef run() -> None:"):]
    assert body.index("startguard.note_started(cfg)") < body.index("acquire_single_instance()")
    assert body.index("startguard.reached_lock(cfg, got_lock)") > body.index("acquire_single_instance()")


# -- GL-22: the supervisor relaunches a just-upgraded build that never booted ----


def _marker(pid=50, **extra):
    base = {"pid": pid, "version": "9.9.9", supervisor.MARKER_FRESH_KEY: True,
            supervisor.MARKER_BOOTED_KEY: False}
    base.update(extra)
    return base


def test_exit_one_of_an_unbooted_fresh_build_is_relaunched():
    d = supervisor.decide(1, _marker(), 50, [], 1000.0)
    assert d.relaunch and "before it finished starting" in d.reason


def test_macos_exiting_stamp_of_an_unbooted_fresh_build_is_relaunched():
    d = supervisor.decide(None, _marker(**{supervisor.MARKER_EXITING_KEY: True}), 50, [], 1000.0)
    assert d.relaunch


def test_a_booted_or_old_build_exit_one_is_still_deliberate():
    assert not supervisor.decide(1, _marker(**{supervisor.MARKER_BOOTED_KEY: True}), 50, [], 1.0).relaunch
    assert not supervisor.decide(1, _marker(**{supervisor.MARKER_FRESH_KEY: False}), 50, [], 1.0).relaunch
    assert not supervisor.decide(1, {"pid": 50}, 50, [], 1.0).relaunch  # a pre-GL-22 marker


def test_no_marker_after_a_quit_means_no_relaunch_even_when_fresh():
    assert not supervisor.decide(1, None, 50, [], 1.0).relaunch


def test_the_startup_relaunch_keeps_the_three_an_hour_ceiling():
    now = 10_000.0
    d = supervisor.decide(1, _marker(), 50, [now - 60, now - 120, now - 180], now)
    assert not d.relaunch and "cannot stay up" in d.reason


def test_the_run_marker_carries_the_flags_and_mark_booted_flips_one(tmp_path, monkeypatch):
    cfg = {"log_path": str(tmp_path / "companion.log")}
    monkeypatch.setattr(startguard, "_fresh_build", True)
    crash_report.write_run_marker(cfg)
    marker = json.loads(crash_report.run_marker_path(cfg).read_text(encoding="utf-8"))
    assert marker[supervisor.MARKER_FRESH_KEY] is True
    assert marker[supervisor.MARKER_BOOTED_KEY] is False
    crash_report.mark_booted(cfg)
    marker = json.loads(crash_report.run_marker_path(cfg).read_text(encoding="utf-8"))
    assert marker[supervisor.MARKER_BOOTED_KEY] is True


def test_app_marks_booted_just_before_the_main_loop():
    text = (REPO / "companion" / "src" / "ccsync_companion" / "app.py").read_text(encoding="utf-8")
    assert text.index("crash_report.mark_booted(self.config)") < text.index(
        "dispatcher.serve(self._stop_event)")


# -- GL-22: --self-test ----------------------------------------------------------


def test_self_test_passes_on_the_real_package(tmp_path):
    out = tmp_path / "result.txt"
    assert startguard.self_test(["--self-test", "--self-test-out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("SELF-TEST OK")


def test_self_test_fails_when_a_module_cannot_import(tmp_path, monkeypatch):
    pkg = tmp_path / "brokenpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "app.py").write_text("raise ImportError('a frozen module is missing')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    out = tmp_path / "result.txt"
    assert startguard.self_test(["--self-test", "--self-test-out", str(out)],
                                package="brokenpkg") == 2
    assert "frozen module is missing" in out.read_text(encoding="utf-8")


# -- GL-22: the release steps launch what they built ------------------------------


def test_every_release_script_launches_the_built_binary():
    ps1 = (REPO / "tools" / "release.ps1").read_text(encoding="utf-8")
    sh = (REPO / "tools" / "release_macos.sh").read_text(encoding="utf-8")
    assert "--self-test" in ps1 and "NOT signing or writing a manifest" in ps1
    assert ps1.index("Start-Process -FilePath $ExePath") < ps1.index("-File $SignScript")
    assert '"$ARTIFACT" --self-test' in sh
    assert sh.index('"$ARTIFACT" --self-test') < sh.index('codesign --force --sign "$CCSYNC_APPLE_DEV_ID"')


def test_a_handoff_child_never_counts_records_or_reverts(guard_env, monkeypatch):
    """GL-22 round 2 (CR-370, 2026-10-07): v1 applies a v2 that dies at import and
    rolls back itself, then retries v2 on its backoff. Three hand-off launches
    must not count, rewrite last_version.json or revert: the spawner owns it."""
    guard_env.mkdir(parents=True)
    version_file = guard_env / "last_version.json"
    version_file.write_text(json.dumps({"version": "1.0.0", "starts": 3,
                                        "first_start_at": time.time()}), encoding="utf-8")
    before = version_file.read_text(encoding="utf-8")
    monkeypatch.setenv("CCSYNC_REPLACES_PID", "4242")
    reverts = []
    path = guard_env / startguard.ATTEMPT_FILENAME
    for _ in range(3):
        out = startguard.begin([], alive=lambda pid: pid == 4242,
                               revert=lambda *a, **k: reverts.append(1) or (True, ""),
                               cfg={}, version="9.9.9")
        assert out == "ok"
        d = json.loads(path.read_text(encoding="utf-8"))
        assert d["failed_starts"] == 0 and d["handoff_child"] is True
        d["pid"] = 999999  # it died at import; the next attempt is another process
        path.write_text(json.dumps(d), encoding="utf-8")
    assert not reverts
    assert version_file.read_text(encoding="utf-8") == before


def test_a_dead_handoff_child_with_a_live_spawner_is_not_counted(guard_env, monkeypatch):
    monkeypatch.delenv("CCSYNC_REPLACES_PID", raising=False)
    guard_env.mkdir(parents=True)
    (guard_env / startguard.ATTEMPT_FILENAME).write_text(json.dumps({
        "version": "9.9.9", "pid": 999999, "reached_lock": False, "handoff_child": True,
        "spawner": 4242, "failed_starts": 0, "fresh_build": True}), encoding="utf-8")
    startguard.begin([], alive=lambda pid: pid == 4242, version="9.9.9")
    d = json.loads((guard_env / startguard.ATTEMPT_FILENAME).read_text(encoding="utf-8"))
    assert d["failed_starts"] == 0


def test_a_handoff_child_dead_after_the_lock_reverts_on_the_third_launch(guard_env, monkeypatch):
    """GL-22 round 2 overseer (CR-370, 2026-10-07): the hand-off child reached the
    lock and died after its spawner exited; two supervisor (plain) relaunches
    follow. The revert must fire on launch 3, not 4."""
    guard_env.mkdir(parents=True)
    (guard_env / "last_version.json").write_text(json.dumps({
        "version": "1.0.0", "starts": 3, "first_start_at": time.time()}), encoding="utf-8")
    path = guard_env / startguard.ATTEMPT_FILENAME
    reverts = []
    alive = lambda pid: False  # noqa: E731 - spawner and every dead child are gone
    revert = lambda *a, **k: reverts.append(1) or (True, "")  # noqa: E731

    def die_after_lock():
        d = json.loads(path.read_text(encoding="utf-8"))
        d["reached_lock"] = True
        d["pid"] = 999000 + len(reverts) + int(d.get("at", 0)) % 7
        path.write_text(json.dumps(d), encoding="utf-8")

    monkeypatch.setenv("CCSYNC_REPLACES_PID", "4242")
    assert startguard.begin([], alive=lambda p: p == 4242, revert=revert, cfg={},
                            version="9.9.9") == "ok"  # launch 1: hand-off child
    die_after_lock()
    monkeypatch.delenv("CCSYNC_REPLACES_PID")
    assert startguard.begin([], alive=alive, revert=revert, cfg={}, version="9.9.9") == "ok"
    die_after_lock()  # launch 2: counted once
    assert not reverts
    out = startguard.begin([], alive=alive, revert=revert, cfg={}, version="9.9.9")
    assert out == "reverted" and len(reverts) == 1  # launch 3
