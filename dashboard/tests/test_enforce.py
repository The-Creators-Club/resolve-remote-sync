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


def test_seed_flag_not_set_when_no_editor_devices_are_visible(conn, fake, collector):
    """First container start racing Syncthing's own startup: /rest/config
    answers 200 with the device list not yet loaded. Flagging THAT as
    'seeded' made the next enforce pass read an empty selections table as
    authoritative and unshare every editor from every folder, fleet-wide,
    with nobody told (see the seed-flag finding)."""
    fake.state["devices"] = [{"deviceID": SERVER_ID, "name": "server"}]
    fake.state["folders"][0]["devices"] = [{"deviceID": SERVER_ID}]
    collector.run_cycle(conn, ["config", "enforce"])
    assert dbmod.meta_get(conn, "selections_seeded") is None      # retried next cycle

    # Devices show up (approved an hour later): NOW the seed runs for real.
    fake.state["devices"] = [
        {"deviceID": SERVER_ID, "name": "server"},
        {"deviceID": EDITOR_ID, "name": "jsmith"},
    ]
    fake.state["folders"][0]["devices"] = [{"deviceID": SERVER_ID}, {"deviceID": EDITOR_ID}]
    collector.run_cycle(conn, ["config", "enforce"])
    assert dbmod.meta_get(conn, "selections_seeded") is not None
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == [SLUG]
    assert folder_devices(fake) == {SERVER_ID, EDITOR_ID}         # nobody unshared


def test_seed_flag_not_set_when_there_are_no_folders(conn, fake, collector):
    fake.state["folders"] = []
    collector.run_cycle(conn, ["config", "enforce"])
    assert dbmod.meta_get(conn, "selections_seeded") is None


def test_enforce_refuses_a_mass_unshare(conn, fake, collector):
    """A pass that would unshare more devices than the configured limit is
    the signature of a bad snapshot, never a normal outcome. Removals are
    skipped (and logged as an ERROR); additions still apply."""
    editors = {"jsmith": EDITOR_ID}
    for i in range(4):
        device_id = f"EXTRA{i:02}-EXTRA{i:02}-EXTRA{i:02}-EXTRA{i:02}-" \
                    f"EXTRA{i:02}-EXTRA{i:02}-EXTRA{i:02}-EXTRA{i:02}"
        name = f"extra{i}"
        editors[name] = device_id
        fake.state["devices"].append({"deviceID": device_id, "name": name})
        fake.state["folders"][0]["devices"].append({"deviceID": device_id})
    collector.run_cycle(conn, ["config", "enforce"])          # seeds all five
    assert folder_devices(fake) >= set(editors.values())

    # Everyone unticks at once (or the selections table is lost).
    for name in editors:
        dbmod.remove_selection(conn, name, SLUG)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert folder_devices(fake) >= set(editors.values())       # nothing removed

    # Raising the limit is the deliberate override.
    collector.settings = Settings(
        **{**collector.settings.__dict__, "enforce_max_share_removals": 99}
    )
    collector.run_cycle(conn, ["enforce"])
    assert folder_devices(fake) == {SERVER_ID, EDITOR2_ID}     # server + unmapped only


def test_enforce_below_the_limit_still_removes(conn, fake, collector):
    collector.run_cycle(conn, ["config", "enforce"])
    dbmod.remove_selection(conn, "jsmith", SLUG)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert folder_devices(fake) == {SERVER_ID, EDITOR2_ID}


def test_enforce_skipped_when_syncthing_reports_no_my_id(conn, fake, collector):
    """An empty myID makes `desired` omit the server device from every
    folder: a put_folder on EVERY folder every cycle (each restarting the
    folder in Syncthing), with the NAS itself showing up as an editor."""
    collector.run_cycle(conn, ["config", "enforce"])
    fake.state.pop("put_folder_calls", None)
    fake.state["my_id"] = ""
    collector.run_cycle(conn, ["config", "enforce"])
    assert "put_folder_calls" not in fake.state
    assert folder_devices(fake) == {SERVER_ID, EDITOR_ID, EDITOR2_ID}
    # ...and the NAS was not re-classified as an editor device
    row = conn.execute("SELECT is_server FROM devices WHERE device_id=?", (SERVER_ID,)).fetchone()
    assert row["is_server"] == 1


# -- B16: a machine-style device name must not be read as an editor ---------


LAPTOP_ID = "ALEXLAP-ALEXLAP-ALEXLAP-ALEXLAP-ALEXLAP-ALEXLAP-ALEXLAP-ALEXLAP"


def _add_second_folder(fake, slug="2026-ff5-alpha"):
    fake.state["folders"].append({
        "id": slug, "label": "2026/FF5/Alpha",
        "path": "/data/Projects/2026/FF5/Alpha",
        "devices": [{"deviceID": SERVER_ID}],
        "type": "sendreceive", "ignorePerms": True,
    })
    return slug


