"""The telemetry switches on the dashboard's side of the wire (LG-1,
docs/LEGAL_GAP_FEATURES_PLAN.md 4.1, 2026-09-25, group G2a).

The rules defended here:

- STRIP BEFORE ANY WRITE, FROM EVERY COMPANION VERSION (correctness H3): a
  report from a build that predates the switches (no `report_optouts`) is
  stripped by the SITE policy on arrival, and nothing withheld is stored.
- A computer's own switches are honoured, and an absent key keeps the list it
  sent last time (G0 hand-off 9) instead of reading as "all on".
- The conflict count survives the strip: absent is how "no conflicts" is
  spelled.
- Note J: with the project name off, a journal's `project` goes and its id
  is masked to `withheld:project/<file>`, because a journal id carries the
  project name (the companion's own table does the same).
- `report_optouts` is a tolerant section: unknown names are dropped, a
  malformed section is dropped, and the report lands either way.
- An upload-only tick of a machine that withholds its file list is not a
  permanent "getting ready" row (correctness H4).
- The dashboard's FIELDS copy is the companion's (pinned from this side).
"""
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api, auth, db as dbmod, netclass, site_store, telemetry_fields
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
EDITOR = "jsmith"
MACHINE = "EDIT-PC"
SLUG = "2025-ff4-nuclear"
LABEL = "2025/FF4/Nuclear"
PROJECT = "Nuclear"                     # names the project's last segment: auto-maps

POLICY_PY = (Path(__file__).resolve().parents[2]
             / "companion" / "src" / "ccsync_companion" / "telemetry_policy.py")

# Every carrier the plan's FIELDS table names, in the shape a 0.9.79 companion
# sends (no `report_optouts`: that build has no switches).
FULL = {
    "editor_name": EDITOR, "machine": MACHINE, "companion_version": "0.9.79",
    "reported_at": "2026-09-25T10:00:00+00:00",
    "lanes": [{"name": "lane_a_video_up", "state": "idle"}],
    "resolve_project": PROJECT,
    "local_manifest": {LABEL: {"n_originals": 1, "bytes_originals": 10,
                               "originals": [["A001/clip.mov", 10]]}},
    "media_tree": {PROJECT: [{"bin_path": "Master/Day 1", "clip_name": "clip.mov",
                              "file_path": "P:/2025/FF4/Nuclear/A001/clip.mov",
                              "kind": "original", "present": True}]},
    "capabilities": {"idle_seconds": 312.0, "resolve": {"running": True,
                                                         "project": PROJECT}},
    "resolve_journals": [{"id": "Nuclear/20260925-100000.json", "project": PROJECT,
                          "started": "2026-09-25T09:00:00", "entries": 3}],
    "sync_guard": {
        "sync_conflicts": {"count": 2, "paths": ["A001/clip.sync-conflict-1.mov"]},
        "resolve_health": {"open_project": PROJECT, "project_open": PROJECT,
                           "missing": 1,
                           "missing_clips": [{"name": "c.mov", "path": "D:/c.mov"}],
                           "non_canonical_refused": [{"name": "d.mov",
                                                      "path": "E:/d.mov"}]},
        "stray_projects": {"count": 1, "bytes": 5, "paths": ["D:/Old/Thing"],
                           "slugs": ["old-thing"]},
        "moved_project_dirs": [{"slug": SLUG, "expected": "P:/2025/FF4/Nuclear",
                                "found": "D:/Nuclear"}],
    },
}

EVERYTHING = {"resolve_project", "local_manifest", "media_tree", "input_idle"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    netclass.clear_cache()
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "optouts.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    site = {"off": set()}
    # G2b's site_store.telemetry_policy; stubbed so this group's half is
    # tested on the contract, whether or not G2b's half has landed yet.
    monkeypatch.setattr(site_store, "telemetry_policy",
                        lambda conn, settings: set(site["off"]), raising=False)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        dbmod.upsert_project(conn, SLUG, LABEL, "/x", dbmod.utcnow_iso())
        conn.commit()
        yield client, conn, site
        conn.close()


def send(client, body):
    hdr = {"X-CCSync-Token": TOKEN,
           "X-CCSync-Identity": auth.make_identity_token(SECRET, EDITOR)}
    resp = client.post("/api/v1/report", json=body, headers=hdr)
    assert resp.status_code == 200, resp.text
    return resp.json()


def full(**changes):
    body = copy.deepcopy(FULL)
    body.update(changes)
    return body


def state(conn):
    return dict(conn.execute(
        "SELECT * FROM machine_state WHERE editor_username=? AND machine=?",
        (EDITOR, MACHINE)).fetchone())


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE editor_username=?"
                        " AND machine=?", (EDITOR, MACHINE)).fetchone()[0]


