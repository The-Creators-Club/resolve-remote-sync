"""Keep a machine from vanishing part-way through an upload.

Two guards, one cause. Both live here because they answer the same question
-- "is anything actually moving right now?" -- from the same predicate.

On 2026-08-02 ruskin's machine went away at 02:44:35 with three camera
originals part-uploaded -- 19.3 GB of partials on the server, and nothing on
his screen had ever suggested that switching off was a bad idea. rclone has
no resume for SFTP uploads (``--partial-suffix`` only names the temp file),
so every one of those files restarts from zero. The bytes are not at risk;
the editor's evening is.

Windows already has the right mechanism for this, and it is not a message
box: a top-level window that answers WM_QUERYENDSESSION with FALSE puts the
shutdown on the "This app is preventing you from shutting down" screen,
where ``ShutdownBlockReasonCreate`` supplies our sentence. The editor still
gets a "Shut down anyway" button -- this is a speed bump with an
explanation, never a lock. Two properties matter and are load-bearing:

  * We block only while something is genuinely moving. A machine that is up
    to date shuts down with no interruption at all, because a guard that
    cries wolf gets ignored on the night it is right.
  * Any failure of the guard ITSELF allows the shutdown. A bug in here must
    never be able to trap someone at their desk, so the reason callback is
    fully fault-isolated and every unexpected path returns "allow".

That covers shutdown, restart and log-off. It does NOT cover sleep, which
never sends WM_QUERYENDSESSION at all -- and sleep is the likelier way a
machine goes quiet at 02:44. So the second guard, _WindowsKeepAwake, holds
ES_SYSTEM_REQUIRED while a lane is busy, which stops the idle timer from
sleeping the machine out from under a transfer. Its constraints:

  * ES_SYSTEM_REQUIRED only, never ES_DISPLAY_REQUIRED. The screen still
    blanks on schedule; we are keeping the upload alive, not the monitor.
  * The execution state is per-THREAD and only lasts as long as the thread
    that set it, so the keep-awake loop must stay alive to hold it -- it is
    not a fire-and-forget call.
  * It cannot stop a DELIBERATE sleep (Start -> Sleep, or a closing lid).
    Nothing in user space can, and the shutdown guard above is what covers
    the deliberate case.
  * Failing open means letting the machine sleep. A bug in here that held
    the state forever would keep someone's PC awake all night, so every
    error path releases.

macOS gets the same two guards with less authority, because the platform
gives less. There is no equivalent of ShutdownBlockReasonCreate: nothing an
unprivileged app can do puts a sentence on the logout screen, and an app
that answers applicationShouldTerminate_ with NSTerminateCancel during a
system logout is simply killed a few seconds later. So the parity is:

  * Sleep -- FULL parity. ``caffeinate -i -w <our pid>`` is the exact
    analogue of ES_CONTINUOUS | ES_SYSTEM_REQUIRED: idle SYSTEM sleep only
    (never -d, the display flag), held for as long as the child lives, and
    -w means it dies with us even if the companion is killed outright.
  * Quit -- REDUCED parity. The companion answers applicationShouldTerminate_
    once with NSTerminateCancel and a notification saying what is still
    moving; a second attempt inside the same episode always goes through.
    That is a warning, not a block, and it is deliberately weaker than
    Windows' because macOS gives us nowhere to put the explanation.
  * Logout / ``launchctl bootout`` -- SIGTERM, which python does not handle
    by default in a way that runs our shutdown path. The handler installed
    here turns it into a graceful stop instead of a process that vanishes
    mid-write. It cannot delay anything; it only makes the exit tidy.

The pure decision logic lives in describe_pending() and
should_cancel_terminate() so it can be tested on any platform; only the
_Windows* classes touch ctypes, and only the _Darwin* ones touch pyobjc --
lazily, inside the methods, so this module imports fine on a machine that
has never heard of AppKit.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterable, Optional

from .sync.base import STATE_ERROR, STATE_PAUSED, STATE_SYNCING

# "ccsync.shutdown_guard", NOT __name__. setup_logging() only ever attaches
# handlers to the "ccsync" logger, so a record emitted under
# "ccsync_companion.shutdown_guard" propagates to the unconfigured ROOT
# logger instead -- and in the windowed (console=False) PyInstaller build
# sys.stderr is None, so logging.lastResort swallows WARNING+ silently and
# INFO/DEBUG vanish outright. Every line this module has ever logged was
# invisible in both companion.log and tray -> Copy diagnostics, which is
# exactly the pair of features an editor asks about after a machine went
# away mid-upload. Every other module in the package uses "ccsync.<x>";
# test_shutdown_guard.py now asserts that for all of them.
log = logging.getLogger("ccsync.shutdown_guard")

# ShutdownBlockReasonCreate silently fails past MAX_STR_BLOCKREASON (256
# wide chars including the terminator). Failing to set a reason while still
# returning FALSE gives the editor a blocked shutdown with NO explanation --
# the worst possible outcome -- so the text is truncated here instead.
MAX_REASON_CHARS = 255

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016

_WINDOW_CLASS = "CCSyncShutdownGuard"
_WINDOW_TITLE = "CCSync"

# stop()'s two bounds (SYNC-15): how long it waits for a window that may
# still be coming up, then for the pump thread to notice the WM_CLOSE.
STOP_READY_WAIT_SECONDS = 2.0
STOP_JOIN_SECONDS = 3.0

# SetThreadExecutionState flags. ES_CONTINUOUS makes the request stick until
# withdrawn (without it the call only resets the idle timer once, which is
# the subtly-broken version of this feature); ES_SYSTEM_REQUIRED is the
# system idle timer alone. ES_DISPLAY_REQUIRED is deliberately absent -- an
# upload does not need the monitor on, and holding it would leave editors
# staring at a screen that never blanks.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

# How often the keep-awake loop re-asks whether anything is moving. Far
# below any sleep timer worth having, and cheap: it reads lane statuses.
KEEP_AWAKE_POLL_SECONDS = 30.0

# --- macOS ------------------------------------------------------------------
#
# caffeinate is part of the base system (/usr/bin, since 10.8) and is the
# supported way to hold off idle sleep without entitlements or a helper.
#   -i  idle SYSTEM sleep only. Never -d: that is ES_DISPLAY_REQUIRED, and
#       an upload does not need the monitor on.
#   -w  wait for OUR pid and exit when it goes. Belt and braces for the case
#       the companion is SIGKILLed and never gets to terminate the child --
#       without it a crash would leave the Mac awake until the next reboot.
CAFFEINATE_PATH = "/usr/bin/caffeinate"

# How long to give caffeinate to go away after SIGTERM before SIGKILL. It has
# no cleanup to do, so this is generous.
CAFFEINATE_STOP_GRACE_SECONDS = 5.0

# NSApplicationTerminateReply. Cancel DELAYS the quit (there is no macOS
# equivalent of the Windows block screen); Now allows it.
NS_TERMINATE_CANCEL = 0
NS_TERMINATE_NOW = 1

# One termination "episode". The hard requirement is that the guard can never
# trap someone: the FIRST attempt while a lane is moving gets a notification
# and a cancel, and any attempt within this window of that cancel goes
# straight through -- clicking Quit twice always quits. A genuinely separate
# attempt later (a different evening, a different shutdown) starts a fresh
# episode and is worth warning about again.
TERMINATE_EPISODE_SECONDS = 120.0

# --- liveness bounds (PendingTracker) --------------------------------------
#
# "Busy" on its own is not a reason to keep a machine awake or to interrupt
# a shutdown, because every lane reports busy from a NUMBER, not from bytes
# arriving: SyncthingLane sets STATE_SYNCING purely from needTotalItems /
# outgoing needItems, so a NAS that went away overnight with four unreceived
# files leaves lane C "syncing" forever. That held ES_CONTINUOUS |
# ES_SYSTEM_REQUIRED permanently (the PC never slept again until the
# companion restarted) and put "still syncing" on every shutdown screen with
# zero bytes in flight -- which is precisely the cry-wolf failure this module
# says in its own docstring it must not have.
#
# So a lane only counts as blocking while it is demonstrably ALIVE:
#   * its status has CHANGED within PROGRESS_STALE_SECONDS (any of state,
#     queued, transferring, bytes_done/total, last_sync), and
#   * nothing positively tells us there is no peer to move bytes to.
# A lane that has just become busy is always given the benefit of the doubt
# (its first sample starts the clock), so a genuine transfer is never
# suppressed at the moment it starts.
PROGRESS_STALE_SECONDS = 180.0

# Backstop for the case staleness cannot see: a lane whose numbers churn but
# never finish (rclone wedged in SFTP retries, re-listing the same backlog
# every pass). After this much CONTINUOUS blocking we stand down until the
# lanes actually settle -- a machine held awake for a third of a day has
# stopped being a warning and become a fault.
MAX_HOLD_SECONDS = 8 * 3600.0


# --- formatting (local copies: tray.py imports pystray at module scope) -----

def _human_bytes(n: Optional[int]) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def _human_duration(seconds: Optional[float]) -> str:
    try:
        secs = int(float(seconds or 0))
    except (TypeError, ValueError):
        return ""
    if secs < 60:
        return ""
    if secs < 3600:
        return f"about {secs // 60} min"
    return f"about {secs // 3600}h {(secs % 3600) // 60}m"


# --- the decision ----------------------------------------------------------

def busy_lanes(statuses: Iterable) -> list:
    """The lanes that have work outstanding, in the order given.

    A lane counts as busy when it is actively syncing or still has queued
    items; PAUSED and ERROR lanes do not, because in neither case is shutting
    down going to lose progress that continuing to sit there would have
    saved. One malformed status must not decide the whole question, so it is
    skipped rather than allowed to raise.
    """
    busy: list = []
    for status in statuses or []:
        try:
            state = str(getattr(status, "state", "") or "")
            if state in (STATE_PAUSED, STATE_ERROR):
                continue
            queued = int(getattr(status, "queued", 0) or 0)
            if state != STATE_SYNCING and queued <= 0:
                continue
            busy.append(status)
        except Exception:
            log.debug("shutdown guard: skipping unreadable lane status", exc_info=True)
            continue
    return busy


def _render_pending(busy: list) -> Optional[str]:
    """The sentence Windows should show for already-judged-busy lanes."""
    if not busy:
        return None
    bytes_left = 0
    have_bytes = False
    eta_seconds = 0.0
    for status in busy:
        try:
            total = getattr(status, "bytes_total", None)
            done = getattr(status, "bytes_done", None)
            if total:
                remaining = int(total) - int(done or 0)
                if remaining > 0:
                    bytes_left += remaining
                    have_bytes = True
            eta = getattr(status, "eta_seconds", None)
            if eta:
                # Lanes run concurrently, so the wait is the slowest one, not
                # the sum. Overstating it would push people to switch off.
                eta_seconds = max(eta_seconds, float(eta))
        except Exception:
            log.debug("shutdown guard: skipping unreadable lane status", exc_info=True)
            continue

    head = "CCSync is still syncing"
    if have_bytes:
        head += f" -- {_human_bytes(bytes_left)} left"
        pretty_eta = _human_duration(eta_seconds)
        if pretty_eta:
            head += f", {pretty_eta}"
    return (
        head + ". Any file part-way uploaded has to start again from the "
        "beginning next time you switch on."
    )[:MAX_REASON_CHARS]


def describe_pending(statuses: Iterable) -> Optional[str]:
    """The sentence Windows should show, or None to allow the shutdown.

    None means "nothing is moving" -- the overwhelmingly common case, and the
    one that must stay silent.

    STATELESS: this answers "does any lane have work outstanding", which is
    only half the question. Production goes through PendingTracker.describe(),
    which adds the liveness bound a single snapshot cannot have (see
    PROGRESS_STALE_SECONDS).
    """
    return _render_pending(busy_lanes(statuses))


def _progress_fingerprint(status: Any) -> tuple:
    """Everything about a lane that MOVES while bytes move.

    Deliberately includes queued/transferring/last_sync as well as the byte
    counters: lane C reports no byte totals at all, so a folder finishing and
    the need count dropping is the only movement it ever shows."""
    def _num(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    return (
        str(getattr(status, "state", "") or ""),
        _num(getattr(status, "queued", 0)),
        _num(getattr(status, "transferring", 0)),
        _num(getattr(status, "bytes_done", 0)),
        _num(getattr(status, "bytes_total", 0)),
        str(getattr(status, "last_sync", "") or ""),
    )


def _lane_key(status: Any) -> str:
    """The name PendingTracker files a lane's samples under."""
    return str(getattr(status, "name", "") or "")


