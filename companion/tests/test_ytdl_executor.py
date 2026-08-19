r"""The local YouTube download executor (docs/YTDL_LOCAL_DOWNLOAD.md §7).

From companion 0.8.0 the requester's own machine may fetch its own reviewed
clips instead of the NAS -- the 2026-08-13/14 incident's answer to "bulk
anonymous downloads out of one datacentre IP is exactly YouTube's bot-check
profile". What this file holds still is everything that could quietly go wrong
with that:

  - **the naming contract** (§5). The `-f` string, the outtmpl and the sidecar
    are the vendored ytdl_common's, so the file an editor's machine writes has
    the same name as the file the NAS would have written into the same
    canonical tree. Two spellings of one clip is the failure this feature must
    not have, and it would surface months later.
  - **410 is the end, quietly** (§3). Every way a lease can be over answers
    410, and the answer to all of them is: stop, clean this clip's own litter,
    post nothing more. No retry, no ping-pong, no error in front of an editor.
  - **the disk** (§7). A project this machine does not sync, a rel path that
    escapes the tree, a URL that is not YouTube's and a disk that is nearly
    full are all refused BEFORE bytes are written -- the free-space one before
    the claim is even made (the 0.7.x upgrade lesson: don't die at clip 40).
  - **the scope cut**. 'best'/'2160p'/'1440p'/'audio' need the server's
    ensure_edit_ready transcode, whose deliverable is `<stem>.editready.mp4` --
    a name this executor cannot reproduce -- so those jobs are handed back by
    letting the lease expire.

Nothing here touches the network or a real yt-dlp: the fleet API is stubbed at
the executor's one request seam, and yt-dlp is a GENERATED SCRIPT that really
parses the argv it is given and really writes the files (or the stderr) the
test asked for. That is deliberate -- it means the outtmpl and the format
string are exercised as strings on a command line, which is what they are.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import pytest

from ccsync_companion import broll_server, loopback_guard, music_server, ytdl_common
from ccsync_companion import ytdl_executor as ex
from ccsync_companion import ytdl_server

LABEL = "2026/FF5/Energy Transition"
TERM = "gulf coast"
REL_DIR = f"{LABEL}/Youtube/{TERM}"
VID1 = "aaaaaaaaaaa"
VID2 = "bbbbbbbbbbb"


def watch(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# ---------------------------------------------------------------------------
# guards + shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_job_leaks():
    """The one-job-at-a-time guard is MODULE state (it protects the machine,
    not a server object), so a job left behind by one test would 409 the next
    one. Cleared on both sides."""
    ex._CURRENT = None
    ex._LAST = None
    yield
    job = ex._CURRENT
    if job is not None:
        job.stop()
    ex._CURRENT = None
    ex._LAST = None


@pytest.fixture(autouse=True)
def _isolate_the_scratch_dir(tmp_path, monkeypatch):
    """No test may write yt-dlp's info json into the REAL %LOCALAPPDATA%\\ccsync.

    test_ytdlp_manager's `_isolate_tools_dir`, for the same reason and against
    the same directory: info_scratch_dir() is derived from ytdlp_manager
    .tools_dir(), whose Windows branch reads LOCALAPPDATA and which nothing in
    conftest redirects (HOME/USERPROFILE cover the POSIX branch only). On the
    developer's own machine that is a real companion's directory.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    """Free space is a real syscall in production and must stay one -- but a
    developer's nearly-full disk must not turn every test in this file into a
    "declined, not enough space". The one test that cares patches it lower."""
    monkeypatch.setattr(ex, "free_bytes_at", lambda path: 500 * 1024 ** 3)


# -- the fake yt-dlp --------------------------------------------------------
#
# A real script, run by this interpreter, that parses the REAL argv the
# executor built: it reads `-o` to learn where to write (BOTH of them -- the
# default template and the `infojson:` one the info json is redirected
# through), `--write-info-json` to decide whether to leave metadata behind, and
# the URL to learn the video id. Per-video, per-attempt behaviour comes from a
# plan file the test writes, so a test can say "fail the first attempt with
# this stderr, succeed the second".
#
# The info json is written BEFORE the media and before any failure, which is
# where yt-dlp writes it (right after extraction) -- and the whole of
# COMP-BROLL-1 is what that timing did in a synced folder.

_FAKE_YTDLP = r'''
import json, os, sys

PLAN = r"{plan}"
LOG = r"{log}"

argv = sys.argv[1:]
calls = json.loads(open(LOG, encoding="utf-8").read()) if os.path.exists(LOG) else []
calls.append(argv)
open(LOG, "w", encoding="utf-8").write(json.dumps(calls))

plan = json.loads(open(PLAN, encoding="utf-8").read())
url = argv[-1]
video_id = url.rsplit("=", 1)[-1]
step = plan.get(video_id) or plan.get("default") or {{}}
attempts = step.get("attempts") or [{{}}]
attempt = attempts[min(sum(1 for c in calls if c[-1] == url) - 1, len(attempts) - 1)]

templates = [argv[i + 1] for i, a in enumerate(argv) if a == "-o"]
outdir = os.path.dirname([t for t in templates if not t.startswith("infojson:")][0])
info_tmpl = ([t.split(":", 1)[1] for t in templates if t.startswith("infojson:")] or [None])[0]
title = step.get("title", "A clip")
uploader = step.get("uploader", "Some Channel")
stem = "%s - %s [%s]" % (uploader, title, video_id)

if "--write-info-json" in argv:
    info = {{"id": video_id, "title": title, "uploader": uploader,
            "channel": uploader + " Official", "channel_url": "https://c",
            "uploader_url": "https://u", "webpage_url": url,
            "upload_date": "20260801", "duration": 12.0}}
    if info_tmpl:
        # yt-dlp forces this output type's extension to `info.json`.
        evaluated = info_tmpl.replace("%(id)s", video_id).replace("%(ext)s", "mp4")
        info_path = os.path.splitext(evaluated)[0] + ".info.json"
    else:
        info_path = os.path.join(outdir, stem + ".info.json")
    with open(info_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(info))

for name in attempt.get("partials", []):
    with open(os.path.join(outdir, name.replace("{{stem}}", stem)), "w") as fh:
        fh.write("half a stream")

if attempt.get("exit"):
    sys.stderr.write(attempt.get("stderr", "yt-dlp failed"))
    sys.exit(attempt["exit"])

with open(os.path.join(outdir, stem + ".mp4"), "wb") as fh:
    fh.write(b"video bytes")
'''


class FakeYtDlp:
    """A generated yt-dlp, plus the argv log every invocation appended to."""

    def __init__(self, tmp_path: Path):
        self.dir = tmp_path / "fake-ytdlp"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.plan_path = self.dir / "plan.json"
        self.log_path = self.dir / "calls.json"
        self.script = self.dir / "yt-dlp.py"
        self.plan_path.write_text("{}", encoding="utf-8")
        self.script.write_text(
            _FAKE_YTDLP.format(plan=str(self.plan_path), log=str(self.log_path)),
            encoding="utf-8")

    def plan(self, mapping: dict) -> None:
        self.plan_path.write_text(json.dumps(mapping), encoding="utf-8")

    @property
    def calls(self) -> list:
        if not self.log_path.exists():
            return []
        return json.loads(self.log_path.read_text(encoding="utf-8"))

    def run_fn(self, argv, timeout, on_spawn=None):
        """The executor's run seam, pointed at the generated script.

        THE REAL ex.default_run does the work -- the Popen, the sanitized
        child env, the kill handle -- so that path is covered here rather than
        stubbed away. The only substitution is this interpreter in front of a
        .py "binary", which no OS runs directly; every other argument is the
        executor's own.
        """
        return ex.default_run([sys.executable, *argv], timeout, on_spawn)


@pytest.fixture
def ytdlp(tmp_path) -> FakeYtDlp:
    return FakeYtDlp(tmp_path)


# -- the fake fleet API -----------------------------------------------------


class FakeFleet:
    """routes_fleet, stubbed at ex.default_request's exact shape."""

    def __init__(self, manifest: dict | None = None):
        self.calls: list = []            # (method, path, body, headers)
        self.statuses: list = []         # (video_id, state, body)
        self.manifest_body = manifest
        self.claim_status = 200
        self.claim_body = {"ok": True, "lease_seconds": 180,
                           # long enough that no heartbeat fires during a test
                           "heartbeat_seconds": 300,
                           "download_pause_seconds": 0}
        # What answers 410: "manifest", "heartbeat", or ("status", vid, state).
        self.gone: set = set()
        self.transport_error = False

    def request(self, method, url, body, headers, timeout):
        if self.transport_error:
            raise OSError("the dashboard is unreachable")
        path = urlparse(url).path
        self.calls.append((method, path, body, dict(headers)))
        if path.endswith("/claim"):
            return self.claim_status, self.claim_body
        if path.endswith("/heartbeat"):
            if "heartbeat" in self.gone:
                return 410, {"detail": "reclaimed"}
            return 200, {"ok": True}
        if path.endswith("/download-manifest"):
            if "manifest" in self.gone:
                return 410, {"detail": "reclaimed"}
            return 200, self.manifest_body
        if path.endswith("/status"):
            video_id = path.split("/clips/")[1].split("/")[0]
            state = (body or {}).get("state")
            self.statuses.append((video_id, state, body))
            if ("status", video_id, state) in self.gone:
                return 410, {"detail": "reclaimed"}
            return 200, {"ok": True}
        raise AssertionError(f"the executor called something unexpected: {path}")

    # -- readers the tests use ------------------------------------------
    @property
    def claimed(self) -> list:
        return [c for c in self.calls if c[1].endswith("/claim")]

    @property
    def state_sequence(self) -> list:
        return [(vid, state) for vid, state, _body in self.statuses]

    def body_for(self, video_id: str, state: str) -> dict:
        for vid, st, body in self.statuses:
            if vid == video_id and st == state:
                return body
        raise AssertionError(f"no {state} status was posted for {video_id}")


