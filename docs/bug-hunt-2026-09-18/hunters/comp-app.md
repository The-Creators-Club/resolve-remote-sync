# comp-app - the companion app core (app.py, config, site, identity, machine, eula, capabilities, reporter, idle, supervisor, upgrade, paths/canon/secretfile, ui_state/ui_copy, theme)

Files read (with approximate coverage):
`git diff 34a3c8f..HEAD` over the whole territory in full (only `app.py` +71 and
`config.py` VERSION changed this week) and `git diff 18e69f3..34a3c8f` over the
whole territory in full (`app.py` +418, `machine.py`, `supervisor.py`,
`upgrade.py`); `supervisor.py` in full; `capabilities.py` in full; `idle.py`
(~60%); `secretfile.py` in full; `canon.py` (~50%); `site.py` (~70%, the
normalise/fetch/cache/feature half in full); `machine.py`'s new accessors;
`reporter.py` `_build_payload` / `_drop_unchanged_sections` /
`_note_sections_sent` / `_fit_payload` / `post_once`; `upgrade.py`
`parse_version` / `compare_to_running` / `note_report_response` /
`_clear_refusal` / `upgrade_report`; `config.py` VERSION and
`REQUIRES_DASHBOARD` blocks; `app.py` `_relink_proxies_once`,
`_resume_broll_proxy_upgrades`, `_project_rel_for_slug`,
`_warn_if_machine_id_is_unreadable`, the `__init__` wiring of
`broll_standins.configure` / `server_locate.ServerLocator` (~15% of a
10,902-line file, chosen by the diff and by the fleet/data paths).
Both sides of two wires: `dashboard/src/ccsync_dashboard/api.py`
`_upgrade_info` + the report reply, and `db.py`'s
`expire_delivered_file_moves` (the 09-11b comp-app-1 regression check).
Callee reads outside the territory for verification only:
`sync/server_locate.py`, `sync/sequencer.py`'s `rel_to_slug` property,
`broll_standins.py` (header + `default_state_path`),
`broll_server.resume_pending_upgrades`.

Tests run:
`cd companion; .venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_machine.py tests/test_eula.py tests/test_supervisor.py tests/test_upgrade.py tests/test_capabilities.py tests/test_reporter.py tests/test_bug_hunt_2026_09_11b_comp_app.py -q` -> 768 passed.

## Findings

### comp-app-1 - the b-roll editing-proxy upgrade resume is gated behind `proxy_relink_enabled` and behind `plan_relinks()` not raising
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4449` (the call), `companion/src/ccsync_companion/app.py:4416-4448` (`_relink_proxies_once`'s two early returns and the `try:` it sits inside), `companion/src/ccsync_companion/app.py:4926` (`_resume_broll_proxy_upgrades`)
- What: `_resume_broll_proxy_upgrades()` has exactly one call site, and it is
  the third statement inside `_relink_proxies_once`'s `try:` block. That
  function returns early when `config["proxy_relink_enabled"]` is false and
  when `_local_root_is_broken()`, and the resume call is placed AFTER
  `proxy_relink.plan_relinks(...)` inside the same `try`, so any exception out
  of `plan_relinks` (it now also builds an ffprobe frame counter) skips the
  resume entirely and is swallowed by the outer `except Exception`. The
  docstring's fault isolation runs one way only ("an upgrade that cannot start
  must never cost the relink pass"); the reverse - a relink that cannot plan
  costing every pending upgrade, for ever - is not guarded.
- Failure scenario: an editor sets `proxy_relink_enabled = false` in
  `~/.ccsync/config.toml` (a supported key, `config.py:419`/`:1125`). Send to
  Resolve plants a stand-in and queues the editing-proxy upgrade; the companion
  restarts before the download finishes. The ledger row stays `pending` for
  ever: nothing else ever calls `resume_pending_upgrades`, so that editor cuts
  on a 1080p H.264 lie under a 6K name with no path back except a manual
  re-insert. Same outcome, with no config change at all, on any machine where
  `plan_relinks` raises on one pass and keeps raising (e.g. a bad
  `ffmpeg_path` that makes `frame_counter` throw at construction).
- Evidence: `grep -n "_resume_broll_proxy_upgrades|_relink_proxies_once|resume_pending_upgrades" app.py broll_server.py` -> the only call site is app.py:4449, reached only from app.py:4155. Read `broll_server.resume_pending_upgrades` (broll_server.py:1259): it needs no Resolve connection at all - it reads the ledger and starts downloads - so the "this is the cycle that already means Resolve is open" justification does not apply to the work it does.
- Ledger: new (related to CR-281)
- Suggested fix: hoist the call out of `_relink_proxies_once` to its own
  statement in the 120 s media-pool cycle (beside it at app.py:4155-4156),
  wrapped in its own try, so it is independent of the relink feature flag and
  of `plan_relinks` succeeding.

### comp-app-2 - the relaunch ceiling's primary source is still written non-atomically, in the one process that exists because machines die abruptly
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/supervisor.py:196` (`write_history`), against `companion/src/ccsync_companion/supervisor.py:242` (`write_relaunch_note`, made tmp+replace by the same fix pass) and `supervisor.py:190` (`read_history`)
- What: the 09-11b pass gave `write_relaunch_note` tmp+replace with the stated
  reason "a kill mid-write cannot leave half a note behind either", and left
  `write_history` - `<state>/supervisor.json`, the source `decide()` actually
  reads on a cold chain - as a bare `write_text`. A process killed while that
  file is being rewritten leaves truncated JSON; `read_history` catches the
  `JSONDecodeError` and returns `[]`. Separately, `read_history` builds the
  list with a comprehension inside the same try, so ONE non-float entry
  discards every stamp rather than that entry.
