"""Editor proxy folders must be scanned but not indexed.

Measured on the real archive: 47% of scanned files were the editors' own
conform proxies of footage already present as originals. Content hashing cannot
detect them (same footage, different encode), so they need excluding by path.
They are NOT dropped from the database, because they still belong in the copy
manifest — existing Resolve projects are linked to them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from broll_index.scanner import do_scan, is_editor_proxy_path
from broll_index.storage.sqlite_backend import SqliteBackend


@pytest.mark.parametrize(
    "rel_path",
    [
        "Proxy/clip.mov",
        "proxy/clip.mov",
        "Orchid/Editor2/Proxy/clip.mov",
        "PROXIES/clip.mov",
        "footage/Optimized/clip.mov",
        "footage/transcodes/clip.mov",
        "lowres/clip.mov",
    ],
)
def test_recognises_editor_proxy_paths(rel_path):
    assert is_editor_proxy_path(rel_path)


@pytest.mark.parametrize(
    "rel_path",
    [
        "clip.mov",
        "news/clip.mov",
        # Must not fire on a substring inside a longer word — a folder legitimately
        # named "Proxywar Documentary" is not a proxy directory.
        "Proxywar Documentary/clip.mov",
        "approximation/clip.mov",
    ],
)
def test_does_not_flag_ordinary_paths(rel_path):
    assert not is_editor_proxy_path(rel_path)


def _make_tree(root: Path) -> None:
    (root / "Proxy").mkdir(parents=True)
    (root / "clip_a.mp4").write_bytes(b"original a")
    (root / "clip_b.mp4").write_bytes(b"original b")
    (root / "Proxy" / "clip_a.mov").write_bytes(b"proxy of a")


def test_scan_marks_proxies_skipped_and_originals_discovered(tmp_path, schema_path):
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)

    assert do_scan(db, "s", root) == 3

    assert db.get_video_by_path("s", "clip_a.mp4")["status"] == "discovered"
    assert db.get_video_by_path("s", "clip_b.mp4")["status"] == "discovered"
    assert db.get_video_by_path("s", "Proxy/clip_a.mov")["status"] == "skipped"


def test_skipped_proxies_are_not_eligible_for_the_pipeline(tmp_path, schema_path):
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    do_scan(db, "s", root)

    eligible = db.videos_by_status(["discovered", "probed", "proxied"])
    paths = {v["rel_path"] for v in eligible}
    assert paths == {"clip_a.mp4", "clip_b.mp4"}


def test_skipped_proxies_remain_in_the_database_for_the_copy_manifest(tmp_path, schema_path):
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    do_scan(db, "s", root)

    # Present, and not marked a duplicate — the manifest keys off duplicate_of,
    # so these still get copied to the NAS.
    row = db.get_video_by_path("s", "Proxy/clip_a.mov")
    assert row is not None
    assert row["duplicate_of"] is None


def test_opt_out_indexes_proxies_like_any_other_file(tmp_path, schema_path):
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)

    do_scan(db, "s", root, skip_editor_proxies=False)

    assert db.get_video_by_path("s", "Proxy/clip_a.mov")["status"] == "discovered"


def test_rescan_does_not_resurrect_a_skipped_proxy(tmp_path, schema_path):
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    do_scan(db, "s", root)
    do_scan(db, "s", root)

    assert db.get_video_by_path("s", "Proxy/clip_a.mov")["status"] == "skipped"


# --- source="proxies": our own shot footage, where the verdicts swap -----------


def test_source_proxies_indexes_the_proxy_and_excludes_the_original(tmp_path, schema_path):
    """On our own shoots the Proxy/ .mov IS the archive copy: it is what gets
    copied to the server, while the camera original is ~20x the bytes (403 GB vs
    17.6 GB on the MOFA event) and stays on the shoot drive."""
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)

    do_scan(db, "s", root, source="proxies")

    assert db.get_video_by_path("s", "Proxy/clip_a.mov")["status"] == "discovered"
    assert db.get_video_by_path("s", "clip_a.mp4")["status"] == "excluded"
    assert db.get_video_by_path("s", "clip_b.mp4")["status"] == "excluded"


def test_source_proxies_makes_only_the_proxy_eligible_for_the_pipeline(tmp_path, schema_path):
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)

    do_scan(db, "s", root, source="proxies")

    eligible = db.videos_by_status(["discovered", "probed", "proxied"])
    assert {v["rel_path"] for v in eligible} == {"Proxy/clip_a.mov"}


def test_excluded_originals_are_still_recorded(tmp_path, schema_path):
    """Not indexed and not copied, but kept as a durable record of which original
    each proxy came from — a finish may need to relink to camera media later."""
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)

    do_scan(db, "s", root, source="proxies")

    row = db.get_video_by_path("s", "clip_a.mp4")
    assert row is not None
    assert row["size_bytes"] == len(b"original a")


def test_source_modes_are_exact_opposites_on_the_same_tree(tmp_path, schema_path):
    """The same two files on disk, opposite verdicts — which is exactly why this
    is a per-share setting and not a global rule."""
    root = tmp_path / "share"
    _make_tree(root)

    originals_db = SqliteBackend(tmp_path / "a.db", schema_path=schema_path)
    do_scan(originals_db, "s", root, source="originals")
    proxies_db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    do_scan(proxies_db, "s", root, source="proxies")

    def indexable(db):
        return {v["rel_path"] for v in db.videos_by_status(["discovered", "probed", "proxied"])}

    assert indexable(originals_db) == {"clip_a.mp4", "clip_b.mp4"}
    assert indexable(proxies_db) == {"Proxy/clip_a.mov"}
    assert not (indexable(originals_db) & indexable(proxies_db))


def test_rescan_of_a_proxies_share_is_stable(tmp_path, schema_path):
    root = tmp_path / "share"
    _make_tree(root)
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    do_scan(db, "s", root, source="proxies")
    do_scan(db, "s", root, source="proxies")

    assert db.get_video_by_path("s", "clip_a.mp4")["status"] == "excluded"
    assert db.get_video_by_path("s", "Proxy/clip_a.mov")["status"] == "discovered"
