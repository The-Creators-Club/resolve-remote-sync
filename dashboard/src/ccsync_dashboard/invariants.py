"""The continuous invariant checker: facts this system relies on, re-verified.

SYS-9 (resilience sweep 2026-08-28), built 2026-08-29 as wave 5. Every
cross-component fact in this product is enforced at the moment something
WRITES it and never asked about again. A tick is written while Syncthing is
unreachable; a project folder is renamed on the NAS by hand; a disk image is
copied onto a second PC and two computers claim one identity; a package is
published with a `min_version` above the build it describes. Each of those is
a fact that was true when it was written and is not true now, and nothing in
the system ever notices.

`collector.folder_tuning_drift` proves the pattern is understood: it re-reads
a Syncthing folder's settings every cycle and repairs the keys that drifted.
It covers folder tuning ALONE. This module is the same idea applied to the
facts that span components, with one deliberate difference:

**IT REPAIRS NOTHING. IT NAMES THINGS.** A checker that also fixed would need
to be trusted with writes to Syncthing, the tree and the registry on a
schedule, and the failure mode of a wrong repair here is B16 (the whole fleet
unshared in one pass). Naming is the gap; repair is a button somebody presses.

THE INVARIANTS ARE DATA (`INVARIANTS`), not a chain of ifs -- the shape
`alerts.ALERT_KINDS` uses, for the same reason: adding an invariant is adding
a row, and the ledger, the admin page, the notices, the alert kind and the
weekly report all pick it up with no second edit.

THREE STATES, NEVER TWO. An invariant is `ok`, `broken`, `not_checked` or
`check_failed`, and the last two are the load-bearing ones: an invariant this
deployment cannot evaluate (no NAS API key, no project tree mounted, no
Syncthing snapshot yet) must render as NOT CHECKED and never as OK. A check
that raises becomes its own `check_failed` finding, exactly as `alerts.scan`
does. "Could not check" rendered as "fine" is the mistake the whole sweep
exists to end.

Nothing here formats a secret: every detail line is built from names, counts,
versions and timestamps.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import db

log = logging.getLogger("ccsync.dashboard.invariants")

# How recently two rows must BOTH have reported for a shared machine_id to be
# the disk-clone signature rather than a rename this server has not tidied up
# (invariant 3). One interval of the checker's own cadence, so "within one
# interval" means what SYS-9 says it means; floored at 15 min so a site that
# tuned DASH_INTERVAL_INVARIANTS down does not lose the signal.
CLONE_WINDOW_SECONDS = 15 * 60

# Feature floors (SYS-13 / invariant 7). A companion below one of these does
# not refuse the feature, it is simply DEAF to it: `commands.upgrade` and
# auto-update landed in 0.9.3, so [ UPDATE NOW ] on an older machine is a
# button that does nothing at all and says nothing (leso's Mac sat on 0.9.2
# for ten days that way); [ RESUME ] for a tripped lane B breaker landed in
# 0.9.43; an upload-only tick needs 0.9.54 or the machine runs lane B for it
# too, which is the one thing upload-only exists to prevent.
FLOOR_COMMANDS = "0.9.3"
FLOOR_RESUME = "0.9.43"
FLOOR_UPLOAD_ONLY = "0.9.54"

# Per invariant: how many broken subjects are worth naming before the count
# says more than the list. Mirrors alerts.MAX_FINDINGS_PER_KIND's reasoning.
MAX_SUBJECTS = db.INVARIANT_MAX_SUBJECTS

# The proxy convention (`<dir>/Proxy/<stem>.mov|.mp4` beside
# `<dir>/<stem>.<ext>`), keyed on the STEM exactly as proxy_scan.py keys it.
PROXY_DIR = "proxy"


# ------------------------------------------------------------- the outcome

OK = db.INVARIANT_OK
BROKEN = db.INVARIANT_BROKEN
NOT_CHECKED = db.INVARIANT_NOT_CHECKED
CHECK_FAILED = db.INVARIANT_CHECK_FAILED


@dataclass
class Outcome:
    """One invariant's verdict this pass.

    `detail` is the technical line, always present: on an `ok` it is the
    evidence ("34 full ticks, all shared"), which is what makes a green row
    mean something. `subjects` is [(subject, detail)] and is only read for a
    broken verdict.
    """
    state: str
    detail: str = ""
    subjects: list[tuple[str, str]] = field(default_factory=list)


def ok(detail: str = "") -> Outcome:
    return Outcome(OK, detail)


def broken(subjects: Iterable[tuple[str, str]], detail: str = "") -> Outcome:
    rows = list(subjects)
    return Outcome(BROKEN, detail or f"{len(rows)} subject(s)", rows[:MAX_SUBJECTS])


def not_checked(reason: str) -> Outcome:
    """The honest answer. `reason` is shown on the page beside NOT CHECKED, so
    it must say what would have to be true for the check to run."""
    return Outcome(NOT_CHECKED, reason)


class Ctx:
    """What the checks read, gathered once per pass.

    Deliberately thin: unlike `alerts.Ctx` this does NOT build the fleet view
    (a full editors view per invariant pass, on the collector's single
    thread, to answer questions that are all table reads). Anything expensive
    or fallible is lazy and cached, and anything that could not be read is
    None -- which the checks turn into NOT CHECKED rather than into silence.
    """

    def __init__(self, conn: sqlite3.Connection, settings: Any, now: str,
                 folder_devices: dict[str, list[str]] | None = None,
                 snapshot_tasks_fn: Callable[[], list[dict[str, Any]] | None] | None = None):
        self.conn = conn
        self.settings = settings
        self.now = now
        # The config cycle's cache (slug -> shared device ids). None means it
        # has not completed a pass in THIS process, which is not evidence
        # that every plan is satisfied -- the same rule
        # notices._check_plan_without_share follows.
        self.folder_devices = folder_devices
        self._snapshot_tasks_fn = snapshot_tasks_fn
        self._machines: list[dict[str, Any]] | None = None
        self._modes: dict[tuple[str, str], str] | None = None

    # -- shared reads -------------------------------------------------------

    def machines(self) -> list[dict[str, Any]]:
        if self._machines is None:
            self._machines = db.fetch_machines(self.conn)
        return self._machines

    def modes(self) -> dict[tuple[str, str], str]:
        if self._modes is None:
            self._modes = db.machine_modes(self.conn)
        return self._modes

    def projects_dir(self) -> Path | None:
        """The tree as THIS container sees it, or None when there is none.

        A dashboard with no DASH_PROJECTS_DIR is a supported deployment
        (provisioning off), so its absence is "not checked", never a fault.
        """
        raw = str(getattr(self.settings, "projects_dir", "") or "").strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_dir() else None

    def snapshot_tasks(self) -> list[dict[str, Any]] | None:
        """The NAS's periodic snapshot tasks, or None when it cannot be asked.

        Injectable (`snapshot_tasks_fn`) because the alternative is a suite
        that either talks to a real NAS or never exercises invariant 9 at
        all. One bounded call per pass, on the slowest cadence in the
        collector.
        """
        if self._snapshot_tasks_fn is not None:
            return self._snapshot_tasks_fn()
        kind = str(getattr(self.settings, "nas_kind", "") or "truenas").strip().lower()
        if kind != "truenas":
            return None
        try:
            from .nas.factory import make_nas_client, nas_configured

            if not nas_configured(self.settings):
                return None
            client = make_nas_client(self.settings)
            resp = client.get("/pool/snapshottask")
            if not (200 <= getattr(resp, "status_code", 500) < 300):
                return None
            payload = resp.json()
            return list(payload) if isinstance(payload, list) else None
        except Exception:                                            # noqa: BLE001
            # A NAS that cannot be asked is NOT a NAS with no snapshots.
            log.debug("invariants: could not read the NAS snapshot tasks", exc_info=True)
            return None


# ------------------------------------------------------------- the registry

@dataclass(frozen=True)
class Invariant:
    """One fact that must stay true, and what it costs when it stops.

    `consequence` is the sentence a non-technical owner reads: what goes
    wrong in the world, not what is wrong in the database. `fix` is the exact
    next action, on the same rule every notice follows. `severity` decides
    how loudly a break is filed (`error` reaches the alert sink through
    `notice_error`; `warn` does not), not just the colour.

    `skip_reason`, when set, means the invariant is REGISTERED AND
    DELIBERATELY NOT EVALUATED: it renders NOT CHECKED with that sentence.
    A registered invariant with no honest way to evaluate it is better than
    an absent one -- it is the only way an owner can see that the fact is
    unchecked rather than fine.
    """
    key: str
    number: int                   # SYS-9's own numbering, kept for the ledger
    title: str
    consequence: str
    fix: str
    check: Callable[[Ctx], Outcome] | None = None
    severity: str = "error"
    skip_reason: str = ""


# --------------------------------------------------------------- the checks

def _check_plan_has_share(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 1: a full tick means a Syncthing share to that
    computer's device.

    The direct form is already a notice (`plan_without_share`); this is the
    same fact as a standing invariant, so the page can say "checked, all 34
    ticks are shared" rather than only ever speaking up when it is wrong.
    """
    if ctx.folder_devices is None:
        return not_checked(
            "the server has not read its sync engine's folder list yet in this "
            "session, so it cannot say which computers a project is shared with")
    by_slug = db.fetch_machine_selections(ctx.conn, sync_modes=(db.SYNC_MODE_FULL,))
    device_by_machine: dict[tuple[str, str], str] = {}
    for row in ctx.machines():
        device = row.get("syncthing_device_id")
        if device:
            device_by_machine[(row["editor_username"], row["machine"])] = str(device)
    bad: list[tuple[str, str]] = []
    checked = 0
    unknown = 0
    for slug, pairs in by_slug.items():
        shared = set(ctx.folder_devices.get(slug) or [])
        for editor, machine in pairs:
            if machine == db.ANY_MACHINE:
                # The unassigned bucket: no computer, so no device id, so no
                # share to compare against.
                continue
            device = device_by_machine.get((editor, machine))
            if not device:
                unknown += 1
                continue
            checked += 1
            if device not in shared:
                bad.append((f"{editor}/{machine} -> {slug}",
                            "ticked to sync, not shared with that computer"))
    if bad:
        return broken(bad, f"{len(bad)} of {checked} full tick(s) are not shared")
    if not checked:
        return not_checked("no full ticks with a known computer to check")
    suffix = f"; {unknown} tick(s) on computers with no device id yet" if unknown else ""
    return ok(f"{checked} full tick(s), all shared{suffix}")


