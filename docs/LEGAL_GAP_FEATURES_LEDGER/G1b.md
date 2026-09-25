# G1b ledger: companion transport, wave 1 (the opener migration)

2026-09-25. Plan: `docs/LEGAL_GAP_FEATURES_PLAN.md` revision 2, section 4.4,
rows G1b of 7.2 / 7.3. Wave 0 (`transport.py`, the guard in
`upgrade.build_no_redirect_opener()`, the `identity.py` refusal, and
`test_transport.py`) is recorded in `transport.md` in this directory. This
file covers the wave-1 half only. No version bumped, nothing committed.

## What was built

Nothing new in code. The wave-1 task is "move every other module that sends
the fleet credential to `dashboard_url` onto the shared opener". It was
re-checked independently in this wave, call site by call site, and every one
is already on it:

| Module (plan's list) | How it reaches the dashboard | On the guarded opener? |
|---|---|---|
| `identity.py` | `reporter.default_http_post` | yes (`upgrade.build_no_redirect_opener()`) |
| `jobs_runner.py` | lazy `broll_ingest.default_request` (line ~784) | yes |
| `sync/server_locate.py` | lazy `broll_ingest.default_request` (line ~158) | yes |
| `timeline_cards_role.py` (tunnel calls) | lazy `broll_ingest.default_request` (line ~976) | yes |
| `project_setup.py` | sends nothing; only `webbrowser.open` on `<dashboard_url>/project-setup` | n/a |

The other credentialed senders the plan names as already migrated were also
confirmed: `reporter.default_http_post`, `broll_ingest.default_request`,
`ytdl_executor.default_request` (and `selection`, `site` through
`reporter`/the same opener). The remaining `urlopen`/`build_opener` users in
the package are not dashboard calls: `ytdlp_manager.default_github_open`
(GitHub only, off-origin redirects refused), `broll_vlm/*` (the local VLM
runtime on loopback), `ytdl_browser_login` (loopback `http.client`), and
`sync/syncthing_admin` (already on the guarded opener, see `transport.md`
review item 4).

## Departures from the plan, and why

1. **No edits to `jobs_runner.py`, `project_setup.py`,
   `timeline_cards_role.py` or `sync/server_locate.py`.** The migration had
   already happened before this plan (COMMERCIAL_READINESS item 15,
   2026-08-17, put every fleet call on the no-redirect opener), so there was
   nothing to move. What the plan wanted from the migration is pinned by
   wave 0's tests instead: `test_no_module_opens_http_outside_the_shared_opener`
   (AST scan with a justified allowlist and no dead entries),
   `test_every_fleet_call_function_is_guarded` (each production fleet
   transport refused on a public http address, passing on LAN), and the
   source pin that the three lazy importers default to `default_request`.
2. **No wave-0 file was edited** (`transport.py`, `upgrade.py`,
   `identity.py`, `test_transport.py`, `test_identity.py`), per the
   instruction to build on wave 0.

## Tests run

`companion/tests/test_transport.py`, `test_identity.py`, `test_upgrade.py`
(the files that pin this group's contract): **328 passed** (3.5 s). No file
was created or touched in this wave, so nothing else was run.

## Hand-offs owed

None new. Wave 0's hand-offs in `transport.md` stand:
- **G1a:** tray line on refusal (`transport.CleartextRefused` /
  `identity.CLEARTEXT_REFUSED_MESSAGE`); `config.validate_config` and
  `settings_window.py` call `transport.classify`.
- **G8:** wizard uses `transport.classify`; refuse `http_public`, note
  `http_local`.
- **G2a:** `dashboard/netclass.py` parity with `classify`, including the
  dotless numeric IPv4 rule and the 30 s DNS TTL.
- **G9 / overseer:** plan 4.4's "600 s" reads "30 s"; GOTCHAS lines for the
  TTL race and the Syncthing-admin coverage; a new module that talks to
  `dashboard_url` must use `broll_ingest.default_request` or
  `reporter.default_http_post` (the AST scan enforces it).
