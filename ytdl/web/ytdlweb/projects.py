"""The projects an editor has ticked, read straight out of the dashboard's DB.

This app needs one fact the dashboard owns: which projects the signed-in editor
is syncing, because those and only those are legitimate download destinations
(REQ 7). Three ways to get it were possible and this is the one chosen:

  - an HTTP call back to the dashboard: a process calling itself through its
    own uvicorn (workers=1, load-bearing) is a deadlock waiting for traffic;
  - a copy of the selections in ytdl.db: two sources of truth for who syncs
    what, and the copy is stale the moment an editor unticks something;
  - this: open `/data/dashboard.db` READ-ONLY over a `file:...?mode=ro` URI.

Read-only is not politeness, it is the safety property. Same container, same
uid, and the dashboard runs its database in WAL, so a reader never blocks the
writer and vice versa -- but a second process holding a WRITE connection to the
dashboard's database is exactly the kind of thing that turns a dashboard bug
into a locked-up fleet status page. The URI form is what makes SQLite refuse
the write rather than us remembering not to.

Unset `YTDL_DASH_DB` = standalone dev. The app still runs; it just reports
`projects_available: false` so the SPA can say "no project list" instead of
"you have no projects", which are opposite messages to an editor.
"""
import logging
import sqlite3
from pathlib import Path

from ytdlweb import config

log = logging.getLogger(__name__)

# projects.active=1 drops folders that have disappeared from syncthing's config
# but whose selections rows survive; ORDER BY position is the editor's own sync
# order, which is the order they think about their projects in.
#
# GROUPED BY SLUG since dashboard schema v24 (ytdl-web-2, 2026-08-21). A sync
# plan belongs to a COMPUTER, not to a person: `selections` is keyed
# (editor_username, machine, project_slug), and the v24 migration fanned every
# pre-existing row out to one row per machine the editor owns. This query has
# no machine to filter on -- the browser asking is a person, and CLAUDE.md's
# rule for a request with no machine is "the PERSON: the union to read" -- so
# without the grouping an editor with a laptop and a desktop saw every project
# in the picker twice. MIN(position) keeps the editor's own order, and the
# whole thing still runs unchanged against a pre-v24 dashboard.
_SQL = ('SELECT s.project_slug AS slug, p.label AS label, '
        '       MIN(s.position) AS position '
        'FROM selections s JOIN projects p '
        '  ON p.slug = s.project_slug AND p.active = 1 '
        'WHERE s.editor_username = ? '
        'GROUP BY s.project_slug, p.label ORDER BY position, p.label')


def _dev_projects():
    """YTDL_DEV_PROJECTS='slug=label,slug2=label2' -- standalone dev only."""
    out = []
    for chunk in config.DEV_PROJECTS.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        slug, _, label = chunk.partition('=')
        out.append({'slug': slug.strip(), 'label': (label or slug).strip()})
    return out


def ticked_projects(user):
    """-> {'projects': [{'slug','label'}], 'available': bool, 'error': str|None}

    `available` is about the DASHBOARD DATABASE, not about the editor: false
    means this app could not consult it at all. An editor who has simply ticked
    nothing gets available=true and an empty list, and the SPA says so.
    """
    if not config.DASH_DB:
        return {'projects': _dev_projects(), 'available': False,
                'error': 'YTDL_DASH_DB is not set: this app has no dashboard '
                         'database to read project selections from.'}
    path = Path(config.DASH_DB)
    if not path.is_file():
        return {'projects': [], 'available': False,
                'error': f'the dashboard database at {path} does not exist.'}

    try:
        # uri=True + mode=ro: SQLite itself refuses any write on this handle.
        # immutable is deliberately NOT set -- the dashboard is writing to this
        # file continuously and immutable would let us read a torn WAL.
        con = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=5)
    except sqlite3.Error as exc:
        log.warning('could not open the dashboard database read-only (%s)', exc)
        return {'projects': [], 'available': False, 'error': str(exc)[:200]}

    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(_SQL, (user,)).fetchall()
        return {'projects': [{'slug': r['slug'], 'label': r['label']} for r in rows],
                'available': True, 'error': None}
    except sqlite3.Error as exc:
        # A dashboard old enough not to have `selections` (schema v1) lands
        # here. Reported, not raised: the page still loads, with no picker.
        log.warning('dashboard project query failed (%s)', exc)
        return {'projects': [], 'available': False, 'error': str(exc)[:200]}
    finally:
        con.close()


def resolve_project(user, slug):
    """-> {'slug','label'} for a slug the user has ticked, or None.

    Every write path re-runs this server-side. The picker in the browser is a
    convenience; this is the check. Without it an editor could post any slug
    and drop files into a project they do not sync.
    """
    if not slug:
        return None
    for p in ticked_projects(user)['projects']:
        if p['slug'] == slug:
            return p
    return None


# The dashboard's `machines` registry (its schema v23): hostname as the key,
# plus the companion-minted machine_id that survives a rename. Read here for
# ONE cosmetic purpose, below.
_MACHINE_SQL = ('SELECT machine FROM machines '
                'WHERE editor_username = ? AND machine_id = ? '
                'ORDER BY last_seen DESC LIMIT 1')


def machine_label(user, machine_id):
    """The hostname the dashboard has on file for this machine_id, or None.

    COSMETIC ONLY (data-model-7, CR-66, 2026-08-21). Since the download lease
    is keyed on (editor, machine_id), an editor's second computer is refused
    with a 409 -- and "9f3c1a2b7e...  is already downloading this job" is not a
    sentence anybody can act on. This turns it into the name of the computer
    they left running.

    Resolved from the REGISTRY rather than taken from the claim body on
    purpose: routes_fleet's rule is that the body decides nothing, and echoing
    a self-asserted hostname back to a different machine would be one editor's
    string in another's log line. Best-effort by construction -- no dashboard
    database, no such machine, an older dashboard with no `machines` table, all
    answer None and the caller names the id instead.
    """
    machine_id = str(machine_id or '').strip()
    if not machine_id or not config.DASH_DB:
        return None
    path = Path(config.DASH_DB)
    if not path.is_file():
        return None
    try:
        # Same read-only URI handle ticked_projects opens, for the same reason:
        # SQLite itself refuses the write rather than us remembering not to.
        con = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        row = con.execute(_MACHINE_SQL, (user, machine_id)).fetchone()
    except sqlite3.Error as exc:
        log.debug('could not name machine %s (%s)', machine_id, exc)
        return None
    finally:
        con.close()
    return (str(row[0]).strip() or None) if row else None
