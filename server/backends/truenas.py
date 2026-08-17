"""The TrueNAS SCALE backend: this repo's production platform.

Every body in here was lifted OUT of the scripts on 2026-08-17 (WP3 step 1 of
docs/SYNOLOGY_PORT_PLAN.md) and is unchanged in behaviour -- same API calls,
same order, same printed lines, same return values, same dry-run semantics.
The scripts still own their CLI and their reporting; what moved is only the
part that would be different on another NAS:

  install_dashboard_app.py  app_installed, restart_dashboard_container, the
                            POST /api/v2.0/app {custom_app...} / DELETE /app/id
                            block, HOST_ROOT_RE, the ix-<app>-<service>-1
                            container naming, the LAN/tailnet bind defaults
  install_syncthing_app.py  the whole catalog install
  setup_editor_account.py   find_group/ensure_group/find_user, the /user
                            create+update calls, filesystem.setperm and the
                            StrictModes verification
  setup_tree.py             the chown -R / chmod 2770 pair
  check_health.py           `docker exec tailscale tailscale status --json`

Calls into the NAS go through common.ScriptCalls so they resolve to the
CALLING SCRIPT's own `truenas_api` / `run_ssh` / `wait_for_job` names -- read
that class's docstring before "simplifying" it.
"""
from __future__ import annotations

import re
import sys

import common
from backends.base import UnsupportedOnBackend

# The install replaces everything under <host-root>/app, as root. Bound that
# to the one location this app is ever deployed to, so a mistyped --host-root
# cannot point the replace at a project tree (AUDIT DEL-9).
HOST_ROOT_RE = re.compile(r"^/mnt/[^/]+/apps/ccsync-dashboard(/[^/]+)*$")

# Host interfaces the dashboard binds to (mirrored by dashboard/deploy/
# compose.yaml, which this repo renders from the same values): LAN for the
# base rig, tailnet for remote editors. Never 0.0.0.0 -- a new NAS interface
# must not silently expose the dashboard.
#
# Blank since 2026-08-17: these were this fleet's own 192.168.0.102 /
# 100.71.216.3, which is the first thing a second site would have had to fork
# (COMMERCIAL_READINESS.md item 10). They come from site.toml now, and a blank
# one is refused by dash_binds() rather than defaulted -- an address the NAS
# does not have makes Docker fail the app with "cannot assign requested
# address", asynchronously, long after the create returns 200.
DEFAULT_LAN_BIND = common.site_value("net", "bind_lan")
DEFAULT_TAILNET_BIND = common.site_value("net", "bind_tailnet")

# Syncthing catalog install (install_syncthing_app.py's constants).
CATALOG = "TRUENAS"
TRAIN = "stable"
SYNCTHING_APP_NAME = "syncthing"
# Fields this backend requires to be present on the catalog entry before it
# will trust its own assumed values payload. If TrueNAS's catalog API shape has
# changed, one or more of these will be missing and the install stops rather
# than guessing.
EXPECTED_CATALOG_FIELDS = ("name", "latest_version")

# sshd StrictModes rejects a home dir that is group- or world-writable, or
# not owned by the user logging in. 0700 satisfies both and matches what
# TrueNAS already does for the .ssh subdirectory it creates.
HOME_MODE = "700"


