"""The music ingest orchestrator (music_ingest.py) and its loopback routes.

docs/MUSIC_INGEST_PLAN.md, 2026-08-18. Everything here runs with no ffmpeg, no
model, no dashboard and no rclone: the seams that made that true for b-roll are
the ones music reuses, which is most of what this file is checking.

Four properties, and they are the ones a bug in would cost an editor a library:

  * **the b-roll path is the same code path.** The refactor that made the
    orchestrator kind-agnostic must not have forked it -- b-roll's 63 tests
    passing is one half of that, and the identity assertions here are the
    other;
  * **the pipeline** -- probe, transcode, embed, result, upload -- and the
    ONE body that differs from b-roll's (`uploaded` takes a size);
  * **the destination comes from the server**, never from this side: the
    filename is allocated at `result` and nothing may be uploaded before it;
  * **the fallback**: a machine that cannot embed does not lose the track.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pytest

from ccsync_companion import (broll_ingest, broll_server, ingest_kinds,
                              music_clap_sidecar, music_ingest)


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

class FakeSidecar:
    """music_clap_sidecar's surface: a machine with the model already cached."""

    SidecarError = music_clap_sidecar.SidecarError

    def __init__(self, ready=True, refusal="", dim=512):
        self._ready = ready
        self._refusal = refusal
        self.dim = dim
        self.ensured = 0
        self.stopped = 0
        self.embedded: list = []
        self.downloading = None
        self.raise_on_embed: Exception | None = None

    # -- the gate ----------------------------------------------------------
    def refusal(self, cfg=None):
        return self._refusal

    def status(self):
        return {"ready": self._ready, "runtime_ready": True, "providers": [],
                "downloading": self.downloading, "last_error": ""}

    def ensure(self, cfg=None, progress_cb=None, stop_event=None, site=None, key=""):
        self.ensured += 1
        self._ready = True
        return True, "the music indexing model is ready"

    def stop_server(self):
        self.stopped += 1

    # -- the work ----------------------------------------------------------
    def probe(self, ffmpeg, path):
        return {"duration": 12.0, "samplerate": 48000, "channels": 2,
                "codec": "pcm_s16le"}

    def content_hash(self, path):
        return "b1a5e" + Path(path).stem[:3]

    def transcode_to_mp3(self, ffmpeg, src, dest_dir, child_sink=None):
        dest = Path(dest_dir) / (Path(src).stem + ".mp3")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mp3" * 100)
        return dest

    def embed_file(self, path, ffmpeg_path="ffmpeg", key="", stop_event=None,
                   child_sink=None):
        if self.raise_on_embed is not None:
            raise self.raise_on_embed
        self.embedded.append(str(path))
        vector = np.zeros(self.dim, dtype=np.float32)
        vector[0] = 1.0
        return {
            "embedding": vector, "dim": self.dim, "duration": 185.25,
            "n_windows": 2, "peaks": bytes(range(256)) * 2,
            "windows": [{"idx": 0, "t0": 0.0, "t1": 10.0, "vector": vector},
                        {"idx": 1, "t0": 10.0, "t1": 20.0, "vector": vector}],
            "model": "laion/larger_clap_music_and_speech@onnx1",
        }

    def model_id(self, key=""):
        return "laion/larger_clap_music_and_speech@onnx1"


class FakeQueue:
    """broll_upload.UploadQueue's surface. Everything lands at once unless a
    test says otherwise.

    `stop_all` is modelled as the ONE-WAY latch it really is (2026-08-21):
    anything enqueued after it goes nowhere, which is what a queue reused
    across a cancel would have done to the next album.
    """

    def __init__(self):
        self.jobs: list = []
        self.failed: list = []
        self.stopped = False
        self.land = True
        self._paused = False
        self.dead: list = []

    def enqueue(self, local_path, remote_rel, kind, item_uid="", size_bytes=None):
        job = {"rel": remote_rel, "kind": kind, "item_uid": item_uid,
               "size": size_bytes, "local": str(local_path)}
        if self.stopped:
            self.dead.append(job)
            return
        self.jobs.append(job)

    def uploaded(self):
        return list(self.jobs) if self.land else []

    def failures(self):
        return list(self.failed)

    def progress(self):
        return {"queued": 0 if self.land else len(self.jobs), "active": None,
                "done": len(self.jobs), "failed": 0, "paused": self._paused}

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop_all(self):
        self.stopped = True


