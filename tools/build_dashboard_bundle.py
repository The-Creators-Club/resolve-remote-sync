#!/usr/bin/env python3
"""Build the dashboard CODE bundle the fleet updates itself from.

ZERO_TOUCH_PLAN.md WP K, 2026-08-18. The image is the RUNTIME (Python, the
hash-pinned lockfile, the sidecars) and can only be replaced by a click in
the NAS's own UI. The code inside it takes the companion's path instead: this
tool packs the trees the Dockerfile copies into one tarball, stamps it with a
manifest, and `tools/publish_feed.py --kind dashboard` signs it into the
vendor feed. A customer's dashboard downloads it, verifies it against the
public keys baked into the build it is already running, stages it under
`/data/code/<version>/` and re-execs.

    python tools/build_dashboard_bundle.py --out dist/
    python tools/build_dashboard_bundle.py --out dist/ --allow-dirty

WHAT GOES IN, AND WHY EXACTLY THIS:

    manifest.json   version, git commit, runtime_id, per-file sha256
    src/            dashboard/src        -> the volume tree's PYTHONPATH root
    templates/      dashboard/templates  -> ui.py's TEMPLATES_DIR is
    static/         dashboard/static        parents[2] of the package, i.e.
                                            the bundle root: these two are
                                            NOT optional, a tree without them
                                            renders a 500 on every page
    deploy/         dashboard/deploy     -> for completeness and diffing; the
                                            entrypoint that actually runs is
                                            always the IMAGE's /app/deploy
    broll-app/      broll/web            -> top-level package `app`
    music-app/      music/web            -> top-level package `musicweb`
    ytdl-app/       ytdl/web             -> top-level package `ytdlweb`

The three sub-apps are deliberately not all called `app` (CLAUDE.md): two
top-level packages of the same name on one PYTHONPATH collide in sys.modules
and one wins silently. The directory names here mirror the image's
`/broll-app`, `/music-app`, `/ytdl-app` mount points so the two layouts read
the same.

WHAT STAYS OUT: `.venv`, `tests/`, `__pycache__`, `*.pyc`, each tree's `data/`
directory (the b-roll/music/ytdl indexes are volumes at runtime, and
`music/web/data` alone is 1.5 GB), and `static/*.map`. The same exclusions
`.dockerignore` applies to the image build, for the same reasons -- a bundle
that carried a 1.5 GB index would be a bundle nobody could ship.

REFUSES A DIRTY TREE without `--allow-dirty`, exactly as
`tools/publish_package.py` refuses a `git_dirty` manifest (OPS-1): a build
nobody can reproduce must not become the thing every customer's dashboard
runs.

Exit codes: 0 ok, 2 usage/refusal, 3 the tree is dirty (and no override).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "dashboard" / "src"))

from ccsync_dashboard import VERSION as DASHBOARD_VERSION  # noqa: E402
from ccsync_dashboard import runtime_id as runtime_id_mod  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DIRTY = 3

BUNDLE_KIND = "dashboard"
# One platform, because there is one image: the dashboard runs in a Linux
# container and nowhere else. `linux` rather than a blank string so the feed's
# (kind, platform, version) key keeps the same shape as every other record.
BUNDLE_PLATFORM = "linux"

MANIFEST_NAME = "manifest.json"

# (source relative to the repo root, name inside the bundle). Order is the
# order they are written, which is the order `--verify` prints them in.
TREES: tuple[tuple[str, str], ...] = (
    ("dashboard/src", "src"),
    ("dashboard/templates", "templates"),
    ("dashboard/static", "static"),
    ("dashboard/deploy", "deploy"),
    ("broll/web", "broll-app"),
    ("music/web", "music-app"),
    ("ytdl/web", "ytdl-app"),
)

# Directory names dropped wherever they appear. `data` is in here because each
# sub-app's data root is a MOUNT at runtime (/broll-data, /music-data,
# /ytdl-data) and never image or bundle content -- the same call
# .dockerignore makes.
EXCLUDE_DIRS = frozenset({
    ".venv", "venv", "tests", "__pycache__", ".pytest_cache", "node_modules",
    ".git", "data", "dist", "build", ".ruff_cache", ".mypy_cache",
})
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".map", ".log")
# Belt to the `data` directory's braces: an index that ended up somewhere else
# still must not travel. `.db-wal`/`.db-shm` are here because a live database
# copied mid-write is worse than no database at all.
EXCLUDE_DB_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")


class BundleError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


def bundle_filename(version: str) -> str:
    """MUST stay identical to tools/sign_release.package_filename's
    `dashboard` branch -- the signature covers the filename, and the two
    disagreeing means a publish refused with an opaque message."""
    return f"ccsync-dashboard-{version}.tar.gz"


def git(*args: str, cwd: Path) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def git_state(repo_root: Path) -> tuple[str, bool]:
    """(commit, dirty). An absent git is not fatal -- a source drop with no
    .git is a legitimate way to build -- but it IS dirty as far as this tool
    is concerned, because nothing can prove otherwise."""
    commit = git("rev-parse", "HEAD", cwd=repo_root)
    if not commit:
        return "", True
    status = git("status", "--porcelain", cwd=repo_root)
    return commit, bool(status)


def _skip(path: Path) -> bool:
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    if path.suffix.lower() in EXCLUDE_DB_SUFFIXES:
        return True
    return False


def iter_tree(source: Path) -> list[Path]:
    """Every file to pack from `source`, sorted, with the exclusions applied.

    Sorted because the manifest and the tar member order must be
    deterministic: two builds of the same commit should differ only in
    `built_at`, so a reviewer diffing two manifests sees the code change and
    nothing else."""
    out: list[Path] = []
    for path in sorted(source.rglob("*")):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(source).parts):
            continue
        if not path.is_file() or path.is_symlink():
            # Symlinks are dropped rather than followed: a bundle is extracted
            # by a process that refuses links on the way in (dashboard_update's
            # safe extraction), so packing one would only ever produce a
            # refusal at the customer's end.
            continue
        if _skip(path):
            continue
        out.append(path)
    return out


def collect_files(repo_root: Path) -> list[tuple[str, Path]]:
    """[(path inside the bundle, path on disk)] for every tree."""
    collected: list[tuple[str, Path]] = []
    for source_rel, bundle_name in TREES:
        source = repo_root / source_rel
        if not source.is_dir():
            raise BundleError(
                f"{source_rel} is missing from this checkout -- a bundle without it "
                f"would boot a dashboard whose {bundle_name} root is empty")
        for path in iter_tree(source):
            rel = path.relative_to(source).as_posix()
            collected.append((f"{bundle_name}/{rel}", path))
    return collected


def build_manifest(repo_root: Path, files: list[tuple[str, Path]], *,
                   version: str, commit: str, dirty: bool, built_at: str) -> dict:
    files_sha256 = {}
    for name, path in files:
        files_sha256[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    rid = runtime_id_mod.runtime_id_from_paths(
        repo_root / "dashboard" / "deploy" / "requirements.lock",
        repo_root / "dashboard" / "deploy" / "Dockerfile",
    )
    return {
        "kind": BUNDLE_KIND,
        "version": version,
        "git_commit": commit,
        "git_dirty": bool(dirty),
        "runtime_id": rid,
        "built_at": built_at,
        "files_sha256": files_sha256,
    }


def write_bundle(out_path: Path, files: list[tuple[str, Path]], manifest: dict) -> None:
    """Write the .tar.gz. Every member is a plain file with a fixed uid/gid,
    mtime and mode -- a tarball whose metadata came from the builder's own
    machine would differ between two builds of the same commit for no reason
    anyone could act on, and the sha256 of these bytes is what gets signed."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with tarfile.open(tmp, "w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest_bytes)
        info.mtime = 0
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(manifest_bytes))
        for name, path in files:
            data = path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            # 0644 for everything: nothing in the bundle is executed as a
            # program by the container (the entrypoint is always the IMAGE's
            # /app/deploy/run.sh), and a code tree that arrives executable is
            # a code tree somebody can be tricked into running.
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    tmp.replace(out_path)


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(repo_root: Path, out_dir: Path, *, allow_dirty: bool, version: str = "",
          built_at: str = "", out: object = None) -> dict:
    """Build the bundle and return {path, manifest, sha256, size_bytes}."""
    stream = out if out is not None else sys.stdout
    version = version or DASHBOARD_VERSION
    commit, dirty = git_state(repo_root)
    if dirty and not allow_dirty:
        raise BundleError(
            "this checkout is DIRTY (uncommitted changes, or no git at all) -- a "
            "dashboard bundle nobody can reproduce must not become what every "
            "customer's dashboard runs. Commit, or pass --allow-dirty for a "
            "deliberate hotfix.", EXIT_DIRTY)
    files = collect_files(repo_root)
    manifest = build_manifest(repo_root, files, version=version, commit=commit,
                              dirty=dirty, built_at=built_at or utcnow_iso())
    out_path = out_dir / bundle_filename(version)
    write_bundle(out_path, files, manifest)
    data = out_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    print(f"[bundle] {out_path} ({len(data)} bytes, {len(files)} files)", file=stream)
    print(f"[bundle] version {version}, commit {commit[:12] or '(none)'}"
          f"{' +dirty' if dirty else ''}", file=stream)
    print(f"[bundle] runtime_id {manifest['runtime_id']}", file=stream)
    print(f"[bundle] sha256 {sha}", file=stream)
    print("[bundle] publish it with:", file=stream)
    print(f"  python tools/publish_feed.py --artifact {out_path} --kind dashboard "
          f"--platform linux --version {version} --runtime-id {manifest['runtime_id']} "
          f"--feed-dir .\\feed --github-repo OWNER/REPO", file=stream)
    return {"path": out_path, "manifest": manifest, "sha256": sha, "size_bytes": len(data)}


