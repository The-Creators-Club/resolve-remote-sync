"""Fakes for the Synology backend: an HTTP fake of the DSM web API (`FakeDSM`)
plus the in-memory `FakeSynology` NasBackend the WP1 seam tests use.

`FakeDSM` is written from the shapes recorded in
`docs/synology-spikes-2026-08-17.md` and re-probed against the DS423+ on
2026-08-17, and it reproduces DSM's TRAPS as faithfully as its successes --
that is the whole value of it:

* a `SYNO.API.Auth` login below version 7 yields a sid that reads fine and is
  refused with 105 on every mutation;
* any parameter arriving as `"True"`/`"False"` (a Python bool that skipped
  JSON serialisation) is error 3103;
* `SYNO.Core.Group.Member add` returns success while reading only `name`, so a
  client that sends `members` silently adds nobody;
* `SYNO.Core.Group list` carries no gids; only `get` does, and a missing group
  is success + `errors:[{"code":3205}]`;
* `SYNO.Core.User delete` wants a JSON array (3101 otherwise) and reports 3102
  in `errors` even when it worked.

The SSH half DSM has no API for is faked by `FakeDSM.ssh`, which is what
SynologyClient.ssh_runner takes: it records every command (so a test can prove
the client never chmods a home or anything under a share) and answers the
`stat -c '%a %U'` read-back the client verifies with.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from ccsync_dashboard.nas.base import EDITORS_GROUP, NasError, is_valid_username

PREFIX = "/webapi"

# DSM's real allocation policy (spike 7): local users from 1024 up, local
# groups from 65536 up, and a deleted uid is never reused. Note what that
# means for the refusals: `admin` (1024) and `guest` (1025) are ABOVE the
# floor, so a uid check alone does not catch them -- the name does.
FIRST_LOCAL_UID = 1024
FIRST_LOCAL_GID = 65536
BUILTIN_NAMES = frozenset({"admin", "guest", "anonymous", "root"})
HOME_ROOT = "/var/services/homes"

# Every API SynologyClient version-gates on, with this DSM's versions.
API_MANIFEST = {
    "SYNO.API.Auth": {"minVersion": 1, "maxVersion": 7, "path": "entry.cgi"},
    "SYNO.Core.User": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
    "SYNO.Core.Group": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
    "SYNO.Core.Group.Member": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
    "SYNO.Core.User.Group": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
    "SYNO.Core.User.Home": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
    "SYNO.Core.FileServ.FTP.SFTP": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
    "SYNO.Core.Share": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
    "SYNO.Core.Share.Permission": {"minVersion": 1, "maxVersion": 1, "path": "entry.cgi"},
}

# Methods DSM refuses (105) to a sid minted at login version < 7.
MUTATIONS = {"create", "set", "delete", "add", "remove", "change", "join"}


def unwrap_sudo_sh(command: str) -> str:
    """The script inside `sudo -S -p '' /bin/sh -c '<shlex.quoted script>'`.

    shlex.quote spells an embedded single quote as '"'"', so assertions (and
    this fake's own matching) have to undo it or they read nothing but escape
    soup."""
    _, _, quoted = command.partition("/bin/sh -c ")
    if quoted.startswith("'") and quoted.endswith("'"):
        quoted = quoted[1:-1]
    return quoted.replace("'\"'\"'", "'")


def default_state() -> dict:
    return {
        "requests": [],
        "account": "ccsync",
        "password": "fake-pw",
        # DSM's own built-ins are present because the refusals must be tested
        # against something real: `admin` is uid 1024, ABOVE TrueNAS's system
        # floor, so only the name check catches it.
        "users": [
            {"name": "admin", "uid": 1024, "description": "System default user",
             "email": "", "expired": "now"},
            {"name": "guest", "uid": 1025, "description": "Guest", "email": "",
             "expired": "now"},
            {"name": "Cablewrap", "uid": 1026, "description": "", "email": "",
             "expired": "normal"},
        ],
        "groups": [{"name": "administrators", "gid": 101}, {"name": "users", "gid": 100}],
        "members": {"administrators": ["admin", "Cablewrap"], "users": ["admin", "guest"]},
        "next_uid": 1030,
        "next_gid": FIRST_LOCAL_GID,
        "sids": {},
        "sid_seq": 0,
        "sftp": {"enable": True, "portnum": 22},
        "home": {"enable": True, "enable_domain": False, "enable_ldap": False,
                 "enable_recycle_bin": True, "encryption": 0, "location": "/volume1",
                 "remote_location": "", "userhome_in_s2s": False},
        # Set to 6 to simulate a DSM whose SYNO.API.Auth tops out below 7 --
        # the shape check must refuse the box outright.
        "auth_max_version": 7,
        # Names to drop from SYNO.API.Info, for the "refuse to guess" test.
        "hide_apis": set(),
        # --- the SSH half -------------------------------------------------
        "ssh_commands": [],
        "ssh_stdin": [],
        "ssh_available": True,
        "authorized_keys": {},
        # per-user home mode, as `stat -c '%a %U'` would report it. DSM ships
        # homes 711; a test can set 777 to reproduce the StrictModes refusal.
        "home_modes": {},
        "missing_homes": set(),
        # Which parameter Group.Member add actually reads. DSM reads `name`;
        # set this to "members" to reproduce a DSM that reads something else
        # (which is exactly how the trap presents: success, and nobody added).
        "member_add_param": "name",
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    # ------------------------------------------------------------ plumbing

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data=None):
        self._send({"data": data if data is not None else {}, "success": True})

    def _err(self, code: int):
        self._send({"error": {"code": code}, "success": False})

    def do_GET(self):
        url = urlparse(self.path)
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        self._dispatch(url.path, params, post=False)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else ""
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        params.update({k: v[-1] for k, v in parse_qs(raw).items()})
        self._dispatch(url.path, params, post=True)

    # ------------------------------------------------------------ dispatch

    def _dispatch(self, path: str, params: dict[str, str], post: bool):
        state = self.server.state              # type: ignore[attr-defined]
        state.setdefault("requests", []).append({"path": path, "params": dict(params),
                                                 "post": post})
        api = params.get("api", "")
        method = params.get("method", "")
        version = int(params.get("version") or 0)

        # DSM's 3103: a Python bool that never went through json.dumps arrives
        # as "True"/"False" and the parser rejects the whole call.
        if any(v in ("True", "False") for k, v in params.items() if k != "passwd"):
            return self._err(3103)

        if api == "SYNO.API.Info":
            return self._api_info(state, params)
        if api == "SYNO.API.Auth":
            return self._auth(state, method, version, params)

        entry = API_MANIFEST.get(api)
        if entry is None:
            return self._err(103)
        if not (entry["minVersion"] <= version <= entry["maxVersion"]):
            return self._err(103)

        sid = params.get("_sid", "")
        session = state["sids"].get(sid)
        if session is None:
            return self._err(119)
        # THE trap: a v6 sid reads happily and is refused on every mutation.
        if method in MUTATIONS and session["version"] < 7:
            return self._err(105)

        handler = {
            "SYNO.Core.User": self._user,
            "SYNO.Core.Group": self._group,
            "SYNO.Core.Group.Member": self._member,
            "SYNO.Core.User.Group": self._user_group,
            "SYNO.Core.User.Home": self._user_home,
            "SYNO.Core.FileServ.FTP.SFTP": self._sftp,
        }.get(api)
        if handler is None:
            return self._err(103)
        return handler(state, method, params)

    # ------------------------------------------------------------ the APIs

    def _api_info(self, state, params):
        wanted = [q.strip() for q in (params.get("query") or "all").split(",")]
        manifest = {}
        for name, entry in API_MANIFEST.items():
            if name in state["hide_apis"]:
                continue
            if wanted != ["all"] and name not in wanted:
                continue
            row = dict(entry)
            if name == "SYNO.API.Auth":
                row["maxVersion"] = state["auth_max_version"]
            manifest[name] = row
        self._ok(manifest)

    def _auth(self, state, method, version, params):
        if method == "logout":
            state["sids"].pop(params.get("_sid", ""), None)
            return self._ok()
        if method != "login":
            return self._err(103)
        if version > state["auth_max_version"] or version < 1:
            return self._err(103)
        if params.get("account") != state["account"] or params.get("passwd") != state["password"]:
            return self._err(400)
        state["sid_seq"] += 1
        sid = f"fake-sid-{state['sid_seq']}"
        state["sids"][sid] = {"version": version, "session": params.get("session", "")}
        self._ok({"account": params.get("account"), "device_id": "fake-device",
                  "ik_message": "", "is_portal_port": False, "sid": sid,
                  "synotoken": f"fake-token-{state['sid_seq']}"})

    # ---- users

    def _user(self, state, method, params):
        if method == "list":
            if params.get("type") != "local":
                return self._err(3103)
            rows = [self._user_row(u, params) for u in state["users"]]
            offset = int(params.get("offset") or 0)
            limit = int(params.get("limit") or 50)
            return self._ok({"offset": offset, "total": len(rows),
                             "users": rows[offset:offset + limit]})
        if method == "get":
            names = _as_list(params.get("name"))
            rows = [self._user_row(u, params) for u in state["users"] if u["name"] in names]
            if not rows:
                return self._err(3106)
            return self._ok({"users": rows})
        if method == "create":
            name = params.get("name") or ""
            if any(u["name"].casefold() == name.casefold() for u in state["users"]):
                return self._err(3107)
            if not params.get("password"):
                return self._err(3103)
            uid = state["next_uid"]
            state["next_uid"] += 1
            state["users"].append({
                "name": name, "uid": uid, "description": params.get("description", ""),
                "email": params.get("email", ""), "expired": params.get("expired", "normal"),
                "password": params.get("password"),
            })
            # DSM's primary group for every local user is `users`, always.
            state["members"].setdefault("users", []).append(name)
            return self._ok({"name": name, "uid": uid})
        if method == "set":
            user = _find(state["users"], params.get("name"))
            if user is None:
                return self._err(3106)
            for key in ("description", "email", "expired", "password"):
                if key in params:
                    user[key] = params[key]
            return self._ok({"name": user["name"], "password_last_change": 20682,
                             "uid": user["uid"]})
        if method == "delete":
            raw = params.get("name") or ""
            if not raw.startswith("["):        # a bare string is error 3101
                return self._err(3101)
            names = _as_list(raw)
            state["users"] = [u for u in state["users"] if u["name"] not in names]
            for members in state["members"].values():
                members[:] = [m for m in members if m not in names]
            # 3102 shows up in errors even on a successful delete.
            return self._ok({"errors": [3102]})
        return self._err(103)

    @staticmethod
    def _user_row(user: dict, params: dict) -> dict:
        row = {"name": user["name"], "uid": user["uid"]}
        for key in _as_list(params.get("additional") or "[]"):
            if key in user:
                row[key] = user[key]
        return row

    # ---- groups

    def _group(self, state, method, params):
        if method == "list":
            rows = [{"name": g["name"], "description": ""} for g in state["groups"]]
            offset = int(params.get("offset") or 0)
            limit = int(params.get("limit") or 50)
            # No gid, not even with `additional` -- measured 2026-08-17.
            return self._ok({"offset": offset, "total": len(rows),
                             "groups": rows[offset:offset + limit]})
        if method == "get":
            names = _as_list(params.get("name"))
            found, errors = [], []
            for name in names:
                group = _find(state["groups"], name)
                if group is None:
                    errors.append({"code": 3205, "name": name})
                else:
                    found.append({"name": group["name"], "gid": group["gid"], "description": ""})
            return self._ok({"errors": errors, "groups": found})
        if method == "create":
            name = params.get("name") or ""
            if _find(state["groups"], name) is not None:
                return self._err(3206)
            gid = state["next_gid"]
            state["next_gid"] += 1
            state["groups"].append({"name": name, "gid": gid})
            state["members"].setdefault(name, [])
            return self._ok({"gid": gid, "name": name})
        if method == "delete":
            for name in _as_list(params.get("name")):
                state["groups"] = [g for g in state["groups"] if g["name"] != name]
                state["members"].pop(name, None)
            return self._ok()
        return self._err(103)

    def _member(self, state, method, params):
        group = params.get("group") or ""
        if _find(state["groups"], group) is None:
            return self._err(3205)
        if method == "list":
            names = state["members"].get(group, [])
            rows = [{"name": u["name"], "uid": u["uid"], "description": u.get("description", "")}
                    for u in state["users"] if u["name"] in names]
            offset = int(params.get("offset") or 0)
            limit = int(params.get("limit") or 50)
            return self._ok({"offset": offset, "total": len(rows),
                             "users": rows[offset:offset + limit]})
        if method == "add":
            # THE silent no-op: `members` is ignored, `name` is what DSM reads,
            # and the answer is success either way.
            for name in _as_list(params.get(state["member_add_param"]) or "[]"):
                if _find(state["users"], name) and name not in state["members"].setdefault(group, []):
                    state["members"][group].append(name)
            return self._ok()
        if method == "remove":
            for name in _as_list(params.get("name") or "[]"):
                if name in state["members"].get(group, []):
                    state["members"][group].remove(name)
            return self._ok()
        return self._err(103)

    def _user_group(self, state, method, params):
        if method != "get":
            return self._err(103)
        name = params.get("name") or ""
        if _find(state["users"], name) is None:
            return self._err(3106)
        return self._ok({"groups": sorted(g for g, members in state["members"].items()
                                          if name in members)})

    def _user_home(self, state, method, params):
        if method != "get":
            return self._err(103)
        return self._ok(dict(state["home"]))

    def _sftp(self, state, method, params):
        if method == "get":
            return self._ok(dict(state["sftp"]))
        if method == "set":
            state["sftp"] = {"enable": params.get("enable") == "true",
                             "portnum": int(params.get("portnum") or 22)}
            return self._ok()
        return self._err(103)


def _as_list(raw: Any) -> list[str]:
    """DSM accepts a JSON array, a JSON string or a bare string for `name`."""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if raw is None:
        return []
    text = str(raw)
    if text.startswith("[") or text.startswith('"'):
        try:
            value = json.loads(text)
        except ValueError:
            return [text]
        return [str(x) for x in value] if isinstance(value, list) else [str(value)]
    return [text]


def _find(rows: list[dict], name: str | None) -> dict | None:
    return next((r for r in rows if name is not None and r["name"] == name), None)


class FakeDSM:
    """A DSM web API on 127.0.0.1, plus the SSH channel the real backend needs
    for authorized_keys. Point SynologyClient at `base_url` and pass `ssh` as
    its ssh_runner."""

    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.state = default_state()     # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def state(self) -> dict:
        return self.httpd.state                # type: ignore[attr-defined]

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}{PREFIX}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    # ---------------------------------------------------------- the SSH half

    def ssh(self, command: str, stdin_text: str) -> tuple[int, str, str]:
        """Stands in for paramiko. Records the command verbatim -- the shape of
        it is what the tests assert on, because a stray `chmod` on a home or
        under a share is the destructive mistake this backend must never make
        (spike 1)."""
        state = self.state
        state["ssh_commands"].append(command)
        state["ssh_stdin"].append(stdin_text)
        if not state["ssh_available"]:
            raise NasError("SSH to dsm.example:22 as 'ccsync' failed: simulated outage")
        script = unwrap_sudo_sh(command)

        if "HASKEY" in script:
            names = re.findall(r"for u in (.*?); do", script, re.S)
            listed = names[0].replace("'", "").split() if names else []
            out = "".join(f"HASKEY {u}\n" for u in listed
                          if state["authorized_keys"].get(u))
            return 0, out, ""

        match = re.search(rf"home='?{re.escape(HOME_ROOT)}/([A-Za-z0-9._-]+)'?", script)
        if not match:
            return 1, "", "fake ssh: unrecognised command"
        user = match.group(1)
        if user in state["missing_homes"] or _find(state["users"], user) is None:
            return 3, "MISSING_HOME\n", ""
        key = re.search(r"printf '%s\\n' '(.*?)' >", script, re.S)
        if key:
            state["authorized_keys"][user] = key.group(1)
        home_mode = state["home_modes"].get(user, "711")
        out = (f"HOME {home_mode} {user}\n"
               f"SSHDIR 700 {user}\n"
               f"KEYS 600 {user}\n"
               f"SHELL /sbin/nologin\n")
        return 0, out, ""


class FakeSynology:
    """The WP1 in-memory NasBackend stand-in, kept because it is the cheapest
    way to run the admin call sites against "a backend that is not TrueNAS and
    not a fake HTTP server either" -- it proves the seam, where FakeDSM proves
    the DSM client. `state` is public so tests can seed accounts.
    """

    def __init__(self) -> None:
        self.state: dict[str, Any] = {
            "users": [],
            "groups": [],
            "next_uid": 1030,
            "next_gid": FIRST_LOCAL_GID,
            # set True to make every call fail the way an unreachable DSM does
            "down": False,
            # usernames whose home cannot take an authorized_keys write
            "block_sshpubkey_usernames": set(),
        }

    # ---------------------------------------------------------- helpers

    def _check_up(self) -> None:
        if self.state["down"]:
            raise NasError("cannot reach the DSM web API at dsm.example: simulated outage")

    def _group(self, name: str) -> dict[str, Any] | None:
        return next((g for g in self.state["groups"] if g["group"] == name), None)

    def _in_editors_group(self, user: dict[str, Any], gid: int) -> bool:
        return gid in (user.get("groups") or [])

    # ---------------------------------------------------------- NasBackend

    def ping(self) -> None:
        self._check_up()

    def find_group(self, name: str) -> dict[str, Any] | None:
        self._check_up()
        return self._group(name)

    def ensure_editors_group(self) -> tuple[int, int]:
        self._check_up()
        existing = self._group(EDITORS_GROUP)
        if existing:
            return existing["id"], existing["gid"]
        gid = self.state["next_gid"]
        self.state["next_gid"] += 1
        # DSM has no separate db id for a group -- the gid IS the id, which is
        # why NasBackend.ensure_editors_group returns a pair rather than
        # assuming TrueNAS' two-number world.
        self.state["groups"].append({"id": gid, "group": EDITORS_GROUP, "gid": gid})
        return gid, gid

    def find_user(self, username: str) -> dict[str, Any] | None:
        self._check_up()
        return next((u for u in self.state["users"] if u["username"] == username), None)

    def list_editors(self) -> list[dict[str, Any]]:
        gid, _unix_gid = self.ensure_editors_group()
        return [u for u in self.state["users"] if self._in_editors_group(u, gid)]

    def is_editor(self, username: str) -> bool:
        if not is_valid_username(username):
            return False
        gid, _unix_gid = self.ensure_editors_group()
        user = self.find_user(username)
        if user is None:
            return False
        if int(user.get("uid", 0)) < FIRST_LOCAL_UID or username in BUILTIN_NAMES:
            return False
        return self._in_editors_group(user, gid)

    def create_or_update_editor(self, username: str, ssh_pubkey: str,
                                full_name: str | None = None) -> dict[str, Any]:
        gid, _unix_gid = self.ensure_editors_group()
        existing = self.find_user(username)
        warnings: list[str] = []

        if existing:
            if int(existing.get("uid", 0)) < FIRST_LOCAL_UID or username in BUILTIN_NAMES:
                raise NasError(
                    f"{username!r} is a system account (uid {existing.get('uid')}) -- refusing "
                    "to modify it. Pick a different username."
                )
            if not self._in_editors_group(existing, gid):
                raise NasError(
                    f"{username!r} already exists on the NAS and is not in the "
                    f"{EDITORS_GROUP!r} group -- refusing to take over an account this "
                    "dashboard didn't create."
                )
            if username in self.state["block_sshpubkey_usernames"]:
                raise NasError(f"{username!r}: home directory is not writable")
            existing["sshpubkey"] = ssh_pubkey
            existing["smb"] = True
            row, created = existing, False
        else:
            uid = self.state["next_uid"]
            self.state["next_uid"] += 1
            row = {
                "id": uid, "uid": uid, "username": username,
                "full_name": full_name or username,
                "home": f"{HOME_ROOT}/{username}",
                "groups": [gid], "sshpubkey": ssh_pubkey, "smb": True,
                "locked": False,
                # DSM users get /sbin/nologin by default, which is what the
                # port wants (COMMERCIAL_READINESS H4) -- SFTP does not need
                # an interactive shell.
                "shell": "/sbin/nologin",
            }
            self.state["users"].append(row)
            created = True

        if not row.get("sshpubkey"):
            warnings.append("sshpubkey is not set")
        return {"created": created, "username": username,
                "home_ok": username not in self.state["block_sshpubkey_usernames"],
                "warnings": warnings}

    def set_known_password(self, username: str, password: str) -> None:
        if not is_valid_username(username):
            raise NasError(
                f"invalid username {username!r}: must start with a letter and contain only "
                "lowercase letters, digits, '.', '_', '-'"
            )
        gid, _unix_gid = self.ensure_editors_group()
        user = self.find_user(username)
        if user is None:
            raise NasError(f"no such user: {username!r}")
        if int(user.get("uid", 0)) < FIRST_LOCAL_UID or username in BUILTIN_NAMES:
            raise NasError(
                f"{username!r} is a system account (uid {user.get('uid')}) -- refusing to set "
                "its password. This dashboard only manages editor accounts."
            )
        if not self._in_editors_group(user, gid):
            raise NasError(
                f"{username!r} is not in the {EDITORS_GROUP!r} group -- refusing to set the "
                "password of an account this dashboard didn't create."
            )
        user["password"] = password
