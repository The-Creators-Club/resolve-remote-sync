# Wave 2 ledger: d-cards

Regression tests for this chunk: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-cards.py`
(19 tests). Proof they fail on HEAD: a scratch mirror of `dashboard/` with the
nine d-cards files replaced by `git show HEAD:...` ran 17 failed / 2 passed (the
two that pass on HEAD are guards: "a playhead moved in Resolve counts" and "a
live machine is untouched"). On this tree: 19 passed.

Tests run (dashboard venv, from `dashboard/`):
`python -m pytest tests/test_bug_hunt_2026_09_24_w2_d-cards.py tests/test_cards_pool.py tests/test_cards_mount.py tests/test_cards_tunnel.py tests/test_cards_ai.py tests/test_cards_page_prefix.py tests/test_cards_picker.py tests/test_cards_capability.py tests/test_broll_mount.py tests/test_music_mount.py tests/test_broll_fleet_stamp.py tests/test_music_fleet_stamp.py tests/test_jobs*.py tests/test_bug_hunt_2026_09_11_dash_api_jobs.py tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py`
-> 558 passed, 6 skipped (+19 new); `tests/test_alerts.py tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py tests/test_bug_hunt_2026_09_18_dashboard.py tests/test_hand_off_2026_09_11b_dash_mounts_ui.py` -> 143 passed.

Skew / deploy order for the whole chunk: dashboard only. No schema change, no
companion change, no new wire key. One new `reason_code` value
(`machines_not_reporting`) on `GET /jobs/<id>/why`; Timeline Cards' client acts
on `schedulable` only (checked `multicam_pipeline/cards/library_engine.py`,
`fleet_jobs.py`), and alerts.py's starved check ignores codes it does not map.
The agent routes answer exactly as before; only which engine answers changed.

## bug-dash-cards-jobs-1 - A double slash walks past CardsGate: `/cards/p/<slug>//api/root` reaches `engine.set_root()`
- Status: FIXED
- Verified as: CONFIRMED medium (med-06). Reproduced on HEAD through the real stack (create_app -> CardsDispatch -> CardsGate -> a2wsgi -> cards_wsgi -> fake BaseHTTPRequestHandler, Python 3.12.10): `POST /cards/p/<slug>//api/root` answered `{"ok": true, "path": "/api/root"}`, i.e. the handler dispatched it. `//agent/state` on a session reached the page's agent protocol the same way.
- Fix: `dashboard/src/ccsync_dashboard/cards.py` new `_gate_readings()` (below `CardsGate`): every sub-path is checked raw, with runs of `/` collapsed, and `posixpath.normpath`-resolved; `CardsGate.__call__` iterates those readings for both BLOCKED_PATHS and AGENT_PREFIX. The forwarded path is untouched (match only).
- Regression test: `test_a_double_slash_does_not_walk_past_the_gate` (`//api/root`, `///api/root/`, `/./api/root`, `//api/./root`, `//api/restart`, `//agent/state`; engine.posts stays empty, restart never reached, `/api/plan` still served) and `test_the_gate_readings_keep_the_raw_path_and_add_the_handlers` - fail on HEAD because the gate matched the raw `//api/root` only.
- Tests run: see top.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-cards-jobs-2 - An agent's traffic follows whichever of its editor's devices made the LAST request, so pending and result land on different engines
- Status: FIXED
- Verified as: CONFIRMED medium (med-06). Read `cards_pool.note_visit` (overwrote `_where[editor]` on every served request), `cards_tunnel._routed` (each of state/pending/result routed alone), and the other repo's `agent.py:1144-1224` (`agent_result` refuses any id that is not its `_req`; the next poll declares `_req` lost). Reproduced on HEAD: pending from A, a page request into B, then result -> B answered "that request is no longer open".
- Fix: (1) `cards_pool.py`: `EnginePool._handed` + `note_handed(editor, engine, id)` / `handed_engine(editor, id)` / `slug_of(engine)`; `cards_tunnel.cards_agent_pending` records which engine handed out an edit with an `id`, and `cards_agent_result` goes back to that engine first (falls back to the old routing when the id is unknown or that episode closed). Cleared by `drop()` / `stop_all()`. (2) `_where` is now stable: `note_visit(slug, editor, enter=True)`; the dispatcher passes `enter` only for a page navigation (GET of the page root wanting HTML, the same test `on_enter` already used), and a non-navigation request moves the agent only if the attached episode has had no PAGE request from that person for `WHERE_STALE_SECONDS` (120 s; `Entry.page_seen`, separate from `seen` which also takes agent stamps). So two open pages no longer flip the agent several times a second: it follows the last episode opened, which is the design rule (CARDS_TWO_PROJECTS).
- Regression test: `test_a_result_goes_back_to_the_engine_that_handed_the_edit_out`, `test_a_polling_page_does_not_drag_the_agent_off_the_episode_just_entered`, `test_a_navigation_through_the_dispatcher_is_what_moves_the_agent` - fail on HEAD because the result routed to B, and `note_visit` had no `enter` so every poll moved `_where`.
- Tests run: see top (test_cards_pool / test_cards_tunnel / test_cards_mount unchanged and green).
- Skew / deploy order: dashboard only; the companion's agent is unchanged.
- OWED: none. Residue deliberately not built: routing on (editor, machine) needs the browser to carry a machine identity, which is a redesign (logic-cards-3, low, is the same root and is not in this chunk).

