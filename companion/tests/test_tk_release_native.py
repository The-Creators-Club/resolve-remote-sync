"""The CR-93 abort itself, with a real Tk, in a subprocess.

Every other test in this suite talks to a fake root, because conftest forbids
a real `tkinter.Tk()` in-process and because the failure being demonstrated
here is not an exception: a Tcl interpreter freed on a thread that did not
create it calls Tcl_Panic, i.e. abort(). The process dies mid-instruction --
no traceback, no `finally`, no pytest report. So the only honest way to test
it is to run it somewhere we are allowed to lose: a child process, whose EXIT
CODE is the assertion.

What it pins, in two shapes:

  the refcount shape (2026-08-29) -- a widget kept past its window, dropped
                 by another thread, kills the process ("Tcl_AsyncDelete: async
                 handler deleted by the wrong thread"); release_root() on the
                 building thread keeps it alive.
  the GC shape (2026-08-30, the recurrence) -- a dialog whose nested
                 functions form a reference cycle that reaches the root. The
                 frame ending frees nothing; the cyclic collector frees it,
                 on whatever thread next trips it. No refcount taken inside
                 the dialog can see this. The cure is the pin every
                 interpreter now carries from birth (ui_dispatch's guard on
                 tkinter.Tk.__init__) plus reclamation on the building thread
                 at the end of dispatch(): the interpreter is freed there, or
                 stays pinned -- never freed elsewhere.

If a "disease" test ever starts passing as "survived", the platform changed
and the guard can be revisited.

Skipped wherever a child cannot build a Tk root ON A WORKER THREAD -- a
headless runner (no display) and macOS both, the latter because Aqua's Tk
belongs to the main thread and a secondary-thread root simply never returns.
CR-93's abort is a Windows/X11 shape; a Mac cannot get far enough to have it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import ccsync_companion

SRC_DIR = str(Path(ccsync_companion.__file__).resolve().parent.parent)
# Long enough for a cold Tk import on a loaded machine, short enough that a
# child that somehow blocks on a dialog does not hold the suite.
CHILD_TIMEOUT_SECONDS = 120

# The probe has to be the SHAPE the tests use, not merely "does Tk work".
# Every child below builds its root on a WORKER thread, and on macOS's Aqua Tk
# that is not a thing you may do: Tk initialises against NSApplication, which
# belongs to the main thread, so the child blocks for ever rather than failing
# -- 120 s per test, three tests, and a red CI run that says "timeout" about a
# platform limit (2026-08-29, first macOS runner to reach this file). A probe
# that creates a root on the main thread proves nothing about that.
PROBE = """
import threading, tkinter as tk


def build():
    root = tk.Tk()
    root.withdraw()
    root.update()
    root.destroy()


thread = threading.Thread(target=build, name="probe")
thread.start()
thread.join()
print("ok")
"""
# Short: a probe that has not answered in this long is the hang it is looking
# for, and waiting the full child timeout for it only delays the skip.
PROBE_TIMEOUT_SECONDS = 30

# A window built on a worker thread that leaves ONE widget behind, exactly as
# WorkProgressWindow did before 2026-08-18 and PopupDialog's per-row
# StringVars did until CR-93.
LEAK_ON_A_WORKER_THREAD = """
import threading, tkinter as tk
KEPT = []


def build():
    root = tk.Tk()
    root.withdraw()
    KEPT.append(tk.Label(root, text="held"))
    root.update()
    {teardown}


thread = threading.Thread(target=build, name="dialog")
thread.start()
thread.join()
KEPT.clear()          # the main thread drops the last Tk object
print("survived")
"""

# The Settings window's shape (settings_window._build_settings_window): a
# nested function that schedules ITSELF with root.after() -- function ->
# closure -> cell -> the same function, a cycle -- and reaches `root` through
# its closure. Every Tk object is a local; nothing is kept in an attribute;
# release_root() is never called, because until 2026-08-30 "all locals"
# was believed to be safe by construction. The frame returns, the cycle is
# garbage, and the FIRST full collection on ANY thread frees the root and
# with it the interpreter. `gc.disable()` keeps the worker thread's own
# allocations from collecting it early, which is exactly what happens live:
# the objects are old by the time the window closes, and only a full pass
# reaches them.
CYCLE_ON_A_WORKER_THREAD = """
import gc, threading, tkinter as tk
{prelude}
gc.disable()


def dialog():
    root = tk.Tk()
    root.withdraw()
    state = {{"closed": False}}

    def _close():
        state["closed"] = True
        root.destroy()

    def _refresh():
        if state["closed"]:
            return
        root.after(10, _refresh)

    _refresh()
    root.after(50, _close)
    root.mainloop()


def build():
    {show}


