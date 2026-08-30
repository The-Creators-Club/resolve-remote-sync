# ANDROID.md -- the CC Sync app on an editor's phone

For a studio admin. Written 2026-08-30 alongside `docs/MOBILE_PLAN.md` §4 M5.
The browser side (install from Chrome, what polls, what works offline) is
`docs/MOBILE.md`; this document is only the APK.

## 0. "The app shows a URL bar"

That is the symptom you will meet, and it is the only one this whole document
exists for. The app opens, everything works, and there is a browser address
bar across the top with the site's URL in it. It means Chrome could not verify
that this site vouches for this app, so it fell back to a Custom Tab. Nothing
on the phone and nothing in the dashboard says so.

It is always one of four things:

1. **The site serves no statement.** Open Settings -> ANDROID and press
   `[ CHECK ]`. If it says `[ EMPTY ]`, paste the package name and the
   fingerprint (§3) and save.
2. **The fingerprint is the wrong one.** The APK you installed was signed with
   a different key from the one whose fingerprint you pasted -- most often a
   debug build from CI (its key is thrown away and regenerated on every run)
   against a release fingerprint, or the other way round. Rebuild, or paste
   the fingerprint the build actually printed.
3. **The origin does not match.** The app is bound to ONE origin, baked in at
   build time (`host` in `twa-manifest.json`). If you built against
   `https://nas.example.ts.net` and then moved the dashboard to
   `https://nas.example.ts.net:9443`, the app checks the old one. Rebuild.
4. **The origin is not reachable, or not https.** Asset links are fetched over
   https by Chrome itself, from the phone. If the phone is off the tailnet, or
   the certificate is not valid, verification fails the same silent way.

After a fix: force-stop the app, or reinstall it. Chrome caches the
verification result and the statement (`max-age=3600`), so it does not
re-check on every launch.

## 1. What you need first

* **https.** A TWA cannot be built or verified against a plain-http origin.
  The studio path today is a `tailscale serve` line on the NAS; see
  `docs/MOBILE.md` and MOBILE_PLAN.md §M6. Set `dashboard_url` in Settings to
  that URL once it exists -- the `[ CHECK ]` panel prints Google's own checker
  URL from it.
* **The PWA works first.** Open the URL in Chrome on the phone, sign in, and
  use it. The app is a wrapper around exactly that; if the browser version is
  wrong, the app will be wrong in the same way.
* **A build machine, or CI.** Building an APK needs a JDK and the Android SDK.
  The base rig has neither. Two routes, below.

## 2. Build the APK

### On CI (no local toolchain)

    gh workflow run android.yml -f origin=https://nas.example.ts.net:9443 -f serve_fixture=false

`workflow_dispatch` only -- an APK is a decision, not a consequence of a push.
(GitHub only offers a dispatch for a workflow that is already on the default
branch, so this works once the branch has merged.) Inputs:

| input | meaning |
|---|---|
| `origin` | the https origin the app is bound to. Cannot be changed later without a rebuild. |
| `package_name` | the application id. Blank derives one from the origin: `nas.example.ts.net` -> `net.ts.example.nas.ccsync`. Stable for a given host, which matters: changing it makes a DIFFERENT app that cannot update the installed one. |
| `serve_fixture` | leave `true` to build against `tools/android/fixture/` (this is how the workflow proves itself; a GitHub runner cannot reach a tailnet). `false` for a real build against a reachable origin. |

