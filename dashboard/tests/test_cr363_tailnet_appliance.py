"""CR-363 (prelaunch review GL-04, GL-05, GL-07, GL-08, GL-09, 2026-10-07):
the appliance publishes itself on the tailnet, its sync engine can start, the
wizard's steps are forms rather than "redeploy", the sync engine's admin page
has a login, and the server watches its own link to the fleet.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, appliance_config, auth, setup_engine, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import syncthing_gui_guard, tailnet_serve, tailscale_local
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

REPO = Path(__file__).resolve().parents[2]
COMPOSE = (REPO / "dashboard" / "deploy" / "compose.appliance.yaml").read_text(encoding="utf-8")
SECRET = "test-secret"
NOW = "2026-10-07T12:00:00+00:00"
DNS = "ccsync-studio.tail1234.ts.net."


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "s.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _fresh_guards():
    tailnet_serve.reset_for_tests()
    syncthing_gui_guard.reset_for_tests()
    yield
    tailnet_serve.reset_for_tests()
    syncthing_gui_guard.reset_for_tests()


def ctx(conn, settings=None):
    app = SimpleNamespace(state=SimpleNamespace())
    return setup_engine.SetupContext(conn=conn, settings=settings or Settings(), app=app)


def running(**extra):
    raw = {"BackendState": "Running", "AuthURL": "", "CertDomains": ["ccsync-studio.tail1234.ts.net"],
           "Self": {"DNSName": DNS, **extra.pop("self", {})}, "TailscaleIPs": ["100.64.0.9"]}
    raw.update(extra)
    return raw


class FakeNode:
    """Stands in for tailscaled's LocalAPI: status, serve-config read, serve-config post."""

    def __init__(self, monkeypatch, status, serve=None, post_ok=True, post_why=""):
        self.status = status
        self.serve = serve
        self.posts = []
        self.post_ok = post_ok
        self.post_why = post_why
        monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: True)
        monkeypatch.setattr(tailscale_local, "status", lambda *a, **k: self.status)
        monkeypatch.setattr(tailnet_serve, "read_serve", lambda env=None: self.serve)

        def post(path, body, env=None, timeout=3.0):
            self.posts.append((path, body))
            if self.post_ok:
                self.serve = body
            return self.post_ok, self.post_why

        monkeypatch.setattr(tailnet_serve, "_post_json", post)


# ======================================================================
# GL-04: publish on the tailnet, and the tick is earned
# ======================================================================

def test_serve_config_names_the_node_and_the_dashboard():
    cfg = tailnet_serve.build_config(DNS)
    assert cfg["TCP"]["443"]["HTTPS"] is True
    host = "ccsync-studio.tail1234.ts.net:443"
    assert cfg["Web"][host]["Handlers"]["/"]["Proxy"] == "http://dashboard:8480"


def test_a_hand_written_serve_config_counts_as_published():
    mine = {"Web": {"other.ts.net:443": {"Handlers": {"/": {"Proxy": "http://x:1"}}}}}
    assert tailnet_serve.serve_covers(mine)
    assert not tailnet_serve.serve_covers(mine, DNS)
    assert not tailnet_serve.serve_covers({})
    assert not tailnet_serve.serve_covers(None)


def test_a_running_node_with_nothing_published_is_not_green(conn, monkeypatch):
    """The defect: the tick used to turn green on `Running` alone."""
    FakeNode(monkeypatch, running(), serve={})
    state = setup_engine.get("tailnet").check(ctx(conn))
    assert state.status == "todo"
    assert "nothing publishes" in state.detail
    # the manual fallback is named in the refusal
    assert "tailscale serve --bg http://dashboard:8480" in state.detail


def test_a_running_node_whose_serve_cannot_be_read_is_not_green(conn, monkeypatch):
    FakeNode(monkeypatch, running(), serve=None)
    state = setup_engine.get("tailnet").check(ctx(conn))
    assert state.status == "todo"
    assert "could not be read" in state.detail


def test_published_through_serve_is_green(conn, monkeypatch):
    FakeNode(monkeypatch, running(), serve=tailnet_serve.build_config(DNS))
    state = setup_engine.get("tailnet").check(ctx(conn))
    assert state.status == "ok"
    assert "ccsync-studio.tail1234.ts.net" in state.detail


def test_a_tailnet_dashboard_url_also_earns_the_tick(conn, monkeypatch):
    """A studio that publishes some other way keeps its green."""
    FakeNode(monkeypatch, running(), serve={})
    site_store.set_many(conn, {"dashboard_url": "https://nas.tail1.ts.net"}, updated_by="a")
    conn.commit()
    assert setup_engine.get("tailnet").check(ctx(conn)).status == "ok"


def test_the_button_publishes_and_records_the_address(conn, monkeypatch):
    node = FakeNode(monkeypatch, running(), serve={})
    state = setup_engine.get("tailnet").run(ctx(conn))
    assert state.status == "ok", state.detail
    assert node.posts and node.posts[0][0] == "/localapi/v0/serve-config"
    manifest = site_store.resolved_manifest(conn, Settings())
    assert manifest["dashboard_url"] == "https://ccsync-studio.tail1234.ts.net"


