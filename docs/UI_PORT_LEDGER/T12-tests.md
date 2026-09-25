# T12: test conversion after the classic look was retired

Converter T12, 2026-09-25, worktree branch `ui-replace`. No commit, no version bump.
Every change below keeps the test's intent and bug id and asserts the same
behaviour against the terminal markup. No test was deleted, and none was loosened.

| File | Before | After | What changed |
|---|---|---|---|
| `dashboard/tests/test_pwa.py` | 2 failed | 27 passed | `/offline`: `[ OFFLINE ]` / `[ RETRY ]` became the window title `offline` and the `Try again` key. I also added a pin on the empty-href retry (ui-dash-static-6). The no-identity/no-CSRF assertions are unchanged. |
| `dashboard/tests/test_recovery.py` | 1 failed | 32 passed | `WHAT WENT WRONG` became the wizard window (`data-win="wizard"`, the `what went wrong` nav), with `?problem=project` marked `aria-current` and its "what to do" plan drawn. Added `import re`. |
| `dashboard/tests/test_release_channel.py` | 2 failed | 49 passed | REL-3: `RECALLED BUILD` became the row's `recalled build` err tag, and the test now checks that the vendor's reason is its tooltip. REL-16: the arch-gap note text is now matched in sentence case. |
| `dashboard/tests/test_report_endpoint.py` | 5 failed | 21 passed | The bracket chips became `<span class="w">` row tags: relayed, orphans, express upload failed (CR-179), update failed x8, reverted from. On a direct-only computer the check is now "no relayed tag" plus `direct: 2` in the details. UX-10's noun agreement is now checked as "1 computer is being refused:", plus the row's "being refused" tag. DASH-2 is "1 computer still on a retired signing key." |
| `dashboard/tests/test_report_tokens.py` | 1 failed | 11 passed | `REPORT TOKENS` was a heading inside the classic panel. The panel is now just the window body, so the test checks the swap target, the mint form and the empty-state row. The Users page's `report tokens` window bar and its lazy `hx-get` of the panel are checked too. |
| `dashboard/tests/test_report_model_pin.py` | 1 failed | passes | **Not a UI failure.** The worktree branched at d920ff7, and main's 77916b8 had already fixed this pin (adding `lane_b_via`). I applied that commit's two hunks as they are (this test plus the `lane_b_via` row in `docs/legal/TELEMETRY.md`), so the merge sees the same change on both sides. |

No product bugs found. Final: 155 passed, 0 failed across the six files.
