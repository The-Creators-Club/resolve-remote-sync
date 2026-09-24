"""CR-310 (2026-09-24): a fresh tick raised a severity-error
`plan_without_share` notice on the home page, every time.

The tick's nudge runs config (which snapshots each folder's devices), then
enforce (which makes the share), then the self-diagnosis pass -- against the
snapshot, which predates the share. The next config read cleared it up to
two minutes later, so the error was seen by exactly the admin who had just
ticked, telling them the tick they made was broken.
"""

from __future__ import annotations

from fake_syncthing import EDITOR_ID, SERVER_ID, FakeSyncthing

from ccsync_dashboard import db as dbmod
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

NOW = "2026-09-24T12:00:00+00:00"
SLUG = "2025-ff4-nuclear"


def _open(conn, kind="plan_without_share"):
    return [r["subject"] for r in conn.execute(
        "SELECT subject FROM notices WHERE kind=? AND cleared_at IS NULL", (kind,))]


def _collector(fake):
    settings = Settings(session_secret="test-secret", syncthing_url=fake.url,
                        syncthing_api_key="k")
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def test_the_share_a_tick_makes_is_seen_by_the_check_in_the_same_cycle(conn):
    fake = FakeSyncthing().start()
    try:
        c = _collector(fake)
        # A settled fleet: jsmith's computer is registered and the folder is
        # shared with nobody but the server.
        fake.state["folders"][0]["devices"] = [{"deviceID": SERVER_ID}]
        c.run_cycle(conn, ["config", "enforce"])
        dbmod.upsert_machine(conn, "jsmith", "EDIT-PC", NOW,
                             syncthing_device_id=EDITOR_ID)
        dbmod.record_known_editor(conn, "jsmith", "test", NOW)
        conn.commit()

        # The tick, then the nudge's kinds in their real order.
        assert dbmod.add_selection(conn, "jsmith", SLUG, "owen", NOW, machine="EDIT-PC")
        conn.commit()
        c.run_cycle(conn, ["config", "enforce"])

        shared = {d["deviceID"] for d in fake.state["folders"][0]["devices"]}
        assert EDITOR_ID in shared, "enforce did not make the share at all"
        assert _open(conn) == [], "a tick that worked was reported as not sharing"
    finally:
        fake.stop()


def test_a_tick_enforce_cannot_share_still_raises_the_notice(conn):
    """The fix must not blind the check: a machine whose device the server
    has never approved gets no share, and that IS the notice's case."""
    fake = FakeSyncthing().start()
    try:
        c = _collector(fake)
        fake.state["folders"][0]["devices"] = [{"deviceID": SERVER_ID}]
        c.run_cycle(conn, ["config", "enforce"])
        unapproved = "UNAPPRV-UNAPPRV-UNAPPRV-UNAPPRV-UNAPPRV-UNAPPRV-UNAPPRV-UNAPPRV"
        dbmod.upsert_machine(conn, "jsmith", "EDIT-PC", NOW,
                             syncthing_device_id=unapproved)
        dbmod.record_known_editor(conn, "jsmith", "test", NOW)
        dbmod.add_selection(conn, "jsmith", SLUG, "owen", NOW, machine="EDIT-PC")
        conn.commit()
        c.run_cycle(conn, ["config", "enforce"])

        assert _open(conn) == [f"jsmith/EDIT-PC -> {SLUG}"]
    finally:
        fake.stop()