def test_a_machine_named_device_is_not_unshared_from_everything(conn, fake, collector):
    """B16: `alex-laptop` is username-SHAPED, so resolve_editor_username read
    it as editor "alex-laptop" -- an account that does not exist and has no
    selections rows. The preserve rule only kept devices whose editor resolved
    to None, so a device with a real-but-empty editor was removed from every
    folder it was shared with, and the enforce brake counted DEVICES (one) so
    it never fired."""
    collector.run_cycle(conn, ["config", "enforce"])          # seed jsmith
    slug2 = _add_second_folder(fake)

    # The laptop is approved AFTER the seed and shared with both folders.
    fake.state["devices"].append({"deviceID": LAPTOP_ID, "name": "alex-laptop"})
    for folder in fake.state["folders"]:
        folder["devices"].append({"deviceID": LAPTOP_ID})

    collector.run_cycle(conn, ["config", "enforce"])
    assert LAPTOP_ID in folder_devices(fake)
    assert LAPTOP_ID in {d["deviceID"] for f in fake.state["folders"]
                         if f["id"] == slug2 for d in f["devices"]}
    # ...and it was NOT recorded as an editor account
    row = conn.execute("SELECT editor_username FROM devices WHERE device_id=?",
                       (LAPTOP_ID,)).fetchone()
    assert row["editor_username"] is None


def test_a_device_named_after_a_real_editor_is_still_managed(conn, fake, collector):
    """The fix must not turn every device unmapped: an account the dashboard
    has a record of still drives shares from its ticks."""
    collector.run_cycle(conn, ["config", "enforce"])
    assert folder_devices(fake) == {SERVER_ID, EDITOR_ID, EDITOR2_ID}
    dbmod.remove_selection(conn, "jsmith", SLUG)
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    assert folder_devices(fake) == {SERVER_ID, EDITOR2_ID}    # jsmith unshared


def test_a_reporting_editor_counts_as_known_even_with_no_selections(conn, fake, collector):
    """An editor whose companion reports is a real account -- machine_state's
    editor_username comes from a signed identity token, never from a Syncthing
    device label."""
    dbmod.upsert_machine_state(conn, "rsmith", "RS-PC", None, dbmod.utcnow_iso(),
                               verified=True)
    conn.commit()
    assert "rsmith" in dbmod.known_editor_usernames(conn)
    assert dbmod.resolve_editor_username(
        "rsmith", dbmod.known_editor_usernames(conn)) == "rsmith"
    assert dbmod.resolve_editor_username(
        "alex-laptop", dbmod.known_editor_usernames(conn)) is None
    # with no account list at all, the old shape-only behaviour is kept
    assert dbmod.resolve_editor_username("alex-laptop") == "alex-laptop"


def test_known_editor_records_outlive_the_evidence(conn):
    """An editor who unticks every project is still an editor: enforce must
    still be willing to unshare their devices."""
    now = dbmod.utcnow_iso()
    dbmod.add_selection(conn, "jsmith", SLUG, "admin", now)
    conn.commit()
    assert "jsmith" in dbmod.known_editor_usernames(conn)
    dbmod.record_known_editor(conn, "jsmith", "seed", now)
    dbmod.remove_selection(conn, "jsmith", SLUG)
    conn.commit()
    assert "jsmith" in dbmod.known_editor_usernames(conn)


def test_the_brake_counts_share_removals_not_devices(conn, fake, collector):
    """The brake capped DEVICES, so one device being unshared from all 40
    folders scored 1 and sailed under the limit -- exactly the B16 shape it
    was meant to catch. DASH_ENFORCE_MAX_REMOVALS is named after share
    removals and now counts them."""
    collector.settings = Settings(
        **{**collector.settings.__dict__, "enforce_max_share_removals": 3})
    slugs = [SLUG] + [_add_second_folder(fake, f"2026-ff5-p{i}") for i in range(4)]
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    for slug in slugs:
        dbmod.add_selection(conn, "jsmith", slug, "admin", now)
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    for slug in slugs:
        devices = {d["deviceID"] for f in fake.state["folders"]
                   if f["id"] == slug for d in f["devices"]}
        assert EDITOR_ID in devices

    # One device, five folders: 5 share removals > the limit of 3 -> refused.
    for slug in slugs:
        dbmod.remove_selection(conn, "jsmith", slug)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    still_shared = [
        slug for slug in slugs
        if EDITOR_ID in {d["deviceID"] for f in fake.state["folders"]
                         if f["id"] == slug for d in f["devices"]}
    ]
    assert still_shared == slugs        # nothing was unshared
