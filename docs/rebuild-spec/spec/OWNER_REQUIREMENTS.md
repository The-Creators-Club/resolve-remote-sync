# What the owner requires of this build

These are the owner's own decisions about the product being built. They
come before everything else in the specification: where a capability's
document and this one disagree, this one holds. Words in quotation marks
are his.

## 1. The guiding principle: elegance

"The keyword is elegance. We go for the most elegant option with the least
moving parts every time, to achieve the desired functionality. This is the
guiding principle for the whole operation."

How it is applied:

- It decides HOW, never WHAT. What the product does for a person is fixed by
  this specification. Elegance never removes something a person can do, a
  ruling of the owner's, or a lesson from real use. It removes mechanisms.
- The test for any part: take it away. If everything the product must do can
  still be done, it goes.
- A design in which a failure cannot happen is better than a mechanism that
  catches the failure. The lessons from real use are given so that the
  fewest parts can be found that meet all of them at once, not so that each
  one gets a guard of its own.
- One way to do each thing: one way of telling a computer something, one
  place a setting comes from, one way to publish a new version.
- How it is built is the builder's to decide from this principle. Nothing in
  this specification says how, and nothing in it should be read as a hint.
  The owner sets two things himself, below: the language, and that the way
  footage travels is chosen by measurement.

### The language

The app on an editor's computer and the server are written in Rust: one
native program on each, light, quick to start, with one version number.
What a browser shows, the link to the editing program (which can only be
driven in the languages that program itself speaks) and the analysis of
footage use whatever serves them best.

### How footage travels is chosen by measurement

The owner asks for "full testing of speed of sync types", with the studio's
remote editor "and also machines in different countries". For the far-off
computers he has settled on one other country: the studio's remote editor
and computers in the United States are enough.

- Before the way footage travels is settled, every candidate way of moving
  it is measured for real, not assumed: camera originals going up, proxies
  and originals coming down, and many small project files kept in step.
- It is measured between the studio's server and real editors' computers:
  a computer on the studio's own network, the studio's remote editor on a
  home connection in the same country, and computers in the United States,
  on Windows and on macOS.
- Each run records what a person would feel: megabytes a second against
  what that connection can carry, how long before the first byte moves,
  how a cut-off transfer picks up again, and how the same transfer behaves
  with several editors moving files at once.
- The results are kept with the product and shown to the owner before the
  choice is made. The choice is the one that is fastest for the far-off
  computers without giving up any promise this specification makes about
  footage. The same measurements are run again before each release, so a
  release that makes syncing slower is caught before it ships.

## 2. One product, a small core, and parts that switch on and off

"I want every individual component to be a module which lives inside its own
codebase and slots into the dashboard, so each one can be maintained,
updated, enabled and disabled individually." And, on what "its own codebase"
means: "one repository with a self contained separately versioned folder per
module."

- **Syncing is core**, on the server and on every editor's computer. It is
  never a part that can be switched off.
- **A site can switch six parts on and off, each by itself:**
  1. the b-roll archive (the folders and links handed to clients included);
  2. music;
  3. YouTube downloads;
  4. Timeline Cards (footage in, the board, the editor and the hand-over to
     the editing program go on and off together, as one);
  5. camera cards with the Footage Sorter;
  6. the help for the editing program (on by default). With it off, nothing
     in the product mentions that program, and the b-roll archive, music and
     Timeline Cards offer exports instead of sending to it.
- **Always available**, each with a setting per computer: making proxies on
  editors' computers, and sharing heavy work across the studio's computers
  (the second also with a setting per kind of work).
- **A new site starts with every one of the six off, except the help for
  the editing program.** A studio that only wants syncing sees nothing
  else until an admin switches a part on.
- **One site-wide switch turns the assistant off.** Everything else still
  works, and no assistant control is left on any screen.
- **On screen the assistant is called "Assistant"**, never by a maker's or
  a model's name, because a site may connect more than one kind. Where a
  person chooses how strong an assistant answers, each choice is described
  by what it does (fastest, stronger, most capable) with its price.
- Alerts by mail, the weekly report and the daily health report are settings
  of the always-on part, not parts of their own.
- **A part that is switched off is seen by nobody except an admin, in
  settings**, where it is listed with its switch. Editors never meet a dead
  tab or a greyed control.
- **Switching a part off hides it and stops its work. It never deletes
  anything.** Each part owns its own records, so updating, switching off or
  removing one can never damage another's.
- **An editor's computer runs one app with one version.** Every optional part
  is in it and can be switched on or off; it updates as a whole.
- Each part's document says what it needs from the core and from other
  parts, and exactly what a person sees when that other part is off.

## 3. One look

"I also want to keep the exact same visual style." And: "The whole product
takes the timeline cards editor's look."

- There is one look, on every surface: the dashboard's pages, the b-roll
  archive, music, YouTube downloads, the Footage Sorter, the app on an
  editor's computer, Timeline Cards, and the page a client opens from a
  link, which carries the studio's own name and mark.
- The look is given in the look book: every colour, typeface, size, spacing,
  shape and motion as plain values, how each kind of control looks and
  behaves, and reference pictures of every Timeline Cards screen.
- The Timeline Cards editor's own screens are matched exactly. Every other
  screen is drawn in that look from what this specification says is on it.
- Nothing a person reads contains a long dash. Use a hyphen with spaces, a
  colon, or two sentences.

