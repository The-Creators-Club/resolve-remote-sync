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
       <host-root>/broll-web -- the broll-platform web/ tree (shipped in step
                             2b); root:root 755, mounted :ro like app/.
     ...and, when the b-roll UI is enabled, the b-roll DATA root -- which is
     the shared archive itself, /mnt/tank/.../Assets/B-roll Archive -- as
     broll:editors 2770 (setgid), the same posture setup_tree.py gives
     Projects/. Deliberately NOT 770/group-3000: editors browse that tree
     over SMB as P:\\Assets\\B-roll Archive and must not be locked out of it.
  2. Upload the local dashboard/ tree via SFTP to a fresh mktemp staging dir,
     verify the staged copy against the local manifest (file count AND total
     byte size), build <host-root>/app.new from it, verify that too, and only
     then swap it into place:
         mv app app.old.<ts> && mv app.new app
     Any failure before the swap leaves the live app/ untouched; a failed
     swap rolls back. The previous app.old.<ts> backups are pruned (most
     recent kept) only after a LATER install has succeeded.
     Excludes .venv, __pycache__, *.pyc.
  2b. When DASH_BROLL_ENABLED=1 (the default): ship the broll-platform web/
     tree into <host-root>/broll-web by exactly the same staged-verify-swap
     route. The container mounts that dir read-only at /broll-app and puts it
     on PYTHONPATH; without this step it is EMPTY, the import fails, and the
     b-roll UI is silently absent behind a green healthcheck. The source is
     BROLL_WEB_SRC, defaulting to ../../broll-platform/web next to this repo;
     if it is missing this script FAILS rather than deploying a feature that
     cannot work. Set DASH_BROLL_ENABLED=0 to skip the b-roll UI entirely.
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
TRUENAS_VERIFY_SSL (default "0" = trust the NAS's self-signed cert),
DASH_BROLL_ENABLED (default "1"; "0" deploys without the b-roll UI),
BROLL_INGEST_TOKEN (REQUIRED when DASH_BROLL_ENABLED=1 -- it guards a write
path the indexer reaches with no session; `openssl rand -hex 24`),
BROLL_WEB_SRC (the broll-platform web/ checkout to ship, default
../../broll-platform/web relative to this repo).

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
    DEFAULT_BROLL_ARCHIVE_ROOT, DEFAULT_PROJECTS_ROOT, add_host_key_arg, ok,
    require_env, run_ssh,
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
# The b-roll app lives in its OWN repo; this script ships a checkout of it into
# <host-root>/broll-web, which the container mounts read-only at /broll-app.
# Default location: a sibling of this repo. Override with BROLL_WEB_SRC.
DEFAULT_BROLL_WEB_DIR = Path(__file__).resolve().parents[2] / "broll-platform" / "web"
# Its tests/, git metadata and local venv have no business on the NAS -- the
# container only ever imports app/ and serves static/.
BROLL_EXCLUDE_DIRS = EXCLUDE_DIRS | {".git", ".github", "tests", "node_modules"}
# Minimum ingest-token strength, mirroring
# ccsync_dashboard.broll.check_ingest_token -- the dashboard refuses to START
# with a weaker one, and finding that out from a crash-looping container is a
# worse experience than finding it out here, before anything is uploaded.
MIN_INGEST_TOKEN_CHARS = 24
PLACEHOLDER_INGEST_TOKENS = {
    "replace_me", "replaceme", "replace-me", "change_me", "changeme", "change-me",
    "changethis", "todo", "tbd", "secret", "password", "token", "test", "example",
    "your-token-here", "xxx", "none", "null",
}
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
                   image: str = DEFAULT_IMAGE,
                   broll_enabled: str = "1", broll_ingest_token: str = "",
                   broll_creators_shares: str = "mofa-disaster") -> dict:
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
                    # b-roll search UI, mounted in-process at /broll so
                    # editors reach it on this same host, port and login.
                    # Must stay in step with deploy/compose.yaml -- the two
                    # describe the same container and drift between them is
                    # only ever discovered in production.
                    "DASH_BROLL_ENABLED": broll_enabled,
                    "BROLL_DATA_ROOT": "/broll-data",
                    "BROLL_SHARES": "broll:Main b-roll archive",
                    "BROLL_CREATORS_SHARES": broll_creators_shares,
                    # Mandatory when the mount is on, and enforced twice: this
                    # script refuses to deploy without a strong one, and the
                    # dashboard refuses to start. Blank used to mean the b-roll
                    # app's own guard fell back to dev mode, where any
                    # logged-in editor could rewrite the archive index.
                    "BROLL_INGEST_TOKEN": broll_ingest_token,
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
                    # b-roll: code read-only (same posture as /app), data rw.
                    f"{host_root}/broll-web:/broll-app:ro",
                    # DATA_ROOT is the shared archive itself (beside Projects/
                    # under Creators_Club), not a private copy -- one set of
                    # media serves both the search UI and editors' timelines.
                    f"{DEFAULT_BROLL_ARCHIVE_ROOT}:/broll-data:rw",
                ],
                "restart": "unless-stopped",
                "healthcheck": healthcheck_config(port),
            }
        }
    }


