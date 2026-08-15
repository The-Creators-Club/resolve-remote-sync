from __future__ import annotations

from broll_index.scanner import ScannedFile, do_scan, is_hidden_or_system, scan_share
from broll_index.storage.sqlite_backend import SqliteBackend


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake video bytes")


def test_scan_share_finds_video_extensions_case_insensitive(tmp_path):
    root = tmp_path / "share"
    _touch(root / "clip1.MOV")
    _touch(root / "sub" / "clip2.mp4")
    _touch(root / "sub" / "clip3.braw")
    _touch(root / "notes.txt")
    _touch(root / "clip4.mkv")

    found = sorted(sf.rel_path for sf in scan_share(root))
    assert found == ["clip1.MOV", "clip4.mkv", "sub/clip2.mp4", "sub/clip3.braw"]


def test_scan_share_skips_dot_dirs_and_files(tmp_path):
    root = tmp_path / "share"
    _touch(root / ".git" / "clip_hidden.mp4")
    _touch(root / ".hidden_file.mp4")
    _touch(root / "visible.mp4")

    found = sorted(sf.rel_path for sf in scan_share(root))
    assert found == ["visible.mp4"]


def test_scan_share_skips_data_root(tmp_path):
    root = tmp_path / "share"
    data_root = root / "_data"
    _touch(data_root / "proxies" / "1.mp4")
    _touch(root / "real_clip.mp4")

    found = sorted(sf.rel_path for sf in scan_share(root, data_root=data_root))
    assert found == ["real_clip.mp4"]


def test_scan_share_skips_data_root_outside_share(tmp_path):
    root = tmp_path / "share"
    data_root = tmp_path / "data"
    _touch(root / "real_clip.mp4")
    _touch(data_root / "proxies" / "1.mp4")

    found = sorted(sf.rel_path for sf in scan_share(root, data_root=data_root))
    assert found == ["real_clip.mp4"]


def test_is_hidden_or_system_dot_prefixed(tmp_path):
    p = tmp_path / ".git"
    p.mkdir()
    assert is_hidden_or_system(p) is True
    p2 = tmp_path / "normal"
    p2.mkdir()
    assert is_hidden_or_system(p2) is False


