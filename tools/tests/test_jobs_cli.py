r"""tools/jobs.py -- submit / list / why / watch against the job API.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 0. Same venv and invocation as
test_publish_package.py, and the same shape: no network, a fake transport
that records what would have been sent.

The two properties worth a test of their own are the ones a person hits at
the keyboard: an ABSOLUTE path is refused with the reason (§4.1), and the
password never reaches argv or the environment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

import jobs as jobs_cli  # noqa: E402

URL = "http://dash.example:8480"


class FakeHttp:
    """Scripted responses keyed by (method, path-without-query)."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def send(self, method, url, headers=None, body=None, timeout=None):
        path = url.split("?", 1)[0].replace(URL, "")
        self.calls.append((method, url, dict(headers or {}),
                           json.loads(body) if body else None))
        status, payload = self.script.get((method, path),
                                          (500, {"detail": "unscripted"}))
        if callable(payload):
            payload = payload()
        return jobs_cli.Response(status, {}, json.dumps(payload).encode())


LOGIN_OK = {"ok": True, "user": "owen", "is_admin": True, "csrf": "csrf-token"}


def a_job(**over):
    job = {"id": 12, "kind": "whisper", "state": "queued", "attempts": 0,
           "claimed_by": None, "claimed_machine": None, "last_error": "",
           "inputs": {"root": "vault", "rel_path": "Vault/2026/FF5/Ep/Youtube/A"},
           "result": None}
    job.update(over)
    return job


@pytest.fixture(autouse=True)
def _password(monkeypatch):
    monkeypatch.setattr(jobs_cli, "read_password", lambda *_: "correct horse")


def run(argv, script):
    http = FakeHttp(script)
    code = jobs_cli.main(["--dashboard-url", URL, "--admin-user", "owen"] + argv, http)
    return code, http


def test_submit_sends_a_root_and_a_relative_path(capsys):
    code, http = run(
        ["submit", "--kind", "whisper", "--root", "vault",
         "--rel", "Vault/2026/FF5/Civil Defence/Youtube/Interview 3",
         "--episode", "Vault/2026/FF5/Civil Defence"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK),
         ("POST", "/api/v1/jobs"): (200, {
             "ok": True, "job": a_job(),
             "why": {"summary": "1 machine(s) can take this job",
                     "machines": [{"editor": "jsmith", "machine": "EDIT-PC",
                                   "ok": True, "why": "this machine can take it"}]}})})
    assert code == jobs_cli.EXIT_OK
    _method, _url, headers, body = http.calls[-1]
    assert body["kind"] == "whisper"
    assert body["inputs"] == {
        "root": "vault", "rel_path": "Vault/2026/FF5/Civil Defence/Youtube/Interview 3",
        "episode_rel": "Vault/2026/FF5/Civil Defence"}
    assert body["requires"] == {"whisper": True, "mount": "vault", "gpu_vram_gb": 6.0}
    # The session's own CSRF token rides the write.
    assert headers["X-CSRF-Token"] == "csrf-token"
    out = capsys.readouterr().out
    assert "job #12 queued" in out
    assert "1 machine(s) can take this job" in out


def test_speakers_rides_when_asked_for():
    _code, http = run(
        ["submit", "--rel", "V/2026/A", "--speakers"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK),
         ("POST", "/api/v1/jobs"): (200, {"job": a_job(), "why": {}})})
    assert http.calls[-1][3]["inputs"]["speakers"] is True


@pytest.mark.parametrize("bad", ["X:/Vault/2026", "/vault/2026", "V/../../etc"])
def test_an_absolute_or_climbing_path_is_refused_before_anything_is_sent(bad, capsys):
    code, http = run(["submit", "--rel", bad],
                     {("POST", "/api/v1/login"): (200, LOGIN_OK)})
    assert code == jobs_cli.EXIT_USAGE
    assert [c for c in http.calls if "/api/v1/jobs" in c[1]] == []
    err = capsys.readouterr().err
    assert "--rel" in err


def test_a_non_admin_is_refused_before_a_job_exists(capsys):
    code, http = run(["submit", "--rel", "V/2026/A"],
                     {("POST", "/api/v1/login"):
                      (200, {"ok": True, "user": "jsmith", "is_admin": False})})
    assert code == jobs_cli.EXIT_LOGIN
    assert [c for c in http.calls if "/api/v1/jobs" in c[1]] == []
    assert "not a dashboard admin" in capsys.readouterr().err


