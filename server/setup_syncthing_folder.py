#!/usr/bin/env python3
"""Create (or update) one Syncthing folder for a project, lane C only.

    python setup_syncthing_folder.py --project-rel-path 2025/FF4/Nuclear \\
        --gui-url http://192.168.0.102:8384 --api-key XXXX [--dry-run]

`--project-rel-path` is relative to Creators_Club/Projects on the mount
(e.g. "2025/FF4/Nuclear"), matching the args passed to setup_tree.py's
--year/--series/--project (year/series/project joined with '/').

Steps, all via the Syncthing REST API (server/README.md documents where the
GUI URL + API key come from -- Syncthing app config, or its config.xml):

  1. Compute folder id = slugify(project-rel-path), e.g. "2025-ff4-nuclear".
  2. GET /rest/config/folders -- if a folder with that id already exists,
     skip creation (idempotent) unless --force is given.
  3. POST /rest/config/folders with:
       - path = <container-mount>/Projects/<project-rel-path>
       - type: sendreceive
       - fsWatcherEnabled: true
       - versioning: staggered (server-side deletion safety net, per SPEC
         "Flaws" #2 -- lane C keeps versioned trash even though renames
         propagate)
  4. POST /rest/db/ignores?folder=<id> with the .stignore content: one
     case-insensitive line per video extension, plus **/Proxy -- videos and
     proxies never travel through Syncthing (lanes A/B, rclone, handle
     those).

Sharing the folder to a specific editor's device is NOT done here --
see accept_device.py, run once per (device, folder) after the editor's
Syncthing device ID is known.

Env vars: none required directly (gui-url/api-key are CLI args so this can
target any Syncthing instance), but SYNCTHING_GUI_URL / SYNCTHING_API_KEY
are read as fallback defaults if the flags are omitted.
"""
import argparse
import os
import sys

from common import build_stignore_lines, ok, slugify, syncthing_api

CONTAINER_MOUNT_DEFAULT = "/data"  # must match install_syncthing_app.py's --container-mount


def find_folder(gui_url: str, api_key: str, folder_id: str, dry_run: bool):
    resp = syncthing_api("GET", gui_url, "/rest/config/folders", api_key, dry_run=dry_run)
    if dry_run:
        return None
    if not ok(resp):
        print(f"FAILED to list folders: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    for f in resp.json():
        if f.get("id") == folder_id:
            return f
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-rel-path", required=True, help="e.g. 2025/FF4/Nuclear")
    ap.add_argument("--gui-url", default=os.environ.get("SYNCTHING_GUI_URL"),
                     help="e.g. http://192.168.0.102:8384 (or SYNCTHING_GUI_URL env var)")
    ap.add_argument("--api-key", default=os.environ.get("SYNCTHING_API_KEY"),
                     help="Syncthing API key (or SYNCTHING_API_KEY env var)")
    ap.add_argument("--container-mount", default=CONTAINER_MOUNT_DEFAULT,
                     help=f"where Creators_Club is mounted inside the Syncthing app, default {CONTAINER_MOUNT_DEFAULT}")
    ap.add_argument("--label", default=None, help="human-readable folder label, defaults to --project-rel-path")
    ap.add_argument("--force", action="store_true", help="recreate config even if the folder id already exists")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.gui_url:
        print("FAILED: --gui-url is required (or set SYNCTHING_GUI_URL)", file=sys.stderr)
        return 1
    if not args.dry_run and not args.api_key:
        print("FAILED: --api-key is required (or set SYNCTHING_API_KEY)", file=sys.stderr)
        return 1

    gui_url = args.gui_url or "<gui-url-unset-dry-run>"
    api_key = args.api_key or "<api-key-unset-dry-run>"

    rel = args.project_rel_path.strip("/").replace("\\", "/")
    folder_id = slugify(rel)
    path = f"{args.container_mount.rstrip('/')}/Projects/{rel}"
    label = args.label or rel

    print(f"project-rel-path: {rel}")
    print(f"folder id: {folder_id}")
    print(f"folder path (inside Syncthing app): {path}")

    existing = find_folder(gui_url, api_key, folder_id, args.dry_run)
    if existing and not args.force:
        print(f"folder already exists, skipping create: {folder_id} (use --force to reconfigure)")
    else:
        folder_config = {
            "id": folder_id,
            "label": label,
            "path": path,
            "type": "sendreceive",
            "fsWatcherEnabled": True,
            # aclmode=restricted on the dataset forbids chmod, which
            # Syncthing otherwise uses to mirror permissions — without this
            # every dir touch fails with "operation not permitted" and
            # transfers stall at the .syncthing.*.tmp stage (seen live).
            "ignorePerms": True,
            "rescanIntervalS": 3600,
            "versioning": {
                "type": "staggered",
                "params": {
                    "cleanInterval": "3600",
                    "maxAge": "31536000",
                },
            },
            # editors are added later, per-device, via accept_device.py; on a
            # --force reconfigure, preserve the existing device shares rather
            # than wiping them back to [].
            "devices": (existing or {}).get("devices", []),
        }
        if existing:
            print(f"--force given, updating existing folder: {folder_id}")
            resp = syncthing_api("PUT", gui_url, f"/rest/config/folders/{folder_id}", api_key,
                                  json_body=folder_config, dry_run=args.dry_run)
        else:
            resp = syncthing_api("POST", gui_url, "/rest/config/folders", api_key,
                                  json_body=folder_config, dry_run=args.dry_run)
        if not args.dry_run:
            if not ok(resp):
                print(f"FAILED to create/update folder: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
                return 1
            print(f"{'updated' if existing else 'created'} folder: {folder_id} "
                  f"(sendreceive, staggered versioning, fsWatcher on)")

    ignore_lines = build_stignore_lines()
    print(f".stignore ({len(ignore_lines)} lines):")
    for line in ignore_lines:
        print(f"  {line}")

    resp = syncthing_api("POST", gui_url, "/rest/db/ignores", api_key,
                          params={"folder": folder_id},
                          json_body={"ignore": ignore_lines}, dry_run=args.dry_run)
    if not args.dry_run:
        if not ok(resp):
            print(f"FAILED to set ignore patterns: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        print(f"ignore patterns applied to folder: {folder_id}")

    print("Done. Next: accept_device.py to share this folder with each editor's device ID.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
