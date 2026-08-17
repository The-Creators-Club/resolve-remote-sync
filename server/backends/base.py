"""The install-time backend interface (docs/SYNOLOGY_PORT_PLAN.md, WP3).

Everything a server script does that depends on WHICH NAS this is lives behind
this Protocol: create/restart the container stack, install Syncthing, create
the editors group and an editor account, make a home directory sshd will
accept, own the project tree, ask Tailscale for its status.

Three rules the implementations follow, because the scripts around them do:

  - **--dry-run touches nothing.** Every method takes `dry_run` and, in that
    mode, prints what it would do and returns the same shape it would have
    returned. A backend must not open a socket in dry-run.
  - **Say what happened.** One line per real action ("created group: editors",
    "restarted container: ..."), on the same stream and in the same words the
    script used before the body moved here -- the output of these scripts is
    read by humans mid-deploy and asserted by server/tests.
  - **Refuse rather than guess.** A shape check that fails is a stop with the
    expected-vs-found printed, never a "try the other payload" (the pattern
    install_syncthing_app.py has used since 2026-07-22).

The signatures below are what the scripts actually need, which is not exactly
the sketch in the plan: the plan was written from the outside, this is the
code. Where a platform simply has no such concept (TrueNAS has no scripted
share/service-user creation -- the admin makes the dataset in the UI, see
server/README.md), the method raises UnsupportedOnBackend rather than
pretending to succeed.
"""
from __future__ import annotations

import re
from typing import Protocol, runtime_checkable


class UnsupportedOnBackend(NotImplementedError):
    """This platform does not automate this step (and says what to do instead).

    Distinct from a backend that is merely unfinished (synology.PENDING): this
    one is a deliberate, permanent "not through this script".
    """


