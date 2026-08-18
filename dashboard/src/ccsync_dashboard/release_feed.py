"""The vendor release feed client (ZERO_TOUCH_PLAN.md WP E, 2026-08-17).

"We publish once, every dashboard pulls." Today a build reaches a customer's
fleet only by someone with the offline release key and an admin cookie
PUTting bytes into THAT dashboard (`api.api_publish_package`). This module is
the second, unattended writer the plan describes: it fetches a small signed
JSON document (`channel.json` -- see `docs/RELEASE_FEED.md` for the exact
schema) from a static file host the vendor controls, verifies it against the
SAME baked `DASH_RELEASE_PUBKEYS` the PUT route already trusts, and offers an
admin "Publish" for anything not already in `companion_packages`. Optionally
(policy `stage`/`current`) it publishes automatically.

THREAT MODEL (see docs/RELEASE_FEED.md for the full writeup): the feed HOST
is untrusted -- GitHub Releases, an S3 bucket, whatever a customer's outbound
network reaches. Nothing here trusts it. Every byte that ends up in
`companion_packages` still passes through `package_store.store_verified_package`,
which re-verifies the Ed25519 signature against `settings.release_pubkeys`
exactly as a human PUT would. A compromised or malicious feed host can, at
worst, serve nothing, serve stale records (caught by watching
`last_channel_generated_at` go static), or serve garbage that fails
verification and is logged and discarded -- it can never make this dashboard
accept a binary the offline release key did not sign.

Fetching is deliberately paranoid in the same shape the companion's own
upgrade client already uses against THIS dashboard (`upgrade.py`): https
only, a short timeout, and a hard byte ceiling BEFORE anything is parsed or
written to disk. An unverified channel is never surfaced to an admin as
"available" -- see `check_now`.

REDIRECTS: these two fetches are the ONE carve-out from `docs/GOTCHAS.md`
§12's "no dashboard call follows a redirect" rule (2026-08-18). That rule
exists because following a 3xx on an AUTHENTICATED call hands the session
cookie / `X-CCSync-Token` / `X-CCSync-Identity` to whatever host the
`Location` names, and it still holds everywhere else in this codebase. It
does not bind here for two reasons that must BOTH stay true: these requests
carry no credential of any kind (no cookie, no Authorization, no token --
nothing in this module may ever add one), and every byte they return is
content-verified before it is believed (the channel against
`settings.release_pubkeys`, the artefact against the sha256 pinned inside
that signed channel and then again by `package_store.store_verified_package`).
A redirect can point us at a different host; it cannot make that host's bytes
verify. The rule had to bend because GitHub Releases -- the chosen feed host
-- answers `https://github.com/OWNER/REPO/releases/download/TAG/FILE` with a
302 to a short-lived signed `release-assets.githubusercontent.com` URL
(measured 2026-08-18), so a redirect-refusing opener failed on the very first
fetch. The follow is bounded at _MAX_REDIRECTS hops and EVERY hop must be
https:// -- a downgrade to http:// is refused, never followed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, Depends, HTTPException, Request as FastAPIRequest
from pydantic import BaseModel

from . import VERSION, db, ed25519, package_store, release_trust
from .api import _require_admin, build_packages_view, get_conn

log = logging.getLogger("ccsync.dashboard.release_feed")

# Domain separation for the channel-level detached signature, distinct from
# release_trust.RECORD_PREFIX (which covers one PACKAGE record, not the
# whole channel document). MUST match tools/publish_feed.py's copy
# byte-for-byte -- two deployment units, same reason release_trust.py
# duplicates release_pubkey.py rather than importing it (see that module's
# docstring): the tool signs offline with only the companion package on its
# path, this runs in the container with only the dashboard package on its
# path, and neither may import the other.
CHANNEL_PREFIX = b"ccsync-channel-v1\n"

_VALID_POLICIES = ("manual", "stage", "current")

# The dashboard's own code bundle (ZERO_TOUCH_PLAN.md WP K, 2026-08-18). It
# travels in the same channel, signed by the same key and verified by the same
# verifier -- but it is APPLIED, never PUBLISHED: nothing of this kind may ever
# reach `companion_packages`, because no editor machine downloads one and a row
# there would offer the dashboard's tarball to a companion as an upgrade.
# Everything in this module that walks records therefore splits on it, and
# `dashboard_update.py` is what consumes the other half.
DASHBOARD_KIND = "dashboard"

# Transport ceilings (docs/RELEASE_FEED.md "threat model"): the channel is a
# few KB of JSON in every real deployment, so 1 MiB is already generous
# headroom, not a working assumption. The artefact ceiling matches
# MAX_PACKAGE_BODY_BYTES (app.py) -- the same ceiling a human PUT is held to.
FEED_FETCH_TIMEOUT = 10.0
FEED_MAX_BYTES = 1024 * 1024
ARTIFACT_MAX_BYTES = 200 * 1024 * 1024
ARTIFACT_FETCH_TIMEOUT = 600.0
# GitHub Releases needs exactly one hop (github.com -> a signed
# release-assets.githubusercontent.com URL); 5 is headroom for a host that
# puts a CDN or a bucket alias in front, not an invitation. Exceeding it is a
# refusal -- see _open_following_https_redirects.
_MAX_REDIRECTS = 5
# How soon after boot the background poller makes its first check, and the
# floor under its cadence -- see FeedPoller._run.
POLLER_FIRST_CHECK_DELAY = 10.0
POLLER_MIN_INTERVAL = 60.0


class FeedError(Exception):
    """Anything that stops a fetch or a verify. Always caught -- a feed
    problem is logged and surfaced as `last_error`, never raised through to a
    request or allowed to kill the poller thread."""


def canonical_channel_bytes(channel: dict[str, Any]) -> bytes:
    """The exact bytes the release key signs for the WHOLE channel document
    (as opposed to release_trust.canonical_record, which signs one package
    record). `channel` must be the parsed document with no `signature` key
    of its own -- the signature is detached (`channel.json.sig`), never
    embedded, so a channel can be re-signed without changing the file every
    consumer diffs against."""
    return CHANNEL_PREFIX + json.dumps(
        channel, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def verify_channel_signature(
    channel: dict[str, Any], signature_b64: str, pubkeys: tuple[str, ...]
) -> tuple[bool, str]:
    """(ok, detail), never raises -- same shape as release_trust.verify_record."""
    keys = tuple(k for k in pubkeys if k)
    if not keys:
        return False, "no release public key is configured (DASH_RELEASE_PUBKEYS)"
    try:
        sig = base64.b64decode(str(signature_b64 or "").strip(), validate=True)
    except Exception:
        return False, "channel signature is not valid base64"
    if len(sig) != 64:
        return False, f"channel signature is {len(sig)} bytes, not 64"
    try:
        message = canonical_channel_bytes(channel)
    except (TypeError, ValueError) as exc:
        return False, f"channel is not signable ({exc})"
    for key in keys:
        try:
            raw = base64.b64decode(key.strip(), validate=True)
        except Exception:
            continue
        if len(raw) != 32:
            continue
        if ed25519.verify(raw, message, sig):
            return True, release_trust.pubkey_id(key)
    return False, "no configured release public key verifies this channel"


class _NoRedirect(HTTPRedirectHandler):
    """urllib must never follow a 3xx BY ITSELF: it would neither count the
    hops nor re-check the scheme. _open_following_https_redirects walks the
    chain by hand instead, one explicitly checked hop at a time."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _opener():
    # A fresh opener per call -- this is polled at most once a day per
    # dashboard and hit on demand from "Check now"; there is no benefit to
    # sharing one across calls and every benefit to not holding state.
    return build_opener(_NoRedirect())


