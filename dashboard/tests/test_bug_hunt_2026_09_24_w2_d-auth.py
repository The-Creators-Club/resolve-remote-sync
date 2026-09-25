"""Wave 2 of the 2026-09-24 hunt's fix pass, group d-auth (2026-09-25):
bug-dash-auth-1..7. Each test fails on HEAD 4462a2a's code."""
from __future__ import annotations

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, provision, sessions, setup_engine, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# ---------------------------------------------------------- bug-dash-auth-1

@pytest.fixture
def local_env(tmp_path):
    db_path = tmp_path / "local-setup.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET, auth_method="local")
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn, settings
        conn.close()


def test_first_run_window_opens_steps_one_and_two_only(local_env):
    client, conn, settings = local_env
    # Steps 1 and 2 still work with no account and no session.
    assert client.get("/api/v1/setup/tasks").status_code == 200
    assert client.get("/api/v1/setup/eula").status_code == 200
    assert client.post("/api/v1/setup/eula").status_code == 200
    # Everything else needs the session step 2 mints.
    r = client.post("/api/v1/setup/alerts", json={"webhook": "https://attacker.example/hook"})
    assert r.status_code == 401
    assert "admin account" in r.json()["detail"]
    from ccsync_dashboard import alerts

    assert "attacker" not in str(alerts.get_settings(conn))
    assert client.post("/api/v1/setup/alerts/test").status_code == 401
    assert client.post("/api/v1/setup/tasks/tailnet/run").status_code == 401
    assert client.post("/api/v1/setup/tasks/secrets/run").status_code == 401
    assert client.post("/api/v1/setup/tasks/storage/check").status_code == 401
    assert client.post("/api/v1/setup/tasks/tailnet/skip").status_code == 401


def test_the_wizard_signed_in_by_step_two_reaches_the_rest(local_env):
    client, conn, settings = local_env
    r = client.post("/api/v1/setup/admin",
                    json={"username": "owen", "password": "correct-horse-battery-staple"})
    assert r.status_code == 200
    # setup_admin set the session cookie on this client; CSRF wants the token
    # the page would carry, so read it the way the page does.
    page = client.get("/setup")
    assert page.status_code == 200
    import re

    m = re.search(r'<meta name="csrf" content="([^"]+)"', page.text)
    assert m, "the signed-in /setup page carries a CSRF token"
    headers = {"X-CSRF-Token": m.group(1)}
    r = client.post("/api/v1/setup/alerts", json={"webhook": "https://hooks.example/x"},
                    headers=headers)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------- bug-dash-auth-2

def _hold_write_lock(path, seconds, ready):
    other = sqlite3.connect(str(path), timeout=0)
    other.execute("BEGIN IMMEDIATE")
    ready.set()
    time.sleep(seconds)
    other.rollback()
    other.close()


def test_session_touch_under_a_held_write_lock_returns_fast_and_valid(tmp_path):
    path = tmp_path / "touch.db"
    store = sessions.SessionStore(path)
    store.create("sid1", "owen", now="2026-09-25T10:00:00Z")
    ready = threading.Event()
    t = threading.Thread(target=_hold_write_lock, args=(path, 4.0, ready))
    t.start()
    try:
        assert ready.wait(5)
        started = time.monotonic()
        # Five minutes on: due a touch.
        user = store.validate("sid1", now="2026-09-25T10:05:00Z")
        took = time.monotonic() - started
    finally:
        t.join()
    assert user == "owen"
    assert took < 2.0, took


def test_session_touch_skips_when_the_module_lock_is_held(tmp_path):
    store = sessions.SessionStore(tmp_path / "lock.db")
    store.create("sid1", "owen", now="2026-09-25T10:00:00Z")
    # Another thread holds the module lock (a revoke waiting on SQLite). On
    # HEAD validate() queued behind it; run it in a worker so a regression
    # fails here instead of hanging the suite.
    out: dict = {}

    def worker():
        out["user"] = store.validate("sid1", now="2026-09-25T10:05:00Z")

    with sessions._write_lock:
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(1.0)
        finished = not t.is_alive()
    t.join(30)
    assert finished, "validate() waited for the module write lock"
    assert out["user"] == "owen"
    # ...and the next request, lock free, does slide it.
    assert store.validate("sid1", now="2026-09-25T10:06:00Z") == "owen"
    conn = dbmod.connect(tmp_path / "lock.db")
    try:
        row = conn.execute("SELECT last_seen FROM auth_sessions WHERE sid='sid1'").fetchone()
    finally:
        conn.close()
    assert row["last_seen"] == "2026-09-25T10:06:00Z"


# ---------------------------------------------------------- bug-dash-auth-3

@pytest.fixture
def site_conn(tmp_path):
    conn = dbmod.connect(tmp_path / "site.db")
    dbmod.migrate(conn)
    yield conn
    conn.close()


