"""Audio decoding via ffmpeg, and window selection for CLAP.

ffmpeg is used rather than librosa/audioread for loading because the library
mixes wav/mp3/flac/aac/ogg and lives on an SMB share; one subprocess that
outputs raw float32 is both faster and far less fragile than the Python
decoders.
"""
import json
import subprocess
import numpy as np

from music_index import config


def probe(path):
    out = subprocess.run(
        [config.FFPROBE, '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_streams', str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    j = json.loads(out.stdout.decode('utf-8', errors='replace'))
    fmt = j.get('format', {})
    aud = next((s for s in j.get('streams', []) if s.get('codec_type') == 'audio'), {})
    return {
        'duration': float(fmt.get('duration', 0) or 0),
        'samplerate': int(aud.get('sample_rate', 0) or 0),
        'channels': int(aud.get('channels', 0) or 0),
        'codec': aud.get('codec_name', ''),
    }


def decode(path, sr=config.SAMPLE_RATE, max_seconds=None):
    """Decode to mono float32 at `sr`. Returns an empty array on failure."""
    cmd = [config.FFMPEG, '-v', 'quiet', '-i', str(path)]
    if max_seconds:
        cmd += ['-t', str(max_seconds)]
    cmd += ['-f', 'f32le', '-acodec', 'pcm_f32le', '-ac', '1', '-ar', str(sr), '-']
    out = subprocess.run(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, timeout=900).stdout
    a = np.frombuffer(out, dtype=np.float32)
    # guard against NaN/Inf from damaged files -- these poison the embedding
    return np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0).copy()


PEAK_BUCKETS = 900


def peaks(samples, n=PEAK_BUCKETS):
    """Waveform overview as n uint8 values.

    Peak (not RMS) per bucket, so transients stay visible at overview scale,
    and normalised to the track's own maximum so a quiet ambient bed still
    draws a readable shape rather than a flat line.
    """
    if samples is None or samples.size == 0:
        return b''
    a = np.abs(samples)
    if a.size < n:
        a = np.pad(a, (0, n - a.size))
    # trim the tail that doesn't divide evenly, then max within each bucket
    per = a.size // n
    a = a[:per * n].reshape(n, per).max(axis=1)
    top = float(a.max())
    if top <= 0:
        return bytes(n)
    return (np.clip(a / top, 0, 1) * 255).astype(np.uint8).tobytes()


def peaks_from_file(path, n=PEAK_BUCKETS):
    """Decode cheaply (8 kHz mono) purely to draw a waveform."""
    return peaks(decode(path, sr=8000), n)


def windows(samples, sr=config.SAMPLE_RATE,
            window_sec=config.WINDOW_SEC, max_windows=config.MAX_WINDOWS):
    """Evenly spaced analysis windows across the track.

    Trims 2% from each end so that fade-ins, count-ins and trailing silence do
    not produce near-empty embeddings that drag the track mean toward "quiet".
    Short tracks yield a single zero-padded window.
    """
    n = samples.size
    w = int(window_sec * sr)
    if n == 0:
        return []
    if n <= w:
        padded = np.zeros(w, dtype=np.float32)
        padded[:n] = samples
        return [(padded, 0.0, n / sr)]

    margin = int(n * 0.02)
    lo, hi = margin, n - margin - w
    if hi <= lo:
        lo, hi = 0, n - w

    count = int(min(max_windows, max(1, (hi - lo) // w + 1)))
    starts = (np.linspace(lo, hi, count).astype(int) if count > 1
              else np.array([(lo + hi) // 2], dtype=int))

    out = []
    for s in starts:
        chunk = samples[s:s + w]
        if chunk.size < w:                       # numerical edge case
            padded = np.zeros(w, dtype=np.float32)
            padded[:chunk.size] = chunk
            chunk = padded
        out.append((chunk, s / sr, (s + w) / sr))
    return out
