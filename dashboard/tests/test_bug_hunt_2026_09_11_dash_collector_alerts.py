"""bug hunt 2026-09-11, dash-collector-alerts + res-fleet (CR-241).

One test per finding, each written to fail at 40f931a. The theme of the
highs is the same sentence said three ways: SILENCE IS NOT GOOD NEWS. A
check that stops judging a subject, a cap that drops the overflow, a ledger
row that was generated and never sent and a schedule retired by a failed
send all used to render as "this is fine" somewhere a person reads.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, mount_status, notices, recovery
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-09-11T12:00:00+00:00"
LATER = "2026-09-11T12:05:00+00:00"


def report_headers(editor="jsmith", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def payload(guard=None, project=None):
    body = {
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.9.70",
        "reported_at": NOW,
        "lanes": [
            {"name": "lane_b_proxy_down", "state": "idle", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None},
        ],
    }
    if guard is not None:
        body["sync_guard"] = guard
    if project is not None:
        body["resolve_project"] = project
    return body


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        # The real collector thread races every direct scan/deliver call
        # below, exactly as test_alerts.py's fixture explains.
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        conn.execute("DELETE FROM alert_log")
        conn.execute("DELETE FROM notices")
        conn.execute("DELETE FROM poll_runs")
        conn.commit()
        try:
            yield client, conn, app.state.settings
        finally:
            conn.close()


def _smtp(conn):
    """A configured sink, so `deliver` takes the per-message path."""
    alerts.set_settings(conn, {
        "alerts_sink": "smtp", "alerts_smtp_host": "mail.example",
        "alerts_smtp_from": "a@example", "alerts_smtp_to": "b@example"}, "owen")
    conn.commit()


def _no_send(monkeypatch, outcome=None):
    """Never touch a network: `_transmit` is the one seam every send uses."""
    sent = []

    def fake(conn, settings, subject, text, label=""):
        sent.append((label, subject))
        return dict(outcome or {"ok": True, "sink": "smtp",
                                "sent_to": "b@example", "detail": "sent"})

    monkeypatch.setattr(alerts, "_transmit", fake)
    return sent


# ------------------------------------------ dash-collector-alerts-1 / res-fleet-3

OUT_OF_TREE_GUARD = {
    "resolve_health": {"out_of_tree": 40, "bad_prefix": 0, "missing": 0,
                       "last_scan_at": NOW},
}


def _only_out_of_tree(conn, settings, now):
    """One kind's findings. The other forty would each send a message of
    their own here and drown the assertion this test is about."""
    return [f for f in alerts.scan(conn, settings, now)
            if f["kind"] == "out_of_tree"]


def test_a_personal_project_does_not_clear_an_open_out_of_tree_alert(env, monkeypatch):
    """CR-232's silence must not be spelled as RECOVERED.

    Raised while the fleet project is open, then the editor opens their own
    wedding project for an hour: the 40 clips are untouched, so nothing has
    cleared and nobody may be told it has.
    """
    client, conn, settings = env
    _smtp(conn)
    sent = _no_send(monkeypatch)
    dbmod.upsert_project(conn, "2026-pangolins", "2026/Ruskin/Ruskin Pangolins",
                         "/mnt/tank/Projects/x", NOW)
    conn.commit()

    client.post("/api/v1/report", json=payload(OUT_OF_TREE_GUARD, "Ruskin Pangolins"),
                headers=report_headers())
    first = alerts.deliver(conn, settings, _only_out_of_tree(conn, settings, NOW), NOW)
    assert first["sent"] == 1
    assert alerts._is_open(conn, "out_of_tree", "jsmith/EDIT-PC")

    client.post("/api/v1/report",
                json=payload(OUT_OF_TREE_GUARD, "Wedding Video For Mum"),
                headers=report_headers())
    second = alerts.deliver(
        conn, settings, _only_out_of_tree(conn, settings, LATER), LATER)
    assert second["recovered"] == 0, "an unrelated project switch was mailed as cleared"
    assert alerts._is_open(conn, "out_of_tree", "jsmith/EDIT-PC"), \
        "the ledger row was closed by a check that stopped looking"
    assert not any("cleared" in subject for _label, subject in sent)


def test_a_personal_project_raises_nothing_when_nothing_was_ever_raised(env):
    """The other half of CR-232, which must stay true: a subject the ledger
    has never held is silent, not quiet."""
    client, conn, settings = env
    dbmod.upsert_project(conn, "2026-pangolins", "2026/Ruskin/Ruskin Pangolins",
                         "/mnt/tank/Projects/x", NOW)
    conn.commit()
    client.post("/api/v1/report",
                json=payload(OUT_OF_TREE_GUARD, "Wedding Video For Mum"),
                headers=report_headers())
    findings = alerts.scan(conn, settings, NOW)
    assert [f for f in findings if f["kind"] == "out_of_tree"] == []


# ----------------------------------------------- dash-collector-alerts-2

def test_a_weekly_that_was_never_sent_is_not_evidence_the_sink_works(env):
    """The one check whose whole job is proving the alarm reaches a person."""
    client, conn, settings = env
    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "", True,
                       "generated, not sent (no sink configured)", NOW)
    conn.commit()
    assert alerts.sink_deliverable(conn, LATER)[0] is False

    _smtp(conn)
    ok, why = alerts.sink_deliverable(conn, LATER)
    assert ok is False, why
    assert "ever been sent" in why

    # ...and a real delivery (any kind) still is evidence.
    dbmod.record_alert(conn, alerts.KIND_HEARTBEAT, "heartbeat", "b@example",
                       True, "sent", NOW)
    conn.commit()
    assert alerts.sink_deliverable(conn, LATER)[0] is True


# ----------------------------------------------- dash-collector-alerts-3

SIX_HOURS_EARLIER = "2026-09-11T06:00:00+00:00"


def test_a_collector_whose_last_cycle_failed_can_still_be_stale(env):
    client, conn, settings = env
    dbmod.record_poll_run(conn, "enforce", SIX_HOURS_EARLIER, SIX_HOURS_EARLIER,
                          False, "syncthing refused")
    conn.commit()
    kinds = {f["kind"] for f in alerts.scan(conn, settings, NOW)}
    assert "collector_stale" in kinds


def test_a_site_with_no_syncthing_is_not_a_site_whose_sync_engine_is_down(env):
    """A deployment with no `syncthing_url` runs the Syncthing-free kinds
    only, so `syncthing_reachable` is False there by configuration."""
    client, conn, settings = env
    assert not settings.syncthing_url
    kinds = {f["kind"] for f in alerts.scan(conn, settings, NOW)}
    assert "nas_engine_down" not in kinds


# ----------------------------------------------- dash-collector-alerts-4

def _silent(n, start=0):
    return [{"kind": "machine_silent", "severity": alerts.SEV_WARN,
             "title": "a computer has gone quiet", "subject": f"e{i}/PC",
             "diagnosis": "quiet", "fix": "ask", "detail": ""}
            for i in range(start, start + n)]


def test_a_truncated_kind_never_declares_anything_recovered(env, monkeypatch):
    client, conn, settings = env
    _smtp(conn)
    _no_send(monkeypatch)
    everyone = _silent(45)
    # Pass one carries the first 40, pass two a different 40: the five that
    # fell out of the window have NOT been fixed.
    alerts.deliver(conn, settings, everyone[:40] + [_truncation_marker()], NOW)
    result = alerts.deliver(conn, settings,
                            everyone[5:45] + [_truncation_marker()], LATER)
    assert result["recovered"] == 0


def _truncation_marker():
    return {"kind": "machine_silent", "severity": alerts.SEV_WARN,
            "title": "a computer has gone quiet",
            "subject": alerts.TRUNCATED_SUBJECT, "truncated": True,
            "diagnosis": "there are more", "fix": "look", "detail": ""}


def test_scan_says_so_when_a_kind_overflows(env, monkeypatch):
    client, conn, settings = env

    kind = next(k for k in alerts.ALERT_KINDS if k.kind == "machine_silent")
    monkeypatch.setattr(alerts, "ALERT_KINDS", [dataclasses.replace(
        kind,
        check=lambda ctx: [alerts._f(f"e{i}/PC", "quiet", "ask")
                           for i in range(45)])])
    findings = alerts.scan(conn, settings, NOW)
    mine = [f for f in findings if f["kind"] == "machine_silent"]
    assert len(mine) == alerts.MAX_FINDINGS_PER_KIND + 1
    over = [f for f in mine if f.get("truncated")]
    assert len(over) == 1
    assert over[0]["subject"] == alerts.TRUNCATED_SUBJECT
    assert "45" in over[0]["diagnosis"]


# ----------------------------------------------- dash-collector-alerts-5

def test_a_restore_refuses_a_tree_it_could_not_walk_to_the_end(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    snaps = tmp_path / "snapshots"
    for rel in ("2026/One/a.txt", "2026/One/b.txt"):
        p = projects / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("live", encoding="utf-8")
    for rel in ("a.txt", "b.txt", "c.txt"):
        p = snaps / "ccsync-20260911-1100" / "2026/One" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("snap", encoding="utf-8")
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token="tok", admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    dbmod.upsert_project(conn, "one", "2026/One", "/x", NOW)
    conn.commit()
    monkeypatch.setattr(recovery, "MAX_SCAN_FILES", 2)
    try:
        with pytest.raises(recovery.RecoveryError) as caught:
            recovery.restore_into_quarantine(
                settings, conn, "one", "ccsync-20260911-1100", "owen",
                env={recovery.ENV_SNAPSHOT_DIR: str(snaps)}, now=NOW,
                snapshot_before=lambda *_a: {"ok": False, "reason": "no NAS"})
        assert caught.value.status == 409
        assert "more than" in str(caught.value)
        # Refused means nothing was written: a half restore that looks
        # complete is the failure this is about.
        assert not list((projects / "2026" / "One").glob(
            f"{recovery.QUARANTINE_PREFIX}*"))
    finally:
        conn.close()


# ----------------------------------------------- dash-collector-alerts-6

def test_a_client_share_token_never_reaches_the_notices_table(tmp_path):
    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    token = "0123456789abcdef0123456789abcdef"
    try:
        notices.record_server_error(
            conn, f"/broll/share/{token}/clip/9", RuntimeError("boom"), now=NOW)
        rows = [dict(r) for r in conn.execute(
            "SELECT subject, body FROM notices WHERE kind='server_error'")]
        assert len(rows) == 1
        assert token not in rows[0]["subject"]
        assert token not in rows[0]["body"]
        assert rows[0]["subject"].startswith("/broll/share")

        # ...and a route with an id in it is ONE row, not one per id.
        for job in range(5):
            notices.record_server_error(
                conn, f"/api/v1/jobs/{job}/why", RuntimeError("boom"), now=NOW)
        n = conn.execute("SELECT COUNT(*) AS n FROM notices "
                         "WHERE kind='server_error'").fetchone()["n"]
        assert n == 2
        # A caller that HAS the matched route template gets it used verbatim.
        notices.record_server_error(conn, "/api/v1/jobs/7/why",
                                    RuntimeError("boom"), now=NOW,
                                    route="/api/v1/jobs/{job_id}/why")
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM notices WHERE subject LIKE ?",
            ("/api/v1/jobs/{job_id}/why%",)).fetchone()["n"] == 1
    finally:
        conn.close()


# ----------------------------------------------- dash-collector-alerts-7

def test_a_failed_weekly_is_still_found_under_a_wall_of_other_alerts(env):
    client, conn, settings = env
    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "", False,
                       "smtp refused", NOW)
    for i in range(250):
        dbmod.record_alert(conn, "machine_silent", f"e{i}/PC", "b@example",
                           True, "sent", NOW)
    conn.commit()
    kinds = {f["kind"] for f in alerts.scan(conn, settings, LATER)}
    assert "weekly_send_failed" in kinds


# ----------------------------------------------- dash-collector-alerts-8

def test_a_mount_that_recorded_no_verdict_does_not_clear_its_notice(tmp_path):
    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    mount_status.reset()
    try:
        mount_status.record("broll", "absent", "the vault root is not mounted")
        notices._check_feature_mounts(conn, None, NOW)
        conn.commit()
        assert _open_mount_notices(conn) == {"broll"}

        # A second boot path that never reached music's record() line. The
        # b-roll notice clears (it is mounted now); music's must NOT, because
        # nothing has said anything about it.
        mount_status.reset()
        mount_status.record("broll", "mounted", "serving /broll")
        notices._check_feature_mounts(conn, None, NOW)
        conn.commit()
        dbmod.notice(conn, "feature_not_mounted", "warn", "music",
                     body="the music page is not available", fix="check", now=NOW)
        conn.commit()
        notices._check_feature_mounts(conn, None, NOW)
        conn.commit()
        assert _open_mount_notices(conn) == {"music"}
    finally:
        mount_status.reset()
        conn.close()


def _open_mount_notices(conn) -> set[str]:
    return {str(r["subject"]) for r in conn.execute(
        "SELECT subject FROM notices WHERE kind='feature_not_mounted' "
        "AND cleared_at IS NULL")}


# ----------------------------------------------------------- res-fleet-2

def test_a_mount_whose_root_goes_away_stops_reading_as_mounted():
    mount_status.reset()
    try:
        mount_status.record("broll", "mounted", "serving /broll")
        mount_status.record_root("broll", "/vault/broll")
        assert mount_status.recheck(lambda _p: True) == {}
        assert mount_status.get("broll") == ("mounted", "serving /broll")

        changed = mount_status.recheck(lambda _p: False)
        assert set(changed) == {"broll"}
        status, detail = mount_status.get("broll")
        assert status == "degraded"
        assert "/vault/broll" in detail

        # ...and it comes back to exactly the verdict the boot recorded.
        mount_status.recheck(lambda _p: True)
        assert mount_status.get("broll") == ("mounted", "serving /broll")
    finally:
        mount_status.reset()


def test_a_mount_that_failed_at_boot_is_not_healed_by_its_folder_returning():
    """The sub-app was never mounted into this process, so "the directory is
    back" is not "the page works": only a restart is."""
    mount_status.reset()
    try:
        mount_status.record("music", "absent", "the music checkout did not import")
        mount_status.record_root("music", "/data/music")
        mount_status.recheck(lambda _p: True)
        assert mount_status.get("music")[0] == "absent"
    finally:
        mount_status.reset()


