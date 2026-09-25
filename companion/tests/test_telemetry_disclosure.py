"""LG-16: the report's shape is pinned against what the documents disclose.

docs/LEGAL_GAP_FEATURES_PLAN.md section 5, LG-16 (2026-09-25). A new report
key used to need nobody's attention: it went on the wire and the dashboard
ignored or stored it. docs/legal/TELEMETRY.md now lists the payload for
counsel, and telemetry_policy.FIELDS decides what the four switches withhold,
so a new key that nobody classified is a disclosure gap. These tests fail on
one, and say what to update.
"""
from __future__ import annotations

import re
from pathlib import Path

from ccsync_companion import capabilities as caps_mod
from ccsync_companion import reporter as reporter_mod
from ccsync_companion import telemetry_policy as tp

UPDATE = ("update TELEMETRY.md's payload table, the FIELDS table, then this list.")

# Every top-level key a full report carries today, sorted.
PINNED_TOP_LEVEL = sorted([
    "arch", "broll_ingest", "capabilities", "companion_version", "completed",
    "current_project", "editor_name", "eula", "file_moves_applied", "lanes",
    "local_manifest", "machine", "machine_id", "machine_settings", "media_tree",
    "mode", "music_ingest", "platform", "proxy_coverage", "queue", "report_optouts",
    "reported_at", "resolve_journals", "resolve_project", "resolve_undo_applied",
    "sync_guard", "syncthing_device_id", "transport_health", "youtube_import",
])

# Every key of the `capabilities` section, sorted.
PINNED_CAPABILITIES = sorted([
    "cards_agent", "claude", "companion_version", "cpu_count", "ffmpeg", "ffprobe",
    "gpu_name", "gpu_present", "gpu_vram_gb", "idle_seconds", "job_kinds",
    "jobs_enabled", "jobs_gate", "jobs_idle_seconds", "load", "mounts", "nvenc",
    "resolve", "volunteer_until", "whisper", "whisper_detail",
])

# Keys that carry none of the four switchable kinds of data, each with why.
# Anything personal that is NOT switchable is named in TELEMETRY.md's "still
# sent" list instead (transfer names, file-move answers, the Cards agent).
NOT_PERSONAL_TOP_LEVEL = {
    "arch", "companion_version", "platform", "reported_at",   # build facts
    "editor_name", "machine", "machine_id", "syncthing_device_id",  # identity, disclosed
    "mode", "lanes", "queue", "current_project",   # the sync plan the dashboard itself set
    "completed", "file_moves_applied",   # "still sent": sync needs them
    "transport_health", "proxy_coverage", "youtube_import",   # counters and states
    "broll_ingest", "music_ingest", "machine_settings",       # the editor's own actions
    "eula", "report_optouts",                                  # LG-5 / LG-1 bookkeeping
}
NOT_PERSONAL_CAPABILITIES = {
    "cards_agent",   # "still sent": only when the editor turned the agent on
    "claude", "companion_version", "cpu_count", "ffmpeg", "ffprobe", "gpu_name",
    "gpu_present", "gpu_vram_gb", "job_kinds", "jobs_enabled", "jobs_gate",
    "jobs_idle_seconds", "load", "mounts", "nvenc", "volunteer_until", "whisper",
    "whisper_detail",
}


# -- inside sync_guard (G1a review round 1, 2026-09-25) ---------------------
#
# The top-level pin could not see a new key INSIDE sync_guard, and local file
# names and paths ride there. These sets are read from the source (the section
# is built from a dozen producers that a unit fixture cannot all switch on),
# so a new `guard["x"] = ...` in app.sync_guard, a new `out["x"]` in lane B's
# sync_guard_report or a new key in app.resolve_health fails here until it is
# classified: in a FIELDS row, not personal, or "still sent" (named in
# TELEMETRY.md's still-sent list).
SRC = Path(caps_mod.__file__).resolve().parent

PINNED_SYNC_GUARD = sorted([
    "blocked", "clock_skew_seconds", "crashes", "disk", "disk_floor",
    "folders_unfiltered", "halt", "ingest_staging", "lane_b_breaker", "loopback",
    "moved_project_dirs", "removal_overrides", "repath_events", "reporter",
    "resolve_health", "restarts", "root_state", "rotation_seconds",
    "shared_folder_problems", "skipped_exists", "stalled", "standins_placed",
    "stray_projects", "sync_conflicts", "syncthing_supervisor", "trash", "upgrade",
    "youtube_import", "ytdlp",
])
NOT_PERSONAL_SYNC_GUARD = {
    "clock_skew_seconds", "crashes", "disk", "disk_floor", "halt", "ingest_staging",
    "lane_b_breaker", "loopback", "reporter", "restarts", "root_state",
    "rotation_seconds", "syncthing_supervisor", "upgrade", "youtube_import", "ytdlp",
}
# Carry names or paths, and are sent whatever the switches say: each is about
# the server's tree, the sync plan or the shared folders the admin set up, or
# is a sentence an admin needs to unblock the machine.
STILL_SENT_SYNC_GUARD = {
    "blocked", "folders_unfiltered", "removal_overrides", "repath_events",
    "shared_folder_problems", "stalled", "standins_placed", "trash",
}
# Keys with a FIELDS row reaching INTO them (so the key itself stays).
PARTLY_SWITCHABLE_SYNC_GUARD = {"resolve_health", "skipped_exists", "sync_conflicts"}

