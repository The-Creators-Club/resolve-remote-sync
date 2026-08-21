"""Server-side half of the signed upgrade channel (COMMERCIAL_READINESS.md
item 4, 2026-08-17).

The dashboard STORES AND SERVES a signature it cannot produce. That is the
whole design: the release key is offline on the release rig, so a
compromised dashboard -- or a customer's own admin -- can publish nothing a
companion will install. Verifying on publish as well is belt and braces: it
turns "the fleet quietly stops upgrading" into "the ship fails at the PUT,
in front of the person doing it".

The record format and the canonicalisation MUST match
companion/src/ccsync_companion/release_pubkey.py byte for byte -- they are
two copies on purpose (different deployment units, neither can import the
other; see ed25519.py). dashboard/tests/test_packages.py pins the ed25519
copy against the companion's.

Which keys are trusted here is CONFIGURATION, not a constant: a customer
running their own dashboard pins the vendor's key via DASH_RELEASE_PUBKEYS
(Settings.release_pubkeys), and a vendor who rotates sets both keys for the
overlap release. Empty = the channel is unauthenticated, and publishing is
refused outright rather than falling back.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Iterable, Mapping

from . import ed25519

RECORD_PREFIX = b"ccsync-release-record-v1\n"

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

_MIN_VERSION_OK = "0123456789."

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


def record_fields(kind) -> tuple:
    """The exact field list the signature covers for this record's kind."""
    return RECORD_FIELDS + tuple(KIND_EXTRA_FIELDS.get(str(kind or ""), ()))


def canonical_record(record: Mapping[str, Any]) -> bytes:
    """The exact bytes the release key signs. See the companion's copy."""
    out: dict[str, Any] = {}
    for field in record_fields(record.get("kind", "")):
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
    try:
        raw = base64.b64decode(str(pubkey_b64).strip(), validate=True)
    except Exception:
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]


def verify_record(
    record: Mapping[str, Any],
    signature_b64: str,
    pubkeys: Iterable[str],
) -> tuple[bool, str]:
    """(ok, detail). Never raises -- a malformed signature is a 4xx, not a
    500 that takes the publish route down for everyone."""
    keys = tuple(k for k in (str(k).strip() for k in pubkeys) if k)
    if not keys:
        return False, "no release public key is configured (DASH_RELEASE_PUBKEYS)"
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
            raw = base64.b64decode(key, validate=True)
        except Exception:
            continue
        if len(raw) != 32:
            continue
        if ed25519.verify(raw, message, sig):
            return True, pubkey_id(key)
    return False, "no configured release public key verifies this record"


def _version_tuple(text: Any) -> tuple[int, ...]:
    raw = str(text or "").strip()
    if not raw or any(ch not in _MIN_VERSION_OK for ch in raw):
        return ()
    try:
        return tuple(int(p) for p in raw.split(".") if p != "")
    except ValueError:
        return ()


def min_version_exceeds_version(version: Any, min_version: Any) -> bool:
    """Whether a record's downgrade floor is ABOVE the build it describes.

    dash-release-ai-3 (2026-08-21): one typo on the release rig
    (`--min-version 0.9.54` for a 0.9.44 build) was accepted by every
    verifier, and `upgrade.note_floor` on each companion is monotonic and
    persistent -- so merely SEEING that offer raised every machine's floor
    above the build on offer, refused it, and then refused the corrected
    republish and the rollback too. Recovery was a build numbered past the
    typo or deleting `upgrade_floor.json` by hand on every editor's machine.
    A record that can only ever refuse itself is a mistake, never an
    intention, so nothing may publish one.

    Unparseable input is NOT reported as exceeding: `valid_min_version` is
    the check that owns "is this a version at all", and two refusals for one
    fault would name the wrong one.
    """
    left = _version_tuple(min_version)
    right = _version_tuple(version)
    if not left or not right:
        return False
    return left > right


def valid_min_version(text: Any) -> bool:
    """A dotted-numeric version, or empty. The floor is compared numerically
    by the companion (upgrade.parse_version), which refuses anything it
    cannot fully parse -- so a record carrying `min_version = "nightly"`
    would be rejected by every editor while looking fine here."""
    raw = str(text or "").strip()
    if not raw:
        return False
    if any(ch not in _MIN_VERSION_OK for ch in raw):
        return False
    parts = raw.split(".")
    return bool(parts) and all(part.isdigit() for part in parts)
