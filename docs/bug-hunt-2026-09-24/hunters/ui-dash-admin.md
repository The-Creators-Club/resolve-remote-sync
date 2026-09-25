# ui-dash-admin - Wave 3 UI: the admin pages (templates/admin_*.html, partials/admin_*.html, settings nav, android, recovery, protection, invariants, notice checks, collector health, fleet halt, minted secret, editor switcher, stamp)

Files read (approximate coverage): every `dashboard/templates/admin_*.html` page (alerts, assignments, audit, health, invariants, jobs, packages, protection, recovery, settings, users) in full; partials `admin_alerts`, `admin_audit`, `admin_dashboard_update`, `admin_diagnostics`, `admin_jobs`, `admin_packages`, `admin_report_tokens`, `admin_sessions`, `admin_suspend_button`, `admin_users`, `android_settings`, `collector_health`, `editor_switcher`, `fleet_halt`, `fleet_halt_banner`, `invariant_checks`, `minted_secret`, `notice_checks`, `protection`, `recovery`, `settings_nav`, `stamp` in full; `static/htmx_errors.js`, `static/dashboard_update.js`, the tail of `static/site_settings.js`, the relevant parts of `style.css` / `mobile.css` / `base.html`; the backing routes in `ui.py` (alerts, health, fleet halt, recovery, protection), `android.py`, `alerts.py` (password + settings_view), `protection.set_ack`, `recovery.preview_restore`/`restore_into_quarantine`, `dashboard_update.rollback`/`preflight`/`status`.
Tests/probes run: dashboard venv snippets only - `ui.ago()` on a timestamp 23 h in the future (returns `'0s ago'`); rendering the archive `onsubmit` string through `ui.templates.env` with a label containing an apostrophe (emits `'Archive Editor&#39;s Cut? ...'`, which the HTML parser decodes back to a bare `'`); grep of `static/htmx.min.js` (1.9.12, no detached-target check before a swap). No em dash found in any template in the territory (grep for U+2014, `&mdash;`, `&#8212;`).

## Findings

