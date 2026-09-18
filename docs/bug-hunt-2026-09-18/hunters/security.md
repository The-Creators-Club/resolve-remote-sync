# security - auth/session gates, credential binding, path traversal, secret leakage, fail-closed

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/app.py` (full: `_OPEN_EXACT`, `_OPEN_PATTERN`, `_open_path`,
  `login_gate`, `csrf_gate`, `_origin_mismatch`, `_CSRF_*`, `body_size_gate`, `_BODY_LIMITS`)
- `dashboard/src/ccsync_dashboard/locate.py` (full) and `api.py` (`api_locate_files`,
  `api_health` + its blocks, `_require_fleet_caller`, `_require_jobs_reader`; diff since 34a3c8f in full)
- `dashboard/src/ccsync_dashboard/cards.py` (`CardsGate`, `sub_paths`, `CardsDispatch`,
  `BLOCKED_PATHS`, `data_dir_for`, `mount_cards`), `cards_pool.py` (full),
  `cards_landing.py` (full), `cards_tunnel.py` (full), `cards_ai.py` (`_cli`, model handling)
- `dashboard/src/ccsync_dashboard/auth.py` (`cookie_secure`, `start_session`, CSRF helpers),
  `help.py` (`resolve_document`, `read_rel`), `ui.py` (`page_help_document`, `_help_response`),
  `protection.py` (new `refresh_line`), `db.py` (`media_rel_key`, nas_media readers)
- `companion/src/ccsync_companion/broll_server.py` (`_vet_request`, `_post_authorised`,
  `_content_type_ok`, `do_GET/do_POST/do_PUT`, `_split_components`, `_validate_components`,
  `translate_path_with_root`, `derive_insert_paths`, `_clean_rel`, `plan_insert`,
  `build_insert_response`), `broll_standins.py` (head + key/normalise), `sync/server_locate.py` (full)
- `broll/web/app/routes_api.py` (`insert_target_detail`, `_insert_object`), `routes_ingest.py`,
  `routes_fleet.py`, `ingest_batches.py` (`mark_uploaded`), `schemas.py`, `routes_share.py`,
  `client_folders.py` (`PUBLIC_VIDEO_COLUMNS`)
- Cross-repo, for the mount contract only (read, not reported on):
  `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\handler.py`
  (`do_GET`/`do_POST` routing, `_gate`), `offline.resolve_spans`, `models.py`

Tests run: none from the repo suites (lens work). One ad-hoc probe from the dashboard venv
against a `create_app` TestClient in the scratchpad (see security-1 evidence). No live system
was touched.

## Findings

### security-1 - the `/cards` PWA login-gate carve-outs are method-agnostic, so an unauthenticated POST reaches the mounted engine
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:50-147` (`_OPEN_EXACT` entries
  `/cards/sw.js`, `/cards/manifest.webmanifest`, `/cards/icon.svg`; `_OPEN_PATTERN`;
  `_open_path`) and `dashboard/src/ccsync_dashboard/app.py:1164-1234` (`login_gate`);
  the far end is `cards.py:418` (`CardsDispatch.__call__`) into the checkout's
  `handler.do_POST`.
