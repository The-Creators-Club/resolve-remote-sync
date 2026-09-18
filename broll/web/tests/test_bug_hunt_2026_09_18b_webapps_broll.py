"""The 2026-09-18b hunt, the b-roll web app's half (webapps-broll, CR-302).

Each test fails on the source before the fix beside it and passes after. The
ids are the hunt's (`docs/bug-hunt-2026-09-18b/hunters/broll.md`) and each one
is cited at its code site.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest

from app import config

from tests.factories import insert_video
from tests.test_fleet_ingest import _claim, _queue  # noqa: F401


def _detail_video(client, video_id):
    r = client.get(f"/api/videos/{video_id}")
    assert r.status_code == 200
    return r.json()["video"]


# --------------------------------------------------------------------------
# broll-1: the editing proxy beside the preview needs CR-90 too
# --------------------------------------------------------------------------

def test_an_nfd_editing_proxy_is_found_beside_an_nfc_preview(client, conn,
                                                             data_root):
    """broll-3 normalised the TOP-SLOT compare and left the editing proxy
    stat'ed under a name built from the DB's NFC string. A Mac's upload spells
    it NFD, so the route answered `original_rel` correctly and
    `edit_proxy_rel: null` - which the companion reads as "fetch the camera
    master" or as a stand-in nothing will ever upgrade."""
    stem_nfc = unicodedata.normalize("NFC", "Matej Šimalčík A002")
    stem_nfd = unicodedata.normalize("NFD", stem_nfc)
    shoot = data_root / "Creators_Club" / "ff5" / "Day 3"
    (shoot / "Proxy").mkdir(parents=True, exist_ok=True)
    (shoot / f"{stem_nfd}.mov").write_bytes(b"top slot")
    (shoot / "Proxy" / f"{stem_nfc}.mp4").write_bytes(b"preview")
    (shoot / "Proxy" / f"{stem_nfd}.mov").write_bytes(b"editing proxy")

    vid = insert_video(
        conn, share="ff5", rel_path=f"x/{stem_nfc}.mov",
        archive_path=f"Creators_Club/ff5/Day 3/Proxy/{stem_nfc}.mp4")

    insert = _detail_video(client, vid)["insert"]

    assert insert["known"] is True
    assert insert["original_rel"] is not None
    assert insert["edit_proxy_rel"] is not None, \
        "the NFD editing proxy was invisible to the stem stat"
    assert insert["edit_proxy_rel"].endswith(".mov")
    # The answer carries the bytes that are on disk, not the row's spelling:
    # the companion opens this path (CLAUDE.md CR-90).
    assert insert["edit_proxy_rel"].endswith(f"{stem_nfd}.mov")


def test_a_mov_preview_is_still_not_its_own_editing_proxy(client, conn,
                                                          data_root):
    """broll-4's guard has to survive broll-1's rewrite: the preview is now
    found by the same listing as the editing proxy, so it must be excluded by
    name rather than by the derived path."""
    shoot = data_root / "Creators_Club" / "ff5" / "Day 4"
    (shoot / "Proxy").mkdir(parents=True, exist_ok=True)
    (shoot / "Proxy" / "talk.mov").write_bytes(b"preview that is also the top slot")

    vid = insert_video(
        conn, share="ff5", rel_path="x/talk.mov",
        archive_path="Creators_Club/ff5/Day 4/Proxy/talk.mov")

    insert = _detail_video(client, vid)["insert"]

    assert insert["edit_proxy_rel"] is None, \
        "the preview was advertised as its own editing proxy"


def test_an_unreadable_proxy_folder_answers_known_false(client, conn,
                                                        data_root,
                                                        monkeypatch):
    """proxy-tiers-3's rule holds for the second listing: a listing that
    RAISED is not "this clip has no editing proxy"."""
    import os as _os

    from app import routes_api

    shoot = data_root / "Creators_Club" / "ff5" / "Day 5"
    (shoot / "Proxy").mkdir(parents=True, exist_ok=True)
    (shoot / "clip.mov").write_bytes(b"top slot")
    (shoot / "Proxy" / "clip.mp4").write_bytes(b"preview")
    (shoot / "Proxy" / "clip.mov").write_bytes(b"editing proxy")

    real_listdir = _os.listdir

    def fake_listdir(path):
        if _os.path.basename(str(path)) == "Proxy":
            raise OSError("dataset unmounted")
        return real_listdir(path)

    monkeypatch.setattr(routes_api.os, "listdir", fake_listdir)

    vid = insert_video(
        conn, share="ff5", rel_path="x/clip.mov",
        archive_path="Creators_Club/ff5/Day 5/Proxy/clip.mp4")

    insert = _detail_video(client, vid)["insert"]

    assert insert["known"] is False
    assert insert["edit_proxy_rel"] is None