PINNED_RESOLVE_HEALTH = sorted([
    "bad_prefix", "connected", "ignored_folders", "ignored_this_session",
    "last_scan_at", "missing", "missing_clips", "non_canonical_refused",
    "open_project", "out_of_tree", "project_open", "proxy_attach", "proxy_gaps",
    "skipped_ever", "standins_owed", "stills", "wedged_call", "wedged_seconds",
])
NOT_PERSONAL_RESOLVE_HEALTH = {
    "bad_prefix", "connected", "ignored_folders", "ignored_this_session",
    "last_scan_at", "missing", "out_of_tree", "proxy_attach", "proxy_gaps",
    "skipped_ever", "standins_owed", "wedged_call", "wedged_seconds",
}
# `stills.path` is the stills folder the site configured.
STILL_SENT_RESOLVE_HEALTH = {"stills"}


def _method_source(module_file: str, signature: str) -> str:
    text = (SRC / module_file).read_text(encoding="utf-8")
    start = text.index(signature)
    end = text.find("\n    def ", start + len(signature))
    return text[start:end if end > 0 else len(text)]


def _source_sync_guard_keys() -> list[str]:
    app_body = _method_source("app.py", "    def sync_guard(self)")
    lane_body = _method_source("sync/rclone_lane.py", "    def sync_guard_report(self)")
    keys = set(re.findall(r'guard\["(\w+)"\]\s*=', app_body))
    keys |= set(re.findall(r'out\["(\w+)"\]\s*=', lane_body))
    return sorted(keys)


def _source_resolve_health_keys() -> list[str]:
    body = _method_source("app.py", "    def resolve_health(self)")
    literal = body[body.index("return {"):]
    return sorted(set(re.findall(r'^\s*"(\w+)":', literal, flags=re.MULTILINE)))


def _covered(prefix: str = "") -> set[str]:
    """The keys (at the level `prefix` names) some FIELDS row reaches into."""
    out = set()
    for paths in tp.FIELDS.values():
        for path in paths:
            if prefix and not path.startswith(prefix + "."):
                continue
            rest = path[len(prefix) + 1:] if prefix else path
            out.add(rest.split(".")[0].replace("[]", ""))
    return out


class _Status:
    def __init__(self):
        self.name, self.state, self.queued, self.transferring = "a", "idle", 0, 0
        self.last_error = self.last_sync = self.detail = self.current_project = None
        self.bytes_done = self.bytes_total = self.speed_bps = self.eta_seconds = None
        self.transfers = []


def _capabilities(monkeypatch, tmp_path):
    caps_mod.reset_cache()
    monkeypatch.setattr(caps_mod, "_gpu", lambda: {"present": True, "name": "RTX", "vram_gb": 24})
    monkeypatch.setattr(caps_mod, "_nvenc", lambda cfg: True)
    monkeypatch.setattr(caps_mod, "_ffmpeg", lambda cfg: True)
    monkeypatch.setattr(caps_mod, "_ffprobe", lambda cfg: True)
    monkeypatch.setattr(caps_mod, "_claude", lambda: False)

    class Idle:
        def seconds_idle(self):
            return 10.0

    section = caps_mod.build(
        {"local_root": str(tmp_path)}, idle_probe=Idle(),
        resolve_running_fn=lambda: False, resolve_project_fn=lambda: "",
        cards_agent_fn=lambda: {"state": "off"},
        volunteer_until_fn=lambda: None,
        jobs_gate_fn=lambda: {"taking_work": True, "reason": "idle"}, use_cache=False)
    caps_mod.reset_cache()
    return section


