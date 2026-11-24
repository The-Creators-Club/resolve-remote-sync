# Brief: writing one piece of the specification

A product is being rebuilt from nothing by a fresh session that will never
see the present code. It will be given a specification of WHAT the product
does for people, the lessons real use taught, and nothing about HOW the
present one is built. You write one piece of that specification.

Your raw material is a bundle: every behaviour of one capability, already
restated as what a person gets (the "items"), the lessons real use taught
about the same sub-topics, the questions earlier readers raised, and the
points left unsettled. The items came from forty-seven readers who each saw
one slice of the present product, so one behaviour often appears several
times, seen from different sides, and sometimes the copies disagree. Your
job is to turn the bundle into the one clear account of what the product
does: each behaviour once, complete, in plain words.

The owner's words:

- "NOTHING about how this product was actually built should make it into
  the rebuild document, only what it achieves."
- "For this rebuild - the keyword is elegance. We go for the most elegant
  option with the least moving parts every time."

## Read first, in this order

1. This brief.
2. `E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\OWNER_REQUIREMENTS.md`:
   what the owner has decided about the new build. It outranks every item.
3. `E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\CAPABILITIES.md`: the
   18 capabilities, so you know what belongs to the others.
4. Your bundle, completely, start to end. Your prompt gives its path.

You may look up ONE other thing: when an item points at another item by its
id ("works as 07-016 to 07-039"), open
`E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\_extracts\<NN>.md` and
read those items. Do not read the product's code, the inventory, the bug
ledger, or anything else.

## Two files, and which side of the glass each is on

You write two files.

- **The specification piece** (`spec\<piece>.md`). This CROSSES to the fresh
  session. Everything in it is on the people's side of the glass: it reads
  as a description of a product, in the present tense, with no past. It
  never says "today", "currently", "at present", "used to", "no longer",
  "the present build", "the old", "legacy", "the inventory" or "the reader",
  never mentions an item id or a question a reader asked, and never hints
  that something exists in two forms or was built twice.
