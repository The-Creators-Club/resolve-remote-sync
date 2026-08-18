#!/usr/bin/env python3
r"""Build, sign and (optionally) publish the vendor release feed.

Why this exists (2026-08-17, ZERO_TOUCH_PLAN.md WP E, part 2). Today a
customer's dashboard learns about a new build only from a human PUTting
bytes into THAT dashboard (tools/publish_package.py). This tool is the other
half: it assembles the STATIC files a feed host serves --

    <feed-dir>/channel.json          the signed manifest (docs/RELEASE_FEED.md)
    <feed-dir>/channel.json.sig      detached Ed25519 signature over it
    <feed-dir>/<platform>/<file>     the artefacts themselves

-- on disk, using the SAME offline release key and the SAME per-record
signing tools/sign_release.py already uses (imported and called, never
re-implemented here: a second signer would be a second place for the record
shape to drift).

Publishing (2026-08-18): the owner chose GitHub Releases as the feed host, so
the upload is part of this tool rather than a one-liner a human is trusted to
remember. It is still OPT-IN and never a side effect -- building a feed dir to
look at it must not push anything to the world:

    --github-repo OWNER/REPO   where it goes; also DERIVES --base-url
    --github-tag TAG           the release holding the assets (default below)
    --github-upload            actually shell out to `gh`. Without this flag
                               nothing leaves the rig, exactly as before.

The channel is SIGNED FIRST and uploaded after -- record URLs live inside the
signed document, so an upload that landed the bytes somewhere else could not be
corrected without re-signing (github_asset_plan() refuses that mismatch). The
RELEASE KEY ITSELF NEVER GOES NEAR GITHUB: only channel.json, its detached
signature and the artefacts are uploaded, and the only credential involved is
the operator's own `gh` login. Non-GitHub hosts are unchanged -- give a
--base-url and copy the directory yourself:

    rclone sync <feed-dir> remote:ccsync-releases --checksum

which docs/RELEASE_FEED.md documents in full.

    python tools/publish_feed.py --artifact companion/dist/ccsync-companion.exe \
        --kind companion --platform windows --version 0.8.0 --min-version 0.7.12 \
        --signed-binary --notes "first zero-touch build" \
        --feed-dir .\feed --github-repo ccsync/ccsync-releases --github-upload

    python tools/publish_feed.py --manifest companion\dist\ccsync-release.json \
        --feed-dir .\feed --base-url https://releases.ccsync.app/v1

    python tools/publish_feed.py --set-image 1.2.3@sha256:deadbeef... --feed-dir .\feed

    python tools/publish_feed.py --verify .\feed

Exit codes: 2 usage, 3 the manifest condemned the build (dirty/untested,
unless overridden), 4 the freshly-written feed failed its own offline
verification (should never happen -- see main()), 5 the feed was signed and
written but the upload failed (nothing partial is ever reported as success).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

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
EXIT_UPLOAD_FAILED = 5

SCHEMA = 1
DEFAULT_CHANNEL_NAME = "stable"

# NON-PACKAGE artefacts the feed also carries (2026-08-18,
# docs/MUSIC_INGEST_PLAN.md step 3). A package record is a thing a dashboard
# INSTALLS -- it is per-platform, it is signed individually with
# `sign_release`, and `package_store` verifies that signature again before it
# reaches `companion_packages`. The CLAP audio tower is none of those things:
# it is one platform-independent file that a COMPANION downloads and verifies
# against a sha256 baked into the binary it is already running, so it needs a
# published URL and a size and nothing else.
#
# So it rides a separate top-level `artefacts` list rather than being squeezed
# into `packages`:
#   * it is covered by the CHANNEL signature (the whole document is signed),
#     so nobody can add or move one without the offline key;
#   * `release_feed.py` reads `schema` and `packages` and ignores everything
#     else, so an existing dashboard is unaffected -- no migration, no version
#     bump, and a customer on an older image simply does not see it;
#   * it cannot be mistaken for something to install, which is the failure a
#     `kind: "model"` inside `packages` would eventually cause.
ARTEFACT_KINDS = ("music-clap-audio",)
CHANNEL_FILENAME = "channel.json"
SIG_FILENAME = "channel.json.sig"

# One long-lived release holds every asset, re-uploaded with --clobber every
# ship: the feed is a mutable POINTER, not a per-version archive (a customer
# dashboard only ever reads the current channel.json). Versioned in the tag
# name so a future schema 2 can be published beside it without disturbing
# anyone still reading v1.
DEFAULT_GITHUB_TAG = "ccsync-releases-v1"

# POSIX "command not found". The real runner maps a FileNotFoundError onto it
# so "gh is not installed" is an ordinary return value -- which is what lets
# tools/tests/test_publish_feed.py exercise that path with a fake runner on a
# machine that does happen to have gh.
GH_NOT_FOUND = 127

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


def upsert_artefact(channel: dict[str, Any], artefact: dict[str, Any]) -> None:
    """Replace-or-append by (kind, filename), NOT by (kind, version): the
    version is in the filename precisely so two artefacts can coexist on the
    feed during a migration, and an editor still running the old companion
    must keep finding the file its baked sha256 belongs to."""
    key = (artefact["kind"], artefact["filename"])
    artefacts = channel.setdefault("artefacts", [])
    for i, existing in enumerate(artefacts):
        if (existing.get("kind"), existing.get("filename")) == key:
            artefacts[i] = artefact
            return
    artefacts.append(artefact)


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    for artefact in channel.get("artefacts", []):
        # No per-record signature to check here (see ARTEFACT_KINDS): these are
        # covered by the channel signature above, and the CONSUMER verifies the
        # sha256 against the one baked into its own binary. What can be checked
        # offline is that the bytes on this rig are the bytes the channel
        # claims -- a mismatch would publish a file every companion refuses.
        label = f"artefact {artefact.get('kind')} {artefact.get('filename')}"
        local = feed_dir / str(artefact.get("filename", ""))
        if not local.is_file():
            report.append(f"{label}: not present locally (fine if already uploaded)")
            continue
        if _sha256_file(local) != artefact.get("sha256"):
            report.append(f"{label}: file on disk does NOT match sha256 -- FAILED")
            ok = False
        elif local.stat().st_size != artefact.get("size_bytes"):
            report.append(f"{label}: file on disk is not size_bytes -- FAILED")
            ok = False
        else:
            report.append(f"{label}: OK")
    return ok, report


# ---------------------------------------------------------------------------
# GitHub Releases publishing (2026-08-18)
# ---------------------------------------------------------------------------
# Everything below shells out to `gh` and NOTHING ELSE: no token is read here,
# no API is spoken directly, and the offline release key is never passed to,
# named in, or uploaded by any of it. The key signs on this rig and stays on
# this rig (docs/RELEASE_FEED.md §5, "CI never holds the release key") -- what
# travels to GitHub is only the already-signed channel, its detached signature
# and the artefacts.

Runner = Callable[[list[str]], tuple[int, str, str]]


def run_command(argv: list[str]) -> tuple[int, str, str]:
    """The real runner: (returncode, stdout, stderr). Injected as a parameter
    everywhere below so the tests can assert on argv without gh installed and
    without a network."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return GH_NOT_FOUND, "", f"{argv[0]} not found on PATH"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def github_base_url(repo: str, tag: str) -> str:
    """Where a GitHub release asset is actually served from. Deriving this
    rather than asking for it is the point: the URL is baked into the signed
    channel, so a hand-typed one that disagrees with the upload target is a
    channel nobody can fix without the offline key."""
    return f"https://github.com/{repo}/releases/download/{tag}"


