"""LG-2 export and the LG-3 erase-history route (docs/LEGAL_GAP_FEATURES_PLAN.md
4.2 and 4.3, 2026-09-25; builder group G3).

Every test signs in through /api/v1/login, so the session is TRACKED and the
CSRF gate is live exactly as in a deployment (test_account_api.py's shape;
hand-minted cookies skip the gate and would make the CSRF tests vacuous).
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import db, subject_data, subject_data_api, ytdl
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

PASSWORD = "correct-horse-battery"
STRONG = "kX9-quiet-harbour-42-zephyr"
EM_DASH = chr(0x2014)


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    yield


@pytest.fixture
def no_other_stores(monkeypatch):
    # A test process may have imported the b-roll or music tree for another
    # suite; the export must not read a real index here.
    monkeypatch.setattr(subject_data, "_store_paths",
                        lambda: {"client_shares": None, "broll": None, "music": None})


def _ytdl_envelope(status="absent", detail="the YouTube downloader has no records here",
                   **payload):
    # G4's real shape (ytdl.subject_rows / forget_history, 2026-09-25). The
    # first build's stubs answered bare tables and hid review points 1 and 2.
    return {"status": status, "detail": detail, **payload}


@pytest.fixture(autouse=True)
def no_real_ytdl_store(monkeypatch):
    # Review point 5: unstubbed, the real helpers open ytdl/web/data/ytdl.db
    # in the repo (YTDL_DATA_ROOT's default) when a mount test imported it,
    # run ensure_schema on it and delete jsmith's finished jobs from it.
    monkeypatch.setattr(ytdl, "subject_rows",
                        lambda u, **k: _ytdl_envelope(tables={}), raising=False)
    monkeypatch.setattr(ytdl, "forget_history",
                        lambda u, **k: _ytdl_envelope(counts={}), raising=False)


@pytest.fixture
def app(tmp_path, strict, no_other_stores):
    settings = Settings(db_path=str(tmp_path / "subj.db"), session_secret=STRONG,
                        admin_users=frozenset({"owen"}))
    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    application = create_app(settings)
    application.state.credential_verifier = lambda s, u, p: p == PASSWORD
    return application


class Signed:
    def __init__(self, app, user: str):
        self.client = TestClient(app)
        self.client.__enter__()
        resp = self.client.post("/api/v1/login", json={"username": user, "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        self.csrf = resp.json()["csrf"]

    @property
    def h(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def close(self):
        self.client.__exit__(None, None, None)


@pytest.fixture
def browsers(app):
    made: list[Signed] = []

    def make(user: str) -> Signed:
        s = Signed(app, user)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def _conn(app) -> sqlite3.Connection:
    return db.connect(app.state.settings.db_path)


def _seed(app, editor: str = "jsmith", machine: str = "JS-LAPTOP") -> None:
    now = db.utcnow_iso()
    conn = _conn(app)
    try:
        db.record_known_editor(conn, editor, "admin")
        db.upsert_machine(conn, editor, machine, now, platform="windows")
        db.upsert_machine_state(conn, editor, machine, None, now, platform="windows",
                                companion_version="0.9.80", mode="remote")
        conn.execute("INSERT INTO lane_report_history (editor_username, machine, lane, state, ts)"
                     " VALUES (?, ?, 'a', 'idle', ?)", (editor, machine, now))
        conn.execute("INSERT INTO diagnostics (editor, machine, received_at, text)"
                     " VALUES (?, ?, ?, 'a bundle')", (editor, machine, now))
        db.create_editor_report_token(conn, editor, "owen", label="laptop")
        conn.commit()
    finally:
        conn.close()


def _export(resp) -> dict:
    assert resp.status_code == 200, resp.text
    return json.loads(resp.content)


def _audit(app, action: str) -> list[dict]:
    conn = _conn(app)
    try:
        return db.fetch_audit(conn, actions=(action,))
    finally:
        conn.close()


# ------------------------------------------------------------------ export

def test_admin_export_holds_every_registry_table(app, browsers):
    _seed(app)
    owen = browsers("owen")
    resp = owen.client.post("/api/v1/admin/users/jsmith/export", headers=owen.h)
    data = _export(resp)
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="ccsync-data-jsmith-')
    assert disposition.endswith('.json"')
    assert data["subject"] == "jsmith"
    assert set(data) == {"generated_at", "dashboard_version", "subject", "tables",
                         "not_included"}
    for entry in db.SUBJECT_TABLES:
        assert entry.table in data["tables"], entry.table
    assert data["tables"]["machines"][0]["machine"] == "JS-LAPTOP"
    assert len(data["tables"]["lane_report_history"]) == 1
    # every base sentence, and a store that is not here is SAID, not skipped
    for sentence in subject_data.NOT_INCLUDED:
        assert sentence in data["not_included"]
    assert any("Client folders" in s for s in data["not_included"])


def test_export_leaves_secret_columns_out(app, browsers):
    _seed(app)
    conn = _conn(app)
    try:
        conn.execute("INSERT INTO users (username, password_hash, role, created_at)"
                     " VALUES ('jsmith', 'scrypt$SECRET', 'editor', ?)", (db.utcnow_iso(),))
        conn.commit()
    except sqlite3.OperationalError:
        pytest.skip("users table shape differs")
    finally:
        conn.close()
    jsmith = browsers("jsmith")
    data = _export(jsmith.client.post("/api/v1/me/export", headers=jsmith.h))
    raw = json.dumps(data)
    assert "scrypt$SECRET" not in raw
    assert all("password_hash" not in r for r in data["tables"]["users"])
    tokens = data["tables"]["editor_report_tokens"]
    assert tokens and all("token_hash" not in r for r in tokens)
    for row in data["tables"].get("sessions.auth_sessions", []):
        assert "sid" not in row


def test_me_export_takes_the_subject_from_the_session_not_as(app, browsers):
    _seed(app)
    owen = browsers("owen")
    data = _export(owen.client.post("/api/v1/me/export?as=jsmith", headers=owen.h))
    assert data["subject"] == "owen"
    assert all(r.get("editor_username") != "jsmith"
               for r in data["tables"].get("machines", []))


def test_non_admin_is_refused_another_persons_data(app, browsers):
    _seed(app)
    _seed(app, "alice", "AL-PC")
    jsmith = browsers("jsmith")
    assert jsmith.client.post("/api/v1/admin/users/alice/export",
                              headers=jsmith.h).status_code == 403
    assert jsmith.client.post("/api/v1/admin/users/jsmith/export",
                              headers=jsmith.h).status_code == 403
    assert jsmith.client.post("/api/v1/admin/users/alice/erase-history",
                              headers=jsmith.h).status_code == 403
    assert jsmith.client.post("/partials/admin/users/erase-history", data={"username": "alice"},
                              headers=jsmith.h).status_code == 403


def test_unknown_person_is_404_and_bad_name_400(app, browsers):
    owen = browsers("owen")
    assert owen.client.post("/api/v1/admin/users/nobody/export",
                            headers=owen.h).status_code == 404
    assert owen.client.post("/api/v1/admin/users/Bad%20Name!/export",
                            headers=owen.h).status_code == 400


def test_over_the_size_cap_is_413_and_not_audited(app, browsers, monkeypatch):
    _seed(app)
    monkeypatch.setattr(subject_data_api, "MAX_EXPORT_BYTES", 10)
    owen = browsers("owen")
    resp = owen.client.post("/api/v1/admin/users/jsmith/export", headers=owen.h)
    assert resp.status_code == 413
    assert "larger than" in resp.json()["detail"]
    assert _audit(app, subject_data_api.AUDIT_USER_EXPORT) == []


def test_six_exports_in_an_hour_is_429(app, browsers):
    _seed(app)
    owen = browsers("owen")
    for _ in range(subject_data_api.EXPORTS_PER_HOUR):
        assert owen.client.post("/api/v1/admin/users/jsmith/export",
                                headers=owen.h).status_code == 200
    resp = owen.client.post("/api/v1/admin/users/jsmith/export", headers=owen.h)
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0
    # keyed on the subject: another person's export is unaffected
    _seed(app, "alice", "AL-PC")
    assert owen.client.post("/api/v1/admin/users/alice/export",
                            headers=owen.h).status_code == 200


def test_one_export_at_a_time_per_person(app, browsers):
    _seed(app)
    owen = browsers("owen")
    gate = subject_data_api._ExportGate()
    gate.running.add("jsmith")
    app.state.subject_export_gate = gate
    resp = owen.client.post("/api/v1/admin/users/jsmith/export", headers=owen.h)
    assert resp.status_code == 429
    assert "already being made" in resp.json()["detail"]
    gate.running.clear()
    assert owen.client.post("/api/v1/admin/users/jsmith/export",
                            headers=owen.h).status_code == 200
    assert gate.running == set()


def test_export_writes_an_audit_row_of_counts_only(app, browsers):
    _seed(app)
    owen = browsers("owen")
    _export(owen.client.post("/api/v1/admin/users/jsmith/export", headers=owen.h))
    rows = _audit(app, subject_data_api.AUDIT_USER_EXPORT)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor"] == "owen" and row["subject"] == "jsmith"
    assert row["detail"]["tables"]["lane_report_history"] == 1
    assert all(isinstance(v, int) for v in row["detail"]["tables"].values())
    assert "JS-LAPTOP" not in row["detail_json"] and "a bundle" not in row["detail_json"]


def test_routes_are_post_only_and_need_the_csrf_token(app, browsers):
    _seed(app)
    owen = browsers("owen")
    for path in ("/api/v1/admin/users/jsmith/export", "/api/v1/me/export",
                 "/api/v1/admin/users/jsmith/erase-history"):
        assert owen.client.get(path).status_code == 405, path
        assert owen.client.post(path).status_code == 403, path
    # the plain forms send the token as a field, which the gate also reads
    resp = owen.client.post("/api/v1/me/export", data={"csrf": owen.csrf})
    assert resp.status_code == 200
    # nothing was erased by the refused erase
    conn = _conn(app)
    try:
        assert conn.execute("SELECT COUNT(*) FROM lane_report_history").fetchone()[0] == 1
    finally:
        conn.close()


def test_signed_out_is_refused(app):
    with TestClient(app) as client:
        for path in ("/api/v1/me/export", "/api/v1/admin/users/jsmith/export"):
            assert client.post(path).status_code in (401, 403)


# ------------------------------------------------------------------- erase

def test_erase_is_history_only_and_export_after_has_none(app, browsers):
    _seed(app)
    owen = browsers("owen")
    resp = owen.client.post("/api/v1/admin/users/jsmith/erase-history", headers=owen.h)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["removed"]["lane_report_history"] == 1
    assert out["removed"]["diagnostics"] == 1
    data = _export(owen.client.post("/api/v1/admin/users/jsmith/export", headers=owen.h))
    for entry in db.SUBJECT_TABLES:
        if entry.kind == db.SUBJECT_HISTORY:
            assert data["tables"].get(entry.table, []) == [], entry.table
    # current state and identity stay (decision D15)
    assert data["tables"]["machine_state"][0]["mode"] == "remote"
    assert data["tables"]["machines"] and data["tables"]["editor_report_tokens"]
    rows = _audit(app, subject_data_api.AUDIT_USER_ERASE_HISTORY)
    assert rows and rows[0]["actor"] == "owen" and rows[0]["subject"] == "jsmith"
    assert rows[0]["detail"]["removed"]["lane_report_history"] == 1
    assert "JS-LAPTOP" not in rows[0]["detail_json"]


def test_erase_calls_the_other_stores_after_the_commit(app, browsers, monkeypatch):
    _seed(app)
    seen: list[tuple] = []

    def fake_purge(self, username, revoked_only=False, now=None):
        # The dashboard's history is already committed when the store runs.
        conn = db.connect(self.db_path)
        try:
            left = conn.execute("SELECT COUNT(*) FROM lane_report_history").fetchone()[0]
        finally:
            conn.close()
        seen.append(("sessions", username, revoked_only, left))
        return {"auth_sessions": 2, "login_attempts": 0}

    def fake_forget(username, **_):
        seen.append(("ytdl", username))
        return _ytdl_envelope("ok", "", counts={"jobs": 3, "terms": 4, "videos": 5})

    from ccsync_dashboard import sessions as sessions_mod

    monkeypatch.setattr(sessions_mod.SessionStore, "purge_user", fake_purge, raising=False)
    monkeypatch.setattr(ytdl, "forget_history", fake_forget, raising=False)
    owen = browsers("owen")
    out = owen.client.post("/api/v1/admin/users/jsmith/erase-history", headers=owen.h).json()
    assert ("sessions", "jsmith", True, 0) in seen
    assert ("ytdl", "jsmith") in seen
    assert out["removed"]["sessions.auth_sessions"] == 2
    assert out["removed"]["ytdl.jobs"] == 3
    assert out["removed"]["ytdl.videos"] == 5
    assert "ytdl.detail" not in out["removed"] and "ytdl.status" not in out["removed"]
    assert out["not_done"] == []
    audit = _audit(app, subject_data_api.AUDIT_USER_ERASE_HISTORY)[0]["detail"]
    assert audit["removed"]["ytdl.terms"] == 4 and "ytdl.detail" not in audit["removed"]


def test_a_ytdl_erase_that_failed_is_not_done(app, browsers, monkeypatch):
    _seed(app)
    monkeypatch.setattr(ytdl, "forget_history",
                        lambda u, **k: _ytdl_envelope("error", "locked", counts={}),
                        raising=False)
    owen = browsers("owen")
    out = owen.client.post("/api/v1/admin/users/jsmith/erase-history", headers=owen.h).json()
    assert out["not_done"] == ["ytdl"]
    assert not any(k.startswith("ytdl") for k in out["removed"])
    audit = _audit(app, subject_data_api.AUDIT_USER_ERASE_HISTORY)[0]
    assert audit["detail"]["not_done"] == ["ytdl"] and "locked" not in audit["detail_json"]
    resp = owen.client.post("/partials/admin/users/erase-history",
                            data={"username": "jsmith"}, headers=owen.h)
    assert "could not be reached" in resp.text


def test_erase_names_a_store_it_could_not_reach(app, browsers, monkeypatch):
    _seed(app)
    monkeypatch.delattr(ytdl, "forget_history", raising=False)
    owen = browsers("owen")
    out = owen.client.post("/api/v1/admin/users/jsmith/erase-history", headers=owen.h).json()
    assert "ytdl" in out["not_done"]


def test_erase_from_the_users_panel_answers_in_the_panel(app, browsers):
    _seed(app)
    owen = browsers("owen")
    resp = owen.client.post("/partials/admin/users/erase-history",
                            data={"username": "jsmith"}, headers=owen.h)
    assert resp.status_code == 200, resp.text
    assert "admin-users-box" in resp.text
    assert "Erased 2 past records about jsmith" in resp.text
    # the row carries both buttons, and the export form carries the token
    assert 'action="/api/v1/admin/users/jsmith/export"' in resp.text
    assert f'name="csrf" value="{owen.csrf}"' in resp.text
    assert 'hx-post="/partials/admin/users/erase-history"' in resp.text
    assert '<span class="t">erase history</span><span class="vh"> of jsmith</span>' in resp.text
    resp = owen.client.post("/partials/admin/users/erase-history",
                            data={"username": "nobody"}, headers=owen.h)
    assert resp.status_code == 200
    assert "holds nothing about nobody" in resp.text


def test_account_page_offers_the_download(app, browsers):
    _seed(app)
    jsmith = browsers("jsmith")
    resp = jsmith.client.get("/account")
    assert resp.status_code == 200, resp.text
    assert 'action="/api/v1/me/export"' in resp.text
    assert f'name="csrf" value="{jsmith.csrf}"' in resp.text
    assert "Download everything the dashboard holds about you" in resp.text


# -------------------------------------------------------- the other stores

def _client_shares(tmp_path) -> str:
    path = tmp_path / "client_shares.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE client_folders (id INTEGER PRIMARY KEY, token TEXT NOT NULL,
            title TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE client_folder_items (id INTEGER PRIMARY KEY, folder_id INTEGER,
            video_id INTEGER, added_by TEXT NOT NULL, added_at TEXT NOT NULL);
        INSERT INTO client_folders VALUES (1, 'tok-secret-1', 'Drone', 'jsmith', 't');
        INSERT INTO client_folders VALUES (2, 'tok-secret-2', 'Other', 'alice', 't');
        INSERT INTO client_folder_items VALUES (1, 1, 10, 'jsmith', 't');
        INSERT INTO client_folder_items VALUES (2, 2, 11, 'alice', 't');
    """)
    conn.commit()
    conn.close()
    return str(path)


