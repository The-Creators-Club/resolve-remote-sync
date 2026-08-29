"""What is protected, and what only looks protected (SYS-14, wave 5).

Pins the property the finding is about, not the wording: **green requires
positive evidence**. A NAS that cannot be asked, an API that raises or times
out, a deployment that was never told which dataset holds what, and a
Synology whose schedules have no API all render CANNOT VERIFY and never
PROTECTED; a schedule that has stopped running is MISSING even though the
task exists; and the CR-10 case (databases in a plain directory with no
snapshot task covering it) is reported out loud rather than rendering green
as it did on every page in the product before this panel.
"""

from __future__ import annotations

import sqlite3

import pytest

from ccsync_dashboard import alerts
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import protection
from ccsync_dashboard.settings import Settings

NOW = "2026-08-29T12:00:00+00:00"

# A TrueNAS periodic snapshot task, in the shape /pool/snapshottask returns.
TREE = "tank/media"
APPS = "tank/apps"


def _settings(**kw) -> Settings:
    return Settings(session_secret="test-secret", **kw)


def _task(dataset: str, *, enabled: bool = True, recursive: bool = False,
          last_run_ms: int | None = None) -> dict:
    task: dict = {"id": 1, "dataset": dataset, "enabled": enabled,
                  "recursive": recursive}
    if last_run_ms is not None:
        task["state"] = {"state": "FINISHED", "datetime": {"$date": last_run_ms}}
    return task


# 2026-08-29T11:00:00Z, one hour before NOW.
FRESH_MS = 1788001200000
# 2026-08-26T12:00:00Z, three days before NOW.
STALE_MS = 1787745600000


def _ctx(conn, tasks=None, *, settings=None, env=None, folder_versioning=None,
         now=NOW, tasks_fn=None) -> protection.Ctx:
    if tasks_fn is None and tasks is not None:
        def tasks_fn():                                       # noqa: ANN202
            return tasks
    return protection.Ctx(
        conn, settings or _settings(), now,
        tasks_fn=tasks_fn or (lambda: None),
        folder_versioning=folder_versioning,
        env=env if env is not None else {})


def _line(results, key):
    return next(r for r in results if r["key"] == key)


# ------------------------------------------------------------- the registry

def test_every_registry_row_is_complete_and_the_keys_are_unique():
    """Adding a safety mechanism is adding a ROW: nothing else in the system
    knows the wording, so a row missing its consequence or its fix reaches an
    owner as a blank line on the panel."""
    keys = [line.key for line in protection.LINES]
    assert len(keys) == len(set(keys))
    for line in protection.LINES:
        assert line.title and line.what and line.consequence and line.fix
        assert line.severity in ("error", "warn")
        assert callable(line.check)
    assert protection.BY_KEY.keys() == set(keys)


def test_nothing_is_green_on_a_deployment_that_can_prove_nothing(conn):
    """THE INVERTED DEFAULT. A dashboard with no NAS, no keys, no dates and no
    computers has evidence for nothing at all, so no line may claim to be
    protected."""
    results = protection.evaluate(_ctx(conn))
    assert len(results) == len(protection.LINES)
    for row in results:
        assert row["state"] != protection.OK
        # ...and every unverifiable verdict says what would make it checkable.
        assert row["detail"]


# ------------------------------------------------- could not ask != nothing

def test_a_nas_that_cannot_be_asked_renders_cannot_verify_and_never_ok(conn):
    results = protection.evaluate(_ctx(conn, tasks_fn=lambda: None))
    for key in ("snapshot_tree", "snapshot_apps", "snapshot_recent"):
        row = _line(results, key)
        assert row["state"] == protection.NOT_CHECKED
        assert row["label"] == "CANNOT VERIFY"
        assert "cannot ask the NAS" in row["detail"]


def test_a_nas_api_that_raises_renders_cannot_verify_not_ok(conn):
    """An exception is not evidence of anything, least of all of safety. It
    must not reach the page as a 500 either."""
    def boom():
        raise TimeoutError("the NAS did not answer in time")

    results = protection.evaluate(_ctx(conn, tasks_fn=boom))
    row = _line(results, "snapshot_tree")
    assert row["state"] == protection.NOT_CHECKED
    assert row["state"] != protection.OK


