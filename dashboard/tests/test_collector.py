from __future__ import annotations

import sqlite3
import time

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


def test_incomplete_pruned_when_device_no_longer_shared(conn, fake, collector):
    """A (slug, device) pair that drops out of _folder_devices (untick,
    deleted editor device, removed folder) must be pruned from _incomplete
    rather than lingering forever and making every future remoteneed cycle
    hit Syncthing with a stale folder/device pair."""
    key = ("2025-ff4-nuclear", EDITOR_ID)
    fake.state["completion"][key] = {"completion": 10.0, "needItems": 5,
                                     "needBytes": 100, "needDeletes": 0}
    collector.run_cycle(conn, ALL)
    assert key in collector._incomplete

    # EDITOR_ID no longer shares the folder -- config cycle rebuilds
    # _folder_devices without it.
    for folder in fake.state["folders"]:
        folder["devices"] = [d for d in folder["devices"] if d["deviceID"] != EDITOR_ID]
    collector.run_cycle(conn, ["config", "completion"])
    assert key not in collector._incomplete


def test_remoteneed_one_bad_pair_does_not_abort_the_cycle(conn, fake, collector, monkeypatch):
    """One (slug, device) pair whose Syncthing call raises must not abort the
    whole remoteneed cycle -- other pairs still get refreshed, and the
    runner is still recorded as ok (fault isolation, not a poll failure)."""
    key = ("2025-ff4-nuclear", EDITOR_ID)
    fake.state["completion"][key] = {"completion": 10.0, "needItems": 5,
                                     "needBytes": 100, "needDeletes": 0}
    collector.run_cycle(conn, ["config", "completion"])
    assert collector._incomplete  # sanity: something is incomplete

    orig = collector.client.remoteneed
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("simulated syncthing error")

    monkeypatch.setattr(collector.client, "remoteneed", flaky)
    results = collector.run_cycle(conn, ["remoteneed"])
    assert results["remoteneed"] is True   # the cycle itself still succeeds
    assert calls["n"] >= 1


def test_folder_removal_spares_recently_seen_project(conn, fake, collector):
    """A project row seen within the grace window survives a config cycle
    even with no Syncthing folder -- this is what keeps an eagerly-created
    /project-setup project active until provisioning catches up."""
    collector.run_cycle(conn, ALL)
    fake.state["folders"] = []
    collector.run_cycle(conn, ["config"])
    row = conn.execute("SELECT active FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()
    assert row["active"] == 1


def test_loop_survives_a_record_poll_run_exception(tmp_path, monkeypatch):
    """A DB error out of db.record_poll_run itself (e.g. a transient
    'database is locked') must not kill the collector thread for good --
    nothing else restarts it, and prune/retention stops with it."""
    settings = Settings(
        syncthing_url="http://127.0.0.1:1",  # nothing listens here -- every runner fails fast
        db_path=str(tmp_path / "loop.db"),
        interval_config=0.01, interval_enforce=0.01, interval_inventory=0.01,
        interval_connections=0.01, interval_completion=0.01, interval_remoteneed=0.01,
        interval_prune=0.01, interval_provision=0.01, backoff_max=0.05,
    )
    collector = Collector(settings, client=SyncthingClient(settings.syncthing_url, "k", timeout=0.2))

    calls = {"n": 0}
    real_record_poll_run = dbmod.record_poll_run

    def flaky_record_poll_run(conn, kind, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise sqlite3.OperationalError("database is locked")
        return real_record_poll_run(conn, kind, *a, **kw)

    monkeypatch.setattr(dbmod, "record_poll_run", flaky_record_poll_run)
    collector.start()
    try:
        deadline = time.monotonic() + 5.0
        while calls["n"] < 5 and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        collector.stop()
    # The thread kept calling record_poll_run THROUGH the injected failures
    # (proving the loop iteration's exception was caught and it kept
    # ticking) and stop() joined it cleanly.
    assert calls["n"] >= 5
    assert not collector._thread.is_alive()
