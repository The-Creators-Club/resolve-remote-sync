## The edit chat knows which cards are selected, 2026-09-11

Alex' ask: typing "the selected cards should be adjusted", "the selected cards
need to be moved after X" or "make the current card selection a new group
called Interviews" into Timeline Cards' "ask claude" edit chat must work
without the owner naming a single card.

Half of it already existed. Since 2026-09-10 the page has sent `ctx.selected`
(bare uids, in cut order) and the model has had a `@selected` handle. What it
did not have was anything to SAY about those cards: no person, no timecode, no
words, no heading, no order the editor would recognise, and nothing that
distinguishes "the selection" from the cut list around it. A turn whose digest
listed a card short ("[cut:aaa] Ada Chen 4.2s") could not be asked to reason
about it, and "make the selection a group" had no operation behind it at all.

### The wire shape

`POST /cards/api/chat` gains two OPTIONAL top-level keys beside `text`,
`version` and `ctx`:

```json
{
  "text": "make the current card selection a new group called Interviews",
  "version": 41,
  "ctx":  { "playhead": {...}, "selected": ["cut:aaa111", "cut:bbb222"] },
  "selection": [
    {"id": "cut:bbb222", "person": "Lin Wu",  "label": "we were ready",
     "tc": "01:00:19:02"},
    {"id": "cut:aaa111", "person": "Ada Chen", "label": "nobody came",
     "tc": "01:00:04:10"}
  ],
  "staged": []
}
```

