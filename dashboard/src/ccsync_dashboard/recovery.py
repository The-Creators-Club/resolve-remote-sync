"""Recovering from something, without a root shell.

SYS-15 (resilience sweep 2026-08-28), built 2026-08-29 as wave 5. The owner
of this fleet is not a systems administrator, and every one of the five
recovery paths `docs/BACKUP_RESTORE.md` documented was a root SSH session
that asked him for judgements he has no way to make: is `apps` a dataset or
a plain directory (which decides which of two `cp` lines is even correct, and
whether a snapshot of it exists at all); which snapshot; is everything
written since it expendable; has the fleet stopped writing; and -- platform
dependent, and destructive if wrong -- `chown` is REQUIRED on TrueNAS and
DELETES the share's ACL on DSM.

Four things live here.

**(a) Snapshot browse-and-restore, into a quarantine directory.** THE WHOLE
POINT IS THAT NOTHING IS OVERWRITTEN. A restore writes only into
`<project>/.restored-<ts>/`, so the destructive judgement ("is everything
since this snapshot expendable?") disappears: a wrong snapshot costs disk
space and nothing else, and the two copies can be compared afterwards by a
person looking at files rather than at a shell. Nothing in this module
deletes, overwrites or chowns anything that was already there -- if a
destination exists, the restore is REFUSED rather than merged.

**(b) The admin-side Resolve undo** is in `db.py` (v41) and `api.py`: it is a
command on the report channel, not a filesystem operation, because the
journal it replays lives on the editor's PC.

**(c) The guided runbook**, which is the honest half. Where this server can
VERIFY a fact -- the NAS answered and named itself, a snapshot task covers a
dataset, the Projects tree is mounted where we think -- the printed command
carries the customer's real pool name and platform. Where it cannot, IT
PRINTS NO COMMAND: an unverified fact produces a refusal naming what is
missing and how to supply it. A generated `zfs rollback` with a guessed
dataset in it is worse than no command at all, and "the doc said tank" is how
somebody rolls back the wrong pool.

**(d) The restore drill.** A backup nobody has restored from is a hypothesis.
The drill copies one real file out of a snapshot into a scratch directory
under `/data`, compares it byte for byte, deletes the scratch copy and
records the DATE through `protection.record_restore_drill` -- the same store
the admin's [ RECORD A RESTORE ] button writes, so the protection panel's
line needs no edit and cannot disagree with itself.

SNAPSHOTS ARE NOT VISIBLE FROM A CONTAINER BY DEFAULT. `/projects` is a bind
mount of the Projects directory; ZFS's `.zfs/snapshot` belongs to the DATASET
above it and DSM's live under `/volume<N>/@sharesnap`. So the browse path is
a mount this deployment was told about (DASH_SNAPSHOT_DIR), and where it is
absent every self-service path here says so plainly and the runbook falls
back to printing commands. Unset is "this server was never told", never "there
are no snapshots" -- the same rule protection.py's dataset lines follow.

NOTHING HERE FORMATS A SECRET, and no NAS call is unbounded: every external
read fails to "cannot verify" rather than to a broken page, because the page
an owner opens after losing something is the last page in this product that
may fail to render.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import db

log = logging.getLogger("ccsync.dashboard.recovery")

# Where a container can see the snapshots. One directory whose ENTRIES are
# snapshots: `/mnt/<pool>/<dataset>/.zfs/snapshot` on TrueNAS,
# `/volume1/@sharesnap/<share>` on DSM, mounted read-only into the container.
# Unset is not "there are none" (see the module docstring).
ENV_SNAPSHOT_DIR = "DASH_SNAPSHOT_DIR"
# The path from ONE snapshot's root to the Projects tree inside it, e.g.
# `Creators_Club/Projects`. Empty means the snapshot root IS the Projects
# tree. Named separately because the mount above may be of the dataset, of
# the share, or of the tree itself, and guessing which is exactly the class of
# guess this package exists to stop making.
ENV_SNAPSHOT_SUBPATH = "DASH_SNAPSHOT_PROJECTS_SUBPATH"
# The container this dashboard runs in, as `docker stop` would name it. Only
# ever used to SUBSTITUTE into a printed command; unset means the runbook
# refuses to print the commands that need it.
ENV_CONTAINER_NAME = "DASH_CONTAINER_NAME"

# The quarantine directory's name. THE LEADING DOT IS LOAD-BEARING:
# provision.scan_project_dirs and marked_ancestor both prune `os.walk` at any
# directory starting with "." (provision.py:340,406), so a restored copy of a
# project -- which carries a copy of that project's `.ccsync-project` marker --
# cannot be discovered as a SECOND project claiming the same slug. That is the
# `duplicate_slug_dirs` notice, and a recovery tool that raised it would be
# creating a new incident during an existing one.
QUARANTINE_PREFIX = ".restored-"

# Ceilings. A project tree is millions of files on this fleet; a page and a
# collector thread are not allowed to walk all of them. Truncation is
# REPORTED, never silent: a preview that stopped early says so, and a restore
# that would exceed the file ceiling is refused rather than half-done.
MAX_SCAN_FILES = 50_000
MAX_PREVIEW_ROWS = 300
MAX_RESTORE_FILES = 20_000

# The drill's scratch area, under the dashboard's own data directory (the one
# place a container is always allowed to write). Deleted at the end of every
# drill, and swept at the start of the next one.
DRILL_DIR_NAME = "restore-drills"
# A drill has to be small enough to run on a page click and real enough to
# prove something: one actual file out of a real snapshot, hashed.
DRILL_MAX_BYTES = 64 * 1024 * 1024

# The last few restores and drills, for the page. `meta`, not a table: this is
# a small current picture with no history worth querying, the same call
# protection.py made about its own results (and the reason schema v40 stayed
# unused).
RESTORES_META = "recovery_restores"
DRILLS_META = "recovery_drills"
HISTORY_KEEP = 20


class RecoveryError(Exception):
    """A refusal an owner reads. `status` is the HTTP code the route uses.

    Every one of these names what is missing and what to do about it: this
    module is used by somebody who has just lost something, and "400 Bad
    Request" is not a recovery step.
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------- snapshots

