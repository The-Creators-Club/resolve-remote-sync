"""LG-1 on the companion: the four reporting switches (telemetry_policy.py).

docs/LEGAL_GAP_FEATURES_PLAN.md section 4.1 (2026-09-25). What is pinned
here, and why each matters:

  * the rule: local AND site, and no project name means no bin structure;
  * the FIELDS table: every row is really removed from a report, and a
    report always says which categories it withheld;
  * COLLECT, THEN WITHHOLD: the media-pool walk still recovers the Resolve
    bridge and relinks proxies with the switch off (safety audit H2);
  * the site half survives normalise -> save -> cached_site (buildability H2);
  * nobody but the person at the computer can switch one back on (safety L2);
  * the LG-4 address rule in config and the settings window, and the tray
    line when the guard refuses a report.
"""
from __future__ import annotations

import itertools
import json
import re
import time
from pathlib import Path

import pytest

from ccsync_companion import capabilities as caps_mod
from ccsync_companion import config as config_mod
from ccsync_companion import identity as identity_mod
from ccsync_companion import machine_settings
from ccsync_companion import reporter as reporter_mod
from ccsync_companion import resolve_bridge, resolve_journal
from ccsync_companion import settings_window as sw
from ccsync_companion import site as site_mod
from ccsync_companion import telemetry_policy as tp
from ccsync_companion import transport
from ccsync_companion.app import CompanionApp, real_journal_id
from ccsync_companion.settings_window import Button, Line

REPO = Path(__file__).resolve().parents[2]


# -- a report carrying every field the table names ----------------------------

def _full_payload() -> dict:
    return {
        "editor_name": "owen",
        "machine": "EDIT-1",
        "resolve_project": "FF5 Civil Defence",
        "local_manifest": {"Projects/2026/FF5": {"files": [["a.mov", 1, 2]]}},
        "media_tree": {"FF5 Civil Defence": [{"bin_path": "A", "clip_name": "c"}]},
        "capabilities": {"resolve": {"running": True, "project": "FF5 Civil Defence"},
                         "idle_seconds": 412.0, "cards_agent": {"project": "Cards"}},
        "resolve_journals": [{"id": "FF5 Civil Defence/20260925-101010.json",
                              "project": "FF5 Civil Defence", "entries": 2}],
        "sync_guard": {
            "resolve_health": {"open_project": "FF5 Civil Defence",
                               "project_open": "FF5 Civil Defence",
                               "missing": 1,
                               "missing_clips": [{"name": "a", "path": "P:/x/a.mov"}],
                               "non_canonical_refused": [{"name": "b", "path": "F:/b.mov"}]},
            "sync_conflicts": {"count": 2, "paths": ["P:/x/a.sync-conflict.mov"]},
            "stray_projects": {"count": 1, "rels": ["Projects/Old"]},
            "moved_project_dirs": [{"rel": "Projects/Gone"}],
            "skipped_exists": {"count": 3, "samples": ["Projects/2026/FF5/a.mov"]},
            "reporter": {"last_status": "ok"},
        },
        "resolve_undo_applied": [{
            "id": 7, "ok": False, "state": "retrying",
            "detail": ("That change was made in \u201cFF5 Civil Defence\u201d but "
                       "\u201cOther\u201d is open.")}],
        "active_transfers": [{"name": "P:/x/still-sent.mov"}],
        "completed": [{"path": "P:/x/also-sent.mov"}],
        "file_moves_applied": [{"id": 1, "state": "done"}],
    }


def _get(payload, path):
    """The value at a FIELDS path, or a sentinel when absent anywhere."""
    node = payload
    for part in path.split("."):
        is_list = part.endswith("[]")
        key = part[:-2] if is_list else part
        if not isinstance(node, dict) or key not in node:
            return _ABSENT
        node = node[key]
        if is_list:
            return node
    return node


_ABSENT = object()


# -- the rule ------------------------------------------------------------------

@pytest.mark.parametrize("local_bits,site_bits", list(itertools.product(
    list(itertools.product([True, False], repeat=4)),
    list(itertools.product([True, False], repeat=4)))))
