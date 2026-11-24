# Brief for a joins settler

Stays behind. You rule on a batch of disagreements between pieces of the
specification, so that fixers can then repair the pieces.

## What this is

Read `E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\_trace\JOINS_BRIEF.md`
first: it says what the specification is, what a join and a finding are, and
where the owner's word is written down. Readers following that brief found
373 findings across 27 pieces. Each finding says what two pieces say, what
settles it, and a Fix. Two things remain before anyone edits a piece:

- The readers marked 168 findings "the owner must say". Most of those do
  not need him: they are two sentences for one message, two names for one
  thing, or a point that a ruling, an answered question or the guiding
  principle settles once somebody looks further than the reader did. Only a
  real fork in what the product does for a person goes to him.
- The same disagreement was often found from both sides by two readers, who
  did not always agree on the fix, and a few readers settled a finding by an
  older lesson without knowing a later answer of the owner's.

You are given a batch of findings (`...\_raw\join-settle\<batch>.md`) and
write one ruling line for every one of them.

## What outranks what

1. The owner's latest word: `spec\OWNER_REQUIREMENTS.md`; `DECISIONS.md`
   (pages 1 and 2 with his answers; two answers on page 2 go against older
   rulings); the answered decision pages in `decisions\` (where a page says
   every recommendation was accepted, the recommended option is his answer).
   An answer of 2026-11-24 outranks any lesson, ruling or not.
2. A lesson of kind `ruling` in `knowledge-base\<capability>.md`.
3. Any other lesson there.
4. The guiding principle, in his words: "the most elegant option with the
   least moving parts every time". One way to do each thing; one place a
   thing is described.

Search before you rule. The reader looked at a few sources; you look at all
of them: search every `knowledge-base\*.md` and every `decisions\*.md` for
the subject's words, and open the other piece. Quote what you find.

## The rulings

One line per finding, in exactly this shape:

```
<target piece> F<n> | <verdict> | <note>
```

`<target piece> F<n>` is the finding's own name as the batch gives it. The
verdicts:

- `apply` : the reader's Fix is right as written. Note: empty, or the
  evidence if the reader had marked it for the owner and you found what
  settles it.
- `instead` : the Fix is wrong, or leaves the choice open, or the reader
  passed it to the owner and you can settle it. Note: say exactly which
  piece changes and to what, in one or two sentences a fixer can act on,
  and what settles it (quote or id).
- `home <piece>` : the same thing is described twice, or under two names,
  or with two wordings, and nothing but tidiness is at stake. `<piece>`
  keeps the full description, its name and its wording; every other piece
  points to it. Note: which name or sentence wins, if they differ.
- `same <target piece> F<n>` : the same disagreement as another finding (in
  your batch or not); it is ruled there. Rule the pair ONCE, on the finding
  that states it best, and make sure that ruling covers every piece the two
  findings name.
- `code` : it turns on a plain fact about what a person sees in the product
  as it runs today (which of two sentences is really shown, which number is
  real), and nothing written settles it. Note: exactly what to look up.
  Use this sparingly; you may not read the code yourself.
- `owner` : a real fork in what the product does for a person, which no
  word of his, no lesson and no principle settles. Note: `Q<n>` , the number
  of the question you write for him (below).
- `drop` : not a disagreement after all. Note: why.

How to choose:

- **Two wordings of one message, two names for one page, button, setting or
  state:** never the owner. `home`. The home is the piece whose subject it
  is (usually the finding's "Here" piece; the dashboard's pieces for a page
  of the dashboard, the app's piece for the app's own windows and menu, the
  Timeline Cards editor's pieces for anything on the editor's screen, whose
  wording crosses exactly). All pieces must then use the home's words.
- **A number, limit, default or rule that differs:** find his word or a
  lesson. If one side is a lesson's Must, that side wins (`instead` or
  `apply`). If neither has backing and the difference does not change what
  a person can do, pick the side of the home piece (`home`). If it does
  change what a person can do and nothing settles it: `owner`.
- **Missing** (a piece leans on something the other never says): if a
  ruling, an answer or a lesson supports the thing, the home piece adds it
  (`apply` or `instead`). If nothing supports it and it is small, the
  leaning piece drops the claim (`instead`). If it would be a new thing the
  product does: `owner`.
- **A thing he cut** that a piece still describes: the piece drops it
  (`instead`, quoting the answer).
- **The owner** only when you could explain to him, in one plain sentence
  about what a person sees or can do, what he is choosing between, and you
  cannot tell which he would pick. Expect well under a quarter of the
  findings marked for him to really need him.

## Questions for the owner

After the rulings, for every `owner` verdict, one question (several
findings may share one question):

```
### Q<n>: <the question, in one plain sentence, about what the product does for a person>
- Findings: <target piece> F<n>, <target piece> F<n>
- The two sides: <what each piece says, in a sentence each, in plain words>
- Options: A: ... B: ...
- Recommend: <A or B>, because <one sentence; by the guiding principle where nothing else decides>
- What you would notice: <one sentence>
```

Plain words only: no file, route or setting name of the present build, no
lesson ids in the question itself, no engineering question (how something
is built is never his to answer).

## What to write

One file, `...\spec\_trace\_joins\_rulings\<batch>.md`:

```
# Rulings: <batch>

## Rulings

<one line per finding>

## Questions for the owner

<the questions, or "none">
```

Every finding of your batch has exactly one ruling line.

## Rules

- Change no file but your own output. Do not edit any piece.
- Do NOT start sub-agents of your own.
- Do not open anything outside `E:\Projects\Editing\ccsync\docs\rebuild-spec`,
  and never the product's code.
- Temporary files, if any, start with the prefix you were given.
- Your last message is at most eight lines: how many findings, how many by
  verdict, how many questions for the owner, and anything you ruled against
  a reader that the lead should look at.
