from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ccsync_dashboard import health

NOW = "2026-07-24T12:00:00+00:00"
RECENT = "2026-07-24T11:59:00+00:00"      # 1 min ago
OLD = "2026-07-24T11:30:00+00:00"         # 30 min ago


def editor(**overrides):
    base = dict(
        completion=100.0, need_items=0, connected=True, last_connected_at=RECENT,
        completion_updated_at=RECENT, syncthing_reachable=True, lanes=(), now=NOW,
    )
    base.update(overrides)
    return health.editor_status(**base)


def test_green_when_synced_and_idle():
    assert editor() == health.GREEN
    assert editor(lanes=[{"state": "idle"}, {"state": "paused"}]) == health.GREEN


def test_amber_when_behind_or_syncing():
    assert editor(completion=62.0, need_items=42) == health.AMBER
    assert editor(lanes=[{"state": "syncing"}]) == health.AMBER
    # behind but offline only briefly -> still amber, not red
    assert editor(completion=62.0, need_items=42, connected=False,
                  last_connected_at=RECENT) == health.AMBER


def test_red_on_lane_error():
    assert editor(lanes=[{"state": "idle"}, {"state": "error"}]) == health.RED


def test_red_when_offline_long_and_behind():
    assert editor(completion=62.0, need_items=42, connected=False,
                  last_connected_at=OLD) == health.RED
    assert editor(completion=62.0, need_items=42, connected=False,
                  last_connected_at=None) == health.RED
    # offline but fully synced -> green (nothing owed either way)
    assert editor(connected=False, last_connected_at=OLD) == health.GREEN


def test_red_when_completion_stale_while_syncthing_up():
    assert editor(completion_updated_at=OLD) == health.RED
    # not stale if Syncthing itself is down -- banner covers that case
    assert editor(completion_updated_at=OLD, syncthing_reachable=False) == health.GREEN


def test_rollups_and_precedence():
    assert health.worst([]) == health.GREEN
    assert health.project_status(["green", "amber", "green"]) == health.AMBER
    assert health.fleet_status(["amber", "red"]) == health.RED
    assert health.worst(["green", "unknown-nonsense"]) == health.GREEN


def test_lane_chip_status():
    assert health.lane_chip_status({"state": "idle", "received_at": RECENT}, NOW) == health.GREEN
    assert health.lane_chip_status({"state": "syncing", "received_at": RECENT}, NOW) == health.AMBER
    assert health.lane_chip_status({"state": "error", "received_at": RECENT}, NOW) == health.RED
    # companion silent for 15+ min -> red regardless of last state
    assert health.lane_chip_status({"state": "idle", "received_at": OLD}, NOW) == health.RED
    fresh_enough = "2026-07-24T11:50:00+00:00"  # 10 min ago, under the 15-min cutoff
    assert health.lane_chip_status({"state": "idle", "received_at": fresh_enough}, NOW) == health.GREEN


# --------------------------------------------------------------- SYS-1 stall
#
# SYS-1 (resilience sweep 2026-08-28). A lane in `syncing` was AMBER for as
# long as it liked: CR-91b sat at state=syncing, transferring=1,
# last_error=NULL for 2 h 20 m with nothing moving, and because lane A takes
# its turn first the editor downloaded nothing for the whole period.

def lane(**overrides):
    base = {"state": "syncing", "received_at": RECENT}
    base.update(overrides)
    return base


def test_a_lane_that_has_not_moved_its_token_past_the_budget_is_red():
    stuck_since = "2026-07-24T10:00:00+00:00"    # 2 h ago
    assert health.lane_stall("syncing", stuck_since, NOW) == 2 * 3600
    colour, reason = health.lane_chip(lane(progress_token_since=stuck_since), NOW)
    assert colour == health.RED
    assert reason == "syncing, no progress for 120 min"


def test_the_budget_is_three_rotations_with_a_thirty_minute_floor():
    forty_min_ago = "2026-07-24T11:20:00+00:00"
    # 30 min floor: a 10 min rotation does not shrink it to 30 min... it IS 30
    assert health.lane_stall("syncing", forty_min_ago, NOW, 600) is not None
    # ...and a one-hour rotation stretches it to three hours, so 40 min is fine
    assert health.lane_stall("syncing", forty_min_ago, NOW, 3600) is None
    assert health.LANE_STALL_FLOOR_SECONDS == 30 * 60
    assert health.LANE_STALL_ROTATIONS == 3


def test_a_lane_inside_its_budget_is_still_amber_not_red():
    ten_min_ago = "2026-07-24T11:50:00+00:00"
    colour, reason = health.lane_chip(lane(progress_token_since=ten_min_ago), NOW)
    assert colour == health.AMBER and reason is None