def test_collect_reads_client_folders_read_only_without_the_link_token(app, tmp_path,
                                                                        monkeypatch):
    _seed(app)
    shares = _client_shares(tmp_path)
    monkeypatch.setattr(subject_data, "_store_paths",
                        lambda: {"client_shares": shares, "broll": None, "music": None})
    monkeypatch.setattr(ytdl, "subject_rows", lambda u, **k: _ytdl_envelope(
        "ok", "", tables={"jobs": [{"id": 1, "created_by": u}], "terms": []}), raising=False)
    conn = _conn(app)
    try:
        data = subject_data.collect(conn, "jsmith")
    finally:
        conn.close()
    folders = data["tables"]["client_shares.client_folders"]
    assert [f["title"] for f in folders] == ["Drone"]
    assert "token" not in folders[0]
    assert len(data["tables"]["client_shares.client_folder_items"]) == 1
    assert data["tables"]["ytdl.jobs"] == [{"id": 1, "created_by": "jsmith"}]
    assert data["tables"]["ytdl.terms"] == []
    assert "ytdl.status" not in data["tables"]
    assert not any(s.startswith("YouTube") for s in data["not_included"])
    assert "tok-secret" not in json.dumps(data)


@pytest.mark.parametrize("status,detail", [
    ("absent", "the YouTube downloader is not installed here"),
    ("error", "the YouTube downloader's records could not be opened (OperationalError)"),
])
def test_a_ytdl_store_that_did_not_answer_says_why(app, monkeypatch, status, detail):
    monkeypatch.setattr(ytdl, "subject_rows",
                        lambda u, **k: _ytdl_envelope(status, detail, tables={}), raising=False)
    conn = _conn(app)
    try:
        data = subject_data.collect(conn, "jsmith")
    finally:
        conn.close()
    assert not any(t.startswith("ytdl") for t in data["tables"])
    assert f"YouTube requests, downloads and rights confirmations: {detail}." in data["not_included"]