def test_a_root_that_cannot_be_probed_changes_nothing():
    mount_status.reset()

    def explode(_path):
        raise OSError("the mount is wedged")

    try:
        mount_status.record("cards", "mounted", "serving /vault")
        mount_status.record_root("cards", "/vault")
        assert mount_status.recheck(explode) == {}
        assert mount_status.get("cards")[0] == "mounted"
    finally:
        mount_status.reset()


# ----------------------------------------------------------- res-fleet-4

MONDAY_MORNING = "2026-09-07T09:00:00+00:00"
MONDAY_NOON = "2026-09-07T12:00:00+00:00"


def test_a_weekly_report_whose_send_failed_is_tried_again(env):
    client, conn, settings = env
    alerts.set_settings(conn, {"alerts_weekly": "1"}, "owen")
    conn.commit()
    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "", False,
                       "smtp refused", MONDAY_MORNING)
    conn.commit()
    assert alerts.weekly_due(conn, MONDAY_NOON) is True

    # ...but not for ever: the ceiling is what stops a dead sink costing an
    # SMTP timeout on every collector cycle until next Monday.
    for _ in range(alerts.MAX_SEND_ATTEMPTS_PER_SLOT):
        dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "", False,
                           "smtp refused", MONDAY_MORNING)
    conn.commit()
    assert alerts.weekly_due(conn, MONDAY_NOON) is False

    # A send that WORKED retires the slot, exactly as before.
    conn.execute("DELETE FROM alert_log")
    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "b@example", True,
                       "sent", MONDAY_MORNING)
    conn.commit()
    assert alerts.weekly_due(conn, MONDAY_NOON) is False