def test_list_prints_the_queue(capsys):
    code, _http = run(["list"], {
        ("POST", "/api/v1/login"): (200, LOGIN_OK),
        ("GET", "/api/v1/jobs"): (200, {"jobs": [
            a_job(), a_job(id=13, state="running", claimed_by="jsmith",
                           claimed_machine="EDIT-PC")]})})
    out = capsys.readouterr().out
    assert code == jobs_cli.EXIT_OK
    assert "#12" in out and "#13" in out and "jsmith/EDIT-PC" in out


def test_why_prints_a_line_per_machine(capsys):
    code, _http = run(["why", "12"], {
        ("POST", "/api/v1/login"): (200, LOGIN_OK),
        ("GET", "/api/v1/jobs/12/why"): (200, {
            "job": a_job(), "schedulable": False,
            "summary": "no machine can take this job right now: 2 of 2 have "
                       "somebody sitting at them",
            "machines": [
                {"editor": "jsmith", "machine": "EDIT-PC", "ok": False,
                 "why": "somebody is at this machine (idle 12s, whisper needs 300s)"},
                {"editor": "leso", "machine": "MBP", "ok": False,
                 "why": "whisper is not available on this machine"}]})})
    out = capsys.readouterr().out
    assert code == jobs_cli.EXIT_OK
    assert "somebody is at this machine" in out
    assert "whisper is not available" in out


def test_watch_follows_a_job_to_done(capsys):
    states = iter([
        {"job": a_job(state="claimed", claimed_machine="EDIT-PC")},
        {"job": a_job(state="running", claimed_machine="EDIT-PC")},
        {"job": a_job(state="done", claimed_machine="EDIT-PC",
                      result={"seconds": 214.0, "realtime": 11.4,
                              "files": ["Clips/A/A_words.json"]})},
    ])
    http = FakeHttp({("POST", "/api/v1/login"): (200, LOGIN_OK),
                     ("GET", "/api/v1/jobs/12"): (200, lambda: next(states))})
    client = jobs_cli.Client(http, URL)
    code = jobs_cli.watch(client, 12, timeout=60, sleep=lambda _s: None)
    out = capsys.readouterr().out
    assert code == jobs_cli.EXIT_OK
    assert "A_words.json" in out
    assert "11.4x realtime" in out


def test_watch_reports_a_failure_as_a_nonzero_exit(capsys):
    http = FakeHttp({("POST", "/api/v1/login"): (200, LOGIN_OK),
                     ("GET", "/api/v1/jobs/12"): (200, {
                         "job": a_job(state="abandoned", last_error="cuda oom")})})
    code = jobs_cli.watch(jobs_cli.Client(http, URL), 12, timeout=60,
                          sleep=lambda _s: None)
    assert code == jobs_cli.EXIT_JOB_FAILED
    assert "cuda oom" in capsys.readouterr().out


def test_watch_gives_up_politely_and_points_at_why(capsys):
    clock = iter([0.0, 100.0, 200.0])
    http = FakeHttp({("POST", "/api/v1/login"): (200, LOGIN_OK),
                     ("GET", "/api/v1/jobs/12"): (200, {"job": a_job()})})
    code = jobs_cli.watch(jobs_cli.Client(http, URL), 12, timeout=30,
                          sleep=lambda _s: None, clock=lambda: next(clock))
    assert code == jobs_cli.EXIT_OK
    assert "why 12" in capsys.readouterr().out


def test_the_password_is_never_an_argument():
    """The rule test_publish_password_hygiene pins on the shell scripts: this
    tool must have no way to put a password in shell history."""
    text = (TOOLS / "jobs.py").read_text(encoding="utf-8")
    assert "--password" not in text.replace("--password-stdin", "")
    assert "getpass" in text
    parser = jobs_cli.build_parser()
    options = {a.dest for a in parser._actions}
    assert "password" not in options


def test_a_missing_dashboard_url_is_a_usage_error(capsys, monkeypatch):
    monkeypatch.delenv(jobs_cli.DASHBOARD_URL_ENV, raising=False)
    assert jobs_cli.main(["list"], FakeHttp({})) == jobs_cli.EXIT_USAGE
    assert "--dashboard-url" in capsys.readouterr().err


# --------------------------------------------------- phase 1 (2026-08-30)

MEDIA_ARGV = ["submit", "--kind", "proxy-480p", "--root", "media",
              "--rel", "FF5/Civil Defence/Interview 3.mp4",
              "--out-root", "vault",
              "--out-rel",
              "Vault/2026/FF5/Civil Defence/Script Docs/remote_audio/source"]


