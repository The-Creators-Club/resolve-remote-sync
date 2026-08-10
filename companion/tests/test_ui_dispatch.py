"""ui_dispatch: where a Tk root is allowed to be built.

Two halves, and only one of them can be honestly proven on this machine:

  - INLINE (win32, and anything not darwin). dispatch(fn) is a plain call on
    the calling thread. These tests exist to pin that down, because the whole
    macOS port rests on the Windows behaviour not moving a millimetre.

  - MAIN-THREAD (darwin). The marshaling and lifecycle logic is exercised
    here against a FAKE root (see FakeRoot below) driven by a real thread, so
    ordering, blocking, exception propagation, stop() and reentrancy are all
    genuinely tested. What CANNOT be tested from Windows is that a real
    Tk-Aqua mainloop and pystray's run_detached() coexist on the same main
    thread -- that is the first-Mac-run spike, and no test here pretends
    otherwise.

Never a real tkinter.Tk() -- conftest._no_real_tk_windows forbids it, and the
tk_factory seam is exactly what makes that possible.
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest

from ccsync_companion import ui_dispatch


@pytest.fixture(autouse=True)
def _no_dispatcher_leaks_between_tests(monkeypatch):
    """Each test starts with no registered dispatcher and leaves none.

    The façade is module state (a process has exactly one main thread), so
    without this a test that registers one would make every later test's
    dispatch() marshal into a dead pump.
    """
    monkeypatch.setattr(ui_dispatch, "_active", None)
    yield
    dispatcher = ui_dispatch._active
    if dispatcher is not None:
        dispatcher.stop()


class FakeRoot:
    """Stands in for the hidden tk.Tk() root: after/mainloop/quit/destroy.

    Deliberately a real (if crude) event loop rather than a mock -- the
    property under test is "the fn runs on the thread inside mainloop(),
    while the caller blocks", and a mock that just records calls proves
    nothing about that.
    """

    def __init__(self) -> None:
        self.withdrawn = False
        self.destroyed = False
        self.mainloop_running = False
        self._pending: list[tuple[float, object]] = []
        self._lock = threading.Lock()
        self._quit = threading.Event()

    def withdraw(self) -> None:
        self.withdrawn = True

    def after(self, ms, callback):
        with self._lock:
            self._pending.append((time.monotonic() + (ms / 1000.0), callback))

    def run_pending(self) -> bool:
        """Run every callback that is now due; True if any ran.

        Split out of mainloop() because `tkwait window` runs the SAME timer
        queue while it waits -- Tcl's notifier is per thread, not per
        interpreter -- and that is precisely the property stop() relies on to
        break a stuck dialog out. WedgedDialogRoot below calls this.
        """
        now = time.monotonic()
        due = []
        with self._lock:
            keep = []
            for when, callback in self._pending:
                (due if when <= now else keep).append((when, callback))
            self._pending = keep
        for _when, callback in due:
            callback()
        return bool(due)

    def mainloop(self) -> None:
        self.mainloop_running = True
        try:
            while not self._quit.is_set():
                if not self.run_pending():
                    time.sleep(0.001)
        finally:
            self.mainloop_running = False

    def quit(self) -> None:
        self._quit.set()

    def destroy(self) -> None:
        self.destroyed = True
        self._quit.set()


@contextlib.contextmanager
def serving(poll_ms: int = 1, register: bool = False, monkeypatch=None):
    """A dispatcher whose start()+serve() run on one thread -- the stand-in
    for the process's main thread."""
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=poll_ms)
    ready = threading.Event()
    pump_ident: list[int] = []

    def _main_thread() -> None:
        dispatcher.start()
        pump_ident.append(threading.get_ident())
        ready.set()
        dispatcher.serve()

    thread = threading.Thread(target=_main_thread, name="fake-main-thread", daemon=True)
    thread.start()
    assert ready.wait(5.0), "the fake main thread never got going"
    if register:
        assert monkeypatch is not None
        monkeypatch.setattr(ui_dispatch, "_active", dispatcher)
    try:
        yield dispatcher, root, pump_ident[0]
    finally:
        dispatcher.stop()
        thread.join(timeout=5.0)


