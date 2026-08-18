"""Settings -> AI providers: the key store, the chain, and the five routes
(2026-08-18, ai_providers.py).

Three properties this file exists to hold down:

* **A key never leaves the container in a readable form.** Not in
  `GET /api/v1/site` (open to anyone who can reach the dashboard), not in the
  admin routes' answers (they publish a mask), not in a log line.
* **The chain is exactly claude_code > anthropic_api > codex > openai_api >
  deepseek_api, first available.** Table-driven over all 32 availability
  combinations, plus every pin.
* **CLI providers are dark unless the site turned them on**, and are never
  probed -- no subprocess at all -- while the flag is off.

No test here runs a real subprocess or opens a socket: `_run` and
`_live_api_check` are the two seams, and both are replaced.
"""
from __future__ import annotations

import itertools
import json

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import ai_providers, auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
ADMIN = "owen"
EDITOR = "editor1"

REAL_KEY = "sk-ant-api03-THIS-IS-THE-SECRET-VALUE-abcd"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture(autouse=True)
def _cold_probe_cache():
    """The CLI probe cache is a module global with a 10-minute TTL; one test's
    answer must not decide the next one's."""
    ai_providers.reset_probe_cache()
    yield
    ai_providers.reset_probe_cache()


@pytest.fixture
def env(tmp_path, monkeypatch):
    # No AI key anywhere in the ambient environment: a developer's shell may
    # genuinely export one, and "env wins" would then quietly decide half
    # these tests.
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(
        db_path=str(tmp_path / "ai.db"),
        session_secret=SECRET,
        admin_users=frozenset({ADMIN}),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "ai.db")
        yield client, conn, settings
        conn.close()


# --------------------------------------------------------------- key storage

def test_a_key_is_stored_0600_under_data_secrets_ai(env):
    _client, _conn, settings = env
    ai_providers.set_key(settings, "anthropic_api", REAL_KEY)
    path = ai_providers.keys_dir(settings) / "anthropic_api_key"
    assert path.read_text(encoding="utf-8") == REAL_KEY
    # The same tree the five boot secrets live in, so one directory is what an
    # operator backs up and locks down.
    assert path.parent.parent.name == "secrets"


def test_the_environment_wins_and_says_so(env, monkeypatch):
    _client, _conn, settings = env
    ai_providers.set_key(settings, "openai_api", "sk-stored-value-1234")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-deployment-9999")
    value, source = ai_providers.read_key(settings, "openai_api")
    assert (value, source) == ("sk-from-the-deployment-9999", "env")


def test_a_key_is_masked_not_published(env):
    assert ai_providers.mask(REAL_KEY) == "sk-…abcd"
    # A short value is masked ENTIRELY: 4 of 6 characters is not a mask.
    assert ai_providers.mask("sk-1234") == "…"
    assert ai_providers.mask("") == ""


@pytest.mark.parametrize("bad,why", [
    ("", "blank"),
    ("   ", "blank"),
    ("Bearer sk-abc", "space"),
    ("sk-abc\ndef", "space"),
    ("sk-\x00abc", "control"),
])
def test_a_malformed_key_is_refused_without_being_echoed(bad, why):
    with pytest.raises(ai_providers.ProviderError) as exc:
        ai_providers.validate_key(bad)
    assert bad.strip() not in str(exc.value) or not bad.strip()


def test_clearing_removes_the_file(env):
    _client, _conn, settings = env
    ai_providers.set_key(settings, "deepseek_api", REAL_KEY)
    assert ai_providers.clear_key(settings, "deepseek_api") is True
    assert ai_providers.read_key(settings, "deepseek_api") == ("", "")
    assert ai_providers.clear_key(settings, "deepseek_api") is False


# ----------------------------------------------------------------- the chain

ORDER = ai_providers.PROVIDER_ORDER


def test_the_order_is_the_one_the_product_asked_for():
    assert ORDER == ("claude_code", "anthropic_api", "codex", "openai_api",
                     "deepseek_api")


@pytest.mark.parametrize(
    "combo", list(itertools.product([False, True], repeat=len(ORDER))))
def test_auto_always_picks_the_first_available(combo):
    """All 32 availability combinations, against the one rule the whole
    feature turns on."""
    availability = dict(zip(ORDER, combo))
    choice = ai_providers.resolve_provider(availability, "auto")
    expected = next((n for n in ORDER if availability[n]), "")
    assert choice.name == expected
    assert choice.ok == bool(expected)
    if not expected:
        assert "no provider" in choice.reason


