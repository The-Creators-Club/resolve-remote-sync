"""The music ingest ledger: everything that writes `ingest_batches`/`ingest_items`.

docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18. `routes_batches.py` is the
browser's half and `routes_fleet.py` the companion's; both are thin, and every
rule that decides what a batch or an item may become is here, once.

WHY THIS IS A SECOND IMPLEMENTATION AND NOT AN IMPORT of
`broll/web/app/ingest_batches.py`, which does the same job for clips. Three
reasons, in order of weight:

  1. **musicweb may not import `app`.** broll/web is deployed as a tree
     imported as the top-level package `app` (CLAUDE.md: "the music web
     package is `musicweb`, deliberately NOT `app`" -- two packages of that
     name collide in sys.modules and one silently wins). Importing it here
     would make the music mount depend on the b-roll checkout being present,
     importable and the same vintage, and both mounts are built so that a
     broken one cannot take the other -- or the dashboard -- down.
  2. **The shared part is the small part.** The state machines, the lease, the
     counters and cancel-as-a-request are the same shape, and they are copied
     with their reasoning intact. Everything that touches data is not: b-roll
     mints `videos` rows at claim and allocates archive directories against
     published `archive_path`s; music mints nothing until `result`, lands one
     flat file per track, and de-duplicates with two entirely different
     defences. Sharing the frame while the body differs is how a "shared"
     module becomes two code paths in a trench coat.
  3. `identity.py` IS vendored byte-for-byte with a parity gate, because a
     verifier is exactly the thing that must not have two opinions. That is
     the test of whether a copy should be mechanical: this file could not be,
     and says why here rather than pretending.

WHAT THIS MODULE GUARANTEES that neither caller can:

  * **A `tracks` row is only written when there is something real to write.**
    b-roll can mint a hidden row at claim because `videos.status='ingesting'`
    is excluded from browse, tree and search. `tracks` has no status column,
    and /api/facets, /api/stats, the tag percentiles and the debias axes all
    read EVERY row -- a placeholder with no embedding would not hide, it would
    skew the library's own scoring. So the row lands at `result`, with the
    embedding, and `uploaded` is what verifies its audio actually arrived.
  * **Nothing is in-memory-only.** A stage that lives in a companion's process
    restarts from zero after a reboot, and a batch that lives there is one
    nobody can cancel. Same rule as the sync lanes' latches
    (docs/SYNC_SAFETY.md).
  * **Both duplicate defences run before anything is written**, the same two
    `musicweb.db` already applies to a browser upload: normalised stem +
    duration (`find_reencode`, which catches a re-encode that hashing cannot
    see) and the whole-file blake2b (`find_content_duplicate_by_digest`).

Refusals are raised as HTTPException with the exact bodies the plan promises --
the shape of a 409 is part of the contract the companion retries against.
"""
import json
import logging
import os
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi import HTTPException

from musicweb import config, db, rescore

log = logging.getLogger(__name__)

# --- state machines -----------------------------------------------------------

BATCH_STATES = ('queued', 'claimed', 'running', 'done', 'done_with_errors',
                'cancelled', 'failed')
# A batch in one of these is over: no lease, no more work, and every fleet call
# against it answers 410.
BATCH_TERMINAL = frozenset({'done', 'done_with_errors', 'cancelled', 'failed'})

# The one legal route through a track, in order. Re-posting the SAME state is
# allowed (that is how stage_percent is reported); going backwards is not, or a
# late-arriving retry of an earlier POST would un-index a track that has
# already been embedded.
ITEM_PROGRESS = ('pending', 'transcoding', 'embedding', 'indexed', 'uploading',
                 'live')
_ITEM_ORDER = {name: i for i, name in enumerate(ITEM_PROGRESS)}
# Ends the item, whatever it was doing. `failed` is the ONE terminal state that
# can be left again (retry): a decode that failed once is worth a second
# attempt and a cancelled batch is not.
#
# `queued_for_base_rig` is music's own, and it is the fallback the plan keeps
# (§1, rejected option (a)): a companion with no CLAP sidecar -- too old, or a
# model download that will not complete -- ends its items here rather than
# failing them.
#
# WHAT IT DOES NOT DO, despite the name and despite the plan's wording
# (music-6, 2026-08-21, and KNOWN_BUGS MUSIC-ING-2): it does not upload the
# audio and it does not leave an `ingest_queue` row -- there is no `queue_add`
# on this side at all. It cannot upload: the library allocates a filename at
# `result`, which never happened for that item. So the audio stays staged on
# the EDITOR'S machine and the page asks them to drop it through the browser
# upload, which does the whole safe dance. Nothing waits for the drain, and a
# drain run in the belief that something does will find nothing. The route that
# would make the name good (`POST .../items/{iuid}/queue`) is MUSIC-ING-2's
# open half.
ITEM_ENDINGS = ('duplicate', 'failed', 'cancelled', 'skipped',
                'queued_for_base_rig')
ITEM_STATES = ITEM_PROGRESS + ITEM_ENDINGS
ITEM_TERMINAL = frozenset({'live', 'duplicate', 'cancelled', 'skipped',
                           'queued_for_base_rig'})
# What "nothing left to do with this track" means, for n_done.
ITEM_FINISHED = ITEM_TERMINAL | {'failed'}

# Settings the create route accepts. 'idle' is the proxy generator's behaviour
# (runs when the editor is away, pauses when they come back); 'foreground'
# ignores the idle gate. There is deliberately no tier: music ingest does not
# use the GPU at all (the CLAP audio tower runs ~93 ms per 10 s window on CPU),
# which is also why it never blocks proxy generation.
RUN_MODES = ('idle', 'foreground')

# What the SPA and the companion agree is audio. The same set
# `routes_ingest.AUDIO_EXTS` accepts, and for the same reason it is a copy
# there: the container cannot import `music_index.config`.
AUDIO_EXTS = {'.wav', '.mp3', '.flac', '.aac', '.m4a', '.ogg', '.aiff', '.aif',
              '.opus'}
