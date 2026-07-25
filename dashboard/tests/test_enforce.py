from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR2_ID, EDITOR_ID, SERVER_ID, FakeSyncthing

SLUG = "2025-ff4-nuclear"


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


@pytest.fixture
def collector(fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k")
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def folder_devices(fake):
    folder = next(f for f in fake.state["folders"] if f["id"] == SLUG)
    return {d["deviceID"] for d in folder.get("devices", [])}


def test_seed_once_from_existing_shares(conn, fake, collector):
    collector.run_cycle(conn, ["config", "enforce"])
    # jsmith (mapped) seeded; EDITOR2 (unmapped name) contributes nothing
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == [SLUG]
    assert dbmod.meta_get(conn, "selections_seeded") is not None
    all_sels = dbmod.fetch_all_selections(conn)
    assert all_sels == {SLUG: ["jsmith"]}
    # seeding does not repeat (untick survives the next cycle)
    dbmod.remove_selection(conn, "jsmith", SLUG)
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    assert dbmod.fetch_selections(conn, "jsmith") == []


def test_untick_removes_device_but_preserves_unmapped_and_config(conn, fake, collector):
    collector.run_cycle(conn, ["config", "enforce"])  # seeds jsmith
    assert folder_devices(fake) == {SERVER_ID, EDITOR_ID, EDITOR2_ID}

    dbmod.remove_selection(conn, "jsmith", SLUG)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    # jsmith's device removed; server + unmapped device untouched
    assert folder_devices(fake) == {SERVER_ID, EDITOR2_ID}
    # non-device folder config preserved verbatim on the PUT
    put = fake.state["put_folder_calls"][-1]
    assert put["label"] == "2025/FF4/Nuclear"
    assert put["path"] == "/data/Projects/2025/FF4/Nuclear"

    # re-tick restores the share
    dbmod.add_selection(conn, "jsmith", SLUG, "jsmith", dbmod.utcnow_iso())
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert folder_devices(fake) == {SERVER_ID, EDITOR_ID, EDITOR2_ID}


def test_tick_shares_unshared_folder(conn, fake, collector):
    # a freshly-provisioned folder has no editor devices
    fake.state["folders"].append({
        "id": "2026-ff5-energy-transition", "label": "2026/FF5/Energy Transition",
        "path": "/data/Projects/2026/FF5/Energy Transition",
        "devices": [{"deviceID": SERVER_ID}],
        "type": "sendreceive", "ignorePerms": True,
    })
    collector.run_cycle(conn, ["config", "enforce"])
    devices = {d["deviceID"] for f in fake.state["folders"]
               if f["id"] == "2026-ff5-energy-transition" for d in f["devices"]}
    assert devices == {SERVER_ID}  # nobody ticked it

    dbmod.add_selection(conn, "jsmith", "2026-ff5-energy-transition", "jsmith", dbmod.utcnow_iso())
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    devices = {d["deviceID"] for f in fake.state["folders"]
               if f["id"] == "2026-ff5-energy-transition" for d in f["devices"]}
    assert devices == {SERVER_ID, EDITOR_ID}


def test_enforce_noop_makes_no_puts(conn, fake, collector):
    collector.run_cycle(conn, ["config", "enforce"])
    fake.state.pop("put_folder_calls", None)
    collector.run_cycle(conn, ["enforce"])  # steady state
    assert "put_folder_calls" not in fake.state
