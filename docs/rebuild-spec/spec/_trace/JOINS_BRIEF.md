# Brief for a joins reader

Stays behind. You are checking one seam of a specification that was written
in 27 pieces by 27 writers, each of whom saw only their own piece.

## What this is

`E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\<piece>.md` are the 27
pieces of a specification for a product (a video studio's sync, dashboard,
Timeline Cards editor, Footage Sorter and more). It describes only what the
product does for a person: what they can do, what happens on its own, what
they are told, what is refused. A different session will build the product
from it and will see nothing else, so where two pieces disagree it will have
to guess. Your job is to find the disagreements. You fix nothing.

Where a behaviour of one piece depends on something another piece describes,
its writer recorded a **join**: "my behaviour X leans on sub-topic Y of that
other piece, for Z". Nobody has yet checked that the other piece really says
what the leaning piece assumes.

## What you are given

- Your **target piece**: `...\spec\<piece>.md`. Read it completely first.
- Your **bundle**: `...\_raw\joins\<piece>.md`. Every join aimed at your
  target, numbered `J1`, `J2`, ..., each with the full text of the behaviour
  that leans on it (quoted with `>`), the sub-topic of your piece it names,
  and what the writer said it leans on.
- `...\spec\OWNER_REQUIREMENTS.md`: the owner's decisions about the new
  build. Read it before the bundle. It outranks any piece.

You may also open, when you need to settle which side is right:

- any other piece under `...\spec\` (to read around a leaning behaviour);
- `...\knowledge-base\<capability>.md`: lessons from real use, each with a
  kind. A lesson of kind `ruling` is the owner's decision and outranks a
  piece;
- `...\decisions\page-NN-<piece>.md`: questions put to the owner. A line
  starting `- Answered by the owner` or a page headed `ANSWERED` is his
  word, and the latest date wins.

Do not open anything outside `E:\Projects\Editing\ccsync\docs\rebuild-spec`.
In particular do not read the product's code: the specification has to stand
on its own, and "the code does it this way" settles nothing here.

## What to do with each join

Read the leaning behaviour's text, then find what your target piece says on
the same matter: first under the sub-topic the join names, then anywhere
else in the piece (search it; the writer may have filed it elsewhere). Then
decide:

- **fine**: the target says what the leaning behaviour assumes, or says more
  without disagreeing. A difference in how much detail each gives is fine. A
  pointer ("see Sync: ...") whose target exists is fine.
- a **finding**, of one of four kinds:
  - `contradiction`: both cannot be true for a person. Different numbers or
    limits; a different sentence for the same message; a different answer to
    who may do it; a step one piece requires and the other says does not
    exist; a state one piece shows and the other says is never shown.
  - `missing`: the leaning behaviour relies on something your target does
    not say anywhere (a page, a setting, a state, a rule, a message). Check
    the whole piece before you say this.
  - `differs`: the same thing under two names, or described so differently
    that a builder would not know they are one thing (a page, a button, a
    setting, a state called one thing here and another there).
  - `said twice`: both pieces describe the same behaviour in full, with no
    disagreement yet, so the next edit to one will make them disagree. Only
    report this when both are full descriptions, not a description and a
    one-line mention.

While you have both texts open, also report any contradiction between them
that the join did not name. These are often the most valuable ones: the
writers recorded what they knew they leaned on, not what they silently
assumed. Give it under the join where you noticed it.

Be strict about real disagreements and relaxed about style. Do not report
wording you would have written differently, or one piece being terser.

## Which side is right

For every finding, say what settles it:

1. `OWNER_REQUIREMENTS.md` or an answered decision page: quote the line.
2. A lesson of kind `ruling`: give its id.
3. Any other lesson: give its id (weaker; say so).
4. Nothing: write `the owner must say`, and put the question in one plain
   sentence about what the product does for a person. Never an engineering
   question (which tool, how many processes): those are not his to answer.

Then say in one sentence which piece should change and to what. If both
should, say both.

## What to write

One file, `...\spec\_trace\_joins\<piece>.md` (make the folder if it is not
there), in exactly this shape:

```
# Joins aimed at <piece>

## Checked

- J1 | fine
- J2 | F1
- J3 | F1, F2
- J4 | fine

## Findings

### F1: <one line saying what disagrees, in plain words>
- Kind: contradiction
- From: <leaning piece> / <heading of the leaning behaviour>
- Here: <heading in the target piece, or "nowhere">
- From says: "<the words, quoted exactly, as short as carries the point>"
- Here says: "<the words, quoted exactly>" (or: nothing)
- Settled by: <the quote or id that settles it, or: the owner must say: <question>>
- Fix: <which piece changes, and to what, in one sentence>
```

Every `J` of your bundle has one line under `## Checked`: `fine`, or the
findings it led to. Every finding has all seven lines, each on one line. A
finding may be named by several joins.

Then run, from `E:\Projects\Editing\ccsync`:

    python docs/rebuild-spec/tools/build_join_bundles.py --check

and repair your file until your piece is not listed with problems (other
pieces "not checked yet" is normal).

## Rules

- Change no file but your own output. Do not edit any piece.
- Do NOT start sub-agents of your own.
- If you write temporary files, start their names with the prefix you were
  given.
- Your last message is at most eight lines: how many joins, how many fine,
  the findings by kind, and the two or three that matter most.
