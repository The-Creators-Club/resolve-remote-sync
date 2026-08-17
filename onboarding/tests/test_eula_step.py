"""Unit tests for the wizard's licence page -- the logic half in steps.py
(2026-08-17, docs/COMMERCIAL_READINESS.md item 3). Headless: nothing here
imports tkinter or touches onboard.py, per this suite's convention that every
real decision lives in steps.py precisely so it can be tested without a
display.

Nothing here may touch the developer's own ~/.ccsync either -- every test
passes an explicit `home=tmp_path` or `path=`, which is what steps.py's
`home` seam (managed_syncthing_dirs_macos, build_cleanup_plan_macos) exists
for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import steps

REPO_ROOT = Path(steps.__file__).resolve().parent.parent
CANONICAL_EULA = REPO_ROOT / "docs" / "legal" / "EULA.md"
BUNDLED_EULA = REPO_ROOT / "onboarding" / "assets" / "EULA.md"


# -- the bundled copy must not drift ---------------------------------------


def test_bundled_eula_is_byte_identical_to_the_canonical_document():
    """onboard.exe ships its own copy (PyInstaller can only bundle files it
    is told about, and the wizard has no repo). Two copies is two chances to
    edit the wrong one -- and the editor accepting a document that is not the
    one counsel approved is the entire failure mode this feature exists to
    prevent."""
    assert BUNDLED_EULA.is_file(), "onboarding/assets/EULA.md is missing"
    assert BUNDLED_EULA.read_bytes() == CANONICAL_EULA.read_bytes(), (
        f"{BUNDLED_EULA} has drifted from {CANONICAL_EULA} -- copy the "
        "canonical document over it verbatim"
    )


def test_find_eula_asset_prefers_the_bundled_copy():
    found = steps.find_eula_asset()
    assert found is not None
    assert found.name == "EULA.md"


def test_the_wizard_has_a_version_and_text():
    assert steps.EULA_VERSION, "the bundled EULA has lost its EULA-VERSION marker"
    assert "End User Licence Agreement" in steps.EULA_TEXT


def test_version_marker_matches_the_canonical_document():
    canonical = steps.parse_eula_version(CANONICAL_EULA.read_text(encoding="utf-8"))
    assert canonical
    assert steps.EULA_VERSION == canonical


@pytest.mark.parametrize("text,expected", [
    ("<!-- EULA-VERSION: 1.0 -->", "1.0"),
    ("<!--EULA-VERSION:2.13-->", "2.13"),
    ("nothing here", ""),
    ("", ""),
])
def test_parse_eula_version(text, expected):
    assert steps.parse_eula_version(text) == expected


def test_find_eula_asset_returns_none_when_there_is_no_document(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, "EULA_ASSET_NAME", "NOT_A_REAL_DOCUMENT.md")
    assert steps.find_eula_asset() is None
    assert steps.eula_text() == ""


# -- numeric version comparison --------------------------------------------


def test_versions_compare_numerically_not_lexically():
    assert steps.eula_version_tuple("1.10") == (1, 10)
    assert steps.eula_version_at_least("1.10", "1.9") is True
    assert steps.eula_version_at_least("1.9", "1.10") is False


def test_version_comparison_pads_the_shorter_side():
    assert steps.eula_version_at_least("1.0", "1.0.0") is True
    assert steps.eula_version_at_least("1.0.1", "1.0") is True
    assert steps.eula_version_at_least("1.0", "1.0.1") is False


def test_version_tuple_tolerates_junk():
    assert steps.eula_version_tuple(None) == (0,)
    assert steps.eula_version_tuple("beta") == (0,)
    assert steps.eula_version_tuple("1.0-draft") == (1, 0)


# -- the acceptance record --------------------------------------------------


def test_acceptance_path_is_the_file_the_companion_reads(tmp_path):
    path = steps.eula_acceptance_path(home=tmp_path)
    assert path == tmp_path / ".ccsync" / "eula_accepted.json"


def test_nothing_accepted_yet(tmp_path):
    assert steps.read_eula_acceptance(home=tmp_path) is None
    assert steps.eula_accepted(home=tmp_path) is False


def test_record_then_accepted(tmp_path):
    written = steps.record_eula_acceptance(home=tmp_path)
    assert written == tmp_path / ".ccsync" / "eula_accepted.json"
    assert steps.eula_accepted(home=tmp_path) is True


def test_record_schema(tmp_path):
    path = steps.record_eula_acceptance(home=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"version", "accepted_at", "eula_sha256"}
    assert data["version"] == steps.EULA_VERSION
    assert data["accepted_at"].endswith("+00:00"), "accepted_at must be ISO-8601 UTC"
    assert len(data["eula_sha256"]) == 64


def test_record_is_atomic_and_leaves_no_temp_file(tmp_path):
    steps.record_eula_acceptance(home=tmp_path)
    steps.record_eula_acceptance(home=tmp_path)
    ccsync = tmp_path / ".ccsync"
    assert sorted(p.name for p in ccsync.iterdir()) == ["eula_accepted.json"]


def test_an_older_acceptance_is_not_enough(tmp_path):
    steps.record_eula_acceptance("0.9", home=tmp_path)
    assert steps.eula_accepted(home=tmp_path, version="1.0") is False


def test_an_equal_or_newer_acceptance_is_enough(tmp_path):
    steps.record_eula_acceptance("1.0", home=tmp_path)
    assert steps.eula_accepted(home=tmp_path, version="1.0") is True
    steps.record_eula_acceptance("99.0", home=tmp_path)
    assert steps.eula_accepted(home=tmp_path, version="1.0") is True


def test_corrupt_json_reads_as_no_acceptance(tmp_path):
    path = tmp_path / "eula_accepted.json"
    path.write_text("{ not json", encoding="utf-8")
    assert steps.read_eula_acceptance(path) is None
    assert steps.eula_accepted(path) is False


def test_a_bom_prefixed_record_still_reads(tmp_path):
    """PowerShell Set-Content writes UTF-8 WITH a BOM; identity.json was
    fixed for exactly this and this file is its neighbour."""
    path = tmp_path / "eula_accepted.json"
    payload = json.dumps({"version": steps.EULA_VERSION, "accepted_at": "x"})
    path.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    assert steps.read_eula_acceptance(path) is not None
    assert steps.eula_accepted(path) is True


def test_no_bundled_document_means_ask_again(tmp_path, monkeypatch):
    """The wizard has a person in front of it: with no document to show it
    cannot claim consent. (The COMPANION fails open on the same absence --
    a packaging fault must not stop the fleet syncing -- which is the one
    place the two halves deliberately differ.)"""
    steps.record_eula_acceptance(home=tmp_path)
    assert steps.eula_accepted(home=tmp_path, version="") is False


# -- the two halves must agree ---------------------------------------------


def test_the_companion_accepts_the_record_the_wizard_writes(tmp_path):
    """The load-bearing cross-component pin: the wizard writes this file
    before the companion is even installed, and the companion gates its sync
    lanes on it. A schema change in either half strands every new editor with
    lanes that never start."""
    from ccsync_companion import eula as companion_eula

    assert companion_eula.EULA_VERSION == steps.EULA_VERSION
    path = steps.record_eula_acceptance(home=tmp_path)
    assert companion_eula.acceptance_ok(path) is True
    assert companion_eula.read_acceptance(path) == json.loads(
        path.read_text(encoding="utf-8"))


def test_the_two_bundled_copies_are_the_same_document():
    companion_copy = REPO_ROOT / "companion" / "src" / "ccsync_companion" / "assets" / "EULA.md"
    assert companion_copy.read_bytes() == BUNDLED_EULA.read_bytes()
