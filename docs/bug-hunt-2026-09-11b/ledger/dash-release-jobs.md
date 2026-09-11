## The release channel, the pinned worker and the Timeline Cards mount, 2026-09-11 (CR-260)

### CR-260a (dash-release-jobs-1, with res-fleet-4) - stop() then start() ran TWO pollers, and two pinned ffmpeg workers - FIXED (`release_feed.py`, `cards_exec.py`)

`FeedPoller.stop()` set `_stop`, joined with a 5 s timeout and dropped
`self._thread` unconditionally. `threading.Thread.join(timeout)` returns None
either way, so a cycle that outlived the join - `fetch_artifact_to` on a slow
link runs for minutes, a hung socket for a read timeout - left a live thread
with no handle to it. `start()` then saw `_thread is None` and called
`self._stop.clear()`, which is exactly the flag `_run`'s
`while not self._stop.is_set()` loop is waiting on: the old thread finished
its cycle, re-tested a now-cleared event and kept polling, beside the new one.
Two pollers on one object then run `check_now` on independent connections;
under the `auto` policy both pass the "already published" test for the same
record and race into `store_verified_package`, and both stamp `valid_records`
and `db.set_feed_state`. `cards_exec.PinnedExecutor` had the same shape from
the day it was written, and there the revived thread is a SECOND ffmpeg worker
draining the same pinned queue - the one thing §4.4 rule 5 promises cannot
happen on the NAS. Both classes now keep the handle when the join expires (and
say so in the log), and `start()` refuses while a previous thread is alive
instead of clearing the event under it. The join timeouts are named constants
(`POLLER_STOP_JOIN_SECONDS`, `STOP_JOIN_SECONDS`) so a test can reach the
overrun case without sitting out five real seconds. The fix that opened this
(dash-release-jobs-5 of the morning hunt, "stop() then start() really polls
again") is intact: a thread that actually ended is still dropped and restarted.

### CR-260b (dash-release-jobs-2) - the staged half of the SELECTED CARDS block was truncated silently, and its count lied - FIXED (`cards_ai.py`)

`selection_block`'s selected half caps at `MAX_SELECTION_ROWS` and then prints
"...and N more, by id alone: ..." so the model knows the list is partial. The
staged half printed the FULL count in its header ("Staged cards selected on
the shelf (120)") and then rendered 40 rows with nothing at all saying the
other 80 existed. An editor who marquee-selects 120 staged cards and asks for
"the selected staged cards" gets an op naming 40 of them, presented as the
answer to a request about 120. Timeline Cards' own `chat_edit.selection_block`
does not truncate at all, so the two doors disagreed about what the model was
told. The staged branch now carries the same "...and N more, by id alone:"
line, so every id the header counts is in the prompt.

### CR-260c (dash-release-jobs-3 / wire-4) - an older companion's Cards agent lost its machine name, and one editor's two computers became one string - FIXED (`cards_tunnel.py`)

dash-release-jobs-6 (morning) stopped trusting the agent's self-asserted
`name` and took `body["machine"]` only - and added that field to the companion
in the SAME commit (18e69f3, companion 0.9.71). The two halves ship
separately, the dashboard first by house rule, and the field runs
0.9.65..0.9.71 with a Mac on 0.9.70. Every machine below 0.9.71 therefore
registered as the bare editor: leso's iMac and MacBook both became `leso`, in
the away/stale text, in `agent_name`, and in anything the cards server keys by
that name - precisely where "which computer is driving Resolve" is the
question being asked. The anti-spoofing stands: the body's `name` is never the
whole identity and never the editor half. It is now taken as the MACHINE HALF
alone, only when no `machine` was declared, sanitised by the same rule, and
rendered `editor/~HOST` - the `~` says that half is the agent's word and not
ours. `test_the_name_is_the_editor_alone_when_no_machine_is_declared`, which
pinned the degraded string as correct, was rewritten.

### CR-260d (dash-release-jobs-4) - a feed record with a non-canonical kind or platform was dropped with nothing at all to tell the admin - FIXED (`release_feed.py`)

The morning's fix for dash-release-jobs-7 case-folds `_record_key` AND drops
any record whose kind/platform is not already lower-case (folding it would
break the record's own signature, so dropping is right). The drop incremented
nothing, set no `last_error` and added no notice; `db.set_feed_state` still
recorded `ok`, so `alerts._check_feed_stale` stayed quiet. The vendor
publishes `companion`/`Windows` 0.10.0, [ CHECK NOW ] answers ok, the feed
page lists nothing new, the fleet never updates, and the only evidence is one
WARNING in a container log nobody opens - an invisible fault where the
pre-fix behaviour was at least a visible one (listed, then 404 on the button).
`_valid_records` now collects what it refused, and `check_now` writes a
sentence naming the versions into `feed_state.last_error` and returns them as
`rejected`. The check still answers `ok: True`: the channel verified, and this
is a build that cannot be offered, not a feed outage.

### CR-260e (dash-release-jobs-5) - `_signature_url` cannot fetch the signature for the pre-signed URL its docstring was about - FIXED, as a refusal that says so (`release_feed.py`)

The morning fix appends `.sig` to the PATH and carries the query across, which
is correct for a CDN token. For the case the docstring named - "a pre-signed
URL" - it cannot work at all: an S3 SigV4 signature is computed over the
canonical request INCLUDING the object key, so the same `X-Amz-Signature`
against `channel.json.sig` answers 403 SignatureDoesNotMatch. The failure
moved from 404 to 403 and the site still stops receiving builds, with the
comment above the code saying the case was handled. The docstring is narrowed
to query-TOKEN URLs, and `_presigned_hint` now names the cause in the reason
that reaches `feed_state.last_error` and the admin page, so the operator is
not left with a refusal about a URL they never configured. A real fix needs a
second setting (`RELEASE_FEED_SIG_URL`) on `Settings`, which is dash-core's
file: it is under OWED below.

### CR-260f (dash-release-jobs-6 / regression-13) - two different fixes cited "dash-release-jobs-3", and the citations were off by one from -3 onward - FIXED in the code, OWED in the ledger (`release_feed.py`)

The morning hunt's ids are -3 the per-kind fleet cap, -4 the signature URL, -5
the poller. The builder labelled the signature-URL fix `-3` and the poller fix
`-4`, so `grep -rn dash-release-jobs-3` returned two unrelated fixes (the
correct one in `db.py:9334` and `api.py:10321`) and `grep -rn
dash-release-jobs-5` returned none - the audit trail the fix-pass rules
depend on. Both code comments and the two test docstrings in
`test_release_feed.py` are relabelled to -4 and -5, each noting the
correction. The KNOWN_BUGS.md half (CR-242b, CR-242c, the missing entry for
dash-release-jobs-3's `claim_job` change, and that entry's stale "Owner
decisions" line) is OWED to the orchestrator: this brief forbids editing
KNOWN_BUGS.md directly.

### CR-260g (dash-release-jobs-7) - `read_state` writes to disk, so a full or read-only data dir turned a status read into an exception on the boot and shutdown paths - FIXED (`dashboard_update.py`)

`_read_json` is deliberately exception-proof because these files are read on
the boot path, but `read_state` always calls `_heal_orphaned_progress`, which
WRITES through an unguarded `_write_json` - and the new `restart_requested`
branch (dash-release-jobs-2, morning) added a second write site on the path
`finish_restart -> consume_restart_request -> read_state`. On a data dataset
that is full, or read-only after a pool fault, the OSError escaped the
lifespan shutdown: `_exit_process(RESTART_EXIT_CODE)` never ran, the process
exited 0, `deploy/run.sh` did not re-exec, and the code that had just been
applied never started running - with nothing in the state file to say why. The
same OSError 500'd every `GET /api/v1/admin/dashboard-update`. The healer's
two writes now go through `_write_json_best_effort`, which logs and returns:
the in-memory correction is what unwedges the routes, and persisting it is
best effort. Every other `_write_json` caller is unchanged - a staged
`current.json` that cannot be written MUST still raise.

### Verification

Run from `dashboard/` with `.venv\Scripts\python.exe -m pytest <file>`.

- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_feed_check_that_outlives_stop_is_not_revived_by_start -> fails at f1eeb42 ("stop() dropped the handle to a live thread"), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_pinned_tick_that_outlives_stop_is_not_revived_by_start -> fails at f1eeb42 ("stop() dropped the handle to a live worker"), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_the_staged_half_of_the_selection_block_says_what_it_truncated -> fails at f1eeb42 (no "...and 80 more" line), passes now
- tests/test_cards_tunnel.py::test_an_older_companion_keeps_its_own_machine_half_marked_unverified -> fails at f1eeb42 ("assert 'leso' != 'leso'"), passes now
- tests/test_cards_tunnel.py::test_the_name_is_sanitised_and_bounded -> extended for the unverified half; fails at f1eeb42, passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_non_canonical_feed_record_is_reported_and_not_merely_dropped -> fails at f1eeb42 ("a build that cannot be offered left nothing to see"), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_canonical_feed_record_still_clears_the_last_error -> the no-regression half of CR-260d (a clean channel still clears last_error)
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_presigned_feed_url_is_named_as_the_cause_of_the_signature_refusal -> fails at f1eeb42 (the reason is a bare 404 on a URL nobody configured), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_query_token_feed_url_still_derives_its_signature -> the no-regression half of CR-260e (the morning fix keeps working)
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_the_healer_survives_a_data_directory_it_cannot_write -> fails at f1eeb42 (OSError 28 escapes read_state), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_spent_restart_request_is_healed_on_a_full_disk_too -> fails at f1eeb42 (OSError 30 escapes read_state), passes now

Files run (territory only): tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py,
tests/test_cards_tunnel.py, tests/test_release_feed.py, tests/test_cards_ai.py,
tests/test_dashboard_update.py, tests/test_cards_mount.py -> 224 passed, plus
`py_compile` on every file touched.

Reverted-source verification was done by copying the f1eeb42 bytes of the five
source files over the working tree, running the two test files, and copying the
fixed files back. No git state was changed.

### OWED TO ANOTHER TERRITORY

- dash-core: `dashboard/src/ccsync_dashboard/settings.py`: add a
  `release_feed_sig_url: str = ""` setting (env `DASH_RELEASE_FEED_SIG_URL`),
  read by `release_feed.fetch_and_verify_channel` when set instead of
  `_signature_url(url)`. This is the real fix for dash-release-jobs-5 (a host
  where the two URLs cannot be derived from one another, i.e. any pre-signed
  object URL). Dashboard only, no deploy ordering. My side is safe without it:
  the refusal now names the cause instead of naming a URL nobody configured.
- dash-collector-alerts: `alerts.py`: CR-260d writes the rejected-record
  sentence into `feed_state.last_error`, which `_check_feed_stale` already
  reads, so a refused build now raises that notice. If the operator would
  rather have its own kind (`feed_record_rejected`, with the version and "the
  feed has to republish it" as the next action), that is one `ALERT_KINDS` row
  plus its writer. Dashboard only.
- server-tools: `tools/publish_feed.py:810`: `--from-manifest` assigns
  `args.platform` from the manifest AFTER argparse, so the
  `choices=sign_release.PLATFORMS` guard does not cover that path - it is what
  makes a non-canonical record publishable at all (the cause behind CR-260d).
  Fold the platform to lower case (or re-validate it) before it is signed.
  Vendor-side tool, no fleet deploy.
- orchestrator (KNOWN_BUGS.md, forbidden to me by rule 7): relabel CR-242b
  from `dash-release-jobs-3` to `dash-release-jobs-4`, CR-242c from
  `dash-release-jobs-4` to `dash-release-jobs-5`, add the missing one-line
  entry for the real dash-release-jobs-3 (the per-kind fleet cap moved into
  `db.claim_job`'s compare-and-set, `db.py:9334`, wired from `api.py:10321`),
  and correct that entry's "Owner decisions" line, which still says the cap
  "is not fixed here". `docs/bug-hunt-2026-09-11/ledger/dash-release-jobs.md`
  lines 33, 44 and 105-108 carry the same three errors.

### Deploy ordering

Every change here is dashboard-side and needs no companion change. CR-260c is
written FOR the deploy window (dashboard first, companions behind): a 0.9.71
companion sends `machine` and is unaffected; anything from 0.9.65 up gets
`editor/~HOST` instead of the bare editor. When the whole fleet is on 0.9.71
the `~` form stops appearing on its own.

### Owner decisions

- CR-260c renders the unverified machine half as `editor/~HOST`. The `~` is
  mine, chosen so the cards page can show a legible computer name without
  presenting a self-asserted string as verified. The alternative the hunter
  offered - leave it degraded and document it - is one line to revert
  (`cards_tunnel.agent_name`).
- CR-260d puts the rejected record into `feed_state.last_error`, which means
  the existing feed-stale notice fires for it. That is deliberate (a build
  that cannot be offered should be a PROBLEM THE SERVER FOUND), but it does
  mean a malformed vendor record shows on the home page as a feed problem
  until the feed republishes it. A dedicated notice kind would read better;
  it is OWED to dash-collector-alerts above.
- CR-260a makes `start()` refuse while a previous thread is alive, rather than
  waiting for it. A poller whose cycle is wedged on a socket therefore stays
  the only poller until that cycle ends, and the log says so. Waiting would
  block the lifespan; killing it is not possible in Python.

### Hand-off wave

The three OWED lines routed back to this territory in `HANDOFFS.md`
("## dash-release-jobs"). All three done; nothing declined.

#### CR-260h (res-fleet-3, from dash-mounts-ui) - the refused-revert banner could never have rendered - FIXED (`dashboard_update.py`)

dash-mounts-ui's CR-259a writes `revert_refused_reason` / `revert_refused_from`
into `current.json` when the boot selector refuses to revert into a tree whose
schema is older than the live database, and added a banner for them to
`templates/partials/admin_dashboard_update.html`. That banner is fed by
`dashboard_update.status()`, which rebuilds `current` with a FIXED key set of
four - so the two new keys were dropped on the way out and the banner was dead
code from the moment it was written, on the one page that is supposed to say
why this container is still running the applied tree. Both keys are in the
dict now, "" when absent, which is also what a pre-fix `current.json` renders
as. This is the API half of res-fleet-3 as well: a notice or alert kind for
"booting the image while current.json names a version" can now read the
refusal out of `GET /api/v1/admin/dashboard-update` instead of opening
`current.json` itself.

#### CR-260i (dash-release-jobs-5's real fix, from dash-core) - the signature URL can be configured instead of derived - FIXED (`release_feed.py`)

CR-260e narrowed `_signature_url`'s promise to query-TOKEN URLs and made the
refusal name the pre-signed case; the actual escape hatch needed a setting,
which is dash-core's file. `fetch_and_verify_channel` now takes a third
argument, `sig_url`, and uses it verbatim when it is non-blank - no
derivation, and no `_presigned_hint` appended, because advising an operator to
configure the thing they have just configured is worse than saying nothing.
`check_now` reads it with `getattr(settings, "release_feed_sig_url", "")`, so
a Settings object that predates dash-core's half (a rollback to an older tree,
a test double) keeps deriving exactly as before rather than raising on the
boot-adjacent poll path. Blank is the shipped default and every configured
site today is unchanged.

#### CR-260j (regression-11, from dash-api) - `why` said "cannot do this kind of work" about a machine that was telling us why - FIXED (`jobs.py`)

comp-ytdl-jobs-3 (2026-09-11) landed the companion half of "say WHY this
computer has no ffmpeg": the cause, the consecutive-failure count and a tray
line. On the dashboard the block was validated by `YtdlpSidecarIn`, stored
whole into the `ytdlp:` meta blob by `_store_ytdlp_state`, and read by NOBODY.
So a Mac whose sidecar install fails on an SSL CA problem reports
`ffmpeg: false`, an admin queues a `proxy-480p` job, and
`GET /api/v1/jobs/{id}/why` - the page whose entire reason for existing is
"unschedulable, and why" - answered "ffmpeg is not available on this
computer", which reads as "nobody ever set that machine up" for a machine that
is trying to set itself up and failing for a nameable reason.

`jobs.sidecar_notes(conn)` reads every stored verdict in ONE fleet-wide query
(the Ctx rule `alerts.py` states; `explain` calls it once, not once per
machine), and `jobs.sidecar_cause(note, requires, capabilities)` turns one
into a sentence under three conditions, all of which matter: the check must
have FAILED (`ok is False` or `action == "failed"` - an absent verdict is
never "it is fine"), the job must require one of the tools that check covers,
and that tool must actually be missing from the capabilities. Without the
third, a machine refused for a `mount` or a VRAM floor would be blamed on an
unrelated `deno` failure. The sentence rides the per-machine line's `why` AND
its own `sidecar_cause` key (so a page can render it beside `cap_ffmpeg`
without parsing a sentence apart), and the job-level summary names the first
machine that has one, because that line is what an admin reads before the
list. A bad meta row is skipped, never raised.

### Hand-off wave: Verification

Run from `dashboard/` with `.venv\Scripts\python.exe -m pytest <file>`.

- tests/test_dashboard_update.py::test_status_carries_a_refused_revert_out_of_current_json -> fails before the fix (KeyError: the fixed key set dropped it), passes now
- tests/test_dashboard_update.py::test_status_says_an_empty_string_when_no_revert_was_refused -> the no-regression half (a current.json with no refusal renders "", never a missing key)
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_declared_signature_url_is_fetched_instead_of_the_derived_one -> fails before the fix (the third argument does not exist and the derived URL 404s), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_check_now_reads_the_declared_signature_url -> fails before the fix (check_now fetched the derived .sig and 404'd), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_settings_without_the_new_field_still_derives_the_signature_url -> the getattr no-regression half
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_why_names_the_sidecar_cause_when_that_is_why_ffmpeg_is_missing -> fails before the fix ("ffmpeg is not available on this computer" and nothing else), passes now
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_an_unrelated_sidecar_failure_does_not_explain_a_mount_refusal -> the third condition: a deno failure never explains a mount refusal
- tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py::test_a_sidecar_that_succeeded_explains_nothing -> a healthy verdict on a machine with no ffmpeg still reads as "nobody set it up"

Files run (territory only): tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py,
tests/test_dashboard_update.py, tests/test_release_feed.py, tests/test_jobs.py,
tests/test_jobs_backpressure.py, tests/test_jobs_scheduling.py,
tests/test_jobs_machines.py, tests/test_jobs_contract.py,
tests/test_jobs_ranking.py, tests/test_jobs_cancel.py,
tests/test_jobs_pinning.py, tests/test_jobs_retry.py,
tests/test_bug_hunt_2026_09_11_dash_api_jobs.py -> 388 passed, 1 skipped, plus
`py_compile` on every file touched.

Reverted-source verification: the three hand-off edits were undone in place
(the wave-1 fixes left standing, since the hunt's baseline f1eeb42 predates
them) and the two test files run - 7 failed, 74 passed - then the fixed files
were copied back and everything re-run green. No git state was changed.

### Hand-off wave: OWED TO ANOTHER TERRITORY

- dash-mounts-ui: nothing blocking. Both halves of what was asked are
  available now: `dashboard_update.status()["current"]` carries
  `revert_refused_reason` / `revert_refused_from`, and
  `jobs.sidecar_notes(conn)` + `jobs.sidecar_cause(note, requires, caps)` are
  public, so the jobs machine list can print the cause beside `cap_ffmpeg`
  without re-reading the meta blob.
- dash-core: `settings.release_feed_sig_url` still has to exist for the new
  argument to be reachable from a deployment (`DASH_RELEASE_FEED_SIG_URL`).
  My side is complete and inert without it - `getattr` with a "" default, and
  "" keeps the derivation. Dashboard only, no deploy ordering.
- dash-collector-alerts: the `ytdlp.sidecar` ALERT_KINDS row is still theirs
  (their own hand-off line). `jobs.sidecar_notes` is the fleet-wide read if
  they would rather not add a second query.
- server-tools: `tools/publish_feed.py:810` (the `--from-manifest` platform
  bypassing argparse `choices`) is unchanged - routed to them in this same
  wave.

### Hand-off wave: Owner decisions

- A declared `release_feed_sig_url` suppresses the pre-signed hint on a
  failure. The reasoning is that the hint is advice to configure the setting;
  once it IS configured, the refusal is about the URL the operator typed. If
  the owner would rather always see it, that is one conditional in
  `fetch_and_verify_channel`.
- The sidecar cause is appended to the per-machine `why` with " - " and named
  once in the job-level summary (the first machine that has one, not all of
  them), on the grounds `_blocked_summary` already states: one sentence an
  admin can act on, with the list underneath for the rest.
