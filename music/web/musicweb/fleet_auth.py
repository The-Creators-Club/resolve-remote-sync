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


def gate_stamp(presented):
    """-> (kind, editor): ('editor', name), ('shared', None) or (None, None).

    Shape only: this never becomes WHO the caller is on its own. The name it
    yields is used for ONE thing, comparing it against the signed identity
    (require_fleet_caller, CR-55) -- two sources for one fact is how the wrong
    one ends up winning, so the identity stays the source and this is the
    check on it.

    Anything unparseable is (None, None) and falls through to the shared-token
    comparison, so a stamp this build does not understand is never an opening.
    """
    if not config.login_gated():
        return None, None
    raw = str(presented or '').strip()
    if not _STAMP_RE.match(raw):
        return None, None
    if raw == 'shared':
        return 'shared', None
    return 'editor', raw[len('editor:'):].strip()


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
                        x_ccsync_fleet_auth: str = Header(default=None)):
    """FAIL CLOSED. An unconfigured token means 403, never "open in dev".

    -> the editor a per-editor token is BOUND to, or None for the shared one
    (which identifies nobody, which is why X-CCSync-Identity exists beside it).

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
    kind, editor = gate_stamp(x_ccsync_fleet_auth)
    if kind == 'editor':
        return editor
    if kind == 'shared':
        return None
    if not token_ok(config.fleet_token(), x_ccsync_token or ''):
        log.warning('music ingest fleet call refused: missing or invalid '
                    'X-CCSync-Token')
        raise HTTPException(403, 'missing or invalid X-CCSync-Token')
    return None


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
            'detail': 'this dashboard cannot verify who is calling',
            'reason': 'identity_unconfigured'})
    editor = identity.read_identity_token(secret, x_ccsync_identity)
    if not editor:
        raise HTTPException(403, {
            'detail': (f'a valid {identity.HEADER} is required: sign in again '
                       'from the CC Sync tray'),
            'reason': 'identity'})
    return editor


def require_fleet_caller(x_ccsync_token: str = Header(default=None),
                         x_ccsync_fleet_auth: str = Header(default=None),
                         x_ccsync_identity: str = Header(default=None)) -> str:
    """Both gates, in the order they fail closed. -> the VERIFIED editor.

    CR-55, 2026-08-21, and the bug hunt of 2026-09-11 (comp-broll-music,
    out of territory): ytdl and b-roll bind the two credentials to each other
    and music never did. A per-editor `cce1.` token proves WHICH editor's
    machine is calling and the signed identity header proves whose name the
    call acts under; when both are present they must AGREE, or the migration
    to bound tokens is a weaker check than the shared-token-plus-identity one
    it replaced. The shared migration token is bound to nobody and keeps
    today's behaviour exactly: it identifies no editor, which is why the
    identity header exists beside it.

    One dependency rather than the two the routes used to declare, so the
    order cannot drift: the machine credential is still checked before the
    identity, and the mismatch can only be tested where both answers are in
    hand.
    """
    bound = require_fleet_token(x_ccsync_token, x_ccsync_fleet_auth)
    editor = require_identity(x_ccsync_identity)
    if bound is not None and bound != editor:
        log.warning('music ingest fleet call refused: the report token is bound '
                    'to %r but the identity header says %r', bound, editor)
        raise HTTPException(403, {
            'detail': 'this report token belongs to a different editor',
            'reason': 'identity_mismatch'})
    return editor
