"""The b-roll ingest orchestrator (broll_ingest.py).

docs/BROLL_INGEST_PLAN.md §5-§6. Everything here runs with no ffmpeg, no GPU,
no dashboard and no rclone: the seams exist precisely so the state machine --
the gate order, the checkpoints, the resume, the lease -- can be tested on a
machine that has none of those, which is every CI runner and most laptops.

The three properties this file is really about, because they are the ones a
bug in would cost an editor their evening:

  * the GATE order, including the two run modes and the VRAM refusal;
  * the CHECKPOINTS -- every transition on disk before it is believed, so a
    companion killed mid-batch resumes rather than restarts;
  * the PRECEDENCE reversal: while a batch crunches, the proxy generator is
    blocked, never the other way round (owner review (a), 2026-08-18).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccsync_companion import broll_ingest, popup, proxy_gen


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

class FakeSidecar:
    """broll_vlm_sidecar's surface, with no GPU and no downloads."""

    def __init__(self, fits=True, ready=True, runtime=True):
        self._fits = fits
        self._ready = ready
        self._runtime = runtime
        self.ensured: list = []
        self.stopped = 0
        self.servers: list = []
        self.downloading = None

    def fits(self, tier, gpu_info=None):
        if self._fits:
            return True, ""
        return False, ("Can't index b-roll: Best needs 12 GB VRAM, this GPU has "
                       "8 GB - choose Good")

    def status(self):
        return {"runtime_ready": self._runtime,
                "model_ready": {"good": self._ready, "best": self._ready},
                "gpu": {"present": True, "vram_gb": 8},
                "downloading": self.downloading, "last_error": ""}

    def ensure(self, tier, progress_cb=None, stop_event=None):
        self.ensured.append(tier)
        self._ready = True
        self._runtime = True
        return True, "Good is ready"

    def server(self, tier, cfg=None, gpu_layers=99):
        handle = type("Handle", (), {"url": "http://127.0.0.1:9999"})()
        self.servers.append(handle)
        return handle

    def stop_server(self):
        self.stopped += 1

    def server_log_path(self, cfg=None):
        return Path("broll_vlm_server.log")

    def cache_dir(self):
        return Path("cache")


class FakeMedia:
    """broll_ingest_media's surface. Every argv builder returns a marker list;
    nothing spawns."""

    UnreadableMediaError = RuntimeError

    def __init__(self):
        self.calls: list = []

    def probe(self, ffmpeg, path):
        return {"duration_s": 10.0, "fps": 25.0, "width": 1920, "height": 1080,
                "codec": "h264", "shot_date": "2026-08-18", "timecode": None}

    def hash_partial(self, path):
        return "cafebabe"

    def preview_proxy_cmd(self, ffmpeg, src, dest, *, nvenc, timecode=None):
        return ["proxy", str(dest), "nvenc" if nvenc else "cpu"]

    def poster_cmd(self, ffmpeg, src, dest, duration_s, width=640):
        return ["poster", str(dest)]

    def thumb_cmd(self, ffmpeg, src, dest, duration_s, width=160):
        return ["thumb", str(dest)]

    def sprite_geometry(self, duration_s, **kw):
        return {"sprite_cols": 10, "sprite_rows": 1, "sprite_cells": 6,
                "sprite_interval_s": 2.0, "cell_width": 240}

    def sprite_cmd(self, ffmpeg, src, dest, geometry):
        return ["sprite", str(dest)]

    def scene_detect_cmd(self, ffmpeg, src, threshold=0.3):
        return ["scenes", str(src)]

    def parse_scene_timestamps(self, stderr):
        return [0.0, 4.0]

    def fill_gaps(self, timestamps, duration_s, max_gap_s=4.0):
        return [0.0, 4.0, 8.0]

    def frame_path(self, frames_dir, index):
        return Path(frames_dir) / f"frame_{index:04d}.jpg"

    def extract_frame_cmd(self, ffmpeg, src, timestamp, dest, duration_s=None,
                          safety_margin=0.05):
        return ["frame", str(dest)]

    def write_frames_json(self, sheets_dir, timestamps, sheets=()):
        Path(sheets_dir).mkdir(parents=True, exist_ok=True)
        path = Path(sheets_dir) / "frames.json"
        path.write_text(json.dumps({"timestamps": list(timestamps), "sheets": []}),
                        encoding="utf-8")
        return path

    def run_ffmpeg(self, cmd, timeout=None):
        """Succeed AND leave the file behind: the orchestrator checks that an
        output exists before it believes an exit code, because NVENC exits 0
        having written nothing when every session is taken."""
        self.calls.append(list(cmd))
        if cmd[0] in ("proxy", "poster", "sprite", "thumb", "frame"):
            dest = Path(cmd[1])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x" * 10)
        return 0, ""


class FakeQueue:
    """broll_upload.UploadQueue's surface: everything "lands" at once unless a
    test says otherwise.

    Two things it models rather than simplifies away, because the orchestrator
    has to answer to both (2026-08-21): `stop_all` is a ONE-WAY latch, so a job
    enqueued after it is never drained; and `failures()` is a ledger a caller
    has to clear with `retry()` before re-sending the same rel.
    """

    def __init__(self):
        self.jobs: list = []
        self.failed: list = []
        self._paused = False
        self.stopped = False
        self.land = True
        # Every rel ever handed over, including the ones that went nowhere:
        # what a retry assertion counts.
        self.enqueued: list = []
        # Rels this machine's rclone cannot send. They land in `failed`
        # instead of `jobs`, and they do it again after a retry -- a NAS that
        # is gone is gone for more than one attempt.
        self.fail_rels: set = set()
        # Jobs handed to a STOPPED queue: appended, never drained, exactly as
        # the real one leaves them.
        self.dead: list = []

    def enqueue(self, local_path, remote_rel, kind, item_uid="", size_bytes=None):
        job = {"rel": remote_rel, "kind": kind, "item_uid": item_uid,
               "size": size_bytes, "local": str(local_path)}
        self.enqueued.append(remote_rel)
        if self.stopped:
            self.dead.append(job)
            return
        if remote_rel in self.fail_rels:
            self.failed.append({"rel": remote_rel, "kind": kind,
                                "item_uid": item_uid,
                                "error": "rclone exited with code 1"})
            return
        self.jobs.append(job)

    def uploaded(self):
        return list(self.jobs) if self.land else []

    def failures(self):
        return list(self.failed)

    def retry(self, rels):
        wanted = {str(rel) for rel in rels}
        keep = [job for job in self.failed if job["rel"] not in wanted]
        dropped = len(self.failed) - len(keep)
        self.failed = keep
        return dropped

    def progress(self):
        return {"queued": 0 if self.land else len(self.jobs), "active": None,
                "done": len(self.jobs), "failed": len(self.failed),
                "paused": self._paused}

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop_all(self):
        self.stopped = True


