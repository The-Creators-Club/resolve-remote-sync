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

    python tools/publish_feed.py --artifact dist/ccsync-dashboard-0.5.1.tar.gz \
        --kind dashboard --platform linux --version 0.5.1 \
        --feed-dir .\feed --github-repo ccsync/ccsync-releases --github-upload

    python tools/publish_feed.py --set-image 1.2.3@sha256:deadbeef... --feed-dir .\feed

    python tools/publish_feed.py --verify .\feed

    python tools/publish_feed.py --retract companion/windows/0.6.1 \
        --feed-dir .\feed --github-repo ccsync/ccsync-releases --github-upload

THE PUBLISHED CHANNEL IS THE BASE (2026-08-21, release-pipeline-1). With
--github-upload this tool first DOWNLOADS the live channel.json + .sig,
verifies it against the release public keys baked into this checkout, and
merges the new record into THAT -- because the upload is `--clobber` over one
long-lived release asset, and rebuilding from a local feed/ dir that a fresh
clone does not have replaced the whole published history with a single
correctly-signed record. An upload that would remove anything published
refuses unless --allow-shrink; --retract is the deliberate way to withdraw a
bad build.

A RECORD ALREADY ON THE FEED IS PROTECTED TWICE (2026-08-21, CR-59 item 8).
Publishing the same (kind, platform, version) with different bytes refuses
unless --allow-replace, because a dashboard that already installed that
version never fetches it again and the fleet would split in two under one
version number; the answer is a version bump. And a --min-version below the
highest floor already published for that kind/platform refuses unless
--allow-floor-drop, because the usual cause is a forgotten
CCSYNC_MIN_VERSION rather than a decision to drop the floor.

--make-current maintains a top-level `current` map, {"<kind>/<platform>":
"<version>"} (release-pipeline-5): without it a customer dashboard on the
"current" policy replayed the whole channel in APPEND order and the LAST
record won, so republishing an older build offered the fleet a rollback.

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
import tempfile
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
                   min_version: str, signed_binary: bool, published_at: str, key: str,
                   runtime_id: str = "", requires_dashboard: str = "",
                   arch: str = "", git_sha: str = "", git_dirty: str = "") -> dict:
    """Run sign_release.main in-process and capture its JSON -- the SAME
    record shape and the SAME key file tools/sign_release.py uses everywhere
    else, imported rather than duplicated (see the module docstring)."""
    argv = ["--artifact", str(artifact), "--kind", kind, "--platform", platform,
            "--version", version, "--min-version", min_version]
    if runtime_id:
        argv += ["--runtime-id", runtime_id]
    # REL-4 / REL-16 / REL-13 (2026-08-28). Passed through rather than
    # re-derived: sign_release.py owns which of these the signature covers for
    # a given kind, and it refuses a value it would have to drop.
    if requires_dashboard:
        argv += ["--requires-dashboard", requires_dashboard]
    if arch:
        argv += ["--arch", arch]
    if git_sha:
        argv += ["--git-sha", git_sha]
    if git_dirty:
        argv += ["--git-dirty", git_dirty]
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


def bundle_manifest(artifact: Path) -> dict[str, Any]:
    """The `manifest.json` inside a dashboard bundle, or {}.

    Read so `--runtime-id` does not have to be re-typed from the builder's
    output (ZERO_TOUCH_PLAN.md WP K): the value is SIGNED, so a hand-typed one
    that disagrees with the bundle is a channel every customer refuses and
    only the offline key can fix. Best-effort by design -- anything that is
    not a readable tarball with a manifest simply falls back to the flag,
    which then refuses on its own if it is empty."""
    import tarfile

    try:
        with tarfile.open(artifact, "r:gz") as tar:
            member = tar.extractfile("manifest.json")
            if member is None:
                return {}
            data = json.loads(member.read().decode("utf-8"))
    except (OSError, ValueError, KeyError, tarfile.TarError):
        return {}
    return data if isinstance(data, dict) else {}


