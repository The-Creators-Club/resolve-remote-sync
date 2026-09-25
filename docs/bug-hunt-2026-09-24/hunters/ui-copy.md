# ui-copy - cross-cutting vocabulary: tray, popups, dashboard, SPAs, HTTP details, alert and notice copy
Files read (approximate coverage): CLAUDE.md; HUNTER_BRIEF.md; docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md section 4 (the one-vocabulary table) and wave 4; dashboard: alerts.py (halt, red_unexplained, file-move, digest composers), notices.py (fix strings), db.py notice registry (hrefs), recovery.py (_stop_the_fleet_step), collector.py/invariants.py (marker notices), health.py (COMPANION_DIAGNOSTICS_PATH), ui.py (SETTINGS_NAV_GROUPS, login and halt refusals), templates fleet.html, partials/fleet_halt.html, fleet_halt_banner.html, fleet_grid.html (diagnostics, cards chip, ASK WHY), project_detail.html (MOVES history), admin_dashboard_update.html, admin_diagnostics.html, topbar.html, login.html; the dashboard/companion/broll vocabulary and em-dash scan tests (to find what they do NOT cover); companion: ui_copy.py, settings_window.py HELP section, tray.py menu, ytdl_executor.py REASON_*, file_moves.py, proxy_gen._notify_text, resolve_undo.py, timeline_cards_role.refusal, identity.py, site.py brand helpers; ytdl/web/static/app.js (companionCapabilities / noteLocalSkipped); broll/music/ytdl static copy for companion naming; KNOWN_BUGS.md for CR-283G (CCSync spelling, declined) and the CR-181 allow-list note.
Tests/probes run: ad-hoc scripts in the scratchpad, no repo writes: (1) an AST scan for U+2014 in non-docstring string literals and in static files across the repo; (2) the dashboard's own RETIRED_WORDS scan (imported from tests/test_sweep_2026_09_04_copy.py) run over EVERY dashboard, ytdlweb, broll/web/app and musicweb module, not just its twelve listed files; (3) the companion's own retired-word scan run over every companion module outside its MODULES tuple; (4) a bracket-label crawl: every `[ LABEL ]` named in Python copy checked against the labels that actually exist in templates/JS/companion; (5) a " -- " count over dashboard Python copy; (6) the broll vocabulary test's JS/HTML string extractors over the ytdl, music and dashboard static files.

## Findings

