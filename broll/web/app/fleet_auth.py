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
    Standalone that shared secret is the ONLY thing it can be; mounted, it may
    equally be the per-editor `cce1.` token the companion prefers, which only
    the dashboard's gate can verify and which it reports in
    `X-CCSync-Fleet-Auth` (CR-55, 2026-08-21, below).

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


# ------------------------------------------------- the mounted gate's verdict
# TWO CREDENTIALS REACH THESE ROUTES, not one (CR-55, 2026-08-21). The shared
# DASH_REPORT_TOKEN above is the one every companion holds today; the other is
# a per-editor `cce1.<id>.<secret>` the dashboard mints on Admin > Users,
# stored HASHED and BOUND to one editor (CR-18). Only the dashboard can check
# the second -- the hash is in ITS database, which this separately deployed
# tree cannot see -- so when we are mounted its gate resolves the token for us
# and STAMPS the answer into this header. A companion PREFERS the per-editor
# token once its editor has one (identity.preferred_report_token, 2026-08-17),
# so without this every claim/heartbeat/result/uploaded from that editor was
# answered 403 here while sailing through the dashboard's own gate: their
# dropped clips sat in `queued` and the archive never saw them. Music and ytdl
# were fixed on 2026-08-21; b-roll was nobody's territory that day (CR-67 item
# 2) and this is the mirror of what they do.
#
# THE STAMP IS ONLY EVER BELIEVED WHEN THE MOUNT INSTALLED IT. BrollGate strips
# any inbound copy before appending its own, so a stamp that arrives while
# `trust_gate_stamp` has been called came from the gate. Standalone -- the dev
# server, this suite -- nothing calls it and the header decides nothing,
# because there would be no gate stripping a forged one.
STAMP_HEADER = "X-CCSync-Fleet-Auth"
STAMP_SHARED = "shared"
STAMP_EDITOR_PREFIX = "editor:"

_trust_stamp = False


def trust_gate_stamp(enabled: bool = True) -> bool:
    """Believe `X-CCSync-Fleet-Auth` from here on. -> the new setting.

    Called by ccsync_dashboard.broll.mount_broll. A module global rather than
    app state, for ytdl's two reasons: what reads it is a request handler with
    no app object in hand, and an older dashboard that does not call it must
    keep working (it simply goes on comparing the shared token, which is what
    it sends).
    """
    global _trust_stamp
    _trust_stamp = bool(enabled)
    return _trust_stamp


def gate_stamp(value: str | None) -> tuple[str | None, str | None]:
    """-> (kind, editor): ("editor", name), ("shared", None) or (None, None).

    Anything unparseable is (None, None) and falls through to the shared-token
    comparison, so a stamp this build does not understand is never an opening.
    """
    if not _trust_stamp:
        return None, None
    raw = str(value or "").strip()
    if raw == STAMP_SHARED:
        return STAMP_SHARED, None
    if raw.startswith(STAMP_EDITOR_PREFIX):
        editor = raw[len(STAMP_EDITOR_PREFIX):].strip()
        if editor:
            return "editor", editor
    return None, None


def require_fleet_token(x_ccsync_token: str | None = Header(default=None),
                        x_ccsync_fleet_auth: str | None = Header(default=None),
                        ) -> str | None:
    """FAIL CLOSED. An unconfigured token means 403, never "open in dev".

    -> the editor a per-editor token is BOUND to, or None for the shared one
    (which identifies nobody, which is why X-CCSync-Identity exists beside it).

    The b-roll INGEST routes (`/api/ingest/*`, the indexer's) allow an unset
    BROLL_INGEST_TOKEN to be a 503 rather than a bypass; these go further and
    refuse outright, because a deployment that has lost its DASH_REPORT_TOKEN
    should lose dashboard b-roll ingest entirely. Nothing else breaks: the
    archive keeps serving, search keeps working, and the base-rig indexer is
    untouched. That refusal is unchanged by CR-55: the stamp is only reachable
    when the dashboard's gate accepted a credential of its own.
    """
    kind, editor = gate_stamp(x_ccsync_fleet_auth)
    if kind == "editor":
        return editor
    if kind == STAMP_SHARED:
        return None
    if not token_ok(config.get_fleet_token(), x_ccsync_token or ""):
        log.warning("b-roll ingest fleet call refused: missing or invalid X-CCSync-Token")
        raise HTTPException(403, "missing or invalid X-CCSync-Token")
    return None


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


def require_fleet_caller(x_ccsync_token: str | None = Header(default=None),
                         x_ccsync_fleet_auth: str | None = Header(default=None),
                         x_ccsync_identity: str | None = Header(default=None),
                         ) -> str:
    """Both gates, in the order they fail closed. -> the VERIFIED editor.

    CR-55, 2026-08-21, the mirror of ytdl's require_fleet_caller. A per-editor
    token proves WHICH machine's editor is calling, and the signed identity
    header proves whose name the call acts under. When both are present they
    must agree: a cce1 token belonging to one editor may not carry another
    editor's identity, or the migration to bound tokens would be a WEAKER check
    than the shared-token-plus-identity one it replaced.

    One dependency rather than the two the routes used to declare, so the order
    cannot drift: the machine credential is still checked before the identity,
    and the mismatch can only be tested where both answers are in hand.
    """
    bound = require_fleet_token(x_ccsync_token, x_ccsync_fleet_auth)
    editor = require_identity(x_ccsync_identity)
    if bound is not None and bound != editor:
        log.warning("b-roll ingest fleet call refused: the report token is bound "
                    "to %r but the identity header says %r", bound, editor)
        raise HTTPException(403, {
            "detail": "this report token belongs to a different editor",
            "reason": "identity_mismatch"})
    return editor
