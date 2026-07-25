"""Identity module tests: token parsing/validity, the identity.json
round-trip, verify_credentials against an injected fake http_post (never
raises, even on HTTPError/network failure), and IdentityManager sign_in/
sign_out."""

from __future__ import annotations

import json
import time
import urllib.error

import pytest

from ccsync_companion import identity as identity_mod
from ccsync_companion.identity import (
    IdentityManager,
    is_valid,
    load_identity,
    parse_token,
    save_identity,
    verify_credentials,
)


def _token(username="alex", expires_epoch=None):
    if expires_epoch is None:
        expires_epoch = int(time.time()) + 3600
    return f"v1.{username}.{expires_epoch}.deadbeef"


# -- identity_path -----------------------------------------------


def test_identity_path_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    path = identity_mod.identity_path({})
    assert path == tmp_path / "identity.json"


# -- parse_token -----------------------------------------------


def test_parse_token_valid():
    username, expires = parse_token("v1.alex.1999999999.deadbeef")
    assert username == "alex"
    assert expires == 1999999999


def test_parse_token_malformed_too_few_parts():
    assert parse_token("v1.alex") == (None, None)


def test_parse_token_malformed_non_integer_expiry():
    assert parse_token("v1.alex.notanumber.deadbeef") == (None, None)


def test_parse_token_blank_username():
    assert parse_token("v1..1999999999.deadbeef") == (None, None)


def test_parse_token_none():
    assert parse_token(None) == (None, None)


def test_parse_token_empty_string():
    assert parse_token("") == (None, None)


# -- is_valid -----------------------------------------------


def test_is_valid_future_expiry():
    identity = {"username": "alex", "token": _token(expires_epoch=int(time.time()) + 100)}
    assert is_valid(identity) is True


def test_is_valid_expired():
    identity = {"username": "alex", "token": _token(expires_epoch=int(time.time()) - 100)}
    assert is_valid(identity) is False


def test_is_valid_none():
    assert is_valid(None) is False


def test_is_valid_empty_dict():
    assert is_valid({}) is False


def test_is_valid_missing_username():
    identity = {"token": _token()}
    assert is_valid(identity) is False


def test_is_valid_blank_username():
    identity = {"username": "  ", "token": _token()}
    assert is_valid(identity) is False


def test_is_valid_malformed_token():
    identity = {"username": "alex", "token": "not-a-real-token"}
    assert is_valid(identity) is False


def test_is_valid_honors_injected_clock():
    identity = {"username": "alex", "token": _token(expires_epoch=1000)}
    assert is_valid(identity, now=lambda: 500) is True
    assert is_valid(identity, now=lambda: 1500) is False


# -- save_identity / load_identity round-trip -----------------------------------------------


def test_save_and_load_identity_round_trip(tmp_path):
    path = tmp_path / "sub" / "identity.json"
    save_identity(path, "alex", _token())
    loaded = load_identity(path)
    assert loaded["username"] == "alex"
    assert loaded["token"] == _token()
    assert "verified_at" in loaded


def test_load_identity_missing_file_returns_none(tmp_path):
    assert load_identity(tmp_path / "nope.json") is None


def test_load_identity_malformed_json_returns_none(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text("not json {{{", encoding="utf-8")
    assert load_identity(path) is None


def test_load_identity_non_dict_json_returns_none(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_identity(path) is None


def test_load_identity_tolerates_utf8_bom(tmp_path):
    # Windows PowerShell Set-Content -Encoding utf8 writes a BOM; the read
    # must still parse (seen live on the base rig).
    path = tmp_path / "identity.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"username": "home", "token": "v1.home.9999999999.ab"}')
    data = load_identity(path)
    assert data is not None and data["username"] == "home"


def test_save_identity_overwrites_existing_file(tmp_path):
    path = tmp_path / "identity.json"
    save_identity(path, "alex", _token(username="alex"))
    save_identity(path, "ruskin", _token(username="ruskin"))
    loaded = load_identity(path)
    assert loaded["username"] == "ruskin"


# -- verify_credentials -----------------------------------------------


def test_verify_credentials_success():
    def fake_post(url, data, headers, timeout):
        assert url == "http://dash.example.com/api/v1/verify"
        assert data["username"] == "alex"
        assert data["password"] == "hunter2"
        # Upgrade channel: the verify request self-identifies so the server
        # can advertise a newer build in its response.
        assert data["companion_version"] == identity_mod.config_mod.VERSION
        assert data["platform"] in {"windows", "macos", "linux"}
        assert "Authorization" not in headers
        return {"ok": True, "username": "alex", "token": _token()}

    result = verify_credentials("http://dash.example.com", "alex", "hunter2", http_post=fake_post)
    assert result["ok"] is True
    assert result["username"] == "alex"
    assert result["token"] == _token()


def test_verify_credentials_strips_trailing_slash_from_url():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(url)
        return {"ok": True, "username": "alex", "token": _token()}

    verify_credentials("http://dash.example.com/", "alex", "hunter2", http_post=fake_post)
    assert calls[0] == "http://dash.example.com/api/v1/verify"


def test_verify_credentials_includes_role():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "alex", "token": _token(username="alex"), "role": "base"}

    result = verify_credentials("http://dash.example.com", "alex", "hunter2", http_post=fake_post)
    assert result["role"] == "base"


def test_verify_credentials_role_none_when_dashboard_omits_it():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "jsmith", "token": _token(username="jsmith")}

    result = verify_credentials("http://dash.example.com", "jsmith", "hunter2", http_post=fake_post)
    assert result["role"] is None


