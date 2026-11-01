# Bug hunt: dashboard UI (bug-dash-ui), 2026-10-06

Lens: the dashboard's ui*.py, help.py, published_docs.py, static_files.py, ui_assets.py,
templates/, static JS/CSS and sw.js, reviewed against the working tree (HEAD 08b40eb plus the
uncommitted alert-kind selection).

What I did:
- Read shell.html, the stale-page gate, the CSRF and login gates (only where they touch htmx),
  sw.js, pwa.js, home.js, everyday.js, confirms.js, the innerHTML sites in site_settings.js,
  help.py's renderer and path rules, published_docs.py, static_files.py and ui_assets.py, the
  /login `next` handling, /go, /download, and the uncommitted alerts-kinds route, template and
  alerts.py diff.
- Crawled all 110 GET routes in-process (TestClient, temporary DB), as an admin and as an
  editor, with and without htmx headers. Before the crawl I seeded a companion report and a
  project whose free-text fields held `"'><zzx>`. Result: no 5xx, no unescaped payload in any
  HTML response, and no em dash in product copy (the only hits were inside documents rendered
  in /help, which the rule exempts). An editor gets 403 on every /admin and admin partial route.
- Served the app on localhost and loaded 19 pages in headless Chrome at its narrowest window
  (500 px) with long unbroken machine, project and file names. Only one page overflowed (see -1).

Not covered: a real phone-width (360-390 px) pass (headless Chrome would not go below 500 px),
cards_landing.js, assignments.js, setup.js, account.js and the rest of site_settings.js,
line by line.

### bug-dash-ui-1 - A long project name with no spaces makes the project page scroll sideways
- Severity: low
- Confidence: CONFIRMED (headless Chrome probe)
- Where: dashboard/templates/project.html:28, dashboard/static/cc/terminal.css:219 (.head h1), dashboard/static/cc/phone.css:7
- What: `.head h1` has no `overflow-wrap: anywhere` or `min-width: 0`, so a project label with no
  break opportunities (the usual `2026_FF5_Civil_Defence_Interviews` shape) widens the page.
- Scenario: a project labelled `A_very_long_project_name_without_any_spaces_at_all_2026_FF5`. On
  /project/<slug>, document.scrollWidth was 1018 px against a 500 px viewport. The H1, its span,
  the head div and `.sub` all ran past the right edge, so on a phone the whole page pans
  sideways. No other page overflowed with the same data.
- Recommendation: add `overflow-wrap: anywhere; min-width: 0` to `.head h1`, `.head .sub` and the
  head's first grid/flex child. Add a regression test that renders a long unbroken label.
- Known: none

### bug-dash-ui-2 - No browser security headers on any dashboard response
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/app.py (no middleware sets them); grep for nosniff, X-Frame-Options or Content-Security-Policy in src/ finds nothing
- What: HTML pages, /admin/alerts/preview (PlainTextResponse), /help and the static files go out
  with no X-Content-Type-Options, no frame-ancestors / X-Frame-Options, no Referrer-Policy and no
  CSP. docs/MOBILE_PLAN.md:47 records "Security headers: none, and no CSP" as a known gap, and
  KNOWN_BUGS does not track it.
- Scenario: SameSite=Lax blocks the obvious cross-site clickjacking, but any SAME-SITE origin can
  frame the admin pages, where one click is a fleet halt, a user delete or a package publish.
  Same-site here includes another port on the same tailnet host, such as the Funnel share port,
  and a sibling subdomain at a customer that runs the dashboard under its own domain. A
  customer's security questionnaire or pen test will flag every one of these headers on day one.
- Recommendation: one middleware that sets `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: frame-ancestors 'self'` (plus `X-Frame-Options: SAMEORIGIN`) and
  `Referrer-Policy: same-origin` on dashboard responses. Leave the mounted SPAs and
  /broll/share alone unless their owners agree. A full script CSP is later work (htmx's
  allowEval and the inline scripts in shell.html need it planned).
- Known: docs/MOBILE_PLAN.md:47 (noted, never filed)

### bug-dash-ui-3 - The /help markdown renderer escapes link targets twice, so `&` in a URL breaks
- Severity: low
- Confidence: CONFIRMED (probe of help.render_markdown)
- Where: dashboard/src/ccsync_dashboard/help.py:473 and :494
- What: `_inline` runs `html.escape` over the whole line first. `_link_html` then escapes the
  already-escaped href again (`quote=True`), so `&` becomes `&amp;amp;`.
- Scenario: `[x](https://a.example/?a=1&b=2)` renders as `href="https://a.example/?a=1&amp;amp;b=2"`,
  so the browser requests `?a=1&amp;b=2`. None of the shipped documents has such a link today,
  but the published legal tree (EULA, privacy, notices) is exactly where a vendor adds an
  `?...&...` URL.
- Recommendation: unescape the href before re-escaping it (`html.escape(html.unescape(href), quote=True)`)
  or match links before the line is escaped. Add a test for a URL that contains `&`.
- Known: none

### bug-dash-ui-4 - The new alert-kinds form blanks its All / Problems only / None buttons while a save is in flight
- Severity: low
- Confidence: CONFIRMED (CSS read)
- Where: dashboard/templates/partials/admin_alerts.html (uncommitted #alerts-kinds-form foot-keys), dashboard/static/cc/health.css:76-81
- What: `#admin-alerts form.htmx-request .key .t { display: none }` hides the label of EVERY key
  in the form. Only Save has a `.busy-t` to show in its place.
- Scenario: the admin clicks "None". For the length of the request the three preset keys are
  empty boxes, and the one that was clicked shows no "saving" state.
- Recommendation: give the preset keys a `.busy-t`, or scope the rule to `[data-busy]` keys.
- Known: none (the code is new and uncommitted)

### bug-dash-ui-5 - The installer 404 shown to an editor names a vendor-only release tool
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ui.py:4008-4021 (page_download_platform)
- What: when no onboard build is published, the plain-text 404 that the editor's [ INSTALLER ]
  click lands on says "Admins: publish one with `tools/publish_latest.py --kind onboard ...`".
  That tool runs from the vendor's repository with the offline signing key, and a customer's
  admin has neither.
- Scenario: a new customer's first editor clicks [ INSTALLER ] before the vendor feed has
  delivered an onboard build. They forward the message, and the customer's admin goes looking
  for a script they do not have.
- Recommendation: point admins at Settings > Packages ("check the vendor feed / upload"). Keep
  the publish_latest wording out of customer builds.
- Known: CR-59 rewrote this text for the editor; this sentence survived it

### bug-dash-ui-6 - An installed Cards app's sign-in page is outside the app's scope
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/cards_landing.py (APP_SCOPE = "/cards/", commit 0c37831); app.py login_gate 303 to /login
- What: the Cards app is now scoped to /cards/, and the login gate redirects an expired session
  to /login, which is outside that scope. On Android that navigation opens with an
  out-of-scope toolbar. In iOS standalone mode, an out-of-scope navigation can open in an
  in-app Safari sheet, which may not share the web app's cookie jar.
- Scenario: a phone user opens the installed Cards icon the morning after the session expired.
  The sign-in page may open outside the app, and on iOS the new session cookie may never reach
  the app, so it loops back to sign-in. Not tested on a device.
- Recommendation: test once on iOS and Android. If it misbehaves, serve the sign-in at a
  /cards/login alias, or widen the scope to "/" with start_url /cards/.
- Known: none
