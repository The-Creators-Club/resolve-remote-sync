"""The CLAP audio sidecar: the vendored front end, the download gates, and
one file turned into one vector.

Three kinds of test, and the split is the point:

  * **parity** -- `music_clap/` is the indexer's bytes below its marker, and
    the two functions that could NOT be vendored (the waveform overview and
    the window layout, which reach `music_index.config`) are pinned against
    the indexer's own copies value for value. A drifted mel or a drifted
    window layout does not raise: it produces a plausible 512-dimensional
    vector for audio that does not sound like that, in a space every cosine in
    the library is measured against;
  * **the gates** -- what this module refuses to download, and why, without a
    byte moving. Every one of them is a refusal an editor reads;
  * **the pipeline**, with the ONNX session and ffmpeg replaced by doubles, so
    the shape of `embed_file`'s answer is pinned on a machine with no model.

`test_embeddings_match_the_torch_model` is the real gate for the numbers and
skips loudly: it needs the exported artefact AND a torch environment, neither
of which exists on an editor's machine or in CI.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ccsync_companion import music_clap_sidecar as sidecar
from ccsync_companion.music_clap import mel_numpy, music_models

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEXER_DIR = REPO_ROOT / "music" / "indexer"
VENDORED_DIR = (REPO_ROOT / "companion" / "src" / "ccsync_companion" / "music_clap")
PARAMS_FIXTURE = INDEXER_DIR / "tests" / "fixtures" / "clap_audio_params.json"

VENDOR_MARKER = b"# --- vendored content below, byte-identical ---"
VENDORED_MODULES = ("music_models.py", "mel_numpy.py")


@pytest.fixture(autouse=True)
def _forget_caches():
    """The module caches a session, an extractor and a readiness snapshot in
    module state; a test that left one behind would decide the next one."""
    sidecar.reset_caches()
    yield
    sidecar.reset_caches()


# ---------------------------------------------------------------------------
# parity
# ---------------------------------------------------------------------------

def _body_below_marker(path: Path) -> bytes:
    raw = path.read_bytes()
    assert raw.count(VENDOR_MARKER) == 1, (
        f"{path} must carry the marker exactly once, as the last line of its "
        f"header (found {raw.count(VENDOR_MARKER)})")
    rest = raw.split(VENDOR_MARKER, 1)[1]
    if rest.startswith(b"\r\n"):
        return rest[2:]
    return rest[1:] if rest.startswith(b"\n") else rest


@pytest.mark.parametrize("name", VENDORED_MODULES)
def test_each_vendored_module_matches_its_source(name):
    source = (INDEXER_DIR / name).read_bytes()
    body = _body_below_marker(VENDORED_DIR / name)
    assert body == source, (
        f"{VENDORED_DIR / name} has drifted from {INDEXER_DIR / name} "
        f"({len(body)} bytes below the marker vs {len(source)}). Edit the "
        f"INDEXER's copy, then re-copy the whole file in below the marker.")


def test_the_vendored_set_is_exactly_what_is_pinned():
    """A third module that appeared here without a parity pair in
    tools/release.ps1 and server/tests/test_cross_component.py would be
    unchecked forever."""
    present = sorted(p.name for p in VENDORED_DIR.glob("*.py")
                     if p.name != "__init__.py")
    assert present == sorted(VENDORED_MODULES)


@pytest.fixture(scope="module")
def params():
    return mel_numpy.MelParams(json.loads(PARAMS_FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def extractor(params):
    return mel_numpy.MelExtractor(params)


def _indexer_module(name: str):
    """The indexer's own copy, loaded by path. `music_index` is not importable
    from the companion's venv (it puts ../web on sys.path and expects
    musicweb), so the two modules that matter are loaded directly."""
    path = INDEXER_DIR / f"{name}.py"
    if not path.is_file():
        pytest.skip(f"the indexer's {name}.py is not in this checkout")
    spec = importlib.util.spec_from_file_location(f"_indexer_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_windows(extractor, n=20):
    """20 deterministic 10 s windows. Reproducible on any machine, which is
    what makes a bit-parity assertion meaningful without library audio."""
    rng = np.random.default_rng(20260818)
    return [(0.25 * rng.standard_normal(extractor.p.n_samples)).astype(np.float32)
            for _ in range(n)]


def test_the_mel_front_end_is_bit_identical_to_the_indexers(extractor):
    """20 windows, and BIT equality rather than a tolerance: an embedding
    computed from a slightly different spectrogram is a plausible vector for
    the wrong audio, and no cosine threshold downstream would catch it."""
    theirs = _indexer_module("mel_numpy")
    reference = theirs.MelExtractor(theirs.MelParams(
        json.loads(PARAMS_FIXTURE.read_text(encoding="utf-8"))))
    chunks = _synthetic_windows(extractor)
    ours = extractor.input_features(chunks)
    ref = reference.input_features(chunks)
    assert ours.shape == ref.shape == (20, 1, extractor.p.n_frames, extractor.p.n_mels)
    assert np.array_equal(ours, ref)


def test_the_mel_matches_the_exporters_own_golden(extractor):
    """The indexer's `test_mel_numpy.GOLDEN`, restated here so a companion
    that never runs the indexer's suite still finds out that the front end
    moved. Same seed, same slice, same numbers."""
    golden = np.array([
        [-19.03274917602539, -9.025296211242676, -6.374568462371826, -5.570005893707275],
        [-8.834033966064453, 1.2019226551055908, -0.5166364312171936, -2.351816415786743],
        [-4.5605244636535645, -10.886054992675781, -3.8859047889709473, -3.4379539489746094],
        [0.34138742089271545, -12.451456069946289, 0.9995208978652954, -1.4109481573104858],
        [1.0303517580032349, -1.8500443696975708, -5.685239315032959, -1.76229989528656],
        [-9.880579948425293, -4.3946428298950195, -13.181050300598145, -5.907430171966553],
    ], dtype=np.float32)
    rng = np.random.default_rng(20260818)
    signal = (0.25 * rng.standard_normal(extractor.p.n_samples)).astype(np.float32)
    mel = extractor.log_mel(signal)
    assert np.allclose(mel[::200, ::16], golden, atol=1e-4)


def test_the_waveform_overview_matches_the_indexers(monkeypatch):
    """`peaks` is PORTED, not vendored (the indexer's copy reaches
    music_index.config), so it is pinned by value instead: the library's 376
    existing waveforms were drawn by that function."""
    audio_mod = _load_indexer_audio()
    rng = np.random.default_rng(7)
    for size in (0, 100, 900, 48_000, 480_123):
        signal = (rng.standard_normal(size) * 0.4).astype(np.float32)
        assert sidecar.peaks(signal) == audio_mod.peaks(signal), size


def test_the_window_layout_matches_the_indexers():
    """Same reason as the waveform: a different set of 10 s windows is a
    different track vector, and nothing downstream can tell."""
    audio_mod = _load_indexer_audio()
    rng = np.random.default_rng(11)
    for seconds in (3, 12, 45, 200, 700):
        signal = (rng.standard_normal(48_000 * seconds) * 0.3).astype(np.float32)
        ours = sidecar.windows(signal)
        theirs = audio_mod.windows(signal)
        assert len(ours) == len(theirs), seconds
        for (chunk_a, t0a, t1a), (chunk_b, t0b, t1b) in zip(ours, theirs):
            assert np.array_equal(chunk_a, chunk_b)
            assert (t0a, t1a) == (t0b, t1b)


def _load_indexer_audio():
    """`music_index.audio`, which needs `musicweb` on sys.path for its config
    import. Skipped rather than failed where the music tree is absent."""
    web = REPO_ROOT / "music" / "web"
    if not (INDEXER_DIR / "music_index" / "audio.py").is_file() or not web.is_dir():
        pytest.skip("the music tree is not in this checkout")
    for entry in (str(web), str(INDEXER_DIR)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    try:
        from music_index import audio  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"music_index.audio is not importable here: {exc}")
    return audio


# ---------------------------------------------------------------------------
# the feed and its gates
# ---------------------------------------------------------------------------

def test_the_feed_base_comes_from_the_site_manifest():
    assert sidecar.feed_base({}, {"release_feed_base": "https://feed.test/v1/"}) \
        == "https://feed.test/v1"


def test_a_config_override_beats_the_manifest():
    """A base rig or a dev loop pointing at a local server."""
    got = sidecar.feed_base({"music_clap_feed_base": "https://local.test/f"},
                            {"release_feed_base": "https://feed.test/v1"})
    assert got == "https://local.test/f"


def test_no_feed_is_a_blank_answer_not_a_guess():
    assert sidecar.feed_base({}, {}) == ""


@pytest.mark.parametrize("url,ok", [
    ("https://github.com/o/r/releases/download/v1/music-clap-audio-1.onnx", True),
    ("https://release-assets.githubusercontent.com/x/y", True),
    ("http://github.com/o/r/x.onnx", False),           # never plain http
    ("https://evil-githubusercontent.com/x", False),   # never a suffix test
    ("https://example.test/x.onnx", False),
])
def test_the_host_allow_list(url, ok):
    assert sidecar.host_allowed(url) is ok


def test_ensure_refuses_without_a_feed_and_downloads_nothing(monkeypatch):
    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    monkeypatch.setattr(sidecar, "feed_base", lambda *a, **k: "")
    ok, message = sidecar.ensure({})
    assert ok is False
    assert "release feed" in message


def test_ensure_refuses_an_unpinned_catalogue(monkeypatch):
    """An unpinned model is an unverified download, which is the one thing
    this path must never make."""
    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    monkeypatch.setattr(music_models, "is_pinned", lambda key=None: False)
    ok, message = sidecar.ensure({})
    assert ok is False and "placeholder" in message


def test_ensure_refuses_a_host_that_is_not_on_the_list(monkeypatch):
    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    monkeypatch.setattr(sidecar, "feed_base", lambda *a, **k: "https://evil.test/v1")
    ok, message = sidecar.ensure({})
    assert ok is False and "evil.test" in message


def test_ensure_refuses_when_the_disk_is_too_small(monkeypatch, tmp_path):
    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    monkeypatch.setattr(sidecar, "feed_base", lambda *a, **k: "https://github.com/o/r/x")
    monkeypatch.setattr(sidecar, "free_space_refusal", lambda *a, **k: "no room")
    assert sidecar.ensure({}) == (False, "no room")


def test_a_disk_we_cannot_measure_is_not_a_refusal(monkeypatch, tmp_path):
    """sidecar_tools' rule: "I could not tell" must never read as "no"."""
    monkeypatch.setattr(sidecar.shutil, "disk_usage",
                        lambda *a: (_ for _ in ()).throw(OSError("nope")))
    assert sidecar.free_space_refusal(directory=tmp_path) is None


