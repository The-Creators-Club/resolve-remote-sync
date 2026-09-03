"""`GET /api/v1/jobs/machines` -- the machines a job can be aimed at.

cards-machine-picker 2026-09-03. `target_machine` has worked end to end since
dashboard 0.7.23, but there has never been a list of names to pick from, so
Timeline Cards' intake head shipped a remembered free-text box (its
docs/STAGED-AND-BINS-PLAN.md section 8: "the clean v2 is one small
GET /api/v1/jobs/machines on the dashboard"). A picker fed by a typed string
is a job addressed to nobody, and the only thing that says so is the receipt's
`why`.

Pinned here: the credential on both sides of the door, the shape the picker
reads, that a machine nobody has heard from in a day sorts and reads as
offline, that a machine's own `jobs_kinds` allow-list rides along, and that
nothing secret does.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
DEVICE = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "machines.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def hdr(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def machine(conn, editor, name, *, at=None, caps=None, mode=None):
    """One computer in the registry, in machine_state, with capabilities."""
    at = at or dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, editor, name, at, machine_id=f"id-{name}",
                         platform="windows", syncthing_device_id=DEVICE)
    dbmod.upsert_machine_state(conn, editor, name, None, at, mode=mode)
    dbmod.store_machine_capabilities(conn, editor, name, caps, at)
    conn.commit()


def ago(hours):
    return (dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def by_name(answer):
    return {m["machine"]: m for m in answer["machines"]}


def test_a_fleet_caller_gets_the_machines_and_the_kinds(env):
    client, conn = env
    machine(conn, "jsmith", "EDIT-PC", caps={
        "gpu_present": True, "gpu_name": "RTX 4090", "gpu_vram_gb": 24,
        "nvenc": True, "ffmpeg": True, "ffprobe": True, "whisper": True,
        "cpu_count": 16, "mounts": ["vault", "media"], "idle_seconds": 900,
        "jobs_enabled": True})
    r = client.get("/api/v1/jobs/machines", headers=hdr())
    assert r.status_code == 200, r.text
    answer = r.json()
    assert list(answer["kinds"]) == list(dbmod.JOB_KINDS)
    row = by_name(answer)["EDIT-PC"]
    assert row["editor"] == "jsmith"
    assert row["online"] is True and row["mode"] == "editor"
    assert row["jobs_enabled"] is True
    assert row["kinds"] == []            # empty is EVERY kind
    assert row["idle_seconds"] == 900
    assert row["current_job"] is None
    assert row["capabilities"]["gpu_name"] == "RTX 4090"
    assert row["capabilities"]["gpu_vram_gb"] == 24
    assert row["capabilities"]["nvenc"] is True
    assert row["capabilities"]["whisper"] is True
    assert row["capabilities"]["mounts"] == ["vault", "media"]


def test_it_refuses_a_caller_with_no_credential_at_all(env):
    client, conn = env
    machine(conn, "jsmith", "EDIT-PC", caps={"ffmpeg": True})
    assert client.get("/api/v1/jobs/machines").status_code == 401
    # ...and a fleet token with no signed identity is the fleet routes' own
    # 403, not a login page: the token proves "a machine in this fleet" and
    # nothing about which.
    r = client.get("/api/v1/jobs/machines", headers={"X-CCSync-Token": TOKEN})
    assert r.status_code == 403
    # A WRONG token never reaches the route: login_gate's carve-out only
    # opens for a credential that resolves, so this is the 401 any anonymous
    # caller gets and the route's own gate is never the thing being tested.
    r = client.get("/api/v1/jobs/machines",
                   headers={"X-CCSync-Token": "not-the-token",
                            "X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith")})
    assert r.status_code == 401


def test_an_admin_session_may_read_it_and_a_plain_editor_may_not(env):
    """The credential the Timeline Cards server already holds: fleet_jobs.py
    signs in as an admin to submit, and the picker rides the same session."""
    client, conn = env
    machine(conn, "jsmith", "EDIT-PC", caps={"ffmpeg": True})
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    assert client.get("/api/v1/jobs/machines").status_code == 403
    client.cookies.clear()
    assert as_admin(client).get("/api/v1/jobs/machines").status_code == 200


def test_it_names_no_token_and_no_device_id(env):
    client, conn = env
    machine(conn, "jsmith", "EDIT-PC", caps={"ffmpeg": True, "resolve": {
        "running": True, "project": "FF5 Civil Defence"}})
    body = client.get("/api/v1/jobs/machines", headers=hdr()).text
    assert TOKEN not in body and SECRET not in body
    assert DEVICE not in body
    assert "id-EDIT-PC" not in body
    # ...and no Resolve project title either: this is a list of computers and
    # what they can do.
    assert "Civil Defence" not in body


def test_a_machine_nobody_has_heard_from_in_a_day_is_offline_and_sorts_last(env):
    client, conn = env
    machine(conn, "jsmith", "AAA-OLD-PC", at=ago(30), caps={"ffmpeg": True})
    machine(conn, "jsmith", "ZZZ-LIVE-PC", caps={"ffmpeg": True})
    answer = client.get("/api/v1/jobs/machines", headers=hdr()).json()
    rows = by_name(answer)
    assert rows["AAA-OLD-PC"]["online"] is False
    assert rows["ZZZ-LIVE-PC"]["online"] is True
    # Online first, then the hostname -- the alphabetical order alone would
    # have put the dead machine at the top of the picker.
    assert [m["machine"] for m in answer["machines"]] == ["ZZZ-LIVE-PC", "AAA-OLD-PC"]


def test_a_machines_own_kind_allow_list_rides_along(env):
    client, conn = env
    machine(conn, "jsmith", "LAPTOP", caps={
        "ffmpeg": True, "jobs_enabled": True, "job_kinds": ["proxy-480p"]})
    machine(conn, "jsmith", "OFF-PC", caps={"ffmpeg": True, "jobs_enabled": False})
    rows = by_name(client.get("/api/v1/jobs/machines", headers=hdr()).json())
    assert rows["LAPTOP"]["kinds"] == ["proxy-480p"]
    assert rows["LAPTOP"]["jobs_enabled"] is True
    assert rows["OFF-PC"]["kinds"] == []
    assert rows["OFF-PC"]["jobs_enabled"] is False


def test_a_machine_holding_a_job_says_which(env):
    client, conn = env
    machine(conn, "jsmith", "EDIT-PC", caps={"whisper": True, "idle_seconds": 900})
    job_id = dbmod.create_job(conn, "whisper", {"root": "vault", "rel_path": "V/x"},
                              {"whisper": True})
    assert dbmod.claim_next_job(conn, "jsmith", "EDIT-PC",
                                {"whisper": True, "idle_seconds": 900},
                                allowed_ids=[job_id]) is not None
    conn.commit()
    row = by_name(client.get("/api/v1/jobs/machines", headers=hdr()).json())["EDIT-PC"]
    assert row["current_job"] == {"id": job_id, "kind": "whisper"}


def test_a_machine_that_never_reported_capabilities_is_not_enabled_by_default(env):
    """{} is "unknown", which the scheduler reads as "offer it nothing that
    has a requirement" -- so the picker must not draw it as ready."""
    client, conn = env
    machine(conn, "jsmith", "OLD-COMPANION")
    row = by_name(client.get("/api/v1/jobs/machines",
                             headers=hdr()).json())["OLD-COMPANION"]
    assert row["jobs_enabled"] is False
    assert row["idle_seconds"] is None
    assert row["capabilities"]["ffmpeg"] is False


def test_machines_is_not_read_as_a_job_id(env):
    """Route order: a literal segment registered after `/jobs/{job_id}` would
    422 on a path an admin opened."""
    client, conn = env
    machine(conn, "jsmith", "EDIT-PC", caps={"ffmpeg": True})
    r = as_admin(client).get("/api/v1/jobs/machines")
    assert r.status_code == 200 and "machines" in r.json()