def test_a_line_whose_check_raises_becomes_could_not_run(conn, monkeypatch):
    monkeypatch.setattr(protection, "_check_release_keys",
                        lambda ctx: (_ for _ in ()).throw(RuntimeError("nope")))
    monkeypatch.setattr(protection, "LINES", tuple(
        protection.ProtectionLine(
            line.key, line.title, line.what, line.consequence, line.fix,
            protection._check_release_keys if line.key == "release_keys" else line.check,
            line.severity)
        for line in protection.LINES))
    row = _line(protection.evaluate(_ctx(conn)), "release_keys")
    assert row["state"] == protection.CHECK_FAILED
    assert row["label"] == "COULD NOT RUN"
    assert "RuntimeError" in row["detail"]


def test_dsm_is_amber_for_ever_and_says_to_confirm_in_dsm(conn):
    """Synology keeps snapshot schedules in a package with no API. Honest
    amber, for the life of the deployment, is the correct answer; a green
    chip would be a guess."""
    ctx = _ctx(conn, settings=_settings(nas_kind="synology"),
               tasks_fn=lambda: None,
               env={protection.ENV_TREE_DATASET: TREE,
                    protection.ENV_APPS_DATASET: APPS})
    for key in ("snapshot_tree", "snapshot_apps", "snapshot_recent"):
        row = _line(protection.evaluate(ctx), key)
        assert row["state"] == protection.NOT_CHECKED
        assert "confirm in DSM" in row["detail"]


# ------------------------------------------------------- the snapshot lines

def test_a_covering_enabled_task_is_the_only_thing_that_makes_it_green(conn):
    env = {protection.ENV_TREE_DATASET: TREE, protection.ENV_APPS_DATASET: APPS}
    results = protection.evaluate(_ctx(
        conn, [_task(TREE, last_run_ms=FRESH_MS), _task(APPS, last_run_ms=FRESH_MS)],
        env=env))
    assert _line(results, "snapshot_tree")["state"] == protection.OK
    assert _line(results, "snapshot_apps")["state"] == protection.OK
    assert _line(results, "snapshot_recent")["state"] == protection.OK


def test_a_disabled_task_does_not_count_as_a_schedule(conn):
    results = protection.evaluate(_ctx(
        conn, [_task(TREE, enabled=False)], env={protection.ENV_TREE_DATASET: TREE}))
    assert _line(results, "snapshot_tree")["state"] == protection.BROKEN


def test_a_recursive_parent_task_covers_a_child_dataset(conn):
    """setup_snapshots.py writes recursive tasks on purpose, so a dataset that
    gains a child later does not fall outside the backup."""
    results = protection.evaluate(_ctx(
        conn, [_task("tank", recursive=True)],
        env={protection.ENV_TREE_DATASET: TREE}))
    assert _line(results, "snapshot_tree")["state"] == protection.OK
    results = protection.evaluate(_ctx(
        conn, [_task("tank", recursive=False)],
        env={protection.ENV_TREE_DATASET: TREE}))
    assert _line(results, "snapshot_tree")["state"] == protection.BROKEN


def test_cr10_the_apps_data_with_no_task_covering_it_is_reported(conn):
    """CR-10, said out loud. The live TrueNAS keeps dashboard.db, broll.db and
    music.db under a plain directory with no snapshot task at all; before this
    panel every page rendered green about it."""
    results = protection.evaluate(_ctx(
        conn, [_task(TREE, last_run_ms=FRESH_MS)],
        env={protection.ENV_TREE_DATASET: TREE, protection.ENV_APPS_DATASET: APPS}))
    row = _line(results, "snapshot_apps")
    assert row["state"] == protection.BROKEN
    assert row["label"] == "MISSING"
    assert APPS in row["subjects"][0]["subject"]
    assert "point-in-time" in row["subjects"][0]["detail"]


def test_an_unnamed_dataset_is_cannot_verify_and_names_the_variable(conn):
    """"Nobody told this server which dataset" is not "there is no snapshot":
    it is a question that was never asked, and the fix is the variable."""
    row = _line(protection.evaluate(_ctx(conn, [_task(TREE)])), "snapshot_apps")
    assert row["state"] == protection.NOT_CHECKED
    assert protection.ENV_APPS_DATASET in row["detail"]


def test_a_schedule_that_stopped_running_is_missing(conn):
    """WPK-6: a snapshot that failed silently on every run for weeks. The task
    existing is not the evidence; the last run is."""
    row = _line(protection.evaluate(_ctx(
        conn, [_task(TREE, last_run_ms=STALE_MS)],
        env={protection.ENV_TREE_DATASET: TREE})), "snapshot_recent")
    assert row["state"] == protection.BROKEN
    assert "72 hour(s) old" in row["subjects"][0]["detail"]


