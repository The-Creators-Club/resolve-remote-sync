## The dashboard core: the wizard, the login throttle, the sidecar env pair, /help (CR-257, 2026-09-11)

Eight findings from the 2026-09-11b hunt of that morning's fix pass. Six of
them are the other half of a fix that landed once: a warn that outlived the
condition it described, a clamp applied after the overflow it was meant to
prevent, a pair written independently and read atomically, a COPY that
hard-fails on a document the policy calls best effort, a login-gate carve-out
that outlived its route, and a regression test that asserted a constant.

### CR-257a (dash-core-1) - a `warn` on the EULA task was sticky, so the licence was never accepted once it arrived - FIXED (dashboard/src/ccsync_dashboard/setup_engine.py)

dash-core-6 (CR-248) made a stored `warn` on the `eula` task stop gating the
wizard, because a REQUIRED task whose only reachable end state is `warn` is a
wall with no button that clears it. But the carve-out read the ROW, and
nothing re-runs a task's check on its own: `setup.js` only POSTs
`/api/v1/setup/tasks/eula/check` when an admin presses CHECK on that one row.
So the warn was a latch. An appliance that booted on a build whose
`docs/legal` did not land wrote `warn` once and stayed satisfied for ever -
including after the next OTA bundle carried `docs/legal/EULA.md`.
`outstanding_required` did not list it, `outstanding_for_done` did not list
it, the Setup badge was clear, the wizard's `done` task passed, the
post-login steer to `/setup` stopped, and no human had ever accepted the
licence agreement on that customer's server. The amber line was stale too: it
still said no licence is included in this build, which was no longer true.
That is exactly the state the other half of the same fix (`eula_path()`,
which re-resolves so a late bundle IS seen) exists to make recoverable, with
the gate that would have sent the admin back already switched off.

`WARN_SATISFIES_IDS` is now derived from `WARN_SATISFIES`, a map of id ->
predicate, and `eula`'s predicate is `not eula_path().is_file()`:
`_gate_satisfied` asks the world, never the row. One `is_file()` per render of
the nav badge. The row stays the display; it stops being the authority for a
condition that is a property of the filesystem.

### CR-257b (dash-core-2) - the "other direction" regression test asserted a constant and could never fail - FIXED (dashboard/tests/test_bug_hunt_2026_09_11_dash_db_core.py)

`test_a_required_task_that_is_merely_warn_still_gates` claimed to prove that
only `eula` is exempt and that a required task warning for a reason an admin
can act on keeps the badge lit. Its entire body was `assert
setup_engine.WARN_SATISFIES_IDS == frozenset({"eula"})` - a literal one line
above itself in the source. It built no state, called neither
`_gate_satisfied` nor `outstanding_required`, and would have stayed green
through a change that dropped the id test inside `_gate_satisfied` and
widened the carve-out to every warn. Nothing else in the suite covers a
non-`eula` required task in `warn`, and `_check_syncthing` can put one there
(reachable but reporting no device id) for a reason an admin CAN act on. The
test now puts a real required task into `warn` and asserts it is in BOTH
`outstanding_required` and `outstanding_for_done`, i.e. it drives the
predicate instead of reading the constant the predicate reads.

### CR-257c (dash-core-3) - the login backoff raised OverflowError once a key passed ~1024 recorded failures - FIXED (dashboard/src/ccsync_dashboard/sessions.py)

`record_failure` computed `min(LOGIN_BACKOFF_BASE_SECONDS * (2 ** (failures -
limit)), LOGIN_BACKOFF_MAX_SECONDS)`. The exponent is an unbounded Python int
and the base is a float, so the multiply ran before `min` clamped anything:
past 1024 over the limit, `float * int` raises `OverflowError`. That is not
an `sqlite3.OperationalError`, so `SessionStore._run` did not catch it and it
escaped `auth.record_login_failure` into the login route. `failures` only
grows on attempts made while the key is NOT blocked and the block caps at
3600 s while the failure window is also 3600 s, so a patient attacker
retrying once an hour increments the counter for ever; after about six weeks
against one username - or one gateway IP, whose budget every editor behind
Tailscale Serve shares - the throttle for that key is replaced by a 500 on
every further failed sign-in. The exponent is clamped before the multiply
(`2 ** min(failures - limit, 16)`, already far past the hour ceiling) and the
product clamped as before.

