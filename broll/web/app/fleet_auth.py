"""Who is calling the b-roll ingest FLEET routes: a machine, and which one.

Two credentials, two different jobs, and the whole design turns on their being
different (docs/BROLL_INGEST_PLAN.md §4.2, 2026-08-18 -- the rules are ytdl's
`routes_fleet.py:54-89,105-140`, applied to the same problem):

  - **`X-CCSync-Token` = the shared `DASH_REPORT_TOKEN`.** These calls happen
    with no browser open: the SPA hands the companion a batch uid and walks
    away, and the companion then crunches for hours. There is no session to
    gate on. FAIL-CLOSED -- a deployment with no DASH_REPORT_TOKEN answers 403
    to every one of these rather than running open, because what is behind them
    is `INSERT INTO videos` and "here is an archive path, upload to it".

  - **AND THE TOKEN IS NOT AN IDENTITY.** Every companion in the fleet holds
    the same one, so it proves "a fleet machine" and nothing about WHICH
    editor. The name therefore arrives as the dashboard's signed identity token
    in `X-CCSync-Identity` and is VERIFIED here (identity.py, vendored from
    ytdl/web) before it is believed. Without that, any machine with the shared
    token could claim another editor's batch, fail its clips, or take it away
    from the machine that was already crunching it -- which is exactly the hole
    H5 closed in ytdl (COMMERCIAL_READINESS.md item 7, 2026-08-17).

Both refusals are 403 and both are logged, because both mean the SERVER is
misconfigured or the caller is not who it says -- neither is retryable and
neither is the "your claim is over" answer, which is 410 and lives in
routes_fleet.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException

from app import config, identity

log = logging.getLogger("broll.fleet")


def token_ok(configured: str | None, presented: str | None) -> bool:
    """Constant-time shared-secret comparison. Empty configured = never ok.

    Copied from ytdlweb.routes_fleet.token_ok (itself copied from the
    dashboard's api.token_ok) rather than imported, for the reason identity.py
    is vendored: this app must run with neither package in reach. It carries
    the same two lessons -- `==` on a secret leaks its length and matching
    prefix through timing, and hmac.compare_digest raises TypeError on a str
    with any character above U+007F, so one junk non-ASCII byte in a header
    turned a 401 into a 500 and a traceback (DASH-5, 2026-08-11).
    """
    if not configured or not presented:
        return False
    try:
        return hmac.compare_digest(
            str(configured).encode("utf-8", "surrogateescape"),
            str(presented).encode("utf-8", "surrogateescape"),
        )
    except (TypeError, ValueError, UnicodeError):
        return False


def require_fleet_token(x_ccsync_token: str | None = Header(default=None)) -> None:
    """FAIL CLOSED. An unconfigured token means 403, never "open in dev".

    The b-roll INGEST routes (`/api/ingest/*`, the indexer's) allow an unset
    BROLL_INGEST_TOKEN to be a 503 rather than a bypass; these go further and
    refuse outright, because a deployment that has lost its DASH_REPORT_TOKEN
    should lose dashboard b-roll ingest entirely. Nothing else breaks: the
    archive keeps serving, search keeps working, and the base-rig indexer is
    untouched.
    """
    if not token_ok(config.get_fleet_token(), x_ccsync_token or ""):
        log.warning("b-roll ingest fleet call refused: missing or invalid X-CCSync-Token")
        raise HTTPException(403, "missing or invalid X-CCSync-Token")


def require_identity(x_ccsync_identity: str | None = Header(default=None)) -> str:
    """The VERIFIED editor behind `X-CCSync-Identity`. 403 if there isn't one.

    The batch's `editor` column is compared against THIS, never against
    anything in the request body: two sources for one fact is how the wrong one
    ends up winning. A body field naming an editor is not accepted anywhere in
    routes_fleet for that reason.

    Fails closed on an unconfigured secret, exactly as require_fleet_token does
    on an unconfigured token. The cost is that dashboard ingest stops while the
    archive and search carry on, which is the right way round.
    """
    secret = config.get_session_secret()
    if not secret:
        log.warning(
            "a b-roll ingest fleet call arrived but DASH_SESSION_SECRET is not set on "
            "this server, so no companion identity can be verified -- refusing. Set it "
            "(the dashboard already requires it to log anyone in) and restart.")
        raise HTTPException(403, {
            "detail": "this dashboard cannot verify companion identities",
            "reason": "identity_unconfigured"})
    editor = identity.read_identity_token(secret, x_ccsync_identity)
    if not editor:
        raise HTTPException(403, {
            "detail": (f"a valid {identity.HEADER} is required: sign in again "
                       "from the companion tray"),
            "reason": "identity"})
    return editor
