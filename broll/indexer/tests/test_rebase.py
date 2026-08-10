from __future__ import annotations

from pathlib import Path

import pytest

from broll_index.rebase import do_rebase, hash_tree, plan_rebase, render_report
from broll_index.storage.sqlite_backend import SqliteBackend


def _video(vid: int, share: str, rel_path: str, digest: str, status: str = "indexed") -> dict:
    return {"id": vid, "share": share, "rel_path": rel_path, "hash": digest, "status": status}


# ---------------------------------------------------------------------------
# planning (pure)
# ---------------------------------------------------------------------------

def test_rematches_video_moved_to_new_share_and_path() -> None:
    videos = [_video(1, "lacie", "old/dir/clip.mov", "aaa")]
    plan = plan_rebase(videos, {"aaa": ["archive/2024/clip.mov"]}, to_share="broll")

    assert len(plan.rematched) == 1
    assert plan.rematched[0]["from"] == "lacie:old/dir/clip.mov"
    assert plan.rematched[0]["to"] == "broll:archive/2024/clip.mov"
    assert plan.missing == [] and plan.superseded == []


def test_unchanged_video_is_already_correct_not_rematched() -> None:
    videos = [_video(1, "broll", "archive/clip.mov", "aaa")]
    plan = plan_rebase(videos, {"aaa": ["archive/clip.mov"]}, to_share="broll")

    assert plan.rematched == []
    assert len(plan.already_correct) == 1


def test_video_absent_from_new_root_is_reported_missing_not_touched() -> None:
    videos = [_video(1, "lacie", "clip.mov", "aaa")]
    plan = plan_rebase(videos, {}, to_share="broll")

    assert plan.rematched == []
    assert len(plan.missing) == 1
    assert "content hash" in plan.missing[0]["reason"]


def test_video_without_hash_is_reported_missing() -> None:
    videos = [{"id": 1, "share": "lacie", "rel_path": "clip.mov", "hash": None, "status": "discovered"}]
    plan = plan_rebase(videos, {"aaa": ["clip.mov"]}, to_share="broll")

    assert len(plan.missing) == 1
    assert "no hash" in plan.missing[0]["reason"]


def test_duplicate_rows_collapse_to_best_indexed_row() -> None:
    # Same clip found on two scattered drives; only one got a full index pass.
    videos = [
        _video(1, "lacie", "a/clip.mov", "aaa", status="probed"),
        _video(2, "gdrive", "b/clip.mov", "aaa", status="indexed"),
    ]
    plan = plan_rebase(videos, {"aaa": ["archive/clip.mov"]}, to_share="broll")

    assert len(plan.rematched) == 1
    assert plan.rematched[0]["video"]["id"] == 2  # the indexed one wins
    assert len(plan.superseded) == 1
    assert plan.superseded[0]["video"]["id"] == 1
    assert plan.superseded[0]["duplicate_of"] == 2


def test_duplicate_rows_tie_broken_by_segment_count() -> None:
    videos = [
        _video(1, "lacie", "a/clip.mov", "aaa"),
        _video(2, "gdrive", "b/clip.mov", "aaa"),
    ]
    plan = plan_rebase(
        videos, {"aaa": ["archive/clip.mov"]}, to_share="broll", segment_counts={1: 2, 2: 9}
    )

    assert plan.rematched[0]["video"]["id"] == 2
    assert plan.superseded[0]["video"]["id"] == 1


def test_files_on_new_root_with_no_index_row_are_listed() -> None:
    plan = plan_rebase([], {"zzz": ["archive/new_clip.mov"]}, to_share="broll")
    assert plan.unindexed_files == ["archive/new_clip.mov"]


def test_duplicate_copies_on_new_root_are_flagged() -> None:
    videos = [_video(1, "lacie", "clip.mov", "aaa")]
    plan = plan_rebase(videos, {"aaa": ["archive/clip.mov", "archive/dupe/clip.mov"]}, to_share="broll")

    assert len(plan.rematched) == 1
    assert any("duplicate copy" in f for f in plan.unindexed_files)


