"""The 2026-09-18 hunt, music's half (webapps-tools group, CR-286).

Every test here fails on the source before the fix beside it and passes after.
The ids are the hunt's (`docs/bug-hunt-2026-09-18/hunters/music.md`) and each
is cited at its code site, so `grep -rn music-1` finds both halves.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from musicweb import db, ingest_batches
from tests.test_fleet_ingest import (MACHINE, fleet,  # noqa: F401
                                     claim, headers, make_batch)

EDITOR = {'X-CCSync-User': 'jsmith'}


def _running_with_a_dead_lease(uid):
    """The batch state music-1 is about: claimed, running, lease long gone,
    and nothing has swept it yet."""
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state = 'running', "
                 "lease_expires_at = '2026-01-01T00:00:00+00:00' "
                 'WHERE uid = ?', (uid,))
    conn.commit()


# --------------------------------------------------------------------------
# music-1: a cancel racing lease expiry must not wedge the batch in `running`
# --------------------------------------------------------------------------

def test_a_cancel_after_the_lease_died_finalises_the_batch(fleet):
    uid = make_batch(fleet, names=('One.wav', 'Two.wav'))
    assert claim(fleet, uid).status_code == 200
    _running_with_a_dead_lease(uid)

    r = fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['state'] == 'cancelled', body
    assert body.get('finalised') is True
    conn = db.con()
    batch = conn.execute('SELECT state FROM ingest_batches WHERE uid = ?',
                         (uid,)).fetchone()
    assert batch['state'] in ingest_batches.BATCH_TERMINAL


def test_a_cancel_never_leaves_a_row_no_sweep_can_reach(fleet):
    """The wedge itself: `running` + a NULL lease is outside
    expire_stale_leases' predicate, so nothing can ever move the row."""
    uid = make_batch(fleet, names=('One.wav',))
    assert claim(fleet, uid).status_code == 200
    _running_with_a_dead_lease(uid)

    fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)

    conn = db.con()
    ingest_batches.expire_stale_leases(conn)
    batch = conn.execute('SELECT state, lease_expires_at FROM ingest_batches '
                         'WHERE uid = ?', (uid,)).fetchone()
    assert not (batch['state'] == 'running'
                and batch['lease_expires_at'] is None), \
        'the batch is unreachable by any sweep and unclaimable for ever'


def test_a_cancel_on_a_live_lease_still_only_asks(fleet):
    """The other half of the OR: a batch a machine really is holding keeps the
    request-not-kill semantics, because the companion is the one that stops."""
    uid = make_batch(fleet, names=('One.wav',))
    assert claim(fleet, uid).status_code == 200
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state = 'running' WHERE uid = ?",
                 (uid,))
    conn.commit()

    r = fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['state'] == 'running' and body['cancel_requested'] is True
    assert 'finalised' not in body


# --------------------------------------------------------------------------
# music-3: the drop preview must respect names already promised elsewhere
# --------------------------------------------------------------------------

def test_the_precheck_preview_honours_a_name_an_unlanded_item_holds(fleet):
    """Editor A's batch is in flight holding `Theme.wav`; nothing is on disk
    yet. Editor B drags in their own `Theme.wav` and the panel must not promise
    the name the ledger has already handed out."""
    uid = make_batch(fleet, names=('Theme.wav',))
    held = 'Theme.wav'
    conn = db.con()
    # The name is allocated when the item's RESULT lands, which is where
    # `reserved_names` reads it from; the audio is still uploading.
    conn.execute('UPDATE ingest_items SET dest_name = ? WHERE batch_uid = ?',
                 (held, uid))
    conn.commit()
    assert held.lower() in ingest_batches.reserved_names(conn)

    r = fleet.post('/api/ingest-batches/precheck', headers=EDITOR,
                   json={'items': [{'local_id': 'b1', 'name': held,
                                    'size': 1234}]})

    assert r.status_code == 200, r.text
    names = [row['final_name'] for row in r.json()['items']]
    assert held not in names, \
        'the preview promised a name an unlanded item already holds'


