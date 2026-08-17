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
  3. Only if that shape check passes does it POST /api/v2.0/app with the
     payload below. If the shape check fails, the script prints exactly what
     it expected vs. what it found and exits non-zero -- it will NOT guess
     at a different payload shape.
  4. POST /app returns a JOB ID, not a finished install: it only means
     "accepted". The job is polled to completion (common.wait_for_job) and
     the script reports success only for state SUCCESS.

The steps above are the TrueNAS backend's (server/backends/truenas.py,
install_syncthing -- the bodies moved there on 2026-08-17, unchanged). On
Synology this script is a no-op by design: Syncthing runs as a service in our
own compose stack there, so we control its version, API key and data mount
(docs/SYNOLOGY_PORT_PLAN.md decision 3).

APP-CREATE PAYLOAD -- this docstring mirrors what the backend actually sends
(schema confirmed against live TrueNAS 25.10.4, stable/syncthing 1.3.11
questions.yaml, 2026-07-22). Edit both together:

    POST /api/v2.0/app
    {
        "app_name": "syncthing",
        "catalog_app": "syncthing",
        "train": "stable",
        "version": "<discovered from the catalog GET in step 2>",
        "values": {
            # [stack] uid/gid from site.toml -- 3000:3001 = broll:editors on
            # this NAS, so files Syncthing writes land group-editors like
            # everything else in the tree.
            "run_as": {"user": <[stack] uid>, "group": <[stack] gid>},
            "network": {
                "web_port": {"bind_mode": "published",
                             "port_number": <--gui-port, default 8384>},
                "tcp_port": {"bind_mode": "published", "port_number": 22000},
                "udp_port": {"bind_mode": "published", "port_number": 22000},
                "host_network": False,
            },
            "storage": {
                "config": {"type": "ix_volume",
                           "ix_volume_config": {"dataset_name": "config",
                                                "acl_enable": False}},
                "additional_storage": [
                    {"type": "host_path",
                     "mount_path": <--container-mount, default /data>,
                     "host_path_config": {"path": <--host-path>,
                                          "acl_enable": False}},
                ],
            },
        },
    }

`storage.additional_storage[0].host_path_config.path` is the host path
bind-mounted into the app; `mount_path` is where it lands inside the
container and is what setup_syncthing_folder.py builds folder paths from
(SYNCTHING_CONTAINER_MOUNT below). Override both with --host-path /
--container-mount if the chart's defaults ever move.

GUI port default 8384 is Syncthing's own default and does not collide with
resolve-projectserver (5432) or anything else known to be running on this
NAS as of SPEC.md; pass --gui-port to override if a future app collides.

Env vars: TRUENAS_HOST / TRUENAS_USER (no defaults -- they come from [nas]
host / admin_user in site.toml, see docs/SERVER.md), TRUENAS_PW (required).
"""
import argparse
import sys

# ok / truenas_api / wait_for_job stay imported (and are re-exported by name)
# even though the bodies moved to server/backends/ on 2026-08-17: ScriptCalls
# resolves the backend's NAS access through THIS module's names, which is what
# keeps server/tests' monkeypatches effective (see common.ScriptCalls).
from common import (  # noqa: F401
    ScriptCalls, add_nas_kind_arg, add_site_arg, cli, get_backend, ok,
    require_site_value, truenas_api, wait_for_job,
)
from common import DEFAULT_CC_ROOT

APP_NAME = "syncthing"
SYNCTHING_CONTAINER_MOUNT = "/data"  # ASSUMPTION -- verify against chart defaults

# The catalog/train/payload-shape constants moved to backends/truenas.py with
# the install itself (WP3); they are re-exported here because this script's
# docstring documents them and they are this script's subject matter.
_ARGS = None   # set by main(); None means "kind from $CCSYNC_NAS_KIND/site.toml"
_BACKEND = None


def backend():
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = get_backend(_ARGS, calls=ScriptCalls(sys.modules[__name__]))
    return _BACKEND


def app_already_installed(dry_run: bool) -> bool:
    """Re-export; the tri-state query moved to backends/<kind>.py 2026-08-17.

    The exit-on-unanswerable stays HERE: unlike install_dashboard_app, nothing
    has been swapped yet when this runs, so stopping is the right answer and
    always was.
    """
    installed = backend().app_installed(APP_NAME, dry_run)
    if installed is None:
        sys.exit(1)
    return installed


def find_catalog_entry(dry_run: bool):
    """Re-export; body in backends/truenas.py since 2026-08-17."""
    return backend().find_catalog_entry(APP_NAME, dry_run)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gui-port", type=int, default=8384, help="Syncthing web GUI port, default 8384")
    ap.add_argument("--host-path", default=DEFAULT_CC_ROOT,
                     help="host path bind-mounted into the app (default: the tree root "
                          "from site.toml)")
    ap.add_argument("--container-mount", default=SYNCTHING_CONTAINER_MOUNT,
                     help=f"where --host-path lands inside the container, default {SYNCTHING_CONTAINER_MOUNT}")
    add_site_arg(ap)
    add_nas_kind_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    global _ARGS
    _ARGS = args
    host_path = require_site_value(args.host_path, "[tree] pool_root/tree_name",
                                   "--host-path")

    if app_already_installed(args.dry_run):
        print(f"app already installed, skipping: {APP_NAME}")
        print(f"(if config needs to change -- e.g. GUI port -- edit it via the TrueNAS UI or "
              f"the /app/update API; this script only handles first-install.)")
        return 0

    # The create half -- catalog lookup, shape check, payload, POST, job wait --
    # is the backend's (backends/truenas.py:install_syncthing). On Synology it
    # is a no-op: Syncthing is a service in our own compose stack there.
    return backend().install_syncthing(args.gui_port, host_path,
                                       args.container_mount, args.dry_run)


if __name__ == "__main__":
    sys.exit(cli(main))
