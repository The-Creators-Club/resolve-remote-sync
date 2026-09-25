# Fable review, wave 2, dashboard/ + server/ (2026-09-25)

Adversarial, read-only review of the uncommitted wave 2 fix pass over
`dashboard/` (src, templates, static, tests) and `server/`, against HEAD
`4462a2a`. Groups: d-db, d-api, d-diag, d-cards, d-auth, d-ops, d-ui, and the
server half of release-tools. `dashboard/design/` was not reviewed.

**`server/` has no change in the working tree.** The release-tools ledger's
edits are all under `tools/` and `docs/`; `git diff HEAD -- server` is empty.

## Method

- Read every hunk of `git diff HEAD` over the 95 changed files in scope and
  the ten untracked test files, against the eight ledgers and
  `wave2_results.json`.
- Traced each fix to its finding and to every other entry point of the same
  shape (the bucket/inheritance rule, the three mount gates, the file-move
  answer loop, the report validators, the untick routes, the recovery
  quarantine).
- Ran the new test files in the tree: d-db + d-api + d-auth -> 107 passed;
  d-diag + d-ops + d-cards + d-cards_owed + test_no_em_dash + CR-334/335 ->
  368 passed; a d-ui slice (package-wide dash scan, capped rows, safe_to_close,
  poll pause, keyed details) -> 26 passed, no xfail left.
- Test honesty: three scratch copies of `dashboard/` with HEAD's files swapped
  in (`db.py`; `api.py`+`ui.py`; `sessions/auth/setup_routes/site_store/
  setup_engine/oidc/provision/app.py`). The regression files fail there as
  claimed: d-db 23 failed / 9 passed (the 9 are the guards), d-api 26 / 10,
  d-auth 25 / 14. Nothing mocks away the thing that breaks: the bucket tests
  drive the real `remove_selection`, the lane-cap tests post to the real
  `/api/v1/report`, the session-touch tests hold a real `BEGIN IMMEDIATE`.
- Scratch probes against the working tree's `db` and `api` modules
  (`scratchpad/probe_db_scenarios.py`): the bucket drain in four shapes, the
  relinked-after-all answer and its repeats, `_halt_when_text`, and a timing of
  `_owed_files_by_machine` on a synthetic 4-machine x 12-project fleet.
- Cross-wire checks from this side into the companion tree as it stands:
  `selection.py` widens only on a 404 (the new 409 deletes nothing);
  `proxy_relink.note_fleet_standins` sets `_FLEET_KNOWN` on an empty list;
  `identity.py` already sends `arch` on `/verify`.

## Verdict table

REAL-AND-SAFE = the finding is closed on every path I could find and I found
no regression. Notes name what I checked beyond the ledger.

