#!/usr/bin/env bash
# Build the CC Sync Android app (a Trusted Web Activity) from a dashboard
# origin -- MOBILE_PLAN.md §4 M5, 2026-08-30.
#
#   CCSYNC_ANDROID_KEYSTORE=/path/to/release.keystore \
#   CCSYNC_ANDROID_KEYSTORE_PASSWORD=... \
#   CCSYNC_ANDROID_KEY_ALIAS=ccsync \
#   CCSYNC_ANDROID_KEY_PASSWORD=... \
#   tools/android/build_apk.sh https://nas.example.ts.net:9443 [package.id] [outdir]
#
# NO KEYSTORE, NO PASSWORD, EVER IN THE REPO. The four variables above are the
# only way in; with none of them set this script generates a THROWAWAY debug
# keystore under the output directory and says so, loudly, because an APK
# signed with it is installable for testing and must never be handed to a
# studio (its fingerprint changes every time this runs, so every user would be
# unable to update).
#
# Bubblewrap's `init` is interactive, so this does not use it: tools/android/
# twa_manifest.py writes twa-manifest.json, `bubblewrap update` generates the
# Gradle project from it, and `bubblewrap build` compiles. `--skipPwaValidation`
# because the origin is normally on a tailnet, which Google's Lighthouse
# service cannot reach; the manifest and the icons are still fetched directly
# by Bubblewrap, so a wrong origin still fails here rather than on a phone.
#
# Bubblewrap brings its OWN JDK and Android SDK on first run when it is asked
# interactively. It cannot ask here, so ~/.bubblewrap/config.json is written
# from JAVA_HOME and ANDROID_HOME if it does not exist -- both are present on a
# GitHub ubuntu runner, and a laptop that has neither gets a clear refusal
# rather than a hung prompt.
set -euo pipefail

ORIGIN="${1:-}"
PACKAGE="${2:-}"
OUT="${3:-build/twa}"

if [ -z "$ORIGIN" ]; then
  echo "usage: $0 <https://origin> [package.id] [outdir]" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
mkdir -p "$OUT"
OUT_ABS="$(cd "$OUT" && pwd)"

# ---------------------------------------------------------------- the keystore
KEYSTORE="${CCSYNC_ANDROID_KEYSTORE:-}"
KEY_ALIAS="${CCSYNC_ANDROID_KEY_ALIAS:-android}"
if [ -n "$KEYSTORE" ]; then
  if [ ! -f "$KEYSTORE" ]; then
    echo "FAIL CCSYNC_ANDROID_KEYSTORE=$KEYSTORE does not exist" >&2
    exit 2
  fi
  if [ -z "${CCSYNC_ANDROID_KEYSTORE_PASSWORD:-}" ] || [ -z "${CCSYNC_ANDROID_KEY_PASSWORD:-}" ]; then
    echo "FAIL a keystore was given but CCSYNC_ANDROID_KEYSTORE_PASSWORD / _KEY_PASSWORD are not set" >&2
    exit 2
  fi
  echo "signing: release keystore from CCSYNC_ANDROID_KEYSTORE"
  SIGNING="release"
else
  KEYSTORE="$OUT_ABS/debug.keystore"
  KEY_ALIAS="${CCSYNC_ANDROID_KEY_ALIAS:-ccsync-debug}"
  export CCSYNC_ANDROID_KEYSTORE_PASSWORD="ccsync-debug"
  export CCSYNC_ANDROID_KEY_PASSWORD="ccsync-debug"
  SIGNING="debug"
  if [ ! -f "$KEYSTORE" ]; then
    echo "signing: no CCSYNC_ANDROID_KEYSTORE -- generating a THROWAWAY debug key."
    echo "         Do not ship this APK: its fingerprint changes on every build,"
    echo "         and an app signed with a new key cannot update an installed one."
    keytool -genkeypair -v -keystore "$KEYSTORE" -alias "$KEY_ALIAS" \
      -keyalg RSA -keysize 2048 -validity 10000 \
      -storepass "$CCSYNC_ANDROID_KEYSTORE_PASSWORD" \
      -keypass "$CCSYNC_ANDROID_KEY_PASSWORD" \
      -dname "CN=CC Sync debug, OU=CC Sync, O=CC Sync, L=, ST=, C=" >/dev/null
  fi
fi