def manifest_for(clips=None, quality="1080p", label=LABEL, rel_dir=REL_DIR,
                 pause=0) -> dict:
    return {
        "job_id": 7,
        "project_label": label,
        "project_rel_path": rel_dir,
        "term_dir": TERM,
        "quality": quality,
        "template_version": ytdl_common.TEMPLATE_VERSION,
        "sidecar_version": ytdl_common.SIDECAR_VERSION,
        "download_pause_seconds": pause,
        "clips": clips if clips is not None else [
            {"video_id": VID1, "url": watch(VID1), "title": "A clip",
             "thumbnail": None},
        ],
    }


# -- deps -------------------------------------------------------------------


class FakeYtDlpManager:
    def __init__(self, ok=True, version="2026.08.11", message="yt-dlp is current"):
        self._status = {"ok": ok, "version": version, "action": "none",
                        "message": message}

    def status(self):
        return dict(self._status)


def fake_ffmpeg(tmp_path) -> str:
    """A real file where `ffmpeg_path` points, because every rung this executor
    runs is a `bestvideo+bestaudio` MERGE and yt-dlp refuses those without a
    merger (COMP-BROLL-5). Resolved through the real ffmpeg_tools
    ._resolve_binary -- an absolute path that exists is all it asks for, and
    nothing here ever runs it."""
    binary = tmp_path / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists():
        binary.write_text("not really ffmpeg")
    return str(binary)


def make_cfg(tmp_path, **overrides) -> dict:
    cfg = {
        "dashboard_url": "http://dash.local:8000",
        "dashboard_token": "fleet-token",
        "local_root": str(tmp_path / "tree"),
        "canonical_prefix": "P:\\",
        "editor_name": "editor2",
        "mode": "editor",
        "ytdl_local_downloads": True,
        "ffmpeg_path": fake_ffmpeg(tmp_path),
    }
    cfg.update(overrides)
    return cfg


def make_deps(tmp_path, fleet=None, ytdlp=None, cfg=None, selection=None,
              editor="editor2", ytdlp_ok=True, sleeps=None) -> ex.Deps:
    cfg = cfg if cfg is not None else make_cfg(tmp_path)
    if ytdlp is not None:
        cfg["ytdlp_path"] = str(ytdlp.script)
    if selection is None:
        selection = [{"slug": "energy", "label": LABEL, "rel_path": LABEL,
                      "active": True}]
    if editor:
        # The rights/ToS attestation, per machine and per editor name
        # (2026-08-17, COMMERCIAL_READINESS.md item 2). capabilities() refuses
        # without it, so a suite that did not record it would be testing the
        # gate in every one of these. conftest cannot do it -- it is keyed on
        # a name only the test knows.
        from ccsync_companion import ytdl_attestation

        ytdl_attestation.accept(editor)
    deps = ex.Deps(
        cfg,
        ytdlp=FakeYtDlpManager(ok=ytdlp_ok),
        editor_fn=lambda: editor or None,
        selection_fn=(lambda: selection),
        # The dashboard-signed identity token the fleet routes verify (H5).
        # Opaque here: this side only has to SEND it, and a companion with no
        # token has no capability.
        identity_token_fn=(lambda: f"v2.identity.token-for-{editor}"
                           if editor else None),
        request_fn=(fleet.request if fleet is not None else None),
        run_fn=(ytdlp.run_fn if ytdlp is not None else None),
        sleep_fn=(sleeps.append if sleeps is not None else (lambda seconds: None)),
    )
    return deps


def run_job(deps, job_id=7) -> ex.DownloadJob:
    """Run one job to completion ON THIS THREAD.

    start() spawns a daemon thread (8899 must answer 202 immediately); the
    tests that care about THAT drive start(). Everything about the download
    itself is deterministic when run inline, and a test that has to poll a
    thread to find out what happened is a test that flakes at 3am.
    """
    job = ex.DownloadJob(job_id, deps)
    job.run()
    return job


def outdir_for(tmp_path) -> Path:
    return Path(tmp_path) / "tree" / "Projects" / Path(*REL_DIR.split("/"))


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------


def test_a_claimed_job_downloads_writes_the_sidecar_and_reports_in_order(
        tmp_path, ytdlp):
    fleet = FakeFleet(manifest_for(clips=[
        {"video_id": VID1, "url": watch(VID1), "title": "A clip"},
        {"video_id": VID2, "url": watch(VID2), "title": "Another clip"},
    ]))
    ytdlp.plan({"default": {"attempts": [{}]}})
    sleeps: list = []
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp, sleeps=sleeps)

    job = run_job(deps)

    # ...the whole conversation, in order: claim, manifest, then per clip.
    assert [c[1].rsplit("/", 1)[-1] for c in fleet.calls][:2] == [
        "claim", "download-manifest"]
    assert fleet.state_sequence == [
        (VID1, "downloading"), (VID1, "done"),
        (VID2, "downloading"), (VID2, "done"),
    ]
    assert (job.done, job.failed, job.total) == (2, 0, 2)

    outdir = outdir_for(tmp_path)
    clip = outdir / f"Some Channel - A clip [{VID1}].mp4"
    assert clip.is_file()
    # `filepath_rel` is the NAME: the server composes the ledger path itself
    # from the job's own label and term dir, and a machine-supplied path is not
    # something it stores (routes_fleet.ClipStatusIn).
    assert fleet.body_for(VID1, "done")["filepath_rel"] == clip.name
    assert fleet.body_for(VID1, "done")["note"] is None

    # The sidecar is the contract; the info json is 200 KB of yt-dlp internals
    # that would otherwise sync fleet-wide beside the footage forever.
    sidecar = Path(ytdl_common.sidecar_path(str(clip)))
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {
        "channel": "Some Channel Official", "channel_url": "https://c",
        "uploader": "Some Channel", "video_url": watch(VID1),
        "title": "A clip", "video_id": VID1,
        "upload_date": "20260801", "duration": 12.0,
    }
    assert not (outdir / f"Some Channel - A clip [{VID1}].info.json").exists()
    assert list(outdir.glob("*.info.json")) == []
    # One pause, between the two clips -- never before the first.
    assert len(sleeps) == 1


