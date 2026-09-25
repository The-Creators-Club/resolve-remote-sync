"""bug-hunt 2026-09-24, fix wave 2, group d-db (db.py).

bug-dash-db-1   the job window is per kind, and an offered id is claimed by id
bug-dash-db-2   a capped proxy manifest no longer invents downloads owed for ever
bug-dash-db-3   forgetting a computer/person takes its diagnostics bundles too
bug-wire-1      RES-10's "relinked after all" answer clears relink_pending
logic-plans-1   an untick of a bucket-inherited project really removes it
logic-plans-4   a move out of a borrowed folder reaches the borrowing machines
logic-ytdl-jobs-5  prune's lease sweep takes the operator's cooldown
"""
from __future__ import annotations

from ccsync_dashboard import db as dbmod

NOW = "2026-09-25T10:00:00+00:00"


def _iso_ago(seconds: float, now: str = NOW) -> str:
    return (dbmod.parse_iso(now) - dbmod.dt.timedelta(seconds=seconds)).isoformat()


# ------------------------------------------------------------ bug-dash-db-1

def _starved_queue(conn):
    for i in range(210):
        dbmod.create_job(conn, "whisper", {"clip": ["vault", f"w{i}.wav"]},
                         requires={"gpu_vram_gb": 6}, now=NOW)
    peaks = dbmod.create_job(conn, "peaks", {"clip": ["vault", "p.wav"]}, now=NOW)
    conn.commit()
    return peaks


def test_a_kind_nobody_can_run_does_not_hide_the_jobs_behind_it(conn):
    peaks = _starved_queue(conn)
    ids = [j["id"] for j in dbmod.queued_jobs(conn)]
    assert peaks in ids
    # ...and whisper's own window is still bounded
    assert sum(1 for j in dbmod.queued_jobs(conn) if j["kind"] == "whisper") == 200
    # scheduler order is kept across kinds
    assert ids == sorted(ids)
    assert "_kind_rank" not in dbmod.queued_jobs(conn)[0]


def test_the_claim_reaches_a_job_past_the_window(conn):
    peaks = _starved_queue(conn)
    got = dbmod.claim_next_job(conn, "ed", "RIG", capabilities={}, max_running={})
    assert got is not None and got["id"] == peaks


def test_an_offered_id_deep_in_one_kind_is_claimed_by_id(conn):
    ids = [dbmod.create_job(conn, "peaks", {"clip": ["vault", f"p{i}.wav"]}, now=NOW)
           for i in range(205)]
    conn.commit()
    last = ids[-1]
    assert last not in [j["id"] for j in dbmod.queued_jobs(conn)]
    got = dbmod.claim_next_job(conn, "ed", "RIG", capabilities={},
                               allowed_ids=[last])
    assert got is not None and got["id"] == last
    # the claimant's own narrowing still intersects, never widens
    assert dbmod.claim_next_job(conn, "ed", "RIG", capabilities={},
                                allowed_ids=[ids[0]], ids=[ids[1]]) is None


def test_priority_still_outranks_age_across_kinds(conn):
    old = dbmod.create_job(conn, "peaks", {"a": 1}, now=NOW)
    urgent = dbmod.create_job(conn, "audio-extract", {"a": 2}, priority=5, now=NOW)
    conn.commit()
    assert [j["id"] for j in dbmod.queued_jobs(conn)] == [urgent, old]


# ------------------------------------------------------------ bug-dash-db-2

def _backlog_fixture(conn, *, nas_proxies: int, held_proxies: int,
                     listed_proxies: int, originals_listed: int = 10):
    pid = dbmod.upsert_project(conn, "et", "Energy Transition", "2026/ET", NOW)
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.add_selection(conn, "ed", "et", created_by="admin", now=NOW, machine="LAP")
    rows = [(f"Proxy/p{i:05d}.mp4", "proxy", "mp4", 10, 1) for i in range(nas_proxies)]
    rows += [(f"o{i:03d}.mov", "original", "mov", 100, 1) for i in range(originals_listed)]
    dbmod.replace_nas_media(conn, pid, rows, "sig", 2, NOW, force=True)
    files = [(f"o{i:03d}.mov", "original", 100) for i in range(originals_listed)]
    files += [(f"Proxy/p{i:05d}.mp4", "proxy", 10) for i in range(listed_proxies)]
    dbmod.replace_editor_media(conn, "ed", "LAP", "et", files, NOW)
    dbmod.upsert_editor_media_project(
        conn, editor="ed", machine="LAP", slug="et", mode="editor",
        n_originals=originals_listed, bytes_originals=100 * originals_listed,
        n_proxies=held_proxies, bytes_proxies=10 * held_proxies,
        truncated=listed_proxies < held_proxies, now=NOW)
    conn.commit()


