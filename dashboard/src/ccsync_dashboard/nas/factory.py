"""One place that knows which NAS this site runs on (DASH_NAS_KIND).

api.py and ui.py go through make_nas_client(); neither imports a concrete
backend. Keep it that way -- the "which NAS?" question belongs to exactly one
function so a third backend is a new file plus one line here
(SYNOLOGY_PORT_PLAN.md WP1, 2026-08-17).
"""
from __future__ import annotations

from .base import NasBackend, NasError
from .synology import SynologyClient
from .truenas import TrueNASClient

NAS_KINDS = ("truenas", "synology")


def nas_configured(settings) -> bool:
    """Whether the admin/provisioning half has credentials to work with.

    This is the gate that keeps a NAS-less deployment serving everything else
    (the fleet's sync status outranks the admin Users section, which simply
    503s). The password has always been the switch; the host now matters too
    because it no longer has a hardcoded default to fall back on
    (SYNOLOGY_PORT_PLAN.md WP0 step 1) -- and a blank host would otherwise
    produce https:///api/v2.0 and a confusing connection error instead of an
    honest "not configured".

    nas_base_url is the tests' escape hatch (it replaces host entirely), so a
    settings object carrying one counts as configured.
    """
    if not (getattr(settings, "nas_pw", "") or "").strip():
        return False
    return bool((getattr(settings, "nas_host", "") or "").strip()
                or (getattr(settings, "nas_base_url", "") or "").strip())


def make_nas_client(settings) -> NasBackend:
    """Build the backend named by settings.nas_kind.

    Raises NasError for an unknown kind: a typo'd DASH_NAS_KIND must not
    silently fall back to TrueNAS and provision accounts on a NAS the operator
    did not mean -- callers already turn NasError into a banner or a 502.
    """
    kind = (getattr(settings, "nas_kind", "") or "truenas").strip().lower()
    if kind == "truenas":
        return TrueNASClient(
            settings.nas_host, settings.nas_user, settings.nas_pw,
            base_url=settings.nas_base_url or None,
            verify_ssl=settings.nas_verify_ssl,
            homes_parent=getattr(settings, "nas_homes_parent", "") or "",
        )
    if kind == "synology":
        client = SynologyClient(
            settings.nas_host, settings.nas_user, settings.nas_pw,
            settings.nas_verify_ssl,
        )
        if settings.nas_base_url:
            client.base_url = settings.nas_base_url
        return client
    raise NasError(
        f"unknown DASH_NAS_KIND {kind!r} -- allowed values: {', '.join(NAS_KINDS)}"
    )