def test_the_done_post_carries_the_title_and_channel_for_the_ledger(tmp_path,
                                                                    ytdlp):
    """YTDL-WEB-8 (2026-08-14), this executor's half. routes_fleet._record_done
    ledgers `body.channel or row['channel']`, mirroring the NAS worker's
    `res.get('channel') or v['channel']` -- but a job created by pasting a URL
    has NO channel on its row until a download reports one, so a locally
    downloaded clip used to be ledgered with a NULL channel where the same clip
    fetched by the server had the real one.

    The values come from the info dict already parsed for the sidecar, through
    credits_sidecar's `channel or uploader` fallback, so the ledger and the
    sidecar cannot credit one clip to two different names."""
    fleet = FakeFleet(manifest_for())
    ytdlp.plan({"default": {"title": "Aerial View Rio Grande LNG",
                            "uploader": "Cruz Yanez"}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    body = fleet.body_for(VID1, "done")
    assert body["title"] == "Aerial View Rio Grande LNG"
    # The fake's info json carries `channel` = uploader + " Official", and
    # channel wins over uploader -- downloader._write_sidecar's own fallback
    # order, pinned in ytdl_common.credits_sidecar.
    assert body["channel"] == "Cruz Yanez Official"
    # The sidecar agrees with what was posted, from the same dict.
    sidecar = outdir_for(tmp_path) / (
        f"Cruz Yanez - Aerial View Rio Grande LNG [{VID1}].credits.json")
    written = json.loads(sidecar.read_text(encoding="utf-8"))
    assert (written["title"], written["channel"]) == (body["title"], body["channel"])


def test_a_clip_with_no_readable_info_json_posts_done_without_them(tmp_path,
                                                                   ytdlp,
                                                                   monkeypatch):
    """Omitted, never sent as null: the server falls back to the row for each
    field, and a companion that could not read an info json must not blank out
    a title or a channel the search pipeline already knew."""
    monkeypatch.setattr(ex, "info_scratch_dir", lambda: None)
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    job = run_job(deps)

    body = fleet.body_for(VID1, "done")
    assert (job.done, job.failed) == (1, 0)
    assert "title" not in body and "channel" not in body
    assert body["filepath_rel"] == f"Some Channel - A clip [{VID1}].mp4"


def test_the_info_json_is_never_written_into_the_synced_tree(tmp_path, ytdlp):
    """COMP-BROLL-1, the one that made this a critical: `--write-info-json`
    used to drop a ~120 KB `<stem>.info.json` next to the video AT EXTRACTION
    TIME -- minutes before the media finishes -- inside a Syncthing
    SENDRECEIVE folder whose stignore covers video extensions, `.part` and
    `.ytdl` but deliberately not `.json`. Every one of a 40-clip job's info
    jsons was indexed and fanned out to the NAS and to every other editor with
    that project ticked, and the executor deleting it afterwards changed
    nothing: ignoreDelete=true (2026-08-11 delete protection) means a received
    delete is not applied. Permanent, undeletable litter -- byte for byte the
    `.part` failure R15 fix 3 closed.

    So it goes to a scratch dir outside the tree, and the ONLY evidence of it
    the term folder ever sees is the credits sidecar built from it."""
    fleet = FakeFleet(manifest_for(clips=[
        {"video_id": VID1, "url": watch(VID1)},
        {"video_id": VID2, "url": watch(VID2)},
    ]))
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    job = run_job(deps)

    outdir = outdir_for(tmp_path)
    assert (job.done, job.failed) == (2, 0)
    assert list(outdir.rglob("*.info.json")) == []
    assert len(list(outdir.glob("*.credits.json"))) == 2

    # ...because yt-dlp was pointed somewhere else entirely, by an `-o` of its
    # own -- and that somewhere is not under the project tree.
    (first, _second) = ytdlp.calls
    templates = [first[i + 1] for i, a in enumerate(first) if a == "-o"]
    (redirect,) = [t for t in templates if t.startswith("infojson:")]
    scratch = Path(redirect.split(":", 1)[1]).parent
    assert scratch == ex.info_scratch_dir()
    assert str(tmp_path / "tree") not in str(scratch)
    # ...and nothing accumulates there either: write_sidecar consumes it.
    assert list(scratch.glob("*.info.json")) == []


def test_a_failed_clip_leaves_no_info_json_anywhere(tmp_path, ytdlp):
    """The scratch copy is housekeeping, not an artifact: a clip that failed
    gets its metadata cleaned up with the rest of its litter."""
    fleet = FakeFleet(manifest_for())
    ytdlp.plan({"default": {"attempts": [{"exit": 1, "stderr": "ERROR: nope"}]}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "failed")]
    assert list(outdir_for(tmp_path).glob("*.info.json")) == []
    assert list(ex.info_scratch_dir().glob("*.info.json")) == []


def test_a_machine_with_nowhere_to_put_the_info_json_still_downloads(
        tmp_path, ytdlp, monkeypatch):
    """Fail absent, not fatal (CLAUDE.md): no scratch dir means no
    `--write-info-json` and therefore no credits sidecar -- which write_sidecar
    already treats as an ordinary outcome -- never a clip that does not land,
    and never the info json going back into the tree."""
    monkeypatch.setattr(ex, "info_scratch_dir", lambda: None)
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    job = run_job(deps)

    (argv,) = ytdlp.calls
    assert "--write-info-json" not in argv
    assert (job.done, job.failed) == (1, 0)
    outdir = outdir_for(tmp_path)
    assert (outdir / f"Some Channel - A clip [{VID1}].mp4").is_file()
    assert list(outdir.glob("*.info.json")) == []
    assert list(outdir.glob("*.credits.json")) == []


def test_the_claim_carries_what_the_server_gates_on(tmp_path, ytdlp):
    """routes_fleet.claim refuses on the naming template and on a stale yt-dlp,
    and records free_bytes as evidence for "why did that editor stop
    claiming". Plus the fleet token -- NOT a browser session: these calls
    happen when no browser is open (§4).

    `sidecar_version` is COMP-BROLL-6: the two contract numbers are separate
    because they fail differently, and only one of them was ever sent.
    `scope_qualities` is COMP-BROLL-10: the server knows the job's quality at
    claim time, so declaring what this executor runs is what lets it refuse
    immediately instead of granting a lease it must then wait out."""
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    method, path, body, headers = fleet.claimed[0]
    assert (method, path) == ("POST", "/ytdl/api/jobs/7/claim")
    assert body == {"editor": "editor2", "ytdlp_version": "2026.08.11",
                    "template_version": ytdl_common.TEMPLATE_VERSION,
                    "sidecar_version": ytdl_common.SIDECAR_VERSION,
                    "scope_qualities": ["480p", "720p", "1080p"],
                    "free_bytes": 500 * 1024 ** 3}
    assert body["scope_qualities"] == list(ex.SCOPE_QUALITIES)
    assert headers["X-CCSync-Token"] == "fleet-token"
    # H5 (2026-08-17): the identity header carries the dashboard-SIGNED token,
    # not the editor's name. It used to be the bare name, which meant the
    # shared fleet token -- held by every machine -- was the only thing between
    # a companion and another editor's job. The body's `editor` is still sent
    # (an older server reads it) and the server now ignores it.
    assert headers["X-CCSync-Identity"] == "v2.identity.token-for-editor2"


def test_the_argv_is_the_shared_naming_contract(tmp_path, ytdlp):
    """The outtmpl and the format string are what make the two executors'
    output byte-identical (§5). Asserted on the real command line, because a
    command line is what they are on this side of the fleet."""
    fleet = FakeFleet(manifest_for(quality="720p"))
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    (argv,) = ytdlp.calls
    assert argv[argv.index("-f") + 1] == ytdl_common.format_selector(
        "720p", prefer_avc=True)
    assert argv[argv.index("-o") + 1] == ytdl_common.outtmpl(str(outdir_for(tmp_path)))
    assert argv[argv.index("--merge-output-format") + 1] == "mp4"
    assert "--write-info-json" in argv and "--no-playlist" in argv
    # The merger the whole scope depends on, always named when the capability
    # said yes (COMP-BROLL-5).
    assert argv[argv.index("--ffmpeg-location") + 1] == \
        str(Path(fake_ffmpeg(tmp_path)).parent)
    assert argv[-1] == watch(VID1)


def test_a_managed_deno_is_passed_to_yt_dlp(tmp_path, ytdlp, monkeypatch):
    """COMP-YTDL (2026-08-16): without a JS runtime, an anonymous download
    still works but cookies make every format vanish. yt-dlp enables only deno
    by default and bundles none, so when the sidecar installed one the executor
    hands it over by path (it lives off PATH)."""
    monkeypatch.setattr(ex.sidecar_tools, "managed_deno", lambda: r"C:\deno\deno.exe")
    deps = make_deps(tmp_path, fleet=FakeFleet(manifest_for()), ytdlp=ytdlp)

    run_job(deps)

    (argv,) = ytdlp.calls
    assert argv[argv.index("--js-runtimes") + 1] == r"deno:C:\deno\deno.exe"


def test_no_deno_means_no_js_runtimes_flag(tmp_path, ytdlp, monkeypatch):
    """An anonymous download without a runtime is still a working download
    (yt-dlp's deprecated no-runtime path), so the flag is simply omitted."""
    monkeypatch.setattr(ex.sidecar_tools, "managed_deno", lambda: None)
    deps = make_deps(tmp_path, fleet=FakeFleet(manifest_for()), ytdlp=ytdlp)

    run_job(deps)

    (argv,) = ytdlp.calls
    assert "--js-runtimes" not in argv


def test_a_configured_cookies_file_is_passed(tmp_path, ytdlp):
    """The editor's signed-in cookies.txt is what passes the bot check and
    unlocks age-gated clips on their own machine (2026-08-16)."""
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    deps = make_deps(tmp_path, fleet=FakeFleet(manifest_for()), ytdlp=ytdlp,
                     cfg=make_cfg(tmp_path, ytdl_cookies_file=str(cookies)))
    deps.cfg["ytdlp_path"] = str(ytdlp.script)

    run_job(deps)

    (argv,) = ytdlp.calls
    assert argv[argv.index("--cookies") + 1] == str(cookies)


def test_a_missing_cookies_file_is_not_passed(tmp_path, ytdlp):
    """A configured-but-absent path is treated as no cookies: yt-dlp would
    abort the whole download on a missing --cookies file, and an anonymous
    attempt beats refusing to try."""
    deps = make_deps(tmp_path, fleet=FakeFleet(manifest_for()), ytdlp=ytdlp,
                     cfg=make_cfg(tmp_path, ytdl_cookies_file=str(tmp_path / "gone.txt")))
    deps.cfg["ytdlp_path"] = str(ytdlp.script)

    run_job(deps)

    (argv,) = ytdlp.calls
    assert "--cookies" not in argv


def test_no_cookies_configured_means_no_cookies_flag(tmp_path, ytdlp):
    deps = make_deps(tmp_path, fleet=FakeFleet(manifest_for()), ytdlp=ytdlp)
    run_job(deps)
    (argv,) = ytdlp.calls
    assert "--cookies" not in argv


def test_the_argv_embeds_the_same_credits_tags_the_nas_embeds(tmp_path, ytdlp):
    """COMP-BROLL-2: §5's must-be-identical set is "the outtmpl, the sidecar,
    EMBEDDED TAGS, ..." and the embedded half was simply missing from the argv.
    Two clips in one term folder -- one fetched by the NAS, one by an editor --
    had the same NAME and different insides, so nothing in the fleet could
    report a difference and the Resolve credits script (which reads the tags as
    the primary of downloader.py's "three redundant metadata channels") saw
    empty fields for every locally-fetched clip.

    Pinned against the source it was copied from: vendor/downloader.py's
    _credits_action calls, which live in a file vendored VERBATIM from
    yt-credit-downloader and are therefore frozen."""
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    (argv,) = ytdlp.calls
    parsed = [argv[i + 1] for i, a in enumerate(argv) if a == "--parse-metadata"]
    assert parsed == [
        # downloader.build_opts' MetadataParser pre_process actions, in order.
        "%(channel,uploader)s:%(meta_channel)s",
        "%(webpage_url)s:%(meta_video_url)s",
        "%(channel_url,uploader_url)s:%(meta_channel_url)s",
        "%(uploader,channel)s:%(meta_uploader)s",
        "%(channel,uploader)s:%(artist)s",
        "%(webpage_url)s:%(meta_comment)s",
    ]
    # ...and the pass that writes them into the file. --embed-chapters is not
    # noise: FFmpegMetadataPP defaults add_chapters=True, so the server's
    # one-key dict embeds chapters where the CLI flag defaults off.
    assert "--embed-metadata" in argv and "--embed-chapters" in argv


def test_the_embedded_tags_are_the_ones_the_server_side_downloader_asks_for():
    """The other end of the same pin, read out of the NAS's own source rather
    than retyped here: if downloader._credits_action's four mappings ever
    change, this fails instead of the fleet quietly growing two artifact
    shapes. Text, not an import -- vendor/downloader.py needs yt_dlp, which the
    companion deliberately does not have (§6)."""
    downloader = (Path(__file__).resolve().parents[2] / "ytdl" / "web" /
                  "ytdlweb" / "vendor" / "downloader.py")
    if not downloader.is_file():
        pytest.skip("the ytdl web tree is not in this checkout")
    source = downloader.read_text(encoding="utf-8")
    for field, meta_key in (("%(channel,uploader)s", "channel"),
                            ("%(webpage_url)s", "video_url"),
                            ("%(channel_url,uploader_url)s", "channel_url"),
                            ("%(uploader,channel)s", "uploader")):
        assert f'_credits_action("{field}", "{meta_key}")' in source
        assert f"{field}:%(meta_{meta_key})s" in ex.CREDITS_METADATA_ARGS


def test_the_destination_goes_through_path_canon(tmp_path):
    """`P:\\Projects\\...` is the fleet's one portable spelling; where it lands
    is this machine's business (§7). The base rig is the identity case -- its
    local_root IS the NAS share, which is why it is the pilot machine."""
    editor = make_cfg(tmp_path, local_root="F:\\Creators_Club")
    assert ex.destination_for(editor, REL_DIR) == str(
        Path("F:\\Creators_Club", "Projects", *REL_DIR.split("/")))

    base = make_cfg(tmp_path, local_root="P:\\", canonical_prefix="P:\\",
                    mode="base")
    assert ex.destination_for(base, REL_DIR) == str(
        Path("P:\\", "Projects", *REL_DIR.split("/")))


@pytest.mark.parametrize("rel", [
    "../../../Windows/System32", "/etc", "C:/Windows", "", None, 5,
    "2026/../../evil",
])
def test_a_rel_path_that_escapes_the_tree_has_no_destination(tmp_path, rel):
    assert ex.destination_for(make_cfg(tmp_path), rel) is None


# ---------------------------------------------------------------------------
# 410: the lease is gone
# ---------------------------------------------------------------------------


def test_a_410_mid_job_stops_quietly_and_cleans_its_own_partials(tmp_path, ytdlp):
    """Reclaim is one-way (§3). The server has the job back and is downloading
    what is missing, so this side stops where it stands -- no retry, no error
    for the editor -- and takes its own `.part` litter with it, because
    yt-dlp RESUMES a .part and the next attempt would inherit poisoned bytes."""
    fleet = FakeFleet(manifest_for(clips=[
        {"video_id": VID1, "url": watch(VID1)},
        {"video_id": VID2, "url": watch(VID2)},
    ]))
    # The `done` for the first clip is the moment the server says "not yours".
    fleet.gone.add(("status", VID1, "done"))
    ytdlp.plan({"default": {"attempts": [{"partials": ["{stem}.f137.mp4.part"]}]}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    job = run_job(deps)

    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "done")]
    assert VID2 not in [vid for vid, _ in fleet.state_sequence]
    assert len(ytdlp.calls) == 1, "the second clip was never started"
    assert list(outdir_for(tmp_path).glob("*.part")) == []
    assert job.running is False


def test_a_410_on_the_manifest_downloads_nothing_at_all(tmp_path, ytdlp):
    fleet = FakeFleet(manifest_for())
    fleet.gone.add("manifest")
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert fleet.statuses == []
    assert ytdlp.calls == []


def test_a_410_leaves_other_clips_partials_alone(tmp_path, ytdlp):
    """The cleanup is ID-SCOPED, never a glob of the folder: the term folder is
    shared with every other clip of the search, and a `.part` in there may
    belong to a download that is still running (worker._clear_partials)."""
    fleet = FakeFleet(manifest_for(clips=[{"video_id": VID1, "url": watch(VID1)}]))
    fleet.gone.add(("status", VID1, "done"))
    ytdlp.plan({"default": {"attempts": [{"partials": ["{stem}.f137.mp4.part"]}]}})
    outdir = outdir_for(tmp_path)
    outdir.mkdir(parents=True)
    stranger = outdir / f"Someone Else - Their clip [{VID2}].mp4.part"
    stranger.write_text("not ours")
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert stranger.exists()
    assert list(outdir.glob(f"*[[]{VID1}[]]*.part")) == []


def test_a_lost_lease_is_not_an_exception_the_tray_ever_sees(tmp_path, ytdlp):
    """LeaseLost is caught inside run(); a job that ends this way is just a job
    that ended. Nothing about it may reach the tray or a dialog."""
    fleet = FakeFleet(manifest_for())
    fleet.gone.add(("status", VID1, "downloading"))
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    job = run_job(deps)  # must not raise

    assert job.running is False
    assert ytdlp.calls == []


def test_the_heartbeat_runs_at_the_interval_the_claim_named(tmp_path, ytdlp):
    """The lease is 180 s and the heartbeat 30 s -- BOTH server config (§3),
    both taken from the claim response rather than assumed here, because
    residential pacing and the fleet's timings are the server's business."""
    fleet = FakeFleet(manifest_for())
    fleet.claim_body = dict(fleet.claim_body, heartbeat_seconds=0.02)
    beat = threading.Event()

    def slow_run(argv, timeout, on_spawn=None):
        # The download waits for the heartbeat, never the other way round --
        # and the cap is a deadlock escape, not a budget, so it is generous
        # (a loaded runner is what broke the 410 test next door on 2026-08-18).
        beat.wait(30)
        return ytdlp.run_fn(argv, timeout, on_spawn)

    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)
    original = fleet.request

    def counting(method, url, body, headers, timeout):
        result = original(method, url, body, headers, timeout)
        if url.endswith("/heartbeat"):
            beat.set()
        return result

    deps.request = counting
    deps.run = slow_run

    run_job(deps)

    assert any(c[1].endswith("/heartbeat") for c in fleet.calls)
    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "done")]