thread = threading.Thread(target=build, name="dialog")
thread.start()
thread.join()
gc.collect()          # the watcher thread's library read, in one line
print("survived")
"""


def _run(code: str, timeout: float = CHILD_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC_DIR + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=timeout, env=env)


@pytest.fixture(scope="module")
def tk_runs() -> None:
    try:
        probe = _run(PROBE, timeout=PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        pytest.skip("Tk on a worker thread hangs here (macOS Aqua): CR-93's "
                    "shape cannot be reproduced on this platform")
    except Exception as exc:  # noqa: BLE001 - no python, no subprocess: skip
        pytest.skip(f"cannot run a child interpreter: {exc}")
    if probe.returncode != 0 or "ok" not in probe.stdout:
        pytest.skip("no display: a real Tk root cannot be created here")


# -- the refcount shape (2026-08-29) ------------------------------------------


def test_dropping_a_widget_on_another_thread_kills_the_process(tk_runs):
    """The disease. This is what "the tray keeps closing itself" WAS."""
    result = _run(LEAK_ON_A_WORKER_THREAD.format(teardown="root.destroy()"))
    assert result.returncode != 0, (
        "a Tk interpreter freed on the wrong thread no longer aborts -- "
        "re-read CR-93 before relaxing anything it added")
    assert "survived" not in result.stdout
    assert "Tcl_AsyncDelete" in (result.stderr or "")


def test_release_root_keeps_the_process_alive_through_the_same_leak(tk_runs):
    """The cure, end to end: the leak is still there (this test does not
    pretend to have found every holder), and the process lives anyway --
    including through interpreter shutdown, which is its own abort without
    the pin (measured 2026-08-29)."""
    teardown = ("from ccsync_companion import ui_dispatch\n    "
                "ui_dispatch.release_root(root, 'the test window')")
    result = _run(LEAK_ON_A_WORKER_THREAD.format(teardown=teardown))
    assert result.returncode == 0, (
        f"the guarded teardown still aborted: {result.stderr[-2000:]}")
    assert "survived" in result.stdout


def test_a_clean_window_needs_no_pin_and_still_exits_cleanly(tk_runs):
    """The ordinary path: nothing held, nothing pinned, and the interpreter
    is freed on the thread that made it rather than kept for the session."""
    code = """
import threading, tkinter as tk
from ccsync_companion import ui_dispatch


def build():
    root = tk.Tk()
    root.withdraw()
    label = tk.Label(root, text="local only")
    root.update()
    del label
    assert ui_dispatch.release_root(root, "the test window") is True
    assert ui_dispatch.pinned_records() == []


thread = threading.Thread(target=build, name="dialog")
thread.start()
thread.join()
print("survived")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "survived" in result.stdout


# -- the GC shape (2026-08-30) ------------------------------------------------


def test_a_closure_cycle_collected_on_another_thread_kills_the_process(tk_runs):
    """The disease as it recurred on the fixed build: no widget is kept
    anywhere, the dialog is all locals, and the process still dies -- on the
    thread that ran the garbage collector, minutes later."""
    result = _run(CYCLE_ON_A_WORKER_THREAD.format(prelude="", show="dialog()"))
    assert result.returncode != 0, (
        "a root freed by the cyclic GC on another thread no longer aborts -- "
        "re-read CR-93's 2026-08-30 recurrence before relaxing anything")
    assert "survived" not in result.stdout
    assert "Tcl_AsyncDelete" in (result.stderr or "")


def test_dispatch_frees_the_cycles_root_on_the_thread_that_built_it(tk_runs):
    """The cure: through dispatch(), the dialog thread collects its own
    garbage when the dialog returns and frees the interpreter itself. The
    main thread's collection then finds nothing of Tk's to free."""
    show = ("ui_dispatch.dispatch(dialog)\n    "
            "assert ui_dispatch.pinned_records() == [], 'not freed on the dialog thread'\n    "
            "print('freed on', threading.current_thread().name)")
    result = _run(CYCLE_ON_A_WORKER_THREAD.format(
        prelude="from ccsync_companion import ui_dispatch", show=show))
    assert result.returncode == 0, result.stderr[-2000:]
    assert "freed on dialog" in result.stdout
    assert "survived" in result.stdout


def test_a_root_nobody_reclaims_stays_pinned_and_the_process_lives(tk_runs):
    """The backstop for a root built outside dispatch() and never released:
    the guard on tkinter.Tk.__init__ pinned it at birth, so the collection on
    the main thread lowers its count to the pin and no further. It leaks
    (~1.8 MB), it is named in the registry, and the process exits 0 --
    interpreter shutdown included."""
    show = ("dialog()\n    "
            "assert len(ui_dispatch.pinned_records()) == 1, 'the root was not adopted'")
    code = CYCLE_ON_A_WORKER_THREAD.format(
        prelude="from ccsync_companion import ui_dispatch", show=show)
    code += """
records = ui_dispatch.pinned_records()
assert len(records) == 1 and records[0].tkapp is not None, "the pin did not hold"
print("pinned:", records[0].describe())
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "survived" in result.stdout
    assert "pinned: a Tk root (built by thread 'dialog'" in result.stdout