def test_a_machine_holding_every_proxy_past_the_cap_owes_nothing(conn):
    _backlog_fixture(conn, nas_proxies=2500, held_proxies=2500, listed_proxies=2000)
    down = [q for q in dbmod.fetch_sync_backlog(conn) if q["direction"] == "down"]
    assert down == []


def test_a_capped_manifest_still_reports_what_is_really_missing(conn):
    _backlog_fixture(conn, nas_proxies=2500, held_proxies=2300, listed_proxies=2000)
    down = [q for q in dbmod.fetch_sync_backlog(conn) if q["direction"] == "down"]
    assert len(down) == 1
    assert down[0]["n_files"] == 200 and down[0]["bytes"] == 2000
    assert down[0]["files"] == [] and down[0]["manifest_truncated"] is True


def test_an_uncapped_proxy_list_keeps_the_exact_diff(conn):
    _backlog_fixture(conn, nas_proxies=30, held_proxies=20, listed_proxies=20)
    down = [q for q in dbmod.fetch_sync_backlog(conn) if q["direction"] == "down"]
    assert down[0]["n_files"] == 10 and len(down[0]["files"]) == 10


# ------------------------------------------------------------ bug-dash-db-3

def _bundle(conn, editor, machine):
    dbmod.record_diagnostics(conn, editor=editor, machine=machine, machine_id="",
                             trigger="manual", at=NOW, received_at=NOW, text="paths")


def test_forgetting_a_computer_takes_its_diagnostics(conn):
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.upsert_machine(conn, "ed", "DESK", NOW)
    _bundle(conn, "ed", "LAP")
    _bundle(conn, "ed", "DESK")
    out = dbmod.forget_machine(conn, "ed", "LAP")
    assert out["deleted"]["diagnostics"] == 1
    left = {(r["editor"], r["machine"]) for r in dbmod.newest_diagnostics_per_machine(conn)}
    assert left == {("ed", "DESK")}


def test_forgetting_a_person_takes_every_bundle(conn):
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    _bundle(conn, "ed", "LAP")
    _bundle(conn, "ed", "UNREGISTERED")
    _bundle(conn, "other", "PC")
    out = dbmod.forget_editor(conn, "ed")
    assert out["deleted"]["diagnostics"] == 2
    left = {(r["editor"], r["machine"]) for r in dbmod.newest_diagnostics_per_machine(conn)}
    assert left == {("other", "PC")}


# --------------------------------------------------------------- bug-wire-1

def _move(conn):
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    move_id = dbmod.record_file_move(
        conn, from_slug="ff5", from_project_rel="2026/FF5", from_rel="A/clip.mp4",
        to_slug="ff5", to_project_rel="2026/FF5", to_rel="B/clip.mp4",
        is_dir=False, proxies_moved=0, requested_by="admin", now=NOW,
        targets=[("ed", "LAP")], state=dbmod.FILE_MOVE_DONE)
    conn.commit()
    return move_id


def _target(conn, move_id):
    return conn.execute(
        "SELECT ok, relink_pending, detail, applied_at FROM file_move_targets"
        " WHERE move_id=?", (move_id,)).fetchone()


def test_the_relinked_after_all_answer_clears_the_flag(conn):
    move_id = _move(conn)
    assert dbmod.mark_file_move_applied(
        conn, move_id, "ed", "LAP", True, "moved; Resolve not relinked (not open)",
        NOW, relink_pending=True)
    first_applied = _target(conn, move_id)["applied_at"]
    later = "2026-09-26T09:00:00+00:00"
    assert dbmod.mark_file_move_applied(
        conn, move_id, "ed", "LAP", True, "moved; relinked 1 clip", later)
    row = _target(conn, move_id)
    assert row["relink_pending"] == 0
    assert row["detail"] == "moved; relinked 1 clip"
    assert row["applied_at"] == first_applied     # the answer's time is the move's
    # a repeat is a no-op, not a second change
    assert not dbmod.mark_file_move_applied(
        conn, move_id, "ed", "LAP", True, "moved; relinked 1 clip", later)


