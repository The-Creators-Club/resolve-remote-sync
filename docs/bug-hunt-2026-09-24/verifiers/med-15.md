# Verifier med-15 - ui-dash-admin-2..7

Judged against HEAD (63d4290) with `git show HEAD:<path>`.

## ui-dash-admin-2 - fleet halt "releases itself 0s ago" - CONFIRMED (medium)

`ui.ago` (ui.py:93-114 at HEAD) computes `now - stamp`, clamps a negative
delta with `max(..., 0)` and always appends "ago". A halt's `expires_at`
(db.py:8192-8307) is a future ISO stamp while active, and both
`partials/fleet_halt.html:38` and `partials/fleet_halt_banner.html:13` pipe it
through `ago`. So every page, for every signed-in user, says the stop has
already released itself while the banner beside it says syncing is stopped;
the one line UX-8 added to answer "when does this end" is wrong for the whole
24 h. No `until` filter exists (only human_bytes/ago/bar/eta/lane_word are
registered). Not in KNOWN_BUGS or an earlier hunt.
Evidence: ran `ui.ago((now+23h).isoformat())` in the dashboard venv (ui.py is
unmodified in the tree): `0s ago`.

## ui-dash-admin-3 - Users/Packages polls wipe forms and orphan in-flight writes - CONFIRMED (medium)

`admin_users.html:16` and `admin_packages.html:14` poll `innerHTML` every 30 s
around the whole partial, and every write form inside (`partials/admin_users.html`
create/password/keys/approve, `partials/admin_packages.html` push-one,
current, feed publish/check/policy) targets `closest .admin-users-box` /
`.admin-packages-box`, i.e. the element the poll replaces. No `hx-sync`,
`hx-preserve`, focus guard or `htmx:beforeRequest` cancel exists in static/ or
the templates (grep), so typed values are discarded on the next tick and the
`.htmx-request` busy label disappears with the old form. When the slow POST
answers, its target is detached; htmx 1.9.12's swap path either inserts into a
null parent (caught as `htmx:swapError`) or into a detached node - either way
the result or refusal is never seen, and the page shows a fresh [ CREATE ]
inviting a second NAS account create. Medium is right: operator-facing, can
lead to duplicate writes, but no data loss by itself.

## ui-dash-admin-4 - OTHER VERSIONS / PREVIOUS STOPS snap shut on every poll - DOWNGRADE (low)

Real: `details.pkg-other` (partials/admin_packages.html:459) and the halt
history `details.proj-group` (partials/fleet_halt.html:89) carry neither
`data-key` nor `id`; base.html's keeper only restores `details[data-key]`,
and tab_memory.js's `detailsId` needs an id or data-key too. Both live inside
30 s / 60 s innerHTML polls, so they re-render collapsed. It is low, not
medium: nothing is lost or mis-written, the section reopens with one click,
PREVIOUS STOPS is read-only history, and the rollback controls inside keep
their own confirms. A one-attribute annoyance fix.

## ui-dash-admin-5 - alerts/recovery/protection results render above the viewport - CONFIRMED (medium)

At HEAD `partials/admin_alerts.html:15-16`, `partials/recovery.html:16-17` and
`partials/protection.html:19-20` put `error` in `class="banner"` (no
`error-banner`) and `notice` in a muted div at the top of the panel; every
form in them swaps `outerHTML` onto the panel id with no `show:` modifier, so
scroll is preserved. `htmx_errors.js` only relocates `.error-banner`, and the
only other `scrollIntoView` calls (setup.js, tab_memory.js, base.html
fragment scroll) do not apply. KNOWN_BUGS:13040 documents DUI-6 as fixed for
"the six partials" only; these three were never included. Same shape and
severity the DUI-6 fix was filed at; SEND A TEST, whose whole output is the
message, shows nothing visible.

## ui-dash-admin-6 - Site Settings SAVE answers at the top, stale "saved" kept - CONFIRMED (medium)

`admin_settings.html:14-15` holds `#settings-error` and `#settings-saved`
above the first field; the [ SAVE ] button is at :183 below ~20 hinted
fields. `site_settings.js:794-799` writes "saved" on success and on failure
only calls `showError`, which never touches `#settings-saved`; nothing in the
file clears it or scrolls either line into view. So a refused save after a
successful one shows "could not save" directly above "saved", both off
screen. Because a refused `dashboard_url` / prefix save looks identical to an
accepted one from the button's position, and those values break
Send-to-Resolve fleet-wide if the owner believes a change landed, medium
holds.

## ui-dash-admin-7 - HEALTH reads "every check answered" when a source raised - CONFIRMED (medium)

`_health_rows` (ui.py:1868-1941 at HEAD) wraps each of the four sources in
`except Exception: log.exception(...)` and adds no row, so a failing source
silently contributes zero rows; if all four fail, `admin_health.html:113-117`
renders "Nothing is open. Every check this server runs answered, and none of
them found a problem." The module's own comment (and docs/SELF_DIAGNOSIS.md /
CLAUDE.md) says an unverified check must never fold into OK, and the
invariant/protection branches already map their own NOT_CHECKED states to the
`unknown` band - the source-level failure is the one path that bypasses it.
Medium: it lies on the authoritative page only when a source raises, which is
rare but exactly the moment the page is opened.
