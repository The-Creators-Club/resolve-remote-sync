"""Fix pass 2026-09-11b, territory dash-api (CR-255).

Each test fails at f1eeb42 and passes now. The interesting half of most of
them is what the existing suites are green over:

  wire-2      the repath ledger's own event 422'd the whole report.
  wire-3      the same section sends seven keys and declared four.
  dash-api-1  the rollback button walked past make_current_refusal.
  dash-api-2  five sync_guard sub-models still dropped undeclared keys.
  dash-api-4  a suspended editor's machine kept burning CPU on a job.
  dash-api-5  a machine with no platform was "unknown" here and "windows"
              in rollout_status, so the ship gate could never clear it.
  dash-api-6  resolve_health_detail carried undeclared keys out.
  dash-api-7  the rollback re-pointed current for machines it never named.
  security-1  the account bar is importable, and the package door asks.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api as api_mod
from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
NOW = "2026-09-11T09:00:00+00:00"

MEDIA_INPUTS = {"root": "media", "rel_path": "FF5/a.mp4",
                "out_root": "vault", "out_rel": "Vault/2026/FF5/cache"}


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects),
        report_token=TOKEN, packages_dir=str(tmp_path / "pkgs"),
        release_soak_minutes=600,
    )
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "pw"
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn, settings
        conn.close()


def admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def fleet_headers(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(client, version="0.9.66", editor="jsmith", machine="EDIT-PC", **extra):
    body = {"editor_name": editor, "machine": machine,
            "companion_version": version, "platform": "windows",
            "reported_at": dbmod.utcnow_iso(),
            "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
    body.update(extra)
    return client.post("/api/v1/report", json=body, headers=fleet_headers(editor))


# --------------------------------------------------------- the real producer

COMPANION_SYNC = (Path(__file__).resolve().parents[2]
                  / "companion" / "src" / "ccsync_companion" / "sync")


def _companion_repath():
    """The COMPANION's repath module, loaded from source.

    The dashboard venv does not carry the companion package, and the point of
    wire-2 is that a hand-written stand-in for the producer is what let the
    two halves disagree: `at` was pinned on the companion side with an ISO
    string the producer never writes. So the real file is loaded, with its one
    relative import stubbed - nothing in RepathLedger touches it.
    """
    if "_wire2_companion_sync" not in sys.modules:
        pkg = types.ModuleType("_wire2_companion_sync")
        pkg.__path__ = [str(COMPANION_SYNC)]
        sys.modules["_wire2_companion_sync"] = pkg
        admin_stub = types.ModuleType("_wire2_companion_sync.syncthing_admin")
        admin_stub.SyncthingAdmin = object
        sys.modules["_wire2_companion_sync.syncthing_admin"] = admin_stub
    name = "_wire2_companion_sync.repath"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, COMPANION_SYNC / "repath.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _real_event():
    repath = _companion_repath()
    ledger = repath.RepathLedger()
    return ledger.record("ff5", r"P:\Creators Club\old", r"P:\Creators Club\new",
                         "moved with the server", relinked=False, moved=True)


# ------------------------------------------------------------------- wire-2

def test_a_real_repath_event_does_not_422_the_whole_report(env):
    """wire-2: `at` is an epoch FLOAT on the producer."""
    client, _conn, _settings = env
    event = _real_event()
    assert isinstance(event["at"], float)
    resp = report(client, sync_guard={"repath_events": [event]})
    assert resp.status_code == 200, resp.text


def test_the_model_keeps_the_float_and_still_bounds_a_string(env):
    guard = api_mod.SyncGuardIn(repath_events=[_real_event()])
    assert isinstance(guard.repath_events[0].at, float)
    long = api_mod.RepathEventIn(at="2026-09-11T09:00:00+00:00" + "x" * 500)
    assert len(long.at) == 64


# ------------------------------------------------------------------- wire-3

def test_every_key_the_repath_ledger_writes_is_declared(env):
    """wire-3: four of the seven were undeclared, so the first rename of the
    week put four lines on the SYS-3 banner that mean nothing is wrong."""
    event = _real_event()
    guard = api_mod.SyncGuardIn(repath_events=[event])
    assert api_mod._nested_extra_keys("sync_guard.", guard) == []
    declared = set(api_mod.RepathEventIn.model_fields)
    assert set(event) <= declared, sorted(set(event) - declared)


def test_the_prune_guards_skipped_key_is_declared(env):
    """wire-3's second half: lane_guard.prune_trash sends `skipped`."""
    assert "skipped" in api_mod.TrashIn.model_fields
    guard = api_mod.SyncGuardIn(
        trash={"count": 2, "bytes": 9, "skipped": "breaker tripped"})
    assert api_mod._nested_extra_keys("sync_guard.", guard) == []
    assert guard.trash.skipped == "breaker tripped"


# --------------------------------------------------------------- dash-api-2

def test_every_sync_guard_subsection_truncates_rather_than_rejects(env):
    """dash-api-2: the five plain BaseModels drop an undeclared key in
    silence, which is the thing comp-app-2 was written to end."""
    for name, field in api_mod.SyncGuardIn.model_fields.items():
        for model in api_mod._section_models(field.annotation):
            assert issubclass(model, api_mod._BoundedSectionIn), \
                f"sync_guard.{name} is a {model.__name__}, which drops extras in silence"


