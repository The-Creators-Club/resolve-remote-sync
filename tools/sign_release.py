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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))

from ccsync_companion import ed25519  # noqa: E402
from ccsync_companion import release_pubkey  # noqa: E402

import release_key as release_key_mod  # noqa: E402  (tools/release_key.py)

PLATFORMS = ("windows", "macos")
KINDS = ("companion", "onboard")


def package_filename(kind: str, platform: str, version: str, head: bytes = b"") -> str:
    """MUST stay identical to the dashboard's api._package_filename.

    Duplicated rather than imported: this runs on the release rig (and on a
    Mac) with only the companion package importable, while the authority is
    in the container. The signature binds the two together -- if they ever
    disagree, the publish is refused instead of quietly serving a record
    that describes a different file (dashboard/tests/test_packages.py
    test_signed_filename_matches_the_server_choice pins it)."""
    if kind == "onboard":
        if platform == "windows":
            return f"ccsync-onboard-{version}.exe"
        return f"ccsync-onboard-{version}" + (".zip" if head[:2] == b"PK" else ".sh")
    return f"ccsync-companion-{version}" + (".exe" if platform == "windows" else "")


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
    return {
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


def query_suffix(record: dict, signature: str, pubkey_id: str) -> str:
    from urllib.parse import quote

    return (
        f"&signature={quote(signature, safe='')}"
        f"&pubkey_id={quote(pubkey_id, safe='')}"
        f"&min_version={quote(record['min_version'], safe='')}"
        f"&published_at={quote(record['published_at'], safe='')}"
        f"&signed_binary={'1' if record['signed_binary'] else '0'}"
    )


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
    ap.add_argument("--key", default="", help="release key file (default ~/.ccsync-release/release.key)")
    ap.add_argument("--out", default="", help="also write the JSON here")
    args = ap.parse_args(argv)

    artifact = Path(args.artifact).expanduser()
    if not artifact.is_file():
        raise SystemExit(f"no artifact at {artifact}")
    if not args.min_version.replace(".", "").isdigit() or not args.min_version:
        raise SystemExit(f"--min-version must be dotted-numeric, got {args.min_version!r}")

    secret = release_key_mod.read_secret(release_key_mod.key_path(args.key))
    record = build_record(
        artifact=artifact,
        kind=args.kind,
        platform=args.platform,
        version=args.version,
        min_version=args.min_version,
        published_at=args.published_at.strip() or utcnow_iso(),
        signed_binary=args.signed_binary,
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
    out["query"] = query_suffix(record, signature, key_id)
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
