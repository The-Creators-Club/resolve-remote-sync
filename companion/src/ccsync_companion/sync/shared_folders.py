"""Editor-side upkeep for the fleet-wide SHARED ASSET folders (the LUT
library at ``<local_root>/Assets/Luts``).

Every other Syncthing folder on an editor's machine exists because they
ticked a project on the dashboard, and the sequencer drives it: accept the
offer, re-assert the ignores each turn, pause it when another project's turn
comes round. A shared asset folder is the opposite shape:

  * nobody ticks it, so it is not in the selection and the sequencer's
    per-project machinery never sees it;
  * it must be online even for an editor with zero projects ticked, which is
    exactly the state in which the sequencer does nothing at all;
  * it must never be paused by the rotation, because it is not part of it --
    but it IS paused by a halt, which is not pacing but a stop, and this
    reconcile must not release what the halt paused (sync-safety-2,
    2026-08-21: see `halted`).

So it gets this: one idempotent reconcile that runs at startup and once per
sequencer pass, doing the smallest set of writes that makes the folder
correct, and NOTHING in steady state (two GETs, no config commits -- every
config write restarts and rescans the folder in Syncthing).

Ordering is the same fail-closed rule the sequencer uses: a folder is never
unpaused until its .stignore is confirmed present, because a `sendreceive`
folder with no ignores indexes and offers everything under it in both
directions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from .syncthing_admin import (
    ASSET_STIGNORE_LINES,
    SHARED_ASSET_FOLDERS,
    missing_asset_ignore_lines,
)

log = logging.getLogger("ccsync.sync.shared_folders")


def local_path_for(local_root: Path | str, rel: str) -> str:
    """The on-disk path this machine keeps a shared asset folder at.

    `rel` is posix ("Assets/Luts"); the result uses the host separator,
    because it is handed to the local Syncthing, not written into a Resolve
    project. (Canonical `P:\\` spellings are canon.py's job and do not apply
    to a Syncthing folder path.)
    """
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
    return str(Path(local_root).expanduser().joinpath(*parts))


def _is_not_found(exc: BaseException) -> bool:
    """A 404 from the Syncthing REST API -- the folder is not configured on
    this machine (yet). Duplicated from sequencer._is_not_found rather than
    imported, to keep this module free of a circular import."""
    code = getattr(exc, "code", None)
    if code == 404:
        return True
    return "404" in str(exc)


class SharedFolderManager:
    """Reconciles this machine's shared asset folders. Never raises: every
    failure is logged and retried on the next call, because none of this is
    worth stopping a sync pass over."""

    def __init__(
        self,
        admin: Any,
        local_root: Path | str,
        folders: Optional[list[tuple[str, str, str]]] = None,
        halted: Optional[Callable[[], bool]] = None,
        root_present_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.admin = admin
        self.local_root = Path(local_root).expanduser()
        # SYNC-6 (resilience sweep 2026-08-28): "is the tree actually here?"
        # -- the same callback ManifestCache takes (manifest.py). The
        # sequencer runs this reconcile at its loop head, BEFORE any root
        # check, and _accept's mkdir(parents=True) on an absent external SSD
        # creates the whole chain on the BOOT disk instead: that is exactly
        # the ghost directory at /Volumes/<Name> root_guard.probe_root exists
        # to detect, and macOS then mounts the real drive as
        # "/Volumes/SAMDISK 1" (ROOT_MISPLACED) permanently. Worse, the
        # folder is POINTED at the ghost. Absent means do nothing at all.
        self._root_present_fn = root_present_fn
        self.folders = list(SHARED_ASSET_FOLDERS if folders is None else folders)
        # "Is syncing halted on this machine?" (sync-safety-2, 2026-08-21).
        # The halt pauses folders through Syncthing's REST API and this
        # reconcile RELEASES a paused shared folder every time it runs, so
        # without this the halt could not hold the asset libraries down for
        # longer than one sequencer pass. Optional and duck-typed like every
        # other collaborator here: absent means "nothing is halted", which is
        # how this module behaved before.
        self._halted = halted
        # Ids whose reconcile has already logged a failure this run, so a
        # server that never offers the folder (an older dashboard) costs one
        # log line rather than one per pass forever. Mirrors reporter.py's
        # once-per-streak convention.
        self._error_logged: set[str] = set()

    def folder_ids(self) -> list[str]:
        """The Syncthing folder ids this manager owns.

        What the halt needs in order to pause the asset libraries too: they
        are in no selection, so `sequencer.expected_folder_slugs()` -- the
        list the halt used to walk -- does not name them, and every editor's
        tray said "Nothing is uploading, downloading or sharing" while the
        B-roll archive, the music library and the LUTs kept syncing every
        addition and modification (sync-safety-2, 2026-08-21)."""
        return [str(folder_id) for folder_id, _rel, _label in self.folders]

    def halted(self) -> bool:
        """Is syncing halted on this machine? Never raises: a check that
        cannot answer must not stop the reconcile, and the only thing it
        gates is an UNPAUSE, which staying paused is the safe side of."""
        if self._halted is None:
            return False
        try:
            return bool(self._halted())
        except Exception:
            log.debug("shared folders: the halt check failed", exc_info=True)
            return True

    def root_present(self) -> bool:
        """Is the sync tree here? (SYNC-6.) Never raises; a check that could
        not answer counts as ABSENT, because the thing it gates is a
        mkdir(parents=True) whose failure mode is a ghost tree on the boot
        disk. With no callback wired in, one plain isdir of local_root."""
        if self._root_present_fn is None:
            try:
                return self.local_root.is_dir()
            except OSError:
                return False
        try:
            return bool(self._root_present_fn())
        except Exception:
            log.debug("shared folders: the root check failed", exc_info=True)
            return False

    def _mkdir_allowed(self, want_path: str) -> bool:
        """Refuse to create a folder path whose local_root ancestor is not a
        directory (SYNC-6). The second half of the guard: root_present() is
        answered at the loop head, this one immediately before the mkdir, so
        a drive that went out in between cannot be written past."""
        try:
            if self.local_root.is_dir():
                return True
        except OSError:
            return False
        log.warning(
            "shared folders: refusing to create %s -- %s is not a directory "
            "(SYNC-6: that mkdir would build a ghost tree on the boot disk)",
            want_path, self.local_root)
        return False

    def reconcile(self) -> dict[str, str]:
        """Reconcile every shared folder. Returns {folder_id: outcome} where
        outcome is one of "ok", "accepted", "repaired", "not-offered",
        "error" -- for the log line and the tray, not for control flow.

        Returns {} untouched when the sync tree is not present (SYNC-6)."""
        if not self.root_present():
            log.debug(
                "shared folders: %s is not present -- skipping the reconcile",
                self.local_root)
            return {}
        results: dict[str, str] = {}
        for folder_id, rel, label in self.folders:
            try:
                results[folder_id] = self._reconcile_one(folder_id, rel, label)
                self._error_logged.discard(folder_id)
            except Exception as exc:
                results[folder_id] = "error"
                if folder_id not in self._error_logged:
                    self._error_logged.add(folder_id)
                    log.warning("shared folder %s: reconcile failed: %s", folder_id, exc)
                else:
                    log.debug("shared folder %s: reconcile failed: %s", folder_id, exc)
        return results

    def _reconcile_one(self, folder_id: str, rel: str, label: str) -> str:
        want_path = local_path_for(self.local_root, rel)
        try:
            folder = self.admin.get_folder(folder_id)
        except Exception as exc:
            if not _is_not_found(exc):
                raise
            return self._accept(folder_id, rel, label, want_path)

        if not isinstance(folder, dict) or not folder.get("id"):
            # Some Syncthing versions answer an unknown folder with 200 and an
            # empty body rather than 404. Treat it as absent, not as a folder
            # whose every field happens to be missing -- the latter reading
            # would PATCH a path onto a folder that does not exist.
            return self._accept(folder_id, rel, label, want_path)

        outcome = "ok"

        # Path first: a folder pointed somewhere else is not this folder, and
        # every check below would be measuring the wrong directory.
        if str(folder.get("path", "")).rstrip("/\\") != want_path.rstrip("/\\"):
            log.warning(
                "shared folder %s is at %r, re-pointing it at %r (local_root moved, or it "
                "was accepted by hand)", folder_id, folder.get("path"), want_path)
            self.admin.set_folder_path(folder_id, want_path, label)
            outcome = "repaired"

        # Versioning before ignores: ensure_versioning is a no-op on a folder
        # that already has it, and a folder that pulls-then-deletes before it
        # is set loses the file outright (the DEL-6 lesson).
        try:
            if self.admin.ensure_versioning(folder_id, folder):
                outcome = "repaired"
        except Exception:
            log.debug("shared folder %s: ensure_versioning failed", folder_id, exc_info=True)

        # delete-protection (2026-08-11, docs/delete-protection-ignoredelete.md):
        # this library reaches every machine in the fleet with no tick to opt
        # out of, so one editor deleting a LUT they did not recognise would
        # otherwise take it off the NAS and off everyone else. Reuses the
        # config fetched above, so steady state stays at zero config writes.
        try:
            if self.admin.ensure_ignore_delete(folder_id, folder):
                outcome = "repaired"
        except Exception:
            log.debug("shared folder %s: ensure_ignore_delete failed", folder_id, exc_info=True)

        ignores_ok = self._ensure_ignores(folder_id)
        if ignores_ok == "repaired":
            outcome = "repaired"

        # Unpause LAST, and only with the ignores confirmed. The sequencer
        # never pauses this folder (it is not in any selection), but a
        # previous companion's crash, a hand-pause in the GUI, or the
        # accept path below can leave it paused.
        if folder.get("paused") and self.halted():
            # A halt is a deliberate stop, and this reconcile is the one
            # thing that would undo it for these folders -- including a
            # shared folder an admin paused by hand (sync-safety-2).
            log.info(
                "shared folder %s stays paused: syncing is stopped on this machine",
                folder_id)
        elif folder.get("paused") and ignores_ok != "unconfirmed":
            log.info("shared folder %s was paused -- releasing it", folder_id)
            self.admin.set_folder_paused(folder_id, False)
            outcome = "repaired"
        elif folder.get("paused"):
            log.warning(
                "shared folder %s stays paused: its .stignore could not be confirmed, and "
                "an unfiltered sendreceive folder must not go online", folder_id)

        return outcome

    def _ensure_ignores(self, folder_id: str) -> str:
        """"ok" | "repaired" | "unconfirmed". Re-asserts only when a line is
        actually missing, so steady state costs one GET and no config write.

        Missing-lines rather than byte-equality, exactly like
        missing_ignore_lines: the dashboard collector rewrites the server
        side's copy of this list every provision cycle, and a stricter
        comparison here would make the two ends rewrite the file at each
        other forever.
        """
        try:
            fetched = self.admin.get_ignores(folder_id)
        except Exception as exc:
            log.warning("shared folder %s: could not read its ignores (%s)", folder_id, exc)
            return "unconfirmed"
        missing = missing_asset_ignore_lines(fetched)
        if not missing:
            return "ok"
        log.warning(
            "shared folder %s is missing %d of its %d ignore patterns (e.g. %s) -- re-asserting",
            folder_id, len(missing), len(ASSET_STIGNORE_LINES), ", ".join(missing[:3]))
        try:
            self.admin.set_ignores(folder_id, list(ASSET_STIGNORE_LINES))
        except Exception as exc:
            log.warning("shared folder %s: re-asserting ignores failed: %s", folder_id, exc)
            return "unconfirmed"
        return "repaired"

    def _accept(self, folder_id: str, rel: str, label: str, want_path: str) -> str:
        """Accept the server's offer of this folder, if it has made one.

        Unlike a project folder there is no tick to check first: the server
        only ever offers a shared asset folder to a device it has decided
        should have it, so the offer IS the authorisation. What is still
        checked is that the offer came from a device this machine is actually
        paired with -- accept_folder writes the offering device into the
        folder config, so accepting an offer from an unknown device would
        pair us to it.
        """
        try:
            pending = self.admin.pending_folders() or {}
        except Exception as exc:
            log.debug("shared folder %s: could not read pending folders: %s", folder_id, exc)
            return "not-offered"
        entry = pending.get(folder_id) if isinstance(pending, dict) else None
        offered_by = list((entry or {}).get("offeredBy", {}) or {})
        if not offered_by:
            # Routine before the dashboard's first provision cycle reaches
            # this device, and permanent on a machine the server has not
            # shared the library with. Debug, not warning.
            log.debug("shared folder %s has not been offered to this device yet", folder_id)
            return "not-offered"

        device_id = str(offered_by[0])
        log.info(
            "accepting shared asset folder %s (%s) from %s at %s",
            folder_id, label, device_id, want_path)
        if not self._mkdir_allowed(want_path):
            return "error"
        # The directory must exist before Syncthing takes the folder online:
        # a missing path is a folder error state, not an empty folder.
        try:
            Path(want_path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("shared folder %s: could not create %s: %s", folder_id, want_path, exc)
            return "error"
        self.admin.accept_folder(
            folder_id, label, want_path, device_id, ignore_lines=list(ASSET_STIGNORE_LINES)
        )
        return "accepted"