def test_effective_is_local_and_site_with_the_project_implying_the_bins(local_bits, site_bits):
    cfg = {tp.CONFIG_KEYS[n]: v for n, v in zip(tp.CATEGORIES, local_bits)}
    site = {"telemetry": dict(zip(tp.CATEGORIES, site_bits))}
    eff = tp.effective(cfg, site)
    for name, local, remote in zip(tp.CATEGORIES, local_bits, site_bits):
        want = local and remote
        if name == tp.MEDIA_TREE:
            want = want and eff[tp.RESOLVE_PROJECT]
        assert eff[name] is want, name


def test_resolve_project_off_switches_the_bins_off_too():
    eff = tp.effective({"report_resolve_project": False}, None)
    assert eff[tp.MEDIA_TREE] is False
    assert tp.withheld(eff) == ["media_tree", "resolve_project"]


def test_absent_keys_and_no_site_keep_todays_behaviour():
    assert tp.withheld(tp.effective({}, None)) == []
    assert tp.withheld(tp.effective({}, {"schema": 1})) == []


def test_only_a_real_false_from_the_site_switches_off():
    site = {"telemetry": {"resolve_project": "false", "local_manifest": 0,
                          "media_tree": None, "input_idle": False}}
    assert tp.site_withheld(site) == ["input_idle"]


def test_a_wrong_typed_local_switch_withholds_and_is_warned_about(tmp_path):
    assert tp.local_switches({"report_local_manifest": "yes"})["local_manifest"] is False
    _, warnings = config_mod.validate_config({"report_local_manifest": "yes"})
    assert any("report_local_manifest must be true or false" in w for w in warnings)


def test_the_site_whitelist_names_the_same_four():
    assert site_mod.TELEMETRY_KEYS == tp.CATEGORIES
    assert set(tp.FIELDS) == set(tp.CATEGORIES)
    for name in tp.CATEGORIES:
        assert config_mod.DEFAULTS[tp.CONFIG_KEYS[name]] is True


# -- the FIELDS table ------------------------------------------------------------

_ROWS = [(name, path) for name, paths in tp.FIELDS.items() for path in paths]


@pytest.mark.parametrize("name,path", _ROWS)
def test_every_fields_row_is_withheld(name, path):
    payload = _full_payload()
    assert _get(payload, path) is not _ABSENT, f"the fixture lacks {path}"
    eff = {n: n != name for n in tp.CATEGORIES}
    out = tp.strip(payload, eff)
    if path == "resolve_journals[].id":
        values = [j.get("id") for j in out["resolve_journals"]]
        assert values == ["withheld:project/20260925-101010.json"]
        assert all("FF5" not in v for v in values)
    elif path == "resolve_undo_applied[].detail":
        (answer,) = out["resolve_undo_applied"]
        assert "FF5" not in answer["detail"] and "Other" not in answer["detail"]
        assert answer["state"] == "retrying" and "<project>" in answer["detail"]
    elif "[]." in path:
        head, leaf = path.split("[].")
        for item in _get(out, head + "[]"):
            assert leaf not in item
    else:
        assert _get(out, path) is _ABSENT


def test_strip_keeps_what_sync_needs_and_never_edits_the_original():
    payload = _full_payload()
    before = json.dumps(payload, sort_keys=True)
    out = tp.strip(payload, {n: False for n in tp.CATEGORIES})
    assert json.dumps(payload, sort_keys=True) == before
    assert out["sync_guard"]["sync_conflicts"] == {"count": 2}
    assert out["sync_guard"]["skipped_exists"] == {"count": 3}
    assert out["active_transfers"] == payload["active_transfers"]
    assert out["completed"] == payload["completed"]
    assert out["file_moves_applied"] == payload["file_moves_applied"]
    # The Timeline Cards agent's project is on the "still sent" list.
    assert out["capabilities"]["cards_agent"] == {"project": "Cards"}
    assert out["capabilities"]["resolve"] == {"running": True}
    assert "FF5 Civil Defence" not in json.dumps(out)


def test_nothing_withheld_is_a_no_op():
    payload = _full_payload()
    assert tp.strip(payload, tp.effective({}, None)) == payload


def test_a_strange_shape_is_left_alone_rather_than_raising():
    payload = {"sync_guard": "not a dict", "resolve_journals": "nor a list",
               "capabilities": None}
    out = tp.strip(payload, {n: False for n in tp.CATEGORIES})
    assert out["sync_guard"] == "not a dict"
    assert out["resolve_journals"] == "nor a list"


