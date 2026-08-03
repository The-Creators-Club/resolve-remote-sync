#!/usr/bin/env python3
"""Create (or update) one Syncthing folder for a project, lane C only.

    python setup_syncthing_folder.py --project-rel-path 2025/FF4/Nuclear \\
        --gui-url http://192.168.0.102:8384 --api-key XXXX [--dry-run]

`--project-rel-path` is relative to Creators_Club/Projects on the mount
(e.g. "2025/FF4/Nuclear"), matching the args passed to setup_tree.py's
--year/--series/--project (year/series/project joined with '/').

Steps, all via the Syncthing REST API (server/README.md documents where the
GUI URL + API key come from -- Syncthing app config, or its config.xml):

  1. Work out the folder id. It is the project's IMMUTABLE identity, NOT a
     function of its current path -- see WHICH FOLDER ID below.
  2. GET /rest/config/folders -- if a folder with that id already exists,
     compare its path with the one we would use:
       - same path  -> skip creation (idempotent) unless --force is given;
       - DIFFERENT path -> refuse and print both. Slugs are lossy ("Season 1",
         "Season-1" and "Season_1" all slugify to "season-1"), so a matching
         id with a different path means two distinct projects are colliding
         on one folder id -- silently skipping there would leave the second
         project sharing the first one's folder (AUDIT §9). Use --force only
         if you genuinely mean to RETARGET the existing folder.
     ...and, before creating anything, refuse if some OTHER folder id already
     points at this same path (see WHICH FOLDER ID).
  3. POST /rest/config/folders with:
       - path = <container-mount>/Projects/<project-rel-path>
       - type: sendreceive
       - fsWatcherEnabled: true
       - versioning: staggered (server-side deletion safety net, per SPEC
         "Flaws" #2 -- lane C keeps versioned trash even though renames
         propagate)
  4. POST /rest/db/ignores?folder=<id> with the .stignore content: one
     case-insensitive line per video extension, plus **/Proxy -- videos and
     proxies never travel through Syncthing (lanes A/B, rclone, handle
     those).

WHICH FOLDER ID
---------------
A project's identity is the slug inside its .ccsync-project marker, and it is
IMMUTABLE: it travels with the directory so that moving or renaming a project
retargets its existing folder instead of looking like a delete plus a brand-new
project. The dashboard collector is the authority and reads exactly that
(dashboard/src/ccsync_dashboard/provision.py's read_marker / MARKER_FILENAME).

This script used to derive the id with slugify(--project-rel-path) alone. For a
project that had MOVED, that disagrees with the marker: find_folder missed the
real folder and this script created a SECOND Syncthing folder over the same
directory -- one no editor is shared with, that fails the collector every cycle,
and that nothing ever cleans up. So the id is resolved, in order:

  1. --slug           explicit, validated. Use this when you cannot reach the
                      NAS over SSH but you know the identity (read it off the
                      dashboard, or `cat` the marker yourself).
  2. the marker       read over SSH from <--projects-root>/<rel>/.ccsync-project
                      and validated against the same ^[a-z0-9-]+$ every sibling
                      applies. Authoritative when present.
  3. slugify(rel)     ONLY when the directory genuinely carries no marker (a
                      project that predates markers, or one being set up before
                      setup_tree.py ran). Printed as a note, never silent.

A marker that exists but cannot be read or parsed is a REFUSAL, not a fallback:
creating a divergent id is the failure this ordering exists to prevent. Pass
--no-marker-read to skip step 2 deliberately (it then goes straight to step 3),
and --slug to skip it because you already know the answer.

Belt-and-braces regardless of how the id was chosen: before creating or
retargeting, the script refuses if a DIFFERENT folder id already points at the
requested path. The collector refuses to add to that confusion from its side;
this script must not create it in the first place.

Sharing the folder to a specific editor's device is NOT done here --
see accept_device.py, run once per (device, folder) after the editor's
Syncthing device ID is known.

Env vars: SYNCTHING_GUI_URL / SYNCTHING_API_KEY are read as fallback defaults
for --gui-url / --api-key. TRUENAS_HOST / TRUENAS_USER / TRUENAS_PW are needed
ONLY for the marker read (step 2 above) -- with --slug, --no-marker-read or
--dry-run this script still talks to nothing but Syncthing, so it can target
any Syncthing instance.
"""
import argparse
import os
import sys