def test_do_scan_upserts_rows(tmp_path, schema_path):
    root = tmp_path / "share"
    _touch(root / "military" / "clip.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        count = do_scan(storage, "broll", root)
        assert count == 1
        row = storage.get_video_by_path("broll", "military/clip.mp4")
        assert row is not None
        assert row["status"] == "discovered"
        assert row["hash"]
        assert row["size_bytes"] == len(b"fake video bytes")
        assert row["in_inbox"] == 0
    finally:
        storage.close()


def test_do_scan_marks_inbox_files(tmp_path, schema_path):
    root = tmp_path / "share"
    _touch(root / "inbox" / "new_clip.mp4")
    _touch(root / "military" / "already_sorted.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        do_scan(storage, "broll", root, inbox="inbox")
        inbox_row = storage.get_video_by_path("broll", "inbox/new_clip.mp4")
        sorted_row = storage.get_video_by_path("broll", "military/already_sorted.mp4")
        assert inbox_row["in_inbox"] == 1
        assert sorted_row["in_inbox"] == 0
    finally:
        storage.close()


def test_do_scan_rescan_does_not_clobber_duplicate_of(tmp_path, schema_path):
    """Rescanning a file already marked a duplicate (by `broll-index duplicates`) must
    never touch duplicate_of -- scan only ever refreshes hash/size/in_inbox/status."""
    root = tmp_path / "share"
    _touch(root / "clip.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        do_scan(storage, "broll", root)
        row = storage.get_video_by_path("broll", "clip.mp4")
        canonical_id = storage.upsert_video("broll", "canonical.mp4", status="indexed")
        storage.update_video(row["id"], duplicate_of=canonical_id, full_hash="cached_full_hash")

        do_scan(storage, "broll", root)
        row_after = storage.get_video_by_path("broll", "clip.mp4")
        assert row_after["duplicate_of"] == canonical_id
        assert row_after["full_hash"] == "cached_full_hash"
    finally:
        storage.close()


# --- rescans must not re-read the whole archive over the wire -----------------
# hash_file_partial reads 8 MiB of head and 8 MiB of tail, and do_scan used to
# call it on every file it walked before even looking the row up. The shares are
# 25 NETWORK roots, so a rescan to pick up a handful of new downloads pulled
# ~16 MiB per already-known file — ~70 GB, ~25 min at the measured 46 MB/s, on
# one 4,482-file share — to recompute a digest that cannot have changed unless
# the file did (BROLL-IDX-6, 2026-08-14).

def _counting_hash(monkeypatch):
    from broll_index import scanner

    calls: list[str] = []
    real = scanner.hash_file_partial

    def counted(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(scanner, "hash_file_partial", counted)
    return calls


def test_a_rescan_does_not_re_read_an_unchanged_file(tmp_path, schema_path, monkeypatch):
    root = tmp_path / "share"
    _touch(root / "clip.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        do_scan(storage, "broll", root)
        first = storage.get_video_by_path("broll", "clip.mp4")["hash"]

        calls = _counting_hash(monkeypatch)
        do_scan(storage, "broll", root)

        assert calls == [], "the size from the stat() already says nothing changed"
        assert storage.get_video_by_path("broll", "clip.mp4")["hash"] == first, \
            "and the stored digest is kept, not blanked"
    finally:
        storage.close()


def test_a_changed_size_is_still_hashed(tmp_path, schema_path, monkeypatch):
    """The discriminator has to be the file, not the calendar: a truncated or
    re-downloaded file must get a fresh digest."""
    root = tmp_path / "share"
    _touch(root / "clip.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        do_scan(storage, "broll", root)
        before = storage.get_video_by_path("broll", "clip.mp4")["hash"]
        (root / "clip.mp4").write_bytes(b"a completely different, longer file")

        calls = _counting_hash(monkeypatch)
        do_scan(storage, "broll", root)

        assert len(calls) == 1
        assert storage.get_video_by_path("broll", "clip.mp4")["hash"] != before
    finally:
        storage.close()


def test_rehash_forces_the_read_for_a_same_size_edit(tmp_path, schema_path, monkeypatch):
    """The one case size cannot see, and the flag that exists for it."""
    root = tmp_path / "share"
    _touch(root / "clip.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        do_scan(storage, "broll", root)
        before = storage.get_video_by_path("broll", "clip.mp4")["hash"]
        (root / "clip.mp4").write_bytes(b"FAKE VIDEO BYTES")  # same length, other bytes

        calls = _counting_hash(monkeypatch)
        do_scan(storage, "broll", root)
        assert calls == [], "same size, so the cheap path trusts the stored hash"

        do_scan(storage, "broll", root, rehash=True)
        assert len(calls) == 1
        assert storage.get_video_by_path("broll", "clip.mp4")["hash"] != before
    finally:
        storage.close()


def test_a_first_sight_file_is_always_hashed(tmp_path, schema_path, monkeypatch):
    root = tmp_path / "share"
    _touch(root / "clip.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        calls = _counting_hash(monkeypatch)
        do_scan(storage, "broll", root)

        assert len(calls) == 1
        assert storage.get_video_by_path("broll", "clip.mp4")["hash"]
    finally:
        storage.close()


def test_do_scan_rescan_does_not_reset_status(tmp_path, schema_path):
    """Rescanning a file that has already progressed past `discovered` must not reset it —
    scan only refreshes hash/size/in_inbox, never status, on an existing row."""
    root = tmp_path / "share"
    _touch(root / "clip.mp4")
    storage = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    try:
        do_scan(storage, "broll", root)
        row = storage.get_video_by_path("broll", "clip.mp4")
        storage.update_video(row["id"], status="indexed")

        do_scan(storage, "broll", root)
        row_after = storage.get_video_by_path("broll", "clip.mp4")
        assert row_after["status"] == "indexed"
    finally:
        storage.close()
