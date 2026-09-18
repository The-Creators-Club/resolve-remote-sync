# Ledger entry for KNOWN_BUGS.md (2026-09-18 fix pass, the ten highs)

Written by the builder; the orchestrator copies it into `KNOWN_BUGS.md` and
bumps the versions. Nothing below was committed and no version was changed.

## The ninth hunt's ten highs: a deletion that came back, a refresh that never ran, and a handler that blocked the loop (CR-282, 2026-09-18)

The ten HIGH findings of `docs/bug-hunt-2026-09-18.md`, fixed in the order
that document gives them, by one builder, against `214869b`. Six of the ten
are in code the whole fleet took on 2026-09-17 (companion 0.9.74 / dashboard
0.7.49); three are in the hand-moves feature (CR-268); one is the CI red that
blocks the vendor feed. Every fix carries a regression test that fails on the
unfixed source.

### CR-282A (comp-sync-1 = dash-api-1) - lane B put a deleted file back at the path it had just trashed it from, every pass, and hid the event from the breaker - FIXED (sync/rclone_lane.py, sync/server_locate.py, dashboard/locate.py)

CR-268b's `_relocate_trashed` read "the server's inventory holds exactly one
place for this (basename, size)" as "it was moved there", and never asked
whether that place was the path this pass had just trashed the file FROM.
`nas_media` is the last COMPLETED walk, so for the whole staleness window a
file genuinely deleted on the NAS is still listed at its old path - and when
a walk keeps collapsing it is listed there for ever, because DASH-5's
refusal deliberately keeps the old rows and never advances `tree_sig`. The
companion rebuilt exactly the path rclone had just emptied and renamed the
file back into it; the next pass trashed it again. The deletion never landed,
and because every restore counted as a relocation that
`LaneBBreaker._discount_relocations` subtracts, a NAS folder wiped by
accident raised nothing at all. `docs/HAND_MOVES_ON_THE_SERVER.md` §4a says
"found ELSEWHERE"; the code did not implement the word.

Both ends are fixed. The companion resolves every candidate place to a local
path and drops any that equals the path the file came out of (NFC-folded and
normcased - `_is_same_local_path`, `_trashed_from`); a file whose only place
is its own old path is a deletion again, is not added to
`_server_relocated_keys`, and so is counted by the breaker. A place that is
the old path BESIDE a real new one is dropped rather than read as ambiguity,
so a walk that caught the copy but not the delete still follows the move. The
dashboard excludes projects whose `nas_inventory_state.last_error` is
non-empty from the locate join and names them in a new `unreadable` key, so
the asking machine can log "the server could not tell for N project(s)".
Only `last_error` is tested, never the age of `walked_at`: a project whose
`tree_sig` has not changed is legitimately not re-walked, and an age test
would exclude healthy projects and turn every hand move back into a deletion.

Tests: `companion/tests/test_rclone_lane.py` (three cases: the own-path
answer, the old path beside a real new one, a differently spelled own path),
`companion/tests/test_bug_hunt_2026_09_18_companion.py` (the `unreadable`
key parsed, and ignored when the dashboard does not send it),
`dashboard/tests/test_locate.py` (a refused walk is not a destination, a
healthy project is unaffected, a readable project still answers beside an
unreadable one).

### CR-282B (res-companion-2) - a move lane B had already followed left Resolve pointing at the old path, and the command that followed said "nothing at the old path" - FIXED (file_moves.py, sync/rclone_lane.py, app.py)

Lane B renames the local copy itself on the server's locate answer, minutes
before the dashboard's own detection delivers the same move as a `file_moves`
command. `apply_move` then found the source gone, its resume branch needed an
intent row lane B had never written, and it answered `ok` with `paths=None` -
so `app.py` skipped `_relink_moved_result` entirely and recorded the move as
done. Every clip under a hand-moved folder was Media Offline in that editor's
Resolve while the MOVES history said the machine had followed, and after the
follow `expected_proxy_paths(<old original path>)` no longer finds the proxy,
so the 120 s relink pass could not heal it either.

