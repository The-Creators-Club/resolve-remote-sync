#!/usr/bin/env python3
"""Create the Creators_Club project template tree on the NAS, over SSH.

    python setup_tree.py --year 2025 --series FF4 --project Nuclear [--dry-run]
    python setup_tree.py --year 2026 --series "Creator Profiles" --project "Season 1"

Any year/series/project is valid; names with spaces work as long as they are
quoted (they are shell-quoted before being sent to the NAS).

Creates:
    <tree root>/Projects/<year>/<series>/<project>/     # e.g.
    #   /mnt/<pool>/<dataset>/Creators_Club/Projects/2025/FF4/Nuclear
        AE/
        Audio/Music/
        Audio/Voiceover/
        B-roll/
        Interviewees/
        "Render in Place"/
        Subs/
        Youtube/

Then makes the tree group-writable the way this NAS does it -- on TrueNAS,
ownership <dataset owner>:editors and mode 2770 (setgid, so files/dirs created
later by any editors-group member inherit the group and stay group-rwx),
recursively on the whole project directory; the step comes from the backend
(server/backends/), because a Synology shared folder's Windows-style ACLs
override mode bits and need an inheritable ACE instead. Proxy/
subfolders are NOT created here -- the Blackmagic Proxy Generator creates
them on demand next to media.

Idempotent: every mkdir is preceded by a PRIVILEGED `test -d` check so
re-running only reports "already exists" for what's there and creates what's
missing; chown/chmod are always re-applied (cheap, safe, and self-healing if
permissions drifted). Privileged because TRUENAS_USER has no traverse rights on
the 770 dataset, so an unprivileged probe false-negatives on a tree that is
right there (SERVER-9, 2026-08-14).

Identity-safe, by design:
  - the .ccsync-project marker is written only when ABSENT. Re-running this
    against a project that was created under a different path keeps its
    original slug and says so; changing a project's identity is a deliberate
    act that lives in write_marker.py --slug ... --force.
  - the run is REFUSED (exit 3/4, nothing created) if any directory between
    the projects root and the target already carries a marker, or if the
    target already contains one. Discovery prunes at markers, so marking a
    container directory would hide every real project underneath it.

Env vars: TRUENAS_HOST / TRUENAS_USER (no defaults -- they come from [nas]
host / admin_user in site.toml, see docs/SERVER.md), TRUENAS_PW (required). See server/README.md.
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
    add_nas_kind_arg,
    add_site_arg,
    build_marker_write_cmd,
    cli,
    get_backend,
    project_acl_mode,
    project_group_name,
    project_path,
    project_path_rel,
    project_relative_dirs,
    require_site_value,
    run_ssh,
    set_host_key_pin,
    shell_quote,
    slugify,
    snapshot_before,
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
                        projects_root: str = "", backend=None,
                        project_group: str = "") -> str:
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

    # SERVER-9 (2026-08-14): the probe runs with the SAME privilege as the
    # mkdir. It used to be a bare `[ -d ]`, i.e. as TRUENAS_USER, who has no
    # traverse rights on the 770 dataset (check_health.check_tree and
    # setup_syncthing_folder.read_marker_slug both say so) -- so on a re-run it
    # false-negatived on every template folder and the output was eight
    # `created:` lines, indistinguishable from having just built a fresh tree at
    # a mistyped path. mkdir -p made that harmless; the REPORT was the damage,
    # and the module docstring promises idempotency.
    for rel in project_relative_dirs():
        full = f"{base}/{rel}"
        full_q = shell_quote(full)
        lines.append(
            f'if echo "$SUDO_PW" | sudo -S -p "" test -d {full_q}; then '
            f'echo {shell_quote("exists: " + rel)}; '
            f'else echo "$SUDO_PW" | sudo -S -p "" mkdir -p {full_q} '
            f"&& echo {shell_quote('created: ' + rel)}; fi"
        )

    # Project marker: the directory's explicit, slug-carrying identity (see
    # common.MARKER_FILENAME) -- the dashboard's provisioning discovers and
    # tracks projects by this file, at any tree depth. Written only when
    # absent: an existing slug is this project's identity forever (DEL-8).
    if slug:
        lines.append(build_marker_write_cmd(base, slug, only_if_absent=True))

    # Group-write, the platform's way: `chown -R` + `chmod 2770` on ZFS,
    # inheritable ACEs on a Synology shared folder (whose Windows-style ACLs
    # override mode bits outright). Backend-supplied lines rather than an
    # executed step, because this script sends ONE script down ONE ssh session
    # and server/tests runs that script under a stub sudo (2026-08-17).
    #
    # With [stack] project_acl = "per-project" the subtree belongs to
    # proj-<slug> instead of the fleet-wide editors group, and the containers
    # above it get the sticky bit -- otherwise per-project groups protect
    # nothing, since deleting a directory needs write on its PARENT
    # (docs/TENANCY.md, COMMERCIAL_READINESS.md item 7).
    containers = ([projects_root.rstrip("/")] + ancestor_dirs(projects_root, base)
                  if project_group and projects_root else [])
    lines.extend((backend or get_backend()).set_tree_acl(
        base, owner, group, project_group=project_group, container_dirs=containers))
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
    add_site_arg(ap)
    add_nas_kind_arg(ap)
    ap.add_argument("--require-snapshot", action="store_true",
                     help="stop (exit 2, nothing created) if the pre-chown snapshot "
                          "cannot be taken. Default is best-effort: warn and continue, "
                          "because a NAS with no snapshot API must not be a NAS where "
                          "projects cannot be created.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)
    backend = get_backend(args)
    args.projects_root = require_site_value(
        args.projects_root, "[tree] pool_root/tree_name", "--projects-root")

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

    # Per-project isolation, off unless the site asks for it (docs/TENANCY.md).
    # The group is created through the platform's identity API rather than a
    # `groupadd` in the remote script, so it is the same object the dashboard's
    # provisioner and setup_editor_account.py --project manage membership on.
    project_group = ""
    if project_acl_mode() == "per-project":
        project_group = project_group_name(slug)
        print(f"Per-project ACL: {base} will belong to {args.owner}:{project_group}, "
              f"and the directories above it get the sticky bit")
        backend.ensure_group(project_group, args.dry_run)

    script = build_remote_script(base, args.owner, args.group, slug=slug,
                                 projects_root=args.projects_root, backend=backend,
                                 project_group=project_group)

    # The script below ends in `chown -R` + a recursive chmod, as root, against
    # a path assembled from free text. That is the single most expensive thing
    # this package can get wrong, and until 2026-08-17 there was nothing behind
    # it (COMMERCIAL_READINESS.md item 8). Snapshot first; best-effort unless
    # --require-snapshot, and it is the whole tree that is snapshotted, not
    # `base`, because a snapshot is per dataset/share.
    snapshot_before("setup_tree", args.projects_root, dry_run=args.dry_run,
                    require=args.require_snapshot, backend=backend)

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
    sys.exit(cli(main))
