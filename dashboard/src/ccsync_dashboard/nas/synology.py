"""Synology DSM 7.2+ backend for the runtime NAS seam (SYNOLOGY_PORT_PLAN.md WP2).

Two channels, because DSM needs both:

* the **DSM Web API** on :5001 (`SYNO.API.Info` -> `SYNO.API.Auth` sid ->
  `SYNO.Core.User` / `SYNO.Core.Group` / `SYNO.Core.Group.Member` /
  `SYNO.Core.User.Group`) for identity: create the account, put it in
  `editors`, set a password, list the fleet;
* an **SSH channel** (paramiko, lazily imported) for `authorized_keys`, which
  DSM exposes no API for at all. It cannot be done over FileStation either:
  a file written that way is owned by the admin, and sshd's StrictModes then
  refuses the key silently (spike 2 -- DSM logs NOTHING for a StrictModes
  refusal, so the only symptom is the editor's "Authentication failed").

Everything here is coded from `docs/synology-spikes-2026-08-17.md`, measured on
a DS423+ running DSM 7.2.1-69057 U6, and re-probed on 2026-08-17 before this
file was written. The traps that shape the code, all of them measured:

1. **`SYNO.API.Auth` must be version 7.** A v6 login returns a perfectly good
   sid that can `list` and `get` and is refused on EVERY mutation with error
   105 / `x-request-error: noprivilege` -- for a full administrators-group
   account. Nothing else (SynoToken, Referer, session name, port) moves it.
2. **Every parameter is JSON.** A Python `False` reaches DSM as `"False"` and
   earns error 3103. `_param()` is the single place that serialises, and the
   only way values are allowed to reach the wire.
3. **`SYNO.Core.Group.Member add` lies.** It returns `{"success": true}`
   whatever you send it, and the parameter it actually reads is `name` (a JSON
   array), not `members`. Membership is therefore always READ BACK.
4. **`SYNO.Core.Group list` does not return gids** (not even with
   `additional`); `SYNO.Core.Group get` does, and reports a missing group as
   `success:true` with `errors:[{"code":3205}]`. Measured 2026-08-17.
5. **`chmod`/`chown` under a shared folder destroys the Synology ACL** (spike
   1: the path flips to "Linux mode", inheritance is gone, and DSM's
   `internal-sftp -u 000` then leaves every new file world-writable). Hence
   `_install_ssh_key` touches `~/.ssh` and nothing above it: the home itself
   is DSM's 711 and already satisfies StrictModes -- do NOT chmod it.

Deliberately NOT done here, with reasons: no `SYNO.Core.AppPriv` grant (the
privilege is `SYNO.SFTP`, it is `grant_by_default: true`, so granting is a
no-op and only a DENY would matter -- WP3's `grant_sftp` verifies instead);
no `SYNO.Core.Share*` calls (share/ACL creation is install-time, WP3); no
`SYNO.Core.User.PasswordConfirm` retry (with a v7 login not one call needed
it, and a retry shape nobody has exercised is exactly the guess this module
refuses to make -- the 105 message names it as the next thing to try).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .base import EDITORS_GROUP, NasError, is_valid_username

log = logging.getLogger("ccsync.dashboard.nas.synology")

# DSM's HTTPS admin port. Overridable because a site can move it, and because
# the DSM reverse proxy in front of it is a normal deployment.
DEFAULT_DSM_PORT = 5001
DEFAULT_SSH_PORT = 22

# SYNO.API.Auth version 7 or nothing -- see trap 1 in the module docstring.
LOGIN_VERSION = 7
# Named session: DSM tracks sids per session name, so logging this client out
# cannot take the operator's own DSM browser session with it.
SESSION_NAME = "ccsync"

# The API/version pairs this module calls, checked against SYNO.API.Info before
# the first login. Share/Share.Permission are in here although WP2 never calls
# them: they are what WP3's installer and the setup checklist provision the
# tree with, and one shape check that fails on the dashboard's first NAS call
# beats a mystery halfway through an install.
REQUIRED_APIS = {
    "SYNO.API.Auth": LOGIN_VERSION,
    "SYNO.Core.User": 1,
    "SYNO.Core.Group": 1,
    "SYNO.Core.Group.Member": 1,
    "SYNO.Core.User.Group": 1,
    "SYNO.Core.User.Home": 1,
    "SYNO.Core.FileServ.FTP.SFTP": 1,
    "SYNO.Core.Share": 1,
    "SYNO.Core.Share.Permission": 1,
}

# DSM allocates local users from 1024 up (admin=1024, guest=1025 on the spike
# box) and never reuses a deleted uid; package accounts live at 170000+.
# Both ends are refused: below is a built-in, above is somebody's *arr stack.
MIN_EDITOR_UID = 1024
PACKAGE_UID_FLOOR = 170000
# Names that no uid check catches: package accounts (`sc-*`, SynoCommunity's
# convention) are not returned by SYNO.Core.User list at all, so their uid is
# never seen -- refuse them by name before the API is even asked.
RESERVED_USERNAMES = frozenset({"admin", "guest", "anonymous", "root", "system", "http"})
RESERVED_PREFIXES = ("sc-",)

# Every DSM local user's primary group is `users` (gid 100) and synouser gives
# no way to change it -- `editors` is supplementary membership only (spike 7).
PRIMARY_GROUP = "users"
# /var/services/homes/<u> is the stable, volume-independent spelling of
# <User.Home location>/homes/<u> (DSM symlinks it); using it means a site whose
# homes live on /volume2 needs no special case.
HOME_ROOT = "/var/services/homes"

# The Synology CLIs are not on sudo's PATH on a stock DSM box, and neither is
# anything else outside /bin (spike report, "PATH note that cost the first ten
# minutes"). Prefixed to every remote command.
SSH_PATH_EXPORT = "export PATH=/usr/syno/bin:/usr/syno/sbin:/usr/local/bin:$PATH"

# DSM error codes seen on the wire (spike 3 plus the 2026-08-17 re-probe).
# The text is what an admin reads in the banner, so it says what to DO.
DSM_ERRORS = {
    103: "no such method (this DSM does not implement the call)",
    105: ("the logged-in session has no privilege for this call -- the usual cause is a sid "
          f"minted with SYNO.API.Auth < {LOGIN_VERSION}, which DSM refuses on every mutation. "
          "If this account really is in `administrators` and login already used version "
          f"{LOGIN_VERSION}, the next thing to try is SYNO.Core.User.PasswordConfirm"),
    119: "the session id expired",
    400: "invalid account or password",
    401: "the account is disabled",
    402: "the account has no permission to log in to DSM",
    403: "the account needs a 2-factor code -- give the dashboard an account with 2FA off",
    404: "the 2-factor code was wrong",
    3101: "bad argument (a name that had to be a JSON array was sent as a string)",
    3103: ("invalid parameter -- classically a Python bool serialised as \"True\"/\"False\" "
           "instead of JSON true/false"),
    3106: "no such user",
    3107: "that user already exists",
    3117: "the password does not satisfy this DSM's password policy",
    3201: "bad group argument",
    3205: "no such group",
    3206: "that group already exists",
}


class DsmApiError(NasError):
    """A DSM call that answered `success:false`. Carries the numeric code so
    callers can branch on the handful that mean something specific (119 sid
    expired, 3106 no such user, 3205/3206 group) without matching on text."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _verify_setting() -> bool | str:
    """TLS verification default, same contract as the TrueNAS client's twin
    (bool, or a CA bundle path). Duplicated rather than shared because each
    backend owns its own default and neither should import the other; WP3 can
    lift it into base.py if a third backend wants it.

    Only reached when a caller builds this client WITHOUT passing verify_ssl --
    nas.factory always passes settings.nas_verify_ssl.
    """
    raw = (os.environ.get("DASH_NAS_VERIFY_SSL", "").strip()
           or os.environ.get("TRUENAS_VERIFY_SSL", "").strip())
    if not raw:
        return False
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return raw  # a CA bundle path


