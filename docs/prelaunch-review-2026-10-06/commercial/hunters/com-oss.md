# Pre-launch commercial review: open-source licence compliance (com-oss)

Lens `com-oss`, 2026-10-06, working tree at HEAD 08b40eb plus uncommitted changes. Read-only.

**Covered:**
- The baseline docs: `docs/COMMERCIAL_READINESS.md` item 3/13 claims, `LICENSE`, `docs/legal/{EULA,PRIVACY,THIRD_PARTY_NOTICES}.md`.
- The licence texts bundled into the companion and onboarding builds (`docs/legal/licenses/*`).
- The gate and its inputs: `tools/check_licenses.py` + `license_allowlist.toml`, `companion/build.spec`, `onboarding/*.spec`, every `requirements.lock` head list.
- The images: `dashboard/deploy/Dockerfile`, `dashboard/deploy/sftp/Dockerfile`, `.dockerignore`, `.github/workflows/{image,release-windows,ci,android}.yml`.
- The editor package: `installer/build_editor_package.ps1`, the installer pins.
- The runtime downloaders: `companion` sidecars (`sidecar_tools`, `ytdlp_manager`, `broll_vlm_sidecar` + `broll_vlm/local_models.py`, `music_clap/music_models.py`), `server/install_dashboard_app.py` (Cards snapshot, encoder copy), `dashboard/src/ccsync_dashboard/cli_tools.py`.
- Static JS/CSS/fonts/icons in `dashboard/static`, `broll|music|ytdl/web/static`.
- The Timeline Cards checkout that ships to customer NASes (`E:\Projects\Editing\Resolve\MulticamPipeline`: requirements, `zh_fold*.py`, `cards/page/10-look.js`).

**Probes:**
- Byte-scanned the deployed `%LOCALAPPDATA%\ccsync\tools\yt-dlp.exe`.
- Listed the `broll-vlm` runtime the companion installed on this machine.
- Listed `psycopg2_binary.libs` in the companion venv.
- Read zhconv/pypinyin metadata.

**Not covered:**
- No macOS build was inspected. The `psycopg2-binary` macOS wheel's extra dylibs and the evermeet ffmpeg configure flags are unverified.
- Docker images were not built or scanned.
- No package's actual licence was re-checked upstream beyond its metadata.

**Already fine, not reported:**
- The pip gate, the frozen-build scan and the notices `--check` gate.
- pystray is removed.
- zhconv is kept out of the container.
- bgutil is split into its own lock.
- Fonts ship with their OFL texts.
- htmx is 0BSD.
- The NAS ffmpeg is fetched by the NAS itself.
- Data directories are excluded from the image.
- The three EULA copies are identical.

---

### com-oss-1 - Vendor-published container images carry GPL OS packages with no notice and no source offer
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `.github/workflows/image.yml:10-11,124-128,162-165,210,234`
  - `dashboard/deploy/Dockerfile:41,69-73`
  - `dashboard/deploy/sftp/Dockerfile:29,55`
  - `dashboard/deploy/compose.appliance.yaml:88,147,291`
  - `docs/legal/THIRD_PARTY_NOTICES.md` (no base-image section)
