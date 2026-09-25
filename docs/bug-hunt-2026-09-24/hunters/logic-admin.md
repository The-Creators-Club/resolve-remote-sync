# logic-admin - the admin/owner journey on the dashboard (users, computers, packages + push, fleet halt, jobs, recovery, settings, AI providers)
Files read (approximate coverage): dashboard/src/ccsync_dashboard/api.py (fleet halt, push/cancel update, command delivery, version/offer helpers, packages make-current / roll-back / delete, disable/suspend/delete user, forget machine, report-handler push arm), ui.py (fleet halt partials, jobs page + retry/cancel, recovery partials, packages htmx doors, `ago` filter), db.py (fleet halt state/set/history, request_job_cancel, expire_leases), alerts.py (fleet halt checks), recovery.py (preview, restore, walk, plan steps), package_store.py (make_current_refusal), ai_providers.py (resolver, states, test, preference), static/site_settings.js (AI providers panel), templates/partials/fleet_halt.html, fleet_halt_banner.html, recovery.html, admin_packages.html. cli_tools.py skimmed only (state machine names), not traced.
Tests/probes run: dashboard venv snippets - `ui.ago(<now + 23 h>)` returns `'0s ago'`; `alerts._check_fleet_halt_expired` on `db._halt_state(<expired halt>)` returns `[]` (the state carries `active: False, expired: True`).

## Findings

### logic-admin-1 - The "fleet-wide stop expired" alert can never fire
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:1409 ; dashboard/src/ccsync_dashboard/db.py:8201
- What: `_check_fleet_halt_expired` fires only when `halt["active"] and halt["expired"]`, but `db._halt_state` (what `get_fleet_halt` returns and what `Ctx.halt` holds) sets `"active": active and not expired`. The two can never both be true, so the check always returns no findings.
- Failure scenario: The owner stops the fleet on Friday, goes home. The halt expires Saturday and every machine starts syncing again. The `fleet_halt_expired` alert is meant to tell him ("If the reason it was set is still true, nobody has been told"), but it never fires. No mail goes out and there is nothing in the weekly report. So the one alarm for a stop that ended without anyone noticing is silent, and it shows as a working registered check.
- Evidence: snippet: `db._halt_state({'active':True,'set_at':'2026-09-20T00:00:00+00:00','expires_at':'2026-09-21T00:00:00+00:00'}, '2026-09-24T00:00:00+00:00')` -> `{'active': False, 'expired': True, ...}`; `alerts._check_fleet_halt_expired(ctx)` with that halt -> `[]`. No test in dashboard/tests names `fleet_halt_expired`.
- Ledger: new
- Suggested fix: Test `halt.get("expired")` alone. Also add a table test that takes an expired halt through `get_fleet_halt` into this check.