def _positive_or(value: Any, fallback: float, label: str) -> float:
    """A positive float, or `fallback` with a line saying why. Never raises."""
    try:
        number = float(value)
        if number > 0:
            return number
    except (TypeError, ValueError):
        pass
    log.error("shutdown guard: %s=%r is not a positive number -- using %r",
              label, value, fallback)
    return float(fallback)


class PendingTracker:
    """describe_pending() with a memory: the liveness bound (see above).

    One instance per app, shared by BOTH guards -- the keep-awake loop's
    30-second poll is what keeps the progress samples fresh, and the shutdown
    guard then reads the same verdict rather than deciding from one snapshot
    taken at the instant someone clicked Shut down.

    Never raises. Every failure path in here means "not blocking": a bug in
    the liveness check must be able to cost a warning, never to trap someone
    at a machine that will not switch off or keep a PC awake all night.
    """

    def __init__(
        self,
        stale_seconds: float = PROGRESS_STALE_SECONDS,
        max_hold_seconds: float = MAX_HOLD_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # Both are config keys (keep_awake_stale_seconds /
        # keep_awake_max_hold_seconds), so both arrive here hand-editable.
        # config.coerce_numeric already screens them, but this is the layer
        # that would MISBEHAVE rather than crash on a bad one -- a stale
        # window of 0 marks every lane stalled on its second sample, i.e. it
        # silently switches both guards off -- so it screens them again.
        self._stale_seconds = _positive_or(stale_seconds, PROGRESS_STALE_SECONDS,
                                           "stale_seconds")
        self._max_hold_seconds = _positive_or(max_hold_seconds, MAX_HOLD_SECONDS,
                                              "max_hold_seconds")
        self._clock = clock
        self._lock = threading.Lock()
        # lane name -> (fingerprint, monotonic time it last CHANGED)
        self._seen: dict[str, tuple[tuple, float]] = {}
        # lane name -> monotonic time it started holding (SYNC-16: per lane,
        # not one clock for the whole tracker)
        self._holding_since: dict[str, float] = {}
        self._stale_logged: set = set()
        self._ceiling_logged: set = set()

    def reset(self) -> None:
        """Forget every sample (used by tests and anything that restarts the
        lanes -- a fresh start deserves a fresh grace period)."""
        with self._lock:
            self._seen.clear()
            self._holding_since.clear()
            self._stale_logged = set()
            self._ceiling_logged = set()

    def describe(
        self,
        statuses: Iterable,
        peer_states: Optional[dict] = None,
    ) -> Optional[str]:
        """The sentence to show, or None to allow the shutdown/sleep.

        `peer_states` is {lane name: True/False/None}. False means we
        POSITIVELY know there is nowhere for this lane's bytes to go (lane C
        with no connected Syncthing device); None/absent means unknown, which
        never vetoes -- "can't tell" must not silence a real warning.
        """
        try:
            now = self._clock()
            busy = busy_lanes(statuses)
            # Windows calls the shutdown guard on ITS thread while the
            # keep-awake loop polls on another; both land here.
            with self._lock:
                alive = [s for s in busy if self._is_alive(s, now, peer_states)]
                self._forget_settled(busy)
                return self._apply_ceiling(alive, now)
        except Exception:
            log.exception("shutdown guard: liveness check failed -- not blocking")
            return None

    # -- internals ----------------------------------------------------------

    def _is_alive(self, status: Any, now: float, peer_states: Optional[dict]) -> bool:
        name = str(getattr(status, "name", "") or "")
        if self._peer_state(status, name, peer_states) is False:
            self._log_once(
                name, "%s reports work outstanding but has no connected peer -- "
                "not counting it as a reason to stay on", name or "a lane",
            )
            return False
        try:
            fingerprint = _progress_fingerprint(status)
        except Exception:
            log.debug("shutdown guard: unreadable progress fingerprint", exc_info=True)
            return True
        previous = self._seen.get(name)
        if previous is None or previous[0] != fingerprint:
            # First sighting, or something moved: the clock restarts here, so
            # a lane that has only just gone busy always counts.
            self._seen[name] = (fingerprint, now)
            self._stale_logged.discard(name)
            return True
        if (now - previous[1]) < self._stale_seconds:
            return True
        self._log_once(
            name,
            "%s has reported the same backlog for %.0f minutes with nothing moving "
            "-- treating it as stalled, not as a sync worth staying on for",
            name or "a lane", (now - previous[1]) / 60.0,
        )
        return False

    @staticmethod
    def _peer_state(status: Any, name: str, peer_states: Optional[dict]) -> Optional[bool]:
        if peer_states:
            try:
                state = peer_states.get(name)
            except Exception:
                state = None
            if state is not None:
                return bool(state)
        # Also honoured off the status itself, so a lane that grows a
        # peer_connected field later needs no change here.
        state = getattr(status, "peer_connected", None)
        return None if state is None else bool(state)

    def _forget_settled(self, busy: list) -> None:
        """Drop lanes that are no longer busy, so one that goes idle and then
        busy again gets a fresh grace period instead of inheriting a stale
        timestamp -- and so the dict cannot grow without bound."""
        live_names = set()
        for status in busy:
            live_names.add(str(getattr(status, "name", "") or ""))
        for name in [n for n in self._seen if n not in live_names]:
            self._seen.pop(name, None)
            self._stale_logged.discard(name)

    def _apply_ceiling(self, alive: list, now: float) -> Optional[str]:
        # SYNC-16 (2026-08-11): the hold clock is PER LANE. It used to be one
        # clock for the tracker, so a lane that churns for eight hours without
        # settling (lane C's need count ticking over a huge library, rclone
        # wedged in retries) stood the whole guard down -- and a genuine 200 GB
        # lane A ingest that started an hour later got no keep-awake at all and
        # the machine idle-slept mid-upload.
        live_names = {_lane_key(status) for status in alive}
        for name in [n for n in self._holding_since if n not in live_names]:
            self._holding_since.pop(name, None)
            self._ceiling_logged.discard(name)
        holding = []
        for status in alive:
            name = _lane_key(status)
            since = self._holding_since.setdefault(name, now)
            if (now - since) < self._max_hold_seconds:
                holding.append(status)
                continue
            if name not in self._ceiling_logged:
                self._ceiling_logged.add(name)
                log.warning(
                    "%s has been busy for %.1f hours without settling -- standing "
                    "down for it: no more shutdown warnings or keep-awake on its "
                    "account until it does",
                    name or "a lane", (now - since) / 3600.0,
                )
        if not holding:
            return None
        return _render_pending(holding)

    def _log_once(self, key: str, message: str, *args: Any) -> None:
        if key in self._stale_logged:
            return
        self._stale_logged.add(key)
        log.info(message, *args)


# --- the guard -------------------------------------------------------------

class ShutdownGuard:
    """No-op base: every non-Windows platform, and Windows when disabled.

    make_shutdown_guard() picks the real implementation. start()/stop() are
    idempotent and never raise -- a guard that cannot start is a lost warning,
    not a reason to fail the companion's startup.
    """

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def active(self) -> bool:
        return False


class _WindowsShutdownGuard(ShutdownGuard):
    def __init__(
        self,
        reason_fn: Callable[[], Optional[str]],
        block_fn: Optional[Callable[[int, str], None]] = None,
        unblock_fn: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._reason_fn = reason_fn
        self._block_fn = block_fn
        self._unblock_fn = unblock_fn
        self._thread: Optional[threading.Thread] = None
        self._hwnd: Optional[int] = None
        self._ready = threading.Event()
        self._blocking = False
        # ctypes callbacks are garbage-collected like any other object; a
        # WNDPROC that gets collected while Windows still holds the pointer
        # is a crash inside USER32 with no Python traceback. Hold the
        # reference for as long as the WINDOW CLASS that names it is
        # registered -- and the class is registered PROCESS-wide, so it
        # outlives this object unless we unregister it (see
        # _release_window_class).
        self._wndproc_ref = None
        self._class_registered = False

    # -- the part worth testing --------------------------------------------

    def handle_query_end_session(self, hwnd: int) -> int:
        """WM_QUERYENDSESSION: 0 blocks the shutdown, 1 allows it.

        Split out from the window procedure so the policy can be tested
        without a window, a message pump, or Windows.
        """
        try:
            reason = self._reason_fn()
        except Exception:
            # Our own bug must never strand someone at a machine that will
            # not turn off.
            log.exception("shutdown guard: reason callback failed -- allowing shutdown")
            self._clear_block(hwnd)
            return 1

        if not reason:
            self._clear_block(hwnd)
            return 1

        if not self._set_block(hwnd, str(reason)[:MAX_REASON_CHARS]):
            # No reason on the block screen = a shutdown that refuses with no
            # explanation. Allow it instead.
            log.warning("shutdown guard: could not set a block reason -- allowing shutdown")
            return 1

        log.warning("shutdown requested while syncing -- blocking: %s", reason)
        return 0

    def _set_block(self, hwnd: int, reason: str) -> bool:
        fn = self._block_fn
        if fn is None:
            return False
        try:
            fn(hwnd, reason)
        except Exception:
            log.exception("shutdown guard: ShutdownBlockReasonCreate failed")
            return False
        self._blocking = True
        return True

    def _clear_block(self, hwnd: int) -> None:
        if not self._blocking:
            return
        self._blocking = False
        fn = self._unblock_fn
        if fn is None:
            return
        try:
            fn(hwnd)
        except Exception:
            log.exception("shutdown guard: ShutdownBlockReasonDestroy failed")

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        # is_alive(), not "is not None": the pump thread ends on ANY failure
        # inside it (ctypes unavailable, RegisterClassW/CreateWindowExW
        # failing, the message loop raising) and used to leave `_thread`
        # holding a dead Thread object -- so start() early-returned forever
        # and the guard could never be restarted, while `active` quietly
        # reported False and (before the logger fix above) the exception
        # explaining it went nowhere.
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._ready.clear()
        try:
            self._thread = threading.Thread(
                target=self._pump, name="ccsync-shutdown-guard", daemon=True
            )
            self._thread.start()
        except Exception:
            log.exception("shutdown guard: could not start its thread")
            self._thread = None
            return
        # The window has to exist before Windows can deliver anything to it,
        # but never hold up startup for it.
        if not self._ready.wait(5.0):
            log.warning("shutdown guard: window did not come up within 5s")

    def stop(self) -> None:
        hwnd = self._hwnd
        thread = self._thread
        if thread is not None and thread.is_alive() and not hwnd:
            # SYNC-15 (2026-08-11): the window may simply not be up YET --
            # start()'s 5 s _ready.wait is a bound, not a guarantee. This used
            # to clear both references regardless while posting WM_CLOSE only
            # `if hwnd`, so the pump thread and the window it went on to create
            # were orphaned for the life of the process and the next start()
            # built a SECOND pump on top of them.
            self._ready.wait(STOP_READY_WAIT_SECONDS)
            hwnd = self._hwnd
        if hwnd:
            try:
                import ctypes
                from ctypes import wintypes

                user32 = ctypes.WinDLL("user32", use_last_error=True)
                # Same truncation trap as GetModuleHandleW, in the other
                # direction: an HWND passed as a bare Python int binds as
                # c_int, so the message would be posted to the low half of
                # the handle -- some other window, or none.
                user32.PostMessageW.argtypes = [
                    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
                ]
                user32.PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0)
            except Exception:
                log.exception("shutdown guard: could not post WM_CLOSE")
        if thread is not None and thread.is_alive():
            thread.join(timeout=STOP_JOIN_SECONDS)
            if thread.is_alive():
                # Keep the references (SYNC-15): the pump still owns its
                # window, so start()'s is_alive() check must keep seeing it
                # rather than spawning a rival, and a later stop() still has
                # an hwnd to post WM_CLOSE to.
                log.warning("shutdown guard: its thread did not exit within 3s -- "
                            "keeping it rather than starting a second pump")
                return
        self._hwnd = None
        self._thread = None

    @property
    def active(self) -> bool:
        return self._hwnd is not None

    # -- window + message pump ---------------------------------------------

    def _release_window_class(self, user32: Any, hinstance: Any) -> None:
        """Give the process-wide window class back, then drop the WNDPROC.

        RegisterClassW registers CLASS NAME -> our ctypes callback for the
        whole process, and stop() used to leave both in place. A second guard
        in the same process then took the ERROR_CLASS_ALREADY_EXISTS branch
        and its CreateWindowExW dispatched WM_NCCREATE into the first guard's
        callback -- which by then may have been garbage-collected. That is a
        non-deterministic crash inside USER32 with no Python traceback; the
        build/start/stop/drop sequence in test_shutdown_guard.py is exactly
        the shape that reaches it.

        Order matters and is the whole point: the callback reference is only
        released once Windows has accepted the unregister (which it refuses
        while any window of the class still exists). If it refuses, we keep
        holding the reference -- a few hundred wasted bytes beats an access
        violation."""
        if not self._class_registered or user32 is None:
            if not self._class_registered:
                self._wndproc_ref = None
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32.UnregisterClassW.restype = wintypes.BOOL
            user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
            if user32.UnregisterClassW(_WINDOW_CLASS, hinstance):
                self._class_registered = False
                self._wndproc_ref = None
            else:
                log.debug(
                    "shutdown guard: UnregisterClassW refused (err=%s) -- keeping the "
                    "window procedure alive", ctypes.get_last_error(),
                )
        except Exception:
            log.debug("shutdown guard: could not unregister its window class", exc_info=True)

    def _pump(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            log.exception("shutdown guard: ctypes unavailable")
            self._ready.set()
            return

        user32 = None
        hinstance = None
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            LRESULT = wintypes.LPARAM  # pointer-sized and signed, like LRESULT
            WNDPROC = ctypes.WINFUNCTYPE(
                LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HANDLE),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            # Explicit restypes on EVERY handle-returning call. ctypes
            # defaults to c_int, which silently truncates a 64-bit handle to
            # its low half: GetModuleHandleW's real 0x7ff7946c0000 arrived as
            # garbage and RegisterClassW died with an access violation inside
            # USER32 -- no Python traceback, just a dead thread and an editor
            # who never gets the warning.
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            user32.DefWindowProcW.restype = LRESULT
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
            ]
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            user32.GetMessageW.restype = wintypes.BOOL
            user32.GetMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
            ]
            user32.DispatchMessageW.restype = LRESULT
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.ShutdownBlockReasonCreate.restype = wintypes.BOOL
            user32.ShutdownBlockReasonCreate.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.ShutdownBlockReasonDestroy.restype = wintypes.BOOL
            user32.ShutdownBlockReasonDestroy.argtypes = [wintypes.HWND]

            def _block(hwnd, reason):
                if not user32.ShutdownBlockReasonCreate(wintypes.HWND(hwnd), reason):
                    raise OSError(ctypes.get_last_error(), "ShutdownBlockReasonCreate")

            def _unblock(hwnd):
                user32.ShutdownBlockReasonDestroy(wintypes.HWND(hwnd))

            if self._block_fn is None:
                self._block_fn = _block
            if self._unblock_fn is None:
                self._unblock_fn = _unblock

            def _wndproc(hwnd, msg, wparam, lparam):
                try:
                    if msg == WM_QUERYENDSESSION:
                        return self.handle_query_end_session(hwnd)
                    if msg == WM_ENDSESSION:
                        return 0
                    if msg == WM_DESTROY:
                        user32.PostQuitMessage(0)
                        return 0
                except Exception:
                    log.exception("shutdown guard: window procedure failed")
                    if msg == WM_QUERYENDSESSION:
                        return 1
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc_ref = WNDPROC(_wndproc)

            hinstance = kernel32.GetModuleHandleW(None)
            wndclass = WNDCLASSW()
            wndclass.lpfnWndProc = self._wndproc_ref
            wndclass.hInstance = hinstance
            wndclass.lpszClassName = _WINDOW_CLASS
            if user32.RegisterClassW(ctypes.byref(wndclass)):
                # Only the guard that REGISTERED the class may unregister it
                # (see _release_window_class); a guard reusing an existing
                # registration must leave the owner's callback alone.
                self._class_registered = True
            else:
                err = ctypes.get_last_error()
                # 1410 = ERROR_CLASS_ALREADY_EXISTS: a previous guard in this
                # process registered it. Reuse it rather than giving up.
                if err != 1410:
                    raise OSError(err, "RegisterClassW")

            # A real top-level window, just never shown: WM_QUERYENDSESSION is
            # not delivered to message-only (HWND_MESSAGE) windows, which is
            # the obvious-looking implementation and the wrong one.
            hwnd = user32.CreateWindowExW(
                0, _WINDOW_CLASS, _WINDOW_TITLE, 0,
                0, 0, 0, 0, None, None, hinstance, None,
            )
            if not hwnd:
                raise OSError(ctypes.get_last_error(), "CreateWindowExW")
            self._hwnd = int(hwnd)
            log.info("shutdown guard: watching for shutdown (hwnd=%s)", self._hwnd)
        except Exception:
            log.exception("shutdown guard: could not create its window -- no warning on shutdown")
            self._hwnd = None
            # Half-built is still registered: give the class back here too,
            # or the next guard reuses a callback nobody is holding.
            self._release_window_class(user32, hinstance)
            self._ready.set()
            return
        finally:
            self._ready.set()

        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            log.exception("shutdown guard: message loop stopped")
        finally:
            self._hwnd = None
            # The window is gone by now (WM_CLOSE -> WM_DESTROY -> quit), so
            # UnregisterClassW can succeed -- which is the only moment it is
            # safe to let go of the WNDPROC.
            self._release_window_class(user32, hinstance)


