# dashboard/design - the redesign's test bench

Started 2026-09-25. The owner asked for "an entire redesign of the dash UI to
make it look more flash and modern, while maintaining the CLI aesthetic",
without the `[ xxx ]` buttons, starting with the home page and the menu bar.

**Second pass, same day.** The first pass ("CC Material": rounded tonal
cards, pill buttons) was judged "a bit AI UI slop ... I want something that
looks nice and unique, but is also readable. You can look at my website for
inspiration" (`X:\sites\TheCreatorsClub\public\productions`,
thecreatorsclub.co/productions). This pass carries that site's language.

Nothing here is served by the dashboard or read by a test. It is a place to
settle the look before a single template changes.

| File | What it is |
|---|---|
| `cc-terminal.css` | The design system, as tokens then components: red-framed square windows with a box-drawing title bar and a dithered DOS shadow, the HUD (the site's CC swoosh, `>word` nav, square LEDs, a Taipei clock), keycap buttons, solid severity tags and framed state tags, readout windows (Orbitron numbers over a text meter), the problems log, computer rows with one text meter per sync lane, transfers, tables, the projects tree drawn in box-drawing characters, a prompt-style search, a toast, and the phone layout (a bottom dock). |
| `home.html` | The home page and the HUD from invented data (the demo seed's `jsmith` / `mrivera` / `tchen`, never the real fleet), plus the TUNE panel. |

## Every page (2026-09-25)

`index.html` is the launcher (the HUD's CC mark goes back to it from any
page). `shell.js` draws the HUD, the Settings strip, the phone dock and TUNE
for every page, and TUNE is ONE setting for the whole bench (it follows
across open tabs). `cc-components.css` holds what every page is built from
(forms, tabs, tables, callouts, dialogs, the site-style scrollbars);
`css/<group>.css` holds each builder's page-specific pieces.

Pages: home, project, transfers, account (NEW: the personal page, editor
and admin; controls the product does not have yet are outlined "new"),
project-setup, installer; cards, broll, music, youtube; site, users,
sync-plans, packages, jobs, history, setup; health (the Settings landing),
invariants, protection, alerts; recovery, help; login, offline. Several pages
carry a dashed "bench" strip (or `?as=`, `?v=`, `?state=`) to switch between
states the real page has; those strips are not product UI.

Product defects the page builders found while mirroring the real templates
(fix them with the redesign): recovery.py's Resolve plan says "the
dashboard has no button for this yet" beside the undo button; a setup step
reads "(optional)" twice; fix texts in protection.py / invariants.py name
`[ BRACKETED ]` buttons; the legal documents' titles carry em dashes.

## Using it

Open `index.html` in a browser. It loads Orbitron, JetBrains Mono and
Space Mono from Google Fonts and falls back to Consolas without
them.

**TUNE** (the key bottom right, or press `T`): the live/selected colour
(cyan like the site, or green, amber, white, violet), the display face, grain, scanlines, glow, the DOS shadow, text
size, density, and busy vs calm data (for the empty states). Settings
persist in the browser; **copy settings** puts them on the clipboard with a
link whose `#s=` fragment reproduces the exact state.

## The rules this look keeps

From the site: square red 1px frames, `+-| name |=` title bars with a dashed
rule, pure white text on warm near-black (`#070403`), cyan for what is live
or selected, red for frames and for what is wrong, Orbitron for display,
JetBrains Mono for reading (the hand-written note was tried and dropped by
the owner), the crosshair cursor, grain, a CRT hint.

For readability, which the site can afford to trade away and a dashboard
cannot:
- body text is plain white mono at 14px on the darkest surface, and no
  effect (grain, scanlines, glow) ever sits over text;
- Orbitron is only for numbers and page titles, never a sentence;
- state is a word plus colour plus a shape (LED, tag, meter), never colour
  alone;
- meters are text characters (`█░`), so they read at any size and copy as
  what they show.

No `[ square brackets ]` on controls: buttons are keycaps (a square frame
with a deeper lower edge that sinks when pressed); the primary one is red
and carries a key hint; quiet actions are text with a red `▸`.

## Next steps (not done)

1. Settle the tokens here with the owner.
2. Carry the HUD into `templates/partials/topbar.html` (the b-roll, music and
   YouTube SPAs fetch it too, so they change with it).
3. Carry the home page, then page by page. The no-em-dash scan and the
   mobile sweep (`tools/mobile_sweep.js`) apply as they do today.
