from __future__ import annotations

from pathlib import Path

import pytest

from broll_index.duplicates import (
    ConfirmedGroup,
    confirm_group,
    do_duplicates,
    find_candidates,
    pick_canonical,
    plan_duplicates,
    render_report,
)
from broll_index.storage.sqlite_backend import SqliteBackend


def _video(vid: int, share: str, rel_path: str, digest: str, status: str = "indexed", **extra) -> dict:
    return {"id": vid, "share": share, "rel_path": rel_path, "hash": digest, "status": status, **extra}


def _resolver(root: Path):
    def resolve(video: dict) -> Path | None:
        share_root = root / video["share"]
        return share_root / video["rel_path"]
    return resolve


# ---------------------------------------------------------------------------
# find_candidates / pick_canonical (pure)
# ---------------------------------------------------------------------------

def test_find_candidates_groups_by_partial_hash():
    videos = [
        _video(1, "a", "one.mov", "hash1"),
        _video(2, "b", "two.mov", "hash1"),
        _video(3, "c", "three.mov", "hash2"),  # unique hash, no group
    ]
    groups = find_candidates(videos)
    assert len(groups) == 1
    assert {v["id"] for v in groups[0]} == {1, 2}


def test_find_candidates_excludes_rows_without_hash():
    videos = [_video(1, "a", "one.mov", None), _video(2, "b", "two.mov", None)]
    assert find_candidates(videos) == []


def test_find_candidates_excludes_already_marked_duplicates():
    # video 2 is already a duplicate of something; it must not be regrouped or
    # allowed to feed a new candidate group.
    videos = [
        _video(1, "a", "one.mov", "hash1"),
        _video(2, "b", "two.mov", "hash1", duplicate_of=99),
    ]
    assert find_candidates(videos) == []


def test_pick_canonical_by_status_rank():
    group = [
        _video(1, "a", "one.mov", "h", status="probed"),
        _video(2, "b", "two.mov", "h", status="indexed"),
    ]
    assert pick_canonical(group)["id"] == 2


def test_pick_canonical_tie_broken_by_segment_count():
    group = [
        _video(1, "a", "one.mov", "h", status="indexed"),
        _video(2, "b", "two.mov", "h", status="indexed"),
    ]
    assert pick_canonical(group, segment_counts={1: 2, 2: 9})["id"] == 2


def test_pick_canonical_tie_broken_by_lowest_id():
    group = [
        _video(5, "a", "one.mov", "h", status="indexed"),
        _video(2, "b", "two.mov", "h", status="indexed"),
    ]
    assert pick_canonical(group)["id"] == 2


# ---------------------------------------------------------------------------
# confirm_group — the correctness-critical step
# ---------------------------------------------------------------------------

def test_confirm_group_true_duplicates_are_confirmed(tmp_path):
    root = tmp_path
    (root / "a").mkdir()
    (root / "b").mkdir()
    (root / "a" / "one.mov").write_bytes(b"identical payload")
    (root / "b" / "two.mov").write_bytes(b"identical payload")

    group = [
        _video(1, "a", "one.mov", "partial_hash_x"),
        _video(2, "b", "two.mov", "partial_hash_x"),
    ]
    confirmed, singletons, missing = confirm_group(group, _resolver(root))

    assert len(confirmed) == 1
    assert {v["id"] for v in confirmed[0].videos} == {1, 2}
    assert singletons == []
    assert missing == []


