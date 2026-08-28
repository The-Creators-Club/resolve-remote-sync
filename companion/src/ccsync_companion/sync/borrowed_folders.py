"""Editor-side upkeep for BORROWED lender folders (SHARED_FOLDERS_PLAN.md
§3.3, 2026-08-24).

A project this machine has ticked may declare that it borrows a folder from
another project (`includes` in the selection response). Lanes A and B just
run a deeper subpath inside the borrower's turn, but lane C cannot: a second
Syncthing folder inside the lender is exactly what the dashboard's collector
refuses ("projects cannot nest"), and its .stfolder would sync into every
other copy of the lender. So the dashboard shares the LENDER's own folder
(id = lender slug) with the borrowing device, and this manager accepts it at
the lender's true path with a device-local .stignore that admits only the
borrowed subtrees (syncthing_admin.restricted_ignore_lines).

Modelled on shared_folders.SharedFolderManager, and the same three rules:

  * one idempotent reconcile per sequencer pass plus startup, with nothing
    but reads in steady state;
  * a folder is never unpaused until its ignores are confirmed -- here that
    means confirmed RESTRICTED: a lender folder online with the plain
    project ignores would pull the lender's every non-video file to a
    machine that never ticked it;
  * a halt is a stop, not pacing -- this reconcile must not release what a
    halt paused.

A lender the editor then TICKS leaves this manager's set (the sequencer's
`borrowed_lenders()` only names lenders outside the selection) and becomes a
normal selected folder; the sequencer's restriction check rewrites the full
STIGNORE_LINES before that folder is ever unpaused. A lender whose last
borrower is unticked has its local folder CONFIG removed; files on disk
stay (the tray's remove flow is the only thing that deletes local copies).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from .syncthing_admin import is_restricted, restricted_ignore_lines

log = logging.getLogger("ccsync.sync.borrowed_folders")


def local_path_for(local_root: Path | str, lender_rel: str) -> str:
    """`<local_root>/Projects/<lender_rel>` in the host's separators -- the
    lender's ONE true path (D2), the same place it would live if ticked."""
    parts = ["Projects"] + [p for p in str(lender_rel).replace("\\", "/").split("/") if p]
    return str(Path(local_root).expanduser().joinpath(*parts))