def snapshot_root(env: dict[str, str] | None = None) -> Path | None:
    raw = ((env if env is not None else os.environ).get(ENV_SNAPSHOT_DIR) or "").strip()
    return Path(raw) if raw else None


def snapshot_subpath(env: dict[str, str] | None = None) -> str:
    raw = ((env if env is not None else os.environ).get(ENV_SNAPSHOT_SUBPATH) or "").strip()
    return raw.strip("/")


def list_snapshots(env: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], str]:
    """(snapshots newest first, why there are none).

    The second half is never empty when the first is: "this server cannot see
    any snapshots" and "there are no snapshots" are different facts and only
    one of them is an emergency. Bounded: one directory listing, no recursion,
    and every failure becomes a sentence rather than an exception.
    """
    root = snapshot_root(env)
    if root is None:
        # OPS-3 (usability + resilience sweep 2026-09-03): NOTHING set this
        # variable until 2026-09-04, so the honest sentence is about the
        # DEPLOYMENT rather than about this server's knowledge. A deploy from
        # server/install_dashboard_app.py fills it in by itself now; an older
        # one, a pasted compose file or a Synology needs the mount adding.
        return [], (
            f"this deployment was never given a snapshot mount, so this server "
            f"cannot read any snapshot ({ENV_SNAPSHOT_DIR} is not set on the "
            f"dashboard container). Re-run the deploy, or mount the NAS's "
            f"snapshots into the container read-only and set {ENV_SNAPSHOT_DIR} "
            f"to that path.")
    try:
        if not root.is_dir():
            return [], (f"{root} is not a directory this server can read. Check the "
                        f"container's mount for {ENV_SNAPSHOT_DIR}.")
        entries = [e for e in root.iterdir() if e.is_dir()]
    except OSError as exc:
        return [], (f"this server could not read {root} ({exc.strerror or exc}). The "
                    f"snapshot mount may be gone.")
    out: list[dict[str, Any]] = []
    for entry in entries:
        try:
            stamp = entry.stat().st_mtime
        except OSError:
            stamp = 0.0
        out.append({"name": entry.name, "mtime": stamp})
    # Name descending: every snapshot this product creates is named with a UTC
    # timestamp (`ccsync-%Y%m%d-%H%M`, `ccsync-daily-%Y%m%d`, DSM's
    # `GMT+NN-YYYY.MM.DD-HH.MM.SS`), so lexical order is chronological within
    # a naming scheme, and mtime breaks the tie between schemes.
    out.sort(key=lambda r: (r["name"], r["mtime"]), reverse=True)
    if not out:
        return [], (f"there are no snapshots under {root}. Either none has been taken "
                    f"yet, or that mount points somewhere else.")
    return out, ""


def _snapshot_dir(name: str, env: dict[str, str] | None = None) -> Path:
    """The directory holding one snapshot's Projects tree. Refuses a name
    that is not a plain entry of the snapshot root: this value comes off a
    form, and `..` in it would read any directory the container can see."""
    root = snapshot_root(env)
    if root is None:
        raise RecoveryError(
            "this deployment was never given a snapshot mount, so this server cannot "
            f"restore from one ({ENV_SNAPSHOT_DIR} is not set on the dashboard "
            "container). Re-run the deploy, or use the commands on the recovery page "
            "instead.", 409)
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise RecoveryError(f"{name!r} is not a snapshot name this server will accept")
    candidate = root / name
    try:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root.resolve()) or not candidate.is_dir():
            raise RecoveryError(f"there is no snapshot called {name} on this NAS", 404)
    except OSError as exc:
        raise RecoveryError(f"this server could not read the snapshot {name} ({exc})", 502)
    sub = snapshot_subpath(env)
    return (candidate / Path(*sub.split("/"))) if sub else candidate


# ------------------------------------------------------------- the project

def _project_label(conn: sqlite3.Connection, slug: str) -> str:
    row = conn.execute("SELECT label FROM projects WHERE slug=?", (slug,)).fetchone()
    if row is None:
        raise RecoveryError(f"there is no project called {slug!r} on this server", 404)
    label = str(row["label"] or "").strip().strip("/")
    if not label:
        raise RecoveryError(
            f"the project {slug!r} has no folder recorded on this server, so this "
            "server cannot tell which folder to restore into", 409)
    return label


