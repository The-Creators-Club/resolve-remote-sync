"""The continuous invariant checker (SYS-9, resilience sweep wave 5).

Pins the properties the finding is about, not the wording: the registry is
DATA and every row evaluates; a broken fact produces a finding carrying the
registry's own fix text; a check that RAISES becomes `check_failed` rather
than silence; an invariant this deployment cannot evaluate renders NOT
CHECKED and never OK; the disk-clone signature (two hostnames on one
machine_id, both reporting inside one interval) is told apart from an old
rename; and the collector kind runs on its own cadence without disturbing the
other nine.
"""

from __future__ import annotations

import sqlite3

import pytest

from ccsync_dashboard import alerts
from ccsync_dashboard import collector as collector_mod
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import invariants
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import FakeSyncthing

NOW = "2026-08-29T12:00:00+00:00"
LATER = "2026-08-29T12:10:00+00:00"
MUCH_LATER = "2026-08-30T12:00:00+00:00"

DEV_A = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"
DEV_B = "IIIIIII-JJJJJJJ-KKKKKKK-LLLLLLL-MMMMMMM-NNNNNNN-OOOOOOO-PPPPPPP"


def _settings(**kw) -> Settings:
    return Settings(session_secret="test-secret", **kw)


def _publish(conn, version: str, min_version: str = "") -> None:
    dbmod.insert_companion_package(
        conn, version=version, platform="windows", filename=f"ccsync-{version}.exe",
        sha256="sha", size_bytes=10, published_by="owen", now=NOW,
        kind="companion", min_version=min_version)


def _ctx(conn, **kw) -> invariants.Ctx:
    return invariants.Ctx(conn, kw.pop("settings", _settings()), kw.pop("now", NOW), **kw)


# ------------------------------------------------------------- the registry

def test_every_registry_row_is_complete_and_the_keys_are_unique():
    """Adding an invariant is adding a ROW: nothing else in the system knows
    the wording, so a row missing its consequence or its fix would reach an
    owner as a blank line on the page."""
    keys = [inv.key for inv in invariants.INVARIANTS]
    assert len(keys) == len(set(keys))
    for inv in invariants.INVARIANTS:
        assert inv.title and inv.consequence and inv.fix
        assert inv.severity in ("error", "warn")
        assert inv.number >= 1
        # A row with no callable must SAY why, or it would render NOT CHECKED
        # with no explanation, which is indistinguishable from a bug.
        assert inv.check is not None or inv.skip_reason
    assert invariants.BY_KEY.keys() == set(keys)


def test_the_whole_registry_evaluates_on_an_empty_database(conn):
    """Every check runs against a database with nothing in it and returns one
    of the four states. Nothing raises, and nothing is silently absent."""
    results = invariants.evaluate(_ctx(conn))
    assert len(results) == len(invariants.INVARIANTS)
    assert {r["key"] for r in results} == set(invariants.BY_KEY)
    for result in results:
        assert result["state"] in dbmod.INVARIANT_STATES
        # An empty deployment can prove nothing, so nothing may claim OK...
        assert result["state"] != dbmod.INVARIANT_OK
        # ...and every not-checked verdict says what would make it checkable.
        if result["state"] == dbmod.INVARIANT_NOT_CHECKED:
            assert result["detail"]


# ------------------------------------------------- a broken fact is a finding

def test_a_broken_invariant_produces_a_notice_carrying_the_registry_fix(conn):
    """A full tick with no Syncthing share: invariant 1, the direct form of
    the thing the fleet page cannot tell you today."""
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="m-1",
                         syncthing_device_id=DEV_A)
    dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1")
    result = invariants.run_cycle(conn, _settings(), NOW, folder_devices={"ff5": []})

    verdicts = {r["key"]: r for r in result["results"]}
    assert verdicts["plan_has_share"]["state"] == dbmod.INVARIANT_BROKEN
    assert verdicts["plan_has_share"]["subjects"][0][0] == "ruskin/DESKTOP-1 -> ff5"

    open_notices = {n["subject"]: n for n in dbmod.open_notices(conn)}
    subject = "plan_has_share: ruskin/DESKTOP-1 -> ff5"
    assert subject in open_notices
    assert open_notices[subject]["fix"] == invariants.BY_KEY["plan_has_share"].fix
    assert open_notices[subject]["kind"] == "invariant_broken"
    # The note is what stops a pass that found something reading as a clean
    # one on the collector health panel.
    assert "broken" in (result["note"] or "")