# -- note J: the undo still reaches the journal -----------------------------------

def _write_journal(project, name):
    root = resolve_journal.journal_root() / resolve_journal.project_slug(project)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(json.dumps({"project": project, "entries": []}), encoding="utf-8")
    return path


def test_an_opaque_journal_id_maps_back_to_the_one_journal_it_names():
    _write_journal("FF5 Civil Defence", "20260925-101010.json")
    _write_journal("Other", "20260925-111111.json")
    opaque = tp.opaque_journal_id("FF5 Civil Defence/20260925-101010.json")
    assert opaque == "withheld:project/20260925-101010.json"
    assert real_journal_id(opaque) == "FF5 Civil Defence/20260925-101010.json"
    # A real id passes through untouched.
    assert real_journal_id("Other/20260925-111111.json") == "Other/20260925-111111.json"


def test_an_ambiguous_or_unknown_opaque_id_is_not_guessed():
    _write_journal("A proj", "20260925-121212.json")
    _write_journal("B proj", "20260925-121212.json")
    opaque = "withheld:project/20260925-121212.json"
    assert real_journal_id(opaque) == opaque
    assert resolve_journal.session_by_id(opaque) is None
    assert real_journal_id("withheld:project/nope.json") == "withheld:project/nope.json"


# -- the reporter ----------------------------------------------------------------------

class _Status:
    def __init__(self):
        self.name, self.state, self.queued, self.transferring = "a", "idle", 0, 0
        self.last_error = self.last_sync = self.detail = self.current_project = None
        self.bytes_done = self.bytes_total = self.speed_bps = self.eta_seconds = None
        self.transfers = []


def _reporter(cfg=None, site=None, **getters):
    base = {"dashboard_url": "https://dash.example", "editor_name": "owen"}
    base.update(cfg or {})
    return reporter_mod.DashboardReporter(
        lambda: [_Status()], base, get_site=lambda: site, **getters)


def test_the_report_always_says_what_it_withheld():
    rep = _reporter()
    payload = rep._build_payload(light=True)
    assert payload["report_optouts"] == []
    rep = _reporter(site={"telemetry": {"input_idle": False}})
    assert rep._build_payload(light=True)["report_optouts"] == ["input_idle"]


def test_collect_then_withhold_in_the_reporter():
    calls = {"manifest": 0, "tree": 0, "project": 0}

    def manifest():
        calls["manifest"] += 1
        return {"P": {"files": []}}

    def tree():
        calls["tree"] += 1
        return {"X": []}

    def project():
        calls["project"] += 1
        return "X"

    rep = _reporter({"report_local_manifest": False, "report_resolve_project": False},
                    get_local_manifest=manifest, get_media_tree=tree,
                    get_resolve_project=project,
                    get_sync_guard=lambda: {"sync_conflicts": {"count": 3, "paths": ["p"]}})
    payload = rep._build_payload(light=False)
    assert calls == {"manifest": 1, "tree": 1, "project": 1}
    for key in ("local_manifest", "media_tree", "resolve_project"):
        assert key not in payload
    assert payload["sync_guard"]["sync_conflicts"] == {"count": 3}
    assert payload["report_optouts"] == ["local_manifest", "media_tree", "resolve_project"]


def test_a_live_switch_change_reaches_the_next_report():
    rep = _reporter(get_resolve_project=lambda: "X")
    assert rep._build_payload(light=True)["resolve_project"] == "X"
    rep.cfg["report_resolve_project"] = False
    assert "resolve_project" not in rep._build_payload(light=True)


def test_a_section_switched_off_then_on_within_the_resend_window_is_sent_again():
    # G1a review round 1 (2026-09-25): the unchanged-section stamp outlived a
    # withhold, so the manifest stayed away for up to 10 minutes after the
    # switch came back on, while the dashboard had already dropped the rows.
    rep = _reporter(get_local_manifest=lambda: {"P": {"files": []}},
                    get_media_tree=lambda: {"X": []})
    first = rep._build_payload(light=False)
    assert "local_manifest" in first
    rep._note_sections_sent(first)
    rep.cfg["report_local_manifest"] = False
    off = rep._build_payload(light=False)
    assert "local_manifest" not in off and off["report_optouts"] == ["local_manifest"]
    rep._note_sections_sent(off)
    rep.cfg["report_local_manifest"] = True
    back = rep._build_payload(light=False)
    assert "local_manifest" in back and back["report_optouts"] == []
    # The bins never changed state and are still suppressed as unchanged.
    assert "media_tree" not in back


