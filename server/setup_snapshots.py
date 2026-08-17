#!/usr/bin/env python3
"""Put a backup floor under the NAS: periodic snapshots of the tree and the app.

    python setup_snapshots.py                 # dry-run: say what would change
    python setup_snapshots.py --apply         # actually create/update the tasks
    python setup_snapshots.py --list          # what snapshots exist right now

Until 2026-08-17 this repo had zero references to snapshots, replication or
restore (docs/COMMERCIAL_READINESS.md item 8). Every recovery path was a
rename-aside, a `.ccsync-trash` or Syncthing versioning -- all of which are
downstream of the thing most likely to destroy a customer's footage: a
privileged recursive command, a deploy, or a fleet-side bug operating on the
wrong path. None of those are recoverable without a point-in-time.

Two datasets, because there are two kinds of loss:

  the TREE   the authoritative project tree ([tree] pool_root in site.toml).
             Losing this is losing the customer's footage. Hourly.
  the APP    the dashboard's host tree ([apps] root): dashboard.db (which IS
             the fleet's provisioning state -- projects, editors, ticks),
             music.db, broll.db. Losing this is losing who is allowed to sync
             what. Hourly, same policy: it is kilobytes of change per hour.

Retention is deliberately short and cheap: 24 hourly + 30 daily. ZFS and Btrfs
snapshots cost only the blocks that CHANGED, and this is a floor, not an
archive -- it buys back the last day at fine grain and the last month at daily
grain. Offsite replication is a separate decision (see docs/BACKUP_RESTORE.md).

DRY-RUN IS THE DEFAULT. Nothing is created without --apply.

Platforms:
  TrueNAS   REST /pool/snapshottask, idempotent by (dataset, naming schema).
  Synology  DSM can TAKE a share snapshot from here, but SCHEDULING one needs
            the Snapshot Replication package; where it is absent this script
            prints the exact DSM click path and exits non-zero, so an operator
            never mistakes "printed some advice" for "backups are configured".

Env vars: TRUENAS_HOST / TRUENAS_USER / TRUENAS_PW (see server/README.md).
"""
import argparse
import sys

from common import (
    DEFAULT_APPS_ROOT,
    DEFAULT_DATASET_ROOT,
    add_host_key_arg,
    add_nas_kind_arg,
    add_site_arg,
    cli,
    get_backend,
    require_site_value,
    set_host_key_pin,
)

# The snapshot names an operator reads at 3am. `ccsync-` prefixed so a human
# scanning `zfs list -t snapshot` can tell ours from the box's own tasks, and
# from the replication package's GMT+NN- ones on DSM.
HOURLY_SCHEMA = "ccsync-%Y%m%d-%H%M"
DAILY_SCHEMA = "ccsync-daily-%Y%m%d"

# The policy. Cadence and retention live HERE, not in a backend: what a
# platform knows is how to install a schedule, not how often a video studio
# wants one (backends/base.py ensure_snapshot_schedule).
#
# Hourly on the hour; daily at 03:10, which is after the fleet's overnight
# rclone lanes have gone quiet and before anyone starts editing.
def schedules(hourly_keep: int, daily_keep: int) -> list[dict]:
    return [
        {
            "label": "hourly",
            "naming_schema": HOURLY_SCHEMA,
            "schedule": {"minute": "0", "hour": "*", "dom": "*",
                         "month": "*", "dow": "*"},
            "lifetime_value": int(hourly_keep),
            "lifetime_unit": "HOUR",
            # Recursive: a dataset that gains a CHILD later (a per-customer or
            # per-project dataset) must not silently fall outside the backup
            # floor, and a non-recursive task is exactly how that happens.
            "recursive": True,
        },
        {
            "label": "daily",
            "naming_schema": DAILY_SCHEMA,
            "schedule": {"minute": "10", "hour": "3", "dom": "*",
                         "month": "*", "dow": "*"},
            "lifetime_value": int(daily_keep),
            "lifetime_unit": "DAY",
            "recursive": True,
        },
    ]


def targets(args) -> list[tuple[str, str]]:
    """[(what it is, path)] -- the two datasets that must have a floor.

    The tree is required: a site that cannot name the tree it is about to
    protect gets require_site_value's refusal, exactly as setup_tree.py does
    before it chowns one. The apps root is optional only in the sense that a
    site may not have deployed the dashboard yet.
    """
    tree = require_site_value(args.tree_root or DEFAULT_DATASET_ROOT,
                              "[tree] pool_root", "--tree-root")
    out = [("tree", tree)]
    apps = (args.apps_root or DEFAULT_APPS_ROOT or "").strip()
    if apps:
        out.append(("app", apps))
    else:
        print("NOTE: no [apps] root in site.toml -- only the tree will be "
              "scheduled. The dashboard's dashboard.db (the fleet's projects, "
              "editors and ticks) then has no snapshot behind it.",
              file=sys.stderr)
    return out


