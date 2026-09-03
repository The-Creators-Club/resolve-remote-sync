"""The collector belt for dash-db-1 (bug-hunt-2026-09-03).

"A base rig can hold no tick" (CR-28) is enforced on every WRITE path, but a
plan reaches Syncthing through a READ - `fetch_machine_selections` - and
`_run_enforce` is what turns a wrong read into a real share with the machine
whose tree root IS the NAS share. The db half is fixed in db.py; this pins the
belt in the cycle itself, which also covers the person-level fallback.
"""

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


def _folder_devices(fake):
    folder = next(f for f in fake.state["folders"] if f["id"] == SLUG)
    return {d["deviceID"] for d in folder.get("devices", [])}


def _make_wired(conn, editor, machine, now):
    """A machine that reported itself as WIRED to the NAS (machine_state.mode,
    v22). Written directly: the tick routes 409 on this shape, which is the
    whole point - the row this cycle reads comes from somewhere else."""
    conn.execute(
        "INSERT INTO machine_state (editor_username, machine, reported_at, "
        "received_at, mode) VALUES (?, ?, ?, ?, 'base')",
        (editor, machine, now, now))


def test_enforce_shares_nothing_with_a_wired_machine(conn, fake, collector):
    collector.run_cycle(conn, ["config", "enforce"])   # seeds jsmith's bucket
    assert EDITOR_ID in _folder_devices(fake)
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "jsmith", "JS-DESKTOP", now,
                         syncthing_device_id=EDITOR_ID)
    _make_wired(conn, "jsmith", "JS-DESKTOP", now)
    # A per-machine row for the wired machine, written past the guarded write
    # paths exactly as the unassigned bucket's fan-out used to produce one.
    conn.execute(
        "INSERT OR REPLACE INTO selections (editor_username, project_slug, "
        "machine, position, created_at, created_by, sync_mode, changed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("jsmith", SLUG, "JS-DESKTOP", 1, now, "admin", dbmod.SYNC_MODE_FULL, now))
    conn.commit()

    collector.run_cycle(conn, ["enforce"])
    devices = _folder_devices(fake)
    assert EDITOR_ID not in devices
    assert SERVER_ID in devices            # the server is never dropped
    assert EDITOR2_ID in devices           # unmapped devices untouched (B16)


def test_enforce_shares_nothing_with_an_editor_whose_every_machine_is_wired(
        conn, fake, collector):
    """The person-level fallback is the second route in: a device the machine
    registry cannot place is resolved by its owner's name."""
    collector.run_cycle(conn, ["config", "enforce"])   # seeds jsmith's bucket
    assert EDITOR_ID in _folder_devices(fake)
    now = dbmod.utcnow_iso()
    _make_wired(conn, "jsmith", "JS-DESKTOP", now)     # no syncthing_device_id
    conn.commit()

    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID not in _folder_devices(fake)
