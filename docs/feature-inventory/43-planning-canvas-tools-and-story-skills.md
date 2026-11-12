# The planning canvas: building it, changing it, reading it back, and turning it into a cut

Terms used throughout this section:

- **Canvas**: a board file (`.canvas`, JSON) opened in the notes program Obsidian. It holds **cards** (text boxes, or "file" boxes that embed another note) and **groups** (labelled rectangles drawn around cards). A group is a themed **section** of the film.
- **Paragraph card** (also "quote card"): a card holding one transcript paragraph. Its first line is a source link of the form `_Source: [[<vault-relative transcript path>#^<ref>|<transcript name> › ^<ref>]]_`, then a blank line, then the paragraph text. The **ref** (block reference) is 4 to 10 lowercase letters or digits that name the paragraph inside its transcript.
- **Direction card** (also "note card"): a text card with no source link (for example "b-roll: harbour at dawn").
- **File-embed card**: a card that embeds a block of another note, usually a transcript from another season.
- **Interviewee**: identified everywhere by the name of the folder the transcript sits in (`.../Interviewees/<Name>/...`), not by the transcript's file name.
- **Pool canvas**: the themed canvas that holds every paragraph of every transcript. **Ordered canvas** (the "cut"): the hand-ordered canvas that is the film in order.
- **Vault**: the Obsidian notes folder (default `X:\Vault`). **Episode root**: the episode's folder, holding `Interviewees\`, `Clips\` and `Script Docs\`.
- **Reflow plugin**: the Obsidian plugin `canvas-reflow` installed in the owner's vault, which packs a group's cards into columns and lines groups up in a row. Every tool here lays cards out exactly as that plugin would, so opening the result and pressing "reflow" changes nothing.
- **Stage 9** is building the canvas; **stage 10** is turning an ordered canvas into a Resolve timeline. **Cut list** is a `.cut.md` file that the Timeline Cards editor opens.

## How a canvas is read: what "order" means
(source: canvas_timeline.py `load_entries`, `classify`; reused by story_flow_extract.py, resequence_canvas.py, canvas_to_cutlist.py and the structure-notes scripts)

- Only three node types are read: groups, text cards and file cards. Any other node type on the canvas (for example a web-link node) is ignored by every reader and never appears in the order.
- Groups are taken left to right by their x position; when two groups share an x, the higher one (smaller y) comes first. There is no notion of rows: a group placed lower down but further left is read before a group further right, whatever its height.
- A card belongs to the first group, in that left-to-right order, whose rectangle contains the card's top-left corner (left and top edges inclusive, right and bottom edges exclusive). Where a card overlaps two groups, the leftmost group wins.
- Inside a group, cards are bucketed into columns: cards are taken in x order and a card joins an existing column if its x is within 20 px of that column's first card; otherwise it starts a new column. Columns are read left to right, and within a column cards are read top to bottom by y.
- Physical gaps mean nothing: the distance between cards, between columns or between groups is never read. Only the relative order of positions matters.
- Cards outside every group are appended after all groups, sorted by x then y, under the section name `(ungrouped)`, and the reader prints `WARNING: <n> node(s) outside every group -- appended at the end`.
- A group with no label is named `(unnamed group)`.
- Each card read becomes one of three kinds:
  - **quote**: a text card whose text contains a `[[<path>#^<ref>]]` or `[[<path>#^<ref>|<alias>]]` link (ref 4 to 10 lowercase letters or digits). Its "match text" is the LAST non-empty line that is not the source line (for a Mandarin interview, the verbatim Chinese line); its label is the first such line, cut to 60 characters.
  - **note**: a text card with no such link. Its text is collapsed to single spaces.
  - **file**: a file-embed card, with the embedded file path and the block it points at (the part after `#`, without the `#`).
- Index numbers: every reader that numbers cards (`[N]` in the story spine, the structure-notes tools, the re-sequence plan) numbers them 1, 2, 3 ... in exactly this order, direction cards and file cards included. Numbers shift as soon as a card is added or moved.

## The layout grid every canvas writer uses
(source: reflow_grid.py)

- The grid's numbers are read from the vault's own reflow-plugin settings file, `.obsidian/plugins/canvas-reflow/data.json`, found by walking up from the canvas's folder to the first folder that holds one. If none is found, or it cannot be read or parsed, the plugin's shipped defaults are used.
- Settings read and their defaults:
  - `padding` 40 px: inside a group, left, right and bottom.
  - `labelHeadroom` 60 px: added to the top padding (top padding is therefore 100 px by default) so the group label has room.
  - `gapX` 40 px between columns.
  - `gapY` 40 px between cards in a column.
  - `maxPerColumn` 8 cards per column (never less than 1).
  - `groupGap` 60 px between groups in the row.
  - `groupRowAlign` `top` (also `center` or `bottom`): how groups of different heights line up in the row.
- Packing a group: cards keep their own width and height; the first 8 go down the first column, the next 8 down the second, and so on ("column-major"). A column is as wide as its widest card. The group is then resized to fit its cards plus padding. Its top-left corner does not move.
- Packing a row of groups: groups go left to right on one baseline, each `groupGap` after the previous one's right edge, their cards moving with them; vertical alignment follows `groupRowAlign`.
- Each writer prints a one-line description of the grid in use, naming the settings file or "plugin defaults".
- Standard card width is 600 px (column pitch 640 px with the default gap).

## Card height
(source: heightfit.py; also the top-level heightfit.py shim)

- A card's height is estimated from how its markdown renders in Obsidian at width 600, so a card is neither clipped nor padded:
  - body lines wrap at 76 width units per line, 24 px per rendered line;
  - a line starting with `# ` (an interviewer question) is rendered as a heading: 40 units per line, 40 px per line;
  - each blank line adds 16 px;
  - card padding 44 px total, plus a 10 px safety margin;
  - minimum height 80 px.
- Width units: East Asian wide and full-width characters count 2, everything else 1.
- The source line `_Source: [[long path|Name › ^ref]]_` is measured as the short text `Source: Name › ^ref` that it renders as.
- `==` highlight marks add no width, and a line wrapped in a single pair of `_` or `*` is measured without them.
- Used by the add-interview tool and the structure-notes flag cards. The first build takes each card's height from the paragraph file instead (computed by the transcript tools, another section).

## One colour per interviewee
(source: interviewee_colors.py)

- Every interviewee has one colour, used for their cards on the canvas, their multicam clips in Resolve's media pool, and their cuts on the conform timeline.
- The palette is 16 hex colours in a fixed order: `#1375a0`, `#ec4b93`, `#448f64`, `#00b5b8`, `#dbaf80`, `#966145`, `#f09ec1`, `#000035`, `#c8a9fe`, `#16552f`, `#b8ad4c`, `#4577a1`, `#7a3b8f`, `#2f6f5e`, `#a0522d`, `#5470c6`.
- Each palette entry is paired by hand with one of Resolve's clip colours, in the same order: Blue, Violet, Green, Teal, Tan, Chocolate, Pink, Navy, Purple, Olive, Yellow, Blue, Purple, Green, Orange, Navy. The first 8 interviewees therefore get 8 distinct Resolve colours; from the 9th on, Resolve colours repeat.
- A canvas colour that is not in the palette (a card recoloured by hand) is mapped to the nearest of Resolve's 16 clip colours by a weighted colour distance, never to Brown.
- Resolve's "Brown" is never assigned anywhere, by rule. The list of colours a picker may offer is Resolve's 16 minus Brown, 15 in all, in Resolve's own menu order (Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Chocolate); the Timeline Cards editor builds its per-cut colour picker from it (that picker belongs to another section).
- The assignment is remembered in a file `interviewee_colors.json` in the folder given to it (see each tool for which folder). Its contents: a comment line, then for each name its `hex` and a derived `clip_color`. Editing `hex` by hand recolours that person everywhere on the next run; `clip_color` is rewritten from `hex` on every save. An unreadable or unparseable file is treated as empty.
- Assigning colours: a name already in the file keeps its colour. New names are taken in case-insensitive alphabetical order and each takes the lowest palette slot nobody uses yet. With more than 16 people the palette wraps (the slot is the count of people already assigned, modulo 16), so colours repeat.
- Interviewee names, where a tool needs the full list, are the subfolders of `<episode root>\Interviewees`, excluding `archive`, `script docs` and `_archive` (any case), sorted case-insensitively.
- A name from a transcript path is the second-to-last path component (the folder the transcript is in). Cards borrowed from another season resolve the same way, so the person keeps their colour across episodes.

### The colours command
(source: interviewee_colors.py `main`; run as `pipeline.py interviewee-colors <episode root>`)

- Argument: the episode root (surrounding quotes and spaces are stripped).
- Always first loads or extends the map at `<episode root>\Script Docs\interviewee_colors.json` from the `Interviewees` folders and SAVES it if anything changed, even on a dry run. Prints the map path and one line per interviewee: name, hex, Resolve colour.
- `--no-resolve`: stop there; Resolve is not touched. Exit 0.
- Otherwise connects to Resolve (needs Resolve open with a project; the connection is made through the transcript tools, another section). Refusals, printed as `Resolve: <message>` with exit status 1:
  - `no project is open in Resolve`;
  - `no multicam clips in bin '<name>'` when the bin holds no multicam clips.
- `--bin <name>`: the media pool bin holding the multicams. Default: whichever bin is open in Resolve.
- For each multicam clip in that bin, the clip name is matched to an interviewee folder (matching rule belongs to the transcript tools). A clip with no matching folder uses its own name stem as the "person", so its colour is at least stable, and after the run the tool prints `NOTE: no interviewee folder under <path> for: <clips> -- run Export first if these should share a person's colour`. Such stems are added to the map file.
- Default is a dry run: each clip is reported as `already <Colour>`, or `would set <Colour> (now <current or none>)`. Prints `Dry run. Re-run with --apply to set the clip colours.`
- `--apply`: sets each clip's colour; status `set <Colour>` or `FAILED to set <Colour>`.
- The map file is saved again after the media-pool pass (dry run or not).
- `--timeline`: also brings the cuts on track V1 of Resolve's CURRENT timeline to their interviewee's colour, only those whose colour differs; prints `timeline: <n> cut(s) recoloured` (or `would be recoloured` without `--apply`). Each change is one Resolve undo step. Refuses with `no timeline is open in Resolve` (this error is not caught, so the command stops with a traceback). Runs only if the media-pool pass succeeded.
- Output table columns: multicam, interviewee, hex, status.

