# Migrations

`schema.sql` is `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
throughout, and `ytdlweb.db.ensure_schema()` runs it against every database it
opens, so *additive* schema changes (a new table, a new index) need no
migration — they land on an existing `ytdl.db` the next time the app starts.

Anything that is not expressible that way needs a file here, matching
`music/web/migrations/` and `broll/web/migrations/`: `NNN_name.sql`, applied in
order, each in its own transaction, tracked with `PRAGMA user_version`, and
registered in `ytdlweb.db._MIGRATIONS` alongside a bump of
`CURRENT_SCHEMA_VERSION`.

**Every entry in `_MIGRATIONS` carries an already-applied predicate, and that —
not the recorded version — decides whether the file runs.** A new migration must
supply one. It is what keeps `ALTER TABLE ... ADD COLUMN` to "only if the column
is absent", and it is what repairs a database whose version says more than its
schema does. music/web learned that the expensive way: a `PRAGMA user_version`
stamp inside `schema.sql` marked a live index as migrated without adding the
column, and a version-driven runner would then have skipped the migration
forever. `schema.sql` here stamps nothing; `ensure_schema()` owns the version.

This database was created at v1. Since then (2026-08-11 bug hunt):

- `002_downloads_term_dir.sql` — v2, the ledger's real on-disk folder (YTDL-31).
- `003_one_active_job_per_editor.sql` — v3, the partial unique index behind
  create_job's 409 (YTDL-25). It retires pre-existing duplicate active jobs
  BEFORE creating the index, because a `CREATE UNIQUE INDEX` that raises on a
  live database would take every `/ytdl` request down with it.
- `004_jobs_kind.sql` — v4, `jobs.kind` ('search' | 'urls'), so a pasted-links
  job can enter the same phase machine at the download phase instead of being
  handed to Claude as a search topic. Every pre-existing row is a search, which
  is the column's default, so there is no backfill.
- `005_jobs_shot_types.sql` — v5, `jobs.shot_types`, the checkboxes the editor
  ticked (the {bias} block of both Claude prompts is composed from them). The
  default is the six footage types, which is what the fixed "prioritise
  visuals" bias did before the boxes existed — so every pre-existing row reads
  as the search it actually ran, and again there is no backfill. `''` means the
  editor ticked nothing (an unbiased search) and is deliberately not the same
  value as an absent one.
- `006_jobs_max_candidates.sql` — v6, `jobs.max_candidates`, the ceiling on how
  many candidate videos one search may accumulate and therefore on how many
  metadata calls it makes at YouTube. Unlike 005, the default is **not** what
  the old rows ran with: they ran unbounded, and unbounded is what reached 336
  candidates and got the NAS's IP bot-checked at 112 metadata calls
  (2026-08-11). There is deliberately no value meaning "no limit" — the only
  rows the backfill can still affect are ones boot recovery re-runs.
- `007_local_download.sql` — v7 (2026-08-14), the requester-first download
  columns: `jobs.download_mode` / `claimed_by` / `lease_expires_at` /
  `mode_lock`, and `job_videos.download_host`
  (`docs/YTDL_LOCAL_DOWNLOAD.md` §4). Purely additive and inert without a 0.8.0
  companion — every existing job reads as `download_mode='server'`, which is
  what they all ran as, so there is no backfill and no schema rollback to plan
  for. It is the first migration to touch **two** tables, so its predicate asks
  about both: a predicate that only checked `jobs` would call a database with
  no `job_videos.download_host` migrated and every clip status post would then
  die on "no such column".
- `008_attestations.sql` — v8 (2026-08-17), the rights/ToS attestation table
  (`attestation.py`, `docs/COMMERCIAL_READINESS.md` item 2). A whole new table,
  so the predicate is simply "is it there"; a database where it is missing or
  unreadable answers "nobody has accepted", which refuses downloads rather than
  allowing them.
- `009_jobs_mode.sql` — v9 (2026-08-18), `jobs.mode`: the SEARCH MODE, `visuals`
  (b-roll to cut under something else) or `news` (a montage made of the
  reporting, where the clip's own audio is what gets used). It picks the framing
  of both AI calls. Like 005 and unlike 006, the default IS what the old rows
  ran: `visuals` composes the previous prompts byte for byte
  (`tests/golden/`), so there is no backfill and no row's history is rewritten.
  It is not `download_mode` (007), which is about which machine fetches the
  clips.
- `010_jobs_claimed_machine.sql` — v10 (2026-08-21), `jobs.claimed_machine`:
  WHICH of the leaseholder's computers holds the download lease (data-model-7,
  KNOWN_BUGS CR-66/CR-67). The lease was keyed on the editor NAME, and a name is
  a person — so one editor's laptop and desktop both passed the
  compare-and-set as "the same holder refreshing" and downloaded the same clips
  into two trees. Additive and inert like 007: NULL is "the holder did not say",
  which is every pre-existing row and every claim from a companion that predates
  the field, and `db.claim_download` reads an unknown holding machine exactly as
  it read every holder before this. There is deliberately no backfill — a
  machine_id cannot be invented for a lease already taken.
