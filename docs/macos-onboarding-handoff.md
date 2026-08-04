# macOS handoff — 2026-08-04

> **UPDATE, same day:** the §2 design question is answered — **option A was
> chosen and implemented** (installer 1.0.17). The wizard now runs on macOS:
> `onboarding/steps.py` darwin branches, a macOS clean-slate,
> `build_onboard_macos.spec` + `tools/build_onboard_macos.sh`, and
> `macos_bootstrap.sh` speaking the wizard's machine-readable contract
> (`CAPABILITY MISSING:` + exit 3, `RESOLVE-MAPPING-STATUS:`, existing-config
> `rclone_path` repair). The role page is asked on macOS too — a commercial
> deployment can run a Mac base rig (companion + LaunchAgent, NAS mount
> untouched). And the distribution decision is made: `build_onboard_macos.sh
> --publish --make-current` puts the zipped .app in the `macos`/`onboard`
> slot, which is **what a Mac's [ INSTALLER ] click downloads** (dashboard
> 0.3.7 names that slot's uploads by content, zip vs script; Windows ships no
> longer push the `.sh` there — see `build_editor_package.ps1`'s advisory).
> Code-complete and unit-tested on Windows (215 onboarding tests green);
> **never built or run on a Mac** — the build needs the Mac and slots in
> after A8 in §6. §2's comparison table describes the pre-1.0.17 state.

Everything needed to pick up the macOS port. Written at the point where the
code builds and tests clean on real hardware but **nothing has been installed
or run** on a Mac, and where the onboarding path for a Mac editor is a
Terminal command rather than the wizard Windows editors get.

Companion documents: `docs/macos-first-run-2026-08-04.md` (the raw findings
from the first Mac session), `installer/MACOS_FIRST_RUN.md` (the ordered
checklist), `installer/README.md` → "Next steps for macOS" (the same plan in
brief), `KNOWN_BUGS.md` item 8 (the standing status).

---

## 1. Where it stands

| | |
|---|---|
| Repo | `main` @ `c725256` — pushed, and checked out on the Mac |
| Companion suite, macOS | **1563 passed, 18 skipped, 0 failed** (all skips genuinely Windows-only) |
| Companion suite, Windows | 1581 passed, 0 skipped |
| Dashboard suite | 354 passed, 1 skipped |
| macOS artifact | built, ad-hoc signed, arm64, `tests_run: true`, `git_dirty: false` |
| Published to the fleet | **no** |
| macOS runtime validated | **no — not one line has executed** |

The artifact lives at
`/Users/leso/resolve-remote-sync/companion/dist/ccsync-companion`
(sha256 `74965ae9dba0ee2cdc51c6e775cd228f0ecbbac5837b76cfb61caa20c6d540ec`,
20,954,720 bytes). It is the first Mac build whose manifest is honest on
every field; the previous one was `0.4.20+dirty` with `tests_run: false`.

**Do not read the green suite as a validated port.** What has run is
compilation and unit tests. `diskutil`, `launchctl`, `xattr`, the Resolve
preference *write*, `caffeinate`, the external-SSD root guard, the
self-upgrade swap and the menu-bar tray have never executed anywhere.

### Package channels (live, checked 2026-08-04)

| platform | kind | current |
|---|---|---|
| windows | companion | 0.4.20 |
| windows | onboard | 1.0.16 |
| macos | onboard | 1.0.16 (this is `macos_bootstrap.sh`, see §2) |
| macos | **companion** | **nothing published** |

```
GET /api/v1/companion/package/macos/current
→ 404  "no current macos companion package is published"
```

> **UPDATE 2026-08-04 (later): A8 is DONE.** The macos companion channel now
> serves **0.4.20, CURRENT** — published over SSH via the handoff's own
> "direct PUT with a minted session cookie" route, uploading the exact
> artifact described above (sha `74965ae9…`, verified again byte-for-byte
> at publish time; ad-hoc signature re-confirmed). Note the ordering
> deviation: §5's recommendation was A7-before-A8, and **A7 has still not
> run** — accepted deliberately because zero Mac companions exist to
> upgrade, so the channel going live affects only future installs. The
> table above is the pre-publish state.

So a Mac editor running the bootstrap today gets rclone, syncthing, a config
and a LaunchAgent — and then no companion. That is exactly the half-finished
state sitting on leso's Mac from a 13:43 run on 2026-08-04.

