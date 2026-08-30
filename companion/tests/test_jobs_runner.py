"""The fleet job runner: the gate, the claim, the child, the answer.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 0 (2026-08-29). The dashboard is a
fake here and `pipeline.py transcribe` is a two-line python script that writes
a marker, so this suite runs on any machine: what is being tested is the
loop's judgement, not whisper.

The properties defended, each of them a way an editor's machine gets hurt:

  * nothing is claimed while somebody is at the keyboard, and "cannot tell"
    counts as somebody (idle.py's contract);
  * nothing is claimed while Resolve is open, or under a fleet halt;
  * never two jobs at once on one machine;
  * a halt arriving mid-run stops the child and hands the job BACK;
  * a path this machine cannot place fails the job with a sentence, not a
    traceback -- and retryably, because another machine may have that root.

Phase 1 (2026-08-30) adds the media half at the bottom: the dispatch by kind,
the two roots a media job names, the progress that rides the heartbeat, and a
lost lease stopping a recipe instead of letting two machines write one file.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ccsync_companion import job_paths
from ccsync_companion import jobs_runner as runner_mod


class FakeIdle:
    def __init__(self, value):
        self.value = value

    def seconds_idle(self):
        return self.value


class FakeDashboard:
    """The three fleet routes, in a dict."""

    def __init__(self, job=None):
        self.job = job
        self.calls: list[tuple[str, dict]] = []
        self.results: list[dict] = []
        self.heartbeat_status = 200
        self.claims = 0

    def request(self, method, url, body, headers, timeout):
        suffix = url.split("/api/v1/jobs", 1)[1]
        self.calls.append((suffix, body or {}))
        if suffix == "/claim":
            self.claims += 1
            job, self.job = self.job, None      # one job, once: a second
            return 200, {"job": job}            # claim must come back empty
        if suffix.endswith("/heartbeat"):
            return self.heartbeat_status, {"ok": True}
        if suffix.endswith("/result"):
            self.results.append(body)
            return 200, {"ok": True}
        return 404, None


def a_job(tmp_path, **inputs):
    base = {"root": "vault", "rel_path": "Vault/2026/FF5/Ep/Youtube/Interview 3",
            "episode_rel": "Vault/2026/FF5/Ep"}
    base.update(inputs)
    return {"id": 7, "kind": "whisper", "inputs": base}


def a_pipeline(tmp_path, body="import sys; print('11.4x realtime overall')"):
    """A fake MulticamPipeline checkout whose pipeline.py writes a marker."""
    checkout = tmp_path / "MulticamPipeline"
    checkout.mkdir(parents=True, exist_ok=True)
    (checkout / "pipeline.py").write_text(
        "import sys, pathlib\n"
        "pathlib.Path(sys.argv[0]).with_name('ran.json').write_text("
        "__import__('json').dumps(sys.argv[1:]))\n" + body + "\n",
        encoding="utf-8")
    return checkout


def a_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Vault/2026/FF5/Ep/Youtube/Interview 3").mkdir(parents=True)
    (vault / "Vault/2026/FF5/Ep/Clips/Interview 3").mkdir(parents=True)
    (vault / "Vault/2026/FF5/Ep/Clips/Interview 3/Interview 3_words.json").write_text(
        "{}", encoding="utf-8")
    return vault


def cfg(tmp_path, **over):
    (tmp_path / "tree").mkdir(exist_ok=True)
    base = {
        "local_root": str(tmp_path / "tree"),
        "dashboard_url": "http://dash.example",
        "dashboard_token": "tok",
        "jobs_vault_root": str(tmp_path / "vault"),
        "jobs_whisper_python": sys.executable,
        "jobs_mulcam_pipeline": str(tmp_path / "MulticamPipeline"),
        "jobs_idle_seconds": 300,
        "jobs_skip_while_resolve_running": True,
    }
    base.update(over)
    return base


def make(tmp_path, dashboard, caps=None, idle=900, resolve=False, halted=False,
         **cfg_over):
    return runner_mod.JobRunner(
        cfg(tmp_path, **cfg_over),
        request_fn=dashboard.request,
        identity_token_fn=lambda: "identity",
        capabilities_fn=lambda: (caps if caps is not None else {"whisper": True}),
        idle_probe=FakeIdle(idle),
        resolve_running_fn=lambda: resolve,
        halted_fn=lambda: halted,
        machine_name="EDIT-PC",
    )


# ---------------------------------------------------------------- the gate

def test_nothing_offered_means_nothing_claimed(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    assert r.tick() is None
    assert dash.claims == 0


def test_somebody_at_the_keyboard_stops_a_claim(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_USER_ACTIVE
    assert dash.claims == 0


def test_an_unknown_idle_answer_counts_as_somebody(tmp_path):
    """idle.py's contract on this side of the wire too."""
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=None)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_USER_ACTIVE


