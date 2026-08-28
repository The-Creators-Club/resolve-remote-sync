"""The release trust anchor baked into the companion, and the record format
its signature covers.

COMMERCIAL_READINESS.md item 4, 2026-08-17. Before this, the upgrade channel
had no authentication at all: `upgrade.url` and the sha256 that "verified"
the download arrived in the SAME plain-HTTP report response, so anything able
to answer one report could hand an editor an arbitrary binary plus a matching
hash, which upgrade.py then renamed over the running companion and launched
detached. Origin pinning and the no-redirect opener (AUDIT_2 CORE-M10,
AUDIT_3 H-1) narrowed that to "whoever can answer as the dashboard" -- which
on a customer install includes the dashboard's own host. An offline signing
key removes the dashboard from the trust chain entirely: it stores and serves
a signature it cannot produce.

WHAT IS SIGNED: the whole package RECORD, not just the file hash. Signing
only the sha256 would leave the server free to re-label a genuine build as a
different version, platform or kind -- which is how you get a Mac handed a
Windows exe, or an onboard installer offered as a companion self-upgrade.

WHAT IS NOT SIGNED: `url`. It is server-relative and its host is pinned to
the configured dashboard by upgrade.same_origin(); binding it would break
every customer whose dashboard lives at a different address than ours.

ROTATION: RELEASE_PUBKEYS is a LIST, and every key in it is trusted. To
rotate, publish builds signed with the new key only after a build carrying
BOTH keys has reached the fleet -- i.e. append the new key, ship, then drop
the old one in a later release. `pubkey_id` on the record says which key
signed it and exists for logging and for that overlap window; it is never
what decides trust (a record is verified against every baked key).
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Iterable, Mapping, Optional

from . import ed25519

# Base64 of the raw 32-byte Ed25519 public keys this build trusts.
#
# THE PRIVATE HALF LIVES OFF THIS MACHINE AND OUT OF THIS REPO --
# %USERPROFILE%\.ccsync-release\release.key on the release rig, 0600, never
# committed (tools/release_key.py new). Baking the PUBLIC half here is the
# whole point: a customer's dashboard can be compromised and still cannot
# produce a build this companion will install.
#
# Generated 2026-08-17 on the base rig by the commercial-readiness pass so the
# signing path could be exercised end to end. OPERATOR: if you want a key you
# generated yourself (or one held on a hardware token / an offline machine),
# run `python tools/release_key.py new --force` and `... bake` BEFORE the
# first customer ship -- after that, rotating costs an overlap release.
RELEASE_PUBKEYS: tuple[str, ...] = (
    "GKNmk8MktRkGkrBv+ziF7O6ZNKCnjXfC9/TwDiYwKDY=",
)

# Domain separation. A signature is over these bytes and nothing else, so a
# release signature can never be replayed as a signature over anything else
# this key might one day be asked for.
RECORD_PREFIX = b"ccsync-release-record-v1\n"

# Every field the signature covers, in the shape the dashboard stores and
# serves. Adding a field means a new prefix (v2) and an overlap release --
# an old companion canonicalises only the fields it knows and would reject
# every new record. See docs/RELEASE.md.
RECORD_FIELDS: tuple[str, ...] = (
    "kind",
    "platform",
    "version",
    "filename",
    "sha256",
    "size_bytes",
    "min_version",
    "published_at",
    "signed_binary",
)

# Fields the signature covers for ONE KIND ONLY (ZERO_TOUCH_PLAN.md WP K,
# 2026-08-18). A `dashboard` record -- the dashboard's own code bundle, which
# the container applies to itself -- carries a tenth signed field,
# `runtime_id`: the id of the image runtime the bundle was built against
# (dashboard/src/ccsync_dashboard/runtime_id.py). It has to be INSIDE the
# signature, because it is what decides whether an update may be applied at
# all; an unsigned runtime_id would let anyone able to serve the feed relabel
# a bundle as compatible with a runtime it was never built for.
#
# Scoped to the kind rather than added to RECORD_FIELDS on purpose. Adding a
# field to EVERY record would need a v2 prefix and an overlap release (an old
# companion canonicalises only the fields it knows and would reject every new
# record -- see RECORD_FIELDS above). No companion ever sees a `dashboard`
# record: they are applied by the dashboard itself and are never published
# into `companion_packages`. So every companion/onboard record canonicalises
# byte for byte as it always did, and the new kind gets the field it needs.
KIND_EXTRA_FIELDS: dict = {"dashboard": ("runtime_id",)}

# Kind-scoped extras that are OPTIONAL: signed when the record carries one,
# absent from the canonical bytes when it does not (REL-4/SYS-13, REL-16,
# resilience sweep 2026-08-28). MUST match release_trust.py's copy -- these
# two files are duplicated on purpose (see the module docstring), and a
# disagreement here is "every editor refuses every build".
#
# `requires_dashboard` is the dashboard version a companion build needs before
# it may be offered at all; `arch` is the CPU it was built for. Both are
# enforced by the DASHBOARD; a companion only has to canonicalise them, which
# is what this build being able to accept a record that carries them means.
#
# Blank reads as ABSENT: the signer omits an empty field, so a record served
# with `arch=""` must canonicalise like a pre-wave record that never had the
# key. That is what keeps every record published before this wave verifying
# byte for byte.
OPTIONAL_KIND_EXTRA_FIELDS: dict = {
    "companion": ("arch", "requires_dashboard"),
}


def record_fields(kind, record: Optional[Mapping[str, Any]] = None) -> tuple:
    """The exact field list the signature covers for this record's kind.

    With `record`, the optional kind-scoped extras it actually carries are
    appended. Order is irrelevant (canonical_record sorts keys); presence is
    not.
    """
    base = RECORD_FIELDS + tuple(KIND_EXTRA_FIELDS.get(str(kind or ""), ()))
    if record is None:
        return base
    extras = tuple(
        field for field in OPTIONAL_KIND_EXTRA_FIELDS.get(str(kind or ""), ())
        if str(record.get(field) or "").strip()
    )
    return base + extras



def canonical_record(record: Mapping[str, Any]) -> bytes:
    """The exact bytes the release key signs.

    Deterministic by construction: fixed field set, sorted keys, no
    whitespace, and every value coerced to its declared type -- so a JSON
    round-trip through the dashboard's SQLite columns (where a bool comes
    back as 0/1 and a size as an int) reproduces the same bytes the signer
    saw. Raises on a missing field: an unsignable record must never
    canonicalise to *something*."""
    out: dict[str, Any] = {}
    for field in record_fields(record.get("kind", ""), record):
        if field not in record:
            raise KeyError(f"release record is missing {field!r}")
        value = record[field]
        if field == "size_bytes":
            out[field] = int(value)
        elif field == "signed_binary":
            out[field] = bool(value)
        else:
            out[field] = str(value)
    return RECORD_PREFIX + json.dumps(
        out, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def pubkey_id(pubkey_b64: str) -> str:
    """A short, stable name for a key: the first 16 hex of sha256(raw key).
    Human-quotable in a log line and in `check_deploy_drift.ps1`."""
    try:
        raw = base64.b64decode(str(pubkey_b64).strip(), validate=True)
    except Exception:
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]


def verify_record(
    record: Mapping[str, Any],
    signature_b64: str,
    pubkeys: Optional[Iterable[str]] = None,
) -> tuple[bool, str]:
    """(ok, detail). NEVER RAISES -- the caller is deciding whether to
    overwrite a running binary.

    `detail` is the pubkey_id that verified it on success, and a short reason
    on failure, so the refusal log line says WHICH check failed rather than
    "invalid"."""
    keys = tuple(RELEASE_PUBKEYS if pubkeys is None else pubkeys)
    if not keys:
        return False, "this build trusts no release key at all"
    try:
        sig = base64.b64decode(str(signature_b64 or "").strip(), validate=True)
    except Exception:
        return False, "signature is not valid base64"
    if len(sig) != 64:
        return False, f"signature is {len(sig)} bytes, not 64"
    try:
        message = canonical_record(record)
    except Exception as exc:
        return False, f"record is not signable ({exc})"
    for key in keys:
        try:
            raw = base64.b64decode(str(key).strip(), validate=True)
        except Exception:
            continue
        if len(raw) != 32:
            continue
        if ed25519.verify(raw, message, sig):
            return True, pubkey_id(key)
    return False, "no baked release key verifies this record"
