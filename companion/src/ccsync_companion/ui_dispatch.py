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
`root.mainloop()` runs. A dispatched `fn` builds its OWN `tk.Tk()` root, which
is legal precisely because it all now happens on one thread -- but it must end
that root with `run_dialog(root)`, NOT with a nested `root.mainloop()`.

WHY NOT A NESTED mainloop(): Tk's loop runs `while Tk_GetNumMainWindows() > 0`,
and that count is per THREAD, not per interpreter. The hidden root above is a
main window on this thread and never closes, so a dialog's nested mainloop()
does not return when the dialog is destroyed -- it spins forever. The caller
stays blocked, `app._popup_active_lock` is never released, and every later
dialog dies on "Another CCSync window is already open" (MAC-6: the sign-in
window opened once, then the tray refused to open it again for the rest of the
session). `run_dialog()` uses `tkwait window` there instead, which returns on
destroy and leaves the outer mainloop untouched. Note that `root.quit()` is NOT
the fix: _tkinter's quit flag is process-global, so it would break the
dispatcher's own mainloop out of serve() and start a shutdown.

WHAT IS AND IS NOT PROVEN (read this before trusting it on a Mac):
  - the marshaling and lifecycle logic below is covered by tests that drive
    the pump with a FAKE root object (tests/test_ui_dispatch.py) -- ordering,
    blocking, exception propagation, stop()-unblocks-waiters, reentrancy;
  - the darwin path itself CANNOT be proven on Windows. That
    `icon.run_detached()` (pystray's darwin backend) and a Tk-Aqua
    `mainloop()` on the same main thread actually coexist is the documented
    first-Mac-run spike. If they do not, the fallback is osascript dialogs --
    a separate piece of work, not something this module hides.

SHUTDOWN CAN BREAK A NESTED tkwait (MAC-11's follow-up). `tkwait window` is
only as good as the window's own promise to destroy itself. A dialog that
never does parks the pump INSIDE the tkwait: the pump timer never re-arms,
every later dialog request queues forever, `serve()`'s mainloop cannot
return, and SIGTERM cannot finish a shutdown -- the live 2026-08-05 incident
took `kill -9`. So `run_dialog()` records the window it is about to park in
and `stop()` destroys it, which is what ends the tkwait. The destroy is
scheduled through the HIDDEN root's `after()` on purpose: Tcl's timer queue
is per THREAD, not per interpreter, and `tkwait` spins in Tk_DoOneEvent,
which services that queue -- so a timer armed on the hidden root fires even
though the pump's own timer chain is parked. (It cannot be run on the calling
thread: only the UI thread may touch Tk-Aqua.)

Serialization of dialogs is NOT this module's job: `app._popup_active_lock`
still decides that only one CCSync window is open at a time, and it is taken
by the CALLER, outside dispatch(). This is a transport, not a lock.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import threading
import time
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

# How long stop() waits for the UI thread to ACCEPT the request to destroy a
# stuck dialog. A cross-thread Tk call is marshaled to the interpreter's own
# thread and blocks the caller until that thread services it -- which a
# parked `tkwait` does, promptly. This bound only matters when the main
# thread is somewhere Tk cannot reach at all, and there shutdown must carry
# on regardless (app.py's hard-exit backstop is what covers that case).
DIALOG_BREAK_TIMEOUT_SECONDS = 5.0


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


def window_label(window: Any) -> str:
    """Something an admin can recognise in the log for a stuck window.

    Its title if it has one (every dialog in this package sets one), its
    class otherwise. Never raises -- this is only ever called to build a
    message about something that has already gone wrong.
    """
    try:
        title = window.title()
        if title:
            return f"{str(title)[:80]!r}"
    except Exception:
        pass
    return type(window).__name__


def _destroy_quietly(window: Any, label: str) -> None:
    try:
        window.destroy()
    except Exception:
        # Already gone, or a Tcl interpreter torn down under us. Either way
        # the tkwait it was holding is over, which is all we wanted.
        log.debug("UI dispatch: destroy of %s failed", label, exc_info=True)


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
            # The dialog's frame is gone: whatever it left in a closure cycle
            # is garbage this thread (the one that built the root) can
            # collect and free right now (CR-93).
            reclaim_mine("dialog finished")
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
        # The dialog root(s) run_dialog() is currently parked in, innermost
        # last (a dialog may open another one -- reentrant dispatch runs it
        # inline on this same thread). Only ever non-empty on darwin.
        self._dialogs: list[Any] = []

    # -- lifecycle ------------------------------------------------------

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def serving(self) -> bool:
        """True while the mainloop is running on the serving thread. False
        the moment it returns -- app.py's shutdown backstop asks this to tell
        "the UI thread is wedged" from "the UI thread has already gone"."""
        return self._serving

    @property
    def open_dialogs(self) -> list[Any]:
        """The dialog windows currently being waited on, outermost first."""
        with self._lock:
            return list(self._dialogs)

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
        # BEFORE _destroy_root(): the hidden root is how the destroy reaches
        # the UI thread, and a dialog left open on a thread whose pump is
        # parked inside it is the whole reason this method can be reached
        # while a window is still up.
        self._break_open_dialogs()
        if not serving:
            # Nobody is going to run serve()'s finally for us.
            self._destroy_root()

    def _finish(self) -> None:
        with self._lock:
            self._stopped = True
            pending = list(self._queue)
            self._queue.clear()
        self._cancel(pending)
        self._break_open_dialogs()
        self._destroy_root()
        # serve()'s thread built the hidden root; it is the one that may free it.
        reclaim_mine("dispatcher finished")

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

    # -- breaking a nested tkwait (MAC-11's follow-up) -------------------

    def note_dialog(self, window: Any) -> bool:
        """Register the window run_dialog() is about to park in.

        False means the dispatcher has already stopped, i.e. stop() has been
        past the point where it would have broken this window out. The caller
        must NOT enter `tkwait` then -- it would be a wedge with nobody left
        to end it.
        """
        with self._lock:
            if self._stopped:
                return False
            self._dialogs.append(window)
            return True

    def forget_dialog(self, window: Any) -> None:
        """The window closed on its own (the normal path). Innermost match
        first, so nested dialogs unwind in the order they were opened."""
        with self._lock:
            for index in range(len(self._dialogs) - 1, -1, -1):
                if self._dialogs[index] is window:
                    del self._dialogs[index]
                    return

    def _break_open_dialogs(self) -> None:
        """Destroy whatever run_dialog() is still parked in, so the UI thread
        can leave its `tkwait` and serve()'s mainloop can return.

        This is the difference between a SIGTERM that finishes and one that
        needs `kill -9`: on 2026-08-05 a fix-all popup that never destroyed
        itself left the pump inside `tkwait window`, so the shutdown ran to
        completion, logged, and then sat there with the window on screen
        (MAC-11). Innermost dialog first -- the outer one's tkwait cannot
        return until the inner one has.
        """
        with self._lock:
            dialogs = list(self._dialogs)
            self._dialogs.clear()
            root = self._root
        for window in reversed(dialogs):
            label = window_label(window)
            log.error(
                "UI dispatch: shutting down with the window %s still open -- closing "
                "it from here. A dialog that never destroys itself parks the main "
                "thread inside `tkwait` for good, and the process then needs killing "
                "(MAC-11).", label,
            )
            self._schedule_destroy(root, window, label)

    def _schedule_destroy(self, root: Any, window: Any, label: str) -> None:
        if root is None or threading.get_ident() == self._owner_ident:
            # Either there is no hidden root left to schedule on, or WE are
            # the UI thread -- in which case nothing is parked in a tkwait
            # below us and destroying it right here is the whole job.
            self._destroy_window(window, label)
            return
        # A Tk call from another thread is marshaled to the interpreter's own
        # thread and BLOCKS until that thread services it. A parked `tkwait`
        # does exactly that (Tcl's timer queue is per thread, and tkwait
        # spins in Tk_DoOneEvent) -- but a main thread that is in no event
        # loop at all would never answer, and shutdown cannot hang there.
        def _ask() -> None:
            try:
                root.after(0, lambda: self._destroy_window(window, label))
            except Exception:
                log.debug("UI dispatch: could not schedule the destroy of %s", label,
                          exc_info=True)

        thread = threading.Thread(target=_ask, name="ccsync-ui-break", daemon=True)
        thread.start()
        thread.join(timeout=DIALOG_BREAK_TIMEOUT_SECONDS)
        if thread.is_alive():
            log.error(
                "UI dispatch: the main thread would not even accept a request to "
                "close %s within %.0fs -- it is not running an event loop we can "
                "reach, so this process cannot end itself tidily.",
                label, DIALOG_BREAK_TIMEOUT_SECONDS,
            )

    def _destroy_window(self, window: Any, label: str) -> None:
        _destroy_quietly(window, label)

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
            try:
                return fn()
            finally:
                reclaim_mine("dialog finished")
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
        try:
            return fn()
        finally:
            # fn's frame has returned. Its root, its widgets and the closures
            # that reference them are garbage now -- garbage that only the
            # cyclic collector frees, on whatever thread next trips it, unless
            # THIS thread (the one that built the interpreter) collects it
            # here and frees the interpreter itself (CR-93).
            reclaim_mine("dialog finished")
    return dispatcher.dispatch(fn)


def run_dialog(root: Any) -> None:
    """Run `root`'s event loop until the window is destroyed, then return.

    The last line of every dialog in this package. On Windows/Linux it is
    `root.mainloop()` -- byte-identical to what shipped for a year, because
    there is no other main window on the thread to keep the loop alive. On
    macOS the dispatcher's hidden root IS such a window, so mainloop() would
    never return (see the module docstring); `tkwait window` is used instead.

    The window is registered with the dispatcher for as long as we are parked
    in it, so shutdown can destroy it if it never destroys itself (MAC-11).
    """
    if not uses_main_thread():
        root.mainloop()
        return
    try:
        if not root.winfo_exists():
            # Destroyed before we got here -- the dialog is already finished,
            # and `tkwait window` on a dead window would raise.
            return
    except Exception:
        return
    dispatcher = _active
    if dispatcher is None:
        root.mainloop()
        return
    if not dispatcher.note_dialog(root):
        # stop() landed between uses_main_thread() above and here: it has
        # already swept the open windows, so parking in `tkwait` now would
        # be a wedge with nobody left to break it. Close instead -- a dialog
        # requested into a shutdown takes its caller's safe default, exactly
        # as UIDispatchStopped does.
        label = window_label(root)
        log.warning("UI dispatch: %s opened as the dispatcher stopped -- closing it "
                    "rather than waiting on it", label)
        _destroy_quietly(root, label)
        return
    try:
        root.wait_window(root)
    finally:
        dispatcher.forget_dialog(root)


# -- a Tcl interpreter dies ONLY on the thread that built it (CR-93) --------
#
# THE FAILURE THIS PREVENTS. A `tk.Tk()` root owns a Tcl interpreter (the
# `_tkinter.tkapp` in `root.tk`, shared by every widget, StringVar and
# PhotoImage made from it), and _tkinter frees that interpreter in
# Tkapp_Dealloc -- inline, on whatever thread drops the LAST Python reference,
# with none of the marshaling an ordinary Tk call gets. Tcl checks: an
# interpreter deleted from a thread other than the one that created it is
#
#     Tcl_AsyncDelete: async handler deleted by the wrong thread
#
# a Tcl_Panic, i.e. abort(). The process is GONE -- no Python traceback, no
# `finally`, no log line. On Windows it surfaces only in the Event Log as
# exception 0x80000003 in tcl86t.dll, and to the editor as "the tray keeps
# closing itself" (CR-93: seven of these between 2026-08-18 and 2026-08-29 on
# the base rig, then two more on the build that carried the first fix).
#
# WHO DROPS THE LAST REFERENCE IS NOT UP TO US. The first fix (0.9.55) counted
# references at the end of a dialog and parked the root when something still
# held it. That closes the holder-in-an-attribute shape and misses the one
# that actually recurred (2026-08-30, twice, dump + faulthandler in hand): a
# dialog whose nested functions reference each other -- the Settings window's
# `_refresh` schedules ITSELF with root.after(), and reaches `root` through
# `_render` -> `_run` -> `_release_and_close` -- is a REFERENCE CYCLE. Its
# frame ending frees nothing; the cyclic garbage collector frees it, later,
# on whichever thread's allocations happen to trip the collector. Both
# recurrences died on the watcher thread inside `Garbage-collecting` during a
# project-library read (a hundred thousand fresh objects is what makes the
# collector run a full pass), minutes to hours after the window had closed.
# No refcount taken inside the dialog can see that, because inside the dialog
# the frame is still alive and every count is legitimately high.
#
# THE RULE, then, and it is the only one that holds: an interpreter is PINNED
# the moment it is born (an extra reference, `Py_IncRef` through ctypes, that
# no Python object owns and finalisation cannot clear), and it is freed in
# exactly one place -- `_try_free()`, on the thread that created it, once a
# full collection ON THAT THREAD has left nothing else holding it. Any other
# path to Tkapp_Dealloc no longer exists: whoever drops the last visible
# reference, on whatever thread, only ever lowers the count to the pin.
#
# The pin is installed by wrapping `tkinter.Tk.__init__` (install_tk_guard,
# done at import), so EVERY root in this process is covered -- the fifteen
# dialogs in this package, a hidden clipboard root, a file picker's root, a
# root some future site forgets to think about. Reclamation happens at the
# end of every `dispatch(fn)` (the frame that built the dialog has returned,
# so its closures are garbage this thread can collect right now) and in
# `release_root()` for the windows that own their roots explicitly. A root
# that is still held after that is left pinned -- a measured 1.8 MB, not an
# aborted process -- and the log NAMES what holds it, which is what every
# previous occurrence cost a dump-parsing session to learn. A root whose
# thread has exited can never be freed at all (the tray's per-click worker
# threads are the usual case) and is reported once as a leak.
#
# `CCSYNC_TK_AUDIT=1` logs the whole registry -- every interpreter, its
# origin, its thread, what holds it, with referrer chains -- after each
# reclamation pass, so the next holder is named on the machine it happens on.

import weakref

_TK_AUDIT_ENV = "CCSYNC_TK_AUDIT"
# A pinned interpreter whose window is gone is a leak by design; say so once
# it stops being a rounding error (1.8 MB each, measured 2026-08-30).
PINNED_WARN_AT = 8
# How many referrer hops the holder description follows. Three is enough to
# get from a tkapp to the dialog function that closed over its root.
HOLDER_CHAIN_HOPS = 3
HOLDER_CHAIN_WIDTH = 4


class _TkRecord:
    """One Tcl interpreter this process has created, and who may free it."""

    __slots__ = ("tkapp", "root_ref", "thread", "ident", "label", "origin",
                 "created", "pinned", "warned_held", "warned_orphan")

    def __init__(self, tkapp: Any, root: Any, label: Optional[str], origin: str) -> None:
        self.tkapp = tkapp
        try:
            self.root_ref = weakref.ref(root)
        except TypeError:
            # A test double without __weakref__: hold it strongly. Only the
            # suite gets here, and only with fakes that own no interpreter.
            self.root_ref = lambda r=root: r  # type: ignore[assignment]
        self.thread = threading.current_thread()
        self.ident = threading.get_ident()
        self.label = label
        self.origin = origin
        self.created = time.monotonic()
        self.pinned = False
        self.warned_held = False
        self.warned_orphan = False

    def describe(self) -> str:
        name = self.label or "a Tk root"
        return f"{name} (built by thread {self.thread.name!r} at {self.origin})"


class _ReleasedInterp:
    """What `root.tk` becomes once the interpreter has been freed.

    A root can outlive its interpreter -- that is the whole point (it may sit
    in a closure cycle for hours) -- and tkinter reaches `root.tk` for every
    call. Answering with TclError, the exception every call site already
    catches for a destroyed window, beats a dangling tkapp.
    """

    __slots__ = ("_label",)

    def __init__(self, label: str) -> None:
        self._label = label

    def __getattr__(self, name: str) -> Any:
        import tkinter  # noqa: PLC0415 - only on the error path

        raise tkinter.TclError(
            f"{self._label}: its Tcl interpreter was freed on the thread that "
            "built it (CR-93); the window is gone")


_registry_lock = threading.Lock()
# id(tkapp) -> record. The record's strong reference plus the Py_IncRef pin
# is what keeps Tkapp_Dealloc from running anywhere we did not choose.
_registry: dict[int, _TkRecord] = {}
_guard_installed = False


def _immortalise(obj: Any) -> bool:
    """Add a reference nothing can take back but us. Returns whether it stuck.

    A pinned interpreter must survive INTERPRETER SHUTDOWN as well as its
    holders: finalisation clears module globals from the main thread, so a
    registry that is only a dict hands the last reference to the main thread
    and aborts on the way out (measured 2026-08-29 -- exit code 3, same
    Tcl_AsyncDelete, just at a moment nobody was watching). An extra refcount
    is invisible to finalisation, and _mortalise() gives it back at the one
    moment the owning thread is ready to do the free itself.
    """
    try:
        import ctypes  # noqa: PLC0415 - only needed on this path

        ctypes.pythonapi.Py_IncRef(ctypes.py_object(obj))
        return True
    except Exception:  # noqa: BLE001 - no ctypes: the record's own reference holds
        log.debug("UI dispatch: could not pin a Tk interpreter", exc_info=True)
        return False


def _mortalise(obj: Any) -> None:
    try:
        import ctypes  # noqa: PLC0415

        ctypes.pythonapi.Py_DecRef(ctypes.py_object(obj))
    except Exception:  # noqa: BLE001
        log.debug("UI dispatch: could not unpin a Tk interpreter", exc_info=True)


def _origin() -> str:
    """The first frame outside tkinter and this module: the dialog that built
    the root, as a label for the log."""
    try:
        frame = sys._getframe(1)
        while frame is not None:
            filename = frame.f_code.co_filename.replace("\\", "/")
            basename = filename.rsplit("/", 1)[-1]
            if "/tkinter/" not in filename and basename != "ui_dispatch.py":
                return f"{frame.f_code.co_name} ({basename}:{frame.f_lineno})"
            frame = frame.f_back
    except Exception:  # noqa: BLE001 - a label, never a failure
        pass
    return "<unknown>"


def adopt(root: Any, label: Optional[str] = None) -> Optional[_TkRecord]:
    """Register (and pin) the interpreter behind `root`. Idempotent; a root
    with no `.tk` owns nothing and gets no record. Normally done for every
    root by the guard below the moment tkinter builds it -- the explicit call
    is for a root built before the guard, and for the suite's fakes."""
    try:
        tkapp = root.__dict__.get("tk")
    except Exception:  # noqa: BLE001 - no __dict__: nothing to own
        return None
    if tkapp is None:
        return None
    key = id(tkapp)
    with _registry_lock:
        record = _registry.get(key)
        if record is not None:
            if label and not record.label:
                record.label = label
            return record
        record = _TkRecord(tkapp, root, label, _origin())
        record.pinned = _immortalise(tkapp)
        _registry[key] = record
    return record


def install_tk_guard() -> bool:
    """Wrap tkinter.Tk.__init__ so every interpreter is pinned at birth.

    Idempotent. The wrapper adopts in a `finally`: a root whose __init__
    raised half-way (Tcl wedged by a sibling thread's root, seen live
    2026-07-25) already owns an interpreter, and that one must not be the
    exception traceback's to free.
    """
    global _guard_installed
    if _guard_installed:
        return True
    try:
        import tkinter
    except Exception:  # noqa: BLE001 - no tkinter: nothing to guard
        return False
    original = tkinter.Tk.__init__

    def __init__(self, *args, **kwargs):  # noqa: N807 - it IS __init__
        try:
            original(self, *args, **kwargs)
        finally:
            adopt(self)

    __init__.__wrapped__ = original  # type: ignore[attr-defined]
    __init__.__doc__ = original.__doc__
    tkinter.Tk.__init__ = __init__  # type: ignore[method-assign]
    _guard_installed = True
    return True


def _baseline(record: _TkRecord) -> int:
    """What sys.getrefcount(record.tkapp) reads when nothing but us holds it:
    the record's attribute, getrefcount's argument, the pin, and the root's
    own `tk` while the root is alive and still has one."""
    count = 2 + (1 if record.pinned else 0)
    root = record.root_ref()
    if root is not None:
        try:
            if root.__dict__.get("tk") is record.tkapp:
                count += 1
        except Exception:  # noqa: BLE001
            pass
    return count


def _root_in_use(record: _TkRecord) -> bool:
    """True while the window still exists -- a hidden clipboard root between
    `withdraw()` and its release reads at the baseline (no widgets), and a
    reclamation pass on a nested dialog must not free it under its frame."""
    root = record.root_ref()
    if root is None:
        return False
    exists = getattr(root, "winfo_exists", None)
    if exists is None:
        return False
    try:
        return bool(exists())
    except Exception:  # noqa: BLE001 - "application has been destroyed"
        return False


def _try_free(record: _TkRecord) -> bool:
    """Free the interpreter HERE if this thread built it and nothing else
    holds it. The only path in this process to Tkapp_Dealloc."""
    if record.thread is not threading.current_thread():
        return False
    if _root_in_use(record):
        return False
    tkapp = record.tkapp
    if tkapp is None:
        return True
    if sys.getrefcount(tkapp) > _baseline(record) + 1:  # +1: our local above
        return False
    root = record.root_ref()
    if root is not None:
        try:
            if root.__dict__.get("tk") is tkapp:
                root.__dict__["tk"] = _ReleasedInterp(record.label or "a Tk root")
        except Exception:  # noqa: BLE001
            pass
    with _registry_lock:
        _registry.pop(id(tkapp), None)
    record.tkapp = None
    if record.pinned:
        record.pinned = False
        _mortalise(tkapp)
    # `tkapp` is now the last reference. It dies on this line, on the thread
    # that made it. Do not move this into a helper that returns it.
    del tkapp
    return True


def _holder_names(obj: Any, limit: int = 6) -> str:
    """Types still referencing `obj`, for the log line that names the leak.
    `_TkRecord` is us; anything else is the holder."""
    try:
        names = sorted({type(ref).__name__ for ref in gc.get_referrers(obj)
                        if not isinstance(ref, _TkRecord)})
    except Exception:  # noqa: BLE001 - a diagnostic may not become the failure
        return "<unknown>"
    return ", ".join(names[:limit]) or "<none>"


def _describe_ref(obj: Any) -> str:
    kind = type(obj).__name__
    try:
        if kind == "function":
            return f"function {obj.__qualname__}"
        if kind == "cell":
            return "cell"
        if kind == "frame":
            return f"frame {obj.f_code.co_name}"
        if kind == "dict":
            keys = list(obj.keys())[:4]
            return f"dict{{{', '.join(repr(k)[:24] for k in keys)}{', ...' if len(obj) > 4 else ''}}}"
    except Exception:  # noqa: BLE001
        pass
    return kind


def holder_chains(obj: Any, hops: int = HOLDER_CHAIN_HOPS,
                  width: int = HOLDER_CHAIN_WIDTH) -> list[str]:
    """Referrer chains from `obj` outwards, a few hops, for naming a holder:
    `Label <- dict{'master', 'tk'} <- cell <- function _refresh`. Best effort,
    bounded, never raises."""
    chains: list[str] = []
    skip_ids = {id(_registry), id(chains)}

    def walk(target: Any, path: list[str], depth: int) -> None:
        if depth > hops:
            chains.append(" <- ".join(path))
            return
        try:
            refs = [r for r in gc.get_referrers(target)
                    if id(r) not in skip_ids and not isinstance(r, _TkRecord)
                    and type(r).__name__ != "frame"]
        except Exception:  # noqa: BLE001
            refs = []
        if not refs:
            chains.append(" <- ".join(path))
            return
        for ref in refs[:width]:
            walk(ref, path + [_describe_ref(ref)], depth + 1)

    try:
        walk(obj, [type(obj).__name__], 1)
    except Exception:  # noqa: BLE001
        pass
    return chains[: width * width]


def _warn_still_held(record: _TkRecord) -> None:
    if record.warned_held:
        return
    record.warned_held = True
    log.warning(
        "UI dispatch: %s closed with its Tcl interpreter still referenced "
        "(%d refs, baseline %d, held by: %s). It stays pinned on this thread "
        "rather than being freed by whichever thread's garbage collection "
        "gets to it -- that is the abort CR-93 was (Tcl_AsyncDelete, exception "
        "0x80000003 in tcl86t.dll, the whole tray gone with no traceback). "
        "Chains: %s",
        record.describe(), sys.getrefcount(record.tkapp), _baseline(record),
        _holder_names(record.tkapp), " | ".join(holder_chains(record.tkapp)) or "-",
    )


def _report_orphans() -> None:
    """A pinned interpreter whose thread has exited can never be freed -- Tcl
    ties it to that thread's storage, which is gone. Say so, once each."""
    with _registry_lock:
        records = list(_registry.values())
    for record in records:
        if record.warned_orphan or record.thread.is_alive():
            continue
        record.warned_orphan = True
        log.warning(
            "UI dispatch: %s is pinned for the life of the process: the thread "
            "that built it has exited and no other thread may free a Tcl "
            "interpreter (CR-93). Held by: %s. Whatever kept it past its own "
            "release is the bug; every dialog must end on the thread that "
            "opened it with nothing of its own left alive.",
            record.describe(), _holder_names(record.tkapp),
        )


def reclaim_mine(reason: str = "") -> int:
    """Free every interpreter THIS thread built that nothing else holds.

    Runs a full collection first, on this thread: the dialog that just
    returned left its closures -- and through them its root and widgets -- as
    cyclic garbage, and collecting it here is what turns "pinned" back into
    "freed" without another thread ever touching it. Returns how many were
    freed. Never raises.
    """
    me = threading.current_thread()
    with _registry_lock:
        mine = [record for record in _registry.values() if record.thread is me]
    try:
        # Even a thread that built nothing can notice that another thread's
        # interpreter has become unfreeable (its builder exited).
        _report_orphans()
    except Exception:  # noqa: BLE001
        pass
    if not mine:
        return 0
    try:
        gc.collect()
    except Exception:  # noqa: BLE001
        pass
    freed = 0
    for record in mine:
        try:
            if _try_free(record):
                freed += 1
            elif not _root_in_use(record):
                _warn_still_held(record)
        except Exception:  # noqa: BLE001 - reclamation must never be the failure
            log.debug("UI dispatch: could not reclaim %s", record.describe(), exc_info=True)
    if freed:
        log.debug("UI dispatch: freed %d Tk interpreter(s) on the thread that built "
                  "them%s", freed, f" ({reason})" if reason else "")
    try:
        with _registry_lock:
            idle = [r for r in _registry.values() if not _root_in_use(r)]
        if len(idle) >= PINNED_WARN_AT:
            log.error(
                "UI dispatch: %d Tk interpreter(s) pinned with their windows gone "
                "-- something keeps a widget or a closure for the life of the "
                "process. Each holds ~1.8 MB; the leak is deliberate (it beats "
                "the abort) but it is still a leak. %s", len(idle),
                "; ".join(r.describe() for r in idle[:PINNED_WARN_AT]))
        if os.environ.get(_TK_AUDIT_ENV):
            log.info("UI dispatch: Tk audit%s\n%s", f" ({reason})" if reason else "", audit())
    except Exception:  # noqa: BLE001
        pass
    return freed


def release_root(root: Any, label: Optional[str] = None) -> bool:
    """End a window that owns its root: destroy it and free its Tcl
    interpreter here, on the thread that built it. Returns True if the
    interpreter died, False if it had to stay pinned.

    Call it from the thread that created the root, with every attribute that
    held a widget already cleared (`self.root = None`, the window classes'
    `_drop_widgets()`); a widget still referenced reads as a holder and the
    interpreter stays pinned, which is safe but wasteful. Called from any
    other thread it destroys nothing and frees nothing, and says so.

    Never raises: a root already gone, a Tk half torn down and a display
    that vanished all mean the same thing here.
    """
    record = adopt(root, label)
    name = label or (record.label if record is not None else None) or window_label(root)
    if record is not None and record.thread is not threading.current_thread():
        log.error(
            "UI dispatch: release_root(%s) called on thread %r, but the root was "
            "built on thread %r -- leaving it pinned rather than freeing it here "
            "(CR-93). Close a window from the thread that opened it.",
            name, threading.current_thread().name, record.thread.name)
        return False
    try:
        # apply_window_icon parks a PhotoImage on the root so Tk does not drop
        # the icon; it is bound to this interpreter and must go with it.
        root.__dict__.pop("_ccsync_icon_image", None)
    except Exception:  # noqa: BLE001
        pass
    _destroy_quietly(root, name)
    if record is None:
        return True
    reclaim_mine(f"release of {name}")
    return record.tkapp is None


def pinned_records() -> list[_TkRecord]:
    with _registry_lock:
        return list(_registry.values())


def parked_roots(ident: Optional[int] = None) -> list:
    """Roots whose interpreter is still pinned (window gone or not), for
    tests and diagnostics. `ident` narrows to one creating thread."""
    with _registry_lock:
        records = [r for r in _registry.values() if ident is None or r.ident == ident]
    roots = []
    for record in records:
        root = record.root_ref()
        if root is not None:
            roots.append(root)
    return roots


def audit() -> str:
    """Every interpreter this process holds, one paragraph each: what built
    it, on which thread, whether that thread and its window are still alive,
    and what references it (with chains). This is the probe that names the
    next holder on the machine it happens on -- CCSYNC_TK_AUDIT=1 logs it
    after every reclamation pass."""
    with _registry_lock:
        records = list(_registry.values())
    if not records:
        return "  no Tk interpreters registered"
    lines = []
    me = threading.current_thread()
    for record in records:
        alive = record.thread.is_alive()
        lines.append(
            f"  - {record.describe()}: thread {'alive' if alive else 'EXITED'}"
            f"{' (this thread)' if record.thread is me else ''}, window "
            f"{'open' if _root_in_use(record) else 'gone'}, "
            f"{sys.getrefcount(record.tkapp) - 1} refs (baseline {_baseline(record)}), "
            f"pinned={record.pinned}, age {time.monotonic() - record.created:.0f}s, "
            f"held by: {_holder_names(record.tkapp)}")
        for chain in holder_chains(record.tkapp):
            lines.append(f"      {chain}")
    return "\n".join(lines)


def _reset_registry_for_tests() -> None:
    """Give back every pin and forget the records. Only the suite calls this
    -- a released pin in production is an interpreter the wrong thread can
    free."""
    with _registry_lock:
        records = list(_registry.values())
        _registry.clear()
    for record in records:
        tkapp, record.tkapp = record.tkapp, None
        if record.pinned and tkapp is not None:
            record.pinned = False
            _mortalise(tkapp)


# Every root in this process is pinned from here on. Explicit as well
# (app.run calls it too, for the log line), but importing this module is
# enough: every dialog site imports it before it builds anything.
install_tk_guard()


def stop() -> None:
    """Stop main-thread dispatch. No-op when there is none (win32).

    Also destroys any dialog the UI thread is still parked in, which is what
    lets a `tkwait` end and `serve()` return -- see _break_open_dialogs.

    The stopped dispatcher stays registered on purpose: a dialog requested
    after this point must fail fast with UIDispatchStopped, NOT quietly fall
    back to building a Tk root on some daemon thread while macOS is tearing
    the process down.
    """
    dispatcher = _active
    if dispatcher is None:
        return
    dispatcher.stop()