def test_a_terminal_state_can_never_stall():
    long_ago = "2026-07-24T06:00:00+00:00"
    for state in ("idle", "error", "paused"):
        assert health.lane_stall(state, long_ago, NOW) is None


def test_a_companion_too_old_to_send_a_token_is_no_verdict_not_a_stall():
    """Every machine in the field on the day this shipped. An upgrade window
    must not redden the whole fleet."""
    assert health.lane_stall("syncing", None, NOW) is None
    assert health.lane_stall("syncing", "", NOW) is None
    assert health.lane_chip(lane(), NOW)[0] == health.AMBER


def test_an_unreadable_token_stamp_is_no_verdict_and_never_raises():
    assert health.lane_stall("syncing", "whenever", NOW) is None


def test_silence_still_outranks_a_stall_and_says_which_it_is():
    colour, reason = health.lane_chip(
        lane(received_at=OLD, progress_token_since=OLD), NOW)
    assert colour == health.RED
    assert "silent" in reason


def test_lane_chip_status_stays_the_colour_only_view():
    stuck_since = "2026-07-24T10:00:00+00:00"
    assert health.lane_chip_status(
        lane(progress_token_since=stuck_since), NOW) == health.RED


def test_lane_chip_status_is_defined_exactly_once():
    """bug-hunt-2026-09-03 dash-collector-8: the pre-SYS-1 definition sat
    above the rewrite, shadowed at import, encoding the OLD rule (no stall
    test) - so it could be maintained to no effect and read as proof the
    stall is not applied to a lane's dot."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(health))
    named = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name == "lane_chip_status"]
    assert len(named) == 1


# ----------------------------------------------------------------- SYS-5 disk

def test_the_disk_rule_reads_both_a_percentage_and_a_floor():
    tb = 1024 ** 4
    gb = 1024 ** 3
    # 4 % of 8 TB is 327 GB, which is plenty of room but a drive about to die
    assert health.disk_status(int(0.04 * 8 * tb), 8 * tb)[0] == health.RED
    # 40 % of a small disk, but only 18 GB left
    assert health.disk_status(18 * gb, 45 * gb)[0] == health.RED
    assert health.disk_status(40 * gb, 500 * gb)[0] == health.AMBER
    assert health.disk_status(300 * gb, 1000 * gb)[0] == health.GREEN
    assert health.disk_status(0, 500 * gb)[0] == health.RED


def test_a_machine_that_reported_no_disk_section_gets_no_verdict():
    """"Could not check" must never render as a green reassurance: the grid
    shows no chip at all rather than a green one."""
    assert health.disk_status(None, None) == (health.GREEN, None)
    assert health.disk_status(None, 1024 ** 4) == (health.GREEN, None)
    assert health.disk_status(1024 ** 3, None) == (health.GREEN, None)


# ------------------------------------------------------------------ UX-1 tick

def test_the_tick_warning_names_both_figures():
    gb = 1024 ** 3
    sentence = health.capacity_warning("2026/FF5/Animals", 620 * gb, "LESO-MBP", 180 * gb)
    assert sentence.startswith("2026/FF5/Animals is 620 GB of proxies. ")
    assert "LESO-MBP has 180 GB free." in sentence
    assert "more than will fit" in sentence
    assert "—" not in sentence


def test_a_tick_that_fits_with_room_to_spare_says_nothing():
    gb = 1024 ** 3
    assert health.capacity_warning("small", 10 * gb, "PC", 900 * gb) is None
    # ...but half of what is left is worth a sentence even though it fits
    assert health.capacity_warning("big", 300 * gb, "PC", 500 * gb) is not None


def test_an_unknown_figure_is_silence_not_a_guess():
    gb = 1024 ** 3
    assert health.capacity_warning("p", None, "PC", 100 * gb) is None
    assert health.capacity_warning("p", 100 * gb, "PC", None) is None
    assert health.capacity_warning("p", 0, "PC", 100 * gb) is None


# ---------------------------------------------------------------- SYS-7
#
# One sentence for "why is this machine not syncing". The tree is ordered, so
# the tests are ordered: every reason, in the contract's order, plus the two
# properties that matter more than any single sentence -- the companion's own
# answer wins, and an upload-only machine is EXPLAINED rather than accused.

GB = 1000 ** 3


def _row(**overrides):
    """A fleet-grid row shaped like build_editors_view's, healthy by default."""
    guard = {
        "breaker_tripped": False, "halt_active": False, "halt_scope": None,
        "clock_skew_seconds": 0.0, "folders_unfiltered": None,
        "supervisor_down_since": None,
        "disk_root_free_bytes": 900 * GB, "disk_root_total_bytes": 1000 * GB,
        "blocked_reason": None, "blocked_detail": None, "blocked_since": None,
        "stalled_lane": None, "stalled_seconds": None,
    }
    guard.update(overrides.pop("guard", {}))
    row = {
        "editor_username": "leso", "machine": "LESO-MBP", "verified": True,
        "mode": "editor", "fleet_halt_active": False, "lanes": [],
        "plan": {"count": 2, "full": 2, "upload_only": 0},
        "guard": guard,
    }
    row.update(overrides)
    return row


