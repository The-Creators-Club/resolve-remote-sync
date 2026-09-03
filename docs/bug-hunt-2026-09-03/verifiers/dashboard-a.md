# verdicts — dashboard-a

Verifier notes: all evidence below was produced from
`E:\Projects\resolve-remote-sync\dashboard` with
`.venv\Scripts\python.exe`, repo untouched (scratch scripts live in the
scratchpad). Findings verified: dash-api-1, dash-api-2, dash-api-3,
dash-api-6, dash-db-1, dash-core-1, dash-core-2.

## dash-api-1
- Verdict: CONFIRMED
- Reasoning: I could not refute it. `auth.read_identity_token(secret, ...)`
  takes `previous=()` by default, and `api.py` calls it at exactly four sites
  (2049 `_require_selection_read`, 2107 `_require_selection_untick`, 7880
  `api_diagnostics`, 8241 `_require_fleet_caller`) with no `previous=`; only
  `api.py:7236` (the report) uses `read_identity_token_ex`, which is the only
  reader of `settings.session_secrets_previous`. Two refutation attempts both
  failed: (a) per-editor `cce1.` tokens do bypass the identity check for
  selection read/untick, but `api_diagnostics` and `_require_fleet_caller`
  demand a verifiable identity for EVERY credential kind, so a modern
  per-editor-token fleet is still broken on diagnostics and jobs; (b) the
  `not settings.session_secret` lab carve-out cannot apply during a rotation,
  since a rotation by definition has one set. `docs/SECRETS.md` §"Rotating
  DASH_SESSION_SECRET" promises a drain window in which companions keep
  working, and that promise is kept for `/report` only.
- Evidence: `scratchpad/t1.py`, a `TestClient` over
  `create_app(Settings(session_secret=NEW, session_secrets_previous=(OLD,),
  report_token="sekrit"))` with an identity minted on OLD:
  ```
  selection : 401 {"detail":"X-CCSync-Identity required (and must match the editor)..."}
  diagnostic: 401 {"detail":"X-CCSync-Identity required -- sign in from the companion tray"}
  jobs/claim: 403 {"detail":"X-CCSync-Identity required - sign in from the companion tray"}
  untick    : 401
  # same requests with an identity minted on NEW: 200 / 200 / 200
  ```
- Fix note: the suggested fix is right and safe -- `read_identity_token_ex`
  returns `(username, retired_flag)`, so `[0]` at all four sites is a pure
  widening (nothing that verified before stops verifying). Two additions I
  would make: the fleet-jobs site (8241) should ALSO get the retired flag into
  the log line the report already writes, so a rotation drain is visible from
  more than one route; and the refusal copy at 2049/2107/7880/8241 is
  misleading during a rotation ("sign in from the companion tray" when the
  editor has signed in) -- worth a "or its signing key was retired" clause.
  Adding a regression test is essential: a fifth gate will otherwise repeat
  this.

## dash-api-2
- Verdict: CONFIRMED
- Reasoning: verified by reading both halves. `undo_file_move` (api.py:2610)
  builds the inverse with `to_path = dirname(from_rel)` and `path = to_rel`;
  `move_project_files` (api.py:2466) then hits `if dest.is_dir(): dest = dest
  / src.name`, and `src` is the CURRENT file, i.e. the renamed one. The
  original basename is in `move["from_rel"]` and is read by nothing. The
  branch is unconditional -- even a root-level `from_rel` (`to_dir == ""`)
  lands in it, since the project root is a directory. The rename case is
  genuinely reachable: `FileMoveIn.to_path` is documented "folder or full path
  inside it", the JSON route accepts it directly, and the htmx form is a
  free-text box (its `title` says "its own name is kept", but the server
  honours a full path).
- Evidence: code reading plus the hunter's `t_undo.py` transcript, which
  matches what the two branches predict (`B-roll/RENAMED.braw` after undo).
  `tests/test_file_moves.py::test_a_move_can_be_put_back` never renames, so
  the suite cannot see it.