def test_a_410_on_the_heartbeat_kills_the_download_in_flight(tmp_path, ytdlp):
    """The laptop-closed / tray-upgraded case from the other side: the server
    reclaimed the job while yt-dlp was running. Finishing the download would
    write a file nobody will record, so the child is killed where it stands and
    its litter goes with it (§3). Nothing more is posted -- the job is not ours
    to report on any more.

    The 410 is held until the child is actually running, rather than raced
    against a short heartbeat interval: this test failed on GitHub's
    windows-latest runner (run 32096641553, 2026-08-18) with an EMPTY state
    sequence, because a 0.02 s heartbeat beat the manifest fetch and the mkdir
    to the first clip, so the lease was gone before there was any download to
    kill -- correct behaviour, and not the behaviour this test is named for.
    Gating the ANSWER is the fix; a bigger interval is the same race with a
    bigger constant."""
    fleet = FakeFleet(manifest_for(clips=[
        {"video_id": VID1, "url": watch(VID1)},
        {"video_id": VID2, "url": watch(VID2)},
    ]))
    fleet.claim_body = dict(fleet.claim_body, heartbeat_seconds=0.02)
    fleet.gone.add("heartbeat")
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)
    in_flight = threading.Event()
    original = fleet.request

    def held_until_the_child_is_running(method, url, body, headers, timeout):
        if url.endswith("/heartbeat"):
            # Not asserted here: this runs on the heartbeat thread, where
            # _heartbeat_loop swallows every exception but LeaseLost. A wait
            # that timed out shows up as the in_flight assertion below.
            in_flight.wait(30)
        return original(method, url, body, headers, timeout)

    def endless(argv, timeout, on_spawn=None):
        def spawned(proc):
            # Registered BEFORE the 410 is let through, or this would exercise
            # _register_proc's spawn-race guard instead of the kill in flight.
            if on_spawn is not None:
                on_spawn(proc)
            in_flight.set()

        # A download that would never finish on its own: only the kill ends it.
        return ex.default_run(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            timeout, spawned)

    deps.request = held_until_the_child_is_running
    deps.run = endless

    job = run_job(deps)  # returns only because the child was killed

    assert in_flight.is_set(), "yt-dlp never spawned, so nothing was killed"
    assert fleet.state_sequence == [(VID1, "downloading")]
    assert job.running is False and (job.done, job.failed) == (0, 0)


def test_the_pause_between_clips_is_the_servers_number(tmp_path, ytdlp):
    """Residential pacing can be gentler -- or brisker -- than the NAS's 3 s,
    so the number is server-provided (§7) and not a companion constant."""
    fleet = FakeFleet(manifest_for(pause=7, clips=[
        {"video_id": VID1, "url": watch(VID1)},
        {"video_id": VID2, "url": watch(VID2)},
    ]))
    sleeps: list = []
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp, sleeps=sleeps)

    run_job(deps)

    assert sleeps == [7]


# ---------------------------------------------------------------------------
# the truncated stream (SAQBbd1Rxmo, 2026-08-13)
# ---------------------------------------------------------------------------


TRUNCATED_STDERR = (
    "ERROR: unable to download video data: Got error: 8 bytes read, 10288457 "
    "more expected. Giving up after 10 retries"
)


def test_a_truncated_stream_falls_back_one_rung_and_says_so(tmp_path, ytdlp):
    """The 2026-08-14 worker fix, on this executor, via the shared
    ytdl_common: BOTH markers, ONE rung, and a note on the DONE row -- the
    only place that will ever say the editor got 720p where they asked for
    1080p."""
    fleet = FakeFleet(manifest_for(quality="1080p"))
    ytdlp.plan({"default": {"attempts": [
        {"exit": 1, "stderr": TRUNCATED_STDERR,
         "partials": ["{stem}.f137.mp4.part"]},
        {},
    ]}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    job = run_job(deps)

    first, second = ytdlp.calls
    assert first[first.index("-f") + 1] == ytdl_common.format_selector("1080p")
    assert second[second.index("-f") + 1] == ytdl_common.format_selector("720p")
    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "done")]
    assert fleet.body_for(VID1, "done")["note"] == \
        ytdl_common.TRUNCATED_NOTE.format(q="1080p", lower="720p")
    assert (job.done, job.failed) == (1, 0)
    # The .part IS the truncated bytes and yt-dlp resumes a .part -- the retry
    # has to start from nothing or it inherits the corpse.
    assert list(outdir_for(tmp_path).glob("*.part")) == []


def test_only_the_full_truncation_signature_downgrades_anything(tmp_path, ytdlp):
    """The byte-count phrase alone is the ordinary short read yt-dlp retries
    out of by itself. A bot check, a throttle and a dead network are MOMENTS,
    and they keep the failure they have always had rather than silently costing
    an editor 360 lines of resolution nobody asked to lose."""
    fleet = FakeFleet(manifest_for(quality="1080p"))
    ytdlp.plan({"default": {"attempts": [
        {"exit": 1, "stderr": "ERROR: Sign in to confirm you're not a bot"},
        {},
    ]}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    job = run_job(deps)

    assert len(ytdlp.calls) == 1, "no second rung was attempted"
    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "failed")]
    assert "not a bot" in fleet.body_for(VID1, "failed")["error"]
    assert (job.done, job.failed) == (0, 1)


