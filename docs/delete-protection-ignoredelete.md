# Delete protection for lane C — `ignoreDelete` on project + asset folders

**Status: proposed patch, not yet implemented (2026-08-11).** Design agreed;
this is the implementation plan and the operational consequences to sign off on
before it lands.

## The gap this closes

Lane C (Syncthing, `sendreceive`) carries every non-video project file
bidirectionally: `Audio/Music`, `Audio/Voiceover`, `.drp`, AE comps, `Subs`,
etc. Three delete scenarios are already defended:

- **Whole project folder deleted** (marker included) → Syncthing sees `.stfolder`
  missing and stops the folder in an error state instead of propagating
  (AUDIT_2 DEL-1; the companion deliberately never recreates the marker,
  `rclone_lane.py:792-798`).
- **Whole drive unplugged** → the root guard stands the lanes down and
  `manifest.py` keeps its last scan, so an absent root never reads as a mass
  delete.
- **Any propagated delete** → 30-day staggered versioning is the recovery floor
  (AUDIT_2 DEL-6, `FOLDER_VERSIONING` in `syncthing_admin.py:133-136`).

The remaining hole is the common one: an editor deletes **a single file** (one
audio cue, one timeline) while the folder marker is intact. Syncthing sees a
legitimate deletion with a healthy folder and **propagates it to the NAS and
every other editor**. Versioning makes it *recoverable* for 30 days, but it is
still removed from the live tree everywhere — recovery, not prevention.

This patch adds **prevention**: no device ever *applies* a delete it receives,
so an accidental single-file delete only ever removes the file on the machine
where it was made. The authoritative NAS copy and every other editor's copy
survive untouched.

## Mechanism: Syncthing's `ignoreDelete`

`ignoreDelete` is a per-folder boolean in the Syncthing folder config (a peer of
`type`, `paused`, `versioning`). Its semantics are **directional and
non-obvious**, confirmed against the Syncthing docs:

> A folder with `ignoreDelete` enabled does **not apply deletions it receives**
> from other devices, but it **still propagates its own local deletions**
> outward.

So the flag protects the device it is set *on*, against deletes made
*elsewhere*. To protect the whole fleet from one editor's slip, it has to go on
**every device except the one that made the delete** — i.e. on the NAS and on
all editor folders. Because every folder carries it, the net effect is:

- A delete only removes the file on the machine that made it.
- The NAS (authority) and every other editor keep the file automatically.
- The 30-day versions remain as a second-line net for the deletes that *are*
  honoured (i.e. the deleter's own local copy) and for reconciliation.

Docs / discussion:
- <https://docs.syncthing.net/advanced/folder-ignoredelete.html>
- <https://forum.syncthing.net/t/ignore-deletes-done-right/18078>

## The tradeoff to sign off on (this is a policy change, not just a flag)

With `ignoreDelete` on the NAS *and* all editors, **deletes effectively stop
propagating destructively cluster-wide.** That is the point — but it means:

1. **A genuine, wanted delete no longer cleans itself up.** Removing a file for
   real now needs an explicit action (see "How to really delete" below), or the
   file lingers on every machine that ignored the delete. For a footage / audio
   / asset library where a delete is almost always a mistake, this is usually
   the *desired* posture — but it is a deliberate policy choice, and the
   workflow owner must accept it.
2. **The deleter and the rest sit "out of date" against each other** until
   reconciled — Syncthing's own docs call two-way ignore-delete a "confusing"
   state. The file is not *lost* anywhere except the deleter's own disk; the
   index just shows a standing disagreement (the deleter is missing a file the
   others have; the others are "behind" on a delete they will never apply).
3. **Recovery to the deleter's own machine is not automatic.** Their local copy
   is gone by their own action. It comes back only when the file is *modified*
   on an `ignoreDelete` peer (a modification outranks the tombstone and does
   propagate) — i.e. a re-touch on the NAS — or is restored from the 30-day
   version history.

If the fleet ever needs a mode where an editor "owns" a project and their
deletes *should* win, that is a different design (`receiveonly` editor folders
plus an explicit publish/override path) and is out of scope here.

## The patch

The change is exactly parallel to how staggered versioning is provisioned
today: set at folder creation in every provisioning site, and retrofitted onto
existing folders by an idempotent per-turn PATCH. `ignoreDelete` is a plain
`true`, so no shared constant is needed (unlike `FOLDER_VERSIONING`), but the
call shape mirrors `ensure_versioning` one-for-one.

### 1. Companion — `sync/syncthing_admin.py`

**a. Set it at creation** in `accept_folder`'s `folder_config`
(`syncthing_admin.py:373-383`), beside `"versioning": dict(FOLDER_VERSIONING)`:

```python
folder_config = {
    "id": folder_id,
    "label": label,
    "path": local_path,
    "type": "sendreceive",
    "paused": True,
    "fsWatcherEnabled": True,
    "ignorePerms": False,
    "versioning": dict(FOLDER_VERSIONING),
    "ignoreDelete": True,          # <-- new: don't apply deletes from the cluster
    "devices": [{"deviceID": offered_by_device_id, "introducedBy": ""}],
}
```

**b. Add an idempotent retrofit** mirroring `ensure_versioning`
(`syncthing_admin.py:310-328`) so folders accepted by an older companion or by
hand get the flag on the next turn:

```python
def ensure_ignore_delete(self, folder_id: str, folder: Optional[dict] = None) -> bool:
    """PATCH ignoreDelete=true onto a folder that lacks it.

    Deletes are near-always mistakes in an asset/audio tree; a folder
    with ignoreDelete does not apply a delete another device made, so an
    editor's accidental single-file delete never removes the NAS or
    another editor's copy. Returns True when a PATCH was issued. Pass
    `folder` to reuse a config the caller already fetched. See
    docs/delete-protection-ignoredelete.md for the fleet-wide policy this
    assumes (real deletes need an explicit prune)."""
    if folder is None:
        folder = self.get_folder(folder_id) or {}
    if (folder or {}).get("ignoreDelete") is True:
        return False
    log.info("syncthing: folder %s had no ignoreDelete -- adding it", folder_id)
    self._write_request("PATCH", self._folder_path(folder_id), {"ignoreDelete": True})
    return True
```

The partial PATCH is safe: `ensure_versioning` already PATCHes a single
top-level key (`{"versioning": ...}`) and Syncthing merges it, so
`{"ignoreDelete": True}` behaves identically.

### 2. Companion — per-turn reassert, `sync/sequencer.py`

In `_reassert_folder_policy` (`sequencer.py:1181-1217`), call it right after
`ensure_versioning`, and treat it the same way — **advisory, never blocks the
unpause** (a missing `ignoreDelete` is a policy gap, not a lane-direction
violation, exactly like versioning):

```python
try:
    self.admin.ensure_versioning(slug)
except Exception as exc:
    if _is_not_found(exc):
        return True
    log.exception("sequencer: could not ensure versioning for %s", slug)
try:
    self.admin.ensure_ignore_delete(slug)
except Exception as exc:
    if _is_not_found(exc):
        return True
    log.exception("sequencer: could not ensure ignoreDelete for %s", slug)
return True
```

### 3. Companion — shared asset folders, `sync/shared_folders.py`

`SharedFolders` already calls `ensure_versioning` per shared-asset folder
(`shared_folders.py:132`). Add the sibling call so `Assets/Luts` and
`Assets/Stills` get the same protection:

```python
if self.admin.ensure_versioning(folder_id, folder):
    ...
if self.admin.ensure_ignore_delete(folder_id, folder):
    ...
```

### 4. Server — `server/setup_syncthing_folder.py`

Add `"ignoreDelete": True` to the generated `folder_config`
(`setup_syncthing_folder.py:424-444`), beside the staggered `versioning` block,
and mention it in the docstring's provisioning list (`:31`). This is the NAS
side — the authority whose copy must survive.

### 5. Dashboard — `dashboard/src/ccsync_dashboard/provision.py`

Add `"ignoreDelete": True` to **both** `build_folder_config`
(`provision.py:294`) and `build_shared_folder_config` (`provision.py:134`),
beside their `versioning` blocks, so the collector's provisioning path sets it
too.

## Behaviour on existing folders (rollout)

No re-provision needed. The per-turn `ensure_ignore_delete` self-heals the whole
fleet exactly the way `ensure_versioning` did after DEL-6: on each folder's
first turn after the companion upgrade, one PATCH lands the flag and logs a
single INFO line. Server/dashboard changes only affect folders created *after*
the deploy; the companion retrofit covers everything already out there.

Expect a one-time wave of `folder <id> had no ignoreDelete -- adding it` INFO
lines fleet-wide on first launch after upgrade, then silence.

## How to *really* delete something (operational runbook)

Because no device applies a received delete, a genuine prune needs an explicit
step. Document one of these for admins; the first is simplest:

- **Re-index / accept the loss per machine.** Delete the file on the NAS *and*
  on each editor that still has it. Tedious but unambiguous; fine for rare
  one-offs.
- **Temporarily lift the flag** on the target folder (PATCH
  `{"ignoreDelete": false}` via the dashboard admin API), delete once, let it
  propagate, then re-assert. The next `ensure_ignore_delete` turn puts the flag
  back automatically, so "temporarily" is self-correcting — but there is a
  window where deletes propagate normally, so do it deliberately.
- **Future nicety (not this patch):** a dashboard "purge this file for real"
  admin action that scripts the lift → delete → re-assert, so no one hand-edits
  Syncthing config. Worth a follow-up if real deletes turn out to be frequent.

Getting an accidentally-deleted file back onto the deleter's *own* machine:
re-touch it on the NAS (a modification propagates through `ignoreDelete`), or
restore from the folder's 30-day `.stversions`.

## Tests

Mirror the versioning coverage:

- `companion/tests/test_syncthing_admin.py`: `ensure_ignore_delete` is
  idempotent (no PATCH when already `true`), PATCHes when absent/false, and
  `accept_folder` writes `ignoreDelete: True` in the creation body.
- `companion/tests/test_sequencer.py`: `_reassert_folder_policy` calls
  `ensure_ignore_delete`, a failure is logged but does **not** block the unpause
  (matches the versioning contract), and a 404 is treated as "not configured
  here", not a failure.
- `server/tests/` + dashboard provision tests: the generated folder config
  carries `ignoreDelete: True` for both project and shared-asset folders.
- **Cross-file parity test.** `ignoreDelete: True` now lives in four hand-kept
  copies (companion `accept_folder`, server `setup_syncthing_folder`, dashboard
  `build_folder_config` + `build_shared_folder_config`), the same drift hazard
  the repo already guards for versioning and `.stignore`. Add it to the existing
  cross-component parity test (`server/tests/test_cross_component.py`) so the
  four cannot diverge.

## Pre-flight to confirm before merge

- **Syncthing version acceptance.** The fleet may run either Syncthing v1 or v2
  across machines; `ignoreDelete` has existed since v1.0, and the partial
  PATCH is the same shape as the working versioning PATCH, but confirm the write
  round-trips on whatever is actually deployed (base rig + one editor) before
  relying on it. A folder that silently drops the key would leave the fleet
  believing it is protected when it is not — verify with
  `GET /rest/config/folders/<id>` after the first `ensure_ignore_delete` turn.
- **Policy sign-off** on the "real deletes need an explicit prune" consequence
  from the workflow owner. This is the load-bearing decision, not the code.

## Incidental noticed while mapping this (not part of the patch)

The staggered-versioning `maxAge` disagrees between sides: the companion keeps
**30 days** (`FOLDER_VERSIONING`, `maxAge 2592000`, `syncthing_admin.py:135`)
while the server and dashboard provision **365 days** (`maxAge 31536000`,
`setup_syncthing_folder.py:444`, `provision.py:157`/`:316`). Whichever wrote the
folder last wins. Worth reconciling to one intended retention, but it is a
separate decision from this patch.