class FakeServer:
    """The fleet routes, as a request_fn. Records every call and answers the
    manifest the plan's §4.2 describes."""

    def __init__(self, items=None):
        self.calls: list = []
        self.claim_status = 200
        self.claim_body: dict = {}
        self.status_codes: dict = {}
        # What /items/<uid>/result answers. A refusal there is the whole of
        # comp-loopback-4 (2026-08-21).
        self.result_status = 200
        self.result_body: dict = {"ok": True}
        self.uploaded_status = 200
        self.uploaded_body: dict = {"ok": True, "live": True}
        self.heartbeat_body: dict = {"ok": True, "cancel_requested": False,
                                     "upload_paused": False}
        self.lease_lost = False
        self.items = items if items is not None else [{
            "uid": "i" * 32, "ord": 0, "orig_name": "A001.MP4", "rel_dir": "",
            "size_bytes": 100, "hash": "cafebabe", "video_id": 4127,
            "share": "creators", "rel_path": "2026-08-18 ingest/A001.MP4",
            "archive_dir": "creators/2026-08-18 ingest", "archive_stem": "A001",
            "state": "pending", "duplicate_of": None, "source": "upload",
            "attempts": 0,
        }]

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "body": body,
                           "headers": headers})
        if self.lease_lost and not url.endswith("/claim"):
            return 410, {"detail": {"detail": "the lease expired",
                                    "reason": "lease_expired"}}
        if url.endswith("/claim"):
            if self.claim_status != 200:
                return self.claim_status, {"detail": "no"}
            return 200, self.claim_body or {
                "batch": {"uid": "b" * 32, "share": "creators", "state": "claimed",
                          "upload_paused": False},
                "settings": {"tier": "good", "run_mode": "idle",
                             "upload_originals": True, "keep_subfolders": True},
                "lease_seconds": 300, "heartbeat_seconds": 30,
                "archive_remote_rel": "Assets/B-roll Archive",
                "taxonomy": [{"slug": "people", "label": "People",
                              "description": "humans"}],
                "items": self.items,
            }
        if url.endswith("/heartbeat"):
            return 200, dict(self.heartbeat_body)
        if url.endswith("/uploaded"):
            return self.uploaded_status, self.uploaded_body
        if url.endswith("/release"):
            return 200, {"ok": True}
        if url.endswith("/result"):
            return self.result_status, self.result_body
        if url.endswith("/status"):
            state = (body or {}).get("state")
            return self.status_codes.get(state, 200), {"ok": True}
        return 200, {"ok": True}

    # -- helpers the assertions read --------------------------------------
    def states(self):
        return [c["body"]["state"] for c in self.calls
                if c["url"].endswith("/status")]

    def released(self):
        return [c["body"] for c in self.calls if c["url"].endswith("/release")]


class FakeIdle:
    def __init__(self, seconds=None):
        self.seconds = seconds

    def seconds_idle(self):
        return self.seconds


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    """The staging root is pytest's tmp dir on the host's system drive, and
    prepare() measures its REAL free space against the 20 GB floor. Faked
    here so a full base-rig disk (2026-08-18) cannot fail tests about
    anything else; the tests that mean to measure it override this."""
    from ccsync_companion import broll_server as _bs

    monkeypatch.setattr(_bs, "_free_bytes_at", lambda _d: 10 ** 12)


def make_ingestor(tmp_path, *, server=None, sidecar=None, media=None, queue=None,
                  idle=None, describe=None, cfg_extra=None, **kwargs):
    cfg = {
        "local_root": str(tmp_path / "tree"),
        "dashboard_url": "http://dash.example",
        "dashboard_token": "t" * 32,
        "broll_ingest_staging_dir": str(tmp_path / "staging"),
        "broll_ingest_idle_seconds": 300,
    }
    cfg.update(cfg_extra or {})
    (tmp_path / "tree").mkdir(exist_ok=True)
    deps = broll_ingest.IngestDeps(
        cfg, editor_fn=lambda: "alex", identity_token_fn=lambda: "signed",
        request_fn=server if server is not None else FakeServer(),
        machine_name="EDIT-1")
    # The defaults are a machine that CAN index -- ffmpeg present, NVENC
    # present, the editor away -- so every test only has to say what is
    # different about its own machine. kwargs wins, which is what lets a gate
    # test switch one of them off.
    options = {
        "sidecar": sidecar if sidecar is not None else FakeSidecar(),
        "media": media if media is not None else FakeMedia(),
        "uploader": queue if queue is not None else FakeQueue(),
        "idle_probe": idle if idle is not None else FakeIdle(9999),
        "available_fn": lambda path: (True, "ok"),
        "encoders_fn": lambda path: frozenset({"h264_nvenc"}),
        "describe_fn": describe or _fake_describe,
    }
    options.update(kwargs)
    return broll_ingest.BrollIngestor(cfg, tmp_path / "state", deps=deps, **options)


def _fake_describe(cfg, storage, video, *, server_url=None, log_usage=None):
    storage.write_index_result(
        video["id"], themes=["interview"], quality_flags=[],
        category_hint="people", model="local:qwen",
        segments=[{"t_start": 0, "t_end": 4, "description": "a person talks"}])
    return storage.result


def stage_one_clip(ingestor, tmp_path, name="A001.MP4"):
    """A staged upload with bytes on disk, as prepare + PUT would leave it."""
    status, body = ingestor.prepare({"items": [
        {"local_id": "c1", "name": name, "size": 4, "source": "upload"}]})
    assert status == 202
    staging_id = body["staging_id"]
    path = Path(ingestor.staging_dir(staging_id)) / f"c1{Path(name).suffix.lower()}"
    path.write_bytes(b"data")
    ingestor.note_upload(staging_id, "c1", 4)
    return staging_id


# ---------------------------------------------------------------------------
# the gate (plan §5)
# ---------------------------------------------------------------------------

def test_the_gate_asks_the_questions_in_the_editors_order(tmp_path):
    """disabled -> drive absent -> paused -> misconfigured -> no ffmpeg ->
    no model -> tier unfit -> nothing to do -> away -> Resolve -> running.
    The FIRST true answer wins, so each of these must beat the ones below."""
    ing = make_ingestor(tmp_path, cfg_extra={"broll_ingest_enabled": False})
    assert ing._gate() == broll_ingest.STATE_DISABLED

    ing = make_ingestor(tmp_path, root_present_fn=lambda: False)
    assert ing._gate() == broll_ingest.STATE_DRIVE_ABSENT

    ing = make_ingestor(tmp_path, paused_fn=lambda: True)
    assert ing._gate() == broll_ingest.STATE_PAUSED

    ing = make_ingestor(tmp_path, blocked_fn=lambda: True)
    assert ing._gate() == broll_ingest.STATE_MISCONFIGURED

    ing = make_ingestor(tmp_path, available_fn=lambda p: (False, "no ffmpeg"))
    assert ing._gate() == broll_ingest.STATE_NO_FFMPEG

    ing = make_ingestor(tmp_path, sidecar=FakeSidecar(ready=False))
    assert ing._gate() == broll_ingest.STATE_NO_MODEL

    # Nothing claimed: everything above passes and there is no work.
    assert make_ingestor(tmp_path)._gate() == broll_ingest.STATE_NOTHING_TO_DO


def test_a_tier_this_gpu_cannot_run_never_downloads_a_model(tmp_path):
    """The plan lists no-model before tier-unfit; the one deviation is here,
    and it is deliberate -- spending 3.9 GB of an editor's connection on a
    model this machine will then refuse to run is not a thing to do."""
    ing = make_ingestor(tmp_path, sidecar=FakeSidecar(fits=False, ready=False))

    assert ing._gate() == broll_ingest.STATE_TIER_UNFIT


def test_an_idle_batch_waits_for_the_editor_to_go_away(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, idle=FakeIdle(5))
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")

    assert ing._gate() == broll_ingest.STATE_USER_ACTIVE


def test_a_foreground_batch_ignores_the_idle_and_resolve_gates(tmp_path):
    """Owner review (b): Foreground runs NOW. The free-space, drive and model
    gates still apply -- only these two are skipped."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, idle=FakeIdle(5),
                        resolve_running_fn=lambda: True)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    assert ing._gate() == broll_ingest.STATE_RUNNING


def test_an_idle_batch_stands_down_while_resolve_is_open(tmp_path):
    """TRUE by default here where the proxy generator's equivalent is false:
    this feature wants the VRAM the open timeline is using."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, idle=FakeIdle(9999),
                        resolve_running_fn=lambda: True)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")

    assert ing._gate() == broll_ingest.STATE_RESOLVE_OPEN