def _full_payload(monkeypatch, tmp_path):
    caps = _capabilities(monkeypatch, tmp_path)
    rep = reporter_mod.DashboardReporter(
        lambda: [_Status()], {"dashboard_url": "https://dash.example", "editor_name": "owen"},
        get_site=lambda: None,
        get_queue_info=lambda: (["Projects/A"], "Projects/A"),
        get_resolve_project=lambda: "P",
        get_local_manifest=lambda: {"Projects/A": {"files": []}},
        get_media_tree=lambda: {"P": []},
        get_mode=lambda: "editor",
        get_machine_id=lambda: "m-1",
        get_syncthing_device_id=lambda: "DEV",
        get_transport_health=lambda: {"syncthing": {}},
        get_completions=lambda: [{"path": "Projects/A/a.mov", "lane": "a"}],
        get_proxy_coverage=lambda: {"missing": 1},
        get_youtube_import=lambda: {"pending": 1},
        get_sync_guard=lambda: {"reporter": {}},
        get_broll_ingest=lambda: {"batch": 1},
        get_music_ingest=lambda: {"batch": 1},
        get_file_moves_applied=lambda: [{"id": 1}],
        get_capabilities=lambda: caps,
        get_resolve_journals=lambda: [],
        get_resolve_undo_applied=lambda: [{"id": 1}],
        get_machine_settings=lambda: {"accepts": ["jobs_enabled"]},
        get_eula=lambda: {"version": "1.1", "accepted_at": "x", "eula_sha256": "y"},
    )
    return rep._build_payload(light=False)


def test_the_top_level_report_keys_are_pinned(monkeypatch, tmp_path):
    payload = _full_payload(monkeypatch, tmp_path)
    assert sorted(payload) == PINNED_TOP_LEVEL, (
        "the report's top-level keys changed: " + UPDATE)


def test_the_capabilities_keys_are_pinned(monkeypatch, tmp_path):
    payload = _full_payload(monkeypatch, tmp_path)
    assert sorted(payload["capabilities"]) == PINNED_CAPABILITIES, (
        "the capabilities section's keys changed: " + UPDATE)


def test_every_key_is_switchable_or_named_not_personal():
    top = _covered()
    for key in PINNED_TOP_LEVEL:
        assert key in top or key in NOT_PERSONAL_TOP_LEVEL, (
            f"report key {key!r} is in no FIELDS row and not listed as not personal: "
            + UPDATE)
    caps = _covered("capabilities")
    for key in PINNED_CAPABILITIES:
        assert key in caps or key in NOT_PERSONAL_CAPABILITIES, (
            f"capabilities key {key!r} is in no FIELDS row and not listed as not "
            "personal: " + UPDATE)


def test_the_lists_carry_no_stale_names():
    assert NOT_PERSONAL_TOP_LEVEL <= set(PINNED_TOP_LEVEL)
    assert NOT_PERSONAL_CAPABILITIES <= set(PINNED_CAPABILITIES)
    # A key cannot be both switchable and "not personal".
    assert not (NOT_PERSONAL_TOP_LEVEL & _covered())
    assert not (NOT_PERSONAL_CAPABILITIES & _covered("capabilities"))


def test_the_sync_guard_keys_are_pinned():
    assert _source_sync_guard_keys() == PINNED_SYNC_GUARD, (
        "a sync_guard key changed: " + UPDATE)


def test_the_resolve_health_keys_are_pinned():
    assert _source_resolve_health_keys() == PINNED_RESOLVE_HEALTH, (
        "a sync_guard.resolve_health key changed: " + UPDATE)


def test_every_sync_guard_key_is_classified_once():
    covered = _covered("sync_guard")
    for key in PINNED_SYNC_GUARD:
        homes = [key in covered, key in NOT_PERSONAL_SYNC_GUARD, key in STILL_SENT_SYNC_GUARD]
        assert sum(homes) == 1 or (key in PARTLY_SWITCHABLE_SYNC_GUARD and homes[0]), (
            f"sync_guard key {key!r} is not classified exactly once: " + UPDATE)
    covered_health = _covered("sync_guard.resolve_health")
    for key in PINNED_RESOLVE_HEALTH:
        homes = [key in covered_health, key in NOT_PERSONAL_RESOLVE_HEALTH,
                 key in STILL_SENT_RESOLVE_HEALTH]
        assert sum(homes) == 1, (
            f"resolve_health key {key!r} is not classified exactly once: " + UPDATE)


def test_the_local_file_names_in_skipped_exists_are_switchable():
    # G1a review round 1: lane A's "skipped, exists" samples are file names
    # from this computer's tree, i.e. the local_manifest kind of data.
    assert "sync_guard.skipped_exists.samples" in tp.FIELDS[tp.LOCAL_MANIFEST]


def test_the_undo_answer_is_switchable_with_the_project_name():
    assert "resolve_undo_applied[].detail" in tp.FIELDS[tp.RESOLVE_PROJECT]
    assert tp.MASKED["resolve_undo_applied[].detail"] == "undo_detail"