@runtime_checkable
class ServerBackend(Protocol):
    """What every platform must provide. See the module docstring."""

    #: "truenas" | "synology"
    kind: str
    #: Deploy-target safety regex: the install REPLACES everything under
    #: <host-root>/app as root, so a mistyped root must be refused before
    #: anything moves (AUDIT DEL-9).
    host_root_re: re.Pattern
    #: The compose service container the dashboard runs in, as the platform
    #: names it: ix-<app_name>-<service>-1 on TrueNAS Apps, which for this
    #: app is "ix-ccsync-dashboard-dashboard-1" (the doubled word is real).
    dashboard_container: str

    # -- the container stack -------------------------------------------------

    def app_installed(self, app_name: str, dry_run: bool) -> bool | None:
        """Is `app_name` deployed? None = the question could not be answered
        (which is a post-swap failure like any other -- SERVER-8)."""

    def delete_app(self, app_name: str, dry_run: bool) -> tuple[bool, str]:
        """Remove the app so it can be re-created (--recreate). (ok, error)."""

    def deploy_stack(self, app_name: str, compose: dict, port: int,
                     dry_run: bool, compose_yaml: str = "",
                     env: dict | None = None) -> int:
        """Create the stack. Returns a process exit code and prints the same
        lines the script used to print itself.

        Two shapes because the platforms take two: TrueNAS's middleware stores
        a compose DICT (`compose`, POSTed verbatim) and ignores the rest;
        Docker Compose over SSH takes a FILE and a `.env` beside it
        (`compose_yaml` from install_dashboard_app.render_compose_yaml, `env`
        the secret-bearing variables it references). The caller renders only
        what its backend needs (2026-08-17, WP3).
        """

    def sftp_path(self, path: str) -> str:
        """`path` as the SFTP channel sees it.

        Identity on TrueNAS. On DSM the SFTP server chroots EVERY account --
        the admin included -- to its share view, so /volume1/docker/ccsync is
        `/docker/ccsync` there and /tmp does not exist at all (measured
        2026-08-17). The deploy engine's staging upload goes through this.
        """

    def restart_stack(self, dry_run: bool) -> tuple[bool, str]:
        """Restart the dashboard container onto freshly installed code."""

    def container_exec(self, container: str, argv: str,
                       dry_run: bool) -> tuple[int, str, str]:
        """Run `argv` inside `container`. Returns (rc, stdout, stderr)."""

    def dash_binds(self, port: int, bind_lan: str = "",
                   bind_tailnet: str = "") -> list[tuple[str, str]]:
        """Host addresses the dashboard publishes on, as (env-var-name,
        address) pairs -- the env name is what compose.yaml lets an operator
        override without editing the file. Never 0.0.0.0."""

    # -- Syncthing -----------------------------------------------------------

    def install_syncthing(self, gui_port: int, host_path: str,
                          container_mount: str, dry_run: bool) -> int:
        """Install Syncthing for lane C. TrueNAS: the catalog app. Synology: a
        no-op, because it is a service in our own compose stack."""

    # -- identity ------------------------------------------------------------

    def find_group(self, name: str, dry_run: bool) -> dict | None: ...

    def ensure_group(self, name: str, dry_run: bool) -> tuple[int, int]:
        """(database id, unix gid). They are different numbers on TrueNAS and
        the /user endpoints want the database one (SERVER-3)."""

    def find_user(self, name: str, dry_run: bool) -> dict | None: ...

    def get_user(self, user_id, dry_run: bool = False) -> tuple[dict | None, str]:
        """Re-read a user for verification. (row, error)."""

    def create_editor(self, username: str, full_name: str, group_id: int,
                      pubkey: str, homes_parent: str,
                      dry_run: bool = False) -> tuple[dict | None, str]:
        """Create the editor account. (created row, error)."""

    def update_editor(self, existing: dict, group_id: int, pubkey: str,
                      dry_run: bool = False) -> tuple[object, str]:
        """Update an existing editor in place. (user id, error)."""

    def set_password_disabled(self, user_id, dry_run: bool = False) -> tuple[str, str]:
        """Try to make SSH key-only. ("ok" | "smb-refused" | "failed", detail)."""

    def ensure_home_permissions(self, home: str, uid: int, unix_gid: int,
                                username: str) -> bool:
        """Make `home` acceptable to sshd's StrictModes check."""

    def verify_home_permissions(self, home: str, username: str) -> bool:
        """Re-read it and confirm sshd will accept it -- getting this wrong is
        silent on the editor's side."""

    def ensure_service_user(self, name: str, group: str, dry_run: bool) -> int:
        """The uid the container runs as. Raises UnsupportedOnBackend where the
        account is created by the admin instead."""

    def grant_sftp(self, group: str, dry_run: bool) -> bool:
        """Whatever gates SFTP for `group` on this platform (nothing on
        TrueNAS; the FTP application privilege on DSM)."""

    # -- storage -------------------------------------------------------------

    def ensure_share(self, name: str, path: str, group: str, dry_run: bool) -> bool:
        """Dataset / shared folder. Raises UnsupportedOnBackend where it is a
        UI step."""

    def set_tree_acl(self, base: str, owner: str, group: str,
                     project_group: str = "", container_dirs=None) -> list[str]:
        """Shell lines that give `group` write access to everything under
        `base`. Returned rather than executed: setup_tree.py assembles ONE
        remote script and runs it in one SSH session, and server/tests runs
        that script under a stub sudo.

        `project_group` / `container_dirs` are the per-project isolation mode
        ([stack] project_acl = "per-project", docs/TENANCY.md, 2026-08-17):
        the project subtree belongs to proj-<slug> instead of the fleet-wide
        editors group, and the directories ABOVE it get the sticky bit so one
        editor cannot delete another's project. Both default to today's
        behaviour, and a backend that cannot express the split says so on
        stderr rather than silently ignoring it."""

    def snapshot(self, path: str, label: str, dry_run: bool) -> bool:
        """Point-in-time snapshot of `path` (readiness item 8).

        The one-call convenience over snapshot_now: it invents the name from
        `label` and throws the identifier away, which is what a caller standing
        in front of a `chown -R` wants (common.snapshot_before).
        """

    def snapshot_now(self, path: str, name: str, dry_run: bool) -> tuple[bool, str]:
        """Take ONE snapshot of the dataset/share `path` lives in, called
        `name`. Returns (ok, the identifier the platform gave it).

        `path` is a NAS PATH on both platforms, not a dataset or a share id:
        the scripts know where the tree is, not how this NAS spells the volume
        it sits on. Each backend maps it (TrueNAS strips /mnt/, DSM takes the
        shared folder out of /volume<N>/<share>/...) -- COMMERCIAL_READINESS.md
        item 8, 2026-08-17.
        """

    def list_snapshots(self, path: str, dry_run: bool) -> list[dict]:
        """Existing snapshots of `path`'s dataset/share, oldest first.

        [{"name": str, "created": str, "used": str}]. A failed read is [] with
        the reason printed -- "I could not tell you" is never "there are none",
        so callers that REPORT (setup_snapshots.py) say so themselves rather
        than letting an empty list read as a backup floor that is missing.
        """

    def ensure_snapshot_schedule(self, path: str, schedules: list[dict],
                                 dry_run: bool) -> list[tuple[str, str]]:
        """Create or update the periodic snapshot tasks for `path`.

        `schedules` is the POLICY (cadence and retention), which belongs to
        setup_snapshots.py, not to a platform; each entry is
        {"label", "naming_schema", "schedule": {minute,hour,dom,month,dow},
        "lifetime_value", "lifetime_unit", "recursive"}. Idempotent by
        (dataset, naming_schema).

        Returns one (state, detail) per entry, state in:
          "created" | "updated" | "unchanged" -- the task is now in place;
          "manual"                            -- this platform cannot be
                                                 scheduled from here and
                                                 `detail` is the exact click
                                                 path for the admin (DSM);
          "failed"                            -- with the reason.
        """

    # -- diagnostics ---------------------------------------------------------

    def tailscale_status_json(self, dry_run: bool) -> tuple[int, str, str]:
        """`tailscale status --json` from the NAS. Returns run_ssh's
        (rc, stdout, stderr) -- the PARSING stays in check_health.py, which is
        platform-independent."""