def test_undo_of_a_template_change_restores_the_defaults_not_nothing(site_conn):
    settings = Settings()
    before = site_store.resolved_manifest(site_conn, settings)
    assert before["template_folders"] == list(provision.TEMPLATE_FOLDERS)
    normalized = site_store.validate_many({"template_folders": "Footage,Audio",
                                           "shared_asset_folders": "Assets/Luts"})
    changes = site_store.diff_against_current(site_conn, settings, normalized)
    by_key = {c["key"]: c for c in changes}
    assert by_key["template_folders"]["from"] == ",".join(provision.TEMPLATE_FOLDERS)
    site_store.set_many(site_conn, normalized, updated_by="owen")
    # Undo, the way setup_routes.api_admin_site_undo_last_change does it.
    restore = {c["key"]: c["from"] for c in changes}
    site_store.set_many(site_conn, site_store.validate_many(restore), updated_by="owen")
    after = site_store.resolved_manifest(site_conn, settings)
    assert after["template_folders"] == before["template_folders"]
    assert after["shared_asset_folders"] == before["shared_asset_folders"]


# ---------------------------------------------------------- bug-dash-auth-4

def test_an_asset_folder_with_no_ascii_letter_is_refused_in_words():
    with pytest.raises(site_store.SiteValidationError) as exc:
        site_store.validate_many({"shared_asset_folders": "Assets/Luts,音效"})
    assert "letter" in str(exc.value)


def test_two_asset_folders_with_one_folder_id_are_refused():
    with pytest.raises(site_store.SiteValidationError) as exc:
        site_store.validate_many({"shared_asset_folders": "Assets/SFX,Assets-SFX"})
    assert "assets-sfx" in str(exc.value)


def test_a_mixed_name_with_ascii_is_still_accepted():
    assert site_store.validate_many({"shared_asset_folders": "Assets/音效 SFX"}) == {
        "shared_asset_folders": "Assets/音效 SFX"}


def test_a_stored_bad_row_is_skipped_not_raised(site_conn):
    site_conn.execute(
        f"INSERT INTO {site_store.TABLE} (key, value, updated_at, updated_by) "
        "VALUES ('shared_asset_folders', 'Assets/Luts,音效,Assets-Luts', 'x', 'x')")
    site_conn.commit()
    manifest = site_store.resolved_manifest(site_conn, Settings())
    assert [f["rel"] for f in manifest["shared_asset_folders"]] == ["Assets/Luts"]


def test_api_site_answers_with_a_stored_bad_row(tmp_path):
    db_path = tmp_path / "api.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET)
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        conn.execute(
            f"INSERT INTO {site_store.TABLE} (key, value, updated_at, updated_by) "
            "VALUES ('shared_asset_folders', '音效', 'x', 'x')")
        conn.commit()
        conn.close()
        site_store.invalidate(app)
        assert client.get("/api/v1/site").status_code == 200


# ---------------------------------------------------------- bug-dash-auth-5

def test_oidc_claim_alone_does_not_satisfy_the_admin_step(site_conn):
    settings = Settings(auth_method="oidc", oidc_admin_claim="groups",
                        oidc_admin_values=frozenset({"ccsync-admins"}))
    ctx = setup_engine.SetupContext(conn=site_conn, settings=settings, app=None)
    state = setup_engine.run_check(ctx, "admin")
    assert state.status == "todo"
    assert "DASH_ADMIN_USERS" in state.detail
    # ...and with the list set it is ok, claim or no claim.
    settings = Settings(auth_method="oidc", oidc_admin_claim="groups",
                        admin_users=frozenset({"owen"}))
    ctx = setup_engine.SetupContext(conn=site_conn, settings=settings, app=None)
    assert setup_engine.run_check(ctx, "admin").status == "ok"


# ---------------------------------------------------------- bug-dash-auth-6

@pytest.mark.parametrize("value,expected", [
    ("1", "Secure forced on"), ("true", "Secure forced on"), ("yes", "Secure forced on"),
    ("on", "Secure forced on"), ("0", "Secure forced off"), ("false", "Secure forced off"),
    ("no", "Secure forced off"), ("off", "Secure forced off"),
    ("auto", "Secure follows the request scheme"),
])
def test_boot_line_names_the_cookie_mode_cookie_secure_obeys(value, expected):
    assert expected in auth.describe_auth(Settings(cookie_secure=value))


# ---------------------------------------------------------- bug-dash-auth-7

def _req(peer, xff, trusted="127.0.0.1,::1"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=headers,
        app=SimpleNamespace(state=SimpleNamespace(settings=Settings(trusted_proxies=trusted))),
    )


def test_an_appending_proxy_is_read_from_the_right():
    # nginx appended the real address after whatever the client sent.
    assert auth.client_ip(_req("127.0.0.1", "6.6.6.6, 100.64.1.2")) == "100.64.1.2"


def test_a_replacing_proxy_still_gives_its_one_address():
    assert auth.client_ip(_req("127.0.0.1", "100.64.1.2")) == "100.64.1.2"


