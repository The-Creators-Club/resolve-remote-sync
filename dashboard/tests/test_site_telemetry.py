"""G2b of the legal-gap features (docs/LEGAL_GAP_FEATURES_PLAN.md, 2026-09-25):
the site's telemetry policy (LG-1) from Settings, site.toml and the
environment, and the clear-on-save that makes a site switch true for every
computer at once; the Settings page's plain-http line (LG-4); the grey
"not reported" chips and the licence line (LG-1 / LG-5) on the fleet grid,
/account and the collector panel's retention line (LG-17).
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, health, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-value-telemetry-1234567890"
NOW = "2026-09-25T10:00:00+00:00"


def _machine(conn, editor="tchen", machine="TCHEN-RIG", **cols):
    dbmod.upsert_machine(conn, editor, machine, now=NOW)
    conn.execute(
        "INSERT OR IGNORE INTO machine_state (editor_username, machine, reported_at) "
        "VALUES (?, ?, ?)", (editor, machine, NOW))
    for key, value in cols.items():
        conn.execute(f"UPDATE machine_state SET {key}=? WHERE editor_username=? AND machine=?",
                     (value, editor, machine))
    conn.commit()


def _media(conn, editor="tchen", machine="TCHEN-RIG", slug="ff5"):
    conn.execute(
        "INSERT INTO editor_media_project (editor_username, machine, project_slug, reported_at)"
        " VALUES (?,?,?,?)", (editor, machine, slug, NOW))
    conn.execute(
        "INSERT INTO editor_media (editor_username, machine, project_slug, rel_path, kind,"
        " refreshed_at) VALUES (?,?,?,?,?,?)",
        (editor, machine, slug, "Footage/A001.mov", "original", NOW))
    conn.execute(
        "INSERT INTO media_tree_clips (editor_username, machine, project_slug, bin_path,"
        " clip_name, refreshed_at) VALUES (?,?,?,?,?,?)",
        (editor, machine, slug, "Master/Day 1", "A001.mov", NOW))
    conn.commit()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ------------------------------------------------------- the policy itself

def test_everything_is_reported_by_default(conn):
    settings = Settings(db_path=":memory:")
    manifest = site_store.resolved_manifest(conn, settings)
    assert manifest["telemetry"] == {"resolve_project": True, "local_manifest": True,
                                     "media_tree": True, "input_idle": True}
    assert site_store.telemetry_policy(conn, settings) == set()
    # No settings object at all is the product default too, never "off".
    assert site_store.telemetry_policy(conn) == set()


def test_the_env_spelling_is_zero_and_nothing_else():
    for value in ("", "1", "false", "no", "off", "False"):
        s = Settings.from_env({"DASH_SITE_TELEMETRY_INPUT_IDLE": value})
        assert s.site_telemetry_input_idle is True, value
    assert Settings.from_env(
        {"DASH_SITE_TELEMETRY_INPUT_IDLE": "0"}).site_telemetry_input_idle is False
    assert Settings.from_env(
        {"DASH_SITE_TELEMETRY_LOCAL_MANIFEST": " 0 "}).site_telemetry_local_manifest is False


def test_a_row_beats_the_environment_in_both_directions(conn):
    env_off = replace(Settings(db_path=":memory:"), site_telemetry_local_manifest=False)
    assert site_store.telemetry_policy(conn, env_off) == {"local_manifest"}
    site_store.set_many(conn, {"telemetry.local_manifest": "1"}, "owen", settings=env_off)
    assert site_store.telemetry_policy(conn, env_off) == set()
    site_store.set_many(conn, {"telemetry.input_idle": "0"}, "owen", settings=env_off)
    assert site_store.telemetry_policy(conn, env_off) == {"input_idle"}


def test_the_project_name_off_takes_the_bins_with_it(conn):
    site_store.set_many(conn, {"telemetry.resolve_project": "0"}, "owen")
    assert site_store.telemetry_policy(conn) == {"resolve_project", "media_tree"}
    # ...while the manifest keeps the admin's own media_tree choice.
    assert site_store.resolved_manifest(conn, Settings())["telemetry"]["media_tree"] is True


@pytest.mark.parametrize("raw", ["", " ", "true", "yes", "2"])
def test_a_blank_or_word_is_refused_not_read_as_off(raw):
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate("telemetry.local_manifest", raw)


def test_an_unreadable_table_falls_back_to_settings_and_never_raises():
    bare = sqlite3.connect(":memory:")
    bare.row_factory = sqlite3.Row
    off = replace(Settings(db_path=":memory:"), site_telemetry_input_idle=False)
    assert site_store.telemetry_policy(bare, off) == {"input_idle"}
    assert site_store.telemetry_policy(bare, Settings()) == set()


def test_an_unreadable_table_keeps_what_the_policy_last_applied():
    """A stored "0" must not lapse because one read failed: the set the last
    apply recorded stands in beside the environment."""
    bare = sqlite3.connect(":memory:")
    bare.row_factory = sqlite3.Row
    bare.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    bare.execute("INSERT INTO meta VALUES (?, ?)",
                 (dbmod.META_SITE_REPORT_OPTOUTS, '["local_manifest"]'))
    assert site_store.telemetry_policy(bare, Settings()) == {"local_manifest"}


# --------------------------------------------------- clear on every write

def test_switching_one_off_clears_every_machine_at_once(conn):
    _machine(conn, "tchen", "RIG", resolve_project="Doc Ep 1", cap_idle_seconds=40.0)
    _machine(conn, "leso", "MAC", resolve_project="Doc Ep 2")        # offline, same rule
    _media(conn, "tchen", "RIG")
    _media(conn, "leso", "MAC")
    site_store.set_many(conn, {"telemetry.local_manifest": "0"}, "owen")
    assert _count(conn, "editor_media") == 0 and _count(conn, "editor_media_project") == 0
    assert _count(conn, "media_tree_clips") == 2                      # not this category
    assert dbmod.withheld(conn, "leso", "MAC") == {"local_manifest"}
    site_store.set_many(conn, {"telemetry.resolve_project": "0"}, "owen")
    assert _count(conn, "media_tree_clips") == 0                      # implied
    assert conn.execute("SELECT COUNT(*) FROM machine_state WHERE resolve_project IS NOT NULL"
                        ).fetchone()[0] == 0


def test_a_write_without_a_telemetry_key_does_not_touch_the_policy(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(dbmod, "apply_site_optouts",
                        lambda c, names: calls.append(set(names)) or {})
    site_store.set_many(conn, {"org_name": "Studio"}, "owen")
    assert calls == []
    site_store.set_many(conn, {"telemetry.input_idle": "0"}, "owen")
    assert calls == [{"input_idle"}]


def test_the_toml_section_round_trips(conn):
    site_store.set_many(conn, {"telemetry.local_manifest": "0"}, "owen")
    text = site_store.export_toml(conn, Settings())
    assert "[telemetry]" in text
    assert "local_manifest = false" in text and "input_idle = true" in text
    parsed = site_store.import_toml(text)
    assert parsed["telemetry.local_manifest"] == "0"
    assert parsed["telemetry.resolve_project"] == "1"


def test_boot_applies_an_environment_policy_to_offline_machines(conn):
    _machine(conn, "tchen", "RIG", cap_idle_seconds=12.0)
    _media(conn)
    env_off = replace(Settings(db_path=":memory:"), site_telemetry_local_manifest=False)
    site_store.set_many(conn, {"org_name": "Already set"}, "owen")   # table not empty
    conn.commit()
    assert site_store.seed_from_env_once(conn, env_off) is False
    assert _count(conn, "editor_media") == 0
    assert dbmod.withheld(conn, "tchen", "RIG") == {"local_manifest"}


def test_boot_enforcement_never_raises(monkeypatch, conn):
    def boom(*_a, **_kw):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(dbmod, "apply_site_optouts", boom)
    assert site_store.enforce_telemetry_policy(conn, Settings()) is None


# ------------------------------------------------------- the admin routes

@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "telemetry.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), dev_insecure=True)
    app = create_app(settings)
    with TestClient(app) as client:
        client.app.state.collector.stop()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        conn = dbmod.connect(db_path)
        try:
            yield client, conn
        finally:
            conn.close()


def test_save_import_and_undo_all_go_through_the_clear(env):
    client, conn = env
    _machine(conn, "tchen", "RIG", resolve_project="Doc Ep 1")
    _media(conn)
    resp = client.put("/api/v1/admin/site",
                      json={"values": {"telemetry.resolve_project": "0"}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["telemetry"]["resolve_project"] is False
    assert _count(conn, "media_tree_clips") == 0
    assert conn.execute("SELECT resolve_project FROM machine_state").fetchone()[0] is None
    # The save is in the change history, so it can be undone.
    assert dbmod.site_history(conn)[0]["after"] == {"telemetry.resolve_project": "0"}

    undo = client.post("/api/v1/admin/site/undo-last-change")
    assert undo.status_code == 200, undo.text
    assert undo.json()["manifest"]["telemetry"]["resolve_project"] is True
    assert site_store.telemetry_policy(conn) == set()

    _media(conn, slug="ff6")
    imp = client.post("/api/v1/admin/site/import",
                      json={"text": "[telemetry]\nlocal_manifest = false\n"})
    assert imp.status_code == 200, imp.text
    assert _count(conn, "editor_media") == 0
    assert dbmod.withheld(conn, "tchen", "RIG") == {"local_manifest"}


def test_a_blank_telemetry_value_is_a_422_and_changes_nothing(env):
    client, conn = env
    _machine(conn)
    _media(conn)
    resp = client.put("/api/v1/admin/site", json={"values": {"telemetry.local_manifest": ""}})
    assert resp.status_code == 422
    assert _count(conn, "editor_media") == 1


def test_the_settings_route_counts_how_computers_arrive(env):
    client, conn = env
    _machine(conn, "a", "A", report_via="http_local")
    _machine(conn, "b", "B", report_via="http_local")
    _machine(conn, "c", "C", report_via="https")
    _machine(conn, "d", "D")                                        # not seen since v59
    body = client.get("/api/v1/admin/site").json()
    assert body["report_via_counts"] == {"https": 1, "http_local": 2, "http_public": 0}


def test_the_settings_page_draws_the_four_switches(env):
    client, conn = env
    site_store.set_many(conn, {"telemetry.input_idle": "0"}, "owen")
    conn.commit()
    client.app.state.__dict__.pop(site_store._CACHE_ATTR, None)
    page = client.get("/admin/settings")
    assert page.status_code == 200
    html = page.text
    assert "[ TELEMETRY ]" in html
    for name in ("resolve_project", "local_manifest", "media_tree", "input_idle"):
        assert f'name="telemetry.{name}"' in html
    assert 'data-telemetry="input_idle"\n                    data-initial="0"' in html
    assert 'data-telemetry="local_manifest"\n                    data-initial="1"' in html
    assert 'id="site-transport-line"' in html
    assert "—" not in html.split("[ TELEMETRY ]", 1)[1].split("[ B-ROLL", 1)[0]


# ------------------------------------------------------ the row facts

def test_withheld_sections_are_ordered_and_unknown_names_dropped():
    assert health.withheld_sections(["input_idle", "resolve_project", "sixth"]) == [
        {"name": "resolve_project", "label": "OPEN RESOLVE PROJECT"},
        {"name": "input_idle", "label": "IDLE TIME"}]
    assert health.withheld_sections(None) == []


def test_the_licence_line_judges_the_version_only():
    same = health.eula_status({"version": "1.1", "accepted_at": NOW,
                               "eula_sha256": "ab" * 32}, "1.1")
    assert (same["state"], same["colour"], same["text"]) == (
        "current", "green", "Licence 1.1 accepted")
    # A different sha under the same version is still current: the sha is
    # shown and never judged.
    assert health.eula_status({"version": "1.1", "eula_sha256": "00"}, "1.1")["state"] == "current"
    older = health.eula_status({"version": "1.0"}, "1.1")
    assert (older["state"], older["colour"], older["text"]) == (
        "older", "amber", "Older licence accepted")
    for absent in (None, {}, {"version": ""}, "junk"):
        line = health.eula_status(absent, "1.1")
        assert line["state"] == "not_reported" and line["text"] == "Not reported"
        assert line["colour"] == ""
    unjudged = health.eula_status({"version": "1.0"}, None)
    assert unjudged["colour"] == "" and unjudged["state"] == "current"
    every_text = {health.eula_status(b, v)["text"].lower()
                  for b in (None, {"version": "1.0"}, {"version": "1.1"})
                  for v in ("1.1", None)}
    assert not any("not accepted" in t for t in every_text)


def test_annotate_legal_reads_the_fleet_once(conn):
    _machine(conn, "tchen", "RIG", report_optouts='["local_manifest"]',
             eula_json='{"version": "1.0", "accepted_at": "%s"}' % NOW)
    _machine(conn, "leso", "MAC")
    entries = [{"editor_username": "tchen", "machine": "RIG"},
               {"editor_username": "leso", "machine": "MAC"}]
    health.annotate_legal(conn, entries, bundled_version="1.1")
    assert entries[0]["report_withheld"] == [{"name": "local_manifest", "label": "FILE LIST"}]
    assert entries[0]["eula"]["state"] == "older"
    assert entries[1]["report_withheld"] == []
    assert entries[1]["eula"]["state"] == "not_reported"


def test_the_bundled_version_is_the_setup_licence(monkeypatch, tmp_path):
    from ccsync_dashboard import setup_engine

    doc = tmp_path / "EULA.md"
    doc.write_text("<!-- EULA-VERSION: 7.3 -->\n# Licence\n", encoding="utf-8")
    monkeypatch.setattr(setup_engine, "eula_path", lambda: doc)
    assert health.bundled_eula_version() == "7.3"
    monkeypatch.setattr(setup_engine, "eula_path", lambda: tmp_path / "missing.md")
    assert health.bundled_eula_version() is None


def test_the_fleet_grid_draws_grey_chips_and_the_licence_line(env, monkeypatch):
    """With the entries annotated (the G2a hand-off: build_editors_view calls
    health.annotate_legal), the grid shows a GREY chip per withheld section,
    never counted as a note, and the licence line under the version."""
    from ccsync_dashboard import ui

    client, conn = env
    _machine(conn, "tchen", "RIG", companion_version="0.9.80",
             report_optouts='["local_manifest"]',
             eula_json='{"version": "1.1", "accepted_at": "%s"}' % NOW)
    real = ui.build_editors_view

    def annotated(c, now=None):
        view = real(c, now)
        health.annotate_legal(c, view.get("editors") or [], bundled_version="1.1")
        return view

    monkeypatch.setattr(ui, "build_editors_view", annotated)
    html = client.get("/").text
    assert "[ NOT REPORTED BY THIS COMPUTER: FILE LIST ]" in html
    assert 'class="chip grey"' in html
    assert f'title="{health.WITHHELD_HELP}"' in html
    assert '<span class="green">Licence 1.1 accepted</span>' in html
    # Never an open issue: the collapsed row's note count does not see it.
    assert health.detail_notes({"report_withheld": health.withheld_sections(
        ["local_manifest"])}) == []


def test_the_fleet_grid_says_nothing_without_the_facts(env):
    client, conn = env
    _machine(conn, "tchen", "RIG", companion_version="0.9.80")
    html = client.get("/").text
    assert "NOT REPORTED BY THIS COMPUTER" not in html
    # api.build_editors_view annotates every row (final review 2026-09-25),
    # so the licence line is drawn, and says only "Not reported" in grey:
    # never a colour, never "not accepted".
    assert '<span class="muted">Not reported</span>' in html
    assert "Licence " not in html and "Older licence accepted" not in html


def _render(name, **ctx):
    from ccsync_dashboard import ui

    return ui.templates.env.get_template(name).render(**ctx)


def test_the_account_computer_draws_the_same_licence_line():
    pc = {"machine": "RIG", "dom_id": "pc-rig", "companion_version": "0.9.80",
          "last_seen": NOW, "live": True, "plan": [], "jobs": {"gpu": ""},
          "readonly": [], "eula": health.eula_status({"version": "1.0"}, "1.1"),
          "report_withheld": health.withheld_sections(["input_idle"])}
    html = _render("partials/account_computer.html", pc=pc,
                   acct={"user": "tchen", "is_admin": False}, site={})
    assert '<dt>licence</dt>' in html
    assert '<span class="amber">Older licence accepted</span>' in html
    assert "[ IDLE TIME ]" in html
    bare = _render("partials/account_computer.html", pc={**pc, "eula": None,
                                                         "report_withheld": []},
                   acct={"user": "tchen", "is_admin": False}, site={})
    assert "<dt>licence</dt>" not in bare


def test_the_collector_panel_says_when_retention_last_ran():
    collector = {"kinds": [
        {"kind": "prune", "ok": True, "finished_at": NOW, "note": "overdue",
         "overdue": True, "status": "amber"},
        {"kind": "alerts", "ok": True, "finished_at": NOW, "note": None,
         "overdue": False, "status": "green"}],
        "collector_stale": False, "retention_last_ran": NOW, "enforce_plan": None}
    html = _render("partials/collector_health.html", fleet={"collector": collector})
    assert "Retention last ran" in html
    assert "[ OVERDUE ]" in html and "[ INCOMPLETE ]" not in html
    never = _render("partials/collector_health.html",
                    fleet={"collector": {**collector, "retention_last_ran": None}})
    assert "Retention last ran" in never and "never on this database" in never


# ------------------------------------------ review round (2026-09-25)
# The adversarial review of G2b found the Settings script did not parse (a
# raw line break inside the Save confirm's string), and that import and undo
# reach the same fleet-wide delete as Save without saying so.

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def _chrome() -> str | None:
    for cand in (os.environ.get("CHROME"),
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 shutil.which("google-chrome"), shutil.which("chromium"),
                 shutil.which("chrome")):
        if cand and Path(cand).exists():
            return cand
    return None


CHROME = _chrome()
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="no node on this machine")
def test_the_settings_script_parses():
    # A script that does not parse runs nothing: Save falls back to a native
    # form post and import, undo and the AI-provider controls go dead.
    out = subprocess.run(
        [NODE, "-e", "new (require('vm').Script)(require('fs').readFileSync("
                     "process.argv[1], 'utf8'))", str(STATIC / "site_settings.js")],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr


def test_the_import_preview_names_a_category_it_switches_off(env):
    client, conn = env
    # Five changes, the telemetry one last: the confirm names only three by
    # key, so the preview must carry it separately.
    text = ("[site]\norg_name = \"Other Studio\"\norg_short = \"OS\"\n"
            "tree_name = \"Vault2\"\ncanonical_prefix = \"Q:\\\\\"\n"
            "[telemetry]\nlocal_manifest = false\nresolve_project = true\n")
    resp = client.post("/api/v1/admin/site/import?dry_run=1", json={"text": text})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["telemetry_off"] == ["local_manifest"], body
    # Switching one back ON deletes nothing and is not named.
    client.put("/api/v1/admin/site", json={"values": {"telemetry.input_idle": "0"}})
    on = client.post("/api/v1/admin/site/import?dry_run=1",
                     json={"text": "[telemetry]\ninput_idle = true\n"}).json()
    assert on["telemetry_off"] == [], on


def test_the_history_names_what_an_undo_would_switch_off(env):
    client, conn = env
    client.put("/api/v1/admin/site", json={"values": {"telemetry.local_manifest": "0"}})
    client.put("/api/v1/admin/site", json={"values": {"telemetry.local_manifest": "1"}})
    entries = client.get("/api/v1/admin/site/history").json()["entries"]
    # Undoing the "back on" save switches reporting off again.
    assert entries[0]["telemetry_off"] == ["local_manifest"], entries
    assert "telemetry_off" not in entries[1]
    client.post("/api/v1/admin/site/undo-last-change")
    entries = client.get("/api/v1/admin/site/history").json()["entries"]
    # The newest entry is now the undo; undoing IT switches reporting on.
    assert "telemetry_off" not in entries[0], entries


SETTINGS_FETCH = r"""
window.__confirms = [];
window.confirm = function (m) { window.__confirms.push(m); return false; };
window.alert = function () {};
function answer(status, body) {
  return Promise.resolve({ok: status < 400, status: status, statusText: "x",
    json: function () { return Promise.resolve(body); }});
}
window.fetch = function (path, opts) {
  if (path.indexOf("/api/v1/admin/site/import?dry_run=1") === 0) {
    return answer(200, {count: 5, telemetry_off: ["local_manifest"], changes: [
      {key: "org_name", from: "A", to: "B"}, {key: "org_short", from: "A", to: "B"},
      {key: "tree_name", from: "A", to: "B"}, {key: "canonical_prefix", from: "P:", to: "Q:"},
      {key: "telemetry.local_manifest", from: "1", to: "0"}]});
  }
  if (path === "/api/v1/admin/site/history") {
    return answer(200, {entries: [{at: "2026-09-25T09:00:00+00:00", actor: "owen",
      action: "save", count: 1, telemetry_off: ["local_manifest"]}]});
  }
  return answer(200, {});
};
window.__done = function (result) {
  var pre = document.createElement("pre");
  pre.id = "out";
  pre.textContent = JSON.stringify(result);
  document.body.appendChild(pre);
};
window.addEventListener("error", function (e) {
  window.__done({error: String(e.message) + " @" + e.lineno});
});
"""


@pytest.mark.skipif(CHROME is None, reason="no Chrome on this machine")
def test_import_and_undo_confirms_say_what_is_deleted(env, tmp_path):
    client, _conn = env
    html = client.get("/admin/settings").text
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<link\b[^>]*>", "", html)
    scenario = """
