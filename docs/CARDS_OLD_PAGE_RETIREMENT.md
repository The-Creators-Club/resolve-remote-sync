# Retiring the old Timeline Cards page

Written 2026-11-11. **A plan, not yet done.** Nothing in this document has
been built or deployed; the owner asked for it on 2026-11-11 ("merge the
standalone editor branch and get rid of the old, it's superseded now") and
it is written down first because it changes what every editor opens.

This is phase 5 of the plan that already exists
(`Resolve/MulticamPipeline/editor/docs/NAS-CUTOVER.md` in the Editing repo,
and "The flip, later" in [`CARDS_EDITOR.md`](CARDS_EDITOR.md)), plus the
step after it that nobody had written: taking the old page's code out.

## Where things stand

| | State on 2026-11-11 |
|---|---|
| The new editor | Live at `/cards/edit` (dashboard 0.7.79, `DASH_CARDS_EDITOR=1`, Node provisioned). Cards commit `3f2344a` on `main`. |
| The old page | Live at `/cards/p/<slug>/`, from the same Cards commit. |
| The branches | `standalone-editor` and the 2026-11-11 deploy branch are merged into `main` (`728a155`). `main` is once again a superset of what is deployed. |
| The owner | Works in the new editor. Controller requests made on 2026-11-11 were first built on the old page by mistake and then rebuilt in the new one. |

## What "the old" is, and what is NOT going

Two things share the name and only one of them is superseded.

**Going: the old PAGE.** `multicam_pipeline/cards/page/` (21 JavaScript
slices, `cards.html`, `cards.css`, `sw.js`), the HTTP handler that serves it
(`cards/handler.py`, about 70 routes), and on the dashboard the WSGI mount
(`cards.py`, `cards_wsgi.py`), the engine pool (`cards_pool.py`) and the
page's three Claude features (`cards_ai.py`).

**Staying: the old Python ENGINE as a library.** The new editor runs it.
Its Python bridges import `multicam_pipeline.cards` for the transcript
index, the paragraph English, the conform plan and the timeline read
(`editor/features/*/bridge.py`), and its tests pin the old cut-list reader's
behaviour. The fleet's pinned media jobs run on an engine's ffmpeg worker
(`cards_exec.py`). The base-rig conform (`reorder_web.py --agent`) is the
same package. None of that is a page and none of it is superseded.

## What still leans on the old page (check each before the flip)

| | What | To settle |
|---|---|---|
| 1 | **The Windows and Android apps** load the old page (`editor/PARITY.md`, last partial row; `NAS-CUTOVER.md` phase 4 is not done). | Either point the apps at the new editor first, or accept that they show the old page at `/cards/old` until they are rebuilt. |
| 2 | **The phone.** The old page is what a phone has installed today (its service worker's scope is `/cards/`). The new editor has a phone layout and its own service worker, tested in portrait, but nobody has used it on a phone in the field. | One real session on the phone at `/cards/edit` before the flip. |
| 3 | **Offline.** The old page keeps a whole episode on the device (`15-offline.js`). The new editor keeps its shell, the lines of English and a pending-edit queue; "keep this project on this computer" is phase 4. | Decide whether the flip waits for phase 4. |
| 4 | **The landing page** (`cards_landing.py`) lists episodes and links to `/cards/p/<slug>/`, with a second link to the new editor. | Flip which link is the main one. |
| 5 | **The fleet's pinned jobs** (`cards_exec.py`) borrow an engine from the pool the old page fills. With no page opening engines, a pinned job needs an engine opened for it. | Give `cards_exec` its own engine, or keep one pool slot for it. |
| 6 | **The companion's Timeline Cards agent role** (`/cards/agent/*`, `cards_tunnel.py`) speaks the old engine's protocol. It is off everywhere. | Leave off; decide later whether it is rebuilt against the new editor or removed. |
| 7 | **Installed service workers.** A browser that has the old page's worker will serve the old shell over `/cards/` after the flip unless it is told to stand down, exactly as on 2026-09-14 (`/cards/sw.js` became a kill switch then). | The same kill switch, once more, as part of the flip. |

## The steps

Each step is one change that can be undone on its own.

1. **A real session on the phone and one on the laptop at `/cards/edit`**
   (rows 2 and 3). No code. The owner's call on whether offline waits for
   phase 4.
2. **Dashboard: make the editor's mount base a setting.** `cards_edit.py`
   has `MOUNT_PATH = "/cards/edit"` as a constant today; the flip in
   `CARDS_EDITOR.md` assumes it is a settings value. Build that, with the
   old mount moving to `/cards/old` when the editor takes `/cards`, the
   route order, the login gate's open paths, the CSRF and JSON-401 prefixes
   and the service-worker kill switch (row 7). Tests for both positions.
   This is dashboard code, so it ships as a dashboard release, before
   anything is switched.
3. **Flip the setting** on this studio's dashboard: `/cards` is the new
   editor, `/cards/old` is the old page. Rollback is the same setting.
4. **Leave it for a release.** Fix what turns up.
5. **Take the old page out.** In the Editing repo: `cards/page/`, the page
   half of `cards/handler.py`, the page's tests and the golden page. In
   ccsync: the WSGI mount, the pool (after row 5), `cards_ai.py`, the
   `/cards/old` route, the old open paths, and the `CLAUDE.md` paragraphs
   that describe them. Per the tree's rule ("retire, do not delete") the
   page moves to `E:\Projects\legacy\` with a line in `README.md`; git
   history keeps it either way.

## What needs the owner

- **Yes or no to steps 2 to 5**, and whether step 3 waits for the phone and
  offline checks.
- **The dashboard release in step 2.** At the owner's terminal that is
  `tools\ship.cmd` (it prompts for the admin password). The unattended
  pathway reads CI, and the CI job that runs the dashboard suites is
  switched off (`d20af6a`), which since 2026-11-11 makes a customer release
  refuse unless told otherwise (`docs/CI.md`).
- **The apps** (row 1): rebuild them to open the new editor, or leave them
  on `/cards/old`.

## What is already done towards it

- The branches are merged and `main` deploys cleanly on top of what is live.
- The owner's controller requests and the English-across-paragraphs fix are
  in the new editor (`fdc5784`, `3f2344a`).
- The old page still got the same controller work on 2026-11-11 (`d9188d7`),
  so nothing is lost for anyone still on it in the meantime.
