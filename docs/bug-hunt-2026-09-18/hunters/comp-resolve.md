# comp-resolve - the companion's Resolve surface: bridge, journal, prefs, fixer, library, proxy gen/scan/relink/history, LUTs, consolidate, watcher, Timeline Cards role

Files read (with approximate coverage):
- `companion/src/ccsync_companion/proxy_relink.py` (100% of the phase 3 additions, ~70% of the rest)
- `companion/src/ccsync_companion/resolve_bridge.py` (`replace_clip`, `link_proxy_media`, `_enrich_proxy_keys`, `_broll_archive_roots`, `_under_broll_archive`, `connect`/`_note_starting`, `_norm_path`; ~35% overall)
- `companion/src/ccsync_companion/watcher.py` (the whole audit-F4 exemption and the re-arm rework; ~60%)
- `companion/src/ccsync_companion/resolve_journal.py` (`allow_automatic` and its bars)
- `companion/src/ccsync_companion/proxy_gen.py` (the preview-tier hunk only)
- `companion/src/ccsync_companion/timeline_cards_role.py` (`_elide`, the watchdog `all()`/`_loop_error` hunk)
- `companion/src/ccsync_companion/app.py` `_relink_proxies_once`, `_note_proxy_attach`, `_classify_pool_once`, `_media_tree_loop`, the watchdog's `_media_tree_target`, the `TimelineWatcher(...)` construction
- `companion/src/ccsync_companion/ffmpeg_tools.py` (`count_frames`, `count_frames_cmd`, `PROBE_TIMEOUT_SECONDS`)
- `companion/src/ccsync_companion/broll_standins.py` (read as the callee: `is_standin`, `is_stale`, `is_under_archive`, the ledger's load/stamp)
- `companion/tests/test_proxy_relink_standins.py` (100%), `companion/tests/test_proxy_relink.py` (skim)
- `docs/BROLL_PROXY_TIERS_PLAN.md` sections 3 and 6, `_AUDIT.md` F1/F4, `KNOWN_BUGS.md` CR-281

Tests run:
- `cd companion; .venv\Scripts\python.exe -m pytest tests/test_proxy_relink_standins.py tests/test_proxy_relink.py -q` -> 52 passed
- ad-hoc snippet from the companion venv (scratchpad, no Resolve): `resolve_bridge.replace_clip(fake_item, <the same path the item reports>)` -> `{'ok': True, 'message': 'Already linked to ...'}` and `ReplaceClip` never called

## Findings

### comp-resolve-1 - the stand-in geometry refresh never runs: `replace_clip` short-circuits on its own path, and reports success
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/resolve_bridge.py:2280-2285` (the `Already linked` early return) and `companion/src/ccsync_companion/proxy_relink.py:704-722` (`apply_relinks`, the refresh branch)
- What: phase 3's whole point is that "only `ReplaceClip(<the same path>)` makes Resolve re-read a file that changed under a clip" (plan section 3, spike measurement). `apply_relinks` implements it as `replace_fn(media_pool_item, op["file_path"])`, defaulting to `resolve_bridge.replace_clip`. But `replace_clip` reads the clip's current `File Path` first and returns `{"ok": True, "message": "Already linked to ..."}` whenever it equals the requested path - which for a refresh is ALWAYS true, by construction. `ReplaceClip` is never called, no save point is taken, nothing is re-read, and the caller counts `refreshed += 1` and logs "re-read %s from its own file".
- Failure scenario: a wired rig opens a project whose archive clips were inserted from a stand-in on someone else's machine. Every pass plans a refresh, every refresh "succeeds", and the clips keep the stand-in's 1920x1080 / 3255-frame geometry for ever over a 6K ProRes original - exactly the state CR-281 says is fixed. Worse, because the geometry never changes, the same ops are planned on EVERY 120 s pass: `_relink_proxies_once` calls `resolve_journal.allow_automatic(project, "auto-proxy-relink")` before applying, so one grant is burnt every 900 s, `AUTOMATIC_MAX_PER_DAY = 8` is reached in about two hours, and from then on the journal logs a WARNING saying "this looks like a configuration problem" and HOLDS every genuine proxy relink for that project for the rest of the day.
- Evidence: the snippet above, run from `companion/.venv`, with a fake media pool item whose `ReplaceClip` raises `AssertionError` - the assertion never fires and the call returns ok. `proxy_relink.py:704` passes `op["file_path"]`, which `plan_relinks` set from `item["file_path"]`, i.e. the clip's own stored path; `_norm_path` is `canon.norm` on both sides, so the comparison at `resolve_bridge.py:2284` always matches.
- Ledger: new - "CR-281's phase 3 refresh (audit F1 / plan section 6) does not work". CR-281's own "still owed" list names the live check that would have caught it (a stand-in-born clip opened on a wired rig).
- Suggested fix: give `replace_clip` an explicit `force: bool = False` (or a `refresh_same_path=True`) that skips the `Already linked` short-circuit and, since the after-read can no longer prove the swap took, verifies with the clip's `Frames`/resolution instead of `File Path`; pass it from `apply_relinks`'s refresh branch. Add a test that drives `apply_relinks` with the REAL default `replace_fn` against a fake media pool item (see comp-resolve-4).

### comp-resolve-2 - the geometry check ffprobes every archive clip, whole-file, on every 120 s pass
- Severity: high
- Confidence: CONFIRMED (the cost); PLAUSIBLE (the watchdog restart it leads to)
- Where: `companion/src/ccsync_companion/proxy_relink.py:311-345` (`_geometry_disagrees`) and `:544-550` (the `refresh` expression), reached from `app.py:4431-4444`
- What: for every in-tree clip under the b-roll archive whose original is present and is not a ledgered stand-in, the pass runs `ffmpeg_tools.count_frames`, which is `ffprobe -count_packets -select_streams v:0` - a FULL demux of the file (the docstring says so: `nb_frames` is "absent or a lie", so it counts packets). The result is cached per pass only, deliberately, so the probe repeats on every pass for every archive clip, for ever, including the overwhelming case where the counts agree and there is nothing to do.
- Failure scenario: the base rig (or any wired editor) with the archive on P: opens a b-roll-heavy project. 50 archive clips of 2 GB each means ~100 GB read over SMB every 120 s, serialised on the media-tree thread; with `PROBE_TIMEOUT_SECONDS = 60` per clip, a 60-clip pool can block that thread for up to an hour. The media-tree loop stamps `_media_tree_heartbeat` only at the top of each iteration, and the lane watchdog restarts a thread silent for `LANE_WATCHDOG_WEDGED_SECONDS = 30 min` (`app.py:867,1135-1148`), so a slow pass is also a thread the watchdog keeps restarting mid-probe - and neither the library walk nor the proxy relink ever completes.
- Evidence: `ffmpeg_tools.py:904-961` (the argv and the 60 s timeout); `proxy_relink.py:323-336` probes before it can know whether the counts agree; `app.py:4443` builds a fresh `frame_counter` per call, so nothing is remembered between passes; `app.py:1737` `media_tree_refresh_interval` defaults to 120.
- Ledger: new (related to CR-281; the plan's own rule "asking ffprobe about every clip in a 1,300-clip pool every 120 s would cost more than the whole pass" is violated for archive clips, which on a wired rig IS the big pool).
- Suggested fix: ask the cheap question first - only probe a clip whose stand-in ledger says `is_stale` (which `broll_standins.is_stale` exists for, and nothing calls), or whose stored geometry disagrees with something free (the clip's resolution vs a `ffprobe -show_streams` header read, no `-count_packets`); and persist a per-(path, size, mtime) verdict across passes so an agreeing clip is never asked twice.

### comp-resolve-3 - a refresh is never remembered, so a clip that does not refresh is re-ReplaceClip'd for ever
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:701-722` (the refresh branch records nothing) vs `:408` `note_refusal`, which is what the proxy half uses
- What: the proxy-link half of this module has a refusal memory keyed on the proxy file's (mtime, size) precisely so Resolve is not asked the same impossible thing every pass. The refresh half has no equivalent: neither a success nor a failure is recorded anywhere, and the only thing that stops the op being planned again is the stored frame count changing. Nothing bounds the case where it does not change.
- Failure scenario: once comp-resolve-1 is fixed, any clip whose `Frames` still disagrees after a real `ReplaceClip` - a file ffprobe counts differently from Resolve (a stream with a non-video first packet stream, a file Resolve reads at a different rate, a `.mxf`/`.braw` proxy pairing), or a clip Resolve refuses to re-read - gets a real `ReplaceClip` plus a `SaveProject` save point and an undo-journal entry every 900 s, for ever, and burns the same 8-per-day automatic budget as comp-resolve-1. Today the same loop happens without the ReplaceClip.
- Evidence: read `apply_relinks`' refresh branch: on success `refreshed += 1` and `continue`; on failure `failures.append` + `REASON_NO_ANSWER`, with an explicit comment that this must NOT be remembered as a refusal. `plan_relinks` consults only the live geometry.
- Ledger: new.
- Suggested fix: record "refresh attempted at (path, size, mtime, stored_frames)" in the same style as `note_refusal`, and do not plan another refresh for that triple; log once when a clip refuses to refresh.

### comp-resolve-4 - every test of the refresh injects `replace_fn`, so the shipped default is untested
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/tests/test_proxy_relink_standins.py:171,188,208`
- What: all three refresh tests pass `replace_fn=lambda item, path: {"ok": True}` (or a recorder). The default - `resolve_bridge.replace_clip`, which is what app.py actually gets, because `_relink_proxies_once` passes no `replace_fn` - is exercised nowhere, and it is the thing that is broken (comp-resolve-1). The suite mocks away exactly the defect.
- Failure scenario: 52 green tests and a feature that has never refreshed a clip; CR-281 is written up as built.
- Evidence: `grep -n replace_fn companion/tests/test_proxy_relink_standins.py`; `grep -n apply_relinks companion/src/ccsync_companion/app.py` shows the call site passing only `link_fn`.
- Ledger: new (test-quality; supports comp-resolve-1).
- Suggested fix: one test that calls `apply_relinks` with no `replace_fn`, monkeypatching `resolve_bridge.replace_clip`'s dependencies rather than the function, or at minimum a direct test of `replace_clip(item, <item's own path>)` asserting that `ReplaceClip` IS called on the refresh path.

### comp-resolve-5 - a refresh-only pass reports "nothing to do" and `attached: 0`
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:775-780` (`message` is built only `if relinked or failures`) and `app.py:4941-4960` (`_note_proxy_attach` reads `relinked` only)
- What: `refreshed` is added to the return dict and read by nobody. A pass that refreshed 40 clips and linked none produces `message == ""`, so `app.py:4475` logs "proxy relink: nothing to do", and the status the tray/report shows records `attached: 0`.
- Failure scenario: an editor (or an operator diagnosing a wired rig) is told nothing happened while the pass rewrote 40 clips' media pool entries with save points - and, on the flip side, the operator has no signal at all that the phase 3 refresh is or is not running, which is what would have surfaced comp-resolve-1.
- Evidence: read both functions; `grep -rn '"refreshed"' companion/src` has exactly one producer and no consumer.
- Ledger: new.
- Suggested fix: include `refreshed` in `message` and in `_note_proxy_attach`'s stored dict (RES-3's own rule: the attach half must be able to say what it did).

### comp-resolve-6 - a refresh on a clip whose proxy is working carries no proxy, and ReplaceClip may drop the link
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/proxy_relink.py:524-545` (`new_proxy` is computed only when `not proxy_is_working(state)`)
- What: when the clip's proxy IS working and a refresh is planned, the op carries `new_proxy = None`, so `apply_relinks` runs the replace and stops. If `ReplaceClip` clears the clip's proxy attachment (it re-reads the source and is the API's re-import path), the clip is left with no proxy until the next pass, which is 120 s later at best and behind `allow_automatic`'s 900 s bar at worst.
- Failure scenario: a wired rig refreshes a b-roll clip that was playing its editing proxy; the editor's timeline drops to the original (or to offline media on a remote-ish rig) for at least a pass.
- Evidence: code reading only - I could not test against Resolve (forbidden by the brief), and the spike notes in the plan do not say what happens to the proxy link across a same-path ReplaceClip.
- Ledger: new.
- Suggested fix: always compute `find_proxy_on_disk` for a refresh op (subject to the same `.mp4` rule) and re-attach after the replace; or read `proxy_path` back after the refresh and re-link if it went blank.

### comp-resolve-7 - the watcher's archive exemption stats the disk for every missing archive clip on a 3 s poll
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/watcher.py:503-536` (`_archive_exempt`), reached from the MISSING branch at `:413`; constructed with no `archive_exempt_fn` at `app.py:2122-2142`, `poll_interval` default 3
- What: the exemption is cached per poll, not across polls. For every distinct MISSING archive path it reads the stand-in ledger (a stat of the ledger file plus a stat of the media file inside `_entry_is_stale`) and then `find_proxy_on_disk`, which probes up to four candidate paths. A remote rig with a proxy-only b-roll timeline is in exactly the designed steady state where every one of those clips is MISSING every poll.
- Failure scenario: a 200-clip b-roll timeline costs roughly 1,000 filesystem probes every 3 seconds on the watcher thread, which is the thread the popup/fixer latency depends on; on a rig whose sync drive is slow or an SMB twin, that is a visible watcher stall for a purely cosmetic count.
- Evidence: code reading; `broll_standins.StandinLedger.get` stats the ledger on every call and `_entry_is_stale` stats the media file.
- Ledger: new (audit F4).
- Suggested fix: cache the verdict per path across polls with a short TTL (the answer only changes when a file lands or is deleted), the way `_warned_missing` already latches per path.

## Coverage note
I did not get to `fixer.py`, `library.py`, `consolidate.py`, `project_setup.py`, `luts.py`, `bpg.py`, `proxy_history.py`, `proxy_scan.py`, `resolve_prefs.py`, `resolve_undo.py` or `script_server.py` beyond a diff check (none of them changed since 34a3c8f or 18e69f3), nor `timeline_cards_bridge.py`. The suite does not cover: `apply_relinks` with its real default `replace_fn` (comp-resolve-4), the cost of `_geometry_disagrees` on a real pool (nothing measures a pass), the watcher exemption's per-poll cost, and what `ReplaceClip` does to an attached proxy. Nothing here was checked against a live Resolve, by the brief's rule.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_standins.py`: `is_stale()` is documented as "the relink pass's signal that the clip was BORN from a stand-in" but no caller exists - `proxy_relink` uses the ffprobe comparison instead, which is what makes comp-resolve-2 expensive (comp-broll-tiers / proxy-tiers lens).
- `companion/src/ccsync_companion/app.py:4431`: `_relink_proxies_once` consumes a `resolve_journal.allow_automatic` grant for a pass that may consist entirely of refreshes, so phase 3 competes with the canonical-path rewrites for the same 8-per-day budget (comp-app).