- **The trace** (`spec\_trace\<piece>.md`). This STAYS BEHIND. It proves
  nothing was skipped and carries the questions for the owner. It may speak
  of the present product ("today the same thing can be done from three
  places"), but still in plain words, naming no file, function or tool.

The purge that the items already went through still applies to every word
of the specification piece: no tool, library, language, engine or outside
service the present build chose; none of its own names for its insides; no
file, function, route, setting, table or flag name; no count of its
engines, processes, channels, copies, passes or stages; nothing about how
work is organised inside. The readers were good at this but not perfect.
If an item carries something from behind the glass, leave that part out.

Names you may use: CC Sync, Timeline Cards, the Footage Sorter, "the
server", "the dashboard", "the app on the editor's computer", "the
assistant", "the editing program" or DaVinci Resolve, "the NAS". People are
"an editor", "an admin", "the owner", "a client". Things the studio has
whatever is built may be named: Resolve, Windows, macOS, browsers, phones,
cameras and recorders and their cards, the kinds of NAS, YouTube.

## How to write a behaviour

Keep the bundle's sub-topics as your `##` headings, with the same names, in
the same order. Under each, write the behaviours as `###` headings. (An
item's "Filed under" line may name a heading the bundle folded into one of
its sub-topics; write the item under the sub-topic the bundle put it in, or
under another of your sub-topics where it plainly fits better.)

A `###` heading is a plain sentence or phrase saying what a person can do or
what happens for them ("An editor ticks a project for a computer"). Each
heading in your file is different from every other, and contains no `|` and
no `;`.

Under it, write the behaviour completely: prose, a short list or a table.
Full sentences, plain words, no long dashes. Keep every number a person
meets (sizes, counts, waits, how long something is kept), every state they
are shown in the words they are shown, every refusal with its condition and
what they are told. Say how soon and how often in clock time. Then add
whichever of these labelled lines apply. Use these labels exactly:

- `- Who:` who may do it (anyone signed in, an editor for their own
  computer, an admin, a client holding a link).
- `- Ways in:` every place the same thing can be done from, described by
  what the place is ("from the project's own page, from the list of
  computers, from the app on the editor's computer"), never by where the
  present build puts a page.
- `- On its own:` what the product decides or does without being asked,
  and from what. One line per decision.
- `- By hand:` how a person sees and sets what the line above decided. See
  "Every decision can be set by hand" below.
- `- Setting:` one line per setting a person can change, in this shape:
  `- Setting: <plain name>. Does: <what it changes for a person>. Default:
  <value>. Who: <who may change it>. Applies to: <the site | a computer | a
  person | a project>. Search words: <three to six words someone might
  type>.`
- `- Name and search words:` for a page, screen or part a person can go to:
  its plain name and three to six words someone might type to find it.
- `- When <part> is off:` what a person sees and can still do when a part
  this behaviour leans on is switched off (the six parts and the assistant
  are in the owner's requirements).
- `- Windows and macOS:` or `- Phone and desk:` where a person meets a
  difference.
- `- Exact: yes` when the passage is copied as it must be built (below).
- `- Pending: <id>` when the text rests on a question still open (below).

Do not pad. A behaviour with nothing to say under a label has no such line.

**Each behaviour once.** When several items describe one behaviour, write
it once, keeping every detail any of them has. When they describe it from
two sides (what the server does, what the app on the editor's computer
does), the person only ever sees one thing happen: describe that.

**Everywhere outside the Timeline Cards editor, say what is on a screen and
what each thing does, never where it sits or how it looks.** The dashboard
is being redrawn from nothing in one look; no page names from the present
build, no menu positions, tab orders, settings groups, colours or button
styles. The owner's requirements give the dashboard's new shape; file a
behaviour under the page it belongs to there only where that is obvious
(the overview, projects, transfers, the per-computer view, settings).

## Describe the job, not the arrangement

This is the hardest part of the work and the reason it exists. The items no
longer name the present build's tools, but they still carry its SHAPE: which
computer does which piece of work, what is handed from one to another, what
an admin must push from one place to another by hand. A fresh session that
reads the shape will build the shape again. The owner: "if you had told the
new session that the product originally used 3 sync engines, surely it
would bias it to use 3 sync engines again."

For every behaviour ask: **is this the job a person wants done, or is it how
the present build arranges getting it done?** Write the job, with everything
a person is promised about it. Leave the arrangement behind.

Arrangements, which do not cross:

- **Which computer does a piece of work**, and work being passed between
  computers. Heavy work (analysing, transcribing, converting, making proxies
  and previews) is "done on a computer of the studio's that is able and
  free": that is one capability of the product (Work shared out across the
  computers), which says who does what. Your piece says what the work
  needs (a graphics card, a one-off download of about 280 MB on the computer
  that does it), what the person is shown while it runs, and what choice
  they have ("now, or while I am away"). Never "the indexing computer", "the
  studio's main computer", "the wired computer", "analysed on the editor's
  computer and then uploaded", "uploaded to the server and analysed later".
- **Batches, claims, holds, releases, take-overs, staging, queues between
  parts**: how the present build keeps one piece of work from being done
  twice or lost. What crosses is the promise: a drop survives the page
  closing, the computer restarting and the network dropping; nothing is
  done twice; nothing is lost; the person can see it, pause it, cancel it.
- **Data being published, pushed, merged, drained or swapped from one place
  to another**, by an admin or on its own, with its holding places, checks,
  previous copies and rollbacks. These exist because the present build
  keeps things in several places. What crosses is the promise (what a
  person adds is never lost by an update; a change shows within a minute).
  An admin's hand-run step that exists only to move data between the
  build's own parts is left out.
- **One part of the build being older or newer than another**, and
  everything said to a person because of it ("the app is too old for this",
  "a different model version"). What crosses: an editor is told plainly when
  their computer must update before something will work.
- **Limits that are only the size of one of the build's own pipes** (so many
  files or bytes per request, so many at a time). A limit a person is told
  about and plans around crosses ("at most 500 tracks in one drop"); if you
  cannot tell which it is, keep it and say so in the trace.
- **How long the present build happens to take.** A wait a person is
  promised or told about crosses ("gives up after 2 minutes and says so").
  A measured running time of the present build ("a full re-order takes
  about nine hours") does not: it would be read as acceptable.
- **The shape of the assistant tooling the present build happens to run
  on**: how many questions it can ask at once, phrases that invoke it,
  which strength of assistant does which step.

Three tests when you are unsure:

1. Would a person using a product that did the same job in the simplest
   possible way ever meet this? If not, it is an arrangement.
2. Does something the studio HAS force it (YouTube refuses the studio's
   address, so a download may have to run on the editor's own connection;
   Resolve can only be driven on the computer it runs on)? Then it is a
   fact about the world and crosses, stated as that fact.
3. Does the person choose it or need to supply something for it (a drive,
   a sign-in, a graphics card, leaving their laptop out of heavy work)?
   Then their choice crosses.

An item that is only arrangement is covered in the trace as `left out: an
arrangement (the promise is under <heading>)`, naming the heading where
you wrote what a person is promised. If you are leaving out something an
admin or editor does by hand today, say in "New in this text" what happens
instead for that person (usually: nothing to do, it happens on its own).

**Wording outside the Timeline Cards editor** is kept where it is plain
("Drop audio to add it to the library"), and reworded where it names the
build's insides or an arrangement ("Your own computer analyses it and
uploads it"). Only `Exact` text is untouchable.

## When items disagree, and what wins

In this order:

1. **The owner's requirements**, then any lesson of kind `ruling`. Never ask
   him again about something he has ruled on; write it as decided. Where a
   requirement for the new build and an older `ruling` lesson pull apart,
   write the requirement (it is his later word, and about this build), mark
   it `- Pending:` and ask him to confirm in one question.
2. **A lesson** (the knowledge base). A lesson is a rule the product must
   meet, learned from real use, and some lessons were learned after the
   present product was last changed. Where an item says the product does
   one thing and a lesson's "Must" says it has to do another, write what
   the lesson requires, and note the conflict in the trace.
3. **The items.** Where two items disagree and nothing above settles it,
   write the one behaviour you would recommend (the one with the fewest
   moving parts that still does the job; when footage is at stake, the
   safer one), mark it `- Pending: <question id>`, and put the question in
   the trace with both options.

**What the text assumes while a question is open:** your recommendation,
with one exception. Something you recommend CUTTING is still written, in
its place, marked `- Pending:`, so the passage exists if he keeps it and is
simply deleted if he does not.

## The flags on items

- `several ways in`: write the behaviour once and list every way in under
  `- Ways in:`. The owner has asked to be asked about every overlap, so
  raise one question in the trace for each THING that can be done several
  ways (which ways in stay?) with your recommendation, and mark the line
  `- Pending:`. Do not fold different things into one question. **Not in the Timeline
  Cards editor**: there, every key, button and gesture for one action is
  kept and is not a question.
- `built twice`: write it once. No question, unless a person could notice
  which form they got.
- `differs: ...`: see "When items disagree" above. One behaviour in the
  text, one question in the trace.
- `dormant` or `unreachable`: write it in its place as if it were live, and
  mark it `- Pending:` with a keep-or-cut question in the trace. If the
  owner cuts it, the passage is deleted.
- `dev only`: a tool for the people building the product. Leave it OUT of
  the specification (the fresh session makes its own tools). In the trace,
  cover every such item with `left out: for the builders only` and raise
  ONE question listing them all together, recommending they go. The one
  exception: where a builders' check states something the product must
  achieve for a person (a page works at phone width, a search finds a known
  clip), write that requirement into the behaviour it belongs to.
- `undetermined: ...`: settle it from the other items and the lessons if
  you can. If you cannot, write the behaviour as far as a person needs it,
  mark it `- Pending: <unsettled id>`, and list it in the trace. Do not
  guess a number or a wording.

## Every decision can be set by hand

The owner: "there must always be a manual override of everything." In
Timeline Cards' footage-in and board, and wherever the Footage Sorter sorts,
names or matches on its own, EVERY decision the product makes gets an `- On
its own:` line saying what is decided and from what, followed by a `- By
hand:` line saying how a person sees it and sets it, and that a value set
by hand is never overwritten by a later automatic pass. Where the items
show no way to set it by hand, write the override anyway as a requirement
and say in the trace that it is new. Elsewhere in the product, write `- By
hand:` wherever the items show a person can overrule the product.

For footage-in and the board, the items describe a row of steps a person
runs by hand today. The specification has no steps: it describes what the
product achieves once clips are dropped in, what it must get right, each
decision and its override, and what a person is shown while it works and
when something cannot be done.

## What crosses exactly

Items marked `Exact: yes` hold what a person sees and touches in the
Timeline Cards editor, the `.cut.md` file, and the named export and import
formats. The owner keeps these as they are. For them:

- Do not reword, summarise or "tidy" keys, gestures, controller buttons,
  labels, messages, states, tables or the file format.
- You may regroup them under your headings, and you fold together items
  that say the same thing.
- To carry an item's text across untouched, put its id alone on a line in
  double braces: `{{31-044}}`. A script replaces that line with the item's
  text, exactly. Use this for any Exact item whose text is clean and stands
  on its own; write your own heading and, if needed, a sentence of framing
  around it. Do NOT use it for an item whose text mentions another item's
  id, an inventory section, or a reader's remark: copy that one by hand and
  repair it. The braces are the only place an item id may appear in the
  specification piece.
- Mark every heading that holds exact text `- Exact: yes`.
- Where on-screen text names the assistant by a product or model name,
  write `[the assistant]` in its place, and where it names a tool the
  present build chose or one of its insides, write the role in square
  brackets (`[speech-to-text]`, `[the episode's media]`). Keep ordinary
  words an editor sees even where the build also uses them. Whether the
  assistant's name shows on screen is already on the owner's list; do not
  raise it again.
- A message that only reports one of the build's insides failing (naming a
  store, a scan, a part of the server) is not something to keep exactly:
  say what the person is told in plain words, outside the exact text.
- "Describe the job, not the arrangement" still governs your own framing
  sentences, but it does not delete what is on the editor's screen: a
  control or state the editor shows crosses even where it reflects how the
  work is arranged. Where such a control only exists because of an
  arrangement (a hand-run way to start work that footage-in now does on its
  own), write it, mark it `- Pending:` and ask whether it stays.
- A lesson of kind `ruling` outranks exact text, as it outranks any item:
  write what the ruling requires and log the conflict.
- Cut by the owner, and so never carried even when an item has them: the
  translate button and draft translations in the editor; anything shaped by
  the notes program (its links, embeds, canvases, folders); Story Deck.

## Lessons

Each sub-topic of your bundle ends with the lessons it must meet. A lesson
is not restated in your text (the knowledge base crosses beside the
specification); your text must be CONSISTENT with it, and where a lesson's
"Must" describes something a person gets that no item shows, you write that
behaviour.

End every `##` sub-topic with:

```
#### Lessons

- Met: MUS-001, MUS-004, MUS-005.
- Not yet met by any behaviour above: MUS-007 (what is missing, in a few words).
```

Every lesson id of the sub-topic appears in one of these lines. Use
"Not yet met" only when you truly could not write a behaviour that meets
it; say why in a few words. Leave the second line out when it is empty.

Some lessons are themselves about an arrangement: their rule only makes
sense if the product is built the way the present one is ("a batch whose
computer goes quiet returns to waiting after five minutes"). Do not build
the arrangement into your text to satisfy them. Write the promise behind
the lesson, and list the lesson on a third line:

```
- Tied to an arrangement: MUS-021, MUS-022 (the promise is in "<heading>").
```

Those lessons will be taken out of what crosses, so be sure the promise
really is in your text.

Two limits on that third line. **A lesson of kind `ruling` is never listed
there**: if the owner asked for something a person can do or see (a "sync
now" button, a count on a page), it is what the product does, however much
it looks like machinery. If you think a ruling only made sense for the
present build, write it as ruled and ask him in one question. And a lesson
that is half promise and half arrangement is `Met` on its promise; note the
half you left behind under "Parts of items left out", by the lesson's id.

## Leaning on other capabilities

Your piece covers one capability. When a behaviour continues in another
("the clip is then sent to the editing program"), say so in one sentence
and name the capability and its sub-topic as CAPABILITIES.md does ("see
Resolve on the editor's computer: Bins, clip sorting and imports"). Do not
describe the other capability's behaviour. List each such join in the
trace, so the joins can be checked when every piece is written.

If your capability is a part that can be switched off, your first piece
opens with what a person sees when it is off, and each piece says, where it
matters, what a behaviour does when a part it leans on is off.

## The specification piece: its shape

```
# <the capability's name, as the bundle's first line gives it>[, part <k> of <n>]

<Three to six sentences: what this is for, who uses it, and, for a part
that can be switched off, what a person sees when it is off. Only in a
capability's first piece; a later piece starts with one sentence saying
what this part covers.>

## <Sub-topic, as in the bundle>

### <A behaviour>

<the behaviour, then its labelled lines>

#### Lessons

- Met: ...
```

## The trace: its shape (a script reads it)

```
# Trace of <piece>

## Coverage

- 25-001 | <the ### heading it was written under>
- 25-002 | <heading> ; <a second heading, when one item fed two>
- 25-046 | left out: for the builders only
- 25-047 | left out: cut by the owner (the translate button)

## Questions for the owner

### <piece>-Q1: <the question, in plain words, as you would ask him>
- Kind: <several ways in | built twice | differs | dormant | unreachable | dev only | either-or | other>
- Today: <what exists now, in plain words>
- Options: A: <...>. B: <...>.
- Recommend: <A or B, and why in one sentence. Fewest moving parts.>
- Changes for a person: <what he or an editor would notice either way>
- Text assumes: <which option the specification piece is written to, or "left out">
- Items: 25-022, 25-024
- Covers: 25-Q1, 25-Q2

## Readers' questions and unsettled points

- 25-Q1 | <piece>-Q1
- 25-Q3 | answered: <the lesson id, or the owner's requirement, that settles it>
- 08-Q7 | with youtube
- 25-Q6 | not a question: <why a person would never notice>
- U-25-2 | settled: <how, in a few words>
- U-25-5 | open: <piece>-U1
- U-08-3 | behind the glass

## Still unsettled

- <piece>-U1 | <what is not known> | <what the text assumes meanwhile> | <item ids>

## Conflicts between an item and a lesson

- <lesson id, or "owner's requirements"> | <item ids> | <what the item says, what the lesson or requirement asks, which you wrote>

## New in this text

- <heading> | <an override or behaviour the items did not show, written because a lesson or the owner's requirements demand it>

## Parts of items left out

- <item id> | <the part of a covered item you did not carry, and why (an arrangement, an inside, cut by the owner)>

## Joins with other capabilities

- <capability / sub-topic> | <heading here> | <what this text relies on there>
```

Rules for the trace:

- **Coverage**: every item id of your bundle, once. Either the heading(s) it
  was written under, copied exactly, or `left out: <reason>`. An item
  carried by a `{{id}}` line still gets its coverage line.
- **Questions for the owner** are numbered `<piece>-Q1` onwards. Ask only
  about WHAT the product does for a person; never an engineering question
  (how many of anything, which tool, where something runs unless a person
  would notice). Fold readers' questions that ask the same thing into one.
  A question you could answer from the owner's requirements or a `ruling`
  lesson is not asked: it is `answered:`.
- **Readers' questions and unsettled points**: every id in the bundle's two
  closing lists, once, with what became of it. A question marked `ALSO
  WITH: <other pieces>` in the bundle is written up by ONE piece: the one
  whose name comes first in alphabetical order among yours and the others
  listed. If that is you, write it up. If not, give `with <that piece>`.
- An empty section keeps its heading, with nothing under it.

## Before you finish

Run `python E:\Projects\Editing\ccsync\docs\rebuild-spec\tools\check_spec.py <piece>`.
(Do not pass `--build`: it writes a third file.) It reports item ids, lessons and questions not accounted for, headings the
trace names that the text does not have, and, in the specification piece,
giveaway words, words that give away a past ("currently", "legacy"), long
dashes and stray ids. Fix what it reports and run it again until it prints
`OK`. A giveaway word is fixed by saying what the thing does for a person,
not by respelling it.

Then read your specification piece once more as the fresh session would,
asking: from this, could I tell how the present product is built, what it
is made of, how many of anything it has inside, or that something used to
be different? Every yes is a leak to fix. And ask: could I build this
behaviour from what is written, without guessing? Every no is a gap to
fill from the items.

## Other rules

- Touch nothing but your two output files. Do not commit. Do not start
  sub-agents. A temporary file's name must start with the prefix your
  prompt gives.
- Never copy a password, token, key, address, e-mail or person's name.
- Write each file in several appends, sub-topic by sub-topic, so nothing is
  lost. Finish the specification piece before the trace's questions, but
  keep the coverage list as you go.

## Your final reply

Short: the two paths; how many behaviours (`###`), settings lines, pending
marks and questions; how many items were left out and the commonest
reasons; how many lessons are "not yet met"; that the checker printed `OK`;
and the three hardest calls you made, with what you chose.
