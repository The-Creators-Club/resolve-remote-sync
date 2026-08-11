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
