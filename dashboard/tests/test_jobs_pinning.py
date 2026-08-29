"""Retry, then PIN: the job the fleet gave up on, done here.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §4.4 rule 5, phase 4 (2026-08-30). Phase 1
shipped the retry budget and wrote down why it stopped there: an abandoned job
was visible, and there was no NAS-side executor to hand it to "because there
is none". Phase 3 mounted the Timeline Cards engine in this container, and
that engine IS one.

What this suite defends:

  * a media job whose budget runs out is PINNED when there is an executor and
    ABANDONED when there is not (a job pinned into a queue nothing drains is
    worse than an abandoned one, which at least says so);
  * WHISPER NEVER PINS -- this container has ffmpeg and no GPU;
  * a pinned job never goes back to the fleet: it is offered to nobody, and a
    failure here is abandoned, never re-queued;
  * the handoff resolves (root, rel_path) through THIS container's roots, and
    the `done` it writes carries `result.files` relative to the output root --
    because the Timeline Cards client polling that row may be on another
    server, where /vault means nothing.
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import cards_exec, db as dbmod, jobs as jobs_mod

MEDIA_INPUTS = {
    "root": "media", "rel_path": "FF5/Civil Defence/Interview 3.mp4",
    "out_root": "vault",
    "out_rel": "Vault/2026/FF5/Civil Defence/Script Docs/remote_audio/source",
    "out_stem": "Interview 3",
}


class FakeEngine:
    """The seam, and nothing else (plan §7f). The real one enqueues onto the
    engine's own single ffmpeg worker; what matters here is the contract."""

    def __init__(self, files=("Interview 3.m4a",), raises=None, error=""):
        self.calls: list[tuple] = []
        self.files = list(files)
        self.raises = raises
        self.error = error
        self.stops: list[str] = []

    def fleet_execute(self, kind, source, out_dir, stem,
                      on_progress=None, should_stop=None):
        self.calls.append((kind, source, out_dir, stem))
        if on_progress is not None:
            on_progress(0.5)
        if should_stop is not None:
            self.stops.append(should_stop())
        if self.raises is not None:
            raise self.raises
        if self.error:
            return {"error": self.error}
        return {"files": list(self.files), "seconds": 1.5}


class NoSeamEngine:
    """A checkout from before §7f. NOT an executor: nothing may pin here."""


class Settings:
    def __init__(self, tmp_path, **over):
        self.db_path = str(tmp_path / "dash.db")
        self.cards_root = ""
        self.cards_vault_root = str(tmp_path / "vault")
        self.projects_dir = str(tmp_path / "projects")
        self.jobs_roots = {"media": str(tmp_path / "media")}
        self.jobs_cooldown_seconds = 120.0
        for k, v in over.items():
            setattr(self, k, v)


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "dash.db")
    dbmod.migrate(c)
    yield c
    c.close()


def spend_the_budget(conn, kind="peaks", pin=False, inputs=None):
    """Fail one job as many times as its budget allows. -> (id, last state)."""
    job_id = dbmod.create_job(conn, kind,
                              dict(inputs if inputs is not None else MEDIA_INPUTS),
                              {})
    state = None
    for i in range(dbmod.job_retry_budget(kind)):
        assert dbmod.claim_job(conn, job_id, "alex", "box-%d" % i)
        state = dbmod.fail_job(conn, job_id, "alex", "box-%d" % i,
                               error="ffmpeg died", pin=pin)
    conn.commit()
    return job_id, state


# ------------------------------------------------- pinned or abandoned

def test_a_media_job_the_fleet_cannot_finish_is_pinned(conn):
    job_id, state = spend_the_budget(conn, "peaks", pin=True)
    assert state == dbmod.JOB_PINNED
    assert dbmod.get_job(conn, job_id)["state"] == "pinned"


def test_with_no_executor_it_is_abandoned_exactly_as_before(conn):
    _job_id, state = spend_the_budget(conn, "peaks", pin=False)
    assert state == dbmod.JOB_ABANDONED


def test_whisper_never_pins(conn):
    """This container has ffmpeg and no GPU. A pinned whisper job would be a
    job that fails for ever in a new place."""
    _job_id, state = spend_the_budget(conn, "whisper", pin=True)
    assert state == dbmod.JOB_ABANDONED


def test_a_lost_lease_pins_too(conn):
    """The budget can run out by silence as easily as by a reported failure."""
    job_id = dbmod.create_job(conn, "audio-extract", dict(MEDIA_INPUTS), {})
    for i in range(dbmod.job_retry_budget("audio-extract")):
        dbmod.claim_job(conn, job_id, "alex", "box-%d" % i, lease_seconds=0)
        dbmod.expire_leases(conn, pin=True)
    conn.commit()
    assert dbmod.get_job(conn, job_id)["state"] == "pinned"


def test_a_pinned_job_is_offered_to_nobody(conn):
    """One-way, and that is the point of rule 5: the fleet already spent the
    budget on it."""
    dbmod.upsert_machine_state(conn, "alex", "box", None, dbmod.utcnow_iso())
    dbmod.store_machine_capabilities(
        conn, "alex", "box",
        {"ffmpeg": True, "ffprobe": True, "mounts": ["vault", "media"],
         "idle_seconds": 900}, dbmod.utcnow_iso())
    job_id, _state = spend_the_budget(conn, "peaks", pin=True)
    # the cooldown from the last failure is on box-1, not on this one
    offers = jobs_mod.offers_for_machine(conn, "alex", "box")
    assert job_id not in offers["offered"]
    assert dbmod.queued_jobs(conn) == []