def test_report_mentions_every_section() -> None:
    videos = [
        _video(1, "lacie", "a/clip.mov", "aaa", status="probed"),
        _video(2, "gdrive", "b/clip.mov", "aaa", status="indexed"),
        _video(3, "lacie", "gone.mov", "bbb"),
    ]
    plan = plan_rebase(videos, {"aaa": ["archive/clip.mov"], "ccc": ["archive/extra.mov"]}, to_share="broll")
    report = render_report(plan, "broll")

    assert "Rematched" in report and "Superseded" in report
    assert "Not found on the new root" in report
    assert "not in the index" in report


# ---------------------------------------------------------------------------
# hashing a real tree + applying against a real DB
# ---------------------------------------------------------------------------

def test_hash_tree_groups_identical_content(tmp_path: Path) -> None:
    root = tmp_path / "nas"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "a" / "one.mov").write_bytes(b"same content")
    (root / "b" / "copy.mov").write_bytes(b"same content")
    (root / "a" / "other.mov").write_bytes(b"different")

    by_hash = hash_tree(root)

    groups = sorted((sorted(v) for v in by_hash.values()), key=len, reverse=True)
    assert groups[0] == ["a/one.mov", "b/copy.mov"]
    assert len(by_hash) == 2


def _seed(db: SqliteBackend, share: str, rel_path: str, digest: str, status: str = "indexed") -> int:
    return db.upsert_video(share, rel_path, hash=digest, status=status)


def test_do_rebase_dry_run_writes_nothing(tmp_path: Path, schema_path: Path) -> None:
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    vid = _seed(db, "lacie", "old/clip.mov", "unused")

    root = tmp_path / "nas"
    root.mkdir()
    (root / "clip.mov").write_bytes(b"payload")
    real_hash = next(iter(hash_tree(root)))
    db.update_video(vid, hash=real_hash)

    plan, _ = do_rebase(db, to_share="broll", root=root, dry_run=True)

    assert len(plan.rematched) == 1
    row = db.get_video(vid)
    assert row["share"] == "lacie" and row["rel_path"] == "old/clip.mov"


def test_do_rebase_apply_updates_path_and_preserves_index(tmp_path: Path, schema_path: Path) -> None:
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    vid = _seed(db, "lacie", "old/clip.mov", "unused")
    db.write_index_result(
        vid,
        themes=["harbor"],
        quality_flags=[],
        category_hint=None,
        segments=[
            {
                "t_start": 0.0,
                "t_end": 4.0,
                "description": "navy frigate at pier",
                "objects": ["navy ship", "frigate"],
                "setting": "harbor",
                "motion": "static",
            }
        ],
        model="claude-haiku-4-5-20251001",
    )

    root = tmp_path / "nas"
    (root / "archive").mkdir(parents=True)
    (root / "archive" / "clip.mov").write_bytes(b"payload")
    db.update_video(vid, hash=next(iter(hash_tree(root))))

    do_rebase(db, to_share="broll", root=root, dry_run=False)

    row = db.get_video(vid)
    assert row["share"] == "broll"
    assert row["rel_path"] == "archive/clip.mov"
    # The whole point: the expensive index survives the move.
    assert db.segment_counts()[vid] == 1


def test_do_rebase_prune_duplicates_only_with_flag(tmp_path: Path, schema_path: Path) -> None:
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    root = tmp_path / "nas"
    root.mkdir()
    (root / "clip.mov").write_bytes(b"payload")
    digest = next(iter(hash_tree(root)))

    keep = _seed(db, "gdrive", "b/clip.mov", digest, status="indexed")
    dupe = _seed(db, "lacie", "a/clip.mov", digest, status="probed")

    do_rebase(db, to_share="broll", root=root, dry_run=False)
    assert db.get_video(dupe) is not None  # not pruned without the flag

    do_rebase(db, to_share="broll", root=root, dry_run=False, prune_duplicates=True)
    assert db.get_video(dupe) is None
    assert db.get_video(keep) is not None
