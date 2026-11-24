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
