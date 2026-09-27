"""Test setup: make `steps` (this package) and `ccsync_companion` (the
companion app's package, imported for identity.py/config.py reuse -- see
steps.py's module docstring) importable without requiring either package to
be pip-installed."""

from __future__ import annotations

import sys
from pathlib import Path

ONBOARDING_DIR = Path(__file__).resolve().parent.parent
COMPANION_SRC = ONBOARDING_DIR.parent / "companion" / "src"

for path in (str(ONBOARDING_DIR), str(COMPANION_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)


# CR-354 (2026-09-27): THE FIRST Tk INTERPRETER MUST OUTLIVE THE SESSION ON A
# MAC. The CI macOS job segfaulted in this suite on every run for days, in a
# different test each time (always one of the wizard tests that build a real
# OnboardWizard). The native stack, from the runner's crash report: AppKit
# (UIIntelligenceSupport "simulating" opening the app menu) asked Tk's
# process-wide TKApplication to validate a menu item, and TKApplication called
# Tcl_FindCommand on the interpreter it was SET UP WITH - the first one this
# process created - which a finished test's wizard had long since freed.
# Every wizard here builds its own tk.Tk() and the fixtures destroy it; the
# wizard in the field builds exactly one per process and never trips this.
# So on darwin the session creates the first interpreter itself and holds it
# to the end: whatever TKApplication remembers is never freed. Its WINDOW is
# destroyed at once - only the interpreter's memory has to live. A second
# live Tk app in the process hung clipboard_get (the COPY LOG test) for the
# whole job timeout on the first attempt. Reproduced on the macos-latest
# runner (the w2 file alone crashed on its first run) and gone with this in
# place (branch debug/mac-onboarding-segv, 2026-09-27).
if sys.platform == "darwin":
    import pytest

    _FIRST_TK = []

    @pytest.fixture(scope="session", autouse=True)
    def _pin_the_first_tk_interpreter():
        try:
            import tkinter
            root = tkinter.Tk()
            _FIRST_TK.append(root)   # the reference is the pin
            root.destroy()           # the window is not
        except Exception:  # noqa: BLE001 - no Tk here: the Tk tests skip themselves
            pass
        yield
