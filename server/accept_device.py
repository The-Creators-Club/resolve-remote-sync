#!/usr/bin/env python3
"""Approve (accept + name) a pending editor Syncthing device.

    python accept_device.py --device-id ABCD1234-... --device-name jsmith \\
        --gui-url http://<nas>:8384 --api-key XXXX [--dry-run]

Run this once per new editor device. The editor's device ID is printed by
their bootstrap script (installer/windows_bootstrap.ps1 or macos_bootstrap.sh)
and sent to the admin out of band.

FOLDER SHARING IS NO LONGER PART OF THE NORMAL WORKFLOW. The dashboard owns
it: an editor's ticks decide which projects they get, and enforcement
reconciles every mapped editor's shares within a minute -- a hand-made share
for a mapped editor is reverted (and a hand-removed one re-added). So
--folder-id is optional and exists only for the legacy/unmapped case: an
editor who is not managed by the dashboard, or a one-off repair while the
dashboard is down.

Steps, via the Syncthing REST API:
  1. GET /rest/cluster/pending/devices -- purely informational; confirms the
     device really is pending (prints a note if it isn't found there, but
     doesn't block on it, since a device already added previously via this
     same script would no longer show as "pending").
  2. GET /rest/config/devices -- if --device-id is already a configured
     device, skip step 3 (idempotent); its name is updated if --device-name
     differs from what is on file.
  3. POST /rest/config/devices to add the device (this is also how you
     "accept" a pending device in Syncthing -- adding it to config approves
     it).
  4. ONLY with --folder-id: GET /rest/config/folders/<folder-id>, add the
     device to that folder's `devices` list if not already present, PUT it
     back.

Env vars: SYNCTHING_GUI_URL / SYNCTHING_API_KEY used as fallback defaults
for --gui-url / --api-key.
"""
import argparse
import os
import re
import sys

from common import add_site_arg, cli, ok, syncthing_api

# A Syncthing device ID is 8 dash-separated groups of 7 base32 characters
# (RFC 4648 alphabet minus 0/1/8/9, i.e. A-Z and 2-7), e.g.
# P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2.
# Deliberately lenient: it does not verify the interleaved Luhn check
# characters, only the shape, so a typo'd-but-well-formed ID still reaches
# Syncthing (which does check them) rather than being rejected here for the
# wrong reason.
DEVICE_ID_RE = re.compile(r"^[A-Z2-7]{7}(-[A-Z2-7]{7}){7}$")

# The device NAME is not cosmetic: the dashboard maps a Syncthing device to an
# editor account by it (db.resolve_editor_username), and that mapping decides
# which projects the device is shared with. Same charset as the dashboard's
# _USERNAME_RE so the two ends agree on what could even be a username.
#
# A name that is merely username-SHAPED is not enough on the dashboard side any
# more: machine names look exactly like usernames ("alex-laptop", "edit-pc"),
# and a device approved under one used to resolve to an editor account with no
# selections, which the enforce cycle read as "ticked for nothing" and unshared
# from every folder it was on (KNOWN_BUGS B16). The dashboard is the only
# component holding the editor account list, so it does the real check; this
# script's job is to make the contract impossible to miss.
USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")


def check_device_name(device_name: str, device_id: str) -> list[str]:
    """Warnings (possibly empty) about a --device-name the dashboard will not
    be able to map to an editor. Never raises: an unmapped device still works,
    it is just managed by hand rather than by project ticks."""
    name = str(device_name or "").strip()
    if name == device_id:
        return ["no --device-name given: this device is UNMAPPED. The dashboard will "
                "not manage its folder shares -- pass --device-name <editor's TrueNAS "
                "username> to have project ticks drive them."]
    if not USERNAME_RE.match(name.lower()):
        return [f"--device-name {name!r} is not a TrueNAS-style username, so the "
                f"dashboard will treat this device as UNMAPPED and never touch its "
                f"folder shares. Use the editor's account name (lowercase; letters, "
                f"digits, '.', '_', '-')."]
    return [f"--device-name must be the editor's TrueNAS USERNAME, not their machine "
            f"name: the dashboard maps device -> editor by it and shares projects "
            f"accordingly. {name!r} is only honoured if an editor account by that name "
            f"is known to the dashboard (it has ticked a project, reported, or been "
            f"created in Admin > Users); otherwise the device is left UNMAPPED and its "
            f"shares are managed by hand."]


