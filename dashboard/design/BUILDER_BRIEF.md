# Design bench builder brief (2026-09-25) - read fully before writing anything

You are building mock pages for the dashboard REDESIGN test bench in
`E:\Projects\Editing\ccsync\dashboard\design\`. The owner approved the look
of `home.html` (open it, and read `README.md`, `cc-terminal.css`,
`cc-components.css` and `shell.js` first) and wants EVERY other page built
the same way "so I can tune it all". Owner rules from today: no `[ square
brackets ]` on controls; NO hand-written (Permanent Marker) notes; all
scrollbars styled like the website (already global in cc-components.css, do
not override); readable first.

## What a page is

A standalone `dashboard/design/<name>.html` with exactly this skeleton (copy
`home.html`'s head: fonts, `cc-terminal.css`, `cc-components.css`):

```html
<body data-page="<nav key>">
<div class="shell"><div class="page one">          <!-- or .page / .page.narrow -->
  <div id="settings-nav"></div>                    <!-- ONLY on Settings pages -->
  <div class="head">...h1 with the red > prompt, .sub line, .acts keys...</div>
  ...windows built with the existing classes...
</div></div>
<script src="shell.js"></script>
<script> ... CC.page({ page: '<nav key>', onData: render }) ... </script>
```

- `data-page` / `page` keys: home, transfers, cards, b-roll, music, youtube,
  and the Settings keys site, users, assignments, packages, jobs, audit,
  setup, health, invariants, protection, alerts, recovery, help; plus
  `account` (the personal page) and `login` (use `CC.page({bare: true})` for
  pages with no HUD such as login / offline / setup-first-run).
- `onData(mode)` is called with `'busy'` or `'calm'` (the TUNE "data"
  switch): render a realistic busy state AND the calm / empty state.
- Use the helpers: `CC.win(name, metaHtml, bodyHtml)`, `CC.meter`,
  `CC.tag`, `CC.led`, `CC.esc`, `CC.toast`. Buttons are `.key` (primary /
  default / quiet, `sm`), `data-busy="toast text"` gives a busy state for
  free, `data-dismiss=".row-selector"` removes a row.
- Components to use before inventing anything: `.win/.bar/.body`, `.tbl`
  (+ `.stack-sm` for phones), `.form/.form-row/.inp/.sel/.area/.check/.radio/
  .switch`, `.tabs`, `.steps`, `.note(.warn/.err/.ok)`, `.kv`, `.code`,
  `pre.log`, `.pager`, `.empty`, `.dialog-back/.dialog`, `.tag`, `.led`,
  `.readout`, `.prob`, `.lane`, `.tree`, `.prompt-in`, `.cols-2/.cols-3`,
  `.stack`, `h2.sec`, `.lede`, `.scroll-y`.
- If you truly need a new component, put it in `dashboard/design/css/<your
  builder id>.css` (link it after the two shared sheets) and say so in your
  report. Do NOT edit `cc-terminal.css`, `cc-components.css`, `shell.js`,
  `home.html`, `index.html`, or another builder's files.
- Long lists live in a window body with a fixed max-height and `.scroll-y`,
  never an endless page (the owner's rule for the computers table: a busy
  row must not ruin the layout; rows stay symmetrical).

## Fidelity: the REAL page's content, in the new look

For every page you own, read the real template(s) under
`dashboard/templates/` (and partials), the route that renders it in
`dashboard/src/ccsync_dashboard/ui.py`, and its view builder, and carry
EVERY section, table column, control, state and explanatory sentence the
real page has. Improve wording only where it is clearly clumsy. The mock is
the owner's picture of the finished page, so nothing real may be missing and
nothing may be invented that the product cannot do. User-visible text: no em
dashes (owner rule), plain words.

Data is INVENTED and must stay invented: editors `jsmith`, `mrivera`,
`tchen`, the admin `owen`; machines `JSMITH-STUDIO`, `JSMITH-MBP`,
`RIVERA-TOWER`, `RIVERA-LAPTOP`, `TCHEN-RIG`, `OWEN-RIG`; projects under
2026/FF5 (Elections, Civil Defence, Repro Rights), 2026/Shorts (Night
Market, Typhoon Prep), 2025/FF4 (Kinmen, CIA City, Taichung Drone Camp).
Never a real person, machine or customer name.

## Check your work

Render every page in headless Chrome at 1440 wide and at phone width
(headless has a minimum window width: put the page in a 390 px iframe inside
a wider page), look at the screenshots, and fix overflow, overlap, clipped
text and anything unreadable. Screenshots and scratch files go in your own
scratchpad, never the repo. Check both TUNE data modes. Chrome:
`"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new
--disable-gpu --hide-scrollbars --virtual-time-budget=5000
--window-size=1440,2000 --screenshot=<png> file:///<path>`.

Do not commit. Do not touch anything outside `dashboard/design/` (other
agents are editing the product in the same tree). Report: the files you
wrote, for each page what real template/route it mirrors, any section of
the real page you could not represent and why, and any new component you
had to add.

## Round 2 rules (owner feedback, 2026-09-25) - these override anything above

- NOTHING MAY SHIFT. The page's scrollbar gutter is now always reserved
  (cc-terminal.css), and every Settings page is one width. On top of that:
  a control that changes its label or state must keep its size (reserve the
  width, overlay the busy text, or use a fixed-width cell), a list that
  empties must keep its window's height where the owner would notice, and a
  switch between tabs or modes must not reflow the rest of the page. Check it
  by clicking through in headless Chrome and comparing screenshots.
- Tags are now a small square plus a lowercase word (no boxes). Do not
  re-add borders or boxes around state words in your own css; delete any
  such override you added.
- Every `.win` folds from its title bar automatically (shell.js). Do not
  build your own collapse for a whole window; nested folds inside a window
  are fine.
- TOOLTIPS: give every control, abbreviation, state word, number or column
  header that a non-technical admin might not understand a `title="..."`
  (shell.js renders it as the bench tooltip). One or two plain sentences:
  what it is, what happens if you press it. Do not tooltip the obvious.
- Prefer a picker, a dropdown or a short wizard over showing every option or
  every old item at once. The owner finds long lists of alternatives
  "visually confusing".
