from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR2_ID, EDITOR_ID, FakeSyncthing

ALL = ["config", "connections", "completion", "remoteneed"]


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


@pytest.fixture
def collector(fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="test-key")
    return Collector(settings, client=SyncthingClient(fake.url, "test-key", timeout=5))


def test_full_cycle_populates_db(conn, fake, collector):
    results = collector.run_cycle(conn, ALL)
    assert all(results.values()), results

    projects = dbmod.fetch_projects(conn)
    assert [p["slug"] for p in projects] == ["2025-ff4-nuclear"]
    editors = projects[0]["editors"]
    assert len(editors) == 2  # server device excluded

    by_dev = {e["device_id"]: e for e in editors}
    jsmith = by_dev[EDITOR_ID]
    assert jsmith["editor_username"] == "jsmith"
    assert jsmith["connected"] == 1 and jsmith["completion"] == 62.5
    assert jsmith["need_items"] == 45 and jsmith["global_items"] == 120

    unmapped = by_dev[EDITOR2_ID]
    assert unmapped["editor_username"] is None
    assert unmapped["completion"] == 100.0 and unmapped["connected"] == 0

    missing = dbmod.fetch_missing(conn, projects[0]["id"], jsmith["device_row_id"])
    assert len(missing["files"]) == 45 and missing["truncated"] is False
    assert missing["files"][0]["name"] == "Audio/Music/track000.wav"
    # fully-synced editor has no missing rows
    assert dbmod.fetch_missing(conn, projects[0]["id"], unmapped["device_row_id"])["files"] == []
    assert dbmod.fetch_collector_status(conn)["syncthing_reachable"] is True


def test_completion_reaching_100_clears_missing(conn, fake, collector):
    collector.run_cycle(conn, ALL)
    key = ("2025-ff4-nuclear", EDITOR_ID)
    fake.state["completion"][key] = {"completion": 100.0, "needItems": 0,
                                     "needBytes": 0, "needDeletes": 0}
    collector.run_cycle(conn, ALL)
    projects = dbmod.fetch_projects(conn)
    jsmith = next(e for e in projects[0]["editors"] if e["device_id"] == EDITOR_ID)
    assert jsmith["completion"] == 100.0
    assert dbmod.fetch_missing(conn, projects[0]["id"], jsmith["device_row_id"])["files"] == []


def test_remoteneed_caps_and_flags_truncation(conn, fake, collector):
    key = ("2025-ff4-nuclear", EDITOR_ID)
    fake.state["completion"][key] = {"completion": 10.0, "needItems": 900,
                                     "needBytes": 10_000, "needDeletes": 0}
    fake.state["remoteneed"][key] = [{"name": f"f{i:04}", "size": i} for i in range(900)]
    collector.run_cycle(conn, ALL)
    projects = dbmod.fetch_projects(conn)
    jsmith = next(e for e in projects[0]["editors"] if e["device_id"] == EDITOR_ID)
    missing = dbmod.fetch_missing(conn, projects[0]["id"], jsmith["device_row_id"])
    assert len(missing["files"]) == 500  # 3 pages of 200, capped to 500 in the DB
    assert missing["truncated"] is True


def test_syncthing_down_records_failures_not_exceptions(conn, fake, collector):
    fake.state["down"] = True
    results = collector.run_cycle(conn, ALL)
    assert not any(results.values())
    status = dbmod.fetch_collector_status(conn)
    assert status["syncthing_reachable"] is False
    assert all(not run["ok"] for run in status["kinds"].values())
    # recovery works with the same collector instance
    fake.state["down"] = False
    assert all(collector.run_cycle(conn, ALL).values())


def test_folder_removal_deactivates_project(conn, fake, collector):
    collector.run_cycle(conn, ALL)
    fake.state["folders"] = []
    # Age the row past the deactivation grace window (which exists so
    # eagerly-created /project-setup projects survive the provisioning gap).
    import datetime as _dt
    aged = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)) \
        .replace(microsecond=0).isoformat()
    conn.execute("UPDATE projects SET last_seen=?", (aged,))
    conn.commit()
    collector.run_cycle(conn, ["config"])
    assert dbmod.fetch_projects(conn) == []  # active only
    row = conn.execute("SELECT active FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()
    assert row["active"] == 0


def test_folder_removal_spares_recently_seen_project(conn, fake, collector):
    """A project row seen within the grace window survives a config cycle
    even with no Syncthing folder -- this is what keeps an eagerly-created
    /project-setup project active until provisioning catches up."""
    collector.run_cycle(conn, ALL)
    fake.state["folders"] = []
    collector.run_cycle(conn, ["config"])
    row = conn.execute("SELECT active FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()
    assert row["active"] == 1
