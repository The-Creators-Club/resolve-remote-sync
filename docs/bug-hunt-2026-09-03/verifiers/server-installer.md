# verdicts — server-installer

## server-tools-1
- Verdict: CONFIRMED (medium)
- Reasoning: I tried to refute the "silent corruption" half by checking what docker
  compose's dotenv parser actually does rather than assuming, and it does exactly what
  the hunter claims. `render_env_file` (server/backends/synology.py:1425-1448) writes
  `NAME=value` bare after refusing only `\n`/`\r` and `$`. Compose v2 parses the `.env`
  beside compose.yaml with compose-spec/compose-go `dotenv` (the deploy runs `docker
  compose --env-file <env_file> ...`, synology.py:191-195, so the file is definitely
  parsed by that code path, not passed through as-is). Two of the eight values are the
  operator's own NAS admin password (`TRUENAS_PW` / `DASH_NAS_PW` <- `secrets["TRUENAS_PW"]`,
  install_dashboard_app.py:4263, 5053-5054; docs/SECRETS.md:17 says its rotation is
  "changing the account password on the NAS"), so the refusal text "Generate it with
  `openssl rand -hex 24`" is advice the operator cannot act on, and the values that are
  NOT checked are precisely the ones the parser eats. Note also that compose's
  `${NAME:?...}` guard in the rendered compose.yaml cannot catch this: a truncated
  password is still non-empty.
- Evidence:
  - compose-go `dotenv/parser.go` `extractVarValue`, quoted verbatim from the upstream
    source: unquoted values get `value, _, _ = strings.Cut(value, " #")` (inline comment
    cut), `value = strings.TrimRightFunc(value, unicode.IsSpace)` and a leading
    `TrimLeftFunc`; a value that *starts* with a quote is treated as quoted
    (`hasQuotePrefix`) and the quotes are stripped. Single-quoted values are literal:
    no `$` interpolation, no escape processing (only the double-quote branch runs
    `expand escape sequences & then interpolate variables`).
  - Round-trip on this machine (render with `dashboard/.venv`, parse with
    python-dotenv 1.2.2 from `music/web/.venv`, which implements the same grammar):
    ```
    A_HASH          in='hunter2 #1'   out='hunter2'     *** DIFFERS
    C_PAD           in='  padded  '   out='padded'      *** DIFFERS
    D_QUOTED        in='"quoted"'     out='quoted'      *** DIFFERS
    E_SQUOTED       in="'sq'"         out='sq'          *** DIFFERS
    H_TABHASH       in='pw\t#x'       out='pw'          *** DIFFERS
    B_HASH_NOSPACE  in='hun#ter2'     out='hun#ter2'    same
    ```
    (compose-go cuts on the literal `" #"` only, so the tab case survives there; the
    space-`#`, whitespace and surrounding-quote cases are identical in both parsers.)
  - `render_env_file({"X": "a$b"})` raises `EnvError` with the openssl advice, from the
    dashboard venv — the refusal half reproduces as reported.
  - `server/tests/test_synology_backend.py:357-365` is the only coverage and asserts
    exactly the newline and `$` cases.
- Fix note: the suggested fix (single-quote every value, refuse an embedded `'`) is
  correct for compose-go — single-quoted values are literal there, `$`/`#`/whitespace
  and double quotes all become safe, and the residual refusal shrinks from "any `$`" to
  "a `'`". Two cautions: (a) compose-go and python-dotenv differ on whether `\'` inside
  single quotes is an escape, so do NOT try to escape the quote — refuse it and say so;
  (b) the refusal wording must distinguish a secret we generate from a credential the
  operator already owns, otherwise the fix keeps the unfollowable advice.
- Aside (out of my findings, worth a look): `env_file` writes `DASH_NAS_PW: truenas_pw`
  unconditionally on Synology, while the TrueNAS path deliberately blanks it when a
  scoped API key exists (`compose_nas_pw = "" if nas_api_key else truenas_pw`,
  install_dashboard_app.py:4278). On DSM the item-6 mitigation therefore does not apply.

## server-tools-2
- Verdict: CONFIRMED (medium)
- Reasoning: I looked for a downstream read-back that would refute it and there is none.
  The script in `_install_authorized_keys` (synology.py:805-820) is a `;`-list with no
  `set -e` and no `&&`; `_root` -> `root_cmd` wraps it in `sudo -S /bin/sh -c '<PATH>; <script>'`,
  so the rc is the last command's — `chmod 600 .../authorized_keys`. On the re-key path
  (`update_editor`, :698) `authorized_keys` already exists, so that chmod succeeds even
  when the `printf`/`mv` before it failed, and the function returns `(True, "")` and
  prints "installed SSH key". The only verification the caller does is
  `verify_home_permissions`, which stats mode/owner of HOME, `.ssh` and `authorized_keys`
  — it never looks at the file's CONTENT, so a stale key passes it cleanly. That makes
  the security half real: a key the operator believes they revoked by rewriting the file
  is still the only key sshd accepts, and the operator is told the account was updated.
  The sibling `ensure_home_permissions` (:846-856) chains with `&&`, which shows the
  omission is accidental rather than deliberate.