- Fix note: `to_path=move["from_rel"]` is correct and I could not break it.
  For a directory undo it produces the identical result (dest does not exist,
  so the exact-path branch renames the folder back to its original name). One
  behaviour change worth stating in the commit: if something has since been
  recreated at the original path, the undo now 409s ("already exists: nothing
  was moved") instead of silently dropping the file beside it under the moved
  name -- that is the repo's "refuses rather than guesses" rule, so it is the
  right change, not a regression.

## dash-api-3
- Verdict: DOWNGRADED to low
- Reasoning: the mechanism is exactly as reported and I confirmed which side
  is wrong. `api.py:7818` emits `block["queue"]` only when the queue is
  non-empty, and `if block:` drops the whole `commands.jobs` key when there is
  nothing else to say -- so an empty fleet sends NO depth, and
  `jobs_runner.wait_seconds` reads a missing depth as "cannot tell" and
  returns `base`. The companion side is deliberate, not a bug:
  `companion/tests/test_jobs_phase4.py::test_a_dashboard_too_old_to_send_a_depth_keeps_the_old_cadence`
  pins "no depth -> old cadence", which is the correct fail-open reading for a
  dashboard deployed behind the companions. So the DASHBOARD is the side to
  change. I downgrade the severity because the impact is nil for correctness
  and small for cost: `tick()` makes no HTTP call when nothing is offered
  (`_gate` returns `STATE_NOTHING_OFFERED` and `tick` returns before
  `_claim`), so the waste is one local gate evaluation per `jobs_poll_seconds`
  per machine, not fleet traffic. The real content of the finding is "the
  IDLE_BACKOFF path is dead code", which is a low.
- Evidence: read `api.py:7760-7783` (the `if block:` guard is what actually
  kills it -- setting `block["queue"]` unconditionally is therefore also what
  makes the block always present), `db.queue_depth` (always returns all four
  keys, never falsy), `jobs_runner.wait_seconds` / `note_report_reply` /
  `_loop` / `_gate`, and the five backoff tests in `test_jobs_phase4.py`.
- Fix note: the suggested fix (send `depth` unconditionally) works, but it is
  INCOMPLETE and should not ship alone. `note_report_reply` only stores the
  new offers; nothing wakes the jobs thread, which is sleeping in
  `self._stop.wait(self.wait_seconds())`. Today that sleep is at most
  `poll_seconds`; once the backoff engages it is up to
  `IDLE_BACKOFF_MAX_SECONDS` (120 s), so a job submitted onto an idle fleet --
  including an admin's [ RUN NOW ] / `forced` -- would wait up to two minutes
  before the machine claims it. Pair the dashboard change with a wake on the
  companion side (an `threading.Event` set by `note_report_reply` whenever
  `offered`/`forced` is non-empty, waited on alongside `_stop`), and note that
  the companion change must ship WITH or BEFORE the dashboard change, not
  after. Also worth adding the seam test the hunter asks for: nothing today
  crosses report-reply -> `wait_seconds`.

## dash-api-6
- Verdict: CONFIRMED (severity low, unchanged) -- but the hunter's failure
  scenario is the wrong way round
- Reasoning: the defect itself is real: `api.py:2489` compares
  `editor_media.rel_path` (written through `db.media_rel_key`, i.e. NFC) with
  the raw admin-supplied `from_rel`, and `_clean_project_rel` does no
  normalisation. That is precisely the comparison shape CR-90 exists to
  forbid. But the scenario as written -- an admin pastes an NFD path for a
  file the NAS holds as NFC -- is UNREACHABLE: `move_project_files` does
  `if not src.exists(): 404` (api.py:2464) before it ever reaches that query,
  and on a Linux/ZFS NAS holding NFC bytes an NFD path does not exist. The
  reachable case is the mirror image: the NAS itself holds NFD bytes (written
  by a Mac through a path that did not fold), the admin pastes that NFD path,
  `src.exists()` succeeds, and the `editor_media` half then matches nothing
  because that table stored the NFC key. The consequence is narrower than
  reported too: the primary target set (`fetch_machine_selections` by slug) is
  unaffected, so only "machines whose manifest holds the file but whose plan
  no longer does" are missed. Low is right.
- Evidence: read `move_project_files` in order (404 gate precedes the query),
  `db.media_rel_key`'s docstring (which explicitly says file_moves keeps its
  own raw bytes), and `db.replace_editor_media` (normalises on write).