- Failure scenario: a machine whose companion aborts (the CR-93 shape) is power
  cut, or the user holds the power button, while the supervisor is writing
  `supervisor.json`. On the next boot the file is half a JSON object,
  `read_history` answers `[]`, and `--prior` is absent because the chain
  started fresh from the logon autostart. A build that cannot stay up is then
  relaunched three more times an hour, every hour, with nothing anywhere saying
  the ceiling was lost - exactly the condition res-companion-4 added the
  WARNING for, except that this path produces no warning because the write
  "succeeded".
- Evidence: read both functions side by side. `write_history` ->
  `(state_dir / HISTORY_FILENAME).write_text(json.dumps(...))`, no tmp, no
  `os.replace`. `write_relaunch_note` (11 lines below) -> `tmp.write_text` +
  `os.replace(tmp, path)`. `read_history`'s `except Exception: return []`
  covers both the parse and the float coercion.
- Ledger: CR-259..CR-266's res-companion-4 / regression-21 work does not fix this half (partial fix of the same defect class)
- Suggested fix: give `write_history` the same tmp+replace as
  `write_relaunch_note`, and coerce the stamps one at a time
  (`try/except (TypeError, ValueError): continue`) so a single bad entry costs
  one entry.

### comp-app-3 - a standing upgrade refusal is cleared by the four report replies that mean "there IS a build, we are just not offering it"
- Severity: medium
- Confidence: CONFIRMED (both sides read; the user-visible consequence is PLAUSIBLE)
- Where: `companion/src/ccsync_companion/upgrade.py:1561-1578` (`note_report_response`'s `if (not offered and isinstance(resp, dict) and not resp.get("upgrade")): self._clear_refusal()`), against `dashboard/src/ccsync_dashboard/api.py:5716-5775` (`_upgrade_info`)
- What: the comp-ytdl-jobs-1 fix treats "the reply carries no `upgrade` key" as
  "the dashboard says there is nothing to take", and justifies itself with "a
  still-current refused build is re-offered and re-refused on the very next
  report, so nothing true is lost". `_upgrade_info` returns `None` - i.e. omits
  the key - for four further reasons, three of which its own comment calls
  "silent to the companion on purpose": the current package is retracted
  (`retracted_at`), it needs a newer dashboard
  (`blocks_on_dashboard_version`), its `arch` does not match the reporter's,
  or the reported `platform` is unknown. In all four the build is NOT
  re-offered, so the refusal is cleared and never restored.
- Failure scenario: an editor's machine refuses build X (signature failure, or
  X below its signed `min_version` floor); the dashboard shows
  `[ REFUSING X ]` and lights `upgrade_refused`. The vendor then publishes a
  build whose `requires_dashboard` is above the dashboard's own version (or an
  admin rolls the dashboard back, or the machine is an Intel Mac and the
  current package is arm64). From the next report on, the reply carries no
  `upgrade` key, the companion clears `last_refusal`, the chip and the alert
  go out, and the operator is told nothing is wrong on a machine that is
  refusing to upgrade and will not be offered anything.