### ui-copy-1 - The fleet-halt alert sends the admin to a button and a page that do not exist
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:1402 (and :1415); dashboard/src/ccsync_dashboard/recovery.py:862-869
- What: `_check_fleet_halt`'s next action reads "On the dashboard: SYNC STATUS, then [ RELEASE THE HALT ]". No template has ever had that label. The control is `[ START SYNCING AGAIN ]` (or `[ KEEP IT STOPPED ]`) in `partials/fleet_halt.html`, which is on Settings, Users (`/admin/users#admin-fleet-halt`, the target the halt banner already links to). SYNC STATUS has no halt control. `_check_fleet_halt_expired` also says "SYNC STATUS". The recovery wizard's "Stop the fleet writing first" step says "Put the fleet on hold", which is a fourth word for the halt, and its `href="/fleet"` also points at SYNC STATUS rather than the panel. The dashboard vocabulary test's VOCABULARY_ALLOWED keeps "[ RELEASE THE HALT ]" on the grounds that it is "a button label, quoted... renamed in the templates or nowhere". But the button in the templates was renamed, and this copy was never updated to match.
- Failure scenario: The fleet is halted over a weekend and the Monday digest or alert mail tells the owner to press [ RELEASE THE HALT ] on SYNC STATUS. The owner opens SYNC STATUS, finds no such button, and syncing stays stopped for every editor until someone finds Settings, Users. The recovery wizard sends the admin to the same wrong page, in the middle of a restore.
- Evidence: `grep -rn "RELEASE THE HALT"` finds the phrase only in alerts.py and a test allow-list. `git log -S"RELEASE THE HALT"` shows it arrived with wave 4 (b3d155e), while `[ START SYNCING AGAIN ]` has been the template label since b2d348a. SETTINGS_NAV_GROUPS and fleet.html have no halt panel.
- Ledger: new (related to CR-181's allow-list, which asserts the label exists)
- Suggested fix: Change both alert next actions and the recovery step to "Settings, Users, [ START SYNCING AGAIN ]" (or "[ KEEP IT STOPPED ]"). Point the recovery href at `/admin/users#admin-fleet-halt`. Drop the stale VOCABULARY_ALLOWED entry so a future rename fails the test.

### ui-copy-2 - "Settings, Diagnostics" is not a page, and the notice links land on an empty div
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/notices.py:241, :290, :315, :1001, :1515; dashboard/src/ccsync_dashboard/db.py:3390-3399, :3506-3508; dashboard/templates/fleet.html:42
- What: Five notice fix strings send the admin to "Settings, Diagnostics". Examples: "Check that Syncthing is running on the server (Settings, Diagnostics)", "Restart the dashboard, then check Settings, Diagnostics", "Send us the crash files: Settings, Diagnostics, [ DOWNLOAD CRASH REPORTS ]" and "Open Settings, Diagnostics and send the detail to support". The Settings strip (ui.SETTINGS_NAV_GROUPS) has no Diagnostics entry. The registry hrefs for `collector_cycle_failed`, `collector_watchdog_restart` and `server_error` are `/fleet#fleet-diagnostics`. That anchor is a bare `<div id="fleet-diagnostics"></div>` that stays empty until someone clicks `[ READ THE ANSWER ]` on a computer whose companion has uploaded a bundle. The "detail to send to support" is in the notice itself, not on that panel.
- Failure scenario: The server's collector keeps failing and HEALTH shows the notice. The owner clicks it, lands on SYNC STATUS scrolled to nothing, looks for a Diagnostics entry in Settings, and finds none. There is nothing to send and no next step.
- Evidence: SETTINGS_NAV_GROUPS (ui.py:165-186) lists SITE, USERS, SYNC PLANS, TRANSFERS, PACKAGES, JOBS, HISTORY, SETUP, HEALTH, INVARIANTS, PROTECTION, ALERTS, RECOVERY and HELP. fleet.html:37-42 describes the div as "Empty until asked for". `partials/admin_diagnostics.html` is fetched only by fleet_grid.html:462 and by its own link.
- Ledger: new (the 2026-09-18 hunts touched these hrefs for other reasons; the copy/page mismatch is not recorded)
- Suggested fix: Name a place that exists, such as "HEALTH, then this notice's detail". Point `server_error` and `collector_*` at `/admin/health`, or make `#fleet-diagnostics` load its panel when the page opens with that fragment. The crash-report fix already has its own href and label, so its sentence can just say "[ DOWNLOAD CRASH REPORTS ] below".

### ui-copy-3 - More next-action sentences name buttons or pages by names they do not have
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:3515; notices.py:392; collector.py:656; invariants.py:1072
- What: `red_unexplained` says "press [ ASK WHY ]", but the button is `[ ASK THIS COMPUTER WHY ]` (fleet_grid.html:460). `ignored_report_sections` says "Settings, Packages, [ UPDATE THE DASHBOARD ]", but the panel is `[ DASHBOARD ]` and its button is `[ UPDATE NOW ]` (admin_dashboard_update.html:85). The only similar label, `[ UPDATE THE DASHBOARD FIRST ]`, is a chip, not a button. The damaged-marker notice and the `project_markers` invariant say "set the project up again from Settings, Projects". There is no Projects page in Settings. Project setup is `/project-setup`, which nothing in the dashboard links to (the tray's "Set up '<name>' on the server..." opens it).
- Failure scenario: An owner reading the mail looks for the named button or page and does not find it. Each one on its own is a small snag, but together they teach the reader that the instructions are not to be trusted.
- Evidence: A label crawl of every `[ X ]` in Python copy against the template/JS corpus: these are the ones that name nothing. `grep "/project-setup"` over the templates finds no link.
- Ledger: new
- Suggested fix: Use the real labels, and pull button labels from one constant shared by the template and the alert text, as COMPANION_DIAGNOSTICS_PATH already does. For the marker, tell the owner to use the tray's "Set up ... on the server" or link `/project-setup`.

### ui-copy-4 - Companion copy outside the vocabulary scan still says "machine", "lane B" and "parked" to editors and admins
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ytdl_executor.py:349-386 (REASON_*); file_moves.py:473, :483, :517; proxy_gen.py:1500, :1520; resolve_undo.py:75-76; timeline_cards_role.py:555-558, :574-576; identity.py:537-539; ytdl_attestation.py:150
- What: The owner-approved vocabulary (2026-09-04) says a computer is "computer", sync never has a "lane", and a stop is "paused" or "stopped...". The companion scan only reads the modules in its MODULES tuple, and these modules are not in it, but their strings reach people. Examples:
  - The ytdl page prints `body.reason` verbatim in the toast "Downloading on the server: nobody is signed in on this machine. YouTube originals only sync upwards... this computer" (ytdl app.js:2527 -> noteLocalSkipped), which uses both words in one toast. Other reasons read "this machine has no valid sign-in token -- sign in again from the tray" and "this machine's tree isn't mounted right now".
  - File-move answers are rendered in the project page's MOVES history (project_detail.html:250, `({{ t.detail }})`) as "moved (lane B had already moved this folder on this machine)".
  - The tray balloon from proxy_gen._notify_text says "(12 on this machine)... This machine has no ffmpeg, so it can only tell you."
  - resolve_undo's result begins "Parked: there is no project open in Resolve".
  - The Timeline Cards refusal "the fleet is halted, so this machine is not taking work", and a refusal that ends in "(CR-68)", go into the fleet grid chip tooltip (fleet_grid.html:405-410).
- Failure scenario: An editor sees "this machine" and "this computer" in the same toast. An admin reads "lane B" and a bug id on the project page and in a chip, which are terms the sweep retired from every visible surface.
- Evidence: The companion suite's own `_sentences`/`_WORD_RE` scan run over every module not in MODULES (75 hits, most of them log/self.log lines). The ones listed above were traced to a rendering surface.
- Ledger: related to CR-181 (the vocabulary wave, which fixed the listed modules only)
- Suggested fix: Reword these strings ("this computer", "proxy download had already moved it", "Waiting:", "syncing is stopped by your admin") and add ytdl_executor, file_moves, proxy_gen, resolve_undo, timeline_cards_role, identity and ytdl_attestation to MODULES.

### ui-copy-5 - The companion and the dashboard give two different routes to "Copy diagnostics"
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ui_copy.py:40; dashboard/src/ccsync_dashboard/health.py:534; companion/src/ccsync_companion/settings_window.py:1591-1612; dashboard/templates/partials/fleet_grid.html:472
- What: The sweep's decision was one constant, "Settings > Help > Copy diagnostics". The dashboard's constant says that. The companion's own constant is "Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN" (no Help step), and the real button in the HELP section is "COPY DIAGNOSTICS FOR YOUR ADMIN". So the admin reading the dashboard and the editor reading the tray are given two different directions to the same button, and neither matches the button's exact text. fleet_grid.html:472 also hand-writes a third spelling ("Settings, then Help, then Copy diagnostics") instead of using the Jinja global.
- Failure scenario: An admin on the phone says "Settings, Help, Copy diagnostics". The editor's window has a HELP section, but the tray's own sentences never mention Help, and the button text is longer. This is small friction, and it is exactly the drift the one-constant rule was meant to prevent.
- Evidence: Read both constants and the Settings window's HELP builder.
- Ledger: new
- Suggested fix: Pick one wording, for example "Settings > Help > COPY DIAGNOSTICS FOR YOUR ADMIN", use it in both constants, and render fleet_grid.html:472 from COMPANION_DIAGNOSTICS_PATH.

### ui-copy-6 - The " -- " stand-in em dash is banned in templates but ships in dashboard Python copy
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ui.py:847, :3315, :773, :817, :1265, :3555, :3579; api.py (21 strings); dashboard_update.py (14); release_feed.py (9); ai_providers.py (7); setup_engine.py (5); cards_tunnel.py:168
- What: DUI-14 treats " -- " as the typewriter em dash that the house rule bans, but `test_no_typewriter_em_dash_in_rendered_copy` scans only templates. Python strings rendered into the same pages still use it. On the login page an editor sees "the server is busy checking sign-ins -- try again in a moment". The halt panel refusal reads "say why -- every editor's tray will show this". The Resolve-mapping refusal reads "this Resolve project is already mapped -- ask an admin to change it". HTTP `detail`s from api.py/dashboard_update.py are shown in admin toasts. The companion's ytdl REASON_NO_IDENTITY (" -- sign in again from the tray") reaches the ytdl toast the same way.
- Failure scenario: An editor or admin reads exactly the glyph the owner banned, on the login page and on the Users page.
- Evidence: An AST scan with the dashboard test's own helpers found about 70 non-docstring, non-log, non-SQL literals containing " -- ". The ui.py entries were traced to `_render(... error=...)` on login.html and fleet_halt.html.
- Ledger: related to DUI-14 (fixed for templates only)
- Suggested fix: Replace them with a colon or two sentences, and extend the DUI-14 check to the Python scan that test_no_em_dash.py already runs over the package.

### ui-copy-7 - "Sign in" everywhere except the topbar's [ LOGIN ] / [ LOGOUT ] / [ LOGOUT ALL ]
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/topbar.html:150, :162, :164, :236, :238; dashboard/templates/partials/admin_sessions.html:36, :38
- What: The login page heading is `[ SIGN IN ]` / `[ SIGN IN WITH SSO ]`, the tray and every SPA say "sign in" / "sign out" (about 66 uses), and the LOGOUT ALL confirm says "Sign yourself out of every browser... you will need to log in again". The buttons themselves say LOGIN / LOGOUT. So one action has two names, sometimes in the same dialog.
- Failure scenario: Admin support copy says "sign out everywhere", the button says LOGOUT ALL, and a non-technical owner has to guess that they are the same thing.
- Evidence: A case-folded count over templates, SPAs, tray and Settings window.
- Ledger: new
- Suggested fix: Rename the buttons to [ SIGN IN ], [ SIGN OUT ] and [ SIGN OUT EVERYWHERE ], and change "log in again" to "sign in again".

## Coverage note
Not covered in depth: the installer and onboarding wizard copy (a separate ui-onboarding hunter covers these; the em-dash scan over .ps1/.sh/.html found only comments); api.py HTTP details one by one (only counted for " -- " and scanned for retired words, which was clean); triage mail bodies beyond the subject lines; macOS-only copy paths; Cards (other repo) copy. I did not re-report the CCSync vs "CC Sync" spelling split (CR-283G, declined, left to the owner). I did not render pages; everything here is proven from source.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/alerts.py:3940 (compose_digest) and :3803 (compose_alert): the alert and digest mails carry no site or org name and no dashboard URL ("Open the CC Sync dashboard for the full picture."), so a vendor or owner getting mail from two sites cannot tell which server wrote it (logic-alerts).
- broll/indexer/broll_index/pipeline.py:129: the audio-only `videos.error` is stored with an em dash; I could not confirm whether any page renders videos.error.