def _dispatch_on_thread(dispatcher, fn, name="caller"):
    """Call dispatcher.dispatch(fn) on a fresh thread; returns (thread, out)
    where out gets "value" or "error" once it returns."""
    out: dict = {}

    def _call() -> None:
        try:
            out["value"] = dispatcher.dispatch(fn)
        except BaseException as exc:  # noqa: BLE001 -- the point of the test
            out["error"] = exc

    thread = threading.Thread(target=_call, name=name, daemon=True)
    thread.start()
    return thread, out


# ===========================================================================
# Platform seam
# ===========================================================================


def test_platform_mode_only_darwin_needs_the_main_thread():
    assert ui_dispatch.platform_mode("win32") == ui_dispatch.MODE_INLINE
    assert ui_dispatch.platform_mode("linux") == ui_dispatch.MODE_INLINE
    assert ui_dispatch.platform_mode("darwin") == ui_dispatch.MODE_MAIN_THREAD


def test_start_does_nothing_at_all_off_darwin():
    """The Windows guarantee: no dispatcher, no thread, no hidden root -- so
    dispatch() stays the plain call it has always been."""
    assert ui_dispatch.start(mode=ui_dispatch.MODE_INLINE) is None
    assert ui_dispatch.active() is None
    assert ui_dispatch.uses_main_thread() is False


def test_stop_is_a_no_op_when_nothing_was_started():
    ui_dispatch.stop()  # must not raise -- app.shutdown() calls this always


# ===========================================================================
# Inline mode (win32): byte-identical to what the companion did before
# ===========================================================================


def test_inline_dispatch_runs_on_the_calling_thread():
    seen: dict = {}

    def _fn():
        seen["ident"] = threading.get_ident()
        return "done"

    assert ui_dispatch.dispatch(_fn) == "done"
    assert seen["ident"] == threading.get_ident()


def test_inline_dispatch_from_a_worker_thread_stays_on_that_thread():
    """The watcher/tray threads build their own roots on Windows and must
    keep doing so -- no marshaling, no main thread involved."""
    seen: dict = {}

    def _fn():
        seen["ident"] = threading.get_ident()

    thread = threading.Thread(target=lambda: ui_dispatch.dispatch(_fn), daemon=True)
    thread.start()
    thread.join(5.0)
    assert seen["ident"] == thread.ident


def test_inline_dispatch_propagates_the_exception_unchanged():
    boom = RuntimeError("no display name and no $DISPLAY environment variable")

    def _fn():
        raise boom

    with pytest.raises(RuntimeError) as excinfo:
        ui_dispatch.dispatch(_fn)
    assert excinfo.value is boom


# ===========================================================================
# Main-thread mode (darwin), driven by the fake root
# ===========================================================================


def test_the_hidden_root_is_created_and_withdrawn():
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root)
    assert dispatcher.start() is root
    assert root.withdrawn, "the pump's own root must never be a visible window"
    dispatcher.stop()
    assert root.destroyed


def test_dispatched_fn_runs_on_the_pump_thread_and_returns_its_value():
    with serving() as (dispatcher, _root, pump_ident):
        seen: dict = {}

        def _fn():
            seen["ident"] = threading.get_ident()
            return 42

        thread, out = _dispatch_on_thread(dispatcher, _fn)
        thread.join(5.0)
        assert out.get("error") is None
        assert out["value"] == 42
        assert seen["ident"] == pump_ident
        assert seen["ident"] != threading.get_ident()


def test_the_caller_blocks_until_the_fn_has_finished():
    """The dialogs rely on this: show_popup() must not return until the
    window has closed, or the popup lock is released while a root is live."""
    with serving() as (dispatcher, _root, _pump_ident):
        finished = []

        def _fn():
            time.sleep(0.05)
            finished.append("fn")
            return "ok"

        assert dispatcher.dispatch(_fn) == "ok"
        assert finished == ["fn"], "dispatch() returned before the fn was done"