def test_a_missing_helper_is_said_in_not_included(app, monkeypatch):
    monkeypatch.delattr(ytdl, "subject_rows", raising=False)
    conn = _conn(app)
    try:
        data = subject_data.collect(conn, "jsmith")
    finally:
        conn.close()
    assert any(s.startswith("YouTube requests") for s in data["not_included"])


def test_forget_shares_pseudonymises_only_that_person(app, tmp_path):
    shares = _client_shares(tmp_path)
    conn = _conn(app)
    try:
        out = subject_data.forget_shares("jsmith", conn=conn, path=shares)
        stand_in = db.pseudonym(conn, "jsmith")
    finally:
        conn.close()
    assert out == {"ok": True, "client_folders": 1, "client_folder_items": 1}
    check = sqlite3.connect(shares)
    try:
        assert check.execute("SELECT created_by FROM client_folders ORDER BY id").fetchall() == [
            (stand_in,), ("alice",)]
        assert check.execute("SELECT added_by FROM client_folder_items ORDER BY id").fetchall() == [
            (stand_in,), ("alice",)]
        # the link still works: the token is untouched
        assert check.execute("SELECT token FROM client_folders WHERE id=1").fetchone() == (
            "tok-secret-1",)
    finally:
        check.close()


def test_forget_shares_raises_when_the_name_stays(tmp_path):
    # Review point 3: delete_user_everywhere ignores the return value, so a
    # quiet {"ok": False} was a finished delete with the name still there.
    shares = _client_shares(tmp_path)
    with pytest.raises(subject_data.ForgetSharesFailed):
        subject_data.forget_shares("jsmith", path=shares)
    check = sqlite3.connect(shares)
    try:
        assert check.execute("SELECT created_by FROM client_folders WHERE id=1").fetchone() == (
            "jsmith",)
    finally:
        check.close()
    # nothing to forget is not a failure
    assert subject_data.forget_shares("jsmith", "deleted-user-x",
                                      path=tmp_path / "absent.db")["ok"] is False
    assert subject_data.forget_shares("jsmith", path=tmp_path / "absent.db")["ok"] is False


