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
_SQL = ('SELECT s.project_slug AS slug, p.label AS label '
        'FROM selections s JOIN projects p '
        '  ON p.slug = s.project_slug AND p.active = 1 '
        'WHERE s.editor_username = ? ORDER BY s.position')


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
