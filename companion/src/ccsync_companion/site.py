"""The site manifest — who this deployment belongs to, fetched not compiled in.

Until 2026-08-17 every tenant fact this companion needed was a DEFAULT baked
into the binary: the dashboard's tailnet IP (config.py's `dashboard_url`), the
rclone remote name, the NAS Syncthing device ID and the pool path in the two
bootstrap scripts. Shipping that build to a second customer was a fork, not an
install (docs/COMMERCIAL_READINESS.md item 10, docs/SYNOLOGY_PORT_PLAN.md WP0).
So the identity moved to the server and the defaults went blank.

    GET {dashboard_url}/api/v1/site   ->  200, unauthenticated, NO SECRETS

    {"schema": 1, "org_name": "", "tree_name": "", "canonical_prefix": "P:\\\\",
     "remote_root": "", "smb_unc": "", "sftp_host": "", "sftp_port": 22,
     "rclone_remote": "", "nas_syncthing_id": "", "dashboard_url": "",
     "template_folders": [], "shared_asset_folders": [], "nas_kind": "truenas",
     "sftp_chunk_size": "", "sftp_concurrency": 0, "sftp_shell_type": ""}

Any string may be "" (unset on the server), and a dashboard older than this
answers **404**. Every consumer therefore degrades: manifest -> its own
flag/config value -> a clear message naming what is missing. Nothing here ever
raises, on the never-raise ethos this package uses everywhere (see reporter.py).

The answer is cached at ~/.ccsync/state/site.json so an offline start still has
last-known values -- the grade swap's UNC (drive_swap.py) is read on the tray
thread, where a network call is not acceptable at all. The cache is written by
whoever has just talked to the dashboard: the onboarding wizard and both
bootstrap scripts do it at install time; `refresh_site()` is the one-liner for
any long-running caller that wants to keep it current.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import upgrade as upgrade_mod

log = logging.getLogger("ccsync.site")

# The only schema this module understands. A dashboard announcing a NEWER
# schema is still read for the keys below (they are additive by contract);
# an unparseable or lower schema is refused rather than half-believed.
SCHEMA = 1

SITE_FILENAME = "site.json"
SITE_PATH_SUFFIX = "/api/v1/site"

# 5 s, not the reporter's 15: every caller has a working fallback and none of
# them may sit on a dead tailnet route waiting for a value they can live
# without.
FETCH_TIMEOUT = 5.0

STRING_KEYS = (
    "org_name", "tree_name", "canonical_prefix", "remote_root", "smb_unc",
    "sftp_host", "rclone_remote", "nas_syncthing_id", "dashboard_url",
    "nas_kind",
    # TRANSPORT TUNING THE SERVER OWNS (2026-08-17, Synology spike 6). rclone's
    # sftp_chunk_size is not a preference, it is a property of the NAS's sshd:
    # DSM 7.2 ships OpenSSH 8.2p1, which lacks the limits@openssh.com
    # extension, and 255Ki -- measured-good on TrueNAS, and this fleet's
    # default -- TRUNCATES every download at 539,000,832 bytes there. 64Ki is
    # the ceiling on that box. No client can know which NAS it is talking to,
    # so the site says. "" = the server didn't say; keep the built-in default.
    "sftp_chunk_size",
    # rclone's `shell_type` for the generated rclone.conf stanza. TrueNAS
    # editors get "unix" (rclone runs `md5sum` over SSH to verify a
    # transfer); a DSM editor's shell is /sbin/nologin, so the same setting
    # makes every hash check fail there and "none" is required (Synology
    # spike 6, 2026-08-17). Read by both bootstrap scripts when they write
    # the stanza; "" = keep their built-in "unix".
    "sftp_shell_type",
)
LIST_KEYS = ("template_folders", "shared_asset_folders")
# 0 for sftp_concurrency means "the server didn't say" -- unlike config.toml,
# where an explicit 0 means "disable the flag entirely".
INT_KEYS = {"sftp_port": 22, "sftp_concurrency": 0}

HttpOpenFn = Callable[[str, float], Any]


def site_url(dashboard_url: str) -> str:
    """The manifest URL for a dashboard base URL, or "" when there is no
    dashboard configured (a blank dashboard_url is now a legitimate, if
    useless, state -- it used to be impossible because the default was a
    literal IP)."""
    base = str(dashboard_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base + SITE_PATH_SUFFIX


def normalise(data: Any) -> Optional[dict[str, Any]]:
    """Coerce a parsed /api/v1/site body into the shape above, or None.

    Every value is type-checked here rather than at each of the half-dozen
    call sites: a server that answers `{"sftp_port": "22"}` or
    `{"template_folders": "Footage"}` must not make an installer crash three
    steps later with a message about something else."""
    if not isinstance(data, dict):
        return None
    try:
        schema = int(data.get("schema", 0))
    except (TypeError, ValueError):
        return None
    if schema < SCHEMA:
        return None

    out: dict[str, Any] = {"schema": schema}
    for key in STRING_KEYS:
        value = data.get(key, "")
        out[key] = value.strip() if isinstance(value, str) else ""
    for key in LIST_KEYS:
        value = data.get(key, [])
        out[key] = [str(v) for v in value if isinstance(v, (str, int))] if isinstance(value, list) else []
    for key, fallback in INT_KEYS.items():
        try:
            out[key] = int(data.get(key, fallback))
        except (TypeError, ValueError):
            out[key] = fallback
    return out


def default_http_open(url: str, timeout: float) -> Any:
    """The same no-redirect discipline the upgrade channel uses
    (upgrade.build_no_redirect_opener): urllib follows 3xx automatically, and
    "the dashboard tells you where your NAS is" is exactly the kind of answer
    that must not be redirectable to somebody else's host."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    return upgrade_mod.build_no_redirect_opener().open(req, timeout=timeout)