## Building a canvas from scratch (stage 9)
(source: build_canvas.py; also the top-level build_canvas.py shim; run as `pipeline.py build-canvas <paragraphs.jsonl> <assignments.json> <out.canvas>`)

- Needs exactly three arguments; with any other count it prints its usage text and exits 1.
- Input 1, the paragraph file (made by the transcript tools, another section): one JSON record per line with at least `key`, `interviewee`, `text` and `height`. Blank lines are skipped. The order in which interviewees first appear in this file is the interviewee order used inside every group.
- Input 2, the assignments file: `{"themes": [{"name": ..., "role": ..., "keys": [...]}, ...]}`. A byte-order mark at the start is tolerated. Each theme lists paragraph keys. The themes and their first proposal come from the canvas-sorter instruction file (section 42).
- Theme roles: `personal`, `body` or `ending`. A theme without a role gets one from its name: "Personal Stories" (any case, surrounding spaces ignored) is `personal`, "Ending" is `ending`, anything else is `body`.
  - Refusal: a role that is not one of the three prints `ERROR: unknown theme role(s): <list> (expected one of personal, body, ending)` and exits 1.
- Every paragraph lands in exactly one group:
  - A key listed under a second theme is dropped there, keeping the first placement, with `WARNING: <key> already placed - dropping the duplicate in '<theme>'`.
  - A key not in the paragraph file is an error: `ERROR: unknown key <key> in theme '<theme>'` for each, then exit 1. Nothing is written.
  - Paragraphs no theme listed are swept into a final group named `Uncategorised`.