def test_a_probe_that_cannot_answer_is_not_away(tmp_path):
    """idle.py's contract: None means "cannot tell", which is NOT away."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, idle=FakeIdle(None))
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")

    assert ing._gate() == broll_ingest.STATE_USER_ACTIVE


def test_the_tray_is_warned_once_when_the_tier_does_not_fit(tmp_path):
    """Owner review (c): a balloon and a menu line naming the VRAM, and the
    SAME sentence in all three places."""
    balloons: list = []
    ing = make_ingestor(tmp_path, sidecar=FakeSidecar(fits=False),
                        notify=lambda text, title=None: balloons.append(text))

    ing._publish_state(broll_ingest.STATE_TIER_UNFIT)
    ing._publish_state(broll_ingest.STATE_TIER_UNFIT)

    assert len(balloons) == 1, "one balloon per transition, not per tick"
    assert "12 GB VRAM" in balloons[0]
    assert ing.status()["warning"] == balloons[0]


# ---------------------------------------------------------------------------
# precedence: indexing beats proxy generation
# ---------------------------------------------------------------------------

def test_a_crunching_batch_blocks_the_proxy_generator(tmp_path):
    """The 2026-08-18 reversal, end to end: the ingestor's blocking_reason
    becomes the generator's gate, and the generator says so in its own
    words."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing._publish_state(broll_ingest.STATE_RUNNING)

    gen = proxy_gen.ProxyGenerator(
        {"local_root": str(tmp_path / "tree"), "proxy_gen_enabled": True},
        tmp_path / "state", blocked_fn=lambda: ing.blocking_reason())

    assert ing.is_working() is True
    assert ing.blocking_reason() == "indexing b-roll first"
    assert gen._gate() == proxy_gen.STATE_BLOCKED
    assert gen.gap()["blocked_reason"] == "indexing b-roll first"


def test_a_bare_true_blocked_fn_still_means_misconfigured(tmp_path):
    """app.py's DEL-3 config gate is the other shape on that seam, and ~2,300
    lines of tests pin it: a bool must not become the new state."""
    gen = proxy_gen.ProxyGenerator(
        {"local_root": str(tmp_path), "proxy_gen_enabled": True},
        tmp_path / "state", blocked_fn=lambda: True)

    assert gen._gate() == proxy_gen.STATE_MISCONFIGURED


def test_an_idle_machine_does_not_block_proxies(tmp_path):
    ing = make_ingestor(tmp_path)
    gen = proxy_gen.ProxyGenerator(
        {"local_root": str(tmp_path / "tree"), "proxy_gen_enabled": True},
        tmp_path / "state", blocked_fn=lambda: ing.blocking_reason())

    assert ing.blocking_reason() is None
    assert gen._gate() != proxy_gen.STATE_BLOCKED


# ---------------------------------------------------------------------------
# run / claim
# ---------------------------------------------------------------------------

def test_run_claims_the_batch_and_takes_the_work_order_from_the_server(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)

    status, body = ing.run("b" * 32, staging, "idle")

    assert status == 202
    assert body["state"] == "claimed"
    claim = [c for c in server.calls if c["url"].endswith("/claim")][0]
    assert claim["url"] == ("http://dash.example/broll/api/fleet/ingest/batches/"
                            + "b" * 32 + "/claim")
    assert claim["body"]["machine"] == "EDIT-1"
    assert claim["headers"]["X-CCSync-Token"] == "t" * 32
    assert claim["headers"]["X-CCSync-Identity"] == "signed"
    # The names and the video id come from the SERVER, never the browser.
    item = ing.status()
    assert item["total"] == 1


