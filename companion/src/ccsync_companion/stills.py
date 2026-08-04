"""Put every machine's Resolve gallery in the same, shared place.

Resolve keeps gallery stills (the Stills tab on the Color page, including
the PowerGrade album) in a directory it derives, not one you name directly:

    <Site.1.FS.<System.Gallery.DtMgr.FileSys>.Root> / <System.Gallery.Folder>

`FileSys` is a 1-based index into the **media storage list**, so the stills
location is a consequence of which media storage entry that index happens to
name. Out of the box it is entry 1 -- each machine's own scratch disk -- and
those are different everywhere by definition:

    base rig    G:\\Resolve Media\\.gallery
    Leso's Mac  /Users/leso/Movies/.gallery

Machines sharing a project database are expected to agree, which is what
produces the "stills location is not the same" complaint at launch.

The fix is to give every machine a media storage entry pointing at the same
shared directory -- ``P:\\Assets\\Stills``, synced like the LUT library -- and
to point the gallery index at that entry instead of at entry 1. On a Mac,
which has no ``P:``, the entry carries the real local path plus a
``MappedRoot`` of ``P:\\Assets\\Stills``: exactly the mechanism SPEC.md flaw 7
describes for the tree itself, so the shared database sees the same
``P:\\`` string from every machine.

Entry 1 is never touched: it is the scratch disk, and ``RenderCaching.FsNo``
points at it by index. The new entry goes in front of Resolve's own trailing
filesystem entry, which it expects last.

Both preference files, and only while Resolve is quit -- see resolve_prefs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from . import resolve_prefs

log = logging.getLogger("ccsync.stills")

# Where the shared gallery lives under local_root, and the Syncthing folder
# that carries it.
LIBRARY_REL = ("Assets", "Stills")
GALLERY_FOLDER = ".gallery"


def stills_dir(local_root: Path | str) -> Path:
    return Path(local_root).expanduser().joinpath(*LIBRARY_REL)


def canonical_stills_path(cfg: dict[str, Any]) -> str:
    """The ``P:\\Assets\\Stills`` form -- what the shared project database
    sees, and so the string that has to match between machines."""
    prefix = str((cfg or {}).get("canonical_prefix", "P:\\") or "P:\\").strip()
    return prefix.rstrip("\\/") + "\\" + "\\".join(LIBRARY_REL)


def desired_entry(cfg: dict[str, Any], local_root: Path | str,
                  windows: Optional[bool] = None) -> tuple[str, str]:
    """(root, mapped_root) for this machine's media storage entry.

    On Windows the canonical path IS the real path, so there is nothing to
    map and `mapped_root` is empty -- adding one would make Resolve map a
    drive onto itself. On macOS the real local path carries a `MappedRoot`
    so the database still sees the canonical spelling.
    """
    if windows is None:
        windows = os.name == "nt"
    canonical = canonical_stills_path(cfg)
    if windows:
        return canonical, ""
    return str(stills_dir(local_root)), canonical


class StillsManager:
    """Idempotent reconcile of the gallery location. Never raises."""

    def __init__(
        self,
        cfg: dict[str, Any],
        local_root: Path | str,
        prefs_factory=None,
        windows: Optional[bool] = None,
    ) -> None:
        self.cfg = cfg or {}
        self.local_root = Path(local_root).expanduser()
        self._prefs_factory = prefs_factory or resolve_prefs.ResolvePrefs
        # A parameter rather than a bare os.name check, for the same reason
        # luts.library_location_string takes one: the two platforms want
        # DIFFERENT entries (Windows the canonical path with no mapping,
        # macOS the real path plus a MappedRoot), and that difference is
        # exactly what a single-platform test run cannot see.
        self._windows = windows
        self._warned: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("stills_sync_enabled", True))

    def stills_dir(self) -> Path:
        return stills_dir(self.local_root)

    def check(self) -> dict[str, Any]:
        """Point the gallery at the shared stills directory.

        Returns {"status", "changed", "message", "path"}. Waits rather than
        acting when the directory has not synced yet: repointing the gallery
        at a directory that does not exist would take an editor's stills
        offline, which is worse than the mismatch warning.
        """
        if not self.enabled:
            return self._report("disabled", False, "")
        target = self.stills_dir()
        if not target.is_dir():
            return self._report(
                "no-library", False,
                f"the shared stills folder {target} has not synced to this machine yet")

        root, mapped_root = desired_entry(self.cfg, self.local_root, self._windows)
        try:
            prefs = self._prefs_factory()
        except resolve_prefs.PrefsError as exc:
            return self._report(exc.status, False, exc.message)
        except Exception as exc:
            log.debug("stills: could not read Resolve preferences", exc_info=True)
            return self._report("error", False, str(exc))

        try:
            current = prefs.gallery_location()
            if resolve_prefs._normcase(current.get("root", "")) == resolve_prefs._normcase(root) \
                    and current.get("folder") == GALLERY_FOLDER:
                return self._report(resolve_prefs.ALREADY, False, "")

            status, index = prefs.ensure_media_storage(root, mapped_root)
            if status in (resolve_prefs.RESOLVE_RUNNING, resolve_prefs.FORMAT_UNRECOGNISED):
                return self._report(status, False, self._blocked_message(status, root))
            # ensure_media_storage may have written; re-read so the gallery
            # write sees the entry it is about to point at.
            prefs = self._prefs_factory()
            gallery_status = prefs.set_gallery_filesys(index, GALLERY_FOLDER)
        except resolve_prefs.PrefsError as exc:
            return self._report(exc.status, False, exc.message)
        except Exception as exc:
            log.debug("stills: could not set the gallery location", exc_info=True)
            return self._report("error", False, str(exc))

        if gallery_status == resolve_prefs.OK:
            log.info("stills: gallery now points at %s (media storage entry %d)", root, index)
            self._warned.clear()
            return self._report(gallery_status, True, f"gallery moved to {root}\\{GALLERY_FOLDER}")
        if gallery_status in (resolve_prefs.RESOLVE_RUNNING, resolve_prefs.FORMAT_UNRECOGNISED):
            return self._report(gallery_status, False, self._blocked_message(gallery_status, root))
        return self._report(gallery_status, False, "")

    @staticmethod
    def _blocked_message(status: str, root: str) -> str:
        if status == resolve_prefs.RESOLVE_RUNNING:
            return (
                "Resolve is running -- the shared stills location will be set the next time "
                "it is closed (Resolve overwrites its own preferences on exit)"
            )
        return (
            "Resolve's preference files are not in the expected shape -- add "
            f"{root} as a media storage location by hand, and set the gallery to it"
        )

    def _report(self, status: str, changed: bool, message: str) -> dict[str, Any]:
        if message and status not in self._warned:
            self._warned.add(status)
            log.warning("stills: %s", message)
        return {"status": status, "changed": changed, "message": message,
                "path": str(self.stills_dir())}
