#!/usr/bin/env python3
"""Sign one package record with the offline release key.

COMMERCIAL_READINESS.md item 4, 2026-08-17. Called by
installer/build_editor_package.ps1 (Windows) and tools/release_macos.sh /
tools/build_onboard_macos.sh (macOS) immediately before the PUT, and by
nothing else. It prints a JSON object the caller turns into query
parameters:

    {"signature": "...", "pubkey_id": "...", "min_version": "...",
     "published_at": "...", "filename": "...", "sha256": "...",
     "size_bytes": N, "signed_binary": true|false, "query": "..."}

`query` is the ready-made `&signature=...&pubkey_id=...` suffix, so a shell
never has to url-encode base64 by hand (a `+` in a signature silently
becomes a space if it does).

    python tools/sign_release.py --artifact companion/dist/ccsync-companion.exe \
        --kind companion --platform windows --version 0.7.12 \
        --min-version 0.7.12 --signed-binary

The filename is DERIVED here exactly as the dashboard derives it, and it is
part of the signed record: the server compares the name it chose against the
signed one and refuses a mismatch. That is what stops a published artifact
being re-labelled as another kind or platform after the fact.

`--published-at` defaults to now (UTC, seconds). It is signed, so the server
stores the signer's timestamp rather than its own -- otherwise the record it
serves would not be the record that was signed.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))

from ccsync_companion import ed25519  # noqa: E402
from ccsync_companion import release_pubkey  # noqa: E402

import release_key as release_key_mod  # noqa: E402  (tools/release_key.py)

# `linux` joined the list with the `dashboard` kind (ZERO_TOUCH_PLAN.md WP K,
# 2026-08-18): the dashboard's code bundle runs in a Linux container and
# nowhere else, and the feed's (kind, platform, version) key wants a real
# platform rather than a blank one.
PLATFORMS = ("windows", "macos", "linux")
# `dashboard` is NOT a companion-style package: it is never published into
# `companion_packages` and no editor machine ever downloads one. It is the
# dashboard's own code, applied by the container to itself
# (dashboard/src/ccsync_dashboard/dashboard_update.py). It signs one extra
# field, `runtime_id` -- see release_pubkey.KIND_EXTRA_FIELDS.
KINDS = ("companion", "onboard", "dashboard")

# The kinds whose signed record carries a runtime_id, and which therefore need
# `--runtime-id` on the command line. Read from the record module rather than
# repeated here, so adding a kind there is the only edit.
RUNTIME_ID_KINDS = tuple(
    kind for kind, fields in release_pubkey.KIND_EXTRA_FIELDS.items()
    if "runtime_id" in fields
)

# REL-4 / REL-16 (resilience sweep 2026-08-28). Two more kind-scoped fields,
# both optional in MEANING and mandatory in the CANONICAL BYTES: whatever
# release_pubkey.KIND_EXTRA_FIELDS says a kind's record covers, every record
# of that kind must carry, because canonical_record raises on a missing field.
# So an unknown value is the EMPTY STRING inside the signature, never an
# absent key -- "absent means offer it to everyone" is a decision the
# dashboard makes about a stored record, not a shape the signer may produce.
#   requires_dashboard  the oldest dashboard VERSION this build works against
#                       ("deploy the dashboard before the companions", which
#                       CLAUDE.md states four times and nothing checked)
#   arch                x86_64 / arm64 / universal2, measured by the builder
#                       (tools/release_macos.sh has measured it since the
#                       macOS port and dropped it at the publish)
OPTIONAL_EXTRA_FIELDS = ("requires_dashboard", "arch")
ARCHITECTURES = ("x86_64", "arm64", "universal2")


def optional_fields_for(kind: str) -> tuple:
    """The OPTIONAL kind-scoped signed fields, read from the record module.

    Optional means the signature covers the field only when the record
    carries a non-empty value, so every record published before this wave
    canonicalises exactly as it always did and no overlap release is owed.
    An older checkout of release_pubkey.py has no such table; there the
    answer is "none", and main() then says what it is not publishing.
    """
    table = getattr(release_pubkey, "OPTIONAL_KIND_EXTRA_FIELDS", {})
    return tuple(table.get(str(kind or ""), ()))


def mandatory_fields_for(kind: str) -> tuple:
    """The kind-scoped fields EVERY record of that kind must carry."""
    return tuple(release_pubkey.KIND_EXTRA_FIELDS.get(str(kind or ""), ()))


def package_filename(kind: str, platform: str, version: str, head: bytes = b"") -> str:
    """MUST stay identical to the dashboard's api._package_filename.

    Duplicated rather than imported: this runs on the release rig (and on a
    Mac) with only the companion package importable, while the authority is
    in the container. The signature binds the two together -- if they ever
    disagree, the publish is refused instead of quietly serving a record
    that describes a different file (dashboard/tests/test_packages.py
    test_signed_filename_matches_the_server_choice pins it)."""
    if kind == "dashboard":
        # Must stay identical to tools/build_dashboard_bundle.bundle_filename:
        # the filename is signed, and the dashboard checks the name it
        # extracted against the signed one.
        return f"ccsync-dashboard-{version}.tar.gz"
    if kind == "onboard":
        if platform == "windows":
            return f"ccsync-onboard-{version}.exe"
        return f"ccsync-onboard-{version}" + (".zip" if head[:2] == b"PK" else ".sh")
    return f"ccsync-companion-{version}" + (".exe" if platform == "windows" else "")


# The floor comparison, byte for byte the rule the dashboard enforces in
# release_trust.min_version_exceeds_version and the companion in
# upgrade._min_version_above_own. THREE copies on purpose: the signing rig
# imports neither the container's code nor (from a Mac) anything but the
# companion package, and the whole point of CR-52 is that no side may be the
# only one holding the rule. Kept deliberately literal so a diff against
# release_trust.py reads as identical logic rather than a clever variant.
_VERSION_CHARS = "0123456789."


def version_tuple(text: Any) -> tuple[int, ...]:
    """A dotted-numeric version as a tuple of ints, () for anything else.

    Strict on purpose (same as release_trust._version_tuple): a value we
    cannot fully rank must not be ranked, because ranking it wrong is what
    CR-52 was about.
    """
    raw = str(text or "").strip()
    if not raw or any(ch not in _VERSION_CHARS for ch in raw):
        return ()
    try:
        return tuple(int(part) for part in raw.split(".") if part != "")
    except ValueError:
        return ()


def min_version_exceeds_version(version: Any, min_version: Any) -> bool:
    """Whether a record's downgrade floor is ABOVE the build it describes.

    CR-52 / CR-67 item 3 (2026-08-21). One typo on the release rig
    (`--min-version 0.9.54` for a 0.9.44 build) produced a perfectly valid
    signature over a record that can only ever refuse itself: every companion
    raises its monotonic floor on RECEIPT, so merely seeing that offer put
    the whole fleet above the build being offered, and the corrected
    republish was below the floor too. The dashboard and the companion both
    refuse such a record now; this is the cheapest place of all to catch it,
    because here the operator can just retype the flag.

    Unparseable input is NOT reported as exceeding: the dotted-numeric check
    in main() owns "is this a version at all", and two refusals for one fault
    would name the wrong one.
    """
    left = version_tuple(min_version)
    right = version_tuple(version)
    if not left or not right:
        return False
    return left > right


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(
    *,
    artifact: Path,
    kind: str,
    platform: str,
    version: str,
    min_version: str,
    published_at: str,
    signed_binary: bool,
    runtime_id: str = "",
    requires_dashboard: str = "",
    arch: str = "",
) -> dict:
    data_head = b""
    digest = hashlib.sha256()
    size = 0
    with artifact.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            if not data_head:
                data_head = chunk[:4]
            size += len(chunk)
            digest.update(chunk)
    if size == 0:
        raise SystemExit(f"{artifact} is empty -- nothing to sign")
    record = {
        "kind": kind,
        "platform": platform,
        "version": version,
        "filename": package_filename(kind, platform, version, head=data_head),
        "sha256": digest.hexdigest(),
        "size_bytes": size,
        "min_version": min_version,
        "published_at": published_at,
        "signed_binary": bool(signed_binary),
    }
    # Only for the kinds whose canonical record covers it: putting a
    # runtime_id on a companion record would change bytes every companion in
    # the field verifies (release_pubkey.KIND_EXTRA_FIELDS).
    extra = {
        "runtime_id": runtime_id,
        "requires_dashboard": requires_dashboard,
        "arch": arch,
    }
    for field in mandatory_fields_for(kind):
        # A field this signer has never heard of must stop the release here,
        # where the fix is one line, rather than produce a record every
        # companion in the field refuses.
        if field not in extra:
            raise SystemExit(
                f"release_pubkey.KIND_EXTRA_FIELDS says a {kind!r} record covers "
                f"{field!r}, which tools/sign_release.py cannot fill in. Teach it "
                f"that field (and the flag that carries it) before publishing.")
        record[field] = str(extra[field] or "")
    # OPTIONAL extras are OMITTED when blank, never written as "" (REL-4 /
    # REL-16, 2026-08-28): the canonical bytes of a record without the key and
    # a record with an empty one are different, and "absent" is what every
    # record published before this wave says.
    for field in optional_fields_for(kind):
        value = str(extra.get(field) or "").strip()
        if value:
            record[field] = value
    return record


def query_suffix(record: dict, signature: str, pubkey_id: str,
                 provenance: dict | None = None) -> str:
    from urllib.parse import quote

    suffix = (
        f"&signature={quote(signature, safe='')}"
        f"&pubkey_id={quote(pubkey_id, safe='')}"
        f"&min_version={quote(record['min_version'], safe='')}"
        f"&published_at={quote(record['published_at'], safe='')}"
        f"&signed_binary={'1' if record['signed_binary'] else '0'}"
    )
    # Every SIGNED field the server would otherwise have to guess at. Sent
    # even when empty (REL-4/REL-16, 2026-08-28): the dashboard re-derives the
    # canonical bytes from what it stored, so a field inside the signature and
    # absent from the query is a publish that verifies nowhere.
    for field in OPTIONAL_EXTRA_FIELDS:
        if field in record:
            suffix += f"&{field}={quote(str(record[field]), safe='')}"
    # UNSIGNED provenance (REL-13): advisory columns the Packages page and the
    # drift check render, so "0.9.55" can never again mean two different sets
    # of bytes with no way to tell which commit the fleet is on.
    for field, value in sorted((provenance or {}).items()):
        if str(value) != "":
            suffix += f"&{field}={quote(str(value), safe='')}"
    return suffix


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", required=True, help="the file being published")
    ap.add_argument("--kind", required=True, choices=KINDS)
    ap.add_argument("--platform", required=True, choices=PLATFORMS)
    ap.add_argument("--version", required=True)
    ap.add_argument(
        "--min-version", default="0.0.0",
        help="the OLDEST build the fleet may be rolled back to from here. "
             "Companions remember the highest value they have ever accepted "
             "and refuse anything below it -- raise it whenever a release "
             "fixes something a downgrade would reintroduce.",
    )
    ap.add_argument("--published-at", default="", help="UTC ISO8601; default now")
    ap.add_argument("--signed-binary", action="store_true",
                    help="the artifact carries a real Authenticode / Developer ID "
                         "signature (NOT ad-hoc, NOT unsigned)")
    ap.add_argument("--runtime-id", default="",
                    help="required for --kind dashboard: the image runtime the bundle was "
                         "built against (tools/build_dashboard_bundle.py prints it, and it "
                         "is inside the bundle's manifest.json). It is SIGNED, because it "
                         "is what decides whether a dashboard may apply the bundle at all")
    ap.add_argument("--requires-dashboard", default="",
                    help="the OLDEST dashboard VERSION this build works against. SIGNED. "
                         "A dashboard below it refuses to advertise the build at all "
                         "(REL-4: 'deploy the dashboard before the companions' was a "
                         "sentence in four docs and a check in no code). Read from the "
                         "companion's REQUIRES_DASHBOARD constant by the build scripts")
    ap.add_argument("--emit-kind-extras", action="store_true",
                    help="sign requires_dashboard/arch into the record (only once every "
                         "companion in the fleet is 0.9.55+; see the overlap note in "
                         "docs/RELEASE.md)")
    ap.add_argument("--arch", default="", choices=("",) + ARCHITECTURES,
                    help="the architecture the artifact runs on, as measured by the "
                         "builder. SIGNED. Blank means 'unknown' and is offered to every "
                         "machine of that platform, which is what every record published "
                         "before 2026-08-28 says (REL-16)")
    ap.add_argument("--git-sha", default="",
                    help="short commit the artifact was built from. UNSIGNED provenance, "
                         "passed through to the publish (REL-13)")
    # APP-16 (usability sweep 2026-09-04): one line of "what changed", shown
    # in the editor's update dialog. UNSIGNED, exactly like the git pair
    # below it: the signature covers a field list every companion in the
    # field mirrors, and a record carrying a field an older canonicaliser
    # does not know is REFUSED by that build with no over-the-air recovery
    # (the overlap-release rule this file already applies to
    # requires_dashboard/arch). A sentence must never be able to strand a
    # machine. CCSYNC_RELEASE_NOTES is the environment route, so a caller
    # that shells this script without owning its argv (ship.ps1 ->
    # build_editor_package.ps1) can still set it.
    ap.add_argument("--notes", default="",
                    help="one line of what changed, shown in the editor's update "
                         "dialog. UNSIGNED advisory (APP-16); "
                         "$CCSYNC_RELEASE_NOTES is read when this is absent")
    ap.add_argument("--git-dirty", default="", choices=("", "0", "1"),
                    help="1 when the build came from an uncommitted tree. UNSIGNED "
                         "provenance (REL-13)")
    ap.add_argument("--key", default="", help="release key file (default ~/.ccsync-release/release.key)")
    ap.add_argument("--out", default="", help="also write the JSON here")
    args = ap.parse_args(argv)

    artifact = Path(args.artifact).expanduser()
    if not artifact.is_file():
        raise SystemExit(f"no artifact at {artifact}")
    if not args.min_version.replace(".", "").isdigit() or not args.min_version:
        raise SystemExit(f"--min-version must be dotted-numeric, got {args.min_version!r}")
    # CR-52 / CR-67 item 3: never MAKE a record that refuses itself. Checked
    # before the key is read, so a typo costs a retype and not a signature.
    if min_version_exceeds_version(args.version, args.min_version):
        raise SystemExit(
            f"--min-version {args.min_version} is ABOVE --version {args.version}: this "
            "record would tell every machine \"you may not install below "
            f"{args.min_version}\" while offering {args.version}, which is below it.\n"
            "Companions raise that floor the moment they SEE the offer and never lower "
            "it, so publishing this refuses the build, every earlier build, and the "
            "corrected republish too -- recoverable only by hand on each machine "
            "(KNOWN_BUGS CR-52). Pass --min-version at or below --version.")
    if args.requires_dashboard.strip() and not version_tuple(args.requires_dashboard):
        raise SystemExit(
            f"--requires-dashboard must be dotted-numeric, got "
            f"{args.requires_dashboard!r}: it is compared against the dashboard's own "
            "VERSION, and a value that cannot be ranked would be ranked wrong (CR-52's "
            "lesson about min_version).")
    # A field the signature does not cover cannot be published, and the two
    # values fail in OPPOSITE directions (REL-4 / REL-16, 2026-08-28).
    #
    # requires_dashboard is a SAFETY CONSTRAINT: dropping it silently leaves
    # the operator believing an ordering rule exists while every customer's
    # companions take a build their dashboard has no columns for. Refuse.
    #
    # arch is a NARROWING: dropping it means "offered to every machine of that
    # platform", which is exactly what every record published before this
    # sweep says and what the fleet already lives with. Say so and continue --
    # refusing would make the build unpublishable on a checkout where the
    # record module has not been taught the field yet.
    # OVERLAP CONSTRAINT (REL-4 / REL-16, 2026-08-28): the kind-scoped extras
    # are absent from the canonical bytes when unset, so every record without
    # them verifies on every companion ever shipped -- but a record that
    # CARRIES one is only verifiable by a companion whose release_pubkey.py
    # knows the field (0.9.55+). Emitting them while any machine in the fleet
    # is older makes that machine refuse the build with "release signature
    # rejected", and there is no over-the-air recovery from that (REL-7).
    # So emission is opt-in: --emit-kind-extras (or CCSYNC_EMIT_KIND_EXTRAS=1)
    # once every machine reports 0.9.55 or newer. Until then the values are
    # dropped LOUDLY and the fleet keeps today's behaviour.
    emit_extras = bool(args.emit_kind_extras) or (
        os.environ.get("CCSYNC_EMIT_KIND_EXTRAS", "").strip() == "1")
    if not emit_extras and (args.requires_dashboard.strip() or args.arch.strip()):
        print(
            "NOTE: requires_dashboard/arch NOT signed into this record: pass "
            "--emit-kind-extras once every companion in the fleet is on 0.9.55 or "
            "newer (older builds refuse a record that carries them: release "
            "signature rejected, no OTA recovery). Until then this build is offered "
            "to every machine on the platform with no dashboard-ordering check, as "
            "every record before 2026-08-28 was.", file=sys.stderr)
        args.requires_dashboard = ""
        args.arch = ""
    covered = optional_fields_for(args.kind) + mandatory_fields_for(args.kind)
    if args.requires_dashboard.strip() and "requires_dashboard" not in covered:
        raise SystemExit(
            f"--requires-dashboard was given, but a {args.kind!r} record's signature does "
            "not cover it in this build (release_pubkey.KIND_EXTRA_FIELDS). Publishing "
            "would drop the constraint silently and the ordering rule would exist only in "
            "your head. Add the field there first, or drop the flag.")
    if args.arch.strip() and "arch" not in covered:
        print(
            f"NOTE: --arch {args.arch.strip()} is not part of a {args.kind!r} record's "
            "signature in this build, so it is NOT published: this build will be offered "
            "to every machine on that platform, as every record before 2026-08-28 was "
            "(REL-16).", file=sys.stderr)
        args.arch = ""
    if args.kind in RUNTIME_ID_KINDS and not args.runtime_id.strip():
        # Refused rather than defaulted to "": a dashboard record with a blank
        # runtime_id verifies fine and is then refused by every customer as a
        # runtime mismatch, which is a very slow way to learn about a typo.
        raise SystemExit(
            f"--kind {args.kind} needs --runtime-id (it is part of the signed record). "
            "tools/build_dashboard_bundle.py prints it, and it is in the bundle's "
            "manifest.json.")

    secret = release_key_mod.read_secret(release_key_mod.key_path(args.key))
    record = build_record(
        artifact=artifact,
        kind=args.kind,
        platform=args.platform,
        version=args.version,
        min_version=args.min_version,
        published_at=args.published_at.strip() or utcnow_iso(),
        signed_binary=args.signed_binary,
        runtime_id=args.runtime_id.strip(),
        requires_dashboard=args.requires_dashboard.strip(),
        arch=args.arch.strip(),
    )
    signature = base64.b64encode(
        ed25519.sign(secret, release_pubkey.canonical_record(record))
    ).decode("ascii")
    pub = base64.b64encode(ed25519.public_key(secret)).decode("ascii")
    key_id = release_pubkey.pubkey_id(pub)

    # Prove what we just produced before it goes anywhere: a signature that
    # does not verify locally would surface as an opaque 400 from the
    # dashboard halfway through a ship.
    ok, detail = release_pubkey.verify_record(record, signature, pubkeys=[pub])
    if not ok:
        raise SystemExit(f"the signature just produced does not verify: {detail}")

    out = dict(record)
    out["signature"] = signature
    out["pubkey_id"] = key_id
    notes = " ".join(
        (args.notes or os.environ.get("CCSYNC_RELEASE_NOTES", "")).split())[:300]
    out["query"] = query_suffix(
        record, signature, key_id,
        provenance={"git_sha": args.git_sha.strip(),
                    "git_dirty": args.git_dirty.strip(),
                    "notes": notes})
    # Echoed OUTSIDE the record so the caller can render them without having
    # to know which fields the signature happens to cover this release.
    out["git_sha"] = args.git_sha.strip()
    out["git_dirty"] = args.git_dirty.strip()
    out["notes"] = notes
    text = json.dumps(out, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)

    if args.min_version == "0.0.0":
        # Not an error: a fleet mid-migration genuinely has no floor to
        # enforce yet. But a floor nobody ever raises is a feature that
        # never fires, so say it out loud every single time.
        print(
            "NOTE: min_version is 0.0.0 -- this release sets NO downgrade floor. "
            "Pass --min-version <oldest build you would still accept> once the "
            "fleet is on signed builds (docs/RELEASE.md).",
            file=sys.stderr,
        )
    if not record["signed_binary"]:
        print(
            "NOTE: signed_binary=false -- the artifact itself carries no "
            "Authenticode/Developer ID signature. The upgrade channel is still "
            "signature-protected; SmartScreen/Gatekeeper are not satisfied.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
