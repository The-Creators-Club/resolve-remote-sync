"""Keeps the local Syncthing daemon alive, because nothing else does.

SYNC-17 (2026-08-18). An editor's Windows session ended at 00:53: rclone was
killed with DBG_TERMINATE_PROCESS and Syncthing logged "Syncthing is being
stopped / Exiting". The companion came back at 18:24 (autostart, then a
self-upgrade). Syncthing did NOT, and stayed dead for eighteen hours, because
the only thing that ever starts it is the HKCU Run key -- which fires at
LOGON and never again. For those eighteen hours the companion logged
`repath: local syncthing unreachable` at DEBUG once a pass and reported lane C
as idle and green with 12 GB unsynced behind it.

Nothing supervises Syncthing on an editor machine. This module is that
supervisor, and it is deliberately the smallest thing that could be: it does
not install Syncthing, does not manage its config, and does not own its
lifetime. It notices that the local REST API has been unreachable for a while
and re-runs the launcher THIS platform's installer already registered --
`%LOCALAPPDATA%\\ccsync\\bin\\CCSyncSyncthing.vbs` on Windows (the same shim
the Run key executes, so a supervised start and a logon start are the same
command line), `launchctl kickstart -k gui/<uid>/com.ccsync.syncthing` on
macOS.

Four properties this could not be shipped without:

  * IT NEVER LOOPS HOT. 30 s of unreachability before the first attempt, then
    exponential backoff (30 s, 1 m, 2 m, ... capped at 10 m). A machine where
    Syncthing genuinely cannot start costs six log lines an hour, not a
    restart storm.
  * IT RESPECTS THE LATCHES. An editor who halted syncing, or paused it, is
    not fought by a background thread that keeps resurrecting the sync engine.
    The refusal is logged with its reason, once per edge.
  * ITS STATE SURVIVES A RESTART (`~/.ccsync/state/syncthing_supervisor.json`).
    A counter that resets when the tray restarts is not a counter -- the
    companion self-upgrades, and a three-strike rule that never reaches three
    would tell nobody anything. Same reason lane_guard.py persists.
  * IT CANNOT BE THE REASON A LANE DIES. Every entry point is
    never-raise; the launch itself goes through an injectable seam so no test
    ever spawns a real process.

The lane C half of the fix lives in syncthing_lane.py: while the API is
unreachable the lane is `error` carrying one of the sentences below, so
"idle, green, 0 queued" is not a state lane C can reach with the sync engine
dead.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .. import site as site_mod

log = logging.getLogger("ccsync.sync.supervisor")

STATE_FILENAME = "syncthing_supervisor.json"

# How long the API must have been unreachable before anything is started. A
# Syncthing that is merely restarting (an upgrade, a config commit) is back
# well inside this, and the lane polls every 15 s, so this is two or three
# ticks of evidence rather than one.
GRACE_SECONDS = 30.0
# 30 s, 1 m, 2 m, 4 m, 8 m, 10 m, 10 m ... -- the delay BEFORE attempt n+1.
BACKOFF_START_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 600.0
# Failed attempts before the log turns from INFO to WARNING and the editor
# gets told. Three is "this is not a transient", not "this is unusual".
FAILURES_BEFORE_WARNING = 3
# After launching, how long to keep asking the API before calling the attempt
# a failure. Syncthing's REST listener is up within a couple of seconds on a
# warm config; 20 s covers a cold one on a slow disk.
API_WAIT_SECONDS = 20.0
API_WAIT_POLL_SECONDS = 2.0

# Written by installer/windows_bootstrap.ps1 (Register-HiddenRunEntry) beside
# the companion exe; the .vbs runs the .cmd through cmd /c with window style
# 0, which is what keeps a console from flashing on every logon.
WINDOWS_LAUNCHER_NAME = "CCSyncSyncthing.vbs"
# installer/macos_bootstrap.sh's LaunchAgent. The legacy com.creatorsclub.*
# label is deliberately NOT supported here: an installer that writes the new
# label boots out and deletes the old pair (CR-16), so a machine carrying only
# the legacy agent is one no current installer has ever touched.
MACOS_LAUNCHD_LABEL = "com.ccsync.syncthing"

# The editor-facing sentences. They are lane C's `last_error`, which is also
# what the tray line renders verbatim (tray.classify_lane_error passes
# anything naming the sync engine straight through) and what the dashboard
# chip shows. "Syncthing" is in parentheses on purpose: an editor knows the
# thing in their tray by neither name, and the log/diagnostics use the real
# one.
LANE_ERROR_RESTARTING = (
    "the sync engine (Syncthing) is not running on this machine -- restarting it"
)
BALLOON_RESTARTED = "Sync engine was not running: restarted it"


def lane_error_failed(why: str) -> str:
    return f"the sync engine (Syncthing) could not be started: {why}"


def lane_error_not_restarted(why: str) -> str:
    """The third form, for a machine where restarting it would be wrong.

    A halted or paused editor whose Syncthing is down is still a lane C
    ERROR -- 12 GB is still not moving -- but telling them it is being
    restarted while the supervisor deliberately stands off would be a lie the
    next tray line contradicts."""
    return (
        "the sync engine (Syncthing) is not running on this machine, and it is "
        f"not being restarted: {why}"
    )


def balloon_failed(why: str) -> str:
    return f"Sync engine will not start: {why}"


def last_line(text: Any, limit: int = 200) -> str:
    """The last non-blank line of a launcher's stderr, bounded.

    The whole point of the three-strike balloon is that it names the actual
    obstacle ("Could not find service", "Load failed: 5: Input/output error"),
    and launchctl writes that on the last line. Bounded because it reaches a
    Windows balloon, which silently truncates anything long.

    Decodes bytes rather than str()-ing them: subprocess hands back bytes
    unless text=True, and str(b"...") is the literal "b'...'", which is what
    an editor would then have read in the balloon."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", "replace")
    lines = [ln.strip() for ln in str(text or "").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    return lines[-1][:limit]


def supervision_enabled(cfg: Optional[dict]) -> bool:
    """The kill switch, default ON.

    The companion's config.toml is FLAT -- every other knob is a top-level
    key -- so `supervise_syncthing = false` is the spelling that matches the
    file. A `[sync]` table is read too, and only because the feature was
    specified that way: an operator who writes the documented-elsewhere form
    must not silently get a supervisor they asked to turn off. Anything
    unparseable leaves it enabled: this is a safety device, and the failure
    direction for "I cannot read your setting" is to keep supervising."""
    cfg = cfg or {}
    value = cfg.get("supervise_syncthing")
    if value is None:
        section = cfg.get("sync")
        if isinstance(section, dict):
            value = section.get("supervise_syncthing")
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def windows_launcher_path() -> Path:
    base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(base) / "ccsync" / "bin" / WINDOWS_LAUNCHER_NAME


def macos_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LAUNCHD_LABEL}.plist"


