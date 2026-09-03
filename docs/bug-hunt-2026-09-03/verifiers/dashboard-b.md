# verdicts — dashboard-b

Verifier notes: all work read-only on the repo at HEAD 097f5a3 (only
`docs/DOCKER.md` dirty). Scratch scripts under `scratchpad/v/`
(offline.py, inv.py, win.py, weekly.py). Dashboard venv used for every run.

## dash-collector-1
- Verdict: DOWNGRADED to low
- Reasoning: The mechanism is exactly as reported and I reproduced it. `scan()`
  (alerts.py:1560-1576) files a crashed check under `CHECK_FAILED.kind` with
  `subject = kind.kind`, and `compose_weekly`'s clean list (alerts.py:1786)
  tests only `by_kind.get(k.kind)`, so the crashed kind is counted and printed
  as `ok - <what>`. `deliver()` (alerts.py:1998-2000) does subtract those
  subjects, so the two halves of the module genuinely disagree. I am
  downgrading because the harm is bounded and self-correcting inside the same
  document: the identical report prints `COULD NOT BE CHECKED (1)` naming the
  same kind and its exception four lines later, and `scan` independently emits
  a SEV_ERROR `check_failed` finding that `deliver` mails at once. So the
  operator IS told; what is wrong is one contradictory line and a wrong
  `(n of N)` count, not a silent all-clear.
