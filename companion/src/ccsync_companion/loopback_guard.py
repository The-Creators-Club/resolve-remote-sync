"""Who is allowed to drive the companion's loopback API on 127.0.0.1:8899.

Until 2026-08-17 the answer was "anyone" (COMMERCIAL_READINESS.md item 5, C1).
The server sent ``Access-Control-Allow-Origin: *`` plus
``Access-Control-Allow-Private-Network: true`` and checked nothing else, so
ANY page an editor happened to have open -- an ad iframe, a forum, a phishing
link -- could POST /insert into the timeline they were grading, spawn Explorer
or ``open`` on their machine, start NAS downloads, and claim fleet ytdl jobs
under their identity. A loopback bind is not an authorisation decision: the
browser is on the same machine, which is exactly the attacker's foothold.

TWO WAYS IN, and only two:

  * **Origin** -- the browser's own, unforgeable statement of which page is
    calling. The allow-list is this deployment's dashboard: `dashboard_url`
    from ~/.ccsync/config.toml, plus the same key from the cached site
    manifest (~/.ccsync/state/site.json), each in both its http and https
    form because Tailscale Serve fronts the same host on both (2026-08-17,
    docs/SERVER-SYNOLOGY.md). The b-roll, music and ytdl pages are all served
    from that origin -- they are the only browser callers that exist. An
    Origin that is not on the list gets 403 and NO CORS headers at all, so a
    hostile page cannot even read the refusal.
  * **Loopback token** -- a per-session random string in
    ~/.ccsync/loopback-token (0600 on posix, owner-only ACL on Windows, both
    via secretfile.harden) sent as the ``X-CCSync-Loopback`` header. For callers that are NOT a browser
    and so have no Origin to offer: the tray app itself, the onboarding
    wizard, an operator with curl. A page in a browser can never read the
    file, which is the whole point of putting the secret on disk rather than
    trusting "no Origin header" as proof of local origin.

WHAT THIS DOES NOT FIX, and is worth saying out loud (trust-model-9,
2026-08-21). The allow-list makes the dashboard's origin trusted, and that
origin serves three SPAs which render text nobody here wrote: clip
transcripts, YouTube titles, music tags, client-folder captions typed by any
editor. A stored XSS in any of them is not "a dashboard bug" -- it is a POST
to 127.0.0.1:8899 on every editor who opens the page, i.e. /insert,
/music/reveal, /ytdl/reveal (which spawn Explorer or `open`), /broll/ingest/run
and on-demand rclone fetches. The answer is a strict Content-Security-Policy
on the dashboard and its mounted SPAs -- server-side, and not something this
module can impose. Note also that origins_for_url below trusts BOTH schemes
for the one host, so a site that has moved to https keeps accepting an http
origin no browser will legitimately present again; tightening that needs a
signal about which scheme editors actually browse, which the manifest does not
carry yet.

Requests with NO Origin still get GETs (curl, a tab opened straight at
/status -- a top-level navigation sends no Origin, and that self-test is what
the web UIs tell editors to run when the button fails). State-changing POSTs
need an allowed Origin OR the token; nothing else.

Two config keys are read straight off the loaded config with `.get()` and
deliberately have no `DEFAULTS` entry -- they are escape hatches, not
settings anyone should be setting routinely:

  loopback_dev_origins = true    also accept http(s)://127.0.0.1|localhost:*
                                 (a dashboard running on the dev's own box)
  loopback_extra_origins = [...] additional exact origins, for a deployment
                                 whose editors browse the dashboard at a name
                                 the configured dashboard_url does not use

Stdlib only -- this ships inside the frozen bundle. Never raises: every
failure here degrades to "refuse", never to an exception on a request thread
(broll_server's MED-5 lesson).
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlsplit

from . import config as config_mod
from . import secretfile

log = logging.getLogger("ccsync.broll")

TOKEN_HEADER = "X-CCSync-Loopback"
TOKEN_FILENAME = "loopback-token"
TOKEN_BYTES = 32

# What a Host header may name. Anything else is a DNS-rebinding attempt: a
# name the attacker controls, resolved to 127.0.0.1, so their page becomes
# same-origin with this server and the Origin check above never fires.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# One safe path segment, and nothing that could ever be joined into a parent.
# `share` is the key of a mounts table AND, on macOS, the tail of
# f"/Volumes/{share}" -- share="../.." reached "/" (C1).
_UNSAFE_SEGMENT_RE = re.compile(r"[\\/:\x00-\x1f\x7f]")
MAX_SHARE_LENGTH = 64

# Paths a file manager must never be pointed AT, only ever INSIDE. On macOS
# `open <x>.app` LAUNCHES the bundle and `open <x>.dmg` mounts it; a reveal
# is supposed to show the editor a folder, not run something. The rule is
# spelled once here and applied wherever an argv is built for a spawner.
BUNDLE_SUFFIXES = (
    ".app", ".bundle", ".framework", ".kext", ".plugin", ".prefpane",
    ".qlgenerator", ".saver", ".service", ".workflow", ".xpc", ".appex",
    ".pkg", ".dmg", ".mpkg",
)

# The one message a refused caller gets. Everything about WHY is a log line:
# a page that is not allowed to talk to this server is not owed a description
# of the allow-list it failed (COMMERCIAL_READINESS.md L-tier, error detail
# leaks).
REFUSED_MESSAGE = ("this request was refused by the CC Sync companion -- see "
                   "its log (Tray > Open log) for the reason")


# -- the loopback token ------------------------------------------------------


def token_path(config_dir: Optional[Path] = None) -> Path:
    """~/.ccsync/loopback-token.

    config_mod.CONFIG_DIR read at CALL time, never captured at import: the
    test suite repoints it at a temp tree (tests/conftest.py) and a token
    written into the developer's real ~/.ccsync would outlive the run.
    """
    base = Path(config_dir) if config_dir is not None else config_mod.CONFIG_DIR
    return base / TOKEN_FILENAME


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def write_token(token: str, path: Optional[Path] = None,
                harden: Optional[Callable[[Any], bool]] = None) -> bool:
    """Publish the session token. False (never an exception) if it could not
    be written -- a machine with an unwritable ~/.ccsync still serves the
    browser, it just has no second way in.

    The permissions are secretfile.harden's, not a second copy: 0600 on posix,
    and on Windows an icacls ACL, because chmod there only toggles the
    read-only bit and says nothing about who may READ the file -- which for
    this file is the entire question.
    """
    target = Path(path) if path is not None else token_path()
    tighten = harden if harden is not None else secretfile.harden
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Tightened BEFORE the rename, so the secret is never on disk under
        # wider permissions even briefly (secretfile.harden's own contract,
        # and root_guard.write_volume_record's ordering).
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        tmp.write_text(token, encoding="utf-8")
        tighten(tmp)
        os.replace(tmp, target)
        return True
    except Exception:
        log.warning("loopback token: could not write %s -- local callers will "
                    "have no way to authenticate", target, exc_info=True)
        return False


def ensure_token(path: Optional[Path] = None,
                 harden: Optional[Callable[[Any], bool]] = None) -> Optional[str]:
    """Mint and publish a token for THIS companion session.

    Regenerated on every start rather than kept: a token that survives a
    restart is a token that survives the process that owned it, and every
    local caller reads the file per call anyway.
    """
    token = new_token()
    if not write_token(token, path, harden=harden):
        return None
    return token


def read_token(path: Optional[Path] = None) -> Optional[str]:
    target = Path(path) if path is not None else token_path()
    try:
        token = target.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def verify_token(presented: Any, path: Optional[Path] = None) -> bool:
    """Constant-time compare against the file. False for anything missing."""
    if not isinstance(presented, str) or not presented:
        return False
    expected = read_token(path)
    if not expected:
        return False
    return hmac.compare_digest(presented.strip(), expected)


# -- the origin allow-list ---------------------------------------------------


def origins_for_url(url: Any) -> set[str]:
    """The origin(s) a configured dashboard base URL authorises.

    Both schemes for the one host:port. Tailscale Serve publishes the
    dashboard on https while `dashboard_url` in a fleet provisioned before
    that still says http (and vice versa on a LAN-only site); refusing the
    other half would break "Send to Resolve" for every editor on the day the
    NAS moved behind TLS, with a 403 and no clue why.
    """
    text = str(url or "").strip()
    if not text:
        return set()
    try:
        parts = urlsplit(text)
    except ValueError:
        return set()
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return set()
    # netloc, not hostname: the PORT is part of an origin. Userinfo is
    # stripped -- it never appears in a browser's Origin header.
    netloc = parts.netloc.rsplit("@", 1)[-1].strip().lower()
    if not netloc:
        return set()
    return {f"http://{netloc}", f"https://{netloc}"}


def allowed_origins(ccsync_cfg: Optional[dict],
                    site: Optional[dict] = None) -> frozenset[str]:
    """Every origin this machine's browser callers may present.

    `site` is the cached site manifest (site.cached_site()); passing it
    explicitly keeps this function pure for tests. It is consulted because a
    de-tenanted build has NO compiled-in dashboard address at all -- the
    manifest is where a provisioned machine's identity now lives
    (docs/SYNOLOGY_PORT_PLAN.md WP0).
    """
    cfg = ccsync_cfg or {}
    out: set[str] = set()
    out |= origins_for_url(cfg.get("dashboard_url"))
    out |= origins_for_url((site or {}).get("dashboard_url"))
    extra = cfg.get("loopback_extra_origins")
    if isinstance(extra, (list, tuple)):
        for item in extra:
            out |= origins_for_url(item)
    return frozenset(out)


def dev_origins_enabled(ccsync_cfg: Optional[dict]) -> bool:
    return bool((ccsync_cfg or {}).get("loopback_dev_origins", False))


def _is_loopback_origin(origin: str) -> bool:
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    host = (parts.hostname or "").strip().lower()
    return parts.scheme in ("http", "https") and host in LOOPBACK_HOSTS


def origin_allowed(origin: Any, allowed: Iterable[str], dev: bool = False) -> bool:
    """Is this Origin header on the list? Exact match, case-folded.

    No prefix or suffix matching, ever: "https://dashboard.example.com" and
    "https://dashboard.example.com.evil.net" differ by a suffix, which is the
    classic way an allow-list written with startswith() lets the whole
    internet in.
    """
    if not isinstance(origin, str):
        return False
    candidate = origin.strip().lower()
    if not candidate or candidate == "null":
        return False
    if candidate in {str(a).strip().lower() for a in (allowed or ())}:
        return True
    return bool(dev) and _is_loopback_origin(candidate)


# -- the Host header ---------------------------------------------------------


def host_allowed(host_header: Any, port: int) -> bool:
    """DNS-rebinding defence: the client must have DIALLED loopback by name.

    A missing Host is allowed. HTTP/1.1 requires one and every browser sends
    one, so its absence means a hand-rolled client -- which is the one caller
    that has to prove itself with the token anyway; refusing it would only
    break curl on an HTTP/1.0 line.
    """
    if host_header is None:
        return True
    text = str(host_header).strip()
    if not text:
        return True
    if text.startswith("["):  # [::1]:8899
        host, _, rest = text[1:].partition("]")
        port_part = rest.lstrip(":")
    else:
        host, _, port_part = text.rpartition(":")
        if not host:  # no colon at all -- rpartition put it all in port_part
            host, port_part = port_part, ""
    if host.strip().lower() not in LOOPBACK_HOSTS:
        return False
    try:
        return int(port_part) == int(port) if port_part else int(port) == 80
    except (TypeError, ValueError):
        return False


# -- request shape -----------------------------------------------------------


def content_type_is_json(content_type: Any) -> bool:
    """Only application/json bodies are accepted on POST.

    Not pedantry: text/plain, multipart/form-data and
    application/x-www-form-urlencoded are the three types a cross-origin
    <form> can send WITHOUT a preflight, so requiring json is what makes the
    browser ask permission before a hostile page's POST ever arrives.
    """
    if not isinstance(content_type, str):
        return False
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


def valid_share(share: Any) -> bool:
    """Exactly one safe path segment.

    A share is a KEY of the mounts table and, on macOS, the tail of
    f"/Volumes/{share}" -- so "..", "../..", "a/b" and a leading dot are all
    refused here rather than defended against three layers down (C1).
    """
    if not isinstance(share, str) or not share:
        return False
    if share != share.strip() or len(share) > MAX_SHARE_LENGTH:
        return False
    if share.startswith("."):  # ".", "..", ".hidden"
        return False
    return not _UNSAFE_SEGMENT_RE.search(share)


def is_bundle_path(path: Any) -> bool:
    """Does this path NAME a macOS bundle (or an installer/disk image)?"""
    name = str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return name.lower().endswith(BUNDLE_SUFFIXES)


def is_within(child: Any, parent: Any,
              realpath: Optional[Callable[[str], str]] = None) -> bool:
    """Does `child` resolve INSIDE `parent`, symlinks followed? Never raises.

    realpath rather than a string compare because the escape this catches is
    a symlink or junction planted inside an otherwise legitimate root; the
    seam exists so a darwin layout can be checked from a Windows host.
    """
    # Before realpath, which turns None into the literal "None" in the CWD --
    # and two of those compare equal, i.e. a missing path would be "contained"
    # in a missing root.
    if not child or not parent:
        return False
    resolve = realpath if realpath is not None else os.path.realpath
    try:
        child_real = os.path.normcase(resolve(str(child)))
        parent_real = os.path.normcase(resolve(str(parent)))
    except Exception:
        return False
    if not parent_real:
        return False
    if child_real == parent_real:
        return True
    sep = os.sep
    prefix = parent_real if parent_real.endswith(sep) else parent_real + sep
    if child_real.startswith(prefix):
        return True
    # A posix-spelled parent checked from a Windows host (the /Volumes probe)
    # normalises to backslashes on one side only.
    alt = parent_real.replace("\\", "/").rstrip("/") + "/"
    return child_real.replace("\\", "/").startswith(alt)
