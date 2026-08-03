"""Where a Tk root is allowed to be built: inline on Windows, on the main
thread on macOS.

The companion builds every dialog on whatever thread wanted it: the watcher
thread opens the fixer popup, a tray worker thread opens sign-in/update/
credentials, the root-guard thread opens the misplaced-drive dialog. On
Windows that works and has worked for a year, so THIS MODULE MUST NOT CHANGE
IT: on win32 (and anything that is not darwin) `dispatch(fn)` calls `fn()`
inline on the calling thread and returns what it returns. Same thread, same
stack, same exceptions, no queue, no extra thread -- byte-identical behaviour.

On macOS neither AppKit nor Tk-Aqua may be touched off the main thread, so
there `dispatch(fn)` marshals `fn` to the main thread and BLOCKS the caller
until it has run, handing back its return value or re-raising its exception.
The main thread is held by `MainThreadDispatcher.serve()`, which owns one
hidden `tk.Tk()` root and pumps the queue from a `root.after()` timer while
`root.mainloop()` runs. A dispatched `fn` is free to build its OWN `tk.Tk()`
root and run its own nested `mainloop()` -- that is what every dialog in this
package does, and it is legal precisely because it all now happens on one
thread.

WHAT IS AND IS NOT PROVEN (read this before trusting it on a Mac):
  - the marshaling and lifecycle logic below is covered by tests that drive
    the pump with a FAKE root object (tests/test_ui_dispatch.py) -- ordering,
    blocking, exception propagation, stop()-unblocks-waiters, reentrancy;
  - the darwin path itself CANNOT be proven on Windows. That
    `icon.run_detached()` (pystray's darwin backend) and a Tk-Aqua
    `mainloop()` on the same main thread actually coexist is the documented
    first-Mac-run spike. If they do not, the fallback is osascript dialogs --
    a separate piece of work, not something this module hides.

Serialization of dialogs is NOT this module's job: `app._popup_active_lock`
still decides that only one CCSync window is open at a time, and it is taken
by the CALLER, outside dispatch(). This is a transport, not a lock.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.ui")

# dispatch() runs fn on the calling thread (Windows/Linux -- today's behaviour).
MODE_INLINE = "inline"
# dispatch() marshals fn to the thread running serve() (macOS).
MODE_MAIN_THREAD = "main-thread"

# How often the main thread looks at the queue while its mainloop runs. Small
# enough that a dialog request never feels laggy, large enough not to spin.
DEFAULT_POLL_MS = 50


class UIDispatchStopped(RuntimeError):
    """dispatch() was called after the dispatcher stopped, or a queued call
    was cancelled by stop().

    Every call site treats a dialog that raises the same way it treats "no
    display": log it and take the safe default (confirm_dialog returns False,
    show_popup falls back to the console listing). That is deliberate -- a
    dialog request arriving during shutdown must fail fast, never block a
    thread forever waiting for a main thread that has left its mainloop.
    """


def platform_mode(platform: Optional[str] = None) -> str:
    """The mode this platform needs. The seam tests use to exercise the
    darwin path from Windows -- production calls it with no argument."""
    return MODE_MAIN_THREAD if (platform or sys.platform) == "darwin" else MODE_INLINE


class _Job:
    """One `fn` handed to the main thread, plus the caller's blocking wait."""

    __slots__ = ("fn", "_done", "_result", "_error")

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self._done = threading.Event()
        self._result: Any = None
        self._error: Optional[BaseException] = None

    def run(self) -> None:
        """On the pump thread. Never raises -- the exception belongs to the
        caller, and letting it out here would kill the pump for everyone."""
        try:
            self._result = self.fn()
        except BaseException as exc:  # noqa: BLE001 -- re-raised in wait()
            self._error = exc
        finally:
            self._done.set()

    def cancel(self, error: BaseException) -> bool:
        if self._done.is_set():
            return False
        self._error = error
        self._done.set()
        return True

    def wait(self) -> Any:
        self._done.wait()
        if self._error is not None:
            raise self._error
        return self._result


