"""Semantic (embedding) search -- schema v4, migrations/004_hybrid_search.sql.

Brute-force cosine similarity over pre-computed sentence embeddings stored as
raw float32 little-endian blobs in the `embeddings` table:
(source, source_id, video_id, model, dim, vec). Vectors are stored
L2-normalized (see migration 004's header), so cosine similarity is just a
dot product -- a full numpy matrix-vector multiply over even ~1e5-1e6 rows is
milliseconds, no ANN index needed at this scale.

Two "never 500 the endpoint" requirements shape this module:

1. `fastembed` (ONNX encoder, no torch) is an OPTIONAL dependency. If it
   isn't installed, or there are no embedding rows yet, semantic search
   contributes nothing and keyword search still works untouched -- every
   public entry point here returns [] rather than raising.
2. The query must be encoded with the SAME model that produced the stored
   vectors -- comparing vectors from two different embedding models is
   meaningless (different vector spaces, not just different quality). This
   module only ever loads embeddings for one configured model (DEFAULT_MODEL,
   overridable via BROLL_EMBEDDING_MODEL) and encodes queries with that same
   model; if the DB holds embeddings under a different model, the row count
   for *this* model is simply zero and semantic search quietly degrades to
   nothing rather than mixing vector spaces.

Model load (~10s the first time -- ONNX weights) is deliberately lazy: it
happens on the first semantic query, not at import or app-startup time, so
`uvicorn app.main:app` and the test suite don't pay that cost unless a
semantic query actually runs.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover -- numpy is a hard dependency in
    np = None         # pyproject.toml; this guard just avoids a hard crash
                       # if some deployment is missing it, matching the
                       # "never 500" posture of the rest of this module.

# The multilingual model measured in migrations/004_hybrid_search.sql's
# header (9/9 top-1 on a corpus sample: English "bulletproof vest" <->
# 防彈衣, Taiwanese 塞車 <-> mainland 堵車). Overridable via env so a future
# re-embed onto a different model needs no code change.
DEFAULT_MODEL = os.environ.get(
    "BROLL_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

# Candidate pool pulled from the full brute-force cosine pass before any
# category/flag filtering or RRF fusion narrows it down. Generous on
# purpose -- app.search filters this down further and RRF only cares about
# rank order, not the raw count.
DEFAULT_TOP_K = 200


def _load_fastembed_encoder(model_name: str) -> Any | None:
    """Import + construct the fastembed encoder for `model_name`. Isolated
    in its own function (rather than inlined) so tests can monkeypatch this
    exact call to inject a fake encoder instead of downloading a real model.
    Returns None if fastembed isn't installed.
    """
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None
    return TextEmbedding(model_name=model_name)


@dataclass
class _ModelIndex:
    """One model's worth of embeddings, loaded into a single matrix."""

    dim: int
    matrix: Any  # np.ndarray, shape (n, dim), float32, rows L2-normalized
    rows: list[tuple[str, int, int]]  # parallel to matrix rows: (source, source_id, video_id)