def load_channel(feed_dir: Path, channel_name: str) -> dict[str, Any]:
    path = feed_dir / CHANNEL_FILENAME
    if not path.is_file():
        return {"schema": SCHEMA, "generated_at": "", "channel": channel_name,
                "pubkey_id": "", "dashboard_image": {"tag": "", "digest": ""}, "packages": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("packages", [])
    data.setdefault("dashboard_image", {"tag": "", "digest": ""})
    return data


def package_keys(channel: dict[str, Any]) -> set[tuple[str, str, str]]:
    """(kind, platform, version) for every package record."""
    return {(str(p.get("kind") or ""), str(p.get("platform") or ""), str(p.get("version") or ""))
            for p in channel.get("packages", [])}


def artefact_keys(channel: dict[str, Any]) -> set[tuple[str, str]]:
    """(kind, filename) for every non-package artefact (see ARTEFACT_KINDS)."""
    return {(str(a.get("kind") or ""), str(a.get("filename") or ""))
            for a in channel.get("artefacts", [])}


def merge_into_published(published: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    """The PUBLISHED channel with the local one merged on top.

    release-pipeline-1 (2026-08-21): this file used to rebuild the channel
    from <feed-dir>/channel.json alone -- a gitignored directory that exists
    on exactly one machine -- and then `gh release upload --clobber` replaced
    the live document with it. Running a publish from a fresh clone, a Mac, a
    new base rig or after a --feed-dir typo therefore replaced 18 package
    records and 2 CLAP artefacts with ONE, correctly signed, so nothing
    logged an error and the loss was discovered by a customer (RELEASE_FEED
    and RELEASE.md: "a feed with no copy of the version the shipped companion
    pins means no editor can ingest music at all").

    The published document is now the BASE and the local one is an overlay:
    anything this rig has that the feed does not is added, anything both have
    is taken from the local copy (that is what a --force republish means), and
    nothing published is ever dropped by omission. dashboard_image and
    `current` are per-key overlays for the same reason.
    """
    merged = json.loads(json.dumps(published))  # deep copy; plain JSON throughout
    for record in local.get("packages", []):
        upsert_record(merged, record)
    for artefact in local.get("artefacts", []):
        upsert_artefact(merged, artefact)
    image = local.get("dashboard_image") or {}
    if image.get("tag") or image.get("digest"):
        merged["dashboard_image"] = image
    current = dict(merged.get("current") or {})
    current.update({k: v for k, v in (local.get("current") or {}).items() if v})
    if current:
        merged["current"] = current
    # A recall is only ever ADDED to (REL-3, 2026-08-28): a publish run from a
    # fresh clone whose feed dir knows nothing about last month's withdrawal
    # must not un-retract it -- that would re-offer the exact build the vendor
    # pulled, correctly signed, under every feed policy.
    for entry in local.get("retracted", []):
        note_retracted(merged, str(entry.get("kind") or ""), str(entry.get("platform") or ""),
                       str(entry.get("version") or ""), str(entry.get("reason") or ""),
                       str(entry.get("at") or ""))
    return merged


def shrink_report(published: dict[str, Any], candidate: dict[str, Any],
                  allowed_removals: set[tuple[str, str, str]] | None = None) -> list[str]:
    """What the candidate channel would REMOVE from the published one.

    A non-empty list is a refusal (release-pipeline-1): the feed is a mutable
    pointer republished in full every ship, so an upload that drops records is
    indistinguishable, to every customer, from those builds never having
    existed. `allowed_removals` is what --retract deliberately took out.
    """
    allowed = allowed_removals or set()
    lost_packages = sorted(package_keys(published) - package_keys(candidate) - allowed)
    lost_artefacts = sorted(artefact_keys(published) - artefact_keys(candidate))
    report = [f"package {kind}/{platform} {version}" for kind, platform, version in lost_packages]
    report += [f"artefact {kind} {filename}" for kind, filename in lost_artefacts]
    return report


def existing_package(channel: dict[str, Any], kind: str, platform: str,
                     version: str) -> dict[str, Any] | None:
    """The record this channel already carries for that exact key, if any."""
    for record in channel.get("packages", []):
        if (str(record.get("kind") or ""), str(record.get("platform") or ""),
                str(record.get("version") or "")) == (kind, platform, version):
            return record
    return None


def published_floor(channel: dict[str, Any], kind: str, platform: str) -> str:
    """The HIGHEST min_version this channel already publishes for (kind, platform).

    Highest rather than newest on purpose (CR-59 item 8, 2026-08-21): a
    companion's floor is monotonic and persistent -- once it has SEEN a
    record demanding 0.9.44 it will never install below 0.9.44 again -- so
    the fleet's real floor is the maximum ever published, whatever order the
    records went out in. A record published under it is not dangerous the way
    CR-52's inverted record was; it is a policy decision quietly undone, and
    the operator who forgot to pass --min-version this time should be told
    rather than left to find out when a rollback they thought was blocked
    goes through on a fresh dashboard.
    """
    best = ""
    for record in channel.get("packages", []):
        if (str(record.get("kind") or ""), str(record.get("platform") or "")) != (kind, platform):
            continue
        candidate = str(record.get("min_version") or "")
        if sign_release.version_tuple(candidate) > sign_release.version_tuple(best):
            best = candidate
    return best


def current_version(channel: dict[str, Any], kind: str, platform: str) -> str:
    """The version this channel points `current` at for (kind, platform)."""
    return str((channel.get("current") or {}).get(f"{kind}/{platform}") or "")


def baked_keys_of_current(channel: dict[str, Any], kind: str, platform: str) -> tuple[str, list]:
    """(version, baked pubkey ids) of the record customers are on today.

    Empty list when the current record predates REL-7 and carries no list --
    "could not check" is then said out loud rather than passed as a check.
    """
    version = current_version(channel, kind, platform)
    if not version:
        return "", []
    record = existing_package(channel, kind, platform, version) or {}
    ids = record.get("baked_pubkey_ids")
    if isinstance(ids, str):
        ids = [part.strip() for part in ids.split(",") if part.strip()]
    return version, [str(i) for i in (ids or [])]


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


def require_gh_auth(repo: str, runner: Runner) -> None:
    """`gh auth status`, once per run, before anything touches the release.

    Moved out of github_upload on 2026-08-21: the credential is needed by the
    DOWNLOAD of the published channel too, which now happens first."""
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


def fetch_published_channel(repo: str, tag: str, *, runner: Runner, dest: Path,
                            out) -> tuple[dict[str, Any] | None, str, str]:
    """Download the LIVE channel.json + .sig from the release, or say why not.

    Returns (channel, signature, status) where status is one of:
        "ok"      -- both files came down and are parseable
        "absent"  -- the release (or the asset) does not exist yet, i.e. this
                     is a legitimate first publish
        anything else -- an error string; the caller must NOT publish, because
                     it cannot tell "nothing is published" from "I could not
                     ask", and `gh release upload --clobber` replaces whatever
                     is there (release-pipeline-1, 2026-08-21).

    Not urllib: the same `gh` credential and the same injected runner as every
    other call here, so the tests exercise this path with a fake and no
    network. The signature is NOT verified here -- main() does that against
    the baked pubkeys, so the refusal message can name the key.
    """
    dest.mkdir(parents=True, exist_ok=True)
    rc, stdout, stderr = runner([
        "gh", "release", "download", tag, "-R", repo,
        "--pattern", CHANNEL_FILENAME, "--pattern", SIG_FILENAME,
        "--dir", str(dest), "--clobber",
    ])
    if rc == GH_NOT_FOUND:
        return None, "", "gh (the GitHub CLI) is not on PATH"
    channel_path = dest / CHANNEL_FILENAME
    sig_path = dest / SIG_FILENAME
    if not channel_path.is_file():
        text = f"{stdout}\n{stderr}".lower()
        # `gh` says one of these when the release or the asset is not there.
        # Any OTHER non-zero exit is a network/auth problem and must not be
        # mistaken for "the feed is empty".
        if rc == 0 or "no assets match" in text or "release not found" in text or "not found" in text:
            print(f"[publish-feed] no published {CHANNEL_FILENAME} in {repo} release {tag} "
                  "-- treating this as the first publish", file=out)
            return None, "", "absent"
        return None, "", f"`gh release download` exited {rc}: {(stderr or stdout).strip()}"
    try:
        channel = json.loads(channel_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, "", f"the published {CHANNEL_FILENAME} is not valid JSON ({exc})"
    if not isinstance(channel, dict):
        return None, "", f"the published {CHANNEL_FILENAME} is not an object"
    signature = sig_path.read_text(encoding="utf-8").strip() if sig_path.is_file() else ""
    channel.setdefault("packages", [])
    return channel, signature, "ok"


def set_current(channel: dict[str, Any], kind: str, platform: str, version: str) -> None:
    """Point `current` at one record (release-pipeline-5, 2026-08-21).

    The channel had no current pointer at all, so a dashboard on the "current"
    policy replayed the WHOLE history in append order and whichever record
    happened to be last won -- append order, not version order, so a --force
    republish of an older build offered the entire fleet a rollback. One
    pointer per (kind, platform), maintained here and honoured by
    dashboard/src/ccsync_dashboard/release_feed.py.
    """
    current = dict(channel.get("current") or {})
    current[f"{kind}/{platform}"] = version
    channel["current"] = current


def retracted_keys(channel: dict[str, Any]) -> set[tuple[str, str, str]]:
    """(kind, platform, version) for every entry on the signed recall list."""
    return {(str(r.get("kind") or ""), str(r.get("platform") or ""),
             str(r.get("version") or "")) for r in channel.get("retracted", [])}


def note_retracted(channel: dict[str, Any], kind: str, platform: str, version: str,
                   reason: str, at: str) -> None:
    """Add one entry to the channel's signed `retracted` list (REL-3, 2026-08-28).

    Removing the record (retract_record, below) stops the feed OFFERING the
    build. It does not reach a customer dashboard that already published it
    locally: on the default `manual` feed policy that dashboard never acts on
    the channel again, so a bad build stayed `is_current` for its whole fleet
    and recovery was one [ UPDATE NOW ] click per editor. This list is what
    the dashboard reads under EVERY policy to un-current the row, refuse to
    serve it and show the admin WHY -- so the reason travels with the
    withdrawal, signed, rather than living in a release note nobody fetches.

    Replace-or-append by (kind, platform, version): re-retracting with a
    better reason must not leave two entries disagreeing about one build.
    """
    entry = {"kind": kind, "platform": platform, "version": version,
             "reason": reason, "at": at}
    entries = channel.setdefault("retracted", [])
    for i, existing in enumerate(entries):
        if ((existing.get("kind"), existing.get("platform"), existing.get("version"))
                == (kind, platform, version)):
            entries[i] = entry
            return
    entries.append(entry)


def retract_record(channel: dict[str, Any], kind: str, platform: str,
                   version: str) -> bool:
    """Remove one package record and any `current` pointer at it.

    The other half of release-pipeline-5: a bad build (the 0.6.1
    proxy-generator shape) could not be withdrawn from feed customers at all,
    because upsert_record only ever appended or replaced in place. The ASSET
    is deliberately left on the release: an older dashboard that already holds
    the record must keep being able to fetch the bytes it verified.
    """
    packages = channel.setdefault("packages", [])
    before = len(packages)
    channel["packages"] = [
        p for p in packages
        if (p.get("kind"), p.get("platform"), p.get("version")) != (kind, platform, version)
    ]
    current = dict(channel.get("current") or {})
    if current.get(f"{kind}/{platform}") == version:
        current.pop(f"{kind}/{platform}")
        channel["current"] = current
    return len(channel["packages"]) != before


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

    # `gh auth status` ran HERE until 2026-08-21. It now runs once, up front
    # in main() (require_gh_auth), because the very first thing an upload run
    # does is DOWNLOAD the published channel to merge into -- and that needs
    # the same credential (release-pipeline-1).
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
    # The builder MEASURED these; retyping them is how a signed record ends up
    # describing a different build than the one in hand (the --runtime-id
    # lesson, WP K). REL-4 / REL-16 / REL-13, 2026-08-28.
    if not args.requires_dashboard:
        args.requires_dashboard = str(manifest.get("requires_dashboard") or "")
    if not args.arch:
        # Normalised, and dropped when it is not a value the record knows: the
        # builders measure it with `uname -m` / PROCESSOR_ARCHITECTURE, which
        # can legitimately say "unknown" on an old manifest, and an arch
        # nothing recognises must degrade to "offer it to everyone" rather
        # than make the build unpublishable (REL-16, 2026-08-28).
        measured = str(manifest.get("arch") or "").strip().lower()
        measured = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64",
                    "universal": "universal2"}.get(measured, measured)
        if measured and measured not in sign_release.ARCHITECTURES:
            print(f"[publish-feed] NOTE: the manifest says arch={measured!r}, which is not "
                  f"one of {', '.join(sign_release.ARCHITECTURES)} -- publishing without an "
                  "arch, i.e. offered to every machine on that platform (REL-16).",
                  file=sys.stdout)
            measured = ""
        args.arch = measured
    if not args.git_sha:
        args.git_sha = str(manifest.get("git_commit") or "")
    if not args.git_dirty and "git_dirty" in manifest:
        args.git_dirty = "1" if manifest.get("git_dirty") else "0"
    if not args.baked_pubkey_ids:
        ids = manifest.get("baked_pubkey_ids") or []
        if isinstance(ids, str):
            ids = [part for part in ids.split(",") if part.strip()]
        args.baked_pubkey_ids = ",".join(str(i).strip() for i in ids if str(i).strip())


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", default="")
    ap.add_argument("--manifest", default="", help="ccsync-release.json; fills version/platform/artifact/signed_binary")
    ap.add_argument("--kind", default="companion", choices=sign_release.KINDS)
    ap.add_argument("--platform", default="", choices=("",) + sign_release.PLATFORMS)
    ap.add_argument("--version", default="")
    ap.add_argument("--min-version", default="0.0.0")
    ap.add_argument("--published-at", default="")
    ap.add_argument("--runtime-id", default="",
                    help="--kind dashboard only: the image runtime the bundle was built "
                         "against (tools/build_dashboard_bundle.py prints it). Signed.")
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
    ap.add_argument("--make-current", action="store_true",
                    help="point the channel's `current` at the record published by this run "
                         "(release-pipeline-5). Without it the record is STAGED: a customer "
                         "dashboard on the 'current' policy keeps offering what it offers now.")
    ap.add_argument("--retract", default="",
                    help="KIND/PLATFORM/VERSION to REMOVE from the channel (a bad build). "
                         "The asset stays on the release; only the record and any `current` "
                         "pointer at it go. Combine with nothing else and it is a pure "
                         "withdrawal.")
    ap.add_argument("--reason", default="",
                    help="why a --retract happened, in one sentence an admin will read on "
                         "the Packages page of every customer dashboard. Required with "
                         "--retract: a recall with no reason gets ignored (REL-3).")
    ap.add_argument("--requires-dashboard", default="",
                    help="the oldest dashboard VERSION this build works against; SIGNED into "
                         "the record. Read from the manifest when --manifest is given (REL-4)")
    ap.add_argument("--arch", default="", choices=("",) + sign_release.ARCHITECTURES,
                    help="the architecture the artifact runs on; SIGNED. From the manifest "
                         "when --manifest is given (REL-16)")
    ap.add_argument("--git-sha", default="",
                    help="short commit the build came from. UNSIGNED provenance (REL-13)")
    ap.add_argument("--git-dirty", default="", choices=("", "0", "1"),
                    help="1 when the build came from an uncommitted tree (REL-13)")
    ap.add_argument("--baked-pubkey-ids", default="",
                    help="comma-separated pubkey ids the ARTIFACT itself trusts "
                         "(tools/release.ps1 writes them into the manifest). Recorded on "
                         "the channel so the NEXT publish can tell whether the fleet on "
                         "the current build would accept a build signed with this key (REL-7)")
    ap.add_argument("--allow-key-rotation", action="store_true",
                    help="publish even though the signing key is not one the CURRENT build "
                         "bakes in. A deliberate rotation, and it costs an overlap release: "
                         "every machine still on the current build refuses this one (REL-7)")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="permit an upload whose package/artefact set is a strict subset of "
                         "the published one. Needed only when you MEAN to drop records; "
                         "without it a feed dir missing history refuses rather than "
                         "clobbering the live channel with it.")
    # CR-59 item 8 (2026-08-21): the two refusals that protect a record which
    # is ALREADY on the feed. Both are per-run overrides, never config.
    ap.add_argument("--allow-replace", action="store_true",
                    help="replace an already-published (kind, platform, version) whose bytes "
                         "differ. Almost always the wrong answer: every dashboard that already "
                         "holds that version keeps the old bytes, so the fleet splits in two "
                         "under one version number. Bump the version instead.")
    ap.add_argument("--allow-floor-drop", action="store_true",
                    help="publish a min_version BELOW the highest floor already published for "
                         "this kind/platform. Needed only when the earlier floor was itself the "
                         "mistake.")
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
    tmpdir: tempfile.TemporaryDirectory | None = None
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

        # --- the LIVE channel is the base, not this rig's feed/ dir --------
        # release-pipeline-1 (2026-08-21). Fetched whenever this run could
        # upload, because that upload is `--clobber` over the live document.
        published: dict[str, Any] | None = None
        # A refusal raised only AFTER the local feed dir is written and
        # signed. That order is deliberate and predates this change: "the feed
        # directory is already written and signed; nothing was uploaded" is
        # the promise every gh failure here makes.
        upload_refusal: PublishFeedError | None = None
        if args.github_upload:
            tmpdir = tempfile.TemporaryDirectory(prefix="ccsync-feed-")
            try:
                require_gh_auth(args.github_repo, runner)
                published, published_sig, status = fetch_published_channel(
                    args.github_repo, args.github_tag, runner=runner,
                    dest=Path(tmpdir.name), out=out)
                if status not in ("ok", "absent"):
                    raise PublishFeedError(
                        f"could not read the channel already published at {args.github_repo} "
                        f"({args.github_tag}): {status}.\nRefusing to upload: `gh release upload "
                        "--clobber` REPLACES the live channel, and a run that cannot see what is "
                        "there cannot tell an empty feed from an unreachable one. The feed "
                        "directory is written and signed; nothing was uploaded.",
                        EXIT_UPLOAD_FAILED)
                if published is not None:
                    ok, detail = verify_channel_signature(
                        published, published_sig, release_pubkey.RELEASE_PUBKEYS)
                    if not ok:
                        raise PublishFeedError(
                            f"the channel published at {args.github_repo} does not verify against "
                            f"this build's release public keys: {detail}.\nEither the feed was "
                            "tampered with, or it was signed by a key this checkout does not know "
                            "(rotate with tools/release_key.py bake --add and rebuild). Nothing "
                            "was uploaded.", EXIT_UPLOAD_FAILED)
                    print(f"[publish-feed] published channel read and verified: "
                          f"{len(published.get('packages', []))} package record(s), "
                          f"{len(published.get('artefacts', []))} artefact(s)", file=out)
                    channel = merge_into_published(published, channel)
            except PublishFeedError as exc:
                upload_refusal = exc
                published = None

        published_something = False
        retracted: set[tuple[str, str, str]] = set()

        if args.retract:
            parts = [p for p in args.retract.split("/") if p]
            if len(parts) != 3:
                raise PublishFeedError(
                    f"--retract wants KIND/PLATFORM/VERSION, got {args.retract!r}", EXIT_USAGE)
            if not args.reason.strip():
                # REL-3 (2026-08-28): the reason is the whole difference between
                # a build that vanished and a build the vendor pulled. It is
                # rendered on every customer Packages and Fleet page beside the
                # machines still running it.
                raise PublishFeedError(
                    f"--retract {args.retract} needs --reason: every customer dashboard "
                    "shows it beside the withdrawn build, and an admin whose fleet is "
                    "being rolled back has nothing else to go on.", EXIT_USAGE)
            r_kind, r_platform, r_version = parts
            note_retracted(channel, r_kind, r_platform, r_version,
                           args.reason.strip(), sign_release.utcnow_iso())
            if retract_record(channel, r_kind, r_platform, r_version):
                print(f"[publish-feed] RETRACTED {r_kind}/{r_platform} {r_version} -- it is no "
                      "longer offered, and the recall list now carries the reason so every "
                      "dashboard un-currents it under any feed policy.", file=out)
            else:
                print(f"[publish-feed] NOTE: {args.retract} was not a record on this channel; "
                      "the recall entry is published anyway -- a dashboard that published it "
                      "locally is exactly who needs to hear about it.", file=out)
            print(f"[publish-feed]   reason: {args.reason.strip()}", file=out)
            retracted.add((r_kind, r_platform, r_version))
            published_something = True

        if args.artifact:
            missing = [n for n, v in (("--platform", args.platform), ("--version", args.version),
                                      ("--base-url (or --github-repo)", args.base_url)) if not v]
            if missing:
                raise PublishFeedError("missing: " + ", ".join(missing), EXIT_USAGE)
            artifact = Path(args.artifact).expanduser()
            if not artifact.is_file():
                raise PublishFeedError(f"no artifact at {artifact}", EXIT_USAGE)
            if args.kind in sign_release.RUNTIME_ID_KINDS:
                manifest_in_bundle = bundle_manifest(artifact)
                inside = str(manifest_in_bundle.get("runtime_id") or "")
                if not args.runtime_id and inside:
                    args.runtime_id = inside
                    print(f"[publish-feed] runtime_id read from the bundle: {inside}", file=out)
                elif args.runtime_id and inside and args.runtime_id.strip() != inside:
                    raise PublishFeedError(
                        f"--runtime-id {args.runtime_id!r} disagrees with the bundle's own "
                        f"manifest ({inside!r}) -- the value is SIGNED, so publishing the "
                        "wrong one gives every customer a runtime mismatch nobody can fix "
                        "without the offline key. Drop the flag (it is read from the bundle).",
                        EXIT_USAGE)
            signed = _sign_artifact(
                artifact, kind=args.kind, platform=args.platform, version=args.version,
                min_version=args.min_version, signed_binary=bool(args.signed_binary),
                published_at=args.published_at, key=args.key,
                runtime_id=args.runtime_id.strip(),
                requires_dashboard=args.requires_dashboard.strip(),
                arch=args.arch.strip(),
                git_sha=args.git_sha.strip(), git_dirty=args.git_dirty.strip(),
            )
            # record_fields(kind, signed), not RECORD_FIELDS: a record's
            # signature covers its kind's extras -- runtime_id always for a
            # dashboard bundle, and arch/requires_dashboard when a companion
            # record carries them (2026-08-28) -- and a channel that carried
            # the signature but dropped a field would fail verification at
            # every customer with no way to tell why.
            try:
                fields = release_pubkey.record_fields(args.kind, signed)
            except TypeError:  # a checkout predating the optional extras
                fields = release_pubkey.record_fields(args.kind)
            record = {k: signed[k] for k in fields}
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
            # UNSIGNED at the record level, signed with the channel (REL-13):
            # provenance, so "0.9.55" on a Packages page can say which commit
            # it is, and say +dirty when it is no commit at all.
            if args.git_sha.strip():
                record["git_sha"] = args.git_sha.strip()
            if args.git_dirty.strip():
                record["git_dirty"] = args.git_dirty.strip()
            if args.baked_pubkey_ids.strip():
                record["baked_pubkey_ids"] = [
                    part.strip() for part in args.baked_pubkey_ids.split(",") if part.strip()]
            print(f"[publish-feed] signed {args.kind}/{args.platform} v{args.version} "
                  f"(pubkey_id {signed['pubkey_id']}, min_version {signed['min_version']})", file=out)

            # --- would the fleet on the CURRENT build accept this key? -----
            # REL-7 (2026-08-28). A companion only ever trusts keys baked into
            # the binary it is ALREADY RUNNING, so signing with a key the
            # current build does not carry strands every machine on it: the
            # offer is refused, logged once, the tray says nothing, and there
            # is no over-the-air way back. The one guard that existed compared
            # the signing key against the build being BUILT -- the one place
            # the two can never disagree.
            cur_version, cur_keys = baked_keys_of_current(channel, args.kind, args.platform)
            if cur_keys and signed["pubkey_id"] not in cur_keys:
                if not args.allow_key_rotation:
                    raise PublishFeedError(
                        f"this build is signed with key {signed['pubkey_id']}, which the build "
                        f"currently CURRENT for {args.kind}/{args.platform} (v{cur_version}) "
                        f"does not trust -- it bakes in {', '.join(cur_keys)}.\n"
                        f"EVERY MACHINE ON v{cur_version} WILL REFUSE THIS BUILD, silently and "
                        "permanently: a companion trusts only the keys inside the binary it is "
                        "already running, so the recovery is a hands-on reinstall per machine.\n"
                        "A rotation costs an overlap release: `python tools/release_key.py bake "
                        "--add`, ship THAT (it trusts both keys), and only then drop the old "
                        "one. Pass --allow-key-rotation if this is that deliberate step. "
                        "Nothing was uploaded.",
                        EXIT_USAGE)
                print(f"[publish-feed] WARNING: --allow-key-rotation -- every machine on "
                      f"v{cur_version} will refuse this build (it trusts "
                      f"{', '.join(cur_keys)}, this is signed with {signed['pubkey_id']})",
                      file=out)
            elif cur_version and not cur_keys:
                print(f"[publish-feed] NOTE: v{cur_version} is current for "
                      f"{args.kind}/{args.platform} but records no baked key ids, so the "
                      "key-rotation check could not run (REL-7). Records published from "
                      "2026-08-28 carry them.", file=out)

            # --- what this record would do to one ALREADY on the feed ------
            # CR-59 item 8 (2026-08-21). `channel` here is the published
            # document with this rig's overlay merged on top (or, without
            # --github-upload, the local feed dir), so both checks see the
            # same records a customer's dashboard would. A --retract earlier
            # in this same run has already removed the record, which is the
            # deliberate withdraw-then-republish path and stays open.
            if ((args.kind, args.platform, args.version) in retracted_keys(channel)
                    and (args.kind, args.platform, args.version) not in retracted):
                raise PublishFeedError(
                    f"{args.kind}/{args.platform} {args.version} is on this channel RECALL "
                    "list -- it was withdrawn on purpose and every dashboard has been told to "
                    "stop offering it. Publishing it again re-offers the exact build that was "
                    "pulled. Bump the version, or re-run this command with --retract "
                    f"{args.kind}/{args.platform}/{args.version} --reason ... if the "
                    "withdrawal itself was the mistake. Nothing was uploaded.",
                    EXIT_USAGE)
            prior = existing_package(channel, args.kind, args.platform, args.version)
            if (prior is not None and str(prior.get("sha256") or "") != record["sha256"]
                    and not args.allow_replace):
                raise PublishFeedError(
                    f"{args.kind}/{args.platform} {args.version} is already published with "
                    f"DIFFERENT bytes:\n  published sha256 {prior.get('sha256')}\n  this build  "
                    f"     {record['sha256']}\n"
                    "A dashboard that already installed that version never fetches it again, so "
                    "replacing it in place gives you two different builds wearing one version "
                    "number and no way to tell them apart in the field (the dashboard's own "
                    "publish refuses this too, and the Packages page renders SAME VERSION, "
                    "DIFFERENT BYTES).\n"
                    "Bump VERSION in companion/src/ccsync_companion/config.py AND "
                    "companion/pyproject.toml, rebuild, and publish that. Use --allow-replace "
                    "only to correct a record nothing has downloaded yet. Nothing was uploaded.",
                    EXIT_USAGE)
            floor = published_floor(channel, args.kind, args.platform)
            if (sign_release.version_tuple(record["min_version"])
                    < sign_release.version_tuple(floor) and not args.allow_floor_drop):
                raise PublishFeedError(
                    f"--min-version {record['min_version']} is BELOW the highest floor already "
                    f"published for {args.kind}/{args.platform} ({floor}).\n"
                    "Every companion that has seen the earlier record remembers that floor for "
                    "ever, so this record does not lower anything in the field; what it does is "
                    "quietly drop the policy for any dashboard reading the feed fresh, and the "
                    "usual cause is simply forgetting CCSYNC_MIN_VERSION on this build.\n"
                    f"Re-run with --min-version {floor} (or higher), or --allow-floor-drop if "
                    "the earlier floor was the mistake. Nothing was uploaded.",
                    EXIT_USAGE)

            upsert_record(channel, record)
            if args.make_current:
                set_current(channel, args.kind, args.platform, args.version)
                print(f"[publish-feed] current[{args.kind}/{args.platform}] = {args.version}",
                      file=out)
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

        # NOTHING published may vanish by omission (release-pipeline-1). The
        # merge above makes this impossible in the ordinary case; it is
        # checked anyway because the failure is silent, signed and only
        # noticed by a customer.
        if published is not None and not args.allow_shrink:
            lost = shrink_report(published, channel, retracted)
            if lost:
                raise PublishFeedError(
                    "this upload would REMOVE from the live channel:\n  "
                    + "\n  ".join(lost)
                    + "\nA customer dashboard reads only the current channel.json, so a record "
                      "that disappears is a build that never existed for them. Re-run with "
                      "--retract for a deliberate withdrawal, or --allow-shrink if you really "
                      "mean to drop all of the above. Nothing was uploaded.",
                    EXIT_USAGE)

        channel["schema"] = SCHEMA
        channel["channel"] = args.channel
        channel["generated_at"] = sign_release.utcnow_iso()
        write_channel(feed_dir, channel, key_path=args.key)
        print(f"[publish-feed] wrote {feed_dir / CHANNEL_FILENAME} and .sig "
              f"({len(channel.get('packages', []))} package record(s))", file=out)

        # Signed and self-verified on disk BEFORE a single byte moves -- the
        # record urls are inside the signed document, so signing can never be
        # the step that follows an upload.
        if upload_refusal is not None:
            raise upload_refusal
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
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
