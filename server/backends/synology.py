"""The Synology DSM 7.2+ backend (docs/SYNOLOGY_PORT_PLAN.md WP3/WP4).

Written 2026-08-17 from docs/synology-spikes-2026-08-17.md -- eight spikes run
against a live DS423+ (DSM 7.2.1-69057 U6) the same day -- and then brought up
against that unit. READ THE SPIKES BEFORE CHANGING ANYTHING HERE: several of
the methods below are shaped by a measurement that contradicts the obvious
implementation, and each one says which.

Two channels, because DSM needs both:

  * **SSH as the admin**, `sudo -S` with the password on STDIN, for docker
    compose, the filesystem, synoacltool and the Tailscale package -- the same
    argv hygiene common.run_ssh has always used (SEC-2). Every command is
    prefixed with a PATH export: the Synology CLIs are NOT on sudo's PATH on a
    stock box, so `synoacltool`/`synowebapi` are otherwise "not found" (the
    spike's "PATH note that cost the first ten minutes").
  * **the DSM Web API** on :5001 (common.synology_api) for users, groups,
    shares, share permissions, the SFTP service, app privileges and snapshots.

The four findings that shape the code, all measured:

  1. **NEVER chmod or chown anything under the tree share.** A single chmod
     DESTROYS that path's Synology ACL -- inheritance gone, and DSM's
     `internal-sftp -u 000` then leaves every new file 0666 (spike 1). Group
     write on DSM is pure ACE. set_tree_acl() therefore emits no chmod and no
     chown, and the deploy's tree-side mkdirs do not either. Mode bits are
     still used INSIDE the apps root (<apps root>/ccsync is our own private
     directory, no editor ever browses it, and mode bits are the only way to
     make a .env root-only) -- that is a deliberate, bounded exception.
  2. **SYNO.API.Auth must be version 7** (common.SYNO_LOGIN_VERSION). A lower
     version logs in happily and hands back a read-only session that fails
     later, and confusingly (spike 3.1).
  3. **The SFTP channel is chrooted to the share view -- for the admin too.**
     /volume1/docker/ccsync is `/docker/ccsync` over SFTP and /tmp does not
     exist there at all (measured 2026-08-17 during this bring-up). Hence
     sftp_path(), and hence the deploy stages code inside the apps root
     instead of /tmp.
  4. **uid/gid must come from the live box.** DSM allocates local users from
     1024 and local groups from 65536, so the fleet's `3000:3001` is wrong
     everywhere here; ensure_service_user() + ensure_group() read the real
     numbers and the compose render is templated from them (spike 7).

One more that is a site.toml value rather than code, and the one that loses
footage: `[net] sftp_chunk_size` MUST be "64Ki" on a Synology site. DSM 7.2's
OpenSSH 8.2 has no `limits@openssh.com`, so a lane-B download at the fleet's
255Ki silently TRUNCATES at 539,000,832 bytes (spike 6).
"""
from __future__ import annotations

import json
import re
import sys

import common
from backends.base import UnsupportedOnBackend

# /volume<N>/<share>/ccsync/... -- the DSM analogue of TrueNAS's
# /mnt/<pool>/apps/ccsync-dashboard deploy-target guard (AUDIT DEL-9). The
# install REPLACES everything under <host-root>/app as root, so a mistyped root
# is refused before anything moves.
HOST_ROOT_RE = re.compile(r"^/volume\d+/[^/]+/ccsync(/[^/]+)*$")

# The Synology CLIs live in /usr/syno/{bin,sbin} and docker in /usr/local/bin,
# none of which are on sudo's PATH on a stock DSM box. Prefixed to every
# privileged command; without it synoacltool/synowebapi/docker are "not found".
#
# The inherited PATH is kept (and only defaulted when there is none) rather
# than replaced: replacing it would drop whatever else sudo's environment
# provides, and server/tests runs these generated scripts under a stub
# sudo/synoacltool that lives on the test's own PATH.
PATH_EXPORT = ("export PATH=/usr/syno/bin:/usr/syno/sbin:/usr/local/bin:"
               "${PATH:-/usr/bin:/bin:/sbin:/usr/sbin}")

# DSM's User Home service puts homes at <location>/homes/<u> and symlinks them
# here; /var/services/homes is the volume-independent spelling, so a site whose
# homes live on /volume2 needs no special case.
HOME_ROOT = "/var/services/homes"
# Every DSM local user's primary group is `users` (gid 100) and synouser gives
# no way to change it -- `editors` is supplementary membership (spike 7).
PRIMARY_GROUP = "users"

# DSM allocates local users from 1024 up (admin=1024, guest=1025 on the tested
# box) and package accounts from 170000 up. Below the floor is a built-in;
# above the ceiling is somebody's *arr stack. Both are refused.
MIN_EDITOR_UID = 1024
PACKAGE_UID_FLOOR = 170000
RESERVED_USERNAMES = frozenset({"admin", "guest", "anonymous", "root", "system", "http"})
RESERVED_PREFIXES = ("sc-",)

# The ACE `SYNO.Core.Share.Permission set` installs for a read-write group, as
# read back off the tested box: full rights, inheritable by files and dirs.
EDITORS_ACE = "rwxpdDaARWc--:fd--"
# What synoacltool prints for a path whose ACL a chmod destroyed.
LINUX_MODE_MARKER = "It's Linux mode"

# The compose profile carrying Syncthing in dashboard/deploy/compose.yaml.
# Lane C is a service in OUR stack on DSM (plan decision 3): we pin the
# version, we generate the API key, and /data matches
# DASH_SYNCTHING_DATA_PREFIX by construction.
SYNCTHING_PROFILE = "bundled-syncthing"

# The Tailscale DSM package, not a container (spike 4).
TAILSCALE_BIN = "/var/packages/Tailscale/target/bin/tailscale"


def share_of(path: str) -> str:
    """The shared folder a /volume<N>/<share>/... path belongs to, or "".

    Shares are what DSM's permission and snapshot APIs are keyed on; every
    absolute path this backend is given is inside one.
    """
    m = re.match(r"^/volume\d+/([^/]+)", str(path or ""))
    return m.group(1) if m else ""


def volume_of(path: str) -> str:
    m = re.match(r"^(/volume\d+)/", str(path or ""))
    return m.group(1) if m else ""


