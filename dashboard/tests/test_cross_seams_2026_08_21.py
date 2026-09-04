"""The dashboard half of the seams the 2026-08-21 fix pass left open (CR-67).

Every one of these has its other half already in the tree: a `site_store`
reader nothing called, a `base_machine_cells` set nothing rendered, a
`db.base_machines` predicate one endpoint used and its fragment twin did not,
a `machine=` kwarg on `build_queue_view`, `secrets_boot.ensure_secrets` on one
entry point of two. This file is the wiring, not the mechanism.

Ids cited per test: dash-core-7 / dash-core-5 (CR-55, CR-57), dash-admin-2
(CR-57), dash-admin-3 (CR-58), dash-admin-8 (CR-49), release-pipeline-11
(CR-59), ops-efficiency-5 / ops-efficiency-6 (CR-62), ytdl-web-5 (CR-66).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import ai_providers, app as appmod, internal_sftp, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"


@pytest.fixture
def env(tmp_path):
    projects_dir = tmp_path / "tree" / "Projects"
    projects_dir.mkdir(parents=True)
    settings = Settings(
        db_path=str(tmp_path / "seams.db"),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        projects_dir=str(projects_dir),
        report_token=TOKEN,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn, settings, app
        conn.close()


def as_user(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# --------------------------------------------------------------- dash-core-7

def test_the_console_entry_point_bootstraps_the_secrets_first(monkeypatch, tmp_path):
    """`ccsync-dashboard` (pyproject's console script) used to build
    Settings.from_env() itself and skip secrets_boot entirely, so an appliance
    start with no DASH_SESSION_SECRET booted with an EMPTY one and login
    silently switched off."""
    order: list[str] = []

    def fake_ensure(*a, **kw):
        order.append("ensure_secrets")
        return {}

    def fake_from_env(*a, **kw):
        order.append("from_env")
        return Settings(db_path=str(tmp_path / "run.db"), session_secret=SECRET,
                        report_token=TOKEN)

    monkeypatch.setattr(appmod.secrets_boot, "ensure_secrets", fake_ensure)
    monkeypatch.setattr(appmod.Settings, "from_env", staticmethod(fake_from_env))
    monkeypatch.setattr(appmod, "create_app", lambda settings: "app")
    fake_uvicorn = type("U", (), {"run": staticmethod(lambda *a, **kw: order.append("serve"))})
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)

    appmod.run()
    assert order == ["ensure_secrets", "from_env", "serve"]


# --------------------------------------------------------------- dash-admin-2

def test_the_internal_sftp_token_is_read_from_the_file_secrets_boot_writes(tmp_path):
    """secrets_boot names every secret file after its ENV VAR, lowercased, so
    the sftp bearer lives at `ccsync_internal_token`. This module looked for
    `internal_token`, which no writer has ever produced: on the appliance the
    dashboard answered 503 and every AuthorizedKeysCommand call was refused."""
    settings = Settings(db_path=str(tmp_path / "d.db"), internal_token="")
    canonical = settings.secrets_path("ccsync_internal_token")
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("from-secrets-boot\n", encoding="utf-8")
    assert internal_sftp._configured_token(settings) == "from-secrets-boot"

    # ...and the old name still answers for a hand-provisioned deployment,
    # while the canonical one wins when both exist.
    settings.secrets_path("internal_token").write_text("legacy\n", encoding="utf-8")
    assert internal_sftp._configured_token(settings) == "from-secrets-boot"
    canonical.unlink()
    assert internal_sftp._configured_token(settings) == "legacy"


# --------------------------------------------------------------- dash-admin-3

def test_create_project_lays_down_the_manifest_template_not_the_env_default(env):
    """The preview was fixed on 2026-08-21 and the create was not, so on a
    DB-overridden site /project-setup showed the admin's folders and then made
    the vendor's."""
    client, conn, settings, app = env
    site_store.set_many(conn, {"template_folders": "Footage, Audio, Graphics"},
                        updated_by="test")
    conn.commit()
    as_user(client)

    r = client.post("/api/v1/projects",
                    json={"parent_rel": "", "name": "Mystery Doc",
                          "resolve_project": "Mystery Doc"})
    assert r.status_code == 200, r.text
    made = sorted(p.name for p in
                  (Path(settings.projects_dir) / "Mystery Doc").iterdir() if p.is_dir())
    assert made == ["Audio", "Footage", "Graphics"]
    assert "Interviewees" not in made          # the documentary-shop default


def test_the_collector_provisions_the_manifest_shared_asset_folders(tmp_path):
    """The collector kept reading provision.SHARED_ASSET_FOLDERS, the
    import-time env copy, so `Assets/SFX` added on Settings was advertised to
    every installer and never created or shared."""
    settings = Settings(db_path=str(tmp_path / "c.db"))
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    collector = Collector(settings, client=object())
    before = set(collector._shared_folder_ids)

    site_store.set_many(conn, {"shared_asset_folders": "Assets/Luts, Assets/SFX"},
                        updated_by="test")
    conn.commit()
    collector._refresh_shared_folders(conn)
    assert {fid for fid, _rel, _label in collector._shared_folders} == {
        "assets-luts", "assets-sfx"}
    assert "assets-sfx" in collector._shared_folder_ids
    assert before != collector._shared_folder_ids

    # An unreadable site_settings keeps the previous list: an empty set here
    # is the B16 shape (every editor unshared from the LUT library).
    class Boom:
        def execute(self, *a, **kw):
            raise RuntimeError("database is locked")

    collector._refresh_shared_folders(Boom())
    assert "assets-sfx" in collector._shared_folder_ids
    conn.close()


def test_the_asgi_title_comes_from_the_database(tmp_path):
    """CR-58's last brand surface: on an appliance compose sets no
    DASH_SITE_*, so the org name lived only in site_settings."""
    db_path = tmp_path / "title.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        report_token=TOKEN)
    with TestClient(create_app(settings)):
        pass
    conn = dbmod.connect(db_path)
    site_store.set_many(conn, {"org_name": "Northlight Pictures"}, updated_by="test")
    conn.commit()
    conn.close()
    assert create_app(settings).title == "Northlight Pictures - CC Sync Dashboard"


# --------------------------------------------------------------- dash-admin-8

def _two_machines(conn):
    """One person, one WIRED desktop and one remote laptop: the mixed account
    f27c181 made supported, and the shape base_only_editors cannot see."""
    now = dbmod.utcnow_iso()
    dbmod.record_known_editor(conn, "jsmith", source="admin", now=now)
    for machine, mode in (("WIRED-PC", "base"), ("LAPTOP", "editor")):
        dbmod.upsert_machine(conn, "jsmith", machine, now)
        dbmod.upsert_machine_state(conn, "jsmith", machine, None, now, mode=mode)
    dbmod.upsert_project(conn, "2026-ff5-animals", "2026/FF5/Animals", "/p", now)
    conn.commit()


def test_the_assignments_grid_greys_the_wired_column_not_the_account(env):
    client, conn, settings, app = env
    _two_machines(conn)
    as_user(client)

    page = client.get("/admin/assignments")
    assert page.status_code == 200
    # The wired computer's cell is disabled and says which computer it means;
    # the same person's laptop column is still clickable.
    wired_cell = [line for line in page.text.splitlines()
                  if "WIRED-PC is wired to the NAS" in line]
    assert wired_cell, page.text
    assert "LAPTOP is wired" not in page.text
    assert page.text.count("disabled") >= 1


def test_the_fragment_toggle_refuses_a_wired_machine_too(env):
    """CR-49: api_tick 409s a `?machine=` naming a wired computer; the htmx
    fragment endpoint took the same query and did not."""
    client, conn, settings, app = env
    _two_machines(conn)
    as_user(client)

    r = client.post("/partials/selection/jsmith/2026-ff5-animals/toggle?machine=WIRED-PC")
    assert r.status_code == 409
    assert "wired to the server" in r.json()["detail"]

    r = client.post("/partials/selection/jsmith/2026-ff5-animals/toggle?machine=NOPE")
    assert r.status_code == 404

    r = client.post("/partials/selection/jsmith/2026-ff5-animals/toggle?machine=LAPTOP")
    assert r.status_code == 200
    rows = {(s["editor_username"], s["machine"]) for s in conn.execute(
        "SELECT editor_username, machine FROM selections")}
    assert rows == {("jsmith", "LAPTOP")}


# ---------------------------------------------------------- release-pipeline-11

def test_the_missing_installer_404_is_written_for_a_customer(env):
    client, conn, settings, app = env
    as_user(client)
    r = client.get("/download/macos")
    assert r.status_code == 404
    body = r.text
    assert "build_editor_package.ps1" not in body
    assert "base rig" not in body
    assert "publish_latest.py --kind onboard --platform macos" in body
    assert "—" not in body                      # the owner's rule


# ------------------------------------------------------------ ops-efficiency-5

def test_the_completion_pass_uses_a_short_per_call_timeout(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"))
    collector = Collector(settings, client=SyncthingClient("http://x", "k", timeout=10.0))
    assert collector._completion_call_timeout() == 3.0
    # ...and never LONGER than a deliberately tight client.
    collector.client.timeout = 1.0
    assert collector._completion_call_timeout() == 1.0


def test_the_client_takes_a_per_call_timeout(monkeypatch):
    seen: list[float | None] = []

    class Session:
        def request(self, method, url, params=None, json=None, headers=None,
                    timeout=None):
            seen.append(timeout)
            return type("R", (), {"status_code": 200, "content": b"{}",
                                  "json": staticmethod(lambda: {})})()

    client = SyncthingClient("http://x", "k", timeout=10.0, session=Session())
    client.config()
    client.db_status("slug", timeout=2.5)
    client.completion("slug", "dev", timeout=2.5)
    assert seen == [10.0, 2.5, 2.5]


# ------------------------------------------------------------ ops-efficiency-6

class _FakeCollector:
    def __init__(self, died=False, stalled=0.0, restart_ok=True):
        self._died = died
        self._stalled = stalled
        self._restart_ok = restart_ok
        self.restarts = 0

    def thread_died(self):
        return self._died

    def seconds_since_heartbeat(self):
        return self._stalled

    def restart(self):
        self.restarts += 1
        if not self._restart_ok:
            return False
        self._died = False
        return True


def _watchdog(collector, **kw):
    exits: list[int] = []
    dog = appmod.CollectorWatchdog(
        collector, interval=kw.pop("interval", 0.01),
        wedged_after=kw.pop("wedged_after", 900.0),
        exit_fn=exits.append, **kw)
    return dog, exits


def test_the_watchdog_restarts_a_dead_collector_thread():
    collector = _FakeCollector(died=True)
    dog, exits = _watchdog(collector)
    assert dog.check() == "restarted"
    assert collector.restarts == 1
    assert exits == []
    assert dog.check() == "ok"


def test_the_watchdog_exits_75_when_the_restart_will_not_take():
    dog, exits = _watchdog(_FakeCollector(died=True, restart_ok=False))
    assert dog.check() == "exiting"
    assert exits == [75]           # deploy/run.sh re-execs on 75


def test_the_watchdog_gives_up_after_the_restart_limit():
    collector = _FakeCollector(died=True)
    collector.restart = lambda: True       # claims success, stays dead
    dog, exits = _watchdog(collector, restart_limit=2)
    assert [dog.check() for _ in range(3)] == ["restarted", "restarted", "exiting"]
    assert exits == [75]


def test_the_watchdog_exits_75_for_a_thread_wedged_inside_one_call():
    dog, exits = _watchdog(_FakeCollector(stalled=1200.0), wedged_after=900.0)
    assert dog.check() == "exiting"
    assert exits == [75]
    # A slow-but-moving cycle is not a wedge: that would be a restart loop on
    # the page whose failure mode is "nobody can tell whether footage syncs".
    dog, exits = _watchdog(_FakeCollector(stalled=300.0), wedged_after=900.0)
    assert dog.check() == "ok"
    assert exits == []


def test_a_collector_that_was_stopped_is_not_a_dead_one(tmp_path):
    collector = Collector(Settings(db_path=str(tmp_path / "s.db"), interval_prune=3600))
    assert collector.thread_died() is False           # never started
    collector.start()
    assert collector.thread_died() is False
    assert collector.seconds_since_heartbeat() < 60
    collector.stop()
    assert collector.thread_died() is False           # deliberate, not a fault
    assert collector.restart() is False


def test_health_ok_goes_false_when_the_collector_thread_is_gone(env):
    client, conn, settings, app = env
    as_user(client)
    assert client.get("/api/v1/health").json()["ok"] is True
    assert client.get("/api/v1/health").json()["collector_alive"] is True

    class Dead:
        def thread_died(self):
            return True

    app.state.collector = Dead()
    body = client.get("/api/v1/health").json()
    assert body["ok"] is False
    assert body["collector_alive"] is False
    # ...including for the unauthenticated container healthcheck, which reads
    # `ok` out of this body and nothing else.
    client.cookies.clear()
    assert client.get("/api/v1/health").json()["ok"] is False


def test_the_watchdog_thread_starts_and_stops_with_the_app(tmp_path):
    settings = Settings(db_path=str(tmp_path / "w.db"), session_secret=SECRET,
                        report_token=TOKEN, interval_prune=3600)
    app = create_app(settings)
    with TestClient(app):
        dog = app.state.collector_watchdog
        assert dog._thread is not None and dog._thread.is_alive()
    for _ in range(50):
        if not dog._thread.is_alive():
            break
        time.sleep(0.02)
    assert not dog._thread.is_alive()


def test_the_watchdog_can_be_switched_off():
    assert appmod._watchdog_intervals({"DASH_COLLECTOR_WATCHDOG_SECONDS": "0"})[0] == 0
    assert appmod._watchdog_intervals({})[0] == appmod.WATCHDOG_INTERVAL_SECONDS
    # An unparseable value is the default, not a crash at boot.
    assert appmod._watchdog_intervals(
        {"DASH_COLLECTOR_WEDGED_SECONDS": "soon"})[1] == appmod.WATCHDOG_WEDGED_SECONDS
    dog = appmod.CollectorWatchdog(_FakeCollector(), interval=0, wedged_after=1)
    dog.start()
    assert dog._thread is None
    dog.stop()


# --------------------------------------------------------------- dash-core-5

def test_a_companion_credential_reaches_the_fleet_halt_read(env):
    """CR-55 moved the ROUTE onto companion_token_ok; login_gate still 401'd
    the request before it ever got there."""
    client, conn, settings, app = env
    client.cookies.clear()
    assert client.get("/api/v1/fleet/halt").status_code == 401

    r = client.get("/api/v1/fleet/halt", headers={"X-CCSync-Token": TOKEN})
    assert r.status_code == 200
    assert r.json()["halt"]["active"] is False

    # SETTING it stays admin-only: the carve-out is GET, and the route's own
    # _require_admin is the second lock.
    r = client.post("/api/v1/fleet/halt", headers={"X-CCSync-Token": TOKEN},
                    json={"active": True, "reason": "no"})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------- ytdl-web-5

def test_a_pinned_provider_is_the_only_one_probed(env, monkeypatch):
    """Resolving per AI call probed every enabled CLI -- a real billed
    one-token call, up to 70 s inside a ytdl job -- before the resolver ever
    looked at the pin the admin had set."""
    client, conn, settings, app = env
    probed: list[str] = []

    def spy(conn_, name, force=False, settings=None):
        probed.append(name)
        return {"installed": False, "signed_in": False, "path": "", "version": "",
                "detail": "not installed"}

    monkeypatch.setattr(ai_providers, "probe_cli", spy)
    monkeypatch.setattr(ai_providers, "cli_enabled", lambda *a, **kw: True)
    monkeypatch.setattr(ai_providers, "read_key",
                        lambda settings_, name: (("key-x", "file")
                                                 if name == ai_providers.ANTHROPIC_API
                                                 else ("", "")))
    ai_providers.set_preference(conn, ai_providers.ANTHROPIC_API, updated_by="owen")
    conn.commit()

    choice = ai_providers.resolved(conn, settings)
    assert choice.name == ai_providers.ANTHROPIC_API and choice.pinned
    assert probed == []               # the pin is an API provider: no subprocess

    # With no pin the ordered probe is unchanged.
    probed.clear()
    ai_providers.set_preference(conn, ai_providers.AUTO, updated_by="owen")
    conn.commit()
    assert ai_providers.resolved(conn, settings).name == ai_providers.ANTHROPIC_API
    assert ai_providers.CLAUDE_CODE in probed


def test_a_pin_that_is_not_available_is_still_a_refusal(env, monkeypatch):
    client, conn, settings, app = env
    monkeypatch.setattr(ai_providers, "cli_enabled", lambda *a, **kw: False)
    monkeypatch.setattr(ai_providers, "read_key", lambda settings_, name: ("", ""))
    ai_providers.set_preference(conn, ai_providers.OPENAI_API, updated_by="owen")
    conn.commit()
    choice = ai_providers.resolved(conn, settings)
    assert choice.name == ""
    assert "pinned but not available" in choice.reason
