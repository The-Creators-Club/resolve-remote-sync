# dash-release-jobs — release trust / feed / self-update / job scheduler / cards mount

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/ed25519.py` (100%), `release_trust.py` (100%),
  `package_store.py` (100%), `release_feed.py` (100%), `jobs.py` (100%),
  `cards.py` (100%), `cards_wsgi.py` (100%), `cards_tunnel.py` (100%),
  `cards_exec.py` (100%), `android.py` (100%), `cards_ai.py` (~40%, the runner
  seam + the file/session helpers), `dashboard_update.py` (~75%: preflight,
  extract/verify, backups, prune, apply/rollback, status, feed health; NOT the
  stage-verify subprocess source or the boot-health probe).
- Cross-checked: `companion/src/ccsync_companion/ed25519.py` and
  `release_pubkey.py` (the two duplicated copies), `db.set_current_package`,
  `db._job_lease_until`, `api._upgrade_info` / `make_current_refusal`,
  `settings.py` pubkey parsing, `templates/partials/admin_dashboard_update.html`.
- Tests read: `test_release_feed.py`, `test_packages.py` (signature/min_version
  blocks), `test_release_channel.py` (REL-1/3/4/16 blocks), `test_jobs_ranking.py`,
  `test_jobs_backpressure.py`, `test_cards_mount.py`, `test_dashboard_update.py`
  (status block).

Tests run:
`dashboard/.venv/Scripts/python.exe -m pytest tests/test_jobs.py tests/test_jobs_ranking.py tests/test_jobs_scheduling.py tests/test_jobs_backpressure.py tests/test_jobs_cancel.py tests/test_jobs_pinning.py tests/test_jobs_contract.py tests/test_release_feed.py tests/test_packages.py tests/test_cards_mount.py tests/test_cards_tunnel.py tests/test_dashboard_update.py tests/test_android.py -q`
-> **431 passed, 1 skipped** (baseline green; none of the findings below is
caught by the suite).

Verified crypto (no finding): `ed25519.verify` matches RFC 8032 §6's reference
verifier byte for byte -- canonical `y < p` decompression, `s < q` malleability
check, cofactorless `[s]B = R + [h]A`, every malformed input -> `False`, never
raises. The dashboard and companion copies are byte-identical (6002 bytes each,
compared directly). `record_fields` / `canonical_record` / `OPTIONAL_KIND_EXTRA_FIELDS`
agree line for line with `companion/.../release_pubkey.py`. `DASH_RELEASE_PUBKEYS`
parsing (comma-or-whitespace, `_looks_like_ed25519_pubkey` filter) is sound.
Two-digit minors are handled correctly everywhere I checked
(`release_trust._version_tuple`, `release_feed._version_sort_key`,
`dashboard_update.version_tuple`, `db.version_tuple`) -- all numeric-per-part.
No em dash in any user-visible string in the twelve territory files (scanned).

## Findings

### dash-release-jobs-1 — the Timeline Cards engine is started and then leaked when the WSGI wrap fails
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards.py:376-400` (`mount_cards`: the
  `a2wsgi` wrap block calls `stop_engine(app)`), against `cards.py:341-355`
  (`stop_engine` reads `app.state.cards_engine`) and `cards.py:363`
  (`app.state.cards_engine = None` at the top of `mount_cards`).
- What: `mount_cards` sets `app.state.cards_engine = None` first, builds the
  engine and calls `engine.start()` (which spawns the library sweep, the ffmpeg
  worker and the translation/search threads), and only assigns
  `app.state.cards_engine = engine` AFTER the `a2wsgi` wrap succeeds. The
  wrap-failure branch's recovery is `stop_engine(app)` -- which reads
  `app.state.cards_engine`, finds `None`, and returns without touching the
  engine it was meant to stop. The started engine is unreachable and its
  threads run for the life of the container.