class MainThreadDispatcher:
    """Owns the main thread's hidden Tk root and the queue feeding it.

    Lifecycle (all on the SAME thread -- the main one on macOS):
        d.start()                # create + withdraw the hidden root
        d.serve(stop_event)      # blocks: pump + mainloop, returns on stop
    and from anywhere:
        d.dispatch(fn)           # blocks the caller, returns fn()'s result
        d.stop()                 # cancels waiters, asks serve() to return
    """

    def __init__(
        self,
        tk_factory: Optional[Callable[[], Any]] = None,
        poll_ms: int = DEFAULT_POLL_MS,
    ) -> None:
        # Injected in tests: a fake root with after/mainloop/quit/destroy, so
        # the pump is exercised without ever creating a real Tk window (see
        # conftest._no_real_tk_windows, which forbids exactly that).
        self._tk_factory = tk_factory
        self.poll_ms = int(poll_ms)
        self._lock = threading.Lock()
        self._queue: deque[_Job] = deque()
        self._root: Any = None
        self._owner_ident: Optional[int] = None
        self._serving = False
        self._stop_requested = False
        self._stopped = False
        self._stop_event: Optional[threading.Event] = None

    # -- lifecycle ------------------------------------------------------

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def root(self) -> Any:
        return self._root

    def start(self) -> Any:
        """Create the hidden root. Call from the thread that will serve()."""
        if self._root is not None:
            return self._root
        if self._stopped:
            # A stopped dispatcher is finished for good -- resurrecting it
            # would put a fresh Tk root up during shutdown.
            raise UIDispatchStopped(
                "the CCSync UI dispatcher has stopped -- not creating another root"
            )
        self._owner_ident = threading.get_ident()
        root = self._make_root()
        try:
            root.withdraw()
        except Exception:
            # A root that refuses to hide is still a usable pump; an empty
            # grey window on screen beats no dialogs at all.
            log.debug("UI dispatch: could not withdraw the hidden root", exc_info=True)
        self._root = root
        return root

    def _make_root(self) -> Any:
        factory = self._tk_factory
        if factory is None:
            import tkinter as tk

            factory = tk.Tk
        return factory()

    def serve(self, stop_event: Optional[threading.Event] = None) -> None:
        """Run the pump and the mainloop here until stop() (or `stop_event`).

        Returns only when the UI is finished, so on macOS this is the last
        thing app.run() does on the main thread.
        """
        try:
            root = self.start()
        except UIDispatchStopped:
            # stop() got here first (a shutdown racing startup). Nothing to
            # serve, and app.run() carries straight on to shutdown().
            log.warning("UI dispatch: serve() after stop() -- not starting a mainloop")
            return
        self._owner_ident = threading.get_ident()
        self._stop_event = stop_event
        with self._lock:
            if self._stopped:
                # stop() landed between the check above and here -- it has
                # already destroyed the root, so there is nothing to loop on.
                log.warning("UI dispatch: stopped while starting the mainloop")
                return
            self._serving = True
        log.info("UI dispatch: main thread is serving dialogs (poll %d ms)", self.poll_ms)
        try:
            root.after(self.poll_ms, self._pump)
            root.mainloop()
        finally:
            with self._lock:
                self._serving = False
            # The mainloop is gone, so nobody can run a queued fn any more:
            # whatever is waiting has to be told, not left hanging.
            self._finish()

    def stop(self) -> None:
        """Cancel every waiter and ask serve() to return. Any thread."""
        with self._lock:
            self._stop_requested = True
            self._stopped = True
            pending = list(self._queue)
            self._queue.clear()
            serving = self._serving
        self._cancel(pending)
        if not serving:
            # Nobody is going to run serve()'s finally for us.
            self._destroy_root()

    def _finish(self) -> None:
        with self._lock:
            self._stopped = True
            pending = list(self._queue)
            self._queue.clear()
        self._cancel(pending)
        self._destroy_root()

    def _cancel(self, pending: list[_Job]) -> None:
        if not pending:
            return
        cancelled = 0
        for job in pending:
            if job.cancel(UIDispatchStopped(
                "the CCSync UI dispatcher stopped before this window could open"
            )):
                cancelled += 1
        if cancelled:
            log.warning(
                "UI dispatch: stopped with %d window request(s) waiting -- they were "
                "cancelled, and their callers take the same safe default as a machine "
                "with no display", cancelled,
            )

    def _destroy_root(self) -> None:
        root, self._root = self._root, None
        if root is None:
            return
        try:
            root.destroy()
        except Exception:
            log.debug("UI dispatch: hidden root destroy() failed", exc_info=True)

    # -- the pump (runs on the serving thread) --------------------------

    def _should_quit(self) -> bool:
        if self._stop_requested or self._stopped:
            return True
        event = self._stop_event
        return event is not None and event.is_set()

    def _pump(self) -> None:
        """One timer tick: run everything queued, then re-arm (or quit)."""
        while True:
            with self._lock:
                if not self._queue:
                    break
                job = self._queue.popleft()
            # run() swallows the fn's exception into the job, so one bad
            # dialog can never take the pump -- i.e. every other dialog for
            # the rest of the session -- down with it.
            job.run()
        if self._should_quit():
            try:
                self._root.quit()
            except Exception:
                log.debug("UI dispatch: quit() failed", exc_info=True)
            return
        try:
            self._root.after(self.poll_ms, self._pump)
        except Exception:
            # No re-arm means no more dialogs; say so loudly rather than
            # letting callers block on a pump that has silently stopped.
            log.exception("UI dispatch: could not re-arm the pump -- stopping it")
            self.stop()

    # -- callers --------------------------------------------------------

    def dispatch(self, fn: Callable[[], Any]) -> Any:
        """Run fn on the serving thread; block until it has, then return its
        result (or re-raise its exception)."""
        if self._stopped:
            # Checked BEFORE the owner-thread shortcut below: once the
            # mainloop is gone, "run it inline on the main thread" would put
            # a fresh modal Tk root in the middle of shutdown.
            raise UIDispatchStopped(
                "the CCSync UI dispatcher has stopped -- no new windows can open"
            )
        if threading.get_ident() == self._owner_ident:
            # Already on the thread that owns the UI -- either reentrant (fn
            # called dispatch again) or a dialog wanted before serve() got
            # going. Queueing here would wait for a pump that is us.
            return fn()
        job = _Job(fn)
        with self._lock:
            if self._stopped:
                raise UIDispatchStopped(
                    "the CCSync UI dispatcher has stopped -- no new windows can open"
                )
            self._queue.append(job)
        return job.wait()


