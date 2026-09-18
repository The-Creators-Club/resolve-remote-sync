# security - auth/session gates, credential binding, path traversal, secret leakage, fail-closed (lens, second hunt of 2026-09-18)

Files read (with approximate coverage):
- `git diff` in full over the security surfaces: `dashboard/src/ccsync_dashboard/app.py`
  (`_OPEN_EXACT`, new `_OPEN_GET_ONLY`, `_open_path`, `login_gate`, `csrf_gate`,
  `_origin_mismatch`, `body_size_gate`, `_BODY_LIMITS`, `_COMPANION_TOKEN_PATHS`,
  `unhandled_error`, `_record_off_the_loop`, `_install_busy_handler_on_mounts`,
  `check_persisted_secrets`), `secrets_boot.py` (`_write_secret_file`), `sessions.py`,
  `oidc.py` (`username_from_claims`), `cards_landing.py` (full), `cards_pool.py` (full),
  `cards.py` (`data_dir_for`, `CardsDispatch`, `evict`, `mount_cards`), `cards_tunnel.py`
  (`_wait_for_an_engine`, `cards_agent_pending`), `cards_exec.py`, `locate.py` (full),
  `api.py` (locate route, `_require_fleet_caller` reachability, `_upgrade_info` /
  `_machine_can_be_offered`, `_by_target_machine`, the new report sub-models,
  `FileMoveResultIn._unknown_state_is_no_state`, `standins_*`), `db.py`
  (`command_machine_names`, `machines_by_machine_id`, `pending_file_moves`,
  `record_standins_placed`, `standins_known`), `notices.py` (`redact_path`,
  `error_detail`, `record_server_error`), `alerts.py` (`_check_broll_archive`,
  `_check_file_moves`), `release_feed.py` (`channel_retractions`, `repair_provenance`),
  `dashboard_update.py`, `deploy/select_code_root.py`, `ui.py`, `assignments.py`,
  `templates/cards_landing.html`, `templates/partials/*`
- `companion/src/ccsync_companion/broll_server.py` (the whole 8899 diff:
  `build_status_response`/`_standins_owed`, `derive_insert_paths`,
  `_no_self_referential_proxy`, `plan_insert`, `build_insert_response`, the
  upgrade in-flight set)
- `broll/web/app/routes_api.py` (`insert_target_detail`, `_insert_object`),
  `routes_batches.py`, `ingest_batches.mark_uploaded`, `routes_share.py` route table,
  `ytdl/web/ytdlweb/routes_api.py` + `db.py`, `music/web/musicweb/routes_batches.py`,
  `server/publish_db.py`
- The morning's `hunters/security.md` and `verifiers/security-regression.md`, and
  `ledger/dashboard.md` CR-285P / CR-285Y / CR-285AF / CR-285AG plus the ledger's
  "what was declined" section

Tests run: none of the repo suites (lens work; the owner's "tests run once, centrally"
rule). Two ad-hoc probes from the dashboard venv against the real modules, written to
the scratchpad, no repo file touched and no live process:
`probe_close.py` (EnginePool.may_close) and `probe_open.py` (`_open_path`). Output is
quoted in the evidence below.

Verdict on the four findings this lens filed this morning: **security-1 (CR-285Y),
security-3 (CR-285AG) and security-4's parse-cost half (CR-285AF) are properly and
completely fixed** - see the coverage note for what I checked. **security-2 (CR-285P) is
fixed in the direction it was asked for, and opened three neighbours**, which are
findings 1-3 below.

## Findings

### security-1 - the new 15-minute idle release measures SERVER REQUESTS, so an editor working OFFLINE in Cards is evictable by any other editor
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (the worst end of the consequence)
- Where: `dashboard/src/ccsync_dashboard/cards_pool.py:405-430` (`EnginePool.may_close`,
  the `if not occupants: return ""` arm) with `cards_pool.py:228-231`
  (`Entry.occupants`) and `cards_pool.py:329-339` (`note_visit`), fed only from
  `dashboard/src/ccsync_dashboard/cards.py:538-552` (`CardsDispatch._note`) and
  `cards_landing.py:191` (`cards_open`).
- What: CR-285P's rule is "or one nobody has been in for `ACTIVE_SECONDS`". "Been in" is
  `Entry.seen`, which is stamped only when a request for that episode is SERVED by this
  container. An offline Cards session - a shipped feature of that page, and the thing the
  same fix pass deliberately protected when it narrowed the `/cards/sw.js` kill switch to
  `cards-shell-*` so it would stop deleting `cards-media`, "the clips an editor
  deliberately downloaded for an offline session (the 2026-09-12 incident)" - makes no
  server requests at all. Neither does a phone with the screen off, a laptop asleep, or
  an editor who has left the page open and gone to stage the cut in Resolve. Fifteen
  minutes of any of those empties `occupants()`, and `may_close` then returns "" for
  every signed-in user on the dashboard, admin or not. Before this change only an admin
  could take that engine away.
