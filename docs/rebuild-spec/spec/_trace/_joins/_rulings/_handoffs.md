# What one fixer left for another

Stays behind. Kept by the lead while the fixers run: things a fixer could not
do because they belong in another piece, and headings that were renamed or
removed (so pointers elsewhere can be repaired in one pass at the end).

## Headings removed or renamed

- sync-1: REMOVED "Unticking can be undone within a minute at no cost"
  (sync-1 F4). Any pointer to it elsewhere must go or be repointed.
- sync-1: the heading "The editor is told about files that will never upload
  because of a name clash or a wrong clock" no longer fits its text
  (future-dated files do upload). Kept for now because other pieces point at
  it word for word; rename it in the pointer pass and repoint them.

## For another piece's fixer

- to resolve-on-the-editors-computer (from sync-1): sync-1's passage on
  asking for originals from inside Resolve is now only a pointer. Four
  details lived only there and need a home in the Resolve piece: the
  "CC Sync: " answers shown in Resolve's console; "Resolve shows new script
  entries only after it restarts"; the message when Resolve does not seem to
  be installed; and that asking never flashes a window on Windows. The old
  text is in git: `git show cba9656:docs/rebuild-spec/spec/sync-1.md`,
  heading "An editor asks for originals from inside Resolve".
- to sync-2 (from sync-1): three sentences of sync-1's old list of reasons
  are not in sync-2's table: "This computer is not set up for syncing yet.";
  "This computer works straight off the server, so there is nothing to
  sync."; "sync off: this computer works directly off the server". GIVEN to
  the sync-2 fixer in its prompt.
- to broll (from editor-app): broll's menu lines still carry "indexing
  model" and "Uploading indexed b-roll…", which describe analysis done on
  the editor's computer and then uploaded (an arrangement). Reword there.
  The editor-app fixer did not copy those two lines into the app's menu.

## Sub-topic headings that still name something the owner cut

- accounts-privacy-legal: the `##` sub-topic "Suspending, disabling and
  removing a person" (disabling was folded into suspending, answer 9.4). A
  `##` heading is tied to the bundle and to the knowledge base's sub-topic
  of the same name, so a fixer may not rename it. Rename it by hand at the
  end, in the piece, in `_raw/spec/accounts-privacy-legal.md` and wherever
  the name is used, and repoint.

## A mistake of the lead's, and what it cost

The first five fix lists (dashboard-1, sync-1, editor-app,
server-install-and-running-1, sync-2) were made by a script that showed the
settler's note only for verdicts other than `apply`. A finding the reader had
left to the owner and the settler had then settled with `apply` therefore
still read as waiting for the owner, and the fixer left it alone. Fixed in
`build_join_bundles.py`; those five fixers are sent back to their rebuilt
lists.

## Headings renamed or removed (continued)

- dashboard-1: RENAMED "An admin resumes a computer's stopped proxy
  download" to "An admin resumes a computer's stopped downloads".
- server-install-and-running-1: RENAMED "Set-up task: reaching the
  dashboard over the private network" to "Set-up task: Connect to your
  private network", and "The server's way in to the NAS" to "Set-up task:
  Connect to your NAS".
- sync-2: RENAMED "Footage travels only over the studio's own private
  network" to "The way footage travels is chosen by measuring real
  transfers". REMOVED "A computer or a person can have a chosen project that
  new footage lands in" (with its setting) and the setting "Drive
  reminders".
- editor-app: ADDED "The editor opens Timeline Cards in a window of its own
  from the app".

## For another piece's fixer (continued)

- to accounts-privacy-legal (from server-install-and-running-1): the admins
  are named in the browser set-up's "your admin account" task, not at
  install. SENT to the accounts fixer.
- to server-install-and-running-2 (from part 1): "a random password the
  editor never needs to know" must go (accounts-privacy-legal F13). GIVEN to
  its fixer in its prompt.

## For the pointer pass (headings to rename by hand at the end)

- accounts-privacy-legal: "The admins are named at install, and are never
  the NAS's own administrator": the text now says they are named in the
  set-up's admin account task; "at install" is wrong.
- accounts-privacy-legal: "A studio can keep editors to file transfers only
  on the NAS" reads as a choice; editors are always limited to transfers
  (accounts-privacy-legal F12).
- accounts-privacy-legal: ADDED "Secrets the server is given are kept by the
  server".
- dashboard-1's "An admin forgets a computer" points to the accounts piece's
  `##` "Suspending, disabling and removing a person": repoint when that is
  renamed.
