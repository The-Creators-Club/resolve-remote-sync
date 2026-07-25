#!/usr/bin/env python3
"""Create the Creators_Club project template tree on the NAS, over SSH.

    python setup_tree.py --year 2025 --series FF4 --project Nuclear [--dry-run]
    python setup_tree.py --year 2026 --series "Creator Profiles" --project "Season 1"

Any year/series/project is valid; names with spaces work as long as they are
quoted (they are shell-quoted before being sent to the NAS).

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

Identity-safe, by design:
  - the .ccsync-project marker is written only when ABSENT. Re-running this
    against a project that was created under a different path keeps its
    original slug and says so; changing a project's identity is a deliberate
    act that lives in write_marker.py --slug ... --force.
  - the run is REFUSED (exit 3/4, nothing created) if any directory between
    the projects root and the target already carries a marker, or if the
    target already contains one. Discovery prunes at markers, so marking a
    container directory would hide every real project underneath it.

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required). See server/README.md.
"""
import argparse
import sys

from common import (
    DEFAULT_PROJECTS_ROOT,
    DEFAULT_DATASET_OWNER,
    EDITORS_GROUP,
    MARKER_FILENAME,
    TEMPLATE_FOLDERS,
    add_host_key_arg,
    build_marker_write_cmd,
    project_path,
    project_path_rel,
    project_relative_dirs,
    run_ssh,
    set_host_key_pin,
    shell_quote,
    slugify,
    validate_slug,
)

# Exit codes the remote script uses for the two "this is not a project
# directory" refusals, so a caller can tell them apart from a real failure.
RC_ANCESTOR_MARKER = 3
RC_DESCENDANT_MARKER = 4


def ancestor_dirs(projects_root: str, base: str) -> list[str]:
    """Directories strictly between `projects_root` and `base`.

    These are the ones that must not already be projects: a marker on any of
    them means `base` lives INSIDE an existing project (AUDIT INST-13).
    Returns [] if `base` is not under `projects_root`.
    """
    root = projects_root.rstrip("/")
    if not base.startswith(root + "/"):
        return []
    rel_parts = [p for p in base[len(root) + 1:].split("/") if p]
    out = []
    for i in range(1, len(rel_parts)):
        out.append(root + "/" + "/".join(rel_parts[:i]))
    return out


