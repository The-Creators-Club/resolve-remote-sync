# Brief for an answers reader

Stays behind. You check one capability's lessons against the owner's later
answers.

## What this is

`E:\Projects\Editing\ccsync\docs\rebuild-spec\knowledge-base\<capability>.md`
holds the lessons real use taught about one capability of a product (a video
studio's sync, dashboard, Timeline Cards editor, Footage Sorter and more).
Each lesson is three lines: what a person saw (the heading), why, and what
the product MUST do, with a kind (`given`, `ruling`, `situation`). A
different session will build the product afresh and will be tested against
every Must.

The lessons were gathered up to 2026-11-13. Since then the owner has answered
several hundred questions about what the new build does, most on 2026-11-24,
and some of his answers change or cancel what an older lesson says. A lesson
left as it is would then demand something he has decided against. Twenty
such lessons were found and taken out already; the first ones found by
accident since show there are more, often only PARTLY overruled. Examples:

- A ruling said an upload-only project sends every file up and "nothing
  comes down". He has since chosen that its empty folders DO come down.
  Only three words of the lesson are wrong: it is amended.
- A ruling said every move of sorted footage "needs approval before it
  runs". He has since chosen that the Footage Sorter moves originals on its
  own with no approval. The approval goes; "never deletes or overwrites an
  original" stays: amended.
- A lesson about staged edits waiting to be applied to a timeline in
  DaVinci Resolve. He has since cut editing a Resolve timeline from the
  cards altogether. Nothing of the lesson is left: withdrawn.

Your job is to find every such lesson in ONE capability. You change no
lesson: you list them, with the words that would put each right.

## What to read

1. `...\spec\OWNER_REQUIREMENTS.md`: the owner's decisions about the new
   build, in one place. Read it first.
2. `...\DECISIONS.md`: pages 1 and 2 with his answers written out. Two
   answers on page 2 go against the recommendation; read them closely.
3. `...\spec\_trace\APPLY_ANSWERS.md`, the section "Decisions of his that
   reach every piece".
4. The decision pages you are given by name (the ones for your capability,
   and the three that cut across: `page-03-whole-product.md`,
   `page-30-open-points.md`, `page-31-after-the-answers.md`), in
   `...\decisions\`. Each question shows what exists today, the options and
   the recommendation. His answer is the line starting `- Answered by the
   owner`, or the page's `ANSWERED` note; where a page says every
   recommendation was accepted, the recommended option IS his answer. A
   question's `Today:` line often describes a thing he then cut.
5. Your capability's lessons, `...\knowledge-base\<capability>.md`,
   completely, every lesson.

You may open any piece of the specification (`...\spec\<piece>.md`) to see
how an answer was written into it, and any other decision page when a lesson
of yours touches another capability's subject (search `...\decisions\` for a
word). Do not open anything outside
`E:\Projects\Editing\ccsync\docs\rebuild-spec`, and never the product's code.

## What counts

Report a lesson when an answer or requirement of the owner's, LATER than the
lesson, means that:

- the thing the lesson is about no longer exists in the new build (he cut
  the feature, the control, the page, the mode, the state): **withdraw**;
- the lesson's Must (or its Why or heading) demands something he has
  decided differently, while the rest of it still holds: **amend**, changing
  as few words as will do;
- a number, limit, default or wording in the lesson is one he has since
  changed: **amend**.

Do NOT report a lesson:

- because the specification's text happens to differ from it (another check
  deals with that) when no answer of his is behind the difference;
- because you think it is out of date, unwise or about machinery. Only his
  later word counts, and you must be able to quote it;
- of kind `ruling` unless his later answer is plainly about the same thing.
  A ruling is his own earlier decision; quote both so the two can be seen
  side by side;
- that merely mentions a thing he cut while its rule is about something
  that remains (then amend the mention away only if the Must cannot be
  tested without the cut thing).

When an answer changes a thing in a way no lesson speaks about, there is
nothing to report. Most lessons are untouched; expect to report a small
share of them. If in doubt whether an answer reaches a lesson, report it
with `- Doubt:` and say what would settle it.

## What to write

One file, `...\knowledge-base\_cross\_answers\<capability>.md` (make the
folder if it is not there):

```
# Answers against lessons: <capability>

## Lessons

### <ID>: withdraw
- Answer: <page and question number, or the section of OWNER_REQUIREMENTS>: "<his answer, or the option he accepted, quoted exactly>"
- Lesson says: "<the words of the lesson that clash, quoted exactly>"
- Because: <one sentence>

### <ID>: amend
- Answer: <where>: "<quoted exactly>"
- Lesson says: "<the words that clash, quoted exactly>"
- Field: must
- New words: <the WHOLE field as it should now read, changing as little as possible>
- Because: <one sentence>

## Read

- lessons read: <how many>
- decision questions read: <how many>
```

Rules for `New words`:

- It replaces the whole of one field: `title` (the heading after the id),
  `why`, or `must`. To change two fields of one lesson, write two blocks
  with the same id.
- At most 30 words for `why` or `must`, 15 for `title`: the knowledge base
  is terse, and the lesson was already within these limits.
- Plain words, in the lesson's own style. No name of a tool, file or
  setting of the present build, no bug number, no person's name, no long
  dash, and no mention that the rule changed ("no longer", "now",
  "formerly"): the new words state the rule as it stands.
- Keep every part of the lesson his answer did not touch.

## Rules

- Change no file but your own output.
- Do NOT start sub-agents of your own.
- Temporary files, if any, start with the prefix you were given.
- Your last message is at most eight lines: lessons read, how many to
  withdraw, how many to amend, any doubts, and the two or three that matter
  most.
