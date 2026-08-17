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

The drain itself is PARALLEL as of 2026-08-11 (owner-approved policy: "maxed
out while the machine is idle, demote when Resolve is using the machine").
Rule 1 above is what makes that safe -- an unforced encode only ever runs on a
machine nobody is sitting at, so there is no one for four ffmpegs to slow
down -- and the one case that does deserve protection, an UNATTENDED RESOLVE
RENDER, is handled by demoting to a single encode for as long as Resolve is
running. N short-lived worker threads drain the same lock-guarded queue for
the length of one drain and are joined before it returns; encode_once() is
still the single-clip unit, unchanged, and still drivable one clip at a time
with no threads at all.

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
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import ffmpeg_tools, proxy_history, proxy_relink, proxy_scan

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

# How many clips are encoded AT ONCE, when the config does not say (2026-08-11,
# owner-approved "maxed out when idle, demote for renders"). Consumer NVENC
# allows 5+ concurrent sessions on current drivers, so 4 leaves one for anything
# else that wants the GPU; CPU-only stops at 2 because libx264/x265 already
# multithread across every core and more processes only thrash the cache. The
# cap exists because `proxy_gen_workers = 64` is a hand-edited config away and
# this feature must never be the reason a machine falls over.
DEFAULT_WORKERS_NVENC = 4
DEFAULT_WORKERS_CPU = 2
MIN_WORKERS = 1
MAX_WORKERS = 8

# How long a worker with no slot waits before asking again. Only reached while
# DEMOTED (Resolve is up), so this is the granularity at which a render
# finishing widens the drain back out -- not something an idle machine pays.
SLOT_WAIT_SECONDS = 1.0

# The demotion probe is resolve_prefs.resolve_is_running: a `tasklist` spawn on
# Windows. Asked between clip pickups, and by every waiting worker once a
# second, so it is TTL-cached on bpg._PROBE_TTL_SECONDS' precedent (MED-9,
# 2026-08-11) -- an encode lasts minutes, so a 60 s stale answer costs at most
# one clip encoded at the wrong width. The `skip_while_resolve` gate deliberately
# does NOT go through this cache: it is asked once per 15 s tick and its answer
# stops the drain entirely.
RESOLVE_PROBE_TTL_SECONDS = 60.0

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

# How often a running encode's progress line is published for the tray.
# ffmpeg emits a -progress block per output packet -- hundreds a second on a
# short clip -- and every one of them would take the lock gap() is read
# under. 1 s is finer than the tray's own 2 s refresh, so nothing is lost.
PROGRESS_PUBLISH_SECONDS = 1.0

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

# The only gate answers a BPG launch is defensible from (MED-7, 2026-08-11).
# BPG *is* Resolve, and this module never stops what it starts, so "the ffmpeg
# queue happens to be empty" is not enough: PAUSED means the editor pressed
# stop, MISCONFIGURED means the config is broken, DRIVE_ABSENT means the tree
# BPG watches is not even mounted, and RUNNING means ffmpeg is on the same GPU.
# DISABLED is in: bpg_enabled is a tri-state of its own, and an explicit true
# on a machine that does not run ffmpeg proxies is a config, not an accident.
BPG_LAUNCH_STATES = frozenset({
    STATE_DISABLED,
    STATE_NO_FFMPEG,
    STATE_NOTHING_TO_DO,
    STATE_USER_ACTIVE,
    STATE_RESOLVE_OPEN,
})

# -- destination-volume floor (COMMERCIAL_READINESS.md item 9, 2026-08-17) --
#
# A proxy is written NEXT TO ITS ORIGINAL, i.e. onto the editor's tree volume
# -- the same volume lane A/B/C are writing, the same one Resolve puts its
# cache and renders on. Filling it does not just fail the encode: it stalls
# every sync lane, and on the base rig it stalls the volume the NAS mount and
# the b-roll archive live on. Until this existed, the generator would encode
# a 4,000-clip backlog straight into the last free gigabyte and report
# nothing but muxer errors.
#
# The floor is whichever is LARGER of a fixed number of gigabytes and a
# percentage of the volume: 20 GB is meaningless on a 400 GB laptop disk and
# 5% is meaningless on a 100 TB array.
DEFAULT_FREE_SPACE_FLOOR_GB = 20.0
DEFAULT_FREE_SPACE_FLOOR_PCT = 5.0

# How long the two stability samples are apart. Deliberately short: it is a
# pause before an encode that takes minutes, and the point is to catch a file
# still GROWING, not to wait out a whole copy (the min-age gate does that).
DEFAULT_STABILITY_SECONDS = 5.0

# Path components that mean "this file is already a proxy". Encoding a proxy
# of a proxy writes `Proxy/Proxy/<stem>.mp4`, halves the quality of the only
# copy some editors have, and -- when the stems line up -- can be published
# over the very file it was made from. Structural, like every other rule in
# this module: no probing, no guessing (item 9, 2026-08-17).
PROXY_DIR_NAMES = frozenset({proxy_relink.PROXY_DIR_NAME.lower(), "proxies"})

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


def _coerce_zero_ok(cfg: dict[str, Any], key: str, default: float) -> float:
    """config_mod.coerce_numeric, except that 0 is a legal value meaning OFF.

    Item 9's three gates are all safety margins the operator must be able to
    switch off (a customer who knows their volume is full, a machine whose
    originals are never written in place). coerce_numeric rejects 0 as "not a
    positive number" and silently substitutes the default, which would turn
    "off" into "on" -- config_mod.coerce_count exists for exactly this shape
    but returns an int, and these are seconds and percentages.
    """
    try:
        value = float(cfg.get(key, default))
        if value < 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        log.error("config: %s=%r is not a number >= 0 (0 disables it) -- using %r",
                  key, cfg.get(key), default)
        return float(default)


def is_proxy_path(path: Any) -> Optional[str]:
    """Why `path` must never be used as an encode SOURCE, or None.

    Three refusals, all structural (item 9, 2026-08-17):
      - anything inside a `Proxy/` (or `proxies/`) directory at any depth --
        the fleet's one convention for where a proxy lives, and the same one
        proxy_relink.expected_proxy_paths writes to;
      - a `.partial`, which is a proxy that is not finished yet;
      - a file whose own sibling convention would make it its own output
        (`<dir>/Proxy/<stem>.mp4` == the file itself).
    A proxy of a proxy is half the quality of the only copy some editors
    have, and where the stems agree it can be published over its own source.
    """
    text = str(path or "")
    if not text:
        return None
    if text.lower().endswith(proxy_scan.PARTIAL_SUFFIX):
        return "it is a half-written proxy, not an original"
    parts = [p for p in re.split(r"[\\/]+", text)[:-1] if p]
    if any(part.lower() in PROXY_DIR_NAMES for part in parts):
        return "it is already a proxy (it lives in a Proxy folder)"
    if os.path.normcase(text) in {
            os.path.normcase(p) for p in proxy_scan.expected_proxies(text)}:
        return "it is already a proxy (encoding it would overwrite itself)"
    return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def wants_progress(cmd: Any) -> bool:
    """Does this argv ask ffmpeg to write a -progress stream to stdout?

    The encode does (see _build_cmd) and the verification decode does not,
    and they share one runner and one Popen helper -- so this is the single
    question both ask rather than two flags threaded through the call.
    """
    try:
        return "-progress" in list(cmd)
    except TypeError:
        return False


def _default_popen(cmd: list[str]) -> Any:
    """Spawn ffmpeg: no console window, below-normal priority, stderr piped.

    Priority is the difference between "the machine was a bit busy" and "the
    machine was unusable" if the user comes back mid-encode -- the 2 s kill
    poll is the real protection, this is what covers the two seconds before
    it fires. Windows takes it as a creation flag; POSIX has no equivalent,
    so it is renice-after-spawn (NOT preexec_fn, which runs between fork and
    exec in a multithreaded process and is documented as unsafe there).

    stdout is a PIPE only when the argv asked for `-progress pipe:1`, and it
    is then DRAINED on its own thread exactly like stderr: an undrained pipe
    fills its ~64 KB OS buffer and blocks the encoder for ever, which is the
    same classic deadlock STDERR_KEEP_LINES exists to avoid.
    """
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE if wants_progress(cmd) else subprocess.DEVNULL,
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


def _drain_progress(stream: Any, on_value: Callable[[str, str], None]) -> None:
    """Read ffmpeg's `-progress` stream to EOF, one `key=value` per line.

    The format is deliberately machine-readable and stable: repeating blocks
    of `out_time_us=`, `total_size=`, `speed=` and friends, terminated by
    `progress=continue` (or `end`). Anything unparseable is skipped rather
    than raised on -- this runs on its own thread, where an exception would
    go to a stderr the windowed build does not have.
    """
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            key, sep, value = line.strip().partition("=")
            if sep:
                try:
                    on_value(key, value)
                except Exception:
                    log.debug("proxy gen: progress sink raised", exc_info=True)
    except Exception:
        log.debug("proxy gen: progress reader stopped early", exc_info=True)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def parse_progress(key: str, value: str) -> Optional[tuple[str, float]]:
    """One ffmpeg progress pair as ("seconds"|"speed", number), or None.

    `out_time_us` is microseconds of OUTPUT written, which is what makes it
    a percentage when divided by the source duration -- `frame=` would need
    a frame count nothing probes, and `out_time=` is a formatted string.
    Older builds emit `out_time_ms`, which is confusingly ALSO microseconds
    (an ffmpeg quirk, not a typo here) -- both are read, both scaled the
    same way. Every other key, including `total_size`, is ignored: the
    finished proxy is measured off the disk where it cannot be wrong.
    Never raises.
    """
    try:
        text = str(value or "").strip()
        if not text or text == "N/A":
            return None
        if key in ("out_time_us", "out_time_ms"):
            return ("seconds", float(text) / 1_000_000.0)
        if key == "speed":
            # "1.23x" -- the multiple of real time ffmpeg is achieving.
            return ("speed", float(text.rstrip("xX")))
    except (TypeError, ValueError):
        return None
    return None


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
        stat_fn: Optional[Callable[[str], Any]] = None,
        disk_usage_fn: Optional[Callable[[str], Any]] = None,
        settle_sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.cfg = cfg
        self.local_root = str(cfg.get("local_root", "") or "")
        self.state_path = Path(state_dir) / NOTIFY_STATE_FILENAME
        # The ledger of what this machine has actually made (proxy_history.py).
        # Behind its own try for the same reason app.py builds the generator
        # behind one: bookkeeping must never be why a companion cannot
        # construct. None means "no history on this machine", and every call
        # site tests for it.
        self.history: Any = None
        try:
            self.history = proxy_history.ProxyHistory(
                state_dir, wall_clock=wall_clock
            )
        except Exception:
            log.exception("proxy gen: could not open the proxy history")

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
        # Item 9's three world-touching seams, injectable for the same reason
        # every other one here is: the gates must be testable with no disk.
        self._stat_fn = stat_fn or os.stat
        self._disk_usage_fn = disk_usage_fn or shutil.disk_usage
        self._settle_sleep_fn = settle_sleep_fn
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
        # Item 9 (2026-08-17) gates. All three are config-overridable because
        # the right numbers differ between a 500 GB laptop and the base rig's
        # array, and because a customer with a full disk needs a way to say
        # "I know, encode anyway" without editing the exe.
        self.free_space_floor_gb = _coerce_zero_ok(
            cfg, "proxy_gen_free_space_floor_gb", DEFAULT_FREE_SPACE_FLOOR_GB)
        self.free_space_floor_pct = _coerce_zero_ok(
            cfg, "proxy_gen_free_space_floor_pct", DEFAULT_FREE_SPACE_FLOOR_PCT)
        self.stability_seconds = _coerce_zero_ok(
            cfg, "proxy_gen_stability_seconds", DEFAULT_STABILITY_SECONDS)
        # Rehearsal mode: every gate runs, the plan is logged, ffmpeg never
        # starts and no `.partial` is created.
        self.dry_run = bool(cfg.get("proxy_dry_run", False))
        if self.dry_run:
            log.warning("proxy_dry_run = true: the generator will report what it "
                        "would encode and encode nothing")
        # None means "derive it per drain" -- the NVENC answer is only known
        # after the first scan has probed ffmpeg, so this cannot be decided here.
        self.workers = self._configured_workers(cfg)

        # -- state, ALL of it guarded by _lock. gap()/coverage() are called
        # from the tray's refresh thread while this thread rewrites them.
        self._lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []
        self._projects: dict[str, dict[str, Any]] = {}
        self._totals: dict[str, Any] = proxy_scan._empty_totals()
        self._state = STATE_NOTHING_TO_DO
        # {thread ident: path} -- ONE ENTRY PER ENCODE IN FLIGHT since the drain
        # went parallel (2026-08-11). Keyed by thread rather than by worker
        # index so a direct encode_once() call (a test, a one-off driver) is
        # registered exactly like a worker's; insertion order is start order,
        # which is what makes _current deterministic.
        self._encoding: dict[int, str] = {}
        # The last free-space refusal, published in coverage() so the
        # dashboard can say "this machine has stopped making proxies and
        # why" rather than showing a gap that never closes (item 9).
        self._low_space: Optional[str] = None
        self._low_space_notified_at: Optional[float] = None
        # {thread ident: {"path", "duration_s", "started", "out_s", "speed"}} --
        # the LIVE progress of those same encodes, kept beside _encoding rather
        # than inside it because every consumer written before 2026-08-17 reads
        # _encoding.values() as a list of paths and must keep doing so.
        self._progress: dict[int, dict[str, Any]] = {}
        # The `.partial` paths those encodes are WRITING, normcased. Keyed on
        # the output rather than the source because that is what rule 2 is
        # about, and two sources can share one output (COMP-MEDIA-2,
        # 2026-08-14 -- see _claim_partial).
        self._partials: set[str] = set()
        # Encode slots taken by the drain's workers. Held from before the clip
        # is popped to after the encode returns, so it covers the window
        # _encoding does not (the probe, the still-needed re-check) -- which is
        # the window a BPG launch must not slip through.
        self._active = 0
        # (asked_at, answer) for the demotion probe. See RESOLVE_PROBE_TTL.
        self._resolve_probe: Optional[tuple[float, bool]] = None
        self._announced_width: Optional[int] = None
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
        # Set by the FIRST worker whose encode is interrupted: one worker's
        # "you're back at the keyboard" is every worker's, and nobody may pick
        # up another clip for the rest of this drain.
        self._drain_over = threading.Event()
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

    # -- how wide the drain runs -------------------------------------------
    @staticmethod
    def _configured_workers(cfg: dict[str, Any]) -> Optional[int]:
        """`proxy_gen_workers` as 1..MAX_WORKERS, or None to derive it.

        Absent/None is the shipped state and means "derive": most machines
        should not have to know what an NVENC session is. A hand-edited
        garbage value goes the same way rather than taking construction down
        (coerce_numeric's whole reason for existing) -- it has already logged
        the error by then, and inventing a width from `"four"` would be worse
        than the derived one.
        """
        raw = cfg.get("proxy_gen_workers")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        value = int(config_mod.coerce_numeric(cfg, "proxy_gen_workers", 0))
        if value <= 0:
            return None
        return max(MIN_WORKERS, min(MAX_WORKERS, value))

    def _worker_width(self) -> int:
        """How many clips this drain may encode at once, before demotion."""
        with self._lock:
            nvenc = self._nvenc
        if self.workers is not None:
            width, why = self.workers, "proxy_gen_workers"
        else:
            width = DEFAULT_WORKERS_NVENC if nvenc else DEFAULT_WORKERS_CPU
            why = "NVENC" if nvenc else "CPU"
        width = max(MIN_WORKERS, min(MAX_WORKERS, int(width)))
        if width != self._announced_width:
            # Once per CHANGE, not per drain: a drain happens every 15 s tick
            # for as long as there is a queue, and this line is a fact about
            # the machine, not an event.
            log.info("proxy gen: encoding %d clip(s) at a time (%s)", width, why)
            self._announced_width = width
        return width

    def _resolve_running_cached(self) -> bool:
        """The DEMOTION probe: is Resolve up right now (TTL-cached)?

        Separate from _resolve_running() because the callers are different
        shapes: the gate asks once a tick and wants the freshest answer, this
        one is asked between every clip pickup and by every waiting worker
        once a second, and the real probe spawns a process (MED-9's family).
        """
        if self._resolve_running_fn is None:
            return False
        now = self._clock()
        with self._lock:
            cached = self._resolve_probe
        if cached is not None and (now - cached[0]) < RESOLVE_PROBE_TTL_SECONDS:
            return cached[1]
        # OUTSIDE the lock: this spawns tasklist, and gap() takes the same lock
        # on the tray's refresh thread.
        value = self._resolve_running()
        with self._lock:
            self._resolve_probe = (now, value)
        return value

    # -- what is encoding right now ----------------------------------------
    @staticmethod
    def _partial_key(partial: str) -> str:
        return os.path.normcase(os.path.normpath(str(partial or "")))

    def _claim_partial(self, partial: str) -> bool:
        """Take the OUTPUT path, or say it is already taken.

        Rule 2 ("never two writers on one proxy") was enforced against BPG
        (is_bpg_busy) and against lane B (_publish's re-check) but never
        against the generator itself: `_encoding` holds SOURCE paths, and two
        sources in one directory that differ only by container -- `A001.mov`
        and `A001.mp4` -- share one `Proxy/A001.mp4.partial`. Since the drain
        went parallel (2026-08-11) two workers could hold that file at once,
        interleave their writes, and publish whichever finished first over a
        file the other was still writing (COMP-MEDIA-2, 2026-08-14).

        The scan no longer queues both, so this is the backstop that also
        covers a direct encode_once(clip), a clip re-queued while its twin
        encodes, and two projects that resolve to the same directory.
        """
        key = self._partial_key(partial)
        with self._lock:
            if key in self._partials:
                return False
            self._partials.add(key)
            return True

    def _release_partial(self, partial: str) -> None:
        with self._lock:
            self._partials.discard(self._partial_key(partial))

    def _mark_encoding(self, path: str, duration_s: Any = None) -> None:
        """Register this thread's encode. `duration_s` (from the probe) is
        what turns ffmpeg's out_time into a percentage; None simply means the
        tray shows elapsed time instead of a bar, which is also what every
        pre-2026-08-17 caller passing one argument gets."""
        try:
            total = float(duration_s) if duration_s else 0.0
        except (TypeError, ValueError):
            total = 0.0
        ident = threading.get_ident()
        with self._lock:
            self._encoding[ident] = path
            self._progress[ident] = {
                "path": path,
                "name": os.path.basename(str(path or "")),
                "duration_s": total,
                "started": self._clock(),
                "out_s": 0.0,
                "speed": None,
                # None, not 0.0: the FIRST block must always publish, and a
                # zero here would make it "too soon" for any clock that
                # starts near zero -- which time.monotonic does on some
                # platforms and every injected test clock does.
                "published": None,
            }

    def _clear_encoding(self) -> None:
        ident = threading.get_ident()
        with self._lock:
            self._encoding.pop(ident, None)
            self._progress.pop(ident, None)

    def _note_progress_for(self, ident: int, key: str, value: str) -> None:
        """Sink for one ffmpeg -progress pair, called from the reader thread.

        `ident` is the ENCODING thread's, passed in because the reader runs
        on its own and its get_ident() would key an entry nothing reads.

        Rate-limited to PROGRESS_PUBLISH_SECONDS: ffmpeg emits a block per
        output packet, and taking the lock gap() is read under hundreds of
        times a second would stall the tray's refresh thread -- the exact
        cost gap() is documented to avoid.
        """
        parsed = parse_progress(key, value)
        if parsed is None:
            return
        field, number = parsed
        now = self._clock()
        with self._lock:
            entry = self._progress.get(ident)
            if entry is None:
                # The encode was cleared (killed, finished) while its reader
                # was still draining a bufferful. Nothing to update.
                return
            if field == "seconds":
                last = entry.get("published")
                if last is not None and (now - float(last)) < PROGRESS_PUBLISH_SECONDS:
                    return
                entry["published"] = now
                entry["out_s"] = number
            elif field == "speed":
                entry["speed"] = number

    def _encoding_detail(self) -> list[dict[str, Any]]:
        """Per-clip live progress for the tray. CALLER HOLDS THE LOCK.

        Percent is out_time/duration, clamped: a VFR source can report a
        few frames past its probed duration and "103%" reads as a bug. ETA
        comes from ffmpeg's own `speed` where it has one, because that is
        measured against this clip on this GPU right now -- the ledger's
        clips-per-hour is the queue-wide answer and lives in gap()["history"].
        """
        rows: list[dict[str, Any]] = []
        for entry in self._progress.values():
            total = float(entry.get("duration_s") or 0.0)
            out = float(entry.get("out_s") or 0.0)
            percent: Optional[int] = None
            eta: Optional[float] = None
            if total > 0 and out > 0:
                percent = int(max(0.0, min(1.0, out / total)) * 100)
                speed = entry.get("speed")
                try:
                    speed = float(speed) if speed else 0.0
                except (TypeError, ValueError):
                    speed = 0.0
                if speed > 0:
                    eta = max(0.0, (total - out) / speed)
            rows.append({
                "path": entry.get("path") or "",
                "name": entry.get("name") or "",
                "percent": percent,
                "eta_seconds": eta,
                "elapsed_s": max(0.0, self._clock() - float(entry.get("started") or 0.0)),
            })
        return rows

    @property
    def _current(self) -> Optional[str]:
        """The one-path view of a drain that now runs several encodes.

        Kept because every consumer written before 2026-08-11 asked "which
        clip is being encoded" and got a path or None; this answers with the
        OLDEST encode in flight, so a machine encoding one clip -- the only
        case that answer was ever unambiguous in -- behaves exactly as before.
        Read-only: gap()/block_reason() read `_encoding` directly, under the
        lock they are already holding.
        """
        with self._lock:
            for path in self._encoding.values():
                return path
        return None

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
            in_flight = list(self._encoding.values())
            left = len(self._queue) + len(in_flight)
            detail = self._encoding_detail()
        # OUTSIDE the lock, and its own: ProxyHistory keeps its rollup in
        # memory for exactly this call, so it is arithmetic and no I/O --
        # but taking two locks in one nesting order here and the other order
        # anywhere else is how a tray thread deadlocks a drain.
        history = self._history_snapshot(left)
        with self._lock:
            return {
                "missing": int(self._totals.get("missing", 0)),
                "braw": int(self._totals.get("braw", 0)),
                "needs_resolve": int(self._totals.get("needs_resolve", 0)),
                # In-flight clips are already OFF the queue, so with a parallel
                # drain "left" without them would count down to 0 while four
                # encodes were still running -- and this number is what the
                # tray tooltip and menu line show the editor (2026-08-11).
                "left": left,
                # Still a BOOL: the tray renders it as one and _menu_fingerprint
                # hashes it, so the LINES of the menu must not change every time
                # a different clip starts. The detail is in the two keys below.
                "encoding": bool(in_flight),
                "encoding_now": in_flight,
                "encoding_count": len(in_flight),
                # Per-clip percent/ETA. TOOLTIP MATERIAL ONLY: it changes every
                # second, and anything the menu fingerprint hashes must not
                # (tray._proxy_fingerprint).
                "encoding_detail": detail,
                "can_generate": bool(self.generation_enabled and self._ffmpeg_ok),
                "state": self._state,
                # This SESSION's counters, unchanged. The numbers that survive
                # a restart are in "history" -- both are here because "since
                # the companion started" is the honest answer to "is it
                # working right now" and the ledger is the answer to "what has
                # it made".
                "generated": self._generated,
                "failed": self._failed,
                "history": history,
            }

    def _history_snapshot(self, remaining: int = 0) -> dict[str, Any]:
        """The ledger's rollup, or an empty one. Never raises, never blocks:
        ProxyHistory answers this from memory precisely so gap() can."""
        if self.history is None:
            return {}
        try:
            return self.history.snapshot(remaining)
        except Exception:
            log.debug("proxy gen: the history snapshot failed", exc_info=True)
            return {}

    def coverage(self) -> dict[str, Any]:
        """What the REPORTER sends. Same rules as gap(): cached, no I/O."""
        with self._lock:
            queued = len(self._queue) + len(self._encoding)
        history = self._history_snapshot(queued)
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
                # "" rather than None: the reporter's payload is JSON either
                # way, and a dashboard testing truthiness reads both the same.
                "low_space": self._low_space or "",
                "projects": projects,
                # SCALARS ONLY (proxy_history.snapshot's contract): the
                # reporter's size guard drops the per-project map when a
                # payload gets big, and this must never be the reason it has
                # to. It is what lets the dashboard say what a machine has
                # made without a second endpoint.
                "history": history,
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
            running = len(self._encoding)
            if not running:
                return None
            left = len(self._queue) + running
        at_once = f", {running} at once" if running > 1 else ""
        return (
            f"still making video proxies so the rest of the team can see this "
            f"footage ({left} clip(s) left{at_once})"
        )

    # -- tray actions ------------------------------------------------------
    def request_run(self) -> None:
        """"Make the missing proxies now (don't wait until I'm away)"."""
        with self._lock:
            self._forced = True
            self._last_scan_at = None  # force a fresh scan on the next tick
            # The cap goes with it: scan_once() filters capped clips OUT of
            # the queue, so after a mass failure (the 0.6.1 muxer night capped
            # all 1040 clips on this rig) the one user-facing retry there is
            # would have scanned, found everything capped, and done precisely
            # nothing (MED-6, 2026-08-11). Asking for a run IS the "try it
            # again" this memory exists to be overridable by.
            capped = len(self._failures)
            self._failures = {}
        self._cancel.clear()
        self._wake.set()
        log.info(
            "proxy gen: run requested from the tray -- scanning now%s",
            f" (and forgetting {capped} earlier failure(s))" if capped else "",
        )

    def cancel_run(self) -> None:
        """"Stop making proxies". Kills the encode in flight (leaving no
        partial behind) and drops the queue for this cycle; the next scheduled
        scan refills it. Deliberately not a disable: switching the feature off
        is a config decision, not a menu click.

        With NOTHING in flight the flag is not set at all, and the queue is
        dropped here instead. `_cancel` is only ever cleared by a drain that
        ran, so setting it with no drain running latched it until the next one
        -- which then died on its first clip, after paying for a probe and a
        spawn, and dropped the whole freshly scanned queue with it
        (COMP-MEDIA-7, 2026-08-14). That is not a corner case: the tray builds
        its menu from a snapshot, so "Stop making proxies" is still on screen
        for a drain that rule 1 already ended the moment the editor touched
        the keyboard -- which is the moment they reach for the tray.
        """
        with self._lock:
            self._forced = False
            in_flight = self._active > 0 or bool(self._encoding)
            if not in_flight:
                self._queue = []
        if in_flight:
            self._cancel.set()
        self._wake.set()
        log.info(
            "proxy gen: stop requested from the tray%s",
            "" if in_flight else " -- nothing was encoding, so this cycle's "
                                "queue was dropped and nothing is left armed",
        )

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
        # `not enabled` FIRST and before anything else is computed: this runs
        # on every 15 s tick on every machine in the fleet, and BPG is
        # Windows-only -- a Mac editor was forking an idle probe ~5,700 times
        # a day for a value the launcher discards on its first line (MED-8,
        # 2026-08-11).
        if self._bpg is None or not getattr(self._bpg, "enabled", False):
            return
        if state not in BPG_LAUNCH_STATES:
            # The gate said something other than "there is nothing for ffmpeg
            # to do": paused, misconfigured or drive-absent all used to fall
            # through to a launch, so a PAUSED base rig still started
            # Resolve.exe -pg -- which nothing in this module ever stops
            # (MED-7, 2026-08-11).
            return
        with self._lock:
            # "Empty" has to mean EMPTY AND IDLE now the drain is parallel
            # (2026-08-11): the last four clips are off the queue while they
            # encode, and BPG taking the GPU while they finish is the exact
            # contention the sequencing exists to prevent. _drain_queue joins
            # its workers before returning, so this is a belt on top of braces
            # -- and the one that holds for a direct caller.
            queue_empty = not self._queue and not self._encoding and self._active <= 0
            needs_resolve = int(self._totals.get("needs_resolve", 0))
            # WHERE those clips are, not just how many: BPG watches folders and
            # takes no file list, so a launcher given only a count can do
            # nothing but open a window (bpg.py fact 3, 2026-08-13).
            watch_dirs = list(self._totals.get("needs_resolve_dirs") or ())
        try:
            self._bpg.maybe_launch(
                queue_empty=queue_empty,
                needs_resolve=needs_resolve,
                # A CALLABLE, not a value: the launcher asks only once every
                # other condition has passed, which on a machine with no BRAW
                # gap is never (MED-8).
                user_away=self._user_is_away,
                watch_dirs=watch_dirs,
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
                # Capped clips are dropped by the SCAN now, before it spends
                # its 500-per-project slots on them: filtering afterwards (the
                # line below, kept as a backstop) let a project whose newest
                # 500 clips had all failed report an empty queue for ever,
                # while the older encodable ones were never even offered
                # (COMP-MEDIA-4, 2026-08-14).
                skip_fn=self._is_capped,
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
        # usually the newest file -- a truncated download). The scan is asked
        # to leave them out in the first place (skip_fn above); this still
        # runs, for an injected scan_fn that ignores the predicate and for a
        # clip capped between the walk and here.
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
            capped = int(totals.get("capped", 0))
            log.info(
                "proxy gap: %d clip(s) in %d project(s) have no proxy -- %d queued for "
                "encoding, %d need Resolve/BPG%s",
                missing, int(totals.get("projects", 0)), len(queue),
                int(totals.get("needs_resolve", 0)),
                # The line that was missing on the 0.6.1 muxer night: a
                # machine reporting 1040 missing and 0 queued said nothing
                # about WHY it had stopped trying (COMP-MEDIA-4).
                f", {capped} given up on until the file changes or a restart"
                if capped else "",
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

        # The -progress stream, when this argv asked for one. The sink is
        # bound to THIS thread's ident here, on the encoding thread, and not
        # inside the reader -- get_ident() there would be the reader's own.
        # Daemon and never joined for progress' sake: the wait below is on the
        # process, and a reader blocked on a pipe of a child that will not die
        # must not hold the drain.
        progress_reader: Optional[threading.Thread] = None
        # getattr, not proc.stdout: an injected popen (every test's, and any
        # future one) is only contracted to offer poll/kill/wait/stderr, and
        # a missing attribute here would be an AttributeError out of the one
        # function whose contract is that it never raises.
        if getattr(proc, "stdout", None) is not None:
            ident = threading.get_ident()
            progress_reader = threading.Thread(
                target=_drain_progress,
                args=(proc.stdout, lambda k, v: self._note_progress_for(ident, k, v)),
                name="ccsync-proxy-gen-progress", daemon=True,
            )
            progress_reader.start()

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
        if progress_reader is not None:
            try:
                # Bounded like the stderr join, and for the same reason: a
                # child that survived _kill leaves this thread blocked on a
                # pipe that never closes, and the drain must still return.
                progress_reader.join(timeout=5.0)
            except Exception:
                log.debug("proxy gen: progress reader would not join", exc_info=True)
        result["returncode"] = proc.poll()
        # SNAPSHOT, inside a try: that join can time out (a _kill that failed
        # to reap the child leaves the reader appending), and iterating a deque
        # another thread is mutating raises "deque mutated during iteration" --
        # out of the one function whose contract is that it never raises
        # (MED-13, 2026-08-11).
        try:
            result["stderr"] = "\n".join(list(lines))
        except RuntimeError:
            log.debug("proxy gen: stderr was still being written -- dropping it")
            result["stderr"] = ""
        return result

    def _verify(self, partial: str, source_duration: Optional[float], forced: bool,
                ceiling: float = STUCK_FLOOR_SECONDS) -> Optional[str]:
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
            # The ENCODE's ceiling, not the bare floor: a multi-hour source
            # encoded fine and then blew the flat 30 minutes decoding its own
            # ~20 GB HEVC back off a share, so the work was thrown away and
            # three passes later the clip was capped forever, with the log
            # blaming the file (MED-2, 2026-08-11).
            ceiling,
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
        already = is_proxy_path(path)
        if already is not None:
            # NEVER encode from a proxy (item 9, 2026-08-17). Structural, and
            # checked here rather than at queue time so a clip that reaches
            # this method by any route -- the scan, a forced run, a direct
            # encode_once(clip) -- meets the same rule.
            return already
        try:
            stat = self._stat_fn(path)
        except OSError:
            return "the original is gone"
        if stat.st_size <= 0:
            return "the original is empty"
        if (time.time() - stat.st_mtime) < self.min_age_seconds:
            return "the original is still being written"
        growing = self._still_growing(clip, path, stat)
        if growing is not None:
            return growing
        if any(os.path.exists(p) for p in proxy_scan.expected_proxies(path)):
            # The commonest one, and deliberately silent: lane B delivering
            # the proxy is the system working, not an event.
            return "it already has a proxy"
        if proxy_scan.is_bpg_busy(path):
            return "the Blackmagic Proxy Generator is making it"
        return None

    def _still_growing(self, clip: dict[str, Any], path: str,
                       now_stat: Any) -> Optional[str]:
        """TWO samples, `stability_seconds` apart, of (size, mtime).

        The single mtime sample this replaces (item 9, 2026-08-17) misses the
        case it was written for. rclone, Syncthing and every camera-card
        copier set the mtime when they CREATE the file and again when they
        finish, so a multi-GB transfer spends minutes looking 'settled' with
        an mtime older than min_age and a size that is still climbing. ffmpeg
        then reads a truncated file, and the proxy that gets published is
        four minutes of a forty-minute interview -- a silent wrong answer,
        the worst kind this module can give.

        Size AND mtime, because either alone has a blind spot: an in-place
        rewrite keeps the size, and a preallocated file keeps the mtime.

        THE FIRST SAMPLE IS USUALLY FREE. proxy_scan already recorded
        (size, mtime) for every queued clip, and the queue is normally
        minutes old, so `now_stat` is the second sample and no waiting is
        needed. The bounded wait below is the fallback for a clip handed
        straight to encode_once() (a forced run, a direct call) where the
        scan sample is missing or younger than `stability_seconds`.
        """
        try:
            wait = float(self.stability_seconds)
        except (TypeError, ValueError):
            wait = DEFAULT_STABILITY_SECONDS
        if wait <= 0:
            return None

        def _changed(before_size: Any, before_mtime: Any, elapsed: float) -> Optional[str]:
            if (int(before_size), float(before_mtime)) == (
                    int(now_stat.st_size), float(now_stat.st_mtime)):
                return None
            log.info(
                "proxy gen: %s changed (%s -> %s bytes) over %.0fs -- still being "
                "written, leaving it for the next scan",
                os.path.basename(path), before_size, now_stat.st_size, elapsed,
            )
            return "the original is still being written (it changed while we watched)"

        scan_size, scan_mtime = clip.get("size"), clip.get("mtime")
        with self._lock:
            last_scan = self._last_scan_at
        if scan_size is not None and scan_mtime is not None and last_scan is not None:
            elapsed = float(self._clock()) - float(last_scan)
            if elapsed >= wait:
                return _changed(scan_size, scan_mtime, elapsed)

        if self._settle_sleep_fn is not None:
            self._settle_sleep_fn(wait)
        elif self._stop_event.wait(wait):
            return "the companion is shutting down"
        try:
            second = self._stat_fn(path)
        except OSError:
            return "the original went away while it was being checked"
        if (second.st_size, second.st_mtime) != (now_stat.st_size, now_stat.st_mtime):
            log.info(
                "proxy gen: %s changed (%s -> %s bytes) over %.0fs -- still being "
                "written, leaving it for the next scan",
                os.path.basename(path), now_stat.st_size, second.st_size, wait,
            )
            return "the original is still being written (it changed while we watched)"
        return None

    def free_space_shortfall(self, target: str) -> Optional[str]:
        """Why this volume must not be encoded onto, or None to go ahead.

        The floor is max(`proxy_gen_free_space_floor_gb`,
        `proxy_gen_free_space_floor_pct` of the volume) -- see
        DEFAULT_FREE_SPACE_FLOOR_GB. "Cannot tell" is NOT a refusal: a volume
        whose free space cannot be read (an exotic mount, a permission quirk)
        is the machine most likely to be the only one making proxies, and
        this gate is a safety margin, not a correctness rule.
        """
        # The `Proxy/` directory usually does not exist yet -- this gate runs
        # BEFORE anything is created, deliberately -- and disk_usage on an
        # absent path raises, which "cannot tell" would turn into a pass. Walk
        # up to the nearest directory that does exist; it is on the same
        # volume, which is the only thing being measured.
        directory = os.path.dirname(str(target or "")) or "."
        for _ in range(16):
            if os.path.isdir(directory):
                break
            parent = os.path.dirname(directory)
            if not parent or parent == directory:
                break
            directory = parent
        try:
            usage = self._disk_usage_fn(directory)
            free = float(usage.free)
            total = float(usage.total)
        except Exception:
            log.debug("proxy gen: could not read free space on %s", directory,
                      exc_info=True)
            return None
        gb = 1024.0 ** 3
        try:
            floor_bytes = max(float(self.free_space_floor_gb) * gb,
                              total * (float(self.free_space_floor_pct) / 100.0))
        except (TypeError, ValueError):
            floor_bytes = DEFAULT_FREE_SPACE_FLOOR_GB * gb
        if floor_bytes <= 0 or free >= floor_bytes:
            return None
        return (f"only {free / gb:.1f} GB free on the drive holding {directory} "
                f"(CCSync keeps {floor_bytes / gb:.1f} GB clear so the sync lanes "
                f"and Resolve's cache do not run out)")

    def _surface_low_space(self, why: str) -> None:
        """Say it once per cooldown, in the log, the tray and coverage().

        Skipping silently is what makes a full disk look like "the proxies
        just never got made" -- the failure this whole module exists to stop
        being invisible."""
        with self._lock:
            self._low_space = why
            last = self._low_space_notified_at
        now = self._wall_clock()
        cooldown = self.notify_cooldown if self.notify_cooldown > 0 else 0
        if cooldown and last is not None and (now - last) < cooldown:
            log.debug("proxy gen: still low on space -- %s", why)
            return
        with self._lock:
            self._low_space_notified_at = now
        log.warning("proxy gen: not encoding -- %s", why)
        if self._notify is not None:
            try:
                self._notify(
                    f"CCSync stopped making video proxies: {why}. Free some space and "
                    "they will resume on their own.",
                    "ccsync-companion: low disk space",
                )
            except Exception:
                log.debug("proxy gen: could not show the low-space notification",
                          exc_info=True)

    def _build_cmd(self, clip: dict[str, Any], partial: str, nvenc: bool,
                   info: dict[str, Any]) -> list[str]:
        path = str(clip.get("path") or "")
        kind = clip.get("kind") or proxy_scan.classify_footage(path)
        if kind == proxy_scan.KIND_PREVIEW:
            # The b-roll 540p spec verbatim, so a proxy made for a YouTube
            # download doubles as its b-roll preview.
            cmd = ffmpeg_tools.preview_proxy_cmd(
                self.ffmpeg_path, path, partial, nvenc=nvenc
            )
        else:
            cmd = ffmpeg_tools.own_proxy_cmd(
                self.ffmpeg_path, path, partial, nvenc=nvenc,
                max_height=self.max_height, bitrate=self.bitrate,
                # The ship-blocker: Resolve's LinkProxyMedia refuses a proxy
                # whose timecode does not match the original
                # (proxy_relink.py:35-37).
                timecode=info.get("timecode"),
            )
        return self._with_progress(cmd)

    @staticmethod
    def _with_progress(cmd: list[str]) -> list[str]:
        """Ask ffmpeg for a machine-readable progress stream on stdout.

        Added HERE rather than in ffmpeg_tools' builders because those two
        argvs are the shared spec for what a CC Sync proxy IS -- the
        b-roll indexer builds the same files from the same functions -- and
        how one caller watches its own encode is not part of that. Position
        1 because `-progress` is a global option and everything after the
        output path would be a different (and rejected) argv; the output
        stays LAST, which several callers rely on.
        """
        if not cmd or wants_progress(cmd):
            return list(cmd)
        return [cmd[0], "-progress", "pipe:1"] + list(cmd[1:])

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
        # FREE SPACE, before anything is claimed or created (item 9,
        # 2026-08-17). Not counted as a failure: the file is fine, the disk
        # is not, and capping the clip after three attempts would silence the
        # one condition an editor must be told about.
        shortfall = self.free_space_shortfall(partial)
        if shortfall is not None:
            self._surface_low_space(shortfall)
            return RESULT_SKIPPED
        with self._lock:
            self._low_space = None
        if self.dry_run:
            log.info("proxy gen [dry-run]: would encode %s -> %s (%s)",
                     path, partial[: -len(proxy_scan.PARTIAL_SUFFIX)],
                     clip.get("kind") or proxy_scan.classify_footage(path))
            return RESULT_SKIPPED
        if not self._claim_partial(partial):
            # Another worker is writing this exact file for a DIFFERENT
            # original (same stem, other container). Skipped rather than
            # requeued: whatever that encode publishes covers this clip too,
            # since the coverage convention is the same stem (COMP-MEDIA-2).
            log.debug(
                "proxy gen: skipping %s -- another encode is already writing %s",
                path, os.path.basename(partial),
            )
            return RESULT_SKIPPED
        try:
            try:
                os.makedirs(os.path.dirname(partial), exist_ok=True)
            except OSError as exc:
                why = f"the Proxy folder could not be made ({exc})"
                self._record_failure(clip, why)
                self._record_history(proxy_history.RESULT_FAILED, clip, error=why)
                return RESULT_FAILED

            try:
                info = self._probe_fn(self.ffmpeg_path, path)
            except ffmpeg_tools.UnreadableMediaError as exc:
                # Not transient: a file with no moov atom will never grow one.
                # Counted like any other failure so the cap eventually silences it.
                self._record_failure(clip, str(exc))
                # Recorded like any other failure, and the one an editor is
                # most likely to go looking for: a truncated download is the
                # usual cause, and the ledger is where "which clips never made
                # it?" gets answered after the log has rotated.
                self._record_history(proxy_history.RESULT_FAILED, clip, error=str(exc))
                return RESULT_FAILED
            except Exception as exc:
                why = f"could not be probed ({exc})"
                self._record_failure(clip, why)
                self._record_history(proxy_history.RESULT_FAILED, clip, error=why)
                return RESULT_FAILED

            duration = info.get("duration_s")
            try:
                ceiling = max(
                    STUCK_FLOOR_SECONDS, float(duration or 0) * STUCK_DURATION_FACTOR
                )
            except (TypeError, ValueError):
                ceiling = STUCK_FLOOR_SECONDS

            # The probed duration goes in with the path: it is the denominator
            # of every percentage the tray shows, and this is the one place
            # that has it.
            self._mark_encoding(path, duration)
            try:
                return self._encode_clip(clip, info, partial, ceiling, forced)
            finally:
                self._clear_encoding()
        finally:
            self._release_partial(partial)

    @staticmethod
    def _encoder_name(cmd: Any) -> str:
        """The `-c:v` value from an argv -- "hevc_nvenc", "libx265", "h264".

        Read off the command rather than passed down from the nvenc flag,
        because the flag says which ATTEMPT this is and the ledger should
        record what actually ran: the CPU retry after a failed GPU encode is
        the case where the two disagree, and it is the interesting one.
        """
        try:
            argv = list(cmd)
            return str(argv[argv.index("-c:v") + 1])
        except (ValueError, IndexError, TypeError):
            return ""

    def _record_history(self, result: str, clip: dict[str, Any], *,
                        info: Optional[dict[str, Any]] = None,
                        encoder: str = "", proxy_bytes: int = 0,
                        encode_s: float = 0.0, error: str = "") -> None:
        """Append one finished clip to the ledger. Never raises, never blocks
        an outcome: proxy_history swallows its own I/O errors and this only
        adds the "no history on this machine" case around them."""
        if self.history is None:
            return
        try:
            self.history.record(
                result,
                clip.get("path"),
                project=str(clip.get("project") or ""),
                kind=str(clip.get("kind") or ""),
                encoder=encoder,
                src_bytes=clip.get("size") or 0,
                proxy_bytes=proxy_bytes,
                duration_s=(info or {}).get("duration_s") or 0.0,
                encode_s=encode_s,
                error=error,
            )
        except Exception:
            log.debug("proxy gen: could not record history for %r",
                      clip.get("path"), exc_info=True)

    def _encode_clip(self, clip: dict[str, Any], info: dict[str, Any], partial: str,
                     ceiling: float, forced: bool) -> str:
        path = str(clip.get("path") or "")
        # Wall time for the WHOLE clip -- encode, verification decode and
        # publish. That is what "how long did this clip cost" means to
        # somebody reading the ledger, and the verify is a full decode of the
        # file we just wrote, so it is a real share of the cost.
        clip_started = self._clock()
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
                why = f"the encode was still running after {ceiling / 60:.0f} minutes"
                self._record_failure(clip, why)
                self._record_history(
                    proxy_history.RESULT_FAILED, clip, info=info,
                    encoder=self._encoder_name(cmd), error=why,
                    encode_s=self._clock() - clip_started,
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
                failure = self._verify(partial, info.get("duration_s"), forced, ceiling)
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
                    self._record_history(
                        proxy_history.RESULT_FAILED, clip, info=info,
                        encoder=self._encoder_name(cmd), error=published,
                        encode_s=self._clock() - clip_started,
                    )
                    return RESULT_FAILED
                self._record_history(
                    proxy_history.RESULT_DONE, clip, info=info,
                    encoder=self._encoder_name(cmd),
                    # Stat the file we just put in place. 0 when _publish
                    # discarded ours because a proxy arrived under the OTHER
                    # extension while we encoded -- the clip really is covered,
                    # which is why this is still a "done", and the bytes we
                    # wrote really are gone.
                    proxy_bytes=self._published_size(partial),
                    encode_s=self._clock() - clip_started,
                )
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
                # NOT recorded: the CPU retry is about to run and one clip is
                # one ledger line. A GPU attempt that the retry rescues is a
                # log detail, not a failure the editor should count.
                continue
            self._record_failure(clip, failure)
            self._record_history(
                proxy_history.RESULT_FAILED, clip, info=info,
                encoder=self._encoder_name(cmd), error=failure,
                encode_s=self._clock() - clip_started,
            )
            return RESULT_FAILED
        return RESULT_FAILED

    @staticmethod
    def _published_size(partial: str) -> int:
        """Bytes of the proxy that `partial` became, or 0 if it is not there."""
        try:
            return int(os.path.getsize(partial[: -len(proxy_scan.PARTIAL_SUFFIX)]))
        except OSError:
            return 0

    def _requeue_front(self, clip: dict[str, Any]) -> None:
        # Several workers can requeue in the same second now (the user comes
        # back and every unforced encode aborts at once). Front-insertion order
        # is completion order, so the last clip to abort ends up first -- all of
        # them are back at the head of a queue that is about to be re-gated, and
        # picking a different order between four equally-newest clips would buy
        # nothing (2026-08-11).
        with self._lock:
            self._queue.insert(0, clip)

    def _claim_slot(self, width: int) -> bool:
        """Take one of this drain's encode slots, or say no.

        DEMOTION lives here (2026-08-11, owner-approved): while Resolve is
        running the drain acts as ONE worker, because an unattended render
        wants the same NVENC/NVDEC sessions four proxies would take. Re-asked
        between clip pickups, never mid-encode -- a clip already being encoded
        runs to its end or is killed by the idle gate, not by a demotion.
        Note this applies to a FORCED run too, on the same reasoning that makes
        `proxy_gen_skip_while_resolve_running` apply to one: the button says
        "don't wait until I'm away", not "take the GPU off the render".
        """
        allowed = 1 if (width > 1 and self._resolve_running_cached()) else width
        with self._lock:
            if self._active >= allowed:
                return False
            self._active += 1
            return True

    def _release_slot(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    def _drain_worker(self, width: int, outcome: dict[str, Any]) -> None:
        """One worker: pick up a clip, encode it, re-gate, repeat.

        The body of what used to be the whole serial drain, with the two
        parallel-only rules on top: a slot has to be claimed before each
        pickup (that is where demotion bites), and an interruption ends the
        drain for EVERY worker rather than only for the one that noticed.
        """
        while not (self._stop_event.is_set() or self._drain_over.is_set()):
            if not self._claim_slot(width):
                # Demoted, or momentarily full. Waiting rather than exiting:
                # Resolve closing mid-drain must widen us back out without
                # having to wait for the next tick.
                if self._stop_event.wait(SLOT_WAIT_SECONDS):
                    return
                continue
            try:
                result = self.encode_once()
            finally:
                self._release_slot()
            if result == RESULT_EMPTY:
                outcome["state"] = STATE_NOTHING_TO_DO
                return
            if result == RESULT_INTERRUPTED:
                self._drain_over.set()
                return
            state = self._gate()
            self._publish_state(state)
            if state != STATE_RUNNING:
                outcome["state"] = state
                return

    def _drain_queue(self) -> str:
        """Encode until the gate stops saying RUNNING or the queue empties.

        Re-gates between every clip rather than draining the whole queue in
        one go: the gate is where "the user came back", "the drive went away"
        and "the editor paused" are noticed, and a 200-clip queue takes days.

        N workers do that at once (2026-08-11) -- see _worker_width and
        _claim_slot for how many and why. THIS thread is worker 0, so a drain
        one clip wide spawns nothing at all, and every helper is joined before
        the state is returned: the caller's next move is _maybe_launch_bpg,
        and "the ffmpeg queue is empty" must not mean "four of them are
        finishing up".
        """
        width = self._worker_width()
        outcome: dict[str, Any] = {"state": STATE_RUNNING}
        self._drain_over.clear()
        helpers = [
            threading.Thread(
                target=self._drain_worker, args=(width, outcome),
                name=f"ccsync-proxy-gen-{index}", daemon=True,
            )
            for index in range(1, width)
        ]
        for helper in helpers:
            helper.start()
        try:
            self._drain_worker(width, outcome)
        finally:
            for helper in helpers:
                # UNBOUNDED, deliberately: the only thing that keeps a worker
                # is an ffmpeg that will not die, which held the serial drain
                # just as hard. Returning while one still encodes would hand a
                # "queue empty" to BPG and let two encoders onto one GPU.
                helper.join()
        # An interruption is not a gate answer: the serial drain broke out
        # still calling itself RUNNING and left the next tick to re-gate, and
        # that is deliberately preserved -- it is the answer that stops
        # _maybe_launch_bpg dead.
        state = STATE_RUNNING if self._drain_over.is_set() else outcome["state"]
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