class SynologyBackend:
    """kind="synology". See the module docstring."""

    kind = "synology"
    host_root_re = HOST_ROOT_RE
    #: The methods are real since 2026-08-17; common.get_backend() checks this
    #: before a script opens any connection.
    ready = True

    #: `docker compose -p ccsync ...`. Deliberately NOT app_name: TrueNAS's
    #: middleware prefixes ix- and uses the app name, giving the doubled
    #: "ix-ccsync-dashboard-dashboard-1"; a stack we name ourselves has no
    #: reason to repeat the word.
    COMPOSE_PROJECT = "ccsync"

    def __init__(self, calls: common.ScriptCalls | None = None,
                 app_name: str = "ccsync-dashboard"):
        self.calls = calls or common.ScriptCalls()
        self.app_name = app_name
        # Where the stack's compose.yaml and .env live. Defaults to the site's
        # [apps] root; install_dashboard_app.py re-points it at --host-root
        # (use_project_dir) before deploying, because every compose command
        # needs `-f <dir>/compose.yaml` and a stack must not be managed from a
        # directory the operator did not name.
        self.project_dir = (common.DEFAULT_APPS_ROOT or "").rstrip("/")

    @property
    def dashboard_container(self) -> str:
        # docker compose names containers <project>-<service>-1; there is no
        # ix- prefix because there is no TrueNAS middleware here.
        return f"{self.COMPOSE_PROJECT}-dashboard-1"

    @property
    def compose_file(self) -> str:
        return f"{self.project_dir}/compose.yaml"

    @property
    def env_file(self) -> str:
        return f"{self.project_dir}/.env"

    def use_project_dir(self, root: str) -> str:
        """Point every compose command at `root`, refusing a root outside
        host_root_re -- `compose down` in the wrong directory is as expensive
        as the deploy's `rm -rf` (AUDIT DEL-9)."""
        root = str(root or "").rstrip("/")
        if not self.host_root_re.match(root):
            raise common.EnvError(
                f"refusing to manage a compose stack at {root!r}: it does not match this "
                f"NAS's app root shape ({self.host_root_re.pattern}). Use "
                f"/volume<N>/<share>/ccsync (site.toml [apps] root).")
        self.project_dir = root
        return root

    # ----------------------------------------------------------------------
    # The privileged channel
    # ----------------------------------------------------------------------

    def root_cmd(self, cmd: str) -> str:
        """`cmd` as one root shell command, PATH fixed, password on STDIN.

        $SUDO_PW is read from the SSH channel's stdin by the remote shell
        (common.SUDO_PW_PREAMBLE) and never appears in the remote argv, which
        any local NAS account can read out of `ps` (AUDIT SEC-2).
        """
        return ('echo "$SUDO_PW" | sudo -S -p "" /bin/sh -c '
                + common.shell_quote(f"{PATH_EXPORT}; {cmd}"))

    def _root(self, cmd: str, dry_run: bool, timeout: int = 120):
        return self.calls.ssh(self.root_cmd(cmd), dry_run=dry_run, timeout=timeout)

    def _compose(self, args: str) -> str:
        """A `docker compose` invocation against THIS stack's files."""
        return (f"docker compose --env-file {common.shell_quote(self.env_file)} "
                f"-p {common.shell_quote(self.COMPOSE_PROJECT)} "
                f"-f {common.shell_quote(self.compose_file)} {args}")

    def sftp_path(self, path: str) -> str:
        """`path` as the SFTP channel sees it: DSM chroots every account --
        the admin included -- to its share view, so /volume1/docker/ccsync is
        `/docker/ccsync` there and /tmp is not reachable at all."""
        stripped = re.sub(r"^/volume\d+", "", str(path or ""))
        return stripped or "/"

    # ----------------------------------------------------------------------
    # The container stack (spike 5: compose over SSH coexists with Container
    # Manager, binds loopback exactly, and is managed by -p + -f from anywhere)
    # ----------------------------------------------------------------------

    def app_installed(self, app_name: str, dry_run: bool) -> bool | None:
        """Is the stack up? None = the question could not be answered.

        `docker compose ls --format json` filtered on Name == "ccsync"
        (spike 5). Tri-state for SERVER-8's reason: this runs AFTER the app
        swap, so an unanswerable query must be routed like any other post-swap
        failure rather than exiting.

        `app_name` is deliberately ignored: on DSM there is one STACK, and
        every service in it (dashboard, Syncthing, the PO-token sidecar) comes
        up together from one compose file. So "is the dashboard installed" and
        "is Syncthing installed" are the same question here -- which is why
        install_syncthing_app.py correctly reports "already installed,
        skipping" on this platform (its TrueNAS-flavoured hint about the Apps
        UI is the only thing that reads oddly).
        """
        rc, out, err = self._root("docker compose ls --format json --all", dry_run, 60)
        if dry_run:
            return False
        if rc != 0:
            print(f"FAILED to list compose projects on the NAS: {err.strip()[:300] or rc}",
                  file=sys.stderr)
            return None
        try:
            projects = json.loads(out.strip() or "[]")
        except ValueError:
            print(f"FAILED: `docker compose ls --format json` was not JSON: {out[:200]!r}",
                  file=sys.stderr)
            return None
        return any(p.get("Name") == self.COMPOSE_PROJECT for p in projects
                   if isinstance(p, dict))

    def delete_app(self, app_name: str, dry_run: bool) -> tuple[bool, str]:
        """`docker compose down --remove-orphans`. (ok, message-to-print).

        VOLUMES ARE KEPT -- no `-v`: /data holds dashboard.db (every project
        row, tick, completion history and published companion package). The
        bind mounts are host directories anyway; the flag would only take the
        named ones, and there is no version of "recreate the app" that means
        "delete the fleet's database".
        """
        rc, _out, err = self._root(self._compose("down --remove-orphans"), dry_run, 300)
        if dry_run:
            return True, ""
        if rc != 0:
            return False, (f"FAILED to bring the stack down for --recreate: "
                           f"{err.strip()[:300] or f'exit {rc}'}")
        return True, ""

    def deploy_stack(self, app_name: str, compose: dict, port: int, dry_run: bool,
                     compose_yaml: str = "", env: dict | None = None) -> int:
        """Upload compose.yaml + .env and `docker compose up -d`. Returns a rc.

        `compose` (the dict TrueNAS's middleware stores) is ignored here: this
        platform reads a FILE. install_dashboard_app.render_compose_yaml()
        produces it and the caller hands it over already rendered, because the
        template lives beside the dashboard and the backend has no business
        knowing about placeholders.

        Written by SFTP, never a heredoc: `sh -c` quoting eats a compose file
        (spike 5), and the .env holds five secrets that must not appear in a
        remote command line at all.
        """
        if not compose_yaml.strip():
            print("FAILED: the Synology deploy needs a RENDERED compose.yaml "
                  "(install_dashboard_app.render_compose_yaml) -- refusing to invent one.",
                  file=sys.stderr)
            return 1
        env = dict(env or {})
        root = self.project_dir
        if not self.host_root_re.match(root):
            print(f"FAILED: the stack directory {root!r} does not match "
                  f"{self.host_root_re.pattern}", file=sys.stderr)
            return 1

        _host, user, _pw = common.truenas_conn_params(dry_run=dry_run)
        stage = f"{root}/.stack-stage"
        # The staging dir is owned by the SSH user (SFTP writes as them) and
        # 700; the files are then INSTALLED into place as root, so the live
        # compose.yaml/.env are never writable by a non-root account.
        rc, _out, err = self._root(
            f"mkdir -p {common.shell_quote(stage)} && "
            f"chown {common.shell_quote(user)} {common.shell_quote(stage)} && "
            f"chmod 700 {common.shell_quote(stage)}",
            dry_run, 60)
        if not dry_run and rc != 0:
            print(f"FAILED to prepare {stage}: {err.strip()[:300] or rc}", file=sys.stderr)
            return 1

        files = {"compose.yaml": compose_yaml}
        if env:
            files[".env"] = render_env_file(env)
        if not self.calls.put_text(self.sftp_path(stage), files, dry_run=dry_run):
            print(f"FAILED to upload compose.yaml/.env to {stage} -- nothing was changed "
                  f"on the NAS.", file=sys.stderr)
            return 1

        # `install` rather than mv+chmod: one call sets owner, group and mode,
        # and .env is 600 root because it carries DASH_SESSION_SECRET,
        # DASH_REPORT_TOKEN, the Syncthing API key and the NAS password.
        place = [f"install -o root -g root -m 0644 "
                 f"{common.shell_quote(stage + '/compose.yaml')} "
                 f"{common.shell_quote(self.compose_file)}"]
        if env:
            place.append(f"install -o root -g root -m 0600 "
                         f"{common.shell_quote(stage + '/.env')} "
                         f"{common.shell_quote(self.env_file)}")
        place.append(f"rm -rf {common.shell_quote(stage)}")
        rc, _out, err = self._root(" && ".join(place), dry_run, 120)
        if not dry_run and rc != 0:
            print(f"FAILED to install compose.yaml/.env into {root}: "
                  f"{err.strip()[:300] or rc}", file=sys.stderr)
            return 1
        print(f"stack files installed: {self.compose_file} (0644 root), "
              f"{self.env_file} (0600 root)")

        # --profile: Syncthing is a service in this stack on DSM, and a
        # profiled service is inert unless its profile is named -- which is
        # what keeps the same file safe on TrueNAS, where lane C is a catalog
        # app (dashboard/deploy/compose.yaml).
        up = self._compose(f"--profile {SYNCTHING_PROFILE} up -d --remove-orphans")
        if dry_run:
            self._root(up, True, 60)
            print(f"[dry-run] would bring up the {self.COMPOSE_PROJECT} stack on port {port} "
                  f"from {self.compose_file} (profile {SYNCTHING_PROFILE})")
            return 0
        # The image pull is the slow part on a first install, exactly as the
        # TrueNAS job wait is (SERVER-2).
        print(f"bringing up the {self.COMPOSE_PROJECT} stack (the image pull can take a "
              f"few minutes)...")
        rc, out, err = self._root(up, False, 1800)
        # compose writes its progress to stderr; print it either way, because
        # this is the step an operator is watching.
        tail = (err or out).strip()
        if tail:
            print(tail[-2000:])
        if rc != 0:
            print(f"FAILED: `docker compose up -d` exited {rc}.\n"
                  f"  Manual fallback: ssh to the NAS and run\n"
                  f"    sudo docker compose -p {self.COMPOSE_PROJECT} -f {self.compose_file} "
                  f"--profile {SYNCTHING_PROFILE} up -d\n"
                  f"  ...which prints the same error without this script in the way.",
                  file=sys.stderr)
            return 1
        # A 0 from compose means "containers created", not "the app is up" --
        # the same gap SERVER-2 closed on TrueNAS. Say what is running.
        rc_ps, ps_out, _ = self._root(self._compose("ps --format json"), False, 120)
        for row in _compose_rows(ps_out if rc_ps == 0 else ""):
            print(f"  {row.get('Name', '?')}: {row.get('State', '?')} "
                  f"{row.get('Status', '')}".rstrip())
        return 0

    def restart_stack(self, dry_run: bool) -> tuple[bool, str]:
        """Restart the dashboard container onto freshly installed code.

        SERVER-1: guarded, because fail_after_app_swap calls this ON a failure
        path -- a transport error raising out of the restart would turn the fix
        for OPS-2 back into the traceback OPS-2 was.
        """
        rc, _out, err = self.calls.ssh_guarded(
            self.root_cmd(self._compose("restart dashboard")), dry_run, 300)
        return (dry_run or rc == 0), err

    def container_exec(self, container: str, argv: str,
                       dry_run: bool) -> tuple[int, str, str]:
        return self._root(f"docker exec {container} {argv}", dry_run)

    def dash_binds(self, port: int, bind_lan: str = "",
                   bind_tailnet: str = "") -> list[tuple[str, str]]:
        """Host addresses the dashboard publishes on.

        Loopback by default, and that is the whole design here (plan decision
        5): the dashboard is reached through `tailscale serve` or DSM's own
        reverse proxy, both of which terminate on the box. Spike 4 found two
        reasons to keep this a LIST rather than the plan's single answer --
        Serve can be disabled at the TAILNET level by policy (it is, on the
        tenant tested, and the installer must stop with the admin-console URL
        rather than report success), and a unit with TUN: true has a real
        tailnet interface that compose can bind directly. So [net] bind_lan /
        bind_tailnet still work if a site sets them; unset means 127.0.0.1.

        Never 0.0.0.0: DSM's own nginx already owns the LAN, and a new
        interface must not silently publish the fleet dashboard.
        """
        lan = (bind_lan or common.site_value("net", "bind_lan")).strip()
        tailnet = (bind_tailnet or common.site_value("net", "bind_tailnet")).strip()
        binds = []
        for env_name, address in (("DASH_BIND_LAN", lan), ("DASH_BIND_TAILNET", tailnet)):
            if not address:
                continue
            if address in ("0.0.0.0", "::", "*"):
                raise common.EnvError(
                    f"refusing to publish the dashboard on {address!r}: bind it to "
                    f"127.0.0.1 (the Synology default) or to a specific address. "
                    f"DSM's nginx owns the LAN ports and `tailscale serve` / the DSM "
                    f"reverse proxy is how editors reach it -- see docs/SERVER-SYNOLOGY.md.")
            binds.append((env_name, address))
        return binds or [("", "127.0.0.1")]

    # ----------------------------------------------------------------------
    # Syncthing (plan decision 3)
    # ----------------------------------------------------------------------

    def install_syncthing(self, gui_port: int, host_path: str,
                          container_mount: str, dry_run: bool) -> int:
        """A NO-OP by design, and it says so rather than pretending to install.

        Syncthing is a service in our own compose stack (profile
        "bundled-syncthing"), not a SynoCommunity package: we control the
        version, the API key (STGUIAPIKEY, generated by us and put in .env)
        and the /data mount. It came up with the stack; there is nothing for
        this script to do.
        """
        print(f"Syncthing on Synology is part of the ccsync compose stack "
              f"(profile {SYNCTHING_PROFILE}), not a package -- nothing to install here.")
        print(f"  It mounts the tree at {container_mount} and its GUI is published on "
              f"127.0.0.1:{gui_port} ONLY (an unauthenticated admin surface over every "
              f"folder in the fleet). Reach it through an SSH tunnel:")
        print(f"    ssh -L {gui_port}:127.0.0.1:{gui_port} <admin>@<nas>")
        print(f"  The API key is the SYNCTHING_API_KEY you put in {self.env_file}; pass the "
              f"same value to setup_syncthing_folder.py / accept_device.py / check_health.py.")
        print(f"  The loopback bind is the containment; the GUI itself still has no LOGIN, "
              f"so anyone with a shell on the NAS is a Syncthing admin. Add one:\n"
              f"    SYNCTHING_API_KEY=... python server/secure_syncthing_gui.py")
        return 0

    # ----------------------------------------------------------------------
    # Identity: groups (SYNO.Core.Group, spike 3)
    # ----------------------------------------------------------------------

    def _dsm(self, api: str, method: str, version: int = 1, post: bool = False,
             dry_run: bool = False, **params) -> dict:
        return self.calls.dsm(api, method, version, post=post, dry_run=dry_run, **params)

    def find_group(self, name: str, dry_run: bool):
        """The group row, in the shape the scripts read off TrueNAS
        (`group`/`gid`/`id`). On DSM the gid IS the id.

        `SYNO.Core.Group list` carries no gids -- not even with `additional`;
        `get` does, and reports a missing group as success + errors[3205]
        rather than an error response (measured 2026-08-17).
        """
        if dry_run:
            print(f"[dry-run] would query DSM for group {name!r} "
                  f"(SYNO.Core.Group get name=[{name!r}])")
            return None
        try:
            data = self._dsm("SYNO.Core.Group", "get", 1, name=[name])
        except common.DsmError as exc:
            if getattr(exc, "code", 0) == 3205:
                return None
            print(f"FAILED to query group {name!r}: {exc}", file=sys.stderr)
            sys.exit(1)
        for row in data.get("groups") or []:
            if row.get("name") == name and row.get("gid") is not None:
                gid = int(row["gid"])
                return {"id": gid, "gid": gid, "group": name,
                        "description": row.get("description") or ""}
        return None

    def ensure_group(self, name: str, dry_run: bool) -> tuple[int, int]:
        """(id, unix gid) -- the same number twice on DSM, which has no
        separate database id for a group. The CREATE response carries the new
        gid ({"data":{"gid":65536}}), so no second lookup is needed (spike 7).
        """
        existing = self.find_group(name, dry_run)
        if dry_run:
            print(f"[dry-run] would ensure group {name!r} exists (SYNO.Core.Group create)")
            return -1, -1
        if existing:
            print(f"group already exists, skipping: {name} (gid {existing['gid']})")
            return existing["id"], existing["gid"]
        try:
            data = self._dsm("SYNO.Core.Group", "create", 1, post=True, name=name)
        except common.DsmError as exc:
            if getattr(exc, "code", 0) != 3206:   # created by someone else meanwhile
                print(f"FAILED to create group {name!r}: {exc}", file=sys.stderr)
                sys.exit(1)
            data = {}
        gid = data.get("gid")
        if gid is None:
            fresh = self.find_group(name, dry_run=False)
            if fresh is None:
                print(f"FAILED: group {name!r} was created but DSM does not list it",
                      file=sys.stderr)
                sys.exit(1)
            gid = fresh["gid"]
        gid = int(gid)
        print(f"created group: {name} (gid {gid})")
        return gid, gid

    def _gids_of(self, names: list) -> list:
        """gids for a list of group NAMES -- one `Group get`, not one per
        group. Used to give a user row the same `groups: [gid, ...]` shape the
        TrueNAS rows have, so setup_editor_account's verification is
        backend-independent."""
        names = [str(n) for n in names if n]
        if not names:
            return []
        try:
            data = self._dsm("SYNO.Core.Group", "get", 1, name=names)
        except common.DsmError:
            return []
        return [int(r["gid"]) for r in (data.get("groups") or []) if r.get("gid") is not None]

    def _groups_of(self, username: str) -> list:
        """The user's group NAMES. `SYNO.Core.User.Group get` is one
        synchronous call and is the cleanest membership question DSM answers
        (Group.Member list is per-group and paged)."""
        try:
            data = self._dsm("SYNO.Core.User.Group", "get", 1, name=username)
        except common.DsmError as exc:
            if getattr(exc, "code", 0) == 3106:
                return []
            raise
        return [str(g) for g in (data.get("groups") or [])]

    def _add_to_group(self, username: str, group: str) -> bool:
        """Add and READ BACK. `SYNO.Core.Group.Member add` returns
        success:true whatever you send it, and the parameter it actually reads
        is `name` (a JSON array), not `members` -- so the read-back is not
        paranoia, it is the only evidence the call did anything (spike 3)."""
        self._dsm("SYNO.Core.Group.Member", "add", 1, post=True,
                  group=group, name=[username])
        return group in self._groups_of(username)

    # ----------------------------------------------------------------------
    # Identity: editors (SYNO.Core.User + authorized_keys over SSH, spike 2)
    # ----------------------------------------------------------------------

    def _list_local_users(self) -> list:
        rows, offset = [], 0
        while True:
            data = self._dsm("SYNO.Core.User", "list", 1, type="local", offset=offset,
                             limit=200, additional=["email", "description", "expired", "uid"])
            page = data.get("users") or []
            rows.extend(page)
            offset += len(page)
            if not page or offset >= int(data.get("total") or 0):
                return rows

    def _row(self, user: dict, groups: list | None = None,
             has_key: bool | None = None) -> dict:
        """One DSM user in the row shape setup_editor_account reads.

        `smb: True` is not a lie by omission: DSM has no per-user SMB flag at
        all (unlike TrueNAS) -- access is decided by the share's permission
        list, and every member of `editors` has it once the tree share exists.
        `sshpubkey` carries a marker, never the key: DSM cannot be asked for
        the text, only whether the file is there.
        """
        name = str(user.get("name") or "")
        expired = user.get("expired")
        uid = user.get("uid")
        return {
            "id": name,           # DSM addresses users by NAME, not a row id
            "uid": int(uid) if uid is not None else None,
            "username": name,
            "full_name": user.get("description") or name,
            "email": user.get("email") or "",
            "home": f"{HOME_ROOT}/{name}",
            "groups": list(groups or []),
            "sshpubkey": "(installed)" if has_key else "",
            "smb": True,
            "locked": expired is not None and expired != "normal",
            "shell": "/sbin/nologin",
        }

    def find_user(self, name: str, dry_run: bool):
        """Scan `SYNO.Core.User list` rather than call `SYNO.Core.User get`.

        `get` is the obvious call and it is NOT reliable: on 2026-08-17 the
        same `get name=<u>` answered 3106 ("no such user") for an account that
        exists, twice, then worked again minutes later. A false "no such user"
        here would make this script CREATE an existing account.

        Matched case-insensitively -- DSM's own names are mixed case
        (`Studio`), and a refusal that can be dodged by capitalising is not
        a refusal.
        """
        if dry_run:
            print(f"[dry-run] would query DSM for user {name!r} (SYNO.Core.User list)")
            return None
        wanted = str(name).strip().casefold()
        for row in self._list_local_users():
            if str(row.get("name") or "").casefold() == wanted:
                username = str(row["name"])
                return self._row(row, groups=self._gids_of(self._groups_of(username)),
                                 has_key=self._has_authorized_keys(username))
        return None

    def get_user(self, user_id, dry_run: bool = False) -> tuple[dict | None, str]:
        """Re-read a user for verification. `user_id` is the USERNAME here."""
        row = self.find_user(str(user_id), dry_run)
        if row is None and not dry_run:
            return None, f"DSM does not list a user called {user_id!r}"
        return row, ""

    @staticmethod
    def _reserved_reason(username: str) -> str:
        low = str(username).strip().casefold()
        if low in RESERVED_USERNAMES:
            return f"{username!r} is a DSM built-in account"
        for prefix in RESERVED_PREFIXES:
            if low.startswith(prefix):
                return f"{username!r} looks like a DSM package account ({prefix}*)"
        return ""

    def _refuse_non_editor(self, username: str, action: str) -> str:
        """"" if this account may be provisioned, else the reason it may not.

        The same three refusals the TrueNAS path carries, with DSM's ranges
        (spike 7): local users start at 1024, so `admin` (1024) and `guest`
        (1025) are ABOVE the floor and only the NAME check catches them, and
        anything at 170000+ is a package account.
        """
        reserved = self._reserved_reason(username)
        if reserved:
            return f"{reserved} -- refusing to {action}."
        existing = self.find_user(username, dry_run=False)
        if existing is None:
            return ""
        uid = existing.get("uid")
        if uid is None or not MIN_EDITOR_UID <= int(uid) < PACKAGE_UID_FLOOR:
            return (f"{username!r} is a system or package account (uid {uid}) -- refusing "
                    f"to {action}.")
        if common.EDITORS_GROUP not in self._groups_of(username):
            return (f"{username!r} already exists on the NAS and is not in the "
                    f"{common.EDITORS_GROUP!r} group -- refusing to take over an account "
                    f"this script did not create. Add it to the group in DSM first, or "
                    f"pick a different username.")
        return ""

    def create_editor(self, username: str, full_name: str, group_id, pubkey: str,
                      homes_parent: str, dry_run: bool = False):
        """Create the account, put it in `editors`, install its key.

        DSM's default shell for a new account is /sbin/nologin and SFTP is a
        subsystem, not a login shell -- so an editor gets lanes A/B with no
        interactive shell at all, which closes readiness item H4 for free
        (spike 2). There is no `random_password` flag: the account is created
        WITH a password nobody keeps, and a known one is set separately and
        deliberately (the dashboard's "Set a known password").
        """
        if dry_run:
            print(f"[dry-run] would create DSM user {username!r} (nologin, home under "
                  f"{HOME_ROOT}), add it to {common.EDITORS_GROUP} and write "
                  f"{HOME_ROOT}/{username}/.ssh/authorized_keys")
            return {"id": username, "uid": -1}, ""
        refusal = self._refuse_non_editor(username, "create it")
        if refusal:
            return None, refusal
        try:
            data = self._dsm("SYNO.Core.User", "create", 1, post=True,
                             name=username, password=_random_password(),
                             description=full_name or username, email="",
                             expired="normal", cannot_chg_passwd=False,
                             password_never_expire=True, notify_by_email=False,
                             send_password=False)
        except common.DsmError as exc:
            if getattr(exc, "code", 0) == 3107:
                return None, (f"DSM says {username!r} already exists but does not list it as "
                              f"a local account -- it is probably a package account. Pick a "
                              f"different username.")
            return None, str(exc)
        uid = data.get("uid")
        if not self._add_to_group(username, common.EDITORS_GROUP):
            return None, (f"created {username!r} but DSM did not add it to "
                          f"{common.EDITORS_GROUP!r} (Group.Member add reports success even "
                          f"when it ignored its arguments -- this is the read-back failing)")
        ok_key, detail = self._install_authorized_keys(username, pubkey)
        if not ok_key:
            return None, detail
        return {"id": username, "uid": int(uid) if uid is not None else None}, ""

    def update_editor(self, existing: dict, group_id, pubkey: str,
                      dry_run: bool = False):
        """Update in place: group membership (read back) and the key."""
        username = str(existing.get("username") or existing.get("id") or "")
        if dry_run:
            print(f"[dry-run] would re-add {username!r} to {common.EDITORS_GROUP} and "
                  f"rewrite its authorized_keys")
            return username, ""
        refusal = self._refuse_non_editor(username, "modify it")
        if refusal:
            return None, refusal
        if not self._add_to_group(username, common.EDITORS_GROUP):
            return None, (f"DSM did not add {username!r} to {common.EDITORS_GROUP!r} "
                          f"(read-back failed)")
        ok_key, detail = self._install_authorized_keys(username, pubkey)
        if not ok_key:
            return None, detail
        return username, ""

    # -- editor shell posture (COMMERCIAL_READINESS.md item 7 / H4) ---------
    #
    # Nothing to do on DSM, and that is worth stating rather than leaving as an
    # absence: a DSM local account is /sbin/nologin already, interactive SSH is
    # refused for anyone outside `administrators` whatever their shell says, and
    # SFTP is the subsystem -- so [stack] editor_shell = "sftp-only" describes
    # this platform's out-of-the-box state (spike 2). editor_shell = "shell"
    # cannot be honoured here and is refused rather than silently ignored.

    def editor_shell(self) -> str:
        return "/sbin/nologin"

    def list_editors(self, group_id, dry_run: bool = False):
        """Every member of the editors group, in the /user row shape."""
        if dry_run:
            return [], ""
        members, err = self.list_group_members(common.EDITORS_GROUP, dry_run)
        if err:
            return [], err
        return [{"id": name, "username": name, "shell": "/sbin/nologin"}
                for name in members], ""

    def revoke_editor_key(self, user_id, lock: bool = False, dry_run: bool = False):
        """Offboarding: empty ~/.ssh/authorized_keys (DSM has no key API).

        Truncated rather than deleted, so the 0600 file sshd expects stays put
        and a later re-add does not have to re-create the directory.
        """
        username = str(user_id)
        home = f"{HOME_ROOT}/{username}"
        keys = common.shell_quote(f"{home}/.ssh/authorized_keys")
        if dry_run:
            print(f"[dry-run] would truncate {home}/.ssh/authorized_keys"
                  + (" and expire the account" if lock else ""))
            return True, ""
        rc, _out, err = self._root(f"[ -e {keys} ] && : > {keys} || true", False, 60)
        if rc != 0:
            return False, f"could not clear {home}/.ssh/authorized_keys: {err.strip()[:200]}"
        if lock:
            try:
                self._dsm("SYNO.Core.User", "set", 1, post=True,
                          name=username, expired="now")
            except common.DsmError as exc:
                return False, f"key removed, but the account could not be expired: {exc}"
        return True, ""

    def set_editor_shell(self, user_id, shell: str, dry_run: bool = False):
        if shell == "/sbin/nologin":
            return True, "already nologin (DSM's default for a local account)"
        return False, ("DSM does not offer editors an interactive shell at all -- SSH is "
                       "administrators-only there, whatever /etc/passwd says. Leave "
                       "[stack] editor_shell = \"sftp-only\" on a Synology site.")

    def ensure_sshd_editor_policy(self, group: str, dry_run: bool = False):
        """A no-op that explains itself.

        DSM regenerates /etc/ssh/sshd_config whenever the SSH/SFTP services are
        touched in Control Panel, so a Match block written here is erased by
        the next toggle -- and it would be redundant: DSM already refuses
        interactive SSH to non-administrators and serves lanes A/B through the
        SFTP subsystem, which is what ForceCommand internal-sftp buys on
        TrueNAS.
        """
        print(f"sshd policy: nothing to install on DSM -- {group} members are nologin, "
              f"interactive SSH is administrators-only, and lanes A/B use the SFTP "
              f"subsystem. Keep 'Enable SFTP service' on and SSH restricted in "
              f"Control Panel > Terminal & SNMP.")
        return "unchanged", ""

    def set_password_disabled(self, user_id, dry_run: bool = False) -> tuple[str, str]:
        """DSM has no per-user "password disabled" flag.

        Its nearest neighbour is `expired`, which disables the ACCOUNT --
        including the SMB session the dashboard login verifies against -- so
        there is nothing to set. Editors are key-only for SSH regardless: the
        password exists for SMB and for the dashboard login, and lanes A/B
        never use it. Answered as its own state rather than "failed", which
        would print a warning about a thing that is not wrong.
        """
        return ("not-applicable",
                "DSM has no password_disabled flag; the account's password is used only for "
                "SMB and the dashboard login. SSH stays key-only.")

    # -- the home directory (spike 2) ---------------------------------------

    def _install_authorized_keys(self, username: str, pubkey: str) -> tuple[bool, str]:
        """Write ~/.ssh/authorized_keys as the editor, over SSH.

        DSM has no sshpubkey field and FileStation is not a substitute: a key
        file written that way is owned by the admin, and sshd's StrictModes
        then refuses it while logging NOTHING (spike 2) -- the editor just sees
        "Authentication failed".

        tmp+mv so a half-written authorized_keys can never be the file sshd
        reads. `chmod`/`chown` here are on ~/.ssh ONLY: sshd reads mode bits
        there and losing that directory's Synology ACL costs nothing, while a
        chmod of the HOME would delete the ACL DSM gave it (spike 1).
        """
        home = f"{HOME_ROOT}/{username}"
        key = (pubkey or "").strip()
        if not key:
            return False, "no SSH public key given"
        # bug-hunt-2026-09-03 server-tools-2: without `set -e` this `;`-list
        # returned the rc of the LAST command, the chmod -- which succeeds on a
        # re-key because authorized_keys is already there from the previous
        # enrolment. A failed printf/mv then read as success and left the OLD
        # key live, i.e. a revocation the operator was told had happened. The
        # grep read-back is the half that closes that: verify_home_permissions
        # only stats mode and owner, never the file's content. `set -e` goes
        # AFTER the MISSING_HOME probe, which exits 3 with its own message.
        script = (
            f"if [ ! -d {common.shell_quote(home)} ]; then echo MISSING_HOME; exit 3; fi; "
            f"set -e; umask 077; mkdir -p {common.shell_quote(home + '/.ssh')}; "
            f"printf '%s\\n' {common.shell_quote(key)} > "
            f"{common.shell_quote(home + '/.ssh/.authorized_keys.ccsync')}; "
            f"mv -f {common.shell_quote(home + '/.ssh/.authorized_keys.ccsync')} "
            f"{common.shell_quote(home + '/.ssh/authorized_keys')}; "
            f"chown -R {common.shell_quote(username + ':' + PRIMARY_GROUP)} "
            f"{common.shell_quote(home + '/.ssh')}; "
            f"chmod 700 {common.shell_quote(home + '/.ssh')}; "
            f"chmod 600 {common.shell_quote(home + '/.ssh/authorized_keys')}; "
            f"grep -qxF {common.shell_quote(key)} "
            f"{common.shell_quote(home + '/.ssh/authorized_keys')}"
        )
        rc, out, err = self._root(script, dry_run=False, timeout=60)
        if "MISSING_HOME" in out:
            return False, (f"{home} does not exist -- DSM's User Home service is off, so the "
                           f"account has nowhere to keep an authorized_keys. Turn it on in "
                           f"Control Panel > User & Group > Advanced and re-run.")
        if rc != 0:
            detail = (err or out).strip()[:200]
            return False, (f"installing the SSH key failed (exit {rc}): "
                           f"{detail or 'the key was not there when it was read back'}")
        print(f"installed SSH key: {home}/.ssh/authorized_keys (0600, owned by {username})")
        return True, ""

    def _has_authorized_keys(self, username: str) -> bool:
        rc, out, _err = self._root(
            f"[ -s {common.shell_quote(f'{HOME_ROOT}/{username}/.ssh/authorized_keys')} ] "
            f"&& echo HASKEY || true", dry_run=False, timeout=60)
        return rc == 0 and "HASKEY" in out

    def ensure_home_permissions(self, home: str, uid: int, unix_gid: int,
                                username: str) -> bool:
        """Make `home` acceptable to sshd's StrictModes -- and ONLY ~/.ssh.

        Measured (spike 2): DSM's default home mode is drwx--x--x+ (711),
        which already satisfies StrictModes. So the whole job is
        `chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; chown -R
        <u>:users ~/.ssh` and NOTHING ELSE. The home itself is deliberately not
        touched: a chmod there would strip its Synology ACL (spike 1) for no
        gain. Repairing a home someone already chmod'd is
        `synoacltool -enforce-inherit <home>` followed by `synoacltool -add
        <home> 'user:<u>:allow:rwxpdDaARWcCo:fd--'`, which reproduced DSM's own
        layout byte-for-byte in the spike.
        """
        ssh_dir = f"{home.rstrip('/')}/.ssh"
        rc, _out, err = self._root(
            f"mkdir -p {common.shell_quote(ssh_dir)} && "
            f"chown -R {common.shell_quote(username + ':' + PRIMARY_GROUP)} "
            f"{common.shell_quote(ssh_dir)} && "
            f"chmod 700 {common.shell_quote(ssh_dir)} && "
            f"{{ [ -e {common.shell_quote(ssh_dir + '/authorized_keys')} ] && "
            f"chmod 600 {common.shell_quote(ssh_dir + '/authorized_keys')} || true; }}",
            dry_run=False, timeout=60)
        if rc != 0:
            print(f"FAILED to set permissions on {ssh_dir}: {err.strip()[:200]}",
                  file=sys.stderr)
            return False
        print(f"home permissions set: {ssh_dir} -> {username}:{PRIMARY_GROUP} mode 0700 "
              f"(the home itself is left alone -- chmod would delete its Synology ACL)")
        return True

    def verify_home_permissions(self, home: str, username: str) -> bool:
        """Re-read what sshd will read. Getting this wrong is SILENT on DSM:
        StrictModes refusals are logged nowhere at the default LogLevel, so
        the editor's only symptom is "Authentication failed" (spike 2)."""
        home = home.rstrip("/")
        rc, out, err = self._root(
            f"stat -c 'HOME %a %U' {common.shell_quote(home)}; "
            f"stat -c 'SSHDIR %a %U' {common.shell_quote(home + '/.ssh')}; "
            f"stat -c 'KEYS %a %U' {common.shell_quote(home + '/.ssh/authorized_keys')}",
            dry_run=False, timeout=60)
        stats = {}
        for line in (out or "").splitlines():
            parts = line.split()
            if len(parts) == 3:
                stats[parts[0]] = (parts[1], parts[2])
        if rc != 0 or "KEYS" not in stats:
            print(f"WARNING: could not stat {home} to verify permissions: "
                  f"{(err or out).strip()[:200]}", file=sys.stderr)
            return False
        problems = []
        home_mode, home_owner = stats.get("HOME", ("", ""))
        try:
            if int(home_mode, 8) & 0o022:
                problems.append(f"{home} is mode 0{home_mode} (group- or world-writable)")
        except ValueError:
            problems.append(f"could not parse the mode of {home}: {home_mode!r}")
        if home_owner and home_owner != username:
            problems.append(f"{home} is owned by {home_owner}, not {username}")
        if stats.get("SSHDIR") != ("700", username):
            problems.append(f"{home}/.ssh is {stats.get('SSHDIR')} (wanted ('700', "
                            f"{username!r}))")
        if stats.get("KEYS") != ("600", username):
            problems.append(f"{home}/.ssh/authorized_keys is {stats.get('KEYS')} (wanted "
                            f"('600', {username!r}))")
        if problems:
            print(f"WARNING: {home} will be REJECTED by sshd StrictModes: "
                  f"{'; '.join(problems)}", file=sys.stderr)
            print("         DSM logs NOTHING for a StrictModes refusal -- the editor will "
                  "just see 'Authentication failed'. Repair ~/.ssh with chmod; repair the "
                  "HOME with `synoacltool -enforce-inherit`, never chmod.", file=sys.stderr)
            return False
        print(f"verified: {home} is 0{home_mode} owned by {home_owner or username}, "
              f".ssh 0700, authorized_keys 0600 (sshd StrictModes will accept it)")
        return True

    def ensure_service_user(self, name: str, group: str, dry_run: bool) -> int:
        """The uid the container runs as, read from the LIVE box.

        Mandatory rather than tidy (spike 7): DSM allocates local users from
        1024 and local groups from 65536, so the fleet's hardcoded 3000:3001 is
        wrong on every DSM unit -- APP_UID/APP_GID must be templated from these
        values at every deploy.

        `synouser --add <name> <pw> <desc> <expired> <email> <cannot_chg_passwd>`
        creates a /sbin/nologin account, which is what a service account should
        be; the API's create would do as well but the CLI is one call and needs
        no session for a step that runs before anything else.
        """
        if dry_run:
            print(f"[dry-run] would ensure service account {name!r} exists (synouser --add, "
                  f"nologin) and read its uid")
            return -1
        rc, out, _err = self._root(f"id -u {common.shell_quote(name)} 2>/dev/null || true",
                                   False, 60)
        uid = _first_int(out)
        if uid is None:
            # The one deliberate exception to SEC-2 (bug-hunt-2026-09-03
            # server-tools-6): `synouser --add` takes the password as an
            # argument only, so this value is on the remote argv for the ~1 s
            # the call runs. It is safe HERE because it is random, single-use,
            # never stored and never reused, and the account it creates is
            # /sbin/nologin. Do not copy this pattern for a credential anyone
            # keeps: everything else goes on stdin (common.SUDO_PW_PREAMBLE).
            rc, _out, err = self._root(
                f"synouser --add {common.shell_quote(name)} "
                f"{common.shell_quote(_random_password())} "
                f"{common.shell_quote('CC Sync service account')} 0 '' 0",
                False, 120)
            if rc != 0:
                raise common.EnvError(
                    f"could not create the service account {name!r} on the NAS: "
                    f"{err.strip()[:300] or rc}")
            rc, out, _err = self._root(f"id -u {common.shell_quote(name)}", False, 60)
            uid = _first_int(out)
            if uid is None:
                raise common.EnvError(
                    f"created {name!r} but the NAS does not report a uid for it")
            print(f"created service account: {name} (uid {uid}, /sbin/nologin)")
        else:
            print(f"service account already exists, skipping: {name} (uid {uid})")
        if not MIN_EDITOR_UID <= uid < PACKAGE_UID_FLOOR:
            raise common.EnvError(
                f"refusing to run the stack as uid {uid} ({name!r}): DSM local accounts "
                f"start at {MIN_EDITOR_UID} and package accounts live at "
                f"{PACKAGE_UID_FLOOR}+. Pick a normal local account.")
        # The service account is NOT an editor. Until 2026-08-17 it was added to
        # the editors group so the container could write the tree through the
        # group ACE -- and then showed up on the dashboard's Users page as an
        # editor with a MISSING ssh key, which is exactly what a studio owner
        # must never see. It gets its own RW ACE on the tree share instead
        # (Share.Permission set, local_user), and if an earlier deploy put it in
        # the group it is taken back out. The container still runs uid:<editors
        # gid>: docker sets the gid regardless of membership, and the ACLs on
        # the tree are what actually decide access.
        share = common.site_value("tree", "share_name")
        if share:
            try:
                self._dsm("SYNO.Core.Share.Permission", "set", 1, post=True, name=share,
                          user_group_type="local_user",
                          permissions=[{"name": name, "is_readonly": False,
                                        "is_writable": True, "is_deny": False,
                                        "is_custom": False}])
                print(f"service account {name!r} has its own RW permission on {share!r}")
            except common.DsmError as exc:
                print(f"NOTE: could not grant {name!r} RW on share {share!r}: {exc}",
                      file=sys.stderr)
        try:
            if group and group in self._groups_of(name):
                self._dsm("SYNO.Core.Group.Member", "remove", 1, post=True,
                          group=group, name=[name])
                if group in self._groups_of(name):
                    print(f"NOTE: {name!r} is still in {group!r} after remove -- take it out "
                          f"in DSM so it stops listing as an editor.", file=sys.stderr)
                else:
                    print(f"removed service account {name!r} from {group!r} (it is not an editor)")
        except common.DsmError as exc:
            print(f"NOTE: could not check/remove {name!r} from {group!r}: {exc}",
                  file=sys.stderr)
        return uid

    def grant_sftp(self, group: str, dry_run: bool) -> bool:
        """Turn the SFTP SERVICE on, then VERIFY the SYNO.SFTP privilege.

        The plan was wrong twice here (spike 2): the app id is `SYNO.SFTP`, not
        "FTP", and it is `grant_by_default: true` -- a nologin user SFTPs with
        a pubkey and no extra grant at all. So the privilege half is a
        verification: an explicit DENY covering `editors` is the only thing
        that can be wrong, and it produces the same client symptom as the
        service being off ("channel closed", nothing in any log), which is why
        both are checked here in one place.
        """
        if dry_run:
            print("[dry-run] would enable DSM's SFTP service if it is off "
                  "(SYNO.Core.FileServ.FTP.SFTP set enable=true) and verify no SYNO.SFTP "
                  f"deny rule covers {group!r}")
            return True
        try:
            state = self._dsm("SYNO.Core.FileServ.FTP.SFTP", "get", 1)
            if state.get("enable"):
                print(f"SFTP service already enabled (port {state.get('portnum', 22)})")
            else:
                port = int(state.get("portnum") or 22)
                self._dsm("SYNO.Core.FileServ.FTP.SFTP", "set", 1, post=True,
                          enable=True, portnum=port)
                print(f"enabled DSM's SFTP service on port {port} -- lanes A and B are "
                      f"rclone over SFTP, and with it off key auth SUCCEEDS and the channel "
                      f"is then closed with nothing in any log")
        except common.DsmError as exc:
            print(f"FAILED to check/enable the SFTP service: {exc}", file=sys.stderr)
            return False

        try:
            rules = self._dsm("SYNO.Core.AppPriv.Rule", "list", 1, app_id="SYNO.SFTP")
        except common.DsmError as exc:
            print(f"NOTE: could not read the SYNO.SFTP privilege rules ({exc}) -- check "
                  f"Control Panel > Application Privileges > SFTP by hand.", file=sys.stderr)
            return True
        denied = [r for r in (rules.get("rules") or [])
                  if _rule_denies(r, group)]
        if denied:
            print(f"FAILED: an application-privilege rule DENIES SYNO.SFTP to {group!r}: "
                  f"{denied}.\n"
                  f"  Lanes A and B would fail with 'channel closed' and nothing in any log. "
                  f"  Remove the rule in Control Panel > Application Privileges > SFTP.",
                  file=sys.stderr)
            return False
        print(f"verified: no SYNO.SFTP deny rule covers {group!r} (the privilege is granted "
              f"by default on DSM)")
        return True

    # ----------------------------------------------------------------------
    # Storage (spike 1: group write is pure ACE; chmod DESTROYS it)
    # ----------------------------------------------------------------------

    def ensure_share(self, name: str, path: str, group: str, dry_run: bool) -> bool:
        """Create the shared folder and give `group` read-write on it.

        `SYNO.Core.Share.Permission set` is what installs the inheritable
        `group:<group>:allow:rwxpdDaARWc--:fd--` ACE -- a share created this
        way needs no separate ACL step at all (spike 1), which is why
        set_tree_acl() below is a verification rather than a grant.
        """
        vol = volume_of(path + "/")
        if not vol or share_of(path) != name:
            print(f"FAILED: {path!r} is not /volume<N>/{name} -- a DSM shared folder IS a "
                  f"top-level directory on a volume, so the share name and the path cannot "
                  f"disagree.", file=sys.stderr)
            return False
        if dry_run:
            print(f"[dry-run] would ensure shared folder {name!r} exists at {path} "
                  f"(SYNO.Core.Share create) and give {group!r} RW on it "
                  f"(SYNO.Core.Share.Permission set)")
            return True
        try:
            existing = self._dsm("SYNO.Core.Share", "get", 1, name=name,
                                 additional=["is_support_acl", "support_snapshot"])
        except common.DsmError as exc:
            existing = {} if getattr(exc, "code", 0) in (402, 3301, 0) else None
            if existing is None:
                print(f"FAILED to query share {name!r}: {exc}", file=sys.stderr)
                return False
        if existing and existing.get("name"):
            print(f"shared folder already exists, skipping: {name} ({existing.get('vol_path')})")
        else:
            info = {"name": name, "vol_path": vol, "desc": "CC Sync tree",
                    "enable_share_cow": True, "enable_recycle_bin": False,
                    "hidden": False, "enable_share_compress": False}
            try:
                self._dsm("SYNO.Core.Share", "create", 1, post=True, name=name,
                          shareinfo=info)
            except common.DsmError as exc:
                print(f"FAILED to create shared folder {name!r}: {exc}", file=sys.stderr)
                return False
            print(f"created shared folder: {name} at {path} (Btrfs CoW on, no recycle bin)")

        try:
            self._dsm("SYNO.Core.Share.Permission", "set", 1, post=True, name=name,
                      user_group_type="local_group",
                      permissions=[{"name": group, "is_readonly": False,
                                    "is_writable": True, "is_deny": False,
                                    "is_custom": False}])
            perms = self._dsm("SYNO.Core.Share.Permission", "list", 1, name=name,
                              user_group_type="local_group", offset=0, limit=100)
        except common.DsmError as exc:
            print(f"FAILED to set share permissions for {group!r} on {name!r}: {exc}",
                  file=sys.stderr)
            return False
        writable = [p for p in (perms.get("items") or [])
                    if p.get("name") == group and p.get("is_writable")]
        if not writable:
            print(f"FAILED: DSM accepted the permission call but still does not list "
                  f"{group!r} as writable on {name!r}", file=sys.stderr)
            return False
        print(f"share permissions verified: {group} has RW on {name} (which is what "
              f"installs the inheritable editors ACE -- no chmod is involved anywhere)")
        return True

    def set_tree_acl(self, base: str, owner: str, group: str,
                     project_group: str = "", container_dirs=None) -> list:
        """Shell lines giving `group` write access under `base` -- WITHOUT a
        single chmod or chown.

        PER-PROJECT MODE IS PARTIAL HERE, and says so rather than pretending
        (2026-08-17, docs/TENANCY.md). `project_group` adds an inheritable ACE
        for proj-<slug> on the project directory, which is the grant half. The
        DENY half -- stopping the share-wide `editors` ACE reaching this path --
        cannot be done from a script the way it can on ZFS: the editors ACE is
        INHERITED from the shared folder, and an inherited ACE cannot be
        deleted without first breaking inheritance on the path, which DSM
        exposes only through File Station (Properties > Permission > uncheck
        "Inherit permissions from parent folder"). `container_dirs` is likewise
        ignored: the sticky bit is a mode bit, and a chmod under a share
        destroys the ACL (spike 1) -- DSM's equivalent is the "Deny modify"
        ACE, which is an operator decision, not a scripted one.

        So: on DSM this mode is a grant plus a printed operator TODO. Anything
        else would be a guess against a live filesystem holding the customer's
        footage.

        THE DANGEROUS ONE. Measured (spike 1): chmod/chown on any path under a
        Synology shared folder DESTROYS its ACL -- inheritance gone, and DSM's
        `internal-sftp -u 000` then leaves every new file 0666. A `chmod -R`
        inherited from the TrueNAS path would do that to a whole project tree.
        `owner` is accepted and ignored for that reason: on DSM every local
        user's primary group is `users`, so `chown :editors` is the only way to
        put the group on a file -- and chown is exactly what must not run here.

        What this does instead: a directory created under a share whose
        permission list grants `editors` RW already carries the inheritable
        ACE, so the normal case is a CHECK. When it is missing (a share made by
        hand, or a path someone chmod'd) the repair is
        `synoacltool -enforce-inherit`, then `-add` as the last resort -- both
        confirmed on the box.

        Returned as lines rather than executed because setup_tree.py sends ONE
        script down ONE ssh session, and server/tests runs that script under a
        stub sudo (which is how the quoting is proved).
        """
        base_q = common.shell_quote(base)
        ace = f"group:{group}:allow:{EDITORS_ACE}"
        want = f"group:{group}:allow"
        get_acl = self.root_cmd(f"synoacltool -get {base_q}")
        extra = []
        if project_group:
            proj_ace = f"group:{project_group}:allow:{EDITORS_ACE}"
            proj_want = f"group:{project_group}:allow"
            extra = [
                f"if {get_acl} 2>/dev/null | grep -q {common.shell_quote(proj_want)}; then "
                f"echo {common.shell_quote(f'ACL ok: {project_group} already has an allow ACE on {base}')}; "
                f"else {self.root_cmd(f'synoacltool -add {base_q} {common.shell_quote(proj_ace)}')} "
                f"&& echo {common.shell_quote(f'ACL set: {proj_ace} on {base}')}; fi",
                f"echo {common.shell_quote(f'OPERATOR TODO (docs/TENANCY.md): {project_group} can now write {base}, but the share-wide {group} ACE is INHERITED here and still grants every editor. Break inheritance on this folder in File Station (Properties > Permission > uncheck Inherit permissions from parent folder, keeping the current entries) and remove the {group} entry. DSM exposes no scripted way to do it.')} >&2",
            ]
        return extra + [
            # `if` conditions are exempt from `set -e`, so none of this can
            # abort the rest of setup_tree's script.
            f"if {get_acl} 2>/dev/null | grep -q {common.shell_quote(want)}; then "
            f"echo {common.shell_quote(f'ACL ok: {group} already has an inherited allow ACE on {base} (Synology group-write is pure ACE -- this backend never changes modes or ownership under the tree, which would DELETE it)')}; "
            f"else "
            f"{self.root_cmd(f'synoacltool -enforce-inherit {base_q}')} >/dev/null 2>&1 || true; "
            f"if {get_acl} 2>/dev/null | grep -q {common.shell_quote(want)}; then "
            f"echo {common.shell_quote(f'ACL repaired by inheritance: synoacltool -enforce-inherit {base}')}; "
            f"else "
            f"{self.root_cmd(f'synoacltool -add {base_q} {common.shell_quote(ace)}')} "
            f"&& echo {common.shell_quote(f'ACL set: {ace} on {base}')}; "
            f"fi; fi",
            # The one thing that must be shouted about: a path in "Linux mode"
            # has had its ACL destroyed by a chmod, and everything created
            # under it inherits nothing.
            f"if {get_acl} 2>/dev/null | grep -q {common.shell_quote(LINUX_MODE_MARKER)}; then "
            f"echo {common.shell_quote(f'WARNING: {base} is in Linux mode -- its Synology ACL was destroyed by a mode/ownership change. New files there inherit nothing and land world-writable (DSM sftp runs umask 000). Repair: synoacltool -enforce-inherit')} >&2; fi",
        ]

    def check_tree_acl(self, path: str, group: str, dry_run: bool) -> tuple:
        """(ok|None, message) -- the health check's Synology arm.

        Asserts what spike 1 says matters: the tree still has an ACL (not "It's
        Linux mode"), and `group` is in it. `synoacltool -get-perm PATH USER` is
        the other oracle, but it needs a username; this one needs nothing.
        """
        if dry_run:
            print(f"[dry-run] would run `synoacltool -get {path}` and assert an inheritable "
                  f"{group} ACE (and that the path is not in Linux mode)")
            return None, ""
        rc, out, err = self._root(f"synoacltool -get {common.shell_quote(path)}",
                                  False, 60)
        if rc != 0 and not out.strip():
            return None, f"could not read the ACL of {path}: {err.strip()[:200] or rc}"
        if LINUX_MODE_MARKER in out:
            return False, (f"{path} is in Linux mode -- something chmod'd it and its Synology "
                           f"ACL is GONE. Editors may still write via mode bits, but new "
                           f"files inherit nothing and land world-writable. Repair with "
                           f"`synoacltool -enforce-inherit {path}`.")
        if f"group:{group}:allow" not in out:
            return False, (f"{path} has no allow ACE for group {group!r} -- editors cannot "
                           f"write there. Repair with `synoacltool -add {path} "
                           f"'group:{group}:allow:{EDITORS_ACE}'`.")
        return True, f"{path} carries an allow ACE for {group} (Synology ACL intact)"

    def list_group_members(self, group: str, dry_run: bool) -> tuple:
        """(ok|None, member names, detail) -- check_health's editor-account
        check, which on TrueNAS is two REST calls it makes itself."""
        if dry_run:
            print(f"[dry-run] would list members of {group!r} "
                  f"(SYNO.Core.Group.Member list)")
            return None, [], ""
        try:
            data = self._dsm("SYNO.Core.Group.Member", "list", 1, group=group,
                             offset=0, limit=200)
        except common.DsmError as exc:
            if getattr(exc, "code", 0) == 3205:
                return False, [], f"group {group!r} does not exist -- no editor accounts yet"
            return None, [], str(exc)
        return True, [str(u.get("name")) for u in (data.get("users") or []) if u.get("name")], ""

    def snapshot(self, path: str, label: str, dry_run: bool) -> bool:
        """A read-only Btrfs snapshot of the share `path` lives in.

        Better than the plan assumed (spike 8): the Snapshot Replication
        PACKAGE is not needed to take, list, restore or delete one --
        `SYNO.Core.Share.Snapshot create` works on base DSM and the result is
        an ordinary tree under /volume<N>/@sharesnap/<share>/<GMT+NN-...>/, so
        single-file restore is a plain `cp`. (`cp -a` does NOT carry the
        Synology ACL or the owner -- use `synoacltool -copy SRC DST` where
        owner fidelity matters.) Only SCHEDULING needs the package: `set_schedule`
        answers 403 without it.
        """
        share = share_of(path)
        if not share:
            print(f"FAILED: {path!r} is not under a /volume<N>/<share> path, so there is no "
                  f"shared folder to snapshot.", file=sys.stderr)
            return False
        if dry_run:
            print(f"[dry-run] would take a share snapshot of {share!r} "
                  f"(SYNO.Core.Share.Snapshot create desc={label!r})")
            return True
        try:
            data = self._dsm("SYNO.Core.Share.Snapshot", "create", 1, post=True,
                             name=share, desc=label)
        except common.DsmError as exc:
            print(f"FAILED to snapshot share {share!r}: {exc}", file=sys.stderr)
            return False
        when = data.get("data") or data.get("time") or "<unknown>"
        print(f"snapshot taken: {share} @ {when} "
              f"(/volume?/@sharesnap/{share}/{when})")
        return True

    def snapshot_now(self, path: str, name: str, dry_run: bool) -> tuple:
        """`snapshot()` with the identifier kept (COMMERCIAL_READINESS item 8).

        DSM names a share snapshot itself, from the clock, in its own
        GMT+NN-YYYY.MM.DD-HH.MM.SS spelling -- there is no way to ask for
        `ccsync-20260817-1400` the way `zfs snapshot` lets you. So `name` is
        carried as the DESCRIPTION, which is what the Snapshot Replication UI
        lists beside each one and what an operator restoring at 3am reads to
        tell "before the deploy" from "hourly". The identifier returned is the
        timestamp directory the snapshot actually lives in.
        """
        share = share_of(path)
        if not share:
            print(f"FAILED: {path!r} is not under a /volume<N>/<share> path, so there is "
                  f"no shared folder to snapshot.", file=sys.stderr)
            return False, ""
        if dry_run:
            print(f"[dry-run] would take a share snapshot of {share!r} "
                  f"(SYNO.Core.Share.Snapshot create desc={name!r})")
            return True, f"{share}@<dsm-timestamp>"
        try:
            data = self._dsm("SYNO.Core.Share.Snapshot", "create", 1, post=True,
                             name=share, desc=name)
        except common.DsmError as exc:
            print(f"FAILED to snapshot share {share!r}: {exc}", file=sys.stderr)
            return False, ""
        when = data.get("data") or data.get("time") or "<unknown>"
        print(f"snapshot taken: {share} @ {when} ({name})")
        return True, f"{share}@{when}"

    def list_snapshots(self, path: str, dry_run: bool) -> list:
        """The share's snapshots, oldest first.

        Read off the FILESYSTEM (/volume<N>/@sharesnap/<share>/) rather than
        through SYNO.Core.Share.Snapshot list, because the directory is the
        thing a restore actually copies out of (spike 8) and because it answers
        on a box with no Snapshot Replication package installed -- which is the
        box most likely to be asked whether it has any backups at all.
        """
        share = share_of(path)
        vol = volume_of(path)
        if not share or not vol:
            return []
        snapdir = common.shell_quote(f"{vol}/@sharesnap/{share}")
        rc, out, err = self._root(f"ls -1 {snapdir} 2>/dev/null || true", dry_run, 60)
        if dry_run:
            print(f"[dry-run] would list share snapshots under {vol}/@sharesnap/{share}")
            return []
        if rc != 0:
            print(f"could not list snapshots of {share}: {err.strip()[:200] or rc}",
                  file=sys.stderr)
            return []
        return [{"name": line.strip(), "created": line.strip(), "used": ""}
                for line in (out or "").splitlines() if line.strip()]

    #: What an admin does by hand when the API cannot schedule (below). Kept as
    #: one string so setup_snapshots.py, the runbook and the failure message
    #: cannot drift apart.
    SCHEDULE_STEPS = (
        "DSM > Package Center > install 'Snapshot Replication' (free), then:\n"
        "  Snapshot Replication > Snapshots > pick the shared folder > "
        "Settings > Schedule:\n"
        "    - Enable snapshot schedule, run every hour, every day\n"
        "  Settings > Retention: 'Apply advanced retention policy' >\n"
        "    - keep 24 hourly (latest 1 day), keep 30 daily (latest 30 days)\n"
        "  Repeat for the shared folder holding the app stack.\n"
        "Verify: Snapshots list is non-empty within the hour, and\n"
        "  ls /volume1/@sharesnap/<share>/ over SSH shows timestamp dirs."
    )

    def ensure_snapshot_schedule(self, path: str, schedules: list,
                                 dry_run: bool) -> list:
        """Try DSM's scheduler; say exactly what to click when it is not there.

        Scheduling a share snapshot on DSM belongs to the Snapshot Replication
        PACKAGE -- base DSM can take, list, restore and delete one
        (`snapshot()` above, spike 8) but `SYNO.Core.Share.Snapshot.Setting
        set` answers 403 without the package, and there is no supported CLI for
        it (`synoschedtask` creates DSM tasks, not snapshot schedules, and
        hand-editing /etc/crontab on DSM is how you lose cron).

        So this is honest rather than clever: it attempts the API, and any
        refusal becomes ("manual", the click path) -- never a silent success.
        Nothing here writes a crontab (2026-08-17, COMMERCIAL_READINESS item 8).
        """
        share = share_of(path)
        if not share:
            return [("failed", f"{path!r} is not under /volume<N>/<share>")]
        out = []
        for spec in schedules:
            label = spec.get("label", "?")
            if dry_run:
                print(f"[dry-run] would ask DSM to schedule {label} snapshots of "
                      f"{share!r} (SYNO.Core.Share.Snapshot.Setting set), and print the "
                      f"manual steps if the Snapshot Replication package is absent")
                out.append(("dry-run", label))
                continue
            try:
                self._dsm("SYNO.Core.Share.Snapshot.Setting", "set", 1, post=True,
                          name=share,
                          snapshot_schedule=json.dumps({
                              "enable": True,
                              "hour": spec["schedule"].get("hour", "*"),
                              "minute": spec["schedule"].get("minute", "0"),
                          }),
                          keep_count=int(spec["lifetime_value"]))
            except Exception as exc:  # noqa: BLE001 - 403, 101, or no such API: same answer
                out.append(("manual", f"DSM would not schedule {label} snapshots of "
                                      f"{share!r} from here ({exc}). Do it once by hand:"
                                      f"\n{self.SCHEDULE_STEPS}"))
                continue
            print(f"scheduled snapshots: {share} ({label})")
            out.append(("created", label))
        return out

    # ----------------------------------------------------------------------
    # Diagnostics (spike 4)
    # ----------------------------------------------------------------------

    def tailscale_status_json(self, dry_run: bool) -> tuple:
        """Tailscale is a DSM PACKAGE here, not a container, so its CLI is on
        the host filesystem rather than behind `docker exec`."""
        return self._root(f"{TAILSCALE_BIN} status --json", dry_run, 60)