def test_resolve_open_stops_a_claim(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, resolve=True)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_RESOLVE_OPEN


def test_a_resolve_probe_that_cannot_answer_stops_a_claim(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r._resolve_running_fn = lambda: (_ for _ in ()).throw(OSError("no tasklist"))
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_RESOLVE_OPEN


def test_a_fleet_halt_stops_a_claim(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, halted=True)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_HALTED


def test_no_capability_means_no_claim(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, caps={"whisper": False})
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_NO_CAPABILITY


def test_jobs_disabled_in_the_config_is_the_first_answer(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, jobs_enabled=False)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_DISABLED


def test_no_dashboard_means_no_claim(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, dashboard_url="")
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None


def test_a_malformed_offer_block_is_ignored(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": "seven"}}})
    r.note_report_reply({"commands": None})
    r.note_report_reply("not a dict")
    assert r.status()["offered"] == []


# -------------------------------------------------------------- the work

def test_it_runs_the_pipeline_and_reports_the_files(tmp_path):
    a_vault(tmp_path)
    checkout = a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is not None
    argv = json.loads((checkout / "ran.json").read_text(encoding="utf-8"))
    assert argv[0] == "transcribe"
    assert argv[1] == "--folder"
    assert argv[2].endswith("Interview 3")
    assert argv[3] == "--root"
    assert argv[4].endswith("Ep")
    assert "--speakers" not in argv
    result = dash.results[-1]
    assert result["ok"] is True
    assert result["result"]["files"] == ["Clips/Interview 3/Interview 3_words.json"]
    assert result["result"]["realtime"] == 11.4


def test_speakers_rides_when_the_job_asks_for_it(tmp_path):
    a_vault(tmp_path)
    checkout = a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path, speakers=True))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    assert "--speakers" in json.loads((checkout / "ran.json").read_text())


def test_a_failing_pipeline_is_a_retryable_failure(tmp_path):
    a_vault(tmp_path)
    a_pipeline(tmp_path, body="import sys; sys.exit(2)")
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    result = dash.results[-1]
    assert result["ok"] is False
    assert result["retryable"] is True
    assert "exited 2" in result["error"]


def test_a_path_this_machine_cannot_place_fails_with_a_sentence(tmp_path):
    a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    # No vault root here at all.
    r = make(tmp_path, dash, jobs_vault_root="")
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    result = dash.results[-1]
    assert result["ok"] is False
    assert "no vault root" in result["error"]
    # RETRYABLE: another machine may well have the vault.
    assert result["retryable"] is True


def test_a_kind_this_build_cannot_run_is_handed_straight_back(tmp_path):
    a_vault(tmp_path)
    a_pipeline(tmp_path)
    job = a_job(tmp_path)
    # `resolve-edit` is the example on purpose and it will never stop being
    # one: section 4.2's last two rows must never become schedulable, so a
    # build that somehow claimed one has to hand it back rather than invent a
    # runner. (This test used to say `proxy-480p`; phase 1 made that a kind
    # this build DOES run.)
    job["kind"] = "resolve-edit"
    dash = FakeDashboard(job)
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    result = dash.results[-1]
    assert result["ok"] is False
    assert result["retryable"] is False, "a kind loop between the two sides is invisible"


def test_only_one_job_at_a_time(tmp_path, monkeypatch):
    """The gate must refuse while a job is in flight, not merely 'usually'."""
    a_vault(tmp_path)
    a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    seen: list[str] = []

    real_execute = r._execute

    def execute(job):
        # Re-entering the loop while this job runs must claim nothing.
        seen.append(r._gate())
        return real_execute(job)

    monkeypatch.setattr(r, "_execute", execute)
    r.tick()
    assert seen == [runner_mod.STATE_RUNNING]
    assert dash.claims == 1


