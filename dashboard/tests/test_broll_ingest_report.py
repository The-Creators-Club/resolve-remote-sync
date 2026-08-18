"""The b-roll ingest report section, the fleet-grid chip and the cancel
command (BROLL_INGEST_PLAN.md PR-I, 2026-08-18).

Also the standing bug this PR fixes in passing: ReportIn never declared
`proxy_coverage` or `youtube_import`, so pydantic's extra='ignore' dropped
both on every tick and no dashboard has ever known how many of an editor's
clips still have no proxy.

The rule every test here defends is the same one B6 wrote down: a diagnostic
section is never worth a 422. A machine that sends a malformed, oversize or
future-shaped section must stay on the fleet grid with its lanes intact.
"""

from __future__ import annotations

import sqlite3
import sys
import types

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
             "transferring": 0, "last_error": None, "last_sync": None, "detail": None},
        ],
    }
    body.update(sections)
    return body


def ingest_section(**over):
    section = {
        "active": True,
        "batch_uid": "0123456789abcdef0123456789abcdef",
        "state": "running",
        "gate": "",
        "done": 12,
        "failed": 1,
        "total": 40,
        "clip": "A001_C003_0817XY.MP4",
        "percent": 55,
        "tier": "good",
        "run_mode": "idle",
        "uploading": True,
        "upload_paused": False,
        "model_download_percent": None,
        "warning": "",
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


def test_an_indexing_machine_is_stored_and_chipped(env):
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(broll_ingest=ingest_section()),
                       headers=report_headers())
    assert resp.status_code == 200

    row = dbmod.fetch_broll_ingest_map(conn)[("jsmith", "EDIT-PC")]
    assert row["active"] is True
    assert (row["done"], row["total"], row["failed"]) == (12, 40, 1)
    assert row["batch"] == "0123456789abcdef0123456789abcdef"
    assert row["clip"] == "A001_C003_0817XY.MP4"

    page = as_admin(client).get("/partials/fleet")
    assert page.status_code == 200
    assert "INDEXING B-ROLL: 12/40" in page.text
    # The tooltip carries what an admin needs before they go and ask: which
    # batch, which clip, which model tier.
    assert "0123456" in page.text and "A001_C003_0817XY.MP4" in page.text
    assert "good model" in page.text


def test_a_finished_batch_leaves_the_grid(env):
    """The companion's reporter OMITS an empty section, so the chip has to
    come down on absence -- not on a 'done' state nobody sends."""
    client, _conn = env
    client.post("/api/v1/report", json=payload(broll_ingest=ingest_section()),
                headers=report_headers())
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    assert "INDEXING B-ROLL" not in as_admin(client).get("/partials/fleet").text


def test_the_vram_refusal_is_visible_even_though_nothing_is_running(env):
    """Owner review (c): a batch that cannot run because the GPU is too small
    must be visible somewhere other than that editor's own tray."""
    client, _conn = env
    client.post("/api/v1/report", json=payload(broll_ingest=ingest_section(
        active=False, state="blocked", done=0, total=6,
        warning="Best needs 12 GB VRAM, this GPU has 8 GB — choose Good",
    )), headers=report_headers())
    page = as_admin(client).get("/partials/fleet").text
    assert "[ VRAM ]" in page
    assert "this GPU has 8 GB" in page
    assert "INDEXING B-ROLL" not in page


def test_the_view_carries_ingest_and_proxy_per_machine(env):
    client, conn = env
    client.post("/api/v1/report", json=payload(
        broll_ingest=ingest_section(),
        proxy_coverage={"state": "encoding", "missing": 9, "left": 4},
    ), headers=report_headers())
    entry = api.build_editors_view(conn)["editors"][0]
    assert entry["ingest"]["active"] is True and entry["ingest"]["percent"] == 55
    assert entry["proxy"]["missing"] == 9 and entry["proxy"]["left"] == 4


# -- the sections ReportIn used to drop -------------------------------------