### CR-257d (dash-core-4) - `APP_UID` without `APP_GID` was written to internal.env and ignored by the reader - FIXED (dashboard/src/ccsync_dashboard/secrets_boot.py, internal_sftp.py)

`_write_sidecar_env_files` emitted the two lines independently (`if app_uid:`
/ `if app_gid:`), so a compose file or an OTA-updated stack that set only one
produced an `internal.env` with half a pair. The dashboard's own reader,
`internal_sftp._uid_gid`, takes the pair or neither and otherwise falls back
to `os.getuid()`/`os.getgid()` with nothing logged, because the warning there
only fires on values that are present but non-integer. So the sftp sidecar
started with `APP_UID` from the file while `GET /internal/sftp/users`
answered with the container's own ids: files the sidecar writes into `/tree`
land owned by one pair and the dashboard and Syncthing expect another, which
is SPEC 3.1's whole reason for the variable. The symptom is a permission
failure on an editor's lane days later with nothing in either log pointing at
it. The writer now treats the pair as atomic - both or neither - and WARNs
when it is half configured; the reader WARNs on the same shape instead of
silently downgrading.

### CR-257e (dash-core-5) - the /help index re-walked and re-opened the whole docs tree on every admin render - FIXED (dashboard/src/ccsync_dashboard/help.py)

`document_groups` did an `rglob("*.md")` over the docs root and then, per
entry, a `resolve_document` (`Path.resolve()` + `is_file()`) and a `_title_of`
(open plus up to 60 readlines), with no cache and no mtime check. On a dev
checkout or the base rig that is 185 documents: roughly 370 filesystem calls
and 185 file opens per `/help` render, repeated on every internal link click,
on the single-worker container's threadpool competing with the collector for
the same disk. The audience gate added that morning filters the list but does
not reduce the work for an admin. The index is now cached per (root,
audience), keyed on the root's own mtime with a 30 s ceiling as well, because
a write inside a subfolder does not touch the root's mtime; copies go in and
out so a caller that mutates an entry cannot poison the next render, and
`help.invalidate_index()` drops it. A customer's image is 7 entries, so this
was a base-rig cost, but it is the page an admin clicks through.

### CR-257f (dash-mounts-ui-b-4) - the image build hard-failed on a document `published_docs.py` calls best effort - FIXED (dashboard/src/ccsync_dashboard/published_docs.py, dashboard/deploy/Dockerfile)

`published_docs.py` states the policy: `HOW_IT_WORKS.md` and the `legal` tree
are REQUIRED, and "everything else on the list is best effort, because a
missing document is not a reason to refuse to ship a dashboard". The
Dockerfile named `docs/EDITOR_SETUP.md` in a COPY, and a COPY that names a
missing file fails the BUILD - which is why the line it replaced was a glob.
So the three shipping routes disagreed about how bad its absence is: rename
the file on a branch and the OTA bundler and the bind-mode deploy ship
happily while the image build dies with a bare `COPY failed` and no mention
of the doc policy. `EDITOR_SETUP.md` is promoted to `REQUIRED_DOCS` - one
decision, written down - so the bundler refuses it by name in the same
sentence it refuses a missing guide with, and the rule is now testable: every
document the Dockerfile names by hand must be in the required set.

### CR-257g (music-6) - `editor:` stamps were rejected for any editor name with a space - FIXED (music/web/musicweb/fleet_auth.py)

The dashboard's MusicGate stamps `editor:{editor}` with the account name it
decoded. `musicweb`'s parser was `^(shared|editor:[^\s]{1,64})$`, so a name
containing whitespace (or over 64 characters) yielded `(None, None)` and fell
through to the SHARED token comparison, which a per-editor `cce1.` token can
never satisfy: such an editor lost music fleet ingest entirely and was
answered 403 "missing or invalid X-CCSync-Token", naming the wrong
credential. b-roll and ytdl accept the same name. The parser is now b-roll's -
prefix plus a non-empty remainder - and a stamp with the prefix and no name
is logged. The stamp never becomes WHO the caller is on its own
(`require_fleet_caller` compares it against the signed identity), so its
shape is not a security boundary; three mounts disagreeing about it is.