def test_a_failed_fallback_is_a_failure_not_a_third_attempt(tmp_path, ytdlp):
    fleet = FakeFleet(manifest_for(quality="1080p"))
    ytdlp.plan({"default": {"attempts": [
        {"exit": 1, "stderr": TRUNCATED_STDERR},
        {"exit": 1, "stderr": "ERROR: the 720p rung died too"},
    ]}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert len(ytdlp.calls) == 2
    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "failed")]
    assert "720p rung died" in fleet.body_for(VID1, "failed")["error"]


def test_a_failure_takes_its_own_litter_with_it(tmp_path, ytdlp):
    fleet = FakeFleet(manifest_for())
    ytdlp.plan({"default": {"attempts": [
        {"exit": 1, "stderr": "ERROR: nope", "partials": ["{stem}.mp4.part",
                                                          "{stem}.mp4.ytdl"]},
    ]}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    outdir = outdir_for(tmp_path)
    assert list(outdir.glob("*.part")) == [] and list(outdir.glob("*.ytdl")) == []


def test_a_finished_per_format_stream_is_litter_too(tmp_path, ytdlp):
    """COMP-BROLL-3. `... [id].f137.mp4` is what yt-dlp renames the video
    stream's `.part` to the moment that stream completes, and it KEEPS it (for
    resume) when the audio or the merge then fails. No suffix rule matched it,
    `landed_file` correctly refused to read it as the clip, and nothing else on
    the machine ever deleted it -- so a 1.4 GB video-only orphan matched lane
    A's `+ *.mp4` include and no stignore line, and went to the NAS and to
    every other editor with that project ticked. The plan's own failure table
    says the opposite ("leaves only `.part` litter", §3)."""
    fleet = FakeFleet(manifest_for())
    ytdlp.plan({"default": {"attempts": [
        {"exit": 1, "stderr": "ERROR: the audio stream died",
         "partials": ["{stem}.f137.mp4", "{stem}.f140.m4a.part",
                      "{stem}.temp.mp4"]},
    ]}})
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    outdir = outdir_for(tmp_path)
    assert sorted(p.name for p in outdir.iterdir()) == []
    assert ex.is_sweepable(f"Ch - T [{VID1}].f137.mp4") is True
    assert ex.is_sweepable(f"Ch - T [{VID1}].temp.mp4") is True
    # ...and the deliverable is still not litter: its stem ends in [id].
    assert ex.is_sweepable(f"Ch - T [{VID1}].mp4") is False
    assert ex.is_sweepable(f"A film about the f137 format [{VID1}].mp4") is False


def test_a_lid_closed_mid_clip_takes_the_finished_stream_with_it(tmp_path, ytdlp):
    """The laptop-lid case from COMP-BROLL-3's failure scenario: the server
    reclaims the lease and re-downloads the clip properly, so anything left
    here is a permanent duplicate the fleet then replicates."""
    fleet = FakeFleet(manifest_for())
    fleet.gone.add(("status", VID1, "downloading"))
    outdir = outdir_for(tmp_path)
    outdir.mkdir(parents=True)
    orphan = outdir / f"Some Channel - A clip [{VID1}].f137.mp4"
    orphan.write_text("1.4 GB of video-only stream")
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert not orphan.exists()


def test_a_failed_attempts_real_output_is_disowned_not_left_in_the_tree(
        tmp_path, ytdlp):
    """worker._disown_output's rule (YTDL-3), which this executor had no
    equivalent of: a download that got as far as a real file and then failed
    left `... [id].mp4` in the term folder carrying the `[id]` the disk-scan
    dedupe anchors on -- so every later search called the clip "already in the
    fleet" and pointed the editor at a file they cannot open. Here it is worse
    than on the NAS: lane A would carry the corpse up. `.failed` is outside
    that include list, and it is a rename rather than a delete because a
    half-written original is still footage somebody may want."""
    fleet = FakeFleet(manifest_for())
    ytdlp.plan({"default": {"attempts": [
        {"exit": 1, "stderr": "ERROR: died after the merge",
         "partials": ["{stem}.mp4"]},
    ]}})
    outdir = outdir_for(tmp_path)
    outdir.mkdir(parents=True)
    # Something with this clip's id that was ALREADY there is not ours to touch.
    stranger = outdir / f"Someone Else - Their clip [{VID1}].mp4"
    stranger.write_text("not this attempt's")
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert (outdir / f"Some Channel - A clip [{VID1}].mp4.failed").is_file()
    assert not (outdir / f"Some Channel - A clip [{VID1}].mp4").exists()
    assert stranger.read_text() == "not this attempt's"
    # ...and a disowned corpse is not read as the clip by the next attempt.
    assert ex.landed_file(outdir, VID1) == stranger.name


def test_yt_dlp_exiting_zero_with_no_file_is_a_failure(tmp_path, ytdlp):
    """YTDL-15's rule on this side: no file means the download did not land,
    whatever else the report says. A `done` with no name would write a ledger
    row saying "the fleet already has this" and pointing at nothing -- and the
    ledger never cascades."""
    fleet = FakeFleet(manifest_for())

    def run_fn(argv, timeout, on_spawn=None):
        return subprocess.CompletedProcess(argv, 0, "", "")

    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)
    deps.run = run_fn

    run_job(deps)

    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "failed")]
    assert "no output file" in fleet.body_for(VID1, "failed")["error"]


# ---------------------------------------------------------------------------
# refusals: the disk, the project, the URL, the rung
# ---------------------------------------------------------------------------


def test_a_project_this_machine_does_not_sync_is_refused(tmp_path, ytdlp):
    """§7: protects an editor's disk from a server bug pointing it outside the
    tree. Nothing is downloaded and nothing is reported -- the lease simply
    expires and the server takes the job back."""
    fleet = FakeFleet(manifest_for(label="2026/FF5/Some Other Show"))
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert ytdlp.calls == []
    assert fleet.statuses == []
    assert not outdir_for(tmp_path).exists()


def test_a_machine_that_cannot_read_its_selection_refuses_too(tmp_path, ytdlp):
    """None ("we could not ask") and [] ("this editor syncs nothing") are
    different answers, and both fail closed. The cost is a job the server
    downloads instead, which is what it did before this feature existed."""
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp, selection=None)
    deps._selection_fn = lambda: None

    run_job(deps)

    assert ytdlp.calls == [] and fleet.statuses == []


def test_the_base_rig_validates_against_its_own_tree_instead(tmp_path, ytdlp):
    """The base rig syncs nothing and has no selection to check against -- its
    local_root IS the NAS share. The directory test replaces the selection one,
    so a label naming nothing real is still refused."""
    cfg = make_cfg(tmp_path, mode="base")
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp, cfg=cfg, selection=[])
    (Path(cfg["local_root"]) / "Projects" / Path(*LABEL.split("/"))).mkdir(parents=True)

    run_job(deps)
    assert [s[1] for s in fleet.state_sequence] == ["downloading", "done"]

    fleet2 = FakeFleet(manifest_for(label="2026/FF5/Never Heard Of It",
                                    rel_dir="2026/FF5/Never Heard Of It/Youtube/x"))
    deps2 = make_deps(tmp_path, fleet=fleet2, ytdlp=ytdlp, cfg=cfg, selection=[])
    run_job(deps2)
    assert fleet2.statuses == []


@pytest.mark.parametrize("url", [
    "https://evil.example.com/watch?v=aaaaaaaaaaa",
    "https://youtube.com.evil.net/watch?v=aaaaaaaaaaa",
    "https://notyoutube.com/watch?v=aaaaaaaaaaa",
    "file:///C:/Windows/System32/calc.exe",
    "", None, 12,
])
def test_a_url_that_is_not_youtubes_is_never_handed_to_yt_dlp(tmp_path, ytdlp, url):
    """The manifest is token-authed and comes from our own dashboard, so this
    guards against a SERVER bug rather than the browser -- which contributes
    nothing but a job id. The clip is recorded failed so the row says
    something, and the server's second-chance sweep is what gets the editor
    their clip if this check is the thing that is wrong."""
    fleet = FakeFleet(manifest_for(clips=[{"video_id": VID1, "url": url}]))
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert ytdlp.calls == []
    assert fleet.state_sequence == [(VID1, "failed")]


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=aaaaaaaaaaa",
    "https://youtu.be/aaaaaaaaaaa",
    "https://m.youtube.com/watch?v=aaaaaaaaaaa",
    "https://music.youtube.com/watch?v=aaaaaaaaaaa",
    "https://rr3---sn-abc.googlevideo.com/videoplayback?x=1",
])
def test_youtubes_own_hosts_are_accepted(url):
    assert ex.url_is_youtube(url) is True


def test_a_nearly_full_disk_declines_before_the_claim(tmp_path, ytdlp, monkeypatch):
    """§7, the 0.7.x upgrade lesson: decline the claim, don't die at clip 40.
    Nothing is claimed at all, so the server never even learns this machine
    thought about it."""
    monkeypatch.setattr(ex, "free_bytes_at", lambda path: 100 * 1024 ** 2)
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert fleet.calls == []
    assert ytdlp.calls == []


@pytest.mark.parametrize("quality", ["best", "2160p", "1440p", "audio", ""])
def test_a_rung_only_the_server_can_name_is_handed_back(tmp_path, ytdlp, quality):
    """The scope cut (SCOPE_QUALITIES). Above 1080p YouTube serves no AVC, so
    the server transcodes and the deliverable is `<stem>.editready.mp4` -- a
    NAME this executor cannot reproduce, and half the fleet spelling a clip
    differently is the one failure §5 exists to prevent.

    The SPA sends a job id and nothing else (§8), so the quality is not known
    until after the claim: nothing is posted, the heartbeat stops, and the
    lease expires within lease_seconds (180 s), after which the server works
    the job as though no companion had ever answered."""
    fleet = FakeFleet(manifest_for(quality=quality))
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert fleet.claimed, "the claim happens before the quality is knowable"
    assert fleet.statuses == []
    assert ytdlp.calls == []


