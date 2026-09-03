# server-tools — server/ + tools/ + .github/workflows/ (NAS provisioning, deploy, release pipeline)

Files read (with approximate coverage):
- `server/common.py` (host-key pinning, `shell_quote`, marker read/write shell,
  `run_ssh`/`sftp_put_text`, `snapshot_before`, `cli`, ScriptCalls, editor-shell
  helpers) ~40%
- `server/publish_db.py` full
- `server/install_dashboard_app.py` (`build_db_swap_script`, `build_swap_script`,
  `build_prune_script`, `secrets_as_env_refs`, `SECRET_ENV_VARS`/`STACK_ENV_SECRETS`,
  step-1 host dirs + the `snapshot_before` call site, the `.env` assembly in `main`) ~15%
- `server/backends/synology.py` (`deploy_stack`, `render_env_file`,
  `_install_authorized_keys`, `ensure_home_permissions`, `ensure_service_user`,
  `create_editor`/`update_editor`) ~25%
- `server/backends/truenas.py` (ownership/setgid script) ~10%
- `server/setup_editor_account.py` (sftp-only gate), `server/setup_tree.py` (snapshot call)
- `tools/publish_latest.py` full, `tools/release_key.py` full,
  `tools/sign_release.py` (record building, version_tuple, min_version guard) ~40%,
  `tools/publish_feed.py` (the four refusals + floor/current helpers) ~15%
- `tools/run_all_tests.ps1` full, `tools/check_licenses.py` ~70%,
  `tools/gen_notices.py` (sentinels + main), `tools/load_secrets.ps1` full,
  `tools/jobs.py` ~30%, `tools/ship.ps1` (gates + Compare-Version) ~15%,
  `tools/check_deploy_drift.ps1` skimmed
- `.github/workflows/*.yml` (triggers, permissions, publish posture, onboard manifest)
- `git ls-files --eol` over every tracked `*.sh`

Tests run:
- `cd server && ../dashboard/.venv/Scripts/python.exe -m pytest tests -q` (from Git Bash)
  -> **616 passed, 2 skipped**
- `cd tools && ../dashboard/.venv/Scripts/python.exe -m pytest tests -q` -> **252 passed**
- `dashboard/.venv/Scripts/python.exe tools/check_licenses.py` -> OK (no unexcused copyleft)

## Findings

