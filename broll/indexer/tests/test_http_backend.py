from __future__ import annotations

import pytest

from broll_index.storage.http_backend import HttpBackend


class FakeResponse:
    def __init__(self, json_data=None):
        self._json = json_data or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return FakeResponse({"id": 999})

    def get(self, url, timeout=None):
        self.gets.append(url)
        return FakeResponse([{"slug": "military/naval", "label": "Naval", "description": ""}])


@pytest.fixture
def http_backend(tmp_path, schema_path):
    session = FakeSession()
    backend = HttpBackend(
        "http://example.local/api", "secret-token", tmp_path / "local.db",
        schema_path=schema_path, session=session,
    )
    yield backend, session
    backend.close()


@pytest.fixture
def http_backend_v4(tmp_path, schema_path_v4):
    # search_norm/embeddings need a v4 local shadow (schema_path is v3) — see
    # conftest.py's schema_path_v4 fixture.
    session = FakeSession()
    backend = HttpBackend(
        "http://example.local/api", "secret-token", tmp_path / "local_v4.db",
        schema_path=schema_path_v4, session=session,
    )
    yield backend, session
    backend.close()


def test_upsert_video_posts_to_ingest_and_updates_local_shadow(http_backend):
    backend, session = http_backend
    video_id = backend.upsert_video("broll", "clip.mov", status="discovered", size_bytes=100)

    assert isinstance(video_id, int)
    assert session.posts[-1][0] == "http://example.local/api/ingest/video"
    assert session.posts[-1][1]["share"] == "broll"
    assert session.posts[-1][1]["rel_path"] == "clip.mov"

    row = backend.get_video(video_id)
    assert row["status"] == "discovered"


def test_update_video_reposts_full_video_row(http_backend):
    backend, session = http_backend
    vid = backend.upsert_video("broll", "clip.mov", status="discovered")
    session.posts.clear()

    backend.update_video(vid, status="probed", duration_s=5.0)
    assert session.posts[-1][0] == "http://example.local/api/ingest/video"
    assert session.posts[-1][1]["status"] == "probed"
    assert session.posts[-1][1]["duration_s"] == 5.0


def test_write_index_result_posts_to_ingest_index(http_backend):
    backend, session = http_backend
    vid = backend.upsert_video("broll", "clip.mov", status="proxied")
    backend.write_index_result(
        vid, themes=["a"], quality_flags=[], category_hint=None, segments=[], model="m"
    )
    url, payload = session.posts[-1]
    assert url == "http://example.local/api/ingest/index"
    assert payload["video_id"] == vid
    assert payload["themes"] == ["a"]


def test_record_moved_posts_to_ingest_moved(http_backend):
    backend, session = http_backend
    vid = backend.upsert_video("broll", "inbox/clip.mov", status="indexed", in_inbox=1, category="cat/a")
    backend.record_moved(vid, "cat/a/clip.mov")
    url, payload = session.posts[-1]
    assert url == "http://example.local/api/ingest/moved"
    assert payload == {"video_id": vid, "new_rel_path": "cat/a/clip.mov"}
    assert backend.get_video(vid)["in_inbox"] == 0


def test_get_categories_reads_from_remote(http_backend):
    backend, session = http_backend
    cats = backend.get_categories()
    assert cats == [{"slug": "military/naval", "label": "Naval", "description": ""}]
    assert session.gets[-1] == "http://example.local/api/categories"


def test_apply_taxonomy_raises_not_implemented(http_backend):
    backend, session = http_backend
    with pytest.raises(NotImplementedError, match="no endpoint"):
        backend.apply_taxonomy([{"slug": "a/b", "label": "AB", "description": ""}])


# ---------------------------------------------------------------------------
# hybrid search (v4): reads served from local shadow, writes raise NotImplementedError
# but still land in the local shadow first (same precedent as write_transcript)
# ---------------------------------------------------------------------------

def test_get_segments_and_transcript_segments_read_from_local_shadow(http_backend_v4):
    backend, session = http_backend_v4
    vid = backend.upsert_video("broll", "clip.mov", status="proxied")
    backend.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None,
        segments=[{"t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [], "setting": "", "motion": ""}],
        model="m",
    )
    segs = backend.get_segments(vid)
    assert len(segs) == 1
    assert segs[0]["description"] == "d"


def test_update_search_norm_writes_local_shadow_then_raises(http_backend_v4):
    backend, session = http_backend_v4
    vid = backend.upsert_video("broll", "clip.mov", status="proxied")
    backend.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None,
        segments=[{"t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [], "setting": "", "motion": ""}],
        model="m",
    )
    seg_id = backend.get_segments(vid)[0]["id"]

    with pytest.raises(NotImplementedError, match="ingest API"):
        backend.update_search_norm("segment", seg_id, "d normalized")

    # local shadow was still updated before the raise
    assert backend.get_segments(vid)[0]["search_norm"] == "d normalized"


def test_upsert_embedding_writes_local_shadow_then_raises(http_backend_v4):
    backend, session = http_backend_v4
    vid = backend.upsert_video("broll", "clip.mov", status="proxied")

    with pytest.raises(NotImplementedError, match="ingest API"):
        backend.upsert_embedding("segment", 1, vid, "model-a", 3, b"\x00\x01\x02")

    assert backend.get_embedding_models(vid) == {("segment", 1): "model-a"}
