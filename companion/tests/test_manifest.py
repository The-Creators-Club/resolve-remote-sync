"""manifest.py tests: local disk media manifest rollups + per-file lists,
and ManifestCache's background-refresh contract. No real filesystem scale --
tmp_path trees only, matching test_fixer.py's style."""

from __future__ import annotations

import logging
import time

from ccsync_companion import manifest as manifest_mod


def _make_project(tmp_path, year, series, project):
    from conftest import write_project_marker

    project_dir = tmp_path / "Projects" / year / series / project
    project_dir.mkdir(parents=True)
    write_project_marker(project_dir, slug=f"{year}-{series}-{project}".lower().replace(" ", "-"))
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


def test_hand_edited_refresh_interval_never_raises_in_the_constructor(tmp_path, caplog):
    """ManifestCache is built inside CompanionApp.__init__, so a bare
    float(cfg.get(...)) on a hand-edited value took the windowed exe down
    with no tray and no log line (AUDIT_3 M-5)."""
    with caplog.at_level(logging.ERROR, logger="ccsync.config"):
        cache = manifest_mod.ManifestCache(
            {"local_root": str(tmp_path), "manifest_refresh_interval": "5m"}
        )
    assert cache.refresh_interval == 300.0
    assert manifest_mod.ManifestCache(
        {"local_root": str(tmp_path), "manifest_refresh_interval": 45}
    ).refresh_interval == 45.0


# -- B6: the project-count cap ---------------------------------------------


def test_scan_caps_the_number_of_projects_reported(tmp_path, caplog):
    """KNOWN_BUGS B6: this module emitted one key per marker-bearing dir with
    NO cap, while the dashboard capped local_manifest at 64 with a raising
    validator -- so a 65th project 422'd the entire heavy report and, because
    an idle companion only ever sends heavy ticks, took the machine off the
    fleet grid. Worst placed is the base rig, whose local_root is the whole
    NAS tree at P:\\."""
    manifest_mod._last_truncation_logged = None
    for i in range(manifest_mod.MAX_PROJECTS + 6):
        _touch(_make_project(tmp_path, "2026", "FF5", f"P{i:03d}") / "a.mov", size=10)

    with caplog.at_level(logging.WARNING, logger="ccsync.manifest"):
        result = manifest_mod.scan_local_manifest(str(tmp_path))
    assert len(result) == manifest_mod.MAX_PROJECTS
    # truncation is LOGGED, never silent
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "6 older project(s)" in logged
    assert "64 of 70 project(s)" in logged


def test_selected_projects_always_survive_the_cap(tmp_path):
    """The editor's TICKED projects are the ones being synced and the ones
    whose per-file lists the presence view needs -- they must never be the
    entries that get dropped."""
    manifest_mod._last_truncation_logged = None
    for i in range(manifest_mod.MAX_PROJECTS + 5):
        _touch(_make_project(tmp_path, "2026", "FF5", f"P{i:03d}") / "a.mov", size=10)
    # the LAST project alphabetically would otherwise be a natural casualty
    selected = {"2026/FF5/P000", f"2026/FF5/P{manifest_mod.MAX_PROJECTS + 4:03d}"}

    result = manifest_mod.scan_local_manifest(str(tmp_path), selected_rels=selected)
    assert len(result) == manifest_mod.MAX_PROJECTS
    for rel in selected:
        assert rel in result
        assert result[rel]["originals"] == [["a.mov", 10]]


def test_prioritize_is_a_no_op_below_the_cap(tmp_path):
    rels = ["2026/FF5/A", "2026/FF5/B"]
    kept, dropped = manifest_mod.prioritize_project_rels(str(tmp_path), rels, None)
    assert kept == rels and dropped == 0


def test_prioritize_keeps_the_most_recently_touched(tmp_path):
    """A base rig holds hundreds of projects going back years; an active
    shoot must outrank a 2019 archive."""
    import os

    rels = []
    for i in range(6):
        d = _make_project(tmp_path, "2026", "FF5", f"P{i}")
        os.utime(d, (1_600_000_000 + i * 1000, 1_600_000_000 + i * 1000))
        rels.append(f"2026/FF5/P{i}")
    kept, dropped = manifest_mod.prioritize_project_rels(
        str(tmp_path), rels, None, max_projects=2)
    assert dropped == 4
    assert set(kept) == {"2026/FF5/P5", "2026/FF5/P4"}


# -- the tree has to actually be there (root_guard.py) ----------------------


def test_a_rescan_is_skipped_while_the_root_is_absent(tmp_path):
    """An empty scan is NOT the same answer as no scan. The manifest is this
    machine's "which files do I hold" report and the dashboard diffs it -- a
    macOS editor unplugging their SSD would otherwise report every project as
    zero files, indistinguishable server-side from having deleted the lot."""
    project = _make_project(tmp_path, "2026", "FF5", "Alpha")
    _touch(project / "clip.mov", 10)

    present = {"value": True}
    cache = manifest_mod.ManifestCache(
        {"local_root": str(tmp_path)}, root_present_fn=lambda: present["value"]
    )
    cache.refresh_once()
    good = cache.get()
    assert good["2026/FF5/Alpha"]["n_originals"] == 1

    # The drive goes away, and with it the whole tree.
    present["value"] = False
    cache.refresh_once()

    assert cache.get() == good, "an unplugged drive was reported as an empty tree"


def test_the_default_gate_is_a_plain_isdir(tmp_path):
    """No callable wired in (legacy construction, tests): the cache answers
    for itself rather than scanning a tree that is not there."""
    missing = manifest_mod.ManifestCache({"local_root": str(tmp_path / "gone")})
    assert missing._root_is_present() is False
    here = manifest_mod.ManifestCache({"local_root": str(tmp_path)})
    assert here._root_is_present() is True


def test_a_raising_gate_scans_anyway(tmp_path):
    """Fail open: a broken gate must cost a wasted walk, never the whole
    manifest."""
    def _boom():
        raise RuntimeError("no")

    cache = manifest_mod.ManifestCache({"local_root": str(tmp_path)}, root_present_fn=_boom)
    assert cache._root_is_present() is True
