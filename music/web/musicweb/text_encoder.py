"""Query-text embedding without the rest of CLAP.

`/api/search` embeds the query string on every request, and that is the *only*
thing the web half ever asks a model for -- audio embeddings, tags, axes,
percentiles, peaks and the source-bias axes are all precomputed into the
database by the base rig. Loading the full `ClapModel` to do it drags in the
audio tower (~780 MB of fp32 the container never touches) and, worse, drags in
torch: 675 MB unpacked for one small transformer forward pass.

So the base rig exports the text half once (`music/indexer/export_text_encoder.py`)
into `music/web/data/text_encoder/`, and this module runs it with onnxruntime
(54 MB unpacked) plus a byte-level BPE tokenizer written out in plain Python
here. Measured on the base rig, interleaved against the full model:

    backend          cold load   median/query
    onnxruntime         1.98 s        30.3 ms
    torchscript         1.01 s        39.7 ms
    full ClapModel      2.58 s        45.3 ms

so the artefact is also the fastest of the three; the image saving is the point
but nothing is being traded for it. Cosine against the full model over the 49
queries in `export_text_encoder.QUERIES` is min 0.9999999 -- the artefact is
the same numbers, not an approximation, and `export_text_encoder` refuses to
write an artefact that is not.

If the artefact is absent (a dev checkout that never ran the export) or
onnxruntime is not installed, this falls back to the full `ClapModel` through
the indexer, exactly as `search.py` used to do unconditionally. That path needs
torch; the artefact path deliberately does not, and `tests/test_text_encoder.py`
pins that.
"""
import json
import os
import threading
import unicodedata
from pathlib import Path

import numpy as np

from musicweb import config
from musicweb.projection import l2norm

MANIFEST_NAME = 'manifest.json'
MODEL_NAME = 'text_encoder.onnx'
TOKENIZER_NAME = 'tokenizer.json'

# Bumped whenever the artefact layout changes in a way this loader cannot read.
# The export writes it into the manifest; a mismatch is treated as "no artefact"
# so a stale export degrades to the CLAP fallback instead of crashing search.
ARTEFACT_VERSION = 1


def config_model_name():
    """CLAP_MODEL without importing the indexer's config (which imports torch's
    neighbours). Only used to label an artefact whose manifest forgot to."""
    return os.environ.get('CLAP_MODEL', 'laion/larger_clap_music_and_speech')


def artefact_dir():
    """Where the exported text encoder lives.

    Under DATA_ROOT, not next to the source, because DATA_ROOT is the directory
    that actually gets shipped to the NAS (it is where `music.db` already
    lives) and is the one path the container is guaranteed to have.
    """
    env = os.environ.get('MUSIC_TEXT_ENCODER_DIR')
    return Path(env) if env else config.DATA_ROOT / 'text_encoder'


# --------------------------------------------------------------- tokenizer
# RoBERTa's byte-level BPE, reimplemented here rather than pulled in from
# `tokenizers`/`transformers`. It is ~80 lines, it is verified token-for-token
# against the real tokenizer by the exporter (which fails the export on any
# disagreement) and by tests/test_text_encoder.py's golden ids, and it keeps the
# container's new-dependency count at exactly one (onnxruntime).

_CONTRACTIONS = ("'s", "'t", "'re", "'ve", "'m", "'ll", "'d")


def _bytes_to_unicode():
    """GPT-2's reversible byte -> printable-codepoint map."""
    bs = (list(range(ord('!'), ord('~') + 1))
          + list(range(ord('\xa1'), ord('\xac') + 1))
          + list(range(ord('\xae'), ord('\xff') + 1)))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))


def _is_letter(ch):
    return unicodedata.category(ch)[0] == 'L'


def _is_number(ch):
    return unicodedata.category(ch)[0] == 'N'


def _contraction_at(text, i):
    for c in _CONTRACTIONS:
        if text.startswith(c, i):
            return c
    return None


