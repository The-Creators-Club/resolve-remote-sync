# verdicts - d-mounts-ui-d-cards

## dash-cards-1
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: The mechanism is exactly as reported. `page/sw.js:36-37` names the
  shell cache `'cards-shell-' + VER` where `VER` comes from `page.render_sw()`
  substituting `page_version()`, so every page the checkout serves - the flat
  one and every `/cards/p/<slug>/` one - uses the SAME cache name on the SAME
  origin, and `KILL_SW`'s prefix filter (`k.indexOf('cards-shell-') === 0`)
  therefore deletes the live per-episode worker's shell, not just the dead flat
  one. The real worker's own prune carries an `n !== SHELL` guard for precisely
  this reason; the kill switch has none, and it cannot have one, because it
  does not know the live VER. Refill is impossible without a republish: only
  `install` writes `SHELL_URLS` (`'./'`, manifest, icon), the navigation arm
  (`shellAnswer`, sw.js:352-365) explicitly never puts a navigation in the
  cache, and `install` re-runs only when the worker's own bytes change. I
  considered refuting on reachability - the kill switch fires once per device
  and unregisters, and any navigation into `/cards/p/...` is itself in the old
  registration's scope, so on most devices it will have burned before an
  episode app was ever cached - but the losing order is ordinary (an episode
  installed and cached, then a later visit to `/cards/` on a device whose flat
  worker had not yet had its update check), the loss is silent, and it persists
  until the next Cards page republish. That is enough to keep it at medium.
- Evidence: `MulticamPipeline/multicam_pipeline/cards/page/sw.js:36-37,68-79,
  352-405`; `page.py:164-171` (`render_sw` bakes one `page_version()` per
  checkout, so all engines in the container serve one VER);
  `dashboard/src/ccsync_dashboard/cards_landing.py:232-267`. `KNOWN_BUGS.md`
  CR-285C names the same two constants and does not consider the collision. No
  KNOWN_BUGS entry covers this half (`grep -an "cards-shell"` -> CR-285C only).
- Fix note: the suggested fix (delete NO caches; unregister plus the client
  reload is the whole act) is right - the per-project worker's `activate`
  already prunes stale `cards-shell-*` itself, so nothing is leaked by not
  deleting. A fix MUST also touch
  `dashboard/tests/test_cards_pool.py:615` (`test_the_kill_switch_leaves_the_
  dashboards_own_caches_alone` asserts `"cards-shell-" in js` and would fail),
  and the CR-285C entry in KNOWN_BUGS.md should say why the narrowed sweep was
  narrowed to nothing. No companion or cross-repo change is needed.

## dash-cards-2
- Verdict: DOWNGRADED to low
- Duplicate of: wire-5 (same defect, same two line ranges, rated low there)
- Reasoning: Every factual claim checks out - `cards_agent_pending` is a
  blocking `def` with `Depends(get_conn)` (`api.py:107-112` opens a connection
  per request and closes it only after the route returns), `_wait_for_an_engine`
  is a `time.sleep` poll with no shared waiter and no counter, `grep -rn
  "CapacityLimiter|total_tokens|to_thread" dashboard/src/` returns nothing, and
  `deploy/run.sh:513,528` runs `--workers 1`. But two things cap the harm. The
  route ALREADY parked one threadpool worker per attached agent for the whole
  25 s poll before this pass - its own docstring says "one worker per connected
  agent, and there is one agent per machine" - so the fix widens an accepted
  design cost to the idle case rather than introducing a new class of
  occupancy. And `cards_agent` is off in the vendor build, this fleet is four
  machines, and the scenario needs 40+ machines with the role on: the hunter
  says so himself and marked it PLAUSIBLE/unmeasured. wire-5 found the same
  thing and rated it low; I agree with wire-5's rating.
- Evidence: `cards_tunnel.py:178-207, 386-424`; `api.py:107-112`;
  `deploy/run.sh:513`; grep for any limiter configuration in `dashboard/src/`
  -> no hits. KNOWN_BUGS CR-282H (line 24663) documents the hold as deliberate
  and already names the "one threadpool worker asleep" trade.
- Fix note: the suggested fix is sound but heavier than the risk. The cheap
  half of wire-5's version - clamp the NO-ENGINE hold well below
  `MAX_WAIT_SECONDS` (a few seconds still kills the spin the fix was written
  for), or make only the no-engine arm `async` with `anyio.sleep` since it
  touches no blocking engine - gets the same protection without a new
  Condition on the pool. If the hold length changes, check
  `dashboard/tests/test_bug_hunt_2026_09_18_dashboard.py` (it stubs
  `cards_tunnel._sleep` and asserts the full hold and the remaining-wait
  hand-on) and the companion's read timeout in
  `companion/src/ccsync_companion/timeline_cards_role.py`, which is the wait
  plus its own margin - shortening the server hold is safe for it, lengthening
  would not be.

## dash-mounts-ui-1
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: Reproduced. `_retire` writes `version: ""` and carries
  `revert_refused_reason`/`revert_refused_from`; `main()` then returns at
  `if not version:` (line 441-445) on every later boot, which is BEFORE the
  clearing rule at line 499, so nothing in `select_code_root.py` can ever drop
  the two keys again. `dashboard_update.status()` passes them through
  (line 1665) and `admin_dashboard_update.html:32-35` renders the banner on the
  key alone, without consulting `version`, so the panel keeps telling a healthy
  container to restore a backup. The only writers that drop the keys are a
  later APPLY (`dashboard_update.py:1439`) and a revert (`:1548`), neither of
  which a healthy server performs. The refusal really is obsolete by
  construction: the retire branch is reached only after `revert_refusal("")`
  returned "", i.e. the image has just been judged able to run this database.
- Evidence: scratch harness in my scratchpad running the real `main()` against
  a temp `CCSYNC_DATA_DIR`/`CCSYNC_APP_ROOT`/`CCSYNC_VENV_DIR` (image 0.7.50,
  current.json naming 0.7.43 with a carried refusal, `live_schema_version`
  stubbed to None so `revert_refusal("")` is ""). Boot 1: `RETIRED 0.7.43: ...
  the image carries it`, current.json keeps `revert_refused_reason` /
  `revert_refused_from`. Boots 2 and 3: file byte-identical, banner still
  rendered. `grep -rn revert_refused_reason dashboard/` confirms the writer set
  above. Nothing in KNOWN_BUGS covers it (`grep -an "revert_refus"` -> the
  CR-259a/dash-release-jobs entries, all about getting the key SHOWN).
- Fix note: of the two suggestions, "drop the two keys in `_retire`" is the
  correct one - the image has just answered the schema question for this exact
  database, so the carried sentence can never be true at that point, and moving
  the clearing rule above the `if not version:` return would also have to
  invent a counter for a version that no longer exists. That change contradicts
  `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py:
  test_a_retire_keeps_an_earlier_refusal_where_the_alert_looks_for_it`, which
  pins the carry, so the test must be rewritten with it (its stated purpose -
  keeping the evidence for `alerts.py:2782` - is moot once `applied` is "",
  because `_check_*` there returns [] when there is no applied version to
  disagree about). No companion or cross-repo change; a KNOWN_BUGS note under
  the regression-3 entry is worth adding since this is the neighbour that
  change opened.
