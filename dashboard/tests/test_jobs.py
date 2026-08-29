"""The fleet job queue: the table, the lease, the offer filter and `why`.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 0 (2026-08-29). Every test here is
about one of the four properties the queue is worth having at all:

  * TWO CLAIMANTS, ONE WINNER. The claim is a compare-and-set; if this ever
    stops being true, two machines transcribe the same folder into the same
    vault path at the same time.
  * POSSESSION EXPIRES. A machine that vanishes mid-job must not park the
    work for ever, and the re-queue must count as an attempt or the job is
    re-offered to the dead machine until the heat death of the fleet.
  * A JOB NOBODY CAN RUN IS VISIBLE. `why` is here from the first commit
    because a scheduler that quietly assigns nothing looks exactly like a
    fleet with nothing to do.
  * THE IDLE ANSWER FAILS CLOSED. None means cannot tell means NOT IDLE, end
    to end (idle.py's contract).
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, jobs as jobs_mod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"

WHISPER_INPUTS = {
    "root": "vault",
    "rel_path": "Vault/2026/FF5/Civil Defence/Youtube/Interview 3",
    "episode_rel": "Vault/2026/FF5/Civil Defence",
}
WHISPER_REQUIRES = {"whisper": True, "gpu_vram_gb": 6, "mount": "vault"}

GOOD_CAPS = {
    "whisper": True, "gpu_present": True, "gpu_vram_gb": 10,
    "mounts": ["tree", "vault"], "idle_seconds": 900, "cpu_count": 16,
}


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(c)
    yield c
    c.close()


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects),
        report_token=TOKEN,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        c = dbmod.connect(settings.db_path)
        yield client, c, settings
        c.close()


def fleet_headers(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def admin_client(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def seen_machine(conn, editor="jsmith", machine="EDIT-PC", mode="editor"):
    dbmod.upsert_machine_state(conn, editor, machine, None, dbmod.utcnow_iso(),
                               mode=mode)
    conn.commit()


# ------------------------------------------------------------ the table

def test_the_table_and_its_indexes_exist(conn):
    assert dbmod.SCHEMA_VERSION >= 41
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"id", "kind", "created_at", "created_by", "priority", "inputs_json",
            "requires_json", "cost_json", "state", "claimed_by", "claimed_machine",
            "lease_expires_at", "heartbeat_at", "attempts", "last_error",
            "result_json", "updated_at"} <= cols
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(jobs)")}
    assert "ix_jobs_state_kind" in indexes


def test_the_migration_is_replayable(tmp_path):
    """migrate() twice must be a no-op, not a duplicate-column crash-loop."""
    c = dbmod.connect(tmp_path / "twice.db")
    dbmod.migrate(c)
    dbmod.migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION
    c.close()


def test_create_and_read_back(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES,
                              created_by="owen")
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == dbmod.JOB_QUEUED
    assert job["inputs"]["rel_path"].endswith("Interview 3")
    assert job["requires"]["gpu_vram_gb"] == 6
    assert dbmod.list_jobs(conn, state="open")[0]["id"] == job_id


# ------------------------------------------------------------ the claim

def test_two_claimants_one_winner(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    assert dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC") is True
    assert dbmod.claim_job(conn, job_id, "leso", "MBP") is False
    job = dbmod.get_job(conn, job_id)
    assert (job["claimed_by"], job["claimed_machine"]) == ("jsmith", "EDIT-PC")


def test_claim_next_job_skips_what_this_machine_cannot_do(conn):
    gpu_job = dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    plain = dbmod.create_job(conn, "whisper", WHISPER_INPUTS, {})
    weak = {"whisper": False, "gpu_vram_gb": 2, "mounts": ["tree"]}
    got = dbmod.claim_next_job(conn, "leso", "MBP", weak)
    assert got["id"] == plain, "a machine with no GPU must never be given the GPU job"
    assert dbmod.get_job(conn, gpu_job)["state"] == dbmod.JOB_QUEUED


def test_priority_then_age_decides_the_order(conn):
    first = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    urgent = dbmod.create_job(conn, "whisper", WHISPER_INPUTS, priority=10)
    assert [j["id"] for j in dbmod.queued_jobs(conn)][:2] == [urgent, first]


# ------------------------------------------------- heartbeat, expiry, reclaim

def test_heartbeat_extends_and_promotes_to_running(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC", "2026-08-29T10:00:00+00:00")
    assert dbmod.heartbeat_job(conn, job_id, "jsmith", "EDIT-PC",
                               "2026-08-29T10:01:00+00:00") is True
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == dbmod.JOB_RUNNING
    assert job["lease_expires_at"] > "2026-08-29T10:01:00+00:00"


def test_a_heartbeat_from_the_wrong_machine_is_refused(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    assert dbmod.heartbeat_job(conn, job_id, "jsmith", "LAPTOP") is False


def test_an_expired_lease_is_requeued_and_counts_as_an_attempt(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC", "2026-08-29T10:00:00+00:00",
                    lease_seconds=60)
    moved = dbmod.expire_leases(conn, "2026-08-29T10:05:00+00:00")
    assert [m["id"] for m in moved] == [job_id]
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == dbmod.JOB_QUEUED
    assert job["attempts"] == 1
    assert job["claimed_by"] is None
    # ...and another machine can now take it.
    assert dbmod.claim_job(conn, job_id, "leso", "MBP") is True


def test_an_expired_lease_cannot_be_heartbeated_back_to_life(conn):
    """ytdl's rule: an expired lease is not extended, because by then the job
    may already be somebody else's."""
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC", "2026-08-29T10:00:00+00:00",
                    lease_seconds=60)
    assert dbmod.heartbeat_job(conn, job_id, "jsmith", "EDIT-PC",
                               "2026-08-29T10:05:00+00:00") is False