### server-tools-1 — the Synology `.env` writer refuses a legitimate NAS admin password, and silently corrupts others
- Severity: medium
- Confidence: CONFIRMED (the `$` refusal); PLAUSIBLE (the `#` / quote / whitespace corruption)
- Where: `server/backends/synology.py:1425-1448` (`render_env_file`), fed from
  `server/install_dashboard_app.py:5048-5063` (`env_file`, which carries
  `TRUENAS_PW` and `DASH_NAS_PW` = the operator's real NAS admin password)
- What: `render_env_file` validates exactly two things — no newline, no `$` — and
  otherwise writes `NAME=value` raw. Its refusal text ("Generate it with
  openssl rand -hex 24") assumes every value is a secret *we* generated, but two of
  the eight are the customer's own NAS admin password, which the operator cannot
  regenerate to suit a `.env` parser. Meanwhile the values it does *not* check are
  exactly the ones docker compose's dotenv parser mangles: an unquoted inline ` #`
  starts a comment, a value wrapped in matching quotes has the quotes stripped, and
  leading/trailing whitespace is trimmed.
- Failure scenario: (a) a DSM site whose NAS admin password is `Str0ng$Pass!` —
  `install_dashboard_app.py` aborts the whole deploy with `EnvError: TRUENAS_PW
  contains a '$' ... Generate it with openssl rand -hex 24`, advice that is
  impossible to follow for that credential; the only real fix is to change the NAS
  admin's password, which nothing tells the operator. (b) a password of
  `hunter2 #1` is written verbatim, compose reads `DASH_NAS_PW=hunter2`, the
  container starts healthy, and every NAS call it makes (SSH/`sudo -S`, the DSM
  API) fails authentication with no hint at the cause.
- Evidence:
  ```
  $ dashboard/.venv/Scripts/python.exe -c "... render_env_file(...)"
  REFUSED: TRUENAS_PW contains a '$', which docker compose would interpolate out
           of the .env. Generate it with `openssl rand -hex 24`.
  ['TRUENAS_PW=hunter2 #1', 'X=  padded  ', 'Y="q"']
  ```
  `server/tests/test_synology_backend.py:358-365` covers only the newline and `$`
  cases, so the suite would not catch either half.
- Ledger: new (`grep -n "render_env_file" KNOWN_BUGS.md` -> nothing)
- Suggested fix: single-quote every value (`NAME='...'`, refusing a value containing
  a single quote) so `$`, `#`, quotes and whitespace are all literal — compose's
  dotenv honours single quotes and does not interpolate inside them — and reword the
  remaining refusal so it distinguishes "a secret we generate" from "the NAS admin
  password you already have".

### server-tools-2 — a failed SSH-key rewrite on DSM reports success, leaving the OLD key live
- Severity: medium
- Confidence: CONFIRMED (shell semantics); the triggering write failure is uncommon
- Where: `server/backends/synology.py:803-823` (`_install_authorized_keys`), callers
  at `server/backends/synology.py:679` (create) and `:698` (`update_editor`, the re-key path)
- What: the generated remote script is a `;`-separated list with **no `set -e` and
  no `&&`**, so `self._root(script, ...)` returns the exit status of the *last*
  command only — `chmod 600 <home>/.ssh/authorized_keys`. Every earlier step (the
  `printf` of the new key into the temp file, the `mv -f` into place, the
  `chown -R`) can fail without changing the rc. The sibling helper
  `ensure_home_permissions` (:846-856) chains the same kind of steps with `&&`,
  which is the correct form and shows the omission is accidental.
- Failure scenario: an editor's DSM key is rotated (`update_editor` with a new
  pubkey). The home volume is over quota / read-only / the `.ssh` ACL has drifted,
  so the `printf` and `mv` fail; `authorized_keys` already exists from the previous
  enrolment, so `chmod 600` succeeds and rc is 0. `_install_authorized_keys` returns
  `(True, "")`, prints `installed SSH key: .../authorized_keys (0600, owned by
  <user>)`, and `setup_editor_account` reports the account updated. The editor's new
  key does not work, and — the security half — a key the operator believed they had
  *revoked* by rewriting the file is still the only key sshd will accept.
- Evidence: read of the generated string (f-strings joined by `"; "`, no `set -e`);
  POSIX `sh` returns the last command's status for a `;` list. Contrast
  `ensure_home_permissions`, which uses `&&` throughout, and
  `common.build_marker_read_cmd`'s SERVER-4 note, which is this exact class of bug
  ("an `if` CONDITION is exempt from its command's exit status") caught once already
  in a neighbouring generated script.
- Ledger: new (related to SERVER-4's lesson, a different call site)
- Suggested fix: prefix the script with `set -e` (or chain with `&&`), and read back
  the installed key's fingerprint before returning True.

### server-tools-3 — no workflow declares `permissions:` except image.yml, so the release builders run with the repo's default `GITHUB_TOKEN`
- Severity: low
- Confidence: PLAUSIBLE (depends on the repo/org default-permissions setting, which
  I cannot read from here)
- Where: `.github/workflows/ci.yml`, `release-windows.yml`, `release-macos.yml`,
  `release-dashboard.yml`, `android.yml` (no top-level `permissions:` block);
  `.github/workflows/image.yml:71-75` is the only one that scopes it
- What: CLAUDE.md and each release workflow's header state the invariant "CI builds
  (never publishes); this rig signs". That is enforced only by what the workflow
  *steps* do — nothing constrains the token they hold. If the repo's default
  workflow permissions are the legacy read/write, an action or a step edit in a
  release workflow can create a GitHub Release or upload a feed asset with the
  ambient token, which is exactly the boundary `publish_latest.py`'s "the signing
  key never enters GitHub" comment is drawing.
- Failure scenario: a compromised or careless third-party action in
  `release-windows.yml` (it already uses `actions/checkout`, `setup-python`,
  `upload-artifact`) uploads an asset to `The-Creators-Club/ccsync-releases` under
  the ambient token. The bytes would still fail signature verification, but "CI
  never publishes" is currently a policy, not a permission.
- Evidence: `grep -n "permissions" .github/workflows/*.yml` matches only image.yml
  (every other hit is prose in a comment).
- Ledger: new
- Suggested fix: add `permissions: contents: read` at the top of ci.yml and the
  three release workflows (android.yml too), overriding per-job only where a write
  is actually needed.

### server-tools-4 — `check_licenses.TARGETS` carries mutable per-run state, so two `check()` calls in one process union their platform slices
- Severity: low
- Confidence: CONFIRMED
- Where: `tools/check_licenses.py:134-141` (`Target.names: set[str] = field(default_factory=set)`,
  on module-level `TARGETS`) and `:317` (`target.names |= parse_lock(target.lock, platform)`)
- What: `names` accumulates into the shared module-level `Target` objects and is
  never reset between calls. The CLI is one call per process, so the shipped gate is
  unaffected, but `tools/tests/` and any programmatic caller get contamination: a
  `check(platforms=["darwin"])` after a `check(platforms=["win32"])` reports the
  win32-only packages (e.g. `colorama`) as UNSCANNED on darwin, which under
  `--strict` is a FAIL.
- Failure scenario: a future test (or a wrapper that runs all three CI slices in one
  process to produce a combined report) sees phantom `FAIL` rows for packages the
  slice never asked about.
- Evidence: read; `names` is the only mutable field on a module-level list of
  dataclasses, and there is no `target.names.clear()` anywhere in the file.
- Ledger: new
- Suggested fix: build the name set as a local in `check()` rather than storing it
  on the shared `Target` (the printed `packages: {len(target.names)}` line can take
  it from the same local).

### server-tools-5 — `load_secrets.ps1` materialises each secret into a plain `$plain` variable it never uses or frees
- Severity: low
- Confidence: CONFIRMED
- Where: `tools/load_secrets.ps1:117-121`
- What: `-Save` converts the SecureString to a BSTR and then to a .NET string purely
  to run `[string]::IsNullOrEmpty($plain)`, then stores the SecureString form. The
  plaintext string stays in the session's variable table (and in the BSTR, which is
  never `ZeroFreeBSTR`'d) for the life of the window — the same window the script's
  own docstring argues should not hold plaintext ("close the window and they are
  gone" is true of `$env:`, not of `$plain`).
- Failure scenario: an operator runs `-Save` and leaves the window open; anything
  that dumps variables (`Get-Variable`, a crash dump, a transcript started later)
  contains the NAS admin password in clear.
- Evidence: read; `$plain` has exactly one use, the emptiness test.
- Ledger: new
- Suggested fix: test emptiness with `$secure.Length -eq 0` and drop the BSTR round
  trip entirely.

### server-tools-6 — the DSM service account's throwaway password goes on the remote process's argv
- Severity: low
- Confidence: CONFIRMED
- Where: `server/backends/synology.py:930-933` (`synouser --add <name> <pw> ...`
  built with `shell_quote(_random_password())`)
- What: this is the one place in the package that puts a credential on a remote
  command line, the thing `common.SUDO_PW_PREAMBLE`'s SEC-2 note exists to avoid
  ("any local NAS account could read it out of `ps`"). It is mitigated by the value
  being random, single-use and attached to a `/sbin/nologin` account, but the
  exception is undocumented at the call site.
- Failure scenario: any local DSM account running `ps` during the ~1 s the
  `synouser --add` runs reads the password of the account the dashboard container
  runs as. That account is nologin, so the practical impact is small — it is the
  invariant, not the exposure, that is broken.
- Evidence: read; contrast `common.run_ssh`'s docstring (AUDIT SEC-2).
- Ledger: new
- Suggested fix: either feed the password on stdin the way `SUDO_PW` is, or leave a
  one-line comment at the call site recording that this is a deliberate,
  never-reused value, so the next reader does not copy the pattern.

## Coverage note
- `install_dashboard_app.py` is 5 105 lines; I read the swap/verify/prune script
  builders, the secrets plumbing and the `snapshot_before` call site, but not the
  compose rendering, the health/restart verification, the image-mode path or the
  ~40 helper functions around them. `check_deploy_drift.ps1` (641 lines) and
  `ship.ps1` (890) were skimmed for the specific gates the brief names, not read in
  full; `release.ps1` (865), `release_macos.sh`, `make_product_repo.ps1` and
  `build_dashboard_bundle.py` were not read.
- `publish_feed.py` (1 308 lines): I verified the four refusals the brief names and
  the floor/current helpers, but not the GitHub upload path, `--retract`, or
  `fetch_published_channel`'s redirect handling.
- **What the suites do not cover:** `server/tests` never exercises
  `render_env_file` beyond the two cases in finding 1, and there is no test
  anywhere that asserts a generated remote script's *exit status* propagates a
  mid-script failure — every test I read asserts on the script's TEXT, or runs it
  under a stub where every command succeeds. Finding 2 is invisible to the suite for
  that reason. Nothing in `tools/tests` runs the PowerShell files at all
  (`run_all_tests.ps1`, `ship.ps1`, `check_deploy_drift.ps1`, `load_secrets.ps1`
  have no tests), so finding 5 and the ship/drift gates rest on reading alone.
- `git ls-files --eol` over every tracked `*.sh` shows all 15 are
  `i/lf w/lf attr/text eol=lf` — no CRLF hazard on anything the NAS or a Mac executes.
- Verified-clean (looked hard, found nothing): `common.shell_quote` and every
  interpolation through it; the host-key pinning three-state machine, including the
  `[host]:port` known_hosts spelling and the changed-key refusal; `publish_db.py`'s
  checkpoint/snapshot/verify/stage/swap chain and its `-wal`/`-shm` handling in both
  directions; `build_db_swap_script`'s owner/mode validation and rename rollback;
  `publish_latest.py`'s `ls-remote` + `merge-base --is-ancestor` check and its
  older-version / dirty-tree / platform-mismatch refusals; `publish_feed.py`'s
  same-version-different-bytes, floor-drop, recall-list and key-rotation refusals;
  `sign_release.min_version_exceeds_version` (CR-52); `release_key.py`'s
  `O_EXCL|0600` key creation and clobber refusal; `run_all_tests.ps1`'s
  `$LASTEXITCODE = 9999` guard and `exit $failed` (13 suites, `PASS*` handled
  correctly); the sftp-only -> `sftp_shell_type = "none"` forcing
  (`install_dashboard_app.py:1572`); `snapshot_before` on the deploy/`--recreate`
  path and on `setup_tree`'s `chown -R`.

## OUT OF TERRITORY
- `dashboard/deploy/compose.yaml`: the eight `KEY: "REPLACE_ME"` lines
  `secrets_as_env_refs` must find are pinned only by
  `server/tests/test_compose_template.py`; a drift there is a hard deploy refusal,
  worth a second reader.
- `companion/src/ccsync_companion/release_pubkey.py`: `canonical_record` /
  `OPTIONAL_KIND_EXTRA_FIELDS` is duplicated in `release_trust.py`; the two must
  agree byte for byte and I did not diff them.
