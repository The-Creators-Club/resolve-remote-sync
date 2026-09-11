# verdicts - dashboard-b

Scope: dash-collector-alerts-1..6, res-fleet-3 (merged into the first),
dash-mounts-ui-1..5, server-tools-1..3 (server-tools-2 merged with
dash-mounts-ui-1). Repo read-only; reproductions run from
`dashboard\.venv` with scratch scripts outside the repo.

## dash-collector-alerts-1 (with res-fleet-3) - CR-232 mails a false RECOVERED
- Verdict: CONFIRMED (high). One verdict for both reports: same line, same
  mechanism. res-fleet-3 rated it medium; I keep high because the false
  message is not only noise - the recovery pass writes the ledger row that
  CLOSES the condition, so the next scan that does see the project raises it
  as NEW again and the weekly report counts the week as clean.
- Reasoning: I could not refute it on any of the three escape routes I
  tried. (a) `_check_out_of_tree` (alerts.py:1778-1780) `continue`s before
  the finding is appended, so `(kind, subject)` never enters `deliver`'s
  `seen` set. (b) `deliver`'s recovery pass (alerts.py:3729-3733) skips only
  kinds whose CHECK FAILED this cycle - `out_of_tree` returned cleanly, so it
  is in `checked_kinds`. (c) `_open_subjects` (alerts.py:3809) groups over the
  whole `alert_log` and asks `_is_open`, so the subject is still open and is
  picked up. There is no `repeat=False`/suppression path between the two, and
  the subject key is `editor/machine` while the predicate now swings with
  whichever project is open at scan time.
- Evidence: code read of the three sites above; the hunter's repro
  (`r2["recovered"] == 1`) is consistent with them. `grep -an` of KNOWN_BUGS
  finds CR-232 recorded as FIXED with nothing about the recovery pass, so
  this is new. `dashboard/tests/test_alerts.py`'s CR-232 cases assert on the
  findings list only and never call `deliver`.
- Fix note: the hunter's fix is right in direction - the subject must stay in
  `seen`. `repeat=False` alone is NOT enough if it is implemented as "emit but
  do not send": check that whatever path is chosen still adds the subject to
  `seen` before any `continue`, since `seen` is what the recovery pass reads.
  A fix must also touch `dashboard/tests/test_alerts.py` (add the first
  `deliver`-after-a-project-switch case; the existing CR-232 cases stay
  green). The cleanest variant is the hunter's alternative - suppress only for
  a subject that has never been raised - because it keeps the owner's CR-232
  intent (silence for personal projects) without ever closing an open row.
  The OUT OF TERRITORY note about `resolve_health.project_open` is a real
  follow-on but not required for this fix.

## dash-collector-alerts-2 - `sink_deliverable` green off a never-sent weekly
- Verdict: CONFIRMED (high)
- Reasoning: reproduced exactly as reported. The asymmetry is plain in the
  code: the `ok = 0` probe excludes `NO_SINK_DETAIL`, the `ok = 1` probe
  (alerts.py:581-583) has no detail filter at all, and `run_cycle`
  (alerts.py:3868-3871) deliberately writes the no-sink weekly with `ok=1`.
  I looked for a second gate that would catch it - there is none:
  `sink_deliverable` is the single shared answer, and the `age >
  SEND_EVIDENCE_MAX_AGE_SECONDS` branch cannot help because the fake row is
  fresh. The one check whose entire job is proving the alarm reaches a person
  can be satisfied by a message that was never sent.
- Evidence: scratchpad `v_sink.py` against a fresh migrated DB -
  `db.record_alert(KIND_WEEKLY, "weekly", "", True, "generated, not sent (no
  sink configured)", 09:00Z)`, then `set_settings(alerts_sink="smtp", ...)`:
  ```
  no sink yet: (False, 'no mail server and no webhook is set, ...')
  AFTER:       (True, 'the smtp channel delivered something 3 hour(s) ago')
  ```