def test_expiry_eventually_abandons_rather_than_ping_ponging(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    for i in range(dbmod.job_retry_budget("whisper")):
        dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC",
                        f"2026-08-29T1{i}:00:00+00:00", lease_seconds=60)
        dbmod.expire_leases(conn, f"2026-08-29T1{i}:30:00+00:00")
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == dbmod.JOB_ABANDONED
    assert "expired" in job["last_error"]


# ------------------------------------------------------ finish, fail, abandon

def test_finish_records_paths_not_bytes(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    assert dbmod.finish_job(conn, job_id, "jsmith", "EDIT-PC",
                            {"files": ["a_words.json"], "realtime": 12.5}) is True
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == dbmod.JOB_DONE
    assert job["result"]["files"] == ["a_words.json"]
    assert job["lease_expires_at"] is None


def test_fail_retries_until_the_budget_then_abandons(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    budget = dbmod.job_retry_budget("whisper")
    states = []
    for _ in range(budget):
        dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
        states.append(dbmod.fail_job(conn, job_id, "jsmith", "EDIT-PC", "boom"))
    assert states[:-1] == [dbmod.JOB_QUEUED] * (budget - 1)
    assert states[-1] == dbmod.JOB_ABANDONED
    assert dbmod.get_job(conn, job_id)["last_error"] == "boom"


def test_an_unretryable_failure_stops_at_once(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    assert dbmod.fail_job(conn, job_id, "jsmith", "EDIT-PC", "no audio here",
                          retryable=False) == dbmod.JOB_FAILED


def test_a_machine_that_does_not_hold_it_cannot_fail_it(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    assert dbmod.fail_job(conn, job_id, "leso", "MBP", "nope") is None


# -------------------------------------------------------- the offer filter

def test_capability_mismatch_is_never_offered(conn):
    dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn)
    weak = dict(GOOD_CAPS, gpu_vram_gb=4)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", weak)
    assert offers["offered"] == []
    assert set(offers["refused"].values()) == {jobs_mod.REFUSE_CAPABILITY}


def test_a_capable_idle_machine_is_offered_the_job(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn)
    assert jobs_mod.offers_for_machine(
        conn, "jsmith", "EDIT-PC", GOOD_CAPS)["offered"] == [job_id]


def test_a_halted_fleet_is_offered_nothing(conn):
    dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn)
    dbmod.set_fleet_halt(conn, True, "something is eating files", "owen")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", GOOD_CAPS)
    assert offers["offered"] == []
    assert set(offers["refused"].values()) == {jobs_mod.REFUSE_FLEET_HALT}


def test_a_machine_with_somebody_at_it_is_offered_nothing(conn):
    dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn)
    busy = dict(GOOD_CAPS, idle_seconds=12)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", busy)
    assert set(offers["refused"].values()) == {jobs_mod.REFUSE_NOT_IDLE}


def test_an_unknown_idle_answer_counts_as_busy(conn):
    """idle.py's contract, end to end: None means cannot tell means not idle."""
    dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn)
    unknown = dict(GOOD_CAPS, idle_seconds=None)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", unknown)
    assert offers["offered"] == []
    assert set(offers["refused"].values()) == {jobs_mod.REFUSE_NOT_IDLE}