def test_a_media_job_names_a_source_and_an_output_directory(capsys):
    """Four values and not one path: the root the rush is under, the rush, the
    root the cache goes in, and the directory inside it. The vault is `X:\\` on
    creator-1 and `/vault` in a container, so a path on the wire would be
    right on exactly one machine."""
    code, http = run(MEDIA_ARGV,
                     {("POST", "/api/v1/login"): (200, LOGIN_OK),
                      ("POST", "/api/v1/jobs"): (200, {
                          "ok": True,
                          "job": a_job(kind="proxy-480p"),
                          "why": {"summary": "1 machine(s) can take this job",
                                  "machines": []}})})
    assert code == jobs_cli.EXIT_OK
    body = http.calls[-1][3]
    assert body["kind"] == "proxy-480p"
    assert body["inputs"] == {
        "root": "media", "rel_path": "FF5/Civil Defence/Interview 3.mp4",
        "out_root": "vault",
        "out_rel": "Vault/2026/FF5/Civil Defence/Script Docs/remote_audio/source"}
    # EMPTY on purpose: a media recipe's requirements have one right answer,
    # the same on every clip, and the dashboard fills them in
    # (jobs.default_requires) so no submitter can forget ffprobe.
    assert body["requires"] == {}


@pytest.mark.parametrize("kind", ["audio-extract", "peaks"])
def test_the_other_two_media_kinds_submit_the_same_way(kind):
    argv = ["submit", "--kind", kind, "--root", "media", "--rel", "A/b.mp4",
            "--out-rel", "V/Ep/Script Docs/remote_audio"]
    _code, http = run(argv, {("POST", "/api/v1/login"): (200, LOGIN_OK),
                             ("POST", "/api/v1/jobs"): (200, {"job": a_job(kind=kind),
                                                              "why": {}})})
    assert http.calls[-1][3]["kind"] == kind
    assert http.calls[-1][3]["inputs"]["out_root"] == "vault"


def test_the_page_may_name_the_clip_itself():
    """`--out-stem` is the name the PAGE knows this clip by (its multicam
    name), which is not always the media file's own stem."""
    _code, http = run(MEDIA_ARGV + ["--out-stem", "Interview 3 (cam B)"],
                      {("POST", "/api/v1/login"): (200, LOGIN_OK),
                       ("POST", "/api/v1/jobs"): (200, {"job": a_job(), "why": {}})})
    assert http.calls[-1][3]["inputs"]["out_stem"] == "Interview 3 (cam B)"


def test_a_media_job_with_no_output_directory_is_refused_before_anything_is_sent(
        capsys):
    """Nothing anywhere guesses where a cache belongs in somebody's vault, and
    the useful place to be told is the one where a person can retype it."""
    code, http = run(
        ["submit", "--kind", "peaks", "--root", "media", "--rel", "A/b.mp4"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK)})
    assert code == jobs_cli.EXIT_USAGE
    assert [c for c in http.calls if c[1].endswith("/jobs")] == []
    assert "--out-rel is required" in capsys.readouterr().err


def test_an_absolute_output_directory_is_refused_too(capsys):
    """`/vault/2026/...` is exactly how the Timeline Cards container spells
    the vault, and quietly reading it as relative would queue a job that lands
    in the wrong place on every machine that is not that container."""
    code, _http = run(
        ["submit", "--kind", "peaks", "--root", "media", "--rel", "A/b.mp4",
         "--out-rel", "/vault/2026/FF5"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK)})
    assert code == jobs_cli.EXIT_USAGE
    assert "must be RELATIVE" in capsys.readouterr().err


def test_the_pinned_kinds_cannot_be_submitted_at_all(capsys):
    """Section 4.2's last two rows are not a runtime refusal, they are absent
    from the parser: every edit is a synthetic keystroke into whatever Resolve
    has open on ONE machine."""
    with pytest.raises(SystemExit):
        jobs_cli.build_parser().parse_args(
            ["submit", "--kind", "resolve-edit", "--rel", "a"])
    assert "conform" not in jobs_cli.KINDS
    assert "resolve-edit" not in jobs_cli.KINDS


def test_watch_shows_the_percentage_a_running_recipe_reports(capsys):
    states = iter([
        {"job": a_job(kind="proxy-480p", state="running",
                      claimed_machine="BASE-RIG", progress=0.62)},
        {"job": a_job(kind="proxy-480p", state="done", claimed_machine="BASE-RIG",
                      result={"seconds": 3.3, "realtime": 11.0, "out_root": "vault",
                              "files": ["V/Ep/Script Docs/remote_audio/source/"
                                        "Interview 3.480p.mp4"]})},
    ])
    http = FakeHttp({("POST", "/api/v1/login"): (200, LOGIN_OK),
                     ("GET", "/api/v1/jobs/12"): (200, lambda: next(states))})
    code = jobs_cli.watch(jobs_cli.Client(http, URL), 12, timeout=60,
                          sleep=lambda _s: None)
    out = capsys.readouterr().out
    assert code == jobs_cli.EXIT_OK
    assert "running on BASE-RIG 62%" in out
    assert "Interview 3.480p.mp4" in out


