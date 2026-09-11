"""Bug hunt 2026-09-11b, territory comp-resolve (CR-252).

Four findings, each with the property it defends:

  * comp-resolve-b-2  a latched non-canonical path the LIMITER refused is
                      offered again, without the editor clicking anything.
  * regression-8      a role that lost ONE of its two loops is recovered.
  * comp-resolve-b-3  `_elide` never returns more than the cap it is given.
  * comp-resolve-b-4  an UNKNOWN probe does not close the launch window with
                      "Resolve registered".

Nothing here reaches a live Resolve (CR-68): the watcher is driven through an
injected `get_timeline_items` and `script_server.state` is monkeypatched.
"""
from __future__ import annotations

import logging
import time

import pytest

from ccsync_companion import resolve_bridge, script_server
from ccsync_companion import timeline_cards_role as role_mod
from ccsync_companion import watcher as watcher_mod
from ccsync_companion.watcher import TimelineWatcher

from conftest import make_timeline_item


# -- comp-resolve-b-2: the queue the limiter refused drains by itself -------


def _a_watcher(tmp_path, offered):
    clip = tmp_path / "root" / "Projects" / "a.mov"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.touch()
    watcher = TimelineWatcher(
        local_root=str(tmp_path / "root"),
        canonical_prefix="P:\\",
        on_non_canonical=lambda items: offered.extend(items),
        get_timeline_items=lambda: {"ok": True, "message": "",
                                    "project_name": "",
                                    "items": [make_timeline_item(str(clip))]},
    )
    return watcher, clip


def test_a_path_the_limiter_refused_is_offered_again(tmp_path):
    """comp-resolve-b-2: the watcher latched at OFFER time and only a FAILED
    relink lifted the latch. When resolve_journal.allow_automatic refuses the
    burst, no clip is attempted, nothing is re-armed, and the clips sit on
    app's pending queue that nothing polls -- for the life of the process."""
    offered: list[dict] = []
    watcher, _clip = _a_watcher(tmp_path, offered)

    watcher.poll_once()
    assert len(offered) == 1

    # The limiter refused the burst: no ReplaceClip was attempted, so
    # rearm_non_canonical is never called. At HEAD every later poll skipped
    # the path for ever.
    for _ in range(20):
        watcher.poll_once()
    assert len(offered) == 1

    watcher._rearm_clock = (
        lambda: time.monotonic() + watcher_mod.REARM_COOLDOWN_SECONDS + 1)
    watcher.poll_once()
    assert len(offered) == 2


def test_the_re_offer_is_still_no_more_often_than_the_cooldown(tmp_path):
    """comp-sync-13's property must survive: a poll every 3 s must not put
    the same path back on a pending list a 15 minute limiter is refusing to
    drain."""
    offered: list[dict] = []
    watcher, clip = _a_watcher(tmp_path, offered)
    watcher.poll_once()
    for _ in range(20):
        watcher.rearm_non_canonical(str(clip), "a.mov")
        watcher.poll_once()
    assert len(offered) == 1


def test_the_offer_book_is_still_bounded(tmp_path):
    """The re-arm book is written on the OFFER path now, which is the path a
    media pool full of non-canonical clips walks."""
    offered: list[dict] = []
    items = [make_timeline_item(str(tmp_path / "root" / "Projects" / f"c{i}.mov"))
             for i in range(watcher_mod.MAX_REARM_TRACKED + 50)]
    (tmp_path / "root" / "Projects").mkdir(parents=True)
    watcher = TimelineWatcher(
        local_root=str(tmp_path / "root"),
        canonical_prefix="P:\\",
        on_non_canonical=lambda batch: offered.extend(batch),
        get_timeline_items=lambda: {"ok": True, "message": "",
                                    "project_name": "", "items": items},
    )
    watcher.poll_once()
    assert len(watcher._rearm_due) <= watcher_mod.MAX_REARM_TRACKED


# -- regression-8: one dead loop is a dead role -----------------------------


class _LiveThread:
    def is_alive(self):
        return True


class _DeadThread:
    def is_alive(self):
        return False


def _a_cfg(tmp_path, **over):
    cfg = {"cards_agent": True, "dashboard_url": "https://dash.example",
           "dashboard_token": "cce1.aaaaaaaaaaaaaaaaaaaaaaaa",
           "jobs_mulcam_pipeline": str(tmp_path / "MulticamPipeline"),
           "jobs_vault_root": str(tmp_path / "vault")}
    cfg.update(over)
    return cfg


