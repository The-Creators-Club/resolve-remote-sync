#!/usr/bin/env python3
"""Which tests does this change need? Prints the gate plan and why.

docs/MODULAR_UPDATES.md Part A (phase M1, 2026-10-06). Alex asked for a
small change to get a small gate: a companion fix should not wait twenty
minutes for the dashboard's 5,973 tests. This reads ONE map,
`tools/test_map.toml` (data, not a chain of ifs), and answers with one of four
tiers, smallest to largest:

    neutral         nothing but the smoke set
    scoped          the changed area's own suites and test files, plus smoke
    dashboard-wide  the dashboard suite and every suite that imports
                    ccsync_dashboard, plus smoke
    full            all 13 suites, check_licenses.py and gen_notices.py --check

    python tools/select_suites.py --base 97d4366
    python tools/select_suites.py --base <live> --base <last-full-green>
    python tools/select_suites.py --base 97d4366 --head 0c37831     # a range, no working tree
    python tools/select_suites.py --files broll/web/app/routes_api.py
    python tools/select_suites.py --base 97d4366 --json             # machine-readable
    python tools/select_suites.py --base 97d4366 --json-out p.json  # both (run_all_tests.ps1)
    python tools/select_suites.py --audit                           # check the map against the tests

FAIL CLOSED, EVERYWHERE. A path no area claims selects the full gate (an
unmapped file is the map's bug, never a reason to skip tests). No base, a base
this clone does not have, or a git that will not answer: the full gate. A
VERSION bump is neutral only when the VERSION line is the WHOLE change to that
file, compared against the base -- with --files and no --base there is nothing
to compare against, so it is not neutral.

THE BASE (A.4). Not HEAD~1: a scoped run is only safe if everything since the
last PROVEN-WHOLE state is inside its diff, so the base is the older of (1) the
commit live on the studio dashboard and (2) the last commit that passed the
full gate. Pass both as --base; this takes their merge base with HEAD, which
for two commits on one line is the older one. Neither is recorded anywhere
yet: (1) arrives with M0 as `code.commit` on /api/v1/health
(`dashboard_update.health_code_block`), and (2) with M2's CI record. Until
then the caller supplies them, e.g. from PowerShell:

    $live = (Invoke-RestMethod "$env:DASH_URL/api/v1/health" -Headers $h).code.commit
    tools\\run_all_tests.ps1 -Changed -Base $live,<last full-green sha>

and a caller that has neither gets the full gate, which is the right answer.

The diff is the NET difference between the base and the working tree
(`git diff <base>`) plus untracked files, because a ship can run on a dirty
tree with -AllowDirty. With --head it is base..head and the working tree is
ignored (the shape CI's per-push plan will use).

Stdlib only, like the rest of tools/ that judges something: it must run under
any interpreter on any machine, before any venv exists.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import posixpath
import re
import subprocess
import sys
import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAP_PATH = REPO / "tools" / "test_map.toml"

NEUTRAL, SCOPED, DASHBOARD_WIDE, FULL = "neutral", "scoped", "dashboard-wide", "full"
TIERS = (NEUTRAL, SCOPED, DASHBOARD_WIDE, FULL)
_RANK = {t: i for i, t in enumerate(TIERS)}

# "The VERSION line alone" (A.1, the version stamp row). Every dashboard and
# companion commit bumps one of these, and if that counted as a change to
# __init__.py / pyproject.toml / config.py nothing would ever be scoped
# (MODULAR_UPDATES.md section 2). The shapes in the tree, 2026-10-06:
#   VERSION = "0.7.73"   (ccsync_dashboard/__init__.py, ccsync_companion/config.py)
#   version = "0.7.73"   (every pyproject.toml)
_VERSION_LINE = re.compile(
    r"""^\s*(?:VERSION|version|__version__)\s*=\s*(["'])[^"']*\1\s*(?:\#.*)?$""")


# --------------------------------------------------------------------- globs

_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A repo-relative glob as a regex: `**` spans directories, `*` and `?`
    do not. fnmatch's `*` crosses `/`, which would make `dashboard/tests/test_cards_*.py`
    match a file in a subdirectory nobody meant."""
    rx = _GLOB_CACHE.get(pattern)
    if rx is not None:
        return rx
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    rx = re.compile("".join(out) + r"\Z")
    _GLOB_CACHE[pattern] = rx
    return rx


def matches(path: str, patterns) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


# ----------------------------------------------------------------------- map

@dataclass(frozen=True)
class Suite:
    name: str
    dir: str
    files: tuple[str, ...]          # globs naming this suite's test files
    runner: str                     # "pytest" or "script" (installer rows: whole only)


@dataclass(frozen=True)
class Area:
    name: str
    tier: str
    paths: tuple[str, ...]
    suites: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    version_line_only: bool = False
    why: str = ""


@dataclass
class TestMap:
    __test__ = False                # a map of tests, not a pytest class
    suites: dict[str, Suite]
    tier_suites: dict[str, tuple[str, ...]]
    smoke: tuple[str, ...]
    areas: list[Area]
    full_checks: list[dict]
    import_roots: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = MAP_PATH) -> "TestMap":
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        suites = {}
        for name, s in data["suites"].items():
            suites[name] = Suite(name=name, dir=s["dir"], files=tuple(s["files"]),
                                 runner=s.get("runner", "pytest"))
        tiers = {t: tuple(v) for t, v in data.get("tiers", {}).items()}
        tiers.setdefault(NEUTRAL, ())
        tiers.setdefault(SCOPED, ())
        tiers[FULL] = tuple(suites)
        areas = []
        for a in data["area"]:
            if a["tier"] not in TIERS:
                raise ValueError(f"area {a['name']!r}: unknown tier {a['tier']!r}")
            areas.append(Area(name=a["name"], tier=a["tier"], paths=tuple(a["paths"]),
                              suites=tuple(a.get("suites", ())),
                              tests=tuple(a.get("tests", ())),
                              version_line_only=bool(a.get("version_line_only", False)),
                              why=a.get("why", "")))
        return cls(suites=suites, tier_suites=tiers, smoke=tuple(data["smoke"]["tests"]),
                   areas=areas, full_checks=list(data.get("full_check", [])),
                   import_roots=tuple(data.get("audit", {}).get("import_roots", ())))

    def area_for(self, path: str, version_only: bool = False) -> Area | None:
        """First match in file order wins. A version_line_only area is skipped
        unless the caller has proved the diff is the VERSION line alone."""
        for area in self.areas:
            if area.version_line_only and not version_only:
                continue
            if matches(path, area.paths):
                return area
        return None

    def wants_version_check(self, path: str) -> bool:
        return any(a.version_line_only and matches(path, a.paths) for a in self.areas)

    def suite_of(self, test_path: str) -> Suite | None:
        for s in self.suites.values():
            if matches(test_path, s.files):
                return s
        return None

    def selects(self, area: Area | None, test_path: str) -> bool:
        """Does a change in `area` run this test file? None = unmapped = full."""
        if area is None or area.tier == FULL:
            return True
        suite = self.suite_of(test_path)
        if suite is not None and (suite.name in self.tier_suites.get(area.tier, ())
                                  or suite.name in area.suites):
            return True
        return matches(test_path, area.tests) or matches(test_path, self.smoke)

    def selects_whole(self, area: Area | None, suite: str) -> bool:
        if area is None or area.tier == FULL:
            return True
        return suite in self.tier_suites.get(area.tier, ()) or suite in area.suites


# ----------------------------------------------------------------------- git

class GitError(RuntimeError):
    pass


def git(*args: str, binary: bool = False):
    try:
        proc = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                              check=False)
    except OSError as e:
        raise GitError(f"git did not run: {e}") from e
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip()
                       or f"git {' '.join(args)} exited {proc.returncode}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def _z(out: str) -> list[str]:
    return [p for p in out.split("\0") if p]


def repo_files() -> list[str]:
    """Tracked plus untracked-not-ignored, as they stand on disk. Untracked
    counts because a new test file is a test before anyone commits it."""
    names = _z(git("ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    return sorted({n for n in names if (REPO / n).is_file()})


def resolve_base(bases: list[str], head: str | None) -> str:
    """-> the merge base of every --base and HEAD (or --head): "the older of"."""
    shas = []
    for ref in bases:
        try:
            shas.append(git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip())
        except GitError:
            raise GitError(f"base {ref!r} is not a commit in this clone "
                           "(fetch it, or the answer is the full gate)") from None
    tip = head or "HEAD"
    return git("merge-base", "--octopus", tip, *shas).strip()


def changed_paths(base: str, head: str | None) -> list[str]:
    if head:
        return sorted(set(_z(git("diff", "--name-only", "--no-renames", "-z", base, head))))
    names = set(_z(git("diff", "--name-only", "--no-renames", "-z", base)))
    names |= set(_z(git("ls-files", "-z", "--others", "--exclude-standard")))
    return sorted(names)


def _content(rev: str | None, path: str) -> str | None:
    if rev is None:
        p = REPO / path
        return p.read_bytes().decode("utf-8", "replace") if p.is_file() else None
    try:
        return git("show", f"{rev}:{path}", binary=True).decode("utf-8", "replace")
    except GitError:
        return None


def version_line_only(path: str, base: str, head: str | None) -> bool:
    """Is the change to this file the VERSION line and nothing else?"""
    return only_version_lines(_content(base, path), _content(head, path))


def only_version_lines(old: str | None, new: str | None) -> bool:
    if old is None or new is None:
        return False                     # added or deleted: a real change
    changed = [line[1:] for line in difflib.unified_diff(
                   old.splitlines(), new.splitlines(), n=0, lineterm="")
               if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    return all(_VERSION_LINE.match(line) for line in changed)


# ---------------------------------------------------------------------- plan

@dataclass
class Change:
    path: str
    area: str | None
    tier: str
    note: str = ""


@dataclass
class Plan:
    tier: str
    base: str | None
    head: str | None
    changes: list[Change] = field(default_factory=list)
    whole: set[str] = field(default_factory=set)
    files: dict[str, set[str]] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    reason: str = ""

    def suites_in_order(self, tmap: TestMap) -> list[str]:
        return [s for s in tmap.suites if s in self.whole or self.files.get(s)]


def _full(tmap: TestMap, reason: str, base=None, head=None, changes=()) -> Plan:
    return Plan(tier=FULL, base=base, head=head, changes=list(changes),
                whole=set(tmap.suites), checks=list(tmap.full_checks), reason=reason)


def build_plan(tmap: TestMap, changes: list[Change], files: list[str],
               base: str | None = None, head: str | None = None) -> Plan:
    if any(c.tier == FULL for c in changes):
        first = next(c for c in changes if c.tier == FULL)
        why = (f"{first.path} is not in any area of tools/test_map.toml"
               if first.area is None else f"{first.path} -> {first.area}")
        return _full(tmap, why, base, head, changes)

    plan = Plan(tier=NEUTRAL, base=base, head=head, changes=changes)
    patterns: list[str] = list(tmap.smoke)
    for c in changes:
        if _RANK[c.tier] > _RANK[plan.tier]:
            plan.tier = c.tier
            plan.reason = f"{c.path} -> {c.area}"
        area = next(a for a in tmap.areas if a.name == c.area)
        plan.whole.update(tmap.tier_suites.get(area.tier, ()))
        plan.whole.update(area.suites)
        patterns.extend(area.tests)
    if not changes:
        plan.reason = "nothing changed since the base"
    elif plan.tier == NEUTRAL:
        plan.reason = "only " + ", ".join(sorted({c.area for c in changes if c.area}))
    for f in files:
        if matches(f, patterns):
            suite = tmap.suite_of(f)
            if suite is None or suite.name in plan.whole:
                continue
            if suite.runner != "pytest":
                plan.whole.add(suite.name)      # a script row runs whole or not at all
            else:
                plan.files.setdefault(suite.name, set()).add(f)
    for name in plan.whole:
        plan.files.pop(name, None)
    return plan


def classify(tmap: TestMap, paths: list[str], base: str | None,
             head: str | None) -> list[Change]:
    out = []
    for p in paths:
        vonly = False
        if base is not None and tmap.wants_version_check(p):
            try:
                vonly = version_line_only(p, base, head)
            except GitError:
                vonly = False
        area = tmap.area_for(p, version_only=vonly)
        if area is None:
            out.append(Change(p, None, FULL, "UNMAPPED: add it to an area"))
        else:
            out.append(Change(p, area.name, area.tier,
                              "the VERSION line alone" if area.version_line_only else ""))
    return out


def plan_for(tmap: TestMap, bases: list[str], head: str | None,
             explicit: list[str] | None) -> Plan:
    try:
        files = repo_files()
    except GitError as e:
        return _full(tmap, f"git could not list the repo ({e})")
    if explicit is not None and not bases:
        return build_plan(tmap, classify(tmap, explicit, None, None), files)
    if not bases:
        return _full(tmap, "no base given: pass --base <live commit> and/or "
                           "--base <last full-green commit> (MODULAR_UPDATES.md A.4)")
    try:
        base = resolve_base(bases, head)
        paths = explicit if explicit is not None else changed_paths(base, head)
    except GitError as e:
        return _full(tmap, str(e), head=head)
    return build_plan(tmap, classify(tmap, paths, base, head), files, base, head)


# -------------------------------------------------------------------- output

def to_json(tmap: TestMap, plan: Plan) -> dict:
    suites = []
    for name in plan.suites_in_order(tmap):
        s = tmap.suites[name]
        whole = name in plan.whole
        tests = [] if whole else sorted(posixpath.relpath(f, s.dir) for f in plan.files[name])
        suites.append({"name": name, "whole": whole, "tests": tests})
    return {
        "tier": plan.tier, "reason": plan.reason, "base": plan.base, "head": plan.head,
        "suites": suites,
        "not_run": [n for n in tmap.suites if n not in plan.suites_in_order(tmap)],
        "checks": plan.checks,
        "changes": [{"path": c.path, "area": c.area, "tier": c.tier, "note": c.note}
                    for c in plan.changes],
    }


def render(tmap: TestMap, plan: Plan) -> str:
    lines = [f"gate plan: {plan.tier.upper()}  ({plan.reason})"]
    if plan.base:
        what = f"{plan.base[:10]}..{plan.head}" if plan.head else \
               f"{plan.base[:10]} -> working tree (committed, uncommitted and untracked)"
        lines.append(f"  diff: {what}")
    if plan.changes:
        lines.append(f"  changed: {len(plan.changes)} file(s)")
        width = min(64, max(len(c.path) for c in plan.changes))
        for c in plan.changes:
            label = f"{c.area or 'NO AREA'} ({c.tier})"
            note = f" - {c.note}" if c.note else ""
            lines.append(f"    {c.path:<{width}}  {label}{note}")
    lines.append("  runs:")
    for name in plan.suites_in_order(tmap):
        if name in plan.whole:
            lines.append(f"    {name:<16} whole suite")
        else:
            fs = sorted(plan.files[name])
            lines.append(f"    {name:<16} {len(fs)} file(s)")
            for f in fs:
                lines.append(f"        {f}")
    for chk in plan.checks:
        lines.append(f"    {chk['name']:<16} {' '.join(chk['argv'])}")
    skipped = [n for n in tmap.suites if n not in plan.suites_in_order(tmap)]
    if skipped:
        lines.append("  not run: " + ", ".join(skipped))
    return "\n".join(lines)


# --------------------------------------------------------------------- audit
#
# A.5: a hand map will miss a dependency. Walk every test file's imports with
# ast, and the repo paths it names in string literals (`REPO / "companion" /
# "src" / ...`, `parents[1] / "static" / "app.js"`), resolve both to repo
# files, and report every test that a change in one of those files would NOT
# select. The message names the row to change. It over-approximates on
# purpose: a dependency it invents costs a line in the map, a dependency it
# misses costs a scoped run that skipped the one test that would have failed.

@dataclass(frozen=True)
class Violation:
    test: str
    dep: str
    area: str
    whole_suite: str = ""           # set for a conftest: the area must take the suite

    def fix(self) -> str:
        if self.whole_suite:
            return (f'area "{self.area}": add "{self.whole_suite}" to suites '
                    f"({self.test} reads {self.dep})")
        return f'area "{self.area}": add "{self.test}" to tests (it reads {self.dep})'


class _Scan(ast.NodeVisitor):
    """Imports and path-shaped string literals of one file."""

    def __init__(self) -> None:
        self.imports: list[tuple[str, int, tuple[str, ...]]] = []   # (module, level, names)
        self.paths: list[str] = []
        self.assigned: dict[str, list[str]] = {}    # NAME = <path chain>
        self._assign_nodes: dict[str, ast.AST] = {}
        self.head_uses: dict[str, int] = {}
        self.loads: dict[str, int] = {}

    # -- imports
    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.imports.append((a.name, 0, ()))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append((node.module or "", node.level,
                             tuple(a.name for a in node.names)))

    # -- path literals
    @staticmethod
    def _str(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("Path", "PurePath", "PurePosixPath")
                and node.args and all(_Scan._str(a) is not None for a in node.args)):
            return "/".join(_Scan._str(a) for a in node.args)
        return None

    def _chain(self, node: ast.BinOp) -> tuple[ast.AST, list[str]]:
        parts: list[ast.AST] = []
        cur: ast.AST = node
        while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
            parts.append(cur.right)
            cur = cur.left
        parts.append(cur)
        parts.reverse()
        head, segs = parts[0], []
        start = 1
        if self._str(head) is not None:
            segs.append(self._str(head))
        for p in parts[start:]:
            s = self._str(p)
            if s is None:
                break
            segs.append(s)
        for p in parts[1:]:
            if self._str(p) is None:
                self.visit(p)
        return head, segs

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, ast.Div):
            self.generic_visit(node)
            return
        head, segs = self._chain(node)
        if isinstance(head, ast.Name):
            self.head_uses[head.id] = self.head_uses.get(head.id, 0) + 1
            segs = self.assigned.get(head.id, []) + segs
        elif self._str(head) is None:
            self.visit(head)
        if segs:
            self.paths.append("/".join(segs))

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        strs = [self._str(a) for a in node.args]
        if name == "import_module" and strs and strs[0]:
            self.imports.append((strs[0], 0, ()))
        elif (name in ("joinpath", "join") and any(strs)
              and not (isinstance(f, ast.Attribute) and self._str(f.value) is not None)):
            # os.path.join(REPO, "a", "b") / ROOT.joinpath("a", "b"); never
            # "sep".join(...), which is a string method, not a path.
            run = []
            for i, s in enumerate(strs):
                if s is None and i == 0:
                    continue
                if s is None:
                    break
                run.append(s)
            if run:
                self.paths.append("/".join(run))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and ("/" in node.value or "\\" in node.value):
            self.paths.append(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loads[node.id] = self.loads.get(node.id, 0) + 1


def _scan(source: str) -> _Scan:
    with warnings.catch_warnings():
        # A test's own "\s" in a non-raw string is its problem, not ours.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    sc = _Scan()
    # NAME = REPO / "docs" at module level: remember the segments, so that
    # `NAME / "API.md"` later resolves to docs/API.md and not to all of docs/.
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Div)):
            probe = _Scan()
            probe.assigned = sc.assigned
            head, segs = probe._chain(node.value)
            if isinstance(head, ast.Name):
                segs = sc.assigned.get(head.id, []) + segs
            if segs:
                sc.assigned[node.targets[0].id] = segs
                sc._assign_nodes[node.targets[0].id] = node.value
    sc.visit(tree)
    # A NAME only ever used as the head of a longer chain is a prefix, not a
    # dependency on the whole directory; one also used any other way
    # (`DOCS.glob(...)`, `os.listdir(DOCS)`) is.
    prefixes_only = {"/".join(segs) for name, segs in sc.assigned.items()
                     if sc.loads.get(name, 0) == 0}
    sc.paths = [p for p in sc.paths if p not in prefixes_only]
    return sc


class _Index:
    def __init__(self, tmap: TestMap, files: list[str]) -> None:
        self.tmap = tmap
        self.files = set(files)
        self.dirs: dict[str, list[str]] = {}
        for f in files:
            d = posixpath.dirname(f)
            while d:
                self.dirs.setdefault(d, []).append(f)
                d = posixpath.dirname(d)
        self.roots = set(tmap.import_roots)

    def module(self, dotted: str, roots: list[str]) -> str | None:
        rel = dotted.replace(".", "/")
        for r in roots:
            base = f"{r}/{rel}" if r else rel
            for cand in (base + ".py", base + "/__init__.py"):
                if cand in self.files:
                    return cand
        return None

    def import_deps(self, path: str, imports) -> set[str]:
        here = posixpath.dirname(path)
        suite = self.tmap.suite_of(path)
        roots = [here]
        if suite is not None:
            roots.append(suite.dir)
        roots += list(self.tmap.import_roots)
        out = set()
        for mod, level, names in imports:
            if level:
                pkg = here
                for _ in range(level - 1):
                    pkg = posixpath.dirname(pkg)
                cands = [f"{mod}.{n}" if mod else n for n in names] + ([mod] if mod else [])
                for c in cands:
                    hit = self.module(c, [pkg])
                    if hit:
                        out.add(hit)
                        break
                continue
            hit = None
            for c in [f"{mod}.{n}" for n in names] + [mod]:
                hit = self.module(c, roots)
                if hit:
                    out.add(hit)
                    if c == mod:
                        break
            if not names and hit is None:
                parts = mod.split(".")
                while parts and hit is None:
                    parts.pop()
                    hit = self.module(".".join(parts), roots) if parts else None
                if hit:
                    out.add(hit)
        return out

    def path_deps(self, path: str, literals: list[str]) -> set[str]:
        out = set()
        for raw in literals:
            s = raw.replace("\\", "/")
            if not s or "\n" in s or "://" in s or ":" in s or s.startswith("/"):
                continue
            segs = []
            for seg in s.split("/"):
                if any(ch in seg for ch in "*?["):
                    break
                segs.append(seg)
            s = "/".join(segs).strip("/")
            # "../companion/src" is a relative path; "2.1.234/../.." is a
            # traversal fixture, and resolving it would make the test depend
            # on whatever directory it happens to land on.
            rest = s
            while rest.startswith("../"):
                rest = rest[3:]
            if not rest or rest in (".", "..") or ".." in rest.split("/"):
                continue
            anc = posixpath.dirname(path)
            while True:
                cand = posixpath.normpath(f"{anc}/{s}" if anc else s)
                if cand.startswith(".."):
                    break
                if cand in self.files:
                    out.add(cand)
                    break
                if cand in self.dirs:
                    # A directory that is an import root is a sys.path entry
                    # (`parents[1] / "src"`), and a PACKAGE directory is a
                    # tree being located or copied (the bundle tests): what
                    # the test then imports is the import graph's to find,
                    # not "every file in it". Any other directory -- static/,
                    # templates/, docs/ -- is globbed and read file by file.
                    if f"{cand}/__init__.py" in self.files:
                        out.add(f"{cand}/__init__.py")
                    elif cand not in self.roots:
                        out.update(self.dirs[cand])
                    break
                if not anc:
                    break
                anc = posixpath.dirname(anc)
        return out


def audit(tmap: TestMap, files: list[str] | None = None,
          only: set[str] | None = None) -> list[Violation]:
    """Every (test, area) pair where a change in the area would not run a test
    that imports or names a file in it. `only` limits which test files are
    judged (every file is still read, for the helpers they import)."""
    files = repo_files() if files is None else files
    idx = _Index(tmap, files)
    py_suites = [s for s in tmap.suites.values() if s.runner == "pytest"]
    test_dirs = sorted({f"{s.dir}/tests/" for s in py_suites})
    in_tests = [f for f in files if f.endswith(".py") and f.startswith(tuple(test_dirs))]

    direct: dict[str, set[str]] = {}
    for f in in_tests:
        try:
            sc = _scan((REPO / f).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        deps = idx.import_deps(f, sc.imports) | idx.path_deps(f, sc.paths)
        deps.discard(f)
        direct[f] = deps

    def closure(f: str) -> set[str]:
        """A helper module in a tests dir is part of the test that imports it."""
        seen, todo, out = {f}, [f], set()
        while todo:
            cur = todo.pop()
            for d in direct.get(cur, ()):
                out.add(d)
                if d in direct and d not in seen and not posixpath.basename(d).startswith("test_"):
                    seen.add(d)
                    todo.append(d)
        return out

    found: dict[tuple, Violation] = {}
    for f in in_tests:
        suite = tmap.suite_of(f)
        is_conftest = posixpath.basename(f) == "conftest.py"
        if not is_conftest and suite is None:
            continue                        # a helper: checked through its importers
        if only is not None and f not in only:
            continue
        if is_conftest:
            owner = next((s for s in py_suites if f.startswith(f"{s.dir}/tests/")), None)
            if owner is None:
                continue
        for dep in sorted(closure(f)):
            area = tmap.area_for(dep)
            if is_conftest:
                if not tmap.selects_whole(area, owner.name):
                    key = (f, area.name)
                    found.setdefault(key, Violation(f, dep, area.name, owner.name))
            elif not tmap.selects(area, f):
                key = (f, area.name)
                found.setdefault(key, Violation(f, dep, area.name))
    return sorted(found.values(), key=lambda v: (v.area, v.test))


# ----------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", action="append", default=[], metavar="REF",
                    help="the live commit and/or the last full-green commit; "
                         "repeatable, the older one wins")
    ap.add_argument("--head", metavar="REF",
                    help="diff base..REF instead of base..working tree")
    ap.add_argument("--files", nargs="+", metavar="PATH",
                    help="classify these paths instead of asking git what changed")
    ap.add_argument("--json", action="store_true", help="machine-readable plan")
    ap.add_argument("--json-out", type=Path, metavar="FILE",
                    help="print the readable plan AND write the JSON one here "
                         "(run_all_tests.ps1 -Changed: one git snapshot, two readers)")
    ap.add_argument("--audit", action="store_true",
                    help="check the map against every test's imports and path literals")
    ap.add_argument("--map", type=Path, default=MAP_PATH, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    try:
        tmap = TestMap.load(args.map)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
        print(f"select_suites: cannot read {args.map}: {e}", file=sys.stderr)
        return 2

    if args.audit:
        found = audit(tmap)
        for v in found:
            print(v.fix())
        print(f"{len(found)} missing selection(s)" if found else "the map covers every "
              "import and path literal the tests have")
        return 1 if found else 0

    explicit = None
    if args.files:
        explicit = []
        for p in args.files:
            q = Path(p)
            if q.is_absolute():
                try:
                    q = q.resolve().relative_to(REPO)
                except ValueError:
                    pass
            explicit.append(q.as_posix().removeprefix("./"))
    plan = plan_for(tmap, args.base, args.head, explicit)
    if args.json_out:
        args.json_out.write_text(json.dumps(to_json(tmap, plan), indent=1) + "\n",
                                 encoding="utf-8")
    if args.json:
        json.dump(to_json(tmap, plan), sys.stdout, indent=1)
        sys.stdout.write("\n")
    else:
        print(render(tmap, plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
