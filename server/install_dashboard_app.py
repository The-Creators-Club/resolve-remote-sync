#!/usr/bin/env python3
"""Deploy the ccsync-dashboard as a TrueNAS custom app.

    SYNCTHING_API_KEY=... DASH_REPORT_TOKEN=... TRUENAS_PW=... \\
        python install_dashboard_app.py [--port 8480] [--dry-run]

Steps (each idempotent, one line printed per action):

  1. Create the host dirs over SSH (sudo):
       <host-root>/app    -- the repo's dashboard/ tree (replaced on re-run)
       <host-root>/data   -- SQLite DB + venv (NEVER touched on re-run)
     both chowned 3000:3001 (broll:editors), mode 770.
  2. Upload the local dashboard/ tree via SFTP to a /tmp staging dir, then
     sudo-move it into <host-root>/app (SFTP runs as TRUENAS_USER, which
     cannot write into the 770 broll:editors dir directly). Excludes .venv,
     __pycache__, *.pyc.
  3. If the app is not yet installed: POST /api/v2.0/app with
       {"custom_app": true, "app_name": "ccsync-dashboard",
        "custom_compose_config": {...}}   (compose dict mirrors
     dashboard/deploy/compose.yaml -- keep them in sync). The custom_app
     payload shape is ASSUMED from the TrueNAS 25.10 middleware; if the POST
     is rejected the script prints the manual fallback (paste
     dashboard/deploy/compose.yaml into Apps > Install via YAML) instead of
     guessing at other shapes.
     If the app IS installed: POST /api/v2.0/app/redeploy {"app_name": ...}
     so the freshly-uploaded code is picked up (also an assumed shape, same
     fallback: restart the app from the TrueNAS UI).

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required), SYNCTHING_API_KEY (required),
DASH_REPORT_TOKEN (required -- companions must present this to POST
status reports; generate one with e.g. `openssl rand -hex 24` and put the
same value in each editor's ~/.ccsync/config.toml as dashboard_token).

TRUENAS_HOST/USER/PW are also forwarded into the deployed app's own
environment (same values this script already needs for its own SSH/API
calls) -- they back the admin "Users" section (create editor accounts,
approve pending Syncthing devices, set known passwords) added to the
dashboard. That section is a convenience layer over server/setup_editor_account.py
and server/accept_device.py, not a replacement -- the CLI scripts remain
the tools of record and work with or without the dashboard deployed.
"""
import argparse
import os
import posixpath
import sys
from pathlib import Path

from common import (
    DEFAULT_PROJECTS_ROOT, ok, require_env, run_ssh, shell_quote, truenas_api,
    truenas_conn_params, wait_for_job,
)

APP_NAME = "ccsync-dashboard"
DEFAULT_HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"
DEFAULT_SYNCTHING_GUI_URL = "http://192.168.0.102:8384"
STAGING_DIR = "/tmp/ccsync-dashboard-upload"
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache"}
LOCAL_DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"


def compose_config(port: int, host_root: str, gui_url: str, api_key: str, token: str,
                   session_secret: str = "", admin_users: str = "truenas_admin",
                   truenas_host: str = "", truenas_user: str = "", truenas_pw: str = "") -> dict:
    # Mirrors dashboard/deploy/compose.yaml -- keep the two in sync.
    return {
        "services": {
            "dashboard": {
                "image": "python:3.12-slim",
                "user": "3000:3001",
                "command": ["/bin/sh", "/app/deploy/run.sh"],
                "environment": {
                    "SYNCTHING_GUI_URL": gui_url,
                    "SYNCTHING_API_KEY": api_key,
                    "DASH_REPORT_TOKEN": token,
                    "DASH_SESSION_SECRET": session_secret,
                    "DASH_ADMIN_USERS": admin_users,
                    "DASH_DB_PATH": "/data/dashboard.db",
                    "DASH_PORT": str(port),
                    "DASH_PROJECTS_DIR": "/projects",
                    # DASH_PACKAGES_DIR intentionally unset: defaults to a
                    # "packages" dir next to DASH_DB_PATH (/data/packages),
                    # which is already the persistent volume.
                    "TRUENAS_HOST": truenas_host,
                    "TRUENAS_USER": truenas_user,
                    "TRUENAS_PW": truenas_pw,
                },
                "ports": [f"{port}:{port}"],
                "volumes": [
                    f"{host_root}/app:/app",
                    f"{host_root}/data:/data",
                    # rw for the /project-setup create flow; container runs
                    # as broll:editors, matching setup_tree.py's ownership.
                    f"{DEFAULT_PROJECTS_ROOT}:/projects:rw",
                ],
                "restart": "unless-stopped",
            }
        }
    }


