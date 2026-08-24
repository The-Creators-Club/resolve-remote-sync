"""Cross-project folder links: validation (SHARED_FOLDERS_PLAN.md §2.2).

Every refusal is exercised against a real tmp_path tree because the marker
is a plain JSON file on a share every editor can write -- links.py is the
only thing between a hand-edited `includes` and a companion running rclone
over it.
"""
from __future__ import annotations

import os

import pytest

from ccsync_dashboard import links, provision


BORROWER = "2026/FF5/Elections"
LENDER = "2026/FF5/Civil Defence"
SUB = "Interviewees/Aha Chu"


def mark(root, rel, slug=None):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    provision.write_marker(d, slug or provision.slugify(rel))
    return d


@pytest.fixture
def tree(tmp_path):
    mark(tmp_path, BORROWER)
    lender = mark(tmp_path, LENDER)
    (lender / SUB).mkdir(parents=True)
    return tmp_path


def resolve(tree, path, borrower=BORROWER):
    return links.resolve_include(tree, borrower, path)


def test_ok_include(tree):
    res = resolve(tree, f"Projects/{LENDER}/{SUB}")
    assert res.status == "ok"
    assert res.lender_rel == LENDER
    assert res.sub_rel == SUB
    assert res.lender_slug == provision.slugify(LENDER)
    assert res.declared == f"Projects/{LENDER}/{SUB}"


def test_backslashes_and_trailing_slash_normalise(tree):
    res = resolve(tree, f"Projects\\{LENDER.replace('/', chr(92))}\\{SUB.replace('/', chr(92))}\\")
    assert res.status == "ok"
    assert res.declared == f"Projects/{LENDER}/{SUB}"


def test_unicode_nfd_spelling_matches_nfc_tree(tmp_path):
    # A Mac-made zip can hand over NFD; the tree serves NFC. The declared
    # path must land on the same folder either way.
    import unicodedata
    mark(tmp_path, BORROWER)
    lender = mark(tmp_path, LENDER)
    name = "caf\u00e9"                       # NFC
    (lender / "Interviewees" / name).mkdir(parents=True)
    nfd = unicodedata.normalize("NFD", f"Projects/{LENDER}/Interviewees/{name}")
    res = resolve(tmp_path, nfd)
    assert res.status == "ok"
    assert res.sub_rel == f"Interviewees/{name}"


@pytest.mark.parametrize("bad, why", [
    ("", "empty"),
    ("   ", "empty"),
    ("/Projects/2026/FF5/Civil Defence/Interviewees", "absolute"),
    ("Projects/../etc/passwd", "dot segment"),
    ("Projects/2026/./x", "dot segment"),
    ("Projects/2026//x", "empty segment"),
    ("Projects/2026/.hidden/x", "leading dot"),
    ("Projects/2026/a\x01b/x", "control char"),
    ("Projects/C:/Users/x", "drive letter"),
    ("Projects/2026/" + "x" * 300 + "/y", "over 255 bytes"),
])
def test_refuses_malformed_paths(tree, bad, why):
    assert resolve(tree, bad).status == "invalid", why


def test_refuses_outside_projects(tree):
    res = resolve(tree, "Assets/B-roll Archive/Creators_Club")
    assert res.status == "invalid"
    assert "inside a project" in res.detail


def test_refuses_bare_project(tree):
    res = resolve(tree, f"Projects/{LENDER}")
    assert res.status == "invalid"
    assert "tick both projects" in res.detail


def test_refuses_projects_root_child_that_is_a_project(tmp_path):
    # A project directly under Projects/: still a whole project, len rule
    # first, marker rule as backstop.
    mark(tmp_path, BORROWER)
    mark(tmp_path, "OneOffs")
    res = resolve(tmp_path, "Projects/OneOffs")
    assert res.status == "invalid"


def test_refuses_proxy_segment_anywhere(tree):
    for path in (f"Projects/{LENDER}/{SUB}/Proxy",
                 f"Projects/{LENDER}/{SUB}/proxy/deep",
                 f"Projects/{LENDER}/PROXY/{SUB}"):
        res = resolve(tree, path)
        assert res.status == "invalid"
        assert "Proxy" in res.detail


def test_refuses_folder_not_inside_any_project(tree):
    (tree / "2026/FF5/loose-folder").mkdir(parents=True)
    res = resolve(tree, "Projects/2026/FF5/loose-folder")
    assert res.status == "invalid"
    assert "not inside a project" in res.detail


def test_refuses_folder_inside_the_borrower_itself(tree):
    (tree / BORROWER / "Interviewees/Someone").mkdir(parents=True)
    res = resolve(tree, f"Projects/{BORROWER}/Interviewees/Someone")
    assert res.status == "invalid"
    assert "this project already" in res.detail


def test_refuses_subtree_containing_a_project(tree):
    # A marker below the include: sharing that subtree would smuggle a whole
    # project through a lane it is not provisioned for.
    mark(tree, f"{LENDER}/Interviewees/Nested Project")
    res = resolve(tree, f"Projects/{LENDER}/Interviewees")
    assert res.status == "invalid"
    assert "contains a project" in res.detail


def test_missing_folder_keeps_lender_identity(tree):
    res = resolve(tree, f"Projects/{LENDER}/Interviewees/Not There Yet")
    assert res.status == "missing"
    assert res.lender_rel == LENDER
    assert res.lender_slug == provision.slugify(LENDER)
    assert res.sub_rel == "Interviewees/Not There Yet"


def test_symlink_escape_refused(tree, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    link_path = tree / LENDER / "Interviewees" / "escape"
    try:
        os.symlink(str(outside), str(link_path), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege on this platform")
    res = resolve(tree, f"Projects/{LENDER}/Interviewees/escape")
    assert res.status == "invalid"
    assert "escapes" in res.detail


# ---------------------------------------------------------------- parsing

def test_parse_includes_shorthand_and_object():
    paths, bad = links.parse_includes([
        "Projects/a/b/c",
        {"path": "Projects/d/e/f", "note": "why", "added_by": "footage-sorter"},
        {"note": "no path"},
        7,
    ])
    assert paths == ["Projects/a/b/c", "Projects/d/e/f"]
    assert bad == 2


def test_parse_includes_non_list():
    assert links.parse_includes("Projects/a/b/c") == ([], 1)
    assert links.parse_includes(None) == ([], 0)


def test_marker_dedupes_equal_and_nested_includes(tree):
    (tree / LENDER / SUB / "Deeper").mkdir(parents=True)
    results = links.resolve_marker_includes(tree, BORROWER, [
        f"Projects/{LENDER}/{SUB}/Deeper",      # below the next one: dropped
        f"Projects/{LENDER}/{SUB}",
        f"Projects/{LENDER}/{SUB}",             # equal: dropped
        f"Projects\\{LENDER.replace('/', chr(92))}\\{SUB.replace('/', chr(92))}",  # same after normalise
    ])
    assert [r.declared for r in results] == [f"Projects/{LENDER}/{SUB}"]
    assert results[0].status == "ok"


def test_marker_caps_includes(tree):
    raw = [f"Projects/{LENDER}/{SUB}/n{i}" for i in range(links.MAX_INCLUDES + 3)]
    results = links.resolve_marker_includes(tree, BORROWER, raw)
    assert len(results) == links.MAX_INCLUDES + 3
    over = [r for r in results if "too many" in r.detail]
    assert len(over) == 3
    assert all(r.status == "invalid" for r in over)


def test_marker_without_includes_yields_no_rows(tree):
    assert links.resolve_marker_includes(tree, BORROWER, None) == []