def test_a_fixed_invariant_closes_its_own_notice(conn):
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="m-1",
                         syncthing_device_id=DEV_A)
    dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1")
    invariants.run_cycle(conn, _settings(), NOW, folder_devices={"ff5": []})
    assert any(n["kind"] == "invariant_broken" for n in dbmod.open_notices(conn))

    invariants.run_cycle(conn, _settings(), LATER, folder_devices={"ff5": [DEV_A]})
    assert not any(n["kind"] == "invariant_broken" for n in dbmod.open_notices(conn))
    stored = dbmod.fetch_invariant_results(conn)["plan_has_share"]
    assert stored["state"] == dbmod.INVARIANT_OK
    # The broken subject row is gone, not left behind as history: this table
    # is a picture of the last pass.
    assert stored["subjects"] == []


def test_the_alert_kind_reports_a_broken_invariant_with_its_fix(conn):
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="m-1",
                         syncthing_device_id=DEV_A)
    dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1")
    invariants.run_cycle(conn, _settings(), NOW, folder_devices={"ff5": []})

    findings = alerts.scan(conn, _settings(), NOW)
    mine = [f for f in findings if f["kind"] == "invariant_broken"]
    assert mine, [f["kind"] for f in findings]
    assert "ruskin/DESKTOP-1 -> ff5" in mine[0]["subject"]
    assert mine[0]["fix"] == invariants.BY_KEY["plan_has_share"].fix
    # The consequence sentence is the registry's, written once.
    assert invariants.BY_KEY["plan_has_share"].consequence in mine[0]["diagnosis"]


# --------------------------------------------------------- a check that raises

def test_a_raising_invariant_becomes_check_failed_and_never_ok(conn, monkeypatch):
    """`alerts.scan`'s posture, one module over: a check that could not run
    must never read as a check that found nothing."""
    def boom(ctx):
        raise RuntimeError("the tree fell over")

    exploding = invariants.Invariant(
        "exploding", 99, "a check that raises", "consequence", "fix", boom)
    monkeypatch.setattr(invariants, "INVARIANTS", (exploding,))
    monkeypatch.setattr(invariants, "BY_KEY", {"exploding": exploding})

    result = invariants.run_cycle(conn, _settings(), NOW)
    verdict = result["results"][0]
    assert verdict["state"] == dbmod.INVARIANT_CHECK_FAILED
    assert "RuntimeError" in verdict["detail"]
    row = conn.execute(
        "SELECT ok, state FROM invariant_results WHERE invariant='exploding' "
        "AND subject=''").fetchone()
    # NULL, not 0 and not 1: the tri-state lives in the data, so no reader can
    # flatten "could not check" into "fine" by accident.
    assert row["ok"] is None and row["state"] == dbmod.INVARIANT_CHECK_FAILED

    failed = [n for n in dbmod.open_notices(conn) if n["kind"] == "invariant_check_failed"]
    assert failed and "unchecked, not as fine" in failed[0]["body"]
    assert "could not run" in (result["note"] or "")


def test_one_raising_invariant_does_not_stop_the_others(conn, monkeypatch):
    def boom(ctx):
        raise RuntimeError("nope")

    rows = (
        invariants.Invariant("boom", 98, "raises", "c", "f", boom),
        invariants.Invariant("fine", 99, "is fine", "c", "f",
                             lambda ctx: invariants.ok("nothing wrong")),
    )
    monkeypatch.setattr(invariants, "INVARIANTS", rows)
    monkeypatch.setattr(invariants, "BY_KEY", {r.key: r for r in rows})
    states = {r["key"]: r["state"]
              for r in invariants.run_cycle(conn, _settings(), NOW)["results"]}
    assert states == {"boom": dbmod.INVARIANT_CHECK_FAILED, "fine": dbmod.INVARIANT_OK}


