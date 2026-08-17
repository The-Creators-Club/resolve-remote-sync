"""Identity module tests: token parsing/validity, the identity.json
round-trip, verify_credentials against an injected fake http_post (never
raises, even on HTTPError/network failure), and IdentityManager sign_in/
sign_out."""

from __future__ import annotations

import base64
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


def _b64u(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).rstrip(b"=").decode("ascii")


def _token(username="owen", expires_epoch=None, purpose="identity"):
    if expires_epoch is None:
        expires_epoch = int(time.time()) + 3600
    return f"v2.{purpose}.{_b64u(username)}.{expires_epoch}.deadbeef"


# -- identity_path -----------------------------------------------


def test_identity_path_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    path = identity_mod.identity_path({})
    assert path == tmp_path / "identity.json"


# -- parse_token -----------------------------------------------


def test_parse_token_valid():
    username, expires = parse_token(f"v2.identity.{_b64u('owen')}.1999999999.deadbeef")
    assert username == "owen"
    assert expires == 1999999999


def test_parse_token_valid_dotted_username_round_trips():
    # base64url-encoding the username means a dot in it (a valid TrueNAS-style
    # username character, e.g. "john.doe") can never be mistaken for a field
    # separator (see S-9).
    username, expires = parse_token(f"v2.identity.{_b64u('john.doe')}.1999999999.deadbeef")
    assert username == "john.doe"
    assert expires == 1999999999


def test_parse_token_malformed_too_few_parts():
    assert parse_token(f"v2.identity.{_b64u('owen')}") == (None, None)


def test_parse_token_malformed_non_integer_expiry():
    assert parse_token(f"v2.identity.{_b64u('owen')}.notanumber.deadbeef") == (None, None)


def test_parse_token_blank_username():
    assert parse_token("v2.identity..1999999999.deadbeef") == (None, None)


def test_parse_token_rejects_v1_format():
    assert parse_token("v1.owen.1999999999.deadbeef") == (None, None)


def test_parse_token_rejects_session_purpose():
    # A dashboard SESSION cookie must never be usable as a machine-identity
    # token (see SEC-1) -- parse_token only accepts purpose="identity".
    assert parse_token(f"v2.session.{_b64u('owen')}.1999999999.deadbeef") == (None, None)


def test_parse_token_none():
    assert parse_token(None) == (None, None)


def test_parse_token_empty_string():
    assert parse_token("") == (None, None)


# -- is_valid -----------------------------------------------


def test_is_valid_future_expiry():
    identity = {"username": "owen", "token": _token(expires_epoch=int(time.time()) + 100)}
    assert is_valid(identity) is True


def test_is_valid_expired():
    identity = {"username": "owen", "token": _token(expires_epoch=int(time.time()) - 100)}
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
    identity = {"username": "owen", "token": "not-a-real-token"}
    assert is_valid(identity) is False


def test_is_valid_honors_injected_clock():
    identity = {"username": "owen", "token": _token(expires_epoch=1000)}
    assert is_valid(identity, now=lambda: 500) is True
    assert is_valid(identity, now=lambda: 1500) is False


# -- save_identity / load_identity round-trip -----------------------------------------------


def test_save_and_load_identity_round_trip(tmp_path):
    path = tmp_path / "sub" / "identity.json"
    save_identity(path, "owen", _token())
    loaded = load_identity(path)
    assert loaded["username"] == "owen"
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
    save_identity(path, "owen", _token(username="owen"))
    save_identity(path, "editor2", _token(username="editor2"))
    loaded = load_identity(path)
    assert loaded["username"] == "editor2"


# -- verify_credentials -----------------------------------------------


def test_verify_credentials_success():
    def fake_post(url, data, headers, timeout):
        assert url == "http://dash.example.com/api/v1/verify"
        assert data["username"] == "owen"
        assert data["password"] == "hunter2"
        # Upgrade channel: the verify request self-identifies so the server
        # can advertise a newer build in its response.
        assert data["companion_version"] == identity_mod.config_mod.VERSION
        assert data["platform"] in {"windows", "macos", "linux"}
        assert "Authorization" not in headers
        return {"ok": True, "username": "owen", "token": _token()}

    result = verify_credentials("http://dash.example.com", "owen", "hunter2", http_post=fake_post)
    assert result["ok"] is True
    assert result["username"] == "owen"
    assert result["token"] == _token()


def test_verify_credentials_strips_trailing_slash_from_url():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(url)
        return {"ok": True, "username": "owen", "token": _token()}

    verify_credentials("http://dash.example.com/", "owen", "hunter2", http_post=fake_post)
    assert calls[0] == "http://dash.example.com/api/v1/verify"


def test_verify_credentials_includes_role():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": _token(username="owen"), "role": "base"}

    result = verify_credentials("http://dash.example.com", "owen", "hunter2", http_post=fake_post)
    assert result["role"] == "base"


def test_verify_credentials_role_none_when_dashboard_omits_it():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "jsmith", "token": _token(username="jsmith")}

    result = verify_credentials("http://dash.example.com", "jsmith", "hunter2", http_post=fake_post)
    assert result["role"] is None


