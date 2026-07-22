#!/usr/bin/env python3
"""Install the Syncthing app (stable catalog) on TrueNAS SCALE for lane C.

    python install_syncthing_app.py [--gui-port 8384] [--dry-run]

TrueNAS SCALE's "Apps" API has changed shape across releases (charts/helm
values in older releases, a simplified `app_create` schema on newer ones).
Rather than guess and risk a bad POST, this script:

  1. GETs /api/v2.0/app to check whether an app named "syncthing" is
     already installed -- if so, it's idempotent-skip.
  2. GETs the catalog listing for the "stable" train (endpoint tried in
     order: /api/v2.0/app/available, falling back to
     /api/v2.0/catalog/apps) and looks for an entry whose name/id is
     "syncthing", validating it has the fields this script expects
     (see EXPECTED_CATALOG_FIELDS below).
  3. Only if that shape check passes does it POST
     /api/v2.0/app/create with the ASSUMED_VALUES payload documented
     below. If the shape check fails, the script prints exactly what it
     expected vs. what it found and exits non-zero -- it will NOT guess
     at a different payload shape.

ASSUMED APP-CREATE PAYLOAD (documented here so a human can adapt it once
the real schema is confirmed against the live API -- this is the single
place to edit):

    {
        "app_name": "syncthing",
        "catalog": "TRUENAS",
        "train": "stable",
        "version": "<discovered from the catalog GET in step 2>",
        "values": {
            "syncthing": {
                "puid": 0,
                "pgid": 0,
            },
            "network": {
                "webUIPort": <--gui-port, default 8384>,
            },
            "storage": {
                "data": {
                    "type": "hostPath",
                    "hostPath": "/mnt/tank/TheCreatorsPool/Creators_Club",
                },
            },
        },
    }

`storage.data.hostPath` is the host path bind-mounted into the app; the
in-container mount point this implies (used by setup_syncthing_folder.py
and referenced in docs) is documented as SYNCTHING_CONTAINER_MOUNT below --
CONFIRM THIS against the actual chart's default container mount point
before relying on it; if the chart mounts it somewhere else, override with
--container-mount.

GUI port default 8384 is Syncthing's own default and does not collide with
resolve-projectserver (5432) or anything else known to be running on this
NAS as of SPEC.md; pass --gui-port to override if a future app collides.

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required).
"""
import argparse
import sys

from common import ok, truenas_api

CATALOG = "TRUENAS"
TRAIN = "stable"
APP_NAME = "syncthing"
SYNCTHING_CONTAINER_MOUNT = "/data"  # ASSUMPTION -- verify against chart defaults

# Fields this script requires to be present on the catalog entry before it
# will trust its own assumed values payload above. If TrueNAS's catalog API
# shape has changed, one or more of these will be missing and the script
# stops rather than guessing.
EXPECTED_CATALOG_FIELDS = ("name", "latest_version")


