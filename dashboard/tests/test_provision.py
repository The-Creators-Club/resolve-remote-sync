from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR2_ID, EDITOR_ID, SERVER_ID, FakeSyncthing


def make_tree(root):
    for rel in ["2025/FF4/Nuclear", "2026/FF5/Energy Transition",
                "2026/Creator Profiles/Season 1"]:
        (root / rel).mkdir(parents=True)
    (root / "2026/.hidden/Secret").mkdir(parents=True)
    (root / "2026/too-shallow").mkdir(parents=True)
    (root / "2026/FF5/Energy Transition/AE").mkdir()  # depth 4: not a project
    (root / "2025/FF4/notes.txt").parent.joinpath("notes.txt").write_text("x")
    return root


def test_scan_project_dirs(tmp_path):
    make_tree(tmp_path)
    assert provision.scan_project_dirs(tmp_path) == [
        "2025/FF4/Nuclear",
        "2026/Creator Profiles/Season 1",
        "2026/FF5/Energy Transition",
    ]


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
    # nuclear pre-existed; the two 2026 projects were created
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

    # hydrated into the DB in the same cycle
    slugs = [p["slug"] for p in dbmod.fetch_projects(conn)]
    assert "2026-ff5-energy-transition" in slugs and "2026-creator-profiles-season-1" in slugs


def test_provision_is_idempotent_and_preserves_existing(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    snapshot = [f["id"] for f in fake.state["folders"]]
    nuclear_before = next(f for f in fake.state["folders"] if f["id"] == "2025-ff4-nuclear")
    collector.run_cycle(conn, ["provision"])
    assert [f["id"] for f in fake.state["folders"]] == snapshot
    nuclear_after = next(f for f in fake.state["folders"] if f["id"] == "2025-ff4-nuclear")
    assert nuclear_before is nuclear_after  # untouched, not recreated


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
