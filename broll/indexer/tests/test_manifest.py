from __future__ import annotations

from pathlib import Path

import pytest

from broll_index.manifest import (
    ManifestPlan,
    do_export_manifest,
    plan_manifest,
    render_list,
    render_robocopy,
    render_rsync,
)
from broll_index.storage.sqlite_backend import SqliteBackend


def _video(vid: int, share: str, rel_path: str, **extra) -> dict:
    return {"id": vid, "share": share, "rel_path": rel_path, "size_bytes": 1000, **extra}


def _resolver(root: Path):
    def resolve(video: dict) -> Path:
        return root / video["share"] / video["rel_path"]
    return resolve


# ---------------------------------------------------------------------------
# plan_manifest (pure)
# ---------------------------------------------------------------------------

def test_plan_manifest_includes_non_duplicates(tmp_path):
    videos = [_video(1, "broll", "a.mov"), _video(2, "broll", "b.mov")]
    plan = plan_manifest(videos, _resolver(tmp_path))
    assert len(plan.to_copy) == 2
    assert plan.skipped_duplicates == []
    assert plan.bytes_saved == 0


def test_plan_manifest_excludes_duplicates_and_reports_bytes_saved(tmp_path):
    videos = [
        _video(1, "broll", "a.mov"),
        _video(2, "broll", "b.mov", duplicate_of=1, size_bytes=5000),
        _video(3, "broll", "c.mov", duplicate_of=1, size_bytes=2500),
    ]
    plan = plan_manifest(videos, _resolver(tmp_path))
    assert len(plan.to_copy) == 1
    assert plan.to_copy[0]["video"]["id"] == 1
    assert len(plan.skipped_duplicates) == 2
    assert plan.bytes_saved == 7500


def test_plan_manifest_missing_size_bytes_counts_as_zero(tmp_path):
    videos = [
        _video(1, "broll", "a.mov"),
        {"id": 2, "share": "broll", "rel_path": "b.mov", "duplicate_of": 1, "size_bytes": None},
    ]
    plan = plan_manifest(videos, _resolver(tmp_path))
    assert plan.bytes_saved == 0


def test_plan_manifest_unresolvable_share_is_reported_separately(tmp_path):
    videos = [_video(1, "unknown_share", "a.mov")]
    plan = plan_manifest(videos, lambda v: None)
    assert plan.to_copy == []
    assert len(plan.unresolved) == 1


def test_summary_mentions_counts_and_bytes():
    plan = ManifestPlan(
        to_copy=[{"video": _video(1, "b", "a.mov"), "path": Path("a.mov")}],
        skipped_duplicates=[{"video": _video(2, "b", "b.mov")}],
        bytes_saved=1234,
    )
    summary = plan.summary()
    assert "1 file(s) to copy" in summary
    assert "1 duplicate(s) skipped" in summary
    assert "1234 byte(s) saved" in summary


# ---------------------------------------------------------------------------
# render_* — three parseable formats
# ---------------------------------------------------------------------------

def test_render_list_one_absolute_path_per_line(tmp_path):
    videos = [_video(1, "broll", "military/clip.mov"), _video(2, "broll", "news/clip2.mov")]
    plan = plan_manifest(videos, _resolver(tmp_path))
    content = render_list(plan)
    lines = [ln for ln in content.splitlines() if ln]
    assert len(lines) == 2
    assert str(tmp_path / "broll" / "military" / "clip.mov") in lines
    assert str(tmp_path / "broll" / "news" / "clip2.mov") in lines


def test_render_list_excludes_duplicates(tmp_path):
    videos = [
        _video(1, "broll", "a.mov"),
        _video(2, "broll", "b.mov", duplicate_of=1),
    ]
    plan = plan_manifest(videos, _resolver(tmp_path))
    content = render_list(plan)
    assert "b.mov" not in content
    assert "a.mov" in content


def test_render_robocopy_produces_runnable_looking_bat(tmp_path):
    videos = [
        _video(1, "broll", "military/naval/clip1.mov"),
        _video(2, "broll", "military/naval/clip2.mov"),
        _video(3, "broll", "news/clip3.mov"),
    ]
    plan = plan_manifest(videos, _resolver(tmp_path))
    content = render_robocopy(plan)

    assert content.startswith("@echo off")
    assert content.count("robocopy ") == 2  # one per distinct source directory
    assert "clip1.mov" in content and "clip2.mov" in content and "clip3.mov" in content
    assert "%DEST%" in content


