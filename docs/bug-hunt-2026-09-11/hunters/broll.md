# broll - the b-roll platform (broll/web + broll/indexer)

Files read (with approximate coverage):
- `broll/web/app/`: `routes_share.py` (100%), `client_folders.py` (100%),
  `routes_client_folders.py` (100%), `main.py` (100%), `media.py` (100%),
  `routes_media.py` (100%), `fleet_auth.py` (100%), `routes_fleet.py` (~60%,
  all of the 097f5a3..HEAD diff), `routes_batches.py` (~70%),
  `ingest_batches.py` (~40%: the whole diff plus claim / expire_stale_leases /
  create_batch / precheck), `routes_ingest.py` (~40%), `semantic.py` and
  `search.py` (the diff plus the availability/count paths).
- `broll/web/static/`: `ingest.js` (the retry/take-over/state-words half),
  grep sweep of `app.js`, `clientfolders.js`, `share.js`, `sprite.js`,
  `index.html` for root-relative URLs, absolute origins and innerHTML.
- `broll/web/migrations/011_ingest_batches.sql` (items/batches tables).
- `broll/indexer/broll_index/local_vlm.py` (the whole diff), `claude_client.py`
  (retry/backoff/cost skim).
- Cross-checked the other side of two wires: `companion/.../broll_ingest.py`
  (`FleetClient`, `Ingestor.retry`), `companion/.../broll_server.py` (the
  `/broll/ingest/*` handler), `dashboard/.../app.py` (`_broll_fleet_re`,
  `_broll_fleet_list_re`), `dashboard/.../broll.py` (`_init_broll_storage`).

Tests run (venv `E:\Projects\broll-platform\web\.venv`):
- `pytest tests/test_client_folders.py tests/test_ingest_retry_and_takeover.py tests/test_mounted_prefix.py tests/test_batch_state_words.py tests/test_no_em_dashes.py -q` -> **124 passed**
- `pytest tests/test_no_em_dashes.py tests/test_one_vocabulary.py tests/test_search_says_what_it_did.py tests/test_send_busy_is_a_queue.py tests/test_fleet_ingest.py tests/test_ingest_batches.py -q` -> **147 passed**
- Two ad-hoc snippets from that venv (scratchpad) proving finding broll-2.

## Findings

