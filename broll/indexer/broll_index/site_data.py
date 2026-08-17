"""Where this installation's own catalogue data lives — outside the git tree.

The queue config names 25 of one customer's projects (episode titles, drives,
camera bodies) and the duplicates report lists ~450 of their archive filenames.
Both were tracked until 2026-08-17, when they moved to `private/` at the repo
root and the directory was git-ignored (COMMERCIAL_READINESS.md item 10 /
section B: client business data must not ship with the product).

Resolved from `__file__`, never from the cwd: these scripts are launched from
`broll/indexer` by hand, from the repo root by tooling, and by watchdog.ps1
with its own `-WorkingDirectory`, and a cwd-relative default silently picks a
different file (or none) in each. Nothing here is required to exist — every
caller takes an explicit `--config` / `--out`, and a site that has no
`private/` gets a FileNotFoundError naming the full path it wanted.
"""

from __future__ import annotations

from pathlib import Path

# broll_index/ -> indexer/ -> broll/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_DIR = REPO_ROOT / "private"

DEFAULT_QUEUE_CONFIG = str(PRIVATE_DIR / "broll" / "indexer" / "config.queue.yaml")
DEFAULT_DUPLICATES_REPORT = str(PRIVATE_DIR / "broll" / "indexer" / "duplicates_report.md")
