from __future__ import annotations

import xxhash

from broll_index import hashing
from broll_index.hashing import hash_file_full, hash_file_partial


def test_hash_is_deterministic(tmp_path):
    f = tmp_path / "a.mov"
    f.write_bytes(b"hello world" * 1000)
    h1 = hash_file_partial(f)
    h2 = hash_file_partial(f)
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) > 0


def test_hash_differs_for_different_content(tmp_path):
    f1 = tmp_path / "a.mov"
    f2 = tmp_path / "b.mov"
    f1.write_bytes(b"a" * 1000)
    f2.write_bytes(b"b" * 1000)
    assert hash_file_partial(f1) != hash_file_partial(f2)


def test_hash_differs_for_different_size_same_prefix(tmp_path):
    f1 = tmp_path / "a.mov"
    f2 = tmp_path / "b.mov"
    f1.write_bytes(b"x" * 1000)
    f2.write_bytes(b"x" * 2000)
    assert hash_file_partial(f1) != hash_file_partial(f2)


def test_hash_large_file_reads_head_and_tail(tmp_path):
    # bigger than CHUNK_SIZE (8 MiB) so both head and tail reads are exercised, and a
    # change only in the middle (untouched by partial hash) should NOT change the hash.
    size = 20 * 1024 * 1024
    f1 = tmp_path / "big1.mov"
    f2 = tmp_path / "big2.mov"
    data = bytearray(b"\x00" * size)
    f1.write_bytes(bytes(data))
    data[size // 2] = 0xFF  # flip a byte in the untouched middle region
    f2.write_bytes(bytes(data))
    assert hash_file_partial(f1) == hash_file_partial(f2)

    # but a change in the head IS detected
    data2 = bytearray(b"\x00" * size)
    data2[0] = 0xFF
    f3 = tmp_path / "big3.mov"
    f3.write_bytes(bytes(data2))
    assert hash_file_partial(f1) != hash_file_partial(f3)


# ---------------------------------------------------------------------------
# hash_file_full — whole-file hash used to CONFIRM a partial-hash candidate
# ---------------------------------------------------------------------------

def test_hash_file_full_is_deterministic(tmp_path):
    f = tmp_path / "a.mov"
    f.write_bytes(b"hello world" * 1000)
    assert hash_file_full(f) == hash_file_full(f)


def test_hash_file_full_differs_for_different_content(tmp_path):
    f1 = tmp_path / "a.mov"
    f2 = tmp_path / "b.mov"
    f1.write_bytes(b"a" * 1000)
    f2.write_bytes(b"b" * 1000)
    assert hash_file_full(f1) != hash_file_full(f2)


def test_hash_file_full_streams_in_chunks_matches_manual_digest(tmp_path, monkeypatch):
    # Force many small reads (well below the file size) to exercise the streaming loop,
    # and confirm the result is identical to hashing the whole buffer in one shot —
    # i.e. chunking never changes the digest.
    monkeypatch.setattr(hashing, "CHUNK_SIZE", 4)
    data = bytes(range(256)) * 3  # 768 bytes, not a multiple-friendly size
    f = tmp_path / "chunked.mov"
    f.write_bytes(data)

    assert hash_file_full(f) == xxhash.xxh64(data).hexdigest()


def test_hash_file_full_reads_middle_bytes_partial_hash_ignores(tmp_path, monkeypatch):
    # A change confined to the middle region (untouched by hash_file_partial's
    # head+tail-only read) must still change hash_file_full.
    monkeypatch.setattr(hashing, "CHUNK_SIZE", 8)
    head = b"H" * 8
    tail = b"T" * 8
    f1 = tmp_path / "a.mov"
    f2 = tmp_path / "b.mov"
    f1.write_bytes(head + b"middle_1" + tail)
    f2.write_bytes(head + b"middle_2" + tail)

    assert hash_file_partial(f1) == hash_file_partial(f2)  # partial hash blind to the middle
    assert hash_file_full(f1) != hash_file_full(f2)  # full hash is not


def test_partial_hash_collision_is_real_full_hash_distinguishes(tmp_path, monkeypatch):
    """THE critical case this whole feature exists for: two DIFFERENT files that share
    identical head, identical tail, and identical total size — hash_file_partial
    genuinely collides on them (this is not a hypothetical), and only hash_file_full
    tells them apart. broll_index.duplicates relies on exactly this to avoid marking
    a unique file duplicate (which would lose it during the NAS copy)."""
    monkeypatch.setattr(hashing, "CHUNK_SIZE", 8)

    head = b"A" * 8
    tail = b"B" * 8
    middle_1 = b"middle_1"  # 8 bytes
    middle_2 = b"middle_2"  # 8 bytes, same length so total size matches too
    assert len(middle_1) == len(middle_2) == 8

    f1 = tmp_path / "one.mov"
    f2 = tmp_path / "two.mov"
    f1.write_bytes(head + middle_1 + tail)
    f2.write_bytes(head + middle_2 + tail)
    assert f1.stat().st_size == f2.stat().st_size == 24  # > CHUNK_SIZE: exercises head+tail read

    assert hash_file_partial(f1) == hash_file_partial(f2)
    assert hash_file_full(f1) != hash_file_full(f2)
