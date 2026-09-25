# logic-cards - Timeline Cards inside the dashboard (pool, landing, tunnel, AI seam, pinned executor) and the companion's Cards role: logic and usability
Files read (approximate coverage): all HEAD versions (read with `git show HEAD:` into the scratchpad, because the working tree has uncommitted edits to cards.py / cards_pool.py / base.html and a new cards_catalog.py that were not there when the brief was written): dashboard/src/ccsync_dashboard/cards_pool.py (all), cards.py (all), cards_landing.py (all), cards_tunnel.py (all), cards_exec.py (all), cards_ai.py (Runner.run/status/_choice/_sdk, ~40%), dashboard/templates/cards_landing.html (all), companion/src/ccsync_companion/timeline_cards_role.py (all); followed into jobs.can_pin, app.py boot block (executor + mount order), mount_status.py header, docs/CARDS_TWO_PROJECTS.md sections 3, 4, 1a and "what was left out", and the other repo's multicam_pipeline/cards/agent.py (agent_state / agent_pending / agent_result / agent_here) and project_agent.py (agent_state / agent_result).
Tests/probes run: two ad-hoc probes against the HEAD cards_pool.py with the dashboard venv (scratchpad probe.py, probe2.py): (a) an agent poll keeping a 3-hour-idle occupant "in" an episode, and (b) a co-occupant closing a shared episode, including the confirm text the landing page would build.

## Findings

### logic-cards-1 - Anyone in a shared episode can close it under the other person, and the confirm names the person pressing the button
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_pool.py:459-463 (`may_close`); cards_landing.py:117-125 (`last_in_phrase` / `close_prompt`); contradicts cards_landing.py:243-245 (the `cards_close` docstring)
- What: `may_close` returns "" (allowed) for any editor listed in `occupants`, even when other people are listed too. The landing page says two people in the same episode is "fine and always was", and the `cards_close` docstring says taking an episode from whoever is in it is "the act that must not happen by accident, which is why an admin is still the only person who can do that". The confirm is built from `Entry.last_in()`, which returns whoever sent the most recent request. That is usually the person about to press CLOSE, so the other person is never named.
- Failure scenario: Alex and Ruskin are both in Framing Formosa (Alex 2 min ago, Ruskin just now). Ruskin goes to /cards/ to free a seat and sees [ CLOSE ] beside Framing Formosa. The confirm reads "Close Framing Formosa? ruskin is in it now. ..." He presses OK and `drop()` stops the engine Alex is editing in. Alex's next fetch gets a 409 "this episode is not open" and his page is sent back to the landing page.
- Evidence: probe2.py: occupants `['alex', 'ruskin']`, `may_close(slug, "ruskin", False) == ''`, and the confirm text printed as above. test_cards_pool.py:557-562 tests nobody / own / somebody else's / admin, but never an episode with two occupants.
- Ledger: new (a gap in security-2, 2026-09-18)
- Suggested fix: allow a non-admin close only when `occupants` is empty or is exactly `[editor]`. Build the confirm from the occupants other than the presser, for example "alex was in it 2 min ago".

### logic-cards-2 - An always-on companion keeps its editor "in" their last episode indefinitely, so the idle release never fires and the landing page names someone who left hours ago
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_pool.py:359-379 (`note_agent`), cards_tunnel.py:143-157 (`local_engine` stamps it on every agent call); consumed by cards_pool.py:228-231 (`occupants`), :439-465 (`may_close`), :420-437 (`_full_sentence`), cards_landing.html:65-77
- What: security-1 made every agent call (`/state`, and the 25-second `/pending` long poll) refresh `seen[editor]` on the episode in `_where[editor]`. `_where` is only cleared by `drop()`. The Cards role runs in the tray app from sign-in to shutdown whether or not anyone is looking at a page. So "occupant" now means "this editor's companion is running and this was the last episode they visited", not "someone is working here". The 15-minute idle release that security-2 relies on, the "nobody in the last 15 min" branch of the cap refusal and the Who column never lapse for an editor with the role on.
- Failure scenario: Alex opens Reproductive Rights at 10:00 and closes the tab at 10:20. His base-rig companion (cards role live since CR-226) polls all day. At 16:00 the cap is full and Ruskin, not an admin, wants a third episode. The refusal says "Reproductive Rights (alex)", the row shows "alex" as in it, and `may_close` refuses Ruskin ("somebody else is in that episode"). Only an admin can free the seat, which is the parked-feature state security-2 was written to end.
- Evidence: probe.py: an entry whose only page request was 3 hours ago, one `note_agent("alex")`, and the result is `occupants == ['alex']`, `last_in == ('alex', 0.0)`, `may_close(..., "ruskin", False)` refused, and a cap sentence naming "Repro (alex)".
- Ledger: related to security-1 / security-2 (2026-09-18b, fixed; this is the side effect of the fix)
- Suggested fix: keep agent liveness separate from page occupancy. Show it as "alex's Resolve is attached", not as a person in the episode, and let the idle rule look at page requests only. Alternatively, count an agent stamp only within N minutes of that editor's last page request, or only when the agent is doing real work (a state push whose version changed, or a result).