---

## 2. The onboarding gap — the main open design question

**There is no macOS equivalent of `onboard.exe`.** `onboarding/` describes
itself as an "all-in-one **Windows** installer wizard"; `steps.py` shells out
to `installer/windows_bootstrap.ps1`, and its only platform check is a
`win32` branch. The published `macos`/`onboard` package is not a wizard — it
is `macos_bootstrap.sh`, uploaded under the `onboard` kind so `/download`
serves the script to Mac user-agents.

| | Windows (`onboard.exe`) | macOS (`macos_bootstrap.sh`) |
|---|---|---|
| Form | tkinter GUI wizard, double-click | Terminal command with flags |
| Tailscale install | winget, in-wizard | `brew install --cask tailscale`, else exits telling you to do it by hand |
| Tailscale **connection test** | **yes** — `tailscale status` + live `GET /api/v1/health`; Next stays disabled until both pass | **no** |
| Credential **gate** | **yes** — POSTs `/api/v1/verify`; a wrong password stops the install | **no** — installs under whatever `--editor-name` is typed |
| SSH keypair | preserved/handled | **out of scope by design** (`macos_bootstrap.sh:27`) — warns and prints the `ssh-keygen` line for the user to run |
| `tailscale up` | in-wizard | **out of scope by design** — manual |
| Dashboard token | held in memory after sign-in | pasted on the command line as an env var |
| Clean slate of old installs | full (autostart entries, old exes, shims, drive unmount) | none |

### What a Mac editor does today

```bash
# 1. by hand, interactive — no installer covers these
tailscale up
ssh-keygen -t ed25519 -f ~/.ssh/ccsync_ed25519
#    → send the .pub to the admin, who runs server/setup_editor_account.py

# 2. download the script from the dashboard ([ INSTALLER ] → /download), then
DASHBOARD_TOKEN=<token> bash ccsync-onboard-*.sh \
    --tailnet-host 100.71.216.3 --editor-name <name> \
    --local-root "/Volumes/<SSD>/Creators_Club"

# 3. sign in from the tray — nothing syncs until this happens
```

Three manual steps plus a Terminal command, against one double-click on
Windows.

### Why the two missing gates matter

They are the two that have caused the worst support incidents:

- **The credential gate** is what stops an install under a bogus identity.
  Per `docs/SERVER.md:338`, a machine that never signs in gets 401 on every
  report and **never appears on the fleet grid** — installed, running, and
  invisible. `require_login` gates the lanes on the same thing, so it also
  isn't syncing.
- **The connection test** catches "Tailscale isn't up" *before* an install
  that otherwise appears to succeed and then silently moves nothing.

### Options

**A — port the wizard (proper fix).** `onboard.py` (tkinter) is already
cross-platform; the work is all underneath it. `steps.py` grows a darwin
branch that calls `macos_bootstrap.sh` instead of `windows_bootstrap.ps1`,
and the clean-slate phase needs a macOS analogue (LaunchAgent unload, old
binary removal — there is no drive to unmount). Built with PyInstaller on a
Mac, as a second artifact. Note it would be a `.app` or a bare binary, and
would hit the same quarantine/Gatekeeper questions the companion does.
Rough size: days, not hours, and it cannot be tested without a Mac.

**B — add the two gates to the shell script (cheap middle).** Give
`macos_bootstrap.sh` a `POST /api/v1/verify` gate that refuses to continue on
a bad credential, and a tailnet health check against
`GET /api/v1/health` before it does anything. Editors still use Terminal, but
they can no longer install under an unverified identity or onto a machine
with no tailnet route. Rough size: an afternoon, and testable on the one Mac.

**C — do nothing yet.** Defensible while there is exactly one Mac editor and
the admin is present for the install. Stops being defensible at the second
Mac.

