#!/usr/bin/env python3
"""Decide which code tree this container boots, and print its PYTHONPATH.

ZERO_TOUCH_PLAN.md WP K, 2026-08-18. `deploy/run.sh` runs this ONCE per boot
in image mode and exports whatever it prints on stdout. Everything else it has
to say goes to stderr, where the container log keeps it.

    /venv/bin/python /app/deploy/select_code_root.py
    -> /data/code/0.5.1/src:/data/code/0.5.1/broll-app:...        (a volume tree)
    -> /app/src:/broll-app:/music-app:/ytdl-app                    (the image)

WHO IS ALLOWED TO DECIDE. This script is IMAGE content, executed by the
IMAGE's python, importing the IMAGE's `ccsync_dashboard.release_trust` and
reading the IMAGE's baked `/venv/.runtime-id`. The tree under `/data/code` is
the thing being judged and gets no vote: nothing from it is imported, executed
or trusted before the verification below passes. That is the whole reason the
selection is a separate script and not a few lines inside the app -- by the
time the app is running, the decision has already been made.

WHY IMPORT release_trust RATHER THAN VENDOR A FOURTH ED25519. There are
already three copies of this codebase's Ed25519 verifier on purpose
(companion, dashboard, and the tools' use of the companion's), each because
two deployment units cannot import each other. This script is in the SAME
deployment unit as `/app/src` -- same image, same layer, same read-only
mount, replaced only by replacing the image. A fourth copy would be a fourth
thing to keep byte-identical for no isolation gained, so it imports.

WHAT IT CHECKS, in order, and any single failure means "boot the image":

 1. `/data/code/current.json` names a version.
 2. `/data/code/<version>/manifest.json` parses and says it is a dashboard
    bundle of that version.
 3. `/data/code/<version>/record.json` is the signed feed record the update
    was applied from, and its Ed25519 signature verifies against
    `DASH_RELEASE_PUBKEYS` -- the same keys, the same verifier and the same
    canonical form the publish route and the feed client use.
 4. The record's `runtime_id` equals the manifest's equals `/venv/.runtime-id`.
    A tree built for another image must never be booted (its dependencies are
    not here).
 5. The version is NEWER than the image's own. Older or equal is the image's
    job: a bundle cannot roll the image backwards, and an equal version is the
    same code with more moving parts.
 6. The four roots exist.

THE WATCHDOG. Before printing a volume tree, `boot_attempts.json` is
incremented; the app clears it once it has been up and healthy for a while
(`dashboard_update.start_boot_watchdog`). So a tree that crashes the process
before it is healthy counts a boot each time, and on the MAX_BOOT_ATTEMPTS'th
try this script rewrites `current.json` to the previous tree (or the image)
with `reverted_reason` and boots that instead. Nobody has to be watching: the
thing that failed to boot is the thing an admin would have used to fix it.

Test seams (environment, never set by a deployment): CCSYNC_DATA_DIR,
CCSYNC_APP_ROOT, CCSYNC_VENV_DIR.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("CCSYNC_DATA_DIR") or "/data")
APP_ROOT = Path(os.environ.get("CCSYNC_APP_ROOT") or "/app")
VENV_DIR = Path(os.environ.get("CCSYNC_VENV_DIR") or "/venv")

CODE_DIR = DATA_DIR / "code"
CURRENT_JSON = CODE_DIR / "current.json"
BOOT_ATTEMPTS = CODE_DIR / "boot_attempts.json"
RUNTIME_ID_FILE = VENV_DIR / ".runtime-id"

# MUST match dashboard_update.MAX_BOOT_ATTEMPTS. Two files, one number, and no
# import between them: this script runs before anything from the app is on the
# path except release_trust, and dragging the whole module in for one integer
# would put the app's imports on the boot path.
MAX_BOOT_ATTEMPTS = 2

# The image's own four roots, in run.sh's order. `src` first, and the three
# sub-apps after it, each a separate top-level package (`app`, `musicweb`,
# `ytdlweb`) that must not collide -- see the Dockerfile.
IMAGE_ROOTS = (APP_ROOT / "src", Path("/broll-app"), Path("/music-app"), Path("/ytdl-app"))
SUBAPP_DIRS = ("broll-app", "music-app", "ytdl-app")


def say(message: str) -> None:
    """Stdout is the answer; everything else is stderr. A single stray print
    would become part of the PYTHONPATH run.sh exports."""
    print(f"select_code_root: {message}", file=sys.stderr)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict) -> bool:
    """Write-then-rename. False (with a reason on stderr) if the volume is not
    writable: a read-only /data must not stop the container booting, it just
    means the watchdog cannot record anything."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as exc:
        say(f"WARNING: could not write {path}: {exc}")
        return False


