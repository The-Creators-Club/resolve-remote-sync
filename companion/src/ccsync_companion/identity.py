"""Editor identity — authenticates WHOSE machine this is via the dashboard's
open login endpoint, rather than trusting the `editor_name` config key.

The editor signs in (tray "Sign in...") with their TrueNAS username and
password; this module POSTs those credentials to
`{dashboard_url}/api/v1/verify` (see the dashboard's login contract below),
and on success stores a signed identity token at ~/.ccsync/identity.json.
That verified username -- not raw config -- becomes this companion's
identity for reporting/selection once `require_login` is on (config.py).

Dashboard contract (already built server-side; this module only calls it):
    POST {dashboard_url}/api/v1/verify  body {"username", "password"}, no
    auth headers (it's the open bootstrap-trust endpoint).
      200 -> {"ok": true, "username": "<lowercased>", "token": "<opaque>",
              "role": "base" | "editor"}
      401 -> bad credentials / 403 -> account exists but is not in the NAS
      `editors` group / 429 -> throttled / 503 -> login not configured, or
      TrueNAS unreachable (retryable)
    EVERY non-2xx body is FastAPI's {"detail": "<sentence>"} -- NOT
    {"error": ...}. The sentence is written to be shown to the editor
    verbatim; _http_error_message reads it, and falls back to a per-status
    default only when the body is missing or unreadable. onboarding/steps.py
    reuses that helper, so the install gate says the same thing the tray does.
    The token is "v2.identity.<user_b64url>.<expires_epoch>.<hexsig>" --
    OPAQUE to this module except for reading the username (base64url field 2,
    padding-less) and the expiry (field 3) back out of it (parse_token). The
    purpose claim ("identity") and the signature can only be verified
    server-side (no secret here) -- the dashboard does that when a report
    comes in with the token in the X-CCSync-Identity header, and rejects a
    token that isn't signed with purpose="identity" (e.g. a plain session
    cookie) -- see the dashboard's auth.py. v1 tokens (pre-2026-07-25, plain
    "v1.<username>.<expires_epoch>.<hexsig>") are no longer issued; parse_token
    treats one as malformed like any other unparseable token.

    `role` is trusted the same way `username` already is: read straight off
    the response with no local signature to check (the dashboard is the
    only party that can forge or verify either). It's not security-critical
    -- worst case a wrong role just picks the wrong sync profile locally,
    same blast radius as a hand-edited config.toml `mode` typo. See
    app.py's _apply_identity_role() for what a role actually changes.
    Older dashboards (pre-role) simply omit the field; role then reads as
    None and app.py falls back to the static config `mode`/`sync_enabled`.

Never-raise ethos: nothing in this module raises out to callers on network
or filesystem failure -- see reporter.py's docstring for the same pattern.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import secretfile
from . import upgrade as upgrade_mod
from .reporter import HttpPostFn, default_http_post

log = logging.getLogger("ccsync.identity")

IDENTITY_FILENAME = "identity.json"


def identity_path(cfg: Optional[dict[str, Any]] = None) -> Path:
    """~/.ccsync/identity.json -- the same ~/.ccsync directory config.py's
    CONFIG_PATH lives in (config_mod.CONFIG_DIR). `cfg` is accepted (and
    currently unused) for symmetry with config.py's resolved_* helpers and
    so callers don't need to special-case identity paths per-config."""
    return config_mod.CONFIG_DIR / IDENTITY_FILENAME


