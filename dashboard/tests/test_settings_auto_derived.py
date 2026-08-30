"""Settings -> the three AUTO_DERIVED_KEYS, and when they may actually be
greyed out (CR-follow-up, 2026-08-30, the owner: "it won't let me change the
dashboard url").

Before this: `admin_settings.html` greyed a field out whenever it was in
`site_store.AUTO_DERIVED_KEYS` AND the DB row had EVER been given any value
-- which every one of them had, from the very first boot's env seed. Nothing
about a stored value means a live source is deriving it today. The fix is
`ui._live_auto_derived_values`: a bounded, fail-open check per key, read only
when a live value is ACTUALLY available right now.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import tailscale_local, ui
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def _make_env(tmp_path, monkeypatch, **settings_kwargs):
    """Settings is a frozen dataclass -- every knob a test needs goes into
    the constructor, never `monkeypatch.setattr(settings, ...)`."""
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: False)
    db_path = tmp_path / "settings.db"
    settings = Settings(
        db_path=str(db_path), session_secret=SECRET,
        admin_users=frozenset({"owen"}), **settings_kwargs,
    )
    app = create_app(settings)
    client = TestClient(app)
    client.__enter__()
    conn = dbmod.connect(db_path)
    as_user(client, "owen")
    return client, conn, settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    # No live source of any kind, by default: no Tailscale socket (S1's own
    # rule -- Path.exists() on a socket that is not there), no Syncthing URL
    # configured. This is every vendor-build deployment, and Alex's.
    client, conn, settings = _make_env(tmp_path, monkeypatch)
    yield client, conn, settings
    conn.close()
    client.__exit__(None, None, None)


def test_dashboard_url_is_editable_with_no_live_source_even_with_a_stored_value(env):
    """The exact bug: a DB row that has a value (from months ago, or the
    first-boot env seed) must not lock the field forever on its own."""
    client, conn, settings = env
    client.put("/api/v1/admin/site",
               json={"values": {"dashboard_url": "http://100.71.216.3:8480"}})
    body = client.get("/admin/settings").text
    assert 'name="dashboard_url"' in body
    field = body[body.index('name="dashboard_url"'):]
    assert "readonly" not in field[:200], field[:200]
    assert "auto-derived" not in body[:body.index('name="dashboard_url"')][-200:]


def test_sftp_host_is_never_auto_derived_no_matter_what(env, monkeypatch):
    """WP C's SFTP sidecar has no outbound status route in this repo -- no
    live source exists, so this key is never greyed, even if someone points
    Syncthing and Tailscale both at something live (which is unrelated to
    it, but proves the per-key check does not leak into a global switch)."""
    client, conn, settings = env
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: True)
    monkeypatch.setattr(tailscale_local, "status", lambda *a, **k: {
        "BackendState": "Running", "AuthURL": "",
        "Self": {"DNSName": "studio.tail1234.ts.net."}, "TailscaleIPs": []})
    client.put("/api/v1/admin/site", json={"values": {"sftp_host": "10.0.0.5"}})
    body = client.get("/admin/settings").text
    field = body[body.index('name="sftp_host"'):]
    assert "readonly" not in field[:200], field[:200]


def test_dashboard_url_greys_out_when_tailscale_is_actually_signed_in(env, monkeypatch):
    """The positive case: a live WP B sidecar, signed in, DOES grey the field
    -- and says why, so an admin who cannot edit it is told what to turn off
    first rather than left guessing."""
    client, conn, settings = env
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: True)
    monkeypatch.setattr(tailscale_local, "status", lambda *a, **k: {
        "BackendState": "Running", "AuthURL": "",
        "Self": {"DNSName": "studio.tail1234.ts.net."}, "TailscaleIPs": []})
    body = client.get("/admin/settings").text
    field = body[body.index('name="dashboard_url"'):]
    assert "readonly" in field[:200], field[:200]
    assert "studio.tail1234.ts.net" in body


def test_dashboard_url_stays_editable_when_tailscale_is_not_signed_in_yet(env, monkeypatch):
    """A socket present but not signed in (NeedsLogin) is not a live VALUE --
    there is nothing to derive dashboard_url FROM yet."""
    client, conn, settings = env
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: True)
    monkeypatch.setattr(tailscale_local, "status", lambda *a, **k: {
        "BackendState": "NeedsLogin", "AuthURL": "https://login.tailscale.com/a/x",
        "Self": {"DNSName": ""}, "TailscaleIPs": []})
    body = client.get("/admin/settings").text
    field = body[body.index('name="dashboard_url"'):]
    assert "readonly" not in field[:200], field[:200]


def test_a_tailscale_localapi_read_that_raises_leaves_the_field_editable(env, monkeypatch):
    """Fails OPEN, not closed: a status page an admin is looking at must
    never lock a field because a probe blew up."""
    client, conn, settings = env
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: True)

    def boom(*a, **k):
        raise OSError("socket refused")
    monkeypatch.setattr(tailscale_local, "status", boom)
    body = client.get("/admin/settings").text
    field = body[body.index('name="dashboard_url"'):]
    assert "readonly" not in field[:200], field[:200]


class _FakeSyncthingClient:
    def __init__(self, my_id):
        self.timeout = 10.0
        self._my_id = my_id

    def system_status(self):
        return {"myID": self._my_id}


def test_nas_syncthing_id_greys_out_when_syncthing_answers_a_device_id(tmp_path, monkeypatch):
    client, conn, settings = _make_env(tmp_path, monkeypatch,
                                       syncthing_url="http://127.0.0.1:8384")
    monkeypatch.setattr(
        ui.SyncthingClient, "from_settings",
        classmethod(lambda cls, s, session=None: _FakeSyncthingClient("ABCDEFG-1234567")))
    body = client.get("/admin/settings").text
    field = body[body.index('name="nas_syncthing_id"'):]
    assert "readonly" in field[:200], field[:200]
    assert "ABCDEFG" in body
    conn.close()
    client.__exit__(None, None, None)


def test_nas_syncthing_id_stays_editable_with_no_syncthing_url_configured(env):
    """The common case (no SYNCTHING_GUI_URL at all) must not even attempt a
    connection -- see the bounded-check tests in test_setup_engine.py for the
    same rule on the setup wizard's identical call."""
    client, conn, settings = env
    body = client.get("/admin/settings").text
    field = body[body.index('name="nas_syncthing_id"'):]
    assert "readonly" not in field[:200], field[:200]


