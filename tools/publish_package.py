#!/usr/bin/env python3
"""Publish ONE prebuilt package to a dashboard's upgrade channel -- no build.

Why this exists (2026-08-17, docs/ZERO_TOUCH_PLAN.md WP E, first slice).
Until today every publish path also BUILT: build_editor_package.ps1 packages
and PUTs the Windows artefacts it just made, release_macos.sh /
build_onboard_macos.sh PUT the macOS artefacts they just made, and neither
can take a file built somewhere else. So a build from the hosted macOS
runner (.github/workflows/release-macos.yml) -- which exists precisely so no
editor's laptop is needed -- had no way onto the channel except retyping the
curl recipe from release_macos.sh by hand. This is that recipe, once, in
Python, for either platform and either kind:

    python tools/publish_package.py --manifest dist/ccsync-release.json \
        --dashboard-url https://... --admin-user <you> --make-current

    python tools/publish_package.py --artifact onboard.zip --kind onboard \
        --platform macos --version 1.0.30 --dashboard-url ... --admin-user ...

What it does, in order, and stops at the first refusal:
  1. Signs the record with the OFFLINE release key (tools/sign_release.py,
     ~/.ccsync-release/release.key). No key, no publish -- the dashboard
     would refuse an unsigned record anyway (503/422), but a missing key
     should cost a message, not a login.
  2. Pre-flight: if DASH_REPORT_TOKEN is in the environment, asks the
     download route (Range 0-0) whether this version already exists, so a
     409 is discovered BEFORE the password prompt.
  3. Logs in (POST /api/v1/login) -- the password comes from the terminal
     (getpass) or --password-stdin, NEVER argv or the environment (the same
     rule companion/tests/test_publish_password_hygiene.py pins on the shell
     scripts). Refuses unless the account is a dashboard admin.
  4. PUT /api/v1/admin/packages/<platform>/<version>?kind=...&sha256=...
     &make_current=...&<signed query>, body = the file bytes.
  5. Reads back GET /api/v1/admin/packages and prints the row it made.

Redirects are never followed (a 302 would re-send the session cookie
somewhere else). Nothing here touches the fleet's floors: min_version is
whatever you pass, default 0.0.0, and the note sign_release prints about that
is printed here too.

--manifest reads the ccsync-release.json the release scripts write and fills
version/platform/artifact/sha256/signed_binary from it; it REFUSES a manifest
stamped git_dirty or tests_run=false unless told --allow-dirty /
--allow-untested, because "published a build whose suite never ran" is
OPS-1, and this tool must not become the way around that gate.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import sign_release  # noqa: E402  (tools/sign_release.py)

PLATFORMS = sign_release.PLATFORMS
KINDS = sign_release.KINDS

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ALREADY_PUBLISHED = 3
EXIT_LOGIN = 4
EXIT_PUBLISH = 5

REPORT_TOKEN_ENV = "DASH_REPORT_TOKEN"
DASHBOARD_URL_ENV = "CCSYNC_DASHBOARD_URL"
ADMIN_USER_ENV = "CCSYNC_ADMIN_USER"


class PublishError(Exception):
    def __init__(self, message: str, code: int = EXIT_PUBLISH):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------- transport
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> dict:
        try:
            return json.loads(self.body.decode("utf-8", errors="replace") or "{}")
        except ValueError:
            return {}


class Http:
    """A cookie-holding, redirect-refusing sender. Tests inject a fake."""

    def __init__(self, timeout: float = 30.0):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPCookieProcessor(self.jar))
        self.timeout = timeout

    def send(self, method: str, url: str, headers: dict | None = None,
             body: bytes | None = None, timeout: float | None = None) -> Response:
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                return Response(resp.status, dict(resp.headers.items()), resp.read())
        except urllib.error.HTTPError as exc:
            # A 3xx lands here too, because the redirect handler declined it.
            return Response(exc.code, dict(exc.headers.items()), exc.read() or b"")


# ---------------------------------------------------------------- inputs
def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublishError(f"cannot read manifest {path}: {exc}", EXIT_USAGE)
    if not isinstance(data, dict):
        raise PublishError(f"manifest {path} is not a JSON object", EXIT_USAGE)
    return data


def apply_manifest(args: argparse.Namespace, manifest: dict, manifest_dir: Path) -> None:
    """Fill what the manifest knows; refuse what the manifest condemns."""
    if manifest.get("git_dirty") and not args.allow_dirty:
        raise PublishError(
            "manifest says git_dirty=true -- this build came from an uncommitted tree "
            f"({manifest.get('version_stamp') or manifest.get('git_describe') or '?'}); "
            "nobody can reproduce it. Re-run with --allow-dirty only for a deliberate hotfix.",
            EXIT_USAGE)
    if manifest.get("tests_run") is False and not args.allow_untested:
        raise PublishError(
            "manifest says tests_run=false -- publishing an untested build to the fleet "
            "is the failure OPS-1 exists to prevent. --allow-untested overrides.",
            EXIT_USAGE)
    if not args.version:
        args.version = str(manifest.get("version") or "")
    if not args.platform:
        args.platform = str(manifest.get("platform") or "")
    if not args.artifact:
        name = str(manifest.get("artifact") or "")
        if name:
            args.artifact = str(manifest_dir / name)
    if args.signed_binary is None and "signed_binary" in manifest:
        args.signed_binary = bool(manifest.get("signed_binary"))
    args.manifest_sha256 = str(manifest.get("sha256") or "").lower()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_password(stdin_mode: bool, prompt: str) -> str:
    if stdin_mode:
        pw = sys.stdin.readline()
    else:
        if not sys.stdin.isatty():
            raise PublishError(
                "no terminal to prompt on -- pass --password-stdin and pipe the "
                "password in (never argv, never the environment).", EXIT_USAGE)
        pw = getpass.getpass(prompt)
    pw = pw.rstrip("\r\n")
    if not pw:
        raise PublishError("no password was entered -- NOT publishing", EXIT_LOGIN)
    if any(ord(ch) < 0x20 for ch in pw):
        # KNOWN_BUGS item 10: bracketed-paste wrappers read as a wrong password.
        raise PublishError("password contains a control character -- retype it, do not paste", EXIT_LOGIN)
    return pw


# ------------------------------------------------------------------ steps
def build_put_url(dashboard_url: str, platform: str, version: str, kind: str,
                  sha256: str, make_current: bool, signed_query: str) -> str:
    return (f"{dashboard_url}/api/v1/admin/packages/{platform}/{version}"
            f"?kind={kind}&sha256={sha256}&make_current={'1' if make_current else '0'}"
            f"{signed_query}")


def preflight(http, dashboard_url: str, platform: str, version: str, kind: str,
              report_token: str) -> str:
    """'exists' | 'absent' | 'unknown:<code>' -- never raises."""
    if not report_token:
        return "unknown:no-token"
    url = f"{dashboard_url}/api/v1/companion/package/{platform}/{version}"
    if kind != "companion":
        url += f"?kind={kind}"
    try:
        r = http.send("GET", url, headers={"X-CCSync-Token": report_token, "Range": "bytes=0-0"},
                      timeout=20)
    except Exception as exc:  # noqa: BLE001 -- pre-flight is advisory
        return f"unknown:{type(exc).__name__}"
    if r.status in (200, 206):
        return "exists"
    if r.status == 404:
        return "absent"
    return f"unknown:{r.status}"


def login(http, dashboard_url: str, username: str, password: str) -> dict:
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    r = http.send("POST", f"{dashboard_url}/api/v1/login",
                  headers={"Content-Type": "application/json"}, body=body, timeout=30)
    if r.status != 200:
        detail = r.json().get("detail") or r.body[:300].decode("utf-8", errors="replace")
        raise PublishError(f"dashboard login failed (HTTP {r.status}): {detail}", EXIT_LOGIN)
    info = r.json()
    if not info.get("is_admin"):
        raise PublishError(f"'{username}' is not a dashboard admin (DASH_ADMIN_USERS) -- NOT publishing",
                           EXIT_LOGIN)
    return info


def upload(http, put_url: str, data: bytes) -> dict:
    r = http.send("PUT", put_url, headers={"Content-Type": "application/octet-stream",
                                          "Content-Length": str(len(data))},
                  body=data, timeout=600)
    if r.status == 409:
        raise PublishError(
            "HTTP 409: that (kind, platform, version) is already published with different "
            "bytes, or you re-ran. The server keeps what it has. Bump the version and rebuild.",
            EXIT_ALREADY_PUBLISHED)
    if r.status != 200:
        detail = r.json().get("detail") or r.body[:500].decode("utf-8", errors="replace")
        raise PublishError(f"publish failed with HTTP {r.status}: {detail} -- nothing is current "
                           "that was not current before.", EXIT_PUBLISH)
    return r.json()


def published_row(http, dashboard_url: str, platform: str, version: str, kind: str) -> dict:
    r = http.send("GET", f"{dashboard_url}/api/v1/admin/packages", timeout=30)
    if r.status != 200:
        return {}
    view = r.json()
    rows = view.get("packages") if isinstance(view, dict) else None
    if not isinstance(rows, list):
        rows = view.get("view", {}).get("packages", []) if isinstance(view, dict) else []
    for row in rows or []:
        if (str(row.get("platform")) == platform and str(row.get("version")) == version
                and str(row.get("kind", "companion")) == kind):
            return row
    return {}


# ------------------------------------------------------------------- main
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", default="", help="the file to publish")
    ap.add_argument("--manifest", default="", help="ccsync-release.json from the build; fills "
                    "version/platform/artifact/sha256/signed_binary")
    ap.add_argument("--kind", default="companion", choices=KINDS)
    ap.add_argument("--platform", default="", choices=("",) + tuple(PLATFORMS))
    ap.add_argument("--version", default="")
    ap.add_argument("--min-version", default="0.0.0")
    ap.add_argument("--signed-binary", dest="signed_binary", action="store_true", default=None,
                    help="the artefact carries a real Authenticode/Developer ID signature")
    ap.add_argument("--make-current", action="store_true")
    ap.add_argument("--dashboard-url", default="", help=f"or ${DASHBOARD_URL_ENV}")
    ap.add_argument("--admin-user", default="", help=f"or ${ADMIN_USER_ENV}")
    ap.add_argument("--key", default="", help="release key file (default ~/.ccsync-release/release.key)")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the dashboard password from stdin instead of prompting")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--allow-untested", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="sign and print the PUT; no network")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None, http=None, environ: dict | None = None,
         password_reader=read_password) -> int:
    env = os.environ if environ is None else environ
    args = parse_args(argv)
    out = sys.stdout
    try:
        args.manifest_sha256 = ""
        if args.manifest:
            mpath = Path(args.manifest).expanduser()
            apply_manifest(args, load_manifest(mpath), mpath.parent)
        dashboard_url = (args.dashboard_url or env.get(DASHBOARD_URL_ENV, "")).rstrip("/")
        admin_user = args.admin_user or env.get(ADMIN_USER_ENV, "")
        missing = [name for name, val in (
            ("--artifact", args.artifact), ("--platform", args.platform), ("--version", args.version),
            (f"--dashboard-url (or {DASHBOARD_URL_ENV})", dashboard_url),
            (f"--admin-user (or {ADMIN_USER_ENV})", admin_user)) if not val]
        if missing:
            raise PublishError("missing: " + ", ".join(missing), EXIT_USAGE)
        if not dashboard_url.startswith(("http://", "https://")):
            raise PublishError(f"--dashboard-url must be http(s)://..., got {dashboard_url!r}", EXIT_USAGE)
        artifact = Path(args.artifact).expanduser()
        if not artifact.is_file():
            raise PublishError(f"no artifact at {artifact}", EXIT_USAGE)

        sha = sha256_of(artifact)
        if args.manifest_sha256 and args.manifest_sha256 != sha:
            raise PublishError(
                f"the manifest describes sha256 {args.manifest_sha256[:12]}... but {artifact.name} "
                f"is {sha[:12]}... -- wrong file, or it changed after the build. NOT publishing.",
                EXIT_USAGE)

        # 1. sign -- before any network, before any prompt.
        sign_argv = ["--artifact", str(artifact), "--kind", args.kind, "--platform", args.platform,
                     "--version", args.version, "--min-version", args.min_version]
        if args.signed_binary:
            sign_argv.append("--signed-binary")
        if args.key:
            sign_argv += ["--key", args.key]
        signed = _sign(sign_argv)
        if signed["sha256"] != sha:
            raise PublishError("the signed record describes a different sha256 than the file", EXIT_PUBLISH)
        put_url = build_put_url(dashboard_url, args.platform, args.version, args.kind, sha,
                                args.make_current, signed["query"])
        size = artifact.stat().st_size
        print(f"[publish] {args.kind}/{args.platform} v{args.version}  {size // 1024} KB  sha256 {sha[:16]}...",
              file=out)
        print(f"[publish] signed (pubkey_id {signed['pubkey_id']}, min_version {signed['min_version']}, "
              f"signed_binary {signed['signed_binary']})", file=out)
        if args.dry_run:
            print(f"[dry-run] would PUT {put_url}", file=out)
            print(f"[dry-run] as {admin_user} after POST {dashboard_url}/api/v1/login", file=out)
            return EXIT_OK

        http = http or Http()

        # 2. pre-flight
        state = preflight(http, dashboard_url, args.platform, args.version, args.kind,
                          env.get(REPORT_TOKEN_ENV, ""))
        if state == "exists":
            raise PublishError(
                f"{args.kind} v{args.version} is ALREADY published for {args.platform}. "
                "Bump the version and rebuild. Nothing was uploaded.", EXIT_ALREADY_PUBLISHED)
        print(f"[publish] pre-flight: {state}", file=out)

        # 3. login
        password = password_reader(args.password_stdin, f"dashboard password for {admin_user}@{dashboard_url}: ")
        login(http, dashboard_url, admin_user, password)
        password = ""  # noqa: F841 -- drop the reference as early as we can
        print(f"[publish] logged in as {admin_user}", file=out)

        # 4. PUT
        print(f"[publish] uploading to {dashboard_url}/api/v1/admin/packages/{args.platform}/{args.version}",
              file=out)
        upload(http, put_url, artifact.read_bytes())
        state_word = "CURRENT" if args.make_current else "STAGED (not current -- flip [ MAKE CURRENT ] on the admin page)"
        print(f"[publish] published {args.kind}/{args.platform} v{args.version} -- {state_word}", file=out)

        # 5. read back
        row = published_row(http, dashboard_url, args.platform, args.version, args.kind)
        if row:
            print(f"[publish] server row: {json.dumps(row, sort_keys=True)[:400]}", file=out)
        else:
            print("[publish] NOTE: could not find the row in GET /api/v1/admin/packages -- check the admin page",
                  file=out)
        return EXIT_OK
    except PublishError as exc:
        print(f"[publish] FAILED: {exc}", file=sys.stderr)
        return exc.code


def _sign(sign_argv: list[str]) -> dict:
    """Run sign_release.main in-process and capture its JSON."""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = sign_release.main(sign_argv)
        except SystemExit as exc:
            raise PublishError(
                f"could not sign the release record: {exc}. The offline release key is missing "
                "or unreadable (~/.ccsync-release/release.key, or --key / $CCSYNC_RELEASE_KEY). "
                "Nothing was uploaded.", EXIT_USAGE)
    if rc != 0:
        raise PublishError(f"sign_release exited {rc}", EXIT_USAGE)
    try:
        return json.loads(buf.getvalue())
    except ValueError:
        raise PublishError("sign_release produced no JSON", EXIT_USAGE)


if __name__ == "__main__":
    sys.exit(main())