def image_pythonpath() -> str:
    return os.pathsep.join(str(p) for p in IMAGE_ROOTS)


def volume_pythonpath(root: Path) -> str:
    return os.pathsep.join([str(root / "src")] + [str(root / d) for d in SUBAPP_DIRS])


def read_runtime_id() -> str:
    try:
        return RUNTIME_ID_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def image_version() -> str:
    """The image's own VERSION, read out of its `__init__.py` rather than
    imported: this script may end up printing a DIFFERENT tree's path, and
    importing the package here would put the wrong one in sys.modules for
    nothing."""
    path = APP_ROOT / "src" / "ccsync_dashboard" / "__init__.py"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("VERSION"):
            return stripped.partition("=")[2].strip().strip('"').strip("'")
    return ""


def parse_version(text: str) -> tuple[int, ...]:
    """Dotted-numeric to a comparable tuple; () for anything else, which
    compares lower than every real version -- so an unparseable version can
    never look newer than the image."""
    raw = str(text or "").strip()
    if not raw or any(ch not in "0123456789." for ch in raw):
        return ()
    try:
        return tuple(int(p) for p in raw.split(".") if p != "")
    except ValueError:
        return ()


def verify_record(record: dict, pubkeys: tuple[str, ...]) -> tuple[bool, str]:
    """The record's own Ed25519 signature, checked with the image's copy of
    the verifier the publish route uses. An import failure here is a refusal,
    never a pass: a boot that cannot verify must boot the image."""
    sys.path.insert(0, str(APP_ROOT / "src"))
    try:
        from ccsync_dashboard import release_trust
    except Exception as exc:                                          # noqa: BLE001
        return False, f"the image's own verifier could not be imported ({exc})"
    return release_trust.verify_record(record, str(record.get("signature", "")), pubkeys)


def release_pubkeys() -> tuple[str, ...]:
    """`DASH_RELEASE_PUBKEYS`, the same variable the publish route and the
    feed client verify against. Empty means nothing can be verified, which
    means the image boots -- exactly as an unconfigured dashboard refuses
    every publish (release_trust.verify_record's own rule)."""
    raw = os.environ.get("DASH_RELEASE_PUBKEYS", "")
    return tuple(k.strip() for k in raw.replace(",", " ").split() if k.strip())


def check_tree(version: str, runtime_id: str) -> tuple[str, str]:
    """(pythonpath, "") for a tree that passes every check, or ("", reason)."""
    if not version:
        return "", "current.json names no version"
    if any(ch not in "0123456789." for ch in version) or ".." in version:
        return "", f"current.json names {version!r}, which is not a version"
    root = CODE_DIR / version
    manifest = read_json(root / "manifest.json")
    if not manifest:
        return "", f"{root}/manifest.json is missing or unreadable"
    if str(manifest.get("kind")) != "dashboard":
        return "", f"{root}/manifest.json is not a dashboard bundle"
    if str(manifest.get("version")) != version:
        return "", (f"{root}/manifest.json says version {manifest.get('version')!r}, "
                    f"but it is installed as {version}")
    record = read_json(root / "record.json")
    if not record:
        return "", f"{root}/record.json is missing -- an unsigned tree is never booted"
    pubkeys = release_pubkeys()
    if not pubkeys:
        return "", "DASH_RELEASE_PUBKEYS is not set, so no code tree can be verified"
    ok, detail = verify_record(record, pubkeys)
    if not ok:
        return "", f"{root}/record.json does not verify: {detail}"
    if str(record.get("kind")) != "dashboard" or str(record.get("version")) != version:
        return "", f"{root}/record.json describes something other than dashboard {version}"
    if not runtime_id:
        return "", "this image has no /venv/.runtime-id, so no bundle can be matched to it"
    if str(record.get("runtime_id") or "") != runtime_id:
        return "", (f"{root} was built for runtime {str(record.get('runtime_id'))[:12]}, "
                    f"this image is {runtime_id[:12]}")
    if str(manifest.get("runtime_id") or "") != runtime_id:
        return "", f"{root}/manifest.json's runtime_id does not match this image"
    installed, image = parse_version(version), parse_version(image_version())
    if not installed or installed <= image:
        return "", (f"{version} is not newer than the image's own {image_version() or '?'} "
                    "-- the image wins")
    for path in [root / "src"] + [root / d for d in SUBAPP_DIRS]:
        if not path.is_dir():
            return "", f"{path} is missing from the installed tree"
    return volume_pythonpath(root), ""


