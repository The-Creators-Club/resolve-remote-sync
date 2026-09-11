## The Resolve bridge, the watcher and the Timeline Cards role (CR-252, 2026-09-11)

Five findings from the second hunt of 2026-09-11, all of them inside a fix
that landed this morning: two same-day fixes that covered one arm of the case
they were written for, one helper that grows a string it was asked to cut, and
one regression test that a half-revert leaves green.

### CR-252a (comp-resolve-b-2) - a clip the rate limiter refused waited for the life of the process - FIXED (companion/src/ccsync_companion/watcher.py)

The watcher latches a NON_CANONICAL path in `_offered_non_canonical` at OFFER
time, and until now the only thing that ever lifted the latch was
`rearm_non_canonical`, which `app._note_non_canonical_result` calls after a
ReplaceClip has been ATTEMPTED and refused. When
`resolve_journal.allow_automatic` refuses the whole burst - the 900 s
unprompted-pass limiter - no clip is attempted, so nothing is re-armed: the
clips sit on `app._canon_relink_pending`, which no timer and no report hook
drains, and `_handle_non_canonical` is never re-entered unless some other path
is newly offered. A companion that restarts inside the limiter's window (a
self-upgrade, the 0.9.62 supervisor's relaunch after a CR-93 abort) refuses its
first burst because `allow_automatic`'s bars are persisted, and every
non-canonical clip in the open project is then latched, queued and stranded
under its local spelling. The log said "holding N clip(s)" once and pointed at
Tray > Settings > SCAN WHOLE PROJECT, which is a sentence in `companion.log`
that no editor reads. Before comp-sync-13 the unconditional re-offer on every
3 s poll masked it; the 900 s cooldown that fix added made the queue's only
automatic drain rarer still.

The OFFER now arms the same cooldown the failed relink does, through one
helper (`_arm_rearm`), so a latched path is offered again 900 s later whether
or not anything was ever attempted on it. That is what drains the queue: the
caller de-dupes each offer against its pending list (comp-sync-13), so a
re-offer the limiter refuses again costs a dictionary lookup, and the offer
that arrives after the limiter's window is what starts the burst. comp-sync-13's
own property is untouched - a re-offer is still never more often than the
cooldown. A second hole went with it: a key evicted by the `MAX_REARM_TRACKED`
ceiling had no due date and so could never come due again, which stranded
exactly the clips the book overflowed on; a missing record now reads as due,
and the re-offer re-arms it.

### CR-252b (regression-8) - a Timeline Cards role that lost ONE of its two loops was never recovered - FIXED (companion/src/ccsync_companion/timeline_cards_role.py)

CR-236's comp-resolve-4 made the watchdog test liveness (`any(t.is_alive())`)
instead of `if self._threads`, which recovers the both-loops-dead case.
`health()` is stricter: `_note_loop_end` records `_loop_error` on the FIRST
loop death and `health()` returns HEALTH_STOPPED as soon as it is set. So a
role whose push loop raised on a Resolve state the other repo's client cannot
encode, with the pull loop still long-polling, showed STOPPED on the fleet grid
with that sentence for ever while `supervise_now` answered "running" every
minute and never called `_clear_dead`/`_start_guarded`. The asymmetry the
finding is named for - the report is honest and the recovery is not - was
narrowed by one loop, not removed. The liveness test is now "there are threads,
ALL of them are alive, and no loop has reported an end", which is the same
predicate `health()` uses, so the two can no longer disagree. The restart path
is unchanged and still bounded by MAX_START_FAILURES, and `_clear_dead` already
clears `_loop_error`, so a recovered role goes green again.

### CR-252c (comp-resolve-b-3) - `_elide` could return more characters than the cap it was given - FIXED (companion/src/ccsync_companion/timeline_cards_role.py)

For `limit == 4`, `head = max(1, limit // 3)` is 1 and the tail slice was
`text[-(limit - head - 3):]`, i.e. `text[-0:]` - the whole string. The helper
whose contract is "cut this to `limit`" returned `text[:1] + "..." + text`. Not
reachable from today's one caller (the standalone-agent refusal's budget is
`255 - 57 - 103 = 95`), but that budget is computed from two sentences in the
same file, and the cut exists precisely to pre-empt the dashboard's silent
`max_length=255` truncation of `CardsAgentIn.detail`. The tail width is clamped
at zero now and the slice is skipped when there is no room for one.

### CR-252d (comp-resolve-b-4) - a blind probe closed the launch window with "Resolve registered" - FIXED (companion/src/ccsync_companion/resolve_bridge.py)