- What: every comment on those four carve-outs states "GET only" ("GET only, no secret in
  it", "GET only, and the slug shape is pinned"), but `_open_path` is a pure path test and
  `login_gate` never looks at `request.method`. Any verb on those paths therefore skips the
  session check. Under the mount, `POST /cards/p/<slug>/sw.js` is dispatched to that
  episode's gate and into the checkout's `do_POST`, which reads and `json.loads`es the whole
  body, and runs `offline.resolve_spans(engine, body)` when the body carries `uid_spans`,
  BEFORE any path match (the 404 is the last `else`). So an unauthenticated caller who knows
  a slug can spend a 4 MB buffered body, one of the engine's 24 WSGI workers and one
  read-only pass over the engine's card index per request.
- Failure scenario: a slug leaks the ordinary way (a phone's installed-app URL, a pasted
  link, browser history on a shared machine). `POST /cards/p/<slug>/sw.js` with
  `Content-Type: application/json`, no cookie, a 4 MB body containing `uid_spans`: 404 in the
  end, but the body was read, parsed and walked against the live engine with no session at
  all, repeatable. The same shape also means a future upstream route named `sw.js`,
  `icon.svg` or `manifest.webmanifest` is silently unauthenticated.
- Evidence: scratch probe against `create_app` (dashboard venv, `DASH_DEV_INSECURE=1`):
  `GET /cards/` and `POST /cards/open` answer `303 -> /login?next=...`, while
  `POST /cards/manifest.webmanifest`, `POST /cards/sw.js`, `DELETE /cards/icon.svg`,
  `POST /cards/p/ep-12345678/sw.js` and `POST /cards/p/ep-12345678/manifest.webmanifest`
  all fall through the gate (404 from the router, not 303/401) - i.e. the gate let a
  non-GET through on an "open" path. Cards is unmounted in that app, which is exactly why
  the answer is 404 and not the engine; with the mount the dispatcher owns those paths.
  `handler.py:1049-1082` is the body read + `resolve_spans` before routing.
- Ledger: new (CR-100 and its 2026-09-04 sibling are what opened the paths; neither asked
  for more than GET).
- Suggested fix: make the carve-out a (method, path) test - `_open_path(path) and
  request.method == "GET"` for the three PWA literals and the `_OPEN_PATTERN` branch (HEAD
  too if anything probes it), leaving every other verb to the session check.

### security-2 - any signed-in non-admin can take both Timeline Cards engine seats, and only an admin can give one back
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_landing.py:139-170` (`cards_open`, no admin
  check) vs `cards_landing.py:172-190` (`cards_close`, `auth.is_admin` or refusal), with
  `cards_pool.EnginePool.open` / `_full_sentence` / `drop` (`cards_pool.py:318-400`).
- What: the pool caps live entries at `DASH_CARDS_ENGINES` (2) and REFUSES the third rather
  than evicting (deliberate - `stop()` upstream leaks threads). Opening is available to every
  session; closing is admin-only, there is no self-close, and nothing ages a seat out
  (`ACTIVE_SECONDS` only decorates the refusal sentence and "holds no seat and frees nothing
  when it lapses"). A FAILED entry is excluded from the live count, but a `ready` or
  `loading` one is permanent for the life of the container unless an admin acts.
- Failure scenario: an editor opens the wrong episode by mistake, then the right one: both
  seats are now his, and he cannot release either. Everyone else - including the person whose
  phone is staging a cut - gets "2 episodes are already open: <name> (<editor>) and <name>
  (<editor>). Ask one of them to leave it..." with no way to leave it, until an admin is
  found or the container is restarted. That is a bad state the user cannot clear, and the
  refusal also discloses which editors are in which episode to every logged-in user.
- Evidence: `cards_open` resolves the row and calls `pool.open(...)` with no role test;
  `cards_close` is the only caller of `pool.drop` and returns
  `/cards/?refused=only+an+admin+can+close+an+episode` for a non-admin; `Entry.occupants`
  feeds `_full_sentence`, which is rendered to whoever was refused.
- Ledger: new (CR-276 is the vault-scan depth, not this).
- Suggested fix: let a user drop an episode they are the only recent occupant of (or one
  with no occupant inside `ACTIVE_SECONDS`), keeping the admin override for the rest; and
  build the refusal sentence from occupant COUNT for a non-admin reader.

### security-3 - the Cards carry-on cookie sets `secure` from the raw request scheme, not from the site's cookie policy
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_landing.py:166-168` and `:277-280`
  (`secure=request.url.scheme == "https"`) vs `auth.cookie_secure`
  (`dashboard/src/ccsync_dashboard/auth.py:539-554`), used by `auth.start_session`.
- What: every other cookie this server sets goes through `auth.cookie_secure`, which honours
  `DASH_COOKIE_SECURE` (`1`/`0`/`auto`) and `X-Forwarded-Proto` from a *trusted* proxy. The
  new 90-day `ccsync_cards_last` cookie asks `request.url.scheme` directly, which behind a
  TLS terminator (Tailscale Serve, the funnel port) is `http`. So on a site that forces
  `DASH_COOKIE_SECURE=1` the session cookie is Secure and this one is not, and the divergence
  is invisible.
- Failure scenario: dashboard behind Tailscale Serve with `DASH_COOKIE_SECURE=1`. The login
  cookie carries Secure; `ccsync_cards_last` does not, and is offered on any plaintext request
  to the same host for 90 days. It carries only a slug and is httponly, so the leak is an
  episode identifier, not a credential - hence low - but the rule "one helper decides this"
  is what stops the next cookie from being a credential.
- Evidence: the two call sites side by side; `cookie_secure`'s docstring states the policy
  the landing page does not consult. While confirming this I also found that `remember()` -
  documented as "Used by the dispatcher's visit recording" and exported in `__all__` - has no
  caller anywhere in `dashboard/src` (`grep -rn "remember("`), so the cookie is only ever
  written by the `/cards/open` form: a person who navigates straight to
  `/cards/p/<slug>/` (the installed PWA's own start URL) never updates "carry on with ...".
- Ledger: new.
- Suggested fix: pass `auth.cookie_secure(request.app.state.settings, request)` in both
  places, and either wire `remember()` into `CardsDispatch._note` as its docstring says or
  delete it.

### security-4 - `/api/v1/files/locate` answers across every active project for any fleet credential, with no per-editor scoping and the cap applied after the parse
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:10741-10762` and
  `dashboard/src/ccsync_dashboard/locate.py:75-115` (`WHERE p.active=1`, no editor/assignment
  predicate).
- What: the route is gated correctly (fleet token + dashboard-signed identity, suspended
  accounts refused), and the wide scope is documented as deliberate. It is still the only
  fleet route that answers about projects the caller is not assigned to: a name+size the
  caller supplies is confirmed or denied anywhere in the tree, and a hit returns the full
  `project_slug` + `rel_path`. Separately, `LocateIn.files` has no `max_length`, so the
  `MAX_LOCATE_FILES` cap runs only after pydantic has built every model in a body up to the
  4 MB default ceiling (~100k entries) on a single-worker container.
- Failure scenario: an editor's machine (or anyone holding that machine's token plus its
  identity - the pair lives on the editor's own disk) confirms that a named deliverable of a
  size they know exists in another client's project, and learns its path. Second: the same
  caller posts a 4 MB `files` array and spends the container's only worker on the parse
  before the 413.
- Evidence: the SQL joins `projects` on `active=1` only; `_require_fleet_caller` returns the
  name but `locate()` is never given it. `_BODY_LIMITS` has no entry for the path, so
  `MAX_DEFAULT_BODY_BYTES` (4 MB) applies and the length check is inside the handler.
- Ledger: new (related to the route's own docstring, which chose the wide scope knowingly).
- Suggested fix: bound the model (`files: list[LocateFileIn] = Field(max_length=2000)`) so
  the refusal happens in validation; and consider scoping the answer to projects the caller
  has a selection/assignment for, or at least logging the caller and the hit count.

## Coverage note

Checked and found sound, so that a later hunt does not re-walk them:
`_require_fleet_caller` (token/identity binding, retired-key drain, the three `barred`
doors); the cards tunnel's name overwrite and `X-Cards-Token` never going downstream, plus
`_clean` and `_NoRedirect`; `app.state.cards_engine` is set to `None` at the top of
`mount_cards` and never re-set, so `_routed`'s single-engine fallback cannot deliver an
agent push into another editor's episode; `BLOCKED_PATHS` normalisation (`rstrip("/")`,
percent-decoded scope path, `//api/root` falls through to the checkout's exact-match `else:
404`); `help.resolve_document`'s audience gate (fails closed on `is_admin=False`, realpath
containment, `_root` allow-list) and its one caller passing the session's admin flag;
`routes_share`'s `PUBLIC_VIDEO_COLUMNS` allow-list (migration 012's new columns are not in
it); `mark_uploaded` pinning `edit_proxy_rel` to the server-allocated path (400, not 409);
the companion loopback envelope (Host, Origin, then Origin-or-token for every POST/PUT, plus
the JSON content-type rule) and `_split_components`/`_validate_components` (`..` and
`drive:` segments) which `_clean_rel` reuses for the new `insert` object; `/api/v1/health`
gating its detail behind a session or the companion token; the Cards model picker resolving
through an upstream slug allow-list before `--model` reaches argv (no argv injection).

Not covered: the `music`/`ytdl` mounts' own gates, OIDC and `setup_api`'s first-run window,
`internal_sftp`, `cli_tools`' sign-in pty and secret files, `release_trust`/feed signature
verification, and the client-share token lifecycle beyond `PUBLIC_VIDEO_COLUMNS` - none of
them changed since 34a3c8f, which is why they were deprioritised in a time-boxed pass. The
suite has no test asserting that an open path is GET-only (security-1), none asserting a
non-admin can recover a Cards seat (security-2), and `test_locate.py` does not cover the
cross-project scope question (security-4).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/protection.py:refresh_line`: a `CHECK_FAILED` outcome stores
  `f"{type(exc).__name__}: {str(exc)[:200]}"` into a notice body rendered on the admin page -
  bounded and admin-only, but it is the one place an upstream exception string (a TrueNAS URL,
  a path) reaches a stored record rather than a log.
