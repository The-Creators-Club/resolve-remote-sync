# bug-comp-syncthing - companion lane C: sequencer, Syncthing lane/supervisor/admin, shared + borrowed folders, selection, file moves
Files read (approximate coverage): sync/syncthing_lane.py (all), sync/syncthing_supervisor.py (all), sync/syncthing_admin.py (all), sync/shared_folders.py (all), sync/borrowed_folders.py (all), selection.py (all), file_moves.py (all), sync/sequencer.py (~90%: everything from the constants through _wait_or_wake; skimmed the imports). Followed calls into app.py (_apply_file_moves, halt_all_sync/_stop_lanes/_pause_lane_c_folders, _synced_project_rels) and dashboard api._expand_includes / collector enforce / db.fetch_selections.
Tests/probes run: two ad-hoc snippets from the companion venv in the scratchpad (probe_fm.py: apply_move with a proxy rename that raises; probe_bor.py: Sequencer._build_borrowed on upload-only selections). No suite run.

## Findings

### bug-comp-syncthing-1 - a proxy that cannot follow turns a completed move into a "failed" one, and the retry then drops the relink
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/file_moves.py:574-579 (and the resume arm at :446-485)
- What: `apply_move` puts `src.replace(dest)` AND `move_proxy_siblings(src, dest)` in one `try`, so an OSError from a proxy (Windows WinError 32 on a proxy Resolve has open in proxy mode) returns `(False, "could not move it on this machine")` after the original has already moved. app records `record_attempt_failed` (state `retryable`, not `applying`), and the retry finds `src` gone: the resume arm only trusts an `applying` row or a lane B relocation, so it answers `(True, "nothing at the old path on this machine", None)`.
- Failure scenario: editor on Windows with Resolve in proxy playback; admin moves a clip. Attempt 1: original moves, proxy replace raises -> tray toast says the copy could NOT follow and the dashboard is told `retrying`. Attempt 2 (10 min later): ok with paths=None -> app skips the Resolve relink and sets relink_pending False, so the clip stays Media Offline; the proxy is left under the old `Proxy/`, where lane B later trashes it as extraneous and re-downloads the new one. This is the same shape the dashboard side fixed as a two-phase move in KNOWN_BUGS (the `_move_proxy_siblings` inside the fatal try), still present on the companion.
- Evidence: probe_fm.py -> `attempt1: False could not move it on this machine: [Errno 32] ...`, `orig at old? False orig at new? True`, then `attempt2: True nothing at the old path on this machine None`, `proxy left behind: True`.
- Ledger: new (companion twin of the dashboard-side fix at KNOWN_BUGS ~6745)
- Suggested fix: move the proxy loop out of the fatal try (per-proxy try, count failures into the detail) so a moved original always returns ok with its paths; and let the resume arm also accept a `retryable` row whose intent paths show src gone and dest present.

