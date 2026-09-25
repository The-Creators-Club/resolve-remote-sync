# Verifier med-14 - ui-dash-main-1, -2, -3, -4, -7, -8

Judged against HEAD (63d4290) with `git show HEAD:<path>`. The htmx facts were
read from the vendored `dashboard/static/htmx.min.js` at HEAD (version 1.9.12).

Common htmx fact behind 1 and 2 (read in the minified source at HEAD): the
response handler does `u.target=c` (the original target) and then fires
`ce(e,"htmx:afterSwap",u)` on each element in `settleInfo.elts`. The
outerHTML swap (`function Ie`) drops the old target from `r.elts`, pushes the
new siblings, and ends with `u(t).removeChild(t)`. There is no reassignment
of `u.target` for outerHTML. So after an outerHTML swap, `evt.detail.target`
is the detached old element and `evt.target` is the new one.

## ui-dash-main-1 - CONFIRMED (medium)

The sidebar checkbox posts with `hx-target="closest .projects"
hx-swap="outerHTML"` (sidebar.html at HEAD), and `partial_toggle` with
`view=sidebar` renders the whole `partials/sidebar.html` (ui.py ~1436-1439),
which holds both the `.sheet-handle` button and the `<nav popover>`. base.html's
details keeper saves state from `detail.target` before the swap and reapplies
it to `detail.target` after, which is the detached old nav, so the new tree
comes back with only the server default open (nothing, on `/`). The new nav is
a new `popover` element and starts closed, and the extra button is inserted
beside the old one. Mechanism holds end to end; ticking several projects in a
row is the rail's main job, so medium is right.

Evidence: base.html:61-86 and sidebar.html:21-22, 74-76 at HEAD; ui.py
`partial_toggle`; htmx.min.js `Ie` and the afterSwap loop.

## ui-dash-main-2 - CONFIRMED (medium), DUPLICATE of ui-dash-static-1

`htmx_errors.js:225-256` at HEAD takes `root = detail.target` and searches it
for `.error-banner`. For every panel it serves, the swap is outerHTML
(admin_users `closest .admin-users-box`, admin_packages
`closest .admin-packages-box`, admin_jobs `#admin-jobs`), so it searches the
detached old panel and returns. The refusal stays at the top of the new panel,
which is the DUI-6 symptom. This is the same defect, same file and same fix as
ui-dash-static-1 (which also covers the chip tabindex pass at :167-175), so it
should be tracked there once.

Evidence: htmx_errors.js at HEAD; hx-target/hx-swap greps of admin_users.html,
admin_packages.html, admin_jobs.html; KNOWN_BUGS CR-259f (the earlier fix, built
on the same `detail.target` assumption).

## ui-dash-main-3 - CONFIRMED (medium)

`#project-detail` on project.html polls `/partials/project/<slug>` every 10 s
with `hx-swap="innerHTML"`, and both the SHARE A FOLDER form and the MOVE form
(text inputs with no id, the `to_slug` select, `to_path`) are inside it
(project_detail.html:131-184 at HEAD). Nothing in the static JS pauses a poll
on focus or dirtiness (grep for `activeElement` / `beforeRequest` finds only
htmx_errors.js' chip handler and path map; pwa.js only slows 2 s/5 s polls and
aborts on hidden). No `hx-preserve` on these fields. So each beat replaces the
inputs with empty ones and drops focus. Nothing is destroyed (an empty MOVE is
refused by the server with a banner), so medium, not higher.

Evidence: project.html:11-13, project_detail.html:131-184, pwa.js and
htmx_errors.js at HEAD.

## ui-dash-main-4 - DOWNGRADE (low)

The mechanism holds: fix_root.html:18-21 links to `/` and
`/?machine=<m>` without `as=`; `_queue_editor` reads `as` only from the query
and so falls back to the admin; `_queue_machine` then rejects a machine not in
`machines_of(admin)`. But it is a read-only view hop on a full page navigation,
and the change is visible: the queue header becomes `[ SYNC QUEUE: ALEX ]`,
the switcher resets to "(me)" and the "acting as" warning disappears. Nothing
is written, nothing is ticked in the wrong place without a further, visible
mistake, and the admin can reach the view by adding `&as=` by hand. Low.

Evidence: fix_root.html at HEAD; ui.py `_queue_editor` (608), `_queue_machine`
(620), `page_fleet` (686); editor_switcher.html and my_queue.html headers.

## ui-dash-main-7 - CONFIRMED (medium)

plan_changes.html:47-50 at HEAD posts `[ UNDO ]` with no `hx-confirm` on any
row. For a TICKED row, `partial_plan_change_undo` removes every `after`
placement not in `before`, which for a person-level tick is every computer the
person owns, i.e. an untick of the whole person in one click. Every other
person-level untick carries the DASH-8 confirm naming the computers
(sidebar.html:23-30), which exists because of CR-49's wrong-row untick; the
undo cannot itself be undone from this panel (its audit action is
`plan.undo`, which the route refuses). Recoverable by re-ticking and no files
are deleted, so medium rather than higher. The slug-only label point is
cosmetic.

Evidence: plan_changes.html at HEAD; ui.py `partial_plan_change_undo`
(1698-1760); sidebar.html DASH-8 confirm.

## ui-dash-main-8 - CONFIRMED (medium)

Every page's `<aside class="sidebar">` polls `/partials/sidebar` every 30 s
with innerHTML (fleet.html:6-7, project.html:6-7 at HEAD), and below the phone
breakpoint the rail is `<nav id="projects-sheet" popover>` inside that aside.
Removing an open popover from the document hides it, and the replacement is a
fresh closed element; nothing in static/*.js, base.html or ui.py records or
reopens `:popover-open` (grep for `projects-sheet`, `showPopover`,
`popover-open` finds only CSS and the template). pwa.js does not slow 30 s
polls. So an open sheet closes at the next beat with its scroll reset. Distinct
from ui-dash-main-1 (the tick path, outerHTML) though the same fix area.

Evidence: fleet.html, project.html, sidebar.html, style.css:1425-1460, pwa.js
at HEAD.
