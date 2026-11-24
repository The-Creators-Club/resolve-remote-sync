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
