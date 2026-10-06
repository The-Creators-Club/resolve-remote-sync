"""The test map has to be true, or a scoped gate skips the test that mattered.

docs/MODULAR_UPDATES.md A.5 (phase M1, 2026-10-06). `tools/test_map.toml`
decides which suites a change runs, and a hand map WILL miss a dependency.
What this file pins:

  * the map and tools/run_all_tests.ps1 name the same 13 suites, and every
    suite is reachable from some area short of the full gate;
  * every path, test glob, smoke file and import root the map names exists,
    and every file in the repo is claimed by an area (so "unmapped means
    full" stays the exception it is meant to be);
  * THE IMPORT-GRAPH AND PATH-LITERAL CHECK: every test that imports a repo
    file, or names one in a string (`REPO / "companion" / "src" / ...`), is
    selected by a change to that file. Its failure message is the row to add;
  * the selector's own rules: unmapped -> full, no base -> full, a VERSION
    line on its own -> neutral and nothing more, the tiers add up the way the
    doc says.

Nothing here depends on git history: CI checks out one commit, so every rule
that needs two commits is exercised on content, not on a real diff.

Run:  cd tools; ..\\dashboard\\.venv\\Scripts\\python.exe -m pytest tests -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import select_suites as ss  # noqa: E402


@pytest.fixture(scope="module")
def tmap():
    return ss.TestMap.load()


@pytest.fixture(scope="module")
def files():
    return ss.repo_files()


# ------------------------------------------------- the map and the runner agree

def _ps1_suites() -> dict[str, str]:
    """name -> repo-relative dir, read out of run_all_tests.ps1 itself."""
    text = (TOOLS / "run_all_tests.ps1").read_text(encoding="utf-8")
    rows = dict(re.findall(r'Name = "([^"]+)";\s*Dir = "\$repo\\([^"]+)"', text))
    out = {name: d.replace("\\", "/") for name, d in rows.items()}
    # The two script rows are written out, not in $Suites.
    for name in re.findall(r'\$results \+= @\{ Name = "(installer[^"]*)"', text):
        out[name] = "installer"
    return out


def test_the_map_and_run_all_tests_name_the_same_suites(tmap):
    ps1 = _ps1_suites()
    assert len(ps1) == 13, f"run_all_tests.ps1 now has {len(ps1)} suites: {sorted(ps1)}"
    assert set(tmap.suites) == set(ps1), (
        "tools/test_map.toml [suites] and run_all_tests.ps1 disagree: "
        f"only in the map {sorted(set(tmap.suites) - set(ps1))}, "
        f"only in the runner {sorted(set(ps1) - set(tmap.suites))}")
    for name, d in ps1.items():
        assert tmap.suites[name].dir == d, name


def test_every_suite_is_reachable_short_of_the_full_gate(tmap):
    """The full gate reaches everything by definition; a suite that ONLY the
    full gate reaches would make every change to its own code a full run."""
    for name in tmap.suites:
        assert any(a.tier != ss.FULL and tmap.selects_whole(a, name) for a in tmap.areas), (
            f"no area short of full selects the {name} suite")


def test_the_dashboard_wide_tier_is_what_the_doc_says(tmap):
    assert set(tmap.tier_suites[ss.DASHBOARD_WIDE]) == {
        "dashboard", "broll/web", "music/web", "ytdl/web", "tools", "server"}


# ------------------------------------------------- everything named exists

def test_every_suite_has_test_files(tmap, files):
    for s in tmap.suites.values():
        assert any(ss.matches(f, s.files) for f in files), f"{s.name}: {s.files} match nothing"


def test_every_area_path_matches_a_file(tmap, files):
    for area in tmap.areas:
        for pattern in area.paths:
            assert any(ss.glob_regex(pattern).match(f) for f in files), (
                f'area "{area.name}": path {pattern!r} matches no file in the repo')


def test_every_area_names_suites_and_tests_that_exist(tmap, files):
    names = {a.name for a in tmap.areas}
    assert len(names) == len(tmap.areas), "two areas share a name"
    for area in tmap.areas:
        for suite in area.suites:
            assert suite in tmap.suites, f'area "{area.name}": no suite {suite!r}'
        for pattern in area.tests:
            hits = [f for f in files if ss.glob_regex(pattern).match(f)]
            assert hits, f'area "{area.name}": test {pattern!r} matches no file'
            for f in hits:
                assert tmap.suite_of(f) is not None, (
                    f'area "{area.name}": {f} is not a test file of any suite')


def test_every_smoke_file_exists_and_belongs_to_a_suite(tmap):
    for f in tmap.smoke:
        assert (REPO / f).is_file(), f"smoke set names a missing file: {f}"
        suite = tmap.suite_of(f)
        assert suite is not None and suite.runner == "pytest", f


def test_the_smoke_set_includes_the_boot_test_and_this_file(tmap):
    """This file is in the smoke set so that a new cross-tree test, or a new
    file no area claims, fails the scoped run it arrives in, not the nightly."""
    assert "dashboard/tests/test_smoke_boot.py" in tmap.smoke
    assert "tools/tests/test_test_map.py" in tmap.smoke


def test_every_import_root_exists(tmap):
    for root in tmap.import_roots:
        assert (REPO / root).is_dir(), root


def test_every_file_in_the_repo_is_claimed_by_an_area(tmap, files):
    unmapped = [f for f in files if tmap.area_for(f) is None]
    assert not unmapped, (
        "these files select the FULL gate because no area in tools/test_map.toml "
        "claims them; give them a row: " + ", ".join(unmapped[:20]))


# ------------------------------------- the import-graph and path-literal check

@pytest.fixture(scope="module")
def violations(tmap, files):
    return ss.audit(tmap, files)


def test_every_test_is_selected_by_what_it_imports_and_reads(violations):
    assert not violations, (
        "a change to these files would NOT run a test that depends on them. "
        "Add the rows (python tools/select_suites.py --audit prints the same):\n  "
        + "\n  ".join(v.fix() for v in violations))


def test_the_check_catches_a_dependency_the_map_misses(tmap, files):
    """Prove the checker can fail: take the companion row's cross-tree file
    away and the dashboard test that reads tray.py by path must be named."""
    target = "dashboard/tests/test_help_doc_matches_the_companion.py"
    areas = [a if a.name not in ("companion", "docs a test reads") else
             ss.Area(name=a.name, tier=a.tier, paths=a.paths, suites=a.suites,
                     tests=tuple(t for t in a.tests if t != target))
             for a in tmap.areas]
    broken = ss.TestMap(suites=tmap.suites, tier_suites=tmap.tier_suites,
                        smoke=tmap.smoke, areas=areas, full_checks=tmap.full_checks,
                        import_roots=tmap.import_roots)
    found = ss.audit(broken, files, only={target})
    by_area = {v.area: v for v in found}
    assert "companion" in by_area, found
    assert by_area["companion"].dep.startswith("companion/src/ccsync_companion/")
    assert target in by_area["companion"].fix()
    assert "docs a test reads" in by_area            # it reads HOW_IT_WORKS.md too


def test_the_scanner_resolves_the_shapes_tests_use(tmap, files):
    idx = ss._Index(tmap, files)
    src = (
        "from pathlib import Path\n"
        "REPO = Path(__file__).resolve().parents[2]\n"
        "DOCS = REPO / 'docs'\n"
        "API = DOCS / 'API.md'\n"
        "TRAY = REPO / 'companion' / 'src' / 'ccsync_companion' / 'tray.py'\n"
        "SRC = Path(__file__).resolve().parents[1] / 'src'\n"
        "BAD = '2.1.234/../..'\n"
        "URL = '/broll/api/search'\n"
        "from ccsync_dashboard import cards_pool\n"
        "def test_it():\n"
        "    API.read_text(); TRAY.read_text(); SRC.exists()\n"
    )
    sc = ss._scan(src)
    here = "dashboard/tests/test_x.py"
    deps = idx.import_deps(here, sc.imports) | idx.path_deps(here, sc.paths)
    assert "docs/API.md" in deps
    assert "companion/src/ccsync_companion/tray.py" in deps
    assert "dashboard/src/ccsync_dashboard/cards_pool.py" in deps
    # DOCS is only ever a prefix, src is a sys.path entry, the traversal
    # fixture and the URL are not repo paths: none of them is "all of docs/",
    # "all of src/" or "all of dashboard/".
    assert "docs/GOTCHAS.md" not in deps
    assert "dashboard/src/ccsync_dashboard/db.py" not in deps
    assert not any(d.startswith("broll/") for d in deps)


# --------------------------------------------------------- the selector's rules

def _plan(tmap, files, *paths):
    return ss.build_plan(tmap, ss.classify(tmap, list(paths), None, None), files)


def test_an_unmapped_path_is_the_full_gate(tmap, files):
    plan = _plan(tmap, files, "nowhere/new_thing.py")
    assert plan.tier == ss.FULL
    assert plan.whole == set(tmap.suites)
    assert {c["name"] for c in plan.checks} == {"licenses", "notices"}
    assert "not in any area" in plan.reason


def test_no_base_is_the_full_gate(tmap):
    plan = ss.plan_for(tmap, [], None, None)
    assert plan.tier == ss.FULL and "no base" in plan.reason


def test_a_base_this_clone_does_not_have_is_the_full_gate(tmap):
    plan = ss.plan_for(tmap, ["0" * 40], None, None)
    assert plan.tier == ss.FULL and "not a commit" in plan.reason


def test_a_docs_change_runs_the_smoke_set_and_the_docs_index(tmap, files):
    plan = _plan(tmap, files, "docs/GOTCHAS.md")
    assert plan.tier == ss.NEUTRAL
    assert not plan.whole
    selected = set().union(*plan.files.values())
    assert set(tmap.smoke) <= selected
    assert "tools/tests/test_docs_index.py" in selected
    assert "onboarding" not in plan.files and "bench" not in plan.files


def test_a_companion_change_skips_the_dashboard_suite(tmap, files):
    plan = _plan(tmap, files, "companion/src/ccsync_companion/fixer.py")
    assert plan.tier == ss.SCOPED
    assert "companion" in plan.whole
    assert "dashboard" not in plan.whole
    assert "dashboard/tests/test_help_doc_matches_the_companion.py" in plan.files["dashboard"]
    assert "dashboard/tests/test_smoke_boot.py" in plan.files["dashboard"]


def test_a_broll_web_change_is_scoped_to_broll(tmap, files):
    plan = _plan(tmap, files, "broll/web/app/routes_api.py")
    assert plan.tier == ss.SCOPED
    assert {"broll/web", "broll/indexer"} <= plan.whole
    assert "dashboard/tests/test_broll_mount.py" in plan.files["dashboard"]
    assert "companion" not in plan.whole


def test_a_core_change_is_dashboard_wide_and_not_the_companion(tmap, files):
    plan = _plan(tmap, files, "dashboard/src/ccsync_dashboard/collector.py")
    assert plan.tier == ss.DASHBOARD_WIDE
    assert set(tmap.tier_suites[ss.DASHBOARD_WIDE]) <= plan.whole
    assert "companion" not in plan.whole and "onboarding" not in plan.whole


@pytest.mark.parametrize("path", [
    "dashboard/src/ccsync_dashboard/db.py",
    "dashboard/templates/shell.html",
    "companion/requirements.lock",
    "dashboard/tests/conftest.py",
    "docs/legal/EULA.md",
    "tools/test_map.toml",
    "ytdl/web/ytdlweb/ytdlp_nightly.py",
])
def test_what_everything_leans_on_is_the_full_gate(tmap, files, path):
    assert _plan(tmap, files, path).tier == ss.FULL


def test_the_highest_tier_wins_and_the_selections_add_up(tmap, files):
    plan = _plan(tmap, files, "docs/GOTCHAS.md", "companion/src/ccsync_companion/fixer.py",
                 "music/web/musicweb/main.py")
    assert plan.tier == ss.SCOPED
    assert {"companion", "music/web"} <= plan.whole
    assert "tools/tests/test_docs_index.py" in plan.files["tools"]


def test_a_script_suite_is_run_whole_or_not_at_all(tmap, files):
    plan = _plan(tmap, files, "installer/windows_bootstrap.ps1")
    assert {"installer", "installer/macos"} <= plan.whole
    assert "installer" not in plan.files


def test_the_json_plan_is_relative_to_each_suite_dir(tmap, files):
    out = ss.to_json(tmap, _plan(tmap, files, "docs/GOTCHAS.md"))
    tools = next(s for s in out["suites"] if s["name"] == "tools")
    assert tools["whole"] is False
    assert "tests/test_docs_index.py" in tools["tests"]
    assert "onboarding" in out["not_run"]


# ------------------------------------------------------- the VERSION-line rule

OLD_INIT = '# 0.7.72: a change log comment\nVERSION = "0.7.72"\n'


@pytest.mark.parametrize("new, neutral", [
    ('# 0.7.72: a change log comment\nVERSION = "0.7.73"\n', True),
    ('# 0.7.72: a change log comment\r\nVERSION = "0.7.73"\r\n', True),   # CRLF copy
    ('# 0.7.73: and a new note\nVERSION = "0.7.73"\n', False),
    ('# 0.7.72: a change log comment\nVERSION = "0.7.73"\nimport os\n', False),
    (OLD_INIT, True),
    (None, False),
])
def test_only_the_version_line_is_neutral(new, neutral):
    assert ss.only_version_lines(OLD_INIT, new) is neutral


def test_pyproject_version_line_shape():
    old = '[project]\nname = "x"\nversion = "0.7.72"\ndependencies = ["a"]\n'
    assert ss.only_version_lines(old, old.replace("0.7.72", "0.7.73"))
    assert not ss.only_version_lines(old, old.replace('["a"]', '["a", "b"]'))


def test_a_version_file_is_neutral_only_when_proved(tmap, files):
    """With --files and no base there is nothing to compare against, so the
    version-stamp row cannot apply: pyproject is a dependency list again."""
    plan = _plan(tmap, files, "dashboard/pyproject.toml")
    assert plan.tier == ss.FULL
    changes = [ss.Change("dashboard/pyproject.toml", "version stamp", ss.NEUTRAL)]
    neutral = ss.build_plan(tmap, changes, files)
    assert neutral.tier == ss.NEUTRAL
    # ...and a version bump still runs the two pins that the copies agree.
    selected = set().union(*neutral.files.values())
    assert {"dashboard/tests/test_hardening.py", "companion/tests/test_config.py"} <= selected


def test_the_version_stamp_row_comes_first(tmap):
    """First match wins: below `dependencies` it could never match pyproject."""
    assert tmap.areas[0].version_line_only


# ---------------------------------------------------------------------- globs

@pytest.mark.parametrize("pattern, path, hit", [
    ("docs/**", "docs/legal/EULA.md", True),
    ("**/conftest.py", "conftest.py", True),
    ("**/conftest.py", "dashboard/tests/conftest.py", True),
    ("dashboard/tests/test_cards_*.py", "dashboard/tests/test_cards_pool.py", True),
    ("dashboard/tests/test_cards_*.py", "dashboard/tests/sub/test_cards_x.py", False),
    ("*/README.md", "dashboard/README.md", True),
    ("*/README.md", "broll/eval/README.md", False),
])
def test_glob_semantics(pattern, path, hit):
    assert bool(ss.glob_regex(pattern).match(path)) is hit
