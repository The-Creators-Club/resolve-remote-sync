#!/usr/bin/env python3
"""Publish a search index (broll.db / music.db) onto the live NAS, safely.

    python publish_db.py --which broll                  # dry-run: say what would happen
    python publish_db.py --which broll --apply
    python publish_db.py --which music  --apply
    python publish_db.py --which broll  --rollback --apply

Until 2026-08-17 the only in-repo recipe for this was one line in
broll/HANDOFF.md:

    copy E:\\broll-queue\\broll.db "P:\\Assets\\B-roll Archive\\broll.db"

-- a plain file copy, over SMB, ON TOP of a WAL-mode SQLite database that the
dashboard container holds OPEN READ-WRITE. Three separate ways to lose the
index at once (COMMERCIAL_READINESS.md item 8, section D):

  1. the live file's `-wal` and `-shm` survive the copy and are then a WAL
     belonging to a database that no longer exists -- the classic way a working
     index becomes a corrupt one;
  2. the container's open file handle keeps pointing at the bytes being
     overwritten UNDER it, so what it serves is a half-written database;
  3. a truncated or interrupted copy IS the live index; there is no previous
     one to go back to.

The fix is the same shape the deploy already uses for code and for music.db
(install_dashboard_app.build_db_swap_script, reused here):

  checkpoint the SOURCE  -> everything committed is in the .db file
  snapshot it locally    -> sqlite3.backup(), consistent even mid-write
  verify it locally      -> PRAGMA quick_check + row counts
  upload to staging      -> nothing live is touched yet
  copy beside the live   -> <target>.new, same filesystem as the target
  verify the CANDIDATE   -> PRAGMA quick_check ON THE NAS, through the
                            container's own python3
  compare row counts     -> refuse a surprise shrink (--allow-shrink)
  rename                 -> <target> to <target>.prev-<ts> (with its -wal/-shm,
                            SERVER-7), then <target>.new to <target>. A rename
                            is atomic; a copy is not, and the container picks
                            up a REPLACED file on its next connection.

`--rollback` is the same rename in reverse, from the newest `.prev-<ts>`.

DRY-RUN IS THE DEFAULT: nothing moves without --apply.

Env vars: TRUENAS_HOST / TRUENAS_USER / TRUENAS_PW (see server/README.md).
"""
import argparse
import json
import posixpath
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import common
from common import (
    DEFAULT_APPS_ROOT,
    DEFAULT_BROLL_ARCHIVE_ROOT,
    DEFAULT_DATASET_OWNER,
    EDITORS_GROUP,
    add_host_key_arg,
    add_nas_kind_arg,
    add_site_arg,
    cli,
    get_backend,
    require_site_value,
    set_host_key_pin,
    shell_quote,
    ssh_client,
    truenas_conn_params,
)
import install_dashboard_app as ida

REPO_ROOT = Path(__file__).resolve().parents[1]

# The two databases this fleet publishes, and everything about each that is
# not shared. Adding a third (a future index) is one entry here.
#
# `tables` is the shrink check's subject: the CONTENT tables, the ones that
# only grow when an indexer runs. Deliberately not every table --
# music.db's `ingest_queue` holds rows that exist ONLY on the NAS (editors
# queue uploads into the live copy; the base rig's copy has never seen them),
# so counting it would make every legitimate publish look like a catastrophic
# shrink. Those rows are drained by index_music.py --queue BEFORE a publish;
# see music/web/DEPLOY.md.
SPECS = {
    "broll": {
        "filename": "broll.db",
        "source": REPO_ROOT / "broll" / "web" / "data" / "broll.db",
        "container_dir": "/broll-data",
        "tables": ("videos", "segments", "embeddings"),
        "what": "the b-roll search index",
    },
    "music": {
        "filename": "music.db",
        "source": REPO_ROOT / "music" / "web" / "data" / "music.db",
        "container_dir": "/music-data",
        "tables": ("tracks", "windows", "tags"),
        "what": "the music search index",
    },
}

# WAL siblings, same set install_dashboard_app uses. They belong to the file
# they sit beside, in BOTH directions (SERVER-7, 2026-08-14).
SIDECARS = ida.MUSIC_DB_SIDECARS

