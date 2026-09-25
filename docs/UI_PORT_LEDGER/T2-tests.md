# T2: test conversion, six dashboard files

Builder: test converter T2, 2026-09-25, worktree branch `ui-replace`, after
C-collapse made the terminal markup the only one. Nothing committed, no
version bumped.

## Per file

| File | Converted | Deleted | Product fix |
|---|---|---|---|
| `tests/test_ai_providers.py` | `test_the_settings_page_carries_the_section_and_the_tos_note`: "AI PROVIDERS" heading -> the `tab-ai` tab ("ai providers") + the `your_ai_providers` window; also pins `ai-cli-tos`, the element the ToS note is hung on | none | none |
| `tests/test_alerts.py` | `test_the_page_groups_the_rows_that_shared_a_message` (ui-dash-admin-12): "one message, <b>2</b> findings" (the count is bold now; still no "(s)") | none | none |
| `tests/test_android.py` | check verdicts `[ SERVING ]` / `[ EMPTY ]` -> the `serving` / `empty` tags (empty also asserts no serving tag); settings page `[ ANDROID ]` -> `tab-android` + exactly one `data-win="android"` | none | none |
| `tests/test_api.py` | `[ MISSING FILES ]` -> the Missing files key; `[ WIRED ]` (CR-179) -> the `wired` tag, plus the report-only row carries no missing key (count == 1, the test's stated intent); fleet refusals: sentence-case banner on `/` (ui-dash-main-10), and the collector / pending share changes / incomplete checks moved to where the window lives now (`/admin/health` tab + `/partials/health-collector`); the editor test was VACUOUS (its negatives were upper-case classic strings) and now asserts the page drew, no refusal banner, and 403 on both Health surfaces; DASH-5 `[ NAS INVENTORY NOT UPDATED ]` -> the `server count not updated` tag | none | none |
| `tests/test_auth.py` | `[ SIGN IN ]` -> the login form + its Sign in key | none | none |
| `tests/test_broll_ingest_report.py` | chips -> lower-case tags (`indexing b-roll: 12/40`, `vram` with the reason as its tip, `132 need proxies`); the two "chip is gone" tests were VACUOUS (upper-case negatives) and now assert the grid drew and the lower-case tag is absent | none | YES, see below |

## Product fix

`templates/partials/fleet_grid.html`: the terminal port drew the
`indexing b-roll: n/m` and `indexing music: n/m` tags with NO tooltip. The
classic chip's title carried what an admin needs before they go and ask
(batch id, clip or track, state/gate, model tier, percent of the clip,
failures, when reported), and `test_an_indexing_machine_is_stored_and_chipped`
pins it. Restored both tooltips verbatim from the classic chips, and the
tone goes to warn when the ingest carries a warning, as classic's amber did.

## Noticed, not mine

- `tests/test_every_template_renders.py` fails on `/help`: another
  converter's ledger title ("... after the ... look was retired", T12)
  puts the phrase that test forbids onto the help index. A ledger title,
  not a product defect.
- `partials/android_settings.html` still says "fingerprint(s)" in the check
  answer (the same "(s)" the review removed elsewhere).
- The fleet grid's job tag dropped classic's "lease until" from its tooltip.

## Final numbers

The six files: 307 passed, 0 failed.