class TrueNASBackend:
    """kind="truenas". See the module docstring."""

    kind = "truenas"
    host_root_re = HOST_ROOT_RE

    def __init__(self, calls: common.ScriptCalls | None = None,
                 app_name: str = "ccsync-dashboard"):
        self.calls = calls or common.ScriptCalls()
        self.app_name = app_name

    @property
    def dashboard_container(self) -> str:
        # Compose name convention on TrueNAS Apps: ix-<app_name>-<service>-1.
        return f"ix-{self.app_name}-dashboard-1"

    # ----------------------------------------------------------------------
    # The container stack (TrueNAS Apps: custom_app + redeploy)
    # ----------------------------------------------------------------------

    def app_installed(self, app_name: str, dry_run: bool) -> bool | None:
        """Is `app_name` installed? None means the question could not be answered.

        SERVER-8 (2026-08-14): this used to sys.exit(1) on a failed GET /app, and
        it runs in step 3 -- after the `app` swap -- so that exit skipped
        fail_after_app_swap's restart and left the container on app.old.<ts>.
        The tri-state lets main() route it like every other post-swap failure.
        """
        # No query-filters param: the 25.10 middleware was observed returning []
        # for a filtered GET /app even when the app exists (2026-07-24 live run),
        # so fetch the full list and filter client-side.
        resp = self.calls.api("GET", "/app", dry_run=dry_run)
        if dry_run:
            return False
        if not self.calls.ok(resp):
            print(f"FAILED to query installed apps: HTTP {resp.status_code} {resp.text}",
                  file=sys.stderr)
            return None
        return any(a.get("name") == app_name for a in resp.json())

    def delete_app(self, app_name: str, dry_run: bool) -> tuple[bool, str]:
        """DELETE /app/id/<name>, waiting on the job it returns.

        Returns (ok, message-to-print): the caller prints the message verbatim,
        because the two failures read differently and both wordings predate the
        move (2026-08-17).
        """
        resp = self.calls.api("DELETE", f"/app/id/{app_name}",
                              json_body={"remove_ix_volumes": False}, dry_run=dry_run)
        if dry_run:
            return True, ""
        if not self.calls.ok(resp):
            return False, (f"FAILED to delete app for --recreate: "
                           f"HTTP {resp.status_code} {resp.text}")
        try:
            job_id = resp.json()
        except ValueError:
            job_id = None
        if isinstance(job_id, int):
            state, job_err = self.calls.wait_for_job(job_id, timeout=180)
            if state != "SUCCESS":
                return False, f"FAILED: app delete job ended {state}: {job_err}"
        return True, ""

    def restart_stack(self, dry_run: bool) -> tuple[bool, str]:
        """`docker restart` the dashboard container. Returns (ok, stderr).

        /app/redeploy was observed NOT restarting the container on TrueNAS 25.10
        (2026-07-24: a stale process kept serving old in-memory code), so the
        restart is done directly.
        """
        # SERVER-1: guarded because fail_after_app_swap calls this ON a failure
        # path -- a transport error raising out of the restart would turn the fix
        # for OPS-2 back into the traceback OPS-2 was.
        rc, _out, err = self.calls.ssh_guarded(
            f'echo "$SUDO_PW" | sudo -S docker restart '
            f'{common.shell_quote(self.dashboard_container)}',
            dry_run, 120,
        )
        return (dry_run or rc == 0), err

    def container_exec(self, container: str, argv: str,
                       dry_run: bool) -> tuple[int, str, str]:
        """`docker exec <container> <argv>` as root over SSH."""
        return self.calls.ssh(
            f'echo "$SUDO_PW" | sudo -S -p "" docker exec {container} {argv}',
            dry_run=dry_run)

    def dash_binds(self, port: int, bind_lan: str = "",
                   bind_tailnet: str = "") -> list[tuple[str, str]]:
        """(env var, address) for each interface the dashboard publishes on."""
        lan = common.require_site_value(bind_lan or DEFAULT_LAN_BIND,
                                        "[net] bind_lan", "--bind-lan")
        tailnet = common.require_site_value(bind_tailnet or DEFAULT_TAILNET_BIND,
                                            "[net] bind_tailnet", "--bind-tailnet")
        return [("DASH_BIND_LAN", lan), ("DASH_BIND_TAILNET", tailnet)]

    def sftp_path(self, path: str) -> str:
        """Identity: TrueNAS's sshd serves the real filesystem (see base)."""
        return path

    def deploy_stack(self, app_name: str, compose: dict, port: int,
                     dry_run: bool, compose_yaml: str = "",
                     env: dict | None = None) -> int:
        """POST /api/v2.0/app {custom_app: true, custom_compose_config: ...}.

        `compose_yaml`/`env` are the Synology half of the interface and are
        ignored here -- the middleware stores the dict itself (2026-08-17).

        Lifted verbatim from install_dashboard_app.main() step 3, prints and
        all: the two failure messages below are the operator's fallback route
        and the wait is SERVER-2.
        """
        body = {
            "custom_app": True,
            "app_name": app_name,
            "custom_compose_config": compose,
        }
        resp = self.calls.api("POST", "/app", json_body=body, dry_run=dry_run)
        if dry_run:
            print(f"[dry-run] would create custom app {app_name} on port {port}")
            return 0
        if not self.calls.ok(resp):
            print(f"FAILED to create custom app: HTTP {resp.status_code} {resp.text}",
                  file=sys.stderr)
            print("Manual fallback: TrueNAS UI > Apps > Discover Apps > (...) > Install via "
                  "YAML, paste dashboard/deploy/compose.yaml and fill in SYNCTHING_API_KEY "
                  "and DASH_REPORT_TOKEN.", file=sys.stderr)
            return 1

        # SERVER-2 (2026-08-14): a 2xx here only means the create job was ACCEPTED --
        # /app returns a job id and brings the compose up asynchronously (AUDIT
        # INST-24, and the --recreate DELETE above already waits the same way). The
        # failures this hides are the ones this script's own docstring names: a
        # stale --bind-lan/--bind-tailnet makes Docker refuse to start the app with
        # "cannot assign requested address", and the image pull can fail. Printing
        # "installed custom app" and exiting 0 for either is the exit-code-lies class
        # of OPS-4.
        try:
            job_id = resp.json()
        except ValueError:
            job_id = None
        if isinstance(job_id, int):
            print(f"app create job {job_id} accepted; waiting for it to finish "
                  f"(the image pull can take a few minutes)...")
            state, job_err = self.calls.wait_for_job(job_id, timeout=900, poll=5)
            if state != "SUCCESS":
                print(f"FAILED: app create job {job_id} ended {state}: {job_err}",
                      file=sys.stderr)
                print(f"A bind address the NAS does not have (--bind-lan/--bind-tailnet) "
                      f"fails HERE, not on the POST: Docker refuses to start the app with "
                      f"'cannot assign requested address'. Check Apps > {app_name} in the "
                      f"TrueNAS UI -- a partially created app may need deleting before "
                      f"re-running this script.", file=sys.stderr)
                print("Manual fallback: TrueNAS UI > Apps > Discover Apps > (...) > Install "
                      "via YAML, paste dashboard/deploy/compose.yaml and fill in "
                      "SYNCTHING_API_KEY and DASH_REPORT_TOKEN.", file=sys.stderr)
                return 1
        else:
            print(f"NOTE: POST /app returned {job_id!r} rather than a job id, so the install "
                  f"could not be waited on -- confirm {app_name} is actually running in the "
                  f"TrueNAS UI before continuing.", file=sys.stderr)
        return 0

    # ----------------------------------------------------------------------
    # Syncthing (TrueNAS catalog app)
    # ----------------------------------------------------------------------

    def find_catalog_entry(self, app_name: str, dry_run: bool):
        """Try /app/available first (older API name), then /catalog/apps."""
        if dry_run:
            print(f"[dry-run] would GET /app/available (catalog={CATALOG}, train={TRAIN}) "
                  f"looking for {app_name!r}, falling back to /catalog/apps if that 404s")
            return {"name": app_name, "latest_version": "<unknown-in-dry-run>"}

        for path, params in (
            ("/app/available", {"catalog": CATALOG, "train": TRAIN}),
            ("/catalog/apps", {"catalog": CATALOG, "train": TRAIN}),
        ):
            resp = self.calls.api("GET", path, params=params, dry_run=False)
            if resp is None:
                continue
            if resp.status_code == 404:
                continue
            if not self.calls.ok(resp):
                print(f"NOTE: {path} returned HTTP {resp.status_code}, trying next candidate endpoint", file=sys.stderr)
                continue
            try:
                entries = resp.json()
            except ValueError:
                continue
            if isinstance(entries, dict):
                entries = list(entries.values())
            matches = [e for e in entries if isinstance(e, dict) and
                       (e.get("name") == app_name or e.get("id") == app_name or e.get("app_name") == app_name)]
            if matches:
                return matches[0]
        return None

    def install_syncthing(self, gui_port: int, host_path: str,
                          container_mount: str, dry_run: bool) -> int:
        """Install the stable-catalog Syncthing app. Returns a process rc.

        The caller has already answered "is it installed?" -- this is the
        create half, shape check and all.
        """
        app_name = SYNCTHING_APP_NAME
        entry = self.find_catalog_entry(app_name, dry_run)
        if entry is None:
            print(f"FAILED: could not find catalog entry for {app_name!r} in catalog={CATALOG} train={TRAIN} "
                  f"via either /app/available or /catalog/apps. The Apps API shape may have changed again -- "
                  f"inspect it manually (GET /api/v2.0/app/available) and update find_catalog_entry() in this "
                  f"script.", file=sys.stderr)
            return 1

        missing = [f for f in EXPECTED_CATALOG_FIELDS if f not in entry]
        if missing and not dry_run:
            print(f"FAILED: catalog entry for {app_name!r} is missing expected field(s) {missing}. "
                  f"Found keys: {sorted(entry.keys())}. Refusing to guess a create payload against an "
                  f"unfamiliar schema -- update EXPECTED_CATALOG_FIELDS and the payload in this script's "
                  f"docstring once you've confirmed the real shape.", file=sys.stderr)
            return 1

        version = entry.get("latest_version", "<unknown>")
        print(f"found catalog entry: {app_name} version {version} (catalog={CATALOG}, train={TRAIN})")

        # Schema confirmed against the live TrueNAS 25.10.4 chart (stable/
        # syncthing 1.3.11 questions.yaml) on 2026-07-22 — see the chart's
        # run_as/network/storage variable tree. run_as = the service uid:gid so
        # files Syncthing writes land group-editors like everything else.
        # KEEP THIS IN SYNC with the payload in install_syncthing_app.py's docstring.
        uid = common.site_int("stack", "uid", 3000)
        gid = common.site_int("stack", "gid", 3001)
        values = {
            "run_as": {"user": uid, "group": gid},
            "network": {
                "web_port": {"bind_mode": "published", "port_number": gui_port},
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
                        "mount_path": container_mount,
                        "host_path_config": {"path": host_path, "acl_enable": False},
                    }
                ],
            },
        }
        body = {
            "app_name": app_name,
            "catalog_app": app_name,
            "train": TRAIN,
            "version": version,
            "values": values,
        }

        resp = self.calls.api("POST", "/app", json_body=body, dry_run=dry_run)
        if dry_run:
            print(f"[dry-run] container mount for --host-path would be assumed at: {container_mount}")
            print("[dry-run] (CONFIRM this against the real chart before running setup_syncthing_folder.py)")
            return 0

        if not self.calls.ok(resp):
            print(f"FAILED to install {app_name}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            print("If this is a 422/400 body-shape error, the payload in this script's docstring "
                  "(and in main(), which must match it) needs updating to match the real chart "
                  "schema -- check the error body above for the specific field(s) it rejected.",
                  file=sys.stderr)
            return 1

        # A 2xx here only means the create job was ACCEPTED: /app returns a job
        # id and pulls the image asynchronously, so it can still fail afterwards
        # (AUDIT INST-24). Wait for the job rather than declaring success.
        try:
            job_id = resp.json()
        except ValueError:
            job_id = None
        if isinstance(job_id, int):
            print(f"app create job {job_id} accepted; waiting for it to finish "
                  f"(image pull can take a few minutes)...")
            state, job_err = self.calls.wait_for_job(job_id, timeout=900, poll=5)
            if state != "SUCCESS":
                print(f"FAILED: app create job {job_id} ended {state}: {job_err}", file=sys.stderr)
                print(f"Check Apps > {app_name} in the TrueNAS UI -- a partially created app may "
                      f"need deleting before re-running this script.", file=sys.stderr)
                return 1
        else:
            print(f"NOTE: POST /app returned {job_id!r} rather than a job id, so the install "
                  f"could not be waited on -- confirm {app_name} is actually running in the "
                  f"TrueNAS UI before continuing.", file=sys.stderr)

        print(f"installed app: {app_name} version {version}, GUI port {gui_port}, "
              f"host path {host_path} -> container mount {container_mount}")
        print(f"Next: fetch the GUI's API key (TrueNAS UI > Apps > {app_name} > Web UI, or the app's "
              f"config file) and pass it to setup_syncthing_folder.py / accept_device.py / check_health.py.")
        return 0

    # ----------------------------------------------------------------------
    # Identity: the editors group and the editor accounts
    # ----------------------------------------------------------------------

    def find_group(self, name: str, dry_run: bool):
        resp = self.calls.api("GET", "/group", params={"group": name}, dry_run=dry_run)
        if dry_run:
            return None
        if not self.calls.ok(resp):
            print(f"FAILED to query group {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)
        matches = [g for g in resp.json() if g.get("group") == name]
        return matches[0] if matches else None

    def ensure_group(self, name: str, dry_run: bool):
        """Return (db_id, unix_gid) for the group, or (-1, -1) in dry-run.

        NOTE: the /user endpoints' `group`/`groups` fields take the group's
        database id, NOT its unix gid — passing the gid fails validation with
        "This group does not exist" (learned against the live 25.10 API). The
        unix gid is needed separately, for chown-ing the home directory.
        """
        existing = self.find_group(name, dry_run)
        if dry_run:
            print(f"[dry-run] would ensure group {name!r} exists")
            return -1, -1
        if existing:
            print(f"group already exists, skipping: {name} (gid {existing['gid']}, id {existing['id']})")
            return existing["id"], existing["gid"]

        resp = self.calls.api("POST", "/group", json_body={"name": name, "smb": True},
                              dry_run=dry_run)
        if not self.calls.ok(resp):
            print(f"FAILED to create group {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)
        created = resp.json()
        # POST /group returns the new row id (an int), not a dict, on 25.10.
        group_id = created if isinstance(created, int) else created.get("id")
        # Re-read to learn the unix gid the system assigned.
        fresh = self.find_group(name, dry_run=False)
        unix_gid = fresh["gid"] if fresh else -1
        print(f"created group: {name} (id {group_id}, gid {unix_gid})")
        return group_id, unix_gid

    def find_user(self, name: str, dry_run: bool):
        resp = self.calls.api("GET", "/user", params={"username": name}, dry_run=dry_run)
        if dry_run:
            return None
        if not self.calls.ok(resp):
            print(f"FAILED to query user {name!r}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)
        matches = [u for u in resp.json() if u.get("username") == name]
        return matches[0] if matches else None

    def get_user(self, user_id, dry_run: bool = False) -> tuple[dict | None, str]:
        resp = self.calls.api("GET", f"/user/id/{user_id}", dry_run=dry_run)
        if not self.calls.ok(resp):
            return None, f"HTTP {resp.status_code}"
        return resp.json(), ""

    def create_editor(self, username: str, full_name: str, group_id, pubkey: str,
                      homes_parent: str, dry_run: bool = False):
        body = {
            "username": username,
            "full_name": full_name,
            "group_create": False,
            "group": group_id,
            "groups": [group_id],
            # With home_create=True, `home` is the PARENT dir — TrueNAS
            # appends the username itself (25.10 API semantics).
            "home": homes_parent,
            "home_create": True,
            "shell": "/usr/bin/bash",
            # Stays False: 25.10 rejects password_disabled for SMB users
            # outright (see setup_editor_account's module docstring). sshd's own
            # `PasswordAuthentication no` is what makes SSH key-only.
            "password_disabled": False,
            "random_password": True,
            "sshpubkey": pubkey,
            "smb": True,
            "locked": False,
        }
        resp = self.calls.api("POST", "/user", json_body=body, dry_run=dry_run)
        if not self.calls.ok(resp):
            return None, f"HTTP {resp.status_code} {resp.text}"
        return resp.json(), ""

    def update_editor(self, existing: dict, group_id, pubkey: str,
                      dry_run: bool = False):
        body = {
            "sshpubkey": pubkey,
            "smb": True,
            "groups": sorted(set(existing.get("groups", []) + [group_id])),
        }
        resp = self.calls.api("PUT", f"/user/id/{existing['id']}", json_body=body,
                              dry_run=dry_run)
        if not self.calls.ok(resp):
            return None, f"HTTP {resp.status_code} {resp.text}"
        return existing["id"], ""

    def set_password_disabled(self, user_id, dry_run: bool = False):
        """Key-only SSH: 25.10 refuses password_disabled for SMB users by
        design, so a 422 mentioning SMB is the EXPECTED answer, not a problem
        to escalate. ("ok" | "smb-refused" | "failed", detail)."""
        resp = self.calls.api("PUT", f"/user/id/{user_id}",
                              json_body={"password_disabled": True}, dry_run=dry_run)
        if self.calls.ok(resp):
            return "ok", ""
        if resp is not None and resp.status_code == 422 and "SMB" in resp.text:
            return "smb-refused", ""
        return "failed", f"HTTP {resp.status_code} {resp.text}"

    def ensure_home_permissions(self, home: str, uid: int, unix_gid: int,
                                username: str) -> bool:
        """Make `home` acceptable to sshd's StrictModes check. Returns True if OK.

        See setup_editor_account's module docstring: homes created by
        `home_create=True` inherit a world-writable ACL from the parent dataset
        and are owned by the dataset owner, which makes sshd refuse the editor's
        key with an error only visible in the server's auth log.
        `filesystem.setperm` with `stripacl` replaces the inherited ACL with a
        trivial one; a plain chmod would fail with EPERM because the dataset is
        aclmode=restricted.

        The is_forbidden_home() guard stays in setup_editor_account.py: refusing
        to touch a shared parent is a rule about OUR tree layout, not about
        TrueNAS, and it must hold on every backend.
        """
        body = {
            "path": home,
            "mode": HOME_MODE,
            "uid": uid,
            "gid": unix_gid,
            "options": {"stripacl": True, "recursive": False, "traverse": False},
        }
        resp = self.calls.api("POST", "/filesystem/setperm", json_body=body, dry_run=False)
        if not self.calls.ok(resp):
            print(f"FAILED to set permissions on {home}: HTTP {resp.status_code} {resp.text}",
                  file=sys.stderr)
            return False

        job_id = resp.json()
        state, error = self.calls.wait_for_job(job_id)
        if state != "SUCCESS":
            print(f"FAILED to set permissions on {home}: job {job_id} ended {state}: {error}",
                  file=sys.stderr)
            return False

        print(f"home permissions set: {home} -> {username}:{unix_gid} mode 0{HOME_MODE} (ACL stripped)")
        return True

    def verify_home_permissions(self, home: str, username: str) -> bool:
        """Re-read the home dir over SSH and confirm sshd will accept it.

        Deliberately re-checks the exact two conditions sshd's StrictModes tests —
        not group/world-writable, and owned by the user — rather than trusting the
        setperm job's success, because getting this wrong is silent.
        """
        rc, out, err = self.calls.ssh(
            f'echo "$SUDO_PW" | sudo -S -p "" stat -c "%a %U" {common.shell_quote(home)}',
            dry_run=False,
        )
        line = (out or "").strip().splitlines()
        if rc != 0 or not line:
            print(f"WARNING: could not stat {home} to verify permissions: {err.strip()[:200]}",
                  file=sys.stderr)
            return False

        parts = line[-1].split()
        if len(parts) != 2:
            print(f"WARNING: unexpected stat output for {home}: {line[-1]!r}", file=sys.stderr)
            return False

        mode_str, owner = parts
        try:
            mode = int(mode_str, 8)
        except ValueError:
            print(f"WARNING: could not parse mode {mode_str!r} for {home}", file=sys.stderr)
            return False

        problems = []
        if mode & 0o022:
            problems.append(f"mode 0{mode_str} is group- or world-writable")
        if owner != username:
            problems.append(f"owned by {owner}, not {username}")

        if problems:
            print(f"WARNING: {home} will be REJECTED by sshd StrictModes: {'; '.join(problems)}",
                  file=sys.stderr)
            print("         The editor's key is installed but public-key auth will fail with "
                  "'bad ownership or modes for directory' in the NAS auth log.", file=sys.stderr)
            return False

        print(f"verified: home {home} is mode 0{mode_str}, owned by {owner} (sshd StrictModes will accept it)")
        return True

    def ensure_service_user(self, name: str, group: str, dry_run: bool) -> int:
        raise UnsupportedOnBackend(
            f"the {name!r} service account is created once, by hand, when the pool is "
            f"built (server/README.md) -- no script on TrueNAS creates it, and the "
            f"uid/gid the container runs as come from [stack] uid/gid in site.toml."
        )

    def grant_sftp(self, group: str, dry_run: bool) -> bool:
        # Nothing to do: on TrueNAS an account with a shell and a home is an
        # SFTP account. (On DSM this is the FTP application privilege, which is
        # why the method exists at all.)
        return True

    # ----------------------------------------------------------------------
    # Storage
    # ----------------------------------------------------------------------

    def ensure_share(self, name: str, path: str, group: str, dry_run: bool) -> bool:
        raise UnsupportedOnBackend(
            f"datasets and SMB shares are created in the TrueNAS UI (Datasets > Add, "
            f"Shares > Windows Shares) -- see server/README.md. Nothing here creates "
            f"{name!r} at {path!r}: the pool layout is a one-time decision made with "
            f"recordsize/atime/ACL settings this script has no business guessing."
        )

    def set_tree_acl(self, base: str, owner: str, group: str) -> list[str]:
        """The chown/chmod pair setup_tree.py appends to its remote script.

        Returned as shell lines, not executed: setup_tree builds ONE script and
        runs it in ONE ssh session (and server/tests executes that script under
        a stub sudo, which is how the quoting is proved).
        """
        base_q = common.shell_quote(base)
        owner_group = common.shell_quote(f"{owner}:{group}")
        lines = [
            f'echo "$SUDO_PW" | sudo -S -p "" chown -R {owner_group} {base_q} '
            f"&& echo {common.shell_quote(f'ownership set: {owner}:{group} on {base}')}"
        ]
        # Non-fatal: some datasets have ZFS aclmode=restricted, which blocks
        # chmod outright (even for root). Ownership above still applies fine in
        # that case; only the setgid bit is missing. `if` conditions are exempt
        # from `set -e`, so this can't abort the rest of the script.
        lines.append(
            f'if echo "$SUDO_PW" | sudo -S -p "" find {base_q} -type d -exec chmod 2770 {{}} + >/dev/null 2>&1; then '
            f"echo {common.shell_quote(f'permissions set: 2770 (setgid) on all directories under {base}')}; "
            f"else echo {common.shell_quote('permissions NOT set: chmod blocked on this dataset (likely ZFS aclmode=restricted) -- ownership above is still correct, only the setgid bit is missing')}; fi"
        )
        return lines

    def snapshot(self, path: str, label: str, dry_run: bool) -> bool:
        raise UnsupportedOnBackend(
            "snapshots on TrueNAS are ZFS periodic snapshot tasks, configured once in "
            "the UI (Data Protection > Periodic Snapshot Tasks) -- no install script "
            "creates or deletes them. See docs/COMMERCIAL_READINESS.md item 8."
        )

    # ----------------------------------------------------------------------
    # Diagnostics
    # ----------------------------------------------------------------------

    def tailscale_status_json(self, dry_run: bool) -> tuple[int, str, str]:
        """Tailscale runs as its own TrueNAS app here, so its CLI is only
        reachable inside that container."""
        return self.container_exec("tailscale", "tailscale status --json", dry_run)
