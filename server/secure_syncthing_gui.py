#!/usr/bin/env python3
"""Put a username and password on Syncthing's GUI, and bind it narrowly.

    python secure_syncthing_gui.py [--gui-url http://<nas>:8384] [--dry-run]
    python secure_syncthing_gui.py --bind 127.0.0.1:8384        # loopback only
    python secure_syncthing_gui.py --show                       # report, change nothing

WHY. Syncthing's GUI is an unauthenticated administrative surface over EVERY
folder in the fleet: from it a visitor can add a device, re-point a folder at
another path, or turn off send-only and let a delete propagate. Until
2026-08-17 the TrueNAS install published it on all interfaces with no password
set (`bind_mode: published`, install_syncthing_app.py) -- finding H4 of
docs/COMMERCIAL_READINESS.md item 7. The Synology stack already binds it to
127.0.0.1 (dashboard/deploy/compose.yaml, profile "bundled-syncthing"), which
is the shape both platforms should end at.

WHAT IT CHANGES, via Syncthing's own REST API so it works the same on the
TrueNAS catalog app and the compose service:

    GET  /rest/config/gui       read the current GUI config
    PUT  /rest/config/gui       write it back with user/password set

  * `user` + `password` are set. Syncthing bcrypts a plaintext password on
    save, so the value written here never survives in the config file.
  * `insecureAdminAccess` is forced false -- it is the setting that lets
    anything reaching the GUI act as admin regardless of credentials.
  * `apiKey` IS LEFT ALONE. Every server script, the dashboard and
    check_health.py authenticate with `X-API-Key`, which is unaffected by GUI
    credentials -- adding a password does not break settings.syncthing_gui_url
    or any automation. That is the whole reason this is safe to run on a live
    fleet.
  * `--bind ADDR:PORT` sets `gui.address`. On the compose service that is the
    real bind; on the TrueNAS catalog app the container's own address must stay
    0.0.0.0 for docker's port map to work, and the HOST side is the app's
    `web_port` (site.toml [syncthing] gui_bind -- see install_syncthing_app.py).
    The script says which case it is in rather than pretending one knob does
    both.

THE PASSWORD IS SHOWN ONCE and written to ~/.ccsync/syncthing-gui.txt (0600) so
an operator who closes the terminal can still find it. It is not stored on the
NAS in plaintext anywhere.

Env vars: SYNCTHING_API_KEY (required), SYNCTHING_GUI_URL (or [syncthing]
gui_url in site.toml, or --gui-url).
"""
import argparse
import os
import secrets as _secrets
import string
import sys
from pathlib import Path

from common import (
    add_site_arg, cli, ok, require_env, require_site_value, site_value,
    syncthing_api,
)

DEFAULT_GUI_USER = "ccsync-admin"
# Long enough that it is never typed from memory, and out of an alphabet with
# no quoting hazards -- it goes in a browser prompt and a text file, nowhere
# that needs escaping.
PASSWORD_ALPHABET = string.ascii_letters + string.digits
PASSWORD_LEN = 28
CREDENTIALS_FILE = ".ccsync/syncthing-gui.txt"


def generate_password() -> str:
    return "".join(_secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LEN))


def credentials_path() -> Path:
    override = os.environ.get("CCSYNC_SYNCTHING_CREDS", "").strip()
    return Path(override) if override else Path.home() / CREDENTIALS_FILE


def write_credentials(gui_url: str, user: str, password: str) -> Path:
    """Record the credentials where the operator will look for them (0600)."""
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f"# Syncthing GUI credentials, written by server/secure_syncthing_gui.py\n"
        f"# The GUI is an admin surface over every folder in the fleet -- treat this\n"
        f"# like the NAS password. Automation does NOT use it (X-API-Key does).\n"
        f"url={gui_url}\nuser={user}\npassword={password}\n")
    # Created with 0600 (never world-readable even for an instant).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def read_gui_config(gui_url: str, api_key: str, dry_run: bool):
    resp = syncthing_api("GET", gui_url, "/rest/config/gui", api_key, dry_run=dry_run)
    if dry_run:
        return {}, ""
    if not ok(resp):
        code = getattr(resp, "status_code", "?")
        return None, (f"GET /rest/config/gui answered HTTP {code}. A 403 means the API "
                      f"key is wrong; a connection error means {gui_url} is not the GUI.")
    try:
        body = resp.json()
    except ValueError:
        return None, "GET /rest/config/gui: the response was not JSON"
    if not isinstance(body, dict):
        return None, "GET /rest/config/gui: the response was not a JSON object"
    return body, ""