def test_a_new_breaker_key_is_named_rather_than_dropped(env):
    guard = api_mod.SyncGuardIn(lane_b_breaker={"tripped": True, "persist_mode": "x"})
    assert api_mod._nested_extra_keys("sync_guard.", guard) == \
        ["sync_guard.lane_b_breaker.persist_mode"]


def test_a_long_breaker_reason_truncates_rather_than_422ing_the_report(env):
    client, _conn, _settings = env
    resp = report(client, sync_guard={
        "lane_b_breaker": {"tripped": True, "editor_reason": "x" * 4000}})
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------- dash-api-6

def test_resolve_health_detail_carries_only_declared_keys(env):
    guard = api_mod.SyncGuardIn(resolve_health={"brand_new_key": "x" * 5000})
    flat = api_mod.flatten_sync_guard(guard, NOW)
    assert "brand_new_key" not in flat["resolve_health_detail"]


# --------------------------------------------------------------- dash-api-5

def test_a_machine_with_no_platform_is_counted_the_way_rollout_status_counts_it(env):
    """dash-api-5: `unknown` here and `windows` in rollout_status is a
    straggler the ship gate can never clear."""
    client, conn, _settings = env
    report(client, platform=None)
    counted = api_mod._rollout_platforms_block(conn)
    status = dbmod.rollout_status(conn)
    assert "unknown" not in counted, counted
    assert counted.get("windows") == 1
    assert {c["platform"] for c in status["channels"]} <= set(counted) | {"windows"}


# ------------------------------------------------------- dash-api-1 / api-7

def _publish(conn, version, *, signature="", current=False, ever=False):
    dbmod.insert_companion_package(
        conn, version=version, platform="windows", filename=f"c{version}.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW,
        signature=signature, pubkey_id="k1" if signature else "")
    if current or ever:
        dbmod.set_current_package(conn, "windows", version, "companion")
    if ever and not current:
        dbmod.set_current_package(conn, "windows", "0.9.66", "companion")
    conn.commit()