def test_a_late_answer_cannot_rewrite_a_terminal_failure(conn):
    move_id = _move(conn)
    dbmod.mark_file_move_applied(conn, move_id, "ed", "LAP", False, "blocked", NOW,
                                 state=dbmod.FILE_MOVE_TARGET_BLOCKED)
    assert not dbmod.mark_file_move_applied(conn, move_id, "ed", "LAP", True, "ok", NOW)
    row = _target(conn, move_id)
    assert row["ok"] == 0 and row["detail"] == "blocked"


def test_a_repeated_relink_pending_answer_changes_nothing(conn):
    move_id = _move(conn)
    dbmod.mark_file_move_applied(conn, move_id, "ed", "LAP", True, "first", NOW,
                                 relink_pending=True)
    assert not dbmod.mark_file_move_applied(conn, move_id, "ed", "LAP", True, "again",
                                            NOW, relink_pending=True)
    assert _target(conn, move_id)["detail"] == "first"


# ------------------------------------------------------------ logic-plans-1

def _bucket_person(conn):
    for slug in ("pa", "pb"):
        dbmod.upsert_project(conn, slug, slug.upper(), f"2026/{slug}", NOW)
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    # ticked before any companion reported: the unassigned bucket
    dbmod.add_selection(conn, "ed", "pb", created_by="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "DESK", NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.add_selection(conn, "ed", "pa", created_by="admin", now=NOW, machine="DESK")
    conn.commit()


def _slugs(conn, machine):
    return sorted(r["slug"] for r in dbmod.selections_for_machine(conn, "ed", machine))


def test_unticking_the_last_inherited_project_really_removes_it(conn):
    _bucket_person(conn)
    assert _slugs(conn, "LAP") == ["pb"] and _slugs(conn, "DESK") == ["pa", "pb"]
    assert dbmod.remove_selection(conn, "ed", "pb", machine="LAP")
    assert _slugs(conn, "LAP") == []
    # ...and the other computer's plan is untouched
    assert _slugs(conn, "DESK") == ["pa", "pb"]
    plans = dbmod.fetch_machine_selections(conn)
    assert plans.get("pb") == [("ed", "DESK")]


def test_the_bucket_drain_keeps_another_inheriting_computer_whole(conn):
    for slug in ("pb", "pc"):
        dbmod.upsert_project(conn, slug, slug.upper(), f"2026/{slug}", NOW)
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.add_selection(conn, "ed", "pb", created_by="admin", now=NOW)
    dbmod.add_selection(conn, "ed", "pc", created_by="admin", now=NOW)
    for m in ("A", "B"):
        dbmod.upsert_machine(conn, "ed", m, NOW)
    assert dbmod.remove_selection(conn, "ed", "pb", machine="A")
    assert _slugs(conn, "A") == ["pc"]
    assert _slugs(conn, "B") == ["pb", "pc"]


def test_an_unregistered_hostname_does_not_end_the_inheritance(conn):
    _bucket_person(conn)
    dbmod.remove_selection(conn, "ed", "pb", machine="GHOST")
    assert conn.execute(
        "SELECT 1 FROM selections WHERE editor_username='ed' AND machine=''"
        " AND project_slug='pb'").fetchone() is not None


def test_an_untick_of_a_project_the_machine_does_not_inherit_leaves_the_bucket_alone(conn):
    # logic-plans-1 review round: LAP has a plan of its own, so it does not
    # inherit the bucket, and unticking pb there is a no-op. It must not
    # delete the bucket row or pin the other computers.
    for slug in ("pa", "pb"):
        dbmod.upsert_project(conn, slug, slug.upper(), f"2026/{slug}", NOW)
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.upsert_machine(conn, "ed", "DESK", NOW)
    dbmod.add_selection(conn, "ed", "pa", created_by="a", now=NOW, machine="LAP")
    dbmod.add_selection(conn, "ed", "pb", created_by="a", now=NOW)   # the bucket
    conn.commit()
    assert dbmod.remove_selection(conn, "ed", "pb", machine="LAP") is False
    assert conn.execute(
        "SELECT 1 FROM selections WHERE editor_username='ed' AND machine=''"
        " AND project_slug='pb'").fetchone() is not None
    # DESK still inherits (no own row was written for it)
    assert conn.execute(
        "SELECT COUNT(*) FROM selections WHERE editor_username='ed'"
        " AND machine='DESK'").fetchone()[0] == 0
    assert _slugs(conn, "DESK") == ["pb"]
    assert _slugs(conn, "LAP") == ["pa"]


def test_an_inherited_placement_is_snapshotted_under_the_machines_name(conn):
    _bucket_person(conn)
    assert dbmod.selection_placements(conn, "ed", "pb", machine="LAP") == [
        {"machine": "LAP", "mode": "full"}]
    # A machine with its own plan that lacks the project holds nothing.
    assert dbmod.selection_placements(conn, "ed", "pb", machine="DESK") == [
        {"machine": "DESK", "mode": "full"}]   # DESK was materialised by pa's tick
    dbmod.remove_selection(conn, "ed", "pb", machine="DESK")
    assert dbmod.selection_placements(conn, "ed", "pb", machine="DESK") == []
    # A wired machine inherits nothing, so it holds nothing.
    dbmod.upsert_machine(conn, "ed", "RIG", NOW)
    dbmod.upsert_machine_state(conn, "ed", "RIG", None, NOW, mode="base")
    assert ("ed", "RIG") in dbmod.base_machines(conn)
    assert dbmod.selection_placements(conn, "ed", "pb", machine="RIG") == []
    # ...while an ordinary registered newcomer does inherit it.
    dbmod.upsert_machine(conn, "ed", "NEW", NOW)
    assert dbmod.selection_placements(conn, "ed", "pb", machine="NEW") == [
        {"machine": "NEW", "mode": "full"}]


def test_an_untick_of_an_inherited_project_is_recorded_and_undoable(tmp_path):
    from fastapi.testclient import TestClient

    from ccsync_dashboard import auth
    from ccsync_dashboard.app import create_app
    from ccsync_dashboard.settings import Settings

    secret, token = "test-secret", "companion-token"
    db_path = tmp_path / "undo.db"
    app = create_app(Settings(db_path=str(db_path), session_secret=secret,
                              report_token=token, admin_users=frozenset({"owen"})))
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        for slug in ("pa", "pb"):
            dbmod.upsert_project(conn, slug, slug.upper(), f"/data/{slug}", now)
        dbmod.add_selection(conn, "ed", "pa", created_by="owen", now=now)
        dbmod.add_selection(conn, "ed", "pb", created_by="owen", now=now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(secret, "owen"))
        for machine, mid in (("LAP", "mid-1"), ("DESK", "mid-2")):
            resp = client.post("/api/v1/report", json={
                "editor_name": "ed", "machine": machine, "machine_id": mid,
                "reported_at": "2026-09-25T10:00:00+00:00", "lanes": []},
                headers={"X-CCSync-Token": token,
                         "X-CCSync-Identity": auth.make_identity_token(secret, "ed")})
            assert resp.status_code == 200, resp.text
        assert _slugs(conn, "LAP") == ["pa", "pb"]

        assert client.delete("/api/v1/selection/ed/pb?machine=LAP").json()["changed"] is True
        assert _slugs(conn, "LAP") == ["pa"]
        assert _slugs(conn, "DESK") == ["pa", "pb"]
        rows = dbmod.fetch_audit(conn, actions=(dbmod.AUDIT_UNTICK,))
        assert rows, "an untick of an inherited project wrote no audit row"
        assert rows[0]["detail"]["before"] == [{"machine": "LAP", "mode": "full"}]
        assert rows[0]["detail"]["after"] == []

        assert client.post(f"/partials/plan-changes/{rows[0]['id']}/undo").status_code == 200
        assert _slugs(conn, "LAP") == ["pa", "pb"]
        assert _slugs(conn, "DESK") == ["pa", "pb"]
        conn.close()


# ------------------------------------------------------------ logic-plans-4

def test_a_move_out_of_a_borrowed_folder_reaches_the_borrower(conn):
    for slug in ("lender", "borrower", "other"):
        dbmod.upsert_project(conn, slug, slug, f"2026/{slug}", NOW)
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.upsert_machine(conn, "ed", "DESK", NOW)
    dbmod.add_selection(conn, "ed", "borrower", created_by="a", now=NOW, machine="LAP")
    dbmod.add_selection(conn, "ed", "other", created_by="a", now=NOW, machine="DESK")
    dbmod.replace_project_links(conn, "borrower", [{
        "declared_path": "Projects/2026/lender/Shared B-roll",
        "lender_slug": "lender", "sub_rel": "Shared B-roll",
        "status": "ok", "detail": ""}], NOW)
    conn.commit()
    got = dbmod.file_move_target_machines(conn, "lender", "Shared B-roll/drone_04.mov")
    assert ("ed", "LAP") in got and ("ed", "DESK") not in got
    # the shared folder itself, or a folder above it, moving
    assert ("ed", "LAP") in dbmod.file_move_target_machines(conn, "lender", "Shared B-roll")
    # a sibling that merely shares the prefix is not the shared folder
    assert dbmod.file_move_target_machines(
        conn, "lender", "Shared B-roll 2/x.mov") == []
    assert dbmod.file_move_target_machines(conn, "lender", "Selects/x.mov") == []


# -------------------------------------------------------- logic-ytdl-jobs-5

def test_prune_takes_the_operators_cooldown(conn):
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, NOW)
    job = dbmod.create_job(conn, "peaks", {"a": 1}, now=_iso_ago(3600))
    assert dbmod.claim_job(conn, job, "ed", "LAP", now=_iso_ago(3600), lease_seconds=60)
    conn.commit()
    dbmod.prune(conn, NOW, jobs_cooldown_seconds=0)
    until, _reason = dbmod.machine_job_cooldown(conn, "ed", "LAP")
    assert not until or until <= NOW
    assert dbmod.get_job(conn, job)["state"] == dbmod.JOB_QUEUED