# Every environment variable whose VALUE is a credential and which ends up in
# the compose body this script prints. --dry-run prints that body in full, on
# purpose (the admin needs to eyeball paths, ports, mounts and bind addresses
# before a real run) -- so the secrets, and only the secrets, are replaced with
# placeholders first. Keep this list in step with the secret-bearing keys in
# compose_config(); everything else in that body is configuration and stays
# readable, because a dry-run that hides the thing you are checking is useless.
SECRET_ENV_VARS = (
    "SYNCTHING_API_KEY",
    "DASH_REPORT_TOKEN",
    "DASH_SESSION_SECRET",
    "BROLL_INGEST_TOKEN",
    "TRUENAS_PW",
)


def dry_run_mask(name: str, value: str) -> str:
    """The placeholder a secret is printed as in --dry-run.

    Still distinguishes "configured" from "not configured": whether a secret is
    SET is not itself a secret, and it is the single most useful thing a dry-run
    can tell you about one (a blank DASH_SESSION_SECRET logs the whole fleet out
    on deploy). Its value is never printed.
    """
    return f"<{name}-not-shown-in-dry-run>" if value else f"<{name}-unset-dry-run>"


def resolve_compose_secrets(dry_run: bool, broll_ingest_token: str) -> dict:
    """The secret-bearing compose values: real ones for a real deploy, masked
    ones for --dry-run.

    ORDER MATTERS, and this function is why it is explicit. Everything that
    VALIDATES a secret (weak_ingest_token on BROLL_INGEST_TOKEN, require_env on
    the three mandatory ones) runs against the real value -- masking happens
    here, afterwards, on the way into the printed body only. A placeholder must
    never be able to satisfy or trip a check that the real value would not:
    `<BROLL_INGEST_TOKEN-unset-dry-run>` is 34 characters and would sail past a
    length check it was never meant to reach.

    TRUENAS_PW is masked here for the compose body alone; run_ssh and
    truenas_api each re-read it from the environment for their own use, so a
    real deploy is unaffected.
    """
    if dry_run:
        return {name: dry_run_mask(name, os.environ.get(name, "").strip())
                for name in SECRET_ENV_VARS}
    return {
        "SYNCTHING_API_KEY": require_env("SYNCTHING_API_KEY"),
        "DASH_REPORT_TOKEN": require_env("DASH_REPORT_TOKEN"),
        # Stable across deploys: rotating it logs every editor out.
        "DASH_SESSION_SECRET": require_env("DASH_SESSION_SECRET"),
        # Already validated by weak_ingest_token when the b-roll UI is on, and
        # legitimately blank when it is off.
        "BROLL_INGEST_TOKEN": broll_ingest_token,
        "TRUENAS_PW": require_env("TRUENAS_PW"),
    }


def broll_web_source() -> Path:
    """The broll-platform web/ checkout to ship. BROLL_WEB_SRC overrides."""
    raw = os.environ.get("BROLL_WEB_SRC", "").strip()
    return Path(raw) if raw else DEFAULT_BROLL_WEB_DIR