def test_every_call_after_the_claim_carries_the_machine_header(tmp_path):
    """docs/API.md §6a: it is what proves the caller is still THIS editor's
    leaseholding machine rather than another of their companions."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing.tick()

    after_claim = [c for c in server.calls if not c["url"].endswith("/claim")]
    assert after_claim
    assert all(c["headers"]["X-CCSync-Machine"] == "EDIT-1" for c in after_claim)


def test_run_refuses_a_tier_this_gpu_cannot_fit_with_the_vram_sentence(tmp_path):
    server = FakeServer()
    balloons: list = []
    ing = make_ingestor(tmp_path, server=server, sidecar=FakeSidecar(fits=False),
                        notify=lambda text, title=None: balloons.append(text))
    staging = stage_one_clip(ing, tmp_path)

    status, body = ing.run("b" * 32, staging, "idle")

    assert status == 503
    assert "12 GB VRAM" in body["message"]
    assert body["reason"] == "tier_unfit"
    assert balloons, "the tray must be told too, not just the page"
    # Nothing is left holding the batch: the lease expires and another of this
    # editor's machines can take it.
    assert ing.status()["batch_uid"] == ""


def test_run_refuses_a_second_batch_while_one_is_in_flight(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")

    status, _body = ing.run("c" * 32, staging, "idle")

    assert status == 409


def test_run_refuses_a_batch_uid_that_is_not_one(tmp_path):
    ing = make_ingestor(tmp_path)

    assert ing.run("../../etc/passwd", "", "idle")[0] == 400


def test_run_needs_somebody_signed_in(tmp_path):
    cfg_ing = make_ingestor(tmp_path)
    cfg_ing.deps._identity_token_fn = lambda: ""

    status, body = cfg_ing.run("b" * 32, "", "idle")

    assert status == 503
    assert "signed in" in body["message"]


def test_a_batch_waiting_for_a_model_says_so(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, sidecar=FakeSidecar(ready=False))
    staging = stage_one_clip(ing, tmp_path)

    status, body = ing.run("b" * 32, staging, "idle")

    assert status == 202
    assert body["state"] == "waiting-for-model"


def test_the_model_is_fetched_on_the_tick_not_at_run(tmp_path):
    """Run must answer the page in one round trip; a 3.9 GB download inside
    it would time out every browser there is."""
    server = FakeServer()
    sidecar = FakeSidecar(ready=False)
    ing = make_ingestor(tmp_path, server=server, sidecar=sidecar)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    assert sidecar.ensured == []

    ing.tick()

    assert sidecar.ensured == ["good"]


# ---------------------------------------------------------------------------
# the crunch, and its checkpoints
# ---------------------------------------------------------------------------

def test_one_clip_goes_through_every_stage_in_order(tmp_path):
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.tick()

    # De-duplicated: the stills sub-stage re-posts  at 40 %, which
    # is a percentage move, not a new stage.
    ordered = [s for i, s in enumerate(server.states())
               if i == 0 or s != server.states()[i - 1]]
    assert ordered[:4] == ["proxying", "framing", "describing", "uploading"]
    result = [c for c in server.calls if c["url"].endswith("/result")][0]
    assert result["body"]["segments"][0]["description"] == "a person talks"
    assert result["body"]["themes"] == ["interview"]
    # The server computes search_norm from these; the geometry is MEASURED
    # off the sheet, never re-derived (BROLL-1/BROLL-2).
    assert result["body"]["sprite_cols"] == 10
    assert result["body"]["duration_s"] == 10.0


def test_the_frames_are_extracted_up_to_the_configured_width(tmp_path):
    """The one place `broll_ingest_max_concurrent_ffmpeg` binds: a clip is 20+
    independent one-frame seeks, each a process spawn, and it is the only
    stage where a second child is free rather than contended."""
    server = FakeServer()
    media = FakeMedia()
    ing = make_ingestor(tmp_path, server=server, media=media,
                        cfg_extra={"broll_ingest_max_concurrent_ffmpeg": 2})
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    # Read BEFORE the tick: the batch finishes inside it, and a finished batch
    # no longer names its staging directory.
    sheets_root = Path(ing._sheets_root())

    ing.tick()

    frames = [c for c in media.calls if c[0] == "frame"]
    assert len(frames) == 3, "one per sampled timestamp, holes and all"
    sheets = sheets_root / "sheets" / "4127" / "frames.json"
    assert json.loads(sheets.read_text())["timestamps"] == [0.0, 4.0, 8.0]


def test_an_interrupted_frame_pass_writes_no_sheet(tmp_path):
    """A partial frames.json would be read next time as a complete one, and
    the clip described from half its frames."""
    server = FakeServer()
    idle = FakeIdle(9999)
    ing = make_ingestor(tmp_path, server=server, idle=idle)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")
    real = ing.media.run_ffmpeg

    def _run(cmd, timeout=None):
        if cmd[0] == "scenes":
            idle.seconds = 1  # the editor came back mid-pass
        return real(cmd, timeout)

    sheets_root = Path(ing._sheets_root())
    ing.media.run_ffmpeg = _run
    ing.tick()

    assert not (sheets_root / "sheets" / "4127" / "frames.json").exists()


def test_the_uploads_are_stills_then_proxy_then_the_original(tmp_path):
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing.tick()

    rels = [job["rel"] for job in queue.jobs]
    assert "posters/4127.jpg" in rels
    assert "sprites/4127.jpg" in rels
    assert "creators/2026-08-18 ingest/Proxy/A001.mp4" in rels
    assert "creators/2026-08-18 ingest/A001.MP4" in rels


def test_a_clip_goes_live_only_after_the_server_has_stat_ed_it(tmp_path):
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.tick()

    uploaded = [c for c in server.calls if c["url"].endswith("/uploaded")]
    assert uploaded and uploaded[0]["body"]["original_uploaded"] is True
    # The last clip going live finishes the batch in the same tick, so the
    # count to assert on is the one the release carried.
    assert server.released()[0]["summary"] == {"done": 1, "failed": 0, "total": 1}


def test_a_409_from_uploaded_retries_the_named_files_not_the_clip(tmp_path):
    """plan §6, "Upload interrupted": the server lists exactly what it cannot
    see, and re-indexing an already-described clip is the thing that must not
    happen."""
    server = FakeServer()
    server.uploaded_status = 409
    server.uploaded_body = {"detail": {"missing": ["posters/4127.jpg"],
                                       "reason": "not_uploaded"}}
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.tick()

    assert ing.status()["done"] == 0
    saved = json.loads((tmp_path / "state" / "broll_ingest.json").read_text())
    item = saved["batch"]["items"][0]
    assert item["described"] is True, "the describe must not be paid for twice"
    assert item["stage"] in ("uploading", "failed"), "and it must not be re-crunched"
    assert item["upload_attempts"] >= 1
    # Only the files the server named are re-sent, not the clip.
    assert [c for c in server.calls if c["url"].endswith("/result")].__len__() == 1


def test_uploads_the_server_never_sees_give_up_rather_than_loop(tmp_path):
    """rclone writes a .partial and renames, so a file the archive cannot stat
    is a transfer that really did not land -- and a fourth identical attempt
    is a batch that never finishes."""
    server = FakeServer()
    server.uploaded_status = 409
    server.uploaded_body = {"detail": {"missing": ["posters/4127.jpg"]}}
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    for _ in range(broll_ingest.MAX_UPLOAD_ATTEMPTS + 1):
        ing.tick()

    assert server.released()[0]["summary"]["failed"] == 1


def test_a_proxy_that_will_not_decode_fails_the_clip_not_the_batch(tmp_path):
    server = FakeServer()

    class Refusing(FakeMedia):
        def run_ffmpeg(self, cmd, timeout=None):
            return (1, "muxer error") if cmd[0] == "proxy" else (0, "")

    ing = make_ingestor(tmp_path, server=server, media=Refusing())
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.tick()

    assert "failed" in server.states()
    assert server.released()[0]["summary"]["failed"] == 1


def test_a_clip_whose_source_vanished_is_failed_with_a_sentence(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    Path(ing._batch["items"][0]["local_path"]).unlink()

    ing.tick()

    failures = [c["body"] for c in server.calls
                if c["url"].endswith("/status") and c["body"]["state"] == "failed"]
    assert failures and "not on this machine" in failures[0]["error"]


def test_the_editor_coming_back_stops_between_stages(tmp_path):
    """plan §6, "User returns mid-clip": the gate is re-run between stages, so
    the cost of coming back is one stage, not one clip."""
    server = FakeServer()
    idle = FakeIdle(9999)
    ing = make_ingestor(tmp_path, server=server, idle=idle)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")

    media = ing.media
    real_run = media.run_ffmpeg

    def _run_then_return(cmd, timeout=None):
        if cmd[0] == "proxy":
            idle.seconds = 1  # the mouse moved
        return real_run(cmd, timeout)

    media.run_ffmpeg = _run_then_return
    ing.tick()

    assert ing._gate() == broll_ingest.STATE_USER_ACTIVE
    assert "describing" not in server.states()
    # And the VRAM goes back to them at once.
    assert ing.sidecar.stopped >= 1


# ---------------------------------------------------------------------------
# the state file: resume, cancel, lease
# ---------------------------------------------------------------------------

def test_every_transition_is_on_disk_before_it_is_believed(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    saved = json.loads((tmp_path / "state" / "broll_ingest.json").read_text())

    assert saved["batch"]["uid"] == "b" * 32
    assert saved["batch"]["items"][0]["archive_stem"] == "A001"
    assert saved["staging"][staging]["items"]["c1"]["hash"] == "cafebabe"


def test_a_companion_killed_mid_batch_resumes_from_the_checkpoint(tmp_path):
    server = FakeServer()
    queue = FakeQueue()
    queue.land = False  # the upload is still in flight when the tray dies
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing.tick()

    # A second orchestrator over the same state dir: the tray restarting.
    revived = make_ingestor(tmp_path, server=FakeServer())

    snap = revived.status()
    assert snap["batch_uid"] == "b" * 32
    saved = revived._batch["items"][0]
    assert saved["stage"] == "uploading", "it resumes at the checkpoint, not at zero"
    assert saved["described"] is True, "and never pays for the describe twice"


def test_a_resumed_batch_whose_files_are_gone_fails_those_items(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")
    Path(ing._batch["items"][0]["local_path"]).unlink()
    ing._save()

    revived = make_ingestor(tmp_path, server=FakeServer())

    assert revived.status()["failed"] == 1


def test_an_unreadable_state_file_starts_clean_rather_than_crashing(tmp_path):
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "broll_ingest.json").write_text("{not json", encoding="utf-8")

    ing = make_ingestor(tmp_path)

    assert ing.status()["batch_uid"] == ""


def test_a_410_stops_everything_quietly(tmp_path):
    """Every way a claim can end arrives as 410 and the answer to all of them
    is the same one: stop. Not an error, and not a retry."""
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    server.lease_lost = True

    ing.tick()

    assert ing.status()["batch_uid"] == ""
    assert queue.stopped is True
    assert ing.sidecar.stopped >= 1


def test_cancel_releases_the_batch_and_keeps_the_staged_files(tmp_path):
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    staged_file = Path(ing._batch["items"][0]["local_path"])

    ing.cancel("cancelled from the tray")

    assert server.released() == [{"state": "cancelled",
                                  "summary": {"reason": "cancelled from the tray"}}]
    assert ing.status()["batch_uid"] == ""
    assert staged_file.is_file(), "an accidental cancel must not lose the drop"


def test_a_dashboard_cancel_arrives_on_the_report_reply(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.note_report_response({"commands": {"broll_ingest": {"cancel": ["b" * 32]}}})

    assert ing.status()["batch_uid"] == ""
    assert server.released()[0]["state"] == "cancelled"


def test_another_machines_cancel_is_not_ours(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.note_report_response({"commands": {"broll_ingest": {"cancel": ["d" * 32]}}})

    assert ing.status()["batch_uid"] == "b" * 32


def test_a_finished_batch_is_released_and_forgotten(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.tick()

    assert server.released()[0]["state"] == "done"
    assert ing.status()["batch_uid"] == ""
    assert ing.sidecar.stopped >= 1, "the VRAM goes back when the batch ends"


# ---------------------------------------------------------------------------
# staging (the loopback's half)
# ---------------------------------------------------------------------------

def test_prepare_refuses_a_file_that_is_not_a_video_per_item(tmp_path):
    """A folder drop with one .txt in it must stage 399 clips, not fail."""
    ing = make_ingestor(tmp_path)

    status, body = ing.prepare({"items": [
        {"local_id": "a", "name": "A001.MP4", "size": 10, "source": "upload"},
        {"local_id": "b", "name": "notes.txt", "size": 10, "source": "upload"},
    ]})

    assert status == 202
    accepted = {i["local_id"]: i["accepted"] for i in body["items"]}
    assert accepted == {"a": True, "b": False}


def test_prepare_offers_an_upload_url_the_page_can_put_to(tmp_path):
    ing = make_ingestor(tmp_path)

    _status, body = ing.prepare({"items": [
        {"local_id": "a", "name": "A001.MP4", "size": 10, "source": "upload"}]})

    url = body["items"][0]["upload_url"]
    assert url == f"/broll/ingest/upload/{body['staging_id']}/a"


def test_prepare_refuses_the_whole_drop_when_the_disk_is_nearly_full(tmp_path,
                                                                    monkeypatch):
    ing = make_ingestor(tmp_path)
    monkeypatch.setattr(broll_ingest.broll_server, "_free_bytes_at",
                        lambda path: 1_000_000_000)

    status, body = ing.prepare({"items": [
        {"local_id": "a", "name": "A001.MP4", "size": 10, "source": "upload"}]})

    assert status == 507
    assert "Free some space" in body["message"]


def test_a_picked_path_is_indexed_where_it_is(tmp_path):
    """The whole point of the picker: a 400-clip card is not copied into
    staging first."""
    card = tmp_path / "card"
    card.mkdir()
    clip = card / "A001.MP4"
    clip.write_bytes(b"data")
    ing = make_ingestor(tmp_path)
    # What /pick would have recorded before the page posted these paths
    # (comp-loopback-6): prepare accepts a local path only where the editor
    # sent the picker.
    ing.note_picked([{"path": str(clip), "name": "A001.MP4", "rel_dir": ""}])

    _status, body = ing.prepare({"items": [
        {"local_id": "a", "name": "A001.MP4", "size": 4, "source": "path",
         "path": str(clip)}]})

    assert body["items"][0]["accepted"] is True
    assert "upload_url" not in body["items"][0]


def test_a_picked_path_that_is_not_there_is_refused(tmp_path):
    ing = make_ingestor(tmp_path)

    _status, body = ing.prepare({"items": [
        {"local_id": "a", "name": "A001.MP4", "size": 4, "source": "path",
         "path": str(tmp_path / "nope.MP4")}]})

    assert body["items"][0]["accepted"] is False


def test_an_upload_slot_is_inside_staging_and_only_there(tmp_path):
    ing = make_ingestor(tmp_path)
    _status, body = ing.prepare({"items": [
        {"local_id": "c1", "name": "A001.MP4", "size": 4, "source": "upload"}]})
    staging_id = body["staging_id"]

    _status, slot = ing.upload_slot(staging_id, "c1")

    assert Path(slot["path"]).parent == Path(ing.staging_dir(staging_id))
    assert Path(slot["staging_root"]) == Path(ing.staging_root())


def test_a_second_upload_of_the_same_clip_is_a_409(tmp_path):
    """Which the page reads as SUCCESS -- it must not re-send 40 GB it has
    already sent."""
    ing = make_ingestor(tmp_path)
    staging_id = stage_one_clip(ing, tmp_path)

    status, body = ing.upload_slot(staging_id, "c1")

    assert status == 409
    assert body["already"] is True


def test_a_staging_id_from_the_wire_cannot_escape(tmp_path):
    ing = make_ingestor(tmp_path)

    assert ing.staging_dir("../../etc") is None
    assert ing.thumb("../../etc", "c1")[0] == 404


def test_progress_carries_the_hash_the_precheck_needs(tmp_path):
    ing = make_ingestor(tmp_path)
    staging_id = stage_one_clip(ing, tmp_path)

    body = ing.progress(staging_id)

    item = body["staging"]["items"][0]
    assert item["hash"] == "cafebabe"
    assert item["state"] == "ready"
    assert item["probe"]["duration_s"] == 10.0


# ---------------------------------------------------------------------------
# what the tray, the reporter and the window read
# ---------------------------------------------------------------------------

def test_the_reporter_section_is_exactly_the_dashboards_fields(tmp_path):
    """BrollIngestIn (dashboard api.py) declares these and pydantic drops the
    rest, so a getter that sent the tray's whole view would be paying for
    fields no column exists for."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    section = ing.report()

    assert set(section) == {
        "active", "batch_uid", "state", "gate", "done", "failed", "total",
        "clip", "percent", "tier", "run_mode", "uploading", "upload_paused",
        "model_download_percent", "warning", "at",
    }
    assert all(not isinstance(v, (dict, list)) for v in section.values())


