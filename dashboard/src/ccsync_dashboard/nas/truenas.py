"""Thin client + account-provisioning logic for the TrueNAS REST API.

The TrueNAS implementation of nas/base.py's NasBackend. Moved here from
ccsync_dashboard/truenas_client.py unchanged on 2026-08-17
(SYNOLOGY_PORT_PLAN.md WP1) -- only the backend-neutral pieces (EDITORS_GROUP,
the username/pubkey shape checks) left, for nas/base.py, and TrueNASError
became a subclass of NasError so callers can catch one type across backends.

Same auth pattern as server/common.py:truenas_api (HTTP basic auth over
api/v2.0, self-signed cert so verify=False) -- but the dashboard container
cannot import server/ (see dashboard/src/ccsync_dashboard/provision.py's
docstring for why), so the pieces of server/setup_editor_account.py this
admin UI needs are intentionally re-implemented here rather than imported.

Unlike setup_editor_account.py, this module never opens an SSH session --
the dashboard has no SSH credentials, only TrueNAS API ones. The CLI script's
final "verify over SSH that sshd's StrictModes will accept it" re-check is
therefore skipped here; `filesystem.setperm`'s job SUCCESS state is trusted
as the signal that the home directory is fixed. `server/check_health.py`
remains the tool for a full independent verification.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import logging

import requests

from .base import EDITORS_GROUP, NasError, is_valid_username

log = logging.getLogger(__name__)

HOME_MODE = "700"
# LEGACY FALLBACK ONLY (2026-08-17): the first fleet's homes dataset. The real
# value now arrives per site as TrueNASClient(homes_parent=...) from
# settings.nas_homes_parent (env DASH_NAS_HOMES_PARENT, written by the deploy
# from site.toml [tree] homes_parent). Kept so an un-migrated container and the
# existing tests keep provisioning where they always did; a warning is logged
# when it is relied on, because for any other site it is the wrong dataset.
HOME_PARENT = "/mnt/tank/TheCreatorsPool/homes"

# TLS verification for TrueNAS API calls. Default False preserves the existing
# behaviour (the NAS presents a self-signed cert, and these calls carry the NAS
# password), but it is now a knob: set DASH_NAS_VERIFY_SSL=1 once the NAS has
# a cert this container trusts, or point it at a CA bundle path.
#
# Only reached when a caller builds this client WITHOUT passing verify_ssl --
# nas.factory always passes settings.nas_verify_ssl. TRUENAS_VERIFY_SSL is the
# name the deployed compose.yaml still uses, kept for one release (WP1).
def _verify_setting() -> bool | str:
    raw = (os.environ.get("DASH_NAS_VERIFY_SSL", "").strip()
           or os.environ.get("TRUENAS_VERIFY_SSL", "").strip())
    if not raw:
        return False
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return raw  # a CA bundle path

# Accounts below this uid are system/builtin (root, truenas_admin, apps...)
# and must never be touched by the "create editor" flow.
MIN_EDITOR_UID = 1000


class TrueNASError(NasError):
    """Kept as its own type (and as the name every existing `except` clause
    uses) while it is also a NasError -- so a call site that has been moved to
    `except NasError` and one that has not both keep working through the WP1
    transition."""


def ok(resp: requests.Response | None) -> bool:
    return resp is not None and 200 <= resp.status_code < 300


@dataclass
class TrueNASClient:
    host: str
    user: str
    password: str
    timeout: float = 30.0
    session: requests.Session = field(default_factory=requests.Session)
    # Production always talks TLS to the real NAS (self-signed cert, hence the
    # verify default of False -- see _verify_setting/TRUENAS_VERIFY_SSL); tests
    # point this at a plain-http fake server instead of also having to fake
    # TLS.
    base_url: str | None = None
    verify_ssl: bool | str = field(default_factory=_verify_setting)
    # See HOME_PARENT: blank = fall back to the first fleet's literal, loudly.
    homes_parent: str = ""
    # A scoped API key (DASH_NAS_API_KEY / TRUENAS_API_KEY). When set it is
    # used INSTEAD of HTTP basic auth with `password`, and the deploy leaves
    # the password out of the container entirely -- see settings.nas_api_key
    # and COMMERCIAL_READINESS.md item 6 (finding H3). TrueNAS 25.10 accepts
    # `Authorization: Bearer <key>` on every /api/v2.0 route.
    api_key: str = field(default_factory=lambda: os.environ.get(
        "DASH_NAS_API_KEY", "").strip() or os.environ.get("TRUENAS_API_KEY", "").strip())

    def _homes_parent(self) -> str:
        if self.homes_parent:
            return self.homes_parent.rstrip("/")
        log.warning("DASH_NAS_HOMES_PARENT is unset -- using the legacy default %s; "
                    "set site.toml [tree] homes_parent and redeploy", HOME_PARENT)
        return HOME_PARENT

    def _request(self, method: str, path: str, json_body: Any = None,
                  params: dict[str, Any] | None = None) -> requests.Response:
        base = self.base_url or f"https://{self.host}/api/v2.0"
        url = f"{base}{path}"
        # Bearer key when the site has one, basic auth otherwise. Never both:
        # sending an Authorization header AND basic credentials makes a 401
        # ambiguous about which of the two the NAS rejected.
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        auth = None if self.api_key else (self.user, self.password)
        try:
            response = self.session.request(
                method, url, json=json_body, params=params, headers=headers,
                auth=auth, verify=self.verify_ssl, timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise TrueNASError(f"{method} {path}: {exc}") from exc
        # No dashboard call follows a redirect (CLAUDE.md; bug-hunt-2026-09-03
        # dash-core-2). A 307/308 preserves method and body, and the bodies
        # here carry a new editor's password; `requests` strips an
        # Authorization header across a host change but never a body.
        if 300 <= response.status_code < 400:
            raise TrueNASError(
                f"{method} {path}: the NAS answered {response.status_code} redirecting to "
                f"{response.headers.get('Location', '(no Location)')!r}. Nothing was sent on. "
                "Point DASH_NAS_BASE_URL at the API address the NAS actually serves"
            )
        return response

    @staticmethod
    def _json(resp: requests.Response, what: str) -> Any:
        """resp.json() that can't 500 the page: a 2xx with a non-JSON body
        (an HTML error page from a proxy, say) raises JSONDecodeError, which
        escapes `except TrueNASError` in every caller and produces a traceback
        instead of the intended banner."""
        try:
            return resp.json()
        except ValueError as exc:
            raise TrueNASError(f"{what}: response was not JSON ({resp.text[:120]!r})") from exc

    def get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        return self._request("GET", path, params=params)

    def post(self, path: str, json_body: Any = None) -> requests.Response:
        return self._request("POST", path, json_body=json_body)

    def put(self, path: str, json_body: Any = None) -> requests.Response:
        return self._request("PUT", path, json_body=json_body)

    def ping(self) -> None:
        """Reachability + credentials, with no side effect (NasBackend.ping).

        A GET of the editors group rather than /system/info: it is the one
        object every deployment of this dashboard already depends on, so a
        200 here means "the NAS answers AND these credentials can read users
        and groups", which is what the admin section actually needs to know.
        """
        resp = self.get("/group", params={"group": EDITORS_GROUP})
        if not ok(resp):
            raise TrueNASError(f"GET /group failed: HTTP {resp.status_code} {resp.text}")

    # ---------------------------------------------------------- groups

    def find_group(self, name: str) -> dict[str, Any] | None:
        resp = self.get("/group", params={"group": name})
        if not ok(resp):
            raise TrueNASError(f"GET /group failed: HTTP {resp.status_code} {resp.text}")
        matches = [g for g in self._json(resp, "GET /group") if g.get("group") == name]
        return matches[0] if matches else None

    def ensure_editors_group(self) -> tuple[int, int]:
        """Returns (db_id, unix_gid), creating the group if missing."""
        existing = self.find_group(EDITORS_GROUP)
        if existing:
            return existing["id"], existing["gid"]
        resp = self.post("/group", {"name": EDITORS_GROUP, "smb": True})
        if not ok(resp):
            raise TrueNASError(f"create group failed: HTTP {resp.status_code} {resp.text}")
        fresh = self.find_group(EDITORS_GROUP)
        if fresh is None:
            raise TrueNASError("group created but not found on re-read")
        return fresh["id"], fresh["gid"]

    # ---------------------------------------------------------- users

    def find_user(self, username: str) -> dict[str, Any] | None:
        resp = self.get("/user", params={"username": username})
        if not ok(resp):
            raise TrueNASError(f"GET /user failed: HTTP {resp.status_code} {resp.text}")
        matches = [u for u in self._json(resp, "GET /user") if u.get("username") == username]
        return matches[0] if matches else None

    def list_editors(self) -> list[dict[str, Any]]:
        """Every TrueNAS user in the editors group (by db id membership)."""
        gid, _unix_gid = self.ensure_editors_group()
        resp = self.get("/user")
        if not ok(resp):
            raise TrueNASError(f"GET /user failed: HTTP {resp.status_code} {resp.text}")
        return [
            u for u in self._json(resp, "GET /user")
            if gid in (u.get("groups") or []) or (u.get("group") or {}).get("id") == gid
        ]

    def _in_editors_group(self, user: dict[str, Any], gid: int) -> bool:
        return gid in (user.get("groups") or []) or (user.get("group") or {}).get("id") == gid

    def is_editor(self, username: str) -> bool:
        """True when `username` exists and is in the editors group. Raises
        TrueNASError if the NAS can't be asked -- callers must NOT read that
        as 'not an editor'."""
        if not is_valid_username(username):
            return False
        gid, _unix_gid = self.ensure_editors_group()
        user = self.find_user(username)
        if user is None:
            return False
        uid = user.get("uid")
        if uid is not None and int(uid) < MIN_EDITOR_UID:
            return False
        return self._in_editors_group(user, gid)

    def create_or_update_editor(self, username: str, ssh_pubkey: str,
                                 full_name: str | None = None) -> dict[str, Any]:
        """Create (or update in place) a TrueNAS editor account: installs the
        SSH key, enables SMB, fixes home-directory permissions. Mirrors
        server/setup_editor_account.py's main(), minus the SSH-based
        StrictModes re-verification (see module docstring).

        Returns a summary dict: {"created": bool, "username": str, "home_ok":
        bool, "warnings": [str, ...]}.

        REFUSES to touch an existing account that isn't already an editor:
        is_valid_username() only checks the charset, so typing an existing
        system account here used to overwrite its sshpubkey, force-add it to
        `editors` and try to disable its password. Only accounts that are
        already in the editors group (and never a builtin/uid<1000 one) may be
        updated in place.
        """
        gid, unix_gid = self.ensure_editors_group()
        existing = self.find_user(username)
        warnings: list[str] = []

        if existing:
            uid = existing.get("uid")
            if uid is not None and int(uid) < MIN_EDITOR_UID:
                raise TrueNASError(
                    f"{username!r} is a system account (uid {uid}) -- refusing to modify it. "
                    "Pick a different username."
                )
            if not self._in_editors_group(existing, gid):
                raise TrueNASError(
                    f"{username!r} already exists on the NAS and is not in the {EDITORS_GROUP!r} "
                    "group -- refusing to take over an account this dashboard didn't create. "
                    "Add it to the group by hand first, or pick a different username."
                )
            body = {
                "sshpubkey": ssh_pubkey,
                "smb": True,
                "groups": sorted(set((existing.get("groups") or []) + [gid])),
            }
            resp = self.put(f"/user/id/{existing['id']}", body)
            if not ok(resp):
                raise TrueNASError(f"update user failed: HTTP {resp.status_code} {resp.text}")
            user_id = existing["id"]
            created = False
        else:
            body = {
                "username": username,
                "full_name": full_name or username,
                "group_create": False,
                "group": gid,
                "groups": [gid],
                # `home` is the PARENT dir with home_create=True -- TrueNAS
                # appends the username itself (25.10 API semantics).
                "home": self._homes_parent(),
                "home_create": True,
                "shell": "/usr/bin/bash",
                "password_disabled": False,
                "random_password": True,
                "sshpubkey": ssh_pubkey,
                "smb": True,
                "locked": False,
            }
            resp = self.post("/user", body)
            if not ok(resp):
                raise TrueNASError(f"create user failed: HTTP {resp.status_code} {resp.text}")
            user_id = self._json(resp, "create user")["id"]
            created = True

        resp = self.get(f"/user/id/{user_id}")
        if not ok(resp):
            raise TrueNASError(f"re-fetch user failed: HTTP {resp.status_code} {resp.text}")
        current = self._json(resp, "re-fetch user")

        if not current.get("sshpubkey"):
            warnings.append("sshpubkey is not set")
        if not current.get("smb"):
            warnings.append("smb flag is not set")
        if gid not in (current.get("groups") or []) and (current.get("group") or {}).get("id") != gid:
            warnings.append(f"user is not a member of group {EDITORS_GROUP!r}")

        # Home permissions are fixed REGARDLESS of the warnings above: they are
        # independent conditions. Gating on `not warnings` meant a
        # not-yet-propagated sshpubkey on the re-fetch silently skipped the
        # chmod, sshd's StrictModes then rejected the key, and lanes A/B failed
        # with a generic auth error while the banner talked only about the key.
        home_ok = False
        home = current.get("home")
        uid = current.get("uid")
        if home and uid is not None:
            home_ok = self._fix_home_permissions(home, uid, unix_gid)
            if not home_ok:
                warnings.append(
                    "home directory permissions could not be confirmed fixed -- "
                    "SSH/SFTP (lanes A/B) may fail with a generic auth error until "
                    "server/setup_editor_account.py or check_health.py verifies this"
                )
        else:
            warnings.append(f"cannot fix home permissions (home={home!r}, uid={uid!r})")

        # Key-only SSH: 25.10 refuses password_disabled for SMB users by
        # design -- that specific 422 is the expected answer, not a failure.
        resp = self.put(f"/user/id/{user_id}", {"password_disabled": True})
        if not ok(resp) and not (resp is not None and resp.status_code == 422 and "SMB" in resp.text):
            warnings.append(f"could not set password_disabled=True: HTTP {resp.status_code}")

        return {"created": created, "username": username, "home_ok": home_ok, "warnings": warnings}

    def _fix_home_permissions(self, home: str, uid: int, unix_gid: int) -> bool:
        if not home or home in ("/", "/nonexistent", "/var/empty"):
            return False
        resp = self.post("/filesystem/setperm", {
            "path": home,
            "mode": HOME_MODE,
            "uid": uid,
            "gid": unix_gid,
            "options": {"stripacl": True, "recursive": False, "traverse": False},
        })
        if not ok(resp):
            return False
        job_id = self._json(resp, "filesystem/setperm")
        state, _error = self._wait_for_job(job_id)
        return state == "SUCCESS"

    def _wait_for_job(self, job_id: int, timeout: float = 120.0, poll: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(poll)
            resp = self.get("/core/get_jobs", params={"id": job_id})
            if not ok(resp):
                continue
            rows = self._json(resp, "core/get_jobs")
            if not rows:
                continue
            job = rows[0]
            state = job.get("state")
            if state in ("SUCCESS", "FAILED", "ABORTED"):
                return state, job.get("error")
        return "TIMEOUT", f"job {job_id} did not finish within {timeout}s"

    # ------------------------------------------- optional capabilities
    # Not on the NasBackend Protocol, deliberately: base.py's rule is that a
    # new backend must not have to carry a method whose whole job is to
    # refuse, and neither of these two has a DSM answer (see synology.py's
    # own note, and BACKUP_RESTORE.md section 2 "Synology": DSM can TAKE a
    # share snapshot from the API but SCHEDULING lives in the Snapshot
    # Replication package, which has no supported CLI or API). Callers reach
    # them through nas.capability() and treat "absent" as "this NAS cannot be
    # asked", never as "the answer is no" (ZERO_TOUCH_PLAN.md WP D, the
    # setup wizard's "Connect to your NAS" / "Protect your data" checks,
    # 2026-08-18).

    def system_info(self) -> dict[str, str]:
        """{"version", "hostname"} for a status line. Raises TrueNASError."""
        resp = self.get("/system/info")
        if not ok(resp):
            raise TrueNASError(
                f"GET /system/info failed: HTTP {resp.status_code} {resp.text[:120]}")
        info = self._json(resp, "GET /system/info")
        if not isinstance(info, dict):
            raise TrueNASError("GET /system/info: expected an object")
        return {
            "version": str(info.get("version") or ""),
            "hostname": str(info.get("hostname") or ""),
        }

    def list_snapshot_tasks(self) -> list[dict[str, Any]]:
        """Every periodic snapshot task the NAS holds (Data Protection ->
        Periodic Snapshot Tasks). The same objects `server/setup_snapshots.py`
        creates over this route; this only ever READS them."""
        resp = self.get("/pool/snapshottask")
        if not ok(resp):
            raise TrueNASError(
                f"GET /pool/snapshottask failed: HTTP {resp.status_code} {resp.text[:120]}")
        rows = self._json(resp, "GET /pool/snapshottask")
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def set_password(self, username: str) -> str:
        """Not used directly -- callers pass an explicit password via
        set_known_password(). Kept out of create_or_update_editor() itself
        because TrueNAS already randomizes it on creation and the admin UI
        offers setting a known one as a separate, explicit action (see
        SERVER.md's "Gotcha" about dashboard login needing a known password).
        """
        raise NotImplementedError("use set_known_password(username, password)")

    def set_known_password(self, username: str, password: str) -> None:
        """Set an EDITOR account's password.

        Carries exactly the refusals create_or_update_editor has, and for the
        same reason: the admin "Users" section takes a free-text username, so
        without them POST /admin/users/root/password set the NAS ROOT
        password (and any system account's) straight through this method --
        an admin-session -> full-NAS-takeover step that no part of the flow
        was ever meant to allow. There is deliberately NO allowlist escape
        hatch: nothing in the UI needs one, and non-editor accounts are
        managed in the TrueNAS UI.
        """
        if not is_valid_username(username):
            raise TrueNASError(
                f"invalid username {username!r}: must start with a letter and contain only "
                "lowercase letters, digits, '.', '_', '-'"
            )
        gid, _unix_gid = self.ensure_editors_group()
        user = self.find_user(username)
        if user is None:
            raise TrueNASError(f"no such user: {username!r}")
        uid = user.get("uid")
        if uid is not None and int(uid) < MIN_EDITOR_UID:
            raise TrueNASError(
                f"{username!r} is a system account (uid {uid}) -- refusing to set its "
                "password. This dashboard only manages editor accounts."
            )
        if not self._in_editors_group(user, gid):
            raise TrueNASError(
                f"{username!r} is not in the {EDITORS_GROUP!r} group -- refusing to set the "
                "password of an account this dashboard didn't create."
            )
        resp = self.put(f"/user/id/{user['id']}", {"password": password})
        if not ok(resp):
            raise TrueNASError(f"set password failed: HTTP {resp.status_code} {resp.text}")

    def delete_editor(self, username: str) -> dict[str, Any]:
        """Delete an EDITOR account (CR-76, 2026-08-24). Same three refusals
        as set_known_password, same reason: the Users page takes a free-text
        username and DELETE /user/id/1 would take the NAS admin with it.

        TrueNAS' user.delete does not touch the home directory unless asked
        (its only option is `delete_group`, and the primary group here is the
        shared `editors` group, so that is never asked). The directory stays
        on the pool for the NAS admin to remove; nothing this fleet syncs
        lives under it.

        A missing account is `deleted=False`, not an error: the dashboard
        can know an editor the NAS never had, and the retry after a
        half-failed delete must be a no-op (NasBackend.delete_editor)."""
        if not is_valid_username(username):
            raise TrueNASError(
                f"invalid username {username!r}: must start with a letter and contain only "
                "lowercase letters, digits, '.', '_', '-'"
            )
        gid, _unix_gid = self.ensure_editors_group()
        user = self.find_user(username)
        if user is None:
            return {"deleted": False, "username": username, "warnings": []}
        uid = user.get("uid")
        if uid is not None and int(uid) < MIN_EDITOR_UID:
            raise TrueNASError(
                f"{username!r} is a system account (uid {uid}) -- refusing to delete it. "
                "This dashboard only manages editor accounts."
            )
        if not self._in_editors_group(user, gid):
            raise TrueNASError(
                f"{username!r} is not in the {EDITORS_GROUP!r} group -- refusing to delete "
                "an account this dashboard didn't create. Remove it in the TrueNAS UI."
            )
        resp = self._request("DELETE", f"/user/id/{user['id']}", json_body={"delete_group": False})
        if not ok(resp):
            raise TrueNASError(f"delete user failed: HTTP {resp.status_code} {resp.text}")
        if self.find_user(username) is not None:
            raise TrueNASError(f"TrueNAS still lists {username!r} after delete")
        warnings = []
        if user.get("home"):
            warnings.append(
                f"the home directory {user['home']} was left in place; remove it in the "
                "TrueNAS UI if it is no longer wanted")
        return {"deleted": True, "username": username, "warnings": warnings}
