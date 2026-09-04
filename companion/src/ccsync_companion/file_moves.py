"""Dashboard-driven file moves, the companion half (docs/FILE_MOVES.md,
2026-08-27).

An admin moved a file (or a folder) between two places in the Projects tree
ON THE SERVER, and this machine held a copy at the old path. Lane A is a
one-way copy that never deletes, so without this the next pass would put
the file straight back where the admin just moved it from -- which is
exactly what happened to leso's card dump. The dashboard tells us through
the report reply (`commands.file_moves`); we move our own copy the same way,
carry its proxies with it, repoint every Resolve clip that referenced the
old path, and answer through the next report (`file_moves_applied`).

Two safety rules, both the same shape as the removal gate's:

* NOTHING here deletes. A move whose destination already exists on this
  machine is refused and reported, with the local file left where it was.
* Every move this machine has HEARD OF keeps its old path out of lane A for
  a day (`recent_excludes`), applied or refused, so a local copy that could
  not be moved still cannot re-upload itself while the admin sorts it out.

The ledger is on disk (`~/.ccsync/state/file_moves.json`): a command that
is redelivered after a restart must not be applied twice, and the exclusion
must survive the process that learned it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.file_moves")

LEDGER_FILENAME = "file_moves.json"
LEDGER_MAX_ENTRIES = 200
# How long a move's OLD path stays out of lane A. Long enough to cover the
# machine that was asleep when the command arrived and the admin who is
# still deciding what to do with a refused one; short enough that a path
# reused for genuinely new footage next week uploads normally.
EXCLUDE_WINDOW_SECONDS = 24 * 3600
PROJECTS_PREFIX = "Projects/"

# RES-1 (resilience sweep 2026-08-28). A move Resolve was holding open used
# to be refused ONCE and never tried again: the ledger answered every later
# report with the same old failure, the 24 h exclusion expired, and lane A
# put the file straight back on the NAS at the path the admin had cleared.
# The first retry is soon (Resolve gets closed at the end of a take), then
# hourly, and the whole thing gives up after a week rather than trying for
# ever -- an exhausted move is a `blocked` answer, which is a thing the
# dashboard shows, not a silence.
RETRY_FIRST_SECONDS = 10 * 60
RETRY_INTERVAL_SECONDS = 3600
RETRY_MAX_ATTEMPTS = 20
RETRY_MAX_SECONDS = 7 * 24 * 3600
# States an entry can be in. `retryable` and `blocked` both mean the local
# copy is still at the OLD path, which is why both hold the lane A exclusion
# open regardless of age.
STATE_DONE = "done"
STATE_RETRYABLE = "retryable"
STATE_BLOCKED = "blocked"
# RES-10: how long an applied move keeps asking to be relinked. The editor
# may not open that project for weeks, and the clip is offline in it until
# they do; after this the fixer meets it like any other offline clip.
RELINK_WINDOW_SECONDS = 30 * 24 * 3600

_BAD_SEGMENT = re.compile(r"^\.\.?$")


def safe_rel(raw: Any) -> Optional[str]:
    """A project-relative posix path from the wire, or None. Refuses
    absolute paths, drive letters, `..`, and control characters: the
    dashboard validated it too, but the command travelled through a JSON
    reply and this is the last stop before a filesystem call."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().replace("\\", "/").strip("/")
    if not value or ":" in value or any(ord(ch) < 32 for ch in value):
        return None
    parts = [p for p in value.split("/") if p]
    if not parts or any(_BAD_SEGMENT.match(p) or not p.strip() for p in parts):
        return None
    return "/".join(parts)


def parse_command(raw: Any) -> Optional[dict[str, Any]]:
    """One `commands.file_moves` entry, validated, or None."""
    if not isinstance(raw, dict):
        return None
    try:
        move_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    from_project = safe_rel(raw.get("from_project_rel"))
    to_project = safe_rel(raw.get("to_project_rel"))
    from_rel = safe_rel(raw.get("from_rel"))
    to_rel = safe_rel(raw.get("to_rel"))
    if not (from_project and to_project and from_rel and to_rel):
        return None
    return {
        "id": move_id,
        "from_project_rel": from_project, "from_rel": from_rel,
        "to_project_rel": to_project, "to_rel": to_rel,
        "is_dir": bool(raw.get("is_dir")),
        "requested_by": str(raw.get("requested_by") or "your administrator").strip(),
    }


