#!/usr/bin/env python3
r"""Release to customers: ONE gated event from ONE green commit.

    python tools/release_customers.py --dry-run          # verify everything, change nothing
    python tools/release_customers.py                    # origin/main's tip
    python tools/release_customers.py --sha <full sha>   # a specific green commit

GL-24 / COM-H8 / PRAC-9 (CR-371, 2026-10-07). A customer release used to be
four hand-run acts that nothing tied together (the dashboard bundle, a `v*` tag
that moves the image, the channel's `dashboard_image`, and the companion and
installers), so the customer channel sat a month behind the studio and a
customer could be offered a companion newer than their dashboard, a draft
EULA, and none of the fixes in between. This is the one command. In order:

  1. verify, before anything moves: origin/main's tip (or --sha, which must be
     an ancestor of it); a green ci.yml run for exactly that commit; a green
     release-dashboard / release-windows / release-macos run for exactly that
     commit; the dashboard bundle built from it, clean; no published channel
     newer than what is being cut.
  1b. (CR-371 round 2) the `customer-release` environment must exist WITH
     required reviewers (GitHub auto-creates a missing one unprotected, which
     would promote with no approval), and the studio's own dashboard must have
     run this commit for --soak-hours (24; --allow-no-soak overrides). Needs
     CCSYNC_STUDIO_URL and DASH_REPORT_TOKEN. The companion half of the soak
     (companion builds current on the studio) is NOT checked here.
  2. tag `v<dashboard VERSION>` on that commit and push it. image.yml then
     builds the image, runs the boot smoke test and waits at the
     `customer-release` environment for the owner's approval (GL-25) before it
     promotes `:<VERSION>` / `:1`.
  3. wait for that image run, read the digests it published.
  4. publish the DASHBOARD bundle first, with `--make-current` and
     `--set-image <tag>@<digest>` in the SAME channel write, so `current` and
     `dashboard_image` can never disagree (the ordering rule: a companion that
     needs a newer dashboard than the channel carries is refused later).
  5. publish the companion and both installers through publish_latest.py,
     pinned to the same commit, with --make-current. It carries its own gates
     (green CI, floor, ordering, rollback).
  6. pin compose.appliance.yaml to the digests (tools/pin_compose_images.py)
     and say so: the owner commits it. Customers are pinned BY DIGEST (GL-50).

It never signs in CI and never lowers a gate: the offline key stays on this
rig, and a build is unsigned during the beta (GL-26 is deferred) without that
being refused anywhere here. Stdlib only; every subprocess goes through
publish_latest.run so the tests can replace it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pin_compose_images  # noqa: E402
import publish_latest as pl  # noqa: E402

REPO_ROOT = pl.REPO_ROOT
FEED_DIR = pl.FEED_DIR
FEED_REPO = pl.FEED_REPO
DASHBOARD_VERSION_FILE = "dashboard/src/ccsync_dashboard/__init__.py"
IMAGE_WORKFLOW = "image.yml"
DASHBOARD_WORKFLOW = "release-dashboard.yml"
DASHBOARD_ARTIFACT = "ccsync-dashboard-bundle"
DIGEST_ARTIFACT = "image-digests"
# Every workflow that must have gone green on THIS commit before it is cut.
REQUIRED_RUNS = (DASHBOARD_WORKFLOW, "release-windows.yml", "release-macos.yml")
# The ci.yml jobs that must have RUN to success, not merely not failed, before
# a dashboard goes to customers: the dashboard, server, tools and web-app
# suites and the CRLF / licence / notices gates all live in `linux`, and
# release-dashboard.yml runs no test at all (see pl.ci_jobs_not_run).
DASHBOARD_CI_JOBS = ("linux",)


class ReleaseError(Exception):
    pass


def step(msg: str) -> None:
    print(f"[release-customers] {msg}")


def dashboard_version_at(sha: str) -> str:
    rc, out, err = pl.run(["git", "-C", str(REPO_ROOT), "show", f"{sha}:{DASHBOARD_VERSION_FILE}"])
    if rc != 0:
        raise ReleaseError(f"cannot read {DASHBOARD_VERSION_FILE} at {sha[:7]}: {err.strip()}")
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', out, re.MULTILINE)
    if not m:
        raise ReleaseError(f"no VERSION in {DASHBOARD_VERSION_FILE} at {sha[:7]}")
    return m.group(1)


def tag_state(tag: str, sha: str) -> str:
    """"absent", "same" (already on `sha`) or "elsewhere" (another commit)."""
    rc, out, _ = pl.run(["git", "-C", str(REPO_ROOT), "ls-remote", "origin",
                         f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"])
    if rc != 0:
        raise ReleaseError(f"could not ask origin about tag {tag}")
    commits = {line.split()[0] for line in (out or "").splitlines() if line.strip()}
    if not commits:
        return "absent"
    return "same" if sha in commits else "elsewhere"


def verify(sha: str, branch_tip: str, channel: dict,
           allow_unrun_ci_jobs: bool = False) -> tuple[str, dict]:
    """Every refusal, in the order an operator can act on them. Returns
    (dashboard_version, {workflow: run_info})."""
    if not pl.commit_is_on_main(sha, branch_tip):
        raise ReleaseError(f"{sha[:7]} is not an ancestor of origin/{pl.RELEASE_BRANCH} "
                           f"({branch_tip[:7]}): a customer release comes from the release branch")
    if not pl.ci_green_for(sha):
        raise ReleaseError(f"{sha[:7]} has no successful {pl.CI_WORKFLOW} run. Customers get "
                           "only what the full suite passed; fix it or wait for CI.")
    unrun = pl.ci_jobs_not_run(sha, DASHBOARD_CI_JOBS)
    if unrun is None or unrun:
        which = (", ".join(unrun) if unrun else ", ".join(DASHBOARD_CI_JOBS))
        problem = (f"the {pl.CI_WORKFLOW} run for {sha[:7]} is green, but its `{which}` job "
                   + ("could not be read" if unrun is None else "did not run to success (a skipped "
                      "job leaves the run green)")
                   + ". That job is the only place the dashboard, server, tools and web-app "
                   "suites run, with the CRLF, licence and notices gates, so nothing has tested "
                   "this dashboard. Turn the job back on (the `if: false` under `linux:` in "
                   f".github/workflows/{pl.CI_WORKFLOW}), get it green on this commit, and "
                   "release then; or pass --allow-unrun-ci-jobs to send customers a dashboard "
                   "that no automated suite has run.")
        if not allow_unrun_ci_jobs:
            raise ReleaseError(problem)
        step("WARNING: --allow-unrun-ci-jobs: " + problem.split(". That job")[0]
             + ". No automated suite has run this dashboard.")
    version = dashboard_version_at(sha)
    newest = pl.newest_published(channel, "dashboard", "linux")
    if newest and pl.version_tuple(version) < pl.version_tuple(newest):
        raise ReleaseError(f"dashboard {version} at {sha[:7]} is OLDER than {newest}, already on "
                           "the channel. That is a rollback, not a release "
                           "(publish_feed.py --set-current is the tool for one).")
    runs: dict[str, dict] = {}
    for wf in REQUIRED_RUNS:
        info = pl.latest_green_run(wf, sha)
        if info is None:
            raise ReleaseError(f"{wf} has no successful run for {sha[:7]}. Dispatch it on that "
                               f"commit (gh workflow run {wf} --ref {pl.RELEASE_BRANCH}) and "
                               "wait; every artefact of a release is built from the same commit.")
        runs[wf] = info
    return version, runs


ENVIRONMENT = "customer-release"


def environment_refusal() -> str:
    """"" when the `customer-release` environment exists WITH required
    reviewers, else why not.

    CR-371 overseer round 2 (2026-10-07). image.yml's promote job names this
    environment, and GitHub auto-creates a missing one with NO protection
    rules, so a forgotten setup step turns the approval gate into a no-op that
    moves :<VERSION> and :1 unattended: the exact COM-H10 condition, silently.
    Checked before the tag is pushed, because after it the promote is already
    running. Not being able to ask is a refusal."""
    rc, out, err = pl.run(["gh", "api", f"repos/{{owner}}/{{repo}}/environments/{ENVIRONMENT}"],
                          cwd=str(REPO_ROOT))
    if rc != 0:
        return (f"could not read the `{ENVIRONMENT}` environment ({(err or out).strip()[:200]}). "
                "Create it (GitHub -> Settings -> Environments) with a REQUIRED REVIEWER before "
                "releasing: without one image.yml promotes with no human approval.")
    try:
        rules = json.loads(out or "{}").get("protection_rules") or []
    except ValueError:
        return f"the `{ENVIRONMENT}` environment answer was not JSON"
    for rule in rules:
        if rule.get("type") == "required_reviewers" and rule.get("reviewers"):
            return ""
    return (f"the `{ENVIRONMENT}` environment has no required reviewers, so image.yml would "
            "promote :<VERSION> and :1 with no approval. Add a reviewer in GitHub -> Settings "
            "-> Environments -> customer-release.")


SOAK_HOURS_DEFAULT = 24.0


def _ledger_path() -> Path:
    import os
    return Path(os.environ.get("CCSYNC_SOAK_LEDGER")
                or Path.home() / ".ccsync" / "release_soak.json")


def fetch_studio_health(url: str, token: str, timeout: float = 15.0) -> dict:
    """The studio dashboard's authenticated /api/v1/health body (the fleet
    token unlocks `code`). No redirect is followed: a credential is on the wire."""
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: D401
            return None
    req = urllib.request.Request(url.rstrip("/") + "/api/v1/health",
                                 headers={"X-CCSync-Token": token})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ReleaseError(f"could not read the studio dashboard's health at {url}: {exc}") from exc


def soak_refusal(health: dict, sha: str, version: str, *, hours: float, now: float,
                 ledger: dict) -> tuple[str, dict]:
    """(refusal or "", ledger entry to persist).

    GL-50 vendor soak (CR-371 overseer round 2, 2026-10-07): customers are
    offered only what the studio's OWN dashboard has already been running.
    The dashboard publishes no uptime, so the clock is this ledger: the first
    time THIS tool saw the studio running <version>@<commit>. That is never
    earlier than the real deploy, so the soak can only be longer than N hours,
    never shorter. The first sighting starts the clock and refuses."""
    code = health.get("code") if isinstance(health.get("code"), dict) else {}
    running = str(health.get("version") or code.get("running") or "")
    commit = str(code.get("commit") or "")
    if running != version:
        return (f"the studio dashboard runs {running or '?'}, not {version}: ship it to the "
                "studio first and let it soak.", {})
    if not commit or not (sha.startswith(commit) or commit.startswith(sha)):
        return (f"the studio dashboard reports commit {commit[:7] or 'unknown'}, not {sha[:7]}: "
                "it has not run this commit (or cannot say), so nothing has soaked.", {})
    key = f"{version}@{sha[:12]}"
    first = ledger.get(key)
    if not isinstance(first, (int, float)):
        return (f"soak clock for {key} starts now; re-run in {hours:g} h. The studio dashboard "
                "is running it, which is the precondition.", {key: now})
    age_h = (now - float(first)) / 3600.0
    if age_h < hours:
        return (f"the studio has run {key} for {age_h:.1f} h of the {hours:g} h soak. "
                f"Wait {hours - age_h:.1f} h more, or pass --allow-no-soak.", {})
    return "", {}


def soak_check(sha: str, version: str, *, hours: float, dry_run: bool,
               now: float | None = None) -> str:
    import os
    url = os.environ.get("CCSYNC_STUDIO_URL", "").strip()
    token = os.environ.get("DASH_REPORT_TOKEN", "").strip()
    if not url or not token:
        return ("no studio dashboard to read: set CCSYNC_STUDIO_URL and DASH_REPORT_TOKEN "
                "(tools\\load_secrets.ps1), or pass --allow-no-soak. A release nobody has run "
                "yet is not a soaked one.")
    health = fetch_studio_health(url, token)
    path = _ledger_path()
    try:
        ledger = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        ledger = {}
    refusal, update = soak_refusal(health, sha, version, hours=hours,
                                   now=time.time() if now is None else now, ledger=ledger)
    if update and not dry_run:
        ledger.update(update)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    return refusal


def read_bundle(run_id: str, dest: Path, sha: str, version: str) -> Path:
    rc, _o, err = pl.run(["gh", "run", "download", str(run_id), "-n", DASHBOARD_ARTIFACT,
                          "--dir", str(dest)])
    if rc != 0:
        raise ReleaseError(f"could not download the dashboard bundle (expired artefact? "
                           f"re-run {DASHBOARD_WORKFLOW}): {err.strip()}")
    bundles = sorted(dest.rglob("ccsync-dashboard-*.tar.gz"))
    if not bundles:
        raise ReleaseError("the dashboard artefact held no ccsync-dashboard-*.tar.gz")
    bundle = bundles[0]
    try:
        with tarfile.open(bundle, "r:gz") as tar:
            member = tar.extractfile("manifest.json")
            manifest = json.loads(member.read().decode("utf-8")) if member else {}
    except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
        raise ReleaseError(f"{bundle.name} has no readable manifest.json: {exc}") from exc
    if manifest.get("git_dirty"):
        raise ReleaseError(f"{bundle.name} was built from a DIRTY tree: it must not reach customers")
    commit = str(manifest.get("git_commit") or "")
    if not commit or not (sha.startswith(commit) or commit.startswith(sha)):
        raise ReleaseError(f"{bundle.name} was built from {commit[:7] or '?'}, not {sha[:7]}: "
                           "re-run release-dashboard on the release commit")
    if str(manifest.get("version") or "") != version:
        raise ReleaseError(f"{bundle.name} is version {manifest.get('version')}, the tree at "
                           f"{sha[:7]} says {version}")
    return bundle


def bundle_channel_refusal(bundle: Path, channel: dict, version: str) -> str:
    """"" or why the CI bundle cannot be published as <version>.

    CR-371 GL-24 round 3 (2026-10-07). manifest.json carries `built_at`, so two
    builds of one commit differ in bytes. If the studio soak put another build
    of this version on the channel (staged, route a), publish_feed refuses the
    CI bundle with "DIFFERENT bytes" at step 4, AFTER the tag is pushed and the
    image approved. Compared here, before anything moves."""
    import hashlib
    import publish_feed  # noqa: E402  (in-repo, pure python)
    # A version on the signed recall list is refused by publish_feed whatever
    # its bytes ("RECALL list"), again after the tag is pushed; neither
    # published_sha256 nor newest_published reads that list.
    if ("dashboard", "linux", version) in publish_feed.retracted_keys(channel):
        return (f"dashboard/linux {version} is on the channel's signed RECALL list: "
                "publish_feed refuses to publish it again, after the tag would already be "
                "pushed. Bump the dashboard VERSION and release that.")
    on_feed = pl.published_sha256(channel, "dashboard", "linux", version)
    if not on_feed:
        return ""
    ours = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if ours == on_feed:
        return ""
    return (f"dashboard/linux {version} is already on the channel with DIFFERENT bytes "
            f"(feed sha256 {on_feed[:16]}..., the CI bundle {ours[:16]}...). Publishing the CI "
            "bundle would be refused after the tag is pushed. The studio soak must use the "
            f"exact CI artefact: `gh run download <the {DASHBOARD_WORKFLOW} run for this "
            f"commit> -n {DASHBOARD_ARTIFACT}`; re-running that workflow breaks the match. "
            "Bump the dashboard VERSION and release that (retiring the staged record only "
            "puts the version on the RECALL list, which is refused too).")


def wait_for_image(tag: str, sha: str, *, timeout: int, poll: int, sleep=time.sleep) -> dict:
    """The digests the tag's image run published, once it succeeded. A failed,
    cancelled or timed-out run is a refusal: nothing moves."""
    deadline = time.monotonic() + timeout
    while True:
        rc, out, err = pl.run(["gh", "run", "list", "--workflow", IMAGE_WORKFLOW,
                               "--branch", tag, "--commit", sha, "--limit", "1",
                               "--json", "databaseId,status,conclusion"])
        if rc != 0:
            raise ReleaseError(f"gh run list failed for {IMAGE_WORKFLOW}: {err.strip()}")
        runs = json.loads(out or "[]")
        if runs and runs[0].get("status") == "completed":
            if runs[0].get("conclusion") != "success":
                raise ReleaseError(f"the image run for {tag} ended {runs[0].get('conclusion')}: "
                                   "no digest was published. Nothing was released.")
            return fetch_digests(str(runs[0]["databaseId"]))
        if time.monotonic() >= deadline:
            raise ReleaseError(f"the image run for {tag} had not finished after {timeout} s. It "
                               "may be waiting for the `customer-release` environment approval "
                               "(GitHub -> Actions -> the run -> Review deployments). Re-run this "
                               "command once it is green; the tag is already pushed.")
        sleep(poll)


def fetch_digests(run_id: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="ccsync-digests-") as tmp:
        rc, _o, err = pl.run(["gh", "run", "download", run_id, "-n", DIGEST_ARTIFACT, "--dir", tmp])
        if rc != 0:
            raise ReleaseError(f"could not download the image digests: {err.strip()}")
        hits = sorted(Path(tmp).rglob("digests.json"))
        if not hits:
            raise ReleaseError("the image run published no digests.json")
        data = json.loads(hits[0].read_text(encoding="utf-8"))
    for key in ("version", "image", "digest", "sftp_digest"):
        if not data.get(key):
            raise ReleaseError(f"digests.json is missing {key!r}")
    for key in ("digest", "sftp_digest"):
        if not pin_compose_images.DIGEST_RE.match(str(data[key])):
            raise ReleaseError(f"digests.json carries a malformed {key} {data[key]!r}")
    return data


def publish_dashboard(bundle: Path, version: str, digests: dict, dry_run: bool,
                      sha: str = "") -> None:
    cmd = [sys.executable, str(HERE / "publish_feed.py"),
           "--artifact", str(bundle), "--kind", "dashboard", "--platform", "linux",
           "--version", version, "--feed-dir", str(FEED_DIR), "--github-repo", FEED_REPO,
           "--make-current", "--git-sha", sha,
           "--set-image", f"{digests['version']}@{digests['digest']}",
           "--set-sftp-digest", digests["sftp_digest"]]
    if dry_run:
        step("DRY RUN: would run " + " ".join(cmd + ["--github-upload"]))
        return
    rc, out, err = pl.run(cmd + ["--github-upload"], cwd=str(REPO_ROOT))
    sys.stdout.write(out)
    sys.stderr.write(err)
    if rc != 0:
        raise ReleaseError(f"publishing the dashboard bundle failed (rc {rc}); the companion "
                           "and installers were NOT published")


def publish_clients(sha: str, dry_run: bool, passthrough: list[str]) -> None:
    cmd = [sys.executable, str(HERE / "publish_latest.py"), "--sha", sha, "--make-current",
           *passthrough]
    if dry_run:
        cmd.append("--dry-run")
    rc, out, err = pl.run(cmd, cwd=str(REPO_ROOT))
    sys.stdout.write(out)
    sys.stderr.write(err)
    if rc != 0:
        raise ReleaseError(f"publish_latest.py failed (rc {rc}). The dashboard bundle IS already "
                           "published and current, which is the safe half (customers are offered "
                           "no companion newer than it): fix the cause and re-run "
                           f"`python tools/publish_latest.py --sha {sha} --make-current`.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sha", default="", help="release this commit (default: origin/main's tip)")
    ap.add_argument("--dry-run", action="store_true",
                    help="verify and print the plan; tag nothing, publish nothing, edit nothing")
    ap.add_argument("--image-timeout", type=int, default=3600,
                    help="seconds to wait for the image run (it waits for the owner's approval)")
    ap.add_argument("--poll", type=int, default=30)
    ap.add_argument("--no-compose-pin", action="store_true",
                    help="do not rewrite compose.appliance.yaml")
    ap.add_argument("--soak-hours", type=float, default=SOAK_HOURS_DEFAULT,
                    help="hours the studio's own dashboard must have run this commit first")
    ap.add_argument("--allow-unrun-ci-jobs", action="store_true",
                    help="release although the ci.yml job that runs the dashboard, server and "
                         "web-app suites (linux) was skipped or could not be read on this "
                         "commit. A skipped job leaves the run green; this says you know that "
                         "no automated suite has run the dashboard being released.")
    ap.add_argument("--allow-no-soak", action="store_true",
                    help="release without the studio soak (a hotfix the studio cannot wait for)")
    args, passthrough = ap.parse_known_args(argv)

    try:
        pl.preflight()
        tip = pl.release_branch_tip()
        if not tip:
            raise ReleaseError(f"could not read origin/{pl.RELEASE_BRANCH}")
        sha = args.sha.strip() or tip
        if len(sha) != 40:
            raise ReleaseError("--sha must be the full 40-character commit id")
        channel = pl.published_channel()
        version, runs = verify(sha, tip, channel,
                               allow_unrun_ci_jobs=args.allow_unrun_ci_jobs)
        tag = f"v{version}"
        state = tag_state(tag, sha)
        if state == "elsewhere":
            raise ReleaseError(f"{tag} already exists on a DIFFERENT commit. An immutable tag is "
                               "never moved: bump the dashboard VERSION and release that.")
        env_problem = environment_refusal()
        if env_problem:
            raise ReleaseError(env_problem)
        if args.allow_no_soak:
            step("WARNING: --allow-no-soak: the studio has NOT soaked this release")
        else:
            soak_problem = soak_check(sha, version, hours=args.soak_hours, dry_run=args.dry_run)
            if soak_problem:
                raise ReleaseError(soak_problem)
            step(f"studio soak satisfied ({args.soak_hours:g} h on {version})")
        step(f"commit {sha[:7]}  dashboard {version}  tag {tag} ({state})")
        step("verified: ci.yml green"
             + (" (BUT its " + ", ".join(DASHBOARD_CI_JOBS) + " job was not required to have run)"
                if args.allow_unrun_ci_jobs
                else " and its " + ", ".join(DASHBOARD_CI_JOBS) + " job ran")
             + ", " + ", ".join(REQUIRED_RUNS) + " green on this commit")
        with tempfile.TemporaryDirectory(prefix="ccsync-customer-release-") as tmp:
            bundle = read_bundle(str(runs[DASHBOARD_WORKFLOW]["databaseId"]), Path(tmp), sha, version)
            mismatch = bundle_channel_refusal(bundle, channel, version)
            if mismatch:
                raise ReleaseError(mismatch)
            step(f"bundle {bundle.name} matches the commit and is clean")
            if args.dry_run:
                step(f"DRY RUN: would tag {tag} on {sha[:7]}, push it, wait for image.yml "
                     "(owner approval), publish the bundle with --make-current --set-image, run "
                     f"publish_latest.py --sha {sha[:7]} --make-current, pin the compose file")
                publish_clients(sha, True, passthrough)
                return 0
            if state == "absent":
                for cmd in (["git", "-C", str(REPO_ROOT), "tag", "-a", tag, sha, "-m",
                             f"Customer release {version}"],
                            ["git", "-C", str(REPO_ROOT), "push", "origin", tag]):
                    rc, _o, err = pl.run(cmd)
                    if rc != 0:
                        raise ReleaseError(f"{' '.join(cmd[3:])} failed: {err.strip()}")
                step(f"pushed {tag}: image.yml is building and will wait for approval")
            digests = wait_for_image(tag, sha, timeout=args.image_timeout, poll=args.poll)
            step(f"image {digests['image']}@{digests['digest']}")
            publish_dashboard(bundle, version, digests, False, sha)
        publish_clients(sha, False, passthrough)
        if not args.no_compose_pin:
            compose = pin_compose_images.COMPOSE
            compose.write_text(pin_compose_images.pin(
                compose.read_text(encoding="utf-8"), version=version,
                dashboard_digest=digests["digest"], sftp_digest=digests["sftp_digest"]),
                encoding="utf-8", newline="")
            step(f"pinned {compose.name} to {version}@{digests['digest'][:19]}...: COMMIT IT")
        step("done. Next: a fresh appliance install against the vendor feed (the one thing "
             "this cannot check), and `python tools/check_feed_freshness.py`.")
        return 0
    except ReleaseError as exc:
        print(f"[release-customers] REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
