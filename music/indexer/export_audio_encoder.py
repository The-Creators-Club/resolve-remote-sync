"""Export CLAP's AUDIO half as a self-contained artefact. BASE RIG ONLY.

    python export_audio_encoder.py                    # -> music/web/data/audio_encoder/
    python export_audio_encoder.py --check            # verify an existing artefact
    python export_audio_encoder.py --tracks 20 --windows-per-track 4
    python export_audio_encoder.py --synthetic        # no library needed
    python export_audio_encoder.py --print-catalogue  # the music_models.py block

The sibling of `export_text_encoder.py`, and the same trade for the same
reason -- except that this artefact does not run in the container at all. It
runs on an EDITOR'S MACHINE, in the companion, so that a dropped folder of
music is embedded where it was dropped instead of being uploaded and queued
for the base rig's GPU (`docs/MUSIC_INGEST_PLAN.md` §1). The companion has no
torch and must not gain it (~2 GB frozen), so the tower goes to ONNX and the
mel front end goes to numpy (`mel_numpy.py`).

## What is written

    music-clap-audio-<ver>.onnx          audio tower + audio_projection + L2 normalise
    music-clap-audio-<ver>.params.json   everything a numpy front end needs
    music-clap-audio-<ver>.fp16.onnx     optional half-precision copy (see below)
    report.md                            what was measured, on what, when

The params JSON is not decoration: `mel_numpy.MelExtractor` is driven entirely
by it, and it is the only thing that keeps the companion's features identical
to the ones the tower was trained and verified with. It records the sample
rate, window length, mel geometry (bins/hop/fft/fmin/fmax), the log-mel
scaling, the padding and truncation rules, the L2/pooling convention, and the
graph's input/output names -- taken from the checkpoint's own
`ClapFeatureExtractor`, never from memory.

## Why the whole tower, normalise included

`analyse_one` produces a track vector as: per-window CLAP audio embedding
(already unit length -- `Clap.embed_audio` L2-normalises), mean over the
windows, then normalise again. The per-window normalise is baked into the
graph so the artefact's output IS a window embedding; the mean-then-normalise
step is recorded in the params JSON (`embedding.pooling`) because it happens
over a variable number of windows, outside any single forward pass.

## fp16

Exported as a second, optional file and never as the default. It halves the
download (~170 MB vs ~340 MB) but onnxruntime's CPU provider executes fp16 by
inserting casts, so on the machines that matter -- editor laptops with no
usable GPU EP -- it is slower, not faster, and it moves the embedding by more
than the fp32 graph does. `report.md` carries the measured size and cosine for
both so the decision can be revisited with numbers rather than instinct.

## The check

Nothing is published until the ONNX embeddings match the torch model's on real
library audio: cosine >= MIN_COSINE (0.999) on every window AND on every
mean-pooled track vector. A drifting audio tower would place newly ingested
tracks in a subtly different space from the 376 already indexed -- they would
still return results, just the wrong ones, which is precisely the failure a
smoke test cannot see. Same staging discipline as the text exporter (MUSIC-1,
2026-08-14): everything is written to `<out>.new`, verified there, and swapped
in only once it passes.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# music_index/__init__.py puts ../web on sys.path -- musicweb.projection's
# l2norm is the one definition the index side and the query side share.
from music_index import audio, config
from musicweb.projection import l2norm

import mel_numpy
import music_models
# One definition of the "stage, verify, swap, keep the previous one" dance and
# of sha256-over-a-file: this is the same MUSIC-1 discipline, not a second
# opinion about it. export_text_encoder imports nothing heavier than
# musicweb.text_encoder at module scope, so this costs nothing.
from export_text_encoder import sha256, staging_dir, swap_into_place

# The bar the artefact must clear against the torch model, on every window and
# every pooled track vector. Same number as the text tower's (which owns it in
# musicweb/text_encoder.py, because the container's LOADER enforces it there);
# repeated here rather than imported because nothing loads this artefact in
# the container -- the companion does, and it verifies a sha256, not a cosine.
MIN_COSINE = 0.999
OPSET = 17

DEFAULT_TRACKS = 20
DEFAULT_WINDOWS_PER_TRACK = 4


def artefact_dir():
    """Where the exported audio tower lands.

    Under DATA_ROOT beside `text_encoder/`, but note the difference: `data/` is
    shipped to the NAS ITEM BY ITEM (music/web/DEPLOY.md excludes `data/` from
    the code ship), and this artefact is NOT one of the items -- the container
    never embeds audio. It goes to the release feed instead.
    """
    env = os.environ.get('MUSIC_AUDIO_ENCODER_DIR')
    return Path(env) if env else config.DATA_ROOT / 'audio_encoder'


# ------------------------------------------------------------- the tower

def _audio_tower(model):
    """audio_model + audio_projection + the L2 normalise get_audio_features does.

    Refuses a fusion checkpoint. The fusion path feeds FOUR mels per clip --
    three random crops and a bilinear-downsampled whole -- chosen with
    `np.random.choice`, so the same file would embed differently on every run
    and the companion could not reproduce, resume or dedupe its own work.
    Every laion CLAP checkpoint this repo uses has `enable_fusion=False`.
    """
    import torch
    import torch.nn as nn

    if getattr(model.config.audio_config, 'enable_fusion', False):
        raise SystemExit(
            '  FAIL: this checkpoint enables feature fusion, whose mel front end '
            'is randomised (3 random crops + a downsample per clip). The '
            'companion needs a deterministic embedding; export an unfused '
            'checkpoint instead.')

    class AudioTower(nn.Module):
        def __init__(self, clap):
            super().__init__()
            self.audio_model = clap.audio_model
            self.audio_projection = clap.audio_projection

        def forward(self, input_features):
            # is_longer is deliberately not an input: it is read only by the
            # fusion branch, which _audio_tower has just refused to export.
            out = self.audio_model(input_features=input_features)
            pooled = out.pooler_output if hasattr(out, 'pooler_output') else out[1]
            feats = self.audio_projection(pooled)
            return feats / torch.clamp(feats.norm(dim=-1, keepdim=True), min=1e-8)

    return AudioTower(model).eval()


def _get_audio_features(model, input_features):
    import torch
    out = model.get_audio_features(input_features=input_features)
    if torch.is_tensor(out):
        return out
    for attr in ('audio_embeds', 'pooler_output'):
        v = getattr(out, attr, None)
        if v is not None and torch.is_tensor(v):
            return v
    raise TypeError(f'cannot extract embedding from {type(out).__name__}')


# --------------------------------------------------------- the check corpus

def library_windows(n_tracks, per_track, db_path=None, seed=11, walk=True):
    """Real audio: up to `per_track` 10 s windows from each of `n_tracks`.

    -> (list of (label, chunk), note). Tracks come from the index's own rows,
    so the check corpus is the library the artefact will be used against
    (mixed .mp3/.aac/.flac/.ogg, quiet ambience and loud percussion alike) and
    not a synthetic tone the model has never seen. Returns ([], reason) rather
    than raising if the library is unreachable -- see --synthetic.

    With no index (a checkout whose `data/` was never populated) it falls back
    to walking the share itself: the point of the corpus is real audio, and a
    base rig with the library mounted has that whether or not it has a copy of
    the database.
    """
    try:
        db_path = Path(db_path or config.DB_PATH)
    except Exception as exc:                                    # noqa: BLE001
        db_path, why = None, f'no index path ({exc})'
    else:
        why = f'no index at {db_path}'
    if db_path is None or not db_path.is_file():
        if walk:
            got, note = share_windows(n_tracks, per_track, seed)
            if got:
                return got, note
        return [], why

    try:
        con = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            'SELECT share, rel_path, duration FROM tracks '
            'WHERE embedding IS NOT NULL ORDER BY id').fetchall()
        con.close()
    except sqlite3.Error as exc:
        return [], f'{db_path} unreadable ({exc})'
    if not rows:
        return [], f'{db_path} holds no analysed tracks'

    # Spread across the library rather than taking the first N: the first N by
    # id are whatever was imported first, which here is one supplier's catalogue.
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(rows))
    out, used, missing = [], 0, 0
    for i in order:
        if used >= n_tracks:
            break
        r = rows[int(i)]
        try:
            path = config.resolve_path(r['share'] or config.SHARE, r['rel_path'])
        except Exception:                                       # noqa: BLE001
            missing += 1
            continue
        if not path.is_file():
            missing += 1
            continue
        y = audio.decode(path)
        if y.size == 0:
            missing += 1
            continue
        wins = audio.windows(y)[:per_track]
        if not wins:
            missing += 1
            continue
        for j, (chunk, t0, _t1) in enumerate(wins):
            out.append((f'{Path(r["rel_path"]).name} @{t0:.0f}s', chunk))
        used += 1
    if not out:
        return [], (f'{len(rows)} rows in {db_path}, but none of their audio is '
                    f'readable from this machine ({missing} tried)')
    return out, f'{used} tracks from {db_path} ({len(out)} windows)'


def share_windows(n_tracks, per_track, seed=11, root=None):
    """The same corpus, taken off the share instead of out of the index.

    -> (list of (label, chunk), note). Used when no `music.db` is at hand --
    a fresh checkout, or the parity test running anywhere but the machine that
    holds the index. `share_root()` is the live mapping (P:\\Assets\\Music on a
    fleet machine), so this is silent and instant when the library is not
    mounted rather than an error nobody can act on.
    """
    try:
        root = Path(root or config.share_root())
    except Exception as exc:                                    # noqa: BLE001
        return [], f'no music share ({exc})'
    if not root.is_dir():
        return [], f'no music library at {root}'

    files = []
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in config.AUDIO_EXTS:
            files.append(p)
    if not files:
        return [], f'no audio files directly under {root}'

    rng = np.random.default_rng(seed)
    out, used = [], 0
    for i in rng.permutation(len(files)):
        if used >= n_tracks:
            break
        path = files[int(i)]
        y = audio.decode(path)
        if y.size == 0:
            continue
        wins = audio.windows(y)[:per_track]
        if not wins:
            continue
        for chunk, t0, _t1 in wins:
            out.append((f'{path.name} @{t0:.0f}s', chunk))
        used += 1
    if not out:
        return [], f'nothing under {root} decoded'
    return out, f'{used} tracks from {root} ({len(out)} windows, no index used)'


def synthetic_windows(n, seed=11):
    """Deterministic stand-ins when no library is reachable. NOT equivalent:
    noise and tones exercise the graph but not the model's dynamic range, so an
    artefact verified only against these says so in report.md."""
    rng = np.random.default_rng(seed)
    sr, w = config.SAMPLE_RATE, int(config.WINDOW_SEC * config.SAMPLE_RATE)
    t = np.arange(w, dtype=np.float32) / sr
    out = []
    for i in range(n):
        kind = i % 4
        if kind == 0:
            y = 0.1 * rng.standard_normal(w)
        elif kind == 1:
            f = 110.0 * (2 ** (i / 12.0))
            y = 0.4 * np.sin(2 * np.pi * f * t)
        elif kind == 2:
            y = 0.3 * np.sin(2 * np.pi * 220 * t) * np.exp(-3 * (t % 0.5))
        else:
            y = 0.05 * rng.standard_normal(w) + 0.2 * np.sin(2 * np.pi * 55 * t)
        out.append((f'synthetic-{kind}-{i}', y.astype(np.float32)))
    return out, f'{n} synthetic windows (NO library audio was reachable)'


# ---------------------------------------------------------------- verifying

def onnx_embed(onnx_path, extractor, chunks, batch=4, threads=None):
    """The artefact's own answer: numpy mel -> onnxruntime -> unit vectors."""
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = int(threads or os.environ.get(
        'MUSIC_AUDIO_ENCODER_THREADS', '8'))
    so.inter_op_num_threads = 1
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(str(onnx_path), so,
                                providers=['CPUExecutionProvider'])
    in_name = sess.get_inputs()[0].name
    in_type = sess.get_inputs()[0].type
    dtype = np.float16 if 'float16' in in_type else np.float32
    out_name = sess.get_outputs()[0].name

    got = []
    for i in range(0, len(chunks), batch):
        feats = extractor.input_features(chunks[i:i + batch]).astype(dtype)
        got.append(np.asarray(sess.run([out_name], {in_name: feats})[0],
                              dtype=np.float32))
    return l2norm(np.concatenate(got, axis=0))