def test_an_idle_machine_reports_nothing_at_all(tmp_path):
    """An ABSENT section is how a finished batch is spelled: the dashboard
    reads it as "not indexing" and clears the grid's chip."""
    assert make_ingestor(tmp_path).report() == {}


def test_a_vram_refusal_is_reported_even_with_no_batch(tmp_path):
    """The batch the editor asked for is NOT happening, and the only other
    place that says so is their own tray."""
    ing = make_ingestor(tmp_path, sidecar=FakeSidecar(fits=False))
    ing._publish_state(broll_ingest.STATE_TIER_UNFIT)

    assert "12 GB VRAM" in ing.report()["warning"]


def test_status_is_zero_io(tmp_path, monkeypatch):
    """It rides the tray's refresh thread, which on the win32 backend can
    stall the message loop."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    calls = len(server.calls)

    monkeypatch.setattr(broll_ingest.os.path, "isfile", _boom)
    ing.status()

    assert len(server.calls) == calls, "status() must not talk to the dashboard"


def _boom(*args, **kwargs):
    raise AssertionError("status() must do no I/O")


def test_the_keep_awake_guard_holds_while_a_batch_crunches(tmp_path):
    """A batch only runs BECAUSE the editor walked away, which is exactly when
    the idle timer would sleep the machine on top of it."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing._publish_state(broll_ingest.STATE_RUNNING)

    assert "still indexing b-roll" in ing.block_reason()
    assert make_ingestor(tmp_path).block_reason() is None


def test_the_progress_model_names_the_clip_the_stage_and_the_buttons(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing._set_current("A001.MP4", "describing", 70)
    ing._publish_state(broll_ingest.STATE_RUNNING)

    model = ing.progress_model()

    assert model.title == "INDEXING B-ROLL"
    assert model.item_line() == "A001.MP4 - describing - 70%"
    assert model.overall_line() == "0 of 1 clip"
    assert "cancel" in model.actions and "pause" in model.actions


def test_the_window_offers_start_now_only_while_something_is_waiting(tmp_path):
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, idle=FakeIdle(5))
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "idle")
    ing._publish_state(ing._gate())

    model = ing.progress_model()

    assert "start_now" in model.actions
    assert model.note == "waiting until you're away from the keyboard"


def test_the_model_download_is_the_top_line_while_it_runs(tmp_path):
    """Until a 3.9 GB model lands nothing else can start, and a still per-clip
    bar reads as a hang."""
    server = FakeServer()
    sidecar = FakeSidecar(ready=False)
    sidecar.downloading = {"name": "Qwen3-VL 4B", "written": 1, "total": 2,
                           "percent": 43}
    ing = make_ingestor(tmp_path, server=server, sidecar=sidecar)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    model = ing.progress_model()

    assert model.headline_line() == "Downloading Qwen3-VL 4B: 43%"


def test_the_model_download_headline_quotes_the_speed_and_the_time_left(tmp_path):
    """A multi-GB fetch with only a percentage on it is indistinguishable from
    a hang (2026-08-18, BROLL-ING-4): the parallel fetcher measures a rate,
    and this is where an editor reads it."""
    sidecar = FakeSidecar(ready=False)
    sidecar.downloading = {"name": "Qwen3-VL 4B (Good)", "written": 61, "total": 100,
                           "percent": 61, "rate_bytes_per_s": 38e6,
                           "eta_seconds": 95}
    ing = make_ingestor(tmp_path, server=FakeServer(), sidecar=sidecar)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    model = ing.progress_model()

    assert model.headline_line() == (
        "Downloading Qwen3-VL 4B (Good): 61% at 36.2 MB/s, about 1 min left")
    # The bar still gets its number; the line just does not say it twice.
    assert model.headline_percent == 61
    snap = ing.status()
    assert snap["model_download_rate"] == 38e6
    assert snap["model_download_eta"] == 95
    assert ing.progress(staging)["batch"]["model"]["rate_bytes_per_s"] == 38e6
    assert ing.progress(staging)["batch"]["model"]["eta_seconds"] == 95