def build_remote_script(base: str, owner: str, group: str, slug: str = "",
                        projects_root: str = "") -> str:
    """Bash snippet run on the NAS. Prints one line per folder: created or
    already-existed, then (re-)applies ownership/permissions and reports
    that too. Runs as root via sudo -S so it works regardless of what
    TRUENAS_USER's own uid/gid are.

    Refuses up front (before creating anything) when the target sits inside
    an existing project, or already contains one: discovery PRUNES at
    markers, so marking a container directory hides every real project
    beneath it (AUDIT INST-13).

    Every message is shell-quoted rather than interpolated into a
    double-quoted echo -- this script runs as root and its inputs are free
    text (AUDIT SEC-8).
    """
    lines = ["set -e"]
    base_q = shell_quote(base)
    marker_q = shell_quote(MARKER_FILENAME)

    # --- refusals, before any mkdir ---
    for ancestor in ancestor_dirs(projects_root, base):
        anc_marker_q = shell_quote(f"{ancestor}/{MARKER_FILENAME}")
        msg = (
            f"REFUSING: {ancestor} is already a project (it carries {MARKER_FILENAME}), "
            f"so {base} would be a folder INSIDE that project, not a project of its own. "
            f"Nothing was created. Either pick a target outside it, or -- if the parent "
            f"marker is the mistake -- remove that marker first."
        )
        lines.append(
            f'if echo "$SUDO_PW" | sudo -S -p "" test -e {anc_marker_q}; then '
            f"echo {shell_quote(msg)} >&2; exit {RC_ANCESTOR_MARKER}; fi"
        )

    desc_msg = (
        f"REFUSING: {base} already CONTAINS at least one project (a {MARKER_FILENAME} "
        f"below it, shown above). Marking a container directory hides every real project "
        f"under it from discovery and from the dashboard -- their ticks stop being "
        f"enforceable. Nothing was created. Run setup_tree.py against the individual "
        f"project directories instead."
    )
    lines.append(
        f'if echo "$SUDO_PW" | sudo -S -p "" test -d {base_q}; then '
        f'found=$(echo "$SUDO_PW" | sudo -S -p "" find {base_q} -mindepth 2 '
        f"-name {marker_q} -print -quit 2>/dev/null || true); "
        f'if [ -n "$found" ]; then echo "found marker: $found" >&2; '
        f"echo {shell_quote(desc_msg)} >&2; exit {RC_DESCENDANT_MARKER}; fi; fi"
    )

    lines.append(f'echo "$SUDO_PW" | sudo -S -p "" mkdir -p {base_q}')

    for rel in project_relative_dirs():
        full = f"{base}/{rel}"
        full_q = shell_quote(full)
        lines.append(
            f'if [ -d {full_q} ]; then echo {shell_quote("exists: " + rel)}; '
            f'else echo "$SUDO_PW" | sudo -S -p "" mkdir -p {full_q} '
            f"&& echo {shell_quote('created: ' + rel)}; fi"
        )

    # Project marker: the directory's explicit, slug-carrying identity (see
    # common.MARKER_FILENAME) -- the dashboard's provisioning discovers and
    # tracks projects by this file, at any tree depth. Written only when
    # absent: an existing slug is this project's identity forever (DEL-8).
    if slug:
        lines.append(build_marker_write_cmd(base, slug, only_if_absent=True))

    owner_group = shell_quote(f"{owner}:{group}")
    lines.append(
        f'echo "$SUDO_PW" | sudo -S -p "" chown -R {owner_group} {base_q} '
        f"&& echo {shell_quote(f'ownership set: {owner}:{group} on {base}')}"
    )
    # Non-fatal: some datasets have ZFS aclmode=restricted, which blocks
    # chmod outright (even for root). Ownership above still applies fine in
    # that case; only the setgid bit is missing. `if` conditions are exempt
    # from `set -e`, so this can't abort the rest of the script.
    lines.append(
        f'if echo "$SUDO_PW" | sudo -S -p "" find {base_q} -type d -exec chmod 2770 {{}} + >/dev/null 2>&1; then '
        f"echo {shell_quote(f'permissions set: 2770 (setgid) on all directories under {base}')}; "
        f"else echo {shell_quote('permissions NOT set: chmod blocked on this dataset (likely ZFS aclmode=restricted) -- ownership above is still correct, only the setgid bit is missing')}; fi"
    )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", help="e.g. 2025")
    ap.add_argument("--series", help="e.g. FF4, or \"Creator Profiles\" (quote names with spaces)")
    ap.add_argument("--project", help="e.g. Nuclear")
    ap.add_argument("--project-rel-path",
                     help="arbitrary-depth alternative to --year/--series/--project, "
                          "e.g. \"2026/CCT/Creator Profiles/Season 1\"")
    ap.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT,
                     help=f"default: {DEFAULT_PROJECTS_ROOT}")
    ap.add_argument("--owner", default=DEFAULT_DATASET_OWNER, help=f"default: {DEFAULT_DATASET_OWNER}")
    ap.add_argument("--group", default=EDITORS_GROUP, help=f"default: {EDITORS_GROUP}")
    add_host_key_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)

    if args.project_rel_path:
        if args.year or args.series or args.project:
            ap.error("--project-rel-path is mutually exclusive with --year/--series/--project")
        rel = args.project_rel_path.strip().strip("/")
        base = project_path_rel(args.projects_root, rel)
    elif args.year and args.series and args.project:
        base = project_path(args.projects_root, args.year, args.series, args.project)
        rel = f"{args.year}/{args.series}/{args.project}"
    else:
        ap.error("provide either --project-rel-path or all of --year/--series/--project")
    try:
        slug = validate_slug(slugify(rel))
    except ValueError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(f"Target project root: {base}")
    print(f"Project slug (marker identity): {slug}")
    print(f"  (only written if {MARKER_FILENAME} is absent -- an existing identity is kept)")
    print(f"Template folders ({len(TEMPLATE_FOLDERS)}): {', '.join(TEMPLATE_FOLDERS)}")

    script = build_remote_script(base, args.owner, args.group, slug=slug,
                                 projects_root=args.projects_root)
    rc, out, err = run_ssh(script, dry_run=args.dry_run)

    if args.dry_run:
        print("[dry-run] remote script that would run:")
        print(script)
        return 0

    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)

    if rc in (RC_ANCESTOR_MARKER, RC_DESCENDANT_MARKER):
        # The remote script already explained itself on stderr; nothing was
        # created, so don't dress it up as a generic failure.
        print("Nothing was created.", file=sys.stderr)
        return rc
    if rc != 0:
        print(f"FAILED (remote exit code {rc})", file=sys.stderr)
        return rc

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
