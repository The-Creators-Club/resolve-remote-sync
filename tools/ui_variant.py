r"""tools/ui_variant.py -- switch the dashboard's terminal look without
rendering a single terminal page (docs/UI_REDESIGN_PORT_PLAN.md R24).

The rollback control for the new look must not live only on a page the new
look might have broken, so this signs in like tools/jobs.py (same Client,
same password hygiene: a terminal prompt or --password-stdin, never argv or
the environment) and PUTs the one site setting:

    ui_variant.py off                 # every page group back to classic ("none")
    ui_variant.py site                # delete the row: follow the vendor default
    ui_variant.py set chrome,home     # these groups, for everyone
    ui_variant.py preview admins      # who may preview with the cookie: off|admins|everyone
    ui_variant.py show                # what is stored now

Run `off` BEFORE an image rollback past a phase whose group is on.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jobs import (EXIT_CALL, EXIT_USAGE, Client, Http, JobsError,  # noqa: E402
                  read_password)

GROUPS = ("chrome", "home", "everyday", "settings-fleet", "settings-health", "apps")
PREVIEW = ("off", "admins", "everyone")
DASHBOARD_URL_ENV = "CCSYNC_DASHBOARD_URL"
ADMIN_USER_ENV = "CCSYNC_ADMIN_USER"


def groups_value(raw: str) -> str:
    """Validate locally what the server would refuse anyway, so the error is
    immediate: unknown names, and any set without chrome (never added
    silently)."""
    items = [p.strip().lower() for p in str(raw or "").split(",") if p.strip()]
    unknown = sorted(set(items) - set(GROUPS))
    if unknown:
        raise JobsError(f"unknown group(s): {', '.join(unknown)} (the groups are "
                        f"{', '.join(GROUPS)})", EXIT_USAGE)
    if not items:
        raise JobsError("name at least one group, or use `off`", EXIT_USAGE)
    if "chrome" not in items:
        raise JobsError("every group needs chrome (the new header is part of every "
                        "new page); add it, or use `off`", EXIT_USAGE)
    return ",".join(g for g in GROUPS if g in items)


def payload(args: argparse.Namespace) -> dict | None:
    if args.command == "off":
        return {"values": {"ui_terminal_groups": "none"}}
    if args.command == "site":
        return {"values": {"ui_terminal_groups": "site"}}
    if args.command == "set":
        return {"values": {"ui_terminal_groups": groups_value(args.groups)}}
    if args.command == "preview":
        mode = str(args.mode or "").strip().lower()
        if mode not in PREVIEW:
            raise JobsError(f"preview must be one of {', '.join(PREVIEW)}", EXIT_USAGE)
        return {"values": {"ui_preview": mode}}
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ui_variant.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--dashboard-url", default=os.environ.get(DASHBOARD_URL_ENV, ""))
    p.add_argument("--admin-user", default=os.environ.get(ADMIN_USER_ENV, ""))
    p.add_argument("--password-stdin", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("off")
    sub.add_parser("site")
    s = sub.add_parser("set")
    s.add_argument("groups")
    pv = sub.add_parser("preview")
    pv.add_argument("mode")
    sub.add_parser("show")
    return p


def main(argv: list[str] | None = None, http: Http | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        body = payload(args)            # refuse a bad set before asking for a password
        if not args.dashboard_url:
            raise JobsError(f"--dashboard-url (or ${DASHBOARD_URL_ENV}) is required", EXIT_USAGE)
        if not args.admin_user:
            raise JobsError(f"--admin-user (or ${ADMIN_USER_ENV}) is required", EXIT_USAGE)
        client = Client(http or Http(), args.dashboard_url)
        client.login(args.admin_user, read_password(args.password_stdin,
                                                    f"password for {args.admin_user}: "))
        if body is None:
            site = client.call("GET", "/api/v1/admin/site")
        else:
            site = client.call("PUT", "/api/v1/admin/site", body)
        print(f"ui_terminal_groups = {site.get('ui_terminal_groups', '?')}")
        print(f"ui_preview = {site.get('ui_preview', '?')}")
        return 0
    except JobsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code if exc.code else EXIT_CALL


if __name__ == "__main__":
    sys.exit(main())