def test_forget_shares_keeps_the_salt_it_minted(app, tmp_path):
    # Review point 9: a salt minted on the caller's connection and never
    # committed made the next stand-in for the same person differ.
    shares = _client_shares(tmp_path)
    conn = _conn(app)
    try:
        conn.execute("DELETE FROM meta WHERE key = ?", (db.META_PSEUDONYM_SALT,))
        conn.commit()
        subject_data.forget_shares("jsmith", conn=conn, path=shares)
    finally:
        conn.close()   # no commit here: the caller forgot
    conn = _conn(app)
    try:
        again = db.pseudonym(conn, "jsmith")
    finally:
        conn.close()
    check = sqlite3.connect(shares)
    try:
        assert check.execute("SELECT created_by FROM client_folders WHERE id=1").fetchone() == (
            again,)
    finally:
        check.close()


# ------------------------------------------------------ review round extras

def test_a_person_with_only_sign_in_records_can_be_exported(app, browsers):
    # Review point 6: a NAS account that never reported has no machines row
    # and no known_editors row, but its sign-ins are records about it.
    browsers("lee")
    owen = browsers("owen")
    data = _export(owen.client.post("/api/v1/admin/users/lee/export", headers=owen.h))
    assert data["tables"].get("sessions.auth_sessions")


