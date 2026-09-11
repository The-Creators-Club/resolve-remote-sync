"""Bug hunt 2026-09-11, territory comp-resolve (CR-236).

Six findings plus res-companion-2, each with the property it defends:

  * comp-resolve-1  a copy's read size comes BACK UP once the link recovers.
  * comp-resolve-2  a rehearsal is not counted as bytes and files copied in.
  * comp-resolve-3  the actionable half of a refusal survives the wire's cap.
  * comp-resolve-4  a role whose loops died is restarted, ONCE, cleanly.
  * res-companion-2 a start that half-succeeds stops the engine it started.
  * comp-resolve-5  a journal tmp orphaned by a kill is swept.
  * comp-resolve-6  "Resolve went away" is not logged as "it registered".
"""
from __future__ import annotations

import builtins
import logging
import os
import time
import types

from ccsync_companion import (consolidate, fixer, resolve_bridge,
                              resolve_journal, script_server)
from ccsync_companion import timeline_cards_role as role_mod


# ------------------------------------------------- comp-resolve-1: the read size

def _read_sizes(tmp_path, monkeypatch, *, total_bytes, slow_reads):
    """Run the real copy_with_progress over a real file, recording the size
    of every read and making the first `slow_reads` of them look slow to the
    injected clock (a hydrating placeholder, an SMB share that is thinking).
    """
    src = tmp_path / "src.bin"
    src.write_bytes(b"\0" * total_bytes)
    dst = tmp_path / "dst.bin"
    sizes: list[int] = []
    now = {"t": 0.0}
    real_open = builtins.open

    class Wrapped:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()
            return False

        def read(self, n):
            sizes.append(n)
            # The read itself is what takes the time, between the two clock
            # reads copy_with_progress takes around it.
            now["t"] += 1.0 if len(sizes) <= slow_reads else 0.001
            return self.fh.read(n)

    def fake_open(path, mode="r", *a, **k):
        fh = real_open(path, mode, *a, **k)
        return Wrapped(fh) if str(path) == str(src) else fh

    monkeypatch.setattr(builtins, "open", fake_open)
    fixer.copy_with_progress(str(src), str(dst), clock=lambda: now["t"])
    monkeypatch.undo()
    assert dst.read_bytes() == src.read_bytes()
    return sizes


def test_one_slow_read_does_not_shrink_the_whole_rest_of_the_file(tmp_path,
                                                                  monkeypatch):
    """comp-resolve-1: RES-14's halving had no way back up, so the FIRST read
    of a cloud placeholder (which always blocks while it hydrates) ratcheted
    the remaining gigabytes down for good."""
    sizes = _read_sizes(tmp_path, monkeypatch, total_bytes=12 * 1024 * 1024,
                        slow_reads=1)
    assert sizes[0] == fixer.POLL_CHUNK_BYTES
    assert sizes[1] == fixer.POLL_CHUNK_BYTES // 2
    assert sizes[-2] == fixer.POLL_CHUNK_BYTES, sizes


def test_a_link_that_stays_slow_still_ratchets_down_and_stays_there(tmp_path,
                                                                    monkeypatch):
    """The grow-back must not undo the property the shrink exists for: the
    cancel the editor already pressed is honoured inside one read."""
    sizes = _read_sizes(tmp_path, monkeypatch, total_bytes=2 * 1024 * 1024,
                        slow_reads=10_000)
    assert min(sizes) == fixer.MIN_CHUNK_BYTES
    assert sizes[-1] == fixer.MIN_CHUNK_BYTES


# ------------------------------------------- comp-resolve-2: a rehearsal copies nothing

def _rehearsal_ops(n=3, size=1000):
    return [{"file_path": f"G:\\x\\f{i}.mov", "media_pool_items": [],
             "dest_rel": "D", "size": size} for i in range(n)]


