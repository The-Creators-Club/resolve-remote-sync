"""internal_sftp.py: what the sftp sidecar's AuthorizedKeysCommand calls
(WP C, docs/ZERO_TOUCH_PLAN.md §3.3/§4 row C, 2026-08-17). Not under
/api/v1, not behind the session -- gated on a bearer token instead.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from ccsync_dashboard import db as dbmod, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

STRONG = "kX9-quiet-harbour-42-zephyr"
TOKEN = "sidecar-bearer-token-abcdef123456"
KEY = "ssh-ed25519 QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE= jsmith@laptop"


def _settings(tmp_path, **kwargs) -> Settings:
    base = dict(db_path=str(tmp_path / "sftp.db"), session_secret=STRONG,
               auth_method="local", internal_token=TOKEN)
    base.update(kwargs)
    return Settings(**base)


def _seed(settings, *, with_key: bool = True, disabled: bool = False) -> None:
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    if with_key:
        local_users.add_ssh_key(conn, "jsmith", KEY, label="laptop")
    if disabled:
        local_users.disable_user(conn, "jsmith", True)
    conn.commit()
    conn.close()


def test_users_requires_bearer_token(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings)
    with TestClient(create_app(settings)) as c:
        assert c.get("/internal/sftp/users").status_code == 401
        assert c.get("/internal/sftp/users",
                     headers={"Authorization": "Bearer wrong-token"}).status_code == 401
        resp = c.get("/internal/sftp/users", headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200
        assert resp.json() == {"users": [{"username": "jsmith", "uid": resp.json()["users"][0]["uid"],
                                          "gid": resp.json()["users"][0]["gid"]}]}


def test_users_excludes_disabled_and_keyless_accounts(tmp_path):
    settings = _settings(tmp_path)
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    local_users.add_ssh_key(conn, "jsmith", KEY)
    local_users.create_user(conn, "nokey", "correct-horse-battery-staple", "editor")
    local_users.create_user(conn, "disabled", "correct-horse-battery-staple", "editor")
    local_users.add_ssh_key(conn, "disabled", KEY)
    local_users.disable_user(conn, "disabled", True)
    conn.commit()
    conn.close()
    with TestClient(create_app(settings)) as c:
        resp = c.get("/internal/sftp/users", headers={"Authorization": f"Bearer {TOKEN}"})
        usernames = {u["username"] for u in resp.json()["users"]}
        assert usernames == {"jsmith"}


def test_keys_returns_plaintext_authorized_keys(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings)
    with TestClient(create_app(settings)) as c:
        resp = c.get("/internal/sftp/keys/jsmith", headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert resp.text == KEY + "\n"


def test_keys_unknown_or_disabled_user_404(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, disabled=True)
    with TestClient(create_app(settings)) as c:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert c.get("/internal/sftp/keys/jsmith", headers=headers).status_code == 404
        assert c.get("/internal/sftp/keys/ghost", headers=headers).status_code == 404


def test_keys_requires_bearer_token(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings)
    with TestClient(create_app(settings)) as c:
        assert c.get("/internal/sftp/keys/jsmith").status_code == 401


def test_unconfigured_token_answers_503(tmp_path):
    settings = _settings(tmp_path, internal_token="")
    _seed(settings)
    with TestClient(create_app(settings)) as c:
        resp = c.get("/internal/sftp/users", headers={"Authorization": "Bearer whatever"})
        assert resp.status_code == 503


def test_token_falls_back_to_secrets_file(tmp_path):
    """CCSYNC_INTERNAL_TOKEN unset -- agent D's SetupEngine wrote the token
    to <data dir>/secrets/internal_token instead; this module only reads it."""
    settings = _settings(tmp_path, internal_token="")
    _seed(settings)
    secrets_dir = settings.secrets_path("internal_token").parent
    secrets_dir.mkdir(parents=True, exist_ok=True)
    settings.secrets_path("internal_token").write_text("file-token-xyz\n", encoding="utf-8")
    with TestClient(create_app(settings)) as c:
        assert c.get("/internal/sftp/users",
                     headers={"Authorization": "Bearer wrong"}).status_code == 401
        resp = c.get("/internal/sftp/users",
                     headers={"Authorization": "Bearer file-token-xyz"})
        assert resp.status_code == 200


def test_no_login_session_required(tmp_path):
    """Not behind the session gate -- app.py's login_gate lets it straight
    through to the bearer check, with no cookie in play at all."""
    settings = _settings(tmp_path)
    _seed(settings)
    with TestClient(create_app(settings)) as c:
        assert "ccsync_session" not in c.cookies
        resp = c.get("/internal/sftp/users", headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200
