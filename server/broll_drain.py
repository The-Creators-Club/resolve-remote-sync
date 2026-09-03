#!/usr/bin/env python3
"""The b-roll publish drain: what lives ONLY in the NAS's broll.db.

BROLL-1, 2026-09-04 (docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md).

`publish_db.py --which broll` replaces the live `broll.db` with the base rig's
copy by renaming a file over it. That is the right way to swap a WAL-mode
database the container holds open -- and until this module existed it was also
a way to delete work nobody could get back, because the dashboard's own b-roll
app WRITES that live file:

  * drag-and-drop ingest mints a `videos` row per clip at claim time, and the
    companion POSTs its segments, embeddings and `live` flip straight into it;
  * `ingest_batches` / `ingest_items` -- every batch's state, lease and
    per-clip progress -- are TABLES INSIDE THAT FILE and exist nowhere else
    (`broll/web/migrations/011_ingest_batches.sql`: "this database is the only
    place the truth about a batch lives");
  * `share_roots` gains a row, with `collection` set, for each ingested shoot.

None of it is in the base rig's copy, so the swap dropped the lot. The shrink
check could not see it: 200 ingested clips against a 15,000-clip archive is a
1.3% difference and the threshold is 10%.

The music index solved the same problem the other way round (`musicweb.drain`,
COMMERCIAL_READINESS item 14): the base rig exports ANALYSED RESULTS and the
NAS merges them, so a file is never pushed over the live index at all. b-roll
cannot copy that shape -- its index really is rebuilt on the base rig and
really is published as a file -- so the drain runs in the other direction:

    take the drain   the NAS-only rows are copied out of the LIVE file into a
                     bundle beside it, BEFORE anything is renamed
    swap             exactly as before
    apply the drain  the bundle is merged into the newly live file, in one
                     transaction, inserting only what that file lacks

The set of rows a drain can affect is fixed at the moment it is taken, and it
is a set of ids, not "the file". Every write in `apply` is keyed and
idempotent, so a bundle can be applied twice, or applied by hand later if the
ssh call that should have applied it died -- which is why the bundle is never
deleted.

Both halves run as a plain `python3 -c` inside the dashboard container: it is
the one interpreter guaranteed to exist on TrueNAS and on DSM alike, and it is
the process that already has the live file open, so its opinion is the one that
counts. They take their paths from argv rather than by interpolation, so a path
with a quote in it is carried rather than refused.
"""

# Exit codes both programs use. Anything else is an unhandled crash and is
# reported with whatever the interpreter said.
RC_NO_LIVE = 3          # export: there is no live database yet (a first publish)
RC_NO_BUNDLE = 4        # apply: the bundle is not where we were told it is
RC_FAILED = 5           # apply: the merge raised, and was rolled back

BUNDLE_VERSION = 1

# Children of a `videos` row. The FTS mirrors are content-backed with AFTER
# INSERT triggers, so they repopulate themselves and must NOT be copied by
# hand; `embeddings` is handled separately because its `source_id` points at a
# `segments` / `transcript_segments` row whose id the merge re-mints.
CHILD_TABLES = ("segments", "transcript_segments", "themes", "quality_flags")


