"""The Android app's half of the site: Digital Asset Links, and the two
settings behind them (docs/MOBILE_PLAN.md §4 M5, 2026-08-30).

The dashboard is installed on a phone as a PWA (M4) and wrapped as a Trusted
Web Activity so a studio can hand its editors a real APK. A TWA opens WITHOUT
a URL bar only if the origin vouches for the app: Chrome fetches
`https://<origin>/.well-known/assetlinks.json` and looks for a statement
naming the APK's package and the SHA-256 fingerprint of the certificate it was
signed with. If the statement is missing, malformed, or names a different
fingerprint, the app still opens -- as a Custom Tab, with the URL bar, and
NOTHING anywhere says why. That silence is why this module exists as its own
route rather than as one more field in `GET /api/v1/site`, why the Settings
panel has a `[ CHECK ]`, and why `docs/ANDROID.md` leads with the symptom.

Three rules the statement has to keep:

* **Open.** Chrome fetches it with no cookie jar, from a phone that has never
  signed in (`app._OPEN_EXACT`). It carries no secret: a package name is
  printed on the Play listing and a certificate fingerprint is a public key's
  digest -- publishing it is the entire mechanism.
* **`[]` until both halves are configured.** A statement naming a package with
  no fingerprints verifies nothing; serving one would only make a broken setup
  look configured. Both fields set, or an empty array.
* **Cacheable, briefly.** Chrome re-verifies on install and periodically after;
  `max-age=3600` is long enough that the check is not a per-launch round trip
  and short enough that pasting a corrected fingerprint takes effect within
  the hour rather than at the next cache eviction.

The `[ CHECK ]` button deliberately does NOT make an HTTP request back to this
same dashboard. The container runs `--workers 1`: a synchronous self-request
from inside a request handler is a deadlock, not a diagnostic. It calls the
same `statements()` the route itself calls, which is the identical answer by
construction, and prints Google's own check URL for the admin to open from a
machine that is actually outside the tailnet.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Mapping
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from . import db, site_store
from .api import get_conn

router = APIRouter()
log = logging.getLogger("ccsync.dashboard.android")

# Exactly one path under /.well-known/, and it is this one. Anything else
# there would be a second open route nobody asked for.
ASSETLINKS_PATH = "/.well-known/assetlinks.json"

# The one relation a TWA needs: "this app may handle every URL on this site,
# and it is the same publisher". Google's spelling, not ours.
RELATION = "delegate_permission/common.handle_all_urls"

# One hour. See this module's docstring.
CACHE_SECONDS = 3600

# Where an admin can ask GOOGLE what it sees at this origin -- the same API
# Chrome's verifier uses, so its answer is the one that decides whether the
# URL bar appears. Printed, never called from the server: a dashboard on a
# tailnet cannot reach it, and a check that silently fails open would be worse
# than no check.
CHECK_API = "https://digitalassetlinks.googleapis.com/v1/statements:list"


def statements_for(android: Mapping[str, Any] | None) -> list[dict]:
    """The asset-links document for one site manifest's `android` block.

    Pure, so the route and the `[ CHECK ]` panel cannot drift apart.
    """
    android = android or {}
    package = str(android.get("package_name") or "").strip()
    prints = [
        str(f).strip().upper()
        for f in (android.get("sha256_cert_fingerprints") or [])
        if str(f).strip()
    ]
    if not package or not prints:
        return []
    return [
        {
            "relation": [RELATION],
            "target": {
                "namespace": "android_app",
                "package_name": package,
                "sha256_cert_fingerprints": prints,
            },
        }
    ]


def statements(conn: sqlite3.Connection, settings: Any) -> list[dict]:
    return statements_for(site_store.resolved_manifest(conn, settings).get("android"))


def check_url(origin: str) -> str:
    """Google's asset-links check for `origin`, or "" when this site does not
    know its own URL yet (`dashboard_url` blank -- M6's job, and until it is
    done there is nothing honest to print)."""
    origin = str(origin or "").strip().rstrip("/")
    if not origin.startswith(("http://", "https://")):
        return ""
    return CHECK_API + "?" + urlencode(
        {"source.web.site": origin, "relation": RELATION}
    )


@router.get(ASSETLINKS_PATH)
def assetlinks(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """The statement Chrome reads before it decides whether to draw a URL bar.

    `application/json` rather than the more specific asset-links media type:
    that is what Google's own documentation and every working deployment
    serve, and Chrome's verifier checks the bytes, not the label.
    """
    return JSONResponse(
        statements(conn, request.app.state.settings),
        media_type="application/json",
        headers={"Cache-Control": f"max-age={CACHE_SECONDS}"},
    )


# ------------------------------------------------------------- the settings

def _context(
    request: Request,
    conn: sqlite3.Connection,
    *,
    notice: str | None = None,
    error: str | None = None,
    check: dict | None = None,
) -> dict:
    """The partial's context. `manifest` is spelled exactly as
    `ui.page_admin_settings` spells it, because the panel is rendered BOTH by
    that page (through the `{% include %}`) and by the two routes below --
    one template, one set of names, no second copy of the field values."""
    manifest = site_store.resolved_manifest(conn, request.app.state.settings)
    return {
        "manifest": manifest,
        "android_notice": notice,
        "android_error": error,
        "android_check": check,
    }


def _render(request: Request, context: dict):
    from . import ui                      # local: ui imports half the package

    return ui._render(request, "partials/android_settings.html", context)


@router.post("/api/v1/setup/android")
def api_setup_android(
    request: Request,
    package_name: str = Form(""),
    sha256_cert_fingerprints: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """[ SAVE ]. Admin only, and admin only -- unlike its `/api/v1/setup/*`
    neighbours there is no anonymous first-run window here: nobody configures
    an Android app before there is an admin account, and app.py's middleware
    treats the whole prefix as open, so this gate is the only one.

    A plain form, not JSON: `static/site_settings.js` belongs to the rest of
    that page (M3) and this panel must not need it. Answers with the panel
    re-rendered, which is what htmx swaps back in.
    """
    from . import setup_routes

    admin = setup_routes._require_admin(request)
    values = {
        "android.package_name": package_name,
        "android.sha256_cert_fingerprints": sha256_cert_fingerprints,
    }
    try:
        site_store.set_many(conn, values, updated_by=admin)
    except site_store.SiteValidationError as exc:
        # The panel re-renders with the message and the admin's own text is
        # still in the boxes (the manifest is unchanged, so the fields show
        # the last SAVED value -- a validation refusal writes nothing at all,
        # per set_many's validate-everything-first rule).
        return _render(request, _context(request, conn, error=str(exc)))
    # Keys only, never values, like every other site write (SYS-11).
    db.audit(conn, admin, "site.android_save", "site", {"keys": sorted(values)})
    conn.commit()
    site_store.invalidate(request.app)          # see setup_routes.api_admin_site_put
    log.info("admin %r updated the Android app settings", admin)
    count = len(statements(conn, request.app.state.settings))
    notice = (
        "Saved. This site now serves an asset-links statement."
        if count
        else "Saved. Both a package name and at least one fingerprint are "
             "needed before this site serves a statement."
    )
    return _render(request, _context(request, conn, notice=notice))


@router.post("/api/v1/setup/android/check")
def api_setup_android_check(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    """[ CHECK ]. What this site is serving at `/.well-known/assetlinks.json`
    right now, read the same way the route builds it (see the module
    docstring for why this is not a self-request), plus the URL an admin can
    paste into a browser to ask Google what IT sees."""
    from . import setup_routes

    setup_routes._require_admin(request)
    settings = request.app.state.settings
    manifest = site_store.resolved_manifest(conn, settings)
    docs = statements(conn, settings)
    target = (docs[0]["target"] if docs else {})
    check = {
        "path": ASSETLINKS_PATH,
        "count": len(docs),
        "package_name": target.get("package_name", ""),
        "fingerprints": list(target.get("sha256_cert_fingerprints", ())),
        "relation": RELATION,
        "dashboard_url": manifest.get("dashboard_url", ""),
        "google_url": check_url(manifest.get("dashboard_url", "")),
    }
    return _render(request, _context(request, conn, check=check))
