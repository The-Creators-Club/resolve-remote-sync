# DaVinci Resolve integration: bridge, journal, watcher, fixer, proxies, BPG, Timeline Cards role

## Summary
The mutation primitives here are the best-defended code in the repo, and the
08-28 sweep hardened them further (the rate limiter is on disk now, folder
ignores persist with a [ FORGET ] button, the admin-side undo exists). What the
sweep did not have was the usability lens, and under it this area has one
shape repeated everywhere: **the companion knows the answer and never says it.**
The tray has no Resolve section at all beyond one binary line; the proxy ATTACH
half of the pipeline has literally zero user-visible surface; the Timeline Cards
role has no channel to the editor by construction; BPG's "press Start in its
window" instruction is a log line. The biggest single risk is RES-1: the
recipe `docs/GOTCHAS.md` §15 hands to every OTHER Resolve client on the machine
is the guard that was PROVEN broken on 2026-08-21 and superseded the same
evening, so the fleet's own documentation propagates the CR-68 bug. The best
cheap wins are RES-1 (change six lines of a doc) and RES-3 (stop discarding
`apply_relinks`'s return value, which already contains the sentence an editor
needs).

## Findings

### RES-1: GOTCHAS §15 tells every other Resolve client to use the guard that was proven broken
- **Lens:** resilience  **Who:** developer / owner
- **Where:** `docs/GOTCHAS.md:980-987`; contradicted by `companion/src/ccsync_companion/script_server.py:51-62,323-337` and `KNOWN_BUGS.md:2855-2857`
- **Today:** §15's "For any other Resolve client on the same machine (the MCP
  server, the MulticamPipeline tools): copy `script_server.py` next to your code
  ... and gate every `scriptapp()` call" ships this snippet:
  ```
  from script_server import is_starting
  if is_starting():
      return None
  app = dvr.scriptapp("Resolve")
  ```
  That is exactly the 0.9.45 shape. `script_server.py:51-62` records why it does
  not work: with **no listener** the answer is ABSENT, `is_starting()` is False,
  the client calls through, and `scriptapp("Resolve")` **does not fail fast**
  (4.0 s per call, 8 s behind a second thread) - so the client is inside a
  connect loop at the instant the server appears and kills it. KNOWN_BUGS CR-68
  is explicit: "the two ports use it (`not ready_to_connect()`, **never**
  `is_starting()`)". `ready_to_connect` appears nowhere in `docs/`. A
  `davinci-resolve` MCP server whose own tool descriptions say they "automatically
  launch Resolve if it is not running" is live on this rig.
- **Proposed:** replace the snippet with
  `from script_server import ready_to_connect` / `if not ready_to_connect(): return None`,
  and add one sentence: "`is_starting()` alone is not enough - `scriptapp()` with
  no server present blocks for seconds retrying, so it becomes the killing client
  the moment the server appears (this is how 0.9.45 still killed two launches)."
  Same edit in the global `~/.claude/CLAUDE.md` copy if it drifts.
- **Effort:** S  **Value:** critical  **Confidence:** high
- **Related:** CR-68, `script_server.py` module docstring, 08-28 RES cross-cutting note

### RES-2: [ ALWAYS LEAVE THIS FOLDER ALONE ] destroys the popup while FIX ALL is still copying
- **Lens:** both  **Who:** editor
- **Where:** `popup.py:1252-1272` (`_on_ignore_folder`, ends `self.root.destroy()`),
  `popup.py:991-994` (`_run_fix` disables only `_fix_btn` and `_ignore_btn`),
  `popup.py:770-773` (`_folder_btn` created, never disabled), `popup.py:925-953`
- **Today:** during a multi-GB FIX ALL, [ SKIP FOR NOW ], [ FIX ALL ] and the X are
  all handled (the X is remapped to CANCEL ALL and deliberately does **not**
  destroy the root, `popup.py:936-938`, "CORE-M1"). The folder button is not:
  it does not check `self._fixing`, it is never disabled, and it calls
  `root.destroy()` unconditionally. `show_popup` then returns, `app`'s
  `_popup_active_lock` is released, and the `ccsync-fixall` daemon thread keeps
  copying and calling `ReplaceClip` with no window - while a second popup or a
  consolidate pass is now free to start over the same clips. The worker's
  `_deliver_results` will also `root.after` on a destroyed interpreter.