def test_prune_default_cooldown_is_unchanged(conn):
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, NOW)
    job = dbmod.create_job(conn, "peaks", {"a": 1}, now=_iso_ago(3600))
    assert dbmod.claim_job(conn, job, "ed", "LAP", now=_iso_ago(3600), lease_seconds=60)
    conn.commit()
    dbmod.prune(conn, NOW)
    until, _reason = dbmod.machine_job_cooldown(conn, "ed", "LAP")
    assert until > NOW


# ================================================================ owed round
# (2026-09-25) items other groups left for db.py.

# ------------------------------------------------------ logic-sync-truth-2

def _originals_fixture(conn, *, held: int, listed: int, on_nas: int):
    """`listed` originals named in the manifest, all of them on the NAS when
    `on_nas >= listed`; `held` is the exact rollup the companion sends."""
    pid = dbmod.upsert_project(conn, "et", "Energy Transition", "2026/ET", NOW)
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.add_selection(conn, "ed", "et", created_by="admin", now=NOW, machine="LAP")
    rows = [(f"o{i:05d}.mov", "original", "mov", 100, 1) for i in range(on_nas)]
    dbmod.replace_nas_media(conn, pid, rows, "sig", 2, NOW, force=True)
    files = [(f"o{i:05d}.mov", "original", 100) for i in range(listed)]
    dbmod.replace_editor_media(conn, "ed", "LAP", "et", files, NOW)
    dbmod.upsert_editor_media_project(
        conn, editor="ed", machine="LAP", slug="et", mode="editor",
        n_originals=held, bytes_originals=100 * held, n_proxies=0,
        bytes_proxies=0, truncated=listed < held, now=NOW)
    conn.commit()