def _a_role(tmp_path, **over):
    from test_bug_hunt_2026_09_11_comp_resolve import FakeEngine, _fake_loader

    FakeEngine.made = []
    return role_mod.TimelineCardsRole(
        _a_cfg(tmp_path, **over),
        request_fn=lambda *a, **k: (200, {}),
        processes_fn=lambda: [],
        engine_loader=_fake_loader(tmp_path),
        bridge=object(),
    )


def test_a_role_that_lost_one_loop_is_restarted(tmp_path):
    """regression-8: comp-resolve-4 made the watchdog test `any()` alive, but
    `health()` goes STOPPED on the FIRST loop death. Push dead, pull alive:
    the grid said STOPPED for ever while the watchdog answered "running"
    every minute, and only a companion restart brought the page back."""
    role = _a_role(tmp_path)
    assert role.start() is True
    first = role._engine
    with role._lock:
        role._threads = [_DeadThread(), _LiveThread()]
    role._note_loop_end("the push loop stopped: RuntimeError: boom")
    assert role.report_block()["state"] == role_mod.HEALTH_STOPPED

    assert role.supervise_now() is True
    assert role._engine is not first
    assert first.stopped is True
    assert role.report_block()["state"] != role_mod.HEALTH_STOPPED
    role.stop()


def test_a_role_whose_loops_reported_an_error_is_not_called_running(tmp_path):
    """The same asymmetry the other way round: both threads alive but a loop
    error recorded is what `health()` calls stopped, so it must be what the
    watchdog calls dead too."""
    role = _a_role(tmp_path)
    assert role.start() is True
    with role._lock:
        role._threads = [_LiveThread(), _LiveThread()]
    role._note_loop_end("the pull loop returned")
    assert role.supervise_now() is True
    assert role.report_block()["state"] != role_mod.HEALTH_STOPPED
    role.stop()


def test_a_healthy_role_is_still_left_alone(tmp_path):
    role = _a_role(tmp_path)
    assert role.start() is True
    engine = role._engine
    assert role.supervise_now() is True
    assert role._engine is engine
    role.stop()


# -- comp-resolve-b-3: the middle cut never grows the string ----------------


@pytest.mark.parametrize("limit", list(range(0, 40)))
def test_elide_never_returns_more_than_its_cap(limit):
    """comp-resolve-b-3: at limit 4 the tail slice was `text[-0:]`, i.e. the
    whole string, so the helper whose contract is "cut this to limit"
    returned head + "..." + everything."""
    assert len(role_mod._elide("x" * 400, limit)) <= limit


def test_elide_still_keeps_both_ends_when_there_is_room():
    out = role_mod._elide("HEAD" + "y" * 200 + "TAIL", 20)
    assert len(out) <= 20
    assert out.startswith("H")
    assert out.endswith("L")


# -- comp-resolve-b-4: an UNKNOWN probe claims nothing ----------------------


_real_connect = resolve_bridge.connect


def test_a_blind_probe_does_not_claim_resolve_registered(monkeypatch, caplog):
    """comp-resolve-b-4: UNKNOWN is the fail-open answer ("the TCP table could
    not be read", "1144 is held by something that is not fuscript"). Closing
    the launch window with "script server has its host now" writes a positive
    claim the probe never made into the one line CR-68 diagnoses are read
    out of."""
    monkeypatch.setattr(resolve_bridge, "connect", _real_connect)
    monkeypatch.setattr(resolve_bridge, "_starting_since", None)
    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath", lambda: None)
    phase = {"now": (script_server.STARTING, "no host yet")}
    monkeypatch.setattr(script_server, "state", lambda: phase["now"])
    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert _real_connect() is None
        phase["now"] = (script_server.UNKNOWN, "port 1144 is held by other.exe")
        _real_connect()
    messages = [r.getMessage() for r in caplog.records]
    assert not any("has its host now" in m for m in messages), messages
    assert any("could not tell" in m for m in messages), messages


def test_a_real_registration_still_says_so(monkeypatch, caplog):
    monkeypatch.setattr(resolve_bridge, "connect", _real_connect)
    monkeypatch.setattr(resolve_bridge, "_starting_since", None)
    monkeypatch.setattr(resolve_bridge, "_ensure_env_and_syspath", lambda: None)
    phase = {"now": (script_server.STARTING, "no host yet")}
    monkeypatch.setattr(script_server, "state", lambda: phase["now"])
    with caplog.at_level(logging.INFO, logger="ccsync.resolve"):
        assert _real_connect() is None
        phase["now"] = (script_server.READY, "")
        _real_connect()
    assert any("has its host now" in r.getMessage() for r in caplog.records)