def test_a_nas_that_does_not_report_a_last_run_is_cannot_verify(conn):
    row = _line(protection.evaluate(_ctx(conn, [_task(TREE)])), "snapshot_recent")
    assert row["state"] == protection.NOT_CHECKED
    assert row["state"] != protection.OK


def test_no_enabled_task_at_all_means_nothing_has_been_snapshotted(conn):
    row = _line(protection.evaluate(_ctx(conn, [_task(TREE, enabled=False)])),
                "snapshot_recent")
    assert row["state"] == protection.BROKEN


def test_an_iso_last_run_is_read_as_well_as_an_epoch(conn):
    """Two TrueNAS versions, two shapes. Neither may read as "never ran"."""
    task = _task(TREE)
    task["state"] = {"state": "FINISHED", "datetime": "2026-08-29T11:30:00+00:00"}
    row = _line(protection.evaluate(_ctx(conn, [task])), "snapshot_recent")
    assert row["state"] == protection.OK


# --------------------------------------------------------- the release keys

def test_release_keys_are_counted_and_never_rendered(conn):
    key = "MC4CAQAwBQYDK2VwBCIEIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    ctx = _ctx(conn, settings=_settings(release_pubkeys=(key,)))
    row = _line(protection.evaluate(ctx), "release_keys")
    assert row["state"] == protection.OK
    assert key not in row["detail"]
    assert "1 release signing key(s)" in row["detail"]


def test_no_release_key_is_missing_not_silence(conn):
    row = _line(protection.evaluate(_ctx(conn)), "release_keys")
    assert row["state"] == protection.BROKEN
    assert "DASH_RELEASE_PUBKEYS" in row["detail"]


# ------------------------------------------------------ the admin-set dates

def test_the_key_backup_is_missing_until_an_admin_records_it(conn):
    settings = _settings(release_pubkeys=("k",))
    row = _line(protection.evaluate(_ctx(conn, settings=settings)), "release_key_backup")
    assert row["state"] == protection.BROKEN

    protection.set_ack(conn, protection.ACK_KEY_BACKUP, "2026-08-20", "owen", now=NOW)
    row = _line(protection.evaluate(_ctx(conn, settings=settings)), "release_key_backup")
    assert row["state"] == protection.OK
    assert "2026-08-20" in row["detail"]


def test_a_site_with_no_signing_key_has_nothing_to_have_backed_up(conn):
    row = _line(protection.evaluate(_ctx(conn)), "release_key_backup")
    assert row["state"] == protection.NOT_CHECKED


def test_a_restore_drill_ages_out_after_a_year(conn):
    protection.set_ack(conn, protection.ACK_RESTORE_DRILL, "2026-08-01", "owen", now=NOW)
    assert _line(protection.evaluate(_ctx(conn)), "restore_drill")["state"] == protection.OK
    protection.set_ack(conn, protection.ACK_RESTORE_DRILL, "2024-08-01", "owen", now=NOW)
    row = _line(protection.evaluate(_ctx(conn)), "restore_drill")
    assert row["state"] == protection.BROKEN
    assert "over a year ago" in row["subjects"][0]["detail"]


def test_a_future_or_unreadable_date_is_refused_where_it_is_typed(conn):
    """A swallowed acknowledgement is a line that reads MISSING for ever while
    the admin believes they cleared it."""
    with pytest.raises(ValueError):
        protection.set_ack(conn, protection.ACK_RESTORE_DRILL, "yesterday", "owen", now=NOW)
    with pytest.raises(ValueError):
        protection.set_ack(conn, protection.ACK_RESTORE_DRILL, "2027-01-01", "owen", now=NOW)
    with pytest.raises(ValueError):
        protection.set_ack(conn, "something_else", "2026-08-01", "owen", now=NOW)


def test_the_recovery_package_records_a_drill_into_the_same_store(conn):
    """SYS-15d records a drill the dashboard ran itself. It is a DATE the
    panel reads, not a boolean the panel computes, so this needs no edit
    here."""
    protection.record_restore_drill(conn, "the dashboard", now=NOW)
    assert protection.read_acks(conn)[protection.ACK_RESTORE_DRILL]["date"] == "2026-08-29"
    assert _line(protection.evaluate(_ctx(conn)), "restore_drill")["state"] == protection.OK


# ----------------------------------------------------- deleted-file copies

def test_server_versioning_is_cannot_verify_until_the_folders_are_read(conn):
    row = _line(protection.evaluate(_ctx(conn)), "server_versioning")
    assert row["state"] == protection.NOT_CHECKED