Lane B cannot write an intent row (the move has no id yet - the dashboard
mints it later), so it writes what it does know: `FileMoveLedger`
`record_relocation(old_local, new_local)`, in the same ledger file, aged out
after a day and capped at 500 entries. `apply_move` accepts that as the
evidence its resume branch needs and answers with the pair of paths, so the
relink runs. Both halves of the note are checked: a machine that merely
DOWNLOADED the file at the new path wrote no note and still answers "nothing
at the old path on this machine", which is what keeps every machine that
syncs the destination from claiming it made the move. Lane B relocates
`**/Proxy/**` only, so this covers exactly what lane B moves.

Test: `companion/tests/test_bug_hunt_2026_09_18_companion.py` - the real lane
B follows a move through a real `ServerLocator` answer, and the real
`apply_move` is then handed the same ledger object the companion wires to
both.

### CR-282C (comp-broll-tiers-1 = res-companion-1) - a stand-in whose download finished after the page stopped polling was never ledgered - FIXED (broll_server.py)

`fetch_standin` writes the 1080p preview to the ORIGINAL's local path with an
asynchronous rclone job on a daemon thread with no callback, and the ledger
row was written only by the request that observed `state == "done"`. Close
the tab, background it, restart the companion or simply switch to Resolve
after the "syncing 40%" toast, and the preview's bytes land under a 6K name
with no ledger entry at all: the next Send to Resolve takes the
import-original path, `broll_fetch` calls the original present for ever, the
relink pass never learns the geometry is the stand-in's, and a render on that
machine renders 1080p H.264 under a 6K name.

The intent row is now written BEFORE the fetch starts, with no size (a
non-int size reads as "still a stand-in", the conservative direction, and the
real original arriving later falsifies the row) and with `upgrade=None`, so
the background upgrade lane cannot start fetching an editing proxy for a
stand-in that is still downloading. The done branch rewrites the row with the
real size and the upgrade state; a refused fetch, and a file that vanished
between "done" and the import, retire it with `forget()` rather than leaving
a row for a file that never arrived.

Tests: `companion/tests/test_broll_insert_tiers.py` - the assertion that
pinned the defect (`assert broll_standins.all() == []` on the downloading
path) is inverted, and a new test lands the bytes after the page has stopped
polling and asserts the ledger knows.

### CR-282D (comp-resolve-1) - the stand-in geometry refresh never ran, and reported success every 120 s - FIXED (resolve_bridge.py, proxy_relink.py)

Phase 3's one mechanism is `ReplaceClip(<the same path>)`, the only call that
makes Resolve re-read a file that changed underneath a clip. `apply_relinks`
called `resolve_bridge.replace_clip`, which short-circuits with "Already
linked" whenever the requested path equals the clip's own - which for a
refresh is always. Nothing was ever re-read, `refreshed += 1` and an INFO
line said it had been, and the same op was planned again on every pass, each
one spending one of the 8 `allow_automatic` grants a day, so genuine proxy
relinks were rate-limited out for the rest of the day.

