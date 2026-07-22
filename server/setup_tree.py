#!/usr/bin/env python3
"""Create the Creators_Club project template tree on the NAS, over SSH.

    python setup_tree.py --year 2025 --series FF4 --project Nuclear [--dry-run]

Creates:
    /mnt/tank/TheCreatorsPool/Creators_Club/Projects/<year>/<series>/<project>/
        AE/
        Audio/Music/
        Audio/Voiceover/
        B-roll/
        Interviewees/
        "Render in Place"/
        Subs/
        Youtube/

Then sets ownership to <dataset owner>:editors and mode 2770 (setgid, so
files/dirs created later by any editors-group member inherit the group and
stay group-rwx) recursively on the whole project directory. Proxy/
subfolders are NOT created here -- the Blackmagic Proxy Generator creates
them on demand next to media.

Idempotent: every mkdir is preceded by a `test -d` check so re-running only
reports "already exists" for what's there and creates what's missing; chown/
chmod are always re-applied (cheap, safe, and self-healing if permissions
drifted).

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required). See server/README.md.
"""
import argparse
import sys

from common import (
    DEFAULT_PROJECTS_ROOT,
    DEFAULT_DATASET_OWNER,
    EDITORS_GROUP,
    TEMPLATE_FOLDERS,
    project_path,
    project_relative_dirs,
    run_ssh,
    shell_quote,
)


def build_remote_script(base: str, owner: str, group: str) -> str:
    """Bash snippet run on the NAS. Prints one line per folder: created or
    already-existed, then (re-)applies ownership/permissions and reports
    that too. Runs as root via sudo -S so it works regardless of what
    TRUENAS_USER's own uid/gid are.
    """
    lines = ["set -e"]
    base_q = shell_quote(base)
    lines.append(f'echo "$SUDO_PW" | sudo -S -p "" mkdir -p {base_q}')

    for rel in project_relative_dirs():
        full = f"{base}/{rel}"
        full_q = shell_quote(full)
        lines.append(
            f'if [ -d {full_q} ]; then echo "exists: {rel}"; '
            f'else echo "$SUDO_PW" | sudo -S -p "" mkdir -p {full_q} && echo "created: {rel}"; fi'
        )

    owner_group = shell_quote(f"{owner}:{group}")
    lines.append(f'echo "$SUDO_PW" | sudo -S -p "" chown -R {owner_group} {base_q} && echo "ownership set: {owner}:{group} on {base}"')
    lines.append(f'echo "$SUDO_PW" | sudo -S -p "" find {base_q} -type d -exec chmod 2770 {{}} + && echo "permissions set: 2770 (setgid) on all directories under {base}"')
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", required=True, help="e.g. 2025")
    ap.add_argument("--series", required=True, help="e.g. FF4")
    ap.add_argument("--project", required=True, help="e.g. Nuclear")
    ap.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT,
                     help=f"default: {DEFAULT_PROJECTS_ROOT}")
    ap.add_argument("--owner", default=DEFAULT_DATASET_OWNER, help=f"default: {DEFAULT_DATASET_OWNER}")
    ap.add_argument("--group", default=EDITORS_GROUP, help=f"default: {EDITORS_GROUP}")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base = project_path(args.projects_root, args.year, args.series, args.project)
    print(f"Target project root: {base}")
    print(f"Template folders ({len(TEMPLATE_FOLDERS)}): {', '.join(TEMPLATE_FOLDERS)}")

    script = build_remote_script(base, args.owner, args.group)
    rc, out, err = run_ssh(script, dry_run=args.dry_run)

    if args.dry_run:
        print("[dry-run] remote script that would run:")
        print(script)
        return 0

    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)

    if rc != 0:
        print(f"FAILED (remote exit code {rc})", file=sys.stderr)
        return rc

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
