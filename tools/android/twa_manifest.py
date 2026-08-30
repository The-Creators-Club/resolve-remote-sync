"""Write Bubblewrap's `twa-manifest.json` for a dashboard origin.

MOBILE_PLAN.md §4 M5, 2026-08-30. Bubblewrap's own `init` is INTERACTIVE: it
asks a dozen questions and then writes this file. A CI job cannot answer
questions, and the answers are the same every time for this product, so this
tool writes the file and `build_apk.sh` runs Bubblewrap over it. That also
makes the values reviewable in a diff instead of living in a runner's stdin.

    python tools/android/twa_manifest.py --origin https://nas.example.ts.net:9443 \
        --out build/twa

Reads the LIVE web app manifest (M4's `/manifest.webmanifest`) for the name,
the colours and the icons -- so the app's icon and splash never drift from the
installed PWA's -- and derives the package name from the origin's host,
reversed, plus `.ccsync`: `nas.example.ts.net` -> `net.ts.example.nas.ccsync`.
Override with `--package` when the studio already owns a package id.

`--manifest` takes a URL or a local path, which is what lets the test suite
run the generator against `tools/android/fixture/manifest.webmanifest` with no
network at all. stdlib only, on purpose: this runs on a CI runner before
anything has been installed, and on an editor's laptop that has node and
nothing else.

NEVER writes a keystore or a password. `signingKey` names a path and an alias;
`build_apk.sh` supplies both from the environment.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, urljoin

# Bubblewrap refuses a manifest whose icon is smaller than this, and Play
# refuses the store listing without it.
MIN_ICON = 512

# What the plan fixes for this product, and why:
#   fallbackType customtabs -- a device without a Chrome new enough for TWA
#     opens a Custom Tab instead of a WebView. A WebView has its own cookie
#     jar, so the editor would be signed out inside their own app.
#   enableNotifications false -- Web Push is §7, not this round. Turning it on
#     would put a notifications permission on the install dialogue for a
#     feature that does not exist.
#   shortcuts [] -- the manifest has none yet; an empty list is what Bubblewrap
#     expects rather than the key being absent.
FALLBACK_TYPE = "customtabs"


def fetch(location: str) -> dict:
    """The web app manifest at `location`, which may be a URL or a path."""
    parsed = urlparse(location)
    if parsed.scheme in ("http", "https"):
        with urllib.request.urlopen(location, timeout=30) as resp:   # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    return json.loads(Path(location).read_text(encoding="utf-8"))


def package_from_origin(origin: str, suffix: str = "ccsync") -> str:
    """`https://nas.example.ts.net:9443` -> `net.ts.example.nas.ccsync`.

    A DNS label may start with a digit and may contain hyphens; an Android
    application id may do neither. AAPT is stricter than Java here: a leading
    UNDERSCORE is a fine Java identifier and aapt2 still refuses it outright
    ("'_1._0._0._127.ccsync' is not a valid Android package name", measured on
    a runner 2026-08-30), so a label that cannot start itself gets an `n`
    prefix and hyphens become underscores. The result is not pretty, it is
    VALID, and it is stable for a given host -- which is what matters:
    changing it after an install is a different app, not an update.
    """
    host = urlparse(origin).hostname or ""
    labels = [label for label in host.split(".") if label]
    segments = []
    for label in reversed(labels):
        seg = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in label).lower()
        if not seg or not ("a" <= seg[0] <= "z"):
            seg = "n" + seg
        segments.append(seg)
    segments.append(suffix)
    if len(segments) < 2:
        raise SystemExit(f"cannot derive a package name from {origin!r} -- pass --package")
    return ".".join(segments)


def _pick_icon(manifest: dict, base: str, maskable: bool) -> str:
    """The biggest icon of the wanted purpose, as an absolute URL."""
    best = None
    best_px = 0
    for icon in manifest.get("icons") or []:
        purpose = str(icon.get("purpose") or "any").split()
        if maskable != ("maskable" in purpose):
            continue
        for size in str(icon.get("sizes") or "").split():
            try:
                px = int(size.split("x")[0])
            except ValueError:
                continue
            if px > best_px:
                best_px, best = px, icon.get("src")
    if best is None:
        return ""
    return urljoin(base, str(best))


def build(manifest: dict, origin: str, package: str, *,
          manifest_url: str, keystore: str, key_alias: str,
          version_name: str, version_code: int) -> dict:
    origin = origin.rstrip("/")
    host = urlparse(origin).hostname or ""
    name = str(manifest.get("name") or "CC Sync")
    short = str(manifest.get("short_name") or name)
    theme = str(manifest.get("theme_color") or "#0a0a0d")
    background = str(manifest.get("background_color") or theme)
    icon = _pick_icon(manifest, manifest_url, maskable=False)
    maskable = _pick_icon(manifest, manifest_url, maskable=True)
    if not icon:
        raise SystemExit(
            f"{manifest_url} names no non-maskable icon -- Bubblewrap needs one "
            f"of at least {MIN_ICON}x{MIN_ICON}")
    return {
        "packageId": package,
        "host": host,
        "name": name,
        "launcherName": short,
        "display": str(manifest.get("display") or "standalone"),
        "themeColor": theme,
        "themeColorDark": theme,
        "navigationColor": theme,
        "navigationColorDark": theme,
        "navigationDividerColor": theme,
        "navigationDividerColorDark": theme,
        "backgroundColor": background,
        "enableNotifications": False,
        "startUrl": str(manifest.get("start_url") or "/"),
        "iconUrl": icon,
        "maskableIconUrl": maskable or icon,
        "splashScreenFadeOutDuration": 300,
        "signingKey": {"path": keystore, "alias": key_alias},
        "appVersionName": version_name,
        "appVersionCode": version_code,
        "shellApkVersion": 0,
        "webManifestUrl": manifest_url,
        "fallbackType": FALLBACK_TYPE,
        "features": {},
        "alphaDependencies": {"enabled": False},
        "enableSiteSettingsShortcut": True,
        "isChromeOSOnly": False,
        "isMetaQuest": False,
        "fullScopeUrl": origin + str(manifest.get("scope") or "/"),
        "minSdkVersion": 21,
        "orientation": str(manifest.get("orientation") or "any"),
        "fingerprints": [],
        "additionalTrustedOrigins": [],
        "retainedBundles": [],
        "shortcuts": [],
        "generatorApp": "ccsync tools/android/twa_manifest.py",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--origin", required=True,
                    help="the dashboard's https origin, e.g. https://nas.example.ts.net:9443")
    ap.add_argument("--package", default="",
                    help="application id (default: the origin's host, reversed, + .ccsync)")
    ap.add_argument("--out", required=True,
                    help="directory to write twa-manifest.json into (created if absent)")
    ap.add_argument("--manifest", default="",
                    help="the web app manifest: a URL or a path "
                         "(default: <origin>/manifest.webmanifest)")
    ap.add_argument("--keystore", default="./android.keystore",
                    help="signingKey.path, relative to --out (never a secret)")
    ap.add_argument("--key-alias", default="android", help="signingKey.alias")
    ap.add_argument("--version-name", default="1.0.0")
    ap.add_argument("--version-code", type=int, default=1)
    args = ap.parse_args(argv)

    origin = args.origin.rstrip("/")
    manifest_url = args.manifest or (origin + "/manifest.webmanifest")
    package = args.package or package_from_origin(origin)
    try:
        manifest = fetch(manifest_url)
    except Exception as exc:                                       # noqa: BLE001
        print(f"FAIL could not read the web app manifest at {manifest_url}: {exc}",
              file=sys.stderr)
        return 2
    doc = build(manifest, origin, package, manifest_url=manifest_url,
                keystore=args.keystore, key_alias=args.key_alias,
                version_name=args.version_name, version_code=args.version_code)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "twa-manifest.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"  packageId  {doc['packageId']}")
    print(f"  host       {doc['host']}")
    print(f"  startUrl   {doc['startUrl']}")
    print(f"  iconUrl    {doc['iconUrl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
