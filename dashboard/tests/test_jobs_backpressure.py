"""The queue pushing back, and saying which kind of "no" it is.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 4 (2026-08-30). Three brakes and one
vocabulary:

  * A PER-KIND FLEET CAP. One job at a time per machine was never a limit on
    the NAS's disk or the media share's bandwidth, which four simultaneous
    480p encodes reading rushes over SMB find long before any one machine
    does.
  * A COOLDOWN AFTER A FAILURE. The machine with the broken ffmpeg is
    otherwise first in the queue for every retry -- failing in two seconds is
    exactly what keeps it idle -- and one bad machine spends a two-attempt
    budget on its own.
  * A QUEUE DEPTH ON THE REPORT REPLY, so a companion can back off by itself
    instead of being refused.

And `reason_code`: Timeline Cards' client falls back to its own ffmpeg when
`why.schedulable` is false, and "no machine in this fleet can ever do this"
and "every machine is busy for the next minute" must not be the same answer.
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod, jobs as jobs_mod

MEDIA_CAPS = {"ffmpeg": True, "ffprobe": True, "mounts": ["vault", "media"],
              "idle_seconds": 900}


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(c)
    yield c
    c.close()


def machine(conn, name, caps=None, mode="editor", editor="alex"):
    dbmod.upsert_machine_state(conn, editor, name, None, dbmod.utcnow_iso(),
                               mode=mode)
    dbmod.store_machine_capabilities(conn, editor, name,
                                     dict(MEDIA_CAPS if caps is None else caps),
                                     dbmod.utcnow_iso())
    conn.commit()
    return (editor, name)


def queue(conn, kind="peaks", requires=None):
    job_id = dbmod.create_job(conn, kind, {"root": "media", "rel_path": "a.mp4"},
                              requires if requires is not None else {})
    conn.commit()
    return job_id


def running(conn, kind, machine_name):
    """One job of `kind`, held by a machine. The cap counts these."""
    job_id = queue(conn, kind)
    assert dbmod.claim_job(conn, job_id, "alex", machine_name)
    conn.commit()
    return job_id


# ------------------------------------------------------------- the cap

def test_a_kind_at_its_fleet_cap_is_offered_to_nobody(conn):
    key = machine(conn, "box-a")
    for i in range(dbmod.JOB_MAX_RUNNING["peaks"]):
        running(conn, "peaks", "holder-%d" % i)
    waiting = queue(conn, "peaks")
    offers = jobs_mod.offers_for_machine(conn, *key)
    assert offers["offered"] == []
    assert offers["refused"][waiting] == jobs_mod.REFUSE_FLEET_CAP


def test_the_cap_counts_offers_made_in_the_same_pass(conn):
    """Eight offers of a capped kind on one reply is exactly the burst the
    cap exists to stop -- the count has to move as the offers are made."""
    key = machine(conn, "box-a")
    for _ in range(6):
        queue(conn, "peaks")
    offered = jobs_mod.offers_for_machine(conn, *key, caps={"peaks": 2})["offered"]
    assert len(offered) == 2


def test_a_deployment_can_raise_its_own_cap(conn):
    key = machine(conn, "box-a")
    for i in range(4):
        running(conn, "proxy-480p", "holder-%d" % i)
    waiting = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, *key)["offered"] == []
    assert jobs_mod.offers_for_machine(
        conn, *key, caps={"proxy-480p": 8})["offered"] == [waiting]


def test_a_typo_in_the_limit_leaves_the_default_standing(conn):
    from ccsync_dashboard.settings import Settings

    settings = Settings.from_env({"DASH_JOBS_MAX_RUNNING": "whisper=lots,peaks=1"})
    caps = jobs_mod.fleet_caps(settings)
    assert caps["peaks"] == 1
    assert caps["whisper"] == dbmod.JOB_MAX_RUNNING["whisper"]


def test_why_says_the_fleet_is_at_its_limit_not_that_nothing_can_do_it(conn):
    machine(conn, "box-a")
    for i in range(2):
        running(conn, "whisper", "holder-%d" % i)
    waiting = queue(conn, "whisper")
    answer = jobs_mod.explain(conn, waiting)
    assert answer["schedulable"] is False
    assert answer["reason_code"] == jobs_mod.REASON_FLEET_CAP
    assert answer["transient"] is True
    assert "limit" in answer["summary"]


# -------------------------------------------------------- the cooldown

def test_a_machine_that_failed_a_job_is_left_alone_for_a_while(conn):
    key = machine(conn, "flaky")
    job_id = queue(conn)
    assert dbmod.claim_job(conn, job_id, *key)
    assert dbmod.fail_job(conn, job_id, *key, error="ffmpeg died") == "queued"
    conn.commit()
    offers = jobs_mod.offers_for_machine(conn, *key)
    assert offers["refused"][job_id] == jobs_mod.REFUSE_COOLDOWN
    until, reason = dbmod.machine_job_cooldown(conn, *key)
    assert until and "ffmpeg died" in reason


def test_a_fault_in_the_job_does_not_punish_the_machine(conn):
    """`retryable=False` is the runner saying the fault is in the CLIP. A
    good machine cooled down for a bad clip is a fleet that stops for a
    reason nobody can see."""
    key = machine(conn, "good")
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, *key)
    dbmod.fail_job(conn, job_id, *key, error="no audio track", retryable=False)
    conn.commit()
    assert dbmod.machine_job_cooldown(conn, *key) == ("", "")


def test_finishing_a_job_clears_the_cooldown(conn):
    key = machine(conn, "box")
    first = queue(conn)
    dbmod.claim_job(conn, first, *key)
    dbmod.fail_job(conn, first, *key, error="a blip")
    second = queue(conn)
    dbmod.claim_job(conn, second, *key)
    assert dbmod.finish_job(conn, second, *key, {"files": []})
    conn.commit()
    assert dbmod.machine_job_cooldown(conn, *key) == ("", "")


def test_a_lost_lease_cools_the_machine_down_too(conn):
    """A machine that went quiet mid-job is the same evidence as one that
    reported a failure: it did not finish what it took."""
    key = machine(conn, "sleeper")
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, *key, lease_seconds=0)
    moved = dbmod.expire_leases(conn)
    conn.commit()
    assert [j["id"] for j in moved] == [job_id]
    until, reason = dbmod.machine_job_cooldown(conn, *key)
    assert until and "lease" in reason


def test_a_cooldown_of_zero_seconds_is_off(conn):
    key = machine(conn, "box")
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, *key)
    dbmod.fail_job(conn, job_id, *key, error="x", cooldown_seconds=0)
    conn.commit()
    assert dbmod.machine_job_cooldown(conn, *key) == ("", "")


def test_the_cooldown_is_a_sentence_on_the_why_page(conn):
    key = machine(conn, "flaky")
    job_id = queue(conn)
    dbmod.claim_job(conn, job_id, *key)
    dbmod.fail_job(conn, job_id, *key, error="ffmpeg died")
    conn.commit()
    answer = jobs_mod.explain(conn, job_id)
    assert answer["reason_code"] == jobs_mod.REASON_COOLDOWN
    assert "cooling down" in answer["machines"][0]["why"]


# ------------------------------------------------------- the depth signal

def test_the_queue_depth_is_what_a_companion_can_back_off_on(conn):
    machine(conn, "holder")
    running(conn, "peaks", "holder")
    queue(conn, "peaks")
    depth = dbmod.queue_depth(conn)
    assert depth["queued"] == 1
    assert depth["running"] == 1
    assert depth["pinned"] == 0
    assert depth["oldest_age_s"] is not None


def test_an_empty_queue_has_no_age_rather_than_an_age_of_zero(conn):
    """Zero is "something arrived this second". A companion that read the
    two the same way would treat an idle fleet as an urgent one."""
    assert dbmod.queue_depth(conn) == {"queued": 0, "running": 0, "pinned": 0,
                                       "oldest_age_s": None}


# --------------------------------------------------------- reason codes

def test_busy_and_incapable_are_different_answers(conn):
    """The whole point: the client falls back for ever on one and waits a
    minute on the other."""
    key = machine(conn, "box")
    job_id = queue(conn, "peaks")
    dbmod.claim_job(conn, job_id, *key)          # this machine is now busy
    waiting = queue(conn, "peaks")
    conn.commit()
    assert jobs_mod.explain(conn, waiting)["reason_code"] == jobs_mod.REASON_ALL_BUSY

    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    dbmod.store_machine_capabilities(conn, *key, {"ffmpeg": False},
                                     dbmod.utcnow_iso())
    conn.commit()
    answer = jobs_mod.explain(conn, dbmod.create_job(
        conn, "peaks", {"root": "media"}, {"ffmpeg": True}))
    assert answer["reason_code"] == jobs_mod.REASON_NO_CAPABLE
    assert answer["transient"] is False
    assert answer["capable"] == 0


def test_somebody_at_the_keyboard_is_idle_wait(conn):
    machine(conn, "desk", dict(MEDIA_CAPS, idle_seconds=3))
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    assert answer["reason_code"] == jobs_mod.REASON_IDLE_WAIT
    assert answer["transient"] is True
    # ...and it IS a machine that could do this, which is the number an admin
    # needs before buying hardware.
    assert answer["capable"] == 1


def test_a_fleet_halt_is_its_own_reason(conn):
    machine(conn, "box")
    dbmod.set_fleet_halt(conn, True, "everything stops", "admin")
    conn.commit()
    assert jobs_mod.explain(conn, queue(conn, "peaks"))["reason_code"] == \
        jobs_mod.REASON_HALTED


def test_a_fleet_nobody_has_ever_reported_to_says_so(conn):
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    assert answer["reason_code"] == jobs_mod.REASON_NO_MACHINES


def test_the_worst_answer_wins_not_the_commonest(conn):
    """One machine that could do this if its editor stood up is a fleet that
    will get to it. Answering "no_capable_machine" because four other
    machines have no ffmpeg would send the client off to do the work itself
    for ever."""
    for i in range(4):
        machine(conn, "no-ffmpeg-%d" % i, {"ffmpeg": False, "idle_seconds": 900})
    machine(conn, "capable", dict(MEDIA_CAPS, idle_seconds=2))
    answer = jobs_mod.explain(conn, queue(conn, "peaks", {"ffmpeg": True}))
    assert answer["reason_code"] == jobs_mod.REASON_IDLE_WAIT


# --------------------------------------------------------- the allow-list

def test_a_machine_is_not_offered_a_kind_its_config_excludes(conn):
    """`jobs_enabled = false` was the only tool, and it takes the machine out
    of everything. "This laptop may make a proxy overnight but must never be
    handed a whisper pass" was unsayable until now."""
    key = machine(conn, "laptop", dict(MEDIA_CAPS, job_kinds=["proxy-480p"]))
    peaks = queue(conn, "peaks")
    proxy = queue(conn, "proxy-480p")
    offers = jobs_mod.offers_for_machine(conn, *key)
    assert offers["offered"] == [proxy]
    assert offers["refused"][peaks] == jobs_mod.REFUSE_KIND_NOT_ALLOWED