def test_an_unreadable_site_is_all_on_and_the_report_still_builds():
    def boom():
        raise OSError("gone")
    rep = reporter_mod.DashboardReporter(
        lambda: [_Status()], {"dashboard_url": "https://d.example"}, get_site=boom)
    assert rep._build_payload(light=True)["report_optouts"] == []


# -- COLLECT, THEN WITHHOLD in the app (safety audit H2) ---------------------------------

def _app(tmp_path, **over):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    cfg = {"editor_name": "owen", "local_root": str(root), "canonical_prefix": "P:\\",
           "remote": "r", "remote_root": "/mnt/tank/Tree", "poll_interval": 3,
           "log_path": str(tmp_path / "companion.log"), "dashboard_url": "",
           "sync_enabled": False, "lane_b_enabled": False}
    cfg.update(over)
    return CompanionApp(cfg)


def test_the_media_pool_walk_still_runs_with_the_bins_switched_off(tmp_path, monkeypatch):
    app = _app(tmp_path, report_media_tree=False)
    counts = {"recover": 0, "relink": 0, "classify": 0}
    monkeypatch.setattr(app, "_maybe_recover_stale_bridge",
                        lambda: counts.__setitem__("recover", counts["recover"] + 1))
    monkeypatch.setattr(app, "_relink_proxies_once",
                        lambda items: counts.__setitem__("relink", counts["relink"] + 1))
    monkeypatch.setattr(app, "_classify_pool_once",
                        lambda items: counts.__setitem__("classify", counts["classify"] + 1))
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: {
        "ok": True, "project_name": "FF5", "items": [
            {"file_path": "P:/x/a.mov", "clip_name": "a", "bin_path": "Master"}]})
    app._refresh_media_tree_once()
    assert counts == {"recover": 1, "relink": 1, "classify": 1}
    assert app.get_media_tree() == {}

    # And with the switch on, the same walk fills the cache as before.
    app.config["report_media_tree"] = True
    app._refresh_media_tree_once()
    assert list(app.get_media_tree()) == ["FF5"]


def test_the_manifest_walk_is_untouched_and_the_conflict_count_still_goes(tmp_path):
    app = _app(tmp_path, report_local_manifest=False)
    app.manifest_cache._conflicts = {"count": 2, "paths": ["P:/x.sync-conflict"]}
    guard = app.sync_guard()
    assert guard["sync_conflicts"]["count"] == 2        # collected
    stripped = tp.strip({"sync_guard": guard}, tp.effective(app.config, None))
    assert stripped["sync_guard"]["sync_conflicts"] == {"count": 2}   # withheld


def test_diagnostics_are_redacted_when_a_content_switch_is_off(tmp_path):
    app = _app(tmp_path, report_resolve_project=False)
    app.watcher.last_resolve_project = "Secret Project Nine"
    text = app.build_diagnostics()
    assert "Secret Project Nine" not in text
    assert "<project>" in text
    assert "this computer withholds" in text
    # Switched on, the bundle is as it always was.
    app.config["report_resolve_project"] = True
    assert "Secret Project Nine" in app.build_diagnostics()


def test_diagnostics_redact_every_project_this_machine_knows(tmp_path):
    # G1a review round 1 (2026-09-25): the open project alone missed the
    # names in the log tail from before a switch, all of them with Resolve
    # closed, and the journal folder's slug (not the name when it has `/`).
    _write_journal("FF4 / interviews v2", "20260925-131313.json")
    app = _app(tmp_path, report_resolve_project=False)
    app.watcher.last_resolve_project = None
    slug_path = str(resolve_journal.journal_root() / "FF4 _ interviews v2"
                    / "20260925-131313.json")
    app._diagnostic_log_tail = lambda n: [
        "opened FF4 / interviews v2 at 10:00",
        "journal written: " + slug_path,
        "project Earlier Cut closed"]
    app.watcher._last_seen_project = "Earlier Cut"
    text = app.build_diagnostics()
    assert "interviews v2" not in text
    assert "Earlier Cut" not in text
    assert "20260925-131313" not in text
    assert "<project>" in text