def _cmp_key(path: object) -> str:
    """A path folded for COMPARISON only -- never for opening, renaming or
    deleting anything (CLAUDE.md's rule: there the bytes on disk are truth).

    `os.path.normcase` is a no-op on POSIX, which is wrong for the editors we
    actually have: a Mac's APFS volume is case-insensitive by default, so
    `Clip.braw` and `clip.braw` are ONE file there, and a ledger lookup that
    missed on case leaves a moved clip looking like a mystery MISSING rather
    than the one-click relink RES-10 built. Windows folds case for us; darwin
    has to be told to. Linux is the one place where case really does
    distinguish two files, so it is left alone. (2026-08-29: found by CI's
    macOS runner, the only machine here that runs this suite on a Mac.)

    bug-hunt-2026-09-03 comp-sync-2: Unicode is folded too (CR-90). The
    ledger's `old_local` is built from the dashboard's NFC `from_rel`, while
    the path `moved_to()` is asked about came out of Resolve on a Mac, i.e.
    NFD -- so `Matej Šimalčík.mov` missed itself and the RES-10 one-click
    relink was never offered for any accented name. Comparison only, which
    is the one case CLAUDE.md's rule allows normalising."""
    folded = os.path.normcase(os.path.normpath(unicodedata.normalize("NFC", str(path))))
    if sys.platform == "darwin":
        folded = folded.lower()
    return folded


def _under(full: str, root: str) -> str:
    """`full` re-expressed relative to the run root `root`, or "" when it is
    not inside it. Both are `/`-separated tree-relative paths, and the
    comparison is case- and Unicode-folded for the reasons _cmp_key gives
    (bug-hunt-2026-09-03 comp-sync-3). An empty root is the whole tree, so
    the path comes back unchanged."""
    if not root:
        return full
    parts = [p for p in full.split("/") if p]
    root_parts = [p for p in root.split("/") if p]
    if len(parts) <= len(root_parts):
        return ""

    def fold(text: str) -> str:
        return unicodedata.normalize("NFC", text).lower()

    # Component-wise, not a string prefix: NFC folding changes a name's
    # LENGTH, so a slice computed from the folded form can cut the raw path
    # in the wrong place.
    if [fold(p) for p in parts[:len(root_parts)]] != [fold(p) for p in root_parts]:
        return ""
    return "/".join(parts[len(root_parts):])


def _same_file(a: Path, b: Path) -> bool:
    return _cmp_key(a) == _cmp_key(b)


def _is_inside(path: Path, root: Path) -> bool:
    p = _cmp_key(path)
    r = _cmp_key(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def move_proxy_siblings(src: Path, dest: Path) -> int:
    """The `Proxy/<stem>.*` beside a file goes where the file goes -- the
    convention Resolve's auto-link and both rclone lanes are built on. Never
    overwrites; returns how many were moved."""
    proxy_dir = src.parent / "Proxy"
    if not proxy_dir.is_dir():
        return 0
    moved = 0
    for candidate in sorted(proxy_dir.iterdir()):
        if not candidate.is_file() or candidate.stem.lower() != src.stem.lower():
            continue
        target_dir = dest.parent / "Proxy"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / candidate.name
        if target.exists():
            continue
        candidate.replace(target)
        moved += 1
    return moved


def apply_move(move: dict[str, Any], local_root: str) -> tuple[bool, str, Optional[tuple[str, str]]]:
    """Move this machine's copy. Returns (ok, detail, (old_local, new_local))
    -- the pair is None when nothing was here to move. Never deletes and
    never overwrites; every refusal leaves the tree exactly as it was."""
    root = Path(local_root) / "Projects"
    src = root / Path(*move["from_project_rel"].split("/")) / Path(*move["from_rel"].split("/"))
    dest = root / Path(*move["to_project_rel"].split("/")) / Path(*move["to_rel"].split("/"))
    if not src.exists():
        return True, "nothing at the old path on this machine", None
    if _same_file(src, dest):
        return True, "already where the server has it", None
    if dest.exists():
        return False, f"the destination already exists on this machine ({dest})", None
    if src.is_dir() and _is_inside(dest, src):
        return False, "a folder cannot be moved into itself", None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dest)
        proxies = 0 if src.is_dir() or dest.is_dir() else move_proxy_siblings(src, dest)
    except OSError as exc:
        return False, f"could not move it on this machine: {exc}", None
    detail = "moved" + (f", {proxies} proxy file(s) with it" if proxies else "")
    return True, detail, (str(src), str(dest))