### logic-admin-2 - The halt's release time reads "releases itself 0s ago", on every page
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/fleet_halt_banner.html:13 ; dashboard/templates/partials/fleet_halt.html:38 ; dashboard/src/ccsync_dashboard/ui.py:93
- What: Both halt templates render the FUTURE `expires_at` through the `ago` filter. `ago` clamps a negative delta to 0 (`max(int(delta.total_seconds()), 0)`), so any future time comes out as "0s ago".
- Failure scenario: An admin stops syncing. Every signed-in user sees on every page "SYNCING IS STOPPED ... it releases itself 0s ago unless somebody keeps it on". The Users panel says "releases itself 0s ago unless you keep it stopped". Nobody can tell when the 24 h stop ends, which is the one number the UX-8 expiry was added to show. It also reads as if the stop has already ended, so the owner can think syncing has resumed when it has not.
- Evidence: `ui.ago((now + 23h).isoformat())` -> `'0s ago'` (run in the dashboard venv).
- Ledger: new (UX-8's banner, KNOWN_BUGS ~6470, never rendered a real value)
- Suggested fix: Add an `until`/`in` filter ("in 23 hours", "at 14:05 tomorrow") and use it for `expires_at` in both templates. Also add a render test with a future expiry.

### logic-admin-3 - An expired fleet stop leaves a banner on every page that nothing in the UI can clear
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/fleet_halt_banner.html:18-25 ; dashboard/templates/partials/fleet_halt.html:62-80 ; dashboard/src/ccsync_dashboard/db.py:8185-8210
- What: After expiry, the stored blob keeps `active: true` and `_halt_state` reports `expired: True` on every read from then on. The every-page banner shows "THE FLEET-WIDE STOP HAS EXPIRED" to every signed-in user, editors included, whenever `halt.expired`. In that state the admin panel offers only [ STOP ALL SYNCING ]: there is no acknowledge or release button. The only thing that clears it is `set_fleet_halt(active=False)`, which the UI posts only from the ACTIVE state. The alert text (logic-admin-1) tells the owner to "confirm it is no longer needed", and no such control exists.
- Failure scenario: A halt expires. From then on every editor sees an amber "fleet-wide stop has expired" banner at the top of every page, for weeks. The owner's only way to remove it is to stop the whole fleet again (which needs a reason and a confirm) and then press START SYNCING AGAIN. That briefly halts every computer, and editors on their next report pick up the halt.
- Evidence: read the two templates and `set_fleet_halt`/`_halt_state`. The `{% else %}` branch of fleet_halt.html has only the halt form. `api_set_fleet_halt` with `active=false` is the only writer that clears `expired`, and only the JSON door can send it in that state.
- Ledger: new
- Suggested fix: In the expired branch, render "[ OK, IT CAN STAY OFF ]", posting `active=0`, next to [ STOP ALL SYNCING ]. Optionally show the expired banner to admins only, or for a bounded time (for example 72 h after `expires_at`).

### logic-admin-4 - After a restore, the recovery page still shows the same files as missing and invites the same restore again
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/recovery.py:259-283 (`_walk` skips dot-dirs), 355-490 ; dashboard/templates/partials/recovery.html:190-205 ; dashboard/src/ccsync_dashboard/recovery.py:874-880
- What: A restore copies files into `<project>/.restored-<ts>/`. `_walk` deliberately skips every dot-directory, so running the preview again for the same snapshot reports exactly the same "N file(s) missing" and offers [ RESTORE INTO A NEW FOLDER ] again. A second click creates a second `.restored-<ts>` copy. Separately, the result line says only "into <label>/.restored-2026..." and the plan step says "Then move what you want back yourself". A folder whose name starts with a dot is hidden by default in the SMB share's Windows view (Samba's `hide dot files` default) and in Finder, and nothing on the page explains how to reach it.
- Failure scenario: The owner restores the 312 files he lost, looks at P:\...\Project in Explorer, and sees nothing new. He comes back to the page, clicks [ SEE WHAT IS MISSING ] again, is told the same 312 files are missing, and restores again. Each copy is a full duplicate on the pool, and the files he needs are still not where Resolve looks for them.
- Evidence: read `_walk` ("Dot-directories are skipped, which is what keeps a previous `.restored-<ts>` ... out of a comparison"), `restore_into_quarantine` (target = `live / ".restored-<stamp>"`), and the recovery.html result block. No preview output mentions an earlier restore; `recovery.restores` lists them only at the bottom of the page.
- Ledger: new
- Suggested fix: Have the preview check `history(RESTORES_META)` for the same slug and snapshot and say "already restored into X on <date>; those files are in that folder". Give the result line the editor-visible path (the canonical prefix plus the label) and a sentence on how to show hidden folders, or use a quarantine name without the leading dot plus a marker the scanners prune on.

