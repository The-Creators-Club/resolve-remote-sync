"""The wizard's part of the legal-gap features (docs/LEGAL_GAP_FEATURES_PLAN.md,
group G8, 2026-09-25): the LG-1 privacy step, the LG-4 address check and the
LG-12 licences link. Headless, like the rest of this suite: every decision is
in steps.py, and nothing here touches the network (the transport resolver is
replaced for every test) or the developer's own ~/.ccsync.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import steps
from ccsync_companion import config as config_mod
from ccsync_companion import site as site_mod
from ccsync_companion import telemetry_policy
from ccsync_companion import transport

EM_DASH = "—"


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """A name the table cannot judge by shape is resolved; here it is
    answered from a dict, and an unknown name fails like a dead resolver
    (which transport reads as local: never refuse on doubt)."""
    answers: dict[str, list[str]] = {}

    def fake_resolve(host: str) -> list[str]:
        if host in answers:
            return answers[host]
        raise OSError("no such host (test)")

    monkeypatch.setattr(transport, "resolve", fake_resolve)
    transport.clear_cache()
    yield answers
    transport.clear_cache()


def _never_called(*_a, **_k):
    raise AssertionError("a request was sent to a refused address")


# -- LG-4: the address check -------------------------------------------------


def test_the_wizard_uses_the_companions_own_table_not_a_copy():
    assert steps.transport_mod is transport


@pytest.mark.parametrize("typed", [
    "http://8.8.8.8:8480",
    "8.8.8.8:8480",            # the normaliser gives an address http://
    "http://[2001:4860:4860::8888]:8480",
])
def test_plain_http_to_a_public_address_is_refused(typed):
    problem = steps.dashboard_url_problem(typed)
    assert problem and "plain http on the public internet" in problem
    assert "https address" in problem
    assert steps.dashboard_url_note(typed) is None


def test_a_name_that_resolves_only_to_public_addresses_is_refused(_no_real_dns):
    _no_real_dns["dash.studio-co.com"] = ["8.8.8.8", "8.8.4.4"]
    assert steps.dashboard_url_problem("http://dash.studio-co.com:8480")


@pytest.mark.parametrize("answers", [
    ["192.168.0.10"],                  # split-horizon DNS inside the studio
    ["8.8.8.8", "100.101.102.103"],    # any tailnet answer makes it local
])
def test_a_name_with_any_private_answer_is_allowed_with_the_note(_no_real_dns, answers):
    _no_real_dns["dash.studio-co.com"] = answers
    url = "http://dash.studio-co.com:8480"
    assert steps.dashboard_url_problem(url) is None
    assert steps.dashboard_url_note(url) == steps.CLEARTEXT_LOCAL_NOTE


def test_a_name_that_does_not_resolve_is_never_refused():
    url = "http://nowhere.studio-co.com:8480"
    assert steps.dashboard_url_problem(url) is None
    assert steps.dashboard_url_note(url) == steps.CLEARTEXT_LOCAL_NOTE


@pytest.mark.parametrize("typed", [
    "http://192.168.0.10:8480",        # the live fleet's address shape
    "192.168.0.104:8480",
    "http://100.65.15.123",
    "http://nas:8480",
    "http://nas.local:8480",
    "http://nas.tail26290e.ts.net:8443",
])
def test_lan_and_tailnet_http_is_accepted_with_the_note(typed):
    assert steps.dashboard_url_problem(typed) is None
    assert steps.dashboard_url_note(typed) == steps.CLEARTEXT_LOCAL_NOTE


@pytest.mark.parametrize("typed", [
    "https://dash.studio-co.com",
    "nas.tail26290e.ts.net",           # a bare tailnet name becomes https
    "http://localhost:8480",
    "http://127.0.0.1:8480",
    "",
])
def test_https_loopback_and_blank_carry_no_note_and_no_refusal(typed):
    assert steps.dashboard_url_problem(typed) is None
    assert steps.dashboard_url_note(typed) is None


def test_the_note_is_the_companion_settings_sentence():
    # Plan 4.4: the settings window and the wizard say the same thing.
    assert steps.CLEARTEXT_LOCAL_NOTE == (
        "This address is not https. It is fine on your studio network or tailnet.")


def test_sign_in_refuses_before_the_password_is_sent():
    result = steps.verify_account("http://8.8.8.8:8480", "alice", "hunter2",
                                  http_post=_never_called)
    assert result["ok"] is False
    assert "plain http on the public internet" in result["error"]


def test_sign_in_to_a_lan_address_still_goes_out():
    sent = []

    def fake_post(url, data, headers, timeout):
        sent.append(url)
        return {"ok": True, "username": "alice", "token": "t", "report_token": "r"}

    result = steps.verify_account("http://192.168.0.10:8480", "alice", "pw",
                                  http_post=fake_post)
    assert result["ok"] is True
    assert sent == ["http://192.168.0.10:8480/api/v1/verify"]


def test_the_ssh_key_offer_refuses_before_the_identity_token_is_sent():
    result = steps.submit_ssh_key("http://8.8.8.8:8480", "alice", "ident",
                                  "ssh-ed25519 AAAA test", http_post=_never_called)
    assert result["ok"] is False
    assert "plain http on the public internet" in result["error"]


def test_the_reachability_probe_names_the_refusal_without_connecting():
    probe = steps.dashboard_probe("http://8.8.8.8:8480", http_get=_never_called)
    assert probe["ok"] is False
    assert probe["kind"] == steps.DASHBOARD_REACH_CLEARTEXT
    assert "https address" in probe["message"]
    assert steps.dashboard_reachable("http://8.8.8.8:8480", http_get=_never_called) is False


def test_the_site_fetch_sends_nothing_to_a_refused_address():
    # Recorded rather than raised: fetch_site swallows every exception into
    # {}, so a raising fake would pass with the guard missing.
    calls = []
    assert steps.fetch_site("http://8.8.8.8:8480",
                            http_get=lambda url, timeout: calls.append(url) or {},
                            cache=False) == {}
    assert calls == []


# -- review round point 2: no redirect, and the guard on every hop ---------


def _serve(handler):
    import http.server
    import threading
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def redirect_pair():
    """A answers everything with a 302 to B; B records what reaches it."""
    import http.server
    seen: list = []

    class Target(http.server.BaseHTTPRequestHandler):
        def _any(self):
            seen.append((self.command, self.path, dict(self.headers)))
            body = b'{"ok": true, "fingerprint": "x"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_GET = do_POST = _any

        def log_message(self, *_a):
            pass

    target = _serve(Target)
    target_url = f"http://127.0.0.1:{target.server_address[1]}"

    class Bouncer(http.server.BaseHTTPRequestHandler):
        def _any(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self.send_response(302)
            self.send_header("Location", target_url + self.path)
            self.send_header("Content-Length", "0")
            self.end_headers()
        do_GET = do_POST = _any

        def log_message(self, *_a):
            pass

    bouncer = _serve(Bouncer)
    yield f"http://127.0.0.1:{bouncer.server_address[1]}", seen
    bouncer.shutdown()
    target.shutdown()


def test_the_identity_token_does_not_follow_a_redirect(redirect_pair):
    """The reviewer's repro against the old plain urlopen: the second hop
    received X-CCSync-Identity. Now the 302 stops the request where it is."""
    url, seen = redirect_pair
    result = steps.submit_ssh_key(url, "alice", "IDENT-TOKEN", "ssh-ed25519 AAAA test",
                                  timeout=5)
    assert seen == []
    assert result["ok"] is False
    assert "redirect (302)" in result["error"]
    assert "nothing more was sent" in result["error"]


def test_the_password_does_not_follow_a_redirect(redirect_pair):
    url, seen = redirect_pair
    result = steps.verify_account(url, "alice", "hunter2", timeout=5)
    assert seen == []
    assert result["ok"] is False and "redirect" in result["error"]


def test_the_probe_and_the_site_fetch_do_not_follow_a_redirect(redirect_pair):
    url, seen = redirect_pair
    probe = steps.dashboard_probe(url, timeout=5)
    assert probe["ok"] is False and "redirect" in probe["message"]
    assert steps.fetch_site(url, timeout=5, cache=False) == {}
    assert seen == []


def test_the_default_calls_carry_the_cleartext_guard():
    """The pre-check sees only the first address; the opener's guard sees
    every request it opens. Called directly, past the pre-check."""
    with pytest.raises(transport.CleartextRefused):
        steps.default_http_get("http://8.8.8.8:9/api/v1/health", 0.5)
    with pytest.raises(transport.CleartextRefused):
        steps.default_http_post("http://8.8.8.8:9/api/v1/verify", {}, {}, 0.5)


def test_a_refusal_on_the_wire_is_worded_like_the_pre_check():
    def refused(url, data, headers, timeout):
        raise transport.CleartextRefused(url)
    result = steps.verify_account("http://192.168.0.10:8480", "alice", "pw",
                                  http_post=refused)
    assert "plain http on the public internet" in result["error"]
    assert "nothing was sent" in result["error"]


# -- LG-1: the privacy step --------------------------------------------------


def test_the_four_switches_are_g1as_contract():
    assert steps.REPORT_CATEGORIES == (
        "resolve_project", "local_manifest", "media_tree", "input_idle")
    assert steps.REPORT_SWITCH_KEYS == (
        "report_resolve_project", "report_local_manifest",
        "report_media_tree", "report_input_idle")


def test_the_config_keys_match_the_companions_defaults_once_g1a_lands():
    """Plan 7.3, G1a -> G8: the names are G1a's. Skipped only while none of
    them exists yet (wave 1 builds in parallel); once any does, all four must
    be there, default True, or the wizard writes keys nothing reads."""
    present = [k for k in steps.REPORT_SWITCH_KEYS if k in config_mod.DEFAULTS]
    if not present:
        pytest.skip("companion config.py has no report_* keys yet (G1a not merged)")
    for key in steps.REPORT_SWITCH_KEYS:
        assert config_mod.DEFAULTS.get(key) is True, key


def test_a_first_run_reads_every_switch_as_on(tmp_path):
    assert steps.read_report_switches(tmp_path / "absent.toml") == {
        c: True for c in steps.REPORT_CATEGORIES}


def test_the_page_opens_on_what_this_computer_already_has(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'editor_name = "alice"\n'
        "report_resolve_project = false\n"
        "report_input_idle = false  # hand-typed\n",
        encoding="utf-8")
    got = steps.read_report_switches(cfg)
    assert got == {"resolve_project": False, "local_manifest": True,
                   "media_tree": True, "input_idle": False}


def test_a_value_that_is_not_a_bool_reads_as_off_like_the_companion(tmp_path):
    """Review round point 5: telemetry_policy withholds on a present non-bool,
    so the page must show it unticked, not tick it and write `true` over it."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('report_media_tree = "maybe"\nreport_input_idle = 0\n',
                   encoding="utf-8")
    got = steps.read_report_switches(cfg)
    assert got["media_tree"] is False
    assert got["input_idle"] is False
    assert got == telemetry_policy.local_switches(
        tomllib.loads(cfg.read_text(encoding="utf-8")))