# How much smaller the new index may be before this refuses, per table.
DEFAULT_SHRINK_PCT = 10.0

# Exit codes the generated remote script uses, so the operator's message can
# name the step rather than "the ssh command failed".
RC_SHORT_CANDIDATE = 8      # build_db_swap_script's own
RC_SWAP_FAILED = 9          # build_db_swap_script's own
RC_INTEGRITY = 11


def remote_dir_for(which: str, backend) -> str:
    """Where the LIVE database lives on the NAS.

    Not a constant, because the two sit in different worlds: broll.db is in the
    shared archive (beside Projects/ under the tree root -- the same directory
    editors browse over SMB as P:\\Assets\\B-roll Archive), while music.db is
    in the app's own writable data root under [apps] root. Both are read from
    site.toml, so this works on a site that is not this one.
    """
    if which == "broll":
        return require_site_value(DEFAULT_BROLL_ARCHIVE_ROOT,
                                  "[tree] pool_root/tree_name", "")
    return require_site_value(
        f"{DEFAULT_APPS_ROOT.rstrip('/')}/music-data" if DEFAULT_APPS_ROOT else "",
        "[apps] root", "")


def install_identity(which: str, backend, target: str) -> tuple[str, str, str]:
    """(owner, mode, acl-fidelity shell line) for the installed file.

    The Synology half is the whole reason this is a function. broll.db lives
    INSIDE the tree share on DSM, and a chown or chmod on a Synology share path
    DESTROYS its ACL -- inheritance gone, and DSM's `internal-sftp -u 000` then
    leaves every new file world-writable (spike 1, docs/synology-spikes-
    2026-08-17.md). So there is no chown and no chmod there; owner and ACL are
    carried across from the file being replaced with `synoacltool -copy`, which
    is the tool that does preserve them (`cp -a` does not).

    music.db is not in the tree share on either platform -- it is under the
    app root -- so it keeps the deploy's <uid>:<private gid> 660, which is what
    the container needs to write queued ingest rows. Rendered from
    install_dashboard_app's APP_UID/APP_PRIVATE_GID rather than the literal
    3000:3000 it was until 2026-08-21, for server-4's reason: the container
    runs as site.toml's [stack] uid, and a publish that chowned to someone
    else's id would hand the live index to an account that is not the one
    holding it open.
    """
    if which == "music":
        return f"{ida.APP_UID}:{ida.APP_PRIVATE_GID}", "660", ""
    if getattr(backend, "kind", "") == "synology":
        live_q = shell_quote(target)
        new_q = shell_quote(target + ".new")
        return "", "", (
            f"if [ -e {live_q} ]; then synoacltool -copy {live_q} {new_q} "
            f">/dev/null || echo \"NOTE: synoacltool -copy failed; check the ACL of "
            f"{target} with synoacltool -get after this run\" >&2; fi; ")
    return f"{DEFAULT_DATASET_OWNER}:{EDITORS_GROUP}", "660", ""


