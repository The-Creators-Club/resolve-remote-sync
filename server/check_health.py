#!/usr/bin/env python3
"""One command to validate the whole server side. Plain PASS/FAIL lines,
exit code = number of failed checks (0 = all good).

    python check_health.py [--gui-url http://<nas>:8384 --api-key XXXX] [--dry-run]

Checks:
  1. Postgres reachable on :5432 (raw TCP connect -- proves resolve-
     projectserver is up and port-forwarded, not that auth works).
  2. Tailscale container logged in: SSH in, `docker exec tailscale tailscale
     status --json`, report tailnet IP and BackendState; FAIL if logged out.
     Also reports, per peer, whether the path is DIRECT or DERP-relayed --
     "logged in" says nothing about whether bytes are flowing over a direct
     UDP path or being proxied through a relay (AUDIT_2 P14).
  2b. Tailnet path from THIS machine to the NAS: same direct-vs-relayed
     check against the local tailscaled. Non-fatal WARNING when relayed.
  3. Syncthing app up: GET /rest/system/ping against --gui-url.
  4. Syncthing folders listed: GET /rest/config/folders, print count + ids.
  5. Project tree exists: SSH `test -d` on the Projects root.
  6. Editor accounts exist: TrueNAS API, list members of the `editors`
     group.
  7. Dashboard up: GET <dashboard-url>/api/v1/health -- reports its version
     and whether IT can reach Syncthing (the companions' whole managed mode
     depends on this endpoint answering).

--dry-run prints the exact checks that would run (SSH commands / API
calls) without opening any connection, same convention as every other
script in this package.

Env vars: TRUENAS_HOST / TRUENAS_USER (no defaults -- they come from [nas]
host / admin_user in site.toml, see docs/SERVER.md), TRUENAS_PW (required). SYNCTHING_GUI_URL / SYNCTHING_API_KEY
used as fallback defaults for --gui-url / --api-key; DASHBOARD_URL for
--dashboard-url. DASH_REPORT_TOKEN (optional) unlocks the dashboard's
detailed /api/v1/health body -- without it check 7 reports liveness only.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from urllib.parse import urlparse

from common import (  # noqa: F401 - synology_api/truenas_api/run_ssh are also
    # the names ScriptCalls resolves the backend's NAS access through, and the
    # offline suite patches them HERE (see common.ScriptCalls).
    DEFAULT_PROJECTS_ROOT,
    DEFAULT_TRUENAS_HOST,
    EDITORS_GROUP,
    ScriptCalls,
    add_host_key_arg,
    add_nas_kind_arg,
    add_site_arg,
    cli,
    get_backend,
    ok,
    require_site_value,
    run_ssh,
    set_host_key_pin,
    shell_quote,
    site_bool,
    site_value,
    syncthing_api,
    synology_api,
    truenas_api,
    truenas_conn_params,
)

# Which NAS this is. check_tailscale() is called with no backend argument (by
# main and by server/tests alike), so the choice lives on the module: main()
# sets it from --nas-kind, and anything calling in directly gets the kind from
# $CCSYNC_NAS_KIND / site.toml. ScriptCalls binds it to THIS module's run_ssh,
# which is what the offline tailscale tests patch (2026-08-17).
_ARGS = None
_BACKEND = None


def backend():
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = get_backend(_ARGS, calls=ScriptCalls(sys.modules[__name__]))
    return _BACKEND

# Where the companions are pointed by default (companion/config.example.toml
# and the installer both use the tailnet address).
# Blank when the site does not say (2026-08-17): it used to be this fleet's own
# tailnet address, so a fresh checkout health-checked someone else's dashboard.
DEFAULT_DASHBOARD_URL = site_value("net", "dashboard_url")

# Hostname the NAS registers on the tailnet, used as a fallback peer hint when
# the dashboard URL is not a tailnet address (a Synology site publishes on
# loopback, so it never is). "truenas" is this fleet's own machine name and a
# poor guess anywhere else -- [net] tailnet_name says what the box is really
# called, and a wrong hint only costs a skipped WARNING.
DEFAULT_NAS_TAILNET_NAME = site_value("net", "tailnet_name") or "truenas"

RESULTS = []  # list of (bool_passed, str_message)
WARNINGS = []  # non-fatal: printed, never counted in the exit code


def report(passed: bool, message: str):
    RESULTS.append((passed, message))
    status = "PASS" if passed else "FAIL"
    print(f"{status}: {message}")


def warn(message: str):
    """A real problem that must not fail the health check.

    A DERP-relayed path is the motivating case: everything still WORKS, it
    is just slow, so failing the run would be wrong -- but staying silent is
    how the dashboard ends up showing a slow editor with no cause (P14).
    """
    WARNINGS.append(message)
    print(f"WARN: {message}")


def info(message: str):
    print(f"      {message}")


def _printable(text) -> str:
    """Peers have non-ASCII hostnames (this tailnet has a CJK one), and a
    Windows console is cp1252 -- printing one raises UnicodeEncodeError and
    takes the whole health check down. Degrade the characters, not the run.
    """
    text = "" if text is None else str(text)
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, "replace").decode(encoding, "replace")
    return text


# ---------------------------------------------------------------------------
# Tailscale direct-vs-DERP (AUDIT_2 P14)
#
# DELIBERATELY DUPLICATED from bench/ccbench/runners/iperf3.py rather than
# imported: server/ and bench/ are separate deployables with separate
# requirements, and neither may take a source dependency on the other. The
# decision rule below must stay identical in both.
# ---------------------------------------------------------------------------


def peer_path(info_dict: dict) -> dict:
    """Direct-vs-relayed for one `tailscale status --json` Peer entry.

    **The signal is `CurAddr`, not `Relay`.** `Relay` is the peer's HOME DERP
    region: it stays populated on a perfectly direct connection, and it is
    empty for a peer that has no home region at all. Both mistakes are live
    on this tailnet -- measured, 2 of 7 peers are classified differently by
    the two rules. `CurAddr` is the endpoint traffic is actually using:
    non-empty means a direct UDP path, empty means DERP. `Relay` is kept as
    supplementary detail (which region is carrying the relayed traffic).
    """
    cur_addr = info_dict.get("CurAddr", "") or ""
    return {
        "hostname": info_dict.get("HostName", "") or "",
        "ips": list(info_dict.get("TailscaleIPs", []) or []),
        "online": bool(info_dict.get("Online", False)),
        "direct": cur_addr != "",
        "cur_addr": cur_addr,
        "relay": info_dict.get("Relay", "") or "",
    }


def parse_tailscale_status(raw_json: str, peer_hint: str) -> dict:
    """Find a peer by hostname, DNS name, node key or TailscaleIP and report
    its path. Mirrors bench's helper of the same name."""
    data = json.loads(raw_json)
    peers = data.get("Peer", {}) or {}
    for key, info_dict in peers.items():
        hostname = info_dict.get("HostName", "") or ""
        dns_name = info_dict.get("DNSName", "") or ""
        ips = info_dict.get("TailscaleIPs", []) or []
        matches_ip = any(peer_hint == ip or peer_hint in ip for ip in ips)
        if peer_hint and (peer_hint in (hostname, dns_name, key) or matches_ip):
            result = peer_path(info_dict)
            result.update({"found": True, "peer_key": key})
            return result
    return {
        "found": False, "peer_key": None, "hostname": None, "ips": [],
        "online": False, "direct": False, "cur_addr": None, "relay": None,
    }


