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


def test_completion_one_bad_device_does_not_roll_back_the_cycle(conn, fake, collector, monkeypatch):
    """Unlike remoteneed, _run_completion had no per-pair isolation: one
    device erroring propagated to _timed, which rolled back every row already
    written for every OTHER project/device -- so five minutes later the whole
    fleet went red at once, uniformly, with no explanation."""
    real = collector.client.completion

    def flaky(folder, device):
        if device == EDITOR_ID:
            raise RuntimeError("simulated syncthing error")
        return real(folder, device)

    monkeypatch.setattr(collector.client, "completion", flaky)
    results = collector.run_cycle(conn, ALL)
    assert results["completion"] is True                 # isolated, not a cycle failure
    projects = dbmod.fetch_projects(conn)
    by_dev = {e["device_id"]: e for e in projects[0]["editors"]}
    assert EDITOR2_ID in by_dev and by_dev[EDITOR2_ID]["completion"] == 100.0
    assert EDITOR_ID not in by_dev                       # no bogus row for the failed pair


def test_completion_skips_a_response_without_a_completion_key(conn, fake, collector):
    """A 200 with an unexpected body must not be recorded as '0% synced, 0
    files needed': on the project page that is indistinguishable from real
    data loss."""
    fake.state["completion"][("2025-ff4-nuclear", EDITOR_ID)] = {"unexpected": "body"}
    collector.run_cycle(conn, ALL)
    projects = dbmod.fetch_projects(conn)
    by_dev = {e["device_id"]: e for e in projects[0]["editors"]}
    assert EDITOR_ID not in by_dev
    assert by_dev[EDITOR2_ID]["completion"] == 100.0


def test_completion_records_syncthing_folder_state(conn, fake, collector):
    """db_status's state/error were read and thrown away, so a folder that
    had STOPPED syncing showed a stale-but-plausible completion % forever."""
    fake.state["db_status"]["2025-ff4-nuclear"] = {
        "globalFiles": 120, "globalBytes": 5_000_000,
        "state": "stopped", "error": "folder marker missing",
    }
    collector.run_cycle(conn, ALL)
    status = dbmod.fetch_collector_status(conn)
    assert [(e["slug"], e["folder_error"]) for e in status["folder_errors"]] == [
        ("2025-ff4-nuclear", "folder marker missing")]
    from ccsync_dashboard.api import build_project_view
    view = build_project_view(conn, "2025-ff4-nuclear")
    assert view["folder_state"] == "stopped"
    assert view["folder_error"] == "folder marker missing"


def test_no_write_transaction_is_held_open_across_syncthing_calls(conn, fake, collector, tmp_path):
    """The 'database is locked' 500s: db.upsert_completion opened the write
    transaction on the first row and the loop then kept issuing 10s-timeout
    HTTP calls before the commit. A second connection (an editor's report)
    must be able to write DURING the cycle's network phase."""
    other = dbmod.connect(conn.execute("PRAGMA database_list").fetchone()[2])
    other.execute("PRAGMA busy_timeout=200")
    blocked: list[str] = []

    real_completion = collector.client.completion

    def probing_completion(folder, device):
        # Called between DB writes in the old code; now strictly before them.
        try:
            other.execute("INSERT INTO poll_runs (kind, started_at, ok) VALUES ('probe', 'x', 1)")
            other.commit()
        except Exception as exc:      # pragma: no cover - only on regression
            blocked.append(str(exc))
        return real_completion(folder, device)

    collector.client.completion = probing_completion
    try:
        assert collector.run_cycle(conn, ALL)["completion"] is True
    finally:
        collector.client.completion = real_completion
        other.close()
    assert blocked == []


