# RELEASE_PATHWAYS.md — the two ways a companion build reaches the fleet

**Read this before starting a release.** It answers one question in one
screen: *which publish pathway applies right now?* The step-by-step detail
stays where it always was — [RELEASE.md](RELEASE.md) for the ship run,
[RELEASE_FEED.md](RELEASE_FEED.md) for the feed — this page only routes you.

## Why this file exists

**2026-08-31.** Asked to "publish the latest companion version", a Claude
session reconstructed the ship from RELEASE.md and got all the way to the
blocker: `ship.cmd` (via `build_editor_package.ps1 -Publish`) asks for the
dashboard admin password with `Read-Host` — deliberately never argv, never the
environment — so an unattended session cannot run it. The direct pathway
(CI build → `publish_latest.py` → the vendor feed, no password anywhere) had
already shipped 0.9.61 the day before, but nothing named it as *the*
autonomous route, so half an hour went to rediscovering it. This file is that
half hour, written down.

## The two pathways

| | **A: the ship** (`tools\ship.cmd`) | **B: CI + the feed** (`tools/publish_latest.py`) |
|---|---|---|
| who runs it | **Alex, at the terminal** — the dashboard password prompt is interactive by design (SEC-2) | **anyone/anything on the base rig** — Claude included; no password exists in this path |
| builds where | this rig (release.ps1 → PyInstaller) | GitHub hosted runners (`release-windows.yml`, `release-macos.yml`) |
| platforms | Windows companion + `onboard.exe` only | **all four**: win/mac × companion/onboard |
| publishes to | ONE dashboard directly (PUT, admin session), staged + make-current | the public vendor feed (`ccsync-releases`); every dashboard takes it per its `[releases] policy` |
| this rig upgraded? | yes, step 3, plus the drift check | no — the companion's own upgrade channel does it after the dashboard flips |
| credentials | `load_secrets.ps1` (TRUENAS_PW etc.), `CCSYNC_DASHBOARD_URL`, `CCSYNC_ADMIN_USER`, **the dashboard password typed at a prompt** | `gh auth login` (already done on this rig) + the offline release key at `~/.ccsync-release/release.key` |
| signing | Authenticode gate on the exe (`-AllowUnsignedBinary` while no cert is configured — every ship so far) | the same, in the workflow; plus every feed record is Ed25519-signed by the release key |

Both refuse to reuse a published version number, and both stand on the same
version-bump rules (RELEASE.md "Where versions live": companion = **2**
files, installer = **4**).

## Pathway B, start to finish (the autonomous one)

1. **Confirm the bump is committed and pushed** — the workflows build
   `main`'s tip, and `publish_latest.py` refuses a run whose commit is not an
   ancestor of `origin/main` (release-pipeline-7 / REL-14).
2. **Dispatch the builds** (they are `workflow_dispatch` only — a push
   builds nothing):
   ```
   gh workflow run release-windows.yml --ref main     # ~36 min
   gh workflow run release-macos.yml  --ref main      # ~7 min
   ```
3. **Wait for green.** `gh run watch <id> --exit-status`.
4. **Publish**: `python tools/publish_latest.py --make-current` (add
   `--dry-run` first if unsure). It downloads the newest green artifacts,
   verifies manifests (refusing `git_dirty` / `tests_run: false`), signs
   each record with the release key, and uploads channel + artefacts to
   `The-Creators-Club/ccsync-releases` with your `gh` login.
   **`--make-current` on the FIRST publish, not later** (learned
   2026-08-31): without it the records land STAGED, and a dashboard on
   `policy = "current"` offers only what the channel's signed `current`
   pointer names — staged records are simply not offered while a pointer
   exists. And the flag cannot be added after the fact through
   `publish_latest --force`, because a newer green run has usually
   rebuilt the same version with different bytes, which the feed rightly
   refuses; the recovery is a SAME-BYTES republish per record (download
   each record's original run artifact, `publish_feed.py --manifest …
   --make-current`), one at a time — sequential, the channel is
   read-modify-upload.
5. **The dashboard does the rest.** This site's `site.toml` has `[releases]
   policy = "current"`: the feed poller picks the release up and publishes +
   makes it current with no click. Editors' companions then self-upgrade.
   The poll interval defaults to DAILY (`release_feed_interval`); a
   `docker restart` of the dashboard container triggers a check 10 s
   after boot when you need it now.
6. **Verify**: `.\tools\check_deploy_drift.ps1`, or the dashboard's
   `[ PUBLISHED PACKAGES ]` box.

**The trap that costs a build cycle:** the *latest green run* is whatever CI
last built — if the version bump landed **after** that run, publishing now
would sweep an artifact of the *previous* version (harmless — already
published, it skips) or worse, an artifact stamped with the new version but
missing later commits. Dispatch a **fresh** run after the bump lands and
publish that. (Two different trees must never both call themselves 0.9.x —
that is the drift RELEASE.md opens with.)

**What B deliberately does not sweep:** the dashboard bundle. That release
stays a two-step (`build_dashboard_bundle.py` → `publish_feed.py --kind
dashboard --runtime-id …`) because the runtime id must be read out of the
tarball — see `publish_latest.py`'s SOURCES comment.

**Why B must never move into CI:** the release key signs what every
companion trusts and runs at logon. CI builds; this rig signs. Owner's call,
2026-08-19 — the go/no-go staying human (or at least local) is a feature.

## Pathway A, when to prefer it

Alex at the terminal wanting the tight loop: gates, local build with both
suites, direct publish to this dashboard, **this machine upgraded in the same
run**, drift check at the end. Also the only path that exercises the staged →
soak (REL-1) → make-current machinery interactively. One command:

```
.\tools\load_secrets.ps1
.\tools\ship.cmd -AllowUnsignedBinary
```

(`-Resume` continues a ship the soak gate stopped; the journal is
`tools\.ship-state.json`.)

## Neither pathway is "the dashboard's own code"

Dashboard code ships separately (image mode: the CI image via a `v*` tag, or
an over-the-air bundle) and Timeline Cards ships separately again
(`install_dashboard_app.py` re-ships `[timeline_cards] src` → `cards-web`
even in image mode). Neither is a companion release; do not reach for these
tools to "publish the companion" or vice versa.