def fetch_site(
    dashboard_url: str,
    timeout: float = FETCH_TIMEOUT,
    http_open: Optional[HttpOpenFn] = None,
) -> Optional[dict[str, Any]]:
    """GET {dashboard_url}/api/v1/site. None on ANY failure -- 404 from a
    dashboard that predates the manifest, a timeout, a redirect, a body that
    isn't the shape above. Logged at debug: an absent manifest is a normal
    state during the rollout, not an error anybody can act on."""
    url = site_url(dashboard_url)
    if not url:
        return None
    opener = http_open or default_http_open
    try:
        resp = opener(url, timeout)
    except urllib.error.HTTPError as exc:
        log.debug("site manifest unavailable (HTTP %s) at %s", getattr(exc, "code", "?"), url)
        return None
    except Exception as exc:
        log.debug("site manifest unreachable at %s: %s", url, type(exc).__name__)
        return None
    try:
        with resp:
            code = upgrade_mod.redirect_status(resp)
            if code is not None:
                log.debug("site manifest answered HTTP %s (redirect) -- refused", code)
                return None
            raw = resp.read()
    except Exception as exc:
        log.debug("site manifest read failed: %s", type(exc).__name__)
        return None
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        log.debug("site manifest at %s is not JSON", url)
        return None
    site = normalise(data)
    if site is None:
        log.debug("site manifest at %s has an unusable shape/schema", url)
    return site


def site_path(state_dir: Optional[Path] = None) -> Path:
    """~/.ccsync/state/site.json. CONFIG_DIR, not an expanduser("~") of our
    own: the test suite repoints config.CONFIG_DIR at a temp tree and nothing
    here may escape it (tests/conftest.py)."""
    if state_dir is not None:
        return Path(state_dir) / SITE_FILENAME
    return config_mod.CONFIG_DIR / "state" / SITE_FILENAME


def save_site(site: dict[str, Any], path: Optional[Path] = None) -> bool:
    """Write the manifest to the cache. Temp file + replace, the shape
    identity.py's save_identity uses -- not fsync-durable, but no reader ever
    sees half a file. False (never an exception) if it could not be written."""
    target = Path(path) if path is not None else site_path()
    payload = dict(site)
    payload["_fetched_at"] = time.time()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(target.name + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(target)
        return True
    except OSError as exc:
        log.debug("could not cache the site manifest at %s: %s", target, exc)
        return False


def cached_site(path: Optional[Path] = None,
                max_age_seconds: Optional[float] = None) -> Optional[dict[str, Any]]:
    """The last manifest this machine saw, or None.

    `max_age_seconds` is checked against the file's mtime (NOT the embedded
    `_fetched_at`, which a file copied between machines carries along with it).
    Callers that would rather have a stale answer than no answer -- the grade
    swap, every offline start -- pass None and get whatever is there."""
    target = Path(path) if path is not None else site_path()
    try:
        stat = target.stat()
        text = target.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    if max_age_seconds is not None and (time.time() - stat.st_mtime) > max_age_seconds:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return normalise(data)


def refresh_site(
    dashboard_url: str,
    path: Optional[Path] = None,
    timeout: float = FETCH_TIMEOUT,
    http_open: Optional[HttpOpenFn] = None,
) -> Optional[dict[str, Any]]:
    """Fetch and cache, falling back to the cache. The network answer wins
    when there is one; otherwise the last-known values are returned unchanged
    (an editor's tailnet is down far more often than their site is
    re-provisioned)."""
    site = fetch_site(dashboard_url, timeout=timeout, http_open=http_open)
    if site is not None:
        save_site(site, path)
        return site
    return cached_site(path)