# .ogg becomes a 320k mp3 on the way in -- the rule routes_ingest applies to a
# browser upload, applied by the companion instead so the bytes crossing the
# wire are the bytes that land.
TRANSCODE_EXTS = {'.ogg'}


# --- small helpers ------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def new_uid(conn):
    """A 32-hex-character id, minted by SQLite's own CSPRNG.

    `lower(hex(randomblob(16)))` -- the precedent `ingest_queue.uid`
    (migrations/003) set -- rather than an autoincrement: these ids travel
    through a browser and a loopback POST, and a guessable integer would let
    any logged-in editor drive another editor's batch. 128 bits is also what
    the dashboard's login_gate carve-out regex pins, so the shape is
    load-bearing.
    """
    return conn.execute('SELECT lower(hex(randomblob(16)))').fetchone()[0]


def lease_live(batch, now=None):
    expires = _parse_iso(batch['lease_expires_at'])
    if expires is None:
        return False
    return expires > (now or datetime.now(timezone.utc))


def load_settings(batch):
    """The settings blob as a dict, never an exception.

    A batch whose JSON cannot be parsed is one the SPA can still list and
    cancel; refusing to render it would strand it.
    """
    try:
        parsed = json.loads(batch['settings_json'] or '{}')
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def validate_settings(raw):
    """The settings the batch will actually run under, or 422."""
    if not isinstance(raw, dict):
        raise HTTPException(422, 'settings must be an object')
    run_mode = str(raw.get('run_mode') or 'idle').strip().lower()
    if run_mode not in RUN_MODES:
        raise HTTPException(422, f'run_mode must be one of {", ".join(RUN_MODES)}')
    return {'run_mode': run_mode}


def _ext(name):
    return Path(str(name or '')).suffix.lower()


def final_name_for(orig_name, transcoded=None):
    """What a dropped file will be CALLED once it lands, before collisions.

    Through `db.safe_upload_name` -- the same reduction a browser upload gets,
    basename only and every character Windows forbids replaced -- and then
    through the .ogg -> .mp3 rule, because the companion transcodes before it
    uploads and the name has to follow the bytes.
    """
    name = db.safe_upload_name(orig_name)
    if transcoded is None:
        transcoded = _ext(name) in TRANSCODE_EXTS
    if transcoded:
        name = Path(name).stem + '.mp3'
    return name


def allocate_name(conn, orig_name, transcoded=None, reserved=None):
    """A flat filename free in the library AND in this batch. -> str.

    `db.unique_dest` settles collisions against what is on DISK, which is the
    right question for a browser upload (the file lands in the same request).
    Dashboard ingest asks it before the bytes exist, so two items of one drop
    called `theme.wav` would both be told `theme.wav`, and the second upload
    would overwrite the first. `reserved` carries the names already handed out
    -- in this call, and by every unlanded item in the ledger -- and is checked
    alongside the disk. That is build_archive's BROLL-IDX-5 lesson, one
    library over: settle against CLAIMED names, never against what is on disk
    alone.

    The `tracks` table is the THIRD member of the collision set
    (bug-hunt-2026-09-03 music-3). The disk answers "free" for every candidate
    when the library mount is absent, or when a row's file was removed by hand
    without a --prune, and `write_item_result` upserts ON CONFLICT(rel_path):
    the old cue's embedding, windows and probe fields are replaced in place
    while its id -- and so its preview proxy -- stays. And a share this host
    cannot see is refused outright here rather than answered with a name, on
    the same helper music-1's gate uses, so there is one notion of "the share
    looks wrong" and not two.
    """
    ok, why = config.share_root_ready(conn)
    if not ok:
        raise HTTPException(503, why)
    reserved = reserved if reserved is not None else set()
    name = final_name_for(orig_name, transcoded)
    stem, ext = Path(name).stem, Path(name).suffix
    candidate, i = name, 2
    while (candidate.lower() in reserved or _taken_on_disk(candidate)
           or _taken_by_a_track(conn, candidate)):
        candidate = f'{stem} ({i}){ext}'
        i += 1
    reserved.add(candidate.lower())
    return candidate


def _spellings(name):
    """`name` and its other Unicode normalisation, longest-lived first.

    MEDIA-21 (resilience sweep 2026-08-28). Names are minted NFC
    (db.safe_upload_name) but the library on disk can hold the NFD spelling of
    the same characters, put there by a Mac over SMB or by an ingest from
    before that fix, and the two are different byte strings to exists() and to
    stat() on Linux (docs/GOTCHAS.md section 17, CR-90). So the QUESTION "is
    this the same name" is asked of both spellings, while whatever gets opened
    or stat()ed is still a path that exists on the disk exactly as written.
    """
    raw = str(name or '')
    seen, out = set(), []
    for cand in (raw, unicodedata.normalize('NFC', raw),
                 unicodedata.normalize('NFD', raw)):
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def _taken_on_disk(name):
    """True if the library already holds a file of this name.

    Never raises: `safe_join` refuses a name that tries to leave the share, and
    a name that cannot be joined is one nothing could have landed under either
    -- it is regenerated by the caller's collision loop.
    """
    for spelling in _spellings(name):
        try:
            if config.safe_join(config.share_root(), spelling).exists():
                return True
        except (config.PathTraversalError, config.UnknownShareError, OSError):
            return True
    return False


def _taken_by_a_track(conn, name):
    """True if an INDEXED track already claims this flat name.

    bug-hunt-2026-09-03 music-3: the library is flat, so rel_path IS the name,
    and both of its Unicode spellings are asked about for the same reason
    _taken_on_disk asks about both (CR-90). Never raises, and a query that
    cannot run counts as TAKEN: the collision loop simply mints another name,
    which is the harmless direction.
    """
    try:
        for spelling in _spellings(name):
            if conn.execute('SELECT 1 FROM tracks WHERE rel_path = ? LIMIT 1',
                            (spelling,)).fetchone():
                return True
    except sqlite3.Error:
        return True
    return False


