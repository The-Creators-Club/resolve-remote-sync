# Migrations

`schema.sql` is `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
throughout, and `musicweb.db.ensure_schema()` runs it against every database it
opens, so *additive* schema changes (a new table, a new index) still need no
migration — they land on an existing `music.db` the next time the app starts.
That is how `peaks` and `debias` were added to a live index.

Anything that is not expressible that way needs a file here, matching
`broll/web/migrations/`: `NNN_name.sql`, applied in order, each in its own
transaction, tracked with `PRAGMA user_version`, and registered in
`musicweb.db._MIGRATIONS` alongside a bump of `CURRENT_SCHEMA_VERSION`.

| # | File | What |
|---|---|---|
| 001 | `001_track_share.sql` | `tracks.share` (constant `'music'`) — the b-roll `(share, rel_path)` rule |
| 002 | `002_ingest_queue.sql` | the drag-and-drop ingest queue (port step 7) |
| 003 | `003_ingest_journal.sql` | `ingest_queue.uid` — a per-upload identity that survives the database being copied, so a drain can close exactly the rows it analysed instead of pushing the whole file back over uploads queued in the meantime (`musicweb/drain.py`) |

Two things differ from b-roll's runner, both because this database predates
`user_version`:

- A v0 database here is not necessarily empty. `ensure_schema()` decides
  "fresh" by whether the `tracks` table exists, not by `user_version == 0`;
  the real 376-row library was at `user_version = 0` when 001 was written.
- **Each entry in `_MIGRATIONS` carries an already-applied predicate, and that
  — not the recorded version — decides whether the file runs.** A new
  migration must supply one. It is what keeps `ALTER TABLE ... ADD COLUMN` to
  "only if the column is absent", and it is what repairs a database whose
  version says more than its schema does.

That last point is not theoretical. `schema.sql` used to end with
`PRAGMA user_version = 1`, and because it is re-applied to *existing*
databases, one stray run took the live 376-track index to `user_version = 1`
without adding `tracks.share` — after which a version-driven runner would have
skipped migration 001 forever. `schema.sql` no longer stamps anything;
`ensure_schema()` owns the version.