- **Proposed:** disable `_folder_btn` alongside `_fix_btn`/`_ignore_btn` in
  `_run_fix` (one line), re-enable it at `popup.py:1174-1175`, and add the same
  `if self._fixing: return` guard `_on_close_request` already has. Belt and
  braces: make `_on_ignore_folder` route through `_on_close_request` rather than
  calling `destroy()` itself, so there is one place that knows a copy is live.
- **Effort:** S  **Value:** critical  **Confidence:** high
- **Related:** CORE-M1, CR-93 (a destroy from under a live worker is also the Tk shape)

### RES-3: the proxy ATTACH half has no user-visible surface at all, and its diagnosis is discarded
- **Lens:** both  **Who:** editor / admin
- **Where:** `app.py:3919` (return value of `apply_relinks` dropped),
  `proxy_relink.py:409-419`, `proxy_relink.py:196-197,268-270`, `proxy_relink.py:318-322`
- **Today:** "why is my proxy not attached?" is unanswerable by any human. The
  generate half has a tray line, a window, a toast and `proxy_history.txt`; the
  attach half has none. `apply_relinks` builds
  `"repointed 3 proxy link(s), 12 refused by Resolve"` and `app.py:3919` throws it
  away. The one sentence that IS the answer -
  `"%d proxy link(s) refused by Resolve (first: %s) -- not retried until the proxy
  file changes. A timecode that does not match the original is the usual cause
  (KNOWN_BUGS R10)"` (`proxy_relink.py:409-414`) - is a WARNING in a 5 MB-rotating
  log. The per-clip reason is **DEBUG** (`:403-407`). `_REFUSALS` is an in-process
  dict that is permanent for the session by design (`:268-270`: "a restart is the
  intended (and only) way to clear this in the field") and nothing tells the editor
  a clip is on it. `:318-322` - proxy already pointed at the right file and still
  not working, i.e. an unreadable proxy - logs nothing at all.
- **Proposed:** (a) keep the message: `msg = proxy_relink.apply_relinks(...)`, log at
  INFO and `_notify_tray` once per pass when `refused` is non-zero:
  "Repointed 3 proxies to the copies in your sync folder. 12 could not be attached -
  usually the proxy's timecode does not match the original. Settings shows which."
  (b) add a Settings > RESOLVE line: "12 clips have a proxy on disk that Resolve
  will not attach" with [ TRY THESE AGAIN ] calling `reset_refusals()` - the escape
  hatch that today is "restart the tray, if you happen to know". (c) promote
  `:403-407` to INFO.
- **Effort:** S/M  **Value:** critical  **Confidence:** high
- **Related:** R10 (FIXED), KNOWN_BUGS carryover item 23 (live-attach proof, SHIP-BLOCKER, still unrun), 08-28 RES-15

### RES-4: an admin's [ UNDO THIS CHANGE ] dies permanently when Resolve is at the Project Manager
- **Lens:** resilience  **Who:** admin
- **Where:** `resolve_undo.py:167-177`, against `resolve_bridge.py:1104,1410,1794`
  (`"no project open in Resolve"`) and `resolve_bridge.py:1525`
  (`_SCRIPTING_ERROR_MESSAGE = "Resolve didn't answer. Make sure a project is open, then try again."`)
- **Today:** the module's whole contract is "the refusals that clear themselves are
  answered `retrying`". It decides that by substring:
  `not message or "open that project" in lowered or "is open" in lowered or "resolve" in lowered and "not" in lowered`.
  `"no project open in Resolve"` matches none of them (no "not", and "project open"
  is not "is open"), so it is recorded **`failed`** and never retried - even though
  the editor opening their project is exactly what clears it. Resolve open at the
  Project Manager, or between projects, is a routine state. `_SCRIPTING_ERROR_MESSAGE`
  ("didn't" contains no "not") is likewise permanently failed although it is
  explicitly transient. The admin sees "could not be put back" and the wrong paths
  stay.
- **Proposed:** stop classifying on prose. Have `undo_last_relink` return a
  `retryable: True/False` key beside `ok` - it already knows which branch it took -
  and have `apply_undo` read that, keeping the substring test only as a fallback for
  an older bridge. Immediately: add `"no project open"`, `"no timeline open"` and
  `_SCRIPTING_ERROR_MESSAGE` to the retry set.
- **Effort:** S  **Value:** high  **Confidence:** high
- **Related:** SYS-15b, `docs/RESOLVE_EDIT_SAFETY.md` "Undoing", 08-28 RES-1's retry contract

### RES-5: there is no RESOLVE section in Settings, and every count the companion computes is thrown away
- **Lens:** usability  **Who:** editor / admin
- **Where:** `settings_window.py:326-601` (sections: THIS COMPUTER, SYNC LANES, YOUTUBE, ADVANCED, HELP),
  `tray.py:1945-1969` + `tray.py:3420-3424` (the one line), `app.py:4249-4259`
  (`resolve_health()` returns `out_of_tree`, `bad_prefix`, `missing`, ...),
  `app.py:6915-6933` (diagnostics only)
- **Today:** the whole of Resolve in the editor's UI is one disabled tray line -
  `"Resolve: connected"` / `"Resolve: not connected right now (<reason>)"`. An
  editor with 40 dead links, 12 unattachable proxies and no popup on screen has
  **no number anywhere in the UI**. `resolve_health()` already computes exactly
  those numbers for the dashboard and `_resolve_health_text` renders them for a
  diagnostics bundle nobody opens unprompted.
- **Proposed:** a `Section("RESOLVE", ...)` in the settings window, above ADVANCED:
  `Line("Project: <name>")`, `Line("Connected")` / warning line with the
  disconnection reason, `Line("40 clips are stored outside your synced folder")` +
  `Button("[ SCAN WHOLE PROJECT ]")`, `Line("12 proxies could not be attached")`,
  the library-walk source (RES-12), and the existing ignore lines moved up from
  ADVANCED. Every value already exists; this is assembly, not new plumbing.
- **Effort:** M  **Value:** high  **Confidence:** high
- **Related:** 08-28 RES-12(b) (the report half is still not built)

### RES-6: the Timeline Cards role reports green while its loop is dead or 401-ing
- **Lens:** resilience  **Who:** admin
- **Where:** `timeline_cards_role.py:458-467` (`_loop`), `:445-452`, `:587-593`
  (`report_block`), `:494-534` (`call`), `dashboard/templates/partials/fleet_grid.html:272`
- **Today:** two daemon threads, no watchdog: `thread.is_alive()` is consulted
  nowhere in the module. On exception `_loop` logs `"cards: the %s loop stopped"`;
  on clean return it logs `"cards: the %s loop returned -- the page will not update
  until the companion restarts"`. Neither clears `self._threads` or `self._state`,
  so `report_block()["connected"]` stays True and the fleet grid keeps rendering
  `[ CARDS: E1 v5 ]` in green. A wrong token raises `CardsTunnelError("the dashboard
  answered HTTP 401 ...")` **inside the imported AgentClient's loops**, which treat
  every exception as "the network is down" and back off - so a machine that has been
  401-ing for hours is indistinguishable from a healthy one. `last_state_at`
  (`_note_traffic`, `:536-547`) is the only thing that stops advancing and it is not
  in `report_block()`.
- **Proposed:** put `last_state_at` in `report_block` and have the grid chip go amber
  with "last talked N min ago" past a threshold; restart a dead loop (bounded, e.g.
  3 times an hour like `supervisor.py`) and set `state="stopped"` with the exception's
  text when it will not come back; count consecutive tunnel errors in `call()` and
  surface the last one in `status()["detail"]`.
- **Effort:** M  **Value:** high  **Confidence:** high
- **Related:** `docs/TIMELINE-CARDS-INTO-CCSYNC.md` §7c; the release/reload handshake has never run live

### RES-7: the cards role's refusal is decided once, at start, and its advice does not work
- **Lens:** both  **Who:** editor / admin
- **Where:** `timeline_cards_role.py:370-411` ("Called before the thread starts and
  never after"), `:377-378`, `:381-382`, `:394-397`, `:87` (`PROBE_CACHE_SECONDS`),
  `app.py:7523-7527`
- **Today:** three consequences. (1) A companion that started before sign-in refuses
  with `"this companion has no dashboard to long-poll (sign in from the tray)"` -
  and signing in from the tray does **not** start the role; only a restart does, so
  the sentence tells the editor to do the one thing that will not help. (2) A fleet
  halt active at boot latches the role off for the whole process, long after the halt
  expires (halts expire at 24 h by design). (3) `PROBE_CACHE_SECONDS = 60` and the
  probe cache are dead weight, since the probe runs at most once per process. The
  standalone-agent refusal also renders "cannot tell" as if it were a sighting:
  `"Found: this machine's processes could not be listed"` (`:232`, `:394-397`).
- **Proposed:** re-evaluate `refusal()` on a timer (it is already cheap and cached),
  start the role when it clears, and stop it when `halted` returns. Change the
  no-dashboard sentence to "sign in from the tray, then restart CCSync" until it does.
  Give the "cannot tell" case its own sentence: "another Timeline Cards process may
  be running and this machine's process list could not be read, so the role is not
  starting."
- **Effort:** M  **Value:** high  **Confidence:** high

### RES-8: Quit during FIX ALL kills a multi-GB copy with no confirmation
- **Lens:** both  **Who:** editor
- **Where:** `tray.py:3275-3277` (`on_quit`: `icon.stop()`, `app.shutdown()`),
  `app.py:5040-5041` (the app already answers `"popup"` as a stand-down blocker,
  used only for self-upgrades), `popup.py:1029` (`ccsync-fixall`, daemon, never joined),
  `fixer.py:827-866` + `app.py:8372-8375`
- **Today:** the tray's Quit item ("Quit CCSync (stops syncing until you next sign
  in)") tears the process down mid-`write()`. The partial `.ccsync-tmp` survives and
  is **reported, never deleted**, an hour later, as
  `"Found {n} half-copied file(s) from an interrupted copy. Nothing was deleted.
  Tray → Copy diagnostics for your admin."` - no filename, no action the editor can
  take. If the kill lands between `os.replace` and `ReplaceClip` the copy exists and
  Resolve is not repointed; nothing records that and the clip returns in the next popup.
- **Proposed:** `on_quit` already has the predicate. Confirm:
  "CCSync is copying 12 of 69 files into your synced folder. Quitting now abandons
  the file it is on. [ QUIT ANYWAY ] [ KEEP COPYING ]". And name the leftovers in
  the next-start toast with a [ DELETE THEM ] button rather than sending the editor
  to a diagnostics bundle.
- **Effort:** S  **Value:** high  **Confidence:** high

### RES-9: two editor-facing toasts hardcode "the P: drive" despite `canonical_prefix_label()`
- **Lens:** usability  **Who:** editor / owner
- **Where:** `app.py:2842` and `app.py:3880` (`"Whoever imported it should re-import
  it through the P: drive"`), vs `app.py:4172-4180` (`canonical_prefix_label`, whose
  docstring is "a second customer on Q: must not read a sentence about P:")
- **Today:** the FOREIGN-clip toasts are the only Resolve-area strings that name a
  drive letter as a literal. On a Mac editor the sentence is also meaningless: there
  is no drive letter there at all.
- **Proposed:** `f"...re-import it through {self.canonical_prefix_label()}"`, which
  falls back to "your media drive" when the prefix is unknown - the fallback that
  helper exists for. Grep-guard it in the companion suite's copy scan.
- **Effort:** S  **Value:** high  **Confidence:** high
- **Related:** COMMERCIAL_READINESS item 11, UX-15

### RES-10: a whole-project proxy scan that raises reports "fully covered"
- **Lens:** resilience  **Who:** editor / admin
- **Where:** `proxy_scan.py:467`, `:557` (`log.exception`, then an empty gap)
- **Today:** a project that cannot be walked - an odd path, a disconnected drive, a
  permission error - returns an empty gap, which is byte-identical to "every clip has
  a proxy". The tray says nothing, the dashboard's coverage says nothing, and the
  editor's footage silently never becomes visible to the rest of the team. This is
  the failure direction the whole feature exists to prevent.
- **Proposed:** return the gap with an `error` field and count the project as
  UNKNOWN, not covered; render "CCSync could not read <project> to check its proxies"
  in the tray line and as a `notices` row (the self-diagnosis registry exists for
  exactly this shape) rather than as zero.
- **Effort:** S  **Value:** high  **Confidence:** high
- **Related:** `docs/SELF_DIAGNOSIS.md` ("an unverified check is NOT CHECKED, never OK")

### RES-11: `capped`, `low_space` and `truncated` never reach the editor's tray
- **Lens:** both  **Who:** editor
- **Where:** `proxy_gen.py:1037-1069` (`gap()`), vs `proxy_gen.py:1117` (`coverage()`
  carries `low_space`), `proxy_gen.py:1515-1549` (`_failures` cap, default 3),
  `proxy_scan.py:461-463` (`MAX_QUEUE_PER_PROJECT = 500`, sets `gap["truncated"]`)
- **Today:** the dashboard can see a low-space machine; the editor sitting at it
  cannot. A clip that failed three times is capped for the life of the process with
  no key in `gap()` naming it. The low-space toast has a 24 h cooldown and no tray
  line behind it, so a full disk is one balloon a day and otherwise looks idle.
- **Proposed:** carry `capped`, `low_space` and `truncated` through `gap()`; tray
  line "Proxies: 3 clips gave up after repeated failures - Settings > Proxy history"
  and "Proxies paused: only 4.1 GB free on <drive>". Both strings already exist
  (`proxy_gen.py:1887-1889`, `:1542-1549`), only in the log.
- **Effort:** S  **Value:** high  **Confidence:** high

### RES-12: the library-walk fallback is invisible, and the symptom is "Resolve got slow"
- **Lens:** both  **Who:** editor / admin
- **Where:** `resolve_bridge.py:960-978` (`_note_library_fallback`), `:918-943`
  (`library_status`: "Nothing in the running companion calls this"), `app.py:6986-6988`
  (diagnostics has `resolve project` / `resolve bridge` / `resolve media`, not this)
- **Today:** the message is right - `"library walk unavailable (%s) -- using the API
  walk; clicks in other Resolve clients will lag during walks"` - and it is a WARNING
  once per process, then INFO, then DEBUG. GOTCHAS §16 measures the cost: 11-14 s per
  walk holding fusionscript, i.e. every click in Resolve stutters. The editor's report
  will be "Resolve is sluggish since the update"; nothing anywhere connects that to a
  postgres library that stopped answering.
- **Proposed:** add `section("resolve library", ...)` to the diagnostics bundle
  rendering `library_status()` (four lines, no new plumbing), and one Settings >
  RESOLVE warning line while `source == "api"`: "CCSync is reading your project the
  slow way (<reason>). Resolve may feel sluggish while it does."
- **Effort:** S  **Value:** med  **Confidence:** high

### RES-13: FIX ALL succeeds silently - no summary, and no pointer to the undo
- **Lens:** usability  **Who:** editor
- **Where:** `popup.py:1217-1227` (clears the status label, `on_done`, `destroy()`),
  `popup.py:2066` (`show_popup` never passes `on_done`), `settings_window.py:545-546`
- **Today:** 158 clips are copied and their paths rewritten in the editor's project
  database, and the window simply closes. There is no toast, no count, and no mention
  anywhere in the flow that the change can be undone. The undo is two levels deep -
  Tray > Settings... > scroll to ADVANCED > [ UNDO THE LAST CLIP-PATH CHANGE CCSYNC
  MADE… ] - and it is not in the tray menu at all (`tray.py:3041` defines
  `action_undo_last_relink`; nothing places it). Its label also names no project and
  no count, so pressing it is blind, although `resolve_journal.describe_latest()`
  already renders exactly that string.
- **Proposed:** on a successful FIX ALL, toast
  `"Copied 158 clip(s) in and repointed Resolve at them. Settings > ADVANCED can undo
  this."`; and make the button label carry the summary:
  `[ UNDO: 158 CLIP PATHS IN "FF4 ROUGH", 14:22… ]`, greyed with "Nothing to undo" when
  `describe_latest()` is empty.
- **Effort:** S  **Value:** high  **Confidence:** high

### RES-14: pressing CANCEL can leave an unresponsive, unclosable window for minutes
- **Lens:** both  **Who:** editor
- **Where:** `fixer.py:633-646` (`should_abort` polled once per 8 MB chunk),
  `fixer.py:504-513` (the cloud-hydration incident: 222 MB per 10 s),
  `fixer.py:1329-1343` (the `ReplaceClip` loop consults `should_abort` not at all),
  `popup.py:1061-1076`, `popup.py:944-946`
- **Today:** `fsrc.read(chunk)` on a Google Drive placeholder blocks for the whole
  hydration. During that block CANCEL ALL has already disabled STOP/SKIP/CANCEL and
  set `"Cancelling. The file being copied now is abandoned..."`, and the X re-enters
  `_on_cancel_all` and returns - so the dialog cannot be closed and does not move.
  Same for a wedged `ReplaceClip`. There is no watchdog on `ccsync-fixall`
  (`LaneWatchdog` covers sequencer, watcher and media_tree only, `app.py:930-983`).
- **Proposed:** cap the chunk read with a smaller chunk on a path known to be
  online-only (the preflight at `popup.py:344-348` already identifies them), and after
  ~20 s of no progress post-cancel change the label to
  `"Still waiting for your cloud drive to release \"<name>\". CCSync will stop as soon
  as it does."` with an elapsed counter - a stuck window that says why is not the same
  bug as one that says nothing. Consult `should_abort` between items in the ReplaceClip
  loop.
- **Effort:** M  **Value:** high  **Confidence:** high

### RES-15: a FIX ALL rehearsal reads as a catastrophe, and rehearsal is config-file-only
- **Lens:** usability  **Who:** admin / owner
- **Where:** `fixer.py:1213-1222` (dry run returns `ok: False`), `popup.py:190-201`
  + `popup.py:1201` (every `ok: False` row becomes `"✗ {name}: {message}"` under
  `", {n} failed"`), `config.py:477-478`, `docs/RESOLVE_EDIT_SAFETY.md:112-125`
- **Today:** `fixer_dry_run = true` is the documented way to rehearse the companion's
  largest destructive action on a machine whose `local_root` is in doubt. Because a
  dry run is `ok: False`, the popup summarises it as `"0 of 69 copied in, 69 failed"`
  with 12 red rows and `"… and 57 more (see tray → Open log)"`. Nothing in the popup
  knows the word `dry_run`. The switch itself is reachable only by hand-editing
  `~/.ccsync/config.toml`, is cached once per process, and an admin who forgets to
  remove it leaves FIX ALL permanently inert on that machine.
- **Proposed:** teach `summarize_fix_results` about `dry_run` - headline
  `"REHEARSAL: nothing was copied. 69 file(s) would be copied into <root>."`, rows
  neutral not red - and surface the mode as a persistent warning line in the popup
  header and in Settings > ADVANCED: `"FIX ALL is in rehearsal mode on this computer
  and will copy nothing."` with [ TURN REHEARSAL OFF ].
- **Effort:** S  **Value:** med  **Confidence:** high

### RES-16: BPG's one actionable instruction is addressed to the editor and delivered to a log
- **Lens:** usability  **Who:** editor
- **Where:** `bpg.py:710-713` (`"bpg: could not press Start (%s) -- the proxy
  generator is open but idle, press Start in its window"`), `bpg.py:781-785`, `:736-776`
- **Today:** the companion opens a DaVinci Resolve window on the editor's machine
  while they are away (`user_away` gates the launch), never closes it ("never stopped
  by us"), and there is not one user-facing string in `bpg.py`. When the UI-automation
  press fails, the only thing standing between the fleet and hours of no BRAW proxies
  is a sentence in `companion.log` telling a human to click a button. The editor
  returning to an unexplained Resolve window has nothing to read.
- **Proposed:** a toast on launch - `"CCSync opened the Blackmagic Proxy Generator to
  make proxies for 14 clips other editors cannot see yet. You can leave it running."`
  - and, on a failed Start, a toast plus a Settings > RESOLVE line with the exact
  instruction and [ SHOW ME THE WINDOW ]. Also: the "watch list is full" path
  (`bpg.py:526-542`) deliberately sets no cooldown, so it warns on **every tick** on
  the one machine whose log most needs reading; give it the same cooldown as the
  other refusals.
- **Effort:** M  **Value:** med  **Confidence:** high
- **Related:** 08-28 RES-4, RES-5 (both still open, see below)

### RES-17: `stills.check()`'s "add it by hand" instruction is discarded on every pass
- **Lens:** both  **Who:** editor
- **Where:** `app.py:7762-7765` (calls `self._stills.check()`, catches at DEBUG,
  reads nothing from the return), `stills.py:162-169`, `:171-176`
- **Today:** `check()` returns `{"status", "changed", "message", "path"}` and the
  periodic caller uses none of it. So `"Resolve's preference files are not in the
  expected shape -- add {root} as a media storage location by hand, and set the
  gallery to it"` - an instruction that cannot be actioned by any code - is logged
  once per process and never seen. `_warned` is keyed by status only and cleared only
  on a successful write, so a check blocked for six weeks looks identical to one
  blocked for fifteen minutes.
- **Proposed:** `_notify_tray` on a status change, and a Settings > RESOLVE line
  while the shared stills folder is not wired up. The "Resolve is running, it will be
  set next time it is closed" case needs no toast, only the line.
- **Effort:** S  **Value:** med  **Confidence:** high

### RES-18: the once-ever NEW PROJECT prompt is consumed by a Tk failure nobody sees
- **Lens:** resilience  **Who:** editor
- **Where:** `project_setup.py:200-203` (`_record_asked` runs BEFORE `_confirm`),
  `popup.py:1986-1994` (`confirm_dialog` returns False on any Tk import failure,
  `"confirm dialog unavailable (%s) -- defaulting to cancel"`), `project_setup.py:163-167,240-241`
- **Today:** on a machine where Tk cannot start - the CR-93 territory, a locked-down
  profile, a remote session - the prompt is recorded as asked without a pixel being
  drawn, permanently and across restarts. The project then never gets a server-side
  home and nothing syncs for it. Separately, `setup_url` uses `cfg["dashboard_url"]`
  with no check, so an unset dashboard hands `webbrowser.open` a bare
  `"/project-setup?resolve_project=X"`, and `trigger_setup` swallows the result: the
  tray item does nothing, visibly or in the log.
- **Proposed:** record the prompt as asked only when the dialog actually rendered
  (`confirm_dialog` should distinguish "declined" from "could not be shown"), fall back
  to a toast when it could not, and log a WARNING when `dashboard_url` is empty rather
  than opening a relative path.
- **Effort:** S  **Value:** med  **Confidence:** high

### RES-19: MISSING clips have no editor surface, and a refused non-canonical relink is never retried
- **Lens:** both  **Who:** editor
- **Where:** `watcher.py:330-334` (MISSING: one DEBUG line), `watcher.py:153`
  (`_offered_non_canonical`, never cleared or re-armed), `app.py:2779-2782`
- **Today:** four of the five classifications have a surface; MISSING has none except
  the RES-10 moved-file path. A clip whose file genuinely is not there - the commonest
  thing an editor actually notices, "Media Offline" - produces a DEBUG line. And a
  NON_CANONICAL relink that failed for a transient reason (Resolve busy, the file
  briefly locked) is logged and then never offered again for the life of the process,
  because `_offered_non_canonical` is add-only.
- **Proposed:** roll MISSING into the RESOLVE section's counts ("6 clips point at
  files that are not on this computer") rather than a toast per clip, and re-arm
  `_offered_non_canonical` when a relink FAILS (only a success should latch it).
- **Effort:** S  **Value:** med  **Confidence:** high

### RES-20: `check_contract` degrades a named refusal into "the role could not start (see the log)"
- **Lens:** resilience  **Who:** admin
- **Where:** `timeline_cards_role.py:164` (`int(version)`), `:169-170` vs `:437`,
  `:409-411`
- **Today:** a checkout whose `BRIDGE_CONTRACT_VERSION` is not an integer ("2.1", "v2")
  makes `int()` raise out of `check_contract` into `start()`'s generic handler, so the
  precise "this checkout speaks contract X and this companion speaks Y" sentence is
  replaced by `"the role could not start (see the log)"`. And `check_contract` accepts
  `SyncEngine or ResolveEngine` (`:169-170`) while `_start` re-fetches `SyncEngine`
  alone (`:437`), so a `ResolveEngine`-only checkout passes the contract check and then
  dies with an `AttributeError` in the same generic handler. Both matter now: the
  bridge contract has never been implemented on the other side, so this is the path
  every first attempt will take.
- **Proposed:** wrap the `int()` in try/except and refuse with the version as written;
  make `_start` reuse the class `check_contract` resolved instead of re-fetching.
- **Effort:** S  **Value:** med  **Confidence:** high

### RES-21: `RESOLVE_EDIT_SAFETY.md` still describes only the 15-minute bar, not the daily cap
- **Lens:** usability  **Who:** admin
- **Where:** `docs/RESOLVE_EDIT_SAFETY.md:41-45` vs `resolve_journal.py:73-80,285-295`
- **Today:** the doc says "the two unprompted passes may each run at most once per
  project per 15 minutes. Held clips are logged, not dropped." Since 08-28 there is
  also `AUTOMATIC_MAX_PER_DAY = 8`, after which the pass is held for the rest of the
  DAY with a WARNING saying "this looks like a configuration problem, tray -> Copy
  diagnostics". An admin whose machine has gone quiet will not find that in the doc,
  and "Scan whole project runs the pass immediately" is no longer true once the daily
  cap is reached.
- **Proposed:** one paragraph in Housekeeping naming the cap, the state file
  (`~/.ccsync/state/resolve_auto.json`), the WARNING's wording, and how it resets (UTC
  midnight). Surface the held count in the diagnostics bundle so the WARNING is not
  the only trace.
- **Effort:** S  **Value:** med  **Confidence:** high

### RES-22: the tray says "Resolve: connected" while a Resolve call has been wedged for 20 minutes
- **Lens:** both  **Who:** editor
- **Where:** `resolve_bridge.py:152-166` (`bridge_activity`), `tray_native.py:400-414`
  (its only consumer, inside a slow-click WARNING), `tray.py:1961-1969`
- **Today:** a refinement of 08-28 RES-3, which is still not built. The tray line is
  binary and derives from `session_state()`, a cached fact from the LAST completed
  enumeration - so a wedged `ImportMedia` against a vanished P: leaves the line reading
  "Resolve: connected" indefinitely while every Resolve feature does nothing.
  `bridge_activity()` was written lock-free "for a status reader" and still has no
  status reader.
- **Proposed:** in `resolve_bridge_line`, when `bridge_activity()["seconds"]` exceeds
  `BRIDGE_WEDGE_SECONDS`, render
  `"Resolve: busy (ImportMedia, 4 min) - CCSync is waiting"` and, past a few minutes,
  `"Resolve is not answering. Quit and reopen Resolve."` Add `resolve_bridge` to the
  report payload so the fleet page can flag it.
- **Effort:** S  **Value:** med  **Confidence:** high

## Still open from 08-28
- RES-1 (file move refused forever): **built** - `resolve_undo.py:16-22` names the retry contract as inherited from it.
- RES-2 (rate limiter in RAM): **built** - persisted at `resolve_journal.py:82-88,167-245`, plus a daily cap.
- RES-3 (nothing reads `bridge_activity()`): not built - see RES-22 above.
- RES-4 (BPG launched without the CR-68 guard): not built - `bpg.py` imports no `script_server`.
- RES-5 (BPG idling makes the companion nag "scripting is dead"): not built - `resolve_prefs.resolve_is_running()` still has no `-pg` awareness.
- RES-6 (undo over-counts on duplicate media-pool entries): not built - `resolve_bridge.py:2429-2435` still `setdefault`s one item per path and never drops the `new` key.
- RES-7 (no free-space preflight on FIX ALL / consolidate): not built - no `disk_usage` in `fixer.py`.
- RES-8 (`resolve_edits` swept only for projects still being edited): not built - `_sweep(slug, ...)` is still called only from `open_session`, still age-only.
- RES-9 (a renamed project orphans its own undo): not built - the journal header still keys on the name.
- RES-10 (`_relink_moved` only fixes the open project): **partly built** - the watcher now offers a repoint for a MISSING clip that matches a recent move (`watcher.py:335-347`), but a project the editor has not opened is still never revisited.
- RES-11 (library walk cannot see unsaved edits): not built.
- RES-12 (an editor who says "no" is never heard): **half built** - persisted folder ignores with [ FORGET ] exist (`settings_window.py:560-566`); the counts still do not reach the dashboard.
- RES-13 (`save_point_due` burns the slot before the export works): not built.
- RES-14 (edits past 5000 silently unjournalled): not built - `resolve_journal.py:265-267` still returns with no log line.
- RES-15 (a zero-byte or in-flight proxy can be handed to `LinkProxyMedia`): not built.
- RES-16 (macOS CR-68 guard rests on a field lsof may truncate): not built - `script_server.py:281` still has no `+c 0`, `_RESOLVE_NAMES` still exact-match.
- RES-17 (automatic proxy repoint tells no one): not built - subsumed by RES-3 above.
- RES-18 (`verify_copy` proves size, not bytes): not built.
- KNOWN_BUGS carryover item 23 (the four-point live proxy-attach proof) remains unrun and is still marked SHIP-BLOCKER.

## Cross-cutting notes
- **Whoever owns docs/ops:** RES-1 is the highest-value edit in this report and it is
  in a document, not code. The Resolve MCP server exposed to this session states that
  its tools "automatically launch Resolve if it is not running" - that is the CR-68
  trigger by design, on the base rig, and CR-68's own "not done" list still records
  that server's copy of the guard as uncommitted.
- **Dashboard agent:** `cap_cards_state` is stored (`db.py:8465-8467`) and rendered
  nowhere; `fleet_grid.html:269-271` claims a refusal "is in the diagnostics bundle",
  and the companion's diagnostics bundle has no cards section at all. Either render
  the state or fix the comment.
- **Tray/UX agent:** the same idea has four vocabularies in four toasts - "outside",
  "offline", "never sync or come online", "re-addressed" - and `popup.py:1262` says
  `Tray > Settings` where `app.py:2817` and `fixer.py:1188` say `Tray →`. Worth one
  pass for consistency.
- **Sync/lanes agent:** `fixer.sweep_stale_tmp_files` reports but never deletes, and
  lane A will happily upload a `.ccsync-tmp` left by a killed FIX ALL (RES-8).
