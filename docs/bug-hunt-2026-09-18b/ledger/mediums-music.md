# CR-304 - music: the cancel wedge's other branch, and a toast that blamed the companion for the browser - FIXED in repo 2026-09-18 (mediums wave)

Group `music` (files: `music/web/*`, `music/indexer/*`). Both confirmed
mediums fixed. `music/indexer` was not touched.

### CR-304A (music-1) - a cancel delivered to a LIVE lease still wedged the batch - FIXED (`music/web/musicweb/ingest_batches.py`)

CR-286's music-1 fix made the finalise branch of the cancel route correct, but
the branch it deliberately keeps - a cancel delivered to a machine that really
is indexing - still called `ingest_batches.cancel()`, which set
`lease_expires_at = NULL` while leaving `state = 'running'`. That is outside
`expire_stale_leases`'s predicate (`lease_expires_at IS NOT NULL`) for ever, so
a companion killed before its next heartbeat (crash, Stop-Process, power cut,
its own upgrade) left a row no sweep could reach, no claim could take
(`_leaseholder_or_410` 410s on `cancel_requested` first), and whose every
`dest_name` stayed in `reserved_names`, so each later drop of `Theme.wav` was
allocated as `Theme (2).wav`. The fix is the verifier's: `cancel()` no longer
touches the lease at all - the YTDL-WEB-1 property it was written for (the next
fleet call 410s even if a heartbeat lands first) is already delivered by
`cancel_requested` - and `expire_stale_leases` now finalises a cancelled batch
whose lease ran out (`release(..., state='cancelled')`) instead of handing it
back to `queued`, which nobody would be allowed to claim. Four tests: the lease
survives the cancel, the swept row is `cancelled` with a `finished_at`, the
names it held are released, and an uncancelled expired lease still goes back to
the queue.

### CR-304B (music-3) - the retry toast reported a browser error as the companion's answer - FIXED (`music/web/static/ingest.js`)

CR-286's music-2 fix replaced a bare `catch { }` with `refused =
miRefusalText(e)` for EVERY exception, and `miRefusalText` falls through to
`e.message` for anything that is not a 409. The two commonest dispatch failures
are not refusals in words at all: no tray at all (a rejected fetch, message
"Failed to fetch", no status) and a companion too old for `/music/ingest/*`
(404, the app's own generic "the CC Sync tray returned HTTP 404"). Both printed
as the reason this computer did not pick the tracks up, and because `refused`
was truthy the only sentence that says what to DO - open the page on the
computer that has the tracks - was unreachable on that path. Now
`miSpokeARefusal(e)` (a 409, or a body carrying `reason`/`message`) decides
whether the companion really answered; anything else keeps the fallback
sentence and gains a hint, `MI_TOO_OLD` on a 404 and "The CC Sync tray on this
computer did not answer." otherwise. `miTakeOver`'s mirror shape (its else arm
printed a raw `e.message` into the notice) goes through the same two helpers.
Three node-driven tests drive `miRetryFailed` with the real thrown shapes.

### Verification
- music-1: `tests/test_bug_hunt_2026_09_18b_music.py` - four tests, all four fail on the pre-fix source (checked) and pass after.
- music-3: same file, three node tests; the no-tray and too-old ones fail on the pre-fix source and pass after.
- Re-run: `cd music/web; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18b_music.py tests/test_bug_hunt_2026_09_18_webapps_tools.py tests/test_bug_hunt_2026_09_11b_music.py tests/test_bug_hunt_2026_09_11_music.py tests/test_fleet_ingest.py tests/test_ingest_ui.py tests/test_plain_words.py tests/test_one_vocabulary.py tests/test_api.py tests/test_db.py -q` - 179 passed. `py_compile` on both changed modules and the new test file; `node --check` on `ingest.js`.

### Not fixed
- Nothing in the group's list. music-2 (downgraded to low) was not started.

### OWED TO ANOTHER GROUP
- `webapps-broll` (CR-302), `broll/web/app/ingest_batches.py`: the b-roll twin of music-1. `cancel()` there nulls `lease_expires_at` in the same UPDATE - drop that column from the UPDATE, and in `expire_stale_leases` select rows with `cancel_requested = 1` whose lease has expired and `release(conn, batch, state='cancelled')` them before the requeue UPDATE, returning `cur.rowcount + len(stopped)`. Same reasoning applies: the 410 comes from `cancel_requested`, not from the lease.
- `webapps-broll` (CR-302), `broll/web/static/ingest.js`: the same helper pair (`miRefusalText` / `miRetryFailed` / `miTakeOver`) carries the music-3 shape. Port `miSpokeARefusal` and the hint arm.
- Both are safe alone: neither half of this fix reads or writes anything in the b-roll checkout.

### Deploy order
Dashboard side only (both files are served by the dashboard's `/music` mount);
no companion or wire change. A companion of any vintage is unaffected: the
fleet routes' answers are unchanged, and the only difference a companion can
observe is that a cancelled batch it never answered for now reaches
`cancelled` rather than `queued`, which its own `_leaseholder_or_410` already
treats as 410. A dashboard rollback restores the old wedge, nothing worse.

### Owner decisions
None.