def _up(conn):
    return [q for q in dbmod.fetch_sync_backlog(conn) if q["direction"] == "up"]


def test_a_capped_originals_list_is_an_uncertain_upload_even_when_the_diff_is_empty(conn):
    # 2500 originals on the laptop, 2000 listed, every listed one on the NAS.
    # HEAD: no up row at all, so "Safe to close" had nothing to hold it back.
    _originals_fixture(conn, held=2500, listed=2000, on_nas=2000)
    up = _up(conn)
    assert len(up) == 1
    assert up[0]["uncertain"] is True
    assert up[0]["n_files"] == 0 and up[0]["files"] == []
    assert up[0]["machine"] == "LAP" and up[0]["slug"] == "et"


def test_a_capped_originals_list_with_a_real_diff_is_flagged_uncertain(conn):
    _originals_fixture(conn, held=2500, listed=2000, on_nas=1990)
    up = _up(conn)
    assert len(up) == 1 and up[0]["n_files"] == 10 and up[0]["uncertain"] is True


def test_an_uncapped_originals_list_is_certain_and_empty_when_all_uploaded(conn):
    _originals_fixture(conn, held=30, listed=30, on_nas=30)
    assert _up(conn) == []
    _originals_fixture(conn, held=30, listed=30, on_nas=20)
    up = _up(conn)
    assert len(up) == 1 and up[0]["uncertain"] is False and up[0]["n_files"] == 10


def test_a_capped_proxy_list_alone_does_not_make_the_upload_uncertain(conn):
    # `truncated` is one flag for both kinds; originals fully listed -> certain.
    _backlog_fixture(conn, nas_proxies=2500, held_proxies=2500, listed_proxies=2000)
    assert _up(conn) == []


