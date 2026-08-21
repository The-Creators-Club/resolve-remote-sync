# Why the tray menu sometimes opens late (investigation, 2026-08-21)

**Symptom.** Right-clicking the companion's tray icon sometimes does not show
the menu instantly. The delay varies (a fraction of a second to many
seconds), it is not every click, and it has survived two earlier rounds of
fixes (2026-07-26 and the 2026-08-17 tray rewrite). Of the work in section 5,
only step 1 (instrumentation) is built so far. Ledger entry: KNOWN_BUGS
CR-70.

Scope: Windows. The macOS backend has a different set of problems
(bug-hunt-2026-08-21 comp-app-core-2: AppKit touched off the main thread) and
is not covered here.

## 1. How a right-click becomes a menu, and where it can stall

1. Explorer sees the click on our icon and **posts** `_CCSYNC_WM_TRAY`
   (lParam `WM_RBUTTONUP`) to the companion's hidden window. Posting is
   asynchronous: Explorer is not blocked by us, and nothing on Explorer's side
   waits for the menu.
2. The companion's pump thread (`tray_native._WindowsIcon._pump`, a plain
   `threading.Thread` running `GetMessageW` in a loop) wakes with the message
   and calls `DispatchMessageW`.
3. USER32 calls our window procedure. **The window procedure is a ctypes
   callback into Python, so before one line of it runs the pump thread must
   take the GIL.**
4. `_show_menu` builds the HMENU (`menu.rendered()` + `InsertMenuItemW` per
   row), asks Explorer where the taskbar is (`SHAppBarMessage`, a synchronous
   SendMessage into Explorer), calls `SetForegroundWindow`, then
   `TrackPopupMenuEx`. The menu appears inside that last call.

Steps 1, 2 and 4 are fast in practice (the whole build is a few hundred
microseconds; `SHAppBarMessage` normally returns in under a millisecond).
Step 3 is where the time goes.

## 2. The primary cause: a fusionscript call holds the GIL for its whole native duration

`resolve_bridge` drives Resolve through `fusionscript.dll`, loaded in-process.
The companion has known since 2026-07-26 that **a fusionscript call holds the
GIL until Resolve answers** (it never releases it the way socket/ctypes/sqlite
calls do), and the repo already carries two mitigations for exactly this
symptom:

* `ui_state.wait_while_menu_open()` in front of every Resolve entry point -
  protects the *open* menu's highlight, and by its own comment
  (`resolve_bridge.py` around line 621) "cannot help ... the click trying to
  open it".
* `_sweep_yield` - a 2 ms `time.sleep` every 25 clips of a timeline walk, so
  the pump "is never more than 25 clips away from a slot". Plus the poll cache
  that skips the per-clip walk when a cheap fingerprint matches.

Both assume that individual calls are quick and that the blackout comes from
*many* of them in a row. That assumption is what is wrong. Each single call
is an RPC into Resolve's own process, serviced by Resolve's UI/main thread,
and it takes as long as Resolve takes to get to it: tens of milliseconds when
Resolve is idle, hundreds of milliseconds to seconds during playback, a
conform, a render, a project load, a modal dialog, or a media-pool operation
on a slow share. During any such call nothing Python in the companion runs -
not the pump thread, not the refresh loop, not the pulse - so the right-click
sits in the message queue until the call returns. Nothing in the repo bounds
a single call's duration, and there is no timeout mechanism possible from
inside the process (bug-hunt-2026-08-14 made the same point about the
watcher and the loopback servers).

How often is a call in flight? The watcher polls every `poll_interval` = 3 s
and even the cheap-fingerprint path makes several calls per poll
(`GetProjectManager`, `GetCurrentProject`, `GetCurrentTimeline`, name, unique
id, track counts, one `GetItemListInTrack` per track). On top of that the
media-tree thread, the proxy generator's Resolve probes, the b-roll insert
path and FIX ALL all go through the same bridge. So at any instant there is a
real probability that a call is mid-flight, and the delay an editor sees is
the *remaining* duration of whatever call their click happened to land
behind. That is precisely "varies, and not every time".

