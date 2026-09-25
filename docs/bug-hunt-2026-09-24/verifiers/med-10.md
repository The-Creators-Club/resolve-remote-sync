# Verifier med-10 (2026-09-24)

Judged against HEAD (63d4290) with `git show`. Read-only; nothing live touched.

## logic-resolve-1 - CONFIRMED (medium)
fix_clip always claims a fresh name through `_claim_destination_path` (O_EXCL loop, `name (2).ext` ...) and has no path that reuses an earlier `copied_to`. Both the relink-failed result (`ok: False`, `copied_to` set, fixer.py:1482-1491) and the partial-relink abort (`aborted`, `partial_relink`, fixer.py:1449-1464, message "Run FIX ALL again") land in `_failed_rows` (popup.py:1466-1467: `failures + aborted`), and RETRY FAILED re-runs the same row from the start. So every retry is a second full copy that lane A uploads. Medium is right: it needs a relink failure or a mid-relink cancel first, but the dialog tells the editor to press the button that duplicates.
Evidence: read fixer.py:773-799, 1175-1500; popup.py:1440-1480, 1222-1224.

## logic-resolve-2 - CONFIRMED (medium)
`open_session` starts a new journal file when more than `SESSION_GAP_SECONDS = 120` passed since the previous record (resolve_journal.py:63, 394); fix_clip copies and relinks per clip, so any copy over two minutes splits one FIX ALL into several journals, contrary to the constant's own comment. `undo_last_relink` (resolve_bridge.py:2572-2690) replays only `latest_session` and never retires it; a second press looks up the `new` paths, finds nothing, counts them `skipped` and prints "no longer in this project's media pool". Mitigation: an admin can undo a specific journal by id from the dashboard (resolve_undo.py, SYS-15b), but the tray button cannot reach earlier bursts.
Evidence: read resolve_journal.py:60-70, 384-470; resolve_bridge.py:2572-2690; resolve_undo.py docstring.

## logic-resolve-3 - CONFIRMED (medium)
`search_dirs` is Resolve's own LUT folder (`_default_resolve_lut_dir`, ProgramData\...\Support\LUT) and `stray_luts` has no factory exclusion; the module docstring itself says a factory LUT in the library shows twice. A same-name different-size file is still a stray, while `copy_into_library` counts an existing dest as `skipped`, so the offer cannot clear. Listing P:\Assets\Luts against this rig's factory folder shows ACES, Arri, Astrodesign, Blackmagic Design, DCI, HDR ST 2084, Invert Color.ilut/.olut, Canon Log *.ilut etc. in both, so the duplicate factory set is already live in the shared library.
Evidence: read luts.py:1-40, 266-383, 451-457, 603-615; `ls /p/Assets/Luts` and `ls "/c/ProgramData/Blackmagic Design/DaVinci Resolve/Support/LUT"`.

## logic-resolve-4 - CONFIRMED (medium)
`build_popup_rows` falls back server mapping -> `pick_project_prefix` (name match -> `active_project` -> ""), and `suggest_destination` with "" returns `B-roll/Editor Added/<editor>` at the tree root. fix_clip only checks containment inside local_root, not inside `Projects/`, and lane A walks `Projects/<rel>` only, so the copy never leaves the machine while the dialog reports Fixed. The only signal is config.py's "active_project is blank" log line. The CORE-H3 fix trimmed the dropdown but not this default.
Evidence: read fixer.py:296-317, 426-442, 1260-1290; popup.py:343-395; rclone_lane.py:2286; config.py:1961.

## logic-admin-1 - CONFIRMED (medium)
`db._halt_state` returns `"active": active and not expired` (db.py:8201), and `_check_fleet_halt_expired` requires `halt.get("active") and halt.get("expired")` (alerts.py:1409). `Ctx.halt` is `db.get_fleet_halt` (alerts.py:1111), which always goes through `_halt_state`. The two cannot both be true, so the registered `fleet_halt_expired` kind never produces a finding and still shows as a working check. Silent-alarm class, medium is right.
Evidence: read db.py:8184-8227, alerts.py:1107-1111, 1392-1418, 3526-3529.

## logic-admin-2 - CONFIRMED (medium), DUPLICATE of ui-dash-admin-2
Both templates render the future `halt.expires_at` through `ago` (fleet_halt_banner.html:13, fleet_halt.html:38), and `ui.ago` clamps negative deltas with `max(..., 0)` then returns `"0s ago"`. The every-page banner therefore says "it releases itself 0s ago" for the whole halt. Same defect as ui-dash-admin-2 in this hunt.
Evidence: read ui.py:93-117, 140 and both templates.

## logic-admin-3 - DOWNGRADE (low)
Mechanism holds: an expired halt keeps the stored `active: true`, `_halt_state` reports `expired` on every read, the banner's `elif halt.expired` branch shows to every signed-in user, and the admin panel's expired branch only offers [ STOP ALL SYNCING ]; only `set_fleet_halt(active=False)` (JSON route or a triage mail action) clears it. But the banner is true ("syncing has started again everywhere"), nothing is blocked and no data is at risk; it is a stale, undismissable notice. Low.
Evidence: read fleet_halt_banner.html, fleet_halt.html, db.py:8244-8315, triage_actions.py:209-229.

## logic-admin-4 - DOWNGRADE (low)
`_walk` skips dot-dirs and the preview compares the snapshot against the live project, so after a restore the same files are still reported missing - which is accurate, since the design is "copy into `.restored-<ts>`, then move what you want back yourself" (recovery.py:872-880). A second restore makes a second additive copy: the module states picking wrong "costs disk space and nothing else", and the page names the folder (`where`) and lists past restores under WHAT HAS BEEN PUT BACK. Real UX gap (no "already restored" note; dot-folder visibility over SMB depends on the share's hide-dot-files setting, not verified on this TrueNAS), but no data loss. Related but distinct: bug-dash-diag-3 (the .restored folder is replicated by Syncthing).
Evidence: read recovery.py:259-283, 355-490, 872-900; recovery.html result and history blocks.