- Failure scenario: editor A opens `/cards/p/civil-defence-xxxx/`, loses the tunnel (the
  2026-09-12 shape: laptop off the tailnet) and keeps working against the service worker.
  Sixteen minutes later editor B, blocked by the cap, is shown [ CLOSE ] beside A's
  episode on the landing page and presses it. `drop()` stops A's engine. A comes back
  online: their replay meets a freshly built engine (the state it replays against is
  whatever was last written to `<data>/cards/<slug>`), or - if both seats have since been
  taken - the cap refusal, with a queue of offline edits in the browser and nowhere to
  put them. `drop()`'s own docstring says the close is not free upstream either.
- Evidence: scratch probe against the real `cards_pool` in the dashboard venv:
  ```
  EpB state: ready occupants: ['alice']
  may_close(bob) while alice active: 'somebody else is in that episode. ...'
  occupants after 15 min quiet: []
  may_close(bob) after 15 min quiet: ''
  ```
  (the second state was produced by ageing `entry.seen["alice"]` past `ACTIVE_SECONDS`,
  which is exactly what fifteen minutes with no served request does).
  `dashboard/tests/test_cards_pool.py:550-562` pins the "nobody in it" arm as correct and
  never asks what "in it" means for a client that is not talking to the server.
- Ledger: "CR-285P does not fix security-2 without opening a neighbour" (new neighbour;
  the ledger's own note at `ledger/dashboard.md:1238` weighs the thread leak of a bored
  closer but not this).
- Suggested fix: make an offline-capable client keep its seat honestly - either have the
  page send a cheap keep-alive that `_note` sees while a session is open (it already
  polls when online, so this is only about the offline window), or require the closer to
  be an occupant/admin when the entry has EVER had an occupant and fall back to the
  no-occupant rule only for an entry nobody has entered at all. At minimum, raise the
  idle bound well past a phone's sleep and say in the button's title how long the
  episode has been quiet.

### security-2 - a co-occupant may close an episode out from under the other people in it, which is the one act the ledger says stays admin-only
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_pool.py:424-428` (`may_close`:
  `if editor in occupants: return ""`).
- What: `cards_close`'s docstring and `ledger/dashboard.md:1238-1242` both state the
  invariant: "Taking an episode away from whoever is IN it is still the act that must not
  happen by accident, which is why an admin is still the only person who can do that."
  The code enforces that only when the closer is NOT an occupant. Two editors in one
  episode - the ordinary Cards shape, a phone staging while a desktop conforms, or two
  people on one cut - means either of them can stop the engine under the other with one
  POST, and the landing page draws the button for both.
- Failure scenario: A and B are both in `civil-defence-xxxx` (both have made a request in
  the last 15 min). B finishes, sees [ CLOSE ] beside it, presses it to "free a seat".
  A's engine stops mid-session; A gets whatever the dead-engine path gives them, and the
  ledger's stated protection never applied.
- Evidence: probe output -
  `occupants: ['alice', 'bob']` / `may_close(bob) with alice also in: ''`.
  The regression test (`test_cards_pool.py:550`) only checks a NON-occupant (`leso`) is
  refused while `jsmith` and `ruskin` are in, so it passes either way.
- Ledger: "CR-285P does not fix security-2 as stated" (the prose and the code disagree).
- Suggested fix: one line - `if occupants and occupants != [editor]` is already the arm
  above; delete the `if editor in occupants: return ""` fall-through, so being one of
  several occupants is not by itself permission to end it for the others. If the wider
  rule is wanted, say so in the docstring and the ledger instead.

### security-3 - `_state`'s comment says a FAILED episode is closable by anybody; for the first fifteen minutes it is closable by nobody but its opener
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_landing.py:104-115` (the comment and the
  `may_close` call) vs `cards_pool.py:405-428`, with `cards_landing.py:184`
  (`cards_open` calls `note_visit` on the entry it just created, before the build thread
  has failed).