def test_a_refused_export_does_not_use_up_the_hour(app, browsers, monkeypatch):
    _seed(app)
    owen = browsers("owen")
    monkeypatch.setattr(subject_data_api, "MAX_EXPORT_BYTES", 10)
    for _ in range(subject_data_api.EXPORTS_PER_HOUR + 1):
        assert owen.client.post("/api/v1/admin/users/jsmith/export",
                                headers=owen.h).status_code == 413
    monkeypatch.setattr(subject_data_api, "MAX_EXPORT_BYTES", 50 * 1024 * 1024)
    assert owen.client.post("/api/v1/admin/users/jsmith/export",
                            headers=owen.h).status_code == 200


def test_admin_exports_do_not_use_up_the_persons_own(app, browsers):
    _seed(app)
    owen = browsers("owen")
    for _ in range(subject_data_api.EXPORTS_PER_HOUR):
        assert owen.client.post("/api/v1/admin/users/jsmith/export",
                                headers=owen.h).status_code == 200
    assert owen.client.post("/api/v1/admin/users/jsmith/export",
                            headers=owen.h).status_code == 429
    jsmith = browsers("jsmith")
    assert jsmith.client.post("/api/v1/me/export", headers=jsmith.h).status_code == 200


def test_the_persons_own_413_is_a_sentence_they_can_act_on(app, browsers, monkeypatch):
    _seed(app)
    monkeypatch.setattr(subject_data_api, "MAX_EXPORT_BYTES", 10)
    jsmith = browsers("jsmith")
    resp = jsmith.client.post("/api/v1/me/export", headers=jsmith.h)
    assert resp.status_code == 413
    assert "Erase" not in resp.json()["detail"]
    assert "Ask an admin" in resp.json()["detail"]


