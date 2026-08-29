#!/usr/bin/env python3
"""Submit and watch FLEET JOBS from the command line.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 0 (2026-08-29), and docs/API.md is
the HTTP contract this speaks. Two audiences: a person putting a
transcription on the queue by hand today, and Timeline Cards calling the same
routes tomorrow (§4: it stays its own repo and is a CLIENT of this API).

    python tools/jobs.py submit --kind whisper --root vault \\
        --rel "Vault/2026/FF5/Civil Defence/Youtube/Interview 3" \\
        --episode "Vault/2026/FF5/Civil Defence" [--speakers]
    python tools/jobs.py list [--state open]
    python tools/jobs.py why 12
    python tools/jobs.py watch 12

PATHS ARE (ROOT NAME, RELATIVE PATH) PAIRS AND NOTHING ELSE (§4.1). The vault
is `X:\\` on creator-1, `/vault` in the Timeline Cards container and a UNC
path on the wire, so an absolute path on the queue would be correct on
exactly one machine. `--rel` is refused if it looks absolute, here as well as
on the claimant, because the useful place to be told is the one where a
person can retype it.

The credential is the dashboard ADMIN session -- a job is work on somebody
else's computer -- and the password comes from the terminal or
--password-stdin, NEVER argv and never the environment (the rule
companion/tests/test_publish_password_hygiene.py pins on the shell scripts,
applied to a tool that would otherwise leak it into shell history).

Stdlib only, like every other script in tools/, and no redirect is ever
followed: the request carries a session cookie.
"""
from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_LOGIN = 4
EXIT_CALL = 5
EXIT_JOB_FAILED = 6

DASHBOARD_URL_ENV = "CCSYNC_DASHBOARD_URL"
ADMIN_USER_ENV = "CCSYNC_ADMIN_USER"

# The roots a job may name. Not a free string: a typo'd root is a job no
# machine can ever place, and the failure would be a queue that never moves.
ROOTS = ("tree", "vault", "media")


class JobsError(Exception):
    def __init__(self, message: str, code: int = EXIT_CALL):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------- transport
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
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
    """A cookie-holding, redirect-refusing sender. Tests inject a fake.

    publish_package.py's, deliberately identical: one transport shape in
    tools/, and the redirect refusal is load-bearing in both (a 302 would
    re-send the session cookie to another origin).
    """

    def __init__(self, timeout: float = 30.0):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPCookieProcessor(self.jar))
        self.timeout = timeout

    def send(self, method: str, url: str, headers: dict | None = None,
             body: bytes | None = None, timeout: float | None = None) -> Response:
        req = urllib.request.Request(url, data=body, method=method,
                                     headers=headers or {})
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                return Response(resp.status, dict(resp.headers.items()), resp.read())
        except urllib.error.HTTPError as exc:
            return Response(exc.code, dict(exc.headers.items()), exc.read() or b"")


class Client:
    """One logged-in conversation with a dashboard."""

    def __init__(self, http: Http, dashboard_url: str):
        self.http = http
        self.url = dashboard_url.rstrip("/")
        self.csrf = ""

    def login(self, username: str, password: str) -> dict:
        r = self.http.send(
            "POST", f"{self.url}/api/v1/login",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"username": username, "password": password}).encode())
        if r.status != 200:
            raise JobsError(f"dashboard login failed (HTTP {r.status}): "
                            f"{_detail(r)}", EXIT_LOGIN)
        info = r.json()
        if not info.get("is_admin"):
            raise JobsError(f"{username!r} is not a dashboard admin -- a job is "
                            f"work on somebody else's computer", EXIT_LOGIN)
        # The session's own CSRF token (api_login returns it for exactly this
        # caller: no page, no hidden field).
        self.csrf = str(info.get("csrf") or "")
        return info

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        r = self.http.send(method, f"{self.url}{path}", headers=headers,
                           body=json.dumps(body).encode() if body is not None else None)
        if r.status != 200:
            raise JobsError(f"{method} {path} answered HTTP {r.status}: {_detail(r)}")
        return r.json()


def _detail(r: Response) -> str:
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        return str(detail.get("detail") or detail)
    return str(detail or r.body[:300].decode("utf-8", errors="replace"))


