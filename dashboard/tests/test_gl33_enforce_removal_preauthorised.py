"""GL-33 / CR-376 (prelaunch review 2026-10-07, PRAC-12).

The blast-radius brake counted every share removal alike, so suspending one
editor (6 projects x 2 computers) froze every untick fleet-wide until a
container env var changed. Removals that trace to an audited admin act are
now pre-authorised, an admin can approve the refused set by name, and the
limit can scale with the fleet. The B16 shape (removals with no admin act
behind them) is still refused: the existing test_enforce.py refusal tests
pin that and are untouched.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR_ID, FakeSyncthing
from test_enforce import SLUG, _add_second_folder, folder_devices


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


@pytest.fixture
def collector(fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k",
                        enforce_max_share_removals=3)
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def _five_shared(conn, fake, collector):
    slugs = [SLUG] + [_add_second_folder(fake, f"2026-ff5-p{i}") for i in range(4)]
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    for slug in slugs:
        dbmod.add_selection(conn, "jsmith", slug, "admin", now)
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    assert all(EDITOR_ID in {d["deviceID"] for f in fake.state["folders"]
                             if f["id"] == s for d in f["devices"]} for s in slugs)
    return slugs


def _has_editor(fake, slug):
    return EDITOR_ID in {d["deviceID"] for f in fake.state["folders"]
                         if f["id"] == slug for d in f["devices"]}


def _untick_unaudited(conn, slugs):
    for slug in slugs:
        dbmod.remove_selection(conn, "jsmith", slug)
    conn.commit()


def test_suspending_one_editor_is_not_frozen_by_the_brake(conn, fake, collector):
    slugs = _five_shared(conn, fake, collector)
    assert dbmod.suspend_editor(conn, "jsmith", by="owen", reason="left")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])               # 5 removals > limit 3
    assert not any(_has_editor(fake, s) for s in slugs)
    assert dbmod.collector_alarms(conn)["enforce_refusal"] is None


def test_archived_projects_are_removed_past_the_limit(conn, fake, collector):
    slugs = _five_shared(conn, fake, collector)
    for slug in slugs:
        assert dbmod.archive_project(conn, slug, by="owen")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert not any(_has_editor(fake, s) for s in slugs)
    assert dbmod.collector_alarms(conn)["enforce_refusal"] is None


def test_audited_untick_is_authorised_but_a_bare_one_is_not(conn, fake, collector):
    slugs = _five_shared(conn, fake, collector)
    _untick_unaudited(conn, slugs)
    collector.run_cycle(conn, ["enforce"])
    assert all(_has_editor(fake, s) for s in slugs)      # B16 shape: still refused
    assert dbmod.collector_alarms(conn)["enforce_refusal"]["count"] >= 4

    for slug in slugs:
        dbmod.audit(conn, "owen", dbmod.AUDIT_UNTICK, slug,
                    {"slug": slug, "editor": "jsmith", "machine": ""})
    conn.commit()
    machine_dev = {("jsmith", ""): EDITOR_ID}
    assert set(dbmod.recent_plan_change_devices(
        conn, dbmod.utcnow_iso(), machine_dev, window_seconds=3600)) == set(slugs)


def test_a_mixed_pass_applies_authorised_and_holds_the_rest(conn, fake, collector):
    """4 unticks nobody audited + 1 archived project: the archived one goes,
    the four stay held (4 > limit 3), and the refusal counts only the four."""
    slugs = _five_shared(conn, fake, collector)
    _untick_unaudited(conn, slugs)
    dbmod.archive_project(conn, slugs[0], by="owen")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert not _has_editor(fake, slugs[0])
    assert all(_has_editor(fake, s) for s in slugs[1:])
    assert dbmod.collector_alarms(conn)["enforce_refusal"]["count"] == 4


def test_approve_these_removals_applies_exactly_the_refused_set(conn, fake, collector):
    slugs = _five_shared(conn, fake, collector)
    _untick_unaudited(conn, slugs)
    collector.run_cycle(conn, ["enforce"])
    assert all(_has_editor(fake, s) for s in slugs)

    with pytest.raises(ValueError, match="the list changed"):
        dbmod.approve_enforce_removals(conn, dbmod.utcnow_iso(), "owen", 4)
    rec = dbmod.approve_enforce_removals(conn, dbmod.utcnow_iso(), "owen", 5)
    conn.commit()
    assert len(rec["pairs"]) == 5
    assert any(a["action"] == dbmod.AUDIT_ENFORCE_APPROVE
               for a in dbmod.fetch_audit(conn))

    collector.run_cycle(conn, ["enforce"])
    assert not any(_has_editor(fake, s) for s in slugs)
    assert dbmod.collector_alarms(conn)["enforce_refusal"] is None
    # one application of one refusal: the approval is spent
    assert dbmod.approved_enforce_pairs(conn, dbmod.utcnow_iso()) == set()


def test_an_approval_expires(conn, fake, collector):
    slugs = _five_shared(conn, fake, collector)
    _untick_unaudited(conn, slugs)
    collector.run_cycle(conn, ["enforce"])
    dbmod.approve_enforce_removals(conn, dbmod.utcnow_iso(), "owen", 5)
    later = dbmod._iso_minus(dbmod.utcnow_iso(), -(dbmod.ENFORCE_APPROVAL_TTL_SECONDS + 5))
    assert dbmod.approved_enforce_pairs(conn, later) == set()


def test_nothing_to_approve_is_a_sentence_not_a_crash(conn):
    with pytest.raises(ValueError, match="no share removals"):
        dbmod.approve_enforce_removals(conn, dbmod.utcnow_iso(), "owen", 1)


def test_the_limit_scales_with_fleet_size_when_the_site_says_so(conn, fake, collector):
    slugs = _five_shared(conn, fake, collector)
    _untick_unaudited(conn, slugs)
    dbmod.set_enforce_removals_per_computer(conn, 10, "owen")   # 1 mapped computer
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert not any(_has_editor(fake, s) for s in slugs)
    assert any(a["action"] == dbmod.AUDIT_ENFORCE_ALLOWANCE
               for a in dbmod.fetch_audit(conn))


def test_allowance_default_is_the_flat_limit_and_is_bounded(conn):
    assert dbmod.enforce_removals_per_computer(conn) == 0
    with pytest.raises(ValueError):
        dbmod.set_enforce_removals_per_computer(conn, 101, "owen")
    with pytest.raises(ValueError):
        dbmod.set_enforce_removals_per_computer(conn, -1, "owen")


@pytest.fixture
def web(tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret="test-secret-not-a-real-one",
                        admin_users=frozenset({"owen"}),
                        projects_dir=str(tmp_path), report_token="companion-token-not-a-real-one")
    app = create_app(settings)
    with TestClient(app) as client:
        c = dbmod.connect(settings.db_path)
        yield client, c
        c.close()


def test_the_routes_are_admin_only_and_approve_the_standing_refusal(web):
    client, c = web
    assert client.post("/api/v1/enforce/approve-removals", json={"count": 1}).status_code in (401, 403)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie("test-secret-not-a-real-one", "owen"))
    assert client.post("/api/v1/enforce/approve-removals", json={"count": 1}).status_code == 409
    dbmod.record_enforce_refusal(c, dbmod.utcnow_iso(), [("a", "D1"), ("b", "D1")], 3)
    c.commit()
    assert client.post("/api/v1/enforce/approve-removals", json={"count": 3}).status_code == 409
    ok = client.post("/api/v1/enforce/approve-removals", json={"count": 2})
    assert ok.status_code == 200 and ok.json()["approved"] == 2
    assert client.post("/api/v1/enforce/allowance", json={"per_computer": 6}).json()["per_computer"] == 6
    assert client.post("/api/v1/enforce/allowance", json={"per_computer": 500}).status_code == 422


def test_audited_unticks_on_a_registered_computer_pass_the_brake(conn, fake, collector):
    """The collector path of the audited-untick trace: a registered computer,
    five audited unticks, one cycle, no refusal."""
    slugs = [SLUG] + [_add_second_folder(fake, f"2026-ff5-p{i}") for i in range(4)]
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "jsmith", "PC1", now, syncthing_device_id=EDITOR_ID)
    for slug in slugs:
        dbmod.add_selection(conn, "jsmith", slug, "admin", now, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    assert all(_has_editor(fake, s) for s in slugs)
    for slug in slugs:
        dbmod.remove_selection(conn, "jsmith", slug)
        dbmod.audit(conn, "owen", dbmod.AUDIT_UNTICK, slug,
                    {"slug": slug, "editor": "jsmith", "machine": "PC1"})
    conn.commit()
    # inside the 60 s undo freeze the share is kept; step past it by
    # back-dating the audit rows, as the real cycle would see them a minute on.
    conn.execute("UPDATE fleet_audit SET at=?", (dbmod._iso_minus(now, 600),))
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert not any(_has_editor(fake, s) for s in slugs)
    assert dbmod.collector_alarms(conn)["enforce_refusal"] is None


def _registered_five(conn, fake, collector):
    slugs = [SLUG] + [_add_second_folder(fake, f"2026-ff5-p{i}") for i in range(4)]
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "jsmith", "PC1", now, syncthing_device_id=EDITOR_ID)
    for slug in slugs:
        dbmod.add_selection(conn, "jsmith", slug, "admin", now, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    assert all(_has_editor(fake, s) for s in slugs)
    return slugs


def _plan_audit(conn, action, slug, **extra):
    return dbmod.audit(conn, "owen", action, slug,
                       {"slug": slug, "editor": "jsmith", "machine": "PC1", **extra})


@pytest.mark.parametrize("how", ["retick", "undo"])
def test_a_superseded_untick_does_not_authorise_a_later_bare_removal(
        conn, fake, collector, how):
    """CR-376 overseer defect 1: untick then re-tick (or untick then UNDO)
    leaves the plan ticked; a later unaudited removal is the B16 shape and
    must still be counted and refused."""
    slugs = _registered_five(conn, fake, collector)
    for slug in slugs:
        untick_id = _plan_audit(conn, dbmod.AUDIT_UNTICK, slug)
        if how == "retick":
            _plan_audit(conn, dbmod.AUDIT_TICK, slug)
        else:
            dbmod.audit(conn, "owen", dbmod.AUDIT_PLAN_UNDO, slug,
                        {"undid": untick_id, "editor": "jsmith", "slug": slug})
    conn.commit()
    later = dbmod._iso_minus(dbmod.utcnow_iso(), -3600)
    collector.now_fn = lambda: later
    for slug in slugs:                                   # bare, unaudited
        dbmod.remove_selection(conn, "jsmith", slug)
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert all(_has_editor(fake, s) for s in slugs)
    assert dbmod.collector_alarms(conn)["enforce_refusal"]["count"] >= 4


def test_standing_untick_needs_the_plan_to_still_lack_the_pair(conn):
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "jsmith", "PC1", now, syncthing_device_id=EDITOR_ID)
    _plan_audit(conn, dbmod.AUDIT_UNTICK, "p1")
    dbmod.add_selection(conn, "jsmith", "p2", "admin", now, machine="PC1")
    _plan_audit(conn, dbmod.AUDIT_UNTICK, "p2")          # plan still has p2
    conn.commit()
    got = dbmod.standing_untick_devices(conn, now, {("jsmith", "PC1"): EDITOR_ID})
    assert got == {"p1": frozenset({EDITOR_ID})}


def test_settings_page_carries_the_allowance_and_its_route_saves_it(web):
    client, c = web
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie("test-secret-not-a-real-one", "owen"))
    page = client.get("/admin/settings").text
    assert 'hx-post="/partials/admin/enforce/allowance"' in page
    assert 'name="per_computer"' in page
    ok = client.post("/partials/admin/enforce/allowance", data={"per_computer": "4"})
    assert ok.status_code == 200 and "4 share removals" in ok.text
    assert dbmod.enforce_removals_per_computer(c) == 4
    assert client.post("/partials/admin/enforce/allowance",
                       data={"per_computer": "900"}).status_code == 422
    assert "—" not in ok.text


# --- round 2 (CR-376, 2026-10-07) ---------------------------------------

def _later(conn, collector, secs=600):
    collector.now_fn = lambda: dbmod._iso_minus(dbmod.utcnow_iso(), -secs)


def test_approval_is_spent_in_a_refused_cycle_and_a_retick_never_revives_it(
        conn, fake, collector):
    slugs = _registered_five(conn, fake, collector)
    extra = [_add_second_folder(fake, f"2026-ff5-x{i}") for i in range(4)]
    collector.run_cycle(conn, ["config", "enforce"])
    now = dbmod.utcnow_iso()
    for s in extra:
        dbmod.add_selection(conn, "jsmith", s, "admin", now, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["config", "enforce"])
    targets = slugs[1:]
    for s in targets:
        dbmod.remove_selection(conn, "jsmith", s, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    n = dbmod.collector_alarms(conn)["enforce_refusal"]["count"]
    dbmod.approve_enforce_removals(conn, dbmod.utcnow_iso(), "owen", n)
    conn.commit()
    for s in extra:                       # a second, bare set refuses the cycle again
        dbmod.remove_selection(conn, "jsmith", s, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert not any(_has_editor(fake, s) for s in targets)       # approved set applied
    assert all(_has_editor(fake, s) for s in extra)             # bare set held
    assert dbmod.approved_enforce_pairs(conn, dbmod.utcnow_iso()) == set()
    now = dbmod.utcnow_iso()
    for s in targets:
        dbmod.add_selection(conn, "jsmith", s, "admin", now, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    for s in targets:                     # bare removal after a re-tick: counted
        dbmod.remove_selection(conn, "jsmith", s, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert all(_has_editor(fake, s) for s in targets)


def test_spend_drops_a_pair_the_plan_holds_again(conn):
    now = dbmod.utcnow_iso()
    dbmod.meta_set_json(conn, dbmod.META_ENFORCE_APPROVAL, {
        "at": now, "by": "owen", "expires": dbmod._iso_minus(now, -3600),
        "pairs": [{"folder": "a", "device": "D1"}, {"folder": "b", "device": "D1"}]})
    dbmod.spend_enforce_approval(conn, [("a", {"D1"}, {"D1"}), ("b", set(), {"D1"})])
    assert dbmod.approved_enforce_pairs(conn, now) == set()
    dbmod.meta_set_json(conn, dbmod.META_ENFORCE_APPROVAL, {
        "at": now, "by": "owen", "expires": dbmod._iso_minus(now, -3600),
        "pairs": [{"folder": "a", "device": "D1"}, {"folder": "c", "device": "D2"}]})
    dbmod.spend_enforce_approval(conn, [("a", {"D1"}, {"D1"})])
    assert dbmod.approved_enforce_pairs(conn, now) == set()  # c converged (absent from plans): spent too


def _switch_to_upload_only(conn, slug):
    before = dbmod.selection_placements(conn, "jsmith", slug, machine="PC1")
    dbmod.add_selection(conn, "jsmith", slug, "owen", dbmod.utcnow_iso(), machine="PC1",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    after = dbmod.selection_placements(conn, "jsmith", slug, machine="PC1")
    assert before != after
    dbmod.audit(conn, "owen", dbmod.AUDIT_TICK, slug, {
        "editor": "jsmith", "slug": slug, "machine": "PC1", "scope": "machine",
        "before": before, "after": after})


def test_an_audited_switch_to_upload_only_is_not_braked_but_a_bare_removal_is(
        conn, fake, collector):
    slugs = _registered_five(conn, fake, collector)
    for s in slugs:                       # 5 > limit 3
        _switch_to_upload_only(conn, s)
    conn.commit()
    _later(conn, collector)
    collector.run_cycle(conn, ["enforce"])
    assert not any(_has_editor(fake, s) for s in slugs)
    assert not dbmod.collector_alarms(conn)["enforce_refusal"]
    # switched back to full: the audit row no longer explains a removal
    now = dbmod.utcnow_iso()
    got = dbmod.standing_untick_devices(conn, now, {("jsmith", "PC1"): EDITOR_ID})
    assert set(got) == set(slugs)
    for s in slugs:
        dbmod.add_selection(conn, "jsmith", s, "owen", now, machine="PC1",
                            sync_mode=dbmod.SYNC_MODE_FULL)
    conn.commit()
    assert dbmod.standing_untick_devices(conn, now, {("jsmith", "PC1"): EDITOR_ID}) == {}


def test_refusal_notice_no_longer_says_none_were_applied():
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "src" / "ccsync_dashboard" / "notices.py"
    text = src.read_text(encoding="utf-8")
    assert "so NONE of them were" not in text and "Every untick made" not in text


# CR-376 round 2b (GL-33, 2026-10-07)
def test_a_retick_before_the_applying_cycle_spends_the_approval_even_when_converged(conn, fake, collector):
    slugs = _registered_five(conn, fake, collector)
    t = slugs[1:]
    for s in t:
        dbmod.remove_selection(conn, "jsmith", s, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert dbmod.collector_alarms(conn)["enforce_refusal"]["count"] == 4
    dbmod.approve_enforce_removals(conn, dbmod.utcnow_iso(), "owen", 4)
    conn.commit()
    now = dbmod.utcnow_iso()
    for s in t:   # admin re-ticks before the approval is applied
        dbmod.add_selection(conn, "jsmith", s, "admin", now, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    live = dbmod.approved_enforce_pairs(conn, dbmod.utcnow_iso())
    assert not live, "a converged folder must not keep an approval alive"
    for s in t:   # bare, unaudited removal later in the hour
        dbmod.remove_selection(conn, "jsmith", s, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    held = [s for s in t if _has_editor(fake, s)]
    assert len(held) == 4, "bare 4 > limit 3 removal went through on a re-ticked approval"


def test_upload_only_then_full_then_a_bare_removal_is_held_and_counted(conn, fake, collector):
    slugs = _registered_five(conn, fake, collector)
    for s in slugs:
        _switch_to_upload_only(conn, s)
    conn.commit()
    _later(conn, collector)
    collector.run_cycle(conn, ["enforce"])
    assert not any(_has_editor(fake, s) for s in slugs)
    now = dbmod.utcnow_iso()
    for s in slugs:   # audited switch back to full
        before = dbmod.selection_placements(conn, "jsmith", s, machine="PC1")
        dbmod.add_selection(conn, "jsmith", s, "owen", now, machine="PC1",
                            sync_mode=dbmod.SYNC_MODE_FULL)
        after = dbmod.selection_placements(conn, "jsmith", s, machine="PC1")
        dbmod.audit(conn, "owen", dbmod.AUDIT_TICK, s, {"editor": "jsmith", "slug": s,
                    "machine": "PC1", "scope": "machine", "before": before, "after": after})
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert all(_has_editor(fake, s) for s in slugs)
    for s in slugs:
        dbmod.remove_selection(conn, "jsmith", s, machine="PC1")
    conn.commit()
    collector.run_cycle(conn, ["enforce"])
    assert all(_has_editor(fake, s) for s in slugs)
    assert dbmod.collector_alarms(conn)["enforce_refusal"]["count"] >= 4
