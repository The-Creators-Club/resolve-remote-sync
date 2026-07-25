"""Tailscale direct-vs-DERP detection.

The verdict must come from `CurAddr`, not from `Relay == ""`: tailscaled
reports a peer's *home DERP region* in `Relay` even when the connection is a
perfectly direct UDP path, so keying on `Relay` mislabels most real peers --
and a mislabelled path invalidates every transfer number measured over it.
"""

from __future__ import annotations

import json

from ccbench.runners.iperf3 import describe_tailscale_path, parse_tailscale_status


def _status(**peer_fields) -> str:
    peer = {
        "HostName": "truenas",
        "DNSName": "truenas.tailnet.ts.net.",
        "TailscaleIPs": ["100.64.1.5"],
        "Relay": "",
        "CurAddr": "",
    }
    peer.update(peer_fields)
    return json.dumps({"Peer": {"nodekey:abc123": peer}})


def test_direct_when_cur_addr_is_set_even_though_relay_names_a_region():
    """The regression this test exists for: a direct peer that still carries a
    home DERP region was reported as RELAYED."""
    raw = _status(Relay="syd", CurAddr="203.0.113.9:41641")
    result = parse_tailscale_status(raw, "truenas")

    assert result["found"]
    assert result["direct"] is True
    assert result["cur_addr"] == "203.0.113.9:41641"
    assert result["relay"] == "syd"  # kept as supplementary detail, not the verdict
    assert "DIRECT" in describe_tailscale_path(result)


def test_relayed_when_cur_addr_is_empty():
    raw = _status(Relay="syd", CurAddr="")
    result = parse_tailscale_status(raw, "truenas")

    assert result["direct"] is False
    assert result["relay"] == "syd"
    assert "RELAYED" in describe_tailscale_path(result)
    assert "syd" in describe_tailscale_path(result)


def test_relayed_when_cur_addr_is_empty_and_relay_is_unknown():
    """No CurAddr and no region name is still not a direct path."""
    raw = _status(Relay="", CurAddr="")
    result = parse_tailscale_status(raw, "truenas")

    assert result["direct"] is False
    assert "RELAYED" in describe_tailscale_path(result)


def test_missing_cur_addr_key_is_treated_as_relayed():
    raw = json.dumps({"Peer": {"nodekey:abc": {"HostName": "truenas", "Relay": "syd"}}})
    result = parse_tailscale_status(raw, "truenas")
    assert result["direct"] is False


def test_null_cur_addr_is_treated_as_relayed():
    raw = _status(CurAddr=None, Relay=None)
    result = parse_tailscale_status(raw, "truenas")
    assert result["direct"] is False
    assert result["relay"] == ""


def test_peer_lookup_by_hostname_dns_name_key_and_ip():
    raw = _status(CurAddr="203.0.113.9:41641")
    for hint in ("truenas", "truenas.tailnet.ts.net.", "nodekey:abc123", "100.64.1.5"):
        assert parse_tailscale_status(raw, hint)["found"], hint


def test_unknown_peer_is_not_reported_as_direct():
    result = parse_tailscale_status(_status(CurAddr="203.0.113.9:41641"), "some-other-host")
    assert result["found"] is False
    assert result["direct"] is False
    assert describe_tailscale_path(result) == "peer not found"
