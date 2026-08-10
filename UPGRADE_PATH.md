# UPGRADE_PATH: proxies (lane B) from rclone to Syncthing

Status: **PLANNED** (investigation 2026-08-04/05, this plan not yet started)
Owner: alex · Companion baseline at time of writing: 0.4.22

## Decision

Move **lane B (proxies, NAS → editors)** off rclone-SFTP and onto Syncthing by
**merging proxies into lane C's existing per-project folder** via an
ignore-pattern change. **Lane A (originals, editor → NAS) stays on rclone** —
Syncthing cannot express "upload my video, never download anyone else's":
ignore patterns block a file in *both* directions, and there is no per-file or
per-device directionality inside a shared folder. A separate up-only folder is
also impossible for the same reason a separate proxy folder is (next section).

Why the swap is expected to win (structural, not incidental):

- Lane B is batch: one `rclone sync` per project per sequencer turn
  (`project_rotation_seconds`, default 600 s), each pass paying a full remote
  listing over SFTP. Lane C is event-driven (fs-watcher + index deltas) and,
  under the current `maxFolderConcurrency` pacing scheme, effectively
  continuous.
- SFTP has no multi-thread upload and a per-file in-flight window of
  chunk × concurrency (tuned to the protocol max 255 KiB × 64 ≈ 16 MiB,
  `rclone_lane.py`). Syncthing multiplexes many block requests across many
  files on one TLS connection, and the server folders are already tuned for it
  (`maxConcurrentWrites: 32`, `pullerMaxPendingKiB: 65536`).
- rclone-SFTP has no resume — an interrupted transfer restarts from byte 0
  (the whole reason `shutdown_guard.py` exists). Syncthing resumes at block
  level and reuses partial temp files.
- The M3 benchmark never actually measured Syncthing over the network: every
  Syncthing row was loopback-only and marked "not comparable"
  (`bench/README.md`), and no results artifact was committed. Field
  observation (2026-08) is the best data we have, and it favors Syncthing.

Deliberately **rejected** alternatives:

- **A second Syncthing folder for proxies.** Proxies live in per-folder
  `Proxy/` subdirs scattered at every depth — there is no subtree to root a
  folder at. Rooting a second folder at the project dir doesn't work either:
  two folders sharing one root share the single `.stignore` file at that root,
  so they cannot carry complementary patterns.
- **Lane A on Syncthing** (see above). Lane A's archival semantics
  (copy-only, never delete on NAS, skip-if-exists) are also exactly what
  `rclone copy` already does well.
- **`ignoreDelete` on the server folder** to block editor-originated proxy
  deletes. It would change lane C's asset-delete semantics too (SPEC flaw 2
  says lane C deliberately propagates deletes with versioned trash), and
  upstream discourages it (permanent out-of-sync noise). Staggered versioning
  on both sides + BPG regeneration is the chosen safety net instead.

## Target state

| Lane | Content | Direction | Engine after this plan |
|---|---|---|---|
| A: video originals | video outside `Proxy/` | editor → NAS only | rclone (SFTP) — unchanged |
| B: proxies | `**/Proxy/**` | NAS → editors (via sendreceive folder; see semantics) | **Syncthing, merged into lane C's folder** |
| C: everything else | audio, GFX, AE, subs, docs | bidirectional | Syncthing — unchanged |

rclone stays installed on every editor regardless: lane A, structure clone
(`clone_directory_tree`), and consolidate's `--dry-run` reconciliation all use
it.

## The ignore-pattern change

Three builders emit the `.stignore` content and must change **together, in the
same order** (`server/tests/test_cross_component.py` asserts parity of the
shared blocks):

1. `server/common.py` → `build_stignore_lines()` (used by
   `setup_syncthing_folder.py`)
2. `dashboard/src/ccsync_dashboard/provision.py` → `build_stignore_lines()`
   (used by the collector, which **unconditionally repairs every existing
   folder's server-side `.stignore` to this list each provision cycle** —
   `collector.py _ensure_ignores`; this is what makes the server-side rollout
   automatic, and also what makes a hand-edited pilot impossible without a
   gate)
3. `companion/src/ccsync_companion/sync/syncthing_admin.py` →
   `STIGNORE_LINES` (re-asserted per project turn by the sequencer's
   `_reassert_folder_policy`, verified at startup via `missing_ignore_lines`)

New pattern list. **Order is load-bearing** — Syncthing ignores are
first-match-wins, so the in-progress excludes must come before the negations
(a growing `.tmp` inside `Proxy/` stays ignored), and the negations must come
before the extension lines (proxies ARE `.mov`/`.mp4` and would otherwise
match them):