**DECIDED, same day: option A, and it is implemented** — see the update
banner at the top. The clean-slate got its macOS analogue
(`steps.build_cleanup_plan_macos` / `execute_cleanup_macos`: LaunchAgent
bootout, our-processes-only kill, old-binary removal, nothing to unmount),
`steps.py` grew darwin branches throughout, and both gates now apply to Mac
installs because they live in the shared wizard flow. The remaining work is
exactly the predicted kind: build it on a Mac
(`tools/build_onboard_macos.sh`, after §6's A8) and survive Gatekeeper.
Option B's two gates were NOT separately added to the standalone Terminal
script — the script still trusts `--editor-name` when run by hand; the
wizard is the gated path.

---

## 3. What was fixed on 2026-08-04 (commit `c725256`)

Five defects from the first Mac run, four in code or test infrastructure
never exercised on any host. Full write-up in
`docs/macos-first-run-2026-08-04.md`; summary in `installer/README.md`.

- **MAC-1, critical** — a UTF-8 BOM on `companion/pyproject.toml` made
  `pip install -e .` impossible, so no Mac build could be produced at all.
  Introduced by the 0.4.20 bump itself. Not macOS-only: it also broke
  `test_version_matches_pyproject` on **every** host, so `main` was red
  everywhere and nobody knew — Windows never installs the package
  (`release.ps1` only *locates* a venv) and every other Windows reader of
  pyproject parses it with a regex. Now guarded by a test that binary-loads
  every `pyproject.toml` in the repo.
- **MAC-4, major** — the rclone test fixture looked for `rclone.exe`, so the
  24 tests proving lane A is up-only and lane B is down-only skipped silently
  on every Mac while pytest still exited 0. Fixture is platform-aware and
  consults `~/.local/ccsync/bin/rclone`; `CCSYNC_REQUIRE_RCLONE=1` (set by
  both release scripts) makes an absent rclone fail rather than skip.
- **MAC-3** — `resolve_bridge._norm_path` and popup's basename fallback used
  the host's `os.path` on canonical `P:\` strings; posix folds nothing and
  `basename` returns the whole string. Silently disabled the popup dedupe and
  the duplicate-`ReplaceClip` guard behind it. Both route through
  `canon.plat_for()` now.
- A drive-rooted `dest_rel` (`C:/Windows/Temp`) passed the containment check
  on posix, where it is an ordinary relative join.
- **D5** — the Resolve mapping helper kept the trailing `/Volumes` entry last
  in `config.dat` but not `.config.data`, contradicting its own docs; and its
  atomic save silently re-owns a root-owned `.config.data`. Fixed and warned
  about respectively.

Also fixed alongside, from a live lane-B investigation the same day:
`build_filter_rules_down()` had no exclusion for Resolve's in-progress render
sidecars, so a growing 2.3 GB `.tmp` was re-downloaded to an editor on three
consecutive passes. `.tmp`/`.lock`/`.partial` now excluded ahead of the Proxy
includes.

---

## 4. The Mac

`liaoshaoxuandeMacBook-Pro` — Apple silicon (arm64), macOS 15.7.4 (24G517),
tailnet `100.66.62.41`, owned by `leso`. SSH is open and the machine is fully
scriptable; **credentials are not recorded in this repo** — see the operator's
own notes.

State on it right now:

- `/Users/leso/resolve-remote-sync` @ `c725256`, clean tree
- `companion/.venv` — uv-managed CPython **3.12.13** (the system python is
  3.9.6 and python.org's is 3.11.0; both are below the `>=3.12` floor, so a
  uv-managed 3.12 was installed and symlinked at `~/.local/bin/python3.12`).
  Homebrew is **not** installed on this machine
- `companion/dist/ccsync-companion` — the built artifact
- `~/.local/ccsync/bin/` — rclone 1.75.0 and syncthing, from the 13:43
  partial bootstrap
- `~/.ccsync/config.toml` — seeded, with `local_root =
  /Users/leso/Creators_Club` (the **internal** disk — see §5)
- Two `syncthing serve` processes running; the Syncthing LaunchAgent exists
  but is **not loaded**
- The companion has never been installed and has never run
- Resolve **21.0.0**, direct build (not App Store), so preferences are in
  `~/Library/Preferences/…`, not a sandbox container

Anything that is pure compute can be driven remotely — the full test suite,
`release_macos.sh` (build/sign/manifest; ad-hoc signing needs no keychain
unlock), the mapping helper in `verify` mode. Anything needing a GUI session
cannot: the menu-bar smoke run, TCC permission prompts, the Resolve restart
check, and physically unplugging the SSD. `--publish` reads the dashboard
password from a TTY, so it needs either a PTY or a direct `PUT` with a minted
session cookie.

---

## 5. Blockers and decisions needed

1. **The onboarding gap** — ~~option A, B or C from §2~~ **answered: A,
   implemented** (see the top banner). What remains of it is a build task,
   not a decision: run `tools/build_onboard_macos.sh` on the Mac after A8.
2. **Which drive, and which filesystem, for the SSD drills (E1–E4).** These
   are the point of the port and are currently **inert**: `local_root` is the
   internal disk, so the root guard can never fire. The only external volume
   on the Mac is `/Volumes/SAMDISK`, which is **ExFAT** and already holds
   unrelated project material. ExFAT has no POSIX permissions and no
   symlinks, which is a poor fit for a sync root. Needs a real answer before
   E means anything.
3. **Publish before or after the smoke run?** Recommendation: after.
   Publishing points every Mac editor's upgrade channel at a binary whose
   tray has never been seen to start. If pystray's AppKit run loop deadlocks
   against Tk (**B1**, still open), that ships a companion with no visible
   interface and no way for an editor to sign in.

---

## 6. Next steps, in order

Each is blocked by the one above it.

1. **A7 — menu-bar smoke run.** Launch
   `/Users/leso/resolve-remote-sync/companion/dist/ccsync-companion` from
   Terminal on the Mac and watch: does a menu-bar icon appear, and does a
   dialog open without deadlocking? Two minutes, needs a human, answers
   **B1**. **This is the next thing to do.**
2. **A8 — publish**: ~~`./tools/release_macos.sh --publish --make-current`~~
   **DONE 2026-08-04**, out of order (before A7 — see §1's update note):
   0.4.20 published and CURRENT via the minted-cookie direct PUT, exact
   manifest bytes.
3. **Build the wizard** (new, 1.0.17): `./tools/build_onboard_macos.sh` on
   the Mac — it bundles `companion/dist/ccsync-companion`, so it comes after
   the release build. Then double-click `CCSync Onboarding.app` once,
   supervised: Gatekeeper behavior, Tk 9.0 rendering, and the full
   wizard-driven install are all unvalidated. Once it looks right, re-run
   with `--publish --make-current`: that fills the `macos`/`onboard` slot
   with the zip, and from then on a Mac's `[ INSTALLER ]` click downloads
   the wizard instead of the Terminal script.
4. **C1–C7 — the install drill**, on a machine that has not been hand-primed.
   The current Mac has a half-finished bootstrap on it; wipe that first
   (`macos_uninstall.sh --full`) or the drill proves nothing. Prefer driving
   it through the wizard (previous step) — same bootstrap underneath, plus
   the credential and connection gates.
5. **B2 — what path spelling does Resolve on macOS return?** Canonical
   `P:\…`, or Mapped-Mount-resolved `/Volumes/…`? No longer blocking (the
   MAC-3 fix is safe either way, since `plat_for` picks `ntpath` only for
   drive-rooted or backslash-bearing strings) but it decides whether the
   popup/fixer layer is doing real work or a no-op on that host.
6. **D1–D6 — the Resolve mapping write**, then quit and relaunch Resolve and
   confirm it survives. Diff both backups. Expect the new ownership warning
   on `.config.data`; record whether Resolve minds.
7. **E1–E4 — the SSD drills.** Blocked on decision 2 above.
8. **F1–F5 self-upgrade, G1–G3 caffeinate, H1–H5 uninstall.**

Only after E–H should `KNOWN_BUGS.md` item 8 or the `installer/README.md`
status block be softened further.

### Read-only facts already banked, so nobody re-derives them

From reading the live preference files on 2026-08-04 (nothing was written):

- `config.dat` — `Site.1.FS.Count = 2`, entries **1-based**, all `MappedRoot`
  blank, `MacDIO = 1` on both, `/Volumes` auto-entry **last**, as the code
  expects.
- `.config.data` — `IoFsNum = 1`, **1-based**, and carries **no `/Volumes`
  entry at all**. The helper now handles both shapes symmetrically.
- `.config.data` is owned by **root**, mode 666, while `config.dat` beside it
  is owned by the user. The atomic save preserves mode but not ownership.
- PyInstaller rewrites the output's macOS SDK version (26.2.0 → 15.5.0 to
  match the Python library). Informational; record it if anything downstream
  behaves oddly.
- Tcl/Tk is **9.0** under the uv-managed 3.12.13, not the 8.6 the checklist
  assumed. A `--onefile` PyInstaller build of a minimal tkinter app opened a
  real window and exited cleanly, so Tk collection works — this does **not**
  pre-answer B1, which is about coexistence with pystray's run loop.