def test_a_heartbeat_whose_send_failed_is_tried_again(env):
    client, conn, settings = env
    _smtp(conn)
    alerts.set_settings(conn, {"alerts_heartbeat": "1"}, "owen")
    conn.commit()
    dbmod.record_alert(conn, alerts.KIND_HEARTBEAT, "heartbeat", "", False,
                       "smtp refused", MONDAY_MORNING)
    conn.commit()
    assert alerts.heartbeat_due(conn, MONDAY_NOON) is True
    dbmod.record_alert(conn, alerts.KIND_HEARTBEAT, "heartbeat", "b@example",
                       True, "sent", MONDAY_MORNING)
    conn.commit()
    assert alerts.heartbeat_due(conn, MONDAY_NOON) is False


# ------------------------- dash-collector-alerts-4, the invariants half

def test_a_truncated_invariant_verdict_keeps_its_notices_past_the_cap(
        tmp_path, monkeypatch):
    """`broken()` caps at MAX_SUBJECTS, and the survivors used to be the whole
    keep-list handed to `clear_notices_of_kind`: subject 21 onward had its
    `invariant_broken` notice CLOSED while the invariant was still broken on
    it."""
    from ccsync_dashboard import invariants

    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    n = invariants.MAX_SUBJECTS + 5
    every = [(f"subject-{i:02d}", "not shared") for i in range(n)]
    inv = invariants.Invariant("wide", 99, "everything is shared",
                               "nothing syncs", "share it",
                               lambda ctx: invariants.broken(every))
    monkeypatch.setattr(invariants, "INVARIANTS", (inv,))
    monkeypatch.setattr(invariants, "BY_KEY", {"wide": inv})
    settings = Settings(session_secret="test-secret")
    try:
        invariants.run_cycle(conn, settings, NOW)
        first = _open_invariant_subjects(conn)
        assert len(first) == invariants.MAX_SUBJECTS

        # The next pass keeps a DIFFERENT window of the same broken set. The
        # ones that fell out are not fixed, so their notice must not close.
        rotated = every[5:] + every[:5]
        monkeypatch.setattr(
            invariants, "INVARIANTS",
            (invariants.Invariant("wide", 99, "everything is shared",
                                  "nothing syncs", "share it",
                                  lambda ctx: invariants.broken(rotated)),))
        monkeypatch.setattr(invariants, "BY_KEY",
                            {"wide": invariants.INVARIANTS[0]})
        invariants.run_cycle(conn, settings, LATER)
        assert first <= _open_invariant_subjects(conn)
    finally:
        conn.close()