- Evidence: read `_upgrade_info` in full - four `return None` paths before the
  offer is built, with the comment "Each is silent to the companion on purpose
  -- there is no 'refused offer' shape in the protocol". Read
  `note_report_response`: the only guard is `resp.get("upgrade")` falsy and
  `info is None` from a parse failure. Both of the fix's regression tests
  (`test_bug_hunt_2026_09_11b_comp_ytdl_jobs.py`) construct the reply by hand,
  so neither exercises a dashboard in one of these four states.
- Ledger: CR-249..CR-266's comp-ytdl-jobs-1 introduces this
- Suggested fix: have the dashboard state the distinction explicitly - e.g. an
  `upgrade_none_reason` on the reply, present only when a package exists but is
  being withheld - and clear the refusal only on its absence; or, cheaply,
  clear only when `running == current` can be inferred (the reply already
  carries the machine's own version back in the fleet-grid path).

### comp-app-4 - "CCSync" is hardcoded in ~60 user-visible companion strings while the vendor-neutral brand helper is used once
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:137`, `:703-704`, `:717-719`, `:2592`, `:2672`, `:2681`, `:2708`, `:2716`, `:2902`, `:2921`, `:2937`, `:3287`, `:3483` and ~50 more; the single correct call is `app.py:5966` (`site_mod.product_name()`)
- What: CLAUDE.md's invariant is "No customer's name in code. Brand strings come
  from the site manifest (`org_name`/`org_short`) with the product name
  (`CC Sync`) as the last fallback; the tray/popup copy goes through
  `companion/site.drive_phrase()`". `site.py` implements exactly that
  (`org_short()`, `product_name()`, `DEFAULT_PRODUCT_NAME = "CC Sync"`), and
  `app.py` calls it once. Every other dialog, balloon and error sentence says
  the literal string `CCSync`, which is neither the site's org name nor the
  product name as this repo spells it.
- Failure scenario: a second customer provisions a dashboard with
  `org_short = "Acme"`. Their editors' trays and dialogs say "CCSync is already
  running", "CCSync STOPPED downloading proxies as a safety measure", "Re-grant
  CCSync Full Disk Access" - the vendor's internal spelling, in a product that
  was made vendor-neutral precisely so a second customer would not fork it
  (COMMERCIAL_READINESS item 10).
- Evidence: `grep -c "CCSync" app.py` -> 65; `grep -n "site_mod.product_name|site_mod.org_short" app.py` -> one hit (5966). `grep -rln CCSync *.py` -> 32 modules. `site.py:335` -> `DEFAULT_PRODUCT_NAME = "CC Sync"` (with a space), so even the vendor build's own name is spelled two ways.
- Ledger: new (COMMERCIAL_READINESS item 10 is not finished on the companion side)
- Suggested fix: add a `site.app_name()` (org_short -> product_name -> "CC Sync")
  and route the user-visible literals through it, with a scan test in the
  companion suite in the shape of the existing em-dash scan; leave comments and
  log lines alone.

### comp-app-5 - `read_history` loses the whole relaunch ceiling to one unparseable stamp
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/supervisor.py:190-194`
- What: `return [float(t) for t in data.get("relaunches", [])]` inside a
  `try/except Exception: return []`. `merge_history`, written the same day for
  the same data, deliberately skips a bad item and keeps the rest
  (`except (TypeError, ValueError): continue`). The reader does the opposite.
- Failure scenario: `supervisor.json` ends up with `{"relaunches": [1.0, null,
  3.0]}` (a half-written file, a hand edit, a future field). Every supervisor in
  the chain reads an empty history and the "three relaunches an hour" ceiling
  restarts from zero on a machine that has already been relaunched three times.
- Evidence: read `read_history` and `merge_history` side by side; the two
  disagree on the same list.
- Ledger: new (same fix pass as comp-app-2)
- Suggested fix: coerce per item, the way `merge_history` already does, and
  hand the result to `merge_history` regardless.

### comp-app-6 - the "cannot read this computer's id file" toast does not mention the repair the same fix pass built
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:9109-9116`, against `companion/src/ccsync_companion/settings_window.py:479-509` (`machine_mod.remint()` behind a button)
- What: comp-app-8's fix has two halves - a once-per-process tray warning and a
  repair button in the Settings window. The warning's copy predates the button:
  it says "Send your log to your admin: the file is repairable and CCSync will
  not overwrite it on its own", and never says that the tray's own Settings
  window offers the repair. The person reading the toast is told to wait for
  somebody else.
- Failure scenario: an editor sees the balloon, mails their log, and the machine
  goes on reporting no `machine_id` until an admin replies - while the fix was
  two clicks away in Settings.
- Evidence: read both call sites; `grep -rn "remint|machine_id_unreadable" src/`
  shows the only repair entry point is `settings_window.py:497`.
- Ledger: CR-249..CR-266's comp-app-8 is incomplete
- Suggested fix: one sentence in the toast pointing at Settings, in the wording
  the button already uses.

### comp-app-7 - a cached `capabilities` block keeps a stale `jobs_gate` when the runner stops answering
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/capabilities.py:277-280`
- What: in the cache-hit branch the four volatile fields are recomputed, and
  then `gate = _jobs_gate(...)` is written back only `if gate:`. `_jobs_gate`
  answers `{}` for "the runner could not say" - which is a meaningful state the
  module's own docstring insists must be ABSENT, not a guess. Because the cache
  copy is a shallow `dict(cached[1])` of a section that never stores
  `jobs_gate`, the practical effect is limited to the first 45 s after a cache
  fill, but the asymmetry is the bug: an empty answer cannot displace a
  non-empty one.
- Failure scenario: the job runner thread dies; `jobs_gate_fn` starts raising.
  Every report still carries the last `jobs_gate` this process assembled, so
  the dashboard's "why is this machine taking no work" panel answers with a
  fact the machine is no longer asserting.
- Evidence: read `build()`'s two branches; `_cache` is stored at line 317
  before `jobs_gate` is added at 325, so the field only ever comes from the
  live call, and the live call's empty answer is dropped instead of clearing.
- Ledger: new
- Suggested fix: `answer.pop("jobs_gate", None)` before the `if gate:` in the
  cached branch (and the same in the fresh one), so absent means absent.

## Coverage note
`app.py` is 10,902 lines; I read the diff, the fleet/data paths named above and
the Resolve-adjacent piggy-backs, which is roughly 15% of it. Not read:
`shutdown_guard.py` (1,602 lines) and `theme.py` at all, `identity.py` and
`eula.py` beyond their public surfaces, `paths.py` and `ui_copy.py` beyond a
skim, and the download/verify/apply half of `upgrade.py` (2,043 lines). The
suite does not cover: a truncated `supervisor.json` (no test writes half a
file), a report reply with no `upgrade` key from a dashboard in one of
`_upgrade_info`'s four withholding states, `_relink_proxies_once` with
`proxy_relink_enabled = false` (no test asserts the resume runs or does not),
or the brand of any user-visible string other than the EULA line.
`canon.norm` is documented as the key for "dedupe keys, ignore sets,
warn-once bookkeeping" but applies no NFC fold, so those keys are two
different strings for the same file on a Mac (CR-90's shape); I could not
find a caller where that costs more than a duplicated warning, so it is
noted here rather than reported.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/sync/sequencer.py:749`: `rel_to_slug` is selection-only, so `app._project_rel_for_slug` answers None for a file hand-moved into a BORROWED folder this machine does syncs via lane C; `rel_to_slug_with_borrowed()` exists and is not used there. comp-sync's call.
- `dashboard/src/ccsync_dashboard/api.py:5716`: `_upgrade_info` has four silent-to-the-companion `return None` paths that are now load-bearing for companion state (see comp-app-3); dash-api / wire should decide which side declares the distinction.