def _dry_run_fix(path, dest, root, mpis, on_bytes=None, **kw):
    # fixer.fix_clip's rehearsal arm since RES-15: ok, and dry_run.
    return {"ok": True, "dry_run": True, "message": "rehearsal: would copy",
            "copied_to": dest}


def test_consolidate_does_not_count_a_rehearsal_as_copied_in():
    """comp-resolve-2: `fixer_dry_run` is a supported mode with a tray switch,
    and the consolidate screen credited every rehearsed file's bytes and
    called them copied (the UI-5 twin-miss, again)."""
    seen: list[dict] = []
    results = consolidate.run_consolidation(
        _rehearsal_ops(), "L", fix_clip_fn=_dry_run_fix, state_fn=seen.append)
    assert len(results) == 3
    final = seen[-1]
    assert final["fixed"] == 0
    assert final["rehearsal"] == 3
    assert final["failed"] == 0
    assert final["batch_bytes_done"] == 0


def test_a_real_copy_is_still_counted():
    seen: list[dict] = []
    consolidate.run_consolidation(
        _rehearsal_ops(2), "L", state_fn=seen.append,
        fix_clip_fn=lambda p, d, r, m, **kw: {"ok": True, "message": "ok",
                                              "copied_to": d})
    assert seen[-1]["fixed"] == 2
    assert seen[-1]["rehearsal"] == 0
    assert seen[-1]["batch_bytes_done"] == 2000


def test_run_consolidation_reports_what_a_rehearsal_did():
    """The caller (app.py's toast) must be able to tell the two apart without
    re-deriving it from `ok`."""
    results = consolidate.run_consolidation(
        _rehearsal_ops(1), "L", fix_clip_fn=_dry_run_fix)
    assert consolidate.count_copied(results) == 0
    assert consolidate.count_rehearsed(results) == 1


# --------------------------------- comp-resolve-3: the refusal survives the cap

WIRE_DETAIL_CAP = 255  # dashboard api.py CardsAgentIn.detail / JobsGateIn.detail


def _a_cfg(tmp_path, **over):
    cfg = {"cards_agent": True, "dashboard_url": "https://dash.example",
           "dashboard_token": "cce1.aaaaaaaaaaaaaaaaaaaaaaaa",
           "jobs_mulcam_pipeline": str(tmp_path / "MulticamPipeline"),
           "jobs_vault_root": str(tmp_path / "vault")}
    cfg.update(over)
    return cfg


def test_the_process_to_close_is_inside_the_first_255_characters(tmp_path):
    """comp-resolve-3: the refusal was 247 characters before the process
    description was appended, so the fleet grid stored eight characters of
    it and the admin could not tell the editor what to close."""
    line = ("4312\tpython.exe\tC:\\Users\\editor\\AppData\\Local\\Programs\\"
            "Python\\Python312\\python.exe E:\\Projects\\MulticamPipeline\\"
            "reorder_web.py --agent --port 8765")
    role = role_mod.TimelineCardsRole(_a_cfg(tmp_path),
                                      processes_fn=lambda: [line])
    state, detail = role.refusal()
    assert state == role_mod.STATE_STANDALONE_AGENT
    assert len(detail) <= WIRE_DETAIL_CAP
    assert "python.exe (pid 4312)" in detail[:WIRE_DETAIL_CAP]


def test_a_long_detail_is_truncated_here_rather_than_on_the_wire(tmp_path):
    role = role_mod.TimelineCardsRole(_a_cfg(tmp_path), processes_fn=lambda: [])
    role._threads = [_LiveThread(), _LiveThread()]
    role._note_loop_end("the push loop stopped: RuntimeError: " + "x" * 600)
    detail = role.report_block()["detail"]
    assert len(detail) <= WIRE_DETAIL_CAP
    assert detail.startswith("the push loop stopped: RuntimeError: xxx")


# ----------------- comp-resolve-4 / res-companion-2: the watchdog and the engine

