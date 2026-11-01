"""Put a password on the sync engine's admin page, from the dashboard
(CR-363, GL-08, 2026-10-07; bug-server-3, PRAC-18).

THE EXPOSURE. Syncthing's GUI is an administrative surface over EVERY folder
in the fleet: from it a visitor can share any project folder with their own
device, re-point a folder or turn on delete propagation. The appliance binds it
to 0.0.0.0:8384 inside the tailnet node's network namespace (the dashboard
reaches it at `tailscale:8384` over the compose network, so it cannot be
loopback-only) and userspace networking forwards tailnet TCP to local
listeners: any editor laptop on the tailnet could open it. The TrueNAS install
published it on every interface of the NAS. Neither set a GUI user.

WHY HERE. Binding to loopback does not close it on the appliance, and the
dashboard is already the one thing that holds the engine's API key. The API key
(`X-API-Key`) is unaffected by a GUI user and password, which is the whole
reason this is safe on a live fleet: the dashboard, every server script and
`check_health.py` keep working. `server/secure_syncthing_gui.py` has always
done this by hand; this module does the same thing at boot so nobody has to.

BEHAVIOUR. `ensure()` reads `/rest/config/gui`; when there is no GUI user or
password, or `insecureAdminAccess` is on, it writes a user and a random
password back (the password is stored 0600 at
`<data>/secrets/syncthing_gui_password` BEFORE it is sent, so a crash between
the two cannot lose it). A GUI that already has a user and a password is left
exactly as it is: a studio that ran the script by hand keeps its own.

OFF SWITCH. `DASH_SYNCTHING_GUI_SECURE=0` for a site that must keep the old
behaviour; the studio's own deployment can say so in its environment while a
new site gets the secure default.

NEVER FATAL. Every failure is a returned status, never an exception: this runs
on the collector's thread and "the dashboard is what tells everyone whether
their footage is syncing" outranks it. A config that does not look like a real
Syncthing GUI config (no `address`/`enabled` key) is "could not tell", never
"unprotected".
"""
from __future__ import annotations

import logging
import secrets
import string
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("ccsync.dashboard.syncthing_gui_guard")

GUI_USER = "ccsync-admin"
PASSWORD_FILE = "syncthing_gui_password"
_ALPHABET = string.ascii_letters + string.digits
_PASSWORD_LEN = 28

# Retry cadence. A guard that failed (the engine is still starting) tries again
# soon; one that succeeded is re-verified rarely, because a Syncthing config
# reset is the only thing that undoes it.
RETRY_SECONDS = 120.0
VERIFY_SECONDS = 3600.0

_lock = threading.Lock()
_next_due = 0.0
_last: dict[str, Any] = {}


def password_path(settings: Any) -> Path:
    return Path(settings.secrets_path(PASSWORD_FILE))


def read_password(settings: Any) -> str:
    try:
        return password_path(settings).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _looks_real(cfg: Any) -> bool:
    return isinstance(cfg, dict) and ("address" in cfg or "enabled" in cfg)


def _read(client) -> dict | None:
    try:
        cfg = client._request("GET", "/rest/config/gui")
    except Exception:                                                  # noqa: BLE001
        return None
    return cfg if _looks_real(cfg) else None


def is_protected(client) -> bool | None:
    """True/False for a GUI that answered like one, None for "could not tell"."""
    cfg = _read(client)
    if cfg is None:
        return None
    return bool(str(cfg.get("user") or "").strip()) \
        and bool(str(cfg.get("password") or "").strip()) \
        and not bool(cfg.get("insecureAdminAccess"))


def enabled(settings: Any) -> bool:
    return bool(getattr(settings, "syncthing_gui_secure", True))


def ensure(settings: Any, client) -> dict[str, Any]:
    """Make sure the admin page has a login. Returns {"status", "detail"} with
    status one of "disabled", "unknown", "protected", "secured", "failed".
    Never raises."""
    if not enabled(settings):
        return {"status": "disabled", "detail": "DASH_SYNCTHING_GUI_SECURE=0"}
    cfg = _read(client)
    if cfg is None:
        return {"status": "unknown", "detail": "the sync engine's admin settings could not be read"}
    has_login = bool(str(cfg.get("user") or "").strip()) and bool(str(cfg.get("password") or "").strip())
    if has_login and not cfg.get("insecureAdminAccess"):
        return {"status": "protected", "detail": "the admin page already requires a login"}
    wanted = dict(cfg)
    wanted["insecureAdminAccess"] = False
    if has_login:
        # CR-363 / GL-08 overseer fix (2026-10-07): a user AND password the admin
        # chose, with only insecureAdminAccess left on. Flip that one setting
        # and keep their login; replacing it with a random password stored only
        # in our secrets directory would lock them out of their own GUI.
        password = ""
    else:
        password = read_password(settings)
        if not password:
            password = "".join(secrets.choice(_ALPHABET) for _ in range(_PASSWORD_LEN))
            from .secrets_boot import write_secret_file

            try:
                # BEFORE the PUT: a password the engine holds and nobody does is a
                # locked door with no key.
                write_secret_file(password_path(settings), password + "\n")
            except OSError as exc:
                return {"status": "failed", "detail": f"could not store the admin page password ({exc})"}
        wanted["user"] = str(cfg.get("user") or "").strip() or GUI_USER
        wanted["password"] = password
    try:
        client._request("PUT", "/rest/config/gui", json_body=wanted)
    except Exception as exc:                                           # noqa: BLE001
        return {"status": "failed", "detail": f"the sync engine refused the change: {exc}"}
    if has_login:
        log.warning("sync engine admin page: insecureAdminAccess turned off; the existing "
                    "login (user %s) was kept", wanted["user"])
    else:
        log.warning("sync engine admin page: a login (user %s) was set; the password is in "
                    "%s", wanted["user"], password_path(settings))
    return {"status": "secured", "detail": f"a login was set for user {wanted['user']}"}


def tick(settings: Any, client, now_monotonic: float | None = None) -> str:
    """The collector's call. Returns the status word, or "skipped" when it is
    not time yet. Rate limited and never raises."""
    global _next_due
    try:
        if not enabled(settings) or not getattr(settings, "syncthing_url", ""):
            return "disabled"
        mono = time.monotonic() if now_monotonic is None else now_monotonic
        with _lock:
            if mono < _next_due:
                return "skipped"
            _next_due = mono + RETRY_SECONDS
        result = ensure(settings, client)
        _last.clear()
        _last.update(result)
        if result["status"] in ("protected", "secured"):
            _next_due = mono + VERIFY_SECONDS
        return result["status"]
    except Exception:                                                  # noqa: BLE001
        log.exception("sync engine admin page guard failed; continuing")
        return "failed"


def last_result() -> dict[str, Any]:
    return dict(_last)


def reset_for_tests() -> None:
    global _next_due
    _next_due = 0.0
    _last.clear()