class SyncthingLauncher:
    """Starts the daemon the way THIS machine's installer registered it.

    `spawn` is the seam: subprocess.Popen in production, a recorder in every
    test. Nothing in this class decides WHETHER to start Syncthing -- that is
    SyncthingSupervisor's job -- so it can be exercised on its own for the one
    property that matters, which is that the Windows child is detached from
    the companion. A Syncthing started as an ordinary child dies with the tray
    (and with the tray's self-upgrade), which would make this whole module a
    slower way of arriving at the same eighteen hours.
    """

    def __init__(
        self,
        spawn: Optional[Callable[..., Any]] = None,
        system: Optional[str] = None,
        launcher_path: Optional[Path] = None,
        uid_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        self._spawn = spawn or subprocess.Popen
        self.system = str(system or sys.platform)
        self._launcher_path = Path(launcher_path) if launcher_path else None
        self._uid_fn = uid_fn or (lambda: int(getattr(os, "getuid", lambda: 0)()))

    # -- what we would run ---------------------------------------------
    @property
    def launcher_path(self) -> Optional[Path]:
        if self._launcher_path is not None:
            return self._launcher_path
        if self.system == "win32":
            return windows_launcher_path()
        if self.system == "darwin":
            return macos_agent_path()
        return None

    def command(self) -> Optional[list[str]]:
        """The argv, or None on a platform with no registered launcher.

        Windows runs the SAME shim the Run key runs, through wscript, so a
        supervised start and a logon start are byte-identical command lines --
        including the Syncthing home, which lives in the .cmd beside the .vbs
        and is the one thing a hand-rolled `syncthing serve` here would get
        wrong. //B suppresses the script host's error dialogs: a broken shim
        must reach the log, never a modal box on an editor's desktop mid-edit.
        """
        path = self.launcher_path
        if self.system == "win32":
            return ["wscript.exe", "//B", "//Nologo", str(path)]
        if self.system == "darwin":
            # kickstart, not `launchctl start`: -k restarts a service stuck in
            # a half-loaded state, and kickstart is the only verb that works
            # against an agent already bootstrapped into the GUI domain.
            return ["launchctl", "kickstart", "-k",
                    f"gui/{self._uid_fn()}/{MACOS_LAUNCHD_LABEL}"]
        return None

    def available(self) -> bool:
        """Whether there is anything to run. Never raises."""
        path = self.launcher_path
        if path is None:
            return False
        try:
            return Path(path).exists()
        except OSError:
            return False

    def missing_reason(self) -> str:
        path = self.launcher_path
        if path is None:
            return f"there is no registered sync engine launcher for {self.system}"
        return (
            f"the sync engine launcher is missing ({path}). Ask your admin to "
            "re-run the CC Sync installer on this machine."
        )

    # -- the launch ------------------------------------------------------
    def launch(self) -> tuple[bool, str]:
        """Start it. Returns (started, error) and never raises.

        (True, "") means the launcher was executed, NOT that Syncthing is up:
        on Windows there is nothing to read back (see below), so the only
        honest confirmation is the API answering, which the supervisor checks.
        """
        argv = self.command()
        if argv is None:
            return False, self.missing_reason()
        if self.system == "darwin":
            return self._launch_capturing(argv)
        return self._launch_detached(argv)

    def _launch_detached(self, argv: list[str]) -> tuple[bool, str]:
        """Windows. DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, no console.

        Both flags are load-bearing and for different reasons: without
        DETACHED_PROCESS the child inherits this process's console (and, in a
        frozen windowed build, Windows allocates a fresh one that flashes on
        the editor's screen), and without a new process group a Ctrl-Break
        delivered to the companion's group would take the sync engine down
        with it. close_fds and DEVNULL on all three handles complete the
        decoupling: an inherited handle keeps a pipe alive in the child, which
        is how a "detached" process still dies with its parent's console.
        """
        kwargs: dict[str, Any] = {
            "close_fds": True,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if self.system == "win32":
            kwargs["creationflags"] = detached_creationflags()
        else:
            # POSIX has no creationflags at all (passing one raises); setsid
            # is the equivalent decoupling. Only reachable on a platform with
            # an explicit launcher_path, since command() returns None
            # otherwise.
            kwargs["start_new_session"] = True
        try:
            self._spawn(argv, **kwargs)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return True, ""

    def _launch_capturing(self, argv: list[str]) -> tuple[bool, str]:
        """macOS. launchctl is a short-lived command whose STDERR is the
        diagnosis ("Could not find service ..."), so this one is waited on --
        the daemon itself is launchd's child, not ours."""
        try:
            proc = self._spawn(
                argv, close_fds=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        try:
            out, err = proc.communicate(timeout=API_WAIT_SECONDS)
        except Exception as exc:
            # A launchctl that will not return is not a launchctl worth
            # waiting for; kill it rather than hold the lane C poll thread.
            try:
                proc.kill()
            except Exception:
                pass
            return False, f"{type(exc).__name__}: {exc}"
        code = getattr(proc, "returncode", 0) or 0
        if code:
            detail = last_line(err) or last_line(out) or f"launchctl exited {code}"
            return False, detail
        return True, ""


def detached_creationflags() -> int:
    """DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, resolved defensively.

    The constants only exist on Windows builds of `subprocess`, and this
    module is imported on macOS too -- getattr with the documented literals so
    an import can never be the thing that breaks a Mac companion."""
    detached = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    new_group = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
    return detached | new_group


class SyncthingSupervisor:
    """Restarts a dead local Syncthing, at most as often as it should be.

    Driven from lane C's poll (`SyncthingLane.check_once` -> `tick`), which
    already knows whether 127.0.0.1:8384 answered and is the only thread in
    the companion that asks. Every collaborator is injected so the state
    machine can be tested without a clock, a process or a network:

      `launcher`   -- SyncthingLauncher (itself seamed on spawn)
      `notify`     -- app._notify_tray
      `suppressed` -- returns the reason supervision must stand off, or ""
      `probe`      -- "is the API answering NOW?", for the post-launch wait
      `clock`      -- WALL clock, not monotonic: the incident outlives the
                      process, and a monotonic timestamp means nothing to the
                      next one.
    """

    def __init__(
        self,
        state_path: Path,
        cfg: Optional[dict] = None,
        launcher: Optional[SyncthingLauncher] = None,
        notify: Optional[Callable[[str, str], None]] = None,
        suppressed: Optional[Callable[[], str]] = None,
        probe: Optional[Callable[[], bool]] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        grace_seconds: float = GRACE_SECONDS,
        api_wait_seconds: float = API_WAIT_SECONDS,
    ) -> None:
        self.state_path = Path(state_path)
        self.enabled = supervision_enabled(cfg)
        self.launcher = launcher or SyncthingLauncher()
        self._notify = notify
        self._suppressed = suppressed
        # Public: the lane hands its own ping in after construction (the
        # supervisor exists before the lanes do -- see app._build_lanes).
        self.probe = probe
        self._clock = clock
        self._sleep = sleep
        self.grace_seconds = float(grace_seconds)
        self.api_wait_seconds = float(api_wait_seconds)
        self._lock = threading.RLock()
        # Log-once flags for the standing-off states; in memory on purpose,
        # so a restart re-states the reason exactly once and a long halt does
        # not write a line every 15 s.
        self._logged_suppression = ""
        self._logged_disabled = False
        state = self._read_state()
        self._since: float = _as_float(state.get("since"))
        self._attempts: int = _as_int(state.get("attempts"))
        self._last_error: str = str(state.get("last_error") or "")
        self._last_attempt: float = _as_float(state.get("last_attempt"))
        self._warned = bool(state.get("warned"))
        # An attempt whose launcher ran but whose outcome is not known yet --
        # only reachable with no `probe` wired. Persisted with the rest: an
        # attempt made just before a self-upgrade must still be able to become
        # a FAILURE in the next process, or a machine that restarts the
        # companion often never reaches three strikes and never warns anyone.
        self._pending_confirm = bool(state.get("pending_confirm"))
        # A launch is running on SOME thread right now. In memory on purpose:
        # it guards one process's threads against each other, and a companion
        # that died mid-launch left no launch running (comp-lane-c-5).
        self._launching = False

    # -- persistence ----------------------------------------------------
    def _read_state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _persist_locked(self) -> None:
        payload = {
            "since": self._since or None,
            "since_at": _iso(self._since),
            "attempts": self._attempts,
            "last_error": self._last_error or None,
            "last_attempt": self._last_attempt or None,
            "last_attempt_at": _iso(self._last_attempt),
            "warned": self._warned,
            "pending_confirm": self._pending_confirm,
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("supervisor: could not persist %s: %s", self.state_path, exc)

    def _clear_state_file(self) -> None:
        try:
            self.state_path.unlink(missing_ok=True)
        except OSError:
            pass

    # -- what the rest of the companion reads ---------------------------
    @property
    def incident_open(self) -> bool:
        with self._lock:
            return bool(self._since)

    @property
    def attempts(self) -> int:
        with self._lock:
            return self._attempts

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def lane_error(self) -> Optional[str]:
        """Lane C's `last_error` while the API is unreachable, or None.

        Never "idle": whatever the supervisor is or is not doing, an
        unreachable API means lane C is carrying nothing, and the one thing
        this incident proved is that a green chip over a dead sync engine is
        worse than no chip at all."""
        with self._lock:
            if not self._since:
                return None
            attempts = self._attempts
            error = self._last_error
        if not self.enabled:
            return lane_error_not_restarted(
                "automatic restarts are switched off on this machine "
                "(supervise_syncthing = false)"
            )
        reason = self._suppression_reason()
        if reason:
            return lane_error_not_restarted(reason)
        if attempts >= FAILURES_BEFORE_WARNING and error:
            return lane_error_failed(error)
        return LANE_ERROR_RESTARTING

    def report(self) -> dict[str, Any]:
        """The `sync_guard.syncthing_supervisor` report section, or {} when
        there is nothing wrong. Empty-when-healthy on purpose: the dashboard
        reads an absent section as "the sync engine is up", and a zeroed one
        would need a second field to say the same thing."""
        with self._lock:
            if not self._since:
                return {}
            return {
                "down_since": _iso(self._since),
                "attempts": self._attempts,
                "last_error": self._last_error or None,
                "last_attempt": _iso(self._last_attempt),
                "supervising": bool(self.enabled and not self._suppression_reason()),
            }

    # -- the state machine ----------------------------------------------
    def tick(self, reachable: bool) -> None:
        """One lane C poll's worth of evidence. Never raises."""
        try:
            if reachable:
                self._note_reachable()
            else:
                self._note_unreachable()
        except Exception:
            log.exception("supervisor: tick failed")

    def _note_reachable(self) -> None:
        with self._lock:
            if not self._since:
                return
            attempts = self._attempts
            down_for = max(0.0, self._clock() - self._since)
            self._since = 0.0
            self._attempts = 0
            self._last_error = ""
            self._last_attempt = 0.0
            self._warned = False
            self._pending_confirm = False
        self._logged_suppression = ""
        self._logged_disabled = False
        self._clear_state_file()
        if attempts:
            log.info(
                "supervisor: the sync engine is answering again after %d start "
                "attempt(s) and %.0f s down", attempts, down_for,
            )
            self._balloon(BALLOON_RESTARTED)
        else:
            log.info(
                "supervisor: the sync engine is answering again (%.0f s down, "
                "nothing was restarted)", down_for,
            )

    def _note_unreachable(self) -> None:
        now = self._clock()
        with self._lock:
            first = not self._since
            if first:
                self._since = now
                self._persist_locked()
            elif now < self._since or now < self._last_attempt:
                # The wall clock went BACKWARDS (an NTP step, a laptop
                # crossing a suspend, a user fixing the date). Every "has it
                # been 30 s yet" comparison here is a subtraction, and a
                # timestamp in the future makes all of them false -- i.e. the
                # supervisor quietly stops supervising until real time
                # catches up, which after a big step could be hours. Re-base
                # instead; one extra grace window is the whole cost.
                log.info(
                    "supervisor: the clock moved backwards -- re-basing this "
                    "incident on the current time")
                self._since = now
                self._last_attempt = 0.0
                self._persist_locked()
            since = self._since
            attempts = self._attempts
            last_attempt = self._last_attempt
            # The launcher ran last time and nothing has confirmed it since.
            # Once the API-wait window has passed with the port still dead,
            # that attempt WAS a failure -- without this the three-strike
            # rule can only ever count launches that refused to execute, so
            # the commonest shape of "it will not start" (the shim runs,
            # Syncthing exits immediately) would warn nobody, ever.
            overdue = (
                self._pending_confirm
                and last_attempt
                and now - last_attempt >= self.api_wait_seconds
            )
            if overdue:
                self._pending_confirm = False
        if overdue:
            self._note_failure(
                "it was started but 127.0.0.1:8384 still does not answer",
                attempts, stamp=False,
            )
        if first:
            log.info(
                "supervisor: the local Syncthing API stopped answering -- "
                "watching it for %.0f s before starting anything", self.grace_seconds,
            )
        if not self.enabled:
            if not self._logged_disabled:
                self._logged_disabled = True
                log.warning(
                    "supervisor: the sync engine is down and supervise_syncthing is "
                    "false on this machine -- NOT restarting it; lane C stays in "
                    "error until someone starts Syncthing by hand",
                )
            return
        reason = self._suppression_reason()
        if reason:
            if self._logged_suppression != reason:
                self._logged_suppression = reason
                log.info(
                    "supervisor: the sync engine is down but %s -- leaving it "
                    "stopped, because resurrecting it would undo a deliberate "
                    "stop. Lane C reports the error either way.", reason,
                )
            return
        self._logged_suppression = ""
        if now - since < self.grace_seconds:
            return
        if last_attempt and now - last_attempt < backoff_seconds(attempts):
            return
        # The backoff test above is read under the lock and acted on outside
        # it, so two threads calling check_once at once -- the lane C poll and
        # the tray's "Copy diagnostics" worker, which builds its report by
        # calling the lane synchronously -- could both pass it and both spawn
        # the shim. The second `syncthing serve` on the same home dies on the
        # DB/port lock, leaving a pair of "start attempt N" lines and an
        # attempts counter advanced by two for one outage (comp-lane-c-5,
        # 2026-08-21). A launch already in flight is the whole answer: the
        # other caller's evidence is the same outage, and _wait_for_api will
        # report on it.
        if not self._claim_launch():
            log.debug("supervisor: a start attempt is already running -- not spawning a second")
            return
        try:
            self._attempt_start(now)
        finally:
            with self._lock:
                self._launching = False

    def _claim_launch(self) -> bool:
        """Test-and-set the "a launch is in flight" flag. See
        _note_unreachable (comp-lane-c-5)."""
        with self._lock:
            if self._launching:
                return False
            self._launching = True
            return True

    def _suppression_reason(self) -> str:
        if self._suppressed is None:
            return ""
        try:
            return str(self._suppressed() or "")
        except Exception:
            log.exception("supervisor: the suppression check failed")
            # Fail towards NOT touching anything: a check that cannot answer
            # "is this machine deliberately stopped" must not be read as "no".
            return "the halt/pause check could not be read"

    def _attempt_start(self, now: float) -> None:
        with self._lock:
            self._attempts += 1
            self._last_attempt = now
            self._pending_confirm = False
            attempt = self._attempts
            down_for = max(0.0, now - self._since)
            self._persist_locked()
        if not self.launcher.available():
            self._note_failure(self.launcher.missing_reason(), attempt)
            return
        log.info(
            "supervisor: the sync engine has been unreachable for %.0f s -- start "
            "attempt %d via %s", down_for, attempt,
            " ".join(self.launcher.command() or []),
        )
        started, error = self.launcher.launch()
        if not started:
            self._note_failure(error or "the launcher would not run", attempt)
            return
        if self.probe is None:
            # No way to confirm from here; the next lane C poll is the
            # confirmation, and _note_reachable owns the balloon either way.
            with self._lock:
                self._pending_confirm = True
                self._last_attempt = self._clock()
                self._persist_locked()
            log.info("supervisor: launcher started -- waiting for the next lane C poll")
            return
        if self._wait_for_api():
            self._note_reachable()
            return
        self._note_failure(
            f"it was started but 127.0.0.1:8384 did not answer within "
            f"{self.api_wait_seconds:.0f} s",
            attempt,
        )

    def _wait_for_api(self) -> bool:
        """Poll the API after a launch. Bounded, and the sleep is injected --
        this runs on the lane C poll thread, which must not be parked for
        longer than one poll interval.

        Bounded TWICE, by the deadline and by an iteration count, because
        neither collaborator can be trusted to end the loop on its own: an
        injected clock that does not move (a test) or a wall clock stepped
        backwards by NTP mid-wait both turn a deadline-only loop into a hang
        on the thread that reports lane C."""
        deadline = self._clock() + self.api_wait_seconds
        rounds = max(1, int(self.api_wait_seconds / API_WAIT_POLL_SECONDS) + 1)
        for _ in range(rounds):
            try:
                if self.probe is not None and self.probe():
                    return True
            except Exception:
                log.debug("supervisor: API probe failed", exc_info=True)
            if self._clock() >= deadline:
                return False
            self._sleep(API_WAIT_POLL_SECONDS)
        return False

    def _note_failure(self, error: str, attempt: int, stamp: bool = True) -> None:
        """Record that attempt `attempt` did not produce a running Syncthing.

        `stamp=True` moves the backoff clock to NOW, because the backoff runs
        from when an attempt FINISHED: _wait_for_api can spend most of one
        backoff window on its own, and measuring from the start would fire the
        next launch seconds after the last gave up. The DEFERRED verdict
        (`_note_unreachable`'s overdue branch) passes False -- that failure is
        merely being recognised late, and re-stamping it would push every
        later attempt out by however long the recognition took."""
        with self._lock:
            self._last_error = str(error or "")
            if stamp:
                self._last_attempt = self._clock()
            warn = attempt >= FAILURES_BEFORE_WARNING and not self._warned
            if warn:
                self._warned = True
            self._persist_locked()
        if attempt < FAILURES_BEFORE_WARNING:
            log.info("supervisor: start attempt %d failed: %s", attempt, error)
            return
        if warn:
            log.warning(
                "supervisor: the sync engine has failed to start %d times: %s. "
                "Lane C (audio, graphics, subtitles, project files) is carrying "
                "NOTHING on this machine until it runs.", attempt, error,
            )
            self._balloon(balloon_failed(last_line(error) or error))
        else:
            log.info("supervisor: start attempt %d failed: %s", attempt, error)

    def _balloon(self, message: str) -> None:
        if self._notify is None:
            return
        try:
            self._notify(message, site_mod.notify_title())  # UX-4
        except Exception:
            log.debug("supervisor: tray notify failed")


def backoff_seconds(attempts: int) -> float:
    """Delay before the attempt AFTER `attempts` failures: 30 s, 1 m, 2 m,
    4 m, 8 m, then 10 m forever."""
    if attempts <= 0:
        return 0.0
    delay = BACKOFF_START_SECONDS * (2 ** (attempts - 1))
    return float(min(delay, BACKOFF_CAP_SECONDS))


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _iso(epoch: float) -> Optional[str]:
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None
