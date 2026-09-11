# dash-release-jobs - the dashboard's release channel, job scheduler, AI providers and Timeline Cards mount

Files read (with approximate coverage): `dashboard/src/ccsync_dashboard/release_feed.py`
(the whole diff since 40f931a plus `_record_key`/`_valid_records`/`publish_from_feed`/
`build_feed_view`/`FeedPoller`, ~60%), `release_trust.py` (version helpers and
`min_version_exceeds_version`, ~40%), `dashboard_update.py` (state file,
`_heal_orphaned_progress`, `request_restart`/`consume_restart_request`/`finish_restart`,
`_read_json`/`_write_json`, ~40%), `cards_ai.py` (the whole selection block, `run`,
`split_prompt`, cache placement, ~50%), `cards_tunnel.py` (100%), `cards.py`
(`mount_cards`, ~40%), `cards_exec.py` (`PinnedExecutor` start/stop/loop/tick, ~50%),
`jobs.py` (skim), `ai_providers.py` / `cli_tools.py` / `cards_wsgi.py` / `ed25519.py`
(skim only). Cross-read outside the territory for both sides of each wire:
`companion/src/ccsync_companion/timeline_cards_role.py`,
`dashboard/src/ccsync_dashboard/{alerts,mount_status}.py`, `tools/publish_feed.py`,
and the Timeline Cards repo's `multicam_pipeline/cards/{chat_edit,agent,claude}.py`.
Prior hunt: `docs/bug-hunt-2026-09-11/hunters/dash-release-jobs.md` + `verdicts.txt`.

Tests run: `cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_release_feed.py
tests/test_cards_tunnel.py tests/test_dashboard_update.py tests/test_cards_ai.py
tests/test_jobs.py tests/test_cards_mount.py -q` -> 272 passed, 1 skipped.
Plus two ad-hoc snippets from the dashboard venv (below).

All seven of this territory's findings from the morning hunt were addressed: -1 and -3
in `db.py`/`api.py` (other territories), -2 in `dashboard_update.py`, -4 and -5 in
`release_feed.py`, -6 in `cards_tunnel.py` + `timeline_cards_role.py`, -7 in
`release_feed.py`. The findings below are what those fixes opened, plus their skew.

## Findings