class _LiveThread:
    def is_alive(self):
        return True


class _DeadThread:
    def is_alive(self):
        return False


class FakeEngine:
    made: list["FakeEngine"] = []

    def __init__(self, root, bridge=None):
        self.root, self.bridge = root, bridge
        self.started = self.stopped = False
        self.version = 5
        FakeEngine.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeAgentClient:
    def __init__(self, server, token, engine, name=None):
        self.url, self.token, self.eng, self.name = server, token, engine, name

    def push_loop(self):
        time.sleep(30)

    pull_loop = push_loop


def _fake_loader(tmp_path, *, client_raises=False):
    engine_mod = types.SimpleNamespace(SyncEngine=FakeEngine,
                                       BRIDGE_CONTRACT_VERSION=1)

    class Boom:
        def __init__(self, *a, **k):
            raise TypeError("AgentClient() takes 5 positional arguments")

    agent_mod = types.SimpleNamespace(
        AgentClient=Boom if client_raises else FakeAgentClient)
    return lambda checkout: (engine_mod, agent_mod)


def _a_role(tmp_path, *, client_raises=False, **over):
    FakeEngine.made = []
    return role_mod.TimelineCardsRole(
        _a_cfg(tmp_path, **over),
        request_fn=lambda *a, **k: (200, {}),
        processes_fn=lambda: [],
        engine_loader=_fake_loader(tmp_path, client_raises=client_raises),
        bridge=object(),
    )


def test_a_role_whose_loops_died_is_restarted_by_the_watchdog(tmp_path):
    """comp-resolve-4: `_threads` was never cleared, so supervise_now's
    `if self._threads` answered "running" for ever over two dead threads and
    only a companion restart brought the editor's page back."""
    role = _a_role(tmp_path)
    assert role.start() is True
    first = role._engine
    with role._lock:
        role._threads = [_DeadThread(), _DeadThread()]
    role._note_loop_end("the push loop stopped: RuntimeError: boom")
    assert role.report_block()["state"] == role_mod.HEALTH_STOPPED
    assert role.supervise_now() is True
    assert role._engine is not first
    # ...and the dead one was stopped, not left driving Resolve beside the
    # new one (one machine, one Resolve client).
    assert first.stopped is True
    assert role.report_block()["state"] != role_mod.HEALTH_STOPPED
    role.stop()


def test_a_running_role_is_still_not_restarted(tmp_path):
    role = _a_role(tmp_path)
    assert role.start() is True
    engine = role._engine
    assert role.supervise_now() is True
    assert role._engine is engine
    assert len(FakeEngine.made) == 1
    role.stop()


def test_stop_lets_go_of_the_engine(tmp_path):
    role = _a_role(tmp_path)
    role.start()
    engine = role._engine
    role.stop()
    assert engine.stopped is True


def test_a_start_that_fails_after_engine_start_stops_that_engine(tmp_path):
    """res-companion-2: the engine was started before `make_tunnel_client`
    and only recorded after it, so anything raised in between left a running
    engine nothing held a reference to."""
    role = _a_role(tmp_path, client_raises=True)
    assert role.start() is False
    assert len(FakeEngine.made) == 1
    engine = FakeEngine.made[0]
    assert engine.stopped is True or engine.started is False
    assert role._engine is None


def test_the_watchdog_does_not_become_an_engine_factory(tmp_path):
    """One failing start a minute, for ever, was 60 live engines an hour."""
    role = _a_role(tmp_path, client_raises=True)
    role.start()
    for _ in range(20):
        assert role.supervise_now() is False
    assert len(FakeEngine.made) <= role_mod.MAX_START_FAILURES
    # Every engine that was started was stopped again.
    assert all(e.stopped or not e.started for e in FakeEngine.made)
    # An explicit start (the editor, or a companion restart) tries again.
    role.start()
    assert len(FakeEngine.made) <= role_mod.MAX_START_FAILURES + 1


