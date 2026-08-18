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
    test says otherwise."""

    def __init__(self):
        self.jobs: list = []
        self.failed: list = []
        self._paused = False
        self.stopped = False
        self.land = True

    def enqueue(self, local_path, remote_rel, kind, item_uid="", size_bytes=None):
        self.jobs.append({"rel": remote_rel, "kind": kind, "item_uid": item_uid,
                          "size": size_bytes, "local": str(local_path)})

    def uploaded(self):
        return list(self.jobs) if self.land else []

    def failures(self):
        return list(self.failed)

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
            return 200, {"ok": True}
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

    assert model.headline_line() == "Downloading Qwen3-VL 4B - 43%"


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
