# Brief for a joins fixer

Stays behind. You repair ONE piece of the specification so that it no longer
disagrees with the other pieces.

## What this is

The specification was written in 27 pieces by 27 writers, each of whom saw
only their own piece. Readers have since checked every place where one piece
leans on another and listed the disagreements. You are given the ones that
name your piece. Your job is to change your piece, and only your piece, so
that each of them is closed.

Read, in this order:

1. `E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\_trace\WRITER_BRIEF.md`:
   the rules the text of a piece is written under. They bind you exactly as
   they bound the writer: describe the job, not the arrangement; no tool,
   file, route or setting name of the present build; no word that admits a
   past; no long dash; what a person sees and touches is kept.
2. `...\spec\OWNER_REQUIREMENTS.md`: the owner's decisions. It outranks
   everything.
3. Your piece, `...\spec\<piece>.md`, completely, and its trace
   `...\spec\_trace\<piece>.md`.
4. Your bundle, `...\_raw\join-fixes\<piece>.md`: every finding that names
   your piece.

## What a finding is

Each finding has: the two places that disagree (`From` is a behaviour of one
piece, `Here` is a heading of the piece named in the note under it), what
each says, what settles it (`Settled by`), and the `Fix`: which piece
changes, and to what. Where a line `THE LEAD'S RULING` is present, it
outranks the `Fix` line.

Your piece may be the `From` side, the `Here` side, or merely mentioned.
For each finding, work out from the Fix (or the ruling) whether YOUR piece
is one that changes:

- The Fix names your piece and says what it does: do that.
- The Fix says another piece changes: change nothing. Say so in your trace.
- The Fix says "one piece holds it and the other points to it" without
  saying which: the HOME is the piece the finding calls "Here" (the piece
  whose sub-topic it is). If you are the home, keep your full description
  and make sure it carries every detail of the other side that is not in
  dispute (open the other piece to read it). If you are not the home,
  replace your full description with one sentence that says what happens in
  a few words and points to the home.
- The Fix depends on an answer nobody has given ("if the owner says ...")
  and no ruling settles it: change nothing and say so in your trace.

## How to change the text

- Make the smallest change that closes the finding. Do not rewrite a
  behaviour because you would have written it differently.
- A pointer is written the way your piece already writes them: "(see <the
  capability's name>: <sub-topic>, "<heading>")". Open the other piece and
  copy the heading exactly as it stands today.
- Do NOT rename, remove or add a `##` heading. Do not rename a `###`
  heading unless the Fix says to, because other pieces and traces point at
  headings by their exact words. If you must rename or remove a `###`
  heading, change every line of your own trace that names it, and list it in
  your last message so pointers elsewhere can be repaired.
- When a behaviour goes entirely, its coverage lines in your trace become
  `left out: settled by the joins (2026-11-24, <target piece> F<n>)`.
- When you add a behaviour (a `###` heading) that the Fix asks for, write it
  the way the piece writes the others, with its Who / Ways in / On its own /
  By hand / Setting lines where they apply.
- Numbers, limits and wording a person is shown: use the side the finding
  says is right, word for word. Never invent a sentence a person is shown;
  if the right wording is not given anywhere, describe what the person is
  told without quoting it.
- The `#### Lessons` lines stay as they are, unless a change of yours means
  a lesson is now met or no longer met; then move its id between the lines.

## What to record

Add to the END of your trace file one section (or extend it if it exists):

```
## Joins settled

- <target piece> F<n> | changed: <heading> ; <heading> | <what changed, in a few words>
- <target piece> F<n> | no change here: <why: the other piece changes / waits for the owner / already agrees>
```

One line for every finding in your bundle.

## Before you finish

From `E:\Projects\Editing\ccsync` run

    python docs/rebuild-spec/tools/check_spec.py <piece>

and repair your piece until it prints no problems. (Run it with
`PYTHONIOENCODING=utf-8` set.) It must still report the same number of
items; you are not adding or dropping inventory items, only text.

## Rules

- Change two files only: `spec/<piece>.md` and `spec/_trace/<piece>.md`.
  Never edit another piece, even to fix an obvious error there: say it in
  your last message instead.
- Do NOT start sub-agents of your own.
- Do not read the product's code or any file outside
  `E:\Projects\Editing\ccsync\docs\rebuild-spec`.
- Temporary files, if any, start with the prefix you were given.
- Your last message is at most ten lines: how many findings, how many
  changed your piece, any heading you renamed or removed, and anything in
  another piece that you saw is wrong and could not fix.
