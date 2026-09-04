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

# Every active project, for the editor whose machines are all WIRED to the NAS
# (CR-72, 2026-08-24). A base rig syncs nothing and CAN sync nothing -- the
# dashboard 409s any tick on a base-only account (CR-28) -- so "the projects
# you sync" is the empty set for such an editor by construction, and the
# picker they saw was permanently blank. A wired machine works directly off
# the whole NAS tree, so for that person every active project is a legitimate
# destination. Ordered by label because there is no selections.position to
# order by; label is the dashboard's own project-list order (db.fetch_projects).
_ALL_SQL = 'SELECT slug, label FROM projects WHERE active = 1 ORDER BY label'

# The same two sources ccsync_dashboard.db.machine_modes reads, in the same
# precedence: machine_state.mode (v22) is the answer, editor_media_project.mode
# the fallback for a machine that last reported before v22. Copied as SQL
# rather than imported for projects.py's usual reason: this app opens the
# dashboard's database read-only and must run with no dashboard package in
# reach. Order matters -- the second query overwrites the first per machine.
_MODE_SQLS = (
    'SELECT DISTINCT machine, mode FROM editor_media_project WHERE editor_username = ?',
    'SELECT machine, mode FROM machine_state WHERE editor_username = ?',
)


def _machine_modes(con, user):
    """machine -> 'base' | 'editor', for every machine of this editor.

    Shared by `_base_only` (per-person, EVERY machine) and `_wired` (per
    MACHINE, CR-72 follow-up 2026-08-30). Same two sources, same precedence,
    as ccsync_dashboard.db.machine_modes: machine_state.mode (v22) wins,
    editor_media_project.mode is the pre-v22 fallback. An older dashboard
    without these tables (or the v22 mode column) lands in the except arm per
    query and returns {}, which is the pre-CR-72 behaviour exactly.
    """
    modes = {}
    for sql in _MODE_SQLS:
        try:
            rows = con.execute(sql, (user,)).fetchall()
        except sqlite3.Error:
            continue
        for machine, mode in rows:
            mode = str(mode or '').strip().lower()
            if mode:
                modes[machine] = mode
    return modes


def _base_only(con, user):
    """True iff the editor has at least one known machine and every one of
    them reports mode 'base' -- the dashboard's base_only_editors predicate,
    per person because the browser asking is a person.

    Deliberately NOT "owns any wired machine": a person with one wired and one
    remote machine keeps the ticked list, because a job they start from the
    remote machine is claimed by THAT machine's companion (the SPA hands the
    job id to its local loopback), and a download into a project that machine
    does not sync is a folder nothing manages. An account with no known
    machines is unknown, not base-only -- same rule as the dashboard's.
    """
    modes = _machine_modes(con, user)
    return bool(modes) and set(modes.values()) == {'base'}


def _wired(con, user, machine):
    """True iff THIS machine (by hostname) is wired to the NAS -- the per
    MACHINE half of CR-72 (2026-08-30 follow-up, owner: "I can still only
    select /animals as a destination on the base rig").

    `_base_only` only ever widened the picker for an account whose EVERY
    machine is wired -- exactly right for a job a REMOTE machine's companion
    will claim (it must land in a project that machine actually syncs), and
    exactly wrong for the person standing at the console of a mixed
    account's wired machine, who saw the picker offer nothing new because
    their OTHER machine is remote. Same machine_state / editor_media_project
    precedence as `_base_only` and the dashboard's own machine_modes; an
    unnamed or unknown machine answers False, same "unknown is not wired"
    rule `_base_only` uses for an unknown editor."""
    machine = str(machine or '').strip()
    if not machine:
        return False
    return _machine_modes(con, user).get(machine) == 'base'


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


def ticked_projects(user, machine=None, local=True):
    """-> {'projects': [{'slug','label'}], 'available': bool, 'error': str|None}

    `available` is about the DASHBOARD DATABASE, not about the editor: false
    means this app could not consult it at all. An editor who has simply ticked
    nothing gets available=true and an empty list, and the SPA says so.

    `machine` and `local` are the CR-72 follow-up (2026-08-30, owner: "I can
    still only select /animals as a destination on the base rig"): the rule
    that widens the picker to every active project is per MACHINE and per
    EXECUTION PLACE, not just per person.

      - `local=False` -- the download is going to run ON THE SERVER (the
        SPA's "on this machine" toggle off, or no companion answered it): no
        machine's companion claims the job, so no machine's sync plan is a
        constraint. Every active project is a legitimate destination, same as
        for a base-only editor, for anyone.
      - `machine` names the REQUESTING machine (a hostname). When it is wired
        (`_wired`), every active project is offered even for a MIXED account
        -- the shape `_base_only` deliberately does not cover, because a job
        that machine's own companion claims writes straight onto the tree it
        already works off of, the same as a base-only editor's does.
      - Neither: the pre-CR-72-follow-up behaviour, `_base_only` alone, so an
        older SPA (no `machine`/`local` fields) or an unnamed machine changes
        nothing.
    """
    if not config.DASH_DB:
        return {'projects': _dev_projects(), 'available': False,
                'error': 'YTDL_DASH_DB is not set: this app has no dashboard '
                         'database to read sync plans from.'}
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
        # A base-only editor gets the whole active project list (CR-72): their
        # machines are wired to the NAS tree, they cannot hold a tick (CR-28),
        # and an empty picker told them "you sync nothing" as if it were their
        # doing. resolve_project() goes through here too, so the server-side
        # destination check widens with the picker rather than drifting from it.
        # `not local` and `_wired(machine)` are the per-machine/per-place
        # follow-up above -- either is enough on its own.
        if (not local) or _wired(con, user, machine) or _base_only(con, user):
            rows = con.execute(_ALL_SQL).fetchall()
        else:
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


def resolve_project(user, slug, machine=None, local=True):
    """-> {'slug','label'} for a slug the user has ticked, or None.

    Every write path re-runs this server-side. The picker in the browser is a
    convenience; this is the check. Without it an editor could post any slug
    and drop files into a project they do not sync.

    `machine`/`local` widen this the SAME way they widen `ticked_projects`
    (CR-72 follow-up, 2026-08-30) -- taken from the job payload (NewJob /
    NewUrlJob) rather than re-derived, so the picker and this check can never
    disagree about what a given request was allowed to see.
    """
    if not slug:
        return None
    for p in ticked_projects(user, machine=machine, local=local)['projects']:
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