- Fix note: the suggested fix is correct and consistent with
  `media_rel_key`'s own rule -- normalise ONLY the value bound into that
  `editor_media` query, leaving `src`/`dest` and the `file_moves` row as raw
  bytes. Worth recording alongside it: in the NFD-on-NAS case the per-machine
  `commands.file_moves` still carries the raw NFD `from_rel` to Windows
  machines holding the NFC spelling, which will fail/block their half of the
  move. That is inherent to "the bytes on disk are the truth" and is NOT
  fixed by normalising this query; it is a separate question about whether a
  move command should carry both spellings.

## dash-db-1
- Verdict: CONFIRMED (severity medium, unchanged) -- with one part of the
  failure scenario refuted
- Reasoning: the db-level asymmetry is real and I reproduced it.
  `add_selection_for_person` filters `base_machines(conn)` (db.py:4947) and
  the tick/copy-plan routes 409 on a wired target (api.py:2253, 4488), but
  `fetch_machine_selections`'s bucket loop and `selections_for_machine` apply
  no such filter, so a `machine=''` row is inherited by a wired machine.
  End-to-end trace of `collector._run_enforce` (collector.py:1273-1380): it
  reads exactly this map, and for each `(editor, machine)` looks up
  `machine_devices[(editor, machine)]` and does `desired.add(device_id)` with
  no mode filter -- `base_machines`/`machine_modes` appear nowhere in the
  enforce cycle. So YES, a real Syncthing share is issued to a wired machine,
  under two preconditions: that machine must have reported a
  `syncthing_device_id` into `machines`, and that device must already be
  approved on the NAS (otherwise the "has not approved" branch `continue`s).
  Those are satisfiable and not exotic: `SyncthingAdmin` is constructed
  whenever `dashboard_url` is set (app.py:1418, `_managed`), NOT gated on
  `sync_enabled`, so a base-mode companion still reports `myID` if a local
  Syncthing answers -- which is exactly the shape of a machine that used to be
  an editor machine and was switched to `mode = "base"`. Note also that
  unticking a machine's LAST project re-arms the bucket for it (`has_own` is
  computed from live rows), which is a second route into the same state.
  What I DO refute is the "permanent [ GETTING READY ] chip" half:
  `build_queue_view` filters both `base_editors` and `base_pairs` on the lane
  C rows AND on the pending/getting-ready rows (api.py:583-588), so CR-28's
  visible symptom does not come back. The real symptoms are the Syncthing
  share offered to the NAS-wired machine and `GET /selection` handing a plan
  to a machine whose lanes are off.
- Evidence: `scratchpad/t2.py` against a fresh migrated db (one editor, DESK
  `mode='base'`, LAP `mode='editor'`, one `machine=''` tick):
  ```
  base_machines        {('ed', 'DESK')}
  base_only_editors    set()
  machine selections   {'projx': [('ed', 'DESK'), ('ed', 'LAP')]}
  sel_for_machine DESK ['projx']
  ```
  Plus: without this bug DESK's device would be excluded from the
  person-level fallback anyway (`d not in mapped_device_ids`), so the bucket
  loop is the SOLE route by which a mapped wired device enters `desired` --
  the fix genuinely changes the outcome rather than being shadowed.
- Fix note: the db.py half of the fix is right. The
  `selections_for_machine -> []` half needs care, for two callers the hunter
  did not name: (1) `db.copy_machine_plan` (db.py:4751) reads
  `selections_for_machine(conn, editor, SOURCE)`, so "copy the desktop's plan
  to the new laptop" would silently copy nothing when the source is a wired
  machine that was inheriting the bucket -- probably acceptable, but it should
  be a refusal with a message, not an empty copy; (2) on the companion, a base
  rig never starts the sequencer (app.py:4868), so `_selected_project_rels`
  is already empty there and proxy generation is not scoped by `/selection` --
  I checked this specifically because MODE_PROFILES keeps proxy generation ON
  for the base rig, and an empty selection would have been a regression. It is
  not. Belt-and-braces filter in `_run_enforce` is worth having as the
  OUT-OF-TERRITORY note says, since the person-level `editor_selections`
  fallback is a second (unmapped-device) route to the same place.

## dash-core-1
- Verdict: CONFIRMED (severity medium, unchanged) -- with the "silently"
  claim corrected