def test_a_halt_mid_run_stops_the_child_and_hands_the_job_back(tmp_path):
    a_vault(tmp_path)
    # A pipeline that would run for a minute if nothing stopped it.
    a_pipeline(tmp_path, body="import time; time.sleep(60)")
    dash = FakeDashboard(a_job(tmp_path))
    halted = {"now": False}
    r = make(tmp_path, dash)
    r._halted_fn = lambda: halted["now"]
    # Beat (and therefore check the halt) immediately rather than in 30 s.
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    original = r._heartbeat

    def beat(job_id):
        halted["now"] = True
        return original(job_id)

    r._heartbeat = beat
    runner_mod.HEARTBEAT_SECONDS_ORIGINAL = runner_mod.HEARTBEAT_SECONDS
    runner_mod.HEARTBEAT_SECONDS = 0.5
    try:
        r.tick()
    finally:
        runner_mod.HEARTBEAT_SECONDS = runner_mod.HEARTBEAT_SECONDS_ORIGINAL
    result = dash.results[-1]
    assert result["ok"] is False
    assert "halt" in result["error"]
    assert result["retryable"] is True


def test_a_lost_lease_stops_the_child(tmp_path):
    a_vault(tmp_path)
    a_pipeline(tmp_path, body="import time; time.sleep(60)")
    dash = FakeDashboard(a_job(tmp_path))
    dash.heartbeat_status = 410
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    runner_mod.HEARTBEAT_SECONDS_ORIGINAL = runner_mod.HEARTBEAT_SECONDS
    runner_mod.HEARTBEAT_SECONDS = 0.5
    try:
        r.tick()
    finally:
        runner_mod.HEARTBEAT_SECONDS = runner_mod.HEARTBEAT_SECONDS_ORIGINAL
    assert dash.results[-1]["error"] == "the lease was lost"


def test_the_claim_body_carries_this_machine_and_its_capabilities(tmp_path):
    a_vault(tmp_path)
    a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, caps={"whisper": True, "idle_seconds": 900})
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    suffix, body = dash.calls[0]
    assert suffix == "/claim"
    assert body["machine"] == "EDIT-PC"
    assert body["capabilities"]["idle_seconds"] == 900
    assert body["kinds"] == ["whisper"]


def test_the_realtime_parser(tmp_path):
    assert runner_mod._parse_realtime("whisper 8.0x realtime\n11.4x realtime overall") == 11.4
    assert runner_mod._parse_realtime("nothing here") is None


# ============================================================ phase 1: media
#
# The dispatch, the paths and the heartbeat -- with no ffmpeg anywhere. What
# the recipes DO is test_jobs_media.py's job; what is defended here is the
# loop around them, which is where an editor's machine gets hurt.

class FakeRecipe:
    """A MediaJob that records what it was asked for and reports progress."""

    calls: list = []

    def __init__(self, **kw):
        self.kw = kw
        FakeRecipe.calls.append(kw)

    def run(self, kind, source, out_dir, stem):
        sink = self.kw.get("on_progress")
        if sink is not None:
            sink(0.5)
        return {"files": [f"{stem}.480p.mp4"], "seconds": 3.3,
                "realtime": 11.0, "skipped": False}


def media_cfg(tmp_path, **over):
    media = tmp_path / "media"
    (media / "FF5").mkdir(parents=True, exist_ok=True)
    (media / "FF5" / "Interview.mp4").write_bytes(b"x")
    vault = tmp_path / "vault"
    (vault / "V/Ep/Script Docs/remote_audio/source").mkdir(parents=True,
                                                           exist_ok=True)
    return cfg(tmp_path, jobs_media_root=str(media), **over)


def a_media_job(kind="proxy-480p", **inputs):
    base = {"root": "media", "rel_path": "FF5/Interview.mp4",
            "out_root": "vault", "out_rel": "V/Ep/Script Docs/remote_audio/source"}
    base.update(inputs)
    return {"id": 9, "kind": kind, "inputs": base}


MEDIA_CAPS = {"ffmpeg": True, "ffprobe": True}


def media_runner(tmp_path, dashboard, caps=None, **over):
    return runner_mod.JobRunner(
        media_cfg(tmp_path, **over),
        request_fn=dashboard.request,
        identity_token_fn=lambda: "identity",
        capabilities_fn=lambda: (MEDIA_CAPS if caps is None else caps),
        idle_probe=FakeIdle(900),
        resolve_running_fn=lambda: False,
        halted_fn=lambda: False,
        machine_name="EDIT-PC",
    )