- Group order along the row: all `personal` groups first, then `body`, then `ending`; within each band, the order the assignments file listed them (the sort never reorders within a band). `Uncategorised` is always last: if the assignments file names it explicitly, its keys are taken out of the normal order and placed, together with any swept-in leftovers, in one final `Uncategorised` group. The name match is exact (capital U, British spelling).
- Inside a group, cards are arranged interviewee by interviewee (in the paragraph file's interviewee order), and within one interviewee in the order the assignments file listed the keys. They are then packed on the reflow grid (8 per column by default).
- All groups sit in one row, top-aligned at y = 0, starting at x = 0, each one group gap after the previous.
- An empty group (a theme whose keys were all dropped as duplicates) is still drawn: 680 px wide by default (600 plus padding both sides) and as tall as its top and bottom padding.
- Each card: 600 px wide, its height from the paragraph file, its text exactly the paragraph's text (including the source line), white text, background, border (2 px) and canvas colour all set to the interviewee's colour.
- Colours come from the colour map kept in the SAME folder as the output canvas (`<canvas folder>\interviewee_colors.json`), extended for any new interviewee and saved when anything changed. People already in the map keep their colour.
- The output file is written as indented JSON with no connecting lines (edges). Its folder is created if missing. An existing file at that path is overwritten without a backup.
- Printed summary: the grid in use, `Wrote <path>`, the count of theme groups, paragraphs placed, and how many were swept into `Uncategorised`; the count of duplicates dropped; a coverage line `coverage: <placed>/<total> paragraphs placed exactly once` with `<-- MISMATCH` appended if they differ; the colour map path; and one line per interviewee with hex and Resolve colour.
- Card and group identifiers are derived from the theme name and paragraph key, so rebuilding the same input gives the same identifiers.
- Needs from outside: the paragraph file and assignments file (from other tools and the canvas-sorter skill); optionally the vault's reflow-plugin settings. No Resolve, no Obsidian running.
- This tool is for a fresh canvas only: it discards any hand arrangement. The tools below edit a canvas that is already in use.

## Adding a later interview to a canvas in use
(source: add_to_canvas.py; also the top-level add_to_canvas.py shim; run as `pipeline.py add-to-canvas <transcript.md> <canvas> (--group <label> | --assign <file>) [options]`)

- Purpose: a follow-up interview arrives and its paragraphs must go into groups of a canvas that is already being arranged by hand, without disturbing the rest.
- Input transcript: a prepared transcript note in which each paragraph is a block of lines followed by a line holding only `^<ref>`. Refusal when it has none: `ERROR: no ^ref blocks in <file> - run finalize_transcript.py first` (exit status non-zero).
- Exactly one of `--group` and `--assign` must be given; otherwise the argument parser stops with `give exactly one of --group or --assign`.
- `--group "<label>"`: every block of the transcript goes into that one group.
- `--assign <file.json>`: `{"<group label>": ["ref", ...], ...}` spreads one interview over several groups. Refs may be written with or without a leading `^`. A byte-order mark is tolerated. Anything not listed is left OFF the canvas entirely (no leftover group).
  - Refusal: a listed ref that is not a block of the transcript: `ERROR: --assign names ref ^<ref>, which is not in <file>`.
- `--skip a,b,c`: refs to leave out. `--only a,b,c`: place only these refs. Both accept refs with or without `^`. Excluded refs are listed as `<n> excluded by --skip/--only`.
- `--color <hex>`: override the colour for the new cards.
- `--dry-run`: print what would be added per group and `Dry run - canvas untouched.`; nothing is written.
- Refusal: a group label not on the canvas: `ERROR: no group '<label>' on this canvas. Groups are:` followed by every group label, sorted. Group labels must match exactly.
- Idempotent: a ref already present anywhere on the canvas (read from any card's source link) is skipped and listed as `<n> already on the canvas, skipped: ^a ^b ...`. Re-running after adding blocks to the transcript adds only the new ones.
- Each new card's text is `_Source: [[<vault-relative path>#^<ref>|<transcript stem> › ^<ref>]]_`, a blank line, then the block. The vault-relative path is everything after a folder named `vault` (any case) in the transcript's path, or the last five path components if there is no such folder. Height is the card-height estimate above.
- Colour: the interviewee's colour as it already appears on THIS canvas (the colour of the first card whose source link is in the same `Interviewees/<Name>/` folder, so two transcripts of one person share a colour); if none, the first palette colour no card on the canvas uses; if all 16 are used, a palette colour chosen by count. The colour map file is NOT consulted or updated. The report says `(reused)` or `(new)`.
- Placement: the new cards go at the END of the target group's reading order. A card counts as already in the group if its CENTRE lies inside the group's rectangle; those existing cards are re-ordered by (x, y) and the whole group, old and new cards together, is re-packed on the reflow grid and resized.
- If the group grew wider, every node whose left edge is at or right of the group's old right edge minus the padding (40 px by default) is shifted right by the same amount, so no group overlaps its neighbour. Groups are processed left to right.
- Per group it prints: cards added, new columns, the x of the first new column, the group's new size, and the row shift in px.
- Before writing, it checks the result and refuses on any problem with `REFUSING TO WRITE - layout check failed:` and exit 1:
  - two groups overlapping (by x, in row order): `groups overlap: '<a>' / '<b>'`;
  - text cards not wholly inside exactly one group: `<n> text node(s) not inside exactly one group`;
  - duplicate node identifiers: `<n> duplicate node id(s)`.
- Before writing, it copies the canvas to `<canvas>.bak-<YYYYMMDD-HHMMSS>` beside it. Backups are never cleaned up.
- The file is written back in the same layout it was read in: if Obsidian wrote it (one node per line, tab-indented), that layout is kept; otherwise indented JSON. Line endings are not converted.
- Prints `Wrote <path> (<n> cards, <m> groups)` and the backup's name. `Nothing to add.` when there is nothing new.
- Needs from outside: a transcript prepared by the transcript tools (blocks with `^ref` lines); the canvas, which should not be open with unsaved changes in Obsidian (nothing checks this); optionally the reflow-plugin settings.

## Carving a new theme out of a canvas in use
(source: regroup_canvas.py; run as `pipeline.py regroup-canvas <canvas> <paragraphs.jsonl> <spec.json> [--dry-run]`)

- Purpose: lift chosen cards out of their groups into a brand-new group, without rebuilding.
- Spec file: `{"group": "<new label>", "keys": [...paragraph keys...]}`, plus at most one placement: `"position": <0-based index>` (clamped to the row), or `"after": "<existing label>"`, or neither (new group goes at the right end). If both are given, `position` wins. Byte-order marks tolerated.
- Cards are matched to paragraph keys by EXACT card text (after trimming surrounding whitespace) against the paragraph file's `text` field. Card identifiers are not used.
- Refusals (each prints `ERROR: <message>` and exits 1, nothing written):
  - the canvas already has a group with that label: `the canvas already has a group called '<label>'`;
  - the spec lists a key twice: `duplicate key(s) in the spec: <first 8>`;
  - the canvas has no groups: `no groups on this canvas - is it a themed canvas?`;
  - some keys are not found on the canvas by text: `<n> requested key(s) are not on this canvas: <first 8> ...`;
  - any card sits outside every group (top-left corner rule): `<n> card(s) sit outside every group - tidy the canvas first, or they would be silently left behind`;
  - the canvas has no cards to measure the card width from: `cannot measure card width - the canvas has nothing to measure it from`;
  - `after` names a group that does not exist: `no group called '<label>' to insert after`;
  - after re-layout, two groups would overlap: `'<a>' and '<b>' would overlap - refusing to write`;
  - a card would stick out of its group: `a card escaped '<label>' - refusing to write`;
  - the number of cards accounted for differs from the number on the canvas: `coverage: <placed>/<total> cards accounted for - refusing to write`.
- Cards not found in the paragraph file are reported as `note: <n> card(s) are not in the paragraph pool - left where they are`; they stay in their group (though that group may be re-packed or shifted).
- Every group that lost cards is re-packed in its remaining reading order (columns by exact x offset, then y) and shrunk. A group left with no cards is deleted, with `'<label>' is now empty - removing the group`.
- The new group's cards are packed in the order the spec lists the keys.
- The whole row is then re-laid left to right from the leftmost existing group's x, at the reflow plugin's group gap, all groups moved onto one baseline (the topmost group's y). Cards ride with their groups. Groups that were spaced differently before are therefore moved too.
- Cards keep their identifier, text, height and colour.
- Printed: the layout description; the new group's card count and position (`position <n> of <m>, after '<label>'` or `first in the row`); how many cards came from each old group; the coverage count.
- `--dry-run`: prints everything and `--dry-run: nothing written`.
- On a real run, copies the canvas to `<canvas>.bak-<YYYYMMDD-HHMMSS>` first, then writes indented JSON (an Obsidian one-node-per-line layout is NOT preserved).
- Needs from outside: the paragraph file for the episode; a canvas whose cards all sit inside groups.

## Re-ordering whole groups along the row
(source: reorder_canvas.py; run as `pipeline.py reorder-canvas <canvas> (--order <file> | --arc | --list) [--dry-run]`)

- Purpose: slide whole groups left or right, cards riding along. No card changes group, no card moves inside its group, nothing is re-packed.
- `--list`, or no option at all: prints the current row (`<file> - <n> groups, <m> cards:` then one numbered line per group with its card count and label). With no option it adds `nothing to do - pass --order <file> or --arc`. Nothing is written.
- `--order <file>`: the new order as group labels, either one label per line (blank lines and lines starting with `#` ignored) or a JSON list, or a JSON object with an `order` list. A byte-order mark is tolerated.
- `--arc`: the mechanical rule with no story judgement: the group named exactly `Personal Stories` moves to the front, the group named exactly `Ending` to the back, everything else keeps its current relative order. Names are case-sensitive here.
- `Uncategorised` (exact name) is always pinned last, whether or not the order names it and wherever it names it.
- Refusals (each `ERROR: <message>`, exit 1, nothing written):
  - the canvas has no groups: `no groups on this canvas - is it a themed canvas?`;
  - any card outside every group (top-left corner rule): `<n> card(s) sit outside every group - tidy the canvas first, or they would be left behind`;
  - two groups share a label: `two groups share a label, so an order cannot name them: <labels>`;
  - both `--order` and `--arc`: `--order and --arc do the same job - pass one`;
  - a label named twice: `group(s) named more than once in the order: <labels>`;
  - a name that is not a group: `<n> name(s) in the order are not groups on this canvas: <names>`;
  - a group left out of the order: `<n> group(s) are on the canvas but not in the order: <labels> - list every group, so nothing is re-ordered by accident`;
  - after the move, overlap, a card outside its group, or a coverage mismatch: the same three messages as the carve-out tool.
- If the requested order is already the current one: `the row is already in that order - nothing to do`, nothing written.
- Layout: the row is re-packed from the leftmost group's current x, at the reflow plugin's group gap, every group moved onto the topmost group's y.
- Printed: each group's new position with a marker showing how far it moved (`^<n>` earlier in the row, `v<n>` later, `-` unmoved), card count and label; then the coverage count.
- `--dry-run`: prints everything, writes nothing.
- On a real run: backup `<canvas>.bak-<YYYYMMDD-HHMMSS>` first, then indented JSON (an Obsidian one-node-per-line layout is not preserved).
- Needs from outside: only the canvas (and optionally the reflow-plugin settings).

## Writing a re-sequenced copy from a card-level plan
(source: resequence_canvas.py; run as `pipeline.py resequence-canvas <canvas> <plan.json> <out.canvas> [--dry-run]`)

- Purpose: rebuild the whole film order card by card into a NEW canvas file; the source canvas is never changed. Used by the structure-notes skill's re-order (below).
- Plan file: `{"groups": [{"label": "...", "cards": [N, ...]}, ...], "drop": [N, ...]}`. A group may have no `cards` (a "marker" group). `drop` is optional. The numbers are the source canvas's reading-order indexes (the `[N]` numbers of the story spine). A byte-order mark is tolerated in the plan.
- Refusals (each `ERROR: <message>`, exit 1, nothing written):
  - the output path is the input path: `output must be a new file - this tool never overwrites its input`;
  - a plan names a number that is not a card on the canvas: `group '<label>' names card [<N>] which is not on the canvas`;
  - a card placed twice: `card [<N>] appears twice: in '<a>' and '<b>'`;
  - a card both placed and dropped: `card [<N>] is both placed (in '<label>') and dropped`;
  - any card neither placed nor dropped: `<n> card(s) neither placed nor dropped: [<list>]`;
  - a label used twice in the plan: `a group label is used twice in the plan`;
  - the source has no cards to measure card width from (same message as the carve-out tool).
- Direction cards and file cards count as cards and must be placed or dropped too.
- Groups are written in plan order, left to right in one row starting at x = 0, y = 0, at the reflow plugin's group gap (settings found from the OUTPUT file's location).
- A plan label that matches a source group reuses that group (its identifier and any other properties, such as its colour). A new label becomes a new group, announced as `new group: <label>`.
- Cards are packed in the plan's order on the reflow grid. A marker group with no cards keeps the source group's box size, or 400 by 400 px if it is a new label.
- Cards keep their identifier, text, height and colour, so the timeline conform still matches on them.
- A source group the plan never names is dropped (`group dropped (plan never names it): <label>`), and dropped cards are listed (`cards dropped: [N], ...`).
- Connecting lines (edges) are kept only when both ends end up in the same plan group; `edges kept <k> of <n>` is printed.
- Any node of another type (not a group, text card or file card) is not carried into the copy, and nothing reports it.
- Printed per group: label, card count, estimated minutes (text-length estimate, see the story-flow extractor); then a TOTAL line.
- `--dry-run`: prints everything and `dry run - nothing written`.
- The output is written as tab-indented JSON. An existing file at the output path is overwritten without a backup (only "same as input" is refused).
- Needs from outside: the source canvas and a plan (normally written by the structure-notes scripts).

## Flattening an ordered canvas for the story read
(source: story_flow_extract.py; also the top-level story_flow_extract.py shim; run as `pipeline.py story-flow-extract --ordered <cut.canvas> --pool <pool.canvas> [--out-dir <dir>] [--conform <report.md>] [--allow-question <ref> ...]`)

- Reads the ordered canvas in the reading order defined above and pairs it with the pool canvas.
- Flags:
  - `--ordered` (required): the hand-ordered canvas.
  - `--pool` (required): the full themed canvas.
  - `--out-dir` (default: the current folder): where the output files go; created if missing.
  - `--conform`: a conform report (made by the timeline tool) to take real cut durations from. If not given, the tool looks for `<ordered stem> - Conform Report.md` beside the ordered canvas and uses it if present.
  - `--allow-question <ref>` (repeatable, with or without `^`): an interviewer-question card that the owner's Structure Notes name for a place in the film; it is reported as exempt instead of as a defect.
- Card text reading rules:
  - The card's body is every non-empty line except the source link.
  - A card is an **interviewer question** when every body line starts with `#`.
  - A line is **Chinese** when it contains CJK characters and more than 30% of its characters are CJK; the English text is all non-Chinese body lines joined, the Chinese text all Chinese lines joined (leading `#` marks removed).
  - Interviewee = the folder name in the source link path (second-to-last component).
- Duration of each quote card: the duration in the conform report for that ref (the first row for a ref wins), else an estimate: Chinese text at 3.6 CJK characters per second when there is any Chinese, else English at 18.5 characters per second, rounded to 0.1 s. Direction cards count 0 s; file-embed cards take the conform duration for their block ref, else 0 s. Every non-conform duration is marked estimated.
- The pool: every text card in the pool canvas that has a source link, keyed by ref (a ref appearing twice keeps the last). Its theme is the label of the pool group containing the card's top-left corner, `(ungrouped)` if none, `(unnamed)` if the group has no label.
- Writes four files named after the ordered canvas's file name (`<stem>`):
  - `<stem>_spine.md`, the narrative spine:
    - title `# Narrative spine -- <canvas file>`, a reading-order note, and two house-style paragraphs: "the film is ONE CONVERSATION" (judge every join as a reply) and "interviewer questions are BANNED from the cut" (any card tagged as a question is a defect; move it to a staged group). When `--allow-question` is used, a sentence about the exempt tag is added.
    - `## SECTION: <group>` at each group, with a `<<<< SECTION BOUNDARY >>>>` line between groups.
    - one entry per card: `**[N] <interviewee> | ^<ref> | <seconds>s**` (`~<seconds>s` when estimated), then the English text or `(no English text)`.
    - tags appended to the entry line: `[DIRECTION CARD -- not a quote]`; `[FILE EMBED from <file>]`; `[INTERVIEWER QUESTION -- banned from the cut, stage it]`; `[INTERVIEWER QUESTION -- exempt, named in the notes]`; `[DUPLICATE -- this ref already played]` for a ref played earlier in the cut. Direction cards show interviewee `(direction)` and ref `^-`; file embeds show `(other season)`.
  - `<stem>_unused.md`, "the bench": every pool paragraph whose ref is not in the cut, under `## <theme>  (<n> unused)` headings (themes with the most unused first), entries sorted by interviewee, each `**<interviewee> | ^<ref>**` (plus ` [QUESTION]`) and its English (else Chinese, else `(no text)`). Its header says questions are context only and must never be proposed.
  - `<stem>_pool.jsonl`: every pool paragraph with ref, source path, interviewee, theme, question flag, English, Chinese, `used` (true if in the cut) and `used_at` (its first `[N]`).
  - `<stem>_flow.json`: a summary and the full spine. The summary holds: both canvas paths; cards in the cut; quote cards in the cut; unique pool refs used; pool paragraph count; unused count; total runtime and the share of cards whose duration was estimated; section order; per section its card count, seconds, first and last `[N]`, cards per interviewee and per pool theme; one boundary record per pair of neighbouring sections with the last two `[N]` out and the first two `[N]` in; duplicate plays; questions in the cut (excluding sections whose name starts with `staged`, any case, and exempt refs); exempt questions; cut cards with no pool match; direction and file cards; pool paragraphs per interviewee; used paragraphs per interviewee; unused per pool theme; whether durations came from a conform report; and the paths of the other three files.
- "Unique quotes" counts only refs that are also in the pool; a cut card whose ref is not in the pool is counted under "no pool match" instead.
- Console output: the four file paths; `<n> cards in cut (<u> unique quotes) / <p> paragraphs in pool / <x> unused`; runtime in minutes and whether from conform durations or estimated; one line per section with cards and minutes; and these warnings:
  - `WARNING: <n> card(s) play a ref that already played: ^ref@[N], ...`;
  - `WARNING: <n> cut card(s) have no pool match (theme unknown)`;
  - `interviewer question ^<ref>@[N]: exempt, named in the notes` per exempt question;
  - `WARNING: <n> interviewer question(s) in the cut -- house style bans them; stage: ^ref@[N], ...`.
- The spine tags EVERY question card, including ones already sitting in a `staged...` group; only the summary list and the console warning leave staged groups out.
- A section that appears twice in the order (two groups with the same label) is merged into one section record in the summary.
- Needs from outside: two canvases; optionally the conform report. No Resolve, no Obsidian.
- Read-only on both canvases; the four output files are overwritten on each run.

## Turning an ordered canvas into a Resolve timeline (stage 10)
(source: canvas_timeline.py; run as `pipeline.py canvas-timeline [options]`)

### Command-line options
- `--canvas <path>`: the ordered canvas. Default is a hard-coded path to one specific episode's canvas (`X:\Vault\2026\FF5\Energy Transition\Script Docs\Energy Transition Canvas (Ordered) V2.canvas`).
- `--vault <path>`: the vault root the card links are relative to. Default `X:\Vault`.
- `--bin <name>`: the media pool bin searched first for clips. Default `Multicams`. The whole media pool is searched after it; a name found in the bin wins.
- `--map <file.json>`: clip overrides, `{"<transcript stem or vault-relative path>": "<clip name>" or null}`, keys compared case-insensitively. `null` skips that transcript (its cards report `skipped by --map`). If not given and a `conform.map.json` sits beside the canvas, that file is used and `map    : <path>` is printed.
- `--only <text>` (repeatable): keep only quote cards whose source path contains this text (case-insensitive); direction and file cards are always kept.
- `--limit <N>`: keep only the first N entries (applied after the alternates and `--only` filters).
- `--include-alternates`: also cut cards in any group whose label contains `Alternates` (case-sensitive). By default those cards are left out and `alts   : <n> card(s) in an 'Alternates' group left out of the cut` is printed.
- `--handles <frames>` (default 12): extra frames before and after each quote, clamped to neighbouring speech.
- `--gap <seconds>` (default 5.0): length of the empty placeholder left for a direction card, file card or unmatched card.
- `--fuzzy-threshold <0..1>` (default 0.8): the lowest similarity accepted when a card's text is not found verbatim.
- `--fps <rate>` (default 29.97, meaning exactly 30000/1001): the rate assumed for a clip whose rate is unknown (every clip in `--from-srt` mode).
- `--timeline <name>`: timeline name. Default `<canvas file stem> Conform <YYYY-MM-DD>`.
- `--from-srt`: offline mode; time cards from the subtitle (`.srt`) files in the vault, with no Resolve connection and no whisper sidecars.
- `--apply`: actually build the timeline. Default is a dry run.
- Refusal: `--apply` together with `--from-srt`: `--apply needs Resolve; drop --from-srt`.
- `--no-clip-colors`: do not tint placed cuts with the interviewee's colour.
- `--no-report`: do not write the conform report.
- `--db-user`, `--db-pass`, `--db-port`: credentials for the project database that holds Resolve's transcriptions (connection handled by the transcript tools, another section).
- Environment variable `CANVAS_TL_DEBUG` (any non-empty value): print the expected and actual position of every cut that fails to place. DEV ONLY.

### Which cards become what
- Reading order is the canvas reading order above.
- A quote card becomes a cut if its words can be found; otherwise an "unmatched" placeholder.
- A direction card becomes a "gap": a placeholder plus a green marker carrying its text.
- A file-embed card: the embedded block is looked up in the embedded transcript (`<vault>\<file>`): the line holding only `^<ref>` and the non-blank lines above it, minus lines starting with `#`. If found and that transcript has timing, the card is cut like a quote using the block's last line; otherwise it becomes a gap noted as `file embed: <file>#^<ref>`.

### Finding each transcript's clip
- Each card's transcript link is resolved to a file: first relative to the vault root; if missing there, by climbing from the episode root towards the drive (up to 10 levels) until the file is found. The episode root is the canvas's folder, or its parent when the canvas is in a folder named `Script Docs` (any case). A link that resolves nowhere keeps the vault-relative guess, and then reports "no .srt" style errors.
- Clip choice, in order:
  1. a `--map` / `conform.map.json` entry for the transcript's stem or path;
  2. the sibling subtitle export: the `.srt` files in the transcript's folder, ignoring names containing `.whisper` or `.truncated` and names ending `.resolve.srt`; an "online" transcript (stem contains `online`) only considers `.srt` names containing `online`, and other transcripts only names without it; used only when exactly one candidate remains, and the clip is named after it;
  3. an excerpt pointer (see below), when the transcript says it was excerpted from another transcript;
  4. a fuzzy name match against the media pool clips (live mode) or the library or whisper-corpus clip names: the transcript stem with `transcript` and `online` removed is split into name tokens and compared with each clip name's tokens; online-ness must match; tokens under 3 characters only count in a whole-token match; a partial (substring) match scores 0.75 per token; the best clip scoring at least 0.5 wins.
- A fuzzy-guessed clip that turns out to have no timing at all is withdrawn and the excerpt pointer is tried; if that also fails, the first guess and its error stand.
- No clip: the transcript's cards are unmatched with `no matching clip (no sibling .srt, no fuzzy hit)`, plus `; pointer to <path> could not be resolved` when an excerpt pointer named a file that was not found.

### Excerpt pointers
- A transcript carried over by hand from another episode can name its origin, and its cards are then timed from the original's clip. The pointer is read from the first 20 lines of the transcript, then of the interviewee note beside it (`<folder name>.md`), in three spellings: front matter `source:` or `excerpt_of:`; or a line `Excerpt of <path>.md` (backticked, quoted or as a wikilink). Only a path ending `.md` counts; a trailing `#^ref` or `|alias` is ignored.
- The pointed-at file is found by climbing from the transcript's folder up to 10 levels.
- At most 2 hops are followed; a path already visited stops the chain (a loop).
- At each hop the same two questions are asked (sibling `.srt`, then fuzzy name). The first that answers becomes the timing folder, and that folder's whisper sidecars are added to the sidecar index. The console says `via <folder>`.

### Where the word timings come from (per clip)
- Four possible sources, chosen per clip:
  - **whisper**: a whisper sidecar `<clip>_words.json`, either `<episode root>\Clips\<clip>\<clip>_words.json` or any `*_words.json` in `<episode root>\Interviewees\<person>\` (made by the transcribe tools, another section). Always asked first when available. An unreadable sidecar prints `NOTE: <clip>: unreadable word sidecar (<error>)` and is skipped.
  - **db**: Resolve's own transcription of the clip from the project database (live mode).
  - **library**: the same transcription read straight from the project library, no Resolve (used by the cut-list tool).
  - **srt**: the vault `.srt` file named after the clip in the timing folder, at subtitle-cue precision.
- Live mode (the default): the clip must be in the media pool (`clip '<name>' not in media pool` otherwise). Rate, start timecode and length come from the clip in Resolve. Words come from the whisper sidecar if any (then the start offset comes from the sidecar), else the database transcription, else the `.srt` (with `NOTE: <clip> has no DB transcription -- using vault .srt`), else the error `no transcription in DB and no vault .srt`. Live mode always opens the project database connection.
- `--from-srt` mode: only the `.srt`; error `no .srt next to <stem>`; the clip's rate is the `--fps` value and its start timecode is taken as 01:00:00:00 (3600 s).
- Whenever the main source is whisper, db or library and an `.srt` exists, the `.srt` is kept as a per-card fallback: if the card is not found verbatim in the main source, the `.srt` is searched too and used if it scores higher. The dry-run table marks such cuts `cut (srt)`.
- A start timecode string that cannot be read is taken as 01:00:00:00. Rates within 0.01 of 23.976, 29.97, 59.94 or 47.952 are taken as the exact 1001-based fractions.

### Matching a card's words
- The text matched is the card's last body line (for a Mandarin interview, the verbatim Chinese; for an English one, the last English line).
- Both sides are reduced to letters and digits only, case-folded, so punctuation, spacing, `==highlight==` marks and polished English punctuation never break a match. Traditional Chinese characters are folded to simplified on both sides, so a traditional-script card matches a simplified transcript and the reverse.
- First, the first verbatim occurrence anywhere in the clip's words. Confidence 1.0.
- Otherwise a fuzzy sweep over overlapping windows (window = the text's length plus a step of a quarter of it, at least 20 characters); the earliest window with the highest similarity wins, and must reach the fuzzy threshold (0.8 default). The in and out points are then narrowed to the first and last substantial matching stretch (at least 4 characters, or 1/50 of the text) so a stray echo cannot drag the in-point early. Search order is optimised (around 16-character anchors from the text's head, middle and tail, up to 3 hits each) but the answer is the same as a plain sweep.
- A card not found: unmatched, `text not found in <clip> transcript`.
- (Library use, for other sections: the same matcher can be confined to a stretch of a transcript, can be hinted where to look first, and can convert a time range into a text range. Timeline Cards uses these; they are not reachable from this command.)

### Cut points
- In point: the matched words' start minus the handles (12 frames by default), but never earlier than the end of the previous spoken word, and never before the clip's start timecode. Pause tokens and line breaks do not count as spoken words.
- Out point: the matched words' end plus the handles, but never later than the start of the next spoken word.
- Converted to frames at the clip's rate (or the default rate), measured from the clip's start timecode; never below frame 0, never past the clip's length when it is known; a cut is always at least 1 frame long.

### Dry run (default)
- Prints `canvas : <path>` and one line per transcript: stem, chosen clip (or `??`), how it was timed (`whisper`, `db` or `srt`) or its error, `via <folder>` for an excerpt, and its colour hex and Resolve colour (or `(no colour)`).
- Prints a table: number, group, ref, clip or note, in timecode, out timecode, duration in seconds, confidence, status (`cut`, `cut (srt)`, `gap+marker`, or `UNMATCHED (<why>)`).
- Summary line: `<n> entries: <c> cuts (<m> min), <g> gaps, <u> unmatched`.
- `NOTE: duplicate card(s) in the canvas -- placed twice: ^ref (#a and #b), ...` when the same transcript block appears twice.
- Ends with `Dry run. Re-run with --apply to build '<timeline name>'.`
- The colour map is read but NOT saved on a dry run.

### Building the timeline (`--apply`)
- Needs: Resolve open with the target project current (refusal `no project is open in Resolve`), the clips in the media pool, the project database reachable (live mode), and the Python database packages the transcript tools use.
- Creates an empty timeline with the chosen name. If Resolve refuses, it creates the timeline from the first matched cut instead; if that fails too, the run stops with `could not create timeline '<name>'`, or `nothing to place -- no matched cuts` when there are no cuts. The new timeline is made current.
- Walks the entries in order, keeping a record position from the timeline's start:
  - at the first entry of each group, a marker named with the group's label. Group markers take a rotating colour by the group's position on the canvas: Blue, Sand, Purple, Mint, Rose, Sky, Lemon, Fuchsia, Cyan, Cocoa, Lavender, Yellow, Pink, Cream, then repeating, so neighbouring sections never share a colour. Green and Red are never used for groups;
  - a gap: a Green marker named with the first 60 characters of the note, full note as the marker's note, then `--gap` seconds of empty timeline;
  - an unmatched card: a Red marker `UNMATCHED ^<ref>` with the reason as its note, then the gap;
  - a cut: appended to the timeline at the record position from the clip's in to out frame (out is exclusive). It counts as placed only if it lands exactly at the record position and its length is within 2 frames of the expected length (a clip at another rate is speed-conformed, so the expected length is scaled by timeline rate over clip rate). Otherwise anything it placed is deleted, `FAILED to place ^<ref> (<clip> <timecode>) -- marker left instead` is printed, a Red marker `FAILED ^<ref>` is added with `AppendToTimeline failed`, and the gap is left. The record position advances by what actually landed.
- All markers are 1 frame long and are added after the cuts. Prints `timeline '<name>': <p> cuts placed, <f> failed, <m>/<n> markers set`.
- Each placed cut is given its interviewee's Resolve clip colour, unless `--no-clip-colors` (`clip colours left alone (--no-clip-colors)`); prints `<t>/<n> cuts tinted with their interviewee's canvas colour`.
- Colours come from the colour map in the canvas's own folder (`<canvas folder>\interviewee_colors.json`), extended with any new interviewee and saved on `--apply`.
- Nothing checks whether a timeline of that name already exists.

### The conform report
- Unless `--no-report`, writes `<canvas stem> - Conform Report.md` beside the canvas, on dry runs too, overwriting any previous one.
- Content: title `# <stem> -- conform report`, a line with the date and time, the timeline name and `applied` or `dry run`, then a table: number, group, ref, clip or note, in, out, duration seconds, confidence, status (`cut`, `gap+marker`, `UNMATCHED: <why>`). On an applied run, cuts that failed to place appear as UNMATCHED with `AppendToTimeline failed`.
- The story-flow extractor reads real durations from this table.

## Turning an ordered canvas into a cut list for Timeline Cards
(source: canvas_to_cutlist.py; run as `pipeline.py canvas-to-cutlist --canvas <file.canvas> [options]`)

- Turns an ordered canvas into a `.cut.md` cut list that the Timeline Cards editor opens. Never needs Resolve. Never writes the canvas. The cut-list file format itself (how it is written, saved and versioned) belongs to the Timeline Cards section; this tool hands it a project of sections, cuts and notes.

### Options
- `--canvas` (required).
- `--kind montage|interview`: override the automatic choice. Automatic: every card carrying a source link counts for "interview"; every card carrying a `_Clip: <name> @ ...` line counts for "montage"; montage wins only if it has strictly more. A canvas with neither is an interview canvas.
- `--root <episode folder>`: default is the canvas's parent folder when the canvas is in `Script Docs` (any case), else the canvas's own folder.
- `--out <file>`: default `<root>\Script Docs\Cuts\<canvas stem>.cut.md`.
- `--project <name>`: the episode name in the cut list. Default the canvas stem.
- `--vault-root <path>`: e.g. `2026/FF5/Energy Transition`, recorded in the cut list.
- `--fps <rate>` (default 29.97, exactly 30000/1001): the TIMELINE rate.
- `--clip-fps <rate>`: the rate assumed for a clip whose real rate is unknown. Default: `--fps`.
- `--drop` / `--no-drop`: drop-frame timecode. Default ON (drop-frame), because this vault's 29.97 timelines are drop-frame. `--no-drop` wins over `--drop`.
- `--tl-start` (default `01:00:00:00`): the timeline start timecode.
- `--timing word|srt` (default `srt`): montage canvases only; a label recorded in the file. An interview canvas sets it itself.
- `--rev <n>` (default 1): the revision number recorded.
- `--handles <frames>` (default 12) and `--fuzzy-threshold` (default 0.8): as the timeline tool.
- `--conform-map <file>`: as the timeline tool's `--map`; default `conform.map.json` beside the canvas if present.
- `--from-words`: also use the whisper corpus as the "library": its clip names become candidates for the fuzzy clip-name match and its recorded rate and start are used as clip facts. (Whisper sidecars are asked first for timing even without this flag.)
- `--from-srt`: vault only; time cards from `.srt` files even if a database is given; ignores whisper sidecars too.
- `--db-host <host>` with `--db-name <library>` (plus `--db-user`, `--db-pass`, `--db-port`): read Resolve's transcriptions straight from the project library database for word timing, read-only, no Resolve. Refusal: `--db-host needs --db-name (the library)`. Ignored when `--from-words` or `--from-srt` is given.
- `--no-colors`: do not give cuts their interviewee's colour.
- `--write`: write the file. Default is a dry run.
- `--force`: overwrite an existing cut list.

### Interview canvas (cards with source links)
- Uses the timeline tool's matcher exactly (clip choice, excerpt pointers, timing sources in the order whisper, then library, then `.srt`, handles, clamping) with no Resolve. The library database is used only when `--db-host`/`--db-name` are given. With neither a library nor `--from-words`, there are no clip names to guess from, so the fuzzy clip-name step never runs and a transcript needs a sibling `.srt`, a map entry or an excerpt pointer to find its clip.
- The cut list's `timing` field is `word` if any clip was timed from whisper or the library, else `srt`.
- Groups become sections, in reading order:
  - an ordinary group becomes an in-cut section titled with the group label, coloured by its position among the in-cut sections (the same 14-colour rotation as the timeline tool's group markers, starting with Blue);
  - a group whose label starts with `Alternates` (case-sensitive) becomes an "alternates" section, not in the cut. Its cards ARE matched and placed in it (unlike the timeline tool, which drops them by default);
  - a group whose label starts with `staged` (any case) becomes a category on the "staged" shelf: the category name is whatever follows `staged` and any separator (with or without a space), so `Staged-- China actually scared`, `staged--polarised` and `Stagedpolarised` name `China actually scared`, `polarised` and `polarised`. Spaces are collapsed and the name cut to 60 characters. A bare `Staged`, or a name that cannot be a heading (contains a comment marker or starts with `#`), goes to the plain shelf. Two groups naming the same category share one shelf section. Shelf sections are written after all in-cut sections, whatever their position on the canvas.
- In addition, for every other canvas group (not alternates, not `(ungrouped)` or `(unnamed group)`, and not already a staged category) an EMPTY shelf category of the same name is added after the cut, in canvas order. (The code can switch this off, but no command-line flag does: UNREACHABLE from the command.)
- Each matched card becomes a cut: clip name, in and out in seconds (6 decimal places, exactly recovering the frames the timeline tool would place), person (the interviewee folder name), ref, the matched text, and the interviewee's colour hex (from the colour map in the canvas's folder, read-only, never saved here).
- Each clip used is recorded once with its rate, its start timecode (written in non-drop spelling) and its pool identifier when known.
- A direction card or unresolvable file embed becomes a note with its text (`(empty card)` if empty).
- An unmatched card becomes an "unmatched" note: its match text followed by `[[<transcript stem>#^<ref>]]`.
- Report counts: matched, low-confidence (anything not found verbatim, confidence below 0.999), unmatched, notes, alternates, staged; each transcript's clip, how it was timed (`whisper`, `library` or `srt`), its error and `via` folder; and every unmatched card with its number, ref, person, first 60 characters of its text and the reason.
- Console: `canvas : <file> (interview)`, a line per transcript, `timing : srt (from .srt cues -- spans at cue granularity; the seconds are exact)` or `timing : word (word timing: <sources>)`, `<m> matched (<l> low-confidence), <u> unmatched, <n> note(s), <a> alternate(s)`, and the unmatched list.

### Montage canvas (cards with `_Clip:` lines)
- A montage card already names its exact clip and span, so no matching is done.
- The span line is `_Clip: <clip name> @ M:SS(.s) - M:SS(.s)` (minutes and seconds; the dash may be a hyphen, en dash or em dash). The card's quote is the last non-empty line above it that does not start with `**`; the speaker comes from a heading line `**<number>. <speaker>**` above it.
- A card with `_Clip: <name> @ M:SS` but no out point becomes an unmatched note `` `<clip>` @ <seconds>  <quote> `` (reported as "no pinned span").
- A source-link (interview) card on a montage canvas becomes an unmatched note `<text> [[<path>#^<ref>]]` (reported as "needs matching (M2)").
- A file-embed card becomes an unmatched note `file card: <file>`.
- A text card with no clip line, or a clip line with nothing above it, becomes a plain note (its text, or `(empty card)`).
- Each clip's rate comes from its whisper corpus sidecar (`fps` field in `<root>\Clips\<clip>\<clip>_words.json`, where root is the canvas's parent when in `Script Docs`, else the canvas folder's grandparent), else `--clip-fps`, else `--fps`. Its start timecode is always `00:00:00:00`.
- Sections, alternates, staged shelf and empty shelf categories: as for interview canvases.
- Console: `<c> cut(s), <n> note(s), <a> alternate(s), <s> not converted`, then each skipped card with its number, reason and detail.

### Writing
- Dry run (default): prints the report and the first 40 lines of the cut list under `--- <target> (dry run, pass --write) ---`, then `... (<n> more line(s); nothing was written)` if longer.
- `--write`: if the target exists and `--force` is not given, prints `<target> already exists -- pass --force to overwrite it (the previous revision is kept under Cuts/.history)` and exits with status 2. Otherwise saves and prints `wrote <target>`.
- The cut list's `written` field is `<ISO date-time> by pipeline.py canvas-to-cutlist`; its `canvas` field is the canvas file name; `title` is the canvas stem.
- Needs from outside: the canvas; transcripts and their `.srt` exports in the vault; optionally whisper sidecars, a reachable project-library database, a `conform.map.json`. No Resolve, no Obsidian.

## Command names and launchers
(source: the top-level add_to_canvas.py, build_canvas.py, story_flow_extract.py, heightfit.py; pipeline.py's command table, read only to confirm names)

- Every tool above is a subcommand of the pipeline's single command: `build-canvas`, `add-to-canvas`, `regroup-canvas`, `reorder-canvas`, `resequence-canvas`, `story-flow-extract`, `interviewee-colors`, `canvas-timeline`, `canvas-to-cutlist`.
- Three tools can also be run by their old top-level file names (`build_canvas.py`, `add_to_canvas.py`, `story_flow_extract.py` in the pipeline folder), with the same arguments, help text and exit status; they exist so instruction files that call them by absolute path keep working. They do nothing of their own.
- `heightfit.py` at the top level is not a command; it only lets other code load the card-height estimator under its old name.
- All tools need Python 3.12 (`py -3.12`) and write console output as UTF-8.

## The story-flow read (an AI assistant's instruction file)
(source: ~/.claude/skills/story-flow/SKILL.md)

- When it is used: the owner asks to check story flow, structure, order or coherence of a canvas or cut, "what is the story here", whether the edit works, how sections connect, or for bridge or transition segments.
- Inputs: two canvases, the CUT (the hand-ordered canvas) and the POOL (the themed canvas holding every paragraph). If the owner names only one, the assistant asks which role it plays and looks for its partner in the same `Script Docs` folder.
- Hard rule: the skill reads and reports; it never edits either canvas. Suggestions are written so the owner can drag the named cards himself.
- Step 1, flatten: runs the story-flow extractor (`story_flow_extract.py` by its absolute path in the pipeline folder) with `--ordered`, `--pool` and the output folder fixed to `E:\Projects\Editing\Transcripts\canvas-theme-picker\work`. The four files described above land there. The assistant must not work out the order from the canvas file itself. It must say in the report whether durations are real (a conform report was found) or estimated, and treat console warnings (duplicate refs, cut cards with no pool match, cards outside every group) as findings.
- Step 2, read everything: the spine end to end in order, then the bench (`_unused.md`) end to end, then `_flow.json`. No helpers working in parallel, no skimming or sampling. Mandarin wording is taken from `_pool.jsonl` when a card's meaning turns on it. Expected sizes: about 50 KB of spine and 120 KB of bench for a 60-minute cut.
- Step 3, the analysis, in five parts, every claim citing `[N]` and `^ref`:
  - A. The story as it currently plays, beat by beat: where the film states its question and whether it answers it, who it is about, whether the argument escalates or flattens into a survey, the act breaks that can actually be found.
  - B. Section by section: its job, how it opens, the state it leaves the viewer in, its runtime, its internal faults (cards out of order, an answer before its setup, a term used before it is introduced, two cards making the same point, a section that peaks and then trails). House style, not to be flagged: a speaker's self-introduction landing after their first substantive line, unless the delay runs to minutes or interrupts an argument.
  - C. The joins: one row per section boundary from `_flow.json`, last card out, first card in, and a verdict of *lands*, *bumps* or *hard cut*, with the reason in terms of what changes across the join (subject, speaker, register, scale, place, time, stance).
  - D. Against the whole corpus: themes with many unused paragraphs that the cut never touches (checking specifically for personal stories, stakes and an ending), unused material that contradicts or answers a claim in the cut, stronger unused versions of a point, and speaker balance (pool paragraphs per interviewee against used ones).
  - E. Mechanical faults: duplicate plays, unresolved direction cards, orphaned interviewer questions, cards with no pool match, ungrouped cards.
- Step 4, transitions: only for joins graded *bumps* or *hard cut* (and internal joins from part B that need one), 2 to 3 ranked candidates each. Preference order: a hinge quote naming both subjects; a widening beat; a cost or stakes beat; a human beat; an interviewer question card from the bench; a non-quote beat (b-roll, archive, narration, location) only when nothing on the bench can do it, specified exactly.
  - Rules: every suggested `^ref` must exist in `_unused.md` (checked by searching the file) and its text is quoted, not paraphrased; prefer a speaker already met; say where it goes (exit ramp, on-ramp or both, "after `[N]`"); prefer moving a card already in the cut over adding one, naming both indexes; name the hinge word or idea; give the card's seconds; say "leave it" where a join works.
  - Each candidate is written as a heading for the join (number, outgoing and incoming sections, the `[N]` either side), a verdict line, then per candidate: kind, speaker, ref, seconds, placement, the quoted text, the hinge, and the cost.
  - NOTE: the transition list ranks an interviewer question card as an acceptable bridge (item 5), while the extractor's own spine and bench headers say interviewer questions are banned from the cut and must never be proposed.
- Step 5, deliver: writes `<Script Docs>\<cut stem> - Story Flow Report.md` beside the conform report. It opens with a header line (date, both canvas paths, card count, unique quotes, runtime, real or estimated durations), then parts A to E, then the transitions. If a previous report exists, the assistant reads it first and notes what changed; it never overwrites one silently (the instruction does not say whether to replace the file or write a new name). In the chat it reports total and per-section runtimes, a two or three sentence verdict, the count of weak joins, the headline structural finding and the report path, never the whole report.
- Re-running: Step 1 is re-run every time; card numbers are never assumed stable between runs.
- Model guidance: use the strongest available model; do not split the read across helpers.
- What a person does between steps: names the canvases; afterwards drags cards in Obsidian by hand from the suggestions.

## Structure notes and the full re-order (an AI assistant's instruction file and its scripts)
(source: ~/.claude/skills/structure-notes/SKILL.md, templates/*, references/example-framing-formosa.md, scripts/*.py)

### When it is used, and the three phases
- Used when the owner shares reading or structure notes about an ordered canvas, or asks to "clean up the inbox", "tidy my notes", "add these to the structure notes", "do the re-order", "reorder the canvas from my notes" or "build V2".
- Three phases, often in separate turns or sessions: 1, tidy raw notes into a structure-notes file; 2, fold new inbox notes in and ask every ambiguity; 3, only when asked, build a NEW re-ordered canvas. Phases 1 and 2 write only the notes file; phase 3 writes only a new canvas. No phase edits an existing canvas.
- Standing rules for all phases: never cut down to a runtime (remove only interviewer questions and chatter; deleting is the owner's job); a ref is a pointer, not a boundary ("run" means that speaker's stretch from the named card onward, and a named card should not move alone by default); a card plays once (two notes wanting one card is a question for the owner); a specific note beats a blanket one; ask, never guess (an interpretation written without asking is marked `*Claude: ...*`); cards go by relevance, intercut as one conversation with no voiceover, following the pipeline's house-style file.

### Where things are (checked every time)
- Episode folder `X:\Vault\<year>\<series>\<Episode>\`.
- SOURCE canvas: `Script Docs\<Episode> - Ordered.canvas` or the newest `Ordered Vn`; if several, ask which. Older ones may end ` (Claude)`; that suffix is never added to a new file.
- POOL canvas: `Script Docs\<Episode> Canvas.canvas` (older: `... Canvas (Claude).canvas`).
- Notes file: `Script Docs\<Episode> - Structure Notes.md`; read in full and continued if it exists, otherwise started from the template.
- The project memory note for the episode, if any.
- Scripts in the skill's `scripts` folder, run with `py -3.12`; they load the pipeline from the fixed path `E:\Projects\Editing\Resolve\MulticamPipeline`.

### The card lookup tool
(source: scripts/canvas_query.py; read-only)
- `canvas_query.py <canvas> sections`: every section in reading order with card count and estimated minutes, then the total card count.
- `canvas_query.py <canvas> find <pattern> [<pattern> ...]`: cards whose English or Chinese matches any of the regular expressions, case-insensitive.
- `canvas_query.py <canvas> section <label prefix> [--who <text>] [--full]`: one section's cards (every section whose label starts with the prefix, any case), optionally only speakers whose name contains the text.
- `canvas_query.py <canvas> run <ref> [--max <n>] [--full]`: a "run": the cards from that ref onward, in the same section and by the same speaker, stopping at the first card by someone else or after `--max` cards (default 12). Refusal `no card with ^<ref>`.
- `canvas_query.py <canvas> link <ref> [<ref> ...]`: the wikilink to use in the notes, `[[<transcript path>#^<ref>|^<ref>]]`, or `!! ^<ref> not on the canvas`.
- Card line format: `[n] <section, first 34 chars> | <speaker> | ^<ref> | ~<seconds>s [QUESTION] | <English>`. Without `--full`, English over 220 characters is shortened to its first 150 and last 60 characters. A card with no English shows `(no English)` and the first 60 Chinese characters.
- Speaker comes from the `Interviewees/<Name>/` part of the card's link; seconds use the story-flow extractor's estimate; numbering is the canvas reading order (the numbers a re-sequence plan uses).
- Any other command, or fewer than 3 arguments, prints the usage text.

### The ref expander
(source: scripts/expand_refs.py)
- `expand_refs.py <canvas> <notes.md>`: replaces each draft shorthand `{{ref}}` or `{{XX:ref}}` (`XX` is 1 to 4 letters, a speaker reminder, dropped) with the card's wikilink `[[<transcript path>#^<ref>|^<ref>]]`, and rewrites the notes file (LF line endings) if anything changed. Shorthand for a ref not on the canvas is left as it is and listed: `!! not on the canvas, left as shorthand: <refs>`. Prints `expanded <n> ref(s)`.
- Then, and alone with `--check`, it lists every `#^ref|` linked in the notes that is no longer on the canvas: `linked refs checked: <n>; missing from canvas: <m>` and one `!! ^<ref>` line each.
- Only refs exactly 6 characters long are recognised, in both the shorthand and the check.

### Phase 1: tidy raw notes
1. Read the raw notes (pasted or a named file) and the SOURCE's section list.
2. Resolve every reference to a card: explicit refs, quotes (with `find`), "X's part", "run from", "the end"; check each quote really is on its card.
3. Write the notes file in the template's layout: header (episode, canvas name, "Read so far", "Last tidied", a statement that nothing has been done on the canvas yet, a legend, and that `*Claude:*` lines are the assistant's); **Rules for the re-order** (the eight standing rules: relevance decides; order inside a section is whatever strengthens its argument; every unnamed card also moves by relevance; strong transitions first, no voiceover; intercut as one conversation; expect to splice a 所以 / 然後 / 但是 between cards; specific beats blanket; a ref is a pointer) plus episode rules; **The shape** (acts and numbered beats with what each does, opens on, is built from and lands on); **Moves** (checkboxes, grouped by the section the card sits in now, named cards only); **Lines to build on**; **Open**; an empty **Inbox** with its one-line format hint (`12 - Speaker ^xxxxxx - move to ... / good out for ... / cut`); **Raw notes, as written** (verbatim and dated). The owner's wording and the strength of his imperatives are kept; undecided notes go to Open.
4. Draft card references as `{{XX:ref}}`, then run the ref expander.
5. Ask the ambiguities (protocol below), fold the answers in, update "Read so far" and "Last tidied".

### Phase 2: clean up the inbox
1. Read the whole notes file, the Inbox, and any extra notes file named.
2. Find each inbox line's cards (`find`, `run`, `section`) and decide where it lands in the shape, the moves and the lines.
3. Collect every ambiguity first: a quote or card not found; a ref not on the canvas; a vague destination; two notes wanting one card; a note contradicting an earlier decision or the shape; whether a run continues past a topic change; a card whose content does not fit the section it was filed under.
4. Ask them all, write the answers in as the owner's decisions; undecided ones go to Open.
5. Move processed inbox lines to "Raw notes, as written" with the date; leave the Inbox empty with its hint.
6. Run the ref expander again; report what moved where, what is now Open, and which readings were the assistant's own.
- Question protocol: the assistant's multiple-choice question tool, up to 4 questions per call, as many calls as needed. Each question names the cards by ref and quotes them, states the consequence, and offers 2 to 4 concrete options plus "keep it open" where fair. If the owner is mid-read, only what he has written is asked about and unread sections are noted under Open. The reference file gives worked examples.

### Phase 3: the full re-order (only when asked)
- **Scope questions first**, in one batch, for whatever the notes do not settle: where staged groups go (default `Staged -- <section>` directly BEFORE each section); how heavily to stage (default light); what happens to a cold open or copied cards (default: copies dropped, originals stay); special bins (a jettisoned theme, personal stories, self-introductions); whether sections are still unread. The assistant also says how many helper agents it will need and the rough cost (the reference run: 2,166 cards took 35 agents).
- **Work folder** `E:\Projects\Editing\Transcripts\canvas-theme-picker\work\<Episode>\reorder-<YYYY-MM-DD>\` (called R), kept outside the scratch area so steps can be re-run and the trail survives.

#### Step 1: the skeleton and the prep
- The assistant writes `R\sections.json`: episode, `source`, `pool`, `notes`, `out` (the new canvas, normally `<Episode> - Ordered V2.canvas`), `date`, `question_groups` (label prefixes of source groups holding interviewer questions, e.g. `Uncat`), `question_bin` (default label `Staged -- Interviewer questions and chatter`), `drop_groups` (label prefixes whose cards are dropped, e.g. cold-open copies `00`), `intro` (default true), `sections`, `staged_only`, `whole_group`, `force`.
- Then runs `prep_reorder.py <R>` (source: scripts/prep_reorder.py), which needs `source` and `notes` in `sections.json` and writes into R:
  - `cards.jsonl`: every card of the SOURCE in reading order with `n` (its number, the only identifier agents ever output), `sec` (its current section), `who`, `ref`, `q` (question), `en`, `zh`, `s` (estimated seconds);
  - `chunks\chunkNN.md`: the body cards (those not in question or drop groups, matched by case-insensitive label prefix) cut into reading chunks of whole sections of about 45,000 English characters each. A section up to 63,000 characters (1.4 times the target) stays whole; a larger one is split into pieces of at least 45,000. Each chunk lists `## OLD SECTION <label>` headings and cards as `[n] <who> ^<ref> ~<s>s` with their English (or `(no English)` plus 80 Chinese characters);
  - `structure_notes_plain.md`: the notes file up to `## Inbox`, with wikilinks reduced to bare `^ref`;
  - `STYLE.md`: a copy of the pipeline's house-style file from its fixed path;
  - empty folders `assign`, `targets`, `seq`, `splices`, `verify`.
  - It prints each chunk's card count, English characters and first and last section numbers, and a summary of cards, body cards, excluded cards, cards with no ref, and chunks.

#### Step 2: the brief
- The assistant turns the notes' shape into target sections and writes `R\BRIEF.md`: a header paragraph (the film, its runtime, no voiceover, one conversation, what was wrong with the source canvas, the notes are the authority); the `cards.jsonl` fields; one line per target section (`KEY`, `NN - Title`, what it is for, what belongs in it, fixed ways in and out, which notes beat it comes from); staged-only targets (e.g. `PS` personal stories, a jettisoned theme) and `INTRO` (a speaker's single best self-introduction, at most one per speaker, placed after their first substantive line); and the rules for placing a card (relevance decides; named cards are fixed and pointers; specific beats blanket; light staging, with a staged card still given the section it would have been in; episode overrides).
- Mirrors it into `sections.json`: `sections` as `{"key", "label" ("NN - Title"), "named": [refs]}` in film order; `staged_only` as `{"key", "label"}`; `whole_group` sending an old section (label prefix) to a target, e.g. `{"36": ["AI", "s"]}`; `force` per-ref overrides, e.g. `{"<ref>": ["E4", "s"]}`. A ref named in two sections must be put to the owner.

#### Step 3: placement
- Default ONE helper agent reads every chunk and all the notes and writes one `assign\chunk01.json` covering every body card; one agent per chunk only when the cards and notes clearly exceed one context (estimate about 1 token per Chinese character, 4 English characters per token).
- The agent prompt is the placement template filled with the work folder, the chunk name and all keys. The agent reads the brief, the style file and the plain notes, then its cards, and for every card writes `[n, "KEY", "k" or "s"]` (keep or staged), judging by what the card says; named cards are fixed and their neighbours judged; staging is light; staged-only keys are always staged; INTRO is kept and at most one per speaker. It checks its own JSON parses and that the count matches, touches nothing outside R, and reports a tally and up to ten hard calls. Agents run in parallel in the background.
- Then `merge_assign.py <R>` (source: scripts/merge_assign.py):
  - Valid keys: every section key, every staged-only key, and `INTRO` when `intro` is on.
  - Refusals (stop with a message, nothing written): a ref named in two sections (`^<ref> is named in both <A> and <B> - a card plays once; ask Alex`); an assignment with an unknown key or a value other than `k`/`s` (`<file>: card <n> has bad entry ...`); a card assigned twice (`card <n> assigned twice`); any body card still unassigned after the fill-in below (`not complete - re-run the placement agent for the chunk(s) holding the missing cards`, printed after the tally).
  - Body cards no agent placed are filled from `whole_group` by their old section's label prefix.
  - Cards assigned outside the body (question or drop groups) are only listed (`not body`), not refused.
  - Then, in order: staged-only keys are forced to staged; INTRO forced to kept; a card the notes name is forced into its named section as kept (each override listed); a `force` entry by ref wins over everything.
  - Warnings: named refs that are not body cards; a speaker with more than one INTRO card (`keep the best, restage the rest`); the speakers with no INTRO card.
  - Tally per key: kept, staged, kept minutes; totals.
  - Writes `assignment.json` and `targets\<KEY>.md` for every key: the kept cards in source order, named ones marked `**NAMED IN THE NOTES**`, each with its old section number, its English, and the first and last 14 Chinese characters (so sequencers can see hooks).
- The assistant re-runs the agent for any chunk with missing cards and reads the tally (a section far over its share of runtime needs a note to its sequencer; a speaker with no INTRO is fine).

#### Step 4: the row and sequencing
- The assistant writes `R\SEQUENCE.md`: a table with one row per section (key, section, way in, way out), every in or out the notes fix marked **FIXED**, every other row saying what the section must hand to the next, and the next section's fixed first card quoted.
- Sequencing agents, in parallel, each on one section or two small neighbouring sections (about 120 cards or fewer), using the sequencing template filled with the runtime, keys, files and any extra wishes. Each reads the style file, the plain notes, the brief, the sequence table and its target files, then writes `seq\<KEY>.json` as `{"order": [...], "stage": [...], "notes": "<up to 12 short lines>"}`: building the section's argument with no priority on original order, intercutting speakers as replies, honouring fixed ins and outs, moving from setup to landing without giving away the next section early, staging only dead cards, unplayable fragments or clearly weaker repeats, never dropping a card, and requesting any splice in the notes as `SPLICE <n>: <what plays>`. Each checks its own file.
- Then `build_plan.py <R>` (source: scripts/build_plan.py):
  - Refusals: a section with no sequence file; a duplicate in an order; a card both ordered and staged; order plus stage not equal to the cards placed there (`re-run the sequencing agent for those sections`); and, at the end, a plan that does not cover the canvas exactly once (`plan does not cover the canvas exactly once: duplicates ... missing ...`).
  - Each INTRO card is inserted right after the end of its speaker's first consecutive block of cards in the film (within one section). A speaker with no line in the film has the intro staged in the first staged-only bin (or, if there is none, in the first section's staged group), with `no line in the film, intro staged: <who>`. Only one INTRO per speaker survives; a second one is left unplaced and makes the coverage check refuse.
  - Group order of the plan: for each section in film order, `Staged -- <label>` (its staged cards, in source order) directly before the section (in its playing order); then each staged-only bin that has cards; then the question bin (every card of the question groups); `drop` = every card of the drop groups.
  - Writes `plan.json`; prints each group's cards and minutes, the dropped count, and the playing (unstaged) minutes.
- The assistant reads every join (last two cards of a section, first two of the next) and may fix a bad hand-off by editing that section's sequence file, saying so in the report.

#### Step 5: splices
- Splice agents, each on 4 to 6 neighbouring sections, using the splice template. The house rule: when only part of a card plays, the part that plays is wrapped in `==...==` (an Obsidian highlight) in the card's ENGLISH text; the Chinese line is never touched; several highlights per card are allowed. Each agent turns every splice the sequencer's notes ask for into exact verbatim substrings of the card's English (whole sentences or clauses; a splice given in Chinese is mapped to the English), includes optional splices only when the join depends on them, invents none, ignores staged cards, writes `splices\sN.json` as `[{"n", "play": [...], "why"}]`, and verifies with a small script of its own (kept in `splices`) that each play string occurs exactly once and that one card's highlights do not overlap.

#### Step 6: build, write, verify
- `make_source.py <R>` (source: scripts/make_source.py):
  - Refusal: if any card's ref is no longer on the card with the same number (`card numbering no longer matches the canvas at [<n>] - re-run prep_reorder.py`).
  - Applies the highlights to a SCRATCH copy of the source, `R\src_with_flags.canvas` (the source itself is never written): each play string is found with flexible whitespace; one found other than exactly once is skipped with `!! [<n>] play text found <k> times: ...`; a card that already has any `==` highlight is left alone entirely (the owner's own splice wins); a highlight never crosses a line break (each line is wrapped separately). Prints the applied and skipped counts.
  - Adds one yellow (`#ffd500`) flag card per section, in a new group `zz flags (scaffold)` placed 1,000 px right of everything (cards 1,100 px right, from y = 100, 40 px apart, the canvas's most common card width, heights from the card-height estimate). Flag text: `⚑ **TRANSITION / FLAG**`, the section label in capitals, the sequencer's notes, and `_Re-ordered <date> from the structure notes; old card numbers shown as their ^refs._`. In the notes, `[n]` numbers become `^ref`, and bare 2 to 5 digit numbers become `^ref` only when that card belongs to this section; internal section keys become `section NN`.
  - Refusal: if adding the scaffold shifted the numbering of the existing cards (`adding the flag scaffold moved the card numbering - stop and investigate`).
  - Writes `R\plan_final.json`: the plan with each section's flag card first in that section. Warns if internal keys remain in any flag text.
- Then, from the pipeline folder: the re-sequence tool as a dry run into `R\out_dryrun.canvas`, then for real into `<OUT>`; then the story-flow extractor on the new canvas with the pool, into `R\verify`. The scaffold group is not named in the plan, so the re-sequence tool drops it (its flag cards travel into their sections).
- Never overwrite: if `<OUT>` exists, use the next `Vn`.
- Verify: no duplicate cards; no interviewer questions in the cut except one the notes explicitly name (forced in `sections.json`, passed to the extractor as `--allow-question`, listed in the report); the unused-pool count equal to the source canvas's; flag cards carrying no internal keys.

#### Step 7: close out
- Add a status block at the top of the notes (what was applied, the new file, a map from beat to new section numbers), leaving the Moves checkboxes as they are.
- Update or create the episode's project memory (what was built, how, choices not yet confirmed).
- Report to the owner: a table of new sections by act; staged-group sizes; that every fixed in/out and named card was honoured; flag and splice counts; and under **Calls for you to check** every choice the agents made that he had not, every place his order was changed and why, splices that could not be made, and translation slips (fixed only with clear evidence from the Chinese, and listed).
- Don'ts: never edit the SOURCE, the POOL or any existing canvas; never cut to runtime or stage heavily; never resolve an ambiguity silently; never let a named card travel alone when its neighbours belong with it, nor drag along neighbours that drift off-topic; never keep speakers' runs together for their own sake.
- What a person does between steps: writes the raw notes while reading the canvas; answers every question batch; asks for the re-order explicitly; answers the scope questions; checks the "Calls for you to check" list; then works in the new canvas in Obsidian.
- The worked example file records one real run for scale (16 interviewees, 2,166 source cards in 37 sections, about 9.5 hours; output 26 sections, 1,511 playing, 629 staged, 146 splices; 13 placement, 16 sequencing and 6 splice agents), excerpts of a brief and a sequence table, the owner's corrections made during that run, and examples of good questions.

## What each tool needs from outside itself
(source: all files above)

- **build-canvas**: a paragraph file and an assignments file (from the transcript tools and the canvas-sorter skill); writes the colour map beside the canvas. No Resolve, no Obsidian.
- **add-to-canvas**: a transcript with `^ref` blocks (from the transcript finalising step) inside a `...\vault\...` path so links come out vault-relative; the canvas closed or saved in Obsidian; optional reflow settings.
- **regroup-canvas**: the episode's paragraph file (cards are found by exact text, so cards whose text was edited in Obsidian are not found); every card inside a group.
- **reorder-canvas**: the canvas only; every card inside a group; unique group labels.
- **resequence-canvas**: a plan file written against the canvas's current numbering.
- **story-flow-extract**: the ordered and pool canvases; optionally the conform report beside the ordered canvas.
- **interviewee-colors**: an episode folder with `Interviewees` and `Script Docs`; Resolve open with a project and a bin of multicam clips (unless `--no-resolve`); an open timeline for `--timeline`.
- **canvas-timeline**: Resolve open on the target project with the clips in the media pool and its project database reachable (or `--from-srt`); transcripts and `.srt` exports in the vault; optionally whisper sidecars, `conform.map.json`.
- **canvas-to-cutlist**: the canvas and the vault's transcripts and `.srt` files; optionally whisper sidecars, the project-library database, `conform.map.json`. No Resolve.
- **story-flow skill**: the owner names the canvases; the fixed work folder exists or is created; the owner drags cards afterwards by hand.
- **structure-notes skill**: the vault at `X:\Vault`, the skill scripts and the pipeline at fixed paths, the house-style file, helper agents, and the owner answering questions between steps.

## Looks redundant or overlapping

- Four different rules decide which group a card is in: top-left corner inside the group (reading order, carve-out, re-order, story pool), card centre inside the group (add-interview), card wholly inside exactly one group (add-interview's final check), and exact column x offset versus a 20 px column tolerance for reading order inside a group (carve-out versus the readers).
- Three places hold an interviewee colour map, and which one a tool uses depends on where the canvas sits: build-canvas and canvas-timeline use the canvas's own folder; interviewee-colors uses `<episode>\Script Docs`; add-to-canvas ignores the map and picks colours from the cards already on the canvas. They agree only when the canvas lives in `Script Docs`.
- "Alternates" is handled two ways: canvas-timeline drops any card whose group label CONTAINS `Alternates` (unless `--include-alternates`); canvas-to-cutlist keeps them, matched, in an alternates section when the label STARTS with `Alternates`.
- Group colours on the timeline (by position among all groups) and section colours in the cut list (by position among in-cut sections only) are the same rotation counted differently, so they diverge once a staged or alternates group sits mid-row.
- Personal Stories and Ending are recognised case-insensitively by build-canvas but case-sensitively by reorder-canvas `--arc`.
- canvas-timeline and canvas-to-cutlist both turn an ordered canvas into a cut by the same matcher; a cut list opened in Timeline Cards can also be conformed to Resolve (other sections), so there are two routes from canvas to timeline.
- canvas-to-cutlist's `--from-words` overlaps with the default (whisper sidecars are asked first without it); its only extra effect is fuzzy clip-name guessing and clip facts from the whisper corpus.
- Story-flow extraction, canvas_query `sections`, resequence's per-group minutes and build_plan's tally each compute their own runtime estimates from the same text-length rule.
- The structure-notes run-time helpers (`canvas_query.py`, `prep_reorder.py`) duplicate the paragraph/question/language splitting already in the extractor by importing it, but keep their own speaker rule (`Interviewees/<Name>/` in the text) beside the extractor's (folder of the link).
- Three in-place canvas editors (add, carve, re-order) each carry their own copy of the backup, overlap, containment and coverage checks.
- interviewee-colors `--timeline` and canvas-timeline's tinting both colour timeline cuts by interviewee.

## Claims the code does not back

- regroup_canvas.py's description says build_canvas lays groups out "strongest-first"; build_canvas keeps the assignments file's order within role bands and never sorts by size.
- regroup_canvas.py says groups the edit does not touch "keep their positions"; the whole row is re-laid at the plugin's group gap on one baseline, so any group not already packed that way moves.
- regroup_canvas.py says cards not in the paragraph pool are "left where they are"; they stay in their group but are re-packed or shifted with it.
- canvas_to_cutlist.py's description says a group becomes a section "coloured Blue"; sections take a rotating 14-colour sequence, only the first is Blue.
- canvas_timeline.py calls `Alternates` a "group label prefix"; the command excludes any group whose label merely contains it.
- canvas_timeline.py says "a dry run stays read-only"; it is read-only for the colour map, but the conform report is written on every dry run unless `--no-report`.
- interviewee_colors.py presents its command as a dry run by default; the colour map file is saved on every run, dry or not.
- story_flow_extract.py's `--out-dir` help says "where the three files go"; it writes four.
- prep_reorder.py says `sections.json` must hold `question_groups` and `drop_groups`; both are optional in the code.
- build_plan.py and make_source.py call themselves steps 5 and 7; the instruction file runs them as steps 4 and 6.
- canvas_to_cutlist.py's overwrite message promises the previous revision is kept under `Cuts/.history`; that is the cut-list saver's behaviour (another section) and was not verified here.

## Could not determine

- Whether `.srt` exports carry a 01:00:00:00 start; in `--from-srt` mode the clip start is assumed to be 3600 s and in points are clamped to it, which would push every cut to the clip head if the subtitle times start at zero.
- What Resolve does when `canvas-timeline --apply` is given a timeline name that already exists (nothing in this code checks).
- How `cutlist.save` versions or backs up an existing cut list, and the exact cut-list text written (Timeline Cards section).
- How clip names are matched to interviewee folders in interviewee-colors (`pick_folder`, transcript tools section).
- What the reflow plugin itself does beyond the settings read here; these tools assume its layout matches their Python copy.
- Whether the story-flow report is meant to replace the previous report file or be written under a new name; the instruction only says never to overwrite silently.
