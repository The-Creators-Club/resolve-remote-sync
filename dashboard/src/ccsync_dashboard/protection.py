"""What is protected, and what only LOOKS protected.

SYS-14 (resilience sweep 2026-08-28), built 2026-08-29 as wave 5. Every
safety mechanism in this product is invisible when it is absent. The live
TrueNAS holds `dashboard.db`, `broll.db` and `music.db` under `/mnt/tank/apps`
-- a plain directory, not a dataset, so it has no scheduled snapshot at all
(CR-10, open since 2026-08-17) -- and every page in this dashboard renders
green about it. `SYNC_SAFETY.md` states the gap in prose: "there is no banner
for 'this NAS has no snapshot schedule'. Until there is, it is a runbook item,
not a system property." This module is that banner.

**THE DEFAULT IS INVERTED HERE.** A safety mechanism this server cannot
POSITIVELY VERIFY is reported as missing or as unverifiable, never as
silence and never as green. Green requires evidence: a snapshot task that
covers a named dataset, a last run inside 25 hours, a key configured, a date
an admin set. Absence of evidence renders as a chip an owner can see.

THE TRI-STATE IS THE WHOLE POINT, and it is the same tri-state
`invariants.py` uses -- this module reuses its `Outcome`, its states and its
`ok`/`broken`/`not_checked` constructors rather than growing a second parallel
vocabulary. "Could not ask" must never render as "fine": `folder_errors` and
the container healthcheck have each made exactly that mistake, and this whole
sweep turns on not making it a third time.

AMBER FOREVER IS AN ACCEPTABLE ANSWER. On DSM there is no scheduling API at
all (BACKUP_RESTORE.md section 2: snapshot schedules live in the Snapshot
Replication package, which has no supported CLI or API), so those lines read
"cannot verify, confirm in DSM" for the life of the deployment. That is
honest. A green chip there would be a lie this server has no way to check.

ONE NAS READ PER PASS, SHARED. The snapshot tasks come from
`/pool/snapshottask`, which `invariants._check_snapshot_schedule` already
asks for on the same cadence; the collector builds one memoised probe
(`nas_probe`) and hands it to both, so this panel costs no extra call and
cannot disagree with the invariant about what the NAS said. Every external
read here is bounded and fails to "cannot verify", never to an exception: a
page and a collector cycle must survive a NAS that is off.

NOTHING HERE FORMATS A SECRET. `DASH_RELEASE_PUBKEYS` is checked for
PRESENCE and counted; its value never reaches a template, a notice body, an
alert or a log line.

STORAGE IS `meta`, NOT A TABLE (2026-08-29). A schema number was reserved for
this package and given back unused: what is kept is a small CURRENT picture
(the last verdict per line) plus two admin-set dates, with no history worth
querying -- the same shape `META_ALERTS_OPEN` and `NOTICE_CHECKS_META` already
use. A migration that adds nothing a JSON blob cannot hold is a migration
every customer's database has to run for no reason. Wave 5's reservations
ended up: **39 the invariant checker, 40 the recovery package's Resolve-undo
ledger, 41 unused** -- the migration list has to stay gapless (test_db's
ordering test), so a number nobody takes is renumbered away rather than left
as a hole.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import db
from .invariants import (
    BROKEN,
    CHECK_FAILED,
    NOT_CHECKED,
    OK,
    Outcome,
    broken,
    not_checked,
    ok,
)

log = logging.getLogger("ccsync.dashboard.protection")

# The last verdict per line, and the admin-set dates. Two meta keys, no table.
RESULTS_META = "protection_results"
ACKS_META = "protection_acks"

# The two acknowledgements an admin (or, later, the recovery package) sets.
# BOTH ARE STORED AS DATES, never as booleans: "the release key is backed up"
# is a claim that ages, and a restore drill that happened in 2024 is not a
# restore drill. A boolean would make "when" unanswerable, and the sibling
# recovery work package (SYS-15d) records its own drill through
# `record_restore_drill` into the same shape.
ACK_KEY_BACKUP = "release_key_backup"
ACK_RESTORE_DRILL = "restore_drill"
ACK_KEYS = (ACK_KEY_BACKUP, ACK_RESTORE_DRILL)

# A snapshot older than this is not a snapshot of today's work. 25 h rather
# than 24: BACKUP_RESTORE.md section 1 schedules hourly snapshots kept a day,
# and a flat 24 h would redden every deployment whose task runs a minute late.
SNAPSHOT_MAX_AGE_SECONDS = 25 * 3600

# A restore nobody has tried in a year is a hypothesis, not a backup
# (SYS-15d's sentence, and the reason this line exists at all).
DRILL_MAX_AGE_DAYS = 365

# `.ccsync-trash`'s documented bound (SYNC_SAFETY.md section 2: 14 days or
# 50 GB, whichever comes first). The dashboard only ever sees the SIZE a
# companion reported -- no machine reports the age of its oldest trashed file
# -- so this line is honest about checking one half of the retention rule and
# says so in its own detail.
TRASH_BOUND_BYTES = 50 * 1024 ** 3

# DDIAG-16 (2026-09-04). Whether the alarm itself can reach a person is
# `alerts.sink_deliverable`, not a second opinion here: invariant 15 and this
# panel must never disagree about it, and the 30 day evidence window lives
# with the ledger it reads (alerts.SEND_EVIDENCE_MAX_AGE_SECONDS).

# Which dataset holds what. Neither is a Settings field on purpose: a
# container sees `/data` and `/projects`, never the pool path behind them
# (dashboard_update.snapshot_before says so), so the pool-side names are
# deployment facts supplied by the environment. DASH_UPDATE_SNAPSHOT_DATASET
# already exists and already means "the dataset this dashboard's own data is
# on"; DASH_TREE_DATASET is its counterpart for the footage, matching
# `server/setup_snapshots.py`'s two targets ([tree] pool_root and [apps]
# root). Unset is NOT "no snapshot": it is "this server was never told", and
# renders as cannot-verify with the variable named in the fix.
ENV_APPS_DATASET = "DASH_UPDATE_SNAPSHOT_DATASET"
ENV_TREE_DATASET = "DASH_TREE_DATASET"

# The two notice kinds this module writes. Registered in db.NOTICE_KINDS
# beside their writers, which is the rule finding 1 of the 2026-08-28 fix
# pass paid for: a kind registered with no writer ticks itself [ OK ].
NOTICE_MISSING = "protection_missing"
NOTICE_UNVERIFIABLE = "protection_unverifiable"

# Chip wording. The states are invariants.py's, the LABELS are this panel's:
# an owner reading about backups needs "MISSING", not "BROKEN".
STATE_LABELS = {
    OK: "PROTECTED",
    BROKEN: "MISSING",
    NOT_CHECKED: "CANNOT VERIFY",
    CHECK_FAILED: "COULD NOT RUN",
}


# --------------------------------------------------------------- the probe

class NasProbe:
    """One bounded read of the NAS's snapshot schedule, memoised.

    Built once per collector pass and handed to BOTH this module and
    `invariants.Ctx(snapshot_tasks_fn=...)`, so the two never make two calls
    or reach two different conclusions from two moments. `tasks()` returns
    None for every failure -- unconfigured, unreachable, refused, a shape we
    will not guess at -- because "could not ask" and "there are none" are
    different answers and only one of them is an emergency.
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._tasks: list[dict[str, Any]] | None = None
        self._asked = False

    @property
    def kind(self) -> str:
        return str(getattr(self.settings, "nas_kind", "") or "truenas").strip().lower()

    def tasks(self) -> list[dict[str, Any]] | None:
        if self._asked:
            return self._tasks
        self._asked = True
        self._tasks = self._read()
        return self._tasks

    def _read(self) -> list[dict[str, Any]] | None:
        try:
            from .nas import capability
            from .nas.factory import make_nas_client, nas_configured

            if not nas_configured(self.settings):
                return None
            client = make_nas_client(self.settings)
            try:
                lister = capability(client, "list_snapshot_tasks")
                if lister is None:
                    # DSM. `capability` returning None means "this NAS cannot
                    # be asked", never "the answer is no".
                    return None
                rows = lister()
            finally:
                closer = getattr(client, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:                                # noqa: BLE001
                        pass
            return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None
        except Exception:                                            # noqa: BLE001
            log.debug("protection: could not read the NAS snapshot tasks", exc_info=True)
            return None


def nas_probe(settings: Any) -> NasProbe:
    return NasProbe(settings)


# ----------------------------------------------------------------- the ctx

class Ctx:
    """What the lines read, gathered once per pass.

    Everything fallible is injected or lazy, and anything that could not be
    read is None, which every line turns into CANNOT VERIFY rather than into
    a green chip.
    """

    def __init__(self, conn: sqlite3.Connection, settings: Any, now: str,
                 tasks_fn: Callable[[], list[dict[str, Any]] | None] | None = None,
                 folder_versioning: dict[str, Any] | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.conn = conn
        self.settings = settings
        self.now = now
        self._tasks_fn = tasks_fn
        # slug -> the live Syncthing folder's `versioning` block, from the
        # config cycle. None means no pass has read the folder list in THIS
        # process, which is not evidence that versioning is configured --
        # the same rule invariants.Ctx.folder_devices follows.
        self.folder_versioning = folder_versioning
        self.env = dict(os.environ) if env is None else dict(env)
        self._acks: dict[str, dict[str, str]] | None = None
        self._tasks: list[dict[str, Any]] | None = None
        self._asked = False

    @property
    def nas_kind(self) -> str:
        return str(getattr(self.settings, "nas_kind", "") or "truenas").strip().lower()

    @property
    def is_dsm(self) -> bool:
        return self.nas_kind == "synology"

    def tasks(self) -> list[dict[str, Any]] | None:
        if not self._asked:
            self._asked = True
            if self._tasks_fn is None:
                self._tasks = nas_probe(self.settings).tasks()
            else:
                try:
                    self._tasks = self._tasks_fn()
                except Exception:                                    # noqa: BLE001
                    log.debug("protection: the snapshot probe raised", exc_info=True)
                    self._tasks = None
        return self._tasks

    def enabled_tasks(self) -> list[dict[str, Any]]:
        """Tasks that would actually run. A task present but DISABLED is the
        most misleading state on a NAS: it is there, it is listed, and it
        takes nothing."""
        return [t for t in (self.tasks() or []) if t.get("enabled", True)]

    def dataset(self, which: str) -> str:
        var = ENV_TREE_DATASET if which == "tree" else ENV_APPS_DATASET
        return (self.env.get(var) or "").strip()

    def acks(self) -> dict[str, dict[str, str]]:
        if self._acks is None:
            self._acks = read_acks(self.conn)
        return self._acks


# ------------------------------------------------------------- the registry

@dataclass(frozen=True)
class ProtectionLine:
    """One safety mechanism, and what its absence costs.

    `consequence` is the sentence a non-technical owner reads: what is lost
    in the world when this is not there. `fix` is the exact next action.
    `what` is the one-liner the weekly report and the checks panel print, so
    a line that is fine is still provably CHECKED.

    Adding a safety mechanism is adding a ROW: the panel, the weekly report,
    the notices and the two alert kinds all pick it up with no second edit,
    which is the shape `alerts.ALERT_KINDS` and `invariants.INVARIANTS` use
    for the same reason.
    """
    key: str
    title: str
    what: str
    consequence: str
    fix: str
    check: Callable[[Ctx], Outcome]
    severity: str = "error"


# ---------------------------------------------------------------- the lines

def _dsm_cannot_verify() -> Outcome:
    """DSM's honest amber, forever.

    Synology's snapshot SCHEDULES live in the Snapshot Replication package,
    which has no supported CLI or API (BACKUP_RESTORE.md section 2), so this
    server cannot ever get positive evidence. It says so instead of guessing,
    and it keeps saying so: a line that went quiet after a week would be
    indistinguishable from a line that turned green.
    """
    return not_checked(
        "cannot verify, confirm in DSM: this Synology's snapshot schedules are "
        "in the Snapshot Replication package, which this server has no way to "
        "read. Open DSM, Snapshot Replication, and check the schedule yourself.")


def _covers(task: dict[str, Any], dataset: str) -> bool:
    """Whether one snapshot task covers `dataset`.

    A recursive task on a parent covers its children, which is exactly how
    `server/setup_snapshots.py` writes them ("a dataset that gains a CHILD
    later must not silently fall outside the backup"). Anything else is an
    exact match, because a task on a SIBLING dataset protects nothing here.
    """
    own = str(task.get("dataset") or "").strip()
    if not own:
        return False
    if own == dataset:
        return True
    return bool(task.get("recursive")) and dataset.startswith(own + "/")


def _dataset_line(ctx: Ctx, which: str, human: str, matters: str) -> Outcome:
    if ctx.is_dsm:
        return _dsm_cannot_verify()
    tasks = ctx.tasks()
    if tasks is None:
        return not_checked(
            "this server cannot ask the NAS about its snapshot schedule (no NAS "
            "credential is configured, or the NAS did not answer)")
    dataset = ctx.dataset(which)
    if not dataset:
        var = ENV_TREE_DATASET if which == "tree" else ENV_APPS_DATASET
        return not_checked(
            f"this server has not been told which dataset {human} is on, so it "
            f"cannot tell whether any of the {len(tasks)} snapshot task(s) on this "
            f"NAS covers it. Set {var} on the dashboard container.")
    covering = [t for t in ctx.enabled_tasks() if _covers(t, dataset)]
    if not covering:
        return broken(
            [(dataset, f"no enabled snapshot task covers this dataset, so {matters}")],
            f"{len(ctx.enabled_tasks())} enabled snapshot task(s) on this NAS, "
            f"none covering {dataset}")
    return ok(f"{len(covering)} enabled snapshot task(s) cover {dataset}")


def _check_snapshot_tree(ctx: Ctx) -> Outcome:
    return _dataset_line(
        ctx, "tree", "the project tree",
        "there is nothing to restore footage from if a project folder is "
        "deleted, overwritten or lost")


def _check_snapshot_apps(ctx: Ctx) -> Outcome:
    """CR-10, said out loud.

    The live TrueNAS keeps `dashboard.db`, `broll.db` and `music.db` under
    `/mnt/tank/apps`, which is a plain DIRECTORY: it cannot carry a snapshot
    task at all, so this line is either MISSING (a dataset was named and
    nothing covers it) or CANNOT VERIFY (nothing named it). It is not green,
    which is the entire point of the package.
    """
    return _dataset_line(
        ctx, "apps", "this dashboard's own data",
        "the fleet's projects, editors, ticks and search indexes have no "
        "point-in-time behind them: losing that file loses the fleet's "
        "configuration, not just its footage")


def _task_last_run(task: dict[str, Any]) -> datetime | None:
    """When a snapshot task last actually ran, or None when the NAS did not
    say.

    TrueNAS reports it under `state.datetime`, as either a millisecond epoch
    wrapped in `{"$date": ...}` or an ISO string depending on version, and
    older versions report nothing at all. None here becomes CANNOT VERIFY,
    never "it has not run".
    """
    state = task.get("state")
    raw: Any = None
    if isinstance(state, dict):
        raw = state.get("datetime")
    if raw is None:
        raw = task.get("last_run") or task.get("last_run_at")
    if isinstance(raw, dict):
        raw = raw.get("$date")
    if isinstance(raw, (int, float)):
        # Milliseconds since the epoch (TrueNAS's JSON date wrapper); a plain
        # seconds value from some other build is told apart by magnitude.
        seconds = float(raw) / 1000.0 if float(raw) > 1e11 else float(raw)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str) and raw.strip():
        try:
            when = db.parse_iso(raw.strip())
        except (ValueError, TypeError):
            return None
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return None


def _check_snapshot_recent(ctx: Ctx) -> Outcome:
    """A schedule that exists and has not run is not a backup.

    WPK-6 is the incident behind this line: a pre-recreate snapshot failed
    silently on every deploy for weeks and nobody could tell, because the
    only evidence anybody looked at was that the task existed.
    """
    if ctx.is_dsm:
        return _dsm_cannot_verify()
    tasks = ctx.tasks()
    if tasks is None:
        return not_checked(
            "this server cannot ask the NAS about its snapshot schedule (no NAS "
            "credential is configured, or the NAS did not answer)")
    enabled = ctx.enabled_tasks()
    if not enabled:
        return broken(
            [("this NAS", "no snapshot task is enabled, so nothing has been "
                          "snapshotted at all and there is no point-in-time to "
                          "go back to")],
            f"{len(tasks)} snapshot task(s), none enabled")
    runs = [(t, _task_last_run(t)) for t in enabled]
    dated = [(t, when) for t, when in runs if when is not None]
    if not dated:
        return not_checked(
            f"{len(enabled)} enabled snapshot task(s), and this NAS does not "
            f"report when any of them last ran, so this server cannot tell "
            f"whether they are actually taking snapshots. Check the last-run "
            f"column on the NAS under Data Protection, Periodic Snapshot Tasks.")
    try:
        now = db.parse_iso(ctx.now)
    except (ValueError, TypeError):
        return not_checked("this server could not read its own clock")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    newest_task, newest = max(dated, key=lambda pair: pair[1])
    age = (now - newest).total_seconds()
    hours = int(age // 3600)
    if age > SNAPSHOT_MAX_AGE_SECONDS:
        return broken(
            [(str(newest_task.get("dataset") or "this NAS"),
              f"the newest snapshot on this NAS is about {hours} hour(s) old, so "
              f"anything done since then is not covered by anything")],
            f"newest snapshot {hours} h old, over the {SNAPSHOT_MAX_AGE_SECONDS // 3600} h limit")
    return ok(f"the newest snapshot on this NAS is about {hours} hour(s) old "
              f"({newest_task.get('dataset') or '?'})")


def _check_release_keys(ctx: Ctx) -> Outcome:
    """Only a COUNT is ever reported. The keys themselves never leave here."""
    keys = tuple(getattr(ctx.settings, "release_pubkeys", ()) or ())
    if not keys:
        return broken(
            [("this server", "no release signing key is configured, so this "
                             "dashboard cannot tell a build we published from "
                             "one somebody else made")],
            "DASH_RELEASE_PUBKEYS is not set")
    return ok(f"{len(keys)} release signing key(s) configured")


def _ack_date(ctx: Ctx, key: str) -> tuple[str, float | None]:
    """(the date an admin recorded, its age in days) or ("", None)."""
    entry = ctx.acks().get(key) or {}
    date = str(entry.get("date") or "").strip()
    if not date:
        return "", None
    try:
        when = db.parse_iso(date if "T" in date else date + "T00:00:00+00:00")
        now = db.parse_iso(ctx.now)
    except (ValueError, TypeError):
        return date, None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return date, (now - when).total_seconds() / 86400.0


def _check_key_backup(ctx: Ctx) -> Outcome:
    """The offline release key, backed up. An ADMIN-SET DATE, because nothing
    on this server can see a key that lives on somebody's workstation.

    A site with no signing key configured has nothing to have backed up, and
    saying MISSING there would be a false alarm on every customer running
    only the vendor feed.
    """
    if not tuple(getattr(ctx.settings, "release_pubkeys", ()) or ()):
        return not_checked(
            "this server has no release signing key configured, so there is "
            "nothing here to have backed up")
    date, age = _ack_date(ctx, ACK_KEY_BACKUP)
    if not date:
        return broken(
            [("the release signing key", "nobody has confirmed that the offline "
                                         "release key is backed up. Lose it and no "
                                         "further update can ever be published to "
                                         "these computers")],
            "no backup has been recorded")
    if age is None:
        return not_checked(f"the recorded backup date ({date}) could not be read")
    return ok(f"backup confirmed on {date}")


def _check_restore_drill(ctx: Ctx) -> Outcome:
    """A backup nobody has restored from is a hypothesis (SYS-15d).

    Stored as a DATE the dashboard reads, not a boolean it computes, so the
    sibling recovery package can record a drill it ran itself into the same
    place with `record_restore_drill` and this line needs no edit.
    """
    date, age = _ack_date(ctx, ACK_RESTORE_DRILL)
    if not date:
        return broken(
            [("this server", "nobody has ever restored anything from a backup "
                             "here, so whether the backups work is unknown")],
            "no restore has ever been recorded")
    if age is None:
        return not_checked(f"the recorded restore date ({date}) could not be read")
    if age > DRILL_MAX_AGE_DAYS:
        return broken(
            [("this server", f"the last restore was tried on {date}, over a year "
                             f"ago. Backups that have not been restored from in a "
                             f"year have usually stopped working")],
            f"last drill {int(age)} day(s) ago")
    return ok(f"a restore was last tried on {date}, {int(age)} day(s) ago")


def _check_server_versioning(ctx: Ctx) -> Outcome:
    """Deleted files on the SERVER are kept (`.stversions`).

    `provision.build_folder_config` writes staggered versioning with a
    365-day maxAge onto every project folder; nothing has ever re-checked
    that it is still there, and a folder created by hand, or edited in the
    Syncthing UI, carries none. Without it a delete that syncs up from one
    editor is simply gone from the NAS.
    """
    if ctx.folder_versioning is None:
        return not_checked(
            "this server has not read its sync engine's folder list yet in this "
            "session, so it cannot say what happens to files deleted on the server")
    if not ctx.folder_versioning:
        return not_checked("there are no project folders on this server to check")
    bad: list[tuple[str, str]] = []
    ages: list[int] = []
    for slug in sorted(ctx.folder_versioning):
        block = ctx.folder_versioning.get(slug) or {}
        kind = str(block.get("type") or "").strip() if isinstance(block, dict) else ""
        params = block.get("params") if isinstance(block, dict) else None
        max_age = 0
        if isinstance(params, dict):
            try:
                max_age = int(str(params.get("maxAge") or "0"))
            except (TypeError, ValueError):
                max_age = 0
        if not kind or max_age <= 0:
            bad.append((slug, "files deleted on the server for this project are "
                              "not kept anywhere: there is no version history on "
                              "that folder"))
        else:
            ages.append(max_age)
    if bad:
        return broken(bad, f"{len(bad)} of {len(ctx.folder_versioning)} project "
                           f"folder(s) keep no deleted files")
    days = min(ages) // 86400 if ages else 0
    return ok(f"{len(ctx.folder_versioning)} project folder(s) keep deleted files "
              f"for at least {days} day(s)")


def _check_editor_trash(ctx: Ctx) -> Outcome:
    """`.ccsync-trash` on editors' machines, within its documented bound.

    SYNC_SAFETY.md section 2 bounds it at 14 days OR 50 GB. Only the SIZE
    half is checkable from here: no companion reports the age of its oldest
    trashed file, so this line says which half it checked rather than
    implying both.
    """
    try:
        rows = list(ctx.conn.execute(
            "SELECT editor_username, machine, trash_bytes FROM machine_state "
            "WHERE trash_bytes IS NOT NULL"))
    except sqlite3.Error:
        return not_checked("this server could not read what the computers reported")
    if not rows:
        return not_checked(
            "no computer has reported the size of its deleted-file safety copies "
            "yet (CC Sync 0.9.55 and newer report it)")
    over = [(f"{r['editor_username']}/{r['machine']}",
             f"{int(r['trash_bytes']) // (1024 ** 3)} GB of deleted-file safety "
             f"copies, over the {TRASH_BOUND_BYTES // (1024 ** 3)} GB limit they "
             f"are meant to be pruned to")
            for r in rows if int(r["trash_bytes"] or 0) > TRASH_BOUND_BYTES]
    if over:
        return broken(over, f"{len(over)} of {len(rows)} computer(s) are over the limit")
    largest = max(int(r["trash_bytes"] or 0) for r in rows) // (1024 ** 3)
    return ok(f"{len(rows)} computer(s) reporting, largest {largest} GB, all under "
              f"the {TRASH_BOUND_BYTES // (1024 ** 3)} GB size limit (the 14 day "
              f"half of the rule is not reported by any computer)")


def _check_alerts_sink(ctx: Ctx) -> Outcome:
    """Whether a human is actually told when any of the lines above breaks
    (DDIAG-16, 2026-09-04).

    Green needs BOTH halves, on this module's inverted default: a sink is set
    AND something has been delivered through it inside
    alerts.SEND_EVIDENCE_MAX_AGE_SECONDS. A configured-but-silent channel is
    the state that feels safest and is not, so it is reported as missing
    rather than as "configured".

    The verdict itself is `alerts.sink_deliverable`, shared with invariant 15
    (SYS-1, 2026-09-04): two answers to "can this server tell anybody" that
    could drift apart would be worse than one.

    `alerts` is imported here rather than at module scope because
    `alerts.compose_weekly` imports THIS module for the weekly report's
    protection block; the cycle is real and this is the end that can afford to
    be lazy.
    """
    from . import alerts

    try:
        deliverable, detail = alerts.sink_deliverable(ctx.conn, ctx.now)
    except sqlite3.Error:
        return not_checked("this server could not read its own record of what "
                           "it has sent")
    except (ValueError, TypeError):
        return not_checked("this server could not read when it last sent "
                           "anything")
    if deliverable:
        return ok(detail)
    sink = alerts.get_settings(ctx.conn).get("alerts_sink") or alerts.SINK_NONE
    subject = "no alert channel" if sink == alerts.SINK_NONE else sink
    return broken([(subject, detail)],
                  "nobody is told when something breaks here"
                  if sink == alerts.SINK_NONE else detail)


def _alert_kind_count() -> int:
    """How many things `alerts.py` checks, for the sentence below (SYS-1).

    Imported lazily and defended: this runs at MODULE IMPORT time, and a
    dashboard boot must never be made fatal by a line of copy. The fallback is
    a round number that reads as an estimate rather than a false count.
    """
    try:
        from . import alerts
        return len(alerts.ALERT_KINDS)
    except Exception:                                                # noqa: BLE001
        log.exception("protection: could not count the alert checks")
        return 40


# The registry. Order is the order the panel and the report print, worst
# consequence first: everything about restoring lost footage, then the
# release channel, then the two "deleted files are still somewhere" lines.
LINES: tuple[ProtectionLine, ...] = (
    ProtectionLine(
        "snapshot_tree",
        "the project tree is on a snapshot schedule",
        "whether the footage on the server can be rolled back",
        "Without a snapshot schedule on the footage there is nothing to restore "
        "from: a folder deleted by hand, a bad sync or a failed disk is simply gone.",
        "On the NAS: Data Protection, Periodic Snapshot Tasks, add an enabled "
        "task covering the dataset the project tree lives on. "
        "server/setup_snapshots.py does it in one command.",
        _check_snapshot_tree),
    ProtectionLine(
        "snapshot_apps",
        "this dashboard's own data is on a snapshot schedule",
        "whether this dashboard's database can be rolled back",
        "The fleet's projects, editors, ticks, client links and search indexes "
        "all live in one folder on the NAS. Without a snapshot behind it, losing "
        "that folder loses how the fleet is set up, not only its footage.",
        "On the NAS: make the folder holding the CC Sync data a dataset, then add "
        "an enabled periodic snapshot task for it (server/setup_snapshots.py "
        "--apps-root). Tell this dashboard its name with DASH_UPDATE_SNAPSHOT_DATASET.",
        _check_snapshot_apps),
    ProtectionLine(
        "snapshot_recent",
        "a snapshot was actually taken in the last day",
        "whether the snapshot schedule is really running",
        "A schedule that exists but has stopped running looks exactly like a "
        "working one from every page in this product, and the day you need it "
        "the newest point-in-time is weeks old.",
        "On the NAS: Data Protection, Periodic Snapshot Tasks, check the last-run "
        "column and the pool's free space (a full pool stops snapshots).",
        _check_snapshot_recent),
    ProtectionLine(
        "release_keys",
        "this server only accepts CC Sync builds we signed",
        "whether update signing is switched on",
        "Without a signing key this dashboard cannot tell an update we published "
        "from one somebody else made, and it hands whatever it has to every "
        "computer in the fleet.",
        "Set DASH_RELEASE_PUBKEYS on the dashboard container to the release "
        "public key (docs/RELEASE.md), then restart it.",
        _check_release_keys),
    ProtectionLine(
        "release_key_backup",
        "the release signing key has been backed up",
        "whether the update signing key survives losing one computer",
        "The signing key exists in one place, on one workstation, and is not in "
        "any repository on purpose. Lose it and no further update can ever be "
        "published to these computers over the air.",
        "Copy the release key off that workstation to somewhere it can be found "
        "again (docs/SECRETS.md), then record it here with "
        "[ I HAVE BACKED IT UP ].",
        _check_key_backup),
    ProtectionLine(
        "restore_drill",
        "somebody has actually restored from a backup this year",
        "whether the backups have ever been proven to work",
        "A backup nobody has restored from is a hypothesis. Every documented "
        "recovery path here starts with finding a snapshot, and the first time "
        "anyone tries should not be the day something is lost.",
        "Restore one project folder from a snapshot into a scratch path, check "
        "the files open, then record the date here with [ RECORD A RESTORE ].",
        _check_restore_drill),
    ProtectionLine(
        "server_versioning",
        "files deleted on the server are kept for a year",
        "whether deleted files can be got back off the server",
        "Without version history on a project folder, a delete that syncs up "
        "from one editor's computer removes the file from the server outright.",
        "Untick and re-tick that project so this server rebuilds the folder, or "
        "set File Versioning (staggered) on it in Syncthing on the NAS.",
        _check_server_versioning,
        severity="error"),
    ProtectionLine(
        "editor_trash",
        "deleted-file copies on editors' computers are within their limit",
        "whether editors' computers are still pruning their safety copies",
        "CC Sync keeps a copy of everything it deletes on an editor's computer. "
        "They are pruned automatically, and a computer well over the limit is a "
        "computer whose pruning has stopped, filling the drive footage needs.",
        "Check that computer's row on the SYNC STATUS page for [ RESUME ]: pruning is "
        "paused while its download safety brake is on.",
        _check_editor_trash,
        severity="warn"),
    # DDIAG-16 / SYS-1 (2026-09-04). The panel had eight lines about safety
    # nets and none about whether their failure ever reaches a person.
    # ERROR, not warn (SYS-1 (a), the owner's call on the wave 2 brief): a
    # fresh install really is unprotected in the way that matters most, and
    # the counter-argument - that a red on day one teaches an owner to ignore
    # the panel - is answered by the fix line, which is two clicks. The count
    # is READ FROM THE REGISTRY rather than written into the sentence: the
    # last time a number like this was typed into copy it was wrong within a
    # wave.
    ProtectionLine(
        "alerts_sink",
        "somebody is told when this server finds a problem",
        "whether a problem here reaches a person",
        f"This server checks {_alert_kind_count()} things every few minutes "
        f"and writes down what is wrong. With nobody to tell, the first anyone "
        f"hears of a stopped sync is an editor asking.",
        "On Settings, Alerts: choose mail or a webhook, then press "
        "[ SEND A TEST ].",
        _check_alerts_sink,
        severity="error"),
)

BY_KEY: dict[str, ProtectionLine] = {line.key: line for line in LINES}


# ------------------------------------------------------------------ storage

def read_acks(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """{ack key: {date, by, at}}. Never raises: a page must render on a
    database an older build migrated."""
    try:
        stored = db.meta_get_json(conn, ACKS_META)
    except sqlite3.Error:
        return {}
    if not isinstance(stored, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, value in stored.items():
        if isinstance(value, dict):
            out[str(key)] = {k: str(v) for k, v in value.items()}
    return out


def set_ack(conn: sqlite3.Connection, key: str, date: str, by: str,
            now: str | None = None) -> dict[str, str]:
    """Record an admin's acknowledgement. Raises ValueError on anything this
    module would then have to guess at, so a typo'd date turns into a message
    on the page rather than a line that silently reads as never-done."""
    if key not in ACK_KEYS:
        raise ValueError(f"unknown acknowledgement {key!r}")
    stamp = now or db.utcnow_iso()
    text = (date or "").strip() or stamp[:10]
    try:
        db.parse_iso(text if "T" in text else text + "T00:00:00+00:00")
    except (ValueError, TypeError):
        raise ValueError("that is not a date this server can read. Use YYYY-MM-DD.")
    if text[:10] > stamp[:10]:
        # A date in the future would make the line green for a year on a
        # fat-fingered year. Refuse it where it is typed.
        raise ValueError("that date is in the future.")
    acks = read_acks(conn)
    entry = {"date": text[:10], "by": str(by or ""), "at": stamp}
    acks[key] = entry
    db.meta_set_json(conn, ACKS_META, acks)
    return entry


def record_restore_drill(conn: sqlite3.Connection, by: str, date: str = "",
                         now: str | None = None) -> dict[str, str]:
    """The hook the recovery package (SYS-15) calls when the dashboard itself
    performs a restore. Deliberately the same store the admin's button
    writes: the panel reads a DATE and does not care who put it there."""
    stamp = now or db.utcnow_iso()
    return set_ack(conn, ACK_RESTORE_DRILL, date or stamp[:10], by, now=stamp)


def _store_results(conn: sqlite3.Connection, results: list[dict[str, Any]],
                   now: str) -> None:
    """The last verdict per line. Best-effort: recording the picture must not
    be able to break the pass that produced it."""
    try:
        db.meta_set_json(conn, RESULTS_META, {"checked_at": now, "lines": results})
    except sqlite3.Error:
        log.exception("protection: could not record this pass")


def stored_results(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        stored = db.meta_get_json(conn, RESULTS_META)
    except sqlite3.Error:
        return {}
    return stored if isinstance(stored, dict) else {}


# ------------------------------------------------------------------ the pass

def evaluate(ctx: Ctx) -> list[dict[str, Any]]:
    """Every line's verdict. NEVER RAISES: a line whose check raised becomes
    its own COULD NOT RUN, because a check that could not run must never read
    as a safety net that is present."""
    results: list[dict[str, Any]] = []
    for line in LINES:
        try:
            outcome = line.check(ctx)
        except Exception as exc:                                     # noqa: BLE001
            log.exception("protection line %s could not run", line.key)
            outcome = Outcome(CHECK_FAILED, f"{type(exc).__name__}: {str(exc)[:200]}")
        results.append({
            "key": line.key, "title": line.title, "what": line.what,
            "consequence": line.consequence, "fix": line.fix,
            "severity": line.severity, "state": outcome.state,
            "label": STATE_LABELS.get(outcome.state, outcome.state.upper()),
            "detail": outcome.detail,
            "subjects": [{"subject": s, "detail": d} for s, d in outcome.subjects],
        })
    return results


def run_cycle(conn: sqlite3.Connection, settings: Any, now: str,
              tasks_fn: Callable[[], list[dict[str, Any]] | None] | None = None,
              folder_versioning: dict[str, Any] | None = None) -> dict[str, Any]:
    """One protection pass: evaluate, store, and file what is missing.

    Returns {"results", "note", "counts"}; the note is what keeps a pass that
    found a hole from looking like a clean one on the collector health panel.

    A line that is MISSING files an error notice, and a line this deployment
    CANNOT VERIFY files a warn notice -- deliberately, because a safety
    mechanism nobody can check is a fact the owner has to be told once and
    not have quietly hidden. Writing the ledger is best-effort per line: a
    database error on one row must not lose the other seven verdicts.
    """
    ctx = Ctx(conn, settings, now, tasks_fn=tasks_fn,
              folder_versioning=folder_versioning)
    results = evaluate(ctx)
    missing: list[str] = []
    unverifiable: list[str] = []
    for result in results:
        line = BY_KEY[result["key"]]
        try:
            if result["state"] == BROKEN:
                for subject in result["subjects"]:
                    key = f"{line.key}: {subject['subject']}"
                    missing.append(key)
                    db.notice(
                        conn, NOTICE_MISSING, line.severity, key,
                        body=(f"{line.consequence} This server checks that "
                              f"{line.title}, and it cannot see that it is: "
                              f"{subject['detail']}."),
                        fix=line.fix, now=now)
            elif result["state"] in (NOT_CHECKED, CHECK_FAILED):
                unverifiable.append(line.key)
                db.notice(
                    conn, NOTICE_UNVERIFIABLE, "warn", line.key,
                    body=(f"This server cannot confirm that {line.title}. "
                          f"{line.consequence} Treat it as unchecked, not as "
                          f"fine: {result['detail']}"),
                    fix=line.fix, now=now)
        except sqlite3.Error:
            log.exception("protection: could not file %s", line.key)
    try:
        db.clear_notices_of_kind(conn, NOTICE_MISSING, missing, now=now)
        db.clear_notices_of_kind(conn, NOTICE_UNVERIFIABLE, unverifiable, now=now)
    except sqlite3.Error:
        # A database an older build migrated has no notices table. The
        # verdicts are still worth storing: the panel is this module's own
        # ledger and does not depend on the notices ledger existing.
        log.exception("protection: could not close its notices")
    _store_results(conn, results, now)
    conn.commit()
    counts = _counts(results)
    return {"results": results, "note": _note(counts), "counts": counts}


def _counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in (OK, BROKEN, NOT_CHECKED, CHECK_FAILED)}
    for result in results:
        counts[result["state"]] = counts.get(result["state"], 0) + 1
    return counts


def _note(counts: dict[str, int]) -> str | None:
    parts = []
    if counts.get(BROKEN):
        parts.append(f"{counts[BROKEN]} safety mechanism(s) missing")
    if counts.get(CHECK_FAILED):
        parts.append(f"{counts[CHECK_FAILED]} protection check(s) could not run")
    if counts.get(NOT_CHECKED):
        parts.append(f"{counts[NOT_CHECKED]} unverifiable here")
    return "; ".join(parts) if parts else None


def page_view(conn: sqlite3.Connection) -> dict[str, Any]:
    """Every line with its last verdict, for the panel.

    THE REGISTRY IS THE SPINE, not the stored blob: a line no pass has
    evaluated yet (a fresh boot, a line added by a build that has not run a
    pass) renders CANNOT VERIFY rather than being absent from the page. A
    panel that silently omits a safety mechanism is the bug this module
    exists to end.
    """
    stored = stored_results(conn)
    by_key = {str(r.get("key")): r for r in (stored.get("lines") or [])
              if isinstance(r, dict)}
    acks = read_acks(conn)
    rows: list[dict[str, Any]] = []
    for line in LINES:
        row = by_key.get(line.key) or {}
        state = str(row.get("state") or NOT_CHECKED)
        rows.append({
            "key": line.key, "title": line.title, "what": line.what,
            "consequence": line.consequence, "fix": line.fix,
            "severity": line.severity, "state": state,
            "label": STATE_LABELS.get(state, state.upper()),
            "detail": str(row.get("detail") or
                          ("no protection pass has run yet on this server")),
            "subjects": list(row.get("subjects") or []),
        })
    counts = {state: sum(1 for r in rows if r["state"] == state)
              for state in (OK, BROKEN, NOT_CHECKED, CHECK_FAILED)}
    return {
        "lines": rows,
        "counts": counts,
        "checked_at": str(stored.get("checked_at") or ""),
        "acks": acks,
    }


def weekly_lines(conn: sqlite3.Connection) -> list[str]:
    """The WHAT IS PROTECTED block of the weekly report (SYS-8 asked for
    SYS-14's absence checks as a standing line, red for as long as they are
    true). Reads the last stored pass; it never evaluates, because the report
    must not make a NAS call from whatever thread composed it."""
    view = page_view(conn)
    counts = view["counts"]
    out = [f"WHAT IS PROTECTED ({counts[OK]} of {len(LINES)} confirmed, "
           f"{counts[BROKEN]} missing, "
           f"{counts[NOT_CHECKED] + counts[CHECK_FAILED]} unverifiable)"]
    for row in view["lines"]:
        out.append(f"  [ {row['label']} ] {row['title']}")
        if row["detail"]:
            out.append(f"      {row['detail']}")
        for subject in row["subjects"]:
            detail = subject.get("detail") if isinstance(subject, dict) else ""
            name = subject.get("subject") if isinstance(subject, dict) else str(subject)
            out.append(f"      - {name}: {detail}")
        if row["state"] != OK:
            out.append(f"      WHAT TO DO: {row['fix']}")
    if not view["checked_at"]:
        out.append("  (no protection pass has run on this server yet)")
    out.append("")
    return out
