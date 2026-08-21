"""OIDC authorization-code login, behind the existing DASH_AUTH_METHOD seam.

COMMERCIAL_READINESS.md item 12, 2026-08-17: `DASH_AUTH_METHOD` was a seam
with exactly one implementation ("smb", an SMB session probe against the NAS),
which is fine for a fleet whose editors are NAS accounts and useless to a
customer who already runs Entra/Okta/Keycloak/Authentik. This is the second
implementation. It changes WHO says the password was right and nothing else:
the username that comes back is fed into the same `start_session` as the SMB
path, so selections, Syncthing device joins, admin rights and every other
username-keyed thing in the dashboard are untouched.

Which claim becomes that username is configurable (`DASH_OIDC_USERNAME_CLAIM`,
default `preferred_username`) and it MATTERS: every join in this app is a NAS
username (Syncthing device name = username, `selections.editor_username`, the
`editors` group). An IdP publishing an email address there produces an editor
the fleet cannot match to anything. The README says so; there is no way for
the code to check it.

Security shape, all mandatory, none configurable:
  * PKCE S256 on every request, even though this is a confidential client --
    it costs nothing and removes code interception entirely.
  * `state` and `nonce`, both random, both carried in an HMAC-signed,
    HttpOnly, 10-minute flow cookie rather than in server memory. A single
    worker with in-memory state loses every in-flight login on the restart
    that each deploy performs, and the container has no shared cache.
  * The id_token is verified as a signature (JWKS from discovery, RS256/ES256
    family only -- never `none`, never HS256 with the client secret), against
    `iss`, `aud`, `exp`, and the `nonce` we generated.
  * `/login?local=1` stays reachable as break-glass, but only for
    DASH_ADMIN_USERS while OIDC is the configured method (ui.py enforces it) --
    an IdP outage must not lock the operator out of their own dashboard, and
    it must not quietly reopen password login for the whole fleet either.

The HTTP calls go through `requests` (already a dependency) and the token
verification through PyJWT (added 2026-08-17). Both are imported lazily, so a
deployment that has not installed PyJWT reports one clear boot problem instead
of failing to import the dashboard.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from . import auth
from .settings import Settings

log = logging.getLogger("ccsync.dashboard.oidc")

router = APIRouter(prefix="/auth/oidc", tags=["auth"])

LOGIN_PATH = "/auth/oidc/login"
CALLBACK_PATH = "/auth/oidc/callback"
FLOW_COOKIE = "ccsync_oidc"
# Long enough for a real sign-in (including an MFA prompt), short enough that a
# flow cookie left on a shared machine is worthless.
FLOW_TTL_SECONDS = 600
DISCOVERY_TTL_SECONDS = 3600
HTTP_TIMEOUT = 10.0
# Asymmetric only. An IdP that offers HS256 would have the client secret double
# as the signing key, and a permissive verifier plus a leaked secret is a
# forged admin login.
ALLOWED_ALGS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256")


class OidcError(Exception):
    """Anything that means "this sign-in cannot be completed". The message is
    logged in full and shown to the operator in short form -- never the raw
    IdP body, which can carry the client secret back in an error echo."""


# ----------------------------------------------------------------- plumbing

def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def pack_flow(secret: str, data: dict[str, Any]) -> str:
    payload = _b64u(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_sign(secret, payload)}"


def unpack_flow(secret: str, cookie: str | None, now: float | None = None) -> dict[str, Any] | None:
    """The flow cookie, or None for missing/tampered/expired. Same defensive
    shape as auth._read_token: attacker-controlled input, so every failure is
    a None rather than an exception."""
    if not cookie or not secret:
        return None
    payload, _, signature = cookie.rpartition(".")
    if not payload or not signature:
        return None
    try:
        if not hmac.compare_digest(signature, _sign(secret, payload)):
            return None
    except TypeError:
        return None
    try:
        data = json.loads(_b64u_decode(payload))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if float(data.get("exp", 0)) < (time.time() if now is None else now):
        return None
    return data


def _http_get_json(url: str) -> dict[str, Any]:
    import requests

    response = requests.get(url, timeout=HTTP_TIMEOUT)
    if response.status_code != 200:
        raise OidcError(f"GET {url} answered {response.status_code}")
    return response.json()


def _http_post_form(url: str, data: dict[str, str],
                    basic: tuple[str, str] | None) -> dict[str, Any]:
    import requests

    response = requests.post(url, data=data, timeout=HTTP_TIMEOUT, auth=basic,
                             headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise OidcError(f"token endpoint answered {response.status_code}")
    return response.json()


# ---------------------------------------------------------------- discovery

class Discovery:
    """`.well-known/openid-configuration`, cached for an hour.

    Cached rather than fetched per login because it is a network round trip on
    the sign-in path and because an IdP that is briefly unreachable should not
    take an already-working login flow down with it. Never cached across a
    change of issuer: the key is the issuer itself."""

    def __init__(self) -> None:
        self._by_issuer: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, issuer: str, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        cached = self._by_issuer.get(issuer)
        if cached is not None and cached[0] > now:
            return cached[1]
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        document = _http_get_json(url)
        for required in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
            if not document.get(required):
                raise OidcError(f"{url} is missing {required}")
        if str(document["issuer"]).rstrip("/") != issuer.rstrip("/"):
            # An issuer that does not match what we asked for is the classic
            # mix-up attack: the document is served by one IdP and claims to
            # speak for another.
            raise OidcError(
                f"discovery issuer {document['issuer']!r} does not match "
                f"DASH_OIDC_ISSUER {issuer!r}")
        self._by_issuer[issuer] = (now + DISCOVERY_TTL_SECONDS, document)
        return document

    def clear(self) -> None:
        self._by_issuer.clear()


_discovery = Discovery()


def discovery_for(request: Request) -> Discovery:
    """Per-app so a test can install its own; falls back to the module cache."""
    return getattr(request.app.state, "oidc_discovery", None) or _discovery


# -------------------------------------------------------------- the two legs

def redirect_uri(settings: Settings, request: Request) -> str:
    if settings.oidc_redirect_url:
        return settings.oidc_redirect_url
    scheme = "https" if auth.request_is_https(settings, request) else request.url.scheme
    return f"{scheme}://{request.url.netloc}{CALLBACK_PATH}"


def _safe_next(raw: str) -> str:
    """Same rule as ui._safe_next: only same-site absolute paths survive.

    Duplicated rather than imported because ui.py imports THIS module (for the
    SSO button's URL), so importing back would be a cycle."""
    raw = str(raw or "").strip()
    if raw.startswith("/") and not (len(raw) > 1 and raw[1] in "/\\"):
        return raw
    return "/"


@router.get("/login")
async def oidc_login(request: Request):
    settings: Settings = request.app.state.settings
    problems = auth.check_oidc_settings(settings)
    if problems:
        raise HTTPException(status_code=503, detail=problems[0])

    verifier = _b64u(secrets.token_bytes(32))
    challenge = _b64u(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _b64u(secrets.token_bytes(16))
    nonce = _b64u(secrets.token_bytes(16))
    next_path = _safe_next(request.query_params.get("next", ""))

    try:
        document = await run_in_threadpool(discovery_for(request).get, settings.oidc_issuer)
    except Exception as exc:                                   # noqa: BLE001
        log.error("OIDC discovery failed for %s: %s", settings.oidc_issuer, exc)
        raise HTTPException(
            status_code=503,
            detail="the identity provider is unreachable -- an admin can sign in at "
                   "/login?local=1",
        ) from exc

    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri(settings, request),
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    response = RedirectResponse(
        f"{document['authorization_endpoint']}?{urlencode(params)}", status_code=303)
    response.set_cookie(
        FLOW_COOKIE,
        pack_flow(settings.session_secret, {
            "state": state, "nonce": nonce, "verifier": verifier,
            "next": next_path, "exp": time.time() + FLOW_TTL_SECONDS,
        }),
        max_age=FLOW_TTL_SECONDS, httponly=True, samesite="lax",
        secure=auth.cookie_secure(settings, request), path="/",
    )
    return response


def username_from_claims(settings: Settings, claims: dict[str, Any]) -> str:
    raw = claims.get(settings.oidc_username_claim)
    username = str(raw or "").strip().lower()
    if not username:
        raise OidcError(
            f"the id_token has no {settings.oidc_username_claim!r} claim; set "
            f"DASH_OIDC_USERNAME_CLAIM to whichever claim carries the NAS username")
    # An '@' means the IdP is publishing an email where a username was asked
    # for. Refused rather than silently truncated: guessing that the local part
    # is the NAS account is how an editor ends up matched to somebody else's.
    if "@" in username or "/" in username or "\\" in username:
        raise OidcError(
            f"claim {settings.oidc_username_claim!r} is {username!r}, which is not a NAS "
            f"username; point DASH_OIDC_USERNAME_CLAIM at the login-name claim")
    return username


def in_allowed_group(settings: Settings, claims: dict[str, Any]) -> bool:
    """Does this id_token carry one of DASH_OIDC_ALLOWED_GROUPS?

    False when no allow-list is configured: an empty list is "not configured",
    never "everybody" (trust-model-5, 2026-08-21)."""
    if not settings.oidc_allowed_groups or not settings.oidc_groups_claim:
        return False
    value = claims.get(settings.oidc_groups_claim)
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return any(str(v).strip().lower() in settings.oidc_allowed_groups for v in values if v)


def require_fleet_member(settings: Settings, username: str, claims: dict[str, Any]) -> None:
    """Refuse an IdP account that is not part of THIS fleet (trust-model-5,
    2026-08-21).

    The password path has done this since 2026-08-17 (api._require_fleet_member,
    the `editors` group on the NAS); OIDC did not, and it maps the username
    claim straight onto an editor identity -- so every account in a customer's
    directory could sign in, and one whose preferred_username equals an
    existing editor's name inherited that editor's selections, ticks, device
    approvals and client-folder panel.

    Four ways to be a member, any one is enough: DASH_ADMIN_USERS, the admin
    claim mapping, DASH_OIDC_ALLOWED_GROUPS, or a username the dashboard has
    a positive record of (db.known_editor_usernames -- ticked, reported,
    known_editors, or a local account).

    Degrades the way api._require_fleet_member does: a fleet the dashboard
    knows NOTHING about yet (a first boot, or a database it cannot open) has
    nothing to check against, so the check is skipped and logged rather than
    locking the operator out of their own dashboard on day one."""
    if auth.is_admin(settings, username) or is_admin_by_claims(settings, claims):
        return
    if in_allowed_group(settings, claims):
        return
    if settings.oidc_allowed_groups:
        log.warning("OIDC: %r carries no %r value from DASH_OIDC_ALLOWED_GROUPS",
                    username, settings.oidc_groups_claim)
        raise HTTPException(
            status_code=403,
            detail="this account is not a member of the group allowed to use this "
                   "dashboard - ask your admin",
        )
    known = _known_usernames(settings)
    if known is None or not known:
        log.warning(
            "OIDC: letting %r in without a fleet-membership check -- this dashboard has "
            "no editors on record yet. Set DASH_OIDC_ALLOWED_GROUPS to have the IdP "
            "decide instead.", username)
        return
    if username not in known:
        log.warning("OIDC: refusing %r -- not an editor this fleet knows", username)
        raise HTTPException(
            status_code=403,
            detail="this account is not part of this fleet - ask your admin to add it",
        )


def _known_usernames(settings: Settings) -> set[str] | None:
    """Every username this dashboard has a positive record of, or None when
    the database cannot be opened at all. Its own short-lived connection: the
    OIDC callback runs before any route has opened one, exactly as
    auth._open_local_conn does for the local-accounts checks."""
    from . import db

    try:
        conn = db.connect(settings.db_path)
    except Exception:  # noqa: BLE001
        log.exception("OIDC: could not open %s to check fleet membership", settings.db_path)
        return None
    try:
        return {u.strip().lower() for u in db.known_editor_usernames(conn)}
    except Exception:  # noqa: BLE001
        log.exception("OIDC: fleet-membership lookup failed")
        return None
    finally:
        conn.close()


def is_admin_by_claims(settings: Settings, claims: dict[str, Any]) -> bool:
    """DASH_ADMIN_USERS always wins; the claim mapping is additive. That way
    losing the IdP's group mapping never silently demotes the operator."""
    if not settings.oidc_admin_claim or not settings.oidc_admin_values:
        return False
    value = claims.get(settings.oidc_admin_claim)
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return any(str(v).strip().lower() in settings.oidc_admin_values for v in values if v)


def verify_id_token(settings: Settings, document: dict[str, Any], id_token: str,
                    nonce: str) -> dict[str, Any]:
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:                                 # pragma: no cover
        raise OidcError(
            "PyJWT is not installed in this container; add it to "
            "dashboard/deploy/requirements.txt and redeploy") from exc

    signing_key = PyJWKClient(document["jwks_uri"]).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token, signing_key.key, algorithms=list(ALLOWED_ALGS),
        audience=settings.oidc_client_id, issuer=document["issuer"],
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    presented = str(claims.get("nonce") or "")
    if not hmac.compare_digest(presented, nonce):
        raise OidcError("id_token nonce does not match the one this login started with")
    return claims


def _exchange(settings: Settings, document: dict[str, Any], code: str,
              verifier: str, redirect: str) -> dict[str, Any]:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "code_verifier": verifier,
        "client_id": settings.oidc_client_id,
    }
    basic = None
    if settings.oidc_client_secret:
        methods = document.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        if "client_secret_basic" in methods:
            basic = (settings.oidc_client_id, settings.oidc_client_secret)
        else:
            form["client_secret"] = settings.oidc_client_secret
    payload = _http_post_form(document["token_endpoint"], form, basic)
    if not payload.get("id_token"):
        raise OidcError("the token response carried no id_token")
    return payload


@router.get("/callback")
async def oidc_callback(request: Request):
    settings: Settings = request.app.state.settings
    problems = auth.check_oidc_settings(settings)
    if problems:
        raise HTTPException(status_code=503, detail=problems[0])

    flow = unpack_flow(settings.session_secret, request.cookies.get(FLOW_COOKIE))
    if flow is None:
        # Expired, tampered, or a callback that no login of ours started.
        raise HTTPException(status_code=400,
                            detail="this sign-in expired or did not start here -- try again")
    presented_state = request.query_params.get("state", "")
    if not hmac.compare_digest(str(flow.get("state") or ""), presented_state):
        log.warning("OIDC callback with a mismatched state from %s", auth.client_ip(request))
        raise HTTPException(status_code=400, detail="bad sign-in state -- try again")
    if request.query_params.get("error"):
        # The IdP refused (consent declined, account disabled). Its own
        # description is not echoed into the page.
        log.warning("OIDC callback error=%s", request.query_params.get("error"))
        raise HTTPException(status_code=403, detail="the identity provider refused this sign-in")
    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="no authorization code in the callback")

    def work() -> dict[str, Any]:
        document = discovery_for(request).get(settings.oidc_issuer)
        payload = _exchange(settings, document, code, str(flow["verifier"]),
                            redirect_uri(settings, request))
        return verify_id_token(settings, document, payload["id_token"], str(flow["nonce"]))

    try:
        claims = await run_in_threadpool(work)
        username = username_from_claims(settings, claims)
    except OidcError as exc:
        log.error("OIDC sign-in failed: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:                                   # noqa: BLE001
        log.error("OIDC sign-in failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=403, detail="the identity provider's answer could not be verified"
        ) from exc

    # WHO the IdP says you are is settled; whether this fleet knows you is a
    # separate question, and one the password path has always asked
    # (trust-model-5, 2026-08-21). Raises 403 before any session exists.
    await run_in_threadpool(require_fleet_member, settings, username, claims)

    response = RedirectResponse(_safe_next(str(flow.get("next") or "/")), status_code=303)
    auth.start_session(request, response, username)
    if is_admin_by_claims(settings, claims):
        # Claim-granted admin is recorded on the session row's client summary
        # only; DASH_ADMIN_USERS remains the list every authorization check
        # reads (auth.is_admin), because a claim mapping that silently grants
        # fleet-wide rights is exactly the thing an operator must be able to
        # see in one place.
        log.info("OIDC: %r carries the admin claim %r", username, settings.oidc_admin_claim)
    response.delete_cookie(FLOW_COOKIE, path="/")
    log.info("OIDC sign-in for %r from %s", username, auth.client_ip(request))
    return response
