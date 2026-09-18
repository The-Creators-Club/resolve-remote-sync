"""CR-295 (2026-09-18b mediums): a child that spawns a child is stopped whole.

comp-music-ytdl-jobs-1 (the whisper worker behind pipeline.py) and
comp-music-ytdl-jobs-3 (the merge ffmpeg behind yt-dlp) are the same defect:
`proc.terminate()` / `proc.kill()` on the one pid we know about, which on
Windows does not cascade and on POSIX cleans nothing up. These tests pin the
shared helper and both call sites through it.
"""

from __future__ import annotations

import signal
import subprocess

from ccsync_companion import jobs_runner, proc_tree, ytdl_executor


class FakeProc:
    def __init__(self, pid=4242, alive=True):
        self.pid = pid
        self._alive = alive
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False

    def wait(self, timeout=None):
        return 0


def test_spawn_kwargs_puts_the_child_in_its_own_group(monkeypatch):
    monkeypatch.setattr(proc_tree, "IS_WINDOWS", True)
    flags = proc_tree.spawn_kwargs(0x08000000)["creationflags"]
    assert flags & 0x08000000                      # the caller's CREATE_NO_WINDOW survives
    # 0x200 literally: `subprocess.CREATE_NEW_PROCESS_GROUP` does not exist on
    # the macOS release runner, and the point is that the WINDOWS value goes in.
    assert flags & 0x200
    assert proc_tree.CREATE_NEW_PROCESS_GROUP == 0x200

    monkeypatch.setattr(proc_tree, "IS_WINDOWS", False)
    kw = proc_tree.spawn_kwargs(0)
    assert kw["start_new_session"] is True


def test_kill_tree_takes_the_whole_tree_down_on_windows(monkeypatch):
    monkeypatch.setattr(proc_tree, "IS_WINDOWS", True)
    calls = []
    proc = FakeProc(pid=9191)
    proc_tree.kill_tree(proc, runner=lambda argv, **kw: calls.append(argv))
    assert calls == [["taskkill", "/T", "/F", "/PID", "9191"]]
    assert proc.terminated                          # and the old single stop still runs


def test_kill_tree_signals_the_group_on_posix(monkeypatch):
    monkeypatch.setattr(proc_tree, "IS_WINDOWS", False)
    sent = []
    monkeypatch.setattr(proc_tree.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(proc_tree.os, "killpg",
                        lambda pgid, sig: sent.append((pgid, sig)), raising=False)
    proc_tree.kill_tree(FakeProc(pid=777))
    assert sent == [(777, signal.SIGTERM)]


def test_kill_tree_never_aims_an_os_kill_at_a_fake_pid(monkeypatch):
    """Every jobs test injects a fake runner; a fake proc with no real pid
    must not raise here, and must not reach taskkill."""
    monkeypatch.setattr(proc_tree, "IS_WINDOWS", True)
    calls = []

    class NoPid:
        pid = None

        def terminate(self):
            raise OSError("gone")

        def kill(self):
            calls.append("kill")

        def wait(self, timeout=None):
            return 0

    proc_tree.kill_tree(NoPid(), runner=lambda *a, **k: calls.append("taskkill"))
    assert calls == ["kill"]


def test_jobs_runner_terminate_goes_through_the_tree_kill(monkeypatch):
    """comp-music-ytdl-jobs-1: the whisper worker outlives a terminate() on
    pipeline.py, so _terminate must be the tree kill."""
    seen = []
    monkeypatch.setattr(proc_tree, "kill_tree",
                        lambda proc, **kw: seen.append(proc))
    proc = FakeProc()
    jobs_runner._terminate(proc)
    assert seen == [proc]
    assert not proc.terminated                      # the helper's job now, not this one's


def test_ytdl_executor_kill_proc_goes_through_the_tree_kill(monkeypatch):
    """comp-music-ytdl-jobs-3: yt-dlp's merge ffmpeg survived proc.kill()."""
    seen = []
    monkeypatch.setattr(proc_tree, "kill_tree",
                        lambda proc, **kw: seen.append(proc))
    job = ytdl_executor.DownloadJob.__new__(ytdl_executor.DownloadJob)
    import threading
    job._lock = threading.Lock()
    job._proc = FakeProc()
    job._kill_proc()
    assert seen == [job._proc]


def test_whisper_child_is_spawned_in_its_own_group(monkeypatch):
    """The spawn half: without a group there is nothing for the POSIX kill to
    signal, and the Windows taskkill has no tree to walk."""
    captured = {}

    def runner(argv, **kwargs):
        captured.update(kwargs)
        raise OSError("not actually spawning")

    r = jobs_runner.JobRunner.__new__(jobs_runner.JobRunner)
    r._runner = runner
    r._run_child(1, ["python", "pipeline.py"])
    if proc_tree.IS_WINDOWS:
        assert captured["creationflags"] & int(subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        assert captured["start_new_session"] is True