def test_verify_credentials_ok_false_response():
    def fake_post(url, data, headers, timeout):
        return {"ok": False, "error": "bad credentials"}

    result = verify_credentials("http://dash.example.com", "alex", "wrong", http_post=fake_post)
    assert result == {"ok": False, "error": "bad credentials"}


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body=b""):
        super().__init__("http://x", code, "err", {}, None)
        self._body = body

    def read(self):
        return self._body


def test_verify_credentials_401_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(401, json.dumps({"error": "bad username or password"}).encode())

    result = verify_credentials("http://dash.example.com", "alex", "wrong", http_post=fake_post)
    assert result["ok"] is False
    assert "error" in result


def test_verify_credentials_401_without_json_body_uses_default_message():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(401, b"")

    result = verify_credentials("http://dash.example.com", "alex", "wrong", http_post=fake_post)
    assert result["ok"] is False
    assert "invalid username or password" in result["error"]


def test_verify_credentials_429_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(429, b"")

    result = verify_credentials("http://dash.example.com", "alex", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "throttled" in result["error"] or "too many" in result["error"]


def test_verify_credentials_503_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(503, b"")

    result = verify_credentials("http://dash.example.com", "alex", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "not available" in result["error"]


def test_verify_credentials_network_error_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise OSError("network unreachable")

    result = verify_credentials("http://dash.example.com", "alex", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "network unreachable" in result["error"]


def test_verify_credentials_malformed_response_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        return "not a dict"

    result = verify_credentials("http://dash.example.com", "alex", "x", http_post=fake_post)
    assert result["ok"] is False


# -- IdentityManager -----------------------------------------------


def _mgr(tmp_path, monkeypatch, http_post=None, dashboard_url="http://dash.example.com"):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    cfg = {"dashboard_url": dashboard_url}
    kwargs = {}
    if http_post is not None:
        kwargs["http_post"] = http_post
    return IdentityManager(cfg, **kwargs)


def test_identity_manager_starts_signed_out_when_no_file(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    assert mgr.valid() is False
    assert mgr.username is None
    assert mgr.token is None


def test_identity_manager_loads_existing_valid_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    save_identity(tmp_path / "identity.json", "alex", _token(username="alex"))
    mgr = IdentityManager({"dashboard_url": "http://dash.example.com"})
    assert mgr.valid() is True
    assert mgr.username == "alex"


def test_identity_manager_sign_in_success_persists_and_updates_state(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "alex", "token": _token(username="alex")}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, error = mgr.sign_in("alex", "hunter2")
    assert ok is True
    assert error is None
    assert mgr.valid() is True
    assert mgr.username == "alex"
    assert mgr.token == _token(username="alex")

    # persisted to disk too.
    loaded = load_identity(tmp_path / "identity.json")
    assert loaded["username"] == "alex"


def test_identity_manager_sign_in_failure_does_not_persist(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": False, "error": "bad credentials"}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, error = mgr.sign_in("alex", "wrong")
    assert ok is False
    assert error == "bad credentials"
    assert mgr.valid() is False
    assert not (tmp_path / "identity.json").exists()


def test_identity_manager_sign_in_no_dashboard_url_configured(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, dashboard_url="")
    ok, error = mgr.sign_in("alex", "hunter2")
    assert ok is False
    assert "dashboard_url" in error


def test_identity_manager_sign_in_malformed_token_from_server_fails(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "alex", "token": "garbage"}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, error = mgr.sign_in("alex", "hunter2")
    assert ok is False
    assert mgr.valid() is False


def test_identity_manager_sign_out_clears_state_and_deletes_file(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "alex", "token": _token(username="alex")}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    mgr.sign_in("alex", "hunter2")
    assert mgr.valid() is True
    assert (tmp_path / "identity.json").exists()

    mgr.sign_out()
    assert mgr.valid() is False
    assert mgr.username is None
    assert not (tmp_path / "identity.json").exists()


def test_identity_manager_sign_out_when_never_signed_in_does_not_raise(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    mgr.sign_out()  # must not raise
    assert mgr.valid() is False


def test_identity_manager_sign_in_persists_and_exposes_role(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "alex", "token": _token(username="alex"), "role": "base"}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, _error = mgr.sign_in("alex", "hunter2")
    assert ok is True
    assert mgr.role == "base"

    loaded = load_identity(tmp_path / "identity.json")
    assert loaded["role"] == "base"

    # a fresh manager loading that same file also sees the role
    reloaded = IdentityManager({"dashboard_url": "http://dash.example.com"})
    assert reloaded.role == "base"


def test_identity_manager_role_none_when_not_signed_in_or_dashboard_omits_it(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    assert mgr.role is None  # never signed in

    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "jsmith", "token": _token(username="jsmith")}

    mgr2 = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    mgr2.sign_in("jsmith", "hunter2")
    assert mgr2.valid() is True
    assert mgr2.role is None  # signed in, but no role info from the dashboard
