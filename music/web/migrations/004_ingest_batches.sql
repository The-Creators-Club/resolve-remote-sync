-- Drag-and-drop MUSIC ingest: the work orders the dashboard hands a companion,
-- and the per-track ledger it reports back against
-- (docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18).
--
-- The same two tables b-roll got in broll/web/migrations/011_ingest_batches.sql,
-- and deliberately so -- the state machine, the lease, the counters and the
-- cancel-as-a-request rule are the same problem twice. Three parties share
-- them and none can see the others' memory: the browser only dispatches, the
-- companion crunches locally under a fleet token, and this database is the
-- only place the truth about a batch lives. So EVERY transition is a row here.
-- A batch that exists only in a companion's process is a batch nobody can
-- cancel; a track whose stage lives only in RAM restarts from zero after a
-- reboot. Same rule the sync lanes' latches follow (docs/SYNC_SAFETY.md).
--
-- WHERE IT DIFFERS FROM B-ROLL'S 011, and why each one:
--
--   * `track_id` instead of `video_id`, and **it is NULL until `result`**.
--     b-roll mints a `videos` row at claim with status='ingesting', which
--     browse/tree/search exclude. `tracks` has no status column and never had
--     one: /api/facets, /api/stats and the tag/axis percentiles all read EVERY
--     row, and the debias axes are computed from the whole embedding matrix.
--     A placeholder row with no embedding would therefore skew the library's
--     own scoring rather than hide. So the row is written when there is
--     something real to write -- at `result`, with the embedding.
--   * NO `collection` column: b-roll's browse tree has collections, music has
--     one flat library and one share.
--   * NO `archive_dir`/`archive_stem`: the music library is FLAT under
--     `share_root()`, so the allocation is one filename (`dest_name`, chosen
--     with db.unique_dest's rules at `result` time), not a directory plus a
--     stem.
--   * `content_hash` instead of b-roll's `hash`: a different algorithm for a
--     different defence. b-roll's is xxh64 over the head and tail (a cheap
--     CANDIDATE match for multi-GB camera files); music's is the blake2b-16
--     over the WHOLE file that `db.content_hash` already computes and that
--     `ingest_queue.content_hash` already stores -- a music file is small
--     enough to hash whole, and byte-identity is a conclusion, not a hint.
--   * `transcoded`, `duration_s`, `samplerate`, `channels`: an .ogg becomes a
--     320k mp3 on the way in (the same rule routes_ingest applies), and the
--     probe fields a track row needs are these rather than fps/width/height.
--
-- `ingest_queue` (migrations 002/003) is untouched. It is the FALLBACK: an
-- editor whose companion is too old, or has no CLAP sidecar, still uploads to
-- the NAS and a base-rig drain analyses it. An item that takes that route ends
-- as `queued_for_base_rig` here and a `pending` row there.
--
-- `uid` rather than an autoincrement id, minted server-side as
-- lower(hex(randomblob(16))) -- the precedent migration 003 set for
-- ingest_queue.uid, and the shape the dashboard's login_gate carve-out regex
-- pins. These ids travel through a browser and a loopback POST, and a
-- guessable integer would let a logged-in editor drive another editor's batch.
CREATE TABLE IF NOT EXISTS ingest_batches (
    uid TEXT PRIMARY KEY,
    -- The VERIFIED dashboard identity that created it. The fleet routes prove
    -- a caller is "a fleet machine" (shared DASH_REPORT_TOKEN) and nothing
    -- about WHICH, so the editor name is re-derived from a signed
    -- X-CCSync-Identity on every fleet call and compared with this column
    -- (H5, COMMERCIAL_READINESS.md item 7).
    editor TEXT NOT NULL,
    -- Which of that editor's machines holds the lease. NULL until a claim.
    machine TEXT,
    companion_version TEXT,
    -- Always the music share ('music'); carried per batch anyway so a second
    -- library later is a config change and not a migration.
    share TEXT NOT NULL DEFAULT 'music',
    -- {run_mode}. JSON because the settings form grows per release and a
    -- column per knob would mean a migration per release; nothing SEARCHES
    -- on them.
    settings_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued'
      CHECK (state IN ('queued','claimed','running','done','done_with_errors','cancelled','failed')),
    n_items INTEGER NOT NULL DEFAULT 0,
    n_done INTEGER NOT NULL DEFAULT 0,
    n_failed INTEGER NOT NULL DEFAULT 0,
    n_live INTEGER NOT NULL DEFAULT 0,
    n_duplicate INTEGER NOT NULL DEFAULT 0,
    current_item_uid TEXT,
    -- The lease, exactly as the ytdl and b-roll fleet routes hold one: a claim
    -- is only good for lease_seconds and dies of silence, so a machine that is
    -- switched off mid-batch releases it without anyone pressing anything.
    lease_expires_at TEXT,
    last_heartbeat_at TEXT,
    -- Cancel is a REQUEST, not a kill: the companion learns about it on its
    -- next heartbeat (410) or in the report reply, and only then does it stop
    -- and release. A row flipped straight to 'cancelled' would leave a
    -- companion crunching a batch the server has forgotten.
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    cancel_by TEXT,
    upload_paused INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_batches_editor ON ingest_batches(editor, created_at);
CREATE INDEX IF NOT EXISTS idx_ingest_batches_state  ON ingest_batches(state);

CREATE TABLE IF NOT EXISTS ingest_items (
    uid TEXT PRIMARY KEY,
    batch_uid TEXT NOT NULL REFERENCES ingest_batches(uid) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    orig_name TEXT NOT NULL,
    size_bytes INTEGER,
    -- blake2b-16 of the WHOLE file, the digest db.content_hash computes and
    -- ingest_queue.content_hash stores. Computed on the editor's machine and
    -- re-checked against the library here; absent = no content dedupe for
    -- this item (the name+duration defence still runs).
    content_hash TEXT,
    duration_s REAL,
    samplerate INTEGER,
    channels INTEGER,
    codec TEXT,
    -- 1 once the companion has turned an .ogg into a 320k mp3, the same rule
    -- routes_ingest.py applies to a browser upload. It changes the name the
    -- file lands under, so the server has to know.
    transcoded INTEGER NOT NULL DEFAULT 0,
    -- 'upload' = the browser streamed the bytes to the companion (a drop;
    -- browsers expose no local paths); 'path' = the native picker gave a real
    -- path and the file is read where it lies.
    source TEXT NOT NULL DEFAULT 'upload' CHECK (source IN ('upload','path')),
    -- Written at `result`, not at claim -- see the header.
    track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    duplicate_of INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    -- The flat filename allocated under the share root (db.unique_dest's
    -- rules). NULL until `result` has chosen it.
    dest_name TEXT,
    state TEXT NOT NULL DEFAULT 'pending'
      CHECK (state IN ('pending','duplicate','transcoding','embedding','indexed',
                       'uploading','live','failed','cancelled','skipped',
                       'queued_for_base_rig')),
    stage_percent INTEGER,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_items_batch ON ingest_items(batch_uid, ord);
CREATE INDEX IF NOT EXISTS idx_ingest_items_track ON ingest_items(track_id);
-- precheck asks "has anyone already ingested these bytes" once per dropped
-- file, against items that have not landed yet as well as against tracks.
CREATE INDEX IF NOT EXISTS idx_ingest_items_hash ON ingest_items(content_hash);

PRAGMA user_version = 4;