# ---------------------------------------------------------------- NOT CHECKED

def test_an_unevaluatable_invariant_renders_not_checked_and_never_ok(conn):
    """Invariant 8 is registered and deliberately not evaluated: the
    editor-side retention number lives in the companion build and no computer
    reports it. It must be VISIBLE as unchecked rather than absent, and it
    must never tick green."""
    skipped = invariants.BY_KEY["versioning_agrees"]
    assert skipped.check is None and skipped.skip_reason

    result = invariants.run_cycle(conn, _settings(), NOW)
    verdict = {r["key"]: r for r in result["results"]}["versioning_agrees"]
    assert verdict["state"] == dbmod.INVARIANT_NOT_CHECKED
    assert verdict["detail"] == skipped.skip_reason

    row = conn.execute(
        "SELECT ok, state FROM invariant_results WHERE invariant='versioning_agrees'"
    ).fetchone()
    assert row["ok"] is None                      # the tri-state is in the data
    assert row["state"] == dbmod.INVARIANT_NOT_CHECKED

    on_page = {i["key"]: i for i in invariants.page_view(conn)}["versioning_agrees"]
    assert on_page["state"] == dbmod.INVARIANT_NOT_CHECKED
    assert on_page["detail"] == skipped.skip_reason


def test_a_pass_that_never_ran_renders_not_checked_rather_than_missing(conn):
    """The registry is the spine of the page, not the table: before any pass
    every invariant is listed as NOT CHECKED with no last-checked time."""
    view = invariants.page_view(conn)
    assert len(view) == len(invariants.INVARIANTS)
    assert {v["state"] for v in view} == {dbmod.INVARIANT_NOT_CHECKED}
    assert all(v["checked_at"] == "" for v in view)


def test_the_share_invariant_is_not_checked_when_the_folder_cache_is_cold(conn):
    """`folder_devices is None` means the config job has not completed a pass
    in this process. That is not evidence every tick is unshared - declaring
    the whole fleet broken there is the B16 direction."""
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="m-1",
                         syncthing_device_id=DEV_A)
    dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1")
    outcome = invariants._check_plan_has_share(_ctx(conn, folder_devices=None))
    assert outcome.state == dbmod.INVARIANT_NOT_CHECKED
    assert outcome.detail


def test_snapshot_invariant_is_not_checked_when_the_nas_cannot_be_asked(conn):
    unaskable = _ctx(conn, snapshot_tasks_fn=lambda: None)
    assert invariants._check_snapshot_schedule(unaskable).state == dbmod.INVARIANT_NOT_CHECKED

    none_enabled = _ctx(conn, snapshot_tasks_fn=lambda: [{"dataset": "tank/x",
                                                          "enabled": False}])
    assert invariants._check_snapshot_schedule(none_enabled).state == dbmod.INVARIANT_BROKEN

    fine = _ctx(conn, snapshot_tasks_fn=lambda: [{"dataset": "tank/x", "enabled": True}])
    assert invariants._check_snapshot_schedule(fine).state == dbmod.INVARIANT_OK


# --------------------------------------------------- the disk-clone signature

def test_two_hostnames_on_one_machine_id_reporting_now_is_the_clone_signature(conn):
    """SYS-9 invariant 3's named case. Until SYS-18a was fixed (2026-08-29)
    `adopt_renamed_machine` ping-ponged one plan between two live PCs and
    left only one row for a same-editor pair; the adoption path now refuses
    while the other row is fresh, so a pair like this one reaches the check.
    The end-to-end proof is in tests/chaos/test_fault_injection.py."""
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="same-id")
    dbmod.upsert_machine(conn, "ruskin", "STUDIO-2", LATER, machine_id="same-id")
    outcome = invariants._check_one_identity_per_computer(_ctx(conn, now=LATER))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    subject, detail = outcome.subjects[0]
    assert subject == "same-id"
    assert "copied disk is in use on two computers at once" in detail
    assert "ruskin/DESKTOP-1" in detail and "ruskin/STUDIO-2" in detail