def test_trusted_hops_on_the_right_are_walked_past():
    req = _req("127.0.0.1", "6.6.6.6, 100.64.1.2, 10.0.0.9", trusted="127.0.0.1,10.0.0.0/8")
    assert auth.client_ip(req) == "100.64.1.2"


def test_garbage_at_the_right_end_falls_back_to_the_peer():
    assert auth.client_ip(_req("127.0.0.1", "6.6.6.6, not-an-ip")) == "127.0.0.1"


def test_an_untrusted_peer_still_ignores_the_header():
    assert auth.client_ip(_req("192.0.2.5", "6.6.6.6")) == "192.0.2.5"


# ================================================= owed round (2026-09-25)
# ------------------------------------------------ ui-dash-static-3 (from d-ui)

@pytest.fixture
def admin_env(tmp_path):
    db_path = tmp_path / "undo-expected.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        as_user(client, "owen")
        yield client, conn
        conn.close()


def _two_saves(client, conn):
    """Two saves with DIFFERENT stamps: the admin's page loaded the first,
    a second tab (or a second admin) then saved again."""
    client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "Q:\\"}})
    first = dbmod.site_history(conn)[0]["at"]
    dbmod.record_site_change(conn, "maria", "save", {"canonical_prefix": "Q:\\"},
                             {"canonical_prefix": "R:\\"}, now="2099-01-01T00:00:00+00:00")
    site_store.set_many(conn, {"canonical_prefix": "R:\\"}, updated_by="maria")
    conn.commit()
    return first


def test_an_undo_of_a_change_that_is_no_longer_newest_is_refused(admin_env):
    # HEAD ignored the body and reverted entries[0], maria's R:, which the
    # admin never saw in the confirm.
    client, conn = admin_env
    confirmed = _two_saves(client, conn)
    history_before = dbmod.site_history(conn)
    resp = client.post("/api/v1/admin/site/undo-last-change", json={"expected_at": confirmed})
    assert resp.status_code == 409
    assert "reload the page" in resp.json()["detail"]
    assert client.get("/api/v1/admin/site").json()["canonical_prefix"] == "R:\\"
    assert dbmod.site_history(conn) == history_before


def test_an_undo_of_the_newest_change_it_names_goes_through(admin_env):
    client, conn = admin_env
    _two_saves(client, conn)
    newest = dbmod.site_history(conn)[0]["at"]
    resp = client.post("/api/v1/admin/site/undo-last-change", json={"expected_at": newest})
    assert resp.status_code == 200
    assert client.get("/api/v1/admin/site").json()["canonical_prefix"] == "Q:\\"


@pytest.mark.parametrize("body", [None, {}, {"expected_at": ""}, {"expected_at": None}])
def test_an_undo_with_no_expected_at_keeps_the_old_behaviour(admin_env, body):
    # An older page, the JSON door and test_site_history send no body.
    client, conn = admin_env
    _two_saves(client, conn)
    kwargs = {} if body is None else {"json": body}
    resp = client.post("/api/v1/admin/site/undo-last-change", **kwargs)
    assert resp.status_code == 200
    assert client.get("/api/v1/admin/site").json()["canonical_prefix"] == "Q:\\"


# ------------------------------------------------ ui-dash-admin-14 (from d-ui)

def test_setup_routes_names_the_undo_button_by_its_label():
    import inspect

    from ccsync_dashboard import setup_routes
    src = inspect.getsource(setup_routes)
    assert "UNDO LAST IMPORT" not in src
    assert src.count("[ UNDO LAST CHANGE ]") >= 3


# ------------------------------------------------------ ui-copy-6 (from d-ui)

def _visible_dashes(module_file):
    """Every ' -- ' inside a string that feeds an HTTP `detail`, a setup
    task's `description`/`detail`, or a JSONResponse body: text a browser
    shows. Docstrings, comments, log calls and SQL are not looked at."""
    import ast

    tree = ast.parse(open(module_file, encoding="utf-8").read())
    hits = []

    def strings(node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                yield sub

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in {"detail", "description"}:
            for c in strings(node.value):
                if " -- " in c.value:
                    hits.append((c.lineno, c.value))
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "detail":
                    for c in strings(v):
                        if " -- " in c.value:
                            hits.append((c.lineno, c.value))
    return hits


@pytest.mark.parametrize("name", ["setup_engine", "app", "oidc", "sessions",
                                  "setup_routes", "site_store"])
def test_visible_copy_in_the_auth_modules_has_no_typewriter_dash(name):
    import importlib

    mod = importlib.import_module(f"ccsync_dashboard.{name}")
    assert _visible_dashes(mod.__file__) == []


def test_the_exported_toml_header_has_no_typewriter_dash(admin_env):
    client, conn = admin_env
    text = client.get("/api/v1/admin/site/export").text
    assert text.startswith("# CC Sync site manifest")
    assert " -- " not in text.splitlines()[0]