```text
# 1. in-progress sidecars — BEFORE the Proxy negations
(?i)**/*.tmp          ← NEW here; BPG/Resolve write .<name>.tmp while generating
(?i)*.tmp                (previously excluded only in rclone's lane filters,
(?i)**/*.lock             rclone_lane.IN_PROGRESS_EXCLUDE_RULES; the server-side
(?i)*.lock                Syncthing folder will now index Proxy/ and must not
                          index a growing temp file — observed live 2026-08-04)
(?i)**/*.partial      ← existing (KNOWN_BUGS B12)
(?i)*.partial
(?i)**/*.ccsync-tmp   ← existing companion-only pair; ADD to all three builders
(?i)*.ccsync-tmp         for byte-parity (harmless server-side)

# 2. negations — un-ignore Proxy contents BEFORE the extension lines
!(?i)**/Proxy/**
!(?i)Proxy/**         ← both forms, matching the existing three-form convention:
                          the codebase's verified understanding is that **/ misses
                          a root-level Proxy/ (see build_stignore_lines comment)

# 3. video originals stay ignored — unchanged
(?i)*.braw
(?i)*.mov
... one line per VIDEO_EXTENSIONS ...

# REMOVED: (?i)Proxy   (?i)**/Proxy   (?i)**/Proxy/**
```

Notes:

- No `!(?i)Proxy` bare-dir negation is needed: after removing the three dir
  ignores, nothing ignores a directory *named* Proxy — only the files inside
  needed rescuing from the extension lines.
- `(?i)*.tmp` / `*.lock` now also hide non-Proxy `.tmp`/`.lock` files from
  lane C tree-wide. No legitimate project asset uses these extensions; accept.
- **Pilot must empirically verify the negation forms** against the running
  Syncthing versions (server 2.1.x, editor bundles): create
  `Proxy/nested-test.mov` at the project root and `B-roll/Proxy/test.mov`,
  confirm both are offered/pulled, and confirm a `.braw` beside them is not.
  Syncthing's pattern anchoring is subtle enough that this check is cheap
  insurance, not paranoia.

## Behavioral changes to accept (and document for editors)

1. **Proxy deletes flip direction.** Lane B was a down-only mirror: an editor
   deleting a local proxy got it re-downloaded next pass. Merged into a
   sendreceive folder, that delete propagates to the NAS and every editor.
   Safety net: staggered versioning already exists on both sides (server
   1 year, editor 30 days via `FOLDER_VERSIONING`), and BPG regenerates a
   missing proxy on its next watch-folder pass. Add a line to
   `docs/EDITOR_SETUP.md`: *deleting proxies locally deletes them for
   everyone; free disk space by unticking projects instead.*
2. **Editor writes into `Proxy/` now propagate up** (previously impossible).
   An editor running Resolve's local proxy generation into adjacent `Proxy/`
   dirs fans results to the fleet. Arguably a feature; it is new behavior.
3. **`.ccsync-trash` retires for proxies.** Superseded/removed proxies land in
   Syncthing's `.stversions` instead. The SMB share-delete gotcha around
   lane B's trash (docs/GOTCHAS.md) goes away with it. Existing
   `<local_root>/.ccsync-trash` contents are untouched (nothing ever prunes
   them — that stays true).
4. **Scheduling.** Proxies inherit lane C's pacing: continuous, event-driven,
   `maxFolderConcurrency`-serialized. Newest-first delivery (lane B's
   `--order-by` equivalent) comes from setting the folder `order` to
   `newest` (see Phase 1).
5. **Dashboard numbers change meaning.** Lane C completion/needBytes now
   includes proxies: per-editor completion %, EMA speed and ETA cover the
   heavy lane (a win — lane B was status-only), but historical continuity
   breaks on the flip date. Tray lane C counts likewise now include proxy
   traffic, which also means the shutdown guard and keep-awake correctly
   cover proxy pulls.
6. **Conflict copies** (`*.sync-conflict-*`) can now appear inside `Proxy/`
   dirs. Only BPG writes proxies, so this needs two writers racing — rare.
   Resolve won't auto-link them; they're clutter, surfaced by Syncthing's
   normal conflict handling.
7. **Filename encoding gotcha shrinks.** rclone's fullwidth-punctuation
   rewriting (docs/GOTCHAS.md) no longer applies to proxies — Syncthing
   carries names byte-exact.

## Version-skew safety (what makes the rollout benign)