### broll-1 - "try the N failed again" sends the server's item uids to a companion that only understands the browser's local ids, so nothing is ever re-queued
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/static/ingest.js:1710` (and the payload it comes from,
  `broll/web/app/ingest_batches.py:585-590` `retry_failed` -> `{"items": item_uids}`);
  other side `companion/src/ccsync_companion/broll_ingest.py:1522-1546`
  (`Ingestor.retry`, `wanted` is matched against staging **local_id**s).
- What: `retry_failed()` returns `items` = `ingest_items.uid`, a 32-hex uid
  minted server-side by `new_uid(conn)` (schema `011_ingest_batches.sql:68`;
  there is no `local_id` column in `ingest_items` at all - `local_id` is only
  echoed back by `precheck` and is never persisted). The page hands that list
  straight to `POST /broll/ingest/retry`, whose `items` field is documented and
  implemented as "a list of local ids from THIS drop": the companion filters
  `if wanted and str(local_id) not in wanted: continue`, so **no staged entry
  ever matches** and it answers `200 {"ok": true, "retried": 0}`.
- Failure scenario: a 200-clip drop finishes `done_with_errors - 12 failed`.
  The editor clicks "try the 12 failed again". The server correctly moves the
  12 items back to `pending` and the batch to `queued`; the loopback call
  returns 200/retried:0, so the JS never takes its `e.status === 404` fallback
  to `/broll/ingest/run`, the staged entries stay `failed` in the companion's
  own ledger, and no claim is ever made. The editor is shown the success toast
  "12 clips queued again", the panel starts polling, and the batch sits in
  `queued` for ever. Note the perverse ordering: a companion **older** than
  0.9.67 404s the route and therefore works (the run fallback fires), while
  0.9.67+ silently does nothing - so this gets worse as the fleet upgrades.
- Evidence: `grep -n local_id broll/web/app/ingest_batches.py` -> only line 489
  (the precheck echo); `ingest_items` schema has `uid TEXT PRIMARY KEY` filled
  by `new_uid(conn)` in `create_batch`. Companion side read in full at
  `broll_ingest.py:1528-1546`. The test that is supposed to pin this,
  `tests/test_ingest_retry_and_takeover.py:257-269`, only asserts the string
  `"/broll/ingest/retry"` appears in the function - it never looks at what is
  in the body, which is exactly the thing that is wrong.
- Ledger: new (BROLL-18 / BROLL-5, 2026-09-04, recorded as fixed; this is the
  seam between the two halves of that fix).
- Suggested fix: either have `retry_failed()` also return the items'
  `orig_name`/`rel_dir` so the page can map them onto its staging rows, or make
  the loopback call `{"items": []}` (which the companion reads as "every failed
  one in every drop") plus an explicit `staging_id`; and add an assertion to
  `test_the_batch_card_offers_the_failed_ones_again` on the body that is sent.

### broll-2 - the client_shares.db v1 -> v2 migration cannot run twice: one interrupted or concurrent run leaves every /broll request 500ing for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `broll/web/app/client_folders.py:150-170` (`ensure_schema`), reached
  per request from `get_shares_db` (`client_folders.py:213`) and at boot from
  `dashboard/src/ccsync_dashboard/broll.py:552` (`_init_broll_storage`).
- What: the v1 -> v2 step is
  `ALTER TABLE ... ADD COLUMN hash` -> `_backfill_hashes()` -> `PRAGMA
  user_version = 2` -> `commit()`. In CPython's sqlite3 the ALTER is DDL and
  **commits immediately** (no implicit BEGIN), while `user_version` is only
  written after the backfill. So there is a window - the whole backfill, which
  is one UPDATE per hashed row in `videos` - in which the file has the column
  but still reports `user_version = 1`. Any second entry into `ensure_schema`
  in or after that window re-runs the ALTER and raises
  `sqlite3.OperationalError: duplicate column name: hash`, which is not caught
  anywhere: it escapes `get_shares_db` and (at boot) `_init_broll_storage`.
- Failure scenario: the dashboard container is upgraded past 2026-09-03 and
  restarted. Two requests land at once (FastAPI runs these sync dependencies in
  a threadpool, so workers=1 does not serialise them) - or the container is
  restarted/OOM-killed during the backfill. From then on **every** client-folder
  route AND every public `/broll/share/<token>/...` link answers 500, and at the
  next boot the mount comes up DEGRADED. Nothing self-heals; the only cure is
  hand-editing `PRAGMA user_version` on the NAS. This is precisely the
  "a migration that cannot run twice" hazard the brief names, on the one
  database CLAUDE.md says must never be at risk from anything.
- Evidence: measured from the b-roll venv (py 3.12.10):
  `c.execute("ALTER TABLE a ADD COLUMN h ...")` -> `c.in_transaction is False`
  and a second connection immediately sees the column. Then, driving the real
  module against a hand-built v1 ledger with the ALTER already applied:
  `ensure_schema RAISED: OperationalError duplicate column name: hash`.
- Ledger: new (the v2 migration landed with broll-1 of the 2026-09-03 fix pass).
- Suggested fix: make the step idempotent - test for the column
  (`PRAGMA table_info(client_folder_items)`) rather than for `user_version`
  alone, or catch `OperationalError` whose message is "duplicate column name",
  and take an `IMMEDIATE` lock around the whole migration so two threads cannot
  both enter it. A `try/except` around `ensure_schema()` in `get_shares_db`
  would additionally stop one bad ledger from taking the public share links out.

### broll-3 - BROLL-8's discovery route has no caller: no companion ever asks for its unfinished batches
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_fleet.py:120-157` (`GET /api/fleet/ingest/batches`);
  companion side `companion/src/ccsync_companion/broll_ingest.py:341-420`
  (`FleetClient` - every call is a POST to `/batches/{uid}/...`).
- What: the route, the dashboard gate carve-out (`_broll_fleet_list_re`) and the
  tests all landed, but nothing on the companion side issues the GET. The stated
  purpose - "a batch whose machine was wiped or reinstalled could be picked up by
  NOTHING ... it sat in `queued` for ever holding name reservations and
  permanently-`ingesting` rows" - is therefore still true for exactly the case
  that motivated it (the machine is gone, so its editor cannot press the page's
  "take over on this computer" button on it either, unless they happen to open
  the panel on another of their machines).
- Failure scenario: EDIT-03 is reinstalled mid-batch. The batch's lease expires,
  it returns to `queued` with `machine = 'EDIT-03'`, and its claimed items keep
  `videos.status = 'ingesting'` rows and allocated archive names. The rebuilt
  EDIT-03's companion starts, asks nobody anything, and the batch stays there.
- Evidence: `grep -rn "fleet/ingest" companion/src/` finds only
  `ingest_kinds.py:198` (the prefix constant); `grep -n '_url(' broll_ingest.py`
  shows claim/heartbeat/release/items only. No GET is issued by `FleetClient`.
- Ledger: new (BROLL-8, 2026-09-04, recorded as fixed).
- Suggested fix: have the companion's ingest worker call
  `GET <api_prefix>/batches` on startup and on an idle tick, and offer/claim any
  non-terminal batch whose `machine` matches this machine - or say plainly in
  the ledger that the server half shipped ahead of the client half.