def test_the_base_rig_is_exempt_from_the_idle_floor(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn, editor="owen", machine="BASE-RIG", mode="base")
    busy = dict(GOOD_CAPS, idle_seconds=0)
    assert jobs_mod.offers_for_machine(
        conn, "owen", "BASE-RIG", busy)["offered"] == [job_id]


def test_a_machine_already_holding_a_job_is_offered_nothing(conn):
    held = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn)
    dbmod.claim_job(conn, held, "jsmith", "EDIT-PC")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", GOOD_CAPS)
    assert offers["offered"] == []
    assert set(offers["refused"].values()) == {jobs_mod.REFUSE_BUSY_WITH_JOB}


def test_a_kind_this_build_does_not_know_is_never_offered(conn):
    dbmod.create_job(conn, "conform", WHISPER_INPUTS)
    seen_machine(conn)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", GOOD_CAPS)
    assert offers["offered"] == []
    assert set(offers["refused"].values()) == {jobs_mod.REFUSE_KIND_UNKNOWN}


def test_a_companion_that_reports_no_capabilities_is_offered_nothing(conn):
    dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    seen_machine(conn)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC", {})
    assert set(offers["refused"].values()) == {jobs_mod.REFUSE_NO_CAPABILITIES}


# ------------------------------------------------------------------- why

def test_why_names_the_reason_per_machine(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS, WHISPER_REQUIRES)
    seen_machine(conn, "jsmith", "EDIT-PC")
    seen_machine(conn, "leso", "MBP")
    answer = jobs_mod.explain(conn, job_id)
    assert answer["schedulable"] is False
    assert len(answer["machines"]) == 2
    assert all(not m["ok"] for m in answer["machines"])
    assert "no machine can take this job" in answer["summary"]


def test_why_says_who_is_holding_it(conn):
    job_id = dbmod.create_job(conn, "whisper", WHISPER_INPUTS)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    assert "EDIT-PC" in jobs_mod.explain(conn, job_id)["summary"]


def test_why_on_a_job_that_does_not_exist(conn):
    assert jobs_mod.explain(conn, 999) is None


# ----------------------------------------------------------------- routes

def test_submit_list_and_why_are_admin_only(env):
    client, conn, _settings = env
    assert client.post("/api/v1/jobs", json={"kind": "whisper"}).status_code in (401, 403)
    assert client.get("/api/v1/jobs").status_code in (401, 403)
    admin_client(client)
    r = client.post("/api/v1/jobs", json={
        "kind": "whisper", "inputs": WHISPER_INPUTS, "requires": WHISPER_REQUIRES})
    assert r.status_code == 200, r.text
    job_id = r.json()["job"]["id"]
    # The receipt says why nothing is running it yet.
    assert r.json()["why"]["schedulable"] is False
    assert client.get("/api/v1/jobs").json()["jobs"][0]["id"] == job_id
    assert client.get(f"/api/v1/jobs/{job_id}/why").json()["job"]["id"] == job_id
    assert client.get("/api/v1/jobs/4242").status_code == 404


def test_login_hands_a_non_browser_client_its_own_csrf_token(env):
    """tools/jobs.py has no page to read the hidden field off, and the
    alternative -- making the JSON write routes CSRF-exempt -- is the wrong
    direction. The token is an HMAC over the caller's OWN session id."""
    client, _conn, _settings = env
    r = client.post("/api/v1/login", json={"username": "owen", "password": "x"})
    if r.status_code != 200:
        pytest.skip("no local credential backend in this environment")
    assert r.json()["csrf"]


def test_the_fleet_routes_need_a_token_and_an_identity(env):
    client, conn, _settings = env
    assert client.post("/api/v1/jobs/claim",
                       json={"machine": "EDIT-PC"}).status_code in (401, 403)
    assert client.post("/api/v1/jobs/claim", json={"machine": "EDIT-PC"},
                       headers={"X-CCSync-Token": TOKEN}).status_code == 403
    # A bad token never reaches the route at all: login_gate's carve-out is
    # conditional on the credential, so it answers 401 "login required" first.
    assert client.post("/api/v1/jobs/claim", json={"machine": "EDIT-PC"},
                       headers={"X-CCSync-Token": "wrong",
                                "X-CCSync-Identity": auth.make_identity_token(
                                    SECRET, "jsmith")}).status_code == 401