EXPORT_PROGRAM = r'''
import json, os, sqlite3, sys

LIVE, OUT = sys.argv[1], sys.argv[2]
RC_NO_LIVE = 3
CHILD_TABLES = ("segments", "transcript_segments", "themes", "quality_flags")

if not os.path.exists(LIVE):
    print(json.dumps({"live": False}))
    sys.exit(RC_NO_LIVE)

src = sqlite3.connect("file:" + LIVE.replace("?", "%3f").replace("#", "%23")
                      + "?mode=ro", uri=True)
have = set(r[0] for r in src.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"))


def copy(out, table, where=""):
    """Create `table` in the bundle from the LIVE schema, and copy rows in.

    The source's own CREATE TABLE text is reused so a bundle can never disagree
    with the database it came from about a column. Indexes and triggers are
    deliberately left behind: a bundle is written once and read once.
    """
    if table not in have:
        return 0
    sql = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    if not sql or not sql[0]:
        return 0
    out.execute(sql[0])
    names = [r[1] for r in src.execute('PRAGMA table_info("%s")' % table)]
    quoted = ",".join('"%s"' % c for c in names)
    rows = src.execute("SELECT %s FROM %s %s" % (quoted, table, where)).fetchall()
    if rows:
        out.executemany("INSERT INTO %s (%s) VALUES (%s)"
                        % (table, quoted, ",".join("?" * len(names))), rows)
    return len(rows)


if "ingest_batches" not in have or "ingest_items" not in have:
    # A live index older than migration 011. Nothing in it can exist only on
    # the NAS, so there is nothing to drain, and that is an answer rather than
    # a failure.
    print(json.dumps({"live": True, "ingest_schema": False, "videos": 0,
                      "batches": 0, "items": 0, "open_batches": 0}))
    sys.exit(0)

# WHICH video rows exist only here. Two sources, because either alone has a
# hole: `ingest_items.video_id` is ON DELETE SET NULL so a row can lose its
# pointer, and a batch's share names every clip that batch archived even after
# that has happened.
ids = set()
for (vid,) in src.execute(
        "SELECT video_id FROM ingest_items WHERE video_id IS NOT NULL"):
    ids.add(vid)
for (vid,) in src.execute(
        "SELECT id FROM videos WHERE share IN (SELECT share FROM ingest_batches)"):
    ids.add(vid)

src.execute("CREATE TEMP TABLE drain_ids (id INTEGER PRIMARY KEY)")
src.executemany("INSERT OR IGNORE INTO temp.drain_ids VALUES (?)",
                [(i,) for i in sorted(ids)])

if os.path.exists(OUT):
    os.remove(OUT)
out = sqlite3.connect(OUT)
out.execute("CREATE TABLE drain_meta (key TEXT PRIMARY KEY, value TEXT)")
# Every video id in the LIVE file with its (share, rel_path) key, not just the
# drained ones: `videos.duplicate_of` and `ingest_items.duplicate_of` point at
# rows that may well be ordinary indexer rows, and an id means nothing in the
# other copy. This table is how the merge resolves them.
out.execute("CREATE TABLE video_keys (id INTEGER PRIMARY KEY, share TEXT, "
            "rel_path TEXT)")
out.executemany("INSERT INTO video_keys VALUES (?,?,?)",
                src.execute("SELECT id, share, rel_path FROM videos").fetchall())

n = {}
n["videos"] = copy(out, "videos", "WHERE id IN (SELECT id FROM temp.drain_ids)")
for t in CHILD_TABLES:
    n[t] = copy(out, t, "WHERE video_id IN (SELECT id FROM temp.drain_ids)")
n["embeddings"] = copy(out, "embeddings",
                       "WHERE video_id IN (SELECT id FROM temp.drain_ids)")
n["share_roots"] = copy(
    out, "share_roots",
    "WHERE share IN (SELECT share FROM ingest_batches) OR collection IS NOT NULL")
n["ingest_batches"] = copy(out, "ingest_batches")
n["ingest_items"] = copy(out, "ingest_items")

open_batches = src.execute(
    "SELECT count(*) FROM ingest_batches WHERE state NOT IN "
    "('done','done_with_errors','cancelled','failed')").fetchone()[0]

out.executemany("INSERT INTO drain_meta VALUES (?,?)", [
    ("bundle_version", "1"),
    ("source", LIVE),
    ("counts", json.dumps(n)),
    ("open_batches", str(open_batches)),
])
out.commit()
out.close()
src.close()

summary = {"live": True, "ingest_schema": True, "bundle": OUT,
           "bytes": os.path.getsize(OUT), "open_batches": open_batches,
           "batches": n["ingest_batches"], "items": n["ingest_items"]}
summary.update(n)
print(json.dumps(summary))
'''


