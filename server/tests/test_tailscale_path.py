"""check_health.py's direct-vs-DERP path check (AUDIT_2 P14).

Nothing here touches the network: `tailscale status --json` output is
supplied as fixtures and the subprocess/SSH seams are monkeypatched.

The decision rule under test is `CurAddr != ""`, NOT `Relay == ""`. That is
not a style preference -- on the tailnet this system actually runs on, the
two rules disagree about 2 of 7 peers in both directions:

  * a peer with a home DERP region AND a live direct endpoint reads
    "relayed" under the old rule, and
  * a peer with no home region and no direct endpoint reads "direct".

Both mistakes are reproduced below as explicit test cases.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_health  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_results():
    check_health.RESULTS.clear()
    check_health.WARNINGS.clear()
    yield
    check_health.RESULTS.clear()
    check_health.WARNINGS.clear()


def _status(peers: dict, backend_state: str = "Running") -> str:
    return json.dumps({
        "BackendState": backend_state,
        "Self": {"HostName": "truenas", "TailscaleIPs": ["100.71.216.3"]},
        "Peer": peers,
    })


def _peer(host, ip, cur_addr="", relay="", online=True, dns=None):
    return {
        "HostName": host,
        "DNSName": dns or f"{host}.tail1234.ts.net.",
        "TailscaleIPs": [ip],
        "CurAddr": cur_addr,
        "Relay": relay,
        "Online": online,
    }


# -- the decision table ------------------------------------------------------


@pytest.mark.parametrize(
    "cur_addr,relay,expected_direct",
    [
        # Relay set AND CurAddr set -> DIRECT. The old `Relay == ""` rule
        # calls this relayed; it is the commonest shape on a healthy tailnet,
        # because Relay is the peer's HOME region, not the path in use.
        ("203.0.113.7:41641", "hkg", True),
        # CurAddr empty -> RELAYED, whatever Relay says.
        ("", "hkg", False),
        # CurAddr empty AND no home region -> still RELAYED. The old rule
        # calls this DIRECT, which is the more dangerous of the two errors:
        # it reports a slow path as healthy.
        ("", "", False),
        # No home region but a live direct endpoint -> DIRECT.
        ("203.0.113.7:41641", "", True),
    ],
)
def test_direct_is_decided_by_cur_addr_not_relay(cur_addr, relay, expected_direct):
    raw = _status({"nodekey:abc": _peer("truenas", "100.71.216.3", cur_addr, relay)})
    result = check_health.parse_tailscale_status(raw, "truenas")
    assert result["found"] is True
    assert result["direct"] is expected_direct
    # The relay region is kept, but only as supplementary detail.
    assert result["relay"] == relay
    assert result["cur_addr"] == cur_addr


def test_the_two_rules_really_do_disagree_in_both_directions():
    """Guard against someone "simplifying" this back to Relay == ""."""
    both_set = check_health.peer_path(_peer("a", "100.0.0.1", "203.0.113.7:41641", "hkg"))
    neither = check_health.peer_path(_peer("b", "100.0.0.2", "", ""))
    assert both_set["direct"] is True and (both_set["relay"] == "") is False
    assert neither["direct"] is False and (neither["relay"] == "") is True


def test_describe_reports_the_endpoint_and_keeps_the_region_as_detail():
    direct = check_health.parse_tailscale_status(
        _status({"k": _peer("truenas", "100.71.216.3", "203.0.113.7:41641", "hkg")}), "truenas"
    )
    assert check_health.describe_tailscale_path(direct) == (
        "DIRECT via 203.0.113.7:41641 (home DERP hkg)"
    )
    relayed = check_health.parse_tailscale_status(
        _status({"k": _peer("truenas", "100.71.216.3", "", "hkg")}), "truenas"
    )
    assert check_health.describe_tailscale_path(relayed) == (
        "RELAYED via DERP hkg (no direct CurAddr)"
    )
    assert check_health.describe_tailscale_path({"found": False}) == "peer not found"


# -- peer lookup -------------------------------------------------------------


@pytest.mark.parametrize("hint", [
    "truenas", "truenas.tail1234.ts.net.", "nodekey:abc", "100.71.216.3", "216.3",
])
def test_peer_is_findable_by_name_dnsname_key_or_ip(hint):
    raw = _status({"nodekey:abc": _peer("truenas", "100.71.216.3", "", "hkg")})
    assert check_health.parse_tailscale_status(raw, hint)["found"] is True


def test_unknown_peer_is_not_found_and_is_not_reported_as_direct():
    raw = _status({"nodekey:abc": _peer("truenas", "100.71.216.3", "1.2.3.4:41641", "")})
    result = check_health.parse_tailscale_status(raw, "some-editor")
    assert result["found"] is False
    assert result["direct"] is False


def test_empty_hint_never_matches_a_peer():
    raw = _status({"nodekey:abc": _peer("truenas", "100.71.216.3")})
    assert check_health.parse_tailscale_status(raw, "")["found"] is False


# -- the NAS-side sweep ------------------------------------------------------


def _fake_ssh(out: str, rc: int = 0):
    def run_ssh(cmd, dry_run=False, timeout=120):
        return rc, out, ""

    return run_ssh


def test_relayed_online_peer_warns_without_failing_the_health_check(monkeypatch):
    raw = _status({
        "k1": _peer("editor-alex", "100.65.15.123", "", "hkg"),
        "k2": _peer("editor-sam", "100.88.89.10", "198.51.100.4:41641", "hkg"),
    })
    monkeypatch.setattr(check_health, "run_ssh", _fake_ssh(raw))
    check_health.check_tailscale(dry_run=False)

    assert [passed for passed, _ in check_health.RESULTS] == [True], "login check still passes"
    assert len(check_health.WARNINGS) == 1
    message = check_health.WARNINGS[0]
    assert "editor-alex" in message and "DERP hkg" in message
    assert "editor-sam" not in message
    # Actionable, not a bare boolean.
    assert "41641" in message and "netcheck" in message


def test_offline_peers_are_listed_but_never_warned_about(monkeypatch):
    raw = _status({"k": _peer("editor-laptop", "100.65.15.123", "", "", online=False)})
    monkeypatch.setattr(check_health, "run_ssh", _fake_ssh(raw))
    check_health.check_tailscale(dry_run=False)
    assert check_health.WARNINGS == []


def test_logged_out_still_fails_and_skips_the_path_sweep(monkeypatch):
    raw = _status({"k": _peer("editor", "100.65.15.123", "", "hkg")}, backend_state="NeedsLogin")
    monkeypatch.setattr(check_health, "run_ssh", _fake_ssh(raw))
    check_health.check_tailscale(dry_run=False)
    assert check_health.RESULTS[0][0] is False
    assert check_health.WARNINGS == []


def test_a_cjk_peer_name_does_not_crash_the_report(monkeypatch, capsys):
    """This tailnet has a peer called 廖少軒的MacBook Pro; a cp1252 Windows
    console raises UnicodeEncodeError on it and would take the whole health
    check down."""
    raw = _status({"k": _peer("廖少軒的MacBook Pro", "100.74.41.100", "", "")})
    monkeypatch.setattr(check_health, "run_ssh", _fake_ssh(raw))

    class _Cp1252Console:
        """Behaves like a real Windows console: refuses characters it cannot
        encode, exactly as the live one does."""

        encoding = "cp1252"

        def __init__(self):
            self.written = []

        def write(self, text):
            text.encode(self.encoding)  # raises UnicodeEncodeError, like the console
            self.written.append(text)
            return len(text)

        def flush(self):
            pass

    console = _Cp1252Console()
    monkeypatch.setattr(check_health.sys, "stdout", console)
    check_health.check_tailscale(dry_run=False)
    assert len(check_health.WARNINGS) == 1
    assert any("MacBook Pro" in line for line in console.written)


def test_peer_paths_are_sorted_and_carry_the_online_flag():
    raw = _status({
        "k1": _peer("zeta", "100.0.0.2", "", "hkg", online=False),
        "k2": _peer("alpha", "100.0.0.1", "1.2.3.4:41641", ""),
    })
    paths = check_health.tailscale_peer_paths(raw)
    assert [p["hostname"] for p in paths] == ["alpha", "zeta"]
    assert paths[0]["direct"] is True and paths[0]["online"] is True
    assert paths[1]["direct"] is False and paths[1]["online"] is False


# -- the local (this-machine) path check ------------------------------------


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _local(monkeypatch, raw, returncode=0, which="tailscale"):
    monkeypatch.setattr(check_health.shutil, "which", lambda name: which)
    monkeypatch.setattr(
        check_health.subprocess, "run",
        lambda *a, **kw: _Proc(raw, returncode),
    )


def test_local_check_warns_when_the_nas_peer_is_relayed(monkeypatch):
    """The live state of this network: the NAS peer is DERP-relayed, so this
    is what a real run prints today."""
    _local(monkeypatch, _status({"k": _peer("truenas", "100.71.216.3", "", "hkg")}))
    check_health.check_tailscale_path_from_here(["100.71.216.3", "truenas"], dry_run=False)
    assert len(check_health.WARNINGS) == 1
    assert "truenas" in check_health.WARNINGS[0]
    # Non-fatal: it must not add a FAIL, because nothing is broken.
    assert check_health.RESULTS == []


def test_local_check_is_quiet_when_the_path_is_direct(monkeypatch, capsys):
    _local(monkeypatch, _status({"k": _peer("truenas", "100.71.216.3", "203.0.113.7:41641", "hkg")}))
    check_health.check_tailscale_path_from_here(["100.71.216.3"], dry_run=False)
    assert check_health.WARNINGS == []
    assert "DIRECT via 203.0.113.7:41641" in capsys.readouterr().out


def test_local_check_skips_cleanly_without_a_tailscale_binary(monkeypatch):
    _local(monkeypatch, "", which=None)
    check_health.check_tailscale_path_from_here(["truenas"], dry_run=False)
    assert check_health.WARNINGS == [] and check_health.RESULTS == []


def test_local_check_skips_cleanly_on_junk_output(monkeypatch):
    _local(monkeypatch, "not json at all")
    check_health.check_tailscale_path_from_here(["truenas"], dry_run=False)
    assert check_health.WARNINGS == [] and check_health.RESULTS == []


def test_local_check_skips_cleanly_when_the_command_fails(monkeypatch):
    _local(monkeypatch, "", returncode=1)
    check_health.check_tailscale_path_from_here(["truenas"], dry_run=False)
    assert check_health.WARNINGS == [] and check_health.RESULTS == []


def test_local_check_tries_every_hint_before_giving_up(monkeypatch):
    _local(monkeypatch, _status({"k": _peer("truenas", "100.71.216.3", "", "hkg")}))
    check_health.check_tailscale_path_from_here(["nas.example", "truenas"], dry_run=False)
    assert len(check_health.WARNINGS) == 1


def test_local_check_makes_no_subprocess_call_in_dry_run(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("--dry-run must not run anything")

    monkeypatch.setattr(check_health.subprocess, "run", boom)
    monkeypatch.setattr(check_health.shutil, "which", boom)
    check_health.check_tailscale_path_from_here(["truenas"], dry_run=True)
    assert check_health.WARNINGS == []


# -- peer hints --------------------------------------------------------------


def test_hints_prefer_an_explicit_flag_then_the_dashboard_tailnet_host():
    assert check_health.nas_peer_hints("box", "http://100.71.216.3:8480") == ["box"]
    assert check_health.nas_peer_hints(None, "http://100.71.216.3:8480") == [
        "100.71.216.3", check_health.DEFAULT_NAS_TAILNET_NAME,
    ]
    # A LAN address is not a tailnet address and would match no peer.
    assert check_health.nas_peer_hints(None, "http://192.168.0.102:8480") == [
        check_health.DEFAULT_NAS_TAILNET_NAME,
    ]
    assert check_health.nas_peer_hints(None, "") == [check_health.DEFAULT_NAS_TAILNET_NAME]


def test_warnings_never_change_the_exit_code(monkeypatch, capsys):
    """A relayed path is slow, not broken. It must not fail the health check
    -- but it must be impossible to miss in the summary."""
    monkeypatch.setattr(check_health, "check_postgres", lambda dry: None)
    monkeypatch.setattr(check_health, "check_tailscale", lambda dry: check_health.warn("relayed!"))
    monkeypatch.setattr(check_health, "check_tailscale_path_from_here", lambda h, dry: None)
    monkeypatch.setattr(check_health, "check_syncthing_app", lambda *a: None)
    monkeypatch.setattr(check_health, "check_tree", lambda *a: None)
    monkeypatch.setattr(check_health, "check_editor_accounts", lambda dry: None)
    monkeypatch.setattr(check_health, "check_dashboard", lambda *a: check_health.report(True, "ok"))
    monkeypatch.setattr(sys, "argv", ["check_health.py"])

    assert check_health.main() == 0
    out = capsys.readouterr().out
    assert "1 warning(s)" in out
    assert "relayed!" in out