def test_an_old_rename_is_reported_without_the_clone_wording(conn):
    """Two rows on one identity where only one is live is history, not a
    clone in use: still worth naming, not worth the same sentence."""
    dbmod.upsert_machine(conn, "ruskin", "OLD-NAME", NOW, machine_id="same-id")
    dbmod.upsert_machine(conn, "ruskin", "NEW-NAME", MUCH_LATER, machine_id="same-id")
    outcome = invariants._check_one_identity_per_computer(_ctx(conn, now=MUCH_LATER))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert "copied disk" not in outcome.subjects[0][1]


def test_one_syncthing_device_id_on_two_computers_is_broken(conn):
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="a",
                         syncthing_device_id=DEV_A)
    dbmod.upsert_machine(conn, "leso", "MAC-1", NOW, machine_id="b",
                         syncthing_device_id=DEV_A)
    outcome = invariants._check_one_identity_per_computer(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert any(s[0] == DEV_A for s in outcome.subjects)


def test_distinct_identities_are_ok(conn):
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="a",
                         syncthing_device_id=DEV_A)
    dbmod.upsert_machine(conn, "leso", "MAC-1", NOW, machine_id="b",
                         syncthing_device_id=DEV_B)
    outcome = invariants._check_one_identity_per_computer(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_OK


# --------------------------------------------------------- the other invariants

def test_a_machine_with_nothing_ticked_is_ok_and_is_named(conn):
    """Owner decision 2026-09-04: a computer with no projects ticked (the
    Razer) is a legitimate state, not an error. The check still counts and
    still names it, so the row is worth reading, but it never breaks and so
    never files a notice."""
    dbmod.upsert_machine(conn, "alex", "BASE-RIG", NOW, machine_id="base")
    dbmod.upsert_machine(conn, "alex", "RAZER", NOW, machine_id="razer")
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="desk")
    conn.execute("INSERT INTO machine_state (editor_username, machine, reported_at, mode) "
                 "VALUES ('alex', 'BASE-RIG', ?, 'base')", (NOW,))
    dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1")

    outcome = invariants._check_machine_has_plan(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_OK
    assert outcome.subjects == []
    assert "3 computer(s) report" in outcome.detail
    assert "1 has nothing ticked (RAZER)" in outcome.detail


def test_a_base_rig_is_not_named_as_having_nothing_ticked(conn):
    """A base rig holds no tick by design (CR-28), so it is not even
    mentioned; a fleet where every computer has a plan says so."""
    dbmod.upsert_machine(conn, "alex", "BASE-RIG", NOW, machine_id="base")
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="desk")
    conn.execute("INSERT INTO machine_state (editor_username, machine, reported_at, mode) "
                 "VALUES ('alex', 'BASE-RIG', ?, 'base')", (NOW,))
    dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1")

    outcome = invariants._check_machine_has_plan(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_OK
    assert "nothing ticked" not in outcome.detail


def test_a_package_floor_above_its_own_build_is_broken(conn):
    """CR-52's brick, re-asked continuously instead of only at publish."""
    _publish(conn, "0.9.55", min_version="0.9.60")
    dbmod.set_current_package(conn, "windows", "0.9.55", kind="companion")
    outcome = invariants._check_package_floor(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert "above the build itself" in outcome.subjects[0][1]


def test_a_sane_package_floor_is_ok(conn):
    _publish(conn, "0.9.55", min_version="0.9.3")
    dbmod.set_current_package(conn, "windows", "0.9.55", kind="companion")
    assert invariants._check_package_floor(_ctx(conn)).state == dbmod.INVARIANT_OK


def test_an_upload_only_tick_on_an_old_build_is_below_its_floor(conn):
    """Two-digit minors compare correctly here: 0.9.9 is below 0.9.54."""
    dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="m-1")
    conn.execute("INSERT INTO machine_state (editor_username, machine, reported_at, "
                 "companion_version) VALUES ('ruskin', 'DESKTOP-1', ?, '0.9.9')", (NOW,))
    dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    outcome = invariants._check_companion_floor(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert invariants.FLOOR_UPLOAD_ONLY in outcome.subjects[0][1]


def test_a_proxy_with_no_original_beside_it_is_broken(conn):
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Day1/A001.mov", "original", "mov", 10, 1),
        ("Day1/Proxy/A001.mp4", "proxy", "mp4", 2, 1),
        ("Day1/Proxy/GONE.mp4", "proxy", "mp4", 2, 1),
    ], "sig", 2, NOW)
    outcome = invariants._check_proxy_pairs(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert outcome.subjects[0][0] == "ff5/Day1/Proxy/GONE.mp4"


def test_every_proxy_paired_is_ok(conn):
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Day1/A001.mov", "original", "mov", 10, 1),
        ("Day1/Proxy/A001.mp4", "proxy", "mp4", 2, 1),
    ], "sig", 2, NOW)
    assert invariants._check_proxy_pairs(_ctx(conn)).state == dbmod.INVARIANT_OK


