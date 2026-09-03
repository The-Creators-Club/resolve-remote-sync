"""CMEDIA-3 (usability sweep 2026-09-04): the 8899 loopback's health reaches
the fleet page.

The companion sends `sync_guard.loopback` = {enabled, bound, port, error,
since} on every report, healthy shape included. Undeclared here it would be
accepted (SyncGuardIn is extra='allow') and then dropped -- the exact
mechanism that lost syncthing_supervisor for weeks (SYS-3 / SYNC-8) -- and
"Send to Resolve does nothing on Ruskin's PC" would stay a fault visible only
in his browser.

server/tests/test_cross_component.py pins the declaration itself; this pins the
half that makes the declaration worth having: the value is STORED, it is read
back per machine, and it is LATCHED so a machine that takes the port back
clears its own chip.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.api import SyncGuardIn, flatten_sync_guard
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "m.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn
        conn.close()


def _report(client, guard=None):
    body = {"editor_name": "ruskin", "machine": "EDIT-PC", "mode": "editor",
            "reported_at": dbmod.utcnow_iso(), "lanes": []}
    if guard is not None:
        body["sync_guard"] = guard
    r = client.post("/api/v1/report", json=body, headers={
        "X-CCSync-Token": TOKEN,
        "X-CCSync-Identity": auth.make_identity_token(SECRET, "ruskin")})
    assert r.status_code == 200, r.text


def _guard(conn):
    return dbmod.fetch_sync_guard_map(conn)[("ruskin", "EDIT-PC")]


def test_sync_guard_declares_the_loopback_section(env):
    assert "loopback" in SyncGuardIn.model_fields


def test_a_held_port_is_stored_and_readable_per_machine(env):
    client, conn = env
    _report(client, {"loopback": {"enabled": True, "bound": False, "port": 8899,
                                  "error": "port 8899 is already in use",
                                  "since": "2026-09-04T09:00:00+00:00"}})
    guard = _guard(conn)
    assert guard["loopback_enabled"] == 1
    assert guard["loopback_bound"] == 0
    assert guard["loopback_port"] == 8899
    assert guard["loopback_error"] == "port 8899 is already in use"
    assert guard["loopback_since"] == "2026-09-04T09:00:00+00:00"


def test_taking_the_port_back_clears_the_fault(env):
    """THE LATCH RULE: the healthy report must be able to clear this
    morning's bind failure, which a COALESCE could never do."""
    client, conn = env
    _report(client, {"loopback": {"enabled": True, "bound": False, "port": 8899,
                                  "error": "port 8899 is already in use",
                                  "since": "2026-09-04T09:00:00+00:00"}})
    _report(client, {"loopback": {"enabled": True, "bound": True, "port": 8899,
                                  "error": "", "since": ""}})
    guard = _guard(conn)
    assert guard["loopback_bound"] == 1
    # "" is a healthy answer over there and NULL here: a column that is either
    # a fault or nothing is one the grid can chip on safely.
    assert guard["loopback_error"] is None
    assert guard["loopback_since"] is None


def test_a_companion_too_old_to_report_it_says_nothing_rather_than_bound(env):
    client, conn = env
    _report(client, {"trash": {"bytes": 1, "count": 1}})
    guard = _guard(conn)
    assert guard["loopback_bound"] is None
    assert guard["loopback_enabled"] is None


def test_a_report_with_no_guard_at_all_leaves_the_columns_alone(env):
    client, conn = env
    _report(client, {"loopback": {"enabled": True, "bound": False, "port": 8899,
                                  "error": "taken"}})
    _report(client, None)
    assert _guard(conn)["loopback_error"] == "taken"


def test_an_absurd_port_does_not_422_the_whole_report(env):
    """SYS-3/B6: a bad value in the alarm channel must never take the lanes,
    the transfers and the presence data down with it."""
    guard = flatten_sync_guard(
        SyncGuardIn.model_validate({"loopback": {"port": 999999, "bound": True}}),
        dbmod.utcnow_iso())
    assert guard["loopback_bound"] == 1