def test_proxy_coverage_is_persisted_and_chipped(env):
    """The standing bug: this section has ridden every heavy tick since the
    proxy generator shipped and reached nobody."""
    client, conn = env
    client.post("/api/v1/report", json=payload(proxy_coverage={
        "state": "idle", "enabled": True, "missing": 132, "braw": 4,
        "needs_resolve": 0, "own": 100, "preview": 32, "left": 12,
        "generated": 900, "failed": 2, "ffmpeg": True, "nvenc": True,
        "scanned_at": "2026-08-18T09:00:00+00:00", "low_space": "",
        "projects": {"2025/FF4/Nuclear": {"missing": 12, "braw": 0,
                                          "needs_resolve": 0, "own": 12,
                                          "preview": 0}},
        "history": {"today": {"generated": 30}, "rate_per_hour": 12.5},
    }), headers=report_headers())
    stored = dbmod.fetch_proxy_coverage_map(conn)[("jsmith", "EDIT-PC")]
    assert stored["missing"] == 132 and stored["state"] == "idle" and stored["left"] == 12
    assert "132 NEED PROXIES" in as_admin(client).get("/partials/fleet").text


def test_youtube_import_parses_instead_of_being_dropped(env):
    client, _conn = env
    resp = client.post("/api/v1/report", json=payload(youtube_import={
        "state": "idle", "pending": 3, "imported_session": 7,
        "failed_session": 0, "last_import_at": "2026-08-18T09:30:00+00:00",
        "last_bin": "Master/Youtube", "last_error": None,
    }), headers=report_headers())
    assert resp.status_code == 200
    parsed = api.ReportIn(**payload(youtube_import={"state": "idle", "pending": 3}))
    assert parsed.youtube_import is not None and parsed.youtube_import.pending == 3


# -- nothing in a diagnostic section may take a machine off the grid --------


def test_oversize_strings_are_truncated_not_rejected(env):
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(broll_ingest=ingest_section(
        clip="x" * 4000, warning="w" * 4000, tier="t" * 200,
        batch_uid="b" * 400, percent=9999,
    )), headers=report_headers())
    assert resp.status_code == 200, "an oversize section must never 422 the report"
    row = dbmod.fetch_broll_ingest_map(conn)[("jsmith", "EDIT-PC")]
    assert len(row["clip"]) == 255 and len(row["warning"]) == 255
    assert len(row["tier"]) == 16 and len(row["batch"]) == 32
    assert row["percent"] == 100


def test_an_unparsable_section_is_dropped_and_the_report_still_lands(env):
    """A companion mid-refactor, or one sending a type this dashboard has
    never seen. The lanes in the same body are what the fleet grid is for."""
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(
        broll_ingest={"done": "twelve", "active": True},
        proxy_coverage=["not", "a", "dict"],
    ), headers=report_headers())
    assert resp.status_code == 200
    assert dbmod.fetch_broll_ingest_map(conn)[("jsmith", "EDIT-PC")]["active"] is False
    assert ("jsmith", "EDIT-PC") in {
        (e["editor_username"], e["machine"]) for e in api.build_editors_view(conn)["editors"]}


def test_unknown_keys_in_the_section_are_ignored(env):
    client, conn = env
    resp = client.post("/api/v1/report", json=payload(broll_ingest=ingest_section(
        transcribing=True, whisper_model="large-v3", future_counter=17,
    )), headers=report_headers())
    assert resp.status_code == 200
    assert dbmod.fetch_broll_ingest_map(conn)[("jsmith", "EDIT-PC")]["active"] is True


# -- commands.broll_ingest --------------------------------------------------


def test_the_reply_carries_the_cancel_list(env, monkeypatch):
    client, _conn = env
    seen = {}

    def provider(settings, editor, machine):
        seen["args"] = (editor, machine)
        return ["a" * 32, "b" * 32]

    monkeypatch.setattr(api, "broll_cancel_requested", provider)
    body = client.post("/api/v1/report", json=payload(broll_ingest=ingest_section()),
                       headers=report_headers()).json()
    assert body["commands"]["broll_ingest"] == {"cancel": ["a" * 32, "b" * 32]}
    assert seen["args"] == ("jsmith", "EDIT-PC")
    # The halt command is untouched by any of this -- it is the channel the
    # whole fleet depends on.
    assert body["commands"]["halt"]["active"] is False


