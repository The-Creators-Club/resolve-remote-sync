"""Thin client + account-provisioning logic for the TrueNAS REST API.

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

import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

EDITORS_GROUP = "editors"
HOME_MODE = "700"
HOME_PARENT = "/mnt/tank/TheCreatorsPool/homes"

# Mirrors ccsync_dashboard.db._USERNAME_RE exactly -- an account created here
# must be mappable by resolve_editor_username(), or it'll show as unmapped.
USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")
SSH_KEY_PREFIXES = (
    "ssh-ed25519", "ssh-rsa", "ssh-dss",
    "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
)


class TrueNASError(Exception):
    pass


def is_valid_username(name: str) -> bool:
    return bool(USERNAME_RE.match(name))


def looks_like_ssh_pubkey(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    return text.split(" ", 1)[0] in SSH_KEY_PREFIXES


def ok(resp: requests.Response | None) -> bool:
    return resp is not None and 200 <= resp.status_code < 300


@dataclass
class TrueNASClient:
    host: str
    user: str
    password: str
    timeout: float = 30.0
    session: requests.Session = field(default_factory=requests.Session)
    # Production always talks TLS to the real NAS (self-signed cert, hence
    # verify=False below); tests point this at a plain-http fake server
    # instead of also having to fake TLS.
    base_url: str | None = None

    def _request(self, method: str, path: str, json_body: Any = None,
                  params: dict[str, Any] | None = None) -> requests.Response:
        base = self.base_url or f"https://{self.host}/api/v2.0"
        url = f"{base}{path}"
        try:
            return self.session.request(
                method, url, json=json_body, params=params,
                auth=(self.user, self.password), verify=False, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TrueNASError(f"{method} {path}: {exc}") from exc

    def get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        return self._request("GET", path, params=params)

    def post(self, path: str, json_body: Any = None) -> requests.Response:
        return self._request("POST", path, json_body=json_body)

    def put(self, path: str, json_body: Any = None) -> requests.Response:
        return self._request("PUT", path, json_body=json_body)

    # ---------------------------------------------------------- groups

    def find_group(self, name: str) -> dict[str, Any] | None:
        resp = self.get("/group", params={"group": name})
        if not ok(resp):
            raise TrueNASError(f"GET /group failed: HTTP {resp.status_code} {resp.text}")
        matches = [g for g in resp.json() if g.get("group") == name]
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
        matches = [u for u in resp.json() if u.get("username") == username]
        return matches[0] if matches else None

    def list_editors(self) -> list[dict[str, Any]]:
        """Every TrueNAS user in the editors group (by db id membership)."""
        gid, _unix_gid = self.ensure_editors_group()
        resp = self.get("/user")
        if not ok(resp):
            raise TrueNASError(f"GET /user failed: HTTP {resp.status_code} {resp.text}")
        return [
            u for u in resp.json()
            if gid in (u.get("groups") or []) or (u.get("group") or {}).get("id") == gid
        ]

    def create_or_update_editor(self, username: str, ssh_pubkey: str,
                                 full_name: str | None = None) -> dict[str, Any]:
        """Create (or update in place) a TrueNAS editor account: installs the
        SSH key, enables SMB, fixes home-directory permissions. Mirrors
        server/setup_editor_account.py's main(), minus the SSH-based
        StrictModes re-verification (see module docstring).

        Returns a summary dict: {"created": bool, "username": str, "home_ok":
        bool, "warnings": [str, ...]}.
        """
        gid, unix_gid = self.ensure_editors_group()
        existing = self.find_user(username)
        warnings: list[str] = []

        if existing:
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
                "home": HOME_PARENT,
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
            user_id = resp.json()["id"]
            created = True

        resp = self.get(f"/user/id/{user_id}")
        if not ok(resp):
            raise TrueNASError(f"re-fetch user failed: HTTP {resp.status_code} {resp.text}")
        current = resp.json()

        if not current.get("sshpubkey"):
            warnings.append("sshpubkey is not set")
        if not current.get("smb"):
            warnings.append("smb flag is not set")
        if gid not in (current.get("groups") or []) and (current.get("group") or {}).get("id") != gid:
            warnings.append(f"user is not a member of group {EDITORS_GROUP!r}")

        home_ok = False
        if not warnings:
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
        job_id = resp.json()
        state, _error = self._wait_for_job(job_id)
        return state == "SUCCESS"

    def _wait_for_job(self, job_id: int, timeout: float = 120.0, poll: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(poll)
            resp = self.get("/core/get_jobs", params={"id": job_id})
            if not ok(resp):
                continue
            rows = resp.json()
            if not rows:
                continue
            job = rows[0]
            state = job.get("state")
            if state in ("SUCCESS", "FAILED", "ABORTED"):
                return state, job.get("error")
        return "TIMEOUT", f"job {job_id} did not finish within {timeout}s"

    def set_password(self, username: str) -> str:
        """Not used directly -- callers pass an explicit password via
        set_known_password(). Kept out of create_or_update_editor() itself
        because TrueNAS already randomizes it on creation and the admin UI
        offers setting a known one as a separate, explicit action (see
        SERVER.md's "Gotcha" about dashboard login needing a known password).
        """
        raise NotImplementedError("use set_known_password(username, password)")

    def set_known_password(self, username: str, password: str) -> None:
        user = self.find_user(username)
        if user is None:
            raise TrueNASError(f"no such user: {username!r}")
        resp = self.put(f"/user/id/{user['id']}", {"password": password})
        if not ok(resp):
            raise TrueNASError(f"set password failed: HTTP {resp.status_code} {resp.text}")
