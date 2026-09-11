# music - the music web app (`music/web/musicweb/*`, `music/web/static/*`) and the music indexer

Files read (with approximate coverage):
- `git diff 40f931a..HEAD -- music/` in full (config.py, fleet_auth.py,
  ingest_batches.py, rescore.py, routes_batches.py, routes_fleet.py,
  routes_media.py, static/ingest.js, SPEC.md, the two test files) - 100% of the
  hunks, read against both sides of every wire they touch.
- `music/web/musicweb/ingest_batches.py` (allocate_name / precheck /
  create_batch / claim / retry_failed / write_item_result / lease helpers, ~70%),
  `routes_fleet.py` (100%), `routes_batches.py` (~80%), `fleet_auth.py` (100%),
  `config.py` share/readiness half (~60%), `rescore.py` (~50%),
  `routes_media.py` (100%), `static/ingest.js` (~60%: miApi, miLoopback, miRun,
  miRenderBatches, miRetryFailed).
- The other side of each wire, read but not owned:
  `companion/src/ccsync_companion/broll_server.py` (the `/music/ingest/retry`
  handler), `music_ingest.py` (`_result_retry_wait`, `_post_result`),
  `broll_ingest.py` (`retry`, `run`, `_next_item`),
  `dashboard/src/ccsync_dashboard/music.py` (the MusicGate stamp), and
  `broll/web/app/{routes_batches,ingest_batches,fleet_auth}.py` +
  `broll/web/static/ingest.js` as the reference implementation music-2 was
  ported from.
- `music/indexer/*`: skimmed only (no diff since 40f931a).

Tests run:
- `cd music\web; .venv\Scripts\python.exe -m pytest tests -q` -> 591 passed, 2 skipped
- `cd music\indexer; python -m pytest tests -q` -> 46 passed, 1 skipped

## Findings

### music-1 - retry-failed takes a LIVE batch away from the machine indexing it (the broll-5 guard was not ported)
- Severity: high
- Confidence: CONFIRMED
- Where: `music/web/musicweb/routes_batches.py:199-215` (no `lease_live` check)
  and `music/web/musicweb/ingest_batches.py:580-590` (the reset that nulls the
  lease); the reference with the guard is
  `broll/web/app/routes_batches.py:197-226`.
- What: music-2's `POST /api/ingest-batches/{uid}/retry-failed` is a near-verbatim
  port of b-roll's BROLL-18 route, but it was ported from the pre-hunt version:
  b-roll grew a refusal THIS MORNING (broll-5, same fix pass, 18e69f3) that
  409s when `ingest_batches.lease_live(batch)` - and that half is missing here.
  `retry_failed` unconditionally sets `state='queued'`, `lease_expires_at=NULL`,
  `current_item_uid=NULL` whenever at least one item is `failed`, without asking
  whether a machine is still holding the batch.
- Failure scenario: an editor is mid-drop, fifteen tracks, one has already
  failed (`n_failed = 1`), the batch is `running` with a live lease on
  `RAZER`. Anyone who may see the batch (the owner on any page, or an admin in
  the "all machines" scope) presses `try the failed tracks again`. The lease is
  nulled server-side; RAZER's next item `status`/`result`/`heartbeat` POST hits
  `_leaseholder_or_410` (`routes_fleet.py:67-98`), fails `lease_live`, and is
  answered `410 lease_expired`, killing the run mid-batch. Worse, `claim`
  (`ingest_batches.py:703`) only refuses another machine when
  `batch['machine'] != machine AND lease_live(batch)` - with the lease nulled
  and `machine` left as-is, a SECOND machine of the same editor can claim
  beside RAZER and both index the same tracks into the same library until the
  first one is 410'd.