def describe_tailscale_path(result: dict) -> str:
    """One-line human description of a parse_tailscale_status() result."""
    if not result.get("found"):
        return "peer not found"
    if result["direct"]:
        via_home = f" (home DERP {result['relay']})" if result.get("relay") else ""
        return f"DIRECT via {result['cur_addr']}{via_home}"
    relay = result.get("relay") or "unknown region"
    return f"RELAYED via DERP {relay} (no direct CurAddr)"


def tailscale_peer_paths(raw_json: str) -> list:
    """Every peer's path, sorted by hostname."""
    data = json.loads(raw_json)
    peers = data.get("Peer", {}) or {}
    return sorted((peer_path(p) for p in peers.values()), key=lambda p: p["hostname"].lower())


def relay_advice(who: str, relay: str) -> str:
    return (
        f"{who} is RELAYED through Tailscale's DERP {relay or '<unknown>'} relay "
        f"(CurAddr is empty -- no direct UDP path). Every byte lanes A/B/C move "
        f"is being proxied: expect a fraction of the direct tailnet speed, and "
        f"no rclone tuning will fix it. Check UDP 41641 reachability both ways "
        f"(router/firewall, CGNAT, and the tailscale container's network mode); "
        f"`tailscale netcheck` on both ends names the blocker."
    )


