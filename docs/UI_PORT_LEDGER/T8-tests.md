# T8: six dashboard suites moved onto the terminal markup

Builder: test converter T8, 2026-09-25, worktree branch `ui-replace`.
Nothing committed, no version bumped. Every test keeps its intent and its bug
id; none was deleted.

## Files

| File | Converted | Deleted | Product fix |
|---|---|---|---|
| `tests/test_home_layout.py` | all 11 (window ids `win-computers` / `win-transfers` / `win-queue`, the `fix-root` section, `/partials/home-queue` with `conftest.HX`, the untick with `mode=off`) | none | yes, the 35vh window (below) |
| `tests/test_help_page.py` | 4 (h1 HELP, `.snav` with `aria-current`, the documents window and its one `aria-current`, the glossary surfaces now `fleet.html` and `partials/projects_tree.html`) | none | yes, the tree's upload-only tag (below) |
| `tests/test_health_page.py` | 6 (the not-checked row tag, the notice row with its `#server-notices` link, the take-me-there key with no brackets, "Not checked is not OK.", the `running` window, "vendor: not checked") | none | none |
| `tests/test_hardening.py` | 1 (the stopped-folder note: `sync folder stopped` tag plus the reason and "stale") | none | none |
| `tests/test_fleet_halt.py` | 8 (sentence-case banners in `.grid-banners`, lowercase row tags, the Users panel's `stop all syncing` / `start syncing again` keys and `previous stops`; the every-page banner is now `/partials/halt-line` in `shell.html`) | none | none |
| `tests/test_hand_off_2026_09_11b_dash_mounts_ui.py` | 4 (dash-api-4 on `/partials/home-queue?machine=` and the home queue body's own `machine=`; regression-11's `sidecar failed` tag on the computer's why line) | none | none |

## Product fixes

- **The live-transfers window lost its 35vh height** (owner's number,
  2026-08-18; MOBILE_PLAN.md said it "keeps its height"). The terminal home
  drew an unbounded list that pushed the sync queue down and shifted the page
  on every 2 s poll, against "nothing shifts". `fleet.html`: the transfers
  `.body` is `live-transfers-window` (the scroller) and the poll moved to an
  inner `live-transfers-poll` wrapper, so a reader mid-list keeps their place.
  `cc/home.css`: `.home-page .live-transfers-window { height: 35vh; overflow:
  auto; }`, `height` not `max-height`.
- **UX-3: the projects tree's upload-only tag no longer linked to the
  glossary** (the old rail's chip did; the queue and project page still do).
  `partials/projects_tree.html`: the tag is an `<a href="{{ term_href('Upload
  only') }}">`, outside the row's label so it never toggles the tick.

## Noticed, not mine

- `test_every_template_renders.py` fails on `/help` because the page lists
  every doc under `docs/`, and another converter's ledger title
  (`T12-tests.md`) contains the retired look's name. The ledger titles need
  rewording, or that test needs to exclude the help index.
- `ui.py:452`: the fleet grid's skipped-exists tooltip still says
  "{n} file(s)". It is a tooltip, not body text.