def quick_check_snippet(container: str, container_path: str, host_path: str,
                        label: str) -> str:
    """Shell that runs `PRAGMA quick_check` ON THE NAS and stops if it is not "ok".

    Run through the dashboard CONTAINER's python3, because that is the one
    interpreter guaranteed to exist on both platforms (the image is a stock
    python:3.12-slim; TrueNAS SCALE happens to have a host python3, DSM does
    not) -- and because the container is what will actually open this file, so
    it is the reader whose opinion counts. Falls back to a host python3, and if
    neither can answer it FAILS: a publish that could not be verified must not
    become the live index (that is the whole of item 8).

    The database is opened read-only through a file: URI. quick_check on a
    WAL-mode file would otherwise create a -wal beside the candidate, which is
    the exact debris this procedure exists to avoid.
    """
    def prog(path: str) -> str:
        # The path is interpolated into a PYTHON string literal that is itself
        # inside a shell-quoted argument. shell_quote handles the shell layer;
        # the python layer has no escaping, so an apostrophe in a tree name is
        # refused rather than mangled into a syntax error at 3am.
        if "'" in path:
            raise common.EnvError(
                f"refusing to verify {path!r}: an apostrophe in the path cannot be "
                f"carried through the remote python -c. Rename the directory, or "
                f"pass --no-integrity-check and check the index by hand.")
        return ("import sqlite3;"
                f"c=sqlite3.connect('file:{path}?mode=ro&immutable=1',uri=True);"
                "print(c.execute('PRAGMA quick_check').fetchone()[0])")

    py, py_host = prog(container_path), prog(host_path)
    return (
        f"v=$(docker exec {shell_quote(container)} python3 -c {shell_quote(py)} "
        f"2>/dev/null) || v=''; "
        f'if [ "$v" != "ok" ]; then '
        f"v=$(python3 -c {shell_quote(py_host)} 2>/dev/null) || v=''; fi; "
        f'if [ "$v" != "ok" ]; then '
        f'echo "PRAGMA quick_check on the staged {label} did not answer ok (got '
        f'\\"$v\\") -- either the candidate is damaged, or neither the dashboard '
        f'container nor a host python3 could read it. The live index is '
        f'UNTOUCHED." >&2; exit {RC_INTEGRITY}; fi; '
        f'echo "staged {label} verified on the NAS: quick_check ok"; '
    )


# --------------------------------------------------------------------------
# The local half: checkpoint, snapshot, verify
# --------------------------------------------------------------------------

def checkpoint_source(path: Path) -> str:
    """`PRAGMA wal_checkpoint(TRUNCATE)` on the source. Returns a status line.

    Everything the indexer committed since the last checkpoint lives in the
    -wal, and only the .db file is shipped -- so without this a publish can
    quietly ship an index that is hours behind the one the operator is looking
    at. Best-effort: a source that is open elsewhere, or on a read-only
    volume, is reported and then snapshotted as-is (the copy is still a valid,
    if older, database).
    """
    try:
        conn = sqlite3.connect(str(path), timeout=30)
        try:
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return (f"WARNING: could not checkpoint {path.name} ({exc}). Anything the "
                f"indexer has committed but not checkpointed may not be in this "
                f"publish -- close the indexer and re-run if the index looks stale.")
    busy = row[0] if row else 0
    if busy:
        return (f"WARNING: {path.name} would not fully checkpoint (another process "
                f"holds a read lock). Publishing what is in the .db file.")
    return f"checkpointed {path.name} (WAL truncated)"