def test_a_machine_asks_only_for_the_kinds_it_can_run(tmp_path):
    """A claim that named a kind this build has no runner for is a job taken
    off the queue and handed straight back, and the dashboard's kind filter
    is the thing that should have stopped it."""
    dash = FakeDashboard()
    assert media_runner(tmp_path, dash).runnable_kinds() == [
        "proxy-480p", "audio-extract", "peaks"]
    both = media_runner(tmp_path, dash,
                        caps={"whisper": True, "ffmpeg": True, "ffprobe": True})
    assert both.runnable_kinds() == ["whisper", "proxy-480p", "audio-extract",
                                     "peaks"]


def test_ffmpeg_without_ffprobe_is_not_a_media_machine(tmp_path):
    """Both or neither: every recipe probes before it encodes -- the GOP comes
    from the source's frame rate and the copy check from its duration -- so a
    machine with ffmpeg alone would claim the work and then guess."""
    r = media_runner(tmp_path, FakeDashboard(),
                     caps={"ffmpeg": True, "ffprobe": False})
    assert r.runnable_kinds() == []
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    assert r.tick() is None
    assert r.status()["state"] == runner_mod.STATE_NO_CAPABILITY


def test_a_media_job_places_both_roots_and_names_the_output(tmp_path):
    r = media_runner(tmp_path, FakeDashboard())
    source, out_dir, stem, out_root, out_rel = r._media_paths(a_media_job())
    assert source == (tmp_path / "media" / "FF5" / "Interview.mp4").resolve()
    assert out_dir == (tmp_path / "vault" / "V/Ep/Script Docs"
                       / "remote_audio/source").resolve()
    assert (stem, out_root, out_rel) == (
        "Interview", "vault", "V/Ep/Script Docs/remote_audio/source")


def test_the_page_may_name_the_clip_itself(tmp_path):
    """`out_stem` is the name the PAGE knows this clip by (its multicam
    name), which is not always the media file's own stem -- and defaulting to
    the file's stem is right for everything else."""
    r = media_runner(tmp_path, FakeDashboard())
    _src, _dir, stem, _root, _rel = r._media_paths(
        a_media_job(out_stem="Interview 3 (cam B)"))
    assert stem == "Interview 3 (cam B)"


def test_a_media_job_with_no_output_directory_is_refused_with_a_sentence(tmp_path):
    """Nothing anywhere guesses where a cache belongs in somebody's vault."""
    r = media_runner(tmp_path, FakeDashboard())
    with pytest.raises(job_paths.JobPathError) as caught:
        r._media_paths(a_media_job(out_rel=""))
    assert "out_root + out_rel" in str(caught.value)


def test_a_media_job_runs_and_reports_paths_relative_to_the_output_root(
        tmp_path, monkeypatch):
    """An absolute path in a result row means something different on every
    machine that reads it later (section 4.1, applied to the answer)."""
    FakeRecipe.calls = []
    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job())
    r = media_runner(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    assert r.tick() is not None
    posted = dash.results[-1]
    assert posted["ok"] is True
    assert posted["result"]["out_root"] == "vault"
    assert posted["result"]["files"] == [
        "V/Ep/Script Docs/remote_audio/source/Interview.480p.mp4"]
    assert posted["result"]["realtime"] == 11.0


def test_the_recipe_is_told_what_this_machine_reported_about_nvenc(
        tmp_path, monkeypatch):
    """The capability, not a wish: the argv can never name an encoder this
    machine's ffmpeg does not have."""
    FakeRecipe.calls = []
    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job())
    r = media_runner(tmp_path, dash, caps=dict(MEDIA_CAPS, nvenc=True))
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    r.tick()
    assert FakeRecipe.calls[-1]["nvenc"] is True