def _validate_repo(repo: str) -> str:
    repo = repo.strip().strip("/")
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        raise PublishFeedError(
            f"--github-repo must be OWNER/REPO, got {repo!r}", EXIT_USAGE)
    return repo


def github_asset_plan(feed_dir: Path, channel: dict[str, Any], *, base_url: str) -> list[Path]:
    """The exact files to upload, refusing anything whose signed URL does not
    match where the bytes will land.

    A GitHub release is ONE FLAT asset namespace per tag -- an asset name
    cannot contain '/', and an upload is named after the local file's
    basename. So every record's `url` must be exactly <base>/<filename>, and
    two records must never share a filename (the second upload would silently
    clobber the first and serve one platform's bytes under both records'
    hashes). Both are checked here, BEFORE anything is pushed, because the url
    is inside the signed document: getting it wrong is not a re-upload away
    from correct, it is a re-sign away."""
    base = base_url.rstrip("/")
    files = [feed_dir / CHANNEL_FILENAME, feed_dir / SIG_FILENAME]
    seen: dict[str, str] = {}
    for record in channel.get("packages", []):
        label = f"{record.get('kind')}/{record.get('platform')} {record.get('version')}"
        filename = str(record.get("filename") or "")
        expected = f"{base}/{filename}"
        if str(record.get("url") or "") != expected:
            raise PublishFeedError(
                f"record {label} is signed with url {record.get('url')!r} but its asset would "
                f"land at {expected!r} -- refusing to upload a signed channel that points "
                "somewhere the bytes are not (re-run the build against this --github-repo/"
                "--github-tag so the record is signed with the right url)", EXIT_USAGE)
        if filename in seen:
            raise PublishFeedError(
                f"records {seen[filename]} and {label} both claim the asset name {filename!r} -- "
                "one would clobber the other in the release's flat asset list", EXIT_USAGE)
        seen[filename] = label
        local = feed_dir / str(record.get("platform") or "") / filename
        if local.is_file():
            files.append(local)
    for artefact in channel.get("artefacts", []):
        label = f"artefact {artefact.get('kind')}"
        filename = str(artefact.get("filename") or "")
        expected = f"{base}/{filename}"
        if str(artefact.get("url") or "") != expected:
            raise PublishFeedError(
                f"{label} is signed with url {artefact.get('url')!r} but its asset would land "
                f"at {expected!r} -- refusing to upload a signed channel that points somewhere "
                "the bytes are not", EXIT_USAGE)
        if filename in seen:
            raise PublishFeedError(
                f"records {seen[filename]} and {label} both claim the asset name {filename!r} -- "
                "one would clobber the other in the release's flat asset list", EXIT_USAGE)
        seen[filename] = label
        local = feed_dir / filename
        if local.is_file():
            files.append(local)
    return files