def test_an_undo_answer_names_no_project_while_the_name_is_withheld(tmp_path):
    _write_journal("Night Market", "20260925-141414.json")
    app = _app(tmp_path, report_resolve_project=False)
    detail = ("That change was made in \u201cNight Market\u201d but \u201cDay Cut\u201d "
              "is open. Open Night Market and undo there.")
    app._queue_resolve_undo_answer(5, False, detail, "retrying")
    (answer,) = app._resolve_undo_results()
    assert "Night Market" not in answer["detail"]
    assert "Day Cut" not in answer["detail"]
    assert answer["state"] == "retrying" and answer["id"] == 5
    # Reported: the undo still works and says so in full.
    app.config["report_resolve_project"] = True
    app._queue_resolve_undo_answer(6, False, detail, "retrying")
    (answer,) = app._resolve_undo_results()
    assert answer["detail"] == detail


def test_the_undo_mask_is_name_agnostic_for_an_older_build():
    text = ("this computer no longer has the record FF4 _ interviews v2/"
            "20260925-101010.json: it has been cleared")
    assert tp.redact_undo_detail(text) == (
        "this computer no longer has the record withheld:project/"
        "20260925-101010.json: it has been cleared")
    assert tp.redact_undo_detail("Put 3 clip path(s) back") == "Put 3 clip path(s) back"


def test_startup_never_asks_dns_about_the_dashboard_address(monkeypatch):
    # G1a review round 1: getaddrinfo on broken DNS blocks for seconds, and
    # validate_config runs in CompanionApp.__init__.
    asked = []
    monkeypatch.setattr(transport, "resolve", lambda host: asked.append(host) or ["8.8.8.8"])
    transport.clear_cache()
    cfg = {"dashboard_url": "http://dash.somestudio-public.com:8480", "dashboard_token": "t"}
    errors, warnings = config_mod.validate_config(cfg)
    assert asked == []
    assert not any("plain http" in e for e in errors)
    assert any(config_mod.DASHBOARD_URL_LOCAL_HTTP in w for w in warnings)
    # A SAVE still asks, and refuses a public answer.
    errors, _ = config_mod.validate_config(cfg, for_save=True)
    assert asked == ["dash.somestudio-public.com"]
    assert any("plain http on the internet" in e for e in errors)
    transport.clear_cache()


def test_the_window_never_waits_on_dns_for_the_address(monkeypatch):
    import threading

    release = threading.Event()
    asked = []

    def slow(host):
        asked.append(host)
        release.wait(5)
        return ["8.8.8.8"]

    monkeypatch.setattr(transport, "resolve", slow)
    transport.clear_cache()
    sw._address_verdicts.clear()
    sw._address_pending.clear()
    url = "http://dash.somestudio-public.com"
    started = time.monotonic()
    first = _texts(sw._address_lines(_SettingsApp({"dashboard_url": url})))
    assert time.monotonic() - started < 1.0
    assert any(config_mod.DASHBOARD_URL_LOCAL_HTTP in t for t in first)
    release.set()
    deadline = time.monotonic() + 5
    while url not in sw._address_verdicts and time.monotonic() < deadline:
        time.sleep(0.01)
    lines = _texts(sw._address_lines(_SettingsApp({"dashboard_url": url})))
    assert any("plain http on the internet" in t for t in lines)
    assert asked == ["dash.somestudio-public.com"]
    sw._address_verdicts.clear()
    transport.clear_cache()


def test_capabilities_blank_the_project_and_the_idle_time(tmp_path):
    caps_mod.reset_cache()

    class Idle:
        def seconds_idle(self):
            return 99.0

    kw = dict(idle_probe=Idle(), resolve_running_fn=lambda: True,
              resolve_project_fn=lambda: "FF5")
    cfg = {"local_root": str(tmp_path)}
    full = caps_mod.build(cfg, **kw)
    assert full["idle_seconds"] == 99.0 and full["resolve"]["project"] == "FF5"
    held = caps_mod.build(cfg, withheld={"resolve_project", "input_idle"}, **kw)
    assert held["idle_seconds"] is None and held["resolve"]["project"] == ""
    # The cached assembly keeps what was collected.
    assert caps_mod.build(cfg, **kw)["resolve"]["project"] == "FF5"
    # Decision D4: no jobs, no idle time.
    assert caps_mod.build({**cfg, "jobs_enabled": False}, **kw)["idle_seconds"] is None
    caps_mod.reset_cache()


