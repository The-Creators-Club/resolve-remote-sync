# Verifier med-02 (2026-09-25)

Judged against HEAD (63d4290) with `git show HEAD:<path>`. Read-only; the
only file written is this one. Nothing touched Resolve, `~/.ccsync` or a live
process.

## bug-comp-ui-1 - CONFIRMED (medium)

`_tk_pick` (popup.py HEAD ~2694) builds `tk.Tk()` inside
`ui_dispatch.dispatch(_ask)`, and on win32 `dispatch()` is a plain inline
call (ui_dispatch.py `dispatch`: `dispatcher is None -> return fn()`), so the
root is built on the `ccsync-ingest-picker` helper thread with no
`_popup_active_lock` taken or checked anywhere on the path
(`broll_server.pick_ingest_sources` -> `popup.pick_media_sources` ->
`_tk_pick`). `pick_media_sources` returns `[]` after `done.wait(timeout)`
(300 s) and nothing closes the dialog; the late pick lands in `box` and is
dropped, and `pick_ingest_sources` answers "cancelled". A second click starts
a second picker thread/root beside the first. No earlier hunt or KNOWN_BUGS
entry covers the lock or the timeout (the 2026-09-03 hunt only praised the
dispatch/release_root half).

Evidence: read popup.py `_tk_pick`/`pick_media_sources`, ui_dispatch.py
`dispatch`, broll_server.py `pick_ingest_sources`; grep of KNOWN_BUGS and
earlier hunts for picker lock/timeout.

## bug-comp-ui-2 - DOWNGRADE (low)

The mechanism reads correctly: `__setattr__('menu')` -> `_apply_menu` ->
`_to_main` enqueues `_apply_menu_now`, which unconditionally rebinds
`self._targets`/`self._delegate`, and NSMenu's delegate is weak, so a rebuild
that runs while the old menu is tracking loses `menuDidClose_`. But the window
is the few milliseconds between the refresh loop's `guard.is_open()` check and
the main-queue block running, it is macOS only and unverified on a Mac, and it
is not "forever": the next time the editor opens and closes the (new) menu, its
watcher sets and clears `ui_state.menu_open` and everything resumes. That makes
it a rare, self-healing stall (tray frozen and Resolve calls deferred 8 s until
the next menu click), which is low.

Evidence: read tray_native.py `_apply_menu`, `_apply_menu_now`,
`_build_nsmenu`, `CCSyncTrayMenuWatcher`; tray.py `_MenuOpenGuard` and
`_refresh_loop`.

## bug-comp-resolve-1 - CONFIRMED (medium)

`apply_undo` classifies the bridge's refusal by substring. Replaying its own
lists against the four `DISCONNECTION_MESSAGES`: "not running" -> retrying
("resolve"+"not"), NO_SCRIPTING -> retrying ("does not help"), NO_SERVER ->
retrying ("is open"), STARTING_MESSAGE "DaVinci Resolve is starting up" ->
**failed**. `undo_last_relink` returns `get_media_pool_items()`'s message,
which `_explain_disconnection` sets from `describe_disconnection()`, and that
returns STARTING_MESSAGE whenever `script_server_starting()`. app.py
`_apply_resolve_undo` records a non-retrying state in the ledger and never
re-applies it on redelivery, so the admin's undo is retired as failed purely on
timing.

Evidence: ran the HEAD PARK_HINTS/RETRY_HINTS/`"resolve" and "not"` logic over
the messages in a Python one-liner (starting up -> failed, the other two ->
retry); read resolve_bridge.py 495-624, 2572-2640, app.py 8303-8360.

## bug-comp-resolve-2 - CONFIRMED (medium)

`current_project_name()` caches for 20 s with no invalidation (the only writer
of `_project_name_cache` is the function itself); `_before_mutation`, the
proxy-link journal entry (resolve_bridge 3050), and both automatic rate
limiters (app.py 3258, 4653) use the default TTL. Only `undo_last_relink` reads
with `max_age=0`. So after a project switch inside the window, B's
unprompted relink is journalled under A's slug and charged to A's limiter, and
the later undo in A passes the journal-vs-open-project check (`A == A`) and
replays B's path entries against A's pool, which shares Assets paths. That is
the comp-resolve-2 / CR-51 hazard reopened. It needs a cache read in the 20 s
before the switch plus an automatic relink right after, so medium rather than
high despite the unjournalled-rewrite outcome.

Evidence: read resolve_bridge.py 2126-2245, 2572-2640, the four app.py call
sites; `git grep _project_name_cache HEAD`.

## bug-comp-resolve-3 - CONFIRMED (medium)

`CardsBridge.sweep_items` calls `resolve_bridge.get_timeline_items(allow_cached=True)`;
when `_library_timeline_items` returns None that function falls through to
`_get_timeline_items_locked` under `_bridge_call` (the API lock), and only
afterwards does `sweep_items` throw away the answer because its items are
`source == "api"`. The call shares the watcher's poll cache, and every cache
hit bumps `_polls_since_full_walk`, so the engine's sweep (called from every
`ResolveEngine._sweep`, MulticamPipeline resolve_engine.py 448-477) speeds up
the watcher's per-clip full-walk valve. It also bypasses
`poll_timeline_items`'s stated "the watcher's entry point and nobody else's".
Gated by `cards_agent`, but that role is live on the Cards machine, and
library-less is the documented default state.

Evidence: read timeline_cards_bridge.py 210-260, resolve_bridge.py 1173-1300
(`get_timeline_items`, `_cached_timeline_result`), MulticamPipeline
`_sweep`/`_sweep_rows`.

## bug-comp-resolve-4 - CONFIRMED (medium)

`supervise_now` restarts when any loop is dead or `_loop_error` is set;
`_clear_dead` drops the thread list and calls `_release_engine`, but the
surviving daemon loop keeps its client, whose `_req` is `role.call` with no
generation/current-client check, and whose `self.eng` is the old engine. The
old `pull_loop` keeps taking `/cards/agent/pending` and staging requests on
engine #1. Worse than the finding says: `_release_engine` does nothing at all
for this engine, because neither `SyncEngine`, `LibraryEngine` nor
`ResolveEngine` has a `stop` in the MulticamPipeline checkout (`git grep 'def
stop' HEAD -- multicam_pipeline/cards/` finds only keys.py and
project_agent.py), and `SyncEngine.__getattr__` turns `getattr(engine,
"stop", None)` into None. So engine #1's Resolve thread keeps sweeping and,
fed by the orphan pull loop, applies edits alongside engine #2. Kept at medium
because it needs a loop to die first and the role is opt-in, but the
confidence is now CONFIRMED, not PLAUSIBLE.

Evidence: read timeline_cards_role.py 379-400, 629-940; MulticamPipeline
agent.py `pull_loop`/`_apply_one`, resolve_engine.py `SyncEngine`, and the
`def stop` grep.

## Duplicates

None within this group or against the highs (checked the summary table in
`docs/bug-hunt-2026-09-24.md`).
