from __future__ import annotations

import json

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR2_ID, EDITOR_ID, SERVER_ID, FakeSyncthing


def mark(root, rel, slug=None):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    provision.write_marker(d, slug or provision.slugify(rel))
    return d


def make_tree(root):
    mark(root, "2025/FF4/Nuclear")
    mark(root, "2026/FF5/Energy Transition")
    mark(root, "2026/Creator Profiles/Season 1")
    (root / "2026/.hidden/Secret").mkdir(parents=True)
    (root / "2026/bare-no-marker").mkdir(parents=True)          # invisible: no marker
    (root / "2026/FF5/Energy Transition/AE").mkdir()             # inside a project: pruned
    (root / "2025/FF4/notes.txt").parent.joinpath("notes.txt").write_text("x")
    return root


def test_scan_project_dirs_markers_any_depth(tmp_path):
    make_tree(tmp_path)
    # depth-4 project under a container
    mark(tmp_path, "2026/CCT/Creator Profiles/Season 2")
    # depth-1 project
    mark(tmp_path, "OneOffs")
    assert provision.scan_project_dirs(tmp_path) == [
        ("2025/FF4/Nuclear", "2025-ff4-nuclear"),
        ("2026/CCT/Creator Profiles/Season 2", "2026-cct-creator-profiles-season-2"),
        ("2026/Creator Profiles/Season 1", "2026-creator-profiles-season-1"),
        ("2026/FF5/Energy Transition", "2026-ff5-energy-transition"),
        ("OneOffs", "oneoffs"),
    ]


def test_scan_prunes_nested_markers_and_skips_containers(tmp_path):
    outer = mark(tmp_path, "2026/Show")
    mark(tmp_path, "2026/Show/Nested")     # nested: pruned by outer
    (tmp_path / "2026/Container").mkdir(parents=True)
    mark(tmp_path, "2026/Container/Real Project")
    scanned = provision.scan_project_dirs(tmp_path)
    rels = [r for r, _ in scanned]
    assert "2026/Show" in rels
    assert "2026/Show/Nested" not in rels
    assert "2026/Container" not in rels                 # container itself: no marker
    assert "2026/Container/Real Project" in rels


def test_scan_malformed_marker_yields_none_slug(tmp_path):
    d = tmp_path / "2026/Broken"
    d.mkdir(parents=True)
    (d / provision.MARKER_FILENAME).write_text("not json{", encoding="utf-8")
    assert provision.scan_project_dirs(tmp_path) == [("2026/Broken", None)]


def test_slugify_matches_server_convention():
    assert provision.slugify("2026/Creator Profiles/Season 1") == "2026-creator-profiles-season-1"
    assert provision.slugify("2025/FF4/Nuclear") == "2025-ff4-nuclear"


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


def collector_for(fake, tmp_path):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k",
                        projects_dir=str(tmp_path), syncthing_data_prefix="/data/Projects")
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def test_provision_creates_missing_folders(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    results = collector.run_cycle(conn, ["provision", "config"])
    assert results["provision"] is True and results["config"] is True

    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert set(by_id) == {"2025-ff4-nuclear", "2026-creator-profiles-season-1",
                          "2026-ff5-energy-transition"}
    created = by_id["2026-ff5-energy-transition"]
    assert created["label"] == "2026/FF5/Energy Transition"
    assert created["path"] == "/data/Projects/2026/FF5/Energy Transition"
    assert created["type"] == "sendreceive"
    assert created["ignorePerms"] is True
    assert created["versioning"]["type"] == "staggered"
    # created UNSHARED: the selections table + enforce cycle drive sharing
    assert created["devices"] == []

    ignores = fake.state["ignores"]["2026-ff5-energy-transition"]
    assert "(?i)*.braw" in ignores and "(?i)**/Proxy/**" in ignores

    slugs = [p["slug"] for p in dbmod.fetch_projects(conn)]
    assert "2026-ff5-energy-transition" in slugs and "2026-creator-profiles-season-1" in slugs


def test_provision_uses_marker_slug_not_path_slug(conn, fake, tmp_path):
    """An adopted/moved project keeps its marker identity even when the
    path would slugify differently."""
    mark(tmp_path, "2026/CCT/Moved Show", slug="original-identity")
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert "original-identity" in by_id
    assert by_id["original-identity"]["label"] == "2026/CCT/Moved Show"


def test_provision_retargets_moved_project(conn, fake, tmp_path):
    """The live 2026-07-25 scenario: dir moved on the NAS, marker traveled
    with it, folder must be re-pointed in place (same slug -- ticks/history
    survive)."""
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision", "config"])

    # move Season 1 into a CCT container (marker travels with the dir)
    src = tmp_path / "2026/Creator Profiles/Season 1"
    dst = tmp_path / "2026/CCT/Creator Profiles/Season 1"
    dst.parent.mkdir(parents=True)
    src.rename(dst)

    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    moved = by_id["2026-creator-profiles-season-1"]         # SAME slug
    assert moved["path"] == "/data/Projects/2026/CCT/Creator Profiles/Season 1"
    assert moved["label"] == "2026/CCT/Creator Profiles/Season 1"
    # projects row updated in the same cycle
    row = conn.execute("SELECT label, path FROM projects WHERE slug=?",
                       ("2026-creator-profiles-season-1",)).fetchone()
    assert row["label"] == "2026/CCT/Creator Profiles/Season 1"


def test_provision_self_heals_missing_markers(conn, fake, tmp_path):
    """A pre-marker-era folder (or a marker someone deleted) gets its marker
    rewritten from the Syncthing folder id."""
    d = tmp_path / "2025/FF4/Nuclear"
    d.mkdir(parents=True)          # NO marker; folder exists in fake config
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    assert provision.read_marker(d) == "2025-ff4-nuclear"


def test_provision_duplicate_slug_dirs_skipped_or_current_kept(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    # copy Nuclear elsewhere WITH its marker (same slug, two dirs)
    copy = tmp_path / "2026/Copies/Nuclear Copy"
    copy.mkdir(parents=True)
    provision.write_marker(copy, "2025-ff4-nuclear")

    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    # the folder still points at the ORIGINAL (current-path preferred)
    assert by_id["2025-ff4-nuclear"]["path"] == "/data/Projects/2025/FF4/Nuclear"


def test_provision_never_deletes_folders(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    import shutil
    shutil.rmtree(tmp_path / "2025/FF4/Nuclear")
    collector.run_cycle(conn, ["provision"])
    assert any(f["id"] == "2025-ff4-nuclear" for f in fake.state["folders"])


def test_provision_is_idempotent_and_preserves_existing(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    snapshot = [f["id"] for f in fake.state["folders"]]
    put_calls_before = len(fake.state.get("put_folder_calls", []))
    collector.run_cycle(conn, ["provision"])
    assert [f["id"] for f in fake.state["folders"]] == snapshot
    # no retarget/label PUTs on a stable tree
    assert len(fake.state.get("put_folder_calls", [])) == put_calls_before


def test_provision_disabled_when_no_projects_dir(conn, fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k")  # projects_dir=""
    collector = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
    results = collector.run_cycle(conn, ["provision"])
    assert results["provision"] is True
    assert conn.execute("SELECT COUNT(*) FROM poll_runs WHERE kind='provision'").fetchone()[0] == 0


def test_provision_fails_loud_on_missing_dir(conn, fake, tmp_path):
    collector = collector_for(fake, tmp_path / "nope")
    results = collector.run_cycle(conn, ["provision"])
    assert results["provision"] is False
    run = conn.execute("SELECT * FROM poll_runs WHERE kind='provision'").fetchone()
    assert "does not exist" in run["error"]