def test_why_explains_the_pin(conn):
    job_id, _state = spend_the_budget(conn, "peaks", pin=True)
    answer = jobs_mod.explain(conn, job_id)
    assert answer["reason_code"] == jobs_mod.REASON_PINNED
    assert "pinned to the dashboard" in answer["summary"]


def test_can_pin_is_false_without_an_engine(tmp_path):
    class App:
        class state:
            pinned_executor = cards_exec.PinnedExecutor(
                Settings(tmp_path), NoSeamEngine())

    assert jobs_mod.can_pin(App) is False
    assert "no fleet_execute" in App.state.pinned_executor.why_not()


def test_can_pin_is_true_with_the_seam(tmp_path):
    class App:
        class state:
            pinned_executor = cards_exec.PinnedExecutor(
                Settings(tmp_path), FakeEngine())

    assert jobs_mod.can_pin(App) is True


# ----------------------------------------------------------- the handoff

def executor(tmp_path, engine):
    return cards_exec.PinnedExecutor(Settings(tmp_path), engine)


def test_the_executor_finishes_a_pinned_job_and_the_client_sees_done(
        tmp_path, conn):
    job_id, _s = spend_the_budget(conn, "audio-extract", pin=True)
    engine = FakeEngine()
    assert executor(tmp_path, engine).tick(conn) == [job_id]
    kind, source, out_dir, stem = engine.calls[0]
    assert kind == "audio-extract"
    assert source.replace("\\", "/").endswith(
        "media/FF5/Civil Defence/Interview 3.mp4")
    assert out_dir.replace("\\", "/").endswith("remote_audio/source")
    assert stem == "Interview 3"
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == "done"
    # PATHS RELATIVE TO THE OUTPUT ROOT, with the root beside them: the
    # client polling this row may be on another server.
    assert job["result"]["files"] == [
        "Vault/2026/FF5/Civil Defence/Script Docs/remote_audio/source/"
        "Interview 3.m4a"]
    assert job["result"]["out_root"] == "vault"
    assert job["result"]["executor"] == dbmod.PIN_HOLDER


def test_progress_reaches_the_row_while_it_runs(tmp_path, conn):
    job_id, _s = spend_the_budget(conn, "proxy-480p", pin=True)
    seen = {}

    class Watching(FakeEngine):
        def fleet_execute(self, kind, source, out_dir, stem,
                          on_progress=None, should_stop=None):
            on_progress(0.42)
            seen["progress"] = dbmod.get_job(conn, job_id)["progress"]
            return {"files": []}

    executor(tmp_path, Watching()).tick(conn)
    assert seen["progress"] == pytest.approx(0.42)


def test_a_failure_here_is_abandoned_never_re_queued(tmp_path, conn):
    job_id, _s = spend_the_budget(conn, "peaks", pin=True)
    executor(tmp_path, FakeEngine(raises=RuntimeError("no ffmpeg"))).tick(conn)
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == "abandoned"
    assert "no ffmpeg" in job["last_error"]
    assert dbmod.queued_jobs(conn) == []


def test_an_engine_that_answers_with_an_error_is_not_a_success(tmp_path, conn):
    job_id, _s = spend_the_budget(conn, "peaks", pin=True)
    executor(tmp_path, FakeEngine(error="the clip has no audio")).tick(conn)
    assert dbmod.get_job(conn, job_id)["state"] == "abandoned"


def test_a_root_this_container_does_not_have_fails_with_a_sentence(
        tmp_path, conn):
    job_id, _s = spend_the_budget(
        conn, "peaks", pin=True,
        inputs=dict(MEDIA_INPUTS, root="footage"))
    executor(tmp_path, FakeEngine()).tick(conn)
    job = dbmod.get_job(conn, job_id)
    assert job["state"] == "abandoned"
    assert "DASH_JOBS_ROOTS" in job["last_error"]


def test_a_path_that_leaves_its_root_is_refused(tmp_path, conn):
    with pytest.raises(cards_exec.ExecutorError):
        cards_exec.resolve({"vault": "/vault"}, "vault", "../etc/passwd")


def test_two_ticks_cannot_both_take_one_job(tmp_path, conn):
    job_id, _s = spend_the_budget(conn, "peaks", pin=True)
    assert dbmod.take_pinned_job(conn, job_id) is True
    assert dbmod.take_pinned_job(conn, job_id) is False
    # ...and the one in hand is not offered to a second tick either
    assert dbmod.pinned_jobs(conn) == []


def test_a_container_that_died_mid_encode_releases_its_jobs_at_boot(
        tmp_path, conn):
    job_id, _s = spend_the_budget(conn, "peaks", pin=True)
    dbmod.take_pinned_job(conn, job_id)
    assert dbmod.release_pinned_jobs(conn) == 1
    assert [j["id"] for j in dbmod.pinned_jobs(conn)] == [job_id]


def test_an_executor_without_the_seam_runs_nothing(tmp_path, conn):
    job_id, _s = spend_the_budget(conn, "peaks", pin=True)
    assert executor(tmp_path, NoSeamEngine()).tick(conn) == []
    assert dbmod.get_job(conn, job_id)["state"] == "pinned"


def test_the_container_roots_come_from_what_this_deployment_already_has(
        tmp_path):
    roots = cards_exec.container_roots(Settings(tmp_path))
    assert roots["vault"] == str(tmp_path / "vault")
    assert roots["tree"] == str(tmp_path / "projects")
    assert roots["media"] == str(tmp_path / "media")
