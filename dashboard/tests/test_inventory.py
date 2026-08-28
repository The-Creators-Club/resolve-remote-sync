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


def test_inventory_walks_outside_the_write_transaction(conn, tmp_path, collector, monkeypatch):
    """record_inventory_error/replace_nas_media used to bracket up to eight
    full recursive walks of a ZFS/NFS tree, so every editor's POST
    /api/v1/report during an inventory cycle 500'd with 'database is
    locked'. All walking happens before the first write now."""
    make_project_tree(tmp_path / "projects", "2025/FF4/Nuclear")
    other = dbmod.connect(conn.execute("PRAGMA database_list").fetchone()[2])
    other.execute("PRAGMA busy_timeout=200")
    blocked = []

    orig = Collector._walk_media_files

    def probing_walk(proj_dir):
        try:
            other.execute("INSERT INTO poll_runs (kind, started_at, ok) VALUES ('probe','x',1)")
            other.commit()
        except Exception as exc:      # pragma: no cover - only on regression
            blocked.append(str(exc))
        return orig(proj_dir)

    monkeypatch.setattr(Collector, "_walk_media_files", staticmethod(probing_walk))
    try:
        assert collector.run_cycle(conn, ["config", "inventory"])["inventory"] is True
    finally:
        other.close()
    assert blocked == []


def test_inventory_disabled_without_projects_dir(conn, fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k")  # no projects_dir
    from ccsync_dashboard.syncthing_client import SyncthingClient
    c = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
    results = c.run_cycle(conn, ["config", "inventory"])
    assert results["inventory"] is True
    assert conn.execute("SELECT COUNT(*) FROM poll_runs WHERE kind='inventory'").fetchone()[0] == 0


# -- the collapse brake + the not-mounted canary (DASH-5, resilience sweep
#    2026-08-28). An unmounted ZFS dataset under /projects/<project> leaves
#    the dir present and EMPTY, so the walk returned [] and the old code
#    wrote 0 originals / 0 proxies with last_error NULL: every media-presence
#    view then said the NAS holds nothing and the backlog listed every
#    original an editor holds as missing from the server.

def test_replace_nas_media_refuses_a_collapse_to_zero(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", "2026-08-28T00:00:00+00:00")
    rows = [("B-roll/a.braw", "original", ".braw", 100, 1),
            ("B-roll/b.braw", "original", ".braw", 100, 2),
            ("B-roll/Proxy/a.mov", "proxy", ".mov", 10, 3)]
    assert dbmod.replace_nas_media(conn, pid, rows, "sig1", 2,
                                   "2026-08-28T00:00:00+00:00") is True

    assert dbmod.replace_nas_media(conn, pid, [], "sig2", 1,
                                   "2026-08-28T01:00:00+00:00") is False
    summary = dbmod.fetch_nas_media_summary(conn, pid)
    assert summary["n_originals"] == 2 and summary["n_proxies"] == 1
    assert "0 of 3 files" in summary["last_error"]
    assert conn.execute("SELECT COUNT(*) FROM nas_media").fetchone()[0] == 3
    # tree_sig must NOT advance, or the next cycle believes it is up to date
    # and never walks again.
    assert dbmod.nas_inventory_sig(conn, pid) == "sig1"


def test_replace_nas_media_refuses_losing_more_than_90_percent(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", "2026-08-28T00:00:00+00:00")
    rows = [(f"B-roll/{i}.braw", "original", ".braw", 10, i) for i in range(40)]
    dbmod.replace_nas_media(conn, pid, rows, "sig1", 2, "2026-08-28T00:00:00+00:00")
    assert dbmod.replace_nas_media(conn, pid, rows[:3], "sig2", 2,
                                   "2026-08-28T01:00:00+00:00") is False
    assert dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 40
    # ...but a normal churn is applied.
    assert dbmod.replace_nas_media(conn, pid, rows[:30], "sig3", 2,
                                   "2026-08-28T02:00:00+00:00") is True
    summary = dbmod.fetch_nas_media_summary(conn, pid)
    assert summary["n_originals"] == 30 and summary["last_error"] is None


def test_replace_nas_media_force_overrides_the_brake(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", "2026-08-28T00:00:00+00:00")
    rows = [("a.braw", "original", ".braw", 10, 1)]
    dbmod.replace_nas_media(conn, pid, rows, "sig1", 1, "2026-08-28T00:00:00+00:00")
    assert dbmod.replace_nas_media(conn, pid, [], "sig2", 1,
                                   "2026-08-28T01:00:00+00:00", force=True) is True
    assert dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 0


def test_a_first_walk_of_an_empty_project_is_not_refused(conn):
    """There is nothing to protect on a project with no recorded inventory:
    the brake must not stop a genuinely empty new project being recorded."""
    pid = dbmod.upsert_project(conn, "p", "P", "/p", "2026-08-28T00:00:00+00:00")
    assert dbmod.replace_nas_media(conn, pid, [], "sig1", 1,
                                   "2026-08-28T00:00:00+00:00") is True
    assert dbmod.fetch_nas_media_summary(conn, pid)["last_error"] is None


def test_an_unmounted_project_dir_keeps_its_inventory(conn, tmp_path, collector):
    """End to end: the dir empties out between two cycles (dataset not
    mounted, or renamed by hand mid-cycle) and the collector keeps the last
    good inventory, with the reason on the row the project page reads."""
    proj = make_project_tree(tmp_path / "projects", "2025/FF4/Nuclear")
    collector.run_cycle(conn, ["config", "inventory"])
    pid = conn.execute("SELECT id FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()[0]
    assert dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 2

    import shutil
    shutil.rmtree(proj / "B-roll")
    shutil.rmtree(proj / "Audio")
    (proj / ".stfolder").mkdir()        # the marker is still there: really empty
    note = collector._run_inventory(conn)
    summary = dbmod.fetch_nas_media_summary(conn, pid)
    assert summary["n_originals"] == 2                    # kept
    assert "not replacing" in summary["last_error"]
    assert note and "collapsed" in note


def test_a_project_dir_with_no_marker_and_no_media_reads_as_unmounted(conn, tmp_path, collector):
    (tmp_path / "projects" / "2025" / "FF4" / "Nuclear").mkdir(parents=True)
    (tmp_path / "projects" / "keep-the-tree-non-empty").mkdir()
    collector.run_cycle(conn, ["config"])
    note = collector._run_inventory(conn)
    pid = conn.execute("SELECT id FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()[0]
    row = conn.execute("SELECT last_error FROM nas_inventory_state WHERE project_id=?",
                       (pid,)).fetchone()
    assert row is not None and "unmounted" in row["last_error"]
    assert note and "unreadable" in note


def test_an_empty_projects_tree_reads_as_unmounted_not_empty(conn, tmp_path, collector):
    """/projects is a bind mount POINT, so it exists whether or not the
    dataset under it is mounted. Zero entries is never a live fleet."""
    make_project_tree(tmp_path / "projects", "2025/FF4/Nuclear")
    collector.run_cycle(conn, ["config", "inventory"])
    pid = conn.execute("SELECT id FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()[0]

    import shutil
    shutil.rmtree(tmp_path / "projects" / "2025")
    note = collector._run_inventory(conn)
    assert note and "unmounted" in note
    assert dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 2
