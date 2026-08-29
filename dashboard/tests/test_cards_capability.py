"""`capabilities.cards_agent`: the columns, the chip, and the refusal it names.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 2 (2026-08-30), schema v44.

The rules this defends are the ones v42 wrote down and this section re-uses:

  * A DIAGNOSTIC SECTION IS NEVER WORTH A 422 (B6). A companion that sends a
    malformed or future-shaped `cards_agent` keeps its lanes and its row.
  * WRITTEN WHOLESALE. A machine that has STOPPED serving the page must be
    able to say so; a merge would leave the last timeline on the grid for
    ever.
  * THE REFUSAL IS THE INTERESTING FIELD. `connected` false is the normal
    state on every computer in the fleet, and "nobody turned it on" and "a
    standalone agent is still running there" are different problems.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api, auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"

SERVING = {
    "ffmpeg": True, "mounts": ["tree", "vault"], "idle_seconds": 5.0,
    "resolve": {"running": True, "project": "FF5 Animals"},
    "cards_agent": {"connected": True, "state": "running",
                    "timeline": "E1", "version": 5, "since": 1756500000.0},
}


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "caps.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    with TestClient(create_app(settings)) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def hdr(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, caps):
    return client.post("/api/v1/report", json={
        "editor_name": "jsmith", "machine": "EDIT-PC",
        "companion_version": "0.9.58",
        "reported_at": "2026-08-30T10:00:00+00:00", "lanes": [],
        "capabilities": caps}, headers=hdr())


def test_the_migration_is_there(tmp_path):
    conn = dbmod.connect(tmp_path / "v44.db")
    dbmod.migrate(conn)
    assert dbmod.SCHEMA_VERSION >= 44
    cols = {r[1] for r in conn.execute("PRAGMA table_info(machine_state)")}
    assert {"cap_cards_connected", "cap_cards_state", "cap_cards_timeline",
            "cap_cards_version", "cap_cards_since"} <= cols
    conn.close()


def test_the_columns_land(env):
    client, conn = env
    assert report(client, SERVING).status_code == 200
    cards = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["cards_agent"]
    assert cards == {"connected": True, "state": "running", "timeline": "E1",
                     "version": 5, "since": 1756500000.0}


def test_a_machine_that_stopped_serving_says_so(env):
    """Wholesale, not merged: the timeline must not outlive the connection."""
    client, conn = env
    report(client, SERVING)
    report(client, {"ffmpeg": True,
                    "cards_agent": {"connected": False, "state": "disabled"}})
    cards = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["cards_agent"]
    assert cards["connected"] is False
    assert cards["timeline"] == ""
    assert cards["state"] == "disabled"


def test_the_refusal_is_carried(env):
    client, conn = env
    report(client, {"cards_agent": {"connected": False,
                                    "state": "standalone_agent"}})
    cards = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["cards_agent"]
    assert cards["state"] == "standalone_agent"


def test_an_older_companion_sends_nothing_and_is_not_refused(env):
    client, conn = env
    assert report(client, {"ffmpeg": True}).status_code == 200
    cards = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["cards_agent"]
    assert cards["connected"] is False and cards["state"] == ""


def test_a_malformed_block_is_dropped_not_422(env):
    """B6: a diagnostic section is never worth refusing a report over.

    The WHOLE capabilities section is dropped, which is the existing rule for
    a section that will not validate -- so the previous answer stands and the
    lanes in the same body are still recorded. What must never happen is a
    422 that takes the sync report down with it.
    """
    client, conn = env
    report(client, SERVING)
    assert report(client, {"ffmpeg": True,
                           "cards_agent": "yes please"}).status_code == 200
    assert report(client, {"ffmpeg": True,
                           "cards_agent": {"connected": "sort of",
                                           "version": -3}}).status_code == 200
    cards = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["cards_agent"]
    assert cards["timeline"] == "E1"


def test_a_future_field_does_not_refuse_the_report(env):
    client, _conn = env
    assert report(client, {"cards_agent": {
        "connected": True, "state": "running",
        "something_phase_three_added": {"a": 1}}}).status_code == 200


def test_an_oversize_timeline_name_is_bounded_not_refused(env):
    client, conn = env
    assert report(client, {"cards_agent": {"connected": True,
                                           "timeline": "E" * 5000}}
                  ).status_code == 200
    cards = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")["cards_agent"]
    assert len(cards["timeline"]) <= 255


def test_the_grid_carries_the_chip(env):
    """build_editors_view is the seam that decides whether [ CARDS: E1 v5 ]
    can exist at all."""
    client, conn = env
    report(client, SERVING)
    entry = next(e for e in api.build_editors_view(conn)["editors"]
                 if e["machine"] == "EDIT-PC")
    assert entry["capabilities"]["cards_agent"]["connected"] is True
    assert entry["capabilities"]["cards_agent"]["timeline"] == "E1"
    assert entry["capabilities"]["cards_agent"]["version"] == 5


def test_the_chip_renders_and_the_refusing_machine_gets_none(env):
    client, conn = env
    report(client, SERVING)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    page = client.get("/partials/fleet")
    assert page.status_code == 200
    assert "[ CARDS: E1 v5 ]" in page.text
    report(client, {"cards_agent": {"connected": False, "state": "disabled"}})
    page = client.get("/partials/fleet")
    assert "[ CARDS" not in page.text
