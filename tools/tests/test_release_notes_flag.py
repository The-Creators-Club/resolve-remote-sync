"""APP-16 (usability sweep 2026-09-04): the release note the editor reads.

A build is offered as a version number and nothing else, so the rational move
is to ignore the dialog. These pin the three ends of the one-line "what
changed":

  * `sign_release.py --notes` puts it in the QUERY (which is what
    build_editor_package.ps1 appends to its PUT) and never in the signed
    record -- a field an older companion's canonicaliser does not know is a
    record that companion REFUSES, with no over-the-air recovery (REL-7),
  * `CCSYNC_RELEASE_NOTES` is the environment route, because ship.ps1 does
    not own the argv of the script that makes the PUT,
  * `publish_latest.py --notes` reaches publish_feed.py, and `ship.ps1
    -Notes` reaches both.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import release_key as release_key_mod  # noqa: E402
import sign_release  # noqa: E402
from ccsync_companion import release_pubkey  # noqa: E402


@pytest.fixture
def key(tmp_path, monkeypatch):
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(tmp_path / "release.key"))
    assert release_key_mod.main(["new"]) == 0


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path / "ccsync-companion.exe"
    path.write_bytes(b"MZ" + b"pretend-exe" * 100)
    return path


def _sign(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert sign_release.main(argv) == 0
    return json.loads(buf.getvalue())


def _base_argv(artifact, version="0.9.67"):
    return ["--artifact", str(artifact), "--kind", "companion",
            "--platform", "windows", "--version", version,
            "--min-version", "0.0.0"]


def test_notes_ride_the_query_and_not_the_signature(key, artifact):
    note = "proxy downloads resume by themselves"
    out = _sign(_base_argv(artifact) + ["--notes", note])
    assert out["notes"] == note
    assert parse_qs(out["query"].lstrip("&"))["notes"] == [note]
    # NOT in the record, so the canonical bytes are what every companion in
    # the field already hashes.
    assert "notes" not in release_pubkey.record_fields("companion", out)
    plain = _sign(_base_argv(artifact))
    signed_fields = {k: v for k, v in out.items()
                     if k not in ("signature", "pubkey_id", "query", "notes",
                                  "git_sha", "git_dirty")}
    assert {k: v for k, v in plain.items()
            if k in signed_fields} == signed_fields
    assert out["signature"] == plain["signature"]


def test_the_environment_route_is_read_when_no_flag_is_passed(key, artifact, monkeypatch):
    monkeypatch.setenv("CCSYNC_RELEASE_NOTES", "  two   words\nhere  ")
    out = _sign(_base_argv(artifact))
    # Folded to one line: it lands in a dialog, not a changelog.
    assert out["notes"] == "two words here"


def test_no_note_leaves_the_query_exactly_as_it_was(key, artifact, monkeypatch):
    monkeypatch.delenv("CCSYNC_RELEASE_NOTES", raising=False)
    out = _sign(_base_argv(artifact))
    assert out["notes"] == ""
    assert "notes=" not in out["query"]


def test_publish_latest_passes_notes_through_to_the_feed():
    source = (TOOLS / "publish_latest.py").read_text(encoding="utf-8")
    assert '"--notes"' in source
    assert 'ap.add_argument("--notes"' in source


def test_ship_carries_notes_to_both_publish_paths():
    ship = (TOOLS / "ship.ps1").read_text(encoding="utf-8")
    assert "[string]$Notes" in ship
    # The PUT into this dashboard, through sign_release's environment route...
    assert "$env:CCSYNC_RELEASE_NOTES" in ship
    # ...and the vendor feed, as a real flag.
    assert '$feedArgs += @("--notes"' in ship
