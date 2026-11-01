"""Per-project access: a dashboard tick is membership of `proj-<slug>`
(GL-19 / COM-H15, CR-368 follow-up, 2026-10-07; docs/TENANCY.md).

Under `project_acl = per-project` (the default for a NEW site; the studio keeps
`shared` in its own site.toml) a project directory is 2770 <owner>:proj-<slug>,
so an editor reaches it only through that group. Until now only the base-rig
`setup_editor_account.py --project` added anyone to it, which a customer who
installs the appliance cannot run: a project was either shared with everyone
(created through /project-setup) or closed to every ticked editor (created by
setup_tree). This module closes that gap on the dashboard's own side:

* `reconcile` runs after every enforce cycle (a tick nudges one) and makes each
  known editor's membership of the proj- groups of KNOWN projects equal what
  they have ticked, on any of their computers and in either mode (an
  upload-only tick still writes). Groups it did not derive from a registered
  project slug are never touched, and an editor is never added to a group they
  did not tick: under-sharing is the safe direction.
* Membership has THREE sources, because a tick is not enough (CR-368 round 2,
  2026-10-07): a tick (a synced editor), an explicit per-project GRANT an admin
  stores here (`grant`, `PUT /api/v1/projects/{slug}/access/{editor}`; the only
  way in for a wired editor, whose tick the API refuses with a 409 because they
  work on the NAS directly), and the dashboard's own LEDGER. The ledger records
  which groups THIS module added; reconcile removes only a group in the ledger
  (or one it is about to add), so a membership made by `setup_editor_account.py
  --project` or by hand in the NAS UI is never revoked.
* `close_new_project_dir` makes a project this dashboard has just created
  2770 <owner>:proj-<slug> at once, so it starts private, not shared.

Everything is best-effort and inert: a `shared` site, a NAS backend without the
capability (DSM: PARTIAL, docs/SERVER-SYNOLOGY.md) or a NAS that cannot be
reached changes nothing and never fails a tick, a project create or the
collector. The name derivation is pinned equal to server/common.py's.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from typing import Any

from . import db
from .nas import capability, make_nas_client, nas_configured

log = logging.getLogger("ccsync.dashboard.project_groups")

PROJECT_GROUP_PREFIX = "proj-"
PROJECT_GROUP_MAXLEN = 32
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_warned_no_capability = False
META_GRANTS = "project_group_grants"      # {slug: [editor, ...]} admin grants
META_LEDGER = "project_group_ledger"      # {editor: [group, ...]} what we added


def grants(conn: sqlite3.Connection) -> dict[str, list[str]]:
    raw = db.meta_get_json(conn, META_GRANTS)
    if not isinstance(raw, dict):
        return {}
    return {str(k): sorted({str(e) for e in v}) for k, v in raw.items() if isinstance(v, list)}


def grant(conn: sqlite3.Connection, slug: str, editor: str) -> bool:
    """Record an explicit grant. True when it was new. Caller commits."""
    cur = grants(conn)
    members = set(cur.get(slug, []))
    if editor in members:
        return False
    members.add(editor)
    cur[slug] = sorted(members)
    db.meta_set_json(conn, META_GRANTS, cur)
    return True


def revoke(conn: sqlite3.Connection, slug: str, editor: str) -> bool:
    cur = grants(conn)
    members = set(cur.get(slug, []))
    if editor not in members:
        return False
    members.discard(editor)
    if members:
        cur[slug] = sorted(members)
    else:
        cur.pop(slug, None)
    db.meta_set_json(conn, META_GRANTS, cur)
    return True


def _ledger(conn: sqlite3.Connection) -> dict[str, set[str]]:
    raw = db.meta_get_json(conn, META_LEDGER)
    if not isinstance(raw, dict):
        return {}
    return {str(k): {str(n) for n in v} for k, v in raw.items() if isinstance(v, list)}


def enabled(settings: Any) -> bool:
    return str(getattr(settings, "project_acl", "") or "").strip().lower() == "per-project"


def group_name(slug: str) -> str:
    """Same derivation as server/common.project_group_name (a test pins it)."""
    slug = str(slug or "").strip()
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}")
    name = f"{PROJECT_GROUP_PREFIX}{slug}"
    if len(name) <= PROJECT_GROUP_MAXLEN:
        return name
    digest = hashlib.sha256(slug.encode()).hexdigest()[:6]
    head = name[: PROJECT_GROUP_MAXLEN - 7].rstrip("-")
    return f"{head}-{digest}"


def desired_membership(conn: sqlite3.Connection) -> tuple[dict[str, set[str]], dict[str, str]]:
    """({editor: {group names they ticked}}, {slug: group name} for every
    registered, unarchived project)."""
    slugs: dict[str, str] = {}
    for row in conn.execute("SELECT slug FROM projects WHERE archived_at IS NULL"):
        try:
            slugs[str(row[0])] = group_name(str(row[0]))
        except ValueError:
            continue
    want: dict[str, set[str]] = {}
    for editor in db.known_editor_usernames(conn):
        want[editor] = set()
    for editor, slug in conn.execute(
            "SELECT DISTINCT editor_username, project_slug FROM selections"):
        if slug in slugs and editor in want:
            want[str(editor)].add(slugs[slug])
    # Explicit admin grants: the only source for a wired editor (no tick).
    for slug, editors in grants(conn).items():
        if slug not in slugs:
            continue
        for editor in editors:
            if editor in want:
                want[editor].add(slugs[slug])
    return want, slugs


def reconcile(conn: sqlite3.Connection, settings: Any, nas: Any = None) -> dict[str, Any]:
    """Apply `desired_membership` to the NAS. Returns a summary; never raises."""
    global _warned_no_capability
    out: dict[str, Any] = {"ran": False, "added": 0, "removed": 0, "errors": 0}
    if not enabled(settings):
        return out
    try:
        if nas is None:
            if not nas_configured(settings):
                return out
            nas = make_nas_client(settings)
        index_fn = capability(nas, "project_groups_index")
        ensure_fn = capability(nas, "ensure_project_group")
        set_fn = capability(nas, "set_editor_project_groups")
        if not (index_fn and ensure_fn and set_fn):
            if not _warned_no_capability:
                _warned_no_capability = True
                log.warning("project_acl is per-project but this NAS backend cannot manage "
                            "project groups (DSM: docs/SERVER-SYNOLOGY.md, per-project is partial)")
            return out
        want, slugs = desired_membership(conn)
        ledger = _ledger(conn)
        index = dict(index_fn())
        for name in sorted({n for names in want.values() for n in names}):
            if name not in index:
                index[name] = ensure_fn(name)
        out["ran"] = True
        new_ledger = {k: set(v) for k, v in ledger.items()}
        for editor in sorted(want):
            # Only what we granted (ledger) or are about to grant is ours to
            # change; any other membership the editor holds is left alone.
            managed = {n: index[n] for n in (want[editor] | ledger.get(editor, set()))
                       if n in index}
            try:
                res = set_fn(editor, want[editor], managed)
            except Exception as exc:                                   # noqa: BLE001
                out["errors"] += 1
                log.warning("could not update %s's project groups: %s", editor, exc)
                continue
            # CR-368 round 2 (2026-10-07): the ledger is what THIS module added,
            # not what the editor is wanted in. A membership made by
            # setup_editor_account.py --project or by hand must not become
            # ours because the editor also ticked the project.
            mine = (ledger.get(editor, set()) & want[editor]) | set(res.get("added", []))
            if mine:
                new_ledger[editor] = mine
            else:
                new_ledger.pop(editor, None)
            out["added"] += len(res.get("added", []))
            out["removed"] += len(res.get("removed", []))
            if res.get("added") or res.get("removed"):
                log.info("project groups for %s: +%s -%s", editor,
                         res.get("added"), res.get("removed"))
        if new_ledger != ledger:
            db.meta_set_json(conn, META_LEDGER, {k: sorted(v) for k, v in new_ledger.items()})
            conn.commit()
    except Exception as exc:                                           # noqa: BLE001
        out["errors"] += 1
        log.warning("project group reconcile skipped: %s", exc)
    return out


def close_new_project_dir(settings: Any, rel: str, slug: str, nas: Any = None) -> bool:
    """Make a just-created project directory private to proj-<slug>. True when
    the NAS did it. Never raises: the folder exists either way, and the next
    reconcile still gives ticked editors their membership."""
    if not enabled(settings):
        return False
    root = str(getattr(settings, "nas_projects_root", "") or "").rstrip("/")
    if not root:
        return False
    try:
        if nas is None:
            if not nas_configured(settings):
                return False
            nas = make_nas_client(settings)
        close = capability(nas, "close_project_dir")
        if close is None:
            return False
        # No container sealing here: create_project requires the parent to
        # exist already (api.py "parent folder does not exist") and its mkdir
        # only ever makes the leaf, so this path never creates a container
        # (CR-368 round 2). Containers are made, sticky, by setup_tree.
        return bool(close(f"{root}/{rel.strip('/')}", group_name(slug)))
    except Exception as exc:                                           # noqa: BLE001
        log.warning("could not make Projects/%s private to its project group: %s", rel, exc)
        return False