def test_a_model_download_with_no_rate_yet_is_still_a_headline(tmp_path):
    """The first seconds have no rate to quote. The line must not say "at
    0 MB/s" or vanish -- it is the reason nothing else is moving."""
    sidecar = FakeSidecar(ready=False)
    sidecar.downloading = {"name": "Qwen3-VL 4B", "written": 0, "total": 100,
                           "percent": 0, "rate_bytes_per_s": None,
                           "eta_seconds": None}
    ing = make_ingestor(tmp_path, server=FakeServer(), sidecar=sidecar)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    assert ing.progress_model().headline_line() == "Downloading Qwen3-VL 4B: 0%"


def test_the_window_is_offered_once_per_batch_and_only_when_working(tmp_path):
    """A window that reappeared every fifteen seconds is the thing an editor
    turns the feature off to escape -- and an orchestrator that could open one
    on its own is one a test can leave a real Tk window behind with (seen
    live 2026-08-18)."""
    server = FakeServer()
    queue = FakeQueue()
    queue.land = False  # keep the batch alive across the ticks
    shown: list = []
    ing = make_ingestor(tmp_path, server=server, queue=queue,
                        show_window=lambda: shown.append(1))
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.tick()
    ing.tick()

    assert shown == [1]


def test_an_orchestrator_with_no_window_seam_opens_none(tmp_path):
    """Which is what every test gets, and why the suite cannot leak one."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    ing.tick()  # no exception, and nothing on anybody's desktop


def test_the_control_route_and_the_tray_drive_the_same_object(tmp_path):
    ing = make_ingestor(tmp_path)

    assert ing.control("pause")[0] == 200
    assert ing.status()["paused"] is True
    assert ing.control("resume")[0] == 200
    assert ing.status()["paused"] is False
    assert ing.control("pause_upload")[0] == 200
    assert ing.status()["upload_paused"] is True
    assert ing.control("do-something-else")[0] == 400


def test_pausing_uploads_leaves_the_crunching_alone(tmp_path):
    """plan §6, "Fleet halt": uploads pause, the local work continues."""
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, queue=queue)

    ing.pause_upload(True)

    assert queue._paused is True
    assert ing._gate() != broll_ingest.STATE_PAUSED


# ---------------------------------------------------------------------------
# the ETA (popup.EmaEta)
# ---------------------------------------------------------------------------

def test_the_eta_says_estimating_until_two_clips_are_done():
    """A number derived from one clip is a number that will be wrong by an
    order of magnitude, and the first estimate an editor sees is the one they
    remember."""
    eta = popup.EmaEta()

    assert eta.eta_seconds(10) is None
    eta.observe(30)
    assert eta.eta_seconds(10) is None
    eta.observe(30)
    assert eta.eta_seconds(10) == pytest.approx(300)


def test_the_eta_follows_a_change_rather_than_averaging_it_away():
    """40 four-second cutaways then a three-minute interview: a cumulative
    mean would still say "seconds left" a quarter of an hour later."""
    eta = popup.EmaEta(alpha=0.4)
    for _ in range(10):
        eta.observe(10)
    before = eta.per_item_seconds()
    for _ in range(4):
        eta.observe(100)

    assert before == pytest.approx(10, abs=0.5)
    assert eta.per_item_seconds() > 50


def test_the_eta_ignores_nonsense_samples():
    eta = popup.EmaEta()
    eta.observe(None)
    eta.observe(-5)
    eta.observe("soon")

    assert eta.per_item_seconds() is None


def test_the_overall_line_counts_failures_separately():
    model = popup.ProgressModel(done=12, total=40, failed=1)

    assert model.overall_line() == "12 of 40 clips · 1 failed"


def test_the_window_says_estimating_before_it_says_a_number():
    assert popup.ProgressModel(total=40).eta_line() == "estimating…"
    assert popup.ProgressModel(total=40, eta_seconds=720).eta_line() == "~12 min left"
    assert popup.ProgressModel(total=40, finished=True).eta_line() == ""


# ---------------------------------------------------------------------------
# the loopback set (comp-loopback-1..4, 2026-08-21): after a cancel, a restart
# mid-batch, a failed rclone or a refused /result, THIS MACHINE MUST STILL BE
# ABLE TO TAKE THE NEXT DROP. All four ended with the batch held, the
# heartbeat keeping the lease alive and every later drop answered 409.
# ---------------------------------------------------------------------------

def test_a_cancelled_batch_does_not_park_every_later_one(tmp_path):
    """comp-loopback-1: `stop_all` latches an UploadQueue shut for ever and
    the orchestrator outlives the batch, so keeping the object meant the FIRST
    cancel of a tray session (tray, page, dashboard command, expired lease)
    left every later drop at 'uploading' 90% with no rclone ever spawned."""
    server = FakeServer()
    queues = [FakeQueue()]
    ing = make_ingestor(tmp_path, server=server, queue=queues[0])

    def _fresh():
        queues.append(FakeQueue())
        return queues[-1]

    ing._new_queue = _fresh
    first = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, first, "foreground")
    ing.cancel("cancelled from the tray")

    second = stage_one_clip(ing, tmp_path)
    status, _body = ing.run("b" * 32, second, "foreground")
    ing.tick()

    assert status == 202, "the machine has to be free for the next batch"
    assert len(queues) == 2, "the cancelled queue is dead; the next batch needs a new one"
    assert queues[1].dead == [], "and nothing may be handed to a stopped queue"
    assert server.released()[-1]["state"] == "done"
    assert ing.status()["batch_uid"] == "", "the second batch finishes and is let go"


def test_a_restarted_companion_re_claims_and_re_queues_its_uploads(tmp_path):
    """comp-loopback-2: `_resume` set `needs_claim` and nothing read it. A tray
    restarted mid-upload never re-claimed, never heartbeated (so the server's
    300 s lease lapsed under it) and never put the item's artifacts back on
    the new, empty queue -- the batch was stuck for ever and every new drop
    got the 409."""
    server = FakeServer()
    queue = FakeQueue()
    queue.land = False  # the upload is still in flight when the tray dies
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing.tick()
    assert ing._batch["items"][0]["stage"] == "uploading"

    # The tray restarts over the same state dir.
    revived_server = FakeServer()
    revived_queue = FakeQueue()
    revived_queue.land = False
    revived = make_ingestor(tmp_path, server=revived_server, queue=revived_queue)
    revived.tick()

    claims = [c for c in revived_server.calls if c["url"].endswith("/claim")]
    assert claims, "the lease has to be taken back, or it lapses under us"
    assert claims[0]["body"]["machine"] == "EDIT-1"
    assert revived._batch.get("needs_claim") is None
    assert (revived._heartbeat_thread is not None
            and revived._heartbeat_thread.is_alive()), "and heartbeated after it"
    assert "posters/4127.jpg" in revived_queue.enqueued, (
        "the artifacts went back on the queue that actually exists now")


def test_a_restart_the_server_will_not_hand_the_batch_back_frees_the_machine(tmp_path):
    """The other half of comp-loopback-2: the tray was down for longer than
    the 300 s lease, so the batch really is gone. Nothing on an item parked at
    'uploading' ever calls the server, so without the re-claim the 410 was
    never even asked for and the machine held the batch (and the 409) for
    ever. A 410 to the re-claim is an ordinary answer, and the ordinary answer
    is to let go."""
    server = FakeServer()
    queue = FakeQueue()
    queue.land = False
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    ing.tick()
    assert ing._batch["items"][0]["stage"] == "uploading"

    revived_server = FakeServer()
    revived_server.claim_status = 410
    revived_server.lease_lost = True
    revived = make_ingestor(tmp_path, server=revived_server,
                            queue=FakeQueue())
    revived.tick()

    assert revived.status()["batch_uid"] == ""
    assert revived.run("c" * 32, "", "foreground")[0] != 409


def test_an_upload_rclone_could_not_send_is_retried_then_failed(tmp_path):
    """comp-loopback-3: a non-zero rclone put the rel in `failures()`, the pump
    copied the text onto the item and `continue`d -- for ever. The item never
    left 'uploading', so the batch was never released and the machine never
    took another drop."""
    server = FakeServer()
    queue = FakeQueue()
    queue.fail_rels = {"posters/4127.jpg"}
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")

    for _ in range(broll_ingest.MAX_UPLOAD_ATTEMPTS + 2):
        ing.tick()

    assert server.released(), "the batch has to end, one way or the other"
    assert server.released()[0]["summary"]["failed"] == 1
    poster = queue.enqueued.count("posters/4127.jpg")
    original = queue.enqueued.count("creators/2026-08-18 ingest/A001.MP4")
    assert poster > 1, "the dropped link deserved a retry"
    assert poster > original, (
        "and the retry is of the FILE that failed - re-sending a 40 GB "
        "original because a 100 KB poster did not land is an editor's evening")
    assert ing.status()["batch_uid"] == ""


def test_a_result_the_archive_refuses_is_never_uploaded(tmp_path):
    """comp-loopback-4: the refusal used to be a log line. The clip was
    uploaded anyway and `mark_uploaded` does not check that any segments
    exist, so the archive got a live clip with no description that no search
    could find -- and `described` was already True, so it was never
    re-described either."""
    server = FakeServer()
    server.result_status = 400
    server.result_body = {"detail": "segments must not be empty"}
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    # The batch is released and forgotten inside the tick, so the item dict
    # (mutated in place) is what there is left to read.
    item = ing._batch["items"][0]

    ing.tick()

    assert queue.enqueued == [], "an undescribed clip must not reach the archive"
    assert item["described"] is False, "so a retry re-runs the model"
    assert item["stage"] == "failed"
    assert "segments must not be empty" in item["error"]
    assert item["attempts"] == broll_ingest.MAX_ITEM_ATTEMPTS, (
        "the clip is retried as a clip, not carried on with as an indexed one")
    assert server.released()[0]["summary"]["failed"] == 1, (
        "and the batch ends, so this machine can take the next drop")


# ---------------------------------------------------------------------------
# the picked-paths allow-list (comp-loopback-6, 2026-08-21)
# ---------------------------------------------------------------------------

def test_a_path_the_editor_never_picked_is_refused(tmp_path):
    """/pick is THE only route that learns a local path (plan 4). That was a
    docstring and not a check: prepare took `path` off the JSON body, so a bug
    in the page could have had this machine index, describe and rclone any
    readable video into the customer's shared archive."""
    private = tmp_path / "private"
    private.mkdir()
    clip = private / "family.mp4"
    clip.write_bytes(b"data")
    ing = make_ingestor(tmp_path)

    _status, body = ing.prepare({"items": [
        {"local_id": "a", "name": "family.mp4", "size": 4, "source": "path",
         "path": str(clip)}]})

    assert body["items"][0]["accepted"] is False
    assert "not chosen on this machine" in body["items"][0]["reason"]