def local_snapshot(path: Path, dest: Path) -> None:
    """A consistent copy of `path` at `dest`, via SQLite's own backup API.

    Not shutil.copy: the source may be being written to right now (the indexer
    runs for hours), and a byte copy of a database mid-transaction is exactly
    the kind of file that passes a size check and fails quick_check.
    """
    src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def local_verify(path: Path, tables) -> tuple[str, dict]:
    """(quick_check result, {table: count}) for a local database file."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        state = conn.execute("PRAGMA quick_check").fetchone()[0]
        counts = {}
        for table in tables:
            try:
                counts[table] = conn.execute(
                    f"SELECT count(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                # A table this build does not have is not a failure; it is a
                # schema difference, and the comparison below skips it.
                counts[table] = None
        return state, counts
    finally:
        conn.close()


# --------------------------------------------------------------------------
# The remote half
# --------------------------------------------------------------------------

def read_live_counts(backend, container: str, container_path: str, tables,
                     dry_run: bool) -> tuple[dict, str]:
    """Row counts of the LIVE database, read through the container. ({}, why)
    when they cannot be read -- which is a WARNING, not a stop: a first publish
    onto a NAS with no index yet is a legitimate thing to do."""
    if "'" in container_path:
        return {}, "the container path holds an apostrophe"
    py = ("import sqlite3,json;"
          f"c=sqlite3.connect('file:{container_path}?mode=ro',uri=True);"
          "o={}\n"
          f"for t in {list(tables)!r}:\n"
          "    try: o[t]=c.execute('SELECT count(*) FROM '+t).fetchone()[0]\n"
          "    except Exception: o[t]=None\n"
          "print(json.dumps(o))")
    rc, out, err = backend.container_exec(
        container, f"python3 -c {shell_quote(py)}", dry_run)
    if dry_run:
        return {}, ""
    text = (out or "").strip().splitlines()[-1:] or [""]
    if rc != 0 or not text[0].startswith("{"):
        return {}, (err or out or f"rc={rc}").strip()[:200]
    try:
        return json.loads(text[0]), ""
    except ValueError:
        return {}, "the container did not answer JSON"


def shrink_refusals(live: dict, new: dict, pct: float) -> list[str]:
    """Which tables shrank by more than `pct`%. One line each, for stderr."""
    out = []
    for table, before in sorted(live.items()):
        after = new.get(table)
        if not before or after is None:
            continue
        if after >= before:
            continue
        lost = (before - after) / before * 100.0
        if lost > pct:
            out.append(f"{table}: {before} rows live -> {after} in the new index "
                       f"({lost:.1f}% fewer)")
    return out


def build_rollback_script(target: str, prev: str, aside: str) -> str:
    """Put `prev` back, keeping what is live now as `aside`.

    Renames only, sidecars carried with the file they belong to in both
    directions (SERVER-7), and the rollback of the rollback is the same
    command with the two names swapped.
    """
    t, p, a = shell_quote(target), shell_quote(prev), shell_quote(aside)
    move_aside = " ".join(
        f"if [ -e {shell_quote(target + s)} ]; then "
        f"mv {shell_quote(target + s)} {shell_quote(aside + s)}; fi;"
        for s in SIDECARS)
    bring_back = " ".join(
        f"if [ -e {shell_quote(prev + s)} ]; then "
        f"mv {shell_quote(prev + s)} {shell_quote(target + s)}; fi;"
        for s in SIDECARS)
    return (
        f"set -e; "
        f"if [ ! -e {p} ]; then echo \"no previous index at {prev}\" >&2; exit 6; fi; "
        f"if [ -e {t} ]; then mv {t} {a}; fi; "
        f"{move_aside} "
        f"mv {p} {t}; "
        f"{bring_back} "
        f'echo "rolled back: {target} restored from {prev} (the index that was '
        f'live is now {aside})"'
    )


def list_prev_command(remote_dir: str, filename: str) -> str:
    """The remote command that lists every <filename>.prev-<ts>.

    UNDER SUDO, like every other filesystem probe in this package (SERVER-9,
    OPS-5, check_tree). server-1 (2026-08-21): this was the one exception, and
    it could never work -- the b-roll archive is 3000:3001 mode 2770 and
    music-data is 3000:3000 mode 770, and TRUENAS_USER can traverse neither.

    `find`, not `ls ... | sort | tail`: a pipeline's rc is the LAST command's,
    so `tail` turned an EACCES into rc 0 with empty stdout and an unreadable
    directory became indistinguishable from an empty one. find's own rc is the
    answer, and the sort happens in Python where nothing can swallow it.
    """
    return ('echo "$SUDO_PW" | sudo -S -p "" '
            f"find {shell_quote(remote_dir)} -maxdepth 1 -mindepth 1 "
            f"-name {shell_quote(filename + '.prev-*')}")


def newest_prev(backend, remote_dir: str, filename: str,
                dry_run: bool) -> tuple[str, str]:
    """(the most recent <filename>.prev-<ts> on the NAS, why it could not be read).

    Three answers, not two: a path, "nothing there" (both strings empty), and
    "the NAS would not tell us" (second string set). do_rollback used to print
    the same "there is nothing to roll back to" for all three, which is how the
    documented first-line recovery (docs/BACKUP_RESTORE.md 4d) reported an
    absent .prev over a directory that held one.
    """
    if dry_run:
        return "", ""
    rc, out, err = ida.run_ssh_guarded(list_prev_command(remote_dir, filename),
                                       False, 60)
    if rc != 0:
        return "", ((err or out or f"rc={rc}").strip()[:300]
                    or f"the listing of {remote_dir} exited {rc}")
    found = sorted(line.strip() for line in (out or "").splitlines() if line.strip())
    return (found[-1] if found else ""), ""


def staging_parent(backend, dry_run: bool) -> str:
    """Where the uploaded copy is staged on the NAS, before the rename.

    /tmp everywhere except DSM, where it CANNOT work: the SFTP channel is
    chrooted to the share view for the administrator too, so /tmp does not
    exist there at all and every `sftp.put` into it fails with "no such file"
    (server-5, 2026-08-21; measured during the 2026-08-17 bring-up, see
    backends/synology.py's module docstring). The deploy has special-cased this
    since day one (install_dashboard_app's code_staging_parent); publish_db
    never did, so no index could be published to a Synology box at all.

    The directory is the same <apps root>/staging build_synology_host_dirs
    creates; it is (re-)made here because publish_db can run against a box
    whose stack was installed by hand.
    """
    if getattr(backend, "kind", "") != "synology":
        return "/tmp"
    root = require_site_value(DEFAULT_APPS_ROOT, "[apps] root", "")
    parent = f"{root.rstrip('/')}/{ida.SYNOLOGY_STAGING_DIRNAME}"
    _host, user, _pw = truenas_conn_params(dry_run=dry_run)
    prepare = (f"mkdir -p {shell_quote(parent)}; "
               f"chown {shell_quote(user)} {shell_quote(parent)}; "
               f"chmod 700 {shell_quote(parent)}")
    rc, _out, err = ida.run_ssh_guarded(backend.root_cmd(prepare), dry_run, 120)
    if not dry_run and rc != 0:
        # Non-fatal: an existing staging dir is the normal case, and the
        # mktemp below is what actually decides whether this works.
        print(f"NOTE: could not prepare {parent} ({err.strip()[:200]}) -- the upload "
              f"below will say if it is unusable.", file=sys.stderr)
    return parent


# --------------------------------------------------------------------------

def do_rollback(args, backend, spec) -> int:
    remote_dir = remote_dir_for(args.which, backend)
    target = posixpath.join(remote_dir, spec["filename"])
    prev, why = "", ""
    if args.from_prev:
        prev = args.from_prev
    else:
        prev, why = newest_prev(backend, remote_dir, spec["filename"], args.dry_run)
    if why:
        # A directory this could not READ is not a directory with nothing in
        # it, and telling the operator otherwise sends them looking for a
        # backup that is right there (server-1, 2026-08-21).
        print(f"FAILED: could not list {remote_dir} to find the previous "
              f"{spec['filename']} ({why}). Nothing was changed. Name the .prev "
              f"explicitly with --from-prev if you know it.", file=sys.stderr)
        return 1
    if not prev and args.dry_run:
        # The listing is a privileged read of the live NAS, so a dry-run does
        # not perform it. Describing the rollback of the newest .prev is the
        # honest answer; the old code printed the FAILED line every time
        # --rollback was typed without --apply (server-1, 2026-08-21).
        print(f"[dry-run] would find the newest {spec['filename']}.prev-* in "
              f"{remote_dir} with:")
        print(f"  {list_prev_command(remote_dir, spec['filename'])}")
        print(f"[dry-run] ...and rename it back over {target}, keeping the index that "
              f"is live now as {target}.rolledback-<ts>.")
        print("\n[dry-run] nothing was changed. Re-run with --apply.")
        return 0
    if not prev:
        print(f"FAILED: no {spec['filename']}.prev-* found in {remote_dir} -- there is "
              f"nothing to roll back to. (A publish keeps exactly one .prev per run and "
              f"never deletes them; if the directory is empty, no publish has run "
              f"through this script.)", file=sys.stderr)
        return 1
    aside = f"{target}.rolledback-{time.strftime('%Y%m%dT%H%M%S')}"
    script = build_rollback_script(target, prev, aside)
    print(f"Rolling back {target}\n  from: {prev}\n  keeping the current one as: {aside}")
    if args.dry_run:
        print("[dry-run] remote script that would run:")
        print(script)
        return 0
    rc, out, err = ida.run_ssh_guarded(
        'echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(script), False, 300)
    sys.stdout.write(out or "")
    if rc != 0:
        print(f"FAILED to roll back (remote exit {rc}): {err.strip()[:400]}",
              file=sys.stderr)
        return rc
    # What the app does with a renamed file, per index (CR-67 seam 11,
    # 2026-08-21). The old text said "the app reopens the database per
    # connection, so a rename is normally enough" for both, which was never
    # true of a long-lived connection: a rename replaces the file the PATH
    # names while every OPEN handle keeps reading the unlinked old inode.
    # musicweb now notices (db._check_swapped, one os.stat per con(), plus
    # db.file_state for the derived search matrices) -- but only where the
    # deployed music-web tree is new enough, and a deployment is not
    # necessarily as new as this script.
    print("Done.")
    if args.which == "music":
        print("  The music app notices a swapped index by itself (one stat per "
              "connection) and reopens within a request or two. An OLDER "
              "deployment does not: it answers from the deleted inode until "
              "somebody POSTs /music/api/reload or the container restarts.")
    else:
        print("  Restart the dashboard container if the app does not pick it "
              "up: the b-roll app reopens the database per connection, so a "
              "rename is normally enough.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--which", choices=sorted(SPECS), required=True)
    ap.add_argument("--source", default="",
                    help="the local database to publish (default: the in-repo one)")
    ap.add_argument("--allow-shrink", action="store_true",
                    help=f"publish even when a content table lost more than "
                         f"--shrink-pct of its rows")
    ap.add_argument("--shrink-pct", type=float, default=DEFAULT_SHRINK_PCT,
                    help=f"how much smaller a table may get before this refuses "
                         f"(default {DEFAULT_SHRINK_PCT:g}%%)")
    ap.add_argument("--no-integrity-check", action="store_true",
                    help="skip the on-NAS PRAGMA quick_check of the staged copy. "
                         "Last resort only -- it is the check that catches the "
                         "failure this script exists to prevent.")
    ap.add_argument("--rollback", action="store_true",
                    help="put the previous index back (the newest .prev-<ts>)")
    ap.add_argument("--from-prev", default="",
                    help="with --rollback: an explicit .prev-<ts> path")
    add_host_key_arg(ap)
    add_site_arg(ap)
    add_nas_kind_arg(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="the default; accepted explicitly so it can be typed")
    ap.add_argument("--apply", action="store_true",
                    help="actually publish (without this, nothing on the NAS moves)")
    args = ap.parse_args()
    args.dry_run = not args.apply
    set_host_key_pin(args.host_key)
    backend = get_backend(args)
    # publish_db drives the NAS through install_dashboard_app's names
    # (run_ssh_guarded, make_staging_dir, the swap script), so the backend has
    # to resolve its calls through that module too -- otherwise the offline
    # suite's patches miss half of what runs. See common.ScriptCalls.
    backend.calls = common.ScriptCalls(sys.modules["install_dashboard_app"])
    spec = SPECS[args.which]

    if args.rollback:
        return do_rollback(args, backend, spec)

    source = Path(args.source) if args.source else spec["source"]
    if not source.is_file():
        print(f"FAILED: no database at {source}. Pass --source, or build the index "
              f"first.", file=sys.stderr)
        return 1

    remote_dir = remote_dir_for(args.which, backend)
    target = posixpath.join(remote_dir, spec["filename"])
    container = backend.dashboard_container
    container_path = posixpath.join(spec["container_dir"], spec["filename"])
    owner, mode, acl_line = install_identity(args.which, backend, target)

    print(f"Publishing {spec['what']}")
    print(f"  from: {source}")
    print(f"  to:   {target}  (the container sees it at {container_path})")

    print(checkpoint_source(source))

    tmpdir = Path(tempfile.mkdtemp(prefix="ccsync-publish-"))
    try:
        staged_local = tmpdir / spec["filename"]
        local_snapshot(source, staged_local)
        state, counts = local_verify(staged_local, spec["tables"])
        size = staged_local.stat().st_size
        print(f"local snapshot: {ida.human_bytes(size)}, quick_check {state}")
        if state != "ok":
            print(f"FAILED: the local snapshot of {source.name} does not pass "
                  f"quick_check ({state}). Nothing was sent; the live index is "
                  f"untouched.", file=sys.stderr)
            return 1
        print("  " + ", ".join(f"{t}={c}" for t, c in counts.items()
                               if c is not None))

        live, why = read_live_counts(backend, container, container_path,
                                     spec["tables"], args.dry_run)
        if why:
            print(f"NOTE: could not read the live index's row counts ({why}). "
                  f"Publishing without the shrink check -- normal for a first "
                  f"publish, worth a look otherwise.", file=sys.stderr)
        refusals = shrink_refusals(live, counts, args.shrink_pct)
        if refusals:
            for line in refusals:
                print(f"  {line}", file=sys.stderr)
            if not args.allow_shrink:
                print(f"FAILED: the new index is more than {args.shrink_pct:g}% "
                      f"smaller than the live one. That is usually a half-finished "
                      f"indexer run or the wrong --source, not a real publish. "
                      f"Nothing was sent. Pass --allow-shrink if the shrink is "
                      f"intended (a prune, a re-scope).", file=sys.stderr)
                return 1
            print("--allow-shrink given: publishing the smaller index anyway.",
                  file=sys.stderr)

        # From here on the NAS is touched. Everything below is staged-verify-
        # swap, and the live file is only ever replaced by a rename.
        timeout = ida.tree_ssh_timeout(size)
        staging = ida.make_staging_dir(args.dry_run, f"ccsync-{args.which}db-upload",
                                       parent=staging_parent(backend, args.dry_run))
        if not staging:
            print("FAILED: no staging dir on the NAS -- the live index is untouched.",
                  file=sys.stderr)
            return 1
        staged_remote = posixpath.join(staging, spec["filename"])
        if args.dry_run:
            print(f"[dry-run] would SFTP {ida.human_bytes(size)} to {staged_remote}")
        else:
            host, user, pw = truenas_conn_params()
            try:
                client = ssh_client(host, user, pw)
                try:
                    sftp = client.open_sftp()
                    sftp.put(str(staged_local), backend.sftp_path(staged_remote))
                    sftp.close()
                finally:
                    client.close()
            except Exception as exc:  # noqa: BLE001 - every transport failure is one answer
                print(f"FAILED: the transfer did not finish ({type(exc).__name__}: "
                      f"{exc}) -- the live index is untouched (staging left at "
                      f"{staging}).", file=sys.stderr)
                return 1
            rc, out, err = ida.run_ssh_guarded(
                f"wc -c < {shell_quote(staged_remote)}", False, timeout)
            got = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1
            if got != size:
                print(f"FAILED: the staged copy is {got} bytes, {size} were sent -- "
                      f"the live index is untouched (staging left at {staging} for "
                      f"inspection): {err.strip()[:200]}", file=sys.stderr)
                return 1
            print(f"staged copy verified: {got} bytes")

        verify = "" if args.no_integrity_check else quick_check_snippet(
            container, container_path + ".new", target + ".new", spec["filename"])
        old = f"{target}.prev-{time.strftime('%Y%m%dT%H%M%S')}"
        swap = ida.build_db_swap_script(
            remote_dir, staging, target, old, size,
            filename=spec["filename"], owner=owner, mode=mode,
            extra_verify=acl_line + verify)
        if args.dry_run:
            print("[dry-run] remote script that would run:")
            print(swap)
            print("\n[dry-run] nothing was changed. Re-run with --apply.")
            return 0
        rc, out, err = ida.run_ssh_guarded(
            'echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(swap), False, timeout)
        sys.stdout.write(out or "")
        if rc != 0:
            print(f"FAILED to install {spec['filename']} (remote exit {rc}): "
                  f"{err.strip()[:500]}\n"
                  f"  The live index is still in place -- it is only ever replaced "
                  f"by a rename, and that rename rolls back.", file=sys.stderr)
            return rc
        print(f"published: {target} ({ida.human_bytes(size)}); previous index kept "
              f"at {old}")
        print(f"Roll back with: python publish_db.py --which {args.which} "
              f"--rollback --apply")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(cli(main))