### broll-4 - routes_fleet's own docstring says the discovery route is unreachable behind the dashboard; it is not, and a reader will act on the wrong fact
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_fleet.py:141-150` vs
  `dashboard/src/ccsync_dashboard/app.py:1067` + `:1168-1170`.
- What: the docstring's "NOTE for the deployed mount" says the login gate's
  carve-out "only covers `.../batches/<32 hex>/...` today, so this route needs
  that regex widened before a companion behind the dashboard can reach it".
  The widening landed in the same commit (`_broll_fleet_list_re`, GET-only).
  Anyone implementing the missing companion caller (broll-3) will read this and
  conclude the route is dead, or will "fix" a gate that is already correct.
- Failure scenario: no runtime effect; a wrong-fact comment on a security gate.
- Evidence: read both files.
- Ledger: new.
- Suggested fix: replace the NOTE with "the gate's `_broll_fleet_list_re`
  carve-out covers this, GET only".

### broll-5 - POST /api/ingest-batches/{uid}/retry-failed accepts a RUNNING batch and silently takes its lease away
- Severity: low
- Confidence: PLAUSIBLE
- Where: `broll/web/app/routes_batches.py:197-210`,
  `broll/web/app/ingest_batches.py:559-575`.
- What: `retry_failed` refuses nothing by state. If the batch is `claimed` or
  `running` with one already-failed item, the route sets `state = 'queued'`,
  `lease_expires_at = NULL`, `current_item_uid = NULL` and
  `cancel_requested = 0` underneath the machine that is still working, so
  another machine can win a claim beside it. The SPA only shows the button for
  `done`/`done_with_errors`/`failed`, so this needs a hand-made request or a
  stale page - but the route is the contract, not the button, and the module's
  own rule elsewhere is that possession is settled server-side.
- Failure scenario: an editor with two machines double-clicks a retry on a page
  that has not refreshed since the batch went `running`; both machines index the
  same clips until the first one's next per-item POST is 410'd by
  `_leaseholder_or_410`.
- Evidence: read `retry_failed`, `claim` (`ingest_batches.py:687-712`) and
  `expire_stale_leases`; the claim's 409 tests `lease_expires_at`, which this
  has just nulled.
- Ledger: new.
- Suggested fix: refuse a non-terminal batch here with the same 409/410 wording
  the fleet routes use, or require `cancel` first.

### broll-6 - the v1 -> v2 backfill is an unindexed UPDATE per archive row, run inside a request (or the dashboard's boot)
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/client_folders.py:173-200` (`_backfill_hashes`).
- What: it reads every `videos` row with a non-blank hash (tens of thousands on
  a real archive) and issues one `UPDATE client_folder_items SET hash = ? WHERE
  hash = '' AND share = ? AND rel_path = ?` per row. `client_folder_items` has
  only `idx_client_folder_items_folder(folder_id, ord)`, so every one of those
  is a full table scan, and the whole thing runs holding a write transaction on
  the ledger inside whichever request first touched it (or the dashboard's
  boot, which is single-threaded).
- Failure scenario: first `/broll/client-folders` request after the upgrade
  blocks for seconds to tens of seconds while the ledger is write-locked; it
  also widens the broll-2 window proportionally.
- Evidence: schema read (`_SCHEMA` in `client_folders.py`), loop read.
- Ledger: new.
- Suggested fix: invert it - iterate the (few hundred) `client_folder_items`
  rows and look each up in `videos` by the indexed `(share, rel_path)`.

## Coverage note
Not reached: the bulk of `search.py` (the 1,350 lines that predate 097f5a3 -
ranking, RRF, the sanitizer), `fuzzy.py`, `normalize.py`, `archive_names.py`,
most of `ingest_batches.py`'s per-item status machine, `routes_ingest.py`'s
`/moved` and `/share-root` handlers, and everything in `broll/indexer/` except
`local_vlm.py`'s diff and a skim of `claude_client.py` (its retry loop has a
ceiling and honours `retry-after`; no key is formatted into a log line I saw).
I did not exercise `publish_db.py` interplay against a live WAL reader.

Checked and found CLEAN: the public share door (`_live_folder` on every route,
`_member_id`'s two-identity re-check, `PUBLIC_VIDEO_COLUMNS`, the `no-cache` +
ETag media headers, `ShareAssets`' allow-list, the same-404-for-everything
rule); `_proxy_path`'s `is_relative_to` containment; `media.py`'s Range parser
on zero-length, suffix, inverted and oversized ranges; `fleet_auth`'s
fail-closed stamp/identity/binding chain; `semantic.mode_availability`'s
never-raise contract (`embeddings(model)` is indexed, so the per-search COUNT
is cheap); `count_in_scope`'s clause/param ordering; XSS in the share viewer
(every `innerHTML` is a clear or an `escapeHtml`); em dashes (the two scan
tests pass).

What the suite does not cover: the retry/take-over tests assert on **substrings
of ingest.js**, not on the payloads that cross the loopback (broll-1 lives in
exactly that gap); nothing anywhere exercises `client_folders.ensure_schema`
against a v1 file that already has the `hash` column, or two threads entering it
at once (broll-2); and `test_mounted_prefix.py`'s root-relative-URL scan covers
`app.js`, `index.html`, `ingest.js` and the `/share/assets` sources but not
`clientfolders.js`, and its regex only knows `/api|/media|/static` (a
root-relative `/share/...` or a leading slash inside a `${}` template would
pass). I checked `clientfolders.js` by hand: it is clean.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_ingest.py:1510` (`Ingestor.retry`): the
  companion half of broll-1 - the body it accepts and the body the page sends
  disagree; whichever side is changed, both need the change together.
- `companion/src/ccsync_companion/broll_ingest.py` (`FleetClient`): the missing
  GET for broll-3.