def report_existing(backend, label: str, path: str, dry_run: bool) -> None:
    """What is already there. Printed before any change, because "there were
    already 700 snapshots" and "there were none" are different situations and
    only one of them is an emergency."""
    rows = backend.list_snapshots(path, dry_run)
    if dry_run:
        return
    if not rows:
        print(f"  {label}: NO snapshots found on {path} -- this dataset has no "
              f"point-in-time behind it today.")
        return
    newest = rows[-1]
    print(f"  {label}: {len(rows)} snapshot(s) on {path}; newest "
          f"{newest.get('name')} ({newest.get('created')})")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree-root", default="",
                    help="path of the tree dataset; default [tree] pool_root")
    ap.add_argument("--apps-root", default="",
                    help="path of the app dataset; default [apps] root")
    ap.add_argument("--hourly-keep", type=int, default=24,
                    help="how many hours of hourly snapshots to keep (default 24)")
    ap.add_argument("--daily-keep", type=int, default=30,
                    help="how many days of daily snapshots to keep (default 30)")
    ap.add_argument("--list", action="store_true",
                    help="only report the snapshots that exist; change nothing")
    ap.add_argument("--snapshot-now", metavar="NAME", default="",
                    help="also take one snapshot of each target immediately, with "
                         "this name (e.g. before a migration). Needs --apply.")
    add_host_key_arg(ap)
    add_site_arg(ap)
    add_nas_kind_arg(ap)
    # --apply, not --dry-run: every other script in this package defaults to
    # doing the thing and opts out. This one creates a RECURRING privileged
    # task on a customer's storage, so it defaults to describing itself and
    # opts in (2026-08-17, COMMERCIAL_READINESS.md item 8).
    ap.add_argument("--apply", action="store_true",
                    help="actually create/update the tasks (default: dry-run)")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)
    backend = get_backend(args)
    dry_run = not args.apply

    where = targets(args)
    print(f"NAS: {backend.kind}")
    print("Snapshot targets:")
    for label, path in where:
        print(f"  {label}: {path}")
    print("Existing snapshots:")
    for label, path in where:
        report_existing(backend, label, path, dry_run)
    if args.list:
        return 0

    policy = schedules(args.hourly_keep, args.daily_keep)
    print(f"Policy: hourly ({HOURLY_SCHEMA}) keep {args.hourly_keep}h; "
          f"daily ({DAILY_SCHEMA}) keep {args.daily_keep}d; recursive")

    failed, manual = [], []
    for label, path in where:
        for state, detail in backend.ensure_snapshot_schedule(path, policy, dry_run):
            if state == "failed":
                failed.append(f"{label}: {detail}")
            elif state == "manual":
                manual.append(f"{label}: {detail}")
        if args.snapshot_now:
            ok, ident = backend.snapshot_now(path, args.snapshot_now, dry_run)
            if not ok:
                failed.append(f"{label}: immediate snapshot {args.snapshot_now!r} failed")
            elif dry_run:
                pass
            else:
                print(f"took: {ident}")

    if dry_run:
        # Refusals are reported in dry-run too. A dry-run that quietly swallows
        # "that path is not on this NAS" is worse than no dry-run: the operator
        # reads a clean report and only meets the refusal with --apply typed.
        for line in failed + manual:
            print(f"\nWOULD NOT SUCCEED -- {line}", file=sys.stderr)
        print("\n[dry-run] nothing was changed. Re-run with --apply to create the "
              "tasks above.")
        return 1 if failed else 0

    for line in manual:
        print(f"\nMANUAL STEP REQUIRED -- {line}", file=sys.stderr)
    for line in failed:
        print(f"FAILED -- {line}", file=sys.stderr)
    if failed or manual:
        # Non-zero on purpose. "The script printed the DSM steps" must not be
        # mistakable for "the customer now has backups"; the runbook check in
        # docs/BACKUP_RESTORE.md is a snapshot LIST, not this script's output.
        print("\nBackups are NOT fully configured. See docs/BACKUP_RESTORE.md.",
              file=sys.stderr)
        return 1
    print("\nDone. Verify within the hour with: python setup_snapshots.py --list")
    return 0


if __name__ == "__main__":
    sys.exit(cli(main))
