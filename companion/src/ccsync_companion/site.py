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
    "org_name",
    # BRAND (2026-08-17, docs/COMMERCIAL_READINESS.md item 10). Additive to
    # schema 1: a dashboard that predates them sends neither, and every reader
    # below falls back rather than showing a name. `org_short` is the same
    # organisation where only a few characters fit; `product_name` is the
    # VENDOR's product, which is why it is the last fallback and not blank.
    "org_short", "product_name",
    # The fleet's own tray/window mark, as a bare asset name the build already
    # ships ("cc_mark_white.png") or an absolute path to a white-on-transparent
    # PNG deployed to the editors. Added 2026-08-18: without it, item 10's
    # de-branding could only be undone by setting $CCSYNC_BRAND_LOGO on every
    # machine, so an existing fleet silently lost its logo on upgrade and
    # needed a reinstall to get it back. "" = wear the product's own mark.
    "brand_logo",
    "tree_name", "canonical_prefix", "remote_root", "smb_unc",
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
    # WHERE THIS FLEET'S VENDOR ARTEFACTS LIVE (2026-08-18,
    # docs/MUSIC_INGEST_PLAN.md step 3): the dashboard's release-feed URL minus
    # its `channel.json`, and the only thing that tells this machine where to
    # fetch the CLAP audio model from. No vendor host is written down anywhere
    # in this repo -- the same rule that keeps a CUSTOMER's name out of it --
    # so a blank here (an older dashboard, or a fleet with no feed) means the
    # model cannot be downloaded, which music_clap_sidecar says in words rather
    # than guessing a host.
    "release_feed_base",
)
LIST_KEYS = ("template_folders", "shared_asset_folders")

# OPTIONAL FEATURES the site has turned on, under the manifest's `features`
# object (2026-08-17, docs/COMMERCIAL_READINESS.md items 2 + 3). Additive to
# schema 1: a dashboard that predates them sends no `features` at all, and
# **that reads as every feature off**, which is the whole point of the
# switch -- the vendor build does not download YouTube material until a
# customer says it may. Never the other way round: a client that cannot tell
# must not assume yes.
#
# THIS TUPLE IS THE WHITELIST. normalise() rebuilds `features` from it, so a
# flag the dashboard publishes but this tuple does not name is stripped
# before feature_enabled() ever sees it -- and feature_enabled fails closed,
# so the flag is silently dead. That is exactly how `auto_update` shipped
# inert in 0.9.3 (ultrareview 2026-08-19, companion 0.9.41): the dashboard
# sent it, the tests monkeypatched feature_enabled, and nobody ran a real
# manifest through normalise(). Every new flag goes here AND in
# tests/test_site.py's round-trip test.
FEATURE_KEYS = ("youtube_download", "youtube_unblock", "auto_update")
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
    # `is True`, not bool(): the only thing that turns a feature on is the
    # server sending a real JSON `true`. A string, a 1, a non-empty dict --
    # anything a hand-edited cache or a half-migrated dashboard could put here
    # -- is not an assertion that this customer may download YouTube material.
    features = data.get("features")
    features = features if isinstance(features, dict) else {}
    out["features"] = {key: features.get(key) is True for key in FEATURE_KEYS}
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


def feature_enabled(name: str, site: Optional[dict[str, Any]] = None) -> bool:
    """Has this site turned optional feature `name` on? FAIL CLOSED.

    Reads the CACHE, never the network: every caller is a tray-thread or
    capability-probe decision that cannot wait on a dead tailnet route, and the
    cache is refreshed by whoever last talked to the dashboard (see the module
    docstring). No cache, an old dashboard, an unreadable file, an unknown
    feature name -- all of them are False, because "we could not ask" and "the
    answer is no" must be the same answer for a feature whose off state is the
    one the vendor ships (docs/legal/YOUTUBE_FEATURE_NOTICE.md).

    Pass `site` when you already have a manifest in hand (one read, not two).
    """
    try:
        manifest = site if site is not None else cached_site()
        features = (manifest or {}).get("features")
        return bool(isinstance(features, dict) and features.get(name) is True)
    except Exception:
        log.debug("site feature %r could not be read; treating it as off", name,
                  exc_info=True)
        return False


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


# --------------------------------------------------------------------------
# Brand -- what the tray and the popups call this editor's tree
# --------------------------------------------------------------------------
#
# Until 2026-08-17 eight tray/popup strings said "your Creators Club drive"
# and the window mark was one studio's logo, compiled in
# (docs/COMMERCIAL_READINESS.md item 10). They read the site manifest now,
# with a NEUTRAL fallback: an editor whose dashboard has never been reached,
# or whose site names no org, is told about "your studio drive" rather than
# about somebody else's studio.

