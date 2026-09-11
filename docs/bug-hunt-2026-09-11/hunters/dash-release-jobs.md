# dash-release-jobs - dashboard release channel, self-update, jobs scheduler, AI providers, Timeline Cards mount

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/jobs.py` (100%)
- `dashboard/src/ccsync_dashboard/release_feed.py` (100%)
- `dashboard/src/ccsync_dashboard/release_trust.py` (100%)
- `dashboard/src/ccsync_dashboard/dashboard_update.py` (100%)
- `dashboard/src/ccsync_dashboard/package_store.py` (~80%: everything from
  `blocks_on_dashboard_version` through `store_verified_package`; the
  `what_is_running` tail skimmed)
- `dashboard/src/ccsync_dashboard/cards.py`, `cards_exec.py`, `cards_tunnel.py` (100%)
- `dashboard/src/ccsync_dashboard/android.py` (100%)
- `dashboard/src/ccsync_dashboard/cards_ai.py` (~50%: the runner, the CLI
  path, the session store, `_says_no_such_session`)
- `dashboard/src/ccsync_dashboard/cli_tools.py` (~45%: the fetch/checksum/
  install/`$HOME`/env-allow-list half; the pty sign-in strategies skimmed)
- `dashboard/src/ccsync_dashboard/ai_providers.py` (~45%: key storage,
  masking, `cli_path`, probe cache, `lookup_payload`, routes)
- supporting reads outside the territory, for both sides of a wire:
  `db.py` (the jobs block, 8700-9700), `api.py` (report reply, job claim /
  cancel routes), `app.py` (lifespan, gates)
- `ed25519.py`, `cards_wsgi.py`, `ytdl.py`: skimmed only (see Coverage note)

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_ai_providers.py
tests/test_android.py tests/test_cards_ai.py tests/test_cards_capability.py
tests/test_cards_mount.py tests/test_cards_page_prefix.py
tests/test_cards_tunnel.py tests/test_cli_tools.py tests/test_dashboard_update.py
tests/test_jobs.py tests/test_jobs_backpressure.py tests/test_jobs_cancel.py
tests/test_jobs_contract.py tests/test_jobs_machines.py tests/test_jobs_pinning.py
tests/test_jobs_ranking.py tests/test_jobs_retry.py tests/test_jobs_scheduling.py
tests/test_release_channel.py tests/test_release_feed.py tests/test_ytdl_mount.py -q`
-> **801 passed, 6 skipped** in 176 s (clean baseline; nothing below is a
failing test today, which is the point of findings 1 and 2).

## Findings

### dash-release-jobs-1 - a cancelled job comes back and is handed to another machine when the lease expires
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:9246` (`expire_leases`) and
  `dashboard/src/ccsync_dashboard/db.py:8884` (`queued_jobs`); the contract it
  breaks is written at `db.py:9560-9581` and in `api.py:9825` (`api_cancel_job`).
- What: cancelling a HELD job only records `cancel_requested_at`; the row stays
  `claimed`/`running` and the machine is expected to stop it. If that machine
  never answers (asleep, offline, killed), `expire_leases` re-queues the row
  with no regard for `cancel_requested_at`, and `queued_jobs` has no filter on
  that column either - so the scheduler offers the cancelled job to the rest of
  the fleet and another machine claims it and starts the work.
- Failure scenario: an admin presses [ CANCEL ] on job #1 (`peaks`) held by
  `alex/BOX1`; BOX1's lid is shut. Ten minutes later the lease expires, #1
  returns to `queued`, `creator-2` is offered it on its next report, claims it
  and starts an ffmpeg over the media share - the exact work the admin stopped.
  It is only killed again after `creator-2`'s *next* report carries
  `commands.jobs.cancel`, and the cycle repeats until the retry budget is spent.
  The module comment says the opposite is true ("stays visible as 'cancelling'
  until the lease expires, and the lease is what ends it").
- Evidence: run from the dashboard venv against the real `db.py`:
  ```
  job 1
  claimed: True
  cancel -> requested
  state after cancel: claimed cancel_at: True
  expired -> [(1, 'queued')]
  final state: queued cancel_requested_at still: 2026-09-11T03:22:22+00:00
  in queued_jobs? [1]
  ```
  `tests/test_jobs_cancel.py` passes because it never expires a lease on a
  cancelled job - the test that would catch this does not exist.
- Ledger: new (cancel is CR-... phase 4, `docs/TIMELINE-CARDS-INTO-CCSYNC.md`
  §4.4 rule 5; nothing in KNOWN_BUGS mentions `cancel_requested_at`).
- Suggested fix: in `expire_leases`, a row with `cancel_requested_at` set goes
  to `failed` with `cancelled by <who>` instead of back to `queued` (the lease
  expiring IS "the machine never answered"), and belt-and-braces exclude
  `cancel_requested_at IS NOT NULL` from `queued_jobs`.

### dash-release-jobs-2 - a `restart_requested` latch left by a killed container wedges apply AND rollback for the life of the process
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/dashboard_update.py:452`
  (`_heal_orphaned_progress`, the `or state.get("restart_requested")` early
  return), consumed only at shutdown in `app.py:774` (`finish_restart`).