from common import (
    DEFAULT_PROJECTS_ROOT,
    MARKER_FILENAME,
    add_host_key_arg,
    build_stignore_lines,
    ok,
    project_path_rel,
    run_ssh,
    set_host_key_pin,
    shell_quote,
    slugify,
    syncthing_api,
    validate_slug,
)
# The marker's format is owned by write_marker.py -- the tool that writes it
# and the only one allowed to change an identity. Importing its parser rather
# than copying it is deliberate: a second copy of "how do I get the slug out of
# a marker" is exactly the kind of duplication that drifts (it already tolerates
# a hand-edited/truncated marker, which matters here because an unparseable
# marker must be a refusal, not a silent fallback). write_marker.py has no
# import-time side effects.
from write_marker import parse_marker_slug

CONTAINER_MOUNT_DEFAULT = "/data"  # must match install_syncthing_app.py's --container-mount

# WAN pull tuning. Byte-for-byte the values the dashboard's collector applies
# when IT creates a folder (dashboard/src/ccsync_dashboard/provision.py's
# build_folder_config, AUDIT_2 P6/§4.2) -- keep the two in sync.
#
# They live here because a --force PUT sends a COMPLETE folder object: every
# key absent from it is reset to the Syncthing default. Omitting them meant
# re-running --force to repair a path silently dropped a project back to
# maxConcurrentWrites=2 over the WAN, permanently and with nothing logged --
# unlike .stignore, folder settings have no repair pass anywhere (B19). And
# folders created by this script rather than by the collector never got the
# tuning in the first place.
#
# maxConcurrentWrites raises in-flight block writes from Syncthing's default
# of 2; pullerMaxPendingKiB (64 MiB) lets the puller keep more blocks in
# flight on a high-latency link. copiers/hashers stay unset (0 == auto):
# pinning them is how you starve a box with many folders.
FOLDER_PULL_TUNING = {
    "maxConcurrentWrites": 32,
    "pullerMaxPendingKiB": 65536,
}


def paths_differ(existing_path: str, requested_path: str) -> bool:
    """True if an existing folder's path is not the one we were asked for.
    Trailing slashes are noise, not a difference."""
    return str(existing_path or "").rstrip("/") != str(requested_path or "").rstrip("/")


def path_conflict_message(folder_id: str, existing_path: str, requested_path: str) -> str:
    """Why we refuse to reuse a folder id that points somewhere else."""
    return (
        f"REFUSING: folder id {folder_id!r} already exists but points somewhere else.\n"
        f"  existing path:  {existing_path or '<none>'}\n"
        f"  requested path: {requested_path}\n"
        f"  Folder ids are slugified, so different project names collapse onto one id "
        f'("Season 1", "Season-1" and "Season_1" all become "season-1"). Reusing this '
        f"folder would point every editor already sharing it at a different project's "
        f"tree, and lane C would then reconcile the two.\n"
        f"  Rename one of the projects so the ids differ, or -- if you really do mean to "
        f"RETARGET this folder at the new path -- re-run with --force."
    )