# Deliberately lowercase and article-free: every call site embeds it in a
# sentence ("Your ... is disconnected"), and DRIVE_PHRASE handles the capital.
NEUTRAL_DRIVE_OWNER = "studio"
# The vendor's product name, used where an org name would be wrong (the popup
# title bar, the tray tooltip's app name). Must match the dashboard's
# settings.site_product_name default.
DEFAULT_PRODUCT_NAME = "CC Sync"

# The manifest is read from disk for these, and the tray asks on every status
# repaint, so the parse is memoised against the cache file's identity+mtime --
# a stat per call, not a JSON parse per call, and a re-provisioned site is
# still picked up. Keyed on the path too, because the test suite repoints
# config.CONFIG_DIR per test (tests/conftest.py).
_BRAND_CACHE: dict = {}


def _brand_site(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    target = Path(path) if path is not None else site_path()
    try:
        key = (str(target), target.stat().st_mtime_ns)
    except OSError:
        return None
    hit = _BRAND_CACHE.get("entry")
    if hit is not None and hit[0] == key:
        return hit[1]
    site = cached_site(target)
    _BRAND_CACHE["entry"] = (key, site)
    return site


def org_name(site: Optional[dict[str, Any]] = None,
             path: Optional[Path] = None) -> str:
    """This deployment's organisation name, or "" when nothing has said.

    "" is a legitimate answer and every caller must handle it -- a blank is
    what an un-provisioned machine and a site that declines to be named both
    look like, and neither may be papered over with a default org."""
    site = site if site is not None else _brand_site(path)
    if not isinstance(site, dict):
        return ""
    return str(site.get("org_name") or "").strip()


def org_short(site: Optional[dict[str, Any]] = None,
              path: Optional[Path] = None) -> str:
    """The organisation name for places only a few characters fit. Falls back
    to the full name, then to ""."""
    site = site if site is not None else _brand_site(path)
    if not isinstance(site, dict):
        return ""
    return (str(site.get("org_short") or "").strip()
            or str(site.get("org_name") or "").strip())


def product_name(site: Optional[dict[str, Any]] = None,
                 path: Optional[Path] = None) -> str:
    """The product's own name. Never blank: unlike an org name, there is
    always a product, and a nameless window title helps nobody."""
    site = site if site is not None else _brand_site(path)
    value = ""
    if isinstance(site, dict):
        value = str(site.get("product_name") or "").strip()
    return value or DEFAULT_PRODUCT_NAME


def brand_logo(site: Optional[dict[str, Any]] = None,
               path: Optional[Path] = None) -> str:
    """This fleet's mark as the manifest names it, or "" for the product's
    own. Resolving it to a file is theme.brand_logo_site()'s job -- this
    module must not care where a build keeps its assets."""
    site = site if site is not None else _brand_site(path)
    if not isinstance(site, dict):
        return ""
    return str(site.get("brand_logo") or "").strip()


def notify_title(suffix: str = "") -> str:
    """The title of every balloon, toast and modal this companion shows
    (UX-4, sweep 2026-09-04).

    Fifty-one of them were titled either "ccsync-companion:" (a package name)
    or "CCSYNC.EXE:" (a filename), in TWO vocabularies, on a product that
    went to real trouble to brand the drive and the dashboard header. The
    org's short name when the manifest gives one, the product's name
    otherwise - never a build artefact's filename.

    Deliberately not memoised beyond _brand_site's stat cache: a title is
    rendered once per notification, and a re-provisioned site must show its
    own name on the next one."""
    brand = org_short() or product_name()
    return f"{brand}: {suffix}" if suffix else brand


def server_phrase(site: Optional[dict[str, Any]] = None,
                  path: Optional[Path] = None) -> str:
    """"the Creators Club server" / "the server" - what the editor's copy
    calls the machine their footage lives on (SYNC-114, APP-10, sweep
    2026-09-04).

    Two tray dialogs said "your TrueNAS username and password". That is a
    storage vendor's name in an editor's sentence: false on the Synology
    target (docs/TENANCY.md, the 2026-08-17 port), and the same class of leak
    as a customer's name in code. Named after the org when the manifest names
    one, and NEUTRAL otherwise - never after whatever hardware the vendor
    happened to sell this site."""
    owner = org_short(site, path)
    return f"the {owner} server" if owner else "the server"


def drive_phrase(capitalised: bool = False,
                 site: Optional[dict[str, Any]] = None,
                 path: Optional[Path] = None) -> str:
    """"your Creators Club drive" / "your studio drive" -- the sync tree as the
    editor thinks of it, for the eight tray and popup sentences that name it.

    A phrase rather than a format string because the sentences it lands in
    start with it as often as not, and one capitalisation flag is cheaper than
    eight call sites each doing their own .capitalize() on a name that may
    itself be capitalised ("your CC drive" must not become "Your Cc drive").
    """
    owner = org_name(site, path) or NEUTRAL_DRIVE_OWNER
    return f"{'Your' if capitalised else 'your'} {owner} drive"
