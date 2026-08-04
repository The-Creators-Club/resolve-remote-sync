"""The fleet-wide shared asset folders (the LUT library) on the server side.

A shared asset folder is a Syncthing folder that is deliberately NOT a
project: no marker, no tick, no row in the projects table. Three things have
to hold, and each of them is a place where the existing project machinery
would otherwise do the wrong thing to it:

  * enforce must share it with EVERY editor -- reading `selections` for it
    would find no rows and unshare it from the whole fleet;
  * the .stignore repair must use the ASSET list, or the collector and the
    companion rewrite the file at each other forever;
  * it must never reach the projects table, or it shows up as a tickable
    project in the dashboard UI.
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR_ID, SERVER_ID, FakeSyncthing

LUTS = provision.LUTS_FOLDER_ID


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


@pytest.fixture
def collector(fake, tmp_path):
    settings = Settings(
        syncthing_url=fake.url, syncthing_api_key="k",
        projects_dir=str(tmp_path), syncthing_data_prefix="/data/Projects",
        syncthing_assets_prefix="/data/Assets",
    )
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def folder(fake, folder_id):
    return next((f for f in fake.state["folders"] if f["id"] == folder_id), None)


def test_provisions_the_lut_library_beside_projects(conn, fake, collector):
    collector.run_cycle(conn, ["provision"])
    created = folder(fake, LUTS)
    assert created is not None
    # Beside Projects/, not inside it -- this is what makes it
    # P:\Assets\Luts on an editor's machine.
    assert created["path"] == "/data/Assets/Luts"
    assert created["type"] == "sendreceive"
    assert created["versioning"]["type"] == "staggered"
    # Created unshared; enforce is what shares it.
    assert created["devices"] == []


def test_gets_the_asset_stignore_not_the_project_one(conn, fake, collector):
    collector.run_cycle(conn, ["provision"])
    ignores = fake.state["ignores"][LUTS]
    assert ignores == provision.build_asset_stignore_lines()
    # The project list's Proxy patterns are meaningless here and must not
    # appear -- their presence would mean the wrong builder was used.
    assert "(?i)**/Proxy/**" not in ignores
    # OS junk is filtered, or every editor conflict-copies .DS_Store files.
    assert "(?i)**/.DS_Store" in ignores


def test_provisioning_is_idempotent(conn, fake, collector):
    collector.run_cycle(conn, ["provision"])
    before = len(fake.state["folders"])
    collector.run_cycle(conn, ["provision"])
    assert len(fake.state["folders"]) == before


def test_enforce_shares_it_with_every_editor_without_a_tick(conn, fake, collector):
    """The whole point: nobody ticks the LUT library."""
    collector.run_cycle(conn, ["provision", "config", "enforce"])
    devices = {d["deviceID"] for d in folder(fake, LUTS).get("devices", [])}
    assert SERVER_ID in devices
    assert EDITOR_ID in devices
    # And there is no selection row backing that share.
    assert LUTS not in dbmod.fetch_all_selections(conn)


def test_it_never_becomes_a_project(conn, fake, collector):
    """A row here would put a non-project into the dashboard's project list
    and into every editor's tick UI."""
    collector.run_cycle(conn, ["provision", "config", "enforce"])
    assert LUTS not in {p["slug"] for p in dbmod.fetch_projects(conn)}
    assert dbmod.fetch_project(conn, LUTS) is None


def test_the_seed_pass_does_not_tick_it_for_anyone(conn, fake, collector):
    """The one-shot seed turns existing shares into selections. Doing that
    for a shared library would hand a non-project slug to every editor's
    sequencer as a project to sync."""
    collector.run_cycle(conn, ["provision", "config", "enforce"])
    # It IS shared with an editor now, which is exactly the state the seed
    # pass turns into selections -- run the cycle again to be sure.
    collector.run_cycle(conn, ["config", "enforce"])
    for editor_selections in dbmod.fetch_all_selections(conn).values():
        assert LUTS not in editor_selections


def test_a_hand_moved_folder_is_reported_not_retargeted(conn, fake, collector, caplog):
    """Repointing a live folder makes Syncthing call every file at the old
    path deleted and propagate that to the fleet. A project move has a
    marker to prove intent; this has nothing, so it refuses."""
    collector.run_cycle(conn, ["provision"])
    target = folder(fake, LUTS)
    target["path"] = "/data/Assets/SomewhereElse"

    with caplog.at_level("ERROR"):
        collector.run_cycle(conn, ["provision"])

    assert folder(fake, LUTS)["path"] == "/data/Assets/SomewhereElse"
    assert any("leaving it alone" in r.message for r in caplog.records)


def test_a_blank_assets_prefix_disables_it(conn, fake, tmp_path):
    settings = Settings(
        syncthing_url=fake.url, syncthing_api_key="k",
        projects_dir=str(tmp_path), syncthing_assets_prefix="",
    )
    collector = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
    collector.run_cycle(conn, ["provision"])
    assert folder(fake, LUTS) is None