| Finding / change | Files | Verdict | Notes |
|---|---|---|---|
| bug-dash-db-1 per-kind queue window, claim by id | db.py `queued_jobs`, `claim_next_job` | REAL-AND-SAFE | Window function needs SQLite >= 3.25; the image (bookworm, 3.40) and the venv (3.49) both have it. `_kind_rank` is popped from the row. `claim_next_job` narrows to `allowed & wanted` before the by-id read. |
| bug-dash-db-2 capped proxy list | db.py `_proxy_manifest_capped`, `fetch_sync_backlog` | REAL-AND-SAFE | Count is `min(diff, NAS - held)`, names dropped; uncapped path byte-identical. Template worded by direction (d-ui round 2/3, [ ON HOLD ] kept). |
| logic-sync-truth-2 capped originals -> `uncertain` | db.py, api.py:681, ui.py `safe_to_close`, transfers.html | REAL-AND-SAFE | End to end now: db keeps the zero-file row, `build_transfers_view` keeps `uncertain`, `safe_to_close` refuses, the panel says CANNOT TELL. Strict-xfail markers are gone and the pair passes. |
| bug-wire-1 relinked-after-all answer | db.py `mark_file_move_applied` | REAL-AND-SAFE | Probed: first (ok, relink_pending) -> applied; second (ok, no flag, no state) -> clears once, True; repeat -> False; a late `retrying` or an ok after a terminal failure -> False, row untouched. `api_report` passes `state=None` for that answer, so the `state in (None,"","done")` arm is the one hit. |
| logic-plans-1 bucket drain + inherited placements | db.py `remove_selection`, `selection_placements` | REAL-AND-SAFE | Probed: LAP (inheriting [pa,pb]) unticks pb -> LAP=[pa], LAP2 (inheriting) materialised [pa,pb], DESK's own plan untouched, wired RIG gets nothing, bucket=[pa], a machine registered later inherits [pa], person view still lists pb. A no-op untick on a machine with its own plan leaves the bucket alone (review-round fix holds). Renamed-PC shape: nothing materialised, returns False. Audit: before=[{LAP,full}] after=[] so [ UNDO ] exists. DASHBOARD FIRST, as the ledger says. |
| logic-plans-4 borrowers get the move | db.py `file_move_target_machines` | REAL-AND-SAFE | NFC via `media_rel_key`, segment-exact prefix test, `ok`+`missing` links. Upload-only borrowers are included via `for_enforce`, which is right: companions <= 0.9.78 build the lender include anyway. |
| bug-dash-db-3 forget takes diagnostics | db.py `_forget_diagnostics` | REAL-AND-SAFE | Table keyed `editor`/`machine`; no schema change. |
| logic-ytdl-jobs-5 prune cooldown | db.py `prune`, collector.py `_run_prune` | REAL-AND-SAFE | `getattr(settings, ..., None)` keeps stubs working. |
| ui-copy-2 notice hrefs | db.py NOTICE_KINDS, notices.py, collector.py, recovery.py, collector_health.html | REAL-AND-SAFE | `id="fleet-collector"` exists in collector_health.html:17; the test walks every href through a TestClient. |
| ui-dash-admin-12 `_halt_when_text` | db.py | REAL-AND-SAFE | Probed: ISO -> `2026-09-25 08:14 UTC`; garbage -> shown as is; lazy alerts import. |
| bug-dash-auth-2 session touch off the 20 s wait | sessions.py | REAL-AND-SAFE | Non-blocking module lock + 250 ms busy; create/revoke/throttle unchanged. Expired-row delete is best effort too. |
| bug-dash-auth-3 undo restores template defaults | site_store.py `_settings_fallback` | REAL-AND-SAFE | Same join `seed_from_env_once` stores; `_shape` reads absence, so the manifest is unchanged. |
| bug-dash-auth-4 asset folder with no ASCII | site_store.py, provision.py | REAL-AND-SAFE | Refused at the door, skipped (logged) in `shared_asset_folders_for`, so `/api/v1/site` can no longer 500 on a stored row or the env value. |
| bug-dash-auth-1 first-run window | setup_routes.py | REAL-AND-SAFE | `POST /setup/admin` and `/setup/status` are in `setup_api`, not behind this gate; `setup.js` calls only tasks/eula/status before step 2. |
| bug-dash-auth-5 oidc claim is not admin | setup_engine.py | REAL-AND-SAFE | Matches `auth.is_admin`; the old test that pinned the wrong answer was flipped, honestly. |
| bug-dash-auth-6 cookie mode words | auth.py | REAL-AND-SAFE | |
| bug-dash-auth-7 X-Forwarded-For from the right | auth.py `client_ip` | REAL-AND-SAFE | Untrusted peers still ignore the header; all-trusted hops -> leftmost as before. (L2: bracketed IPv6 hops.) |
| ui-dash-static-3 undo `expected_at` | setup_routes.py `SiteUndoIn` | REAL-AND-SAFE | Optional body; no body / `{}` / `null` keep today's behaviour. |
| bug-dash-api-1 approve keeps other keys | api.py, nas/synology.py `add_editor_ssh_key` | REAL-AND-SAFE | TrueNAS merge keeps every >=2-field line verbatim (review round). DSM append script: `.format` braces, `shlex`-quoted key, awk on adjacent fields, newline guard; an unwritten key RAISES so the offer is kept. Never run on a real DSM (ledger says so). |
| bug-dash-api-2 proxy follows the new stem | api.py `_move_proxy_siblings` | REAL-AND-SAFE | NFC compare only; on-disk bytes used for the rename (CR-90). Companion still keeps the old stem locally until c-sync's owed half: lane B converges (one download + trash per holder). |
| bug-wire-3 lane string caps truncate | api.py validators | REAL-AND-SAFE | `_bound_to_field_caps` slices strings AND lists, so 257 transfers now 200. `name` min_length still refuses. Fixes every companion in the field. |
| bug-dash-api-3 archived project refused | api.py `_refuse_archived_project` | REAL-AND-SAFE | Three doors: create, adopt, `_register_project` backstop. |
| bug-dash-api-4 password reset signs out | api.py, ui.py (both doors), JSON create | REAL-AND-SAFE | Keeps the admin's own sid via the cached request state; never raises; report tokens untouched by design. |
| bug-wire-4 `/verify` arch + withheld reason | api.py | REAL-AND-SAFE | Truncating before-validator, never 422. Companion's `identity.py:333` already sends `arch`. |
| bug-wire-5 `standins_known` sent empty | api.py | REAL-AND-SAFE | `proxy_relink.py:474-476`: empty list -> `_FLEET_KNOWN=True`, empty set -> "no" -> probe. |
| bug-comp-syncthing-2/-3 includes and covered by FULL ticks | api.py `_expand_includes` | REAL-AND-SAFE | `fetch_selections` rows carry `sync_mode`; NULL/'' read as full. |
| logic-plans-5 companion untick 409 | api.py `api_untick` | REAL-AND-SAFE | Companion `selection.py:545` widens only on 404, so 0.9.77/0.9.78 delete nothing on this 409. Signed-in UI stays idempotent. |
| logic-sync-truth-5 `owed_files` on the row | api.py `_owed_files_by_machine`, health.py | REAL-AND-SAFE (M1) | Correct; base rows skipped; uncertain zeros dropped. Cost noted below. |
| bug-comp-media-3 out_stem refused at POST and in the pinned engine | jobs.py, api.py, cards_exec.py | REAL-AND-SAFE | Same four rules both ends, not `:`/`\`. |
| bug-dash-ops-2/-3, bug-dash-cards-jobs-4 the three mount gates | broll.py, music.py, ytdl.py | REAL-AND-SAFE | One rule in all three: state verdict first, login_gate's resolver when the app is in scope, cookie with previous secrets last; fail closed on any exception. Starlette's `request.state` writes into `scope["state"]`, so the verdict is where they read it. |
| bug-dash-cards-jobs-1 `//api/root` | cards.py `_gate_readings` | REAL-AND-SAFE | Collapse + normpath for the MATCH only; forwarded path untouched. |
| bug-dash-cards-jobs-2, logic-cards-2/-3 agent routing and seats | cards_pool.py, cards_tunnel.py | REAL-AND-SAFE | `note_visit` moves `_where` only to a READY entry; `handed_engine` by engine identity; `_seat` only for work; `_playhead_moved` compares the attributes the other repo really has (`agent.py:352-353`). |
| logic-cards-1 close rule | cards_pool.py, cards_landing.py | REAL-AND-SAFE | |
| logic-cards-7 build deadline | cards_pool.py | REAL-AND-SAFE | Publish decided and done under one lock; a late build is published if a seat is free, else stopped. |
| logic-cards-4/-6/-8/-9, cards-jobs-3/-5/-6 | cards*.py, cards_landing.* | REAL-AND-SAFE | `cards_open`/`cards_close` off the loop; `_trimmed` keeps every corpus pair; `attached: False`. |
| logic-ytdl-jobs-1 silent machines | jobs.py | REAL-AND-SAFE | `machine_facts` (the reporter) carries no `reported_at`; `offers_for_machine` overrides its own row. Order: after the fleet halt, before per-machine state. `REASON_SILENT` non-transient and mapped in alerts. |
| logic-ytdl-jobs-6 offer clause | jobs.py | REAL-AND-SAFE | |
| logic-sync-truth-1 silence is amber then red | health.py `lane_chip`, `_silence`, `fleet_headline` | REAL-AND-SAFE (M2) | Review-round gate on the ROW's freshness holds. See M2 for the nothing-ticked case. |
| bug-dash-diag-1 carried MISSING verdict | protection.py | REAL-AND-SAFE | `stored_results` read before the new pass is stored; `refresh_line` applies the same carry. |
| bug-dash-diag-3 quarantine outside the project | recovery.py, api.py/ui.py docstrings, templates | REAL-AND-SAFE | `<tree>/.restored-<ts>/<label>/` via `_under`; the container already mkdirs at the tree root for new projects. Past restores keep their recorded `where`. |
| bug-dash-ops-1/-5/-7 Sent proof, poll cap, authserv-id | triage_mail.py | REAL-AND-SAFE | Hit fetched and compared; explicit dkim/dmarc fail never overruled; known id only for Gmail. |
| bug-dash-ops-6 CCT masked at rest | triage.py | REAL-AND-SAFE | Masked on write and on read. |
| logic-admin-1 fleet stop expired alert | alerts.py | REAL-AND-SAFE | 24 h window; the ack button clears `expired` (`_halt_state` with active False). |
| logic-alerts-1/-2/-3/-4/-5/-6/-7/-8 | alerts.py, notices.py, invariants.py | REAL-AND-SAFE | `full_tick_pairs` uses `fetch_machine_selections(for_enforce)`, which EXPANDS the bucket onto registered machines, so an inheriting computer is still alerted. Invariant 9 checks both datasets through `protection._covers`. |
| bug-dash-diag-2 check_failed recovers; whole-scan failure clears nothing | alerts.py `deliver` | REAL-AND-SAFE | One "cleared" line per stale check_failed row on first deploy, as stated. |
| bug-dash-diag-4 migrate retry | collector.py | REAL-AND-SAFE | |
| ui-copy-1/-3/-5 button and route names | alerts.py, notices.py, collector.py, invariants.py, health.py | REAL-AND-SAFE | `folders_by_id` is in scope at collector.py:637. |
| ui-dash-admin-10 ack date east of UTC | protection.py | REAL-AND-SAFE | |
| logic-admin-4/-5, ui-dash-admin-13 restore copy and defaults | recovery.py, recovery.html | REAL-AND-SAFE | |
| bug-dash-ops-4 redaction | crash_report.py | REAL-AND-SAFE | Over-redacts `token_count=5`, accepted. |
| bug-dash-ops-8 CLI grace carried | cli_tools.py | REAL-AND-SAFE | Older dashboard reads `previous_version` as before. |
| bug-dash-ops-9 crash file names | crash_report.py | REAL-AND-SAFE | `~NN`, past the highest slot, age key for the prune. |
| logic-release-3/-4 pointer honoured | release_feed.py, package_store.py | REAL-AND-SAFE | `channel` optional (None = old rule). Auto-rollback DEFERRED to the owner, rightly. |
| ui-dash-admin-8 Android draft kept | android.py | REAL-AND-SAFE | |
| logic-admin-6 ship.cmd only off-feed | package_store.py, admin_packages.html | REAL-AND-SAFE | |
| CR-334 / CR-335 (owner asks, outside the ledgers) | ui.py `_vendor_rows`, `_kind_platform_groups`, admin_packages.html, release_feed.py, package_store.py | REAL-AND-SAFE | `_feed_flag` reused; newest-first sort; row-level refusal; audit rows on both promotion paths. |
| ui-dash-main-1/-2/-8, ui-dash-static-1 `liveRoot`, popover carry | base.html, htmx_errors.js, sidebar.html | REAL-AND-SAFE | Sidebar tick swaps the aside's innerHTML now. On desktop `.projects.sheet` has an author `display`, so `:popover-open` is false and no poll is held. |
| ui-dash-main-3/-6, ui-dash-admin-3 poll pause | htmx_errors.js | REAL-AND-SAFE (L1) | Skips, never delays; `load, every` triggers judged on an empty root at load. |
| ui-dash-static-2 4xx refusals beside the control | htmx_errors.js | REAL-AND-SAFE | 401 still ends the session; GET 4xx still stale. |
| ui-dash-main-7 undo of a tick asks | ui.py, plan_changes.html | REAL-AND-SAFE | |
| ui-dash-main-9 queue untick keeps the machine view | ui.py `partial_toggle`, my_queue.html | REAL-AND-SAFE | View key only; the write stays person-level. |
| logic-plans-2 mode buttons ask | ui.py `_tick_confirms`, project_detail.html | REAL-AND-SAFE | All five project-detail renders carry it. |
| logic-admin-3 [ OK, IT CAN STAY OFF ] | fleet_halt.html, ui.py | REAL-AND-SAFE (L5) | Refuses when a NEW stop is live. |
| ui-copy-2 Resolve undo panel + route | ui.py `_resolve_undo_view`, recovery.html | REAL-AND-SAFE | Calls the JSON route's own function; `asked` from every open request. |
| ui-dash-admin-7 health rows on a raised source | ui.py `_health_rows` | REAL-AND-SAFE | |
| ui-dash-admin-2/-4/-5/-6/-9/-11/-12/-14, ui-dash-static-4..9, ui-copy-6/-7, ui-dash-main-4/-5/-10 | ui.py, templates, static | REAL-AND-SAFE | Copy, layout, JS feedback. Package-wide " -- " scan and the template scan both pass. |
| logic-sync-truth-4 disk chip | ui.py CHIP_HELP | REAL-AND-SAFE | Worded by version, matching what 0.9.77/0.9.78 really do. |
| logic-admin-7 pinned cancel wording | ui.py, triage_actions.py | REAL-AND-SAFE | |
| NOT_A_DEFECT: ui-copy-6 db.py `--` (SQL comments), cards_ai.py:118 (model prompt) | | correct | |
| ALREADY_FIXED: logic-alerts-9 (= ops-5), logic-cards-5 (5a26e10), ui-dash-static-1 (= main-2) | | correct | Checked each against the current source. |
| DEFERRED: logic-cards-3 (routing by machine), logic-release-4 auto-rollback | | correct | Both are owner decisions, not fixes. |
| release-tools, server/ part | (none) | n/a | No file under `server/` changed. |

