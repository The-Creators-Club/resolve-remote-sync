r"""tools/ui_variant.py -- the look's rollback control that renders no terminal
page (docs/UI_REDESIGN_PORT_PLAN.md R24). No network: a fake transport records
what would have been sent, as test_jobs_cli.py does."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

import jobs as jobs_cli  # noqa: E402
import ui_variant as tool  # noqa: E402

URL = "http://dash.example:8480"


class FakeHttp:
    def __init__(self):
        self.sent = []

    def send(self, method, url, headers=None, body=None):
        self.sent.append((method, url, dict(headers or {}), body))
        if url.endswith("/api/v1/login"):
            return jobs_cli.Response(200, {}, json.dumps({"is_admin": True, "csrf": "tok"}).encode())
        return jobs_cli.Response(200, {}, json.dumps({"ui_terminal_groups": "none",
                                                  "ui_preview": "off"}).encode())


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "stdin", io.StringIO("pw\n"))
    http = FakeHttp()
    code = tool.main(["--dashboard-url", URL, "--admin-user", "owen", "--password-stdin",
                      *argv], http=http)
    return code, http


def test_off_sends_exactly_none_with_the_csrf_token(monkeypatch):
    code, http = run(monkeypatch, "off")
    assert code == 0
    method, url, headers, body = http.sent[-1]
    assert (method, url) == ("PUT", f"{URL}/api/v1/admin/site")
    assert json.loads(body) == {"values": {"ui_terminal_groups": "none"}}
    assert headers["X-CSRF-Token"] == "tok"


def test_site_deletes_the_row(monkeypatch):
    _code, http = run(monkeypatch, "site")
    assert json.loads(http.sent[-1][3]) == {"values": {"ui_terminal_groups": "site"}}


def test_a_set_without_chrome_is_refused_before_any_request(monkeypatch):
    code, http = run(monkeypatch, "set", "home")
    assert code == jobs_cli.EXIT_USAGE and http.sent == []


def test_a_set_is_normalised_to_group_order(monkeypatch):
    _code, http = run(monkeypatch, "set", "home,chrome")
    assert json.loads(http.sent[-1][3]) == {"values": {"ui_terminal_groups": "chrome,home"}}


def test_preview_modes(monkeypatch):
    _code, http = run(monkeypatch, "preview", "admins")
    assert json.loads(http.sent[-1][3]) == {"values": {"ui_preview": "admins"}}
    code, http = run(monkeypatch, "preview", "sometimes")
    assert code == jobs_cli.EXIT_USAGE and http.sent == []


def test_the_password_never_reaches_argv():
    parser = tool.build_parser()
    assert not any("password" == a.dest for a in parser._actions)


def test_every_font_family_is_named_in_the_notices_block():
    """2.3: gen_notices reads the hand block back verbatim, so the fonts are
    named in THIRD_PARTY_NOTICES.md itself."""
    repo = TOOLS.parent
    text = (repo / "docs" / "legal" / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    block = text.rsplit("<!-- BEGIN HAND-MAINTAINED -->", 1)[1].split("<!-- END HAND-MAINTAINED -->", 1)[0]
    fonts = sorted((repo / "dashboard" / "static" / "fonts").glob("*.woff2"))
    assert fonts
    for p in fonts:
        family = "JetBrains Mono" if p.name.startswith("jetbrains") else "Orbitron"
        assert family in block and p.name in block, p.name