def test_publishing_never_overwrites_a_dashboard_url_the_site_already_has(conn, monkeypatch):
    FakeNode(monkeypatch, running(), serve={})
    site_store.set_many(conn, {"dashboard_url": "http://192.168.0.10:8480"}, updated_by="a")
    conn.commit()
    ok, _detail = tailnet_serve.publish(conn, Settings())
    assert ok
    assert site_store.resolved_manifest(conn, Settings())["dashboard_url"] == \
        "http://192.168.0.10:8480"


def test_serve_not_enabled_on_the_tailnet_says_so_and_stays_todo(conn, monkeypatch):
    FakeNode(monkeypatch, running(), serve={}, post_ok=False,
             post_why="Serve is not enabled on your tailnet. To enable, visit https://login.tailscale.com/f/serve")
    state = setup_engine.get("tailnet").run(ctx(conn))
    assert state.status == "todo"
    assert "Serve is not turned on" in state.detail
    assert "login.tailscale.com/f/serve" in state.detail
    assert "tailscale serve --bg" in state.detail


def test_watchdog_puts_a_lost_serve_config_back(conn, monkeypatch):
    node = FakeNode(monkeypatch, running(), serve={})
    assert tailnet_serve.tick(conn, Settings(), now_monotonic=1000.0) == "repaired"
    assert len(node.posts) == 1
    # rate limited: a collector that wakes every few seconds does not hammer tailscaled
    assert tailnet_serve.tick(conn, Settings(), now_monotonic=1010.0) == "skipped"
    assert tailnet_serve.tick(conn, Settings(), now_monotonic=1100.0) == "ok"
    assert len(node.posts) == 1


def test_watchdog_reports_a_repair_that_failed(conn, monkeypatch):
    FakeNode(monkeypatch, running(), serve={}, post_ok=False, post_why="boom")
    assert tailnet_serve.tick(conn, Settings(), now_monotonic=1000.0) == "failed"
    assert tailnet_serve.last_repair()["ok"] is False


def test_watchdog_is_inert_with_no_bundled_node(conn, monkeypatch):
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: False)
    assert tailnet_serve.tick(conn, Settings()) == "no-node"
    assert tailnet_serve.snapshot() is None


def test_watchdog_leaves_a_node_that_is_not_running_alone(conn, monkeypatch):
    node = FakeNode(monkeypatch, {"BackendState": "NeedsLogin", "AuthURL": "x", "Self": {}})
    assert tailnet_serve.tick(conn, Settings(), now_monotonic=5.0) == "not-running"
    assert node.posts == []


# ======================================================================
# GL-05: the sync engine's config folder is made and owned by secrets-init
# ======================================================================

def _secrets_init_block() -> str:
    start = COMPOSE.index("  secrets-init:")
    end = COMPOSE.index("\n  dashboard:", start)
    return COMPOSE[start:end]


def test_secrets_init_owns_the_syncthing_config_folder():
    block = _secrets_init_block()
    assert "/syncthing-config:/syncthing-config" in block
    assert re.search(r"chown -R \$\{APP_UID:-3000\}:\$\{APP_GID:-3001\} /syncthing-config", block)
    # the same host path the syncthing service mounts
    assert "/syncthing-config:/var/syncthing/config" in COMPOSE


def test_secrets_init_makes_the_three_tree_folders_and_never_chowns_existing_ones():
    block = _secrets_init_block()
    assert ":/tree" in block
    for rel in ('"Projects"', '"Assets/B-roll Archive"', '"Assets/Music"'):
        assert rel in block
    # a folder is only created+chowned inside the `[ ! -d ]` guard
    guard = block.index('if [ ! -d "/tree/$$rel" ]')
    assert block.index('chown ${APP_UID:-3000}:${APP_GID:-3001} "/tree/$$rel"') > guard
    assert "chown -R" not in block[guard:block.index("echo \"secrets-init: done\"")]


