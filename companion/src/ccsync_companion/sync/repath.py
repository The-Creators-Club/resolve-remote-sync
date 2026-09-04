"""Local auto-repath for server-side project moves (added 2026-07-25).

When a project directory is moved/renamed on the NAS, the dashboard keeps
its slug (the immutable identity from the .ccsync-project marker) and
retargets the SERVER Syncthing folder. This module is the editor-side half:
for each selected project, compare where the LOCAL Syncthing folder points
(its `path` in the local Syncthing config) against where the fresh
selection says it should live (local_root/Projects/<rel_path>). A mismatch
means the project moved server-side -- so move the local directory to match
and re-point the local folder.

The DECISION is deliberately stateless: the local Syncthing config *is* the
persisted state. (The events ledger added for SYNC-102 records what happened
so the editor can be told; nothing in it decides whether to repath.) That
closes the seeding gap -- a fresh install, an editor offline
through several moves, or an upgrade from a pre-repath companion all
converge on first reconcile, because there's no history file to be missing.

Order matters for lane A safety: the sequencer calls reconcile() BEFORE
running lanes each pass, so rclone never re-uploads the old tree to the
NAS's (now nonexistent) old path.

Never-raise ethos, injectable collaborators -- same conventions as the
rest of sync/.
"""
from __future__ import annotations

import errno
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .syncthing_admin import SyncthingAdmin

log = logging.getLogger("ccsync.sync.repath")

# SYNC-102 (sweep 2026-09-03). A server-side rename moved the editor's whole
# project directory with no toast, no tray line, no report field and no
# Resolve relink, so the project went offline mid-session with nothing
# anywhere saying why -- while a single-file move (file_moves.py) got all
# four. These are the state that makes it sayable.
EVENTS_FILENAME = "repath_events.json"
EVENTS_MAX = 20
# How long an applied repath keeps asking to be relinked, matching
# file_moves.RELINK_WINDOW_SECONDS: the editor may not open that project for
# weeks, and every clip in it is offline until they do.
RELINK_WINDOW_SECONDS = 30 * 24 * 3600

# "C:", "c:", "Z:" -- a drive letter as a path SEGMENT, which pathlib and
# ntpath both treat as re-rooting the join.
_DRIVE_SEGMENT = re.compile(r"^[A-Za-z]:$")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def rel_path_is_safe(rel: Any) -> bool:
    """Whether `rel` is a plain, contained, relative project path.

    Everything downstream does `Path(local_root) / "Projects" / rel`, and
    neither pathlib nor str.strip("/") collapses `..`, strips backslashes,
    or notices a drive letter. Measured with local_root=C:\\Creators_Club
    (AUDIT_2 L-7):

        "../../../Windows/Temp/x"  -> C:\\Windows\\Temp\\x
        "2026/../../../evil"       -> C:\\evil
        "\\evil"                   -> C:\\evil

    reconcile() would then MOVE the editor's whole project directory to
    that path and re-point Syncthing at it; the same string reaches lane
    A's source, where `rclone copy C:\\ nas:...` would upload every video on
    the editor's C: drive. Reachable via the dashboard's project rel_path,
    which no API path validates.
    """
    if not isinstance(rel, str) or not rel.strip():
        return False
    stripped = rel.strip()
    # A leading separator makes the join absolute -- reject before splitting
    # so "/evil" and "\\evil" can't be mistaken for a clean single segment.
    if stripped[0] in "/\\":
        return False
    segments = [seg for chunk in stripped.split("/") for seg in chunk.split("\\")]
    if not segments:
        return False
    for seg in segments:
        seg = seg.strip()
        if seg in ("", ".", ".."):
            return False
        if _DRIVE_SEGMENT.match(seg):
            return False
    return True


def normalized_safe_rel(rel: Any) -> Optional[str]:
    """The canonical form of a dashboard-supplied rel_path, or None when it
    isn't safe to build a path from.

    ONE normalize-then-validate step, shared by every consumer. It exists
    because the consumers disagreed: this module stripped a LEADING "/"
    before calling rel_path_is_safe (below), while sequencer.py validated the
    raw string. So "/2026/CCT/Show" was judged safe here -- the local project
    directory was MOVED and its Syncthing folder re-pointed -- and unsafe
    there, so lanes A and B skipped that project entirely and it never synced
    again, with nothing anywhere saying why (AUDIT_3 L-11).

    The STRICT side wins: normalization is whitespace + TRAILING separators
    only, so a leading separator still reaches rel_path_is_safe and is still
    refused everywhere (a leading "/" or "\\" re-roots the join --
    `Path(local_root) / "Projects" / "/evil"` is C:\\evil; see
    rel_path_is_safe and test_escaping_rel_paths_never_reach_a_lane).
    Refusing a project in both halves is a visible, logged stop; accepting it
    in one half and not the other is the silent half-move above.
    """
    if not isinstance(rel, str):
        return None
    normalized = rel.strip().rstrip("/\\")
    if not normalized or not rel_path_is_safe(normalized):
        return None
    return normalized


