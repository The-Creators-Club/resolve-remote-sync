# T1: test conversion, account and admin people pages

Builder: test converter T1, 2026-09-25, worktree branch `ui-replace`, after
C-collapse (the terminal look is the only look). Nothing committed, no
version bumped. No test deleted: every failing assertion pinned a behaviour
that still exists, so each was rewritten against the terminal markup, with
its intent and bug id kept.

## Product fix (one line)

- `templates/partials/admin_users.html`, DEVICES AWAITING APPROVAL bar: the
  meta said "none pending" while Syncthing was unreachable and the body said
  "The device list is unavailable". That is the DASH-7 shape (an unreadable
  list claimed as empty) that `test_a_syncthing_blip_does_not_hide_the_account_half`
  forbids. The bar now says "unavailable" when `admin_users.syncthing_error`
  is set. The converted test asserts "none pending" is absent, so it fails
  without the fix.

## Per file

- `tests/test_account_page.py` (24 failing -> 54 pass). The browser helper's
  htmx headers now carry `X-CC-UI: terminal` (`conftest.HX`); without it
  `app.stale_page_gate` answered every htmx post with an empty HX-Refresh,
  which was 14 of the 24. The rest: bracket copy -> the terminal heading
  (`YOUR_ACCOUNT_H1`), `<h2 class="sec">your computers` / `your wired
  computers`, key labels (`Settings, Users`, `Ask this computer why`, `Sign
  out`, `Sign out the others`, `Sign out everywhere`, `Withdraw`), the
  "this browser" tag, the `full` tag. The editor-page negative checks also
  assert the admin-only update and ask-why routes are absent. The computer
  poll assertion now pins the terminal shape (a hidden `.ev-poll` inside the
  window, `every 30s`, `hx-select-oob` onto that window's own body). Fleet
  grid: the sign-in name rides in the muted `<small>` as "J. Smith (jsmith)".
  Audit and plan changes: WHO is `<b>J. Smith</b>`, EDITOR is the plain cell
  after the `ticked` tag; the partial is identified by `id="plan-changes"`
  (its window title lives on the page, not in the partial). Plan rows: the
  toggle URL carries `view=none` (R15), and Untick is the explicit
  `mode=off` (everyday-apps-1), matched with or without `&amp;`.
- `tests/test_admin_assignments.py` (3 -> 20 pass): the `> SYNC PLANS`
  heading; the picker form is `assign-pick pickrow`; the computer select is
  now drawn before a person is chosen (plan 5.3) but disabled with only its
  placeholder option, which is what "no computer picker until a person is
  chosen" now means; the fleet-size counts are bold numbers, compared on the
  tag-stripped text.
- `tests/test_admin_delete.py` (2 -> 42 pass): the COMPUTERS window by
  `data-win` and its title, and the `remove` key inside the forget form.
- `tests/test_admin_tick_for_editor.py` (4 -> 6 pass): the TICKING FOR window
  and its `name="as"` editor select (absent for a non-admin); the sidebar
  refresh became the project tree's poll (`/partials/projects-tree?...as=`,
  sent with `HX`); the admin tick posts `view=tree&mode=on` as the tree does;
  the project page keys read `Tick for editor1` / `Tick for me`.
- `tests/test_admin_users.py` (3 -> 29 pass): the APPROVE key on the pending
  device's own row, "The account/device list is unavailable" wording, the
  create window and form for the account half, the `> USERS` heading and the
  devices window. Plus the product fix above.
- `tests/test_admin_users_local.py` (1 -> 25 pass): the LOCAL ACCOUNTS window
  by `data-win` and its title.

Final: 176 passed, 0 failed across the six files.
