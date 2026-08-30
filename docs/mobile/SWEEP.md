# SWEEP.md -- the mobile sweep: what it measures and how to run it

MOBILE_PLAN.md work package M0, 2026-08-30. Two tools:

| tool | what it is |
|---|---|
| `tools/mobile_sweep_seed.py` | a REAL dashboard on a throwaway data dir, filled with enough rows that every page has its hard case on it |
| `tools/mobile_sweep.js` | headless Chrome over CDP: signs in, visits every page at every width, writes a PNG per page and measures three things |

Neither needs npm, a NAS, Syncthing, or anything on the tailnet. Node 24 and
Chrome are the whole toolchain, and node 24 has `fetch` and `WebSocket` built
in (the same rule MulticamPipeline's `tests/test_looks.js` follows).

## Running it

Two terminals, two lines:

```
E:\Projects\resolve-remote-sync\dashboard\.venv\Scripts\python.exe tools/mobile_sweep_seed.py --port 8499
node tools/mobile_sweep.js --url http://127.0.0.1:8499 --user owen --password <the one it printed>
```

The seed tool prints the URL, the admin username and a fresh random password,
and stays up until Ctrl+C. Its data dir is a temp dir that is removed on exit
unless `--data DIR` names one to keep.

`mobile_sweep.js` flags:

| flag | default | means |
|---|---|---|
| `--url` | `http://127.0.0.1:8499` | the dashboard to sweep |
| `--user` / `--password` | `owen` / (required) | the account to sign in as; it must be an admin or half the page list 403s |
| `--out` | `docs/mobile` | PNGs go to `<out>/<width>/<page>.png` |
| `--json` | `<out>/report.json` | the same findings as JSON, for diffing two runs |
| `--widths` | `390,768` | 390 is 844 tall at DPR 3, 768 is 1024 tall at DPR 2 |
| `--resolve-project` | `FF5 Elections E2` | what `/project-setup?resolve_project=` is given |
| `--chrome` | `C:/Program Files/Google/Chrome/Application/chrome.exe` | |
| `--debug-port` | `9358` | the CDP port Chrome is started on |

It exits **non-zero if anything FAILed**, which is what makes it usable as a
gate. The `/project/<slug>` entry is not hard-coded: the sweep reads the first
`a[href^="/project/"]` off the home page, so it works against a real
deployment as well as against the seed.

## The page list

Every page route except `/setup`, `/download*`, `/admin/alerts/preview` and
`/admin/site*` (MOBILE_PLAN.md §M0). Sixteen pages:

`login`, `home` (`/`), `transfers`, `project` (`/project/<slug>`),
`project-setup`, `installer`, `admin-users`, `admin-assignments`,
`admin-jobs`, `admin-packages`, `admin-settings`, `admin-audit`,
`admin-alerts`, `admin-invariants`, `admin-protection`, `admin-recovery`.

`login` is visited with the browser's cookies CLEARED, because a signed-in
browser is redirected off `/login` and the login box would never be measured.
Every other page is visited with the session cookie the sweep minted by
posting `/login` itself.

## What FAIL means

**FAIL, the page scrolls sideways** -- `documentElement.scrollWidth >
window.innerWidth`. A phone page that pans left and right is the failure this
whole round exists to remove (§2 goal 1).

**FAIL, content scrolls sideways** -- some element that is NOT a `.scroll-x`
wrapper (and is not inside one) has `overflow-x: auto|scroll` and a
`scrollWidth` bigger than its `clientWidth`. This is the check that actually
fires on this codebase, and the reason it exists is worth writing down:
`style.css:375` is `.main { overflow-x: auto }`, so the content column
absorbs the overflow and the documentElement measurement above stays clean
while the fleet grid is being dragged left and right under a thumb. §3.2 says
horizontal scroll is allowed inside a `.scroll-x` wrapper and nowhere else,
so a scrollable element that is not one is precisely the failure that
vocabulary exists to fix. Form controls are exempt: a text input longer than
its box scrolls by definition.

**FAIL, redirected to /login** -- not a layout finding at all. Without it, a
session that did not stick would sweep sixteen copies of the login box and
report every one of them clean.

## What WARN means

**WARN, tap target** -- the smallest VISIBLE element among `button, a.chip,
.btn, input, select`, measured on the smaller of its two axes, is under 44 px
(the smaller of Apple's 44 pt and Material's 48 dp). Reported with a short
selector -- tag, id or first two classes, and its parent -- which is enough to
find the template. Visible means it has a box and is not `display:none`,
`visibility:hidden` or fully transparent.

**WARN, font size** -- the smallest computed `font-size` on an element that is
actually rendering a non-empty text node, under 12 px. Deliberately not "the
smallest rule in the stylesheet": an 8 px class nothing uses is not a phone
problem.

A WARN does not fail the run. It is a fix-up task for whichever package owns
the file (§5, round 2).

## The htmx wait

Several partials paint on `hx-trigger="load"`, so a measurement taken at load
time measures the skeleton. The sweep waits for the first `htmx:afterSettle`
to bubble to `document.body`, plus 250 ms, and gives up after 1500 ms for the
pages with no htmx on them. The screenshot is captured BEFORE the measurement
is read, because `Page.captureScreenshot` is what forces the renderer to
commit a frame.

## The baseline

`docs/mobile/baseline/` is the "before": the sweep run against `mobile-m0`,
which carries no mobile changes at all, so every finding in it is what the
dashboard does today. `report.json` there has both widths; only the 390-wide
PNGs are committed (the 768 ones are regenerated on demand and would double
the repo's image weight for a width nobody is designing to first).

Round 2 (§5) re-runs the sweep against merged `mobile` and hands every
remaining FAIL and WARN back to the package that owns the file. The round
ends when the sweep is clean at both widths.

## What the seed cannot fake

`tools/mobile_sweep_seed.py` uses `db.py`'s and `local_users.py`'s own
writers, never an INSERT of its own, so a page renders what a real report
would produce. Four things follow from that and are listed at the foot of the
tool itself: `/admin/users`, `/admin/recovery` and `/admin/protection` show
their no-NAS states (real, and the narrower layout); jobs are plain (the v41
schema has no "forced" or "targeted" column yet); and the fleet halt is left
off so a fleet-wide banner does not sit on top of all sixteen screenshots.