def test_no_allow_list_is_every_kind(conn):
    """A companion older than phase 4 sends none, and must not be read as
    "no kinds" -- that would take the whole fleet out of the queue on the day
    the dashboard is deployed ahead of the companions."""
    key = machine(conn, "old", dict(MEDIA_CAPS))
    job_id = queue(conn, "peaks")
    assert jobs_mod.offers_for_machine(conn, *key)["offered"] == [job_id]


def test_the_allow_list_is_a_sentence_on_the_why_page(conn):
    machine(conn, "laptop", dict(MEDIA_CAPS, job_kinds=["proxy-480p"]))
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    assert answer["reason_code"] == jobs_mod.REASON_NOT_ALLOWED
    assert "allows only proxy-480p" in answer["machines"][0]["why"]
    # ...and it is NOT counted as a machine that could do this: an admin
    # asking "do I need another box" is asking about hardware, and this is a
    # setting somebody chose.
    assert answer["capable"] == 0


def test_jobs_switched_off_is_its_own_refusal(conn):
    machine(conn, "off", dict(MEDIA_CAPS, jobs_enabled=False))
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    assert answer["machines"][0]["reason"] == jobs_mod.REFUSE_JOBS_DISABLED


# ------------------------------------- the depth on the wire (dash-api-3)
#
# bug-hunt-2026-09-03 dash-api-3: the depth block was sent only when the queue
# was NON-empty, and an empty queue is the one state a companion needs it for.
# jobs_runner.wait_seconds reads a missing depth as "cannot tell" and stays on
# the base cadence, so IDLE_BACKOFF never engaged on any machine in the field.
#
# Version-gated: a companion older than 0.9.65 has no wake event, so telling it
# the fleet is idle would let it sleep up to IDLE_BACKOFF_MAX_SECONDS with a
# job (an admin's RUN NOW included) waiting. Those builds keep the old silence.