def test_a_config_that_does_not_parse_is_read_from_its_last_good_copy(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("report_input_idle = False\n", encoding="utf-8")  # not TOML
    assert steps.read_report_switches(cfg) == {c: True for c in steps.REPORT_CATEGORIES}
    config_mod.backup_path(cfg).write_text("report_input_idle = false\n", encoding="utf-8")
    assert steps.read_report_switches(cfg)["input_idle"] is False


def test_ensure_config_writes_all_four_keys_as_toml_bools(tmp_path):
    cfg = tmp_path / "config.toml"
    steps.ensure_config(
        "base", editor_name="alice", dashboard_url="http://nas:8480",
        dashboard_token="tok", local_root=str(tmp_path), config_path=cfg,
        report_switches={"resolve_project": False, "local_manifest": True,
                         "media_tree": True, "input_idle": False})
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["report_resolve_project"] is False
    assert data["report_local_manifest"] is True
    assert data["report_media_tree"] is True
    assert data["report_input_idle"] is False
    # And the page reads back exactly what it wrote.
    assert steps.read_report_switches(cfg) == {
        "resolve_project": False, "local_manifest": True,
        "media_tree": True, "input_idle": False}


def test_a_rerun_replaces_the_keys_rather_than_appending_twice(tmp_path):
    cfg = tmp_path / "config.toml"
    kwargs = dict(editor_name="alice", dashboard_url="http://nas:8480",
                  dashboard_token="tok", local_root=str(tmp_path), config_path=cfg)
    steps.ensure_config("base", report_switches={"input_idle": False}, **kwargs)
    steps.ensure_config("base", report_switches={"input_idle": True}, **kwargs)
    text = cfg.read_text(encoding="utf-8")
    # Assignments only: the companion's template carries a commented example.
    assert len(re.findall(r"(?m)^report_input_idle\s*=", text)) == 1
    assert tomllib.loads(text)["report_input_idle"] is True


def test_no_answer_leaves_the_keys_exactly_as_they_were(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("report_local_manifest = false\n", encoding="utf-8")
    steps.ensure_config("base", editor_name="alice", dashboard_url="http://nas:8480",
                        dashboard_token="tok", local_root=str(tmp_path),
                        config_path=cfg, report_switches=None)
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["report_local_manifest"] is False
    assert "report_input_idle" not in data


def test_literals_drop_unknown_categories_and_default_missing_ones_on():
    assert steps.report_switch_literals({"input_idle": False, "bogus": False}) == {
        "report_resolve_project": "true", "report_local_manifest": "true",
        "report_media_tree": "true", "report_input_idle": "false"}
    assert steps.report_switch_literals(None) == {}


def test_the_site_policy_is_read_from_the_manifest():
    site = {"tree_name": "X", "telemetry": {
        "resolve_project": False, "local_manifest": True,
        "media_tree": "false", "input_idle": 0, "extra": False}}
    # Only an explicit False is off; a string or 0 is not a bool False.
    assert steps.site_telemetry_off(site) == {"resolve_project"}


def test_no_telemetry_block_means_the_site_withholds_nothing():
    assert steps.site_telemetry_off({"tree_name": "X"}) == set()
    assert steps.site_telemetry_off({"tree_name": "X", "telemetry": "off"}) == set()


def test_a_failed_fetch_falls_back_to_the_cached_manifest(monkeypatch):
    cached = {"dashboard_url": "http://nas:8480",
              "telemetry": {"input_idle": False}}
    monkeypatch.setattr(site_mod, "cached_site", lambda **_k: cached)
    assert steps.site_telemetry_off(None, "http://nas:8480") == {"input_idle"}
    # A cache from a different dashboard is not this site's policy.
    assert steps.site_telemetry_off(None, "http://other:8480") == set()


def test_a_broken_cache_is_nothing_withheld(monkeypatch):
    def boom(**_k):
        raise OSError("unreadable")
    monkeypatch.setattr(site_mod, "cached_site", boom)
    assert steps.site_telemetry_off(None, "http://nas:8480") == set()


def _rows_by_category(rows):
    return {row["category"]: row for row in rows}


def test_everything_on_shows_every_tick_ticked_and_live():
    rows = steps.privacy_rows({c: True for c in steps.REPORT_CATEGORIES}, set())
    assert [r["category"] for r in rows] == list(steps.REPORT_CATEGORIES)
    assert all(r["checked"] and r["enabled"] and not r["note"] for r in rows)


def test_a_site_switch_greys_the_row_out_and_says_who():
    choices = {c: True for c in steps.REPORT_CATEGORIES}
    rows = _rows_by_category(steps.privacy_rows(choices, {"input_idle"}))
    assert rows["input_idle"]["checked"] is False
    assert rows["input_idle"]["enabled"] is False
    assert rows["input_idle"]["note"] == (
        "Turned off for everyone by your administrator")
    # The computer's own answer underneath is untouched.
    assert choices["input_idle"] is True


@pytest.mark.parametrize("choices,site_off", [
    ({"resolve_project": False}, set()),
    ({}, {"resolve_project"}),
])
def test_the_project_name_off_takes_the_bins_with_it(choices, site_off):
    rows = _rows_by_category(steps.privacy_rows(choices, site_off))
    assert rows["media_tree"]["checked"] is False
    assert rows["media_tree"]["enabled"] is False
    assert rows["media_tree"]["note"] == steps.IMPLIED_OFF_NOTE


def test_a_greyed_row_keeps_this_computers_own_answer_on_disk(tmp_path):
    """The site's switch is the site's; if an admin turns it back on, this
    computer must be on its own previous choice, not a silent off."""
    choices = {c: True for c in steps.REPORT_CATEGORIES}
    steps.privacy_rows(choices, {"local_manifest"})
    literals = steps.report_switch_literals(choices)
    assert literals["report_local_manifest"] == "true"


def test_the_privacy_words_carry_no_em_dash():
    texts = [steps.PRIVACY_INTRO, steps.PRIVACY_STILL_SENT, steps.SITE_OFF_NOTE,
             steps.IMPLIED_OFF_NOTE, steps.CLEARTEXT_LOCAL_NOTE,
             steps.LICENSES_MISSING_TEXT]
    for row in steps.REPORT_SWITCHES:
        texts += [row["label"], row["cost"]]
    texts.append(steps.dashboard_url_problem("http://8.8.8.8") or "")
    assert not [t for t in texts if EM_DASH in t]


def test_the_page_names_what_is_still_sent():
    # Plan 4.1 / 8.1 "still sent", all four items (review round point 4).
    text = steps.PRIVACY_STILL_SENT
    assert text.startswith("Still sent")
    assert "being transferred and recently transferred" in text
    assert "file move the dashboard ordered" in text
    assert "project name you type or send when setting up a project" in text
    assert "Timeline Cards agent" in text and "project and timeline it is driving" in text


def test_every_cost_is_plan_8_1s_in_full():
    costs = {row["category"]: row["cost"] for row in steps.REPORT_SWITCHES}
    assert "not mapped automatically from this computer" in costs["resolve_project"]
    assert "be the first to map a Resolve project" in costs["resolve_project"]
    assert "every file move in every active project" in costs["local_manifest"]
    assert "holdings and upload progress as not reported" in costs["local_manifest"]
    assert "wait for an idle computer" in costs["input_idle"]


# -- review round point 5: the companion's copy, not the wizard's ------------


def _settings_window_constants():
    """settings_window imports Tk and the tray, so its labels are read from
    the source: the dict literal with telemetry_policy's names as keys."""
    import ast
    src = (Path(config_mod.__file__).parent / "settings_window.py").read_text(encoding="utf-8")
    found = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "REPORT_LABELS":
                found[name] = {getattr(telemetry_policy, k.attr): ast.literal_eval(v)
                               for k, v in zip(node.value.keys, node.value.values)}
            elif name in ("SITE_OFF_NOTE", "IMPLIED_OFF_NOTE"):
                found[name] = ast.literal_eval(node.value)
    return found


def test_the_labels_are_the_companion_settings_windows_word_for_word():
    theirs = _settings_window_constants()
    assert steps.REPORT_LABELS == theirs["REPORT_LABELS"]
    assert [row["label"] for row in steps.REPORT_SWITCHES] == [
        theirs["REPORT_LABELS"][c] for c in steps.REPORT_CATEGORIES]
    assert steps.SITE_OFF_NOTE == theirs["SITE_OFF_NOTE"]
    assert steps.IMPLIED_OFF_NOTE == theirs["IMPLIED_OFF_NOTE"]


def test_the_categories_keys_and_note_come_from_the_companion():
    assert steps.policy_mod is telemetry_policy
    assert steps.REPORT_CATEGORIES == telemetry_policy.CATEGORIES
    assert steps.REPORT_SWITCH_KEYS == tuple(
        telemetry_policy.CONFIG_KEYS[c] for c in telemetry_policy.CATEGORIES)
    assert steps.CLEARTEXT_LOCAL_NOTE is config_mod.DASHBOARD_URL_LOCAL_HTTP


def test_the_greying_follows_telemetry_policy_effective(monkeypatch):
    """The only copy of the rule is effective(). A rule it gains (here, a
    made-up one) must reach the page without touching the wizard."""
    real = telemetry_policy.effective

    def with_a_new_rule(cfg, site):
        eff = real(cfg, site)
        eff["input_idle"] = False
        return eff

    monkeypatch.setattr(telemetry_policy, "effective", with_a_new_rule)
    rows = _rows_by_category(
        steps.privacy_rows({c: True for c in steps.REPORT_CATEGORIES}, set()))
    assert rows["input_idle"]["checked"] is False
    assert rows["input_idle"]["enabled"] is False
    assert rows["input_idle"]["note"] == steps.IMPLIED_OFF_NOTE


def test_the_site_policy_is_telemetry_policys_site_withheld(monkeypatch):
    monkeypatch.setattr(telemetry_policy, "site_withheld", lambda site: ["media_tree"])
    assert steps.site_telemetry_off({"tree_name": "X"}) == {"media_tree"}


# -- review round point 3: a companion that ignores the switches -------------


def test_an_old_bundled_companion_is_warned_about_when_something_is_off():
    off = {c: True for c in steps.REPORT_CATEGORIES} | {"local_manifest": False}
    warning = steps.report_switches_install_warning(off, (0, 9, 80))
    assert warning and warning.startswith("WARNING") and "local_manifest" in warning
    assert "0.9.80" in warning
    assert steps.report_switches_install_warning(off, (0, 9, 70)).startswith("WARNING")
    assert steps.report_switches_install_warning(off, (0, 9, 81)) is None
    assert steps.report_switches_install_warning(off, (0, 10, 0)) is None
    unknown = steps.report_switches_install_warning(off, None)
    assert unknown and unknown.startswith("note:")
    assert EM_DASH not in warning + unknown


def test_nothing_switched_off_needs_no_warning():
    all_on = {c: True for c in steps.REPORT_CATEGORIES}
    assert steps.report_switches_install_warning(all_on, (0, 9, 4)) is None
    assert steps.report_switches_install_warning(None, (0, 9, 4)) is None


def test_the_bundled_companion_version_comes_from_its_release_manifest(tmp_path):
    exe = tmp_path / "ccsync-companion.exe"
    exe.write_bytes(b"MZ")
    assert steps.bundled_companion_version(exe) is None
    manifest = tmp_path / "ccsync-release.json"
    manifest.write_text('{"version": "0.9.80"}', encoding="utf-8")
    assert steps.bundled_companion_version(exe) == (0, 9, 80)
    manifest.write_text('{"version": "0.9.81+dirty"}', encoding="utf-8")
    assert steps.bundled_companion_version(exe) is None


# -- LG-12: the licences link ------------------------------------------------


def test_an_explicit_bundled_file_is_found_and_shown(tmp_path):
    bundled = tmp_path / steps.LICENSES_ASSET_NAME
    bundled.write_text("MIT License\n\nCopyright ...\n", encoding="utf-8")
    assert steps.find_licenses_file(bundled) == bundled
    assert steps.licenses_text(bundled).startswith("MIT License")


def test_a_frozen_build_looks_where_g6_bundles_it(tmp_path, monkeypatch):
    """Plan 7.3, G6: assets/THIRD_PARTY_LICENSES.txt beside EULA.md in the
    extraction folder."""
    target = tmp_path / "assets" / steps.LICENSES_ASSET_NAME
    target.parent.mkdir()
    target.write_text("texts", encoding="utf-8")
    monkeypatch.setattr(steps.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert steps.find_licenses_file() == target


def test_the_dev_tree_always_has_something_to_show():
    found = steps.find_licenses_file()
    assert found is not None and found.is_file()
    assert steps.licenses_text().strip()


def test_nothing_bundled_says_where_copies_come_from(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, "find_licenses_file", lambda asset_path=None: None)
    assert steps.licenses_text() == steps.LICENSES_MISSING_TEXT


def test_an_empty_file_is_treated_as_missing(tmp_path):
    empty = tmp_path / steps.LICENSES_ASSET_NAME
    empty.write_text("   \n", encoding="utf-8")
    assert steps.licenses_text(empty) == steps.LICENSES_MISSING_TEXT


# -- the GUI wiring (onboard.py has no display tests; pin the seams) ---------

ONBOARD_SRC = (Path(steps.__file__).resolve().parent / "onboard.py").read_text(encoding="utf-8")


def _method(name):
    return ONBOARD_SRC.split(f"def {name}(", 1)[1].split("\n    def ", 1)[0]


def test_the_role_page_refuses_a_public_http_address_off_the_tk_thread():
    """Review round point 6: the check can resolve a name, so it runs in the
    page's worker and the refusal comes back through _safe_after."""
    body = _method("_on_role_next")
    before, worker = body.split("def _worker", 1)
    assert "steps.dashboard_url_problem" in worker
    assert "steps.dashboard_url_problem" not in before
    assert "threading.Thread(target=_worker" in body
    assert "self._safe_after(_ui)" in body


def test_the_address_note_is_worked_out_off_the_tk_thread():
    body = _method("_dashboard_url_note")
    before, worker = body.split("def _worker", 1)
    assert "steps.dashboard_url_note" in worker
    assert "steps.dashboard_url_note" not in before
    assert "threading.Thread(target=_worker" in body


def test_the_install_is_refused_before_the_clean_slate_on_the_worker():
    begin = _method("_on_begin_install")
    assert "dashboard_url_problem" not in begin
    assert begin.index("self._install_url = ") < begin.index("threading.Thread")
    assert "steps.dashboard_url_problem(self._install_url)" in _method("_install_url_refused")
    for worker in ("_worker_editor", "_worker_base"):
        body = _method(worker)
        assert body.index("self._install_url_refused()") < body.index("self._clean_slate("), worker


def test_the_install_log_warns_about_a_companion_that_ignores_the_switches():
    write = _method("_write_config_and_identity")
    assert "steps.report_switches_install_warning(" in write
    assert "steps.bundled_companion_version()" in write


def test_sign_in_leads_to_the_privacy_page_and_install_writes_its_answers():
    assert "self.show_privacy()" in ONBOARD_SRC
    write = ONBOARD_SRC.split("def _write_config_and_identity", 1)[1].split("\n    def ", 1)[0]
    assert "report_switches=self.report_choices" in write


def test_both_finish_pages_link_the_licences():
    nav = ONBOARD_SRC.split("def _finish_nav", 1)[1].split("\n    def ", 1)[0]
    assert "OPEN-SOURCE LICENCES" in nav
    assert ONBOARD_SRC.count("self._finish_nav(frame)") == 2
