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

# Only builds from THIS branch are publishable (release-pipeline-7,
# 2026-08-21). `gh run list` had no --branch filter and the headSha was
# printed and nothing more, so anyone who dispatched release-windows on a
# feature branch or an old commit made that artifact the next thing this rig
# signed and handed to every customer.
RELEASE_BRANCH = "main"

# workflow -> what its artifact publishes as. The dashboard is absent on
# purpose: its bundle carries a runtime_id that must be read out of the tarball
# (build_dashboard_bundle.py prints it), and publish_feed.py wants it passed
# explicitly -- so a dashboard release stays a deliberate two-step rather than
# something this sweeps up. Add it here the day that stops being true.
#
# `onboard` joined on 2026-08-21 (release-pipeline-4). The installer channel
# was never published through the feed at all, so a customer dashboard fed
# only from the vendor channel showed an EMPTY [ INSTALLER ] page and told its
# admin to run a vendor-internal PowerShell script -- no new Windows or Mac
# editor could be onboarded at that site. Both workflows now write a
# ccsync-onboard.json beside their wizard artefact, in the same shape as the
# companion's ccsync-release.json.
SOURCES = [
    {"workflow": "release-windows.yml", "kind": "companion", "platform": "windows",
     "manifest": "ccsync-release.json"},
    {"workflow": "release-macos.yml", "kind": "companion", "platform": "macos",
     "manifest": "ccsync-release.json"},
    {"workflow": "release-windows.yml", "kind": "onboard", "platform": "windows",
     "manifest": "ccsync-onboard.json"},
    {"workflow": "release-macos.yml", "kind": "onboard", "platform": "macos",
     "manifest": "ccsync-onboard.json"},
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


def published_channel() -> dict:
    """The channel THE WORLD reads, downloaded from the release.

    NOT feed/channel.json (release-pipeline-1, 2026-08-21): that directory is
    gitignored and exists on one machine, so on any other it says "nothing is
    published" about a feed carrying the entire fleet's history. publish_feed
    is imported rather than re-implemented -- it is the one place that knows
    how to fetch, and it verifies the signature the same way.

    An empty dict means the feed is genuinely empty (a first publish). A
    failure to ASK is fatal: guessing "nothing published" is how a republish
    of an existing version would be attempted, or a rollback missed.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))
    import publish_feed  # noqa: E402  (in-repo, pure python)

    with tempfile.TemporaryDirectory(prefix="ccsync-channel-") as tmp:
        channel, signature, status = publish_feed.fetch_published_channel(
            FEED_REPO, publish_feed.DEFAULT_GITHUB_TAG,
            runner=lambda argv: run(argv), dest=Path(tmp), out=sys.stdout)
        if status == "absent":
            return {}
        if status != "ok" or channel is None:
            fail(f"could not read the published channel: {status}")
        ok, detail = publish_feed.verify_channel_signature(
            channel, signature, publish_feed.release_pubkey.RELEASE_PUBKEYS)
        if not ok:
            fail(f"the published channel does not verify ({detail}) -- refusing to "
                 "publish on top of a feed this build does not trust")
        return channel


def version_tuple(version: str) -> tuple:
    """Comparable form. Numeric per component, so 0.10.0 > 0.9.9 -- after
    0.9.9 comes 0.10.0 and never 1.0 (owner's rule, 2026-08-18)."""
    parts = []
    for chunk in str(version or "").replace("+", ".").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def newest_published(channel: dict, kind: str, platform: str) -> str:
    versions = [str(p.get("version") or "") for p in channel.get("packages", [])
                if p.get("kind") == kind and p.get("platform") == platform]
    return max(versions, key=version_tuple, default="")


def latest_green_run(workflow: str) -> dict | None:
    # --branch: a green run of THIS workflow on a feature branch is a build,
    # not a release (release-pipeline-7).
    rc, out, err = run(["gh", "run", "list", "--workflow", workflow,
                        "--branch", RELEASE_BRANCH,
                        "--status", "success", "--limit", "1",
                        "--json", "databaseId,headSha,displayTitle,createdAt"])
    if rc != 0:
        fail(f"gh run list failed for {workflow}: {err.strip()}")
    runs = json.loads(out or "[]")
    return runs[0] if runs else None


def remote_head_sha() -> str:
    """The sha `origin` says refs/heads/<RELEASE_BRANCH> is at RIGHT NOW, or "".

    REL-14 (resilience sweep 2026-08-28). commit_is_on_main used to compare
    against whatever `origin/main` this working copy last fetched, which can
    be days old and can name a commit a force-push has since removed from the
    branch -- the exact class of untruth the --branch filter above exists to
    defeat, one ref removed. This asks the server.
    """
    rc, out, _err = run(["git", "-C", str(REPO_ROOT), "ls-remote", "origin",
                         f"refs/heads/{RELEASE_BRANCH}"])
    if rc != 0:
        return ""
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{RELEASE_BRANCH}":
            return parts[0].strip()
    return ""


def have_commit(sha: str) -> bool:
    """Whether this clone holds that object as a commit."""
    if not sha:
        return False
    rc, _out, _err = run(["git", "-C", str(REPO_ROOT), "cat-file", "-e",
                          f"{sha}^{{commit}}"])
    return rc == 0


def release_branch_tip() -> str:
    """The tip this run compares against: the REMOTE head, fetched if needed.

    Returns "" when the remote could not be asked, and the caller then refuses
    rather than falling back to a local ref -- "could not check" must never
    render as "fine". A fetch is attempted only when the remote head is not
    already in this clone, so the ordinary case costs one ls-remote.
    """
    tip = remote_head_sha()
    if not tip:
        return ""
    if not have_commit(tip):
        step(f"fetching origin/{RELEASE_BRANCH} ({tip[:7]}) -- this clone does not have it yet")
        run(["git", "-C", str(REPO_ROOT), "fetch", "origin", RELEASE_BRANCH])
    return tip if have_commit(tip) else ""


def commit_is_on_main(sha: str, tip: str = "") -> bool:
    """True when `sha` is an ancestor of the release branch.

    --branch above filters by the branch the run was DISPATCHED on, which a
    force-push or a deleted branch can make a lie; this asks git. `tip`
    defaults to the local remote-tracking ref for callers that have not
    established the remote head; main() always passes the fetched one
    (REL-14). Unknown counts as NOT verified -- the caller refuses rather
    than signs (release-pipeline-7)."""
    rc, _out, _err = run(["git", "-C", str(REPO_ROOT), "merge-base",
                          "--is-ancestor", sha, tip or f"origin/{RELEASE_BRANCH}"])
    return rc == 0


def find_manifest(root: Path, name: str) -> Path | None:
    hits = sorted(root.rglob(name))
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
    ap.add_argument("--kind", choices=["companion", "onboard"], default=None,
                    help="only this kind (default: every source below)")
    ap.add_argument("--platform", choices=["windows", "macos"], default=None,
                    help="only this platform")
    ap.add_argument("--dry-run", action="store_true",
                    help="download and verify, but do not sign or upload")
    ap.add_argument("--force", action="store_true",
                    help="publish even if that version is already in the feed "
                         "(publish_feed.py may still refuse)")
    ap.add_argument("--make-current", action="store_true",
                    help="also point the channel's `current` at what is published "
                         "(otherwise the record is STAGED and customers keep being "
                         "offered what they are offered now)")
    ap.add_argument("--allow-older", action="store_true",
                    help="publish a version LOWER than the newest already on the "
                         "channel for that kind/platform. A deliberate rollback; "
                         "refused by default (release-pipeline-7)")
    ap.add_argument("--min-version", default=None,
                    help="downgrade floor to stamp into the record")
    ap.add_argument("--allow-key-rotation", action="store_true",
                    help="publish even though the signing key is not baked into the build "
                         "that is CURRENT for that platform. Every machine on the current "
                         "build will refuse what this publishes, so it is only ever the "
                         "second half of an overlap release (REL-7)")
    args = ap.parse_args()

    preflight()
    # The tip THE SERVER says main is at, before anything is compared against
    # it (REL-14). Established once per run and printed, so the operator can
    # see what the ancestry test actually used.
    branch_tip = release_branch_tip()
    if not branch_tip:
        fail(f"could not read origin/{RELEASE_BRANCH} from the remote -- refusing to sign "
             "against a possibly stale local ref. Check network/`gh auth`, or run "
             f"`git fetch origin {RELEASE_BRANCH}` and try again.")
    step(f"origin/{RELEASE_BRANCH} is at {branch_tip[:7]}")
    # What THE WORLD has, not what this rig's feed/ dir has.
    channel = published_channel()
    already = {(p.get("kind", ""), p.get("platform", ""), p.get("version", ""))
               for p in channel.get("packages", [])}
    extra = ["--min-version", args.min_version] if args.min_version else []
    if args.make_current:
        extra.append("--make-current")
    if args.allow_key_rotation:
        extra.append("--allow-key-rotation")

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
            # The run says it was dispatched on main; git says whether that
            # commit is actually IN main (release-pipeline-7). A force-push or
            # a deleted branch makes the first claim a lie, and this rig signs
            # what it publishes.
            if not commit_is_on_main(run_info["headSha"], branch_tip):
                fail(f"{wf} run {run_info['databaseId']} is at {run_info['headSha'][:7]}, "
                     f"which is not an ancestor of origin/{RELEASE_BRANCH} as the remote "
                     f"has it RIGHT NOW ({branch_tip[:7]}) -- refusing to sign a build the "
                     "release branch does not contain. A force-push can remove a commit CI "
                     "went green on; merge it again, or re-run the workflow on the tip.")

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

            manifest_path = find_manifest(dest, src["manifest"])
            if manifest_path is None:
                step(f"no {src['manifest']} in the artifact -- skipping")
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
                step(f"v{version} is already on the published channel -- nothing to do "
                     "(--force to republish)")
                skipped.append(f"{kind}/{plat}: v{version} already published")
                continue

            # A LOWER version than the channel already carries is a rollback,
            # and until 2026-08-21 nothing here noticed one (release-pipeline-7):
            # combined with the missing `current` pointer, an older record
            # appended after a newer one offered the whole fleet a downgrade.
            newest = newest_published(channel, kind, plat)
            if newest and version_tuple(version) < version_tuple(newest) and not args.allow_older:
                fail(f"{kind}/{plat} v{version} is OLDER than v{newest}, which is already "
                     "on the channel -- refusing. Pass --allow-older for a deliberate "
                     "rollback (and --make-current, or nobody is offered it).")

            publish(meta, artifact, manifest_path, kind, args.dry_run, extra)
            published.append(f"{kind}/{plat} v{version}")

    print()
    step("summary")
    step(f"compared against origin/{RELEASE_BRANCH} @ {branch_tip[:7]}")
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