### logic-cards-3 - Routing is by person, not by computer, and nothing tells the person: opening a second episode (even one still loading, even for a colleague) moves their Resolve, and one editor's two machines cannot be in two episodes
- Severity: medium
- Confidence: CONFIRMED (mechanism); PLAUSIBLE (how often it bites)
- Where: dashboard/src/ccsync_dashboard/cards_landing.py:224 (`cards_open` calls `note_visit` on a LOADING entry); cards_pool.py:324-339 (`engine_for`, keyed on editor only), :347-357; cards_tunnel.py:161-170 (the no-engine sentence); cards_landing.html:21-25
- What: `_where` holds one slug per EDITOR, and every agent of that editor is routed through it. That breaks three things the design promises:
  - docs/CARDS_TWO_PROJECTS.md 1a says "an editor with two machines can be live in two projects at once". Both of Alex's machines (Creator-1 and Razer) send state into the same engine, and `agent.py:348` keeps whichever pushed last.
  - Pressing [ OPEN ] on the landing page points `_where` at the new entry while it is still LOADING. That detaches the editor's agent from the episode they are working in for the whole build. During that time the agent is told "alex is not in a Timeline Cards episode", which is false. When the build finishes, the agent is attached to the new episode. Opening an episode is not the same act as moving your Resolve into it, but the code treats it as one.
  - The landing page says "One episode at a time per person". Nothing enforces that. It is also the opposite of the "laptop and phone, two episodes" pair the design is built around, and the page never says that Resolve follows the last episode you touched.
- Failure scenario: Alex is conforming Repro Rights from his laptop with Creator-1's Resolve attached. He opens Framing Formosa from his phone so it is warm for Ruskin. From that click, his laptop page shows the Resolve agent away and any queued edit on Repro Rights is left undelivered. Once Formosa is ready, Creator-1's state pushes go into Formosa's engine. Alex has no way to learn this from any page.
- Evidence: code as cited. The routing flip itself and the pending/result split are already written up by wave 1 as bug-dash-cards-jobs-2. This finding is the design angle: the wrong key, the loading-detach and the missing UI.
- Ledger: related to bug-dash-cards-jobs-2 (this hunt, wave 1)
- Suggested fix: route on the (editor, machine) the tunnel already knows (`body.machine` / `agent_name`), not the editor alone, and let the agent say which Resolve project it is sweeping. At minimum, do not call `note_visit` for a LOADING entry from `/cards/open`. Replace "One episode at a time per person" with the true sentence, "your Resolve follows the last episode you opened".

