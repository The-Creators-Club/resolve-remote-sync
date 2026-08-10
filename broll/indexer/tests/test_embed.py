from __future__ import annotations

import numpy as np
import pytest

from broll_index import embed


# ---------------------------------------------------------------------------
# blob round-trip — pure logic, no model involved
# ---------------------------------------------------------------------------

def test_to_blob_from_blob_round_trip_preserves_values_and_dtype():
    vec = np.array([0.1, -0.2, 0.3, 0.4], dtype=np.float32)
    blob = embed.to_blob(vec)
    assert isinstance(blob, bytes)

    restored = embed.from_blob(blob, dim=4)
    assert restored.dtype == np.float32
    np.testing.assert_allclose(restored, vec, rtol=1e-6)


def test_to_blob_accepts_non_float32_input_and_coerces():
    vec = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    blob = embed.to_blob(vec)
    restored = embed.from_blob(blob, dim=3)
    assert restored.dtype == np.float32
    np.testing.assert_allclose(restored, [1.0, 2.0, 3.0])


def test_from_blob_wrong_dim_raises():
    vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    blob = embed.to_blob(vec)
    with pytest.raises(ValueError, match="expected 4"):
        embed.from_blob(blob, dim=4)


def test_embed_texts_empty_list_returns_empty_array():
    result = embed.embed_texts([])
    assert result.shape == (0, 0)


# ---------------------------------------------------------------------------
# graceful degradation — must never crash the indexer
# ---------------------------------------------------------------------------

def test_fastembed_unavailable_flag_reported():
    # Whatever the real availability is on this machine, the accessor must not raise.
    assert embed.fastembed_available() in (True, False)


def test_embed_texts_raises_clearly_when_fastembed_unavailable(monkeypatch):
    monkeypatch.setattr(embed, "_FASTEMBED_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="fastembed is not installed"):
        embed.embed_texts(["hello"])


def test_get_model_raises_clearly_when_fastembed_unavailable(monkeypatch):
    monkeypatch.setattr(embed, "_FASTEMBED_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="fastembed is not installed"):
        embed.get_model()


def test_degradation_warns_only_once(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(embed, "_FASTEMBED_AVAILABLE", False)
    monkeypatch.setattr(embed, "_warned", False)

    with caplog.at_level(logging.WARNING, logger="broll_index.embed"):
        with pytest.raises(RuntimeError):
            embed.embed_texts(["a"])
        caplog.clear()
        with pytest.raises(RuntimeError):
            embed.embed_texts(["b"])

    assert caplog.records == []


# ---------------------------------------------------------------------------
# real model — network/cache dependent, must never block the rest of the suite
# ---------------------------------------------------------------------------

def _model_is_cached() -> bool:
    """Best-effort check: try to load the default model with local_files_only, so a
    real network fetch is never attempted just to run this check."""
    if not embed.fastembed_available():
        return False
    try:
        from fastembed import TextEmbedding

        TextEmbedding(model_name=embed.DEFAULT_MODEL, local_files_only=True)
        return True
    except Exception:
        return False


@pytest.mark.slow
def test_embed_texts_are_l2_normalized():
    if not _model_is_cached():
        pytest.skip("embedding model not cached locally — skipping without network")
    vectors = embed.embed_texts(["hello world", "測試中文句子"], model_name=embed.DEFAULT_MODEL)
    norms = np.linalg.norm(vectors, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-4)


@pytest.mark.slow
def test_cosine_of_text_with_itself_is_approximately_one():
    if not _model_is_cached():
        pytest.skip("embedding model not cached locally — skipping without network")
    vectors = embed.embed_texts(["bulletproof vest", "bulletproof vest"], model_name=embed.DEFAULT_MODEL)
    cosine = float(np.dot(vectors[0], vectors[1]))
    assert cosine == pytest.approx(1.0, abs=1e-3)


@pytest.mark.slow
def test_cross_lingual_similarity_higher_than_unrelated():
    if not _model_is_cached():
        pytest.skip("embedding model not cached locally — skipping without network")
    vectors = embed.embed_texts(
        ["bulletproof vest", "防彈衣", "banana bread recipe"], model_name=embed.DEFAULT_MODEL
    )
    related = float(np.dot(vectors[0], vectors[1]))
    unrelated = float(np.dot(vectors[0], vectors[2]))
    assert related > unrelated
