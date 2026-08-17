#!/usr/bin/env python3
"""Mint a SCOPED TrueNAS API key for the dashboard container.

    python create_api_key.py --name ccsync-dashboard [--username ccsync-api] [--dry-run]

WHY THIS EXISTS. Until 2026-08-17 the dashboard container held `TRUENAS_PW` --
the NAS admin password, root-equivalent on TrueNAS -- in its environment, where
`docker inspect` and any code execution inside the container can read it. Every
editor can reach that dashboard, and it mounts three other web apps
(/broll, /music, /ytdl) in-process. That was finding H3 of
docs/COMMERCIAL_READINESS.md item 6.

The dashboard's NAS client makes exactly these calls (dashboard/src/
ccsync_dashboard/nas/truenas.py -- keep this list in step with it):

    GET  /group?group=<name>          find the editors group
    POST /group                       create it
    GET  /user, /user?username=...    list / find editors
    GET  /user/id/<id>                re-read one for verification
    POST /user                        create an editor
    PUT  /user/id/<id>                key, smb flag, groups, password,
                                      password_disabled
    POST /filesystem/setperm          make a new home sshd will accept
    GET  /core/get_jobs?id=<id>       wait for that setperm job

Nothing else. No pool, dataset, app, snapshot, share, service or system route.

HOW TRUENAS SCOPES A KEY -- and the version split this script handles:

  * TrueNAS SCALE <= 24.04 (`api_key.create` with an ALLOWLIST): the key
    carries its own list of {"method", "resource"} pairs and is checked per
    request. --allowlist-shape forces this, and ALLOWLIST below is the exact
    list for the calls above.
  * TrueNAS SCALE >= 24.10 (`api_key.create` with a USERNAME): allowlists were
    removed; a key acts AS a user and inherits that user's roles. Least
    privilege is then a dedicated non-shell account holding only the two roles
    the calls above need:

        ACCOUNT_WRITE             /user and /group, create + update
        FILESYSTEM_ATTRS_WRITE    filesystem.setperm

    (job reads come with any authenticated session). Create that account and
    its privilege in the UI -- Credentials > Local Users, then Credentials >
    Privileges -- because a script that invents roles on someone's NAS is
    exactly the guess this package refuses to make.

VERIFY AGAINST THE LIVE VERSION. The two shapes above are from this project's
knowledge of the middleware, not from a probe of the customer's box: the script
tries the newer shape first, reports what the API said if it is refused, and
falls back to the allowlist shape. If a third shape appears, it stops and
prints the response rather than guessing (the install_syncthing_app.py rule,
2026-07-22).

THE KEY IS SHOWN ONCE. TrueNAS returns the plaintext key only in the create
response; it is stored hashed. This script prints it once, to stdout, and does
not write it anywhere. Put it in the deploy environment:

    export TRUENAS_API_KEY=1-xxxxxxxx...
    python server/install_dashboard_app.py            # password stays out of
                                                      # the container

Rotation is a re-run with a new --name plus a delete of the old key in
Credentials > API Keys. Do that when an operator leaves, exactly as you would
rotate the password (docs/SERVER.md, "Scoped API key").

Env vars: TRUENAS_HOST / TRUENAS_USER (from [nas] host / admin_user in
site.toml), TRUENAS_PW (required -- minting a key needs the admin, once).
"""
import argparse
import sys

from common import (  # noqa: F401 - truenas_api is the name ScriptCalls/tests patch
    add_host_key_arg, add_nas_kind_arg, add_site_arg, cli, nas_kind, ok,
    set_host_key_pin, truenas_api,
)

# The legacy (<= 24.04) allowlist: one entry per call the dashboard makes.
# `resource` matches by prefix on the middleware side, which is why the
# per-id routes are covered by "/user" rather than a wildcard -- a wildcard
# would also cover /user/... routes that do not exist yet.
ALLOWLIST = [
    {"method": "GET", "resource": "/user"},
    {"method": "POST", "resource": "/user"},
    {"method": "PUT", "resource": "/user"},
    {"method": "GET", "resource": "/group"},
    {"method": "POST", "resource": "/group"},
    {"method": "POST", "resource": "/filesystem/setperm"},
    {"method": "GET", "resource": "/core/get_jobs"},
]

# The roles the >= 24.10 shape needs on the account the key acts as.
ROLES = ("ACCOUNT_WRITE", "FILESYSTEM_ATTRS_WRITE")


