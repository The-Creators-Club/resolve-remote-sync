"""The declared report model, pinned (LG-16, docs/LEGAL_GAP_FEATURES_PLAN.md
section 5, 2026-09-25, group G2a).

TELEMETRY.md's payload table says what a companion report carries, and the
telemetry switches (LG-1) say which of it can be withheld. Both are only true
while the model they describe is the model the dashboard parses. This file
fails the moment a field is declared on ReportIn, CapabilitiesIn or
SyncGuardIn without somebody deciding, in writing, whether it carries one of
the four switchable kinds of data (then it gets a row in telemetry_fields.
FIELDS and the companion's telemetry_policy.FIELDS) or not (then it goes in
the NOT_PERSONAL list below, with the reason on its line).

The companion pins its own payload the same way
(companion/tests/test_telemetry_disclosure.py, G1a).
"""
from __future__ import annotations

from ccsync_dashboard import api, telemetry_fields

FIX = ("update TELEMETRY.md's payload table, the FIELDS table, then this list "
       "(dashboard telemetry_fields.FIELDS and companion telemetry_policy.FIELDS "
       "move together)")

REPORT_FIELDS = [
    "arch", "broll_ingest", "capabilities", "companion_version", "completed",
    "current_project", "editor_name", "eula", "file_moves_applied", "lanes",
    "local_manifest", "machine", "machine_id", "machine_settings", "media_tree",
    "mode", "music_ingest", "platform", "proxy_coverage", "queue",
    "report_optouts", "reported_at", "resolve_journals", "resolve_project",
    "resolve_undo_applied", "sync_guard", "syncthing_device_id",
    "transport_health", "truncated", "youtube_import",
]

CAPABILITY_FIELDS = [
    "cards_agent", "claude", "cpu_count", "ffmpeg", "ffprobe", "gpu_name",
    "gpu_present", "gpu_vram_gb", "idle_seconds", "job_kinds", "jobs_enabled",
    "jobs_gate", "jobs_idle_seconds", "load", "mounts", "nvenc", "resolve",
    "volunteer_until", "whisper", "whisper_detail",
]

SYNC_GUARD_FIELDS = [
    "blocked", "clock_skew_seconds", "crashes", "disk", "disk_floor",
    "folders_unfiltered", "halt", "ingest_staging", "lane_b_breaker", "loopback",
    "moved_project_dirs", "removal_overrides", "repath_events", "reporter",
    "resolve_health", "restarts", "root_state", "rotation_seconds",
    "shared_folder_problems", "skipped_exists", "stalled", "standins_placed",
    "stray_projects", "sync_conflicts", "syncthing_supervisor", "trash",
    "upgrade", "youtube_import", "ytdlp",
]

