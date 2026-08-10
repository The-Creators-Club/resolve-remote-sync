"""Classical DSP features: tempo, key, loudness.

CLAP gives semantics but has no notion of tempo or key, and an editor cutting
to picture needs both. Every extractor degrades to None rather than raising, so
one odd file cannot stall an index run.
"""
import warnings
import numpy as np

from music_index import config

warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)

# Krumhansl-Schmuckler key profiles
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def tempo(y, sr):
    try:
        import librosa
        t = librosa.beat.beat_track(y=y, sr=sr)[0]
        t = float(np.atleast_1d(t)[0])
        if not np.isfinite(t) or t <= 0:
            return None
        # librosa can land on a half/double-time reading; fold into a musical range
        while t < 60:
            t *= 2
        while t > 190:
            t /= 2
        return round(t, 1)
    except Exception:
        return None


def key(y, sr):
    """Estimated key via correlation of the mean chroma with KS profiles.

    Returns (name, confidence) where confidence is the margin between the best
    and second-best candidate -- low margin means "ambiguous", which is common
    and honest for ambient and drone material.
    """
    try:
        import librosa
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        v = chroma.mean(axis=1)
        if not np.isfinite(v).all() or v.sum() <= 0:
            return None, None
        v = (v - v.mean()) / (v.std() or 1)

        scores = []
        for i in range(12):
            for prof, mode in ((_MAJOR, 'major'), (_MINOR, 'minor')):
                p = np.roll(prof, i)
                p = (p - p.mean()) / (p.std() or 1)
                scores.append((float(np.dot(v, p) / 12), f'{_NOTES[i]} {mode}'))
        scores.sort(reverse=True)
        best, second = scores[0], scores[1]
        conf = round(max(0.0, best[0] - second[0]), 4)
        return best[1], conf
    except Exception:
        return None, None


def loudness(y, sr):
    """(integrated LUFS, true-ish peak dBFS)."""
    lufs = peak = None
    try:
        import pyloudnorm as pyln
        if y.size > sr * 0.5:
            meter = pyln.Meter(sr)
            val = meter.integrated_loudness(y.astype(np.float64))
            if np.isfinite(val):
                lufs = round(float(val), 2)
    except Exception:
        pass
    try:
        pk = float(np.max(np.abs(y))) if y.size else 0.0
        peak = round(20 * np.log10(pk), 2) if pk > 0 else -120.0
    except Exception:
        pass
    return lufs, peak


def extract(y48, sr48=config.SAMPLE_RATE, max_seconds=360):
    """All DSP features from the 48kHz signal already decoded for CLAP.

    Resampled to 22.05k because librosa's beat and chroma models are tuned
    there, and capped at `max_seconds` so a 14-minute ambient bed does not
    dominate the run.
    """
    out = {'bpm': None, 'music_key': None, 'key_conf': None,
           'lufs': None, 'peak_db': None}
    if y48 is None or y48.size == 0:
        return out
    try:
        import librosa
        y = y48[:int(sr48 * max_seconds)]
        ya = librosa.resample(y, orig_sr=sr48, target_sr=config.ANALYSIS_SR)
        out['bpm'] = tempo(ya, config.ANALYSIS_SR)
        k, c = key(ya, config.ANALYSIS_SR)
        out['music_key'], out['key_conf'] = k, c
        out['lufs'], out['peak_db'] = loudness(y, sr48)
    except Exception:
        pass
    return out