def test_verify_credentials_ok_false_response():
    def fake_post(url, data, headers, timeout):
        return {"ok": False, "error": "bad credentials"}

    result = verify_credentials("http://dash.example.com", "owen", "wrong", http_post=fake_post)
    assert result == {"ok": False, "error": "bad credentials"}


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body=b""):
        super().__init__("http://x", code, "err", {}, None)
        self._body = body

    def read(self):
        return self._body


def test_verify_credentials_401_returns_ok_false():
    """The dashboard is FastAPI: every refusal on /api/v1/verify is an
    HTTPException, which serialises to {"detail": ...}. This test used to
    build a {"error": ...} body -- a shape the dashboard has never sent --
    which is what let the companion's own read of "error" look correct while
    the real, actionable sentence was dropped on every sign-in (B18)."""
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(401, json.dumps({"detail": "bad username or password"}).encode())

    result = verify_credentials("http://dash.example.com", "owen", "wrong", http_post=fake_post)
    assert result["ok"] is False
    assert result["error"] == "bad username or password"


def test_verify_credentials_surfaces_the_403_editors_group_message():
    """The single most likely first-run failure: a working NAS account that
    simply is not in the `editors` group. The dashboard answers with a
    one-line fix; the editor used to see "sign-in failed (HTTP 403)"."""
    detail = ("'rsmith' is not in the 'editors' group on the NAS -- ask an admin to "
              "add the account in Admin > Users")

    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(403, json.dumps({"detail": detail}).encode())

    result = verify_credentials("http://dash.example.com", "rsmith", "pw", http_post=fake_post)
    assert result["ok"] is False
    assert result["error"] == detail


def test_verify_credentials_403_without_a_body_still_says_what_to_do():
    """403 had NO entry in the fallback map, so an unreadable body produced
    the useless generic "sign-in failed (HTTP 403)"."""
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(403, b"")

    result = verify_credentials("http://dash.example.com", "rsmith", "pw", http_post=fake_post)
    assert "editors" in result["error"]
    assert "HTTP 403" not in result["error"]


def test_verify_credentials_still_accepts_a_legacy_error_body():
    """verify_credentials' own failure dicts use "error", and
    onboarding/steps.py renders both through the same helper -- so the old
    key stays supported, just second."""
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(401, json.dumps({"error": "legacy shape"}).encode())

    assert verify_credentials("http://dash.example.com", "owen", "x",
                              http_post=fake_post)["error"] == "legacy shape"


def test_a_pydantic_422_detail_list_is_not_shown_to_the_editor():
    """FastAPI's validation errors send `detail` as a LIST of error dicts.
    Rendering that at an editor is worse than the per-status fallback."""
    body = json.dumps({"detail": [{"loc": ["body", "username"], "msg": "field required"}]})

    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(422, body.encode())

    result = verify_credentials("http://dash.example.com", "owen", "x", http_post=fake_post)
    assert result["error"] == "sign-in failed (HTTP 422)"


def test_verify_credentials_401_without_json_body_uses_default_message():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(401, b"")

    result = verify_credentials("http://dash.example.com", "owen", "wrong", http_post=fake_post)
    assert result["ok"] is False
    assert "invalid username or password" in result["error"]


