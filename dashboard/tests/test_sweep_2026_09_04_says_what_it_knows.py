"""Usability + resilience sweep 2026-09-04, wave 3: the machine says what it
knows (dashboard half).

One section per finding, each pinning the PROPERTY rather than the wording:

* DCORE-8  a throttled sign-in says HOW LONG, on both routes and on the page.
* DCORE-9  an expired session on the dashboard's own API is a 401 that names
           itself and points at the login page.
* DCORE-13 a pushed update, a resume and an ask-why say what will happen and
           when, including for a computer nobody has heard from in days.
* DCORE-14 revoking a fleet token names the computers it stops.
* DCORE-16 one folder Syncthing refuses does not cost the rest of the fleet
           its enforce cycle, and what was held is readable off a page.
* REL-16   the roll-back is not recall-only, and every kind's row carries the
           machines-running count (present and EMPTY when nothing reports it).
* APP-16   a package record carries a "what's new" line, unsigned, and it
           reaches the upgrade offer.
* CYT-3    sync_guard.youtube_import is stored per machine and rendered.
* RES-4    an undo parked because no project is open is not a failure.
* RES-6    the cards agent's state comes with the reason for it.
* BROLL-8  the fleet batch LIST is carved out of the login gate; the prefix
           around it is not.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import ed25519, release_trust
from ccsync_dashboard.api import (
    build_editors_view,
    build_packages_view,
    build_report_tokens_view,
)
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
SHARED = "sekrit"
NOW = "2026-09-04T12:00:00+00:00"

TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")
PUBLISHED_AT = "2026-09-04T10:00:00Z"


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "sweep.db"),
        report_token=SHARED,
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,),
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn, settings
        conn.close()


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def report(client, token=SHARED, editor="jsmith", machine="EDIT-PC", **extra):
    body = {
        "editor_name": editor,
        "machine": machine,
        "companion_version": "0.9.66",
        "platform": "windows",
        "reported_at": NOW,
        "lanes": [{"name": "lane_a_video_up", "state": "idle"}],
    }
    body.update(extra)
    return client.post(
        "/api/v1/report", json=body,
        headers={"X-CCSync-Token": token,
                 "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)})


# ------------------------------------------------------------------ DCORE-8

def test_a_throttled_signin_says_how_long_and_sets_retry_after(env, monkeypatch):
    client, _conn, _settings = env
    # The budget is real (sessions.LoginAttempts): six wrong passwords put a
    # measurable wait on the clock rather than a mocked one.
    for _ in range(6):
        client.post("/api/v1/login", json={"username": "owen", "password": "wrong"})
    resp = client.post("/api/v1/login", json={"username": "owen", "password": "pw"})
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail.startswith("Too many sign-in attempts. Try again in ")
    assert detail.endswith(".")
    # The number the route already had, and the header a client can obey.
    assert int(resp.headers["Retry-After"]) >= 1
    # /verify is the tray's door and carries the same answer.
    verify = client.post("/api/v1/verify", json={"username": "owen", "password": "pw"})
    assert verify.status_code == 429
    assert "Try again in" in verify.json()["detail"]
    assert "Retry-After" in verify.headers


@pytest.mark.parametrize("seconds,phrase", [
    (0.0, "a minute"), (30.0, "a minute"), (60.0, "a minute"),
    (61.0, "2 minutes"), (360.0, "6 minutes"), (3600.0, "about an hour"),
])
def test_the_wait_is_worded_and_rounded_up(seconds, phrase):
    assert auth.throttle_wait_phrase(seconds) == phrase
    # Never "retry now" while the budget still refuses.
    assert int(auth.throttle_headers(seconds)["Retry-After"]) >= 1


def test_the_login_page_shows_the_wait(env):
    client, _conn, _settings = env
    for _ in range(6):
        client.post("/login", data={"username": "owen", "password": "wrong"},
                    follow_redirects=False)
    page = client.post("/login", data={"username": "owen", "password": "pw"},
                       follow_redirects=False)
    assert "Too many sign-in attempts" in page.text


# ------------------------------------------------------------------ DCORE-9

def test_an_expired_session_on_the_api_names_itself(env):
    client, _conn, _settings = env
    resp = client.get("/api/v1/admin/packages")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"] == "Your sign-in has expired. Sign in again."
    # ...and where to go. The ?next= is the caller's, from the page it is on.
    assert body["login"] == "/login"


def test_the_mounted_apps_keep_their_own_401_wording(env):
    client, _conn, _settings = env
    resp = client.get("/broll/api/anything")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "login required"


def test_assignments_js_navigates_on_401_rather_than_toasting():
    js = (Path(__file__).resolve().parents[1] / "static" / "assignments.js").read_text(
        encoding="utf-8")
    assert "function signedOut(err)" in js
    assert "err.status !== 401" in js
    # Every rejection path consults it before it toasts.
    assert js.count("signedOut(err)") >= 4
    assert "?next=" in js


# ----------------------------------------------------------------- DCORE-13

def test_a_pushed_update_says_when_it_will_apply(env):
    client, conn, _settings = env
    report(client)
    as_admin(client)
    dbmod.insert_companion_package(
        conn, version="0.9.67", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW)
    conn.commit()
    resp = client.post("/api/v1/admin/machines/jsmith/EDIT-PC/update",
                       json={"version": "0.9.67"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["queued_for"] == "jsmith/EDIT-PC"
    assert "next report" in body["applies"]
    assert body["pending_before"] is False
    # A second click is a re-arm, and says so rather than reading as new.
    again = client.post("/api/v1/admin/machines/jsmith/EDIT-PC/update",
                        json={"version": "0.9.67"})
    assert again.json()["pending_before"] is True


def test_a_machine_nobody_has_heard_from_is_not_promised_thirty_seconds(env):
    client, conn, _settings = env
    report(client)
    conn.execute("UPDATE machine_state SET reported_at=? WHERE machine='EDIT-PC'",
                 ("2026-08-20T12:00:00+00:00",))
    # CR-191: the push refuses a version this channel does not carry, so the
    # build has to exist before the delivery wording can be asked about.
    dbmod.insert_companion_package(
        conn, version="0.9.67", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW)
    conn.commit()
    as_admin(client)
    body = client.post("/api/v1/admin/machines/jsmith/EDIT-PC/update",
                       json={"version": "0.9.67"}).json()
    assert body["stale"] is True
    assert "days ago" in body["applies"]
    assert "usually within" not in body["applies"]


def test_ask_why_answers_with_the_same_shape(env):
    client, conn, _settings = env
    report(client)
    as_admin(client)
    body = client.post("/api/v1/admin/machines/jsmith/EDIT-PC/ask-why").json()
    assert body["queued_for"] == "jsmith/EDIT-PC"
    assert body["pending_before"] is False
    assert "next report" in body["applies"]
    # The ASK is not cleared by delivery, so a second click knows.
    assert client.post(
        "/api/v1/admin/machines/jsmith/EDIT-PC/ask-why").json()["pending_before"] is True


def test_resume_answers_with_the_same_shape(env):
    client, conn, _settings = env
    report(client, sync_guard={"lane_b_breaker": {"tripped": True, "reason": "nas gone"}})
    as_admin(client)
    body = client.post("/api/v1/admin/machines/jsmith/EDIT-PC/resume-lane-b").json()
    assert body["queued_for"] == "jsmith/EDIT-PC"
    assert "next report" in body["applies"]
    assert body["pending_before"] is False


# ----------------------------------------------------------------- DCORE-14

def test_revoking_a_token_names_the_computers_it_stops(env):
    client, conn, _settings = env
    token, row = dbmod.create_editor_report_token(conn, "jsmith", created_by="owen")
    conn.commit()
    assert report(client, token=token).status_code == 200
    assert report(client, token=token, machine="EDIT-LAPTOP").status_code == 200

    view = build_report_tokens_view(conn)
    entry = next(t for t in view["tokens"] if t["token_id"] == row["token_id"])
    assert sorted(entry["machine_names"]) == ["jsmith/EDIT-LAPTOP", "jsmith/EDIT-PC"]

    as_admin(client)
    resp = client.delete(f"/api/v1/admin/report-tokens/{row['token_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["machines"]) == ["jsmith/EDIT-LAPTOP", "jsmith/EDIT-PC"]
    assert "jsmith/EDIT-PC" in body["detail"]
    assert "stop reporting" in body["detail"]


def test_a_token_no_machine_used_says_so_rather_than_nothing(env):
    client, conn, _settings = env
    _token, row = dbmod.create_editor_report_token(conn, "jsmith", created_by="owen")
    conn.commit()
    as_admin(client)
    body = client.delete(f"/api/v1/admin/report-tokens/{row['token_id']}").json()
    assert body["machines"] == []
    assert "No computer" in body["detail"]


def test_the_shared_token_records_no_token_id(env):
    client, conn, _settings = env
    report(client, token=SHARED)
    row = conn.execute("SELECT auth_kind, token_id FROM report_auth").fetchone()
    assert row["auth_kind"] == "shared"
    assert row["token_id"] == ""


# ----------------------------------------------------------------- DCORE-16

def test_one_bad_folder_does_not_cost_the_cycle(env, monkeypatch):
    """The enforce loop applies what it can and NAMES what it could not."""
    from ccsync_dashboard import collector as collectormod

    client, conn, settings = env
    del client

    class Client:
        def __init__(self):
            self.applied = []

        def config(self):
            return {"devices": [{"deviceID": "SERVER", "name": "nas"}], "folders": []}

        def system_status(self):
            return {"myID": "SERVER"}

        def get_folder(self, slug):
            return {"id": slug, "devices": []}

        def put_folder(self, slug, body):
            if slug == "bad":
                raise RuntimeError("folder is paused")
            self.applied.append(slug)

    del conn, monkeypatch
    fake = Client()
    poller = collectormod.Collector(settings, fake, now_fn=lambda: NOW)
    plans = [("a", {"SERVER"}, set()), ("bad", {"SERVER"}, set()),
             ("c", {"SERVER"}, set())]
    note = poller._enforce_loop(plans, skip_removals=False)
    assert fake.applied == ["a", "c"]
    assert "applied 2 of 3" in note
    assert "folder is paused" in note


def test_a_held_cycle_is_readable_off_a_page(env):
    client, conn, _settings = env
    dbmod.record_poll_run(conn, "enforce", NOW, NOW, True,
                          "applied 9 of 40 folder(s); syncthing refused the rest")
    dbmod.record_poll_run(conn, "config", NOW, NOW, True, None)
    conn.commit()
    notes = dbmod.enforce_notes(conn)
    assert [n["note"] for n in notes] == [
        "applied 9 of 40 folder(s); syncthing refused the rest"]
    assert notes[0]["at"] == NOW
    # ...and it is in the two contexts D4 renders.
    as_admin(client)
    page = client.get("/partials/admin/diagnostics")
    assert page.status_code == 200


# ------------------------------------------------------------------- REL-16

def test_every_kind_carries_machines_running_and_says_when_it_cannot_tell(env):
    client, conn, settings = env
    report(client)
    dbmod.insert_companion_package(
        conn, version="0.9.66", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW)
    dbmod.insert_companion_package(
        conn, version="1.0.40", platform="windows", filename="o.exe",
        sha256="b" * 64, size_bytes=1, published_by="owen", now=NOW, kind="onboard")
    conn.commit()
    view = build_packages_view(conn, settings)
    companion = next(p for p in view["packages"] if p["kind"] == "companion")
    onboard = next(p for p in view["packages"] if p["kind"] == "onboard")
    assert companion["machines_running"] == 1
    assert companion["machines_running_known"] is True
    # PRESENT AND EMPTY: nothing reports which installer a computer used.
    assert onboard["machines_running"] == 0
    assert onboard["machines_running_known"] is False


def test_the_rollback_works_without_a_recall(env):
    client, conn, _settings = env
    report(client)
    for version in ("0.9.64", "0.9.66"):
        dbmod.insert_companion_package(
            conn, version=version, platform="windows", filename=f"c{version}.exe",
            sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW)
    dbmod.set_current_package(conn, "windows", "0.9.66", "companion")
    conn.commit()
    as_admin(client)
    # Nothing was ever retracted here: this is "put the fleet back on 0.9.64".
    resp = client.post(
        "/api/v1/admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64")
    assert resp.status_code == 200
    assert resp.json()["machines"] == ["jsmith/EDIT-PC"]
    assert dbmod.pending_machine_request(conn, "jsmith", "EDIT-PC")["update"] == "0.9.64"


def test_rolling_a_non_companion_kind_back_says_why_not(env):
    client, conn, _settings = env
    dbmod.insert_companion_package(
        conn, version="1.0.40", platform="windows", filename="o.exe",
        sha256="b" * 64, size_bytes=1, published_by="owen", now=NOW, kind="onboard")
    conn.commit()
    as_admin(client)
    resp = client.post(
        "/api/v1/admin/packages/windows/1.0.39/roll-fleet-back?kind=onboard&to=1.0.40")
    assert resp.status_code == 409
    assert "no computer reports which onboard" in resp.json()["detail"].lower()


# ------------------------------------------------------------------- APP-16

def signed_query(kind, platform, version, body, min_version="0.0.0"):
    record = {
        "kind": kind, "platform": platform, "version": version,
        "filename": f"ccsync-companion-{version}.exe",
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body), "min_version": min_version,
        "published_at": PUBLISHED_AT, "signed_binary": False,
    }
    signature = base64.b64encode(
        ed25519.sign(TEST_SEED, release_trust.canonical_record(record))).decode("ascii")
    return (f"&signature={quote(signature, safe='')}"
            f"&pubkey_id={release_trust.pubkey_id(TEST_PUBKEY)}"
            f"&min_version={min_version}&published_at={quote(PUBLISHED_AT, safe='')}"
            f"&signed_binary=0")


def test_notes_publish_store_and_reach_the_offer(env):
    client, conn, _settings = env
    as_admin(client)
    body = b"exe-bytes"
    sha = hashlib.sha256(body).hexdigest()
    note = "proxy downloads resume by themselves after a drive comes back"
    resp = client.put(
        f"/api/v1/admin/packages/windows/0.9.67?sha256={sha}&make_current=1&prune=0"
        f"&notes={quote(note, safe='')}" + signed_query("companion", "windows", "0.9.67", body),
        content=body, headers={"Content-Type": "application/octet-stream"})
    assert resp.status_code == 200, resp.text
    row = dbmod.get_package(conn, "windows", "0.9.67")
    assert row["notes"] == note
    entry = next(p for p in resp.json()["view"]["packages"] if p["version"] == "0.9.67")
    assert entry["notes"] == note
    # ...and the companion's own offer carries it, additively.
    offer = report(client, companion_version="0.9.60").json()["upgrade"]
    assert offer["version"] == "0.9.67"
    assert offer["notes"] == note


def test_notes_are_outside_the_signature(env):
    """A record with a note verifies byte for byte like one without: the
    canonical bytes are the signed field list and nothing else (REL-7)."""
    record = {
        "kind": "companion", "platform": "windows", "version": "0.9.67",
        "filename": "ccsync-companion-0.9.67.exe", "sha256": "a" * 64,
        "size_bytes": 9, "min_version": "0.0.0",
        "published_at": PUBLISHED_AT, "signed_binary": False,
    }
    with_note = dict(record, notes="anything at all")
    assert release_trust.canonical_record(with_note) == release_trust.canonical_record(record)


def test_a_note_is_one_bounded_line():
    assert dbmod.package_notes("two\nlines   here") == "two lines here"
    assert len(dbmod.package_notes("x" * 5000)) == dbmod.MAX_PACKAGE_NOTES_CHARS
    assert dbmod.package_notes(None) == ""


# -------------------------------------------------------------------- CYT-3

def test_youtube_import_is_stored_per_machine_and_rendered(env):
    client, conn, _settings = env
    report(client, sync_guard={"youtube_import": {
        "state": "no-project-match", "reason": "no server folder for FF5",
        "pending": 8, "at": NOW}})
    view = build_editors_view(conn, NOW)
    machine = view["editors"][0]
    assert machine["youtube_import"]["state"] == "no-project-match"
    assert machine["youtube_import"]["pending"] == 8
    # A section that is no longer sent CLEARS: a stale "8 waiting" is worse
    # than silence (the latch rule every guard sub-section follows).
    report(client, sync_guard={"lane_b_breaker": {"tripped": False}})
    assert build_editors_view(conn, NOW)["editors"][0]["youtube_import"] == {}


def test_an_unknown_youtube_import_state_does_not_422_the_report(env):
    client, _conn, _settings = env
    resp = report(client, sync_guard={"youtube_import": {
        "state": "a-state-from-the-future", "pending": 1, "at": NOW}})
    assert resp.status_code == 200


# --------------------------------------------------------------------- RES-4

def test_a_parked_undo_is_not_a_failure(env):
    client, conn, _settings = env
    report(client)
    request_id = dbmod.request_resolve_undo(
        conn, "jsmith", "EDIT-PC", "j1", "FF5", "owen", NOW)
    conn.commit()
    assert request_id
    resp = report(client, resolve_undo_applied=[
        {"id": request_id, "ok": False, "state": "parked",
         "detail": "no project open in Resolve"}])
    assert resp.status_code == 200
    row = dbmod.resolve_undos_for_machine(conn, "jsmith", "EDIT-PC")[0]
    assert row["state"] == "parked"
    # NOT retired: the command keeps riding until the machine actually does it.
    assert row["applied_at"] is None
    assert dbmod.pending_resolve_undos(conn, "jsmith", "EDIT-PC")

    as_admin(client)
    view = client.get(
        "/api/v1/admin/machines/jsmith/EDIT-PC/resolve-journals").json()
    assert view["requests"][0]["state_sentence"] == "no project open in Resolve"


def test_the_straddle_flag_lands_as_parked(env):
    client, conn, _settings = env
    report(client)
    request_id = dbmod.request_resolve_undo(
        conn, "jsmith", "EDIT-PC", "j1", "FF5", "owen", NOW)
    conn.commit()
    # A companion that cannot risk the new state sends retrying + parked.
    assert report(client, resolve_undo_applied=[
        {"id": request_id, "ok": False, "state": "retrying", "parked": True}
    ]).status_code == 200
    row = dbmod.resolve_undos_for_machine(conn, "jsmith", "EDIT-PC")[0]
    assert row["state"] == "parked"
    assert row["applied_at"] is None


# --------------------------------------------------------------------- RES-6

def test_the_cards_agent_says_why_it_is_not_running(env):
    client, conn, _settings = env
    resp = report(client, capabilities={"cards_agent": {
        "connected": False, "state": "credential_refused",
        "gate_state": "refused", "detail": "the tunnel answered 401",
        "last_poll_at": NOW, "last_http_status": 401}})
    assert resp.status_code == 200
    caps = build_editors_view(conn, NOW)["editors"][0]["capabilities"]["cards_agent"]
    assert caps["state"] == "credential_refused"
    assert caps["gate_state"] == "refused"
    assert caps["detail"] == "the tunnel answered 401"
    assert caps["last_http_status"] == 401
    assert caps["last_poll_at"] == NOW


def test_a_companion_too_old_to_say_reads_as_unknown_not_ok(env):
    client, conn, _settings = env
    report(client, capabilities={"cards_agent": {"connected": True, "state": "running"}})
    caps = build_editors_view(conn, NOW)["editors"][0]["capabilities"]["cards_agent"]
    assert caps["gate_state"] == ""
    assert caps["detail"] == ""
    assert caps["last_poll_at"] is None
    assert caps["last_http_status"] is None


# ------------------------------------------------------------------ BROLL-8

def test_the_fleet_batch_list_is_carved_out_of_the_login_gate(env):
    client, _conn, _settings = env
    headers = {"X-CCSync-Token": SHARED}
    # Carved out: it reaches the mount (whatever the mount answers), and is
    # not turned into a login page.
    for path in ("/broll/api/fleet/ingest/batches",
                 "/broll/api/fleet/ingest/batches/"):
        resp = client.get(path, headers=headers, follow_redirects=False)
        assert resp.status_code != 303, path
        assert "<html" not in resp.text.lower()[:200], path
    # Nothing broader, and no second door onto creation.
    assert client.get("/broll/api/fleet/", headers=headers,
                      follow_redirects=False).status_code in (303, 401)
    assert client.post("/broll/api/fleet/ingest/batches", headers=headers,
                       follow_redirects=False).status_code in (303, 401)
    # ...and with no credential at all it is still refused.
    assert client.get("/broll/api/fleet/ingest/batches",
                      follow_redirects=False).status_code in (303, 401)
