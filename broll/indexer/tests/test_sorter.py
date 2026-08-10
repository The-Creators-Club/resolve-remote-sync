from __future__ import annotations

from pathlib import Path

from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig
from broll_index.sorter import _dedupe_rel_path, do_sort, move_file, plan_move


def _touch(path: Path, content: bytes = b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_plan_move_uses_category_and_filename(tmp_path):
    share_root = tmp_path
    video = {"category": "military/naval", "rel_path": "inbox/clip_0021.mov"}
    dest_path, dest_rel = plan_move(share_root, video)
    assert dest_rel == "military/naval/clip_0021.mov"
    assert dest_path == share_root / "military/naval/clip_0021.mov"


def test_dedupe_rel_path_appends_suffix_on_collision(tmp_path):
    _touch(tmp_path / "military/naval/clip.mov")
    result = _dedupe_rel_path(tmp_path, "military/naval/clip.mov")
    assert result == "military/naval/clip_2.mov"

    _touch(tmp_path / "military/naval/clip_2.mov")
    result2 = _dedupe_rel_path(tmp_path, "military/naval/clip.mov")
    assert result2 == "military/naval/clip_3.mov"


def test_move_file_same_volume_uses_replace(tmp_path):
    src = tmp_path / "src.mov"
    dest = tmp_path / "sub" / "dest.mov"
    _touch(src, b"hello")
    move_file(src, dest, same_volume=True)
    assert not src.exists()
    assert dest.read_bytes() == b"hello"


def test_move_file_cross_volume_copies_verifies_and_deletes(tmp_path):
    src = tmp_path / "src.mov"
    dest = tmp_path / "sub" / "dest.mov"
    _touch(src, b"cross volume payload")
    move_file(src, dest, same_volume=False)
    assert not src.exists()
    assert dest.read_bytes() == b"cross volume payload"


def _cfg(tmp_path) -> Config:
    return Config(
        shares={"broll": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        sampling=SamplingConfig(),
    )


def test_do_sort_dry_run_does_not_move_files(tmp_path, sqlite_storage):
    _touch(tmp_path / "inbox/clip.mov")
    sqlite_storage.upsert_video(
        "broll", "inbox/clip.mov", status="indexed", in_inbox=1, category="military/naval"
    )
    cfg = _cfg(tmp_path)
    plan = do_sort(cfg, sqlite_storage, dry_run=True)
    assert len(plan) == 1
    assert plan[0]["to"] == "military/naval/clip.mov"
    assert (tmp_path / "inbox/clip.mov").exists()  # untouched
    assert not (tmp_path / "military/naval/clip.mov").exists()


def test_do_sort_moves_file_and_updates_db(tmp_path, sqlite_storage):
    _touch(tmp_path / "inbox/clip.mov")
    vid = sqlite_storage.upsert_video(
        "broll", "inbox/clip.mov", status="indexed", in_inbox=1, category="military/naval"
    )
    cfg = _cfg(tmp_path)
    plan = do_sort(cfg, sqlite_storage, dry_run=False)
    assert len(plan) == 1
    assert not (tmp_path / "inbox/clip.mov").exists()
    assert (tmp_path / "military/naval/clip.mov").exists()

    row = sqlite_storage.get_video(vid)
    assert row["rel_path"] == "military/naval/clip.mov"
    assert row["in_inbox"] == 0
    assert row["status"] == "sorted"


def test_do_sort_only_moves_eligible_videos(tmp_path, sqlite_storage):
    _touch(tmp_path / "inbox/a.mov")
    sqlite_storage.upsert_video("broll", "inbox/a.mov", status="indexed", in_inbox=1, category="cat/a")
    # not in inbox
    sqlite_storage.upsert_video("broll", "military/b.mov", status="indexed", in_inbox=0, category="cat/a")
    # no category
    sqlite_storage.upsert_video("broll", "inbox/c.mov", status="indexed", in_inbox=1, category=None)
    # not indexed yet
    sqlite_storage.upsert_video("broll", "inbox/d.mov", status="discovered", in_inbox=1, category="cat/a")

    cfg = _cfg(tmp_path)
    plan = do_sort(cfg, sqlite_storage, dry_run=True)
    assert [p["from"] for p in plan] == ["inbox/a.mov"]
