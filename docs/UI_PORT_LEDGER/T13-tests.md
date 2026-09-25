# T13: test conversion after the collapse (2026-09-25)

Converter T13, worktree branch `ui-replace`. Six dashboard test files that
pinned classic markup, rewritten to state the same behaviour against the
terminal markup. Nothing deleted, no product code changed, nothing committed.

| File | Result | Tests |
|---|---|---|
| `tests/test_selection_api.py` | converted `test_queue_ui_and_toggle` | 9 passed |
| `tests/test_sessions.py` | converted 2 (revoke panel, UX-22 own-row label) | 34 passed |
| `tests/test_settings_hub.py` | converted strip/drawer/packages/installer pins | 33 passed |
| `tests/test_setup_routes.py` | converted 2 (indexer tier radios, tray logo field) | 38 passed |
| `tests/test_site.py` | converted the topbar brand test | 26 passed |
| `tests/test_site_manifest_consumers.py` | converted the nas_kind select test | 5 passed |

145 passed across the six.

## What changed per file

- **test_selection_api**: the queue window is `#win-queue` ("sync queue"
  title), its body says "For <b>jsmith</b>"; the tick answers
  `?view=home-queue` with the project and its `Untick` key (the classic
  no-view answer is now an empty 200 + `cc-plan-changed`, so the test names
  the view the page sends). Posts carry `conftest.HX`. Project page asserts
  lower-case "selected by".
- **test_sessions**: `[ REVOKE ALL ]` / `[ SIGN ME OUT EVERYWHERE ]` became
  the `<span class="t">` key words; UX-22 is pinned as exactly one
  "sign me out everywhere" (the (you) row) and one "revoke all". The C-9
  confirm copy pins are unchanged.
- **test_settings_hub**: the strip is found by the whole-token class `snav`
  (was `settings-nav`); entries are `<a href>word</a>`, the current one with
  `aria-current="page"`, counted inside the strip only (the HUD also marks
  help). The drawer checks are the HUD row and the "more" sheet.
  One behavioural difference, taken from the product rather than the test:
  on `/transfers` the HUD lights **transfers**, not settings
  (`hud_in_settings` excludes it on purpose, it is its own HUD entry); the
  test pins that. Packages panels are found by window id
  (`win-currently_served`, `win-from_the_vendor`, `win-other_versions_held`).
  Installer chooser: h1 "INSTALLER", `win-installer-windows/-macos`, the
  detected card is `pick-plat here`; the empty state is "Nothing published
  for this platform yet." and is pinned as not a `note err`.
  `has_strip` now matches the real strip, so the "no strip on /installer" and
  "the poll cannot eat the strip" tests are no longer vacuous.
- **test_setup_routes**: the tier help is inside the `<label>` wrapping each
  radio (the classic `aria-describedby` ids are gone; the text is read with
  the choice). The facts per option are checked inside that option's label.
  Tray logo: `<label for="f-brand_logo">Tray logo`, the hint on the box via
  `title` + `aria-describedby="h-brand_logo"`.
- **test_site**: `/partials/topbar` signed out answers the sign-in page
  (`<h1 class="brand">CC</h1>`), which is what the old assertion was really
  reading; the test now also signs in and pins the HUD's
  `<span class="hud-name">CC</span>` and the product fallback `CC Sync`
  (and that no customer name leaks into the fallback).
- **test_site_manifest_consumers**: the `<select name="nas_kind">` now has a
  class and id; the pin is the select plus its options (truenas offered,
  qnap not).

## Product bugs found

None.