def test_a_folder_pick_allows_the_whole_folder_that_was_picked(tmp_path):
    """The picker walks sub-folders and reports each clip's `rel_dir` below
    the folder the editor chose; the allow-list climbs back up to that one
    root, so a 400-clip card is one entry and not forty."""
    card = tmp_path / "card"
    (card / "DCIM" / "100MEDIA").mkdir(parents=True)
    first = card / "DCIM" / "100MEDIA" / "A001.MP4"
    second = card / "DCIM" / "100MEDIA" / "A002.MP4"
    first.write_bytes(b"data")
    second.write_bytes(b"data")
    ing = make_ingestor(tmp_path)
    ing.note_picked([{"path": str(first), "name": "A001.MP4",
                      "rel_dir": "DCIM/100MEDIA"}])

    _status, body = ing.prepare({"items": [
        {"local_id": "a", "name": "A001.MP4", "size": 4, "source": "path",
         "path": str(first)},
        {"local_id": "b", "name": "A002.MP4", "size": 4, "source": "path",
         "path": str(second)}]})

    assert [entry["accepted"] for entry in body["items"]] == [True, True]


def test_the_picked_folders_survive_a_tray_restart(tmp_path):
    """The pick and the prepare are two requests: a tray that restarted
    between them must not refuse the drop the editor is halfway through."""
    card = tmp_path / "card"
    card.mkdir()
    clip = card / "A001.MP4"
    clip.write_bytes(b"data")
    ing = make_ingestor(tmp_path)
    ing.note_picked([{"path": str(clip), "name": "A001.MP4", "rel_dir": ""}])

    revived = make_ingestor(tmp_path)
    _status, body = revived.prepare({"items": [
        {"local_id": "a", "name": "A001.MP4", "size": 4, "source": "path",
         "path": str(clip)}]})

    assert body["items"][0]["accepted"] is True


# -- MEDIA-2 / MEDIA-3 (resilience sweep 2026-08-28) -------------------------


class FakeChild:
    """A Popen the runner publishes and the orchestrator has to be able to
    end."""

    def __init__(self):
        self.terminated = False
        self.killed = False
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False

    def wait(self, timeout=None):
        return 0


def test_the_media_runner_publishes_its_child_and_stop_kills_it(tmp_path):
    """MEDIA-2: `self._child` was never assigned anywhere in the package, so
    stop()'s documented kill was a no-op and an ffmpeg outlived the tray."""
    child = FakeChild()

    def runner(cmd, child_sink=None):
        child_sink(child)
        return 0, ""

    ingestor = make_ingestor(tmp_path, run_media_fn=runner)
    assert ingestor._run_media(["proxy", "x"]) == (0, "")
    # Published and taken back by the runner itself; publish one by hand to
    # stand in for a child that is still running when stop() lands.
    ingestor._publish_child(child)
    ingestor.stop()
    assert child.terminated is True


def test_a_child_published_after_stop_is_killed_at_once(tmp_path):
    """The spawn and the shutdown are on different threads: a child born in
    the window between them is exactly how an orphan outlives the tray."""
    ingestor = make_ingestor(tmp_path)
    ingestor.stop()
    child = FakeChild()
    ingestor._publish_child(child)
    assert child.terminated is True


def test_a_runner_without_the_keyword_is_still_called(tmp_path):
    """Every existing `run_media_fn` double takes one argument."""
    seen = []

    def runner(cmd):
        seen.append(cmd)
        return 0, ""

    ingestor = make_ingestor(tmp_path, run_media_fn=runner)
    assert ingestor._run_media(["poster"]) == (0, "")
    assert seen == [["poster"]]


def _finished_staging(ingestor, tmp_path, *, ended_at, name="A001.MP4"):
    status, body = ingestor.prepare({"items": [
        {"local_id": "c1", "name": name, "size": 4, "source": "upload"}]})
    assert status == 202
    sid = body["staging_id"]
    directory = ingestor.staging_dir(sid)
    (directory / "big.bin").write_bytes(b"x" * 2048)
    ingestor._staging[sid]["ended_at"] = ended_at
    return sid, directory


def test_finished_staging_older_than_the_retention_is_deleted(tmp_path):
    """MEDIA-3: nothing anywhere deleted a staging directory, and the plan
    has promised seven days since the feature shipped."""
    ingestor = make_ingestor(tmp_path)
    sid, directory = _finished_staging(ingestor, tmp_path,
                                       ended_at="2020-01-01T00:00:00Z")
    result = ingestor.prune_staging()
    assert result["removed"] == 1
    assert result["bytes"] >= 2048
    assert not directory.exists()
    assert sid not in ingestor._staging


def test_a_recent_batch_and_an_unfinished_drop_are_left_alone(tmp_path):
    ingestor = make_ingestor(tmp_path)
    sid, directory = _finished_staging(ingestor, tmp_path, ended_at=_iso_now_utc())
    assert ingestor.prune_staging()["removed"] == 0
    assert directory.exists()

    # A drop that has been staged but never run has no ended_at at all.
    del ingestor._staging[sid]["ended_at"]
    ingestor._staging[sid]["at"] = _iso_now_utc()
    assert ingestor.prune_staging()["removed"] == 0
    assert directory.exists()