def test_a_recipe_that_refuses_permanently_is_not_retried_elsewhere(
        tmp_path, monkeypatch):
    """A file with no audio track has none on every machine in the fleet, and
    a job that toured the fleet failing identically is three machines'
    evenings spent proving one thing."""
    class NoAudio(FakeRecipe):
        def run(self, *a, **kw):
            raise runner_mod.jobs_media.MediaJobError("no audio track",
                                                      retryable=False)

    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", NoAudio)
    dash = FakeDashboard(a_media_job("audio-extract"))
    r = media_runner(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    r.tick()
    assert dash.results[-1]["ok"] is False
    assert dash.results[-1]["retryable"] is False
    assert dash.results[-1]["error"] == "no audio track"


def test_a_root_this_machine_lacks_fails_the_job_retryably(tmp_path, monkeypatch):
    """Another machine may have the share mounted where this one does not --
    which is the entire reason a job's paths are (root, rel_path) pairs."""
    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", FakeRecipe)
    dash = FakeDashboard(a_media_job())
    r = media_runner(tmp_path, dash)
    r.cfg["jobs_media_root"] = str(tmp_path / "not-mounted")
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    r.tick()
    assert dash.results[-1]["ok"] is False
    assert dash.results[-1]["retryable"] is True
    assert "media root" in dash.results[-1]["error"]


def test_a_heartbeat_carries_the_percentage_the_recipe_published(
        tmp_path, monkeypatch):
    """The fleet chip's number. It rides the heartbeat rather than a second
    channel because the lease is the thing that has to keep being renewed
    anyway."""
    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 0.05)

    class SlowRecipe(FakeRecipe):
        def run(self, kind, source, out_dir, stem):
            self.kw["on_progress"](0.62)
            time.sleep(0.25)
            return {"files": [f"{stem}.480p.mp4"], "seconds": 1.0,
                    "skipped": False}

    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", SlowRecipe)
    dash = FakeDashboard(a_media_job())
    r = media_runner(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    r.tick()
    beats = [body for suffix, body in dash.calls if suffix.endswith("/heartbeat")]
    assert beats, "no heartbeat was sent while the recipe ran"
    assert beats[-1]["progress"] == 0.62


def test_a_recipe_with_no_fraction_heartbeats_without_one(tmp_path, monkeypatch):
    """None, never 0: a peaks pass reads its input in one gulp, and a machine
    reported at 0% for two minutes looks wedged."""
    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 0.05)

    class Quiet(FakeRecipe):
        def run(self, kind, source, out_dir, stem):
            time.sleep(0.2)
            return {"files": [f"{stem}.peaks"], "seconds": 1.0, "skipped": False}

    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", Quiet)
    dash = FakeDashboard(a_media_job("peaks"))
    r = media_runner(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    r.tick()
    beats = [body for suffix, body in dash.calls if suffix.endswith("/heartbeat")]
    assert beats and all("progress" not in body for body in beats)


def test_a_lost_lease_stops_the_recipe_rather_than_finishing_it(
        tmp_path, monkeypatch):
    """410 is the dashboard saying the job is somebody else's now. Carrying on
    would mean two machines writing one output -- the thing the lease and rule
    2 both exist to stop."""
    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 0.05)
    stops: list = []

    class Watching(FakeRecipe):
        def run(self, kind, source, out_dir, stem):
            for _ in range(50):
                reason = self.kw["should_stop"]()
                if reason:
                    stops.append(reason)
                    raise runner_mod.jobs_media.MediaJobError(reason)
                time.sleep(0.02)
            return {"files": [], "seconds": 1.0, "skipped": False}

    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", Watching)
    dash = FakeDashboard(a_media_job())
    dash.heartbeat_status = 410
    r = media_runner(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    r.tick()
    assert stops == ["the lease was lost"]
    assert dash.results[-1]["ok"] is False


def test_a_skipped_job_is_still_a_success(tmp_path, monkeypatch):
    """A fleet that re-encodes what it already has is a fleet doing nothing
    useful loudly, and a job that found its file already made DID the thing
    that was asked."""
    class Skipper(FakeRecipe):
        def run(self, kind, source, out_dir, stem):
            return {"files": [f"{stem}.peaks"], "seconds": 0.1, "skipped": True}

    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", Skipper)
    dash = FakeDashboard(a_media_job("peaks"))
    r = media_runner(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    r.tick()
    assert dash.results[-1]["ok"] is True
    assert dash.results[-1]["result"]["skipped"] is True


# ================================ section 10: force, volunteer and progress
#
# docs/TIMELINE-CARDS-INTO-CCSYNC.md section 10 (2026-08-30). Two levers a
# PERSON pulls -- the one at the machine volunteering it, the admin forcing a
# job -- and the progress a whisper pass never reported. What is defended here
# is that each lever opens exactly the gate it is meant to and no other, and
# that the fraction is never invented.

def test_volunteering_opens_the_gate_with_somebody_at_the_keyboard(tmp_path):
    a_vault(tmp_path)
    a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.tick() is None, "the ordinary gate still shuts"
    assert r.volunteer(30)
    assert r.volunteering is True
    assert r.tick() is not None
    assert dash.claims == 1


def test_volunteering_opens_the_resolve_gate_too(tmp_path):
    """Both gates, because the person clicking it can see their own Resolve
    and has decided they do not mind."""
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, resolve=True)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r._gate() == runner_mod.STATE_RESOLVE_OPEN
    r.volunteer(None)
    assert r._gate() == runner_mod.STATE_READY


def test_volunteering_never_opens_a_halt_or_a_missing_capability(tmp_path):
    """"Do not wait for anybody to leave" is not "run on a machine that
    cannot" -- section 10.1's rule, on this side of it."""
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12, halted=True)
    r.volunteer(None)
    assert r._gate() == runner_mod.STATE_HALTED
    r2 = make(tmp_path, dash, idle=12, caps={"whisper": False})
    r2.volunteer(None)
    assert r2._gate() == runner_mod.STATE_NO_CAPABILITY


