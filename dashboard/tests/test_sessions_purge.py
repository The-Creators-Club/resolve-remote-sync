"""SessionStore.purge_user and SessionStore.subject_rows (LG-2 / LG-3,
docs/LEGAL_GAP_FEATURES_PLAN.md 4.2 and 4.3, 2026-09-25, group G2a).

The rules defended here:

- ERASE HISTORY (revoked_only=True) keeps the account working: a live
  session survives, dead ones (revoked, idle-expired, past the absolute
  lifetime) go, and an ACTIVE sign-in lockout survives (safety L1) while a
  lapsed one goes.
- DELETE (revoked_only=False) removes every session and every
  username-keyed throttle row, and nothing of anybody else's.
- IP-keyed throttle rows are never touched: they cannot be tied to a person.
- The export never carries the sid, which is a keyed digest of the cookie.
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import sessions as sessmod

NOW = "2026-09-25T12:00:00+00:00"
HOUR = 3600


def _at(seconds_before: float) -> str:
    return sessmod._shift(NOW, -seconds_before)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "sessions.db"
    conn = dbmod.connect(str(path))
    dbmod.migrate(conn)
    conn.close()
    s = sessmod.SessionStore(path)
    s.ensure_schema()
    return s


def _sessions(store, username):
    conn = dbmod.connect(store.db_path)
    try:
        return {r["sid"]: dict(r) for r in conn.execute(
            "SELECT * FROM auth_sessions WHERE username=?", (username,))}
    finally:
        conn.close()


def _attempts(store):
    conn = dbmod.connect(store.db_path)
    try:
        return {(r["scope"], r["key"]): dict(r) for r in conn.execute(
            "SELECT * FROM login_attempts")}
    finally:
        conn.close()


def _seed(store):
    # alice: one live, one revoked, one idle-expired, one past absolute life.
    store.create("live", "alice", "1.2.3.4 Chrome", now=_at(60))
    store.create("revoked", "alice", "", now=_at(2 * HOUR))
    store.revoke("revoked", by="alice", now=_at(HOUR))
    store.create("idle", "alice", "", now=_at(13 * HOUR))
    store.create("old", "alice", "", now=_at(8 * 24 * HOUR))
    conn = dbmod.connect(store.db_path)
    try:
        # A recent touch so "old" is only past its ABSOLUTE life.
        conn.execute("UPDATE auth_sessions SET last_seen=? WHERE sid='old'", (_at(60),))
        conn.commit()
    finally:
        conn.close()
    # bob's session must never be touched by alice's purge.
    store.create("bob-live", "bob", "", now=_at(60))


def test_erase_keeps_the_live_session_and_deletes_the_dead_ones(store):
    _seed(store)
    out = store.purge_user("alice", revoked_only=True, now=NOW)
    left = _sessions(store, "alice")
    assert set(left) == {"live"}
    assert out["auth_sessions"] == 3
    assert set(_sessions(store, "bob")) == {"bob-live"}
    # The one that survived still validates: erase never signs anyone out.
    assert store.validate("live", now=NOW) == "alice"


def test_erase_keeps_an_active_lockout_and_drops_a_lapsed_one(store):
    conn = dbmod.connect(store.db_path)
    try:
        conn.execute(
            "INSERT INTO login_attempts VALUES ('user','alice',7,?,?,?)",
            (_at(600), _at(60), sessmod._shift(NOW, 1800)))
        conn.execute(
            "INSERT INTO login_attempts VALUES ('user','carol',6,?,?,?)",
            (_at(3 * HOUR), _at(2 * HOUR), _at(HOUR)))
        conn.execute(
            "INSERT INTO login_attempts VALUES ('ip','1.2.3.4',3,?,?,NULL)",
            (_at(600), _at(60)))
        conn.commit()
    finally:
        conn.close()
    assert store.purge_user("alice", revoked_only=True, now=NOW)["login_attempts"] == 0
    assert ("user", "alice") in _attempts(store)
    # The lockout still holds after the erase (safety L1).
    assert store.throttled("alice", now=NOW) > 0
    assert store.purge_user("carol", revoked_only=True, now=NOW)["login_attempts"] == 1
    assert ("user", "carol") not in _attempts(store)
    assert ("ip", "1.2.3.4") in _attempts(store)


def test_a_failure_row_with_no_block_is_history(store):
    store.record_failure("alice", ip="9.9.9.9", now=_at(60))
    assert store.purge_user("alice", revoked_only=True, now=NOW)["login_attempts"] == 1
    assert ("ip", "9.9.9.9") in _attempts(store)


def test_delete_removes_every_session_and_throttle_row_of_that_user_only(store):
    _seed(store)
    conn = dbmod.connect(store.db_path)
    try:
        conn.execute(
            "INSERT INTO login_attempts VALUES ('user','alice',7,?,?,?)",
            (_at(600), _at(60), sessmod._shift(NOW, 1800)))
        conn.execute(
            "INSERT INTO login_attempts VALUES ('user','bob',1,?,?,NULL)",
            (_at(600), _at(60)))
        conn.commit()
    finally:
        conn.close()
    out = store.purge_user("Alice", now=NOW)
    assert out == {"auth_sessions": 4, "login_attempts": 1}
    assert _sessions(store, "alice") == {}
    assert set(_sessions(store, "bob")) == {"bob-live"}
    assert ("user", "bob") in _attempts(store)


def test_purge_before_the_tables_exist_is_a_no_op(tmp_path):
    path = tmp_path / "fresh.db"
    conn = dbmod.connect(str(path))
    dbmod.migrate(conn)
    conn.close()
    fresh = sessmod.SessionStore(path)
    assert fresh.purge_user("alice") == {"auth_sessions": 0, "login_attempts": 0}
    assert fresh.subject_rows("alice") == {"auth_sessions": [], "login_attempts": []}


def test_subject_rows_carry_no_sid(store):
    _seed(store)
    store.record_failure("alice", ip="9.9.9.9", now=_at(60))
    rows = store.subject_rows("ALICE")
    assert len(rows["auth_sessions"]) == 4
    for row in rows["auth_sessions"]:
        assert "sid" not in row
        assert set(row) == {"created_at", "last_seen", "client", "revoked",
                            "revoked_at", "revoked_by"}
        # No value is a sid or a prefix handle of one either.
        assert not any(str(v) in {"live", "revoked", "idle", "old"} for v in row.values())
    # Only the username-keyed throttle row; the IP one is not a person's.
    assert [(r["scope"], r["key"]) for r in rows["login_attempts"]] == [("user", "alice")]
    assert rows == store.subject_rows("alice")


# ------------------------------------------- the delete that calls purge_user
#
# api.delete_user_everywhere's LG-3 half (G0 hand-off 2): the store's rows,
# the revoked report tokens, the stand-in on the delete's own audit row, the
# admin actor kept, and the other stores asked, none of it able to turn a
# finished delete into an error.

import sys
import types

from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"


@pytest.fixture
def local_env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "purge_delete.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    app = create_app(settings)
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client


def _make(client, username, role="editor"):
    resp = client.post("/api/v1/admin/users", json={
        "username": username, "role": role, "password": "correct-horse-battery-new"})
    assert resp.status_code == 200, resp.text


def _db(client):
    return dbmod.connect(client.app.state.settings.db_path)


def test_delete_removes_every_session_row_and_the_revoked_tokens(local_env):
    _make(local_env, "newbie")
    store = local_env.app.state.session_store
    store.create("sid-live", "newbie", client="laptop")
    store.create("sid-dead", "newbie", client="phone")
    store.revoke("sid-dead", by="newbie")
    store.record_failure("newbie", ip="5.6.7.8")
    conn = _db(local_env)
    dbmod.create_editor_report_token(conn, "newbie", created_by="owen")
    conn.commit()
    conn.close()

    resp = local_env.delete("/api/v1/admin/users/newbie")
    assert resp.status_code == 200, resp.text
    deleted = resp.json()["deleted"]
    assert deleted["sessions_revoked"] == 1
    assert deleted["report_tokens_revoked"] == 1
    assert deleted["report_tokens_deleted"] == 1
    # Ints, like `sessions_revoked` beside them (review round, point 6).
    assert deleted["sessions_deleted"] == 2
    assert deleted["login_attempts_deleted"] == 1
    assert store.subject_rows("newbie") == {"auth_sessions": [], "login_attempts": []}
    conn = _db(local_env)
    try:
        assert conn.execute("SELECT COUNT(*) FROM editor_report_tokens"
                            " WHERE editor_username='newbie'").fetchone()[0] == 0
        # The IP-keyed row is nobody's and stays.
        assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE scope='ip'"
                            " AND key='5.6.7.8'").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_delete_audit_row_names_the_stand_in(local_env):
    _make(local_env, "newbie")
    assert local_env.delete("/api/v1/admin/users/newbie").status_code == 200
    conn = _db(local_env)
    try:
        rows = conn.execute("SELECT actor, subject, detail_json FROM fleet_audit"
                            " WHERE action='user.delete'").fetchall()
        assert len(rows) == 1
        assert rows[0]["actor"] == "owen"
        assert rows[0]["subject"] == dbmod.pseudonym(conn, "newbie")
        assert rows[0]["subject"].startswith("deleted-user-")
        assert "newbie" not in rows[0]["detail_json"]
    finally:
        conn.close()


def test_a_deleted_admin_keeps_their_name_on_what_they_did(local_env):
    _make(local_env, "chief", role="admin")   # boss is not the last local admin
    _make(local_env, "boss", role="admin")
    _make(local_env, "newbie")
    conn = _db(local_env)
    dbmod.audit(conn, "boss", "project.archive", "p1", {})
    dbmod.audit(conn, "newbie", "selection.tick", "newbie/PC", {})
    conn.commit()
    conn.close()
    assert local_env.delete("/api/v1/admin/users/boss").status_code == 200
    assert local_env.delete("/api/v1/admin/users/newbie").status_code == 200
    conn = _db(local_env)
    try:
        actors = {r["action"]: r["actor"] for r in conn.execute(
            "SELECT action, actor FROM fleet_audit WHERE action IN"
            " ('project.archive', 'selection.tick')")}
        # Safety M5: an administrator's actions keep their name until the
        # 180-day prune; nobody else's do.
        assert actors["project.archive"] == "boss"
        assert actors["selection.tick"] == dbmod.pseudonym(conn, "newbie")
    finally:
        conn.close()


def test_the_other_stores_are_asked_and_a_failure_is_a_warning(local_env, monkeypatch):
    from ccsync_dashboard import ytdl
    asked = []
    monkeypatch.setattr(ytdl, "forget_requester",
                        lambda username, **kw: asked.append(("ytdl", username)) or {"jobs": 1},
                        raising=False)

    def broken(username, *a, **kw):
        asked.append(("shares", username))
        raise RuntimeError("client_shares.db is locked")

    fake = types.ModuleType("ccsync_dashboard.subject_data")
    fake.forget_shares = broken
    monkeypatch.setitem(sys.modules, "ccsync_dashboard.subject_data", fake)
    _make(local_env, "newbie")
    resp = local_env.delete("/api/v1/admin/users/newbie")
    assert resp.status_code == 200, resp.text
    assert asked == [("ytdl", "newbie"), ("shares", "newbie")]
    warnings = resp.json()["warnings"]
    assert any("client folders" in w for w in warnings)
    assert not any("—" in w for w in warnings)


# G2a review round, point 1 (2026-09-25): the first build called both stores
# with the username alone. G3's real forget_shares raises without a stand-in
# or a connection, so every delete kept the real name in client folders and
# warned about it; the fake above hid that.


def _client_shares(path):
    import sqlite3
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE client_folders (id INTEGER PRIMARY KEY, name TEXT, created_by TEXT);
        CREATE TABLE client_folder_items (id INTEGER PRIMARY KEY, folder_id INTEGER,
                                          added_by TEXT);
        INSERT INTO client_folders VALUES (1, 'Taichung', 'newbie');
        INSERT INTO client_folders VALUES (2, 'Other', 'owen');
        INSERT INTO client_folder_items VALUES (1, 1, 'newbie');
    """)
    c.commit()
    c.close()


