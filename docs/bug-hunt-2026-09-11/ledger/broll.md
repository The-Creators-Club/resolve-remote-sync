## B-roll platform, 2026-09-11 (CR-245)

### CR-245 - the client-folder ledger's migration could only ever be run once, "try the N failed again" told the companion nothing it understood, and a retry could take a running batch away from the machine holding it - FIXED 2026-09-11 (`broll/web`)

**broll-2 (high) - one interrupted migration and every public share link
500s for ever.** `client_folders.ensure_schema`'s v1 -> v2 step was
`ALTER TABLE client_folder_items ADD COLUMN hash` -> `_backfill_hashes()` ->
`PRAGMA user_version = 2` -> `commit()`. CPython's sqlite3 runs DDL in
autocommit, so the ALTER was durable the instant it executed while the
version was only written after the backfill: a container restarted, killed
or OOM-ed inside the backfill left a file that HAS the column and still
reports version 1, and every later entry re-ran the ALTER and raised
`sqlite3.OperationalError: duplicate column name: hash`. Nothing catches it.
`ensure_schema` is a per-request dependency (`get_shares_db`), so that is a
500 on every client-folder route AND on every `/broll/share/<token>/...`
link an editor has handed a client, permanently, curable only by
hand-editing `PRAGMA user_version` on the NAS - on the one database
CLAUDE.md says must never be at risk from anything. The verifier knocked
down the hunter's concurrency trigger (`mount_broll` calls `ensure_schema`
at boot, before any request) and confirmed the interrupt path. Fixed by
making the step re-runnable and atomic: one `BEGIN IMMEDIATE` around the
whole v1 branch (two threads cannot both enter it, and the ALTER now rolls
back with everything else if the process dies), the column TESTED for with
`PRAGMA table_info` rather than assumed absent, `user_version` re-read under
the lock, and a backfill that only ever writes rows whose hash is still
blank, so a half-done one is simply finished by the next run. `get_shares_db`
also no longer lets a sqlite failure in `ensure_schema` take the public door
out - it logs and opens the connection anyway. The deliberately fatal
"newer user_version" RuntimeError is NOT caught: an older app half-reading a
newer file is the worse outcome.

**broll-6 (low) - the backfill was sized by the archive.** It read every
hashed row of `videos` (tens of thousands) and issued one
`UPDATE ... WHERE hash = '' AND share = ? AND rel_path = ?` per row against a
table indexed by `(folder_id, ord)` alone: a full scan each, inside whichever
request first touched the ledger, holding its write lock - which is also what
made broll-2's window seconds wide instead of milliseconds. Inverted: it now
walks the few hundred `client_folder_items` rows with a blank hash and looks
each up on `videos`' UNIQUE `(share, rel_path)`.

**broll-1 (medium, with comp-broll-music-3) - "try the 12 failed again"
queued them again and then told nobody.** `retry_failed` answers with
`items` = `ingest_items.uid`, 32-hex uids minted server-side, and the page
handed them straight to the companion's `POST /broll/ingest/retry`, which
matches `items` against the keys of its STAGING ledger - browser-minted local
ids (`i<base36>`), a namespace these uids can never be in. So the companion
answered `200 {"retried": 0}`, the page's `e.status === 404` fallback to
`/broll/ingest/run` never fired, the toast said "12 clips queued again", and
the batch sat in `queued` for ever. Perversely a companion OLDER than 0.9.67
worked, because it 404s the route. The two routes are also about different
failures (`/ingest/retry` re-uploads staged bytes, BROLL-5; `retry-failed`
re-indexes batch items), so an id mapping would have rewritten the wrong
ledger. The fix is on the web side, as the verdict directs: the button now
dispatches the take-over call (`POST /broll/ingest/run` with the batch uid
and no staging id) - the already-tested path that settles possession through
the claim and works on every build in the fleet, new and old - and a 409 from
it now says plainly that another of the editor's computers is still on the
batch. The misleading comment in `retry_failed` that claimed those uids were
the companion's body is gone; `items` stays in the response for the page to
show.

