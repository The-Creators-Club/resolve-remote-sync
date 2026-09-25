# Verifier med-16 (2026-09-25)

Judged against HEAD (`git show HEAD:<path>`), read-only.

## ui-dash-static-1 - CONFIRMED (medium)

In HEAD's htmx.min.js the request info is built as `I={xhr:b,target:u,...}` (the original target), the outerHTML swap (`Ie`) ends with `r.elts=r.elts.filter(e!=t)` then `u(t).removeChild(t)`, and afterSwap is fired per settled element with that same info object. So `detail.target` in htmx_errors.js:227 is the detached old panel for every outerHTML swap. The admin panels that carry `.error-banner` (admin_jobs, admin_packages, admin_report_tokens, admin_users, fleet_halt) all swap `outerHTML`, so the mover searches a detached tree and the refusal stays at the top of the new panel. The chip `focusable()` pass at :175 has the same stale-root defect. Medium is right: it is a regression of the DUI-6 fix's whole purpose on the pages it was written for.
Evidence: htmx.min.js (HEAD) swap and afterSwap code; `git grep 'hx-swap="outerHTML"'` and `git grep error-banner` over dashboard/templates.

## ui-dash-static-2 - CONFIRMED (medium)

htmx_errors.js:61-70 treats every responseError the same way: 401/403 become "Your session has ended", and anything else becomes "THIS PAGE HAS STOPPED UPDATING ... The server answered N". It never reads `xhr.responseText`. There is no htmx:beforeSwap anywhere that lets a 4xx swap (base.html's beforeSwap only records details state). The sidebar toggle route (ui.py) answers `403 if user else 401` and 409 with a detailed reason for wired machines, so a signed-in 403 is mislabelled as an ended session and the 409 reason is lost. The next successful request clears the banner. Real and user-misleading on every write route; medium.
Evidence: HEAD htmx_errors.js, base.html, ui.py toggle route, sidebar.html hx-post.

## ui-dash-static-3 - CONFIRMED (medium)

`loadSiteHistory()` runs once at DOMContentLoaded and the undo button's `latest` is captured in its closure. The settings save handler (:794-799) and the CLI-provider flag (:139-141) both PUT /api/v1/admin/site, which records a new `save` history entry (setup_routes.py:326), and neither reloads the history. `undo-last-change` always reverts `entries[0]` (setup_routes.py:431-435). So the confirm names the old entry while the server reverts the save just made. That silently reverts a site setting (a drive letter, say) the admin did not mean to touch, so medium is fair.
Evidence: HEAD site_settings.js:737-814, setup_routes.py:301-447.

## ui-dash-static-4 - DOWNGRADE (low)

Real for the apply path: `runUpdate`'s catch writes the refusal into `#dashupd-progress` and then calls `reloadPanel()`, which replaces the panel's outerHTML with a render that knows only `in_progress` and `last_error`. The refusal text is therefore wiped. The rollback half of the finding title does not hold, because the rollback catch (:198) only calls `progress()` and never reloads, so its refusal stays. In the "update already in progress" example the repainted panel shows "working: <step> - ..." and resumes watching, so the admin does see why. What is left is a vanished reason for a signature or runtime refusal on an admin-only, retryable action, with nothing harmed. That is low.
Evidence: HEAD dashboard_update.js:38-43, 59-80, 131-151, 170-199; admin_dashboard_update.html:11-66.

## ui-broll-web-1 - DOWNGRADE (low)

The mechanism holds. share.css:62-64 sets `grid-template-columns: 1fr`, which is `minmax(auto, 1fr)`, and `.video-meta .title` (style.css:831) has no `overflow-wrap`/`word-break`. An underscore-joined camera filename has no break opportunity, so the single column widens to its min-content. The hunter's 390 px render (docW 463) matches that. The result is sideways scrolling on the public page for some clips, but the player and controls stay reachable by scrolling. This is the same class as ui-broll-web-2 and -8, which the hunter filed as low, and it is cosmetic with no loss of function.
Evidence: HEAD share.css, share.js:281-285, style.css:825-851.

## ui-broll-web-3 - CONFIRMED (medium)

app.js:1528-1586 `onKeydown` is registered on `document` (:962). While `state.detail` is set, it exempts only INPUT, SELECT and TEXTAREA. Enter always calls `preventDefault()` and `sendToResolve(...)`, and Space/K toggles playback. No other handler stops these keys: clientfolders.js's capture listener stops only Escape with the popover open, and ingest.js handles only Escape. So with a detail open, Enter on any focused button does not activate it and can instead append the clip to the live Resolve timeline. That covers the detail view's own meta-link buttons and every button in the cf, ingest and settings drawers. That is an unintended mutation plus a keyboard trap, so medium stands.
Evidence: HEAD app.js:955-962, 1200-1215, 1528-1587; clientfolders.js:130-135; ingest.js:237-239.

## ui-broll-web-4 - DOWNGRADE (low)

Confirmed that nothing writes `--header-h`: its only definition is the constant `88px` at style.css:42, and it is read at :1015/:1024/:1025. `#app-header` is sticky with z-index 10 and holds the injected topbar plus the controls row, so at the widths the hunter measured (98-233 px) it paints over the top of the sticky rail. The effect is that the rail's head row and first folder are hidden while the page is scrolled, and scrolling back up shows them. That is a layout nuisance with no lost data or function, so low.
Evidence: `git grep header-h HEAD -- broll/web/static`; HEAD style.css:141-148, 1012-1026.

## ui-broll-web-5 - DOWNGRADE (low)

The mechanism holds. `cfCreateFlow` toasts "Created" and returns `afterCreate(folder)` with no catch (clientfolders.js:220-221). The `+ new folder` handler awaits it with no catch (:589-599), so a failed items POST is an unhandled rejection: no error toast, and the popover is not re-rendered. The trigger is narrow, though. The create POST has just succeeded on the same session a moment earlier, so the add must fail independently (for example, a video removed in between). The editor also never sees the "Added to" toast they would otherwise get. The result is an empty folder, which is visible and recoverable, not data loss. Low.
Evidence: HEAD clientfolders.js:205-224, 545-605.