def github_upload(feed_dir: Path, channel: dict[str, Any], *, repo: str, tag: str,
                  base_url: str, runner: Runner, out) -> None:
    """Sign-then-upload, idempotently. Re-running a ship re-uploads the same
    asset names with --clobber on purpose: the feed is republished every
    release and the tag is stable."""
    files = github_asset_plan(feed_dir, channel, base_url=base_url)
    for record in channel.get("packages", []):
        local = feed_dir / str(record.get("platform") or "") / str(record.get("filename") or "")
        if not local.is_file():
            print(f"[publish-feed] NOTE: {local.name} is not in this feed dir -- assuming the "
                  "release already carries it from an earlier run", file=out)

    rc, _stdout, stderr = runner(["gh", "auth", "status"])
    if rc == GH_NOT_FOUND:
        raise PublishFeedError(
            "gh (the GitHub CLI) is not on PATH -- install it from https://cli.github.com, "
            "run `gh auth login`, then re-run with --github-upload. The feed directory is "
            "already written and signed; nothing was uploaded.", EXIT_UPLOAD_FAILED)
    if rc != 0:
        raise PublishFeedError(
            f"`gh auth status` exited {rc} -- run `gh auth login` (a token with write access to "
            f"{repo}). The feed directory is already written and signed; nothing was uploaded."
            + (f"\n{stderr.strip()}" if stderr.strip() else ""), EXIT_UPLOAD_FAILED)

    rc, _stdout, _stderr = runner(["gh", "release", "view", tag, "-R", repo])
    if rc != 0:
        print(f"[publish-feed] release {tag} not found in {repo} -- creating it", file=out)
        rc, stdout, stderr = runner([
            "gh", "release", "create", tag, "-R", repo,
            "--title", f"CC Sync release feed ({tag})",
            "--notes", "Vendor release feed -- docs/RELEASE_FEED.md. The assets here are "
                       "republished every release; trust comes from channel.json.sig, never "
                       "from this host.",
        ])
        # A concurrent ship (or a `release view` that failed for a reason other
        # than absence) can leave the release already there; that is success,
        # not a collision to abort on.
        if rc != 0 and "already exists" not in (stdout + stderr).lower():
            raise PublishFeedError(
                f"`gh release create {tag}` exited {rc} -- nothing was uploaded."
                + (f"\n{(stderr or stdout).strip()}" if (stderr or stdout).strip() else ""),
                EXIT_UPLOAD_FAILED)

    argv = ["gh", "release", "upload", tag] + [str(p) for p in files] + ["--clobber", "-R", repo]
    rc, stdout, stderr = runner(argv)
    if rc != 0:
        raise PublishFeedError(
            f"`gh release upload` exited {rc} -- the release may now be PARTIALLY updated; "
            f"re-run the same command (it is idempotent: --clobber) once the cause is fixed."
            + (f"\n{(stderr or stdout).strip()}" if (stderr or stdout).strip() else ""),
            EXIT_UPLOAD_FAILED)
    print(f"[publish-feed] uploaded {len(files)} file(s) to {repo} release {tag}", file=out)
    print(f"[publish-feed] feed URL for DASH_RELEASE_FEED_URL: {base_url.rstrip('/')}/{CHANNEL_FILENAME}",
          file=out)


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
    ap.add_argument("--base-url", default="", help="https://... this feed will be served from "
                                                   "(derived from --github-repo if omitted)")
    ap.add_argument("--github-repo", default="", help="OWNER/REPO hosting the feed as a GitHub release")
    ap.add_argument("--github-tag", default=DEFAULT_GITHUB_TAG, help=f"release tag (default {DEFAULT_GITHUB_TAG})")
    ap.add_argument("--github-upload", action="store_true",
                    help="actually push to GitHub with `gh`. Deliberately explicit: rebuilding a "
                         "feed dir to inspect it must never publish to the world")
    ap.add_argument("--channel", default=DEFAULT_CHANNEL_NAME)
    ap.add_argument("--asset", default=None, action="append", dest="assets",
                    help="a non-package artefact to publish beside the packages "
                         "(repeatable): the CLAP audio ONNX and its params JSON")
    ap.add_argument("--asset-kind", default=ARTEFACT_KINDS[0], choices=ARTEFACT_KINDS,
                    help="which artefact these files belong to")
    ap.add_argument("--asset-version", default="",
                    help="the artefact version (music_models.MODELS[...]['version'])")
    ap.add_argument("--set-image", default="", help="tag@digest for dashboard_image")
    ap.add_argument("--verify", default="", help="offline-verify an existing feed dir and exit")
    ap.add_argument("--key", default="", help="release key file (default ~/.ccsync-release/release.key)")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--allow-untested", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = run_command) -> int:
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

        if args.github_upload and not args.github_repo:
            raise PublishFeedError("--github-upload needs --github-repo OWNER/REPO", EXIT_USAGE)
        if args.github_repo:
            args.github_repo = _validate_repo(args.github_repo)
            derived = github_base_url(args.github_repo, args.github_tag)
            if args.base_url and args.base_url.rstrip("/") != derived:
                raise PublishFeedError(
                    f"--base-url {args.base_url!r} disagrees with --github-repo/--github-tag "
                    f"({derived!r}) -- a signed channel whose urls point away from the assets is "
                    "worse than no channel at all. Drop --base-url (it is derived) or fix the tag.",
                    EXIT_USAGE)
            if not args.base_url:
                args.base_url = derived
                print(f"[publish-feed] base URL derived from --github-repo: {derived}", file=out)

        if args.manifest:
            mpath = Path(args.manifest).expanduser()
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            _apply_manifest(args, manifest, mpath.parent)

        channel = load_channel(feed_dir, args.channel)
        published_something = False

        if args.artifact:
            missing = [n for n, v in (("--platform", args.platform), ("--version", args.version),
                                      ("--base-url (or --github-repo)", args.base_url)) if not v]
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
            # GitHub releases have no directories: an asset name cannot contain
            # '/', so the <platform>/ segment every other static host gets would
            # name a URL GitHub will never serve (2026-08-18). The LOCAL feed dir
            # keeps the platform sub-directory either way -- verify_feed_dir
            # looks there -- and sign_release.package_filename already makes
            # filenames unique across platforms (the .exe suffix is windows-only),
            # so nothing collides in the flat namespace.
            record["url"] = (f"{base}/{record['filename']}" if args.github_repo
                             else f"{base}/{args.platform}/{record['filename']}")
            record["notes"] = args.notes
            print(f"[publish-feed] signed {args.kind}/{args.platform} v{args.version} "
                  f"(pubkey_id {signed['pubkey_id']}, min_version {signed['min_version']})", file=out)
            upsert_record(channel, record)
            published_something = True
            if not args.dry_run:
                dest_dir = feed_dir / args.platform
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(artifact, dest_dir / record["filename"])

        for asset_path in (args.assets or []):
            if not args.base_url:
                raise PublishFeedError(
                    "--asset needs --base-url (or --github-repo): the URL is part of the "
                    "signed channel, so it cannot be filled in later", EXIT_USAGE)
            if not args.asset_version:
                raise PublishFeedError(
                    "--asset needs --asset-version: the version is what stops two exports "
                    "of the same model being confused for each other", EXIT_USAGE)
            asset = Path(asset_path).expanduser()
            if not asset.is_file():
                raise PublishFeedError(f"no asset at {asset}", EXIT_USAGE)
            base = args.base_url.rstrip("/")
            artefact = {
                "kind": args.asset_kind,
                "version": args.asset_version,
                "filename": asset.name,
                "sha256": _sha256_file(asset),
                "size_bytes": asset.stat().st_size,
                # FLAT, on every host: GitHub Releases has one asset namespace
                # per tag, and the companion's own catalogue builds exactly
                # this shape (music_models.FEED_URL_TEMPLATE).
                "url": f"{base}/{asset.name}",
            }
            print(f"[publish-feed] artefact {artefact['kind']} {asset.name} "
                  f"({artefact['size_bytes']} bytes, sha256 {artefact['sha256'][:16]}...)",
                  file=out)
            print("[publish-feed]   the COMPANION verifies this sha256 against the one baked "
                  "into its own build: if they disagree, publish the artefact that build "
                  "expects or ship a build that expects this one", file=out)
            upsert_artefact(channel, artefact)
            published_something = True
            if not args.dry_run:
                feed_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(asset, feed_dir / asset.name)

        if args.set_image:
            if "@" not in args.set_image:
                raise PublishFeedError("--set-image must look like tag@sha256:...", EXIT_USAGE)
            tag, digest = args.set_image.split("@", 1)
            channel["dashboard_image"] = {"tag": tag, "digest": digest}
            print(f"[publish-feed] dashboard_image = {tag}@{digest}", file=out)
            published_something = True

        if not published_something:
            raise PublishFeedError("nothing to do -- pass --artifact/--manifest, --asset and/or --set-image", EXIT_USAGE)

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

        # Signed and self-verified on disk BEFORE a single byte moves -- the
        # record urls are inside the signed document, so signing can never be
        # the step that follows an upload.
        if args.github_upload:
            github_upload(feed_dir, channel, repo=args.github_repo, tag=args.github_tag,
                          base_url=args.base_url, runner=runner, out=out)
            return EXIT_OK

        if args.github_repo:
            print(f"[publish-feed] built only -- add --github-upload to push it to "
                  f"{args.github_repo} release {args.github_tag}", file=out)
        else:
            print("[publish-feed] nothing was uploaded. Either pass --github-repo "
                  "--github-upload, or copy the directory yourself (docs/RELEASE_FEED.md):", file=out)
            print(f"  rclone sync {feed_dir} remote:ccsync-releases --checksum", file=out)
        return EXIT_OK
    except PublishFeedError as exc:
        print(f"[publish-feed] FAILED: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