def _default_move(src: str, dst: str) -> None:
    """Same-volume rename with the destination's parent tree created first.

    Deliberately NOT os.renames: os.renames additionally prunes every
    now-empty parent directory of the SOURCE (via os.removedirs), walking
    up as far as it can. For a one-project editor whose project was the
    last thing left under its parent, that walk continues past Projects/
    and can remove local_root itself (e.g. the `subst P:` target),
    leaving every `P:\\...` path in the Resolve database dead
    (AUDIT D-3). No pruning at all is the simplest correct behavior here --
    an emptied source directory is harmless and left in place.

    Falls back to shutil.move on EXDEV: os.rename cannot cross volumes, and
    a `subst P:` whose target is on another drive, or a reconfigured
    local_root, makes that a routine failure rather than an exotic one
    (AUDIT_2 L-8). shutil.move copies then removes the source, so nothing
    is destroyed if the copy half fails.
    """
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError as exc:
        if getattr(exc, "errno", None) != errno.EXDEV:
            raise
        log.info("repath: cross-volume move %s -> %s, falling back to copy+remove", src, dst)
        shutil.move(src, dst)


def _item_is_valid(item: dict) -> bool:
    """A selection item usable for repathing: rel_path must be a non-blank
    str, contained (see rel_path_is_safe), and active (when present) must
    not be explicitly False. A null/non-str rel_path (e.g. a dashboard row
    whose project record is gone -- LEFT JOIN yields NULL) must never reach
    a path join, where str(None) == "None" would become a literal path
    segment and move the project directory to "...\\Projects\\None"
    (AUDIT D-4)."""
    rel = item.get("rel_path")
    if not isinstance(rel, str) or not rel.strip():
        return False
    if normalized_safe_rel(rel) is None:
        log.warning(
            "repath: refusing selection item with an unsafe rel_path %r "
            "(slug=%s) -- it would escape local_root",
            rel, item.get("slug"),
        )
        return False
    if item.get("active") is False:
        return False
    return True


class RepathLedger:
    """The last EVENTS_MAX server-side project moves this machine made, and
    whether Resolve has been repointed for each (SYNC-102).

    Persisted under `~/.ccsync/state/` for the same reason file_moves' is:
    "the clips will reconnect next time you open that project" is a promise
    that has to survive the restart the editor makes in between. A ledger
    with no state_dir keeps the events in memory only, which is what every
    test and every bare ProjectRepather gets.
    """

    def __init__(self, state_dir: Optional[Path | str] = None,
                 now: Callable[[], float] = time.time) -> None:
        self._path = Path(state_dir) / EVENTS_FILENAME if state_dir else None
        self._now = now
        self._events: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        events = data.get("events") if isinstance(data, dict) else None
        if isinstance(events, list):
            self._events = [e for e in events if isinstance(e, dict) and e.get("old")]

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"events": self._events[-EVENTS_MAX:]}, indent=1),
                           encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("repath: could not write the events ledger")

    def record(self, slug: str, old: str, new: str, note: str,
               relinked: Optional[bool], moved: bool = True) -> dict[str, Any]:
        event = {
            "id": int(float(self._now()) * 1000),
            "slug": str(slug),
            "old": str(old),
            "new": str(new),
            "at": float(self._now()),
            "relinked": relinked,
            "note": str(note)[:512],
            "moved": bool(moved),
        }
        # One row per project per outcome: a folder that cannot be moved is
        # retried every pass, and twenty identical "could not move" events
        # would push out the twenty renames the editor actually wants to
        # read.
        self._events = [e for e in self._events
                        if not (e.get("slug") == event["slug"]
                                and e.get("old") == event["old"]
                                and e.get("moved") == event["moved"])]
        self._events.append(event)
        self._events = self._events[-EVENTS_MAX:]
        self._save()
        return event

    def events(self) -> list[dict[str, Any]]:
        """Newest last, the order they happened in."""
        return [dict(e) for e in self._events]

    def pending_relinks(self) -> list[dict[str, Any]]:
        """Applied repaths whose Resolve clips have not been repointed yet:
        `relinked is None` means "Resolve was not open", which is not an
        answer to the question (the RES-10 rule, kept identical here)."""
        cutoff = float(self._now()) - RELINK_WINDOW_SECONDS
        return [dict(e) for e in self._events
                if e.get("moved") and e.get("relinked") is None
                and e.get("old") and e.get("new")
                and float(e.get("at") or 0) >= cutoff]

    def mark_relinked(self, event_id: Any, relinked: bool, note: str = "") -> None:
        for event in self._events:
            if event.get("id") == event_id:
                event["relinked"] = bool(relinked)
                if note:
                    event["note"] = str(note)[:512]
                self._save()
                return


