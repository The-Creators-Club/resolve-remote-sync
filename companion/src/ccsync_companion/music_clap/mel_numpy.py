# VENDORED VERBATIM from music/indexer/mel_numpy.py -- DO NOT EDIT HERE.
# Edit the indexer's copy and re-copy it in BELOW THE MARKER LINE at the end of
# this header; everything under that line is byte-identical to the source on
# purpose, so the two trees can be compared mechanically -- and they are:
# tools/release.ps1 (and tools/release_macos.sh) strip this header, byte-compare
# the rest against the source and REFUSE to build on a mismatch, and
# server/tests/test_cross_component.py pins the same comparison in the suites.
# Same mechanism as ccsync_companion/broll_vlm/ (2026-08-18) and
# ccsync_companion/ytdl_common.py (2026-08-14).
#
# Why a copy and not an import (docs/MUSIC_INGEST_PLAN.md step 3): the
# companion is a frozen, windowed PyInstaller build and `music_index` reaches
# torch, librosa and transformers -- gigabytes -- for two modules that between
# them need nothing but the stdlib and numpy. The MODULE NAMES are unchanged so
# nothing inside them has to be rewritten.
#
# What drift here would cost is not a crash: a mel that differs in its last
# bits produces a plausible embedding of the wrong audio, in the wrong place in
# a 512-dimensional space that every cosine in the library is measured against.
# Nothing downstream can detect it.
#
# The marker is the LAST line of this header and appears exactly once (both the
# gate and the test refuse an absent or ambiguous marker rather than skipping).
# Nothing but the source file's own bytes may follow it.
# --- vendored content below, byte-identical ---
"""CLAP's log-mel front end, in numpy alone. NO torch, NO transformers.

The companion has to produce `input_features` for the exported CLAP audio
tower (`export_audio_encoder.py`) and it cannot carry transformers to do it:
`ClapFeatureExtractor` lives in a 98 MB package that imports torch. So the
feature extraction is reimplemented here from the model's own
`preprocessor_config.json`, driven entirely by the params JSON the exporter
writes beside the ONNX -- this module never hardcodes a number that belongs
to a model.

**This file is the thing the companion sidecar vendors** (WP 3 of
`docs/MUSIC_INGEST_PLAN.md`), so it stays stdlib + numpy and imports nothing
from `music_index`. `tests/test_mel_numpy.py` holds it to BIT parity (not
"close enough") against `ClapFeatureExtractor` on 20 real windows when torch
is installed, and to a stored golden vector when it is not: an embedding
computed from a subtly different mel is a plausible vector for the wrong
audio, which no cosine threshold downstream would catch.

Parity is achieved by mirroring `transformers.audio_utils.spectrogram` /
`mel_filter_bank` / `power_to_db` step for step, including the two places a
reimplementation naturally diverges:

  * the per-frame FFT result is stored into a **complex64** buffer before the
    magnitude is taken (transformers allocates `np.empty(..., np.complex64)`),
    so the whole thing is not simply float64 end to end; and
  * the mel projection is `mel_filters.T @ power_spectrogram` -- that operand
    order, on float64, is what fixes the last bits.

Both are checked by the parity test rather than trusted.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Bumped when the params JSON gains a key this module needs. The exporter
# writes it; a sidecar that reads a newer params file than it understands must
# refuse rather than guess (params_version below).
PARAMS_VERSION = 1


class ParamsError(ValueError):
    """The params JSON is missing, unreadable, or of a version this cannot run."""


class MelParams:
    """The feature-extractor half of `music-clap-audio-<ver>.params.json`.

    Every field is read from the file; the defaults below only exist so a
    hand-written params file for a *different* CLAP checkpoint stays readable,
    and they are the HF defaults for `ClapFeatureExtractor`, not this
    library's values.
    """

    def __init__(self, data: dict):
        version = int(data.get("params_version", 0))
        if version != PARAMS_VERSION:
            raise ParamsError(
                f"params_version {version} is not {PARAMS_VERSION}: this build of "
                "mel_numpy cannot reproduce that artefact's features. Update the "
                "sidecar rather than embedding audio with the wrong front end."
            )
        f = data.get("features") or {}
        self.raw = data
        self.model = str(data.get("model", ""))
        self.sample_rate = int(f.get("sampling_rate", 48000))
        self.window_seconds = float(f.get("max_length_s", 10))
        self.n_samples = int(f.get("nb_max_samples",
                                   round(self.sample_rate * self.window_seconds)))
        self.n_mels = int(f.get("feature_size", 64))
        self.n_fft = int(f.get("fft_window_size", 1024))
        self.hop_length = int(f.get("hop_length", 480))
        self.fmin = float(f.get("frequency_min", 0.0))
        self.fmax = float(f.get("frequency_max", 14000.0))
        self.padding = str(f.get("padding", "repeatpad"))
        self.padding_value = float(f.get("padding_value", 0.0))
        self.mel_scale = str(f.get("mel_scale", "slaney"))
        self.mel_norm = f.get("mel_norm", "slaney")
        self.mel_floor = float(f.get("mel_floor", 1e-10))
        self.log_mel = str(f.get("log_mel", "dB"))
        self.log_min_value = float(f.get("log_min_value", 1e-10))
        self.log_reference = float(f.get("log_reference", 1.0))
        self.power = float(f.get("power", 2.0))
        self.center = bool(f.get("center", True))
        self.pad_mode = str(f.get("pad_mode", "reflect"))
        self.window = str(f.get("window", "hann"))
        self.window_periodic = bool(f.get("window_periodic", True))
        self.truncation_rule = str(f.get("truncation_rule", "head"))
        self.n_frames = int(f.get("n_frames", 0)) or self.frames_for(self.n_samples)
        self.embed_dim = int((data.get("embedding") or {}).get("dim", 512))

    @classmethod
    def load(cls, path):
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ParamsError(f"no CLAP audio params at {path}: {exc}") from exc
        except ValueError as exc:
            raise ParamsError(f"CLAP audio params at {path} are not JSON: {exc}") from exc
        return cls(data)

    def frames_for(self, n_samples: int) -> int:
        """How many STFT frames `n_samples` produces under these params."""
        padded = n_samples + (2 * (self.n_fft // 2) if self.center else 0)
        return int(1 + np.floor((padded - self.n_fft) / self.hop_length))


# --------------------------------------------------------------- primitives
# Mirrors of transformers.audio_utils. Kept as free functions taking explicit
# numbers so the parity test can drive them directly with the HF values.


def hertz_to_mel(freq, mel_scale="slaney"):
    if mel_scale == "htk":
        return 2595.0 * np.log10(1.0 + (np.asarray(freq, dtype=np.float64) / 700.0))
    if mel_scale != "slaney":
        raise ValueError(f'mel_scale must be "slaney" or "htk", not {mel_scale!r}')
    min_log_hertz, min_log_mel = 1000.0, 15.0
    logstep = 27.0 / np.log(6.4)
    freq = np.asarray(freq, dtype=np.float64)
    mels = 3.0 * freq / 200.0
    if freq.ndim:
        log_region = freq >= min_log_hertz
        mels[log_region] = min_log_mel + np.log(freq[log_region] / min_log_hertz) * logstep
    elif freq >= min_log_hertz:
        mels = min_log_mel + np.log(freq / min_log_hertz) * logstep
    return mels


def mel_to_hertz(mels, mel_scale="slaney"):
    if mel_scale == "htk":
        return 700.0 * (np.power(10, np.asarray(mels, dtype=np.float64) / 2595.0) - 1.0)
    if mel_scale != "slaney":
        raise ValueError(f'mel_scale must be "slaney" or "htk", not {mel_scale!r}')
    min_log_hertz, min_log_mel = 1000.0, 15.0
    logstep = np.log(6.4) / 27.0
    mels = np.asarray(mels, dtype=np.float64)
    freq = 200.0 * mels / 3.0
    if mels.ndim:
        log_region = mels >= min_log_mel
        freq[log_region] = min_log_hertz * np.exp(logstep * (mels[log_region] - min_log_mel))
    elif mels >= min_log_mel:
        freq = min_log_hertz * np.exp(logstep * (mels - min_log_mel))
    return freq


def mel_filter_bank(n_freq_bins, n_mels, fmin, fmax, sample_rate,
                    norm="slaney", mel_scale="slaney"):
    """(n_freq_bins, n_mels) triangular filters. Slaney scale + Slaney norm is
    what CLAP's `rand_trunc` path uses (`mel_filters_slaney`); the `fusion`
    path's HTK/no-norm bank is unreachable here because the tower is exported
    without fusion."""
    mel_min = hertz_to_mel(float(fmin), mel_scale)
    mel_max = hertz_to_mel(float(fmax), mel_scale)
    mel_freqs = np.linspace(mel_min, mel_max, n_mels + 2)
    filter_freqs = mel_to_hertz(mel_freqs, mel_scale)
    fft_freqs = np.linspace(0, sample_rate // 2, n_freq_bins)

    filter_diff = np.diff(filter_freqs)
    slopes = np.expand_dims(filter_freqs, 0) - np.expand_dims(fft_freqs, 1)
    down = -slopes[:, :-2] / filter_diff[:-1]
    up = slopes[:, 2:] / filter_diff[1:]
    filters = np.maximum(np.zeros(1), np.minimum(down, up))

    if norm == "slaney":
        enorm = 2.0 / (filter_freqs[2:n_mels + 2] - filter_freqs[:n_mels])
        filters *= np.expand_dims(enorm, 0)
    elif norm is not None:
        raise ValueError('norm must be None or "slaney"')
    return filters


def hann_window(length, periodic=True):
    """np.hanning is symmetric; CLAP (like torch.hann_window) wants periodic."""
    n = length + 1 if periodic else length
    w = np.hanning(n)
    return w[:-1] if periodic else w


def power_to_db(spec, reference=1.0, min_value=1e-10):
    if reference <= 0.0 or min_value <= 0.0:
        raise ValueError("reference and min_value must be greater than zero")
    reference = max(min_value, reference)
    spec = np.clip(spec, a_min=min_value, a_max=None)
    return 10.0 * (np.log10(spec) - np.log10(reference))


# ------------------------------------------------------------------ the mel

class MelExtractor:
    """log-mel spectrograms for one set of params. Filters built once.

    Thread-safety: `log_mel`/`input_features` allocate everything they touch,
    so one extractor is safe to share across the sidecar's worker threads.
    """

    def __init__(self, params: MelParams):
        self.p = params
        self.n_freq_bins = (params.n_fft >> 1) + 1
        self.filters = mel_filter_bank(
            self.n_freq_bins, params.n_mels, params.fmin, params.fmax,
            params.sample_rate, norm=params.mel_norm, mel_scale=params.mel_scale)
        self.window = hann_window(params.n_fft, params.window_periodic)
        if params.window != "hann":
            raise ParamsError(f"unsupported window {params.window!r}")

    @classmethod
    def from_params_file(cls, path):
        return cls(MelParams.load(path))

    # ---------------------------------------------------------------- fitting
    def fit_window(self, waveform):
        """One analysis window of exactly `n_samples`, per the params' rules.

        Short input is `repeatpad`ed (tile whole copies, then zero-pad), which
        is what `ClapFeatureExtractor` does. Long input is cut from the HEAD,
        not from a random offset: HF's `rand_trunc` picks `np.random.randint`,
        and an embedding that changes between two runs of the same file is not
        something a fleet can dedupe, resume, or verify. The pipeline never
        reaches this branch anyway -- `music_index.audio.windows` hands over
        exact 10 s windows -- and `truncation_rule` in the params JSON records
        which rule the artefact was verified under.
        """
        p = self.p
        y = np.asarray(waveform, dtype=np.float64).reshape(-1)
        n = p.n_samples
        if y.size > n:
            if p.truncation_rule != "head":
                raise ParamsError(f"unsupported truncation_rule {p.truncation_rule!r}")
            return y[:n]
        if y.size < n:
            if p.padding == "repeatpad":
                repeats = int(n / y.size) if y.size else 0
                if repeats > 1:
                    y = np.tile(y, repeats)
            elif p.padding == "repeat":
                repeats = int(n / y.size) if y.size else 0
                y = np.tile(y, repeats + 1)[:n]
            elif p.padding != "pad":
                raise ParamsError(f"unsupported padding {p.padding!r}")
            if y.size < n:
                y = np.pad(y, (0, n - y.size), mode="constant",
                           constant_values=p.padding_value)
        return y

    # ------------------------------------------------------------------ stft
    def log_mel(self, waveform):
        """-> (n_frames, n_mels) float32, bit-identical to ClapFeatureExtractor.

        `waveform` is fitted to the window length first.
        """
        p = self.p
        y = self.fit_window(waveform)
        if p.center:
            pad = int(p.n_fft // 2)
            y = np.pad(y, [(pad, pad)], mode=p.pad_mode)
        window = self.window.astype(np.float64)

        n_frames = int(1 + np.floor((y.size - p.n_fft) / p.hop_length))
        # A (n_frames, n_fft) view, not a copy, then one batched rfft: numpy
        # transforms each row independently with the same pocketfft plan the
        # per-frame loop in transformers uses, so this is a speed change and
        # not a numerical one -- pinned by the bit-parity test.
        frames = np.lib.stride_tricks.as_strided(
            y, shape=(n_frames, p.n_fft),
            strides=(y.strides[0] * p.hop_length, y.strides[0]),
            writeable=False)
        buf = frames * window

        # complex64 on purpose: transformers writes each frame's FFT into a
        # complex64 array, and rounding there is visible in the last bits of
        # the dB values. Dropping this is the single easiest way to be
        # "obviously equivalent" and not bit-equal.
        spec = np.asarray(np.fft.rfft(buf, n=p.n_fft, axis=-1), dtype=np.complex64)
        spec = np.abs(spec, dtype=np.float64) ** p.power
        spec = spec.T

        spec = np.maximum(p.mel_floor, np.dot(self.filters.T, spec))
        if p.log_mel == "dB":
            spec = power_to_db(spec, p.log_reference, p.log_min_value)
        elif p.log_mel == "log":
            spec = np.log(spec)
        elif p.log_mel == "log10":
            spec = np.log10(spec)
        elif p.log_mel:
            raise ParamsError(f"unsupported log_mel {p.log_mel!r}")
        return np.asarray(spec, dtype=np.float32).T

    # ----------------------------------------------------------- model input
    def input_features(self, chunks):
        """list of 1-D waveforms -> (N, 1, n_frames, n_mels) float32.

        The channel axis of 1 is CLAP's own: the HTSAT reshapes the mel into an
        image, and the unfused model takes exactly one mel per clip.
        """
        chunks = list(chunks)
        if not chunks:
            return np.zeros((0, 1, self.p.n_frames, self.p.n_mels), dtype=np.float32)
        mels = [self.log_mel(c) for c in chunks]
        return np.stack(mels, axis=0)[:, None, :, :]

    def is_longer(self, n):
        """The companion always feeds exactly one window, so `is_longer` is
        always False -- but the graph takes the input, so it must be fed. It is
        only read by the fusion branch, which this artefact does not contain."""
        return np.zeros((int(n), 1), dtype=bool)