- Evidence: read both routes side by side; b-roll's docstring states the
  reason in as many words ("possession taken away without telling it: a second
  machine can win a claim beside it"). `lease_live` is defined at
  `music/web/musicweb/ingest_batches.py:156` and is already used by `claim`, so
  nothing but the call is missing. No test in `tests/` calls retry-failed on a
  non-terminal batch: `test_bug_hunt_2026_09_11_music.py` only exercises a
  batch forced to `done_with_errors` by `_fail_one_item`.
- Ledger: new (the music half of broll-5 / CR-246); "CR-246 does not fix
  broll-5 in music".
- Suggested fix: copy b-roll's guard verbatim into `routes_batches.retry_failed`
  - `if ingest_batches.lease_live(batch): raise HTTPException(409, {...'reason':
  'held', 'machine': batch['machine']})` - with the same wording (no em dash).

### music-2 - the retry button is drawn on running batches and on other editors' batches
- Severity: medium
- Confidence: CONFIRMED
- Where: `music/web/static/ingest.js:1245` (`if (batch.n_failed > 0)`); the
  reference is `broll/web/static/ingest.js:1623` (`n_failed > 0 && ing.scope
  === "mine" && ["done","done_with_errors","failed"].includes(batch.state)`).
- What: b-roll draws the retry button only for the editor's OWN batches and
  only in a terminal state; music's port dropped both conditions. It is drawn
  next to `cancel` on a `claimed`/`running` batch as soon as one track has
  failed, and it is drawn in the admin `all` scope over other editors'
  machines' work. That single click is how music-1 above is reached in
  practice, and in the admin scope the dispatch half cannot possibly help
  (the admin's computer has none of the audio staged).
- Failure scenario: admin opens Music -> ingest, scope "all machines", sees
  `leso - running - 1 failed`, presses the button; leso's run is 410'd
  mid-batch (music-1) and the admin is told "1 track back in the queue" with
  no machine anywhere holding it.
- Evidence: the two render functions read side by side; music's
  `MI_TERMINAL_STATES` is already in the file (used two lines above for the
  cancel button) and is not consulted for the new one.
- Ledger: new (music half of BROLL-18/broll-5).
- Suggested fix: `if (batch.n_failed > 0 && mi.scope !== 'all' &&
  MI_TERMINAL_STATES.includes(batch.state))`. Keep the server-side guard from
  music-1 as well: the route is the contract, not the button.

### music-3 - a retried batch is undispatchable after a page reload: music has no take-over path
- Severity: medium
- Confidence: CONFIRMED
- Where: `music/web/static/ingest.js:1287` (`if (uid === mi.batchUid &&
  mi.stagingId)`), `:137` (`stagingId: null`, in-memory only), `:930` (`miRun`
  builds a NEW batch from the currently staged items); the b-roll equivalent is
  `broll/web/static/ingest.js:1613` ("take over on this computer" for any
  `queued` batch) and `:1702` (retry always dispatches `/broll/ingest/run`).
- What: music's `miRetryFailed` only tells the companion to pick the batch up
  when the page still remembers the drop in memory (`mi.batchUid` +
  `mi.stagingId`). Both live in `mi` and are lost on every reload. The
  otherwise-correct fallback toast says "Open this page on the computer that
  staged them and press Run" - but music's Run button submits the CURRENT
  staged selection as a brand new batch; there is no "take over"/resume control
  for a `queued` batch anywhere in the music SPA, and the companion only
  resumes a batch it is already holding in its own state file
  (`broll_ingest._resume`). b-roll grew the take-over button precisely because
  of this.
- Failure scenario: the normal case - a drop finishes `done_with_errors`, the
  editor comes back after lunch (page reloaded), presses "try the failed tracks
  again". The server re-queues the items and the batch sits in `queued`
  ("waiting for your computer") for ever; the only way out is cancelling it and
  dropping the files again, which is exactly the state music-2 set out to
  remove.
- Evidence: `grep -n stagingId static/ingest.js` shows it is only ever set from
  a live `prepare` answer (line 519) and reset to null (353); nothing reads or
  writes it from storage. No `take over` / resume control exists in the file.
- Ledger: new (music-2 landed the server half and only the same-session half of
  the browser half).
- Suggested fix: dispatch unconditionally for the editor's own batch -
  `miLoopback('POST', '/music/ingest/retry', {batch_uid: uid, staging_id:
  mi.batchUid === uid ? mi.stagingId : ''})` - the companion's run() accepts an
  empty staging id; and/or add b-roll's "take over on this computer" button for
  any `queued` batch in the `mine` scope.

### music-4 - the positive readiness cache keeps the write gate open for 5 s after the library mount disappears
- Severity: medium
- Confidence: PLAUSIBLE (mechanism CONFIRMED by reading; not reproduced against
  a real bind mount)
- Where: `music/web/musicweb/config.py:434-460` (`_READY_CACHE_SECONDS`,
  `_ready_cached`) and `:486-489` (the early return in `share_root_ready`).
- What: music-5 cached the POSITIVE answer of the mount probe for 5 seconds to
  save the per-item stat storm. `share_root_ready` is the ONLY thing standing
  between an unmounted `/library` bind mount and a write path that mints
  filenames and `tracks` rows for audio that will land in the container's own
  filesystem; caching its positive answer converts a fail-closed gate into one
  that stays open for up to 5 s after the mount goes. The comment argues "a
  mount that was there a moment ago is not a fact that changes between two
  items of one batch" - but a NAS reboot or an SMB session drop is precisely a
  fact that changes between two items, and the fleet ingest path calls
  `allocate_name` once per item with no other mount check.
- Failure scenario: the NAS reboots during a 15-track album drop. Items 6, 7
  and 8 are allocated and written inside the cache window: three `tracks` rows
  and three `uploaded` destinations pointing at a directory that is not the
  library. (`mark_uploaded` stat()s afterwards, which catches the file - but
  the row, its embedding and the rescore have already happened.) After the
  window the refusal appears and the editor is told the mount is away, mid-drop.
- Evidence: `share_root_ready` is called from `allocate_name`
  (`ingest_batches.py:249`) and nothing else re-probes per write; the new
  `test_a_positive_answer_is_not_re_probed_per_item` asserts the cache is used
  and never asserts anything about a share that vanishes inside the window.
- Ledger: new (introduced by music-5 in CR-246).
- Suggested fix: keep the cache but make the cheap half unconditional - re-run
  `root.is_dir()` (one stat, not fifty) on every call and cache only the
  50-sample content probe; or drop the window to ~1 s and clear it whenever a
  write path sees an OSError.

### music-5 - `_snapshot_token` can raise out of the first line of `rescore_library`
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/musicweb/rescore.py:330-352` - `scores_stale(con)` is
  called OUTSIDE the `try` that the docstring says makes an unreadable database
  a harmless "cannot tell" token.
- What: the guard catches a failure of `SELECT MAX(id)` but not of the
  `meta` read beside it, so a locked or malformed database raises from
  `rescore_library`'s first statement rather than yielding the never-equal
  sentinel the comment promises. Both callers happen to catch
  (`ingest_batches.py:1023` and `routes_fleet._settle_scores`), so the
  consequence today is only a misleading error path (`write_item_result`'s
  handler then calls `rescore.scores_stale(conn)` again, which raises a second
  time from inside the except and turns a degraded DB into a 500 on the fleet
  result route - a status the companion treats as terminal for that track).
- Failure scenario: `music.db` is locked by a long publish (`publish_db.py`)
  while a fleet result lands: the track is written, `apply_for_track` raises,
  and the handler's own `scores_stale` raises again -> HTTP 500 -> the
  companion's `_result_retry_wait` sees no `retry` flag and no retryable status
  and fails the track permanently.
- Evidence: read `_snapshot_token` and `write_item_result`'s except block;
  `db.get_meta` does no swallowing of `sqlite3.Error`.
- Ledger: new (introduced by music-3 in CR-246).
- Suggested fix: move `scores_stale(con)` inside the `try` (and wrap the
  `scores_stale` call in `write_item_result`'s except block, or reuse the value
  already read).

### music-6 - `editor:` stamps are rejected for any editor name with a space, silently downgrading to a token mismatch 403
- Severity: low
- Confidence: PLAUSIBLE
- Where: `music/web/musicweb/fleet_auth.py:61` (`_STAMP_RE =
  ^(shared|editor:[^\s]{1,64})$`) vs `broll/web/app/fleet_auth.py:107-122`
  (any non-empty name after the prefix).
- What: the dashboard's MusicGate stamps `editor:{editor}` with the account
  name it decoded (`dashboard/.../music.py:210`). Music's regex refuses a name
  containing whitespace or longer than 64 characters; `gate_stamp` then returns
  `(None, None)` and the call falls through to the SHARED token comparison,
  which a per-editor `cce1.` token cannot satisfy - so such an editor is
  answered 403 "missing or invalid X-CCSync-Token" with no hint that the stamp
  was the problem. b-roll and ytdl accept the same name.
- Failure scenario: an editor account whose username is not the usual unix
  shape (the site manifest and local_users do not everywhere force one) loses
  music fleet ingest entirely, with a refusal that names the wrong credential.
- Evidence: the two regexes read side by side; the refusal path is
  `fleet_auth.py:130-134`. Not reproduced end to end (I did not verify what
  usernames provisioning can mint).
- Ledger: related to CR-55; new in music.
- Suggested fix: match b-roll's parser (prefix + non-empty remainder), and log
  the rejected stamp shape at warning level when one is present but
  unparseable.

## Coverage note
- `music/indexer/*` got a skim only: it has no diff since 40f931a and the whole
  hunt's premise is this afternoon's fixes. Its 46 tests pass.
- I did not audit `search.py`, `projection.py`, `vocab.py`, `drain.py` or the
  share/reveal routes beyond what the diff touched.
- What the suite does not cover: the retry-failed route against a
  non-terminal/leased batch (music-1 - nothing calls it in any state but
  `done_with_errors`); the browser half of music-2 beyond a source-text scan of
  `ingest.js` (`test_the_page_only_says_running_when_the_companion_claimed_it`
  greps the function body for three strings - it would pass with the dispatch
  unreachable, which is music-3); a share that disappears INSIDE the new
  readiness cache window; and `_snapshot_token` against a database that cannot
  answer `get_meta`.
- The new regression tests are otherwise honest: music-1's deadline-thread
  harness genuinely fails on the pre-fix loop, and the CR-55 binding tests do
  exercise the mismatch that used to succeed.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_ingest.py:2093-2115`: `_next_item`
  skips items whose `result_retry_at` is in the future; if every remaining item
  is waiting, `_drain` returns `STATE_NOTHING_TO_DO` on each pass - worth a
  check by comp-broll-music that `_maybe_finish` really does hold the batch and
  the lease open (the comment asserts it) rather than releasing it as done.
- `music/web/musicweb/config.py:209`: `_LOGIN_GATED` IS read from
  `MUSIC_LOGIN_GATED` despite the comment three lines above saying it is "NOT
  inferred from the environment"; a standalone musicweb with that hatch set
  believes an inbound `X-CCSync-Fleet-Auth` header with no gate stripping it.
  Pre-existing, mitigated by `require_identity`, but it is the b-roll
  `trust_gate_stamp` discipline not applied here - for the security lens.