# What Bubblewrap reads for the two passwords. Exported here rather than
# written into twa-manifest.json, which is committed-shaped text.
export BUBBLEWRAP_KEYSTORE_PASSWORD="$CCSYNC_ANDROID_KEYSTORE_PASSWORD"
export BUBBLEWRAP_KEY_PASSWORD="$CCSYNC_ANDROID_KEY_PASSWORD"

# ------------------------------------------------------ bubblewrap's own config
BW_CONFIG="$HOME/.bubblewrap/config.json"
if [ ! -f "$BW_CONFIG" ]; then
  JDK="${JAVA_HOME:-}"
  SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
  if [ -z "$JDK" ] || [ -z "$SDK" ]; then
    echo "FAIL no ~/.bubblewrap/config.json and JAVA_HOME / ANDROID_HOME are not both set." >&2
    echo "     Run 'npx @bubblewrap/cli doctor' once interactively and let it install them," >&2
    echo "     or export both and re-run." >&2
    exit 2
  fi
  mkdir -p "$(dirname "$BW_CONFIG")"
  printf '{"jdkPath":"%s","androidSdkPath":"%s"}\n' "$JDK" "$SDK" > "$BW_CONFIG"
  echo "wrote $BW_CONFIG (jdk=$JDK sdk=$SDK)"
fi

# Bubblewrap validates an Android SDK by looking for `tools/source.properties`
# -- a file from the RETIRED "SDK Tools" package, which no current SDK ships
# and which nothing in the build actually uses. Without it `bubblewrap build`
# dies with "The provided androidSdk isn't correct" and no hint at all
# (measured on ubuntu-latest, 2026-08-30). One stub file satisfies the check;
# every real tool it then invokes lives in build-tools/ and platform-tools/.
SDK_PATH="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["androidSdkPath"])' "$BW_CONFIG" 2>/dev/null || true)"
if [ -n "$SDK_PATH" ] && [ ! -f "$SDK_PATH/tools/source.properties" ]; then
  if mkdir -p "$SDK_PATH/tools" 2>/dev/null; then
    printf 'Pkg.Revision=26.1.1\n' > "$SDK_PATH/tools/source.properties"
  else
    sudo mkdir -p "$SDK_PATH/tools"
    printf 'Pkg.Revision=26.1.1\n' | sudo tee "$SDK_PATH/tools/source.properties" >/dev/null
  fi
  echo "stubbed $SDK_PATH/tools/source.properties for bubblewrap's SDK check"
fi

# ---------------------------------------------------------------- the manifest
ARGS=(--origin "$ORIGIN" --out "$OUT_ABS" --keystore "$KEYSTORE" --key-alias "$KEY_ALIAS")
if [ -n "$PACKAGE" ]; then
  ARGS+=(--package "$PACKAGE")
fi
if [ -n "${CCSYNC_ANDROID_WEB_MANIFEST:-}" ]; then
  ARGS+=(--manifest "$CCSYNC_ANDROID_WEB_MANIFEST")
fi
"$PYTHON" "$REPO_ROOT/tools/android/twa_manifest.py" "${ARGS[@]}"

# ------------------------------------------------------------------- the build
cd "$OUT_ABS"
BW="${BUBBLEWRAP:-npx --yes @bubblewrap/cli@latest}"
echo "== bubblewrap update (generating the Gradle project from twa-manifest.json)"
$BW update --skipVersionUpgrade
echo "== bubblewrap build --skipPwaValidation"
$BW build --skipPwaValidation

# --------------------------------------------------------------- what to paste
echo
echo "== signing certificate ($SIGNING)"
# `keytool -list` prints several digests; the SHA-256 one is what Chrome
# verifies and what Settings -> ANDROID wants.
FINGERPRINT="$(keytool -list -v -keystore "$KEYSTORE" -alias "$KEY_ALIAS" \
  -storepass "$CCSYNC_ANDROID_KEYSTORE_PASSWORD" 2>/dev/null \
  | grep -i 'SHA256:' | head -n 1 | sed 's/.*SHA256: *//' | tr -d '\r')"
echo "package:     $(${PYTHON} -c 'import json,sys;print(json.load(open("twa-manifest.json"))["packageId"])')"
echo "fingerprint: $FINGERPRINT"
echo
echo "Paste both into the dashboard's Settings -> ANDROID, save, then verify:"
echo "  python tools/android/check_assetlinks.py $ORIGIN $FINGERPRINT"
ls -l app-release-signed.apk app-release-bundle.aab 2>/dev/null || true