def moved_note(name: str, relinked: Optional[bool]) -> str:
    """What the editor is told about a rename that worked. No em dashes."""
    head = (f"Your admin renamed a project on the server. CC Sync moved your copy "
            f"to match ({name}).")
    if relinked:
        return head + " Resolve was relinked."
    return head + " Resolve reconnects the clips next time you open that project."


def blocked_note(name: str) -> str:
    """What the editor is told about a rename whose move could not be made.

    The words the finding asked for, and the same ones the Settings line and
    the dashboard chip carry: this is the one sentence that explains a
    project quietly not syncing."""
    return (f"{name} is not syncing because CC Sync could not move its folder. "
            f"Your files are safe where they are. Close it in Resolve and in "
            f"Explorer, then it retries by itself.")


class ProjectRepather:
    def __init__(
        self,
        admin: SyncthingAdmin,
        local_root: str,
        move_fn: Callable[[str, str], Any] = _default_move,
        state_dir: Optional[Path | str] = None,
        relink_fn: Optional[Callable[[str, str], tuple[bool, str]]] = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.admin = admin
        self.local_root = local_root
        self._move = move_fn
        # SYNC-102: what happened, kept where the tray and the Settings
        # window can read it. Injectable relink so this module never imports
        # Resolve for itself -- the sequencer hands in file_moves' relink,
        # which is the one that takes a save point and writes the undo
        # journal (CLAUDE.md: every media-pool write goes through
        # resolve_bridge.replace_clip).
        self.ledger = RepathLedger(state_dir, now=now)
        self._relink_fn = relink_fn

    def reconcile(self, selection: list[dict]) -> list[str]:
        """Repath every selected project whose local folder points somewhere
        other than local_root/Projects/<rel_path>. Returns the slugs that
        were repathed. Never raises; per-project failures are logged and the
        folder is always unpaused again."""
        repathed: list[str] = []
        # Before anything else: a repath from an earlier pass whose clips
        # Resolve never answered for (SYNC-102).
        self.retry_pending_relinks()
        try:
            config = self.admin.get_config() or {}
            folders = {f.get("id"): f for f in config.get("folders", [])}
        except Exception:
            log.debug("repath: local syncthing unreachable -- skipping reconcile")
            return repathed

        for item in selection or []:
            if not _item_is_valid(item):
                continue
            slug = item.get("slug")
            rel = normalized_safe_rel(item.get("rel_path"))
            if not slug or not rel:
                continue
            folder = folders.get(slug)
            if folder is None:
                continue  # not accepted locally yet -- the accept flow owns creation
            actual = str(folder.get("path", ""))
            expected = str(Path(self.local_root) / "Projects" / Path(*rel.split("/")))
            if not actual or _norm(actual) == _norm(expected):
                continue
            if not self._is_contained(expected):
                log.error(
                    "repath: computed target %s for %s is not under local_root %s "
                    "-- refusing to move anything", expected, slug, self.local_root,
                )
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

            moved = self._move_dir(slug, actual, expected)
            if not moved:
                # SYNC-102: recorded, not just logged. This branch is the
                # routine one (Resolve or Explorer holding a handle) and it
                # leaves ONE project not syncing, silently, until a human
                # looks -- which is exactly what nothing anywhere said.
                self.ledger.record(slug, actual, expected, blocked_note(rel),
                                   relinked=None, moved=False)
                # DELIBERATELY LEFT PAUSED. Re-pointing after a failed move
                # aims the local Syncthing folder at a directory that does
                # not hold the content -- and the structure clone then
                # creates it -- so Syncthing sees the whole project's
                # lane-C set as deleted and propagates that to the NAS and
                # every other editor (AUDIT_2 DEL-5/L-8). Staying paused
                # costs this editor one project's sync until a human looks;
                # the alternative costs everyone the files.
                log.error(
                    "repath: %s -- local directory could NOT be moved to %s; "
                    "leaving the folder PAUSED and pointed at %s. Your files are "
                    "safe where they are; close Resolve/Explorer on that folder "
                    "and the next pass will retry.", slug, expected, actual,
                )
                continue

            try:
                self.admin.set_folder_path(slug, expected, label=rel)
                repathed.append(slug)
            except Exception:
                log.exception("repath: could not re-point folder %s", slug)
            # The editor's clips still point at the old canonical path
            # (SYNC-102), so relink them the same way a single-file move
            # does -- and record the event either way, because "Resolve was
            # not open" is not "there was nothing to relink" (RES-10).
            relinked, detail = self._relink(actual, expected)
            event = self.ledger.record(slug, actual, expected,
                                       moved_note(rel, relinked), relinked=relinked)
            log.info("repath: %s -- %s%s", slug, event["note"],
                     f" ({detail})" if detail else "")
            try:
                self.admin.set_folder_paused(slug, False)
            except Exception:
                log.exception("repath: could not unpause folder %s", slug)
        return repathed

    def _relink(self, old_local: str, new_local: str) -> tuple[Optional[bool], str]:
        """Repoint the open Resolve project's clips. (relinked, detail).

        None means "Resolve did not answer the question" -- closed, or open
        on another project -- which leaves the event pending so the next
        reconcile with a project open tries again, exactly as file_moves'
        pending relinks do. Never raises: a repath that worked must not be
        reported as failed because Resolve was busy."""
        if self._relink_fn is None:
            return None, ""
        try:
            matched, text = self._relink_fn(old_local, new_local)
        except Exception:
            log.exception("repath: the Resolve relink failed for %s", new_local)
            return None, ""
        return (True if matched else None), str(text or "")

    def retry_pending_relinks(self) -> int:
        """Try again for every applied repath Resolve has not answered for.

        Called at the head of each reconcile, i.e. once per sequencer pass:
        the editor opens the renamed project some time AFTER the move, and
        that is the only moment the media pool can be walked. Returns how
        many were retired. Never raises."""
        done = 0
        try:
            for event in self.ledger.pending_relinks():
                relinked, detail = self._relink(event.get("old", ""), event.get("new", ""))
                if relinked:
                    self.ledger.mark_relinked(
                        event.get("id"), True,
                        moved_note(str(event.get("slug") or ""), True))
                    done += 1
                    log.info("repath: %s relinked in Resolve after the project changed%s",
                             event.get("slug"), f" ({detail})" if detail else "")
        except Exception:
            log.exception("repath: could not re-run the pending relinks")
        return done

    def _is_contained(self, expected: str) -> bool:
        """Belt to rel_path_is_safe's braces: the computed target must
        genuinely live under local_root (AUDIT_2 L-7)."""
        root = str(self.local_root or "").strip()
        if not root:
            return False
        try:
            common = os.path.commonpath([_norm(root), _norm(expected)])
        except ValueError:
            return False  # different drives -- commonpath raises
        return common == _norm(root)

    def _move_dir(self, slug: str, actual: str, expected: str) -> bool:
        """Filesystem half. Returns True only when the folder can safely be
        re-pointed at `expected`, i.e. the content is there.

        Missing source counts as success ONLY when the target already
        exists -- otherwise there is no content anywhere and re-pointing
        would hand Syncthing an empty folder to "reconcile" downward.
        Target already exists (with a live source) is a conflict: skip the
        move but still re-point, since the target is what holds the folder's
        content going forward and the old directory is left for a human."""
        src = Path(actual)
        dst = Path(expected)
        if not src.is_dir():
            if dst.is_dir():
                log.info(
                    "repath: %s -- old local dir %s absent and %s already exists, "
                    "re-pointing only", slug, src, dst,
                )
                return True
            log.warning(
                "repath: %s -- neither %s nor %s exists locally; not re-pointing "
                "until there is something to point at", slug, src, dst,
            )
            return False
        if dst.exists():
            log.warning(
                "repath: %s -- target %s already exists; leaving old dir %s in place "
                "(reconcile by hand), re-pointing the folder anyway", slug, dst, src,
            )
            return True
        try:
            self._move(str(src), str(dst))
        except OSError:
            # Routine on Windows: Resolve, Explorer or AV holding a handle
            # inside the project dir gives ERROR_ACCESS_DENIED / a sharing
            # violation. The caller must NOT re-point on this path.
            log.exception("repath: move failed for %s -- NOT re-pointing", slug)
            return False
        except Exception:
            log.exception("repath: unexpected move failure for %s -- NOT re-pointing", slug)
            return False
        log.info("repath: moved %s -> %s", src, dst)
        return True