def test_watch_says_nothing_about_a_percentage_nobody_measured(capsys):
    """None, never 0: a peaks pass has no fraction to report and must not look
    wedged at 0%."""
    states = iter([
        {"job": a_job(kind="peaks", state="running", claimed_machine="BASE-RIG",
                      progress=None)},
        {"job": a_job(kind="peaks", state="done", claimed_machine="BASE-RIG",
                      result={"seconds": 1.0, "files": ["V/Ep/a.peaks"]})},
    ])
    http = FakeHttp({("POST", "/api/v1/login"): (200, LOGIN_OK),
                     ("GET", "/api/v1/jobs/12"): (200, lambda: next(states))})
    jobs_cli.watch(jobs_cli.Client(http, URL), 12, timeout=60, sleep=lambda _s: None)
    out = capsys.readouterr().out
    assert "running on BASE-RIG\n" in out
    assert "%" not in out


def test_a_job_that_found_its_file_already_made_says_so(capsys):
    """A fleet that re-encodes what it already has is doing nothing useful
    loudly, and "0 file(s) written" would read as a failure."""
    http = FakeHttp({("POST", "/api/v1/login"): (200, LOGIN_OK),
                     ("GET", "/api/v1/jobs/12"): (200, {
                         "job": a_job(kind="peaks", state="done",
                                      result={"seconds": 0.1, "skipped": True,
                                              "files": ["V/Ep/a.peaks"]})})})
    jobs_cli.watch(jobs_cli.Client(http, URL), 12, timeout=60, sleep=lambda _s: None)
    assert "already made" in capsys.readouterr().out


# ------------------------------------------ section 10: --now and --on
#
# The two levers an admin has over a scheduler that could otherwise only ever
# say "wait" (docs/TIMELINE-CARDS-INTO-CCSYNC.md section 10). Both are checked
# at the BODY, because the field names differ from the flag names on purpose
# (`--now` sends `force`, and the column is `forced`) and a mismatch here is a
# job that quietly queues as an ordinary one.


def test_now_sends_force_and_the_receipt_says_what_it_did(capsys):
    _code, http = run(
        ["submit", "--rel", "V/2026/A", "--now"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK),
         ("POST", "/api/v1/jobs"): (200, {"job": a_job(forced=True), "why": {}})})
    assert http.calls[-1][3]["force"] is True
    assert "target_machine" not in http.calls[-1][3]
    assert "forced: every capable machine is asked at once" in capsys.readouterr().out


def test_on_sends_the_target_and_the_receipt_names_it(capsys):
    _code, http = run(
        ["submit", "--rel", "V/2026/A", "--on", "CREATOR-1"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK),
         ("POST", "/api/v1/jobs"): (200, {"job": a_job(target_machine="CREATOR-1"),
                                          "why": {}})})
    assert http.calls[-1][3]["target_machine"] == "CREATOR-1"
    assert "force" not in http.calls[-1][3]
    assert "for CREATOR-1 only" in capsys.readouterr().out


def test_the_two_levers_ride_a_media_job_as_well(capsys):
    """`--now --on` is section 10.5's answer to "give me that machine's time",
    and it has to work on the kind an editor is actually waiting for."""
    _code, http = run(
        ["submit", "--kind", "proxy-480p", "--root", "media", "--rel", "a.mp4",
         "--out-rel", "V/cache", "--now", "--on", "jsmith/EDIT-PC"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK),
         ("POST", "/api/v1/jobs"): (200, {
             "job": a_job(kind="proxy-480p", forced=True,
                          target_machine="jsmith/EDIT-PC"), "why": {}})})
    body = http.calls[-1][3]
    assert (body["force"], body["target_machine"]) == (True, "jsmith/EDIT-PC")
    out = capsys.readouterr().out
    assert "forced" in out and "for jsmith/EDIT-PC only" in out


def test_a_submission_without_them_is_byte_for_byte_the_old_one():
    """Neither field appears unless asked for, so this tool still submits to
    a dashboard older than 0.7.23 exactly as it used to."""
    _code, http = run(
        ["submit", "--rel", "V/2026/A"],
        {("POST", "/api/v1/login"): (200, LOGIN_OK),
         ("POST", "/api/v1/jobs"): (200, {"job": a_job(), "why": {}})})
    body = http.calls[-1][3]
    assert "force" not in body and "target_machine" not in body
