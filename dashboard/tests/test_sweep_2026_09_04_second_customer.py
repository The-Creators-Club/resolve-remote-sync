"""Wave 5 of the usability + resilience sweep: the second customer.

DCORE-1  a disabled or absent account's computers are turned away.
DCORE-4  SUSPEND / RESUME: fleet state, not a login flag, on every site.
DCORE-5  ARCHIVE PROJECT: reversible, audited, deletes nothing.
DCORE-6  fleet membership on a local site is the local account, not a skip.
DCORE-12 eviction never deletes a registry row that still owes something.
OPS-2    an account can be created with no SSH key, and the wizard sends one.
UX-13    the no-NAS-password copy names DASH_NAS_PW and where to set it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR_ID, SERVER_ID, FakeSyncthing

SECRET = "test-secret"
TOKEN = "sekrit"
SLUG = "2025-ff4-nuclear"
KEY = "ssh-ed25519 QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE= jsmith@laptop"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def report_body(editor="jsmith", machine="EDIT-PC"):
    return {
        "editor_name": editor,
        "machine": machine,
        "companion_version": "0.9.66",
        "reported_at": "2026-09-04T10:00:00+00:00",
        "lanes": [
            {"name": "lane_a_video_up", "state": "idle", "queued": 0, "transferring": 0,
             "last_error": None, "last_sync": None, "detail": None},
        ],
    }


def report_headers(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


@pytest.fixture
def smb_env(tmp_path):
    """The SHIPPED shape: DASH_AUTH_METHOD=smb, no NAS credential here."""
    app = create_app(Settings(db_path=str(tmp_path / "smb.db"), report_token=TOKEN,
                              session_secret=SECRET, admin_users=frozenset({"owen"})))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "smb.db")
        yield client, conn
        conn.close()


@pytest.fixture
def local_env(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "local.db"), report_token=TOKEN,
                              session_secret=SECRET, admin_users=frozenset({"owen"}),
                              auth_method="local"))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "local.db")
        yield client, conn
        conn.close()


# ----------------------------------------------------------------- DCORE-1

def test_a_disabled_account_is_turned_away_at_the_report_path(local_env):
    client, conn = local_env
    as_user(client, "owen")
    assert client.post("/api/v1/admin/users",
                       json={"username": "jsmith",
                             "password": "correct-horse-battery-new"}).status_code == 200
    assert client.post("/api/v1/report", json=report_body(),
                       headers=report_headers()).status_code == 200

    assert client.post("/api/v1/admin/users/jsmith/disable",
                       json={"disabled": True}).status_code == 200
    resp = client.post("/api/v1/report", json=report_body(), headers=report_headers())
    assert resp.status_code == 401
    assert "disabled" in resp.json()["detail"]

    refusals = dbmod.report_refusal_map(conn)
    assert refusals[("jsmith", "EDIT-PC")]["reason"] == "this account has been disabled"

    # ...and enabling gives it straight back.
    assert client.post("/api/v1/admin/users/jsmith/disable",
                       json={"disabled": False}).status_code == 200
    assert client.post("/api/v1/report", json=report_body(),
                       headers=report_headers()).status_code == 200


def test_an_account_no_local_site_has_is_turned_away(local_env):
    """ABSENT, not merely disabled: the account was deleted at the NAS or
    never existed, and the identity token outlives it by a century."""
    client, conn = local_env
    as_user(client, "owen")
    client.post("/api/v1/admin/users", json={"username": "someone",
                                             "password": "correct-horse-battery-new"})
    resp = client.post("/api/v1/report", json=report_body(), headers=report_headers())
    assert resp.status_code == 401
    assert "disabled" in resp.json()["detail"]


def test_a_local_site_with_no_accounts_yet_does_not_turn_the_fleet_away(local_env):
    """The bootstrap window: auth_method=local and nobody created yet must
    not 401 a fleet that has been reporting for a year."""
    client, _conn = local_env
    assert client.post("/api/v1/report", json=report_body(),
                       headers=report_headers()).status_code == 200


def test_disable_is_audited(local_env):
    client, conn = local_env
    as_user(client, "owen")
    client.post("/api/v1/admin/users", json={"username": "jsmith",
                                             "password": "correct-horse-battery-new"})
    client.post("/api/v1/admin/users/jsmith/disable", json={"disabled": True})
    actions = [r["action"] for r in dbmod.fetch_audit(conn, limit=20)]
    assert "user.disable" in actions


def test_the_disable_confirm_names_what_survives():
    """DCORE-1(b): the alternative to removing their devices is saying
    exactly what does NOT happen."""
    text = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "templates" / "partials" / "admin_users.html").read_text(encoding="utf-8")
    # Shortened to fit a phone dialog (M3's 90-character cap, wave 5 gate):
    # the consequence is the confirm's own sentence, the rest of it is the
    # button's title.
    assert "Their computers keep their projects until you untick them" in text
    assert "its computers are turned away when they report" in text


# ----------------------------------------------------------------- DCORE-4

def test_suspend_works_on_an_smb_site_and_turns_the_computers_away(smb_env):
    client, conn = smb_env
    as_user(client, "owen")
    assert client.post("/api/v1/report", json=report_body(),
                       headers=report_headers()).status_code == 200

    resp = client.post("/api/v1/admin/users/jsmith/suspend",
                       json={"suspended": True, "reason": "back in March"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["suspended"] is True

    refused = client.post("/api/v1/report", json=report_body(), headers=report_headers())
    assert refused.status_code == 401
    assert "suspended" in refused.json()["detail"]
    assert (dbmod.report_refusal_map(conn)[("jsmith", "EDIT-PC")]["reason"]
            == "this account is suspended")

    assert client.post("/api/v1/admin/users/jsmith/suspend",
                       json={"suspended": False}).status_code == 200
    assert client.post("/api/v1/report", json=report_body(),
                       headers=report_headers()).status_code == 200


def test_suspend_leaves_the_plan_alone(smb_env):
    client, conn = smb_env
    as_user(client, "owen")
    now = dbmod.utcnow_iso()
    dbmod.record_known_editor(conn, "jsmith", "admin", now)
    dbmod.add_selection(conn, "jsmith", SLUG, "owen", now, machine="EDIT-PC")
    conn.commit()

    client.post("/api/v1/admin/users/jsmith/suspend", json={"suspended": True})
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == [SLUG]
    assert "jsmith" in dbmod.suspended_editors(conn)

    client.post("/api/v1/admin/users/jsmith/suspend", json={"suspended": False})
    assert dbmod.suspended_editors(conn) == set()
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == [SLUG]


def test_an_admin_cannot_suspend_themselves(smb_env):
    client, conn = smb_env
    as_user(client, "owen")
    dbmod.record_known_editor(conn, "owen", "admin")
    conn.commit()
    resp = client.post("/api/v1/admin/users/owen/suspend", json={"suspended": True})
    assert resp.status_code == 409


def test_suspending_an_unknown_editor_is_a_404(smb_env):
    client, _conn = smb_env
    as_user(client, "owen")
    assert client.post("/api/v1/admin/users/nobody/suspend",
                       json={"suspended": True}).status_code == 404


def test_the_users_view_and_the_fleet_grid_both_say_suspended(smb_env):
    client, conn = smb_env
    as_user(client, "owen")
    client.post("/api/v1/report", json=report_body(), headers=report_headers())
    client.post("/api/v1/admin/users/jsmith/suspend", json={"suspended": True})

    view = client.get("/api/v1/admin/users").json()
    assert view["suspended"] == ["jsmith"]
    assert view["suspensions"]["jsmith"]["by"] == "owen"

    page = client.get("/")
    assert "[ SUSPENDED ]" in page.text


# --------------------------------------------------- DCORE-4 / DCORE-5 enforce

@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


@pytest.fixture
def collector(fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k")
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def folder_devices(fake):
    folder = next(f for f in fake.state["folders"] if f["id"] == SLUG)
    return {d["deviceID"] for d in folder.get("devices", [])}


def test_the_enforce_cycle_unshares_a_suspended_editor(conn, fake, collector):
    collector.run_cycle(conn, ["config", "enforce"])   # seeds jsmith on SLUG
    assert EDITOR_ID in folder_devices(fake)

    dbmod.suspend_editor(conn, "jsmith", by="owen")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID not in folder_devices(fake)

    dbmod.unsuspend_editor(conn, "jsmith")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID in folder_devices(fake), "RESUME puts back exactly what was there"


def test_the_enforce_cycle_unshares_an_archived_project(conn, fake, collector):
    collector.run_cycle(conn, ["config", "enforce"])
    assert EDITOR_ID in folder_devices(fake)

    assert dbmod.archive_project(conn, SLUG, by="owen") is True
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert folder_devices(fake) == {SERVER_ID} | (folder_devices(fake) - {SERVER_ID, EDITOR_ID})
    assert EDITOR_ID not in folder_devices(fake)

    # ...and the config pass must NOT resurrect it: the folder is still there,
    # which is the whole point of "nothing is deleted".
    collector.run_cycle(conn, ["config"])
    row = conn.execute("SELECT active, archived_at FROM projects WHERE slug=?",
                       (SLUG,)).fetchone()
    assert row["active"] == 0 and row["archived_at"]

    assert dbmod.unarchive_project(conn, SLUG) is True
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID in folder_devices(fake)


# ----------------------------------------------------------------- DCORE-5

def test_archive_is_admin_only_reversible_and_audited(smb_env):
    client, conn = smb_env
    now = dbmod.utcnow_iso()
    dbmod.upsert_project(conn, SLUG, "2025/FF4/Nuclear", "/mnt/x", now)
    dbmod.record_known_editor(conn, "jsmith", "admin", now)
    dbmod.add_selection(conn, "jsmith", SLUG, "owen", now, machine="EDIT-PC")
    conn.commit()

    as_user(client, "jsmith")
    assert client.post(f"/api/v1/projects/{SLUG}/archive",
                       json={"archived": True}).status_code == 403

    as_user(client, "owen")
    resp = client.post(f"/api/v1/projects/{SLUG}/archive", json={"archived": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["editors"] == ["jsmith"]
    assert conn.execute("SELECT active FROM projects WHERE slug=?",
                        (SLUG,)).fetchone()["active"] == 0
    # nothing was deleted: the tick is still there
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == [SLUG]

    assert client.post(f"/api/v1/projects/{SLUG}/archive",
                       json={"archived": True}).status_code == 409
    assert client.post(f"/api/v1/projects/{SLUG}/archive",
                       json={"archived": False}).status_code == 200
    assert conn.execute("SELECT active FROM projects WHERE slug=?",
                        (SLUG,)).fetchone()["active"] == 1

    actions = [r["action"] for r in dbmod.fetch_audit(conn, limit=20)]
    assert "project.archive" in actions and "project.unarchive" in actions


def test_archiving_an_unknown_project_is_a_404(smb_env):
    client, _conn = smb_env
    as_user(client, "owen")
    assert client.post("/api/v1/projects/nope/archive",
                       json={"archived": True}).status_code == 404


def test_the_create_form_says_who_may_create_a_project():
    text = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "templates" / "partials" / "project_setup_panel.html"
            ).read_text(encoding="utf-8")
    assert "Anyone signed in can create a project" in text
    assert "ARCHIVE" in text


# ----------------------------------------------------------------- DCORE-6

def test_verify_refuses_a_local_account_that_is_not_a_fleet_member(local_env):
    client, conn = local_env
    as_user(client, "owen")
    client.post("/api/v1/admin/users",
                json={"username": "jsmith", "password": "correct-horse-battery-new"})
    client.cookies.clear()

    ok = client.post("/api/v1/verify",
                     json={"username": "jsmith", "password": "correct-horse-battery-new"})
    assert ok.status_code == 200
    assert ok.json()["token"]

    # An account this dashboard does not have gets no identity, even with a
    # password the credential check would accept elsewhere.
    missing = client.post("/api/v1/verify",
                          json={"username": "ghost", "password": "correct-horse-battery-new"})
    assert missing.status_code in (401, 403)

    # ...and a suspended one is refused with the reason, not silently.
    dbmod.suspend_editor(conn, "jsmith", by="owen")
    conn.commit()
    resp = client.post("/api/v1/verify",
                       json={"username": "jsmith", "password": "correct-horse-battery-new"})
    assert resp.status_code == 403
    assert "suspended" in resp.json()["detail"]


def test_the_skip_warning_names_the_real_configuration(smb_env, caplog):
    """No NAS credential on an smb site: the check is skipped, and the log
    line no longer points at DASH_NAS_PW, which is not what this is about."""
    client, _conn = smb_env
    with caplog.at_level("WARNING"):
        client.post("/api/v1/verify", json={"username": "jsmith", "password": "x"})
    assert not any("DASH_NAS_PW is not configured" in r.getMessage()
                   for r in caplog.records)


# ----------------------------------------------------------------- DCORE-12

def test_eviction_keeps_a_registry_row_that_still_owes_something(conn, caplog):
    now = dbmod.utcnow_iso()
    for i in range(3):
        machine = f"BOX-{i}"
        dbmod.upsert_machine(conn, "jsmith", machine, now,
                             syncthing_device_id=(EDITOR_ID if i == 0 else None))
        conn.execute(
            "INSERT INTO machine_state (editor_username, machine, reported_at, received_at) "
            "VALUES (?, ?, ?, ?)", ("jsmith", machine, now, f"2026-09-0{i + 1}T00:00:00+00:00"))
    dbmod.add_selection(conn, "jsmith", SLUG, "owen", now, machine="BOX-1")
    conn.commit()

    with caplog.at_level("WARNING"):
        assert dbmod.evict_extra_machines(conn, "jsmith", keep=1) == 2
    kept = {r["machine"] for r in dbmod.fetch_machines(conn, "jsmith")}
    # BOX-0 still has a Syncthing device and BOX-1 still has a plan: both
    # stay in the registry (and so on the fleet page's LOST list).
    assert kept == {"BOX-0", "BOX-1", "BOX-2"}
    assert any("NOT evicting" in r.getMessage() for r in caplog.records)


def test_eviction_still_removes_a_registry_row_that_owes_nothing(conn):
    now = dbmod.utcnow_iso()
    for i in range(2):
        dbmod.upsert_machine(conn, "jsmith", f"BOX-{i}", now)
        conn.execute(
            "INSERT INTO machine_state (editor_username, machine, reported_at, received_at) "
            "VALUES (?, ?, ?, ?)", ("jsmith", f"BOX-{i}", now,
                                    f"2026-09-0{i + 1}T00:00:00+00:00"))
    conn.commit()
    assert dbmod.evict_extra_machines(conn, "jsmith", keep=1) == 1
    assert {r["machine"] for r in dbmod.fetch_machines(conn, "jsmith")} == {"BOX-1"}


# ------------------------------------------------------------------- OPS-2

def test_the_wizard_can_offer_a_key_and_an_admin_approves_it(local_env):
    client, conn = local_env
    as_user(client, "owen")
    client.post("/api/v1/admin/users",
                json={"username": "jsmith", "password": "correct-horse-battery-new"})
    client.cookies.clear()

    resp = client.post("/api/v1/ssh-key",
                       json={"username": "jsmith", "ssh_pubkey": KEY, "machine": "EDIT-PC"},
                       headers={"X-CCSync-Identity":
                                auth.make_identity_token(SECRET, "jsmith")})
    assert resp.status_code == 200, resp.text
    fingerprint = resp.json()["fingerprint"]
    assert local_users.keys_for(conn, "jsmith") == [], "a queued key grants nothing"

    as_user(client, "owen")
    view = client.get("/api/v1/admin/users").json()
    assert [k["fingerprint"] for k in view["pending_ssh_keys"]] == [fingerprint]

    ok = client.post("/api/v1/admin/users/jsmith/keys/pending/approve",
                     json={"fingerprint": fingerprint})
    assert ok.status_code == 200, ok.text
    assert [k["fingerprint"] for k in local_users.keys_for(conn, "jsmith")] == [fingerprint]
    assert client.get("/api/v1/admin/users").json()["pending_ssh_keys"] == []
    assert "ssh_key.approve" in [r["action"] for r in dbmod.fetch_audit(conn, limit=20)]


def test_a_key_offer_needs_a_matching_identity_token(local_env):
    client, _conn = local_env
    assert client.post("/api/v1/ssh-key",
                       json={"username": "jsmith", "ssh_pubkey": KEY}).status_code == 401
    resp = client.post("/api/v1/ssh-key",
                       json={"username": "jsmith", "ssh_pubkey": KEY},
                       headers={"X-CCSync-Identity":
                                auth.make_identity_token(SECRET, "someone-else")})
    assert resp.status_code == 401


def test_a_suspended_editor_cannot_queue_a_key(local_env):
    client, conn = local_env
    as_user(client, "owen")
    client.post("/api/v1/admin/users",
                json={"username": "jsmith", "password": "correct-horse-battery-new"})
    client.post("/api/v1/admin/users/jsmith/suspend", json={"suspended": True})
    client.cookies.clear()
    resp = client.post("/api/v1/ssh-key",
                       json={"username": "jsmith", "ssh_pubkey": KEY},
                       headers={"X-CCSync-Identity":
                                auth.make_identity_token(SECRET, "jsmith")})
    assert resp.status_code == 403


def test_a_dismissed_key_leaves_the_account_alone(local_env):
    client, conn = local_env
    as_user(client, "owen")
    client.post("/api/v1/admin/users",
                json={"username": "jsmith", "password": "correct-horse-battery-new"})
    fingerprint = local_users.pubkey_fingerprint(KEY)
    dbmod.add_pending_ssh_key(conn, "jsmith", fingerprint, KEY)
    conn.commit()
    resp = client.post("/api/v1/admin/users/jsmith/keys/pending/dismiss",
                       json={"fingerprint": fingerprint})
    assert resp.status_code == 200 and resp.json()["dropped"] is True
    assert local_users.keys_for(conn, "jsmith") == []


def test_creating_a_local_account_without_a_key_is_fine(local_env):
    client, _conn = local_env
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/users",
                       json={"username": "jsmith", "password": "correct-horse-battery-new"})
    assert resp.status_code == 200


# ------------------------------------------------------------ UX-13 / UX-14

def test_the_users_page_names_dash_nas_pw_and_where_to_set_it():
    text = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "templates" / "partials" / "admin_users.html").read_text(encoding="utf-8")
    assert "This dashboard has no NAS password" in text
    assert "DASH_NAS_PW in the container" in text
    assert "/setup" in text
    assert "TRUENAS_PW is not configured" not in text


def test_the_key_field_is_optional_and_the_row_offers_one():
    text = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "templates" / "partials" / "admin_users.html").read_text(encoding="utf-8")
    assert "[ NO SSH KEY ]" in text
    assert "upload and proxy download will not run until a key is added" in text
    assert "[ UPDATE SSH KEY ]" in text
    assert 'name="ssh_pubkey" placeholder="ssh-ed25519 AAAA... user@host" rows="2" required' \
        not in text


# ------------------------------------------------------------------ CMEDIA-1

def test_the_local_work_gate_survives_a_round_trip(smb_env):
    """The scheduler's half of CMEDIA-1: what a machine is busy with ITSELF
    has to be stored, or a machine holding 12 GB of VLM weights ranks as
    idle."""
    from ccsync_dashboard import jobs as jobs_mod

    client, conn = smb_env
    body = report_body()
    body["capabilities"] = {"gpu_present": True,
                            "jobs_gate": {"reason": "local_work",
                                          "detail": "waiting: indexing b-roll"}}
    assert client.post("/api/v1/report", json=body,
                       headers=report_headers()).status_code == 200
    caps = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert caps["jobs_gate"] == {"reason": "local_work",
                                 "detail": "waiting: indexing b-roll"}
    assert jobs_mod.local_work_words(caps) == "waiting: indexing b-roll"
