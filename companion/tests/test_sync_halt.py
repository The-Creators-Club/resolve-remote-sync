"""The "stop all sync" halt, the fleet halt command, and the caught-up gate
on "Remove from this machine" (COMMERCIAL_READINESS.md item 9, 2026-08-17).

Nothing here touches a real Syncthing, a real rclone or Tk: the halt's lane C
half goes through a fake SyncthingAdmin, and the removal gate's lane A half
through a fake lane.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ccsync_companion.app import CompanionApp
from ccsync_companion.sync import lane_guard


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _app(tmp_path, **overrides) -> CompanionApp:
    return CompanionApp(_cfg(tmp_path, **overrides))


class _FakeAdmin:
    def __init__(self):
        self.paused: list[tuple[str, bool]] = []
        self.completion: dict = {"completion": 100.0, "needBytes": 0}
        self.status: dict = {"needTotalItems": 0, "state": "idle"}

    def set_folder_paused(self, folder_id, paused):
        self.paused.append((folder_id, paused))

    def folder_completion(self, folder_id):
        return self.completion

    def folder_status(self, folder_id):
        return self.status

    def remove_folder(self, folder_id):
        pass


class _FakeSequencer:
    def __init__(self, slugs):
        self._slugs = slugs
        self.triggered = 0

    def expected_folder_slugs(self):
        return list(self._slugs)

    def stop(self):
        pass

    def trigger_pass_now(self):
        self.triggered += 1


class _HaltAwareSequencer(_FakeSequencer):
    """A sequencer of the shape CR-48 landed: it can name the shared asset
    libraries as well as the selection, and it owns the filtered release."""

    def __init__(self, slugs, shared):
        super().__init__(slugs)
        self._shared = list(shared)
        self.released_for_halt = 0

    def halt_folder_ids(self):
        return list(self._slugs) + list(self._shared)

    def release_for_halt(self):
        self.released_for_halt += 1


# -- the halt ---------------------------------------------------------------


def test_halt_stops_the_rclone_lanes_and_pauses_every_lane_c_folder(tmp_path):
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer(["proj-a", "proj-b"])
    ok, _msg = app.halt_all_sync("the NAS is being rebuilt")
    assert ok
    assert app.halt.active
    # Pause deliberately leaves lane C alone; a HALT must not.
    assert app.syncthing_admin.paused == [("proj-a", True), ("proj-b", True)]
    assert app._lanes_started is False


def test_a_halt_survives_a_restart_and_keeps_the_lanes_down(tmp_path):
    app = _app(tmp_path, sync_enabled=True)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer([])
    app.halt_all_sync("stopped from the tray on this machine")

    revived = _app(tmp_path, sync_enabled=True)
    assert revived.halt.active
    revived._start_lanes()
    assert revived._lanes_started is False, "a halt an editor can restart past is not a halt"
    assert "STOPPED" in revived.lanes[0].status().detail


def test_release_unpauses_lane_c(tmp_path):
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer(["proj-a"])
    app.halt_all_sync("x")
    app.syncthing_admin.paused.clear()
    ok, _ = app.release_halt(by="tray")
    assert ok
    assert app.syncthing_admin.paused == [("proj-a", False)]
    assert not app.halt.active


def test_an_editor_cannot_release_a_fleet_halt(tmp_path):
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer([])
    app.halt_all_sync("admin stopped everything", lane_guard.HALT_SCOPE_FLEET)
    ok, message = app.release_halt(by="tray")
    assert ok is False
    # The load-bearing half (wave 4 vocabulary, 2026-09-04): a fleet halt is
    # STOPPED BY YOUR ADMIN, and the refusal has to say they are the only one
    # who can start it again - an editor who reads only "no" goes looking for
    # a switch that is not theirs. "admin stopped everything" after the colon
    # is the halting admin's OWN note, interpolated; not a duplicate.
    assert "your admin stopped syncing for the whole fleet" in message
    assert "Only they can start it again." in message
    assert app.halt.active


def test_the_report_reply_engages_and_releases_the_fleet_halt(tmp_path):
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer(["proj-a"])

    app._on_report_response({"ok": True, "commands": {
        "halt": {"active": True, "reason": "restoring the pool"}}})
    assert app.halt.active
    assert app.halt.scope == lane_guard.HALT_SCOPE_FLEET
    assert ("proj-a", True) in app.syncthing_admin.paused

    app._on_report_response({"ok": True, "commands": {"halt": {"active": False}}})
    assert not app.halt.active
    assert ("proj-a", False) in app.syncthing_admin.paused


def test_an_older_dashboards_reply_leaves_a_fleet_halt_alone(tmp_path):
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer([])
    app._on_report_response({"ok": True, "commands": {"halt": {"active": True}}})
    app._on_report_response({"ok": True})       # no `commands` key at all
    assert app.halt.active


def test_the_halt_state_reaches_the_report(tmp_path):
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer([])
    app.halt_all_sync("because")
    guard = app.sync_guard()
    assert guard["halt"]["active"] is True
    assert guard["halt"]["reason"] == "because"


def test_a_tripped_breaker_reaches_the_report(tmp_path):
    app = _app(tmp_path)
    app.lane_b_breaker.trip("the NAS listed the tree as EMPTY")
    guard = app.sync_guard()
    assert guard["lane_b_breaker"]["tripped"] is True
    assert "EMPTY" in guard["lane_b_breaker"]["reason"]


def test_resuming_the_breaker_from_the_tray_clears_it(tmp_path):
    app = _app(tmp_path)
    app._managed = True
    app.sequencer = _FakeSequencer([])
    app.lane_b_breaker.trip("boom")
    ok, _msg = app.resume_lane_b()
    assert ok
    assert not app.lane_b_breaker.tripped
    assert app.sequencer.triggered == 1
    assert app.resume_lane_b()[0] is False


# -- CR-48 / CR-67 item 1: the halt reaches the shared asset libraries ------


def test_the_halt_pauses_the_shared_asset_libraries_too(tmp_path):
    """sync-safety-2. The halt walked the project SELECTION, which names no
    shared folder -- so a halt pressed because a bad ingest or a mass rename
    in the B-roll archive was spreading left the archive, the music library
    and the LUTs syncing on every machine in the fleet, while every tray said
    "Nothing is uploading, downloading or sharing"."""
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _HaltAwareSequencer(
        ["proj-a"], ["ccsync-luts", "ccsync-broll-archive", "ccsync-music"])

    app.halt_all_sync("a bad ingest is spreading through the archive")

    assert app.syncthing_admin.paused == [
        ("proj-a", True), ("ccsync-luts", True),
        ("ccsync-broll-archive", True), ("ccsync-music", True),
    ]


def test_a_sequencer_that_cannot_name_them_still_pauses_the_selection(tmp_path):
    """Every seam CR-48 left is behind a getattr on purpose: a companion
    whose sequencer predates halt_folder_ids must halt exactly as it does
    today rather than not at all."""
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer(["proj-a", "proj-b"])

    app.halt_all_sync("x")

    assert app.syncthing_admin.paused == [("proj-a", True), ("proj-b", True)]


def test_release_goes_through_the_sequencers_filtered_unpause(tmp_path):
    """sync-safety-4. The release PATCHed `paused: false` onto every folder
    the halt had touched, which includes a folder deliberately left paused
    because its .stignore never landed -- putting an unfiltered `sendreceive`
    folder online to offer every original and every Proxy/ file."""
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _HaltAwareSequencer(["proj-a"], ["ccsync-luts"])
    app.halt_all_sync("x")
    app.syncthing_admin.paused.clear()

    ok, _msg = app.release_halt(by="tray")

    assert ok
    assert app.sequencer.released_for_halt == 1
    assert app.syncthing_admin.paused == [], \
        "the release must not unpause a folder behind the sequencer's back"


def test_the_fleet_release_takes_the_same_filtered_path(tmp_path):
    """An admin's release must not be the one path that can put a folder
    with no .stignore online (sync-safety-4)."""
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _HaltAwareSequencer(["proj-a"], ["ccsync-luts"])

    app._on_report_response({"ok": True, "commands": {
        "halt": {"active": True, "reason": "restoring the pool"}}})
    assert ("ccsync-luts", True) in app.syncthing_admin.paused
    app.syncthing_admin.paused.clear()

    app._on_report_response({"ok": True, "commands": {"halt": {"active": False}}})

    assert not app.halt.active
    assert app.sequencer.released_for_halt == 1
    assert app.syncthing_admin.paused == []


def test_a_release_the_sequencer_cannot_do_leaves_lane_c_paused(tmp_path):
    """Staying paused is the safe side of this one: a folder nobody released
    syncs nothing, and the next pass sweeps it up."""
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _HaltAwareSequencer(["proj-a"], [])

    def boom():
        raise RuntimeError("syncthing is not answering")

    app.sequencer.release_for_halt = boom
    app.halt_all_sync("x")
    app.syncthing_admin.paused.clear()

    ok, _msg = app.release_halt(by="tray")

    assert ok, "the halt latch itself must still clear"
    assert app.syncthing_admin.paused == []


def test_a_legacy_companion_with_no_sequencer_still_unpauses(tmp_path):
    """The old direct call survives as the no-sequencer fallback, where
    nothing else would ever release the folders at all."""
    app = _app(tmp_path)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = None

    app.halt_all_sync("x")
    ok, _msg = app.release_halt(by="tray")

    assert ok
    # Nothing to name, so nothing to write -- but the path taken is the
    # direct one, not a crash on a missing release_for_halt.
    assert app.syncthing_admin.paused == []


def test_the_sequencer_is_built_knowing_whether_this_machine_is_halted(tmp_path):
    """The other half of sync-safety-2: the once-per-pass shared-folder
    reconcile RELEASES a paused asset library, so without this predicate the
    halt held the libraries down for exactly one sequencer pass."""
    app = _app(tmp_path, dashboard_url="http://dash.example:8480",
               dashboard_token="tok")
    assert app.sequencer is not None
    assert app.sequencer.shared_folders.halted() is False

    app.syncthing_admin = _FakeAdmin()
    app.halt_all_sync("stop touching the files")

    assert app.sequencer.shared_folders.halted() is True


# -- the caught-up gate on "Remove from this machine" -----------------------


class _FakeLaneA:
    def __init__(self, pending):
        self._pending = pending
        self.asked: list[str] = []

    def pending_uploads(self, subpath=None):
        self.asked.append(subpath)
        return self._pending


def _gate_app(tmp_path, pending, admin=None):
    app = _app(tmp_path)
    app._lane_a = _FakeLaneA(pending)
    app.syncthing_admin = admin
    app.removable_projects = lambda: [
        {"slug": "p1", "rel": "2026/CCT/Website Highlights"}]
    return app


def test_the_gate_is_open_when_everything_has_reached_the_server(tmp_path):
    admin = _FakeAdmin()
    app = _gate_app(tmp_path, {"count": 0, "samples": []}, admin)
    blockers = app.removal_blockers("p1")
    assert blockers["blocked"] is False
    assert app._lane_a.asked == ["Projects/2026/CCT/Website Highlights"]


def test_pending_uploads_block_the_removal_and_are_named(tmp_path):
    admin = _FakeAdmin()
    app = _gate_app(tmp_path, {"count": 2, "samples": ["A001.braw"]}, admin)
    blockers = app.removal_blockers("p1")
    assert blockers["blocked"] is True
    assert blockers["pending_uploads"] == 2
    assert any("A001.braw" in r for r in blockers["reasons"])


def test_a_probe_that_cannot_answer_blocks_the_removal(tmp_path):
    # FAILS CLOSED, unlike every other guard in app.py: "I could not tell"
    # must not cost footage that exists nowhere else.
    app = _gate_app(tmp_path, None, _FakeAdmin())
    blockers = app.removal_blockers("p1")
    assert blockers["blocked"] is True
    assert blockers["unknown"] is True


def test_lane_c_still_sharing_blocks_the_removal(tmp_path):
    admin = _FakeAdmin()
    admin.completion = {"completion": 62.5, "needBytes": 1234}
    app = _gate_app(tmp_path, {"count": 0, "samples": []}, admin)
    blockers = app.removal_blockers("p1")
    assert blockers["blocked"] is True
    assert any("62% synced" in r for r in blockers["reasons"])


def test_lane_c_files_not_yet_here_block_the_removal(tmp_path):
    admin = _FakeAdmin()
    admin.status = {"needTotalItems": 7, "state": "syncing"}
    app = _gate_app(tmp_path, {"count": 0, "samples": []}, admin)
    assert app.removal_blockers("p1")["blocked"] is True


def test_an_upload_only_project_is_gated_on_its_uploads_alone(tmp_path):
    """docs/UPLOAD_ONLY_TICK.md: no shared folder on this machine, so the
    lane C half of the gate is not asked -- a Syncthing that has no such
    folder (or a stale one from an earlier full tick) must not block, and
    pending originals still must."""
    admin = _FakeAdmin()
    admin.completion = {"completion": 12.0, "needBytes": 999}
    admin.status = {"needTotalItems": 7, "state": "syncing"}
    app = _gate_app(tmp_path, {"count": 0, "samples": []}, admin)
    app.removable_projects = lambda: [
        {"slug": "p1", "rel": "2026/CCT/Website Highlights", "upload_only": True}]
    blockers = app.removal_blockers("p1")
    assert blockers["blocked"] is False and blockers["lane_c"] == {}

    app = _gate_app(tmp_path, {"count": 2, "samples": ["A001.braw"]}, admin)
    app.removable_projects = lambda: [
        {"slug": "p1", "rel": "2026/CCT/Website Highlights", "upload_only": True}]
    assert app.removal_blockers("p1")["blocked"] is True


def test_remove_refuses_while_blocked_and_deletes_nothing(tmp_path):
    app = _gate_app(tmp_path, {"count": 3, "samples": ["A001.braw"]}, _FakeAdmin())
    app._managed = True
    app.selection_client = object()
    ok, message = app.remove_project_from_machine("p1")
    assert ok is False
    assert "not been uploaded yet" in message


def test_an_override_is_logged_and_reported(tmp_path, caplog):
    app = _gate_app(tmp_path, {"count": 3, "samples": ["A001.braw"]}, _FakeAdmin())
    app._managed = True

    class _Selection:
        def untick(self, slug):
            return False, "dashboard unreachable"

    app.selection_client = _Selection()
    with caplog.at_level("WARNING"):
        ok, _message = app.remove_project_from_machine("p1", override=True)
    # The untick fails, so nothing is deleted -- but the override decision was
    # already taken, and it must be on the record either way.
    assert ok is False
    assert any("OVERRIDE" in r.message for r in caplog.records)
    assert app.sync_guard()["removal_overrides"][-1]["pending_uploads"] == 3


# -- the Syncthing supervisor's wiring (SYNC-17, 2026-08-18) ----------------
#
# The supervisor's own state machine is tested in
# test_syncthing_supervisor.py; these are the four joins to the app: lane C
# drives it, the halt and the pause hold it off, and an open incident reaches
# the report. No process is spawned here either -- nothing calls tick().


def test_lane_c_is_handed_the_supervisor_and_a_probe(tmp_path):
    app = _app(tmp_path)
    assert app._lane_c.supervisor is app.syncthing_supervisor
    # The probe is the lane's own ping, bound after construction (the
    # supervisor exists before the lanes do).
    assert app.syncthing_supervisor.probe == app._lane_c.api_reachable


def test_the_supervisor_stands_off_while_syncing_is_halted(tmp_path):
    app = _app(tmp_path, sync_enabled=True)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer([])
    assert app._syncthing_supervision_suppressed() == ""

    app.halt_all_sync("restoring the pool")
    reason = app._syncthing_supervision_suppressed()
    # "halted" left the copy on 2026-09-04: sync is paused (you), stopped by
    # your admin (a fleet halt) or stopped itself (the breaker, the floor).
    assert "stopped on this computer" in reason


def test_a_fleet_halt_says_whose_it_is(tmp_path):
    app = _app(tmp_path, sync_enabled=True)
    app.syncthing_admin = _FakeAdmin()
    app.sequencer = _FakeSequencer([])
    app.halt.engage("pool import", lane_guard.HALT_SCOPE_FLEET)
    assert "administrator" in app._syncthing_supervision_suppressed()


def test_the_supervisor_stands_off_while_paused(tmp_path):
    app = _app(tmp_path, sync_enabled=True)
    app._paused = True
    assert "paused" in app._syncthing_supervision_suppressed()


def test_the_supervisor_stands_off_where_there_is_no_lane_c_at_all(tmp_path):
    """The base rig works straight off the NAS: sync_enabled=false, no lanes,
    and nothing for a resurrected Syncthing to do."""
    app = _app(tmp_path)          # the fixture config is sync_enabled=false
    assert "switched off" in app._syncthing_supervision_suppressed()


def test_an_open_supervisor_incident_reaches_the_report(tmp_path):
    app = _app(tmp_path)
    assert "syncthing_supervisor" not in app.sync_guard()

    app.syncthing_supervisor.tick(reachable=False)
    guard = app.sync_guard()
    assert guard["syncthing_supervisor"]["down_since"]
    assert guard["syncthing_supervisor"]["attempts"] == 0
    # sync_enabled=false on this machine, so it is NOT being restarted.
    assert guard["syncthing_supervisor"]["supervising"] is False

    app.syncthing_supervisor.tick(reachable=True)
    assert "syncthing_supervisor" not in app.sync_guard()


def test_the_supervisors_state_stays_in_the_state_dir(tmp_path):
    """The supervisor's incident record is diagnostics, so it stays under
    state/. The two LATCHES moved out of it (APP-3, 2026-08-28) because
    deleting state/ cleared a breaker only a human may clear."""
    app = _app(tmp_path)
    assert app.syncthing_supervisor.state_path.name == "syncthing_supervisor.json"
    assert app.syncthing_supervisor.state_path.parent.name == "state"
    assert (app.syncthing_supervisor.state_path.parent
            != app.lane_b_breaker.state_path.parent)


def test_both_latches_live_beside_the_config_not_in_the_state_dir(tmp_path):
    from ccsync_companion import config as config_mod

    app = _app(tmp_path)
    for latch in (app.lane_b_breaker.state_path, app.halt.state_path):
        assert latch.parent == config_mod.CONFIG_DIR, latch


def test_a_latch_written_by_an_older_build_is_adopted(tmp_path, monkeypatch):
    """The move must not CLEAR a live latch: an editor whose lane B is
    tripped, or a machine carrying a fleet halt, keeps it (APP-3)."""
    from ccsync_companion import config as config_mod
    from ccsync_companion.sync import lane_guard

    legacy = tmp_path / "state"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / lane_guard.HALT_STATE_FILENAME).write_text(
        json.dumps({"active": True, "scope": "fleet", "reason": "admin said so"}),
        encoding="utf-8")

    app = _app(tmp_path)
    assert app.halt.state_path == config_mod.CONFIG_DIR / lane_guard.HALT_STATE_FILENAME
    assert app.halt.active is True
    assert app.halt.scope == "fleet"
    # ...and the old copy is GONE, so a downgrade cannot latch on it again.
    assert not (legacy / lane_guard.HALT_STATE_FILENAME).exists()


# -- borrowed folders in the removal gate (SHARED_FOLDERS_PLAN.md WP2) ------


class _FakeSelectionEntries:
    def __init__(self, entries):
        self.entries = entries

    def get(self):
        return self.entries, "cache"


def _borrower_entries():
    return [{
        "slug": "p1", "label": "2026/CCT/Website Highlights",
        "rel_path": "2026/CCT/Website Highlights", "position": 0, "active": True,
        "includes": [{
            "subpath": "2026/FF5/Civil Defence/Interviewees/Aha Chu",
            "sub_rel": "Interviewees/Aha Chu",
            "lender_slug": "s-lender", "lender_label": "2026/FF5/Civil Defence",
            "covered": False,
        }],
    }]


def test_removing_a_borrower_dry_runs_its_borrowed_dirs_too(tmp_path):
    admin = _FakeAdmin()
    app = _gate_app(tmp_path, {"count": 0, "samples": []}, admin)
    app.selection_client = _FakeSelectionEntries(_borrower_entries())
    blockers = app.removal_blockers("p1")
    assert blockers["blocked"] is False
    assert app._lane_a.asked == [
        "Projects/2026/CCT/Website Highlights",
        "Projects/2026/FF5/Civil Defence/Interviewees/Aha Chu",
    ]


def test_unuploaded_footage_in_a_borrowed_dir_blocks_the_removal(tmp_path):
    admin = _FakeAdmin()
    app = _gate_app(tmp_path, {"count": 1, "samples": ["borrowed.braw"]}, admin)
    app.selection_client = _FakeSelectionEntries(_borrower_entries())
    blockers = app.removal_blockers("p1")
    assert blockers["blocked"] is True
    # both the project's own run and the include's run counted
    assert blockers["pending_uploads"] == 2


def test_removing_a_lender_with_a_selected_borrower_is_blocked(tmp_path):
    admin = _FakeAdmin()
    app = _gate_app(tmp_path, {"count": 0, "samples": []}, admin)
    entries = _borrower_entries()
    # the machine also has the LENDER selected; the include is covered
    entries[0]["includes"][0]["covered"] = True
    entries[0]["includes"][0]["lender_slug"] = "p-lender"
    entries.append({"slug": "p-lender", "label": "2026/FF5/Civil Defence",
                    "rel_path": "2026/FF5/Civil Defence", "position": 1,
                    "active": True, "includes": []})
    app.selection_client = _FakeSelectionEntries(entries)
    app.removable_projects = lambda: [
        {"slug": "p1", "rel": "2026/CCT/Website Highlights"},
        {"slug": "p-lender", "rel": "2026/FF5/Civil Defence"}]
    blockers = app.removal_blockers("p-lender")
    assert blockers["blocked"] is True
    assert any("is shared into 2026/CCT/Website Highlights" in r
               for r in blockers["reasons"])
    # a covered include is never dry-run as the borrower's own upload scope
    assert "Projects/2026/FF5/Civil Defence" in app._lane_a.asked[0]