def load_identity(path: Path) -> Optional[dict[str, Any]]:
    """Tolerant read: missing file, unreadable file, or malformed JSON all
    return None rather than raising -- the never-raise ethos throughout this
    package (see reporter.py's docstring)."""
    try:
        # utf-8-sig tolerates a UTF-8 BOM -- Windows tools (PowerShell
        # Set-Content, some editors, the installer) prepend one, and a plain
        # utf-8 read would leave "﻿{" that json can't parse.
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_identity(path: Path, username: str, token: str, role: Optional[str] = None,
                  report_token: Optional[str] = None,
                  editor_report_token: Optional[str] = None) -> None:
    """Write {username, token, role, report_token, verified_at} to `path`.
    Writes to a sibling temp file then replaces -- not a full fsync-durable
    atomic write, but enough to avoid a reader ever seeing a half-written file.

    `report_token` is the SHARED fleet report token /api/v1/verify hands back
    (api.py's `report_token` key). It is not an identity, but this file is the
    only thing the companion rewrites at runtime, and a stale
    config.toml `dashboard_token` otherwise 401s every report forever with a
    successful tray sign-in sitting right next to it -- see IdentityManager.

    `editor_report_token` is the PER-EDITOR one ("cce1.<id>.<secret>", minted
    by an admin on the dashboard's Users page, 2026-08-17). It outranks the
    shared token everywhere and must SURVIVE a sign-in: /api/v1/verify only
    ever answers with the shared token, so writing that alone here would
    silently demote a machine that had been migrated (see IdentityManager).

    The file is written owner-only -- it holds two credentials. See
    secretfile.harden for what that means on Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "username": username,
        "token": token,
        "role": role,
        "report_token": report_token,
        "editor_report_token": editor_report_token,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Tightened BEFORE the rename, so the file is never readable by anyone
    # else even for the instant between the two calls (the pattern
    # root_guard.py's volume record already uses).
    secretfile.harden(tmp_path)
    tmp_path.replace(path)


def preferred_report_token(cfg: dict[str, Any],
                           identity: Optional[dict[str, Any]]) -> tuple[str, str]:
    """Which fleet credential this machine should present. -> (token, source).

    Precedence, most specific first (COMMERCIAL_READINESS.md item 15,
    2026-08-17):

      identity.json editor_report_token   per-editor, minted by an admin and
                                          revocable for this editor alone
      config.toml   report_token          the same thing, placed by an
                                          installer/admin at provision time
      identity.json report_token          the SHARED fleet token, captured at
                                          the last tray sign-in
      config.toml   dashboard_token       the shared token as installed

    A per-editor token beats a shared one wherever it is found, because the
    shared one proves only "somebody in this fleet" and the dashboard will
    stop accepting it once DASH_SHARED_REPORT_TOKEN_ENABLED=0.
    """
    identity = identity or {}
    candidates = (
        (str(identity.get("editor_report_token") or "").strip(), "identity.json"),
        (str(cfg.get("report_token", "") or "").strip(), "config.toml report_token"),
        (str(identity.get("report_token") or "").strip(), "identity.json (shared)"),
        (str(cfg.get("dashboard_token", "") or "").strip(), "config.toml dashboard_token"),
    )
    for token, source in candidates:
        if token:
            return token, source
    return "", "none"


def parse_token(token: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """Split the opaque "v2.identity.<user_b64url>.<expires_epoch>.<hexsig>"
    token into (username, expires_epoch). Returns (None, None) for anything
    malformed -- including a v1 token, a session-cookie-shaped token (wrong
    purpose), or an unparseable base64url username -- this module cannot and
    does not verify the signature, only reads the two fields it needs
    (display + expiry)."""
    if not token or not isinstance(token, str):
        return None, None
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != "v2" or parts[1] != "identity":
        return None, None
    user_b64, expires_s = parts[2], parts[3]
    try:
        padded = user_b64 + "=" * (-len(user_b64) % 4)
        username = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").strip()
    except Exception:
        return None, None
    if not username:
        return None, None
    try:
        expires_epoch = int(expires_s)
    except (TypeError, ValueError):
        return None, None
    return username, expires_epoch


def is_valid(identity: Optional[dict[str, Any]], now: Callable[[], float] = time.time) -> bool:
    """True when `identity` has a non-expired, parseable token AND a
    non-empty username. Does NOT verify the token's signature (can't --
    that's the dashboard's job when the report arrives)."""
    if not identity:
        return False
    if not str(identity.get("username", "")).strip():
        return False
    username, expires_epoch = parse_token(identity.get("token"))
    if not username or expires_epoch is None:
        return False
    return expires_epoch > now()


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    """Best-effort human-readable message for a non-2xx /api/v1/verify
    response -- the JSON body's message first, then a per-status-code default.

    THE BODY KEY IS "detail", NOT "error" (KNOWN_BUGS B18). FastAPI's
    HTTPException serialises to {"detail": ...} and every refusal the
    dashboard raises on this route uses it (api.py's login/verify handlers).
    This function read "error" -- a shape the dashboard never sends -- so the
    actionable sentence never reached the editor and they got the generic
    per-status fallback instead. "error" is still accepted second, because
    verify_credentials' OWN failure dicts use that key and onboarding/steps.py
    passes them through the same rendering.
    """
    data: Any = {}
    try:
        body = exc.read()
        data = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        data = {}
    if isinstance(data, dict):
        for key in ("detail", "error"):
            value = data.get(key)
            # A pydantic 422 sends detail as a LIST of error dicts, which is
            # not something to show an editor -- fall through to the map.
            if isinstance(value, str) and value.strip():
                return value.strip()
    return {
        401: "invalid username or password",
        # 403 had no entry at all, so an editor with a working NAS account
        # that simply is not in the `editors` group -- the single most likely
        # first-run failure, and the one with a one-line fix -- was told
        # "sign-in failed (HTTP 403)".
        403: ("this account is not allowed to sync -- ask an admin to add it to the "
              "'editors' group on the NAS"),
        429: "too many sign-in attempts -- try again shortly",
        503: "sign-in is not available on this server right now -- try again shortly",
    }.get(exc.code, f"sign-in failed (HTTP {exc.code})")


# Set once per process by _warn_if_plaintext(): sign-in is a tray action an
# editor may repeat all day, and one warning is a note, twenty are noise.
_PLAINTEXT_WARNED = False
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "[::1]", "localhost"}


def _warn_if_plaintext(dashboard_url: str) -> None:
    """Warn ONCE when sign-in will POST the editor's TrueNAS password over
    plain HTTP to a non-loopback host.

    DELIBERATELY NOT A REFUSAL. The current deployment is http over
    LAN/Tailscale by design, and refusing here would lock every editor out of
    a working system to fix a risk the tailnet already bounds -- but a
    password crossing the wire in clear should not be invisible either
    (AUDIT_3 L-13). The fix when it comes is TLS on the dashboard (a reverse
    proxy in front of the container, or Tailscale HTTPS certs); see the
    dashboard's deploy notes. Never raises."""
    global _PLAINTEXT_WARNED
    if _PLAINTEXT_WARNED:
        return
    try:
        parsed = urllib.parse.urlparse(str(dashboard_url or "").strip())
        host = (parsed.hostname or "").strip().lower()
        if parsed.scheme.lower() != "http" or not host or host in _LOOPBACK_HOSTS:
            return
        _PLAINTEXT_WARNED = True
        log.warning(
            "sign-in posts your TrueNAS username and password to %s over plain HTTP "
            "(no TLS) -- anyone able to read traffic between this machine and the "
            "dashboard can read them. It is sent over the tailnet, not the open "
            "internet; enable TLS on the dashboard to close this properly.",
            dashboard_url,
        )
    except Exception:
        log.debug("plaintext sign-in check failed", exc_info=True)


def verify_credentials(
    dashboard_url: str,
    username: str,
    password: str,
    http_post: HttpPostFn = default_http_post,
    timeout: float = 15,
) -> dict[str, Any]:
    """POST {username, password} to {dashboard_url}/api/v1/verify. Returns
    {"ok": True, "username": ..., "token": ...} on success, or
    {"ok": False, "error": "..."} on any failure -- bad credentials,
    throttling, a misconfigured server, or a network error. Never raises."""
    _warn_if_plaintext(dashboard_url)
    url = f"{str(dashboard_url).rstrip('/')}/api/v1/verify"
    headers = {"Content-Type": "application/json"}
    payload = {
        "username": username,
        "password": password,
        # Upgrade channel: lets the dashboard include an `upgrade` key in
        # the response when this build is out of date. Older dashboards
        # ignore both fields.
        "companion_version": config_mod.VERSION,
        "platform": upgrade_mod.platform_key(),
    }
    try:
        resp = http_post(url, payload, headers, timeout)
    except urllib.error.HTTPError as exc:
        message = _http_error_message(exc)
        log.info("verify_credentials: dashboard rejected sign-in (HTTP %s): %s", exc.code, message)
        return {"ok": False, "error": message}
    except Exception as exc:
        log.warning("verify_credentials: request failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    if not isinstance(resp, dict) or not resp.get("ok"):
        error = resp.get("error") if isinstance(resp, dict) else None
        return {"ok": False, "error": error or "sign-in failed"}

    return {
        "ok": True,
        "username": resp.get("username"),
        "token": resp.get("token"),
        # Absent on older dashboards -- .get() leaves it None, the
        # "no role info" case _apply_identity_role() falls back from.
        "role": resp.get("role"),
        # The shared fleet report token. /api/v1/verify has always returned
        # it (api.py) and onboarding consumes it, but THIS module dropped it
        # -- so a tray sign-in on a machine whose config.toml
        # `dashboard_token` was stale (rotated, or a bad copy-paste at
        # install) succeeded and then 401'd every single report, forever,
        # with nothing on screen connecting the two.
        "report_token": resp.get("report_token"),
        # Conditional upgrade advertisement (absent = up to date / older
        # dashboard) -- handed to UpgradeManager by app.sign_in().
        "upgrade": resp.get("upgrade"),
    }


class IdentityManager:
    """Owns this machine's verified editor identity: loads it (if any) from
    ~/.ccsync/identity.json at construction, and updates both the in-memory
    state and that file on sign_in()/sign_out(). Never raises out of any
    public method."""

    def __init__(self, cfg: dict[str, Any], http_post: HttpPostFn = default_http_post) -> None:
        self.cfg = cfg
        self._http_post = http_post
        self.path = identity_path(cfg)
        # _identity is READ from the reporter thread and the tray refresh
        # loop, and REASSIGNED from tray callback threads (sign_in/sign_out)
        # and the app's expiry watcher. Without this, a sign_out() landing
        # between a getter's valid() guard and its .get() raises
        # AttributeError -- contained today only by the reporter's per-getter
        # try/except (AUDIT_2 §2-low). Every access below goes through it.
        self._lock = threading.RLock()
        self._identity: Optional[dict[str, Any]] = load_identity(self.path)
        # The `upgrade` advertisement from the most recent sign_in()'s verify
        # response, if any -- app.sign_in() forwards it to the
        # UpgradeManager. Deliberately NOT persisted: the reporter refreshes
        # this every report interval anyway.
        self.last_upgrade_info: Optional[dict[str, Any]] = None
        # A report token from a previous run's sign-in beats config.toml from
        # the moment this object exists -- IdentityManager is built before the
        # reporter and the selection client (app.py), and both read
        # cfg["dashboard_token"] per request.
        self._adopt_report_token()

    def _adopt_report_token(self) -> None:
        """Publish the credential this machine should present into
        `cfg["dashboard_token"]`, which is the one dict every consumer reads.

        /api/v1/verify returns the shared fleet report token; the companion
        used to throw it away, so a stale config.toml `dashboard_token` --
        rotated on the server, or mistyped at install -- meant every report
        401'd forever even though the tray said "signed in as ...". config.toml
        is written by the installer, not by the running companion, so the
        freshest value lives in identity.json and is republished here.

        Since 2026-08-17 a PER-EDITOR token outranks the shared one wherever it
        is found (preferred_report_token): it is revocable for this editor
        alone, and the shared token stops being accepted the day an admin sets
        DASH_SHARED_REPORT_TOKEN_ENABLED=0. Never raises."""
        try:
            with self._lock:
                identity = dict(self._identity or {})
            token, source = preferred_report_token(self.cfg, identity)
            if not token:
                return
            if str(self.cfg.get("dashboard_token", "") or "").strip() != token:
                log.info("using the report token from %s", source)
            self.cfg["dashboard_token"] = token
        except Exception:
            log.debug("could not adopt the signed-in report token", exc_info=True)

    @property
    def report_token(self) -> Optional[str]:
        """The shared fleet report token captured at sign-in, or None. NOT an
        identity -- see save_identity."""
        with self._lock:
            identity = self._identity or {}
            return str(identity.get("report_token") or "").strip() or None

    @property
    def editor_report_token(self) -> Optional[str]:
        """This machine's PER-EDITOR fleet token, or None.

        Read from identity.json unconditionally -- not through snapshot() --
        because it is a credential, not part of the identity: it stays usable
        while the signed identity token is expired, which is exactly the state
        in which an editor most needs their reports to still say something.
        """
        with self._lock:
            identity = self._identity or {}
            return str(identity.get("editor_report_token") or "").strip() or None

    def valid(self) -> bool:
        with self._lock:
            return is_valid(self._identity)

    def snapshot(self) -> Optional[dict[str, Any]]:
        """A consistent copy of the identity, or None when it isn't valid.
        Callers that need two fields must use this, not two properties."""
        with self._lock:
            if not is_valid(self._identity) or self._identity is None:
                return None
            return dict(self._identity)

    @property
    def username(self) -> Optional[str]:
        identity = self.snapshot()
        if identity is None:
            return None
        username = str(identity.get("username", "")).strip()
        return username or None

    @property
    def token(self) -> Optional[str]:
        identity = self.snapshot()
        if identity is None:
            return None
        return identity.get("token")

    @property
    def role(self) -> Optional[str]:
        """"base" or "editor" as returned by the dashboard at sign-in, or
        None if not signed in / the dashboard didn't send one (older
        server). See app.py's _apply_identity_role()."""
        identity = self.snapshot()
        if identity is None:
            return None
        role = identity.get("role")
        if not role:
            return None
        return str(role).strip().lower() or None

    def sign_in(self, username: str, password: str) -> tuple[bool, Optional[str]]:
        """Verify `username`/`password` against the dashboard; on success,
        persist and adopt the identity. Returns (ok, error) -- error is None
        on success, a human-readable message otherwise."""
        dashboard_url = str(self.cfg.get("dashboard_url", "")).strip()
        if not dashboard_url:
            return False, "dashboard_url is not configured -- cannot sign in"

        result = verify_credentials(dashboard_url, username, password, http_post=self._http_post)
        if not result.get("ok"):
            return False, result.get("error") or "sign-in failed"
        self.last_upgrade_info = result.get("upgrade")

        verified_username = str(result.get("username") or username).strip()
        token = str(result.get("token") or "")
        role = result.get("role")
        # Absent/blank on an older dashboard (or one with no report token
        # configured): keep whatever was already in play rather than blanking
        # a working token.
        report_token = str(result.get("report_token") or "").strip() or self.report_token
        # PRESERVED across sign-in, deliberately: /api/v1/verify only ever
        # answers with the SHARED token, so rewriting the file from its
        # response alone would silently demote a machine an admin had already
        # migrated to a per-editor credential (2026-08-17).
        editor_report_token = self.editor_report_token
        try:
            save_identity(self.path, verified_username, token, role=role,
                          report_token=report_token,
                          editor_report_token=editor_report_token)
        except OSError as exc:
            log.warning("sign_in: failed to persist identity to %s: %s", self.path, exc)

        with self._lock:
            self._identity = {
                "username": verified_username,
                "token": token,
                "role": role,
                "report_token": report_token,
                "editor_report_token": editor_report_token,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        self._adopt_report_token()
        if not self.valid():
            # The dashboard's response didn't yield a usable (parseable,
            # non-expired) token -- treat this as a failed sign-in rather
            # than silently adopting a broken identity.
            with self._lock:
                self._identity = None
            return False, (
                "The server's sign-in reply couldn't be used. If this keeps happening, "
                "check this machine's clock is correct, then tray -> Copy diagnostics for your admin."
            )
        return True, None

    def sign_out(self) -> None:
        with self._lock:
            self._identity = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            log.debug("sign_out: failed to remove identity file at %s", self.path)