def test_the_fns_exception_reaches_the_caller():
    with serving() as (dispatcher, _root, _pump_ident):
        boom = RuntimeError("Tcl is wedged")

        def _fn():
            raise boom

        with pytest.raises(RuntimeError) as excinfo:
            dispatcher.dispatch(_fn)
        assert excinfo.value is boom


def test_one_failing_dialog_does_not_kill_the_pump():
    """Every later dialog in the session depends on the pump surviving."""
    with serving() as (dispatcher, _root, _pump_ident):
        with pytest.raises(ValueError):
            dispatcher.dispatch(lambda: (_ for _ in ()).throw(ValueError("nope")))
        assert dispatcher.dispatch(lambda: "still alive") == "still alive"


def test_queued_calls_run_in_the_order_they_were_queued():
    with serving() as (dispatcher, _root, _pump_ident):
        gate = threading.Event()
        order: list[str] = []

        def _hold():
            order.append("gate")
            gate.wait(5.0)

        gate_thread, _gate_out = _dispatch_on_thread(dispatcher, _hold, name="gate")
        while "gate" not in order:
            time.sleep(0.001)

        threads = []
        for name in ("a", "b", "c"):
            thread, _out = _dispatch_on_thread(
                dispatcher, lambda n=name: order.append(n), name=name)
            threads.append(thread)
            # Wait until THIS one is queued before starting the next, so the
            # test is asserting on the queue's order and not on how the OS
            # happened to schedule three threads.
            expected = len(threads)
            deadline = time.monotonic() + 5.0
            while len(dispatcher._queue) < expected and time.monotonic() < deadline:
                time.sleep(0.001)
            assert len(dispatcher._queue) == expected

        gate.set()
        gate_thread.join(5.0)
        for thread in threads:
            thread.join(5.0)
        assert order == ["gate", "a", "b", "c"]


def test_stop_unblocks_everyone_still_waiting_with_a_clear_error(caplog):
    """Shutdown must never leave a thread parked forever on a main thread
    that has left its mainloop."""
    import logging

    with serving() as (dispatcher, _root, _pump_ident):
        gate = threading.Event()
        started = threading.Event()

        def _hold():
            started.set()
            gate.wait(5.0)

        gate_thread, _gate_out = _dispatch_on_thread(dispatcher, _hold, name="gate")
        assert started.wait(5.0)

        waiter_thread, waiter_out = _dispatch_on_thread(
            dispatcher, lambda: "never runs", name="waiter")
        while not dispatcher._queue:
            time.sleep(0.001)

        with caplog.at_level(logging.WARNING, logger="ccsync.ui"):
            dispatcher.stop()
        waiter_thread.join(5.0)
        gate.set()
        gate_thread.join(5.0)

    assert isinstance(waiter_out.get("error"), ui_dispatch.UIDispatchStopped)
    assert "value" not in waiter_out
    assert any("cancelled" in r.message or "cancelled" in r.getMessage()
               for r in caplog.records), "a cancelled window must be logged, not silent"


def test_dispatch_after_stop_fails_fast_instead_of_blocking():
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    dispatcher.start()
    dispatcher.stop()

    thread, out = _dispatch_on_thread(dispatcher, lambda: "nope")
    thread.join(5.0)
    assert not thread.is_alive(), "dispatch() after stop() must not block"
    assert isinstance(out.get("error"), ui_dispatch.UIDispatchStopped)
    assert "stopped" in str(out["error"])


