"""The music ingest report section, its fleet-grid chip and its cancel
command (docs/MUSIC_INGEST_PLAN.md step 3, 2026-08-18).

The b-roll suite next door pins the same contract for the same shape; what
these tests exist to defend is the part that is NOT shared: the two sections
ride ONE report and must land in two sets of columns, because a machine with
no GPU to fight over can be embedding an album and indexing a camera card at
the same time. A single set of columns (or one chip) would have shown whichever
report arrived last and looked perfectly plausible doing it.

Everything B6 wrote down still applies: a diagnostic section is never worth a
422, and a machine that sends a malformed one stays on the grid.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"


def report_headers(editor="jsmith", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def payload(**sections):
    body = {
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.8.1",
        "reported_at": "2026-08-18T10:00:00+00:00",
        "lanes": [
            {"name": "lane_a_video_up", "state": "idle", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None,
             "detail": None},
        ],
    }
    body.update(sections)
    return body


def music_section(**over):
    section = {
        "kind": "music",
        "active": True,
        "batch_uid": "0123456789abcdef0123456789abcdef",
        "state": "running",
        "gate": "",
        "done": 4,
        "failed": 1,
        "total": 12,
        "clip": "03 Slow Burn.wav",
        "percent": 40,
        "tier": "",
        "run_mode": "idle",
        "uploading": True,
        "upload_paused": False,
        "model_download_percent": None,
        "warning": "",
        "at": "2026-08-18T09:59:30+00:00",
    }
    section.update(over)
    return section


def broll_section(**over):
    section = {
        "active": True,
        "batch_uid": "ffffffffffffffffffffffffffffffff",
        "state": "running", "gate": "", "done": 12, "failed": 0, "total": 40,
        "clip": "A001_C003.MP4", "percent": 55, "tier": "good",
        "run_mode": "idle", "uploading": False, "upload_paused": False,
        "model_download_percent": None, "warning": "",
        "at": "2026-08-18T09:59:30+00:00",
    }
    section.update(over)
    return section


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "dash.db")
        yield client, conn
        conn.close()


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


# -- the section reaches the database and the grid --------------------------


def test_a_machine_indexing_music_is_stored_and_chipped(env):
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(music_ingest=music_section()),
                       headers=report_headers())
    assert resp.status_code == 200

    row = dbmod.fetch_music_ingest_map(conn)[("jsmith", "EDIT-PC")]
    assert row["active"] is True
    assert (row["done"], row["total"], row["failed"]) == (4, 12, 1)
    assert row["batch"] == "0123456789abcdef0123456789abcdef"
    assert row["track"] == "03 Slow Burn.wav"

    page = as_admin(client).get("/partials/fleet")
    assert page.status_code == 200
    assert "INDEXING MUSIC: 4/12" in page.text
    assert "03 Slow Burn.wav" in page.text


def test_both_kinds_ride_one_report_into_two_sets_of_columns(env):
    """The reason music has its own section, its own columns and its own chip:
    music needs no GPU, so both can be true at once and neither may overwrite
    the other."""
    client, conn = env
    client.post("/api/v1/report",
                json=payload(broll_ingest=broll_section(),
                             music_ingest=music_section()),
                headers=report_headers())

    broll = dbmod.fetch_broll_ingest_map(conn)[("jsmith", "EDIT-PC")]
    music = dbmod.fetch_music_ingest_map(conn)[("jsmith", "EDIT-PC")]
    assert (broll["done"], broll["total"]) == (12, 40)
    assert (music["done"], music["total"]) == (4, 12)
    assert broll["clip"] == "A001_C003.MP4" and music["track"] == "03 Slow Burn.wav"

    page = as_admin(client).get("/partials/fleet").text
    assert "INDEXING B-ROLL: 12/40" in page
    assert "INDEXING MUSIC: 4/12" in page


def test_a_finished_music_batch_leaves_the_grid(env):
    """The reporter OMITS an empty section, so the chip comes down on absence
    -- not on a 'done' state nobody sends."""
    client, _conn = env
    client.post("/api/v1/report", json=payload(music_ingest=music_section()),
                headers=report_headers())
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    assert "INDEXING MUSIC" not in as_admin(client).get("/partials/fleet").text


def test_a_b_roll_only_report_does_not_clear_the_music_columns(env):
    """Both flags are written on every report; everything else is held. A
    b-roll-only tick from a machine mid-music-batch must not blank the track
    name it is on."""
    client, conn = env
    client.post("/api/v1/report", json=payload(music_ingest=music_section()),
                headers=report_headers())
    client.post("/api/v1/report", json=payload(broll_ingest=broll_section()),
                headers=report_headers())
    row = dbmod.fetch_music_ingest_map(conn)[("jsmith", "EDIT-PC")]
    assert row["active"] is False              # the flag clears...
    assert row["track"] == "03 Slow Burn.wav"  # ...and the detail is kept


def test_the_model_refusal_is_visible_with_nothing_running(env):
    """A build that cannot run the model at all, or a fleet with no release
    feed to fetch it from: the batch the editor asked for is not happening,
    and their own tray must not be the only place that says so."""
    client, _conn = env
    client.post("/api/v1/report", json=payload(music_ingest=music_section(
        active=False, state="blocked", done=0, total=6,
        warning="this fleet has no release feed configured, so the music "
                "indexing model cannot be downloaded",
    )), headers=report_headers())
    page = as_admin(client).get("/partials/fleet").text
    assert "[ MUSIC MODEL ]" in page
    assert "no release feed configured" in page
    assert "INDEXING MUSIC" not in page


def test_the_view_carries_the_music_section_per_machine(env):
    client, conn = env
    client.post("/api/v1/report", json=payload(music_ingest=music_section()),
                headers=report_headers())
    entry = api.build_editors_view(conn)["editors"][0]
    assert entry["music_ingest"]["active"] is True
    assert entry["music_ingest"]["percent"] == 40


# -- nothing in a diagnostic section may take a machine off the grid --------


def test_oversize_strings_are_truncated_not_rejected(env):
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(music_ingest=music_section(
        clip="x" * 4000, warning="w" * 4000, batch_uid="b" * 400, percent=9999,
    )), headers=report_headers())
    assert resp.status_code == 200, "an oversize section must never 422 the report"
    row = dbmod.fetch_music_ingest_map(conn)[("jsmith", "EDIT-PC")]
    assert len(row["track"]) == 255 and len(row["warning"]) == 255
    assert len(row["batch"]) == 32 and row["percent"] == 100


def test_an_unparsable_music_section_is_dropped_and_the_report_still_lands(env):
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(
        music_ingest={"done": "four", "active": True},
        broll_ingest=broll_section(),
    ), headers=report_headers())
    assert resp.status_code == 200
    assert dbmod.fetch_music_ingest_map(conn)[("jsmith", "EDIT-PC")]["active"] is False
    # The b-roll section in the same body is untouched by the bad one.
    assert dbmod.fetch_broll_ingest_map(conn)[("jsmith", "EDIT-PC")]["done"] == 12


def test_unknown_keys_in_the_music_section_are_ignored(env):
    """A newer companion that grew a counter must not 422 its whole report
    against an older dashboard."""
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(music_ingest=music_section(
        windows_embedded=137, provider="CUDAExecutionProvider",
    )), headers=report_headers())
    assert resp.status_code == 200
    assert dbmod.fetch_music_ingest_map(conn)[("jsmith", "EDIT-PC")]["active"] is True


# -- commands.music_ingest --------------------------------------------------


def test_the_reply_carries_the_music_cancel_list(env, monkeypatch):
    client, _conn = env
    seen = {}

    def provider(settings, editor, machine):
        seen["args"] = (editor, machine)
        return ["a" * 32]

    monkeypatch.setattr(api, "music_cancel_requested", provider)
    body = client.post("/api/v1/report", json=payload(music_ingest=music_section()),
                       headers=report_headers()).json()
    assert body["commands"]["music_ingest"] == {"cancel": ["a" * 32]}
    assert seen["args"] == ("jsmith", "EDIT-PC")
    # The halt command is untouched by any of this -- it is the channel the
    # whole fleet depends on.
    assert body["commands"]["halt"]["active"] is False


def test_no_music_cancels_means_no_key(env, monkeypatch):
    client, _conn = env
    monkeypatch.setattr(api, "music_cancel_requested", lambda *a: [])
    body = client.post("/api/v1/report", json=payload(),
                       headers=report_headers()).json()
    assert "music_ingest" not in body["commands"]


def test_the_music_cancel_lookup_answers_nothing_without_a_checkout():
    """Best-effort in every direction: the report reply is the fleet's status
    channel and must not depend on the music tree being importable."""
    class Anything:
        pass

    assert api.music_cancel_requested(Anything(), "jsmith", "EDIT-PC") == []