def pretokenize(text):
    """The GPT-2 split, hand-rolled.

        's|'t|'re|'ve|'m|'ll|'d| ?\\p{L}+| ?\\p{N}+| ?[^\\s\\p{L}\\p{N}]+|\\s+(?!\\S)|\\s+

    Python's `re` has no `\\p{L}`, and pulling in `regex` just for this would
    undo the point of the exercise, so the alternation is walked by hand. The
    order below IS the alternation order and matters: a space followed by a
    letter belongs to the letter run (` ?\\p{L}+`), which is why "epic drums"
    tokenizes as ['epic', ' drums'] and not ['epic', ' ', 'drums'].

    The last clause is the subtle one. `\\s+(?!\\S)` backtracks, so a run of k
    whitespace characters followed by a non-space yields k-1 characters and
    leaves the final space to be claimed as the next token's optional prefix. A
    run that reaches the end of the string is taken whole.
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "'":
            c = _contraction_at(text, i)
            if c is not None:
                out.append(c)
                i += len(c)
                continue
        # the optional single leading space of the three ` ?...` alternatives
        j = i + 1 if (text[i] == ' ' and i + 1 < n) else i
        ch = text[j]
        if _is_letter(ch):
            k = j
            while k < n and _is_letter(text[k]):
                k += 1
        elif _is_number(ch):
            k = j
            while k < n and _is_number(text[k]):
                k += 1
        elif not ch.isspace():
            k = j
            while k < n and not (text[k].isspace() or _is_letter(text[k])
                                 or _is_number(text[k])):
                k += 1
        else:
            k = i
            while k < n and text[k].isspace():
                k += 1
            if k < n and k - i > 1:
                k -= 1                       # leave the last space for the next token
        out.append(text[i:k])
        i = k
    return out


class ByteLevelBPETokenizer:
    """Reads a HuggingFace `tokenizer.json` (BPE model + RobertaProcessing)."""

    def __init__(self, path):
        spec = json.loads(Path(path).read_text(encoding='utf-8'))
        model = spec['model']
        self.vocab = model['vocab']
        merges = model['merges']
        # tokenizers wrote merges as "a b" strings in v1 files and as ["a","b"]
        # pairs in newer ones; both formats are in the wild for this model.
        if merges and isinstance(merges[0], str):
            merges = [tuple(m.split(' ', 1)) for m in merges]
        else:
            merges = [tuple(m) for m in merges]
        self.ranks = {m: i for i, m in enumerate(merges)}
        self.byte_encoder = _bytes_to_unicode()
        post = spec.get('post_processor') or {}
        self.bos_id = (post.get('cls') or ['<s>', 0])[1]
        self.eos_id = (post.get('sep') or ['</s>', 2])[1]
        self.pad_id = ((spec.get('padding') or {}).get('pad_id')
                       if spec.get('padding') else None)
        if self.pad_id is None:
            self.pad_id = self.vocab.get('<pad>', 1)
        self._cache = {}

    def _bpe(self, word):
        hit = self._cache.get(word)
        if hit is not None:
            return hit
        parts = list(word)
        while len(parts) > 1:
            best, at = None, None
            for i in range(len(parts) - 1):
                r = self.ranks.get((parts[i], parts[i + 1]))
                if r is not None and (best is None or r < best):
                    best, at = r, i
            if at is None:
                break
            parts[at:at + 2] = [parts[at] + parts[at + 1]]
        self._cache[word] = parts
        return parts

    def encode(self, text, max_length=None):
        """-> list of token ids, wrapped in <s> ... </s>."""
        ids = []
        for piece in pretokenize(text):
            mapped = ''.join(self.byte_encoder[b] for b in piece.encode('utf-8'))
            for tok in self._bpe(mapped):
                ids.append(self.vocab[tok])
        if max_length is not None and len(ids) > max_length - 2:
            # Only bites on inputs the reference cannot embed either -- CLAP's
            # text tower has 512 usable positions and indexes past the end
            # rather than truncating. Queries are a handful of words.
            ids = ids[:max_length - 2]
        return [self.bos_id] + ids + [self.eos_id]

    def encode_batch(self, texts, max_length=None):
        """-> (input_ids, attention_mask) int64 arrays, right-padded."""
        rows = [self.encode(t, max_length=max_length) for t in texts]
        width = max(len(r) for r in rows)
        ids = np.full((len(rows), width), self.pad_id, dtype=np.int64)
        mask = np.zeros((len(rows), width), dtype=np.int64)
        for i, r in enumerate(rows):
            ids[i, :len(r)] = r
            mask[i, :len(r)] = 1
        return ids, mask


# ----------------------------------------------------------------- backends

class OnnxTextEncoder:
    """The exported text tower + projection, run by onnxruntime."""

    backend = 'onnx'

    def __init__(self, directory=None, threads=None):
        import onnxruntime as ort

        self.dir = Path(directory or artefact_dir())
        self.manifest = json.loads((self.dir / MANIFEST_NAME).read_text(encoding='utf-8'))
        self.name = self.manifest.get('model', config_model_name())
        self.dim = int(self.manifest.get('dim', 512))
        self.max_length = int(self.manifest.get('max_length', 512))
        self.tokenizer = ByteLevelBPETokenizer(self.dir / TOKENIZER_NAME)

        so = ort.SessionOptions()
        # One query at a time on a NAS box that is also serving the dashboard:
        # let onnxruntime spread a single forward pass across a few cores but
        # not fight uvicorn's threadpool for all of them. 0 means "decide for
        # me", which on a 24-core rig oversubscribes for a 20-token sequence.
        so.intra_op_num_threads = int(threads or os.environ.get(
            'MUSIC_TEXT_ENCODER_THREADS', '4'))
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(self.dir / MODEL_NAME), so,
                                            providers=['CPUExecutionProvider'])
        self._lock = threading.Lock()

    def embed_text(self, texts, batch_size=64):
        """Same contract as `music_index.clap_model.Clap.embed_text`:
        list of strings -> (N, dim) float32 unit vectors."""
        texts = list(texts)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = []
        for i in range(0, len(texts), batch_size):
            ids, mask = self.tokenizer.encode_batch(texts[i:i + batch_size],
                                                    max_length=self.max_length)
            # InferenceSession.run is thread-safe, but the tokenizer's BPE cache
            # is not, and FastAPI runs sync routes on a threadpool.
            with self._lock:
                feats = self.session.run(
                    ['text_embeds'],
                    {'input_ids': ids, 'attention_mask': mask})[0]
            out.append(np.asarray(feats, dtype=np.float32))
        return l2norm(np.concatenate(out, axis=0))


class ClapTextEncoder:
    """Fallback: the full `ClapModel` from the indexer, as before.

    Kept so a dev checkout that has never run the export still answers text
    searches, and so the base rig -- which has torch anyway and may not have
    bothered exporting -- is never blocked on the artefact.
    """

    backend = 'clap'

    def __init__(self):
        if not config.add_indexer_to_path():
            raise RuntimeError(
                'no text encoder: neither an exported artefact in '
                f'{artefact_dir()} nor a music/indexer checkout to fall back on. '
                'Run music/indexer/export_text_encoder.py on the base rig.')
        from music_index.clap_model import Clap
        self.clap = Clap()
        self.name = self.clap.name
        self.dim = self.clap.dim

    def embed_text(self, texts, batch_size=64):
        return self.clap.embed_text(list(texts), batch_size=batch_size)


def artefact_available(directory=None):
    """True if a readable artefact of a version this loader understands exists."""
    d = Path(directory or artefact_dir())
    try:
        manifest = json.loads((d / MANIFEST_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if int(manifest.get('artefact_version', 0)) != ARTEFACT_VERSION:
        return False
    return (d / MODEL_NAME).is_file() and (d / TOKENIZER_NAME).is_file()


def load(directory=None):
    """Best available text encoder. -> OnnxTextEncoder or ClapTextEncoder.

    Never raises for a *missing* artefact -- that is the documented dev-checkout
    case and falls through to CLAP. It does raise if neither is usable, because
    silently returning something that cannot embed would surface as an empty
    result set, which looks like "nothing matched".
    """
    if artefact_available(directory):
        try:
            return OnnxTextEncoder(directory)
        except ImportError:
            # artefact present, onnxruntime is not: the deployment is
            # half-done. Say so, then carry on with whatever still works.
            print('  ! text encoder artefact found but onnxruntime is not '
                  'installed; falling back to the full ClapModel')
        except Exception as e:                        # noqa: BLE001
            print(f'  ! text encoder artefact unusable ({type(e).__name__}: {e}); '
                  'falling back to the full ClapModel')
    return ClapTextEncoder()