def test_a_template_skew_downloads_nothing(tmp_path, ytdlp):
    """Version skew degrades to server-side execution, NEVER to divergent
    files (§5). The claim already refuses it; this is the belt to that brace."""
    manifest = manifest_for()
    manifest["template_version"] = ytdl_common.TEMPLATE_VERSION + 1
    fleet = FakeFleet(manifest)
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert ytdlp.calls == [] and fleet.statuses == []


@pytest.mark.parametrize("sidecar_version", [
    ytdl_common.SIDECAR_VERSION + 1, ytdl_common.SIDECAR_VERSION - 1, None,
])
def test_a_sidecar_skew_downloads_nothing_either(tmp_path, ytdlp, sidecar_version):
    """COMP-BROLL-6: the sidecar half of the §5 handshake was advertised by the
    server (manifest AND client config) and compared by nobody. The two numbers
    exist separately because they fail differently -- a template skew
    duplicates clips, a sidecar skew feeds the Resolve credits script a shape
    it does not read, in files whose names look perfect. Nine fields on the
    NAS and eight on every editor's machine is exactly the divergence §5 is
    for."""
    manifest = manifest_for()
    manifest["sidecar_version"] = sidecar_version
    fleet = FakeFleet(manifest)
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)

    assert ytdlp.calls == [] and fleet.statuses == []


@pytest.mark.parametrize("status", [403, 409, 410, 500])
def test_a_refused_claim_is_never_an_error_anyone_sees(tmp_path, ytdlp, status):
    """403 stale yt-dlp, 409 somebody else holds it, 410 not claimable, 500 a
    broken dashboard: one outcome on this side -- the server downloads it
    exactly as it does today, which is the whole rollback story (§10)."""
    fleet = FakeFleet(manifest_for())
    fleet.claim_status = status
    fleet.claim_body = {"detail": "no"}
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)  # must not raise

    assert len(fleet.calls) == 1, "nothing was asked for after the refusal"
    assert ytdlp.calls == []


def test_a_403_on_a_yt_dlp_we_rank_as_current_says_the_floor_is_the_problem(
        tmp_path, ytdlp, caplog):
    """COMP-BROLL-9. This side ranks versions as tuples of ints, the dashboard
    compares the raw strings -- exact for yt-dlp's own zero-padded YYYY.MM.DD
    and wrong for the free-text YTDL_MIN_YTDLP_VERSION an operator types. One
    unpadded floor ('2026.8.5') 403s every claim from every machine while every
    companion concludes it is current, so local downloads die fleet-wide and
    the only line in any log says the yt-dlp is old. The ranking here is the
    correct one and stays; what is added is the sentence naming the cause."""
    fleet = FakeFleet(manifest_for())
    fleet.claim_status = 403
    fleet.claim_body = {"detail": {
        "detail": "yt-dlp 2026.08.11 is older than the fleet minimum 2026.8.5",
        "reason": "ytdlp_version", "min_ytdlp_version": "2026.8.5"}}
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    with caplog.at_level(logging.WARNING, logger="ccsync.ytdl"):
        run_job(deps)

    assert ytdlp.calls == []
    assert any("not zero-padded" in r.getMessage() for r in caplog.records)


def test_an_ordinary_stale_yt_dlp_403_says_nothing_of_the_sort(tmp_path, ytdlp,
                                                               caplog):
    """The genuinely-behind case is not a misconfiguration and must not be
    reported as one: the sidecar manager updates itself and the next claim
    works (§11)."""
    fleet = FakeFleet(manifest_for())
    fleet.claim_status = 403
    fleet.claim_body = {"detail": {"detail": "too old", "reason": "ytdlp_version",
                                   "min_ytdlp_version": "2027.01.01"}}
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    with caplog.at_level(logging.WARNING, logger="ccsync.ytdl"):
        run_job(deps)

    assert not any("zero-padded" in r.getMessage() for r in caplog.records)


def test_an_unreachable_dashboard_is_the_same_shrug(tmp_path, ytdlp):
    fleet = FakeFleet(manifest_for())
    fleet.transport_error = True
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    run_job(deps)  # must not raise

    assert ytdlp.calls == []


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_capabilities_is_ok_when_everything_is_in_place(tmp_path):
    deps = make_deps(tmp_path)
    cap = ex.capabilities(deps)
    assert cap["ok"] is True and cap["reason"] is None
    assert cap["editor"] == "editor2"
    assert cap["ytdlp_version"] == "2026.08.11"
    assert cap["template_version"] == ytdl_common.TEMPLATE_VERSION
    assert cap["sidecar_version"] == ytdl_common.SIDECAR_VERSION
    assert cap["free_bytes"] == 500 * 1024 ** 3


def test_capabilities_says_which_rungs_this_machine_runs(tmp_path):
    """COMP-BROLL-10: the SPA knows the job's quality when it decides whether
    to dispatch, and this is what lets it not dispatch the ones only the
    server can name -- instead of the companion claiming the job, reading the
    manifest, handing it back and leaving it still for the 180 s the lease
    takes to expire."""
    cap = ex.capabilities(make_deps(tmp_path))
    assert cap["scope_qualities"] == ["480p", "720p", "1080p"]
    assert cap["scope_qualities"] == list(ex.SCOPE_QUALITIES)


def test_capabilities_never_runs_the_binary(tmp_path, monkeypatch):
    """The SPA's probe aborts at 1 s (§2 step 2), and `yt-dlp --version` on a
    cold PyInstaller binary behind an AV scanner is allowed FIFTEEN
    (ytdlp_manager.VERSION_TIMEOUT_SECONDS). The answer is the sidecar
    manager's cached daily result, and this is what stops that regressing."""
    def _boom(*a, **kw):
        pytest.fail("the capability probe ran a subprocess")

    monkeypatch.setattr(ex.ytdlp_manager, "version", _boom)
    monkeypatch.setattr(ex.subprocess, "Popen", _boom)
    monkeypatch.setattr(ex.subprocess, "run", _boom)

    assert ex.capabilities(make_deps(tmp_path))["ok"] is True


@pytest.mark.parametrize("overrides,editor,ytdlp_ok,expected", [
    ({"ytdl_local_downloads": False}, "editor2", True, ex.REASON_DISABLED),
    ({"dashboard_url": ""}, "editor2", True, ex.REASON_NO_DASHBOARD),
    ({"dashboard_token": ""}, "editor2", True, ex.REASON_NO_DASHBOARD),
    ({}, "", True, ex.REASON_NO_EDITOR),
    ({}, None, True, ex.REASON_NO_EDITOR),
])
def test_capabilities_says_why_it_is_not_ok(tmp_path, overrides, editor,
                                            ytdlp_ok, expected):
    deps = make_deps(tmp_path, cfg=make_cfg(tmp_path, **overrides),
                     editor=editor, ytdlp_ok=ytdlp_ok)
    cap = ex.capabilities(deps)
    assert cap["ok"] is False
    assert cap["reason"] == expected
    # ...and it is still a complete answer: the SPA gets one round trip.
    assert cap["template_version"] == ytdl_common.TEMPLATE_VERSION


@pytest.mark.parametrize("ffmpeg_path", ["", "   ", "/nowhere/at/all/ffmpeg"])
def test_a_machine_with_no_ffmpeg_has_no_capability(tmp_path, ffmpeg_path):
    """COMP-BROLL-5. ffmpeg is genuinely OPTIONAL on this fleet (nothing in
    installer/ or onboarding/ provisions it, and proxy_generation_enabled is
    tri-state for that reason) -- but every rung in SCOPE_QUALITIES resolves to
    a `bestvideo...+bestaudio...` selector, which yt-dlp refuses outright with
    no merger. Before this, such a machine answered ok:true, claimed a 30-clip
    job, failed all 30, burned its own IP on the metadata calls and left the
    editor's name on 30 red rows -- while §6 promises "editors never see a
    broken local downloader, they see the old behaviour"."""
    deps = make_deps(tmp_path, cfg=make_cfg(tmp_path, ffmpeg_path=ffmpeg_path))
    cap = ex.capabilities(deps)
    assert cap["ok"] is False
    assert cap["reason"] == ex.REASON_NO_FFMPEG
    assert cap["ytdlp_version"] == "2026.08.11", "still a complete answer"


def test_a_machine_with_no_ffmpeg_never_claims_the_job(tmp_path, ytdlp):
    """...and the decline happens before the claim, so the server works the job
    as though no companion had answered -- no lease to wait out, no red rows."""
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp,
                     cfg=make_cfg(tmp_path, ffmpeg_path=""))
    deps.cfg["ytdlp_path"] = str(ytdlp.script)

    run_job(deps)

    assert fleet.calls == [] and ytdlp.calls == []


def test_capabilities_passes_the_sidecars_own_message_through(tmp_path):
    """A stale/missing/broken yt-dlp is not an error state to nag about -- it
    means this machine has no capability, and the message ytdlp_manager already
    wrote is the one worth logging."""
    deps = make_deps(tmp_path, ytdlp_ok=False)
    deps.ytdlp = FakeYtDlpManager(ok=False, version=None,
                                  message="no yt-dlp on this machine")
    cap = ex.capabilities(deps)
    assert cap["ok"] is False and cap["reason"] == "no yt-dlp on this machine"


def test_no_sidecar_manager_at_all_is_no_capability(tmp_path):
    from ccsync_companion import ytdl_attestation

    ytdl_attestation.accept("editor2")
    deps = ex.Deps(make_cfg(tmp_path), editor_fn=lambda: "editor2",
                   identity_token_fn=lambda: "v2.identity.token")
    cap = ex.capabilities(deps)
    assert cap["ok"] is False and "sidecar" in cap["reason"]


# ---------------------------------------------------------------------------
# POST /ytdl/download + the one-job guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("job_id", [None, "7", 7.0, True, False, 0, -1, [7], {}])
def test_the_download_endpoint_reads_a_job_id_and_nothing_else(tmp_path, job_id):
    """Plan §8: the browser contributes a job id and nothing else. `True` is
    called out because isinstance(True, int) is True in Python -- a JSON `true`
    would otherwise become job 1."""
    status, body = ex.start(job_id, make_deps(tmp_path))
    assert status == 400 and body["ok"] is False


