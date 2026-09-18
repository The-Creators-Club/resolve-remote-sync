"""The ninth fleet hunt's dashboard mediums and lows (2026-09-18), CR-285.

One test per finding, named for the behaviour it pins; the finding id is in
the docstring and at the code site. The cards half of this wave lives in
`test_cards_pool.py` beside the suite that owns the pool, and the derived
notice-registry test (tests-5) in `test_alerts.py` beside the hand-written one
it replaces.
"""
from __future__ import annotations

import inspect
import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import (app as appmod, assignments, collector as collector_mod,
                              dashboard_update, db as dbmod, health,
                              mount_status, notices, package_store,
                              release_feed, secrets_boot, sessions)
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one-at-all"
NOW = "2026-09-18T12:00:00+00:00"


def _settings(tmp_path, **over):
    kwargs = dict(db_path=str(tmp_path / "hunt.db"), session_secret=SECRET,
                  admin_users=frozenset({"owen"}))
    kwargs.update(over)
    return Settings(**kwargs)


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "hunt.db")
    dbmod.migrate(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# dash-core-1 / dash-core-6: a secret file lands, or the boot says it did not
# ---------------------------------------------------------------------------


def test_a_secret_write_that_fails_leaves_the_previous_file_intact(tmp_path,
                                                                   monkeypatch):
    """dash-core-1 / dash-core-6: the write was `O_CREAT|O_TRUNC` in place, so
    the good copy was destroyed BEFORE the new bytes were written. A failure
    between the two left a ZERO-BYTE file - and `internal.env` is rewritten on
    every boot, where that is the dash-admin-2 outage by another road."""
    path = tmp_path / "dash_session_secret"
    secrets_boot.write_secret_file(path, "the-good-one")

    real = os.fsync

    def boom(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        secrets_boot.write_secret_file(path, "the-half-written-one")
    monkeypatch.setattr(os, "fsync", real)

    assert path.read_text(encoding="utf-8") == "the-good-one"
    # ...and no debris left behind on a volume that is already full.
    assert [p.name for p in tmp_path.iterdir()] == ["dash_session_secret"]


def test_a_zero_byte_secret_file_is_a_lost_secret_not_a_saved_one(tmp_path,
                                                                  monkeypatch):
    """dash-core-1: the DCORE-3 refusal asked `is_file()` only, so a create
    that succeeded and a flush that did not satisfied it - and the dashboard
    served on a secret that existed only in memory. The next restart minted a
    different one and 401'd every browser session and every non-expiring
    identity token in the fleet at once."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dashboard.db"))
    monkeypatch.setenv("DASH_SESSION_SECRET", "what-this-boot-is-using")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "dash_session_secret").write_text("", encoding="utf-8")
    provenance = {"DASH_SESSION_SECRET": "generated"}
    assert appmod.check_persisted_secrets(provenance) == ["DASH_SESSION_SECRET"]
    # ...and the file carrying OTHER bytes than this boot's is lost too.
    (secrets / "dash_session_secret").write_text("something-else",
                                                 encoding="utf-8")
    assert appmod.check_persisted_secrets(provenance) == ["DASH_SESSION_SECRET"]
    # The real shape passes.
    (secrets / "dash_session_secret").write_text("what-this-boot-is-using",
                                                 encoding="utf-8")
    assert appmod.check_persisted_secrets(provenance) == []


# ---------------------------------------------------------------------------
# dash-core-3: OIDC may not mint a name the rest of the dashboard refuses
# ---------------------------------------------------------------------------


def test_oidc_refuses_a_claim_the_rest_of_the_dashboard_will_not_accept(tmp_path):
    """dash-core-3: `username_from_claims` refused only `@`, `/` and `\\`,
    while `db._USERNAME_RE` gates four write paths. A display-name claim
    therefore minted a valid session for a name every tick, every Syncthing
    join and every selection write silently refuses."""
    from ccsync_dashboard import oidc

    s = _settings(tmp_path, oidc_username_claim="name")
    for bad in ("Jurgen Muller", "9lives", "a" * 40, "who:me", "jürgen"):
        with pytest.raises(oidc.OidcError) as err:
            oidc.username_from_claims(s, {"name": bad})
        assert "DASH_OIDC_USERNAME_CLAIM" in str(err.value)
    assert oidc.username_from_claims(s, {"name": "J.Smith-1_x"}) == "j.smith-1_x"


# ---------------------------------------------------------------------------
# dash-core-4 = security-1: the open PWA paths are GET only, as their
# comments have always claimed
# ---------------------------------------------------------------------------


def test_the_open_pwa_paths_are_open_to_reads_only():
    """dash-core-4 = security-1: `_open_path` took a path and `login_gate`
    never read the method, so every verb on those names skipped the session
    check - and under the cards mount `POST /cards/p/<slug>/sw.js` reached the
    checkout's `do_POST`, which json.loads the whole body before any path
    match."""
    for path in ("/cards/sw.js", "/cards/manifest.webmanifest",
                 "/cards/icon.svg", "/manifest.webmanifest", "/sw.js",
                 "/offline", "/favicon.ico",
                 "/cards/p/ep-12345678/sw.js",
                 "/cards/p/ep-12345678/manifest.webmanifest"):
        assert appmod._open_path(path, "GET") is True, path
        assert appmod._open_path(path, "HEAD") is True, path
        for verb in ("POST", "PUT", "DELETE", "PATCH"):
            assert appmod._open_path(path, verb) is False, (path, verb)
    # ...and the credentialed POST targets are untouched.
    for path in ("/login", "/api/v1/login", "/api/v1/report",
                 "/api/v1/diagnostics", "/api/v1/ssh-key"):
        assert appmod._open_path(path, "POST") is True, path


def test_an_unauthenticated_post_to_an_open_path_is_sent_to_login(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/cards/sw.js", follow_redirects=False).status_code != 303
    resp = client.post("/cards/sw.js", follow_redirects=False)
    assert resp.status_code == 303 and "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# dash-core-5: expired sessions are swept by the collector, not only at boot
# ---------------------------------------------------------------------------


def test_the_collector_prunes_expired_sessions(tmp_path, monkeypatch):
    """dash-core-5: `auth_sessions` was the one table with no periodic sweep -
    a session from a phone nobody opens again stayed until the next container
    restart, and `list_all(limit=200)` starts hiding live sessions behind dead
    ones. AND it must not run inside the prune's open write transaction: that
    is a second writer waiting out its background busy timeout while this one
    holds the lock, which is what `test_db_write_locks.py` exists to pin."""
    settings = _settings(tmp_path)
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    calls: list[str] = []
    in_transaction: list[bool] = []

    def sweep():
        in_transaction.append(c.in_transaction)
        calls.append("pruned")

    coll = collector_mod.Collector(settings, client=object(),
                                   session_prune_fn=sweep)
    coll._run_prune(c)
    assert calls == ["pruned"]
    assert in_transaction == [False]
    c.close()


# ---------------------------------------------------------------------------
# dash-db-1 = dash-collector-alerts-4: a long PASS is not a held write lock
# ---------------------------------------------------------------------------


def test_a_long_collector_pass_is_not_reported_as_a_held_write_lock(tmp_path,
                                                                    monkeypatch):
    """dash-db-1: `_timed` measured the WHOLE runner - an SSH walk of the NAS
    tree, Syncthing round trips - and filed anything over the busy timeout as
    a `slow_write` whose body asserts the poll "held the database's write lock
    for longer than a request waits". `_record_inventory`'s own docstring says
    every filesystem walk happens BEFORE the first write, by design."""
    settings = _settings(tmp_path)
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    monkeypatch.setattr(notices, "SLOW_POLL_SECONDS", -1.0)
    coll = collector_mod.Collector(settings, client=object())
    assert coll._timed(c, "inventory", lambda _c: None) is True
    rows = {r["kind"]: r for r in dbmod.open_notices(c)}
    assert notices.SLOW_WRITE_KIND not in rows
    card = rows[notices.SLOW_POLL_KIND]
    assert "write lock" not in card["body"]
    assert "took longer than a cycle" in card["body"]

    # ...and a pass that finishes inside a cycle CLOSES it, which nothing did
    # before: `db.notice` NULLs `cleared_at` on every re-assert, so the card
    # could not even be dismissed.
    monkeypatch.setattr(notices, "SLOW_POLL_SECONDS", 3600.0)
    assert coll._timed(c, "inventory", lambda _c: None) is True
    assert notices.SLOW_POLL_KIND not in {r["kind"] for r in dbmod.open_notices(c)}
    c.close()


def test_a_clean_collector_pass_writes_nothing_about_how_long_it_took(tmp_path):
    """The other half of dash-db-1's fix, and the reason it is not an
    unconditional `clear_notice`: a write transaction per poll per kind puts
    the collector back in front of every companion report."""
    settings = _settings(tmp_path)
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    coll = collector_mod.Collector(settings, client=object())
    coll._timed(c, "prune", lambda _c: None)
    before = c.total_changes
    coll._timed(c, "prune", lambda _c: None)
    coll._timed(c, "prune", lambda _c: None)
    # Two more passes: `poll_runs` rows only, nothing about the timing.
    assert c.total_changes - before == 2
    c.close()


# ---------------------------------------------------------------------------
# dash-db-4: a folder move's prefix is a literal, not a LIKE pattern
# ---------------------------------------------------------------------------


def test_a_move_of_an_underscored_folder_does_not_claim_its_siblings(conn):
    """dash-db-4: `_` is a single-character wildcard in SQL LIKE and is in
    half the folder names this product handles. A directory move of
    `Gold_Card_Meetup` therefore also matched `Gold-Card-Meetup`, and that
    machine was sent a `commands.file_moves` entry for a file it does not
    hold - a wrong per-machine progress row on the project page."""
    now = dbmod.utcnow_iso()
    dbmod.replace_editor_media(conn, "jsmith", "EDIT-PC", "cct-s1",
                               [("Gold_Card_Meetup/A001.mov", "original", 10)], now)
    dbmod.replace_editor_media(conn, "ruskin", "DESK-1", "cct-s1",
                               [("Gold-Card-Meetup/A001.mov", "original", 10)], now)
    conn.commit()
    targets = dbmod.file_move_target_machines(conn, "cct-s1", "Gold_Card_Meetup")
    assert targets == [("jsmith", "EDIT-PC")]


# ---------------------------------------------------------------------------
# dash-db-5 = dash-mounts-ui-3: the picker does not offer a dead end
# ---------------------------------------------------------------------------


def test_the_bucket_option_is_not_offered_beside_a_real_computer(conn):
    """dash-db-5: `_machine_options`' own docstring promises "never a bucket
    option invented beside two real computers", and it then appended one
    whenever the person carried legacy bucket rows. Choosing it filtered every
    column away and the page said "this person has no computer to show a plan
    for yet" - which the picker had just contradicted."""
    now = dbmod.utcnow_iso()
    dbmod.record_known_editor(conn, "editor1", now)
    dbmod.add_selection(conn, "editor1", "ff5", "owen", now,
                        machine=dbmod.ANY_MACHINE)
    conn.commit()
    # No machine yet: the bucket IS the only honest answer.
    assert [o["value"] for o in assignments._machine_options(conn, "editor1")] \
        == [dbmod.ANY_MACHINE]
    dbmod.upsert_machine(conn, "editor1", "DESKTOP-1", now)
    conn.commit()
    options = [o["value"] for o in assignments._machine_options(conn, "editor1")]
    assert options == ["DESKTOP-1"]


# ---------------------------------------------------------------------------
# dash-collector-alerts-2: a dropped move is not a deferred move
# ---------------------------------------------------------------------------


def test_moves_dropped_by_the_cap_become_a_problem_the_server_found(conn):
    """dash-collector-alerts-2: the log line promised the surplus was "picked
    up on later cycles". It is not: `replace_nas_media` has already
    overwritten the only record of the old paths. Those files are a deletion
    to every machine - lane A puts them back, lane B's breaker parks - and the
    only trace was one warning in a container log a recreate throws away."""
    notices.record_moves_dropped(conn, 700, 200, now=NOW)
    rows = {r["kind"]: r for r in dbmod.open_notices(conn)}
    card = rows[notices.MOVES_DROPPED_KIND]
    assert card["severity"] == "error"
    assert "200" in card["body"] and "700" in card["body"]
    assert "MOVE ON THE SERVER" in card["fix"]
    assert notices.MOVES_DROPPED_KIND in dbmod.NOTICE_KINDS


# ---------------------------------------------------------------------------
# dash-collector-alerts-3: a folder RENAMED in place is one row
# ---------------------------------------------------------------------------


def test_a_folder_renamed_in_place_is_one_row_not_one_per_file():
    """dash-collector-alerts-3: `_folder_move` derived its candidate from the
    shared SUFFIX only, so a rename of the leaf folder itself shared nothing
    but the basename and every file fell through to the per-file loop. A
    300-clip `Interviews` -> `Interviews 2026` was 300 rows, 300 command
    entries per holding machine and a third of the 500-row cap in one pass."""
    walk = collector_mod.InventoryWalk(
        slug="cct-s1", project_rel="2026/CCT",
        old=[("Interviews/A001.braw", "original", 10, 1),
             ("Interviews/A002.braw", "original", 20, 2),
             ("Interviews/Proxy/A001.mov", "proxy", 5, 3)],
        new=[("Interviews 2026/A001.braw", "original", 10, 1),
             ("Interviews 2026/A002.braw", "original", 20, 2),
             ("Interviews 2026/Proxy/A001.mov", "proxy", 5, 3)])
    moves = collector_mod.detect_moves([walk])
    assert len(moves) == 1
    assert (moves[0].from_rel, moves[0].to_rel) == ("Interviews", "Interviews 2026")
    assert moves[0].is_dir is True and moves[0].n_files == 3


def test_a_renamed_proxy_folder_is_still_refused_as_a_folder_move():
    """The bar the button applies has not moved: a `Proxy` folder at either
    end is refused, and a detected move may not do what the button would
    have refused."""
    walk = collector_mod.InventoryWalk(
        slug="cct-s1", project_rel="2026/CCT",
        old=[("Interviews/Proxy/A001.mov", "proxy", 5, 3)],
        new=[("Interviews/Proxies/A001.mov", "proxy", 5, 3)])
    moves = collector_mod.detect_moves([walk])
    assert [m.is_dir for m in moves] in ([], [False]), moves
    assert not any(m.is_dir for m in moves)


# ---------------------------------------------------------------------------
# dash-mounts-ui-4: the five conditions the declutter hid
# ---------------------------------------------------------------------------


def test_the_folded_amber_conditions_are_counted_on_the_closed_summary():
    """dash-mounts-ui-4: `detail_notes`' own docstring says its count "is the
    one thing shown beside the collapsed expander, so that folding a row's
    diagnostics away can never hide a real problem silently" - and five
    conditions the 2026-09-11 declutter moved INTO the fold were in neither
    this list nor the headline. An express upload failing for a week drew
    "Idle, nothing owed" and no note count at all."""
    for row, word in (
        ({"guard": {"skipped_exists": 4}}, "upload"),
        ({"guard": {"trash_bytes": 9_000_000_000}}, "trash"),
        ({"guard": {"ingest_staging_bytes": 5}}, "drop folder"),
        ({"guard": {}, "transport": {"express_last_error": "boom"}}, "express"),
        ({"guard": {}, "transport": {"express_dropped": 3}}, "express"),
    ):
        notes = health.detail_notes(row)
        assert notes, row
        assert any(word in n for n in notes), (row, notes)
    # A clean row still has nothing to say.
    assert health.detail_notes({"guard": {"trash_bytes": 1000}, "transport": {}}) == []


# ---------------------------------------------------------------------------
# dash-api-4 = dash-mounts-ui-5: a lane nobody reported is not a healthy lane
# ---------------------------------------------------------------------------


def test_an_unreported_lane_carries_the_flag_the_template_now_reads():
    """dash-api-4: `lane_strip` fills an absent lane with
    `{state: "not reported", chip: green, reported: False}` and the template
    mapped green to `quiet`, so "did not report" and "is fine" were the same
    grey box. The flag was produced and never consumed."""
    strip = health.lane_strip([{"lane": "A", "state": "idle", "chip": "green"}])
    by_lane = {s["label"]: s for s in strip}
    unreported = [s for s in strip if not s.get("reported")]
    assert unreported, by_lane
    assert all(s["state"] == "not reported" for s in unreported)


def test_the_grid_draws_an_unreported_lane_in_its_own_style():
    template = (appmod.TEMPLATES_DIR if hasattr(appmod, "TEMPLATES_DIR") else None)
    from pathlib import Path

    import ccsync_dashboard

    path = (Path(ccsync_dashboard.__file__).parent.parent.parent
            / "templates" / "partials" / "fleet_grid.html")
    text = path.read_text(encoding="utf-8")
    assert "lane.reported" in text
    assert "unknown" in text


# ---------------------------------------------------------------------------
# dash-mounts-ui-6: the b-roll mount names its ROOT, not a directory inside it
# ---------------------------------------------------------------------------


def test_the_broll_mount_records_its_root_and_a_witness_inside_it(tmp_path):
    """dash-mounts-ui-6: b-roll was left on the single-argument shape after
    the hand-off wave added `witness`, so the degraded sentence named
    `/broll-data/proxies` when it was `/broll-data` that was gone."""
    mount_status.reset()
    mount_status.record_root("broll", "/broll-data", witness="/broll-data/proxies")
    assert mount_status.root_of("broll") == ("/broll-data", "/broll-data/proxies")
    mount_status.reset()


# ---------------------------------------------------------------------------
# proxy-tiers-3's dashboard half: an unlistable archive is a PROBLEM
# ---------------------------------------------------------------------------


def test_an_archive_this_server_cannot_list_is_a_problem_it_found(conn, tmp_path):
    """proxy-tiers-3 (owed here by companion-media): an OSError listing the
    archive was swallowed into "no entries", which is byte for byte the answer
    for "this clip has no original" - so every Send to Resolve in the window
    attached the 540p preview and the Resolve project kept pointing at it."""
    mount_status.reset()
    mount_status.record_root("broll", str(tmp_path / "not-mounted"))
    notices._check_broll_archive(conn, _settings(tmp_path), NOW)
    rows = {r["kind"]: r for r in dbmod.open_notices(conn)}
    card = rows[notices.BROLL_ARCHIVE_KIND]
    assert card["severity"] == "error"
    assert "preview" in card["body"]
    assert notices.BROLL_ARCHIVE_KIND in dbmod.NOTICE_KINDS

    # ...and it clears itself when the mount comes back. An EMPTY directory is
    # not the mount coming back (dash-collector-alerts-2, 2026-09-18b): that
    # is what a bind mount leaves behind when it goes, so the archive has to
    # have something in it before this card may clear.
    (tmp_path / "not-mounted").mkdir()
    (tmp_path / "not-mounted" / "Creators_Club").mkdir()
    notices._check_broll_archive(conn, _settings(tmp_path), NOW)
    assert notices.BROLL_ARCHIVE_KIND not in {r["kind"] for r in dbmod.open_notices(conn)}
    mount_status.reset()


# ---------------------------------------------------------------------------
# dash-release-jobs-1: the process can exit 75 with an unwritable /data
# ---------------------------------------------------------------------------


def test_the_restart_still_happens_when_the_state_file_cannot_be_written(
        tmp_path, monkeypatch):
    """dash-release-jobs-1: CR-260g guarded the HEALER's two writes and left
    every other caller alone - but the failure path its own ledger entry
    describes is `finish_restart -> consume_restart_request -> _set_state`,
    which is a WRITE. So the OSError escaped one line later, uvicorn exited 0,
    and run.sh did not re-exec the tree `current.json` already names."""
    settings = _settings(tmp_path)
    dashboard_update._write_json(
        dashboard_update.update_state_path(settings),
        {"restart_requested": True, "owner_pid": os.getpid(),
         "owner_nonce": dashboard_update.PROCESS_NONCE, "in_progress": True})

    def no_space(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(dashboard_update, "_write_json", no_space)
    exits: list[int] = []
    monkeypatch.setattr(dashboard_update, "_exit_process", exits.append)
    assert dashboard_update.finish_restart(settings) is True
    assert exits == [dashboard_update.RESTART_EXIT_CODE]


def test_a_restart_is_signalled_even_when_the_note_about_it_cannot_land(
        tmp_path, monkeypatch):
    """The other half: `request_restart` wrote FIRST, so on the same disk the
    apply worker raised before `_signal_restart()` ever fired and `_fail_state`
    then raised again inside its own except."""
    settings = _settings(tmp_path)

    def no_space(*_a, **_k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(dashboard_update, "_write_json", no_space)
    signalled: list[bool] = []
    monkeypatch.setattr(dashboard_update, "_signal_restart",
                        lambda: signalled.append(True))
    dashboard_update.request_restart(settings)
    assert signalled == [True]
    # ...and the failure recorder inside an `except` does not raise either.
    dashboard_update._fail_state(settings, "something went wrong")


def test_the_restart_intent_survives_a_disk_that_never_took_the_note(
        tmp_path, monkeypatch):
    """dash-release-jobs-1 (2026-09-18b mediums): CR-285S made
    `request_restart`'s write best effort and left the INTENT living only in
    that file - `consume_restart_request` decides from `read_state()`, a pure
    disk read. So on the very disk the fix is about, the note was swallowed,
    the flag was nowhere, uvicorn exited 0, run.sh's loop saw no 75, and the
    container went on serving the OLD code while current.json already named
    the new tree."""
    settings = _settings(tmp_path)
    dashboard_update._restart_requested_nonce = ""

    def no_space(*_a, **_k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(dashboard_update, "_write_json", no_space)
    monkeypatch.setattr(dashboard_update, "_signal_restart", lambda: None)
    exits: list[int] = []
    monkeypatch.setattr(dashboard_update, "_exit_process", exits.append)

    dashboard_update.request_restart(settings)
    # Nothing on disk to read back: this is the whole point.
    assert dashboard_update.read_state(settings).get("restart_requested") in (None, False)
    assert dashboard_update.finish_restart(settings) is True
    assert exits == [dashboard_update.RESTART_EXIT_CODE]
    # Consumed exactly once - a later shutdown that nobody asked for must not
    # inherit the claim and exit 75 again.
    exits.clear()
    assert dashboard_update.finish_restart(settings) is False
    assert exits == []


def test_a_rollback_whose_state_write_fails_still_asks_for_the_restart(
        tmp_path, monkeypatch):
    """dash-release-jobs-1's second half: both `apply` and `rollback` ran an
    UNGUARDED `_set_state(step="restarting", ...)` on the line before
    `request_restart`, so on a read-only /data the OSError escaped one line
    EARLIER than the guarded call and the restart was never asked for at all -
    with the swap already done and current.json already naming the target.
    The writer here fails PART WAY (state file only), which no earlier case
    did."""
    settings = _settings(tmp_path)
    dashboard_update._restart_requested_nonce = ""
    real_write = dashboard_update._write_json
    dashboard_update._write_json(
        dashboard_update.current_json_path(settings),
        {"version": "0.7.49", "previous": ""})

    def picky(path, data):
        if str(path).endswith("update_state.json"):
            raise OSError(30, "Read-only file system")
        return real_write(path, data)

    monkeypatch.setattr(dashboard_update, "_write_json", picky)
    monkeypatch.setattr(dashboard_update, "image_mode", lambda: True)
    monkeypatch.setattr(dashboard_update, "restore_backup",
                        lambda *a, **k: {})
    signalled: list[bool] = []
    monkeypatch.setattr(dashboard_update, "_signal_restart",
                        lambda: signalled.append(True))

    result = dashboard_update.rollback(settings, acknowledge_schema=True,
                                       started_by="owen")
    assert result["version"] == "image"
    assert signalled == [True]
    # ...and the process can still exit 75 with that same disk.
    exits: list[int] = []
    monkeypatch.setattr(dashboard_update, "_exit_process", exits.append)
    assert dashboard_update.finish_restart(settings) is True
    assert exits == [dashboard_update.RESTART_EXIT_CODE]
    dashboard_update._restart_requested_nonce = ""


# ---------------------------------------------------------------------------
# dash-release-jobs-5 / regression-4: the two current.json arithmetic bugs
# ---------------------------------------------------------------------------


def test_reapplying_the_running_version_keeps_the_rollback_target(tmp_path):
    """dash-release-jobs-5: `""` means "the image" to both `rollback` and
    select_code_root, and `previous if previous != version else ""` blanked it
    whenever the version being applied was the one `current.json` already
    names - not because there was no previous tree, but because the arithmetic
    could not express "unchanged".

    tests-1 (2026-09-18b mediums): this case used to re-implement that
    arithmetic in its own body, so a revert of the `apply` hunk left it green.
    It now drives `dashboard_update._carry_previous` - the function `apply`
    itself calls, on the line the fix lives at - from a real `current.json`.
    """
    settings = _settings(tmp_path)
    path = dashboard_update.current_json_path(settings)
    dashboard_update._write_json(path, {"version": "0.7.49", "previous": "0.7.48"})
    held = dashboard_update._read_json(path)
    # Re-applying the running version keeps 0.7.48 as the rollback target.
    assert dashboard_update._carry_previous(held, "0.7.49") == "0.7.48"
    # A genuine step forward supersedes it.
    assert dashboard_update._carry_previous(held, "0.7.50") == "0.7.49"
    # ...and the branch the fix added: a held `previous` naming the tree being
    # applied is not a rollback target, so it becomes "" (the image).
    dashboard_update._write_json(path, {"version": "0.7.50", "previous": "0.7.50"})
    held = dashboard_update._read_json(path)
    assert dashboard_update._carry_previous(held, "0.7.50") == ""
    # The only way this test can pass without guarding the fix is `apply` not
    # using the helper any more, so pin that too.
    assert "_carry_previous(held, version)" in inspect.getsource(
        dashboard_update.apply)


def test_a_tree_that_could_not_say_its_schema_is_not_recorded_as_schema_zero():
    """regression-4: `tree_schema_version`'s own docstring says "None is NOT
    zero and must never read as safe", and `int(... or 0)` collapsed the third
    state - so a tree that could not answer was recorded as claiming schema
    v0, `0 >= live` is false for every live schema, and the rollback CR-259a
    exists to permit was refused for ever with a sentence naming a number the
    tree never claimed."""
    import inspect

    src = inspect.getsource(dashboard_update.apply)
    assert 'staged_manifest["schema_version"] = int(checks.get("schema_version") or 0)' \
        not in src
    assert 'staged_manifest.pop("schema_version", None)' in src


# ---------------------------------------------------------------------------
# dash-release-jobs-2 / -4: the feed's two quiet failures
# ---------------------------------------------------------------------------


def test_a_recall_with_a_capitalised_kind_still_recalls():
    """dash-release-jobs-4: `channel_retractions` folded `platform` and left
    `kind` at `.strip()`, while `companion_packages` stores kind folded and
    `db.retract_package` matches it exactly. A recall spelled `"Companion"`
    un-currented nothing and answered False, which is indistinguishable from
    "we never published that"."""
    out = release_feed.channel_retractions(
        {"retracted": [{"kind": "Companion", "platform": "Windows",
                        "version": "0.9.74"}]})
    assert out and out[0]["kind"] == "companion"
    assert out[0]["platform"] == "windows"


def test_the_feed_may_clear_a_dirty_chip_and_may_not_write_a_commit(conn):
    """dash-release-jobs-2: `git_sha` and `git_dirty` are outside the Ed25519
    signature by design, so a feed host can edit them freely; a sha match
    proves the BYTES agree, not the story about them. The repair exists for
    one bug (0.7.44 read the string "0" as truthy), so that is all it does -
    and a rewritten commit string is not a repair at all."""
    now = dbmod.utcnow_iso()
    dbmod.insert_companion_package(
        conn, version="0.9.0", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=now,
        kind="companion", signature="sig", pubkey_id="k", min_version="",
        signed_binary=False, requires_dashboard="", arch="",
        git_sha="3c7cf8e", git_dirty=True)
    conn.commit()
    record = {"kind": "companion", "platform": "windows", "version": "0.9.0",
              "sha256": "a" * 64, "git_dirty": "0", "git_sha": "deadbeef"}
    assert release_feed.repair_provenance(conn, [record]) == ["companion/windows 0.9.0"]
    row = dbmod.get_package(conn, "windows", "0.9.0", "companion")
    assert bool(row["git_dirty"]) is False
    assert row["git_sha"] == "3c7cf8e", "the feed may not rewrite our commit"

    # ...and the other direction is refused outright: nothing may make a clean
    # row look dirty.
    record["git_dirty"] = "1"
    assert release_feed.repair_provenance(conn, [record]) == []
    row2 = dbmod.get_package(conn, "windows", "0.9.0", "companion")
    assert bool(row2["git_dirty"]) is False


# ---------------------------------------------------------------------------
# live-2 = dash-api-6: a publish places its bytes LAST
# ---------------------------------------------------------------------------


def test_a_publish_that_fails_to_insert_does_not_replace_the_live_artefact(
        tmp_path, monkeypatch):
    """live-2 = dash-api-6, seen live on 2026-09-17: the file was moved into
    its final, SERVED name before the row existed, so a failed insert (the
    UNIQUE constraint of a racing publish, a busy database) left the new bytes
    under a row whose sha256 describes the old ones. Every companion that
    downloaded that build failed its hash check and could not upgrade, while
    the Packages page showed a normal record."""
    settings = _settings(tmp_path, packages_dir=str(tmp_path / "packages"))
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    dest = settings.packages_path() / "windows"
    dest.mkdir(parents=True)
    (dest / "c.exe").write_bytes(b"the old bytes")
    part = tmp_path / "new.part"
    part.write_bytes(b"the new bytes")

    monkeypatch.setattr(package_store.release_trust, "verify_record",
                        lambda *a, **k: (True, "k1"))
    monkeypatch.setattr(dbmod, "insert_companion_package",
                        lambda *a, **k: (_ for _ in ()).throw(
                            sqlite3.IntegrityError("UNIQUE constraint failed")))
    with pytest.raises(sqlite3.IntegrityError):
        package_store.store_verified_package(
            c, settings, kind="companion", platform="windows", version="0.9.0",
            filename="c.exe", sha256="b" * 64, size_bytes=13, min_version="",
            published_at=NOW, signed_binary=False, signature="sig",
            pubkey_id="k1", published_by="owen", make_current=False,
            prune=False, part_path=part)
    assert (dest / "c.exe").read_bytes() == b"the old bytes"
    c.close()


def test_publishing_a_version_this_server_already_holds_is_a_refusal(
        tmp_path, monkeypatch):
    """The other half of live-2: a version already held is a clean answer
    BEFORE anything on disk moves - a no-op for the same bytes, a 409 for
    different ones - never a 500 with a stack trace in an open `server_error`
    notice telling the admin to send the detail to support."""
    settings = _settings(tmp_path, packages_dir=str(tmp_path / "packages"))
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    dbmod.insert_companion_package(
        c, version="0.9.0", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=NOW,
        kind="companion", signature="sig", pubkey_id="k1", min_version="",
        signed_binary=False, requires_dashboard="", arch="")
    c.commit()
    dest = settings.packages_path() / "windows"
    dest.mkdir(parents=True)
    (dest / "c.exe").write_bytes(b"the old bytes")
    monkeypatch.setattr(package_store.release_trust, "verify_record",
                        lambda *a, **k: (True, "k1"))

    def publish(sha):
        part = tmp_path / f"{sha}.part"
        part.write_bytes(b"the new bytes")
        return package_store.store_verified_package(
            c, settings, kind="companion", platform="windows", version="0.9.0",
            filename="c.exe", sha256=sha, size_bytes=13, min_version="",
            published_at=NOW, signed_binary=False, signature="sig",
            pubkey_id="k1", published_by="owen", make_current=False,
            prune=False, part_path=part)

    with pytest.raises(package_store.PackageStoreError) as err:
        publish("b" * 64)
    assert err.value.status_code == 409
    assert (dest / "c.exe").read_bytes() == b"the old bytes"
    # The same bytes are a no-op, not an error.
    assert "already published" in publish("a" * 64)
    assert (dest / "c.exe").read_bytes() == b"the old bytes"
    c.close()


# ---------------------------------------------------------------------------
# live-3: a naive timestamp is a logout, never a 500 on every page
# ---------------------------------------------------------------------------


def test_a_naive_timestamp_is_read_as_utc_rather_than_raising():
    """live-3, seen live on 2026-09-17: `db.age_seconds` subtracts two
    datetimes, `sessions.validate` catches ValueError only, and naive minus
    aware raises TypeError - so one hand-inserted session row made EVERY
    request with that cookie an unhandled 500, including the one to /login
    that would have let the person out of it."""
    assert dbmod.age_seconds("2026-09-18T11:00:00",
                             "2026-09-18T12:00:00+00:00") == 3600.0
    assert dbmod.age_seconds("2026-09-18T11:00:00+00:00",
                             "2026-09-18T12:00:00") == 3600.0


def test_a_session_row_nobody_can_parse_is_no_session(tmp_path):
    settings = _settings(tmp_path)
    store = sessions.SessionStore(str(settings.db_path))
    store.ensure_schema()
    store.create("sid-1", "owen")
    c = dbmod.connect(settings.db_path)
    c.execute("UPDATE auth_sessions SET created_at='not a date' WHERE sid='sid-1'")
    c.commit()
    c.close()
    assert store.validate("sid-1", now=NOW) is None


# ---------------------------------------------------------------------------
# live-4 + the two OWED declarations: the companion's real report shape
# ---------------------------------------------------------------------------


def test_the_companions_real_report_sections_are_all_declared():
    """live-4: `sync_guard.stray_projects` has carried `slugs` and
    `checked_at` since 2026-09-11 and this model never declared them, so
    `ignored_report_sections` - the notice that exists to catch "the
    companions are ahead of the dashboard" - has been open as a warn on this
    fleet for a week, with the fix line "Update the dashboard", on a dashboard
    that IS current. An admin who followed it found nothing to update.

    Plus the two owed here by companion-core in the same shape:
    `proxy_attach.refreshed` (comp-resolve-5) and `resolve_health.
    standins_owed` (comp-broll-tiers-5).

    Fed as the PRODUCER's real dicts, so the next added field fails a test
    instead of opening a notice: an undeclared key inside a sub-model is
    invisible to `model_extra`, which is why this could not be caught by the
    generic walker.
    """
    from ccsync_dashboard import api

    stray = {"count": 2, "bytes": 1234,
             "paths": ["P:/Projects/2026/Stray"], "slugs": ["2026-stray"],
             "checked_at": "2026-09-18T03:42:07+00:00"}
    model = api.StrayProjectsIn(**stray)
    assert model.slugs == ["2026-stray"]
    assert model.checked_at == "2026-09-18T03:42:07+00:00"
    assert model.model_extra == {}

    attach = api.ProxyAttachIn(attached=3, failed=0, refreshed=2,
                               at="2026-09-18T03:42:07+00:00")
    assert attach.refreshed == 2 and attach.model_extra == {}

    resolve = api.ResolveHealthIn(
        out_of_tree=0,
        standins_owed={"count": 4, "why": "the editing proxy has not landed"})
    assert resolve.standins_owed.count == 4
    assert resolve.standins_owed.model_extra == {}
    assert resolve.model_extra == {}


# ---------------------------------------------------------------------------
# live-1 (dashboard half): a healed stall is not a current blockage
# ---------------------------------------------------------------------------


def _stalled(**over):
    row = {"guard": {"stalled_lane": "A", "stalled_seconds": 1500,
                     "stalled_killed": 1,
                     "stalled_at": "2026-09-11T16:26:15+00:00"},
           "lanes": [{"lane": "A", "state": "idle", "last_sync": None}]}
    row["guard"].update(over.pop("guard", {}))
    row.update(over)
    return row


def test_a_stall_older_than_a_day_is_not_a_current_blockage():
    """live-1, seen live on 2026-09-18: SYNC-1 made the stall record
    persistent so a restart could not erase the evidence, and gave it no
    expiry. ruskin's lane A was killed once on 2026-09-11 and recovered the
    same day; a week later his row still said `blocked_reason=lane_stalled
    since 2026-09-11`, his tray was red, and "still not fixed after 4 day(s)"
    had gone out by mail four mornings running."""
    assert health.stall_is_current(_stalled(), NOW) is False
    # A stall from an hour ago is still a stall.
    fresh = _stalled(guard={"stalled_at": "2026-09-18T11:00:00+00:00"})
    assert health.stall_is_current(fresh, NOW) is True


def test_a_lane_that_has_synced_since_the_kill_is_not_stuck_in_it():
    """The other clearing condition, and the one that does not need a clock:
    a lane that completed a pass after the moment it was killed is not stuck
    in that kill."""
    row = _stalled(guard={"stalled_at": "2026-09-18T11:00:00+00:00"})
    row["lanes"] = [{"lane": "A", "state": "idle",
                     "last_sync": "2026-09-18T11:30:00+00:00"}]
    assert health.stall_is_current(row, NOW) is False
    row["lanes"] = [{"lane": "A", "state": "idle",
                     "last_sync": "2026-09-18T10:30:00+00:00"}]
    assert health.stall_is_current(row, NOW) is True


def test_a_stall_with_no_stamp_keeps_the_old_behaviour():
    """An older build, or a report that carried the stall without its stamp:
    "cannot tell" must never quietly turn a real stall green."""
    row = _stalled()
    row["guard"].pop("stalled_at")
    assert health.stall_is_current(row, NOW) is True
    # ...and no stall at all is not a stall.
    assert health.stall_is_current({"guard": {}, "lanes": []}, NOW) is False


# ---------------------------------------------------------------------------
# wire-2: the mounted sub-apps answer a busy database the way the parent does
# ---------------------------------------------------------------------------


def test_a_mounted_sub_app_answers_a_busy_database_with_the_same_503(tmp_path):
    """wire-2: `@app.exception_handler(Exception)` is installed on the
    PARENT's ServerErrorMiddleware, and `/broll`, `/music` and `/ytdl` are
    real ASGI mounts with error middleware of their own - so a busy timeout
    inside the fleet ingest routes was still a plain 500, and the companion's
    ingest client treats any non-200 from `/items/{uid}/result` as TERMINAL:
    the item is failed and minutes of local VLM work are thrown away."""
    from fastapi import FastAPI

    app = create_app(_settings(tmp_path))
    sub = FastAPI()

    @sub.get("/boom")
    def boom():
        raise sqlite3.OperationalError("database is locked")

    @sub.get("/real")
    def real():
        raise RuntimeError("a genuine defect")

    app.mount("/sub", sub)
    appmod._install_busy_handler_on_mounts(app, _busy_handler(app))
    client = TestClient(app, raise_server_exceptions=False)
    # A mount is behind `login_gate` like everything else, and an unauthenticated
    # GET is a 303 to /login that follow_redirects turns into a 200 page.
    from ccsync_dashboard import auth

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    resp = client.get("/sub/boom")
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "30"
    # ...and a real defect is still a 500, not a "try again".
    assert client.get("/sub/real").status_code == 500


def _busy_handler(app):
    """The parent's own handler object, however Starlette is storing it."""
    handlers = getattr(app, "exception_handlers", {})
    for key, fn in handlers.items():
        if key is Exception:
            return fn
    raise AssertionError("the parent app has no catch-all exception handler")


# ---------------------------------------------------------------------------
# security-4: one locate question is bounded before anything is buffered
# ---------------------------------------------------------------------------


def test_a_locate_body_is_refused_by_declared_length():
    """security-4: `LocateIn.files` has no `max_length`, so the route's
    MAX_LOCATE_FILES cap ran AFTER pydantic had built every entry in a body up
    to the 4 MB default, on a single-worker container. A declared-length
    refusal keeps the route's careful 413 sentence, which exists so a caller
    does not read a truncated answer as "not on the server"."""
    limit = appmod._BODY_LIMITS.get("/api/v1/files/locate")
    assert limit == ("POST", appmod.MAX_LOCATE_BODY_BYTES)
    assert appmod.MAX_LOCATE_BODY_BYTES < appmod.MAX_DEFAULT_BODY_BYTES


# ---------------------------------------------------------------------------
# comp-app-3 (owed here by companion-core): "held back" is not "no build"
# ---------------------------------------------------------------------------


def test_a_push_of_a_build_this_machine_cannot_take_is_not_sent(tmp_path):
    """res-fleet-2: the push and the OFFER were computed independently, so a
    machine was asked for ever for a build `_upgrade_info` withholds - and
    `jobs.machine_facts` turns "has an update waiting" into a blanket refusal
    of every job kind, so that computer was out of the whisper/proxy/peaks
    fleet until the 14-day expiry dropped the row."""
    settings = _settings(tmp_path, report_token="r" * 30)
    app = create_app(settings)
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    now = dbmod.utcnow_iso()
    dbmod.insert_companion_package(
        c, version="0.9.74", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=now,
        kind="companion", signature="sig", pubkey_id="k", min_version="",
        signed_binary=False, requires_dashboard="", arch="arm64")
    dbmod.set_current_package(c, "windows", "0.9.74", "companion")
    dbmod.upsert_machine(c, "jsmith", "EDIT-PC", now)
    dbmod.request_machine_update(c, "jsmith", "EDIT-PC", "0.9.74", "owen", now)
    c.commit()
    c.close()

    from ccsync_dashboard import auth

    client = TestClient(app)
    body = {"editor_name": "jsmith", "machine": "EDIT-PC", "platform": "windows",
            "arch": "x86_64", "companion_version": "0.9.70",
            "reported_at": NOW, "lanes": []}
    reply = client.post("/api/v1/report", json=body, headers={
        "X-CCSync-Token": "r" * 30,
        "X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith"),
    }).json()
    assert "upgrade" not in reply.get("commands", {})
    assert reply.get("upgrade_none_reason")


def test_a_build_withheld_from_a_machine_says_so_on_the_reply(conn):
    """comp-app-3: `_upgrade_info` returns None silently for a retracted
    build, one needing a newer dashboard, and one for another processor - and
    the companion cannot tell that from "there is no build", so it clears the
    standing refusal it is on and asks again for ever."""
    from ccsync_dashboard import api

    now = dbmod.utcnow_iso()
    dbmod.insert_companion_package(
        conn, version="0.9.74", platform="windows", filename="c.exe",
        sha256="a" * 64, size_bytes=1, published_by="owen", now=now,
        kind="companion", signature="sig", pubkey_id="k", min_version="",
        signed_binary=False, requires_dashboard="", arch="arm64")
    dbmod.set_current_package(conn, "windows", "0.9.74", "companion")
    conn.commit()
    withheld: list[str] = []
    offer = api._upgrade_info(conn, "windows", "0.9.70", arch="x86_64",
                              withheld=withheld)
    assert offer is None
    assert withheld and "processor" in withheld[0]
    # A machine the build DOES match is offered it, and nothing is withheld.
    withheld2: list[str] = []
    assert api._upgrade_info(conn, "windows", "0.9.70", arch="arm64",
                             withheld=withheld2) is not None
    assert withheld2 == []