def reserved_names(conn):
    """Every name an unlanded item has already been promised, lowercased."""
    rows = conn.execute(
        "SELECT dest_name FROM ingest_items WHERE dest_name IS NOT NULL "
        "AND state NOT IN ('cancelled','failed','skipped','duplicate')")
    return {r['dest_name'].lower() for r in rows if r['dest_name']}


# --- reading ------------------------------------------------------------------

def get_batch(conn, uid):
    return conn.execute('SELECT * FROM ingest_batches WHERE uid = ?',
                        (uid,)).fetchone()


def get_item(conn, batch_uid, item_uid):
    return conn.execute(
        'SELECT * FROM ingest_items WHERE uid = ? AND batch_uid = ?',
        (item_uid, batch_uid)).fetchone()


def list_items(conn, batch_uid):
    return conn.execute(
        'SELECT * FROM ingest_items WHERE batch_uid = ? ORDER BY ord, uid',
        (batch_uid,)).fetchall()


def batch_public(batch):
    """One batch as both APIs report it. Scalars only: this is polled every few
    seconds by the SPA and rides the fleet grid."""
    out = {k: batch[k] for k in batch.keys() if k != 'settings_json'}
    out['settings'] = load_settings(batch)
    out['cancel_requested'] = bool(batch['cancel_requested'])
    out['upload_paused'] = bool(batch['upload_paused'])
    return out


def item_public(item):
    out = {k: item[k] for k in item.keys()}
    out['transcoded'] = bool(item['transcoded'])
    return out


def list_batches(conn, editor=None, limit=200):
    """Newest first. `editor=None` is the admin's "all machines" view; every
    other caller passes a name, because a batch names the machine an editor is
    sitting at and that is nobody else's business."""
    sql = 'SELECT * FROM ingest_batches'
    params = []
    if editor is not None:
        sql += ' WHERE editor = ?'
        params.append(editor)
    sql += ' ORDER BY created_at DESC, uid DESC LIMIT ?'
    params.append(limit)
    return [batch_public(r) for r in conn.execute(sql, params).fetchall()]


# --- counters -----------------------------------------------------------------

def _recount(conn, batch_uid):
    """Counters recomputed from the items, never incremented.

    An increment is one lost/duplicated POST away from a batch that says 39 of
    40 forever, and the item table is at most MAX_BATCH_ITEMS rows -- the read
    costs less than the bug does.
    """
    rows = conn.execute(
        'SELECT state, COUNT(*) n FROM ingest_items WHERE batch_uid = ? '
        'GROUP BY state', (batch_uid,)).fetchall()
    by_state = {r['state']: r['n'] for r in rows}
    counts = {
        'n_items': sum(by_state.values()),
        'n_done': sum(n for s, n in by_state.items() if s in ITEM_FINISHED),
        'n_failed': by_state.get('failed', 0),
        'n_live': by_state.get('live', 0),
        'n_duplicate': by_state.get('duplicate', 0),
    }
    conn.execute(
        'UPDATE ingest_batches SET n_items = ?, n_done = ?, n_failed = ?, '
        'n_live = ?, n_duplicate = ?, updated_at = ? WHERE uid = ?',
        (counts['n_items'], counts['n_done'], counts['n_failed'],
         counts['n_live'], counts['n_duplicate'], now_iso(), batch_uid))
    return counts


# --- duplicate defences -------------------------------------------------------

def duplicate_for(conn, *, name, duration, content_hash, size):
    """Is this file already in the library? -> (track_id|None, name|None).

    BOTH of `musicweb.db`'s existing defences, in the order routes_ingest runs
    them, and against a file that is still on the editor's machine:

      1. `find_reencode` -- normalised stem plus a duration within 2 s. This is
         the one hashing cannot do: transcoding an .ogg changes every byte, so
         a re-encode of a track already held sails past a content hash. Run on
         the ORIGINAL name and the probed duration, before any transcode.
      2. `find_content_duplicate_by_digest` -- the whole-file blake2b-16, the
         same digest `db.content_hash` computes, against library rows whose
         byte count already matches (and against the base-rig queue).

    Advisory at pre-check time and decisive at create: the editor is shown what
    was found and unticks or keeps it, exactly as the drag-and-drop upload path
    reports a duplicate rather than silently dropping it.
    """
    rel = db.find_reencode(conn, name, duration)
    if not rel and content_hash:
        rel = db.find_content_duplicate_by_digest(conn, content_hash, size)
    if not rel:
        return None, None
    row = conn.execute('SELECT id, filename FROM tracks WHERE rel_path = ?',
                       (rel,)).fetchone()
    return (row['id'] if row else None), (row['filename'] if row else rel)


# --- create + precheck (the SPA's half) ---------------------------------------

def precheck(conn, items):
    """Per item: already in the library, and what will it be called?

    Read-only and reserves NOTHING -- it runs while the editor is still ticking
    boxes, and a name reserved here would be a name leaked by every abandoned
    drop. The real allocation happens at `result`; this is a preview of it, and
    the SPA says so.
    """
    reserved = set()
    out = []
    for item in items:
        duplicate_of, duplicate_name = duplicate_for(
            conn, name=item.name, duration=item.duration,
            content_hash=item.content_hash, size=item.size)
        out.append({
            'local_id': item.local_id,
            'duplicate_of': duplicate_of,
            'duplicate_name': duplicate_name,
            'final_name': allocate_name(conn, item.name, reserved=reserved),
            'unsupported': _ext(item.name) not in AUDIO_EXTS or None,
        })
    return out


