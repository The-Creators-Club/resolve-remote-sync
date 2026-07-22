"""iperf3 raw-throughput ceiling + Tailscale direct-vs-DERP verification.

This is not a file-transfer runner (dataset_dir/manifest are irrelevant --
iperf3 just pushes synthetic TCP traffic), but it shares the RunResult shape
so it slots into the same results.jsonl / report as the file-transfer
engines, letting the report show "here's the network ceiling" alongside
"here's what each transport actually achieved".

Sweeps -P {1,4,8} parallel streams, both directions (-R for "down" = server
sends to client).

Also exposes `check_tailscale_path()`, which shells out to
`tailscale status --json` (a purely local query of the already-running
tailscaled daemon's cached peer state -- it does not itself open a
connection to the peer) and reports whether the path to a given peer is
direct or relayed via DERP (`Peer[*].Relay` empty vs set). A relayed path
caps throughput well below Blackmagic Cloud's ~60 mb/s baseline, so this is
usually the first thing to check before blaming any transport engine.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ccbench.result import RunResult, make_skipped

from . import base

ENGINE = "iperf3"

DEFAULT_DURATION_S = 10


def available() -> tuple[bool, str]:
    return base.which("iperf3")


def param_matrix(cfg: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    parallel_values = base.expand_sweep(cfg.get("parallel"), [1, 4, 8])
    duration = cfg.get("duration_s", DEFAULT_DURATION_S)
    return [{"parallel": p, "duration_s": duration} for p in parallel_values]


def _run_iperf3_client(
    host: str,
    port: int,
    parallel: int,
    reverse: bool,
    duration_s: float,
    timeout: float | None,
) -> tuple[int, dict[str, Any] | None, str]:
    cmd = [
        "iperf3",
        "-c", host,
        "-p", str(port),
        "-P", str(parallel),
        "-t", str(int(duration_s)),
        "-J",
    ]
    if reverse:
        cmd.append("-R")
    rc, out, err, _seconds = base.run_subprocess(cmd, timeout=timeout)
    parsed = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = None
    return rc, parsed, err


def run(
    dataset_dir: Path | None,
    direction: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
    *,
    dataset_name: str = "network",
    verify: bool = True,
    keep_remote_data: bool = False,
    dest_dir: Path | None = None,
    lane: str = "",
    repeat_index: int = 0,
    timeout: float | None = 120,
) -> RunResult:
    ok, reason = available()
    if not ok:
        return make_skipped(ENGINE, dataset_name, direction, params, reason, lane, "", repeat_index)

    host = endpoint.get("host")
    if not host:
        return make_skipped(
            ENGINE, dataset_name, direction, params, "no iperf3 host configured", lane, "", repeat_index
        )
    port = int(endpoint.get("port", 5201))
    parallel = int(params.get("parallel", 1))
    duration_s = float(params.get("duration_s", DEFAULT_DURATION_S))
    reverse = direction == "down"

    rc, parsed, err = _run_iperf3_client(host, port, parallel, reverse, duration_s, timeout)

    if rc != 0 or parsed is None or "error" in (parsed or {}):
        err_detail = (parsed or {}).get("error", "") if parsed else ""
        return RunResult(
            engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
            seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
            reason=f"iperf3 exit {rc}: {err_detail or base.tail(err)}",
            lane=lane, endpoint=f"{host}:{port}", repeat_index=repeat_index,
        )

    summary = parsed["end"]["sum_received"]
    num_bytes = int(summary["bytes"])
    seconds = float(summary["seconds"])

    return RunResult(
        engine=ENGINE,
        dataset=dataset_name,
        direction=direction,
        params=params,
        seconds=seconds,
        num_bytes=num_bytes,
        MB_s=base.mb_per_s(num_bytes, seconds),
        verified=True,  # iperf3's own goodput accounting; no separate file check applies
        ok=True,
        reason="",
        lane=lane,
        endpoint=f"{host}:{port}",
        repeat_index=repeat_index,
    )


# ---------------------------------------------------------------------------
# Tailscale direct-vs-DERP check
# ---------------------------------------------------------------------------


def get_tailscale_status_json(timeout: float = 15) -> str | None:
    """Local-only query of the already-running tailscaled daemon's cached peer
    state. Does not itself contact any peer."""
    ok, _reason = base.which("tailscale")
    if not ok:
        return None
    try:
        proc = subprocess.run(
            ["tailscale", "status", "--json"], capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode == 0:
            return proc.stdout
    except Exception:
        pass
    return None


def parse_tailscale_status(raw_json: str, peer_hint: str) -> dict[str, Any]:
    """Find a peer in `tailscale status --json` output by hostname, DNS name,
    node key, or (substring of) a TailscaleIP, and report direct-vs-relay."""
    data = json.loads(raw_json)
    peers = data.get("Peer", {}) or {}
    for key, info in peers.items():
        hostname = info.get("HostName", "") or ""
        dns_name = info.get("DNSName", "") or ""
        ips = info.get("TailscaleIPs", []) or []
        matches_ip = any(peer_hint == ip or peer_hint in ip for ip in ips)
        if peer_hint in (hostname, dns_name, key) or matches_ip:
            relay = info.get("Relay", "") or ""
            return {
                "found": True,
                "peer_key": key,
                "hostname": hostname,
                "direct": relay == "",
                "relay": relay,
                "cur_addr": info.get("CurAddr", ""),
            }
    return {"found": False, "peer_key": None, "hostname": None, "direct": False, "relay": None, "cur_addr": None}


def check_tailscale_path(peer_hint: str) -> dict[str, Any]:
    """Convenience wrapper: query local tailscaled + parse for peer_hint,
    printing a loud warning if the path is DERP-relayed instead of direct."""
    raw = get_tailscale_status_json()
    if raw is None:
        return {"found": False, "reason": "tailscale not available or `status --json` failed"}
    result = parse_tailscale_status(raw, peer_hint)
    if result["found"] and not result["direct"]:
        print(
            f"WARNING: Tailscale path to {peer_hint!r} is RELAYED via DERP "
            f"({result['relay']}) -- expect throughput far below a direct "
            f"connection. Check UDP 41641 forwarding / NAT traversal before "
            f"trusting any transfer benchmark numbers."
        )
    return result