def weak_ingest_token(token: str) -> str | None:
    """None if `token` may guard the b-roll ingest write path, else the reason.

    Mirrors ccsync_dashboard.broll.check_ingest_token; keep the two in step.
    """
    token = (token or "").strip()
    if not token:
        return "is not set"
    if token.lower() in PLACEHOLDER_INGEST_TOKENS:
        return f"is the placeholder {token!r} (a value that is in the public repo)"
    if len(token) < MIN_INGEST_TOKEN_CHARS:
        return f"is only {len(token)} characters; at least {MIN_INGEST_TOKEN_CHARS} are required"
    if len(set(token)) < 8:
        return "has too little variety to be a random secret"
    return None


def iter_local_files(base: Path = LOCAL_DASHBOARD_DIR, excludes: set = EXCLUDE_DIRS):
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if any(part in excludes for part in rel.parts) or path.suffix == ".pyc":
            continue
        if path.is_file():
            yield path, rel.as_posix()


def make_staging_dir(dry_run: bool, slug: str = "ccsync-dashboard-upload") -> str:
    """Fresh unpredictable staging dir on the NAS (mode 700, owned by the SSH
    user). A fixed /tmp path could be pre-created world-writable or symlinked
    by any local account and later cp -a'd into /app as root (AUDIT SEC-11).
    """
    if dry_run:
        return f"/tmp/{slug}.dryrun"
    rc, out, err = run_ssh(f"mktemp -d /tmp/{slug}.XXXXXX")
    staging = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if rc != 0 or not staging.startswith(f"/tmp/{slug}."):
        print(f"FAILED to create staging dir: {err or out}", file=sys.stderr)
        sys.exit(1)
    return staging


def local_manifest(base: Path = LOCAL_DASHBOARD_DIR,
                   excludes: set = EXCLUDE_DIRS) -> tuple[int, int]:
    """(file count, total bytes) of the tree we are about to ship.

    Both halves matter: a partial transfer that wrote every file but
    truncated the last one passes a count-only check (AUDIT INST-31).
    """
    files = list(iter_local_files(base, excludes))
    return len(files), sum(p.stat().st_size for p, _ in files)


def upload_tree(staging_dir: str, dry_run: bool, base: Path = LOCAL_DASHBOARD_DIR,
                excludes: set = EXCLUDE_DIRS) -> int:
    files = list(iter_local_files(base, excludes))
    if dry_run:
        print(f"[dry-run] would SFTP {len(files)} files from {base} "
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
                      expected_count: int, expected_bytes: int,
                      target_dir: str | None = None) -> str:
    """The install itself: build <root>/app.new from staging, verify it
    (count AND bytes), then swap it in with renames only.

    `target_dir` defaults to <root>/app; the b-roll code ships to
    <root>/broll-web through this same script, so both trees get the same
    never-gut-the-live-directory guarantees.

    Failure modes and what they leave behind:
      - cp/chown/chmod fails  -> app/ untouched, app.new left for inspection
      - verification fails    -> app/ untouched, exit 8
      - the swap-in mv fails  -> the previous app/ is renamed back, exit 9
    Nothing here ever deletes the running code: it is moved to app.old.<ts>
    and only pruned by a LATER successful install (most recent kept).
    """
    app_q = shell_quote(target_dir if target_dir is not None else root + "/app")
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