def test_inventory_uses_the_project_path_not_its_label(conn, fake, tmp_path):
    """A folder whose label isn't the rel path (hand-created folders, and
    X-3's adopted projects) made projects_dir/label miss every cycle:
    record_inventory_error forever, MEDIA PRESENCE stuck on 'NAS has 0
    original(s)', and health.presence_status GREEN for a base rig holding
    nothing."""
    projects = tmp_path / "projects"
    proj = projects / "2025/FF4/Nuclear/B-roll"
    proj.mkdir(parents=True)
    (proj / "A001.braw").write_bytes(b"x" * 10)
    fake.state["folders"][0]["label"] = "Nuclear (Sam's cut)"   # label != rel path

    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k",
                        projects_dir=str(projects))
    c = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
    c.run_cycle(conn, ["config", "inventory"])
    pid = conn.execute("SELECT id FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()[0]
    assert dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 1
    row = conn.execute("SELECT last_error FROM nas_inventory_state WHERE project_id=?",
                       (pid,)).fetchone()
    assert row["last_error"] is None


def test_prune_runs_without_syncthing_configured(conn, tmp_path):
    """db.prune is reachable ONLY from the collector, and the collector used
    to be started only when SYNCTHING_GUI_URL was set -- so a Syncthing-less
    deployment (which settings.py fully supports) grew eight tables forever."""
    settings = Settings(db_path=str(tmp_path / "p.db"))       # no syncthing_url
    c = Collector(settings, client=SyncthingClient("", "", timeout=1))
    old = "2026-06-01T12:00:00+00:00"
    dbmod.upsert_lane_report(
        conn, editor_username="ghost", machine="OLD-PC", lane="lane_a_video_up",
        state="idle", queued=0, transferring=0, last_error=None, last_sync=None,
        detail=None, companion_version="0.1.0", reported_at=old, received_at=old,
    )
    conn.commit()
    results = c.run_cycle(conn, ["config", "connections", "prune"])
    assert results["prune"] is True
    assert results["config"] is True and results["connections"] is True   # skipped, not failed
    assert conn.execute("SELECT COUNT(*) FROM lane_report_current").fetchone()[0] == 0
    # ...and nothing pretends Syncthing is reachable off a prune run
    assert dbmod.fetch_collector_status(conn)["syncthing_reachable"] is False


def test_app_starts_the_collector_without_syncthing(tmp_path):
    from fastapi.testclient import TestClient

    from ccsync_dashboard.app import create_app

    app = create_app(Settings(db_path=str(tmp_path / "c.db"), interval_prune=3600))
    with TestClient(app) as client:
        assert client.app.state.collector is not None
        assert client.get("/api/v1/health").status_code == 200


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


def test_item_finished_events_land_in_history_without_duplicates(conn, fake, collector):
    """A lane C upload finishing between polls appeared in NO view
    (2026-07-26): the server's ItemFinished events now feed transfer_history,
    idempotently across cycles and across a Syncthing restart (event IDs
    reset to 1)."""
    fake.state["events"] = [
        {"id": 1, "type": "ItemFinished", "time": "2026-07-26T08:30:00+00:00",
         "data": {"folder": "2025-ff4-nuclear", "item": "Audio/Music/track.mp3",
                  "action": "update", "type": "file", "error": None}},
        {"id": 2, "type": "ItemFinished", "time": "2026-07-26T08:30:01+00:00",
         "data": {"folder": "2025-ff4-nuclear", "item": "Audio/Music",
                  "action": "update", "type": "dir", "error": None}},   # dirs skipped
        {"id": 3, "type": "ItemFinished", "time": "2026-07-26T08:30:02+00:00",
         "data": {"folder": "unknown-folder", "item": "x.mp3",
                  "action": "update", "type": "file", "error": None}},  # unregistered
    ]
    collector.run_cycle(conn, ALL)

    import ccsync_dashboard.db as dbm
    rows = dbm.fetch_transfer_history(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["lane"] == "lane_c_syncthing" and row["direction"] == "up"
    assert row["name"].endswith("Audio/Music/track.mp3")
    assert row["editor_username"] == "jsmith"     # the folder's single sharing editor

    # second cycle: nothing new, no duplicates
    collector.run_cycle(conn, ALL)
    assert len(dbm.fetch_transfer_history(conn)) == 1

    # syncthing restart: IDs reset; a fresh event with a small id still lands
    fake.state["events"] = [
        {"id": 1, "type": "ItemFinished", "time": "2026-07-26T09:00:00+00:00",
         "data": {"folder": "2025-ff4-nuclear", "item": "Audio/Music/next.mp3",
                  "action": "update", "type": "file", "error": None}},
    ]
    collector.run_cycle(conn, ALL)
    names = [r["name"] for r in dbm.fetch_transfer_history(conn)]
    assert any(n.endswith("next.mp3") for n in names)
    assert len(names) == 2