- Fix note: the suggested fix works, but pick the `sent_to` form over the
  `detail LIKE` form - the detail string is user-facing prose that will be
  reworded, and a green/red gate keyed on prose will rot silently. Note the
  `ok=1` probe has no `kind` filter either, so a HEARTBEAT row is legitimate
  evidence and must stay so. Other files a fix touches:
  `dashboard/tests/test_alerts.py` (the five existing `sink_deliverable`
  cases, KNOWN_BUGS line 11575) and anything asserting the no-sink weekly's
  recorded shape; the two callers (`invariants.py` check 15,
  `protection.py`'s `alerts_sink` line) need no change.

## dash-collector-alerts-3 - staleness never computed after a failed cycle
- Verdict: DOWNGRADED to medium
- Reasoning: the mechanism is real and I reproduced both shapes, but the
  "hours later the home page is silent" claim overstates it. (a) When the
  collector is still alive, a failed cycle already raises
  `collector_kind_failed` (SEV_ERROR, alerts.py:2799) and the collector panel
  renders that kind red with its LAST RUN age, so the incident is not silent -
  what is missing is the specific "the collector has stopped" verdict and its
  banner. (b) When the collector is genuinely dead, `_check_collector_stale`
  could never fire anyway: the alerts pass runs INSIDE the collector. So the
  only consumer that matters in the dead case is the web-rendered
  home page / `/api/v1/health`, which is exactly where the flag is wrong.
  The Syncthing-less half is the sharper defect and it is confirmed:
  `collector.py:386` makes a site with no `syncthing_url` first-class, and
  `_check_nas_engine` (alerts.py:1337) has no settings gate, so such a site
  gets `nas_engine_down` for ever while `collector_stale` can never fire.
- Evidence: scratchpad `v_stale.py`, `COLLECTOR_STALE_SECONDS = 180.0`:
  ```
  A failed-last-run:  syncthing_reachable=False  collector_stale=False
  B syncthing-less:   syncthing_reachable=False  collector_stale=False
  C ok-but-old:       syncthing_reachable=False  collector_stale=True
  ```
- Fix note: the suggested fix is right and the two halves are independent -
  take the `_check_nas_engine` gate even if the `MAX(finished_at)` change is
  deferred. One caution the hunter did not raise: `MAX(finished_at)` over ALL
  kinds would make `prune` (daily-ish) or `alerts` dominate the answer, so
  compute it over the kinds this deployment actually runs and keep
  `stale_after_seconds` meaningful against the shortest of them. Files:
  `db.fetch_collector_status` plus `db.collector_health`'s consumers
  (`api.py:1360`, `templates/partials/collector_health.html`), and
  `dashboard/tests/test_collector.py` / `test_health.py` which pin the
  current pairing of `reachable` and `stale`.

## dash-collector-alerts-4 - truncation reads as recovery
- Verdict: CONFIRMED (medium)
- Reasoning: both halves check out. `scan` caps at
  `MAX_FINDINGS_PER_KIND = 40` with no marker (alerts.py:2962), and the
  recovery pass's only exclusion is a kind whose check FAILED - a truncated
  kind is indistinguishable from a complete one. `_check_notices` is the
  readiest trigger and the ordering really is unstable: its query is
  `ORDER BY last_seen DESC LIMIT 40` with NO tiebreaker (alerts.py:1700-1703)
  while `db.open_notices` next door uses `ORDER BY last_seen DESC, id DESC` -
  so ties resolve to whatever SQLite returns, and `last_seen` is re-stamped
  every pass. The invariants half is confirmed too: `broken()` truncates to
  `MAX_SUBJECTS` (invariants.py:137) and only the surviving subjects reach
  `broken_subjects`, which is the keep-list handed to
  `clear_notices_of_kind` (invariants.py:1223). The `stored_broken` keep-list
  added for non-verdict passes does not cover a BROKEN-but-truncated verdict.
  Medium is right: it needs 40+ simultaneous subjects of one kind, which this
  fleet is far from, but nothing about it is theoretical on a larger site.
- Evidence: code read of the four sites above plus the `ORDER BY` comparison;
  the hunter's `deliver`-twice repro is consistent with `deliver`'s structure.
- Fix note: the suggested fix is right. Add one thing: give `_check_notices`
  (and any other `LIMIT`ed check) a deterministic tiebreaker, which removes
  the commonest trigger even before the capped-kind rule lands. A "and N more"
  synthetic finding must NOT be given the same subject as a real one or it
  will dedup against it. Files: `alerts.scan`/`deliver`,
  `invariants.run_cycle`, and the weekly report's "checked and found nothing
  wrong" wording in `compose_weekly`, which would otherwise still count a
  truncated kind as clean.

## dash-collector-alerts-5 - restore discards the truncation flag
- Verdict: CONFIRMED (medium), with one half of the failure scenario corrected
- Reasoning: the read is right - `_walk` returns `(found, truncated)` and
  returns early at `MAX_SCAN_FILES = 50_000`; `preview_restore` surfaces the
  flag as `"truncated"`, `restore_into_quarantine` binds both to `_cut`/`_cut2`
  and never reads them (recovery.py:369-370). Nothing downstream carries it:
  `result`, the audit row and `_remember` are all built without it, so a
  half-restore renders identically to a complete one. The hunter's SECOND
  half is overstated: `MAX_RESTORE_FILES = 20_000` is lower than
  `MAX_SCAN_FILES = 50_000`, so a truncated LIVE walk that misclassifies the
  whole tree as missing normally hits the 409 "over this server's limit"
  refusal instead of inflating the copy; and where it does not, the copy is
  additive into `.restored-<ts>/` and overwrites nothing. The real defect is
  the silent partial restore, which is enough on its own.
- Evidence: read of recovery.py:259-283, 301-322 and 361-380; constants at
  recovery.py:101-103.
- Fix note: the 409 form is the right one and matches the module's own
  posture ("the printed commands are the way through this one" is already the
  answer for a project too big to click). Carrying `"truncated": True` into
  `result` alone is not enough unless the template renders it - if you take
  the minimum, `dashboard/templates` (the restore result page) is the other
  file. `dashboard/tests/test_recovery.py` has no truncated-walk case to
  break, so this is additive.

## dash-collector-alerts-6 - server_error notices file the raw path
- Verdict: CONFIRMED (medium), and the hunter's open question resolves AGAINST
  the mount
- Reasoning: I resolved the one thing that kept this PLAUSIBLE. A parent
  `@app.exception_handler(Exception)` DOES run for an exception raised inside
  a mounted sub-app on this Starlette (1.6.0) - the sub-app's own
  ServerErrorMiddleware sends its plain 500 body and re-raises, and the
  parent handler is then invoked (its response is discarded because the
  response has started, but `record_server_error` has already run). So a
  `/broll/share/<token>/...` path that 500s writes the 128-bit credential
  into `notices.subject`, which the home page renders and `_check_notices`
  quotes verbatim into an `error` alert body and mail. The unbounded-growth
  half is confirmed separately: `db.prune` has no `DELETE FROM notices` and
  there is no other retention anywhere in the package.
- Evidence: scratchpad `v_mount.py` - parent handler saw
  `['/broll/share/SECRET123/x', '/top/abc']` (sub-app response body came from
  the sub-app, 500; the parent's handler still ran). `grep` for a notices
  DELETE/prune across `src/ccsync_dashboard` returns nothing.
- Fix note: the suggested fix is right, with a caveat - `request.scope["route"]`
  is NOT set for an exception raised inside a mounted sub-app (the parent
  matched a Mount, not a route), so the route-template normalisation must
  keep the "first two path segments" fallback and that fallback must NOT be
  two segments for `/broll/share/<token>` (segment 3 is the token there, so
  first-two is safe - but verify against the ytdl and cards mounts too). The
  retention clause belongs in `db.prune` beside the `alert_log` cutoff. Also
  worth pairing with a targeted 500 handler inside `routes_share.py` so the
  token never leaves that sub-app in the first place.

## dash-mounts-ui-1 (with server-tools-2) - /help serves the internal docs tree
- Verdict: CONFIRMED (high). One verdict for both reports.
- Reasoning: I could not refute any link in the chain. The route
  `page_help_document` (ui.py:4159) has no `_require_admin_page` - every
  admin page in ui.py calls it and these two do not - and the nav entry is
  `("help", "HELP", "/help", False)` with `admin_only` False by an explicit
  comment. `help.resolve_document` checks only the path SHAPE (.md, no `..`,
  realpath inside root); there is no audience allow-list for anything under
  `docs/`. The tree really is shipped by all three routes. The only thing I
  can narrow is the hunter's secondary claim about the Dockerfile's
  `COPY *.md` glob: the `_root/` half IS allow-listed, to exactly four names
  (`help.ROOT_FILES = README/SPEC/KNOWN_BUGS/CLAUDE`), so a future top-level
  `.md` would be in the image but not servable. That is a narrowing of the
  glob's danger, not of the finding: `KNOWN_BUGS.md` and `CLAUDE.md` are the
  two worst documents in the repo and both are on that allow-list, and
  everything under `docs/` - including `docs/bug-hunt-2026-09-11/` once
  committed - has no allow-list at all.
- Evidence: ui.py:4144/4159 vs the 16 `_require_admin_page` call sites;
  help.py:70 `ROOT_FILES`, help.py:296-311 (`_root` allow-list) and
  help.py:312-320 (no allow-list for the rest); `.dockerignore` excludes
  `docs` then re-includes `**/*.md`; `Dockerfile:110,118`;
  `build_dashboard_bundle.TREES` has `("docs","docs")` with
  `MD_ONLY_TREES = {"docs"}` and `ROOT_DOCS` (4 names);
  `install_dashboard_app.SHIPPED_ROOT_DOCS` + `_stage_docs_tree`.
- Which route, which gate (asked for explicitly): **all three shipping routes
  carry it** - image (`dashboard/deploy/Dockerfile:110` `COPY docs /app/docs`
  plus `:118` `COPY *.md /app/docs/_root/`, with `.dockerignore`'s `!**/*.md`
  re-include), OTA bundle (`tools/build_dashboard_bundle.py:107` `("docs",
  "docs")` under `MD_ONLY_TREES`, plus `ROOT_DOCS` at :125), and bind-mode
  deploy (`server/install_dashboard_app.py:_stage_docs_tree` with
  `SHIPPED_ROOT_DOCS` at :310). **The gate that must change is
  `help.resolve_document`** - it is the one place the code already declares
  path policy ("a path from a URL is checked in ONE place or in none of
  them"), so the audience allow-list belongs there, not in the route. Gating
  the ROUTE on `session_is_admin` instead is the cheaper fix but it is the
  wrong one long-term: the vendor's documents should not be in a customer's
  image for an admin to read either, and the admin at a second customer is
  not this studio's admin. Narrowing what SHIPS (a `docs/published/` subtree)
  is the only fix that closes it in all three routes at once; the gate change
  is what makes today's already-deployed images safe.
- Fix note: the hunter's fix is right. The test that pins the old behaviour
  is `dashboard/tests/test_help_page.py` line 383 (`as_user(client).get(
  "/help/GOTCHAS.md")`) and the index-listing assertions around line 375 -
  NOT `test_an_editor_can_read_it` (line 177), which only asks for the guide
  at bare `/help` and stays green under any correct split. Other files a fix
  touches: `help.doc_groups` (the index must not list what it will not
  serve), `setup_engine._find_eula` (the EULA must keep resolving - it is
  under `docs/legal/` and the wizard needs it), and the deep links in
  product copy that point at `/help/GOTCHAS.md#section-15` and
  `/help/_root/KNOWN_BUGS.md` (test_help_page.py:278-290), which would become
  admin-only or dead.

## dash-mounts-ui-2 - "safe to close" is per person, worded per computer
- Verdict: DOWNGRADED to low
- Reasoning: the mechanism is exactly as described - `safe_to_close`
  (ui.py:396-441) filters `transfers` and `queues` on `t["editor"] == editor`
  and never on machine, and every branch says "this computer". But the error
  is asymmetric and the dangerous direction is the one it does NOT take: the
  function is safe only when NO machine of that editor has an upload owed, so
  it can never tell someone their laptop is safe while it is still uploading.
  The wrong answer is the conservative one ("Not yet ... leave it running"
  about another machine), whose cost is a computer left on overnight and a
  confusing sentence - not lost footage. That is a copy defect, not a
  resilience defect.
- Evidence: read of ui.py:396-441 and the four call sites (619, 883, 1482,
  1497), all of which pass `scope.editor` and none a machine; the hunter's
  one-liner reproduces from the function alone.
- Fix note: the suggested fix is right, and the honest form really is to name
  the machines - the dashboard cannot know which browser is on which box.
  Note the naming is available: the transfer rows already carry `machine`, so
  no new query is needed. `dashboard/tests/test_templates_wave3_2026_09_04.py`
  is the suite that pins the current sentences, and the no-em-dash scan
  covers whatever replaces them.

## dash-mounts-ui-3 - run.sh writes ok:true for an unverified unblock install
- Verdict: DOWNGRADED to low
- Reasoning: the mechanism is confirmed by reading - `if [ "$want_unblock" =
  "$have_unblock" ] && [ ! -f "$UNBLOCK_MARKER" ]; then write_unblock_marker
  1 0 ""` records SUCCESS having run no pip and stat'd no package, which is
  the shape SELF_DIAGNOSIS.md forbids. What pulls the severity down is that
  the marker is only REPORTING the decision the installer itself already
  made: the install is skipped on the stamp alone on every boot, marker or
  no marker, so the green health route is downstream of a gate that was
  already stamp-only. The trigger also has to separate the stamp from the
  artefact, and in image mode both live on `/data` (`/data/.requirements-
  unblock-hash` and `/data/unblock-site`) so they are normally lost and kept
  together; in bind mode both live in the venv. CR-84's "an image update
  threw the manual install away" does not reproduce it, because `/data`
  survives an image update.
- Evidence: run.sh lines 242-248 (the backfill) against 250-266 (the real
  install, which writes the stamp only on success); `UNBLOCK_SITE` /
  `STAMP_UNBLOCK` both under `/data` at lines 179-184.
- Fix note: the suggested fix is right but INCOMPLETE as stated - adding
  `[ -d "$UNBLOCK_SITE/yt_dlp_plugins" ]` to the marker-backfill condition
  fixes the report while leaving the install gate stamp-only, so a wiped
  artefact would then read NOT CHECKED for ever and still never reinstall.
  Put the artefact test on the INSTALL condition (`want != have` OR artefact
  missing) and let the marker follow from it. Other files: `ytdl/web/tests/
  test_plugin_install_marker.py` and `ytdlweb.routes_api._plugin_install_state`
  must learn the third state before run.sh can write it, or the health route
  will treat `ok: null` as false.

## dash-mounts-ui-4 - CI runs one of the seven installer test scripts
- Verdict: CONFIRMED (medium)
- Reasoning: nothing to refute. `.github/workflows/ci.yml:192-195` is a single
  step naming `Test-DriveMapParser.ps1`, and `ls installer/tests/*.ps1`
  returns seven files. Since `tools/publish_latest.py` publishes the newest
  GREEN CI run on main, a green run is evidence about one of seven covered
  behaviours. I checked the obvious escape - that the other six run somewhere
  else in CI - and they do not appear anywhere in `.github/workflows/`; only
  `tools/run_all_tests.ps1` (a base-rig command) collects all seven. Medium
  is right: this is a missing gate, not a live defect, and the pathway A ship
  from Alex's terminal does run them.
- Evidence: the ci.yml step; the seven-file listing; run_all_tests.ps1's own
  comment that the list "has now been wrong twice".
- Fix note: the glob loop is the right fix and is what run_all_tests.ps1
  already does. Two cautions: the step must fail the job on the first
  non-zero exit (a bare `foreach` in pwsh will not, so check `$LASTEXITCODE`
  per script), and some of the seven may assume a Windows runner with a
  drive/registry fixture - run them once locally before wiring them in, or a
  correct CI change becomes a red build blamed on the loop.

## dash-mounts-ui-5 - same-version redeploy leaves phones on cached static
- Verdict: DOWNGRADED to low
- Reasoning: the reading is correct. `sw.js`'s `/static/` branch is
  cache-first with no revalidation and no background update, `CACHE` is
  `'ccsync-' + VERSION`, the `activate` sweep deletes only caches whose name
  differs, and `base.html`'s asset URLs carry no version query - so a static
  change shipped under an unchanged VERSION is invisible to an installed
  phone for ever. What makes it low rather than medium is that the trigger is
  a deliberate policy violation, not an ordinary operation: `ship.cmd` refuses
  a companion version already published, `publish_latest.py` refuses the same
  version with different bytes without `--allow-replace`, and the image-mode
  redeploy recipe reuses the LIVE DIGEST, i.e. the same bytes. Every recorded
  same-day redeploy in this project's history bumped the version.
- Evidence: static/sw.js lines 18-19, 79-87 (activate) and 95-129 (fetch);
  ui.py:4107-4125 (`__VERSION__` substitution, `Cache-Control: no-cache` on
  the worker itself).
- Fix note: of the two suggestions, stale-while-revalidate on the `/static/`
  branch is the safer one - seeding `CACHE` from a per-deploy runtime id
  discards the whole precache on every restart, which costs exactly the
  phones the PWA exists for. Whichever is taken, `dashboard/tests/test_pwa.py`
  pins the current cache-naming and would need updating.

## server-tools-1 - `-EmitKindExtras` gate fails open on an empty rollout
- Verdict: CONFIRMED (high)
- Reasoning: confirmed on both halves, and the PowerShell semantics are
  exactly as claimed - I ran them. `$null -eq @()` is `$false`, so
  `if ($null -eq $health -or $null -eq $health.rollout)` catches a MISSING
  property and not an empty array; the `foreach` then runs zero times,
  `$stragglers.Count` is 0, and the script prints "every reporting computer
  is on 0.9.55 or newer" having examined nothing. `api._rollout_block`
  (api.py:1512-1515) returns `[]` on ANY exception with HTTP 200, so the
  fail-open path is reachable from a dashboard-side fault the operator cannot
  see. The second hole is real too: `db.rollout_status` builds channels from
  `companion_packages WHERE kind='companion' AND is_current=1`, so a platform
  with machines but no current build contributes no channel and its machines
  are invisible even when the array is non-empty - the leso-Mac-on-0.9.2
  shape exactly.
- Evidence:
  ```
  PS> $h = '{"rollout": [], "version": "0.7.42"}' | ConvertFrom-Json
  type: System.Object[]   isnull: False   count: 0   stragglers: 0
  PS> ('{"version":"0.7.42"}' | ConvertFrom-Json).rollout -eq $null   -> True
  ```
  api.py:1508-1515 and db.py:4253-4256 read as described.
- Fix note: the suggested PowerShell fix is correct (`@($health.rollout).Count
  -eq 0`). The wire-level half matters more and touches the other side:
  `_rollout_block` must return `null` (or a distinguishable shape) on the
  exception path so "computed, nothing current" and "could not compute" stop
  sharing one representation - and `/api/v1/health`'s schema/consumers plus
  `tools/tests/test_release_scripts.py` (which already exercises
  `-EmitKindExtras`) are the files that move with it. Do not fix only the
  PowerShell side: an empty array would then refuse a legitimately fresh
  site, which is the safe direction but will be papered over with a flag the
  first time it bites.

## server-tools-3 - the `.zfs/snapshot` bind mount and mount propagation
- Verdict: CONFIRMED on the mechanism; NOT verified live (no NAS access from
  here, as the task states). Severity stays medium.
- Reasoning: the docker side is settled by documented semantics rather than
  by a guess. A bind in the short `host:container:ro` form is created
  `rprivate`, so mounts that appear under the source AFTER the container's
  mount namespace was set up do not propagate into it; only mounts already
  present at container start are carried (the bind is recursive). The ZFS
  side is the half that decides it, and it points the same way: traversing
  `.zfs/snapshot/<name>` triggers an automount performed by the kernel's
  usermode-helper in the INITIAL mount namespace, not in the caller's - so a
  snapshot first traversed from inside the container mounts on the host and
  the container keeps seeing the empty trigger directory. The intermittency
  the hunter predicts follows directly: a snapshot already automounted when
  the container started is visible, one that has timed out is not. I read
  `snapshot_volumes` and the whole `volumes:` list and confirmed no
  propagation option is emitted anywhere, and `remote_dir_exists` only
  `test -d`s the ctldir itself.
- Evidence: `install_dashboard_app.py:715-760` and `:762-766`
  (`f"{host}:{SNAPSHOT_MOUNT}:ro"`); `server/tests/test_snapshot_mount.py`
  asserts the emitted string, not what the container can read.
  `grep -an` KNOWN_BUGS finds the OPS-3 write-up (line ~8206) stating only
  that snapshots need a mount, nothing about propagation - this is new.
- Correction to the hunter's failure scenario: the outcome is very likely a
  MISLEADING REFUSAL rather than a silent empty restore.
  `preview_restore`/`restore_into_quarantine` both raise
  `RecoveryError(..., 404)` - "the snapshot X holds no folder for <label>.
  Either the project did not exist yet when it was taken, or its folder has
  been renamed since" - when `source.is_dir()` is false, which is what an
  unpropagated automount looks like. So the page fails loudly and blames the
  wrong thing; it does not restore zero files while claiming success. Medium
  is still right because the recovery feature is then non-functional in its
  intended deployment and the message sends an operator mid-incident after a
  rename that never happened.
- Fix note: the live check the hunter names is the right next step and must
  come first - `docker exec ... ls /snapshots/<name>/` on a snapshot nobody
  has touched for an hour. If it confirms, `bind-propagation: rslave` needs
  compose's LONG-form volume syntax, which means `compose_config()` in
  `server/install_dashboard_app.py` has to emit a different shape for this
  one mount (and `server/tests/test_snapshot_mount.py` plus the compose
  env/volume parity tests move with it). `rslave` on the container side alone
  is not enough if the host mount is `private` - the source mount needs
  `shared` propagation on the host, which is a NAS-side change the deploy
  cannot make silently. Reading snapshots over SSH is the fallback that needs
  nothing from the host, and is worth costing before committing to the mount.

## Notes
- Not re-verified here (not in this group): dash-collector-alerts-7 and -8,
  dash-mounts-ui-6/7/8, server-tools-4/5/6, and every OUT OF TERRITORY item.
  The `_send_smtp` login-without-TLS note in dash-collector-alerts' OUT OF
  TERRITORY section looks worth a group of its own.