def _ssh_port_setting() -> int:
    """DSM_NAS_SSH_PORT is read here rather than plumbed through Settings so
    the factory stays backend-neutral (it builds every backend from the same
    five values). A non-22 SSH port is common on DSM."""
    raw = os.environ.get("DASH_NAS_SSH_PORT", "").strip()
    try:
        return int(raw) if raw else DEFAULT_SSH_PORT
    except ValueError:
        log.warning("DASH_NAS_SSH_PORT=%r is not a number -- using %d", raw, DEFAULT_SSH_PORT)
        return DEFAULT_SSH_PORT


def _key_probe_setting() -> bool:
    return (os.environ.get("DASH_NAS_SSH_KEY_PROBE", "").strip() or "1") not in ("0", "false", "no")


def _param(value: Any) -> str:
    """The ONE place a value becomes a DSM parameter. Trap 2: DSM's parser
    wants JSON, and `requests` renders a Python bool as "True" -- which is not
    JSON, and comes back as error 3103 with no hint of which parameter."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(list(value) if isinstance(value, tuple) else value)
    if isinstance(value, int):
        return str(value)
    return str(value)


def _dsm_message(code: int) -> str:
    return DSM_ERRORS.get(code, f"DSM error {code}")


# The remote script that installs a key. Every interpolation is shlex.quote'd
# by the caller. What it deliberately does NOT do (spike 1 + spike 2):
#   * no chmod/chown of the home itself -- DSM's 711 already satisfies
#     StrictModes, and a chmod would delete the home's Synology ACL;
#   * no touch of anything under a shared folder, ever.
# The write is tmp+mv so a half-written authorized_keys can never be the file
# sshd reads, and `umask 077` means even the tmp file is never group-readable.
_INSTALL_KEY_SCRIPT = """\
{path_export}
set -e
home={home}
if [ ! -d "$home" ]; then echo MISSING_HOME; exit 3; fi
umask 077
mkdir -p "$home/.ssh"
printf '%s\\n' {key} > "$home/.ssh/.authorized_keys.ccsync"
mv -f "$home/.ssh/.authorized_keys.ccsync" "$home/.ssh/authorized_keys"
chown -R {owner} "$home/.ssh"
chmod 700 "$home/.ssh"
chmod 600 "$home/.ssh/authorized_keys"
printf 'HOME %s\\n' "$(stat -c '%a %U' "$home")"
printf 'SSHDIR %s\\n' "$(stat -c '%a %U' "$home/.ssh")"
printf 'KEYS %s\\n' "$(stat -c '%a %U' "$home/.ssh/authorized_keys")"
printf 'SHELL %s\\n' "$(getent passwd {user} | cut -d: -f7)"
"""

# One exec for the whole editor list: DSM has no API that answers "does this
# account have an authorized_keys", and N SSH round trips on an admin page
# render would be absurd.
_KEY_PROBE_SCRIPT = """\
{path_export}
for u in {users}; do
  if [ -s {home_root}/"$u"/.ssh/authorized_keys ]; then printf 'HASKEY %s\\n' "$u"; fi
