"""CR-317 (2026-09-24): "N clips Resolve cannot find" was false.

Seen live on ruskin's DESKTOP-LQQ41TC: "57 clips Resolve cannot find" over a
timeline that played perfectly. Up to companion 0.9.75 `missing_clips` is
every clip whose ORIGINAL is absent, and a remote rig by design holds only
proxies. From 0.9.76 the companion leaves out a clip playing its proxy. The
wire did not change, so the label is chosen by the reporting build: each
wording must be true of the list that build sends.
"""
from __future__ import annotations

import html

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, health
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-value-cr317-1234567890ab"
TOKEN = "sekrit-report-token-cr317-0924"


@pytest.mark.parametrize("version, proxy_aware", [
    ("0.9.75", False),
    ("0.9.70", False),
    ("0.9.76", True),
    ("0.9.77", True),
    ("0.10.0", True),          # two-digit minor: a string compare gets this wrong
    ("0.9.76+dirty", True),
    ("0.9.76-rc1", True),
    ("", False),
    (None, False),
    ("garbage", False),
])
def test_the_label_follows_what_the_build_puts_in_the_list(version, proxy_aware):
    label = health.missing_clips_label(version)
    help_text = health.missing_clips_help(version)
    if proxy_aware:
        assert label == "with neither the original nor a proxy on this computer"
        assert "not listed" in help_text
    else:
        # True of the old list AND the new one, which is why an unreadable
        # version gets it.
        assert label == "whose original is not on this computer"
        assert "playing their proxy" in help_text
    assert "cannot find" not in label


def test_no_em_dash_in_the_new_copy():
    for text in (health.MISSING_CLIPS_LABEL_ORIGINAL_ONLY,
                 health.MISSING_CLIPS_LABEL_NOTHING_TO_PLAY,
                 health.MISSING_CLIPS_HELP_ORIGINAL_ONLY,
                 health.MISSING_CLIPS_HELP_NOTHING_TO_PLAY):
        assert "\u2014" not in text


def test_the_details_note_uses_the_same_words():
    """The count beside [ DETAILS ] (health.detail_notes) and the group
    inside it must say the same thing."""
    row = {"companion_version": "0.9.75",
           "resolve_detail": {"missing_clips": [{"name": "a", "path": "P:/a"}] * 3}}
    assert "3 clips whose original is not on this computer" in health.detail_notes(row)
    row["companion_version"] = "0.9.76"
    assert ("3 clips with neither the original nor a proxy on this computer"
            in health.detail_notes(row))


@pytest.fixture
def fleet(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              report_token=TOKEN, admin_users=frozenset({"owen"})))
    with TestClient(app) as client:
        def report(version):
            body = {"editor_name": "owen", "machine": "EDIT-PC",
                    "companion_version": version, "lanes": [],
                    "reported_at": dbmod.utcnow_iso(),
                    "sync_guard": {"resolve_health": {
                        "connected": True,
                        "missing_clips": [
                            {"name": "A004C001.braw",
                             "path": "P:/Projects/RRF/A004C001.braw"},
                            {"name": "A005C002.braw",
                             "path": "P:/Projects/RRF/A005C002.braw"},
                        ]}}}
            resp = client.post("/api/v1/report", json=body, headers={
                "X-CCSync-Token": TOKEN,
                "X-CCSync-Identity": auth.make_identity_token(SECRET, "owen")})
            assert resp.status_code == 200, resp.text

        def page():
            client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
            resp = client.get("/partials/fleet")
            assert resp.status_code == 200, resp.text
            return " ".join(html.unescape(resp.text).split())

        yield report, page


def test_an_old_companion_is_labelled_by_the_original_only(fleet):
    report, page = fleet
    report("0.9.75")
    line = page()
    assert "2 clips whose original is not on this computer" in line
    assert "A clip playing its proxy is fine" in line
    assert "Resolve cannot find" not in line


def test_a_proxy_aware_companion_is_labelled_as_having_nothing_to_play(fleet):
    report, page = fleet
    report("0.9.76")
    line = page()
    assert "2 clips with neither the original nor a proxy on this computer" in line
    assert "Clips playing their proxy are not listed here" in line
    assert "Resolve cannot find" not in line
