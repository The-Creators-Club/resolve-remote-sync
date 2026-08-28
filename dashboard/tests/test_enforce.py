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


# -- per-machine plans (MULTI_MACHINE_PLAN.md WP3, 2026-08-18) --------------


def test_a_dashboard_ahead_of_its_fleet_shares_exactly_what_it_did_before(
        conn, fake, collector):
    """THE DEPLOY-ORDER PROPERTY. v24 moves the plan onto computers, but no
    companion has reported a Syncthing device id yet, so no device can be
    resolved to a machine. Every share must come out exactly as the
    person-level cycle produced it -- otherwise upgrading the dashboard
    unshares a working fleet, which is the B16 shape."""
    collector.run_cycle(conn, ["config", "enforce"])          # seeds jsmith
    assert folder_devices(fake) == {SERVER_ID, EDITOR_ID, EDITOR2_ID}

    dbmod.upsert_machine(conn, "jsmith", "JS-DESKTOP", dbmod.utcnow_iso())
    conn.commit()
    collector.run_cycle(conn, ["enforce"])

    assert folder_devices(fake) == {SERVER_ID, EDITOR_ID, EDITOR2_ID}


def test_once_a_machine_owns_the_device_the_share_follows_its_own_plan(
        conn, fake, collector):
    """...and once the companion HAS reported which device it is, a tick for
    the other computer stops reaching this one."""
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    # The laptop's device is APPROVED on the server (comp-lane-c-1,
    # 2026-08-21): a device the server does not have cannot be shared with,
    # Syncthing drops the entry from the PUT, and the cycle would re-issue it
    # for ever. This test is about plans, not approval -- see
    # test_a_device_the_server_has_not_approved_is_not_shared_with.
    laptop_device = "LAPTOPX-LAPTOPX"
    fake.state["devices"].append({"deviceID": laptop_device, "name": laptop_device})
    dbmod.upsert_machine(conn, "jsmith", "JS-DESKTOP", now, syncthing_device_id=EDITOR_ID)
    dbmod.upsert_machine(conn, "jsmith", "JS-LAPTOP", now, syncthing_device_id=laptop_device)
    # The seeded row is the unassigned bucket; give the LAPTOP a plan of its
    # own and the desktop keeps the bucket.
    dbmod.add_selection(conn, "jsmith", "2026-ff5-elections", "admin", now, machine="JS-LAPTOP")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID in folder_devices(fake)

    # Now the desktop gets an explicit plan that does NOT include this folder.
    # Its first own row COPIES what it was inheriting (dash-core-1), so the
    # folder leaves this machine's plan when it is UNTICKED for it, not as a
    # side effect of ticking something else.
    dbmod.add_selection(conn, "jsmith", "2026-ff5-elections", "admin", now, machine="JS-DESKTOP")
    assert dbmod.remove_selection(conn, "jsmith", SLUG, machine="JS-DESKTOP") is True
    conn.commit()
    collector.run_cycle(conn, ["enforce"])

    assert EDITOR_ID not in folder_devices(fake)
    assert SERVER_ID in folder_devices(fake)          # the server is never dropped
    assert EDITOR2_ID in folder_devices(fake)         # unmapped devices untouched (B16)


def test_a_device_the_server_has_not_approved_is_not_shared_with(conn, fake, collector):
    """comp-lane-c-1 / dash-admin-6, 2026-08-21.

    A companion reports its Syncthing device id as soon as it has one, which
    is typically BEFORE an admin approves the pending device. Syncthing drops
    a folder-device entry naming a device it does not have and still answers
    200, so the plan never converged: every 60s cycle re-PUT the folder and
    logged '+[<id>]' while no share was ever made."""
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "newbie", "NEW-LAPTOP", now,
                         syncthing_device_id="PENDING-PENDING")
    dbmod.record_known_editor(conn, "newbie", "admin", now)
    dbmod.add_selection(conn, "newbie", SLUG, "admin", now, machine="NEW-LAPTOP")
    conn.commit()
    fake.state.pop("put_folder_calls", None)

    collector.run_cycle(conn, ["enforce"])

    assert "PENDING-PENDING" not in folder_devices(fake)
    assert "put_folder_calls" not in fake.state      # nothing to do, so nothing written
    # ...and it stays that way, cycle after cycle
    collector.run_cycle(conn, ["enforce"])
    assert "put_folder_calls" not in fake.state


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


