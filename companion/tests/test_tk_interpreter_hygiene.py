"""Every Tk variable in the package must name its master (MAC-6).

A tkinter Variable binds to the Tcl interpreter of its master, and a
masterless one silently takes `tkinter._default_root`. That was harmless for
the year the companion was Windows-only: the first (and only) Tk root of a
session WAS the dialog's own root.

On macOS it is not. ui_dispatch creates a hidden root on the main thread
before anything else, so the default root is a DIFFERENT interpreter from the
dialog being built. The Entry writes the typed text into the dialog's
interpreter and `var.get()` reads the hidden one, which is always empty:

    sign-in with both fields filled in -> "username and password are both
    required", forever, with nothing in the log.

The fixer's destination comboboxes fail the same way and would file media at
the tree root. There is no runtime symptom to catch here -- an empty string
is a legal value -- so the guard is on the source. `tkinter.ttk.Style()` has
the identical hazard; theme.style_combobox/style_progressbar take a `master`
for that reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ccsync_companion"

# tkinter.Variable subclasses: Variable(master=None, value=None, name=None)
VARIABLE_TYPES = {"StringVar", "IntVar", "BooleanVar", "DoubleVar", "Variable"}


def _variable_constructions() -> list[tuple[Path, ast.Call]]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else None)
            if name in VARIABLE_TYPES:
                found.append((path, node))
    return found


def test_the_scan_finds_the_variables_it_is_meant_to_guard():
    """A guard that silently matches nothing guards nothing."""
    assert len(_variable_constructions()) >= 5


@pytest.mark.parametrize(
    "path,node",
    [pytest.param(p, n, id=f"{p.name}:{n.lineno}") for p, n in _variable_constructions()],
)
def test_every_tk_variable_names_its_master(path: Path, node: ast.Call):
    has_master = any(kw.arg == "master" for kw in node.keywords) or bool(node.args)
    assert has_master, (
        f"{path.name}:{node.lineno} builds a Tk variable with no master, so on macOS it "
        f"binds to ui_dispatch's hidden root instead of this dialog's and always reads "
        f"back empty. Pass master=<this dialog's root>."
    )