# --------------------------------------------------------------------------
# music-2 / regression-1: the loopback's own refusal must reach the editor,
# and a dispatch that lost its staging id must adopt the one the companion
# names rather than dying between two fixes from the same pass.
# --------------------------------------------------------------------------

INGEST_JS = Path(__file__).resolve().parents[1] / 'static' / 'ingest.js'


def _run_js(driver):
    """Slice the two dispatch helpers out of ingest.js and drive them in node.

    The page is a plain script that touches `document` at the top level, so
    only the functions under test are extracted. `miLoopback` is stubbed: it
    is the seam, and the refusal bodies are the companion's real ones
    (`broll_ingest.run`).
    """
    body = INGEST_JS.read_text(encoding='utf-8')
    start = body.index('async function miDispatchLocal(')
    end = body.index('async function miTakeOver(')
    src = body[start:end]
    script = f"""
const calls = [];
let answers = ANSWERS_JSON;
const mi = {{runMode: 'idle', batchUid: '', stagingId: ''}};
async function miLoopback(method, path, body, withStatus) {{
  calls.push(body);
  const a = answers.shift();
  if (a.status >= 400) {{
    const err = new Error((a.body && (a.body.message || a.body.detail)) ||
                          `the CC Sync tray returned HTTP ${{a.status}}`);
    err.status = a.status;
    err.body = a.body;
    throw err;
  }}
  return withStatus ? {{status: a.status, body: a.body}} : a.body;
}}
{src}
{driver}
"""
    return script


HELD_409 = {
    'status': 409,
    'body': {'ok': False, 'reason': 'staging_id_missing',
             'staging_id': 'stg-77',
             'message': ('this computer has those tracks staged, but the '
                         'request did not say which drop: reload the page '
                         'and try again')},
}


def _node(tmp_path, answers, driver):
    if shutil.which('node') is None:
        pytest.skip('node not installed')
    script = _run_js(driver).replace('ANSWERS_JSON', json.dumps(answers))
    path = tmp_path / 'drive.mjs'
    path.write_text(script, encoding='utf-8')
    out = subprocess.run(['node', str(path)], capture_output=True, text=True,
                         encoding='utf-8')
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_dispatch_that_lost_its_staging_id_adopts_the_one_the_companion_names(
        tmp_path):
    """regression-1: CR-262C sends an empty staging id after a reload and
    CR-253A refuses exactly that on the one machine holding the files."""
    driver = """
(async () => {
  const r = await miDispatchLocal('/music/ingest/retry', 'b1', '', true);
  console.log(JSON.stringify({sent: calls.map(c => c.staging_id),
                              status: r.status}));
})();
"""
    result = _node(tmp_path, [HELD_409, {'status': 202, 'body': {'ok': True}}],
                   driver)
    assert result['sent'] == ['', 'stg-77'], \
        'the refusal named the staging id it holds and the page ignored it'
    assert result['status'] == 202


def test_the_companions_own_refusal_is_what_the_editor_is_shown(tmp_path):
    """music-2: only the dashboard claim's 409 is about another computer."""
    driver = """
(async () => {
  const seen = [];
  for (const _ of [0, 1]) {
    try {
      await miDispatchLocal('/music/ingest/run', 'b1', '', false);
      seen.push(null);
    } catch (e) { seen.push(miRefusalText(e)); }
  }
  console.log(JSON.stringify({seen}));
})();
"""
    busy = {'status': 409,
            'body': {'ok': False,
                     'message': 'this computer is already indexing another batch'}}
    claim = {'status': 409, 'body': None}
    result = _node(tmp_path, [busy, claim], driver)
    assert result['seen'][0] == 'this computer is already indexing another batch'
    assert result['seen'][1] == \
        'Another of your computers is still working on this batch.'