def _open_invariant_subjects(conn) -> set[str]:
    return {str(r["subject"]) for r in conn.execute(
        "SELECT subject FROM notices WHERE kind='invariant_broken' "
        "AND cleared_at IS NULL")}


# ----------------------------------------------------------- res-fleet-6

class _OneFolder:
    """The two reads `_enforce_loop` makes, with a device appearing between
    them: an admin approving and sharing by hand mid-cycle."""

    def __init__(self, devices):
        self.devices = list(devices)
        self.put = None

    def get_folder(self, slug):
        return {"id": slug, "devices": [{"deviceID": d, "introducedBy": ""}
                                        for d in self.devices]}

    def put_folder(self, slug, folder):
        self.put = [d["deviceID"] for d in folder["devices"]]


def test_a_device_that_appeared_after_the_snapshot_is_never_unshared_uncounted():
    from ccsync_dashboard.collector import Collector

    settings = Settings(session_secret="test-secret")
    client = _OneFolder(["SERVER", "PLANNED", "APPROVED-MID-CYCLE"])
    c = Collector(settings, client=client)
    # The plan was made from a snapshot that had two devices; the brake
    # counted its removals against THAT.
    plans = [("ff5", {"SERVER", "PLANNED"}, {"SERVER", "PLANNED"})]
    c._enforce_loop(plans, False)
    assert "APPROVED-MID-CYCLE" in (client.put or []), \
        "a share removed without ever being counted by the blast-radius brake"