def check_postgres(dry_run: bool):
    """The Resolve Project Server, TCP-probed.

    Opt-out since 2026-08-17 ([stack] project_server = false): a Synology site
    carries Postgres as a compose PROFILE that is off unless asked for, and a
    site that never deployed one should not have a permanent FAIL in the one
    command whose whole contract is its exit code. Default is true, so nothing
    changes for a site that says nothing.
    """
    if not site_bool("stack", "project_server", True):
        info("postgres: not part of this site ([stack] project_server = false) -- "
             "skipped. Resolve project sharing needs one; deploy it with "
             "`docker compose --profile project-server up -d` (Synology) or as its "
             "own app (TrueNAS).")
        return
    host, _, _ = truenas_conn_params(dry_run=dry_run)
    port = 5432
    if dry_run:
        print(f"[dry-run] would TCP-connect to {host}:{port}")
        return
    try:
        with socket.create_connection((host, port), timeout=5):
            report(True, f"postgres reachable at {host}:{port}")
    except OSError as e:
        report(False, f"postgres NOT reachable at {host}:{port} ({e})")


def check_tailscale(dry_run: bool):
    # HOW tailscale is reached is the backend's business (a container on
    # TrueNAS, the DSM package on Synology); the parsing and the reporting
    # below are not, and stay here (2026-08-17).
    rc, out, err = backend().tailscale_status_json(dry_run)
    if dry_run:
        return
    if rc != 0:
        report(False, f"could not run `tailscale status --json` in the tailscale container "
                       f"(SSH/docker exec exit {rc}): {err.strip() or out.strip()}")
        return
    try:
        status = json.loads(out)
    except ValueError:
        report(False, f"tailscale status output was not valid JSON: {out[:200]!r}")
        return
    backend_state = status.get("BackendState", "<unknown>")
    self_info = status.get("Self", {}) or {}
    tailnet_ips = self_info.get("TailscaleIPs", [])
    if backend_state == "Running":
        report(True, f"tailscale logged in (BackendState=Running), tailnet IP(s): {tailnet_ips}")
    else:
        report(False, f"tailscale NOT logged in (BackendState={backend_state!r}) -- run `tailscale up` "
                       f"in the container to re-auth")
        return

    # "Logged in" is not "fast". Report the actual path per peer, from the
    # NAS's own vantage point: these are the editors, and a relayed one is
    # an editor whose uploads are being proxied through a DERP relay
    # (AUDIT_2 P14). Offline peers are listed but never warned about --
    # a laptop that is simply shut has no path to be wrong about.
    try:
        paths = tailscale_peer_paths(out)
    except ValueError:
        return
    for peer in paths:
        name = _printable(peer["hostname"] or "<unnamed>")
        ip = peer["ips"][0] if peer["ips"] else "?"
        if not peer["online"]:
            info(f"peer {name} ({ip}): offline")
        elif peer["direct"]:
            home = f", home DERP {peer['relay']}" if peer["relay"] else ""
            info(f"peer {name} ({ip}): DIRECT via {peer['cur_addr']}{home}")
        else:
            warn(relay_advice(f"NAS <-> peer {name} ({ip})", peer["relay"]))