- What: `_heal_orphaned_progress` heals a stale `in_progress` flag by comparing
  `owner_pid`/`owner_nonce` - but it returns *before* that comparison whenever
  `restart_requested` is set. That flag is written by `request_restart` a
  moment before the process SIGTERMs itself, and it is cleared only by
  `consume_restart_request`, which runs exclusively in the lifespan's shutdown
  `finally`. A process that dies without that shutdown running (SIGKILL, OOM,
  NAS power loss, a `_write_json` failure in `consume_restart_request`) leaves
  `in_progress: true, restart_requested: true` on disk, owned by a pid/nonce
  that no longer exists, and nothing ever heals it.
- Failure scenario: `apply()` finishes the swap and calls `request_restart`;
  the NAS loses power in that second. The container comes back on the new tree
  and serves fine, but `preflight` and `rollback` both answer
  `409 ... an update to 0.7.43 is in progress (step: restarting)` for every
  admin click, for the whole life of that process. On the appliance shape
  (ZERO_TOUCH) there is no shell to delete `/data/code/update_state.json` with -
  which is the precise recovery problem CR-52's `dash-release-ai-2` /
  REL-9 fix was written to remove, and this is the one door they left open.
- Evidence: against the real module from the dashboard venv, with a state file
  stamped `owner_pid: 99999, owner_nonce: "deadbeef"`:
  ```
  after read_state: {'step': 'restarting', 'in_progress': True, 'restart_requested': True}
  ROLLBACK -> 409 an update to 0.7.43 is in progress (step: restarting) -- rolling back underneath it would race the swap.
  ```
  KNOWN_BUGS:1859 states the exemption deliberately ("`restart_requested`, the
  one in-progress state that legitimately outlives its process, is exempt") -
  it outlives its process legitimately for *one* boot, not for ever.
- Ledger: related to CR-52 (dash-release-ai-2 / REL-9, recorded FIXED) - the
  residual hole in that fix.
- Suggested fix: keep the exemption only while the flag belongs to a live
  process: if `owner_nonce != PROCESS_NONCE`, treat a `restart_requested`
  state as "the restart already happened (or was lost)" - clear it to
  `step: done, in_progress: False` on the first `read_state` of a new process,
  rather than returning early. (An alternative is to consume it at STARTUP as
  well as at shutdown.)

### dash-release-jobs-3 - the per-kind fleet cap is advisory: two simultaneous claims both pass it
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/jobs.py:830` (`running =
  db.count_running_by_kind(conn)` in `offers_for_machine`) and
  `dashboard/src/ccsync_dashboard/api.py:9916-9921` (the claim route) /
  `db.py:9088` (`claim_next_job` -> `claim_job`).
- What: the cap (`DASH_JOBS_MAX_RUNNING`) is enforced by counting held jobs at
  OFFER time and incrementing a local counter for the rest of that one pass.
  The claim route recomputes offers and then claims, but the count and the
  compare-and-set are not one atomic act across connections: the CAS only
  guarantees that two machines do not get the SAME job, never that the Nth+1
  job of a kind is refused. `db.claim_job`'s `WHERE state=?` says nothing about
  the cap.
- Failure scenario: cap 4, three `proxy-480p` running. Two machines POST
  `/api/v1/jobs/claim` in the same instant; both read `running=3`, both are
  offered a different queued job, both CAS successfully - five encodes reading
  rushes over SMB, which is exactly the saturation the cap exists to stop. The
  overshoot equals the number of concurrent claims.
- Evidence: read of `claim_job`/`claim_next_job` (no cap predicate anywhere in
  the SQL) plus the claim route, which computes the cap on its own connection
  before the write. Not reproduced - two truly concurrent requests are not
  something I could stage inside the time box, hence PLAUSIBLE.
- Ledger: new.
- Suggested fix: push the cap into the claim's `WHERE` clause (a correlated
  `(SELECT COUNT(*) FROM jobs WHERE kind=? AND state IN (...)) < ?`), which
  SQLite evaluates inside the same write transaction, so the loser simply
  matches no row exactly as it does for a contested id today.

### dash-release-jobs-4 - the channel signature URL is built by string concatenation, so a feed URL with a query string can never verify
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:356`
  (`sig_raw = _fetch_bytes(url + ".sig", cap=8192)`).
- What: the detached signature is fetched at `<feed url> + ".sig"`. The threat
  model explicitly contemplates "an S3 bucket, whatever a customer's outbound
  network reaches"; a pre-signed or CDN-token URL carries a query string, and
  `https://host/channel.json?X-Amz-Signature=...` + `.sig` is a URL that does
  not exist. The failure is a 404 -> `FeedError` -> `last_error`, i.e. the feed
  silently never delivers anything and the site quietly stops receiving builds -
  the exact state REL-11 was written about.
- Failure scenario: a customer whose outbound policy forces the vendor to serve
  `channel.json` from a bucket with a signed URL. Every check fails with
  "answered HTTP 403/404" naming a URL the operator never configured, and
  nothing ever updates.
- Evidence: read of `fetch_and_verify_channel`; `_fetch_bytes` does no URL
  parsing, and there is no test covering a feed URL with a query.
- Ledger: new.
- Suggested fix: split the URL with `urlsplit`, append `.sig` to the PATH
  component and re-assemble with the query and fragment intact (and refuse a
  feed URL with a fragment outright).

### dash-release-jobs-5 - `FeedPoller.start()/stop()` are documented as idempotent but a stopped poller can never be restarted
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:513-522`.
- What: `stop()` sets `self._stop` and joins but never clears `_thread` or the
  event; `start()` returns early whenever `_thread is not None`. So `stop()`
  then `start()` on the same object silently starts nothing, and the docstring
  claims "start()/stop() are idempotent so the lifespan handler can call them
  unconditionally" - which is true of `stop()` and false of `start()`.
- Failure scenario: today `app.py` builds a fresh `FeedPoller` per lifespan, so
  the live blast radius is nil; it bites the first caller that reuses one (a
  reload path, a test harness, or a future "pause/resume the feed" button) with
  a poller that reports itself started and never polls - green while dead.
  `cards_exec.PinnedExecutor.stop()` gets this right (`_stop.clear()` in
  `start()`, `_thread = None` in `stop()`), so the two threads in this
  territory disagree about the same pattern.
- Evidence: read of both classes side by side.
- Ledger: new.
- Suggested fix: copy `PinnedExecutor`'s shape - `self._stop.clear()` at the
  top of `start()`, `thread, self._thread = self._thread, None` in `stop()`.

### dash-release-jobs-6 - the cards tunnel falls back to the agent's self-asserted `name`, which its own docstring forbids
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:257`
  (`body["name"] = agent_name(editor, body.get("machine") or body.get("name") or "")`).
- What: rule 1 of the module ("THE VERIFIED IDENTITY IS THE AGENT'S NAME ...
  never `body.editor`") is implemented as verified-editor + declared machine -
  but when the caller declares no `machine`, the second half falls back to the
  body's own `name`, the `socket.gethostname()` string the rule exists to
  distrust. The editor half is still verified, so this is display spoofing, not
  auth bypass: a holder of a fleet credential can make the cards page's
  away/stale text read `alex/ANYTHING-I-LIKE`.
- Failure scenario: a companion (or anything holding a fleet token) posts
  `{"name": "CREATOR-1"}` with no `machine`; the page shows that machine as the
  live agent even though the call came from elsewhere, which is misleading
  exactly where "which computer is driving Resolve" matters.
- Evidence: read of the route against `agent_name`, which sanitises characters
  but does not otherwise constrain the value.
- Ledger: new.
- Suggested fix: use `body.get("machine")` only, and fall back to the editor
  alone (which `agent_name` already handles) rather than to `name`.

### dash-release-jobs-7 - a feed record whose `platform` is not lower-case is unpublishable from the admin button
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:605`
  (`platform=payload.platform.strip().lower()`) against `:318`
  (`_record_key(r) == (kind, platform, version)`, which does not normalise).
- What: `_valid_records` lower-cases `platform` only when building the recall
  key; `_record_key` keeps the record's own spelling. The admin [ PUBLISH ]
  route lower-cases what the page posts, so a record published as `Windows` or
  `Darwin` would 404 with "no verified feed record ... run Check now first"
  while being visible in `available` (which renders `_record_key` unchanged).
  The auto-publish path is unaffected because it passes `_record_key` through.
- Failure scenario: a vendor tool (or a hand-edited channel) emits a
  capitalised platform; the admin sees the build listed and the button is a
  permanent 404 that tells them to re-check the feed.
- Evidence: read only - I did not find a producer that emits a non-lowercase
  platform today (`tools/publish_feed.py` was outside my territory), hence
  PLAUSIBLE.
- Ledger: new.
- Suggested fix: normalise `platform` in `_record_key` (or in `_valid_records`,
  once) so every consumer of a record agrees about its spelling.

## Coverage note

- I read `ed25519.py` only for its shape and did NOT re-audit the field
  arithmetic against RFC 8032 - `tests/test_packages.py` pins it against the
  companion's copy, and a hand review of curve code in a time box would have
  produced guesses, not findings.
- `cards_wsgi.py` (the `BaseHTTPRequestHandler` -> WSGI shim, Range/206
  streaming) was skimmed, not read line by line. That file is where a
  byte-for-byte 206 bug would live and it deserves its own pass.
- `ytdl.py` was skimmed only (the mount contract, not the ytdl app behind it);
  `cli_tools.py`'s pty sign-in strategies (`_strategies`, the five-minute
  timeout, `_redact`) and `ai_providers.provider_states`/`test_provider` got a
  read for key leakage only. I found no key or token echoed into a response,
  a log or an exception message on the paths I did read - `validate_key` never
  quotes the value, `set_key` logs the provider name only, and `mask()` is
  correct (a value under 12 chars is masked entirely).
- The invariants I checked and found HELD, so nobody re-checks them: the
  release feed's redirect walk is https-only on every hop, credential-free,
  bounded at 5 and closes the raising 3xx response; nothing is believed before
  its signature (channel) and its sha256 (artefact); `min_version_exceeds_version`
  is refused in BOTH `_valid_records` and `store_verified_package` (CR-52);
  every version comparison in the territory is per-dotted-part, so 0.10.0 > 0.9.70
  (`release_trust._version_tuple`, `release_feed._version_sort_key`,
  `dashboard_update.version_tuple` - three copies, all correct and all
  documented as having to agree); `whisper` is absent from
  `db.JOB_PINNABLE_KINDS` and `can_pin` is false without an engine exposing
  `fleet_execute`; `idle_seconds is None` refuses in `policy_refusal` and
  `rank_key` floors an unknown idle at 0 so it can never out-rank a known one;
  `/cards/api/restart` is refused on the rstrip'ed path and `/cards/agent/*`
  404s inside the mount; `stop_engine` runs before the feed poller in the
  lifespan `finally`; `cli_tools` refuses a Codex release with no published
  checksum outright (trust-model-7) and `cli_env` is an allow-list with
  `ANTHROPIC_API_KEY` excluded.
- The suite does not cover: a lease expiring on a cancelled job (finding 1), a
  `restart_requested` state owned by a dead nonce (finding 2), concurrent
  claims against the fleet cap (finding 3), or a feed URL with a query string
  (finding 4).

## OUT OF TERRITORY

- `dashboard/src/ccsync_dashboard/package_store.py:456`: `os.replace(part_path,
  dest_dir / filename)` happens before `insert_companion_package` and the
  commit, so a failed commit leaves a package file on disk with no row (the
  docstring's commit-then-unlink reasoning covers the PRUNED files, not this
  one). Harmless today, but it is the mirror of the case that comment names.
- `dashboard/src/ccsync_dashboard/db.py:9285` (`expire_leases`): a machine that
  is merely switched off earns a `jobs_cooldown` for every job it was holding,
  which is indistinguishable on the why page from a machine with a broken
  ffmpeg. Correct per the comment, possibly wrong per an admin reading it.
- `dashboard/src/ccsync_dashboard/dashboard_update.py:1150` (`restore_backup`):
  `backup_database(candidate, live)` runs `sqlite3.backup()` INTO a database
  the running process holds open in WAL mode; it is invoked from the rollback
  route with the dashboard still serving.
