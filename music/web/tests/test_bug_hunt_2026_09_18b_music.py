"""The 2026-09-18b hunt, music's mediums (CR-304).

Every test here fails on the source before the fix beside it and passes after.
The ids are the hunt's (`docs/bug-hunt-2026-09-18b/hunters/music.md`) and each
is cited at its code site, so `grep -rn music-1` finds both halves.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from musicweb import config, db, ingest_batches
from tests.test_fleet_ingest import (MACHINE, fleet,  # noqa: F401
                                     claim, headers, make_batch)

EDITOR = {'X-CCSync-User': 'jsmith'}


def _running_with_a_live_lease(uid):
    """The state music-1 is about: a machine really is indexing this batch."""
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state = 'running' WHERE uid = ?",
                 (uid,))
    conn.commit()


def _row(uid):
    return db.con().execute(
        'SELECT state, lease_expires_at, cancel_requested, finished_at '
        'FROM ingest_batches WHERE uid = ?', (uid,)).fetchone()


# --------------------------------------------------------------------------
# music-1: the live-lease branch of cancel must not wedge the batch either
# --------------------------------------------------------------------------

def test_a_cancel_on_a_live_lease_leaves_the_lease_for_the_sweep(fleet):
    """The wedge on the OTHER branch: `cancel` nulled the lease while leaving
    `state='running'`, which is outside expire_stale_leases' predicate for
    good, so a companion that died before its next heartbeat left a row no
    sweep could reach and no claim could take."""
    uid = make_batch(fleet, names=('One.wav',))
    assert claim(fleet, uid).status_code == 200
    _running_with_a_live_lease(uid)

    r = fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)

    assert r.status_code == 200, r.text
    batch = _row(uid)
    assert batch['cancel_requested'] == 1
    assert batch['lease_expires_at'], \
        'the lease was taken away, so no sweep can ever reach this row again'


def test_a_cancelled_batch_whose_machine_never_answers_is_finalised(fleet):
    """The companion is killed between the cancel and its next heartbeat
    (crash, Stop-Process, power cut, the tray's own upgrade). The sweep is the
    only thing left, and it must END the batch rather than hand it back to
    `queued`, which `_leaseholder_or_410` refuses to let anyone claim."""
    uid = make_batch(fleet, names=('One.wav',))
    assert claim(fleet, uid).status_code == 200
    _running_with_a_live_lease(uid)
    fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET lease_expires_at = "
                 "'2026-01-01T00:00:00+00:00' WHERE uid = ?", (uid,))
    conn.commit()

    ingest_batches.expire_stale_leases(conn)

    batch = _row(uid)
    assert batch['state'] == 'cancelled', batch['state']
    assert batch['finished_at'], 'nothing recorded that this batch is over'


def test_a_cancelled_batch_stops_holding_its_names_once_it_is_swept(fleet):
    """What the wedge cost downstream: `reserved_names` excludes only the
    terminal item states, so a batch nothing could finalise kept every
    `dest_name` reserved and each later drop of `Theme.wav` was allocated as
    `Theme (2).wav`."""
    uid = make_batch(fleet, names=('Theme.wav',))
    assert claim(fleet, uid).status_code == 200
    _running_with_a_live_lease(uid)
    conn = db.con()
    conn.execute("UPDATE ingest_items SET dest_name = 'Theme.wav' "
                 'WHERE batch_uid = ?', (uid,))
    conn.commit()
    fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)
    conn.execute("UPDATE ingest_batches SET lease_expires_at = "
                 "'2026-01-01T00:00:00+00:00' WHERE uid = ?", (uid,))
    conn.commit()

    ingest_batches.expire_stale_leases(conn)

    assert 'theme.wav' not in ingest_batches.reserved_names(db.con()), \
        'the cancelled batch still holds the name for every later drop'


def test_an_uncancelled_expired_lease_still_goes_back_to_the_queue(fleet):
    """The sweep's own contract is unchanged for everything else: the work is
    still wanted when nobody cancelled it."""
    uid = make_batch(fleet, names=('One.wav',))
    assert claim(fleet, uid).status_code == 200
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state = 'running', "
                 "lease_expires_at = '2026-01-01T00:00:00+00:00' "
                 'WHERE uid = ?', (uid,))
    conn.commit()

    ingest_batches.expire_stale_leases(conn)

    assert _row(uid)['state'] == 'queued'


# --------------------------------------------------------------------------
# music-3: only an answer the companion really gave is a refusal
# --------------------------------------------------------------------------

INGEST_JS = Path(config.STATIC_DIR) / 'ingest.js'


def _script(answer, driver):
    """Drive miRetryFailed in node with everything around it stubbed.

    The page is a plain script that touches `document` at the top level, so
    only the helpers under test are extracted: the refusal helpers (which sit
    between miDispatchLocal and miTakeOver) and miRetryFailed itself. The
    thrown errors are the real ones - `miLoopback`'s shape for an HTTP answer,
    and a bare fetch rejection for a tray that is not running.
    """
    body = INGEST_JS.read_text(encoding='utf-8')
    helpers = body[body.index('function miRefusalText('):
                   body.index('async function miTakeOver(')]
    retry = body[body.index('async function miRetryFailed('):]
    retry = retry[:retry.index('\nasync function ')]
    return f"""
const MI_TOO_OLD = 'your CC Sync tray is too old for music ingest: take the '
  + 'update it offers, then reload this page.';
const MI_COMPANION_HINT = 'not reachable: the CC Sync tray is not running';
const mi = {{batchUid: '', stagingId: ''}};
const toasts = [];
function el(tag, cls, text) {{ return {{cls: cls, text: text}}; }}
function toast(node) {{ toasts.push(node.text); }}
function miSetNotice() {{}}
function miLoadBatches() {{}}
function miPollServer() {{}}
async function miApi() {{ return {{ok: true, retried: 3}}; }}
async function miDispatchLocal() {{ throw THROWN(); }}
{helpers}
{retry}
(async () => {{
  {driver}
  console.log(JSON.stringify({{toasts}}));
}})();
"""


def _node(tmp_path, thrown, driver="await miRetryFailed('b1');"):
    if shutil.which('node') is None:
        pytest.skip('node not installed')
    script = _script(thrown, driver).replace('THROWN()', thrown)
    path = tmp_path / 'retry.mjs'
    path.write_text(script, encoding='utf-8')
    out = subprocess.run(['node', str(path)], capture_output=True, text=True,
                         encoding='utf-8')
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])['toasts']


NO_TRAY = "new TypeError('Failed to fetch')"
TOO_OLD = ("(() => { const e = new Error('the CC Sync tray returned HTTP 404'); "
           "e.status = 404; e.body = null; return e; })()")
REFUSED = ("(() => { const e = new Error('this computer is already indexing "
           "another batch'); e.status = 409; e.body = {ok: false, message: "
           "'this computer is already indexing another batch'}; return e; })()")


def test_a_tray_that_is_not_running_is_not_reported_as_the_companions_reason(tmp_path):
    """A rejected fetch has no status and no body: "Failed to fetch" is the
    browser's words, not the companion's, and printing it as the reason also
    hides the only sentence that says what to do."""
    toasts = _node(tmp_path, NO_TRAY)

    assert len(toasts) == 1, toasts
    assert 'Failed to fetch' not in toasts[0]
    assert 'did not pick them up' not in toasts[0]
    assert 'Open this page on the computer that has the tracks' in toasts[0]


def test_a_companion_too_old_for_music_ingest_is_named_as_such(tmp_path):
    """The 404 the laptop's older tray answers: the page already knows what
    that means everywhere else, and an editor must not be shown a raw code."""
    toasts = _node(tmp_path, TOO_OLD)

    assert 'HTTP 404' not in toasts[0], toasts[0]
    assert 'too old' in toasts[0]
    assert 'Open this page on the computer that has the tracks' in toasts[0]


def test_a_refusal_the_companion_really_spoke_still_reaches_the_editor(tmp_path):
    """The music-2 fix must survive this one: a companion that answered in
    words is still quoted."""
    toasts = _node(tmp_path, REFUSED)

    assert 'did not pick them up: this computer is already indexing another batch' \
        in toasts[0], toasts[0]
