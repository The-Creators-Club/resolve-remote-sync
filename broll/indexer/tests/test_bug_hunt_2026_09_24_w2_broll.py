"""bug-broll-2 (2026-09-24 hunt, wave 2): HttpBackend posted the LOCAL shadow
id to /api/ingest/index and /api/ingest/moved.

The shadow database and the web app's canonical broll.db mint ids
independently (the module docstring says so), so the local number names some
other clip over there: its segments and themes were replaced by the new
clip's description, and a sort renamed it. These pin that the id sent is the
one /ingest/video answered with, that the clip's (share, rel_path) rides
along for a current server to resolve by, and that with no recorded
canonical id the number sent is one no row carries.
"""
from __future__ import annotations

import pytest

from broll_index.storage.http_backend import HttpBackend


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _Canonical:
    """A web app whose archive already holds clips 1..15000: the first new
    clip it is told about becomes 15001, while the indexer's fresh shadow
    numbers that same clip 1."""

    def __init__(self):
        self.next_id = 15001
        self.ids: dict[tuple[str, str], int] = {}
        self.posts = []
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        if url.endswith("/ingest/video"):
            key = (json["share"], json["rel_path"])
            if key not in self.ids:
                self.ids[key] = self.next_id
                self.next_id += 1
            return _Resp({"id": self.ids[key]})
        return _Resp({"ok": True})


@pytest.fixture
def backend(tmp_path, schema_path):
    session = _Canonical()
    b = HttpBackend("http://nas/api", "tok", tmp_path / "shadow.db",
                    schema_path=schema_path, session=session)
    yield b, session
    b.close()


def test_the_index_result_goes_to_the_canonical_id(backend):
    b, session = backend
    local = b.upsert_video("broll", "inbox/new.mov", status="proxied")
    assert local == 1
    b.write_index_result(local, themes=["harbour"], quality_flags=[], category_hint=None,
                         segments=[], model="m")
    url, payload = session.posts[-1]
    assert url.endswith("/ingest/index")
    assert payload["video_id"] == 15001, "the local shadow id was posted"
    assert (payload["share"], payload["rel_path"]) == ("broll", "inbox/new.mov")


def test_a_move_names_the_canonical_id_and_where_the_clip_was(backend):
    b, session = backend
    local = b.upsert_video("broll", "inbox/new.mov", status="indexed", in_inbox=1)
    b.record_moved(local, "cat/new.mov")
    url, payload = session.posts[-1]
    assert url.endswith("/ingest/moved")
    assert payload == {"video_id": 15001, "share": "broll", "rel_path": "inbox/new.mov",
                       "new_rel_path": "cat/new.mov"}
    assert b.get_video(local)["rel_path"] == "cat/new.mov"


def test_the_mapping_survives_a_new_process(tmp_path, schema_path):
    """The scan that learns the canonical id and the index run that needs it
    are usually two different processes."""
    session = _Canonical()
    first = HttpBackend("http://nas/api", "tok", tmp_path / "shadow.db",
                        schema_path=schema_path, session=session)
    local = first.upsert_video("broll", "inbox/new.mov", status="proxied")
    first.close()
    second = HttpBackend("http://nas/api", "tok", tmp_path / "shadow.db",
                         schema_path=schema_path, session=session)
    try:
        second.write_index_result(local, themes=[], quality_flags=[], category_hint=None,
                                  segments=[], model="m")
        assert session.posts[-1][1]["video_id"] == 15001
    finally:
        second.close()


def test_an_unmapped_clip_sends_an_id_no_row_carries(backend):
    """A shadow row from before the mapping existed: never the local number."""
    b, session = backend
    local = b.upsert_video("broll", "inbox/old.mov", status="proxied")
    b._local.conn.execute("DELETE FROM http_remote_ids")
    b._local.conn.commit()
    b.write_index_result(local, themes=[], quality_flags=[], category_hint=None,
                         segments=[], model="m")
    payload = session.posts[-1][1]
    assert payload["video_id"] == 0
    assert payload["rel_path"] == "inbox/old.mov"


def test_update_video_refreshes_the_mapping(backend):
    b, session = backend
    local = b.upsert_video("broll", "inbox/new.mov", status="discovered")
    session.ids[("broll", "inbox/new.mov")] = 42  # the canonical DB was republished
    b.update_video(local, status="probed")
    b.write_index_result(local, themes=[], quality_flags=[], category_hint=None,
                         segments=[], model="m")
    assert session.posts[-1][1]["video_id"] == 42
