from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fuzzy, semantic  # noqa: E402
from app.db import ensure_schema, get_db, open_connection  # noqa: E402
from app.main import app  # noqa: E402

# One value for the whole suite, matched by the `client` fixture's default
# header. Long enough to also satisfy the dashboard gate's 24-char floor, so a
# test that reuses it against ccsync_dashboard.broll.check_ingest_token passes.
INGEST_TOKEN = "test-ingest-token-0123456789abcdef"


@pytest.fixture(autouse=True)
def reset_hybrid_search_caches():
    """app.semantic.SemanticSearch and app.fuzzy.VocabularyCache are
    process-wide singletons (by design -- see their module docstrings: model
    load is expensive and must not happen per-request). Each test gets a
    fresh DATA_ROOT/db file, so without this reset a cached numpy matrix or
    vocabulary built against one test's DB could leak into the next test
    that happens to hash to the same (db path, row count) cache key, or --
    for the encoder -- simply retain a monkeypatched fake from a prior test.
    """
    semantic.get_semantic_search().reset()
    fuzzy.get_vocabulary_cache().reset()
    yield
    semantic.get_semantic_search().reset()
    fuzzy.get_vocabulary_cache().reset()


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    """Fresh DATA_ROOT per test, with a schema-applied DB."""
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path))
    # The ingest routes are fail-closed since 2026-08-17 (no token = 503), so
    # the suite runs configured like a deployment rather than in the dev mode
    # that no longer exists. The `client` fixture sends the matching header on
    # every request; tests about the gate itself build their own bare client.
    monkeypatch.setenv("BROLL_INGEST_TOKEN", INGEST_TOKEN)
    ensure_schema(tmp_path / "broll.db")
    return tmp_path


@pytest.fixture()
def conn(data_root):
    connection = open_connection(data_root / "broll.db")
    yield connection
    connection.close()


@pytest.fixture()
def client(data_root, conn):
    """TestClient wired to reuse the same connection/db as the `conn` fixture,
    so tests can seed data directly and then hit the API in the same test.
    """

    def _override():
        yield conn

    app.dependency_overrides[get_db] = _override
    with TestClient(app, headers={"X-Ingest-Token": INGEST_TOKEN}) as c:
        yield c
    app.dependency_overrides.clear()
