"""Export CLAP's text half as a self-contained artefact. BASE RIG ONLY.

    python export_text_encoder.py                  # -> music/web/data/text_encoder/
    python export_text_encoder.py --check          # verify an existing artefact
    python export_text_encoder.py --out D:\\some\\dir --model laion/clap-htsat-unfused

`/api/search` embeds the query string on every request and that is the only
model call the web half ever makes. Everything else is precomputed here. So the
container does not need `ClapModel` -- it needs `text_model` + `text_projection`
(125M of the model's 194M params) and a tokenizer.

## Why ONNX and not a torch artefact

Both were exported and measured on the base rig (24-core, machine under load,
49-query corpus, batch of 1, interleaved so contention hits all three equally):

    backend         artefact    cold load   median/query   cos vs ClapModel
    onnxruntime     501.4 MB       1.98 s        30.3 ms   min 0.99999994
    torchscript     501.3 MB       1.01 s        39.7 ms   min 0.99999988
    full ClapModel  (777 MB)       2.58 s        45.3 ms   --

The artefacts are the same size (the same 125M fp32 weights either way) and both
are numerically exact, so the decision is entirely about what has to be
installed to *run* them, on a NAS container:

    onnxruntime 1.28.0  linux cp312   19.2 MB wheel /  54.3 MB unpacked
    torch 2.6.0+cpu     linux cp312  178.6 MB wheel / 675.1 MB unpacked

12x, before torch's own runtime deps (sympy, networkx, jinja2, fsspec) and
before `transformers` (11.6 MB wheel / 98 MB unpacked), which a torchscript
artefact avoids but a `state_dict` one would not. ONNX is also the fastest of
the three per query, so nothing is traded away for the smaller image. Hence
ONNX. If a future transformers release breaks the export, the honest move is to
fall back to torchscript rather than to ship a drifting artefact --
`musicweb/text_encoder.py` already degrades to the full `ClapModel`.

## What is written

    text_encoder.onnx   text tower + projection + final L2 normalise
    tokenizer.json      the model's own byte-level BPE, verbatim
    manifest.json       model name, dim, ids, versions, sha256s, the check result

The exporter refuses to write an artefact whose embeddings differ from
`ClapModel.get_text_features`: cosine over QUERIES below must be >= MIN_COSINE
for every one of them. A shifted embedding would silently reorder every search
result, which is exactly the failure that would not show up in a smoke test.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# music_index/__init__.py puts ../web on sys.path, which is where the artefact
# LOADER lives -- the exporter verifies itself against the exact code the
# container will run rather than against a second copy of the tokenizer.
from music_index import config                       # noqa: F401  (sys.path side effect)
from musicweb import text_encoder as te

MIN_COSINE = 0.999
OPSET = 17

# Varied on purpose: the ten eval.py retrieval queries, single words, long
# sentences, punctuation, digits, non-ASCII and awkward whitespace -- the last
# three are where a hand-rolled tokenizer would break first, and a tokenizer
# break is indistinguishable from a model break once it is an embedding.
QUERIES = [
    'eerie unsettling horror music',
    'traditional japanese music',
    'retro neon synthwave',
    'angry aggressive riot music',
    'lonely empty city at night',
    'gentle rain and quiet reflection',
    'mysterious forest atmosphere',
    'ancient historical discovery',
    'jazz with brass and drums',
    'dark futuristic technology',
    'drums', 'sad', 'epic', 'lofi', 'a',
    'solo piano', 'heavy metal', 'string quartet', 'tribal percussion',
    'ambient drone',
    'sparse ominous drone under an interview',
    'a hopeful build that pays off in the last eight bars',
    'warm acoustic guitar for a montage of family photographs',
    'driving electronic pulse for a drone flyover of a city at dawn',
    'quiet reflective underscore that never pulls focus from the dialogue',
    'triumphant orchestral fanfare with brass swells and timpani hits',
    'unsettling metallic scrape that suggests something is very wrong',
    'bouncy playful ukulele for a lighthearted product explainer',
    'slow mournful cello over a wide shot of an empty landscape',
    'aggressive industrial techno with distorted kick drums',
    'a long sustained cinematic cue that opens with almost nothing, just a single '
    'held string note and some room tone, then gradually layers in low brass and a '
    'heartbeat pulse until it breaks into a full orchestral climax with choir',
    'documentary underscore for an interview about the history of aerial photography '
    'in taiwan, needs to feel curious and forward looking without being saccharine',
    'Epic Climax!', 'ROCK N ROLL', '80s synth-pop', 'a 3/4 waltz, gentle',
    "don't stop the beat", 'piano & strings (soft)', '128 bpm house',
    'trailer riser -- 5 seconds',
    '\u5c0b\u627e\u5bf6\u5cf6 opening theme', 'caf\u00e9 accordion, parisian',
    'm\u00fasica latina alegre', '\u30a8\u30ec\u30af\u30c8\u30ed\u30cb\u30ab',
    'foley   whoosh', '  leading and trailing spaces  ', 'b-roll bed',
    'no copyright chill beats to study to', 'sub bass hit',
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _text_tower(model):
    """text_model + text_projection + the L2 normalise get_text_features does.

    Baking the normalise into the graph means the artefact's output IS the
    query vector, with no chance of the two halves disagreeing about whether it
    has been normalised yet.
    """
    import torch
    import torch.nn as nn

    class TextTower(nn.Module):
        def __init__(self, clap):
            super().__init__()
            self.text_model = clap.text_model
            self.text_projection = clap.text_projection

        def forward(self, input_ids, attention_mask):
            out = self.text_model(input_ids=input_ids, attention_mask=attention_mask)
            # transformers 4.x returns a tuple, 5.x a BaseModelOutputWithPooling
            pooled = out.pooler_output if hasattr(out, 'pooler_output') else out[1]
            feats = self.text_projection(pooled)
            return feats / torch.clamp(feats.norm(dim=-1, keepdim=True), min=1e-8)

    return TextTower(model).eval()


def reference_embeddings(clap, queries):
    """What the full ClapModel says, one query at a time -- which is exactly how
    `Index.text_search` calls it, so the comparison is like for like."""
    return np.stack([clap.embed_text([q])[0] for q in queries])


def verify(directory, reference=None, queries=QUERIES, verbose=True):
    """Load the artefact the way the container will and compare to CLAP.

    -> (min_cos, mean_cos). Raises SystemExit on drift, so this is safe to use
    as the last step of an export.
    """
    enc = te.OnnxTextEncoder(directory)
    got = enc.embed_text(queries)

    if reference is None:
        from music_index.clap_model import Clap
        reference = reference_embeddings(Clap(), queries)

    cos = np.sum(got * reference, axis=1)
    order = np.argsort(cos)
    if verbose:
        print(f'\n  cosine vs full ClapModel over {len(queries)} queries')
        print(f'    min  {cos.min():.7f}   mean {cos.mean():.7f}   '
              f'max {cos.max():.7f}')
        for i in order[:3]:
            # !a, not !r: the check corpus is deliberately full of non-ASCII and
            # a Windows console is cp1252.
            print(f'    worst {cos[i]:.7f}  {queries[i][:60]!a}')
    if cos.min() < MIN_COSINE:
        raise SystemExit(
            f'\n  FAIL: min cosine {cos.min():.7f} < {MIN_COSINE}. The artefact '
            'does not reproduce ClapModel and would silently reorder search '
            'results. Not writing it.')
    return float(cos.min()), float(cos.mean())


def verify_tokenizer(directory, tokenizer, queries=QUERIES):
    """Token-for-token against the model's real tokenizer.

    Separate from the cosine check because it fails differently: a tokenizer
    that disagrees on one unusual character produces a *plausible* embedding of
    the wrong string, and the cosine check would only catch it if that exact
    string happened to be in QUERIES.
    """
    ours = te.ByteLevelBPETokenizer(Path(directory) / te.TOKENIZER_NAME)
    bad = []
    for q in queries:
        want = list(tokenizer(q)['input_ids'])
        got = ours.encode(q, max_length=None)
        if want != got:
            bad.append((q, want, got))
    if bad:
        for q, want, got in bad[:5]:
            print(f'    {q!a}\n      transformers {want}\n      artefact     {got}')
        raise SystemExit(f'\n  FAIL: tokenizer disagrees on {len(bad)} of '
                         f'{len(queries)} queries. Not writing the artefact.')
    print(f'  tokenizer matches transformers on all {len(queries)} queries')


def export(out_dir, model_name=None, opset=OPSET, queries=QUERIES):
    import torch
    import transformers
    from transformers import ClapModel, ClapProcessor

    model_name = model_name or config.CLAP_MODEL
    print(f'  loading {model_name} ...')
    t0 = time.time()
    model = ClapModel.from_pretrained(model_name).eval()
    processor = ClapProcessor.from_pretrained(model_name)
    print(f'    {time.time() - t0:.1f}s')

    tokenizer = processor.tokenizer
    text_cfg = model.config.text_config
    tower = _text_tower(model)
    n_text = (sum(p.numel() for p in model.text_model.parameters())
              + sum(p.numel() for p in model.text_projection.parameters()))
    print(f'  text tower + projection: {n_text/1e6:.1f}M params of '
          f'{sum(p.numel() for p in model.parameters())/1e6:.1f}M')

    # Trace on a padded batch so the padding path is exercised at export time,
    # not first discovered by a two-query request in production.
    sample = tokenizer(['epic climax with drums', 'soft'],
                       return_tensors='pt', padding=True)
    with torch.no_grad():
        drift = (tower(sample['input_ids'], sample['attention_mask'])
                 - _get_text_features(model, sample)).abs().max().item()
    print(f'  tower vs ClapModel.get_text_features (torch): max abs diff {drift:g}')

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = out_dir / te.MODEL_NAME

    print(f'  exporting ONNX opset {opset} -> {onnx_path}')
    t0 = time.time()
    torch.onnx.export(
        tower, (sample['input_ids'], sample['attention_mask']), str(onnx_path),
        input_names=['input_ids', 'attention_mask'],
        output_names=['text_embeds'],
        dynamic_axes={'input_ids': {0: 'batch', 1: 'seq'},
                      'attention_mask': {0: 'batch', 1: 'seq'},
                      'text_embeds': {0: 'batch'}},
        opset_version=opset, dynamo=False)
    print(f'    {time.time() - t0:.1f}s, {onnx_path.stat().st_size/1e6:.1f} MB')

    # tokenizer.json straight from the model, so the vocabulary and merges are
    # the model's own and not a copy that can rot.
    with tempfile.TemporaryDirectory() as tmp:
        tokenizer.save_pretrained(tmp)
        src = Path(tmp) / te.TOKENIZER_NAME
        if not src.is_file():
            raise SystemExit(f'  FAIL: {model_name} did not save a '
                             f'{te.TOKENIZER_NAME}; this exporter needs the fast '
                             'tokenizer format.')
        shutil.copy2(src, out_dir / te.TOKENIZER_NAME)
    print(f'  tokenizer -> {(out_dir / te.TOKENIZER_NAME).stat().st_size/1e6:.1f} MB')

    # max_positions counts RoBERTa's padding_idx offset (514 = 512 + 2), so the
    # usable token budget -- including <s> and </s> -- is 512.
    max_length = int(getattr(text_cfg, 'max_position_embeddings', 514)) - 2

    manifest = {
        'artefact_version': te.ARTEFACT_VERSION,
        'format': 'onnx',
        'model': model_name,
        'dim': int(model.config.projection_dim),
        'max_length': max_length,
        'bos_id': int(tokenizer.bos_token_id),
        'eos_id': int(tokenizer.eos_token_id),
        'pad_id': int(tokenizer.pad_token_id),
        'text_params': int(n_text),
        'opset': opset,
        'exported_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'torch': torch.__version__,
        'transformers': transformers.__version__,
        'sha256': {te.MODEL_NAME: sha256(onnx_path),
                   te.TOKENIZER_NAME: sha256(out_dir / te.TOKENIZER_NAME)},
    }
    (out_dir / te.MANIFEST_NAME).write_text(json.dumps(manifest, indent=2),
                                            encoding='utf-8')

    verify_tokenizer(out_dir, tokenizer, queries)

    print('  embedding the check corpus with the full ClapModel ...')
    from music_index.clap_model import Clap
    clap = Clap(name=model_name, device='cpu')
    ref = reference_embeddings(clap, queries)
    lo, mean = verify(out_dir, reference=ref, queries=queries)

    manifest['check'] = {'queries': len(queries), 'min_cosine': lo,
                         'mean_cosine': mean, 'threshold': MIN_COSINE}
    (out_dir / te.MANIFEST_NAME).write_text(json.dumps(manifest, indent=2),
                                            encoding='utf-8')
    print(f'\n  wrote {out_dir}')
    return manifest


def _get_text_features(model, inputs):
    import torch
    out = model.get_text_features(**inputs)
    if torch.is_tensor(out):
        return out
    for attr in ('text_embeds', 'pooler_output'):
        v = getattr(out, attr, None)
        if v is not None and torch.is_tensor(v):
            return v
    raise TypeError(f'cannot extract embedding from {type(out).__name__}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', default=None,
                    help='artefact directory (default: music/web/data/text_encoder)')
    ap.add_argument('--model', default=None, help=f'default {config.CLAP_MODEL}')
    ap.add_argument('--opset', type=int, default=OPSET)
    ap.add_argument('--check', action='store_true',
                    help='verify an existing artefact instead of writing one')
    args = ap.parse_args()

    out = Path(args.out) if args.out else te.artefact_dir()

    if args.check:
        if not te.artefact_available(out):
            raise SystemExit(f'no artefact at {out}')
        print(f'  checking {out}')
        lo, mean = verify(out)
        print(f'\n  OK  min {lo:.7f}  mean {mean:.7f}')
        return

    export(out, model_name=args.model, opset=args.opset)


if __name__ == '__main__':
    sys.exit(main())