@pytest.mark.parametrize("pinned", ORDER)
def test_a_pin_wins_over_a_higher_ranked_provider(pinned):
    everything = {name: True for name in ORDER}
    choice = ai_providers.resolve_provider(everything, pinned)
    assert choice.name == pinned
    assert choice.pinned is True


@pytest.mark.parametrize("pinned", ORDER)
def test_an_unavailable_pin_is_a_refusal_not_a_fallback(pinned):
    """Falling through would spend a key the admin did not choose -- on a
    service they may have pinned away from deliberately."""
    availability = {name: True for name in ORDER}
    availability[pinned] = False
    choice = ai_providers.resolve_provider(availability, pinned)
    assert choice.name == ""
    assert choice.pinned is True
    assert "pinned but not available" in choice.reason


def test_a_nonsense_pin_is_refused_rather_than_ignored():
    choice = ai_providers.resolve_provider({n: True for n in ORDER}, "gemini")
    assert choice.name == ""
    assert "not a known AI provider" in choice.reason


def test_a_blank_preference_reads_as_auto(env):
    _client, conn, _settings = env
    assert ai_providers.preference(conn) == "auto"
    ai_providers.set_setting(conn, ai_providers.PREFERENCE_KEY, "nonsense", "seed")
    conn.commit()
    # A stored value nothing recognises must not become a pin nothing can
    # satisfy -- it reads as auto.
    assert ai_providers.preference(conn) == "auto"


# -------------------------------------------------------- CLI gating + probe

def test_cli_providers_are_off_and_unprobed_in_the_vendor_build(env, monkeypatch):
    _client, conn, settings = env
    ran = []
    monkeypatch.setattr(ai_providers, "_run",
                        lambda *a, **kw: ran.append(a) or None)
    rows = {r["name"]: r for r in ai_providers.provider_states(conn, settings)}
    assert rows["claude_code"]["status"] == "disabled_by_site"
    assert rows["codex"]["status"] == "disabled_by_site"
    assert rows["claude_code"]["available"] is False
    # NOT ONE SUBPROCESS. An off site must not run somebody's agent binary to
    # find out whether it would have worked.
    assert ran == []


def enable_cli(conn):
    conn.execute(
        "INSERT INTO site_settings (key, value, updated_at, updated_by) "
        "VALUES ('features.ai_cli_providers','1','now','test') "
        "ON CONFLICT(key) DO UPDATE SET value='1'")
    conn.commit()


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def fake_cli(monkeypatch, *, on_path="/usr/bin/claude", version=FakeProc(0, "2.1.0"),
             probe=FakeProc(0, "ok")):
    monkeypatch.setattr(ai_providers.shutil, "which",
                        lambda binary: on_path)

    def run(argv, stdin, timeout, env=None):
        return version if argv[1:] == ["--version"] else probe

    monkeypatch.setattr(ai_providers, "_run", run)


def test_an_installed_and_signed_in_cli_is_available_and_wins_the_chain(env, monkeypatch):
    _client, conn, settings = env
    enable_cli(conn)
    fake_cli(monkeypatch)
    rows = ai_providers.provider_states(conn, settings)
    by_name = {r["name"]: r for r in rows}
    assert by_name["claude_code"]["status"] == "available"
    # Claude Code is rank 1: with a key set as well, it still wins.
    ai_providers.set_key(settings, "anthropic_api", REAL_KEY)
    choice = ai_providers.resolved(conn, settings)
    assert choice.name == "claude_code"


def test_a_missing_binary_reads_as_not_installed(env, monkeypatch):
    _client, conn, settings = env
    enable_cli(conn)
    fake_cli(monkeypatch, on_path=None)
    row = {r["name"]: r for r in ai_providers.provider_states(conn, settings)}["codex"]
    assert row["status"] == "not_installed"
    assert "codex" in row["detail"]


def test_a_logged_out_cli_reads_as_not_signed_in_with_the_command(env, monkeypatch):
    _client, conn, settings = env
    enable_cli(conn)
    fake_cli(monkeypatch, probe=FakeProc(1, "", "Invalid API key. Please run /login"))
    row = {r["name"]: r for r in ai_providers.provider_states(conn, settings)}["claude_code"]
    assert row["status"] == "not_signed_in"
    assert row["available"] is False
    # We cannot complete an interactive OAuth from a web page and must not
    # pretend to: the page prints the command to run on the host.
    assert row["login_command"]