def relink_moved(old_local: str, new_local: str, local_root: str,
                 canonical_prefix: str, is_dir: bool = True) -> tuple[bool, str]:
    """Repoint every media pool clip under `old_local` to `new_local`.
    Returns (matched, detail).

    `matched` is "a media pool walk actually found clips at the old path",
    the only thing that retires a pending relink (RES-10): a Resolve that is
    closed, or open on another project, has not answered the question.

    The twin of CompanionApp._relink_moved, and here rather than there
    because sync/repath.py needs the same act for a whole PROJECT DIRECTORY
    the admin renamed on the server (SYNC-102, sweep 2026-09-03) and cannot
    import the app. Every write still goes through resolve_bridge.replace_clip
    -- save point plus undo journal, the CLAUDE.md rule -- and `connect()`
    stays the only caller of scriptapp (CR-68). Never raises: a Resolve that
    is busy is reported, not treated as a failed move; the files HAVE moved
    either way, and the fixer meets an offline clip like any other.
    """
    try:
        from . import canon, resolve_bridge

        result = resolve_bridge.get_media_pool_items()
        if not result.get("ok"):
            return False, f"Resolve not relinked ({result.get('message') or 'not open'})"
        old_n = os.path.normcase(os.path.normpath(old_local))
        relinked = failed = 0
        for item in result.get("items") or []:
            file_path = str(item.get("file_path") or "")
            local = canon.canonical_to_local(file_path, local_root, canonical_prefix) \
                or file_path
            local_n = os.path.normcase(os.path.normpath(local))
            if is_dir:
                if not (local_n == old_n or local_n.startswith(old_n.rstrip("\\/") + os.sep)):
                    continue
                target = os.path.join(new_local, os.path.relpath(local, old_local)) \
                    if local_n != old_n else new_local
            elif local_n == old_n:
                target = new_local
            else:
                continue
            clip = resolve_bridge.resolve_media_pool_item(item)
            if clip is None:
                failed += 1
                continue
            canonical = canon.local_to_canonical(target, local_root, canonical_prefix)
            outcome = resolve_bridge.replace_clip(clip, canonical, source="file_move")
            if outcome.get("ok"):
                relinked += 1
            else:
                failed += 1
                log.warning("relink: could not repoint %s -> %s: %s",
                            file_path, canonical, outcome.get("message"))
        if not relinked and not failed:
            return False, ""
        text = f"{relinked} Resolve clip(s) relinked"
        if failed:
            text += f", {failed} could not be"
        # A walk that FOUND the old path answered the question, even where
        # some of the writes were refused: the app's own _relink_moved_result
        # draws the line in exactly this place, and a clip Resolve will not
        # let us repoint is not something another pass fixes.
        return True, text
    except Exception:
        log.exception("relink: the Resolve relink failed")
        return False, "Resolve relink failed (see the log)"


