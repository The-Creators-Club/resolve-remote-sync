"""The text-tower-only query encoder.

Three tiers, because the three things that can break need different machinery
to catch them:

  * tokenizer/pretokenizer unit tests -- pure Python, no artefact, no torch.
    A tokenizer that disagrees with transformers on one odd character produces
    a perfectly plausible embedding of the wrong string, so these are goldens
    captured from the real tokenizer rather than round-trips of our own output.
  * artefact tests -- need `music/web/data/text_encoder/` and onnxruntime, and
    skip without them. They pin the thing the whole port step is for: the
    artefact path embeds text WITHOUT importing torch.
  * the numerical check against the full ClapModel -- needs torch, so it skips
    in this venv (which deliberately has none) and runs on the base rig. The
    exporter runs the same check and refuses to write a drifting artefact, so
    this is the belt to that braces.

The artefact directory is resolved from `config.WEB_DIR`, not from
`text_encoder.artefact_dir()`: conftest repoints DATA_ROOT at a throwaway
directory before anything is imported, and the artefact is not throwaway --
it is 500 MB that took the base rig a minute to write.
"""
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pytest

from musicweb import config
from musicweb import text_encoder as te

ARTEFACT_DIR = Path(os.environ.get('MUSIC_TEXT_ENCODER_DIR')
                    or config.WEB_DIR / 'data' / 'text_encoder')

# Captured from transformers' own tokenizer for laion/larger_clap_music_and_speech
# (RobertaTokenizer, byte-level BPE). Chosen to cover what a hand-rolled split
# gets wrong: contractions, digits mixed with letters, punctuation runs, the
# empty string, whitespace-only, runs of spaces (the `\s+(?!\S)` backtrack),
# leading/trailing spaces, and multi-byte UTF-8.
GOLDEN_IDS = [
    ('epic climax with drums', [0, 2462, 636, 29885, 19, 21072, 2]),
    ('drums', [0, 10232, 8014, 2]),
    ('a', [0, 102, 2]),
    ('', [0, 2]),
    ('   ', [0, 1437, 1437, 1437, 2]),
    ("don't stop the beat", [0, 7254, 75, 912, 5, 1451, 2]),
    ('80s synth-pop', [0, 2940, 29, 38668, 12, 15076, 2]),
    ('a 3/4 waltz, gentle', [0, 102, 155, 73, 306, 885, 3967, 329, 6, 16634, 2]),
    ('caf\xe9 accordion, parisian',
     [0, 438, 2001, 1140, 10170, 1499, 6, 2242, 354, 811, 2]),
    ('尋找寶島 opening theme',
     [0, 47842, 13859, 48548, 4726, 48420, 19002, 42393, 15264, 19002, 1273, 4782, 2]),
    ('foley   whoosh', [0, 21466, 607, 1437, 1437, 54, 5212, 2]),
    ('  leading and trailing spaces  ',
     [0, 1437, 981, 8, 12564, 5938, 1437, 1437, 2]),
    ('ROCK N ROLL', [0, 500, 13181, 234, 10033, 6006, 2]),
    ('piano & strings (soft)', [0, 642, 5472, 359, 22052, 36, 24810, 43, 2]),
    ('trailer riser -- 5 seconds', [0, 9738, 10329, 910, 5999, 480, 195, 2397, 2]),
]


def _installed(name):
    return importlib.util.find_spec(name) is not None


artefact = pytest.mark.skipif(
    not te.artefact_available(ARTEFACT_DIR) or not _installed('onnxruntime'),
    reason=f'no usable text encoder artefact at {ARTEFACT_DIR} (or no '
           'onnxruntime); run music/indexer/export_text_encoder.py on the base rig')

needs_torch = pytest.mark.skipif(
    not _installed('torch'),
    reason='needs torch/transformers -- this venv deliberately has neither; '
           'run it in the indexer venv on the base rig')


@pytest.fixture(scope='module')
def encoder():
    return te.OnnxTextEncoder(ARTEFACT_DIR)


@pytest.fixture(scope='module')
def tokenizer():
    return te.ByteLevelBPETokenizer(ARTEFACT_DIR / te.TOKENIZER_NAME)


# ---------------------------------------------------------------- pretokenize

def test_a_space_belongs_to_the_following_word():
    """` ?\\p{L}+` beats the whitespace alternatives, so the space rides along
    with the next token. Getting this backwards turns every multi-word query
    into a different sequence of ids."""
    assert te.pretokenize('epic drums') == ['epic', ' drums']


def test_a_run_of_spaces_leaves_the_last_one_for_the_next_token():
    """The `\\s+(?!\\S)` backtrack: three spaces before a word yield two, and
    the third prefixes the word."""
    assert te.pretokenize('a   b') == ['a', '  ', ' b']


def test_trailing_whitespace_is_taken_whole():
    assert te.pretokenize('a  ') == ['a', '  ']
    assert te.pretokenize(' ') == [' ']


def test_contractions_split_off():
    assert te.pretokenize("don't") == ['don', "'t"]
    assert te.pretokenize("we'll go") == ['we', "'ll", ' go']


