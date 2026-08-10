"""Pushing share -> source-root facts to the web app.

The web app cannot derive them: share roots and ShareConfig.source live in
config.queue.yaml, which web/app/config.py says it does not read and may not
even be able to see. They matter at final export, when a remote editor's proxy
has to be relinked to the true original on whatever drive it now lives.
"""
from __future__ import annotations

from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig
from broll_index.share_push import push_shares, share_payload
from broll_index.storage.sqlite_backend import SqliteBackend


def _cfg(tmp_path) -> Config:
    return Config(
        shares={
            "ff4-nuclear": ShareConfig(root="Z:/FF4/Nuclear/Youtube"),
            "mofa-disaster": ShareConfig(root="Z:/MOFA/Event", source="proxies",
                                         description="own footage", index=False),
        },
        data_root=tmp_path,
        db=DbConfig(mode="sqlite", path=str(tmp_path / "b.db")),
        sampling=SamplingConfig(),
    )


def test_the_payload_carries_what_a_conform_needs(tmp_path):
    payload = {p["share"]: p for p in share_payload(_cfg(tmp_path))}

    own = payload["mofa-disaster"]
    assert own["root"] == "Z:/MOFA/Event"
    assert own["source"] == "proxies", (
        "for a proxies share the archived original IS the Proxy/*.mov — a conform "
        "must not go hunting for camera files left behind on purpose")
    assert own["indexed"] is False
    assert payload["ff4-nuclear"]["source"] == "originals"
    assert payload["ff4-nuclear"]["indexed"] is True


def test_push_writes_the_table(tmp_path, schema_path):
    db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    assert push_shares(_cfg(tmp_path), db) == 2

    rows = {r["share"]: r for r in db.conn.execute("SELECT * FROM share_roots")}
    assert rows["mofa-disaster"]["source"] == "proxies"
    assert rows["mofa-disaster"]["indexed"] == 0
    assert rows["ff4-nuclear"]["root"] == "Z:/FF4/Nuclear/Youtube"


def test_push_is_idempotent_and_updates_in_place(tmp_path, schema_path):
    db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    cfg = _cfg(tmp_path)
    push_shares(cfg, db)
    cfg.shares["mofa-disaster"].root = "Z:/MOFA/Event MOVED"
    push_shares(cfg, db)

    rows = db.conn.execute("SELECT share, root FROM share_roots").fetchall()
    assert len(rows) == 2, "upsert, not insert"
    assert dict(rows[1] if rows[1]["share"] == "mofa-disaster" else rows[0])["root"] \
        == "Z:/MOFA/Event MOVED"


def test_a_share_dropped_from_the_config_is_not_deleted(tmp_path, schema_path):
    """Its videos are still in the table and their origin must stay resolvable."""
    db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    cfg = _cfg(tmp_path)
    push_shares(cfg, db)
    del cfg.shares["ff4-nuclear"]
    push_shares(cfg, db)

    shares = {r[0] for r in db.conn.execute("SELECT share FROM share_roots")}
    assert "ff4-nuclear" in shares


def test_a_push_failure_never_fails_the_run(tmp_path, schema_path):
    """Bookkeeping for a conform weeks away must not cost an indexing run."""
    class Boom(SqliteBackend):
        def push_shares(self, payload):
            raise RuntimeError("network is down")

    db = Boom(tmp_path / "b.db", schema_path=schema_path)
    assert push_shares(_cfg(tmp_path), db) == 0


def test_a_backend_without_push_is_not_an_error(tmp_path):
    class NoPush:
        pass

    assert push_shares(_cfg(tmp_path), NoPush()) == 0
