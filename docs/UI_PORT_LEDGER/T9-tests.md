# T9: test conversion after the collapse (six dashboard files)

Builder: test converter T9, 2026-09-25, worktree branch `ui-replace`. Nothing
committed, no version bumped. Each pin now asserts the same behaviour against
the terminal markup, sheets and copy. It keeps its intent and its bug id.

## Per file

- `tests/test_installer_page.py` (OPS-20), converted.
  - The platform split now uses the per-platform windows
    (`id="win-installer-windows"` / `-macos`) instead of the bracketed
    `[ WINDOWS ]` / `[ MACOS ]` headings.
  - The Mac test also checks that the Mac package really is drawn there, so
    the missing warning cannot pass just because the window is empty.
- `tests/test_invariants.py` (the three-state page), converted.
  - The verdicts are read from `#invariant-table` as tags (`broken`, `ok`,
    `not checked`) and not from bracketed chips.
  - The heading is `INVARIANTS</span></h1>`.
- `tests/test_jobs_cancel.py`, converted.
  - The cancel key is pinned by its `hx-post` and by its label.
  - "no pinning here" is pinned as a tag, and so is the absence of the
    "pin: this server" tag.
- `tests/test_jobs_retry.py` (DDIAG-11), converted.
  - Constants were added for the keys (show finished, hide finished, try
    again) and for the window title with its hidden underscores.
  - The "not retryable" test used to pass vacuously on a missing bracket. It
    now also asserts that there is no retry `hx-post`.
  - The open list asserts that no finished window is drawn.
  - The "last held by" cell reads `jsmith/<b>EDIT-PC</b>`.
- `tests/test_live_notices_2026_09_21.py`, converted.
  - The red-on-red dismiss rule now covers both terminal notice partials
    (`home_problems`, `health_notices`), rendered with an error notice.
  - The red paint is only the severity tag. The `.prob` row has no
    background. The dismiss is a `.key.quiet`, which is transparent, uses
    `--text-2` and never `--red`.
  - "Still reads as clickable" is now the quiet key's pointer glyph plus
    its hover colour.
- `tests/test_mobile_admin.py` (M3), converted to the terminal vocabulary.
  - `table.tbl.stack-sm`, lower-case `data-label`, the jobs why-row,
    `.scroll-x` on the same line or the line above, `.mx-wrap` for the
    matrix, `.vd` rows for invariants and protection, `.key` under
    `(pointer: coarse)`, `cc/phone.css`.
  - The collector partial is `health_collector.html`.
  - The box-drawing check now refuses a run of 4 or more glyphs (literal or
    entity) or a Jinja multiplication. The window bar's 3-glyph
    aria-hidden corner ornament is allowed.
  - The poll count went from 17 to 6: 11 were the classic sidebar poll, and
    there is no sidebar now (D17).
  - The C-5 allowed long confirm follows the port's truthful delete copy
    ("trash on this server for 30 days").

## Deleted

- `test_m3_wrote_only_in_its_own_section_of_mobile_css`: it pinned the
  two-owner section markers of `static/mobile.css`, which is deleted. The
  terminal phone rules are one sheet, `cc/phone.css`.

## Product fixes

- `templates/partials/recovery.html` (the resolve-undo table) and
  `templates/partials/health_collector.html` (both tables): each is now
  wrapped in `<div class="scroll-x">`, M3's rule for every admin table.
- `static/cc/phone.css`, `(pointer: coarse)`: added
  `label.upm { min-height: var(--tap); align-items: center; }`.
  - The matrix's upload-only label is a control, and under the terminal
    look it had lost M3's thumb-sized hit box. The legend's `span.upm` does
    not grow.

## Seen, not mine

- `tests/test_every_template_renders.py` fails on `/help` because another
  converter's ledger title contains the words "classic look" (T12). That
  test is correct. The fix is to retitle that ledger.
