#!/usr/bin/env python3
"""Approve a pending editor Syncthing device and share a folder with it.

    python accept_device.py --device-id ABCD1234-... --folder-id 2025-ff4-nuclear \\
        --gui-url http://192.168.0.102:8384 --api-key XXXX [--device-name jsmith] [--dry-run]

Run this once per (device, folder) pair the editor needs -- typically once
per new editor per project they're on. The editor's device ID is printed by
their bootstrap script (installer/windows_bootstrap.ps1 or macos_bootstrap.sh)
and sent to the admin out of band.

Steps, via the Syncthing REST API:
  1. GET /rest/cluster/pending/devices -- purely informational; confirms the
     device really is pending (prints a note if it isn't found there, but
     doesn't block on it, since a device already added previously via this
     same script would no longer show as "pending").
  2. GET /rest/config/devices -- if --device-id is already a configured
     device, skip step 3 (idempotent).
  3. POST /rest/config/devices to add the device (this is also how you
     "accept" a pending device in Syncthing -- adding it to config approves
     it).
  4. GET /rest/config/folders/<folder-id>, add the device to that folder's
     `devices` list if not already present, PUT it back.

Env vars: SYNCTHING_GUI_URL / SYNCTHING_API_KEY used as fallback defaults
for --gui-url / --api-key.
"""
import argparse
import os
import sys

from common import ok, syncthing_api


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device-id", required=True, help="the editor's Syncthing device ID")
    ap.add_argument("--folder-id", required=True, help="folder id from setup_syncthing_folder.py")
    ap.add_argument("--device-name", default=None, help="human-readable label, defaults to --device-id")
    ap.add_argument("--gui-url", default=os.environ.get("SYNCTHING_GUI_URL"))
    ap.add_argument("--api-key", default=os.environ.get("SYNCTHING_API_KEY"))
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
    device_name = args.device_name or args.device_id

    # Step 1: informational only.
    resp = syncthing_api("GET", gui_url, "/rest/cluster/pending/devices", api_key, dry_run=args.dry_run)
    if not args.dry_run:
        if ok(resp) and args.device_id in resp.json():
            print(f"device confirmed pending: {args.device_id}")
        else:
            print(f"NOTE: {args.device_id} not found in /rest/cluster/pending/devices "
                  f"(already added previously, or hasn't dialed in yet -- continuing anyway)")

    # Step 2/3: ensure device is in config.
    resp = syncthing_api("GET", gui_url, "/rest/config/devices", api_key, dry_run=args.dry_run)
    already_configured = False
    if not args.dry_run:
        if not ok(resp):
            print(f"FAILED to list configured devices: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        already_configured = any(d.get("deviceID") == args.device_id for d in resp.json())

    if already_configured:
        print(f"device already configured, skipping add: {args.device_id}")
    else:
        device_config = {
            "deviceID": args.device_id,
            "name": device_name,
            "addresses": ["dynamic"],
            "introducer": False,
        }
        resp = syncthing_api("POST", gui_url, "/rest/config/devices", api_key,
                              json_body=device_config, dry_run=args.dry_run)
        if not args.dry_run:
            if not ok(resp):
                print(f"FAILED to add device: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
                return 1
            print(f"added device: {args.device_id} ({device_name})")

    # Step 4: share folder with device.
    resp = syncthing_api("GET", gui_url, f"/rest/config/folders/{args.folder_id}", api_key, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[dry-run] would ensure folder {args.folder_id!r} shares to device {args.device_id!r}")
        return 0

    if not ok(resp):
        print(f"FAILED to fetch folder {args.folder_id!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        return 1
    folder = resp.json()
    devices = folder.get("devices", [])
    if any(d.get("deviceID") == args.device_id for d in devices):
        print(f"folder already shared with device, skipping: {args.folder_id} -> {args.device_id}")
        return 0

    devices.append({"deviceID": args.device_id, "introducedBy": ""})
    folder["devices"] = devices
    resp = syncthing_api("PUT", gui_url, f"/rest/config/folders/{args.folder_id}", api_key,
                          json_body=folder, dry_run=False)
    if not ok(resp):
        print(f"FAILED to share folder with device: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        return 1
    print(f"shared folder {args.folder_id} with device {args.device_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