def test_the_volunteer_timer_running_out_closes_the_gate_again(tmp_path):
    """A TIMER, not a toggle: somebody who lends their machine and walks away
    gets it back without having to remember they lent it."""
    dash = FakeDashboard(a_job(tmp_path))
    now = {"t": 1000.0}
    r = make(tmp_path, dash, idle=12)
    r._clock = lambda: now["t"]
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.volunteer(30)
    assert r._gate() == runner_mod.STATE_READY
    now["t"] += 29 * 60
    assert r._gate() == runner_mod.STATE_READY
    now["t"] += 2 * 60
    assert r._gate() == runner_mod.STATE_USER_ACTIVE
    assert r.status()["volunteer_until"] is None
    assert dash.claims == 0


def test_volunteer_zero_hands_the_machine_straight_back(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.volunteer(None) is not None
    assert r.volunteer(0) is None
    assert r.volunteering is False
    assert r.status()["volunteer_until"] is None
    assert r._gate() == runner_mod.STATE_USER_ACTIVE


def test_the_volunteer_deadline_is_iso_utc_and_the_configured_default(tmp_path):
    """The dashboard cannot read this machine's monotonic clock, so the report
    carries a wall-clock deadline it can compare with its own now."""
    from datetime import datetime, timezone

    dash = FakeDashboard(None)
    r = make(tmp_path, dash, jobs_volunteer_minutes=45)
    until = r.volunteer(None)
    assert until == r.volunteer_until_iso
    parsed = datetime.fromisoformat(until)
    assert parsed.tzinfo is not None
    ahead = (parsed - datetime.now(timezone.utc)).total_seconds()
    assert 44 * 60 < ahead <= 45 * 60


def test_a_forced_job_claims_by_id_through_a_closed_gate(tmp_path):
    """The admin's lever. The claim names the ids so the dashboard can only
    ever narrow what comes back: a machine whose gate is shut must not pick up
    the ordinary job offered beside the forced one."""
    a_vault(tmp_path)
    a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [5, 7], "forced": [7]}}})
    assert r.tick() is not None
    suffix, body = dash.calls[0]
    assert suffix == "/claim"
    assert body["ids"] == [7]
    assert r.status()["forced"] == [7]


def test_a_forced_job_says_so_while_it_runs(tmp_path, monkeypatch):
    """STATE_FORCED, so the tray and the diagnostics can say why a job started
    with the editor present instead of looking like a broken idle gate."""
    a_vault(tmp_path)
    a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [7], "forced": [7]}}})
    seen: list[str] = []
    real_execute = r._execute

    def execute(job):
        seen.append(r.status()["state"])
        return real_execute(job)

    monkeypatch.setattr(r, "_execute", execute)
    r.tick()
    assert seen == [runner_mod.STATE_FORCED]
    assert r.status()["state"] == runner_mod.STATE_NOTHING_OFFERED


def test_a_forced_id_this_machine_was_not_offered_is_ignored(tmp_path):
    """The offer is still the invitation. A forced id nobody offered this
    machine is a stale reply, not permission."""
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [5], "forced": [7]}}})
    assert r._gate() == runner_mod.STATE_USER_ACTIVE
    assert r.tick() is None
    assert dash.claims == 0


def test_an_ordinary_claim_names_no_ids(tmp_path):
    """`ids` rides ONLY a forced claim: an open gate claiming by id would
    narrow what the scheduler is allowed to hand out for no reason."""
    a_vault(tmp_path)
    a_pipeline(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7], "forced": [7]}}})
    r.tick()
    assert "ids" not in dash.calls[0][1]