done
"""


@dataclass
class SynologyClient:
    """NasBackend for DSM 7.2+. The first four positional arguments are fixed
    by nas.factory.make_nas_client; everything after them is defaulted (and
    env-driven where a site might need to move it) so the factory can stay
    backend-neutral."""

    host: str
    user: str
    pw: str
    verify_ssl: bool | str = field(default_factory=_verify_setting)
    port: int = DEFAULT_DSM_PORT
    ssh_port: int = field(default_factory=_ssh_port_setting)
    timeout: float = 15.0
    session: requests.Session = field(default_factory=requests.Session)
    # Same escape hatch as TrueNASClient.base_url: tests point this at a
    # plain-http fake instead of also having to fake DSM's TLS.
    base_url: str | None = None
    # The SSH half, injected. Signature: (command: str, stdin_text: str) ->
    # (exit_status, stdout, stderr). None means "open a real paramiko session";
    # tests pass a callable and assert on the command SHAPE, which is the part
    # that can quietly become destructive (a stray chmod under a share).
    ssh_runner: Callable[[str, str], tuple[int, str, str]] | None = None
    probe_ssh_keys: bool = field(default_factory=_key_probe_setting)

    _sid: str | None = field(default=None, init=False, repr=False)
    _token: str = field(default="", init=False, repr=False)
    _paths: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _shapes_checked: bool = field(default=False, init=False, repr=False)
    _ssh: Any = field(default=None, init=False, repr=False)
    _key_probe_cache: dict[str, bool] | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------- transport

    @property
    def webapi_base(self) -> str:
        return self.base_url or f"https://{self.host}:{self.port}/webapi"

    def __enter__(self) -> SynologyClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        # A safety net, not the mechanism: unlike TrueNAS's basic auth, every
        # DSM call needs a sid, and api.py builds a client per request and
        # drops it -- so without this a busy admin page would leave one live
        # DSM session behind per render. Guarded absolutely, because __del__
        # can run during interpreter shutdown when `requests` is half-torn-down
        # and an exception here would print a traceback nobody can act on.
        try:
            self.close()
        except BaseException:
            pass

    def close(self) -> None:
        """Log the sid out and drop the SSH channel. DSM keeps a bounded
        number of sessions per account; a dashboard that logs in on every
        admin request and never logs out eventually gets refused."""
        if self._sid:
            try:
                self._request("SYNO.API.Auth", "logout", LOGIN_VERSION,
                              post=True, session=SESSION_NAME)
            except NasError:
                pass  # logging out of a NAS we can no longer reach is not an error
            self._sid = None
            self._token = ""
        if self._ssh is not None:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None

    def _url(self, api: str) -> str:
        # SYNO.API.Info reports each API's cgi; entry.cgi for everything we
        # call on 7.2.1, but taking it from the manifest is what makes this
        # "recorded" rather than "assumed".
        return f"{self.webapi_base}/{self._paths.get(api, 'entry.cgi')}"

    def _http(self, url: str, params: dict[str, str], post: bool) -> requests.Response:
        headers = {"X-SYNO-TOKEN": self._token} if self._token else {}
        try:
            if post:
                return self.session.post(url, data=params, headers=headers,
                                         verify=self.verify_ssl, timeout=self.timeout)
            return self.session.get(url, params=params, headers=headers,
                                    verify=self.verify_ssl, timeout=self.timeout)
        except requests.RequestException as exc:
            raise NasError(
                f"cannot reach the DSM web API at {self.host}:{self.port}: {exc}") from exc

    @staticmethod
    def _json(resp: requests.Response, what: str) -> dict[str, Any]:
        """resp.json() that cannot 500 the page: a 2xx carrying HTML (a proxy's
        error page, or DSM's login redirect) raises JSONDecodeError, which
        escapes every `except NasError` and produces a traceback instead of
        the intended banner. Copied in spirit from TrueNASClient._json."""
        if not (200 <= resp.status_code < 300):
            raise NasError(f"{what}: DSM answered HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise NasError(f"{what}: response was not JSON ({resp.text[:120]!r})") from exc
        if not isinstance(body, dict):
            raise NasError(f"{what}: response was not a JSON object ({resp.text[:120]!r})")
        return body

    def _request(self, api: str, method: str, version: int, post: bool = False,
                 **kwargs: Any) -> dict[str, Any]:
        """One DSM call, no session handling. Returns the `data` object."""
        params = {"api": api, "method": method, "version": _param(version)}
        params.update({k: _param(v) for k, v in kwargs.items() if v is not None})
        if self._sid:
            params["_sid"] = self._sid
        if self._token:
            params["SynoToken"] = self._token
        what = f"{api}.{method}"
        body = self._json(self._http(self._url(api), params, post), what)
        if not body.get("success"):
            code = int((body.get("error") or {}).get("code") or 0)
            raise DsmApiError(code, f"{what} failed: DSM error {code} -- {_dsm_message(code)}")
        return body.get("data") or {}

    def _call(self, api: str, method: str, version: int = 1, post: bool = False,
              **kwargs: Any) -> dict[str, Any]:
        """A DSM call with a session, retried ONCE on 119 (sid expired).

        119 is expected in normal operation: DSM ages sessions out, and this
        client is built per request but a long-lived one would hit it. Anything
        else is reported as-is -- 105 in particular must NOT be retried, it
        means the login version was wrong and retrying just doubles the wait.
        """
        self._ensure_session()
        try:
            return self._request(api, method, version, post=post, **kwargs)
        except DsmApiError as exc:
            if exc.code != 119:
                raise
            log.info("DSM session expired mid-call (%s.%s); logging in again", api, method)
            self._sid, self._token = None, ""
            self._ensure_session()
            return self._request(api, method, version, post=post, **kwargs)

    # --------------------------------------------------------------- session

    def _api_info(self) -> dict[str, Any]:
        params = {"api": "SYNO.API.Info", "version": "1", "method": "query",
                  "query": ",".join(sorted(REQUIRED_APIS))}
        resp = self._http(f"{self.webapi_base}/query.cgi", params, post=False)
        body = self._json(resp, "SYNO.API.Info.query")
        if not body.get("success"):
            raise NasError(
                f"the DSM web API at {self.host}:{self.port} refused SYNO.API.Info -- "
                "this does not look like a DSM 7 box")
        return body.get("data") or {}

    def _check_api_shapes(self) -> None:
        """Refuse to guess: every API this module calls must be advertised at
        the version it is called with, and SYNO.API.Auth must offer version 7.

        A DSM that offers Auth <= 6 is not "slightly older" -- it is a box on
        which every mutation returns 105, i.e. one where accounts would be
        half-created (user exists, never added to `editors`, no key). Better to
        say so before the first editor than after (spike 3.1).
        """
        if self._shapes_checked:
            return
        info = self._api_info()
        problems: list[str] = []
        for api, want in sorted(REQUIRED_APIS.items()):
            entry = info.get(api)
            if not isinstance(entry, dict):
                problems.append(f"{api}: not offered by this DSM")
                continue
            self._paths[api] = str(entry.get("path") or "entry.cgi")
            low, high = int(entry.get("minVersion") or 1), int(entry.get("maxVersion") or 0)
            if not (low <= want <= high):
                problems.append(f"{api}: need version {want}, this DSM offers {low}-{high}")
        if problems:
            raise NasError(
                "this DSM does not offer the web API shapes CC Sync provisions with: "
                + "; ".join(problems)
                + ". Provision editors in DSM's Control Panel instead, or open an issue with "
                  "this message -- guessing at a different shape risks half-created accounts."
            )
        self._shapes_checked = True

    def _ensure_session(self) -> None:
        if self._sid:
            return
        self._check_api_shapes()
        if not self.pw:
            raise NasError("no DSM password configured (DASH_NAS_PW)")
        params = {
            "api": "SYNO.API.Auth", "method": "login", "version": _param(LOGIN_VERSION),
            "account": self.user, "passwd": self.pw, "session": SESSION_NAME,
            "format": "sid", "enable_syno_token": "yes",
        }
        # The password goes in the body, not a query string: DSM logs request
        # lines for GETs, and its own UI posts the login.
        body = self._json(self._http(self._url("SYNO.API.Auth"), params, post=True),
                          "SYNO.API.Auth.login")
        if not body.get("success"):
            code = int((body.get("error") or {}).get("code") or 0)
            raise NasError(
                f"DSM login for {self.user!r} failed: error {code} -- {_dsm_message(code)}")
        data = body.get("data") or {}
        sid = data.get("sid")
        if not sid:
            raise NasError("DSM login succeeded but returned no sid (format=sid was ignored)")
        self._sid = str(sid)
        self._token = str(data.get("synotoken") or "")

    # ------------------------------------------------------------ NasBackend

    def ping(self) -> None:
        """Reachability + shape check + credentials, with no side effect.

        Wider than the WP1 stub's unauthenticated probe, and deliberately the
        same contract as TrueNASClient.ping: a green ping means "DSM answers,
        it speaks the APIs we provision with, these credentials work, and they
        can read groups" -- which is what the admin section needs to know.
        """
        self.find_group(EDITORS_GROUP)

    # ----------------------------------------------------------------- groups

    def find_group(self, name: str) -> dict[str, Any] | None:
        """Keys mirror the TrueNAS client's group rows (`group`, `gid`, `id`)
        so no caller has to know which NAS answered. On DSM the gid IS the id.

        `SYNO.Core.Group list` does NOT carry gids -- not even with
        `additional` (measured 2026-08-17) -- so this is `get`, which reports a
        missing group as success + `errors:[{"code":3205}]` rather than an
        error response.
        """
        data = self._call("SYNO.Core.Group", "get", 1, name=[name])
        for row in data.get("groups") or []:
            if row.get("name") == name:
                gid = int(row["gid"])
                return {"id": gid, "gid": gid, "group": name,
                        "description": row.get("description") or ""}
        return None

    def ensure_editors_group(self) -> tuple[int, int]:
        """(db_id, unix_gid) for `editors`, creating it if missing. DSM has no
        separate db id for a group, so both halves are the gid -- the pair
        exists for TrueNAS, where they differ."""
        existing = self.find_group(EDITORS_GROUP)
        if existing:
            return existing["id"], existing["gid"]
        try:
            data = self._call("SYNO.Core.Group", "create", 1, post=True, name=EDITORS_GROUP)
        except DsmApiError as exc:
            # 3206 = created by someone else between the read and the write.
            if exc.code != 3206:
                raise
            data = {}
        gid = data.get("gid")
        if gid is None:
            fresh = self.find_group(EDITORS_GROUP)
            if fresh is None:
                raise NasError(f"group {EDITORS_GROUP!r} created but not found on re-read")
            return fresh["id"], fresh["gid"]
        return int(gid), int(gid)

    # ------------------------------------------------------------------ users

    def _list_local_users(self) -> list[dict[str, Any]]:
        """Every local account, paged. `type=local` is the only value this DSM
        accepts (`system` is a 3103) and it already includes admin/guest, which
        is what the refusals need to see. Package accounts (sc-*) never appear
        at all -- RESERVED_PREFIXES is what covers those."""
        rows: list[dict[str, Any]] = []
        offset, limit = 0, 200
        while True:
            data = self._call("SYNO.Core.User", "list", 1, type="local", offset=offset,
                              limit=limit,
                              additional=["email", "description", "expired", "uid"])
            page = data.get("users") or []
            rows.extend(page)
            offset += len(page)
            if not page or offset >= int(data.get("total") or 0):
                return rows

    def _row(self, dsm_user: dict[str, Any], groups: list[str] | None = None,
             has_key: bool | None = None) -> dict[str, Any]:
        """One DSM user as a NasBackend row.

        The keys are exactly the ones api.build_admin_users_view reads off the
        TrueNAS rows (username, uid, full_name, smb, sshpubkey, home, locked)
        plus `groups`/`shell`, so the admin Users page renders a DSM fleet with
        no backend-specific branch anywhere above this line.

        `smb: True` is not a lie by omission: DSM has no per-user SMB flag at
        all (unlike TrueNAS), access is decided by the share's permission list,
        and every member of `editors` has it once WP3 has created the tree
        share. Reporting False would show the whole fleet as SMB-less.
        `sshpubkey` carries a marker string, never the key: DSM cannot be asked
        for the key's text, only whether the file exists (_probe_ssh_keys).
        """
        name = str(dsm_user.get("name") or "")
        expired = dsm_user.get("expired")
        return {
            "id": dsm_user.get("uid"),
            "uid": dsm_user.get("uid"),
            "username": name,
            "full_name": dsm_user.get("description") or name,
            "email": dsm_user.get("email") or "",
            "home": f"{HOME_ROOT}/{name}",
            "groups": list(groups or []),
            "sshpubkey": "(installed)" if has_key else None,
            "smb": True,
            "locked": expired is not None and expired != "normal",
            "shell": "/sbin/nologin",
        }

    def _groups_of(self, username: str) -> list[str]:
        """`SYNO.Core.User.Group get` -- one synchronous call that returns the
        user's group NAMES, which is the cleanest membership question DSM
        answers (the alternative, Group.Member list, is per-group and paged)."""
        try:
            data = self._call("SYNO.Core.User.Group", "get", 1, name=username)
        except DsmApiError as exc:
            if exc.code == 3106:
                return []
            raise
        return [str(g) for g in (data.get("groups") or [])]

    def find_user(self, username: str) -> dict[str, Any] | None:
        """Scan `SYNO.Core.User list` rather than call `SYNO.Core.User get`.

        `get` is the obvious call and it is NOT reliable: on 2026-08-17 the
        same `get name=<u> additional=[...]` returned 3106 ("no such user") for
        an account that exists, twice in a row, and then started working again
        minutes later with no change. A false "no such user" here would make
        create_or_update_editor try to CREATE an existing account -- the exact
        adopt-an-account path the refusals exist to prevent. `list` has never
        misreported in any probe, and TrueNASClient.find_user filters a list
        for the same reason.

        Matched case-insensitively: DSM's own names are mixed case
        (`Studio`), and a refusal that can be dodged by capitalising is not
        a refusal. The row carries DSM's spelling of the name.

        The row's `sshpubkey` is always None here: answering it costs an SSH
        session (DSM has no API for it) and this is the refusal path, called
        on every create. list_editors -- the one caller that renders the
        column -- pays for the probe once for the whole page.
        """
        wanted = username.strip().casefold()
        for row in self._list_local_users():
            if str(row.get("name") or "").casefold() == wanted:
                return self._row(row, groups=self._groups_of(str(row["name"])))
        return None

    def list_editors(self) -> list[dict[str, Any]]:
        """Every account in `editors`, in the row shape above.

        Two API calls, not one per editor: `Group.Member list` says who is in
        the group (name/uid/description only), `User list` carries the rest
        (expired, email). A member that `User list` does not know about still
        gets a row -- a fleet member missing from the page is worse than a row
        with thin detail.
        """
        members: list[dict[str, Any]] = []
        offset, limit = 0, 200
        while True:
            try:
                data = self._call("SYNO.Core.Group.Member", "list", 1, group=EDITORS_GROUP,
                                  offset=offset, limit=limit)
            except DsmApiError as exc:
                if exc.code == 3205:      # no editors group yet == no editors yet
                    return []
                raise
            page = data.get("users") or []
            members.extend(page)
            offset += len(page)
            if not page or offset >= int(data.get("total") or 0):
                break
        if not members:
            return []
        detail = {str(u.get("name")): u for u in self._list_local_users()}
        names = [str(m.get("name") or "") for m in members if m.get("name")]
        keys = self._probe_ssh_keys(names)
        return [
            self._row(detail.get(name) or next(m for m in members if m.get("name") == name),
                      groups=[EDITORS_GROUP], has_key=keys.get(name))
            for name in names
        ]

    def is_editor(self, username: str) -> bool:
        """True when `username` exists and is in `editors`. Raises NasError
        when the NAS cannot be asked -- callers must NOT read that as "not an
        editor" (that is what keeps /api/v1/verify fail-closed but retryable).
        """
        if not is_valid_username(username) or self._reserved_reason(username):
            return False
        user = self.find_user(username)
        if user is None:
            return False
        if not self._uid_is_provisionable(user.get("uid")):
            return False
        return EDITORS_GROUP in (user.get("groups") or [])

    # ------------------------------------------------------------- refusals

    @staticmethod
    def _uid_is_provisionable(uid: Any) -> bool:
        if uid is None:
            return False
        return MIN_EDITOR_UID <= int(uid) < PACKAGE_UID_FLOOR

    @staticmethod
    def _reserved_reason(username: str) -> str | None:
        low = username.strip().casefold()
        if low in RESERVED_USERNAMES:
            return f"{username!r} is a DSM built-in account"
        for prefix in RESERVED_PREFIXES:
            if low.startswith(prefix):
                return f"{username!r} looks like a DSM package account ({prefix}*)"
        return None

    def _refuse_non_editor(self, username: str, action: str) -> dict[str, Any] | None:
        """The shared half of create_or_update_editor's and
        set_known_password's refusals. Returns the existing user row, or None
        if there is no such account.

        These are what stop a free-text username in the admin UI from becoming
        a NAS takeover -- the same three refusals the TrueNAS backend carries,
        with DSM's uid ranges (spike 7: local users start at 1024, so `admin`
        and `guest` are ABOVE TrueNAS's 1000 floor and only the name check
        catches them).
        """
        if not is_valid_username(username):
            raise NasError(
                f"invalid username {username!r}: must start with a letter and contain only "
                "lowercase letters, digits, '.', '_', '-'")
        reserved = self._reserved_reason(username)
        if reserved:
            raise NasError(f"{reserved} -- refusing to {action}. Pick a different username.")
        existing = self.find_user(username)
        if existing is None:
            return None
        uid = existing.get("uid")
        if not self._uid_is_provisionable(uid):
            raise NasError(
                f"{username!r} is a system or package account (uid {uid}) -- refusing to "
                f"{action}. Pick a different username.")
        if EDITORS_GROUP not in (existing.get("groups") or []):
            raise NasError(
                f"{username!r} already exists on the NAS and is not in the {EDITORS_GROUP!r} "
                "group -- refusing to take over an account this dashboard didn't create. "
                "Add it to the group in DSM first, or pick a different username.")
        return existing

    # ---------------------------------------------------------- provisioning

    def create_or_update_editor(self, username: str, ssh_pubkey: str,
                                full_name: str | None = None) -> dict[str, Any]:
        """Create (or update in place) a DSM editor account: the account, its
        `editors` membership, and its `authorized_keys`.

        Returns the same summary dict as the TrueNAS backend -- {"created",
        "username", "home_ok", "warnings"} (+ "uid") -- because api.py and the
        admin template read exactly those.

        Steps, and why in this order: the account first (it is the thing that
        can fail on a policy), then the group (read back, trap 3), then the
        key over SSH (the only irreversible-looking step, and the one that
        needs the home to exist -- DSM creates it with the account).
        """
        existing = self._refuse_non_editor(username, "modify it")
        # Before the account, not after: Group.Member add against a group that
        # does not exist is error 3205, and by then the user would already be
        # created and orphaned.
        self.ensure_editors_group()
        warnings: list[str] = []
        created = False

        if existing is None:
            # DSM has no `random_password` flag: an account must be created
            # WITH one. It is deliberately never returned or logged -- the
            # admin sets a known password as a separate, explicit action
            # (set_known_password), exactly as on TrueNAS.
            try:
                data = self._call(
                    "SYNO.Core.User", "create", 1, post=True,
                    name=username, password=_random_password(),
                    description=full_name or username, email="", expired="normal",
                    cannot_chg_passwd=False, password_never_expire=True,
                    notify_by_email=False, send_password=False,
                )
            except DsmApiError as exc:
                if exc.code == 3107:
                    # Only reachable for an account SYNO.Core.User list does
                    # not show -- a package account. Refuse rather than adopt.
                    raise NasError(
                        f"DSM says {username!r} already exists but does not list it as a local "
                        "account -- it is probably a package account. Pick a different username."
                    ) from exc
                raise
            uid = data.get("uid")
            created = True
        else:
            uid = existing.get("uid")
            if full_name and full_name != existing.get("full_name"):
                self._call("SYNO.Core.User", "set", 1, post=True,
                           name=username, description=full_name)

        # Trap 3: Group.Member add answers success:true even when it ignored
        # the members it was given. The read-back is not paranoia, it is the
        # only evidence the call did anything.
        self._call("SYNO.Core.Group.Member", "add", 1, post=True,
                   group=EDITORS_GROUP, name=[username])
        if EDITORS_GROUP not in self._groups_of(username):
            warnings.append(f"user is not a member of group {EDITORS_GROUP!r}")

        home_ok, key_warnings = self._install_ssh_key(username, ssh_pubkey)
        warnings.extend(key_warnings)
        return {"created": created, "username": username, "uid": uid,
                "home_ok": home_ok, "warnings": warnings}

    def set_known_password(self, username: str, password: str) -> None:
        """Set an EDITOR's password, with create_or_update_editor's refusals.

        The refusals matter more here than anywhere: without them a POST to
        /admin/users/admin/password would set the DSM ADMINISTRATOR's password
        straight through this method. There is deliberately no allowlist
        escape hatch -- non-editor accounts are managed in DSM.
        """
        existing = self._refuse_non_editor(username, "set its password")
        if existing is None:
            raise NasError(f"no such user: {username!r}")
        self._call("SYNO.Core.User", "set", 1, post=True, name=username, password=password)

    def sftp_enabled(self) -> bool:
        """Is DSM's SFTP service on? Lanes A/B are rclone over SFTP, and with
        the service off a key auth SUCCEEDS and the channel is then closed with
        no server-side log at all (spike 2) -- an editor sees "channel closed"
        and nobody can tell it from a denied SYNO.SFTP privilege. Exposed for
        WP8's setup checklist; nothing in WP2 gates on it."""
        data = self._call("SYNO.Core.FileServ.FTP.SFTP", "get", 1)
        return bool(data.get("enable"))

    def _delete_user(self, username: str) -> None:
        """Private, and guarded to `ccsync_`-prefixed names on purpose: this
        exists for the WP2 live-verification script and its cleanup, NOT for
        the dashboard. Removing an editor is a DSM Control Panel action --
        the admin UI has never offered it, and an HTTP route that deletes NAS
        accounts is not something to add as a side effect of a port.
        """
        if not username.startswith("ccsync_"):
            raise NasError(
                f"_delete_user refuses {username!r}: it only deletes ccsync_-prefixed test "
                "accounts. Delete real accounts in DSM's Control Panel.")
        # `name` must be a JSON ARRAY (a bare string is error 3101), and DSM
        # reports 3102 inside data.errors even on a successful delete -- so the
        # only trustworthy check is the re-read below.
        self._call("SYNO.Core.User", "delete", 1, post=True, name=[username])
        if self.find_user(username) is not None:
            raise NasError(f"DSM still lists {username!r} after delete")

    # --------------------------------------------------------------- the SSH half

    def _install_ssh_key(self, username: str, ssh_pubkey: str) -> tuple[bool, list[str]]:
        """Write ~/.ssh/authorized_keys as the editor, over SSH.

        DSM has no API for this and FileStation is not a substitute: a key file
        written through it is owned by the admin, and sshd's StrictModes then
        refuses it while logging NOTHING (spike 2) -- the editor just sees
        "Authentication failed".

        home_ok mirrors the TrueNAS backend's meaning: "the home directory is
        in a state where sshd will accept this key". Here that is read back
        from `stat`, not assumed from an exit code.
        """
        home = f"{HOME_ROOT}/{username}"
        script = _INSTALL_KEY_SCRIPT.format(
            path_export=SSH_PATH_EXPORT,
            home=shlex.quote(home),
            key=shlex.quote(ssh_pubkey.strip()),
            owner=shlex.quote(f"{username}:{PRIMARY_GROUP}"),
            user=shlex.quote(username),
        )
        try:
            rc, out, err = self._run_ssh(script)
        except NasError as exc:
            # A key that could not be installed is a warning, not a failure of
            # the whole create: the account exists and is in `editors`, and an
            # operator can paste the key by hand. Failing here would leave the
            # dashboard's editors table and the NAS disagreeing.
            return False, [f"could not install the SSH key over SSH: {exc}"]

        warnings: list[str] = []
        strict_modes_ok = True
        if "MISSING_HOME" in out:
            return False, [
                f"{home} does not exist -- DSM's User Home service is off, so the account has "
                "nowhere to keep an authorized_keys. Turn it on in Control Panel > User & "
                "Group > Advanced, then re-run this."]
        if rc != 0:
            return False, [f"installing the SSH key failed (exit {rc}): {(err or out).strip()[:200]}"]

        stats = dict(
            (line.split(" ", 1)[0], line.split(" ", 1)[1].strip())
            for line in out.splitlines() if " " in line
        )
        home_mode, home_owner = _split_stat(stats.get("HOME"))
        ssh_mode, ssh_owner = _split_stat(stats.get("SSHDIR"))
        key_mode, key_owner = _split_stat(stats.get("KEYS"))

        # The home is NOT chmod'd -- DSM ships it 711, which already satisfies
        # StrictModes, and a chmod would delete its Synology ACL (spike 1). It
        # is only INSPECTED: group/other write on the home is what makes sshd
        # refuse the key silently.
        if home_mode and (int(home_mode[-2]) & 2 or int(home_mode[-1]) & 2):
            strict_modes_ok = False
            warnings.append(
                f"{home} is mode {home_mode}: sshd's StrictModes will refuse the key and log "
                "nothing. Repair with `synoacltool -enforce-inherit` -- do NOT chmod it, that "
                "deletes the Synology ACL.")
        if (ssh_mode, ssh_owner) != ("700", username):
            strict_modes_ok = False
            warnings.append(f"{home}/.ssh is {ssh_mode or '?'} owned by {ssh_owner or '?'} "
                            "(wanted 700 owned by the editor)")
        if (key_mode, key_owner) != ("600", username):
            strict_modes_ok = False
            warnings.append(f"{home}/.ssh/authorized_keys is {key_mode or '?'} owned by "
                            f"{key_owner or '?'} (wanted 600 owned by the editor)")
        shell = stats.get("SHELL", "")
        if shell and not shell.endswith(("nologin", "false")):
            # Not fatal, but worth saying: DSM's default is /sbin/nologin and
            # an editor with a real shell is a bigger account than the fleet
            # needs (COMMERCIAL_READINESS H4).
            warnings.append(f"{username} has an interactive shell ({shell}); DSM's default is "
                            "/sbin/nologin and SFTP does not need one")
        # home_ok means exactly "sshd will accept this key" -- read back from
        # stat, never inferred from an exit status. An interactive shell is a
        # warning but not a reason to call the home broken.
        return strict_modes_ok, warnings

    def _probe_ssh_keys(self, usernames: list[str]) -> dict[str, bool]:
        """Which of these accounts has a non-empty authorized_keys.

        Best effort by design: DSM cannot be asked over the API, and an admin
        page that 500s because the container has no SSH credentials would be a
        worse trade than a page that cannot say whether a key is installed.
        DASH_NAS_SSH_KEY_PROBE=0 turns it off for a site that would rather not
        have the dashboard open an SSH session on every render.
        """
        if not usernames or not self.probe_ssh_keys:
            return {}
        if self._key_probe_cache is not None:
            return self._key_probe_cache
        script = _KEY_PROBE_SCRIPT.format(
            path_export=SSH_PATH_EXPORT,
            users=" ".join(shlex.quote(u) for u in usernames),
            home_root=shlex.quote(HOME_ROOT),
        )
        found: dict[str, bool] = {}
        try:
            _rc, out, _err = self._run_ssh(script)
            for line in out.splitlines():
                if line.startswith("HASKEY "):
                    found[line.split(" ", 1)[1].strip()] = True
        except NasError as exc:
            log.debug("ssh key probe unavailable (%s); reporting keys as unknown", exc)
        self._key_probe_cache = found
        return found

    def _run_ssh(self, script: str) -> tuple[int, str, str]:
        """Run `script` on the NAS as root, via sudo, over SSH.

        The password goes on STDIN and never into argv (`sudo -S -p ''`) --
        the same argv hygiene server/common.py uses, and for the same reason:
        argv is world-readable in /proc on the NAS while the command runs.
        """
        command = f"sudo -S -p '' /bin/sh -c {shlex.quote(script)}"
        runner = self.ssh_runner or self._paramiko_run
        return runner(command, self.pw + "\n")

    def _paramiko_run(self, command: str, stdin_text: str) -> tuple[int, str, str]:
        client = self._ssh_client()
        stdin, stdout, stderr = client.exec_command(command, timeout=self.timeout)
        if stdin_text:
            stdin.write(stdin_text)
            stdin.flush()
        try:
            stdin.channel.shutdown_write()
        except Exception:
            pass
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        return stdout.channel.recv_exit_status(), out, err

    def _ssh_client(self):
        """One paramiko session per client instance, opened on first use.

        paramiko is imported HERE, not at module scope: it is an optional
        extra (`pip install ccsync-dashboard[synology]`), the dashboard's core
        dependency set does not carry it, and a TrueNAS site must not need it
        installed to import this package.
        """
        if self._ssh is not None:
            return self._ssh
        try:
            import paramiko
        except ImportError as exc:
            raise NasError(
                "the Synology backend needs paramiko for the parts DSM has no API for "
                "(~/.ssh/authorized_keys). Install it in the dashboard's venv "
                "(`pip install 'ccsync-dashboard[synology]'`, or add paramiko to "
                "dashboard/deploy/requirements.txt for the container)."
            ) from exc

        client = paramiko.SSHClient()
        pinned = (os.environ.get("DASH_NAS_SSH_HOSTKEY", "") or "").strip()
        if pinned:
            try:
                key = _parse_host_key(pinned)
            except Exception as exc:
                raise NasError(f"DASH_NAS_SSH_HOSTKEY is not a usable SSH public key: {exc}") from exc
            client.get_host_keys().add(_hostkey_name(self.host, self.ssh_port),
                                       key.get_name(), key)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            # TOFU, and SAID SO. An unlogged AutoAddPolicy is a
            # man-in-the-middle waiting to happen on a channel that carries the
            # NAS admin password (COMMERCIAL_READINESS.md H2); the log line is
            # what makes it an operator's decision rather than ours.
            log.warning(
                "SSH host key for %s:%s is NOT pinned -- accepting whatever the NAS presents "
                "(trust on first use). Set DASH_NAS_SSH_HOSTKEY to the base64 host key from "
                "`ssh-keyscan -t ed25519 %s` to pin it.",
                self.host, self.ssh_port, self.host)
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.host, port=self.ssh_port, username=self.user, password=self.pw,
                timeout=self.timeout, allow_agent=False, look_for_keys=False,
            )
        except Exception as exc:
            raise NasError(f"SSH to {self.host}:{self.ssh_port} as {self.user!r} failed: {exc}") from exc
        self._ssh = client
        return client