def test_the_running_batch_staging_is_never_a_candidate(tmp_path):
    ingestor = make_ingestor(tmp_path)
    sid, directory = _finished_staging(ingestor, tmp_path,
                                       ended_at="2020-01-01T00:00:00Z")
    ingestor._batch = {"uid": "b1", "staging_id": sid}
    assert ingestor.prune_staging()["removed"] == 0
    assert directory.exists()


def test_clear_finished_staging_takes_everything_now(tmp_path):
    """max_age_days=0 is the tray's CLEAR FINISHED STAGING button."""
    ingestor = make_ingestor(tmp_path)
    _sid, directory = _finished_staging(ingestor, tmp_path, ended_at=_iso_now_utc())
    assert ingestor.prune_staging(max_age_days=0)["removed"] == 1
    assert not directory.exists()


def test_staging_report_counts_the_bytes_the_space_refusal_blames(tmp_path):
    ingestor = make_ingestor(tmp_path)
    _finished_staging(ingestor, tmp_path, ended_at=_iso_now_utc())
    report = ingestor.staging_report()
    assert report["batches"] == 1
    assert report["bytes"] >= 2048
    assert report["oldest_at"]


def _iso_now_utc():
    import time as _time

    return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())


def test_a_batch_that_ends_starts_the_retention_clock(tmp_path):
    ingestor = make_ingestor(tmp_path)
    status, body = ingestor.prepare({"items": [
        {"local_id": "c1", "name": "A.MP4", "size": 4, "source": "upload"}]})
    sid = body["staging_id"]
    ingestor._note_staging_ended({"staging_id": sid})
    assert ingestor._staging[sid]["ended_at"]


# -- UX-17: the whole drop, before the first byte ---------------------------


def test_a_drop_bigger_than_the_free_space_is_refused_whole(tmp_path, monkeypatch):
    """The per-file 507 fired mid-batch, once part of a 200 GB shoot was
    already on the disk."""
    from ccsync_companion import broll_server as _bs

    monkeypatch.setattr(_bs, "_free_bytes_at", lambda _d: 30 * 10 ** 9)
    ingestor = make_ingestor(tmp_path)
    status, body = ingestor.prepare({"items": [
        {"local_id": f"c{i}", "name": f"A{i}.MP4", "size": 5 * 10 ** 9,
         "source": "upload"} for i in range(10)]})
    assert status == 507
    assert "50.0 GB" in body["message"]
    assert not body["ok"]


def test_a_drop_that_fits_is_still_accepted(tmp_path, monkeypatch):
    from ccsync_companion import broll_server as _bs

    monkeypatch.setattr(_bs, "_free_bytes_at", lambda _d: 100 * 10 ** 9)
    ingestor = make_ingestor(tmp_path)
    status, _body = ingestor.prepare({"items": [
        {"local_id": "c1", "name": "A.MP4", "size": 5 * 10 ** 9,
         "source": "upload"}]})
    assert status == 202


# ---------------------------------------------------------------------------
# The checkpoint survives the threads that write it
# (bug-hunt-2026-09-03 comp-broll-music-1)
# ---------------------------------------------------------------------------


def test_a_checkpoint_is_not_lost_to_a_thread_adding_a_key(tmp_path, caplog):
    """_save() used to put LIVE references to _batch and _staging in the
    snapshot and serialise them after releasing the lock. json.dumps with
    indent= is the pure-Python encoder, which yields the GIL mid-iteration, so
    the tick thread doing item["described"] = True or outputs["proxy"] = ...
    while the heartbeat thread saved raised "dictionary changed size during
    iteration"; the broad except swallowed it, os.replace never ran, and the
    state file silently stopped being written at exactly the moment there was
    most to record. Three threads reach _save, and the docstring promises a
    checkpoint at EVERY transition.
    """
    import threading

    ingestor = make_ingestor(tmp_path)
    ingestor._batch = {
        "batch_id": "b1",
        "items": [{"local_id": f"c{i}", "name": f"A{i}.MP4", "outputs": {},
                   "uploads": {}} for i in range(300)],
    }
    ingestor._staging = {f"s{i}": {"items": {}, "ended_at": None}
                         for i in range(20)}

    stop = threading.Event()

    def _crunch_like():
        """What _crunch_item does, at speed: keys _item_from_manifest did not
        pre-create, added with no lock held. Bounded so the state file cannot
        grow without limit while the saves run."""
        n = 0
        while not stop.is_set():
            n += 1
            for item in ingestor._batch["items"]:
                item["described"] = True
                if len(item["outputs"]) > 200:
                    item["outputs"].clear()
                    item["uploads"].clear()
                item["outputs"][f"stage{n}"] = n
                item["uploads"][f"u{n}"] = n
            for entry in ingestor._staging.values():
                if len(entry["items"]) > 200:
                    entry["items"].clear()
                entry["items"][f"i{n}"] = n

    mutator = threading.Thread(target=_crunch_like, daemon=True)
    with caplog.at_level("WARNING"):
        mutator.start()
        try:
            # 40 saves against a batch this size is where the old shape
            # failed about thirty times out of forty (measured); one lost
            # write is the defect.
            for _ in range(40):
                ingestor._save()
        finally:
            stop.set()
            mutator.join(timeout=5)

    assert not [r for r in caplog.records if "could not write" in r.getMessage()]
    saved = json.loads(ingestor.state_path.read_text(encoding="utf-8"))
    assert saved["batch"]["batch_id"] == "b1"
    assert len(saved["batch"]["items"]) == 300


# ---------------------------------------------------------------------------
# BROLL-5 / CMEDIA-10: a failed clip can be retried, and says why it failed
# ---------------------------------------------------------------------------


def _staged(ing, name="clip.mov"):
    status, answer = ing.prepare({"items": [{"local_id": "l1", "name": name,
                                             "source": "upload", "size": 4096}]})
    assert status == 202, answer
    return answer["staging_id"]


def test_a_failed_upload_can_be_re_queued(tmp_path):
    """BROLL-5: `item.error` used to be permanent for the life of the page --
    the pump skips a clip that has one, so a hotel-wifi blip at 95% of a 4 GB
    file failed one clip of a 200-clip drop for good."""
    ing = make_ingestor(tmp_path)
    staging_id = _staged(ing)
    entry = ing._staging[staging_id]["items"]["l1"]
    entry.update(state=broll_ingest.STAGED_FAILED, error="upload failed")
    partial = Path(entry["path"] + ".partial")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"half a body")

    status, answer = ing.retry({"staging_id": staging_id, "items": ["l1"]})

    assert (status, answer) == (200, {"ok": True, "retried": 1})
    assert entry["state"] == broll_ingest.STAGED_WAITING
    assert entry["error"] == ""
    # The half-body goes with it: _stream_body_to renames only on a complete
    # body, so a stale .partial is the only litter there can be.
    assert not partial.exists()


def test_retrying_something_that_is_not_failed_is_a_no_op_not_an_error(tmp_path):
    """Two clicks must mean what one click meant."""
    ing = make_ingestor(tmp_path)
    staging_id = _staged(ing)

    assert ing.retry({"staging_id": staging_id}) == (200, {"ok": True, "retried": 0})
    assert ing.retry({}) == (200, {"ok": True, "retried": 0})
    assert ing.retry({"staging_id": "../../etc"})[0] == 400


def test_the_progress_body_names_the_failures_not_just_a_count(tmp_path):
    """CMEDIA-10: the reason is on the item and reached nobody -- the tray said
    "3 clip(s) could not be indexed. See the log"."""
    ing = make_ingestor(tmp_path)
    ing._batch = {"uid": "b" * 32, "state": "running", "items": [
        {"uid": "i1", "name": "one.mov", "stage": broll_ingest.ITEM_FAILED,
         "error": "the source file is not on this machine any more"},
        {"uid": "i2", "name": "two.mov", "stage": broll_ingest.ITEM_LIVE},
    ]}

    body = ing.progress()

    assert body["failed_items"] == [
        {"name": "one.mov",
         "error": "the source file is not on this machine any more"}]
    assert body["batch"]["failed_items"] == body["failed_items"]
    assert ing.status()["failed_items"] == body["failed_items"]