class SemanticSearch:
    """Process-wide cache: one embedding matrix for `model`, one lazily
    loaded encoder. Instances are meant to be long-lived (see
    get_semantic_search() below) -- reload is triggered only by a changed
    (db file, row count) pair, never rebuilt per request.
    """

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._index: _ModelIndex | None = None
        self._index_key: tuple[str, int] | None = None
        self._encoder: Any | None = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Drop all cached state. Used by tests between DBs/models -- normal
        request handling never needs this (the cache key already accounts
        for a changed DB file or row count)."""
        self._index = None
        self._index_key = None
        self._encoder = None

    # ---- availability -------------------------------------------------

    def available(self, conn: sqlite3.Connection) -> bool:
        """True if there is at least one embedding row for this instance's
        model -- a cheap COUNT(*), no matrix build, no encoder load."""
        if np is None:
            return False
        return self._count_for_model(conn) > 0

    def _count_for_model(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM embeddings WHERE model = ?", (self.model,)
        ).fetchone()
        return row[0] if row else 0

    def _db_identity(self, conn: sqlite3.Connection) -> str:
        # PRAGMA database_list -> rows of (seq, name, file); "file" is the
        # on-disk path for the 'main' schema (empty string for :memory:).
        # Included in the cache key so distinct DBs (e.g. one per test) with
        # a coincidentally equal row count never share a cached matrix.
        row = conn.execute("PRAGMA database_list").fetchone()
        return row[2] if row else ""

    # ---- index (numpy matrix) cache ------------------------------------

    def _ensure_index(self, conn: sqlite3.Connection) -> _ModelIndex | None:
        count = self._count_for_model(conn)
        if count == 0:
            self._index = None
            self._index_key = None
            return None

        key = (self._db_identity(conn), count)
        if self._index is not None and self._index_key == key:
            return self._index

        rows = conn.execute(
            "SELECT source, source_id, video_id, dim, vec FROM embeddings WHERE model = ?",
            (self.model,),
        ).fetchall()
        dim = rows[0]["dim"]
        matrix = np.zeros((len(rows), dim), dtype=np.float32)
        sources: list[tuple[str, int, int]] = []
        write_i = 0
        for row in rows:
            vec = np.frombuffer(row["vec"], dtype="<f4")
            if vec.shape[0] != dim:
                # Corrupt/mismatched-dim row -- skip rather than crash the
                # whole index; one bad embedding shouldn't take out search.
                continue
            matrix[write_i, :] = vec
            sources.append((row["source"], row["source_id"], row["video_id"]))
            write_i += 1
        matrix = matrix[:write_i]

        self._index = _ModelIndex(dim=dim, matrix=matrix, rows=sources)
        self._index_key = key
        return self._index

    # ---- encoder (fastembed) lazy load ---------------------------------

    def _ensure_encoder(self) -> Any | None:
        if self._encoder is not None:
            return self._encoder
        self._encoder = _load_fastembed_encoder(self.model)
        return self._encoder

    def encode_query(self, text: str) -> Any | None:
        """Return an L2-normalized float32 vector for `text`, or None if
        fastembed is unavailable. Never raises -- an encoder-side failure
        (bad ONNX runtime, etc.) degrades to "no semantic contribution"
        rather than a 500."""
        if np is None:
            return None
        with self._lock:
            encoder = self._ensure_encoder()
        if encoder is None:
            return None
        try:
            (vec,) = list(encoder.embed([text]))
        except Exception:
            return None
        vec = np.asarray(vec, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec

    # ---- search ---------------------------------------------------------

    def search(
        self,
        conn: sqlite3.Connection,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        allowed_video_ids: set[int] | None = None,
        source_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to `top_k` hits, best first:
        [{"source": "segment"|"transcript", "source_id": int, "video_id": int, "score": float}]

        `allowed_video_ids`, if given, restricts the candidate pool to those
        video ids *before* the top-k cut (rather than after), so a category/
        flag filter narrow enough to exclude the naive top-k doesn't starve
        semantic results for that query -- correct at this component's scale
        (brute-force numpy pass), see module docstring.

        `source_filter`, if given ("segment" or "transcript"), restricts the
        candidate pool to embeddings.source rows of that kind -- same masking
        approach as `allowed_video_ids` (row metadata is already cached
        alongside the matrix in `index.rows`, so this is a cheap boolean mask
        over the existing cache rather than a second cache or a Python-side
        filter over a re-fetched full matrix). Used by app.search's
        sources="visual"|"transcript" filter so mode="semantic" only ever
        considers the requested kind of embedding.

        Returns [] whenever semantic search cannot run for any reason (no
        numpy, no fastembed, no embeddings for this model, empty query,
        encode failure) -- callers can treat [] as "no semantic
        contribution" unconditionally, this method must never raise.
        """
        if np is None or not query or not query.strip():
            return []

        with self._lock:
            index = self._ensure_index(conn)
        if index is None or index.matrix.shape[0] == 0:
            return []

        query_vec = self.encode_query(query)
        if query_vec is None or query_vec.shape[0] != index.dim:
            return []

        scores = index.matrix @ query_vec

        if allowed_video_ids is not None or source_filter is not None:
            mask = np.fromiter(
                (
                    (allowed_video_ids is None or row[2] in allowed_video_ids)
                    and (source_filter is None or row[0] == source_filter)
                    for row in index.rows
                ),
                dtype=bool,
                count=len(index.rows),
            )
            scores = np.where(mask, scores, -np.inf)

        k = min(top_k, scores.shape[0])
        if k <= 0:
            return []
        top_idx = np.argpartition(-scores, k - 1)[:k]
        # Stable, deterministic tie-break: sort the top-k slice by
        # (-score, source_id) rather than relying on argpartition/argsort's
        # unspecified order among exact ties.
        top_idx = sorted(top_idx.tolist(), key=lambda i: (-scores[i], index.rows[i][1]))

        hits: list[dict[str, Any]] = []
        for i in top_idx:
            score = float(scores[i])
            if score == -np.inf:
                continue  # filtered out by allowed_video_ids
            source, source_id, video_id = index.rows[i]
            hits.append(
                {"source": source, "source_id": source_id, "video_id": video_id, "score": score}
            )
        return hits


# Module-level singleton shared by app.search -- see class docstring for why
# this must not be rebuilt per-request. Tests should call reset() (or use the
# `reset_semantic_cache` autouse fixture in tests/conftest.py) between DBs.
_default_instance: SemanticSearch | None = None


def get_semantic_search() -> SemanticSearch:
    global _default_instance
    if _default_instance is None:
        _default_instance = SemanticSearch()
    return _default_instance