def _random_password() -> str:
    """A password nobody knows, for an account that will get a real one from
    set_known_password (or none at all -- lanes A/B are key-only). The suffix
    guarantees DSM's default policy (mixed case + digit) is satisfied whatever
    token_urlsafe happens to produce, which is otherwise a 3117 on a box whose
    admin turned the policy on."""
    return secrets.token_urlsafe(24) + "aA1"


def _split_stat(value: str | None) -> tuple[str | None, str | None]:
    """'700 jsmith' -> ('700', 'jsmith'); anything else -> (None, None)."""
    if not value:
        return None, None
    parts = value.split()
    return (parts[0], parts[1]) if len(parts) >= 2 else (parts[0], None)


def _hostkey_name(host: str, port: int) -> str:
    """known_hosts spells a non-default port as [host]:port."""
    return host if int(port) == 22 else f"[{host}]:{port}"


def _parse_host_key(raw: str):
    """Accept either a bare base64 blob or a full `ssh-ed25519 AAAA... comment`
    line. The key TYPE is read out of the blob itself (SSH wire format starts
    with a length-prefixed type name) rather than trusted from the text, so a
    mislabelled line cannot pin the wrong algorithm."""
    import paramiko

    blob_b64 = raw.split()[1] if len(raw.split()) > 1 and raw.split()[0].startswith(
        ("ssh-", "ecdsa-")) else raw.split()[0]
    blob = base64.b64decode(blob_b64, validate=True)
    name_len = int.from_bytes(blob[:4], "big")
    key_type = blob[4:4 + name_len].decode("ascii")
    return paramiko.PKey.from_type_string(key_type, blob)