# ----------------------------------------------------------- res-fleet-5

def test_a_person_level_share_of_an_unplaceable_device_is_said_out_loud(
        conn, caplog):
    """The fallback stays (unsharing a device the registry cannot place is
    the B16 shape), but it stops being SILENT: that computer's own tick mode
    and wired flag are decided per machine and cannot be read here, so a
    fleet sitting in this state is a configuration somebody has to look at.
    """
    import logging

    from fake_syncthing import EDITOR_ID, FakeSyncthing

    from ccsync_dashboard.collector import Collector
    from ccsync_dashboard.syncthing_client import SyncthingClient

    fake = FakeSyncthing().start()
    try:
        settings = Settings(session_secret="test-secret", syncthing_url=fake.url,
                            syncthing_api_key="k")
        c = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
        with caplog.at_level(logging.WARNING):
            # No machine row claims jsmith's device, so his tick reaches it
            # through the person-level fallback.
            c.run_cycle(conn, ["config", "enforce"])
            said = [r for r in caplog.records if "BY PERSON" in r.getMessage()]
            assert said, "the person-level fallback shared a device silently"
            assert EDITOR_ID in said[0].getMessage()
            # ...once per (editor, device) per process, on the rule the two
            # warnings beside it already follow.
            caplog.clear()
            c.run_cycle(conn, ["enforce"])
            assert not [r for r in caplog.records if "BY PERSON" in r.getMessage()]
    finally:
        fake.stop()