def test_the_download_endpoint_declines_when_the_capability_is_gone(tmp_path):
    deps = make_deps(tmp_path, cfg=make_cfg(tmp_path, ytdl_local_downloads=False))
    status, body = ex.start(7, deps)
    assert status == 503
    assert body["message"] == ex.REASON_DISABLED
    assert ex.current_job() is None


def test_the_download_endpoint_answers_202_and_downloads_on_a_thread(
        tmp_path, ytdlp):
    """8899 must answer immediately: the job takes minutes and the SPA is
    waiting on this response."""
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    status, body = ex.start(7, deps)
    assert status == 202 and body == {"ok": True, "job_id": 7, "state": "started"}

    _join_current()
    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "done")]


def test_only_one_job_at_a_time(tmp_path, ytdlp):
    """Two browser tabs, or one editor clicking twice: the second gets 409 and
    the first keeps its lease (§11). The guard is module state because what it
    protects is the MACHINE -- two jobs would compete for one line."""
    started = threading.Event()
    release = threading.Event()

    def blocking_run(argv, timeout, on_spawn=None):
        started.set()
        release.wait(10)
        return ytdlp.run_fn(argv, timeout, on_spawn)

    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)
    deps.run = blocking_run

    assert ex.start(7, deps)[0] == 202
    assert started.wait(10), "the first job never reached yt-dlp"

    status, body = ex.start(8, ex.Deps(make_cfg(tmp_path)))
    assert status == 409 and body["job_id"] == 7

    release.set()
    _join_current()
    # ...and once it is finished the machine is free again.
    assert ex.current_job() is None


def test_progress_mirrors_the_running_job_then_the_last_one(tmp_path, ytdlp):
    fleet = FakeFleet(manifest_for(clips=[
        {"video_id": VID1, "url": watch(VID1)},
        {"video_id": VID2, "url": watch(VID2)},
    ]))
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)

    assert ex.progress(7) == {"job_id": 7, "running": False, "clip": None,
                              "done": 0, "failed": 0, "total": 0}
    ex.start(7, deps)
    _join_current()

    done = ex.progress(7)
    assert done["running"] is False
    assert (done["done"], done["failed"], done["total"]) == (2, 0, 2)
    # A job id nobody here has heard of gets the empty shape, not somebody
    # else's numbers.
    assert ex.progress(999)["total"] == 0


def _join_current(timeout: float = 30.0) -> None:
    """Wait for the running job to finish. Polling the module guard rather than
    the thread object: start() deliberately does not hand one out."""
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        job = ex.current_job()
        if job is None or not job.running:
            return
        _time.sleep(0.02)
    raise AssertionError("the download job never finished")


# ---------------------------------------------------------------------------
# the pieces underneath
# ---------------------------------------------------------------------------


def test_the_landed_file_is_anchored_on_the_id_at_the_end_of_the_stem(tmp_path):
    """ytsearch._ID_RE's rule (YTDL-27): `... [id].credits.json` and
    `... [id].mp4.part` carry the id but are not the clip."""
    outdir = tmp_path / "term"
    outdir.mkdir()
    for name in (f"A clip [{VID1}].mp4.part", f"A clip [{VID1}].credits.json",
                 f"A clip [{VID1}].info.json", f"A clip [{VID1}].f137.mp4.ytdl"):
        (outdir / name).write_text("x")
    assert ex.landed_file(outdir, VID1) is None

    (outdir / f"A clip [{VID1}].mp4").write_text("x")
    assert ex.landed_file(outdir, VID1) == f"A clip [{VID1}].mp4"


def test_a_video_id_with_brackets_and_dashes_is_matched_by_substring(tmp_path):
    """Never a glob: a video id may contain any of `[]-_` and one bad escape
    silently matches nothing (worker._id_bearing_files)."""
    weird = "a-b_c[d]ef"
    outdir = tmp_path / "term"
    outdir.mkdir()
    (outdir / f"Clip [{weird}].mp4").write_text("x")
    (outdir / f"Clip [{weird}].mp4.part").write_text("x")
    assert ex.landed_file(outdir, weird) == f"Clip [{weird}].mp4"
    ex.clear_partials(outdir, weird)
    assert list(outdir.glob("*.part")) == []
    assert (outdir / f"Clip [{weird}].mp4").exists()


def test_the_sidecar_is_written_the_way_the_server_writes_it(tmp_path):
    """§5 says BYTE-identical artifacts, and the sidecar is one of them:
    `indent=2, ensure_ascii=False`, exactly downloader._write_sidecar's call.
    ensure_ascii defaults to True, so without it every CJK or accented title
    would be \\u-escaped on the editor's machine and literal on the NAS -- one
    file, two encodings, one canonical tree."""
    info = tmp_path / f"Chaine - Un été [{VID1}].info.json"
    info.write_text(json.dumps({
        "id": VID1, "title": "Un été à 東京", "uploader": "Chaîne",
        "channel_url": "https://c", "webpage_url": watch(VID1),
        "upload_date": "20260801", "duration": 12.0,
    }), encoding="utf-8")
    video = tmp_path / f"Chaine - Un été [{VID1}].mp4"
    video.write_text("x")

    path, parsed = ex.write_sidecar(video, info)

    assert parsed["title"] == "Un été à 東京"
    raw_bytes = Path(path).read_bytes()
    # LF, on Windows too: text mode would translate to os.linesep, so an
    # editor's machine would write CRLF into a file the Linux container writes
    # LF into -- and on the base rig both spellings land in the same folder.
    assert b"\r\n" not in raw_bytes
    raw = Path(path).read_text(encoding="utf-8")
    assert "東京" in raw and "\\u" not in raw
    assert raw == json.dumps(
        ytdl_common.credits_sidecar(json.loads(
            json.dumps({"id": VID1, "title": "Un été à 東京",
                        "uploader": "Chaîne", "channel_url": "https://c",
                        "webpage_url": watch(VID1), "upload_date": "20260801",
                        "duration": 12.0}))),
        indent=2, ensure_ascii=False)
    assert not info.exists()


def test_a_missing_info_json_still_leaves_a_clip_and_no_sidecar(tmp_path):
    video = tmp_path / f"A clip [{VID1}].mp4"
    video.write_text("x")
    assert ex.write_sidecar(video, None) == (None, None)
    assert video.exists()


def test_a_sidecar_that_could_not_be_written_keeps_the_info_json(tmp_path,
                                                                 monkeypatch):
    """COMP-BROLL-8: the unlink used to run whatever happened above it. A full
    disk, a share that dropped, or a name over Windows' 260 characters meant
    the warning was logged, the info json was deleted anyway, and the clip was
    then reported `done` -- with no sidecar, and nothing that ever regenerates
    one for a done clip. A leftover info json is recoverable; a deleted one is
    not."""
    info = tmp_path / f"A clip [{VID1}].info.json"
    info.write_text(json.dumps({"id": VID1, "title": "A clip"}), encoding="utf-8")
    video = tmp_path / f"A clip [{VID1}].mp4"
    video.write_text("x")

    def refuse(*_a, **_kw):
        raise OSError(206, "the file name is too long")

    monkeypatch.setattr(Path, "write_text", refuse)

    path, parsed = ex.write_sidecar(video, info)

    assert path is None
    assert info.exists(), "the only source the credits could be rebuilt from"
    # ...and the dict that WAS parsed is still handed back: the ledger's title
    # and channel do not depend on the sidecar write having succeeded
    # (YTDL-WEB-8 meets COMP-BROLL-8).
    assert parsed["title"] == "A clip"


def test_an_unreadable_info_json_is_kept_too(tmp_path):
    """Same rule, the other failure branch: json.loads said no, so nothing was
    written and nothing may be thrown away."""
    info = tmp_path / f"A clip [{VID1}].info.json"
    info.write_text("{not json", encoding="utf-8")
    video = tmp_path / f"A clip [{VID1}].mp4"
    video.write_text("x")

    assert ex.write_sidecar(video, info) == (None, None)
    assert info.exists()


def test_the_default_runner_captures_the_exit_code_and_stderr():
    """ex.default_run is what talks to the real yt-dlp.exe: a non-zero exit and
    its stderr are the entire failure signal on a CLI boundary -- the
    truncation fallback is decided from that text."""
    proc = ex.default_run(
        [sys.executable, "-c",
         "import sys; sys.stderr.write('Giving up after 10 retries'); sys.exit(3)"],
        60)
    assert proc.returncode == 3
    assert "Giving up after" in proc.stderr


def test_the_default_runner_hands_the_child_out_so_a_lost_lease_can_kill_it():
    seen: list = []
    proc = ex.default_run([sys.executable, "-c", "pass"], 60, seen.append)
    assert proc.returncode == 0
    assert len(seen) == 1 and hasattr(seen[0], "kill")


def test_a_410_anywhere_raises_lease_lost_and_nothing_else_does(tmp_path):
    """routes_fleet's 410 docstring is the contract: "your claim is over" is
    the answer to every way this can fail, and the companion's response to all
    of them is the same one."""
    answers = {"status": 410}

    def request(method, url, body, headers, timeout):
        return answers["status"], {"detail": "gone"}

    deps = ex.Deps(make_cfg(tmp_path), request_fn=request)
    client = ex.FleetClient(deps, "editor2")
    with pytest.raises(ex.LeaseLost):
        client.heartbeat(7)
    with pytest.raises(ex.LeaseLost):
        client.manifest(7)
    with pytest.raises(ex.LeaseLost):
        client.clip_status(7, VID1, "done", filepath_rel="x.mp4")

    answers["status"] = 500
    client.clip_status(7, VID1, "done", filepath_rel="x.mp4")  # logged, not raised


