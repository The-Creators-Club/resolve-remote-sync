"""The self-diagnosis sweep: everything the server can observe about itself.

UX-10 (resilience sweep 2026-08-28), widened on the owner's instruction the
same day: "make the server as self-diagnosing as possible. Any errors should be
flagged, the diagnosis should be as clear as possible."

Two halves:

* the WRITERS in collector.py / provision.py / app.py, which put a notice
  beside a diagnosis they were already making into a log nobody opens, and
* `run_checks()` here, which is a READ-ONLY pass over what the database
  already knows: the last outcome of every collector job, the persisted
  brakes, the machine registry's identity collisions, disk space, the release
  feed. It runs once per collector cycle and never raises.

Every notice carries a `fix`: the exact next action, named as a button, a page
or a command. A diagnosis a non-technical owner cannot act on is a log line
with better placement.

Nothing here formats a secret. The bodies are built from names, counts and
timestamps; the one place a raw string is quoted (a collector exception) is
truncated and comes from our own exceptions, not from a credential.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

# alerts is imported for its SILENT_SECONDS threshold only (dash-collector-6):
# "a machine has gone quiet" has to mean the same number in both modules.
# alerts imports db and health, never notices, so this is not a cycle.
from . import alerts, crash_report, db

# DDIAG-7 (usability sweep 2026-09-03). mount_status records what each of the
# four optional mounts did at boot. Imported defensively because it is a
# sibling work package: a build without it writes no mount notice at all
# (the kind then renders [ NOT CHECKED ], which is honest) rather than
# refusing to import the module the whole self-diagnosis pass lives in.
try:  # pragma: no cover - exercised both ways by the tests, via monkeypatch
    from . import mount_status
except ImportError:  # pragma: no cover
    mount_status = None  # type: ignore[assignment]

log = logging.getLogger("ccsync.dashboard.notices")

# Free space on the volume the database, the packages and the backups share.
# Below this the dashboard is one write away from being the thing that is
# broken, so it is an error and not a warning.
DASHBOARD_DISK_FLOOR_BYTES = 2 * 1024 ** 3
# An editor's own drive. Warned, never refused: the owner may know something
# we do not, and this is the machine's own disk.
MACHINE_DISK_FLOOR_BYTES = 50 * 1024 ** 3
# Deleted-file safety copies (.ccsync-trash / .stversions) worth mentioning.
MACHINE_TRASH_FLOOR_BYTES = 200 * 1024 ** 3
# How long a device may sit unapproved, or an editor account exist with no
# computer, before either is worth a sentence.
PENDING_DEVICE_HOURS = 24
EDITOR_WITHOUT_MACHINE_DAYS = 30
# A feed that has not been reachable for this long is not a blip.
FEED_STALE_HOURS = 48
# DDIAG-9: how old a stamped reading may be before it stops being a fact about
# a machine TODAY. Deliberately looser than alerts' "this machine has gone
# quiet" line: a laptop that was off over a long weekend has not changed its
# free space, and a machine that is genuinely silent is machine_silent's
# business, said once rather than twice in different words.
MACHINE_DISK_STALE_HOURS = 48
# DDIAG-3: past this, a silent computer stops being a daily alert and becomes
# one standing notice naming [ FORGET ]. Read from alerts when that module
# carries it, so the two halves of the same give-up rule cannot drift; the
# fallback is here because notices.py must import against an older alerts.
SILENT_GIVE_UP_DAYS = int(getattr(alerts, "SILENT_GIVE_UP_DAYS", 14) or 14)
# Caps, so one broken condition cannot write a hundred rows.
MAX_ROWS_PER_KIND = 20

# DDIAG-10: "since this server started". run_checks is handed (conn, settings)
# on the collector's thread and can reach neither app.state nor the ASGI app,
# and this module is imported once while the process is coming up, so its
# import is the boot to within a second or two -- which is the precision the
# question ("has anything crashed since we started") needs.
_PROCESS_STARTED = time.time()
# The newest N crash files the download hands over. crash_report keeps at most
# MAX_CRASH_FILES on disk anyway; this states the ceiling at the route.
CRASH_ZIP_MAX_FILES = 20


def _hours_since(ts: str, now: str) -> float | None:
    try:
        return db.age_seconds(ts, now) / 3600.0
    except (TypeError, ValueError):
        return None


def _stale_reading(ts: Any, now: str, hours: float = MACHINE_DISK_STALE_HOURS) -> bool:
    """Whether a measurement is too old to say anything about today
    (bug-hunt-2026-09-03 dash-collector-6). A reading with NO timestamp is
    treated as stale: an unstamped number cannot be shown to be current, and
    the safe direction for a notice nobody can clear is not to open it.

    The ceiling is a parameter because every judgement made on a STAMPED
    reading has to make it (DDIAG-9), and they do not all age at the same
    rate."""
    if not ts:
        return True
    age = _hours_since(str(ts), now)
    if age is None:
        return True
    return age > float(hours)


def _since(ts: str, now: str) -> str:
    """"since <n> hours ago", in words, for the body of a notice."""
    hours = _hours_since(ts, now)
    if hours is None:
        return "for an unknown length of time"
    if hours < 1:
        return "for less than an hour"
    if hours < 48:
        return f"for about {int(hours)} hour(s)"
    return f"for about {int(hours // 24)} day(s)"


def run_checks(
    conn, settings, now: str | None = None,
    pending_devices: dict[str, Any] | None = None,
    folder_devices: dict[str, list[str]] | None = None,
) -> int:
    """One read-only self-diagnosis pass. Returns how many checks ran.

    Every check is individually isolated: this runs inside the collector
    cycle, and a diagnosis that killed the cycle it describes would be worse
    than no diagnosis. A check that cannot run leaves its notices ALONE
    rather than clearing them -- "could not check" must never render as
    "fine".

    `folder_devices` is `Collector._folder_devices` (slug -> shared device
    ids), the same cache `_run_completion` and `_run_enforce` read, handed in
    because this module only ever sees `conn` otherwise (finding 1, resilience
    sweep 2026-08-28 fix pass -- `_check_plan_without_share` needs it)."""
    stamp = now or db.utcnow_iso()
    checks = (
        _check_collector_jobs,
        _check_collector_alarms,
        _check_tree,
        _check_identity_collisions,
        _check_machine_space,
        _check_dashboard_space,
        _check_release_feed,
        _check_accounts,
        # usability sweep 2026-09-03, wave 2: DDIAG-3, DDIAG-7, SYS-1(c) and
        # DDIAG-10. Each is registered in db.NOTICE_KINDS WITH the writer
        # beside it, never a kind nothing writes.
        _check_forgotten_machines,
        _check_feature_mounts,
        _check_alerts_sink,
        _check_server_crashes,
    )
    ran = 0
    for check in checks:
        try:
            check(conn, settings, stamp)
            ran += 1
        except Exception:  # noqa: BLE001 - see the docstring
            log.exception("notice check %s failed; continuing", getattr(check, "__name__", "?"))
        # ONE COMMIT PER CHECK (2026-09-03 database is locked, api_report held
        # the lock). Each check does its own syscalls FIRST and its writes
        # after, so committing here is what keeps a syscall out of an open
        # write transaction: without it, the first check to write a notice
        # opened the transaction and _check_tree's is_dir/iterdir on the NAS
        # mount and _check_dashboard_space's disk_usage then ran inside it,
        # holding the write lock across storage that can hang. Each check's
        # findings are independently durable, which is also the right shape
        # for a pass whose checks are already individually isolated.
        _commit(conn)
    try:
        _check_pending_devices(conn, stamp, pending_devices)
        ran += 1
    except Exception:  # noqa: BLE001
        log.exception("notice check for pending devices failed; continuing")
    _commit(conn)
    try:
        _check_plan_without_share(conn, stamp, folder_devices)
        ran += 1
    except Exception:  # noqa: BLE001
        log.exception("notice check for plan without share failed; continuing")
    conn.commit()
    return ran


def _commit(conn) -> None:
    """A commit that cannot end the pass. The caller (the collector cycle)
    commits again after us, and a failure to write one check's notices must
    not cost the other seven."""
    try:
        conn.commit()
    except Exception:  # noqa: BLE001 - see the docstring
        log.exception("could not commit a notice check's findings; continuing")


# ------------------------------------------------------ the collector itself

# What a failing job means, in words an owner can act on. Keyed by the
# collector's own kind names so a new kind cannot silently render as "".
_JOB_MEANING = {
    "provision": ("new and moved project folders are not being set up for syncing",
                  "Look at the other problems listed here first: a stray project marker "
                  "is the usual cause. If there is none, restart the dashboard."),
    "config": ("this server cannot read its own sync engine, so nothing about the fleet "
               "is being updated",
               "Check that Syncthing is running on the server (Settings, Diagnostics)."),
    "enforce": ("projects ticked or unticked on this dashboard are not reaching the "
                "editors' computers",
                "Check that Syncthing is running on the server, then untick and re-tick "
                "one project to retry."),
    "inventory": ("the server's own file list is not being refreshed, so the figures on "
                  "every project page are going stale",
                  "Check that the projects folder is still mounted on the server."),
    "connections": ("this server cannot see which computers are connected",
                    "Check that Syncthing is running on the server."),
    "completion": ("how far behind each editor is has stopped being measured, so the "
                   "grid's percentages are old",
                   "Check that Syncthing is running on the server."),
    "remoteneed": ("which files each computer is still missing has stopped being measured",
                   "Check that Syncthing is running on the server."),
    "prune": ("old rows are not being cleared out of the database",
              "Check the free space on the data volume (Settings, Packages)."),
    "invariants": ("the checks that re-verify the facts this system relies on are not "
                   "running, so nothing is re-checking them (SYS-9)",
                   "Open Settings, Invariants to see which check last ran, then restart "
                   "the dashboard."),
}

# sqlite says these when the problem is the disk rather than the query.
_DB_FAULT_MARKERS = ("disk i/o error", "database or disk is full", "readonly database",
                     "attempt to write a readonly database", "database is locked",
                     "unable to open database", "database disk image is malformed")


def _check_collector_jobs(conn, settings, now: str) -> None:
    """Every background job's LAST outcome, as a sentence (owner, 2026-08-28).

    poll_runs has always held this and only the Diagnostics page read it, so
    "enforce has failed every minute for three days" was a fact the server
    knew and never said."""
    health = db.collector_health(conn, now)
    for row in health.get("kinds") or []:
        kind = str(row.get("kind") or "")
        if not kind:
            continue
        # `note` is poll_runs.error, which carries a note on a SUCCESSFUL run
        # too, so it is only read on the failing branch below.
        error = str(row.get("note") or "")
        if row.get("ok"):
            db.clear_notice(conn, "collector_cycle_failed", kind, now=now)
            db.clear_notice(conn, "collector_db_write_failed", kind, now=now)
            continue
        meaning, fix = _JOB_MEANING.get(
            kind, ("one of the background jobs that keeps the fleet in step is failing",
                   "Restart the dashboard, then check Settings, Diagnostics."))
        when = str(row.get("finished_at") or row.get("started_at") or "")
        db.notice(
            conn, "collector_cycle_failed", "error", kind,
            body=(f"The '{kind}' job has been failing {_since(when, now)}: {meaning}. "
                  f"The server reported: {error[:200] or 'no detail'}"),
            fix=fix, now=now)
        low = error.lower()
        if any(marker in low for marker in _DB_FAULT_MARKERS):
            db.notice(
                conn, "collector_db_write_failed", "error", kind,
                body=("The dashboard could not write to its own database while running "
                      f"the '{kind}' job: {error[:200]}. Nothing this server records is "
                      "safe while that is true."),
                fix=("Check the free space and the permissions on the data volume "
                     "(Settings, Packages shows the free space)."),
                now=now)
        else:
            db.clear_notice(conn, "collector_db_write_failed", kind, now=now)
    # The sync engine, as one line rather than seven job failures.
    if health.get("syncthing_reachable") is False:
        db.notice(
            conn, "syncthing_unreachable", "error", "server",
            body=("The sync engine (Syncthing) on this server is not answering, so no "
                  "project is being shared, measured or updated for anybody."),
            fix="Start Syncthing on the server, then check Settings, Diagnostics.",
            now=now)
    elif health.get("syncthing_reachable") is True:
        db.clear_notice(conn, "syncthing_unreachable", "server", now=now)


def _check_collector_alarms(conn, settings, now: str) -> None:
    """The persisted brakes (wave 1's DASH-3/DASH-4 banners), as notices.

    The banners stay where they are: they are read in context, on the pages
    that show what was not applied. This is the same fact on the home page,
    where somebody who is not looking for it will still meet it."""
    alarms = db.collector_alarms(conn)
    refusal = alarms.get("enforce_refusal")
    if isinstance(refusal, dict) and refusal.get("count"):
        folders = ", ".join(refusal.get("folders") or [])[:200]
        db.notice(
            conn, "enforce_refusal", "error", "share removals",
            body=(f"{refusal['count']} project share(s) would have been taken away from "
                  f"computers in one pass, which is more than the safety limit "
                  f"({refusal.get('limit')}), so NONE of them were. Every untick made "
                  f"since is sitting unapplied. Folders involved: {folders or 'unknown'}."),
            fix=("Check that no editor's computer has just been renamed or removed. "
                 "If the removals are genuine, raise DASH_ENFORCE_MAX_REMOVALS and "
                 "redeploy, or untick fewer projects at a time."),
            now=now)
        # The inverse of SYS-9 invariant 1 ("every full-tick selection has a
        # Syncthing folder shared with that machine's device id"), computed
        # from what the brake already recorded rather than a fresh read: a
        # computer still being SENT a project nobody ticked for it. Invariant
        # 3 is device-id uniqueness (_check_identity_collisions); this pair
        # check was mislabelled before the resilience sweep 2026-08-28 fix
        # pass. The direct form of invariant 1 -- a plan with no matching
        # share -- is `_check_plan_without_share` below.
        pairs = [p for p in (refusal.get("pairs") or []) if isinstance(p, dict)]
        for pair in pairs[:MAX_ROWS_PER_KIND]:
            subject = f"{pair.get('folder', '?')} -> {pair.get('device', '?')}"
            db.notice(
                conn, "share_without_plan", "warn", subject,
                body=("This computer is still being sent a project that nobody has "
                      "ticked for it. The removal was refused by the safety limit above, "
                      "so the project keeps syncing to a computer whose sync plan "
                      "does not include it."),
                fix="Clear the share-removal problem above and the next pass applies it.",
                now=now)
    else:
        db.clear_notice(conn, "enforce_refusal", "share removals", now=now)
        db.clear_notices_of_kind(conn, "share_without_plan", now=now)
    deactivation = alarms.get("deactivation_refusal")
    # The key is `would_deactivate`, which is what db.deactivate_missing_projects
    # persists; this read asked for `count` and so was never once true, clearing
    # the notice on every cycle instead of raising it (SYS-18b, 2026-08-29, found
    # by the wave 5 chaos suite). Had it ever been true the f-string below would
    # have raised KeyError inside run_checks' own isolation and been swallowed -
    # UX-10 recurring inside the mechanism built to close UX-10. Read it through
    # a local so the test and the sentence cannot drift apart again.
    n_refused = deactivation.get("would_deactivate") if isinstance(deactivation, dict) else None
    if n_refused:
        db.notice(
            conn, "deactivation_refusal", "error", "projects",
            body=(f"{n_refused} project(s) looked as though they had been "
                  f"deleted from the server in one pass, which is more than the safety "
                  f"limit, so none of them were marked gone. If the projects folder was "
                  f"unmounted, that is what this means."),
            fix=("Check that the projects folder is mounted on the server. Once it is, "
                 "this clears by itself on the next pass."),
            now=now)
    else:
        db.clear_notice(conn, "deactivation_refusal", "projects", now=now)
    ignored = db.ignored_report_sections(conn) if hasattr(db, "ignored_report_sections") else None
    if isinstance(ignored, dict) and ignored.get("sections"):
        names = ", ".join(sorted(str(s) for s in ignored["sections"]))[:200]
        db.notice(
            conn, "ignored_report_sections", "warn", "report fields",
            body=("Editors' computers are sending information this dashboard is too old "
                  f"to store, so it is being thrown away: {names}. The companions are "
                  "ahead of the dashboard."),
            fix="Update the dashboard (Settings, Packages, [ UPDATE THE DASHBOARD ]).",
            now=now)
    else:
        db.clear_notice(conn, "ignored_report_sections", "report fields", now=now)


# ------------------------------------------------------------------- the tree

def _check_tree(conn, settings, now: str) -> None:
    projects_dir = str(getattr(settings, "projects_dir", "") or "")
    if not projects_dir:
        return
    path = Path(projects_dir)
    try:
        exists = path.is_dir()
        entries = any(path.iterdir()) if exists else False
    except OSError as exc:
        db.notice(
            conn, "projects_dir_missing", "error", projects_dir,
            body=(f"The projects folder on the server could not be read: {exc}. Nothing "
                  "can be discovered, measured or shared while that is true."),
            fix="Check that the server's storage is mounted, then restart the dashboard.",
            now=now)
        return
    if not exists:
        db.notice(
            conn, "projects_dir_missing", "error", projects_dir,
            body=("The projects folder on the server is not there. Every project on this "
                  "dashboard came from inside it, so discovery, file counts and sharing "
                  "have all stopped."),
            fix="Mount the server's storage at that path, then restart the dashboard.",
            now=now)
        return
    if not entries:
        db.notice(
            conn, "projects_dir_missing", "error", projects_dir,
            body=("The projects folder on the server is EMPTY, which normally means the "
                  "storage is not mounted rather than that the projects are gone. "
                  "Nothing has been marked as deleted."),
            fix="Mount the server's storage at that path. Nothing else is needed.",
            now=now)
        return
    db.clear_notice(conn, "projects_dir_missing", projects_dir, now=now)
    _check_inventory(conn, now)


def _check_inventory(conn, now: str) -> None:
    """A project whose file walk was refused (DASH-5's brake). Per project,
    because that is the unit an owner acts on."""
    failing: list[str] = []
    for row in conn.execute(
        "SELECT p.slug AS slug, m.last_error AS last_error, m.walked_at AS walked_at "
        "FROM projects p JOIN nas_inventory_state m ON m.project_id = p.id "
        "WHERE p.active=1 AND m.last_error IS NOT NULL AND m.last_error <> ''"
    ):
        slug = str(row["slug"])
        failing.append(slug)
        db.notice(
            conn, "inventory_refused", "error", slug,
            body=(f"The file list for {slug} was not updated: "
                  f"{str(row['last_error'])[:200]}. The figures on that project's page "
                  f"are the last good ones, from before this started."),
            fix=("Check that the project's folder is still on the server under the name "
                 "the dashboard knows. If it was renamed, use [ MOVE ON THE SERVER AND "
                 "ON EVERY MACHINE ] on the project page."),
            now=now)
    db.clear_notices_of_kind(conn, "inventory_refused", failing, now=now)


# ------------------------------------------------------- identity collisions

def _check_identity_collisions(conn, settings, now: str) -> None:
    """DASH-11: two hostnames claiming one identity.

    A cloned machine (a disk image copied onto a second computer) reports the
    same machine_id or the same Syncthing device id from two places, and every
    per-machine decision after that is made about the wrong computer."""
    open_subjects: list[str] = []
    for row in conn.execute(
        "SELECT machine_id, COUNT(*) AS n, GROUP_CONCAT(editor_username || '/' || machine, ', ') "
        "AS who FROM machines WHERE machine_id IS NOT NULL AND machine_id <> '' "
        "GROUP BY machine_id HAVING n > 1"
    ):
        subject = str(row["machine_id"])
        open_subjects.append(subject)
        db.notice(
            conn, "duplicate_machine_id", "error", subject,
            body=(f"Two computers are reporting the same identity: {row['who']}. This "
                  "happens when a computer's disk was copied onto another one. Sync "
                  "plans, updates and stop commands for either of them can land on "
                  "the wrong computer."),
            fix=("On the newer computer, quit CCSync, delete the file .ccsync/machine.json "
                 "in that user's home folder, and start CCSync again. It mints a fresh "
                 "identity on the next start."),
            now=now)
    db.clear_notices_of_kind(conn, "duplicate_machine_id", open_subjects, now=now)

    open_devices: list[str] = []
    for row in conn.execute(
        "SELECT syncthing_device_id AS did, COUNT(*) AS n, "
        "GROUP_CONCAT(editor_username || '/' || machine, ', ') AS who FROM machines "
        "WHERE syncthing_device_id IS NOT NULL AND syncthing_device_id <> '' "
        "GROUP BY syncthing_device_id HAVING n > 1"
    ):
        subject = str(row["did"])
        open_devices.append(subject)
        db.notice(
            conn, "duplicate_device_id", "error", subject,
            body=(f"Two computers are claiming the same place on the sync network: "
                  f"{row['who']}. Only one of them can actually receive anything, and "
                  "which one it is is not something this server chooses."),
            fix=("Reinstall CCSync on the newer computer, or reset its Syncthing "
                 "identity, so it has a device id of its own."),
            now=now)
    db.clear_notices_of_kind(conn, "duplicate_device_id", open_devices, now=now)


def _check_pending_devices(conn, now: str, pending: dict[str, Any] | None) -> None:
    """A computer that has been waiting to be let onto the sync network.

    `pending is None` means the sync engine could not be asked. That is not
    evidence that nothing is waiting, so nothing is cleared."""
    if pending is None:
        return
    open_ids: list[str] = []
    for device_id, info in (pending or {}).items():
        seen = str((info or {}).get("time") or "") if isinstance(info, dict) else ""
        hours = _hours_since(seen, now) if seen else None
        if hours is not None and hours < PENDING_DEVICE_HOURS:
            continue
        open_ids.append(str(device_id))
        who = conn.execute(
            "SELECT editor_username, machine FROM machines WHERE syncthing_device_id=?",
            (str(device_id),),
        ).fetchone()
        whose = f"{who['editor_username']}/{who['machine']}" if who else "an unknown computer"
        db.notice(
            conn, "pending_device_approval", "warn", str(device_id),
            body=(f"A computer ({whose}) has been waiting to be approved for the sync "
                  f"network {_since(seen, now) if seen else 'for over a day'}. Until it "
                  "is approved, none of its projects can be shared with it, and it will "
                  "look permanently behind."),
            fix="Approve it on Settings, Users, in the pending devices list.",
            now=now)
    db.clear_notices_of_kind(conn, "pending_device_approval", open_ids, now=now)


def _check_plan_without_share(
    conn, now: str, folder_devices: dict[str, list[str]] | None,
) -> None:
    """The direct form of SYS-9 invariant 1, and the inverse of
    `share_without_plan`: a computer whose PLAN says a project should be
    syncing to it, that this server is not actually sending it (finding 1,
    resilience sweep 2026-08-28 fix pass -- registered in `db.NOTICE_KINDS`
    since the sweep landed, with no writer until now).

    `folder_devices is None` means the config job has not cached a
    folder/device snapshot in THIS process yet (a fresh boot, or Syncthing
    unreachable): that is not evidence every plan is satisfied, so nothing is
    written or cleared, the same rule `_check_pending_devices` follows for a
    `pending is None` read."""
    if folder_devices is None:
        return
    # FULL ticks only (docs/UPLOAD_ONLY_TICK.md): upload-only is lane A alone
    # and is never a Syncthing share by design, so it has nothing to check
    # here -- mirroring the filter _run_enforce applies to the same table.
    by_slug = db.fetch_machine_selections(conn, sync_modes=(db.SYNC_MODE_FULL,))
    device_by_machine: dict[tuple[str, str], str] = {}
    for row in db.fetch_machines(conn):
        device_id = row.get("syncthing_device_id")
        if device_id:
            device_by_machine[(row["editor_username"], row["machine"])] = str(device_id)
    open_subjects: list[str] = []
    for slug, pairs in by_slug.items():
        shared = set(folder_devices.get(slug) or [])
        for editor, machine in pairs:
            if machine == db.ANY_MACHINE:
                # The unassigned bucket: nobody's computer yet, so there is no
                # device id to check a share against.
                continue
            device_id = device_by_machine.get((editor, machine))
            if not device_id or device_id in shared:
                continue
            subject = f"{editor}/{machine} -> {slug}"
            open_subjects.append(subject)
            db.notice(
                conn, "plan_without_share", "error", subject,
                body=(f"{editor}/{machine} has ticked {slug} to sync, but this server "
                      "is not sending that project to it. Nothing about it is reaching "
                      "that computer, and the tick looks exactly like it is working."),
                fix=("Untick and re-tick that project for that computer on its "
                     "project page. If it keeps happening, check that computer's row "
                     "on the SYNC STATUS page has a Syncthing device id."),
                now=now)
    db.clear_notices_of_kind(conn, "plan_without_share", open_subjects, now=now)


# ------------------------------------------------------------------- space

def _check_machine_space(conn, settings, now: str) -> None:
    open_disks: list[str] = []
    open_trash: list[str] = []
    for row in conn.execute(
        "SELECT editor_username, machine, disk_root_free_bytes AS free, "
        "disk_root_total_bytes AS total, disk_at, trash_bytes FROM machine_state"
    ):
        subject = f"{row['editor_username']}/{row['machine']}"
        # bug-hunt-2026-09-03 dash-collector-6: a measurement from a machine
        # that has stopped reporting is not a fact about that machine today.
        # Without this gate a retired laptop's last reading kept a warn open
        # for ever, with a fix ("untick a project for that computer") that
        # nobody can act on, because the only way to clear was for the same
        # machine to report again with more space. DDIAG-9 gave it its own
        # ceiling (MACHINE_DISK_STALE_HOURS) rather than borrowing alerts'
        # gone-quiet line: this is not "could not check", it is "this reading
        # is not about now", and the skip CLEARS both kinds for that subject
        # through the two clear_notices_of_kind calls below.
        if _stale_reading(row["disk_at"], now):
            continue
        free = row["free"]
        if free is not None and int(free) < MACHINE_DISK_FLOOR_BYTES:
            open_disks.append(subject)
            db.notice(
                conn, "machine_disk_low", "warn", subject,
                body=(f"{subject} has {int(free) // (1024 ** 3)} GB free on the drive it "
                      "keeps footage on. Proxy downloads for one project are typically "
                      "50 to 300 GB, so this computer is close to filling up, which "
                      "stops it syncing and makes Resolve unusable on it too."),
                fix=("Untick a project for that computer on its project page, or ask the "
                     "editor to clear space on that drive."),
                now=now)
        trash = row["trash_bytes"]
        if trash is not None and int(trash) > MACHINE_TRASH_FLOOR_BYTES:
            open_trash.append(subject)
            db.notice(
                conn, "machine_trash_oversize", "warn", subject,
                body=(f"{subject} is holding {int(trash) // (1024 ** 3)} GB of safety "
                      "copies of deleted files. They are kept on purpose, but they are "
                      "taking up room that footage needs."),
                fix=("The computer clears these by itself every 6 hours unless "
                     "proxy download has stopped itself. Check that computer's row on "
                     "the SYNC STATUS page for [ RESUME ]."),
                now=now)
    db.clear_notices_of_kind(conn, "machine_disk_low", open_disks, now=now)
    db.clear_notices_of_kind(conn, "machine_trash_oversize", open_trash, now=now)


def _check_forgotten_machines(conn, settings, now: str) -> None:
    """DDIAG-3: a computer nobody is going to hear from again.

    `machine_silent` is an ALERT at error severity, and an error re-sends once
    a day for as long as it is true, so a laptop that was retired, reinstalled
    under another hostname or taken on a three-week shoot produced twenty-one
    identical mails whose fix ("ask that editor to check the tray icon") could
    never be carried out. Past the give-up line the alert side stops and this
    takes over: one standing warn, said once, naming the button that ends it.

    It clears when the machine reports again (its subject drops out of the
    open set) or when the row is forgotten (it is no longer selected at all).
    """
    cutoff = (db.parse_iso(now) - dt.timedelta(days=SILENT_GIVE_UP_DAYS)).isoformat()
    open_subjects: list[str] = []
    for row in conn.execute(
        "SELECT editor_username, machine, received_at FROM machine_state "
        "WHERE received_at IS NOT NULL AND received_at <> '' AND received_at < ? "
        "ORDER BY received_at LIMIT ?", (cutoff, MAX_ROWS_PER_KIND),
    ):
        subject = f"{row['editor_username']}/{row['machine']}"
        open_subjects.append(subject)
        db.notice(
            conn, "machine_forgotten", "warn", subject,
            body=(f"{row['editor_username']}'s computer {row['machine']} last reported "
                  f"{_since(str(row['received_at']), now)}, so this server has stopped "
                  "asking about it. Nothing is syncing to or from that computer, and "
                  "anything ticked for it is sitting unapplied."),
            fix=("If that computer is gone for good, open FLEET and press [ FORGET ] on "
                 "its row so this stops. If it is coming back, no action is needed."),
            now=now)
    db.clear_notices_of_kind(conn, "machine_forgotten", open_subjects, now=now)


# ------------------------------------------------------------ mounted apps

# The four optional mounts, in the words the topbar uses for their links.
_MOUNT_LABELS = {
    "broll": "B-ROLL",
    "music": "MUSIC",
    "ytdl": "YOUTUBE",
    "cards": "TIMELINE CARDS",
}


def _check_feature_mounts(conn, settings, now: str) -> None:
    """DDIAG-7: a page that did not start says so somewhere a human looks.

    Each mount already computes a tri-state with a sentence in `detail` ("the
    vault root is not mounted (/vault)", "the checkout did not import"). That
    sentence reached the container log and the authenticated health body; on
    the page the topbar link simply disappeared, so an editor asking "where
    has B-ROLL gone" met an owner with no page that answers.

    With no `mount_status` module in this build nothing is written and nothing
    is cleared: a status this pass could not read is not evidence that the
    four pages are up."""
    snapshot = getattr(mount_status, "snapshot", None) if mount_status else None
    if snapshot is None:
        return
    statuses = snapshot() or {}
    if not isinstance(statuses, dict):
        return
    open_names: list[str] = []
    for name, value in statuses.items():
        try:
            status, detail = value
        except (TypeError, ValueError):
            continue
        if str(status) == "mounted":
            continue
        label = _MOUNT_LABELS.get(str(name), str(name).upper())
        open_names.append(str(name))
        db.notice(
            conn, "feature_not_mounted", "warn", str(name),
            body=(f"The {label} page is not available on this server: "
                  f"{str(detail or status)[:200]}. Editors will not see the link in "
                  "the menu."),
            fix=("Check the container's bind mounts (docs/DOCKER.md), then restart the "
                 "dashboard."),
            now=now)
    db.clear_notices_of_kind(conn, "feature_not_mounted", open_names, now=now)


# --------------------------------------------------------------- the sink

def _check_alerts_sink(conn, settings, now: str) -> None:
    """SYS-1(c): the mechanism that delivers every other diagnosis.

    Forty checks, ten invariants and a weekly report, and the vendor default
    is that they are told to nobody. The panel whose premise is that a safety
    net this server cannot verify is reported had no line for the one that
    carries all the others."""
    sink = str((alerts.get_settings(conn) or {}).get("alerts_sink") or alerts.SINK_NONE)
    if sink == alerts.SINK_NONE:
        db.notice(
            conn, "alerts_sink_none", "warn", "alerts",
            body=("Nobody is being told when this server finds a problem. Everything on "
                  "this panel is found whether or not anyone is looking at it, and with "
                  "no address or webhook set the first anyone hears of a stopped sync is "
                  "an editor asking."),
            fix=("Set an address or a webhook on Settings, Alerts, then press "
                 "[ SEND A TEST ]."),
            now=now)
    else:
        db.clear_notice(conn, "alerts_sink_none", "alerts", now=now)


# ------------------------------------------------- this server's own crashes

def crash_files(settings, limit: int = CRASH_ZIP_MAX_FILES) -> list[Path]:
    """The newest crash reports on disk, newest first. Never raises: an
    unreadable directory reads as no reports, because the caller is either a
    check inside the collector cycle or a download an admin pressed."""
    try:
        directory = crash_report.crash_dir(settings)
        files = [p for p in directory.glob("*.json") if p.is_file()]
    except Exception:  # noqa: BLE001 - see the docstring
        return []
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[:int(limit)]


def crash_zip_bytes(settings, limit: int = CRASH_ZIP_MAX_FILES) -> tuple[bytes, int]:
    """(zip bytes, file count) for [ DOWNLOAD CRASH REPORTS ].

    Built in MEMORY: the data volume is the one this server warns about
    filling up, and a download must never write into it. The files are NOT
    re-redacted -- crash_report.build_report passes both the exception message
    and the traceback through `redact` before the file is ever written, so
    what is on disk is already the redacted form, and a second pass would only
    be able to make the text less faithful."""
    buf = io.BytesIO()
    files = crash_files(settings, limit)
    written = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            try:
                zf.writestr(path.name, path.read_bytes())
                written += 1
            except OSError:
                log.warning("crash report %s could not be read for the download", path.name)
    return buf.getvalue(), written


def _check_server_crashes(conn, settings, now: str) -> None:
    """DDIAG-10: the dashboard's own crash files get a reader.

    Editors' crash counts ride the report channel and become an alert; this
    server's own were visible only to somebody with a shell in the container.
    `collector_stale` and `watchdog_restart` report the symptom and never
    point at the file that holds the cause."""
    recent = 0
    for path in crash_files(settings, limit=CRASH_ZIP_MAX_FILES):
        try:
            if path.stat().st_mtime >= _PROCESS_STARTED:
                recent += 1
        except OSError:
            continue
    if not recent:
        db.clear_notice(conn, "server_crash_report", "this server", now=now)
        return
    db.notice(
        conn, "server_crash_report", "error", "this server",
        body=(f"This server's own background tasks have crashed {recent} time(s) since "
              "it started. The details are saved on the server. Whatever that task was "
              "doing (setting projects up, sharing them, measuring them) stopped when "
              "it fell over."),
        fix=("Send us the crash files: Settings, Diagnostics, "
             "[ DOWNLOAD CRASH REPORTS ]"),
        now=now)


def _check_dashboard_space(conn, settings, now: str) -> None:
    """This server's own volume: the database, the packages and the backups.

    A full one is a SQLite write failure on the database that tells the whole
    fleet whether its footage is syncing."""
    root = Path(getattr(settings, "db_path", "") or ".").parent
    subject = str(root)
    try:
        usage = shutil.disk_usage(root)
    except OSError as exc:
        db.notice(
            conn, "dashboard_disk_low", "error", subject,
            body=(f"The free space on this server's own data volume could not be "
                  f"measured ({exc}). That is not the same as knowing it is fine."),
            fix="Check the data volume on the server.",
            now=now)
        return
    if usage.free < DASHBOARD_DISK_FLOOR_BYTES:
        db.notice(
            conn, "dashboard_disk_low", "error", subject,
            body=(f"This dashboard's own data volume has {usage.free // (1024 ** 3)} GB "
                  "free. Below a floor it refuses to publish builds, and a full volume "
                  "stops every write it makes, including the record of whether anybody's "
                  "footage is syncing."),
            fix=("Delete old builds on Settings, Packages, or give the server's data "
                 "volume more room."),
            now=now)
        return
    db.clear_notice(conn, "dashboard_disk_low", subject, now=now)


# ------------------------------------------------------------ release feed

def _check_release_feed(conn, settings, now: str) -> None:
    if not getattr(settings, "release_feed_url", ""):
        # bug-hunt-2026-09-03 dash-collector-7: returning here used to stamp
        # no evidence at all, so on the vendor default (no feed configured)
        # both kinds sat at [ NOT CHECKED ] for ever - which the checks
        # panel's contract reads as "no writer runs anywhere in this build",
        # i.e. a gap, rather than "there is no feed here to check". Closing
        # them is also right on its own terms: a site that removes its feed
        # URL must not keep an open feed_unreachable nothing can now clear.
        db.clear_notices_of_kind(conn, "feed_unreachable", (), now=now)
        db.clear_notices_of_kind(conn, "feed_runtime_mismatch", (), now=now)
        return
    state = db.get_feed_state(conn)
    error = str(state.get("last_error") or "")
    checked = str(state.get("last_checked_at") or "")
    stale = _hours_since(checked, now) if checked else None
    if error or (stale is not None and stale > FEED_STALE_HOURS) or not checked:
        db.notice(
            conn, "feed_unreachable", "warn", "vendor feed",
            body=("The vendor's release feed has not been read successfully "
                  + (_since(checked, now) if checked else "at all yet")
                  + (f": {error[:200]}" if error else ".")
                  + " No new companion or dashboard builds can arrive until it can be."),
            fix=("Press [ CHECK NOW ] on Settings, Packages. If it keeps failing, check "
                 "that this server can reach the internet."),
            now=now)
    else:
        db.clear_notice(conn, "feed_unreachable", "vendor feed", now=now)
    mismatch = db.get_feed_runtime_mismatch(conn)
    if isinstance(mismatch, dict) and mismatch:
        db.notice(
            conn, "feed_runtime_mismatch", "warn", "dashboard image",
            body=("Every dashboard build the vendor is offering was made for a different "
                  "container image than the one this server is running, so none of them "
                  "can be installed from here."),
            fix="Update the container image on the server, then check the feed again.",
            now=now)
    else:
        db.clear_notice(conn, "feed_runtime_mismatch", "dashboard image", now=now)


# ---------------------------------------------------------------- accounts

def _check_accounts(conn, settings, now: str) -> None:
    """An editor account no computer has ever reported for.

    Information, not an alarm: it is usually somebody who was set up and has
    not run the wizard yet, and that is exactly the thing that gets forgotten
    for a month."""
    cutoff = (db.parse_iso(now) - dt.timedelta(days=EDITOR_WITHOUT_MACHINE_DAYS)).isoformat()
    open_names: list[str] = []
    for row in conn.execute(
        "SELECT editor_username, first_seen AS since FROM known_editors"
    ):
        name = str(row["editor_username"] or "").strip().lower()
        if not name:
            continue
        since = str(row["since"] or "")
        if since and since > cutoff:
            continue
        machines = conn.execute(
            "SELECT COUNT(*) AS n FROM machines WHERE editor_username=?", (name,)
        ).fetchone()
        if machines and int(machines["n"]):
            continue
        open_names.append(name)
        db.notice(
            conn, "editor_without_machine", "info", name,
            body=(f"The account {name} has existed {_since(since, now) if since else 'for a while'} "
                  "and no computer has ever reported for it, so nothing is syncing for "
                  "that person."),
            fix=("Send them the installer from the [ INSTALLER ] link, or delete the "
                 "account on Settings, Users if it is not needed."),
            now=now)
    db.clear_notices_of_kind(conn, "editor_without_machine", open_names, now=now)


# ------------------------------------------------- boot-time configuration

def check_settings(conn, settings, now: str | None = None) -> None:
    """DASH-10 and its neighbours: configuration this server was STARTED with.

    Run once at boot rather than per cycle, because that is when the values
    were read. A quoted or space-padded secret is the failure that looks like
    a wrong password on every machine at once, and nothing anywhere said so."""
    stamp = now or db.utcnow_iso()
    suspicious: list[str] = []
    for name in ("report_token", "session_secret", "syncthing_api_key"):
        raw = getattr(settings, name, "")
        if not isinstance(raw, str) or not raw:
            continue
        if raw != raw.strip() or (len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "\"'"):
            suspicious.append(name)
    if suspicious:
        # The KEY names, never the values: a notice is rendered on a page and
        # may be mailed by the alerts sink.
        db.notice(
            conn, "insecure_secret", "error", ", ".join(sorted(suspicious)),
            body=("One or more of this server's passwords or tokens has quotation marks "
                  "or spaces around it, which almost always means the quotes were copied "
                  "into the setting by mistake. Everything that uses it will be refused, "
                  "on every computer at once."),
            fix=("Edit those settings on the server (no quotes, no trailing spaces) and "
                 "restart the dashboard."),
            now=stamp)
    else:
        db.clear_notices_of_kind(conn, "insecure_secret", now=stamp)
    if getattr(settings, "dev_insecure", False):
        db.notice(
            conn, "dev_insecure", "error", "DASH_DEV_INSECURE",
            body=("This server is running with its security checks relaxed: weak "
                  "passwords are accepted, sessions are not checked against the server, "
                  "and the anti-forgery token is not enforced. That switch is for tests "
                  "and development only."),
            fix="Remove DASH_DEV_INSECURE from the server's configuration and restart it.",
            now=stamp)
    else:
        db.clear_notice(conn, "dev_insecure", "DASH_DEV_INSECURE", now=stamp)
    conn.commit()


# -------------------------------------------------------------- 5xx faults

# What a server error body may carry. Truncated hard, and the exception's own
# message is NOT included: it is the one string that could hold a path, a
# query or a credential fragment.
SERVER_ERROR_BODY_CHARS = 200


def record_server_error(
    conn, path: str, exc: BaseException, now: str | None = None,
) -> None:
    """One notice per (path, exception class), counted.

    A 500 an editor met at 2 am is on the home page in the morning. Deduped by
    subject so a page failing every poll is one row with a rising count, not a
    thousand."""
    stamp = now or db.utcnow_iso()
    subject = f"{path} ({type(exc).__name__})"
    row = conn.execute(
        "SELECT body FROM notices WHERE kind='server_error' AND subject=?", (subject,),
    ).fetchone()
    seen = 1
    if row is not None:
        for token in str(row["body"] or "").split():
            if token.isdigit():
                seen = int(token) + 1
                break
    db.notice(
        conn, "server_error", "error", subject,
        body=(f"{seen} time(s) a request to {path} failed with an error "
              f"({type(exc).__name__}). Whoever was using that page saw a failure."),
        fix=("Open Settings, Diagnostics and send the detail to support. The full error "
             "is in the server log with this same path."),
        now=stamp)
    conn.commit()