### logic-cards-4 - The landing page ignores `?want=`, so a phone sent back from its installed episode app is shown a bare list, and "carry on" only remembers episodes you personally built
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_landing.py:179,188 (`want` is computed and passed to the template), cards_landing.html (never reads `want`); cards_landing.py:232 (`remember` is only called from `POST /cards/open`) and :373-374 (its docstring says the dispatcher calls it, which it does not)
- What: `CardsDispatch._not_open` sends every navigation to an episode that is not open to `/cards/?want=<slug>`. After a container restart or an admin close, that is where an installed phone app lands. The template never uses `want`, so there is no "Civil Defence is not open: press [ OPEN ]" line, no highlighted row, and no forwarding once the build finishes (the meta refresh just stops). The carry-on cookie is set only when this browser pressed [ OPEN ] on a not-yet-open episode. Entering an episode through a READY row's `<a href>` or the installed app never updates it, so "carry on" points at the last episode you built, not the last one you were in.
- Failure scenario: the dashboard image updates overnight. Ruskin opens his installed Framing Formosa app and lands on a generic TIMELINE CARDS table with no mention of Formosa and no carry-on button (nothing is ready). He has to find the row, press [ OPEN ], watch the page refresh, and then find and press [ OPEN ] again on the same row.
- Evidence: `git grep want HEAD -- dashboard/templates/cards_landing.html` finds nothing. `remember(` has one caller at HEAD (cards_landing.py:232).
- Ledger: new (the uncommitted cards_catalog / `on_enter` work in the tree may be heading at the carry-on half)
- Suggested fix: render a `want` banner with the episode's own [ OPEN ] form. While `want` is LOADING, redirect to its href when it turns READY instead of just stopping the refresh. Set the carry-on cookie when a navigation enters an episode.

### logic-cards-5 - The landing page still says closing is an admin act, three lines under a refusal that tells non-admins to close one themselves
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/cards_landing.html:116-120; dashboard/src/ccsync_dashboard/cards_landing.py:243-245 (docstring); against cards_pool.py:434-437 and :439-465
- What: the footer says "Closing one is an admin act because it takes the episode away from whoever is in it." Since security-2, `may_close` lets a non-admin close their own episode or any episode idle for 15 minutes. The cap refusal says so ("or close an idle one yourself"), and the page draws [ CLOSE ] for them. The two sentences are on the same page and contradict each other, so a non-admin who sees [ CLOSE ] beside an idle episode is told by the page not to press it.
- Failure scenario: a non-admin editor is refused a third episode, reads "close an idle one yourself", sees [ CLOSE ] on the idle row, reads the footer, and goes to find Alex instead.
- Evidence: template text as cited; `may_close` and `_full_sentence` as cited.
- Ledger: new (text left behind by security-2)
- Suggested fix: "You can close an episode you are in, or one nobody has used for 15 minutes; an admin can close any."

