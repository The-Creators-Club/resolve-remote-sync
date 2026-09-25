# F-a11y verification (2026-09-25)

Verifier pass over F-a11y (every `a11y-copy-*` finding). Method: the seeded
dev server (`tools/mobile_sweep_seed.py`, every terminal group on through
`tools/ui_variant.py set`), headless Chrome over CDP at 1440 and 390 (touch
emulation, coarse pointer), `Accessibility.getFullAXTree` on 13 dashboard
pages and the music SPA. b-roll and ytdl are not mounted on the seed server.
Their `cc_spa.js` is byte-identical to music's, so the music run stands for
all three.

| Finding | Verdict | Evidence |
|---|---|---|
| a11y-copy-1 | CLOSED | No button, link, radio, checkbox, heading or tab name on 13 pages or on /music/ contains a glyph (▸ ◉ ○ □ ■ ⇡ ⇣, a leading `>`, `//` or `##`). The radio on /admin/alerts is named "none". Transfers uses `dirmark`: the arrow is aria-hidden and the word is in `.vh`. |
| a11y-copy-2 | CLOSED | /admin/users, "disable jsmith": the AX dialog is named "are you sure" and its description is "Stop jsmith signing in? ...". The #site-ask dialog is described by #site-ask-q. SPA `ccSpa.confirm`: name "Are you sure?", description is the question. |
| a11y-copy-3 | CLOSED for screen readers and keyboard. The iPhone tap path is still open. | /music/: after a mouse pass the title moves to aria-description, which stays. Focus shows `.cc-spa-tip`, blur hides it. There is still no SPA `.tip-btn`, so iPhone Safari (no focus on tap) never shows a control's tip. |
| a11y-copy-4 | CLOSED, after a verifier fix | 390 coarse: "?" buttons on home 34, settings 34, users 37, alerts 17, account 11, packages 12. The review measured 0 on each. Tapping one opens #chip-sheet with the explanation. At 1440, focusing "Send a test" shows the tip. **Bug found and fixed:** when Tab moved focus below the fold, the page scrolled after focusin, and `scroll -> hideTip` cleared the tip. Tabbing through /admin/alerts showed 7 tips on 10 stops, and the 3 misses were all scrolls. cc.js now tracks `focusTip`, and a scroll moves a focus tip with its control instead of hiding it. After the fix, 9 tips on 10 stops (the miss is a fold, which has no tip). |
| a11y-copy-5 | CLOSED | Heading names: "TRANSFERS"; Packages "currently served", "this dashboard"; /help "1. The problem it solves", "2.1 The NAS ...". No `>`, `##` or underscores. |
| a11y-copy-6 | CLOSED, with one extra fix | Folds are named "fold currently served", "fold your studio" and so on. Keys read "DELETE JSMITH" and "ERASE HISTORY OF JSMITH". Home links read "TAKE ME THERE : <subject>". **Fixed:** the per-person ssh "add" key was repeated 4 times with no subject. It now has `<span class="vh"> a key for {{ u.username }}</span>` (cc/partials/admin_users.html). Left as is: "UPDATE NOW" x2 on Packages, and Health rows that share a title (each sits in its own row). |
| a11y-copy-7 | CLOSED | 390, touch: .tree-count, h3.sec, label.field > span, span.sha, tr.grp-row td and .sp-caps are all 12px. A scan for text under 12px is empty on 10 pages. |
| a11y-copy-8 | CLOSED | Rendered confirms read "...and \"Resume\" puts it back." and "\"Disable\" only stops logins.". Packages reads Press "Check now" there, and names the From the vendor window. The remaining all-caps words (EVERY) are emphasis, not key labels. |
| a11y-copy-9 | CLOSED | /admin/settings renders "Usually the same server". fleet_grid now says "this computer". |
| a11y-copy-10 | CLOSED | Seeded /admin/alerts/preview reads "has never been able to check for new CC Sync builds" and "is on 0.9.53 (since when is not known)". No "since never" anywhere. |
| a11y-copy-11 | CLOSED, with one extra fix | The `2026/Show/Episode/Interviews/...` placeholder is in. **Fixed:** the move form in the same template still said `e.g. Interviewees/Pangolin`, from the studio's own "Animals - Pangolins and Bears" project. It now says `e.g. Interviews/Guest`, and `test_no_studio_show_name_is_an_example_path` also scans for "Pangolin". |

Tests after the fixes: test_cc_a11y_copy, test_admin_users_local, test_ui_chrome,
test_cc_settings_people, test_cc_everyday and test_cc_css_facts: 239 passed. test_cc_home,
test_fleet_scope, test_hardening, test_mobile_fleet, test_sweep_2026_09_04_copy,
test_templates_wave3_2026_09_04 and test_ui_variant_mechanism: 853 passed, 12 skipped.

Outside this finding set, for whoever retires the classic look: the classic half of
the three SPA `style.css` files still has `.menu-btn::before/after "[" "]"` (a
bracket control) and `.nav-link.nav-sep::before "\2f\2f"` with no alt text.
They do not render under html.cc.