# ------------------------------------------------------------------ inputs
def read_password(stdin_mode: bool, prompt: str) -> str:
    if stdin_mode:
        pw = sys.stdin.readline()
    else:
        if not sys.stdin.isatty():
            raise JobsError("no terminal to prompt on -- pass --password-stdin "
                            "and pipe the password in (never argv, never the "
                            "environment).", EXIT_USAGE)
        pw = getpass.getpass(prompt)
    pw = pw.rstrip("\r\n")
    if not pw:
        raise JobsError("no password was entered", EXIT_LOGIN)
    return pw


def check_relative(label: str, value: str) -> str:
    """A job's path, or a refusal naming the rule (§4.1)."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise JobsError(f"{label} is required", EXIT_USAGE)
    # The RAW value decides, before any stripping: "/vault/2026" is exactly
    # how the Timeline Cards container spells the vault, and quietly turning
    # it into a relative path would queue a job that lands in the wrong place
    # on every machine that is not that container.
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise JobsError(
            f"{label} must be RELATIVE to its root, and {value!r} is an absolute "
            f"path. The vault is a different absolute path on every machine "
            f"(TIMELINE-CARDS-INTO-CCSYNC.md section 4.1) -- name the root with "
            f"--root and the path inside it with {label}.", EXIT_USAGE)
    rel = raw.strip("/")
    if ".." in rel.split("/"):
        raise JobsError(f"{label} must not contain '..'", EXIT_USAGE)
    return rel


def whisper_job(args: argparse.Namespace) -> dict:
    """The body for a whisper submission.

    `requires` is what the scheduler filters on, and it is set HERE rather
    than defaulted on the server: the requirements are a property of the WORK
    (large-v3 in float16 wants ~6 GB of VRAM), and a dashboard that invented
    them would be deciding something the submitter knows better.
    """
    rel = check_relative("--rel", args.rel)
    episode = check_relative("--episode", args.episode) if args.episode else None
    inputs = {"root": args.root, "rel_path": rel}
    if episode:
        inputs["episode_rel"] = episode
    if args.speakers:
        inputs["speakers"] = True
    requires = {"whisper": True, "mount": args.root,
                "gpu_vram_gb": float(args.vram)}
    return {"kind": args.kind, "inputs": inputs, "requires": requires,
            "priority": int(args.priority)}


# ----------------------------------------------------------------- commands
def cmd_submit(client: Client, args: argparse.Namespace) -> int:
    if args.kind != "whisper":
        raise JobsError(f"this tool only submits `whisper` jobs today "
                        f"(asked for {args.kind!r})", EXIT_USAGE)
    answer = client.call("POST", "/api/v1/jobs", whisper_job(args))
    job = answer.get("job") or {}
    why = answer.get("why") or {}
    print(f"job #{job.get('id')} queued ({job.get('kind')})")
    print(f"  {job.get('inputs', {}).get('root')}:{job.get('inputs', {}).get('rel_path')}")
    # The RECEIPT says whether anything can run it. A submitter who queues
    # work no machine can take learns it here, not by watching a queue that
    # never moves.
    print(f"  {why.get('summary') or 'no scheduling answer'}")
    for machine in (why.get("machines") or []):
        mark = "yes" if machine["ok"] else "no "
        print(f"    [{mark}] {machine['editor']}/{machine['machine']}: {machine['why']}")
    if args.watch:
        return watch(client, int(job["id"]), args.timeout)
    return EXIT_OK


def cmd_list(client: Client, args: argparse.Namespace) -> int:
    answer = client.call("GET", f"/api/v1/jobs?state={args.state}&limit={args.limit}")
    jobs = answer.get("jobs") or []
    if not jobs:
        print("no jobs")
        return EXIT_OK
    for job in jobs:
        held = (f" {job['claimed_by']}/{job['claimed_machine']}"
                if job.get("claimed_machine") else "")
        print(f"#{job['id']:<5} {job['kind']:<10} {job['state']:<10}"
              f" attempts={job['attempts']}{held}"
              f"  {job.get('inputs', {}).get('rel_path', '')}")
        if job.get("last_error"):
            print(f"        last error: {job['last_error'][:160]}")
    return EXIT_OK


def cmd_why(client: Client, args: argparse.Namespace) -> int:
    answer = client.call("GET", f"/api/v1/jobs/{args.job_id}/why")
    job = answer.get("job") or {}
    print(f"job #{job.get('id')} ({job.get('kind')}, {job.get('state')})")
    print(f"  {answer.get('summary')}")
    for machine in (answer.get("machines") or []):
        mark = "yes" if machine["ok"] else "no "
        print(f"    [{mark}] {machine['editor']}/{machine['machine']}: {machine['why']}")
    return EXIT_OK


def cmd_watch(client: Client, args: argparse.Namespace) -> int:
    return watch(client, args.job_id, args.timeout)


def watch(client: Client, job_id: int, timeout: float, sleep=time.sleep,
          clock=time.monotonic) -> int:
    """Poll until the job finishes, or the timeout. -> an exit code.

    Deliberately a POLL and not a long-poll: a job runs for minutes on a
    machine whose report interval is 30 s, and a held-open connection to the
    single-worker dashboard container is a cost with nothing to buy
    (§7.3 splits the two channels for the same reason).
    """
    deadline = clock() + max(1.0, float(timeout))
    last = ""
    while True:
        job = client.call("GET", f"/api/v1/jobs/{job_id}").get("job") or {}
        state = str(job.get("state") or "?")
        held = (f" on {job.get('claimed_machine')}" if job.get("claimed_machine") else "")
        line = f"{state}{held}"
        if line != last:
            print(f"  #{job_id}: {line}")
            last = line
        if state == "done":
            result = job.get("result") or {}
            files = result.get("files") or []
            print(f"  #{job_id}: done in {result.get('seconds', '?')}s"
                  f" ({result.get('realtime') or '?'}x realtime), "
                  f"{len(files)} file(s) written")
            for path in files[:20]:
                print(f"    {path}")
            return EXIT_OK
        if state in ("failed", "abandoned"):
            print(f"  #{job_id}: {state}: {job.get('last_error')}")
            return EXIT_JOB_FAILED
        if clock() > deadline:
            print(f"  #{job_id}: still {state} after {timeout:.0f}s -- "
                  f"`python tools/jobs.py why {job_id}` says who could take it")
            return EXIT_OK
        sleep(5.0)


# --------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tools/jobs.py", description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dashboard-url", default=os.environ.get(DASHBOARD_URL_ENV, ""),
                    help=f"default: ${DASHBOARD_URL_ENV}")
    ap.add_argument("--admin-user", default=os.environ.get(ADMIN_USER_ENV, ""),
                    help=f"default: ${ADMIN_USER_ENV}")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the password from stdin instead of prompting")
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("submit", help="queue a job")
    s.add_argument("--kind", default="whisper")
    s.add_argument("--root", default="vault", choices=ROOTS,
                   help="the ROOT NAME the paths are relative to")
    s.add_argument("--rel", required=True, metavar="REL_PATH",
                   help="the folder of clips, relative to the root")
    s.add_argument("--episode", default="", metavar="REL_PATH",
                   help="the episode root the transcripts land under, relative "
                        "to the same root (default: the folder's parent)")
    s.add_argument("--speakers", action="store_true", help="also diarise")
    s.add_argument("--vram", type=float, default=6.0,
                   help="GPU VRAM (GB) this job needs; the scheduler filters on it")
    s.add_argument("--priority", type=int, default=0)
    s.add_argument("--watch", action="store_true")
    s.add_argument("--timeout", type=float, default=3600)

    s = sub.add_parser("list", help="what is on the queue")
    s.add_argument("--state", default="open",
                   help="open (the default), queued, running, done, failed, abandoned")
    s.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("why", help="why a job is not running")
    s.add_argument("job_id", type=int)

    s = sub.add_parser("watch", help="follow a job to its end")
    s.add_argument("job_id", type=int)
    s.add_argument("--timeout", type=float, default=3600)
    return ap


COMMANDS = {"submit": cmd_submit, "list": cmd_list, "why": cmd_why,
            "watch": cmd_watch}


def main(argv: list[str] | None = None, http: Http | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.dashboard_url:
            raise JobsError(f"--dashboard-url (or ${DASHBOARD_URL_ENV}) is required",
                            EXIT_USAGE)
        if not args.admin_user:
            raise JobsError(f"--admin-user (or ${ADMIN_USER_ENV}) is required",
                            EXIT_USAGE)
        client = Client(http or Http(), args.dashboard_url)
        client.login(args.admin_user,
                     read_password(args.password_stdin,
                                   f"password for {args.admin_user}: "))
        return COMMANDS[args.command](client, args)
    except JobsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