# --- macOS: the same question, a quieter answer ----------------------------

def should_cancel_terminate(
    now: float,
    last_cancel_at: Optional[float],
    busy: bool,
    episode_seconds: float = TERMINATE_EPISODE_SECONDS,
) -> bool:
    """Whether to answer applicationShouldTerminate_ with NSTerminateCancel.

    The entire macOS quit policy, kept pure so it can be tested without
    AppKit -- which on Windows is the only way it can be tested at all.

    Cancel at most ONCE per episode: warn on the first quit while bytes are
    moving, then get out of the way. Someone who quits again straight after
    reading the notification has answered the question, and a guard that
    argues twice is a guard people force-quit past.
    """
    if not busy:
        return False
    if last_cancel_at is None:
        return True
    try:
        elapsed = float(now) - float(last_cancel_at)
    except (TypeError, ValueError):
        # Unusable clock: allow. Same discipline as everywhere else in here.
        return False
    if elapsed < 0:
        # A clock that went backwards. Treat it as "we just warned".
        return False
    return elapsed >= _positive_or(episode_seconds, TERMINATE_EPISODE_SECONDS,
                                   "episode_seconds")


class _DarwinShutdownGuard(ShutdownGuard):
    """SIGTERM into a graceful stop, plus a one-shot warning on Quit.

    Two independent halves, and the first is the load-bearing one:

      * SIGTERM. ``launchctl bootout`` and logout both send it, and the
        default disposition kills the interpreter where it stands -- part-way
        through a state write, with no lane shutdown. The handler here turns
        it into the companion's normal shutdown path. This works with or
        without pyobjc.
      * applicationShouldTerminate_. Best effort, and only that: pystray's
        darwin backend sets NO NSApplication delegate at all (it uses its
        IconDelegate purely as the status-item/menu target), so there is
        nothing of pystray's to patch -- we install our own delegate on
        NSApp, and only when nothing else has claimed the slot. If AppKit is
        missing, or someone else owns the delegate, this half silently does
        nothing and the editor loses a warning, never a quit.
    """

    def __init__(
        self,
        reason_fn: Callable[[], Optional[str]],
        on_shutdown: Optional[Callable[[], None]] = None,
        notify_fn: Optional[Callable[[str], None]] = None,
        signal_fn: Optional[Callable[[int, Any], Any]] = None,
        install_delegate_fn: Optional[Callable[[], Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        episode_seconds: float = TERMINATE_EPISODE_SECONDS,
    ) -> None:
        self._reason_fn = reason_fn
        self._on_shutdown = on_shutdown
        self._notify_fn = notify_fn
        self._signal_fn = signal_fn
        self._install_delegate_fn = install_delegate_fn
        self._clock = clock
        self._episode_seconds = episode_seconds
        self._last_cancel_at: Optional[float] = None
        self._sigterm_installed = False
        self._previous_sigterm: Any = None
        # Holds the ObjC delegate alive while NSApp points at it (see
        # _install_app_delegate); NSApplication keeps only a weak reference.
        self._delegate_ref: Any = None
        # Whatever undoes the delegate install, or None if nothing is
        # installed. Doubles as the "did the AppKit half work" flag.
        self._undo_delegate: Optional[Callable[[], None]] = None

    # -- the part worth testing --------------------------------------------

    def handle_should_terminate(self) -> int:
        """applicationShouldTerminate_: CANCEL delays the quit, NOW allows it.

        Split out from the delegate for the same reason the Windows guard
        splits out handle_query_end_session: the policy is the part that can
        ruin an evening, and it must be testable without the platform.

        EVERY unexpected path returns NOW. A bug in here must be able to cost
        a warning, never to leave someone unable to quit their menu-bar app.
        """
        try:
            reason = self._reason_fn()
        except Exception:
            log.exception("shutdown guard: reason callback failed -- allowing quit")
            return NS_TERMINATE_NOW

        try:
            now = float(self._clock())
            cancel = should_cancel_terminate(
                now, self._last_cancel_at, bool(reason), self._episode_seconds
            )
        except Exception:
            log.exception("shutdown guard: quit policy failed -- allowing quit")
            return NS_TERMINATE_NOW

        if not cancel:
            if reason:
                log.warning("quit requested while syncing -- already warned, allowing: %s",
                            reason)
            return NS_TERMINATE_NOW

        self._last_cancel_at = now
        text = str(reason)[:MAX_REASON_CHARS]
        self._notify(text)
        log.warning("quit requested while syncing -- asking once: %s", text)
        return NS_TERMINATE_CANCEL

    def handle_sigterm(self, signum: int = 0, frame: Any = None) -> None:
        """SIGTERM (logout, ``launchctl bootout``) -> the normal shutdown.

        Never raises: a signal handler that throws lands the exception in
        whatever unrelated line of code happened to be running.
        """
        log.warning("SIGTERM received (logout or launchctl bootout) -- shutting down")
        try:
            callback = self._on_shutdown
            if callback is not None:
                callback()
        except Exception:
            log.exception("shutdown guard: shutdown callback failed on SIGTERM")
        # Whoever had SIGTERM before us may well be what actually ends the
        # process (pystray installs nothing for it, but a future caller
        # might). Chaining keeps us additive rather than in the way.
        previous = self._previous_sigterm
        # SYNC-7 (2026-08-11): this was `previous is not self.handle_sigterm`,
        # which never fired -- attribute access builds a NEW bound method every
        # time, so the identity test was always True. _restore_signal_handler
        # deliberately leaves our handler installed when it cannot restore, so
        # a later start() captures it as _previous_sigterm and the next SIGTERM
        # recursed to the recursion limit, one logged traceback per frame.
        # Compared by __func__/__self__ rather than == so a foreign handler's
        # own __eq__ can never run inside a signal handler.
        is_self = (getattr(previous, "__func__", None) is type(self).handle_sigterm
                   and getattr(previous, "__self__", None) is self)
        if callable(previous) and not is_self:
            try:
                previous(signum, frame)
            except Exception:
                log.exception("shutdown guard: previous SIGTERM handler failed")
        # If nothing else ends us, the shutdown callback is expected to --
        # and launchd escalates to SIGKILL a few seconds later regardless, so
        # a hang here costs a hard kill, not a stuck logout.

    def _notify(self, text: str) -> None:
        fn = self._notify_fn
        if fn is None:
            fn = _osascript_notify
        try:
            fn(text)
        except Exception:
            # The warning is the whole feature, but failing to show it is not
            # a reason to fail the cancel decision that has already been made.
            log.exception("shutdown guard: could not show the quit warning")

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self._install_signal_handler()
        if self._undo_delegate is not None:
            return
        fn = self._install_delegate_fn or self._install_app_delegate
        try:
            undo = fn()
        except Exception:
            log.exception("shutdown guard: could not hook Quit -- no warning on quit")
            undo = None
        self._undo_delegate = undo if callable(undo) else None

    def stop(self) -> None:
        undo, self._undo_delegate = self._undo_delegate, None
        if undo is not None:
            try:
                undo()
            except Exception:
                log.exception("shutdown guard: could not release the app delegate")
        self._restore_signal_handler()

    @property
    def active(self) -> bool:
        """Whether ANY half is in place -- either is worth having alone."""
        return self._sigterm_installed or self._undo_delegate is not None

    # -- SIGTERM ------------------------------------------------------------

    def _install_signal_handler(self) -> None:
        if self._sigterm_installed:
            return
        if self._on_shutdown is None:
            # Installing a handler that does nothing would SWALLOW SIGTERM and
            # leave `launchctl bootout` hanging until launchd's SIGKILL --
            # strictly worse than the default disposition.
            log.debug("shutdown guard: no shutdown callback -- leaving SIGTERM alone")
            return
        # If the hardware spike shows signal.signal never fires because the
        # main thread is parked inside NSApp.run() (Python signal handlers
        # only run between bytecodes there), swap this seam for
        # PyObjCTools.MachSignals.signal -- it is what pystray's own darwin
        # backend uses for SIGINT, for exactly this reason.
        fn = self._signal_fn or signal.signal
        try:
            # ValueError off the main thread; AttributeError on a platform
            # with no SIGTERM. Both mean "no graceful logout", never a crash.
            self._previous_sigterm = fn(signal.SIGTERM, self.handle_sigterm)
        except Exception:
            log.warning("shutdown guard: could not install a SIGTERM handler -- a logout "
                        "will kill the companion outright", exc_info=True)
            return
        self._sigterm_installed = True
        log.info("shutdown guard: SIGTERM will shut the companion down gracefully")

    def _restore_signal_handler(self) -> None:
        if not self._sigterm_installed:
            return
        self._sigterm_installed = False
        fn = self._signal_fn or signal.signal
        previous = self._previous_sigterm
        self._previous_sigterm = None
        if previous is None:
            # signal.signal() returns None for a handler it cannot describe;
            # putting None back would raise, so leave ours in place.
            return
        try:
            fn(signal.SIGTERM, previous)
        except Exception:
            log.debug("shutdown guard: could not restore the previous SIGTERM handler",
                      exc_info=True)

    # -- AppKit (never imported anywhere but here) --------------------------

    def _install_app_delegate(self) -> Optional[Callable[[], None]]:
        """Make NSApp ask us before it quits. Returns the undo, or None.

        Deliberately timid. pystray owns the NSApplication and its run loop;
        the delegate slot merely happens to be one thing it does not use, and
        the moment that stops being true (a future pystray, or another
        library) this backs out rather than fighting for it.
        """
        try:
            import objc  # noqa: F401  (proves pyobjc is really there)
            import AppKit
        except Exception:
            log.info("shutdown guard: pyobjc/AppKit unavailable -- no warning on quit")
            return None

        try:
            app = AppKit.NSApplication.sharedApplication()
            existing = app.delegate()
            if existing is not None:
                log.info("shutdown guard: something else owns the app delegate (%r) -- "
                         "leaving it alone, no warning on quit", existing)
                return None

            delegate = _app_delegate_class().alloc().init()
            # Same trick pystray uses on its own IconDelegate: a plain python
            # attribute on an ObjC instance, so the class itself stays a
            # process-wide singleton (see _app_delegate_class).
            delegate.guard = self
            app.setDelegate_(delegate)
        except Exception:
            log.exception("shutdown guard: could not install the app delegate")
            return None

        # The delegate is held weakly by NSApplication, so this reference is
        # what keeps it alive -- exactly the WNDPROC problem in the Windows
        # guard, in a different language.
        self._delegate_ref = delegate

        def _undo() -> None:
            try:
                if app.delegate() is delegate:
                    app.setDelegate_(None)
            finally:
                self._delegate_ref = None

        log.info("shutdown guard: watching for Quit")
        return _undo


# Defined ONCE per process by _app_delegate_class(), never per guard.
_APP_DELEGATE_CLASS: Any = None


def _app_delegate_class() -> Any:
    """The NSApplicationDelegate subclass that answers Quit.

    Built lazily and cached, because defining an ObjC class registers its
    NAME with the runtime and doing that twice raises. The tray stops and
    restarts its guards (pause/resume, a config reload), and the second
    start must not turn into an exception where a warning should be.
    """
    global _APP_DELEGATE_CLASS
    if _APP_DELEGATE_CLASS is not None:
        return _APP_DELEGATE_CLASS

    import Foundation

    class CCSyncAppDelegate(Foundation.NSObject):
        def applicationShouldTerminate_(self, sender):  # noqa: N802 (ObjC selector)
            try:
                guard = getattr(self, "guard", None)
                if guard is None:
                    return NS_TERMINATE_NOW
                return guard.handle_should_terminate()
            except Exception:
                log.exception("shutdown guard: delegate failed -- allowing quit")
                return NS_TERMINATE_NOW

    _APP_DELEGATE_CLASS = CCSyncAppDelegate
    return CCSyncAppDelegate


def _osascript_notify(text: str) -> None:
    """The pending-bytes sentence, as a macOS notification.

    Same mechanism pystray's own darwin backend uses for notify(), and for
    the same reason: no pyobjc, no entitlements, no user-notification centre
    API that Apple has deprecated twice. Fire-and-forget -- this is called on
    the main thread inside applicationShouldTerminate_, where waiting on a
    subprocess would freeze the menu bar.
    """
    message = str(text).replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{message}" with title "CCSync"'
    _spawn_detached(["/usr/bin/osascript", "-e", script])


def make_shutdown_guard(
    reason_fn: Callable[[], Optional[str]],
    enabled: bool = True,
    on_shutdown: Optional[Callable[[], None]] = None,
) -> ShutdownGuard:
    """The guard for this platform. Always returns something startable.

    `on_shutdown` is the companion's own shutdown path. macOS uses it to turn
    SIGTERM (logout, ``launchctl bootout``) into a graceful stop; Windows
    ignores it, because WM_ENDSESSION arrives at the window instead.
    """
    if not enabled:
        return ShutdownGuard()
    if sys.platform == "win32":
        return _WindowsShutdownGuard(reason_fn)
    if sys.platform == "darwin":
        return _DarwinShutdownGuard(reason_fn, on_shutdown=on_shutdown)
    return ShutdownGuard()


# --- keep-awake ------------------------------------------------------------

class KeepAwakeGuard:
    """No-op base: every non-Windows platform, and Windows when disabled."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def held(self) -> bool:
        return False


class _WindowsKeepAwake(KeepAwakeGuard):
    """Hold off the system idle timer for as long as a lane is busy.

    The loop exists because SetThreadExecutionState is scoped to the calling
    thread: the state evaporates when that thread ends, so something has to
    stay alive holding it. Polling also means the state is withdrawn within
    KEEP_AWAKE_POLL_SECONDS of the sync finishing, rather than lingering
    until the companion exits.
    """

    def __init__(
        self,
        busy_fn: Callable[[], bool],
        set_state_fn: Optional[Callable[[int], int]] = None,
        poll_seconds: float = KEEP_AWAKE_POLL_SECONDS,
    ) -> None:
        self._busy_fn = busy_fn
        self._set_state_fn = set_state_fn
        self._poll_seconds = poll_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    # -- the part worth testing --------------------------------------------

    def _is_busy(self) -> bool:
        try:
            return bool(self._busy_fn())
        except Exception:
            # Fail towards letting the machine sleep: a guard bug that kept
            # every editor's PC awake overnight would be worse than a missed
            # upload, and the next poll will pick it up if it recovers.
            log.exception("keep-awake: busy check failed -- allowing sleep")
            return False

    def apply_once(self) -> bool:
        """Re-assert (or withdraw) the request. Returns whether it is held.

        Only calls Windows on a CHANGE. Re-asserting ES_CONTINUOUS every
        poll would work, but it makes powercfg's requests list churn and
        buries any real diagnosis in noise.
        """
        busy = self._is_busy()
        if busy == self._held:
            return self._held
        flags = (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) if busy else ES_CONTINUOUS
        fn = self._set_state_fn
        if fn is None:
            return self._held
        try:
            if not fn(flags):
                # Returns the previous state, or 0 on failure.
                log.warning("keep-awake: SetThreadExecutionState(0x%x) failed", flags)
                return self._held
        except Exception:
            log.exception("keep-awake: SetThreadExecutionState failed")
            return self._held
        self._held = busy
        log.info(
            "keep-awake: %s the system idle timer while syncing",
            "holding off" if busy else "released",
        )
        return self._held

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        # is_alive(), for the same reason as the shutdown guard's start():
        # the loop thread exits on any failure (ctypes unavailable, the loop
        # raising) and a dead Thread object left here made the guard
        # permanently un-restartable.
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._stop.clear()
        try:
            self._thread = threading.Thread(
                target=self._loop, name="ccsync-keep-awake", daemon=True
            )
            self._thread.start()
        except Exception:
            log.exception("keep-awake: could not start its thread")
            self._thread = None

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        self._stop.set()
        if thread is not None and thread.is_alive():
            # The loop releases the state in its own finally, and it must be
            # the SAME thread that set it -- releasing from here would be a
            # no-op on a state this thread never held.
            thread.join(timeout=max(2.0, self._poll_seconds / 4))

    def _loop(self) -> None:
        if self._set_state_fn is None:
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.SetThreadExecutionState.restype = wintypes.DWORD
                kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
                self._set_state_fn = kernel32.SetThreadExecutionState
            except Exception:
                log.exception("keep-awake: ctypes unavailable -- machines may sleep mid-sync")
                return
        try:
            while True:
                self.apply_once()
                if self._stop.wait(self._poll_seconds):
                    break
        except Exception:
            log.exception("keep-awake: loop stopped")
        finally:
            # Never leave the idle timer suppressed by a thread that is
            # about to die -- on this thread, while it still exists.
            try:
                if self._held and self._set_state_fn is not None:
                    self._set_state_fn(ES_CONTINUOUS)
            except Exception:
                log.exception("keep-awake: could not release the idle timer")
            self._held = False


def caffeinate_command(pid: Optional[int] = None) -> list:
    """``caffeinate -i -w <our pid>`` -- built here so it can be asserted.

    -i and NOT -d: idle SYSTEM sleep only, the exact analogue of
    ES_SYSTEM_REQUIRED. -w <pid> makes the child outlive nothing: it exits
    when we do, even if we are killed with no chance to tidy up.
    """
    return [CAFFEINATE_PATH, "-i", "-w", str(os.getpid() if pid is None else pid)]


def _spawn_detached(argv: list) -> Any:
    """Start a child that is fully detached from our stdio and our signals.

    start_new_session so a ^C or a session-wide signal aimed at the companion
    does not also hit caffeinate, and DEVNULL throughout because the
    companion's own stdout is None in a windowed/LaunchAgent build -- a child
    inheriting that is a broken pipe waiting to happen.
    """
    try:
        from .resolve_bridge import sanitized_child_env

        env = sanitized_child_env()
    except Exception:
        log.debug("keep-awake: could not sanitise the child environment", exc_info=True)
        env = dict(os.environ)
    return subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
        argv,
        env=env,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class _DarwinKeepAwake(KeepAwakeGuard):
    """Hold off the system idle timer with caffeinate, for as long as a lane
    is busy.

    Structurally the twin of _WindowsKeepAwake -- same poll, same "only act
    on a change", same release-in-the-finally -- with a child process where
    Windows has a per-thread flag. The differences that matter:

      * The hold lives in ANOTHER process, so it survives this thread but not
        this machine's login session, and it has to be reaped. A caffeinate
        we forget about keeps a Mac awake indefinitely, which is the exact
        failure this module exists to avoid causing.
      * That child can die on its own (someone kills it, the binary is
        missing on a stripped image). The poll notices and starts another,
        rather than quietly believing it still holds something.
      * Failing to spawn means the machine may sleep mid-upload. That is the
        fail-open direction, and it is logged once rather than every poll.
    """

    def __init__(
        self,
        busy_fn: Callable[[], bool],
        spawn_fn: Optional[Callable[[list], Any]] = None,
        poll_seconds: float = KEEP_AWAKE_POLL_SECONDS,
        stop_grace_seconds: float = CAFFEINATE_STOP_GRACE_SECONDS,
    ) -> None:
        self._busy_fn = busy_fn
        self._spawn_fn = spawn_fn
        self._poll_seconds = poll_seconds
        self._stop_grace_seconds = stop_grace_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._child: Any = None
        self._held = False
        self._spawn_failure_logged = False

    @property
    def held(self) -> bool:
        return self._held

    # -- the part worth testing --------------------------------------------

    def _is_busy(self) -> bool:
        try:
            return bool(self._busy_fn())
        except Exception:
            # Fail towards letting the machine sleep, exactly as on Windows.
            log.exception("keep-awake: busy check failed -- allowing sleep")
            return False

    def apply_once(self) -> bool:
        """Spawn or reap caffeinate to match reality. Returns whether held."""
        if not self._is_busy():
            self._release("the sync finished")
            return self._held

        child = self._child
        if child is not None:
            returncode = self._poll_child(child)
            if returncode is None:
                return self._held  # still holding: nothing to do
            log.warning(
                "keep-awake: caffeinate exited on its own (rc=%s) while a lane was "
                "still busy -- starting another", returncode,
            )
            self._child = None
            self._held = False
        self._spawn()
        return self._held

    @staticmethod
    def _poll_child(child: Any) -> Optional[int]:
        """The child's exit code, or None while it is still running."""
        try:
            return child.poll()
        except Exception:
            # An unpollable child is one we cannot rely on, so treat it as
            # gone: a spurious respawn costs nothing, a phantom hold costs a
            # night's upload.
            log.debug("keep-awake: could not poll caffeinate", exc_info=True)
            return -1

    def _spawn(self) -> None:
        argv = caffeinate_command()
        fn = self._spawn_fn or _spawn_detached
        try:
            child = fn(argv)
        except Exception:
            if not self._spawn_failure_logged:
                self._spawn_failure_logged = True
                log.exception("keep-awake: could not start %s -- this Mac may sleep "
                              "mid-upload", " ".join(argv))
            self._child = None
            self._held = False
            return
        if child is None:
            if not self._spawn_failure_logged:
                self._spawn_failure_logged = True
                log.warning("keep-awake: caffeinate did not start -- this Mac may sleep "
                            "mid-upload")
            self._child = None
            self._held = False
            return
        self._spawn_failure_logged = False
        self._child = child
        self._held = True
        log.info("keep-awake: holding off the system idle timer while syncing")

    def _release(self, why: str = "stopping") -> None:
        """End the caffeinate child, if any. Idempotent, never raises."""
        child, self._child = self._child, None
        self._held = False
        if child is None:
            return
        try:
            if self._poll_child(child) is None:
                child.terminate()
        except Exception:
            log.debug("keep-awake: could not terminate caffeinate", exc_info=True)
        if not self._wait_for(child, self._stop_grace_seconds):
            # A caffeinate that ignores SIGTERM would hold the idle timer
            # until the login session ends, long after the sync finished.
            log.warning("keep-awake: caffeinate did not stop -- killing it")
            try:
                child.kill()
            except Exception:
                log.debug("keep-awake: could not kill caffeinate", exc_info=True)
            self._wait_for(child, self._stop_grace_seconds)
        log.info("keep-awake: released the system idle timer (%s)", why)

    @staticmethod
    def _wait_for(child: Any, timeout: float) -> bool:
        try:
            child.wait(timeout=timeout)
            return True
        except Exception:
            return False

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        # is_alive(), for the same reason as everywhere else in this module:
        # a dead Thread object left in _thread makes the guard permanently
        # un-restartable while `held` quietly reports False.
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._stop.clear()
        try:
            self._thread = threading.Thread(
                target=self._loop, name="ccsync-keep-awake", daemon=True
            )
            self._thread.start()
        except Exception:
            log.exception("keep-awake: could not start its thread")
            self._thread = None

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(2.0, self._poll_seconds / 4))
        # The loop releases in its own finally, and _release() is idempotent.
        # This second call is what covers the loop that never ran (or never
        # got there): unlike the Windows execution state, a child process can
        # be ended from any thread, and a caffeinate nobody ends keeps a Mac
        # awake until it reboots.
        self._release("stopped")

    def _loop(self) -> None:
        try:
            while True:
                self.apply_once()
                if self._stop.wait(self._poll_seconds):
                    break
        except Exception:
            log.exception("keep-awake: loop stopped")
        finally:
            self._release("stopping")


def make_keep_awake_guard(
    busy_fn: Callable[[], bool], enabled: bool = True
) -> KeepAwakeGuard:
    """The keep-awake guard for this platform. Always startable."""
    if not enabled:
        return KeepAwakeGuard()
    if sys.platform == "win32":
        return _WindowsKeepAwake(busy_fn)
    if sys.platform == "darwin":
        return _DarwinKeepAwake(busy_fn)
    return KeepAwakeGuard()