APPLY_PROGRAM = r'''
import json, os, sqlite3, sys

LIVE, BUNDLE = sys.argv[1], sys.argv[2]
RC_NO_BUNDLE, RC_FAILED = 4, 5
CHILD_TABLES = ("segments", "transcript_segments", "themes", "quality_flags")

if not os.path.exists(BUNDLE):
    print(json.dumps({"error": "no bundle at " + BUNDLE}))
    sys.exit(RC_NO_BUNDLE)

b = sqlite3.connect("file:" + BUNDLE.replace("?", "%3f").replace("#", "%23")
                    + "?mode=ro", uri=True)
con = sqlite3.connect(LIVE, timeout=60)
# The merge re-mints ids in an order the foreign keys would not like halfway
# through (a child before its parent's duplicate_of target has been re-pointed).
# They are inert on a connection that does not ask for them; the merge is
# correct at COMMIT, in one transaction, and every later write still meets the
# schema's constraints.
con.execute("PRAGMA foreign_keys=OFF")

bt = set(r[0] for r in b.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"))
lt = set(r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"))


def shared(table):
    """Columns the bundle and the live file agree on.

    A bundle can outlive a migration: the newly published index may have a
    column the drained one did not, or the other way round. Copying the
    intersection keeps the merge working across one, and anything left out
    keeps the default a fresh row would have had.
    """
    live_cols = set(r[1] for r in con.execute('PRAGMA table_info("%s")' % table))
    return [r[1] for r in b.execute('PRAGMA table_info("%s")' % table)
            if r[1] in live_cols]


report = {"videos_inserted": 0, "videos_already_there": 0, "children": 0,
          "embeddings": 0, "share_roots": 0, "batches": 0, "items": 0}

try:
    con.execute("BEGIN IMMEDIATE")

    # bundle video id -> live video id, for EVERY id the bundle knows about,
    # so a duplicate_of pointing at a clip the drain did not carry still lands
    # on the right row.
    vmap, fresh = {}, set()
    if "video_keys" in bt:
        for vid, share, rel in b.execute(
                "SELECT id, share, rel_path FROM video_keys"):
            row = con.execute(
                "SELECT id FROM videos WHERE share=? AND rel_path=?",
                (share, rel)).fetchone()
            if row:
                vmap[vid] = row[0]

    # Videos. Only rows the newly published index LACKS are inserted, and never
    # with their old id: an id is a per-database rowid and the published copy
    # has almost certainly minted its own rows on it. A clip that is in both is
    # left exactly as the publish left it -- the base rig's pass is the one
    # that just ran.
    if "videos" in bt and "videos" in lt:
        names = [c for c in shared("videos") if c != "id"]
        quoted = ",".join('"%s"' % c for c in names)
        placeholders = ",".join("?" * len(names))
        for row in b.execute("SELECT id,%s FROM videos" % quoted):
            old, values = row[0], list(row[1:])
            if old in vmap:
                report["videos_already_there"] += 1
                continue
            cur = con.execute("INSERT INTO videos (%s) VALUES (%s)"
                              % (quoted, placeholders), values)
            vmap[old] = cur.lastrowid
            fresh.add(cur.lastrowid)
            report["videos_inserted"] += 1
        # duplicate_of points at another videos row; re-point it now that every
        # id is known. An unresolvable target becomes NULL, which the schema
        # already means as "this row is canonical, as far as anyone knows".
        if "duplicate_of" in names:
            for old, dup in b.execute("SELECT id, duplicate_of FROM videos "
                                      "WHERE duplicate_of IS NOT NULL"):
                if vmap.get(old) in fresh:
                    con.execute("UPDATE videos SET duplicate_of=? WHERE id=?",
                                (vmap.get(dup), vmap[old]))

    # Children go with a video that was INSERTED, never with one that was
    # already there: that clip's segments came with the published index, and
    # adding the drained copies would double every search hit for it.
    smap = {}
    for table in CHILD_TABLES:
        if table not in bt or table not in lt:
            continue
        names = [c for c in shared(table) if c != "id"]
        if "video_id" not in names:
            continue
        quoted = ",".join('"%s"' % c for c in names)
        placeholders = ",".join("?" * len(names))
        has_id = any(r[1] == "id" for r in
                     b.execute('PRAGMA table_info("%s")' % table))
        select = "SELECT %s,%s FROM %s" % ("id" if has_id else "NULL",
                                           quoted, table)
        i_vid = names.index("video_id")
        for row in b.execute(select):
            old_child, values = row[0], list(row[1:])
            live_video = vmap.get(values[i_vid])
            if live_video is None or live_video not in fresh:
                continue
            values[i_vid] = live_video
            cur = con.execute("INSERT INTO %s (%s) VALUES (%s)"
                              % (table, quoted, placeholders), values)
            if old_child is not None:
                smap[(table, old_child)] = cur.lastrowid
            report["children"] += 1

    if "embeddings" in bt and "embeddings" in lt:
        names = shared("embeddings")
        quoted = ",".join('"%s"' % c for c in names)
        placeholders = ",".join("?" * len(names))
        i_src, i_sid = names.index("source"), names.index("source_id")
        i_vid = names.index("video_id")
        for row in b.execute("SELECT %s FROM embeddings" % quoted):
            values = list(row)
            live_video = vmap.get(values[i_vid])
            if live_video is None or live_video not in fresh:
                continue
            table = ("segments" if values[i_src] == "segment"
                     else "transcript_segments")
            new_child = smap.get((table, values[i_sid]))
            if new_child is None:
                # The vector's own row did not come across. A vector pointing
                # at somebody else's segment id is a wrong search hit, so it is
                # dropped rather than guessed at.
                continue
            values[i_vid], values[i_sid] = live_video, new_child
            con.execute("INSERT OR REPLACE INTO embeddings (%s) VALUES (%s)"
                        % (quoted, placeholders), values)
            report["embeddings"] += 1

    # A share the published index has never heard of has no root, and without
    # one its clips cannot be resolved back to an original. OR IGNORE: a row
    # the new index brought is the newer of the two.
    if "share_roots" in bt and "share_roots" in lt:
        names = shared("share_roots")
        quoted = ",".join('"%s"' % c for c in names)
        for row in b.execute("SELECT %s FROM share_roots" % quoted):
            cur = con.execute(
                "INSERT OR IGNORE INTO share_roots (%s) VALUES (%s)"
                % (quoted, ",".join("?" * len(names))), list(row))
            report["share_roots"] += cur.rowcount

    # The two ingest tables are REPLACED, not ignored: they were read out of
    # the live file minutes ago, and anything the published copy carries under
    # the same uid is a stale snapshot the base rig once pulled. Their video
    # pointers are re-mapped, and an unresolvable one becomes NULL exactly as
    # the schema's ON DELETE SET NULL would have left it.
    for table, refs in (("ingest_batches", ()),
                        ("ingest_items", ("video_id", "duplicate_of"))):
        if table not in bt or table not in lt:
            continue
        names = shared(table)
        quoted = ",".join('"%s"' % c for c in names)
        placeholders = ",".join("?" * len(names))
        idx = [names.index(c) for c in refs if c in names]
        for row in b.execute("SELECT %s FROM %s" % (quoted, table)):
            values = list(row)
            for i in idx:
                if values[i] is not None:
                    values[i] = vmap.get(values[i])
            con.execute("INSERT OR REPLACE INTO %s (%s) VALUES (%s)"
                        % (table, quoted, placeholders), values)
            report["batches" if table == "ingest_batches" else "items"] += 1

    # Every write path that touches embeddings, or the rows the typo-correction
    # vocabulary is built from, bumps this in the same transaction as the write
    # (schema.sql, `meta`). A merge that inserted clips is one of them.
    if report["videos_inserted"] and "meta" in lt:
        con.execute(
            "INSERT INTO meta (key, value) VALUES ('search_generation','1') "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)")

    con.commit()
except Exception as exc:
    con.rollback()
    print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}))
    sys.exit(RC_FAILED)

print(json.dumps(report))
'''