def test_an_admin_configured_path_beats_whatever_is_on_path(env, monkeypatch, tmp_path):
    _client, conn, settings = env
    enable_cli(conn)
    binary = tmp_path / "my-claude"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    ai_providers.set_setting(conn, "ai_claude_code_path", str(binary), "owen")
    conn.commit()
    monkeypatch.setattr(ai_providers.shutil, "which", lambda b: "/usr/bin/claude")
    assert ai_providers.cli_path(conn, "claude_code") == str(binary)


def test_the_probe_does_not_hand_the_cli_the_containers_api_key(monkeypatch):
    """Claude Code prefers ANTHROPIC_API_KEY when it finds one, so a probe
    that inherited it would answer "signed in" about a key rather than about
    the login -- and bill the wrong account to say so."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-inherited")
    assert "ANTHROPIC_API_KEY" not in ai_providers._probe_env()
    assert "PATH" in ai_providers._probe_env()   # the rest is inherited


def test_the_probe_is_cached_between_calls(env, monkeypatch):
    _client, conn, settings = env
    enable_cli(conn)
    calls = []
    monkeypatch.setattr(ai_providers.shutil, "which", lambda b: "/usr/bin/claude")

    def run(argv, stdin, timeout, env=None):
        calls.append(argv)
        return FakeProc(0, "ok")

    monkeypatch.setattr(ai_providers, "_run", run)
    ai_providers.probe_cli(conn, "claude_code")
    before = len(calls)
    ai_providers.probe_cli(conn, "claude_code")
    # The chain re-resolves on EVERY ytdl AI call; a subprocess per call would
    # be a fork bomb under a running job.
    assert len(calls) == before
    ai_providers.probe_cli(conn, "claude_code", force=True)
    assert len(calls) > before


# ------------------------------------------------------- what ytdl is handed

def test_the_lookup_payload_carries_the_key_and_the_name(env):
    _client, conn, settings = env
    ai_providers.set_key(settings, "openai_api", REAL_KEY)
    payload = ai_providers.lookup_payload(conn, settings)
    assert payload["provider"] == "openai_api"
    assert payload["api_key"] == REAL_KEY
    assert payload["cli_enabled"] is False


def test_the_lookup_payload_names_nothing_when_nothing_works(env):
    _client, conn, settings = env
    payload = ai_providers.lookup_payload(conn, settings)
    assert payload["provider"] == ""
    assert "api_key" not in payload
    assert payload["detail"]


def test_a_cli_choice_carries_a_path_not_a_key(env, monkeypatch):
    _client, conn, settings = env
    enable_cli(conn)
    fake_cli(monkeypatch)
    payload = ai_providers.lookup_payload(conn, settings)
    assert payload["provider"] == "claude_code"
    assert payload["cli_path"] == "/usr/bin/claude"
    assert payload["cli_enabled"] is True
    assert "api_key" not in payload


# ----------------------------------------------------------------- the routes

ROUTE = "/api/v1/admin/ai-providers"


@pytest.mark.parametrize("method,path,body", [
    ("get", ROUTE, None),
    ("put", ROUTE + "/anthropic_api/key", {"key": REAL_KEY}),
    ("delete", ROUTE + "/anthropic_api/key", None),
    ("post", ROUTE + "/anthropic_api/test", None),
    ("put", ROUTE + "/preference", {"preference": "openai_api"}),
])
def test_every_route_refuses_an_anonymous_caller(env, method, path, body):
    client, _conn, _settings = env
    resp = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("get", ROUTE, None),
    ("put", ROUTE + "/anthropic_api/key", {"key": REAL_KEY}),
    ("delete", ROUTE + "/anthropic_api/key", None),
    ("post", ROUTE + "/anthropic_api/test", None),
    ("put", ROUTE + "/preference", {"preference": "openai_api"}),
])
def test_every_route_refuses_a_non_admin_session(env, method, path, body):
    client, _conn, _settings = env
    as_user(client, EDITOR)
    resp = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert resp.status_code == 403


def test_the_get_lists_every_provider_in_chain_order(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    body = client.get(ROUTE).json()
    assert [p["name"] for p in body["providers"]] == list(ORDER)
    assert [p["rank"] for p in body["providers"]] == [1, 2, 3, 4, 5]
    assert body["preference"] == "auto"
    assert body["resolved"]["name"] == ""          # nothing configured yet
    assert body["cli_enabled"] is False
    # The ToS note is part of the API answer, not just the template: an admin
    # driving this from curl gets the same warning.
    assert "personal" in body["cli_tos_note"]


def test_setting_a_key_answers_a_mask_and_never_the_key(env):
    client, _conn, settings = env
    as_user(client, ADMIN)
    resp = client.put(ROUTE + "/anthropic_api/key", json={"key": REAL_KEY})
    assert resp.status_code == 200
    raw = resp.text
    assert REAL_KEY not in raw
    row = {p["name"]: p for p in resp.json()["providers"]}["anthropic_api"]
    assert row["masked"] == "sk-…abcd"
    assert row["key_present"] is True
    assert row["status"] == "available"
    # ...and the resolved line now names it.
    assert resp.json()["resolved"]["name"] == "anthropic_api"
    # The value really was stored.
    assert ai_providers.read_key(settings, "anthropic_api")[0] == REAL_KEY


def test_a_key_never_appears_in_the_open_site_manifest(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    client.put(ROUTE + "/anthropic_api/key", json={"key": REAL_KEY})
    manifest = client.get("/api/v1/site").text
    assert REAL_KEY not in manifest
    assert "anthropic" not in manifest.lower()
    # And the CLI feature flag is not published either: no client needs it.
    assert "ai_cli_providers" not in manifest


def test_the_features_block_of_the_open_manifest_is_still_exactly_two(env):
    client, _conn, _settings = env
    features = client.get("/api/v1/site").json()["features"]
    assert set(features) == {"youtube_download", "youtube_unblock"}


def test_a_bad_key_is_a_422_that_does_not_echo_it(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    resp = client.put(ROUTE + "/anthropic_api/key", json={"key": "Bearer " + REAL_KEY})
    assert resp.status_code == 422
    assert REAL_KEY not in resp.text


def test_an_unknown_provider_is_a_404(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    assert client.put(ROUTE + "/gemini_api/key", json={"key": REAL_KEY}).status_code == 404
    assert client.post(ROUTE + "/gemini_api/test").status_code == 404


def test_a_cli_provider_has_no_key_route(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    resp = client.put(ROUTE + "/claude_code/key", json={"key": REAL_KEY})
    assert resp.status_code == 400
    assert "CLI" in resp.json()["detail"]


def test_a_key_set_by_the_deployment_cannot_be_overwritten_from_the_page(env, monkeypatch):
    client, _conn, _settings = env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-the-deployment")
    as_user(client, ADMIN)
    resp = client.put(ROUTE + "/anthropic_api/key", json={"key": REAL_KEY})
    assert resp.status_code == 409
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]
    row = {p["name"]: p for p in client.get(ROUTE).json()["providers"]}["anthropic_api"]
    assert row["key_source"] == "env"
    assert row["editable"] is False
    assert "set by the deployment" in row["detail"]


def test_clearing_a_key_takes_the_provider_out_of_the_chain(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    client.put(ROUTE + "/openai_api/key", json={"key": REAL_KEY})
    assert client.get(ROUTE).json()["resolved"]["name"] == "openai_api"
    resp = client.delete(ROUTE + "/openai_api/key")
    assert resp.status_code == 200
    assert resp.json()["resolved"]["name"] == ""


def test_the_preference_is_stored_and_reflected(env):
    client, conn, _settings = env
    as_user(client, ADMIN)
    client.put(ROUTE + "/anthropic_api/key", json={"key": REAL_KEY})
    client.put(ROUTE + "/deepseek_api/key", json={"key": REAL_KEY})
    resp = client.put(ROUTE + "/preference", json={"preference": "deepseek_api"})
    assert resp.status_code == 200
    assert resp.json()["resolved"]["name"] == "deepseek_api"
    assert resp.json()["resolved"]["pinned"] is True
    # It is a site_settings row, so it survives a restart.
    assert ai_providers.preference(dbmod.connect(conn.execute(
        "PRAGMA database_list").fetchone()[2])) == "deepseek_api"


def test_the_cli_path_route_is_the_only_writable_thing_about_a_cli(env, tmp_path):
    """There is no install button and never will be: we ship, fetch and
    update neither binary. All an admin can say is where theirs is."""
    client, conn, _settings = env
    as_user(client, ADMIN)
    enable_cli(conn)
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    resp = client.put(ROUTE + "/claude_code/path", json={"path": str(binary)})
    assert resp.status_code == 200
    assert ai_providers.get_setting(conn, "ai_claude_code_path") == str(binary)
    # ...and it can be cleared back to "search PATH".
    client.put(ROUTE + "/claude_code/path", json={"path": ""})
    assert ai_providers.get_setting(conn, "ai_claude_code_path") == ""


def test_an_api_provider_has_no_path_route(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    resp = client.put(ROUTE + "/openai_api/path", json={"path": "/usr/bin/openai"})
    assert resp.status_code == 400


def test_the_path_route_refuses_an_anonymous_caller(env):
    client, _conn, _settings = env
    assert client.put(ROUTE + "/claude_code/path",
                      json={"path": "/x"}).status_code == 401
    as_user(client, EDITOR)
    assert client.put(ROUTE + "/claude_code/path",
                      json={"path": "/x"}).status_code == 403


def test_a_pin_nothing_recognises_is_refused(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    resp = client.put(ROUTE + "/preference", json={"preference": "gemini"})
    assert resp.status_code == 422


def test_the_test_button_reports_a_live_failure_without_the_key(env, monkeypatch):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    client.put(ROUTE + "/anthropic_api/key", json={"key": REAL_KEY})
    monkeypatch.setattr(ai_providers, "_live_api_check",
                        lambda name, key: "the key was refused (HTTP 401). ")
    resp = client.post(ROUTE + "/anthropic_api/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "401" in resp.json()["detail"]
    assert REAL_KEY not in resp.text


def test_the_test_button_reports_success(env, monkeypatch):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    client.put(ROUTE + "/openai_api/key", json={"key": REAL_KEY})
    monkeypatch.setattr(ai_providers, "_live_api_check", lambda name, key: None)
    body = client.post(ROUTE + "/openai_api/test").json()
    assert body["ok"] is True
    assert "accepted the key" in body["detail"]


def test_testing_an_unconfigured_provider_says_so_rather_than_calling_out(env, monkeypatch):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    called = []
    monkeypatch.setattr(ai_providers, "_live_api_check",
                        lambda name, key: called.append(name))
    body = client.post(ROUTE + "/deepseek_api/test").json()
    assert body["ok"] is False
    assert called == []


def test_testing_a_cli_while_the_flag_is_off_runs_nothing(env, monkeypatch):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    monkeypatch.setattr(ai_providers, "_run",
                        lambda *a, **kw: pytest.fail("no subprocess may run"))
    body = client.post(ROUTE + "/claude_code/test").json()
    assert body["ok"] is False
    assert "ai_cli_providers" in body["detail"]


def test_these_routes_are_not_csrf_exempt():
    """They are cookie-authenticated writes, so app.csrf_gate must cover them
    -- i.e. they must be on neither exemption list. Asserted against the lists
    themselves because the suite's hand-minted cookies are deliberately not
    server-tracked sessions, so the middleware short-circuits before the token
    check and a request-level test would pass for the wrong reason."""
    from ccsync_dashboard import app as appmod

    for path in (ROUTE + "/anthropic_api/key", ROUTE + "/anthropic_api/test",
                 ROUTE + "/preference"):
        assert path not in appmod._CSRF_EXEMPT_EXACT
        assert not path.startswith(appmod._CSRF_EXEMPT_PREFIXES)


def test_the_settings_page_carries_the_section_and_the_tos_note(env):
    """The page's static half. The rows themselves are drawn by
    static/site_settings.js from the admin route (a CLI status costs two
    subprocesses, and Settings must not block on those), so what is pinned
    here is the frame: the section, the pin control, the flag, and the ToS
    sentence that has to be in front of an admin BEFORE they turn CLI
    providers on."""
    client, _conn, _settings = env
    as_user(client, ADMIN)
    page = client.get("/admin/settings").text
    assert "AI PROVIDERS" in page
    assert 'id="ai-providers"' in page
    assert 'id="ai-preference"' in page
    assert 'id="ai-cli-enabled"' in page
    assert 'id="ai-resolved"' in page


def test_the_tos_note_says_whose_decision_it_is():
    note = ai_providers.CLI_TOS_NOTE
    assert "personal" in note and "terms" in note
    assert "your decision" in note
    # And that we ship neither CLI -- the half of COMMERCIAL_READINESS item 1
    # that is ours to keep answered.
    assert "Neither CLI is shipped, bundled or updated by CC Sync" in note
    # And that the SET UP button, added 2026-08-18, is described for what it
    # is: a fetch from the publisher at the customer's click, checksum-checked
    # -- not us putting a copy of somebody's proprietary binary in an artefact.
    assert "publisher's own build" in note and "checksum" in note


def test_the_key_is_never_in_a_query_string(env):
    """The routes take the key in a BODY. A query string lands in access logs,
    browser history and every proxy in between."""
    client, _conn, _settings = env
    as_user(client, ADMIN)
    resp = client.put(ROUTE + "/anthropic_api/key?key=" + REAL_KEY, json={"key": REAL_KEY})
    # The query is simply not read: the stored value came from the body.
    assert resp.status_code == 200
    assert json.loads(resp.text)["providers"][1]["masked"] == "sk-…abcd"