# ------------------------------------------ dash-db-1, the two readers of it

def test_a_wired_machines_stale_tick_is_not_a_permanent_error_notice(tmp_path):
    """A base rig holds no tick (CR-28) and syncs nothing, so a row left on
    one that flipped to wired in the tray is not "ticked but not shared": it
    is a row about a computer this server shares nothing with. It used to
    raise a severity-error notice whose own fix text ("untick and re-tick")
    409s on the re-tick half, so nothing an admin could do closed it.
    """
    from ccsync_dashboard import invariants

    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    try:
        dbmod.upsert_machine(conn, "alex", "BASE-RIG", NOW,
                             syncthing_device_id="BASEDEV-BASEDEV")
        dbmod.upsert_project(conn, "ff5", "2026/FF5", "/x", NOW)
        dbmod.add_selection(conn, "alex", "ff5", "owen", NOW, machine="BASE-RIG")
        dbmod.upsert_machine_state(conn, "alex", "BASE-RIG", None, NOW, mode="base")
        conn.commit()
        assert ("alex", "BASE-RIG") in dbmod.base_machines(conn)

        notices._check_plan_without_share(conn, NOW, {"ff5": []})
        conn.commit()
        assert [r for r in conn.execute(
            "SELECT subject FROM notices WHERE kind='plan_without_share' "
            "AND cleared_at IS NULL")] == []

        outcome = invariants.run_cycle(
            conn, Settings(session_secret="test-secret"), NOW,
            folder_devices={"ff5": []})
        verdict = next(r for r in outcome["results"] if r["key"] == "plan_has_share")
        assert verdict["state"] != dbmod.INVARIANT_BROKEN, verdict["detail"]
    finally:
        conn.close()
