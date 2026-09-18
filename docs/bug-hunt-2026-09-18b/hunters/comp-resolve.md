# comp-resolve - the companion's Resolve bridge, proxy relink/refresh, watcher, Cards role

Files read (with approximate coverage): `git diff` over the whole territory first
(only four files changed today: `proxy_relink.py` +379, `resolve_bridge.py` +150,
`timeline_cards_role.py` +54, `watcher.py` +33 - all read hunk by hunk). Then in
full or near-full: `proxy_relink.py` (all of `_geometry_disagrees`,
`plan_relinks`, `apply_relinks`, the three new module caches, `_openable_path` /
`_local_twin` / `_proxy_fingerprint` / `expected_proxy_paths` /
`find_proxy_on_disk`), `resolve_bridge.py` (`replace_clip`, `link_proxy_media`,
`clip_proxy_state`, `_real_original_here`, `_attach_adjacent_proxy` and its one
caller, the b-roll insert), `watcher.py` `_archive_exempt` + the memo,
`timeline_cards_role.py` `_note_answer` / `_tunnel` / `report_block`. Read as the
other side of each wire (cite only): `broll_standins.py` (`is_standin`,
`is_stale`, `archive_rel_of`), `app.py` `_relink_proxies_once` +
`note_report_response`, `dashboard/.../api.py` report reply + `db.standins_known`,
`dashboard/.../cards_tunnel.py` `_no_engine` / `_routed` / the pending route,
`proxy_scan.py` (`GENERATED_EXT`, the .mp4 rule), `proxy_gen.py` `_build_cmd`.
Plus the tests: `test_bug_hunt_2026_09_18_companion_media.py` (CR-284D/E/R/S/T/U,
proxy-tiers-4), `test_bug_hunt_2026_09_18_companion.py` comp-resolve-1/-2,
`test_proxy_relink.py`.

Tests run: `companion/.venv/Scripts/python.exe -m pytest tests/test_proxy_relink.py tests/test_bug_hunt_2026_09_18_companion_media.py -q` -> 80 passed.
Plus three ad-hoc snippets from the companion venv (scratchpad, not in the repo);
their output is quoted in the findings below.

## Findings

### comp-resolve-1 - the refresh verdict is written under a key nothing ever reads, on every machine that cannot open the canonical spelling
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:1023` and `:1046`
  (`note_geometry_verdict(op["file_path"], ...)`) against
  `companion/src/ccsync_companion/proxy_relink.py:542`
  (`remembered_geometry_verdict(probe, ...)`)
- What: `_geometry_disagrees` keys its memory on `probe`, the spelling
  `_openable_path` proved is openable on THIS machine (the local twin when the
  canonical `P:\...` is not visible). `apply_relinks` writes the verdict back
  under `op["file_path"]`, which is the clip's own spelling as Resolve reports
  it - the canonical one. `_geometry_key` normcases and normpaths, so
  `p:\assets\...` and `f:\creators_club\assets\...` are two different keys.
  Wherever the two spellings differ, every verdict `apply_relinks` records is
  unreadable and the memory the whole of comp-resolve-1/-2/CR-284R rests on
  never hits.
- Failure scenario: a macOS editor (or any companion whose process has no `P:`
  mapping - `_local_twin`'s own docstring: "a service or a remote shell has no
  P: even though the editor's own Resolve does, and a macOS editor has no P: at
  all") holds an archive clip born from a stand-in. Pass 1: `is_stale(probe)` is
  True, a refresh is planned, `replace_clip(force=True)` runs, `apply_relinks`
  notes the verdict under `P:\...`. Pass 2 (120 s later):
  `remembered_geometry_verdict(F:\...)` returns None, the ledger entry is still
  stale (nothing ever clears it), so the SAME refresh is planned again - and
  again, for ever. Each of those passes spends one of the eight
  `resolve_journal.allow_automatic` grants a day (`app.py:4654`), so within
  ~16 minutes the proxy-relink pass is rate-limited out for the rest of the day
  and genuine proxy attachments stop happening on that machine. This is exactly
  the harm CR-284R's ledger entry says it closed.
- Evidence: snippet from `companion/.venv`, with `local_root=F:\Creators_Club`,
  `canonical_prefix=P:\` and only the twin existing:

      probe: F:\Creators_Club\Assets\B-roll Archive\Creators_Club\ff5\A001.mov
      lookup under probe: None
      keys: ['p:\\assets\\b-roll archive\\creators_club\\ff5\\a001.mov|300']
      probe key: f:\creators_club\assets\b-roll archive\creators_club\ff5\a001.mov|300

  The regression test (`test_a_clip_that_will_not_converge_is_refreshed_once_not_for_ever`,
  `test_bug_hunt_2026_09_18_companion_media.py:524`) uses a `tmp_path` file, so
  `file_path == probe` by construction and the mismatch cannot show. Its own
  closing comment ("plan_relinks is what must stop giving it") is the assertion
  it does not make.
- Ledger: CR-284R / comp-resolve-1 does not fix comp-resolve-1 on a machine
  where the canonical prefix is not openable.
- Suggested fix: carry the probe spelling out of `_geometry_disagrees` (or
  re-derive it in `apply_relinks` with `_openable_path`) and note the verdict
  under the same key, or key the verdict on the resolved local twin in both
  places. Add a regression test whose `file_path` is canonical and whose only
  existing file is the local twin.

### comp-resolve-2 - a forced refresh in which ReplaceClip RAISED (but not every time) is remembered for ever as "this file is settled"
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/resolve_bridge.py:2382-2394`
  (`if raised == max(1, tries)` then the `if refresh:` branch), consumed at
  `companion/src/ccsync_companion/proxy_relink.py:1019-1027`
