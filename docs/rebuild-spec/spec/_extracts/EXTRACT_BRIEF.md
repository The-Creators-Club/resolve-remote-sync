# Brief: extracting one inventory section for the specification

A product is being rebuilt from nothing by a fresh session that will never
see the present code. It will be given a specification of WHAT the product
does for people, and nothing about HOW the present one is built. You turn
one section of a very detailed inventory of the present product into the
raw material for that specification.

The inventory was written from the code, slice by slice, so it is full of
the present build's insides. Your whole job is to carry across what a
person gets and leave the insides behind.

The owner's words:

- "NOTHING about how this product was actually built should make it into
  the rebuild document, only what it achieves. For example if you had told
  the new session that the product originally used 3 sync engines, surely
  it would bias it to used 3 sync engines again, even if not necessary.
  This is the exact kind of bias I was trying to ensure is purged."
- "For this rebuild - the keyword is elegance. We go for the most elegant
  option with the least moving parts every time."

## Read first

1. This brief.
2. `E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\CAPABILITIES.md`: the
   18 capabilities every item is filed under, and their sub-topics.
3. Your inventory section, completely, start to end. Your prompt gives its
   path. Do not read the product's code, other inventory sections, the bug
   ledger or the knowledge base.

## The glass

Picture a sheet of glass between the people who use the product (an editor,
an admin, the studio's owner, a client with a link, a person installing it)
and its insides. **Everything on the people's side crosses. Nothing behind
the glass does.**

Crosses, in full:

- what a person can do, and every way of doing it;
- what happens for them on its own, and when, in terms they would notice
  ("a change is picked up within about a minute", not the loop that does it);
- what they see and are told: every state they are shown, every warning,
  every refusal and the condition for it;
- every limit and number a person would run into or wait through: sizes,
  counts, how long something is kept, how long before something gives up;
- every setting a person can change, BY WHAT IT DOES, with its default and
  who may change it (never its key name);
- who may do each thing (anyone signed in, an admin, the owner of a
  computer, a client holding a link);
- every difference between Windows and macOS, or between phone and desk,
  that a person meets;
- facts about the things the studio has whatever is built: DaVinci Resolve,
  Windows, macOS, browsers, phones, cameras, recorders and their cards, the
  kinds of NAS, YouTube, the studio's network.

Never crosses:

- any tool, library, language, engine or outside service the present build
  CHOSE, and anything that gives the choice away, including how many
  engines, processes, channels, copies, passes or stages it has;
- the present build's own names for its insides (its transfer routes,
  queues, roles, stores, switches, records), and every file, function,
  route, setting, table, flag and environment-variable name;
- how the work is organised inside: loops, queues, retries, locks, caches,
  internal states nobody is shown, the order of internal steps;
- formats on the wire or on disk, except the three things under "Exact";
- why a mechanism exists, where the reason is itself a mechanism.

**The test for any line of the inventory: would a person using the product
notice if this were different?** If yes, say what they would notice. If no,
it is behind the glass.

Translating, by example:

| The inventory says | The item says |
|---|---|
| "Base wait is `idle_seconds` (default 60 s); after a pass that moved nothing the multiplier steps 1x, 2x, 5x" | "A change made on an editor's computer starts syncing within about a minute; with nothing changing, the product checks less often, never less than every five minutes." |
| "`POST /api/v1/selections` (admin or the editor themself): 409 when the machine's role is base" | "An editor or an admin can tick a project for a computer. A computer set to sync nothing cannot be ticked: the person is told why." |
| "Lane B circuit breaker trips when the listing has fewer than 20 % of last pass's files" | "Downloading stops by itself, and says so, when the server suddenly appears to hold far fewer files than before (under a fifth), so a server fault is never copied to an editor's disk as deletions. Only a person restarts it." |
| "Reads `X_TIMEOUT` (default 900)" for a wait nobody sees | left behind |
| "The tray menu has ten items: ..." | each item, by what it does, in the order shown |

Three habits of the inventory to translate every time:

- **Rounds, passes, turns, cycles.** These are how the present build paces
  itself. Say how soon and how often in clock time ("within about a
  minute", "about every two hours"), never "one round in ten".
- **Log lines.** What the product writes to its log is behind the glass. Do
  not quote log lines. If something is ONLY logged, the item says that
  nobody is told (that is itself worth knowing), in those words.
- **Lists of internal states.** Carry the states a person is shown, in the
  words they are shown. A state nobody sees is behind the glass.

A setting that only tunes the present build's machinery (how many
connections, how big a chunk) is behind the glass. A setting whose effect a
person feels (a speed limit, a pause, how long something is kept) crosses,
described by its effect.

Names that may be used: the product's own names as people see them (CC
Sync, Timeline Cards, the Footage Sorter), "the server", "the dashboard",
"the app on the editor's computer", "the assistant" (never the name of the
model or its maker), "the editing program" or Resolve, "the NAS". A person
is "an editor", "an admin", "the owner", "a client".

## Three things that cross exactly

The owner decided that what a person sees and touches in Timeline Cards is
kept exactly, and that one file format is kept. For these, copy the
inventory's detail faithfully and mark the item `- Exact: yes`:

1. **In the Timeline Cards editor: every key, mouse and touch gesture,
   controller button, on-screen control, label, message and state**, with
   exactly what each does in each context. Keep tables as tables. Still no
   route, file or function names: the key and what it does cross, the
   handler does not.
2. **The cut list file (`.cut.md`)**: what the file looks like and what each
   part means, exactly as the inventory gives it.
3. **The export and import formats a person chooses by name** (Final Cut
   Pro XML, OpenTimelineIO, EDL, the script as text or Markdown): what each
   carries and what it cannot.