**broll-3 / broll-4 (low) - a fleet route with no caller, under a docstring
with a wrong fact about the gate.** `GET /api/fleet/ingest/batches` shipped
with BROLL-8 on 2026-09-04 along with tests and a GET-only carve-out in the
dashboard's login gate (`_broll_fleet_list_re`), and no `FleetClient` method
ever issued it: the only `fleet/ingest` string in `companion/src` is the
prefix constant. The verdict refuted the failure scenario (the panel's
`[ take over on this computer ]` button is on every queued batch in the
editor's own scope, which is what a rebuilt machine's editor sees when they
open the panel) and warned against building the poller: a companion that
discovers and claims its own work moves the decision about what a machine
works on off the page, and the plan's rule is that possession is won by a
claim the PAGE dispatches. So the route is deleted, with its five tests, and
the module now carries the history in place of the route. Its docstring's
NOTE - "this route needs that regex widened before a companion behind the
dashboard can reach it", widened in the same commit that wrote it - went with
it; a wrong fact about a security gate is what gets a correct gate "fixed".

**broll-5 (low) - a retry could take a batch away from the machine working
on it.** `POST /api/ingest-batches/{uid}/retry-failed` refused nothing by
state: on a `claimed`/`running` batch with one failed item it set `queued`
and nulled `lease_expires_at`, `current_item_uid` and `cancel_requested`
underneath the leaseholder, so another of the editor's machines could win a
claim beside it and both index the same clips until the first one's next
per-item POST was 410'd. The SPA only draws the button on a finished batch,
but the route is the contract, not the button. It now 409s while the lease is
live, naming the machine. A lease nobody renewed has already been expired by
the list and claim paths, so the orphaned-batch case the button exists for is
untouched (pinned by a test).

### Verification
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_a_ledger_half_migrated_by_a_crash_is_completed_by_the_next_run` -> fails at 40f931a (`duplicate column name: hash`), passes now  (broll-2)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_ensure_schema_can_be_run_twice_over_the_same_v1_file` -> fails at 40f931a, passes now  (broll-2)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_a_ledger_that_will_not_migrate_does_not_take_the_share_door_out` -> fails at 40f931a, passes now  (broll-2)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_the_backfill_does_not_touch_the_ledger_once_per_archive_row` -> fails at 40f931a (61 writes for 1 curated item), passes now  (broll-6)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_the_retry_button_dispatches_the_take_over_call_not_item_uids` -> fails at 40f931a, passes now  (broll-1)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_retry_failed_does_not_claim_its_uids_are_the_companions_body` -> fails at 40f931a, passes now  (broll-1)
- `broll/web/tests/test_ingest_retry_and_takeover.py::test_the_batch_card_offers_the_failed_ones_again` -> rewritten to assert the BODY the page sends, which is the gap broll-1 lived in
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_the_fleet_router_carries_no_route_without_a_caller` -> fails at 40f931a, passes now  (broll-3)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_the_fleet_docstrings_do_not_claim_the_gate_needs_widening` -> fails at 40f931a, passes now  (broll-4)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_a_retry_is_refused_while_a_machine_still_holds_the_batch` -> fails at 40f931a (200, lease nulled), passes now  (broll-5)
- `broll/web/tests/test_bug_hunt_2026_09_11_broll.py::test_a_retry_is_allowed_once_the_lease_is_gone` -> the orphaned batch the button exists for is unaffected

### OWED TO ANOTHER TERRITORY
- `dashboard/src/ccsync_dashboard/app.py`: `_broll_fleet_list_re` (the GET-only
  login-gate carve-out for `/api/fleet/ingest/batches`, app.py:1067 and
  :1166-1170) now covers a route that no longer exists. It is harmless where
  it stands (GET only, and the fleet token is still required by the sub-app,
  which answers 404), but it should be deleted with this change. Ordering does
  not matter: nothing calls the route on either side.

### Owner decisions
- broll-3 was fixed by DELETING the discovery route rather than by writing the
  companion poller, on the verifier's reasoning (possession is won by a claim
  the page dispatches, and the take-over button already covers the rebuilt
  machine). If the fleet is ever meant to pick up its own orphaned batches
  unattended, that route comes back with a caller and the gate carve-out stays.
- The retry button no longer talks to `/broll/ingest/retry` at all. That
  loopback route keeps its job (re-uploading staged bytes for the drop the
  page is holding) and is unchanged; nothing on the companion side needs
  redeploying for this fix, which is the reason it was chosen.
