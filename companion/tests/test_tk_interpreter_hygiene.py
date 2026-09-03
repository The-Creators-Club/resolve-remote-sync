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


# -- every tk.Tk() root is built inside a dispatched function ----------------
#
# bug-hunt-2026-09-03 comp-ui-1. ui_dispatch pins every interpreter at birth
# (install_tk_guard) and frees it in exactly two places: dispatch()'s reclaim
# and release_root(). A root built outside dispatch, on a worker thread that
# then exits, is an orphan for the life of the process (~1.8 MB, and after
# eight of them the module logs an ERROR naming no holder) -- and on macOS it
# is Tk-Aqua touched off the main thread, which is the CR-93 abort shape.
# _install_youtube_cookies and _show_youtube_terms_dialog were both this,
# invisible to the suite because every test of them passes the picker=/confirm=
# seam that mocks the Tk branch away.

# ui_dispatch builds the hidden root the dispatcher itself pumps; it is the one
# site that cannot be inside a dispatched call.
TK_ROOT_ALLOWED = {("ui_dispatch.py", "_make_root")}


def _callee_name(func: ast.expr):
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _called_names(node: ast.AST) -> set:
    return {_callee_name(n.func) for n in ast.walk(node)
            if isinstance(n, ast.Call) and _callee_name(n.func)}


def _dispatch_facts():
    """(names dispatched, ids of lambdas passed to dispatch) over the package.

    A function counts as dispatched when it is handed to `ui_dispatch.dispatch`
    by name, or called from a lambda that is -- plus ONE level further, for the
    `def _build_and_show(): _build_settings_window(...)` shape the package uses
    (and the class whose __init__ builds the root, as popup.show_popup does).
    Deeper than that is a call graph, and a call graph approves everything.
    """
    trees = {p: ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
             for p in sorted(PACKAGE.rglob("*.py"))}
    seeds, lambdas = set(), set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "dispatch"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "ui_dispatch" and node.args):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Lambda):
                lambdas.add(id(arg))
                seeds |= _called_names(arg)
            elif isinstance(arg, (ast.Name, ast.Attribute)):
                seeds.add(arg.attr if isinstance(arg, ast.Attribute) else arg.id)

    defs, classes = {}, set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, []).append(node)
            elif isinstance(node, ast.ClassDef):
                classes.add(node.name)
    approved = set(seeds)
    for name in seeds:
        for fn in defs.get(name, []):
            for called in _called_names(fn):
                approved.add(called)
                if called in classes:
                    approved.add("__init__")
    return trees, approved, lambdas


def _tk_root_sites():
    trees, approved, lambdas = _dispatch_facts()
    sites = []
    for path, tree in trees.items():
        stack: list[str] = []

        def walk(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    stack.append(child.name)
                    walk(child)
                    stack.pop()
                elif isinstance(child, ast.Lambda):
                    stack.append("<dispatched>" if id(child) in lambdas else "<lambda>")
                    walk(child)
                    stack.pop()
                else:
                    if isinstance(child, ast.Call) and _callee_name(child.func) == "Tk":
                        ok = any(f in approved or f == "<dispatched>" for f in stack)
                        if (path.name, stack[-1] if stack else "") in TK_ROOT_ALLOWED:
                            ok = True
                        sites.append((path, child.lineno, list(stack), ok))
                    walk(child)

        walk(tree)
    return sites


def test_the_scan_finds_the_tk_roots_it_is_meant_to_guard():
    assert len(_tk_root_sites()) >= 10


@pytest.mark.parametrize(
    "path,lineno,stack,ok",
    [pytest.param(p, n, s, ok, id=f"{p.name}:{n}") for p, n, s, ok in _tk_root_sites()],
)
def test_every_tk_root_is_built_inside_a_dispatched_function(path, lineno, stack, ok):
    assert ok, (
        f"{path.name}:{lineno} builds a Tk root in {' > '.join(stack) or '<module>'}, "
        f"which nothing passes to ui_dispatch.dispatch. The interpreter is pinned for "
        f"the life of the process (CR-93) and on macOS this is Tk-Aqua off the main "
        f"thread. Wrap the body in a function, call it through ui_dispatch.dispatch, "
        f"and free the root with ui_dispatch.release_root in a finally."
    )
