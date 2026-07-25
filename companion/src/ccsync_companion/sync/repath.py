"""Local auto-repath for server-side project moves (added 2026-07-25).

When a project directory is moved/renamed on the NAS, the dashboard keeps
its slug (the immutable identity from the .ccsync-project marker) and
retargets the SERVER Syncthing folder. This module is the editor-side half:
for each selected project, compare where the LOCAL Syncthing folder points
(its `path` in the local Syncthing config) against where the fresh
selection says it should live (local_root/Projects/<rel_path>). A mismatch
means the project moved server-side -- so move the local directory to match
and re-point the local folder.

Deliberately STATELESS: the local Syncthing config *is* the persisted
state. That closes the seeding gap -- a fresh install, an editor offline
through several moves, or an upgrade from a pre-repath companion all
converge on first reconcile, because there's no history file to be missing.

Order matters for lane A safety: the sequencer calls reconcile() BEFORE
running lanes each pass, so rclone never re-uploads the old tree to the
NAS's (now nonexistent) old path.

Never-raise ethos, injectable collaborators -- same conventions as the
rest of sync/.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from .syncthing_admin import SyncthingAdmin

log = logging.getLogger("ccsync.sync.repath")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


class ProjectRepather:
    def __init__(
        self,
        admin: SyncthingAdmin,
        local_root: str,
        move_fn: Callable[[str, str], Any] = os.renames,
    ) -> None:
        self.admin = admin
        self.local_root = local_root
        self._move = move_fn

    def reconcile(self, selection: list[dict]) -> list[str]:
        """Repath every selected project whose local folder points somewhere
        other than local_root/Projects/<rel_path>. Returns the slugs that
        were repathed. Never raises; per-project failures are logged and the
        folder is always unpaused again."""
        repathed: list[str] = []
        try:
            config = self.admin.get_config() or {}
            folders = {f.get("id"): f for f in config.get("folders", [])}
        except Exception:
            log.debug("repath: local syncthing unreachable -- skipping reconcile")
            return repathed

        for item in selection or []:
            slug = item.get("slug")
            rel = str(item.get("rel_path", "")).strip().strip("/")
            if not slug or not rel:
                continue
            folder = folders.get(slug)
            if folder is None:
                continue  # not accepted locally yet -- the accept flow owns creation
            actual = str(folder.get("path", ""))
            expected = str(Path(self.local_root) / "Projects" / Path(*rel.split("/")))
            if not actual or _norm(actual) == _norm(expected):
                continue

            log.warning(
                "repath: project %s moved server-side -- local %s -> %s",
                slug, actual, expected,
            )
            try:
                self.admin.set_folder_paused(slug, True)
            except Exception:
                log.exception("repath: could not pause folder %s -- skipping this cycle", slug)
                continue
            try:
                self._move_dir(slug, actual, expected)
                try:
                    self.admin.set_folder_path(slug, expected, label=rel)
                    repathed.append(slug)
                except Exception:
                    log.exception("repath: could not re-point folder %s", slug)
            finally:
                try:
                    self.admin.set_folder_paused(slug, False)
                except Exception:
                    log.exception("repath: could not unpause folder %s", slug)
        return repathed

    def _move_dir(self, slug: str, actual: str, expected: str) -> None:
        """Filesystem half. Missing source = nothing to move (re-point only).
        Target already exists = conflict: skip the move but still re-point
        -- lane C re-fills the folder's (small, non-video) files, and the
        old directory is left for a human to reconcile."""
        src = Path(actual)
        dst = Path(expected)
        if not src.is_dir():
            log.info("repath: %s -- old local dir %s absent, re-pointing only", slug, src)
            return
        if dst.exists():
            log.warning(
                "repath: %s -- target %s already exists; leaving old dir %s in place "
                "(reconcile by hand), re-pointing the folder anyway", slug, dst, src,
            )
            return
        try:
            self._move(str(src), str(dst))
            log.info("repath: moved %s -> %s", src, dst)
        except OSError:
            log.exception("repath: move failed for %s (re-pointing anyway)", slug)