def check_tailscale_path_from_here(peer_hints, dry_run: bool):
    """Direct-vs-DERP for the NAS as seen from the machine running this
    script -- the other half of P14, and the half that matches what an
    editor's companion experiences.

    Local-only query of the already-running tailscaled's cached peer state;
    it contacts no peer itself. Never FAILs: no local tailscale (an admin
    box outside the tailnet) is a skip, and a relayed path is a WARNING.
    """
    hints = [h for h in peer_hints if h]
    if dry_run:
        print(f"[dry-run] would run `tailscale status --json` locally and check the "
              f"path to the NAS peer (hints: {hints})")
        return
    exe = shutil.which("tailscale")
    if exe is None:
        info("tailnet path from here: skipped -- no `tailscale` binary on this machine")
        return
    try:
        proc = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=15)
    except Exception as e:  # noqa: BLE001 - any transport failure is one answer
        info(f"tailnet path from here: skipped -- `tailscale status --json` failed ({e})")
        return
    if proc.returncode != 0:
        info(f"tailnet path from here: skipped -- `tailscale status --json` exited "
             f"{proc.returncode}: {(proc.stderr or '').strip()[:160]}")
        return

    result = {"found": False}
    for hint in hints:
        try:
            result = parse_tailscale_status(proc.stdout, hint)
        except ValueError:
            info("tailnet path from here: skipped -- `tailscale status --json` was not JSON")
            return
        if result.get("found"):
            break
    if not result.get("found"):
        info(f"tailnet path from here: NAS peer not found in the local tailnet "
             f"(tried {hints}) -- is this machine on the same tailnet?")
        return

    name = _printable(result["hostname"] or "<unnamed>")
    ip = result["ips"][0] if result.get("ips") else "?"
    if result["direct"]:
        print(f"PATH: tailnet path from here to the NAS ({name}, {ip}) is "
              f"{describe_tailscale_path(result)}")
    else:
        warn(relay_advice(f"the tailnet path from this machine to the NAS ({name}, {ip})",
                          result.get("relay")))


