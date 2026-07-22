#!/usr/bin/env python3
"""One command to validate the whole server side. Plain PASS/FAIL lines,
exit code = number of failed checks (0 = all good).

    python check_health.py [--gui-url http://192.168.0.102:8384 --api-key XXXX] [--dry-run]

Checks:
  1. Postgres reachable on :5432 (raw TCP connect -- proves resolve-
     projectserver is up and port-forwarded, not that auth works).
  2. Tailscale container logged in: SSH in, `docker exec tailscale tailscale
     status --json`, report tailnet IP and BackendState; FAIL if logged out.
  3. Syncthing app up: GET /rest/system/ping against --gui-url.
  4. Syncthing folders listed: GET /rest/config/folders, print count + ids.
  5. Project tree exists: SSH `test -d` on the Projects root.
  6. Editor accounts exist: TrueNAS API, list members of the `editors`
     group.

--dry-run prints the exact checks that would run (SSH commands / API
calls) without opening any connection, same convention as every other
script in this package.

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required). SYNCTHING_GUI_URL / SYNCTHING_API_KEY
used as fallback defaults for --gui-url / --api-key.
"""
import argparse
import os
import socket
import sys

from common import (
    DEFAULT_PROJECTS_ROOT,
    DEFAULT_TRUENAS_HOST,
    EDITORS_GROUP,
    ok,
    run_ssh,
    shell_quote,
    syncthing_api,
    truenas_api,
    truenas_conn_params,
)

RESULTS = []  # list of (bool_passed, str_message)


def report(passed: bool, message: str):
    RESULTS.append((passed, message))
    status = "PASS" if passed else "FAIL"
    print(f"{status}: {message}")


def check_postgres(dry_run: bool):
    host, _, _ = truenas_conn_params(dry_run=dry_run)
    port = 5432
    if dry_run:
        print(f"[dry-run] would TCP-connect to {host}:{port}")
        return
    try:
        with socket.create_connection((host, port), timeout=5):
            report(True, f"postgres reachable at {host}:{port}")
    except OSError as e:
        report(False, f"postgres NOT reachable at {host}:{port} ({e})")


def check_tailscale(dry_run: bool):
    cmd = 'echo "$SUDO_PW" | sudo -S -p "" docker exec tailscale tailscale status --json'
    rc, out, err = run_ssh(cmd, dry_run=dry_run)
    if dry_run:
        return
    if rc != 0:
        report(False, f"could not run `tailscale status --json` in the tailscale container "
                       f"(SSH/docker exec exit {rc}): {err.strip() or out.strip()}")
        return
    import json as _json
    try:
        status = _json.loads(out)
    except ValueError:
        report(False, f"tailscale status output was not valid JSON: {out[:200]!r}")
        return
    backend_state = status.get("BackendState", "<unknown>")
    self_info = status.get("Self", {}) or {}
    tailnet_ips = self_info.get("TailscaleIPs", [])
    if backend_state == "Running":
        report(True, f"tailscale logged in (BackendState=Running), tailnet IP(s): {tailnet_ips}")
    else:
        report(False, f"tailscale NOT logged in (BackendState={backend_state!r}) -- run `tailscale up` "
                       f"in the container to re-auth")


def check_syncthing_app(gui_url, api_key, dry_run: bool):
    if not gui_url or not api_key:
        if dry_run:
            print("[dry-run] would check syncthing app/folders, but --gui-url/--api-key "
                  "(or SYNCTHING_GUI_URL/SYNCTHING_API_KEY) were not provided")
        else:
            report(False, "syncthing GUI/API check skipped -- pass --gui-url/--api-key "
                           "or set SYNCTHING_GUI_URL/SYNCTHING_API_KEY")
        return
    resp = syncthing_api("GET", gui_url, "/rest/system/ping", api_key, dry_run=dry_run)
    if dry_run:
        return
    if ok(resp):
        report(True, f"syncthing app reachable at {gui_url}")
    else:
        code = resp.status_code if resp is not None else "<no response>"
        report(False, f"syncthing app NOT reachable at {gui_url} (HTTP {code})")
        return

    resp = syncthing_api("GET", gui_url, "/rest/config/folders", api_key, dry_run=dry_run)
    if ok(resp):
        folders = resp.json()
        ids = [f.get("id") for f in folders]
        report(True, f"syncthing folders listed: {len(folders)} folder(s): {ids}")
    else:
        report(False, f"could not list syncthing folders (HTTP {resp.status_code if resp else '?'})")


def check_tree(projects_root: str, dry_run: bool):
    # sudo: TRUENAS_USER itself has no traverse rights on the 770 dataset,
    # so an unprivileged test -d false-negatives even when the tree exists.
    cmd = (f'echo "$SUDO_PW" | sudo -S -p "" test -d {shell_quote(projects_root)} '
           f"&& echo PRESENT || echo MISSING")
    rc, out, err = run_ssh(cmd, dry_run=dry_run)
    if dry_run:
        return
    if "PRESENT" in out:
        report(True, f"project tree root exists: {projects_root}")
    else:
        report(False, f"project tree root MISSING: {projects_root}")


def check_editor_accounts(dry_run: bool):
    resp = truenas_api("GET", "/group", params={"group": EDITORS_GROUP}, dry_run=dry_run)
    if dry_run:
        print(f"[dry-run] would also GET /user and cross-reference group membership for {EDITORS_GROUP!r}")
        return
    if not ok(resp):
        report(False, f"could not query group {EDITORS_GROUP!r} (HTTP {resp.status_code})")
        return
    groups = [g for g in resp.json() if g.get("group") == EDITORS_GROUP]
    if not groups:
        report(False, f"group {EDITORS_GROUP!r} does not exist -- no editor accounts can exist yet")
        return
    gid = groups[0]["gid"]

    resp = truenas_api("GET", "/user", dry_run=dry_run)
    if not ok(resp):
        report(False, f"could not list users (HTTP {resp.status_code})")
        return
    members = [u["username"] for u in resp.json()
               if gid in u.get("groups", []) or u.get("group") == gid]
    if members:
        report(True, f"editor accounts found in group {EDITORS_GROUP!r}: {members}")
    else:
        report(False, f"group {EDITORS_GROUP!r} exists but has no members yet")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gui-url", default=os.environ.get("SYNCTHING_GUI_URL"))
    ap.add_argument("--api-key", default=os.environ.get("SYNCTHING_API_KEY"))
    ap.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"Checking Creators Club sync server ({os.environ.get('TRUENAS_HOST', DEFAULT_TRUENAS_HOST)})...\n")

    check_postgres(args.dry_run)
    check_tailscale(args.dry_run)
    check_syncthing_app(args.gui_url, args.api_key, args.dry_run)
    check_tree(args.projects_root, args.dry_run)
    check_editor_accounts(args.dry_run)

    if args.dry_run:
        print("\n[dry-run] no checks were actually executed.")
        return 0

    failed = [msg for passed, msg in RESULTS if not passed]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed.")
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
