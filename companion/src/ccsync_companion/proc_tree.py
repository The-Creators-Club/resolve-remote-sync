"""Stopping a child that is itself a parent.

WHY THIS EXISTS (comp-music-ytdl-jobs-1 / -3, 2026-09-18b mediums). Two of the
companion's children spawn children of their own, and both were stopped with
`Popen.terminate()` / `Popen.kill()` on the single pid we know about:

  * `jobs_runner._run_child` runs the whisper venv's `pipeline.py transcribe`,
    and that process is NOT the worker -- `whisper_corpus.run_worker` Popens a
    second process, which is the one that loads the model and holds the VRAM.
    A cancel, a fleet halt or a tray quit reported the job stopped within a
    heartbeat and left the worker running on the GPU, so the machine went back
    to idle and could claim the next whisper job onto the same card. A fleet
    halt is a safety latch (docs/SYNC_SAFETY.md); one that does not stop the
    work it names is the worst shape we have.
  * `ytdl_executor` runs yt-dlp with `--ffmpeg-location` and a
    `bestvideo+bestaudio` selector, so essentially every download ends in an
    ffmpeg merge. Killing yt-dlp alone leaves that merge holding handles on
    the `.part` and the output, which is what `clear_partials` /
    `clear_aside_originals` then fail on (MEDIA-2's symptom, one process out).

THE FLAG ALONE IS NOT THE FIX. `CREATE_NEW_PROCESS_GROUP` changes nothing
about `Popen.terminate()`, which still calls TerminateProcess on one pid, and
TerminateProcess does not cascade; the companion's existing users of that flag
pass it to DETACH a child, the opposite intent. What works is the shape
`onboarding`'s `terminate_bootstrap` already uses and KNOWN_BUGS records:
`taskkill /T /F /PID` on Windows, `os.killpg` elsewhere. The group flag /
`start_new_session` is still wanted, because it is what gives the POSIX half a
group to signal and what keeps a Ctrl-C in a dev console from racing us.

The helper is shared rather than copied for the fourth time: `spawn_kwargs()`
at the Popen, `kill_tree()` wherever the old code said `terminate()`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.proc_tree")

IS_WINDOWS = os.name == "nt"


def spawn_kwargs(creationflags: int = 0) -> dict[str, Any]:
    """The Popen kwargs that make a child the head of its own group.

    `creationflags` is the caller's existing flags (CREATE_NO_WINDOW, in both
    call sites) and is preserved, not replaced. On POSIX `creationflags=0` is
    accepted by Popen and means nothing, so the two branches keep the same
    call shape.
    """
    flags = 0
    try:
        flags = int(creationflags or 0)
    except Exception:                                               # noqa: BLE001
        flags = 0
    if IS_WINDOWS:
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return {"creationflags": flags}
    return {"creationflags": flags, "start_new_session": True}


def _pid_of(proc: Any) -> Optional[int]:
    """The child's pid, or None for anything we must not aim an OS kill at.

    Test fakes stand in for a real Popen all over this suite; a fake with no
    pid (or a Mock for one) must not make the kill path raise, and must never
    reach `taskkill`.
    """
    try:
        pid = getattr(proc, "pid", None)
        if isinstance(pid, bool) or not isinstance(pid, int):
            return None
        return pid if pid > 0 else None
    except Exception:                                               # noqa: BLE001
        return None


def _exited(proc: Any) -> bool:
    try:
        return proc.poll() is not None
    except Exception:                                               # noqa: BLE001
        return False


def _taskkill(pid: int, runner: Optional[Callable[..., Any]]) -> None:
    run = runner or subprocess.run
    try:
        run(["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=20,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
    except Exception:                                               # noqa: BLE001
        log.debug("proc_tree: taskkill on pid %s did not run", pid, exc_info=True)


def _killpg(pid: int, sig: int) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except Exception:                                               # noqa: BLE001
        log.debug("proc_tree: could not signal the group of pid %s", pid,
                  exc_info=True)


def kill_tree(proc: Any, *, timeout: float = 10.0,
              runner: Optional[Callable[..., Any]] = None) -> None:
    """Stop `proc` AND anything it spawned, and do not hang waiting for it.

    Every failure is swallowed on purpose: this is reached from a cancel, a
    fleet halt and a shutdown, and a raise there would leave the caller
    reporting nothing at all. The plain terminate/kill always runs afterwards
    so a fake proc (and a platform where the tree kill could not run) still
    gets the pre-2026-09-18 behaviour.
    """
    pid = _pid_of(proc)
    if pid is not None and not _exited(proc):
        if IS_WINDOWS:
            _taskkill(pid, runner)
        else:
            _killpg(pid, signal.SIGTERM)
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
        return
    except Exception:                                               # noqa: BLE001
        pass
    if pid is not None and not IS_WINDOWS:
        _killpg(pid, signal.SIGKILL)
    try:
        proc.kill()
    except Exception:                                               # noqa: BLE001
        log.debug("proc_tree: could not kill the child", exc_info=True)
    try:
        proc.wait(timeout=5)
    except Exception:                                               # noqa: BLE001
        pass
