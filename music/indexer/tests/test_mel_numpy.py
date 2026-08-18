"""`mel_numpy` is the companion's half of the CLAP audio embedding.

Two kinds of test here, and the split is the point:

* the numpy-only ones run everywhere (system interpreter, no torch), and pin
  the shapes, the padding/truncation rules, the refusals, and a GOLDEN
  log-mel — so a rig with no torch still finds out that the front end moved;
* `test_bit_parity_with_transformers` is the real gate and skips loudly when
  transformers is absent, because "close enough" is not a standard a feature
  extractor can be held to: an embedding computed from a slightly different
  spectrogram is a plausible vector for the wrong audio, and no cosine
  threshold downstream would catch it.

    cd music/indexer && python -m pytest tests -q
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mel_numpy                                                  # noqa: E402

PARAMS_PATH = Path(__file__).resolve().parent / 'fixtures' / 'clap_audio_params.json'

# The exact sample the exporter's own run measured (2026-08-18), taken from a
# deterministic signal so any machine can reproduce it: mel[::200, ::16] of
# 0.25 * default_rng(20260818).standard_normal(480000). Identical under numpy
# 2.2.6 and 2.4.4; the tolerance below is for a future numpy whose FFT differs
# in the last bits, not for a change in what this module computes.
GOLDEN_SEED = 20260818
GOLDEN = [
    [-19.03274917602539, -9.025296211242676, -6.374568462371826, -5.570005893707275],
    [-8.834033966064453, 1.2019226551055908, -0.5166364312171936, -2.351816415786743],
    [-4.5605244636535645, -10.886054992675781, -3.8859047889709473, -3.4379539489746094],
    [0.34138742089271545, -12.451456069946289, 0.9995208978652954, -1.4109481573104858],
    [1.0303517580032349, -1.8500443696975708, -5.685239315032959, -1.76229989528656],
    [-9.880579948425293, -4.3946428298950195, -13.181050300598145, -5.907430171966553],
]


@pytest.fixture(scope='module')
def raw_params():
    return json.loads(PARAMS_PATH.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def params(raw_params):
    return mel_numpy.MelParams(raw_params)


@pytest.fixture(scope='module')
def extractor(params):
    return mel_numpy.MelExtractor(params)


# --------------------------------------------------------------- the params

def test_fixture_matches_the_checkpoints_own_numbers(params):
    """These are laion CLAP's `preprocessor_config.json`, not our preferences.

    If this fails, an artefact was exported from a checkpoint with different
    feature geometry -- which is a model change, and needs a version bump in
    music_models.py, not a new expectation here.
    """
    assert (params.sample_rate, params.window_seconds) == (48000, 10.0)
    assert (params.n_samples, params.n_frames, params.n_mels) == (480000, 1001, 64)
    assert (params.n_fft, params.hop_length) == (1024, 480)
    assert (params.fmin, params.fmax) == (50.0, 14000.0)
    assert (params.mel_scale, params.mel_norm) == ('slaney', 'slaney')
    assert (params.log_mel, params.power) == ('dB', 2.0)
    assert (params.padding, params.truncation_rule) == ('repeatpad', 'head')
    assert params.embed_dim == 512


def test_a_newer_params_file_is_refused_not_guessed(raw_params):
    newer = dict(raw_params, params_version=mel_numpy.PARAMS_VERSION + 1)
    with pytest.raises(mel_numpy.ParamsError) as exc:
        mel_numpy.MelParams(newer)
    assert 'params_version' in str(exc.value)


def test_a_missing_params_file_names_itself(tmp_path):
    with pytest.raises(mel_numpy.ParamsError) as exc:
        mel_numpy.MelParams.load(tmp_path / 'nope.json')
    assert 'nope.json' in str(exc.value)


def test_frames_for_matches_the_recorded_frame_count(params):
    assert params.frames_for(params.n_samples) == params.n_frames


# ---------------------------------------------------------- the primitives

def test_filter_bank_geometry(extractor, params):
    assert extractor.filters.shape == ((params.n_fft >> 1) + 1, params.n_mels)
    assert extractor.filters.dtype == np.float64
    assert (extractor.filters >= 0).all()
    # every mel filter carries some weight: an all-zero row means the bank is
    # finer than the FFT resolution, which transformers only warns about.
    assert (extractor.filters.max(axis=0) > 0).all()


def test_hann_window_is_periodic_not_symmetric():
    w = mel_numpy.hann_window(8, periodic=True)
    assert w.size == 8
    assert w[0] == 0.0
    assert not np.allclose(w, w[::-1])          # symmetric hann would be
    assert np.allclose(w, np.hanning(9)[:-1])


def test_power_to_db_clips_at_the_floor():
    got = mel_numpy.power_to_db(np.array([1e-20, 1.0, 100.0]))
    assert got[0] == pytest.approx(-100.0)
    assert got[1] == pytest.approx(0.0)
    assert got[2] == pytest.approx(20.0)


def test_mel_scale_round_trip():
    hz = np.array([50.0, 440.0, 1000.0, 14000.0])
    back = mel_numpy.mel_to_hertz(mel_numpy.hertz_to_mel(hz, 'slaney'), 'slaney')
    assert np.allclose(back, hz)


# ------------------------------------------------------------ fitting rules

def test_exact_length_window_is_untouched(extractor, params):
    y = np.linspace(-1, 1, params.n_samples).astype(np.float32)
    assert np.array_equal(extractor.fit_window(y), y.astype(np.float64))


def test_short_input_is_repeated_then_zero_padded(extractor, params):
    n = params.n_samples // 3 + 7            # repeats twice, then pads
    y = np.arange(n, dtype=np.float32) + 1.0
    got = extractor.fit_window(y)
    assert got.size == params.n_samples
    assert np.array_equal(got[:n], y)
    assert np.array_equal(got[n:2 * n], y)   # repeatpad tiles whole copies
    assert (got[3 * n:] == 0).all()          # ... and zero-fills the remainder


def test_long_input_is_cut_from_the_head_and_is_reproducible(extractor, params):
    """HF's rand_trunc picks a random offset; a fleet cannot dedupe, resume or
    verify an embedding that changes between runs of the same file."""
    y = np.arange(params.n_samples * 2, dtype=np.float32)
    first, second = extractor.fit_window(y), extractor.fit_window(y)
    assert np.array_equal(first, second)
    assert np.array_equal(first, y[:params.n_samples].astype(np.float64))


def test_an_unknown_truncation_rule_refuses(raw_params):
    bad = json.loads(json.dumps(raw_params))
    bad['features']['truncation_rule'] = 'random'
    mx = mel_numpy.MelExtractor(mel_numpy.MelParams(bad))
    with pytest.raises(mel_numpy.ParamsError):
        mx.fit_window(np.zeros(bad['features']['nb_max_samples'] + 1, np.float32))


# -------------------------------------------------------------- the mel/API

def test_log_mel_shape_and_dtype(extractor, params):
    mel = extractor.log_mel(np.zeros(params.n_samples, np.float32))
    assert mel.shape == (params.n_frames, params.n_mels)
    assert mel.dtype == np.float32


def test_log_mel_golden(extractor, params):
    """The values, not just the shape -- the whole point of the module."""
    rng = np.random.default_rng(GOLDEN_SEED)
    y = (0.25 * rng.standard_normal(params.n_samples)).astype(np.float32)
    mel = extractor.log_mel(y)
    assert np.allclose(mel[::200, ::16], np.array(GOLDEN, dtype=np.float32),
                       atol=1e-4)


def test_input_features_are_what_the_graph_declares(extractor, params):
    chunks = [np.zeros(params.n_samples, np.float32) for _ in range(3)]
    feats = extractor.input_features(chunks)
    assert feats.shape == (3, 1, params.n_frames, params.n_mels)
    assert feats.dtype == np.float32
    empty = extractor.input_features([])
    assert empty.shape == (0, 1, params.n_frames, params.n_mels)


def test_is_longer_is_always_false(extractor):
    flags = extractor.is_longer(4)
    assert flags.shape == (4, 1)
    assert not flags.any()


# ---------------------------------------------------------- the real gate

def _parity_windows(n_windows=20):
    """20 windows of real library audio if this machine can reach it, else
    deterministic synthetic ones. -> (chunks, note)."""
    try:
        import export_audio_encoder as exporter
    except Exception as exc:                                      # noqa: BLE001
        pytest.skip(f'export_audio_encoder is not importable here: {exc}')
    per_track = 4
    got, note = exporter.library_windows(n_windows // per_track, per_track)
    if not got:
        got, note = exporter.synthetic_windows(n_windows)
    return [c[1] for c in got[:n_windows]], note


@pytest.mark.skipif(
    __import__('importlib').util.find_spec('transformers') is None,
    reason='transformers is not installed here (base-rig-only); the bit-parity '
           'gate needs the checkpoint\'s own ClapFeatureExtractor to compare to')
def test_bit_parity_with_transformers(extractor, params, raw_params):
    from transformers import ClapFeatureExtractor

    fe = ClapFeatureExtractor.from_pretrained(raw_params['model'])
    # The fixture is a copy of a published params file; if the checkpoint has
    # moved under it, everything below would be comparing the wrong things.
    assert fe.sampling_rate == params.sample_rate
    assert fe.hop_length == params.hop_length
    assert fe.fft_window_size == params.n_fft
    assert fe.feature_size == params.n_mels
    assert np.array_equal(extractor.filters, fe.mel_filters_slaney)

    chunks, note = _parity_windows()
    ours = extractor.input_features(chunks)
    ref = np.asarray(fe(chunks, sampling_rate=fe.sampling_rate,
                        return_tensors='np')['input_features'], dtype=np.float32)
    assert ours.shape == ref.shape, note
    assert np.array_equal(ours, ref), (
        f'mel_numpy diverged from ClapFeatureExtractor on {note}: max abs diff '
        f'{np.abs(ours - ref).max():g}')
