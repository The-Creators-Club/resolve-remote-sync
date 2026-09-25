"""Change your own password, from the account page.

Account page 2026-09-25 (docs/ACCOUNT_PAGE_FEATURES.md 3.3, feature F2).
Until this module a password could be changed only by an admin, from
Settings > Users (`api.api_admin_set_password`). This is the self-service
half, and the whole of its logic: the JSON route (`account_api`, group C)
and, through that group's service, the page's htmx partial both call these
two functions and only map the result to HTTP and handle the cookie, so
nothing here is implemented twice.

Why it is shaped the way it is:

- **Every refusal is decided before anything changes**, and every sentence
  ends with "Nothing changed." where that is true, because a person who
  mistyped needs to know whether their old password still works.
- **Wrong "current password" tries share the sign-in throttle** (owner
  decision D-3): a stolen browser session is exactly the attacker this form
  must not hand five free guesses an hour on top of the sign-in page's.
- **The current password is checked by the same verifier `/api/v1/login`
  uses** (`app.state.credential_verifier`, else `auth.verify_credentials`):
  the SMB probe on smb, scrypt on local. Anything else would be a second
  definition of "your password" that could drift from the first.
- **smb changes the NAS password**, through the same backend call and the
  same editors-only refusals the admin reset uses (`set_known_password`), and
  asks `is_editor` first so an account the dashboard may not touch gets a
  sentence, never a NAS round trip that fails half way.
- **After the change every other browser is signed out and this one gets a
  fresh cookie** (owner decisions D-1, D-2). A report token or companion
  identity is NOT touched: those authenticate a machine, and a password
  change says nothing about the editor's computers (the same reasoning as
  `api.revoke_sessions_after_password_reset`).
- **No password, typed, old or new, nor its length, is ever logged,
  audited or returned.** A NAS error's own text is logged (at warning, with
  anything that looks like either password masked) but never shown: it is
  backend detail, not an editor's sentence.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from fastapi import Request, Response

from . import auth, db, local_users
from .nas.base import NasError
from .nas.factory import make_nas_client, nas_configured

log = logging.getLogger("ccsync.dashboard.account_password")

# The audit action (group A defines it in db.py as AUDIT_ACCOUNT_PASSWORD).
# Read through getattr so this module works on a tree where group A's
# constants have not merged yet; the value is the one the spec pins.
AUDIT_ACTION = getattr(db, "AUDIT_ACCOUNT_PASSWORD", "account.password_change")

# Every sentence exactly as docs/ACCOUNT_PAGE_FEATURES.md 3.3 writes it. No em
# dash in any of them: they are shown to the person who typed the password.
MSG_OIDC = ("You sign in with your organisation's account, so there is no password here "
            "to change. Change it where your organisation looks after its accounts.")
MSG_MISMATCH = "The two new passwords are not the same. Nothing changed."
MSG_TOO_SHORT = ("The new password needs at least {n} characters. Nothing changed.")
MSG_SAME = "The new password is the same as the current one. Nothing changed."
MSG_BUSY = ("The server is busy checking other sign-ins. Try again in a minute. "
            "Nothing changed.")
MSG_WRONG_CURRENT = ("That is not your current password, so nothing changed. Several wrong "
                     "tries in a row make this form wait, like the sign-in page.")
MSG_NOT_LOCAL = ("{user} is not an account this dashboard keeps a password for. Ask another "
                 "admin, or change it where that account lives.")
MSG_NO_NAS = ("This dashboard holds no server credential, so it cannot change server "
              "passwords. Ask your admin.")
MSG_NAS_UNREACHABLE = "Could not reach the server, so nothing changed. Try again in a minute."
MSG_NOT_EDITOR = ("The server does not let this dashboard change the password of {user}. "
                  "Change it in the NAS's own settings, or ask your admin.")
MSG_NAS_REFUSED = ("The server refused the change, so nothing changed. Try again, or ask "
                   "your admin.")
MSG_UNKNOWN_METHOD = ("This dashboard does not know how to change passwords for its sign-in "
                      "method. Ask your admin. Nothing changed.")


@dataclass
class PasswordChangeResult:
    ok: bool
    status: int            # the HTTP code the route answers
    detail: str            # the sentence (for ok: "")
    method: str
    other_sessions_signed_out: int | None = None
    retry_after: float = 0.0


def _refuse(status: int, detail: str, method: str, retry_after: float = 0.0
            ) -> PasswordChangeResult:
    return PasswordChangeResult(ok=False, status=status, detail=detail, method=method,
                                retry_after=retry_after)


def _masked(text: str, *secrets_: str) -> str:
    """`text` with every non-trivial secret replaced. A NAS error body has
    been seen to echo the request it refused; the log is read by people who
    must never learn a password from it."""
    out = str(text or "")
    for secret in secrets_:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "***")
    return out


def _other_live_sessions(request: Request, user: str) -> int | None:
    """How many live sessions of `user` there are besides this browser's.
    None when sessions are not recorded or the store cannot be read (the
    count is a courtesy, never a reason to fail)."""
    store = auth.session_store(request)
    if store is None:
        return None
    try:
        current = auth.get_session_id(request)
        rows = store.list_for_user(user)
    except Exception:  # noqa: BLE001 - a count must never fail the change
        log.exception("password change for %r: could not count their sessions", user)
        return None
    return sum(1 for r in rows if r.get("sid") != current)


def change_own_password(request: Request, conn: sqlite3.Connection, user: str,
                        current_password: str, new_password: str,
                        new_password_again: str) -> PasswordChangeResult:
    """Steps 2-8 of docs/ACCOUNT_PAGE_FEATURES.md 3.3 and the audit of step 10.

    The caller has already established `user` is the signed-in person (step
    1) and, on `ok`, calls `rotate_after_password_change`. On `ok` this has
    COMMITTED `conn` (the password and the audit row; see the note at the
    commit), so the route's commit after the rotation has nothing left to do.
    On a refusal nothing was written.
    Plain `def` on purpose: the SMB probe, the scrypt hash and the NAS call
    all block, so the route that calls this runs in the threadpool.

    The audit's `other_sessions_signed_out` is counted here, just before the
    rotation revokes them; the rotation returns the count it actually
    revoked, which is what the route answers."""
    settings = request.app.state.settings
    user = (user or "").strip().lower()
    method = str(getattr(settings, "auth_method", "") or "smb").strip().lower()
    current_password = current_password or ""
    new_password = new_password or ""
    new_password_again = new_password_again or ""

    # 2. Single sign-on keeps no password here to change.
    if method == "oidc":
        return _refuse(409, MSG_OIDC, method)
    if method not in ("smb", "local"):
        return _refuse(409, MSG_UNKNOWN_METHOD, method)
    # 3-5. The form's own mistakes: nothing is asked of anyone yet, so none
    # of these spends a throttle budget.
    if new_password != new_password_again:
        return _refuse(422, MSG_MISMATCH, method)
    if auth.check_password(new_password):
        return _refuse(422, MSG_TOO_SHORT.format(n=auth.MIN_PASSWORD_CHARS), method)
    if new_password == current_password:
        return _refuse(422, MSG_SAME, method)

    # 6. The sign-in page's own budgets (D-3).
    wait = auth.login_throttled(request, user)
    if wait:
        return _refuse(429, auth.throttle_message(wait), method, retry_after=float(wait))

    # A DASH_ADMIN_USERS break-glass name with no local row has no password
    # this dashboard keeps. Account page 2026-09-25: asked BEFORE verifying
    # (the spec's step 8 answer, one step early): the local verifier answers
    # False for a missing row, so asking after would record a sign-in failure
    # against a person who typed their password correctly and then tell them
    # it was wrong. The row lookup is the person's own account; it reveals
    # nothing they cannot already see.
    if method == "local" and local_users.get_user(conn, user) is None:
        return _refuse(409, MSG_NOT_LOCAL.format(user=user), method)

    # 7. The current password, exactly as /api/v1/login checks it.
    verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)
    try:
        verified = verifier(settings, user, current_password)
    except auth.CredentialProbeBusy:
        return _refuse(503, MSG_BUSY, method)
    if not verified:
        auth.record_login_failure(request, user)
        return _refuse(422, MSG_WRONG_CURRENT, method)
    auth.clear_login_failures(request, user)

    # 8. Set it.
    if method == "local":
        try:
            local_users.set_password(conn, user, new_password)
        except local_users.LocalUserError:
            # The row vanished between the check above and here (an admin
            # deleted the account mid-request). The floor was checked above,
            # so a missing row is the only way in.
            return _refuse(409, MSG_NOT_LOCAL.format(user=user), method)
    else:
        if not nas_configured(settings):
            return _refuse(503, MSG_NO_NAS, method)
        try:
            nas = make_nas_client(settings)
            is_editor = nas.is_editor(user)
        except NasError as exc:
            log.warning("password change for %r: could not ask the NAS whether it is an "
                        "editor: %s", user,
                        _masked(str(exc), current_password, new_password))
            return _refuse(502, MSG_NAS_UNREACHABLE, method)
        except Exception as exc:  # noqa: BLE001
            # Account page 2026-09-25 review round: a misconfigured NAS setup
            # can raise something other than NasError from make_nas_client;
            # an unhandled 500 would carry backend detail the spec says is
            # never returned. Log it masked, answer the same 502 sentence.
            log.warning("password change for %r: the NAS client could not be set up: "
                        "%s: %s", user, type(exc).__name__,
                        _masked(str(exc), current_password, new_password))
            return _refuse(502, MSG_NAS_UNREACHABLE, method)
        if not is_editor:
            return _refuse(409, MSG_NOT_EDITOR.format(user=user), method)
        try:
            nas.set_known_password(user, new_password)
        except NasError as exc:
            log.warning("password change for %r: the NAS refused it: %s", user,
                        _masked(str(exc), current_password, new_password))
            return _refuse(502, MSG_NAS_REFUSED, method)

    # 10 (the audit half). No password and no length in the detail.
    others = _other_live_sessions(request, user)
    db.audit(conn, user, AUDIT_ACTION, user,
             {"method": method, "other_sessions_signed_out": others})
    # Account page 2026-09-25: COMMITTED HERE, although the spec leaves the
    # commit to the route after the rotation. Measured: the audit INSERT (and
    # on local the hash UPDATE) holds the SQLite write lock on `conn`, and the
    # rotation writes through the session store's OWN connection, so rotating
    # before this commit waited out the 20 s busy timeout and failed, leaving
    # the other browsers signed in (api.revoke_sessions_after_password_reset
    # says "call AFTER the commit" for the same reason). The password has
    # changed by now (on smb, irreversibly on the NAS), so its record must land
    # whatever the rotation does. The route's own commit afterwards is a no-op.
    conn.commit()
    log.warning("%r changed their own password (%s) and signed out %s other session(s)",
                user, method, "an unknown number of" if others is None else others)
    return PasswordChangeResult(ok=True, status=200, detail="", method=method,
                                other_sessions_signed_out=others)


def rotate_after_password_change(request: Request, response: Response,
                                 user: str) -> int | None:
    """Step 9: sign out every other browser of `user` and give this one a
    fresh cookie. Returns how many OTHER sessions were revoked, or None when
    that is not known (sessions not recorded, or the revocation failed).

    Never raises: the password HAS changed by the time this runs.

    Account page 2026-09-25: the new session is minted FIRST and everything
    else revoked after it (`except_sid` = the new one), rather than "revoke
    all, then mint" as the spec words it. The end state is the same (every
    session that existed before the change is revoked; exactly one new one
    lives), but each failure lands safe: if minting fails, every OTHER session is
    still revoked (except_sid = the old one) and nothing else has been
    revoked yet and this browser keeps its old session; if revoking fails,
    this browser is still signed in with the new cookie. The other order
    signs the person out of the page they just changed their password on
    whenever the mint fails."""
    user = (user or "").strip().lower()
    store = auth.session_store(request)
    old_sid = None
    try:
        old_sid = auth.get_session_id(request)
    except Exception:  # noqa: BLE001
        old_sid = None
    try:
        new_sid = auth.start_session(request, response, user)
    except Exception:  # noqa: BLE001 - the password has already changed
        # Account page 2026-09-25 (review round): a failed mint must NOT leave
        # the other browsers signed in. D-1 says the others are ALWAYS signed
        # out, and a password is usually changed because someone else may know
        # it, so a stolen cookie surviving the change is the one outcome to
        # rule out. The others go; this browser keeps its OLD session.
        log.exception("password change for %r: could not start a fresh session; "
                      "signing the other sessions out and keeping this one", user)
        if store is None:
            return None
        try:
            revoked = store.revoke_user(user, by=f"self:{user} (password change)",
                                        except_sid=old_sid)
        except Exception:  # noqa: BLE001
            log.exception("password change for %r: could not sign out their other "
                          "sessions either", user)
            return None
        return max(0, int(revoked))
    if store is None:
        # No server-side sessions: nothing to revoke, and a cookie-only
        # deployment cannot tell how many other browsers hold one.
        return None
    try:
        old_live = old_sid is not None and any(
            r.get("sid") == old_sid for r in store.list_for_user(user))
        revoked = store.revoke_user(user, by=f"self:{user} (password change)",
                                    except_sid=new_sid)
    except Exception:  # noqa: BLE001
        log.exception("password change for %r: could not sign out their other sessions",
                      user)
        return None
    return max(0, int(revoked) - (1 if old_live else 0))