- Evidence: my repro (`scratchpad/v/weekly.py`, `ALERT_KINDS[0].check` replaced
  by a raiser, migrated temp DB):
  ```
  '  [check_failed] breaker_tripped'
  'CHECKED AND FOUND NOTHING WRONG (41 of 43)'
  "  ok - a computer's proxy download brake"
  'COULD NOT BE CHECKED (1)'
  '  breaker_tripped: RuntimeError: kaboom'
  ```
  (43 kinds today, not 40 as the hunter's text says.) Not in KNOWN_BUGS:
  lines 6118-6123 document the section's intended shape only.
- Fix note: the suggested fix is right and is a two-line change mirroring
  `deliver`'s existing `checked_kinds` computation. Nothing else reads `clean`,
  so it cannot break anything. Keep the `(n of N)` denominator at
  `len(ALERT_KINDS)` and drop only the numerator, otherwise the report loses
  the "43 kinds exist" fact.

## dash-collector-2
- Verdict: CONFIRMED (medium)
- Reasoning: I could not refute this and I reproduced both halves.
  `evaluate()` (invariants.py:762-768) turns any exception into
  `Outcome(CHECK_FAILED, ...)` whose `subjects` defaults to empty;
  `db.record_invariant_result` builds `kept` from those subjects and then
  unconditionally executes
  `DELETE ... WHERE invariant=? AND subject<>'' AND subject NOT IN ('')`,
  wiping every stored broken subject regardless of verdict. `run_cycle` only
  appends to `broken_subjects` on `INVARIANT_BROKEN`, so
  `clear_notices_of_kind(conn, "invariant_broken", [])` closes the subject's
  notice on the same pass. On the alerts side `_check_invariants` reads
  `db.broken_invariants` and therefore returns an empty list WITHOUT raising,
  so `invariant_broken` stays inside `deliver`'s `checked_kinds` and every one
  of those subjects is mailed as RECOVERED. That is the module's own stated
  invariant ("a check that could not run must never read as a check that found
  nothing") inverted, which is why I hold it at medium rather than downgrade.
  It is not high: an `invariant_check_failed` SEV_ERROR notice IS filed and
  mailed - it just names the invariant, not the subject, and it arrives
  alongside a "this has cleared" mail for that subject.
- Evidence: `scratchpad/v/inv.py` against a migrated temp DB:
  ```
  broken:               [{'invariant': 'tick_is_shared', 'subject': 'alex/base', ...}]
  notices:              [('invariant_broken', 'tick_is_shared: alex/base', None)]
  after failed broken:  []
  after failed notices: [('invariant_broken', 'tick_is_shared: alex/base', '2026-09-03T00:00:00+00:00')]
  ```
- Fix note: the suggested fix is right in shape. Gate the DELETE on
  `verdict in (INVARIANT_OK, INVARIANT_BROKEN)`. Do NOT also skip the summary
  row INSERT - the page needs the `check_failed` state stamped. The second half
  (seeding `broken_subjects` from the still-stored subjects of a `check_failed`
  invariant) is necessary too: without it the DB keeps the row but `run_cycle`
  still closes the notice on the very next pass. Check that `_counts`/`_note`
  are unaffected, and that a subject left in place keeps its OLD `checked_at`
  so the page's age wording does not claim a fresh check.

## dash-collector-3
- Verdict: CONFIRMED (medium)
- Reasoning: `alerts.py:1874` is a bare `client.starttls()`. I confirmed on the
  dashboard's own interpreter that `smtplib.SMTP.starttls` builds
  `ssl._create_stdlib_context()` when `context is None`, and that that context
  reports `check_hostname False verify_mode 0`. The channel is encrypted but
  unauthenticated, and the very next statement is `client.login(user, password)`
  with the stored SMTP secret. The refutation I tried - "the sink is off in the
  vendor build" - fails: the whole point of the setting is that customers turn
  it on, and the same module refuses a non-https webhook at BOTH save and send
  time precisely because a fleet diagnosis on the wire matters. So the mail
  path is inconsistent with the module's own standard, not merely imperfect.
  Not high because it needs an on-path or DNS-hijacking attacker.
- Evidence: `.venv/Scripts/python.exe` (3.12.10): `starttls` source shows
  `if context is None: context = ssl._create_stdlib_context()`;
  `ssl._create_stdlib_context()` -> `check_hostname False verify_mode 0`.
  The suite never exercises this - `_smtp_class` is stubbed in tests, which is
  exactly the layer that would break.
- Fix note: `client.starttls(context=ssl.create_default_context())` is correct.
  It WILL break a site using a self-signed internal relay, so ship it with the
  hunter's second half - catch `ssl.SSLCertVerificationError` and raise an
  `AlertError` naming the host, plus an explicit opt-out setting. Do not
  silently fall back to an unverified context on failure; that would be worse
  than today because it would look verified.

## dash-collector-4
- Verdict: CONFIRMED as a mechanism, DOWNGRADED to low
- Reasoning: The mechanism is real and I reproduced it exactly, so the hunter's
  PLAUSIBLE can be raised to certain on the code path. What I can partly refute
  is the impact sentence. The hunter writes "Nothing is sent, on the page or by
  mail" - the page is unaffected: the finding still comes out of `scan()` every
  cycle, still lands in `db.META_ALERTS_OPEN` (alerts.py:2073, read by
  ui.py:199) and still renders on the alerts panel. `alert_log` feeds only
  dedup, `_is_open` and the recovered path. So the defect is "a warn's
  mail/webhook notification is permanently muted for that subject", not "the
  dashboard goes quiet". With the trigger cost (500 newer `alert_log` rows;
  `ALERT_MAX_AGE_DAYS = 120` pruning neither helps nor hurts, since the cap is
  on the newest 500) that is a low.
- Evidence: `scratchpad/v/win.py` - one `folders_unfiltered` row for
  `ruskin/RUSKIN-PC`, then 600 newer rows:
  ```
  _is_open: True
  offered by _open_subjects: False   n= 500
  ```
  `db.fetch_alerts`'s `max(1, min(int(limit), 500))` (db.py:5219) means the
  caller cannot widen it, as reported. Worth adding: the `sink == SINK_NONE`
  branch of `send()` still writes an `alert_log` row per call, so a site with NO
  sink fills the window at the same rate as one with a sink.
- Fix note: the suggested fix is right and low-risk. A
  `SELECT kind, subject, MAX(at) FROM alert_log WHERE kind IN (...) GROUP BY
  kind, subject` is the natural shape, and the `ix_alert_log_kind` index
  (db.py:1248) already covers `(kind, subject, id)`. Do not simply raise the
  500 cap - that only moves the cliff and slows the Alerts page.

## dash-release-jobs-1
- Verdict: CONFIRMED (medium)
- Reasoning: The ordering is unambiguous in the source: `mount_cards` sets
  `app.state.cards_engine = None` (cards.py:337), starts the engine
  (cards.py:368-370), and assigns `app.state.cards_engine = engine` only after
  the a2wsgi wrap (cards.py:390). The wrap-failure branch calls
  `stop_engine(app)`, and `stop_engine` (cards.py:245-261) reads
  `app.state.cards_engine`, sees `None`, and returns at line 254 without
  touching the engine. The refutation I tried - "the engine-start failure
  branch above covers it" - does not hold; that branch returns before anything
  started successfully, and `stop_engine` is the only shutdown path, so a
  leaked engine is never collected. Medium, not high: a2wsgi is a pinned image
  dep, so the realistic trigger is `handler_mod.make_handler(engine)` raising on
  a version-mismatched `/cards-app` checkout - precisely the situation this
  mount exists to survive.
- Evidence: code read of cards.py:337 / 368-390 / 245-261 (the hunter's line
  numbers for `stop_engine` are off - it is at 245, not 341 - the substance is
  right). Consequence chain confirmed: with `cards_engine` None the health line
  says `absent`, `jobs.can_pin` sees no executor, and nothing an admin can see
  reports live sweep/ffmpeg threads. `tests/test_cards_mount.py` has no
  wrap-failure test.
- Fix note: prefer the hunter's second option - assign
  `app.state.cards_engine = engine` immediately after `engine.start()` and let
  the existing `stop_engine(app)` do the work. That also closes the same hole
  for any future statement added between the start and the mount. Calling
  `engine.stop()` directly in the except branch works but leaves the ordering
  trap in place. Either way keep the try/except; `stop_engine` already swallows.

## dash-release-jobs-2
- Verdict: CONFIRMED (medium)
- Reasoning: Verified end to end and I could not refute it. `_apply_policy`'s
  already-published branch (release_feed.py:678-687) calls
  `db.set_current_package(conn, platform, version, kind)` directly.
  `db.set_current_package` (db.py:3213-3247) checks `retracted_at` and nothing
  else - its own docstring says so. `grep blocks_on_dashboard_version` finds it
  only in `api.py` (3 sites: `_upgrade_info` 4743, the packages view 4860,
  `make_current_refusal` 5251) and `package_store.py:178`, never on the feed's
  path. `package_store.store_verified_package`'s comment at :172-176 explicitly
  claims the gate is there "so the human PUT and the feed's `current` policy
  cannot disagree" - that claim is false for a version the dashboard already
  holds. `select_offered_records` / `package_records` do no `requires_dashboard`
  filtering either, so nothing upstream saves it. The REL-1 soak gate
  (`api.make_current_refusal`) is bypassed on the same path, widening the
  finding slightly. The precondition (a staged row whose `requires_dashboard`
  exceeds this dashboard) is reachable: `make_current=0` PUTs are allowed by
  design, and a period under `stage` policy produces the same row.
- Evidence: code read plus the greps above; no test in `test_release_feed.py`
  or `test_release_channel.py` touches `requires_dashboard` on a feed
  re-current. Consequence confirmed at api.py:4743 - `_upgrade_info` returns
  `None`, i.e. the fleet silently stops being offered anything while the
  Packages page says CURRENT.
- Fix note: the suggested fix is right, and the second variant is better: have
  `_apply_policy` go through a shared helper rather than
  `db.set_current_package`. Be careful which gates that helper applies -
  `api.make_current_refusal` also carries the REL-1 soak gate and the UX-9
  unsigned-build typed confirmation, and a feed poller has no admin to type
  into a box. The minimum correct change is the `requires_dashboard` check;
  adding the soak gate to the feed path is a policy decision for the owner, not
  a silent extra.

## dash-release-jobs-3
- Verdict: CONFIRMED as a mechanism, DOWNGRADED to low
- Reasoning: The mechanism is exactly as described. `publish_from_feed` streams
  the artefact to a `.part` (release_feed.py:786, `ARTIFACT_MAX_BYTES` 200 MiB)
  and only then calls `store_verified_package`, whose
  `make_current and blocks_on_dashboard_version(...)` branch
  (package_store.py:178) unlinks the part and raises 409; `_apply_policy`
  catches `PackageStoreError`, logs and `continue`s, so no row is inserted and
  the next check repeats it. It does contradict `store_verified_package`'s own
  staging comment. I downgrade because the harm is bandwidth plus a delayed
  staging, both transient: it lasts only while the dashboard is behind, and the
  moment the admin updates the dashboard the next check publishes normally. No
  fleet state is wrong and nothing is lost. Note the default interval is
  86400 s but `POLLER_MIN_INTERVAL` is 60 s, so a site that shortened the
  interval turns this into a real download storm - that is what would push it
  back to medium.
- Evidence: code read of release_feed.py:688-700 / 731-791 and
  package_store.py:170-184; `release_feed.py:925`
  `max(POLLER_MIN_INTERVAL, ... 86400.0)`. Not covered by any test.
- Fix note: the suggested fix is right and is the cheaper of the two: test
  `blocks_on_dashboard_version` in `_apply_policy` and pass
  `make_current=False`, logging why. One caveat - once it is staged that way,
  nothing later flips it current when the dashboard catches up, because the
  next `_apply_policy` pass takes the `existing is not None` branch, which is
  the branch finding 2 says is ungated. Fix 2 and 3 together, or the pair
  leaves an ordering-violating build one poll away from being made current.

## dash-mounts-ui-1
- Verdict: CONFIRMED (high)
- Reasoning: I ran `node --check` myself and it fails at the reported line. I
  could not refute it on any of the three angles I tried. (a) Is the repo file
  what ships? Yes - `dashboard/deploy/Dockerfile:98` is
  `COPY dashboard/static /app/static`, with no minifier, bundler or codegen step
  anywhere in `server/`, `dashboard/deploy/` or `.github/`, and there is exactly
  one `assignments.js` in the tree. (b) Does the page work without JS? No -
  `templates/admin_assignments.html:154` is a plain
  `<script src="/static/assignments.js" defer></script>`, the checkboxes carry
  no `hx-*` attributes, and the whole file is a single `(function () { ... })();`
  IIFE, so a parse error unregisters every listener in it. (c) Is only the
  current tree broken? No - I checked the blob at each commit that touched the
  file: `9568d68 OK, 26cfd0d OK, 097745f OK, 55fdfa7 BROKEN, 0407b57 BROKEN`.
  Broken since 55fdfa7 (Fri 2026-08-28 13:16), which predates dashboard 0.7.17
  through 0.7.27, so the live image is carrying it.
- Evidence:
  ```
  $ node --check dashboard/static/assignments.js
  .../assignments.js:89
      return window.confirm(sentence + "
                                       ^
  SyntaxError: Invalid or unexpected token          (exit 1)
  ```
  `cat -A` on lines 87-91 shows real `$`-terminated lines inside the literal.
  Per-commit blob check as listed above.
- Fix note: the one-line fix (`sentence + "\n\nSync it there anyway?"`) is
  right. The regression gate matters more than the fix: add a test that parses
  `static/*.js`. `node --check` is the honest check but node is not a dependency
  of the dashboard venv or of CI's python job, so make it skip cleanly when node
  is absent - otherwise the gate is green on exactly the machine that needed it.
  The dependency-free fallback the hunter suggests (no quoted literal spanning a
  newline) would have caught this defect and is a reasonable belt.

## dash-mounts-ui-2
- Verdict: CONFIRMED (medium)
- Reasoning: I rendered `/offline` myself with a real session cookie
  (`auth.make_session_cookie`) in a TestClient and the response carries the
  username, a live CSRF token and the topbar. `offline.html` extends
  `base.html`, and `ui._render` sets `session_user` / `session_is_admin` /
  `csrf_token` on every render with no exemption for this route. On the worker
  side I confirmed the two halves that make it a precache rather than a
  same-request render: `sw.js:23-34` lists `/offline` in `PRECACHE`,
  `sw.js:67-70` fetches each with `cache.add(new Request(url, {cache:'reload'}))`
  (default `credentials: 'same-origin'`, so the session cookie goes with it),
  and the navigate handler at `sw.js:95-102` serves that frozen copy on any
  navigation whose fetch fails. `/offline` is not in `PASS_THROUGH`, and the
  copy is replaced only when `VERSION` changes the cache name. Medium is right:
  a stale-identity display always, an identity disclosure only on a shared or
  handed-over device.
- Evidence: `scratchpad/v/offline.py`, session cookie for `owen`:
  ```
  status 200 len 5650
  owen in body: True
  csrf meta: bd8dd206d4f1ca09...
  hx-headers: True
  anon status 200  owen in body: False
  ```
  The hunter's reading of `tests/test_pwa.py:193` is correct: it uses the
  anonymous `client` fixture and then splits on `</header>`, discarding the
  topbar, which is the only place the name appears.
- Fix note: the suggested fix is right; of the two options prefer rendering
  `/offline` from a session-free context (force `session_user=None`,
  `session_is_admin=False`, `csrf_token=""`) over dropping it from `PRECACHE`.
  Dropping it costs the offline page entirely on a cold cache, and the template
  would still carry a token on a direct-navigation render. Whichever is chosen,
  widen the test to a LOGGED-IN GET asserting the username is absent and the
  `csrf` meta empty, over the whole body - the current `</header>` split is what
  let this through.