Everywhere else (the dashboard, b-roll, music, YouTube, the Sorter, the app
on the editor's computer) say what is on a screen and what each thing does,
and what a message tells the person, but NOT where the present build puts
it: no page names, menu positions, tab orders or settings groups. The
dashboard's layout is being redrawn from nothing.

## What the owner has already decided about the rebuild

Apply these while you extract. An inventory heading that is ONLY about
something cut is left behind with the reason `left behind: cut by the
owner (<which>)`.

- **Cut whole:** Story Deck. The notes program (Obsidian) and everything
  shaped by it: its canvas files, block links, embeds, its folder of notes,
  plugins. The translate button and draft translations in the editor. The
  old Timeline Cards page as a page (what it could DO lives on in the
  editor and is extracted; its own screens and controls are not).
- **Planning** is now a board inside Timeline Cards: theme columns,
  transcript paragraphs as cards, dragged by hand; a place for notes; the
  assistant proposes themes and a first sort, and updates the board when
  called. From anything about the old planning tools, extract what planning
  ACHIEVES for him and his editorial rules, filed under `cards-board`.
- **Footage in, ready to cut:** clips are dropped in and everything runs on
  its own (which clips are one interview, lining up by sound, the multicam,
  transcript, translation, word timing, the first sort). There are no
  stages a person runs. From anything about the present hand-run stages,
  extract what each ACHIEVES and what it must get right, filed under
  `cards-footage-in`. **Every decision the product makes on its own must be
  listed as its own item**, saying what is decided and from what, because
  each one needs a manual override in the rebuild.
- **A transcript is one file** holding text, translation, each word's time
  and the links between English and original words, with a readable
  Markdown copy alongside. The present separate files and how they find
  each other are behind the glass; note them under "Old data" only.
- **Nothing before the hand-over depends on an editing program.** Resolve
  is the first one supported. Exports (XML, OTIO, EDL, script) are kept.
- **Six parts can be switched on and off by a site:** b-roll, music,
  YouTube downloads, Timeline Cards (as one), camera cards with the Footage
  Sorter, and the help for the editing program. Making proxies and sharing
  heavy work are always available. One site-wide switch turns the assistant
  off. A part that is off is visible only to an admin in settings.
- **One look everywhere**, the Timeline Cards editor's. Do not describe how
  anything outside the editor looks (colours, button styles, bracketed
  labels).
- **Syncing is always on.**

## What you write

ONE Markdown file at the path your prompt gives, in exactly this shape (a
script reads it):

```
# Extract of inventory section <NN>

## Items

### <NN>-001: <one plain sentence: what a person can do, or what happens for them>
- Where: <capability> / <sub-topic>
- What: <the behaviour, complete and plain. As many sentences as it needs,
  or a short list or table on the following lines.>
- Flag: <only when one applies, see below>
- Exact: yes            <only for the three things that cross exactly>

## Questions for the owner

- <NN>-Q1 | <kind> | <the question, in plain words> | <item ids it concerns>

## Old data

- <a kind of information the live product holds that must still be there after a rebuild, named as information> | <the heading line(s), e.g. L212>

## Unsettled

- <something the inventory section itself could not determine, that a writer of the specification needs to know is open>

## Coverage

- L16 | <NN>-001, <NN>-002
- L37 | left behind: how the present build paces its own work
```

**Items.** One item is one thing a person could point at: an action, an
automatic behaviour, a thing they are shown or told, a refusal, a setting,
a limit. Put related details in one item's `What` rather than making ten
tiny items; split when two things could be kept or cut separately. Ids run
`<NN>-001` onwards with no gaps.

- `Where`: one capability name from CAPABILITIES.md, copied exactly, then
  ` / ` and a sub-topic: one of that capability's listed sub-topics where
  one fits, otherwise a new plain heading. File an item by what it is FOR,
  not by which program the inventory found it in. The same behaviour seen
  from the server and from the editor's computer is ONE item.
- `What`: complete. Keep every number a person meets. Plain words, full
  sentences. No em dashes.
- `Flag`, when one applies, starts with one of:
  - `several ways in`: the same thing can be done from more than one place
    (say which places, by what they are, not by page name);
  - `built twice`: the same job exists in two forms that behave the same;
  - `differs: <how>`: two forms of one job that behave DIFFERENTLY;
  - `dormant`: present but switched off for everyone by default;
  - `dev only`: a hatch for the people building it;
  - `unreachable`: present but no person can get to it;
  - `undetermined: <what>`: the inventory could not tell.
  Dormant, dev-only and unreachable features ARE extracted, with their
  flag, so the owner can decide whether they go.

**Questions for the owner.** From the inventory section's own "Looks
redundant or overlapping" list and from what you notice: only questions
about WHAT the product does for a person, never an engineering question.
Kinds: `several ways in` (keep which?), `built twice` (which behaviour
wins?), `dormant` (can it go?), `either-or` (two tools for one job),
`other`. A duplication with no difference a person could notice is not a
question: describe the behaviour once and move on. **In the Timeline Cards
editor, several keys, buttons or gestures for one action is NOT a
question**: the owner has already said all of them are kept. There, ask
only where two controls for the same job BEHAVE differently, or where
something is dormant, dev-only or unreachable.

**Old data.** Information the live studio already holds that a rebuild must
be able to bring across (people, their computers, what each syncs, cut
lists, transcripts, client links, settings, histories), named as
information. Do not describe its present format: give the heading line
where the inventory does.

**Coverage.** Every `##` and `###` heading of your inventory section, by its
line number, with either the items drawn from it or `left behind: <a few
words why>`. Get the list with
`python E:\Projects\Editing\ccsync\docs\rebuild-spec\tools\check_extract.py <NN> --headings`.
This is the proof that nothing was skipped. The inventory's three closing
lists are headings too: "Looks redundant or overlapping" is covered by your
questions (`left behind: see the questions` is fine), "Claims the code does
not back" is `left behind: about the present code and its notes`, and
"Could not determine" by your Unsettled list.

## Before you finish

Run `python E:\Projects\Editing\ccsync\docs\rebuild-spec\tools\check_extract.py <NN>`.
It reports headings not accounted for, bad fields, and giveaway words (tool
names, identifiers with underscores, file extensions, version numbers,
people's names). Fix what it reports and run it again until it prints
`OK`. A giveaway word is fixed by saying what the thing does for a person,
not by respelling it. In an `Exact: yes` item the word check is skipped, so
use that mark only where this brief allows it.

Then read your own file once more as the fresh session would, asking: from
this, could I tell how the present product is built, what it is made of, or
how many of anything it has inside? Every yes is a leak to fix.

## Other rules

- Touch nothing but your one output file. Do not commit. Do not start
  sub-agents. A temporary file's name must start with the prefix your
  prompt gives.
- Never copy a password, token, key, address, e-mail or person's name.
- Write the file in several appends if it is long, so nothing is lost.

## Your final reply

Short: the path; how many items, questions, old-data lines and unsettled
lines; how many headings were left behind and the three commonest reasons;
that the checker printed `OK`; and the three places where it was hardest to
tell which side of the glass something was on, with what you chose.