def test_ensure_fetches_both_files_and_verifies_them(monkeypatch, tmp_path):
    """The happy path, with the vendored fetcher replaced: what matters here
    is that BOTH files are asked for, each with its own pinned digest."""
    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    monkeypatch.setattr(sidecar, "feed_base",
                        lambda *a, **k: "https://github.com/o/r/releases/download/v1")
    monkeypatch.setattr(sidecar, "free_space_refusal", lambda *a, **k: None)
    monkeypatch.setattr(sidecar, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(sidecar, "refresh", lambda force=False: {})
    asked = []

    def fake_download(url, dest, *, sha256, size_bytes=None, progress=None):
        asked.append((url, dest.name, sha256))
        if progress is not None:
            progress(size_bytes or 1, size_bytes)
        dest.write_bytes(b"x")
        return dest

    from ccsync_companion.broll_vlm import local_runtime
    monkeypatch.setattr(local_runtime, "download_verified", fake_download)

    ok, message = sidecar.ensure({})

    assert ok is True and "ready" in message
    onnx, params_name = music_models.filenames()
    assert sorted(name for _u, name, _s in asked) == sorted([onnx, params_name])
    for _url, name, digest in asked:
        assert digest == music_models.expected_sha256(name)


def test_a_stop_event_leaves_the_partial_alone(monkeypatch, tmp_path):
    """A shutdown mid-download is a resumable partial, not a failure."""
    import threading

    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    monkeypatch.setattr(sidecar, "feed_base",
                        lambda *a, **k: "https://github.com/o/r/releases/download/v1")
    monkeypatch.setattr(sidecar, "free_space_refusal", lambda *a, **k: None)
    monkeypatch.setattr(sidecar, "cache_dir", lambda: tmp_path)
    stop = threading.Event()
    stop.set()
    ok, message = sidecar.ensure({}, stop_event=stop)
    assert ok is False and "resume" in message


# ---------------------------------------------------------------------------
# what the loopback publishes
# ---------------------------------------------------------------------------

def test_capabilities_is_zero_io_and_names_the_download(monkeypatch):
    monkeypatch.setattr(sidecar, "model_ready", lambda key="": False)
    sidecar.refresh(force=True)
    caps = sidecar.capabilities({"music_clap_feed_base": "https://github.com/o/r/v1"})
    assert caps["cached"] is False
    assert caps["download_bytes"] == sum(music_models.model()["size_bytes"].values())
    assert caps["version"] == music_models.model()["version"]
    assert caps["dim"] == 512
    assert caps["feed"] is True


def test_a_cached_model_has_nothing_to_download(monkeypatch):
    monkeypatch.setattr(sidecar, "model_ready", lambda key="": True)
    sidecar.refresh(force=True)
    caps = sidecar.capabilities({})
    assert caps["cached"] is True and caps["download_bytes"] == 0


def test_the_refusal_names_the_missing_feed(monkeypatch):
    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    assert "release feed" in sidecar.refusal({})


def test_no_refusal_when_everything_is_in_place(monkeypatch):
    monkeypatch.setattr(sidecar, "runtime_available", lambda: (True, ""))
    assert sidecar.refusal({"music_clap_feed_base": "https://github.com/o/r/v1"}) == ""


def test_the_model_id_names_the_checkpoint_and_the_export():
    """`tracks.model` has to stay comparable with the rows the base rig wrote
    -- same checkpoint, same space -- while still recording WHICH export
    produced a row (plan §1)."""
    got = sidecar.model_id()
    assert got.startswith(music_models.model()["hf_model"])
    assert got.endswith("onnx" + music_models.model()["version"])


# ---------------------------------------------------------------------------
# decoding and the pipeline
# ---------------------------------------------------------------------------

class _FakeCompleted:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_decode_never_writes_a_temp_file(monkeypatch, tmp_path):
    """The whole point of decoding through a pipe: a 60 MB wav copied into
    staging per track would double an ingest's disk traffic and leave debris
    behind a killed process."""
    seen = {}
    samples = np.linspace(-1, 1, 4800, dtype=np.float32)

    def fake_run(cmd, timeout, capture_stdout=True):
        seen["cmd"] = cmd
        return _FakeCompleted(stdout=samples.tobytes())

    monkeypatch.setattr(sidecar, "_run", fake_run)
    got = sidecar.decode("ffmpeg", tmp_path / "a.wav")

    assert np.allclose(got, samples)
    assert seen["cmd"][-1] == "-", "the output goes to stdout, never to a path"
    assert "f32le" in seen["cmd"] and "48000" in seen["cmd"]
    # Nothing landed beside the source (the conftest redirects HOME into
    # tmp_path, so its own .ccsync is expected and is not ours).
    assert [p.name for p in tmp_path.iterdir()] == [".ccsync"]


def test_decode_scrubs_nan_and_inf(monkeypatch, tmp_path):
    """A damaged file that decodes to Inf poisons the embedding rather than
    failing, and a poisoned vector is one nothing downstream can detect."""
    bad = np.array([np.nan, np.inf, -np.inf, 0.5], dtype=np.float32)
    monkeypatch.setattr(sidecar, "_run",
                        lambda *a, **k: _FakeCompleted(stdout=bad.tobytes()))
    got = sidecar.decode("ffmpeg", tmp_path / "a.wav")
    assert np.isfinite(got).all()
    assert got.tolist() == [0.0, 0.0, 0.0, 0.5]


def test_probe_answers_zero_for_something_that_is_not_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(sidecar, "_run", lambda *a, **k: _FakeCompleted(
        stdout=json.dumps({"format": {"duration": "12"}, "streams": [
            {"codec_type": "video", "codec_name": "h264"}]}).encode()))
    assert sidecar.probe("ffmpeg", tmp_path / "x.mp3")["duration"] == 0.0


def test_probe_reads_the_audio_stream(monkeypatch, tmp_path):
    monkeypatch.setattr(sidecar, "_run", lambda *a, **k: _FakeCompleted(
        stdout=json.dumps({"format": {"duration": "185.5"}, "streams": [
            {"codec_type": "audio", "sample_rate": "44100", "channels": 2,
             "codec_name": "flac"}]}).encode()))
    got = sidecar.probe("ffmpeg", tmp_path / "x.flac")
    assert got == {"duration": 185.5, "samplerate": 44100, "channels": 2,
                   "codec": "flac"}


def test_a_transcode_that_dropped_the_audio_is_a_failure(monkeypatch, tmp_path):
    """It exits 0 and writes a file, which is exactly why it has to be probed:
    a silent mp3 uploads perfectly happily."""
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()

    def fake_run(cmd, timeout, capture_stdout=True):
        (dest_dir / "a.mp3").write_bytes(b"junk")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(sidecar, "_run", fake_run)
    monkeypatch.setattr(sidecar, "probe", lambda *a: {"duration": 0.0})
    with pytest.raises(RuntimeError) as exc:
        sidecar.transcode_to_mp3("ffmpeg", tmp_path / "a.ogg", dest_dir)
    assert "no audio" in str(exc.value)


def test_the_transcode_command_is_the_containers(monkeypatch, tmp_path):
    """`routes_ingest._transcode_to_mp3`, flag for flag: the same album
    ingested through two doors must land as the same bytes."""
    seen = {}
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()

    def fake_run(cmd, timeout, capture_stdout=True):
        seen["cmd"] = cmd
        (dest_dir / "a.mp3").write_bytes(b"x" * 10)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(sidecar, "_run", fake_run)
    monkeypatch.setattr(sidecar, "probe", lambda *a: {"duration": 12.0})
    out = sidecar.transcode_to_mp3("ffmpeg", tmp_path / "a.ogg", dest_dir)
    assert out.name == "a.mp3"
    assert "libmp3lame" in seen["cmd"]
    assert "320k" in seen["cmd"]
    assert "-map_metadata" in seen["cmd"]


class _FakeSession:
    """An InferenceSession that returns unit vectors, so `embed_file` can be
    tested on a machine with no model."""

    class _Spec:
        def __init__(self, name):
            self.name = name

    def __init__(self, dim=512):
        self.dim = dim
        self.calls = []

    def get_inputs(self):
        return [self._Spec("input_features"), self._Spec("is_longer")]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _outputs, inputs):
        self.calls.append(inputs)
        n = inputs["input_features"].shape[0]
        out = np.zeros((n, self.dim), dtype=np.float32)
        out[:, 0] = 1.0
        return [out]