`replace_clip` grows `force=False`. A forced call skips the short-circuit and
really calls ReplaceClip; success is a GEOMETRY change (`Frames` /
`Resolution` re-read), never the File Path, which is vacuously equal to what
was asked for - so a forced call whose ReplaceClip raised every time reports
failure, not success. It takes no save point and writes no undo-journal
entry: old_path == new_path, so the journal's inverse edit is this same call
again, and a SaveProject + ExportProject on every 120 s pass is part of the
cost the finding is about. The answer carries `changed` beside `ok`: a
refresh Resolve took that moved nothing is not a failure and not a refresh,
and `apply_relinks` remembers that verdict (CR-282E's memory) instead of
re-planning the op for ever. Every other caller of `replace_clip`
(fixer, popup, file moves, music worker) keeps the short-circuit unchanged.

Tests: `companion/tests/test_bug_hunt_2026_09_18_companion.py` - the REAL
`replace_clip` against a fake media pool item (ReplaceClip called, geometry
success, the all-raised case refused, the no-change case reported), plus
`apply_relinks` asking for `force=True` and not counting a no-change refresh.

### CR-282E (comp-resolve-2 = res-companion-3) - the geometry check ffprobed every archive clip, whole file, every 120 s - FIXED (proxy_relink.py, app.py)

`_geometry_disagrees` ran `ffprobe -count_packets` - a full demux, 60 s
timeout, serial, on the media-tree thread - against every in-tree archive
clip whose original was present and was not a ledgered stand-in, cached per
pass only. On the wired rig the archive IS the pool and every original IS
present: fifty 2 GB clips is about 100 GB read off the SMB share every two
minutes, competing with lanes A and B for the same link, and the lane
watchdog restarts the thread mid-probe, so neither the library walk nor the
relink ever completes. The rate limiter cannot bound it: `allow_automatic` is
consulted only after `if not ops: return`.

The cheap questions are asked first, in order: a verdict already reached about
these exact bytes; the stand-in ledger's `is_stale` (which nothing called),
free and conclusive when it answers; a HEADER-only estimate (`probe_video`,
duration x fps, one open) which settles the clear-cut case; and only then the
exact packet count. Every answer is remembered per (file, mtime, size, the
frame count the CLIP believes), in process, so an agreeing clip is never
asked twice and a file whose bytes change - the event this feature exists to
notice - is asked again at once. The ledger is a short-circuit and never the
test, because on the wired rig it is empty by construction
(proxy-tiers-4). While a probe run IS needed the media-tree heartbeat is
stamped per clip (`on_probe` -> `_stamp_media_tree_heartbeat`), so a slow
serial probe run no longer reads as a wedged thread to LaneWatchdog.

Tests: `companion/tests/test_bug_hunt_2026_09_18_companion.py` (probed once
over five passes, asked again when the bytes change, the header answer
skipping the demux, a disagreeing header still paying for the count, the
ledger answering free of charge, the heartbeat stamped around the probe) and
an autouse reset in `companion/tests/test_proxy_relink_standins.py`, which
uses one path and one fake stat throughout.

### CR-282F (dash-api-2 = dash-db-3 = dash-core-2) - the database-busy handler did a blocking 5 s write on the event loop, under the contention it was reporting - FIXED (dashboard/app.py)

`unhandled_error` is `async def`, so on a `--workers 1` container its body
runs ON the event loop - and the branch that gets there most is the one whose
precondition is that somebody has held the write lock longer than the busy
timeout already. Opening a second connection there and writing through it
blocked the whole loop for another busy timeout (5.4 s measured against a
held `BEGIN IMMEDIATE`) and then raised `database is locked` itself,
swallowed: every companion report and every htmx poll stalled behind the
handler, and the `db_busy` notice the 2026-09-17 rework exists to write was
precisely the one that never got written.

Both branches now record through one helper that runs in the threadpool and
opens its connection with a 250 ms busy timeout instead of 5 s. Losing a
notice to contention is the point of the short timeout, and it is logged. The
503 answer itself never waits on the database.

Tests: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py` - the record
runs on a different thread from the `async` route that raised (both
branches), and with a real `BEGIN IMMEDIATE` held the 503 comes back in well
under the busy timeout.

### CR-282G (res-fleet-1) - the pinned-job executor was never started, and jobs were still pinned into a queue nothing drains - FIXED (dashboard/app.py, cards_exec.py, alerts.py)

`PinnedExecutor.start()` was correctly un-gated for the lazily built engine
pool, but its caller still read `if executor.available():`, which at boot asks
a pool with no engines and gets None. The thread was never created and
`release_pinned_jobs()` never ran - while `jobs.can_pin` asks the same object
later, after an editor has opened an episode, and answers true. A spent
`proxy-480p` job went `pinned` with no worker, was not `abandoned`, and
DDIAG-6 could not see it: its two shapes need "not mounted" or a non-empty
`claimed_machine`. The boot log line said "fleet jobs are never pinned here:
Timeline Cards is not mounted", which was untrue.

The release and the start are now gated on the MOUNT
(`app.state.cards_mounted`), not on `available()`; `start()` is already safe
with no engine, because its loop returns at once per tick. `why_not()`
distinguishes "no episode is open yet" from "not mounted", so the boot line
is true. `cards_exec.is_running()` is a module-level fact (the
`mount_status` pattern, because the check runs on the collector thread with
no app object) and DDIAG-6 has a third shape: pinned rows, Cards mounted, no
drain thread in this container.

Tests: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py` - the lifespan
is driven with a mounted Cards whose pool has no engine and the executor must
start (and the flag must come down on shutdown), the boot sentence, and the
new DDIAG-6 finding appearing and clearing.

### CR-282H (dash-cards-1) - an agent whose editor is in no episode long-polled in a hot loop - FIXED (cards_tunnel.py)

Phase 1a made `/cards/agent/pending` answer a note IMMEDIATELY when `_routed`
finds no engine for that editor. The companion's `pull_loop` has no sleep of
its own on a 200 - its pacing was always this route's 25 s hold - so every
machine with the cards role on issued that GET continuously, from every
container restart until somebody opened an episode, each request a token
lookup plus an identity verify plus a barred-account query on a single-worker
dashboard. Before the engine pool this path raised and the loop's own backoff
caught it; the pool turned the exception into a 200.

The refusal now honours `wait`: an interruptible poll (half-second steps) on
a route that stays a blocking `def`, so it is one threadpool worker asleep
rather than the event loop. An episode opened mid-hold attaches the agent
within a step, and the engine is then asked for what is LEFT of the wait, not
for a second full one - the companion's read timeout is the wait plus its own
margin. Dashboard-only: the answer's shape is unchanged, so no companion
needs republishing. `dash-cards-8` (the honest-signal half) is untouched.

Tests: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py`, with an
injected clock so the 25 s hold costs the suite nothing: the full hold, the
early wake with the remaining wait passed on, and `wait=0` answering at once.

### CR-282I (wire-1) - a non-409 refusal of `/items/{uid}/uploaded` wedged the item in `uploading` for ever - FIXED (broll_ingest.py)

`_pump_uploads` handled 200 and 409 and logged everything else. The item kept
`uploading` with every rel landed, so the next pump recomputed `missing = []`
and posted the identical body again, with no attempt counter and no ceiling,
while the batch lease was heartbeated and this machine 409ed every later drop
on it. This week the server grew the first non-409 refusals of that route
(`400 wrong_edit_proxy`, `400 outside_root`), whose own comments say no retry
can make them right, and the companion had no reader for either.

A 4xx is now terminal: the item fails with the server's own sentence
(`_detail_of`, or the new `_reason_of`) and releases its share of the batch.
Anything else - a 5xx, a connection-level refusal - is a counted attempt on
the 409 branch's `upload_attempts` and `MAX_UPLOAD_ATTEMPTS`, so a server
that is down for an hour costs a retry and a server that is broken ends the
item instead of wedging it. `wire-2` is deliberately not fixed here, and the
5xx path is what keeps a busy-database 500 or 503 retryable, so fixing it
later moves no loss.

Tests: `companion/tests/test_bug_hunt_2026_09_18_companion.py` drives the
REAL pump with the server's own refusal body; `broll/web/tests/test_fleet_
ingest.py` gained one assertion pinning the sentence beside the reason, so
the two ends of the wire cannot drift.

### CR-282J (ytdl-web-1) - the ytdl/web suite was red from today on a hard-coded date, and red CI blocks the vendor feed - FIXED (ytdl/web/tests/test_api.py)

`test_health_reports_how_old_the_running_yt_dlp_is` monkeypatched the running
yt-dlp to the literal `2026.08.27` and asserted it was not stale against a
21-day limit computed from `date.today()`. It held until 2026-09-17 and
failed from 2026-09-18 for ever. The `ytdl/web -- pytest` CI step has no
`continue-on-error` and `tools/publish_latest.py` publishes only the newest
GREEN run on `main`, so the vendor feed could not take any commit made after
2026-09-17. Both versions are now derived from the clock (`today - 1 day`,
`today - (YTDLP_MAX_AGE_DAYS + 1)`), so the test pins the rule and cannot rot
in either direction if the limit is changed.

Swept the rest of the tree for the same shape: no other test compares a
literal date against `date.today()` / `datetime.now()`. The other literal
yt-dlp versions in `ytdl/web/tests` are compared against the configured
fleet FLOOR, which only a deliberate change moves.

### Verification

- companion/tests/test_rclone_lane.py::test_the_only_place_is_the_path_it_was_trashed_from_so_it_stays_deleted -> fails at 214869b, passes now
- companion/tests/test_rclone_lane.py::test_the_old_path_beside_a_real_new_one_still_follows_the_move -> fails at 214869b, passes now
- companion/tests/test_rclone_lane.py::test_a_differently_spelled_own_path_is_still_the_own_path -> fails at 214869b, passes now
- companion/tests/test_rclone_lane.py::test_the_projects_the_server_could_not_read_are_carried_and_logged -> fails at 214869b, passes now
- dashboard/tests/test_locate.py::test_a_project_whose_walk_was_refused_is_not_a_destination -> fails at 214869b, passes now
- dashboard/tests/test_locate.py::test_a_readable_project_still_answers_beside_an_unreadable_one -> fails at 214869b, passes now
- companion/tests/test_bug_hunt_2026_09_18_companion.py::test_the_move_command_after_lane_b_followed_it_still_relinks_resolve -> fails at 214869b, passes now
- companion/tests/test_broll_insert_tiers.py::test_a_download_in_flight_answers_the_page_the_shape_it_understands -> fails at 214869b (it pinned the defect), passes now
- companion/tests/test_broll_insert_tiers.py::test_a_download_that_finishes_after_the_page_gave_up_is_still_ledgered -> fails at 214869b, passes now
- companion/tests/test_bug_hunt_2026_09_18_companion.py::test_the_refresh_really_calls_replace_clip_on_the_clips_own_path -> fails at 214869b (no `force`, and ReplaceClip is never called), passes now
- companion/tests/test_bug_hunt_2026_09_18_companion.py::test_a_clip_that_agrees_is_probed_once_and_never_again -> fails at 214869b (five probes), passes now
- dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py::test_the_busy_notice_is_written_off_the_event_loop -> fails at 214869b, passes now
- dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py::test_a_held_write_lock_does_not_make_the_503_wait_for_it -> fails at 214869b (waits the full busy timeout), passes now
- dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py::test_the_pinned_executor_starts_even_though_no_episode_is_open -> fails at 214869b, passes now
- dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py::test_a_pinned_job_with_no_worker_running_is_a_finding -> fails at 214869b, passes now
- dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py::test_an_agent_in_no_episode_is_held_for_the_wait_it_asked_for -> fails at 214869b, passes now
- companion/tests/test_bug_hunt_2026_09_18_companion.py::test_a_refusal_no_retry_can_fix_ends_the_item_and_says_why -> fails at 214869b (the item stays `uploading` for ever), passes now
- ytdl/web/tests/test_api.py::test_health_reports_how_old_the_running_yt_dlp_is -> fails at 214869b from 2026-09-18 onwards, passes now and on every later day

### Deploy order

- **The dashboard first, then the companions** (CR-282A). The dashboard's
  half of the locate wire is additive (`unreadable`) and a 0.9.74 companion
  ignores it; the companion's own-path exclusion works against a 0.7.49
  dashboard. Neither end needs the other, but the dashboard's exclusion is
  the half that stops the resurrection fleet-wide in one deploy, including
  for machines that have not upgraded.
- CR-282F, CR-282G, CR-282H are dashboard-only and need no companion
  release. CR-282H deliberately changes no answer shape.
- CR-282B, CR-282C, CR-282D, CR-282E, CR-282I are companion-only.
  CR-282I reads a refusal the server already sends today, so no server
  deploy is owed with it.
- CR-282J is CI only, and it must land before any commit can reach the
  vendor feed.

### Owner decisions

- **CR-282A: `last_error` only, not the age of `walked_at`.** The brief
  allowed excluding stale walks too. The verifier's caution is the reason it
  was not done: a project whose `tree_sig` is unchanged is legitimately not
  re-walked, so an age test alone would exclude healthy projects and turn
  every hand move back into a deletion. If the owner wants the age test as
  well, it needs its own signal (last ATTEMPT, not last successful walk).
- **CR-282B: the evidence is a note lane B writes, not "src gone and dest
  present".** The verifier suggested accepting the bare filesystem shape.
  That would make every machine which syncs the DESTINATION project - and
  which merely downloaded the file there - answer "I moved it" and run a
  relink for a path it never held. The note costs one line in the ledger
  file and says who actually moved what.
- **CR-282D: a forced refresh writes no undo-journal entry and takes no save
  point.** An entry whose old_path equals its new_path undoes nothing, and
  the save point is a SaveProject plus an ExportProject on a pass that runs
  every 120 s. If the owner wants a record of refreshes, it should be its own
  journal kind rather than a replace-clip entry that cannot be replayed.
- **CR-282E: the probe memory is in process, not on disk**, following
  `_REFUSALS`' own reasoning in the same module ("a blacklist persisted to
  disk turns one bad night into a permanent refusal"). A restart re-asks
  every clip once.
- **CR-282I: a 4xx fails the item, and the editor sees the server's own
  sentence.** The alternative (park it for a human) has no UI to park it in
  today, and a wedged batch is what the finding is about.