- Evidence: POSIX `;`-list semantics demonstrated locally —
  `sh -c 'false; mv -f /nonexistent/x /nonexistent/y; chmod 600 /tmp/ktest'` prints the
  `mv` error and exits `rc=0`. Read of `root_cmd` (:178-186) confirms nothing adds
  `set -e`; stderr is not consulted on the success path. Worth recording as a partial
  mitigation the hunter did not state: on a FIRST enrolment there is no pre-existing
  `authorized_keys`, so the final `chmod` fails and the failure IS caught — the false
  success is specific to the re-key / re-run path, which is also the security-relevant
  one.
- Fix note: `set -e` is right, but put it after the `if [ ! -d ... ]; then echo
  MISSING_HOME; exit 3; fi` probe (that branch is meant to exit 3 with its own message,
  and `set -e` does not interfere there anyway since the `if` condition is exempt — the
  SERVER-4 lesson). `&&`-chaining is equally correct and matches the neighbour. The
  stronger half of the suggestion — read the installed key back (fingerprint or a
  `grep -qxF` of the key line) before returning True — is what actually closes the
  revocation hole, since any `chmod`-only success is invisible to
  `verify_home_permissions`.

## install-onboard-1
- Verdict: CONFIRMED (medium; no field impact today because every deployed site is `P:`)
- Reasoning: reproduced with onboarding's system python. `ensure_config`'s editor branch
  does `site = site or {}` then `site.get("canonical_prefix") or "P:\\"` (steps.py:2613-2614),
  while `onboard.py` passes `site=self.site` — a plain `{}` after a failed `fetch_site`
  — at both call sites (:978 and :1039). Every sibling resolves the same class of value
  through the CACHE: `_site()` (onboard.py:538-542) deliberately converts `{}` to `None`
  so `site_drive_letter`/`site_tree_name` read `site_mod.cached_site()`, and
  `default_local_root` does the same. So one wizard run genuinely resolves two site
  values from two different sources. `fetch_site` returns `{}` on ANY failure by contract
  (steps.py:804-833) even though `verify_account` succeeded seconds earlier, so the
  trigger is a single transient GET. Nothing later reconciles it: `finalize_config_identity`
  re-asserts only the username, and the companion reads `canonical_prefix` from
  config.toml alone (app.py/canon.py, ~20 call sites: path re-addressing, out-of-tree
  classification, tray copy) — there is no runtime fallback to the manifest.
- Evidence (system python, `cached_site()` stubbed to `{'tree_name':'Creators_Club',
  'canonical_prefix':'Q:\\'}`, `site={}`):
  ```
  config.toml: local_root = "C:\\Creators_Club"   <- from the CACHE
  config.toml: canonical_prefix = "P:\\"          <- ignores the cache
  site_drive_letter(None) -> Q      site_drive_letter({}) -> P
  subst_task_name(cache)  -> CCSync-SubstQ
  ```
- Fix note: the suggested `site_canonical_prefix(site)` helper with the same
  `cached_site()`-when-None fallback and `_CANONICAL_PREFIX_RE` validation is right and
  matches the two existing helpers. One thing the fix must preserve: the `role == "base"`
  branch above forces `canonical_prefix = local_root` deliberately (canon.py's base-rig
  identity case) — the helper belongs in the editor branch only. Also note the caller
  should pass `self._site()` (None-when-empty), not `self.site`, or the helper's fallback
  never fires; fixing only the helper leaves the `{}` path intact.

## install-onboard-2
- Verdict: CONFIRMED (medium; same "no field impact while every site is P:" caveat)
- Reasoning: verified by reading the bootstrap's whole parameter block — there is no
  `-CanonicalPrefix` and no `-TreeName` (`awk '/^param\(/,/^\)/'` gives
  TailnetHost, EditorName, LocalRoot, RemoteRoot, DriveLabel, CompanionExePath,
  CompanionExeSource, ResolvePrefsWaitSeconds, DashboardUrl, DashboardToken, SftpPort,
  NasSyncthingId, KeepRemoteSmbOpen, DryRun). The script therefore makes its own
  `Invoke-RestMethod .../api/v1/site -TimeoutSec 8` (windows_bootstrap.ps1:663-672),
  whose failure is explicitly non-fatal, and falls back to the literal `"P:\"` at :709-710
  (and `"CCSync"` for the tree name at :696-697). The bootstrap's own comment at :645-649
  states the intended contract — "an explicit FLAG always wins (a hand-run, or the wizard
  passing what it already fetched), then the manifest, then a neutral fallback" — and
  `run_bootstrap`'s comment (steps.py:1124-1127) says passing them "keeps ONE fetch per
  install"; both are true for RemoteRoot/NasSyncthingId/SftpPort/LocalRoot and false for
  the two keys COMMERCIAL_READINESS item 11 is actually about. The halves cannot
  reconcile afterwards: `ensure_config` runs first (onboard.py:972 via
  `_write_config_and_identity`, then :1032 run_bootstrap) and the bootstrap skips its own
  config seeding when config.toml exists (windows_bootstrap.ps1:1921-1927).