- server-install-and-running-1 (seen by part 2's fixer, not fixed): "Set-up
  checks that the Synology's secure file transfer is switched on" overlaps
  part 2's "On a Synology the file-transfer service must be on and allowed to
  editors"; and "Editor accounts on the NAS are made and managed by the
  dashboard" still speaks of sign-in keys and switching off password
  sign-in, which turns on the approval question (decision page 32, 32.1).
- youtube (seen by whole-product's fixer): the heading "A site decides
  whether signed-in YouTube sessions may be used on editors' computers" no
  longer fits once it describes the one switch "YouTube's extra measures
  against being blocked" (youtube F1). whole-product points to it word for
  word: if it is renamed, repoint whole-product.
- whole-product F8 (a judgement of its fixer): footage-in's tasks and the
  board's assistant are listed with the Timeline Cards features that work
  with only one kind of assistant; the Footage Sorter's Ask with the ones
  that work with any kind. The other pieces say nothing either way.
- to cards-editor-5 (from dashboard-2): it must carry the refusal "this
  request came from another site" under "An edit is refused only for a real
  reason, and never in silence" (cards-editor-5 F7); dashboard-2 now points
  there for it. Check it landed.

## Not covered by any finding, for a later look

- server-install-and-running-1 and dashboard-2 both list the settings Tree
  name, Drive letter, Dashboard address and Folders in every new project,
  under different names ("Where editors see the studio's tree" against
  "Drive letter"). One home and one name each.

## Headings renamed (continued)

- fleet-jobs: RENAMED "A computer's own heavy work comes first" to "Work on
  one computer takes turns". Pointers elsewhere to the old name must follow.
- proxies-and-file-moves: ADDED "Renaming a b-roll collection is a move
  every computer follows".

## Knots between rulings the lead untied while the fixers ran

- The relink ranking: proxies-and-file-moves F12/F13 made the Resolve piece
  its home, resolve F9's Fix read as if the proxies piece held it. Decided:
  resolve-on-the-editors-computer holds it ("An editor relinks offline clips
  to files found in the tree"), in PRX-090's order; the proxies piece points.
- Proxy making as shared work: it keeps its own two rules from lessons
  PRX-030 and PRX-031 (several at once on an idle computer; stops within
  seconds when the person returns and discards the part-made proxy), stated
  in fleet-jobs as how that kind behaves. Never while Resolve is rendering,
  whatever the hold-back setting (lesson PRX-031 amended to say so).
- fleet-jobs now holds the setting for the share of a working computer
  heavy work may use; broll's copy becomes a pointer.
- footage-sorter-and-camera-cards-2: RENAMED "The NAS's footage goes to the
  cloud backup every night" to "The studio's proxies, sound and project
  files go off site every night". Pointers elsewhere must follow.
- youtube: "A site decides whether signed-in YouTube sessions may be used on
  editors' computers" no longer fits its text (it is now the one switch
  "YouTube's extra measures against being blocked"); rename by hand and
  repoint whole-product, dashboard-2 and youtube's own one pointer.
- sync-1: its pointer for asking for originals from inside Resolve should
  name the Resolve piece's "Grading from the server's originals: An editor
  asks for originals from inside Resolve" (it still says "Bins, clip sorting
  and imports"); and its pending mark sync-1-U2 belonged to the passage that
  moved: decide whether it still applies.
- music and broll say heavy work uses no more than "the share that computer
  allows"; fleet-jobs holds that share as a SITE setting an admin sets (60%
  by default, the owner's own figure). Make the two sentences say "the share
  the studio allows" in the last pass.

## More for the last pass (from the Sorter, board and editor fixers)

- cards-footage-in's colour passage points to "Timeline Cards: the board:
  Cards on the board"; the behaviour is "Every interviewee has one colour
  everywhere" under that sub-topic: name the heading. GIVE to the
  footage-in fixer.
- cards-board: "Selecting several cards and acting on them at once" still
  says cards can be deleted, while Delete now sets a card aside. No finding
  says which act deletes a note card on the board. Decide (the editor's
  "Deleting stages cuts on the shelf" rule is the natural one) and fix.
- The words carried for item 29-028 say "the controller's Menu (which
  toggles it)"; the settled rule is Menu tapped = caret in a find box, Menu
  held 600 ms = the help sheet. Change the item's own words in
  spec/_extracts/29.md.
- cards-editor-3's aids table defaults the Fillers aid to "Not read";
  cards-editor-1 says the fillers strike stays off until switched on. Both
  wait for decision 32.3.

## Carried words that now contradict a ruling (change the item's own words)

A piece carries some passages word for word by a `{{id}}` line; a fixer cannot
edit them and wrote an "Except that ..." sentence after each instead. In the
last pass change the item's words in `spec/_extracts/<NN>.md` and take the
"Except that" sentence out again.

- 29-028 (cards-editor-1, perhaps cards-editor-5): "the controller's Menu
  (which toggles it)"; settled: Menu tapped = caret in a find box, Menu held
  600 ms = the help sheet.
- 39-041 (cards-editor-2): the editor reloads and refuses an edit when the
  file changed on disk ("the project file changed on disk -- reloaded, redo
  your edit"); settled by answer 25.5: the change is merged in as edits.
- 40-018 (cards-editor-2): the refusals "no timeline is open" and "that cut
  is no longer on the timeline", notes on draft cards, notes re-matched to a
  card on a timeline; all gone with answer 29.2.
- 28-074 (cards-editor-2): a new gap goes "else at the end"; ruling CE1-038
  refuses a gap at the very end.

## Left open by the fixers, for the lead or the owner

- cards-editor-2: RENAMED "Notes on cards and gaps while a cut is worked on
  a live timeline" to "Notes on cards and gaps go with the cut when it is
  handed over".
- Nothing in the editor's shelf panel shows the board's alternates section
  (its tabs are Staged, with All, Uncategorised and the named categories,
  and Sequences). Where a person sees the alternates the board hands over
  is undecided.
- cards-editor-3: "Clicking a word puts the transcript playhead on it..."
  still lists "the interview's reference audio"; and two lines of "A trimmed
  or split cut's English..." still match by letters (the "other Chinese
  script" line and the one about line-ups from earlier cuts).

## From the cards-editor-4 fixer

- RENAMED four headings (no other piece pointed at the old names): "Timeline
  Cards has its own apps for Windows and Android that show the editor from
  the studio's server" -> "Timeline Cards opens in the editor window on a
  computer and in its own app on Android, from the studio's server"; "In the
  Windows and Android apps, kept cut lists are real files in a folder the
  person can open and move" -> "In the editor window and the Android app,
  kept cut lists are real files in a folder the person can open and move";
  "The Windows app installs per person or runs portable, and runs once" ->
  "On a computer the editor window comes with the one app and updates with
  it"; "The Windows app's window, links, permissions and downloads" -> "The
  editor window's links, permissions and downloads".
- Carried words to change at the source (then drop the "Except that"):
  33-088 (on a computer the editor window uses the one app's dashboard
  address; the server address is the Android app's only); 33-091 (the SERVER
  section is on the Android app's settings page only); 33-052 (on a computer
  the label reads "The editor window's project folder", default folder
  Documents\Timeline Cards on Windows and macOS: the label is the FIXER'S
  wording, no source gives it; decide or describe without quoting); 33-098
  (closing the last editor window leaves the app running; the window opens
  at the dashboard's address; on a Mac downloads go to Downloads; and it
  says the menu bar is hidden until Alt, while cards-editor-5 makes the
  header the window's title bar: make them agree).
- The lead's look-up, extended: the list of episodes shows no occupants at
  all, "is in it now" included (the editor's own code has no such words; they
  were the retired page's). SENT to the fixers of cards-editor-4 and -5.

## The closing pass (the lead, 2026-11-24)

Done:
- No cross-reference points at any of the 14 headings renamed or removed by
  the fixers; of 481 bracketed cross-references, three named a heading by a
  shortened form and were given its full words.
- Five headings renamed by hand everywhere they are used (pieces, traces,
  the capability list, the bundle, the merged lessons): the accounts
  sub-topic is now "Suspending and removing a person"; "The admins are named
  in set-up, and are never the NAS's own administrator"; "Editors are kept
  to file transfers only on the NAS"; "A site decides whether YouTube's
  extra measures against being blocked are used"; "The editor is told about
  files that will never upload because of a name clash, and about a wrong
  clock".
- Carried words changed at their source and the "Except that" sentences
  taken out: 29-028, 39-041, 28-074, 40-018, 33-088, 33-098.
- Three join targets in the traces of dashboard-2 and fleet-jobs named
  properly; the join checks now read only the "Joins with other
  capabilities" section (the fixers' "Joins settled" sections had been
  counted as joins).
- Music's sentence about the share of a working computer now says the
  studio allows it (a site setting), as fleet-jobs holds it.

Still open after the closing pass:
- Four "Except that" sentences remain: cards-editor-4 (the SERVER section
  is on the Android app's settings page only; the panel's label on a
  computer, where no source gives the new label's words), cards-editor-5
  (the Send button, waits for decision 32.8), cards-to-resolve-and-exports
  (item 32-016: a cut not on the timeline goes to its section's shelf; an
  unknown Red marker is a plain heading).
- Carried items 32-014 and 32-007 say the timeline is "read from the project
  library, never from a live Resolve": that names a way the present build
  works. For the blind reader, or change at the source.
- The carried editor-window menu (33-099) still has "Quit", "Open the
  project folder" and "Toggle developer tools"; with the window part of the
  one app, what Quit does is undecided.
- cards-to-resolve-and-exports keeps a refusal ending "needs force: true",
  which shows an inside of the present build.
- server-install-and-running-1 and dashboard-2 both list the settings Tree
  name, Drive letter, Dashboard address and Folders in every new project
  under different names.
- Where a person sees the board's alternates in the editor's shelf panel.
- cards-board: which act deletes a note card, now that Delete sets a card
  aside.
- The eight findings held for the owner (decision page 32) and the render
  test for youtube F6.
