"""Semantic embeddings via fastembed (ONNX runtime — no torch).

The complement to broll_index/normalize.py: keyword normalization is exact but
literal (a query has to share characters/tokens with the source text); embeddings
are fuzzy but cross-lingual, matching on *meaning*. See migrations/004_hybrid_search.sql
(header comment) and docs/indexing-findings.md for the measurements behind this design:
multilingual embeddings retrieve English "bulletproof vest" from 防彈衣, and Traditional
塞車 from Simplified 堵車 footage — 9/9 top-1 on a corpus sample with the default model.

Vectors are float32 and L2-normalized at embed time, so cosine similarity reduces to a
plain dot product wherever they're compared later (see `embeddings.vec` in
migrations/004_hybrid_search.sql — brute-force numpy scan, no vector extension needed
at this corpus scale).

fastembed is an OPTIONAL import, same reasoning as jieba/opencc in normalize.py: a
machine without it (or without network access to fetch the model on first use) must
not crash the indexer — the `embed` pipeline stage degrades to a no-op and logs once.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DIM = 384

try:
    from fastembed import TextEmbedding

    _FASTEMBED_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via monkeypatched flag in tests
    TextEmbedding = None  # type: ignore[assignment,misc]
    _FASTEMBED_AVAILABLE = False

_lock = threading.Lock()
_model_cache: dict[str, Any] = {}
_warned = False


def fastembed_available() -> bool:
    return _FASTEMBED_AVAILABLE


def _warn_once() -> None:
    global _warned
    if not _warned:
        logger.warning(
            "embed: fastembed is not installed — semantic embeddings are disabled "
            "(pip install fastembed to enable this stage)"
        )
        _warned = True


def get_model(model_name: str = DEFAULT_MODEL) -> Any:
    """Load (and cache) a fastembed TextEmbedding model.

    Model init/first-use download is slow (network fetch + ONNX session setup), so this
    is lazy and cached per model name — called at most once per model per process.
    """
    if not _FASTEMBED_AVAILABLE:
        _warn_once()
        raise RuntimeError("fastembed is not installed")
    with _lock:
        model = _model_cache.get(model_name)
        if model is None:
            model = TextEmbedding(model_name=model_name)
            _model_cache[model_name] = model
        return model


def embed_texts(
    texts: list[str], model_name: str = DEFAULT_MODEL, batch_size: int = 64
) -> np.ndarray:
    """Embed a batch of texts. Returns float32, L2-normalized vectors, shape (n, dim).

    Passed as one batched call (fastembed handles internal batching via `batch_size`)
    rather than looped one text at a time — looping would pay per-call ONNX overhead
    for every row.
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    if not _FASTEMBED_AVAILABLE:
        _warn_once()
        raise RuntimeError("fastembed is not installed")

    model = get_model(model_name)
    vectors = np.array(list(model.embed(texts, batch_size=batch_size)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # avoid divide-by-zero for a (theoretical) all-zero vector
    return (vectors / norms).astype(np.float32)


def to_blob(vec: np.ndarray) -> bytes:
    """Serialize a vector to raw float32 little-endian bytes, for `embeddings.vec`."""
    return np.asarray(vec, dtype="<f4").tobytes()


def from_blob(blob: bytes, dim: int) -> np.ndarray:
    """Inverse of `to_blob`. Raises if the blob doesn't contain exactly `dim` floats."""
    arr = np.frombuffer(blob, dtype="<f4")
    if arr.size != dim:
        raise ValueError(f"embedding blob has {arr.size} float32 values, expected {dim}")
    return arr.astype(np.float32)