def test_a_sony_camera_proxy_beside_its_original_is_ok(conn):
    """2026-09-03: Sony XAVC bodies write `<clip>S03.MP4` into the card's SUB
    folder and editors copy those into Proxy/. Stem-for-stem that was 44
    orphans on one drone shoot."""
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Day1/fx3_20260830_1415.MP4", "original", "mp4", 10, 1),
        ("Day1/Proxy/fx3_20260830_1415.mov", "proxy", "mov", 2, 1),
        ("Day1/Proxy/fx3_20260830_1415S03.MP4", "proxy", "mp4", 2, 1),
    ], "sig", 3, NOW)
    assert invariants._check_proxy_pairs(_ctx(conn)).state == dbmod.INVARIANT_OK


def test_a_sony_camera_proxy_with_no_original_is_still_broken(conn):
    """The exception is a second stem to try, not a blanket ignore: with the
    footage really gone, both stems miss and the check still says so."""
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Day1/A001.mov", "original", "mov", 10, 1),
        ("Day1/Proxy/A001.mp4", "proxy", "mp4", 2, 1),
        ("Day1/Proxy/fx3_20260830_1415S03.MP4", "proxy", "mp4", 2, 1),
    ], "sig", 3, NOW)
    outcome = invariants._check_proxy_pairs(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert outcome.subjects[0][0] == "ff5/Day1/Proxy/fx3_20260830_1415S03.MP4"


def test_an_ordinary_stem_mismatch_is_still_broken(conn):
    """A near miss that is not a camera suffix stays a finding."""
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Day1/A001.mov", "original", "mov", 10, 1),
        ("Day1/Proxy/A001_v2.mp4", "proxy", "mp4", 2, 1),
    ], "sig", 2, NOW)
    outcome = invariants._check_proxy_pairs(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert outcome.subjects[0][0] == "ff5/Day1/Proxy/A001_v2.mp4"


def test_the_camera_proxy_suffix_matches_case_insensitively(conn):
    """Cameras and card copies disagree on case, so `s03` pairs too."""
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Day1/C0007.MP4", "original", "mp4", 10, 1),
        ("Day1/Proxy/C0007s03.mp4", "proxy", "mp4", 2, 1),
    ], "sig", 2, NOW)
    assert invariants._check_proxy_pairs(_ctx(conn)).state == dbmod.INVARIANT_OK