def create_batch(conn, *, editor, settings, items, share=None):
    """Mint a queued batch and its items. Returns the batch uid.

    No `tracks` rows, no names and no files: a batch no machine ever picks up
    must leave nothing behind but a row the editor can see and cancel.
    """
    if not items:
        raise HTTPException(422, 'a batch needs at least one track')
    if len(items) > config.MAX_BATCH_ITEMS:
        raise HTTPException(
            422, f'a batch may hold at most {config.MAX_BATCH_ITEMS} tracks '
                 f'({len(items)} were sent)')
    bad = [i.name for i in items if _ext(i.name) not in AUDIO_EXTS]
    if bad:
        # Refused, not silently dropped: an editor who dragged a folder in
        # should be told which files are not audio, not left counting.
        raise HTTPException(422, {
            'detail': f'{len(bad)} of these are not audio files',
            'reason': 'not_audio', 'names': bad[:20]})

    created = now_iso()
    uid = new_uid(conn)
    share = share or config.SHARE
    with conn:
        conn.execute(
            'INSERT INTO ingest_batches (uid, editor, share, settings_json, '
            "state, n_items, created_at, updated_at) VALUES (?, ?, ?, ?, "
            "'queued', ?, ?, ?)",
            (uid, editor, share, json.dumps(settings, sort_keys=True),
             len(items), created, created))
        for ord_, item in enumerate(items):
            duplicate_of, _name = duplicate_for(
                conn, name=item.name, duration=item.duration,
                content_hash=item.content_hash, size=item.size)
            conn.execute(
                'INSERT INTO ingest_items (uid, batch_uid, ord, orig_name, '
                'size_bytes, content_hash, duration_s, source, duplicate_of, '
                "state, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "'pending', ?)",
                (new_uid(conn), uid, ord_, item.name, item.size,
                 item.content_hash or None, item.duration, item.source,
                 duplicate_of, created))
    log.info('music ingest: %s queued batch %s (%d tracks)', editor, uid,
             len(items))
    return uid


def cancel(conn, uid, by):
    """Ask for a stop, and take the lease away in the same breath.

    A REQUEST, not a kill: the companion is mid-ffmpeg or mid-embedding and
    learns about this on its next heartbeat (410) or from the report reply,
    then stops and releases. Expiring the lease at the same time is what makes
    the NEXT fleet call 410 even if the heartbeat is the call that lands first
    (YTDL-WEB-1's lesson, 2026-08-14).
    """
    with conn:
        conn.execute(
            'UPDATE ingest_batches SET cancel_requested = 1, cancel_by = ?, '
            'lease_expires_at = NULL, updated_at = ? WHERE uid = ?',
            (by, now_iso(), uid))
    log.info('music ingest: batch %s cancel requested by %s', uid, by)


def set_upload_paused(conn, uid, paused):
    with conn:
        conn.execute(
            'UPDATE ingest_batches SET upload_paused = ?, updated_at = ? '
            'WHERE uid = ?', (1 if paused else 0, now_iso(), uid))