def verify(bundle_path: Path, out: object = None) -> tuple[bool, list[str]]:
    """Offline self-check of a built bundle: the manifest is present and
    complete, every member is listed in `files_sha256`, and every hash
    matches. Says out loud what a customer's dashboard would refuse."""
    stream = out if out is not None else sys.stdout
    report: list[str] = []
    ok = True
    with tarfile.open(bundle_path, "r:gz") as tar:
        names = tar.getnames()
        if MANIFEST_NAME not in names:
            return False, [f"{bundle_path} has no {MANIFEST_NAME}"]
        manifest = json.loads(tar.extractfile(MANIFEST_NAME).read().decode("utf-8"))
        listed = dict(manifest.get("files_sha256") or {})
        report.append(f"version {manifest.get('version')}, runtime_id {manifest.get('runtime_id')}")
        for member in tar.getmembers():
            if member.name == MANIFEST_NAME:
                continue
            if not member.isfile():
                report.append(f"{member.name}: not a regular file -- FAILED")
                ok = False
                continue
            expected = listed.pop(member.name, None)
            if expected is None:
                report.append(f"{member.name}: in the tar but not in the manifest -- FAILED")
                ok = False
                continue
            actual = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            if actual != expected:
                report.append(f"{member.name}: sha256 mismatch -- FAILED")
                ok = False
        for missing in listed:
            report.append(f"{missing}: in the manifest but not in the tar -- FAILED")
            ok = False
    report.append("VERIFY OK" if ok else "VERIFY FAILED")
    for line in report:
        print(line, file=stream)
    return ok, report


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="", help="directory to write the .tar.gz into")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    ap.add_argument("--version", default="", help=f"default: the dashboard's own VERSION ({DASHBOARD_VERSION})")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="build from an uncommitted tree anyway (stamps git_dirty=true)")
    ap.add_argument("--verify", default="", help="offline-verify an existing bundle and exit")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.verify:
            ok, _report = verify(Path(args.verify).expanduser())
            return EXIT_OK if ok else EXIT_USAGE
        if not args.out:
            raise BundleError("--out is required (or use --verify)", EXIT_USAGE)
        build(Path(args.repo_root).expanduser(), Path(args.out).expanduser(),
              allow_dirty=args.allow_dirty, version=args.version)
        return EXIT_OK
    except BundleError as exc:
        print(f"[bundle] FAILED: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