def test_verify_credentials_429_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(429, b"")

    result = verify_credentials("http://dash.example.com", "owen", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "throttled" in result["error"] or "too many" in result["error"]


def test_verify_credentials_503_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(503, b"")

    result = verify_credentials("http://dash.example.com", "owen", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "not available" in result["error"]


def test_verify_credentials_network_error_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise OSError("network unreachable")

    result = verify_credentials("http://dash.example.com", "owen", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "network unreachable" in result["error"]


def test_verify_credentials_malformed_response_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        return "not a dict"

    result = verify_credentials("http://dash.example.com", "owen", "x", http_post=fake_post)
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
    save_identity(tmp_path / "identity.json", "owen", _token(username="owen"))
    mgr = IdentityManager({"dashboard_url": "http://dash.example.com"})
    assert mgr.valid() is True
    assert mgr.username == "owen"


def test_identity_manager_sign_in_success_persists_and_updates_state(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": _token(username="owen")}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, error = mgr.sign_in("owen", "hunter2")
    assert ok is True
    assert error is None
    assert mgr.valid() is True
    assert mgr.username == "owen"
    assert mgr.token == _token(username="owen")

    # persisted to disk too.
    loaded = load_identity(tmp_path / "identity.json")
    assert loaded["username"] == "owen"


def test_identity_manager_sign_in_failure_does_not_persist(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": False, "error": "bad credentials"}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, error = mgr.sign_in("owen", "wrong")
    assert ok is False
    assert error == "bad credentials"
    assert mgr.valid() is False
    assert not (tmp_path / "identity.json").exists()


def test_identity_manager_sign_in_no_dashboard_url_configured(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, dashboard_url="")
    ok, error = mgr.sign_in("owen", "hunter2")
    assert ok is False
    assert "dashboard_url" in error


def test_identity_manager_sign_in_malformed_token_from_server_fails(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": "garbage"}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, error = mgr.sign_in("owen", "hunter2")
    assert ok is False
    assert mgr.valid() is False


def test_identity_manager_sign_out_clears_state_and_deletes_file(tmp_path, monkeypatch):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "owen", "token": _token(username="owen")}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    mgr.sign_in("owen", "hunter2")
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
        return {"ok": True, "username": "owen", "token": _token(username="owen"), "role": "base"}

    mgr = _mgr(tmp_path, monkeypatch, http_post=fake_post)
    ok, _error = mgr.sign_in("owen", "hunter2")
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


# -- plaintext sign-in warning (AUDIT_3 L-13) -------------------------------


@pytest.fixture
def _reset_plaintext_warning(monkeypatch):
    monkeypatch.setattr(identity_mod, "_PLAINTEXT_WARNED", False)
    yield


def _ok_post(url, data, headers, timeout):
    return {"ok": True, "username": "owen", "token": _token()}


def test_http_signin_to_a_remote_host_warns_once(caplog, _reset_plaintext_warning):
    """NOT a refusal: the deployment is http over the tailnet by design, and
    refusing would lock every editor out to fix a risk the tailnet already
    bounds. But a TrueNAS password crossing the wire in clear must not be
    invisible either -- the fix is TLS on the dashboard."""
    with caplog.at_level("WARNING", logger="ccsync.identity"):
        verify_credentials("http://100.64.0.1:8480", "owen", "hunter2", http_post=_ok_post)
        verify_credentials("http://100.64.0.1:8480", "owen", "hunter2", http_post=_ok_post)

    warnings = [r for r in caplog.records if "plain HTTP" in r.message]
    assert len(warnings) == 1, "one note, not one per sign-in attempt"
    # ...and it still signs in.
    assert verify_credentials(
        "http://100.64.0.1:8480", "owen", "hunter2", http_post=_ok_post
    )["ok"] is True


def test_no_plaintext_warning_for_https_or_loopback(caplog, _reset_plaintext_warning):
    with caplog.at_level("WARNING", logger="ccsync.identity"):
        verify_credentials("https://dash.example.com", "owen", "x", http_post=_ok_post)
        verify_credentials("http://127.0.0.1:8480", "owen", "x", http_post=_ok_post)
        verify_credentials("http://localhost:8480", "owen", "x", http_post=_ok_post)

    assert not [r for r in caplog.records if "plain HTTP" in r.message]


def test_plaintext_check_never_raises(_reset_plaintext_warning):
    identity_mod._warn_if_plaintext(None)
    identity_mod._warn_if_plaintext(5)
    identity_mod._warn_if_plaintext("")


# -- the report token /api/v1/verify hands back (cross-component minor) ------


def _verify_ok(report_token="fresh-token", username="owen"):
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": username, "token": _token(username=username),
                "role": "editor", "report_token": report_token}
    return fake_post


def test_verify_credentials_returns_the_report_token():
    """/api/v1/verify has always returned `report_token` (dashboard api.py)
    and onboarding consumes it, but this module dropped it -- so a tray
    sign-in on a machine with a stale config.toml `dashboard_token` succeeded
    and then 401'd every single report, forever."""
    result = verify_credentials("http://dash.example.com", "owen", "pw",
                                http_post=_verify_ok())
    assert result["report_token"] == "fresh-token"


def test_sign_in_publishes_the_report_token_into_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    cfg = {"dashboard_url": "http://dash.example.com", "dashboard_token": "STALE"}
    mgr = identity_mod.IdentityManager(cfg, http_post=_verify_ok())
    ok, error = mgr.sign_in("owen", "pw")
    assert ok is True and error is None
    assert mgr.report_token == "fresh-token"
    # the one dict every consumer reads from now carries the fresh token
    assert cfg["dashboard_token"] == "fresh-token"


def test_the_report_token_survives_a_restart(tmp_path, monkeypatch):
    """config.toml is written by the installer, not by the running companion,
    so identity.json is where the freshest token lives -- and it has to be
    republished into cfg before the reporter is built."""
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    identity_mod.IdentityManager(
        {"dashboard_url": "http://d", "dashboard_token": "STALE"},
        http_post=_verify_ok()).sign_in("owen", "pw")

    restarted_cfg = {"dashboard_url": "http://d", "dashboard_token": "STALE"}
    mgr = identity_mod.IdentityManager(restarted_cfg)
    assert restarted_cfg["dashboard_token"] == "fresh-token"
    assert mgr.report_token == "fresh-token"


def test_an_older_dashboard_without_a_report_token_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(identity_mod.config_mod, "CONFIG_DIR", tmp_path)
    cfg = {"dashboard_url": "http://d", "dashboard_token": "CONFIGURED"}
    mgr = identity_mod.IdentityManager(cfg, http_post=_verify_ok(report_token=None))
    assert mgr.sign_in("owen", "pw")[0] is True
    assert cfg["dashboard_token"] == "CONFIGURED"
    assert mgr.report_token is None
