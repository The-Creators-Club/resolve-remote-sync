"""Fill the proxy gaps proxy_scan finds -- with ffmpeg, while nobody is here.

proxy_scan answers "which originals can nobody else see?" (lane B only
carries `**/Proxy/**`, so an original with no sibling proxy reaches no other
machine in the fleet). This module is the half that DOES something about it:
one background thread that encodes the missing proxies and, on every machine
whether it generates or not, tells the editor the gap exists.

Three rules shape the whole design, and every awkward-looking piece below is
one of them being enforced:

  1. NEVER UNDER THE USER'S HANDS. Encoding starts only after
     `proxy_gen_idle_seconds` of no keyboard/mouse input, and the ffmpeg
     child is KILLED within ~2 s of the user coming back. idle.py's contract
     -- None means cannot tell means not idle -- is what makes that safe on
     a platform whose idle time we cannot read at all.
  2. NEVER TWO WRITERS ON ONE PROXY. Everything is encoded to
     `Proxy/<stem>.mp4.partial` (excluded by every lane filter in both
     directions) and moved into place with os.replace only after re-checking
     that neither final extension exists. The Blackmagic Proxy Generator
     writes the same directory on the base rig, Resolve holds proxies open
     without share-delete (GOTCHAS:354-357), and lane B can deliver a proxy
     mid-encode -- first writer wins, always, and we are happy to lose.
  3. NEVER STOP THE COMPANION. This is an advisory feature bolted onto the
     thing that tells the fleet whether its footage is syncing. No method
     here raises, the thread catches everything per tick, a missing ffmpeg
     degrades to notifier-only, and the gate publishes WHY it isn't running
     rather than going quiet.

Thread model: one daemon thread (ManifestCache/DashboardReporter idiom), a
15 s tick, and a 900 s scan cadence on top of it. gap()/coverage()/
block_reason() are lock-guarded reads of cached dicts and do NO I/O -- the
tray snapshot calls them on its refresh thread, and a getter that touched the
filesystem there is how the right-click freeze of 2026-07-26 happened.

Every collaborator that touches the world -- the filesystem scan, ffmpeg,
the idle probe, the clock -- arrives as a constructor parameter, so the whole
state machine is testable with no ffmpeg, no timers and no real tree.

Added 2026-08-10 with the missing-proxy notifier.
"""

from __future__ import annotations

import collections
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

from . import config as config_mod
from . import ffmpeg_tools, proxy_scan

# "ccsync.proxy_gen", NOT __name__ -- setup_logging() only attaches handlers
# to the "ccsync" logger, and in the windowed build sys.stderr is None, so a
# record emitted under "ccsync_companion.proxy_gen" goes nowhere at all.
log = logging.getLogger("ccsync.proxy_gen")

# How often the gate is re-evaluated. Short enough that "the user came back"
# and "the drive reappeared" are noticed promptly, long enough that a machine
# with nothing to do is doing arithmetic four times a minute and no more.
TICK_SECONDS = 15.0

# How often a RUNNING encode is checked for "should I still be doing this?".
# This is the number that decides how long ffmpeg keeps stealing cycles after
# an editor touches the mouse, so it is deliberately small.
ENCODE_POLL_SECONDS = 2.0

# Runaway ceiling: max(this, source duration x STUCK_DURATION_FACTOR). A
# 30 s clip that has been encoding for 30 minutes is not slow, it is wedged
# (a network read that never returns, an NVENC session in a bad state), and
# an unkillable encode would hold the generator's only thread forever.
STUCK_FLOOR_SECONDS = 1800.0
STUCK_DURATION_FACTOR = 60.0

# A proxy must decode cleanly AND be as long as its source. 0.97 rather than
# 1.0 because the last GOP and a trailing partial audio frame legitimately
# round a 60.00 s source to a 59.95 s proxy; anything shorter than this means
# ffmpeg stopped early (disk full, source read error) and the file would
# silently truncate somebody's timeline.
VERIFY_DURATION_RATIO = 0.97

# ffmpeg's stderr is drained by a reader thread into a bounded deque: the
# pipe's OS buffer is ~64 KB and a full one BLOCKS the encoder forever, which
# is the classic Popen deadlock. Bounded because an ffmpeg that decides to
# complain once per frame would otherwise be a memory leak with a progress
# bar; the LAST lines are the ones that say why it failed.
STDERR_KEEP_LINES = 200

# POSIX nice value for the encoder. The Windows half is
# BELOW_NORMAL_PRIORITY_CLASS at spawn time; POSIX gets os.setpriority AFTER
# the fork (preexec_fn is not async-signal-safe and is documented as unsafe
# in threaded programs -- this whole module IS a thread).
ENCODE_NICE = 10

# Where the once-a-day notification cooldown is remembered. Persisted so a
# companion that restarts every morning does not re-nag about a gap the
# editor has already decided about; in the state dir with every other piece
# of companion state (project_prompts.json's neighbour).
NOTIFY_STATE_FILENAME = "proxy_notify.json"

# Gate answers, published verbatim as coverage()["state"]. Strings rather
# than an enum because they cross into the report payload and a dashboard
# reading them must not need this module.
STATE_DISABLED = "disabled"
STATE_DRIVE_ABSENT = "drive-absent"
STATE_PAUSED = "paused"
STATE_MISCONFIGURED = "misconfigured"
STATE_NO_FFMPEG = "no-ffmpeg"
STATE_NOTHING_TO_DO = "nothing-to-do"
STATE_USER_ACTIVE = "user-active"
STATE_RESOLVE_OPEN = "resolve-open"
STATE_RUNNING = "running"

# encode_once() outcomes -- returned rather than logged-and-swallowed so the
# state machine is assertable in a test.
RESULT_EMPTY = "empty"
RESULT_DONE = "done"
RESULT_SKIPPED = "skipped"
RESULT_FAILED = "failed"
RESULT_INTERRUPTED = "interrupted"