### logic-cards-6 - With the Cards mount absent or disabled, the tunnel tells every agent to set DASH_CARDS_SERVER_URL instead of naming why the mount did not take
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards_tunnel.py:184-186 (`_routed` returns (None, None) whenever there is no pool) and :247-259 (`_upstream`'s 503 sentences); companion/src/ccsync_companion/timeline_cards_role.py:914-921, :1021-1025
- What: `app.state.cards_pool` exists only when `mount_cards` returned MOUNTED. On a dashboard where the mount came up ABSENT (vault bind not there at boot, checkout missing) or DISABLED, every agent call falls through to the phase-2 proxy and gets a 503 "no Timeline Cards server is configured here (set DASH_CARDS_SERVER_URL on the dashboard)". The role reports that verbatim as HEALTH_UNREACHABLE on the fleet grid. The phase-2 proxy has been the fallback since phase 3, so this points the owner at a setting that does not fix the problem. The real reason, `app.state.cards_detail` (for example "the vault root is not mounted (/vault)"), is already available.
- Failure scenario: after a reboot the NAS share mounts late, Cards comes up ABSENT, and Creator-1's grid chip says "the dashboard answered HTTP 503 for pending: no Timeline Cards server is configured here (set DASH_CARDS_SERVER_URL ...)". Alex, who is non-technical, is sent looking for a standalone server URL.
- Evidence: code path as cited. `mount_cards` sets `cards_pool` only after the vault, checkout, import and a2wsgi checks all pass.
- Ledger: new
- Suggested fix: in `_routed`/`_upstream`, when `cards_status` is not MOUNTED and no `cards_server_url` is configured, answer with the mount's own status and detail ("Timeline Cards is not running on this dashboard: <cards_detail>").

### logic-cards-7 - An episode build has no timeout: a hung vault read is [ OPENING ] forever, refreshing every 3 s, holding a seat, with no elapsed time
- Severity: low
- Confidence: PLAUSIBLE (depends on the share hanging rather than refusing, which `RETRY_FLOOR_SECONDS`' own comment names as a real shape)
- Where: dashboard/src/ccsync_dashboard/cards_pool.py:415-418, :467-486 (`_run_build` has no deadline); cards_landing.html:31-39
- What: the state machine is LOADING -> READY | FAILED, and only the builder thread can leave LOADING. A build blocked in a scandir on a hung SMB/NFS share stays LOADING for the life of the container. It counts toward the cap, and the page shows "it takes a moment, and the page refreshes itself until it is ready" and reloads every 3 seconds indefinitely, for everyone viewing /cards/. After 15 minutes the entry becomes closable by anyone, but nothing tells them that the open has stalled rather than being slow.
- Failure scenario: the vault share stalls mid-open. A phone left on /cards/ reloads every 3 s all afternoon, one of two seats is gone, and the only visible state is "OPENING".
- Evidence: no timer or deadline anywhere in `EnginePool`. `Entry.opened_at` is recorded but never shown or checked.
- Ledger: new
- Suggested fix: show "opening for N min" from `opened_at`. After a limit (say 5 min), mark the entry FAILED with "the vault did not answer" so it frees its seat and stops the refresh. If the orphaned thread finishes later, the existing orphan path discards its result.

### logic-cards-8 - /api/v1/health reports a Cards agent as attached if one has ever pushed, forever
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cards.py:777 and :783, :790 (`bool(getattr(e.engine, "agent_name", None))`)
- What: `agent_name` is set by the first `agent_state` and never cleared (agent.py:67, :348). The engine's own liveness test is `agent_here()` (`agent_seen` within AGENT_GONE_S). So the health block says `agent: true` for an episode whose agent left hours ago, which is the "green while dead" shape.
- Failure scenario: Creator-1's companion quits at 18:00. At 21:00 `/api/v1/health` still reports `cards.agent: true` and `open[i].agent: true`, while the page itself says "Resolve agent away since 18:00:04".
- Evidence: the other repo's agent.py:67, :155-162, :348.
- Ledger: new
- Suggested fix: use `engine.agent_here()` when it exists, and report `agent_name` separately as "last agent".

### logic-cards-9 - The Cards role calls a routine stale-result refusal "the dashboard is discarding this computer's pushes"
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/timeline_cards_role.py:940-965 (`_note_answer`), :1039-1046 (`health`)
- What: `_note_answer` treats any `error` or `note` in a 200 answer as "the editor is in no episode" (wire-3). `/agent/result` also answers `{"ok": false, "error": "that request is no longer open"}` whenever the engine has already let an edit go: the lost-agent path in `agent_pending`, or a request id from before a restart. That ordinary refusal is logged as a WARNING, "the dashboard is discarding this computer's pushes", and it replaces the fleet grid detail until the next clean call. An engine exception wrapped by `_local` is labelled the same way.
- Failure scenario: an edit times out on the engine side, and the result arrives late. The companion log and the grid say the dashboard is discarding pushes, which sends the reader looking at routing instead of at the one late edit.
- Evidence: agent.py:1206-1210 (`agent_result`'s refusal), cards_tunnel.py:220-236 (`_local`).
- Ledger: new (a side effect of wire-3 / dash-cards-8)
- Suggested fix: treat only the tunnel's own no-engine sentence as "not attached": have the tunnel add a machine-readable key such as `"attached": false`, and match on that instead of on any `error`/`note`.

## Coverage note
cards_ai.py was read for the run/status seam only (provider choice, the not-Claude and not-probed sentences); the session store, trimming and model-learning halves were not read. cards_wsgi.py was not read. The other repo's page (what a phone actually renders on a 409, or when the agent is away) is out of scope and was read only as far as agent.py's agent routes. Two defects in this territory are already written up by wave 1 and are not repeated here: the pending/result routing split (bug-dash-cards-jobs-2) and pinned jobs waiting with no engine (bug-dash-cards-jobs-3). The uncommitted cards_catalog.py / `on_enter` changes in the working tree were not hunted.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/jobs.py:467 (`can_pin`): whether a spent media job is pinned or abandoned depends on whether someone happens to have an episode open at that moment; after every restart the pool is empty (see bug-dash-cards-jobs-3 for the other half).