- Reasoning: reproduced exactly. `Settings.from_env` stores
  `DASH_AUTH_METHOD` verbatim (settings.py:674) and `__post_init__`
  normalises many things but not this one; `verify_credentials`
  (auth.py:143/157) is the only consumer that compares the RAW value, while
  `check_boot_secrets`, `describe_auth`, `setup_api._auth_method`,
  `setup_routes` and `ui.py` all `.strip().lower()`. So a mis-cased or
  newline-terminated value boots clean, describes itself as a valid method,
  lets the setup wizard create the first local admin, and then refuses every
  password for ever. One correction to the finding's title: it is not fully
  silent -- `verify_credentials` logs `unknown DASH_AUTH_METHOD 'SMB' --
  rejecting all logins` with the exact value on every attempt. It IS silent at
  boot, and the INFO line above it contradicts the ERROR, which is the part
  that would burn an operator's time.
- Evidence: `scratchpad/t3.py`:
  ```
  'SMB'     | stored: 'SMB'     | boot problems mentioning method: [] | describe: auth method=smb
  'Local'   | stored: 'Local'   | boot problems mentioning method: [] | describe: auth method=local
  'local\n' | stored: 'local\n' | boot problems mentioning method: [] | describe: auth method=local
  ' local'  | stored: ' local'  | boot problems mentioning method: [] | describe: auth method=local
  ```
- Fix note: both halves of the suggested fix are right, and the ORDER matters
  -- normalising in `__post_init__` alone would make the boot check
  unreachable (every value would already be lowercase), so the unknown-method
  check must test the ORIGINAL string, or simply test membership of the
  normalised value in `{"smb", "oidc", "local"}` after normalisation (which
  catches a genuine typo like `smd` while the strip/lower catches the case and
  whitespace variants). Refusing to START on an unknown method is the right
  call given the repo's fail-closed posture, but note it turns a
  login-refusing dashboard into a non-booting one: pair it with the exact
  value and the accepted list in the refusal text.

## dash-core-2
- Verdict: CONFIRMED (severity medium, unchanged)
- Reasoning: the code shape is exactly as reported --
  `grep -rn "allow_redirects\|_NoRedirect"` finds five `_NoRedirect` openers
  and zero `allow_redirects` anywhere, while `oidc._http_get_json` /
  `_http_post_form` and `nas/truenas.py::_request` are plain `requests` calls
  at the default `allow_redirects=True`. I tried to refute it on the
  exploitability side and only partly could: `requests.Session.rebuild_auth`
  strips the `Authorization` header across a host change, so the
  `client_secret_basic` path (and the TrueNAS Bearer/basic credentials) is
  protected; and 301/302/303 turn the POST into a GET and drop the body. What
  survives is precisely the case `_exchange` (oidc.py:397) creates when the
  IdP does not advertise `client_secret_basic`: the secret is in the FORM
  BODY, and a 307/308 preserves method and body verbatim to the new host.
  The same applies to `nas/truenas.py::_request`, whose `json_body` on the
  user-creation calls carries a password. That is a narrower window than the
  finding implies, but it is a live one, and the codebase's own stated
  invariant ("No dashboard call follows a redirect", one documented
  carve-out that says it is not precedent) is broken here regardless of
  exploitability.
- Evidence: read `oidc.py:127/135/397`, `nas/truenas.py:110-127`, and the
  five reference implementations (`ai_providers.py:1048`, `alerts.py:1806`,
  `cards_tunnel.py:89`, `dashboard_update.py:345`, `release_feed.py:158`).
  No session-level default overrides them.
- Fix note: `allow_redirects=False` is right for `_http_post_form` and for
  `nas/truenas.py::_request` -- both already treat a non-200/non-2xx as an
  error, so a 3xx becomes a named refusal for free. Be more careful with
  `_http_get_json`: real IdPs do sometimes 301 the discovery URL (an issuer
  configured without its trailing slash, a vanity hostname in front of
  Keycloak/Entra), so turning redirects off there converts a working
  deployment into a login outage. Either keep redirects on that ONE call
  (it carries no credential, and `Discovery.get`'s issuer check already
  bounds what the document may claim) with a comment saying why, or refuse
  and make the error name the `Location` so the operator's fix is obvious
  ("repoint DASH_OIDC_ISSUER at <location>"). Do not add a blanket
  `_NoRedirect` opener to `oidc.py` without that distinction.