def boot_attempts(version: str) -> int:
    """How many times this exact version has been handed to run.sh without
    ever reaching a healthy boot. The app clears the file once it has been up
    for a while (dashboard_update.start_boot_watchdog), so a non-zero count
    here always means "the last boot of this tree did not work"."""
    state = read_json(BOOT_ATTEMPTS)
    if str(state.get("version") or "") != version:
        return 0
    return int(state.get("attempts") or 0)


def bump_boot_attempts(version: str) -> int:
    """Count this boot BEFORE the app gets a chance to fail."""
    attempts = boot_attempts(version) + 1
    write_json(BOOT_ATTEMPTS, {"version": version, "attempts": attempts})
    return attempts


def revert(current: dict, reason: str) -> None:
    """Point current.json at the previous tree (or the image) and say why.
    The failed tree's FILES are left alone on purpose: they are what an
    operator needs to work out what happened, and disk is cheaper than
    forensics."""
    previous = str(current.get("previous") or "")
    write_json(CURRENT_JSON, {
        "version": previous,
        "previous": "",
        "applied_at": current.get("applied_at") or "",
        "reverted_from": str(current.get("version") or ""),
        "reverted_reason": reason,
    })
    write_json(BOOT_ATTEMPTS, {"version": "", "attempts": 0})
    say(f"REVERTED to {previous or 'the image'}: {reason}")


def main() -> int:
    runtime_id = read_runtime_id()
    current = read_json(CURRENT_JSON)
    version = str(current.get("version") or "")

    if not version:
        # The normal state for a dashboard that has never taken an OTA update,
        # and not worth a warning on every boot.
        print(image_pythonpath())
        return 0

    # The counter is read BEFORE it is bumped, so the number tested is how
    # many boots of this tree have already failed: MAX_BOOT_ATTEMPTS failures
    # revert, and the tree really is tried that many times rather than being
    # written off after one.
    already_failed = boot_attempts(version)
    if already_failed >= MAX_BOOT_ATTEMPTS:
        revert(current, f"{version} failed to reach a healthy boot {already_failed} times")
        current = read_json(CURRENT_JSON)
        version = str(current.get("version") or "")
        if not version:
            print(image_pythonpath())
            return 0
    attempts = bump_boot_attempts(version)

    pythonpath, reason = check_tree(version, runtime_id)
    if reason:
        say(f"WARNING: booting the image's own code instead of {version}: {reason}")
        print(image_pythonpath())
        return 0
    say(f"booting the installed code tree {version} (attempt {attempts})")
    print(pythonpath)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                          # noqa: BLE001
        # NOTHING here may stop the container booting. Any unexpected failure
        # prints the image's own roots and says why, which is a dashboard that
        # runs with the code it shipped with -- the outcome this whole feature
        # is allowed to fail into.
        print(f"select_code_root: WARNING: falling back to the image ({exc})", file=sys.stderr)
        print(os.pathsep.join(str(p) for p in IMAGE_ROOTS))
        sys.exit(0)