def test_claim_heartbeat_result_over_http(env):
    client, conn, _settings = env
    admin_client(client)
    job_id = client.post("/api/v1/jobs", json={
        "kind": "whisper", "inputs": WHISPER_INPUTS,
        "requires": WHISPER_REQUIRES}).json()["job"]["id"]
    seen_machine(conn)
    body = {"machine": "EDIT-PC", "capabilities": GOOD_CAPS}
    r = client.post("/api/v1/jobs/claim", json=body, headers=fleet_headers())
    assert r.status_code == 200, r.text
    assert r.json()["job"]["id"] == job_id
    # A second machine asking gets nothing, not somebody else's job.
    seen_machine(conn, "leso", "MBP")
    r2 = client.post("/api/v1/jobs/claim",
                     json={"machine": "MBP", "capabilities": GOOD_CAPS},
                     headers=fleet_headers("leso"))
    assert r2.json()["job"] is None
    assert client.post(f"/api/v1/jobs/{job_id}/heartbeat",
                       json={"machine": "EDIT-PC"},
                       headers=fleet_headers()).status_code == 200
    # Somebody else's heartbeat is 410 GONE, never 403.
    assert client.post(f"/api/v1/jobs/{job_id}/heartbeat", json={"machine": "MBP"},
                       headers=fleet_headers("leso")).status_code == 410
    r3 = client.post(f"/api/v1/jobs/{job_id}/result",
                     json={"machine": "EDIT-PC", "ok": True,
                           "result": {"files": ["x_words.json"]}},
                     headers=fleet_headers())
    assert r3.status_code == 200
    assert dbmod.get_job(conn, job_id)["state"] == dbmod.JOB_DONE


def test_a_failed_result_requeues_the_job(env):
    client, conn, _settings = env
    admin_client(client)
    job_id = client.post("/api/v1/jobs", json={
        "kind": "whisper", "inputs": WHISPER_INPUTS}).json()["job"]["id"]
    seen_machine(conn)
    client.post("/api/v1/jobs/claim",
                json={"machine": "EDIT-PC", "capabilities": GOOD_CAPS},
                headers=fleet_headers())
    r = client.post(f"/api/v1/jobs/{job_id}/result",
                    json={"machine": "EDIT-PC", "ok": False, "error": "cuda oom"},
                    headers=fleet_headers())
    assert r.json()["state"] == dbmod.JOB_QUEUED
    assert dbmod.get_job(conn, job_id)["attempts"] == 1


def test_the_report_reply_offers_jobs(env, monkeypatch):
    """commands.jobs rides the reply the halt and the pushed update ride."""
    client, conn, _settings = env
    admin_client(client)
    job_id = client.post("/api/v1/jobs", json={
        "kind": "whisper", "inputs": WHISPER_INPUTS}).json()["job"]["id"]
    monkeypatch.setattr(dbmod, "machine_capabilities",
                        lambda *a, **k: dict(GOOD_CAPS))
    body = {"editor_name": "jsmith", "machine": "EDIT-PC",
            "companion_version": "0.9.56",
            "reported_at": dbmod.utcnow_iso(), "lanes": []}
    r = client.post("/api/v1/report", json=body, headers=fleet_headers())
    assert r.status_code == 200, r.text
    block = r.json()["commands"]["jobs"]
    assert block["offered"] == [job_id]
    # ...and phase 4's depth signal beside it, so a companion can back off by
    # itself rather than by being refused.
    assert block["queue"] == {"queued": 1, "running": 0, "pinned": 0,
                              "oldest_age_s": block["queue"]["oldest_age_s"]}


def test_a_broken_scheduler_never_costs_a_report(env, monkeypatch):
    client, conn, _settings = env
    monkeypatch.setattr(jobs_mod, "offers_for_machine",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    body = {"editor_name": "jsmith", "machine": "EDIT-PC",
            "companion_version": "0.9.56",
            "reported_at": dbmod.utcnow_iso(), "lanes": []}
    r = client.post("/api/v1/report", json=body, headers=fleet_headers())
    assert r.status_code == 200
    assert "jobs" not in r.json()["commands"]


def test_finished_jobs_are_pruned_and_queued_ones_are_not(conn):
    old = dbmod.create_job(conn, "whisper", WHISPER_INPUTS,
                           now="2026-01-01T00:00:00+00:00")
    dbmod.claim_job(conn, old, "jsmith", "EDIT-PC", "2026-01-01T00:00:00+00:00")
    dbmod.finish_job(conn, old, "jsmith", "EDIT-PC", {}, "2026-01-01T00:10:00+00:00")
    waiting = dbmod.create_job(conn, "whisper", WHISPER_INPUTS,
                               now="2026-01-01T00:00:00+00:00")
    dbmod.prune(conn, dbmod.utcnow_iso())
    assert dbmod.get_job(conn, old) is None
    assert dbmod.get_job(conn, waiting) is not None