comp-resolve-6 split the close of the CR-68 launch window into READY and
ABSENT, but the fall-through took UNKNOWN with READY. UNKNOWN is the fail-open
answer: the TCP table could not be read (a locked-down endpoint agent), or 1144
is held by something that is not fuscript. Logging it as "script server has its
host now - connecting" writes a positive claim the probe never made into the
one line a CR-68 diagnosis is read out of, so the next reader of a diagnostics
bundle concludes scripting was healthy at the moment the guard was actually
blind and the call went through unguarded. `_note_starting`'s `ready` is
tri-state now - True registered, False went away, None could not tell - and
UNKNOWN gets its own sentence saying the probe could not tell and that the
connection was made anyway, which is what fail-open means. Nothing about when
the companion connects changed.

### CR-252e (comp-resolve-b-5) - the res-companion-2 regression test passed on a half-reverted fix - FIXED (companion/tests/test_bug_hunt_2026_09_11_comp_resolve.py)

`test_a_start_that_fails_after_engine_start_stops_that_engine` asserted
`engine.stopped is True or engine.started is False`. res-companion-2's fix has
two independent halves - the client is built before `engine.start()`, and the
failure path calls `_release_engine` - and the disjunction is satisfied by
either, so reverting the release alone left the suite green over the exact
breach the module exists to prevent: a Timeline Cards engine driving Resolve
with nothing holding a reference to it, and the watchdog starting a second one
a minute later. The two properties are asserted separately now, and a second
case covers the half the ordering cannot: an engine whose own `start()` raises
after a successful client build is stopped and let go. Both fail with
`_release_engine` removed from `_start`'s except arm (verified by reverting it
and re-running).

### Verification
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_a_path_the_limiter_refused_is_offered_again -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_the_re_offer_is_still_no_more_often_than_the_cooldown -> passes before and after (comp-sync-13's property, pinned so this fix cannot undo it)
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_the_offer_book_is_still_bounded -> passes before and after (the new writer must stay bounded)
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_a_role_that_lost_one_loop_is_restarted -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_a_role_whose_loops_reported_an_error_is_not_called_running -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_a_healthy_role_is_still_left_alone -> passes before and after (the watchdog must not become a restarter)
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_elide_never_returns_more_than_its_cap[4] -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_a_blind_probe_does_not_claim_resolve_registered -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_resolve.py::test_a_real_registration_still_says_so -> passes before and after (the READY sentence is unchanged)
- companion/tests/test_bug_hunt_2026_09_11_comp_resolve.py::test_a_start_that_fails_after_engine_start_stops_that_engine -> passes at f1eeb42 by accident (the or-assertion); fails with `_release_engine` reverted, which is the point
- companion/tests/test_bug_hunt_2026_09_11_comp_resolve.py::test_an_engine_that_will_not_start_is_stopped_and_let_go -> new; fails with `_release_engine` reverted

Also run (both green, both cover a module in this territory):
companion/tests/test_watcher.py (68 passed) and the comp-sync-13 relink tests
in companion/tests/test_bug_hunt_2026_09_11_comp_sync.py (5 passed, -k relink),
because the watcher change touches the path they pin.

### OWED TO ANOTHER TERRITORY
- comp-app: `companion/src/ccsync_companion/app.py`: `_handle_non_canonical`: nothing REQUIRED - CR-252a drains the queue from the watcher side alone, and the app's de-dupe makes the re-offer cheap. Optional and strictly better: when the limiter refuses, log the holding line at most once per window instead of once per offer (it now fires every 900 s per project rather than once), and consider scheduling one retry at `resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS` so the drain does not depend on Resolve still being open at the next poll. No deploy ordering: both halves are inside one companion build, nothing on the wire.
- comp-ui: `companion/src/ccsync_companion/popup.py`: `run_fix_all`: comp-resolve-b-1 (comp-resolve-2's fix landed in consolidate only, so FIX ALL still counts a rehearsal as bytes copied) is assigned to comp-ui and was left alone here. `consolidate.count_copied` / `count_rehearsed` are import-safe and take a plain result list.

### Owner decisions
- CR-252a re-offers a latched non-canonical path every 900 s for as long as the project stays open and the clips stay non-canonical, where before it was once per process. On a machine with a wrong `canonical_prefix` that means the "holding N clip(s)" log line appears every fifteen minutes instead of once. That is the price of the queue draining by itself; the alternative (a timer in app.py) is the comp-app half recorded above.
- CR-252d's UNKNOWN sentence is a third INFO line in the launch-window log. It does not change whether the companion connects - UNKNOWN still fails open, per CR-68 - only what the log claims about it.