- What: in the forced path, `ok` is False only when EVERY attempt raised. If one
  or two of the three `ReplaceClip` calls raised and the non-raising one did not
  move the geometry, the function answers `{"ok": True, "changed": False,
  "message": "...its geometry did not change"}`, and `apply_relinks` records that
  as a permanent verdict ("not asked again until the file does [change]"). A
  transient Resolve failure is therefore promoted to a settled negative answer.
- Failure scenario: Resolve is mid-render / the script server flaps for the two
  seconds the pass takes. The clip genuinely carries a stand-in's 300 frames over
  a 9,000-frame original. The refresh half-fails, the verdict False is written,
  and because the file's `(mtime, size)` will never change again (the original
  already arrived - that is why the refresh was planned), the clip keeps the
  stand-in's geometry for the life of the process. Phase 3's one mechanism is
  permanently disarmed for that clip, silently.
- Evidence: read of `replace_clip`; `raised` is only compared against
  `max(1, tries)`, and the `if refresh:` return below it does not consult it.
  `apply_relinks` calls `note_geometry_verdict(..., False, ...)` on
  `changed is False` with no regard for whether anything raised.
- Ledger: new (a neighbour opened by comp-resolve-1's fourth condition).
- Suggested fix: in the forced path, when `raised > 0` return
  `{"ok": True, "changed": False, "retryable": True}` (or simply `ok: False`)
  and have `apply_relinks` skip `note_geometry_verdict` unless the pass was
  clean.

### comp-resolve-3 - the `.mp4` refusal is not scoped to the b-roll archive, so a legacy project `.mp4` proxy is silently never attached and nothing is said
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:833-839` (plan side,
  shipped in 0.9.74) and `companion/src/ccsync_companion/resolve_bridge.py:3016-3026`
  + `_real_original_here` at `:2959` (insert side, added today)
- What: both readers refuse a `.mp4` proxy purely on "the file at `local_path`
  exists and is not a ledgered stand-in". Neither asks `_under_archive`, although
  every comment on the rule says "in the b-roll archive that file is the browser
  PREVIEW". Outside the archive a `Proxy/<stem>.mp4` is a perfectly good proxy -
  `proxy_scan.py:59` states the fleet invariant in capitals: "EXISTING `.mp4`
  PROXIES STAY VALID and are not re-made" (`GENERATED_EXT` became `.mov` only at
  R14, 2026-08-19; everything proxied before that is `.mp4` and the generator
  will not redo it).
- Failure scenario: an editor's project clip `P:\Projects\FF5\Media\A001.mov`
  with a pre-R14 `Proxy\A001.mp4` beside it and the original on disk. It plays
  the 6K original for ever; `plan_relinks` emits no op AND no `notes` entry, so
  the RES-3 "why is my proxy not attached" channel, the tray line and the log all
  say nothing at all.
- Evidence: snippet from the companion venv with exactly that clip
  (`proxy_state = "None"`, only the original and the `.mp4` existing):

      ops: []
      notes: []

- Ledger: related to audit F1 / proxy-tiers-1; the scope gap is pre-existing in
  0.9.74 on the plan side and was propagated verbatim to the insert side today.
- Suggested fix: gate both on `_under_archive(file_path, local_root,
  canonical_prefix)` (the insert side can reuse `broll_standins.archive_rel_of`,
  which is filesystem-free and safe under `_API_LOCK`), and when the rule does
  fire on the plan side, append a `notes` entry so the refusal is explainable.

### comp-resolve-4 - the fleet's stand-in hint is treated as conclusive about THIS machine, and it is not the per-machine answer either side's comments describe
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:565-573`
  (`if fleet is True: ... return True`), other end
  `dashboard/src/ccsync_dashboard/api.py:9869-9872` +
  `dashboard/src/ccsync_dashboard/db.py:8868-8886`
- What: `standins_known` is the set of archive rels at which SOME machine placed
  a stand-in. `_geometry_disagrees` reads a hit as proof that the clip in THIS
  machine's pool was born from a stand-in and needs a `ReplaceClip`. On the wired
  rig - the machine the hint was added for - the original was always there and
  the clip was never born from a stand-in, so the hit is a false positive by
  construction. Separately, `db.standins_known(conn)` takes no editor, machine or
  rel filter: it returns the fleet-wide 200 most recently seen rels, while both
  `app.py:2293` ("the archive rels this machine listed") and `api.py:9858` ("the
  machine that needs the answer is already sending the list the answer is about")
  describe a per-machine answer.
- Failure scenario: a remote editor places 150 stand-ins. On its next pass the
  wired rig plans a forced `ReplaceClip` for every one of those clips in its own
  pool - full re-imports of good 6K clips - each of which, per comp-resolve-6's
  own premise, may drop the clip's proxy attachment. It is bounded to one pass
  only by the geometry memory, which is the memory comp-resolve-1 above shows is
  broken on any machine that cannot open the canonical spelling.
- Evidence: read of both ends; `standins_known(conn, limit=200)` has no
  `WHERE editor/machine`, and the companion's `fleet_says_standin` is consulted
  before both probes with `True` short-circuiting to a plan.
- Ledger: proxy-tiers-4 does not fix proxy-tiers-4 for the wired rig it was
  written for.
- Suggested fix: make the hint a reason to run the cheap HEADER estimate rather
  than a conclusion (the estimate is one open and answers "nowhere near"
  correctly for a real original), and filter `standins_known` to the rels the
  requesting report actually listed, or rename the key on both sides to say it is
  fleet-wide and capped.

### comp-resolve-5 - the refresh mutates the project with no save point and no undo journal, and it is not the no-op the docstring claims
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/resolve_bridge.py:2333`
  (`project_name = "" if refresh else ...`) and `:2364` (`if journal and not refresh`)
- What: the `force` docstring justifies dropping the save point and the journal
  entry with "There is nothing to undo: old_path == new_path" and "The bytes on
  disk are not touched either way". comp-resolve-6, added in the same pass, is
  built on the opposite premise: `ReplaceClip` is the API's re-import path and
  may clear the clip's proxy attachment. So the call DOES change the project, and
  CLAUDE.md's invariant ("Every media-pool write goes through
  `resolve_bridge.replace_clip` / `link_proxy_media`, which take a
  `SaveProject`+export save point and write an undo journal") is relaxed for a
  write that is not inert.
- Failure scenario: the refresh drops the proxy and `clip_proxy_state` answers
  `""` (the property read raised, Resolve going away) - `apply_relinks` then
  re-attaches nothing, there is no journal entry naming the inverse edit, and no
  save point to roll the project back to. The editor's clip is on its original
  (or offline on a remote rig) with nothing in `~/.ccsync/resolve_edits`
  recording that the companion did it.
- Evidence: the two code sites plus the comp-resolve-6 comment at
  `proxy_relink.py:1050-1058` that states the drop is real and its own fix is
  "best effort".
- Ledger: new (comp-resolve-1's decision vs comp-resolve-6's premise, same pass).
- Suggested fix: keep the save point for a forced refresh (it is once per burst,
  not per clip) and journal it as a proxy-attachment edit when the re-attach
  fires or when `clip_proxy_state` cannot answer.

### comp-resolve-6 - the `except TypeError` fallback lets an exception escape `apply_relinks`, and masks a real TypeError as a settled verdict
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:1007-1013`
- What: two problems in one four-line construct. (a) The retry inside the
  `except TypeError:` handler is unprotected - an exception raised there is not
  caught by the sibling `except Exception:` (Python does not run sibling handlers
  for an exception raised inside a handler), so it escapes a function whose
  docstring says "Never raises: one clip Resolve refuses must not stop the rest".
  (b) A `TypeError` raised from INSIDE the real `replace_clip` (e.g. from
  `_norm_path` on an odd path) is silently retried WITHOUT `force`, which
  short-circuits to `{"ok": True, "changed": False, "message": "Already linked"}`
  - and `apply_relinks` then records that as a permanent "settled" verdict,
  re-creating the exact bug comp-resolve-1 was written to fix, invisibly.
- Failure scenario: (a) any injected two-argument `replace_fn` that raises aborts
  the whole pass at the first refresh op, losing the proxy relinks of every
  clip behind it.
- Evidence: snippet from the companion venv:

      ESCAPED apply_relinks: RuntimeError Resolve went away mid-refresh

- Ledger: new.
- Suggested fix: detect the signature once (`inspect.signature` or a module
  flag), or wrap the fallback in its own `try/except Exception`, and never let a
  `TypeError` path reach `note_geometry_verdict`.

### comp-resolve-7 - `proxy_state_fn` is only defaulted when `resolve_fn` or `replace_fn` is None, so a caller that injects both loses the comp-resolve-6 re-attach silently
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:960-970`
- What: `if proxy_state_fn is None: proxy_state_fn = resolve_bridge.clip_proxy_state`
  sits INSIDE `if resolve_fn is None or replace_fn is None:`. A caller that
  supplies both (every refresh test in
  `test_bug_hunt_2026_09_18_companion_media.py` except the CR-284D one, and any
  future caller) leaves it None, and the re-attach at `:1059` is skipped by
  `if reattach and proxy_state_fn is not None`. The guard turns a missing default
  into a silent no-op rather than an error.
- Failure scenario: a future caller injects both fns for testability; the
  proxy-restoring half of comp-resolve-6 stops running and no test notices,
  because the tests that would notice are the ones that inject
  `proxy_state_fn` by hand.
- Evidence: read of the block; the two re-attach tests both pass
  `proxy_state_fn` explicitly, so neither covers the default.
- Ledger: new.
- Suggested fix: move the `proxy_state_fn` default out of the conditional import
  block (import `resolve_bridge` lazily for it as the block already does).

### comp-resolve-8 - `standins_known` is sent only when non-empty, contradicting the three-state contract both sides document
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9870-9872` (`if known:`) against
  `dashboard/src/ccsync_dashboard/db.py:8877-8880`, `api.py:9866-9868` and
  `companion/src/ccsync_companion/proxy_relink.py:398-402`
- What: every docstring on this wire says an EMPTY list is sent deliberately "for
  the same reason, so the two shapes cannot be confused", and the companion's
  `_FLEET_KNOWN` tri-state is built on that. The route only sets the key when the
  list is non-empty, so "the dashboard knows of none" and "the dashboard does not
  know" are the same bytes on the wire and `_FLEET_KNOWN` can never be set True
  with an empty set.
- Failure scenario: harmless today (both shapes fall through to the probe), but
  the documented contract and the code disagree, and the next person to make
  `False` mean something - the obvious optimisation, "the fleet says no, skip the
  demux" - will build it on a distinction that is not on the wire.
- Evidence: `if known:` at `api.py:9870`; `note_fleet_standins` returns False and
  leaves `_FLEET_KNOWN` untouched for an absent key.
- Ledger: new (proxy-tiers-4 contract).
- Suggested fix: send `{"rels": []}` unconditionally as the docstrings promise,
  or correct all four comments to say absent is the only "I do not know".

## Coverage note
`fixer.py`, `library.py`, `consolidate.py`, `project_setup.py`, `luts.py`,
`bpg.py`, `proxy_gen.py`, `proxy_history.py`, `proxy_scan.py`,
`resolve_journal.py`, `resolve_undo.py`, `resolve_prefs.py`, `script_server.py`
and `timeline_cards_bridge.py` are unchanged by today's pass and were only read
where a changed path led into them (`proxy_scan.GENERATED_EXT` and the `.mp4`
rule, `resolve_journal.allow_automatic`'s budget, `proxy_gen._build_cmd`'s
container). I did not read them end to end. Nothing here was run against a live
Resolve (rule 1; `scriptapp()` never called, `_no_live_resolve` left in force), so
every claim about what `ReplaceClip` does to an attached proxy rests on the
builders' own comp-resolve-6 premise, not on measurement - comp-resolve-5's
severity depends on that premise being right. The suite does not cover: a clip
whose canonical spelling is not openable (finding 1), a `ReplaceClip` that raises
on some attempts only (finding 2), the `.mp4` rule outside the archive
(finding 3), or the wired rig's reaction to a fleet stand-in hit (finding 4).
The `watcher.py` exemption memo and the `timeline_cards_role._note_answer`
changes I read closely and found sound: the memo has a single caller on a single
thread, a 60 s TTL and a bounded size, and `note`/`error` are emitted by
`cards_tunnel` only on the no-engine paths, so a healthy push cannot be
misread as discarded.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/db.py:8868`: `standins_known` has no per-machine
  filter and a fleet-wide `LIMIT 200`, so in a fleet with more than 200 stand-ins
  the rels a given machine needs may never be in its reply (degradation only).
- `companion/src/ccsync_companion/broll_standins.py:470`: `is_stale` stays True
  for ever once the original has arrived - nothing clears or ages the entry, so
  it is a permanent "yes" to the relink pass's first cheap question.
