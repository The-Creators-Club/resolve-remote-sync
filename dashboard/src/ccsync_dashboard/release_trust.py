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

# Kind-scoped extra fields that are OPTIONAL: covered by the signature when
# the record carries one, absent from the canonical bytes when it does not
# (REL-4/SYS-13 and REL-16, resilience sweep 2026-08-28).
#
# `requires_dashboard` is the dashboard version this companion build needs --
# "deploy the dashboard before the companions", which was a rule in four docs
# and enforced nowhere. `arch` is the CPU the binary was built for, so an
# Intel Mac is never handed an arm64 exe that cannot exec.
#
# OPTIONAL is what makes them free of a v2 prefix. A record published before
# this wave carries neither key, canonicalises over exactly the nine fields
# it always did, and keeps verifying byte for byte -- on this dashboard and in
# every companion in the field. The cost is on the OTHER side and must be
# paid before the fields are ever emitted: a companion whose release_pubkey.py
# does not know them canonicalises without them and REFUSES a record that
# carries them, which is the overlap release RECORD_FIELDS' comment warns
# about. So `tools/sign_release.py` may only start filling these in once the
# fleet is on a build that mirrors this function (docs/RELEASE.md).
#
# A blank value reads as ABSENT, deliberately: the signer omits an empty
# field, so a record that arrives with `arch=""` must canonicalise like one
# that never had the key, or a stray empty query param would break every
# signature.
OPTIONAL_KIND_EXTRA_FIELDS: dict = {
    "companion": ("arch", "requires_dashboard"),
}


def record_fields(kind, record: Mapping[str, Any] | None = None) -> tuple:
    """The exact field list the signature covers for this record's kind.

    With `record`, the optional kind-scoped extras this record actually
    carries are appended. Field ORDER does not matter (canonical_record
    json.dumps with sort_keys=True); presence does.
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
    """The exact bytes the release key signs. See the companion's copy."""
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


def version_above(left: Any, right: Any) -> bool | None:
    """Is dotted-numeric `left` strictly above `right`?

    None when either side cannot be parsed -- "could not compare" must never
    render as "fine" (resilience sweep 2026-08-28), so the ordering gate
    treats None as a refusal it can explain rather than a silent pass.

    Numeric per part, like every other version comparison in this product:
    after 0.9.9 comes 0.10.0, never 1.0 (owner's rule 2026-08-18), and a
    string compare puts 0.10.0 BELOW 0.9.9. `packaging.version` would agree
    on these shapes, but it is a build-time dependency here, not one the
    container's runtime is guaranteed to carry -- and the two-digit-minor
    rule is exactly what this file already had to get right for min_version.
    """
    a, b = _version_tuple(left), _version_tuple(right)
    if not a or not b:
        return None
    return a > b


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
