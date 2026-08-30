#!/usr/bin/env python3
"""Is this origin one a phone will install the dashboard from? Exit 1 if not.

MOBILE_PLAN.md M6, 2026-08-30. A phone browser refuses to register a service
worker, refuses to offer "Add to Home screen" and refuses to verify a TWA
unless the origin is a real https one, and every one of those refusals is
SILENT: Chrome just never shows the install prompt, the app opens with a URL
bar, and nothing in the dashboard's own logs says why. This script is the
thing that says why, one line per check, in the order a browser cares about.

    python tools\\check_mobile_origin.py https://truenas.tail26290e.ts.net:9443
    python tools\\check_mobile_origin.py <url> --json     # machine-readable

It is what `docs/MOBILE.md`'s runbook tells an admin to run after putting the
dashboard behind TLS, before touching a phone at all.

WHAT IT CHECKS, AND WHY EACH ONE IS A BROWSER RULE AND NOT AN OPINION

  https             `isSecureContext` is false on http (except localhost), and
                    `navigator.serviceWorker` does not exist there.
  certificate       a certificate the SYSTEM trust store rejects fails the
                    same way: the phone shows an interstitial, and a TWA will
                    not open at all. Tailscale Serve's cert is a real Let's
                    Encrypt one, so this passing is the normal case.
  manifest          `/manifest.webmanifest` must be fetchable with NO session
                    (the browser fetches it before anyone signs in) and must
                    carry `start_url` and a non-empty `icons` array, which are
                    the two fields Chrome's installability check reads.
  service worker    `/sw.js` must be served from the ROOT path with
                    `Service-Worker-Allowed`, or its scope cannot be `/`.
  asset links       `/.well-known/assetlinks.json` must be reachable and be
                    JSON. An empty list is fine and is the default: it means
                    "no Android app configured yet", not a fault.
  health            `/api/v1/health` must answer with a `version`. That is
                    the proof the thing behind the TLS terminator is THIS
                    dashboard and not the NAS's own web UI on a wrong port.
  cookie secure     the session cookie must carry `Secure` on an https origin.
                    `DASH_COOKIE_SECURE=auto` only sets it when the request
                    LOOKS https to the app, which behind a proxy means
                    `X-Forwarded-Proto` from an address in
                    `DASH_TRUSTED_PROXIES` (default: loopback only). A proxy
                    on another container's address is the case that silently
                    leaves the flag off -- see docs/MOBILE.md.

STOPS AT THE FIRST FAIL, deliberately: the checks are ordered so that the
first failure is the cause and everything after it would be a consequence
(no https -> no service worker -> no install), and printing four red lines
for one problem is how a runbook trains someone to skim past it.

ONE FETCH FUNCTION, injected. Every check goes through `fetch(url)` and
nothing else touches the network, so `dashboard/tests/test_mobile_origin.py`
drives every verdict here from a TestClient-backed fake with no server, no
sockets and no certificate anywhere.

Stdlib only (urllib + ssl + json): this runs on a customer's NAS or an
admin's laptop, where the dashboard's venv is not.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

TIMEOUT = 15.0
USER_AGENT = "ccsync-check-mobile-origin/1"


# --------------------------------------------------------------- the fetch

@dataclass
class Response:
    """What a check is allowed to know about one request."""
    status: int
    headers: dict[str, str] = field(default_factory=dict)   # lowercase keys
    body: bytes = b""
    # Every `Set-Cookie` on the response, in order. Kept separate from
    # `headers` because a dict cannot hold two of them and the cookie check
    # needs them all: the dashboard may set more than one.
    set_cookies: tuple[str, ...] = ()

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class FetchError(Exception):
    """The request never produced an HTTP response (DNS, refused, timeout)."""


class CertificateProblem(FetchError):
    """TLS itself was refused. Its own type because it is its own check."""


def http_fetch(url: str) -> Response:
    """The real one: GET `url` with the SYSTEM trust store, follow redirects.

    Anonymous on purpose -- no cookie jar, no credentials. Every path this
    script asks for is one a signed-out browser must be able to fetch, and
    checking them with a session would pass on a dashboard where they are
    behind the login wall (which is the actual failure mode: a manifest
    that 303s to /login makes the install prompt never appear)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as reply:
            return Response(
                status=reply.status,
                headers={k.lower(): v for k, v in reply.headers.items()},
                body=reply.read(),
                set_cookies=tuple(reply.headers.get_all("Set-Cookie") or ()),
            )
    except urllib.error.HTTPError as exc:                     # a real response
        body = b""
        try:
            body = exc.read()
        except Exception:                                     # noqa: BLE001
            pass
        return Response(
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            body=body,
            set_cookies=tuple((exc.headers.get_all("Set-Cookie") if exc.headers else None) or ()),
        )
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLError) or isinstance(reason, ssl.CertificateError):
            raise CertificateProblem(str(reason)) from exc
        raise FetchError(str(reason)) from exc
    except ssl.SSLError as exc:                               # not always wrapped
        raise CertificateProblem(str(exc)) from exc
    except OSError as exc:
        raise FetchError(str(exc)) from exc


