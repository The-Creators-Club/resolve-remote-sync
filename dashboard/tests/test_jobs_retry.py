"""What the fleet gave up on, and putting it back on the queue.

DDIAG-11 (usability + resilience sweep 2026-09-03, built 2026-09-04). `failed`
and `abandoned` are terminal states and the JOBS page listed OPEN jobs only,
so a fleet that had just spent its retry budget on twelve whisper jobs (one
machine with a broken ffmpeg is the documented case) showed the operator
"Nothing is queued or running." There was no count, no list, no last_error and
no way back except retyping the kind, the root and the relative path from
nothing.

The property this file exists to pin: A RETRY IS A NEW ROW AND THE OLD ONE IS
LEFT ALONE. "It failed three times on two machines and then worked" is the
only evidence anybody has for a bad clip as against a broken computer, and a
retry that reopened the row would erase it.
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


def queue(conn, kind="peaks", **over):
    job_id = dbmod.create_job(conn, kind, dict(MEDIA_INPUTS), {}, **over)
    conn.commit()
    return job_id


def end(conn, job_id, state=dbmod.JOB_ABANDONED, error="ffmpeg: no such file",
        machine="EDIT-PC", when=None):
    """Put a job in a terminal state the way the lease sweeper would, without
    driving four claims through the API to spend a retry budget."""
    conn.execute(
        "UPDATE jobs SET state=?, last_error=?, attempts=3, claimed_by=?, "
        "       claimed_machine=?, updated_at=? WHERE id=?",
        (state, error, "jsmith", machine, when or dbmod.utcnow_iso(), job_id))
    conn.commit()


# ------------------------------------------------------ listing what ended

def test_finished_jobs_lists_the_terminal_states_with_their_error(env):
    _client, conn = env
    dead = queue(conn)
    end(conn, dead)
    done = queue(conn)
    end(conn, done, state=dbmod.JOB_DONE, error="")
    open_one = queue(conn)

    rows = dbmod.finished_jobs(conn)
    ids = [r["id"] for r in rows]
    assert dead in ids and done in ids
    assert open_one not in ids, "an open job is not finished"
    assert rows[0]["last_error"] == "" or rows[-1]["last_error"]
    assert next(r for r in rows if r["id"] == dead)["last_error"] \
        == "ffmpeg: no such file"


def test_finished_jobs_stops_at_the_window(env):
    _client, conn = env
    old = queue(conn)
    end(conn, old, when=dbmod._iso_minus(dbmod.utcnow_iso(), 30 * 3600))
    fresh = queue(conn)
    end(conn, fresh)
    ids = [r["id"] for r in dbmod.finished_jobs(conn, hours=24)]
    assert ids == [fresh]
    # ...and the window is a parameter, not a fact about the world.
    assert old in [r["id"] for r in dbmod.finished_jobs(conn, hours=48)]


def test_the_abandoned_count_is_only_the_abandoned_ones(env):
    _client, conn = env
    for _ in range(3):
        job_id = queue(conn)
        end(conn, job_id)
    failed = queue(conn)
    end(conn, failed, state=dbmod.JOB_FAILED)
    queue(conn)
    assert dbmod.count_abandoned_jobs(conn) == 3
    old = queue(conn)
    end(conn, old, when=dbmod._iso_minus(dbmod.utcnow_iso(), 40 * 3600))
    assert dbmod.count_abandoned_jobs(conn) == 3, "yesterday is not last night"


# --------------------------------------------------------------- the route

def test_a_retry_is_a_new_job_with_the_same_inputs(env):
    client, conn = env
    dead = queue(conn, kind="proxy-480p")
    end(conn, dead)

    r = admin(client).post(f"/api/v1/jobs/{dead}/retry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retry_of"] == dead
    new = body["job"]
    assert new["id"] != dead
    assert new["state"] == "queued"
    assert new["kind"] == "proxy-480p"
    assert new["attempts"] == 0
    assert {k: v for k, v in new["inputs"].items() if k != "retry_of"} \
        == MEDIA_INPUTS
    assert new["inputs"]["retry_of"] == dead
    # The receipt carries the scheduling answer, like a submission's does.
    assert body["why"]["summary"]


def test_the_old_row_is_left_exactly_as_it_was(env):
    client, conn = env
    dead = queue(conn)
    end(conn, dead)
    before = dbmod.get_job(conn, dead)
    admin(client).post(f"/api/v1/jobs/{dead}/retry")
    assert dbmod.get_job(conn, dead) == before


def test_the_levers_and_the_priority_come_with_it(env):
    client, conn = env
    dead = queue(conn, priority=7, forced=True, target_machine="CREATOR-1")
    end(conn, dead)
    new = admin(client).post(f"/api/v1/jobs/{dead}/retry").json()["job"]
    assert new["priority"] == 7
    assert new["forced"] is True
    assert new["target_machine"] == "CREATOR-1"


def test_a_job_that_has_not_finished_is_a_409(env):
    """Nothing forces a row terminal behind a live ffmpeg, so a retry does not
    quietly cancel one on the way past."""
    client, conn = env
    running = queue(conn)
    dbmod.claim_job(conn, running, "jsmith", "EDIT-PC")
    conn.commit()
    r = admin(client).post(f"/api/v1/jobs/{running}/retry")
    assert r.status_code == 409
    assert "has not finished" in r.json()["detail"]
    assert dbmod.get_job(conn, running)["state"] == "claimed"


def test_a_second_retry_while_the_first_is_still_queued_is_a_409(env):
    client, conn = env
    dead = queue(conn)
    end(conn, dead)
    first = admin(client).post(f"/api/v1/jobs/{dead}/retry").json()["job"]["id"]
    r = admin(client).post(f"/api/v1/jobs/{dead}/retry")
    assert r.status_code == 409
    assert f"#{first}" in r.json()["detail"]
    # ...but once that attempt has itself ended, another one is allowed: the
    # refusal is about a double queue, not about a job being cursed.
    end(conn, first)
    assert admin(client).post(f"/api/v1/jobs/{dead}/retry").status_code == 200


def test_a_retry_of_a_retry_names_its_immediate_origin(env):
    client, conn = env
    dead = queue(conn)
    end(conn, dead)
    first = admin(client).post(f"/api/v1/jobs/{dead}/retry").json()["job"]["id"]
    end(conn, first)
    second = admin(client).post(f"/api/v1/jobs/{first}/retry").json()["job"]
    assert second["inputs"]["retry_of"] == first


def test_retrying_a_job_that_does_not_exist_is_a_404(env):
    client, _conn = env
    assert admin(client).post("/api/v1/jobs/999/retry").status_code == 404


def test_an_editor_cannot_retry_anybodys_job(env):
    """The same gate as cancel: a job is work on somebody else's computer."""
    client, conn = env
    dead = queue(conn)
    end(conn, dead)
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "jsmith"))
    assert client.post(f"/api/v1/jobs/{dead}/retry").status_code == 403
    assert dbmod.count_abandoned_jobs(conn) == 1


