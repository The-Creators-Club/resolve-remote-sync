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

The pure decision logic lives in describe_pending() so it can be tested on
any platform; only the two _Windows* classes touch ctypes.
"""

from __future__ import annotations

import logging
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
        self._holding_since: Optional[float] = None
        self._stale_logged: set = set()
        self._ceiling_logged = False

    def reset(self) -> None:
        """Forget every sample (used by tests and anything that restarts the
        lanes -- a fresh start deserves a fresh grace period)."""
        with self._lock:
            self._seen.clear()
            self._holding_since = None
            self._stale_logged = set()
            self._ceiling_logged = False

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
        if not alive:
            self._holding_since = None
            self._ceiling_logged = False
            return None
        if self._holding_since is None:
            self._holding_since = now
        elif (now - self._holding_since) >= self._max_hold_seconds:
            if not self._ceiling_logged:
                self._ceiling_logged = True
                log.warning(
                    "a lane has been busy for %.1f hours without settling -- standing "
                    "down: no more shutdown warnings or keep-awake until it does",
                    (now - self._holding_since) / 3600.0,
                )
            return None
        return _render_pending(alive)

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
        hwnd, self._hwnd = self._hwnd, None
        thread, self._thread = self._thread, None
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
            thread.join(timeout=3.0)

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


def make_shutdown_guard(
    reason_fn: Callable[[], Optional[str]], enabled: bool = True
) -> ShutdownGuard:
    """The guard for this platform. Always returns something startable."""
    if not enabled or sys.platform != "win32":
        return ShutdownGuard()
    return _WindowsShutdownGuard(reason_fn)


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


def make_keep_awake_guard(
    busy_fn: Callable[[], bool], enabled: bool = True
) -> KeepAwakeGuard:
    """The keep-awake guard for this platform. Always startable."""
    if not enabled or sys.platform != "win32":
        return KeepAwakeGuard()
    return _WindowsKeepAwake(busy_fn)