def test_nas_syncthing_id_stays_editable_when_syncthing_is_unreachable(tmp_path, monkeypatch):
    client, conn, settings = _make_env(tmp_path, monkeypatch,
                                       syncthing_url="http://127.0.0.1:8384")

    class _Boom:
        def __init__(self):
            self.timeout = 10.0

        def system_status(self):
            raise RuntimeError("connection refused")
    monkeypatch.setattr(
        ui.SyncthingClient, "from_settings",
        classmethod(lambda cls, s, session=None: _Boom()))
    body = client.get("/admin/settings").text
    field = body[body.index('name="nas_syncthing_id"'):]
    assert "readonly" not in field[:200], field[:200]
    conn.close()
    client.__exit__(None, None, None)


# ------------------------------------------------------------- the env hint

def test_the_env_value_shows_as_a_hint_when_it_differs_from_the_db_row(tmp_path, monkeypatch):
    """Found the same night: DASH_SITE_DASHBOARD_URL carried the tailnet URL
    while the DB row held an old LAN IP -- the field showed the DB row (as
    site_store's own "the DB wins" rule says it must) and gave no sign the
    env disagreed at all."""
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: False)
    db_path = tmp_path / "settings.db"
    settings = Settings(
        db_path=str(db_path), session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        site_dashboard_url="https://truenas.tail26290e.ts.net:9443",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        as_user(client, "owen")
        client.put("/api/v1/admin/site",
                  json={"values": {"dashboard_url": "http://100.71.216.3:8480"}})
        body = client.get("/admin/settings").text
        conn.close()
    assert "http://100.71.216.3:8480" in body       # the DB row is what shows
    # ...and the env is visible too, named as what it is
    assert "DASH_SITE_DASHBOARD_URL" in body
    assert "https://truenas.tail26290e.ts.net:9443" in body


def test_no_hint_when_the_env_and_the_db_row_agree(tmp_path, monkeypatch):
    monkeypatch.setattr(tailscale_local, "socket_present", lambda *a, **k: False)
    db_path = tmp_path / "settings.db"
    settings = Settings(
        db_path=str(db_path), session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        site_dashboard_url="http://100.71.216.3:8480",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        as_user(client, "owen")
        client.put("/api/v1/admin/site",
                  json={"values": {"dashboard_url": "http://100.71.216.3:8480"}})
        body = client.get("/admin/settings").text
        conn.close()
    assert "DASH_SITE_DASHBOARD_URL" not in body


def test_a_writable_auto_derived_field_can_actually_be_saved(env):
    """The whole point: the readonly attribute was the only thing stopping
    it, and PUT /api/v1/admin/site never refused these keys server-side --
    proving the fix is complete once the UI stops blocking the click."""
    client, conn, settings = env
    r = client.put("/api/v1/admin/site",
                   json={"values": {"dashboard_url": "https://new.example.ts.net"}})
    assert r.status_code == 200, r.text
    body = client.get("/admin/settings").text
    assert "https://new.example.ts.net" in body