The run summary prints the package name and the SHA-256 fingerprint. The
artefact `ccsync-android` carries the APK (sideload this), the AAB (the Play
Store's input, later) and the `twa-manifest.json` the build used.

**Signing.** With none of the four secrets set, the job generates a throwaway
DEBUG key and says so in the summary. That APK installs and runs, and it must
never be handed to a studio: its fingerprint is different on every run, so no
installed copy can ever be updated. For a real build set:

    CCSYNC_ANDROID_KEYSTORE_BASE64      the .keystore file, base64'd
    CCSYNC_ANDROID_KEYSTORE_PASSWORD
    CCSYNC_ANDROID_KEY_ALIAS
    CCSYNC_ANDROID_KEY_PASSWORD

The keystore itself never goes in the repo, and neither does a password.
Losing it means every editor uninstalls and reinstalls, so back it up
somewhere a lost laptop does not take with it.

### On a laptop with node

    CCSYNC_ANDROID_KEYSTORE=~/keys/ccsync.keystore \
    CCSYNC_ANDROID_KEYSTORE_PASSWORD=... \
    CCSYNC_ANDROID_KEY_ALIAS=ccsync \
    CCSYNC_ANDROID_KEY_PASSWORD=... \
    tools/android/build_apk.sh https://nas.example.ts.net:9443

The script writes `twa-manifest.json` with
`tools/android/twa_manifest.py` (Bubblewrap's `init` is interactive; a script
cannot answer it, and the answers are the same every time for this product),
then runs `bubblewrap update` and `bubblewrap build --skipPwaValidation`.
`--skipPwaValidation` because the origin is normally on a tailnet, which
Google's Lighthouse service cannot reach -- the manifest and the icons are
still fetched by Bubblewrap, so a wrong origin fails here rather than on a
phone.

It needs a JDK and the Android SDK. Either export `JAVA_HOME` and
`ANDROID_HOME` and it writes `~/.bubblewrap/config.json` for you, or run
`npx @bubblewrap/cli doctor` once interactively and let Bubblewrap install
its own.

## 3. Paste the fingerprint

Dashboard -> Settings -> ANDROID:

* **PACKAGE NAME** -- what the build printed as `package:`.
* **SHA-256 CERT FINGERPRINTS** -- what it printed as `fingerprint:`, one per
  line. 32 colon-separated hex pairs. A leading `SHA256:` label is stripped
  for you; anything else that is not 32 pairs is refused rather than saved
  half-right.

`[ SAVE ]`, then `[ CHECK ]`. It reads back exactly what
`/.well-known/assetlinks.json` is serving:

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "net.ts.example.nas.ccsync",
      "sha256_cert_fingerprints": ["AA:BB:...:FF"]
    }
  }
]
```

Until BOTH a package name and at least one fingerprint are saved, the route
answers `[]`. That is deliberate: half a statement verifies nothing, and
serving one would make a broken setup look configured.

**Keep the old fingerprint while you hand over to a new key.** Both may be
listed at once. Dropping the old one mid-rollout breaks every copy still on
the old build.

## 4. Verify

From anywhere that can reach the site:

    python tools/android/check_assetlinks.py https://nas.example.ts.net:9443 AA:BB:...:FF

Exit 0 the fingerprint is there, 1 it is not, 2 the site could not be reached.

Google's verifier is the one that actually decides. It needs a publicly
resolvable name, so it cannot see a tailnet origin -- but if your origin IS
public, the `[ CHECK ]` panel prints the URL to open:

    https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=<origin>&relation=delegate_permission/common.handle_all_urls

The dashboard never calls it itself: the container runs one worker, a
self-request from inside a request handler is a deadlock, and a check that
silently failed open would be worse than no check at all.

## 5. Install it on a phone

Sideload, for now (a Play Store listing is its own document; the AAB the
workflow uploads is its input):

1. Copy the APK to the phone, or open the artifact link on it.
2. Settings -> Apps -> the browser or file manager -> allow installing unknown
   apps, once.
3. Open the APK, install, launch.
4. No URL bar: done. A URL bar: §0.

The first launch signs in through the normal login page and keeps the session
in Chrome's own cookie jar, which is why the fallback is a Custom Tab and not
a WebView -- a WebView has a separate jar, so the editor would be signed out
inside their own app.

## 6. What is where

| path | what |
|---|---|
| `dashboard/src/ccsync_dashboard/android.py` | the `/.well-known/assetlinks.json` route and the two settings routes |
| `dashboard/templates/partials/android_settings.html` | the Settings -> ANDROID panel |
| `tools/android/twa_manifest.py` | writes Bubblewrap's `twa-manifest.json` from the live web app manifest |
| `tools/android/build_apk.sh` | the build, the keystore from the environment, the fingerprint |
| `tools/android/check_assetlinks.py` | is this fingerprint in that site's statement |
| `tools/android/fixture/` | the manifest and icons CI builds against |
| `.github/workflows/android.yml` | the CI build |
| `dashboard/tests/test_android.py` | all of the above |

The two settings are ordinary site-manifest fields
(`android.package_name`, `android.sha256_cert_fingerprints`), so Export,
Import, the change history and `[ UNDO LAST IMPORT ]` all carry them. They are
deliberately NOT in `GET /api/v1/site`: no installer, companion or indexer has
any use for the app's identity, and the one client that does -- Chrome -- reads
it from the asset-links route in the shape Google defines.