def describe_scope() -> str:
    lines = ["The key will be limited to:"]
    for entry in ALLOWLIST:
        lines.append(f"    {entry['method']:5} {entry['resource']}")
    lines.append("  (allowlist shape), or to the roles "
                 + ", ".join(ROLES) + " via its account (username shape).")
    return "\n".join(lines)


def create_key(name: str, username: str, shape: str, dry_run: bool):
    """POST /api_key in whichever shape this middleware takes. (key, error).

    Returns ("", "") in dry-run: nothing is minted, and a fake key printed as
    if it were real is how a secret ends up in a runbook.
    """
    attempts = []
    if shape in ("auto", "username"):
        attempts.append(("username", {"name": name, "username": username}))
    if shape in ("auto", "allowlist"):
        attempts.append(("allowlist", {"name": name, "allowlist": ALLOWLIST}))

    last = ""
    for label, body in attempts:
        resp = truenas_api("POST", "/api_key", json_body=body, dry_run=dry_run)
        if dry_run:
            print(f"[dry-run] would POST /api_key in the {label} shape")
            continue
        if ok(resp):
            try:
                data = resp.json()
            except ValueError:
                return "", "POST /api_key succeeded but the response was not JSON"
            key = (data or {}).get("key") or ""
            if not key:
                return "", (f"POST /api_key ({label} shape) returned no `key` field -- "
                            f"got {sorted((data or {}).keys())}. TrueNAS shows the "
                            f"plaintext key only in this response, so there is nothing "
                            f"to recover; delete the key it just made and re-run.")
            return key, ""
        last = f"{label} shape: HTTP {resp.status_code} {resp.text[:300]}"
        print(f"NOTE: /api_key rejected the {label} shape ({last})", file=sys.stderr)
    if dry_run:
        return "", ""
    return "", (f"could not create an API key. Last answer -- {last}\n"
                f"  This middleware takes neither shape this script knows. Do NOT guess: "
                f"look at `GET /api/v2.0/api_key` and the API docs on the NAS itself "
                f"(System > API Keys / the /api/docs page), then update ALLOWLIST/ROLES "
                f"in server/create_api_key.py.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="ccsync-dashboard",
                    help="the key's label in Credentials > API Keys. Use a new one per "
                         "rotation so the old key can be deleted by name.")
    ap.add_argument("--username", default="",
                    help="on TrueNAS >= 24.10 the account the key acts AS. Make a "
                         "dedicated non-shell account holding only "
                         + ", ".join(ROLES) + " -- defaults to $TRUENAS_USER, which is "
                         "the ADMIN and defeats the point.")
    ap.add_argument("--shape", choices=("auto", "username", "allowlist"), default="auto",
                    help="which /api_key body to send. auto tries username then allowlist.")
    add_host_key_arg(ap)
    add_site_arg(ap)
    add_nas_kind_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)

    if nas_kind(args) != "truenas":
        print("FAILED: API keys are a TrueNAS concept. DSM has none -- a Synology "
              "deployment keeps using the admin password in DASH_NAS_PW, and its "
              "mitigation is a dedicated non-administrator service account plus the "
              "loopback bind (docs/SERVER-SYNOLOGY.md).", file=sys.stderr)
        return 2

    import os

    username = args.username or os.environ.get("TRUENAS_USER", "")
    if not args.username:
        print(f"WARNING: no --username given, so the key would act as the ADMIN "
              f"({username or '<unset>'}). That is a key with root-equivalent rights -- "
              f"better than a password only because it can be revoked without changing "
              f"the login. Make a dedicated account holding {', '.join(ROLES)} and pass "
              f"it with --username.", file=sys.stderr)

    print(describe_scope())
    key, err = create_key(args.name, username, args.shape, args.dry_run)
    if err:
        print(f"FAILED: {err}", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    print(f"\ncreated API key: {args.name}")
    print("SHOWN ONCE -- TrueNAS stores it hashed and will not show it again:\n")
    print(f"    {key}\n")
    print("Put it in the deploy environment and redeploy; the admin password then "
          "stays out of the container:\n")
    print(f"    export TRUENAS_API_KEY={key}")
    print("    python server/install_dashboard_app.py\n")
    print("Revoke it in Credentials > API Keys when it is no longer needed.")
    return 0


if __name__ == "__main__":
    sys.exit(cli(main))
