#!/usr/bin/env python3
"""Deploy the ccsync-dashboard as a TrueNAS custom app.

    SYNCTHING_API_KEY=... DASH_REPORT_TOKEN=... TRUENAS_PW=... \\
        python install_dashboard_app.py [--port 8480] [--dry-run]

Steps (each idempotent, one line printed per action):

  1. Create the host dirs over SSH (sudo):
       <host-root>/app    -- the repo's dashboard/ tree (replaced on re-run);
                             root:root, world-readable, never group-writable
                             (mounted :ro in the container -- AUDIT C-1)
       <host-root>/venv   -- the container's dependency venv (NEVER touched
                             on re-run); 3000:3000, mode 700. Deliberately
                             NOT inside data/: run.sh execs an interpreter
                             out of it, and data/ used to be group-writable
                             by every editor (AUDIT C-2).
       <host-root>/data   -- SQLite DB + companion packages (NEVER touched on
                             re-run); 3000:3000 (broll:broll), mode 770 --
                             group 3000, NOT 3001/editors.
  2. Upload the local dashboard/ tree via SFTP to a fresh mktemp staging dir,
     verify the staged copy against the local manifest (file count AND total
     byte size), build <host-root>/app.new from it, verify that too, and only
     then swap it into place:
         mv app app.old.<ts> && mv app.new app
     Any failure before the swap leaves the live app/ untouched; a failed
     swap rolls back. The previous app.old.<ts> backups are pruned (most
     recent kept) only after a LATER install has succeeded.
     Excludes .venv, __pycache__, *.pyc.
  3. If the app is not yet installed: POST /api/v2.0/app with
       {"custom_app": true, "app_name": "ccsync-dashboard",
        "custom_compose_config": {...}}   (compose dict mirrors
     dashboard/deploy/compose.yaml -- keep them in sync; tests/test_safety.py
     asserts they have not drifted on image tag, bind defaults, env keys and
     healthcheck). The custom_app
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
same value in each editor's ~/.ccsync/config.toml as dashboard_token),
DASH_SESSION_SECRET (required -- signs editor/admin session cookies;
generate the same way. It must stay STABLE across deploys: a fresh value
logs every editor out, so store it alongside DASH_REPORT_TOKEN and pass
both again on --recreate).
Optional: DASH_ADMIN_USERS (default truenas_admin), SYNCTHING_GUI_URL,
CCSYNC_SSH_HOSTKEY (pin the NAS SSH host key; see --host-key),
DASH_BIND_LAN / DASH_BIND_TAILNET (the two addresses the dashboard is
published on, defaults 192.168.0.102 / 100.71.216.3 -- change these when the
NAS's DHCP lease or tailnet IP moves, or Docker refuses to start the app
with "cannot assign requested address"), DASH_IMAGE (pinned base image),
TRUENAS_VERIFY_SSL (default "0" = trust the NAS's self-signed cert).

Compose-level settings are baked in at CREATE time: after changing any of
them, re-run with --recreate, otherwise the running app keeps the old ones.

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
import re
import sys
import time
from pathlib import Path

from common import (
    DEFAULT_PROJECTS_ROOT, add_host_key_arg, ok, require_env, run_ssh,
    set_host_key_pin, shell_quote, ssh_client, truenas_api,
    truenas_conn_params, wait_for_job,
)

APP_NAME = "ccsync-dashboard"
DEFAULT_HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"
# The install replaces everything under <host-root>/app, as root. Bound that
# to the one location this app is ever deployed to, so a mistyped --host-root
# cannot point the replace at a project tree (AUDIT DEL-9).
HOST_ROOT_RE = re.compile(r"^/mnt/[^/]+/apps/ccsync-dashboard(/[^/]+)*$")
DEFAULT_SYNCTHING_GUI_URL = "http://192.168.0.102:8384"
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache"}
LOCAL_DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"
# Pinned, mirroring dashboard/deploy/compose.yaml: an unpinned python:3.12-slim
# silently changes underneath a redeploy. Bump deliberately, in both places.
DEFAULT_IMAGE = "python:3.12.7-slim"
# Host interfaces the dashboard binds to (mirrors dashboard/deploy/compose.yaml
# -- keep in sync): LAN for the base rig, tailnet for remote editors. Never
# 0.0.0.0 -- a new NAS interface must not silently expose the dashboard.
# These are DEFAULTS only: compose reads ${DASH_BIND_LAN}/${DASH_BIND_TAILNET}
# and this script takes --bind-lan/--bind-tailnet (same env names), because a
# NAS DHCP change or a tailnet IP rotation otherwise makes Docker fail with
# "cannot assign requested address" and the app never starts.
LAN_BIND_IP = "192.168.0.102"
TAILNET_BIND_IP = "100.71.216.3"


def healthcheck_config(port: int) -> dict:
    """Mirrors compose.yaml's healthcheck -- keep the two identical.

    `restart: unless-stopped` only covers a process that EXITS; a collector
    thread that died before entering its guarded loop leaves a container that
    answers nothing useful forever. /api/v1/health is unauthenticated by
    design for exactly this. urllib rather than curl: the python:*-slim image
    has no curl.
    """
    probe = (
        "python -c \"import urllib.request,sys; sys.exit(0 if "
        f"urllib.request.urlopen('http://127.0.0.1:{port}/api/v1/health', "
        "timeout=5).status == 200 else 1)\""
    )
    return {
        "test": ["CMD-SHELL", probe],
        "interval": "60s",
        "timeout": "10s",
        "retries": 3,
        "start_period": "120s",
    }


def compose_config(port: int, host_root: str, gui_url: str, api_key: str, token: str,
                   session_secret: str = "", admin_users: str = "truenas_admin",
                   truenas_host: str = "", truenas_user: str = "", truenas_pw: str = "",
                   truenas_verify_ssl: str = "0",
                   bind_lan: str = LAN_BIND_IP, bind_tailnet: str = TAILNET_BIND_IP,
                   image: str = DEFAULT_IMAGE) -> dict:
    # Mirrors dashboard/deploy/compose.yaml -- keep the two in sync. The ${VAR}
    # substitutions there are resolved here in Python instead: the TrueNAS
    # middleware stores this dict verbatim, so an unresolved ${...} would end
    # up as a literal bind address.
    return {
        "services": {
            "dashboard": {
                "image": image,
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
                    # AUDIT SEC-2 asked whether TRUENAS_PW can be dropped from
                    # the container env (it is readable via `docker inspect`).
                    # It cannot: the dashboard reads it at runtime
                    # (settings.py -> api.py/ui.py "Users" admin section, which
                    # creates editor accounts and approves devices) and returns
                    # a 503 "TRUENAS_PW is not configured" without it. Removing
                    # it here would break that section, so it stays -- the
                    # mitigation is that the container is root-only-readable and
                    # the dashboard is never exposed beyond LAN/tailnet.
                    "TRUENAS_HOST": truenas_host,
                    "TRUENAS_USER": truenas_user,
                    "TRUENAS_PW": truenas_pw,
                    # TLS verification for those TrueNAS API calls (they carry
                    # TRUENAS_PW). "0" = trust the NAS's self-signed cert, as
                    # before; "1" or a CA bundle path inside the container
                    # once the NAS has a trusted cert.
                    "TRUENAS_VERIFY_SSL": truenas_verify_ssl,
                },
                "ports": [
                    f"{bind_lan}:{port}:{port}",
                    f"{bind_tailnet}:{port}:{port}",
                ],
                "volumes": [
                    # ro: the command: line executes /app/deploy/run.sh, so a
                    # writable /app is code execution in a container holding
                    # TRUENAS_PW (AUDIT C-1).
                    f"{host_root}/app:/app:ro",
                    # The venv is its own volume, owned 3000:3000 mode 700.
                    # At /data/venv (group editors, mode 770) any editor
                    # could replace the interpreter run.sh execs and run code
                    # as the dashboard user with TRUENAS_PW in its env
                    # (AUDIT C-2). Keep it OUT of /data.
                    f"{host_root}/venv:/venv",
                    f"{host_root}/data:/data",
                    # rw for the /project-setup create flow; container runs
                    # as broll:editors, matching setup_tree.py's ownership.
                    f"{DEFAULT_PROJECTS_ROOT}:/projects:rw",
                ],
                "restart": "unless-stopped",
                "healthcheck": healthcheck_config(port),
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


def make_staging_dir(dry_run: bool) -> str:
    """Fresh unpredictable staging dir on the NAS (mode 700, owned by the SSH
    user). A fixed /tmp path could be pre-created world-writable or symlinked
    by any local account and later cp -a'd into /app as root (AUDIT SEC-11).
    """
    if dry_run:
        return "/tmp/ccsync-dashboard-upload.dryrun"
    rc, out, err = run_ssh("mktemp -d /tmp/ccsync-dashboard-upload.XXXXXX")
    staging = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if rc != 0 or not staging.startswith("/tmp/ccsync-dashboard-upload."):
        print(f"FAILED to create staging dir: {err or out}", file=sys.stderr)
        sys.exit(1)
    return staging


def local_manifest() -> tuple[int, int]:
    """(file count, total bytes) of the tree we are about to ship.

    Both halves matter: a partial transfer that wrote every file but
    truncated the last one passes a count-only check (AUDIT INST-31).
    """
    files = list(iter_local_files())
    return len(files), sum(p.stat().st_size for p, _ in files)


def upload_tree(staging_dir: str, dry_run: bool) -> int:
    files = list(iter_local_files())
    if dry_run:
        print(f"[dry-run] would SFTP {len(files)} files from {LOCAL_DASHBOARD_DIR} "
              f"to {staging_dir} on the NAS")
        return len(files)

    host, user, pw = truenas_conn_params()
    client = ssh_client(host, user, pw)
    try:
        sftp = client.open_sftp()
        made: set[str] = set()
        for local, rel in files:
            remote = posixpath.join(staging_dir, rel)
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
    print(f"uploaded {len(files)} files to staging {staging_dir}")
    return len(files)


def count_and_size_cmd(path: str) -> str:
    """Shell printing two lines for `path`: file count, then total bytes.

    `cat | wc -c` rather than `find -printf '%s'` so the check does not
    depend on GNU find; the tree is well under a megabyte.
    """
    q = shell_quote(path)
    return f"find {q} -type f | wc -l; find {q} -type f -exec cat {{}} + | wc -c"


def build_swap_script(root: str, staging: str, new_dir: str, old_dir: str,
                      expected_count: int, expected_bytes: int) -> str:
    """The install itself: build <root>/app.new from staging, verify it
    (count AND bytes), then swap it in with renames only.

    Failure modes and what they leave behind:
      - cp/chown/chmod fails  -> app/ untouched, app.new left for inspection
      - verification fails    -> app/ untouched, exit 8
      - the swap-in mv fails  -> the previous app/ is renamed back, exit 9
    Nothing here ever deletes the running code: it is moved to app.old.<ts>
    and only pruned by a LATER successful install (most recent kept).
    """
    app_q = shell_quote(root + "/app")
    new_q = shell_quote(new_dir)
    old_q = shell_quote(old_dir)
    staged_q = shell_quote(staging)
    return (
        f"set -e; "
        f"rm -rf {new_q}; mkdir -p {new_q}; "
        f"cp -a {staged_q}/. {new_q}/; "
        f"chown -R root:root {new_q}; "
        f"chmod -R u+rwX,go+rX,go-w {new_q}; "
        f"n=$(find {new_q} -type f | wc -l); "
        f"b=$(find {new_q} -type f -exec cat {{}} + | wc -c); "
        f'if [ "$n" -ne {expected_count} ] || [ "$b" -ne {expected_bytes} ]; then '
        f'echo "candidate tree incomplete: $n files/$b bytes, expected '
        f'{expected_count}/{expected_bytes} -- app left untouched" >&2; exit 8; fi; '
        f"mkdir -p {app_q}; "
        # The only step that touches the live dir, and it is a rename.
        f"mv {app_q} {old_q}; "
        f"mv {new_q} {app_q} || {{ mv {old_q} {app_q}; "
        f'echo "swap failed, previous code restored" >&2; exit 9; }}; '
        f"rm -rf {staged_q}"
    )


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
    ap.add_argument("--bind-lan", default=os.environ.get("DASH_BIND_LAN", LAN_BIND_IP),
                    help=f"LAN address to publish the dashboard on, default {LAN_BIND_IP} "
                         f"(or DASH_BIND_LAN). It must be an address the NAS actually has, "
                         f"or Docker refuses to start the app.")
    ap.add_argument("--bind-tailnet",
                    default=os.environ.get("DASH_BIND_TAILNET", TAILNET_BIND_IP),
                    help=f"tailnet address to publish on, default {TAILNET_BIND_IP} "
                         f"(or DASH_BIND_TAILNET)")
    ap.add_argument("--image", default=os.environ.get("DASH_IMAGE", DEFAULT_IMAGE),
                    help=f"container base image, default {DEFAULT_IMAGE} (pinned on "
                         f"purpose; keep it in step with dashboard/deploy/compose.yaml)")
    ap.add_argument("--recreate", action="store_true",
                    help="delete and re-create the app so compose changes (env vars, "
                         "mounts, ports) take effect; host app/ and data/ dirs survive")
    ap.add_argument("--allow-any-host-root", action="store_true",
                    help="allow a --host-root outside /mnt/<pool>/apps/ccsync-dashboard. "
                         "The install REPLACES everything under <host-root>/app as root; "
                         "this flag exists so that can never happen by typo.")
    add_host_key_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)

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
    # "0" keeps today's behaviour (self-signed NAS cert trusted); the dashboard
    # reads the same var (truenas_client._verify_setting).
    truenas_verify_ssl = os.environ.get("TRUENAS_VERIFY_SSL", "0").strip() or "0"
    truenas_host, truenas_user, truenas_pw = truenas_conn_params(dry_run=args.dry_run)
    if args.dry_run:
        # --dry-run prints the whole compose body; the NAS admin password has
        # no business in a terminal scrollback or a pasted bug report.
        truenas_pw = "<TRUENAS_PW-not-shown-in-dry-run>"

    root = args.host_root.rstrip("/")
    if not HOST_ROOT_RE.match(root):
        if not args.allow_any_host_root:
            print(
                f"REFUSING --host-root {root!r}: it is not under "
                f"/mnt/<pool>/apps/ccsync-dashboard.\n"
                f"  This install replaces EVERYTHING under {root}/app as root, so a "
                f"mistyped root (a project tree, a share) would take its contents with "
                f"it.\n"
                f"  Use {DEFAULT_HOST_ROOT} (the default), or pass --allow-any-host-root "
                f"if this really is a deliberate alternate deployment.",
                file=sys.stderr)
            return 1
        print(f"WARNING: --allow-any-host-root given. {root}/app will be REPLACED "
              f"wholesale (its current contents are moved aside to {root}/app.old.<ts>, "
              f"not deleted); {root}/data is left untouched.", file=sys.stderr)

    # Step 1: host dirs. app/ is root-owned and world-readable but NOT
    # group-writable -- editors have shell accounts in group 3001, and a
    # group-writable code dir behind the container's `command: run.sh` was an
    # editor->NAS-admin escalation (AUDIT C-1). The container only ever READS
    # /app (mounted :ro).
    #
    # data/ and venv/ are create-only (contents never touched on re-run) and
    # are owned 3000:3000, NOT 3000:3001. AUDIT C-2: with group `editors` and
    # mode 770, every editor could write into /data -- where run.sh kept the
    # venv it execs `bin/python` from, guarded only by an md5 stamp file in
    # the same directory. Swapping that interpreter was arbitrary code
    # execution as the dashboard user, in a container holding TRUENAS_PW.
    # The venv now has its own volume at 700, and dashboard.db + packages/
    # sit under a /data no editor can traverse.
    rc, _, err = run_ssh(
        'echo "$SUDO_PW" | sudo -S sh -c '
        + shell_quote(
            f"mkdir -p {shell_quote(root + '/app')} {shell_quote(root + '/data')} "
            f"{shell_quote(root + '/venv')} && "
            f"chown root:root {shell_quote(root)} {shell_quote(root + '/app')} && "
            f"chmod 755 {shell_quote(root)} {shell_quote(root + '/app')} && "
            f"chown -R 3000:3000 {shell_quote(root + '/data')} && "
            f"chmod 770 {shell_quote(root + '/data')} && "
            f"chown -R 3000:3000 {shell_quote(root + '/venv')} && "
            f"chmod 700 {shell_quote(root + '/venv')}"
        ),
        dry_run=args.dry_run,
    )
    if rc != 0:
        print(f"FAILED to create host dirs: {err}", file=sys.stderr)
        return 1
    print(f"host dirs ready: {root}/app, {root}/venv, {root}/data")

    # A pre-C-2 deployment has an editor-writable venv sitting inside data/.
    # Move it aside (never delete: no-deletion rule) so run.sh rebuilds a
    # clean one at /venv and nothing keeps executing the old interpreter.
    quarantine = f"{root}/data/venv.quarantined.{time.strftime('%Y%m%d%H%M%S')}"
    retire_old_venv = (
        f"if [ -d {shell_quote(root + '/data/venv')} ]; then "
        f"mv {shell_quote(root + '/data/venv')} {shell_quote(quarantine)} && "
        f"chmod 700 {shell_quote(quarantine)} && "
        f'echo "retired the old editor-writable venv to {quarantine}"; fi'
    )
    run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(retire_old_venv),
            dry_run=args.dry_run)

    # Step 2: upload code to a fresh staging dir, verify the staged copy is
    # COMPLETE, build app.new from it, verify THAT, and only then swap it in.
    # Constraints shaping this (AUDIT INST-31 / D-7):
    #   - No step may leave the live app/ gutted. The old sequence was
    #     `find app -mindepth 1 -delete && cp -a staged/. app/`, so a cp
    #     failure half-way (full dataset, I/O error) left /app empty with
    #     nothing to roll back to. Now the only destructive-looking step is
    #     `mv app app.old.<ts>`, which is a rename: the previous code is
    #     still there, and the swap rolls back if the second mv fails.
    #   - Verification is count AND total bytes against the local manifest:
    #     a transfer that wrote every file but truncated the last one passes
    #     a count-only check.
    #   - Staging comes from mktemp (see make_staging_dir) so no other local
    #     account can pre-plant content that ends up root-copied into /app.
    #   - The swap changes app/'s inode, and the container bind-mounts it, so
    #     the running container keeps serving the OLD inode until it is
    #     restarted. Step 3 always restarts it (docker restart re-resolves
    #     bind mounts) -- a redeploy alone was observed not to, 2026-07-24.
    staging = make_staging_dir(args.dry_run)
    expected = upload_tree(staging, args.dry_run)
    expected_count, expected_bytes = local_manifest()
    new_dir_raw = root + "/app.new"
    old_dir_raw = f"{root}/app.old.{time.strftime('%Y%m%d%H%M%S')}"
    staged_q = shell_quote(staging)

    # Verify the staged upload before anything on the NAS is moved.
    rc, out, err = run_ssh(count_and_size_cmd(staging), dry_run=args.dry_run)
    if not args.dry_run:
        nums = [ln.strip() for ln in out.strip().splitlines() if ln.strip().isdigit()]
        staged_count = int(nums[0]) if rc == 0 and len(nums) >= 2 else -1
        staged_bytes = int(nums[1]) if rc == 0 and len(nums) >= 2 else -1
        if staged_count != expected_count or staged_bytes != expected_bytes:
            print(f"FAILED: staged tree does not match what was sent "
                  f"({staged_count} files/{staged_bytes} bytes on the NAS vs "
                  f"{expected_count}/{expected_bytes} locally) -- {root}/app is "
                  f"untouched (staging left at {staging} for inspection)",
                  file=sys.stderr)
            return 1
        print(f"staged tree verified: {staged_count} files, {staged_bytes} bytes")
    if expected != expected_count:  # upload_tree and the manifest must agree
        print(f"FAILED: internal manifest mismatch ({expected} vs {expected_count})",
              file=sys.stderr)
        return 1

    swap = build_swap_script(root, staging, new_dir_raw, old_dir_raw,
                             expected_count, expected_bytes)
    rc, _, err = run_ssh(
        'echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(swap),
        dry_run=args.dry_run,
    )
    if rc != 0:
        print(f"FAILED to install code into {root}/app: {err.strip()[:500]}\n"
              f"  The previously installed code is still in place ({root}/app was only "
              f"replaced by an atomic rename, and that rename rolls back).\n"
              f"  Staging is left at {staging} and the candidate tree at {new_dir_raw} "
              f"for inspection.",
              file=sys.stderr)
        return 1
    print(f"installed code: {root}/app (previous code kept at {old_dir_raw})")

    # Prune earlier backups now that THIS install has succeeded -- always
    # keeping the most recent one, i.e. the copy of the code we just
    # replaced. Non-fatal: a failure here changes nothing about the deploy.
    prune = (
        f"ls -1d {shell_quote(root)}/app.old.* 2>/dev/null | sort | head -n -1 "
        f"| xargs -r rm -rf"
    )
    run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(prune), dry_run=args.dry_run)

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
            print("NOTE: only the CODE was updated. Compose-level changes -- bind "
                  "addresses (--bind-lan/--bind-tailnet), image tag, healthcheck, env "
                  "vars -- need --recreate to take effect (pass DASH_REPORT_TOKEN and "
                  "DASH_SESSION_SECRET again when you do).")
        else:
            print(f"NOTE: docker restart failed ({err.strip()[:200]}); restart the "
                  f"{APP_NAME!r} app from the TrueNAS UI to pick up the new code.")
        return 0

    body = {
        "custom_app": True,
        "app_name": APP_NAME,
        "custom_compose_config": compose_config(
            args.port, root, args.syncthing_gui_url, api_key, token,
            session_secret, admin_users, truenas_host, truenas_user, truenas_pw,
            truenas_verify_ssl=truenas_verify_ssl,
            bind_lan=args.bind_lan, bind_tailnet=args.bind_tailnet,
            image=args.image,
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
