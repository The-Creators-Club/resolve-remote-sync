"""The syncthing runner's completion detection and CLI-version handling.

The bug these tests exist for: an empty `sendreceive` folder that has just been
added scans instantly and reports `state="idle", needBytes=0` **before** the
peer has connected and before the global index has arrived. The old loop polled
immediately after `add_folder` and accepted exactly that, returning "sync
complete" at t~=0 with 0 bytes moved -- and because such a row carries
`ok=True`, the report medianed a 0.0 MB/s into lane C.

No real syncthing process is involved here: the REST client is faked, so the
poll sequence is scripted and the assertions are about the decision logic.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ccbench.runners import syncthing

# Short waits so the timeout paths are quick; the logic under test doesn't care.
FAST = {"poll_interval": 0.001}
TINY_TIMEOUT = 0.05

V1_VERSION = 'syncthing v1.27.9 "Gold Grasshopper" (go1.22.5 windows-amd64) builder@github 2024-07-08'
V2_VERSION = 'syncthing v2.1.2 "Hafnium Hornet" (go1.26.5 windows-amd64) builder@github 2026-06-26'


@pytest.fixture(autouse=True)
def _clear_version_cache(monkeypatch):
    """The version probe is cached per binary process-wide; don't leak between
    tests (or from a real probe done by another test module)."""
    monkeypatch.setattr(syncthing, "_VERSION_CACHE", {})


class FakeInstance:
    """Scripted stand-in for `_Instance`'s REST surface.

    `statuses` is consumed one entry per poll; the last entry repeats forever
    (a real folder keeps reporting its final state).
    """

    def __init__(self, statuses: list[dict], connected_after: int | None = 0):
        self._statuses = list(statuses) or [{}]
        self._connected_after = connected_after
        self.polls = 0
        self.connection_checks = 0

    def folder_status(self, folder_id: str) -> dict:
        self.polls += 1
        if len(self._statuses) > 1:
            return self._statuses.pop(0)
        return self._statuses[0]

    def peer_connected(self, peer_device_id: str) -> bool:
        self.connection_checks += 1
        if self._connected_after is None:
            return False
        return self.connection_checks > self._connected_after


def _status(state="idle", need=0, glob=0) -> dict:
    return {"state": state, "needBytes": need, "globalBytes": glob}


def _fake_version_probe(monkeypatch, output: str, rc: int = 0, exc: Exception | None = None):
    """Replace the module's subprocess helper with a scripted `--version`."""
    calls: list[list[str]] = []

    def fake_run(cmd, timeout=None):
        calls.append(list(cmd))
        if exc is not None:
            raise exc
        return rc, output, ""

    monkeypatch.setattr(syncthing, "_run", fake_run)
    return calls


# ---------------------------------------------------------------------------
# version detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output, major",
    [
        (V1_VERSION, 1),
        (V2_VERSION, 2),
        ("syncthing v1.23.0", 1),
        ("syncthing v2.0.0-rc.3 \"Hafnium Hornet\"", 2),
        ("syncthing 2.1.2 (no v prefix)", 2),
    ],
)
def test_parse_version_major(output, major):
    assert syncthing.parse_version_major(output) == major


def test_parse_version_major_returns_none_when_unreadable():
    assert syncthing.parse_version_major("") is None
    assert syncthing.parse_version_major("syncthing (unknown build)") is None


def test_detect_major_probes_the_binary_once_and_caches(monkeypatch):
    calls = _fake_version_probe(monkeypatch, V2_VERSION)

    assert syncthing.detect_major("syncthing") == 2
    assert syncthing.detect_major("syncthing") == 2

    assert calls == [["syncthing", "--version"]]  # probed once, not per instance


def test_detect_major_caches_per_binary(monkeypatch):
    outputs = {"st1": V1_VERSION, "st2": V2_VERSION}
    monkeypatch.setattr(syncthing, "_run", lambda cmd, timeout=None: (0, outputs[cmd[0]], ""))

    assert syncthing.detect_major("st1") == 1
    assert syncthing.detect_major("st2") == 2


