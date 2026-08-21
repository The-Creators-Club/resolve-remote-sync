"""Who is calling the music ingest FLEET routes: a machine, and which one.

docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18. The rules are b-roll's
`app/fleet_auth.py`, which are ytdl's, applied to the same problem a third
time -- two credentials, two different jobs, and the whole design turns on
their being different:

  - **`X-CCSync-Token` = a fleet credential.** These calls happen
    with no browser open: the SPA hands the companion a batch uid and walks
    away, and the companion then embeds tracks for however long the drop
    takes. There is no session to gate on. FAIL-CLOSED -- a deployment with no
    DASH_REPORT_TOKEN answers 403 to every one of these rather than running
    open, because what is behind them is `INSERT INTO tracks` and a re-score
    of the whole library. Standalone that shared secret is the ONLY thing it
    can be; mounted, it may equally be the per-editor `cce1.` token the
    companion prefers, which the dashboard's gate resolves for us and reports
    in `X-CCSync-Fleet-Auth` (music-1, 2026-08-21, below).

  - **AND THE TOKEN IS NOT AN IDENTITY.** Every companion in the fleet holds
    the same one, so it proves "a fleet machine" and nothing about WHICH
    editor. The name therefore arrives as the dashboard's signed identity
    token in `X-CCSync-Identity` and is VERIFIED here (identity.py, vendored
    from ytdl/web) before it is believed. Without that, any machine with the
    shared token could claim another editor's batch, fail its tracks, or take
    it away from the machine already crunching it -- the hole H5 closed in
    ytdl (COMMERCIAL_READINESS.md item 7, 2026-08-17).

Both refusals are 403 and both are logged, because both mean the SERVER is
misconfigured or the caller is not who it says -- neither is retryable and
neither is the "your claim is over" answer, which is 410 and lives in
routes_fleet.

Deliberately NOT shared with broll/web's copy of this file, for the reason in
identity.py's header: musicweb may not import the tree deployed as `app`.
It is ~40 lines of policy either way, and the two headers say so.
"""
import hmac
import logging
import re

from fastapi import Header, HTTPException

from musicweb import config, identity

log = logging.getLogger(__name__)

# What the dashboard mount says about `X-CCSync-Token` when it has resolved it
# for us (music-1, 2026-08-21). `shared` = the fleet-wide DASH_REPORT_TOKEN;
# `editor:<name>` = a per-editor `cce1.<id>.<secret>` token, which the
# companion PREFERS since 2026-08-17 and which THIS app cannot verify: doing so
# means reading the dashboard's own database, and the music tree is deployed on
# its own and cannot see it. Without this every editor an admin migrated had
# their music ingest silently switched off -- login_gate let their companion
# through and `require_fleet_token` then answered 403 to every claim.
#
# The stamp is believed ONLY when config.login_gated() is true, because that
# flag is set by a CALL from the mount (config.set_login_gated) and the mount
# is what strips every inbound copy of the header. Standalone the flag is off
# and this is inert, so a header on the wire proves nothing there.
FLEET_AUTH_HEADER = 'X-CCSync-Fleet-Auth'
_STAMP_RE = re.compile(r'^(shared|editor:[^\s]{1,64})$')


def stamp_ok(presented):
    """True if `presented` is a fleet-auth stamp this app may act on.

    Shape only, and deliberately narrow: the value is never parsed into an
    identity here. WHO the caller is still comes from the signed
    `X-CCSync-Identity` (require_identity) exactly as before -- two sources for
    one fact is how the wrong one ends up winning.
    """
    if not config.login_gated():
        return False
    return bool(_STAMP_RE.match(str(presented or '').strip()))


def token_ok(configured, presented):
    """Constant-time shared-secret comparison. Empty configured = never ok.

    Carries the same two lessons every other copy does: `==` on a secret leaks
    its length and matching prefix through timing, and hmac.compare_digest
    raises TypeError on a str with any character above U+007F, so one junk
    non-ASCII byte in a header turned a 401 into a 500 and a traceback (DASH-5,
    2026-08-11).
    """
    if not configured or not presented:
        return False
    try:
        return hmac.compare_digest(
            str(configured).encode('utf-8', 'surrogateescape'),
            str(presented).encode('utf-8', 'surrogateescape'),
        )
    except (TypeError, ValueError, UnicodeError):
        return False


def require_fleet_token(x_ccsync_token: str = Header(default=None),
                        x_ccsync_fleet_auth: str = Header(default=None)) -> None:
    """FAIL CLOSED. An unconfigured token means 403, never "open in dev".

    Stricter than `/api/ingest`, which lets a login-gated mount stand on the
    session: nothing gates these, because no browser is involved. A deployment
    that has lost its DASH_REPORT_TOKEN loses dashboard music ingest entirely
    and nothing else -- search, streaming, the queue drain and the base-rig
    indexer are all untouched.

    TWO credentials satisfy it, and the second one is why (music-1,
    2026-08-21): a companion may present a per-editor `cce1.` token instead of
    the shared one, which only the dashboard can verify. Mounted, its gate has
    already done so and said which; standalone, the stamp is ignored and the
    shared comparison below is the whole story. The shared comparison runs
    either way, so an older dashboard that stamps nothing still works.
    """
    if stamp_ok(x_ccsync_fleet_auth):
        return
    if not token_ok(config.fleet_token(), x_ccsync_token or ''):
        log.warning('music ingest fleet call refused: missing or invalid '
                    'X-CCSync-Token')
        raise HTTPException(403, 'missing or invalid X-CCSync-Token')


def require_identity(x_ccsync_identity: str = Header(default=None)) -> str:
    """The VERIFIED editor behind `X-CCSync-Identity`. 403 if there isn't one.

    The batch's `editor` column is compared against THIS, never against
    anything in the request body: two sources for one fact is how the wrong one
    ends up winning. No body model in routes_fleet carries an editor name for
    that reason.
    """
    secret = config.session_secret()
    if not secret:
        log.warning(
            'a music ingest fleet call arrived but DASH_SESSION_SECRET is not set '
            'on this server, so no companion identity can be verified -- '
            'refusing. Set it (the dashboard already requires it to log anyone '
            'in) and restart.')
        raise HTTPException(403, {
            'detail': 'this dashboard cannot verify companion identities',
            'reason': 'identity_unconfigured'})
    editor = identity.read_identity_token(secret, x_ccsync_identity)
    if not editor:
        raise HTTPException(403, {
            'detail': (f'a valid {identity.HEADER} is required: sign in again '
                       'from the companion tray'),
            'reason': 'identity'})
    return editor