def _fake_pipeline(monkeypatch, seconds=30.0, dim=512):
    params = mel_numpy.MelParams(json.loads(PARAMS_FIXTURE.read_text(encoding="utf-8")))
    extractor = mel_numpy.MelExtractor(params)
    session = _FakeSession(dim)
    monkeypatch.setattr(sidecar, "extractor", lambda key="": extractor)
    monkeypatch.setattr(sidecar, "session", lambda key="": session)
    rng = np.random.default_rng(3)
    signal = (rng.standard_normal(int(48_000 * seconds)) * 0.2).astype(np.float32)
    monkeypatch.setattr(sidecar, "decode", lambda *a, **k: signal)
    return session, signal


def test_embed_file_answers_everything_the_result_route_wants(monkeypatch, tmp_path):
    session, signal = _fake_pipeline(monkeypatch, seconds=30.0)
    got = sidecar.embed_file(tmp_path / "a.wav")

    assert got["dim"] == 512
    expected = len(sidecar.windows(signal))
    assert got["n_windows"] == len(got["windows"]) == expected
    assert len(got["peaks"]) == sidecar.PEAK_BUCKETS
    assert np.isclose(np.linalg.norm(got["embedding"]), 1.0)
    assert got["model"] == sidecar.model_id()
    # The duration is the DECODED sample count, never ffprobe's answer.
    assert got["duration"] == pytest.approx(signal.size / 48_000)


