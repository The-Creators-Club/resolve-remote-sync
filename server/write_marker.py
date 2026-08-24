#!/usr/bin/env python3
"""Write (or deliberately change) a project's .ccsync-project marker on the NAS.

    python write_marker.py --project-rel-path "2026/CCT/Creator Profiles/Season 1" \
        --slug 2026-creator-profiles-season-1 [--dry-run]

The marker's slug is the project's IMMUTABLE identity (see the dashboard's
provision.py). This tool exists for adoption/repair cases where the slug
must NOT be derived from the current path -- e.g. a project that was moved
on the NAS keeps its original slug so all dashboard state (ticks, mappings,
history) survives; omit --slug to use slugify(rel) for a fresh identity.

This is the ONLY tool that may change an existing identity, and it will not
do so quietly (AUDIT INST-12):
  - the existing marker is read first and printed;
  - a change is shown as `old -> new` and REFUSED unless --force is given;
  - the slug is validated against ^[a-z0-9-]+$ whether it came from --slug
    or from slugify(), because it becomes a Syncthing folder id and a
    dashboard URL segment.

Changing a live project's slug orphans every slug-keyed row (selections,
Resolve project_roots mappings, completion history, media inventory) and
leaves its Syncthing folder pointing at the old identity. Only do it when
that is what you actually mean.

Env vars: TRUENAS_HOST / TRUENAS_USER / TRUENAS_PW (see server/README.md).
"""
import argparse
import json
import re
import sys

from common import (
    DEFAULT_PROJECTS_ROOT,
    MARKER_FILENAME,
    add_site_arg,
    cli,
    require_site_value,
    add_host_key_arg,
    build_marker_read_cmd,
    build_marker_write_cmd,
    project_path_rel,
    run_ssh,
    set_host_key_pin,
    shell_quote,
    slugify,
    validate_slug,
)


def parse_marker_slug(text: str) -> str:
    """Pull the slug out of a marker file's contents. Tolerates a marker that
    isn't valid JSON (hand-edited, truncated) rather than crashing -- an
    unreadable marker still means "there is an identity here"."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("slug"):
            return str(data["slug"])
    except ValueError:
        pass
    m = re.search(r'"slug"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m else ""


def read_existing_marker(base: str, dry_run: bool) -> tuple[bool, str, str]:
    """Return (present, raw_contents, slug) for the marker at `base`.

    Read as root (the dataset is 770 and TRUENAS_USER has no traverse
    rights). In dry-run mode nothing is connected and (False, "", "") comes
    back, same convention as everywhere else in this package.

    SERVER-4 (2026-08-14): "no marker" must come from the PRIVILEGED shell, not
    from a sudo that failed -- see common.build_marker_read_cmd. It matters more
    here than anywhere: this tool's write is UNCONDITIONAL (only the Python side
    guards an identity change behind --force), so a failed read that reported
    "absent" would take the fresh-identity path and reassign a live project's
    slug without ever showing the operator the `old -> new` line.
    """
    rc, out, err = run_ssh(build_marker_read_cmd(base), dry_run=dry_run)
    if dry_run:
        return False, "", ""
    if rc != 0:
        print(f"FAILED to read the existing marker: {err.strip() or out.strip()}",
              file=sys.stderr)
        sys.exit(1)
    lines = out.splitlines()
    if "MARKER-PRESENT" not in lines:
        if "MARKER-ABSENT" not in lines:
            print(f"FAILED to read the existing marker at {base}: the read printed "
                  f"neither MARKER-PRESENT nor MARKER-ABSENT, so whether this "
                  f"project already has an identity is unknown "
                  f"({(err.strip() or out.strip())[:200]!r}). REFUSING to write a "
                  f"fresh one over it.", file=sys.stderr)
            sys.exit(1)
        return False, "", ""
    idx = lines.index("MARKER-PRESENT")
    raw = "\n".join(lines[idx + 1:]).strip()
    return True, raw, parse_marker_slug(raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-rel-path", required=True,
                     help='e.g. "2026/CCT/Creator Profiles/Season 1"')
    ap.add_argument("--slug", default="",
                     help="identity to write; default = slugify(rel path)")
    ap.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT)
    ap.add_argument("--created-by", default="write_marker")
    ap.add_argument("--force", action="store_true",
                     help="required to CHANGE an existing marker's slug (writing a "
                          "marker where there is none never needs it)")
    add_host_key_arg(ap)
    add_site_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)
    args.projects_root = require_site_value(
        args.projects_root, "[tree] pool_root/tree_name", "--projects-root")

    rel = args.project_rel_path.strip().strip("/")
    base = project_path_rel(args.projects_root, rel)
    try:
        slug = validate_slug(args.slug.strip() or slugify(rel))
    except ValueError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(f"Target: {base}")
    print(f"Slug:   {slug}")

    present, raw, old_slug = read_existing_marker(base, args.dry_run)
    if present:
        print(f"existing marker: {raw}")
        if old_slug == slug:
            print(f"identity unchanged: {old_slug} (re-writing the same marker)")
        else:
            print(f"identity CHANGE: {old_slug or '<unreadable>'} -> {slug}")
            if not args.force:
                print(
                    f"REFUSING to change an existing project identity without --force.\n"
                    f"  {base} already carries {MARKER_FILENAME} with slug "
                    f"{old_slug or '<unreadable>'!r}.\n"
                    f"  Every dashboard row for this project (ticks, Resolve mappings, "
                    f"completion history, media inventory) is keyed on that slug, and its "
                    f"Syncthing folder id is derived from it -- rewriting it orphans all of "
                    f"them.\n"
                    f"  If you meant to keep the original identity (the usual case after a "
                    f"move), pass --slug {old_slug or '<the-original-slug>'}.\n"
                    f"  If you really do mean to reassign it, re-run with --force.",
                    file=sys.stderr)
                return 3
            print("--force given: reassigning this project's identity.")
    elif not args.dry_run:
        print(f"no existing marker at {base}/{MARKER_FILENAME} -- writing a fresh identity")

    # Additive marker keys (`includes` and anything future, SHARED_FOLDERS_PLAN.md
    # §2.1) survive the rewrite: the write here merges over what was read.
    # An unparseable existing marker has nothing recoverable to preserve.
    preserved: dict = {}
    if present:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                preserved = {k: v for k, v in data.items() if k not in ("slug", "created_by")}
        except ValueError:
            print("existing marker is not valid JSON; its non-identity keys "
                  "cannot be preserved", file=sys.stderr)
    extra = sorted(k for k in preserved if k != "created_at")
    if extra:
        print(f"preserving additive marker keys: {', '.join(extra)}")

    base_q = shell_quote(base)
    missing_msg = shell_quote(f"MISSING: {base}")
    script = "\n".join([
        "set -e",
        f'echo "$SUDO_PW" | sudo -S -p "" test -d {base_q} || {{ echo {missing_msg} >&2; exit 2; }}',
        build_marker_write_cmd(base, slug, created_by=args.created_by, extra_keys=preserved),
    ])
    rc, out, err = run_ssh(script, dry_run=args.dry_run)
    if args.dry_run:
        print("[dry-run] would first read any existing marker and refuse a slug change "
              "without --force")
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
    sys.exit(cli(main))