# Per-project entries in coverage(). The scan is already capped at
# manifest.MAX_PROJECTS (64) projects, so this is a belt-and-braces bound on
# what a caller can be handed; the reporter caps again on its own terms.
MAX_COVERAGE_PROJECTS = 64


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_popen(cmd: list[str]) -> Any:
    """Spawn ffmpeg: no console window, below-normal priority, stderr piped.

    Priority is the difference between "the machine was a bit busy" and "the
    machine was unusable" if the user comes back mid-encode -- the 2 s kill
    poll is the real protection, this is what covers the two seconds before
    it fires. Windows takes it as a creation flag; POSIX has no equivalent,
    so it is renice-after-spawn (NOT preexec_fn, which runs between fork and
    exec in a multithreaded process and is documented as unsafe there).
    """
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        # ffmpeg reads stdin for its interactive keys and would consume the
        # parent's if it had one -- and in the frozen windowed build there is
        # no console stdin to consume, which makes it an error rather than a
        # theft. DEVNULL settles both.
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }
    kwargs.update(ffmpeg_tools.TEXT_UTF8)
    flags = ffmpeg_tools._win_creationflags()
    if sys.platform == "win32":
        flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
    kwargs["creationflags"] = flags
    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 -- argv built by ffmpeg_tools
    if sys.platform != "win32":
        try:
            os.setpriority(os.PRIO_PROCESS, proc.pid, ENCODE_NICE)
        except Exception:
            # A failed renice is a slower machine, not a broken encode.
            log.debug("proxy gen: could not renice the encoder", exc_info=True)
    return proc


def _kill(proc: Any) -> None:
    """End a child that must stop NOW. The rclone_lane._end_probe idiom
    (:613-631): kill, then a BOUNDED wait, because a process stuck in an
    uninterruptible kernel wait cannot be killed at all and an unbounded
    wait() here would hang the very thread whose job is to be responsive."""
    try:
        proc.kill()
    except Exception:
        log.debug("proxy gen: could not kill the encoder", exc_info=True)
    try:
        proc.wait(timeout=5)
    except Exception:
        log.warning(
            "proxy gen: the encoder did not die when killed -- leaving it to the OS. "
            "Its output file stays a .partial and is never published."
        )