def _check_machine_has_plan(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 2: a computer that reports has something to sync.

    A base rig holds no tick by design (CR-28) and the unassigned bucket is a
    real plan, so both count as satisfied. What is left is a computer that
    reports every minute, appears on the grid, and is syncing nothing at all
    because nobody ever ticked anything for it.
    """
    machines = ctx.machines()
    if not machines:
        return not_checked("no computer has reported to this server yet")
    modes = ctx.modes()
    by_slug = db.fetch_machine_selections(ctx.conn)
    planned: set[tuple[str, str]] = set()
    for pairs in by_slug.values():
        planned.update(pairs)
    bad: list[tuple[str, str]] = []
    for row in machines:
        key = (row["editor_username"], row["machine"])
        if modes.get(key) == "base":
            continue
        if key in planned:
            continue
        bad.append((f"{key[0]}/{key[1]}",
                    "no project ticked for this computer and it is not a base rig"))
    if bad:
        return broken(bad, f"{len(bad)} of {len(machines)} computer(s) have no plan")
    return ok(f"{len(machines)} computer(s), each with a plan or a base-rig role")


def _check_one_identity_per_computer(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 3, including THE DISK-CLONE SIGNATURE.

    Two rows sharing a `machine_id` can be innocent history (a computer
    renamed, the old row not yet aged out). Two rows sharing a `machine_id`
    that have BOTH reported within one interval cannot: that is two live PCs
    off one disk image, and `adopt_renamed_machine` then ping-pongs the plan
    and the Syncthing device between them on every report, restarting the
    affected folders every enforce cycle (DASH-11 / APP-10).

    The SAME-EDITOR clone used to be invisible here (SYS-18a, fixed
    2026-08-29). `api._register_machine` read the second hostname as a rename
    and `db.adopt_renamed_machine` deleted the other row, so one editor's two
    clones never left a second row to group. The adoption path now refuses
    while the previous row is fresh (api.CLONE_ADOPTION_WINDOW_SECONDS), both
    rows survive, and that pair arrives here and at
    `notices._check_identity_collisions` exactly as the two-editor case
    always did. Nothing in this check changed; what changed is that the rows
    it needs now exist.

    The Syncthing device id half is the same fact one level down: one device
    id on two rows means only one of the two computers can actually receive
    anything, and which one is not this server's choice.
    """
    machines = ctx.machines()
    if not machines:
        return not_checked("no computer has reported to this server yet")
    by_machine_id: dict[str, list[dict[str, Any]]] = {}
    by_device: dict[str, list[dict[str, Any]]] = {}
    for row in machines:
        machine_id = str(row.get("machine_id") or "").strip()
        if machine_id:
            by_machine_id.setdefault(machine_id, []).append(row)
        device = str(row.get("syncthing_device_id") or "").strip()
        if device:
            by_device.setdefault(device, []).append(row)
    bad: list[tuple[str, str]] = []
    for machine_id, rows in sorted(by_machine_id.items()):
        if len(rows) < 2:
            continue
        who = ", ".join(f"{r['editor_username']}/{r['machine']}" for r in rows)
        live = [r for r in rows if _seen_within(r.get("last_seen"), ctx.now,
                                                CLONE_WINDOW_SECONDS)]
        if len(live) >= 2:
            bad.append((machine_id,
                        f"{who}: both reported within "
                        f"{CLONE_WINDOW_SECONDS // 60} minutes, so a copied disk is "
                        f"in use on two computers at once"))
        else:
            bad.append((machine_id, f"{who}: two computers on one identity"))
    for device, rows in sorted(by_device.items()):
        if len(rows) < 2:
            continue
        who = ", ".join(f"{r['editor_username']}/{r['machine']}" for r in rows)
        bad.append((device, f"{who}: one place on the sync network claimed twice"))
    if bad:
        return broken(bad, f"{len(bad)} identity collision(s)")
    return ok(f"{len(by_machine_id)} computer identity/identities and "
              f"{len(by_device)} sync device id(s), each on one computer")


def _check_project_markers(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 4: an active project's `.ccsync-project` marker is
    there and still says what the row says.

    A directory that has gone MISSING is not counted here: that is the
    deactivation grace's business one function up, and a project being
    renamed on the NAS while this pass runs would otherwise read as a fault
    every fifteen minutes. What is counted is a directory that is there and
    has lost, or disagrees with, its identity -- which is the state in which
    the collector stops recognising the project and every editor's tick for
    it quietly stops meaning anything.
    """
    from . import provision

    root = ctx.projects_dir()
    if root is None:
        return not_checked("this dashboard has no project tree mounted "
                           "(DASH_PROJECTS_DIR), so it cannot look at the markers")
    prefix = str(getattr(ctx.settings, "syncthing_data_prefix", "") or "").rstrip("/")
    rows = list(ctx.conn.execute(
        "SELECT slug, path FROM projects WHERE active=1 ORDER BY slug"))
    bad: list[tuple[str, str]] = []
    checked = 0
    skipped = 0
    for row in rows:
        path = str(row["path"] or "")
        if not prefix or not path.startswith(prefix + "/"):
            skipped += 1
            continue
        rel = path[len(prefix) + 1:].strip("/")
        directory = root / Path(*[p for p in rel.split("/") if p])
        if not directory.is_dir():
            skipped += 1
            continue
        checked += 1
        try:
            marker = provision.read_marker(directory)
        except Exception:                                            # noqa: BLE001
            marker = None
        if marker is None:
            bad.append((str(row["slug"]),
                        f"{rel}: the folder is there and its CCSync marker is not"))
        elif marker != row["slug"]:
            bad.append((str(row["slug"]),
                        f"{rel}: the marker says {marker!r}, this server says "
                        f"{row['slug']!r}"))
    if bad:
        return broken(bad, f"{len(bad)} of {checked} project folder(s) disagree")
    if not checked:
        return not_checked("no active project folder could be located under the "
                           "tree this container can see")
    suffix = f"; {skipped} not visible from this container" if skipped else ""
    return ok(f"{checked} project marker(s) present and matching{suffix}")


def _check_tree_markers(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 5: the tree root still looks like the tree.

    The companion asks this of `remote_root` once per process
    (`sequencer._check_remote_root`, sync-safety-5) because a root pointing
    at a stale copy -- a backup dataset, a snapshot clone mounted for a
    restore drill -- passes every per-project probe and then trashes every
    proxy newer than the copy. The SERVER never asked it of the tree it
    serves, which is the same tree.
    """
    root = ctx.projects_dir()
    if root is None:
        return not_checked("this dashboard has no project tree mounted "
                           "(DASH_PROJECTS_DIR), so it has no tree to look at")
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        return not_checked(f"the project tree could not be read: {type(exc).__name__}")
    if not entries:
        return broken(
            [(str(root), "the project tree is readable and completely empty, which "
                         "normally means the storage is not mounted")],
            "the tree is empty")
    marked = 0
    try:
        from . import provision

        for entry in entries:
            if entry.is_dir() and (entry / provision.MARKER_FILENAME).exists():
                marked += 1
    except OSError:
        marked = 0
    return ok(f"the tree holds {len(entries)} entr(ies) at the top level "
              f"({marked} of them a project in their own right)")


def _check_package_floor(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 6: the published floor is a floor, not a brick.

    CR-52: a package whose `min_version` is ABOVE the build it describes
    bricks the upgrade channel for every machine that accepts it -- the
    machine writes the floor, then refuses the only build on offer, for
    ever. The publish path refuses one; nothing ever re-asked, and a record
    can also arrive from a restored backup or an older build's publish.

    The second half is the floor-drop rule: a current package whose floor is
    below one this channel has already published means a machine that took
    the earlier floor will not accept this build either.
    """
    rows = list(db.fetch_companion_packages(ctx.conn))
    if not rows:
        return not_checked("no build has been published to this dashboard yet")
    highest_floor: dict[tuple[str, str], tuple[tuple[int, ...], str]] = {}
    for row in rows:
        key = (str(row["kind"]), str(row["platform"]))
        floor = db.version_tuple(row["min_version"])
        if floor and floor > highest_floor.get(key, ((), ""))[0]:
            highest_floor[key] = (floor, str(row["min_version"]))
    bad: list[tuple[str, str]] = []
    checked = 0
    for row in rows:
        if not row["is_current"]:
            continue
        checked += 1
        key = (str(row["kind"]), str(row["platform"]))
        subject = f"{key[0]}/{key[1]} {row['version']}"
        version = db.version_tuple(row["version"])
        floor = db.version_tuple(row["min_version"])
        if floor and version and floor > version:
            bad.append((subject,
                        f"its floor {row['min_version']} is above the build itself, so a "
                        f"computer that accepts it can never install anything again"))
            continue
        top = highest_floor.get(key)
        if floor and top and floor < top[0]:
            bad.append((subject,
                        f"its floor {row['min_version']} is below {top[1]}, which this "
                        f"channel has already published, so machines holding the higher "
                        f"floor will refuse it"))
    if bad:
        return broken(bad, f"{len(bad)} of {checked} current build(s) carry a bad floor")
    if not checked:
        return not_checked("no build on this dashboard is marked current")
    return ok(f"{checked} current build(s), each with a workable floor")


def _check_companion_floor(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 7: a computer runs a build new enough for its plan.

    A machine below the floor does not refuse the feature, it is DEAF to it:
    below 0.9.3 the [ UPDATE NOW ] push and auto-update do not exist, so the
    button is silent; below 0.9.43 an admin's [ RESUME ] never reaches a
    tripped lane B breaker; below 0.9.54 an upload-only tick still runs lane
    B, which is the one behaviour upload-only exists to prevent.
    """
    machines = ctx.machines()
    if not machines:
        return not_checked("no computer has reported to this server yet")
    versions: dict[tuple[str, str], str] = {}
    for row in ctx.conn.execute(
        "SELECT editor_username, machine, companion_version FROM machine_state"
    ):
        if row["companion_version"]:
            versions[(row["editor_username"], row["machine"])] = str(row["companion_version"])
    upload_only: set[tuple[str, str]] = set()
    for slug, pairs in db.fetch_machine_selections(
            ctx.conn, sync_modes=(db.SYNC_MODE_UPLOAD_ONLY,)).items():
        upload_only.update(pairs)
    bad: list[tuple[str, str]] = []
    checked = 0
    unknown = 0
    for row in machines:
        key = (row["editor_username"], row["machine"])
        running = versions.get(key)
        if not running:
            unknown += 1
            continue
        checked += 1
        needed = FLOOR_UPLOAD_ONLY if key in upload_only else FLOOR_RESUME
        reason = ("it holds an upload-only tick, which needs "
                  f"{FLOOR_UPLOAD_ONLY} or it will download that project too"
                  if key in upload_only else
                  f"the fleet's [ RESUME ] and [ UPDATE NOW ] buttons need {FLOOR_RESUME}")
        if db.version_tuple(running) and db.version_tuple(running) < db.version_tuple(needed):
            bad.append((f"{key[0]}/{key[1]}", f"running {running}: {reason}"))
    if bad:
        return broken(bad, f"{len(bad)} of {checked} computer(s) are below their floor")
    if not checked:
        return not_checked("no computer has reported which CC Sync build it is running")
    suffix = f"; {unknown} computer(s) have not said which build they run" if unknown else ""
    return ok(f"{checked} computer(s) new enough for their plan{suffix}")


def _check_snapshot_schedule(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 9 (SYS-14's standing red line): the customer's data is
    on a snapshot schedule.

    Every documented restore path in this product starts "find the snapshot".
    The live TrueNAS's `apps` dataset has never had a snapshot task at all
    (CR-10) and every page renders green about it. This does not go looking
    for the dataset the tree is on -- a container sees `/data`, not the pool
    path (`dashboard_update.snapshot_before` says so) -- so it asks the
    narrower question it can answer honestly: does this NAS have any enabled
    periodic snapshot task, and does it cover the dataset the deployment
    named, if it named one.
    """
    tasks = ctx.snapshot_tasks()
    if tasks is None:
        return not_checked("this server cannot ask the NAS about its snapshot "
                           "schedule (no NAS API key, or the NAS did not answer)")
    enabled = [t for t in tasks if isinstance(t, dict) and t.get("enabled", True)]
    if not enabled:
        return broken(
            [("this NAS", "no snapshot task is enabled, so there is nothing to "
                          "restore from if footage is deleted or a disk fails")],
            f"{len(tasks)} snapshot task(s), none enabled")
    import os

    named = (os.environ.get("DASH_UPDATE_SNAPSHOT_DATASET") or "").strip()
    if named:
        covered = any(
            str(t.get("dataset") or "") == named
            or (t.get("recursive") and named.startswith(str(t.get("dataset") or "") + "/"))
            for t in enabled)
        if not covered:
            return broken(
                [(named, "no enabled snapshot task covers this dataset, so the "
                         "dashboard's own data has nothing to restore from")],
                f"{len(enabled)} enabled task(s), none covering {named}")
    return ok(f"{len(enabled)} enabled snapshot task(s) on this NAS")


def _check_proxy_pairs(ctx: Ctx) -> Outcome:
    """SYS-9 invariant 10: a proxy has the original it was made from.

    `<dir>/Proxy/<stem>.mov|.mp4` beside `<dir>/<stem>.<ext>` is the
    convention every part of this system keys on. A proxy whose original is
    gone is the cheapest detector of a half-completed reorganisation on the
    NAS: somebody moved the footage and left the Proxy folders behind, and
    every editor now downloads proxies for clips that do not exist.

    Only that direction is checked. An original with no proxy is the NORMAL
    state of freshly uploaded footage, so treating it as a broken invariant
    would make this check cry wolf on every shoot day.
    """
    projects = list(ctx.conn.execute(
        "SELECT id, slug FROM projects WHERE active=1 ORDER BY slug"))
    if not projects:
        return not_checked("no active project to look at")
    bad: list[tuple[str, str]] = []
    checked = 0
    walked = 0
    for project in projects:
        rows = list(ctx.conn.execute(
            "SELECT rel_path, kind FROM nas_media WHERE project_id=?", (project["id"],)))
        if not rows:
            continue
        walked += 1
        originals: set[tuple[str, str]] = set()
        proxies: list[str] = []
        for row in rows:
            rel = str(row["rel_path"] or "")
            parts = rel.split("/")
            stem = parts[-1].rsplit(".", 1)[0] if parts else ""
            if row["kind"] == "proxy":
                proxies.append(rel)
            else:
                originals.add(("/".join(parts[:-1]), stem))
        for rel in proxies:
            parts = rel.split("/")
            if len(parts) < 2 or parts[-2].lower() != PROXY_DIR:
                # A proxy somewhere other than a Proxy/ dir directly beside
                # its original: the convention does not say where its
                # original should be, so this check has nothing to compare.
                continue
            checked += 1
            stem = parts[-1].rsplit(".", 1)[0]
            if ("/".join(parts[:-2]), stem) not in originals:
                bad.append((f"{project['slug']}/{rel}",
                            "this proxy has no original beside it on the server"))
    if bad:
        return broken(bad, f"{len(bad)} of {checked} proxy file(s) have no original")
    if not walked:
        return not_checked("the server has not walked any project's files yet")
    return ok(f"{checked} proxy file(s) across {walked} project(s), each with its original")


def _seen_within(ts: Any, now: str, seconds: float) -> bool:
    """True when `ts` is a timestamp this recent. An unparseable one is NOT
    recent: the clone signature must be evidence of two live machines, and
    "cannot tell" is not evidence."""
    try:
        return 0 <= db.age_seconds(str(ts or ""), now) <= seconds
    except (TypeError, ValueError):
        return False


# The registry. Ordered by SYS-9's own numbering so the finding and the page
# read against each other; the order has no other meaning.
INVARIANTS: tuple[Invariant, ...] = (
    Invariant(
        "plan_has_share", 1,
        "every project ticked to sync is actually shared with that computer",
        "A computer whose tick was never turned into a share receives nothing at "
        "all, and the tick looks exactly like it is working.",
        "Untick and re-tick that project for that computer on its project page. "
        "If it comes back, check that computer has a sync device id on the FLEET page.",
        _check_plan_has_share),
    Invariant(
        "machine_has_plan", 2,
        "every computer that reports has something to sync",
        "A computer with no projects ticked for it sits on the fleet page looking "
        "healthy and syncs nothing at all.",
        "Tick at least one project for that computer on the FLEET page, or set it "
        "to base rig in its own CC Sync settings if it works straight off the server.",
        _check_machine_has_plan, severity="warn"),
    Invariant(
        "one_identity_per_computer", 3,
        "no two computers claim one identity",
        "Two computers sharing an identity fight over one sync plan: each report "
        "moves the plan and the sync network place to whichever reported last, so "
        "both of them keep losing projects.",
        "On the newer computer, quit CC Sync, delete .ccsync/machine.json in that "
        "user's home folder, and start CC Sync again. It mints a fresh identity.",
        _check_one_identity_per_computer),
    Invariant(
        "project_markers", 4,
        "every project folder still carries its own identity file",
        "A project folder that has lost or changed its CCSync marker stops being "
        "that project to this server: everyone's ticks for it quietly stop meaning "
        "anything and it can be set up a second time under a new name.",
        "Restore the .ccsync-project file in that folder on the server (copy a "
        "working one and correct its id), or set the project up again from "
        "Settings, Projects.",
        _check_project_markers),
    Invariant(
        "tree_markers", 5,
        "the project tree on the server still looks like the tree",
        "If the storage is not mounted, the tree reads as empty: projects look "
        "deleted, and the computers that still hold the footage are told the "
        "server does not have it.",
        "Check the storage is mounted on the NAS and that the CC Sync container "
        "still has the projects folder mapped in, then reload this page.",
        _check_tree_markers),
    Invariant(
        "package_floor", 6,
        "no published build carries a floor that would brick the computers taking it",
        "A build whose minimum version is above itself makes every computer that "
        "installs it refuse every future update, permanently, with no way back "
        "over the air.",
        "On Settings, Packages: retract that build and publish one whose minimum "
        "version is at or below its own version number.",
        _check_package_floor),
    Invariant(
        "companion_floor", 7,
        "every computer runs a build new enough for the plan it has been given",
        "A computer running too old a build ignores the buttons on this dashboard "
        "in silence: the update push does nothing, [ RESUME ] never arrives, and an "
        "upload-only project is downloaded anyway.",
        "On Settings, Packages: press [ UPDATE NOW ] for that computer. If it is "
        "below 0.9.3 that button cannot reach it, and somebody has to update it at "
        "the computer itself.",
        _check_companion_floor),
    Invariant(
        "versioning_agrees", 8,
        "deleted-file retention agrees between the server and the editors",
        "The server keeps deleted files for a year and editors' computers keep them "
        "for a month, so where a deleted file can be recovered from depends on which "
        "machine you ask (R5).",
        "Nothing to press. This one is a code change, tracked as R5 in KNOWN_BUGS.",
        None, severity="warn",
        skip_reason=(
            "the editor-side retention number lives in the companion build itself "
            "and no computer reports it, so this server can see only one of the two "
            "values it would have to compare")),
    Invariant(
        "snapshot_schedule", 9,
        "the customer's data is on a snapshot schedule",
        "Without a snapshot schedule there is nothing to restore from: a deleted "
        "folder, a bad sync or a failed disk is simply gone.",
        "On the NAS: Data Protection, Periodic Snapshot Tasks, add a task for the "
        "dataset the project tree lives on and enable it.",
        _check_snapshot_schedule),
    Invariant(
        "proxy_pairs", 10,
        "every proxy on the server has the original it was made from",
        "Proxies left behind by a half-finished reorganisation are downloaded by "
        "every editor for clips that no longer exist, and the project looks fuller "
        "than it is.",
        "On the server, look at the folder named below: either put the original "
        "footage back beside it or delete the leftover Proxy folder.",
        _check_proxy_pairs, severity="warn"),
)

BY_KEY: dict[str, Invariant] = {inv.key: inv for inv in INVARIANTS}


# ------------------------------------------------------------------ the pass

def evaluate(ctx: Ctx) -> list[dict[str, Any]]:
    """Run every invariant. NEVER RAISES: an invariant that raises becomes its
    own `check_failed` result, exactly as `alerts.scan` does, because a check
    that could not run must never read as a check that found nothing."""
    results: list[dict[str, Any]] = []
    for inv in INVARIANTS:
        if inv.skip_reason or inv.check is None:
            outcome = not_checked(inv.skip_reason or
                                  "no check is wired for this invariant yet")
        else:
            try:
                outcome = inv.check(ctx)
            except Exception as exc:                                 # noqa: BLE001
                log.exception("invariant %s could not run", inv.key)
                outcome = Outcome(
                    CHECK_FAILED,
                    f"{type(exc).__name__}: {str(exc)[:200]}")
        results.append({
            "key": inv.key, "number": inv.number, "title": inv.title,
            "consequence": inv.consequence, "fix": inv.fix,
            "severity": inv.severity, "state": outcome.state,
            "detail": outcome.detail, "subjects": list(outcome.subjects),
        })
    return results


def run_cycle(
    conn: sqlite3.Connection, settings: Any, now: str,
    folder_devices: dict[str, list[str]] | None = None,
    snapshot_tasks_fn: Callable[[], list[dict[str, Any]] | None] | None = None,
) -> dict[str, Any]:
    """One invariant pass: evaluate, record, and file what broke.

    Returns {"results", "note"}; the note is what the collector health panel
    shows, so a pass that found something is not indistinguishable from a
    clean one. Writing the ledger is best-effort per invariant: a database
    error on one row must not lose the other nine verdicts.
    """
    ctx = Ctx(conn, settings, now, folder_devices=folder_devices,
              snapshot_tasks_fn=snapshot_tasks_fn)
    results = evaluate(ctx)
    # bug-hunt-2026-09-03 dash-collector-2: what the ledger held BEFORE this
    # pass, so an invariant whose check could not run keeps its open notices.
    # `db.record_invariant_result` no longer deletes those subject rows on a
    # non-verdict, but the keep-list below is the other half: without it
    # `clear_notices_of_kind` would still close the notice on the very next
    # pass, and the fleet would be mailed "this has cleared" about a subject
    # nothing has looked at.
    stored_broken: dict[str, list[str]] = {}
    for row in db.broken_invariants(conn):
        stored_broken.setdefault(str(row["invariant"]), []).append(str(row["subject"]))
    broken_subjects: list[str] = []
    failed_subjects: list[str] = []
    for result in results:
        try:
            db.record_invariant_result(
                conn, result["key"], result["state"], result["detail"],
                subjects=result["subjects"], now=now)
        except sqlite3.Error:
            log.exception("invariants: could not record %s", result["key"])
        inv = BY_KEY[result["key"]]
        if result["state"] == db.INVARIANT_BROKEN:
            for subject, detail in result["subjects"]:
                key = f"{inv.key}: {subject}"
                broken_subjects.append(key)
                db.notice(
                    conn, "invariant_broken", inv.severity, key,
                    body=(f"{inv.consequence} This server checks that "
                          f"{inv.title}, and right now it is not true: {detail}."),
                    fix=inv.fix, now=now)
        elif result["state"] not in (db.INVARIANT_OK, db.INVARIANT_BROKEN):
            # A pass that did not reach a verdict (check_failed, or a check
            # that answered not_checked) has said NOTHING about the subjects
            # this invariant was already failing on. They stay open, with
            # their old checked_at.
            for subject in stored_broken.get(inv.key, ()):
                broken_subjects.append(f"{inv.key}: {subject}")
        if result["state"] == db.INVARIANT_CHECK_FAILED:
            failed_subjects.append(inv.key)
            db.notice(
                conn, "invariant_check_failed", "error", inv.key,
                body=(f"The check for '{inv.title}' could not run, so this server "
                      f"does not know whether that is all right. Treat it as "
                      f"unchecked, not as fine."),
                fix="Send us the container log from the NAS.", now=now)
    db.clear_notices_of_kind(conn, "invariant_broken", broken_subjects, now=now)
    db.clear_notices_of_kind(conn, "invariant_check_failed", failed_subjects, now=now)
    conn.commit()
    counts = _counts(results)
    return {"results": results, "note": _note(counts), "counts": counts}


def _counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in db.INVARIANT_STATES}
    for result in results:
        counts[result["state"]] = counts.get(result["state"], 0) + 1
    return counts


def _note(counts: dict[str, int]) -> str | None:
    """The collector health panel's line. None on a wholly clean pass: a
    panel that always carries text stops being read."""
    parts = []
    if counts.get(db.INVARIANT_BROKEN):
        parts.append(f"{counts[db.INVARIANT_BROKEN]} invariant(s) broken")
    if counts.get(db.INVARIANT_CHECK_FAILED):
        parts.append(f"{counts[db.INVARIANT_CHECK_FAILED]} check(s) could not run")
    if counts.get(db.INVARIANT_NOT_CHECKED):
        parts.append(f"{counts[db.INVARIANT_NOT_CHECKED]} not checked here")
    return "; ".join(parts) if parts else None


def page_view(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every invariant with its last verdict, for the admin page.

    THE REGISTRY IS THE SPINE, not the table: an invariant with no row at all
    (a fresh boot, a kind added by a build that has not run a pass yet)
    renders NOT CHECKED rather than being absent from the page, which is the
    same rule the notices panel's [ NOT CHECKED ] follows.
    """
    stored = db.fetch_invariant_results(conn)
    view: list[dict[str, Any]] = []
    for inv in INVARIANTS:
        row = stored.get(inv.key) or {}
        state = str(row.get("state") or db.INVARIANT_NOT_CHECKED)
        detail = str(row.get("detail") or "")
        if not row and inv.skip_reason:
            detail = inv.skip_reason
        view.append({
            "key": inv.key, "number": inv.number, "title": inv.title,
            "consequence": inv.consequence, "fix": inv.fix,
            "severity": inv.severity, "state": state, "detail": detail,
            "checked_at": str(row.get("checked_at") or ""),
            "subjects": list(row.get("subjects") or []),
        })
    return view