- Evidence: the parameter list above; `Get-SiteValue` (:674-680) returns "" whenever
  `$Site` is null, i.e. the whole manifest block is a no-op on a failed fetch; the
  `"P:\"`/`"CCSync"` fallbacks at :696-710. This is genuinely a second finding, not a
  restatement of 1: here the wizard is RIGHT (Q) and the machine gets P, so config.toml,
  the loopback share `CCSync_P`, the logon task `CCSync-SubstP` and the uninstaller's
  cleanup list all disagree.
- Fix note: adding `-CanonicalPrefix`/`-TreeName` resolved flag-first is the right shape
  and costs nothing (the bootstrap already refuses a non-drive-letter prefix at :711-718,
  so a bad flag value fails loudly). Two constraints: pass `site["canonical_prefix"]`
  (the manifest value), never config.toml's, because the base-rig role deliberately
  stores `canonical_prefix == local_root` and that would fail the drive-letter check; and
  keep the manifest fetch in the script for hand-runs, exactly as `-RemoteRoot` does.
  A test asserting that every manifest key `run_bootstrap` holds has a bootstrap flag
  would have caught this and would keep it caught.

## install-onboard-3
- Verdict: CONFIRMED (medium)
- Reasoning: I read installer/windows_uninstall.ps1:240-310 in full and constructed the
  branch path. `$share = Get-SmbShare -Name $ShareName` is captured once, at :266, BEFORE
  any removal, and is never re-read (`Get-SmbShare` appears exactly once in the file).
  The keep-the-rule guard at :297 is `if ($smbRule -and $share -and -not $unmapSettled)`,
  which keeps the rule only in the "we deliberately kept the share because the unmap did
  not settle" case. Path to the bug: drive unmapped cleanly -> `$unmapSettled = $true` ->
  `elseif ($share)` -> `Remove-SmbShare` throws -> `catch` writes "Harmless leftover" and
  continues -> firewall block falls to `elseif ($smbRule)` -> `Remove-NetFirewallRule`
  succeeds. Share still published, block rule gone. There is a SECOND path the hunter
  missed and it is wider: if `Get-SmbShare` itself throws (the `try/catch` at :266
  swallows it), `$share` is `$null` while the share still exists, the script prints "no
  SMB share" and then removes the rule unconditionally. Nothing re-applies the rule:
  `Set-SmbLoopbackFirewallRule` is called only from windows_bootstrap.ps1 (:1247, :1321,
  :1339) and the elevated share-helper it writes, i.e. only by a re-run of the bootstrap
  — so after an uninstall the block is gone until someone reinstalls.
- Evidence: the rule is `New-NetFirewallRule -Direction Inbound -Action Block -Protocol
  TCP -LocalPort 139,445 -RemoteAddress Any -Profile Any` (windows_bootstrap.ps1:1179-1198),
  i.e. the machine-wide inbound-SMB block; the share is `New-SmbShare -Name $ShareName
  -Path $CCRoot -FullAccess "$env:USERDOMAIN\$env:USERNAME"` (:1336), the whole tree.
  The uninstaller's own comment at :288-294 states the invariant the code then breaks
  ("It also STAYS when the share stays (OPS-8)"). Mitigating, and the reason I did not
  upgrade: the grant is one named user rather than Everyone, so exploitation needs that
  Windows account's credentials, and in a NON-elevated uninstall `Remove-NetFirewallRule`
  would fail too (so the exposure needs an elevated run where only the share removal
  fails, or the `Get-SmbShare`-throws path).
- Fix note: the suggested fix is right and is the minimal one — re-read
  `Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue` AFTER the removal attempt
  and gate the firewall block on "the share is actually gone", not on `$unmapSettled`.
  Make the re-read's failure count as "still there" (the same fail-safe direction the
  unmap re-read already uses at :253-259: "an unreadable re-read counts as still
  mapped"), otherwise the `Get-SmbShare`-throws path stays open. `installer/tests` has no
  coverage of the share/firewall lifecycle at all, so this is reading-only either way.