def test_a_healthy_machine_has_no_sentence():
    assert health.why_not_syncing(_row(), NOW) is None


def test_every_reason_the_companion_can_report_gets_one_sentence():
    """Parametrised over the WHOLE contract order, in order.

    The point is not the wording, it is that no reason in the wire contract
    can arrive and produce nothing: silence here renders as green, which is
    the mistake SYS-7 exists to end.
    """
    for reason in health.WHY_ORDER:
        row = _row(guard={"blocked_reason": reason})
        answer = health.why_not_syncing(row, NOW)
        assert answer is not None, reason
        code, sentence = answer
        assert code == reason
        assert sentence
        assert sentence[0].isupper()
        # No em dash in anything an editor reads (owner's rule, 2026-08-18).
        assert "\u2014" not in sentence
        # A sentence that is only the code back again explains nothing.
        assert sentence != reason
        assert sentence.startswith(("Not syncing:", "Not downloading proxies:",
                                    "Not syncing safely:", "Nothing to sync:",
                                    "Nothing to download:"))


def test_the_order_is_the_contracts_order():
    """First match wins, and the ordering is the whole design: the ACTIONABLE
    reason has to beat the consequence it caused."""
    assert health.WHY_ORDER.index("not_signed_in") == 0
    assert health.WHY_ORDER.index("clock_skew") < health.WHY_ORDER.index("disk_full")
    assert health.WHY_ORDER.index("disk_full") < health.WHY_ORDER.index("fleet_halt")
    assert health.WHY_ORDER.index("fleet_halt") < health.WHY_ORDER.index("local_halt")
    assert health.WHY_ORDER.index("breaker_tripped") < health.WHY_ORDER.index("no_selection")
    assert health.WHY_ORDER.index("upload_only") < health.WHY_ORDER.index("lane_stalled")
    assert health.WHY_ORDER.index("transport_offline") == len(health.WHY_ORDER) - 1


def test_the_companions_own_answer_beats_the_servers_derivation():
    """SYNC-15: the machine can see the root guard's fourth answer, the licence
    park and its own transport. None of those reach a column here, so a
    reported reason must not be overridden by a locally derived one."""
    row = _row(guard={"blocked_reason": "root_not_answering",
                      "breaker_tripped": True, "halt_active": True})
    code, sentence = health.why_not_syncing(row, NOW)
    assert code == "root_not_answering"
    assert "not answering" in sentence


def test_the_companions_detail_is_appended_never_substituted():
    row = _row(guard={"blocked_reason": "root_misplaced",
                      "blocked_detail": "P:\\ points at D:\\Backup"})
    _code, sentence = health.why_not_syncing(row, NOW)
    assert sentence.startswith("Not syncing: the sync drive is pointing")
    assert "P:\\ points at D:\\Backup" in sentence


def test_a_paragraph_of_detail_is_left_off_the_grid_line():
    row = _row(guard={"blocked_reason": "root_absent", "blocked_detail": "x" * 400})
    _code, sentence = health.why_not_syncing(row, NOW)
    assert "xxxx" not in sentence


def test_a_reason_a_newer_companion_knows_is_named_not_swallowed():
    """The third repeat of SYS-3 in a new place is what this prevents: an
    unknown code must never render as no reason at all."""
    row = _row(guard={"blocked_reason": "quantum_flux"})
    code, sentence = health.why_not_syncing(row, NOW)
    assert code == "blocked"
    assert "too old to explain" in sentence


def test_not_signed_in_is_the_first_thing_derived():
    code, sentence = health.why_not_syncing(_row(verified=False), NOW)
    assert code == "not_signed_in"
    assert sentence == "Not syncing: this computer is not signed in"


def test_clock_skew_is_named_with_its_size():
    code, sentence = health.why_not_syncing(
        _row(guard={"clock_skew_seconds": -480.0}), NOW)
    assert code == "clock_skew"
    assert "8 minutes" in sentence
    # Under the threshold is NTP jitter, not a fault.
    assert health.why_not_syncing(_row(guard={"clock_skew_seconds": 12.0}), NOW) is None