def _compose_rows(text: str) -> list:
    """`docker compose ps --format json` rows, whichever shape it used.

    Compose v2 has emitted BOTH: one JSON object per line (2.20, the version
    on the tested DS423+) and a single JSON array (newer builds). Reading only
    one of them is a silent "no containers" report on the other, which is
    exactly the kind of lie this print exists to prevent.
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        rows = []
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows
    if isinstance(parsed, dict):
        return [parsed]
    return [r for r in parsed if isinstance(r, dict)]


def _rule_denies(rule, group: str) -> bool:
    """True when an AppPriv rule is an explicit deny that covers `group`.

    Shape (spike 3): {"app_id", "entity_type": "everyone"|"group"|"user",
    "entity_name", "allow_ip": [...], "deny_ip": [...]}. A rule denies when it
    lists 0.0.0.0 in deny_ip and allows nothing.
    """
    if not isinstance(rule, dict):
        return False
    entity_type = str(rule.get("entity_type") or "")
    entity_name = str(rule.get("entity_name") or "")
    if entity_type == "group" and entity_name != group:
        return False
    if entity_type == "user":
        return False        # a per-user deny is that user's problem, not the group's
    return bool(rule.get("deny_ip")) and not rule.get("allow_ip")


# The two .env values the operator already owns rather than one we mint. Their
# rotation is "change the account password on the NAS" (docs/SECRETS.md), so a
# refusal that says `openssl rand -hex 24` is advice nobody can follow
# (bug-hunt-2026-09-03 server-tools-1).
OPERATOR_OWNED_ENV = ("TRUENAS_PW", "DASH_NAS_PW")


def _env_refusal(name: str, what: str) -> common.EnvError:
    head = f"{name} contains {what}, which a .env value cannot carry safely."
    if name in OPERATOR_OWNED_ENV:
        return common.EnvError(
            f"{head} That value is your NAS admin password, so the fix is to set a password "
            f"without {what} on the NAS (Control Panel > User & Group) and re-run.")
    return common.EnvError(
        f"{head} It is a secret this installer generates, so replace it with a fresh one: "
        f"`openssl rand -hex 24`.")


def render_env_file(values: dict) -> str:
    """The `.env` compose reads beside compose.yaml, as text.

    Every value is SINGLE-quoted (bug-hunt-2026-09-03 server-tools-1). Compose
    parses this file with compose-go's dotenv, where an UNQUOTED value loses
    everything after an inline " #", loses its leading/trailing whitespace, and
    loses a wrapping pair of quotes -- silently, so a truncated NAS password
    reads as a container that starts healthy and fails every authentication.
    A single-quoted value is literal there: no interpolation, no escapes.

    A value containing a single quote is refused rather than escaped, because
    compose-go and python-dotenv disagree about what `\\'` means inside single
    quotes and a password that differs by one byte is worse than a refusal.
    """
    lines = [
        "# ccsync stack -- generated by server/install_dashboard_app.py.",
        "# Mode 0600, owned by root: this file holds the dashboard session",
        "# secret, the fleet report token, the Syncthing API key, the b-roll",
        "# ingest token and the NAS admin password. Do not copy it anywhere.",
        "# Every value is single-quoted, i.e. literal: compose does not",
        "# interpolate inside single quotes.",
    ]
    for name in sorted(values):
        value = str(values[name] if values[name] is not None else "")
        if "\n" in value or "\r" in value:
            raise _env_refusal(name, "a newline")
        if "'" in value:
            raise _env_refusal(name, "a single quote")
        lines.append(f"{name}='{value}'")
    return "\n".join(lines) + "\n"


def _first_int(text: str):
    for line in (text or "").splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def _random_password() -> str:
    """A password nobody keeps, for an account that gets a real one later (or
    none at all -- lanes A/B are key-only). The suffix guarantees DSM's default
    policy (mixed case + digit) is satisfied whatever token_urlsafe produces,
    which is otherwise a 3117 on a box whose admin turned the policy on."""
    import secrets

    return secrets.token_urlsafe(24) + "aA1"


# Kept so `from backends.synology import PENDING` still resolves for anything
# that imported it while this backend was a stub (2026-08-17). It is no longer
# raised anywhere: every method above is real.
PENDING = ("the Synology backend is implemented as of 2026-08-17 -- "
           "see docs/SERVER-SYNOLOGY.md")

# Steps this platform does not automate. Nothing here is unfinished: DSM's
# Snapshot Replication package is what SCHEDULES snapshots (403 without it),
# and taking one is `snapshot()` above.
_UNSUPPORTED = UnsupportedOnBackend  # re-exported for symmetry with truenas.py
