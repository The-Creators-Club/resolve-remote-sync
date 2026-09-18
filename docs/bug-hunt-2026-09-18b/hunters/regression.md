# regression - each of the five ledger sections judged against its finding, plus the twenty-one OWED hand-offs

Files read (with approximate coverage): all five ledgers
(`docs/bug-hunt-2026-09-18/ledger/{highs,companion-core,companion-media,dashboard,webapps-tools}.md`,
100% of the section headings, 100% of `highs.md`, the OWED + Deploy order +
Owner decisions blocks of all five, and the prose of ~35 sections read in
full); the fixes behind the ten highs in
`companion/src/ccsync_companion/sync/rclone_lane.py` (`_follow_server_moves`,
`_trashed_from`, `_is_same_local_path`, `_note_relocated`),
`sync/server_locate.py`, `resolve_bridge.replace_clip` (the whole `force`
path), `proxy_relink.py` (`_openable_path`, `_geometry_key`,
`note_/remembered_geometry_verdict`, `_geometry_disagrees`,
`note_fleet_standins`, `fleet_says_standin`, `apply_relinks`' refresh branch),
`companion/app.py` (`_note_dashboard_version`, `_dashboard_knows_state_word`,
`_apply_file_moves`' answer sites, `standins_owed`, `_note_proxy_attach`),
`companion/sidecar_tools.py` (CR-280 block), `companion/upgrade.py`
(`note_report_response`), `dashboard/app.py` (`_record_off_the_loop`,
`unhandled_error`), `dashboard/api.py` (`ProxyAttachIn`, `StandinsOwedIn`,
`StandinsPlacedIn`, `_upgrade_info`'s withheld paths, the `standins_known`
reply), `dashboard/db.py` (`connect`, `standins_known`),
`broll/web/app/routes_api.py` (`known`), `tools/publish_feed.py`,
`.github/workflows/ci.yml`, `dashboard/notices.py` + `alerts.py`
(`broll_archive_unreadable`), plus the six 18b hunter reports already filed
(comp-ui, dash-core, dash-db, install-onboard, music, res-companion,
ytdl-web) so nothing below repeats them.

Tests run: none (read-only pass; every claim below is traced in source. The
mechanical sweep `for each ledger finding-id: grep -rl <id> over .py/.js/
.ps1/.sh/.yml/.html` was run and found a code citation for every non-test
section, so no section claims a fix that left no code behind).

## Findings

### regression-1 - CR-282D/CR-282E's memory is WRITTEN under a different key than it is READ under, so on any machine whose linked path is not openable in this process the refresh is re-planned every 120 s exactly as before the fix
- Severity: medium
- Confidence: CONFIRMED (the key asymmetry; PLAUSIBLE for how many machines in this fleet are in the affected class)
- Where: `companion/src/ccsync_companion/proxy_relink.py:1025` and `:1091` (`apply_relinks`, `note_geometry_verdict(op["file_path"], ...)`) against `companion/src/ccsync_companion/proxy_relink.py:544` (`_geometry_disagrees`, `probe = _openable_path(file_path, local_root, canonical_prefix, exists)` then `remembered_geometry_verdict(probe, stat_fn, stored)`)
- What: `_geometry_disagrees` keys the verdict cache on `probe` - the spelling that can actually be opened here, which `_openable_path` may take from `_local_twin(path, local_root, canonical_prefix)` rather than from the clip's linked path. `apply_relinks` records the post-refresh verdict on `op["file_path"]`, the LINKED (canonical) path, which `plan_relinks` never translated. `_geometry_key` normalises but does not translate, so the two are different dict keys whenever `local_root != canonical_prefix` and the canonical spelling is not visible to this process - the exact case `_local_twin`'s own docstring exists for ("a service or a remote shell has no P: even though the editor's own Resolve does, and a macOS editor has no P: at all"). `plan_relinks`' own comment at `:848-850` states the intent that was missed: "carried so apply_relinks can remember the verdict under the same key the probe used" - only `stored_frames` was carried, not the probe path.
- Failure scenario: a companion whose `local_root` is `D:\CC Sync` (or a Mac mount) while Resolve's clips are linked under the canonical `P:\`. Pass 1: `_geometry_disagrees` probes via the twin, says True, the op is planned with `refresh: True`; the forced `replace_clip` returns `{"ok": True, "changed": False}` (Resolve took the call, the geometry did not move - the "will not re-read it" case CR-282D's own text names); `note_geometry_verdict("P:\\...")` stores under a key nothing reads, and additionally under a fingerprint of a path that cannot be statted. Pass 2, 120 s later: no remembered verdict under the twin key, so the header estimate and then the full `-count_packets` demux run again, the op is planned again, and one of the 8 `allow_automatic` grants a day is spent again - which is precisely the outcome CR-282D and CR-282E were built to end. It never converges.
- Evidence: read of `_geometry_key` (`:373`, normalises the string, no root translation), `_openable_path` (`:260`, returns `path` OR `_local_twin(path, ...)`), `_geometry_disagrees` (`:543-546`, `probe` used for both `remembered_geometry_verdict` and every `note_geometry_verdict`), `apply_relinks` (`:1025`, `:1091`, both `op["file_path"]`). `companion/tests/test_bug_hunt_2026_09_18_companion.py`'s `test_a_clip_that_agrees_is_probed_once_and_never_again` and `test_proxy_relink_standins.py` both use ONE path and one fake stat throughout (the ledger says so itself), so no test in the suite can distinguish the two keys.
- Ledger: CR-282D/CR-282E do not fully fix comp-resolve-1/comp-resolve-2 (and CR-284R inherits the same gap)
- Suggested fix: carry the probe path on the op (`op["probe_path"] = probe`, beside `stored_frames`, from the same `_geometry_disagrees` call site) and have `apply_relinks` pass it to `note_geometry_verdict`; fall back to `op["file_path"]` when absent.

### regression-2 - CR-283U (CR-280) opens a neighbour: every FROZEN WINDOWS companion now logs, at WARNING, the exact symptom of a macOS-only bug it does not have
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sidecar_tools.py:192-201` (`CA_BUNDLE_CANDIDATES`) and `:243-251` (`ensure_ca_bundle`), called from `companion/src/ccsync_companion/app.py:11228`
- What: `ensure_ca_bundle` returns early only for `not frozen and platform != "darwin"`. A frozen Windows build satisfies `sys.frozen`, so it proceeds - and `CA_BUNDLE_CANDIDATES` holds six POSIX paths and no Windows entry (there is none to hold: CPython on Windows loads the system store through `ssl.enum_certificates`, not a file). So `ca_bundle_path()` returns None and the function logs WARNING "no CA bundle was found on this machine, so HTTPS downloads (yt-dlp, ffmpeg, deno, the upgrade channel) may fail to verify certificates (CR-280)" on every start, on a platform where verification works.
- Failure scenario: 0.9.75 ships; three of the four machines in this fleet (and every Windows customer machine) print that line at every start and after every self-upgrade. The next time someone diagnoses a Windows download failure the log hands them CR-280, which is a macOS bug, and the honest next step ("certifi in the bundle") is wrong for that machine. The line is also indistinguishable in a shipped log from the genuine macOS case.
- Evidence: read of the candidate tuple (no `C:`-shaped or `%SystemRoot%`-shaped entry, no `ssl.enum_certificates` branch) and of the guard; `companion/tests/test_bug_hunt_2026_09_18_companion_core.py:453` pins "no bundle anywhere is a warning not a refusal to start" with `sys.frozen` forced True and the candidates emptied - i.e. the test pins the Windows-shaped path as CORRECT and cannot catch this.
- Ledger: CR-283U does not fully fix CR-280 (new neighbour on Windows)
- Suggested fix: return None before the search on `sys.platform == "win32"` (the store is not a file there), or demote the no-bundle line to INFO on Windows.

### regression-3 - the proxy-tiers-4 hand-off was answered with a FLEET-GLOBAL top-200, not "the rels this machine listed", so the one mechanism that works on a wired rig degrades silently past 200 stand-ins
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9870` (`known = db.standins_known(conn)`) against `dashboard/src/ccsync_dashboard/db.py:8869-8887`, contract in `docs/bug-hunt-2026-09-18/ledger/dashboard.md:1186-1189`
- What: the written contract is "for the rels this machine listed in its own `media_tree`/`local_manifest` the reply carries `standins_known`", bounded to 200. The implementation ignores the reporting machine entirely: `standins_known(conn)` is `SELECT archive_rel ... GROUP BY archive_rel ORDER BY last_seen DESC LIMIT 200` over the whole `broll_standins` table, and the reply is built without reference to `payload.media_tree` or the machine. The bound is therefore applied to the WRONG set.
- Failure scenario: a fleet where remote editors have placed more than 200 stand-ins (one editor's evening of Send-to-Resolve reaches that easily). The wired rig's own clips are not in the top 200 by `last_seen`, `fleet_says_standin` answers False, and `_geometry_disagrees` falls through to the header estimate and then the full `-count_packets` demux for every one of them - the CR-282E cost this feature exists to remove - with no log line anywhere saying the hint was truncated. It also puts up to 200 other editors' archive rels on every machine's report reply every 30 s, which the per-machine intersection would not.
- Evidence: read of both sides; `fleet_says_standin` (`proxy_relink.py:476`) is correctly non-conclusive on False, which is what keeps this from being a correctness bug rather than a performance one.
- Ledger: CR-285AN answers proxy-tiers-4 with something other than what the contract in the same file asks for
- Suggested fix: intersect with the rels the payload just reported (`media_tree`/`local_manifest`) before the LIMIT, or at minimum log once when the row count exceeds the limit so the degradation is visible.

### regression-4 - `apply_relinks`' `except TypeError` fallback silently reverts to the UNFIXED call and then records a permanent "this clip agrees" verdict
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:1008-1011`
- What: the forced call is `replace_fn(media_pool_item, op["file_path"], force=True)` wrapped in `except TypeError: replace_fn(media_pool_item, op["file_path"])`. The `except` cannot tell a signature mismatch from a `TypeError` raised INSIDE `replace_clip` (e.g. `_norm_path(new_path)` on a non-str). When it fires, the un-forced call short-circuits with `{"ok": True, "message": "Already linked", "changed": False}` - the exact defect CR-282D is about - and the code then reads `changed is False` and calls `note_geometry_verdict(..., False, ...)`, which records the clip as agreeing until its bytes change. The fix's own failure mode is thus converted into a persistent "nothing to do".
- Failure scenario: any injected two-argument `replace_fn` (the docstring names "older tests, any other caller of this module") or any internal `TypeError` makes the refresh a silent no-op that is never retried, with `ok: True` reported upward.
- Evidence: read of `replace_clip:2324-2326` (the short-circuit returns `changed: False`) and of the two branches at `:1019` / `:1033`.
- Ledger: CR-282D neighbour
- Suggested fix: probe the signature once (`inspect.signature` or a module-level flag) instead of catching `TypeError` around the call, and never record a verdict from the un-forced answer.

### regression-5 - one of the twenty-one OWED hand-offs was not discharged, and it is the one CR-283U's own text names as the next move
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/requirements.lock`, `companion/build.spec`, `tools/release_macos.sh`, `tools/check_licenses.py` (owed at `docs/bug-hunt-2026-09-18/ledger/companion-core.md:480`)
- What: the hand-off asked webapps-tools to add `certifi` to the companion lock and the macOS build so the frozen Mac bundle carries its own CA bundle. `grep -i certifi` over `companion/requirements.lock`, `companion/requirements.txt`, `companion/pyproject.toml` and `companion/build.spec` finds nothing; `webapps-tools.md`'s OWED section does not list it as taken or declined either way. So CR-280's fix on the one platform it affects rests entirely on `/etc/ssl/cert.pem` existing on leso's Mac, which nobody here can test.
- Failure scenario: 0.9.75 ships, leso's Mac still fails `CERTIFICATE_VERIFY_FAILED`, and the ledger's summary line ("CR-280 is fixed in repo but cannot be VERIFIED") is the only record that the planned second half was never built. The 18b hunt is the last chance to catch it before the release.
- Evidence: the greps above; `KNOWN_BUGS.md:24398` still carries CR-280 as OPEN and `:25270` still carries the owed line, so the ledger is honest - the work simply did not happen.
- Ledger: OWED hand-off (companion-core -> webapps-tools) not discharged; CR-280 stays OPEN
- Suggested fix: either add `certifi` to the lock and the two build scripts (and `check_licenses.py`'s inputs - certifi is MPL-2.0 plus the Mozilla CA file, so the gate must be told), or record the decision not to and say so beside CR-280.

### regression-6 - the `upgrade_none_reason` hand-off was answered with two different vocabularies on one key: four short codes on one path and a human sentence on the other
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9650` (`result["upgrade_none_reason"] = withheld[0]`) and `:9732` (`result.setdefault("upgrade_none_reason", "the update you were sent cannot be installed on this computer")`)
- What: the hand-off asked for "a short string: `retracted` / `needs_newer_dashboard` / `arch_mismatch` / `unknown_platform`". One writer sends a code from `withheld`; the other sends an English sentence. The companion (`upgrade.py:1563`) only tests truthiness today, so nothing breaks - but the first surface that renders or switches on this key (the tray line and the Packages page are both named in CR-285Q as the intended readers) will meet a value it cannot map, and a sentence in a report reply is also a user-visible string that no em-dash / wording scan covers.
- Failure scenario: a later build adds `REASON_TEXT = {"retracted": ...}` in the tray, and the machine with a pushed-but-unofferable update renders a blank or a raw internal sentence.
- Evidence: read of both writers and of the single companion reader.
- Ledger: CR-283F/CR-285Q answer comp-app-3 with a wider contract than the hand-off specified
- Suggested fix: send a code (`push_not_offerable`) at `:9732` and keep the sentence, if one is wanted, in a separate key.

## Coverage note

Judged in full: all ten highs (CR-282A..J) and the OWED/deploy-order/owner-decision
blocks of all five ledgers. Sampled rather than judged: the ~120 medium and low
sections of CR-283/284/285/286 - I read every heading and the prose of the ones
whose fix crossed two files or two processes, and relied on the mechanical
citation sweep for the rest. Not reached: CR-286's install/uninstall sections
(install-onboard's 18b report covers eight of them from the other end), the
Cards pool sections CR-285A..E, and the whole webapps-tools indexer half. The
suites cannot cover regression-1 (every relevant test uses one path spelling
throughout, by the ledger's own admission), regression-2 (the test forces the
no-bundle branch and asserts it is correct) or regression-3 (no test asserts
the reply is scoped to the reporting machine).

Already reported by a territory hunter, cited not re-reported: the
`standins_known` empty-list-never-sent gap (res-companion-5), the double
record of an unhandled error under a mount (dash-core-1), res-fleet-4's
offer-only half (dash-db-1), CR-286K not fixing ytdl-web-3 (ytdl-web-1),
CR-283O freeing neither the window nor the class (comp-ui-3).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:9420`: the `standins_placed` guard is written as one physically long line with run-together whitespace (`... else None` padded to column 80+), unlike every neighbour - cosmetic, but it is the shape a bad merge leaves.
- `companion/src/ccsync_companion/resolve_bridge.py:2380`: a forced refresh where the first `ReplaceClip` raises and a later one does not take returns `ok: True, changed: False` ("asked, nothing changed") although one attempt was a scripting error; only `raised == tries` is treated as Resolve going away.