def test_a_project_folder_with_no_version_history_is_missing(conn):
    good = {"type": "staggered", "params": {"maxAge": "31536000"}}
    row = _line(protection.evaluate(_ctx(
        conn, folder_versioning={"ff5": good, "ff6": {}})), "server_versioning")
    assert row["state"] == protection.BROKEN
    assert row["subjects"][0]["subject"] == "ff6"

    row = _line(protection.evaluate(_ctx(
        conn, folder_versioning={"ff5": good})), "server_versioning")
    assert row["state"] == protection.OK
    assert "365 day(s)" in row["detail"]


def test_editor_trash_needs_a_report_before_it_can_be_green(conn):
    row = _line(protection.evaluate(_ctx(conn)), "editor_trash")
    assert row["state"] == protection.NOT_CHECKED

    conn.execute(
        "INSERT INTO machine_state (editor_username, machine, reported_at, trash_bytes) "
        "VALUES (?,?,?,?)", ("ruskin", "DESKTOP-1", NOW, 10 * 1024 ** 3))
    assert _line(protection.evaluate(_ctx(conn)), "editor_trash")["state"] == protection.OK

    conn.execute("UPDATE machine_state SET trash_bytes=?", (80 * 1024 ** 3,))
    row = _line(protection.evaluate(_ctx(conn)), "editor_trash")
    assert row["state"] == protection.BROKEN
    assert "ruskin/DESKTOP-1" == row["subjects"][0]["subject"]


# ------------------------------------------------------------- the notices

def test_a_missing_mechanism_files_a_notice_carrying_its_own_fix(conn):
    protection.run_cycle(conn, _settings(), NOW,
                         tasks_fn=lambda: [_task(TREE, last_run_ms=FRESH_MS)])
    rows = [r for r in dbmod.open_notices(conn)
            if r["kind"] == protection.NOTICE_MISSING]
    subjects = {r["subject"] for r in rows}
    assert any(s.startswith("release_keys") for s in subjects)
    row = next(r for r in rows if r["subject"].startswith("release_keys"))
    assert row["fix"] == protection.BY_KEY["release_keys"].fix
    assert row["severity"] == "error"


def test_an_unverifiable_mechanism_files_a_warn_notice_not_silence(conn):
    protection.run_cycle(conn, _settings(), NOW, tasks_fn=lambda: None)
    rows = [r for r in dbmod.open_notices(conn)
            if r["kind"] == protection.NOTICE_UNVERIFIABLE]
    assert {"snapshot_tree", "snapshot_apps", "snapshot_recent"} <= {r["subject"] for r in rows}
    assert all(r["severity"] == "warn" for r in rows)


def test_a_mechanism_that_comes_back_closes_its_own_notice(conn):
    protection.run_cycle(conn, _settings(), NOW, tasks_fn=lambda: None)
    assert any(r["kind"] == protection.NOTICE_MISSING and
               r["subject"].startswith("release_keys")
               for r in dbmod.open_notices(conn))
    protection.run_cycle(conn, _settings(release_pubkeys=("k",)), NOW,
                         tasks_fn=lambda: None)
    assert not any(r["subject"].startswith("release_keys")
                   for r in dbmod.open_notices(conn))


def test_both_notice_kinds_are_registered_with_their_writer(conn):
    """A kind registered with no writer ticks itself [ OK ] on the WHAT THE
    SERVER CHECKS panel (finding 1 of the 2026-08-28 fix pass). Both of these
    have one, and this proves the pass stamps the evidence."""
    assert protection.NOTICE_MISSING in dbmod.NOTICE_KINDS
    assert protection.NOTICE_UNVERIFIABLE in dbmod.NOTICE_KINDS
    protection.run_cycle(conn, _settings(), NOW, tasks_fn=lambda: None)
    checked = dbmod.notice_check_times(conn)
    assert protection.NOTICE_MISSING in checked
    assert protection.NOTICE_UNVERIFIABLE in checked


# --------------------------------------------------------------- the alerts

def test_the_alert_kinds_report_both_halves_with_their_fixes(conn):
    protection.run_cycle(conn, _settings(), NOW, tasks_fn=lambda: None)
    findings = alerts.scan(conn, _settings(), NOW)
    by_kind: dict[str, list] = {}
    for finding in findings:
        by_kind.setdefault(finding["kind"], []).append(finding)
    missing = by_kind.get("protection_missing") or []
    unverifiable = by_kind.get("protection_unverifiable") or []
    assert any(f["subject"] == "release_keys" for f in missing)
    assert any(f["subject"] == "snapshot_tree" for f in unverifiable)
    assert all(f["severity"] == "error" for f in missing)
    assert all(f["severity"] == "warn" for f in unverifiable)
    assert protection.BY_KEY["release_keys"].fix in {f["fix"] for f in missing}