def test_detect_major_rejects_an_unknown_major_instead_of_guessing(monkeypatch):
    _fake_version_probe(monkeypatch, 'syncthing v3.0.0 "Future Ferret"')

    with pytest.raises(syncthing.UnsupportedSyncthingVersion) as exc:
        syncthing.detect_major("syncthing")
    assert "3" in str(exc.value)
    assert "not supported" in str(exc.value)


def test_detect_major_rejects_unparseable_output(monkeypatch):
    _fake_version_probe(monkeypatch, "something else entirely")
    with pytest.raises(syncthing.UnsupportedSyncthingVersion):
        syncthing.detect_major("syncthing")


def test_detect_major_rejects_a_failed_probe(monkeypatch):
    _fake_version_probe(monkeypatch, "", rc=127)
    with pytest.raises(syncthing.UnsupportedSyncthingVersion):
        syncthing.detect_major("syncthing")


def test_detect_major_rejects_a_probe_that_will_not_start(monkeypatch):
    _fake_version_probe(monkeypatch, "", exc=OSError("permission denied"))
    with pytest.raises(syncthing.UnsupportedSyncthingVersion) as exc:
        syncthing.detect_major("syncthing")
    assert "permission denied" in str(exc.value)

    _fake_version_probe(monkeypatch, "", exc=subprocess.TimeoutExpired(["syncthing"], 30))
    with pytest.raises(syncthing.UnsupportedSyncthingVersion):
        syncthing.detect_major("syncthing")


def test_an_unsupported_version_skips_the_run_rather_than_failing_it(tmp_path, monkeypatch):
    monkeypatch.setattr(syncthing, "available", lambda cfg=None: (True, "syncthing"))
    _fake_version_probe(monkeypatch, 'syncthing v3.0.0 "Future Ferret"')
    spawned = []
    monkeypatch.setattr(syncthing.subprocess, "Popen", lambda *a, **k: spawned.append(a))

    result = syncthing.run(tmp_path, "up", {}, {}, dataset_name="small", lane="C")

    assert result.skipped is True
    assert "not supported" in result.reason
    assert spawned == []  # nothing was started with guessed flags


# ---------------------------------------------------------------------------
# per-version command construction
# ---------------------------------------------------------------------------


def test_v1_commands_keep_the_shape_that_worked(tmp_path):
    cfg = tmp_path / "st-editor"

    assert syncthing.generate_cmd("syncthing", cfg, 1) == [
        "syncthing", "generate", "--config", str(cfg), "--no-default-folder",
    ]
    assert syncthing.device_id_cmd("syncthing", cfg, 1) == [
        "syncthing", "--config", str(cfg), "--device-id",
    ]
    serve = syncthing.serve_cmd("syncthing", cfg, "127.0.0.1:8384", 1)
    assert serve[:2] == ["syncthing", "--config"]  # no subcommand on v1
    assert "--gui-address" in serve and "127.0.0.1:8384" in serve
    assert "--no-browser" in serve and "--no-restart" in serve


def test_v2_commands_use_the_reorganised_cli(tmp_path):
    cfg = tmp_path / "st-editor"

    generate = syncthing.generate_cmd("syncthing", cfg, 2)
    assert generate[:2] == ["syncthing", "generate"]
    assert "--no-default-folder" not in generate  # removed in v2
    assert generate.count(str(cfg)) == 2  # --config and --data both under temp

    assert syncthing.device_id_cmd("syncthing", cfg, 2) == [
        "syncthing", "device-id", "--config", str(cfg), "--data", str(cfg),
    ]

    serve = syncthing.serve_cmd("syncthing", cfg, "127.0.0.1:8384", 2)
    assert serve[:2] == ["syncthing", "serve"]  # v2 needs the subcommand
    assert "--no-default-folder" not in serve
    assert "--data" in serve
    assert "--gui-address" in serve and "127.0.0.1:8384" in serve
    assert "--no-browser" in serve and "--no-restart" in serve


def test_v2_never_points_syncthing_at_the_real_user_database(tmp_path):
    """Without an explicit --data, a v2 bench instance would write its database
    into the machine's real syncthing state directory."""
    cfg = tmp_path / "st-nas"
    for cmd in (
        syncthing.generate_cmd("syncthing", cfg, 2),
        syncthing.device_id_cmd("syncthing", cfg, 2),
        syncthing.serve_cmd("syncthing", cfg, "127.0.0.1:1", 2),
    ):
        assert "--data" in cmd
        assert cmd[cmd.index("--data") + 1] == str(cfg)


