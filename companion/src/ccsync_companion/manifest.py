"""Local disk media manifest -- per-project rollups (and, for
selected/current projects, per-file lists) of video originals and proxies
found under local_root, reported to the dashboard alongside the media pool
BIN tree (see app.py:get_media_tree) and rclone transfer progress.

Deliberately filesystem-scan-only (no Resolve dependency): it answers "what
video media actually exists on disk right now", independent of what's
imported into any Resolve project. Reuses fixer.list_project_dirs() for the
same Projects/<year>/<series>/<project> discovery the rest of the companion
uses, and sync.rclone_lane.VIDEO_EXTS for the same "what counts as a video
file" definition as the sync lanes -- only extensions in that list are
counted; everything else (audio, stills, project files, etc.) is skipped.

Never raises: a bad/missing local_root just yields fewer (or no) entries,
matching the never-raise ethos used throughout this package.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import fixer
from .sync import rclone_lane

log = logging.getLogger("ccsync.manifest")

# Per-project cap on per-file list entries (originals/proxies each) -- a
# project with a huge shoot could otherwise blow the payload up hugely.
# Rollup counts/bytes are always exact regardless of this cap; only the
# per-file lists get truncated.
MAX_PER_FILE_ENTRIES = 2000

# Cap on the NUMBER OF PROJECTS reported (KNOWN_BUGS B6). This module used to
# emit one key per marker-bearing dir with no cap at all, while the dashboard
# capped `local_manifest` at 64 keys with a RAISING pydantic validator -- so a
# 65th project 422'd the entire heavy report and, because an idle companion
# only ever sends heavy ticks, took this machine off the fleet grid completely.
# Worst placed is the BASE RIG, whose local_root is the whole NAS tree at P:\
# -- it hits 64 first and holds the authoritative copy of everything.
#
# The dashboard now truncates rather than rejecting (api.MAX_REPORT_PROJECTS),
# so this is no longer load-bearing for availability -- but capping HERE is
# what decides WHICH 64 survive, and it also saves walking 200 project dirs
# every refresh. Keep the value in step with api.MAX_REPORT_PROJECTS.
MAX_PROJECTS = 64

GetSelectedRelsFn = Callable[[], Optional[set]]

# Module-level so the "reported fewer projects than exist" warning fires on a
# CHANGE rather than every refresh_interval forever (the warn-once pattern
# used in reporter.py/watcher.py). None = nothing logged yet.
_last_truncation_logged: Optional[int] = None


def _is_proxy_path(rel_parts: tuple) -> bool:
    return any(part.lower() == "proxy" for part in rel_parts)


def _project_priority(local_root: str, project_rel: str, selected_rels: Optional[set]):
    """Sort key deciding which projects survive MAX_PROJECTS.

    Selected projects first -- they are the ones the editor is actually
    syncing, and the ones whose per-file lists the dashboard's presence view
    needs. Then most-recently-touched, so an active shoot outranks a 2019
    archive on a base rig holding hundreds. `rel` last, purely so the order is
    stable/deterministic between refreshes.
    """
    selected = 0 if (selected_rels is not None and project_rel in selected_rels) else 1
    try:
        mtime = os.stat(
            os.path.join(local_root, "Projects", project_rel.replace("/", os.sep))
        ).st_mtime
    except OSError:
        mtime = 0.0
    return (selected, -mtime, project_rel)


def prioritize_project_rels(
    local_root: str, project_rels: list[str], selected_rels: Optional[set] = None,
    max_projects: int = MAX_PROJECTS,
) -> tuple[list[str], int]:
    """(the rels to report, how many were dropped). Never raises."""
    if len(project_rels) <= max_projects:
        return list(project_rels), 0
    ordered = sorted(
        project_rels, key=lambda rel: _project_priority(local_root, rel, selected_rels)
    )
    return ordered[:max_projects], len(project_rels) - max_projects


def scan_local_manifest(
    local_root: str,
    selected_rels: Optional[set] = None,
    size_fn: Callable[[str], int] = os.path.getsize,
) -> dict[str, dict[str, Any]]:
    """Walk every project dir under local_root and build the manifest dict.

    `selected_rels`, if given, is the set of project_rel strings ("<year>/
    <series>/<project>") for which per-file lists should be populated --
    every other project still gets exact rollups, just with originals/
    proxies=None. `selected_rels=None` means every project is rollup-only.
    """
    global _last_truncation_logged

    result: dict[str, dict[str, Any]] = {}
    # Selection rels union in so a just-selected project whose marker file
    # hasn't synced down yet still gets a rollup (see fixer.list_project_dirs).
    project_rels = fixer.list_project_dirs(local_root, extra_rels=selected_rels or ())
    # B6: cap the project COUNT, keeping the ones that matter (see
    # prioritize_project_rels). Applied before the walk, so the dropped
    # projects cost nothing to skip.
    project_rels, dropped = prioritize_project_rels(
        local_root, project_rels, selected_rels
    )
    if dropped != _last_truncation_logged:
        _last_truncation_logged = dropped
        if dropped:
            log.warning(
                "media manifest reports %d of %d project(s): the dashboard accepts at most "
                "%d per report (B6). Ticked projects and the most recently touched are kept; "
                "%d older project(s) are not in this machine's presence data.",
                len(project_rels), len(project_rels) + dropped, MAX_PROJECTS, dropped,
            )
        else:
            log.info("media manifest is no longer truncated (%d project(s))",
                     len(project_rels))
    for project_rel in project_rels:
        project_dir = Path(local_root) / "Projects" / project_rel.replace("/", os.sep)
        include_files = selected_rels is not None and project_rel in selected_rels

        n_originals = 0
        bytes_originals = 0
        n_proxies = 0
        bytes_proxies = 0
        originals: Optional[list] = [] if include_files else None
        proxies: Optional[list] = [] if include_files else None
        truncated = False

        for dirpath, _dirnames, filenames in os.walk(project_dir):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in rclone_lane.VIDEO_EXTS:
                    continue
                file_path = os.path.join(dirpath, filename)
                try:
                    rel = Path(file_path).relative_to(project_dir)
                except ValueError:
                    continue
                try:
                    size = size_fn(file_path)
                except OSError:
                    continue

                is_proxy = _is_proxy_path(rel.parts)
                if is_proxy:
                    n_proxies += 1
                    bytes_proxies += size
                    if proxies is not None:
                        if len(proxies) < MAX_PER_FILE_ENTRIES:
                            proxies.append([rel.as_posix(), size])
                        else:
                            truncated = True
                else:
                    n_originals += 1
                    bytes_originals += size
                    if originals is not None:
                        if len(originals) < MAX_PER_FILE_ENTRIES:
                            originals.append([rel.as_posix(), size])
                        else:
                            truncated = True

        result[project_rel] = {
            "n_originals": n_originals,
            "bytes_originals": bytes_originals,
            "n_proxies": n_proxies,
            "bytes_proxies": bytes_proxies,
            "truncated": truncated,
            "originals": originals,
            "proxies": proxies,
        }
    return result


class ManifestCache:
    """Background daemon thread that periodically rescans the local manifest
    and caches the result -- get() is always cheap/non-blocking (never walks
    the filesystem inline) and never raises, matching the fault-isolated
    background-loop pattern used by reporter.py / sync/*_lane.py."""

    def __init__(
        self,
        cfg: dict[str, Any],
        get_selected_rels: Optional[GetSelectedRelsFn] = None,
        size_fn: Callable[[str], int] = os.path.getsize,
    ) -> None:
        self.cfg = cfg
        self.local_root = cfg.get("local_root", "")
        # coerce_numeric, not float(): ManifestCache is constructed inside
        # CompanionApp.__init__, so a hand-edited "5m" here took the windowed
        # exe down with no tray and no log line (AUDIT_2 CORE-M4's family).
        self.refresh_interval = config_mod.coerce_numeric(cfg, "manifest_refresh_interval", 300)
        self._get_selected_rels = get_selected_rels
        self._size_fn = size_fn

        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ccsync-manifest-cache", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def get(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._cache)

    def refresh_once(self) -> None:
        """Rescan and update the cache. Never raises."""
        try:
            selected_rels = None
            if self._get_selected_rels is not None:
                selected_rels = self._get_selected_rels()
            scanned = scan_local_manifest(self.local_root, selected_rels, self._size_fn)
        except Exception:
            log.exception("manifest cache: refresh failed")
            return
        with self._lock:
            self._cache = scanned

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self.refresh_once()
            if self._stop_event.wait(self.refresh_interval):
                break