def test_reentrant_dispatch_runs_inline_instead_of_deadlocking(monkeypatch):
    """A dispatched dialog that opens another dialog (confirm inside a tray
    action) would otherwise queue itself behind the pump that is running it."""
    with serving(register=True, monkeypatch=monkeypatch) as (dispatcher, _root, pump_ident):
        seen: dict = {}

        def _outer():
            def _inner():
                seen["inner_ident"] = threading.get_ident()
                return "inner"

            seen["outer_ident"] = threading.get_ident()
            seen["inner_result"] = ui_dispatch.dispatch(_inner)
            return "outer"

        thread, out = _dispatch_on_thread(dispatcher, _outer)
        thread.join(5.0)
        assert not thread.is_alive(), "reentrant dispatch deadlocked"
        assert out.get("error") is None
        assert out["value"] == "outer"
        assert seen["inner_result"] == "inner"
        assert seen["inner_ident"] == seen["outer_ident"] == pump_ident


def test_dispatch_from_the_owner_thread_before_serve_runs_inline():
    """start() has happened but the mainloop has not -- queueing there would
    park the only thread that could ever run the queue."""
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    dispatcher.start()  # this thread is now the owner
    try:
        assert dispatcher.dispatch(lambda: threading.get_ident()) == threading.get_ident()
    finally:
        dispatcher.stop()


def test_serve_returns_when_the_apps_stop_event_is_set():
    """app.run()'s main loop on macOS: serve(self._stop_event) replaces the
    `while not stop_event: wait(1.0)` loop, so it has to end the same way."""
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    stop_event = threading.Event()
    done = threading.Event()

    def _main_thread() -> None:
        dispatcher.start()
        dispatcher.serve(stop_event)
        done.set()

    thread = threading.Thread(target=_main_thread, daemon=True)
    thread.start()
    time.sleep(0.05)
    assert not done.is_set(), "serve() must keep the main thread until asked to stop"
    stop_event.set()
    assert done.wait(5.0), "serve() ignored the stop event"
    thread.join(5.0)
    assert root.destroyed
    assert dispatcher.stopped


def test_serve_ending_leaves_dispatch_failing_fast_not_hanging():
    """Between the mainloop exiting and shutdown() finishing, a dialog
    request must bounce off, not block a shutting-down thread."""
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    stop_event = threading.Event()
    done = threading.Event()

    def _main_thread() -> None:
        dispatcher.start()
        dispatcher.serve(stop_event)
        done.set()

    thread = threading.Thread(target=_main_thread, daemon=True)
    thread.start()
    stop_event.set()
    assert done.wait(5.0)
    thread.join(5.0)

    caller, out = _dispatch_on_thread(dispatcher, lambda: "nope")
    caller.join(5.0)
    assert isinstance(out.get("error"), ui_dispatch.UIDispatchStopped)


# ===========================================================================
# The façade the rest of the package actually calls
# ===========================================================================


def test_module_dispatch_uses_the_registered_dispatcher(monkeypatch):
    with serving(register=True, monkeypatch=monkeypatch) as (_d, _root, pump_ident):
        assert ui_dispatch.uses_main_thread() is True
        assert ui_dispatch.dispatch(threading.get_ident) == pump_ident


def test_start_registers_a_main_thread_dispatcher(monkeypatch):
    root = FakeRoot()
    dispatcher = ui_dispatch.start(
        mode=ui_dispatch.MODE_MAIN_THREAD, tk_factory=lambda: root, poll_ms=1)
    try:
        assert dispatcher is not None
        assert ui_dispatch.active() is dispatcher
        assert root.withdrawn
    finally:
        ui_dispatch.stop()
    assert root.destroyed
    assert dispatcher.stopped


def test_a_stopped_dispatcher_stays_registered_so_late_dialogs_cannot_sneak_a_root(
        monkeypatch):
    """If stop() de-registered it, dispatch() would fall back to INLINE and
    build a Tk root on a random thread while macOS tears the process down --
    the exact thing this module exists to prevent."""
    root = FakeRoot()
    ui_dispatch.start(mode=ui_dispatch.MODE_MAIN_THREAD, tk_factory=lambda: root, poll_ms=1)
    ui_dispatch.stop()

    assert ui_dispatch.active() is not None
    assert ui_dispatch.uses_main_thread() is False
    built = []
    with pytest.raises(ui_dispatch.UIDispatchStopped):
        ui_dispatch.dispatch(lambda: built.append("root"))
    assert built == []