def test_the_instance_builds_its_commands_from_its_detected_version(tmp_path, monkeypatch):
    v1 = syncthing._Instance("syncthing", "editor", tmp_path, version_major=1)
    v2 = syncthing._Instance("syncthing", "editor", tmp_path, version_major=2)

    seen: list[list[str]] = []
    monkeypatch.setattr(syncthing.subprocess, "Popen", lambda cmd, **k: seen.append(cmd))
    monkeypatch.setattr(syncthing._Instance, "_wait_for_gui", lambda self: None)

    v1.start()
    v2.start()

    assert "serve" not in seen[0]
    assert seen[1][1] == "serve"


# ---------------------------------------------------------------------------
# _wait_for_sync
# ---------------------------------------------------------------------------


def test_idle_and_zero_need_before_the_index_arrives_is_not_completion():
    """The exact B25 shape: connected or not, an empty just-added folder is
    idle with needBytes 0 and nothing in the global index."""
    inst = FakeInstance([_status(state="idle", need=0, glob=0)])

    completed, seconds, detail = syncthing._wait_for_sync(
        inst, "f", TINY_TIMEOUT, expected_bytes=4096, **FAST
    )

    assert completed is False
    assert "global index never arrived" in detail
    assert seconds >= 0.0
    assert inst.polls > 1  # it kept polling instead of declaring victory at t=0


def test_completion_needs_the_index_then_needbytes_zero():
    inst = FakeInstance(
        [
            _status(state="idle", need=0, glob=0),  # index not in yet
            _status(state="syncing", need=4096, glob=4096),  # index arrived, pulling
            _status(state="idle", need=0, glob=4096),  # done
        ]
    )

    completed, _seconds, detail = syncthing._wait_for_sync(
        inst, "f", TINY_TIMEOUT, expected_bytes=4096, **FAST
    )

    assert completed is True
    assert detail == ""
    assert inst.polls == 3


def test_a_partial_global_index_is_not_completion():
    """globalBytes > 0 but short of what the sender holds: the index is still
    arriving, so needBytes==0 means "nothing left of what I've heard about"."""
    inst = FakeInstance([_status(state="idle", need=0, glob=400)])

    completed, _seconds, detail = syncthing._wait_for_sync(
        inst, "f", TINY_TIMEOUT, expected_bytes=4096, **FAST
    )

    assert completed is False
    assert "expected at least 4096" in detail


def test_a_folder_that_never_finishes_pulling_times_out_with_detail():
    inst = FakeInstance([_status(state="syncing", need=1024, glob=4096)])

    completed, _seconds, detail = syncthing._wait_for_sync(
        inst, "f", TINY_TIMEOUT, expected_bytes=4096, **FAST
    )

    assert completed is False
    assert "needBytes never reached 0" in detail
    assert "syncing" in detail


def test_completion_is_accepted_on_the_first_poll_once_the_index_is_there():
    inst = FakeInstance([_status(state="idle", need=0, glob=4096)])

    completed, _seconds, _detail = syncthing._wait_for_sync(
        inst, "f", TINY_TIMEOUT, expected_bytes=4096, **FAST
    )

    assert completed is True
    assert inst.polls == 1


def test_without_an_expected_size_a_nonempty_index_still_gates_completion():
    """Callers that can't say how much was seeded still get the globalBytes>0
    guard -- the part that distinguishes "finished" from "hasn't heard yet"."""
    empty = FakeInstance([_status(state="idle", need=0, glob=0)])
    completed, _s, _d = syncthing._wait_for_sync(empty, "f", TINY_TIMEOUT, **FAST)
    assert completed is False

    indexed = FakeInstance([_status(state="idle", need=0, glob=1)])
    completed, _s, _d = syncthing._wait_for_sync(indexed, "f", TINY_TIMEOUT, **FAST)
    assert completed is True


