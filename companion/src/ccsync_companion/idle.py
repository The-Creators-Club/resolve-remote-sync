"""How long has the user been away from the keyboard?

The proxy generator encodes only while nobody is here, and stops the instant
they come back: ffmpeg at BelowNormal is still a machine-wide tax, and an
editor who scrubs a timeline into a stutter because the companion decided to
transcode under their hands would (rightly) switch the feature off forever.

The contract that makes that safe is `None`:

    seconds_idle() -> Optional[float]
    None means CANNOT TELL, and cannot-tell means NOT IDLE.

Every caller must treat None as "the user is here" and stand down. That is
why an unsupported platform, a missing DLL, a timed-out helper and a garbled
answer all collapse to the same value -- there is no failure mode of this
module that can result in an encode starting while somebody is working.

KNOWN LIMITS, all deliberate:

  * PER SESSION. Windows' GetLastInputInfo reports input for the session the
    calling process runs in. The companion runs in the interactive session,
    which is the right one -- but a second logged-in user typing in their own
    session is invisible to us, and so is anything happening while our
    session is disconnected.
  * RDP. A remote session and the console session keep separate input
    timers. Reconnecting over RDP does not reset the console's, so a machine
    can look idle to a probe running in the other session.
  * IT CANNOT SEE AN UNATTENDED RENDER. Idle means "no keyboard or mouse
    input", not "no work". A DaVinci Resolve render left running overnight is
    idle by this measure, and the generator would contend with it for the
    GPU. That is what the opt-in `proxy_gen_skip_while_resolve_running`
    config key exists for; no input-based probe can answer it.

Factory-by-platform with an inert base, the shape make_shutdown_guard
(:1140) uses, and the same injectable-seam discipline as root_guard.py:
everything that touches ctypes or a subprocess arrives as a parameter, so
the Windows and macOS behaviour is testable from any host.

Added 2026-08-10 with the companion proxy generator.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from typing import Any, Callable, Optional

# "ccsync.idle", NOT __name__ -- setup_logging() only attaches handlers to
# the "ccsync" logger, and in the windowed build sys.stderr is None, so a
# record emitted under "ccsync_companion.idle" is swallowed outright.
log = logging.getLogger("ccsync.idle")

# GetTickCount's counter is 32 bits of milliseconds and wraps every 49.7 days.
_TICK_MODULO = 2 ** 32

# `ioreg -c IOHIDSystem -d 1 -w 0`: -d 1 keeps the output to the one plane
# level that carries the properties, -w 0 stops it wrapping lines (a wrapped
# HIDIdleTime would split the digits and the regex would read a truncated
# number, i.e. a machine that looks LESS idle than it is -- the safe way to
# be wrong, but wrong).
#
# Absolute path for the same reason root_guard.DISKUTIL_PATH is absolute: a
# LaunchAgent gets a minimal environment, and a PATH lookup is not something
# to depend on for a binary that has lived here since forever.
IOREG_PATH = "/usr/sbin/ioreg"
IOREG_ARGV = [IOREG_PATH, "-c", "IOHIDSystem", "-d", "1", "-w", "0"]
IOREG_TIMEOUT_SECONDS = 10.0

# HIDIdleTime is NANOSECONDS since the last HID event.
_HID_IDLE_RE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')
_NANOSECONDS = 1_000_000_000.0


class IdleProbe:
    """Inert base: every platform without a probe, and any platform when the
    caller switched idle detection off.

    Answers None forever, which by this module's contract means "cannot tell"
    -- so a companion on an unsupported platform never generates proxies
    rather than generating them at the worst possible moment.
    """

    def seconds_idle(self) -> Optional[float]:
        return None


# --- Windows ---------------------------------------------------------------

def _elapsed_ms(now32: Any, last32: Any) -> int:
    """Milliseconds between two 32-bit tick counts, wrap included. Pure.

    GetLastInputInfo hands back `dwTime`, a DWORD sampled from the SAME
    32-bit counter GetTickCount reads -- so the subtraction has to be done in
    32-bit arithmetic. Every 49.7 days that counter rolls over, and on the
    days either side of a rollover a plain `now - last` is a negative number
    or a ~49-day idle time depending on which one wrapped first. The first
    would read as "not idle" (harmless); the second as "idle for seven weeks"
    on a machine somebody is typing on, which is the encode-under-their-hands
    failure this whole module exists to prevent. The modulo is what makes it
    right on both sides.

    Deliberately NOT GetTickCount64: mixing a 64-bit now with a 32-bit last
    reintroduces exactly the same bug in a form that only appears after the
    machine has been up 49.7 days.
    """
    return (int(now32) - int(last32)) % _TICK_MODULO


class _WindowsIdleProbe(IdleProbe):
    """GetLastInputInfo vs GetTickCount, both via ctypes.

    The ctypes binding is built lazily on the first call and cached, so
    constructing a probe touches nothing -- a factory call must be free of
    side effects, and the tests build one on macOS.
    """

    def __init__(
        self,
        tick_fn: Optional[Callable[[], Any]] = None,
        last_input_fn: Optional[Callable[[], Any]] = None,
    ) -> None:
        # Injectable seams (root_guard.py's run_fn style): tick_fn is
        # GetTickCount, last_input_fn is the dwTime out of GetLastInputInfo
        # or None when the call itself failed.
        self._tick_fn = tick_fn
        self._last_input_fn = last_input_fn
        self._bind_failed = False

    def _bind(self) -> bool:
        """Wire up the two Win32 calls. False on any failure, once."""
        if self._tick_fn is not None and self._last_input_fn is not None:
            return True
        if self._bind_failed:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("dwTime", wintypes.DWORD),
                ]

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # Explicit restypes, like shutdown_guard's bindings: ctypes
            # defaults to c_int, which would sign-extend a DWORD past
            # 0x7FFFFFFF into a negative number -- the wrap bug again, 24.9
            # days in.
            kernel32.GetTickCount.restype = wintypes.DWORD
            kernel32.GetTickCount.argtypes = []
            user32.GetLastInputInfo.restype = wintypes.BOOL
            user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]

            def _last_input() -> Optional[int]:
                info = LASTINPUTINFO()
                info.cbSize = ctypes.sizeof(LASTINPUTINFO)
                if not user32.GetLastInputInfo(ctypes.byref(info)):
                    return None
                return int(info.dwTime)

            if self._tick_fn is None:
                self._tick_fn = kernel32.GetTickCount
            if self._last_input_fn is None:
                self._last_input_fn = _last_input
            return True
        except Exception:
            # Not fatal to anything: no idle answer means no generation.
            log.debug("idle: ctypes unavailable -- no idle detection", exc_info=True)
            self._bind_failed = True
            return False

    def seconds_idle(self) -> Optional[float]:
        try:
            if not self._bind():
                return None
            last = self._last_input_fn()
            if last is None:
                return None
            now = self._tick_fn()
            if now is None:
                return None
            return _elapsed_ms(now, last) / 1000.0
        except Exception:
            log.debug("idle: GetLastInputInfo failed", exc_info=True)
            return None


# --- macOS -----------------------------------------------------------------

def parse_hid_idle_seconds(text: Any) -> Optional[float]:
    """Seconds out of an `ioreg -c IOHIDSystem` dump, or None.

    None for a missing key, a garbled dump and an unparseable number alike --
    all of them mean "no idle answer", and this is the only place the
    difference could be invented.
    """
    try:
        if not text:
            return None
        match = _HID_IDLE_RE.search(text if isinstance(text, str) else str(text))
        if not match:
            return None
        return int(match.group(1)) / _NANOSECONDS
    except Exception:
        log.debug("idle: could not read HIDIdleTime", exc_info=True)
        return None


def default_ioreg_run(
    argv: list, timeout: float = IOREG_TIMEOUT_SECONDS
) -> Optional[str]:
    """Run ioreg, return stdout as text, or None on ANY failure.

    Same single-failure-signal shape as root_guard.default_run: a missing
    binary, a non-zero exit and a timeout all mean "no idle answer", and none
    of them may raise into a caller's loop.

    utf-8 with errors="replace": a device name with an odd byte in it must
    not turn into a UnicodeDecodeError, and the digits we want are ASCII.
    """
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            argv,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        log.debug("idle: %s failed", " ".join(str(a) for a in argv), exc_info=True)
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or b"").decode("utf-8", "replace")


class _DarwinIdleProbe(IdleProbe):
    """HIDIdleTime out of ioreg -- the base system's own idle counter.

    ioreg rather than Quartz's CGEventSourceSecondsSinceLastEventType, which
    would be one call and no subprocess: Quartz comes from pyobjc, and the
    frozen macOS build does not carry it (nothing else in the companion needs
    it, and adding a framework bridge to the bundle for one number is not a
    trade worth making). ioreg is in the base OS on every Mac.
    """

    def __init__(self, run_fn: Optional[Callable[..., Any]] = None) -> None:
        self._run_fn = run_fn if run_fn is not None else default_ioreg_run

    def seconds_idle(self) -> Optional[float]:
        try:
            return parse_hid_idle_seconds(
                self._run_fn(list(IOREG_ARGV), IOREG_TIMEOUT_SECONDS)
            )
        except Exception:
            log.debug("idle: ioreg probe failed", exc_info=True)
            return None


def make_idle_probe(enabled: bool = True) -> IdleProbe:
    """The idle probe for this platform. Always returns something callable.

    `enabled=False` returns the inert base rather than None, so callers never
    need a null check -- and, because inert means "cannot tell" means "not
    idle", switching idle detection off switches idle-gated work off with it.
    """
    if not enabled:
        return IdleProbe()
    if sys.platform == "win32":
        return _WindowsIdleProbe()
    if sys.platform == "darwin":
        return _DarwinIdleProbe()
    return IdleProbe()