def _redirect_target(url: str, headers) -> str:
    """The absolute https URL a 3xx points at. Raises FeedError on a missing
    Location or on any scheme but https -- a `Location: http://...` is a
    downgrade attempt and is refused outright, never fetched."""
    location = ""
    if headers is not None:
        location = str(headers.get("Location") or headers.get("location") or "").strip()
    if not location:
        raise FeedError(f"{url} answered with a redirect but no Location -- refused")
    # Relative Locations are legal (RFC 7231 §7.1.2) and resolve against the
    # hop we are on, so a relative target on an https base stays https --
    # which the explicit check below still confirms rather than assumes.
    target = urljoin(url, location)
    if not target.lower().startswith("https://"):
        raise FeedError(
            f"refusing a non-https redirect: {url} -> {target!r} (scheme downgrade)")
    return target


def _open_following_https_redirects(url: str, *, timeout: float):
    """GET `url` and return the OPEN response for the caller to stream and
    close, following at most _MAX_REDIRECTS redirects.

    No credential is sent on any hop -- no cookie, no Authorization, no
    `X-CCSync-*` header, on the first request or any redirect target. That,
    plus the fact that every byte the caller gets back is signature- or
    sha256-verified afterwards, is what makes following a redirect safe HERE
    and nowhere else (module docstring, `docs/GOTCHAS.md` §12, 2026-08-18).
    Do not add a header to this request.

    Raises FeedError on a non-https hop, a chain longer than the cap, a 3xx
    with no usable Location, or any transport failure."""
    current = url
    for _hop in range(_MAX_REDIRECTS + 1):
        if not current.lower().startswith("https://"):
            raise FeedError(f"refusing a non-https feed URL: {current!r}")
        req = Request(current, method="GET")
        try:
            resp = _opener().open(req, timeout=timeout)
        except HTTPError as exc:
            # _NoRedirect turns a 3xx into an HTTPError; the headers on it are
            # the redirect's own, so this IS the normal redirect path.
            if 300 <= exc.code < 400:
                current = _redirect_target(current, getattr(exc, "headers", None))
                continue
            raise FeedError(f"{current} answered HTTP {exc.code}") from exc
        except URLError as exc:
            raise FeedError(f"could not reach {current}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise FeedError(f"{current} timed out after {timeout}s") from exc
        status = int(getattr(resp, "status", None) or getattr(resp, "code", 200))
        if 300 <= status < 400:
            # Belt and braces: a handler stack that answered a 3xx as a normal
            # response instead of raising must not be read as a body.
            headers = getattr(resp, "headers", None)
            close = getattr(resp, "close", None)
            if callable(close):
                close()
            current = _redirect_target(current, headers)
            continue
        return resp
    raise FeedError(f"{url} redirected more than {_MAX_REDIRECTS} times -- refused")


def _fetch_bytes(url: str, *, cap: int, timeout: float = FEED_FETCH_TIMEOUT) -> bytes:
    """GET url, https only, at most _MAX_REDIRECTS https redirects followed,
    capped at `cap` bytes. Raises FeedError on anything short of a clean 2xx
    under the cap -- see the module docstring's threat model. The cap is
    applied to the FINAL response's body, so no length of redirect chain can
    smuggle more than `cap` bytes past it."""
    try:
        with _open_following_https_redirects(url, timeout=timeout) as resp:
            data = bytearray()
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > cap:
                    raise FeedError(f"{url} exceeded the {cap}-byte cap -- refused")
            return bytes(data)
    # _open_following_https_redirects has already turned every transport
    # failure it saw into a FeedError; these two cover the read half.
    except URLError as exc:
        raise FeedError(f"could not reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FeedError(f"{url} timed out after {timeout}s") from exc


class FeedHashMismatch(FeedError):
    """The bytes arrived but they are not the bytes the signed record
    describes. A distinct type because it is a distinct answer: the transport
    worked (so retrying changes nothing) and the FEED is what is wrong."""


def fetch_artifact_to(url: str, part: Path, *, expected_sha256: str,
                      max_bytes: int, timeout: float) -> tuple[str, int]:
    """Stream `url` into `part`, capped and hashed, and refuse anything whose
    digest is not `expected_sha256`. Returns (sha256, size).

    `part` is UNLINKED on every failure -- a half-written artefact must never
    survive to be mistaken for a good one. Raises FeedHashMismatch for a
    digest that does not match and FeedError for everything else, because the
    two are different answers to "should I retry".

    Two callers (publish_from_feed for an editor package,
    dashboard_update.apply for the dashboard's own code bundle) and one
    implementation on purpose: this is the function that decides whether
    bytes off an untrusted host are believed, and that must have one answer.
    Same credential-free, https-only, bounded redirect follow as the channel
    fetch (module docstring)."""
    digest = hashlib.sha256()
    size = 0
    try:
        with part.open("wb") as fh, _open_following_https_redirects(
            url, timeout=timeout
        ) as resp:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise FeedError(f"artifact exceeded the {max_bytes}-byte cap -- refused")
                fh.write(chunk)
                digest.update(chunk)
    except (FeedError, HTTPError, URLError, OSError, TimeoutError) as exc:
        part.unlink(missing_ok=True)
        if isinstance(exc, FeedError):
            raise
        raise FeedError(f"could not download {url}: {exc}") from exc
    sha = digest.hexdigest()
    if size == 0 or sha != str(expected_sha256 or "").lower():
        part.unlink(missing_ok=True)
        raise FeedHashMismatch(
            "the downloaded artefact's sha256 does not match the signed record -- refused")
    return sha, size


def fetch_and_verify_channel(
    url: str, pubkeys: tuple[str, ...]
) -> tuple[dict[str, Any] | None, str | None]:
    """(channel, None) on a fully verified channel; (None, reason) otherwise.
    NEVER returns a channel that failed signature verification -- the one
    rule this whole module exists to enforce (see the module docstring)."""
    try:
        raw = _fetch_bytes(url, cap=FEED_MAX_BYTES)
    except FeedError as exc:
        return None, str(exc)
    try:
        channel = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"channel.json is not valid JSON: {exc}"
    if not isinstance(channel, dict) or channel.get("schema") != 1:
        return None, "channel.json is not a schema=1 object"
    try:
        sig_raw = _fetch_bytes(url + ".sig", cap=8192)
    except FeedError as exc:
        return None, str(exc)
    signature = sig_raw.decode("utf-8", errors="replace").strip()
    ok, detail = verify_channel_signature(channel, signature, pubkeys)
    if not ok:
        return None, f"channel signature invalid: {detail}"
    return channel, None


def _record_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (str(record.get("kind", "")), str(record.get("platform", "")), str(record.get("version", "")))


def _valid_records(channel: dict[str, Any], pubkeys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Every package record in `channel` whose OWN signature verifies.
    Belt-and-braces on top of the channel-level signature: a compromised or
    buggy feed host could otherwise splice in an unsigned or mis-signed
    record under an otherwise-valid, correctly-signed channel wrapper."""
    out: list[dict[str, Any]] = []
    packages = channel.get("packages")
    if not isinstance(packages, list):
        return out
    dropped = 0
    for rec in packages:
        if not isinstance(rec, dict):
            dropped += 1
            continue
        ok, _detail = release_trust.verify_record(rec, str(rec.get("signature", "")), pubkeys)
        if ok:
            out.append(rec)
        else:
            dropped += 1
    if dropped:
        log.warning("release feed: %d package record(s) failed verification and were ignored", dropped)
    return out


def package_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The verified records that describe an EDITOR package (companion,
    onboard). Everything the packages table, the publish routes and the
    auto-publish policy touch goes through here, so a `dashboard` record can
    never be published into `companion_packages` by any of the three."""
    return [r for r in records if str(r.get("kind", "")) != DASHBOARD_KIND]


def dashboard_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The verified records that describe THIS dashboard's own code bundle.
    Consumed by dashboard_update.py, never by package_store."""
    return [r for r in records if str(r.get("kind", "")) == DASHBOARD_KIND]


def verified_records(app_state) -> list[dict[str, Any]]:
    """Everything the last check verified, for a caller outside this module
    (dashboard_update.py). Empty until a check has run -- the cache is
    deliberately process-local; see _cache."""
    return list(_cache(app_state).get("valid_records") or [])


# --------------------------------------------------------------- app-state cache
# The verified channel is cheap to refetch but must never be re-verified on
# every GET of the admin page (a check is a network call to a host outside
# our control) -- so the last verified result lives on app.state, populated
# by check_now(), and GET /api/v1/admin/feed just reads it back. Lost on
# restart, which is fine: the next scheduled or manual check repopulates it,
# and feed_state (db.py) keeps the DURABLE half (last_checked_at/last_error).
def _cache(app_state) -> dict[str, Any]:
    if not hasattr(app_state, "feed_cache"):
        app_state.feed_cache = {"channel": None, "valid_records": [], "checked_at": None}
    return app_state.feed_cache


def effective_policy(conn, settings) -> str:
    state = db.get_feed_state(conn)
    override = str(state.get("policy_override") or "").strip().lower()
    if override in _VALID_POLICIES:
        return override
    return settings.release_feed_policy if settings.release_feed_policy in _VALID_POLICIES else "manual"


def set_policy(conn, policy: str) -> str:
    policy = str(policy or "").strip().lower()
    if policy not in _VALID_POLICIES:
        raise ValueError(f"policy must be one of {_VALID_POLICIES}, got {policy!r}")
    db.set_feed_state(conn, policy_override=policy)
    conn.commit()
    return policy


def _safe_filename(name: str) -> str:
    name = str(name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise package_store.PackageStoreError(400, f"feed record has an unsafe filename {name!r} -- refused")
    return name


def check_now(conn, settings, app_state) -> dict[str, Any]:
    """Fetch + verify the channel, refresh the cache and `feed_state`, and
    apply the configured policy to anything newly available. Never raises --
    a feed outage is a logged, cached `last_error`, not a 500."""
    now = db.utcnow_iso()
    if not settings.release_feed_url:
        return {"ok": False, "error": "DASH_RELEASE_FEED_URL is not configured"}
    channel, err = fetch_and_verify_channel(settings.release_feed_url, settings.release_pubkeys)
    if err:
        log.warning("release feed check failed: %s", err)
        db.set_feed_state(conn, last_checked_at=now, last_error=err)
        conn.commit()
        return {"ok": False, "error": err}
    valid_records = _valid_records(channel, settings.release_pubkeys)
    cache = _cache(app_state)
    cache["channel"] = channel
    cache["valid_records"] = valid_records
    cache["checked_at"] = now
    db.set_feed_state(
        conn, last_checked_at=now, last_error="",
        last_channel_generated_at=str(channel.get("generated_at") or ""),
    )
    conn.commit()
    applied = _apply_policy(conn, settings, app_state, valid_records, now)
    return {"ok": True, "error": None, "applied": applied}


def _apply_policy(conn, settings, app_state, valid_records: list[dict[str, Any]], now: str) -> list[str]:
    """manual: do nothing (the admin page's [ PUBLISH ] buttons are the only
    writer). stage/current: auto-publish every verified record this
    dashboard does not already have, current also flipping it live. Returns
    the "kind/platform/version" strings actually published, for the log
    line and the /check response -- an admin watching a fresh install should
    see this happen, not infer it from the packages table changing."""
    policy = effective_policy(conn, settings)
    if policy == "manual":
        return []
    applied: list[str] = []
    # package_records, not valid_records: `stage`/`current` must never
    # auto-apply a DASHBOARD code update. Replacing the code the container is
    # running is a ten-second outage and an admin's decision, not a
    # consequence of a policy about editor packages (ZERO_TOUCH_PLAN.md WP K).
    for record in package_records(valid_records):
        kind, platform, version = _record_key(record)
        if not (kind and platform and version):
            continue
        if db.get_package(conn, platform, version, kind) is not None:
            continue
        try:
            publish_from_feed(
                conn, settings, app_state, kind=kind, platform=platform, version=version,
                make_current=(policy == "current"), published_by="release-feed",
            )
        except package_store.PackageStoreError as exc:
            log.warning("release feed auto-publish of %s/%s %s failed: %s",
                        kind, platform, version, exc.detail)
            continue
        applied.append(f"{kind}/{platform} {version}")
    if applied:
        log.info("release feed (%s policy) auto-published: %s", policy, ", ".join(applied))
    return applied


def publish_from_feed(
    conn, settings, app_state, *, kind: str, platform: str, version: str,
    make_current: bool, published_by: str,
) -> dict[str, Any]:
    """Download the artefact the last verified channel described for
    (kind, platform, version), verify its bytes AND its signed record, and
    hand it to package_store -- the exact same write path a human PUT uses
    (see package_store.store_verified_package's docstring). Raises
    PackageStoreError; never partially publishes."""
    if kind == DASHBOARD_KIND:
        raise package_store.PackageStoreError(
            400, "a dashboard code bundle is applied, not published: use "
                 "Admin > Packages > Dashboard, or POST "
                 "/api/v1/admin/dashboard-update/apply")
    valid_records = package_records(_cache(app_state).get("valid_records") or [])
    record = next(
        (r for r in valid_records if _record_key(r) == (kind, platform, version)), None
    )
    if record is None:
        raise package_store.PackageStoreError(
            404, f"no verified feed record for {kind}/{platform}/{version} -- run Check now first")
    if db.get_package(conn, platform, version, kind) is not None:
        raise package_store.PackageStoreError(
            409, f"{kind} {platform} {version} is already published on this dashboard")

    filename = _safe_filename(str(record.get("filename", "")))
    url = str(record.get("url", ""))
    if not url.lower().startswith("https://"):
        raise package_store.PackageStoreError(400, "feed record's url is not https -- refused")
    sha_expected = str(record.get("sha256", "")).lower()

    dest_dir = settings.packages_path() / platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / f"{filename}.{uuid.uuid4().hex}.part"
    # Same bounded, credential-free, https-only redirect follow as the channel
    # fetch (2026-08-18): GitHub Releases 302s every asset URL to a signed
    # release-assets.githubusercontent.com URL, and the sha256 check inside
    # fetch_artifact_to is what decides whether the bytes are believed -- not
    # which host handed them over.
    try:
        sha, size = fetch_artifact_to(
            url, part, expected_sha256=sha_expected,
            max_bytes=ARTIFACT_MAX_BYTES, timeout=ARTIFACT_FETCH_TIMEOUT)
    except FeedHashMismatch as exc:
        raise package_store.PackageStoreError(
            400, "downloaded artefact's sha256 does not match the feed record -- refused") from exc
    except FeedError as exc:
        raise package_store.PackageStoreError(502, f"could not download the feed artefact: {exc}") from exc

    # store_verified_package re-verifies release_trust.verify_record against
    # settings.release_pubkeys -- belt and braces on top of _valid_records'
    # check at fetch time, and the ONLY check that matters for what actually
    # lands in companion_packages (see its docstring).
    package_store.store_verified_package(
        conn, settings,
        kind=kind, platform=platform, version=version, filename=filename,
        sha256=sha, size_bytes=size,
        min_version=str(record.get("min_version") or "0.0.0"),
        published_at=str(record.get("published_at") or ""),
        signed_binary=bool(record.get("signed_binary")),
        signature=str(record.get("signature") or ""),
        pubkey_id=str(record.get("pubkey_id") or ""),
        published_by=published_by,
        make_current=make_current,
        prune=False,
        part_path=part,
    )
    return build_packages_view(conn, settings)


def build_feed_view(conn, settings, app_state) -> dict[str, Any]:
    """The shape GET /api/v1/admin/feed serves, and what the admin partial
    renders. `available` never fabricates a record: it is exactly the last
    verified channel's package records minus anything already published
    HERE, so an admin never sees something recommended that a stale cache
    would then fail to publish."""
    state = db.get_feed_state(conn)
    configured = bool(settings.release_feed_url)
    cache = _cache(app_state)
    available: list[dict[str, Any]] = []
    if configured:
        # package_records only: the `dashboard` half of the channel is served
        # by dashboard_update.status(), which knows about runtime ids and the
        # running code root. Offering it here would put a [ PUBLISH ] button
        # next to something that must never enter companion_packages.
        for record in package_records(cache.get("valid_records") or []):
            kind, platform, version = _record_key(record)
            if kind and platform and version and db.get_package(conn, platform, version, kind) is None:
                available.append(record)
    channel = cache.get("channel") or {}
    image = channel.get("dashboard_image") if isinstance(channel.get("dashboard_image"), dict) else {}
    return {
        "configured": configured,
        "feed_url": settings.release_feed_url,
        "policy": effective_policy(conn, settings),
        "last_checked_at": state.get("last_checked_at"),
        "last_error": state.get("last_error"),
        "last_channel_generated_at": state.get("last_channel_generated_at"),
        "available": available,
        "image": {
            "tag": str(image.get("tag") or ""),
            "digest": str(image.get("digest") or ""),
            "current_running_version": VERSION,
        },
    }


# --------------------------------------------------------------- background poller
class FeedPoller:
    """A daemon thread that calls check_now on settings.release_feed_interval
    (default 86400s = daily), same shape as collector.Collector: never lets
    an exception escape the loop, and start()/stop() are idempotent so the
    lifespan handler can call them unconditionally.

    Only started when release_feed_url is set (app.py's lifespan gates it) --
    an unconfigured feed must add nothing at all: no thread, no DNS lookup,
    no log line."""

    def __init__(self, settings, app_state) -> None:
        self.settings = settings
        self.app_state = app_state
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="release-feed-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        # A short initial delay, not an immediate check at import time: a
        # container restart storm (a redeploy touching many customers'
        # dashboards near-simultaneously in a hypothetical multi-tenant
        # operator setup) must not turn into a thundering herd against the
        # feed host the moment every process boots.
        if self._stop.wait(POLLER_FIRST_CHECK_DELAY):
            return
        interval = max(POLLER_MIN_INTERVAL, float(self.settings.release_feed_interval or 86400.0))
        while not self._stop.is_set():
            try:
                conn = db.connect(self.settings.db_path)
                try:
                    check_now(conn, self.settings, self.app_state)
                finally:
                    conn.close()
            except Exception:
                log.exception("release feed poller cycle failed")
            if self._stop.wait(interval):
                return


# --------------------------------------------------------------------- JSON API
router = APIRouter(prefix="/api/v1/admin/feed")


class FeedPublishIn(BaseModel):
    kind: str = "companion"
    platform: str
    version: str
    make_current: bool = False


class FeedPolicyIn(BaseModel):
    policy: str


@router.get("")
def api_admin_feed(request: FastAPIRequest, conn=Depends(get_conn)) -> dict[str, Any]:
    _require_admin(request)
    settings = request.app.state.settings
    return build_feed_view(conn, settings, request.app.state)


@router.post("/check")
def api_admin_feed_check(request: FastAPIRequest, conn=Depends(get_conn)) -> dict[str, Any]:
    _require_admin(request)
    settings = request.app.state.settings
    if not settings.release_feed_url:
        raise HTTPException(status_code=503, detail="DASH_RELEASE_FEED_URL is not configured")
    result = check_now(conn, settings, request.app.state)
    return {"ok": result["ok"], "error": result.get("error"),
            "view": build_feed_view(conn, settings, request.app.state)}


@router.post("/publish")
def api_admin_feed_publish(
    payload: FeedPublishIn, request: FastAPIRequest, conn=Depends(get_conn)
) -> dict[str, Any]:
    user = _require_admin(request)
    settings = request.app.state.settings
    if not settings.release_feed_url:
        raise HTTPException(status_code=503, detail="DASH_RELEASE_FEED_URL is not configured")
    try:
        view = publish_from_feed(
            conn, settings, request.app.state,
            kind=payload.kind.strip().lower(), platform=payload.platform.strip().lower(),
            version=payload.version.strip(), make_current=payload.make_current,
            published_by=user,
        )
    except package_store.PackageStoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {"ok": True, "view": view}


@router.post("/policy")
def api_admin_feed_policy(
    payload: FeedPolicyIn, request: FastAPIRequest, conn=Depends(get_conn)
) -> dict[str, Any]:
    _require_admin(request)
    settings = request.app.state.settings
    try:
        policy = set_policy(conn, payload.policy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "policy": policy, "view": build_feed_view(conn, settings, request.app.state)}