# -- the site half survives the cache (buildability audit H2) -------------------------------

class _Resp:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")
        self.status = 200

    def read(self):
        return self._body

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_site_false_survives_fetch_normalise_save_and_the_cache(tmp_path):
    body = {"schema": 1, "telemetry": {"resolve_project": True, "local_manifest": False,
                                       "media_tree": "junk", "input_idle": False,
                                       "unknown": False}}
    path = tmp_path / "site.json"
    got = site_mod.refresh_site("https://dash.example", path=path,
                                http_open=lambda url, timeout: _Resp(body))
    assert got["telemetry"] == {"resolve_project": True, "local_manifest": False,
                                "media_tree": True, "input_idle": False}
    cached = site_mod.cached_site(path)
    assert cached["telemetry"] == got["telemetry"]
    assert tp.site_withheld(cached) == ["input_idle", "local_manifest"]


def test_a_manifest_without_the_block_is_all_on():
    site = site_mod.normalise({"schema": 1})
    assert site["telemetry"] == {n: True for n in tp.CATEGORIES}


# -- never remote-controlled (safety audit L2) ------------------------------------------------

def test_the_report_switches_are_not_in_either_machine_settings_allow_list():
    keys = set(tp.CONFIG_KEYS.values())
    assert not keys & set(machine_settings.ACCEPTS)
    db_py = (REPO / "dashboard" / "src" / "ccsync_dashboard" / "db.py").read_text(
        encoding="utf-8")
    match = re.search(r"^MACHINE_SETTING_KEYS\s*=\s*\(([^)]*)\)", db_py, re.MULTILINE)
    assert match, "db.MACHINE_SETTING_KEYS moved; point this test at it"
    assert not any(k in match.group(1) for k in keys)


# -- LG-4: the address rule in config and in the window ---------------------------------------

def test_a_public_plain_http_address_refuses_a_save_but_never_stops_the_start():
    cfg = {"dashboard_url": "http://8.8.8.8:8480", "dashboard_token": "t"}
    errors, warnings = config_mod.validate_config(cfg)
    assert not any("plain http on the internet" in e for e in errors)
    assert any("plain http on the internet" in w for w in warnings)
    errors, _ = config_mod.validate_config(cfg, for_save=True)
    assert any("plain http on the internet" in e for e in errors)


def test_a_studio_address_is_a_note_and_https_is_silent():
    _, warnings = config_mod.validate_config(
        {"dashboard_url": "http://192.168.0.10:8480", "dashboard_token": "t"}, for_save=True)
    assert any(config_mod.DASHBOARD_URL_LOCAL_HTTP in w for w in warnings)
    _, warnings = config_mod.validate_config(
        {"dashboard_url": "https://dash.example", "dashboard_token": "t"})
    assert not any("https" in w and "not https" in w for w in warnings)


def test_the_reporter_names_a_refusal_once(tmp_path):
    toasts = []
    rep = reporter_mod.DashboardReporter(
        lambda: [], {"dashboard_url": "http://8.8.8.8"}, notify=toasts.append,
        get_site=lambda: None, state_dir=tmp_path)
    exc = transport.CleartextRefused("http://8.8.8.8/api/v1/report")
    rep._note_failure(exc)
    rep._note_failure(exc)
    assert toasts == [reporter_mod.CLEARTEXT_REFUSED_LINE]
    assert rep.last_status == reporter_mod.CLEARTEXT_REFUSED_STATUS
    assert reporter_mod.CLEARTEXT_REFUSED_LINE == identity_mod.CLEARTEXT_REFUSED_MESSAGE


class _SettingsApp:
    def __init__(self, cfg):
        self.config = cfg


def _texts(items):
    return [i.text if isinstance(i, Line) else i.label for i in items]


