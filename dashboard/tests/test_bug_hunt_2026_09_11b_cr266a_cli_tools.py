"""CR-266a: the CLI wizard's install route answered a bare 500 once, live.

2026-09-10 06:55Z the live dashboard recorded exactly one `server_error`
notice, "/api/v1/admin/ai-providers/claude_code/install (TypeError)", when the
admin clicked the Claude Code SET UP wizard. The traceback is gone (image mode
keeps `/data` across a recreate and does not keep the container's log), so this
file holds down the two halves that can be held down without it:

* **`install_supported` never raises**, which is its documented contract and
  what both its callers - the wizard's render and the install route's request
  thread - depend on. A check that cannot COMPLETE is a refusal naming the
  exception type, never an accidental yes.
* **an unforeseen fault on this route is a 503 with a sentence in it**, not
  `{"detail": "internal error"}`, and the operator still gets the
  `server_error` notice and the traceback in the log.

What is deliberately NOT claimed here: that the original TypeError is
reproduced. Every shape the publishers' APIs can answer with was driven
through `_install_claude` / `_install_codex` (a manifest that is null, a list,
`platforms: null`, a `size` that is null / a string / a dict, a `checksum`
that is a number, a `binary` that is null or a number, a release whose
`assets` is null, an asset whose name is a number, a checksums file that is
not text) and every one of them is a ToolError refusal already - and those run
in the install THREAD, whose failures become a status and can never be a 500.
The last two cases below pin the publisher-shape half so it stays that way,
and the checksum CONDITION (trust-model-7) with it.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import ai_providers, auth, cli_tools
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
ADMIN = "owen"
ROUTE = "/api/v1/admin/ai-providers"
INSTALL = ROUTE + "/claude_code/install"


@pytest.fixture(autouse=True)
def _cold_module_state():
    """Every latch in cli_tools is a process global."""
    cli_tools._install_status.clear()
    cli_tools._install_running = ""
    cli_tools._signin = None
    cli_tools._signin_last.clear()
    ai_providers.reset_probe_cache()
    yield
    cli_tools._install_status.clear()
    cli_tools._install_running = ""
    cli_tools._signin = None
    cli_tools._signin_last.clear()
    ai_providers.reset_probe_cache()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                    admin_users=frozenset({ADMIN}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(db_path=str(tmp_path / "ai.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "ai.db")
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        conn.execute(
            "INSERT INTO site_settings (key, value, updated_at, updated_by) "
            "VALUES ('features.ai_cli_providers','1','now','test') "
            "ON CONFLICT(key) DO UPDATE SET value='1'")
        conn.commit()
        yield client, conn, settings
        conn.close()


def _linux(monkeypatch):
    """The container's answer to the platform question, on a Windows or macOS
    dev box: without it every install refuses before it reaches the code under
    test here."""
    monkeypatch.setattr(cli_tools, "platform_key",
                        lambda machine=None, system=None: "linux-x64")


# ------------------------------------------------- install_supported's contract

def test_a_space_check_that_raises_is_a_refusal_not_a_traceback(settings, monkeypatch):
    """`install_supported` promises never to raise. The one failure it caught
    was UnsupportedPlatform, so a `space_refusal` whose signature has drifted
    - a TypeError raised AT the call site, which that function's own
    try/except cannot see - went out of the install route as a 500."""
    _linux(monkeypatch)
    from ccsync_dashboard import dashboard_update

    monkeypatch.setattr(dashboard_update, "space_refusal",
                        lambda settings, declared: "")     # the pre-REL-7 shape
    ok, why = cli_tools.install_supported(settings, "claude_code")
    assert ok is False
    # Names the tool, the kind of failure and the fallback the trust model
    # keeps for it. And it is a refusal: an unverified check is not checked.
    assert "TypeError" in why
    assert "Claude Code" in why
    assert "full path" in why


def test_a_data_volume_with_no_path_is_a_refusal_not_a_traceback(monkeypatch):
    """`Path(settings.db_path)` is the first thing the room check does, so a
    settings object carrying None reached `TypeError: argument should be a
    str` on the request thread."""
    _linux(monkeypatch)

    class Broken:
        db_path = None

    ok, why = cli_tools.install_supported(Broken(), "codex")
    assert ok is False
    assert "TypeError" in why and "Codex" in why


def test_the_install_route_refuses_instead_of_500ing_when_the_room_check_breaks(
        env, monkeypatch):
    _linux(monkeypatch)
    from ccsync_dashboard import dashboard_update

    monkeypatch.setattr(dashboard_update, "space_refusal",
                        lambda settings, declared: "")
    client, _conn, _settings = env
    resp = client.post(INSTALL)
    assert resp.status_code == 400
    assert "TypeError" in resp.json()["detail"]


# ------------------------------------------------ the route's own last resort

def test_an_unforeseen_fault_is_a_503_with_a_sentence(env, monkeypatch):
    """THE CR-266a shape, from the admin's side: whatever raised, the answer
    is not `{"detail": "internal error"}`."""
    _linux(monkeypatch)
    client, conn, _settings = env

    def boom(settings, name):
        raise TypeError("unsupported operand type(s) for /: 'int' and 'NoneType'")

    monkeypatch.setattr(cli_tools, "start_install", boom)
    resp = client.post(INSTALL)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "Claude Code" in detail and "TypeError" in detail
    assert "full path" in detail
    # Nothing derived from the exception's MESSAGE crosses: a sign-in
    # transcript and a download URL both pass through this module.
    assert "unsupported operand" not in detail
    assert "—" not in detail          # house style: no em dash in what an admin reads
    # The operator still learns about it: taking the request out of app.py's
    # unhandled-exception handler is what used to write this row.
    row = conn.execute(
        "SELECT subject FROM notices WHERE kind = 'server_error'").fetchone()
    assert row is not None
    assert "TypeError" in row["subject"]


def test_a_failing_remove_on_the_same_path_answers_the_same_way(env, monkeypatch):
    """`record_server_error` keys on (path, exception class) and never carried
    the method, so DELETE on this path is as likely an origin as the POST."""
    _linux(monkeypatch)
    client, _conn, _settings = env

    def boom(settings, name):
        raise TypeError("rmtree got a non-path")

    monkeypatch.setattr(cli_tools, "remove_install", boom)
    resp = client.delete(INSTALL)
    assert resp.status_code == 503
    assert "remove the install of Claude Code" in resp.json()["detail"]


def test_a_refusal_is_still_a_400_and_a_busy_install_still_a_409(env, monkeypatch):
    """The last-resort handler must not swallow the refusals that already have
    words: ToolError stays 400 and ToolBusy stays 409."""
    _linux(monkeypatch)
    client, _conn, _settings = env

    def refuse(settings, name):
        raise cli_tools.ToolError("no room on the data volume")

    monkeypatch.setattr(cli_tools, "start_install", refuse)
    assert client.post(INSTALL).status_code == 400

    def busy(settings, name):
        raise cli_tools.ToolBusy("an install of Codex is already running")

    monkeypatch.setattr(cli_tools, "start_install", busy)
    assert client.post(INSTALL).status_code == 409


# ---------------------------------------------- the worker's crash, in words

def test_an_unforeseen_crash_in_the_worker_names_the_tool_and_the_step(
        settings, monkeypatch):
    """The status an admin reads used to be "TypeError while installing
    claude_code": a Python class name and the internal name of the tool, with
    nothing about whether anything was installed."""
    def boom(_settings):
        raise TypeError("NoneType is not subscriptable")

    monkeypatch.setattr(cli_tools, "_install_claude", boom)
    cli_tools._set_status("claude_code", state="running",
                          step="downloading 2.1.234 (linux-x64)")
    cli_tools._install_worker(settings, "claude_code")
    status = cli_tools.install_status(settings, "claude_code")
    assert status["state"] == "error"
    error = status["error"]
    assert "Claude Code" in error
    assert "TypeError" in error
    assert "downloading 2.1.234 (linux-x64)" in error
    assert "Nothing was installed" in error
    assert "—" not in error


# ----------------------------------- the publisher shapes, and the CONDITION

class _Resp:
    def __init__(self, data: bytes):
        self._data = data
        self._at = 0

    def read(self, size=-1):
        end = (len(self._data) if size in (-1, None)
               else min(self._at + size, len(self._data)))
        out = self._data[self._at:end]
        self._at = end
        return out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


def _serve(monkeypatch, routes: dict):
    """Stub the OPENER, which is the seam every byte in this module comes
    through (`release_feed.open_https_stream`); nothing here touches a
    socket."""
    def opener(url, *, timeout):
        for fragment, data in routes.items():
            if fragment in url:
                return _Resp(data if isinstance(data, bytes) else data.encode())
        raise AssertionError(f"unrouted url {url}")

    monkeypatch.setattr(cli_tools.release_feed, "open_https_stream", opener)


PAYLOAD = b"pretend this is 313 MiB of claude"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.mark.parametrize("manifest", [
    b"null",
    b"[1, 2]",
    json.dumps({"platforms": None}).encode(),
    json.dumps({"platforms": {"linux-x64": None}}).encode(),
    json.dumps({"platforms": {"linux-x64": {"checksum": 12345,
                                            "size": None}}}).encode(),
    json.dumps({"platforms": {"linux-x64": {"checksum": SHA,
                                            "size": {"bytes": 3}}}}).encode(),
    json.dumps({"platforms": {"linux-x64": {"checksum": SHA, "size": "33",
                                            "binary": None}}}).encode(),
])
def test_a_wrong_typed_publisher_manifest_is_a_refusal_never_a_typeerror(
        settings, monkeypatch, manifest):
    _linux(monkeypatch)
    _serve(monkeypatch, {"/latest": b"2.1.234", "manifest.json": manifest,
                         "/linux-x64/": PAYLOAD})
    try:
        cli_tools._install_claude(settings)
    except cli_tools.ToolError:
        pass                      # a refusal in words is the expected answer
    # Whatever happened, it was not a TypeError, and an entry that did parse
    # only installs when the publisher's own sha256 matched.
    binary = cli_tools.installed_binary(settings, "claude_code")
    if binary:
        state = cli_tools.read_state(settings, "claude_code")
        assert state["sha256"] == SHA
        assert state["checksum_verified"] is True


def test_a_codex_release_with_no_published_checksum_is_still_refused(
        settings, monkeypatch):
    """trust-model-7, re-pinned here because CR-266a touched this module: a
    release that publishes no checksum for the asset is REFUSED, never
    installed unverified."""
    _linux(monkeypatch)
    monkeypatch.setattr(cli_tools, "codex_target",
                        lambda machine=None, system=None: "x86_64-unknown-linux-musl")
    release = json.dumps({"tag_name": "rust-v0.147.0", "assets": [
        {"name": "codex-package-x86_64-unknown-linux-musl.tar.gz",
         "browser_download_url": "https://gh/pkg.tar.gz"}]}).encode()
    _serve(monkeypatch, {"releases/latest": release, "pkg.tar.gz": b"x"})
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools._install_codex(settings)
    assert "no checksum" in str(exc.value)
    assert cli_tools.installed_binary(settings, "codex") == ""