var imp = document.getElementById("settings-import-form");
imp.text.value = "[telemetry]";
imp.dispatchEvent(new Event("submit", {cancelable: true}));
setTimeout(function () {
  document.getElementById("site-undo-btn").click();
  setTimeout(function () { window.__done({confirms: window.__confirms}); }, 300);
}, 300);
"""
    head = (f"<script>{SETTINGS_FETCH}</script>"
            f"<script src=\"{(STATIC / 'site_settings.js').as_uri()}\"></script>")
    tail = ("<script>document.addEventListener('DOMContentLoaded', function () {"
            "setTimeout(function () { try {" + scenario + "} catch (e) {"
            "window.__done({error: String(e && e.stack || e)}); } }, 300); });</script>")
    html = re.sub(r"<head>", lambda _m: "<head>" + head, html, count=1)
    html = html.replace("</body>", tail + "</body>", 1)
    page = tmp_path / "settings.html"
    page.write_text(html, encoding="utf-8")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
         "--virtual-time-budget=15000", "--dump-dom", page.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', out.stdout, flags=re.S)
    assert m, f"the page never reported: {out.stdout[-2000:]} {out.stderr[-2000:]}"
    raw = (m.group(1).replace("&quot;", '"').replace("&lt;", "<")
           .replace("&gt;", ">").replace("&amp;", "&"))
    result = json.loads(raw)
    assert "error" not in result, result
    confirms = result["confirms"]
    assert len(confirms) == 2, confirms
    for text in confirms:
        assert "deleted for every computer" in text, text
        assert "cannot be brought back" in text, text
        # The page's own tick label, not the internal key.
        assert "local_manifest" not in text.split("\n\n", 1)[-1], text
    assert "and 2 more" in confirms[0]
    assert confirms[1].startswith("Put back the 1 setting")