def test_render_robocopy_excludes_duplicates(tmp_path):
    videos = [
        _video(1, "broll", "a.mov"),
        _video(2, "broll", "b.mov", duplicate_of=1),
    ]
    plan = plan_manifest(videos, _resolver(tmp_path))
    content = render_robocopy(plan)
    assert "b.mov" not in content
    assert "a.mov" in content


def test_render_rsync_relative_paths_one_per_line(tmp_path):
    videos = [_video(1, "broll", "military/clip.mov"), _video(2, "broll", "news/clip2.mov")]
    plan = plan_manifest(videos, _resolver(tmp_path))
    content = render_rsync(plan)
    lines = [ln for ln in content.splitlines() if ln]
    assert lines == ["broll/military/clip.mov", "broll/news/clip2.mov"]


def test_render_rsync_excludes_duplicates(tmp_path):
    videos = [
        _video(1, "broll", "a.mov"),
        _video(2, "broll", "b.mov", duplicate_of=1),
    ]
    plan = plan_manifest(videos, _resolver(tmp_path))
    content = render_rsync(plan)
    assert content.strip() == "broll/a.mov"


def test_all_formats_survive_non_ascii_cjk_paths(tmp_path):
    videos = [_video(1, "broll", "軍事/演習_畫面.mov")]
    plan = plan_manifest(videos, _resolver(tmp_path))

    list_content = render_list(plan)
    robocopy_content = render_robocopy(plan)
    rsync_content = render_rsync(plan)

    assert "演習_畫面.mov" in list_content
    assert "演習_畫面.mov" in robocopy_content
    assert "軍事/演習_畫面.mov" in rsync_content

    # UTF-8 round trip through an actual file write, as a real export would do.
    out = tmp_path / "manifest.txt"
    out.write_text(list_content, encoding="utf-8")
    assert "演習_畫面.mov" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# do_export_manifest against a real DB
# ---------------------------------------------------------------------------

def test_do_export_manifest_end_to_end(tmp_path, schema_path):
    root = tmp_path / "share"
    root.mkdir()
    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    canonical = db.upsert_video("broll", "a.mov", status="indexed", size_bytes=1000)
    dup = db.upsert_video("broll", "b.mov", status="probed", size_bytes=1000)
    db.update_video(dup, duplicate_of=canonical)

    def resolve(video):
        return root / video["rel_path"]

    plan, content = do_export_manifest(db, resolve_path=resolve, fmt="list")
    assert len(plan.to_copy) == 1
    assert plan.to_copy[0]["video"]["id"] == canonical
    assert len(plan.skipped_duplicates) == 1
    assert plan.bytes_saved == 1000
    assert "b.mov" not in content
    assert "a.mov" in content


def test_do_export_manifest_unknown_format_raises():
    class SqliteBackendStub:
        def all_videos(self):
            return []

    with pytest.raises(ValueError):
        do_export_manifest(SqliteBackendStub(), resolve_path=lambda v: None, fmt="xml")


def test_excluded_originals_are_never_copied(tmp_path, schema_path):
    """The whole point of a source="proxies" share: only the proxy goes to the
    server. On the MOFA event that is 17.6 GB copied instead of 403 GB, so a
    manifest that included the originals would defeat the entire exercise."""
    root = tmp_path / "src"
    root.mkdir()
    db = SqliteBackend(tmp_path / "excl.db", schema_path=schema_path)
    proxy = db.upsert_video("mofa", "Day 1/Fx3/Proxy/a.mov", status="indexed", size_bytes=6_400_000)
    db.upsert_video("mofa", "Day 1/Fx3/a.MP4", status="excluded", size_bytes=128_700_000)

    def resolve(video):
        return root / video["rel_path"]

    plan, content = do_export_manifest(db, resolve_path=resolve, fmt="list")

    assert len(plan.to_copy) == 1
    assert plan.to_copy[0]["video"]["id"] == proxy
    assert "a.MP4" not in content, "the camera original must not be in the copy plan"
    assert "a.mov" in content
    assert plan.bytes_saved == 128_700_000