def torch_embed(clap, chunks, batch=4):
    """What the full ClapModel says -- the same call `analyse_one` makes."""
    return clap.embed_audio(list(chunks), batch_size=batch)


def pooled(vectors, per_track):
    """analyse_one's track vector: mean of the window vectors, renormalised."""
    out = []
    for i in range(0, len(vectors), per_track):
        v = vectors[i:i + per_track].mean(axis=0)
        out.append(v / max(float(np.linalg.norm(v)), 1e-8))
    return np.stack(out) if out else np.zeros((0, vectors.shape[1]), np.float32)


def compare(name, got, reference, labels=None, min_cosine=MIN_COSINE,
            fatal=True, verbose=True):
    """-> (min, mean). Raises SystemExit when a fatal comparison drifts."""
    cos = np.sum(got * reference, axis=1)
    if verbose:
        print(f'  {name}: n={len(cos)}  min {cos.min():.7f}  '
              f'mean {cos.mean():.7f}  max {cos.max():.7f}')
        for i in np.argsort(cos)[:3]:
            label = labels[i] if labels else f'#{i}'
            print(f'      worst {cos[i]:.7f}  {label[:64]!a}')
    if fatal and cos.min() < min_cosine:
        raise SystemExit(
            f'\n  FAIL: {name} min cosine {cos.min():.7f} < {min_cosine}. The '
            'artefact does not reproduce ClapModel; tracks embedded with it '
            'would land in a different space from the ones already indexed. '
            'Not writing it.')
    return float(cos.min()), float(cos.mean())