def test_letters_numbers_and_punctuation_are_separate_runs():
    assert te.pretokenize('80s') == ['80', 's']
    assert te.pretokenize('a 3/4 waltz') == ['a', ' 3', '/', '4', ' waltz']


def test_empty_string():
    assert te.pretokenize('') == []


def test_non_ascii_is_a_letter_run():
    assert te.pretokenize('caf\xe9 bar') == ['caf\xe9', ' bar']
    assert te.pretokenize('尋找 theme') == ['尋找', ' theme']


def test_pretokenize_is_lossless():
    """Whatever the split, concatenating it must give the input back --
    otherwise characters are being silently dropped from queries."""
    for text, _ in GOLDEN_IDS:
        assert ''.join(te.pretokenize(text)) == text


# ------------------------------------------------------------------ tokenizer

@artefact
def test_tokenizer_matches_golden_ids(tokenizer):
    for text, want in GOLDEN_IDS:
        assert tokenizer.encode(text) == want, repr(text)


@artefact
def test_tokenizer_wraps_in_bos_eos(tokenizer):
    ids = tokenizer.encode('drums')
    assert ids[0] == tokenizer.bos_id == 0
    assert ids[-1] == tokenizer.eos_id == 2


@artefact
def test_batch_is_right_padded_with_the_pad_id(tokenizer):
    ids, mask = tokenizer.encode_batch(['epic climax with drums', 'soft'])
    assert ids.shape == mask.shape == (2, 7)
    assert list(ids[0]) == [0, 2462, 636, 29885, 19, 21072, 2]
    assert list(ids[1]) == [0, 24810, 2, 1, 1, 1, 1]      # <pad> is 1
    assert list(mask[0]) == [1] * 7
    assert list(mask[1]) == [1, 1, 1, 0, 0, 0, 0]
    assert ids.dtype == np.int64 and mask.dtype == np.int64


@artefact
def test_absurdly_long_input_is_truncated_not_crashed(tokenizer):
    """CLAP has 512 usable positions and indexes past the end rather than
    truncating, so a pasted essay must not reach the model."""
    ids = tokenizer.encode('epic drums ' * 500, max_length=512)
    assert len(ids) == 512
    assert ids[0] == 0 and ids[-1] == 2


# ------------------------------------------------------------------- artefact

def test_artefact_dir_follows_the_data_root_and_the_env(monkeypatch):
    monkeypatch.delenv('MUSIC_TEXT_ENCODER_DIR', raising=False)
    assert te.artefact_dir() == config.DATA_ROOT / 'text_encoder'
    monkeypatch.setenv('MUSIC_TEXT_ENCODER_DIR', r'/somewhere/else')
    assert te.artefact_dir() == Path('/somewhere/else')


def test_missing_artefact_is_not_available(tmp_path):
    assert te.artefact_available(tmp_path) is False


@artefact
def test_manifest_is_the_version_this_loader_understands():
    m = json.loads((ARTEFACT_DIR / te.MANIFEST_NAME).read_text(encoding='utf-8'))
    assert m['artefact_version'] == te.ARTEFACT_VERSION
    assert m['format'] == 'onnx'
    assert m['dim'] == 512
    # the exporter's own cosine check against the full ClapModel, recorded at
    # export time -- an artefact below the threshold is never written
    assert m['check']['min_cosine'] >= 0.999


@artefact
def test_stale_artefact_version_is_treated_as_absent(tmp_path):
    """A manifest from a future layout must degrade to the CLAP fallback rather
    than load half of something."""
    m = json.loads((ARTEFACT_DIR / te.MANIFEST_NAME).read_text(encoding='utf-8'))
    m['artefact_version'] = te.ARTEFACT_VERSION + 1
    (tmp_path / te.MANIFEST_NAME).write_text(json.dumps(m), encoding='utf-8')
    (tmp_path / te.MODEL_NAME).write_bytes(b'')
    (tmp_path / te.TOKENIZER_NAME).write_bytes(b'')
    assert te.artefact_available(tmp_path) is False


@artefact
def test_embeds_a_unit_vector_of_the_right_shape(encoder):
    v = encoder.embed_text(['epic orchestral climax'])
    assert v.shape == (1, encoder.dim) == (1, 512)
    assert v.dtype == np.float32
    assert np.linalg.norm(v[0]) == pytest.approx(1.0, abs=1e-5)


@artefact
def test_empty_input_returns_an_empty_matrix(encoder):
    assert encoder.embed_text([]).shape == (0, 512)


@artefact
def test_is_deterministic(encoder):
    a = encoder.embed_text(['sparse ominous drone under an interview'])
    b = encoder.embed_text(['sparse ominous drone under an interview'])
    assert np.array_equal(a, b)


@artefact
def test_padding_does_not_change_a_query(encoder):
    """Batching pads the short queries; if the attention mask were wrong a
    query's vector would depend on what it was batched with, which would make
    results depend on request shape."""
    texts = ['drums', 'a long sustained cinematic cue with choir and low brass']
    batch = encoder.embed_text(texts)
    for i, t in enumerate(texts):
        alone = encoder.embed_text([t])[0]
        assert float(batch[i] @ alone) == pytest.approx(1.0, abs=1e-5)