def test_embed_file_feeds_the_graph_the_shape_it_declares(monkeypatch, tmp_path):
    session, _signal = _fake_pipeline(monkeypatch, seconds=30.0)
    sidecar.embed_file(tmp_path / "a.wav")
    fed = session.calls[0]
    assert fed["input_features"].shape[1:] == (1, 1001, 64)
    assert fed["input_features"].dtype == np.float32
    # `is_longer` is always False -- one window per clip, no fusion branch.
    windows = fed["input_features"].shape[0]
    assert fed["is_longer"].shape == (windows, 1) and not fed["is_longer"].any()


def test_a_file_with_no_audio_is_refused_not_embedded(monkeypatch, tmp_path):
    _fake_pipeline(monkeypatch)
    monkeypatch.setattr(sidecar, "decode",
                        lambda *a, **k: np.zeros(0, dtype=np.float32))
    with pytest.raises(sidecar.SidecarError) as exc:
        sidecar.embed_file(tmp_path / "a.wav")
    assert "no audio" in str(exc.value)


def test_stop_server_drops_the_session(monkeypatch, tmp_path):
    session, _signal = _fake_pipeline(monkeypatch, seconds=12.0)
    sidecar.embed_file(tmp_path / "a.wav")
    sidecar.stop_server()          # never raises, and frees ~300 MB
    assert sidecar.status()["downloading"] is None


