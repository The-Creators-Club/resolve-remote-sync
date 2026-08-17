"""Sync orchestrator — Component 3 of SPEC.md's companion app.

Three lanes behind a common adapter interface (see base.py):
  - rclone_lane.py — Lane A (video originals, up) and Lane B (proxies, down),
    both wrap the same rclone-subprocess machinery with different filters
    and direction.
  - syncthing_lane.py — Lane C (everything else, bidirectional), supervises
    a locally-running Syncthing instance via its REST API.
  - lane_guard.py — the safety latches that sit ACROSS the lanes rather than
    inside one: lane B's circuit breaker, `.ccsync-trash` retention, and the
    "stop all sync" halt (COMMERCIAL_READINESS.md item 9, 2026-08-17). All
    three persist to <state_dir>, because a latch that a tray restart clears
    is not a latch. See docs/SYNC_SAFETY.md.
"""
