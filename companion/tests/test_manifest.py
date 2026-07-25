"""manifest.py tests: local disk media manifest rollups + per-file lists,
and ManifestCache's background-refresh contract. No real filesystem scale --
tmp_path trees only, matching test_fixer.py's style."""

from __future__ import annotations

import time

from ccsync_companion import manifest as manifest_mod


def _make_project(tmp_path, year, series, project):
    project_dir = tmp_path / "Projects" / year / series / project
    project_dir.mkdir(parents=True)
    return project_dir


def _touch(path, size=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


# -- scan_local_manifest: rollups -----------------------------------------------


def test_scan_local_manifest_counts_originals_and_proxies(tmp_path):
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    _touch(project_dir / "A001.braw", size=1000)
    _touch(project_dir / "A002.mov", size=2000)
    _touch(project_dir / "Proxy" / "A001.mp4", size=100)
    _touch(project_dir / "Proxy" / "A002.mp4", size=200)

    result = manifest_mod.scan_local_manifest(str(tmp_path))
    entry = result["2026/FF5/Nuclear"]
    assert entry["n_originals"] == 2
    assert entry["bytes_originals"] == 3000
    assert entry["n_proxies"] == 2
    assert entry["bytes_proxies"] == 300
    assert entry["truncated"] is False
    # Not selected -> per-file lists are None.
    assert entry["originals"] is None
    assert entry["proxies"] is None


def test_scan_local_manifest_nested_proxy_dir_still_counted_as_proxy(tmp_path):
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    _touch(project_dir / "Interviews" / "Proxy" / "B001.mp4", size=50)

    result = manifest_mod.scan_local_manifest(str(tmp_path))
    entry = result["2026/FF5/Nuclear"]
    assert entry["n_proxies"] == 1
    assert entry["n_originals"] == 0


def test_scan_local_manifest_skips_non_video_files(tmp_path):
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    _touch(project_dir / "notes.txt", size=10)
    _touch(project_dir / "audio.wav", size=20)
    _touch(project_dir / "clip.mov", size=30)

    result = manifest_mod.scan_local_manifest(str(tmp_path))
    entry = result["2026/FF5/Nuclear"]
    assert entry["n_originals"] == 1
    assert entry["bytes_originals"] == 30


def test_scan_local_manifest_multiple_projects(tmp_path):
    _touch(_make_project(tmp_path, "2026", "FF5", "Nuclear") / "a.mov", size=10)
    _touch(_make_project(tmp_path, "2025", "FF4", "Solar") / "b.mov", size=20)

    result = manifest_mod.scan_local_manifest(str(tmp_path))
    assert set(result.keys()) == {"2026/FF5/Nuclear", "2025/FF4/Solar"}


def test_scan_local_manifest_missing_local_root_returns_empty(tmp_path):
    result = manifest_mod.scan_local_manifest(str(tmp_path / "does-not-exist"))
    assert result == {}


# -- per-file lists: selected_rels gating -----------------------------------------------


def test_scan_local_manifest_per_file_lists_only_for_selected_rels(tmp_path):
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    _touch(project_dir / "A001.braw", size=1000)
    _touch(project_dir / "Proxy" / "A001.mp4", size=100)
    _make_project(tmp_path, "2025", "FF4", "Solar")
    _touch(tmp_path / "Projects" / "2025" / "FF4" / "Solar" / "b.mov", size=20)

    result = manifest_mod.scan_local_manifest(str(tmp_path), selected_rels={"2026/FF5/Nuclear"})

    selected = result["2026/FF5/Nuclear"]
    assert selected["originals"] == [["A001.braw", 1000]]
    assert selected["proxies"] == [["Proxy/A001.mp4", 100]]

    not_selected = result["2025/FF4/Solar"]
    assert not_selected["originals"] is None
    assert not_selected["proxies"] is None
    # Rollups are still exact for non-selected projects.
    assert not_selected["n_originals"] == 1
    assert not_selected["bytes_originals"] == 20


def test_scan_local_manifest_truncates_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(manifest_mod, "MAX_PER_FILE_ENTRIES", 3)
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    for i in range(5):
        _touch(project_dir / f"clip{i}.mov", size=1)

    result = manifest_mod.scan_local_manifest(str(tmp_path), selected_rels={"2026/FF5/Nuclear"})
    entry = result["2026/FF5/Nuclear"]
    assert entry["n_originals"] == 5  # rollup count always exact
    assert len(entry["originals"]) == 3  # per-file list capped
    assert entry["truncated"] is True


def test_scan_local_manifest_under_cap_not_truncated(tmp_path):
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    _touch(project_dir / "clip.mov", size=1)

    result = manifest_mod.scan_local_manifest(str(tmp_path), selected_rels={"2026/FF5/Nuclear"})
    entry = result["2026/FF5/Nuclear"]
    assert entry["truncated"] is False


def test_scan_local_manifest_size_fn_error_skips_file(tmp_path):
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    _touch(project_dir / "clip.mov", size=1)

    def failing_size(path):
        raise OSError("vanished")

    result = manifest_mod.scan_local_manifest(str(tmp_path), size_fn=failing_size)
    entry = result["2026/FF5/Nuclear"]
    assert entry["n_originals"] == 0


# -- ManifestCache -----------------------------------------------------


def test_manifest_cache_get_before_start_is_empty(tmp_path):
    cache = manifest_mod.ManifestCache({"local_root": str(tmp_path)})
    assert cache.get() == {}


def test_manifest_cache_refresh_once_populates_cache(tmp_path):
    _touch(_make_project(tmp_path, "2026", "FF5", "Nuclear") / "a.mov", size=10)
    cache = manifest_mod.ManifestCache({"local_root": str(tmp_path)})
    cache.refresh_once()
    result = cache.get()
    assert result["2026/FF5/Nuclear"]["n_originals"] == 1


def test_manifest_cache_start_stop_background_thread(tmp_path):
    _touch(_make_project(tmp_path, "2026", "FF5", "Nuclear") / "a.mov", size=10)
    cache = manifest_mod.ManifestCache(
        {"local_root": str(tmp_path), "manifest_refresh_interval": 0.05}
    )
    cache.start()
    try:
        deadline = time.monotonic() + 3.0
        while not cache.get() and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        cache.stop()
    assert cache.get()["2026/FF5/Nuclear"]["n_originals"] == 1


def test_manifest_cache_refresh_once_never_raises_on_scan_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk error")

    monkeypatch.setattr(manifest_mod, "scan_local_manifest", boom)
    cache = manifest_mod.ManifestCache({"local_root": str(tmp_path)})
    cache.refresh_once()  # must not raise
    assert cache.get() == {}


def test_manifest_cache_uses_get_selected_rels_callback(tmp_path):
    project_dir = _make_project(tmp_path, "2026", "FF5", "Nuclear")
    _touch(project_dir / "a.mov", size=10)

    cache = manifest_mod.ManifestCache(
        {"local_root": str(tmp_path)}, get_selected_rels=lambda: {"2026/FF5/Nuclear"}
    )
    cache.refresh_once()
    entry = cache.get()["2026/FF5/Nuclear"]
    assert entry["originals"] == [["a.mov", 10]]
