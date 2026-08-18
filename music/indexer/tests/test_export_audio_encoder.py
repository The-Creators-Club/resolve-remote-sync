"""The exporter's torch-free half.

The export itself needs torch, a GPU rig and a 600 MB checkpoint, so it is not
a CI surface. What IS testable without any of that is the part that decides
what gets published: the params it writes (which drive `mel_numpy` on every
editor machine), the pooling it verifies against, and the refusal that stops a
drifting artefact from reaching the feed.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mel_numpy                                                  # noqa: E402
import music_models                                               # noqa: E402
import export_audio_encoder as exporter                           # noqa: E402

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'clap_audio_params.json'


def _fake_feature_extractor():
    """A stand-in shaped like ClapFeatureExtractor, with the checkpoint's
    numbers -- the fixture params are what the real one produced."""
    f = json.loads(FIXTURE.read_text(encoding='utf-8'))['features']

    # A named class, not SimpleNamespace: feature_params records
    # type(fe).__name__ in the params, and the fixture was written by the real
    # extractor.
    class ClapFeatureExtractor(SimpleNamespace):
        pass

    return ClapFeatureExtractor(
        sampling_rate=f['sampling_rate'], max_length_s=f['max_length_s'],
        nb_max_samples=f['nb_max_samples'], feature_size=f['feature_size'],
        fft_window_size=f['fft_window_size'], hop_length=f['hop_length'],
        frequency_min=f['frequency_min'], frequency_max=f['frequency_max'],
        padding=f['padding'], padding_value=f['padding_value'],
        truncation=f['truncation'])


def _fake_model(enable_fusion=False):
    return SimpleNamespace(config=SimpleNamespace(
        projection_dim=512,
        audio_config=SimpleNamespace(enable_fusion=enable_fusion)))


def test_params_reproduce_the_published_fixture():
    """Byte-for-byte on everything except the timestamp: this is the contract
    between the exporter and every companion that reads the params file."""
    got = exporter.feature_params('laion/larger_clap_music_and_speech',
                                  _fake_feature_extractor(), _fake_model(),
                                  exporter.OPSET)
    want = json.loads(FIXTURE.read_text(encoding='utf-8'))
    got.pop('exported_at'), want.pop('exported_at')
    assert got == want


def test_params_are_readable_by_the_thing_that_consumes_them():
    got = exporter.feature_params('laion/larger_clap_music_and_speech',
                                  _fake_feature_extractor(), _fake_model(),
                                  exporter.OPSET)
    params = mel_numpy.MelParams(got)
    assert params.n_frames == got['graph']['input_shape'][2] == 1001
    assert params.embed_dim == got['embedding']['dim']
    # the artefact the params claim to belong to is the one in the catalogue
    assert got['artefact'] == music_models.filenames()[0]


def test_pooling_is_analyse_ones_pooling():
    """mean of the per-window unit vectors, then renormalise -- the same three
    lines as index_music.analyse_one, which is why the params say so."""
    rng = np.random.default_rng(1)
    v = rng.standard_normal((6, 8)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    got = exporter.pooled(v, 3)
    assert got.shape == (2, 8)
    assert np.allclose(np.linalg.norm(got, axis=1), 1.0)
    want = v[:3].mean(axis=0)
    assert np.allclose(got[0], want / np.linalg.norm(want))


def test_compare_refuses_below_the_threshold():
    a = np.eye(3, dtype=np.float32)
    b = np.roll(a, 1, axis=1)                     # orthogonal: cosine 0
    with pytest.raises(SystemExit) as exc:
        exporter.compare('per window', a, b, verbose=False)
    assert 'min cosine' in str(exc.value)
    # ... and reports rather than refuses when the caller says it is advisory
    lo, mean = exporter.compare('fp16', a, b, fatal=False, verbose=False)
    assert (lo, mean) == (0.0, 0.0)


def test_compare_accepts_an_exact_match():
    a = np.eye(4, dtype=np.float32)
    lo, mean = exporter.compare('per window', a, a.copy(), verbose=False)
    assert lo == pytest.approx(1.0) and mean == pytest.approx(1.0)


def test_synthetic_windows_are_deterministic_and_the_right_length():
    a, note = exporter.synthetic_windows(4)
    b, _ = exporter.synthetic_windows(4)
    assert len(a) == 4 and 'synthetic' in note
    assert all(chunk.size == 480000 for _, chunk in a)
    assert all(np.array_equal(x[1], y[1]) for x, y in zip(a, b))


def test_library_windows_says_why_rather_than_raising(tmp_path):
    # walk=False: on a machine that HAS the library mounted the fallback would
    # (correctly) return real windows, and this test is about the refusal.
    got, note = exporter.library_windows(2, 2, db_path=tmp_path / 'nope.db',
                                         walk=False)
    assert got == []
    assert 'no index at' in note


def test_share_windows_is_silent_when_the_library_is_not_mounted(tmp_path):
    got, note = exporter.share_windows(2, 2, root=tmp_path / 'not-mounted')
    assert got == []
    assert 'no music library at' in note
    got, note = exporter.share_windows(2, 2, root=tmp_path)
    assert got == [] and 'no audio files' in note


def test_artefact_dir_is_overridable(monkeypatch, tmp_path):
    monkeypatch.setenv('MUSIC_AUDIO_ENCODER_DIR', str(tmp_path / 'elsewhere'))
    assert exporter.artefact_dir() == tmp_path / 'elsewhere'
    monkeypatch.delenv('MUSIC_AUDIO_ENCODER_DIR')
    assert exporter.artefact_dir().name == 'audio_encoder'


def test_catalogue_block_quotes_the_real_files(tmp_path):
    onnx, params = music_models.filenames()
    (tmp_path / onnx).write_bytes(b'weights')
    (tmp_path / params).write_bytes(b'{}')
    block = exporter.catalogue_block({'onnx': tmp_path / onnx,
                                      'params_path': tmp_path / params})
    assert onnx in block and params in block
    assert '"size_bytes"' in block and str(len(b'weights')) in block