### dash-release-jobs-1 - the FeedPoller restart fix revives the OLD thread as well as starting a new one
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:1263-1280` (same shape,
  pre-existing, at `dashboard/src/ccsync_dashboard/cards_exec.py:144-157`)
- What: `stop()` sets `_stop`, joins with a 5 s timeout and drops `_thread`
  unconditionally - it does not check whether the join succeeded. `start()` then
  does `self._stop.clear()` before spawning thread 2. `_run`'s loop condition is
  `while not self._stop.is_set()`, so clearing the event un-stops the thread that was
  still inside `check_now` when the join expired: it finishes its cycle, re-tests a
  now-cleared event, and keeps polling. Two poller threads on one `FeedPoller`.
- Failure scenario: a feed check is mid-artifact-download (`fetch_artifact_to`, minutes
  on a slow link, or a hung socket up to the read timeout) when the lifespan calls
  `stop()`. join(5.0) expires, `_thread` becomes None, a later `start()` (a settings
  reload, or any code path that restarts the poller on the same object) clears the
  event. From then on two threads run `check_now(conn, settings, app_state)` on
  independent connections: under `auto` policy both can pass the "already published"
  test for the same record and race into `store_verified_package`, and both stamp
  `app_state`'s `valid_records` cache and `db.set_feed_state`. The fix's own comment
  claims `cards_exec.PinnedExecutor` "has always had this shape; the two threads in
  this territory now agree" - they agree on the bug too, and for `PinnedExecutor` the
  revived thread is a second ffmpeg worker on the same pinned queue.
- Evidence: read of `FeedPoller.stop/start/_run` (release_feed.py:1263-1303) and
  `PinnedExecutor.stop/start/_loop` (cards_exec.py:144-182). `threading.Thread.join`
  with a timeout returns None either way; nothing consults `thread.is_alive()`.
  `test_a_stopped_feed_poller_starts_again` (test_release_feed.py:1258) stubs
  `check_now` with a lambda that returns instantly, so the join never times out and
  the test cannot see this.
- Ledger: new (opened by the fix for dash-release-jobs-5, cited in the code as
  "dash-release-jobs-4")
- Suggested fix: in `stop()`, keep `_thread` when `join` times out
  (`if thread.is_alive(): self._thread = thread`), or give the loop a generation
  counter so a revived thread exits on the next pass. Apply to both classes.

### dash-release-jobs-2 - the staged half of the SELECTED CARDS block is truncated silently, and its count lies
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_ai.py:862-868`
- What: the selected half caps at `MAX_SELECTION_ROWS` and then prints
  "...and N more, by id alone: ..." so the model knows the list is partial. The staged
  half prints the FULL count in its header ("Staged cards selected on the shelf
  (%d)" % len(shelf)) and then renders `shelf[:MAX_SELECTION_ROWS]` with no such line.
  The model is told there are 120 and shown 40, with nothing saying the other 80 exist.
- Failure scenario: an editor marquee-selects 120 staged cards on the shelf and asks
  "put the selected staged cards into a new section". The model sees a header claiming
  120 and 40 ids; the plausible completion is an op naming those 40, presented to the
  editor as the answer to a request about 120. The Timeline Cards side
  (`chat_edit.Where.selection_block`) does not truncate at all, so the same selection
  through the standalone CLI door renders all 120 - the two doors now disagree about
  what the model was told, which is exactly the "two builders of one wire, two
  contracts" shape.
- Evidence: ad-hoc from the dashboard venv:
  `selection_block({'cards': [3 rows], 'staged': [120 rows]}, staged)` -> 47 lines,
  last staged row `40. [g39]`, next line `END SELECTED CARDS`, header says 120.
- Ledger: new (cards selection context, 2026-09-11, uncommitted-in-spirit half of the
  cards-selection wire)
- Suggested fix: give the staged branch the same "...and N more, by id alone:" line the
  selected branch has, or cap the header count at what is actually rendered.

### dash-release-jobs-3 - an older companion's Cards agent loses its machine name, so one editor's two machines become one string
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:247-254` (dashboard side),
  `companion/src/ccsync_companion/timeline_cards_role.py:873-878` (companion side)
- What: the fix stopped falling back to the body's self-asserted `name` and now uses
  `body.get("machine")` only. `machine` is sent only by companion 0.9.71, which landed
  in the SAME commit (18e69f3). The field runs 0.9.65..0.9.71 and a Mac on 0.9.70, so
  for every machine not yet upgraded `agent_name(editor, "")` returns the editor alone.
- Failure scenario: alex runs the cards agent on CREATOR-1 (0.9.71) and on the Mac
  (0.9.70). The page's away/stale text and `agent_name` used to read
  `alex/CREATOR-1` and `alex/leso-mbp`; after the dashboard is deployed and before the
  companions are, the Mac reports as plain `alex`. Since the engine keeps the last
  `body["name"]` (`multicam_pipeline/cards/agent.py:348`,
  `self.agent_name = body.get("name") or self.agent_name`), the one question the fix's
  own comment says this string answers - "which computer is driving Resolve" - is now
  answered less precisely than before for most of the fleet. Display only (nothing keys
  on it), which is why this is medium and not high.
- Evidence: `git log -- companion/.../timeline_cards_role.py` shows `body["machine"]`
  first appears in 18e69f3 (companion 0.9.71); the previous commit touching that file
  is 84be2d7 (0.9.70). The dashboard-side test
  `test_the_name_is_the_editor_alone_when_no_machine_is_declared`
  (test_cards_tunnel.py:226) pins the degraded string as correct rather than flagging
  the skew.
- Ledger: new (skew opened by the fix for dash-release-jobs-6)
- Suggested fix: fall back to a SANITISED `body["name"]` only as the machine half when
  `machine` is absent, and mark it as unverified on the page (e.g. `alex/~HOSTNAME`);
  or leave it as is and note in `KNOWN_BUGS` that the legible name needs 0.9.71 on the
  machine, so an operator does not read "alex" as a bug.

### dash-release-jobs-4 - a feed record with a non-canonical kind/platform is now dropped with nothing at all to tell the admin
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:489-508`
- What: the fix for dash-release-jobs-7 both case-folds `_record_key` AND adds a
  `continue` that drops any record whose `kind`/`platform` is not already lower-case.
  The drop increments nothing, sets no `last_error`, adds no notice, and is not counted
  in the `dropped` tally that the summary log line reports (that counter is for
  signature failures only). `db.set_feed_state` still records `ok`, so
  `alerts._check_feed_stale` (alerts.py:1748) - which fires only on `last_error` or
  staleness - stays quiet.
- Failure scenario: the vendor publishes `companion`/`Windows` 0.10.0. The admin's
  [ CHECK NOW ] answers ok, the feed page lists nothing new, the fleet never updates,
  and the only evidence is one WARNING in a container log nobody opens. Before the fix
  the record was at least LISTED as available (and 404'd on the button), which is a
  visible fault; it is now an invisible one. Likelihood is low because
  `tools/publish_feed.py` constrains `--platform` with `choices=sign_release.PLATFORMS`
  - but `--from-manifest` (publish_feed.py:810) assigns `args.platform` from the
  manifest after argparse, bypassing that.
- Evidence: read of `_valid_records` (the `odd` branch), of the `dropped` counter it
  does not touch, and of `alerts.ALERT_KINDS`' two feed checks - neither reads anything
  a dropped record would set.
- Ledger: new (opened by the fix for dash-release-jobs-7)
- Suggested fix: count these in `dropped` (or a second counter) and surface them
  through `db.set_feed_state`'s `last_error` / a `feed_record_rejected` notice kind, so
  a build that cannot be offered is a PROBLEM THE SERVER FOUND and not a log line.

### dash-release-jobs-5 - `_signature_url` still cannot fetch the signature for the pre-signed URL its docstring is about
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:339-352`
- What: the fix appends `.sig` to the path and carries the query across. For a CDN
  token query that works. For the case the docstring names - "a pre-signed ... URL" -
  it cannot: an S3/SigV4 pre-signed signature is computed over the canonical request
  INCLUDING the object key, so reusing the same `X-Amz-Signature` against
  `channel.json.sig` yields `SignatureDoesNotMatch` (403), not the file. The failure
  moves from 404 to 403; the site still stops receiving builds.
- Failure scenario: an operator configures `RELEASE_FEED_URL` as an S3 pre-signed URL
  as the fix's own comment invites. Every check fails with a 403 on a URL the operator
  never configured, and the comment above the code says this case is handled.
- Evidence: read of `_signature_url` and of `fetch_and_verify_channel`'s single call
  site; AWS SigV4 pre-signing binds the signature to the path. No test covers a feed URL
  with a query string (grep of test_release_feed.py for `?` in a CHANNEL_URL).
- Ledger: new (the fix for dash-release-jobs-4 is correct for query-token URLs and
  over-claims for pre-signed ones)
- Suggested fix: either narrow the docstring to query-token URLs, or take the signature
  URL as its own setting (`RELEASE_FEED_SIG_URL`) for hosts where the two URLs cannot be
  derived from one another.

### dash-release-jobs-6 - two different fixes in the tree cite "dash-release-jobs-3", and the citations are off by one from -3 onward
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:342` and `:1264`
- What: the morning hunt's ids are -3 = the advisory fleet cap, -4 = the signature URL,
  -5 = the poller. The builder labelled the signature-URL fix "dash-release-jobs-3
  (2026-09-11)" and the poller fix "dash-release-jobs-4 (2026-09-11)". `db.py:9294`
  and `api.py:10321` correctly cite dash-release-jobs-3 for the fleet cap, so
  `grep -rn dash-release-jobs-3` now returns two unrelated fixes and
  `grep -rn dash-release-jobs-5` returns none - the audit trail this brief's own rule 3
  and the `regression` lens depend on.
- Failure scenario: a future reviewer greps for dash-release-jobs-5, finds nothing, and
  concludes the poller finding was never fixed - or finds the signature URL under -3 and
  concludes the fleet cap was fixed in `release_feed.py`.
- Evidence: `docs/bug-hunt-2026-09-11/tally.txt:93-99` against
  `grep -rn "dash-release-jobs" --include=*.py .`
- Ledger: new (hygiene on the CR-233..CR-248 fix pass)
- Suggested fix: renumber the two comments to -4 and -5; a one-line note in
  `KNOWN_BUGS.md` is cheaper than the next grep.

### dash-release-jobs-7 - `read_state` writes to disk, so a full or read-only data dir turns a status read into an exception on the boot and shutdown paths
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:439-446` and `:493-510`
- What: `_read_json` is deliberately exception-proof ("these are read on the boot path
  and a JSON error must not be what stops the dashboard starting"), but
  `_heal_orphaned_progress` - which `read_state` always calls - writes through
  `_write_json`, which is not guarded. The new `restart_requested` branch adds a second
  unguarded write site on the path `finish_restart -> consume_restart_request ->
  read_state`.
- Failure scenario: the appliance's data dataset is full (or read-only after a pool
  fault). An update reaches `request_restart`; at lifespan shutdown `finish_restart`
  calls `read_state`, `tmp.write_text` raises `OSError: No space left on device`, the
  exception escapes the shutdown handler, `_exit_process(75)` is never reached, and the
  process exits 0 - so `deploy/run.sh` does not re-exec and the applied code never
  starts running, with no state file entry saying why. The same OSError makes every
  `GET /api/v1/admin/dashboard-update` 500 instead of reporting the disk problem.
- Evidence: read of `_write_json` (no try/except; `mkdir` + `write_text` + `replace`)
  and of `read_state`'s unconditional call into the healer. `_free_bytes` two functions
  below shows the module already knows "unknown must not be guessed at".
- Ledger: new (aggravated by the fix for dash-release-jobs-2)
- Suggested fix: wrap the healer's `_write_json` in try/except OSError, log it, and
  return the healed dict anyway - the in-memory correction is what unwedges the routes;
  persisting it is best-effort.

## Coverage note

`jobs.py` (1,106 lines: the rank signals, the per-kind fleet cap's ranking half, the
cooldown and `why`) got a skim only - the cap's compare-and-set fix landed in `db.py`
and `api.py`, which are other territories, and the dashboard suite's `test_jobs.py` is
green. `cli_tools.py` (2,003 lines: the SET UP wizard, the checksum CONDITION of
trust-model-7, the pty sign-in) and `ai_providers.py` (1,192 lines) were not read in
anger; neither changed since 40f931a, but neither is covered by anything I ran beyond
their own suites, which I did not run (other territories' files import them). I did not
exercise `cards_exec.py`'s pinning path against a real engine, and nothing in the suite
does either - `fleet_execute` is stubbed everywhere. No test drives a feed URL carrying
a query string, a `check_now` that overruns a `stop()`, or a selection block larger than
`MAX_SELECTION_ROWS` on the staged side.

## OUT OF TERRITORY

- `dashboard/src/ccsync_dashboard/mount_status.py:73-81`: `_ROOTS` is a process-global
  that `record_root` only ever adds to - a mount that is later disabled or re-mounted
  at a different root leaves the old path being re-probed by `recheck` every collector
  cycle for the life of the container.
- `tools/publish_feed.py:810`: `--from-manifest` assigns `args.platform` from the
  manifest AFTER argparse, so the `choices=sign_release.PLATFORMS` guard that keeps the
  vendor feed in the canonical lower-case spelling does not cover that path (this is
  what makes dash-release-jobs-4 above reachable at all).
- `multicam_pipeline/cards/chat_edit.py:606-627` (the Timeline Cards repo): its
  `selection_block` does not truncate, so a several-hundred-card selection through the
  standalone CLI door renders every row into the prompt.