def test_every_down_row_carries_uncertain_false(conn):
    _backlog_fixture(conn, nas_proxies=30, held_proxies=20, listed_proxies=20)
    down = [q for q in dbmod.fetch_sync_backlog(conn) if q["direction"] == "down"]
    assert down and all(q["uncertain"] is False for q in down)


# --------------------------------------------------------------- ui-copy-2

def test_no_notice_links_to_the_fleet_path_that_404s(conn):
    for kind, spec in dbmod.NOTICE_KINDS.items():
        href = spec.get("href")
        if callable(href):
            for subject in ("", "not a slug!", "a/b -> ", "ed/LAP -> ff5-lab"):
                assert not href(subject).startswith("/fleet"), (kind, subject)
        elif href:
            # HEAD: nine kinds said "/fleet", eight "/fleet#fleet-diagnostics".
            assert not str(href).startswith("/fleet"), kind


def test_the_collector_kinds_point_at_the_collector_panel():
    for kind in ("collector_cycle_failed", "collector_watchdog_restart",
                 "syncthing_unreachable", "db_busy", "slow_write", "slow_poll"):
        assert dbmod.notice_href(kind)[0] == "/#fleet-collector", kind
    for kind in ("server_error", "feature_not_mounted"):
        assert dbmod.notice_href(kind)[0] == "/admin/health", kind
    assert dbmod.notice_href("machine_forgotten")[0] == "/"
    assert dbmod.notice_href("enforce_refusal", "share removals")[0] == "/"
    assert dbmod.notice_href("plan_without_share", "ed/LAP -> ")[0] == "/"


def test_every_notice_href_is_a_page_the_dashboard_serves(tmp_path):
    from fastapi.testclient import TestClient

    from ccsync_dashboard import auth
    from ccsync_dashboard.app import create_app
    from ccsync_dashboard.settings import Settings

    secret = "test-secret-value-w2-d-db-owed-123456"
    settings = Settings(db_path=str(tmp_path / "hrefs.db"), session_secret=secret,
                        report_token="companion-token-w2-d-db-owed-1234567",
                        admin_users=frozenset({"owen"}))
    hrefs = set()
    for spec in dbmod.NOTICE_KINDS.values():
        href = spec.get("href")
        if callable(href):
            hrefs.add(href(""))
        elif href:
            hrefs.add(str(href))
    with TestClient(create_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(secret, "owen"))
        for href in sorted(hrefs):
            path = href.split("#", 1)[0]
            if path.startswith(("/broll", "/admin/diagnostics/crash-reports")):
                continue    # a mounted app / a download: not a page of this test app
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code in (200, 302, 303, 307), (href, resp.status_code)


# ------------------------------------------------------- ui-dash-admin-12

def _stale_keep_halted(conn, monkeypatch=None):
    dbmod.set_fleet_halt(conn, True, "moving the NAS", "owen",
                         now="2026-09-25T08:14:03.512345+00:00", hours=1)
    conn.commit()
    try:
        dbmod.set_fleet_halt(conn, True, "", "owen",
                             now="2026-09-25T12:00:00+00:00", extend=True)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("a stale KEEP HALTED was accepted")


def test_the_stale_keep_halted_refusal_reads_as_a_time(conn):
    msg = _stale_keep_halted(conn)
    # HEAD: "...started again at 2026-09-25T09:14:03.512345+00:00. ..."
    assert "T09:14" not in msg and "+00:00" not in msg
    assert "2026-09-25 09:14 UTC" in msg
    assert "—" not in msg and " -- " not in msg


def test_the_stale_keep_halted_refusal_uses_the_site_zone(conn, monkeypatch):
    from ccsync_dashboard import alerts
    monkeypatch.setattr(alerts, "_zone_or_utc", lambda _c: (
        dbmod.dt.timezone(dbmod.dt.timedelta(hours=8)), "Asia/Taipei"))
    assert "2026-09-25 17:14 Asia/Taipei" in _stale_keep_halted(conn)


def test_a_broken_zone_lookup_still_gives_the_refusal(conn, monkeypatch):
    from ccsync_dashboard import alerts

    def boom(_c):
        raise RuntimeError("no tzdata")
    monkeypatch.setattr(alerts, "_zone_or_utc", boom)
    assert "2026-09-25 09:14 UTC" in _stale_keep_halted(conn)
    assert dbmod._halt_when_text(conn, "not a time") == "not a time"