def test_confirm_group_splits_false_positive_partial_hash_collision(tmp_path):
    """The critical case: two files that share the fast partial hash (constructed here
    with identical head/tail/size but different content) must be confirmed DISTINCT and
    never end up in the same confirmed group."""
    import broll_index.hashing as hashing_mod

    root = tmp_path

    head = b"H" * 8
    tail = b"T" * 8
    (root).mkdir(exist_ok=True)
    (root / "one.mov").write_bytes(head + b"middle_1" + tail)
    (root / "two.mov").write_bytes(head + b"middle_2" + tail)

    # Prove the partial hash actually collides for these two files (not hypothetical).
    from broll_index.hashing import hash_file_partial
    orig_chunk = hashing_mod.CHUNK_SIZE
    hashing_mod.CHUNK_SIZE = 8
    try:
        partial_1 = hash_file_partial(root / "one.mov")
        partial_2 = hash_file_partial(root / "two.mov")
        assert partial_1 == partial_2  # confirmed collision

        group = [
            _video(1, "share", "one.mov", partial_1),
            _video(2, "share", "two.mov", partial_2),
        ]

        def resolve(video: dict) -> Path:
            return root / video["rel_path"]

        confirmed, singletons, missing = confirm_group(group, resolve)

        assert confirmed == []  # NOT a true duplicate group
        assert {v["id"] for v in singletons} == {1, 2}
        assert missing == []
    finally:
        hashing_mod.CHUNK_SIZE = orig_chunk


def test_confirm_group_missing_file_is_never_marked_duplicate(tmp_path):
    root = tmp_path
    (root / "one.mov").write_bytes(b"payload")
    # "two.mov" deliberately not created — simulates a moved/deleted source file.

    group = [
        _video(1, "share", "one.mov", "hash_x"),
        _video(2, "share", "two.mov", "hash_x"),
    ]

    def resolve(video: dict) -> Path:
        return root / video["rel_path"]

    confirmed, singletons, missing = confirm_group(group, resolve)
    assert confirmed == []
    assert singletons == [] or all(v["id"] != 2 for v in singletons)
    assert len(missing) == 1
    assert missing[0]["id"] == 2


def test_confirm_group_reuses_cached_full_hash(tmp_path):
    calls = []

    def counting_hasher(path: Path) -> str:
        calls.append(path)
        return "computed"

    root = tmp_path
    (root / "one.mov").write_bytes(b"x")
    (root / "two.mov").write_bytes(b"x")

    group = [
        _video(1, "share", "one.mov", "h", full_hash="cached"),
        _video(2, "share", "two.mov", "h"),  # no cached full_hash -> must hash
    ]

    def resolve(video: dict) -> Path:
        return root / video["rel_path"]

    confirmed, singletons, missing = confirm_group(group, resolve, hasher=counting_hasher)
    assert len(calls) == 1  # only the uncached row was hashed
    # different full_hash values ("cached" vs "computed") -> not grouped together
    assert confirmed == []
    assert len(singletons) == 2


# ---------------------------------------------------------------------------
# plan_duplicates / render_report
# ---------------------------------------------------------------------------

def test_plan_duplicates_true_duplicate_marks_loser_keeps_best_indexed(tmp_path):
    root = tmp_path
    (root / "a").mkdir()
    (root / "b").mkdir()
    (root / "a" / "clip.mov").write_bytes(b"same bytes")
    (root / "b" / "clip.mov").write_bytes(b"same bytes")

    videos = [
        _video(1, "a", "clip.mov", "partial", status="probed"),
        _video(2, "b", "clip.mov", "partial", status="indexed"),
    ]
    plan = plan_duplicates(videos, resolve_path=_resolver(root), segment_counts={1: 0, 2: 3})

    assert len(plan.marked) == 1
    assert plan.marked[0]["video"]["id"] == 1
    assert plan.marked[0]["duplicate_of"] == 2
    assert plan.marked[0]["full_hash"]
    assert len(plan.canonicals) == 1
    assert plan.canonicals[0]["video"]["id"] == 2
    assert plan.false_positives == []
    assert plan.missing == []