# Dotted from the report root. Each is either identity the report cannot
# exist without, machine health, or something sync or the editor's own
# action needs (the "still sent" list in TELEMETRY.md). A field that ALSO
# has a switchable part (capabilities, sync_guard) is listed here and its
# switchable part is in FIELDS.
NOT_PERSONAL = {
    "arch": "CPU architecture, for the update channel",
    "broll_ingest": "b-roll indexing progress",
    "capabilities": "container; its switchable parts are in FIELDS",
    "companion_version": "build",
    "completed": "recently transferred file names: STILL SENT, sync needs them",
    "current_project": "the TREE project lane sync is on, not a Resolve project",
    "editor_name": "identity: the report is authenticated as this person",
    "eula": "licence version and time accepted (LG-5)",
    "file_moves_applied": "answers to moves the dashboard ordered: STILL SENT",
    "lanes": "lane states and transfer names: STILL SENT, sync needs them",
    "machine": "identity: the computer's name",
    "machine_id": "identity: the computer's minted id",
    "machine_settings": "the fleet-work settings echo (account page)",
    "mode": "wired or remote",
    "music_ingest": "music indexing progress",
    "platform": "windows or macos",
    "proxy_coverage": "proxy counts per tree project",
    "queue": "the ticked TREE projects this machine syncs",
    "report_optouts": "which switches are off (LG-1)",
    "reported_at": "the companion's clock",
    "resolve_undo_applied": "container; its detail sentence is in FIELDS (undo_detail mask)",
    "sync_guard": "container; its switchable parts are in FIELDS",
    "syncthing_device_id": "identity: the Syncthing device",
    "transport_health": "connection path and counters",
    "truncated": "set by the dashboard itself, never by the client",
    "youtube_import": "YouTube import state",
    "capabilities.cards_agent": "Timeline Cards agent: STILL SENT when the editor turns it on",
    "capabilities.claude": "tool present", "capabilities.cpu_count": "hardware",
    "capabilities.ffmpeg": "tool present", "capabilities.ffprobe": "tool present",
    "capabilities.gpu_name": "hardware", "capabilities.gpu_present": "hardware",
    "capabilities.gpu_vram_gb": "hardware", "capabilities.job_kinds": "the machine's allow-list",
    "capabilities.jobs_enabled": "setting", "capabilities.jobs_gate": "why it takes no work",
    "capabilities.jobs_idle_seconds": "setting (a threshold, not a measurement)",
    "capabilities.load": "CPU load", "capabilities.mounts": "root NAMES, never paths",
    "capabilities.nvenc": "hardware", "capabilities.resolve": "container; project is in FIELDS",
    "capabilities.volunteer_until": "a deadline the editor set",
    "capabilities.whisper": "tool present", "capabilities.whisper_detail": "tool detail",
    "sync_guard.blocked": "why nothing is moving", "sync_guard.clock_skew_seconds": "clock",
    "sync_guard.crashes": "crash counters", "sync_guard.disk": "free space",
    "sync_guard.disk_floor": "lane B latch", "sync_guard.folders_unfiltered": "Syncthing folder ids",
    "sync_guard.halt": "latch", "sync_guard.ingest_staging": "bytes and batch counts",
    "sync_guard.lane_b_breaker": "latch", "sync_guard.loopback": "8899 listener health",
    "sync_guard.removal_overrides": "a gate override on a TREE project",
    "sync_guard.repath_events": "an admin's server-side rename, followed",
    "sync_guard.reporter": "reporter health", "sync_guard.resolve_health": "container; names and paths are in FIELDS",
    "sync_guard.restarts": "watchdog counters", "sync_guard.root_state": "tree root present",
    "sync_guard.rotation_seconds": "setting", "sync_guard.shared_folder_problems": "shared folder faults",
    "sync_guard.skipped_exists": "container; the counts stay, its samples are in FIELDS", "sync_guard.stalled": "lane stall",
    "sync_guard.standins_placed": "archive-relative b-roll paths, fleet data not personal",
    "sync_guard.sync_conflicts": "container; paths are in FIELDS",
    "sync_guard.syncthing_supervisor": "Syncthing supervisor state", "sync_guard.trash": "counters",
    "sync_guard.upgrade": "last update attempt", "sync_guard.youtube_import": "import state",
    "sync_guard.ytdlp": "yt-dlp sidecar health",
}


def _switchable_roots() -> set[str]:
    """The declared fields a FIELDS path removes or rewrites whole or in part,
    as dotted names down to the model level this file pins."""
    out: set[str] = set()
    for paths in telemetry_fields.FIELDS.values():
        for path in paths:
            parts = [p[:-2] if p.endswith("[]") else p for p in path.split(".")]
            if parts[0] in ("capabilities", "sync_guard") and len(parts) > 1:
                out.add(f"{parts[0]}.{parts[1]}")
            else:
                out.add(parts[0])
    return out


def test_the_report_model_is_pinned():
    assert sorted(api.ReportIn.model_fields) == REPORT_FIELDS, FIX


def test_the_capabilities_model_is_pinned():
    assert sorted(api.CapabilitiesIn.model_fields) == CAPABILITY_FIELDS, FIX


def test_the_sync_guard_model_is_pinned():
    assert sorted(api.SyncGuardIn.model_fields) == SYNC_GUARD_FIELDS, FIX


def test_every_field_is_either_switchable_or_said_not_to_be():
    switchable = _switchable_roots()
    declared = (REPORT_FIELDS + [f"capabilities.{k}" for k in CAPABILITY_FIELDS]
                + [f"sync_guard.{k}" for k in SYNC_GUARD_FIELDS])
    unclassified = [k for k in declared if k not in switchable and k not in NOT_PERSONAL]
    assert unclassified == [], f"{unclassified}: {FIX}"
    # ...and the list names nothing that no longer exists, nor anything FIELDS
    # also covers without saying it is only a container.
    assert sorted(set(NOT_PERSONAL) - set(declared)) == [], FIX
    overlap = sorted(k for k in set(NOT_PERSONAL) & switchable
                     if "container" not in NOT_PERSONAL[k])
    assert overlap == [], f"{overlap} are in FIELDS and called not personal: {FIX}"