def test_a_full_disk_uses_the_chips_own_red():
    code, sentence = health.why_not_syncing(
        _row(guard={"disk_root_free_bytes": 8 * GB,
                    "disk_root_total_bytes": 1000 * GB}), NOW)
    assert code == "disk_full"
    assert "free" in sentence
    # An amber disk is not a reason nothing is syncing.
    assert health.why_not_syncing(
        _row(guard={"disk_root_free_bytes": 60 * 1024 ** 3,
                    "disk_root_total_bytes": 1000 * 1024 ** 3}), NOW) is None


def test_a_machine_that_never_reported_a_disk_is_not_called_full():
    """"Could not check" must never render as either answer (wave 1's rule)."""
    assert health.why_not_syncing(
        _row(guard={"disk_root_free_bytes": None,
                    "disk_root_total_bytes": None}), NOW) is None


def test_a_fleet_halt_outranks_the_local_one():
    code, _s = health.why_not_syncing(
        _row(fleet_halt_active=True, guard={"halt_active": True}), NOW)
    assert code == "fleet_halt"
    code, _s = health.why_not_syncing(_row(guard={"halt_active": True}), NOW)
    assert code == "local_halt"


def test_the_breaker_is_named_as_proxy_download_only():
    code, sentence = health.why_not_syncing(
        _row(guard={"breaker_tripped": True}), NOW)
    assert code == "breaker_tripped"
    assert sentence.startswith("Not downloading proxies:")


def test_no_tick_is_a_reason_but_never_on_a_base_rig():
    """CR-28: a base rig holds no tick BY DESIGN, and saying so in red is what
    put a permanent GETTING READY chip on the fleet page."""
    code, sentence = health.why_not_syncing(
        _row(plan={"count": 0, "full": 0, "upload_only": 0}), NOW)
    assert code == "no_selection"
    assert "ticked" in sentence
    assert health.why_not_syncing(
        _row(mode="base", plan={"count": 0, "full": 0, "upload_only": 0}), NOW) is None


def test_an_absent_plan_is_not_read_as_an_empty_one():
    row = _row()
    row.pop("plan")
    assert health.why_not_syncing(row, NOW) is None


def test_upload_only_is_informational_not_a_fault():
    """CR-85: lane B is MEANT to be idle for an upload-only tick. The sentence
    exists so an admin stops chasing it, which is the opposite of an alarm."""
    code, sentence = health.why_not_syncing(
        _row(plan={"count": 1, "full": 0, "upload_only": 1}), NOW)
    assert code == "upload_only"
    assert code in health.WHY_INFORMATIONAL
    assert sentence == ("Nothing to download: this project is upload-only on this "
                        "computer")
    # ...and a machine with BOTH kinds of tick is not upload-only.
    assert health.why_not_syncing(
        _row(plan={"count": 2, "full": 1, "upload_only": 1}), NOW) is None


def test_only_upload_only_is_informational():
    for reason in health.WHY_ORDER:
        if reason == "upload_only":
            continue
        assert reason not in health.WHY_INFORMATIONAL, reason


def test_a_stall_the_companion_killed_is_named_by_lane():
    code, sentence = health.why_not_syncing(
        _row(guard={"stalled_lane": "B", "stalled_seconds": 2820}), NOW)
    assert code == "lane_stalled"
    assert "proxy download" in sentence
    assert "47 minutes" in sentence


def test_a_stall_only_the_server_can_see_is_still_named():
    """SYS-1's half: the token has not moved for two hours and the companion
    never noticed, which is CR-91b exactly."""
    row = _row(lanes=[{"lane": "lane_a_video_up", "state": "syncing",
                       "progress_token_since": "2026-07-24T09:40:00+00:00",
                       "received_at": RECENT}])
    code, sentence = health.why_not_syncing(row, NOW)
    assert code == "lane_stalled"
    assert "upload" in sentence


def test_a_dead_sync_engine_is_the_last_thing_derived():
    code, sentence = health.why_not_syncing(
        _row(guard={"supervisor_down_since": OLD}), NOW)
    assert code == "syncthing_down"
    assert "sync engine" in sentence


def test_unfiltered_folders_beat_an_upload_only_explanation():
    """A folder with no ignore filter carries camera originals both ways; that
    is a fault, and an explanation must not hide it."""
    code, _s = health.why_not_syncing(
        _row(plan={"count": 1, "full": 0, "upload_only": 1},
             guard={"folders_unfiltered": 3}), NOW)
    assert code == "folders_unfiltered"