@pytest.fixture
def client_env(tmp_path):
    from fastapi.testclient import TestClient

    from ccsync_dashboard import auth
    from ccsync_dashboard.app import create_app
    from ccsync_dashboard.settings import Settings

    projects = tmp_path / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "dash.db"),
                        session_secret="test-secret-not-a-real-one",
                        report_token="companion-token-not-a-real-one",
                        admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        c = dbmod.connect(settings.db_path)
        yield client, c, auth
        c.close()


def _report(client, auth, version, capabilities=None):
    body = {"editor_name": "alex", "machine": "EDIT-PC",
            "companion_version": version,
            "reported_at": dbmod.utcnow_iso(), "lanes": []}
    if capabilities is not None:
        body["capabilities"] = capabilities
    r = client.post("/api/v1/report", json=body, headers={
        "X-CCSync-Token": "companion-token-not-a-real-one",
        "X-CCSync-Identity": auth.make_identity_token(
            "test-secret-not-a-real-one", "alex")})
    assert r.status_code == 200, r.text
    return r.json()["commands"]


def test_an_idle_fleet_tells_a_new_companion_the_queue_is_empty(client_env):
    client, conn, auth = client_env
    cmds = _report(client, auth, "0.9.65", dict(MEDIA_CAPS))
    assert cmds["jobs"]["queue"] == {"queued": 0, "running": 0, "pinned": 0,
                                     "oldest_age_s": None}
    # ...and nothing else: an empty depth is not an offer.
    assert "offered" not in cmds["jobs"]


def test_an_older_companion_still_hears_nothing_on_an_idle_fleet(client_env):
    """0.9.64 cannot be roused from a backed-off sleep, so silence (which it
    reads as "cannot tell") is the safe answer for it."""
    client, conn, auth = client_env
    assert "jobs" not in _report(client, auth, "0.9.64", dict(MEDIA_CAPS))
    assert "jobs" not in _report(client, auth, "", dict(MEDIA_CAPS))


def test_a_machine_with_jobs_switched_off_is_not_sent_a_depth(client_env):
    client, conn, auth = client_env
    caps = dict(MEDIA_CAPS, jobs_enabled=False)
    assert "jobs" not in _report(client, auth, "0.9.65", caps)


def test_a_non_empty_queue_still_reaches_an_older_companion(client_env):
    client, conn, auth = client_env
    queue(conn, "peaks")
    assert _report(client, auth, "0.9.64", dict(MEDIA_CAPS))["jobs"]["queue"]["queued"] == 1
