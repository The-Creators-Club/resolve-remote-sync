"""Backend-neutral half of the NAS seam: the Protocol every backend answers,
the one error type callers catch, and the shape checks that are about OUR
conventions rather than any NAS's API.

Why a Protocol and not a base class: the TrueNAS client is a dataclass with
its own `requests.Session` field and the Synology one will carry a DSM sid and
an SSH channel (SYNOLOGY_PORT_PLAN.md WP2) -- they share a surface, not an
implementation. Callers depend on the surface only.
"""
from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

# The Unix group that defines "is a member of this fleet" on every backend.
# Named the same on TrueNAS and DSM on purpose: server/, the companion and
# check_health.py all speak it, and a per-backend spelling would mean an
# editor is in the fleet on one NAS and not the other.
EDITORS_GROUP = "editors"

# Mirrors ccsync_dashboard.db._USERNAME_RE exactly -- an account created here
# must be mappable by resolve_editor_username(), or it'll show as unmapped.
USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")
SSH_KEY_PREFIXES = (
    "ssh-ed25519", "ssh-rsa", "ssh-dss",
    "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
)


class NasError(Exception):
    """Anything the NAS could not be made to do: unreachable, refused, or
    answering a shape we will not guess at. Every call site catches THIS --
    a backend-specific subclass (TrueNASError) is still one of these."""


def capability(client: Any, name: str):
    """An OPTIONAL backend method, or None when this backend has none.

    The Protocol below is the surface EVERY backend must answer. Some
    questions only one NAS can answer at all -- reading periodic snapshot
    tasks is a TrueNAS API call with no DSM equivalent (BACKUP_RESTORE.md
    section 2: DSM's scheduling lives in the Snapshot Replication package,
    which has no supported CLI) -- and putting those on the Protocol would
    force every future backend to carry a method whose whole job is to
    refuse, which is exactly what the Protocol docstring below says it will
    not do. So they are looked up by name instead, and "absent" means "this
    NAS cannot be asked", never "the answer is no" (2026-08-18, the setup
    wizard's NAS-backed checks).
    """
    return getattr(client, name, None)


def is_valid_username(name: str) -> bool:
    return bool(USERNAME_RE.match(name))


def looks_like_ssh_pubkey(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    return text.split(" ", 1)[0] in SSH_KEY_PREFIXES


@runtime_checkable
class NasBackend(Protocol):
    """What the dashboard asks of a NAS. Exactly the surface api.py and ui.py
    call today, no more: a backend that answers these six questions can run
    the admin Users section and the companion's fleet-membership check.

    Deliberately NOT on here: home-directory permission fixing. TrueNAS does
    it inside create_or_update_editor via `filesystem.setperm`; DSM will do it
    over SSH with chmod (SYNOLOGY_PORT_PLAN.md's "home directory trap" row).
    It is one backend's private business either way, and no caller sequences
    it -- they read `home_ok` out of the summary dict instead. Nor is
    TrueNASClient.set_password, which exists only to raise NotImplementedError
    and point at set_known_password: a new backend should not have to carry a
    method whose whole job is to refuse.
    """

    def ping(self) -> None:
        """Cheap reachability check. Raises NasError when the NAS cannot be
        reached or refuses the credentials; returns None on success."""

    def find_group(self, name: str) -> dict[str, Any] | None:
        ...

    def ensure_editors_group(self) -> tuple[int, int]:
        """(db_id, unix_gid) for EDITORS_GROUP, creating it if missing. The
        first element is whatever id the backend's user records reference
        (TrueNAS' group db id); the second is the POSIX gid."""

    def find_user(self, username: str) -> dict[str, Any] | None:
        ...

    def list_editors(self) -> list[dict[str, Any]]:
        """Every account in EDITORS_GROUP. Rows carry at least: username, uid,
        full_name, smb, sshpubkey, home, locked -- build_admin_users_view
        renders those and treats the rest as backend detail."""

    def is_editor(self, username: str) -> bool:
        """True when `username` exists and is in EDITORS_GROUP. Raises
        NasError if the NAS can't be asked -- callers must NOT read that as
        'not an editor' (that is what makes /api/v1/verify fail closed but
        retryable rather than open)."""

    def create_or_update_editor(self, username: str, ssh_pubkey: str,
                                full_name: str | None = None) -> dict[str, Any]:
        """Create (or update in place) an editor account. Returns
        {"created": bool, "username": str, "home_ok": bool, "warnings": [...]}.

        Every backend MUST carry the same refusals: never a system/builtin
        account, never an existing account that isn't already in
        EDITORS_GROUP. They are what stops a free-text username in the admin
        UI from becoming a NAS takeover.
        """

    def set_known_password(self, username: str, password: str) -> None:
        """Set an EDITOR's password, with create_or_update_editor's refusals."""

    def delete_editor(self, username: str) -> dict[str, Any]:
        """Delete an EDITOR account (admin delete of a user, CR-76, 2026-08-24).

        Returns {"deleted": bool, "username": str, "warnings": [...]}:
        `deleted=False` means there was no such account, which is not an
        error - the dashboard may know an editor the NAS never had (a device
        approved under a name nobody provisioned), and a retry after a
        half-failed delete must be a no-op.

        Every backend MUST carry create_or_update_editor's refusals, for the
        same reason: never a system/builtin account, never an account that is
        not in EDITORS_GROUP. A free-text username on the Users page must not
        be able to delete the NAS admin.

        What happens to the home directory is the backend's own behaviour
        and is named in `warnings` when it is not "left in place" - the
        canonical project tree is never under a home directory, so a
        deleted account takes no footage with it either way."""