| Server patterns | Editor companion | Result |
|---|---|---|
| old (Proxy ignored) | old | status quo — lane B carries proxies |
| **new** (Proxy indexed) | old | server offers proxies; editor's local `.stignore` still ignores them → editor declines, keeps using lane B. The old companion re-asserts its *own* (old) editor-side patterns each turn, so nothing drifts. **Safe.** |
| old | **new** | editor un-ignores Proxy locally but the server's index has no proxies to offer → editor keeps receiving them via lane B (still enabled in the transition build). Editor-side proxies become *offers* to the server, which ignores them (its stignore governs what it pulls). **Safe**, with one thing to verify in the pilot: the tray/dashboard must not show a phantom "sending N files to the server" from the server-side ignored offers (`syncthing_lane` outgoing-need reads `/rest/db/completion`, which should exclude ignored items — confirm). |
| new | new | target state — proxies via lane C; lane B finds nothing to do |

Because the mixed states are safe, the rollout needs no flag day: server-side
flips per project (gated), editor-side flips per machine (companion upgrade).

**Overlap period (lane B still running + proxies in lane C) — two knowns:**

- Benign double-coverage: Syncthing preserves mtimes, so lane B's
  size+modtime comparison sees synced proxies as up-to-date and skips them.
  Temp files are mutually excluded (`.syncthing.*.tmp` matches lane B's
  `- *.tmp`; `.partial` is in the stignore).
- **One real hazard, fixed in Phase 1:** editor-side `.stversions` lives at
  the folder root (inside the project dir). Syncthing never syncs it, but
  lane B's `rclone sync` sees `.stversions/**/Proxy/*.mov` as local files
  absent on the NAS and would sweep the editor's proxy version history into
  trash every pass. Phase 1 adds `.stversions` excludes to the lane B (and,
  as cheap defense, lane A) filter rules.

## Migration cost (one-time)

- **NAS:** the server Syncthing must hash-index the entire proxy corpus of
  each flipped project (rescan). CPU/IO burst per project — the per-project
  gate doubles as the throttle: flip in batches, watch load. Check disk
  headroom for server-side `.stversions` growth (proxies now get versioned on
  overwrite/delete; BPG overwrites rarely).
- **Editors:** one-time hash of the local proxy mirror per flipped project.
  Bytes are identical to the NAS copies (lane B put them there), so Syncthing
  reconciles by hash with **zero retransfer**. The pilot's first checkpoint is
  confirming exactly that (needBytes ≈ 0 after scan).

---

## Phase 0 — baseline + prerequisites (no code)

1. **Record the "before" numbers**, or the swap can never be judged:
   - Lane B: median MB/s and per-pass wall clock from companion logs
     (`--stats` JSON lines) on at least 2 remote editors; note pass latency
     (time from proxy landing on NAS → editor has it), which is the metric
     editors actually feel.
   - Lane C: dashboard EMA speeds for the same editors, same days.
2. Confirm server Syncthing version (2.1.x) and editor bundle versions —
   the pattern-semantics pilot check depends on what's actually deployed.
3. Confirm NAS free space + `.stversions` policy headroom on the pool.
4. *(Optional, cheap insurance)* one real-network ccbench Syncthing row: the
   runner's own README says the loopback pairing logic only needs real
   addresses swapped in. Do it only if the effort is small; the pilot itself
   produces the decisive numbers.

Exit: baseline table committed to `bench/results/` or this file's appendix.

## Phase 1 — code, behind a per-project gate

Everything lands dark; nothing changes behavior until the gate opens.

**Dashboard (`provision.py`, `collector.py`):**

- `build_stignore_lines(proxy_via_lane_c: bool = False)` — old list when
  False, new list (above) when True.
- Gate: `CCSYNC_PROXY_LANE_C_SLUGS` env var on the dashboard app — a
  comma-separated slug allowlist, `*` = all. Collector passes the per-slug
  verdict everywhere it builds or repairs ignores (`_provision_slug`,
  `_ensure_ignores`). The unconditional-repair loop is then the rollout
  mechanism: adding a slug to the env var flips that folder within one
  provision cycle (≤5 min), removing it flips it back.
- `build_folder_config`: add `"order": "newest"` (Syncthing folder pull
  order — preserves lane B's newest-first delivery; harmless for lane C's
  small files). Mirror in `setup_syncthing_folder.py`'s folder object and
  `FOLDER_PULL_TUNING` parity comment — remember a `--force` PUT resets any
  key absent from the object (the B19 lesson).

**Server scripts (`server/common.py`, `setup_syncthing_folder.py`):**

- Same two-variant builder; `--proxy-via-lane-c` flag on the script. Keep
  byte-parity with the dashboard builder for both variants.

**Companion (target version 0.6.0 — 0.5.x got used by the 2026-08-10 companion unification + tray fixes before this plan started):**