def secure_gui(gui_url: str, api_key: str, user: str = DEFAULT_GUI_USER,
               password: str = "", bind: str = "") -> tuple[bool, str, str]:
    """Do what `main()` does, as a function the installers can call
    (CR-363 / GL-08, 2026-10-07; bug-server-3).

    `install_syncthing_app` used to print "run secure_syncthing_gui.py by hand"
    and leave the GUI an unauthenticated admin surface on every interface of
    the NAS until somebody did. It now calls this itself once the app is up.
    Returns (ok, message, password); the password is "" when nothing was set
    (the GUI already had a login, which is left alone). Never raises: a
    refusal is a message the installer prints.
    """
    current, err = read_gui_config(gui_url, api_key, False)
    if err:
        return False, err, ""
    if (current.get("user") or "").strip() and (current.get("password") or "").strip() \
            and not current.get("insecureAdminAccess") and not bind:
        return True, "the GUI already requires a login; left as it is", ""
    wanted = dict(current)
    wanted["insecureAdminAccess"] = False
    if bind:
        wanted["address"] = bind
    if (current.get("user") or "").strip() and (current.get("password") or "").strip() and not password:
        # Overseer fix (2026-10-07): an existing login with only
        # insecureAdminAccess on keeps its own password.
        resp = syncthing_api("PUT", gui_url, "/rest/config/gui", api_key, json_body=wanted)
        if not ok(resp):
            return False, (f"PUT /rest/config/gui answered HTTP "
                           f"{getattr(resp, 'status_code', '?')}"), ""
        return True, "insecureAdminAccess turned off; the existing GUI login was kept", ""
    password = password or generate_password()
    wanted["user"] = (current.get("user") or "").strip() or user
    wanted["password"] = password
    # CR-363 / GL-08 round 2 (2026-10-07): record the password BEFORE the
    # engine holds it. A PUT that lands with the write failing after it leaves
    # a login nobody knows, and a rerun then says "already requires a login".
    existed = credentials_path().exists()
    try:
        path = write_credentials(gui_url, wanted["user"], password)
    except OSError as exc:
        return False, (f"could not record the GUI password at {credentials_path()} "
                       f"({exc}); the Syncthing GUI was NOT changed"), ""
    resp = syncthing_api("PUT", gui_url, "/rest/config/gui", api_key, json_body=wanted)
    if not ok(resp):
        if not existed:
            try:
                path.unlink()       # a file naming a password the engine never took
            except OSError:
                pass
        return False, (f"PUT /rest/config/gui answered HTTP "
                       f"{getattr(resp, 'status_code', '?')}"), ""
    return True, (f"the GUI now requires a login (user {wanted['user']}; "
                  f"credentials in {path}, mode 0600)"), password


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gui-url", default="",
                    help="Syncthing's GUI base URL; defaults to $SYNCTHING_GUI_URL, "
                         "then [syncthing] gui_url in site.toml")
    ap.add_argument("--api-key", default="", help="defaults to $SYNCTHING_API_KEY")
    ap.add_argument("--user", default=DEFAULT_GUI_USER)
    ap.add_argument("--password", default="",
                    help="defaults to a generated one, printed once")
    ap.add_argument("--bind", default="",
                    help="set gui.address, e.g. 127.0.0.1:8384. Leave unset to keep "
                         "whatever the GUI is bound to now.")
    ap.add_argument("--show", action="store_true",
                    help="report the current GUI auth/bind state and change nothing")
    add_site_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gui_url = require_site_value(
        args.gui_url or os.environ.get("SYNCTHING_GUI_URL", "") or site_value("syncthing", "gui_url"),
        "[syncthing] gui_url", "--gui-url").rstrip("/")
    api_key = args.api_key or ("<SYNCTHING_API_KEY-unset-dry-run>" if args.dry_run
                               else require_env("SYNCTHING_API_KEY"))

    current, err = read_gui_config(gui_url, api_key, args.dry_run)
    if err:
        print(f"FAILED: {err}", file=sys.stderr)
        return 1

    if args.show:
        if args.dry_run:
            print("[dry-run] would report the GUI's user/address/insecureAdminAccess")
            return 0
        has_user = bool((current.get("user") or "").strip())
        print(f"Syncthing GUI at {gui_url}")
        print(f"  address:              {current.get('address', '?')}")
        print(f"  user:                 {current.get('user') or '(none -- UNAUTHENTICATED)'}")
        print(f"  insecureAdminAccess:  {current.get('insecureAdminAccess')}")
        if not has_user:
            print("\nAnyone who can reach that address is a Syncthing administrator over "
                  "every folder in the fleet. Re-run without --show to fix it.",
                  file=sys.stderr)
        return 0 if has_user else 1

    password = args.password or generate_password()
    wanted = dict(current)
    wanted["user"] = args.user
    wanted["password"] = password
    # The one setting that makes the password decorative if it is left on.
    wanted["insecureAdminAccess"] = False
    if args.bind:
        wanted["address"] = args.bind

    if args.dry_run:
        print(f"[dry-run] would PUT /rest/config/gui at {gui_url} setting user="
              f"{args.user!r}, a generated password, insecureAdminAccess=False"
              + (f", address={args.bind!r}" if args.bind else "")
              + f"; the API key is left untouched, so nothing that uses X-API-Key "
                f"(the dashboard, every server script) is affected.")
        print(f"[dry-run] would write the credentials to {credentials_path()} (0600)")
        return 0

    resp = syncthing_api("PUT", gui_url, "/rest/config/gui", api_key, json_body=wanted)
    if not ok(resp):
        code = getattr(resp, "status_code", "?")
        print(f"FAILED: PUT /rest/config/gui answered HTTP {code} "
              f"{getattr(resp, 'text', '')[:300]}", file=sys.stderr)
        return 1

    path = write_credentials(gui_url, args.user, password)
    print(f"Syncthing GUI at {gui_url} now requires a login.")
    print(f"  user:     {args.user}")
    print(f"  password: {password}")
    print(f"  (also written to {path}, mode 0600 -- SHOWN ONCE)")
    if args.bind:
        print(f"  address:  {args.bind}")
        print("  NOTE: on the TrueNAS catalog app the container must keep listening on "
              "0.0.0.0 for docker's port map to work -- restrict the HOST side with "
              "site.toml [syncthing] gui_bind instead (docs/SERVER.md).")
    print("\nThe API key was NOT changed: the dashboard, setup_syncthing_folder.py, "
          "accept_device.py and check_health.py all authenticate with X-API-Key and "
          "keep working unchanged.")

    restart = syncthing_api("GET", gui_url, "/rest/config/restart-required", api_key)
    if ok(restart):
        try:
            if (restart.json() or {}).get("requiresRestart"):
                print("Syncthing says a restart is required for this to take effect: "
                      "restart the app (TrueNAS Apps > syncthing) or the container.")
        except ValueError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(cli(main))