# ------------------------------------------------------------------ writing

def feature_params(model_name, fe, model, opset, precision='fp32'):
    """Everything a numpy front end needs, read off the checkpoint's own
    feature extractor. Never hand-written: a number that drifts from the
    checkpoint here is an embedding that drifts from the library."""
    n_frames = int(1 + np.floor(
        (fe.nb_max_samples + 2 * (fe.fft_window_size // 2) - fe.fft_window_size)
        / fe.hop_length))
    return {
        'params_version': mel_numpy.PARAMS_VERSION,
        'artefact': music_models.model()['onnx_name'],
        'artefact_version': music_models.model()['version'],
        'model': model_name,
        'precision': precision,
        'opset': opset,
        'exported_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'features': {
            'extractor': type(fe).__name__,
            'sampling_rate': int(fe.sampling_rate),
            'max_length_s': float(fe.max_length_s),
            'nb_max_samples': int(fe.nb_max_samples),
            'feature_size': int(fe.feature_size),
            'fft_window_size': int(fe.fft_window_size),
            'hop_length': int(fe.hop_length),
            'frequency_min': float(fe.frequency_min),
            'frequency_max': float(fe.frequency_max),
            'n_frames': n_frames,
            # The rand_trunc path's bank: slaney scale, slaney (area) norm.
            'mel_scale': 'slaney',
            'mel_norm': 'slaney',
            'mel_floor': 1e-10,
            'power': 2.0,
            'log_mel': 'dB',
            'log_reference': 1.0,
            'log_min_value': 1e-10,
            'center': True,
            'pad_mode': 'reflect',
            'window': 'hann',
            'window_periodic': True,
            'padding': str(fe.padding),
            'padding_value': float(fe.padding_value),
            # The checkpoint says "rand_trunc"; a random crop is not something
            # a fleet can reproduce, and the pipeline feeds exact windows, so
            # the artefact is verified under a deterministic head crop and the
            # companion must use the same rule (mel_numpy.fit_window).
            'truncation': str(fe.truncation),
            'truncation_rule': 'head',
        },
        'graph': {
            'input': 'input_features',
            'input_shape': ['batch', 1, n_frames, int(fe.feature_size)],
            'output': 'audio_embeds',
            'is_longer_required': False,
            'enable_fusion': bool(getattr(model.config.audio_config,
                                          'enable_fusion', False)),
        },
        'embedding': {
            'dim': int(model.config.projection_dim),
            'normalised': True,
            # analyse_one: mean of the per-window unit vectors, renormalised.
            'pooling': 'mean_then_l2',
            'window_seconds': float(config.WINDOW_SEC),
            'max_windows': int(config.MAX_WINDOWS),
            'window_trim_fraction': 0.02,
        },
    }


def write_artefact(out_dir, model_name=None, opset=OPSET, fp16=True):
    """The torch half: ONNX (+ fp16) + params into out_dir. -> (info dict).

    Always called on a staging directory; see export().
    """
    import torch
    import transformers
    from transformers import ClapModel, ClapProcessor

    model_name = model_name or config.CLAP_MODEL
    print(f'  loading {model_name} ...')
    t0 = time.time()
    model = ClapModel.from_pretrained(model_name).eval()
    processor = ClapProcessor.from_pretrained(model_name)
    fe = processor.feature_extractor
    print(f'    {time.time() - t0:.1f}s')

    tower = _audio_tower(model)
    n_audio = (sum(p.numel() for p in model.audio_model.parameters())
               + sum(p.numel() for p in model.audio_projection.parameters()))
    print(f'  audio tower + projection: {n_audio/1e6:.1f}M params of '
          f'{sum(p.numel() for p in model.parameters())/1e6:.1f}M')

    params = feature_params(model_name, fe, model, opset)
    extractor = mel_numpy.MelExtractor(mel_numpy.MelParams(params))

    # Trace on a batch of two so the batch axis is exercised at export time.
    rng = np.random.default_rng(3)
    sample_chunks = [0.1 * rng.standard_normal(fe.nb_max_samples).astype(np.float32)
                     for _ in range(2)]
    sample = torch.from_numpy(extractor.input_features(sample_chunks))

    with torch.no_grad():
        drift = (tower(sample) - _get_audio_features(model, sample)).abs().max().item()
    print(f'  tower vs ClapModel.get_audio_features (torch): max abs diff {drift:g}')

    # The mel front end the companion will run, against the checkpoint's own
    # extractor, on the very features being exported. A mismatch here is not a
    # rounding difference -- it is a different spectrogram.
    ref_feats = np.asarray(
        fe(sample_chunks, sampling_rate=fe.sampling_rate,
           return_tensors='np')['input_features'], dtype=np.float32)
    ours = extractor.input_features(sample_chunks)
    mel_bit_equal = bool(np.array_equal(ours, ref_feats))
    mel_max_abs = float(np.abs(ours - ref_feats).max())
    print(f'  mel_numpy vs {type(fe).__name__}: '
          f'{"BIT-IDENTICAL" if mel_bit_equal else f"max abs diff {mel_max_abs:g}"}')
    if not mel_bit_equal:
        raise SystemExit(
            '\n  FAIL: mel_numpy does not reproduce the checkpoint\'s feature '
            'extractor. Fix mel_numpy.py (or the params it is driven by) '
            'before exporting -- the companion would embed a different '
            'spectrogram from the one this tower was verified on.')

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    onnx_name, params_name = music_models.filenames()
    onnx_path = out_dir / onnx_name

    print(f'  exporting ONNX opset {opset} -> {onnx_path}')
    t0 = time.time()
    torch.onnx.export(
        tower, (sample,), str(onnx_path),
        input_names=['input_features'], output_names=['audio_embeds'],
        dynamic_axes={'input_features': {0: 'batch'},
                      'audio_embeds': {0: 'batch'}},
        opset_version=opset, dynamo=False)
    size = onnx_path.stat().st_size
    print(f'    {time.time() - t0:.1f}s, {size/1e6:.1f} MB')

    fp16_path, fp16_note = None, ''
    if fp16:
        fp16_path, fp16_note = write_fp16(onnx_path, out_dir)

    (out_dir / params_name).write_text(json.dumps(params, indent=2),
                                       encoding='utf-8')
    return {
        'model': model_name, 'params': params, 'onnx': onnx_path,
        'params_path': out_dir / params_name, 'fp16': fp16_path,
        'fp16_note': fp16_note, 'extractor': extractor, 'torch_drift': drift,
        'mel_bit_equal': mel_bit_equal, 'mel_max_abs': mel_max_abs,
        'audio_params': int(n_audio),
        'torch_version': torch.__version__,
        'transformers_version': transformers.__version__,
    }


def write_fp16(onnx_path, out_dir):
    """A half-precision copy beside the fp32 one. -> (path|None, note).

    Never fatal: fp16 is an option to be measured, not a requirement, and the
    converter lives in a package (onnxconverter-common, or the copy shipped
    inside onnxruntime.transformers) that a base rig may not have.
    """
    target = Path(out_dir) / Path(onnx_path).name.replace('.onnx', '.fp16.onnx')
    try:
        import onnx
    except ImportError:
        return None, 'skipped: the `onnx` package is not installed'
    convert = None
    try:
        from onnxconverter_common import float16 as f16
        convert = f16.convert_float_to_float16
        source = 'onnxconverter-common'
    except ImportError:
        try:
            from onnxruntime.transformers.float16 import convert_float_to_float16
            convert = convert_float_to_float16
            source = 'onnxruntime.transformers.float16'
        except ImportError:
            return None, ('skipped: neither onnxconverter-common nor '
                          'onnxruntime.transformers is installed')
    try:
        model = onnx.load(str(onnx_path))
        half = convert(model, keep_io_types=False)
        onnx.save(half, str(target))
    except Exception as exc:                                    # noqa: BLE001
        if target.exists():
            target.unlink()
        return None, f'skipped: conversion failed ({type(exc).__name__}: {exc})'
    print(f'  fp16 ({source}) -> {target.name}, '
          f'{target.stat().st_size/1e6:.1f} MB')
    return target, f'converted with {source}'


# ------------------------------------------------------------------- report

def render_report(info, checks, corpus_note, out_dir):
    onnx_name, params_name = music_models.filenames()
    lines = [
        f'# {onnx_name} — export report',
        '',
        f'Written by `music/indexer/export_audio_encoder.py` on '
        f'{datetime.now(timezone.utc).isoformat(timespec="seconds")}.',
        '',
        '| | |',
        '|---|---|',
        f'| checkpoint | `{info["model"]}` |',
        f'| exported | audio_model + audio_projection + L2 normalise |',
        f'| params | {info["audio_params"]/1e6:.1f} M |',
        f'| opset | {info["params"]["opset"]} |',
        f'| torch / transformers | {info["torch_version"]} / '
        f'{info["transformers_version"]} |',
        f'| embedding | {info["params"]["embedding"]["dim"]}-d, unit length, '
        f'pooled `{info["params"]["embedding"]["pooling"]}` |',
        f'| check corpus | {corpus_note} |',
        f'| threshold | cosine >= {MIN_COSINE} |',
        '',
        '## Artefacts',
        '',
        '| file | bytes | sha256 |',
        '|---|---:|---|',
    ]
    for path in [info['onnx'], info['params_path']] + (
            [info['fp16']] if info['fp16'] else []):
        lines.append(f'| `{path.name}` | {path.stat().st_size:,} | '
                     f'`{sha256(path)}` |')
    if not info['fp16']:
        lines.append(f'| `*.fp16.onnx` | — | {info["fp16_note"]} |')
    lines += [
        '',
        '## Agreement with the torch model',
        '',
        '| comparison | n | min cosine | mean cosine |',
        '|---|---:|---:|---:|',
    ]
    for name, n, lo, mean in checks:
        lines.append(f'| {name} | {n} | {lo:.7f} | {mean:.7f} |')
    mel_verdict = ('bit-identical' if info['mel_bit_equal']
                   else f'max abs diff {info["mel_max_abs"]:g}')
    lines += [
        '',
        f'`mel_numpy.MelExtractor` vs `ClapFeatureExtractor`: {mel_verdict} '
        'on the export sample; `tests/test_mel_numpy.py` repeats it on '
        'library windows.',
        '',
        f'Tower vs `ClapModel.get_audio_features` inside torch: max abs diff '
        f'{info["torch_drift"]:g}.',
        '',
        '## Publishing',
        '',
        'These two files go to the vendor release feed '
        '(`docs/RELEASE_FEED.md`), not to the NAS: the container never embeds '
        'audio, the companion does. Paste the block below into '
        '`music/indexer/music_models.py` so the sidecar can verify what it '
        'downloads, and bump `version` if anything about the tower or the '
        'features changed.',
        '',
        '```python',
        catalogue_block(info),
        '```',
        '',
    ]
    (Path(out_dir) / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def catalogue_block(info):
    """The `music_models.MODELS` fragment for what was just produced."""
    onnx_name, params_name = music_models.filenames()
    return (
        '        "sha256": {\n'
        f'            "{onnx_name}":\n'
        f'                "{sha256(info["onnx"])}",\n'
        f'            "{params_name}":\n'
        f'                "{sha256(info["params_path"])}",\n'
        '        },\n'
        '        "size_bytes": {\n'
        f'            "{onnx_name}": {info["onnx"].stat().st_size},\n'
        f'            "{params_name}": {info["params_path"].stat().st_size},\n'
        '        },'
    )


# -------------------------------------------------------------------- verify

def verify(directory, chunks, labels, per_track, clap=None, reference=None,
           check_fp16=True):
    """Compare the artefact in `directory` to the torch model. -> (checks, ref).

    `checks` is the list of (name, n, min, mean) rows report.md prints.
    """
    directory = Path(directory)
    onnx_name, params_name = music_models.filenames()
    extractor = mel_numpy.MelExtractor.from_params_file(directory / params_name)

    if reference is None:
        if clap is None:
            from music_index.clap_model import Clap
            clap = Clap()
        print(f'  embedding {len(chunks)} windows with the full ClapModel '
              f'({clap.name} on {clap.device}) ...')
        reference = torch_embed(clap, chunks)

    print(f'  embedding the same {len(chunks)} windows with onnxruntime ...')
    t0 = time.time()
    got = onnx_embed(directory / onnx_name, extractor, chunks)
    per_window = (time.time() - t0) / max(len(chunks), 1)
    print(f'    {per_window*1000:.0f} ms per 10 s window (CPU)')

    checks = []
    lo, mean = compare('per window', got, reference, labels)
    checks.append(('per window (fp32)', len(chunks), lo, mean))
    if per_track > 1 and len(chunks) >= per_track:
        n = (len(chunks) // per_track) * per_track
        lo, mean = compare('per track (mean-pooled)', pooled(got[:n], per_track),
                           pooled(reference[:n], per_track))
        checks.append(('per track, mean-pooled (fp32)', n // per_track, lo, mean))

    fp16_path = directory / onnx_name.replace('.onnx', '.fp16.onnx')
    if check_fp16 and fp16_path.is_file():
        try:
            half = onnx_embed(fp16_path, extractor, chunks)
        except Exception as exc:                                # noqa: BLE001
            print(f'  ! fp16 could not be run here ({type(exc).__name__}: {exc})')
        else:
            # NOT fatal: fp16 is published as an option and its cosine is a
            # measurement, not a gate. The fp32 file is what the catalogue pins.
            lo, mean = compare('per window (fp16)', half, reference, labels,
                               fatal=False)
            checks.append(('per window (fp16, informational)', len(chunks), lo, mean))
    return checks, reference


def export(out_dir, model_name=None, opset=OPSET, tracks=DEFAULT_TRACKS,
           per_track=DEFAULT_WINDOWS_PER_TRACK, synthetic=False, fp16=True,
           db_path=None):
    """Export, verify, and only then publish. -> the info dict."""
    out_dir = Path(out_dir)

    chunks_labelled, note = ([], '') if not synthetic else synthetic_windows(
        tracks * per_track)
    if not synthetic:
        chunks_labelled, note = library_windows(tracks, per_track, db_path)
        if not chunks_labelled:
            print(f'  ! no library audio ({note}); falling back to synthetic '
                  'signals -- report.md will say so')
            chunks_labelled, note = synthetic_windows(tracks * per_track)
    labels = [c[0] for c in chunks_labelled]
    chunks = [c[1] for c in chunks_labelled]
    print(f'  check corpus: {note}')

    staging = staging_dir(out_dir)
    try:
        info = write_artefact(staging, model_name, opset, fp16=fp16)
        checks, _ = verify(staging, chunks, labels,
                           per_track if not synthetic else 1)
        render_report(info, checks, note, staging)
        # Point the info at the published location before anything is read
        # back from it (the report was already written into staging).
        previous = swap_into_place(staging, out_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(f'\n  wrote {out_dir}')
    if previous:
        print(f'  the artefact it replaced is at {previous}')
    print('\n  paste into music/indexer/music_models.py:\n')
    info['onnx'] = out_dir / info['onnx'].name
    info['params_path'] = out_dir / info['params_path'].name
    print(catalogue_block(info))
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', default=None,
                    help='artefact directory (default: music/web/data/audio_encoder)')
    ap.add_argument('--model', default=None, help=f'default {config.CLAP_MODEL}')
    ap.add_argument('--opset', type=int, default=OPSET)
    ap.add_argument('--tracks', type=int, default=DEFAULT_TRACKS,
                    help=f'library tracks in the check corpus (default {DEFAULT_TRACKS})')
    ap.add_argument('--windows-per-track', type=int, default=DEFAULT_WINDOWS_PER_TRACK)
    ap.add_argument('--synthetic', action='store_true',
                    help='check against generated signals instead of the library')
    ap.add_argument('--no-fp16', action='store_true',
                    help='do not write the half-precision copy')
    ap.add_argument('--db', default='', help='index to draw the check corpus from')
    ap.add_argument('--check', action='store_true',
                    help='verify an existing artefact instead of writing one')
    ap.add_argument('--print-catalogue', action='store_true',
                    help='print the music_models.py block for an existing artefact')
    args = ap.parse_args()

    out = Path(args.out) if args.out else artefact_dir()
    onnx_name, params_name = music_models.filenames()

    if args.print_catalogue:
        if not (out / onnx_name).is_file():
            raise SystemExit(f'no artefact at {out}')
        print(catalogue_block({'onnx': out / onnx_name,
                               'params_path': out / params_name}))
        return

    try:
        config.require_tools()
    except config.FfmpegNotConfigured as exc:
        # Only the library corpus needs ffmpeg; say so rather than refusing.
        if not args.synthetic:
            raise SystemExit(f'{exc}\n  (or run with --synthetic)')

    if args.check:
        if not (out / onnx_name).is_file():
            raise SystemExit(f'no artefact at {out}')
        chunks_labelled, note = (
            synthetic_windows(args.tracks * args.windows_per_track)
            if args.synthetic else
            library_windows(args.tracks, args.windows_per_track, args.db or None))
        if not chunks_labelled:
            print(f'  ! no library audio ({note}); using synthetic signals')
            chunks_labelled, note = synthetic_windows(
                args.tracks * args.windows_per_track)
        print(f'  checking {out} against {note}')
        verify(out, [c[1] for c in chunks_labelled],
               [c[0] for c in chunks_labelled],
               args.windows_per_track if not args.synthetic else 1)
        print('\n  OK')
        return

    export(out, model_name=args.model, opset=args.opset, tracks=args.tracks,
           per_track=args.windows_per_track, synthetic=args.synthetic,
           fp16=not args.no_fp16, db_path=args.db or None)


if __name__ == '__main__':
    sys.exit(main())