# -- module-level façade ----------------------------------------------------
#
# Everything in the package calls ui_dispatch.dispatch(fn) and does not care
# which platform it is on. On win32 no dispatcher is ever started, so
# dispatch() is a plain call.

_active_lock = threading.Lock()
_active: Optional[MainThreadDispatcher] = None


def start(
    mode: Optional[str] = None,
    tk_factory: Optional[Callable[[], Any]] = None,
    poll_ms: int = DEFAULT_POLL_MS,
) -> Optional[MainThreadDispatcher]:
    """Start main-thread UI dispatch if this platform needs it.

    Returns the dispatcher on darwin, None everywhere else (where dispatch()
    is already inline and there is nothing to start). Call from the main
    thread: the returned dispatcher's serve() must run on this same thread.
    """
    global _active

    resolved = mode or platform_mode()
    if resolved != MODE_MAIN_THREAD:
        log.debug("UI dispatch: inline mode (%s) -- dialogs build on their own threads",
                  resolved)
        return None
    with _active_lock:
        if _active is not None and not _active.stopped:
            return _active
        dispatcher = MainThreadDispatcher(tk_factory=tk_factory, poll_ms=poll_ms)
        dispatcher.start()
        _active = dispatcher
    return dispatcher


def active() -> Optional[MainThreadDispatcher]:
    return _active


def uses_main_thread() -> bool:
    """True when a live main-thread dispatcher owns the UI (darwin)."""
    dispatcher = _active
    return dispatcher is not None and not dispatcher.stopped


def dispatch(fn: Callable[[], Any]) -> Any:
    """Build-and-show a window: inline on Windows, on the main thread on
    macOS. Blocks either way, returns fn()'s value, re-raises its exception."""
    dispatcher = _active
    if dispatcher is None:
        return fn()
    return dispatcher.dispatch(fn)


def stop() -> None:
    """Stop main-thread dispatch. No-op when there is none (win32).

    The stopped dispatcher stays registered on purpose: a dialog requested
    after this point must fail fast with UIDispatchStopped, NOT quietly fall
    back to building a Tk root on some daemon thread while macOS is tearing
    the process down.
    """
    dispatcher = _active
    if dispatcher is None:
        return
    dispatcher.stop()