def health_meta(conn):
    return dbmod.meta_get_json(conn, f"{dbmod.RESOLVE_HEALTH_META_PREFIX}{EDITOR}/{MACHINE}")


def journals(conn):
    return dbmod.machine_resolve_journals(conn, EDITOR, MACHINE)


# ------------------------------------------------------------ the control


def test_with_nothing_withheld_everything_is_stored(env):
    client, conn, _site = env
    send(client, full())
    row = state(conn)
    assert row["resolve_project"] == PROJECT
    assert row["cap_idle_seconds"] == 312.0
    assert count(conn, "editor_media") == 1
    assert count(conn, "media_tree_clips") == 1
    assert journals(conn)[0]["project"] == PROJECT
    # An old build under a site that withholds nothing: nothing is known.
    assert row["report_optouts"] is None and row["report_optouts_local"] is None


# ---------------------------------------------------- the site, old builds


def test_an_old_build_under_a_site_switch_arrives_stripped(env):
    client, conn, site = env
    site["off"] = set(EVERYTHING)
    reply = send(client, full())
    row = state(conn)
    assert row["resolve_project"] is None
    assert row["cap_resolve_project"] in (None, "")
    assert row["cap_idle_seconds"] is None
    assert count(conn, "editor_media") == 0
    assert count(conn, "editor_media_project") == 0
    assert count(conn, "media_tree_clips") == 0
    assert journals(conn) == [{"id": "withheld:project/20260925-100000.json",
                               "project": "", "started": "2026-09-25T09:00:00",
                               "entries": 3, "sources": ""}]
    assert health_meta(conn) is None
    # No project name, so no NEW PROJECT prompt and no auto-mapping.
    assert not reply.get("resolve_project_unmapped")
    assert conn.execute("SELECT COUNT(*) FROM project_roots").fetchone()[0] == 0
    # Counts survive: absent is never zero.
    assert row["sync_conflicts"] == 2
    assert json.loads(row["report_optouts"]) == sorted(EVERYTHING)
    assert row["report_optouts_local"] is None      # that build sent no list


def test_a_site_switch_clears_what_an_earlier_report_left(env):
    client, conn, site = env
    send(client, full())
    assert count(conn, "editor_media") == 1
    site["off"] = {"local_manifest"}
    send(client, full())
    assert count(conn, "editor_media") == 0
    assert count(conn, "media_tree_clips") == 1       # not withheld
    assert state(conn)["resolve_project"] == PROJECT


def test_local_manifest_keeps_the_counts_and_drops_the_paths(env):
    client, conn, site = env
    site["off"] = {"local_manifest"}
    body = full()
    stripped = copy.deepcopy(body)
    telemetry_fields.strip(stripped, {"local_manifest"})
    guard = stripped["sync_guard"]
    assert "paths" not in guard["sync_conflicts"] and guard["sync_conflicts"]["count"] == 2
    assert "stray_projects" not in guard and "moved_project_dirs" not in guard
    assert "missing_clips" not in guard["resolve_health"]
    assert guard["resolve_health"]["missing"] == 1
    send(client, body)
    meta = health_meta(conn) or {}
    assert "missing_clips" not in meta and "non_canonical_refused" not in meta


def test_the_site_policy_failing_falls_back_to_what_was_last_applied(env, monkeypatch):
    client, conn, _site = env
    dbmod.apply_site_optouts(conn, ["input_idle"])
    conn.commit()

    def broken(conn, settings):
        raise RuntimeError("site_settings unreadable")

    monkeypatch.setattr(site_store, "telemetry_policy", broken, raising=False)
    send(client, full())
    assert state(conn)["cap_idle_seconds"] is None
    assert state(conn)["resolve_project"] == PROJECT


