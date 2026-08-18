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
# Blank since 2026-08-17: these were this fleet's own 192.168.0.10 /
# 100.64.0.1, which is the first thing a second site would have had to fork
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
        # Which host address the GUI is published on. Blank keeps the chart's
        # own behaviour (every interface), which is what this install did until
        # 2026-08-17 and is finding H4 of COMMERCIAL_READINESS.md item 7: the
        # Syncthing GUI is an unauthenticated admin surface over every folder in
        # the fleet. A site sets [syncthing] gui_bind to the one address the
        # base rig reaches it on -- 127.0.0.1 plus an SSH tunnel is the
        # strictest useful value, and it is what the Synology stack already
        # does.
        #
        # `host_ips` is the TrueNAS 25.10 port-schema field for this. VERIFY
        # AGAINST THE LIVE VERSION before a customer install: if the create is
        # rejected with a schema error naming host_ips, this is the field to
        # drop (and then bind it with `secure_syncthing_gui.py --bind` plus a
        # firewall rule instead).
        gui_bind = common.site_value("syncthing", "gui_bind")
        web_port = {"bind_mode": "published", "port_number": gui_port}
        if gui_bind:
            web_port["host_ips"] = [gui_bind]
        values = {
            "run_as": {"user": uid, "group": gid},
            "network": {
                "web_port": web_port,
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
        if not gui_bind:
            print(f"WARNING: the Syncthing GUI is published on EVERY interface of this NAS "
                  f"(port {gui_port}) and ships with no password. It can add devices and "
                  f"re-point folders across the whole fleet. Set [syncthing] gui_bind in "
                  f"site.toml, and run:\n"
                  f"    SYNCTHING_API_KEY=... python server/secure_syncthing_gui.py",
                  file=sys.stderr)
        else:
            print(f"Then: SYNCTHING_API_KEY=... python server/secure_syncthing_gui.py "
                  f"-- the GUI has no password until you do.")
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

    # TrueNAS SCALE (Debian userland) ships nologin at /usr/sbin/nologin, and
    # /user validates `shell` against `user.shell_choices` -- an unknown path is
    # a 422, not a silently-broken account. Both spellings are checked because
    # 25.10 lists them from /etc/shells and the set has moved before.
    NOLOGIN_CHOICES = ("/usr/sbin/nologin", "/sbin/nologin", "/usr/bin/false")

    def editor_shell(self) -> str:
        """The `shell` an editor account is created with, per [stack] editor_shell."""
        if not common.editor_shell_is_sftp_only():
            return "/usr/bin/bash"
        return self.NOLOGIN_CHOICES[0]

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
            # nologin unless the site says [stack] editor_shell = "shell"
            # (COMMERCIAL_READINESS.md item 7 / H4, 2026-08-17). This was
            # /usr/bin/bash for every editor: an interactive account on the box
            # holding the whole customer's footage, bought for exactly one
            # feature -- rclone's `shell_type = unix` md5sum. See
            # common.editor_shell_mode and setup_editor_account.py
            # --migrate-existing.
            "shell": self.editor_shell(),
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

    def list_editors(self, group_id, dry_run: bool = False):
        """Every account in the editors group. ([row, ...], error).

        Rows are the /user shape, so `username`, `id`, `shell` and `sshpubkey`
        are all there -- --migrate-existing reports on all four.
        """
        resp = self.calls.api("GET", "/user", dry_run=dry_run)
        if dry_run:
            return [], ""
        if not self.calls.ok(resp):
            return [], f"HTTP {resp.status_code} {resp.text}"
        try:
            rows = resp.json()
        except ValueError:
            return [], "GET /user: response was not JSON"
        return [u for u in rows
                if group_id in (u.get("groups") or []) or u.get("group") == group_id
                or (isinstance(u.get("group"), dict) and u["group"].get("id") == group_id)], ""

    def revoke_editor_key(self, user_id, lock: bool = False, dry_run: bool = False):
        """Offboarding: drop the installed public key. (ok, detail).

        The editor's key is generated WITHOUT a passphrase by the onboarding
        wizard (onboarding/steps.py, `-N ""`), because a tray app cannot prompt
        for one on every rclone pass. That is a defensible trade only if the
        key can be taken away again -- and until 2026-08-17 nothing in this
        repo ever removed one (COMMERCIAL_READINESS.md item 7 / H4). This is
        that step; `lock` additionally disables the account so the SMB session
        the dashboard login checks stops working too.
        """
        body = {"sshpubkey": ""}
        if lock:
            body["locked"] = True
        resp = self.calls.api("PUT", f"/user/id/{user_id}", json_body=body, dry_run=dry_run)
        if dry_run:
            return True, ""
        if not self.calls.ok(resp):
            return False, f"HTTP {resp.status_code} {resp.text}"
        return True, ""

    def set_editor_shell(self, user_id, shell: str, dry_run: bool = False):
        """Change an existing editor's login shell. (ok, detail).

        Only setup_editor_account.py --migrate-existing calls this: a plain
        re-run must NOT flip a working editor to nologin, because their
        rclone.conf still says `shell_type = unix` and every checksum would
        start failing the moment it did (2026-08-17).
        """
        resp = self.calls.api("PUT", f"/user/id/{user_id}",
                              json_body={"shell": shell}, dry_run=dry_run)
        if dry_run:
            return True, ""
        if not self.calls.ok(resp):
            detail = f"HTTP {resp.status_code} {resp.text}"
            if resp is not None and resp.status_code == 422:
                detail += (f" -- if it rejected the shell path, check "
                           f"`GET /api/v2.0/user/shell_choices` for what this "
                           f"release calls nologin (tried: {shell})")
            return False, detail
        return True, ""

    # sshd policy for the editors group. TrueNAS regenerates /etc/ssh/sshd_config
    # from middleware, so a file dropped in sshd_config.d is erased by the next
    # service change -- the supported seam is the ssh service's free-text
    # "Auxiliary Parameters" (`options`), which middleware appends verbatim to
    # the END of sshd_config. A Match block there covers everything after it,
    # which is exactly what a trailing block should do.
    SSHD_POLICY_BEGIN = "# --- ccsync editors policy (managed by setup_editor_account.py) ---"
    SSHD_POLICY_END = "# --- end ccsync editors policy ---"

    def sshd_editor_policy(self, group: str) -> str:
        """The auxiliary-parameters block that makes `group` SFTP-only.

        NO ChrootDirectory, deliberately (2026-08-17, COMMERCIAL_READINESS.md
        item 7): sshd demands every component of a chroot be root-owned and not
        group-writable, and the tree root is <owner>:<editors> 2770 by design --
        so the only chrootable point is the pool mountpoint, and chrooting there
        would re-root every rclone path the site manifest publishes
        (DASH_SITE_REMOTE_ROOT is absolute, and every editor's rclone.conf and
        every dashboard remote path is built from it). ForceCommand
        internal-sftp already removes the shell, which is what H4 was about;
        chroot would only add containment against an editor reading OTHER
        directories on the NAS, and that is what docs/TENANCY.md's per-project
        mode addresses instead.
        """
        return "\n".join([
            self.SSHD_POLICY_BEGIN,
            f"Match Group {group}",
            "    ForceCommand internal-sftp",
            "    PasswordAuthentication no",
            "    AllowTcpForwarding no",
            "    X11Forwarding no",
            "    PermitTunnel no",
            "    PermitTTY no",
            self.SSHD_POLICY_END,
        ])

    def ensure_sshd_editor_policy(self, group: str, dry_run: bool = False):
        """Install/refresh the Match block. ("ok"|"unchanged"|"failed", detail).

        Idempotent by markers rather than by string equality of the whole field:
        an operator's own auxiliary parameters sit in the same box and must
        survive (they are usually the reason the box is non-empty at all).
        """
        block = self.sshd_editor_policy(group)
        if dry_run:
            print(f"[dry-run] would GET /ssh and ensure its auxiliary parameters carry:\n{block}")
            return "ok", ""
        resp = self.calls.api("GET", "/ssh", dry_run=False)
        if not self.calls.ok(resp):
            return "failed", f"GET /ssh: HTTP {resp.status_code} {resp.text}"
        try:
            current = str((resp.json() or {}).get("options") or "")
        except ValueError:
            return "failed", "GET /ssh: response was not JSON"

        if self.SSHD_POLICY_BEGIN in current:
            head, _, rest = current.partition(self.SSHD_POLICY_BEGIN)
            _old, _, tail = rest.partition(self.SSHD_POLICY_END)
            # The same "\n\n" the append branch uses, so a second run rebuilds
            # byte-identical text and reports "unchanged" instead of PUTting an
            # sshd config change on every account create.
            head = head.rstrip()
            wanted = ((head + "\n\n" if head else "") + block + tail).strip()
        else:
            wanted = (current.rstrip() + "\n\n" + block).strip() if current.strip() else block
        if wanted == current.strip():
            return "unchanged", ""

        put = self.calls.api("PUT", "/ssh", json_body={"options": wanted}, dry_run=False)
        if not self.calls.ok(put):
            return "failed", f"PUT /ssh: HTTP {put.status_code} {put.text}"
        return "ok", ""

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

    def set_tree_acl(self, base: str, owner: str, group: str,
                     project_group: str = "", container_dirs=None) -> list[str]:
        """The chown/chmod pair setup_tree.py appends to its remote script.

        Returned as shell lines, not executed: setup_tree builds ONE script and
        runs it in ONE ssh session (and server/tests executes that script under
        a stub sudo, which is how the quoting is proved).

        With `project_group` set ([stack] project_acl = "per-project",
        docs/TENANCY.md), two things change and nothing else does:

          * the project subtree is owned by <owner>:proj-<slug> rather than
            <owner>:<editors>, so only the people ticked onto this project can
            read or write inside it;
          * the CONTAINER directories above it (Projects/, the year, the
            series) get the sticky bit as well as setgid -- 3770. Without that,
            per-project groups change nothing about the finding they exist for:
            deleting a directory needs write on its PARENT, and the parents are
            group-writable to every editor by design. Sticky means only the
            entry's owner (the service account) can remove it.

        The service account still owns everything, which is what keeps lane C
        working: Syncthing runs as one uid and must write into every folder.
        """
        base_q = common.shell_quote(base)
        effective_group = project_group or group
        owner_group = common.shell_quote(f"{owner}:{effective_group}")
        lines = [
            f'echo "$SUDO_PW" | sudo -S -p "" chown -R {owner_group} {base_q} '
            f"&& echo {common.shell_quote(f'ownership set: {owner}:{effective_group} on {base}')}"
        ]
        for container in (container_dirs or []):
            cont_q = common.shell_quote(container)
            lines.append(
                f'if echo "$SUDO_PW" | sudo -S -p "" chmod 3770 {cont_q} >/dev/null 2>&1; then '
                f"echo {common.shell_quote(f'container protected: 3770 (setgid+sticky) on {container} -- one editor can no longer delete the project directory of another')}; "
                f"else echo {common.shell_quote(f'container NOT protected: chmod blocked on {container} (likely ZFS aclmode=restricted) -- see docs/TENANCY.md')}; fi"
            )
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

    # ----------------------------------------------------------------------
    # Snapshots (COMMERCIAL_READINESS.md item 8, 2026-08-17)
    # ----------------------------------------------------------------------
    #
    # Until this date the answer here was UnsupportedOnBackend: "snapshots are
    # a thing the admin configures in the UI". Nobody had, and the audit found
    # what that meant -- a mistaken `chown -R`, a deploy or a fleet-side bug
    # had NOTHING behind it. So the floor is code now.
    #
    # Taking one goes over SSH (`zfs snapshot`), not through the middleware, on
    # purpose: the REST namespace for a single snapshot was renamed between
    # SCALE generations (zfs.snapshot.create -> pool.snapshot.create) and this
    # repo cannot verify which one a given customer's box answers, whereas the
    # `zfs` CLI has spelled it the same way for twenty years and the snapshot
    # it makes is an ordinary one the UI lists. SCHEDULING is the opposite case
    # -- /pool/snapshottask is stable across every SCALE this repo has met, and
    # there is no CLI for it at all -- so that half is REST.

    #: A dataset a snapshot task may be created for. Anything else is a typo,
    #: and a recursive task on the wrong dataset snapshots someone's whole
    #: pool on an hourly schedule (the same reasoning as HOST_ROOT_RE).
    DATASET_RE = re.compile(r"^[A-Za-z0-9][-A-Za-z0-9_.: ]*(/[-A-Za-z0-9_.: ]+)+$")

    @staticmethod
    def dataset_of(path: str) -> str:
        """The ZFS dataset a /mnt/... path belongs to, as `zfs` spells it.

        Path in, dataset out: the scripts know /mnt/tank/TheCreatorsPool, the
        pool knows tank/TheCreatorsPool. Only the mountpoint prefix is
        stripped; whether the result is a dataset or a directory INSIDE one is
        the caller's problem, and `zfs snapshot` says so plainly if it is the
        latter.
        """
        p = str(path or "").strip().rstrip("/")
        if not p.startswith("/mnt/"):
            return ""
        return p[len("/mnt/"):]

    def resolve_dataset(self, path: str, dry_run: bool) -> str:
        """The dataset `path` actually lives in, asked of the NAS.

        dataset_of() is only string surgery, and the paths this repo hands
        around are mostly DIRECTORIES inside a dataset rather than dataset
        mountpoints: /mnt/tank/TheCreatorsPool/Creators_Club is a folder in
        `tank/TheCreatorsPool` on this fleet's box, and whether
        /mnt/tank/apps/ccsync-dashboard is its own dataset is a per-site
        choice. `zfs snapshot` on a directory fails, so ask df -- which needs
        no privilege and answers with the dataset name ZFS mounted there --
        and fall back to the string form if it cannot be read.
        """
        naive = self.dataset_of(path)
        if dry_run or not naive:
            return naive
        rc, out, _err = self.calls.ssh(
            f"df --output=source {common.shell_quote(path)} | tail -n 1",
            dry_run=False, timeout=60)
        found = (out or "").strip().splitlines()[-1:] or [""]
        dataset = found[0].strip()
        # A pool ROOT is a dataset too: on this fleet's box /mnt/tank/apps is
        # a plain directory in `tank` itself, and df answers "tank" -- no
        # slash. Requiring one sent every deploy back to the naive
        # `tank/apps/ccsync-dashboard`, which does not exist, so the
        # pre-recreate snapshot silently failed on every deploy until the
        # first image-mode migration read the WARNING (2026-08-18). What is
        # refused now is only what cannot be a dataset: an empty answer, a
        # device path (/dev/...), or something with whitespace in it.
        if (rc != 0 or not dataset or dataset == "Filesystem"
                or dataset.startswith("/") or any(c.isspace() for c in dataset)):
            return naive
        if dataset != naive:
            print(f"{path} is inside dataset {dataset} (not a dataset of its own) "
                  f"-- snapshotting {dataset}")
        return dataset

    def snapshot(self, path: str, label: str, dry_run: bool) -> bool:
        """One snapshot, named from `label` and the clock. See snapshot_now."""
        import time  # noqa: PLC0415 - only this path needs a clock

        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(label or "manual")).strip("-")
        ok, _ident = self.snapshot_now(path, f"ccsync-pre-{safe}-{stamp}", dry_run)
        return ok

    def snapshot_now(self, path: str, name: str, dry_run: bool) -> tuple[bool, str]:
        dataset = self.resolve_dataset(path, dry_run)
        if not dataset:
            print(f"FAILED: {path!r} is not under /mnt, so there is no ZFS dataset to "
                  f"snapshot.", file=sys.stderr)
            return False, ""
        if not re.match(r"^[A-Za-z0-9][-A-Za-z0-9_.:]*$", name):
            print(f"FAILED: {name!r} is not a usable snapshot name (letters, digits and "
                  f"-_.: only).", file=sys.stderr)
            return False, ""
        ident = f"{dataset}@{name}"
        # `zfs snapshot` on an EXISTING name is an error, and re-running a
        # deploy inside the same second is a normal thing to do, so an
        # already-taken snapshot is success: the point-in-time it names exists.
        cmd = (f'echo "$SUDO_PW" | sudo -S -p "" zfs snapshot {common.shell_quote(ident)}')
        rc, _out, err = self.calls.ssh(cmd, dry_run=dry_run, timeout=120)
        if dry_run:
            print(f"[dry-run] would take a ZFS snapshot: {ident} (the dataset is "
                  f"resolved from the path on the NAS at run time, so a real run may "
                  f"snapshot the parent dataset this path sits in)")
            return True, ident
        if rc != 0 and "exists" not in (err or "").lower():
            print(f"FAILED to snapshot {ident}: {err.strip()[:300] or rc}", file=sys.stderr)
            return False, ""
        print(f"snapshot taken: {ident}")
        return True, ident

    def list_snapshots(self, path: str, dry_run: bool) -> list[dict]:
        dataset = self.resolve_dataset(path, dry_run)
        if not dataset:
            return []
        cmd = ('echo "$SUDO_PW" | sudo -S -p "" zfs list -H -t snapshot -s creation '
               f"-o name,used,creation -d 1 {common.shell_quote(dataset)}")
        rc, out, err = self.calls.ssh(cmd, dry_run=dry_run, timeout=120)
        if dry_run:
            print(f"[dry-run] would list ZFS snapshots of {dataset}")
            return []
        if rc != 0:
            print(f"could not list snapshots of {dataset}: {err.strip()[:200] or rc}",
                  file=sys.stderr)
            return []
        rows = []
        for line in (out or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 3 or "@" not in parts[0]:
                continue
            rows.append({"name": parts[0].split("@", 1)[1], "used": parts[1],
                         "created": parts[2]})
        return rows

    def ensure_snapshot_schedule(self, path: str, schedules: list[dict],
                                 dry_run: bool) -> list[tuple[str, str]]:
        """Idempotent /pool/snapshottask create-or-update, keyed on
        (dataset, naming_schema).

        The naming schema is the identity because the middleware gives a task
        no name of its own, and because it is the thing that must not collide:
        two tasks on one dataset writing the same schema fight over the same
        snapshot names. Existing tasks are matched, diffed, and only PUT when
        something actually differs -- a re-run of setup_snapshots.py on a
        configured site prints "unchanged", which is what makes it safe to put
        in a runbook.
        """
        dataset = self.resolve_dataset(path, dry_run)
        out: list[tuple[str, str]] = []
        if not dataset:
            return [("failed", f"{path!r} is not under /mnt -- no dataset to schedule")]
        if not self.DATASET_RE.match(dataset):
            return [("failed", f"refusing to schedule snapshots on {dataset!r}: that is "
                               f"a pool, not a dataset. Name the dataset the tree lives "
                               f"in (site.toml [tree] pool_root).")]

        existing = []
        if not dry_run:
            resp = self.calls.api("GET", "/pool/snapshottask", dry_run=False)
            if not self.calls.ok(resp):
                return [("failed", f"could not read existing snapshot tasks: "
                                   f"HTTP {resp.status_code} {resp.text[:200]}")]
            try:
                existing = [t for t in resp.json() if t.get("dataset") == dataset]
            except ValueError:
                return [("failed", "GET /pool/snapshottask did not answer JSON")]

        for spec in schedules:
            body = {
                "dataset": dataset,
                "recursive": bool(spec.get("recursive", True)),
                "lifetime_value": int(spec["lifetime_value"]),
                "lifetime_unit": str(spec["lifetime_unit"]),
                "naming_schema": str(spec["naming_schema"]),
                "schedule": dict(spec["schedule"]),
                "enabled": True,
                # An empty dataset at 03:00 is not an error worth an alert, and
                # a task that fails on it is a task an admin switches off.
                "allow_empty": True,
            }
            if dry_run:
                print(f"[dry-run] would ensure a periodic snapshot task on {dataset}: "
                      f"{spec['label']} -- {body['naming_schema']}, keep "
                      f"{body['lifetime_value']} {body['lifetime_unit'].lower()}(s), "
                      f"at {_cron_text(body['schedule'])}")
                out.append(("dry-run", spec["label"]))
                continue
            match = next((t for t in existing
                          if t.get("naming_schema") == body["naming_schema"]), None)
            if match is None:
                resp = self.calls.api("POST", "/pool/snapshottask", json_body=body,
                                      dry_run=False)
                if not self.calls.ok(resp):
                    out.append(("failed", f"{spec['label']}: HTTP {resp.status_code} "
                                          f"{resp.text[:200]}"))
                    continue
                print(f"created snapshot task: {dataset} {body['naming_schema']} "
                      f"(keep {body['lifetime_value']} {body['lifetime_unit'].lower()})")
                out.append(("created", spec["label"]))
                continue
            drift = {k: v for k, v in body.items()
                     if k != "dataset" and _differs(match.get(k), v)}
            if not drift:
                print(f"snapshot task already correct, skipping: {dataset} "
                      f"{body['naming_schema']}")
                out.append(("unchanged", spec["label"]))
                continue
            resp = self.calls.api("PUT", f"/pool/snapshottask/id/{match.get('id')}",
                                  json_body=body, dry_run=False)
            if not self.calls.ok(resp):
                out.append(("failed", f"{spec['label']}: HTTP {resp.status_code} "
                                      f"{resp.text[:200]}"))
                continue
            print(f"updated snapshot task: {dataset} {body['naming_schema']} "
                  f"({', '.join(sorted(drift))})")
            out.append(("updated", spec["label"]))
        return out

    # ----------------------------------------------------------------------
    # Diagnostics
    # ----------------------------------------------------------------------

    def tailscale_status_json(self, dry_run: bool) -> tuple[int, str, str]:
        """Tailscale runs as its own TrueNAS app here, so its CLI is only
        reachable inside that container."""
        return self.container_exec("tailscale", "tailscale status --json", dry_run)


def _cron_text(schedule: dict) -> str:
    """A snapshot task's schedule as five cron fields, for the dry-run line."""
    return " ".join(str(schedule.get(k, "*"))
                    for k in ("minute", "hour", "dom", "month", "dow"))


def _differs(found, wanted) -> bool:
    """Does the middleware's stored value differ from what we want?

    Dicts are compared on OUR keys only: GET /pool/snapshottask returns the
    schedule with `begin`/`end` fields the create payload never sets, and
    treating those as drift would make every re-run a PUT (and every runbook
    line a lie about being idempotent).
    """
    if isinstance(wanted, dict):
        return any(_differs((found or {}).get(k), v) for k, v in wanted.items())
    return str(found) != str(wanted)