def test_the_window_notes_a_studio_address_and_warns_on_a_public_one():
    sw._address_verdicts.clear()
    lines = _texts(sw._address_lines(_SettingsApp({"dashboard_url": "http://192.168.0.10:8480"})))
    assert "Dashboard address: http://192.168.0.10:8480" in lines
    assert any(config_mod.DASHBOARD_URL_LOCAL_HTTP in t for t in lines)
    lines = _texts(sw._address_lines(_SettingsApp({"dashboard_url": "http://8.8.8.8"})))
    assert any("plain http on the internet" in t for t in lines)
    assert _texts(sw._address_lines(_SettingsApp({"dashboard_url": "https://d.example"}))) == [
        "Dashboard address: https://d.example"]


# -- the PRIVACY block -------------------------------------------------------------------------

def test_privacy_rows_tick_what_is_reported():
    items = sw._privacy_controls(_SettingsApp({"report_input_idle": False}))
    buttons = [i.label for i in items if isinstance(i, Button)]
    assert f"  [x] {sw.REPORT_LABELS['resolve_project']}" in buttons
    assert f"  [ ] {sw.REPORT_LABELS['input_idle']}" in buttons


def test_a_site_switch_is_greyed_and_cannot_be_ticked_back_on():
    site_mod.save_site(site_mod.normalise(
        {"schema": 1, "telemetry": {"local_manifest": False, "resolve_project": False}}))
    items = sw._privacy_controls(_SettingsApp({}))
    lines = [i.text for i in items if isinstance(i, Line)]
    buttons = [i.label for i in items if isinstance(i, Button)]
    assert any(sw.SITE_OFF_NOTE in t and sw.REPORT_LABELS["local_manifest"] in t
               for t in lines)
    assert any(sw.IMPLIED_OFF_NOTE in t for t in lines)            # bins follow the name
    assert not any(sw.REPORT_LABELS["local_manifest"] in b for b in buttons)
    assert any(sw.REPORT_LABELS["input_idle"] in b for b in buttons)


def test_unticking_writes_the_file_and_takes_effect_at_once(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    config_mod.ensure_config_exists(path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    notes = []
    monkeypatch.setattr(sw.tray_mod, "_spawn", lambda a, label, fn: fn())
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda a, msg: notes.append(msg))
    monkeypatch.setattr(sw, "show_settings", lambda a: None)
    app = _SettingsApp({})
    sw.action_set_report_switch(app, "local_manifest", False)
    assert app.config["report_local_manifest"] is False
    assert config_mod.load_config(path)["report_local_manifest"] is False
    assert "Sync is not affected" in notes[-1]
    assert "\u2014" not in notes[-1]


def test_the_help_section_offers_the_licences(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(sw.tray_mod, "_open_path_or_say_why",
                        lambda app, path, missing: opened.append((path, missing)))
    sw.action_open_licences(_SettingsApp({}))
    path, missing = opened[0]
    if sw.licences_path() is None:
        assert path == "" and "licence texts" in missing
    else:
        assert path.endswith("THIRD_PARTY_LICENSES.txt")


def test_no_em_dash_in_any_new_editor_visible_string():
    strings = [config_mod.DASHBOARD_URL_PUBLIC_HTTP, config_mod.DASHBOARD_URL_LOCAL_HTTP,
               reporter_mod.CLEARTEXT_REFUSED_LINE, sw.SITE_OFF_NOTE, sw.IMPLIED_OFF_NOTE,
               *sw.REPORT_LABELS.values()]
    assert not any("\u2014" in s for s in strings)


# -- redact_text ------------------------------------------------------------------------------

def test_redact_cuts_paths_under_roots_and_names_as_whole_words():
    text = ("opened P:\\Projects\\FF5 Civil Defence\\a.mov, then P:/x/y.mov; "
            "dashboard http://nas:8480/api ok; alice and alice2 and /mnt/tank/Tree/p/q.mov; "
            "Plan A works")
    out = tp.redact_text(text, ["alice", "FF5 Civil Defence", "A"], ["P:\\", "/mnt/tank/Tree"])
    assert "a.mov" not in out and "y.mov" not in out and "q.mov" not in out
    assert "P:/<file>" in out and "/mnt/tank/Tree/<file>" in out
    assert "http://nas:8480/api" in out                  # "http:" is not the P: root
    assert "<project> and alice2" in out                 # whole words only
    assert "Plan A works" in out                         # a one-letter name is skipped


def test_redact_handles_nothing_to_do():
    assert tp.redact_text("plain", [], []) == "plain"
    assert tp.redact_text("", [None], [None, ""]) == ""
