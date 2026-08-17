"""Unit tests for eula.py -- the licence-acceptance record the onboarding
wizard writes and the sync lanes are gated on (2026-08-17,
docs/COMMERCIAL_READINESS.md item 3).

conftest's _isolate_ccsync_home repoints config_mod.CONFIG_DIR at a temp dir,
so acceptance_path() here can never see (or write) the developer's real
~/.ccsync/eula_accepted.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import eula

REPO_ROOT = Path(eula.__file__).resolve().parents[3]
CANONICAL_EULA = REPO_ROOT / "docs" / "legal" / "EULA.md"


# -- the bundled copy must not drift from the document counsel signs off ----


def test_bundled_eula_is_byte_identical_to_the_canonical_document():
    """The companion ships its own copy of docs/legal/EULA.md so a frozen
    build has one without the repo. Two copies is two chances to edit the
    wrong one, and an editor accepting a stale document is exactly the
    failure this whole feature exists to prevent."""
    bundled = eula.asset_path()
    assert bundled is not None, "assets/EULA.md is missing from the source tree"
    assert bundled.read_bytes() == CANONICAL_EULA.read_bytes(), (
        f"{bundled} has drifted from {CANONICAL_EULA} -- copy the canonical "
        "document over it verbatim"
    )


def test_bundled_version_matches_the_canonical_document_marker():
    canonical_version = eula.parse_version(CANONICAL_EULA.read_text(encoding="utf-8"))
    assert canonical_version, "docs/legal/EULA.md has lost its EULA-VERSION marker"
    assert eula.EULA_VERSION == canonical_version


def test_bundled_text_is_the_document():
    assert "End User Licence Agreement" in eula.bundled_text()


# -- version marker parsing -------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("<!-- EULA-VERSION: 1.0 -->", "1.0"),
    ("<!--EULA-VERSION:2.13-->", "2.13"),
    ("prose\n<!--   EULA-VERSION:   1.0.1   -->\nmore", "1.0.1"),
    ("no marker here", ""),
    ("", ""),
])
def test_parse_version(text, expected):
    assert eula.parse_version(text) == expected


# -- numeric version comparison --------------------------------------------


def test_version_tuple_is_numeric_not_lexical():
    # The whole point: as strings, "1.10" sorts BEFORE "1.9".
    assert eula.version_tuple("1.10") == (1, 10)
    assert eula.version_tuple("1.9") == (1, 9)
    assert eula.version_at_least("1.10", "1.9") is True
    assert eula.version_at_least("1.9", "1.10") is False


def test_version_at_least_pads_the_shorter_side():
    assert eula.version_at_least("1.0", "1.0.0") is True
    assert eula.version_at_least("1.0.0", "1.0") is True
    assert eula.version_at_least("1.0.1", "1.0") is True
    assert eula.version_at_least("1.0", "1.0.1") is False


def test_version_tuple_tolerates_junk():
    assert eula.version_tuple(None) == (0,)
    assert eula.version_tuple("") == (0,)
    assert eula.version_tuple("beta") == (0,)
    assert eula.version_tuple("1.0-draft") == (1, 0)


# -- the acceptance record --------------------------------------------------


def test_acceptance_path_is_under_the_ccsync_config_dir():
    assert eula.acceptance_path() == config_mod.CONFIG_DIR / "eula_accepted.json"
    assert eula.acceptance_path().name == "eula_accepted.json"


def test_no_record_blocks():
    # conftest's _eula_already_accepted writes one for every test; this is
    # the machine nobody ever ran the wizard on.
    eula.acceptance_path().unlink(missing_ok=True)
    assert eula.acceptance_ok() is False
    problem = eula.acceptance_problem()
    assert problem and "has not been accepted" in problem


def test_record_acceptance_then_ok():
    eula.acceptance_path().unlink(missing_ok=True)
    eula.record_acceptance()
    assert eula.acceptance_ok() is True
    assert eula.acceptance_problem() is None


def test_record_acceptance_schema(tmp_path):
    path = tmp_path / "eula_accepted.json"
    eula.record_acceptance(path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"version", "accepted_at", "eula_sha256"}
    assert data["version"] == eula.EULA_VERSION
    assert data["accepted_at"].endswith("+00:00"), "accepted_at must be ISO-8601 UTC"
    assert len(data["eula_sha256"]) == 64
    assert data["eula_sha256"] == eula._text_sha256(eula.bundled_text())


def test_record_acceptance_creates_the_config_dir(tmp_path):
    path = tmp_path / "nested" / "deeper" / "eula_accepted.json"
    eula.record_acceptance(path=path)
    assert path.is_file()


def test_record_acceptance_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "eula_accepted.json"
    eula.record_acceptance(path=path)
    eula.record_acceptance(path=path)  # overwrite an existing record
    assert not list(tmp_path.glob("*.tmp")), "the temp file must be replaced, not left behind"
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == eula.EULA_VERSION


def test_an_older_record_blocks(tmp_path):
    path = tmp_path / "eula_accepted.json"
    eula.record_acceptance("0.9", path=path)
    assert eula.acceptance_ok(path) is False
    problem = eula.acceptance_problem(path)
    assert problem and "has been updated" in problem
    assert eula.EULA_VERSION in problem and "0.9" in problem


def test_an_equal_record_passes(tmp_path):
    path = tmp_path / "eula_accepted.json"
    eula.record_acceptance(eula.EULA_VERSION, path=path)
    assert eula.acceptance_ok(path) is True


def test_a_newer_record_passes(tmp_path):
    """A machine that accepted a LATER document (downgraded companion, or a
    build published before the marker bump reached it) must not be pushed
    back through the wizard."""
    path = tmp_path / "eula_accepted.json"
    eula.record_acceptance("99.0", path=path)
    assert eula.acceptance_ok(path) is True


def test_corrupt_json_blocks_but_does_not_raise(tmp_path):
    path = tmp_path / "eula_accepted.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert eula.read_acceptance(path) is None
    assert eula.acceptance_ok(path) is False


def test_a_json_list_is_not_a_record(tmp_path):
    path = tmp_path / "eula_accepted.json"
    path.write_text("[]", encoding="utf-8")
    assert eula.read_acceptance(path) is None
    assert eula.acceptance_ok(path) is False


def test_a_record_with_no_version_blocks(tmp_path):
    path = tmp_path / "eula_accepted.json"
    path.write_text(json.dumps({"accepted_at": "2026-08-17T00:00:00+00:00"}), encoding="utf-8")
    problem = eula.acceptance_problem(path)
    assert problem and "unreadable" in problem


def test_a_bom_prefixed_record_still_reads(tmp_path):
    """PowerShell Set-Content and several editors write UTF-8 WITH a BOM;
    identity.load_identity was fixed for exactly this and the acceptance
    file lives in the same directory, written by the same installer."""
    path = tmp_path / "eula_accepted.json"
    payload = json.dumps({"version": eula.EULA_VERSION, "accepted_at": "x", "eula_sha256": ""})
    path.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    assert eula.read_acceptance(path) is not None
    assert eula.acceptance_ok(path) is True


def test_unknown_keys_are_ignored(tmp_path):
    """Either half of the schema may add a key; the other must not care."""
    path = tmp_path / "eula_accepted.json"
    path.write_text(json.dumps({
        "version": eula.EULA_VERSION,
        "accepted_at": "2026-08-17T00:00:00+00:00",
        "eula_sha256": "0" * 64,
        "accepted_by": "someone",
        "installer_version": "1.0.29",
    }), encoding="utf-8")
    assert eula.acceptance_ok(path) is True


# -- fail open when the document itself is missing -------------------------


def test_a_missing_bundled_document_fails_open(tmp_path, monkeypatch, caplog):
    """A forgotten build.spec datas line must not stop every editor in the
    fleet syncing -- the standing "fail absent, not fatal" rule. There is no
    acceptance record here at all and it STILL passes."""
    monkeypatch.setattr(eula, "EULA_VERSION", "")
    with caplog.at_level("WARNING", logger="ccsync.eula"):
        assert eula.acceptance_ok(tmp_path / "nothing.json") is True
    assert any("packaging fault" in r.getMessage() for r in caplog.records)


def test_asset_path_is_none_when_the_asset_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(eula, "EULA_ASSET_NAME", "NOT_THERE.md")
    monkeypatch.setattr(eula.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert eula.asset_path() is None
    assert eula.bundled_text() == ""
    assert eula.parse_version(eula.bundled_text()) == eula.UNKNOWN_VERSION


def test_build_spec_ships_the_eula():
    """The frozen build must actually contain the document it gates on.

    build.spec lists assets file by file rather than collecting the directory
    (deliberately -- see its comment), so a new asset is silently absent from
    every shipped build until someone adds a line. acceptance_ok() fails OPEN
    on a missing document, which means the omission has no symptom at all: the
    gate just never fires. This is the only thing that would notice.
    """
    from pathlib import Path

    spec = (Path(__file__).resolve().parent.parent / "build.spec").read_text(
        encoding="utf-8")
    assert "src/ccsync_companion/assets/EULA.md" in spec