# ------------------------------------------------- a computer's own switches


def test_a_computers_own_switch_is_honoured(env):
    client, conn, _site = env
    send(client, full(report_optouts=["input_idle"]))
    row = state(conn)
    assert row["cap_idle_seconds"] is None
    assert row["resolve_project"] == PROJECT
    assert json.loads(row["report_optouts_local"]) == ["input_idle"]


def test_resolve_project_implies_media_tree_and_masks_the_journals(env):
    client, conn, _site = env
    send(client, full())
    assert journals(conn)[0]["id"].startswith("Nuclear/")
    send(client, full(report_optouts=["resolve_project"]))
    row = state(conn)
    assert row["resolve_project"] is None
    assert count(conn, "media_tree_clips") == 0
    assert [(j["id"], j["project"]) for j in journals(conn)] == [
        ("withheld:project/20260925-100000.json", "")]
    assert PROJECT not in json.dumps(journals(conn))
    assert json.loads(row["report_optouts"]) == ["media_tree", "resolve_project"]


def test_an_absent_key_keeps_the_list_it_sent_last_time(env):
    client, conn, _site = env
    send(client, full(report_optouts=["input_idle"]))
    body = full()                                    # the section went missing
    send(client, body)
    assert state(conn)["cap_idle_seconds"] is None
    send(client, full(report_optouts=[]))           # an explicit "all on"
    assert state(conn)["cap_idle_seconds"] == 312.0


def test_unknown_names_are_dropped_entry_by_entry(env):
    client, conn, _site = env
    send(client, full(report_optouts=["input_idle", "telepathy", 7, None]))
    assert json.loads(state(conn)["report_optouts_local"]) == ["input_idle"]


@pytest.mark.parametrize("bad", ["input_idle", {"input_idle": True}, 5])
def test_a_malformed_section_is_dropped_and_the_report_lands(env, bad):
    client, conn, _site = env
    send(client, full(report_optouts=bad))
    row = state(conn)
    assert row["report_optouts_local"] is None
    assert row["cap_idle_seconds"] == 312.0
    assert conn.execute("SELECT COUNT(*) FROM lane_report_current WHERE"
                        " editor_username=?", (EDITOR,)).fetchone()[0] == 1


def test_an_empty_list_is_not_an_old_build(env):
    client, conn, _site = env
    send(client, full(report_optouts=[]))
    assert state(conn)["report_optouts_local"] == "[]"


# ------------------------------------------------------ the preparing rule