## Problems, ranked

### High

None found.

### Medium

**M1. `api._owed_files_by_machine` puts the full file-level backlog diff on
every fleet-grid render** (`api.py:867`, called from `build_editors_view`
at `api.py:994`). That view is rendered by `/partials/fleet` every 15 s per
open admin tab, by `/api/v1/editors`, and by every alerts cycle. Measured on a
scratch DB (4 machines x 12 projects x 4,000 listed files each, local SSD):
77 ms per call; `build_editors_view` went from ~14 ms to ~91 ms. It is one
pass over `fetch_sync_backlog` with `files_per_group=0`, so it scales with
the number of ticked pairs, and each pair's diff is a NOT EXISTS between
`editor_media` and `nas_media`. Not a correctness defect and the ledger flags
it, but on the NAS (WAL, spinning pool, more pairs) it is the biggest new
per-request cost of the wave. Cheap fix later: compute once per collector
cycle into `machine_state` or a module cache with a 15-30 s TTL, and read
that from the view.

**M2. A computer with nothing ticked that has gone quiet now leads with an
amber "Not heard from since ..." headline** (`health.py:1205`). The d-diag
ledger for logic-sync-truth-1 says "A computer with nothing ticked is
untouched (the informational `why` path is below and muted as before)"; that
is not what the code does: `_silence` runs BEFORE the informational `why`
path, so `fleet_headline({why: nothing-ticked, status_reason: "no report
since ...", lanes: []})` answers `not_reporting` / amber (probed). The
row's own dot was already amber from `report_freshness` (UX-2), and the fact
is about the computer being off rather than its ticks, so I do not think it
breaks the owner's "nothing ticked is fine" rule in spirit; but it is a new
amber line on such a row, and the ledger's claim is wrong. Owner call; if the
rule is read strictly, move the `_silence` block below the informational
return.