### Evidence from this machine's log (`~/.ccsync/companion.log`, build 0.9.41)

The bridge logs a wedge only when a second caller has waited
`BRIDGE_WEDGE_SECONDS` = 30 s for `_API_LOCK`. Six such lines in three days:

| when | call inside Resolve | for | waiter waited |
|---|---|---|---|
| 2026-08-19 19:56 | get_media_pool_items | 40 s | 37 s |
| 2026-08-20 09:18 | get_timeline_items | 47 s | 33 s |
| 2026-08-20 09:47 | get_timeline_items | 80 s | 37 s |
| 2026-08-20 13:10 | get_timeline_items | 91 s | 40 s |
| 2026-08-20 16:53 | get_timeline_items | 33 s | 32 s |
| 2026-08-21 14:44 | get_timeline_items | 50 s | 30 s |

Two things these lines prove, beyond "Resolve is slow sometimes":

1. **The GIL really is held for the whole call.** The waiter's
   `_API_LOCK.acquire(timeout=30)` returns after 30 s, but logging the
   warning needs the GIL. In every row the warning's timestamp equals the
   moment the call *ended* (waiter start + 30 s is always earlier than the
   logged "inside for N s"): the waiter could not get a word out until the
   fusionscript call came back. A right-click in that window waits the same
   way.
2. **Calls of 30-90 s happen roughly daily on the base rig.** Anything
   shorter than 30 s - the 0.3 s to 10 s band that an editor experiences as
   "the menu is slow" - is invisible by design: no log line, no counter.
   The logged wedges are the tail of a distribution whose body we never
   record.

During each of those six windows the tray was not "slow": it was dead - no
menu, no tooltip update, no pulse, for 33 to 91 seconds.

### Why the earlier fixes did not finish the job

* 2026-07-26: fingerprinted menu rebuilds, the menu-open flag, deferring
  Resolve calls while the menu is open. These fixed the *open-menu* hangs
  (repaints under the cursor, destroyed HMENU) and did.
* `_sweep_yield` + poll cache: reduced the number of calls per poll. The
  blackout per *call* is untouched, and the yield is counted in clips, not
  time: 25 clips at 3-4 calls each is 75-100 round trips between yields, which
  is seconds when Resolve is busy.
* 2026-08-17 `tray_native` rewrite: removed the pystray-era race (destroyed
  handle, `TrackPopupMenuEx` returning 0 with `GetLastError` 0 - 24 of those
  are in the log from the 0.9.2 era, none after the rewrite). The pump is
  still a Python callback and still needs the GIL, so the GIL-hold class of
  delay survived the rewrite unchanged.

## 3. Secondary causes (real, smaller, or situational)

Ranked by how likely they are to be what an editor sees.

**3a. Any other in-process work that holds the GIL without releasing it.**
Pure-Python CPU work on the companion's ~30 threads costs the pump at most
the 5 ms switch interval per contending thread and is not the problem. C
work that does not release the GIL is: fusionscript is the big one, and the
`scriptapp("Resolve")` connect itself can block "for minutes" when Resolve's
script server is in a bad state (`music_worker.py`'s reason for living in a
child process; `connect()` now only avoids the *launch* window, CR-68).
Today's log ends with "Resolve is running but isn't accepting scripting
connections" - the state in which a connect attempt is most likely to stall.

**3b. CPython garbage collection.** A full (generation 2) collection runs on
whichever thread happens to allocate, holds the GIL, and scales with the
number of live container objects. The companion holds the media manifest,
the proxy ledger, timeline snapshots and the b-roll/music ingest state as
ordinary dicts and lists; on a machine with a big tree a gen-2 pass can
plausibly cost 100-500 ms and it recurs as allocation churn continues. This
is a hypothesis, not measured; `gc.callbacks` timing (section 5) would settle
it in one session.