def iter_local_files():
    for path in sorted(LOCAL_DASHBOARD_DIR.rglob("*")):
        rel = path.relative_to(LOCAL_DASHBOARD_DIR)
        if any(part in EXCLUDE_DIRS for part in rel.parts) or path.suffix == ".pyc":
            continue
        if path.is_file():
            yield path, rel.as_posix()


def upload_tree(dry_run: bool) -> int:
    files = list(iter_local_files())
    if dry_run:
        print(f"[dry-run] would SFTP {len(files)} files from {LOCAL_DASHBOARD_DIR} "
              f"to {STAGING_DIR} on the NAS")
        return len(files)

    import paramiko

    host, user, pw = truenas_conn_params()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=pw,
                   look_for_keys=False, allow_agent=False, timeout=20)
    try:
        sftp = client.open_sftp()
        made: set[str] = set()
        for local, rel in files:
            remote = posixpath.join(STAGING_DIR, rel)
            parent = posixpath.dirname(remote)
            parts = parent.split("/")
            for i in range(2, len(parts) + 1):
                d = "/".join(parts[:i])
                if d and d not in made:
                    try:
                        sftp.stat(d)
                    except FileNotFoundError:
                        sftp.mkdir(d)
                    made.add(d)
            sftp.put(str(local), remote)
        sftp.close()
    finally:
        client.close()
    print(f"uploaded {len(files)} files to staging {STAGING_DIR}")
    return len(files)