def test_a_dashboard_too_old_to_send_forced_changes_nothing(tmp_path):
    r = make(tmp_path, FakeDashboard(None), idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert r.status()["forced"] == []
    r.note_report_reply({"commands": {"jobs": {"offered": [7], "forced": "all"}}})
    assert r.status()["forced"] == []


# --------------------------------------------------------- whisper progress

def test_the_whisper_progress_parser():
    """The corpus stage's own four lines, and nothing else. The per-file
    summary sits at the SAME indent as the progress line, which is why the
    pattern is anchored rather than searched for."""
    state: dict = {}
    p = runner_mod.whisper_progress
    assert p("12 media file(s), 3 already transcribed, 9 to do", state) is None
    assert state["total"] == 9
    # None, never 0: a machine reported at 0% looks stuck, one reported as
    # unknown shows its job id (db.clamp_progress's rule).
    assert p("[1/9] Interview 3.mp4", state) is None
    assert p("        45s / 90s", state) == pytest.approx(0.5 / 9)
    assert p("[2/9] Interview 4.mp4", state) == pytest.approx(1 / 9)
    assert p("        30s / 60s", state) == pytest.approx(1 / 9 + 0.5 / 9)
    # A duration nothing could measure holds at the file boundary rather than
    # dividing by nothing.
    assert p("        12s / 0s", state) == pytest.approx(1 / 9)
    assert p("done: 9 transcribed, 0 failed, 3 skipped", state) == 1.0


def test_the_whisper_parser_ignores_every_other_line():
    state: dict = {"total": 9, "base": 1 / 9}
    p = runner_mod.whisper_progress
    for line in ("[load] large-v3 on cuda/float16 in 8.1s",
                 "        lang=zh 41s audio in 3.6s (11.4x realtime), 900 words",
                 "        speakers: 3 in 42 turn(s)",
                 "        FAILED: no audio stream",
                 "[skip] Interview 3 -- a clip of that stem is already in this run",
                 "", "Traceback (most recent call last):"):
        assert p(line, state) is None, line


def test_a_run_with_nothing_to_do_reports_none_before_it_finishes():
    state: dict = {}
    assert runner_mod.whisper_progress(
        "4 media file(s), 4 already transcribed, 0 to do", state) is None
    assert state["total"] == 0


def test_the_progress_rides_the_heartbeat_early_when_it_moves(
        tmp_path, monkeypatch):
    """The 30 s beat is sized against the LEASE, not against a progress bar.
    Without the early one the chip sat still for half a minute at a time --
    and section 7f's whole point was telling working from wedged."""
    monkeypatch.setattr(runner_mod, "PROGRESS_MIN_SECONDS", 0.05)
    a_vault(tmp_path)
    a_pipeline(tmp_path, body=(
        "import time\n"
        "print('2 media file(s), 0 already transcribed, 2 to do', flush=True)\n"
        "print('[1/2] A.mp4', flush=True)\n"
        "print('        50s / 100s', flush=True)\n"
        "time.sleep(0.4)\n"
        "print('        100s / 100s', flush=True)\n"
        "time.sleep(0.4)\n"
        "print('done: 2 transcribed, 0 failed, 0 skipped', flush=True)\n"
        "time.sleep(0.4)\n"))
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    beats = [body.get("progress") for suffix, body in dash.calls
             if suffix.endswith("/heartbeat")]
    assert beats, "a job that runs for a second must still beat once it moves"
    assert beats[0] == pytest.approx(0.25)
    assert beats[-1] == pytest.approx(1.0)
    assert dash.results[-1]["ok"] is True


def test_the_childs_output_still_rides_the_result(tmp_path):
    """The drain thread replaced communicate(), and the tail is what
    _parse_realtime reads -- so losing it would lose the one number that says
    whether handing this work to another machine was worth it."""
    a_vault(tmp_path)
    a_pipeline(tmp_path, body=(
        "print('[1/1] A.mp4')\n"
        "print('done: 1 transcribed, 0 failed, 0 skipped (11.4x realtime overall)')\n"))
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    result = dash.results[-1]
    assert result["ok"] is True
    assert "[1/1] A.mp4" in result["result"]["output"]
    assert result["result"]["realtime"] == 11.4