def _under(root: Path, rel: str) -> Path:
    """`rel` under `root`, refusing anything that escapes. The same
    is_relative_to check api._safe_rel makes, for the same reason."""
    parts = [p for p in str(rel or "").split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise RecoveryError("that path escapes the project folder")
    target = root.joinpath(*parts)
    try:
        if not target.resolve().is_relative_to(root.resolve()):
            raise RecoveryError("that path escapes the project folder")
    except OSError:
        # A path that cannot be resolved has not been shown to be inside.
        raise RecoveryError("that path escapes the project folder")
    return target


def _live_project_dir(settings: Any, label: str) -> Path:
    projects_dir = str(getattr(settings, "projects_dir", "") or "")
    if not projects_dir or not Path(projects_dir).is_dir():
        raise RecoveryError(
            "the project tree on the server is not mounted on this dashboard "
            "(DASH_PROJECTS_DIR), so this server cannot restore anything into it. "
            "The recovery page's printed commands are the way through this one.", 409)
    return _under(Path(projects_dir), label)


def _walk(root: Path) -> tuple[dict[str, tuple[int, float]], bool]:
    """{rel posix: (size, mtime)} under `root`, and whether the walk was cut
    short at MAX_SCAN_FILES. Dot-directories are skipped, which is what keeps
    a previous `.restored-<ts>` (and `.stversions`) out of a comparison."""
    found: dict[str, tuple[int, float]] = {}
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        base = Path(dirpath)
        for name in filenames:
            if name.startswith("."):
                continue
            path = base / name
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            found[rel] = (int(stat.st_size), float(stat.st_mtime))
            if len(found) >= MAX_SCAN_FILES:
                truncated = True
                return found, truncated
    return found, truncated


def preview_restore(settings: Any, conn: sqlite3.Connection, slug: str,
                    snapshot: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """What restoring this snapshot of this project WOULD put back.

    Read-only, and it is the whole reason this is a browse-and-restore rather
    than a restore: an owner deciding between two snapshots is deciding on
    "does the file I lost appear in this one", which is a list of names, not a
    date.
    """
    label = _project_label(conn, slug)
    live = _live_project_dir(settings, label)
    source = _under(_snapshot_dir(snapshot, env), label)
    if not source.is_dir():
        raise RecoveryError(
            f"the snapshot {snapshot} holds no folder for {label}. Either the project "
            "did not exist yet when it was taken, or its folder has been renamed "
            "since (this server looks it up by the folder name it has now).", 404)
    snap_files, snap_cut = _walk(source)
    live_files, live_cut = ({}, False) if not live.is_dir() else _walk(live)
    missing, changed, unchanged = [], [], 0
    for rel, (size, mtime) in sorted(snap_files.items()):
        current = live_files.get(rel)
        if current is None:
            missing.append({"rel": rel, "bytes": size})
        elif current[0] != size:
            changed.append({"rel": rel, "bytes": size, "live_bytes": current[0]})
        else:
            unchanged += 1
    added = sorted(set(live_files) - set(snap_files))
    return {
        "slug": slug, "label": label, "snapshot": snapshot,
        "live_exists": live.is_dir(),
        "missing": missing[:MAX_PREVIEW_ROWS], "missing_count": len(missing),
        "missing_bytes": sum(int(m["bytes"]) for m in missing),
        "changed": changed[:MAX_PREVIEW_ROWS], "changed_count": len(changed),
        "changed_bytes": sum(int(c["bytes"]) for c in changed),
        "unchanged_count": unchanged,
        "added": added[:MAX_PREVIEW_ROWS], "added_count": len(added),
        "truncated": bool(snap_cut or live_cut),
        # Said on the page every time, not only in the docs: this is the
        # property that makes the choice above safe to get wrong.
        "note": ("Nothing here is overwritten. Whatever you restore is copied into a "
                 "new folder inside the project, and the files that are there now are "
                 "left exactly as they are."),
    }


def restore_into_quarantine(
    settings: Any, conn: sqlite3.Connection, slug: str, snapshot: str, actor: str,
    include_changed: bool = False, env: dict[str, str] | None = None,
    now: str | None = None,
    snapshot_before: Callable[[Any, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Copy what is missing (and optionally what differs) out of a snapshot
    into `<project>/.restored-<ts>/`.

    NOTHING IS OVERWRITTEN, NOTHING IS DELETED, NOTHING IS CHOWNED. The
    quarantine directory must not already exist; every file lands under it at
    the same relative path it has in the snapshot; a file that cannot be
    copied is counted and named, and the rest of the restore continues,
    because a partial recovery is worth more than none and the copy is
    additive either way.

    A NAS snapshot is taken first when the deployment can take one
    (`dashboard_update.snapshot_before`, best effort). This path is neither
    privileged nor recursive-destructive, but "snapshot before anything
    privileged and recursive" is this repo's rule and a restore is exactly the
    moment somebody would most regret its absence.
    """
    stamp = (now or db.utcnow_iso())
    label = _project_label(conn, slug)
    live = _live_project_dir(settings, label)
    if not live.is_dir():
        raise RecoveryError(
            f"there is no folder for {label} on the server to restore into. Restore "
            "the whole project folder with the commands on the recovery page, or "
            "create the project again first.", 409)
    # The preview's lists are CAPPED for display (MAX_PREVIEW_ROWS), so the
    # restore walks both trees again rather than working off the page's copy:
    # a restore that silently stopped at row 300 would be the worst possible
    # kind of half-recovery, one that looks complete.
    source = _under(_snapshot_dir(snapshot, env), label)
    if not source.is_dir():
        raise RecoveryError(
            f"the snapshot {snapshot} holds no folder for {label}.", 404)
    snap_files, _cut = _walk(source)
    live_files, _cut2 = _walk(live)
    rels = sorted(rel for rel in snap_files
                  if rel not in live_files
                  or (include_changed and live_files[rel][0] != snap_files[rel][0]))
    if not rels:
        raise RecoveryError(
            f"nothing in the snapshot {snapshot} is missing from {label} as it is now, "
            "so there is nothing to restore.", 409)
    if len(rels) > MAX_RESTORE_FILES:
        raise RecoveryError(
            f"that would restore {len(rels)} files, over this server's limit of "
            f"{MAX_RESTORE_FILES} in one go. Restore the folder with the commands on "
            "the recovery page instead: a restore this large is a transfer, not a "
            "click.", 409)
    target = live / f"{QUARANTINE_PREFIX}{stamp[:19].replace(':', '').replace('-', '')}"
    if target.exists():
        raise RecoveryError(
            f"{target.name} already exists in that project. A restore never writes "
            "into a folder that is already there: rename or delete it first.", 409)
    taken: dict[str, Any] = {"ok": False, "reason": "not attempted"}
    if snapshot_before is None:
        from .dashboard_update import snapshot_before as _snap
        snapshot_before = _snap
    try:
        taken = snapshot_before(settings, f"restore-{slug}")
    except Exception as exc:                                         # noqa: BLE001
        # Best effort, exactly like every other caller of it: a NAS that will
        # not snapshot must not be a NAS you cannot recover a file on.
        log.warning("pre-restore snapshot failed (continuing): %s", exc)
        taken = {"ok": False, "reason": str(exc)}
    copied, copied_bytes = 0, 0
    failed: list[str] = []
    try:
        target.mkdir(parents=True)
    except OSError as exc:
        # A tree mounted read-only, or a full pool. A refusal an owner can
        # read, never a traceback on the page they opened after losing
        # something.
        raise RecoveryError(
            f"this server could not create {target.name} in {label} "
            f"({exc.strerror or exc}). Nothing was changed.", 502)
    for rel in rels:
        src = source.joinpath(*rel.split("/"))
        dest = target.joinpath(*rel.split("/"))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            # copy2, and only ever onto a path inside `target`: the live file
            # of the same name is not opened, not renamed and not touched.
            shutil.copy2(src, dest)
            copied += 1
            copied_bytes += int(snap_files.get(rel, (0, 0))[0])
        except OSError as exc:
            failed.append(f"{rel} ({exc.strerror or exc})")
    result = {
        "ok": copied > 0,
        "slug": slug, "label": label, "snapshot": snapshot,
        "directory": target.as_posix(),
        "where": f"{label}/{target.name}",
        "files": copied, "bytes": copied_bytes,
        "failed": failed[:20], "failed_count": len(failed),
        "include_changed": bool(include_changed),
        "nas_snapshot": taken,
        "at": stamp, "by": actor,
    }
    _remember(conn, RESTORES_META, {
        "at": stamp, "by": actor, "slug": slug, "snapshot": snapshot,
        "files": copied, "bytes": copied_bytes, "where": result["where"],
        "failed": len(failed),
    })
    try:
        db.audit(conn, actor, "recovery.restore", slug,
                 {"snapshot": snapshot, "files": copied, "into": result["where"]},
                 now=stamp)
        conn.commit()
    except sqlite3.Error:
        log.exception("recovery: could not record the restore (the files are copied)")
    log.warning("recovery: %s restored %d file(s) from %s into %s",
                actor, copied, snapshot, result["where"])
    return result


# ------------------------------------------------------------- the drill

def _drill_root(settings: Any) -> Path:
    data = Path(str(getattr(settings, "db_path", "/data/dashboard.db") or "")).parent
    return data / DRILL_DIR_NAME


def _pick_drill_file(source: Path) -> tuple[Path, int] | None:
    """The first small real file in a snapshot, or None. Small on purpose: a
    drill that copies 40 GB is a drill nobody runs."""
    for dirpath, dirnames, filenames in os.walk(source, onerror=lambda _e: None):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = Path(dirpath) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= DRILL_MAX_BYTES:
                return path, int(size)
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_drill(settings: Any, conn: sqlite3.Connection, actor: str,
              env: dict[str, str] | None = None, now: str | None = None,
              snapshot: str = "") -> dict[str, Any]:
    """Restore one real file out of a real snapshot into a scratch path, prove
    it came back byte for byte, delete it, and record the date.

    A backup nobody has restored from is a hypothesis (SYS-15d). This is the
    smallest thing that is not one: it exercises the mount, the snapshot, the
    read and the compare, and it writes ONLY under `<data>/restore-drills/`,
    which is the dashboard's own directory and never the tree.

    A failure records NOTHING on the protection panel, deliberately: the panel
    reads a date meaning "a restore worked here", and a drill that could not
    read the snapshot must leave that line MISSING rather than green.
    """
    stamp = now or db.utcnow_iso()
    snapshots, why = list_snapshots(env)
    if not snapshots:
        raise RecoveryError(
            f"this server cannot rehearse a restore: {why}", 409)
    name = (snapshot or snapshots[0]["name"]).strip()
    source = _snapshot_dir(name, env)
    if not source.is_dir():
        raise RecoveryError(
            f"the snapshot {name} does not hold a project tree where this server was "
            f"told to look ({ENV_SNAPSHOT_SUBPATH}).", 409)
    picked = _pick_drill_file(source)
    if picked is None:
        raise RecoveryError(
            f"the snapshot {name} holds no file small enough to rehearse with "
            f"(under {DRILL_MAX_BYTES // (1024 ** 2)} MB).", 409)
    src, size = picked
    root = _drill_root(settings)
    scratch = root / stamp[:19].replace(":", "").replace("-", "")
    try:
        # Sweep first: a drill killed halfway through (a container restart)
        # must not leave copies behind for ever. Best effort.
        if root.is_dir():
            for entry in root.iterdir():
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
        scratch.mkdir(parents=True, exist_ok=True)
        dest = scratch / src.name
        shutil.copy2(src, dest)
        restored_size = dest.stat().st_size
        same = restored_size == size and _sha256(dest) == _sha256(src)
    except OSError as exc:
        raise RecoveryError(
            f"the rehearsal could not copy a file out of the snapshot {name}: "
            f"{exc.strerror or exc}", 502)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    result = {
        "ok": bool(same), "at": stamp, "by": actor, "snapshot": name,
        "file": src.name, "bytes": size,
        "detail": ("restored one file out of this snapshot and it came back byte for "
                   "byte" if same else
                   "the file that came back is NOT the file in the snapshot"),
    }
    _remember(conn, DRILLS_META, result)
    if same:
        from . import protection

        protection.record_restore_drill(conn, actor or "the restore rehearsal",
                                        date=stamp[:10], now=stamp)
    try:
        db.audit(conn, actor, "recovery.drill", name,
                 {"ok": bool(same), "file": src.name, "bytes": size}, now=stamp)
        conn.commit()
    except sqlite3.Error:
        log.exception("recovery: could not record the drill")
    log.info("recovery: restore rehearsal from %s: %s", name, result["detail"])
    return result


def _remember(conn: sqlite3.Connection, key: str, entry: dict[str, Any]) -> None:
    """Keep the last HISTORY_KEEP of something in `meta`. Best effort: losing
    the note must never lose the operation it is a note about."""
    try:
        stored = db.meta_get_json(conn, key)
        rows = stored if isinstance(stored, list) else []
        rows = ([entry] + rows)[:HISTORY_KEEP]
        db.meta_set_json(conn, key, rows)
    except sqlite3.Error:
        log.exception("recovery: could not record %s", key)


def history(conn: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    try:
        stored = db.meta_get_json(conn, key)
    except sqlite3.Error:
        return []
    return [r for r in stored if isinstance(r, dict)] if isinstance(stored, list) else []


# ------------------------------------------------------------- the runbook
#
# Facts first, then steps. The rule that makes this honest: a step that needs
# a fact this server could not VERIFY is not printed. It becomes a refusal
# that names the fact and how to supply it.


@dataclass(frozen=True)
class Fact:
    """One thing about this deployment, and whether this server KNOWS it.

    `verified` means positive evidence: the NAS answered, the directory is
    there, a snapshot task names this dataset. A value that is merely
    CONFIGURED is not verified -- `DASH_TREE_DATASET` being set proves
    somebody typed something, not that it is a dataset, and the difference
    between those two is the `apps`-is-a-directory case (CR-10) that makes
    half of BACKUP_RESTORE.md's commands wrong on the live NAS.
    """
    key: str
    label: str
    value: str = ""
    verified: bool = False
    why_not: str = ""
    fix: str = ""


@dataclass
class Step:
    """One step of a plan: something the dashboard can do, something a person
    must do, a command block, or a refusal to print one."""
    kind: str                                    # action | note | command | refusal
    title: str
    body: str = ""
    commands: list[str] = field(default_factory=list)
    href: str = ""
    needs: tuple[str, ...] = ()


def _nas_identity(settings: Any, probe: Callable[[], dict[str, str] | None] | None = None
                  ) -> tuple[str, str]:
    """(what the NAS says it is, why we could not ask). ONE bounded call.

    This is the fact the whole platform branch hangs off: `chown` is required
    on TrueNAS and DELETES the share's ACL on DSM, so a runbook that guesses
    the platform can print the command that destroys the thing it is
    recovering.
    """
    try:
        if probe is not None:
            info = probe()
        else:
            from .nas import capability
            from .nas.factory import make_nas_client, nas_configured

            if not nas_configured(settings):
                return "", ("no NAS credential is configured on this dashboard, so it "
                            "cannot ask the NAS what it is")
            client = make_nas_client(settings)
            try:
                # `ping` is on the Protocol every backend answers; DSM has no
                # `system_info` at all, so the ANSWER is the evidence and the
                # version string is only decoration where it exists.
                client.ping()
                asker = capability(client, "system_info")
                info = asker() if asker is not None else {}
            finally:
                closer = getattr(client, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:                                # noqa: BLE001
                        pass
    except Exception as exc:                                         # noqa: BLE001
        log.debug("recovery: the NAS did not answer", exc_info=True)
        return "", f"the NAS did not answer ({type(exc).__name__})"
    if info is None:
        return "", "the NAS did not answer"
    kind = str(getattr(settings, "nas_kind", "") or "").strip().lower()
    if not kind:
        return "", "this dashboard has no NAS kind configured, so it cannot tell a "\
                   "TrueNAS from a Synology, and the two need different commands"
    return kind, ""


def _dataset_fact(key: str, label: str, dataset: str, var: str,
                  tasks: list[dict[str, Any]] | None, is_dsm: bool) -> Fact:
    """A dataset name is VERIFIED only when the NAS's own snapshot task list
    names it (or a recursive parent of it).

    That is deliberately a stronger bar than "somebody set the variable": on
    this fleet's own NAS `/mnt/tank/apps` is a plain directory with no task at
    all, `.zfs` does not exist under it, and the two `cp` lines in
    BACKUP_RESTORE.md §4c differ by exactly that fact. Unverified here means
    no command containing this name is printed.
    """
    if not dataset:
        return Fact(key, label, "", False,
                    f"this server has not been told which dataset {label} is on",
                    f"set {var} on the dashboard container")
    if is_dsm:
        return Fact(key, label, dataset, False,
                    "this is a Synology: DSM's snapshot schedules live in the Snapshot "
                    "Replication package, which this server has no way to read, so it "
                    "cannot confirm that this share is snapshotted",
                    "check the schedule in DSM, Snapshot Replication")
    if tasks is None:
        return Fact(key, label, dataset, False,
                    "this server could not ask the NAS whether anything snapshots that "
                    "dataset (no NAS credential, or the NAS did not answer)",
                    "configure this dashboard's NAS credential, then reload this page")
    for task in tasks:
        own = str(task.get("dataset") or "").strip()
        if own and (own == dataset
                    or (task.get("recursive") and dataset.startswith(own + "/"))):
            return Fact(key, label, dataset, True)
    return Fact(key, label, dataset, False,
                f"the NAS has {len(tasks)} snapshot task(s) and none of them covers "
                f"{dataset}, so this server cannot confirm it is a dataset with "
                f"snapshots behind it rather than a plain directory",
                # UX-18 (usability sweep 2026-09-03): this used to name a repo
                # script, and the admin reading it has a container and a
                # browser. The wizard's "Protect your data" task is the same
                # job with nothing to check out.
                "set up snapshots on the SETUP page, under 'Protect your data', "
                "or correct the variable naming it")


def gather_facts(settings: Any, conn: sqlite3.Connection,
                 env: dict[str, str] | None = None,
                 tasks_fn: Callable[[], list[dict[str, Any]] | None] | None = None,
                 nas_probe: Callable[[], dict[str, str] | None] | None = None,
                 ) -> dict[str, Fact]:
    """Everything the runbook may substitute into a command, each with whether
    this server actually knows it. Never raises."""
    env = dict(os.environ) if env is None else dict(env)
    kind, why = _nas_identity(settings, nas_probe)
    is_dsm = (kind or str(getattr(settings, "nas_kind", "") or "")).lower() == "synology"
    facts: dict[str, Fact] = {}
    facts["platform"] = Fact(
        "platform", "which kind of NAS this is",
        {"truenas": "TrueNAS", "synology": "Synology DSM"}.get(kind, kind or ""),
        bool(kind), why or "",
        "check the NAS host, user and API key on Settings, then reload this page")
    tasks: list[dict[str, Any]] | None
    try:
        if tasks_fn is not None:
            tasks = tasks_fn()
        else:
            from . import protection

            tasks = protection.nas_probe(settings).tasks()
    except Exception:                                                # noqa: BLE001
        log.debug("recovery: the snapshot task probe raised", exc_info=True)
        tasks = None
    from . import protection

    facts["tree_dataset"] = _dataset_fact(
        "tree_dataset", "the project tree",
        (env.get(protection.ENV_TREE_DATASET) or "").strip(),
        protection.ENV_TREE_DATASET, tasks, is_dsm)
    facts["apps_dataset"] = _dataset_fact(
        "apps_dataset", "this dashboard's own data",
        (env.get(protection.ENV_APPS_DATASET) or "").strip(),
        protection.ENV_APPS_DATASET, tasks, is_dsm)
    pool = facts["tree_dataset"].value.split("/")[0] if facts["tree_dataset"].verified else ""
    facts["pool"] = Fact(
        "pool", "the storage pool the footage is on", pool, bool(pool),
        "" if pool else "this follows from the project tree's dataset, which this "
                        "server has not confirmed",
        facts["tree_dataset"].fix)
    projects_dir = str(getattr(settings, "projects_dir", "") or "")
    mounted = bool(projects_dir) and Path(projects_dir).is_dir()
    facts["projects_dir"] = Fact(
        "projects_dir", "where this dashboard reads the project tree",
        projects_dir, mounted,
        "" if mounted else "the project tree is not mounted on this dashboard",
        "mount the Projects tree into the dashboard container (DASH_PROJECTS_DIR)")
    snapshots, snap_why = list_snapshots(env)
    facts["snapshots"] = Fact(
        "snapshots", "snapshots this dashboard can read for itself",
        (f"{len(snapshots)} snapshot(s), newest {snapshots[0]['name']}"
         if snapshots else ""),
        bool(snapshots), snap_why,
        # OPS-3: the deploy sets this itself since 2026-09-04, so the first
        # thing to try is the one an admin can do without a shell.
        f"re-run the deploy of this dashboard, which mounts them and sets "
        f"{ENV_SNAPSHOT_DIR}; site.toml [tree] snapshot_dir names the directory "
        f"where the deploy cannot work it out")
    container = (env.get(ENV_CONTAINER_NAME) or "").strip()
    facts["container"] = Fact(
        "container", "what this dashboard's container is called", container,
        bool(container),
        "" if container else "this server was not told the name of the container it "
                             "runs in, and it cannot see it from inside",
        f"set {ENV_CONTAINER_NAME} on the dashboard container "
        "(docker ps on the NAS names it)")
    return facts


@dataclass(frozen=True)
class Problem:
    """One thing that can have gone wrong, in the owner's words.

    A registry row, like `protection.LINES` and `alerts.ALERT_KINDS`: adding a
    recovery is adding a row, and the page, the wizard and the tests all pick
    it up with no second edit.
    """
    key: str
    question: str
    detail: str
    build: Callable[[dict[str, Fact], dict[str, Any]], list[Step]]


def _command_step(title: str, body: str, commands: list[str],
                  needs: tuple[str, ...], facts: dict[str, Fact]) -> Step:
    """A command block, or the refusal that replaces it.

    THIS FUNCTION IS THE FINDING. Every command this page prints is generated
    from facts this server verified; where one is missing, nothing is printed
    with a placeholder in it, because a command with a guessed pool name in it
    is a command somebody will paste into a root shell.
    """
    missing = [facts[key] for key in needs
               if key not in facts or not facts[key].verified]
    if missing:
        lines = "; ".join(
            f"{fact.label}: {fact.why_not or 'not confirmed'} ({fact.fix})"
            for fact in missing)
        return Step(
            "refusal",
            f"{title}: this server will not print these commands",
            body=("Some of what these commands need is not something this server has "
                  f"been able to confirm, and it will not guess at it. {lines}. Until "
                  "then, follow docs/BACKUP_RESTORE.md by hand with somebody who can "
                  "check the answers on the NAS itself."),
            needs=needs)
    substituted = [
        line.format(**{key: fact.value for key, fact in facts.items()})
        for line in commands
    ]
    return Step("command", title, body=body, commands=substituted, needs=needs)


def _stop_the_fleet_step() -> Step:
    return Step(
        "action",
        "Stop the fleet writing first",
        body=("Every editor's computer is still syncing. Put the fleet on hold before "
              "you put anything back, or the machines will push the state you are "
              "undoing straight back up."),
        href="/fleet")


def _plan_project(facts: dict[str, Fact], ctx: dict[str, Any]) -> list[Step]:
    steps = [
        Step("action",
             "Restore it here, into a new folder inside the project",
             body=("Pick the project and a snapshot, see what is missing, and this "
                   "server copies it back into a new folder called .restored-<date> "
                   "inside that project. Nothing that is there now is touched or "
                   "overwritten, so picking the wrong snapshot costs disk space and "
                   "nothing else. Then move what you want back yourself."),
             href="/admin/recovery#restore"),
        Step("note",
             "Look in the deleted-files folder first, if it was recent",
             body=("A file an editor overwrote or deleted in the last year is usually "
                   "still in the .stversions folder inside that project on the server, "
                   "with a timestamp in its name. That is a plain copy over the "
                   "network share and needs nobody's help.")),
    ]
    if not facts["snapshots"].verified:
        steps.append(_command_step(
            "Restore it over SSH instead",
            ("This server cannot read the snapshots itself, so this is the manual "
             "route. Run it on the NAS, as an administrator, and change nothing else."),
            ["ls /mnt/{tree_dataset}/.zfs/snapshot/",
             "cp -a \"/mnt/{tree_dataset}/.zfs/snapshot/<SNAPSHOT>/<PROJECT>/<FILE>\" \\",
             "      \"/mnt/{tree_dataset}/<PROJECT>/\"",
             "chown broll:editors \"/mnt/{tree_dataset}/<PROJECT>/<FILE>\""],
            ("platform", "tree_dataset"), facts))
    return steps


def _plan_dashboard_db(facts: dict[str, Fact], ctx: dict[str, Any]) -> list[Step]:
    return [
        Step("action",
             "Put back one of this dashboard's own backups",
             body=("This dashboard takes a backup of its databases before every "
                   "update, and it can put one back by itself. That covers the case "
                   "this almost always is: an update went wrong. It does NOT need a "
                   "shell and it does not need the NAS."),
             href="/admin/packages#dashboard-update"),
        Step("note",
             "What a restore of this database costs",
             body=("Footage is not in it. What is in it is who may sync what: "
                   "projects, editors, computers and their ticks. After a restore, "
                   "check the Projects page against the fleet: a tick made since the "
                   "backup is not re-discoverable and has to be made again.")),
        _command_step(
            "Restore it from a NAS snapshot instead",
            ("Only when the backups above are gone too. The container must be stopped "
             "first: it holds the file open, and copying over an open database is how "
             "a working one becomes a broken one."),
            ["sudo docker stop {container}",
             "sudo cp -a /mnt/{apps_dataset}/.zfs/snapshot/<SNAPSHOT>/ccsync-dashboard/data/dashboard.db \\",
             "           /mnt/{apps_dataset}/ccsync-dashboard/data/dashboard.db",
             "sudo chown 3000:3000 /mnt/{apps_dataset}/ccsync-dashboard/data/dashboard.db",
             "sudo docker start {container}"],
            ("platform", "apps_dataset", "container"), facts),
    ]


def _plan_whole_tree(facts: dict[str, Fact], ctx: dict[str, Any]) -> list[Step]:
    return [
        _stop_the_fleet_step(),
        Step("note",
             "This is the one that cannot be undone",
             body=("Rolling the whole tree back destroys everything written since the "
                   "snapshot, including snapshots taken after it. Restoring one "
                   "project into a new folder (the first question on this page) is "
                   "almost always what is actually wanted, and it destroys nothing. "
                   "Only carry on if everything since that moment really is "
                   "expendable.")),
        _command_step(
            "Roll the project tree back",
            ("On the NAS, as an administrator, with the fleet halted. Read the "
             "snapshot list first and be sure of the name."),
            ["zfs list -t snapshot -r {tree_dataset}",
             "zfs rollback -r {tree_dataset}@<SNAPSHOT>"],
            ("platform", "tree_dataset"), facts),
        # UX-18 (usability sweep 2026-09-03): this step used to say "re-run
        # server/setup_tree.py for each project". The person reading it has a
        # container and a browser, no checkout of this repo and no SSH to the
        # NAS, so it named the one thing they cannot do. What they CAN do is
        # here, and who to ask is said out loud rather than implied.
        Step("action",
             "Afterwards: put back anything the rollback undid",
             body=("A project that was created after that moment is gone from the "
                   "server with everything else written since. Create it again from "
                   "the Projects page here: the folder is made with the right owner "
                   "and permissions as it goes, which is what editors need to be able "
                   "to write to it. Folders that existed in the snapshot come back "
                   "exactly as they were and need nothing."),
             href="/projects"),
        Step("note",
             "Then watch the first pass",
             body=("Let the fleet off hold and watch the first pass on the "
                   # UX-7 (usability sweep 2026-09-03): the words "Fleet page"
                   # appear nowhere in the UI. The nav calls it SYNC STATUS.
                   "SYNC STATUS page. If an editor is refused access to a folder "
                   "that came back, that one needs an administrator login on the NAS "
                   "itself and nothing on this page can do it: ask whoever installed "
                   "CC Sync for you.")),
    ]


def _plan_search_index(facts: dict[str, Fact], ctx: dict[str, Any]) -> list[Step]:
    return [
        Step("note",
             "The search index has its own rollback, and it takes a second",
             body=("Publishing an index leaves the previous one beside it on the "
                   "server as .prev-<timestamp>, so nothing was lost when the bad one "
                   "went live. Putting the previous one back needs no snapshot and no "
                   "shell on the NAS.")),
        # UX-18 (usability sweep 2026-09-03): the command is still the honest
        # answer -- this dashboard deliberately does not swap its own live
        # index out from under itself -- but it runs on the computer that
        # PUBLISHES the index, and an admin with only a browser has to be told
        # that in words rather than left to discover it in a shell.
        Step("note",
             "Who can do it",
             body=("It is one command on the computer the index is published from: "
                   "the studio computer that runs the indexing, not this server and "
                   "not an editor's computer. If that is not yours, ask whoever "
                   "publishes the b-roll or music search for you. Nothing else on "
                   "this server is affected in the meantime: search shows the wrong "
                   "results, and every other page is unaffected.")),
        Step("command",
             "On the computer that publishes the index",
             body="",
             commands=["cd server",
                       "python publish_db.py --which broll --rollback --apply"]),
    ]


def _plan_resolve(facts: dict[str, Fact], ctx: dict[str, Any]) -> list[Step]:
    return [
        Step("action",
             "Undo it from here, on that computer",
             body=("CC Sync writes down every clip path it changes. Pick the computer "
                   "and the change, and it is replayed backwards on that machine the "
                   "next time it reports, whether or not anybody is sitting at it. "
                   "The editor has the same button in their tray."),
             href="/fleet"),
        Step("note",
             "If the undo cannot help",
             body=("CC Sync also exports a copy of the whole Resolve project before it "
                   "changes anything. On that computer it is under "
                   ".ccsync/resolve_edits, and it imports into Resolve as a separate "
                   "project: nothing is overwritten, and the two can be compared. "
                   "docs/RESOLVE_EDIT_SAFETY.md is the procedure.")),
    ]


PROBLEMS: tuple[Problem, ...] = (
    Problem("project",
            "Something on the server was deleted, overwritten or changed by mistake",
            "One project, one folder or one file. The usual one.",
            _plan_project),
    Problem("resolve",
            "CC Sync changed clip paths in somebody's Resolve project and they are wrong",
            "The clips point somewhere they should not, after a relink or a FIX ALL.",
            _plan_resolve),
    Problem("dashboard_db",
            "This dashboard has lost projects, editors or their ticks",
            "The fleet page is empty or wrong, but the footage on the server is fine.",
            _plan_dashboard_db),
    Problem("search_index",
            "The b-roll or music search is empty or wrong",
            "The index was published from a half-finished run.",
            _plan_search_index),
    Problem("whole_tree",
            "Everything on the server is wrong since a particular moment",
            "The last resort, and the only one here that destroys anything.",
            _plan_whole_tree),
)

BY_KEY: dict[str, Problem] = {p.key: p for p in PROBLEMS}


def plan(problem_key: str, facts: dict[str, Fact],
         ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """The steps for one problem, with every command substituted or refused."""
    problem = BY_KEY.get((problem_key or "").strip())
    if problem is None:
        raise RecoveryError(f"there is no recovery here for {problem_key!r}", 404)
    steps = problem.build(facts, ctx or {})
    return {
        "problem": problem.key, "question": problem.question,
        "detail": problem.detail,
        "steps": [
            {"kind": s.kind, "title": s.title, "body": s.body,
             "commands": list(s.commands), "href": s.href, "needs": list(s.needs)}
            for s in steps
        ],
        "refusals": sum(1 for s in steps if s.kind == "refusal"),
    }


def page_view(settings: Any, conn: sqlite3.Connection, problem_key: str = "",
              env: dict[str, str] | None = None) -> dict[str, Any]:
    """Everything the recovery page draws. NEVER RAISES on the gathering half:
    the page somebody opens after losing something must render even when the
    NAS is the thing that is down."""
    from . import protection

    try:
        facts = gather_facts(settings, conn, env)
    except Exception:                                                # noqa: BLE001
        log.exception("recovery: could not gather the facts")
        facts = {}
    snapshots, snap_why = list_snapshots(env)
    chosen: dict[str, Any] | None = None
    if problem_key:
        try:
            chosen = plan(problem_key, facts)
        except RecoveryError as exc:
            chosen = {"problem": problem_key, "question": "", "detail": "",
                      "steps": [{"kind": "refusal", "title": str(exc), "body": "",
                                 "commands": [], "href": "", "needs": []}],
                      "refusals": 1}
    try:
        projects = [{"slug": r["slug"], "label": r["label"]} for r in conn.execute(
            "SELECT slug, label FROM projects WHERE active=1 ORDER BY label")]
    except sqlite3.Error:
        projects = []
    return {
        "facts": [
            {"key": f.key, "label": f.label, "value": f.value,
             "verified": f.verified, "why_not": f.why_not, "fix": f.fix}
            for f in facts.values()
        ],
        "problems": [{"key": p.key, "question": p.question, "detail": p.detail}
                     for p in PROBLEMS],
        "plan": chosen,
        "snapshots": snapshots,
        "snapshots_why_not": snap_why,
        "projects": projects,
        "protection": protection.page_view(conn),
        "restores": history(conn, RESTORES_META),
        "drills": history(conn, DRILLS_META),
    }