def test_a_plain_form_refusal_is_a_page_not_json(app, browsers, monkeypatch):
    _seed(app)
    monkeypatch.setattr(subject_data_api, "MAX_EXPORT_BYTES", 10)
    jsmith = browsers("jsmith")
    resp = jsmith.client.post("/api/v1/me/export", data={"csrf": jsmith.csrf})
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("text/html")
    assert 'href="/account"' in resp.text and "Ask an admin" in resp.text
    owen = browsers("owen")
    resp = owen.client.post("/api/v1/admin/users/nobody/export", data={"csrf": owen.csrf})
    assert resp.status_code == 404 and 'href="/admin/users"' in resp.text


def test_the_size_cap_stops_encoding_early():
    # Review point 8: the cap is checked while encoding, not after the whole
    # string exists.
    big = {"tables": {"editor_media": [{"rel_path": "x" * 100}] * 10_000}}
    full = len(subject_data.to_json_bytes(big))
    with pytest.raises(subject_data.ExportTooLarge) as caught:
        subject_data.to_json_bytes(big, max_bytes=1000)
    assert caught.value.args[0] < 2000 < full
    assert subject_data.to_json_bytes(big, max_bytes=full) == subject_data.to_json_bytes(big)


def test_no_em_dash_in_what_a_person_reads():
    texts = list(subject_data.NOT_INCLUDED) + [
        v for k, v in vars(subject_data_api).items()
        if k.isupper() and isinstance(v, str)]
    for text in texts:
        assert EM_DASH not in text