@artefact
def test_the_artefact_path_never_imports_torch():
    """The point of the whole exercise: 675 MB of torch must not be what
    answers a search in the container.

    In a subprocess, because sys.modules is process-wide and the base rig runs
    this same file in a venv where the ClapModel tests do import torch.
    """
    src = textwrap.dedent(f'''
        import sys
        sys.path.insert(0, {str(config.WEB_DIR)!r})
        from musicweb import text_encoder as te
        assert 'torch' not in sys.modules, 'import pulled in torch'
        assert 'onnxruntime' not in sys.modules, 'import pulled in onnxruntime'
        enc = te.OnnxTextEncoder({str(ARTEFACT_DIR)!r})
        v = enc.embed_text(['dark futuristic technology'])
        assert v.shape == (1, 512), v.shape
        assert enc.backend == 'onnx'
        for mod in ('torch', 'transformers', 'music_index'):
            assert mod not in sys.modules, mod
        print('OK')
    ''')
    r = subprocess.run([sys.executable, '-c', src], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


def test_the_lock_guards_the_tokenizer_and_not_the_session():
    """MUSIC-6 (2026-08-11): the lock was around the wrong half.

    `InferenceSession.run` is thread-safe; the tokenizer's BPE cache is not.
    Guarding the session serialised every query behind a 30 ms forward pass
    AND left the unsafe cache unprotected -- benign under the GIL, wrong under
    a free-threaded build. No artefact and no onnxruntime here: the encoder is
    built without __init__ and given the two collaborators it locks around.
    """
    enc = te.OnnxTextEncoder.__new__(te.OnnxTextEncoder)
    enc.dim, enc.max_length = 4, 32
    enc._lock = threading.Lock()
    held = {}

    class FakeTokenizer:
        def encode_batch(self, texts, max_length=None):
            held['encode_batch'] = enc._lock.locked()
            n = len(texts)
            return (np.zeros((n, 3), dtype=np.int64), np.ones((n, 3), dtype=np.int64))

    class FakeSession:
        def run(self, names, feed):
            held['session.run'] = enc._lock.locked()
            return [np.ones((feed['input_ids'].shape[0], 4), dtype=np.float32)]

    enc.tokenizer, enc.session = FakeTokenizer(), FakeSession()

    out = enc.embed_text(['tense driving synth pulse'])
    assert out.shape == (1, 4)
    assert held['encode_batch'] is True, 'the BPE cache is the part that is unsafe'
    assert held['session.run'] is False, 'the thread-safe half must not serialise'


# --------------------------------------------------------------- search rewire

def test_index_encoder_is_lazy():
    """Neither model may be built by constructing the index -- the server has
    to start instantly and most requests never search by text."""
    from musicweb import db
    from musicweb.search import Index
    idx = Index(db.con())
    assert idx._encoder is None
    assert idx._clap is None            # ingest's full model, deliberately separate


def test_text_search_goes_through_the_encoder():
    """search.py must ask `encoder`, not `clap` -- the fake below has no audio
    tower, which is exactly the container's situation."""
    from musicweb import db
    from musicweb.search import Index

    class Fake:
        backend = 'fake'

        def __init__(self):
            self.calls = []

        def embed_text(self, texts, batch_size=64):
            self.calls.extend(texts)
            v = np.zeros((len(texts), 8), dtype=np.float32)
            v[:, 0] = 1.0
            return v

    idx = Index(db.con())
    fake = Fake()
    idx._encoder = fake
    hits = idx.text_search('anything at all', k=3)
    assert fake.calls == ['anything at all']
    assert len(hits) == 3
    assert idx._clap is None            # never touched the full model


# ------------------------------------------------------- vs the full ClapModel

@artefact
@needs_torch
def test_matches_the_full_clap_model():
    """The check that makes the whole change safe: an artefact that shifted the
    embedding would silently reorder every search result.

    Same corpus and same threshold as the exporter, imported from it so the two
    cannot drift apart.
    """
    assert config.add_indexer_to_path()
    from export_text_encoder import MIN_COSINE, QUERIES, reference_embeddings
    from music_index.clap_model import Clap

    assert len(QUERIES) >= 40
    got = te.OnnxTextEncoder(ARTEFACT_DIR).embed_text(QUERIES)
    ref = reference_embeddings(Clap(device='cpu'), QUERIES)
    cos = np.sum(got * ref, axis=1)
    assert cos.min() >= MIN_COSINE, (
        f'min cosine {cos.min():.7f} on {QUERIES[int(np.argmin(cos))]!a}')


@artefact
@needs_torch
def test_tokenizer_matches_transformers(tokenizer):
    from transformers import AutoTokenizer

    assert config.add_indexer_to_path()
    from export_text_encoder import QUERIES

    m = json.loads((ARTEFACT_DIR / te.MANIFEST_NAME).read_text(encoding='utf-8'))
    hf = AutoTokenizer.from_pretrained(m['model'])
    for q in QUERIES:
        assert tokenizer.encode(q) == list(hf(q)['input_ids']), repr(q)