LAPTOP_ID = "OWENLAP-OWENLAP-OWENLAP-OWENLAP-OWENLAP-OWENLAP-OWENLAP-OWENLAP"


def _add_second_folder(fake, slug="2026-ff5-alpha"):
    fake.state["folders"].append({
        "id": slug, "label": "2026/FF5/Alpha",
        "path": "/data/Projects/2026/FF5/Alpha",
        "devices": [{"deviceID": SERVER_ID}],
        "type": "sendreceive", "ignorePerms": True,
    })
    return slug


def test_a_machine_named_device_is_not_unshared_from_everything(conn, fake, collector):
    """B16: `owen-laptop` is username-SHAPED, so resolve_editor_username read
    it as editor "owen-laptop" -- an account that does not exist and has no
    selections rows. The preserve rule only kept devices whose editor resolved
    to None, so a device with a real-but-empty editor was removed from every
    folder it was shared with, and the enforce brake counted DEVICES (one) so
    it never fired."""
    collector.run_cycle(conn, ["config", "enforce"])          # seed jsmith
    slug2 = _add_second_folder(fake)

    # The laptop is approved AFTER the seed and shared with both folders.
    fake.state["devices"].append({"deviceID": LAPTOP_ID, "name": "owen-laptop"})
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
        "owen-laptop", dbmod.known_editor_usernames(conn)) is None
    # with no account list at all, the old shape-only behaviour is kept
    assert dbmod.resolve_editor_username("owen-laptop") == "owen-laptop"


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


# -- borrowed folders (SHARED_FOLDERS_PLAN.md §4.1, WP2) --------------------


def add_link(conn, borrower, lender, sub_rel, lender_label, status="ok"):
    dbmod.replace_project_links(conn, borrower, [
        {"declared_path": f"Projects/{lender_label}/{sub_rel}",
         "lender_slug": lender, "sub_rel": sub_rel, "status": status,
         "detail": None}], dbmod.utcnow_iso())
    conn.commit()


def lender_folder(fake, slug="2026-ff5-lender"):
    fake.state["folders"].append({
        "id": slug, "label": "2026/FF5/Lender",
        "path": "/data/Projects/2026/FF5/Lender",
        "devices": [{"deviceID": SERVER_ID}],
        "type": "sendreceive", "ignorePerms": True,
    })


def test_borrowers_device_gets_the_lenders_folder(conn, fake, collector):
    """jsmith ticks only the BORROWER; an ok link makes the lender's folder
    follow, so lane C can pull the borrowed subtree (restricted client-side
    by .stignore, WP3). Unticking the borrower removes it again."""
    lender_folder(fake)
    collector.run_cycle(conn, ["config", "enforce"])   # seeds jsmith on SLUG
    devices = {d["deviceID"] for f in fake.state["folders"]
               if f["id"] == "2026-ff5-lender" for d in f["devices"]}
    assert devices == {SERVER_ID}                       # no link yet

    add_link(conn, SLUG, "2026-ff5-lender", "Interviewees/Aha Chu", "2026/FF5/Lender")
    collector.run_cycle(conn, ["enforce"])
    devices = {d["deviceID"] for f in fake.state["folders"]
               if f["id"] == "2026-ff5-lender" for d in f["devices"]}
    assert devices == {SERVER_ID, EDITOR_ID}

    # untick the borrower everywhere: the lender share follows it out (the
    # removal is under the same blast-radius brake as every other unshare)
    dbmod.remove_selection(conn, "jsmith", SLUG)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    devices = {d["deviceID"] for f in fake.state["folders"]
               if f["id"] == "2026-ff5-lender" for d in f["devices"]}
    assert devices == {SERVER_ID}


