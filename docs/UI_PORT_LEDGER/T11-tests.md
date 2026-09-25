# T11: six dashboard test files onto the terminal markup

Converter T11, 2026-09-25, worktree branch `ui-replace`, after C-collapse
made the terminal look the only one. Nothing committed, no version bumped.
Every conversion keeps the test's intent and bug id; no test was deleted.

## tests/test_oidc.py (1 converted)

- `test_local_password_login_is_break_glass_for_admins_only`: the SSO key is
  pinned by its words ("Sign in with SSO") and its href
  (`oidc.LOGIN_PATH?next=`), instead of the bracket label.

## tests/test_packages.py (10 converted)

- C-4: pins the feed-aware `instead_words` (logic-admin-6) and the unsigned
  hx-confirm that reads it, as the terminal partial writes them once.
- C-5: pins the terminal delete confirm, which says what is true (the trash
  for 30 days, `api._trash_package_file`) and what losing the bytes costs.
- Fleet grid: `out of date` / `version unknown` tags (with the running vs
  current tip), plus "unknown is not out of date" asserted on the page too.
- REL-6 rollout window: scoped to `data-win="rollout"`, counts in their
  table cells. REL-3: `refusing 0.2.0` tag and the `update now` key.
- Layout (owner 2026-09-11): sections are the `data-win` windows, kind and
  platform headings are `grp-row` / `grp-row plat`, held section sliced up
  to the out-of-date window, the drawer is a closed `<details>`, one
  `delete` key, vendor tags `current here` / `staged, not current` and the
  `publish` / `publish and make current` / `make current` counts.

## tests/test_presence.py (4 converted)

- `test_pages_render`: TRANSFERS heading + the live window; the project page
  is checked for its tick key (`toggle?view=project&mode=on`) and the media
  presence window. The classic sidebar toggle (`view=sidebar`) no longer
  exists; the round trip is now the project page's own tick (view=project,
  with the HX header pair), asserting the answer offers the untick, carries
  HX-Trigger, and the selection landed.
- Backlog / history / preparing: `#xf-queued` with the queue row's data-key,
  the file under `#xf-history`, and the `getting ready` tag.

## tests/test_project_root.py (2 converted)

- Unmatched projects: the project roots window moved from home to each
  project page (D7), so the test reads `/project/<slug>` and checks the
  unmatched row plus the admin's mapping form.
- Fixed root on home: the terminal wording "matched by itself, then kept",
  plus a new check that home carries no root-changing form.

## tests/test_project_setup.py (11 converted)

- Headings (`pick the folder...`, `or create...`, `already set up`, `done`),
  the `project` and `same name` tags, the `Use Projects/...` key, "projects
  cannot nest". The "you are in" bar is `HERE = "You are in <b>Projects/"`;
  the two NEGATIVE checks use the same constant so they cannot pass
  vacuously on the new markup.

## tests/test_protection.py (1 converted)

- The heading, the `#protection-table`, and each state's per-line tag by its
  own title (the page's "cannot verify is not protected" note also carries
  a tag, so a bare word would pass vacuously).

## Product fix

- `templates/partials/project_setup_panel.html`, "already set up": told an
  admin to change the mapping "in the project roots box on the sync status
  page", linking `/`. Since D7 that window is on each project page; the link
  now goes to `/project/<mapping slug>`. Pinned in
  `test_page_shows_mapping_when_already_set`.

## Seen, not mine

- `test_every_template_renders.py` fails on `/help` because a ledger title
  under `docs/UI_PORT_LEDGER/` (T12's) contains the words that test bans.
- `partials/person_fix_root.html` still says "auto-matched, fixed" where the
  home twin says "matched by itself, then kept" (same fact, two wordings).

Final: 205 passed, 0 failed across the six files.