* `selection` is the SAME cards as `ctx.selected`, in the order they were
  CLICKED (`MULTI` is a `Set`, so its own iteration order is that order), with
  a label each: `person`, `label` (the card's first words, capped at 80 chars)
  and `tc` (the timecode the page is showing, which is the one thing only the
  page knows). `ctx.selected` keeps its cut order and its meaning, because
  `@selected` and every op that takes a list of uids treat that as an order.
* `staged` is the same shape for cards on the staged shelf, which are in the
  file but NOT in the cut and take different ops (`unstage`, not `move`).
* Empty list when nothing is selected; `group` is carried for a staged card's
  shelf category. NEVER A PATH: a uid, a person's name, a timecode and the
  card's own words, all of which the digest already carries. The page test
  asserts this with the same regex the `ctx` check has used since 2026-09-10.

Server to model, rendered once per turn under the CONTEXT block:

```
SELECTED CARDS
The user currently has 2 cards selected on the page, in the order they were
selected. Use these ids in ops; "@selected" means exactly these cards.
  1. [cut:bbb222] Lin Wu - 01:00:19:02 - "we were ready" (section: Middle)
  2. [cut:aaa111] Ada Chen - 01:00:04:10 - "nobody came" (section: Opening)
END SELECTED CARDS
```

Server to runner: the same rows as STRUCTURE, `selection=` on
`cards_ai.Runner.run`.

### Where the block is rendered, and why exactly once

Timeline Cards renders it (`Where.selection_block`), because the standalone
server's `claude -p` door has no runner to render anything for it. The CC Sync
runner renders it too when a caller hands it `selection=` and the prompt does
not already carry the header - `SELECTION_HEADER` ("SELECTED CARDS") is the
same string in both repos and is the whole dedupe test. So:

* new page + new dashboard: Cards writes the block, the runner sees the header
  and passes the prompt through untouched;
* new page + OLD dashboard runner: `claude.run_claude` reads the runner's
  signature and does not pass `selection=` at all (an unexpected keyword in a
  seam whose promise is "never raises" would be "the AI provider failed
  (TypeError)" on every turn); the block is still in the prompt;
* old page + new dashboard: no `selection` anywhere, and the prompt is byte for
  byte the one sent yesterday. Pinned by
  `test_no_selection_is_todays_prompt_exactly`.

The block always lands in the UNCACHED half of the prompt (after
`---INSTRUCTIONS---`). A selection changes on every click and the corpus block
is billed per cache write; a selection above the marker would re-write an
episode's whole cached prefix every time the editor clicked a card.

### Files changed

CC Sync (`E:\Projects\ccsync`):

* `dashboard/src/ccsync_dashboard/cards_ai.py` - `Runner.run(..., selection=)`;
  `SELECTION_HEADER` / `SELECTION_END` / `MAX_SELECTION_ROWS`;
  `selection_block(selection, staged)`, `_selection_rows`, `_selection_line`,
  `_with_selection` (insert into the instruction half, skip when the header is
  already there).
* `dashboard/tests/test_cards_ai.py` - seven checks (the block and its order,
  the uncached half, today's prompt without it, the dedupe, a bare-id list, the
  staged rows, a selection longer than the label cap).

Timeline Cards (`E:\Projects\Editing\Resolve\MulticamPipeline`, inside the
Editing repo - the unrelated uncommitted work there was not touched):

* `multicam_pipeline/cards/page/16-chat.js` - `chatSelUids`, `chatCardOf`,
  `chatRowOf`, `chatSelRows`, `chatStagedRows`; the POST body carries
  `selection` and `staged`.
* `multicam_pipeline/cards/handler.py` - `/api/chat` passes both through.
* `multicam_pipeline/cards/chat_edit.py` - `SELECTION_HEADER` / `_END`;
  `Where(engine, ctx, selection, staged)` with `_rows` (ids checked against the
  LIVE cut list and shelf, person/words taken off the live card, section
  derived here from the markers, a dead id dropped), `_live`, `_section_of`,
  `wire()`, `selection_block()`; `block()` appends it; `ask` / `_ask` take the
  two new arguments; `_turn` passes `selection=` down; the new `section_from`
  op and its validation.
* `multicam_pipeline/cards/claude.py` - `run_claude(..., selection=)` and
  `_takes_selection(runner)` (signature read once, cached on the runner, a
  runner it cannot inspect counts as no).
* `multicam_pipeline/cards/library_engine.py` - `_run_claude_json(...,
  selection=)`.
* `multicam_pipeline/cards/config.py` - `section_from` in
  `CHAT_OPS_REFERENCE`, plus a paragraph telling the model what a SELECTED
  CARDS block is.
* `tests/test_chat_edit.py` - new sections (m2) and (m3), 14 checks.
* `tests/test_chat_page.js` - five checks on the posted body.
* `tests/golden/page.html` - regenerated for the JS (69 lines, all mine).

### What the model can now do to a selection

Every op that takes uids already accepted `@selected`, and now the ids are in
the prompt as well, so the model may name them one by one: `move` (before /
after / to_start / to_end / at_playhead), `delete`, `stage` (with a category),
`color`, `note`, `trim`, `split`, `gap`, `highlight`, `section_add` before the
first of them, `section_move`, and `insert` placed relative to one of them.

New: `section_from {uids, title}` - "make the current card selection a new
group called Interviews". It is two of the existing engine requests and no new
path under them: one `reorder` that gathers the cards where the first of them
already sits, then one `marker` that puts a section heading in front of the
first. One op rather than two composed by the model, because `move`'s anchor
may not be one of the cards being moved, which is exactly what the model would
write. The line the editor reads says what it did not do: a section runs until
the NEXT heading, so cards that follow the group fall under it unless one is
already there. Closing it would mean inventing a second heading with a title
nobody asked for.

### OWED

1. **The shelf has no selection of its own.** `staged` is on the wire, built by
   the page and rendered by both sides, but the shelf's cards are click-to-hear
   and drag-to-place; nothing on the page ever puts a shelf uid in `MULTI`. So
   in the field the key is always `[]` today. What it would take: a marquee or
   shift-click on `#stagetab` filling a `SMULTI` set, and `chatStagedRows`
   reading it instead of intersecting with the cut selection. Small, but it is
   page interaction work rather than plumbing, and it belongs with whoever next
   touches the shelf.
2. **"Group" is a SECTION here.** The canvas has no other grouping concept
   (runs and stacks are a different thing), so `section_from` writes a section
   marker. If the owner means something else by "group", that is a new engine
   kind and a new page affordance, not a chat change.
3. **`section_from` cannot close a section it opens** (see above).
4. **Never run live against Fable.** Everything below was proved against the
   scripted runner and a headless page, exactly as the chat itself was on
   2026-09-10, which has still never had a live turn against the real model.

### How it was verified

* `dashboard/.venv/Scripts/python.exe -m pytest tests/test_cards_ai.py -q` ->
  57 passed (50 before, 7 new).
* `python tests/test_chat_edit.py` -> all passed, including the pre-existing
  "no prompt of that conversation hands the model a file to open" and "none of
  them carries the vault root either", which now also cover the new block.
* `python tests/test_page_golden.py` -> all passed after regenerating
  `tests/golden/page.html`.
* `node tests/test_chat_page.js 8879` against `python tests/run_all.py --serve
  agent --port 8879` -> all passed; the fixture server was killed afterwards
  (a leftover 88xx server silently takes the Cards agent role).
* `python tests/test_claude_seam.py` and `python tests/test_handler.py` -> all
  passed (both files' modules were touched).
* `node --check` on `16-chat.js` and `test_chat_page.js`; `py_compile` on
  `cards_ai.py`, `test_cards_ai.py`, `chat_edit.py`, `claude.py`,
  `library_engine.py`, `handler.py`, `config.py`.
* No full suite and no full Cards gate was run, per the standing rule that the
  orchestrator runs those once.

### Deploy order

**Timeline Cards first, the dashboard second - and either alone is safe.**

The whole feature works with a new Cards checkout on today's dashboard: the
block is in the prompt because Cards renders it, and `run_claude` simply does
not hand the old runner a keyword it has no parameter for. The dashboard change
adds nothing an editor can see; it is there so a caller that hands the runner
structure instead of prose gets the same block, and so the header stays one
string owned by two repos.

So: ship the Cards checkout (`server/install_dashboard_app.py` snapshot of the
commit, per `docs/CARDS_DEPLOY.md`), then the dashboard at leisure. Nothing
here is a schema change, nothing is a companion change, and no editor machine
is involved at all.