def test_an_appledouble_sidecar_in_proxy_is_not_a_finding(conn):
    """2026-09-03 (CR-138 follow-up): a Mac copied proxies over SMB and left a
    `._<name>` resource fork beside each one, e.g. under
    2026-creator-profiles-season-1/Interviewees/Creator_Interviews/Proxy/.
    The inventory classifies by extension, so 22 of them read as orphaned
    proxies and took the whole 20-item cap the moment the S03 subjects
    cleared. A real orphan beside them is still reported."""
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Interviewees/A001_05181238_C003.mov", "original", "mov", 10, 1),
        ("Interviewees/Proxy/A001_05181238_C003.mp4", "proxy", "mp4", 2, 1),
        ("Interviewees/Proxy/._A001_05181238_C003.mp4", "proxy", "mp4", 4, 1),
        ("Interviewees/Proxy/.DS_Store", "proxy", "", 6, 1),
    ], "sig", 2, NOW)
    assert invariants._check_proxy_pairs(_ctx(conn)).state == dbmod.INVARIANT_OK

    dbmod.replace_nas_media(conn, project_id, [
        ("Interviewees/A001_05181238_C003.mov", "original", "mov", 10, 1),
        ("Interviewees/Proxy/A001_05181238_C003.mp4", "proxy", "mp4", 2, 1),
        ("Interviewees/Proxy/._A001_05181238_C003.mp4", "proxy", "mp4", 4, 1),
        ("Interviewees/Proxy/GONE.mp4", "proxy", "mp4", 2, 1),
    ], "sig2", 2, NOW)
    outcome = invariants._check_proxy_pairs(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert [s[0] for s in outcome.subjects] == ["ff5/Interviewees/Proxy/GONE.mp4"]


def test_an_appledouble_original_cannot_pair_a_proxy(conn):
    """The skip is on BOTH sides: a `._` sidecar filed as an original must not
    become the missing original for a proxy that really has none."""
    project_id = dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.replace_nas_media(conn, project_id, [
        ("Day1/._A001.mov", "original", "mov", 4, 1),
        ("Day1/Proxy/._A001.mp4", "proxy", "mp4", 4, 1),
        ("Day1/Proxy/A001.mp4", "proxy", "mp4", 2, 1),
    ], "sig", 2, NOW)
    outcome = invariants._check_proxy_pairs(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert [s[0] for s in outcome.subjects] == ["ff5/Day1/Proxy/A001.mp4"]


def test_project_markers_are_not_checked_without_a_tree(conn):
    outcome = invariants._check_project_markers(_ctx(conn))
    assert outcome.state == dbmod.INVARIANT_NOT_CHECKED


def test_a_project_folder_that_lost_its_marker_is_broken(conn, tmp_path):
    from ccsync_dashboard import provision

    tree = tmp_path / "Projects"
    (tree / "FF5").mkdir(parents=True)
    (tree / "FF6").mkdir(parents=True)
    provision.write_marker(tree / "FF6", "ff6")
    settings = _settings(projects_dir=str(tree), syncthing_data_prefix="/data/Projects")
    dbmod.upsert_project(conn, "ff5", "FF5", "/data/Projects/FF5", NOW)
    dbmod.upsert_project(conn, "ff6", "FF6", "/data/Projects/FF6", NOW)

    outcome = invariants._check_project_markers(_ctx(conn, settings=settings))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert [s[0] for s in outcome.subjects] == ["ff5"]

    provision.write_marker(tree / "FF5", "ff5")
    assert invariants._check_project_markers(
        _ctx(conn, settings=settings)).state == dbmod.INVARIANT_OK


def test_an_empty_tree_breaks_the_tree_invariant(conn, tmp_path):
    tree = tmp_path / "Projects"
    tree.mkdir()
    settings = _settings(projects_dir=str(tree))
    outcome = invariants._check_tree_markers(_ctx(conn, settings=settings))
    assert outcome.state == dbmod.INVARIANT_BROKEN
    assert "not mounted" in outcome.subjects[0][1]

    (tree / "FF5").mkdir()
    assert invariants._check_tree_markers(
        _ctx(conn, settings=settings)).state == dbmod.INVARIANT_OK


# ------------------------------------------------------------ the collector kind

@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


def test_the_kind_is_registered_with_its_own_cadence(fake):
    settings = _settings(syncthing_url=fake.url, syncthing_api_key="test-key",
                         interval_invariants=900.0)
    collector = Collector(settings, client=SyncthingClient(fake.url, "test-key", timeout=5))
    assert "invariants" in collector_mod.KINDS
    # Before `alerts`, so the alert kind reads rows this pass has just written.
    assert collector_mod.KINDS.index("invariants") < collector_mod.KINDS.index("alerts")
    # Runs without Syncthing: most of it is a table read, and a cloned disk
    # must still be reported on a deployment that has no sync engine.
    assert "invariants" in collector_mod.SYNCTHING_FREE_KINDS
    assert collector._interval("invariants") == 900.0


def test_the_kind_runs_and_leaves_the_other_kinds_alone(conn, fake):
    settings = _settings(syncthing_url=fake.url, syncthing_api_key="test-key")
    collector = Collector(settings, client=SyncthingClient(fake.url, "test-key", timeout=5))
    results = collector.run_cycle(conn, ["config", "invariants"])
    assert results == {"config": True, "invariants": True}
    assert dbmod.fetch_invariant_results(conn)                     # a verdict per invariant
    kinds = {r["kind"]: r for r in dbmod.collector_health(conn)["kinds"]}
    assert kinds["invariants"]["ok"] == 1
    assert kinds["config"]["ok"] == 1


def test_a_failing_invariant_pass_cannot_fail_the_cycle(conn, fake, monkeypatch):
    """Fault isolation: the checker names things, and a checker that took the
    collector down with it would cost more than it tells anybody."""
    def boom(ctx):
        raise RuntimeError("everything is on fire")

    rows = tuple(
        invariants.Invariant(inv.key, inv.number, inv.title, inv.consequence,
                             inv.fix, boom, inv.severity)
        for inv in invariants.INVARIANTS)
    monkeypatch.setattr(invariants, "INVARIANTS", rows)
    monkeypatch.setattr(invariants, "BY_KEY", {r.key: r for r in rows})

    settings = _settings(syncthing_url=fake.url, syncthing_api_key="test-key")
    collector = Collector(settings, client=SyncthingClient(fake.url, "test-key", timeout=5))
    results = collector.run_cycle(conn, ["config", "invariants"])
    assert results["invariants"] is True and results["config"] is True
    states = {r["invariant"] for r in conn.execute(
        "SELECT invariant FROM invariant_results WHERE state=?",
        (dbmod.INVARIANT_CHECK_FAILED,))}
    assert states == set(invariants.BY_KEY)


# ------------------------------------------------------------------- the page

def test_the_page_renders_all_three_states_and_is_admin_only(tmp_path):
    """Full-stack: renders the real template and reads the chips back out, so
    a future template edit that loses [ NOT CHECKED ] fails here rather than
    on somebody's dashboard."""
    from fastapi.testclient import TestClient

    from ccsync_dashboard import auth
    from ccsync_dashboard.app import create_app

    secret = "s"
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=secret, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        # The real Collector thread starts on lifespan entry and runs
        # `invariants` on its own connection, with folder_devices=None because
        # no Syncthing is configured here -- which re-records invariant 1 as
        # NOT CHECKED over the BROKEN verdict this test seeds below. On this
        # rig the GET usually won that race; on CI's Linux runner it did not
        # (2026-08-29). Stop it first, then seed: the same pattern, and the
        # same reason, as test_alerts.py.
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        try:
            dbmod.upsert_machine(conn, "ruskin", "DESKTOP-1", NOW, machine_id="m-1",
                                 syncthing_device_id=DEV_A)
            dbmod.add_selection(conn, "ruskin", "ff5", "owen", NOW, machine="DESKTOP-1")
            invariants.run_cycle(conn, _settings(), NOW, folder_devices={"ff5": []})
        finally:
            conn.close()
        # Anonymous gets the login gate, never the page: what is on it names
        # editors, machines and what is broken about them.
        anon = client.get("/admin/invariants")
        assert "[ INVARIANTS ]" not in anon.text

        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(secret, "owen"))
        resp = client.get("/admin/invariants")
        assert resp.status_code == 200
        html = resp.text
        assert "[ BROKEN ]" in html              # the unshared tick
        assert "[ OK ]" in html                  # identity uniqueness, with one machine
        assert "[ NOT CHECKED ]" in html         # invariant 8 and the rest
        assert invariants.BY_KEY["plan_has_share"].fix.split(".")[0] in html
        assert "[ INVARIANTS ]" in html


def test_the_ledger_survives_a_missing_table(tmp_path):
    """`fetch_invariant_results` is read by a page and by an alert check that
    may run against a database an older build migrated: an absent table is an
    empty picture, never a 500."""
    conn = sqlite3.connect(tmp_path / "bare.db")
    conn.row_factory = sqlite3.Row
    assert dbmod.fetch_invariant_results(conn) == {}
    assert dbmod.broken_invariants(conn) == []
    conn.close()


# --------------------------------------------- bug-hunt-2026-09-03 fix pass

def _one_invariant(monkeypatch, key: str, check):
    """The registry reduced to one row, so a pass is a two-call script."""
    inv = invariants.BY_KEY[key]
    row = invariants.Invariant(inv.key, inv.number, inv.title, inv.consequence,
                               inv.fix, check, inv.severity)
    monkeypatch.setattr(invariants, "INVARIANTS", (row,))
    monkeypatch.setattr(invariants, "BY_KEY", {row.key: row})
    return row


def test_a_check_that_raises_keeps_the_subjects_it_had_broken(conn, monkeypatch):
    """dash-collector-2: `evaluate` turns an exception into a check_failed
    Outcome with NO subjects. An unconditional subject DELETE then wiped the
    broken rows of an invariant nothing had looked at, `broken_invariants`
    went empty without raising, and `deliver` mailed every one of those
    subjects as RECOVERED."""
    key = "plan_has_share"
    broken = invariants.Outcome(dbmod.INVARIANT_BROKEN, "one tick is unshared",
                                [("alex/base", "no share")])
    _one_invariant(monkeypatch, key, lambda ctx: broken)
    invariants.run_cycle(conn, _settings(), NOW)
    assert [r["subject"] for r in dbmod.broken_invariants(conn)] == ["alex/base"]
    assert [(r["kind"], r["cleared_at"]) for r in dbmod.open_notices(conn)
            if r["kind"] == "invariant_broken"] == [("invariant_broken", None)]

    def boom(_ctx):
        raise RuntimeError("transient")

    _one_invariant(monkeypatch, key, boom)
    invariants.run_cycle(conn, _settings(), LATER)
    rows = dbmod.broken_invariants(conn)
    assert [r["subject"] for r in rows] == ["alex/base"]
    # ...and stamped with the OLD check, so the page cannot claim it was
    # looked at this pass.
    assert rows[0]["checked_at"] == NOW
    still_open = [r["subject"] for r in dbmod.open_notices(conn)
                  if r["kind"] == "invariant_broken"]
    assert still_open == [f"{key}: alex/base"]
    # The summary row IS stamped with the failed verdict: the page needs it.
    summary = dbmod.fetch_invariant_results(conn)[key]
    assert summary["state"] == dbmod.INVARIANT_CHECK_FAILED


def test_a_verdict_still_deletes_the_subjects_it_did_not_name(conn, monkeypatch):
    """The picture-of-the-last-pass rule is unchanged for a real verdict."""
    key = "plan_has_share"
    _one_invariant(monkeypatch, key, lambda ctx: invariants.Outcome(
        dbmod.INVARIANT_BROKEN, "unshared", [("alex/base", "no share")]))
    invariants.run_cycle(conn, _settings(), NOW)
    _one_invariant(monkeypatch, key, lambda ctx: invariants.Outcome(
        dbmod.INVARIANT_OK, "all shared"))
    invariants.run_cycle(conn, _settings(), LATER)
    assert dbmod.broken_invariants(conn) == []
    assert [r["subject"] for r in dbmod.open_notices(conn)
            if r["kind"] == "invariant_broken"] == []
