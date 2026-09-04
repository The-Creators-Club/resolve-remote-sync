"""The wizard offering its SSH public key to the dashboard (OPS-2, wave 5 of
the usability + resilience sweep, 2026-09-04).

Creating an editor account used to REQUIRE the key this wizard generates, and
the wizard cannot run until the account exists. The account can be created
without one now; this is the other half -- the key goes up under the identity
token verify_account has just returned, into a queue an admin approves in one
click.

It is a courtesy, never a gate: every failure here has to come back as
{"ok": False} so a dashboard too old to have the route cannot turn a
successful install into a failed one.
"""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import steps  # noqa: E402

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample jsmith@edit-pc"


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body=b"{}"):
        super().__init__("http://dash.example.com", code, "err", {}, None)
        self._body = body

    def read(self):
        return self._body


def test_the_key_goes_up_with_the_identity_token():
    seen = {}

    def fake_post(url, data, headers, timeout):
        seen.update(url=url, data=data, headers=headers)
        return {"ok": True, "pending": True, "fingerprint": "SHA256:abc"}

    result = steps.submit_ssh_key("http://dash.example.com", "jsmith", "v1.jsmith.9.abc",
                                  KEY, "EDIT-PC", http_post=fake_post)
    assert result["ok"] is True
    assert result["fingerprint"] == "SHA256:abc"
    assert seen["url"] == "http://dash.example.com/api/v1/ssh-key"
    assert seen["headers"]["X-CCSync-Identity"] == "v1.jsmith.9.abc"
    assert seen["data"] == {"username": "jsmith", "ssh_pubkey": KEY, "machine": "EDIT-PC"}


def test_a_trailing_slash_and_a_scheme_less_url_both_work():
    seen = {}

    def fake_post(url, data, headers, timeout):
        seen["url"] = url
        return {"ok": True}

    steps.submit_ssh_key("http://dash.example.com/", "jsmith", "t", KEY, http_post=fake_post)
    assert seen["url"] == "http://dash.example.com/api/v1/ssh-key"


def test_no_identity_token_means_no_post_at_all():
    def fake_post(url, data, headers, timeout):        # pragma: no cover
        raise AssertionError("must not be called without an identity token")

    result = steps.submit_ssh_key("http://dash.example.com", "jsmith", "", KEY,
                                  http_post=fake_post)
    assert result["ok"] is False


def test_no_key_means_no_post_at_all():
    def fake_post(url, data, headers, timeout):        # pragma: no cover
        raise AssertionError("must not be called with nothing to send")

    result = steps.submit_ssh_key("http://dash.example.com", "jsmith", "t", "   ",
                                  http_post=fake_post)
    assert result["ok"] is False


def test_an_older_dashboard_404s_and_the_install_carries_on():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(404, json.dumps({"detail": "Not Found"}).encode())

    result = steps.submit_ssh_key("http://dash.example.com", "jsmith", "t", KEY,
                                  http_post=fake_post)
    assert result["ok"] is False
    assert result["error"]


def test_a_transport_failure_never_raises():
    def fake_post(url, data, headers, timeout):
        raise OSError("connection reset")

    result = steps.submit_ssh_key("http://dash.example.com", "jsmith", "t", KEY,
                                  http_post=fake_post)
    assert result == {"ok": False, "error": "connection reset"}


def test_a_refusal_body_is_not_read_as_success():
    def fake_post(url, data, headers, timeout):
        return {"ok": False, "detail": "this account is suspended"}

    assert steps.submit_ssh_key("http://dash.example.com", "jsmith", "t", KEY,
                                http_post=fake_post)["ok"] is False