def cancel_requested_for(conn, editor, machine=None):
    """Batch uids this editor+machine should stop, for the report reply.

    Best-effort by contract: it must never fail a report. A pre-004 database
    has no such table and gets an empty list.
    """
    try:
        placeholders = ', '.join('?' for _ in BATCH_TERMINAL)
        params = [editor, *sorted(BATCH_TERMINAL)]
        sql = ('SELECT uid FROM ingest_batches WHERE cancel_requested = 1 '
               f'AND editor = ? AND state NOT IN ({placeholders})')
        if machine:
            sql += ' AND (machine IS NULL OR machine = ?)'
            params.append(machine)
        return [r['uid'] for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


# --- leases (the companion's half) --------------------------------------------

def expire_stale_leases(conn, now=None):
    """Hand back every batch whose machine stopped talking. Returns how many.

    Back to `queued`, not to a terminal state: the work is still wanted, and
    the same editor's companion (that machine on restart, or another of theirs)
    re-claims it and resumes from the items' own recorded stages. `machine` is
    deliberately LEFT in place so the SPA can still say "waiting for
    <machine>".

    Called opportunistically from list and claim rather than on a timer,
    because this app has no timer: the dashboard runs uvicorn with workers=1
    and a background thread here would be a thread the fleet status page waits
    behind.

    The comparison is a STRING one, which is only sound because every
    `lease_expires_at` in this table is written by this module as a UTC
    `datetime.isoformat()` -- same offset, same field widths, so lexical order
    is chronological order.
    """
    cutoff = (now or datetime.now(timezone.utc)).isoformat()
    with conn:
        cur = conn.execute(
            "UPDATE ingest_batches SET state = 'queued', lease_expires_at = NULL, "
            'current_item_uid = NULL, updated_at = ? '
            "WHERE state IN ('claimed', 'running') AND lease_expires_at IS NOT NULL "
            'AND lease_expires_at < ?', (now_iso(), cutoff))
    if cur.rowcount:
        log.info('music ingest: %d batch lease(s) expired and went back to queued',
                 cur.rowcount)
    return cur.rowcount


def claim(conn, *, batch_uid, editor, machine, companion_version, capabilities=None):
    """Take the batch and receive the work order. One transaction.

    IDEMPOTENT for the machine that already holds it: a companion restarting
    mid-batch re-issues exactly this call and must get the same manifest back.

    It mints NOTHING in `tracks` -- see the module docstring. What a claim
    actually settles is: which machine owns this batch, until when, and what
    the items are.

    Refusals: 403 the verified identity is not this batch's editor (the one
    thing here that is NOT 410, because it means "wrong credentials", not
    "your claim is over"); 409 another of this editor's machines holds a live
    lease; 410 the batch is cancelled or finished.
    """
    expire_stale_leases(conn)
    batch = get_batch(conn, batch_uid)
    if batch is None:
        raise HTTPException(404, 'no such batch')
    if batch['editor'] != editor:
        raise HTTPException(403, {'detail': 'this batch belongs to another editor',
                                  'reason': 'identity'})
    if batch['cancel_requested'] and (batch['state'] not in BATCH_TERMINAL
                                      or batch['state'] == 'cancelled'):
        raise HTTPException(410, {'detail': 'this batch has been cancelled',
                                  'reason': 'cancelled'})
    if batch['state'] in BATCH_TERMINAL:
        raise HTTPException(410, {'detail': f'this batch is {batch["state"]}',
                                  'reason': 'finished', 'state': batch['state']})
    if batch['machine'] and batch['machine'] != machine and lease_live(batch):
        raise HTTPException(409, {
            'detail': f'{batch["machine"]} is already indexing this batch',
            'machine': batch['machine'],
            'lease_expires_at': batch['lease_expires_at']})

    now = now_iso()
    expires = (datetime.now(timezone.utc)
               + timedelta(seconds=config.LEASE_SECONDS)).isoformat()
    with conn:
        conn.execute(
            "UPDATE ingest_batches SET state = CASE WHEN state = 'running' "
            "THEN 'running' ELSE 'claimed' END, machine = ?, "
            'companion_version = ?, claimed_at = COALESCE(claimed_at, ?), '
            'lease_expires_at = ?, last_heartbeat_at = ?, error = NULL, '
            'updated_at = ? WHERE uid = ?',
            (machine, companion_version, now, expires, now, now, batch_uid))
        _recount(conn, batch_uid)

    log.info('music ingest: %s claimed batch %s on %s (companion %s)',
             editor, batch_uid, machine, companion_version)
    fresh = get_batch(conn, batch_uid)
    return {
        'batch': batch_public(fresh),
        'settings': load_settings(fresh),
        'lease_seconds': config.LEASE_SECONDS,
        'heartbeat_seconds': config.HEARTBEAT_SECONDS,
        # Where the library is ON THE REMOTE, relative to the rclone remote's
        # root -- never a local path. Only the companion knows what that root
        # is mapped to on the machine it is running on, exactly as
        # /music/send's contract has it (never trust the page with paths, and
        # never tell the server about drive letters).
        'library_remote_rel': 'Assets/Music',
        'transcode_exts': sorted(TRANSCODE_EXTS),
        'audio_exts': sorted(AUDIO_EXTS),
        'items': [{
            'uid': i['uid'], 'ord': i['ord'], 'orig_name': i['orig_name'],
            'size_bytes': i['size_bytes'], 'content_hash': i['content_hash'],
            'duration_s': i['duration_s'], 'state': i['state'],
            'duplicate_of': i['duplicate_of'], 'source': i['source'],
            'dest_name': i['dest_name'], 'track_id': i['track_id'],
            'attempts': i['attempts'],
        } for i in list_items(conn, batch_uid)],
    }


def heartbeat(conn, batch):
    """Extend the lease. Answers with the two flags the companion acts on."""
    expires = (datetime.now(timezone.utc)
               + timedelta(seconds=config.LEASE_SECONDS)).isoformat()
    now = now_iso()
    with conn:
        conn.execute(
            'UPDATE ingest_batches SET lease_expires_at = ?, last_heartbeat_at = ?, '
            'updated_at = ? WHERE uid = ?', (expires, now, now, batch['uid']))
    fresh = get_batch(conn, batch['uid'])
    return {'ok': True, 'cancel_requested': bool(fresh['cancel_requested']),
            'upload_paused': bool(fresh['upload_paused']),
            'lease_expires_at': fresh['lease_expires_at'],
            'lease_seconds': config.LEASE_SECONDS}


# --- per-item transitions ------------------------------------------------------

def _check_transition(old, new):
    """Monotonic, with exactly one way back: `failed` -> retry.

    Enforced server-side because the companion is not the only writer of an
    item's stage -- a cancel writes it too -- and because a retried POST that
    arrives late must not un-index a track that has since been embedded. 400,
    not 409: the companion sent something illegal, and naming the two states is
    what makes that debuggable from a log line.
    """
    if new not in ITEM_STATES:
        raise HTTPException(400, f'unknown item state {new!r}')
    if old == new:
        return
    if new in ITEM_ENDINGS:
        if old in ITEM_TERMINAL:
            raise HTTPException(400, {
                'detail': f'item is already {old}; it cannot become {new}',
                'reason': 'illegal_transition', 'state': old})
        return
    if old == 'failed':
        return  # retry
    if old in ITEM_TERMINAL:
        raise HTTPException(400, {
            'detail': f'item is already {old}; it cannot become {new}',
            'reason': 'illegal_transition', 'state': old})
    if _ITEM_ORDER[new] < _ITEM_ORDER[old]:
        raise HTTPException(400, {
            'detail': f'an item cannot go back from {old} to {new}',
            'reason': 'illegal_transition', 'state': old})


_PROBE_COLUMNS = ('duration_s', 'samplerate', 'channels', 'codec')


def _apply_probe(conn, item_uid, probe):
    """ffprobe's answers onto the item row. COALESCE so a probe that only
    carries a duration cannot blank the codec a previous one recorded."""
    values = [probe.get(c) for c in _PROBE_COLUMNS]
    conn.execute(
        'UPDATE ingest_items SET '
        + ', '.join(f'{c} = COALESCE(?, {c})' for c in _PROBE_COLUMNS)
        + ' WHERE uid = ?', [*values, item_uid])


def set_item_state(conn, batch, item, *, state, stage_percent=None, error=None,
                   attempts=None, content_hash=None, transcoded=None, probe=None):
    """Record where a track has got to, and drag the batch along with it."""
    _check_transition(item['state'], state)
    now = now_iso()
    with conn:
        conn.execute(
            'UPDATE ingest_items SET state = ?, stage_percent = ?, '
            'error = COALESCE(?, error), attempts = COALESCE(?, attempts), '
            'content_hash = COALESCE(?, content_hash), '
            'transcoded = COALESCE(?, transcoded), updated_at = ? WHERE uid = ?',
            (state, stage_percent, error, attempts, content_hash,
             None if transcoded is None else int(bool(transcoded)), now,
             item['uid']))
        if probe:
            _apply_probe(conn, item['uid'], probe)
        # `running` is entered by the FIRST item that starts, not by the claim:
        # a batch that was claimed and then blocked on the idle gate for three
        # hours is honestly `claimed`, and the fleet grid says so.
        if state != 'pending' and batch['state'] == 'claimed':
            conn.execute(
                "UPDATE ingest_batches SET state = 'running', "
                'started_at = COALESCE(started_at, ?), updated_at = ? WHERE uid = ?',
                (now, now, batch['uid']))
        conn.execute(
            'UPDATE ingest_batches SET current_item_uid = ?, updated_at = ? '
            'WHERE uid = ?',
            (None if state in ITEM_FINISHED else item['uid'], now, batch['uid']))
        counts = _recount(conn, batch['uid'])
    return {'ok': True, 'state': state, **counts}


# --- the result: a real track row ---------------------------------------------

def _float32(raw):
    """`raw` as a float32 vector, or None if those bytes are not one.

    numpy raises ValueError for a buffer whose length is not a multiple of the
    element size, and an uncaught one on a fleet route is a 500 with a
    traceback (music-5, 2026-08-21). The length check is the whole difference
    between a refusal the companion can act on and a retry loop.
    """
    raw = raw or b''
    if len(raw) % 4:
        return None
    return np.frombuffer(raw, dtype='<f4')


def _embedding_blob(body):
    """The companion's float32 embedding, as the BLOB `tracks.embedding` holds.

    Re-normalised here rather than trusted: every consumer in this database
    assumes unit vectors (cosine is a dot product throughout search.py and
    rescore.py), and a vector that arrived slightly off unit length -- fp16
    rounding, a different pooling, a truncated body -- would not fail, it would
    quietly rank wrong. The dimension is checked against what the library
    already holds, because an embedding of another width is an embedding from
    another model and cannot be compared with these at all.
    """
    vec = _float32(body.embedding_bytes())
    if vec is None:
        # music-5, 2026-08-21: np.frombuffer raises ValueError on a byte count
        # that is not a multiple of 4, nothing here mapped that to a refusal,
        # and the companion treated the resulting 500 as transient and retried
        # the same truncated body until its budget ran out. Attacker-shaped
        # input on a token-reachable route is a refusal, never a traceback.
        raise HTTPException(422, {
            'detail': 'the embedding is not a float32 vector',
            'reason': 'embedding'})
    if vec.size == 0:
        raise HTTPException(422, {'detail': 'the embedding is empty',
                                  'reason': 'embedding'})
    if body.dim and int(body.dim) != int(vec.size):
        raise HTTPException(422, {
            'detail': f'the embedding is {vec.size} floats but declares dim '
                      f'{body.dim}', 'reason': 'embedding'})
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm <= 0:
        raise HTTPException(422, {'detail': 'the embedding is not a finite vector',
                                  'reason': 'embedding'})
    return db.to_blob(vec / norm), int(vec.size)


def _library_dim(conn):
    row = conn.execute('SELECT dim FROM tracks WHERE embedding IS NOT NULL '
                       'ORDER BY id LIMIT 1').fetchone()
    return int(row['dim']) if row and row['dim'] else None


def write_item_result(conn, batch, item, body):
    """The track row, from the embedding the editor's machine computed.

    This is where a music item differs most from a b-roll one. There is no
    `videos` row waiting to be filled in: the row is CREATED here, with its
    embedding, its probe fields and its waveform, under a name allocated
    against the library and against every other unlanded item.

    The audio itself is still on the editor's machine at this point -- the
    companion uploads it next and calls `uploaded`, which is what verifies it
    landed. In between, the track is searchable and its audio is not there yet;
    that window is seconds long, is the price of `tracks` having no status
    column (see the module docstring), and is the reason `uploaded` stat()s
    rather than believing.

    Then the library is re-scored (`rescore.apply_for_track`): tags, axes and
    the source-bias directions are all relative to the library, so a new track
    changes everybody's numbers, and there is no cheaper honest version.
    """
    if item['track_id']:
        # A retried result for a track this batch already wrote: update it in
        # place rather than allocating a second name for the same audio.
        dest_name = item['dest_name']
    else:
        dest_name = allocate_name(
            conn, body.name or item['orig_name'],
            transcoded=bool(body.transcoded),
            reserved=reserved_names(conn))
    _check_transition(item['state'], 'indexed')

    blob, dim = _embedding_blob(body)
    library_dim = _library_dim(conn)
    if library_dim and dim != library_dim:
        # Not a 500 and not silence: an embedding of another width is another
        # model's, and mixing two models in one index makes every cosine in it
        # meaningless. The companion is told which two numbers disagree so the
        # operator can see it is a model-version problem.
        raise HTTPException(409, {
            'detail': f'this library is indexed at {library_dim} dimensions and '
                      f'the embedding has {dim}; the companion is running a '
                      f'different CLAP model version',
            'reason': 'model_mismatch', 'expected_dim': library_dim, 'dim': dim})

    now = now_iso()
    probe = body.probe or {}
    # Whether this is a NEW row decides one thing outside the database
    # (music-4, 2026-08-21): a created row takes max(rowid)+1, which is the id
    # of the highest row ever deleted, and the preview proxy is keyed by id
    # alone. Read before the INSERT, acted on after it commits.
    created = conn.execute('SELECT id FROM tracks WHERE rel_path = ?',
                           (dest_name,)).fetchone() is None
    try:
        with conn:
            cur = conn.execute(
                'INSERT INTO tracks(share, rel_path, filename, ext, bytes, '
                'duration, samplerate, channels, codec, bpm, music_key, '
                'key_conf, lufs, peak_db, embedding, dim, file_hash, model, '
                'analyzed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(rel_path) DO UPDATE SET '
                'bytes=excluded.bytes, duration=excluded.duration, '
                'samplerate=excluded.samplerate, channels=excluded.channels, '
                'codec=excluded.codec, bpm=excluded.bpm, '
                'music_key=excluded.music_key, key_conf=excluded.key_conf, '
                'lufs=excluded.lufs, peak_db=excluded.peak_db, '
                'embedding=excluded.embedding, dim=excluded.dim, '
                'model=excluded.model, analyzed_at=excluded.analyzed_at',
                (batch['share'] or config.SHARE, dest_name, dest_name,
                 Path(dest_name).suffix.lower(), body.size_bytes,
                 body.duration, probe.get('samplerate'), probe.get('channels'),
                 probe.get('codec'), body.bpm, body.music_key, body.key_conf,
                 body.lufs, body.peak_db, blob, dim,
                 # file_hash is the indexer's size+mtime fingerprint and this
                 # host has no file to stat yet. The CONTENT hash is what
                 # dashboard ingest knows, and recording it here is what stops
                 # a later sweep re-analysing a track it already has.
                 body.content_hash or None, body.model, now))
            track_id = conn.execute('SELECT id FROM tracks WHERE rel_path = ?',
                                    (dest_name,)).fetchone()['id']
            _write_windows(conn, track_id, body)
            _write_peaks(conn, track_id, body)
            conn.execute(
                "UPDATE ingest_items SET state = 'indexed', stage_percent = 100, "
                'error = NULL, track_id = ?, dest_name = ?, transcoded = ?, '
                'content_hash = COALESCE(?, content_hash), updated_at = ? '
                'WHERE uid = ?',
                (track_id, dest_name, int(bool(body.transcoded)),
                 body.content_hash or None, now, item['uid']))
            _apply_probe(conn, item['uid'], {
                'duration_s': body.duration, **{k: probe.get(k) for k in
                                                ('samplerate', 'channels', 'codec')}})
            if batch['state'] == 'claimed':
                conn.execute(
                    "UPDATE ingest_batches SET state = 'running', "
                    'started_at = COALESCE(started_at, ?), updated_at = ? '
                    'WHERE uid = ?', (now, now, batch['uid']))
            counts = _recount(conn, batch['uid'])
    except sqlite3.IntegrityError as exc:
        # Overwhelmingly UNIQUE(rel_path): another batch landed this name
        # between the allocation and the INSERT. The companion retries the
        # result, which re-allocates around it.
        log.warning('music ingest: result for %s hit a constraint: %s',
                    item['uid'], exc)
        raise HTTPException(409, {
            'detail': 'another batch claimed that filename first; retry',
            'reason': 'name_race'}) from exc

    if created:
        # Any mp3 already sitting at this id belonged to a track that was
        # deleted; serving it would give this cue another one's audio
        # (music-4). Cheap, and there is nothing to roll back: existence on
        # disk is the whole record a proxy has.
        config.drop_proxy(track_id)

    # OUTSIDE the transaction above, and after the counters: re-scoring reads
    # every embedding and writes every tag row, and holding the item's write
    # open across it would keep a lock on the database the fleet grid also
    # reads. A failure here leaves the track written and untagged, which the
    # next result (or a base-rig retag) fixes -- so it is reported, not fatal.
    scores = {}
    try:
        scores = rescore.apply_for_track(conn, track_id)
    except Exception as exc:                                    # noqa: BLE001
        # ROLLBACK FIRST (MUSIC-1, 2026-09-04). rescore_library rolls back its
        # own connection, but this handler must not depend on that: `conn` is
        # this thread's CACHED connection, and handing it back inside an open
        # write transaction meant the next write on this thread committed
        # whatever was in it -- which, for the failure this catches, is
        # "the library has no tags and no axes". A second rollback is a no-op.
        conn.rollback()
        rescore.mark_scores_stale(conn)
        log.error('music ingest: track %s written but not scored (%s: %s); it is '
                  'searchable by similarity and has no tags until the next '
                  'result or a base-rig --retag', track_id, type(exc).__name__, exc)
        scores = {'error': f'{type(exc).__name__}: {exc}',
                  'scores_stale': rescore.scores_stale(conn)}
    return {'ok': True, 'state': 'indexed', 'track_id': track_id,
            'rel_path': dest_name, 'scores': scores, **counts}


def _write_windows(conn, track_id, body):
    """Per-window vectors, if the companion sent them.

    Optional on purpose: `text_search(pool='max')` scores a track by its best
    10 s window and is measurably better for it (40% vs 20% top-10), so they
    are wanted -- but a companion that sent only the pooled track vector still
    produces a searchable track, and refusing the result would be worse.
    DELETE-then-INSERT, because a re-analysis with fewer windows must not leave
    the tail of the previous one behind ranking in search.
    """
    conn.execute('DELETE FROM windows WHERE track_id = ?', (track_id,))
    rows = []
    for w in body.windows or []:
        vec = _float32(w.vector_bytes())
        if vec is None:
            # A window whose byte count is not a float32 vector at all. Dropped
            # like every other unusable window rather than 422'd (music-5,
            # 2026-08-21): windows are optional here by design, and this runs
            # INSIDE the item transaction, where a raised ValueError aborted
            # the block after the track INSERT and the companion saw a 500.
            log.warning('music ingest: window %s of track %s is %d bytes, not a '
                        'float32 vector; dropped', w.idx, track_id,
                        len(w.vector_bytes() or b''))
            continue
        norm = float(np.linalg.norm(vec))
        if vec.size == 0 or not np.isfinite(norm) or norm <= 0:
            continue
        rows.append((track_id, w.idx, w.t0, w.t1, db.to_blob(vec / norm)))
    if rows:
        conn.executemany(
            'INSERT INTO windows(track_id, idx, t0, t1, embedding) '
            'VALUES(?,?,?,?,?)', rows)


def _write_peaks(conn, track_id, body):
    """The waveform overview, uint8 per bucket, exactly as audio.peaks makes it."""
    data = body.peaks_bytes()
    if not data:
        return
    conn.execute('INSERT OR REPLACE INTO peaks(track_id, n, data) VALUES(?,?,?)',
                 (track_id, len(data), data))


# --- upload verification -------------------------------------------------------

def mark_uploaded(conn, batch, item, *, size=None):
    """The track goes live -- but only once the server has seen the bytes.

    The music share is mounted in this container (it is what /api/audio
    streams), so "did the upload land" is a `stat()`, not a promise. The path
    is the one the SERVER allocated at `result` and is read from the item row:
    nothing about it comes off the wire, so there is no path to validate and
    none to escape with.

    A 409 says exactly what is wrong -- absent, or the wrong size -- which is
    what lets an interrupted rclone retry the file instead of restarting the
    track.
    """
    if not item['track_id'] or not item['dest_name']:
        raise HTTPException(409, {
            'detail': 'this item has no track row yet; post its result first',
            'reason': 'unindexed'})
    # Every spelling of the allocated name, and the first one that is actually
    # there wins (MEDIA-21, 2026-08-28): the name was minted NFC but rclone
    # copies the bytes the editor's machine holds, and a Mac hands it NFD, so
    # stat()ing the NFC path alone answered "the library does not hold this
    # file yet" for a file sitting on the disk under the other spelling -- a
    # 409 not_uploaded loop with no way out. `rel_path` is then corrected to
    # the spelling on disk, because that is what /api/audio has to open.
    landed, path, actual = None, None, None
    for spelling in _spellings(item['dest_name']):
        try:
            cand = config.resolve_path(batch['share'] or config.SHARE, spelling)
        except (config.PathTraversalError, config.UnknownShareError) as exc:
            raise HTTPException(500, {
                'detail': f'the music share is not resolvable on this server: {exc}',
                'reason': 'share'}) from exc
        if path is None:
            path = cand
        try:
            actual = cand.stat().st_size
        except OSError:
            continue
        landed, path = spelling, cand
        break

    if landed is None:
        log.warning('music ingest: item %s not live -- %s is not in the library',
                    item['uid'], item['dest_name'])
        raise HTTPException(409, {
            'detail': 'the library does not hold this file yet',
            'reason': 'not_uploaded', 'rel_path': item['dest_name']})
    if size is not None and int(size) != actual:
        raise HTTPException(409, {
            'detail': 'the file in the library is not the size the companion sent',
            'reason': 'size_mismatch', 'rel_path': item['dest_name'],
            'declared': int(size), 'actual': actual})

    _make_readable_to_the_fleet(path)
    now = now_iso()
    with conn:
        if landed != item['dest_name']:
            log.warning('music ingest: item %s landed as %r, not %r (a Unicode '
                        'spelling difference); the track row now names what is '
                        'on the disk', item['uid'], landed, item['dest_name'])
            conn.execute('UPDATE tracks SET rel_path = ?, filename = ? WHERE id = ?',
                         (landed, os.path.basename(landed), item['track_id']))
            conn.execute('UPDATE ingest_items SET dest_name = ? WHERE uid = ?',
                         (landed, item['uid']))
        conn.execute('UPDATE tracks SET bytes = ? WHERE id = ?',
                     (actual, item['track_id']))
        conn.execute(
            "UPDATE ingest_items SET state = 'live', stage_percent = 100, "
            'error = NULL, updated_at = ? WHERE uid = ?', (now, item['uid']))
        conn.execute(
            'UPDATE ingest_batches SET current_item_uid = NULL, updated_at = ? '
            'WHERE uid = ?', (now, batch['uid']))
        counts = _recount(conn, batch['uid'])
    log.info('music ingest: item %s is live at %s (%d bytes)', item['uid'],
             item['dest_name'], actual)
    return {'ok': True, 'live': True, 'rel_path': landed,
            'bytes': actual, **counts}


def _make_readable_to_the_fleet(path):
    """Widen an ingested file's mode so editors can actually see it.

    The same fix `routes_ingest._make_readable_to_the_fleet` applies to a
    browser upload, applied to a file rclone put there instead: the dashboard
    container runs `umask 077` (deploy/run.sh), and a file created under the
    editor's own SMB/SFTP identity may still land 0600. Present on disk, in the
    index, and invisible over SMB is the one thing a shared library must not
    be. The share directory is setgid so the group is already right.

    A no-op on Windows, and non-fatal everywhere -- a file that landed but
    could not be chmod'ed is still better than a refused upload, and the
    symptom is visible rather than silent.
    """
    if os.name == 'nt':
        return
    try:
        os.chmod(path, 0o664)
    except OSError as exc:                                      # noqa: BLE001
        log.warning('could not widen mode on %s (%s); editors may not see it '
                    'over SMB until it is chmod 664', path, exc)


# --- finishing ----------------------------------------------------------------

def release(conn, batch, *, state, summary=None):
    """End the batch and drop the lease.

    `done` becomes `done_with_errors` when anything failed -- the companion
    reports what it did, the server decides what to call it, so a track that
    failed cannot be summarised away.

    On `cancelled`, items still in flight are cancelled with it. What is NOT
    deleted is any `tracks` row already written: unlike b-roll's `ingesting`
    videos, a music row only exists because a real embedding arrived, and if
    its audio never landed it is `indexed` rather than `live` -- visible in the
    ledger, fixable by re-uploading, and not a name-holding ghost.
    """
    if state not in ('done', 'failed', 'cancelled'):
        raise HTTPException(422, 'release state must be done, failed or cancelled')
    now = now_iso()
    with conn:
        counts = _recount(conn, batch['uid'])
        final = state
        if state == 'done' and counts['n_failed']:
            final = 'done_with_errors'
        if state == 'cancelled':
            conn.execute(
                "UPDATE ingest_items SET state = 'cancelled', updated_at = ? "
                'WHERE batch_uid = ? AND state NOT IN '
                "('live', 'duplicate', 'skipped', 'cancelled', 'queued_for_base_rig')",
                (now, batch['uid']))
        conn.execute(
            'UPDATE ingest_batches SET state = ?, error = ?, finished_at = ?, '
            'lease_expires_at = NULL, current_item_uid = NULL, updated_at = ? '
            'WHERE uid = ?',
            (final, _summary_text(summary), now, now, batch['uid']))
        counts = _recount(conn, batch['uid'])
    log.info('music ingest: batch %s released as %s (%d live, %d failed)',
             batch['uid'], final, counts['n_live'], counts['n_failed'])
    return {'ok': True, 'state': final, **counts}


def _summary_text(summary):
    """Whatever the companion said, as one short string for `error`.

    Capped because it is rendered in a tooltip on the fleet grid and a
    companion traceback pasted whole would push everything else off it.
    """
    if summary in (None, '', {}, []):
        return None
    text = summary if isinstance(summary, str) else json.dumps(summary, default=str)
    return text[:500]