class FakeServer:
    """The music fleet routes, as a request_fn (docs/API.md §6b)."""

    def __init__(self, items=None):
        self.calls: list = []
        self.claim_status = 200
        self.result_status = 200
        self.result_body = {"ok": True, "state": "indexed", "track_id": 91,
                            "rel_path": "Slow Burn (2).mp3"}
        self.uploaded_status = 200
        self.lease_lost = False
        self.items = items if items is not None else [{
            "uid": "i" * 32, "ord": 0, "orig_name": "Slow Burn.ogg",
            "size_bytes": 4096, "content_hash": None, "duration_s": 185.0,
            "state": "pending", "duplicate_of": None, "source": "upload",
            "dest_name": None, "track_id": None, "attempts": 0,
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
            return 200, {
                "batch": {"uid": "b" * 32, "share": "music", "state": "claimed",
                          "upload_paused": False},
                "settings": {"run_mode": "idle"},
                "lease_seconds": 300, "heartbeat_seconds": 30,
                "library_remote_rel": "Assets/Music",
                "audio_exts": [".wav", ".mp3", ".ogg"],
                "transcode_exts": [".ogg"],
                "items": self.items,
            }
        if url.endswith("/heartbeat"):
            return 200, {"ok": True, "cancel_requested": False,
                         "upload_paused": False}
        if url.endswith("/result"):
            return self.result_status, dict(self.result_body)
        if url.endswith("/uploaded"):
            return self.uploaded_status, {"ok": True, "live": True}
        return 200, {"ok": True}

    def bodies(self, suffix):
        return [c["body"] for c in self.calls if c["url"].endswith(suffix)]

    def states(self):
        return [c["body"]["state"] for c in self.calls
                if c["url"].endswith("/status")]


class FakeIdle:
    def __init__(self, seconds=9999):
        self.seconds = seconds

    def seconds_idle(self):
        return self.seconds


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    """prepare() measures the REAL free space of the staging root, which is
    pytest's tmp dir on the host's system drive: the day that drive dropped
    under the 20 GB floor, test_only_audio_may_be_staged 507'd for reasons
    that had nothing to do with audio (2026-08-18). Same fix test_proxy_gen
    took: the disk is faked, the floor stays real."""
    from ccsync_companion import broll_server as _bs

    monkeypatch.setattr(_bs, "_free_bytes_at", lambda _d: 10 ** 12)


def make_ingestor(tmp_path, *, server=None, sidecar=None, queue=None, idle=None,
                  cfg_extra=None, **kwargs):
    cfg = {
        "local_root": str(tmp_path / "tree"),
        "dashboard_url": "http://dash.example",
        "dashboard_token": "t" * 32,
        "music_ingest_staging_dir": str(tmp_path / "staging"),
        "music_ingest_idle_seconds": 300,
    }
    cfg.update(cfg_extra or {})
    (tmp_path / "tree").mkdir(exist_ok=True)
    deps = broll_ingest.IngestDeps(
        cfg, editor_fn=lambda: "alex", identity_token_fn=lambda: "signed",
        request_fn=server if server is not None else FakeServer(),
        machine_name="EDIT-1", kind=ingest_kinds.MUSIC_KIND)
    options = {
        "sidecar": sidecar if sidecar is not None else FakeSidecar(),
        "uploader": queue if queue is not None else FakeQueue(),
        "idle_probe": idle if idle is not None else FakeIdle(),
        "available_fn": lambda path: (True, "ok"),
        "hash_fn": lambda path: "b1a5e" + Path(path).stem[:3],
    }
    options.update(kwargs)
    return music_ingest.MusicIngestor(cfg, tmp_path / "state", deps=deps, **options)


def stage_one(ing, tmp_path, name="Slow Burn.ogg"):
    """Put a file where a claimed item will find it, the way `prepare` would."""
    status, answer = ing.prepare({"items": [{"local_id": "l1", "name": name,
                                             "source": "upload", "size": 4096}]})
    assert status == 202, answer
    staging_id = answer["staging_id"]
    path = Path(ing.staging_dir(staging_id)) / f"l1{Path(name).suffix}"
    path.write_bytes(b"audio" * 800)
    ing._staging[staging_id]["items"]["l1"]["path"] = str(path)
    return staging_id


# ---------------------------------------------------------------------------
# the kind, and the b-roll path it must not have forked
# ---------------------------------------------------------------------------

def test_the_two_kinds_share_the_orchestrator(tmp_path):
    """The refactor was supposed to parameterise `BrollIngestor`, not copy it.
    If these ever stop being the same function objects, a fix to one gate stops
    reaching the other and nothing else says so."""
    assert music_ingest.MusicIngestor._gate is broll_ingest.BrollIngestor._gate
    assert music_ingest.MusicIngestor.prepare is broll_ingest.BrollIngestor.prepare
    assert music_ingest.MusicIngestor.tick is broll_ingest.BrollIngestor.tick
    assert music_ingest.MusicIngestor.run is broll_ingest.BrollIngestor.run
    assert (music_ingest.MusicIngestor._pump_uploads
            is broll_ingest.BrollIngestor._pump_uploads)


def test_the_broll_kind_is_still_the_default(tmp_path):
    """Every existing caller constructs a b-roll ingestor by saying nothing."""
    ing = broll_ingest.BrollIngestor({}, tmp_path)
    assert ing.kind is ingest_kinds.BROLL_KIND
    assert ing.state_path.name == "broll_ingest.json"
    assert ing.kind.api_prefix == "/broll/api/fleet/ingest"


def test_music_has_its_own_state_file_and_prefix(tmp_path):
    ing = make_ingestor(tmp_path)
    assert ing.state_path.name == "music_ingest.json"
    assert ing.kind.api_prefix == "/music/api/fleet/ingest"
    assert ing.state_path.parent == (tmp_path / "state")


def test_music_never_blocks_the_proxy_generator(tmp_path):
    """The one gate decision that is NOT shared (plan §2): b-roll stands
    proxies down because both want the GPU, and music never touches it."""
    ing = make_ingestor(tmp_path)
    ing._state = broll_ingest.STATE_RUNNING
    ing._batch = {"uid": "b" * 32, "items": []}
    assert ing.is_working() is True
    assert ing.blocking_reason() is None


def test_the_window_counts_tracks_not_clips(tmp_path):
    ing = make_ingestor(tmp_path)
    ing._batch = {"uid": "b" * 32, "items": [{"stage": "pending"}] * 3,
                  "settings": {"run_mode": "idle"}}
    model = ing.progress_model()
    assert model.title == "INDEXING MUSIC"
    assert "tracks" in model.overall_line()


# ---------------------------------------------------------------------------
# staging
# ---------------------------------------------------------------------------

def test_only_audio_may_be_staged(tmp_path):
    ing = make_ingestor(tmp_path)
    status, answer = ing.prepare({"items": [
        {"local_id": "a", "name": "cue.wav", "source": "upload"},
        {"local_id": "b", "name": "A001.MP4", "source": "upload"},
    ]})
    assert status == 202
    by_id = {row["local_id"]: row for row in answer["items"]}
    assert by_id["a"]["accepted"] is True
    assert by_id["b"]["accepted"] is False
    assert "audio file" in by_id["b"]["reason"]


def test_the_upload_url_is_the_music_route(tmp_path):
    ing = make_ingestor(tmp_path)
    _status, answer = ing.prepare({"items": [
        {"local_id": "a", "name": "cue.wav", "source": "upload"}]})
    assert answer["items"][0]["upload_url"].startswith("/music/ingest/upload/")


def test_a_batch_bigger_than_the_server_takes_is_refused_here(tmp_path):
    """500 is `musicweb.config.MAX_BATCH_ITEMS`: offering to stage more would
    be an offer this machine cannot keep."""
    ing = make_ingestor(tmp_path)
    status, answer = ing.prepare({"items": [
        {"local_id": f"i{n}", "name": f"{n}.wav", "source": "upload"}
        for n in range(501)]})
    assert status == 413 and "500" in answer["message"]


# ---------------------------------------------------------------------------
# the pipeline
# ---------------------------------------------------------------------------

def _run_one(tmp_path, **kw):
    """Claim a one-track batch and crunch it. -> (ing, server, sidecar, queue,
    batch).

    The batch dict is handed back because a tick that finishes the last item
    RELEASES the batch and sets `_batch` to None -- correctly, and it is what
    the finish test asserts. The dict itself survives, so the per-item
    assertions read it here rather than reaching into a cleared field.
    """
    server = kw.pop("server", None) or FakeServer()
    sidecar = kw.pop("sidecar", None) or FakeSidecar()
    queue = kw.pop("queue", None) or FakeQueue()
    ing = make_ingestor(tmp_path, server=server, sidecar=sidecar, queue=queue, **kw)
    staging_id = stage_one(ing, tmp_path)
    status, answer = ing.run("b" * 32, staging_id)
    assert status == 202, answer
    batch = ing._batch
    ing.tick()
    return ing, server, sidecar, queue, batch


def test_one_track_goes_probe_transcode_embed_result_upload(tmp_path):
    _ing, server, sidecar, queue, batch = _run_one(tmp_path)

    # The .ogg was transcoded before anything was embedded or uploaded.
    assert batch["items"][0]["transcoded"] is True
    assert sidecar.embedded and sidecar.embedded[0].endswith(".mp3")
    assert server.states()[:2] == ["transcoding", "embedding"]
    assert queue.jobs and queue.jobs[0]["local"].endswith(".mp3")


def test_the_result_body_is_the_documented_one(tmp_path):
    _ing, server, _sidecar, _queue, _batch = _run_one(tmp_path)
    body = server.bodies("/result")[0]

    assert set(body) >= {"embedding", "dim", "model", "transcoded",
                         "content_hash", "duration", "peaks", "windows",
                         "probe", "size_bytes", "name"}
    # base64 of raw little-endian float32 -- the bytes db.to_blob stores.
    raw = base64.b64decode(body["embedding"])
    vector = np.frombuffer(raw, dtype="<f4")
    assert vector.size == body["dim"] == 512
    assert np.isclose(np.linalg.norm(vector), 1.0)
    # The waveform rides as base64 of the uint8 buckets.
    assert len(base64.b64decode(body["peaks"])) == 512
    # The duration is the decoded one, not ffprobe's 12.0.
    assert body["duration"] == 185.25
    assert body["transcoded"] is True
    assert body["probe"]["samplerate"] == 48000


def test_the_windows_ride_with_their_times(tmp_path):
    """`text_search(pool='max')` scores a track by its best 10 s window and is
    measurably better for it, so the per-window vectors are wanted."""
    _ing, server, _sidecar, _queue, _batch = _run_one(tmp_path)
    windows = server.bodies("/result")[0]["windows"]
    assert [w["idx"] for w in windows] == [0, 1]
    assert windows[1]["t0"] == 10.0
    assert np.frombuffer(base64.b64decode(windows[0]["vector"]),
                         dtype="<f4").size == 512


def test_the_upload_uses_the_name_the_server_allocated(tmp_path):
    """`theme.wav` and `theme (2).wav`: only the ledger knows which is which,
    so the destination is the server's answer and never a name this side
    invented."""
    _ing, _server, _sidecar, queue, batch = _run_one(tmp_path)
    assert queue.jobs[0]["rel"] == "Slow Burn (2).mp3"
    assert batch["items"][0]["dest_name"] == "Slow Burn (2).mp3"


def test_nothing_is_uploaded_when_the_result_was_refused(tmp_path):
    """A 409 model_mismatch is not transient: this companion's artefact is a
    different embedding space from the library's, and the bytes have nowhere
    legitimate to go."""
    server = FakeServer()
    server.result_status = 409
    server.result_body = {"detail": {"detail": "different CLAP model version",
                                     "reason": "model_mismatch"}}
    _ing, server, _sidecar, queue, batch = _run_one(tmp_path, server=server)
    assert queue.jobs == []
    assert batch["items"][0]["stage"] == broll_ingest.ITEM_FAILED
    assert "different CLAP model" in batch["items"][0]["error"]


def test_uploaded_declares_a_size_and_no_paths(tmp_path):
    """docs/API.md §6b: a music item owns exactly one file and the server
    allocated its name, so there is no path to validate and none to escape
    with."""
    _ing, server, _sidecar, _queue, batch = _run_one(tmp_path)
    body = server.bodies("/uploaded")[0]
    assert set(body) == {"size"}
    assert batch["items"][0]["stage"] == music_ingest.ITEM_LIVE


def test_the_checkpoint_carries_content_hash_not_hash(tmp_path):
    """ItemStatusIn declares `content_hash`; pydantic would silently DROP
    b-roll's `hash`, and the server would never record the digest its
    duplicate defence runs on."""
    _ing, server, _sidecar, _queue, _batch = _run_one(tmp_path)
    checkpoint = server.bodies("/status")[0]
    assert "content_hash" in checkpoint and "hash" not in checkpoint
    assert checkpoint["content_hash"]


def test_the_hash_follows_the_transcoded_bytes(tmp_path):
    """The server stores this as the file's content hash and stats the file it
    received; hashing the .ogg would record a digest of something nobody
    has."""
    _ing, server, _sidecar, _queue, batch = _run_one(tmp_path)
    item = batch["items"][0]
    assert item["hash"].startswith("b1a5e")
    assert server.bodies("/result")[0]["content_hash"] == item["hash"]


def test_a_wav_is_not_transcoded(tmp_path):
    server = FakeServer(items=[{
        "uid": "i" * 32, "ord": 0, "orig_name": "Slow Burn.wav",
        "size_bytes": 4096, "content_hash": None, "duration_s": 185.0,
        "state": "pending", "duplicate_of": None, "source": "upload",
        "dest_name": None, "track_id": None, "attempts": 0,
    }])
    sidecar = FakeSidecar()
    ing = make_ingestor(tmp_path, server=server, sidecar=sidecar)
    staging_id = stage_one(ing, tmp_path, name="Slow Burn.wav")
    ing.run("b" * 32, staging_id)
    ing.tick()
    assert "transcoding" not in server.states()
    assert sidecar.embedded[0].endswith(".wav")


# ---------------------------------------------------------------------------
# the gate and the model
# ---------------------------------------------------------------------------

def test_a_build_that_cannot_run_the_model_refuses_the_claim(tmp_path):
    """The primary fallback (plan §1): the page then falls back to the browser
    upload, which lands the file in the library and leaves a base-rig queue
    row -- the loop that existed before this feature."""
    sidecar = FakeSidecar(refusal="this build cannot run the music indexing model")
    ing = make_ingestor(tmp_path, sidecar=sidecar)
    staging_id = stage_one(ing, tmp_path)
    status, answer = ing.run("b" * 32, staging_id)
    assert status == 503
    assert answer["reason"] == "tier_unfit"
    assert "cannot run the music indexing model" in answer["message"]


def test_a_missing_model_is_fetched_before_any_track_is_touched(tmp_path):
    sidecar = FakeSidecar(ready=False)
    ing = make_ingestor(tmp_path, sidecar=sidecar)
    staging_id = stage_one(ing, tmp_path)
    ing.run("b" * 32, staging_id)
    ing.tick()
    assert sidecar.ensured == 1


def test_the_model_download_is_the_windows_headline(tmp_path):
    sidecar = FakeSidecar(ready=False)
    sidecar.downloading = {"name": "music-clap-audio-1.onnx", "percent": 42}
    ing = make_ingestor(tmp_path, sidecar=sidecar)
    ing._batch = {"uid": "b" * 32, "items": [{"stage": "pending"}],
                  "settings": {"run_mode": "idle"}}
    model = ing.progress_model()
    assert model.headline_percent == 42
    # The artefact's filename is a true answer to a question no editor asked.
    assert "music indexing model" in model.headline


def test_a_track_that_cannot_be_embedded_is_left_for_the_base_rig(tmp_path):
    """The kept fallback (plan §1, rejected option (a)): the file belongs in
    the library whether or not THIS machine could embed it."""
    sidecar = FakeSidecar()
    # ModelUnavailable, not SidecarError: the model went missing between the
    # gate and the load (a deleted cache, a half-written download). The gate
    # is still open, so the drain reaches the track and has to decide.
    sidecar.raise_on_embed = music_clap_sidecar.ModelUnavailable(
        "the music indexing model is not downloaded on this machine yet")
    _ing, server, _sidecar, queue, batch = _run_one(tmp_path, sidecar=sidecar)
    item = batch["items"][0]

    assert item["stage"] == music_ingest.ITEM_QUEUED_FOR_BASE_RIG
    assert "not downloaded" in item["error"]
    # NOTHING was uploaded: the library's names are allocated by the server at
    # `result`, this item never got that far, and the only name this side could
    # have used is how you overwrite another editor's `theme.wav`.
    assert queue.jobs == []
    # The ledger was told, so an admin can see who has to finish it -- and the
    # staged file is still here for the browser-upload fallback.
    assert server.states()[-1] == music_ingest.ITEM_QUEUED_FOR_BASE_RIG
    assert Path(item["local_path"]).is_file()


def test_a_decode_failure_fails_the_track_rather_than_queueing_it(tmp_path):
    """A refusal from the FILE is not a refusal from the machine: queueing a
    corrupt track for the base rig would only move the failure."""
    sidecar = FakeSidecar()
    sidecar.raise_on_embed = music_clap_sidecar.SidecarError(
        "this file has no audio this machine could decode")
    _ing, _server, _sidecar, queue, batch = _run_one(tmp_path, sidecar=sidecar)
    assert batch["items"][0]["stage"] == broll_ingest.ITEM_FAILED
    assert queue.jobs == []


# ---------------------------------------------------------------------------
# the reporter section
# ---------------------------------------------------------------------------

def test_the_report_section_names_its_kind(tmp_path):
    """Two sections ride one report and land in different columns; a section
    that could not name itself would be one flatten() from writing music's
    counters into b-roll's chip."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server)
    staging_id = stage_one(ing, tmp_path)
    ing.run("b" * 32, staging_id)          # claimed, nothing crunched yet
    section = ing.report()
    assert section["kind"] == "music"
    assert section["tier"] == "", "music has one model and nothing to choose"
    assert section["batch_uid"] == "b" * 32


def test_a_dashboard_cancel_reaches_the_right_orchestrator(tmp_path):
    """`commands.music_ingest.cancel`, never b-roll's: one editor can be
    running one of each."""
    ing = make_ingestor(tmp_path)
    staging_id = stage_one(ing, tmp_path)
    ing.run("b" * 32, staging_id)
    ing.note_report_response({"commands": {"broll_ingest": {"cancel": ["b" * 32]}}})
    assert ing.status()["batch_uid"] == "b" * 32, "a b-roll cancel is not ours"
    ing.note_report_response({"commands": {"music_ingest": {"cancel": ["b" * 32]}}})
    assert ing.status()["batch_uid"] == ""


# ---------------------------------------------------------------------------
# the loopback routes
# ---------------------------------------------------------------------------

def test_the_capability_route_reports_the_clap_model(tmp_path, monkeypatch):
    monkeypatch.setattr(music_clap_sidecar, "model_ready", lambda key="": False)
    music_clap_sidecar.reset_caches()
    music_clap_sidecar.refresh(force=True)
    caps = broll_server.build_ingest_capabilities(
        {"music_clap_feed_base": "https://github.com/o/r/v1",
         "music_ingest_staging_dir": str(tmp_path)},
        None, None, kind=ingest_kinds.MUSIC_KIND)

    assert caps["kind"] == "music"
    assert set(caps["clap"]) >= {"cached", "download_bytes", "version"}
    # No tiers and no VRAM: a machine with no GPU is a good music indexer.
    assert "tiers" not in caps and "gpu" not in caps
    assert caps["max_file_bytes"] == 512 * 1024 * 1024
    assert ".wav" in caps["audio_exts"] and ".ogg" in caps["transcode_exts"]


def test_the_broll_capability_route_is_unchanged(tmp_path):
    """The same function, called the way it always was."""
    caps = broll_server.build_ingest_capabilities({}, None, None)
    assert set(caps["tiers"]) == {"good", "best"}
    assert "clap" not in caps


def test_a_music_path_resolves_to_the_music_kind():
    handler = broll_server.BrollRequestHandler.__new__(
        broll_server.BrollRequestHandler)
    assert handler._kind_for_path("/music/ingest/progress").name == "music"
    assert handler._kind_for_path("/broll/ingest/progress").name == "broll"
    # Anything else is b-roll's, which is what it was before music existed.
    assert handler._kind_for_path("/status").name == "broll"


def test_the_free_space_floor_reads_this_kind_s_key(tmp_path):
    """The orchestrator reads `<prefix>_free_space_floor_gb` through cfg_key,
    so the loopback must too: a site that set only the music key used to get
    its number in the batch and b-roll's at the PUT that refuses first."""
    cfg = {"music_ingest_free_space_floor_gb": 5,
           "broll_ingest_free_space_floor_gb": 40,
           "music_ingest_staging_dir": str(tmp_path)}

    music = broll_server.build_ingest_capabilities(
        cfg, None, None, kind=ingest_kinds.MUSIC_KIND)
    broll = broll_server.build_ingest_capabilities(cfg, None, None)

    assert music["staging"]["floor_bytes"] == 5_000_000_000
    assert broll["staging"]["floor_bytes"] == 40_000_000_000


def test_a_music_ingest_get_reaches_the_ingest_dispatcher():
    """The GET dispatcher tested `INGEST_PREFIX` (b-roll's) rather than the
    whole set until 2026-08-18, so `/music/ingest/capabilities` 404'd and every
    music page read that as "this companion is too old" and uploaded through
    the browser. The music feature was invisible on the machine holding it."""
    handler = broll_server.BrollRequestHandler.__new__(
        broll_server.BrollRequestHandler)
    seen: list[str] = []
    answered: list[int] = []
    handler._dispatch_ingest_get = lambda path, query: (  # type: ignore[method-assign]
        seen.append(path) or True)
    handler._send_json = lambda status, body: answered.append(status)  # type: ignore[method-assign]

    for path in ("/music/ingest/capabilities", "/music/ingest/progress",
                 "/music/ingest/thumb", "/broll/ingest/capabilities"):
        handler.path = path
        handler._dispatch_get()

    assert seen == ["/music/ingest/capabilities", "/music/ingest/progress",
                    "/music/ingest/thumb", "/broll/ingest/capabilities"]
    assert answered == []


def test_the_upload_route_matches_both_prefixes():
    match = broll_server._UPLOAD_PATH_RE.match("/music/ingest/upload/s1/l1")
    assert match and match.group(1) == "music"
    assert (match.group(2), match.group(3)) == ("s1", "l1")
    assert broll_server._UPLOAD_PATH_RE.match("/broll/ingest/upload/s1/l1")
    assert not broll_server._UPLOAD_PATH_RE.match("/ytdl/ingest/upload/s1/l1")


def test_the_state_file_is_written_where_the_plan_says(tmp_path):
    ing = make_ingestor(tmp_path)
    ing._save()
    saved = json.loads((tmp_path / "state" / "music_ingest.json").read_text())
    assert saved["version"] == 1
    assert not (tmp_path / "state" / "broll_ingest.json").exists()


# ---------------------------------------------------------------------------
# the shared upload queue's lifetime (comp-loopback-1, 2026-08-21)
# ---------------------------------------------------------------------------

def test_a_cancelled_batch_leaves_the_next_one_a_working_queue(tmp_path):
    """The b-roll fix reaches music because the orchestrator is shared:
    `stop_all` latches an UploadQueue shut for ever, so the object cannot
    outlive the batch that was cancelled or every later album's file is handed
    to a queue nothing will ever drain."""
    server = FakeServer()
    queues = [FakeQueue()]
    ing = make_ingestor(tmp_path, server=server, queue=queues[0])

    def _fresh():
        queues.append(FakeQueue())
        return queues[-1]

    ing._new_queue = _fresh
    first = stage_one(ing, tmp_path)
    ing.run("b" * 32, first)
    ing.cancel("cancelled from the tray")

    second = stage_one(ing, tmp_path)
    status, answer = ing.run("b" * 32, second)
    ing.tick()

    assert status == 202, answer
    assert len(queues) == 2, "the cancelled queue is dead; the next batch needs a new one"
    assert queues[1].jobs, "and the next track has to reach a queue that runs"
    assert queues[1].dead == []


def test_a_new_queue_points_at_this_batchs_library(tmp_path):
    """Per BATCH, not per process: the library path is the SERVER's answer to
    this batch's claim, so a queue built for the previous one would upload
    into the wrong place (comp-loopback-1, 2026-08-21)."""
    ing = make_ingestor(tmp_path, uploader=None)
    ing._batch = {"uid": "b" * 32, "archive_remote_rel": "Assets/Music Library"}

    queue = ing._new_queue()

    assert queue._archive_rel == "Assets/Music Library"


def test_the_upload_plan_names_the_one_file_the_server_named(tmp_path):
    """Both kinds have to answer "which local file is behind this remote rel"
    for the retry path to be shared (comp-loopback-3, 2026-08-21). A track
    with no allocated name has nothing to answer with, which is the same case
    `_enqueue_uploads` fails it for."""
    ing = make_ingestor(tmp_path)
    item = {"dest_name": "Slow Burn_2.mp3",
            "outputs": {"audio": str(tmp_path / "Slow Burn.mp3")}}

    plan = ing._upload_plan(item)

    assert plan == {"Slow Burn_2.mp3": (music_ingest.KIND_AUDIO,
                                        str(tmp_path / "Slow Burn.mp3"))}
    assert ing._upload_plan({"outputs": {"audio": "x.mp3"}}) == {}


def test_the_music_checkpoint_is_the_same_save():
    """bug-hunt-2026-09-03 comp-broll-music-1 names music_ingest as well as
    b-roll, and the answer is that MusicIngestor INHERITS _save: the snapshot
    that stopped being lost to a thread adding a key is this one. Pinned
    because a second copy of _save here would bring the defect back with it,
    and _crunch_item's item["analysis"] = ... is exactly the mutator."""
    import inspect

    assert music_ingest.MusicIngestor._save is broll_ingest.BrollIngestor._save
    assert "_snapshot(self._batch)" in inspect.getsource(
        broll_ingest.BrollIngestor._save)


# ---------------------------------------------------------------------------
# CMEDIA-4: a track waiting for the base rig is counted, and is NOT deleted
# ---------------------------------------------------------------------------


def _queued_batch(tmp_path):
    sidecar = FakeSidecar()
    sidecar.raise_on_embed = music_clap_sidecar.ModelUnavailable(
        "the music indexing model is not downloaded on this machine yet")
    return _run_one(tmp_path, sidecar=sidecar)


def test_a_queued_track_is_counted_and_the_window_can_finish(tmp_path):
    """It was in the kind's finished set and in NEITHER counter: the tray said
    "8 of 10" for ever, the ETA divided by a remainder that never reached zero,
    and the progress window's `finished` never became true."""
    ing = make_ingestor(tmp_path)
    # Mid-batch, which is when this is visible: one track embedded, one left
    # for the base rig, one still to go.
    ing._batch = {"uid": "b" * 32, "state": "running", "items": [
        {"uid": "i1", "name": "one.wav", "stage": broll_ingest.ITEM_LIVE},
        {"uid": "i2", "name": "Slow Burn.ogg",
         "stage": music_ingest.ITEM_QUEUED_FOR_BASE_RIG,
         "error": "the music indexing model is not downloaded"},
    ]}

    snap = ing.status()
    assert snap["queued_for_base_rig"] == 1
    assert (snap["done"], snap["failed"]) == (1, 0)
    assert snap["queued_names"] == ["Slow Burn.ogg"]

    model = ing.progress_model()
    assert model.finished is True
    assert "need the base rig to finish" in model.note
    assert ing.progress()["batch"]["queued_for_base_rig"] == 1


def test_the_pruner_never_deletes_a_drop_the_base_rig_still_needs(tmp_path):
    """"It is still on this computer" is the whole contract of the state, and
    CLEAR FINISHED STAGING is prune_staging(0) -- immediate, no confirmation."""
    ing, _server, _sidecar, _queue, _batch = _queued_batch(tmp_path)
    (staging_id, entry), = list(ing._staging.items())
    assert entry["held_for_base_rig"] == ["Slow Burn.ogg"]
    directory = Path(entry["dir"])
    assert directory.is_dir()

    answer = ing.prune_staging(0)

    assert answer["removed"] == 0
    assert answer["held"] == 1 and answer["held_names"] == ["Slow Burn.ogg"]
    assert directory.is_dir()
    assert staging_id in ing._staging