Fetch = Callable[[str], Response]


# --------------------------------------------------------------- the checks

@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    # A check that could not reach a verdict without being a fault: the
    # cookie one, when the login page sets no cookie at all. Reported as a
    # line of its own so nobody reads "7 lines, no FAIL" as "7 things
    # verified".
    skipped: bool = False

    @property
    def verdict(self) -> str:
        return "SKIP" if self.skipped else ("OK" if self.ok else "FAIL")

    def line(self) -> str:
        return f"{self.verdict:4}  {self.name:<15}  {self.detail}"


def normalise(url: str) -> str:
    """`https://host:9443/anything?x` -> `https://host:9443`."""
    parts = urlsplit(url if "://" in url else "https://" + url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def check_https(origin: str) -> Result:
    scheme = urlsplit(origin).scheme
    if scheme == "https":
        return Result("https", True, f"{origin} is an https origin")
    return Result("https", False,
                  f"{origin} is {scheme or 'not a URL'}, so the phone has no secure "
                  "context: no service worker, no install prompt, no TWA")


def check_certificate(origin: str, fetch: Fetch) -> Result:
    """A request that reaches ANY status proves the handshake succeeded."""
    try:
        reply = fetch(origin + "/api/v1/health")
    except CertificateProblem as exc:
        return Result("certificate", False, f"TLS refused: {exc}")
    except FetchError as exc:
        return Result("certificate", False, f"could not connect: {exc}")
    return Result("certificate", True,
                  f"handshake fine (health answered {reply.status})")


def check_manifest(origin: str, fetch: Fetch) -> Result:
    url = origin + "/manifest.webmanifest"
    try:
        reply = fetch(url)
    except FetchError as exc:
        return Result("manifest", False, f"{url}: {exc}")
    if reply.status != 200:
        return Result("manifest", False,
                      f"{url} answered {reply.status} to an anonymous request "
                      "(the browser fetches it signed out)")
    try:
        doc = reply.json()
    except Exception as exc:                                  # noqa: BLE001
        return Result("manifest", False, f"{url} is not JSON: {exc}")
    missing = [k for k in ("start_url", "icons") if not doc.get(k)]
    if missing:
        return Result("manifest", False,
                      f"{url} has no {', '.join(missing)} -- Chrome will not offer to install it")
    return Result("manifest", True,
                  f"start_url {doc['start_url']!r}, {len(doc['icons'])} icons")


def check_service_worker(origin: str, fetch: Fetch) -> Result:
    url = origin + "/sw.js"
    try:
        reply = fetch(url)
    except FetchError as exc:
        return Result("service worker", False, f"{url}: {exc}")
    if reply.status != 200:
        return Result("service worker", False, f"{url} answered {reply.status}")
    allowed = reply.headers.get("service-worker-allowed")
    if not allowed:
        return Result("service worker", False,
                      f"{url} carries no Service-Worker-Allowed header, so its scope "
                      "cannot be /")
    return Result("service worker", True, f"served with Service-Worker-Allowed: {allowed}")


def check_asset_links(origin: str, fetch: Fetch) -> Result:
    url = origin + "/.well-known/assetlinks.json"
    try:
        reply = fetch(url)
    except FetchError as exc:
        return Result("asset links", False, f"{url}: {exc}")
    if reply.status != 200:
        return Result("asset links", False,
                      f"{url} answered {reply.status} -- an Android app installed from "
                      "this origin would open with a URL bar")
    try:
        doc = reply.json()
    except Exception as exc:                                  # noqa: BLE001
        return Result("asset links", False, f"{url} is not JSON: {exc}")
    if not doc:
        # The DEFAULT, and not a fault: no Android package configured yet.
        return Result("asset links", True,
                      "empty (no Android package configured yet -- see docs/ANDROID.md)")
    return Result("asset links", True, f"{len(doc)} statement(s)")


def check_health(origin: str, fetch: Fetch) -> Result:
    url = origin + "/api/v1/health"
    try:
        reply = fetch(url)
    except FetchError as exc:
        return Result("health", False, f"{url}: {exc}")
    if reply.status != 200:
        return Result("health", False, f"{url} answered {reply.status}")
    try:
        doc = reply.json()
    except Exception as exc:                                  # noqa: BLE001
        return Result("health", False, f"{url} is not JSON: {exc} "
                                       "(is something else answering on this port?)")
    version = str(doc.get("version") or "")
    if not version:
        return Result("health", False,
                      f"{url} has no version -- whatever is behind this origin, it is "
                      "not the dashboard")
    return Result("health", True, f"dashboard {version}")


def check_cookie_secure(origin: str, fetch: Fetch) -> Result:
    """The Secure flag on whatever the login page sets.

    This is the check that catches the trusted-proxy trap. Behind a TLS
    terminator the app sees plain http; `DASH_COOKIE_SECURE=auto` turns the
    flag on from `X-Forwarded-Proto`, but auth.request_is_https believes that
    header ONLY from a peer inside `DASH_TRUSTED_PROXIES` (default
    `127.0.0.1,::1`). A proxy that arrives from another container's address
    therefore gets a cookie with no Secure flag on an https origin, which no
    test on the server can see and no browser complains about."""
    url = origin + "/login"
    try:
        reply = fetch(url)
    except FetchError as exc:
        return Result("cookie secure", False, f"{url}: {exc}")
    if not reply.set_cookies:
        return Result("cookie secure", True,
                      "the login page set no cookie, so nothing to judge here; sign in "
                      "on the phone and check the session cookie in devtools",
                      skipped=True)
    insecure = [c.split("=", 1)[0] for c in reply.set_cookies
                if "secure" not in c.lower().replace("secure-", "")]
    if insecure:
        return Result("cookie secure", False,
                      f"{', '.join(insecure)} set without Secure on an https origin -- "
                      "set DASH_COOKIE_SECURE=1, or add the proxy's address to "
                      "DASH_TRUSTED_PROXIES")
    return Result("cookie secure", True,
                  f"{len(reply.set_cookies)} cookie(s), all Secure")


def run_checks(origin: str, fetch: Fetch) -> list[Result]:
    """In browser order, stopping at the first FAIL (see the module docstring)."""
    results = [check_https(origin)]
    if not results[-1].ok:
        return results
    for check in (check_certificate, check_manifest, check_service_worker,
                  check_asset_links, check_health, check_cookie_secure):
        results.append(check(origin, fetch))
        if not results[-1].ok:
            break
    return results


# ----------------------------------------------------------------- the CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", help="the origin editors browse, e.g. https://nas.tailnet.ts.net:9443")
    ap.add_argument("--json", action="store_true",
                    help="print the results as JSON instead of lines")
    args = ap.parse_args(argv)

    origin = normalise(args.url)
    results = run_checks(origin, http_fetch)
    failed = [r for r in results if not r.ok]

    if args.json:
        print(json.dumps({
            "origin": origin,
            "ok": not failed,
            "checks": [{"name": r.name, "verdict": r.verdict, "detail": r.detail}
                       for r in results],
        }, indent=2))
    else:
        for result in results:
            print(result.line())
        if failed:
            # Named again at the bottom: the FAIL is the last line only when
            # nothing was skipped, and a runbook reader scrolls to the end.
            print(f"\nSTOPPED at {failed[0].name}. Fix that and run this again.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