# ----------------------------------------------------------------- the page

def test_an_empty_queue_still_says_what_was_abandoned(env):
    client, conn = env
    for _ in range(2):
        end(conn, queue(conn))
    body = admin(client).get("/admin/jobs").text
    assert "Nothing is queued or running." in body
    assert "2 jobs were abandoned in the last 24 h." in body
    assert "[ SHOW FINISHED ]" in body


def test_the_queue_head_counts_the_abandoned_beside_the_running(env):
    client, conn = env
    end(conn, queue(conn))
    queue(conn)
    body = admin(client).get("/admin/jobs").text
    assert "1 abandoned in the last 24 h" in body


def test_the_finished_list_shows_the_whole_error_and_a_try_again(env):
    client, conn = env
    long_error = "ffmpeg: " + "x" * 300
    dead = queue(conn)
    end(conn, dead, error=long_error)
    body = admin(client).get("/partials/admin/jobs?finished=1").text
    assert long_error in body, "the sentence ffmpeg wrote is the evidence"
    assert "[ TRY AGAIN ]" in body
    assert "media:FF5/a.mp4" in body
    assert "jsmith/EDIT-PC" in body


def test_a_finished_job_that_succeeded_is_shown_but_not_retryable(env):
    client, conn = env
    done = queue(conn)
    end(conn, done, state=dbmod.JOB_DONE, error="")
    body = admin(client).get("/partials/admin/jobs?finished=1").text
    assert f"#{done}" in body
    assert "[ TRY AGAIN ]" not in body


def test_the_open_list_is_the_default(env):
    client, conn = env
    dead = queue(conn)
    end(conn, dead, error="the one that got away")
    body = admin(client).get("/partials/admin/jobs").text
    assert "the one that got away" not in body
    assert "[ SHOW FINISHED ]" in body


def test_the_toggle_survives_the_poll(env):
    """The poll is on the partial itself and carries the flag: a wrapper
    polling a fixed URL closed the list every 15 seconds."""
    client, conn = env
    end(conn, queue(conn))
    body = admin(client).get("/partials/admin/jobs?finished=1").text
    assert 'hx-get="/partials/admin/jobs?finished=1"' in body
    assert "[ HIDE FINISHED ]" in body


def test_the_page_button_retries_and_says_which_number_it_is_now(env):
    client, conn = env
    dead = queue(conn)
    end(conn, dead)
    r = admin(client).post(f"/partials/admin/jobs/{dead}/retry?finished=1")
    assert r.status_code == 200
    new = dbmod.list_jobs(conn, state="queued")[0]
    assert new["inputs"]["retry_of"] == dead
    assert f"as #{new['id']}" in r.text
    assert dbmod.get_job(conn, dead)["state"] == "abandoned"


def test_the_page_refusal_is_a_sentence_not_a_stack_trace(env):
    client, conn = env
    running = queue(conn)
    dbmod.claim_job(conn, running, "jsmith", "EDIT-PC")
    conn.commit()
    r = admin(client).post(f"/partials/admin/jobs/{running}/retry")
    assert r.status_code == 200
    assert "has not finished" in r.text


def test_the_page_retry_is_admin_only(env):
    client, conn = env
    dead = queue(conn)
    end(conn, dead)
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "jsmith"))
    assert client.post(f"/partials/admin/jobs/{dead}/retry").status_code == 403


def test_both_lists_render_together(env):
    """The toggle is under the open table as well as under an empty queue:
    the operator who has one job stuck is the one asking what the fleet gave
    up on before it."""
    client, conn = env
    end(conn, queue(conn))
    open_id = queue(conn)
    body = admin(client).get("/partials/admin/jobs?finished=1").text
    assert f"#{open_id}" in body
    assert "[ FINISHED IN THE LAST 24 HOURS ]" in body
    assert "[ HIDE FINISHED ]" in body