def install_tree(root: str, target_name: str, source: Path, dry_run: bool,
                 excludes: set = EXCLUDE_DIRS,
                 staging_slug: str = "ccsync-dashboard-upload") -> bool:
    """Ship `source` into <root>/<target_name>. True on success.

    Upload to a fresh staging dir, verify the staged copy is COMPLETE, build
    <target>.new from it, verify THAT, and only then swap it in. Constraints
    shaping this (AUDIT INST-31 / D-7):
      - No step may leave the live tree gutted. The old sequence was
        `find app -mindepth 1 -delete && cp -a staged/. app/`, so a cp failure
        half-way (full dataset, I/O error) left /app empty with nothing to roll
        back to. Now the only destructive-looking step is `mv app app.old.<ts>`,
        which is a rename: the previous code is still there, and the swap rolls
        back if the second mv fails.
      - Verification is count AND total bytes against the local manifest: a
        transfer that wrote every file but truncated the last one passes a
        count-only check.
      - Staging comes from mktemp (see make_staging_dir) so no other local
        account can pre-plant content that ends up root-copied into /app.
      - The swap changes the directory's inode, and the container bind-mounts
        it, so the running container keeps serving the OLD inode until it is
        restarted. Step 3 always restarts it (docker restart re-resolves bind
        mounts) -- a redeploy alone was observed not to, 2026-07-24.

    Used for both the dashboard tree and the b-roll app's tree: two mounts with
    the same posture (root-owned, world-readable, :ro in the container) deserve
    the same install guarantees, and the b-roll one is the mount whose silent
    emptiness made /broll disappear without a single error.
    """
    target = f"{root}/{target_name}"
    staging = make_staging_dir(dry_run, staging_slug)
    expected = upload_tree(staging, dry_run, source, excludes)
    expected_count, expected_bytes = local_manifest(source, excludes)
    if expected_count == 0:
        print(f"FAILED: {source} contains no files to ship -- refusing to install an "
              f"empty {target}", file=sys.stderr)
        return False
    new_dir_raw = f"{target}.new"
    old_dir_raw = f"{target}.old.{time.strftime('%Y%m%d%H%M%S')}"

    # Verify the staged upload before anything on the NAS is moved.
    rc, out, err = run_ssh(count_and_size_cmd(staging), dry_run=dry_run)
    if not dry_run:
        nums = [ln.strip() for ln in out.strip().splitlines() if ln.strip().isdigit()]
        staged_count = int(nums[0]) if rc == 0 and len(nums) >= 2 else -1
        staged_bytes = int(nums[1]) if rc == 0 and len(nums) >= 2 else -1
        if staged_count != expected_count or staged_bytes != expected_bytes:
            print(f"FAILED: staged tree does not match what was sent "
                  f"({staged_count} files/{staged_bytes} bytes on the NAS vs "
                  f"{expected_count}/{expected_bytes} locally) -- {target} is "
                  f"untouched (staging left at {staging} for inspection)",
                  file=sys.stderr)
            return False
        print(f"staged tree verified: {staged_count} files, {staged_bytes} bytes")
    if expected != expected_count:  # upload_tree and the manifest must agree
        print(f"FAILED: internal manifest mismatch ({expected} vs {expected_count})",
              file=sys.stderr)
        return False

    swap = build_swap_script(root, staging, new_dir_raw, old_dir_raw,
                             expected_count, expected_bytes, target_dir=target)
    rc, _, err = run_ssh(
        'echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(swap),
        dry_run=dry_run,
    )
    if rc != 0:
        print(f"FAILED to install code into {target}: {err.strip()[:500]}\n"
              f"  The previously installed code is still in place ({target} was only "
              f"replaced by an atomic rename, and that rename rolls back).\n"
              f"  Staging is left at {staging} and the candidate tree at {new_dir_raw} "
              f"for inspection.",
              file=sys.stderr)
        return False
    print(f"installed code: {target} (previous code kept at {old_dir_raw})")

    # Prune earlier backups now that THIS install has succeeded -- always
    # keeping the most recent one, i.e. the copy of the code we just
    # replaced. Non-fatal: a failure here changes nothing about the deploy.
    # -d '\n': xargs default splitting breaks on any whitespace, so a space
    # anywhere in the root (HOST_ROOT_RE permits one) would hand rm -rf path
    # fragments and silently stop pruning forever.
    prune = (
        f"ls -1d {shell_quote(target)}.old.* 2>/dev/null | sort | head -n -1 "
        f"| xargs -r -d '\\n' rm -rf"
    )
    run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(prune), dry_run=dry_run)
    return True


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

    # b-roll pre-flight, BEFORE anything is uploaded or created. Two ways this
    # feature used to ship broken and silent, and neither is detectable from a
    # healthcheck: an empty broll-web (nothing ever copied the app in), and an
    # ingest token that was blank or the literal "REPLACE_ME" from the repo.
    # Both are refusals now, and both are refusals HERE, where the operator is
    # still looking at a terminal.
    broll_enabled = os.environ.get("DASH_BROLL_ENABLED", "1").strip() or "1"
    broll_src = broll_web_source()
    broll_ingest_token = os.environ.get("BROLL_INGEST_TOKEN", "").strip()
    # A --dry-run reports both problems instead of returning 1: it touches
    # nothing, and it must stay runnable on a machine that has neither the
    # b-roll checkout nor the production secrets (the same "only works on one
    # workstation" trap the b-roll tests fell into). A real run refuses.
    ship_broll = broll_enabled == "1"
    if broll_enabled == "1":
        if not (broll_src / "app" / "main.py").is_file():
            print(
                f"{'[dry-run] would FAIL' if args.dry_run else 'FAILED'}: "
                f"DASH_BROLL_ENABLED=1 but no b-roll app at {broll_src}\n"
                f"  (looked for {broll_src / 'app' / 'main.py'}).\n"
                f"  The container mounts <host-root>/broll-web read-only at /broll-app "
                f"and imports app.main from it; deploying without shipping that tree "
                f"gives a dashboard whose /broll silently does not exist.\n"
                f"  Point BROLL_WEB_SRC at the broll-platform web/ checkout, or set "
                f"DASH_BROLL_ENABLED=0 to deploy without the b-roll UI.",
                file=sys.stderr)
            if not args.dry_run:
                return 1
            ship_broll = False
        problem = weak_ingest_token(broll_ingest_token)
        if problem:
            print(
                f"{'[dry-run] would FAIL' if args.dry_run else 'FAILED'}: "
                f"DASH_BROLL_ENABLED=1 but BROLL_INGEST_TOKEN {problem}.\n"
                f"  /broll/api/ingest/* is a WRITE path the indexer reaches with no "
                f"session at all -- this token is the only thing guarding it, and the "
                f"dashboard refuses to start without a strong one.\n"
                f"  Generate one with `openssl rand -hex 24`, or set "
                f"DASH_BROLL_ENABLED=0.",
                file=sys.stderr)
            if not args.dry_run:
                return 1

    # Secrets, resolved in one place and AFTER every check that needs the real
    # value (the b-roll pre-flight above). --dry-run prints the entire compose
    # body, which is the point of it -- but a token pasted into a bug report or
    # left in terminal scrollback is a live credential, and four of the five
    # here used to be printed in the clear while only TRUENAS_PW was masked.
    secrets = resolve_compose_secrets(args.dry_run, broll_ingest_token)
    api_key = secrets["SYNCTHING_API_KEY"]
    token = secrets["DASH_REPORT_TOKEN"]
    session_secret = secrets["DASH_SESSION_SECRET"]
    broll_ingest_token = secrets["BROLL_INGEST_TOKEN"]
    truenas_pw = secrets["TRUENAS_PW"]
    admin_users = os.environ.get("DASH_ADMIN_USERS", "truenas_admin")
    # "0" keeps today's behaviour (self-signed NAS cert trusted); the dashboard
    # reads the same var (truenas_client._verify_setting).
    truenas_verify_ssl = os.environ.get("TRUENAS_VERIFY_SSL", "0").strip() or "0"
    # Host and user only -- neither is a secret, and both appear in the printed
    # ssh lines anyway. The password for the compose body comes from `secrets`;
    # run_ssh and truenas_api re-read TRUENAS_PW themselves for their own calls.
    truenas_host, truenas_user, _ = truenas_conn_params(dry_run=args.dry_run)

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
            f"{shell_quote(root + '/venv')} {shell_quote(root + '/broll-web')} && "
            f"chown root:root {shell_quote(root)} {shell_quote(root + '/app')} && "
            f"chmod 755 {shell_quote(root)} {shell_quote(root + '/app')} && "
            f"chown -R 3000:3000 {shell_quote(root + '/data')} && "
            f"chmod 770 {shell_quote(root + '/data')} && "
            f"chown -R 3000:3000 {shell_quote(root + '/venv')} && "
            f"chmod 700 {shell_quote(root + '/venv')} && "
            # b-roll CODE: root-owned and world-readable, mounted :ro -- same
            # posture as app/, so the process running it cannot rewrite it.
            # (There is deliberately no <root>/broll-data any more: nothing
            # ever mounted it. The b-roll DATA root is the shared archive,
            # prepared separately below.)
            f"chown root:root {shell_quote(root + '/broll-web')} && "
            f"chmod 755 {shell_quote(root + '/broll-web')}"
        ),
        dry_run=args.dry_run,
    )
    if rc != 0:
        print(f"FAILED to create host dirs: {err}", file=sys.stderr)
        return 1
    print(f"host dirs ready: {root}/app, {root}/venv, {root}/data, {root}/broll-web")

    # The b-roll DATA root: the one the compose file actually bind-mounts at
    # /broll-data. It is NOT under <host-root> -- it is the shared archive
    # itself, beside Projects/ under Creators_Club, which is what makes it
    # P:\Assets\B-roll Archive on an editor's machine. Two things follow:
    #
    #   - It must exist and be writable by the container's uid BEFORE the app
    #     starts. Left to Docker, the bind source is auto-created root:root
    #     0755, the container (3000:3001) cannot create broll.db in it, and
    #     every /broll request answers "unable to open database file".
    #   - Its posture is Projects', not /data's: broll:editors 2770 setgid,
    #     exactly what setup_tree.py applies. It is emphatically NOT chmod 770
    #     group-3000 -- that is the mode for a private app directory, and this
    #     tree is browsed over SMB by the same editors whose proxies live in
    #     it. That change would have locked them out of their own archive.
    #
    # Only the archive root and the four directories the app itself creates are
    # touched, non-recursively: the tree is tens of gigabytes and an existing
    # archive's contents are none of this script's business. Pre-creating those
    # four also side-steps run.sh's `umask 077`, under which the app would make
    # them 0700/uid-3000 and invisible over SMB.
    #
    # chmod is non-fatal: TrueNAS datasets with aclmode=restricted (NFSv4 ACLs)
    # refuse chmod outright, even for root -- setup_tree.py handles it the same
    # way. Ownership still applies. NOTE FOR THE NAS: whether these mode bits
    # survive on THIS dataset is unverified from here; check with `ls -ld` (and
    # `getfacl`) after the first install.
    if broll_enabled == "1":
        archive_dirs = [DEFAULT_BROLL_ARCHIVE_ROOT] + [
            f"{DEFAULT_BROLL_ARCHIVE_ROOT}/{d}"
            for d in ("proxies", "sprites", "posters", "sheets")
        ]
        quoted = " ".join(shell_quote(d) for d in archive_dirs)
        rc, _, err = run_ssh(
            'echo "$SUDO_PW" | sudo -S sh -c '
            + shell_quote(
                f"mkdir -p {quoted} && chown 3000:3001 {quoted} && "
                f"{{ chmod 2770 {quoted} || "
                f'echo "NOTE: chmod blocked on this dataset (likely ZFS '
                f'aclmode=restricted) -- ownership above still applied"; }}'
            ),
            dry_run=args.dry_run,
        )
        if rc != 0:
            print(f"FAILED to prepare the b-roll archive root "
                  f"{DEFAULT_BROLL_ARCHIVE_ROOT}: {err}", file=sys.stderr)
            return 1
        print(f"b-roll data root ready: {DEFAULT_BROLL_ARCHIVE_ROOT} "
              f"(broll:editors 2770, same as Projects/)")

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
    rc, _, err = run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(retire_old_venv),
                         dry_run=args.dry_run)
    if not args.dry_run and rc != 0:
        # A failed mv leaves the editor-writable venv (the C-2 hazard) in
        # place; reporting success here would defeat the quarantine's point.
        print(f"FAILED to retire the old editor-writable venv at "
              f"{root}/data/venv: {err.strip() or 'mv/chmod failed'}",
              file=sys.stderr)
        return 1

    # Step 2: ship the dashboard code (see install_tree for the guarantees).
    if not install_tree(root, "app", LOCAL_DASHBOARD_DIR, args.dry_run):
        return 1

    # Step 2b: ship the b-roll app's own repo into broll-web. Without this the
    # directory the container mounts at /broll-app is EMPTY, `from app.main
    # import app` raises ModuleNotFoundError, the mount is skipped, and the
    # operator gets a green healthcheck with a missing feature.
    if ship_broll:
        if not install_tree(root, "broll-web", broll_src, args.dry_run,
                            excludes=BROLL_EXCLUDE_DIRS,
                            staging_slug="ccsync-brollweb-upload"):
            return 1

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
            broll_enabled=broll_enabled,
            # Validated in the pre-flight above (weak_ingest_token) against the
            # REAL value, and masked afterwards for --dry-run only: the
            # dashboard refuses to START with a blank, placeholder or short
            # one, because this guards a write path no session protects.
            broll_ingest_token=broll_ingest_token,
            broll_creators_shares=os.environ.get(
                "BROLL_CREATORS_SHARES", "mofa-disaster"),
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