def test_no_cancels_means_no_key(env, monkeypatch):
    client, _conn = env
    monkeypatch.setattr(api, "broll_cancel_requested", lambda *a: [])
    body = client.post("/api/v1/report", json=payload(),
                       headers=report_headers()).json()
    assert "broll_ingest" not in body["commands"]


def test_the_cancel_lookup_is_skipped_when_broll_is_off():
    class Off:
        broll_enabled = False

    assert api.broll_cancel_requested(Off(), "jsmith", "EDIT-PC") == []


class _BrollOn:
    broll_enabled = True


def _fake_broll_app(monkeypatch, tmp_path, cancel_requested_for):
    """Stand in for the mounted sub-app, imported as top-level `app` exactly
    as broll.py imports it."""
    db_file = tmp_path / "broll.db"
    sqlite3.connect(db_file).close()

    pkg = types.ModuleType("app")
    pkg.__path__ = []                       # a package, so `app.x` may resolve
    config = types.ModuleType("app.config")
    config.get_db_path = lambda: db_file
    batches = types.ModuleType("app.ingest_batches")
    batches.cancel_requested_for = cancel_requested_for
    pkg.config, pkg.ingest_batches = config, batches
    for name, mod in (("app", pkg), ("app.config", config),
                      ("app.ingest_batches", batches)):
        monkeypatch.setitem(sys.modules, name, mod)
    return db_file


def test_the_real_lookup_asks_the_broll_database(tmp_path, monkeypatch):
    seen = {}

    def cancel_requested_for(conn, editor, machine):
        seen["args"] = (editor, machine)
        conn.execute("SELECT 1").fetchone()      # a live connection, not a path
        return ["a" * 32, "b" * 32]

    _fake_broll_app(monkeypatch, tmp_path, cancel_requested_for)
    assert api.broll_cancel_requested(_BrollOn(), "jsmith", "EDIT-PC") == \
        ["a" * 32, "b" * 32]
    assert seen["args"] == ("jsmith", "EDIT-PC")


def test_the_lookup_is_read_only_and_capped(tmp_path, monkeypatch):
    """The mounted app holds that database open read-write in WAL mode; this
    is a passenger on somebody else's request, never a writer."""
    def cancel_requested_for(conn, editor, machine):
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE nope (x INTEGER)")
        return [str(n) * 32 for n in range(api.MAX_INGEST_CANCELS + 5)]

    _fake_broll_app(monkeypatch, tmp_path, cancel_requested_for)
    assert len(api.broll_cancel_requested(_BrollOn(), "jsmith", "EDIT-PC")) == \
        api.MAX_INGEST_CANCELS


def test_a_broken_broll_checkout_never_fails_a_report(env, tmp_path, monkeypatch):
    """Best-effort in every direction: the report reply is the fleet's status
    channel and must not acquire a dependency on the b-roll app being
    present, migrated or even readable."""
    client, _conn = env

    def explode(conn, editor, machine):
        raise RuntimeError("no such table: ingest_batches")

    _fake_broll_app(monkeypatch, tmp_path, explode)
    assert api.broll_cancel_requested(_BrollOn(), "jsmith", "EDIT-PC") == []

    # ...and through the route, with the real function in place.
    monkeypatch.setattr(type(client.app.state.settings), "broll_enabled", True,
                        raising=False)
    resp = client.post("/api/v1/report", json=payload(), headers=report_headers())
    assert resp.status_code == 200
    assert "broll_ingest" not in resp.json()["commands"]


def test_no_broll_checkout_at_all_is_silent(monkeypatch):
    """An ImportError is the NORMAL case for a dashboard without the b-roll
    code (and for every dashboard until the ingest module lands): not an
    error, not a log line an operator has to explain."""
    monkeypatch.setitem(sys.modules, "app", types.ModuleType("app"))
    assert api.broll_cancel_requested(_BrollOn(), "jsmith", "EDIT-PC") == []