- Failure scenario: `a2wsgi` missing from the image (an ImportError inside the
  `try`), or `handler_mod.make_handler(engine)` raising on a checkout the
  dashboard is a version ahead of. The mount reports `absent` and the page is
  gone, but the engine keeps sweeping the vault and keeps its single ffmpeg
  worker alive against a project nothing is serving -- with `app.state.cards_engine`
  `None`, so `jobs.can_pin` says there is no executor, the health line says
  `absent`, and nothing an admin can see says threads are running. It also
  survives a dev reload, which is exactly what `stop_engine`'s docstring says it
  exists to prevent ("what stops a SWEEP from running against a database the
  next process is opening").
- Evidence: reproduced from the dashboard venv with a stub checkout and
  `cards_wsgi.handler_wsgi` forced to raise:
  ```
  the Timeline Cards handler did not wrap (RuntimeError: boom)
  absent the WSGI shim did not build (RuntimeError: boom)
  engine started: True engine stopped: False
  ```
  `test_cards_mount.py` has no test for the wrap-failure path.
- Ledger: new
- Suggested fix: in that except branch call `engine.stop()` directly (or set
  `app.state.cards_engine = engine` immediately after `engine.start()` so the
  existing `stop_engine(app)` can find it), guarded by try/except as
  `stop_engine` already is.

### dash-release-jobs-2 — the feed's `current` policy makes a build current through a door that skips the `requires_dashboard` (REL-4/SYS-13) gate
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:678-687` (`_apply_policy`,
  the `existing is not None` branch), against
  `package_store.py:170-184` (the gate, and its comment claiming this cannot
  happen) and `db.py` `set_current_package` (checks retraction only).
- What: `package_store.store_verified_package`'s comment states the REL-4
  ordering check lives there "so the human PUT and the feed's `current` policy
  cannot disagree". But `_apply_policy` only goes through `package_store` for a
  build it has to DOWNLOAD. For a version already published on this dashboard it
  calls `db.set_current_package(conn, platform, version, kind)` directly, and
  that function checks only `retracted_at` -- not `requires_dashboard`, and not
  the REL-1 soak gate (`api.make_current_refusal`) either. So the feed is a third
  door that both of the other two doors' gates do not cover.
- Failure scenario: an admin stages companion 0.9.70 by hand (`make_current=0`
  is allowed and returns 200 -- `test_a_build_needing_a_newer_dashboard_cannot_be_made_current`
  pins only the `/current` route), the record carries `requires_dashboard =
  0.8.0` and this dashboard is 0.7.27. The channel's `current` pointer names
  0.9.70 and the policy is `current`. The next daily poll flips
  `is_current = 1` for a build this dashboard is forbidden to advertise.
  `api._upgrade_info` then correctly refuses to offer it, so the whole fleet
  silently stops upgrading while the Packages page shows 0.9.70 as CURRENT --
  the exact "an admin cannot tell an ordering violation from a quiet fleet"
  shape REL-4 was written for, with the arrow reversed.
- Evidence: code read. `grep -n blocks_on_dashboard_version *.py` finds it in
  `api.py` (3 sites) and `package_store.py` only -- never on the
  `db.set_current_package` path `_apply_policy` uses. `db.set_current_package`'s
  own docstring lists retraction as the one check "in the one writer".
  No test in `test_release_feed.py` or `test_release_channel.py` covers a feed
  `current` policy re-pointing at an already-published `requires_dashboard`
  build (`grep requires_dashboard test_release_feed.py` -> nothing).
- Ledger: related to REL-4/SYS-13 (recorded as FIXED); this is the hole the fix
  left on the third door.
- Suggested fix: put the `blocks_on_dashboard_version` (and, arguably, the
  retraction + soak) check inside `db.set_current_package`'s callers' shared
  gate, or have `_apply_policy` call `api.make_current_refusal` / a
  `package_store.make_current` helper instead of `db.set_current_package`.

### dash-release-jobs-3 — under the `current` policy, a build that needs a newer dashboard is re-downloaded in full on every feed check, for ever, and is never staged
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:688-700` (`_apply_policy`
  -> `publish_from_feed(..., make_current=(policy == "current"))`) and
  `package_store.py:176-184`.
- What: `publish_from_feed` streams the whole artefact to a `.part` file
  (`fetch_artifact_to`, up to `ARTIFACT_MAX_BYTES = 200 MiB`) and only then hands
  it to `store_verified_package`, whose `make_current and
  blocks_on_dashboard_version(...)` branch unlinks the part and raises 409 with
  "Nothing was published." `_apply_policy` catches `PackageStoreError`, logs and
  continues -- so no row is inserted, and the next scheduled check (default
  daily) repeats the download and the refusal. This also contradicts
  `store_verified_package`'s own comment two lines above the refusal: "may be
  PUBLISHED here -- an admin who is about to update the dashboard should be
  able to stage it".
- Failure scenario: the vendor publishes companion 0.9.70 with
  `requires_dashboard = 0.8.0` while a customer's dashboard is 0.7.27 and the
  policy is `current`. Every day, for as long as the dashboard is behind, the
  container downloads ~60-100 MB of companion exe (per platform), writes it to
  `/data`, hashes it, and throws it away -- and the build is never staged, so
  the moment the admin updates the dashboard there is still nothing on the shelf.
- Evidence: code read; `_apply_policy`'s `except package_store.PackageStoreError:
  ... continue` and the unconditional `db.get_package(...) is None` re-entry are
  both explicit. Not covered by any test.
- Ledger: new (the other half of REL-4/SYS-13's landing)
- Suggested fix: in `_apply_policy`, if `blocks_on_dashboard_version(kind,
  record.get("requires_dashboard"))` is true, publish with `make_current=False`
  (staging it, as the comment intends) and log why it was not made current --
  rather than downloading it only to refuse it.

### dash-release-jobs-4 — `/cards/api/restart` is blocked by exact string match only
- Severity: low
- Confidence: PLAUSIBLE (the upstream checkout is not on this machine, so I
  could not read how `handler.py` dispatches `/api/restart/`)
- Where: `dashboard/src/ccsync_dashboard/cards.py:76` (`BLOCKED_PATHS =
  frozenset({"/api/restart"})`) and `cards.py:296-303` (`CardsGate.__call__`,
  `if path in BLOCKED_PATHS`).
- What: the gate compares `sub_paths(scope)` for exact membership. A request to
  `/cards/api/restart/` (trailing slash) yields candidates
  `/cards/api/restart/` and `/api/restart/`, neither of which is in the set, so
  it passes through to the handler. Query strings are safe (`scope["path"]`
  carries none) and the second lock (`_NoServer.shutdown()` refusing) still
  holds, so this is defence-in-depth that is one layer thinner than the module
  docstring claims ("It is refused by the gate ... and `self.server` is an
  object whose `shutdown()` refuses as well").
- Failure scenario: an upstream `handler.py` that normalises a trailing slash
  before dispatch reaches `restart_server`, which then calls
  `self.server.shutdown()` -- refused, logged as an error, page not restarted.
  Harmless today, and a straight hit if a future checkout ever calls
  `os._exit` directly rather than through `self.server`.
- Evidence: `test_cards_mount.py:409` tests only the exact path. `sub_paths` does
  no normalisation.
- Ledger: new
- Suggested fix: normalise (`path.rstrip("/") or "/"`) before the membership
  test, or match on `startswith` for the blocked prefixes.

### dash-release-jobs-5 — release_feed's redirect walk never closes the 3xx `HTTPError` responses
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:212-217`
  (`_open_following_https_redirects`, the `except HTTPError` branch).
- What: `_NoRedirect` turns each 3xx into an `HTTPError`, which IS an open
  response object holding a socket. The branch reads its headers and `continue`s
  without calling `exc.close()`. The non-raising 3xx branch six lines below does
  close its response ("Belt and braces"), so the two halves of the same walk
  disagree.
- Failure scenario: every feed check and every artefact download leaks one
  socket per redirect hop (GitHub Releases is always exactly one) until the GC
  runs. On a daily poller this is invisible; on `cli_tools.py`'s
  `open_https_stream` (the second caller of the same function) a chain of hops
  in a tight loop would hold file descriptors longer than it should.
- Evidence: code read; contrast lines 226-233 which explicitly close.
- Ledger: new
- Suggested fix: `try: exc.close() except Exception: pass` before `continue`,
  or wrap the `HTTPError` in a `with contextlib.closing(...)`.

### dash-release-jobs-6 — `jobs.job_age_seconds`'s docstring contradicts its own code (documentation of a safety direction)
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/jobs.py:585-597`.
- What: the docstring says "0 when either timestamp is unreadable -- which makes
  the grace period expire IMMEDIATELY rather than never". The code returns
  `RANK_GRACE_SECONDS`. The CODE is right (`first_refusal` tests
  `>= RANK_GRACE_SECONDS`, so returning the grace value expires the window at
  once, and returning 0 would make it never expire); the docstring is the wrong
  way round. Worth flagging because this is precisely the "a preference that can
  starve a queue looks exactly like a fleet with nothing to do" invariant, and
  the next person to "fix the code to match the comment" would reintroduce the
  stall it guards against. Related, smaller: `SIGNAL_WORDS["near_media"]` reads
  "the base rig or the dashboard host" but `_signal_true` only tests
  `facts["mode"] == "base"`.
- Failure scenario: a maintainer trusting the docstring changes the return to
  `0.0`; a job whose `created_at` is unparseable then waits for its preferred
  machine for ever and is never offered to the rest of the fleet.
- Evidence: `jobs.py:596` `return RANK_GRACE_SECONDS` vs the docstring at line
  587; `jobs.py:609` `if job_age_seconds(job, now) >= RANK_GRACE_SECONDS`.
  No test covers an unreadable `created_at` (`grep job_age_seconds tests/` ->
  nothing).
- Ledger: new
- Suggested fix: correct the docstring (and the `near_media` wording) rather
  than the code.

## Coverage note

Not reached: `dashboard_update.py`'s stage-verify subprocess source
(`_STAGE_VERIFY_SOURCE`) and the boot-health probe / `boot_attempts.json`
watchdog half, and its interaction with `deploy/select_code_root.py` (out of
territory, but it is the copy that ACTS at boot -- the two `parse_version`
implementations should be diffed by somebody). `cards_ai.py`'s CLI/SDK branches
were read for path-safety and secret handling only, not for provider-selection
correctness (`ai_providers` is another territory). `jobs.py`'s cancel is
`api.py`/`db.py` (out of territory) -- I only confirmed `cards_exec`'s
`should_stop` half of the third act.

What the suite does not cover, all confirmed by grep: the feed's `current`
policy interacting with `requires_dashboard` at all (findings 2 and 3); the
`mount_cards` wrap-failure path (finding 1); an unreadable `job.created_at`
(finding 6); a redirect chain longer than one hop.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/db.py` `set_current_package`: it advertises
  itself as "the one writer" with the retraction check in it, but three other
  invariants (`requires_dashboard`, the REL-1 soak gate, `arch`) live only in
  `api.py`/`package_store.py` -- so any caller that is not one of those two
  routes bypasses them (finding 2 is one such caller).
- `dashboard/src/ccsync_dashboard/api.py:5205` region: the human PUT route
  passes `signed_binary` as a FastAPI `int` query param, which is correct, but
  `arch`/`requires_dashboard` are `.strip()`ed by `package_store` AFTER the
  signer signed the raw value -- a record signed with a padded value fails
  closed, which is safe but would read as "signature rejected" rather than
  "your signer emitted whitespace".
