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

import itertools
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.file_moves")

LEDGER_FILENAME = "file_moves.json"
LEDGER_MAX_ENTRIES = 200
# res-companion-2 (2026-09-18): how many lane-B relocations the ledger
# remembers, and for how long. A pass is bounded by rclone's --max-delete
# (100), and the dashboard's own detection delivers the matching move within
# a collector cycle or two, so a day is generous; the cap is what keeps a
# machine that follows moves all week from growing the file without bound.
RELOCATION_MAX_ENTRIES = 500
RELOCATION_MAX_AGE_SECONDS = 24 * 3600
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
# res-companion-1 (2026-09-11): "we are part-way through applying this one".
# Written before the first filesystem call and replaced by the real outcome a
# moment later, so the only way to READ it is to be the process that came
# after a crash. It holds the lane A exclusion open like every other row.
STATE_APPLYING = "applying"
# res-fleet-3 (2026-09-18): the move landed in a project this machine does not
# sync, so the local copy went to the lane B trash instead of into a directory
# that is not a project here. `docs/HAND_MOVES_ON_THE_SERVER.md` section 4b.
# ok=True and the detail sentence are the wire as it was; the WORD is the
# added part (the dashboard declared it first - a companion that sends it to
# a dashboard below 0.7.50 422s the whole report, so the dashboard deploys
# first, exactly as `applying` did).
STATE_NOT_SYNCED_HERE = "not_synced_here"
DETAIL_NOT_SYNCED_HERE = "trashed locally, destination not synced here"
# The lane B trash, spelled the same way rclone_lane spells it. NOT imported
# from there: rclone_lane is the sync package and this module is imported by
# it in comment and by app.py before the lanes exist. One directory per run,
# keyed by the file's own project path, so a recovery is unambiguous and
# lane_guard.prune_trash ages it out with everything else.
TRASH_DIR_NAME = ".ccsync-trash"
# RES-10: how long an applied move keeps asking to be relinked. The editor
# may not open that project for weeks, and the clip is offline in it until
# they do; after this the fixer meets it like any other offline clip.
RELINK_WINDOW_SECONDS = 30 * 24 * 3600

_BAD_SEGMENT = re.compile(r"^\.\.?$")
# res-companion-2 (2026-09-18b): one counter per process behind the
# ledger's scratch filenames, so no two writes can name the same tmp.
_TMP_SEQ = itertools.count()


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


# comp-sync-11 (2026-09-11): the public spelling. `relink_moved` below and
# CompanionApp._relink_moved (its twin) both compared media-pool paths with a
# bare normcase/normpath, which on darwin folds NEITHER case nor Unicode -- so
# a moved clip whose name carries a diacritic never matched, the pending
# relink never retired and the clip stayed Media Offline for the whole 30 day
# window. Anything outside this module that compares two paths must come
# through here rather than grow a third private copy of the rule.
cmp_key = _cmp_key


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


def _raw_tail(full: str, root: str) -> str:
    """`full` minus `root`'s leading components, in `full`'s own spelling
    (comp-sync-11, 2026-09-11). "" when there is nothing left over.

    Counting components rather than slicing the string: the caller has
    already established that `full` is under `root` through the folded keys,
    and the two may be spelled differently (NFC vs NFD), which makes every
    length-based slice wrong by a few bytes per accent."""
    parts = os.path.normpath(str(full)).replace("\\", "/").split("/")
    root_parts = os.path.normpath(str(root)).replace("\\", "/").split("/")
    tail = parts[len(root_parts):]
    return os.path.join(*tail) if tail else ""


def _same_file(a: Path, b: Path) -> bool:
    return _cmp_key(a) == _cmp_key(b)