def test_broken_link_shares_nothing(conn, fake, collector):
    lender_folder(fake)
    collector.run_cycle(conn, ["config", "enforce"])
    add_link(conn, SLUG, "2026-ff5-lender", "Gone", "2026/FF5/Lender",
             status="missing")
    collector.run_cycle(conn, ["enforce"])
    devices = {d["deviceID"] for f in fake.state["folders"]
               if f["id"] == "2026-ff5-lender" for d in f["devices"]}
    assert devices == {SERVER_ID}


# -- the refusal is PERSISTED and the diff is readable (DASH-3 / DASH-14,
#    resilience sweep 2026-08-28). The brake used to fire into the container
#    log and nowhere else, while _timed recorded the cycle as ok: poll_runs,
#    /api/v1/health and every page said enforce was fine and every genuine
#    untick sat unapplied.

def _refuse_five_removals(conn, fake, collector):
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
        dbmod.remove_selection(conn, "jsmith", slug)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    return slugs


def test_a_refused_enforce_pass_is_persisted_and_noted(conn, fake, collector):
    slugs = _refuse_five_removals(conn, fake, collector)
    refusal = dbmod.collector_alarms(conn)["enforce_refusal"]
    assert refusal["count"] == 5 and refusal["limit"] == 3
    assert refusal["devices"] == [EDITOR_ID]
    assert sorted(refusal["folders"]) == sorted(slugs)
    assert {(p["folder"], p["device"]) for p in refusal["pairs"]} == \
        {(slug, EDITOR_ID) for slug in slugs}

    # ...and the cycle no longer reports a clean reconcile (DASH-14).
    run = conn.execute("SELECT ok, error FROM poll_runs WHERE kind='enforce' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    assert run["ok"] == 1 and "refused 5 share removal(s)" == run["error"]
    health = dbmod.collector_health(conn)
    enforce = next(k for k in health["kinds"] if k["kind"] == "enforce")
    assert enforce["status"] == "amber" and "refused" in enforce["note"]


def test_the_refusal_clears_when_the_next_pass_is_sane(conn, fake, collector):
    slugs = _refuse_five_removals(conn, fake, collector)
    assert dbmod.collector_alarms(conn)["enforce_refusal"] is not None
    now = dbmod.utcnow_iso()
    for slug in slugs[1:]:
        dbmod.add_selection(conn, "jsmith", slug, "admin", now)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])          # one removal, under the limit
    assert dbmod.collector_alarms(conn)["enforce_refusal"] is None
    assert dbmod.collector_health(conn)["kinds"][0]["kind"] is not None


def test_the_pending_enforce_diff_is_recorded_for_the_dry_run_view(conn, fake, collector):
    """The admin-visible +/- comes from the same desired/actual sets the cycle
    itself acts on, written once per cycle and never acted on."""
    slugs = _refuse_five_removals(conn, fake, collector)
    plan = dbmod.collector_alarms(conn)["enforce_plan"]
    assert plan["n_remove"] == 5 and plan["n_add"] == 0
    assert {f["folder"] for f in plan["folders"]} == set(slugs)
    assert all(f["remove"] == [EDITOR_ID] for f in plan["folders"])

    # A cycle with nothing to do records an EMPTY plan rather than leaving the
    # last one standing: "nothing pending" and "I have not looked" must not
    # render the same.
    now = dbmod.utcnow_iso()
    for slug in slugs:
        dbmod.add_selection(conn, "jsmith", slug, "admin", now)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    collector.run_cycle(conn, ["enforce"])
    assert dbmod.collector_alarms(conn)["enforce_plan"]["folders"] == []