def test_empty_state_string_still_counts_as_idle():
    """Older syncthing builds report an empty state for a freshly-scanned
    folder; that was accepted before and must stay accepted -- with the index
    guard applied."""
    inst = FakeInstance([_status(state="", need=0, glob=4096)])
    completed, _s, _d = syncthing._wait_for_sync(
        inst, "f", TINY_TIMEOUT, expected_bytes=4096, **FAST
    )
    assert completed is True


def test_a_missing_needbytes_field_is_treated_as_not_done():
    inst = FakeInstance([{"state": "idle", "globalBytes": 4096}])
    completed, _s, detail = syncthing._wait_for_sync(
        inst, "f", TINY_TIMEOUT, expected_bytes=4096, **FAST
    )
    assert completed is False
    assert "needBytes never reached 0" in detail


# ---------------------------------------------------------------------------
# _wait_for_peer_connection
# ---------------------------------------------------------------------------


def test_wait_for_peer_connection_returns_true_once_the_peer_dials_in():
    inst = FakeInstance([_status()], connected_after=2)
    assert syncthing._wait_for_peer_connection(inst, "PEER", timeout_s=1.0, poll_interval=0.001)
    assert inst.connection_checks == 3


def test_wait_for_peer_connection_gives_up_and_says_no():
    inst = FakeInstance([_status()], connected_after=None)
    assert not syncthing._wait_for_peer_connection(
        inst, "PEER", timeout_s=TINY_TIMEOUT, poll_interval=0.001
    )
    assert inst.connection_checks > 1


def test_peer_connected_reads_the_connections_endpoint(tmp_path: Path, monkeypatch):
    # REST is version-stable, so the major used here is immaterial.
    inst = syncthing._Instance("syncthing", "nas", tmp_path, version_major=2)

    monkeypatch.setattr(
        inst, "_get", lambda path: {"connections": {"PEERID": {"connected": True}}}
    )
    assert inst.peer_connected("PEERID") is True
    assert inst.peer_connected("SOMEONE-ELSE") is False

    monkeypatch.setattr(
        inst, "_get", lambda path: {"connections": {"PEERID": {"connected": False}}}
    )
    assert inst.peer_connected("PEERID") is False


def test_peer_connected_is_false_while_the_gui_is_still_refusing():
    inst = syncthing._Instance.__new__(syncthing._Instance)

    def boom(_path):
        raise ConnectionRefusedError("gui not up yet")

    inst._get = boom  # type: ignore[method-assign]
    assert inst.peer_connected("PEERID") is False


# ---------------------------------------------------------------------------
# direction handling
# ---------------------------------------------------------------------------


def test_bidirectional_is_rejected_instead_of_measured_one_way(tmp_path, monkeypatch):
    """The runner seeds one side and times the other receiving it. Labelling
    that "bidirectional" would publish a one-way number under a two-way name."""
    monkeypatch.setattr(syncthing, "available", lambda cfg=None: (True, "syncthing"))

    result = syncthing.run(
        tmp_path, "bidirectional", {}, {}, dataset_name="small", lane="C", repeat_index=0
    )

    assert result.skipped is True
    assert result.ok is False
    assert "both" in result.reason
    assert result.loopback is True


def test_an_unknown_direction_is_still_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(syncthing, "available", lambda cfg=None: (True, "syncthing"))

    result = syncthing.run(tmp_path, "sideways", {}, {}, dataset_name="small", lane="C")

    assert result.skipped is True
    assert "unsupported direction" in result.reason


def test_a_missing_binary_skips_before_anything_is_spawned(tmp_path, monkeypatch):
    monkeypatch.setattr(syncthing, "available", lambda cfg=None: (False, "'syncthing' not found"))

    result = syncthing.run(tmp_path, "up", {}, {}, dataset_name="small", lane="C")

    assert result.skipped is True
    assert "not found" in result.reason


# ---------------------------------------------------------------------------
# the short-transfer backstop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "moved, expected, is_bad",
    [
        (0, 4096, True),
        (2048, 4096, True),
        (4096, 4096, False),
        (4100, 4096, False),
        (0, 0, False),  # nothing expected, nothing moved: not this check's call
    ],
)
def test_short_transfer_reason_catches_partial_and_empty_runs(moved, expected, is_bad):
    from ccbench.runners import base

    reason = base.short_transfer_reason("syncthing", moved, expected)
    assert bool(reason) is is_bad
