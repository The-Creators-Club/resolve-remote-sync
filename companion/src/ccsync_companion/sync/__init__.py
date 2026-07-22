"""Sync orchestrator — Component 3 of SPEC.md's companion app.

Three lanes behind a common adapter interface (see base.py):
  - rclone_lane.py — Lane A (video originals, up) and Lane B (proxies, down),
    both wrap the same rclone-subprocess machinery with different filters
    and direction.
  - syncthing_lane.py — Lane C (everything else, bidirectional), supervises
    a locally-running Syncthing instance via its REST API.
"""