### ui-dash-admin-1 - A project name with an apostrophe breaks the ARCHIVE confirm and archives with no question (and a crafted folder name runs script on the admin's page)
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/templates/admin_assignments.html:166
- What: The confirm is built as `onsubmit="return window.confirm('Archive {{ p.label }}? ...')"`. Jinja escapes `'` to `&#39;`, but the attribute is HTML-decoded before the handler is compiled, so the label lands raw inside a single-quoted JS string. `p.label` is the project's relative folder path (collector.py:1020 / api.py:3546 `upsert_project(conn, slug, rel, ...)`), i.e. a folder name anyone with write access to the tree chooses.
- Failure scenario: A project folder called `Editor's Cut` (or any English possessive) -> the inline handler is a SyntaxError -> per the HTML spec the handler is null -> the admin's click on [ ARCHIVE ] submits immediately with no confirm. A folder named `x');fetch('/partials/admin/users/delete',{...});('` (Windows allows every one of those characters) executes that code in an admin's session the moment the admin clicks ARCHIVE on that row.
- Evidence: rendered the attribute through the dashboard's own Jinja env: `<form onsubmit="return window.confirm('Archive Editor&#39;s Cut? ok');">`. The cards landing page already fixed the same shape with `| tojson` (KNOWN_BUGS 29431, cards_landing.html:44); this one was missed.
- Ledger: new (same shape as the fixed Cards episode-name entry at KNOWN_BUGS:29431)
- Suggested fix: `onsubmit='return window.confirm({{ ("Archive " ~ p.label ~ "? ...") | tojson }});'` (single-quoted attribute, JSON string), or move the text into a `data-confirm` attribute read by confirms.js.

### ui-dash-admin-2 - The fleet halt says it "releases itself 0s ago" for the whole 24 hours it is active
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/fleet_halt.html:38; dashboard/templates/partials/fleet_halt_banner.html:13 (filter: dashboard/src/ccsync_dashboard/ui.py:93-114)
- What: `halt.expires_at` is in the FUTURE while a halt is active, and the `ago` filter clamps negative deltas to 0 (`seconds = max(int(delta.total_seconds()), 0)`) and always appends "ago".
- Failure scenario: Admin stops the fleet. The every-page banner shown to every editor and the admin panel both read "it releases itself 0s ago unless somebody keeps it on" - i.e. that it has already released - for the entire 24 h. The one number UX-8 added so "I will look at it on Monday" reads as what it is, is wrong on every page.
- Evidence: `ui.ago((now + 23h).isoformat())` returns `'0s ago'` in the dashboard venv.
- Ledger: new (UX-8 feature, KNOWN_BUGS ~6470)
- Suggested fix: a `until` filter ("in 23h") for future stamps, used on both lines; keep `ago` for the expired branch.

### ui-dash-admin-3 - The Users and Packages polls wipe what the admin is typing and orphan in-flight writes (undoing DUI-4's busy labels)
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/admin_users.html:16 (30 s innerHTML poll around the whole USERS panel) and :29-30 (60 s around REPORT TOKENS); dashboard/templates/admin_packages.html:14 (30 s around the packages panel)
- What: Every form on those panels lives inside a wrapper that re-fetches and replaces its innerHTML on a timer: CREATE LOCAL ACCOUNT / CREATE NEW EDITOR ACCOUNT (username, SSH key textarea, password), SET password, ADD SSH KEY, the device-approval owner field, MINT A TOKEN, the typed "type 0.9.77" override and the push-one computer select. htmx 1.9.12 does not check that a response's target is still in the document, and the forms' targets are `closest .admin-users-box` / `closest .admin-packages-box`, which the poll has detached. The other admin pages say in their own comments that they are NOT polled for exactly this reason (admin_alerts.html:17, admin_audit.html:18, admin_protection.html:22).
- Failure scenario: (a) Admin pastes an editor's public key and types a username, looks something up for 30 s -> the form comes back blank, focus gone. (b) Admin clicks [ CREATE ] on a NAS account, which the page itself says "can take up to two minutes": the next poll replaces the form with a fresh one showing [ CREATE ] again (the `.htmx-request` class was on the old form), so the "CREATING THE ACCOUNT ON THE NAS..." label vanishes within 30 s; when the POST answers, its panel (the notice or the refusal banner) is swapped into the detached box and never seen. Only the OOB password survives. The natural next move is a second CREATE. Same for [ PUBLISH ] / [ PUBLISH + MAKE CURRENT ] ("DOWNLOADING THE BUILD...", tens of MB) and [ CHECK NOW ] on Packages.
- Evidence: admin_users.html:16/29-30, admin_packages.html:14 poll attributes; htmx.min.js 1.9.12 response path (`Mr`) computes the target at request time and swaps without a `bodyContains` check; no `hx-sync`, `hx-preserve` or pause-on-focus anywhere in static/ (grep).
- Ledger: new
- Suggested fix: pause the wrapper's poll while any descendant form has focus, input, or `.htmx-request` (`hx-trigger="every 30s [document.visibilityState === 'visible' && !this.querySelector('.htmx-request, :focus')]"`), or poll only the read-only tables and keep the forms outside the swapped element.

### ui-dash-admin-4 - "OTHER VERSIONS HELD ON THIS SERVER" (the rollback list) snaps shut every 30 seconds
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/admin_packages.html:459; also dashboard/templates/partials/fleet_halt.html:89 (PREVIOUS STOPS, 60 s poll)
- What: base.html's open/closed keeper (base.html:62-86) and tab_memory.js only remember a `<details>` that has a `data-key` or an id. `details.pkg-other` and the halt history `details.proj-group` have neither, and both live inside a timed innerHTML poll.
- Failure scenario: Admin opens OTHER VERSIONS to find the build to roll back to, reads the canary line, and within 30 s the section collapses under the cursor, scrolling the page; the MAKE CURRENT / MAKE CURRENT ANYWAY controls they were about to use disappear. Same for PREVIOUS STOPS on the Users page every 60 s.
- Evidence: grep for `pkg-other` finds only the template and one style rule; no `data-key` on either element; the keepers select `details[data-key]` / id.
- Ledger: new
- Suggested fix: `data-key="pkg-other"` and `data-key="halt-history"` on the two elements.

### ui-dash-admin-5 - The result of SEND A TEST / SET PASSWORD / RUN NOW / RESTORE / REHEARSE / a date refusal renders a screen or more above the button
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/admin_alerts.html:15-16 (buttons at :145, :170, :182-183, :193); dashboard/templates/partials/recovery.html:16-17 (buttons at :182, :210); dashboard/templates/partials/protection.html:19-20 (forms at :77-101)
- What: Each panel swaps outerHTML (scroll preserved) and puts its `error` / `notice` at the very top as a plain `banner` or `muted` div. The DUI-6 mechanism that moves a refusal next to its button (htmx_errors.js) only acts on `.error-banner`, which none of these three panels use.
- Failure scenario: Admin scrolls past twenty alert-settings fields and CURRENTLY OPEN, presses [ SEND A TEST ]; "the test could not be sent: ..." (the only thing that button exists to say) appears above the viewport and the page looks unchanged. [ SAVE ] refused on one bad field ("alerts.set_settings refuses the whole form"): same. On Recovery, a restore refused with "nothing in the snapshot ... is missing" or "already exists", or a FAILED rehearsal, lands at the top of the longest page in the product. On Protection, "that date is in the future" is invisible under the forms.
- Evidence: route code ui.py:2209-2316 (alerts), the recovery restore/drill routes above ui.py:2196, ui.py:2033-2068 (protection) all re-render with `error`/`notice`; templates use `class="banner"` without `error-banner`.
- Ledger: related to DUI-6 (fixed for users/packages/jobs/fleet-halt only)
- Suggested fix: `class="banner error-banner"` for the error on all three panels, and render the notice next to (or move it beside) the form that posted.

### ui-dash-admin-6 - Site Settings [ SAVE ] gives its answer at the top of the page, and a stale "saved" stays beside a later failure
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/templates/admin_settings.html:14-15, :183; dashboard/static/site_settings.js:31-37, :794-799
- What: The save handler writes "saved" into `#settings-saved` and errors into `#settings-error`, both above the first field; the button is below ~20 fields with hints. `settings-saved` is never cleared: `showError` hides only the error div, and a failed save leaves the previous "saved" in place right under the new error.
- Failure scenario: Owner changes DASHBOARD URL near the bottom, presses [ SAVE ]: nothing visible happens. A second save that is refused shows "▲ could not save: ..." directly above the old "saved", two contradictory statements, both off screen. Import and undo errors use the same top slot, far above the import box.
- Evidence: read site_settings.js; no scrollIntoView and no clearing of `settings-saved` anywhere in the file.
- Ledger: new
- Suggested fix: clear `settings-saved` at the start of each submit and on error, and show the result beside the button (or scroll the result line into view).

### ui-dash-admin-7 - HEALTH says "Every check this server runs answered" when a source raised
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ui.py:1866-1941 (`_health_rows`), rendered by dashboard/templates/admin_health.html:113-117
- What: Each of the four sources (notices, alert scan, invariants, protection) is wrapped in `except Exception: log.exception(...)` that adds no row. If any source fails its rows silently vanish; if all fail (a locked DB, a bad migration) the page renders the green-sounding banner "Nothing is open. Every check this server runs answered, and none of them found a problem."
- Failure scenario: `protection.page_view` raises after an upgrade. The HEALTH page (the page SYS-6 made "the authoritative one") shows everything else and nothing about protection; with a broader failure it says all is well. That is the "unverified check rendered as OK" shape CLAUDE.md's self-diagnosis rule forbids.
- Evidence: read the four try/except blocks; none appends an `unknown`-band row.
- Ledger: new
- Suggested fix: in each except, add one `band="unknown"` row naming the source ("could not read the protection lines, see the log"), so the NOT CHECKED band and count reflect it and the green sentence cannot render.

### ui-dash-admin-8 - An Android validation refusal throws away the fingerprints the admin just pasted
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/android.py:180-187 and :129-148 (`_context`); template dashboard/templates/partials/android_settings.html:129-141
- What: On `SiteValidationError` the route re-renders from `site_store.resolved_manifest`, i.e. the last SAVED values. The comment says "the admin's own text is still in the boxes", but the swap replaces the form's fields with the stored ones.
- Failure scenario: Admin pastes three fingerprints, one of them with a typo -> the panel shows the refusal and the textarea goes back to its old (often empty) value; the other two fingerprints have to be found and pasted again.
- Evidence: `_context` takes no form values; the template's fields read only `manifest.android.*`.
- Ledger: new
- Suggested fix: pass the submitted `package_name` / `sha256_cert_fingerprints` into the context on the error path and prefer them in the template.

### ui-dash-admin-9 - SMTP [ SET PASSWORD ] / [ CLEAR ] say "stored" / "cleared" when the environment password is the one in use
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/admin_alerts.html:177-188; dashboard/src/ccsync_dashboard/ui.py:2247-2267; alerts.py:503-513
- What: `read_password` makes ENV win, and the template still offers both buttons when `password_source == "env"`. The route writes or deletes the file and answers "password stored." / "password cleared.", while mail keeps going out with the env value.
- Failure scenario: Admin rotates the Google app password here, sees "password stored.", and mail keeps failing with the old env password; or clears it and mail keeps working.
- Evidence: read the three functions.
- Ledger: new
- Suggested fix: hide or disable the two buttons when the source is env, or have the route answer "stored, but the deployment's environment password is used instead".

### ui-dash-admin-10 - Protection: today's date is refused as "in the future" for the first hours of the day east of UTC
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/protection.py:800-803 (form at dashboard/templates/partials/protection.html:81, :94)
- What: The check compares the typed date with the UTC date (`text[:10] > stamp[:10]`); the browser's date picker offers the admin's local date.
- Failure scenario: The owner (Taiwan, UTC+8) records a key backup at 07:00 local, picks today in the picker -> "that date is in the future.", rendered at the top of the panel where finding 5 hides it.
- Evidence: read `set_ack`.
- Ledger: new
- Suggested fix: allow one day of slack, or compare against the site time zone (`alerts.timezone_name`).

### ui-dash-admin-11 - A minted report token runs off a phone screen
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/minted_secret.html:26; dashboard/static/style.css:442 and :1900
- What: The value carries `mono-sm` (`white-space: nowrap`), which defeats `.minted-value { word-break: break-all }`, and `#minted-secret` sits outside `.admin-users-box`, so mobile.css's round-2 unwrap rule never reaches it.
- Failure scenario: At 390 px a `cce1.<16 hex>.<48 hex>` token (70 characters, ~500 px at 12 px) overflows the green box and makes `main.main` scroll sideways; the admin reading it to transcribe sees it cut at the edge.
- Evidence: CSS cascade read; `.main { overflow-x: auto }`.
- Ledger: new
- Suggested fix: `white-space: normal` on `.minted-value` (or drop `mono-sm` from it).

### ui-dash-admin-12 - Raw ISO timestamps beside humanised ones on the same pages
- Severity: low
- Confidence: CONFIRMED
- Where: partials/admin_report_tokens.html:54-55 (CREATED, LAST USED); partials/fleet_halt.html:29 ("set by X at 2026-09-24T03:16:18+00:00", while the banner and history say "3h ago"); partials/admin_alerts.html:157-166, :214, :218 (running since, last check, replies last read, WHEN); partials/recovery.html:216, :224; static/site_settings.js:751 (change history); db.set_fleet_halt's refusal "Syncing already started again at <iso>"; partials/admin_jobs.html:33 ("the oldest has waited 86400s")
- What: Everywhere else in the product uses `| ago`; these print the stored UTC ISO string (or raw seconds), which a non-technical owner in UTC+8 has to convert in their head.
- Failure scenario: The report-tokens table shows "2026-09-24T03:16:18.123456+00:00" in a column beside the sessions panel's "3h ago"; the jobs head says "the oldest has waited 172800s".
- Evidence: template reads.
- Ledger: new
- Suggested fix: `| ago` (with the ISO in a `title=`) in the templates, and `eta` for the job age.

### ui-dash-admin-13 - The restore confirm counts only missing files, so it can say "Copy 0 file(s)"
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/partials/recovery.html:167-178
- What: The form is offered when `missing_count or changed_count`, but the confirm text is always `Copy {{ missing_count }} file(s)`, and the "also bring back the ones that are different" box is unticked by default.
- Failure scenario: A project whose snapshot differs only in changed files: the admin clicks RESTORE and is asked "Copy 0 file(s) into a new folder?". If they did not tick the box, the restore is refused with "nothing ... is missing", shown at the top of the page (finding 5).
- Evidence: template read; `restore_into_quarantine` refuses an empty set (recovery.py).
- Ledger: new
- Suggested fix: offer the button only when there is something to copy under the current checkbox state, and word the confirm from both counts ("N missing, plus M different if ticked").

### ui-dash-admin-14 - Two buttons whose words say something other than what they do
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/templates/admin_settings.html:251 with static/site_settings.js:739-760; dashboard/static/dashboard_update.js:157-166 with partials/admin_dashboard_update.html:100
- What: (a) "[ UNDO LAST IMPORT ]" calls `/admin/site/undo-last-change` and undoes the newest save OR import; the blurb above it says as much. (b) "[ ROLL BACK TO 0.7.55 ]" shares the apply handler and asks "Update this dashboard to 0.7.55?".
- Failure scenario: The owner saved a field after importing, clicks UNDO LAST IMPORT expecting the import to go, and only the save is undone. A rollback prompt that says "Update" is the wrong word at the one moment the owner is going backwards.
- Evidence: read both handlers.
- Ledger: new
- Suggested fix: "[ UNDO LAST CHANGE ]"; pass a flag on the rollback buttons so the confirm says "Roll this dashboard back to X?".

## Coverage note
Not reached: `static/assignments.js` and `static/confirms.js` in depth (the assignments grid's own toasts and column tools), `static/copy_value.js`, the full ai-providers wizard half of site_settings.js, and the collector_health partial beyond reading it (it is rendered inside the fleet grid, which is another territory's page). No page was rendered in a real browser at 390 px; the phone findings come from reading the CSS cascade.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/dashboard_update.py:1655-1694: `rollback_candidates` are not filtered by `runtime_id`, so a [ ROLL BACK TO X ] offered for a bundle built on another runtime always 409s in `preflight`.
- dashboard/src/ccsync_dashboard/dashboard_update.py:1586-1595: the schema refusal tells the admin to "Send restore_db with the backup name, or acknowledge_schema", which are API field names; the page has no acknowledge control.