def test_the_content_hash_is_the_libraries_digest(tmp_path):
    """blake2b-16 over the whole file: what `musicweb.db.content_hash`
    computes, and what the server compares against."""
    import hashlib

    path = tmp_path / "a.wav"
    path.write_bytes(b"hello music" * 1000)
    expected = hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()
    assert sidecar.content_hash(path) == expected


# ---------------------------------------------------------------------------
# the real gate: the same numbers as the torch model
# ---------------------------------------------------------------------------

def _artefact_dir():
    env = os.environ.get("MUSIC_AUDIO_ENCODER_DIR")
    if env:
        return Path(env)
    return REPO_ROOT / "music" / "web" / "data" / "audio_encoder"


TORCH_VENV = Path(r"E:\Projects\music-tagger\.venv\Scripts\python.exe")
LIBRARY = Path(r"P:\Assets\Music")


@pytest.mark.skipif(
    not (TORCH_VENV.is_file() and LIBRARY.is_dir()
         and (_artefact_dir() / music_models.filenames()[0]).is_file()),
    reason="needs the exported artefact AND a torch environment AND the music "
           "library: a base rig, not CI and not an editor's machine")
def test_embeddings_match_the_torch_model(tmp_path):
    """THE gate for the numbers: cosine >= 0.999 against the checkpoint this
    artefact was exported from, on real library audio.

    A drifting audio tower would place newly ingested tracks in a subtly
    different space from the ones already indexed. They would still return
    results, just the wrong ones -- precisely the failure a smoke test cannot
    see, which is why this compares vectors and not shapes.
    """
    tracks = sorted(p for p in LIBRARY.iterdir()
                    if p.suffix.lower() in {".wav", ".mp3", ".flac"})[:3]
    if len(tracks) < 3:
        pytest.skip("fewer than three usable tracks in the library")

    directory = _artefact_dir()
    onnx_name, params_name = music_models.filenames()
    import shutil as _shutil
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in (onnx_name, params_name):
        _shutil.copy2(directory / name, cache / name)

    from unittest import mock
    with mock.patch.object(sidecar, "cache_dir", lambda: cache), \
            mock.patch.object(sidecar, "model_ready", lambda key="": True):
        ours = [sidecar.embed_file(track)["embedding"] for track in tracks]

    script = (
        "import json,sys,numpy as np;"
        "sys.path.insert(0, r'%s');" % str(INDEXER_DIR) +
        "sys.path.insert(0, r'%s');" % str(REPO_ROOT / "music" / "web") +
        "from music_index import audio, clap_model;"
        "clap = clap_model.Clap();"
        "out=[];\n"
        "for p in json.loads(sys.argv[1]):\n"
        "    y = audio.decode(p)\n"
        "    emb = clap.embed_audio([w[0] for w in audio.windows(y)])\n"
        "    v = emb.mean(axis=0); v = v / np.linalg.norm(v)\n"
        "    out.append(v.tolist())\n"
        "print(json.dumps(out))"
    )
    proc = subprocess.run([str(TORCH_VENV), "-c", script,
                           json.dumps([str(p) for p in tracks])],
                          capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-2000:]
    theirs = [np.array(v, dtype=np.float32) for v in json.loads(proc.stdout)]

    for track, mine, ref in zip(tracks, ours, theirs):
        cosine = float(np.dot(mine, ref))
        assert cosine >= 0.999, f"{track.name}: cosine {cosine:.6f} vs torch"