# --------------------------------------------------------------------------
# proxy-tiers-3 (owed to CR-302 by the companion-broll group): a server that
# could not look must not send a 0.9.74 companion a stand-in plan
# --------------------------------------------------------------------------

def test_a_heavy_row_answers_edit_weight_true_when_the_listing_raised(
        client, conn, data_root):
    """`known` is read by 0.9.75 and later only. Builds in the field today
    read `original_is_edit_weight` alone, and a `false` there during an outage
    is what makes them plan a stand-in and write a ledger row that outlives
    the outage. The existing known=false cell in `test_insert_target.py` is a
    3 Mb/s clip, already edit-weight, so it cannot pin this."""
    vid = insert_video(
        conn, share="ff5", rel_path="x/heavy.mov", width=3840, height=2160,
        bitrate=200_000_000, codec="h264",
        archive_path="Creators_Club/ff5/Nowhere/Proxy/heavy.mp4")

    insert = _detail_video(client, vid)["insert"]

    assert insert["known"] is False
    assert insert["original_rel"] is None
    assert insert["edit_proxy_rel"] is None
    assert insert["original_is_edit_weight"] is True, \
        "an outage sent an old companion a stand-in plan"


def test_a_healthy_heavy_row_is_still_not_edit_weight(client, conn, data_root):
    """The forced answer stays scoped to the outage path: a `true` on the
    healthy path would suppress every stand-in the tier exists to make."""
    shoot = data_root / "Creators_Club" / "ff5" / "Day 6"
    (shoot / "Proxy").mkdir(parents=True, exist_ok=True)
    (shoot / "heavy.mov").write_bytes(b"camera master")
    (shoot / "Proxy" / "heavy.mp4").write_bytes(b"preview")

    vid = insert_video(
        conn, share="ff5", rel_path="x/heavy.mov", width=3840, height=2160,
        bitrate=200_000_000, codec="h264",
        archive_path="Creators_Club/ff5/Day 6/Proxy/heavy.mp4")

    insert = _detail_video(client, vid)["insert"]

    assert insert["known"] is True
    assert insert["original_rel"] is not None
    assert insert["original_is_edit_weight"] is False


# --------------------------------------------------------------------------
# music-1's twin (owed to CR-302 by the music group): a cancel delivered to a
# LIVE lease wedged the batch
# --------------------------------------------------------------------------

def _row(conn, uid):
    return conn.execute(
        "SELECT state, lease_expires_at, cancel_requested, finished_at "
        "FROM ingest_batches WHERE uid = ?", (uid,)).fetchone()


def test_a_cancel_on_a_live_lease_leaves_the_lease_for_the_sweep(client, conn):
    """`cancel` nulled `lease_expires_at` while leaving `state='running'`,
    which is outside `expire_stale_leases`'s predicate for good: a companion
    that died before its next heartbeat left a row no sweep could reach, no
    claim could take (410 on `cancel_requested`), and whose `dest_name`
    reservations were held for ever."""
    from app import ingest_batches

    uid = _queue(client)
    assert _claim(client, uid).status_code == 200
    conn.execute("UPDATE ingest_batches SET state = 'running' WHERE uid = ?",
                 (uid,))
    conn.commit()

    ingest_batches.cancel(conn, uid, "root")

    batch = _row(conn, uid)
    assert batch["cancel_requested"] == 1
    assert batch["lease_expires_at"], \
        "the lease was taken away, so no sweep can ever reach this row again"


def test_the_sweep_finalises_a_cancelled_batch_rather_than_requeueing_it(
        client, conn):
    """The companion asked to stop is also the one that may never answer, so
    the sweep is the only thing left. Back to `queued` would be a row asking
    to be claimed while `_leaseholder_or_410` refuses every claim."""
    from datetime import datetime, timedelta, timezone

    from app import ingest_batches

    uid = _queue(client)
    assert _claim(client, uid).status_code == 200
    ingest_batches.cancel(conn, uid, "root")

    later = datetime.now(timezone.utc) + timedelta(hours=2)
    swept = ingest_batches.expire_stale_leases(conn, now=later)

    batch = _row(conn, uid)
    assert swept == 1, "the finalised batch was not counted"
    assert batch["state"] == "cancelled", \
        "a cancelled batch was handed back to a queue nobody may claim from"
    assert batch["finished_at"]


def test_an_uncancelled_expired_lease_still_goes_back_to_the_queue(client,
                                                                   conn):
    """The sweep's own job is untouched: work still wanted is still requeued."""
    from datetime import datetime, timedelta, timezone

    from app import ingest_batches

    uid = _queue(client)
    assert _claim(client, uid).status_code == 200

    later = datetime.now(timezone.utc) + timedelta(hours=2)
    swept = ingest_batches.expire_stale_leases(conn, now=later)

    batch = _row(conn, uid)
    assert swept == 1
    assert batch["state"] == "queued"
    assert batch["lease_expires_at"] is None


