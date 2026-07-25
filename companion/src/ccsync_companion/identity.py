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
      401 -> bad credentials / 429 -> throttled / 503 -> login not configured
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
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
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


def save_identity(path: Path, username: str, token: str, role: Optional[str] = None) -> None:
    """Write {username, token, role, verified_at} to `path`. Writes to a
    sibling temp file then replaces -- not a full fsync-durable atomic
    write, but enough to avoid a reader ever seeing a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "username": username,
        "token": token,
        "role": role,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


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
    response -- tries the JSON body's "error" field first, then falls back
    to a per-status-code default per the dashboard's documented contract."""
    data: Any = {}
    try:
        body = exc.read()
        data = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        data = {}
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    return {
        401: "invalid username or password",
        429: "too many sign-in attempts -- try again shortly",
        503: "sign-in is not available on this server",
    }.get(exc.code, f"sign-in failed (HTTP {exc.code})")


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
        self._identity: Optional[dict[str, Any]] = load_identity(self.path)
        # The `upgrade` advertisement from the most recent sign_in()'s verify
        # response, if any -- app.sign_in() forwards it to the
        # UpgradeManager. Deliberately NOT persisted: the reporter refreshes
        # this every report interval anyway.
        self.last_upgrade_info: Optional[dict[str, Any]] = None

    def valid(self) -> bool:
        return is_valid(self._identity)

    @property
    def username(self) -> Optional[str]:
        if not self.valid() or self._identity is None:
            return None
        username = str(self._identity.get("username", "")).strip()
        return username or None

    @property
    def token(self) -> Optional[str]:
        if not self.valid() or self._identity is None:
            return None
        return self._identity.get("token")

    @property
    def role(self) -> Optional[str]:
        """"base" or "editor" as returned by the dashboard at sign-in, or
        None if not signed in / the dashboard didn't send one (older
        server). See app.py's _apply_identity_role()."""
        if not self.valid() or self._identity is None:
            return None
        role = self._identity.get("role")
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
        try:
            save_identity(self.path, verified_username, token, role=role)
        except OSError as exc:
            log.warning("sign_in: failed to persist identity to %s: %s", self.path, exc)

        self._identity = {
            "username": verified_username,
            "token": token,
            "role": role,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        if not self.valid():
            # The dashboard's response didn't yield a usable (parseable,
            # non-expired) token -- treat this as a failed sign-in rather
            # than silently adopting a broken identity.
            self._identity = None
            return False, "dashboard returned a malformed or already-expired token"
        return True, None

    def sign_out(self) -> None:
        self._identity = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            log.debug("sign_out: failed to remove identity file at %s", self.path)
