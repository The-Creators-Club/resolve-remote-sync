"""Is this fingerprint in that site's asset-links statement?

MOBILE_PLAN.md §4 M5, 2026-08-30. The TWA's failure mode is silent: an app
whose asset links do not verify still opens, just with a URL bar across the
top, and neither the phone nor the dashboard says a word. This is the tool
that turns that silence into a sentence.

    python tools/android/check_assetlinks.py https://nas.example.ts.net:9443 \
        AA:BB:...:FF

Exit codes: 0 the fingerprint is there, 1 it is not (or the statement is
empty/malformed), 2 the site could not be reached. stdlib only -- it runs from
an editor's laptop and from CI.

It reads the SITE's own statement, not Google's verifier. Google's answer is
the one that decides, but it needs a public DNS name; a tailnet origin is
unreachable from it, so the check that can always run is this one, and
docs/ANDROID.md prints the Google URL beside it for the case where the origin
IS public.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

RELATION = "delegate_permission/common.handle_all_urls"
PATH = "/.well-known/assetlinks.json"


def normalise(fingerprint: str) -> str:
    value = str(fingerprint or "").strip()
    if value.upper().startswith("SHA256:"):
        value = value[len("SHA256:"):].strip()
    return value.upper()


def fetch(origin: str, timeout: float = 15.0) -> list:
    url = origin.rstrip("/") + PATH
    with urllib.request.urlopen(url, timeout=timeout) as resp:       # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def evaluate(statements, fingerprint: str) -> tuple[bool, str]:
    """(ok, one line for a human). Pure, so the tests do not need a socket."""
    wanted = normalise(fingerprint)
    if not isinstance(statements, list):
        return False, "FAIL that is not an asset-links document (expected a JSON array)"
    if not statements:
        return False, ("FAIL the statement is empty ([]) -- the site has no Android "
                       "package configured, so no app can verify against it")
    seen: list[str] = []
    for entry in statements:
        if not isinstance(entry, dict):
            continue
        if RELATION not in (entry.get("relation") or []):
            continue
        target = entry.get("target") or {}
        if target.get("namespace") != "android_app":
            continue
        package = str(target.get("package_name") or "")
        for raw in target.get("sha256_cert_fingerprints") or []:
            got = normalise(str(raw))
            seen.append(got)
            if got == wanted:
                return True, f"OK  {package} is declared with this fingerprint"
    if not seen:
        return False, (f"FAIL no {RELATION} statement for an android_app was found")
    return False, ("FAIL this fingerprint is not in the statement. The site declares: "
                   + ", ".join(seen))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("origin", help="the site, e.g. https://nas.example.ts.net:9443")
    ap.add_argument("fingerprint", help="SHA-256 cert fingerprint, AA:BB:...:FF")
    args = ap.parse_args(argv)

    url = args.origin.rstrip("/") + PATH
    try:
        statements = fetch(args.origin)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"FAIL could not read {url}: {exc}", file=sys.stderr)
        return 2
    ok, line = evaluate(statements, args.fingerprint)
    print(f"{line}\n     source: {url}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
