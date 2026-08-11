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