def test_a_bare_machine_state_row_is_a_valid_shape():
    """The function is also called with the flat row (no `guard` nesting): a
    caller that has one must not have to reshape it."""
    code, _s = health.why_not_syncing(
        {"verified": True, "blocked_reason": "transport_offline"}, NOW)
    assert code == "transport_offline"


def test_nothing_here_raises_on_junk():
    """It runs on every fleet-grid render: a bad value must cost a sentence,
    never the page."""
    for junk in ({"clock_skew_seconds": "soon"},
                 {"disk_root_free_bytes": "lots", "disk_root_total_bytes": 0},
                 {"stalled_seconds": "ages", "stalled_lane": 7}):
        health.why_not_syncing(_row(guard=junk), NOW)
    health.why_not_syncing({}, NOW)
    health.why_not_syncing({"lanes": [None, "x"]}, NOW)


# ------------------------------------------------------------------- UX-19
#
# Usability sweep 2026-09-03. A local stop and a pause are two switches with
# one word: with both set, an editor cleared the one the grid named and
# nothing started moving. The ranking is unchanged - it decides which comes
# FIRST, never which of the two is said - and only causes a person can act on
# separately qualify, so a stall or a dead engine never becomes a second
# clause about the same fault.


def test_a_pause_under_a_stop_names_both_switches():
    row = _row(guard={"blocked_reason": "paused", "halt_active": True})
    code, sentence = health.why_not_syncing(row, NOW)
    assert code == "paused"                       # the companion's own answer
    assert sentence == ("Not syncing: syncing is paused on this computer. "
                        "Also: syncing is stopped on this computer")
    assert [c for c, _s in health.why_causes(row, NOW)] == ["paused", "local_halt"]


def test_a_fleet_stop_is_the_second_cause_when_the_computer_reported_a_pause():
    row = _row(fleet_halt_active=True, guard={"blocked_reason": "paused"})
    code, sentence = health.why_not_syncing(row, NOW)
    assert code == "paused"
    assert "stopped by your admin" in sentence
    assert sentence.count("Not syncing") == 1, (
        "the second clause is a clause, not a second whole sentence")


def test_the_ranking_still_decides_which_comes_first():
    """A fleet stop outranks the local one, and the local one is not repeated
    under it: the two halt branches are one switch, not two."""
    row = _row(fleet_halt_active=True, guard={"halt_active": True})
    codes = [c for c, _s in health.why_causes(row, NOW)]
    assert codes == ["fleet_halt"]


def test_only_a_switch_a_person_can_clear_is_a_second_cause():
    """A stalled transfer under a stop is the SAME fault said twice."""
    row = _row(guard={"halt_active": True, "stalled_lane": "B",
                      "stalled_seconds": 2820})
    codes = [c for c, _s in health.why_causes(row, NOW)]
    assert codes == ["local_halt"]
    assert set(health.WHY_SECOND_CAUSES) <= set(health.WHY_ORDER)
    for code in health.WHY_SECOND_CAUSES:
        assert code not in ("lane_stalled", "syncthing_down", "no_selection")


def test_a_computer_that_stopped_itself_says_so_in_both_shapes():
    """The vocabulary (CR-181): the brake and the disk floor are the computer
    stopping ITSELF, which is neither "you paused it" nor "your admin
    stopped it"."""
    _code, breaker = health.why_not_syncing(
        _row(guard={"breaker_tripped": True}), NOW)
    assert "stopped itself" in breaker
    _code, disk = health.why_not_syncing(
        _row(guard={"disk_root_free_bytes": 8 * GB,
                    "disk_root_total_bytes": 1000 * GB}), NOW)
    assert "stopped itself" in disk


def test_the_three_ways_sync_is_off_are_three_different_sentences():
    row = _row()
    assert "stopped by your admin" in health._why_sentence("fleet_halt", row)
    assert "paused" in health._why_sentence("paused", row)
    assert "stopped on this computer" in health._why_sentence("local_halt", row)
    for code in ("fleet_halt", "local_halt", "paused", "breaker_tripped"):
        sentence = health._why_sentence(code, row)
        assert "halted" not in sentence and "parked" not in sentence
        assert "breaker" not in sentence and "machine" not in sentence


def test_a_second_cause_never_costs_the_page():
    for junk in ({"halt_active": "yes", "halt_scope": 7},
                 {"blocked_reason": "paused", "disk_root_free_bytes": "lots",
                  "disk_root_total_bytes": 0},
                 {"breaker_tripped": "maybe"}):
        health.why_not_syncing(_row(guard=junk), NOW)
        health.why_causes(_row(guard=junk), NOW)
    assert health.why_causes({}, NOW) == []
