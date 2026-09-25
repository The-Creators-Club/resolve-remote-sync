# G1b ledger: companion transport (LG-4, wave 0 + the opener migration)

2026-09-25. Plan: `docs/LEGAL_GAP_FEATURES_PLAN.md` revision 2, section 4.4
and rows G1b of 7.2 / 7.3. Built against acdcfba. No version bumped, nothing
committed.

## What was built

### `companion/src/ccsync_companion/transport.py` (NEW, leaf module)

No import from the package (pinned by a test), so the wizard (G8) and the
dashboard's parity test (G2a) can load it standalone.

- `classify(url) -> "https" | "loopback" | "http_local" | "http_public" | "invalid"`.
  Constants `HTTPS`, `LOOPBACK`, `HTTP_LOCAL`, `HTTP_PUBLIC`, `INVALID`,
  `CLASSES`. Never raises.
  - https to anything is `https`. Plain http to 127/8, ::1, `localhost`,
    `*.localhost` is `loopback`. Any other scheme, or no host, is `invalid`.
  - `http_local`: private, link-local, CGNAT 100.64/10 and loopback IPs; a
    single-label name; `.ts.net .local .lan .internal .home.arpa`; the
    RFC 2606/6761 reserved names (`.test .example .invalid .localhost`,
    `example.com/.net/.org`), which are classified without a lookup; and any
    IP literal that is not globally routable (documentation, 0.0.0.0).
  - `http_public`: a globally routable IP literal (IPv4-mapped IPv6
    unwrapped), or a name whose EVERY resolved address is global.
  - A name that fails to resolve, resolves to nothing, or has any
    non-global address is `http_local` (safety H3: never refuse on doubt).
  - Lookups are cached per host for 600 s (`RESOLVE_TTL_SECONDS`); a failed
    lookup for 60 s (`RESOLVE_FAIL_TTL_SECONDS`). `transport.resolve` is the
    swappable resolver (getaddrinfo); `clear_cache()` for tests.
- `host_is_local(host)`: the body of `upgrade._host_is_local`, moved.
- `CleartextGuard`: a urllib `BaseHandler` (`handler_order = 100`) whose
  `http_request` raises `CleartextRefused` for `http_public`.
- `CleartextRefused(url)`: subclass of `urllib.error.URLError`, carries
  `.url` and `.host`.
- `is_refused(url) -> bool`.

### `upgrade.py`

- `_host_is_local = transport.host_is_local` (alias kept; `transport_ok`
  unchanged and still shape-only, so the updater stays stricter than the
  guard).
- `build_no_redirect_opener()` now builds `NoRedirectHandler`,
  `transport.CleartextGuard`, then any extra handlers. Every credentialed
  dashboard call already uses this opener.
- Removed the now-unused `import ipaddress`.

### `identity.py`