def test_a_rollback_cannot_make_an_unsigned_build_current(env):
    """dash-api-1: the sixth door into "make current". An unsigned build made
    current stops EVERY companion updating, silently (UX-9)."""
    client, conn, _settings = env
    report(client, version="0.9.66")
    _publish(conn, "0.9.64")                       # never current, unsigned
    _publish(conn, "0.9.66", signature="sig", current=True)

    resp = admin(client).post(
        "/api/v1/admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The recall still reaches the machines: that is the half that matters.
    assert body["machines"] == ["jsmith/EDIT-PC"]
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.9.66"
    assert body["uncurrented"] == ""
    assert "signature" in (body.get("current_refused") or "")


def test_a_rollback_to_a_build_that_has_been_current_still_repoints(env):
    """dash-api-1 does not undo dash-api-3: `ever_current` is the evidence
    the soak gate asks for, and make_current_refusal says so itself."""
    client, conn, _settings = env
    report(client, version="0.9.66")
    _publish(conn, "0.9.64", signature="sig", current=True)
    _publish(conn, "0.9.66", signature="sig", current=True)

    resp = admin(client).post(
        "/api/v1/admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64")
    assert resp.status_code == 200, resp.text
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.9.64"
    assert resp.json()["uncurrented"] == "0.9.66"


def test_the_rollback_names_the_machines_it_would_downgrade(env):
    """dash-api-7: re-pointing `current` reaches every machine on the
    platform, and `_upgrade_info` offers a build that DIFFERS."""
    client, conn, _settings = env
    report(client, version="0.9.66")
    report(client, version="0.9.72", machine="BASE-RIG")
    _publish(conn, "0.9.64", signature="sig", current=True)
    _publish(conn, "0.9.66", signature="sig", current=True)

    resp = admin(client).post(
        "/api/v1/admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64")
    assert resp.status_code == 200, resp.text
    assert resp.json()["newer_machines"] == ["jsmith/BASE-RIG"]


# ------------------------------------------------------- dash-api-4 / wire-5

def test_a_suspended_editors_running_job_is_told_to_stop(env):
    """dash-api-4 / wire-5: 403 is "fix your credentials" to the runner, and
    only 410 stops the child. The machine ran the job to the end and the
    dashboard re-queued it for a second machine."""
    client, conn, _settings = env
    report(client)
    job_id = dbmod.create_job(conn, "peaks", dict(MEDIA_INPUTS), {})
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC", now=NOW)
    conn.commit()
    dbmod.suspend_editor(conn, "jsmith", by="owen", reason="contract ended")
    conn.commit()

    beat = client.post(f"/api/v1/jobs/{job_id}/heartbeat", headers=fleet_headers(),
                       json={"machine": "EDIT-PC"})
    assert beat.status_code == 410, beat.text


def test_a_suspended_editors_finished_job_can_still_be_retired(env):
    """The other half: a result RETIRES work already claimed. Refusing it
    throws away the forty minutes the machine has already spent and hands the
    same job to a second one."""
    client, conn, _settings = env
    report(client)
    job_id = dbmod.create_job(conn, "peaks", dict(MEDIA_INPUTS), {})
    dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC", now=NOW)
    conn.commit()
    dbmod.suspend_editor(conn, "jsmith", by="owen", reason="contract ended")
    conn.commit()

    done = client.post(f"/api/v1/jobs/{job_id}/result", headers=fleet_headers(),
                       json={"machine": "EDIT-PC", "ok": True, "result": {}})
    assert done.status_code == 200, done.text
    assert dbmod.get_job(conn, job_id)["state"] == dbmod.JOB_DONE


# -------------------------------------------------------------- security-1

def test_the_account_bar_is_importable_by_the_mounted_apps(env):
    """security-1: the mounts cannot reach `_refuse_barred_account`. One
    predicate, public, is what lets the word mean the same thing everywhere."""
    client, conn, settings = env
    report(client)
    assert api_mod.account_bar_reason(settings, conn, "jsmith") is None
    dbmod.suspend_editor(conn, "jsmith", by="owen", reason="contract ended")
    conn.commit()
    reason = api_mod.account_bar_reason(settings, conn, "jsmith")
    assert reason and "suspended" in reason.lower()


def test_a_suspended_editors_machine_cannot_keep_itself_upgraded(env):
    """security-1: the package door never asked."""
    client, conn, _settings = env
    report(client)
    token, _row = dbmod.create_editor_report_token(conn, "jsmith", "owen")
    conn.commit()
    headers = {"X-CCSync-Token": token}
    dbmod.suspend_editor(conn, "jsmith", by="owen", reason="contract ended")
    conn.commit()
    resp = client.get("/api/v1/companion/package/windows/current", headers=headers)
    assert resp.status_code == 403, resp.text


# =====================================================================
# Hand-off wave (HANDOFFS.md "## dash-api"). The OWED lines wave 1's other
# territories routed here.
# =====================================================================

import ast
import sqlite3

COMPANION_UPGRADE = (Path(__file__).resolve().parents[2]
                     / "companion" / "src" / "ccsync_companion" / "upgrade.py")


def _upgrade_report_keys() -> set[str]:
    """The keys `upgrade.upgrade_report` really returns, read from the
    COMPANION's source.

    Not a hand-written stand-in: wire-2's whole lesson was that a receiver
    test written against an imagined producer is how the two halves drift.
    The module itself cannot be imported into the dashboard venv (it pulls
    the companion's config, its tray and pywin32), so the return literal is
    parsed instead - which is still the producer's own text.
    """
    tree = ast.parse(COMPANION_UPGRADE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade_report":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                    keys = {k.value for k in inner.value.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                    if keys:
                        return keys
    raise AssertionError("upgrade_report's returned dict literal was not found")


def test_every_key_the_upgrade_report_writes_is_declared(env):
    """comp-ytdl-jobs (res-companion-4): `state_write_failures` is sent by
    every 0.9.72 companion on every report, so an undeclared field means the
    SYS-3 banner names a dropped key daily, for the whole fleet."""
    keys = _upgrade_report_keys()
    assert "state_write_failures" in keys, "the producer stopped sending it"
    declared = set(api_mod.UpgradeIn.model_fields)
    assert keys <= declared, sorted(keys - declared)


def test_the_upgrade_section_names_no_undeclared_key(env):
    """The same thing through the walker the banner actually reads."""
    guard = api_mod.SyncGuardIn(upgrade={"version": "0.9.72", "attempts": 0,
                                         "state_write_failures": 2})
    assert api_mod._nested_extra_keys("sync_guard.", guard) == []
    assert guard.upgrade.state_write_failures == 2


def test_a_suspended_editor_cannot_claim_new_work(env):
    """dash-api-4's third door: the claim stays 403 while the heartbeat is
    410. No new work under a barred name."""
    client, conn, _settings = env
    report(client)
    dbmod.create_job(conn, "peaks", dict(MEDIA_INPUTS), {})
    dbmod.suspend_editor(conn, "jsmith", by="owen", reason="contract ended")
    conn.commit()
    resp = client.post("/api/v1/jobs/claim", headers=fleet_headers(),
                       json={"machine": "EDIT-PC", "capabilities": {}})
    assert resp.status_code == 403, resp.text


def test_the_users_page_survives_a_locked_suspension_read(env, monkeypatch):
    """dash-db-5: CR-240 made these three readers re-raise `database is
    locked`, which is right where the empty answer was a fail-open and a 500
    on the page carrying [ RESUME ] and the key approvals."""
    client, conn, settings = env
    report(client)

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(api_mod.db, "suspended_editors", locked)
    monkeypatch.setattr(api_mod.db, "fetch_pending_ssh_keys", locked)
    view = api_mod._build_admin_users_view(settings, conn)
    assert view["suspensions_unreadable"] is True
    assert view["pending_ssh_keys_unreadable"] is True
    assert view["suspended"] == [] and view["pending_ssh_keys"] == []
    # And the page itself still answers.
    admin(client)
    assert client.get("/api/v1/admin/users").status_code == 200