def test_the_alert_kinds_are_quiet_on_a_database_with_no_pass(conn):
    """A dashboard that has never run a pass has nothing to say HERE: the
    panel says it for itself, and inventing findings from an empty store
    would alert on every fresh boot."""
    findings = alerts.scan(conn, _settings(), NOW)
    assert not [f for f in findings if f["kind"].startswith("protection_")]


# ---------------------------------------------------------- the page + report

def test_the_panel_and_the_weekly_report_both_carry_it(conn):
    protection.run_cycle(conn, _settings(), NOW,
                         tasks_fn=lambda: [_task(TREE, last_run_ms=FRESH_MS)])
    view = protection.page_view(conn)
    assert len(view["lines"]) == len(protection.LINES)
    assert view["counts"][protection.BROKEN] >= 1
    assert view["checked_at"] == NOW

    subject, text = alerts.compose_weekly(conn, NOW, _settings())
    assert "WHAT IS PROTECTED" in text
    assert "[ MISSING ]" in text
    assert "[ CANNOT VERIFY ]" in text
    # The standing red line SYS-8 asked for, with the action beside it.
    assert protection.BY_KEY["release_keys"].fix.split(".")[0] in text


def test_the_panel_renders_every_line_before_any_pass_has_run(conn):
    """THE REGISTRY IS THE SPINE. A panel that silently omitted a safety
    mechanism it had not evaluated yet would be the exact bug this module
    exists to end."""
    view = protection.page_view(conn)
    assert [r["key"] for r in view["lines"]] == [line.key for line in protection.LINES]
    assert all(r["state"] == protection.NOT_CHECKED for r in view["lines"])
    assert all(r["label"] == "CANNOT VERIFY" for r in view["lines"])


def test_the_store_survives_a_database_an_older_build_migrated(tmp_path):
    conn = sqlite3.connect(tmp_path / "bare.db")
    conn.row_factory = sqlite3.Row
    assert protection.read_acks(conn) == {}
    assert protection.stored_results(conn) == {}
    assert len(protection.page_view(conn)["lines"]) == len(protection.LINES)
    conn.close()


def test_the_page_renders_the_three_states_and_is_admin_only(tmp_path):
    """Full-stack: renders the real template and reads the chips back out, so
    a template edit that loses [ CANNOT VERIFY ] fails here rather than on
    somebody's dashboard."""
    from fastapi.testclient import TestClient

    from ccsync_dashboard import auth
    from ccsync_dashboard.app import create_app

    secret = "s"
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=secret, admin_users=frozenset({"owen"}),
        release_pubkeys=("k",),
    ))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "dash.db")
        try:
            protection.set_ack(conn, protection.ACK_RESTORE_DRILL, "2026-08-01",
                               "owen", now=NOW)
            protection.run_cycle(
                conn, Settings(session_secret=secret, release_pubkeys=("k",)), NOW,
                tasks_fn=lambda: None)
        finally:
            conn.close()

        anon = client.get("/admin/protection")
        assert "[ PROTECTION ]" not in anon.text

        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(secret, "owen"))
        resp = client.get("/admin/protection")
        assert resp.status_code == 200
        html = resp.text
        assert "[ PROTECTION ]" in html
        assert "[ PROTECTED ]" in html        # the release key, and the drill
        assert "[ MISSING ]" in html          # the backup nobody has confirmed
        assert "[ CANNOT VERIFY ]" in html    # every snapshot line: no NAS here
        assert protection.BY_KEY["snapshot_apps"].fix.split(".")[0] in html


def test_an_admin_can_record_a_date_and_a_bad_one_is_refused(tmp_path):
    from fastapi.testclient import TestClient

    from ccsync_dashboard import auth
    from ccsync_dashboard.app import create_app

    secret = "s"
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=secret, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(secret, "owen"))
        resp = client.post("/partials/admin/protection/ack",
                           data={"key": "restore_drill", "date": "2026-08-02"})
        assert resp.status_code == 200
        assert "recorded 2026-08-02" in resp.text

        bad = client.post("/partials/admin/protection/ack",
                          data={"key": "restore_drill", "date": "2099-01-01"})
        assert "future" in bad.text

        conn = dbmod.connect(tmp_path / "dash.db")
        try:
            assert protection.read_acks(conn)["restore_drill"]["date"] == "2026-08-02"
            assert protection.read_acks(conn)["restore_drill"]["by"] == "owen"
        finally:
            conn.close()