def _is_not_found(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    if code == 404:
        return True
    return "404" in str(exc)


class BorrowedFolderManager:
    """Reconciles the lender folders this machine borrows from. Never
    raises: every failure is logged and retried next pass."""

    def __init__(
        self,
        admin: Any,
        local_root: Path | str,
        lenders_fn: Callable[[], dict],
        selected_slugs_fn: Optional[Callable[[], list]] = None,
        halted: Optional[Callable[[], bool]] = None,
        move_dir: Optional[Callable[[str, str], None]] = None,
        root_present_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.admin = admin
        self.local_root = Path(local_root).expanduser()
        # sequencer.borrowed_lenders: lender_slug -> {"rel", "subs",
        # "borrowers"} for lenders NOT in the selection.
        self.lenders_fn = lenders_fn
        # sequencer.expected_folder_slugs: what the drop path must never
        # touch -- a lender the editor just ticked belongs to the sequencer.
        self.selected_slugs_fn = selected_slugs_fn
        self._halted = halted
        self._move_dir = move_dir
        # SYNC-6 (resilience sweep 2026-08-28): see SharedFolderManager for
        # the whole story. This reconcile runs at the sequencer's loop head,
        # before any root check, and both _accept and _repoint end in a
        # mkdir(parents=True) that would build the tree on the boot disk
        # while the external SSD is out -- and then point a Syncthing folder
        # at it.
        self._root_present_fn = root_present_fn
        self._error_logged: set[str] = set()

    def folder_ids(self) -> list[str]:
        try:
            return [str(s) for s in self.lenders_fn()]
        except Exception:
            return []

    def halted(self) -> bool:
        if self._halted is None:
            return False
        try:
            return bool(self._halted())
        except Exception:
            log.debug("borrowed folders: the halt check failed", exc_info=True)
            return True

    def root_present(self) -> bool:
        """Is the sync tree here? (SYNC-6.) Never raises; unanswerable counts
        as ABSENT, because what it gates is a mkdir into a ghost tree."""
        if self._root_present_fn is None:
            try:
                return self.local_root.is_dir()
            except OSError:
                return False
        try:
            return bool(self._root_present_fn())
        except Exception:
            log.debug("borrowed folders: the root check failed", exc_info=True)
            return False

    def _mkdir_allowed(self, want_path: str) -> bool:
        """Refuse a mkdir whose local_root ancestor is not a directory
        (SYNC-6): the drive can go out between the loop-head check and here."""
        try:
            if self.local_root.is_dir():
                return True
        except OSError:
            return False
        log.warning(
            "borrowed folders: refusing to create %s -- %s is not a directory "
            "(SYNC-6: that mkdir would build a ghost tree on the boot disk)",
            want_path, self.local_root)
        return False

    def reconcile(self) -> dict[str, str]:
        """Reconcile every borrowed lender folder. Returns {lender_slug:
        outcome} for the log and the tray, not for control flow.

        Returns {} untouched when the sync tree is not present (SYNC-6):
        nothing here, including the drop path, is worth doing against a root
        that is not on the machine."""
        if not self.root_present():
            log.debug("borrowed folders: %s is not present -- skipping the reconcile",
                      self.local_root)
            return {}
        try:
            lenders = dict(self.lenders_fn() or {})
        except Exception:
            log.debug("borrowed folders: could not read the lender set", exc_info=True)
            return {}
        results: dict[str, str] = {}
        for slug, rec in lenders.items():
            try:
                results[slug] = self._reconcile_one(str(slug), rec)
                self._error_logged.discard(slug)
            except Exception as exc:
                results[slug] = "error"
                if slug not in self._error_logged:
                    self._error_logged.add(slug)
                    log.warning("borrowed folder %s: reconcile failed: %s", slug, exc)
                else:
                    log.debug("borrowed folder %s: reconcile failed: %s", slug, exc)
        self._drop_unborrowed(set(lenders))
        return results

    def _reconcile_one(self, slug: str, rec: dict) -> str:
        rel = str(rec.get("rel") or "")
        subs = [str(s) for s in rec.get("subs") or [] if str(s).strip()]
        if not rel or not subs:
            return "invalid"
        want_path = local_path_for(self.local_root, rel)
        # The negations address paths relative to the FOLDER root (the
        # lender dir), so they are the sub rels alone.
        want_ignores = restricted_ignore_lines(subs)

        try:
            folder = self.admin.get_folder(slug)
        except Exception as exc:
            if not _is_not_found(exc):
                raise
            return self._accept(slug, rel, want_path, want_ignores)
        if not isinstance(folder, dict) or not folder.get("id"):
            return self._accept(slug, rel, want_path, want_ignores)

        outcome = "ok"

        # Path first (lender moved on the NAS: the server re-resolved the
        # include, the label changed, and the selection now spells the new
        # rel). Move the local partial dir when it exists at the old path
        # and nothing sits at the new one, exactly as repath does for a
        # selected project.
        old_path = str(folder.get("path", "")).rstrip("/\\")
        if old_path != want_path.rstrip("/\\"):
            self._repoint(slug, old_path, want_path, rel)
            outcome = "repaired"

        try:
            if self.admin.ensure_versioning(slug, folder):
                outcome = "repaired"
        except Exception:
            log.debug("borrowed folder %s: ensure_versioning failed", slug, exc_info=True)
        try:
            if self.admin.ensure_ignore_delete(slug, folder):
                outcome = "repaired"
        except Exception:
            log.debug("borrowed folder %s: ensure_ignore_delete failed", slug, exc_info=True)

        ignores_ok = self._ensure_ignores(slug, want_ignores)
        if ignores_ok == "repaired":
            outcome = "repaired"

        if folder.get("paused") and self.halted():
            log.info("borrowed folder %s stays paused: syncing is stopped on this machine",
                     slug)
        elif folder.get("paused") and ignores_ok != "unconfirmed":
            log.info("borrowed folder %s was paused -- releasing it", slug)
            self.admin.set_folder_paused(slug, False)
            outcome = "repaired"
        elif folder.get("paused"):
            log.warning(
                "borrowed folder %s stays paused: its restricted .stignore could not be "
                "confirmed, and the lender's whole folder must not go online here", slug)
        return outcome

    def _repoint(self, slug: str, old_path: str, want_path: str, rel: str) -> None:
        if not self._mkdir_allowed(want_path):
            # Leave the folder pointed where it is: a re-point at a path we
            # cannot create is worse than a stale one (SYNC-6).
            return
        log.warning("borrowed folder %s is at %r, re-pointing it at %r (the lender moved "
                    "on the NAS)", slug, old_path, want_path)
        try:
            self.admin.set_folder_paused(slug, True)
        except Exception:
            log.debug("borrowed folder %s: pause before re-point failed", slug, exc_info=True)
        if (self._move_dir is not None and old_path
                and Path(old_path).is_dir() and not Path(want_path).exists()):
            try:
                self._move_dir(old_path, want_path)
            except Exception:
                log.warning("borrowed folder %s: could not move %s -> %s; re-pointing "
                            "anyway (Syncthing will re-pull the subtree)",
                            slug, old_path, want_path, exc_info=True)
        Path(want_path).mkdir(parents=True, exist_ok=True)
        self.admin.set_folder_path(slug, want_path, rel)

    def _ensure_ignores(self, slug: str, want_ignores: list[str]) -> str:
        """"ok" | "repaired" | "unconfirmed". The check is BOTH halves:
        every wanted line present AND the list actually restricted -- a
        lender folder here must never run on the plain project list."""
        try:
            fetched = self.admin.get_ignores(slug)
        except Exception as exc:
            log.warning("borrowed folder %s: could not read its ignores (%s)", slug, exc)
            return "unconfirmed"
        lines = fetched.get("ignore") if isinstance(fetched, dict) else fetched
        present = {str(line).strip() for line in lines} if isinstance(
            lines, (list, tuple)) else set()
        missing = [want for want in want_ignores if want not in present]
        if not missing and is_restricted(fetched):
            note = getattr(self.admin, "note_ignores_confirmed", None)
            if note is not None:
                try:
                    note(slug)
                except Exception:
                    log.debug("borrowed folder %s: note_ignores_confirmed failed",
                              slug, exc_info=True)
            return "ok"
        log.warning(
            "borrowed folder %s: .stignore is %s -- re-asserting the restricted list",
            slug,
            f"missing {len(missing)} line(s) (e.g. {', '.join(missing[:3])})"
            if missing else "not restricted")
        try:
            self.admin.set_ignores(slug, want_ignores)
        except Exception as exc:
            log.warning("borrowed folder %s: re-asserting restricted ignores failed: %s",
                        slug, exc)
            return "unconfirmed"
        return "repaired"

    def _accept(self, slug: str, rel: str, want_path: str, want_ignores: list[str]) -> str:
        """Accept the server's offer of the lender's folder, restricted
        BEFORE it can pull anything (accept_folder creates paused, sets the
        ignores, then unpauses -- the same no-unfiltered-window guarantee a
        project accept has, with the tighter list)."""
        try:
            pending = self.admin.pending_folders() or {}
        except Exception as exc:
            log.debug("borrowed folder %s: could not read pending folders: %s", slug, exc)
            return "not-offered"
        entry = pending.get(slug) if isinstance(pending, dict) else None
        offered_by = list((entry or {}).get("offeredBy", {}) or {})
        if not offered_by:
            # Routine until the dashboard's enforce cycle reaches this
            # device; permanent while the server has not shared the lender.
            log.debug("borrowed folder %s has not been offered to this device yet", slug)
            return "not-offered"
        device_id = str(offered_by[0])
        if self.halted():
            # accept_folder ends in an unpause; during a halt that would put
            # a new folder online mid-stop. The offer keeps.
            log.info("borrowed folder %s: offer left pending, syncing is stopped here", slug)
            return "not-offered"
        log.info("accepting borrowed folder %s (%s) from %s at %s, restricted to %d "
                 "subtree(s)", slug, rel, device_id, want_path,
                 sum(1 for l in want_ignores if l.startswith("!") and not l.endswith("/**")))
        if not self._mkdir_allowed(want_path):
            return "error"
        try:
            Path(want_path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("borrowed folder %s: could not create %s: %s", slug, want_path, exc)
            return "error"
        self.admin.accept_folder(slug, rel, want_path, device_id,
                                 ignore_lines=want_ignores)
        return "accepted"

    def _drop_unborrowed(self, live: set[str]) -> None:
        """A lender that no borrower on this machine needs any more loses its
        LOCAL folder config; files stay on disk (plan §3.3 step 4).

        Identified by the restricted .stignore itself -- this feature's own
        signature, which nothing else writes -- rather than an in-memory
        "we accepted it" set, which a tray restart would empty, leaving the
        folder syncing forever. Never touches: a live borrowed lender, any
        SELECTED folder (a lender the editor ticked belongs to the
        sequencer, whose restriction check rewrites the full list), or any
        folder whose ignores are not the restricted shape. Skipped entirely
        when the selection is unknown/empty: no selection is no information
        (a dashboard blip must not deconfigure every borrowed folder)."""
        if self.selected_slugs_fn is None:
            return
        try:
            selected = {str(s) for s in self.selected_slugs_fn() or []}
        except Exception:
            return
        if not selected:
            return
        try:
            folders = self.admin.get_folders() or []
        except Exception:
            log.debug("borrowed folders: could not list local folders", exc_info=True)
            return
        for folder in folders:
            slug = str((folder or {}).get("id") or "")
            if not slug or slug in live or slug in selected:
                continue
            try:
                if not is_restricted(self.admin.get_ignores(slug)):
                    continue
            except Exception:
                continue
            log.info("borrowed folder %s is no longer borrowed by any selected project "
                     "-- removing its local Syncthing config (files stay on disk)", slug)
            try:
                self.admin.remove_folder(slug)
            except Exception:
                log.warning("borrowed folder %s: could not remove its local config",
                            slug, exc_info=True)