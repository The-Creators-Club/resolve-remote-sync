## Settings, then PACKAGES: the page's layout, 2026-09-11

Not a hunt finding: the owner read the page and said what was wrong with it.
Verbatim: "on the packages page it should be sorted into categories, so
companion > windows / mac / linux | dashboard | onboard ... Also the publish
packages UI is confusing, delete takes three lines, nothing is aligned
properly. What is the difference between published packages which aren't
current, and available from the vendor? Surely the top should just be
'currently served' and then underneath it 'available from the vendor', having
not-current packages at the top under published packages is confusing, unless
there is some reason for it."

There is a reason, and it is not a reason to put them at the top. A row in
`companion_packages` that is not current is either the bytes a rollback needs
(republishing an older build IS the rollback here, via the upgrade channel's
version-difference rule) or a build pulled from the vendor feed and staged for
a canary. Both are real, neither is the answer to "what is my fleet running",
and they were the first thing on the page.

### What changed

**`dashboard/templates/partials/admin_packages.html`** now reads in three
sections instead of one nine-column table called PUBLISHED PACKAGES:

1. `[ CURRENTLY SERVED ]` - one row per (kind, platform) that has a current
   package.
2. `[ AVAILABLE FROM THE VENDOR ]` - the feed, with its check/policy controls
   unchanged.
3. `[ OTHER VERSIONS HELD ON THIS SERVER ]` - a `<details>`, collapsed, whose
   one explanatory line says why they are kept (rollback; staged awaiting
   make-current). This is where [ MAKE CURRENT ], [ PUSH TO ONE COMPUTER ],
   the typed override and [ DELETE ] live now.

All three group by kind then platform (`companion`, `dashboard`, `onboard` x
`windows`, `macos`, `linux`), from one helper, `ui._kind_platform_groups`. A
group with no rows is NOT rendered: there is no linux companion build, and a
heading over an empty space reads as something that has gone missing.

A row is one line with four fixed column roles - version + chips, published,
size + sha, actions right-aligned - and all three tables declare the same
`colgroup` under `table-layout: fixed` (`.pkg-table` in `static/style.css`),
which is what makes a version line up with a version between sections. KIND
and PLATFORM stopped being columns repeated on every row and became the
headings. The delete warning moved into `hx-confirm` (it is unchanged text,
and it was three lines of page copy nobody read); `[ DELETE ]` is one button.

**`ui._vendor_rows`** is the answer to the owner's question, said on the row.
`release_feed.build_feed_view`'s `available` deliberately drops every record
this server already has a row for, so a version the vendor offers and this
dashboard already serves was absent from that section entirely - which is
exactly what made the two lists read as two unrelated ledgers. The vendor
section is now built by CLASSIFYING the same verified records
(`release_feed.verified_records`, so a [ PUBLISH ] button still names only
what a check really verified) rather than filtering them: `[ CURRENT HERE ]`,
`[ STAGED, NOT CURRENT ]` with the make-current action, or the two publish
buttons. `release_feed.py` itself is untouched (the `bool("0")` dirty-stamp
bug is someone else's, in parallel), and if the record cache cannot be read
the section falls back to naming `feed.available`'s versions rather than
showing nothing.

Everything else on the panel is byte-identical and in the same place: every
route, form field, `hx-target`, `hx-swap`, `.admin-packages-box` root (the
whole panel still swaps outerHTML onto itself), the recall banner and
[ ROLL THE FLEET BACK ], the arch-gap banners, [ ROLLOUT ], the out-of-date
computers table with [ UPDATE NOW ] / [ CANCEL ], the data-volume gauge, the
feed's [ CHECK NOW ] / policy select / refusals / sha conflicts / image line,
and the ship.cmd footer.

### Files

- `dashboard/templates/partials/admin_packages.html` - the rework
- `dashboard/src/ccsync_dashboard/ui.py` - `PACKAGE_KIND_ORDER`,
  `PACKAGE_PLATFORM_ORDER`, `_ordered`, `_kind_platform_groups`,
  `_vendor_rows`; `_packages_and_feed` gains `served_groups`, `held_groups`,
  `held_count`, `vendor_groups`
- `dashboard/static/style.css` - `.pkg-table` column roles, `.pkg-actions`,
  the two heading-row rules, `details.pkg-other`
- `docs/RELEASE.md`, `docs/RELEASE_PATHWAYS.md`, `docs/SERVER.md` - the four
  places that told an operator to look in a box called
  `[ PUBLISHED PACKAGES ]`

### Verification

From `dashboard` with `.venv\Scripts\python.exe -m pytest <file> -q`.

New, in `tests/test_packages.py`:

- `test_the_packages_page_is_grouped_by_kind_then_platform_in_a_fixed_order`
  - the section order, the heading order (companion before onboard, windows
  before macos, no invented linux heading), and that the current build is in
  the top section and NOT also in the drawer while the version behind it is
  only in the drawer
- `test_the_rollback_drawer_says_why_those_versions_are_kept` - collapsed,
  explains itself, one [ DELETE ] with the warning in the confirm
- `test_the_vendor_section_marks_what_this_server_already_holds` - the
  three states, and that only the version this server has never taken is
  offered for download

Updated: `tests/test_settings_hub.py` (the page's headings), and
`tests/test_mobile_admin.py` (`.stack` labels: KIND and PLATFORM are headings
now, and the class assertion is a prefix because the tables carry
`.pkg-table` as well).

Run: `test_packages.py`, `test_settings_hub.py`, `test_mobile_admin.py`,
`test_no_em_dash.py`, `test_sweep_2026_09_04_copy.py`,
`test_sweep_2026_09_04_dash_ui.py`, `test_release_feed.py`,
`test_release_channel.py`, `test_dashboard_update.py`,
`test_templates_wave3_2026_09_04.py`,
`test_hand_off_2026_09_11b_dash_mounts_ui.py` - 845 passed, 1 skipped.

### Owner decisions

- The canary line (REL-1's evidence for [ MAKE CURRENT ]) is still a sentence
  rather than a chip, and it sits in the actions cell of a held row, so that
  one row can wrap on a narrow panel. It is the only text in front of the
  click that hands a build to the whole fleet; shortening it was not worth it.
- `[ CURRENT ]` rows carry no buttons at all, on purpose: making the current
  build current again is nothing, and deleting it was already refused.
- The three [ NO CODE SIG ] / [ UNSIGNED ] / [ +dirty ] chips are unchanged
  and still shown, including the dirty one that is currently stamped on
  everything (a separate bug, being fixed in parallel).

### Owed to another territory

- none. No route, schema or API shape changed.
