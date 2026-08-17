#!/usr/bin/env python3
r"""Build/update a local vendor release feed directory -- no network write.

Why this exists (2026-08-17, ZERO_TOUCH_PLAN.md WP E, part 2). Today a
customer's dashboard learns about a new build only from a human PUTting
bytes into THAT dashboard (tools/publish_package.py). This tool is the other
half: it assembles the STATIC files a feed host serves --

    <feed-dir>/channel.json          the signed manifest (docs/RELEASE_FEED.md)
    <feed-dir>/channel.json.sig      detached Ed25519 signature over it
    <feed-dir>/<platform>/<file>     the artefacts themselves

-- entirely on disk, using the SAME offline release key and the SAME
per-record signing tools/sign_release.py already uses (imported and called,
never re-implemented here: a second signer would be a second place for the
record shape to drift). This tool never uploads anything: publishing the
directory to wherever it is actually served from is one of

    gh release upload ccsync-releases-v1 <feed-dir>/channel.json \
        <feed-dir>/channel.json.sig <feed-dir>/windows/*.exe --clobber -R ccsync/ccsync-releases
    rclone sync <feed-dir> remote:ccsync-releases --checksum

which docs/RELEASE_FEED.md documents in full.

    python tools/publish_feed.py --artifact companion/dist/ccsync-companion.exe \
        --kind companion --platform windows --version 0.8.0 --min-version 0.7.12 \
        --signed-binary --notes "first zero-touch build" \
        --feed-dir .\feed --base-url https://releases.ccsync.app/v1

    python tools/publish_feed.py --manifest companion\dist\ccsync-release.json \
        --feed-dir .\feed --base-url https://releases.ccsync.app/v1

    python tools/publish_feed.py --set-image 1.2.3@sha256:deadbeef... --feed-dir .\feed

    python tools/publish_feed.py --verify .\feed

Exit codes: 2 usage, 3 the manifest condemned the build (dirty/untested,
unless overridden), 4 the freshly-written feed failed its own offline
verification (should never happen -- see main()).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))

import release_key as release_key_mod  # noqa: E402  (tools/release_key.py)
import sign_release  # noqa: E402       (tools/sign_release.py)

from ccsync_companion import ed25519  # noqa: E402
from ccsync_companion import release_pubkey  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONDEMNED = 3
EXIT_SELF_VERIFY_FAILED = 4

SCHEMA = 1
DEFAULT_CHANNEL_NAME = "stable"
CHANNEL_FILENAME = "channel.json"
SIG_FILENAME = "channel.json.sig"

# Domain separation for the channel-level detached signature -- MUST match
# dashboard/src/ccsync_dashboard/release_feed.py's copy byte-for-byte. Two
# deployment units (this runs on the release rig; that runs in the
# customer's container) neither of which may import the other -- the same
# reason release_pubkey.py and release_trust.py are two copies of one
# record-level scheme. See docs/RELEASE_FEED.md.
CHANNEL_PREFIX = b"ccsync-channel-v1\n"


class PublishFeedError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


def canonical_channel_bytes(channel: dict[str, Any]) -> bytes:
    return CHANNEL_PREFIX + json.dumps(
        channel, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sign_artifact(artifact: Path, *, kind: str, platform: str, version: str,
                   min_version: str, signed_binary: bool, published_at: str, key: str) -> dict:
    """Run sign_release.main in-process and capture its JSON -- the SAME
    record shape and the SAME key file tools/sign_release.py uses everywhere
    else, imported rather than duplicated (see the module docstring)."""
    argv = ["--artifact", str(artifact), "--kind", kind, "--platform", platform,
            "--version", version, "--min-version", min_version]
    if signed_binary:
        argv.append("--signed-binary")
    if published_at:
        argv += ["--published-at", published_at]
    if key:
        argv += ["--key", key]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = sign_release.main(argv)
        except SystemExit as exc:
            raise PublishFeedError(f"could not sign {artifact.name}: {exc}", EXIT_USAGE)
    if rc != 0:
        raise PublishFeedError(f"sign_release exited {rc}", EXIT_USAGE)
    try:
        return json.loads(buf.getvalue())
    except ValueError:
        raise PublishFeedError("sign_release produced no JSON", EXIT_USAGE)


def load_channel(feed_dir: Path, channel_name: str) -> dict[str, Any]:
    path = feed_dir / CHANNEL_FILENAME
    if not path.is_file():
        return {"schema": SCHEMA, "generated_at": "", "channel": channel_name,
                "pubkey_id": "", "dashboard_image": {"tag": "", "digest": ""}, "packages": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("packages", [])
    data.setdefault("dashboard_image", {"tag": "", "digest": ""})
    return data


def upsert_record(channel: dict[str, Any], record: dict[str, Any]) -> None:
    key = (record["kind"], record["platform"], record["version"])
    packages = channel.setdefault("packages", [])
    for i, existing in enumerate(packages):
        if (existing.get("kind"), existing.get("platform"), existing.get("version")) == key:
            packages[i] = record
            return
    packages.append(record)


def write_channel(feed_dir: Path, channel: dict[str, Any], *, key_path: str) -> None:
    secret = release_key_mod.read_secret(release_key_mod.key_path(key_path))
    pub = base64.b64encode(ed25519.public_key(secret)).decode("ascii")
    # pubkey_id is PART of the signed document (so a consumer can see which
    # key to expect without decoding the signature first) -- set it BEFORE
    # signing, not after.
    channel["pubkey_id"] = release_pubkey.pubkey_id(pub)
    message = canonical_channel_bytes(channel)
    signature = base64.b64encode(ed25519.sign(secret, message)).decode("ascii")

    # Prove what was just produced verifies, offline, before it goes
    # anywhere -- same discipline as sign_release.py's own self-check.
    ok, detail = verify_channel_signature(channel, signature, pubkeys=[pub])
    if not ok:
        raise PublishFeedError(
            f"the channel signature just produced does not verify: {detail}", EXIT_SELF_VERIFY_FAILED)

    feed_dir.mkdir(parents=True, exist_ok=True)
    (feed_dir / CHANNEL_FILENAME).write_text(
        json.dumps(channel, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (feed_dir / SIG_FILENAME).write_text(signature + "\n", encoding="utf-8")


def verify_channel_signature(channel: dict[str, Any], signature_b64: str,
                             pubkeys) -> tuple[bool, str]:
    keys = tuple(k for k in pubkeys if k)
    if not keys:
        return False, "no release public key to verify against"
    try:
        sig = base64.b64decode(str(signature_b64 or "").strip(), validate=True)
    except Exception:
        return False, "channel signature is not valid base64"
    if len(sig) != 64:
        return False, f"channel signature is {len(sig)} bytes, not 64"
    message = canonical_channel_bytes(channel)
    for key in keys:
        try:
            raw = base64.b64decode(key.strip(), validate=True)
        except Exception:
            continue
        if len(raw) != 32:
            continue
        if ed25519.verify(raw, message, sig):
            return True, release_pubkey.pubkey_id(key)
    return False, "no configured release public key verifies this channel"


def verify_feed_dir(feed_dir: Path, pubkeys=None) -> tuple[bool, list[str]]:
    """Offline self-check: the channel signature AND every package record's
    signature, against the SAME baked pubkeys a real dashboard/companion
    trusts (release_pubkey.RELEASE_PUBKEYS) unless a caller overrides them --
    a channel this fails to verify would be refused by every customer's
    dashboard too."""
    pubkeys = release_pubkey.RELEASE_PUBKEYS if pubkeys is None else pubkeys
    report: list[str] = []
    ok = True
    channel_path = feed_dir / CHANNEL_FILENAME
    sig_path = feed_dir / SIG_FILENAME
    if not channel_path.is_file() or not sig_path.is_file():
        return False, [f"{feed_dir} has no {CHANNEL_FILENAME}/{SIG_FILENAME}"]
    channel = json.loads(channel_path.read_text(encoding="utf-8"))
    signature = sig_path.read_text(encoding="utf-8").strip()
    cok, cdetail = verify_channel_signature(channel, signature, pubkeys)
    report.append(f"channel signature: {'OK' if cok else 'FAILED'} ({cdetail})")
    ok = ok and cok
    for record in channel.get("packages", []):
        rok, rdetail = release_pubkey.verify_record(record, record.get("signature", ""), pubkeys=pubkeys)
        label = f"{record.get('kind')}/{record.get('platform')} {record.get('version')}"
        report.append(f"record {label}: {'OK' if rok else 'FAILED'} ({rdetail})")
        ok = ok and rok
        artifact = feed_dir / str(record.get("platform", "")) / str(record.get("filename", ""))
        if artifact.is_file():
            import hashlib
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if digest != record.get("sha256"):
                report.append(f"record {label}: artifact on disk does NOT match sha256 -- FAILED")
                ok = False
        else:
            report.append(f"record {label}: artifact not present locally (fine if already uploaded)")
    return ok, report


def _apply_manifest(args: argparse.Namespace, manifest: dict, manifest_dir: Path) -> None:
    """Same gate as tools/publish_package.py's apply_manifest -- OPS-1
    applies to the feed path too."""
    if manifest.get("git_dirty") and not args.allow_dirty:
        raise PublishFeedError(
            "manifest says git_dirty=true -- this build came from an uncommitted tree; "
            "nobody can reproduce it. --allow-dirty overrides for a deliberate hotfix.",
            EXIT_CONDEMNED)
    if manifest.get("tests_run") is False and not args.allow_untested:
        raise PublishFeedError(
            "manifest says tests_run=false -- publishing an untested build to the feed "
            "is the failure OPS-1 exists to prevent. --allow-untested overrides.",
            EXIT_CONDEMNED)
    if not args.version:
        args.version = str(manifest.get("version") or "")
    if not args.platform:
        args.platform = str(manifest.get("platform") or "")
    if not args.artifact:
        name = str(manifest.get("artifact") or "")
        if name:
            args.artifact = str(manifest_dir / name)
    if args.signed_binary is None and "signed_binary" in manifest:
        args.signed_binary = bool(manifest.get("signed_binary"))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", default="")
    ap.add_argument("--manifest", default="", help="ccsync-release.json; fills version/platform/artifact/signed_binary")
    ap.add_argument("--kind", default="companion", choices=sign_release.KINDS)
    ap.add_argument("--platform", default="", choices=("",) + sign_release.PLATFORMS)
    ap.add_argument("--version", default="")
    ap.add_argument("--min-version", default="0.0.0")
    ap.add_argument("--published-at", default="")
    ap.add_argument("--signed-binary", dest="signed_binary", action="store_true", default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--feed-dir", default="")
    ap.add_argument("--base-url", default="", help="https://... this feed will be served from")
    ap.add_argument("--channel", default=DEFAULT_CHANNEL_NAME)
    ap.add_argument("--set-image", default="", help="tag@digest for dashboard_image")
    ap.add_argument("--verify", default="", help="offline-verify an existing feed dir and exit")
    ap.add_argument("--key", default="", help="release key file (default ~/.ccsync-release/release.key)")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--allow-untested", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = sys.stdout
    try:
        if args.verify:
            ok, report = verify_feed_dir(Path(args.verify).expanduser())
            for line in report:
                print(line, file=out)
            print("VERIFY OK" if ok else "VERIFY FAILED", file=out)
            return EXIT_OK if ok else EXIT_SELF_VERIFY_FAILED

        if not args.feed_dir:
            raise PublishFeedError("--feed-dir is required (or use --verify)", EXIT_USAGE)
        feed_dir = Path(args.feed_dir).expanduser()

        if args.manifest:
            mpath = Path(args.manifest).expanduser()
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            _apply_manifest(args, manifest, mpath.parent)

        channel = load_channel(feed_dir, args.channel)
        published_something = False

        if args.artifact:
            missing = [n for n, v in (("--platform", args.platform), ("--version", args.version),
                                      ("--base-url", args.base_url)) if not v]
            if missing:
                raise PublishFeedError("missing: " + ", ".join(missing), EXIT_USAGE)
            artifact = Path(args.artifact).expanduser()
            if not artifact.is_file():
                raise PublishFeedError(f"no artifact at {artifact}", EXIT_USAGE)
            signed = _sign_artifact(
                artifact, kind=args.kind, platform=args.platform, version=args.version,
                min_version=args.min_version, signed_binary=bool(args.signed_binary),
                published_at=args.published_at, key=args.key,
            )
            record = {k: signed[k] for k in release_pubkey.RECORD_FIELDS}
            record["signature"] = signed["signature"]
            record["pubkey_id"] = signed["pubkey_id"]
            base = args.base_url.rstrip("/")
            record["url"] = f"{base}/{args.platform}/{record['filename']}"
            record["notes"] = args.notes
            print(f"[publish-feed] signed {args.kind}/{args.platform} v{args.version} "
                  f"(pubkey_id {signed['pubkey_id']}, min_version {signed['min_version']})", file=out)
            upsert_record(channel, record)
            published_something = True
            if not args.dry_run:
                dest_dir = feed_dir / args.platform
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(artifact, dest_dir / record["filename"])

        if args.set_image:
            if "@" not in args.set_image:
                raise PublishFeedError("--set-image must look like tag@sha256:...", EXIT_USAGE)
            tag, digest = args.set_image.split("@", 1)
            channel["dashboard_image"] = {"tag": tag, "digest": digest}
            print(f"[publish-feed] dashboard_image = {tag}@{digest}", file=out)
            published_something = True

        if not published_something:
            raise PublishFeedError("nothing to do -- pass --artifact/--manifest and/or --set-image", EXIT_USAGE)

        if args.dry_run:
            print("[dry-run] channel would be:", file=out)
            print(json.dumps(channel, indent=2, sort_keys=True), file=out)
            return EXIT_OK

        channel["schema"] = SCHEMA
        channel["channel"] = args.channel
        channel["generated_at"] = sign_release.utcnow_iso()
        write_channel(feed_dir, channel, key_path=args.key)
        print(f"[publish-feed] wrote {feed_dir / CHANNEL_FILENAME} and .sig "
              f"({len(channel.get('packages', []))} package record(s))", file=out)
        print("[publish-feed] this tool never uploads. Two one-liners that do "
              "(docs/RELEASE_FEED.md):", file=out)
        print(f"  gh release upload {args.channel}-v1 {feed_dir}\\{CHANNEL_FILENAME} "
              f"{feed_dir}\\{SIG_FILENAME} {feed_dir}\\*\\* --clobber -R ccsync/ccsync-releases", file=out)
        print(f"  rclone sync {feed_dir} remote:ccsync-releases --checksum", file=out)
        return EXIT_OK
    except PublishFeedError as exc:
        print(f"[publish-feed] FAILED: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