- What: the comment asserts "A `failed` entry is closable by anybody (it has no occupant
  and no engine): that is the admin door dash-cards-2 asks for, widened to everyone
  because there is nothing to take away." A failed entry DOES have an occupant - the
  person whose click created it, recorded by `note_visit` immediately after `open()`
  returns the LOADING entry and kept for `ACTIVE_SECONDS` regardless of what the build
  thread then does. So `may_close` refuses every other non-admin for fifteen minutes, and
  the template draws no [ CLOSE ]. The practical damage is small because CR-285O also
  made `open()` treat a FAILED entry as absent, so [ OPEN ] retries after
  `RETRY_FLOOR_SECONDS` - but the comment is the thing a future reader will trust.
- Failure scenario: A's open of an episode fails (share not up). B, blocked by the cap,
  is told by the landing page that the failed entry cannot be closed by them, and the
  comment says that state is impossible. A failed entry holds no seat, so nothing is
  actually stuck; the cost is a false statement in the one place the rule is explained.
- Evidence: probe output -
  ```
  state: failed | occupants: ['alice']
  may_close(bob, non-admin): 'somebody else is in that episode. ...'
  may_close(alice): ''
  ```
- Ledger: "CR-285P/CR-285O comment does not match the code" (new).
- Suggested fix: either clear `entry.seen` when a build fails (a failed entry really has
  nothing to take away, which makes the comment true), or correct the comment.

