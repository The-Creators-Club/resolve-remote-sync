"""Stopping a job, and the page an operator stops it from.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 4 (2026-08-30). Cancelling is three
different acts wearing one button, and the difference is the point:

  * a QUEUED job is this dashboard's own row: it is over when the click
    returns, and it is never retried;
  * a HELD one belongs to the machine running it. The request is recorded,
    rides `commands.jobs.cancel` on that machine's next report, and the
    companion kills its child. NOTHING HERE FORCES THE ROW TERMINAL BEHIND A
    LIVE FFMPEG -- saying "stopped" while a child is still writing into the
    vault is how a half-made proxy gets published;
  * a PINNED one is this container's own worker, whose should_stop() reads
    the same flag.

The jobs page is the other half of phase 4's stated risk (§6): "the failure
mode is invisible". `why` has answered it since phase 0 for anyone with a
terminal; the person who notices a lane spinning is not holding one.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"

MEDIA_INPUTS = {"root": "media", "rel_path": "FF5/a.mp4",
                "out_root": "vault", "out_rel": "Vault/2026/FF5/cache"}


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
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def fleet_headers(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def queue(conn, kind="peaks"):
    job_id = dbmod.create_job(conn, kind, dict(MEDIA_INPUTS), {})
    conn.commit()
    return job_id


# ------------------------------------------------------------- the route

def test_cancelling_a_queued_job_ends_it_there_and_then(env):
    client, conn = env
    job_id = queue(conn)
    r = admin(client).post(f"/api/v1/jobs/{job_id}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "failed"
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == "failed"
    assert "cancelled by owen" in job["last_error"]
    # ...and it is not retried: a cancelled job back on the queue would be the
    # fleet arguing with a person.
    assert dbmod.queued_jobs(conn) == []


def test_cancelling_a_running_job_is_a_message_not_a_state_change(env):
    client, conn = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    r = admin(client).post(f"/api/v1/jobs/{job_id}/cancel")
    assert r.json()["state"] == "requested"
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == "claimed"          # still theirs, still running
    assert job["cancel_requested_by"] == "owen"


def test_the_machine_holding_it_is_told_on_its_next_report(env):
    client, conn = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    admin(client).post(f"/api/v1/jobs/{job_id}/cancel")
    r = client.post("/api/v1/report", headers=fleet_headers(), json={
        "editor_name": "jsmith", "machine": "EDIT-PC",
        "companion_version": "0.9.60", "reported_at": dbmod.utcnow_iso(),
        "lanes": []})
    assert r.json()["commands"]["jobs"]["cancel"] == [job_id]


def test_another_machine_is_told_nothing(env):
    client, conn = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    admin(client).post(f"/api/v1/jobs/{job_id}/cancel")
    assert dbmod.pending_job_cancels(conn, "jsmith", "OTHER-PC") == []


def test_the_request_keeps_riding_until_the_machine_answers(env):
    """The file_moves rule, not the resume_lane_b rule: an admin clicking
    while a laptop is asleep must not be a click that evaporates."""
    client, conn = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    admin(client).post(f"/api/v1/jobs/{job_id}/cancel")
    for _ in range(3):
        assert dbmod.pending_job_cancels(conn, "jsmith", "EDIT-PC") == [job_id]
    # ...and stops the moment the companion hands it back
    dbmod.fail_job(conn, job_id, "jsmith", "EDIT-PC", error="cancelled",
                   retryable=False)
    conn.commit()
    assert dbmod.pending_job_cancels(conn, "jsmith", "EDIT-PC") == []


def test_cancelling_a_finished_job_is_a_409(env):
    client, conn = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    dbmod.finish_job(conn, job_id, "jsmith", "EDIT-PC", {"files": []})
    conn.commit()
    assert admin(client).post(f"/api/v1/jobs/{job_id}/cancel").status_code == 409


def test_cancelling_a_job_that_does_not_exist_is_a_404(env):
    client, _conn = env
    assert admin(client).post("/api/v1/jobs/999/cancel").status_code == 404


def test_an_editor_cannot_cancel_anybodys_job(env):
    """A job is work on somebody else's computer, and so is stopping one."""
    client, conn = env
    job_id = queue(conn)
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "jsmith"))
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 403
    assert dbmod.get_job(conn, job_id)["state"] == "queued"


def test_a_pinned_job_can_be_cancelled_too(env):
    client, conn = env
    job_id = queue(conn)
    conn.execute("UPDATE jobs SET state='pinned' WHERE id=?", (job_id,))
    conn.commit()
    assert admin(client).post(f"/api/v1/jobs/{job_id}/cancel").json()["state"] \
        == "requested"
    # what the executor's should_stop() reads
    assert dbmod.job_cancel_requested(conn, job_id) is True


# ------------------------------------------------------ the depth route

def test_the_queue_route_names_the_caps_and_whether_anything_pins(env):
    client, conn = env
    queue(conn)
    answer = admin(client).get("/api/v1/jobs/queue").json()
    assert answer["queue"]["queued"] == 1
    kinds = {row["kind"]: row for row in answer["kinds"]}
    assert kinds["whisper"]["cap"] == dbmod.JOB_MAX_RUNNING["whisper"]
    # No /cards mount in this test app, so there is no executor -- and the
    # honest answer is "nothing pins here", never a silent maybe.
    assert answer["pinning"]["available"] is False
    assert answer["pinning"]["why_not"]


def test_the_queue_route_is_not_read_as_a_job_id(env):
    """FastAPI matches in registration order, and /jobs/queue arriving at
    /jobs/{job_id} is a 422 on a page an admin opened."""
    client, _conn = env
    assert admin(client).get("/api/v1/jobs/queue").status_code == 200


# ----------------------------------------------------------- the page

def test_the_jobs_page_shows_a_job_and_why_it_is_not_moving(env):
    client, conn = env
    job_id = queue(conn)
    body = admin(client).get("/admin/jobs").text
    assert f"#{job_id}" in body
    assert "no machine has ever reported to this dashboard" in body
    assert "[ CANCEL ]" in body


def test_the_page_says_whether_anything_pins(env):
    client, _conn = env
    assert "[ NO PINNING HERE ]" in admin(client).get("/admin/jobs").text


def test_the_page_button_cancels(env):
    client, conn = env
    job_id = queue(conn)
    r = admin(client).post(f"/partials/admin/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert dbmod.get_job(conn, job_id)["state"] == "failed"
    assert "is over" in r.text


def test_the_page_does_not_claim_a_running_job_has_stopped(env):
    """The one lie this page cannot afford."""
    client, conn = env
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    r = admin(client).post(f"/partials/admin/jobs/{job_id}/cancel")
    assert "will stop on its next report" in r.text
    assert dbmod.get_job(conn, job_id)["state"] == "claimed"


def test_the_page_is_admin_only(env):
    client, _conn = env
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "jsmith"))
    assert client.get("/admin/jobs").status_code == 403


def test_the_fleet_grid_chip_links_to_the_page(env):
    """The chip is where an admin notices a job; the page is where they can
    do something about it."""
    client, conn = env
    dbmod.upsert_machine_state(conn, "jsmith", "EDIT-PC", None,
                               dbmod.utcnow_iso())
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    body = admin(client).get("/partials/fleet").text
    assert 'href="/admin/jobs"' in body
