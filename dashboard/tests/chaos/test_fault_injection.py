"""Fault injection: the server half of SYS-18's nine chaos tests.

SYS-18 (resilience sweep 2026-08-28, `docs/RESILIENCE_SWEEP_2026-08-28.md`
item 43). The companion carries seven of the nine
(`companion/tests/chaos/test_fault_injection.py`); the three here are the
ones whose observable only exists on the server, because the fault is
something a MACHINE did and the dashboard is what has to notice:

  7. a report carrying a section this dashboard does not declare (SYS-3)
  8. a second hostname reporting an existing `machine_id` (SYS-9 / DASH-11)
  9. a folder listing that answers 200 with nothing in it (DASH-4), the
     server-side twin of the companion's CR-44 / CR-47 breaker case

Same two rules as the companion module. Every assertion is an OBSERVABLE -
the row that survived, the notice a person is handed, the sentence on the
page - never "the guard function was called": sixteen `log.error` diagnoses
reaching only the container log is the exact defect (UX-10) that wave 4 was
built to close, and a test that asserted the call would have passed
throughout. And nothing here sleeps, spawns or reaches the network.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api as apimod
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import invariants
from ccsync_dashboard import notices as noticesmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-08-29T12:00:00+00:00"


# -- the fault list --------------------------------------------------------
#
# The same registry the companion module carries, filtered to what is
# observable here. Kept in both places deliberately: a chaos suite that could
# be reduced to eight injections by deleting one file would not be a pin.

SERVER_FAULTS = ("undeclared_section", "cloned_machine_id", "empty_folder_list")


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "dash.db"
    settings = Settings(db_path=str(db_path), report_token="sekrit",
                        session_secret=SECRET, admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        # Process-global, so a chaos test must not inherit another module's
        # "already logged today" and conclude the dashboard said nothing.
        apimod._IGNORED_SECTION_LOGGED.clear()
        yield client, conn, settings
        conn.close()


def _headers(editor: str = "jsmith"):
    return {"X-CCSync-Token": "sekrit",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def _report(machine: str = "EDIT-PC", **extra):
    body = {
        "editor_name": "JSmith",
        "machine": machine,
        "companion_version": "0.9.55",
        "reported_at": NOW,
        "lanes": [
            {"name": "lane_c_syncthing", "state": "idle", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None, "detail": None},
        ],
    }
    body.update(extra)
    return body


# -- 7: a report carrying an undeclared section (SYS-3) --------------------


@pytest.mark.parametrize("section,expected", [
    # A whole top-level section, which is how transport_health was lost for
    # months (B17) and proxy_coverage / youtube_import for a year each.
    ({"resolve_health": {"out_of_tree": 4}}, "resolve_health"),
    # ...and a sync_guard SUB-key, which is how syncthing_supervisor was lost
    # (SYNC-8). Namespaced in the record so the two cannot collide.
    ({"sync_guard": {"vram_pressure": True}}, "sync_guard.vram_pressure"),
])
def test_an_undeclared_section_is_accepted_counted_and_shown_to_a_person(
        env, caplog, section, expected):
    """SYS-3: `extra='ignore'` has now silently thrown away companion
    telemetry three times, and each was found by a human reading the source -
    none by a signal. The fourth has to announce itself.

    Three observables, and the report being ACCEPTED is the first of them: an
    undeclared key must never be the reason a machine drops off the fleet
    grid, which is what a 422 would do.
    """
    client, conn, settings = env

    with caplog.at_level("WARNING"):
        r = client.post("/api/v1/report", json=_report(**section), headers=_headers())

    assert r.status_code == 200, "an undeclared key must never cost the report"
    assert any("does not read" in m for m in caplog.messages)

    record = dbmod.ignored_report_sections(conn)
    assert record is not None and expected in record["sections"]
    assert record["sections"][expected]["machines"] == ["jsmith/EDIT-PC"]

    # The one that matters: it reaches a PERSON, on the home page, with the
    # action attached. A durable meta row nobody renders is UX-10 again.
    noticesmod.run_checks(conn, settings, now=NOW)
    found = [n for n in dbmod.open_notices(conn)
             if n["kind"] == "ignored_report_sections"]
    assert found, "the diagnosis reached the database and stopped there"
    assert expected in found[0]["body"]
    assert found[0]["fix"], "a notice with no next action is a log line"


def test_a_declared_section_raises_nothing_at_all(env):
    """The converse, and the reason this is not merely noisy: every section
    wave 2 landed must read as declared, or the banner cries wolf on every
    report from every machine and gets ignored the way the log was."""
    client, conn, settings = env
    client.post("/api/v1/report", json=_report(sync_guard={
        "syncthing_supervisor": {"down_since": NOW, "attempts": 1,
                                 "last_error": "boom", "supervising": True},
        "crashes": {"count": 1, "newest": "20260829-lane"},
        "clock_skew_seconds": -1200.0,
        "reporter": {"last_success_at": NOW, "last_status": "ok",
                     "consecutive_failures": 0},
    }), headers=_headers())

    assert dbmod.ignored_report_sections(conn) is None
    noticesmod.run_checks(conn, settings, now=NOW)
    assert not [n for n in dbmod.open_notices(conn)
                if n["kind"] == "ignored_report_sections"]


# -- 8: a second hostname reporting an existing machine_id -----------------


CLONED_ID = "mach-0f3c9a12"


def test_one_machine_id_on_two_editors_accounts_is_named_as_a_clone(env):
    """SYS-9 / DASH-11. An editor's disk image is copied onto a second
    computer, so both report the same `machine_id`, the same identity token
    and the same Syncthing device id. Every per-machine decision after that -
    a sync plan, a pushed update, a halt - lands on whichever of the two
    reported last, and the enforce cycle restarts the affected folders on the
    same cadence.

    The observable is the NOTICE, because nothing else about this shape looks
    wrong: both machines are online, both are reporting, and each row is
    individually valid.

    The two computers here are signed in as different editors, which is the
    case the check can actually see; the same-editor clone is the gap pinned
    below.
    """
    client, conn, settings = env

    client.post("/api/v1/report", json=_report("EDIT-PC", machine_id=CLONED_ID),
                headers=_headers("jsmith"))
    client.post("/api/v1/report", json=dict(_report("STUDIO-2", machine_id=CLONED_ID),
                                            editor_name="RSmith"),
                headers=_headers("rsmith"))

    rows = dbmod.fetch_machines(conn)
    assert {r["machine"] for r in rows} == {"EDIT-PC", "STUDIO-2"}

    noticesmod.run_checks(conn, settings, now=NOW)
    clone = [n for n in dbmod.open_notices(conn) if n["kind"] == "duplicate_machine_id"]
    assert clone, "two computers claiming one identity must not be silent"
    assert clone[0]["severity"] == "error"
    assert "EDIT-PC" in clone[0]["body"] and "STUDIO-2" in clone[0]["body"]
    # An owner who cannot read a stack trace has to be able to act on it.
    assert "machine.json" in (clone[0]["fix"] or "")


def _quieten(conn, editor: str, machine: str) -> None:
    """Take a registry row off the air, which is what a RENAME does to the old
    hostname: the computer reboots to take its new name, and the row it used
    to report under is never touched again. Written straight onto `last_seen`
    (the SERVER's received_at) because that, since SYS-18a, is what tells a
    rename from a clone."""
    old = (dt.datetime.fromisoformat(NOW) - dt.timedelta(hours=1)).isoformat()
    conn.execute("UPDATE machines SET last_seen=? WHERE editor_username=? AND machine=?",
                 (old, editor, machine))
    conn.commit()


def test_one_computer_that_was_renamed_is_not_a_clone(env):
    """The shape this must NOT fire on, and the reason `machine_id` exists at
    all: a renamed computer is one machine with two hostnames over TIME, not
    two at once. A false clone alarm would send an owner to delete the
    machine.json of a machine that is fine.

    The old row is quietened first (SYS-18a, 2026-08-29): the rename branch is
    now conditional on the previous hostname having gone quiet, and a rename
    that reboots a PC always does. Two reports a millisecond apart from one
    TestClient are the clone shape, not the rename shape."""
    client, conn, settings = env
    client.post("/api/v1/report", json=_report("EDIT-PC", machine_id=CLONED_ID),
                headers=_headers())
    _quieten(conn, "jsmith", "EDIT-PC")
    client.post("/api/v1/report", json=_report("EDIT-PC-RENAMED", machine_id=CLONED_ID),
                headers=_headers())

    assert [r["machine"] for r in dbmod.fetch_machines(conn)] == ["EDIT-PC-RENAMED"]
    noticesmod.run_checks(conn, settings, now=NOW)
    assert not [n for n in dbmod.open_notices(conn)
                if n["kind"] == "duplicate_machine_id"]


def test_a_rename_still_carries_the_sync_plan_to_the_new_name(env):
    """The half of the rename branch that matters to an editor, and the one
    thing the SYS-18a fix must not have cost: `machine_id` exists so a renamed
    computer keeps its ticks. A rename that started an empty plan would stop
    that machine syncing silently, which is worse than the bug being fixed."""
    client, conn, _unused = env
    dbmod.upsert_project(conn, "ff5", "FF5", "/projects/ff5", NOW)
    conn.commit()   # the app has its own connection; an open write txn locks it
    client.post("/api/v1/report", json=_report("EDIT-PC", machine_id=CLONED_ID),
                headers=_headers())
    dbmod.add_selection(conn, "jsmith", "ff5", "admin", NOW, machine="EDIT-PC")
    conn.commit()
    _quieten(conn, "jsmith", "EDIT-PC")

    client.post("/api/v1/report", json=_report("EDIT-PC-RENAMED", machine_id=CLONED_ID),
                headers=_headers())
    assert [r["machine"] for r in dbmod.fetch_machines(conn)] == ["EDIT-PC-RENAMED"]
    assert dbmod.fetch_machine_selections(conn)["ff5"] == [("jsmith", "EDIT-PC-RENAMED")]


# Was the CHARACTERISATION of SYS-18a: until 2026-08-29 this pair of reports
# left ONE row that ping-ponged between the two hostnames, carrying (and on
# each swap destroying) a sync plan. Freshness now decides, so the assertions
# below are the inverse of what they were.
def test_a_live_same_editor_clone_is_refused_and_both_rows_survive(env):
    """The clone case DASH-11 actually describes: one person's disk imaged
    onto their second computer, both signed in as them, both reporting every
    30 s.

    `_register_machine` used to read "this machine_id at a new hostname" as a
    RENAME unconditionally, and `adopt_renamed_machine` DELETEd the old
    registry row and carried the plan across - for ever, in both directions.
    The old row here reported milliseconds ago, so this is two live computers
    and the adoption is refused. UNDER-acting is the point: nothing is
    deleted, nothing moves, and the collision is left where the two checks
    written for it can see it.
    """
    client, conn, _unused = env
    dbmod.upsert_project(conn, "ff5", "FF5", "/projects/ff5", NOW)
    conn.commit()
    client.post("/api/v1/report", json=_report("EDIT-PC", machine_id=CLONED_ID),
                headers=_headers())
    dbmod.add_selection(conn, "jsmith", "ff5", "admin", NOW, machine="EDIT-PC")
    conn.commit()

    # The clone reports. BOTH rows now exist, and the plan has not moved.
    client.post("/api/v1/report", json=_report("LAPTOP", machine_id=CLONED_ID),
                headers=_headers())
    assert sorted(r["machine"] for r in dbmod.fetch_machines(conn)) == ["EDIT-PC", "LAPTOP"]
    assert dbmod.fetch_machine_selections(conn)["ff5"] == [("jsmith", "EDIT-PC")]

    # ...and it stays put however many turns the two take. The verdict is
    # asked again on every report (the deferred half of the fix), so "it did
    # not adopt on the second report" is not the property under test: a clone
    # must never adopt, and its twin reporting every 30 s is what guarantees
    # the deferred branch is never reached.
    for _ in range(4):
        for hostname in ("EDIT-PC", "LAPTOP"):
            client.post("/api/v1/report", json=_report(hostname, machine_id=CLONED_ID),
                        headers=_headers())
        assert sorted(r["machine"] for r in dbmod.fetch_machines(conn)) == \
            ["EDIT-PC", "LAPTOP"]
        assert dbmod.fetch_machine_selections(conn)["ff5"] == [("jsmith", "EDIT-PC")]
    assert [n for n in dbmod.open_notices(conn) if n["kind"] == "duplicate_machine_id"]


# Was a strict xfail until 2026-08-29: it pinned SYS-18a, where a same-editor
# clone was read as a rename, left one `machines` row and so could never reach
# `duplicate_machine_id` - the check whose own fix text is written for exactly
# this. The adoption path now refuses while the other row is fresh, so both
# rows survive and the check fires on its own.
def test_a_same_editor_clone_is_named_as_a_clone(env):
    client, conn, settings = env
    for hostname in ("EDIT-PC", "LAPTOP"):
        client.post("/api/v1/report",
                    json=_report(hostname, machine_id=CLONED_ID),
                    headers=_headers())

    # Named the moment the adoption is refused, not one collector cycle later:
    # the report path is where both computers are known to have been live.
    at_once = [n for n in dbmod.open_notices(conn)
               if n["kind"] == "duplicate_machine_id"]
    assert at_once, "a refused adoption that says nothing is the old bug in a new place"
    assert at_once[0]["severity"] == "error"
    assert "EDIT-PC" in at_once[0]["body"] and "LAPTOP" in at_once[0]["body"]
    # An owner who cannot read a stack trace has to be able to act on it.
    assert "machine.json" in (at_once[0]["fix"] or "")

    noticesmod.run_checks(conn, settings, now=NOW)
    still = [n for n in dbmod.open_notices(conn) if n["kind"] == "duplicate_machine_id"]
    assert still, "the collector's own pass must keep it open while both rows are there"
    assert "EDIT-PC" in still[0]["body"] and "LAPTOP" in still[0]["body"]


def test_a_rename_refused_at_first_sight_adopts_itself_once_the_old_name_is_quiet(env):
    """The self-healing half of SYS-18a, and the reason the verdict is asked
    on every report rather than once.

    A renamed Windows box reboots and is back inside one to three minutes,
    which is inside any window wide enough to catch a clone: its first report
    under the new name is refused exactly like a clone's, ON PURPOSE. What
    tells the two apart is what happens next - a clone's twin keeps reporting
    every 30 s, a renamed computer's old name never speaks again. So the
    second report, with the old row now quiet, adopts; the plan arrives; and
    the notice the refusal raised is closed, because a rename must not leave a
    permanent problem on the home page.
    """
    client, conn, _unused = env
    dbmod.upsert_project(conn, "ff5", "FF5", "/projects/ff5", NOW)
    conn.commit()
    client.post("/api/v1/report", json=_report("EDIT-PC", machine_id=CLONED_ID),
                headers=_headers())
    dbmod.add_selection(conn, "jsmith", "ff5", "admin", NOW, machine="EDIT-PC")
    conn.commit()

    # One to three minutes after the rename: both names look live.
    client.post("/api/v1/report", json=_report("EDIT-PC-RENAMED", machine_id=CLONED_ID),
                headers=_headers())
    assert sorted(r["machine"] for r in dbmod.fetch_machines(conn)) == \
        ["EDIT-PC", "EDIT-PC-RENAMED"]
    assert dbmod.fetch_machine_selections(conn)["ff5"] == [("jsmith", "EDIT-PC")]
    assert [n for n in dbmod.open_notices(conn) if n["kind"] == "duplicate_machine_id"]

    # ...and the old name is never heard from again.
    _quieten(conn, "jsmith", "EDIT-PC")
    client.post("/api/v1/report", json=_report("EDIT-PC-RENAMED", machine_id=CLONED_ID),
                headers=_headers())
    assert [r["machine"] for r in dbmod.fetch_machines(conn)] == ["EDIT-PC-RENAMED"]
    assert dbmod.fetch_machine_selections(conn)["ff5"] == [("jsmith", "EDIT-PC-RENAMED")]
    assert not [n for n in dbmod.open_notices(conn)
                if n["kind"] == "duplicate_machine_id"], \
        "a rename that sorted itself out must not leave a finding behind"


def test_a_new_name_given_a_plan_of_its_own_is_never_adopted_onto(env):
    """The guard on the deferred adoption. Between the refusal and the old row
    going quiet, an admin can tick projects for the new name - and by then it
    is a registered computer with a plan, which is the one thing
    `adopt_renamed_machine` has refused to overwrite since the ultrareview of
    2026-08-19. Under-acting again: both plans stay, and a person decides."""
    client, conn, _unused = env
    for slug in ("ff5", "ff6"):
        dbmod.upsert_project(conn, slug, slug.upper(), f"/projects/{slug}", NOW)
    conn.commit()
    client.post("/api/v1/report", json=_report("EDIT-PC", machine_id=CLONED_ID),
                headers=_headers())
    dbmod.add_selection(conn, "jsmith", "ff5", "admin", NOW, machine="EDIT-PC")
    conn.commit()
    client.post("/api/v1/report", json=_report("LAPTOP", machine_id=CLONED_ID),
                headers=_headers())

    # An admin gives the second name a plan of its own, then the first goes
    # quiet - which on an empty row would have been the deferred adoption.
    dbmod.add_selection(conn, "jsmith", "ff6", "admin", NOW, machine="LAPTOP")
    conn.commit()
    _quieten(conn, "jsmith", "EDIT-PC")
    client.post("/api/v1/report", json=_report("LAPTOP", machine_id=CLONED_ID),
                headers=_headers())

    assert sorted(r["machine"] for r in dbmod.fetch_machines(conn)) == ["EDIT-PC", "LAPTOP"]
    assert dbmod.fetch_machine_selections(conn)["ff5"] == [("jsmith", "EDIT-PC")]
    assert dbmod.fetch_machine_selections(conn)["ff6"] == [("jsmith", "LAPTOP")]


def test_the_invariant_checker_now_sees_the_same_editor_clone(env):
    """SYS-9 invariant 3 inherited SYS-18a's blind spot: it groups `machines`
    by machine_id, and a same-editor clone never left two rows to group. It
    was never wrong, it was starved. Nothing in it changed for this fix, which
    is why the assertion is here and not on its own code."""
    client, conn, settings = env
    for hostname in ("EDIT-PC", "LAPTOP"):
        client.post("/api/v1/report",
                    json=_report(hostname, machine_id=CLONED_ID),
                    headers=_headers())

    ctx = invariants.Ctx(conn, settings, dbmod.utcnow_iso())
    outcome = invariants._check_one_identity_per_computer(ctx)
    assert outcome.state == dbmod.INVARIANT_BROKEN
    subject, detail = outcome.subjects[0]
    assert subject == CLONED_ID
    assert "copied disk is in use on two computers at once" in detail
    assert "jsmith/EDIT-PC" in detail and "jsmith/LAPTOP" in detail


# -- 9: a listing that answers 200 with no folders at all ------------------


def _inventory_rows(conn, project_id: int) -> int:
    """Rows in the table `purge_nas_media_for_inactive` deletes from -- the
    NAS inventory that vanished in DASH-4, counted where it actually lives."""
    return conn.execute(
        "SELECT COUNT(*) FROM nas_media WHERE project_id=?", (project_id,)).fetchone()[0]


def _aged_project(conn, slug: str) -> int:
    """A project last seen well outside `deactivate_missing_projects`' grace
    window, i.e. an ordinary steady-state row rather than one the setup page
    created a minute ago."""
    old = (dt.datetime.fromisoformat(NOW) - dt.timedelta(hours=6)).isoformat()
    pid = dbmod.upsert_project(conn, slug, slug, f"/projects/{slug}", old)
    conn.execute("UPDATE projects SET last_seen=? WHERE id=?", (old, pid))
    dbmod.replace_nas_media(
        conn, pid, [(f"{slug}/A001.mov", "original", ".mov", 1024, 1)],
        tree_sig=slug, n_dirs=1, now=old)
    conn.commit()
    return pid


def test_a_config_with_no_folders_at_all_takes_nothing_off_the_fleet(env):
    """DASH-4, and the server-side twin of the companion's CR-44 / CR-47
    breaker. A Syncthing whose config was re-created or restored answers
    /rest/config with 200 and ZERO folders while `myID` is perfectly valid,
    so none of the empty-myID guards fire.

    What used to happen next is the whole finding: every project flipped
    `active=0`, the hourly prune's `purge_nas_media_for_inactive` deleted the
    entire NAS inventory, the project list and the fleet grid emptied out,
    nobody appeared behind, and `api_tick` answered 404 so an admin could not
    even re-tick - silently, for the one thing this dashboard exists to say.

    So the assertion runs the PRUNE too. A brake that stops the deactivation
    but leaves the inventory purged would be no brake at all.
    """
    _client, conn, settings = env
    slugs = [f"p{i:02d}" for i in range(8)]
    ids = [_aged_project(conn, slug) for slug in slugs]

    result = dbmod.deactivate_missing_projects(conn, [], now=NOW)

    assert result["deactivated"] == 0
    assert "0 of 8 folders" in result["refused"]["message"]
    assert sorted(p["slug"] for p in dbmod.fetch_projects(conn)) == slugs

    dbmod.purge_nas_media_for_inactive(conn)
    for pid in ids:
        assert _inventory_rows(conn, pid) == 1, (
            "the brake held but the prune still emptied the inventory")

    # Persisted, not merely logged - a container restart used to lose even
    # the log line.
    alarm = dbmod.collector_alarms(conn)["deactivation_refusal"]
    assert alarm["active"] == 8 and alarm["would_deactivate"] == 8


# Was a strict xfail when this suite was written: the record carries
# `would_deactivate` and the reader asked for `count`, so the notice was cleared
# on every cycle instead of raised, and a true branch would have KeyError'd
# inside run_checks' own isolation. Fixed in notices.py the same day (SYS-18b).
# It stays here as the regression: this is the last hop, from the persisted
# record to the panel an owner actually reads.
def test_the_refused_deactivation_reaches_a_person_on_the_home_page(env):
    """UX-10's whole point: a diagnosis that reaches only the container log
    reaches nobody. The brake above holds correctly and records correctly;
    this is the last hop, from the record to the panel an owner reads."""
    _client, conn, settings = env
    for i in range(8):
        _aged_project(conn, f"p{i:02d}")
    dbmod.deactivate_missing_projects(conn, [], now=NOW)

    noticesmod.run_checks(conn, settings, now=NOW)
    refusal = [n for n in dbmod.open_notices(conn) if n["kind"] == "deactivation_refusal"]
    assert refusal and refusal[0]["fix"]


def test_a_genuine_removal_under_the_ceiling_still_applies(env):
    """The brake must not become a system that can never forget a project:
    an admin who really did delete two of eight folders gets the deactivation
    they asked for, and the refusal clears itself on that healthy pass."""
    _client, conn, _settings = env
    slugs = [f"p{i:02d}" for i in range(8)]
    ids = {slug: _aged_project(conn, slug) for slug in slugs}

    dbmod.deactivate_missing_projects(conn, [], now=NOW)          # refused
    kept = slugs[:6]
    result = dbmod.deactivate_missing_projects(conn, kept, now=NOW)

    assert result["deactivated"] == 2 and result["refused"] is None
    assert sorted(p["slug"] for p in dbmod.fetch_projects(conn)) == kept
    assert dbmod.collector_alarms(conn)["deactivation_refusal"] is None

    dbmod.purge_nas_media_for_inactive(conn)
    assert _inventory_rows(conn, ids["p07"]) == 0
    assert _inventory_rows(conn, ids["p00"]) == 1


# -- the registry ----------------------------------------------------------


def test_every_server_side_injection_has_a_section():
    """The mirror of the companion module's pin. SYS-18 names nine
    injections; if one of the three that can only be seen here is dropped,
    the number nine stays true in the docs and stops being true in the
    suites."""
    from pathlib import Path

    body = Path(__file__).read_text(encoding="utf-8")
    for number in (7, 8, 9):
        assert f"# -- {number}:" in body, f"no injection section for fault {number}"
    assert len(SERVER_FAULTS) == 3