def _drain(stream: Any, sink: Any) -> None:
    """Read a pipe to EOF into a bounded deque. Never raises: this runs on
    its own thread, where an exception would be printed to a stderr the
    windowed build does not have and then lost."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            sink.append(line.rstrip("\r\n"))
    except Exception:
        log.debug("proxy gen: stderr reader stopped early", exc_info=True)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def sweep_stale_partials(
    local_root: Any,
    max_age_seconds: float = 6 * 3600.0,
    now_fn: Callable[[], float] = time.time,
) -> list[str]:
    """REPORT (never delete) `Proxy/*.partial` files nothing is writing.

    Deliberately the same shape and the same refusal as
    fixer.sweep_stale_tmp_files (AUDIT_2 CORE-H5): a partial is the user's
    disk space but it is also, potentially, a file some OTHER process is
    writing this second -- the filesystem alone cannot tell us -- and an
    automatic unlink here would be this system's only unprompted removal of
    a file under local_root. So it says so and leaves it.

    Stale means older than `max_age_seconds`, which is far longer than any
    single encode: a live encode's partial is touched continuously, and the
    only thing that leaves an old one behind is a kill -9, a power cut, or a
    publish that hit a sharing violation. Never raises.
    """
    root = str(local_root or "").strip()
    if not root:
        return []
    found: list[tuple[float, str]] = []
    cutoff = now_fn() - max(0.0, float(max_age_seconds or 0))
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if os.path.basename(dirpath).lower() != proxy_scan.PROXY_DIR_NAME.lower():
                continue
            for name in filenames:
                if not name.endswith(proxy_scan.PARTIAL_SUFFIX):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                if stat.st_mtime > cutoff:
                    continue
                found.append((stat.st_mtime, full))
    except Exception:
        log.debug("proxy gen: stale .partial sweep failed under %s", root, exc_info=True)
        return []
    found.sort()
    for mtime, path in found:
        log.warning(
            "leftover half-made proxy from an interrupted encode: %s (last written %s) "
            "-- NOT deleted; it is excluded from every sync lane and will be redone "
            "on the next pass",
            path, time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
        )
    return [path for _mtime, path in found]


class ProxyGenerator:
    """The worker. start()/stop()/join() plus zero-I/O status readers."""

    def __init__(
        self,
        cfg: dict[str, Any],
        state_dir: Any,
        *,
        root_present_fn: Optional[Callable[[], bool]] = None,
        paused_fn: Optional[Callable[[], bool]] = None,
        blocked_fn: Optional[Callable[[], bool]] = None,
        get_selected_rels: Optional[Callable[[], Optional[set]]] = None,
        notify: Optional[Callable[..., None]] = None,
        idle_probe: Any = None,
        scan_fn: Optional[Callable[..., dict]] = None,
        encode_fn: Optional[Callable[..., dict]] = None,
        probe_fn: Optional[Callable[[str, Any], dict]] = None,
        available_fn: Optional[Callable[[str], tuple]] = None,
        encoders_fn: Optional[Callable[[str], Any]] = None,
        resolve_running_fn: Optional[Callable[[], bool]] = None,
        bpg_launcher: Any = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg
        self.local_root = str(cfg.get("local_root", "") or "")
        self.state_path = Path(state_dir) / NOTIFY_STATE_FILENAME

        # -- injected seams. Everything that touches the world is here, which
        # is what lets the state machine be tested with no ffmpeg anywhere.
        self._root_present_fn = root_present_fn
        self._paused_fn = paused_fn
        self._blocked_fn = blocked_fn
        self._get_selected_rels = get_selected_rels
        self._notify = notify
        self._idle_probe = idle_probe
        self._scan_fn = scan_fn or proxy_scan.scan_missing_proxies
        self._encode_fn = encode_fn or self._run_ffmpeg
        self._probe_fn = probe_fn or ffmpeg_tools.probe_video
        self._available_fn = available_fn or ffmpeg_tools.ffmpeg_available
        self._encoders_fn = encoders_fn or ffmpeg_tools.detect_encoders
        self._resolve_running_fn = resolve_running_fn
        # Started only once the ffmpeg queue is empty -- see bpg.py. None on a
        # machine with no proxy generator, which is most of the fleet.
        self._bpg = bpg_launcher
        # monotonic for every INTERVAL (a clock the user can drag backwards
        # must not make an encode look 3 hours old), wall clock only for the
        # persisted notification cooldown, which has to survive a restart and
        # therefore cannot be monotonic.
        self._clock = clock
        self._wall_clock = wall_clock

        # -- config. coerce_numeric everywhere, never float(): this object is
        # constructed inside CompanionApp.__init__, where a hand-edited
        # `proxy_scan_interval = "15m"` would take the windowed exe down with
        # no tray and no log line (AUDIT_2 CORE-M4's family).
        self.notify_enabled = bool(cfg.get("proxy_notify_enabled", True))
        self.generation_enabled = config_mod.proxy_generation_enabled(cfg)
        self.ffmpeg_path = str(cfg.get("ffmpeg_path", "ffmpeg") or "ffmpeg").strip() or "ffmpeg"
        self.scan_interval = config_mod.coerce_numeric(cfg, "proxy_scan_interval", 900)
        self.idle_seconds = config_mod.coerce_numeric(cfg, "proxy_gen_idle_seconds", 300)
        self.min_age_seconds = config_mod.coerce_numeric(cfg, "proxy_gen_min_age_seconds", 120)
        self.max_height = int(config_mod.coerce_numeric(cfg, "proxy_gen_max_height", 1080))
        self.bitrate = config_mod.coerce_bitrate(cfg, "proxy_gen_bitrate", "7M")
        self.max_failures = int(config_mod.coerce_numeric(cfg, "proxy_gen_max_failures", 3))
        self.notify_cooldown = config_mod.coerce_numeric(
            cfg, "proxy_notify_cooldown_seconds", 86400
        )
        self.skip_while_resolve = bool(cfg.get("proxy_gen_skip_while_resolve_running", False))

        # -- state, ALL of it guarded by _lock. gap()/coverage() are called
        # from the tray's refresh thread while this thread rewrites them.
        self._lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []
        self._projects: dict[str, dict[str, Any]] = {}
        self._totals: dict[str, Any] = proxy_scan._empty_totals()
        self._state = STATE_NOTHING_TO_DO
        self._current: Optional[str] = None
        self._generated = 0
        self._failed = 0
        self._scanned_at: Optional[str] = None
        self._nvenc = False
        self._ffmpeg_ok = False
        # {path: {"attempts": n, "mtime": m, "size": s}} -- in-process ONLY.
        # A blacklist persisted to disk turns one bad night for the GPU into
        # a permanent refusal to ever proxy those clips again.
        self._failures: dict[str, dict[str, Any]] = {}

        self._stop_event = threading.Event()
        # Wakes the tick early (a tray "make them now" must not wait 15 s).
        self._wake = threading.Event()
        # Set by cancel_run(): kills the encode in flight and empties the
        # queue for this cycle. NOT a disable -- the next scan refills it.
        self._cancel = threading.Event()
        self._forced = False
        self._thread: Optional[threading.Thread] = None
        self._last_scan_at: Optional[float] = None
        self._root_was_present = True
        self._no_ffmpeg_warned = False
        # Once per EPISODE: a gap is a state, not an event, and a toast per
        # 15 s tick about the same 12 clips is how a useful notice becomes
        # something the editor turns off. Cleared when the gap closes or the
        # drive comes back (root_guard's _root_absent_announced precedent).
        self._notified_episode = False
        self._last_notified_at = self._load_notify_state()

    # -- persisted notification cooldown ---------------------------------
    def _load_notify_state(self) -> float:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return float(data.get("last_notified_at") or 0.0)
        except (OSError, ValueError, TypeError):
            # No file yet, or one written by a different version: "never
            # notified" is the safe reading -- worst case one extra toast.
            return 0.0

    def _record_notify(self, when: float) -> None:
        self._last_notified_at = when
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps({"last_notified_at": when}, indent=1), encoding="utf-8"
            )
        except OSError as exc:
            # A cooldown that cannot be persisted costs at most one extra
            # toast per restart. Never worth failing the tick over.
            log.debug("proxy gen: could not persist the notify cooldown: %s", exc)

    # -- collaborators, each fault-isolated --------------------------------
    def _root_present(self) -> bool:
        try:
            if self._root_present_fn is not None:
                return bool(self._root_present_fn())
            return os.path.isdir(self.local_root)
        except Exception:
            # "Can't tell" is present, matching ManifestCache._root_is_present:
            # an unanswerable probe must not switch a feature off.
            log.debug("proxy gen: could not check local_root", exc_info=True)
            return True

    def _is_paused(self) -> bool:
        try:
            return bool(self._paused_fn()) if self._paused_fn is not None else False
        except Exception:
            log.debug("proxy gen: paused_fn failed", exc_info=True)
            return False

    def _is_blocked(self) -> bool:
        try:
            return bool(self._blocked_fn()) if self._blocked_fn is not None else False
        except Exception:
            log.debug("proxy gen: blocked_fn failed", exc_info=True)
            return False

    def _resolve_running(self) -> bool:
        """Fails CLOSED (True), like resolve_prefs.resolve_is_running: this
        gate exists for the machine that leaves UNATTENDED renders going, and
        a check that cannot answer must not be read as "the GPU is free"."""
        if self._resolve_running_fn is None:
            return False
        try:
            return bool(self._resolve_running_fn())
        except Exception:
            log.debug("proxy gen: resolve_running_fn failed", exc_info=True)
            return True

    def _seconds_idle(self) -> Optional[float]:
        if self._idle_probe is None:
            return None
        try:
            value = self._idle_probe.seconds_idle()
            return None if value is None else float(value)
        except Exception:
            log.debug("proxy gen: idle probe failed", exc_info=True)
            return None

    def _user_is_away(self) -> bool:
        """None (cannot tell) is NOT away. See idle.py's contract."""
        idle = self._seconds_idle()
        return idle is not None and idle >= self.idle_seconds

    def _check_ffmpeg(self) -> bool:
        """Is there a runnable ffmpeg? Cheap: ffmpeg_available caches
        successes for 300 s, and a MISS is a failure we want re-probed every
        time so that installing ffmpeg starts generation with no restart."""
        try:
            ok, message = self._available_fn(self.ffmpeg_path)
        except Exception:
            log.debug("proxy gen: ffmpeg probe failed", exc_info=True)
            return False
        if ok:
            self._no_ffmpeg_warned = False
            return True
        if not self._no_ffmpeg_warned:
            # WARNING once, then silence: this is the expected state on every
            # machine until the Phase-2 installer step exists, and it costs
            # the fleet nothing -- the notifier still works.
            log.warning(
                "proxy generation is on but %s -- this machine will still TELL you "
                "which clips have no proxy, it just cannot make them", message,
            )
            self._no_ffmpeg_warned = True
        return False

    def _has_nvenc(self, encoder: str) -> bool:
        try:
            return encoder in self._encoders_fn(self.ffmpeg_path)
        except Exception:
            log.debug("proxy gen: encoder detection failed", exc_info=True)
            return False

    # -- the gate ---------------------------------------------------------
    def _gate(self) -> str:
        """Why the generator is or isn't encoding right now, in priority
        order. The FIRST true answer wins, and the order is the order an
        editor would ask the questions in: is it on, is the disk here, did I
        pause it, is it set up, can it run, is there anything to do, am I
        here, is Resolve busy."""
        if not self.generation_enabled:
            return STATE_DISABLED
        if not self._root_present():
            return STATE_DRIVE_ABSENT
        if self._is_paused():
            return STATE_PAUSED
        if self._is_blocked():
            return STATE_MISCONFIGURED
        if not self._check_ffmpeg():
            return STATE_NO_FFMPEG
        with self._lock:
            empty = not self._queue
            forced = self._forced
        if empty:
            return STATE_NOTHING_TO_DO
        # A forced run is the editor saying "don't wait until I'm away", so
        # it skips the idle gates -- and ONLY those. Everything above still
        # applies, and so does the Resolve gate below.
        if not forced and not self._user_is_away():
            return STATE_USER_ACTIVE
        if self.skip_while_resolve and self._resolve_running():
            return STATE_RESOLVE_OPEN
        return STATE_RUNNING

    def _publish_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    # -- public, zero-I/O readers ------------------------------------------
    def gap(self) -> dict[str, Any]:
        """What the TRAY renders. Cached, lock-guarded, no filesystem.

        Called on the tray's refresh thread (tray._tray_snapshot), which on
        the win32 backend can stall the message loop: nothing in here may
        block, probe, or walk anything.
        """
        with self._lock:
            return {
                "missing": int(self._totals.get("missing", 0)),
                "braw": int(self._totals.get("braw", 0)),
                "needs_resolve": int(self._totals.get("needs_resolve", 0)),
                "left": len(self._queue),
                "encoding": self._current is not None,
                "can_generate": bool(self.generation_enabled and self._ffmpeg_ok),
                "state": self._state,
                "generated": self._generated,
                "failed": self._failed,
            }

    def coverage(self) -> dict[str, Any]:
        """What the REPORTER sends. Same rules as gap(): cached, no I/O."""
        with self._lock:
            projects = {
                rel: {
                    "missing": int(entry.get("missing", 0)),
                    "braw": int(entry.get("braw", 0)),
                    "needs_resolve": int(entry.get("needs_resolve", 0)),
                    proxy_scan.KIND_OWN: int(entry.get(proxy_scan.KIND_OWN, 0)),
                    proxy_scan.KIND_PREVIEW: int(entry.get(proxy_scan.KIND_PREVIEW, 0)),
                }
                for rel, entry in list(self._projects.items())[:MAX_COVERAGE_PROJECTS]
                # Only projects with a gap: a base rig with 64 fully-covered
                # projects would otherwise send 64 rows of zeroes every tick.
                if int(entry.get("missing", 0)) > 0
            }
            return {
                "state": self._state,
                "enabled": bool(self.generation_enabled),
                "missing": int(self._totals.get("missing", 0)),
                "braw": int(self._totals.get("braw", 0)),
                "needs_resolve": int(self._totals.get("needs_resolve", 0)),
                proxy_scan.KIND_OWN: int(self._totals.get(proxy_scan.KIND_OWN, 0)),
                proxy_scan.KIND_PREVIEW: int(self._totals.get(proxy_scan.KIND_PREVIEW, 0)),
                "left": len(self._queue),
                "generated": self._generated,
                "failed": self._failed,
                "ffmpeg": bool(self._ffmpeg_ok),
                "nvenc": bool(self._nvenc),
                "scanned_at": self._scanned_at,
                "projects": projects,
            }

    def block_reason(self) -> Optional[str]:
        """Shutdown-screen text while an encode is in flight, else None.

        Read by app._shutdown_block_reason (Windows calls it on its own
        thread with seconds of patience) and, through the same function, by
        the keep-awake guard -- so a machine will not sleep mid-encode, and
        sleeps again the moment the queue drains. That is intentional: the
        generator only ever runs while the user is away, which is exactly
        when the idle timer would otherwise fire.
        """
        with self._lock:
            if self._current is None:
                return None
            left = len(self._queue)
        return (
            f"still making video proxies so the rest of the team can see this "
            f"footage ({left} clip(s) left)"
        )

    # -- tray actions ------------------------------------------------------
    def request_run(self) -> None:
        """"Make the missing proxies now (don't wait until I'm away)"."""
        with self._lock:
            self._forced = True
            self._last_scan_at = None  # force a fresh scan on the next tick
        self._cancel.clear()
        self._wake.set()
        log.info("proxy gen: run requested from the tray -- scanning now")

    def cancel_run(self) -> None:
        """"Stop making proxies". Kills the encode in flight (leaving no
        partial behind) and drops the queue for this cycle; the next scheduled
        scan refills it. Deliberately not a disable: switching the feature off
        is a config decision, not a menu click."""
        with self._lock:
            self._forced = False
        self._cancel.set()
        self._wake.set()
        log.info("proxy gen: stop requested from the tray")

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        if not (self.notify_enabled or self.generation_enabled):
            log.info("proxy gap notifier and generator are both disabled by config")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ccsync-proxy-gen", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Told FIRST in app.shutdown(): setting this is what kills the
        ffmpeg child, and everything else in teardown is cheap by comparison.
        Never blocks -- join() is the caller's separate decision."""
        self._stop_event.set()
        self._wake.set()

    def join(self, timeout: float = 5.0) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        try:
            thread.join(timeout=timeout)
            if thread.is_alive():
                log.warning("proxy gen: the worker did not stop within %.0fs", timeout)
        except Exception:
            log.exception("proxy gen: failed to join the worker thread")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                # One bad tick must not end the thread: this feature's whole
                # value is that it keeps telling you about the gap.
                log.exception("proxy gen: tick failed")
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    # -- the tick ----------------------------------------------------------
    def tick(self) -> str:
        """One pass: gate, maybe scan, maybe notify, maybe encode. Returns
        the published state (what the tests and the reporter read)."""
        present = self._root_present()
        # The drive coming back is a scan trigger: an editor who plugs their
        # SSD in wants the answer now, not up to 15 minutes later. It also
        # clears the once-per-episode notification latch -- a new drive is a
        # new episode.
        if present and not self._root_was_present:
            with self._lock:
                self._last_scan_at = None
            self._notified_episode = False
            log.info("proxy gen: the tree is back -- rescanning for missing proxies")
        self._root_was_present = present

        state = self._gate()
        self._publish_state(state)

        if present and (self.notify_enabled or self.generation_enabled):
            if self._scan_due():
                self.scan_once()
                self._maybe_notify()

        # Re-gate: the scan above may have just filled (or emptied) the queue,
        # and publishing "nothing-to-do" for 15 s with 40 clips queued would
        # make the tray lie.
        state = self._gate()
        self._publish_state(state)
        if state == STATE_RUNNING:
            state = self._drain_queue()
        # AFTER the drain, and only from a state that means the ffmpeg queue is
        # empty: BPG is the same GPU, so the two must never encode at once.
        # _drain_queue returns the state it finished in, so a pass that just
        # emptied the queue lands here in the same tick rather than a scan later.
        self._maybe_launch_bpg(state)
        return state

    def _maybe_launch_bpg(self, state: str) -> None:
        """Hand the clips ffmpeg cannot decode to the Blackmagic Proxy
        Generator, once there is nothing else encoding. Never raises: this is
        a convenience on top of a report that was already correct without it."""
        if self._bpg is None:
            return
        with self._lock:
            queue_empty = not self._queue
            needs_resolve = int(self._totals.get("needs_resolve", 0))
        try:
            self._bpg.maybe_launch(
                queue_empty=queue_empty and state != STATE_RUNNING,
                needs_resolve=needs_resolve,
                user_away=self._user_is_away(),
            )
        except Exception:
            log.exception("proxy gen: the BPG launcher raised")

    def _scan_due(self) -> bool:
        with self._lock:
            last = self._last_scan_at
        if last is None:
            return True  # first tick after start(), a root return, or a request
        interval = self.scan_interval if self.scan_interval > 0 else 900
        return (self._clock() - last) >= interval

    def scan_once(self) -> dict[str, Any]:
        """Walk the tree, rebuild the queue and the cached counts.

        The SECOND full walk this companion does (ManifestCache owns the
        first), which is the whole reason the cadence is 900 s and the
        project count is capped. Never raises -- scan_missing_proxies already
        swallows its own failures, and this adds the same guarantee around
        the getter it calls.
        """
        selected = None
        if self._get_selected_rels is not None:
            try:
                selected = self._get_selected_rels()
            except Exception:
                log.exception("proxy gen: get_selected_rels() failed")
        try:
            result = self._scan_fn(
                self.local_root, selected, self.min_age_seconds,
            )
        except Exception:
            log.exception("proxy gen: the scan failed")
            with self._lock:
                self._last_scan_at = self._clock()
            return {"projects": {}, "totals": proxy_scan._empty_totals()}

        projects = result.get("projects") or {}
        totals = result.get("totals") or proxy_scan._empty_totals()
        # One flat queue, newest first across every project: the clip someone
        # shot this morning is the one their collaborators are waiting on,
        # whichever project it lives in. Ties break on path so two scans of an
        # unchanged tree produce the same order.
        queue: list[dict[str, Any]] = []
        for rel, gap in projects.items():
            for clip in gap.get("clips") or []:
                entry = dict(clip)
                entry["project"] = rel
                queue.append(entry)
        queue.sort(key=lambda clip: (-float(clip.get("mtime") or 0), str(clip.get("path"))))
        # Anything that has already failed its way past the cap stays out of
        # the queue entirely, or every cycle would re-attempt it first (it is
        # usually the newest file -- a truncated download).
        queue = [clip for clip in queue if not self._is_capped(clip)]

        # Probed OUTSIDE the lock: ffmpeg_available can spawn a process and
        # detect_encoders can take a second on a cold binary, and gap() --
        # which the tray calls on its refresh thread -- takes the same lock.
        ffmpeg_ok = self._check_ffmpeg() if self.generation_enabled else False
        nvenc = bool(
            ffmpeg_ok
            and (self._has_nvenc("hevc_nvenc") or self._has_nvenc("h264_nvenc"))
        )

        with self._lock:
            self._projects = dict(projects)
            self._totals = dict(totals)
            self._queue = queue
            self._last_scan_at = self._clock()
            self._scanned_at = _iso_now()
            self._ffmpeg_ok = ffmpeg_ok
            self._nvenc = nvenc
        missing = int(totals.get("missing", 0))
        if missing:
            log.info(
                "proxy gap: %d clip(s) in %d project(s) have no proxy -- %d queued for "
                "encoding, %d need Resolve/BPG",
                missing, int(totals.get("projects", 0)), len(queue),
                int(totals.get("needs_resolve", 0)),
            )
        return result

    # -- notification ------------------------------------------------------
    def _biggest_gap_project(self) -> tuple[str, dict[str, Any]]:
        with self._lock:
            projects = dict(self._projects)
        best_rel, best_gap = "", proxy_scan.empty_gap()
        for rel, gap in projects.items():
            if int(gap.get("missing", 0)) > int(best_gap.get("missing", 0)):
                best_rel, best_gap = rel, gap
        return best_rel, best_gap

    def _notify_text(self, rel: str, totals: dict[str, Any],
                     project_missing: int = 0) -> str:
        """The toast. Names ONE project (the biggest gap) and how many clips
        the whole machine is missing, because "12 clips have no proxy" with no
        location is a sentence nobody can act on.

        Those are two DIFFERENT numbers and the sentence has to say so. It
        used to read "1046 clips in Energy Transition have no proxy" when the
        1046 was seven projects and Energy Transition was 438 of them -- which
        sends the reader looking for a thousand clips in a project that does
        not have them (base rig, 2026-08-10). The project's own count leads,
        the machine total follows, and when they are equal it says it once.

        The four variants exist because the right next action is different in
        each: we are about to fix it / we cannot fix it here / we cannot fix
        it at all on this machine / only Resolve can fix these.
        """
        missing = int(totals.get("missing", 0))
        needs_resolve = int(totals.get("needs_resolve", 0))
        here = int(project_missing or 0)
        name = rel.split("/")[-1] if rel else ""
        if name and 0 < here < missing:
            head = (
                f"{here} {'clip' if here == 1 else 'clips'} in {name} "
                f"({missing} on this machine) have no proxy, so nobody else in "
                f"the team can see them."
            )
        else:
            where = f" in {name}" if name else ""
            head = (
                f"{missing} clips{where} have no proxy, so nobody else in the team "
                f"can see them."
            ) if missing != 1 else (
                f"1 clip{where} has no proxy, so nobody else in the team can see it."
            )
        if missing and missing == needs_resolve:
            # ffmpeg cannot decode BRAW/R3D/CRM at any quality -- saying "I'll
            # make them" here would be a promise this machine cannot keep.
            return head + " Run the Blackmagic Proxy Generator on them."
        if not self.generation_enabled:
            return head + " Ask your admin to generate proxies for them."
        if not self._ffmpeg_ok:
            return head + " This machine has no ffmpeg, so it can only tell you."
        return head + " I'll make them while you're away from the keyboard."

    def _maybe_notify(self) -> Optional[str]:
        """At most one toast per scan cycle, per episode, per cooldown.

        Three separate brakes because they stop three different failures: the
        per-cycle one stops a 15 s tick from toasting, the episode latch stops
        the same unchanged gap re-toasting every 15 minutes, and the persisted
        cooldown stops a companion that restarts daily from re-nagging.
        """
        if not self.notify_enabled or self._notify is None:
            return None
        with self._lock:
            totals = dict(self._totals)
        missing = int(totals.get("missing", 0))
        if missing <= 0:
            # The gap closed: the next one is a new episode worth hearing about.
            self._notified_episode = False
            return None
        if self._notified_episode:
            return None
        now = self._wall_clock()
        cooldown = self.notify_cooldown if self.notify_cooldown > 0 else 0
        if cooldown and (now - self._last_notified_at) < cooldown:
            # Latched anyway: without this the cooldown would be re-evaluated
            # on every scan for a day, which is 96 identical no-ops and a log
            # line each if anyone ever adds one.
            self._notified_episode = True
            return None
        rel, gap = self._biggest_gap_project()
        text = self._notify_text(rel, totals, int(gap.get("missing", 0)))
        try:
            self._notify(text, "ccsync-companion")
        except Exception:
            log.exception("proxy gen: could not show the missing-proxy notification")
        self._notified_episode = True
        self._record_notify(now)
        return text

    # -- error memory ------------------------------------------------------
    @staticmethod
    def _fingerprint(clip: dict[str, Any]) -> tuple:
        return (float(clip.get("mtime") or 0), int(clip.get("size") or 0))

    def _is_capped(self, clip: dict[str, Any]) -> bool:
        """Has this exact file failed max_failures times already?

        Keyed on (mtime, size) as well as the path: a re-shot or re-downloaded
        file at the same name is a DIFFERENT file, and the usual cause of
        three failures in a row is a truncated download that the editor then
        re-downloads.
        """
        entry = self._failures.get(str(clip.get("path") or ""))
        if entry is None:
            return False
        if entry.get("fingerprint") != self._fingerprint(clip):
            return False
        return int(entry.get("attempts", 0)) >= max(1, self.max_failures)

    def _record_failure(self, clip: dict[str, Any], why: str) -> None:
        path = str(clip.get("path") or "")
        entry = self._failures.get(path)
        fingerprint = self._fingerprint(clip)
        if entry is None or entry.get("fingerprint") != fingerprint:
            entry = {"attempts": 0, "fingerprint": fingerprint}
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        self._failures[path] = entry
        with self._lock:
            self._failed += 1
        attempts, cap = entry["attempts"], max(1, self.max_failures)
        if attempts >= cap:
            log.warning(
                "proxy gen: giving up on %s after %d attempt(s) -- %s. It will be "
                "retried if the file changes, or on the next companion restart",
                path, attempts, why,
            )
        else:
            log.warning("proxy gen: %s failed (attempt %d/%d) -- %s",
                        path, attempts, cap, why)

    # -- encoding ----------------------------------------------------------
    def _interrupt_reason(self, forced: bool) -> Optional[str]:
        """Why the encode in flight must die NOW, or None to carry on.

        Ordered by how urgent the caller is. Pause is in here, not only in
        the gate: pause means "stop moving bytes", and a 20-minute encode
        that runs to completion after the editor pauses is exactly the thing
        they pressed the button to stop.
        """
        if self._stop_event.is_set():
            return "the companion is shutting down"
        if self._cancel.is_set():
            return "you asked it to stop"
        if self._is_paused():
            return "syncing is paused"
        if not forced and not self._user_is_away():
            # Covers idle-unknown as well as genuinely-back: seconds_idle()
            # returning None mid-encode (a locked session, a ctypes failure)
            # means we can no longer prove nobody is here, and the safe
            # reading of that is that somebody is.
            return "you're back at the keyboard"
        return None

    def _run_ffmpeg(
        self,
        cmd: list[str],
        should_stop: Callable[[], Optional[str]],
        ceiling: float,
    ) -> dict[str, Any]:
        """Run one ffmpeg argv to completion, a kill, or a timeout.

        Returns {"returncode", "stderr", "interrupted", "timed_out"}. Never
        raises -- a spawn failure comes back as returncode None with the
        message in "stderr", which the caller treats as any other failure.
        """
        result: dict[str, Any] = {
            "returncode": None, "stderr": "", "interrupted": None, "timed_out": False,
        }
        try:
            proc = _default_popen(cmd)
        except Exception as exc:
            result["stderr"] = f"could not start ffmpeg: {exc}"
            return result

        lines: Any = collections.deque(maxlen=STDERR_KEEP_LINES)
        reader = threading.Thread(
            target=_drain, args=(proc.stderr, lines),
            name="ccsync-proxy-gen-stderr", daemon=True,
        )
        reader.start()

        started = self._clock()
        while True:
            if proc.poll() is not None:
                break
            reason = should_stop()
            if reason:
                result["interrupted"] = reason
                _kill(proc)
                break
            if (self._clock() - started) > ceiling:
                result["timed_out"] = True
                _kill(proc)
                break
            # Waiting on the stop event rather than sleeping: shutdown must
            # not have to wait out a poll interval per running child.
            self._stop_event.wait(ENCODE_POLL_SECONDS)

        try:
            reader.join(timeout=5.0)
        except Exception:
            log.debug("proxy gen: stderr reader would not join", exc_info=True)
        result["returncode"] = proc.poll()
        result["stderr"] = "\n".join(lines)
        return result

    def _verify(self, partial: str, source_duration: Optional[float], forced: bool) -> Optional[str]:
        """None if the encoded file is good, else why it isn't.

        Container metadata can look perfect while the bitstream is damaged --
        measured on the b-roll archive, 17% of proxies made under concurrent
        NVENC decoded with "Invalid NAL unit size" while reporting the right
        duration -- so this is a full decode, not a probe. The duration check
        is the other half: a decode that stops cleanly after 4 of 60 seconds
        reports no errors at all.
        """
        decode = self._encode_fn(
            ffmpeg_tools.verify_decodes_cmd(self.ffmpeg_path, partial),
            lambda: self._interrupt_reason(forced),
            STUCK_FLOOR_SECONDS,
        )
        if decode.get("interrupted"):
            return decode.get("interrupted")
        if decode.get("timed_out"):
            return "the verification decode never finished"
        errors = ffmpeg_tools.count_decode_errors(decode.get("stderr"))
        if decode.get("returncode") or errors:
            return f"the proxy does not decode cleanly ({errors} error line(s))"
        if source_duration:
            try:
                info = self._probe_fn(self.ffmpeg_path, partial)
                made = float(info.get("duration_s") or 0)
            except Exception as exc:
                return f"the finished proxy could not be probed ({exc})"
            if made < (float(source_duration) * VERIFY_DURATION_RATIO):
                return (
                    f"the proxy is {made:.1f}s of a {float(source_duration):.1f}s source "
                    f"-- ffmpeg stopped early"
                )
        return None

    def _publish(self, src: str, partial: str) -> Optional[str]:
        """Move the finished .partial onto its final name. None on success.

        FIRST WRITER WINS: the existence check is repeated HERE, after the
        encode, not just before it -- lane B can deliver the real proxy while
        we encode, and BPG can finish one, and overwriting either would be
        replacing a file somebody is using with one we just made. Resolve
        also holds proxies open without share-delete (GOTCHAS:354-357), so on
        the base rig the os.replace can simply be refused; that leaves the
        .partial (excluded from every lane) and reports it.
        """
        for candidate in proxy_scan.expected_proxies(src):
            if os.path.exists(candidate):
                log.info(
                    "proxy gen: %s already has a proxy now (%s) -- discarding the one "
                    "just made rather than overwriting it",
                    os.path.basename(src), os.path.basename(candidate),
                )
                self._discard(partial)
                return None
        final = partial[: -len(proxy_scan.PARTIAL_SUFFIX)]
        try:
            os.replace(partial, final)
        except OSError as exc:
            return (
                f"could not put the finished proxy in place ({exc}) -- it is still "
                f"there as {os.path.basename(partial)}"
            )
        return None

    @staticmethod
    def _discard(partial: str) -> None:
        """Remove a partial we are not going to finish. Never raises: the
        file is excluded from every sync lane and swept/reported later, so a
        failure here costs disk space and nothing else."""
        try:
            os.remove(partial)
        except OSError:
            log.debug("proxy gen: could not remove %s", partial, exc_info=True)

    def _still_needed(self, clip: dict[str, Any]) -> Optional[str]:
        """Re-verify a queued clip against the disk. None = go ahead.

        The queue can be 15 minutes old and this is a background job on a
        shared tree: the original may be gone, may have been re-copied (so
        it is inside the settle window again), may have had its proxy
        delivered by lane B, or may be under BPG's hands right now.
        """
        path = str(clip.get("path") or "")
        if not path:
            return "no path"
        try:
            stat = os.stat(path)
        except OSError:
            return "the original is gone"
        if stat.st_size <= 0:
            return "the original is empty"
        if (time.time() - stat.st_mtime) < self.min_age_seconds:
            return "the original is still being written"
        if any(os.path.exists(p) for p in proxy_scan.expected_proxies(path)):
            # The commonest one, and deliberately silent: lane B delivering
            # the proxy is the system working, not an event.
            return "it already has a proxy"
        if proxy_scan.is_bpg_busy(path):
            return "the Blackmagic Proxy Generator is making it"
        return None

    def _build_cmd(self, clip: dict[str, Any], partial: str, nvenc: bool,
                   info: dict[str, Any]) -> list[str]:
        path = str(clip.get("path") or "")
        kind = clip.get("kind") or proxy_scan.classify_footage(path)
        if kind == proxy_scan.KIND_PREVIEW:
            # The b-roll 540p spec verbatim, so a proxy made for a YouTube
            # download doubles as its b-roll preview.
            return ffmpeg_tools.preview_proxy_cmd(
                self.ffmpeg_path, path, partial, nvenc=nvenc
            )
        return ffmpeg_tools.own_proxy_cmd(
            self.ffmpeg_path, path, partial, nvenc=nvenc,
            max_height=self.max_height, bitrate=self.bitrate,
            # The ship-blocker: Resolve's LinkProxyMedia refuses a proxy whose
            # timecode does not match the original (proxy_relink.py:35-37).
            timecode=info.get("timecode"),
        )

    def encode_once(self, clip: Optional[dict[str, Any]] = None) -> str:
        """Take one clip off the front of the queue and make its proxy.

        Returns one of RESULT_*. Never raises. The whole per-clip contract
        lives here so a test can drive it one clip at a time without a thread.
        """
        forced = False
        if clip is None:
            with self._lock:
                if not self._queue:
                    return RESULT_EMPTY
                clip = self._queue.pop(0)
                forced = self._forced
        else:
            with self._lock:
                forced = self._forced

        path = str(clip.get("path") or "")
        skip = self._still_needed(clip)
        if skip is not None:
            log.debug("proxy gen: skipping %s -- %s", path, skip)
            return RESULT_SKIPPED
        if self._is_capped(clip):
            return RESULT_SKIPPED

        partial = proxy_scan.partial_path(path)
        if not partial:
            return RESULT_SKIPPED
        try:
            os.makedirs(os.path.dirname(partial), exist_ok=True)
        except OSError as exc:
            self._record_failure(clip, f"the Proxy folder could not be made ({exc})")
            return RESULT_FAILED

        try:
            info = self._probe_fn(self.ffmpeg_path, path)
        except ffmpeg_tools.UnreadableMediaError as exc:
            # Not transient: a file with no moov atom will never grow one.
            # Counted like any other failure so the cap eventually silences it.
            self._record_failure(clip, str(exc))
            return RESULT_FAILED
        except Exception as exc:
            self._record_failure(clip, f"could not be probed ({exc})")
            return RESULT_FAILED

        duration = info.get("duration_s")
        try:
            ceiling = max(STUCK_FLOOR_SECONDS, float(duration or 0) * STUCK_DURATION_FACTOR)
        except (TypeError, ValueError):
            ceiling = STUCK_FLOOR_SECONDS

        with self._lock:
            self._current = path
        try:
            return self._encode_clip(clip, info, partial, ceiling, forced)
        finally:
            with self._lock:
                self._current = None

    def _encode_clip(self, clip: dict[str, Any], info: dict[str, Any], partial: str,
                     ceiling: float, forced: bool) -> str:
        path = str(clip.get("path") or "")
        with self._lock:
            nvenc = self._nvenc
        # NVENC first when the build has it, then EXACTLY ONE CPU retry --
        # the shape broll's build_proxy uses. NVENC being listed by
        # `-encoders` is not proof it will run (no GPU, every session taken,
        # a driver that has fallen over), and its failures are also the ones
        # that produce a file that decodes badly rather than an error.
        attempts = [True, False] if nvenc else [False]
        for index, use_nvenc in enumerate(attempts):
            cmd = self._build_cmd(clip, partial, use_nvenc, info)
            log.info(
                "proxy gen: encoding %s (%s%s)", os.path.basename(path),
                clip.get("kind") or "own", ", NVENC" if use_nvenc else ", CPU",
            )
            outcome = self._encode_fn(
                cmd, lambda: self._interrupt_reason(forced), ceiling
            )
            reason = outcome.get("interrupted")
            if reason:
                # Nothing left behind, and the clip goes back to the FRONT:
                # it is still the newest thing anybody is waiting for, and
                # dropping to the back would mean a machine whose user keeps
                # coming back never finishes the same first clip.
                self._discard(partial)
                self._requeue_front(clip)
                log.info(
                    "proxy gen: stopped encoding %s -- %s. Nothing was left behind and "
                    "it is first in line for next time",
                    os.path.basename(path), reason,
                )
                return RESULT_INTERRUPTED
            if outcome.get("timed_out"):
                self._discard(partial)
                self._record_failure(
                    clip, f"the encode was still running after {ceiling / 60:.0f} minutes",
                )
                return RESULT_FAILED

            failure: Optional[str] = None
            if outcome.get("returncode"):
                # Five lines, not three: ffmpeg explains a refused output in
                # FOUR ("Unable to choose an output format..." then three
                # boilerplate "Error ..." lines), and keeping the last three
                # cost exactly the explanatory one on the night the muxer flag
                # was missing (2026-08-11).
                tail = "\n".join((outcome.get("stderr") or "").splitlines()[-5:])
                failure = f"ffmpeg exited {outcome.get('returncode')}: {tail[:500]}"
            else:
                failure = self._verify(partial, info.get("duration_s"), forced)
                if failure and self._interrupt_reason(forced):
                    # The verification was cut short by the user coming back,
                    # not by a bad file: same handling as an interrupted encode.
                    self._discard(partial)
                    self._requeue_front(clip)
                    return RESULT_INTERRUPTED
            if failure is None:
                published = self._publish(path, partial)
                if published is not None:
                    self._record_failure(clip, published)
                    return RESULT_FAILED
                with self._lock:
                    self._generated += 1
                    # The gap shrinks as the queue drains: the tray would
                    # otherwise keep saying "12 clips have no proxy" for the
                    # rest of the 15-minute scan interval while we fix them.
                    for key in ("missing", clip.get("kind") or proxy_scan.KIND_OWN):
                        if int(self._totals.get(key, 0)) > 0:
                            self._totals[key] = int(self._totals[key]) - 1
                log.info("proxy gen: made a proxy for %s", os.path.basename(path))
                return RESULT_DONE

            self._discard(partial)
            if use_nvenc and index + 1 < len(attempts):
                log.warning(
                    "proxy gen: the GPU encode of %s failed (%s) -- retrying once on "
                    "the CPU", os.path.basename(path), failure,
                )
                continue
            self._record_failure(clip, failure)
            return RESULT_FAILED
        return RESULT_FAILED

    def _requeue_front(self, clip: dict[str, Any]) -> None:
        with self._lock:
            self._queue.insert(0, clip)

    def _drain_queue(self) -> str:
        """Encode until the gate stops saying RUNNING or the queue empties.

        Re-gates between every clip rather than draining the whole queue in
        one go: the gate is where "the user came back", "the drive went away"
        and "the editor paused" are noticed, and a 200-clip queue takes days.
        """
        state = STATE_RUNNING
        while not self._stop_event.is_set():
            result = self.encode_once()
            if result == RESULT_EMPTY:
                state = STATE_NOTHING_TO_DO
                break
            if result == RESULT_INTERRUPTED:
                break
            state = self._gate()
            self._publish_state(state)
            if state != STATE_RUNNING:
                break
        if self._cancel.is_set():
            # "Stop making proxies": drop the rest of this cycle's queue. The
            # next scheduled scan puts it all back, which is what makes this a
            # stop rather than a disable.
            with self._lock:
                self._queue = []
                self._forced = False
            self._cancel.clear()
            state = STATE_NOTHING_TO_DO
        self._publish_state(state)
        if state != STATE_RUNNING:
            with self._lock:
                if not self._queue:
                    # A forced run is over once its queue is done; the next
                    # one has to be asked for again.
                    self._forced = False
        return state