## bug-dash-cards-jobs-4 - After a session-secret rotation the b-roll and music gates mint no identity
- Status: PARTIAL (rest OWED)
- Verified as: CONFIRMED medium (med-06). `BrollGate/MusicGate._identified_scope` called `auth.read_session_cookie(self._secret, ...)` with no `previous=`, while `auth._resolve_session` accepts `previous_session_secrets(settings)`. Reproduced on HEAD: a cookie minted with a previous secret passes the gate with no `x-ccsync-user`.
- Fix: `broll.py` and `music.py` new `_session_user(scope, headers)`: take the identity `login_gate` already resolved from `scope["state"]["ccsync_session"]` (the rule `CardsDispatch._note` follows; it also honours a server-side revocation, so a revoked session now mints NO header); only when no resolution is present (a gate driven without the dashboard in front) read the cookie with the current AND previous secrets.
- Regression test: `test_a_cookie_signed_before_a_rotation_still_names_its_editor[broll|music]`, `test_the_gate_takes_the_identity_login_gate_resolved[broll|music]` - fail on HEAD because the old-secret cookie produced no header and the resolved state was ignored.
- Tests run: see top (test_broll_mount, test_music_mount, both fleet_stamp suites green).
- Skew / deploy order: dashboard only.
- OWED: d-ops, `dashboard/src/ccsync_dashboard/ytdl.py` (YtdlGate identity minting): the verifier found the same shape there. Apply the same `_session_user` rule: read `scope["state"]["ccsync_session"][0]` when present (None there means no header), else `auth.read_session_cookie(secret, cookie, previous=auth.previous_session_secrets(settings))`.

## logic-ytdl-jobs-1 - The scheduler judges a computer by its LAST report however old it is
- Status: FIXED
- Verified as: CONFIRMED medium (med-12). `fleet_facts` read every `machine_state` row with no age bound; `policy_refusal`/`ranked_machines`/`explain` never asked whether a machine still reports. Reproduced on HEAD: one machine last seen 30 days ago answered `schedulable: true`, "first choice"; with a stale not-idle answer the job read `idle_wait`, transient.
- Fix: `jobs.py`: `fleet_facts` now carries `reported_at` (server clock); new `REFUSE_SILENT = "not_reporting"`, `MACHINE_SILENT_SECONDS = 15 min`, `_silent_for()`, `_duration_words()`; `policy_refusal` refuses a silent machine second (after the fleet halt, before every per-machine state, since those describe a machine that is there); new job-level `REASON_SILENT = "machines_not_reporting"`, NOT transient, ordered after every code a live machine can clear and before `no_capable_machine`; summary words added. `machine_facts` does not carry `reported_at`, so the machine reporting or claiming right now is never judged by its own stored row. `capable` still counts a silent machine (it is hardware that could). Doc row added to `docs/TIMELINE-CARDS-INTO-CCSYNC.md`'s reason_code table.
- Regression test: `test_a_machine_in_a_drawer_is_not_a_schedulable_answer`, `test_a_dead_machines_old_idle_answer_does_not_keep_a_job_transient`, `test_a_silent_machine_cannot_win_the_rank_grace` (+ guard `test_a_live_machine_is_untouched`) - fail on HEAD because nothing bounded the age.
- Tests run: see top (every test_jobs* suite green).
- Skew / deploy order: dashboard only. 15 min is deliberately shorter than the jobs picker's `online` (a day): the picker aims work, this answers "will it be claimed on a next report".
- OWED: d-api, `docs/API.md` section 6c reason_code table: add `machines_not_reporting` | every machine that could run it has not reported for 15 min | no. d-diag (their call), `alerts.py::_check_jobs_starved`: consider adding `jobs.REASON_SILENT` to the `meaning` map ("every computer that could do it has been switched off"), since a 6 h queue whose only capable machines are silent will not empty by itself; left out here because alerts.py is not ours.