def test_a_stopped_dispatcher_never_builds_another_root():
    """Shutdown racing startup: serve() must return, not resurrect the pump
    with a brand new Tk root while the process is going away."""
    roots: list = []

    def _factory():
        root = FakeRoot()
        roots.append(root)
        return root

    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=_factory, poll_ms=1)
    dispatcher.start()
    dispatcher.stop()
    assert len(roots) == 1 and roots[0].destroyed

    with pytest.raises(ui_dispatch.UIDispatchStopped):
        dispatcher.start()

    dispatcher.serve()  # must simply return
    assert len(roots) == 1
    assert roots[0].mainloop_running is False


# ===========================================================================
# run_dialog: how a dialog's own root is waited on (MAC-6)
# ===========================================================================


class FakeDialogRoot:
    """A dialog root that records which loop was used to wait on it."""

    def __init__(self, exists: bool = True) -> None:
        self.exists = exists
        self.calls: list[str] = []

    def winfo_exists(self) -> bool:
        return self.exists

    def mainloop(self) -> None:
        self.calls.append("mainloop")

    def wait_window(self, window) -> None:
        assert window is self
        self.calls.append("wait_window")


def test_run_dialog_uses_mainloop_off_darwin(monkeypatch):
    """Windows must keep the loop it has run for a year -- there is no other
    main window on the thread, so mainloop() returns on destroy."""
    monkeypatch.setattr(ui_dispatch, "_active", None)
    root = FakeDialogRoot()
    ui_dispatch.run_dialog(root)
    assert root.calls == ["mainloop"]


def test_run_dialog_waits_on_the_window_when_a_dispatcher_owns_the_thread(monkeypatch):
    """macOS: the dispatcher's hidden root keeps Tk_GetNumMainWindows() above
    zero forever, so a nested mainloop() would never return -- the caller
    would hold app._popup_active_lock for the rest of the session and every
    later dialog would be refused with "Another CCSync window is already
    open". tkwait window returns on destroy instead."""
    with serving(register=True, monkeypatch=monkeypatch):
        root = FakeDialogRoot()
        ui_dispatch.run_dialog(root)
    assert root.calls == ["wait_window"]


def test_run_dialog_returns_at_once_when_the_window_is_already_gone(monkeypatch):
    """tkwait on a destroyed window raises; a dialog that closed early is
    simply finished."""
    with serving(register=True, monkeypatch=monkeypatch):
        root = FakeDialogRoot(exists=False)
        ui_dispatch.run_dialog(root)
    assert root.calls == []


def test_a_stopped_dispatcher_still_sends_dialogs_to_mainloop(monkeypatch):
    """Once the dispatcher has stopped there is no hidden root left holding
    the window count up, so mainloop() is correct again."""
    with serving(register=True, monkeypatch=monkeypatch) as (dispatcher, _root, _ident):
        dispatcher.stop()
        root = FakeDialogRoot()
        ui_dispatch.run_dialog(root)
    assert root.calls == ["mainloop"]


# ===========================================================================
# stop() breaks a nested tkwait (MAC-11's follow-up)
#
# A dialog that never destroys itself parks the pump INSIDE `tkwait window`:
# the pump timer never re-arms, every later dialog request queues forever,
# and serve()'s mainloop cannot return -- so SIGTERM ran the whole shutdown
# and then sat there with the window on screen, and it took `kill -9`
# (2026-08-05, live). The window below is that window.
# ===========================================================================