- `_warn_if_plaintext`, `_PLAINTEXT_WARNED` and `_LOOPBACK_HOSTS` deleted
  (plan 4.4, G1a bullet; done here because `identity.py` is G1b's file).
- `verify_credentials` catches `transport.CleartextRefused` before the
  generic branch and returns `{"ok": False, "error":
  CLEARTEXT_REFUSED_MESSAGE}`, the plan's tray wording: "Not sent: the
  dashboard address is plain http on the internet. Ask your admin for its
  https address." (no em dash). `CLEARTEXT_REFUSED_MESSAGE` is a module
  constant G1a can reuse for the tray line.
- Removed the now-unused `import urllib.parse`.

## Departures from the plan, and why

1. **The opener migration needed no code change.** The plan lists
   `identity`, `jobs_runner`, `project_setup`, `timeline_cards_role` and
   `sync/server_locate` as modules to move onto the shared opener. Read on
   2026-09-25 they already are: `identity` posts through
   `reporter.default_http_post`; `jobs_runner`, `server_locate` and the Cards
   tunnel (`TimelineCardsRole.call`) default to
   `broll_ingest.default_request`, which uses `build_no_redirect_opener()`;
   `project_setup` sends nothing (it only opens a browser at
   `/project-setup`). `jobs_runner.py`, `project_setup.py`,
   `timeline_cards_role.py` and `sync/server_locate.py` are therefore
   untouched. What the plan wanted from the migration is pinned instead by
   tests: the no-stray-opener AST scan, an end-to-end test of every
   production fleet transport against a public address, and a source pin
   that the three lazy importers default to `default_request`.
2. **`host_is_local` checks IP literals first.** Writing the table found a
   pre-existing bug: an IPv6 literal has no dot, so the single-label rule
   called `2001:4860:4860::8888` an intranet name and the updater allowed
   plain http to it. Now a literal is judged as an IP. Effect on the
   updater: stricter for public IPv6 only; every existing updater test passes.
3. **Reserved names are `http_local` without a lookup.** Not in the plan.
   It keeps every existing test fixture (`http://dash.example.com`,
   `http://dash.example`) off the network and out of the refusal, and such a
   name can never be a real public dashboard.
4. **`CleartextRefused` is a `URLError`.** The plan does not say. Chosen so
   every existing caller's "could not reach the dashboard" path and its
   never-raise contract handle the refusal unchanged.
5. **`test_identity.py` edited:** the three AUDIT_3 L-13 warning tests were
   replaced by two: tailnet http still signs in, and a public http sign-in is
   refused before sending through the real opener with the sentence above.

## Tests run

- `companion/tests/test_transport.py` (NEW): **86 passed**. Classify table
  (38 cases), DNS evidence (all-public, split-horizon, tailnet, mixed,
  failure/empty/garbage, cache, expiry, shorter failure TTL), guard through
  the real urllib chain (refused before sending; every fleet-shaped address
  passes; split-horizon and unresolvable are sent; NoRedirectHandler still
  present), every production fleet call function refused on public and
  passing on LAN, the three lazy `default_request` users, the no-stray-opener
  scan with a justified allowlist (and no dead entries), the updater alias,
  the shape rule, the updater staying stricter, and the leaf-module pin.
- `companion/tests/test_identity.py` (edited): **56 passed**.
- Because `upgrade.build_no_redirect_opener` changed, the suites that drive
  it were also run: `test_transport, test_identity, test_upgrade,
  test_dashboard_redirects, test_reporter, test_selection,
  test_jobs_resilience, test_ytdl_executor,
  test_bug_hunt_2026_09_11b_comp_sync, test_site` together: **717 passed**.

## Hand-offs owed

- **G1a:** the tray line on refusal. Test `isinstance(exc,
  transport.CleartextRefused)` (or check `transport.is_refused(dashboard_url)`
  before a pass) and reuse `identity.CLEARTEXT_REFUSED_MESSAGE`. Sign-in
  already returns that sentence as its error. `config.validate_config` and
  `settings_window.py` should call `transport.classify`. The
  `_warn_if_plaintext` deletion the plan gave G1a is DONE here.
- **G8 (wizard):** `transport.classify(url)`; refuse `http_public`, note
  `http_local`. The module is standalone-importable.
- **G2a (`dashboard/netclass.py`):** must match `classify` for the table in
  `test_transport.py::test_classify_table`, including: IP literal before the
  single-label rule; `is_global` as the test for "public"; IPv4-mapped IPv6
  unwrapped; reserved names local; a name is public only if every resolved
  address is global. The dashboard classifies the `Host` header, so a name
  there resolves on the dashboard host. The parity test may import
  `companion/src/ccsync_companion/transport.py` by path.
- **G9 (docs):** nothing in the plan's section 8 wording depends on these
  departures. `docs/GOTCHAS.md` may want one line: the updater
  (`transport_ok`) is deliberately stricter than the report guard (it
  refuses a cleartext public-looking name by shape, with no DNS lookup).
- **Overseer:** the section 4.4 pre-ship check (no machine with
  `report_via = 'http_public'`) is unchanged by this group.

## Review round (2026-09-25)

1. **Fixed (medium), plan 4.4 amended in code.** A DNS verdict now lives
   30 s, success and failure alike (was 600 s / 60 s). A laptop that cached
   "local" on the studio's split-horizon DNS and then joined another network
   would have sent reports, the fleet token and a sign-in password in
   cleartext to the studio's public port forward for up to ten minutes; the
   reverse refused it for ten minutes back home. The OS resolver caches too,
   so the short TTL costs a cache hit, not a query. **Remaining race, not
   closable here:** the guard's lookup and the connection's lookup are two
   separate `getaddrinfo` calls, so a record that flips between them is not
   caught. The window is the gap between two calls, not a TTL. **Departure
   from the plan:** section 4.4 says 600 s; the overseer/docs group should
   amend that line to 30 s. Test:
   `test_a_network_change_is_noticed_within_thirty_seconds` (private answer,
   31 s later a public one, refused through the real opener, nothing sent).
2. **Fixed (low).** A dotless all-digit, `0x` hex or leading-zero octal label
   is parsed as IPv4 (inet_aton's shorthand) BEFORE the single-label
   intranet rule, in both `host_is_local` (so `upgrade.transport_ok` too) and
   `classify`. Parsed by hand, not `socket.inet_aton`, so every platform and
   the dashboard's parity copy agree. Above 2**32-1, or `09`-style non-octal,
   stays a name. No lookup is made for any of them. Tests:
   `test_dotless_numeric_hosts_are_judged_as_addresses` (8 rows:
   `134744072`, `0x08080808`, `01002004010` public; `3232235530`,
   `0x7f000001`, `0` local; `99999999999`, `09` names) and
   `test_the_updater_refuses_dotless_public_literals` (2 rows).
3. **Fixed (low, copy).** `CleartextRefused`'s reason no longer says
   "(LG-4)"; it reads `not sent: <host> is plain http on the public
   internet; use the dashboard's https address`. The id is in a WARNING log
   line from the guard (`LG-4: refused plain http to public address ...`),
   once per host per ten minutes because a refused report retries every few
   seconds. Test: `test_the_refusal_reason_carries_no_ticket_id_and_the_log_does`.
4. **Accepted (info), recorded.** `sync/syncthing_admin.py`'s `_opener()`
   also uses `upgrade.build_no_redirect_opener()`, so the guard covers lane
   C's Syncthing admin calls (`X-API-Key`). No fleet impact: the default
   `syncthing_url` is `http://127.0.0.1:8384` (`loopback`). A site pointing
   lane C at a Syncthing GUI on a public IP over plain http now has lane C
   refused, surfacing as a plain URLError. That is the right direction (the
   admin key was going out in cleartext), but it is a scope the plan did not
   name.

Proof the new tests bite: with the four changes reverted in place (TTLs
600/60, numeric parse disabled, "(LG-4)" back in the reason, log call
removed), the new tests give **7 failed, 5 passed** (the 5 are the rows
that were already local). Restored: `test_transport.py` +
`test_identity.py` + `test_upgrade.py` **328 passed**
(`test_transport.py` + `test_identity.py` alone: 154 passed).

### Hand-offs added this round

- **G9 (docs / GOTCHAS):** one line each: the DNS verdict TTL is 30 s and
  the guard-lookup vs connect-lookup race remains; the guard also covers
  Syncthing admin calls (a public plain-http `syncthing_url` is refused).
  Plan section 4.4's "600 s" should read "30 s".
- **G2a (`dashboard/netclass.py`):** parity now also includes the dotless
  numeric IPv4 rule (`_single_label_ipv4`) ahead of the single-label rule,
  and the 30 s TTL if the dashboard caches lookups.
- **G1a:** unchanged, but the refusal string is now safe to show verbatim
  if the tray line lands late.
