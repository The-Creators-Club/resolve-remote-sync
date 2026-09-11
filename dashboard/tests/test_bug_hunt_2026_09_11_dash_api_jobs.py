"""Bug hunt 2026-09-11, territory dash-api-jobs (CR-239).

Eight findings across the JSON API, the jobs state machine and the upgrade
channel. Each test here fails at 40f931a and passes now; each names the
finding it pins, because the interesting half of every one of them is the
thing the existing suites are green over:

  dash-api-1           the trash retention clock started at PUBLISH time.
  dash-api-2 + res-fleet-1 + dash-release-jobs-1
                       a cancel that outlived its lease, and one that was
                       never recorded at all.
  dash-api-3           [ ROLL THE FLEET BACK ] delivered nothing, ever.
  dash-api-4           one computer's queue page showed another's project.
  dash-api-5           a +dirty build could never clear a pushed update.
  dash-api-6           suspended meant /report and no other door.
  dash-db-4            the retry guard stopped guarding past 1,000 rows.
  dash-release-jobs-3  the fleet cap was advisory across concurrent claims.
  comp-app-2           nine resolve_health fields dropped in silence.
  comp-resolve-3       the cards refusal cut off after 255 characters.
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api as api_mod
from ccsync_dashboard import auth, db as dbmod, ed25519, release_trust
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
NOW = "2026-09-11T09:00:00+00:00"

TEST_SEED = bytes(range(32))
TEST_PUBKEY = base64.b64encode(ed25519.public_key(TEST_SEED)).decode("ascii")
PUBLISHED_AT = "2026-09-01T12:00:00Z"

MEDIA_INPUTS = {"root": "media", "rel_path": "FF5/a.mp4",
                "out_root": "vault", "out_rel": "Vault/2026/FF5/cache"}


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects),
        report_token=TOKEN, packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,), release_soak_minutes=0,
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn, settings
        conn.close()


def admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def fleet_headers(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, version="0.9.66", editor="jsmith", machine="EDIT-PC", **extra):
    body = {"editor_name": editor, "machine": machine,
            "companion_version": version, "platform": "windows",
            "reported_at": dbmod.utcnow_iso(),
            "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
    body.update(extra)
    return client.post("/api/v1/report", json=body, headers=fleet_headers(editor))


def queue(conn, kind="peaks", **kw):
    job_id = dbmod.create_job(conn, kind, dict(MEDIA_INPUTS), {}, **kw)
    conn.commit()
    return job_id


# ------------------------------------------------------------- dash-api-1

def test_a_trashed_package_is_kept_thirty_days_from_the_DELETE(env):
    """The clock is the deletion, not the publish (dash-api-1).

    The source file is backdated before the delete, which is the state the
    real code reaches on its own: a package published five weeks ago. The
    existing prune test ages the file BY HAND after the delete and is green
    either way.
    """
    client, conn, settings = env
    dbmod.insert_companion_package(
        conn, version="0.9.64", platform="windows",
        filename="ccsync-companion-0.9.64.exe", sha256="a" * 64, size_bytes=3,
        published_by="owen", now=NOW)
    conn.commit()
    path = settings.packages_path() / "windows" / "ccsync-companion-0.9.64.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"old")
    old = time.time() - (api_mod.PACKAGE_TRASH_DAYS + 10) * 86400
    os.utime(path, (old, old))

    resp = admin(client).delete("/api/v1/admin/packages/windows/0.9.64")
    assert resp.status_code == 200, resp.text
    trashed = Path(resp.json()["trashed_to"])
    # The route names a path; the bytes a rollback needs are AT that path.
    assert trashed.exists(), "the delete unlinked the bytes it said it trashed"
    assert trashed.read_bytes() == b"old"


# ------------------------------- dash-api-2 / dash-release-jobs-1 / res-fleet-1

def test_a_cancelled_job_does_not_come_back_when_the_lease_expires(env):
    client, conn, _settings = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC", now=NOW)
    conn.commit()
    assert admin(client).post(f"/api/v1/jobs/{job_id}/cancel").json()["state"] \
        == "requested"

    # The laptop is asleep: it never reads commands.jobs.cancel, and the
    # lease runs out.
    later = "2026-09-11T11:00:00+00:00"
    moved = dbmod.expire_leases(conn, later)
    conn.commit()
    assert [m["state"] for m in moved] == ["failed"]
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == "failed"
    assert "cancelled" in (job["last_error"] or "")
    assert dbmod.queued_jobs(conn) == []
    assert dbmod.claim_next_job(conn, "other", "BOX2") is None


def test_a_cancel_lost_to_a_concurrent_claim_is_not_reported_as_done(env):
    """res-fleet-1: the read is unlocked, so the WRITE has to decide."""
    client, conn, _settings = env
    job_id = queue(conn)

    real_get_job = dbmod.get_job
    claimed = {"done": False}

    def racing_get_job(c, jid):
        job = real_get_job(c, jid)
        if not claimed["done"]:
            # A POST /jobs/claim commits in the window between the read and
            # the write. One interleaving, on a second connection, exactly
            # as two requests would.
            claimed["done"] = True
            other = dbmod.connect(str(_settings.db_path))
            dbmod.claim_job(other, jid, "jsmith", "EDIT-PC")
            other.commit()
            other.close()
        return job

    dbmod.get_job = racing_get_job
    try:
        state = dbmod.request_job_cancel(conn, job_id, "owen")
    finally:
        dbmod.get_job = real_get_job
    conn.commit()

    job = dbmod.get_job(conn, job_id)
    assert job["state"] == "claimed"
    # It fell through to the held branch: the machine IS told to stop.
    assert state == "requested"
    assert job["cancel_requested_at"]
    assert dbmod.pending_job_cancels(conn, "jsmith", "EDIT-PC") == [job_id]


# ------------------------------------------------------------- dash-api-3

def _publish_rows(conn):
    for version in ("0.9.64", "0.9.66"):
        dbmod.insert_companion_package(
            conn, version=version, platform="windows", filename=f"c{version}.exe",
            sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW)
    dbmod.set_current_package(conn, "windows", "0.9.66", "companion")
    conn.commit()


def test_the_rollback_is_actually_delivered_to_the_machine(env):
    """dash-api-3: the push used to be retired on the next report, before
    commands.upgrade was ever emitted - a no-op with a green toast."""
    client, conn, _settings = env
    report(client, version="0.9.66")
    _publish_rows(conn)
    resp = admin(client).post(
        "/api/v1/admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64")
    assert resp.status_code == 200, resp.text
    assert resp.json()["machines"] == ["jsmith/EDIT-PC"]

    # The machine is still on 0.9.66 when it next reports: it has to be TOLD.
    first = report(client, version="0.9.66").json()
    assert first["commands"].get("upgrade", {}).get("version") == "0.9.64"
    # ...and the request only clears once it is actually on the older build.
    assert dbmod.pending_machine_request(conn, "jsmith", "EDIT-PC")["update"] == "0.9.64"
    done = report(client, version="0.9.64").json()
    assert done["commands"].get("upgrade") is None
    assert dbmod.pending_machine_request(conn, "jsmith", "EDIT-PC")["update"] == ""


def test_the_channel_stops_handing_out_the_build_being_rolled_off(env):
    """dash-api-3's second half: with 0.9.66 still current, every machine
    that takes 0.9.64 is offered 0.9.66 again on its next report - and
    unattended where auto_update is on."""
    client, conn, _settings = env
    report(client, version="0.9.66")
    _publish_rows(conn)
    admin(client).post(
        "/api/v1/admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64")
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.9.64"
    after = report(client, version="0.9.64").json()
    assert (after.get("upgrade") or {}).get("version") != "0.9.66"


def test_an_upgrade_push_still_clears_at_or_past_the_version_asked_for(env):
    """dash-core-6 is not undone: a machine that took a NEWER build than the
    one pushed has honoured the push."""
    client, conn, _settings = env
    report(client, version="0.9.64")
    dbmod.request_machine_update(conn, "jsmith", "EDIT-PC", "0.9.66", "owen",
                                 dbmod.utcnow_iso())
    conn.commit()
    report(client, version="0.9.70")
    assert dbmod.pending_machine_request(conn, "jsmith", "EDIT-PC")["update"] == ""


# ------------------------------------------------------------- dash-api-5

def test_a_dirty_build_clears_the_push_it_has_already_taken(env):
    client, conn, _settings = env
    report(client, version="0.9.70+dirty")
    dbmod.request_machine_update(conn, "jsmith", "EDIT-PC", "0.9.70", "owen",
                                 dbmod.utcnow_iso())
    conn.commit()
    reply = report(client, version="0.9.70+dirty").json()
    assert reply["commands"].get("upgrade") is None
    assert dbmod.pending_machine_request(conn, "jsmith", "EDIT-PC")["update"] == ""


def test_a_version_with_no_numeric_prefix_still_reads_as_not_past_it():
    assert api_mod._version_tuple("dev") == ()
    assert api_mod._version_tuple("0.9.70+dirty") == (0, 9, 70)
    assert not api_mod._version_at_least("dev", "0.9.70")


# ------------------------------------------------------------- dash-api-4

def test_a_named_computers_queue_shows_that_computers_resolve_project(env):
    client, conn, _settings = env
    report(client, machine="IMAC", resolve_project="THE IMAC PROJECT")
    report(client, machine="MACBOOK", resolve_project="THE LAPTOP PROJECT")
    # Each page is about ONE computer, and used to be about whichever of the
    # person's computers reported last.
    assert api_mod.build_queue_view(
        conn, "jsmith", machine="IMAC")["resolve_project"] == "THE IMAC PROJECT"
    assert api_mod.build_queue_view(
        conn, "jsmith", machine="MACBOOK")["resolve_project"] == "THE LAPTOP PROJECT"
    # With no machine named the view is the PERSON's, which is one of them.
    person = api_mod.build_queue_view(conn, "jsmith")
    assert person["resolve_project"] in ("THE IMAC PROJECT", "THE LAPTOP PROJECT")


# ------------------------------------------------------------- dash-api-6

def test_a_suspended_editor_is_turned_away_from_the_fleet_doors_too(env):
    client, conn, _settings = env
    report(client)
    assert client.get("/api/v1/selection/jsmith",
                      headers=fleet_headers()).status_code == 200
    dbmod.suspend_editor(conn, "jsmith", by="owen", reason="contract ended")
    conn.commit()

    plan = client.get("/api/v1/selection/jsmith", headers=fleet_headers())
    assert plan.status_code == 403
    assert "suspended" in plan.json()["detail"].lower()
    claim = client.post("/api/v1/jobs/claim", headers=fleet_headers(),
                        json={"machine": "EDIT-PC", "capabilities": {}})
    assert claim.status_code == 403
    # An admin can still read the plan: [ RESUME ] has to put back what was
    # there, and a page that cannot show it is a page nobody can check.
    assert admin(client).get("/api/v1/selection/jsmith").status_code == 200


# -------------------------------------------------------------- dash-db-4

def test_the_retry_guard_holds_on_a_queue_deeper_than_a_thousand(env):
    client, conn, _settings = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    dbmod.fail_job(conn, job_id, "jsmith", "EDIT-PC", error="boom",
                   retryable=False)
    conn.commit()
    new_id, refusal = dbmod.retry_job(conn, job_id, created_by="owen")
    assert new_id and not refusal
    conn.commit()
    # A big card dump lands on the queue AFTER the retry, pushing it past the
    # old 1,000-row scan.
    for _ in range(1005):
        dbmod.create_job(conn, "proxy-480p", dict(MEDIA_INPUTS), {})
    conn.commit()
    again, refusal = dbmod.retry_job(conn, job_id, created_by="owen")
    assert again is None
    assert f"#{new_id}" in refusal


# ----------------------------------------------------- dash-release-jobs-3

def test_the_fleet_cap_is_enforced_by_the_compare_and_set(env):
    """Two claims that both passed the offer-time count: the CAS refuses the
    one that would take the kind over its cap."""
    client, conn, settings = env
    caps = {"proxy-480p": 2}
    running = [queue(conn, kind="proxy-480p") for _ in range(3)]
    assert dbmod.claim_job(conn, running[0], "jsmith", "BOX1", max_running=2)
    assert dbmod.claim_job(conn, running[1], "jsmith", "BOX2", max_running=2)
    conn.commit()
    # Two are in flight and the cap is two: the third claim matches no row.
    assert dbmod.claim_job(conn, running[2], "jsmith", "BOX3", max_running=2) is False
    assert dbmod.claim_next_job(conn, "jsmith", "BOX3", max_running=caps) is None
    # With no cap asked for, the CAS behaves exactly as it always did.
    assert dbmod.claim_next_job(conn, "jsmith", "BOX3") is not None


# -------------------------------------------------------------- comp-app-2

WAVE_3 = {
    "connected": True,
    "project_open": "FF5 EP12",
    "wedged_seconds": 12.5,
    "wedged_call": "GetMediaPool",
    "missing_clips": [{"name": "a.mov", "path": "P:/x/a.mov"}],
    "non_canonical_refused": [{"name": "b.mov", "path": "P:/x/b.mov"}],
    "proxy_attach": {"attached": 3, "failed": 1, "why": "timecode", "at": NOW},
    "proxy_gaps": {"capped": 2, "low_space": "8 GB free", "truncated": True},
    "stills": {"ok": False, "status": "add-by-hand", "instruction": "point it at P:",
               "path": "P:/Assets/Stills"},
    "skipped_ever": 7,
}


def test_the_wave_three_resolve_health_fields_survive_the_wire():
    parsed = api_mod.ResolveHealthIn.model_validate({"out_of_tree": 1, **WAVE_3})
    assert parsed.connected is True
    assert parsed.wedged_seconds == 12.5
    assert parsed.wedged_call == "GetMediaPool"
    assert parsed.missing_clips[0].path == "P:/x/a.mov"
    assert parsed.non_canonical_refused[0].name == "b.mov"
    assert parsed.proxy_attach.failed == 1
    assert parsed.proxy_gaps.low_space == "8 GB free"
    assert parsed.stills.instruction == "point it at P:"
    assert parsed.skipped_ever == 7


def test_a_field_dropped_inside_a_section_is_named_like_a_section(env):
    """The SYS-3 banner can see one level down now (comp-app-2)."""
    client, _conn, _settings = env
    payload = api_mod.ReportIn.model_validate({
        "editor_name": "jsmith", "machine": "EDIT-PC", "lanes": [],
        "reported_at": NOW,
        "sync_guard": {"resolve_health": {"out_of_tree": 1,
                                          "a_field_from_the_future": 5}},
    })
    assert "sync_guard.resolve_health.a_field_from_the_future" in \
        api_mod.undeclared_report_sections(payload)


def test_a_report_carrying_the_new_fields_is_still_accepted(env):
    client, conn, _settings = env
    resp = report(client, sync_guard={"resolve_health": {"out_of_tree": 2, **WAVE_3}})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------- comp-resolve-3

def test_the_cards_refusal_keeps_the_process_it_named():
    base = ("Timeline Cards is not started here because another program on this "
            "computer already holds the Resolve scripting client. One machine, "
            "one Resolve client. Close it and this companion picks the role up "
            "on its own within a minute. ") * 1
    detail = base + "Found: python.exe (pid 4812), started 09:12, reorder_web.py --agent"
    parsed = api_mod.CardsAgentIn.model_validate({"detail": detail})
    assert "pid 4812" in parsed.detail
    assert "reorder_web.py --agent" in parsed.detail


# ------------------------------------------------------------------ v52

def test_v52_runs_on_a_last_shipped_database_and_runs_twice(tmp_path):
    """The migration rule: from the last shipped build's schema (0.7.34, v50),
    twice, with nothing lost."""
    path = tmp_path / "v50.db"
    conn = dbmod.connect(str(path))
    dbmod.migrate(conn, steps=[s for s in dbmod._MIGRATION_STEPS if s[0] <= 50])
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 50
    conn.execute("INSERT INTO machines (editor_username, machine, first_seen, "
                 "last_seen, update_requested_version) "
                 "VALUES ('jsmith','EDIT-PC','a','b','0.9.64')")
    conn.commit()

    dbmod.migrate(conn)
    dbmod.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION
    row = conn.execute("SELECT update_requested_version, update_requested_from "
                       "FROM machines").fetchone()
    # The push that was already outstanding survives, and reads as the OLD
    # behaviour: nobody said which way it points.
    assert row["update_requested_version"] == "0.9.64"
    assert row["update_requested_from"] is None
    assert dbmod.machine_update_request(conn, "jsmith", "EDIT-PC")["from_version"] == ""
    conn.close()


# ------------------------------------------------- server-tools-1 (owed in)

def test_health_counts_machines_per_platform_and_says_when_it_cannot(env,
                                                                     monkeypatch):
    """The ship gate counts MACHINES, and a block it could not compute is
    null rather than empty (server-tools-1)."""
    client, conn, _settings = env
    report(client, machine="EDIT-PC")
    report(client, machine="MACBOOK", platform="macos")

    body = client.get("/api/v1/health", headers=fleet_headers()).json()
    assert body["rollout_platforms"] == {"windows": 1, "macos": 1}

    # "could not compute" is not "nothing to report": both blocks answer null.
    def boom(*_a, **_kw):
        raise RuntimeError("the database is not answering")

    monkeypatch.setattr(dbmod, "rollout_status", boom)
    monkeypatch.setattr(api_mod, "_rollout_platforms_block", lambda _c: None)
    body = client.get("/api/v1/health", headers=fleet_headers()).json()
    assert body["rollout"] is None
    assert body["rollout_platforms"] is None


# ---------------------------------------------------------------- dash-db-1

def test_a_wired_machine_is_not_told_to_move_its_own_copy(env):
    """A base rig's tree root IS the NAS share: the rename the dashboard has
    already made is the only one there is (dash-db-1)."""
    client, conn, _settings = env
    report(client, machine="BASE-RIG")
    dbmod.add_selection(conn, "jsmith", "ff5", "owen", dbmod.utcnow_iso(),
                        machine="BASE-RIG")
    conn.execute("UPDATE machine_state SET mode='base' WHERE machine='BASE-RIG'")
    conn.commit()
    assert ("jsmith", "BASE-RIG") in dbmod.base_machines(conn)
    # The admin grid still shows the tick, so there is a button to clear it.
    assert ("jsmith", "BASE-RIG") in dbmod.fetch_machine_selections(
        conn).get("ff5", [])
    assert ("jsmith", "BASE-RIG") not in [
        (e, m) for e, m in dbmod.fetch_machine_selections(
            conn, for_enforce=True).get("ff5", [])]


def test_the_nine_fields_are_stored_and_read_back(env):
    """comp-app-2's second half: declaring them stops the silent drop, and
    db.store_resolve_health_detail is what makes them survive the report."""
    client, conn, _settings = env
    assert report(client, sync_guard={
        "resolve_health": {"out_of_tree": 2, **WAVE_3}}).status_code == 200
    detail = dbmod.resolve_health_detail(conn, "jsmith", "EDIT-PC")
    assert detail["connected"] is True
    assert detail["wedged_call"] == "GetMediaPool"
    assert detail["wedged_seconds"] == 12.5
    assert detail["missing_clips"][0]["path"] == "P:/x/a.mov"
    assert detail["proxy_attach"]["failed"] == 1
    assert detail["proxy_gaps"]["low_space"] == "8 GB free"
    assert detail["stills"]["instruction"] == "point it at P:"
    # THE LATCH RULE: a later report with the counters and none of the nine
    # clears it. A wedged-call sentence from last Tuesday is worse than
    # silence.
    report(client, sync_guard={"resolve_health": {"out_of_tree": 0}})
    assert dbmod.resolve_health_detail(conn, "jsmith", "EDIT-PC") == {}