def find_folder(gui_url: str, api_key: str, folder_id: str, dry_run: bool):
    resp = syncthing_api("GET", gui_url, "/rest/config/folders", api_key, dry_run=dry_run)
    if dry_run:
        return None
    if not ok(resp):
        print(f"FAILED to list folders: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    for f in resp.json():
        if f.get("id") == folder_id:
            return f
    return None


def find_folder_by_path(gui_url: str, api_key: str, path: str, folder_id: str, dry_run: bool):
    """The existing folder that already points at `path` under a DIFFERENT id,
    or None. Two Syncthing folders over one directory is the moved-project
    failure mode: the collector's folder (keyed on the marker slug) and a
    stale slugify(rel) one, both indexing the same tree."""
    resp = syncthing_api("GET", gui_url, "/rest/config/folders", api_key, dry_run=dry_run)
    if dry_run:
        return None
    if not ok(resp):
        print(f"FAILED to list folders: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    for f in resp.json():
        if f.get("id") != folder_id and not paths_differ(str(f.get("path", "")), path):
            return f
    return None


def duplicate_path_message(folder_id: str, existing_id: str, path: str) -> str:
    """Why we refuse to add a second folder over a directory that already has
    one. Almost always a moved project: the existing id came from the marker
    (via the dashboard collector), ours came from slugify(rel)."""
    return (
        f"REFUSING: folder id {existing_id!r} already points at this exact path, "
        f"but we were about to use {folder_id!r}.\n"
        f"  path: {path}\n"
        f"  Two Syncthing folders over one directory means both index the same "
        f"tree; the second is shared with nobody and fails the dashboard "
        f"collector every cycle, and nothing ever cleans it up.\n"
        f"  This is what a MOVED project looks like: {existing_id!r} is the "
        f"project's immutable identity from its {MARKER_FILENAME} marker, while "
        f"{folder_id!r} was derived from its current path.\n"
        f"  Re-run with --slug {existing_id} to operate on the real folder, or "
        f"fix the marker with write_marker.py if the identity itself is wrong."
    )


# -- marker read (the project's immutable identity) ---------------------------

# read_marker_slug's status values. The detail string carries the slug for
# "present" and a human explanation for everything else.
MARKER_PRESENT = "present"
MARKER_ABSENT = "absent"
MARKER_INVALID = "invalid"
MARKER_UNAVAILABLE = "unavailable"


def read_marker_slug(projects_root: str, rel: str) -> tuple[str, str]:
    """Read a project's identity from its .ccsync-project marker over SSH.

    Returns (status, detail):
      MARKER_PRESENT     detail is the validated slug -- authoritative.
      MARKER_ABSENT      no marker here; slugify(rel) is the right identity.
      MARKER_INVALID     a marker exists but its slug is missing/malformed.
      MARKER_UNAVAILABLE could not read it at all (no TRUENAS_PW, host down,
                         permission denied). NOT the same as absent.

    Read as root: the dataset is 770 and TRUENAS_USER has no traverse rights
    (same command shape as write_marker.read_existing_marker). Never raises --
    every failure becomes MARKER_UNAVAILABLE so the caller can refuse cleanly
    instead of unwinding a stack trace over a missing env var.
    """
    try:
        base = project_path_rel(projects_root, rel)
    except ValueError as exc:
        return MARKER_UNAVAILABLE, str(exc)

    marker_q = shell_quote(f"{base}/{MARKER_FILENAME}")
    cmd = (f'if echo "$SUDO_PW" | sudo -S -p "" test -e {marker_q}; then '
           f'echo "MARKER-PRESENT"; echo "$SUDO_PW" | sudo -S -p "" cat {marker_q}; '
           f'else echo "MARKER-ABSENT"; fi')
    try:
        rc, out, err = run_ssh(cmd, dry_run=False)
    except Exception as exc:
        return MARKER_UNAVAILABLE, f"{type(exc).__name__}: {exc}"
    if rc != 0:
        return MARKER_UNAVAILABLE, ((err or "").strip() or (out or "").strip())[:200]

    lines = (out or "").splitlines()
    if "MARKER-PRESENT" not in lines:
        return MARKER_ABSENT, base
    raw = "\n".join(lines[lines.index("MARKER-PRESENT") + 1:]).strip()
    slug = parse_marker_slug(raw)
    if not slug:
        return MARKER_INVALID, f"marker at {base}/{MARKER_FILENAME} carries no slug: {raw[:160]!r}"
    try:
        return MARKER_PRESENT, validate_slug(slug)
    except ValueError as exc:
        return MARKER_INVALID, f"marker at {base}/{MARKER_FILENAME}: {exc}"


def choose_folder_id(rel: str, explicit_slug: str, marker_status: str,
                     marker_detail: str) -> tuple[str, str, str]:
    """Decide the Syncthing folder id. Pure -- all the I/O happened already.

    Returns (folder_id, source, refusal). A non-empty `refusal` means do
    nothing at all and folder_id is "". See WHICH FOLDER ID in the module
    docstring for why the order is what it is.
    """
    explicit_slug = str(explicit_slug or "").strip()
    if explicit_slug:
        try:
            return validate_slug(explicit_slug), "--slug", ""
        except ValueError as exc:
            return "", "", f"FAILED: invalid --slug: {exc}"

    if marker_status == MARKER_PRESENT:
        return marker_detail, f"the project's {MARKER_FILENAME} marker", ""

    if marker_status == MARKER_ABSENT:
        try:
            return slugify(rel), "slugify(--project-rel-path)", ""
        except ValueError as exc:
            return "", "", f"FAILED: {exc}"

    if marker_status == MARKER_INVALID:
        return "", "", (
            f"REFUSING: this project HAS a {MARKER_FILENAME} marker, but its identity "
            f"could not be read.\n"
            f"  {marker_detail}\n"
            f"  Falling back to slugify(--project-rel-path) here would create a folder "
            f"under a DIFFERENT id from the one the dashboard collector uses, i.e. a "
            f"second Syncthing folder over the same directory.\n"
            f"  Repair the marker with write_marker.py, or pass --slug <identity> if you "
            f"already know it."
        )

    return "", "", (
        f"REFUSING: could not read this project's {MARKER_FILENAME} marker, so its "
        f"identity is unknown.\n"
        f"  {marker_detail}\n"
        f"  The marker's slug is the project's immutable identity and the id the "
        f"dashboard collector uses; guessing it from the current path is only correct "
        f"for a project that has never moved.\n"
        f"  Fix by one of:\n"
        f"    --slug <identity>   you already know it (dashboard, or cat the marker)\n"
        f"    set TRUENAS_PW      (plus TRUENAS_HOST / TRUENAS_USER) so the marker can "
        f"be read over SSH\n"
        f"    --no-marker-read    accept slugify(--project-rel-path); correct only for "
        f"a project that has never moved"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-rel-path", required=True,
                     help='e.g. 2025/FF4/Nuclear or "2026/Creator Profiles/Season 1"')
    ap.add_argument("--gui-url", default=os.environ.get("SYNCTHING_GUI_URL"),
                     help="e.g. http://192.168.0.102:8384 (or SYNCTHING_GUI_URL env var)")
    ap.add_argument("--api-key", default=os.environ.get("SYNCTHING_API_KEY"),
                     help="Syncthing API key (or SYNCTHING_API_KEY env var)")
    ap.add_argument("--container-mount", default=CONTAINER_MOUNT_DEFAULT,
                     help=f"where Creators_Club is mounted inside the Syncthing app, default {CONTAINER_MOUNT_DEFAULT}")
    ap.add_argument("--label", default=None, help="human-readable folder label, defaults to --project-rel-path")
    ap.add_argument("--force", action="store_true", help="recreate config even if the folder id already exists")
    # -- folder identity (see WHICH FOLDER ID in the module docstring) --
    ap.add_argument("--slug", default="",
                     help="the project's identity (its .ccsync-project slug). Skips the "
                          "marker read entirely -- use it when you know the identity but "
                          "cannot reach the NAS over SSH")
    ap.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT,
                     help=f"HOST-side path the marker is read from (not the container "
                          f"mount), default {DEFAULT_PROJECTS_ROOT}")
    ap.add_argument("--no-marker-read", action="store_true",
                     help="do not read the project's marker over SSH; derive the id from "
                          "--project-rel-path. Correct ONLY for a project that has never "
                          "moved")
    add_host_key_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)

    if not args.dry_run and not args.gui_url:
        print("FAILED: --gui-url is required (or set SYNCTHING_GUI_URL)", file=sys.stderr)
        return 1
    if not args.dry_run and not args.api_key:
        print("FAILED: --api-key is required (or set SYNCTHING_API_KEY)", file=sys.stderr)
        return 1

    gui_url = args.gui_url or "<gui-url-unset-dry-run>"
    api_key = args.api_key or "<api-key-unset-dry-run>"

    rel = args.project_rel_path.strip("/").replace("\\", "/")
    # Every sibling script routes an arbitrary-depth rel path through
    # common.project_path_rel, which validates each segment. This one built the
    # path by f-string, so --project-rel-path "../../etc" produced folder id
    # "etc" at /data/Projects/../../etc and would have sendreceive-synced the
    # container's /etc to every editor sharing it.
    try:
        path = project_path_rel(f"{args.container_mount.rstrip('/')}/Projects", rel)
    except ValueError as exc:
        print(f"FAILED: invalid --project-rel-path {args.project_rel_path!r}: {exc}",
              file=sys.stderr)
        return 1
    # -- the folder id is the project's IMMUTABLE identity, not a function of
    # its current path. See WHICH FOLDER ID in the module docstring.
    marker_status, marker_detail = MARKER_ABSENT, ""
    if args.slug:
        pass  # explicit identity wins; no SSH needed at all
    elif args.no_marker_read:
        print(f"--no-marker-read: not consulting the project's {MARKER_FILENAME} marker; "
              f"the id below is derived from --project-rel-path and is only correct for a "
              f"project that has never moved.")
    elif args.dry_run:
        # --dry-run opens no connection, in every script in this package. Say
        # plainly that the real run resolves the id differently rather than
        # implying this one is the answer.
        print(f"[dry-run] would read {args.projects_root}/{rel}/{MARKER_FILENAME} over SSH "
              f"for this project's identity; showing the slugify(--project-rel-path) id "
              f"below instead, which differs for a project that has moved.")
    else:
        marker_status, marker_detail = read_marker_slug(args.projects_root, rel)

    folder_id, id_source, refusal = choose_folder_id(
        rel, args.slug, marker_status, marker_detail)
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    if marker_status == MARKER_ABSENT and not args.slug and not args.no_marker_read \
            and not args.dry_run:
        print(f"note: no {MARKER_FILENAME} at {marker_detail} -- using the id derived from "
              f"--project-rel-path. Run setup_tree.py (or write_marker.py) to give this "
              f"project a permanent identity before it is ever moved.")

    label = args.label or rel

    print(f"project-rel-path: {rel}")
    print(f"folder id: {folder_id}  (from {id_source})")
    print(f"folder path (inside Syncthing app): {path}")

    existing = find_folder(gui_url, api_key, folder_id, args.dry_run)
    if existing:
        existing_path = str(existing.get("path", ""))
        if paths_differ(existing_path, path):
            if not args.force:
                print(path_conflict_message(folder_id, existing_path, path), file=sys.stderr)
                return 1
            print(f"--force given: RETARGETING folder {folder_id} "
                  f"from {existing_path or '<none>'} to {path}")
        else:
            print(f"folder id {folder_id} already points at the requested path: {existing_path}")

    if existing and not args.force:
        print(f"folder already exists, skipping create: {folder_id} (use --force to reconfigure)")
    else:
        # Belt-and-braces, whatever the id came from: never put a SECOND folder
        # over a directory that already has one. This is the moved-project
        # failure in its final form -- the collector's marker-slug folder is
        # already there and we are about to add a slugify(rel) twin beside it.
        # Runs for --force too: retargeting our id onto an occupied path is the
        # same duplication.
        twin = find_folder_by_path(gui_url, api_key, path, folder_id, args.dry_run)
        if twin:
            print(duplicate_path_message(folder_id, str(twin.get("id", "")), path),
                  file=sys.stderr)
            return 1

        folder_config = {
            "id": folder_id,
            "label": label,
            "path": path,
            "type": "sendreceive",
            "fsWatcherEnabled": True,
            # aclmode=restricted on the dataset forbids chmod, which
            # Syncthing otherwise uses to mirror permissions — without this
            # every dir touch fails with "operation not permitted" and
            # transfers stall at the .syncthing.*.tmp stage (seen live).
            "ignorePerms": True,
            "rescanIntervalS": 3600,
            # A --force PUT replaces the whole folder object, so these MUST be
            # here or the WAN puller tuning is silently reset (B19). See
            # FOLDER_PULL_TUNING above.
            **FOLDER_PULL_TUNING,
            "versioning": {
                "type": "staggered",
                "params": {
                    "cleanInterval": "3600",
                    "maxAge": "31536000",
                },
            },
            # editors are added later, per-device, via accept_device.py; on a
            # --force reconfigure, preserve the existing device shares rather
            # than wiping them back to [].
            "devices": (existing or {}).get("devices", []),
        }
        if existing:
            print(f"--force given, updating existing folder: {folder_id}")
            resp = syncthing_api("PUT", gui_url, f"/rest/config/folders/{folder_id}", api_key,
                                  json_body=folder_config, dry_run=args.dry_run)
        else:
            resp = syncthing_api("POST", gui_url, "/rest/config/folders", api_key,
                                  json_body=folder_config, dry_run=args.dry_run)
        if not args.dry_run:
            if not ok(resp):
                print(f"FAILED to create/update folder: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
                return 1
            print(f"{'updated' if existing else 'created'} folder: {folder_id} "
                  f"(sendreceive, staggered versioning, fsWatcher on)")

    ignore_lines = build_stignore_lines()
    print(f".stignore ({len(ignore_lines)} lines):")
    for line in ignore_lines:
        print(f"  {line}")

    resp = syncthing_api("POST", gui_url, "/rest/db/ignores", api_key,
                          params={"folder": folder_id},
                          json_body={"ignore": ignore_lines}, dry_run=args.dry_run)
    if not args.dry_run:
        if not ok(resp):
            print(f"FAILED to set ignore patterns: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        print(f"ignore patterns applied to folder: {folder_id}")

    print("Done. Next: accept_device.py to share this folder with each editor's device ID.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