# --------------------------------------------------------------------------
# music-3's twin (owed to CR-302 by the music group): a browser failure is not
# the companion's answer
# --------------------------------------------------------------------------

INGEST_JS = Path(config.STATIC_DIR) / "ingest.js"


def _script(driver, thrown):
    """Drive ingestRetryFailedBatch in node with everything around it stubbed.

    The page is a plain script that touches `document` at the top level, so
    only the helpers under test are extracted: the two refusal helpers (which
    sit between ING_COMPANION_HINT and `const ing`) and the function itself.
    The thrown errors are the real ones - `ingestLoopback`'s shape for an HTTP
    answer, and a bare fetch rejection for a tray that is not running.
    """
    body = INGEST_JS.read_text(encoding="utf-8")
    helpers = body[body.index("function ingestSpokeARefusal("):
                   body.index("const ing = {")]
    fn = body[body.index("async function ingestRetryFailedBatch("):]
    fn = fn[:fn.index("\nasync function ")]
    take = body[body.index("async function ingestTakeOver("):]
    take = take[:take.index("\nasync function ")]
    return f"""
const ING_TOO_OLD = 'your CC Sync tray is too old for b-roll ingest: take the '
  + 'update it offers, then reload this page';
const ing = {{batchUid: '', stagingId: null, runMode: 'foreground',
              running: false}};
const notices = [];
const toasts = [];
function toast(text) {{ toasts.push(text); }}
function ingestSetNotice(text) {{ notices.push(text); }}
function ingestLoadBatches() {{}}
function ingestStartPolling() {{}}
function ingestRenderSummary() {{}}
function $() {{ return {{classList: {{remove() {{}}}}}}; }}
async function fetchJson() {{ return {{retried: 3}}; }}
async function ingestLoopback() {{ throw THROWN(); }}
{helpers}
{fn}
{take}
(async () => {{
  {driver}
  console.log(JSON.stringify({{notices, toasts}}));
}})();
""".replace("THROWN()", thrown)


def _node(tmp_path, thrown, driver="await ingestRetryFailedBatch('b1');"):
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    path = tmp_path / "retry.mjs"
    path.write_text(_script(driver, thrown), encoding="utf-8")
    out = subprocess.run(["node", str(path)], capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


NO_TRAY = "new TypeError('Failed to fetch')"
TOO_OLD = ("(() => { const e = new Error('the CC Sync tray returned HTTP 404'); "
           "e.status = 404; e.body = null; return e; })()")
REFUSED = ("(() => { const e = new Error('this computer is already indexing "
           "another batch'); e.status = 409; e.body = {ok: false, message: "
           "'this computer is already indexing another batch'}; return e; })()")


def test_a_tray_that_is_not_running_is_not_reported_as_the_companions_reason(
        tmp_path):
    """A rejected fetch has no status and no body: "Failed to fetch" is the
    browser's words, not the companion's, and printing it as the reason also
    drops the only sentence that says what to do next."""
    notice = _node(tmp_path, NO_TRAY)["notices"][-1]

    assert "Failed to fetch" not in notice
    assert "did not pick them up" not in notice
    assert "take over on this computer" in notice


def test_a_companion_too_old_for_broll_ingest_is_named_as_such(tmp_path):
    """The 404 an older tray answers on every /broll/ingest route: the page
    already knows what that means everywhere else, and an editor must not be
    shown a raw code."""
    notice = _node(tmp_path, TOO_OLD)["notices"][-1]

    assert "HTTP 404" not in notice
    assert "too old" in notice
    assert "take over on this computer" in notice


def test_a_refusal_the_companion_really_spoke_still_reaches_the_editor(
        tmp_path):
    """broll-1 (2026-09-11b) must survive this: a companion that answered in
    words is still quoted, and the editor is not told to wait for something
    that will never happen."""
    notice = _node(tmp_path, REFUSED)["notices"][-1]

    assert "did not pick them up: this computer is already indexing another " \
           "batch" in notice


def test_take_over_does_not_blame_the_companion_for_a_dead_tray(tmp_path):
    """`ingestTakeOver`'s else arm printed a raw `e.message` into the notice,
    which for the two commonest failures is "Failed to fetch" or an HTTP code
    rather than anything the companion said."""
    notice = _node(tmp_path, NO_TRAY,
                   driver="await ingestTakeOver('b1');")["notices"][-1]

    assert "Failed to fetch" not in notice
    assert "did not answer" in notice