def normalize_device_id(device_id: str) -> str:
    """Uppercase + shape-check a Syncthing device ID, or raise ValueError."""
    cleaned = str(device_id or "").strip().upper()
    if not DEVICE_ID_RE.match(cleaned):
        raise ValueError(
            f"--device-id {device_id!r} is not a Syncthing device ID.\n"
            f"  Expected 8 groups of 7 characters (A-Z, 2-7) separated by dashes, e.g.\n"
            f"    P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2\n"
            f"  The editor's bootstrap prints this value; copy it whole (it is 63 "
            f"characters). Adding a malformed ID would create a device entry that can "
            f"never connect."
        )
    return cleaned


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device-id", required=True, help="the editor's Syncthing device ID")
    ap.add_argument("--folder-id", default=None,
                    help="OPTIONAL, legacy: share this folder with the device too. The "
                         "dashboard's enforcement owns sharing for mapped editors and will "
                         "reconcile it away; use this only for an unmanaged editor or a "
                         "repair while the dashboard is down.")
    ap.add_argument("--device-name", default=None,
                    help="the editor's TrueNAS USERNAME (NOT their machine name) -- the "
                         "dashboard maps device -> editor by this and shares their ticked "
                         "projects accordingly. Defaults to --device-id, which leaves the "
                         "device unmapped.")
    ap.add_argument("--gui-url", default=os.environ.get("SYNCTHING_GUI_URL"))
    ap.add_argument("--api-key", default=os.environ.get("SYNCTHING_API_KEY"))
    add_site_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        args.device_id = normalize_device_id(args.device_id)
    except ValueError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1

    if not args.dry_run and not args.gui_url:
        print("FAILED: --gui-url is required (or set SYNCTHING_GUI_URL)", file=sys.stderr)
        return 1
    if not args.dry_run and not args.api_key:
        print("FAILED: --api-key is required (or set SYNCTHING_API_KEY)", file=sys.stderr)
        return 1

    gui_url = args.gui_url or "<gui-url-unset-dry-run>"
    api_key = args.api_key or "<api-key-unset-dry-run>"
    device_name = args.device_name or args.device_id

    for warning in check_device_name(device_name, args.device_id):
        print(f"NOTE: {warning}")

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
    existing_device = None
    if not args.dry_run:
        if not ok(resp):
            print(f"FAILED to list configured devices: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        existing_device = next((d for d in resp.json()
                                if d.get("deviceID") == args.device_id), None)
    already_configured = existing_device is not None

    if already_configured:
        print(f"device already configured, skipping add: {args.device_id}")
        # Renaming is the one thing worth doing on a re-run: a device that
        # first appeared under its machine name is much easier to match to an
        # editor once it carries their username.
        if args.device_name and existing_device.get("name") != args.device_name:
            updated = dict(existing_device)
            updated["name"] = args.device_name
            resp = syncthing_api("PUT", gui_url, f"/rest/config/devices/{args.device_id}",
                                  api_key, json_body=updated, dry_run=args.dry_run)
            if not ok(resp):
                print(f"WARNING: could not rename device to {args.device_name!r}: "
                      f"HTTP {resp.status_code if resp is not None else '?'}", file=sys.stderr)
            else:
                print(f"renamed device: {existing_device.get('name')!r} -> "
                      f"{args.device_name!r}")
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

    # Step 4: share a folder with the device -- OPTIONAL and legacy. The
    # dashboard's enforcement loop owns sharing for every mapped editor, so a
    # hand-made share here is reverted (or re-added) within about a minute.
    if not args.folder_id:
        print("no --folder-id given: the device is approved, no folder was touched.")
        print("Next: tick this editor's projects in the dashboard -- enforcement shares "
              "the matching folders (and revokes the ones they are not on). Pass "
              "--folder-id only for an editor the dashboard does not manage.")
        return 0

    print(f"NOTE: --folder-id given. If {device_name} is a dashboard-mapped editor, "
          f"enforcement will reconcile this share against their ticked projects and may "
          f"undo it -- tick the project in the dashboard instead.")

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
    sys.exit(cli(main))
