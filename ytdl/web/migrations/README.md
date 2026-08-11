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

There are no migrations yet — this database was created at v1. The runner is
here so the first one is a two-line change instead of a design decision made
under pressure.