## 4. What is kept exactly

- **In the Timeline Cards editor, everything a person sees and touches**:
  every screen, panel, key, mouse and touch gesture, game-controller button,
  label, message and state. These were shaped by months of his use. Where
  this specification marks a passage `Exact`, it is to be built as written.
- **The cut list is a `.cut.md` file "as it currently is".** The file's
  format is given exactly, so that every cut list the studio already has
  opens unchanged.
- **The exports**: "We should also keep the ability to export an xml otio edl
  and a txt script." Reading such a file back in is kept on the same footing.

## 5. The dashboard's shape

"It should focus on UX cleanliness."

- **An Overview page is the home page.** It shows problems, health, a summary
  of syncing, the state of each part, the version, and quick links to the
  settings people use most.
- **A Projects page.** "You can see all the projects, click into them to
  manage them, tick them, untick them, do all the relevant stuff."
- **Transfers is a page of its own.**
- **"Sync" in the menu bar opens a dropdown** holding three entries:
  Projects, Transfers, and the per-computer view (which computer is syncing
  what, and how far along). It opens when rolled over with a mouse and when
  tapped on a touch screen.
- **Settings is laid out logically.** The specification lists every setting
  by what it does, with no arrangement. The builder proposes the menu and
  the grouping of settings from that list, and the owner approves the map
  before any page is built.
- **A general search in the menu bar** jumps to any part, any page, any
  setting, and finds projects, computers and people.
- **A second search inside Settings**, for settings only.
- Every page, part and setting therefore has a plain name and a few search
  words in this specification.

## 6. Timeline Cards: footage in, the board, the cut, the hand-over

Timeline Cards is one part with four steps in order: clips dropped in and
made ready, the board, the cut, and the hand-over to the editing program.
Only the last step knows about an editing program.

### Footage in, ready to cut

"The whole pipeline should be automated, from dragging in to transcription
to translation and word timing etc."

- **Drop clips in and they process themselves.** A person drops an
  interview's clips into the product and does nothing more. The product
  works out which clips are the same interview seen by different cameras and
  recorders, lines them up by their sound, makes the multicam, transcribes
  the speech, translates it, and times every word, so that any part of the
  English stands for exact words of the original. When it finishes, the
  interview is ready to cut.
- **Every step runs on its own.** No step waits for a person to start it.
- **Nothing outside the product is needed**: no separate notes program, no
  folder a person must keep in a certain shape, and no editing program open
  while footage is processed.
- **It is not tied to one editing program.** "This is for potential clients
  down the line so it's NLE-agnostic." Everything up to the finished cut
  works with no editing program at all. The hand-over is written for DaVinci
  Resolve first; each further program is a part of its own when a client
  needs it.
- **Everything the product decides on its own can be set by hand.** "For the
  multicam generation and transcript names and everything there must always
  be a manual override of everything." Which clips make an interview, which
  camera or recorder is which angle, how the angles line up, what the
  interview, the multicam and the transcript are called, who is speaking,
  the language, where paragraphs break, which lines are questions, the
  translation, the word timing, the themes and the first sort: a person can
  see each one and set it by hand. A value set by hand is never overwritten
  by a later automatic pass. A decision with no way to override it is a
  defect.
- **One file per interview holds everything together**: the text, the
  translation, the time of every word, and which English words go with which
  original words. They are tied to each other directly and never found again
  by matching text, so correcting a word cannot loosen its timing or its
  translation.
- **There is always a readable Markdown transcript that can be taken
  elsewhere.** It is a copy the product writes and keeps in step. The product
  does not promise to follow changes made to the copy in another program.
- **The studio's existing transcripts are brought in once**, and every
  paragraph keeps the reference it already has, so every existing cut list
  still points at the right paragraphs.

### The board

"It should be a kind of kanban which you can do manually by dragging
paragraphs out from a transcript into, create your own column with themes
and drag things around, etc., and it should still be in .md format so that
it stays in the same format as the transcripts themselves and can be
transferred elsewhere."

- A board inside Timeline Cards for planning the film before cutting.
  Columns are themes. Cards are paragraphs of the transcripts.
- A person drags a paragraph out of a transcript onto the board, makes
  their own columns, names them, and drags cards and columns around.
- The board is a Markdown file, complete in itself and readable anywhere.
- **The product makes the first sort, and the board can also be worked by
  hand.** Proposing themes and placing every paragraph in one is the last
  automatic step of processing. A person can instead start from an empty
  board.
- **A place on the board to write notes, and the assistant can be called to
  update the board from them.** He writes his ideas on the board and calls
  the assistant to rearrange the board to follow them. The assistant acts
  only when called, and what it changed can be seen and undone.
- The board follows the editor's ways of working: the same look, touch
  first, and where the same act exists in both (select, move, undo), the
  same keys and gestures.
- Nothing goes from the board straight to an editing program. The board
  hands to the cut.

### The cut

- **No translate controls in the editor.** A card's English is picked, on its
  own, from the part of the transcript the card covers.
- **The join check stays**: the editor reads a join between two cuts afresh
  and warns when the meaning or the grammar broke.
- There is one board and one editor.

## 7. What the studio already holds must still be there

The people, their computers, what each computer syncs, the cut lists, the
transcripts, the b-roll and music libraries, the links already handed to
clients, and the rest of what the studio has built up are carried over. The
list is in the carry-over companion to this specification.