### CR-257h (security-2) - the login-gate carve-out for `GET /broll/api/fleet/ingest/batches` outlived the route it was written for - FIXED (dashboard/src/ccsync_dashboard/app.py)

broll-3 (CR-245) deleted the b-roll discovery route because nothing called
it; the other half of that wire, `_broll_fleet_list_re` in `login_gate`, was
left behind. Today that is only dead code - the request skips the session
gate, reaches BrollGate and 404s - but the carve-out names a COLLECTION path
with no route behind it, so any GET route added there later is
unauthenticated by inheritance and nothing in that diff would say so. The
regex and its `or (...)` clause are gone, with a comment saying that if
discovery comes back, the route and the carve-out land in the same commit.

### Verification
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_a_stored_eula_warn_stops_gating_only_while_the_licence_is_missing -> fails at f1eeb42 ("eula" absent from outstanding_required), passes now
- dashboard/tests/test_bug_hunt_2026_09_11_dash_db_core.py::test_a_required_task_that_is_merely_warn_still_gates -> the old body could not fail; the new one fails against a `_gate_satisfied` that drops its id test (checked by hand) and passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_the_login_backoff_survives_a_thousand_recorded_failures -> fails at f1eeb42 (OverflowError), passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_a_half_set_uid_pair_is_not_written_to_internal_env -> fails at f1eeb42 (APP_UID alone written), passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_a_half_set_uid_pair_is_logged_by_the_reader -> fails at f1eeb42 (no warning), passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_the_help_index_is_not_re_walked_on_every_render -> fails at f1eeb42 (two walks for two renders), passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_the_image_only_hard_copies_documents_the_policy_calls_required -> fails at f1eeb42 (EDITOR_SETUP.md copied but optional), passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_the_broll_fleet_batch_list_has_no_login_gate_carve_out -> fails at f1eeb42 (404, i.e. admitted past the gate), passes now
- music/web/tests/test_bug_hunt_2026_09_11b_music.py::test_a_stamp_the_mount_can_produce_is_parsed (the music territory's own test, written for music-6) -> passes with this fix; test_an_unparseable_stamp_is_still_not_a_credential passes too

Also run, unchanged: dashboard tests test_help_page.py, test_internal_sftp.py,
test_sessions.py, test_setup_engine.py, test_setup_api.py, test_setup_routes.py,
test_secrets_boot.py (260 passed). The one red in
test_bug_hunt_2026_09_11_dash_mounts_ui.py
(`test_a_refused_tree_is_not_counted_as_a_failed_boot`, a TypeError on a lambda
arity) is another territory's in-flight edit, not this one's.

### OWED TO ANOTHER TERRITORY
- server-tools: `server/install_dashboard_app.py`: `SHIPPED_DOCS` is a hand-written copy of the REQUIRED set and still reads `("HOW_IT_WORKS.md",)`; add `"EDITOR_SETUP.md"` so the bind-mode deploy refuses the same absence the image and the bundler now refuse. No deploy order: it only changes what a deploy REFUSES, and the file is present in the tree today.
- broll: `broll/web/app/routes_fleet.py`: the comment at :65-67 and `test_the_fleet_docstrings_do_not_claim_the_gate_needs_widening` still describe `_broll_fleet_list_re` as present in the dashboard; it is deleted now (broll-4's other half). Dashboard side deploys first or together - deleting a carve-out for a route that does not exist changes nothing on the wire.
- music: `music/web/musicweb/fleet_auth.py` is that territory's file. music-6 was assigned here, so the fix is applied there; music's builder already wrote its regression test (see Verification). If both edits land, keep this one - it is the b-roll parser verbatim.

### Owner decisions
- `EDITOR_SETUP.md` is now REQUIRED rather than best effort (CR-257f). The alternative was to make the Dockerfile's COPY tolerate its absence, which Docker has no clean syntax for. The consequence: a checkout without `docs/EDITOR_SETUP.md` now fails `tools/build_dashboard_bundle.py` by name instead of shipping a thinner /help.
- The /help index cache carries a 30 s ceiling as well as the root mtime (CR-257e). A document edited in place inside `docs/` on the base rig can therefore be up to 30 s stale in the INDEX (its title); the document itself is read per request and is never stale.
- The login backoff exponent is clamped at 16 doublings (CR-257c). Nothing observable changes - 60 s * 2**16 is already 45 days against a 1 hour ceiling - but if the ceiling is ever raised above 45 days this constant has to move with it.

### Hand-off wave

Two OWED lines were routed here. One was already done in wave 1 and is
confirmed below; the other adds a settings field whose reader lives in
another territory's file.

**broll -> dash-core: delete `_broll_fleet_list_re` and its GET clause.**
Already done in wave 1 as CR-257h (security-2): `app.py` carries no
`_broll_fleet_list_re` and no collection-path carve-out, only the two
per-batch regexes (`app.py:1062` for b-roll, `:1085` for music) and the
comment at `:1065` saying the discovery route and its carve-out must land in
the same commit if discovery ever comes back. The regression test exists
too - `test_the_broll_fleet_batch_list_has_no_login_gate_carve_out` asserts
401, not 404, for both the bare and trailing-slash forms of the collection
path. Nothing further was needed and nothing was changed.

### CR-257i (dash-release-jobs-5, hand-off) - an explicit signature URL for the vendor feed - ADDED (dashboard/src/ccsync_dashboard/settings.py)

`release_feed._signature_url` derives the detached signature's URL by putting
`.sig` on the feed URL's path. That handles a CDN-token URL (the query
survives) but it cannot handle a PRE-SIGNED URL at all: a SigV4 signature is
computed over the canonical request including the object key, so the derived
URL answers 403 SignatureDoesNotMatch and the site quietly stops receiving
builds. There was no way for an operator to name the two URLs separately.

`Settings.release_feed_sig_url` (env `DASH_RELEASE_FEED_SIG_URL`, stripped,
default empty) is that escape hatch. Empty keeps the derivation exactly as it
is, so no deployment in the field changes. A signature URL set with no
`release_feed_url` is half a configured pair in the CR-257d sense - the feed
is disabled, so the override is read by nothing - and `__post_init__` now
WARNs at boot rather than leaving the operator to wonder why their explicit
URL is never fetched.

The READ half is `release_feed.fetch_and_verify_channel`, which is
dash-release-jobs's file; the hand-off sheet routes it to them in the same
wave. The settings half alone is inert and harmless in either order.

### Verification
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_an_explicit_release_feed_signature_url_is_read_from_the_environment -> fails at f1eeb42 (no such field: `from_env` has no `release_feed_sig_url` keyword and the attribute does not exist), passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_a_signature_url_with_no_feed_url_is_named_at_boot -> fails at f1eeb42 (no warning; the setting does not exist), passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_core.py::test_the_broll_fleet_batch_list_has_no_login_gate_carve_out -> unchanged from wave 1, re-run green (the broll OWED line's confirmation)
- Whole file re-run: 9 passed. Also re-run unchanged: test_settings_hub.py, test_settings_auto_derived.py, test_settings_projects_dir.py (49 passed). py_compile on settings.py.

### OWED TO ANOTHER TERRITORY (hand-off wave)
- dash-release-jobs: `dashboard/src/ccsync_dashboard/release_feed.py`: `fetch_and_verify_channel` (and `_signature_url`'s caller at :408): use `getattr(settings, "release_feed_sig_url", "")` when non-empty instead of `_signature_url(url)`, getattr-guarded so an older Settings object still works. `fetch_and_verify_channel` takes `url` and `pubkeys` only today, so the URL has to be threaded from `release_feed.py:715` (which holds `settings`) - an optional third parameter, defaulting to "". Already on their hand-off sheet. No deploy order: both halves are in the same process, and the field is inert until read.

### Owner decisions (hand-off wave)
- The signature URL is NOT validated as https at config time. `release_feed._fetch_bytes` refuses a non-https URL at fetch time already, and duplicating the rule in settings would refuse a boot for a feed that is not even enabled.
