"""GL-31 / GL-34 (ledger CR-374, 2026-10-07): the vendor build hard-disables
the Claude Code / Codex CLI providers; the studio's deploy opts back in; and
the site manifest carries a vendor-defaulted support contact.

conftest.py runs the whole suite as the STUDIO flavour; every test here that
wants the vendor build deletes the variable first.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import ai_providers, auth, build_flavor, cli_tools, triage, ui
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import site_store
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
ADMIN = "owen"


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "f.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def vendor(monkeypatch):
    monkeypatch.delenv(build_flavor.ENV_VAR, raising=False)


def _turn_everything_on(conn):
    site_store.set_many(conn, {"features.ai_cli_providers": "1",
                               "features.ai_cli_auto_update": "1"}, updated_by="test")
    conn.commit()


# ------------------------------------------------------------ GL-31

def test_the_studio_flavour_reads_the_row_as_before(conn, monkeypatch):
    monkeypatch.setenv(build_flavor.ENV_VAR, "1")
    _turn_everything_on(conn)
    assert ai_providers.cli_enabled(conn, Settings()) is True
    assert site_store.feature_enabled(conn, Settings(), "ai_cli_auto_update") is True


def test_the_vendor_build_ignores_a_stored_row_and_the_env(conn, vendor):
    _turn_everything_on(conn)
    assert ai_providers.cli_enabled(conn, Settings()) is False
    assert site_store.feature_enabled(conn, Settings(), "ai_cli_auto_update") is False
    assert ai_providers.cli_enabled(
        conn, Settings(site_feature_ai_cli_providers=True)) is False


def test_the_vendor_lock_does_not_touch_other_features(conn, vendor):
    site_store.set_many(conn, {"features.auto_update": "1"}, updated_by="test")
    conn.commit()
    assert site_store.feature_enabled(conn, Settings(), "auto_update") is True


@pytest.mark.parametrize("value", ["", "0", "true", "yes", " 2 "])
def test_only_a_literal_one_opts_the_studio_in(monkeypatch, value):
    monkeypatch.setenv(build_flavor.ENV_VAR, value)
    assert build_flavor.studio_cli_allowed() is False


def test_the_manifest_publishes_the_cli_features_off_on_a_vendor_build(conn, vendor):
    _turn_everything_on(conn)
    features = site_store.resolved_manifest(conn, Settings())["features"]
    assert features["ai_cli_providers"] is False
    assert features["ai_cli_auto_update"] is False


def test_the_provider_rows_say_not_in_this_build(conn, vendor):
    _turn_everything_on(conn)
    rows = ai_providers.provider_states(conn, Settings(), probe=True)
    cli_rows = [r for r in rows if r["name"] in ("claude_code", "codex")]
    assert cli_rows
    for row in cli_rows:
        assert row["status"] == ai_providers.ST_DISABLED
        assert row["detail"] == build_flavor.LOCKED_DETAIL


def test_a_pinned_cli_never_resolves_on_a_vendor_build(conn, vendor, monkeypatch):
    _turn_everything_on(conn)
    # A pin the studio stored before the lock: written straight, since
    # set_preference now refuses it on this build.
    ai_providers.set_setting(conn, ai_providers.PREFERENCE_KEY, "claude_code", "test")
    monkeypatch.setattr(ai_providers, "cli_path", lambda *a, **k: "/usr/bin/claude")
    choice = ai_providers.resolved(conn, Settings())
    assert choice.name != "claude_code"
    assert "pinned but not available" not in choice.reason


def test_test_button_refuses_a_cli_with_the_locked_wording(conn, vendor):
    _turn_everything_on(conn)
    out = ai_providers.test_provider(conn, Settings(), "claude_code")
    assert out["ok"] is False
    assert out["detail"] == build_flavor.LOCKED_DETAIL


def test_the_wizard_routes_refuse_with_the_locked_wording(conn, vendor):
    _turn_everything_on(conn)
    with pytest.raises(Exception) as exc:
        cli_tools._require_cli_enabled(conn, Settings())
    assert exc.value.status_code == 409
    assert exc.value.detail == build_flavor.LOCKED_DETAIL


def test_triage_gate_on_a_locked_build_needs_an_api_key_first(conn, vendor, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path, why = triage.cli_gate(conn, Settings(db_path=str(conn.execute("PRAGMA database_list").fetchone()[2])))
    assert path == "" and "Anthropic API key" in why


def test_triage_gate_on_a_locked_build_needs_a_binary(conn, vendor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-1234567890")
    monkeypatch.setattr(ai_providers, "cli_path", lambda c, n, s=None: "")
    path, why = triage.cli_gate(conn, Settings())
    assert path == "" and "full path" in why and "SET UP" not in why


def test_triage_runs_on_a_locked_build_with_key_and_binary_never_the_subscription(
        conn, vendor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-1234567890")
    monkeypatch.setenv(cli_tools.CLAUDE_TOKEN_VAR, "sub-token")
    monkeypatch.setattr(ai_providers, "cli_path", lambda c, n, s=None: "/usr/bin/claude")
    _turn_everything_on(conn)
    path, why = triage.cli_gate(conn, Settings())
    assert (path, why) == ("/usr/bin/claude", "")
    env = triage.run_env(Settings())
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test-key-1234567890"
    assert cli_tools.CLAUDE_TOKEN_VAR not in env


def test_the_features_panel_has_no_cli_rows_on_a_locked_build(tmp_path, vendor):
    settings = Settings(db_path=str(tmp_path / "q.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        html = client.get("/admin/settings").text
        assert "features.ai_cli_auto_update" not in html
        assert "Keep Claude Code up to date" not in html
        assert "AI CLI providers" not in html


def test_the_features_panel_keeps_the_cli_rows_for_the_studio(tmp_path, monkeypatch):
    monkeypatch.setenv(build_flavor.ENV_VAR, "1")
    settings = Settings(db_path=str(tmp_path / "q2.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        assert "features.ai_cli_auto_update" in client.get("/admin/settings").text


def test_stranded_rows_are_detected_and_never_rewritten(conn, vendor):
    assert build_flavor.stranded_cli_rows(conn) is False
    _turn_everything_on(conn)
    assert build_flavor.stranded_cli_rows(conn) is True
    assert site_store.get_all(conn)["features.ai_cli_auto_update"] == "1"


# ------------------------------------------------------------ GL-34 raw value

def test_support_contact_unset_is_blank_in_the_box_and_export(conn):
    assert site_store.raw_support_contact(conn, Settings()) == ""
    assert site_store.resolved_manifest(conn, Settings())["support_contact"] ==         site_store.DEFAULT_SUPPORT_CONTACT
    assert site_store.DEFAULT_SUPPORT_CONTACT not in site_store.export_toml(conn, Settings())


def test_support_contact_box_renders_blank_with_a_placeholder(tmp_path):
    settings = Settings(db_path=str(tmp_path / "q3.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        html = client.get("/admin/settings").text
        assert 'name="support_contact" value="" placeholder="%s"' %             site_store.DEFAULT_SUPPORT_CONTACT in html


def test_a_mailed_fix_line_carries_the_support_address(conn):
    from ccsync_dashboard import alerts

    sent = {}
    site_store.set_many(conn, {"support_contact": "help@x.example"}, updated_by="t")
    conn.commit()
    alerts.set_settings(conn, {"alerts_sink": "webhook",
                               "alerts_webhook_url": "https://h.example/x"}, "test")
    orig = alerts._send_webhook
    alerts._send_webhook = lambda url, subject, text: sent.setdefault("text", text) and "ok"
    try:
        alerts._transmit(conn, Settings(), "s", "Send us the container log.", label="t")
    finally:
        alerts._send_webhook = orig
    assert "help@x.example" in sent["text"]
    assert site_store.with_support_text("Send us the container log.", "help@x.example")         .endswith("Support: help@x.example")


def test_setup_checklist_shows_the_support_contact(tmp_path):
    settings = Settings(db_path=str(tmp_path / "q4.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        r = client.get("/setup")
        assert r.status_code == 200
        assert site_store.DEFAULT_SUPPORT_CONTACT in r.text


def test_the_admin_page_snapshot_carries_cli_build_locked(tmp_path, vendor):
    settings = Settings(db_path=str(tmp_path / "p.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        body = client.get("/api/v1/admin/ai-providers").json()
        assert body["cli_build_locked"] is True
        assert body["cli_enabled"] is False
        r = client.post("/api/v1/admin/ai-providers/codex/install")
        assert r.status_code in (409, 403)


def test_the_settings_script_hides_cli_rows_when_locked():
    js = (ui.TEMPLATES_DIR.parent / "static" / "cc" / "site_settings.js").read_text(
        encoding="utf-8")
    assert "cli_build_locked" in js


def test_the_deploy_script_projects_only_the_studio_toml_key():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    import install_dashboard_app as ida

    body = ida.compose_config(8480, "/mnt/tank/apps/ccsync-dashboard",
                              "http://x:8384", "k", "t")
    assert body["services"]["dashboard"]["environment"]["DASH_STUDIO_CLI_PROVIDERS"] == "0"
    body = ida.compose_config(8480, "/mnt/tank/apps/ccsync-dashboard",
                              "http://x:8384", "k", "t", studio_cli_providers="1")
    assert body["services"]["dashboard"]["environment"]["DASH_STUDIO_CLI_PROVIDERS"] == "1"


# ------------------------------------------------------------ GL-34

def test_support_contact_defaults_to_the_vendor_address(conn):
    manifest = site_store.resolved_manifest(conn, Settings())
    assert manifest["support_contact"] == site_store.DEFAULT_SUPPORT_CONTACT


def test_support_contact_reseller_override_by_env_and_by_row(conn):
    assert site_store.resolved_manifest(
        conn, Settings(site_support_contact="help@reseller.example"))[
        "support_contact"] == "help@reseller.example"
    site_store.set_many(conn, {"support_contact": "desk@x.example"}, updated_by="test")
    conn.commit()
    assert site_store.resolved_manifest(
        conn, Settings(site_support_contact="help@reseller.example"))[
        "support_contact"] == "desk@x.example"


def test_support_contact_is_in_the_env_loader():
    s = Settings.from_env({"DASH_SITE_SUPPORT_CONTACT": " a@b.example "})
    assert s.site_support_contact == "a@b.example"


def test_support_contact_round_trips_through_export(conn):
    site_store.set_many(conn, {"support_contact": "desk@x.example"}, updated_by="test")
    conn.commit()
    assert 'support_contact = "desk@x.example"' in site_store.export_toml(conn, Settings())


def test_with_support_text_appends_once_and_only_where_it_applies():
    f = ui.with_support_text
    assert f("Send us the container log.", "h@x.example") == \
        "Send us the container log. Support: h@x.example"
    assert f("Copy it and send it to support.", "h@x.example").endswith("h@x.example")
    assert f("Restart the tray.", "h@x.example") == "Restart the tray."
    again = f("Send us the log. Support: h@x.example", "h@x.example")
    assert again.count("h@x.example") == 1
    assert f("Send us the log.", "") == "Send us the log."
    assert f(None, "h@x.example") == ""


def test_the_api_site_route_publishes_support_contact(tmp_path):
    settings = Settings(db_path=str(tmp_path / "s.db"), session_secret=SECRET,
                        site_support_contact="help@reseller.example")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/site").json()["support_contact"] == "help@reseller.example"


def test_help_and_health_show_the_contact(tmp_path):
    settings = Settings(db_path=str(tmp_path / "s.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}),
                        site_support_contact="help@reseller.example")
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        assert "help@reseller.example" in client.get("/help").text
        assert "help@reseller.example" in client.get("/admin/health").text


# ------------------------------------------------------------ CR-374 round 2

def test_the_vendor_default_support_address_is_the_owner_confirmed_one():
    assert site_store.DEFAULT_SUPPORT_CONTACT == "support@thecreatorsclub.co"


def test_locked_triage_run_has_its_own_writable_home_and_only_the_api_key(
        conn, vendor, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-1234567890")
    monkeypatch.setenv("HOME", "/nonexistent-container-home")
    monkeypatch.setenv(cli_tools.CLAUDE_TOKEN_VAR, "sub-token")
    settings = Settings(db_path=str(tmp_path / "d" / "x.db"))
    env = triage.run_env(settings)
    home = tmp_path / "d" / "tools" / "claude-code" / "api-home"
    assert env["HOME"] == str(home) and home.is_dir()
    assert not (tmp_path / "d" / "tools" / "claude-code" / "home").exists()
    assert cli_tools.CLAUDE_TOKEN_VAR not in env
    assert env["ANTHROPIC_API_KEY"].startswith("sk-ant-")


def test_a_stored_cli_pin_is_inert_on_a_locked_build_and_refused_when_set(conn, vendor):
    ai_providers.set_setting(conn, ai_providers.PREFERENCE_KEY, "claude_code", "test")
    conn.commit()
    assert ai_providers.preference(conn) == ai_providers.AUTO
    with pytest.raises(ai_providers.ProviderError) as exc:
        ai_providers.set_preference(conn, "codex", "test")
    assert str(exc.value) == build_flavor.LOCKED_DETAIL
    assert ai_providers.set_preference(conn, "anthropic_api", "test") == "anthropic_api"
    assert ai_providers.preference(conn) == "anthropic_api"


def test_a_cli_pin_still_works_for_the_studio(conn, monkeypatch):
    monkeypatch.setenv(build_flavor.ENV_VAR, "1")
    assert ai_providers.set_preference(conn, "claude_code", "test") == "claude_code"
    assert ai_providers.preference(conn) == "claude_code"


def test_export_keeps_the_raw_cli_flags_on_a_locked_build(conn, vendor):
    _turn_everything_on(conn)
    out = site_store.export_toml(conn, Settings())
    assert "ai_cli_providers = true" in out
    assert "ai_cli_auto_update = true" in out


def test_stranded_studio_raises_a_notice_and_clears_it(conn, vendor, monkeypatch):
    from ccsync_dashboard import notices

    _turn_everything_on(conn)
    from ccsync_dashboard import ai_providers

    none = ai_providers.ProviderChoice(name="", label="", reason="none")
    monkeypatch.setattr(ai_providers, "resolved", lambda *a, **k: none)
    notices._check_cli_lock_stranded(conn, Settings(), dbmod.utcnow_iso())
    rows = [r for r in dbmod.open_notices(conn) if r["kind"] == "cli_lock_stranded"]
    assert len(rows) == 1 and "allow_cli_providers" not in rows[0]["fix"]
    monkeypatch.setenv(build_flavor.ENV_VAR, "1")
    notices._check_cli_lock_stranded(conn, Settings(), dbmod.utcnow_iso())
    assert not [r for r in dbmod.open_notices(conn) if r["kind"] == "cli_lock_stranded"]


def test_customer_with_an_api_key_and_an_inert_row_has_no_notice(conn, vendor, monkeypatch):
    from ccsync_dashboard import ai_providers, notices

    _turn_everything_on(conn)
    none = ai_providers.ProviderChoice(name="", label="", reason="none")
    monkeypatch.setattr(ai_providers, "resolved", lambda *a, **k: none)
    notices._check_cli_lock_stranded(conn, Settings(), dbmod.utcnow_iso())
    assert [r for r in dbmod.open_notices(conn) if r["kind"] == "cli_lock_stranded"]
    key = ai_providers.ProviderChoice(name="anthropic_api", label="x", reason="key")
    monkeypatch.setattr(ai_providers, "resolved", lambda *a, **k: key)
    notices._check_cli_lock_stranded(conn, Settings(), dbmod.utcnow_iso())
    assert not [r for r in dbmod.open_notices(conn) if r["kind"] == "cli_lock_stranded"]


def test_an_openai_only_site_is_still_stranded(conn, vendor, monkeypatch):
    # Round 2 overseer: Cards and the locked triage gate need a Claude
    # provider, so a non-Claude key must not close the notice.
    from ccsync_dashboard import ai_providers, notices

    _turn_everything_on(conn)
    oa = ai_providers.ProviderChoice(name="openai_api", label="x", reason="key")
    monkeypatch.setattr(ai_providers, "resolved", lambda *a, **k: oa)
    notices._check_cli_lock_stranded(conn, Settings(), dbmod.utcnow_iso())
    assert [r for r in dbmod.open_notices(conn) if r["kind"] == "cli_lock_stranded"]


def test_locked_build_keeps_the_claude_code_install_open_and_codex_shut(tmp_path, vendor, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "i.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    seen = []
    monkeypatch.setattr(cli_tools, "start_install",
                        lambda s, name, **k: seen.append(name) or {"state": "running"})
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, ADMIN))
        r = client.post("/api/v1/admin/ai-providers/claude_code/install")
        assert r.status_code == 200 and seen == ["claude_code"]
        r = client.post("/api/v1/admin/ai-providers/codex/install")
        assert r.status_code == 409 and seen == ["claude_code"]
        r = client.post("/api/v1/admin/ai-providers/claude_code/signin", json={})
        assert r.status_code == 409


def test_the_locked_page_offers_a_path_box_and_no_wizard():
    js = (ui.TEMPLATES_DIR.parent / "static" / "cc" / "site_settings.js").read_text(
        encoding="utf-8")
    assert "drawLockedCheck" in js and "ai-check-path-save" in js
    assert "your own Claude Code" in js
    assert "which this build does not include" not in js


def test_the_pinned_non_claude_case_names_the_pin_not_a_missing_key(conn, vendor, monkeypatch):
    # CR-374 round 3: a Claude key exists but openai_api is pinned.
    from ccsync_dashboard import ai_providers, notices

    _turn_everything_on(conn)
    oa = ai_providers.ProviderChoice(name="openai_api", label="x", reason="key")
    monkeypatch.setattr(ai_providers, "resolved", lambda *a, **k: oa)
    monkeypatch.setattr(ai_providers, "read_key",
                        lambda s, n: ("sk-ant-x", "env") if n == ai_providers.ANTHROPIC_API else ("", ""))
    notices._check_cli_lock_stranded(conn, Settings(), dbmod.utcnow_iso())
    row = [r for r in dbmod.open_notices(conn) if r["kind"] == "cli_lock_stranded"][0]
    assert "pinned" in row["body"] and "no AI API key" not in row["body"]
    assert "preference" in row["fix"]
    # the locked triage gate never reads the pin, so it is not dark here
    assert "server check" not in row["body"]
    monkeypatch.setattr(ai_providers, "read_key", lambda s, n: ("", ""))
    notices._check_cli_lock_stranded(conn, Settings(), dbmod.utcnow_iso())
    row = [r for r in dbmod.open_notices(conn) if r["kind"] == "cli_lock_stranded"][0]
    assert "not a Claude one" in row["body"]