def _is_inside(path: Path, root: Path) -> bool:
    p = _cmp_key(path)
    r = _cmp_key(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def _stem_key(stem: str) -> str:
    """A file stem folded for COMPARISON only (comp-sync-18, 2026-09-11).

    `iterdir()` on a Mac hands back NFD while the command's `from_rel` is the
    dashboard's NFC, so a raw `.lower()` compare orphaned the proxy of every
    accented name: the original moved, `Proxy/Šimalčík_A001.mov` stayed behind
    under the old project, where lane B's sync eventually trashed it. The same
    CR-90 class as `_cmp_key`, on the one comparison in this module that did
    not go through it."""
    return unicodedata.normalize("NFC", str(stem)).lower()


def move_proxy_siblings(src: Path, dest: Path) -> int:
    """The `Proxy/<stem>.*` beside a file goes where the file goes -- the
    convention Resolve's auto-link and both rclone lanes are built on. Never
    overwrites; returns how many were moved."""
    proxy_dir = src.parent / "Proxy"
    if not proxy_dir.is_dir():
        return 0
    moved = 0
    want = _stem_key(src.stem)
    for candidate in sorted(proxy_dir.iterdir()):
        if not candidate.is_file() or _stem_key(candidate.stem) != want:
            continue
        target_dir = dest.parent / "Proxy"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / candidate.name
        if target.exists():
            continue
        candidate.replace(target)
        moved += 1
    return moved


def _rename_case_only(src: Path, dest: Path) -> None:
    """Rename a file whose old and new names differ only in spelling
    (comp-sync-12, 2026-09-11).

    `src.replace(dest)` is a no-op or an error on a case-insensitive
    filesystem when the two names fold together, so the rename goes through a
    temporary name the filesystem agrees is a third file. The NAS is
    case-sensitive and DID rename it: without this the companion answered
    "already where the server has it", nothing moved on the editor's disk,
    and a day later -- once `recent_excludes` lapsed -- lane A uploaded the
    old spelling back beside the new one, which is the duplicate-at-the-
    cleared-path failure docs/FILE_MOVES.md exists to prevent."""
    # comp-sync-b-4 (2026-09-11b): the prefix is load-bearing and is spelled
    # the same in rclone_lane.MOVE_STAGING_PREFIX, which is what keeps a
    # staging name left behind by a failed rename (Resolve holding a handle:
    # WinError 32 on the replace AND on the restore) out of both of lane A's
    # doors. It keeps the original extension, so without that rule the next
    # pass uploaded it to the NAS beside the real clip. Kept as a literal
    # here on purpose: this module deliberately imports nothing of its own.
    staging = src.with_name(f".ccsync-move-{os.getpid()}-{src.name}")
    src.replace(staging)
    try:
        staging.replace(dest)
    except OSError:
        # Put it back rather than leave the editor's file under a dot name.
        try:
            staging.replace(src)
        except OSError:
            log.exception("file moves: could not restore %s after a failed "
                          "case-only rename -- it is at %s", src, staging)
        raise


def _move_is_on_disk(entry: dict[str, Any]) -> bool:
    """Did this move's file actually reach `new_local`? (comp-sync-b-2.)

    Never raises: a filesystem that cannot answer counts as NO, because the
    thing this gates is repointing Resolve at a path we would then be
    guessing about."""
    new_local = str(entry.get("new_local") or "")
    old_local = str(entry.get("old_local") or "")
    if not new_local:
        return False
    try:
        return os.path.exists(new_local) and not os.path.exists(old_local)
    except OSError:
        return False


def rename_proxy_siblings_case_only(src: Path, dest: Path) -> int:
    """The case-only twin of move_proxy_siblings (regression-6, 2026-09-11b).

    move_proxy_siblings keeps each proxy's OWN name, which for a rename that
    differs only in spelling means it moves nothing at all: the target is the
    same file. The dashboard renames the proxy on the NAS with the original
    ("the dashboard renames it (proxies with it)", docs/FILE_MOVES.md), so
    leaving the local proxy under the old spelling hands lane B a proxy that
    is missing locally and one that is extraneous -- it downloads the first
    and trashes the second, and charges the deletion to the breaker's
    account. Never raises: the original has already been renamed by the time
    this runs, and a proxy that could not follow is a cosmetic loss beside
    undoing that."""
    proxy_dir = src.parent / "Proxy"
    if not proxy_dir.is_dir():
        return 0
    want = _stem_key(src.stem)
    moved = 0
    for candidate in sorted(proxy_dir.iterdir()):
        try:
            if not candidate.is_file() or _stem_key(candidate.stem) != want:
                continue
            target_dir = dest.parent / "Proxy"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / (dest.stem + candidate.suffix)
            if os.path.normpath(str(target)) == os.path.normpath(str(candidate)):
                continue
            if _same_file(target, candidate):
                _rename_case_only(candidate, target)
            elif not target.exists():
                candidate.replace(target)
            else:
                continue
            moved += 1
        except OSError:
            log.warning("file moves: the proxy %s could not follow the rename to %s",
                        candidate, dest.name, exc_info=True)
    return moved


def _dest_is_synced_here(move: dict[str, Any],
                         project_rels: Optional[Any]) -> bool:
    """Does this machine sync the place this file is moving TO?
    (res-fleet-3, `docs/HAND_MOVES_ON_THE_SERVER.md` section 4b.)

    `project_rels` is every Projects-relative path this machine syncs -
    `sequencer.rel_to_slug_with_borrowed()`'s keys, NOT `rel_to_slug`'s: a
    borrowed subtree is on this disk too, and judging by the selection alone
    would trash a file that has a perfectly good home here (comp-sync-4, the
    same missing lookup from the other end).

    The test is the destination PATH rather than the destination project,
    which is what makes one rule cover both: a selected project's rel is a
    prefix of everything in it, and a borrowed entry's key is the lender's
    subpath, so a move into the borrowed folder falls under it and a move
    into the rest of the lender's project does not.

    None means "no plan was passed" and answers True, which is exactly what
    this function did before it existed: an unmanaged companion, or an older
    caller, keeps today's behaviour.

    comp-sync-1 (2026-09-18b): so does an EMPTY plan, and so does a source
    the plan does not account for. Section 4b may only be trusted to a plan
    that has at least one entry AND that names the place this machine is
    holding the file: `app._synced_project_rels` returns `[]` (not None) for
    any managed companion whose sequencer has an empty selection - an editor
    between projects, or one whose admin has just cleared the ticks - and
    against an empty list EVERY destination read as "not synced here", so
    every move that machine was told of trashed the local original, with no
    relink and an ok=True answer, and prune_trash deleted it a fortnight
    later. A machine holding the file in a project its plan does not name is
    the same evidence one step weaker: the plan is not the whole truth about
    that disk, so trashing on it is a guess, and following the move is not.
    """
    if project_rels is None:
        return True
    known_rels = [_cmp_key(str(rel or "").strip("/")) for rel in project_rels or ()]
    known_rels = [rel for rel in known_rels if rel]
    if not known_rels:
        return True
    from_project = str(move.get("from_project_rel") or "").strip("/")
    to_project = str(move.get("to_project_rel") or "").strip("/")
    # A move WITHIN the project this machine is holding the file in: whatever
    # the plan says, "the destination is not synced here" cannot be true of a
    # directory the file is already sitting in.
    if from_project and _cmp_key(from_project) == _cmp_key(to_project):
        return True
    source_full = "/".join(part for part in (
        from_project, str(move.get("from_rel") or "").strip("/")) if part)
    if source_full and not _under_any(source_full, known_rels):
        return True
    dest_full = "/".join(part for part in (
        to_project, str(move.get("to_rel") or "").strip("/")) if part)
    if not dest_full:
        return True
    return _under_any(dest_full, known_rels)


def _under_any(rel_path: str, known_rels: list[str]) -> bool:
    """Is this Projects-relative path inside one of the plan's entries?

    The test is the PATH rather than the project, which is what lets one rule
    cover a borrowed subtree too: a selected project's rel is a prefix of
    everything in it, and a borrowed entry's key is the lender's subpath."""
    want = _cmp_key(rel_path)
    return any(want == known or want.startswith(known + os.sep)
               for known in known_rels)


def _trash_destination(local_root: str, move: dict[str, Any]) -> Path:
    """Where the local copy goes when section 4b applies: the lane B trash,
    under the file's own project path, in a per-run timestamped directory."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return (Path(local_root) / TRASH_DIR_NAME / stamp / "Projects"
            / Path(*str(move["from_project_rel"]).split("/"))
            / Path(*str(move["from_rel"]).split("/")))


def apply_move(move: dict[str, Any], local_root: str,
               ledger: Optional["FileMoveLedger"] = None,
               project_rels: Optional[Any] = None,
               ) -> tuple[bool, str, Optional[tuple[str, str]]]:
    """Move this machine's copy. Returns (ok, detail, (old_local, new_local))
    -- the pair is None when nothing was here to move. Never deletes and
    never overwrites; every refusal leaves the tree exactly as it was.

    `ledger` is optional and is the crash window's answer (res-companion-1,
    2026-09-11): given one, an INTENT row is written before the first
    filesystem call and a redelivered command whose file is already at the
    new path resumes from it instead of answering "nothing at the old path
    on this machine". Without it the behaviour is exactly what it was, which
    is what lets an older caller keep working."""
    root = Path(local_root) / "Projects"
    src = root / Path(*move["from_project_rel"].split("/")) / Path(*move["from_rel"].split("/"))
    dest = root / Path(*move["to_project_rel"].split("/")) / Path(*move["to_rel"].split("/"))
    if not src.exists():
        # res-companion-1: the move itself is not crash-atomic with the
        # record of it (the proxy loop and the media-pool walk are seconds to
        # tens of seconds, and "died without a shutdown" is routine here --
        # CR-93). A process killed in that window left the file moved, no
        # ledger row, and a redelivery that answered ok/relink_pending=False:
        # the clip was offline in Resolve for ever and the fixer's answer to
        # an in-tree missing clip is to copy it back to the path the admin
        # just cleared. Resume only on the exact evidence the verdict names
        # -- OUR intent row, src gone AND dest present -- so a machine that
        # never held the file still answers "nothing at the old path".
        if ledger is not None and dest.exists():
            entry = ledger.entry(move["id"]) or {}
            if entry.get("state") == STATE_APPLYING:
                proxies = 0 if dest.is_dir() else move_proxy_siblings(src, dest)
                detail = ("finished a move this machine was interrupted during"
                          + (f", {proxies} proxy file(s) with it" if proxies else ""))
                return True, detail, (str(src), str(dest))
            # res-companion-2 (2026-09-18): lane B may have followed this move
            # already, on the server's locate answer, minutes before the
            # dashboard's detection made a command of it. It could not write
            # an intent row (the move had no id yet), so it left the note
            # `record_relocation` writes instead -- the same evidence, from
            # the one actor that knows it carried THIS file to THIS path.
            # Answering "nothing at the old path" here is what left the clips
            # Media Offline in Resolve while the move was recorded as done.
            if ledger.relocation_to(str(src), str(dest)):
                return True, "lane B had already moved it on this machine", (
                    str(src), str(dest))
            # comp-sync-3 (2026-09-18b mediums): the FOLDER drag is the shape
            # this feature exists for, and it was the one shape the evidence
            # above could not read. The collector sends a hand-moved folder as
            # ONE is_dir command naming the directory, while lane B notes one
            # relocation row per FILE, so the exact-pair check matched nothing
            # and every clip under the folder stayed Media Offline while the
            # MOVES history said this machine had followed.
            if move.get("is_dir") and ledger.relocated_folder(str(src), str(dest)):
                return True, "lane B had already moved this folder on this machine", (
                    str(src), str(dest))
        return True, "nothing at the old path on this machine", None
    if _same_file(src, dest):
        # ...unless the two names differ in bytes and fold to the same key:
        # that is a real rename on the server's case-sensitive filesystem
        # (comp-sync-12).
        if os.path.normpath(str(src)) == os.path.normpath(str(dest)):
            return True, "already where the server has it", None
        if src.is_dir():
            return False, ("a folder cannot be renamed by spelling alone on this "
                           "machine; ask your admin to do it in two steps"), None
        if ledger is not None:
            ledger.record_intent(move, str(src), str(dest))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _rename_case_only(src, dest)
        except OSError as exc:
            return False, f"could not rename it on this machine: {exc}", None
        proxies = rename_proxy_siblings_case_only(src, dest)
        detail = ("renamed to match the server's spelling"
                  + (f", {proxies} proxy file(s) with it" if proxies else ""))
        return True, detail, (str(src), str(dest))
    if dest.exists():
        # comp-sync-3 (2026-09-18b mediums): the same folder drag, arriving on
        # the other branch. Lane B carries the FILES out and the emptied source
        # directory can survive, so src.exists() is still true and the refusal
        # below would fire on a move this machine had in fact followed. Only an
        # empty leftover counts, and only with lane B's own evidence; nothing
        # here deletes the husk.
        if (move.get("is_dir") and src.is_dir() and dest.is_dir()
                and ledger is not None
                and ledger.relocated_folder(str(src), str(dest))
                and not any(p.is_file() for p in src.rglob("*"))):
            return True, "lane B had already moved this folder on this machine", (
                str(src), str(dest))
        return False, f"the destination already exists on this machine ({dest})", None
    if src.is_dir() and _is_inside(dest, src):
        return False, "a folder cannot be moved into itself", None
    if not _dest_is_synced_here(move, project_rels):
        # res-fleet-3 (2026-09-18), section 4b. The dashboard picks its target
        # machines from the SOURCE project's ticks and never asks about the
        # destination's, so a move between two projects reaches every machine
        # that holds the file - including the ones that do not sync where it
        # is going. `mkdir(parents=True)` there built a directory with no
        # `.ccsync-project` marker, which nothing in the product can see:
        # `fixer.list_project_dirs` keys on the marker, the media manifest
        # never reports it, and neither lane touches it. The file was a
        # permanent invisible orphan on the editor's disk - filling the disk
        # lane B's floor parks on - while the MOVES history said that
        # computer had followed. Trashed, never deleted, and said so.
        trash = _trash_destination(local_root, move)
        if ledger is not None:
            # comp-sync-2 / res-companion-1 (2026-09-18b): the intent row is
            # written for its lane A exclusion and for the crash window, NOT
            # as a destination, so its new_local is empty. Writing the trash
            # path here put it in the ledger, from where `record()` carried it
            # into the completion row (it inherits the previous row's paths
            # whenever `paths` is falsy, which is exactly what the 4b branch
            # returns) and RES-10 offered the editor a one-click relink of
            # Resolve into `.ccsync-trash` - which prune_trash deletes on its
            # age rule, taking every relinked clip permanently offline.
            ledger.record_intent(move, str(src), "")
        try:
            trash.parent.mkdir(parents=True, exist_ok=True)
            src.replace(trash)
        except OSError as exc:
            return False, f"could not move it out of the way on this machine: {exc}", None
        # comp-sync-1 (2026-09-18b): the proxies go with it, as they do on
        # every other branch. Left behind they are an orphan whose original
        # has gone: lane B trashes them on its own next pass, in a different
        # batch, so the recovery an admin might want is in two places with
        # two ages.
        if not trash.is_dir():
            try:
                move_proxy_siblings(src, trash)
            except OSError:
                log.warning("file move #%s: a proxy could not follow the original "
                            "into the trash", move.get("id"), exc_info=True)
        log.info("file move #%s: %s is not a project this machine syncs -- "
                 "the local copy is in %s", move.get("id"),
                 move.get("to_project_rel"), trash)
        # paths=None on purpose: nothing moved TO a path Resolve should be
        # repointed at, and a relink to the trash would be worse than the
        # offline clip.
        return True, DETAIL_NOT_SYNCED_HERE, None
    # res-companion-1: the intent goes down BEFORE the first filesystem call,
    # so a crash between the rename and record() leaves evidence to resume
    # from rather than a file nobody can account for.
    if ledger is not None:
        ledger.record_intent(move, str(src), str(dest))
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
        from . import canon, resolve_bridge, ui_copy

        result = resolve_bridge.get_media_pool_items()
        if not result.get("ok"):
            return False, f"Resolve not relinked ({result.get('message') or 'not open'})"
        # comp-sync-11 (2026-09-11): through _cmp_key, like every other
        # comparison in this module. A bare normcase folds neither case nor
        # Unicode on darwin, and `old_local` is built from the dashboard's NFC
        # `from_rel` while Resolve hands back the Mac's NFD -- so the walk
        # matched nothing, `matched` stayed False, and the toast's promise
        # ("the clip reconnects next time you open that project") was never
        # kept on any accented name. The raw strings are what relpath/join
        # below still operate on: `target` is written into Resolve.
        old_n = cmp_key(old_local)
        relinked = failed = 0
        for item in result.get("items") or []:
            file_path = str(item.get("file_path") or "")
            local = canon.canonical_to_local(file_path, local_root, canonical_prefix) \
                or file_path
            local_n = cmp_key(local)
            if is_dir:
                if not (local_n == old_n or local_n.startswith(old_n.rstrip("\\/") + os.sep)):
                    continue
                # comp-sync-11: os.path.relpath compares the two RAW strings,
                # so an NFD clip path under an NFC root shares no prefix with
                # it and comes back full of `..`. The tail is taken by
                # COMPONENT COUNT instead, off the raw path, so the spelling
                # that goes into Resolve is the one on the disk.
                tail = _raw_tail(local, old_local)
                target = os.path.join(new_local, tail) if tail else new_local
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
        # regression-19 hand-off (2026-09-11b): this string is editor-visible
        # now. app.py used to build its own sentence and comp-sync-11 folded
        # the two halves into this one, so the developer plural rides out to
        # the RELINK IT toast and the moved-clip dialog's answer (owner's
        # rule, 2026-08-18: no "(s)" in copy an editor reads).
        text = f"{ui_copy.count(relinked, 'Resolve clip')} relinked"
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
    """What this machine has done about each move it was told of.

    res-companion-2 (2026-09-18b): TWO threads write this. The reporter
    thread applies `file_moves` commands (`record_intent` / `record`), and
    since CR-282B the sequencer/lane thread writes lane B's relocation notes
    (`record_relocation`, up to rclone's 100 per pass) - while lane A reads
    `recent_excludes` on a third. Every public method takes `_lock` around
    the mutation AND the `_save()` that follows it: interleaved saves used to
    write one shared `file_moves.json.tmp` and promote it half-written, and
    `_load` runs once, at startup, so the damage stayed invisible until the
    restart after a crash - the ONE case the intent rows exist for. A ledger
    that reads back as `[]` un-muzzles lane A on every moved path, which is
    the single failure docs/FILE_MOVES.md exists to prevent."""

    def __init__(self, state_dir: Path, now: Callable[[], float] = time.time) -> None:
        self._path = Path(state_dir) / LEDGER_FILENAME
        self._now = now
        # Reentrant: record_attempt_failed calls record, and the readers are
        # called from inside the writers.
        self._lock = threading.RLock()
        self._entries: list[dict[str, Any]] = []
        self._relocations: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        if isinstance(entries, list):
            self._entries = [e for e in entries if isinstance(e, dict) and "id" in e]
        moved = data.get("relocations") if isinstance(data, dict) else None
        if isinstance(moved, list):
            self._relocations = [r for r in moved
                                 if isinstance(r, dict) and r.get("old") and r.get("new")]

    def _tmp_path(self) -> Path:
        """A scratch name no other writer can be holding (res-companion-2).

        The lock covers the threads of ONE companion; a second process on the
        same state directory (a supervisor relaunch racing the dying tray,
        CR-93's shape) is covered by nothing, and the shared
        `file_moves.json.tmp` there is published over the live ledger
        half-written. On Windows the loser's `replace` also raises
        PermissionError, which was caught and logged and lost."""
        return self._path.with_name(
            f"{self._path.name}.{os.getpid()}.{next(_TMP_SEQ)}.tmp")

    def _save(self) -> None:
        tmp: Optional[Path] = None
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._tmp_path()
                tmp.write_text(json.dumps(
                    {"entries": self._entries[-LEDGER_MAX_ENTRIES:],
                     "relocations": self._relocations[-RELOCATION_MAX_ENTRIES:]},
                    indent=1), encoding="utf-8")
                tmp.replace(self._path)
                tmp = None
            except OSError:
                log.exception("file moves: could not write the ledger")
            finally:
                # A unique tmp name is only free if the loser tidies up after
                # itself: state/ is not somewhere anything ever prunes.
                if tmp is not None:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

    def entry(self, move_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            for e in self._entries:
                if e.get("id") == move_id:
                    return e
            return None

    def record_relocation(self, old_local: str, new_local: str) -> None:
        """Lane B carried this file to the place the server says it moved to.

        res-companion-2 (2026-09-18). Lane B follows a hand move minutes
        before the dashboard's detection turns the same move into a
        `file_moves` command, and it cannot write an intent row because the
        move has no id yet -- the dashboard mints that later. So it writes
        what it DOES know, and `apply_move` accepts it as the evidence its
        resume branch needs: without this the redelivered command finds
        nothing at the old path, answers ok with no paths, and app.py skips
        the Resolve relink entirely, leaving every clip under the moved
        folder Media Offline while the MOVES history says the machine
        followed.
        """
        if not old_local or not new_local:
            return
        with self._lock:
            now = float(self._now())
            key = _cmp_key(old_local)
            self._relocations = [r for r in self._relocations
                                 if _cmp_key(r.get("old")) != key]
            self._relocations.append({"old": str(old_local), "new": str(new_local),
                                      "at": now})
            self._prune_relocations(now)
            self._save()

    def relocated_folder(self, old_dir: str, new_dir: str) -> bool:
        """Did lane B carry a whole FOLDER from `old_dir` to `new_dir`?

        comp-sync-3 (2026-09-18b): lane B relocates files, one row each, and
        the dashboard describes a hand-moved folder with a single is_dir
        command naming the directory - so `relocation_to`'s exact pair could
        never match it. Evidence here is every row under `old_dir` landing at
        the SAME relative path under `new_dir`: one row pointing anywhere else
        means the folder was only partly followed, and a partly followed
        folder must not be relinked as if it were complete. The prefixes are
        folded with `_cmp_key` like every other comparison in this module
        (CR-90: a Mac's NFD spelling of the folder is not `==` the NAS's NFC).
        """
        with self._lock:
            now = float(self._now())
            self._prune_relocations(now)
            old_root = _cmp_key(old_dir).rstrip("\\/") + os.sep
            new_root = _cmp_key(new_dir).rstrip("\\/") + os.sep
            matched = False
            for row in self._relocations:
                old_key = _cmp_key(row.get("old"))
                if not old_key.startswith(old_root):
                    continue
                if _cmp_key(row.get("new")) != new_root + old_key[len(old_root):]:
                    return False
                matched = True
            return matched

    def relocation_to(self, old_local: str, new_local: str) -> bool:
        """Did lane B carry `old_local` to exactly `new_local` recently?

        Both halves are checked (res-companion-2): a machine that merely
        DOWNLOADED the file at the new path never wrote a row here, and must
        still answer "nothing at the old path on this machine".
        """
        with self._lock:
            now = float(self._now())
            self._prune_relocations(now)
            old_key, new_key = _cmp_key(old_local), _cmp_key(new_local)
            return any(_cmp_key(r.get("old")) == old_key
                       and _cmp_key(r.get("new")) == new_key
                       for r in self._relocations)

    def _prune_relocations(self, now: float) -> None:
        kept = []
        for r in self._relocations:
            try:
                age = now - float(r.get("at") or 0.0)
            except (TypeError, ValueError):
                continue
            if age <= RELOCATION_MAX_AGE_SECONDS:
                kept.append(r)
        self._relocations = kept[-RELOCATION_MAX_ENTRIES:]

    def record(self, move: dict[str, Any], ok: bool, detail: str,
               state: Optional[str] = None, paths: Optional[tuple[str, str]] = None,
               relink_pending: bool = False) -> dict[str, Any]:
        with self._lock:
            return self._record_locked(move, ok, detail, state, paths, relink_pending)

    def _record_locked(self, move: dict[str, Any], ok: bool, detail: str,
                       state: Optional[str], paths: Optional[tuple[str, str]],
                       relink_pending: bool) -> dict[str, Any]:
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
        elif entry["state"] == STATE_NOT_SYNCED_HERE:
            # comp-sync-2 / res-companion-1 (2026-09-18b): section 4b returns
            # `paths=None` on purpose - the local copy went to the lane B
            # trash and nothing may be repointed at it - so this row must not
            # inherit a destination from the intent row that preceded it. A
            # `not_synced_here` move has no new path anywhere, by definition.
            pass
        elif previous.get("old_local"):
            entry["old_local"] = previous["old_local"]
            entry["new_local"] = previous.get("new_local", "")
        self._entries = [e for e in self._entries if e.get("id") != move["id"]] + [entry]
        self._entries = self._entries[-LEDGER_MAX_ENTRIES:]
        self._save()
        return entry

    def record_intent(self, move: dict[str, Any], old_local: str,
                      new_local: str) -> dict[str, Any]:
        """Write the `applying` row for a move about to be made
        (res-companion-1).

        The paths are precomputed here because they are what both recovery
        routes need and what the crash used to take with it: `moved_to()` can
        then still offer the watcher's one-click relink, and `apply_move` can
        finish the job on the redelivered command.

        comp-sync-b-2 (2026-09-11b): `relink_pending` is FALSE here, and both
        readers skip `applying` rows besides. An intent row is written before
        the first filesystem call, so the file is still at the old path -- a
        row that looked like a finished move sent _relink_pending_moves() and
        the watcher's "RELINK IT" dialog at a `new_local` that does not
        exist, taking every clip under it Media Offline and journalling it as
        a real Resolve mutation. The move's own completion row sets
        relink_pending properly (app._apply_file_moves), including on the
        crash-resume path."""
        return self.record(move, ok=False, detail="applying it on this machine",
                           state=STATE_APPLYING, paths=(old_local, new_local),
                           relink_pending=False)

    def record_attempt_failed(self, move: dict[str, Any], detail: str) -> dict[str, Any]:
        """A move that could not be applied THIS time (RES-1).

        Returns the entry: `state` is `retryable` with a `next_attempt_at`
        until the attempt cap or the week runs out, and `blocked` after that.
        Blocked is an answer the dashboard shows; it is never a silence, and
        the local copy is still exactly where it was either way."""
        with self._lock:
            return self._attempt_failed_locked(move, detail)

    def _attempt_failed_locked(self, move: dict[str, Any],
                               detail: str) -> dict[str, Any]:
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
        with self._lock:
            entries = list(self._entries)
        return [e for e in entries
                if e.get("relink_pending") and e.get("old_local")
                # comp-sync-b-2: an `applying` row is an INTENT. Its
                # new_local is where the file is going, not where it is.
                and e.get("state") != STATE_APPLYING
                # comp-sync-2 (2026-09-18b): and a `not_synced_here` row is a
                # file in the lane B trash, which is never a relink target -
                # prune_trash deletes it while the 30 day relink window is
                # still open.
                and e.get("state") != STATE_NOT_SYNCED_HERE
                and float(e.get("at") or 0) >= cutoff]

    def clear_relink_pending(self, move_id: int) -> None:
        with self._lock:
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
        with self._lock:
            entries = list(self._entries)
        for entry in reversed(entries):
            old = entry.get("old_local")
            if not old or not entry.get("new_local"):
                continue
            if entry.get("state") == STATE_NOT_SYNCED_HERE:
                # comp-sync-2 / res-companion-1 (2026-09-18b): section 4b put
                # this machine's copy in the lane B trash and answered with no
                # paths for exactly this reason. A row that still carries them
                # (one written by 0.9.75 before this fix, read after an
                # upgrade) must not become the watcher's "CCSync can repoint
                # Resolve to where it is now" - `_moved_destination_is_there`
                # passes, because the file really is in the trash, and
                # prune_trash then deletes it under the relinked clips.
                continue
            if entry.get("state") == STATE_APPLYING and not _move_is_on_disk(entry):
                # comp-sync-b-2 (2026-09-11b): an `applying` row is written
                # BEFORE the first filesystem call, so on its own it says
                # nothing about where the file is. res-companion-1 wants the
                # one-click relink offered after a crash BETWEEN the rename
                # and record(), and the disk is the only witness to which of
                # the two crashes happened: offer it when the file really is
                # at new_local, refuse it when it is not. Without this the
                # dialog told the editor, in writing, "Your copy has already
                # been moved to match" for a move that never happened.
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
        with self._lock:
            entries = list(self._entries)
        for e in entries:
            # RES-1 (2026-08-28): a move that has NOT been applied here keeps
            # its exclusion for as long as it is unresolved, not for a day.
            # The old path still holds the file (that is why the move failed),
            # so letting the window lapse is letting lane A -- which never
            # deletes -- put the file back on the NAS at the path the admin
            # cleared, which is the failure this feature exists to prevent.
            # res-companion-1: an `applying` row is a move this machine was
            # interrupted part-way through, i.e. the one state where we least
            # know where the file is. It holds its exclusion open too.
            unresolved = e.get("state") in (STATE_RETRYABLE, STATE_BLOCKED, STATE_APPLYING)
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
