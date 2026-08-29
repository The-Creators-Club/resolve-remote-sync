"""The CR-93 abort itself, with a real Tk, in a subprocess.

Every other test in this suite talks to a fake root, because conftest forbids
a real `tkinter.Tk()` in-process and because the failure being demonstrated
here is not an exception: a Tcl interpreter freed on a thread that did not
create it calls Tcl_Panic, i.e. abort(). The process dies mid-instruction --
no traceback, no `finally`, no pytest report. So the only honest way to test
it is to run it somewhere we are allowed to lose: a child process, whose EXIT
CODE is the assertion.

What it pins:

  the disease -- a widget kept past its window, dropped by another thread,
                 kills the process ("Tcl_AsyncDelete: async handler deleted by
                 the wrong thread"). If this test ever starts passing as
                 "survived", the platform changed and the guard below can be
                 revisited;
  the cure    -- the same shape with ui_dispatch.release_root() in it exits 0,
                 including through interpreter shutdown, which is its own
                 abort (the pin in _immortalise, measured 2026-08-29).

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
    pretend to have found every holder), and the process lives anyway."""
    teardown = ("from ccsync_companion import ui_dispatch\n    "
                "ui_dispatch.release_root(root, 'the test window')")
    result = _run(LEAK_ON_A_WORKER_THREAD.format(teardown=teardown))
    assert result.returncode == 0, (
        f"the guarded teardown still aborted: {result.stderr[-2000:]}")
    assert "survived" in result.stdout


def test_a_clean_window_needs_no_parking_and_still_exits_cleanly(tk_runs):
    """The ordinary path: nothing held, nothing parked, and the interpreter
    is freed on the thread that made it rather than pinned for the session."""
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
    assert ui_dispatch.parked_roots() == []


thread = threading.Thread(target=build, name="dialog")
thread.start()
thread.join()
print("survived")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "survived" in result.stdout