def _tick_upload_only(conn):
    dbmod.add_selection(conn, EDITOR, SLUG, "owen", dbmod.utcnow_iso(), machine=MACHINE,
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    conn.commit()


def _preparing(client, conn):
    view = api.build_transfers_view(conn)
    return [q for q in view["queues"]
            if q.get("pending") and q.get("upload_only") and q["slug"] == SLUG]


def test_an_opted_out_machine_gets_no_permanent_preparing_row(env):
    client, conn, _site = env
    send(client, full(local_manifest=None))
    _tick_upload_only(conn)
    assert _preparing(client, conn), "control: a normal machine does prepare"
    send(client, full(report_optouts=["local_manifest"]))
    assert _preparing(client, conn) == []
    rows = [q for q in api.build_transfers_view(conn)["queues"] if q["slug"] == SLUG]
    # "not reported", an uncertain upload: never absent, never "nothing owed".
    assert [(q.get("not_reported"), q.get("uncertain"), q["n_files"]) for q in rows] == [
        (True, True, 0)]


# -------------------------------------------------------------- FIELDS


def test_strip_works_on_a_dict_and_reports_what_it_removed(env):
    body = copy.deepcopy(FULL)
    removed = telemetry_fields.strip(body, {"resolve_project"})
    assert "resolve_project" not in body and "media_tree" not in body
    assert body["resolve_journals"] == [{"id": "withheld:project/20260925-100000.json",
                                         "started": "2026-09-25T09:00:00",
                                         "entries": 3}]
    # Idempotent: a companion that already masked it is left alone.
    assert "resolve_journals[].id" not in telemetry_fields.strip(body, {"resolve_project"})
    assert body["capabilities"]["resolve"] == {"running": True}
    assert "open_project" not in body["sync_guard"]["resolve_health"]
    assert "media_tree" in removed
    # A report that carries none of it strips nothing and raises nothing.
    assert telemetry_fields.strip({"lanes": []}, EVERYTHING) == []
    assert telemetry_fields.strip(None, EVERYTHING) == []


def test_every_field_path_resolves_on_the_report_model():
    """A path that names no declared field would strip nothing on the
    dashboard side while the wording says it is withheld."""
    for paths in telemetry_fields.FIELDS.values():
        for path in paths:
            model = api.ReportIn
            for segment in path.split("."):
                key = segment[:-2] if segment.endswith("[]") else segment
                assert key in model.model_fields, path
                sub = [m for m in api._section_models(model.model_fields[key].annotation)]
                model = sub[0] if sub else None
                if model is None:
                    break


def test_the_categories_are_the_databases():
    assert telemetry_fields.CATEGORIES == dbmod.REPORT_CATEGORIES
    assert set(telemetry_fields.FIELDS) == set(dbmod.REPORT_CATEGORIES)


def _companion_policy():
    if not POLICY_PY.is_file():
        pytest.skip("companion telemetry_policy.py is not in this checkout yet (G1a)")
    spec = importlib.util.spec_from_file_location("_companion_policy_for_parity", POLICY_PY)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        pytest.skip(f"companion telemetry_policy.py does not load standalone ({exc})")
    return module


def _normalised(fields):
    out = {}
    for category, paths in dict(fields).items():
        out[str(category)] = sorted(
            p if isinstance(p, str) else ".".join(p) for p in paths)
    return out


def test_the_fields_copy_equals_the_companions():
    assert _normalised(telemetry_fields.FIELDS) == _normalised(_companion_policy().FIELDS), (
        "the dashboard strips what telemetry_fields.FIELDS names and the companion "
        "withholds what telemetry_policy.FIELDS names: change both, then "
        "TELEMETRY.md's payload table")


def test_no_em_dash_in_what_this_group_shows():
    sources = [inspect.getsource(api._forget_elsewhere),
               inspect.getsource(api._record_legal_sections),
               inspect.getsource(api.EulaIn), inspect.getsource(api.ReportOptoutsIn),
               Path(netclass.__file__).read_text(encoding="utf-8"),
               Path(telemetry_fields.__file__).read_text(encoding="utf-8")]
    for text in sources:
        assert "\u2014" not in text


def test_the_masks_equal_the_companions():
    policy = _companion_policy()
    assert telemetry_fields.MASKED == dict(policy.MASKED)
    assert telemetry_fields.OPAQUE_JOURNAL_PREFIX == policy.OPAQUE_JOURNAL_PREFIX
    for value in ("FF5 Civil Defence/20260925-101010.json", "a\b.json", "",
                  None, "withheld:project/x.json", "/lead/and/trail/"):
        assert telemetry_fields.opaque_journal_id(value) == policy.opaque_journal_id(value)
    assert telemetry_fields.CATEGORIES == tuple(policy.CATEGORIES)


# ------------------------------------------ the eula section (LG-5, G2a half)


def _eula(conn):
    raw = state(conn)["eula_json"]
    return None if raw is None else json.loads(raw)


def test_the_eula_section_is_stored_and_absent_changes_nothing(env):
    client, conn, _site = env
    send(client, full())
    assert _eula(conn) is None                           # not reported
    block = {"version": "1.1", "accepted_at": "2026-09-25T09:00:00+00:00",
             "eula_sha256": "ab" * 32, "path": "C:/Users/x/eula.json"}
    send(client, full(eula=block))
    assert _eula(conn) == {"version": "1.1", "accepted_at": "2026-09-25T09:00:00+00:00",
                           "eula_sha256": "ab" * 32}
    send(client, full())                                 # absent keeps it
    assert _eula(conn)["version"] == "1.1"


@pytest.mark.parametrize("bad", ["1.1", [1], {"version": {"x": 1}}])
def test_a_malformed_eula_section_is_dropped_and_the_report_lands(env, bad):
    client, conn, _site = env
    send(client, full(eula=bad))
    assert _eula(conn) is None
    assert state(conn)["resolve_project"] == PROJECT


# --------------------------------------------------------------- review round
#
# G2a review round (2026-09-25). Each test below fails on the first build.


def _post_bundle(client, text, trigger="button"):
    hdr = {"X-CCSync-Token": TOKEN,
           "X-CCSync-Identity": auth.make_identity_token(SECRET, EDITOR)}
    resp = client.post("/api/v1/diagnostics", headers=hdr, json={
        "editor_name": EDITOR, "machine": MACHINE, "trigger": trigger, "text": text})
    assert resp.status_code == 200, resp.text
    return resp.json()


BUNDLE = f"=== CCSYNC DIAGNOSTICS ===\nopen project: {PROJECT}\nD:/{PROJECT}/A001/clip.mov"


def test_point2_an_old_builds_bundle_is_not_stored_under_a_site_switch(env):
    client, conn, site = env
    site["off"] = {"local_manifest"}
    send(client, full())                                  # 0.9.79: no own list
    dbmod.request_diagnostics(conn, EDITOR, MACHINE, "owen", dbmod.utcnow_iso())
    conn.commit()
    reply = _post_bundle(client, BUNDLE, trigger="admin_request")
    assert reply["stored"] is False
    stored = dbmod.fetch_diagnostics(conn, EDITOR, MACHINE)
    assert len(stored) == 1
    assert PROJECT not in stored[0]["text"] and "clip.mov" not in stored[0]["text"]
    assert "local_manifest" in stored[0]["text"]
    # The admin's ask is still answered, so it does not read as lost.
    assert not dbmod.pending_machine_request(conn, EDITOR, MACHINE)["diagnostics"]


def test_point2_a_build_with_the_switches_is_stored_as_sent(env):
    client, conn, site = env
    site["off"] = {"local_manifest"}
    # The list a companion sends is local AND site: naming the category
    # is what says it has read the site policy and redacted under it.
    send(client, full(report_optouts=["local_manifest"]))
    reply = _post_bundle(client, BUNDLE)
    assert "stored" not in reply
    assert dbmod.fetch_diagnostics(conn, EDITOR, MACHINE)[0]["text"] == BUNDLE


def test_point2_a_build_that_has_not_learned_the_site_policy_is_stubbed(env):
    """Final review 2026-09-25: a current companion whose manifest cache
    predates the site switch (up to SITE_REFRESH_SECONDS) sends
    report_optouts without the site category and an unredacted bundle.
    The first build stored it because ANY own list, even [], read as
    "redacts its own bundle"."""
    client, conn, site = env
    site["off"] = {"local_manifest"}
    send(client, full(report_optouts=[]))                 # has not seen the switch
    reply = _post_bundle(client, BUNDLE)
    assert reply["stored"] is False
    text = dbmod.fetch_diagnostics(conn, EDITOR, MACHINE)[0]["text"]
    assert PROJECT not in text and "clip.mov" not in text
    # Its own switch covers a different category: still the site one it lacks.
    send(client, full(report_optouts=["input_idle"]))
    assert _post_bundle(client, BUNDLE)["stored"] is False


def test_point2_input_idle_alone_never_rides_a_bundle(env):
    client, conn, site = env
    site["off"] = {"input_idle"}
    send(client, full())
    _post_bundle(client, BUNDLE)
    assert dbmod.fetch_diagnostics(conn, EDITOR, MACHINE)[0]["text"] == BUNDLE


def test_point3_the_host_lookup_runs_before_the_reports_first_write(env, monkeypatch):
    """Ordered, not probed: the collector's own thread takes the write lock
    now and then, so a lock probe from here would be flaky. The first write
    of an accepted report is clear_report_refused; the lookup must precede
    it, so no write transaction of the report's is open across it."""
    client, conn, _site = env
    order = []
    real_clear = dbmod.clear_report_refused

    def clear(*a, **k):
        order.append("first write")
        return real_clear(*a, **k)

    def resolve(host):
        order.append("lookup")
        return ["93.184.216.34"]

    monkeypatch.setattr(dbmod, "clear_report_refused", clear)
    monkeypatch.setattr(netclass, "resolve", resolve)
    hdr = {"X-CCSync-Token": TOKEN, "Host": "dash.studio-name.net",
           "X-CCSync-Identity": auth.make_identity_token(SECRET, EDITOR)}
    resp = client.post("/api/v1/report", json=full(), headers=hdr)
    assert resp.status_code == 200, resp.text
    assert order == ["lookup", "first write"]
    assert state(conn)["report_via"] == "http_public"


def test_point4_the_unassigned_bucket_follows_the_machines_it_stands_for(env):
    """The reviewer's shape: laptop EDIT-PC withholds its file list and has a
    plan of its own, so the unassigned upload-only tick belongs to DESK,
    which reports normally. It never reached the "any machine withholds"
    branch: db.fetch_machine_selections resolves the bucket to DESK itself
    (machine '' survives only for a person with no registered computer), so
    the row is DESK's and clears on DESK's manifest. Pinned so the rejection
    of review point 4 stays true."""
    client, conn, _site = env
    dbmod.upsert_project(conn, "2025-ff4-other", "2025/FF4/Other", "/y", dbmod.utcnow_iso())
    conn.commit()
    send(client, full(local_manifest=None, report_optouts=["local_manifest"]))
    dbmod.add_selection(conn, EDITOR, "2025-ff4-other", "owen", dbmod.utcnow_iso(),
                        machine=MACHINE)
    dbmod.add_selection(conn, EDITOR, SLUG, "owen", dbmod.utcnow_iso(), machine="",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    conn.commit()
    send(client, full(machine="DESK", local_manifest=None, report_optouts=[]))

    def rows():
        return [(q["machine"], bool(q.get("not_reported")), bool(q.get("pending")))
                for q in api.build_transfers_view(conn)["queues"] if q["slug"] == SLUG]

    assert rows() == [("DESK", False, True)]          # preparing, on DESK
    send(client, full(machine="DESK", report_optouts=[]))
    assert not any(nr or p for _m, nr, p in rows())   # DESK's manifest ends it


def test_point4_a_bucket_only_withholding_machines_stand_for_is_not_reported(env):
    client, conn, _site = env
    send(client, full(local_manifest=None, report_optouts=["local_manifest"]))
    dbmod.add_selection(conn, EDITOR, SLUG, "owen", dbmod.utcnow_iso(), machine="",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    conn.commit()
    assert api._upload_only_tick_withheld(
        conn, EDITOR, "", dbmod.machines_withholding(conn, "local_manifest"), set())
    rows = [q for q in api.build_transfers_view(conn)["queues"] if q["slug"] == SLUG]
    assert rows and all(q.get("not_reported") and not q.get("pending") for q in rows)


def test_point5_a_path_that_cannot_be_stripped_takes_its_section(monkeypatch):
    real = telemetry_fields._remove

    def fussy(obj, key):
        if key == "missing_clips":
            raise ValueError("validate_assignment said no")
        return real(obj, key)

    monkeypatch.setattr(telemetry_fields, "_remove", fussy)
    model = api.ReportIn.model_validate(copy.deepcopy(FULL))
    removed = telemetry_fields.strip(model, {"local_manifest"})
    assert "sync_guard.resolve_health.missing_clips" in removed
    assert model.sync_guard is None
    body = copy.deepcopy(FULL)
    telemetry_fields.strip(body, {"local_manifest"})
    assert "sync_guard" not in body


def test_point5_a_section_that_cannot_be_dropped_raises(monkeypatch):
    class Stubborn(dict):
        def pop(self, *a, **k):
            raise RuntimeError("no")

    def boom(obj, key):
        raise ValueError("no")

    monkeypatch.setattr(telemetry_fields, "_remove", boom)
    body = Stubborn(copy.deepcopy(FULL))
    with pytest.raises(telemetry_fields.StripFailed):
        telemetry_fields.strip(body, {"local_manifest"})


def test_point5_a_failed_strip_stores_nothing_withheld(env, monkeypatch):
    client, conn, site = env
    site["off"] = {"local_manifest"}
    real = telemetry_fields._remove

    def fussy(obj, key):
        if key == "missing_clips":
            raise ValueError("validate_assignment said no")
        return real(obj, key)

    monkeypatch.setattr(telemetry_fields, "_remove", fussy)
    send(client, full())
    assert "missing_clips" not in (health_meta(conn) or {})