### Low

**L1. The poll pause's "focus" hold has no time bound** (`htmx_errors.js`
`busy()`): a text field or select left focused inside a polled panel (Users'
CREATE form, the project page's MOVE / SHARE forms) stops that panel's beat
until focus leaves. The dirty, in-flight and picker holds are bounded at
5 min; focus is not. Deliberate and defensible, but an admin who clicks into
the username box and walks away stops the pending-key list updating for as
long as the tab has focus there.

**L2. `auth.client_ip` handles a bracketed IPv6 hop half way**
(`auth.py:250`): the address is validated with `[]` stripped but passed to
`trusted_proxy()` and returned WITH the brackets, so the throttle bucket and
the sessions page would show `[2001:db8::1]`. No proxy in the field writes
brackets into X-Forwarded-For; cosmetic.

**L3. `mark_file_move_applied`'s second arm stores `detail` for an ok answer**
(`db.py:6345`) where the first arm stores NULL for ok. The project page may
now show the companion's "relinked N clips" text on a finished move and
nothing on a plain one. Harmless inconsistency.

**L4. The [ OK, IT CAN STAY OFF ] path writes a second "release" history row
when the stop is neither active nor expired any more** (a second admin already
acknowledged it): `partial_admin_set_fleet_halt` only refuses when a NEW stop
is live. Cosmetic duplicate in PREVIOUS STOPS.

**L5. `queued_jobs` now needs SQLite >= 3.25** (window functions). The
container image (python:3.12-slim on bookworm, SQLite 3.40) and the venv
(3.49) both have it. Worth one line in docs/RELEASE.md or the Dockerfile as a
floor, because nothing else in the package uses a window function.

**L6. `triage_mail._unhandled_numbers` can make up to 500 header peeks per
poll on a flooded address**, each an IMAP round trip. Bounded and the feature
is off in the vendor build; noted only.

**L7. `test_packages.py::test_c4_unsigned_make_current_confirm_copy_is_pinned`
now pins raw Jinja source including `{% if feed is defined ... %}`.** It was
already a template-text pin; it is just more brittle now. The rendered copy
is covered by `test_a_feed_site_is_pointed_at_the_feed_not_ship_cmd`.

**L8. `_owed_files_by_machine` claims "nothing owed" from whatever manifests
have arrived**: a machine whose manifest for project B has not been sent yet
(only A's has) counts A's backlog and can read "Idle, nothing owed" for a few
report cycles after ticking B. The GETTING READY chip covers the just-ticked
case on the transfers page; the headline does not know about it. Minor.

## Things I checked that are fine but worth recording

- **No schema migration in this wave.** No new column, no `ALTER`, nothing a
  0.7.57 database would trip on. The stored protection blob gains optional
  `carried`/`verdict_at`/`verdict_detail` keys; the CLI state file gains an
  optional `superseded_earlier` list; both are read with `.get`.
- **Wire keys.** New optional reply keys only: `upgrade_none_reason` on
  `/verify`, `standins_known` always present, `attached: False` on the cards
  tunnel, `sessions_revoked` on two admin JSON routes, `last_agent` /
  `opening_seconds` on cards state. The one new refusal (409 on a companion's
  machine-scoped untick) is handled by every field build as "refused, delete
  nothing" (`selection.py:545` widens only on 404).
- **Deploy order.** Dashboard first for logic-plans-1 and bug-wire-4; every
  other change is either order-free or dashboard-only. Nothing here needs a
  companion newer than 0.9.77 to be safe.
- **NFC/NFD (CR-90).** `_proxy_stem_key` and `file_move_target_machines`
  normalise for comparison only; every rename uses the on-disk bytes.
- **No em dash.** The package-wide `" -- "` scan (d-ui round 3, with the SQL
  and prompt exemptions tightened) and `test_no_em_dash.py` pass; I read the
  new 409, jobs, alerts, notices and headline strings by hand.
- **Recovery quarantine.** `_under(quarantine, label)` refuses `..`; the tree
  root is no Syncthing folder; `provision.scan_project_dirs` skips dot-dirs.
- **Session gates.** Starlette writes `request.state` into `scope["state"]`,
  so the three gates read the verdict `login_gate` wrote; a fleet-stamped
  companion request (no cookie) still mints no identity header.
- **Cards gate.** `posixpath.normpath` alone keeps a leading `//`; the code
  collapses runs of `/` first, so `//api/root`, `/./api/root` and
  `/api/../api/root` all match the block list.

## Should anything block the commit?

No. Nothing in `dashboard/` or `server/` is NOT-FIXED or REAL-BUT-BREAKS-X.
The two mediums are a performance watch (M1) and a headline the owner may
want moved below the nothing-ticked path (M2); both are one-line follow-ups,
not reasons to hold the tree. The ledger sentence in d-diag's
logic-sync-truth-1 entry ("A computer with nothing ticked is untouched")
should be corrected before the ledgers are treated as the record.