def test_the_tree_loop_really_runs(tmp_path):
    """Run the shell loop against a scratch tree: missing folders appear, an
    existing one is untouched (bash only; skipped where there is none)."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    block = _secrets_init_block()
    loop = block[block.index("for rel in"):block.index('echo "secrets-init: done"')]
    loop = loop.replace("$$", "$").replace("/tree/", f"{tmp_path.as_posix()}/")
    loop = loop.replace("chown ${APP_UID:-3000}:${APP_GID:-3001}", "true")
    (tmp_path / "Assets").mkdir()
    (tmp_path / "Assets" / "keep.txt").write_text("customer data")
    out = subprocess.run([bash, "-c", "set -eu\n" + loop], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "Projects").is_dir()
    assert (tmp_path / "Assets" / "B-roll Archive").is_dir()
    assert (tmp_path / "Assets" / "Music").is_dir()
    assert (tmp_path / "Assets" / "keep.txt").read_text() == "customer data"
    assert "created Assets\n" not in out.stdout        # existed: never touched


# ======================================================================
# GL-07: wizard forms in place of "set an env var and redeploy"
# ======================================================================

def test_overlay_fills_only_what_the_environment_leaves_blank(tmp_path):
    appliance_config.save("admin", {"DASH_ADMIN_USERS": "alex, sam"}, data_dir=tmp_path)
    appliance_config.save("release_key", {"DASH_RELEASE_PUBKEYS": "A" * 43 + "="},
                          data_dir=tmp_path)
    env = {"DASH_ADMIN_USERS": "from-compose"}
    applied = appliance_config.apply_overlay(env, data_dir=tmp_path)
    assert env["DASH_ADMIN_USERS"] == "from-compose"            # env always wins
    assert "DASH_RELEASE_PUBKEYS" in applied and env["DASH_RELEASE_PUBKEYS"]
    assert "DASH_ADMIN_USERS" not in applied


def test_the_stored_value_reaches_settings(tmp_path):
    appliance_config.save("admin", {"DASH_ADMIN_USERS": "Alex, sam"}, data_dir=tmp_path)
    env = {"DASH_DB_PATH": str(tmp_path / "dashboard.db")}
    # data dir comes from DASH_DB_PATH, as secrets_boot derives it
    (tmp_path / "secrets").mkdir(exist_ok=True)
    assert appliance_config.config_path(env) == tmp_path / "secrets" / "appliance_config.json"
    appliance_config.apply_overlay(env)
    assert Settings.from_env(env).admin_users == frozenset({"alex", "sam"})


def test_a_key_that_is_not_in_the_allow_list_cannot_be_written(tmp_path):
    with pytest.raises(appliance_config.ConfigError):
        appliance_config.save("admin", {"DASH_SESSION_SECRET": "x"}, data_dir=tmp_path)
    with pytest.raises(appliance_config.ConfigError):
        # right key, wrong task
        appliance_config.save("admin", {"DASH_NAS_HOST": "nas"}, data_dir=tmp_path)
    with pytest.raises(appliance_config.ConfigError):
        appliance_config.save("studio", {"DASH_ADMIN_USERS": "a"}, data_dir=tmp_path)


@pytest.mark.parametrize("task,values", [
    ("admin", {"DASH_ADMIN_USERS": "bad name!"}),
    ("syncthing", {"SYNCTHING_GUI_URL": "ftp://x"}),
    ("syncthing", {"SYNCTHING_GUI_URL": "http://user:pw@host:8384"}),
    ("nas_connect", {"DASH_NAS_HOST": "http://nas"}),
    ("nas_connect", {"DASH_NAS_KIND": "qnap"}),
    ("release_key", {"DASH_RELEASE_PUBKEYS": "not-a-key"}),
    ("software", {"DASH_RELEASE_FEED_URL": "http://insecure.example/feed"}),
])
def test_values_are_validated(tmp_path, task, values):
    with pytest.raises(appliance_config.ConfigError):
        appliance_config.save(task, values, data_dir=tmp_path)
    assert appliance_config.load(data_dir=tmp_path) == {}


def test_a_secret_is_never_shown_back_and_blank_keeps_it(tmp_path):
    appliance_config.save("nas_connect", {"DASH_NAS_HOST": "nas.local",
                                          "DASH_NAS_API_KEY": "1-sekret",
                                          "DASH_NAS_API_KEY_USER": "ccsync-svc"},
                                         data_dir=tmp_path)
    shown = json.dumps(appliance_config.view("nas_connect", data_dir=tmp_path))
    assert "1-sekret" not in shown
    key = next(f for f in appliance_config.view("nas_connect", data_dir=tmp_path)
               if f["env"] == "DASH_NAS_API_KEY")
    assert key["set"] is True and key["value"] == ""
    appliance_config.save("nas_connect", {"DASH_NAS_HOST": "nas2.local",
                                          "DASH_NAS_API_KEY": ""}, data_dir=tmp_path)
    stored = appliance_config.load(data_dir=tmp_path)
    assert stored["DASH_NAS_API_KEY"] == "1-sekret" and stored["DASH_NAS_HOST"] == "nas2.local"


def test_the_file_is_private(tmp_path):
    appliance_config.save("admin", {"DASH_ADMIN_USERS": "alex"}, data_dir=tmp_path)
    path = appliance_config.config_path(data_dir=tmp_path)
    assert path.is_file()
    import os
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600


def test_remedy_texts_no_longer_send_a_customer_to_the_container_environment(conn):
    c = ctx(conn)
    texts = [
        setup_engine.get("admin").check(c).detail,
        setup_engine.get("syncthing").check(c).detail,
        setup_engine.get("nas_connect").check(c).detail,
        setup_engine.get("release_key").check(c).detail,
    ]
    for text in texts:
        assert "redeploy" not in text.lower(), text
        assert not re.search(r"\b(DASH|SYNCTHING)_[A-Z_]+\b", text), text


@pytest.fixture
def client_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "setup.db"))
    settings = Settings(db_path=str(tmp_path / "setup.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    restarts = []
    monkeypatch.setattr(appliance_config, "schedule_restart",
                        lambda s, *a, **k: restarts.append(s))
    with TestClient(create_app(settings)) as client:
        yield client, restarts


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))


def test_the_task_list_carries_forms_for_the_six_steps(client_env):
    client, _ = client_env
    as_user(client, "owen")
    tasks = {t["id"]: t for t in client.get("/api/v1/setup/tasks").json()["tasks"]}
    for task_id in ("admin", "syncthing", "nas_connect", "release_key", "software"):
        assert tasks[task_id]["fields"], task_id
        assert tasks[task_id]["operator_note"]
    assert tasks["secrets"]["restartable"] is True
    assert tasks["studio"]["fields"] == []


def test_the_form_post_stores_audits_and_restarts(client_env, tmp_path):
    client, restarts = client_env
    as_user(client, "owen")
    resp = client.post("/api/v1/setup/config/admin",
                       json={"values": {"DASH_ADMIN_USERS": "alex"}})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "saved": ["DASH_ADMIN_USERS"], "restarting": True}
    assert len(restarts) == 1
    assert appliance_config.load(data_dir=tmp_path) == {"DASH_ADMIN_USERS": "alex"}


def test_the_form_post_refuses_bad_input_without_restarting(client_env):
    client, restarts = client_env
    as_user(client, "owen")
    resp = client.post("/api/v1/setup/config/release_key",
                       json={"values": {"DASH_RELEASE_PUBKEYS": "nope"}})
    assert resp.status_code == 422
    assert restarts == []


def test_the_form_post_needs_an_admin_session(client_env):
    client, restarts = client_env
    assert client.post("/api/v1/setup/config/admin",
                       json={"values": {"DASH_ADMIN_USERS": "x"}}).status_code == 401
    as_user(client, "editor1")
    assert client.post("/api/v1/setup/config/admin",
                       json={"values": {"DASH_ADMIN_USERS": "x"}}).status_code == 403
    assert restarts == []


def test_restart_route_is_admin_only_and_schedules_one(client_env):
    client, restarts = client_env
    assert client.post("/api/v1/setup/restart").status_code == 401
    as_user(client, "owen")
    assert client.post("/api/v1/setup/restart").json()["restarting"] is True
    assert len(restarts) == 1


def test_the_secrets_step_points_at_the_button_not_the_container(conn, tmp_path):
    settings = Settings(db_path=str(tmp_path / "x" / "d.db"))
    state = setup_engine.get("secrets").run(ctx(conn, settings))
    # nothing generated in a scratch dir => the detail may or may not carry the
    # sentence, but it must never carry the old instruction
    assert "Restart the container" not in state.detail


# ======================================================================
# GL-08: the sync engine's admin page has a login
# ======================================================================

class FakeGuiClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.puts = []

    def _request(self, method, path, params=None, json_body=None, timeout=None):
        assert path == "/rest/config/gui"
        if method == "GET":
            if self.cfg is None:
                raise RuntimeError("down")
            return dict(self.cfg)
        self.puts.append(json_body)
        self.cfg = dict(json_body)
        return {}


def gui_settings(tmp_path, **kw):
    return Settings(db_path=str(tmp_path / "d.db"), syncthing_url="http://tailscale:8384", **kw)


def test_an_open_admin_page_gets_a_user_and_a_stored_password(tmp_path):
    settings = gui_settings(tmp_path)
    client = FakeGuiClient({"address": "0.0.0.0:8384", "enabled": True, "user": "",
                            "password": "", "insecureAdminAccess": True, "apiKey": "k"})
    result = syncthing_gui_guard.ensure(settings, client)
    assert result["status"] == "secured"
    put = client.puts[0]
    assert put["user"] == "ccsync-admin" and put["password"]
    assert put["insecureAdminAccess"] is False
    assert put["apiKey"] == "k"                       # the dashboard's own key untouched
    assert syncthing_gui_guard.read_password(settings) == put["password"]
    assert syncthing_gui_guard.is_protected(client) is True


def test_a_page_that_already_has_a_login_is_left_exactly_alone(tmp_path):
    client = FakeGuiClient({"address": "x", "user": "studio", "password": "$2a$hash",
                            "insecureAdminAccess": False})
    assert syncthing_gui_guard.ensure(gui_settings(tmp_path), client)["status"] == "protected"
    assert client.puts == []


def test_insecure_admin_access_is_closed_even_with_a_user(tmp_path):
    client = FakeGuiClient({"address": "x", "user": "studio", "password": "$2a$h",
                            "insecureAdminAccess": True})
    assert syncthing_gui_guard.ensure(gui_settings(tmp_path), client)["status"] == "secured"
    assert client.puts[0]["user"] == "studio"          # an existing user name is kept
    assert client.puts[0]["password"] == "$2a$h"       # and so is the password
    assert client.puts[0]["insecureAdminAccess"] is False


def test_the_guard_can_be_switched_off_and_never_guesses(tmp_path):
    client = FakeGuiClient({"address": "x", "user": "", "password": ""})
    off = gui_settings(tmp_path, syncthing_gui_secure=False)
    assert syncthing_gui_guard.ensure(off, client)["status"] == "disabled"
    assert client.puts == []
    # an answer that does not look like a GUI config is "could not tell"
    odd = FakeGuiClient({"unrelated": 1})
    assert syncthing_gui_guard.ensure(gui_settings(tmp_path), odd)["status"] == "unknown"
    assert syncthing_gui_guard.is_protected(odd) is None
    assert syncthing_gui_guard.is_protected(FakeGuiClient(None)) is None


def test_the_password_is_stored_before_it_is_sent(tmp_path):
    settings = gui_settings(tmp_path)

    class Boom(FakeGuiClient):
        def _request(self, method, *a, **k):
            if method == "PUT":
                raise RuntimeError("refused")
            return super()._request(method, *a, **k)

    result = syncthing_gui_guard.ensure(settings, Boom({"address": "x", "user": "", "password": ""}))
    assert result["status"] == "failed"
    assert syncthing_gui_guard.read_password(settings)        # not lost; reused next try


def test_secure_is_the_default_and_only_zero_turns_it_off():
    assert Settings.from_env({}).syncthing_gui_secure is True
    assert Settings.from_env({"DASH_SYNCTHING_GUI_SECURE": "no"}).syncthing_gui_secure is True
    assert Settings.from_env({"DASH_SYNCTHING_GUI_SECURE": "0"}).syncthing_gui_secure is False


def test_the_tick_is_rate_limited_and_retries_a_failure_soon(tmp_path):
    settings = gui_settings(tmp_path)
    client = FakeGuiClient({"address": "x", "user": "", "password": ""})
    assert syncthing_gui_guard.tick(settings, client, now_monotonic=0.0) == "secured"
    assert syncthing_gui_guard.tick(settings, client, now_monotonic=30.0) == "skipped"
    # verified again after the long interval
    assert syncthing_gui_guard.tick(settings, client, now_monotonic=4000.0) == "protected"


def test_compose_no_longer_claims_the_gui_is_unreachable_from_the_tailnet():
    assert "deliberately never exposed anywhere outside" not in COMPOSE
    assert "syncthing_gui_guard" in COMPOSE


def test_the_setup_check_warns_when_the_page_is_open(tmp_path, monkeypatch, conn):
    from ccsync_dashboard import syncthing_client

    class StubClient:
        timeout = 5.0
        _request = FakeGuiClient({"address": "x", "user": "", "password": ""})._request

        def system_status(self):
            return {"myID": "ABCDEFGHIJ"}

    monkeypatch.setattr(syncthing_client.SyncthingClient, "from_settings",
                        classmethod(lambda cls, s, session=None: StubClient()))
    state = setup_engine.get("syncthing").check(ctx(conn, gui_settings(tmp_path)))
    assert state.status == "warn" and "no password" in state.detail


# ======================================================================
# GL-09: the server watches its own tailnet connection
# ======================================================================

def alert_ctx(tailnet=None, editors=()):
    return SimpleNamespace(tailnet=tailnet, editors=list(editors), now=NOW,
                           name=lambda s: s)


def test_key_expiry_parses_go_timestamps_and_ignores_zero_time():
    raw = {"Self": {"KeyExpiry": "2027-03-01T10:20:30.123456789Z"}}
    assert tailnet_serve.key_expiry(raw).year == 2027
    assert tailnet_serve.key_expiry({"Self": {"KeyExpiry": "0001-01-01T00:00:00Z"}}) is None
    assert tailnet_serve.key_expiry({"Self": {}}) is None
    assert tailnet_serve.key_expiry(None) is None
    assert tailnet_serve.key_expiry({"Self": {"KeyExpiry": "garbage"}}) is None


def expiry_in(days):
    return dt.datetime.fromisoformat(NOW) + dt.timedelta(days=days)


def test_key_expiry_alerts_fourteen_days_ahead_and_not_before():
    soon = alerts._check_tailnet_key(alert_ctx({"key_expiry": expiry_in(13)}))
    assert len(soon) == 1 and "Disable key expiry" in soon[0]["fix"]
    assert alerts._check_tailnet_key(alert_ctx({"key_expiry": expiry_in(40)})) == []
    assert alerts._check_tailnet_key(alert_ctx({"key_expiry": None})) == []
    assert alerts._check_tailnet_key(alert_ctx(None)) == []
    gone = alerts._check_tailnet_key(alert_ctx({"key_expiry": expiry_in(-1)}))
    assert "expired" in gone[0]["diagnosis"]


def test_a_node_that_is_not_running_is_one_finding():
    found = alerts._check_tailnet_node(alert_ctx({"backend_state": "NeedsLogin"}))
    assert len(found) == 1 and "NeedsLogin" in found[0]["diagnosis"]
    assert alerts._check_tailnet_node(alert_ctx({"backend_state": "Running"})) == []
    assert alerts._check_tailnet_node(alert_ctx(None)) == []        # no node: not checked


def test_missing_serve_alerts_only_on_positive_evidence():
    base = {"backend_state": "Running"}
    assert len(alerts._check_tailnet_serve(alert_ctx({**base, "serve": False}))) == 1
    assert alerts._check_tailnet_serve(alert_ctx({**base, "serve": True})) == []
    # unreadable is NOT CHECKED (the check raises, so the kind is check_failed
    # and deliver() does not mail "cleared"), never "fine"
    with pytest.raises(RuntimeError):
        alerts._check_tailnet_serve(alert_ctx({**base, "serve": None}))
    with pytest.raises(RuntimeError):
        alerts._check_tailnet_serve(alert_ctx({"backend_state": "unreachable", "serve": None}))
    with pytest.raises(RuntimeError):
        alerts._check_tailnet_key(alert_ctx({"backend_state": "unreachable", "key_expiry": None}))
    assert alerts._check_tailnet_serve(alert_ctx({"backend_state": "Stopped", "serve": False})) == []


def _machine(name, minutes_ago):
    stamp = (dt.datetime.fromisoformat(NOW) - dt.timedelta(minutes=minutes_ago)).isoformat()
    return {"editor_username": name, "machine": "pc", "received_at": stamp}


def test_most_machines_going_quiet_together_is_one_alert():
    fleet = [_machine("a", 50), _machine("b", 48), _machine("c", 45), _machine("d", 5)]
    found = alerts._check_fleet_silent_at_once(alert_ctx(
        {"backend_state": "NeedsLogin", "serve": None}, editors=fleet))
    assert len(found) == 1
    assert "3 of the 4" in found[0]["diagnosis"]
    assert "tailnet" in found[0]["fix"]


def test_scattered_lids_closing_is_not_a_fleet_outage():
    fleet = [_machine("a", 200), _machine("b", 100), _machine("c", 45), _machine("d", 5)]
    assert alerts._check_fleet_silent_at_once(alert_ctx(
        {"backend_state": "NeedsLogin", "serve": None}, editors=fleet)) == []


def test_a_single_quiet_machine_and_a_tiny_fleet_do_not_trigger_it():
    assert alerts._check_fleet_silent_at_once(
        alert_ctx({"backend_state": "NeedsLogin"},
                  editors=[_machine("a", 50), _machine("d", 5), _machine("e", 4)])) == []
    assert alerts._check_fleet_silent_at_once(
        alert_ctx({"backend_state": "NeedsLogin"}, editors=[_machine("a", 50)])) == []


def test_the_four_kinds_are_registered_and_in_a_page_group():
    names = {"tailnet_node_down", "tailnet_key_expiring", "tailnet_serve_missing",
             "fleet_silent_at_once"}
    assert names <= set(alerts.KIND_BY_NAME)
    grouped = {k for _title, kinds in alerts.KIND_GROUPS for k in kinds}
    assert names <= grouped
    # the one catch-all stays last
    assert alerts.ALERT_KINDS[-1].kind == "red_unexplained"


def test_a_scan_with_no_tailnet_node_raises_nothing(conn, monkeypatch):
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: False)
    assert alerts._tailnet_state() is None


def test_setup_offers_the_heartbeat_and_stores_the_choice(conn):
    c = setup_engine.SetupContext(conn=conn, settings=Settings(), app=SimpleNamespace(
        state=SimpleNamespace()), payload={"email": "boss@example.com", "heartbeat": True})
    state = setup_engine.run_do_it(c, "alerts")
    assert alerts.get_settings(conn)["alerts_heartbeat"] == "1"
    assert "still-here message is on" in state.detail or state.status in ("warn", "ok")
    off = setup_engine.SetupContext(conn=conn, settings=Settings(), app=SimpleNamespace(
        state=SimpleNamespace()), payload={"email": "boss@example.com", "heartbeat": False})
    setup_engine.run_do_it(off, "alerts")
    assert alerts.get_settings(conn)["alerts_heartbeat"] == "0"
    # a form that does not send the field leaves the choice alone
    keep = setup_engine.SetupContext(conn=conn, settings=Settings(), app=SimpleNamespace(
        state=SimpleNamespace()), payload={"email": "boss@example.com"})
    setup_engine.run_do_it(keep, "alerts")
    assert alerts.get_settings(conn)["alerts_heartbeat"] == "0"


def test_the_checklist_says_when_the_dead_mans_message_is_off(conn):
    alerts.set_settings(conn, {"alerts_sink": alerts.SINK_WEBHOOK,
                               "alerts_webhook_url": "https://hooks.example.com/x"}, "t")
    conn.commit()
    state = setup_engine.get("alerts").check(ctx(conn))
    assert state.status == "ok" and "itself goes down" in state.detail


def test_the_tailnet_ok_detail_tells_the_admin_to_disable_key_expiry(conn, monkeypatch):
    far = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=150)).strftime("%Y-%m-%dT%H:%M:%SZ")
    FakeNode(monkeypatch, running(self={"KeyExpiry": far}),
             serve=tailnet_serve.build_config(DNS))
    state = setup_engine.get("tailnet").check(ctx(conn))
    assert state.status == "ok" and "Disable key expiry" in state.detail


def test_the_tailnet_task_warns_when_the_key_is_about_to_expire(conn, monkeypatch):
    soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    FakeNode(monkeypatch, running(self={"KeyExpiry": soon}),
             serve=tailnet_serve.build_config(DNS))
    state = setup_engine.get("tailnet").check(ctx(conn))
    assert state.status == "warn" and "expires in" in state.detail


# ======================================================================
# Overseer fixes (2026-10-07)
# ======================================================================

SICK = {"backend_state": "NeedsLogin", "serve": None}
HEALTHY = {"backend_state": "Running", "serve": True}


def test_an_end_of_day_cluster_with_a_healthy_node_is_not_an_outage():
    """Overseer fix: four machines shut down around 18:00 look exactly like a
    fleet that lost the server. Without the node corroborating, say nothing."""
    fleet = [_machine("a", 70), _machine("b", 68), _machine("c", 65), _machine("d", 62)]
    assert alerts._check_fleet_silent_at_once(alert_ctx(HEALTHY, editors=fleet)) == []
    assert alerts._check_fleet_silent_at_once(alert_ctx(None, editors=fleet)) == []
    assert len(alerts._check_fleet_silent_at_once(alert_ctx(SICK, editors=fleet))) == 1


def test_a_real_outage_stays_open_past_six_hours_until_machine_silent_takes_over():
    fleet = [_machine(n, m) for n, m in (("a", 420), ("b", 418), ("c", 415), ("d", 416))]
    assert len(alerts._check_fleet_silent_at_once(alert_ctx(SICK, editors=fleet))) == 1
    day = [_machine(n, 24 * 60 + m) for n, m in (("a", 20), ("b", 18), ("c", 15), ("d", 16))]
    assert alerts._check_fleet_silent_at_once(alert_ctx(SICK, editors=day)) == []


class _Resp:
    def __init__(self, status, body):
        self.status, self._b = status, body

    def read(self, n=-1):
        return self._b


def _fake_localapi(monkeypatch, status_obj, serve_body, posted):
    """A LocalAPI that answers like the real one: GET serve-config on an
    empty node is HTTP 200 with the literal body `null` (spike S1c)."""
    class Conn:
        def __init__(self, path, timeout=None):
            pass

        def request(self, method, path, body=None, headers=None):
            self.m, self.p, self.b = method, path, body

        def getresponse(self):
            if self.p == "/localapi/v0/status":
                return _Resp(200, json.dumps(status_obj).encode())
            if self.m == "GET":
                return _Resp(200, serve_body)
            posted.append(json.loads(self.b))
            return _Resp(200, b"")

        def close(self):
            pass

    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: True)
    monkeypatch.setattr(tailscale_local, "_UnixHTTPConnection", Conn)
    monkeypatch.setattr(tailnet_serve, "_Conn", Conn)


def test_a_null_serve_config_is_empty_not_unreadable(conn, monkeypatch):
    posted = []
    _fake_localapi(monkeypatch, running(), b"null", posted)
    assert tailnet_serve.read_serve() == {}
    assert tailnet_serve.snapshot()["serve"] is False
    ok, detail = tailnet_serve.publish(conn, Settings())
    assert ok and posted and posted[0]["Web"]


def test_the_watchdog_repairs_a_node_whose_serve_answers_null(conn, monkeypatch):
    posted = []
    _fake_localapi(monkeypatch, running(), b"null", posted)
    assert tailnet_serve.tick(conn, Settings(), now_monotonic=9000.0) == "repaired"
    assert len(posted) == 1


def test_a_refused_or_garbled_serve_read_is_still_unreadable(monkeypatch):
    for body in (b"[1]", b"{not json"):
        _fake_localapi(monkeypatch, running(), body, [])
        assert tailnet_serve.read_serve() is None


def test_https_certificates_off_means_no_publish_and_no_recorded_url(conn, monkeypatch):
    """The LocalAPI accepts a Serve config on a tailnet without HTTPS; nothing
    could then connect. Stay todo, name the DNS page, record nothing."""
    node = FakeNode(monkeypatch, running(CertDomains=None), serve={})
    ok, detail = tailnet_serve.publish(conn, Settings())
    assert not ok and "HTTPS" in detail and "admin/dns" in detail
    assert node.posts == []
    assert not site_store.resolved_manifest(conn, Settings()).get("dashboard_url")
    state = setup_engine.get("tailnet").run(ctx(conn))
    assert state.status == "todo" and "admin/dns" in state.detail
    # even a hand-written Serve config is not green without certificates
    node.serve = tailnet_serve.build_config(DNS)
    assert setup_engine.get("tailnet").check(ctx(conn)).status == "todo"


def test_https_capability_reads_certdomains_or_the_capability():
    assert tailnet_serve.https_capable({"CertDomains": ["a.ts.net"]})
    assert tailnet_serve.https_capable({"Self": {"Capabilities": ["https"]}})
    assert not tailnet_serve.https_capable({"CertDomains": None, "Self": {}})
    assert not tailnet_serve.https_capable(None)


def test_an_unreadable_snapshot_does_not_clear_an_open_tailnet_alert(conn, monkeypatch):
    """Both kinds raise on an unreadable node, so scan() files check_failed and
    deliver() leaves them out of checked_kinds (no 'cleared' mail)."""
    monkeypatch.setattr(alerts, "_tailnet_state",
                        lambda: {"backend_state": "unreachable", "dns_name": "",
                                 "key_expiry": None, "serve": None})
    found = alerts.scan(conn, Settings(), NOW)
    failed = {f["subject"] for f in found if f["kind"] == alerts.CHECK_FAILED.kind}
    assert {"tailnet_key_expiring", "tailnet_serve_missing"} <= failed


def test_an_existing_gui_login_is_kept_when_only_insecure_access_is_on(tmp_path):
    client = FakeGuiClient({"address": "x", "user": "studio", "password": "$2a$mine",
                            "insecureAdminAccess": True})
    assert syncthing_gui_guard.ensure(gui_settings(tmp_path), client)["status"] == "secured"
    assert client.puts[0]["password"] == "$2a$mine"
    assert client.puts[0]["insecureAdminAccess"] is False
    assert not syncthing_gui_guard.read_password(gui_settings(tmp_path))


# ======================================================================
# Round 2 (2026-10-07)
# ======================================================================


def _compose_service_block(name):
    import re as _re
    m = _re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S)", COMPOSE, _re.S | _re.M)
    assert m, name
    return m.group(1)


def test_tailscaled_runs_as_the_dashboards_own_uid_so_localapi_writes_work():
    """GL-04 round 2: tailscaled grants LocalAPI write to the peer's uid only
    if it is root, the daemon's own uid, the operator or a local admin. The
    dashboard runs as APP_UID, so the daemon must too."""
    import re as _re
    want = '"${APP_UID:-3000}:${APP_GID:-3001}"'
    dash = _re.search(r'^    user: (".*")$', _compose_service_block("dashboard"), _re.M)
    ts = _re.search(r'^    user: (".*")$', _compose_service_block("tailscale"), _re.M)
    assert dash and ts and dash.group(1) == ts.group(1) == want
    # and secrets-init hands that uid the state folder and the socket volume
    init = _compose_service_block("secrets-init")
    assert "/tailscale-state" in init and "/tailscale-sock" in init
    assert "chown -R ${APP_UID:-3000}:${APP_GID:-3001} /tailscale-state /tailscale-sock" in init
    assert "service_completed_successfully" in _compose_service_block("tailscale")


def test_the_s1c_spike_is_not_cited_as_proof_of_a_write_as_the_dashboard_uid():
    assert "ran its client\n      # as ROOT" in COMPOSE or "client ran as ROOT" in COMPOSE or "as ROOT" in COMPOSE


def _busy(name, minutes_ago, state="syncing"):
    m = _machine(name, minutes_ago)
    m["lanes"] = [{"state": state}]
    return m


def test_no_bundled_node_a_cluster_that_vanished_mid_transfer_still_alerts():
    """GL-09 round 2: the TrueNAS case (no socket, ctx.tailnet None). A NAS
    update that stops the Tailscale app takes machines out mid-transfer."""
    fleet = [_busy("a", 70), _busy("b", 68), _busy("c", 65), _machine("d", 5)]
    found = alerts._check_fleet_silent_at_once(alert_ctx(None, editors=fleet))
    assert len(found) == 1 and "middle of a transfer" in found[0]["diagnosis"]
    # a healthy node does not suppress mid-transfer evidence either
    assert len(alerts._check_fleet_silent_at_once(alert_ctx(HEALTHY, editors=fleet))) == 1


def test_no_bundled_node_an_idle_end_of_day_cluster_stays_quiet():
    fleet = [_busy("a", 70, "idle"), _busy("b", 68, "idle"),
             _busy("c", 65, "idle"), _machine("d", 5)]
    assert alerts._check_fleet_silent_at_once(alert_ctx(None, editors=fleet)) == []
    one = [_busy("a", 70), _busy("b", 68, "idle"), _busy("c", 65, "idle"), _machine("d", 5)]
    assert alerts._check_fleet_silent_at_once(alert_ctx(None, editors=one)) == []


def test_blanking_the_key_account_on_a_resubmit_is_refused(tmp_path):
    appliance_config.save("nas_connect", {"DASH_NAS_HOST": "nas.local",
                                          "DASH_NAS_API_KEY": "1-sekret",
                                          "DASH_NAS_API_KEY_USER": "svc"},
                          env={}, data_dir=tmp_path)
    for values in ({"DASH_NAS_API_KEY_USER": ""},
                   {"DASH_NAS_HOST": "", "DASH_NAS_API_KEY": "", "DASH_NAS_API_KEY_USER": ""}):
        with pytest.raises(appliance_config.ConfigError):
            appliance_config.save("nas_connect", values, env={}, data_dir=tmp_path)
    assert appliance_config.load({}, tmp_path)["DASH_NAS_API_KEY_USER"] == "svc"