## logic-cards-1 - Anyone in a shared episode can close it under the other person, and the confirm names the person pressing the button
- Status: FIXED
- Verified as: CONFIRMED medium (med-13). HEAD `may_close` returned "" for any listed occupant; confirm built from `Entry.last_in()` (newest request = usually the presser).
- Fix: `cards_pool.py` `may_close`: a non-admin may close only when there is no occupant or they are the ONLY one (docstring updated). New `Entry.last_in_other_than(editor)`; `cards_landing._state` builds `close_prompt` from the newest person OTHER than the reader (the row's own "last in" note is unchanged).
- Regression test: `test_one_of_two_occupants_cannot_close_the_other_ones_episode`, `test_the_close_confirm_names_the_other_person_not_the_presser` - fail on HEAD because ruskin was allowed and the confirm named owen (the reader).
- Tests run: see top (test_cards_pool's existing security-2 and confirm tests unchanged and green).
- Skew / deploy order: dashboard only.
- OWED: none

## logic-cards-2 - An always-on companion keeps its editor "in" their last episode indefinitely
- Status: FIXED
- Verified as: CONFIRMED medium (med-13). `cards_tunnel.local_engine` called `pool.note_agent(editor)` on every agent call, including the 25 s `/pending` long poll and the `AGENT_PING_S` heartbeat (`push_loop` in the other repo's agent.py re-sends an unchanged playhead as a heartbeat).
- Fix: `cards_tunnel.py`: the stamp moved out of `local_engine` into `_seat()`, called only for WORK: a full state push (`state` not null), a `state: null` ping whose playhead/ph_uid differ from what the engine holds (`_playhead_moved`, read before the engine takes it), and a result. `note_agent(editor, engine=None)` stamps the episode of the engine actually used (so a pinned result stamps the right episode). The security-1 intent (an offline browser whose Resolve is being worked keeps its seat) holds whenever Resolve is actually being used; an idle tray no longer holds a seat, and the landing row + confirm still name who was last in.
- Regression test: `test_an_idle_agent_poll_does_not_keep_its_editor_in_the_episode` (+ guard `test_a_playhead_moved_in_resolve_counts_as_being_there`) - fails on HEAD because a pending poll re-stamped alex.
- Tests run: see top.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-cards-jobs-3 - Pinned jobs wait for ever, with no alert, whenever no episode happens to be open
- Status: FIXED (as the downgraded low)
- Verified as: DOWNGRADE to low (med-06): the job is delayed, not lost; any engine runs any pinned job, so the next episode opened drains it, and the outputs are only read by open Cards pages. The real residue is the jobs page saying "pinned to the dashboard's own worker" as though it were being worked on.
- Fix: `cards_exec.py`: module-level `_NO_ENGINE` event set by `PinnedExecutor.tick()` when it has no engine, cleared when it has one or on `stop()`; `waiting_for_an_engine()` (running AND no engine). `jobs._terminal_summary` for a pinned job appends "It is waiting: no Timeline Cards episode is open on the dashboard, and it runs as soon as somebody opens one" when that is true. No alert added: the verifier's reading is that nothing is lost and nobody is waiting.
- Regression test: `test_a_pinned_job_with_no_open_episode_says_what_it_waits_for` - fails on HEAD because `waiting_for_an_engine` / the sentence do not exist.
- Tests run: see top (test_jobs_pinning green).
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-cards-jobs-5 - The API-path session trim throws away corpus parts 2..n once a conversation passes 40 turns
- Status: FIXED
- Verified as: low, unverified by the hunt; verified here. `cards_ai._trimmed` kept `messages[:2]` + the last 78; `_user_message` stores every marked corpus part in the two-block form and `_is_corpus_message` recognises them, so parts 2..n (messages 2..2n-1) were the first dropped past 40 turns, and the moving cut changed the prefix after message 1 on every save. Reproduced on HEAD with a 4-part corpus + 60 turns: index 2 was "search 21", not part 1.
- Fix: `cards_ai.py` `_trimmed`: keep EVERY leading corpus pair (user message `_is_corpus_message` with its reply), then the most recent `MAX_TURNS - lead` pairs (never fewer than one); pairs stay user/assistant. `MAX_TURNS` comment and docstring updated.
- Regression test: `test_the_trim_keeps_every_corpus_part` - fails on HEAD because parts 1-3 were cut.
- Tests run: see top (test_cards_ai's existing 40-turn test unchanged and green).
- Skew / deploy order: dashboard only; stored session files are read unchanged.
- OWED: none


# Chunk 2 (bug-dash-cards-jobs-6, logic-ytdl-jobs-6, logic-cards-3..8)

Regression tests: appended to `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-cards.py`
(14 new, 33 in the file). Proof they fail on HEAD: a scratch mirror of `dashboard/`
with cards.py, cards_pool.py, cards_landing.py, cards_tunnel.py, jobs.py and
cards_landing.html/.js/.css replaced by `git show HEAD:...`, run with
`PYTHONPATH=<mirror>/src`: all 14 FAILED (the logic-cards-3 one fails there on
chunk 1's `enter=` keyword; against the chunk-1 tree it fails because
`note_visit` on a LOADING entry moved `_where`, read line by line). On this tree:
33 passed.

Tests run (dashboard venv, from `dashboard/`):
`python -m pytest tests/test_bug_hunt_2026_09_24_w2_d-cards.py tests/test_cards_pool.py tests/test_cards_mount.py tests/test_cards_tunnel.py tests/test_cards_picker.py tests/test_cards_page_prefix.py tests/test_cards_capability.py tests/test_mount_status.py tests/test_health.py tests/test_jobs*.py tests/test_bug_hunt_2026_09_11_dash_api_jobs.py tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py`
-> 500 passed, 6 skipped; `tests/test_no_em_dash.py tests/test_cards_ai.py tests/test_jobs_pinning.py` -> 239 passed.
Rendered `/cards/?want=<slug>` through a TestClient and looked at it in headless
Chrome at 1280 and in a 390 px iframe: the banner wraps, its [ OPEN ] sits
beside the text on both widths, no horizontal scroll.

Skew / deploy order for the whole chunk: dashboard only. No schema change, no
companion change. New optional keys only: `open[i].last_agent` on
`/api/v1/health` (and `open[i].agent` now means "attached now"), and
`opening_seconds` on `/cards/state.json` rows. The 503 detail an agent gets
from a dashboard with no Cards mount changed wording; the companion role shows
it verbatim and parses nothing out of it.

## bug-dash-cards-jobs-6 - `POST /cards/open` walks the vault four levels deep on the event loop
- Status: FIXED
- Verified as: low, unverified by the hunt; verified here. `cards_open` is `async def` (it awaits the form) and called `_episodes(request)` -> `cards_pool.episodes()` (recursive `os.scandir`, depth 4) directly once the 30 s `_scan` cache lapsed; `cards_close` (also async) called `pool.drop` -> the other repo's `engine.stop()` and the executor shutdown on the loop. Probed on HEAD: a spy on `cards_pool.episodes` saw a running event loop in its thread.
- Fix: `cards_landing.py` `cards_open`: `rows = await asyncio.to_thread(_episodes, request)`; `cards_close`: `await asyncio.to_thread(pool.drop, slug)`.
- Regression test: `test_open_and_close_walk_the_vault_and_stop_engines_off_the_event_loop` - fails on HEAD because the walk (and `stop()`) ran with a running loop in their thread.
- Tests run: see chunk header.
- Skew / deploy order: dashboard only.
- OWED: none

## logic-ytdl-jobs-6 - The why page says a lower-ranked machine is offered the job "once it has waited 60s" when it already is
- Status: FIXED
- Verified as: low, verified. `explain` built the clause as a constant for every rank > 1, while `first_refusal` returns True for a forced job, a targeted job, a job older than RANK_GRACE_SECONDS, and a tie with first choice. Probed on HEAD: a forced proxy job's second machine read "offered the job anyway once it has waited 60s".
- Fix: `jobs.py` new `_offer_clause(job, key, fleet, now)` built from `first_refusal` itself: "it is being offered the job now too", else "it is offered the job too in Ns if nobody ahead of it has taken it by then" (N from `job_age_seconds`, ceil, at least 1). `import math`.
- Regression test: `test_a_forced_job_does_not_tell_the_second_machine_to_wait`, `test_a_job_past_the_grace_is_already_offered_to_everyone`, `test_a_fresh_job_says_how_long_the_second_machine_waits` - fail on HEAD because the old constant sentence has neither phrase.
- Tests run: see chunk header (every test_jobs* suite green; nothing pinned the old sentence).
- Skew / deploy order: dashboard only; `why` is words, and Timeline Cards reads `schedulable` only.
- OWED: none

## logic-cards-3 - Routing is by person, not by computer; opening a second episode moves your Resolve; the page promises one episode per person
- Status: PARTIAL (the two-machine routing is DEFERRED for an owner decision, nothing owed)
- Verified as: DOWNGRADE to low (med-13), "largely a duplicate of bug-dash-cards-jobs-2"; the verifier named the residue jobs-2 does not cover: the `/cards/open` stamp on a LOADING entry (probe: `engine_for` answered None for the whole build) and the landing copy. Re-read after chunk 1: `note_visit(enter=True)` from `cards_open` still pointed `_where` at the LOADING entry.
- Fix: `cards_pool.py` `note_visit`: the seat is stamped as before, but `_where` moves only to a READY entry, so opening an episode no longer detaches the agent from the one being worked in; entering the new episode's page (a navigation, chunk 1's `enter`) is what moves it. `cards_landing.html`: "One episode at a time per person" replaced by "Up to N episodes at once on this server (M open now). Your Resolve follows the last episode you went into. ..." (the true rule).
- Regression test: `test_opening_a_second_episode_does_not_detach_the_agent_while_it_builds`, `test_the_landing_page_no_longer_promises_one_episode_per_person`.
- Tests run: see chunk header.
- Skew / deploy order: dashboard only.
- DEFERRED (needs the owner): routing on (editor, machine) so one editor's two computers can drive two episodes (CARDS_TWO_PROJECTS 1a). The tunnel knows the agent's machine, but a BROWSER request carries no machine identity, so "which computer's Resolve does this page drive" has no key to join on; that is a design decision (pick a machine on the page, or bind a page to a companion), not a fix.
- OWED: none

## logic-cards-4 - The landing page ignores `?want=`, and "carry on" only remembers episodes you built
- Status: FIXED
- Verified as: low, verified. `cards_landing` passed `want` to the template and the template never read it; `remember(` had one caller, `POST /cards/open`, and its docstring claimed the dispatcher called it. (The picker's YOUR RECENT tiles, 5a26e10, cover the per-person half; the per-browser carry-on cookie was still stale.)
- Fix: `cards_landing.html`: a `.cl-want` banner (with `data-want` on `<main>`) naming the episode and its state (IS OPEN / OPENING "this page takes you into it as soon as it is ready" / IS NOT OPEN "an episode closes when the dashboard restarts or somebody closes it") with the row's own [ OPEN ] / [ CLOSE ] actions; `cards_landing.css` styles it. `cards_landing.js`: when the watched state moves and the wanted slug is now READY, `location.replace(href)` into it instead of reloading; only a transition seen while watching forwards, and `replace` means Back does not land on a page that forwards again (a server-side forward on `?want=<ready>` was rejected for exactly that trap). `cards.py` `CardsDispatch._with_carry_on`: a page navigation into a READY episode (the same `entering` test that moves the agent) gets the carry-on cookie through `cards_landing.remember`, `Secure` from `auth.cookie_secure` (wired in `mount_cards` as `dispatch.cookie_secure`; None in hand-built dispatchers means no cookie), only on a response below 400.
- Regression test: `test_want_names_the_episode_that_is_not_open_and_offers_its_button`, `test_entering_an_episode_page_sets_the_carry_on_cookie` (also: a fetch inside the page sets none), `test_the_picker_script_goes_into_the_wanted_episode_when_it_is_ready` - fail on HEAD because there is no banner, no cookie, no forward.
- Tests run: see chunk header; rendered and screenshotted at 1280 / 390.
- Skew / deploy order: dashboard only.
- OWED: none

## logic-cards-5 - The landing page still says closing is an admin act
- Status: ALREADY_FIXED
- Verified as: HEAD `4462a2a`'s `cards_landing.html` (picker redesign, commit `5a26e10`) no longer has "Closing one is an admin act"; its footer reads "You can close your own episode, or one nobody has been in for a while; closing one somebody else is in is for an admin.", which matches `may_close` (including chunk 1's logic-cards-1 tightening: "your own" means nobody else is in it) and the cap refusal. The `cards_close` docstring says the same.
- Fix: none.
- Regression test: none (no change).
- Tests run: n/a.
- Skew / deploy order: n/a.
- OWED: none

## logic-cards-6 - With the Cards mount absent or disabled, every agent is told to set DASH_CARDS_SERVER_URL
- Status: FIXED
- Verified as: low, verified. `_routed` answers (None, None) whenever `app.state.cards_pool` is absent, which is every non-MOUNTED status, and `_upstream`'s 503 then named only DASH_CARDS_SERVER_URL; `app.state.cards_detail` ("the vault root is not mounted (/vault)") was never read. Probed on HEAD with a missing vault: the detail was "no Timeline Cards server is configured here (set DASH_CARDS_SERVER_URL on the dashboard)".
- Fix: `cards_tunnel.py` new `_no_server_sentence(request)`: when `cards_status` is set, not "mounted", and has a detail, the 503 reads "Timeline Cards is not running on this dashboard: <cards_detail>. No separate Timeline Cards server is configured either (DASH_CARDS_SERVER_URL on the dashboard)." Otherwise the old sentence. The variable is still named, last, so `test_cards_tunnel.py::test_no_server_configured_is_a_503_naming_the_variable` passes unchanged. The token-missing 503 is unchanged (a URL was configured, so that is the real problem).
- Regression test: `test_an_absent_mount_names_its_own_reason_not_the_server_url` - fails on HEAD (old sentence).
- Tests run: see chunk header.
- Skew / deploy order: dashboard only; the companion role (timeline_cards_role.py) shows the detail verbatim.
- OWED: none

## logic-cards-7 - An episode build has no timeout: a hung vault read is OPENING forever, holding a seat
- Status: FIXED
- Verified as: low, verified. Only `_run_build` could leave LOADING; nothing in `EnginePool` read `opened_at`; a LOADING entry counts toward the cap in `open()`. A build blocked in a scandir on a hung share therefore held the seat for the life of the container.
- Fix: `cards_pool.py`: `BUILD_DEADLINE_SECONDS = 600` (generous: a real build reads the episode off the share). `_expire_stalled()` (lazy, under the lock, from `get()`, `entries()` and `open()`, since nothing in the pool ticks and the landing page's own poll is what notices) turns an over-age LOADING entry FAILED with "the vault did not answer for 10 min, so this episode did not open. Press [ OPEN ] to try again." and `failed_at`, which frees the seat and stops the page polling. `_run_build` now decides AND publishes under one lock (a deadline-failed entry can be replaced by a new `open()`, so a gap between the two would be a window to publish an engine nothing holds); a build that finishes after the deadline is PUBLISHED if its entry is still registered and a seat is free, else stopped with "this episode opened too late: every seat was taken by then". `Entry.as_dict()` carries `opening_seconds`; `cards_landing._opening_phrase` and the template show "opening for N min; it gives up at 10 min" on a row past one minute.
- Regression test: `test_a_build_stuck_on_the_share_gives_up_and_frees_its_seat`, `test_a_slow_build_that_finishes_after_the_deadline_is_still_published`, `test_the_landing_row_says_how_long_an_episode_has_been_opening` - fail on HEAD (no deadline, no `opening_seconds`, no phrase).
- Tests run: see chunk header (test_cards_pool's orphan and retry-floor tests unchanged and green).
- Skew / deploy order: dashboard only.
- OWED: none

## logic-cards-8 - /api/v1/health reports a Cards agent as attached if one has ever pushed
- Status: FIXED
- Verified as: low, verified against the other repo: `agent.py:67` sets `agent_name = None`, `:348` sets it on every `agent_state` and nothing clears it; `:155` `agent_here()` is `time.time() - agent_seen < AGENT_GONE_S`. `cards.health_block` used `bool(agent_name)` for `open[i].agent`, the top-level `agent`, and the single-engine fallback.
- Fix: `cards.py` new `_agent_here(engine)` (calls `agent_here()` when the engine has it, else the old `agent_name` answer, never raises) and `_last_agent(engine)`; `open[i]` gains `last_agent`, and all three `agent` readings use `_agent_here`.
- Regression test: `test_health_reports_an_agent_that_left_as_not_attached` - fails on HEAD because `agent` was True for a named, gone agent (and `last_agent` did not exist).
- Tests run: see chunk header (test_health, test_mount_status green).
- Skew / deploy order: dashboard only; `last_agent` is a new optional key.
- OWED: none

## Owed round (2026-09-25, builder "d-cards / d-api")

### bug-comp-media-3 (from c-media) - refuse an unwritable out_stem at POST /api/v1/jobs
- Status: FIXED
- Verified as: c-media's ledger (the companion's `job_paths.safe_stem` refuses an empty/dot name, a `/` or a control character fleet-wide, retryable=False, and `:`/`\` only on Windows, retryable). On HEAD `api_create_job` queued any `out_stem`, so such a job was queued, offered, claimed and failed before anyone heard. The only submitter besides an admin by hand is Timeline Cards' `fleet_jobs.submit` (MulticamPipeline), which on a non-answer falls back to making the clip itself, so a 422 here shortens the same path HEAD takes after the claim fails.
- Fix: `dashboard/src/ccsync_dashboard/jobs.py` new `out_stem_problem(kind, inputs)` (the three media kinds only; the stripped stem, blank = fallback to the source stem, as `jobs_runner._media_paths` does; refuses `.`/`..`, `/`, control characters; NOT `:` or `\`). `api.py` `api_create_job` raises 422 with that sentence before `db.create_job`. `docs/API.md` §6c paragraph on `out_stem` states the rule.
- Regression test: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-cards_owed.py` (new file so it cannot collide with another builder's edits to the chunk files): `test_a_stem_no_machine_can_write_is_refused_at_submit` (9 stems x 3 kinds), `test_a_kind_that_has_no_stem_is_not_judged_by_one` - fail on HEAD (200 and a queued row / no helper). Guards: `test_a_windows_only_or_ordinary_name_is_still_queued` (`Q&A: Ruskin`, a backslash, `C:x`, an ordinary name), `test_a_missing_stem_falls_back_to_the_source_and_is_queued`, and `test_the_submit_rule_is_the_companions_fleet_wide_rule` (both directions against `job_paths.safe_stem(windows=False)`).
- Tests run: `pytest tests/test_bug_hunt_2026_09_24_w2_d-cards_owed.py` -> 37 passed; the same file from a scratch copy of the package with HEAD's api.py + jobs.py -> 28 failed, 8 passed (the guards), 1 skipped (the contract test, no companion beside the scratch copy); `pytest tests/test_jobs.py tests/test_jobs_contract.py tests/test_jobs_cancel.py tests/test_jobs_backpressure.py` + the new file -> 134 passed, 1 skipped.
- Skew / deploy order: dashboard only, no wire key. An older companion never sees a refused job; Cards treats the 422 as "no receipt" and makes the clip locally (its existing fallback).
- OWED: none. (The separate d-cards item for `cards_exec._paths` in the same c-media ledger was not in this round's list and is untouched here; `jobs.out_stem_problem` is importable there if it wants the same rule without `:`/`\`.)

## Owed round (2026-09-25, builder "d-cards")

Tests for every item below: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-cards.py`, section "owed round". Run: `dashboard\.venv\Scripts\python.exe -m pytest -q tests/test_bug_hunt_2026_09_24_w2_d-cards.py tests/test_bug_hunt_2026_09_24_w2_d-cards_owed.py tests/test_broll_mount.py tests/test_music_mount.py tests/test_broll_fleet_stamp.py tests/test_music_fleet_stamp.py tests/test_cards_mount.py tests/test_cards_pool.py tests/test_cards_tunnel.py tests/test_jobs_contract.py tests/test_cards_page_prefix.py` -> 306 passed, 5 skipped. "Fails on HEAD" below is reasoned line by line against the pre-round code (each asserted behaviour did not exist there).

### bug-comp-media-3 (from c-media) - the pinned engine's `_paths` took any out_stem
- Status: FIXED
- Verified as: `cards_exec.PinnedExecutor._paths` returned `str(out_stem).strip() or _stem(source)` unchecked after `resolve` had guarded out_rel, so `..`, `/etc/x`, `Interview 1/2` reached `fleet_execute` as the output name. The owed half at POST time (`jobs.out_stem_problem` + api 422) was done by the "d-cards / d-api" owed builder above; this is the engine half.
- Fix: `dashboard/src/ccsync_dashboard/cards_exec.py` new `_plain_stem()` (copied, not imported: the container ships no companion package) refuses a blank/dot name, a `/`, or a control character with `ExecutorError` (which `_run` turns into `fail_pinned_job`, never retried). NOT `:` or backslash: this Linux engine is where a Windows-refused name gets made. A blank out_stem still falls back to the source's stem.
- Regression test: `test_a_pinned_out_stem_that_is_not_a_plain_name_is_refused` (8 stems; HEAD returned them). Guards: `test_a_name_only_windows_refuses_is_made_by_the_linux_engine`, `test_an_empty_out_stem_still_takes_the_sources_own_name`, and `test_the_pinned_engine_and_the_submit_check_agree` (14 stems: the engine refuses exactly what `jobs.out_stem_problem` refuses, so a job the POST accepted is never refused here).
- Skew / deploy order: dashboard only; a job already pinned with such a stem now fails with a sentence instead of writing outside its cache directory.
- OWED: none

### logic-cards-9 (from c-resolve) - the no-engine answer says `attached: False`
- Status: FIXED
- Verified as: c-resolve's companion `_is_no_engine_answer` reads `attached` first and falls back to the phrase "is not in a Timeline Cards episode". `cards_tunnel._no_engine` and the long poll's `{"note": ...}` carried no such key.
- Fix: `cards_tunnel.py` `_no_engine()` adds `"attached": False`; the pending route's no-engine return is `{"note": ..., "attached": False}`. `_local`'s `{"error": str(exc)}` is untouched (an attached engine). The sentence keeps the fallback phrase verbatim.
- Regression test: `test_the_no_engine_answer_says_it_is_not_attached` (also pins the fallback phrase), `test_the_long_polls_no_engine_answer_says_it_is_not_attached` - no key on HEAD.
- Skew / deploy order: either order; older companions ignore the key.
- OWED: none

### bug-dash-ops-2 / bug-dash-ops-3 (from d-ops) - b-roll and music gates vs login_gate's session verdict
- Status: FIXED (the previous-secret half was already FIXED in this group's chunk as bug-dash-cards-jobs-4; this round adds the rest)
- Verified as: `BrollGate/MusicGate._session_user` already took `scope["state"]["ccsync_session"]` when login_gate had resolved it and otherwise read the cookie with previous secrets. Two gaps remained: with no verdict in the state but the dashboard app in the scope it still re-read the cookie (no revocation check, unlike `ytdl.YtdlGate._session_user`), and `broll._session_cookie` (imported by music.py) was FIRST-wins where Starlette's parser is last-wins.
- Fix: `broll.py` / `music.py` `_session_user`: when `scope["app"].state.settings` exists, `auth.get_session_user(Request(scope))` (login_gate's resolver, cached on the request state; an exception mints no header). `broll._session_cookie` is last-wins.
- Regression test: `test_two_session_cookies_name_the_last_one_as_login_gate_does[0,1]` (HEAD stamped `alice`, the first cookie), `test_with_the_dashboard_in_scope_the_gate_asks_login_gates_resolver[0,1]` (HEAD never asked the resolver and stamped the cookie's owner of a session the resolver calls dead).
- Skew / deploy order: dashboard only.
- OWED: none

### ui-copy-6 (from d-ui) - " -- " in Cards copy
- Status: FIXED (cards.py, cards_tunnel.py); NOT_A_DEFECT for cards_ai.py:118
- Verified as: read each. cards.py 95/99 (`BLOCKED_PATHS`, shown by the page as `error`), 678/687 (`_not_open` / `_not_here` JSON `error`) and cards_tunnel.py:196 (`_no_engine`, shown in the companion's tray/fleet detail) are user-visible. cards_ai.py:118 is `JSON_REPLY_NOTE`, a line of the PROMPT sent to the model, never shown to a person: left alone.
- Fix: colons or two sentences. Substrings existing tests pin ("cannot restart itself", "one engine per episode", "is not in a Timeline Cards episode") are unchanged.
- Regression test: `test_the_cards_sentences_a_page_shows_carry_no_typewriter_dash` - HEAD had " -- " in all five.
- Skew / deploy order: dashboard only.
- OWED: none