### security-4 - the GET-only rule stops at the static assets; `/setup`, `/api/v1/site`, `/api/v1/health` and `/api/v1/setup/status` are still open to every verb
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:160-175` (`_OPEN_GET_ONLY`, `_open_path`)
  against the rest of `_OPEN_EXACT` at `app.py:40-127`.
- What: CR-285Y's own stated purpose is that "the next handler registered at one of these
  names would inherit an unauthenticated write door with nothing in its diff to say so",
  and it correctly excludes `/login`, `/api/v1/login`, `/api/v1/report`,
  `/api/v1/diagnostics`, `/api/v1/ssh-key` and `/api/v1/setup/admin`, which are POST
  targets with their own credential. But four remaining members are GET pages/readers
  with no non-GET use anywhere: `/setup` (an HTML page whose gate lives inside
  `ui.page_setup`), `/api/v1/site`, `/api/v1/health` and `/api/v1/setup/status`. They
  answer 405 today only because no POST route exists at those paths; the door is the same
  door the fix closed for the other eight.
- Failure scenario: a later change adds `POST /api/v1/setup/status` (the wizard's own API
  prefix already has both shapes) or a POST action to the setup page. It is
  session-exempt at the middleware from the moment it is written, silently, and the
  in-handler gate is the only thing between it and an anonymous caller.
- Evidence: probe against the real `_open_path` -
  ```
  /setup                GET=True POST=True DELETE=True
  /api/v1/site          GET=True POST=True DELETE=True
  /api/v1/health        GET=True POST=True DELETE=True
  /api/v1/setup/status  GET=True POST=True DELETE=True
  /favicon.ico          GET=True POST=False DELETE=False
  ```
  `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py:123-141` pins only the
  eight static names and the five credentialed POST targets; these four are in neither
  list, so nothing notices.
- Ledger: "CR-285Y does not fix security-1 for the whole set" (partial; the finding named
  the PWA paths, and the fix's own comment claims the wider rule).
- Suggested fix: move the four read-only members into `_OPEN_GET_ONLY` (they are GET/HEAD
  today and nothing in the tree asks for more), and add them to the test's first loop, so
  the list that is method-free is exactly the list of credentialed POST targets.

## Coverage note

Checked in this pass and found SOUND, so a later hunt does not re-walk them:

- **CR-285Y (security-1, this morning)**: `_open_path(path, method)` is correct -
  `_OPEN_GET_ONLY` is a subset of `_OPEN_EXACT`, the `_OPEN_PATTERN` branch is covered,
  HEAD is allowed, and `login_gate` passes the real verb. The residue is finding 4 above.
- **CR-285AG (security-3)**: fully fixed. `cards_landing` now has exactly ONE
  `set_cookie`, inside `remember()`, and its only caller passes
  `auth.cookie_secure(settings, request)`. No `request.url.scheme` decision survives in
  the module (`grep -n "scheme" cards_landing.py` finds only the comment). The finding's
  side observation - that `remember()` is never called for a person who navigates
  straight to `/cards/p/<slug>/`, so "carry on with ..." never updates - is still true and
  is a UX gap, not a security one.
- **CR-285AF (security-4's parse half)**: the `_BODY_LIMITS` entry (512 KB) is the right
  shape and keeps the route's 413 sentence. I checked the ordering worry it invites and
  it is FINE: `login_gate` is registered after `body_size_gate`, so it is the OUTER
  middleware and already refuses `/api/v1/files/locate` without `_companion_token_ok` or
  a session; the body is therefore never buffered for an anonymous caller, and the
  route's absence from `_COMPANION_TOKEN_PATHS` is not the hole it looks like.
- **`secrets_boot._write_secret_file`** is now genuinely atomic (sibling temp, fsync,
  mode set on the fd before the rename, temp unlinked on any BaseException) and
  `check_persisted_secrets` compares the BYTES, with "cannot judge" never refusing a boot.
  This is the strongest security fix in the pass: the pre-fix shape could 401 every
  browser session and every non-expiring `cce1.` token in a fleet at once.
- **`oidc.username_from_claims`** now applies `db._USERNAME_RE`, closing the "a session
  whose name every write path refuses" gap, and refuses rather than coercing.
- **`release_feed.repair_provenance`** is correctly narrowed to one direction and never
  writes `git_sha`; `channel_retractions` now folds `kind`, so a recall spelled
  `"Companion"` is no longer silently suppressed. Both are real hardening.
- **`notices.redact_path` / `error_detail`** still hold under wire-2's change: installing
  the parent's `unhandled_error` on `/broll`, `/music` and `/ytdl` means `scope["route"]`
  is now the SUB-APP's route object, and every share route is a template
  (`/share/{token}/...`, `routes_share.py:145-261`), so no client-folder credential can
  reach a notice subject by that road. `error_detail` goes through `crash_report.redact`.
- **`cards_pool._run_build`** no longer renders another repo's exception into the browser
  (dash-cards-7). Verified live in the probe: `detail` came back as
  "this episode did not open (RuntimeError). The dashboard log has the detail." while the
  log line carried the full `psycopg: host=db user=secret` string I planted.
- **`db.command_machine_names` / `machines_by_machine_id`** are scoped
  `WHERE editor_username=? AND machine_id=?`, so the self-asserted `machine_id` on a
  report can only ever widen a command lookup within the reporting editor's own
  registry - not across editors.
- **`FileMoveResultIn._unknown_state_is_no_state`** is the right fail-soft shape and does
  not widen anything: an unknown word is dropped, not stored.
- **`/cards/close`** is session-gated at `login_gate` and origin-gated at `csrf_gate`
  (`_CSRF_ORIGIN_ONLY_PREFIXES`); the `Origin: null` arm is a refusal. Widening the route
  from admin-only to any session does not create a CSRF hole.
- **The occupants' names in the cap refusal** are an explicit, recorded owner decline
  (`ledger/dashboard.md:1243-1247`) and are NOT re-reported.

Not covered, and deprioritised because nothing in this diff touched them:
`help.resolve_document`'s audience gate, `routes_share`'s token lifecycle and
`PUBLIC_VIDEO_COLUMNS`, `internal_sftp`, `cli_tools`' sign-in pty and its secret files,
`release_trust`'s signature verification, `setup_api`'s first-run window, the
`music`/`ytdl` mount gates, and the companion's `loopback_guard` (unchanged file). The
suite still has no test asserting that a co-occupant cannot close an episode
(finding 2), none asserting what "idle" means for an offline client (finding 1), and
none covering the four method-free paths in finding 4.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py` (`StandinsPlacedIn.rels`): `max_length=200`
  bounds the LIST, not each string, so one report can write 200 rows of arbitrarily long
  TEXT into `broll_standins` (bounded only by `MAX_REPORT_BODY_BYTES`). Same shape as the
  pre-existing `StrayProjectsIn.paths`, so not new, but the new table is rewritten every
  thirty seconds per machine. -> dash-api / dash-db.
- `dashboard/src/ccsync_dashboard/cards_tunnel.py` (`_wait_for_an_engine`): the 25 s hold
  runs in a Starlette threadpool worker, one per companion with the cards role on, held
  continuously from every container restart until somebody opens an episode. Bounded by
  the fleet size today; worth a number in `docs/CARDS_TWO_PROJECTS.md` §12's accounting.
  -> dash-cards / res-fleet.
- `companion/src/ccsync_companion/broll_server.py` (`build_status_response`): `/status`
  now calls `broll_standins.given_up_upgrades()` on every poll, a disk read per status
  request from the b-roll page's poller. -> comp-broll-tiers.
- `dashboard/src/ccsync_dashboard/collector.py` (`_moves_including_carried_halves`):
  cross-cycle pairing decides, from two different passes, that a vanish in project A and
  an appearance in project B are the same file, and the result is a command that RENAMES
  that file on every editor's disk. Whatever the pairing key is, a false pair is a wrong
  rename fleet-wide; worth an adversarial read of the matching rule specifically.
  -> dash-collector-alerts / res-fleet.
