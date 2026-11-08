"""CR-383 (2026-11-08): clips only on one computer, in projects not open there.

"Animals - Pangolins and Bears" (library FF5) held 45 music clips on ruskin's
Desktop for at least nine days, and `out_of_tree` never fired because it
reads the OPEN project's scan. Companion 0.9.88's unopened-projects sweep
reports the flagged projects as `sync_guard.resolve_health.
unopened_out_of_tree`; these tests pin the server half: the model, the v61
columns, the LG-1 strip, the alert and the two sentences.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, api as api_mod, auth, health, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import telemetry_fields
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-11-08T12:00:00+00:00"
LATER = "2026-11-08T12:30:00+00:00"
PANGOLINS = "Animals - Pangolins and Bears"
WHO = "ruskin/DESKTOP-LQQ41TC"


def report_headers(editor="ruskin"):
    return {"X-CCSync-Token": "sekrit",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def payload(unopened=..., scan_at=NOW, project=None):
    health_section = {"out_of_tree": 0, "bad_prefix": 0, "missing": 0,
                      "last_scan_at": NOW}
    if unopened is not ...:
        health_section["unopened_out_of_tree"] = unopened
        health_section["unopened_scan_at"] = scan_at
    body = {
        "editor_name": "ruskin", "machine": "DESKTOP-LQQ41TC",
        "companion_version": "0.9.88", "reported_at": NOW,
        "lanes": [{"name": "lane_a_upload", "state": "idle", "queued": 0,
                   "transferring": 0, "last_error": None, "last_sync": None}],
        "sync_guard": {"resolve_health": health_section},
    }
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
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        conn.execute("DELETE FROM alert_log")
        conn.execute("DELETE FROM notices")
        conn.commit()
        try:
            yield client, conn, app.state.settings
        finally:
            conn.close()


def _stored(conn):
    return dbmod.fetch_machine_guards(conn)[("ruskin", "DESKTOP-LQQ41TC")] \
        if hasattr(dbmod, "fetch_machine_guards") else None


def _row(conn):
    return conn.execute(
        "SELECT resolve_unopened_out_of_tree, resolve_unopened_scan_at "
        "FROM machine_state WHERE editor_username='ruskin'").fetchone()


def _found(conn, settings, now=NOW):
    return [f for f in alerts.scan(conn, settings, now)
            if f["kind"] == "unopened_out_of_tree"]


# ---------------------------------------------------------------- the model

def test_the_model_declares_the_fields():
    parsed = api_mod.ResolveHealthIn.model_validate({
        "unopened_out_of_tree": [{"project": PANGOLINS, "count": 45}],
        "unopened_scan_at": NOW})
    assert parsed.unopened_out_of_tree[0].project == PANGOLINS
    assert parsed.unopened_out_of_tree[0].count == 45
    assert parsed.unopened_scan_at == NOW
    assert not parsed.model_extra
    # Absent is "has not looked", never [].
    assert api_mod.ResolveHealthIn.model_validate({}).unopened_out_of_tree is None


def test_an_overlong_list_is_truncated_not_rejected():
    parsed = api_mod.ResolveHealthIn.model_validate({
        "unopened_out_of_tree": [{"project": f"P{n}", "count": 1} for n in range(40)]})
    assert len(parsed.unopened_out_of_tree) == 20


def test_the_lg1_tables_carry_the_path_on_this_side():
    assert ("sync_guard.resolve_health.unopened_out_of_tree"
            in telemetry_fields.FIELDS["resolve_project"])


# ------------------------------------------------------------ v61 + storage

def test_v61_is_in_the_list_and_replays(tmp_path):
    assert dict(dbmod._MIGRATION_STEPS)[61] is dbmod.SCHEMA_V61
    old = dbmod.connect(tmp_path / "v60.db")
    dbmod.migrate(old, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 60])
    dbmod.migrate(old)
    dbmod.migrate(old)
    assert old.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION
    cols = {r[1] for r in old.execute("PRAGMA table_info(machine_state)")}
    assert {"resolve_unopened_out_of_tree", "resolve_unopened_scan_at"} <= cols


def test_a_report_stores_the_list_and_a_later_absence_clears_it(env):
    client, conn, _settings = env
    resp = client.post("/api/v1/report", headers=report_headers(),
                       json=payload([{"project": PANGOLINS, "count": 45}]))
    assert resp.status_code == 200, resp.text
    raw, at = _row(conn)
    assert dbmod._unopened_list(raw) == [{"project": PANGOLINS, "count": 45}]
    assert at == NOW

    # A sweep that found nothing is [] - looked, clean.
    client.post("/api/v1/report", headers=report_headers(), json=payload([]))
    assert dbmod._unopened_list(_row(conn)[0]) == []

    # And a companion that stops saying anything (older build, switched off)
    # clears it: the LATCH rule, never a COALESCE.
    client.post("/api/v1/report", headers=report_headers(), json=payload())
    assert tuple(_row(conn)) == (None, None)


def test_a_damaged_column_reads_as_cannot_tell():
    assert dbmod._unopened_list(None) is None
    assert dbmod._unopened_list("{not json") is None
    assert dbmod._unopened_list('{"a": 1}') is None
    assert dbmod._unopened_list('[{"project": "", "count": 3}, {"project": "X"}]') == [
        {"project": "X", "count": 0}]


def test_the_site_switch_strips_the_names_on_arrival(env):
    client, conn, _settings = env
    site_store.set_many(conn, {"telemetry.resolve_project": "0"}, "owen")
    conn.commit()
    client.post("/api/v1/report", headers=report_headers(),
                json=payload([{"project": PANGOLINS, "count": 45}]))
    raw, at = _row(conn)
    assert raw is None
    # The time names nothing and stays.
    assert at == NOW


def test_switching_the_names_off_deletes_what_was_held(env):
    client, conn, _settings = env
    client.post("/api/v1/report", headers=report_headers(),
                json=payload([{"project": PANGOLINS, "count": 45}]))
    assert _row(conn)[0] is not None
    dbmod._clear_categories(conn, "ruskin", "DESKTOP-LQQ41TC", {"resolve_project"})
    assert _row(conn)[0] is None


# ------------------------------------------------------------------ the alert

def test_the_kind_is_registered_and_grouped():
    by_name = {k.kind: k for k in alerts.ALERT_KINDS}
    kind = by_name["unopened_out_of_tree"]
    assert kind.severity == alerts.SEV_WARN and callable(kind.check)
    grouped = [k for _name, kinds in alerts.KIND_GROUPS for k in kinds]
    assert grouped.count("unopened_out_of_tree") == 1


def test_the_alert_names_the_project_and_keys_on_the_computer(env):
    client, conn, settings = env
    client.post("/api/v1/report", headers=report_headers(),
                json=payload([{"project": PANGOLINS, "count": 45},
                              {"project": "Elections", "count": 2}]))
    (finding,) = _found(conn, settings)
    assert finding["subject"] == WHO
    assert finding["title"] == (
        f"footage on one computer only in '{PANGOLINS}' and 1 other project")
    assert f"'{PANGOLINS}' (45)" in finding["diagnosis"]
    assert "47 clip(s)" in finding["diagnosis"]
    assert "FIX ALL" in finding["fix"]
    for text in (finding["title"], finding["diagnosis"], finding["fix"]):
        assert "—" not in text


def test_nothing_found_or_nothing_said_raises_nothing(env):
    client, conn, settings = env
    client.post("/api/v1/report", headers=report_headers(), json=payload([]))
    assert _found(conn, settings) == []
    client.post("/api/v1/report", headers=report_headers(), json=payload())
    assert _found(conn, settings) == []


def test_a_project_the_dashboard_cannot_name_still_alerts(env):
    """The companion's evidence (a clip under a project root in the tree) is
    stronger than any name match, and a project nobody opens is the one
    nobody mapped: filtering on `_synced_project` would silence CR-383."""
    client, conn, settings = env
    client.post("/api/v1/report", headers=report_headers(),
                json=payload([{"project": "Nothing Like Any Folder", "count": 3}]))
    (finding,) = _found(conn, settings)
    assert "slugs=-" in finding["detail"]


def test_a_withheld_category_closes_an_open_alert_without_a_mail(env):
    client, conn, settings = env
    client.post("/api/v1/report", headers=report_headers(),
                json=payload([{"project": PANGOLINS, "count": 45}]))
    alerts.deliver(conn, settings, _found(conn, settings), NOW)
    assert alerts._is_open(conn, "unopened_out_of_tree", WHO)
    site_store.set_many(conn, {"telemetry.resolve_project": "0"}, "owen")
    conn.commit()
    client.post("/api/v1/report", headers=report_headers(),
                json=payload([{"project": PANGOLINS, "count": 45}]))
    found = _found(conn, settings, LATER)
    assert [f.get("withdrawn") for f in found] == [True]


# ------------------------------------------------------- the two sentences

def test_the_health_notes_name_the_count():
    notes = health.detail_notes({"guard": {"resolve_unopened_out_of_tree": [
        {"project": PANGOLINS, "count": 45}]}})
    assert "1 project not open with clips only on this computer" in notes
    assert health.detail_notes({"guard": {"resolve_unopened_out_of_tree": None}}) == []


def test_the_fleet_why_sentence_mentions_it(env):
    client, conn, _settings = env
    client.post("/api/v1/report", headers=report_headers(),
                json=payload([{"project": PANGOLINS, "count": 45}]))
    view = api_mod.build_editors_view(conn, NOW)
    (entry,) = [e for e in view["editors"] if e.get("machine") == "DESKTOP-LQQ41TC"]
    assert entry["why"] is not None
    assert f"'{PANGOLINS}'" in entry["why"]["sentence"]
    assert entry["why"]["unopened_out_of_tree"] == 1