def test_plan_duplicates_mixed_group_splits_true_duplicate_and_false_positive(tmp_path):
    """A single partial-hash candidate group containing BOTH a true duplicate pair and a
    false positive (constructed via identical head/tail/size, different middle) must
    split: the true pair gets marked, the false positive does not."""
    import broll_index.hashing as hashing_mod

    root = tmp_path
    orig_chunk = hashing_mod.CHUNK_SIZE
    hashing_mod.CHUNK_SIZE = 8
    try:
        # Two byte-identical files (true duplicates).
        (root / "dup_a.mov").write_bytes(b"AAAAAAAAsame content!!!BBBBBBBB")
        (root / "dup_b.mov").write_bytes(b"AAAAAAAAsame content!!!BBBBBBBB")
        # A third file sharing the SAME partial hash (identical head/tail/size) but
        # different real content — a genuine false positive that must land in the
        # same candidate group as the pair above.
        head = b"AAAAAAAA"
        tail = b"BBBBBBBB"
        assert (root / "dup_a.mov").read_bytes()[:8] == head
        assert (root / "dup_a.mov").read_bytes()[-8:] == tail
        size = (root / "dup_a.mov").stat().st_size
        middle_len = size - 16
        (root / "false_pos.mov").write_bytes(head + b"X" * middle_len + tail)
        assert (root / "false_pos.mov").stat().st_size == size

        from broll_index.hashing import hash_file_partial
        h_a = hash_file_partial(root / "dup_a.mov")
        h_b = hash_file_partial(root / "dup_b.mov")
        h_f = hash_file_partial(root / "false_pos.mov")
        assert h_a == h_b == h_f  # all three genuinely share the partial hash

        videos = [
            _video(1, "share", "dup_a.mov", h_a, status="probed"),
            _video(2, "share", "dup_b.mov", h_b, status="indexed"),
            _video(3, "share", "false_pos.mov", h_f, status="probed"),
        ]

        def resolve(video: dict) -> Path:
            return root / video["rel_path"]

        plan = plan_duplicates(videos, resolve_path=resolve)

        assert len(plan.marked) == 1
        assert plan.marked[0]["video"]["id"] == 1  # dup_a superseded by the indexed dup_b
        assert plan.marked[0]["duplicate_of"] == 2

        assert len(plan.false_positives) == 1
        assert plan.false_positives[0]["video"]["id"] == 3
    finally:
        hashing_mod.CHUNK_SIZE = orig_chunk


def test_plan_duplicates_missing_file_reported_not_marked(tmp_path):
    root = tmp_path
    (root / "present.mov").write_bytes(b"data")

    videos = [
        _video(1, "share", "present.mov", "h"),
        _video(2, "share", "gone.mov", "h"),
    ]

    def resolve(video: dict) -> Path:
        return root / video["rel_path"]

    plan = plan_duplicates(videos, resolve_path=resolve)
    assert plan.marked == []
    assert len(plan.missing) == 1
    assert plan.missing[0]["video"]["id"] == 2


def test_plan_duplicates_no_verify_marks_straight_off_partial_hash(tmp_path):
    # --no-verify: no file I/O at all, marks purely off the partial-hash grouping.
    videos = [
        _video(1, "a", "one.mov", "h", status="probed"),
        _video(2, "b", "two.mov", "h", status="indexed"),
    ]

    def resolve(video: dict):
        raise AssertionError("resolve_path must not be called when verify=False")

    plan = plan_duplicates(videos, resolve_path=resolve, verify=False)
    assert plan.verified is False
    assert len(plan.marked) == 1
    assert plan.marked[0]["video"]["id"] == 1
    assert plan.marked[0]["duplicate_of"] == 2
    assert plan.marked[0]["full_hash"] is None


def test_render_report_warns_prominently_when_unverified():
    plan = plan_duplicates([], resolve_path=lambda v: None, verify=False)
    report = render_report(plan)
    assert "WARNING" in report
    assert "--no-verify" in report


def test_render_report_mentions_every_section(tmp_path):
    root = tmp_path
    (root / "a.mov").write_bytes(b"same")
    (root / "b.mov").write_bytes(b"same")

    videos = [
        _video(1, "share", "a.mov", "h1", status="probed"),
        _video(2, "share", "b.mov", "h1", status="indexed"),
    ]

    def resolve(video):
        return root / video["rel_path"]

    plan = plan_duplicates(videos, resolve_path=resolve)
    report = render_report(plan)
    assert "Marked duplicate" in report
    assert "Canonical copies kept" in report