def test_an_empty_my_id_is_noted_not_recorded_as_a_reconcile(conn, fake, collector):
    """Ten minutes of a restarting Syncthing used to read as ten successful
    enforce cycles."""
    collector.run_cycle(conn, ["config", "enforce"])
    fake.state["my_id"] = ""
    results = collector.run_cycle(conn, ["enforce"])
    assert results["enforce"] is True                  # still not a FAILURE
    run = conn.execute("SELECT ok, error FROM poll_runs WHERE kind='enforce' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    assert run["ok"] == 1 and run["error"] == "skipped: empty myID"
    health = dbmod.collector_health(conn)
    assert {k["kind"]: k["status"] for k in health["kinds"]}["enforce"] == "amber"


def test_a_first_config_cycle_with_no_my_id_is_noted(conn, fake, collector):
    """The config half of the same restart: with no last known server id
    there is nothing to fall back to, so the pass is skipped -- and said."""
    fake.state["my_id"] = ""
    assert collector.run_cycle(conn, ["config"])["config"] is True
    run = conn.execute("SELECT ok, error FROM poll_runs WHERE kind='config' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    assert run["ok"] == 1 and run["error"] == "skipped: empty myID"


def test_a_fresh_untick_keeps_its_share_for_one_cycle(conn, fake, collector):
    """DASH-8 (resilience sweep 2026-08-28): the undo window is free.

    An untick recorded in the audit ledger seconds ago leaves the share
    exactly as it is, so the fleet page's [ UNDO ] does not pay for an
    unshare followed by a re-share -- which restarts the folder on every
    device holding it. One cycle later the freeze has lifted and the removal
    happens.
    """
    collector.run_cycle(conn, ["config", "enforce"])          # seeds jsmith
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "jsmith", "JS-DESKTOP", now, syncthing_device_id=EDITOR_ID)
    dbmod.add_selection(conn, "jsmith", SLUG, "admin", now, machine="JS-DESKTOP")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID in folder_devices(fake)

    dbmod.remove_selection(conn, "jsmith", SLUG, machine="JS-DESKTOP")
    dbmod.remove_selection(conn, "jsmith", SLUG, machine=dbmod.ANY_MACHINE)
    dbmod.audit(conn, "owen", dbmod.AUDIT_UNTICK, SLUG, {
        "editor": "jsmith", "slug": SLUG, "machine": "JS-DESKTOP",
        "before": [{"machine": "JS-DESKTOP", "mode": "full"}], "after": [],
    })
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID in folder_devices(fake)                  # frozen, not unshared

    # The same cycle a minute later: the window has closed.
    collector.now_fn = lambda: dbmod._iso_minus(
        dbmod.utcnow_iso(), -(dbmod.PLAN_FREEZE_SECONDS + 5))
    collector.run_cycle(conn, ["enforce"])
    assert EDITOR_ID not in folder_devices(fake)


def test_a_fresh_tick_is_never_delayed_by_the_freeze(conn, fake, collector):
    """The freeze holds shares, it does not withhold them. Ticking used to
    wait out interval_enforce before anything started (fixed 2026-07-26 with
    the collector nudge) and this must not hand that back."""
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    fake.state["folders"].append({
        "id": "2026-ff5-fresh", "label": "2026/FF5/Fresh",
        "path": "/data/Projects/2026/FF5/Fresh",
        "devices": [{"deviceID": SERVER_ID}],
        "type": "sendreceive", "ignorePerms": True,
    })
    dbmod.upsert_machine(conn, "jsmith", "JS-DESKTOP", now, syncthing_device_id=EDITOR_ID)
    dbmod.add_selection(conn, "jsmith", "2026-ff5-fresh", "admin", now, machine="JS-DESKTOP")
    dbmod.audit(conn, "owen", dbmod.AUDIT_TICK, "2026-ff5-fresh", {
        "editor": "jsmith", "slug": "2026-ff5-fresh", "machine": "JS-DESKTOP",
        "before": [], "after": [{"machine": "JS-DESKTOP", "mode": "full"}],
    })
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    devices = {d["deviceID"] for f in fake.state["folders"]
               if f["id"] == "2026-ff5-fresh" for d in f["devices"]}
    assert EDITOR_ID in devices