class WedgedDialogRoot:
    """A dialog root that NEVER closes itself -- only a destroy ends it.

    Its wait_window() models `tkwait window` honestly: it keeps running the
    hidden root's due timer callbacks (Tcl's notifier is per thread, not per
    interpreter) and returns only once this window has been destroyed. So a
    test that never destroys it really does park the pump, exactly like the
    fix-all popup did.
    """

    def __init__(self, hidden: FakeRoot, name: str = "CCSync — FIX ALL") -> None:
        self._hidden = hidden
        self._name = name
        self.destroyed = threading.Event()
        self.parked = threading.Event()
        # Run once inside the tkwait, before this window starts waiting --
        # how a dialog opens a second dialog on the same thread.
        self.on_parked = None

    def title(self) -> str:
        return self._name

    def winfo_exists(self) -> bool:
        return not self.destroyed.is_set()

    def mainloop(self) -> None:  # pragma: no cover -- darwin path never calls it
        raise AssertionError("a nested mainloop() is the MAC-6 bug")

    def wait_window(self, window) -> None:
        assert window is self
        self.parked.set()
        if self.on_parked is not None:
            self.on_parked()
        while not self.destroyed.is_set():
            if not self._hidden.run_pending():
                time.sleep(0.001)

    def destroy(self) -> None:
        self.destroyed.set()


def _park_a_dialog(dispatcher, root, name="CCSync — FIX ALL"):
    """Open a wedged dialog through dispatch(), the way a real one arrives
    (the pump runs it inside its own timer callback). Returns the window and
    the caller's thread."""
    window = WedgedDialogRoot(root, name)
    thread, out = _dispatch_on_thread(
        dispatcher, lambda: ui_dispatch.run_dialog(window), name="dialog-caller")
    assert window.parked.wait(5.0), "the dialog never reached tkwait"
    return window, thread, out


def test_the_window_being_waited_on_is_tracked_while_it_is_open(monkeypatch):
    with serving(register=True, monkeypatch=monkeypatch) as (dispatcher, root, _ident):
        window, thread, _out = _park_a_dialog(dispatcher, root)
        assert dispatcher.open_dialogs == [window]
        window.destroy()
        thread.join(5.0)
        assert dispatcher.open_dialogs == [], (
            "a dialog that closed normally must not still look stuck")


def test_stop_destroys_the_window_the_pump_is_parked_in(monkeypatch, caplog):
    """The whole point: SIGTERM must be able to end a dialog that cannot end
    itself, so serve() returns and the process exits without `kill -9`."""
    import logging

    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    monkeypatch.setattr(ui_dispatch, "_active", dispatcher)
    served = threading.Event()

    def _main_thread() -> None:
        dispatcher.start()
        dispatcher.serve()
        served.set()

    main_thread = threading.Thread(target=_main_thread, name="fake-main-thread", daemon=True)
    main_thread.start()
    window, caller, _out = _park_a_dialog(dispatcher, root)
    assert not served.is_set(), "serve() cannot return while a dialog is parked"

    with caplog.at_level(logging.ERROR, logger="ccsync.ui"):
        dispatcher.stop()

    # stop() hands the destroy to the UI thread rather than reaching into Tk
    # from here -- the parked tkwait runs it on its next turn round the loop.
    assert window.destroyed.wait(5.0), "the stuck window was never destroyed"
    caller.join(5.0)
    assert not caller.is_alive(), "run_dialog() never came back out of tkwait"
    assert served.wait(5.0), "serve() still could not return -- this is the kill -9 case"
    main_thread.join(5.0)
    assert root.destroyed
    # ...and it says which window it had to close, by name.
    messages = [r.getMessage() for r in caplog.records]
    assert any("FIX ALL" in m and "still open" in m for m in messages), messages


def test_a_normal_shutdown_with_no_window_open_logs_nothing_alarming(monkeypatch, caplog):
    import logging

    with caplog.at_level(logging.ERROR, logger="ccsync.ui"):
        with serving(register=True, monkeypatch=monkeypatch) as (dispatcher, _root, _i):
            dispatcher.dispatch(lambda: "a dialog that closed properly")
    assert [r.getMessage() for r in caplog.records] == []