def app_already_installed(dry_run: bool) -> bool:
    resp = truenas_api("GET", "/app", params={"query-filters": f'[["name","=","{APP_NAME}"]]'}, dry_run=dry_run)
    if dry_run:
        return False
    if not ok(resp):
        print(f"FAILED to query installed apps: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    apps = resp.json()
    return any(a.get("name") == APP_NAME for a in apps)


def find_catalog_entry(dry_run: bool):
    """Try /app/available first (older API name), then /catalog/apps."""
    if dry_run:
        print(f"[dry-run] would GET /app/available (catalog={CATALOG}, train={TRAIN}) "
              f"looking for {APP_NAME!r}, falling back to /catalog/apps if that 404s")
        return {"name": APP_NAME, "latest_version": "<unknown-in-dry-run>"}

    for path, params in (
        ("/app/available", {"catalog": CATALOG, "train": TRAIN}),
        ("/catalog/apps", {"catalog": CATALOG, "train": TRAIN}),
    ):
        resp = truenas_api("GET", path, params=params, dry_run=False)
        if resp is None:
            continue
        if resp.status_code == 404:
            continue
        if not ok(resp):
            print(f"NOTE: {path} returned HTTP {resp.status_code}, trying next candidate endpoint", file=sys.stderr)
            continue
        try:
            entries = resp.json()
        except ValueError:
            continue
        if isinstance(entries, dict):
            entries = list(entries.values())
        matches = [e for e in entries if isinstance(e, dict) and
                   (e.get("name") == APP_NAME or e.get("id") == APP_NAME or e.get("app_name") == APP_NAME)]
        if matches:
            return matches[0]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gui-port", type=int, default=8384, help="Syncthing web GUI port, default 8384")
    ap.add_argument("--host-path", default="/mnt/tank/TheCreatorsPool/Creators_Club",
                     help="host path bind-mounted into the app")
    ap.add_argument("--container-mount", default=SYNCTHING_CONTAINER_MOUNT,
                     help=f"where --host-path lands inside the container, default {SYNCTHING_CONTAINER_MOUNT}")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if app_already_installed(args.dry_run):
        print(f"app already installed, skipping: {APP_NAME}")
        print(f"(if config needs to change -- e.g. GUI port -- edit it via the TrueNAS UI or "
              f"the /app/update API; this script only handles first-install.)")
        return 0

    entry = find_catalog_entry(args.dry_run)
    if entry is None:
        print(f"FAILED: could not find catalog entry for {APP_NAME!r} in catalog={CATALOG} train={TRAIN} "
              f"via either /app/available or /catalog/apps. The Apps API shape may have changed again -- "
              f"inspect it manually (GET /api/v2.0/app/available) and update find_catalog_entry() in this "
              f"script.", file=sys.stderr)
        return 1

    missing = [f for f in EXPECTED_CATALOG_FIELDS if f not in entry]
    if missing and not args.dry_run:
        print(f"FAILED: catalog entry for {APP_NAME!r} is missing expected field(s) {missing}. "
              f"Found keys: {sorted(entry.keys())}. Refusing to guess a create payload against an "
              f"unfamiliar schema -- update EXPECTED_CATALOG_FIELDS and the payload in this script's "
              f"docstring once you've confirmed the real shape.", file=sys.stderr)
        return 1

    version = entry.get("latest_version", "<unknown>")
    print(f"found catalog entry: {APP_NAME} version {version} (catalog={CATALOG}, train={TRAIN})")

    # Schema confirmed against the live TrueNAS 25.10.4 chart (stable/
    # syncthing 1.3.11 questions.yaml) on 2026-07-22 — see the chart's
    # run_as/network/storage variable tree. run_as 3000:3001 = broll:editors
    # so files Syncthing writes land group-editors like everything else.
    values = {
        "run_as": {"user": 3000, "group": 3001},
        "network": {
            "web_port": {"bind_mode": "published", "port_number": args.gui_port},
            "tcp_port": {"bind_mode": "published", "port_number": 22000},
            "udp_port": {"bind_mode": "published", "port_number": 22000},
            "host_network": False,
        },
        "storage": {
            "config": {
                "type": "ix_volume",
                "ix_volume_config": {"dataset_name": "config", "acl_enable": False},
            },
            "additional_storage": [
                {
                    "type": "host_path",
                    "mount_path": args.container_mount,
                    "host_path_config": {"path": args.host_path, "acl_enable": False},
                }
            ],
        },
    }
    body = {
        "app_name": APP_NAME,
        "catalog_app": APP_NAME,
        "train": TRAIN,
        "version": version,
        "values": values,
    }

    resp = truenas_api("POST", "/app", json_body=body, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[dry-run] container mount for --host-path would be assumed at: {args.container_mount}")
        print("[dry-run] (CONFIRM this against the real chart before running setup_syncthing_folder.py)")
        return 0

    if not ok(resp):
        print(f"FAILED to install {APP_NAME}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        print("If this is a 422/400 body-shape error, the ASSUMED_VALUES payload in this script's "
              "docstring needs updating to match the real chart schema -- check the error body above "
              "for the specific field(s) it rejected.", file=sys.stderr)
        return 1

    print(f"installed app: {APP_NAME} version {version}, GUI port {args.gui_port}, "
          f"host path {args.host_path} -> container mount {args.container_mount}")
    print(f"Next: fetch the GUI's API key (TrueNAS UI > Apps > {APP_NAME} > Web UI, or the app's "
          f"config file) and pass it to setup_syncthing_folder.py / accept_device.py / check_health.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