# ---------------------------------------------------------------------------
# do_duplicates against a real DB — apply + idempotency
# ---------------------------------------------------------------------------

def test_do_duplicates_dry_run_writes_nothing(tmp_path, schema_path):
    root = tmp_path / "share"
    root.mkdir()
    (root / "a.mov").write_bytes(b"same content")
    (root / "b.mov").write_bytes(b"same content")

    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    v1 = db.upsert_video("broll", "a.mov", hash="h1", status="probed")
    v2 = db.upsert_video("broll", "b.mov", hash="h1", status="indexed")

    def resolve(video):
        return root / video["rel_path"]

    plan, report = do_duplicates(db, resolve_path=resolve, apply=False)
    assert len(plan.marked) == 1

    row1 = db.get_video(v1)
    row2 = db.get_video(v2)
    assert row1["duplicate_of"] is None
    assert row2["duplicate_of"] is None


def test_do_duplicates_apply_marks_loser_keeps_canonical(tmp_path, schema_path):
    root = tmp_path / "share"
    root.mkdir()
    (root / "a.mov").write_bytes(b"same content")
    (root / "b.mov").write_bytes(b"same content")

    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    loser = db.upsert_video("broll", "a.mov", hash="h1", status="probed")
    canonical = db.upsert_video("broll", "b.mov", hash="h1", status="indexed")

    def resolve(video):
        return root / video["rel_path"]

    do_duplicates(db, resolve_path=resolve, apply=True)

    loser_row = db.get_video(loser)
    canonical_row = db.get_video(canonical)
    assert loser_row["duplicate_of"] == canonical
    assert loser_row["full_hash"]
    assert canonical_row["duplicate_of"] is None
    assert canonical_row["full_hash"]  # cached for next time too


def test_do_duplicates_apply_is_idempotent(tmp_path, schema_path):
    root = tmp_path / "share"
    root.mkdir()
    (root / "a.mov").write_bytes(b"same content")
    (root / "b.mov").write_bytes(b"same content")

    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    loser = db.upsert_video("broll", "a.mov", hash="h1", status="probed")
    canonical = db.upsert_video("broll", "b.mov", hash="h1", status="indexed")

    def resolve(video):
        return root / video["rel_path"]

    plan1, _ = do_duplicates(db, resolve_path=resolve, apply=True)
    assert len(plan1.marked) == 1

    before = db.get_video(loser), db.get_video(canonical)
    plan2, _ = do_duplicates(db, resolve_path=resolve, apply=True)
    after = db.get_video(loser), db.get_video(canonical)

    assert plan2.marked == []  # nothing new to mark
    assert before == after  # re-running changed nothing


def test_do_duplicates_false_positive_never_marked_end_to_end(tmp_path, schema_path):
    """Full stack version of the critical case: real sqlite rows, a real partial-hash
    collision, apply=True — the false positive must come out of the DB untouched."""
    import broll_index.hashing as hashing_mod

    root = tmp_path / "share"
    root.mkdir()

    orig_chunk = hashing_mod.CHUNK_SIZE
    hashing_mod.CHUNK_SIZE = 8
    try:
        head, tail = b"H" * 8, b"T" * 8
        (root / "one.mov").write_bytes(head + b"middle_1" + tail)
        (root / "two.mov").write_bytes(head + b"middle_2" + tail)

        from broll_index.hashing import hash_file_partial
        digest = hash_file_partial(root / "one.mov")
        assert digest == hash_file_partial(root / "two.mov")

        db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
        v1 = db.upsert_video("broll", "one.mov", hash=digest, status="probed")
        v2 = db.upsert_video("broll", "two.mov", hash=digest, status="probed")

        def resolve(video):
            return root / video["rel_path"]

        plan, report = do_duplicates(db, resolve_path=resolve, apply=True)

        assert plan.marked == []
        assert len(plan.false_positives) == 2

        row1 = db.get_video(v1)
        row2 = db.get_video(v2)
        assert row1["duplicate_of"] is None
        assert row2["duplicate_of"] is None
    finally:
        hashing_mod.CHUNK_SIZE = orig_chunk