def test_default_request_turns_an_http_error_into_an_answer(monkeypatch):
    """410 and 409 are ordinary outcomes this executor branches on, so they may
    not arrive as urllib exceptions -- a caller that had to know urllib's shape
    is a caller a test stubs wrong."""
    import urllib.error

    class _Opener:
        # Stubbed at the OPENER, not at urlopen: since 2026-08-17 this request
        # goes through upgrade.build_no_redirect_opener so the fleet token can
        # never be re-sent to a redirect target (COMMERCIAL_READINESS.md item
        # 15). Patching urlopen would leave the test passing against code that
        # no longer calls it.
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 410, "Gone", {},
                                         _BytesResponse(b'{"detail": "reclaimed"}'))

    monkeypatch.setattr(ex.upgrade_mod, "build_no_redirect_opener",
                        lambda *handlers: _Opener())
    status, parsed = ex.default_request("POST", "http://d/x", {"a": 1}, {}, 5)
    assert status == 410 and parsed == {"detail": "reclaimed"}


class _BytesResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, *_a):
        return self._payload

    def close(self):
        # HTTPError closes the file object it was handed when it is collected;
        # without this the GC raises during an unrelated later test.
        pass


# ---------------------------------------------------------------------------
# over the wire, on the ONE 8899 listener
# ---------------------------------------------------------------------------


class Client:
    """test_ytdl_server.Client's shape -- same listener, same conventions.

    Every POST carries the loopback token: since 2026-08-17
    (COMMERCIAL_READINESS.md item 5) a state-changing request on 8899 needs an
    allowed Origin or that header, and the executor's callers are the SPA on
    the dashboard origin and local ones. Without it every /ytdl/download here
    was answering 403 instead of the status the test is about.
    """

    def __init__(self, port: int):
        self.port = port

    def _connect(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def get(self, path: str):
        conn = self._connect()
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def post_json(self, path: str, obj):
        conn = self._connect()
        payload = json.dumps(obj).encode("utf-8")
        conn.request("POST", path, body=payload,
                     headers={"Content-Type": "application/json",
                              "Content-Length": str(len(payload)),
                              loopback_guard.TOKEN_HEADER:
                                  loopback_guard.read_token() or ""})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)


@pytest.fixture
def live_server(tmp_path, ytdlp, monkeypatch):
    """The real 8899 handler on an ephemeral port, with the executor wired the
    way app.py wires it. A SECOND listener on that port breaks the tray app
    (CLAUDE.md), which is why these routes are here at all."""
    monkeypatch.setattr(music_server, "call",
                        lambda action, timeout=None, **kw: {"ok": True})
    fleet = FakeFleet(manifest_for())
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)
    cfg = {"mounts": {}, music_server.MOUNTS_KEY: {},
           ytdl_server.MOUNTS_KEY: {}}
    srv = broll_server.make_server(cfg, host="127.0.0.1", port=0,
                                   ccsync_cfg=deps.cfg, ytdl_deps=deps)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(srv.server_address[1]), fleet, deps
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_capabilities_over_http_is_200_with_the_verdict_in_the_body(live_server):
    client, _fleet, _deps = live_server
    status, body = client.get("/ytdl/capabilities")
    assert status == 200
    assert body["ok"] is True
    assert body["template_version"] == ytdl_common.TEMPLATE_VERSION


def test_download_over_http_is_202_then_409(live_server, tmp_path):
    client, fleet, _deps = live_server
    status, body = client.post_json("/ytdl/download", {"job_id": 7})
    assert status == 202 and body["job_id"] == 7
    _join_current()
    assert fleet.state_sequence == [(VID1, "downloading"), (VID1, "done")]

    status, body = client.post_json("/ytdl/download", {"job_id": "seven"})
    assert status == 400 and body["ok"] is False


def test_the_download_route_ignores_everything_but_the_job_id(live_server, tmp_path):
    """§8: no paths, no URLs, no templates from the browser. A body carrying
    them is not an error -- they are simply never read, and the download that
    follows writes exactly where the SERVER's manifest said."""
    client, fleet, _deps = live_server
    status, _body = client.post_json("/ytdl/download", {
        "job_id": 7,
        "outdir": "C:/Windows/System32",
        "url": "https://evil.example.com/x",
        "project_rel_path": "../../../evil",
    })
    assert status == 202
    _join_current()
    assert (outdir_for(tmp_path) /
            f"Some Channel - A clip [{VID1}].mp4").is_file()


def test_progress_over_http(live_server):
    client, _fleet, _deps = live_server
    status, body = client.get("/ytdl/progress?job_id=7")
    assert status == 200
    assert set(body) == {"job_id", "running", "clip", "done", "failed", "total"}
    # A junk job id is not a 400: this endpoint is a mirror the SPA may ignore.
    assert client.get("/ytdl/progress?job_id=abc")[0] == 200


def test_a_malformed_download_body_is_400_not_a_dead_request(live_server):
    client, _fleet, _deps = live_server
    conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=5)
    conn.request("POST", "/ytdl/download", body=b"{not json",
                 headers={"Content-Type": "application/json",
                          "Content-Length": "9",
                          loopback_guard.TOKEN_HEADER:
                              loopback_guard.read_token() or ""})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 400 and body["ok"] is False


def test_a_server_with_no_executor_deps_has_no_capability(tmp_path, monkeypatch):
    """The fallback is capability-less rather than clever: a build whose app
    never managed to construct the deps downloads on the NAS, exactly as the
    fleet did before 0.8.0."""
    monkeypatch.setattr(music_server, "call",
                        lambda action, timeout=None, **kw: {"ok": True})
    srv = broll_server.make_server({"mounts": {}}, host="127.0.0.1", port=0,
                                   ccsync_cfg=make_cfg(tmp_path))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = Client(srv.server_address[1]).get("/ytdl/capabilities")
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
    assert status == 200 and body["ok"] is False


# --------------------------------------------- CR-31: a blip is not a verdict

def test_a_transport_failure_is_retried_inside_the_lease(tmp_path):
    """CR-31 (2026-08-19). The dashboard container restarted mid-job -- three
    seconds -- and the clip-status POST that landed in the gap raised
    ConnectionRefused. It left _call, left _download_all, and run()'s catch-all
    ended the whole local download at clip 2 of 22. The server then reclaimed
    the expired lease and downloaded the remaining 20 onto the NAS, where lane
    B does not bring YouTube originals down: the editor lost their footage to
    an outage they never saw.

    The lease is 180 s and the heartbeat renews it every 30. Nothing about a
    three second gap is a reason to hand a job back.
    """
    calls: list = []
    slept: list = []

    def request(method, url, body, headers, timeout):
        calls.append(url)
        if len(calls) < 3:
            raise ConnectionRefusedError(10061, "actively refused")
        return 200, {"ok": True}

    deps = ex.Deps(make_cfg(tmp_path), request_fn=request)
    client = ex.FleetClient(deps, "editor2", sleep=slept.append,
                            clock=lambda: 0.0)
    client.clip_status(7, VID1, "done", filepath_rel="x.mp4")

    assert len(calls) == 3
    # Backing off, not hammering: the first wait is the configured one and each
    # is longer than the last.
    assert slept == [ex.CALL_RETRY_FIRST_BACKOFF,
                     ex.CALL_RETRY_FIRST_BACKOFF * 2]


def test_the_retry_is_bounded_by_the_lease_and_then_gives_up(tmp_path):
    """A dashboard that has been unreachable for a minute has already let the
    lease lapse, and the server is downloading what this machine did not. The
    budget is on ELAPSED time, not on an attempt count: six attempts that each
    time out at HTTP_TIMEOUT_SECONDS is 90 s of wall clock, not six seconds."""
    calls: list = []
    now = {"t": 0.0}

    def request(method, url, body, headers, timeout):
        calls.append(url)
        now["t"] += 30.0          # each attempt burns half the budget
        raise ConnectionRefusedError(10061, "actively refused")

    deps = ex.Deps(make_cfg(tmp_path), request_fn=request)
    client = ex.FleetClient(deps, "editor2", sleep=lambda s: None,
                            clock=lambda: now["t"])
    with pytest.raises(ConnectionRefusedError):
        client.manifest(7)
    # Two attempts, not "until the heat death". The deadline is fixed when the
    # call starts (t=0 + 60 s): the first attempt ends at t=30 and there is
    # budget left, the second ends at t=60 and there is not, so it propagates.
    assert len(calls) == 2


def test_a_status_code_is_never_retried(tmp_path):
    """default_request's rule, and this is the half that must not drift: an
    HTTP status is an ANSWER. Retrying a 410 would turn the server's one-way
    reclaim into a ping-pong, and retrying a 500 would multiply a server-side
    error by six."""
    calls: list = []

    def request(method, url, body, headers, timeout):
        calls.append(url)
        return 500, {"detail": "boom"}

    deps = ex.Deps(make_cfg(tmp_path), request_fn=request)
    client = ex.FleetClient(deps, "editor2", sleep=lambda s: None)
    client.clip_status(7, VID1, "done", filepath_rel="x.mp4")
    assert len(calls) == 1

    calls.clear()

    def gone(method, url, body, headers, timeout):
        calls.append(url)
        return 410, {"detail": "reclaimed"}

    client = ex.FleetClient(ex.Deps(make_cfg(tmp_path), request_fn=gone),
                            "editor2", sleep=lambda s: None)
    with pytest.raises(ex.LeaseLost):
        client.heartbeat(7)
    assert len(calls) == 1


def test_a_shutdown_stops_the_retry_at_once(tmp_path):
    """The tray asking to quit must be felt during a backoff, not up to
    CALL_RETRY_MAX_BACKOFF later -- which is why the job passes its stop
    Event's wait() as the sleep."""
    calls: list = []
    stopping = {"yes": False}

    def request(method, url, body, headers, timeout):
        calls.append(url)
        stopping["yes"] = True
        raise ConnectionRefusedError(10061, "actively refused")

    deps = ex.Deps(make_cfg(tmp_path), request_fn=request)
    client = ex.FleetClient(deps, "editor2", sleep=lambda s: None,
                            should_stop=lambda: stopping["yes"])
    with pytest.raises(ConnectionRefusedError):
        client.manifest(7)
    assert len(calls) == 1
