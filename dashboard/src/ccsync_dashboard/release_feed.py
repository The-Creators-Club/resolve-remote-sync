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
                headers = getattr(exc, "headers", None)
                # bug-hunt-2026-09-03 dash-release-jobs-5: an HTTPError IS an
                # open response holding a socket, so the raising half of this
                # walk leaked one file descriptor per hop until the GC caught
                # up. The non-raising 3xx branch below has always closed its
                # response; these two halves must agree. Closed before the
                # Location is parsed, because that parse can itself raise.
                try:
                    exc.close()
                except Exception:  # noqa: BLE001 - a hop we are leaving anyway
                    pass
                current = _redirect_target(current, headers)
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


def open_https_stream(url: str, *, timeout: float):
    """The public name for the follow above (2026-08-18).

    `cli_tools.py` fetches the AI CLIs from their publishers' own
    distributions, and GitHub 302s a release asset to
    release-assets.githubusercontent.com exactly as this module's feed does.
    ONE implementation of "which redirects may be followed, and on what
    terms" -- a second one written next door is how the https-only, no-hop-
    limit, no-credential rule ends up being true of one caller and not the
    other. Everything it returns is sha256-verified by the caller, which is
    the condition that makes the follow safe at all (docs/GOTCHAS.md 12).
    """
    return _open_following_https_redirects(url, timeout=timeout)


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