### logic-admin-5 - When only "changed" files exist, the restore form's defaults are refused, and the confirm quotes the wrong count
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/recovery.html:180-200 ; dashboard/src/ccsync_dashboard/recovery.py:422-426
- What: The restore form is shown when `missing_count or changed_count`, and "also bring back the ones that are there but different" starts unticked. With 0 missing and some changed, the confirm reads "Copy 0 file(s) into a new folder?", and `restore_into_quarantine` then refuses with "nothing in the snapshot ... is missing ... so there is nothing to restore". That refusal does not mention the checkbox that would do it. When the box is ticked, the confirm still quotes only `missing_count`.
- Failure scenario: An editor overwrote a timeline file (same name, different size). The owner previews: "0 missing, 1 that is there but different". He clicks RESTORE, confirms "Copy 0 file(s)", and is told there is nothing to restore, even though the page just showed one.
- Evidence: read the template condition and the `rels` / refusal code.
- Ledger: new
- Suggested fix: Render the checkbox ticked (or show the form only for missing files) when `missing_count == 0 and changed_count`. Have the refusal name the checkbox. Compute the confirm count client-side, or state both numbers.

### logic-admin-6 - The Packages page tells a customer's admin to run tools\ship.cmd, a vendor-only script
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/admin_packages.html:71, 137, 259-261, 553-558 ; dashboard/src/ccsync_dashboard/package_store.py:220-226
- What: Five owner-facing texts give `tools\ship.cmd` as the next action: the "nothing is being served yet" empty state, the footer "Publish new builds from your wired computer with one command", the [ UNSIGNED ] chip, the unsigned make-current confirm, and the refusal from `make_current_refusal`. None of them depends on the deployment. release_feed.py:1093 already makes the same kind of text conditional on `image_mode`, and a customer site (zero-touch plan, vendor builds only) has no repo, no wired computer and no ship.cmd. For that site the real next action is the vendor feed panel on this same page ([ CHECK NOW ] / feed policy).
- Failure scenario: A new customer's admin opens Settings -> Packages on a fresh appliance before the first feed poll. He reads "publish a build below, or from your wired computer with tools\ship.cmd" and "See docs/RELEASE.md", and has neither. The button that would help, checking the vendor feed, is not named.
- Evidence: grep of `ship.cmd` in templates and package_store.py. No surrounding `{% if %}` on image mode or feed configuration.
- Ledger: related to REL-8 (which chose ship.cmd over a footgun flag, but for the studio only)
- Suggested fix: Make the text depend on the release pathway. When a vendor feed is configured or `image_mode` is on, name [ CHECK FOR NEW BUILDS ]. Keep ship.cmd for the studio's own non-image deployment.

### logic-admin-7 - Cancelling a pinned job says "the computer running it" will stop it, but this server runs it
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ui.py:3474-3478 ; dashboard/src/ccsync_dashboard/db.py:11089-11098
- What: `request_job_cancel` returns "requested" for CLAIMED, RUNNING and PINNED alike, and the page always answers "job #N will stop on its next report - the computer running it is the only thing that can end it". A pinned job is run by the dashboard's own Timeline Cards worker (`cards_exec.py`, which polls `should_stop`). No computer and no report is involved.
- Failure scenario: The owner cancels a proxy job the fleet gave up on (pinned). The page tells him to wait for a computer's report, so he goes looking at the fleet grid for which computer holds it and finds none. The job actually ends on this server when the worker next checks.
- Evidence: read both functions. The job's `state` is available in `_jobs_context` but is not passed into the notice.
- Ledger: new
- Suggested fix: Have `request_job_cancel` return a distinct value for pinned jobs (or read the state first), and word the notice as "this server's own worker will stop it at its next check".

## Coverage note
cli_tools.py's install and sign-in state machine (2.4k lines) was not traced beyond a skim. The SSH key approval queue, report tokens, sessions and the audit page were not read. `build_admin_users_view` / `build_packages_view` were read only as far as the templates use them. On the push doors: the htmx [ UPDATE NOW ] and [ PUSH TO ONE COMPUTER ] return the panel with no DCORE-13 "applies" sentence. The panel does show LAST REPORT per machine, so I judged that not a finding.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/ai_providers.py:1110: `test_provider` for a disabled CLI answers "([features] ai_cli_providers)", the config-key wording the row detail was reworded away from on 2026-08-18. The UI hides [ TEST ] in that state, so only the JSON door reaches it.
