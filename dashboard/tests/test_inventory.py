from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings

from fake_syncthing import FakeSyncthing


def test_classify_media():
    f = provision.classify_media
    assert f(["B-roll", "a.braw"], ".braw") == "original"
    assert f(["B-roll", "Proxy", "a.mov"], ".mov") == "proxy"
    assert f(["b-roll", "proxy", "a.mov"], ".mov") == "proxy"    # case-insensitive
    assert f(["Audio", "track.wav"], ".wav") is None             # non-video skipped
    assert f(["notes.txt"], ".txt") is None


def make_project_tree(root, rel):
    d = root / rel
    (d / "B-roll").mkdir(parents=True)
    (d / "B-roll" / "A001.braw").write_bytes(b"x" * 100)
    (d / "B-roll" / "A002.mov").write_bytes(b"y" * 50)
    (d / "B-roll" / "Proxy").mkdir()
    (d / "B-roll" / "Proxy" / "A001.mov").write_bytes(b"z" * 10)
    (d / "Audio").mkdir()
    (d / "Audio" / "music.wav").write_bytes(b"w" * 5)  # non-video, skipped
    return d


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


@pytest.fixture
def collector(fake, tmp_path):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k",
                        projects_dir=str(tmp_path / "projects"))
    from ccsync_dashboard.syncthing_client import SyncthingClient
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def test_inventory_walks_and_classifies(conn, tmp_path, collector):
    projects = tmp_path / "projects"
    make_project_tree(projects, "2025/FF4/Nuclear")
    # the fake config has folder 2025-ff4-nuclear with label 2025/FF4/Nuclear
    collector.run_cycle(conn, ["config", "inventory"])
    pid = conn.execute("SELECT id FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()[0]
    summary = dbmod.fetch_nas_media_summary(conn, pid)
    assert summary["n_originals"] == 2 and summary["bytes_originals"] == 150
    assert summary["n_proxies"] == 1 and summary["bytes_proxies"] == 10
    rows = conn.execute("SELECT rel_path, kind FROM nas_media WHERE project_id=? ORDER BY rel_path",
                        (pid,)).fetchall()
    assert ("B-roll/Proxy/A001.mov", "proxy") in [(r["rel_path"], r["kind"]) for r in rows]
    assert not any("music.wav" in r["rel_path"] for r in rows)  # non-video excluded


def test_inventory_signature_skip(conn, tmp_path, collector, monkeypatch):
    make_project_tree(tmp_path / "projects", "2025/FF4/Nuclear")
    collector.run_cycle(conn, ["config", "inventory"])

    # a second inventory pass with the tree unchanged must NOT re-walk files
    calls = []
    orig = Collector._walk_media_files
    monkeypatch.setattr(Collector, "_walk_media_files",
                        staticmethod(lambda p: calls.append(p) or orig(p)))
    collector.run_cycle(conn, ["inventory"])
    assert calls == []  # signature matched -> file walk skipped


def test_inventory_disabled_without_projects_dir(conn, fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k")  # no projects_dir
    from ccsync_dashboard.syncthing_client import SyncthingClient
    c = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
    results = c.run_cycle(conn, ["config", "inventory"])
    assert results["inventory"] is True
    assert conn.execute("SELECT COUNT(*) FROM poll_runs WHERE kind='inventory'").fetchone()[0] == 0