### bug-comp-syncthing-2 - an UPLOAD-ONLY borrower still builds a borrowed lender, so the tray tells the editor to chase an admin who can never fix it
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/sequencer.py:1628-1664 (_build_borrowed); consumed by sync/borrowed_folders.py:344-360 and sync/shared_folders.py:167-169
- What: `_build_borrowed` skips only invalid items, never upload-only ones, so an upload-only borrower's `includes` land in `_borrowed_lenders`. The dashboard's enforce cycle shares a lender's folder only for FULL borrower ticks (collector.py ~1416, `sync_modes=(db.SYNC_MODE_FULL,)`), so the offer never comes and BorrowedFolderManager records `not-offered` for ever.
- Failure scenario: a project that borrows `Lender/Interviewees` is ticked upload-only on a laptop. Lane C's detail and the report carry "Lender has not been shared with this computer yet. Ask your admin to approve it." permanently; the admin finds nothing to approve because not sharing is correct. If the lender folder already exists locally from an earlier full tick, the manager keeps it restricted-but-unpaused, i.e. still pulling the borrowed subtree DOWN on a tick whose whole promise is that nothing comes down. The borrowed rel also enters `known_rels` / `rel_to_slug_with_borrowed`, attributing that subtree to a project that never runs it.
- Evidence: probe_bor.py -> `lenders for an UPLOAD-ONLY borrower: {'lender': {'rel': '2026/FF5/Lender', 'subs': ['Interviewees'], 'borrowers': ['borrower']}}`.
- Ledger: new
- Suggested fix: in `_build_borrowed`, `continue` on `_item_upload_only(item)` (and mirror it in the dashboard's `_expand_includes`, which also expands includes for upload-only rows).

### bug-comp-syncthing-3 - a FULL borrower whose lender is ticked upload-only never gets the borrowed subtree, on either side of the wire
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/sequencer.py:1651 and :1659 (_build_borrowed); dashboard/src/ccsync_dashboard/api.py:2291 and :2304 (_expand_includes)
- What: both sides decide "the lender's own runs cover this subtree" from the selection WITHOUT the mode: the dashboard marks the include `covered` when the lender slug is in `rows` (fetch_selections, every mode), and the companion drops it when the subpath is under any rel in `rel_to_slug` (upload-only rels included) and treats the lender as selected when it is in `slug_to_item`. An upload-only lender's turn is lane A alone, so nothing covers it. This is the CLAUDE.md rule "every reader of selections that decides what comes DOWN must ask for sync_modes=(FULL,)" broken twice.
- Failure scenario: laptop ticks Borrower (full) and Lender (upload-only, to back its originals up). Borrower's borrowed `Lender/Interviewees` never comes down: no lane B proxies, no lane C files, no borrowed lender folder, and no problem sentence anywhere, because nothing thinks anything is missing.
- Evidence: probe_bor.py case 2 -> `full borrower of an upload-only lender -> includes run: {} lenders: {}` (with or without `covered`, since the companion's own rel check drops it too). Read api.py:2291-2315.
- Ledger: new
- Suggested fix: compute `selected` / `selected_rels` / the lender test from FULL items only on both sides (dashboard: `selected = {r["slug"] for r in rows if r sync_mode is full}`; companion: exclude upload-only slugs and rels in `_build_borrowed`).

### bug-comp-syncthing-4 - a sequencer thread that outlives stop() can unpause a folder AFTER the halt paused it
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/sync/sequencer.py:2811-2812 (_wait_for_folder_sync then _verify_current_folder_unpaused with no stop check); sync/syncthing_admin.py:577-579 (accept_folder ends in an unconditional unpause); app.py:7642-7649 (halt order)
- What: `halt_all_sync` calls `_stop_lanes()` (sequencer.stop(): 5 s wait for the lane C sweep, then a 10 s join) and only then `_pause_lane_c_folders(True)`. The lane C turn has two writes that are not behind a stop check: `_verify_current_folder_unpaused` runs straight after `_wait_for_folder_sync` returns (which it does BECAUSE stop was set), and `_maybe_auto_accept` -> `accept_folder` finishes with `set_folder_paused(id, False)`. One loop of `_wait_for_folder_sync` can take folder_status (5 s) + completion (5 s per device) + a selection fetch (5 s), and set_ignores inside accept_folder has a 30 s timeout, so the join can time out with the thread still in flight.
- Failure scenario: admin presses a fleet halt while a slow Syncthing/dashboard (the usual reason for a halt) has the sequencer inside one of those calls. stop() returns at 10 s, the halt pauses every folder, then the old thread's verify sees the current project's folder "still paused after its lane C turn" and PATCHes it back to running (or accept_folder unpauses the new folder). That folder syncs through the whole halt while the tray says nothing is sharing, and nothing re-pauses it.
- Evidence: read-through of the call order; no live repro (would need a stalled Syncthing).
- Ledger: related to sync-safety-2 / CR-48 (halt must hold lane C down)
- Suggested fix: check `_stop_event`/`_resume_event` before `_verify_current_folder_unpaused` and pass a "still allowed?" predicate into accept_folder's final unpause; or have the halt consult `halted()` inside `_set_paused(..., False)` so no sequencer path can release a folder while the latch is on.

### bug-comp-syncthing-5 - borrowed-folder negations are escaped with backslashes, which Syncthing on Windows reads as path separators
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/sync/syncthing_admin.py:198-206 and :235-239
- What: `escape_ignore_glob` prefixes `\` to `[ ] { } * ?`. Syncthing's ignore documentation says escaping is not supported on Windows because `\` is the path separator there; but `[`, `]`, `{`, `}` ARE legal in Windows file names. So on a Windows editor a borrowed subtree named e.g. `Interviews [raw]` is written as `!/Interviews \[raw\]`, which Syncthing reads as `Interviews /[raw/]`.
- Failure scenario: the negation matches nothing, the trailing `**` ignores the whole lender, and the borrowed subtree silently never arrives on Windows (it works on the Mac, which does honour `\`). No problem sentence: the restricted list is "confirmed" because it reads back exactly as written.
- Evidence: code read; Syncthing behaviour from its documented escaping rule, not reproduced (no scratch Syncthing run, per the brief's no-live-process rule).
- Ledger: new
- Suggested fix: on Windows, escape with a character class instead (`[[]`, `[]]`, `[{]`, `[}]`) or emit `#escape=|`-style directive if the fleet's Syncthing supports it; add a test that runs the pattern through Syncthing's matcher on both platforms.

### bug-comp-syncthing-6 - the cached plan is not keyed by editor, so a sign-in as someone else can run the previous person's projects
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/selection.py:361-373 (_write_cache), :442-449 (load_cached), :573-585 (get)
- What: `selection.json` stores `{fetched_at, response}` with no editor, and nothing clears it on sign-out. `get()` falls back to it whenever `fetch()` returns None, which includes "no identity yet" and every failed fetch for the NEW editor; `_startup_unpause` also reads it. The in-memory TTL is editor-keyed, the disk fallback is not.
- Failure scenario: a shared or re-assigned machine: editor A signs out, B signs in while the dashboard is restarting (or B's first fetch 401s). The sequencer runs A's plan from the cache: lane A uploads and lane B downloads A's projects' proxies onto B's session's disk until a live fetch succeeds.
- Evidence: code read; grep shows no writer or deleter of selection.json outside selection.py.
- Ledger: new
- Suggested fix: write the editor (and machine) into the cache payload and have `load_cached()` refuse a cache whose editor differs from `_editor_name_fn()`.

### bug-comp-syncthing-7 - re-pointing a shared asset folder neither moves its contents nor creates the path/marker, and reports "repaired"
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/sync/shared_folders.py:369-374
- What: when the folder's path differs from `<local_root>/Assets/Luts`, `_reconcile_one` PATCHes the new path onto the running folder with no pause, no `_mkdir_allowed`, no mkdir and no move of the old directory (the borrowed manager's `_repoint` does at least move/mkdir). Syncthing only creates a folder root and `.stfolder` for a newly added folder, so a re-pointed one comes up in "folder path missing"/"folder marker missing", and the outcome "repaired" CLEARS any FolderProblems entry. CR-278's heal skips it too (it needs the marker to exist).
- Failure scenario: local_root changes (canonical_prefix/tree_name change, a Mac volume remounted under a new name): the LUT library folder is re-pointed at an empty non-existent directory, sits in error for ever, and no tray line, lane detail or report field says so (lane C only judges selected folders).
- Evidence: code read; the Syncthing behaviour is its documented "move the folder including .stfolder before changing the path" rule, not reproduced.
- Ledger: new
- Suggested fix: pause, `_mkdir_allowed`, move the old directory when it exists and the new one does not (as borrowed `_repoint` does), create the marker, then re-point; and do not return "repaired" until a db/status read shows the folder out of error.

## Coverage note
Did not trace sync/repath.py (another territory) beyond the relink call, did not run any suite, and did not verify Syncthing ignore/escape or path-change behaviour against a real Syncthing (no scratch instance started, per the no-live-process rule). The CR-319 skip-ahead was read end to end and I found nothing wrong in it.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/api.py:2291: `_expand_includes` reads every-mode `rows` for `covered` and expands includes for upload-only rows (the dashboard half of findings 2 and 3).
- companion/src/ccsync_companion/app.py:7642: `halt_all_sync` stops the sequencer before pausing lane C, which gives finding 4 its window; pausing first (or re-pausing after the join) would close it from the app side.