- **What:** CI builds and pushes two images to GHCR, which the appliance compose then pulls.
  - `ghcr.io/<owner>/ccsync` is built on Debian `python:3.12.7-slim`. That base carries bash, coreutils, grep, sed and tar (GPL-3.0+), libreadline8 and libgdbm (GPL-3.0, linked by CPython's own modules), dpkg/apt (GPL-2.0+) and glibc (LGPL).
  - `ghcr.io/<owner>/ccsync-sftp` is built on `alpine:3.20`, which carries BusyBox (GPL-2.0-only) plus `apk add` of openssh, shadow, curl and jq.

  The vendor builds and publishes these images, so the vendor is the distributor (mode A by the notices' own definition). Gaps:
  - `THIRD_PARTY_NOTICES.md` has no section for any OS package in either image.
  - No licence texts for those packages are aggregated anywhere.
  - No written offer covers them.
  - The image label says `org.opencontainers.image.licenses="NOASSERTION"` and `source="https://example.invalid/ccsync"`.
  - The buildx SBOM is attached, but an SBOM is not a source offer.
- **Scenario:** A customer's security or legal reviewer runs `syft`/`trivy` over the pulled image and finds BusyBox and GNU userland with no offer. GPL-2.0 §3(c), "pass along upstream's offer", is not available to a commercial distributor. So the vendor must either ship the source alongside or give a 3-year written offer. BusyBox is the most-enforced GPL codebase there is. The same reviewer sees `NOASSERTION` and a placeholder source URL and reads the vendor as having no compliance process.
- **Recommendation:**
  - Engineering:
    - Generate an OS-package notice per image digest from the SBOM (package, version, licence) and publish it beside the image. Add a "Container images" section to `THIRD_PARTY_NOTICES.md` (hand-maintained block).
    - Retain the corresponding source for each published digest: the Debian source packages for that snapshot date, and the Alpine aports at the tag. A source image pushed beside each release is one way.
    - Set real OCI `licenses`/`source` labels.
    - Consider a distroless or minimal runtime to shrink the GPL surface.
  - Counsel: approve a written offer covering GPL OS components in the images.
- **Known:** not in KNOWN_BUGS or COMMERCIAL_READINESS. Item 12 built the image but never assessed its OS layer.

### com-oss-2 - The CLAP audio tower is published on the vendor feed to every editor with no licence, NOTICE or inventory row
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/RELEASE.md:166-170` (`publish_feed.py --asset music-clap-audio-1.onnx`)
  - `companion/src/ccsync_companion/music_clap/music_models.py:34-40,84-125`
  - `music/web/data/audio_encoder/` (no LICENSE/NOTICE, unlike `text_encoder/`)
  - `docs/legal/THIRD_PARTY_NOTICES.md` inventory + "CLAP ... what actually ships"
  - `music/web/data/text_encoder/NOTICE` ("The audio tower was not exported")
- **What:** `export_audio_encoder.py` exports LAION's `larger_clap_music_and_speech` audio tower to ONNX (280 MB). The release recipe publishes it to the vendor feed on GitHub Releases, and `music_clap_sidecar` downloads it onto every editor machine that ingests music. That is mode A conveyance of a modified Apache-2.0 work. Three gaps:
  - The notices inventory lists only the text tower, and the text tower's NOTICE says the audio tower "was not exported".
  - Nothing ships beside the feed asset: no LICENSE, no NOTICE, no modification statement. Apache-2.0 §4(a), (b) and (d) require a licence copy, a prominent modification notice and any NOTICE content.
  - The two licence statements disagree. `music_models.py` says "Apache-2.0 model code, CC0-1.0 weights"; the notices say Apache-2.0 for the weights.
- **Scenario:** Every customer's editors receive a vendor-redistributed derivative model with no attribution. A buyer's diligence checklist ("list every model you redistribute and its licence") gets an answer from the notices that is factually wrong.
- **Recommendation:**
  - Engineering:
    - Publish `music-clap-audio-1.LICENSE` and `.NOTICE` as feed assets beside the model, and have the sidecar store them next to it.
    - Add an inventory row (mode A, vendor feed) and fix the text tower NOTICE's sentence.
    - Pick one licence statement for the weights, as on the model card, and use it in both places.
  - Counsel (one line in the notes): LAION's training corpus for the music variant includes datasets with their own terms. Ask whether the vendor relies on the model card's licence alone for commercial use.
- **Known:** none.

### com-oss-3 - psycopg2 (LGPL-3.0+) is frozen into the single-file companion: the LGPL/GPL texts are missing, and "replaceable" contradicts the repo's own pystray reasoning
- **Severity:** high
- **Confidence:** CONFIRMED (missing texts, onefile build); PLAUSIBLE (that the replaceability posture fails §4(d))
- **Where:**
  - `companion/build.spec:24-31` (pystray reasoning), `:33-39` (psycopg2 hidden import), `:255-262` (single `EXE`, no `COLLECT`, i.e. onefile)
  - `tools/license_allowlist.toml` `[allow.psycopg2-binary]`
  - `docs/legal/licenses/companion/psycopg2-binary-2.9.13.txt` (57 lines; points at "the doc/ directory")
  - `docs/legal/licenses/companion/THIRD_PARTY_LICENSES.txt`: the only GPL text is GPL-2.0 (line 169, PyInstaller), and there is no "GNU LESSER GENERAL PUBLIC LICENSE Version 3"
  - `docs/legal/THIRD_PARTY_NOTICES.md` "psycopg2 in the companion executable"
  - `docs/legal/EULA.md:51-55,166-172`
- **What:**
  - **(a) Missing texts.** LGPL-3.0 §4(b) requires the combined work to be accompanied by the LGPL-3.0 text and the GPL-3.0 text. Neither is in the licence bundle the exe carries. psycopg2's own LICENSE says "you should have received a copy ... (see the doc/ directory)", and that directory is not shipped.
  - **(b) Replaceability.** `build.spec` removed pystray because "a single-file PyInstaller freeze conveys it with no way for the recipient to relink against a modified copy, which is precisely what LGPL §4 requires". psycopg2 is frozen into the same single-file exe today. Its `.pyd`, `libpq` and OpenSSL are unpacked from inside our signed binary into a fresh temp directory on every launch, so an editor cannot replace them without repacking (and breaking the signature of) our exe. That is not a §4(d)(1) "copy already present on the user's computer system".
  - **(c) EULA scope.** EULA §2(b) bars reverse engineering except "in respect of third-party components". LGPL-3.0 §4 requires that the terms for the Combined Work not restrict reverse engineering for debugging modifications of the library, which is broader than the component itself.
  - Counsel cleared the disclosure on the premise that these are "separate, replaceable shared-library files". The onefile fact undercuts that premise.
- **Scenario:** A customer, or a competitor, asks for the means to relink psycopg2 under LGPL §4. The vendor can produce neither a user-replaceable library nor Minimal Corresponding Source, and the shipped exe lacks the licence texts.
- **Recommendation:**
  - Engineering (now, one line in `tools/notices_extra/` plus regeneration): add the LGPL-3.0 and GPL-3.0 texts to the companion licence bundle.
  - Then choose one of:
    - load psycopg2 from a user-replaceable location first (for example a `psycopg2` override directory under `%LOCALAPPDATA%\ccsync`), with the frozen copy only as the fallback;
    - ship psycopg2 outside the exe;
    - or put a §4(d)(0) offer of the companion's application archive plus build recipe in the notices.
  - Counsel: re-review with the onefile fact and the EULA §2(b) scope in front of them.
  - Also: inspect the macOS build's `psycopg2/.dylibs`. The macOS wheel may carry krb5, libintl and similar libraries the notices do not name.
- **Known:** LEGAL_GAP_FEATURES_PLAN D6, decided "keep it, counsel cleared". That decision did not consider these points.

### com-oss-4 - IP chain of title: the yt-credit-downloader grant is still owed, and the root LICENSE is still a placeholder draft
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:**
  - `ytdl/web/ytdlweb/vendor/PROVENANCE.md:3-7,21-36`
  - `KNOWN_BUGS.md:449-451` (CR-2 "Owed: a written licence grant")
  - `docs/legal/THIRD_PARTY_NOTICES.md` "yt-credit-downloader: the Licensor's own code"
  - `LICENSE:1-13`
- **What:** The counsel-cleared notices say the vendored downloader is "the Licensor's own code". PROVENANCE.md and CR-2 still say no grant exists: the upstream is authored by Alex personally, in the `The-Creators-Club` GitHub org, with no licence. The Licensor named in every legal document is "Cablewrap Creative Ltd.". The root `LICENSE` still opens "DRAFT FOR COUNSEL" with `TODO(legal): replace "Cablewrap Creative" with the registered legal entity name`, which disagrees with the cleared EULA and notices. The same gap applies to the whole codebase, this repo and the separately deployed MulticamPipeline: nothing in the repo records an assignment from the individual author(s) to the contracting entity.
- **Scenario:** A buyer's diligence asks who owns the code being licensed. The licensor's title to the vendored files, and arguably to all of it, rests on an unwritten understanding with an individual author.
- **Recommendation:**
  - Owner + counsel:
    - A signed IP assignment (or exclusive, sublicensable licence) from Alex, and any contractor, to Cablewrap Creative Ltd. It should cover ccsync, MulticamPipeline, yt-credit-downloader and the brand assets.
    - The PROVENANCE grant as specified there.
  - Engineering: finalise `LICENSE` with the real entity details so it matches the EULA, and update PROVENANCE/CR-2 when it is signed.
- **Known:** CR-2 (open, the grant part); COMMERCIAL_READINESS item 3 "still blocking a sale".

### com-oss-5 - The editor-side yt-dlp.exe is a GPL-3.0+ combined binary from the nightly repo, but the notices say "Unlicense" and "stable"
- **Severity:** medium
- **Confidence:** CONFIRMED (mutagen bundled, nightly source); PLAUSIBLE (the exact upstream licence statement)
- **Where:**
  - `companion/src/ccsync_companion/ytdlp_manager.py:66,80-84` (`yt-dlp/yt-dlp-nightly-builds`, CR-361)
  - `docs/legal/THIRD_PARTY_NOTICES.md` inventory row "yt-dlp (editor side) | latest, refreshed daily | Unlicense | GitHub releases"
- **What:** A byte scan of the deployed `%LOCALAPPDATA%\ccsync\tools\yt-dlp.exe` (17.8 MB) shows the following bundled modules:

  | Module | Licence | Hits |
  |---|---|---|
  | `mutagen` | GPL-2.0+ | 48 |
  | `Cryptodome` | BSD/PD | 111 |
  | `curl_cffi` | MIT, bundles curl-impersonate | 31 |
  | `websockets` | BSD | 59 |
  | `certifi` | MPL | 4 |
  | `yt_dlp_ejs` | (not checked) | 6 |

  yt-dlp's own release notes license the frozen executables as GPL-3.0+ because of what they bundle, and ship a THIRD_PARTY_LICENSES file. The notices call it Unlicense and point at the stable releases. Since 2026-10-05 the companion pulls daily from the separate nightly repository. Mode B (fetched by the editor's machine) limits the obligation, but the published notice is wrong.
- **Scenario:** A reviewer compares the notices with what is on an editor's disk, and finds a GPL binary declared as public domain from a source it no longer comes from.
- **Recommendation:**
  - Engineering: correct the row to "GPL-3.0-or-later as a combined binary (yt-dlp code Unlicense); `yt-dlp/yt-dlp-nightly-builds`, refreshed daily". Keep the companion's mode B (never re-hosted).
  - Counsel: note the auto-updating nightly posture in the YouTube notice.
- **Known:** none (CR-361 changed the channel and did not touch the notices).

### com-oss-6 - The notices say llama.cpp and Qwen3-VL "never leave the indexing machine", but the companion installs them, plus NVIDIA's CUDA runtime, on editor machines
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `companion/src/ccsync_companion/broll_vlm_sidecar.py:69-84`
  - `companion/src/ccsync_companion/broll_vlm/local_models.py:214` (`cudart-llama-bin-win-cuda-12.4-x64.zip`)
  - `companion/src/ccsync_companion/broll_ingest.py:57`, `broll_server.py:116,1748-1778`
  - `docs/legal/THIRD_PARTY_NOTICES.md` "Qwen3-VL / llama.cpp: NOT SHIPPED ... never bundled into the companion"
  - On this machine: `%LOCALAPPDATA%\ccsync\tools\broll-vlm\runtime\llamacpp-b10470-windows\{cudart64_12,cublas64_12,cublasLt64_12}.dll`
- **What:** The companion's b-roll ingest path fetches onto editor workstations:
  - the llama.cpp CUDA build;
  - the `cudart-llama-bin` zip (NVIDIA CUDA runtime and cuBLAS, distributed under NVIDIA's proprietary CUDA EULA redistributable terms, not open source);
  - the Qwen3-VL GGUF weights.

  The notices state the opposite, and inventory no NVIDIA component at all. PRIVACY.md, to its credit, already names `broll_vlm_sidecar` as a Hugging Face/GitHub egress, so the two documents disagree.
- **Scenario:** A customer's licence audit finds proprietary NVIDIA DLLs and a 2.5 GB model on editor PCs that the vendor's notices say are never there.
- **Recommendation:**
  - Engineering:
    - Rewrite the row: mode B on editor machines with an NVIDIA GPU, via the companion's b-roll ingest.
    - Add an "NVIDIA CUDA runtime (cudart/cuBLAS), NVIDIA CUDA EULA, fetched from the llama.cpp release" row.
  - Counsel: confirm the end user downloading the NVIDIA redistributables is acceptable under NVIDIA's terms.
- **Known:** none.

### com-oss-7 - Timeline Cards code ships to customer NASes outside every licence document, with unattributed OpenCC data and a runtime Google Fonts fetch
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:**
  - `server/install_dashboard_app.py:542,566-626,950-969` (git-archive snapshot of `Resolve/MulticamPipeline` to `/cards-app` when `[timeline_cards] enabled`)
  - `docs/legal/EULA.md:27-32` ("Software" definition: no Timeline Cards)
  - `MulticamPipeline/multicam_pipeline/zh_fold_table.py:1-20` (4112 pairs "generated from OpenCC's own TSCharacters / TWVariantsRev")
  - `MulticamPipeline/multicam_pipeline/cards/page/10-look.js:23-31` (`fonts.googleapis.com` / `fonts.gstatic.com`)
  - `docs/legal/PRIVACY.md:141-148` (no Google Fonts row)
- **What:** The Cards tree is a separate repository with no LICENSE or NOTICE. It is conveyed to any customer who enables the feature. Gaps:
  - The EULA's definition of the Software does not name it.
  - THIRD_PARTY_NOTICES covers only its psycopg2 use.
  - It embeds a derived OpenCC (Apache-2.0) data table with no attribution or licence copy (Apache §4).
  - Its page makes every viewer's browser load Archivo and Roboto Mono from Google, which is undisclosed third-party egress of the viewer's IP. A German court (LG München I, 2022) awarded damages for exactly this. The dashboard itself self-hosts its fonts with OFL texts.
- **Scenario:** An EU customer enables Cards, and their DPO finds Google requests the privacy policy does not mention. Separately, the customer's licence audit finds OpenCC-derived data with no notice, in code their EULA does not cover.
- **Recommendation:**
  - Counsel: extend the EULA's "Software" definition to Timeline Cards (EULA bump).
  - Engineering:
    - Ship a NOTICE in the Cards snapshot, with the OpenCC Apache-2.0 attribution and licence text.
    - Self-host the two fonts under `/cards` with their licence texts, or fall back to system fonts.
    - Add Cards rows to THIRD_PARTY_NOTICES.
- **Known:** none.

### com-oss-8 - The hand-maintained notices inventory has drifted from the code, and nothing gates it
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/legal/THIRD_PARTY_NOTICES.md` inventory rows "rclone | rclone-current-* (resolved at install time)" and "Syncthing (editor side) | latest release" vs `installer/windows_bootstrap.ps1:329-333` and `installer/macos_bootstrap.sh:79-82` (pinned v1.75.0 / v2.1.3, already listed in the binaries table above it)
  - `dashboard/src/ccsync_dashboard/cli_tools.py:194,203`
  - `dashboard/deploy/compose*.yaml` (`syncthing/syncthing:1.30.0`, `postgres:13`, `tailscale/tailscale`)
- **What:**
  - The inventory contradicts its own binaries table about pinning.
  - It has no rows for the Claude Code CLI (Anthropic proprietary terms, fetched from downloads.claude.ai by the SET UP wizard) or the OpenAI Codex CLI (Apache-2.0).
  - It has no rows for the third-party images the vendor's compose files pull.
  - `gen_notices.py --check` guards only the pip tables. The ffmpeg section's maintainer comment ("a written offer that names the wrong build is not an offer") has no test behind it.
- **Scenario:** Each release, a pin moves and a cleared legal document silently goes stale. com-oss-5 and com-oss-6 are two instances already.
- **Recommendation:** Engineering:
  - Fix the rows and add the missing ones.
  - Add a tools test that reads every pin from its source module (`sidecar_tools`, `ytdlp_manager`, `broll_vlm/local_models`, installers, compose image tags, `install_dashboard_app` ffmpeg) and asserts that THIRD_PARTY_NOTICES names it.
- **Known:** none.

### com-oss-9 - The dashboard container has no aggregated licence-text bundle, unlike the companion and wizard
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:**
  - `docs/legal/licenses/` (only `companion/`, `onboarding/`)
  - `.dockerignore` `!docs/legal/licenses/**/*.txt`
  - `tools/gen_notices.py --write-texts`
- **What:** The companion and onboarding builds carry a generated THIRD_PARTY_LICENSES.txt that /help can serve. The container's ~100 pip packages have their texts only inside `/venv/.../dist-info`, which is technically present but never shown. Neither the OTA bundle nor /help lists them. Many MIT/BSD licences require the notice to accompany "all copies".
- **Scenario:** A customer admin opens /help → licences and sees the companion's list, not the list for the software running on their NAS.
- **Recommendation:** Engineering: extend `--write-texts` to the `dashboard-container` target, write `docs/legal/licenses/dashboard/THIRD_PARTY_LICENSES.txt`, and publish it through `published_docs`. Combine with com-oss-1's OS-package notice.
- **Known:** none.

### com-oss-10 - The Android TWA APK has no licence or notice coverage
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:**
  - `.github/workflows/android.yml`
  - `tools/android/build_apk.sh`
  - `docs/ANDROID.md`
  - `docs/legal/*` (no APK mention)
- **What:** The vendor's CI builds a Bubblewrap TWA for a studio to sideload. A Bubblewrap project links android-browser-helper and androidx (Apache-2.0), which need their licence and NOTICE carried. Neither the app nor the legal set mentions it, and the EULA's Software definition does not include it.
- **Scenario:** The APK handed to a customer studio carries no attribution.
- **Recommendation:**
  - Engineering: add an APK row to the notices, and an "Open-source licences" link (the dashboard's /help licences page is enough, since the TWA renders it).
  - Counsel: include the Android app in the EULA's Software definition.
- **Known:** none.