- `syncthing_admin.py`: `STIGNORE_LINES` → the new list (the companion is
  per-machine, not per-project — it flips all its folders at once; the skew
  table shows why that's safe). `missing_ignore_lines` automatically enforces
  the new list; on first start after upgrade, folders latch paused until the
  first turn's re-assert writes the new patterns — existing behavior, no code
  needed, but note it in the release notes (one-turn delay per project).
- `rclone_lane.py`: add `.stversions` excludes (`- /.stversions/**` and
  `- **/.stversions/**`) to `build_filter_rules_down` — ahead of the
  `+ **/Proxy/**` include — and to `build_filter_rules_up` as defense.
  This is the overlap-hazard fix and must ship **in or before** the same
  release that changes `STIGNORE_LINES`.
- **Lane B stays enabled** in this release (belt and braces during overlap).
  No sequencer changes yet.
- Tests: `test_rclone_filters.py` (the `.stversions` rules, against the real
  rclone binary as that suite already does), `syncthing_admin`/sequencer
  tests for the new list, and `test_cross_component.py` extended to assert
  both variants' parity across all three builders.

**Docs:** SPEC.md lane table + a pointer to this file; EDITOR_SETUP delete
semantics; GOTCHAS entries (trash/share-delete, fullwidth names) annotated.

Exit: all tests green; dashboard deployed with the env var **unset** (no
behavior change anywhere); companion 0.6.0 built but not yet published.

## Phase 2 — pilot: one project, one editor

Pick a real but low-stakes project, and a pilot machine that is genuinely
remote (real WAN path — Ruskin's PC is SSH-reachable and scriptable, or the
laptop). The base rig is not eligible (no sync lanes).

1. **Server flip:** set `CCSYNC_PROXY_LANE_C_SLUGS=<pilot-slug>`, redeploy the
   dashboard app. Watch one provision cycle repair the folder's `.stignore`,
   then the NAS rescan index the proxy corpus (folder `globalFiles`/
   `globalBytes` jump in the server GUI). Note rescan duration and NAS load —
   this calibrates Phase 3 batch sizes.
2. **Pattern semantics check** (server-side, before any editor): root-level
   `Proxy/test.mov` + nested `B-roll/Proxy/test.mov` indexed; a sibling
   `.braw` not; a fake growing `.<name>.tmp` inside Proxy not.
3. **Editor flip:** install companion 0.6.0 on the pilot machine only (direct
   install, not the upgrade channel — that would flip the fleet).
4. **Checkpoints, in order:**
   - Reconcile: after the local rescan, folder needBytes ≈ 0 — **no
     retransfer of the existing proxy mirror.** This is the abort tripwire;
     if a re-download storm starts, pause the folder, investigate, roll back.
   - No phantom outgoing: tray/dashboard don't report bogus "sending to
     server" for this or — the old-server-patterns skew case, tested for
     free — any *other* project the pilot editor has ticked.
   - Delivery: generate a proxy via BPG on the base rig → measure NAS→editor
     latency and MB/s; compare against Phase 0's lane B baseline. **This is
     the number the whole plan exists for.**
   - In-progress exclusion: while BPG is mid-generate, the editor must not
     receive the `.tmp`; the finished rename must arrive normally.
   - Resolve behavior: auto-link and `proxy_relink` still resolve the synced
     proxies; a proxy updated server-side while Resolve has it open locally
     retries rather than erroring the folder (Windows open-file locks).
   - Delete semantics: delete one proxy on the editor → confirm propagation,
     recovery from server `.stversions`, and BPG regeneration.
   - Overlap: run a full lane B pass — zero deletions/trash moves, zero
     re-downloads, `.stversions` untouched (the new excludes working).
5. **Soak ≥1 week** with the editor actually cutting. Watch dashboard
   completion, tray states, shutdown-guard behavior overnight.

Rollback (any point): remove the slug from the env var (collector restores
old patterns within a cycle; server stops offering proxies), reinstall
the pre-plan companion (0.5.x) on the pilot machine (its per-turn re-assert restores the old
editor-side patterns). Lane B was never off, so proxy delivery never stopped.

Exit: checkpoint results + before/after speed table appended to this file.

## Phase 3 — fleet rollout

1. **Server side in batches:** add project slugs to
   `CCSYNC_PROXY_LANE_C_SLUGS` in groups sized by the Phase 2 rescan
   measurements (suggest 2–3 projects, then larger). All editors are still on
   the pre-plan 0.5.x → skew row 2 → no visible change for them yet.
2. **Publish companion 0.6.0** via the upgrade channel
   (`build_editor_package.ps1 -Publish -MakeCurrent`). Editors upgrade via
   the tray one-click as usual; each machine flips to lane C proxies as it
   upgrades. Expect the one-turn paused-folder latch per project on first
   start (release notes).
3. When every project is flipped, set the env var to `*`.
4. Monitor for two weeks: dashboard fleet strip, `[ OUT OF DATE ]` stragglers,
   NAS load, `.stversions` growth, and lane B run logs — which should now
   report zero work every pass.

Rollback: per-project (env var) and per-editor (republish the pre-plan 0.5.x as CURRENT —
the upgrade channel's version-difference rule makes rollback a first-class
operation) independently. No step in this phase is destructive.

## Phase 4 — retire lane B + cleanup

Only after the fleet has soaked on 0.6.0:

- **Companion 0.6.x/0.7.0:** sequencer stops invoking lane B (remove the call
  site in `_run_lanes_a_and_b`; lane A's concurrent-thread scaffolding
  simplifies). Do **not** rely on flipping the `lane_b_enabled` default:
  every existing install has a literal `lane_b_enabled = true` written in its
  `config.toml` (DEFAULT_TOML_TEXT), so a default flip reaches nobody — the
  call-site removal is the only mechanism that works. Keep the
  `rclone_lane` down-direction machinery itself: `consolidate.py` uses it for
  dry-run reconciliation.
- Config: mark `lane_b_enabled` as a no-op in `config.example.toml` +
  README (leave the key tolerated so old configs don't warn).
- Make the builders' new patterns the only variant; drop the gate from
  dashboard/server code and the env var from the deployment; collapse
  `test_cross_component.py` back to one list.
- Reporter/dashboard: retire the lane B `LaneStatus` row (or keep it
  reporting `idle/retired` for one release so old dashboards don't render a
  hole — decide when touching the reporter).
- Docs sweep: SPEC lane table + flaw 2 (delete-asymmetry rule now reads:
  originals-up never deletes; *everything else including proxies* propagates
  deletes with versioned trash), GOTCHAS (retire trash/share-delete and
  proxy-name-encoding entries), EDITOR_SETUP, this file → status DONE.
- Structure clone (`_maybe_clone_structure`) **stays**: Proxy dirs now arrive
  via lane C, but dirs whose only content is originals still need it, and
  it's cheap and idempotent.

## Follow-ups unlocked (separate work, not this plan)

- **Peer-assist:** editors sharing a project can exchange proxy blocks with
  each other if their Syncthing devices are introduced to one another
  (today each editor peers only with the server). Directly attacks SPEC
  flaw 6 (every download riding one HiNet upstream). Needs `accept_device.py`
  to cross-share devices + a think about tailnet ACLs.
- **Lane A pain relief** (independent of Syncthing): revisit rclone-SMB
  multi-thread uploads with a real bench row, now that the harness exists and
  lane B no longer competes for the link.
- Real-network Syncthing rows in ccbench so the next engine decision starts
  from committed data.

## Risk register

| Risk | Phase | Mitigation |
|---|---|---|
| Negation patterns behave differently on deployed Syncthing versions | 2 | explicit semantics checkpoint before any editor flips; per-slug gate limits blast radius to one project |
| Re-download storm on editor flip (hash reconcile fails) | 2 | needBytes tripwire immediately after rescan; pause folder + rollback; lane B still running so delivery never stops |
| NAS overload hashing the proxy corpus | 2–3 | per-slug gate = batch throttle; measure in pilot first |
| Editor deletes proxies to free space → fleet-wide delete | 3+ | versioning both sides + BPG regen; EDITOR_SETUP doc line; monitor server `.stversions` |
| lane B trashes `.stversions` during overlap | 2–3 | `.stversions` excludes ship in 0.6.0 with the stignore change |
| Phantom "sending to server" from ignored offers | 2 | explicit pilot checkpoint; skew is otherwise harmless |
| Old companion re-asserts old patterns forever | 3 | by design — that machine simply keeps lane B until it upgrades; fleet strip flags `[ OUT OF DATE ]` |
| Rollback needed after Phase 4 (lane B call site gone) | 4 | upgrade channel makes republishing an older companion a one-command rollback; server gate can resurrect old patterns per-project until Phase 4's builder cleanup lands — sequence Phase 4 last for exactly this reason |

## Appendix — baseline / results

*(fill in during Phase 0 and Phase 2)*

| Metric | rclone lane B (before) | Syncthing lane C (after) |
|---|---|---|
| median MB/s, remote editor | | |
| NAS→editor latency for a fresh proxy | | |
| interrupted-transfer recovery | restart from byte 0 | block-level resume |
