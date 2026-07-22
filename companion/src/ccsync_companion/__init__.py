"""ccsync-companion — editor-side agent for the Creators Club Resolve remote-sync system.

Tray app + three supervised daemons (per SPEC.md, Architecture + Components §2):

  1. watcher.py   — polls the current Resolve timeline, classifies every clip
                     path as OK / OUT_OF_TREE / BAD_PREFIX.
  2. fixer.py/popup.py — one dialog per batch of OUT_OF_TREE clips, "Fix all"
                     copies + relinks (never moves/deletes originals).
  3. sync/        — three lane adapters (rclone up, rclone down, Syncthing)
                     behind a common LaneAdapter interface.

See README.md in this directory for the architecture writeup and config
reference.
"""

from .config import VERSION

__all__ = ["VERSION"]
