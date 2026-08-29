# Undoing a clip-path change CCSync made

*Added 2026-08-17 for `docs/COMMERCIAL_READINESS.md` item 9 ("close the
remaining data-loss edges").*

The companion rewrites paths inside an editor's Resolve project database from
four places. Two of them are **unprompted** — they happen while the editor is
working, with no dialog:

| Where | What it changes | Prompted? |
|---|---|---|
| FIX ALL (`fixer.fix_clip` → `ReplaceClip`) | the clip's **original** path, after copying the file into the tree | yes — the popup |
| Automatic canonical relink (`app._relink_non_canonical`) | the clip's **original** path, `F:\…` → `P:\…` | **no** |
| Automatic proxy repoint (`proxy_relink.apply_relinks` → `LinkProxyMedia`) | the clip's **proxy** path | **no** |
| Post-import canonicalise (`resolve_bridge._canonicalize_imported`) | the clip's **original** path, right after a scripted import | no (part of the import you asked for) |

Resolve's own **Undo does not cover a scripted `ReplaceClip`**. Before
2026-08-17 there was no save, no backup and no record: a wrong `local_root` or
a stale `canonical_prefix` rewrote hundreds of clips with nothing to go back
to. That is what this page is about.

## What now happens before any of those edits

1. **`SaveProject()`** — the editor's own unsaved work goes to disk first.
2. **`ProjectManager.ExportProject()`** into
   `~/.ccsync/resolve_edits/<project>/<timestamp>.drp` — a rollback copy of
   the whole project database, without stills or LUTs (a rollback, not an
   archive).
3. **An undo journal** at
   `~/.ccsync/resolve_edits/<project>/<timestamp>.json`, one file per burst
   of edits, listing every clip with its old and new path and which code
   path asked.

Both the save and the export are **best effort**. Older API builds have no
`ExportProject`, and a project open in a collaboration refuses it. The journal
is the guarantee that always holds — which is why the undo below replays the
journal rather than the `.drp`.

The save point is taken at most once per project per 15 minutes, and the two
unprompted passes may each run at most once per project per 15 minutes.
Held clips are logged, not dropped; **Tray → Advanced → Scan whole project**
runs the pass immediately.

## Undoing

**Tray → Advanced → "Undo the last clip-path change CCSync made…"**

**Or from the dashboard, on somebody else's computer** (SYS-15b, 2026-08-29):
Settings → RECOVERY → "CC Sync changed clip paths in somebody's Resolve
project and they are wrong", which lists what each machine has recorded and
asks it to replay one. It goes out on the report channel like the fleet halt
and CR-45's [ RESUME ], and it runs **exactly the code below** on that
machine: same journal, same `undo_last_relink`, same refusals. An undo asked
for while Resolve is closed, or while a different project is open, is answered
"still trying" and repeated on every report until it can run - so the admin's
click is not lost, and the wrong paths are not left in place with somebody
believing they were put back. What the dashboard knows about is what that
computer has reported: names, times and counts, never the journal entries.

It reads the newest journal **for the project that is open in Resolve right
now** and replays it **in reverse**, so a clip touched twice in one burst ends
up at the path it had before the burst started. A clip that is no longer in
the media pool is reported as skipped, never guessed at. The undo itself is
not journalled, so pressing it twice does not redo the change.

**The journal and the open project must match** (comp-resolve-2, 2026-08-21).
This used to replay the newest journal of *any* project against whatever
project happened to be open, matching clips by file path alone - and every
project shares the paths under `Assets` (music beds, archive b-roll), so one
project's journal could rewrite another project's music clip to a
machine-private `F:\…` spelling, unjournalled and therefore not itself
undoable. Now, when the last change CCSync made was in a different project,
the undo is **refused and says which project it was**:

> CCSync has not changed any clip paths in "FF4". The last change it made was
> in "Season 1 EP3": open that project and undo there.

Open that project and press it there. A journal that names no project at all
(the pre-2026-08-21 shape, or a build that could not read the name) is still
replayable, because refusing it would leave that editor with no rollback at
all.

Then the tray reports, e.g.:

> Put 158 clip path(s) back the way they were (from 20260817-1042.json).

## Restoring the exported project instead

When the journal is not enough — the project was closed and reopened, clips
were deleted since, the edit went somewhere this cannot follow — import the
`.drp`:

1. Resolve → **Project Manager** (Home icon).
2. Right-click in the project list → **Import**.
3. Pick the newest `.drp` under `%USERPROFILE%\.ccsync\resolve_edits\<project>\`
   (`~/.ccsync/resolve_edits/<project>/` on a Mac).
4. It imports as a **separate project** — nothing is overwritten. Compare, then
   keep whichever is right.

If the folder holds no `.drp`, the export was refused on this machine (see
above); use the undo action, or read the `.json` and relink by hand — it names
every old path.

## Housekeeping

* Journals and exports older than 60 days are swept on the next write.
* Nothing here syncs: `~/.ccsync` is outside the tree, so an editor's journal
  never reaches the NAS or another machine.
* The log line to look for when something went wrong:
  `resolve: saved '<project>' and exported a rollback copy to …`, or the
  WARNING that names why there is no rollback copy.

## Rehearsing the destructive paths

Two config switches (`~/.ccsync/config.toml`) make the two biggest actions
report their plan and change nothing. Both default to off:

```toml
fixer_dry_run = true   # FIX ALL logs "would copy X -> Y, would relink N items"
proxy_dry_run = true   # the proxy generator logs "would encode X -> Y"
```

Use them on a machine whose `local_root` or drive mapping is in doubt, then
turn them off. `fixer_dry_run` is read once per process — restart the tray
after changing it.