**3c. `SHAppBarMessage(ABM_GETTASKBARPOS)` on the pump thread (added in
0.5.1, `a3f4b96`).** It is a synchronous SendMessage into Explorer's taskbar
window and returns only when Explorer's tray thread gets to it. Explorer is
normally instant, but it is also the thread that animates the Windows 11
taskbar, the hidden-icons flyout and thumbnail previews, and it can be
busy for hundreds of milliseconds right after the very click we are
handling. It does not explain multi-second delays but it is the one call on
the click path that depends on another process.

**3d. Working-set trimming / paging.** A tray app with no visible window is
first in line when Windows trims working sets under memory pressure, and
Resolve on an editing machine supplies the pressure. The first right-click
after a quiet spell then pays hard page faults to bring the interpreter, the
ctypes thunks and the menu-build code back in. Characteristic: a delay only
on the *first* click after a while, instant afterwards.

**3e. Windows power throttling (EcoQoS / "efficiency mode").** Windows 11
may classify a windowless background process as throttleable and run its
threads at reduced frequency or on efficiency cores. The companion sets
nothing either way (`PROCESS_POWER_THROTTLING_STATE` is never touched; only
ffmpeg children get `BELOW_NORMAL_PRIORITY_CLASS`). This would make every UI
interaction feel sluggish rather than produce occasional multi-second stalls,
so it is a contributor at most. Checkable from Task Manager's "Efficiency
mode" leaf on `ccsync-companion.exe`, or with `GetProcessInformation(...,
ProcessPowerThrottling, ...)`. The companion was not running when this
investigation ran, so it is unchecked.

**3f. Two backend defects that turn a delay into "the click did nothing".**
Both are in the log after the rewrite:

* `GetLastError=1446` (`ERROR_POPUP_ALREADY_ACTIVE`, 2026-08-19 13:19): a
  second `WM_RBUTTONUP` was dispatched while `TrackPopupMenuEx` was already
  running. That is the signature of the primary cause seen from the other
  side: the editor clicked, nothing appeared, they clicked again; when the
  GIL came back both clicks were in the queue, the first opened the menu and
  the second, dispatched from inside the menu's own modal loop, re-entered
  `_show_menu` and failed. `_show_menu` has no re-entry guard (the
  `_menu_open` Event is set, but nobody checks it on the way in).
* `GetLastError=1400` (`ERROR_INVALID_WINDOW_HANDLE`, twice at 2026-08-21
  14:24:50): clicks dispatched after `_CCSYNC_WM_QUIT_TRAY` destroyed the
  window during a restart. Harmless, but it is noise in the very log line we
  will want to trust.

**3g. Explorer itself.** Windows 11's taskbar occasionally delivers tray
callbacks late, especially for icons living in the hidden-icons flyout. This
is outside the companion and cannot be fixed here, but it can be *ruled in or
out* cheaply: `companion/tools/tray_smoke.py` runs the identical backend with
no Resolve, no lanes and no other threads. If its menu ever lags on the same
machine, the lag is Explorer's; if it never does, the lag is ours.

Ruled out: menu actions blocking the pump (every handler goes through
`_spawn`; only Quit runs inline, deliberately), the old destroyed-handle
race (structurally gone), menu size (building ~40 rows is sub-millisecond),
and logging on the click path (nothing is logged before the menu shows).

## 4. What we cannot currently see

There is no measurement of click-to-menu latency anywhere. The wedge detector
starts at 30 s; below that the companion records nothing, which is why three
rounds of work have been aimed by feel. The cheapest next step is not a fix,
it is instrumentation - and Windows hands us the number for free: the `MSG`
struct the pump already reads carries `time`, the tick count at which
Explorer posted the message, so `GetTickCount() - msg.time` at dispatch is
the exact queue latency of that click, measured by the OS, with no clock of
ours involved.

## 5. Recommended order of work

1. **Instrument - DONE in repo 2026-08-21 (unshipped).** `_pump` stamps
   `GetTickCount() - MSG.time` (modulo 2**32) for every menu click and
   `_show_menu` times everything before `TrackPopupMenuEx`. A click that
   waited >= 150 ms in the queue, or a build that took >= 150 ms, logs ONE
   line under `ccsync.tray.native`:

       WARNING tray menu opened late: the click waited 1830 ms in the queue
       and the menu took 3 ms to build (Resolve call in flight:
       get_timeline_items for 4.2s; gc counts (412, 3, 1))

   Fast clicks log the same two numbers at DEBUG. Read the field logs as:
   queue time with a Resolve call named = section 2; queue time with "no
   Resolve call in flight" = 3a/3b/3d/3e (the gc counts help split 3b out);
   build time large = 3c. A week of fleet logs turns section 2 from "very
   likely" into "this call, this often, this long" per machine.
2. **Guard `_show_menu` against re-entry and a dead window** (3f): if
   `_menu_open` is already set, ignore the click instead of calling
   `TrackPopupMenuEx` into a 1446; if `_hwnd` is None, return. Small,
   independent, removes two misleading log lines.
3. **The structural fix: take fusionscript out of the process that owns the
   tray.** Two shapes, either ends the GIL coupling for good:
   * *Resolve in a child process* - the pattern `music_worker.py` already
     uses and that bug-hunt-2026-08-14 recommended for the watcher and the
     loopback servers. The main process keeps the tray, lanes and servers;
     the child holds `_API_LOCK` and the fusionscript module, is killable on
     a deadline (which also gives us the per-call timeout the bridge cannot
     have today), and a fusionscript 0xc0000005 no longer takes the tray with
     it. Cost: the per-file pool-walk concern noted at
     `resolve_bridge.py` ~1216 (ImportMedia batches) - solvable by batching
     in the child rather than per call.
   * *Tray in a child process* - a tiny process that owns the icon, menu and
     message pump and talks to the companion over the existing 8899
     loopback. Smaller change to the bridge, but it moves the menu's data
     (lane lines, snapshot) across a process boundary and leaves every other
     "why did X freeze" symptom (watcher, /insert, dashboard reports) in
     place.
   The first is the right one: it fixes the tray *and* the rest of the
   fusionscript-hold family at once.
4. **Tactical, if 3 has to wait:** make `_sweep_yield` time-based (yield
   whenever more than ~50 ms has passed, not every 25 clips); lengthen the
   watcher poll while the timeline fingerprint has not changed for a while;
   and move `SHAppBarMessage` off the click path by caching the taskbar
   rectangle from the refresh thread (re-read on `WM_SETTINGCHANGE` /
   `ABN_POSCHANGED` or just every refresh tick). None of these remove the
   cause; each shrinks the window.

## 6. Files

* `companion/src/ccsync_companion/tray_native.py` - `_pump`, `_on_message`,
  `_show_menu`, `_anchor_clear_of_taskbar`
* `companion/src/ccsync_companion/tray.py` - `start_tray`, `_refresh_loop`,
  `_pulse_loop`, `_tray_snapshot`, `_MenuOpenGuard`
* `companion/src/ccsync_companion/ui_state.py` - `menu_open`,
  `wait_while_menu_open`
* `companion/src/ccsync_companion/resolve_bridge.py` - `_API_LOCK`,
  `_bridge_call`, `_note_wedge`, `_sweep_yield`, `connect`
* `companion/src/ccsync_companion/watcher.py` - `run` (3 s poll)
* `companion/tools/tray_smoke.py` - the backend alone, for the
  Explorer-or-us test
* `docs/bug-hunt-2026-08-14.md` - the earlier "no timeout on any
  fusionscript call" finding and the child-process recommendation