def test_the_real_forget_shares_takes_the_name_out_of_client_folders(
        local_env, monkeypatch, tmp_path):
    import sqlite3
    from ccsync_dashboard import subject_data, ytdl
    shares = tmp_path / "client_shares.db"
    _client_shares(shares)
    monkeypatch.setattr(subject_data, "_store_paths",
                        lambda: {"client_shares": shares, "broll": None, "music": None})
    seen = {}

    def fake_ytdl(username, conn=None, **kw):
        seen.update(conn=conn is not None, **kw)
        return {"status": "absent"}

    monkeypatch.setattr(ytdl, "forget_requester", fake_ytdl, raising=False)
    _make(local_env, "newbie")
    resp = local_env.delete("/api/v1/admin/users/newbie")
    assert resp.status_code == 200, resp.text
    assert not any("client folders" in w for w in resp.json()["warnings"])
    conn = _db(local_env)
    try:
        stand_in = dbmod.pseudonym(conn, "newbie")
    finally:
        conn.close()
    c = sqlite3.connect(shares)
    try:
        assert c.execute("SELECT created_by FROM client_folders ORDER BY id").fetchall() == [
            (stand_in,), ("owen",)]
        assert c.execute("SELECT added_by FROM client_folder_items").fetchall() == [
            (stand_in,)]
    finally:
        c.close()
    # ytdl gets the dashboard connection and the same stand-in, not a
    # DASH_DB_PATH it may not have.
    assert seen == {"conn": True, "pseudonym": stand_in}