# ------------------- dash-release-jobs-6: the state push names its machine

def test_the_state_push_carries_this_machine(tmp_path):
    """The cards tunnel no longer trusts the agent's self-asserted `name`: it
    derives the machine from the editor plus `body["machine"]`, which is the
    same hostname the report carries. Optional on the wire, so an older
    dashboard ignoring it is fine."""
    sent: list[tuple[str, dict]] = []

    def request(method, url, body, headers, timeout):
        sent.append((url, body))
        return 200, {}

    role = role_mod.TimelineCardsRole(_a_cfg(tmp_path), request_fn=request,
                                      processes_fn=lambda: [],
                                      machine_name="DESKTOP-LQQ41TC")
    role.call("/agent/state", {"token": "secret", "name": "whatever-it-says",
                               "state": {"timeline": "E1"}})
    role.call("/agent/result", {"token": "secret", "id": "1"})
    url, body = sent[0]
    assert url.endswith("/cards/agent/state")
    assert body["machine"] == "DESKTOP-LQQ41TC"
    # Still no token on the wire, and the other routes are untouched.
    assert "token" not in body
    assert "machine" not in sent[1][1]


# ------------------------------------------- comp-resolve-5: the orphaned tmp

def test_an_orphaned_journal_tmp_is_swept():
    """comp-resolve-5: `<name>.json.tmp.<pid>.<tid>` is unlinked by the writer
    only when the write RAISES. A companion killed between open() and
    os.replace() (CR-93's abort, the supervisor's relaunch) leaves one for
    ever: neither `*.json` nor `*.drp` matches it."""
    old = time.time() - (resolve_journal.RETENTION_DAYS + 1) * 86400
    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                           new_path="P:/a.mov", clock=lambda: old)
    directory = resolve_journal.journal_root() / "FF5"
    orphan = directory / "20260101-000000.json.tmp.4312.9876"
    orphan.write_text("{", encoding="utf-8")
    os.utime(orphan, (old, old))
    fresh_tmp = directory / "20260901-000000.json.tmp.4312.9877"
    fresh_tmp.write_text("{", encoding="utf-8")
    resolve_journal.reset_for_tests()

    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                           new_path="P:/b.mov")

    assert not orphan.exists()
    # A tmp young enough to be an in-flight write from another thread stays.
    assert fresh_tmp.exists()


# ------------------------------- comp-resolve-6: went away != registered

_real_connect = resolve_bridge.connect


def test_resolve_dying_in_its_launch_window_is_not_logged_as_a_recovery(
        monkeypatch, caplog):
    """comp-resolve-6: STARTING -> ABSENT logged "script server has its host
    now - connecting", the same line as a real recovery, and a CR-68 diagnosis
    is read out of exactly this log."""
    monkeypatch.setattr(resolve_bridge, "connect", _real_connect)
    monkeypatch.setattr(resolve_bridge, "_starting_since", None)
    phase = {"now": (script_server.STARTING, "no host yet")}
    monkeypatch.setattr(script_server, "state", lambda: phase["now"])
    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert _real_connect() is None
        phase["now"] = (script_server.ABSENT, "")
        assert _real_connect() is None
    messages = [r.getMessage() for r in caplog.records]
    assert not any("has its host now" in m for m in messages), messages
    assert any("went away" in m for m in messages), messages


def test_a_real_recovery_still_says_so(monkeypatch, caplog):
    monkeypatch.setattr(resolve_bridge, "connect", _real_connect)
    monkeypatch.setattr(resolve_bridge, "_starting_since", None)
    phase = {"now": (script_server.STARTING, "no host yet")}
    monkeypatch.setattr(script_server, "state", lambda: phase["now"])
    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath", lambda: None)
    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert _real_connect() is None
        phase["now"] = (script_server.READY, "")
        _real_connect()
    assert any("has its host now" in r.getMessage() for r in caplog.records)
