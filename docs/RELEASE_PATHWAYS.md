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
   exists. Since 2026-09-25 (logic-release-6) the recovery no longer needs
   the original bytes: `publish_latest.py --make-current` on a version
   already staged with the same bytes moves the pointer alone, and when a
   newer green run has rebuilt that version with different bytes it prints
   the `publish_feed.py --set-current KIND/PLATFORM/VERSION ...` line that
   makes the STAGED record current. `publish_latest --force` is still the
   wrong tool: the feed rightly refuses different bytes under one version.
5. **The dashboard does the rest.** This site's `site.toml` has `[releases]
   policy = "current"`: the feed poller picks the release up and publishes +
   makes it current with no click. Editors' companions then self-upgrade.
   The poll interval defaults to DAILY (`release_feed_interval`); a
   `docker restart` of the dashboard container triggers a check 10 s
   after boot when you need it now.
6. **Verify**: `.\tools\check_deploy_drift.ps1`, or the dashboard's
   `[ CURRENTLY SERVED ]` box.

**The trap that costs a build cycle:** the *latest green run* is whatever CI
last built — if the version bump landed **after** that run, publishing now
would sweep an artifact of the *previous* version (harmless — already
published, it skips) or worse, an artifact stamped with the new version but
missing later commits. Dispatch a **fresh** run after the bump lands and
publish that. (Two different trees must never both call themselves 0.9.x —
that is the drift RELEASE.md opens with.)

**One command for a customer release (GL-24, CR-371, 2026-10-07):**
`python tools/release_customers.py` (`--dry-run` first). From ONE green commit
it verifies `ci.yml` plus the three release workflows on that exact commit,
tags `v<VERSION>`, waits for `image.yml` (smoke test, then the
`customer-release` environment approval), publishes the dashboard bundle with
`--make-current --set-image <tag>@<digest>` in a single channel write, then the
companion and both installers through `publish_latest.py --sha`, and pins
`compose.appliance.yaml` by digest. `publish_latest.py` on its own now also
refuses a commit with no green `ci.yml` run (`--allow-red-ci` for a hotfix) and
stamps the downgrade floor from `tools/release_floor.json` (see RELEASE.md).
`tools/check_feed_freshness.py` (nightly, `feed-freshness.yml`) fails when the
customer channel trails main. The beta ships UNSIGNED binaries (GL-26 is
deferred): nothing here refuses that, but the record signature with the
offline key stays mandatory. One-time repo setup the owner does in GitHub:
create the `customer-release` environment with a required reviewer, and (for
the freshness check) a `FEED_READ_TOKEN` secret.

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

## First delivery of the CLI lock to the studio (GL-31 / CR-374, 2026-10-07)

The CR-374 dashboard boots with the Claude Code and Codex providers LOCKED
unless the container environment carries `DASH_STUDIO_CLI_PROVIDERS=1`. An
over-the-air bundle, the vendor feed, Settings > Packages "Update now" and
`policy = current` all keep the container's OLD environment, so the first
CR-374 build to arrive that way would strand the studio: Timeline Cards' AI
(no API key here), the YouTube downloader's AI and the server check go dark.
Do this first, once: put `[studio] allow_cli_providers = true` in the
studio's site.toml and deploy through `server/install_dashboard_app.py`
(`tools\ship.cmd`), and only then let any OTA path carry the build (hold it
off `--make-current` until then). If it happens anyway, the dashboard says so:
the notice `cli_lock_stranded` (PROBLEMS THE SERVER FOUND) names the fix.
Details: `docs/STUDIO_BUILD.md`.

## The studio reads the customer channel too (GL-24 / CR-371, 2026-10-07)

`ship.cmd` publishes to the studio's own dashboard only, which is how the
studio never exercised the channel customers read (COM-H8, PRAC-9). The move
is configuration, not code: point the studio's own dashboard at the vendor
feed so every build it runs reached it the way a customer's does.

1. The feed half is already in place on the live studio: its `site.toml` has
   `[releases] feed_url` at the vendor feed (`vendor_defaults.VENDOR_FEED_URL`),
   `policy = "current"` and the vendor public key. A new studio does the same
   (`DASH_RELEASE_PUBKEYS` = the key customers trust) and deploys through
   `server/install_dashboard_app.py`. What is left is the soak route below.
2. What policy moves. Companion and onboard records reach the studio through
   `_apply_policy`. The DASHBOARD bundle also arrives over the air:
   `check_now` calls `apply_dashboard_policy`, and on an image-mode site with
   `policy = "current"` it applies the bundle the channel's signed current
   pointer names once `soak_minutes` has passed (pinned by
   `test_release_feed.py`; see the CR-374 section above). So the studio can
   run a release by the same road a customer does.
   The soak is earned there: `release_customers.py`'s soak check runs BEFORE it
   tags and publishes, and needs the studio's health `code.commit` to equal the
   release sha for `--soak-hours`. The live studio is IMAGE mode (`[stack] mode
   = "image"`, image pinned by digest), so `ship.cmd` / `-DashboardOnly`
   deploys NO dashboard code there ("image mode: nothing to deploy from here"):
   do not use it for this. Routes that work in image mode:
   a. Publish the dashboard bundle STAGED to the vendor feed
      (`publish_feed.py --kind dashboard`, no `--make-current`; the CI gate does
      not block a staged publish) and apply it on the studio with Settings >
      Packages > Update now. Let it run 24 h, then `release_customers.py`.
      The bundle MUST be the exact CI artefact: `gh run download <the
      release-dashboard.yml run for the release commit> -n
      ccsync-dashboard-bundle`. Its manifest carries `built_at`, so a local
      build, or the same workflow re-run afterwards, has other bytes, and
      `release_customers.py` refuses (before tagging) when the channel already
      holds that version with different bytes. Do not re-run the workflow.
   b. Or set `[stack] image` to image.yml's `:<short-sha>` build of the release
      commit and re-run `install_dashboard_app.py` (`--container-image` /
      `$CCSYNC_IMAGE` win over it if set).
   If the release needs a NEW RUNTIME (image contents, not just code), route a
   cannot work: a bundle cannot be applied over the air onto an older runtime,
   and the `v*` tag that builds the customer image is only pushed by
   `release_customers.py` AFTER the soak. Use route b for those. Without a
   soaked studio the gate refuses and only `--allow-no-soak` gets past it;
   that is the habit the soak exists to prevent.
3. `ship.cmd -Publish -MakeCurrent` conflicts with `policy = "current"`: on
   the next poll the studio sees the feed's current companion version in its
   store but not marked current and makes it current again, undoing every
   local ship. Pick one. Either leave the studio on `policy = "stage"` (it
   stages the feed's records and a human or ship.cmd decides what is current),
   or, on `current`, do not use `ship.cmd` for the dashboard at all (in image
   mode `-DashboardOnly` deploys nothing, see step 2: use route a or b there)
   and let the feed move the companion pointer.
   Route b soaks the `:<short-sha>` image from the push to main; the `v*` tag
   rebuilds the same commit, so the digest customers are pinned to is a
   sibling build, not the very digest the studio ran (same base digest and
   hash-locked deps, but not byte-identical).
4. Keep the live studio working through the change: do it on a quiet day,
   confirm Packages shows the feed as checked with no error, and only then
   rely on it for the soak.

Not done by code: changing the live studio's config is the owner's act (it
alters what the studio fleet is offered). The companions follow the studio
dashboard's current package, so they move with step 1.

## Neither pathway is "the dashboard's own code"

Dashboard code ships separately (image mode: the CI image via a `v*` tag, or
an over-the-air bundle) and Timeline Cards ships separately again
(`install_dashboard_app.py` re-ships `[timeline_cards] src` → `cards-web`
even in image mode). Neither is a companion release; do not reach for these
tools to "publish the companion" or vice versa.