def check_syncthing_app(gui_url, api_key, dry_run: bool):
    if not gui_url or not api_key:
        if dry_run:
            print("[dry-run] would check syncthing app/folders, but --gui-url/--api-key "
                  "(or SYNCTHING_GUI_URL/SYNCTHING_API_KEY) were not provided")
        else:
            report(False, "syncthing GUI/API check skipped -- pass --gui-url/--api-key "
                           "or set SYNCTHING_GUI_URL/SYNCTHING_API_KEY")
        return
    # A health CHECK must not crash on the thing it is checking (2026-08-17):
    # this raised requests.ConnectionError straight out of main() when the GUI
    # was unreachable -- which is the single most likely state for it to be in,
    # and the one a run is asking about. It is also the normal state on
    # Synology, where the GUI is published on 127.0.0.1 of the NAS and this
    # script runs on an admin workstation (tunnel it: ssh -L 8384:127.0.0.1:8384).
    try:
        resp = syncthing_api("GET", gui_url, "/rest/system/ping", api_key, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 - any transport failure is one answer
        report(False, f"syncthing app NOT reachable at {gui_url} "
                      f"({type(exc).__name__}: {str(exc)[:160]})")
        return
    if dry_run:
        return
    if ok(resp):
        report(True, f"syncthing app reachable at {gui_url}")
    else:
        code = resp.status_code if resp is not None else "<no response>"
        report(False, f"syncthing app NOT reachable at {gui_url} (HTTP {code})")
        return

    try:
        resp = syncthing_api("GET", gui_url, "/rest/config/folders", api_key,
                             dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        report(False, f"could not list syncthing folders ({type(exc).__name__})")
        return
    if ok(resp):
        folders = resp.json()
        ids = [f.get("id") for f in folders]
        report(True, f"syncthing folders listed: {len(folders)} folder(s): {ids}")
    else:
        report(False, f"could not list syncthing folders (HTTP {resp.status_code if resp else '?'})")


def check_tree(projects_root: str, dry_run: bool):
    # sudo: TRUENAS_USER itself has no traverse rights on the 770 dataset,
    # so an unprivileged test -d false-negatives even when the tree exists.
    cmd = (f'echo "$SUDO_PW" | sudo -S -p "" test -d {shell_quote(projects_root)} '
           f"&& echo PRESENT || echo MISSING")
    rc, out, err = run_ssh(cmd, dry_run=dry_run)
    if dry_run:
        return
    if "PRESENT" in out:
        report(True, f"project tree root exists: {projects_root}")
    else:
        report(False, f"project tree root MISSING: {projects_root}")
        return

    # Platform-specific follow-up: on Synology, "the directory is there" says
    # nothing about whether editors can WRITE to it -- group write is pure ACE
    # and a single chmod destroys it silently (docs/synology-spikes-2026-08-17
    # spike 1). Capability-probed rather than branched on kind, so a backend
    # that has no such question simply does not answer it.
    check_acl = getattr(backend(), "check_tree_acl", None)
    if check_acl is None:
        return
    ok_acl, message = check_acl(projects_root, EDITORS_GROUP, dry_run)
    if ok_acl is None:
        if message:
            warn(f"tree ACL: {message}")
    else:
        report(ok_acl, message)


def check_editor_accounts(dry_run: bool):
    # A backend that can answer this itself does (Synology: two DSM calls);
    # the TrueNAS path below is the original two REST calls, unchanged, and
    # stays here because its SERVER-3 subtlety is about TrueNAS's own schema.
    lister = getattr(backend(), "list_group_members", None)
    if lister is not None:
        found, members, detail = lister(EDITORS_GROUP, dry_run)
        if dry_run:
            return
        if found is None:
            report(False, f"could not list members of group {EDITORS_GROUP!r}: {detail}")
        elif not found:
            report(False, detail or f"group {EDITORS_GROUP!r} does not exist")
        elif members:
            report(True, f"editor accounts found in group {EDITORS_GROUP!r}: {members}")
        else:
            report(False, f"group {EDITORS_GROUP!r} exists but has no members yet")
        return

    resp = truenas_api("GET", "/group", params={"group": EDITORS_GROUP}, dry_run=dry_run)
    if dry_run:
        print(f"[dry-run] would also GET /user and cross-reference group membership for {EDITORS_GROUP!r}")
        return
    if not ok(resp):
        report(False, f"could not query group {EDITORS_GROUP!r} (HTTP {resp.status_code})")
        return
    groups = [g for g in resp.json() if g.get("group") == EDITORS_GROUP]
    if not groups:
        report(False, f"group {EDITORS_GROUP!r} does not exist -- no editor accounts can exist yet")
        return
    # SERVER-3 (2026-08-14): membership is keyed on the group's DATABASE id,
    # not its unix gid -- setup_editor_account.ensure_group carries the same
    # note ("passing the gid fails validation with 'This group does not exist'",
    # learned against the live 25.10 API) and returns the two as separate
    # values for exactly this reason. Testing the unix gid found no members on
    # a fully provisioned NAS, so check 6 always FAILed and check_health could
    # never exit 0 -- the one command whose whole contract is its exit code.
    # `group` is a nested object, so it is unwrapped, never compared to an int
    # (dashboard/src/ccsync_dashboard/truenas_client.py:165 is the canonical
    # form of this test).
    grp = groups[0]
    db_id, unix_gid = grp.get("id"), grp.get("gid")
    if db_id is None:
        report(False, f"group {EDITORS_GROUP!r} row carries no database id, so its "
                      f"membership cannot be checked: {sorted(grp)}")
        return

    resp = truenas_api("GET", "/user", dry_run=dry_run)
    if not ok(resp):
        report(False, f"could not list users (HTTP {resp.status_code})")
        return
    members = [u["username"] for u in resp.json()
               if db_id in (u.get("groups") or [])
               or (u.get("group") or {}).get("id") == db_id]
    if members:
        report(True, f"editor accounts found in group {EDITORS_GROUP!r} "
                     f"(gid {unix_gid}): {members}")
    else:
        report(False, f"group {EDITORS_GROUP!r} exists but has no members yet")


def check_dashboard(dashboard_url: str, dry_run: bool):
    """GET /api/v1/health on the dashboard.

    Works with no credentials at all -- this check must run from an admin box
    with no session cookie -- but /health now answers an UNAUTHENTICATED
    caller with `{"ok", "version"}` only: the full body carries project slugs,
    labels and Syncthing folder errors, i.e. the client roster, and the route
    is open by design for the container healthcheck. DASH_REPORT_TOKEN (the
    same shared secret the companions hold) unlocks the detail, so set it in
    the environment to get the collector-level verdict instead of plain
    liveness.
    """
    url = dashboard_url.rstrip("/") + "/api/v1/health"
    token = os.environ.get("DASH_REPORT_TOKEN", "").strip()
    if dry_run:
        print(f"[dry-run] would GET {url}"
              + (" with X-CCSync-Token" if token else " (no DASH_REPORT_TOKEN: liveness only)"))
        return

    import requests  # noqa: PLC0415 -- keep dry-run import-free like the rest

    headers = {"X-CCSync-Token": token} if token else {}
    try:
        resp = requests.get(url, timeout=10, headers=headers)
    except Exception as e:  # noqa: BLE001 - any transport failure is one answer
        report(False, f"dashboard NOT reachable at {url} ({type(e).__name__}: {e})")
        return
    if not ok(resp):
        report(False, f"dashboard unhealthy at {url} (HTTP {resp.status_code})")
        return
    try:
        body = resp.json()
    except ValueError:
        report(False, f"dashboard at {url} did not return JSON: {resp.text[:120]!r}")
        return
    version = body.get("version", "<unknown>")
    if "syncthing_reachable" not in body:
        # Liveness-only answer: say so rather than inventing a verdict about a
        # collector this caller was not allowed to see.
        report(bool(body.get("ok")),
               f"dashboard is up at {dashboard_url} (version {version}); "
               f"ok={body.get('ok')!r}. Set DASH_REPORT_TOKEN to also check whether its "
               f"collector can see Syncthing.")
        return
    st_ok = body.get("syncthing_reachable")
    if st_ok:
        report(True, f"dashboard healthy at {dashboard_url} (version {version}, "
                     f"syncthing reachable from the dashboard)")
    else:
        report(False, f"dashboard is up at {dashboard_url} (version {version}) but reports "
                      f"syncthing_reachable={st_ok!r} -- its collector cannot see Syncthing, "
                      f"so lane C status and project provisioning are stale")


def nas_peer_hints(explicit, dashboard_url: str) -> list:
    """Which names/IPs to look the NAS up by in the local tailnet.

    The dashboard URL is the companions' own pointer at the NAS, so its host
    is the most accurate hint available -- but only when it is a tailnet
    (100.64.0.0/10 / CGNAT) address; a LAN IP would match nothing.
    """
    if explicit:
        return [explicit]
    hints = []
    host = ""
    try:
        host = urlparse(dashboard_url or "").hostname or ""
    except ValueError:
        host = ""
    if host.startswith("100."):
        hints.append(host)
    elif host and not host[0].isdigit():
        hints.append(host)
    hints.append(DEFAULT_NAS_TAILNET_NAME)
    return hints


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gui-url", default=os.environ.get("SYNCTHING_GUI_URL"))
    ap.add_argument("--api-key", default=os.environ.get("SYNCTHING_API_KEY"))
    ap.add_argument("--dashboard-url",
                    default=os.environ.get("DASHBOARD_URL", DEFAULT_DASHBOARD_URL),
                    help=f"dashboard base URL, default {DEFAULT_DASHBOARD_URL} "
                         f"(or DASHBOARD_URL)")
    ap.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT)
    ap.add_argument("--tailscale-peer",
                    help="hostname or tailnet IP of the NAS peer for the local "
                         "direct-vs-DERP check (default: the dashboard URL's host "
                         f"if it is a tailnet address, else {DEFAULT_NAS_TAILNET_NAME!r})")
    add_host_key_arg(ap)
    add_site_arg(ap)
    add_nas_kind_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)
    global _ARGS
    _ARGS = args
    args.projects_root = require_site_value(
        args.projects_root, "[tree] pool_root/tree_name", "--projects-root")
    args.dashboard_url = require_site_value(
        args.dashboard_url, "[net] dashboard_url", "--dashboard-url")

    print(f"Checking Creators Club sync server ({os.environ.get('TRUENAS_HOST', DEFAULT_TRUENAS_HOST)})...\n")

    check_postgres(args.dry_run)
    check_tailscale(args.dry_run)
    check_tailscale_path_from_here(
        nas_peer_hints(args.tailscale_peer, args.dashboard_url), args.dry_run
    )
    check_syncthing_app(args.gui_url, args.api_key, args.dry_run)
    check_tree(args.projects_root, args.dry_run)
    check_editor_accounts(args.dry_run)
    check_dashboard(args.dashboard_url, args.dry_run)

    if args.dry_run:
        print("\n[dry-run] no checks were actually executed.")
        return 0

    failed = [msg for passed, msg in RESULTS if not passed]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed.")
    if WARNINGS:
        # Non-fatal by design (see warn()): these do not move the exit code.
        print(f"{len(WARNINGS)} warning(s) -- nothing is broken, but something is slow:")
        for message in WARNINGS:
            print(f"  - {message}")
    return len(failed)


if __name__ == "__main__":
    sys.exit(cli(main))
