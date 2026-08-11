"""Launch the Blackmagic Proxy Generator for the clips ffmpeg cannot touch.

proxy_gen encodes everything ffmpeg can decode and deliberately never queues
BRAW/R3D/CRM: ffmpeg cannot decode them at any quality, and promising a proxy
this machine cannot make is worse than reporting the gap. BPG is the answer for
those, and until now "the answer" meant remembering to open it -- which is why
the base rig sat with 6 BRAW clips unproxied while BPG had not run since 00:41
that morning (2026-08-10).

Three facts shape everything here, all established on the base rig:

  1. BPG IS RESOLVE. The Start-menu entry is a shortcut to
     `Resolve.exe -pg`, not a separate binary. So "is BPG running" cannot be
     answered by process NAME -- plain Resolve and BPG are the same image, and
     only the command line separates them.
  2. It is a WATCHER, not a job runner. It takes no file arguments; it scans
     the folders in its own INI (`watchFolderList`, `P:\\Projects` here) and
     picks up whatever lacks a proxy. So this module never says WHAT to
     encode -- it only decides WHEN the watcher should be up. Which is enough:
     by the time it runs, ffmpeg has already taken every clip it could, so
     what remains for BPG is exactly the BRAW.
  3. Its INI is read at startup and owned by the user. This module does NOT
     write it. Narrowing watchFolderList to the projects with BRAW gaps was
     the obvious way to say "only these clips", and it would silently redefine
     what a MANUAL launch does later -- a config the user set, changed behind
     their back, for a run they did not ask about.

Sequencing, per the design this was asked for: BPG starts only once the ffmpeg
queue is EMPTY, so the two never encode at the same time. Running it alongside
an open Resolve is explicitly allowed (they are the same engine and it
self-throttles), unlike the ffmpeg path's optional Resolve gate.

Nothing here ever kills it. The ffmpeg child is safe to kill because proxy_gen
writes `<stem>.mp4.partial` and only ever os.replaces onto a name that does not
exist -- an interrupted encode leaves nothing behind. BPG's write behaviour is
its own and unobserved, and lane B would happily fan out a truncated proxy, so
a started BPG is left to finish. That is the conservative half of the contract:
we choose when it starts, never when it stops.
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Union

log = logging.getLogger("ccsync.bpg")

# `-pg` is the whole difference between the proxy generator and the editor.
BPG_FLAG = "-pg"

# Where Resolve installs on Windows. The Start-menu .lnk points here; reading
# the shortcut would need COM for no gain, since the install path is fixed.
WINDOWS_RESOLVE_EXE = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"

# Don't retry a launch more often than this. If BPG exits immediately -- no
# licence, a dialog, an install that has moved -- a tick-rate relaunch would
# spawn Resolve every 15 seconds for as long as the gap exists.
RELAUNCH_COOLDOWN_SECONDS = 1800

# The CIM probe is a PowerShell spawn, and the gate asks on every 15 s tick for
# as long as a BRAW gap exists: the launcher's cheap short-circuit only covers
# a BPG *we* started, so an editor who opened it from the Start menu paid a
# PowerShell per tick (MED-9, 2026-08-11). TTL-cached on
# resolve_bridge._PROBE_TTL_SECONDS' precedent. Longer than that one because
# the answer only decides whether to start a SECOND generator, and the
# 30-minute relaunch cooldown is the real backstop against a launch storm.
_PROBE_TTL_SECONDS = 60.0
_PROBE_LOCK = threading.Lock()
_probe_cache: Optional[tuple[float, Optional[list[str]]]] = None


def _reset_probe_cache() -> None:
    """Forget the cached process list. For tests, and for a launch we just made."""
    global _probe_cache
    with _PROBE_LOCK:
        _probe_cache = None


def find_bpg_command(configured: str = "") -> Optional[list[str]]:
    """The argv that starts the proxy generator, or None.

    Windows only, on purpose: BRAW, BPG and the base rig are all Windows here,
    and inventing a macOS path that has never been run would be a guess
    presented as support.
    """
    if configured:
        exe = Path(configured).expanduser()
        return [str(exe), BPG_FLAG] if exe.is_file() else None
    if platform.system() != "Windows":
        return None
    exe = Path(WINDOWS_RESOLVE_EXE)
    return [str(exe), BPG_FLAG] if exe.is_file() else None


def _cim_command_lines() -> Optional[list[str]]:
    """Command lines of every running Resolve.exe, or None if we cannot tell.

    tasklist cannot do this -- it reports image names, and BPG's image name is
    Resolve.exe like the editor's. None means "unknown", which callers treat
    as "not running" rather than blocking a launch: the cost of a wrong launch
    is Resolve focusing a window it already has open, and the cost of a wrong
    "already running" is the BRAW gap never closing.
    """
    global _probe_cache
    if platform.system() != "Windows":
        return None
    with _PROBE_LOCK:
        cached = _probe_cache
        if cached is not None and (time.monotonic() - cached[0]) < _PROBE_TTL_SECONDS:
            return cached[1]
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='Resolve.exe'\" "
             "| ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        log.debug("bpg: could not read Resolve command lines", exc_info=True)
        lines = None
    else:
        lines = (
            None if out.returncode != 0
            else [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        )
    # A failed read is cached too: it means the same as an empty one to every
    # caller, and re-spawning PowerShell every 15 s to be told nothing again is
    # the cost this cache exists to remove.
    with _PROBE_LOCK:
        _probe_cache = (time.monotonic(), lines)
    return lines


def is_bpg_running(command_lines_fn: Callable[[], Optional[list[str]]] = _cim_command_lines) -> bool:
    """Is a Resolve running in proxy-generator mode?

    Matched on the `-pg` argument, since the image name is shared with the
    editor. An unreadable process list is reported as NOT running -- see
    _cim_command_lines.
    """
    lines = command_lines_fn()
    if not lines:
        return False
    return any(BPG_FLAG in line.split() for line in lines)


class BpgLauncher:
    """Starts BPG when, and only when, the ffmpeg queue has nothing left.

    Every collaborator is injectable for the same reason proxy_gen's are: the
    real ones start a video application.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        generation_enabled: bool,
        clock: Callable[[], float],
        spawn: Optional[Callable[[list[str]], Any]] = None,
        running_fn: Optional[Callable[[], bool]] = None,
        command: Optional[list[str]] = None,
    ) -> None:
        self.command = command if command is not None else find_bpg_command(
            str(cfg.get("bpg_path", "") or "").strip()
        )
        # Tri-state, exactly like proxy_gen_enabled: an explicit value wins,
        # and the derivation is "wherever this machine already generates
        # proxies AND has something to launch". A machine with no Resolve
        # installed derives False rather than logging a failure every tick.
        value = cfg.get("bpg_enabled")
        if isinstance(value, bool):
            self.enabled = value
        else:
            if value is not None:
                log.error("config: bpg_enabled=%r is not true/false -- deriving it", value)
            self.enabled = bool(generation_enabled and self.command)
        self._clock = clock
        self._spawn = spawn if spawn is not None else _spawn_detached
        self._running_fn = running_fn if running_fn is not None else is_bpg_running
        self._last_launch_at: Optional[float] = None
        self._child: Any = None

    def _child_alive(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def maybe_launch(self, *, queue_empty: bool, needs_resolve: int,
                     user_away: Union[bool, Callable[[], bool]]) -> Optional[str]:
        """Start BPG if this is the moment. Returns a reason when it did not.

        Order is not only what gets logged any more: every condition below is
        required, and the two EXPENSIVE ones (the caller's idle probe, which
        forks ioreg on macOS, and our own PowerShell process probe) are asked
        last, after the cheap ones have already ruled the tick out (MED-8/MED-9,
        2026-08-11). `user_away` accepts a callable for exactly that reason.
        """
        if not self.enabled:
            return "disabled"
        if not self.command:
            return "no proxy generator installed"
        if needs_resolve <= 0:
            return "nothing needs BPG"
        if not queue_empty:
            # The whole point of the sequencing: two encoders on one GPU.
            return "ffmpeg still has clips queued"
        if not (user_away() if callable(user_away) else user_away):
            return "user is at the keyboard"
        if self._child_alive():
            # Free: a poll() on a handle we hold. Kept ahead of the cooldown so
            # a running BPG of ours is still reported as one.
            return "already running"
        now = self._clock()
        # The COOLDOWN before the process probe, not after: inside it the
        # probe's answer cannot change the outcome, and the probe is a
        # PowerShell spawn (MED-9).
        if (self._last_launch_at is not None
                and (now - self._last_launch_at) < RELAUNCH_COOLDOWN_SECONDS):
            return "launched too recently"
        if self._running_fn():
            return "already running"
        try:
            self._child = self._spawn(self.command)
        except Exception:
            # Non-fatal like every other thing in this feature: the clips stay
            # in the report as needing BPG, which is what they were before.
            log.exception("bpg: could not start %s", " ".join(self.command))
            self._last_launch_at = now      # don't retry in a tight loop
            return "launch failed"
        self._last_launch_at = now
        # A BPG we just started must not be masked by a process list read
        # before it existed -- the cache is a cost saver, not a state.
        _reset_probe_cache()
        log.info(
            "bpg: started the Blackmagic Proxy Generator for %d clip(s) ffmpeg "
            "cannot decode -- it watches its own folder list and is never "
            "stopped by us", needs_resolve,
        )
        return None


def _spawn_detached(command: list[str]) -> Any:
    """Start BPG so it outlives the companion.

    DETACHED_PROCESS: the companion is a tray app an editor quits, and a proxy
    run halfway through a 40-minute BRAW clip must not die with it.
    """
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
        cwd=os.path.dirname(command[0]) or None,
    )
