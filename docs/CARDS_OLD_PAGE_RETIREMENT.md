# Retiring the old Timeline Cards page

Written 2026-11-11 as a plan. **Step one was built on 2026-11-12** (the owner:
"the old timeline cards should be gotten rid of and the picker does not need
'open in new editor', just open should open the new editor. The old timeline
cards should be retired"). It is in the repo as dashboard 0.7.80, tested, and
**not yet released or deployed**: until that release is live, the dashboard
behaves as it did.

This is phase 5 of the plan that already exists
(`Resolve/MulticamPipeline/editor/docs/NAS-CUTOVER.md` in the Editing repo,
and "The flip" in [`CARDS_EDITOR.md`](CARDS_EDITOR.md)), plus the step after
it: taking the old page's code out.

## What is built (dashboard 0.7.80)

The old page is retired **at the dashboard's door**. Nothing was deleted.

| | Before | With 0.7.80 and the editor on |
|---|---|---|
| The picker at `/cards/` | "Open" opened an engine on the server and went to the old page; a second quiet link went to the new editor | One **Open** per episode. It goes straight into the editor, on the episode's newest cut list. No second link, no "opening", no "close", no cap on how many are open |
| `/cards/p/<episode>/` (the old page) | The old page | A browser going there is sent to the editor for that episode. A request from an old tab that is still open gets a sentence saying the page is retired (HTTP 410) |
| "Last opened" and "Carry on with" | Recorded when the old page was entered | Recorded by the Open itself (`GET /cards/go/<slug>`), so the picker still orders by what you opened last |
| The old page's offline workers | Kept a saved picker and each episode's page on the device | Both stand down the next time the device reaches the server. **Nothing a device saved is deleted**: an old page's unsent edits are still on the device if the old page is brought back |
| Jobs the fleet gives up on | Pinned to the dashboard's own worker, which ran on an old-page engine | Abandoned, and shown as abandoned, because no engine is opened any more (see "Still to do", row 1) |

One predicate decides all of it, `cards.old_page_retired(settings)`: the
editor is on (`DASH_CARDS_EDITOR=1`, i.e. `[timeline_cards] editor = true`)
and the rollback switch is not set.

* **The editor off** (the vendor build, and any customer who has not turned
  it on): the old page exactly as it was. It is the only page there is.
* **Rollback**: set `DASH_CARDS_OLD_PAGE=1` on the dashboard container and
  restart it. The old picker, the engine pool and the old page come back as
  they were, and the editor stays reachable at `/cards/edit/`.

Where it is: `cards.py` (`old_page_retired`, `CardsDispatch._retired`,
`EPISODE_SW_KILL`), `cards_landing.py` (`_state_retired`, `cards_go`,
`CARDS_SW_KILL`), `templates/cards_landing.html`, `cards_exec.py`
(`RETIRED_WHY`), `app.py` (the lifespan's executor), `jobs.py` and
`alerts.py` (what a job pinned before the change is told). Tests:
`dashboard/tests/test_cards_edit.py` (from `cards_app` down) and one in
`test_alerts.py`.

The editor did not move: it is still at `/cards/edit/`, and the picker is
still `/cards/`. The plan's "make the mount base a setting and move the
editor to `/cards`" was not needed to get what was asked for, and it is not
built.

## What "the old" is, and what is NOT going

Two things share the name and only one of them is superseded.

**Retired: the old PAGE.** `multicam_pipeline/cards/page/` (21 JavaScript
slices, `cards.html`, `cards.css`, `sw.js`), the HTTP handler that serves it
(`cards/handler.py`, about 70 routes), and on the dashboard the WSGI mount
(`cards.py`, `cards_wsgi.py`), the engine pool (`cards_pool.py`) and the
page's three Claude features (`cards_ai.py`). All of it is still in both
repos, unreachable while the page is retired.

**Staying: the old Python ENGINE as a library.** The new editor runs it.
Its Python bridges import `multicam_pipeline.cards` for the transcript
index, the paragraph English, the conform plan and the timeline read
(`editor/features/*/bridge.py`), and its tests pin the old cut-list reader's
behaviour. The base-rig conform (`reorder_web.py --agent`) is the same
package. None of that is a page and none of it is superseded.

## What the retirement costs, today

Things the old page did that are different now. Each was on the plan's list.

| | What | Now |
|---|---|---|
| 1 | **Offline on a phone or laptop.** The old page kept a whole episode on the device and opened it with no network, from the picker's "on this device" window. | The picker no longer lists on-device copies (they were the old page's). The editor has its own "keep on this device" (`editor/features/projects/offline*.ts`); a cut list kept there is opened from inside the editor, not from the picker, and the picker itself does not open with no network. |
| 2 | **The Windows and Android apps** (`apps/` in the Editing repo) load whatever the server serves at `/cards/`. | They show the new picker and open the editor. Their own offline store held the OLD page; nobody has run the editor inside them yet. |
| 3 | **Edits waiting on a device.** An old page that went offline with edits it had not sent. | It cannot send them: its API answers "retired". They stay on the device. If that matters for a device, use the rollback, let it send, then switch back. |
| 4 | **Pinned fleet jobs** (`cards_exec.py`). | See "Still to do", row 1. |

## Still to do

| | What | Notes |
|---|---|---|
| 1 | **Give the pinned-job executor an engine of its own.** | It borrowed one from the pool the old page filled. Until this is built, a media job the fleet spends its retry budget on is abandoned (visibly) instead of being run by the dashboard. A job that was already pinned when 0.7.80 arrived is told so in words, with "cancel it and queue it again". |
| 2 | **Release 0.7.80 and deploy it.** | A dashboard release (`docs/RELEASE_PATHWAYS.md`). No Cards deploy is needed for the retirement itself. |
| 3 | **Leave it for a release.** | Fix what turns up. The rollback is one setting. |
| 4 | **Take the old page out.** | In the Editing repo: `cards/page/`, the page half of `cards/handler.py`, the page's tests and the golden page. In ccsync: the WSGI mount, the pool (after row 1), `cards_ai.py`, the dispatcher, the old open paths, the rollback switch, and the `CLAUDE.md` paragraphs that describe them. Per the tree's rule ("retire, do not delete") the page moves to `E:\Projects\legacy\` with a line in `README.md`; git history keeps it either way. |
| 5 | **The apps** (row 2 above). | Run the editor in the Windows and Android apps, or rebuild them for it (`NAS-CUTOVER.md` phase 4). |
| 6 | **The companion's Timeline Cards agent role** (`/cards/agent/*`, `cards_tunnel.py`) speaks the old engine's protocol. It is off everywhere. | Leave off; decide later whether it is rebuilt against the editor or removed. |