def app_installed(dry_run: bool) -> bool:
    # No query-filters param: the 25.10 middleware was observed returning []
    # for a filtered GET /app even when the app exists (2026-07-24 live run),
    # so fetch the full list and filter client-side.
    resp = truenas_api("GET", "/app", dry_run=dry_run)
    if dry_run:
        return False
    if not ok(resp):
        print(f"FAILED to query installed apps: HTTP {resp.status_code} {resp.text}",
              file=sys.stderr)
        sys.exit(1)
    return any(a.get("name") == APP_NAME for a in resp.json())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8480,
                    help="dashboard HTTP port, default 8480 (avoid 5432/8384/22000)")
    ap.add_argument("--host-root", default=DEFAULT_HOST_ROOT,
                    help=f"host dir for app+data, default {DEFAULT_HOST_ROOT}")
    ap.add_argument("--syncthing-gui-url",
                    default=os.environ.get("SYNCTHING_GUI_URL", DEFAULT_SYNCTHING_GUI_URL),
                    help="Syncthing GUI URL as seen FROM THE CONTAINER (host LAN IP works)")
    ap.add_argument("--recreate", action="store_true",
                    help="delete and re-create the app so compose changes (env vars, "
                         "mounts, ports) take effect; host app/ and data/ dirs survive")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not LOCAL_DASHBOARD_DIR.is_dir():
        print(f"FAILED: {LOCAL_DASHBOARD_DIR} not found -- run from the repo", file=sys.stderr)
        return 1

    if args.dry_run:
        api_key = os.environ.get("SYNCTHING_API_KEY", "<SYNCTHING_API_KEY-unset-dry-run>")
        token = os.environ.get("DASH_REPORT_TOKEN", "<DASH_REPORT_TOKEN-unset-dry-run>")
        session_secret = os.environ.get("DASH_SESSION_SECRET", "<DASH_SESSION_SECRET-unset-dry-run>")
    else:
        api_key = require_env("SYNCTHING_API_KEY")
        token = require_env("DASH_REPORT_TOKEN")
        # Stable across deploys: rotating it logs every editor out.
        session_secret = require_env("DASH_SESSION_SECRET")
    admin_users = os.environ.get("DASH_ADMIN_USERS", "truenas_admin")
    truenas_host, truenas_user, truenas_pw = truenas_conn_params(dry_run=args.dry_run)

    root = args.host_root.rstrip("/")

    # Step 1: host dirs. data/ is create-only; app/ contents get replaced later.
    rc, _, err = run_ssh(
        'echo "$SUDO_PW" | sudo -S sh -c '
        + shell_quote(
            f"mkdir -p {shell_quote(root + '/app')} {shell_quote(root + '/data')} && "
            f"chown -R 3000:3001 {shell_quote(root)} && chmod 770 "
            f"{shell_quote(root)} {shell_quote(root + '/app')} {shell_quote(root + '/data')}"
        ),
        dry_run=args.dry_run,
    )
    if rc != 0:
        print(f"FAILED to create host dirs: {err}", file=sys.stderr)
        return 1
    print(f"host dirs ready: {root}/app, {root}/data")

    # Step 2: upload code to staging, sudo-copy into place (data/ untouched).
    # The app dir is bind-mounted into the running container, so its INODE
    # must be preserved: empty it and copy contents in, never rm -rf + mv the
    # directory itself (that orphans the container's mount -- seen live
    # 2026-07-24 as an empty /app inside the container).
    upload_tree(args.dry_run)
    app_dir = shell_quote(root + "/app")
    rc, _, err = run_ssh(
        'echo "$SUDO_PW" | sudo -S sh -c '
        + shell_quote(
            f"mkdir -p {app_dir} && "
            f"find {app_dir} -mindepth 1 -delete && "
            f"cp -a {shell_quote(STAGING_DIR)}/. {app_dir}/ && "
            f"rm -rf {shell_quote(STAGING_DIR)} && "
            f"chown -R 3000:3001 {app_dir} && "
            f"chmod -R u+rwX,g+rwX,o-rwx {app_dir}"
        ),
        dry_run=args.dry_run,
    )
    if rc != 0:
        print(f"FAILED to install code into {root}/app: {err}", file=sys.stderr)
        return 1
    print(f"installed code: {root}/app")

    # Step 3: create or redeploy the custom app.
    if args.recreate and app_installed(args.dry_run):
        resp = truenas_api("DELETE", f"/app/id/{APP_NAME}",
                           json_body={"remove_ix_volumes": False}, dry_run=args.dry_run)
        if args.dry_run:
            print(f"[dry-run] would delete app {APP_NAME} and re-create it")
        elif not ok(resp):
            print(f"FAILED to delete app for --recreate: HTTP {resp.status_code} {resp.text}",
                  file=sys.stderr)
            return 1
        else:
            try:
                job_id = resp.json()
            except ValueError:
                job_id = None
            if isinstance(job_id, int):
                state, job_err = wait_for_job(job_id, timeout=180)
                if state != "SUCCESS":
                    print(f"FAILED: app delete job ended {state}: {job_err}", file=sys.stderr)
                    return 1
            print(f"deleted app for re-create: {APP_NAME}")

    if app_installed(args.dry_run):
        # /app/redeploy was observed NOT restarting the container on 25.10
        # (2026-07-24: stale process kept serving old in-memory code), so
        # restart the container directly. Compose name convention:
        # ix-<app_name>-<service>-1.
        container = f"ix-{APP_NAME}-dashboard-1"
        rc, out, err = run_ssh(
            f'echo "$SUDO_PW" | sudo -S docker restart {shell_quote(container)}',
            dry_run=args.dry_run,
        )
        if args.dry_run or rc == 0:
            print(f"restarted container: {container}")
        else:
            print(f"NOTE: docker restart failed ({err.strip()[:200]}); restart the "
                  f"{APP_NAME!r} app from the TrueNAS UI to pick up the new code.")
        return 0

    body = {
        "custom_app": True,
        "app_name": APP_NAME,
        "custom_compose_config": compose_config(
            args.port, root, args.syncthing_gui_url, api_key, token,
            session_secret, admin_users, truenas_host, truenas_user, truenas_pw
        ),
    }
    resp = truenas_api("POST", "/app", json_body=body, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[dry-run] would create custom app {APP_NAME} on port {args.port}")
        return 0
    if not ok(resp):
        print(f"FAILED to create custom app: HTTP {resp.status_code} {resp.text}",
              file=sys.stderr)
        print("Manual fallback: TrueNAS UI > Apps > Discover Apps > (...) > Install via "
              "YAML, paste dashboard/deploy/compose.yaml and fill in SYNCTHING_API_KEY "
              "and DASH_REPORT_TOKEN.", file=sys.stderr)
        return 1
    print(f"installed custom app: {APP_NAME} on port {args.port}")
    print(f"Next: open http://<tailnet-ip>:{args.port}/ and check /api/v1/health; then set "
          f"dashboard_url/dashboard_token in each editor's ~/.ccsync/config.toml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