class FileMoveLedger:
    """What this machine has done about each move it was told of."""

    def __init__(self, state_dir: Path, now: Callable[[], float] = time.time) -> None:
        self._path = Path(state_dir) / LEDGER_FILENAME
        self._now = now
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        if isinstance(entries, list):
            self._entries = [e for e in entries if isinstance(e, dict) and "id" in e]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"entries": self._entries[-LEDGER_MAX_ENTRIES:]},
                                      indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("file moves: could not write the ledger")

    def entry(self, move_id: int) -> Optional[dict[str, Any]]:
        for e in self._entries:
            if e.get("id") == move_id:
                return e
        return None

    def record(self, move: dict[str, Any], ok: bool, detail: str,
               state: Optional[str] = None, paths: Optional[tuple[str, str]] = None,
               relink_pending: bool = False) -> dict[str, Any]:
        previous = self.entry(move["id"]) or {}
        entry = {
            "id": move["id"],
            "from_project_rel": move["from_project_rel"], "from_rel": move["from_rel"],
            "to_project_rel": move["to_project_rel"], "to_rel": move["to_rel"],
            "is_dir": bool(move.get("is_dir")),
            "ok": bool(ok), "detail": detail[:512], "at": float(self._now()),
            "state": state or (STATE_DONE if ok else STATE_BLOCKED),
            "attempts": int(previous.get("attempts") or 0),
            "first_attempt_at": float(previous.get("first_attempt_at")
                                      or previous.get("at") or self._now()),
            "relink_pending": bool(relink_pending),
        }
        if paths:
            entry["old_local"], entry["new_local"] = paths[0], paths[1]
        elif previous.get("old_local"):
            entry["old_local"] = previous["old_local"]
            entry["new_local"] = previous.get("new_local", "")
        self._entries = [e for e in self._entries if e.get("id") != move["id"]] + [entry]
        self._entries = self._entries[-LEDGER_MAX_ENTRIES:]
        self._save()
        return entry

    def record_attempt_failed(self, move: dict[str, Any], detail: str) -> dict[str, Any]:
        """A move that could not be applied THIS time (RES-1).

        Returns the entry: `state` is `retryable` with a `next_attempt_at`
        until the attempt cap or the week runs out, and `blocked` after that.
        Blocked is an answer the dashboard shows; it is never a silence, and
        the local copy is still exactly where it was either way."""
        previous = self.entry(move["id"]) or {}
        now = float(self._now())
        attempts = int(previous.get("attempts") or 0) + 1
        first = float(previous.get("first_attempt_at") or now)
        exhausted = attempts >= RETRY_MAX_ATTEMPTS or (now - first) >= RETRY_MAX_SECONDS
        entry = self.record(move, ok=False, detail=detail,
                            state=STATE_BLOCKED if exhausted else STATE_RETRYABLE)
        entry["attempts"] = attempts
        entry["first_attempt_at"] = first
        entry["next_attempt_at"] = (
            None if exhausted
            else now + (RETRY_FIRST_SECONDS if attempts == 1 else RETRY_INTERVAL_SECONDS))
        self._entries = [e for e in self._entries if e.get("id") != move["id"]] + [entry]
        self._save()
        return entry

    def retry_due(self, entry: dict[str, Any]) -> bool:
        """Is this failed move ready to be tried again? A missing stamp (an
        entry written by an older build) is due: trying once more costs a
        filesystem call and the alternative is the file re-uploading itself."""
        if entry.get("state") != STATE_RETRYABLE:
            return False
        due = entry.get("next_attempt_at")
        try:
            return due is None or float(self._now()) >= float(due)
        except (TypeError, ValueError):
            return True

    def pending_relinks(self) -> list[dict[str, Any]]:
        """Applied moves whose Resolve clips have not been repointed yet
        (RES-10). The media pool that references them was not the one open
        when the move landed, so the clip is offline in a project the editor
        has not looked at yet."""
        cutoff = float(self._now()) - RELINK_WINDOW_SECONDS
        return [e for e in self._entries
                if e.get("relink_pending") and e.get("old_local")
                and float(e.get("at") or 0) >= cutoff]

    def clear_relink_pending(self, move_id: int) -> None:
        for entry in self._entries:
            if entry.get("id") == move_id and entry.get("relink_pending"):
                entry["relink_pending"] = False
                self._save()
                return

    def moved_to(self, local_path: str) -> Optional[dict[str, Any]]:
        """The move that took `local_path` away, or None (RES-10).

        The watcher asks this about every clip whose file is MISSING: a path
        this machine moved on the server's instruction is not a mystery, it
        is a one-click relink to a destination we know exactly."""
        wanted = _cmp_key(local_path or "")
        if not wanted:
            return None
        cutoff = float(self._now()) - RELINK_WINDOW_SECONDS
        for entry in reversed(self._entries):
            old = entry.get("old_local")
            if not old or not entry.get("new_local"):
                continue
            if float(entry.get("at") or 0) < cutoff:
                continue
            old_n = _cmp_key(old)
            if wanted == old_n or (entry.get("is_dir")
                                   and wanted.startswith(old_n.rstrip("\\/") + os.sep)):
                return entry
        return None

    def recent_excludes(self, subpath: Optional[str]) -> list[str]:
        """Old paths, relative to `subpath` (a lane A run root such as
        `Projects/2026/Base Drone`), of every move heard of in the last
        EXCLUDE_WINDOW_SECONDS. Applied or refused: both mean the server no
        longer wants the file there.

        SYNC-11 (resilience sweep 2026-08-28): every path is emitted in BOTH
        Unicode spellings, NFC and NFD, deduped. The dashboard's `from_rel`
        is NFC; a Mac's own filesystem hands the same name to rclone in NFD,
        and rclone matches an exclude rule against the bytes it reads off the
        disk -- so before this, a moved path with any diacritic was simply
        not excluded and lane A put it straight back on the NAS, the one
        failure this whole feature exists to stop (CR-90's lesson, CR-90
        itself being why it went unnoticed: CJK names never warn you). These
        are `-` rules, so the spelling that matches nothing costs nothing.
        Comparison/matching only: `apply_move` still uses the raw path.

        bug-hunt-2026-09-03 comp-sync-3: the run root is matched as a PREFIX
        of the old path, not as an equal project rel, and what comes back is
        re-expressed relative to that root. A borrowed subtree runs lane A
        over `Projects/<lender rel>/<sub rel>`, which can never equal a
        project rel, so demanding equality dropped every exclusion for that
        run and lane A -- which never deletes -- put the lender's file back
        at the path the admin cleared. `subpath=None` (a whole-tree run) is
        the same shape one level up: the root is local_root itself, so the
        paths come back with their `Projects/` prefix on."""
        wanted = str(subpath or "").replace("\\", "/").strip("/")
        if wanted and not wanted.lower().startswith(PROJECTS_PREFIX.lower()):
            # A caller that named the run root without the tree's top
            # component means the same directory the prefixed form does.
            wanted = PROJECTS_PREFIX + wanted
        cutoff = float(self._now()) - EXCLUDE_WINDOW_SECONDS
        out: list[str] = []
        for e in self._entries:
            # RES-1 (2026-08-28): a move that has NOT been applied here keeps
            # its exclusion for as long as it is unresolved, not for a day.
            # The old path still holds the file (that is why the move failed),
            # so letting the window lapse is letting lane A -- which never
            # deletes -- put the file back on the NAS at the path the admin
            # cleared, which is the failure this feature exists to prevent.
            unresolved = e.get("state") in (STATE_RETRYABLE, STATE_BLOCKED)
            if not unresolved and float(e.get("at") or 0) < cutoff:
                continue
            project = str(e.get("from_project_rel", "")).replace("\\", "/").strip("/")
            old = str(e.get("from_rel") or "").replace("\\", "/").strip("/")
            if not project or not old:
                continue
            full = f"{PROJECTS_PREFIX}{project}/{old}"
            rel = _under(full, wanted)
            if not rel:
                continue
            for spelling in (unicodedata.normalize("NFC", rel),
                             unicodedata.normalize("NFD", rel)):
                if spelling not in out:
                    out.append(spelling)
        return out
