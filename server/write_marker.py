#!/usr/bin/env python3
"""Write (or overwrite) a project's .ccsync-project marker on the NAS.

    python write_marker.py --project-rel-path "2026/CCT/Creator Profiles/Season 1" \
        --slug 2026-creator-profiles-season-1 [--dry-run]

The marker's slug is the project's IMMUTABLE identity (see the dashboard's
provision.py). This tool exists for adoption/repair cases where the slug
must NOT be derived from the current path -- e.g. a project that was moved
on the NAS keeps its original slug so all dashboard state (ticks, mappings,
history) survives; omit --slug to use slugify(rel) for a fresh identity.

Env vars: TRUENAS_HOST / TRUENAS_USER / TRUENAS_PW (see server/README.md).
"""
import argparse
import sys

from common import (
    DEFAULT_PROJECTS_ROOT,
    build_marker_write_cmd,
    project_path_rel,
    run_ssh,
    shell_quote,
    slugify,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-rel-path", required=True,
                     help='e.g. "2026/CCT/Creator Profiles/Season 1"')
    ap.add_argument("--slug", default="",
                     help="identity to write; default = slugify(rel path)")
    ap.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT)
    ap.add_argument("--created-by", default="write_marker")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rel = args.project_rel_path.strip().strip("/")
    base = project_path_rel(args.projects_root, rel)
    slug = args.slug.strip() or slugify(rel)
    print(f"Target: {base}")
    print(f"Slug:   {slug}")

    base_q = shell_quote(base)
    script = "\n".join([
        "set -e",
        f'echo "$SUDO_PW" | sudo -S -p "" test -d {base_q} || {{ echo "MISSING: {base}"; exit 2; }}',
        build_marker_write_cmd(base, slug, created_by=args.created_by),
    ])
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