def test_nested_dialogs_are_all_closed_innermost_first(monkeypatch):
    """A dialog may open another one (a confirm inside a tray action runs
    reentrantly on the same thread). The outer tkwait cannot return until the
    inner one has, so the inner window must be destroyed too."""
    with serving(register=True, monkeypatch=monkeypatch) as (dispatcher, root, _ident):
        outer = WedgedDialogRoot(root, "CCSync — outer")
        inner = WedgedDialogRoot(root, "CCSync — inner")
        outer.on_parked = lambda: ui_dispatch.run_dialog(inner)

        thread, _out = _dispatch_on_thread(
            dispatcher, lambda: ui_dispatch.run_dialog(outer), name="nested")
        assert inner.parked.wait(5.0)
        assert dispatcher.open_dialogs == [outer, inner]

        dispatcher.stop()
        thread.join(5.0)
        assert inner.destroyed.wait(5.0) and outer.destroyed.wait(5.0)
        assert not thread.is_alive(), "the outer dialog never came back out"


def test_stop_from_the_ui_thread_itself_destroys_the_window_directly(monkeypatch):
    """The pump calls stop() on itself when it cannot re-arm. Nothing is
    parked below it then, so the destroy needs no round trip."""
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    dispatcher.start()  # this thread is the owner
    window = WedgedDialogRoot(root, "CCSync — sign in")
    assert dispatcher.note_dialog(window) is True

    def _no_threads(*_args, **_kwargs):
        raise AssertionError("the owner thread must not marshal to itself")

    monkeypatch.setattr(ui_dispatch.threading, "Thread", _no_threads)
    dispatcher.stop()
    assert window.destroyed.is_set()


def test_a_main_thread_that_never_answers_does_not_hang_stop(monkeypatch, caplog):
    """The bound that makes this safe to call from a signal handler: if the
    UI thread is in no event loop we can reach, stop() gives up and says so
    (app.py's hard-exit backstop is what covers the rest)."""
    import logging

    class _DeafRoot(FakeRoot):
        def after(self, ms, callback):
            threading.Event().wait()  # never returns, like a blocked marshal

    root = _DeafRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    dispatcher.start()
    dispatcher._owner_ident = -1  # pretend the UI thread is somebody else
    window = WedgedDialogRoot(root, "CCSync — FIX ALL")
    dispatcher.note_dialog(window)
    monkeypatch.setattr(ui_dispatch, "DIALOG_BREAK_TIMEOUT_SECONDS", 0.05)

    started = time.monotonic()
    with caplog.at_level(logging.ERROR, logger="ccsync.ui"):
        dispatcher.stop()
    assert time.monotonic() - started < 3.0, "stop() blocked on the UI thread"
    assert any("would not even accept" in r.getMessage() for r in caplog.records)


def test_a_dialog_opening_into_a_shutdown_is_closed_not_waited_on(monkeypatch, caplog):
    """The race stop() cannot otherwise see: the window was built between
    uses_main_thread() and note_dialog(). Parking in tkwait there would be a
    wedge with nobody left to break it."""
    import logging

    with serving(register=True, monkeypatch=monkeypatch) as (dispatcher, root, _ident):
        window = WedgedDialogRoot(root, "CCSync — sign in")
        real_uses = ui_dispatch.uses_main_thread

        def _uses_main_thread():
            answer = real_uses()
            dispatcher.stop()  # stop() lands in the gap
            return answer

        monkeypatch.setattr(ui_dispatch, "uses_main_thread", _uses_main_thread)
        with caplog.at_level(logging.WARNING, logger="ccsync.ui"):
            ui_dispatch.run_dialog(window)
    assert window.destroyed.is_set()
    assert not window.parked.is_set(), "it parked in tkwait during a shutdown"
    assert any("closing it" in r.getMessage() for r in caplog.records)


def test_serving_reports_whether_the_mainloop_is_up(monkeypatch):
    """app.py's shutdown backstop keys on this to tell "the UI thread is
    wedged" from "the UI thread has already gone"."""
    root = FakeRoot()
    dispatcher = ui_dispatch.MainThreadDispatcher(tk_factory=lambda: root, poll_ms=1)
    assert dispatcher.serving is False
    with serving() as (live, _root, _ident):
        assert live.serving is True
    assert live.serving is False
