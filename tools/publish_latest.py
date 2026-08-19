#!/usr/bin/env python3
r"""Publish the newest GREEN CI build to the vendor feed, in one command.

    python tools/publish_latest.py                    # everything new
    python tools/publish_latest.py --kind companion --platform macos
    python tools/publish_latest.py --dry-run          # say what it would do

WHY THIS EXISTS (2026-08-19). `tools\ship.cmd` is still THE ship for a build
made ON this rig: gates, dashboard deploy, build, publish, make-current, local
upgrade, drift check. This is the other half, and it did not exist:
`.github/workflows/release-*.yml` build on hosted runners and deliberately do
NOT publish, so every CI build had to be downloaded, checked and fed to
publish_feed.py BY HAND, with the version and platform retyped each time. In
practice that meant they were not published at all -- the macOS companion sat
at 0.9.2 while the repo was at 0.9.3, which is the whole reason a Mac editor
runs a build from a previous fix pass. See docs/RELEASE.md.

WHY IT DOES NOT RUN IN CI, AND MUST NOT. The signing key lives at
~/.ccsync-release/release.key and never enters GitHub (docs/RELEASE_FEED.md
section 5). A runner that could sign would mean anyone who compromised the
repo, a third-party action or the account could push code that every editor's
companion TRUSTS and runs at logon -- and because the public key is baked into
each build, recovering from that costs an overlap release plus every editor
upgrading. Owner's call 2026-08-19, having weighed exactly that: CI builds,
this rig signs. The manual step that remains is the go/no-go, which is a
feature -- a bad companion build takes the whole fleet offline.

Stdlib only, and it shells out with sys.executable so it runs under whatever
interpreter invoked it (the dashboard venv and a bare system python both work
-- publish_feed.py's crypto is ccsync_companion.ed25519, pure Python).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FEED_DIR = REPO_ROOT / "feed"
FEED_REPO = "The-Creators-Club/ccsync-releases"

# workflow -> what its artifact publishes as. The dashboard is absent on
# purpose: its bundle carries a runtime_id that must be read out of the tarball
# (build_dashboard_bundle.py prints it), and publish_feed.py wants it passed
# explicitly -- so a dashboard release stays a deliberate two-step rather than
# something this sweeps up. Add it here the day that stops being true.
SOURCES = [
    {"workflow": "release-windows.yml", "kind": "companion", "platform": "windows"},
    {"workflow": "release-macos.yml", "kind": "companion", "platform": "macos"},
]


def run(cmd, **kw):
    """Run and return (rc, stdout, stderr). Never raises on a non-zero rc."""
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return p.returncode, p.stdout, p.stderr


def fail(msg: str) -> None:
    print(f"[publish-latest] FAILED: {msg}")
    raise SystemExit(1)


def step(msg: str) -> None:
    print(f"[publish-latest] {msg}")


def preflight() -> None:
    if shutil.which("gh") is None:
        fail("`gh` is not on PATH -- install the GitHub CLI (docs/RELEASE.md)")
    rc, _, err = run(["gh", "auth", "status"])
    if rc != 0:
        fail("`gh` is not authenticated -- run `gh auth login`\n" + err.strip())
    key = Path(os.path.expanduser("~/.ccsync-release/release.key"))
    if not key.exists():
        # The refusal names the file rather than the concept: without it
        # nothing here can sign, and `release_key.py new` would MINT A NEW ONE,
        # which is the wrong answer for a fleet already trusting the old half.
        fail(f"no release key at {key} -- this rig cannot sign.\n"
             "  If it moved, restore it. Do NOT run `release_key.py new`: a new key is "
             "trusted by no companion in the field (docs/RELEASE.md, key rotation).")


def published_versions() -> set[tuple[str, str, str]]:
    """(kind, platform, version) already in the LOCAL feed.

    The local feed is the one publish_feed.py rewrites, so it is what a second
    publish of the same version would collide with. Missing feed = nothing
    published yet, which is a legitimate first run rather than an error.
    """
    ch = FEED_DIR / "channel.json"
    if not ch.exists():
        return set()
    try:
        data = json.loads(ch.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"{ch} is unreadable ({exc}) -- refusing to guess what is published")
    return {(p.get("kind", ""), p.get("platform", ""), p.get("version", ""))
            for p in data.get("packages", [])}


def latest_green_run(workflow: str) -> dict | None:
    rc, out, err = run(["gh", "run", "list", "--workflow", workflow,
                        "--status", "success", "--limit", "1",
                        "--json", "databaseId,headSha,displayTitle,createdAt"])
    if rc != 0:
        fail(f"gh run list failed for {workflow}: {err.strip()}")
    runs = json.loads(out or "[]")
    return runs[0] if runs else None


def find_manifest(root: Path) -> Path | None:
    hits = sorted(root.rglob("ccsync-release.json"))
    return hits[0] if hits else None


def verify(manifest_path: Path) -> tuple[dict, Path]:
    """Check the artifact beside the manifest still hashes to what it claims.

    Not paranoia about GitHub: an artifact is a ZIP round trip, and this is the
    last point at which a truncated download is cheap to notice. Signing a bad
    artifact would put a broken build on the channel with a GOOD signature,
    which is the one failure the signature cannot warn anyone about.
    """
    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest_path.parent / meta["artifact"]
    if not artifact.exists():
        fail(f"{manifest_path} names {meta['artifact']}, which is not beside it")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if digest != meta.get("sha256"):
        fail(f"{artifact.name}: sha256 {digest} != manifest {meta.get('sha256')} "
             "-- refusing to sign a mismatch")
    size = artifact.stat().st_size
    if size != meta.get("size_bytes"):
        fail(f"{artifact.name}: {size} bytes, manifest says {meta.get('size_bytes')}")
    return meta, artifact


def publish(meta: dict, artifact: Path, manifest_path: Path, kind: str,
            dry_run: bool, extra: list[str]) -> None:
    cmd = [sys.executable, str(REPO_ROOT / "tools" / "publish_feed.py"),
           "--manifest", str(manifest_path), "--artifact", str(artifact),
           "--kind", kind, "--feed-dir", str(FEED_DIR),
           "--github-repo", FEED_REPO, *extra]
    if not dry_run:
        cmd.append("--github-upload")
    else:
        step("DRY RUN -- publish_feed.py would run as:")
        print("   ", " ".join(cmd))
        return
    rc, out, err = run(cmd, cwd=str(REPO_ROOT))
    sys.stdout.write(out)
    if rc != 0:
        sys.stderr.write(err)
        fail(f"publish_feed.py exited {rc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=["companion"], default=None,
                    help="only this kind (default: every source below)")
    ap.add_argument("--platform", choices=["windows", "macos"], default=None,
                    help="only this platform")
    ap.add_argument("--dry-run", action="store_true",
                    help="download and verify, but do not sign or upload")
    ap.add_argument("--force", action="store_true",
                    help="publish even if that version is already in the feed "
                         "(publish_feed.py may still refuse)")
    ap.add_argument("--min-version", default=None,
                    help="downgrade floor to stamp into the record")
    args = ap.parse_args()

    preflight()
    already = published_versions()
    extra = ["--min-version", args.min_version] if args.min_version else []

    wanted = [s for s in SOURCES
              if (args.kind is None or s["kind"] == args.kind)
              and (args.platform is None or s["platform"] == args.platform)]
    if not wanted:
        fail("no source matches that --kind/--platform combination")

    published, skipped = [], []
    with tempfile.TemporaryDirectory(prefix="ccsync-publish-") as tmp:
        for src in wanted:
            wf, kind, plat = src["workflow"], src["kind"], src["platform"]
            step(f"--- {kind}/{plat} ({wf}) ---")
            run_info = latest_green_run(wf)
            if run_info is None:
                step(f"no successful {wf} run yet -- skipping")
                skipped.append(f"{kind}/{plat}: no green run")
                continue
            step(f"run {run_info['databaseId']} ({run_info['headSha'][:7]}, "
                 f"{run_info['createdAt']})")

            dest = Path(tmp) / f"{kind}-{plat}"
            dest.mkdir(parents=True, exist_ok=True)
            rc, _, err = run(["gh", "run", "download", str(run_info["databaseId"]),
                              "--dir", str(dest)])
            if rc != 0:
                # Expired artifacts are the common case here (GitHub keeps them
                # ~90 days), and a re-run of the workflow is the fix -- not
                # anything this script can do.
                step(f"could not download artifacts: {err.strip() or 'no artifact'}")
                skipped.append(f"{kind}/{plat}: no downloadable artifact")
                continue

            manifest_path = find_manifest(dest)
            if manifest_path is None:
                step("no ccsync-release.json in the artifact -- skipping")
                skipped.append(f"{kind}/{plat}: no manifest")
                continue

            meta, artifact = verify(manifest_path)
            version = meta.get("version", "")
            step(f"verified {artifact.name} v{version} "
                 f"({meta.get('size_bytes')} bytes, sha256 ok)")

            if meta.get("platform") != plat:
                fail(f"{wf} produced platform={meta.get('platform')!r}, expected {plat!r}")
            if meta.get("git_dirty"):
                fail(f"{kind}/{plat} v{version} was built from a DIRTY tree -- "
                     "a +dirty build must not reach the fleet")
            if not meta.get("tests_run"):
                step("WARNING: this build was made with tests skipped")

            if (kind, plat, version) in already and not args.force:
                step(f"v{version} is already in the feed -- nothing to do "
                     "(--force to republish)")
                skipped.append(f"{kind}/{plat}: v{version} already published")
                continue

            publish(meta, artifact, manifest_path, kind, args.dry_run, extra)
            published.append(f"{kind}/{plat} v{version}")

    print()
    step("summary")
    for p in published:
        print(f"   published: {p}")
    for s in skipped:
        print(f"   skipped:   {s}")
    if published and not args.dry_run:
        print()
        step("the fleet does NOT have these yet: the dashboard offers a feed build "
             "only after Settings > Packages > check, and an admin clicks Publish "
             "([releases] policy = manual).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