def channel_retractions(channel: Any) -> list[dict[str, str]]:
    """The channel's `retracted` list: builds the vendor has RECALLED
    (REL-3, resilience sweep 2026-08-28).

    Shape: [{kind, platform, version, reason, at}]. It lives inside the signed
    channel document (canonical_channel_bytes covers the whole dict), so the
    feed host cannot fabricate a recall and cannot suppress one either without
    breaking the signature -- which matters, because a recall is the one
    channel message whose SUPPRESSION is the attack.

    Malformed entries are dropped one by one rather than failing the list: a
    feed carrying one bad entry beside three good ones must still deliver the
    three. Anything missing kind/platform/version names no build and can
    therefore do nothing.
    """
    raw = channel.get("retracted") if isinstance(channel, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        platform = str(item.get("platform") or "").strip().lower()
        version = str(item.get("version") or "").strip()
        if not (kind and platform and version):
            continue
        out.append({
            "kind": kind, "platform": platform, "version": version,
            "reason": str(item.get("reason") or "").strip(),
            "at": str(item.get("at") or "").strip(),
        })
    return out


def apply_retractions(conn, channel: Any, now: str) -> list[str]:
    """Honour every recall in the channel, under EVERY policy including
    `manual` (REL-3).

    Policy governs whether this dashboard takes NEW builds; it has never
    governed whether it keeps offering one the vendor has withdrawn, and the
    default policy is `manual`, so a recall that respected policy would reach
    almost nobody. Un-currenting is the whole action here: the row and the
    file stay, because the fleet may still be running the build and the admin
    has to be able to see what they are rolling back from.
    """
    applied: list[str] = []
    for item in channel_retractions(channel):
        if db.retract_package(conn, item["kind"], item["platform"], item["version"],
                              item["reason"], now):
            applied.append(f"{item['kind']}/{item['platform']} {item['version']}")
            log.warning(
                "release feed: %s/%s %s has been RECALLED by the vendor%s -- it is no "
                "longer current and will not be offered to any machine",
                item["kind"], item["platform"], item["version"],
                f" ({item['reason']})" if item["reason"] else "")
    if applied:
        conn.commit()
    return applied


def _valid_records(channel: dict[str, Any], pubkeys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Every package record in `channel` whose OWN signature verifies.
    Belt-and-braces on top of the channel-level signature: a compromised or
    buggy feed host could otherwise splice in an unsigned or mis-signed
    record under an otherwise-valid, correctly-signed channel wrapper."""
    out: list[dict[str, Any]] = []
    packages = channel.get("packages")
    if not isinstance(packages, list):
        return out
    # A recalled build is not "available" either (REL-3, 2026-08-28): dropping
    # it here takes it out of the auto-publish selection AND off the admin
    # page's [ PUBLISH ] buttons in one place, so a dashboard that has never
    # published it cannot start now.
    recalled = {
        (r["kind"], r["platform"], r["version"]) for r in channel_retractions(channel)
    }
    dropped = 0
    for rec in packages:
        if not isinstance(rec, dict):
            dropped += 1
            continue
        ok, _detail = release_trust.verify_record(rec, str(rec.get("signature", "")), pubkeys)
        if not ok:
            dropped += 1
            continue
        key = (str(rec.get("kind", "")), str(rec.get("platform", "")).strip().lower(),
               str(rec.get("version", "")))
        if key in recalled:
            log.warning("release feed: %s/%s %s is in the channel's `retracted` list "
                        "-- not offering it", *key)
            continue
        # A validly signed record can still be a typo that would brick the
        # channel: min_version above the version it describes raises every
        # companion's permanent downgrade floor past the build on offer
        # (dash-release-ai-3, 2026-08-21). Dropped here as well as refused in
        # package_store, so it is never even shown to an admin as available.
        if release_trust.min_version_exceeds_version(
                rec.get("version"), rec.get("min_version")):
            log.warning("release feed: ignoring %s/%s %s -- its min_version %s is higher "
                        "than its own version, which would raise every companion's "
                        "downgrade floor above it",
                        rec.get("kind"), rec.get("platform"), rec.get("version"),
                        rec.get("min_version"))
            continue
        out.append(rec)
    if dropped:
        log.warning("release feed: %d package record(s) failed verification and were ignored", dropped)
    return out


def channel_current(channel: Any) -> dict[tuple[str, str], str]:
    """The channel's `current` pointer: {(kind, platform): version}.

    release-pipeline-5 (2026-08-21). The feed used to be a pure APPEND log
    with no statement of what the vendor currently ships, so `_apply_policy`
    replayed all 18 historical records in list order and made each one
    current in turn -- a fresh customer downloaded ~1 GB on its first check,
    and whichever record happened to be LAST won, which is append order and
    not version order (a --force republish of an older build, or a late macOS
    CI upload, offered the whole fleet a rollback). This object is part of
    the SIGNED channel document (canonical_channel_bytes covers the whole
    dict), so the feed host cannot steer it. Absent or malformed reads as
    "no pointer", and the caller falls back to the highest version.
    """
    out: dict[tuple[str, str], str] = {}
    raw = channel.get("current") if isinstance(channel, dict) else None
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        kind, sep, platform = str(key).partition("/")
        version = str(value or "").strip()
        if sep and kind.strip() and platform.strip() and version:
            out[(kind.strip(), platform.strip())] = version
    return out


def _version_sort_key(version: str) -> tuple[int, ...]:
    """Dotted-numeric to a comparable tuple; () for anything else, which sorts
    below every real version. Same rule as dashboard_update.version_tuple --
    and the reason "0.10.0 comes after 0.9.9" holds here too (CLAUDE.md:
    the companion never reaches 1.0)."""
    raw = str(version or "").strip()
    if not raw or any(ch not in "0123456789." for ch in raw):
        return ()
    try:
        return tuple(int(p) for p in raw.split(".") if p != "")
    except ValueError:
        return ()


def select_offered_records(
    records: list[dict[str, Any]], channel: Any
) -> dict[tuple[str, str], dict[str, Any]]:
    """ONE record per (kind, platform) -- what an auto-publish policy acts on.

    The channel's `current` pointer names it; without one, the highest
    version wins. A pointer naming a version this feed does not carry selects
    NOTHING for that pair, deliberately: publishing some other build because
    the named one is missing is exactly the accidental rollback
    release-pipeline-5 is about.
    """
    pointer = channel_current(channel)
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        kind, platform, version = _record_key(record)
        if not (kind and platform and version):
            continue
        key = (kind, platform)
        named = pointer.get(key)
        if named is not None:
            if version == named:
                chosen[key] = record
            continue
        best = chosen.get(key)
        if best is None or _version_sort_key(version) > _version_sort_key(_record_key(best)[2]):
            chosen[key] = record
    return chosen


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
    # BEFORE the policy runs, and outside it (REL-3, 2026-08-28): a recall is
    # honoured under EVERY policy, `manual` included -- policy governs whether
    # this dashboard takes NEW builds and has never governed whether it keeps
    # offering one the vendor has withdrawn. Manual is the default, so a
    # recall that respected policy would reach almost nobody.
    retracted = apply_retractions(conn, channel, now)
    applied = _apply_policy(conn, settings, app_state, valid_records, now)
    # REL-11 (resilience sweep 2026-08-28): "every dashboard build on offer
    # needs a new container image" is a state a site can sit in for months
    # while every check succeeds. Recorded here, where the records are, so the
    # fleet page's banner can read it from the database. Imported lazily and
    # never fatal: dashboard_update imports this module, and a feed check must
    # not fail over a banner.
    try:
        from . import dashboard_update

        dashboard_update.record_feed_runtime_mismatch(conn, settings, app_state)
        conn.commit()
    except Exception:                                                 # noqa: BLE001
        log.warning("could not record the feed's runtime-mismatch state", exc_info=True)
    refused = record_offer_state(conn, valid_records, now)
    return {"ok": True, "error": None, "applied": applied, "retracted": retracted,
            "refused": refused}


def record_offer_state(conn, valid_records: list[dict[str, Any]], now: str) -> list[str]:
    """What the vendor is offering, and what of it this dashboard cannot hand
    out yet (SYS-2, 2026-09-04). Returns the refused "kind/platform version"
    strings.

    Two durable facts, written on EVERY check whether or not anything is
    wrong. `db.set_feed_offered` is what lets `alerts._check_versions_behind`
    measure the fleet against the vendor's channel rather than against this
    dashboard's own shelf; the notice is the half a `policy = "current"` site
    could never see, because its only previous statement was a log line and
    nobody clicks anything there.

    The refusal itself is REL-4/SYS-13's and is correct: a companion whose
    `requires_dashboard` is above this build is staged, never made current.
    What was missing is that the same site then reads as fully up to date on
    the fleet grid, in the weekly report and on the Packages page - the
    fleet's updates have stopped and every page agrees that nothing is wrong.

    Never raises: this is the tail of a poller, and a diagnosis must not be
    able to fail the check it describes.
    """
    offered: dict[str, list[str]] = {}
    refused: list[str] = []
    subjects: list[str] = []
    try:
        for record in package_records(valid_records):
            kind = str(record.get("kind") or "")
            platform = str(record.get("platform") or "")
            version = str(record.get("version") or "")
            if kind != "companion" or not platform or not version:
                continue
            offered.setdefault(platform, []).append(version)
            if package_store.blocks_on_dashboard_version(
                    kind, record.get("requires_dashboard")):
                refused.append(f"{kind}/{platform} {version}")
                subjects.append(f"{platform} {version}")
                db.notice(
                    conn, "feed_publish_refused", "error", f"{platform} {version}",
                    body=(f"A new CC Sync build for {platform} ({version}) is on "
                          f"offer but cannot be handed to the computers here: it "
                          f"needs dashboard "
                          f"{str(record.get('requires_dashboard') or '')} and this "
                          f"dashboard is {VERSION}. Until the dashboard is "
                          f"updated, every computer in the fleet stays on the "
                          f"build it has and this server reports them all as up "
                          f"to date."),
                    fix=("On the dashboard: SETTINGS, PACKAGES, then update the "
                         "DASHBOARD from the vendor feed. The companion build "
                         "becomes available to the fleet straight after."),
                    now=now)
        # Every check, refusals or none: being asked to clear a kind is the
        # evidence that its writer ran (db._mark_notice_checked).
        db.clear_notices_of_kind(conn, "feed_publish_refused", subjects, now=now)
        db.set_feed_offered(conn, offered)
        conn.commit()
    except Exception:                                                 # noqa: BLE001
        log.warning("could not record what the vendor feed offers", exc_info=True)
    if refused:
        log.warning("release feed: %s cannot be made current here (this dashboard "
                    "is %s)", ", ".join(refused), VERSION)
    return refused


def _apply_policy(conn, settings, app_state, valid_records: list[dict[str, Any]], now: str) -> list[str]:
    """manual: do nothing (the admin page's [ PUBLISH ] buttons are the only
    writer). stage/current: auto-publish the ONE record the channel currently
    offers per (kind, platform), current also flipping it live. Returns the
    "kind/platform/version" strings actually published, for the log line and
    the /check response -- an admin watching a fresh install should see this
    happen, not infer it from the packages table changing.

    "The one record" since 2026-08-21 (release-pipeline-5): this used to walk
    every verified record in list order, publishing all of them and, under
    `current`, making each current in turn -- so the LAST entry in the file
    won rather than the newest build, and a fresh dashboard downloaded the
    whole history to get there. `select_offered_records` picks by the
    channel's signed `current` pointer, falling back to the highest version;
    everything else in the feed stays available behind the page's own
    [ PUBLISH ] buttons, which is where a deliberate rollback belongs.
    """
    policy = effective_policy(conn, settings)
    if policy == "manual":
        return []
    applied: list[str] = []
    # package_records, not valid_records: `stage`/`current` must never
    # auto-apply a DASHBOARD code update. Replacing the code the container is
    # running is a ten-second outage and an admin's decision, not a
    # consequence of a policy about editor packages (ZERO_TOUCH_PLAN.md WP K).
    channel = _cache(app_state).get("channel") or {}
    offered = select_offered_records(package_records(valid_records), channel)
    for (kind, platform), record in sorted(offered.items()):
        version = _record_key(record)[2]
        existing = db.get_package(conn, platform, version, kind)
        if existing is not None:
            _warn_on_sha_conflict(existing, record)
            # The pointer can move BACKWARDS -- that is how a bad build is
            # withdrawn from feed customers (release-pipeline-5). A version
            # this dashboard already holds still has to become current when
            # the channel says it is current.
            if policy == "current" and not existing["is_current"]:
                # bug-hunt-2026-09-03 dash-release-jobs-2: through
                # package_store, not db.set_current_package, which checks only
                # retraction. This was the third door onto `is_current` and the
                # only one the REL-4 ordering gate did not stand at.
                try:
                    package_store.make_current(
                        conn, settings, platform=platform, version=version, kind=kind)
                except package_store.PackageStoreError as exc:
                    conn.rollback()
                    log.warning("release feed (current policy) did NOT make %s/%s %s "
                                "current: %s", kind, platform, version, exc.detail)
                    continue
                conn.commit()
                log.info("release feed (current policy) made %s/%s %s current again",
                         kind, platform, version)
                applied.append(f"{kind}/{platform} {version}")
            continue
        # bug-hunt-2026-09-03 dash-release-jobs-3: asked BEFORE the download.
        # store_verified_package refuses a make_current publish this dashboard
        # is too old for, after streaming up to 200 MiB into a .part it then
        # unlinks -- and refuses the whole publish with it, so the build was
        # re-fetched and re-thrown-away on every check and never reached the
        # shelf. Staging it is what its own comment says should happen.
        stage_only = package_store.blocks_on_dashboard_version(
            kind, record.get("requires_dashboard"))
        if stage_only:
            log.info("release feed: staging %s/%s %s WITHOUT making it current - "
                     "it needs dashboard %s and this dashboard is %s. Update the "
                     "dashboard, then make it current from the Packages page.",
                     kind, platform, version, record.get("requires_dashboard"), VERSION)
        try:
            publish_from_feed(
                conn, settings, app_state, kind=kind, platform=platform, version=version,
                make_current=(policy == "current" and not stage_only),
                published_by="release-feed",
            )
        except package_store.PackageStoreError as exc:
            log.warning("release feed auto-publish of %s/%s %s failed: %s",
                        kind, platform, version, exc.detail)
            continue
        applied.append(f"{kind}/{platform} {version}")
    if applied:
        log.info("release feed (%s policy) auto-published: %s", policy, ", ".join(applied))
    return applied


def sha_conflict(existing: Any, record: dict[str, Any]) -> bool:
    """Whether a published row and a feed record share a version but not their
    bytes (release-pipeline-6, 2026-08-21). `tools/publish_feed.py` replaces a
    record in place, so a CI re-run published with --force gives new customers
    one binary and everyone who already holds that version another -- under
    the same version number, which is the only thing drift tooling, the
    Packages page and every companion report speak in."""
    if existing is None:
        return False
    try:
        held = str(existing["sha256"] or "").lower()
    except (KeyError, IndexError, TypeError):
        held = ""
    offered = str(record.get("sha256") or "").lower()
    return bool(held and offered and held != offered)


def _warn_on_sha_conflict(existing: Any, record: dict[str, Any]) -> bool:
    if not sha_conflict(existing, record):
        return False
    kind, platform, version = _record_key(record)
    log.warning(
        "release feed: %s/%s %s is published here with sha256 %s but the feed now "
        "offers sha256 %s for the SAME version -- same version, different bytes. "
        "Nothing was replaced; ask the vendor to publish a new version number",
        kind, platform, version,
        str(existing["sha256"] or "")[:12], str(record.get("sha256") or "")[:12])
    return True


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
    existing = db.get_package(conn, platform, version, kind)
    if existing is not None:
        # Name the DISAGREEMENT when there is one (release-pipeline-6,
        # 2026-08-21): "already published" is a fine answer when the bytes
        # match and a misleading one when they do not, and a version number
        # standing for two different binaries is invisible to everything else
        # in this product.
        if _warn_on_sha_conflict(existing, record):
            raise package_store.PackageStoreError(
                409,
                f"{kind} {platform} {version} is already published on this dashboard, but "
                f"the feed offers DIFFERENT bytes for that same version "
                f"(published sha256 {str(existing['sha256'] or '')[:12]}, feed "
                f"{str(record.get('sha256') or '')[:12]}). Nothing was replaced. The "
                f"vendor has to publish this build under a new version number.",
            )
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
        # The two SIGNED extras and the two ADVISORY provenance fields
        # (REL-4/SYS-13, REL-16, REL-13, 2026-08-28). The first two are inside
        # the signature and are re-verified by store_verified_package, so a
        # feed host that strips or edits one gets a refusal, not a mis-offered
        # build; the git pair is advisory and shown, never acted on.
        requires_dashboard=str(record.get("requires_dashboard") or ""),
        arch=str(record.get("arch") or ""),
        git_sha=str(record.get("git_sha") or ""),
        git_dirty=bool(record.get("git_dirty")),
        # APP-16 (2026-09-04): the feed has carried `notes` on every record
        # since publish_feed.py's first version and nothing here read it.
        # Unsigned, display only, bounded by db.package_notes -- a feed host
        # cannot make a build unverifiable with it, only wordy.
        notes=str(record.get("notes") or ""),
        published_by=published_by,
        make_current=make_current,
        # REL-5 (resilience sweep 2026-08-28): prune by default on BOTH
        # publish paths. Nothing on the release path ever pruned, and this one
        # runs unattended on a daily timer -- a year of it is 50 companion exes
        # and 50 onboard exes on the dataset the SQLite database lives on, and
        # a full /data is the dashboard going down. db.prune_companion_packages
        # keeps the current build plus the two newest, which is the rollback
        # material anybody actually reaches for.
        prune=True,
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
    conflicts: list[dict[str, str]] = []
    if configured:
        # package_records only: the `dashboard` half of the channel is served
        # by dashboard_update.status(), which knows about runtime ids and the
        # running code root. Offering it here would put a [ PUBLISH ] button
        # next to something that must never enter companion_packages.
        for record in package_records(cache.get("valid_records") or []):
            kind, platform, version = _record_key(record)
            if not (kind and platform and version):
                continue
            existing = db.get_package(conn, platform, version, kind)
            if existing is None:
                available.append(record)
            elif sha_conflict(existing, record):
                # Surfaced, not hidden (release-pipeline-6, 2026-08-21): this
                # version is not "available" (publishing it would 409) but an
                # admin has to be able to see that their copy and the vendor's
                # differ, since every other surface speaks only in versions.
                conflicts.append({
                    "kind": kind, "platform": platform, "version": version,
                    "published_sha256": str(existing["sha256"] or ""),
                    "feed_sha256": str(record.get("sha256") or ""),
                })
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
        "sha_conflicts": conflicts,
        # What the vendor has RECALLED (REL-3, 2026-08-28), whether or not
        # this dashboard ever published it: an admin reading "0.9.55 was
        # withdrawn: it corrupts proxies" needs to see it even on a site that
        # never took 0.9.55, because that is how they know not to hunt for it.
        "retracted": channel_retractions(channel),
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
    # `applied` is what a stage/current policy just did (check_now's docstring
    # has always said this belongs in the response; 2026-08-21): an admin
    # watching a fresh install should see it, not infer it from the packages
    # table changing under them.
    return {"ok": result["ok"], "error": result.get("error"),
            "applied": result.get("applied") or [],
            # What this check RECALLED (REL-3, 2026-08-28). Beside `applied`
            # for the same reason: an admin pressing Check now must see that a
            # build was withdrawn from under their fleet, not deduce it from
            # the current pointer having moved.
            "retracted": result.get("retracted") or [],
            # SYS-2 (2026-09-04): and what it CANNOT hand out. The admin who
            # just pressed the button is the one person who can act on "this
            # build needs a newer dashboard", and the answer used to be a log
            # line on a machine they have no shell on.
            "refused": result.get("refused") or [],
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
