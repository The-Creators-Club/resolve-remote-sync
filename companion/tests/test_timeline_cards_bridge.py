"""The bridge the Timeline Cards engine borrows: the lock, the guard, the sweep.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 2 (2026-08-30), §7c. No Resolve, no
project library and no keyboard here: every seam is a constructor parameter,
which is the same posture proxy_gen and jobs_runner already have.

The properties defended, each of them a way this phase's one real risk (§3.1,
"the lock is the hard part") shows up live:

  * ONE CHOKEPOINT. resolve() goes through resolve_bridge.connect(), which
    carries the CR-68 guard. An engine that connected for itself would be the
    second unguarded client on the machine.
  * THE LOCK IS THE COMPANION'S, AND IT IS SHARED. A take here excludes the
    watcher, and the watcher excludes a take here. Two schedulers, one lock.
  * IT IS HELD FOR MILLISECONDS. The hold time is measured, because the whole
    argument for the merge is that the sweep reads rows and not the API.
  * THE SWEEP IS THE LIBRARY'S, OR IT IS NOBODY'S. An API walk answered here
    would be the 11-95 s per-clip crawl the library walk exists to remove.
"""
from __future__ import annotations

import threading
import time

import pytest

from ccsync_companion import resolve_bridge
from ccsync_companion import timeline_cards_bridge as bridge_mod


@pytest.fixture
def bridge():
    return bridge_mod.CardsBridge(
        {}, connect_fn=lambda: "a-resolve", ready_fn=lambda: True,
        items_fn=lambda uid: [{"media_pool_uid": "m1", "source": "library"}])


# ----------------------------------------------------------- the connection

def test_resolve_goes_through_the_one_chokepoint(monkeypatch):
    """CR-68: connect() is the only place scriptapp() may be called, because
    it is the only place that asks the script server whether it is safe."""
    calls = []
    monkeypatch.setattr(resolve_bridge, "connect",
                        lambda: calls.append(1) or "resolve")
    assert bridge_mod.CardsBridge({}).resolve() == "resolve"
    assert calls == [1]


def test_a_connect_that_raises_is_none_not_a_traceback(bridge):
    b = bridge_mod.CardsBridge({}, connect_fn=lambda: 1 / 0)
    assert b.resolve() is None


def test_ready_is_the_script_server_guard(monkeypatch):
    from ccsync_companion import script_server

    monkeypatch.setattr(script_server, "ready_to_connect", lambda: False)
    assert bridge_mod.CardsBridge({}).ready() is False


def test_ready_fails_open(bridge):
    """The only thing this can withhold is a connection, so a probe that
    cannot answer must not be what stops the page working."""
    b = bridge_mod.CardsBridge({}, ready_fn=lambda: 1 / 0)
    assert b.ready() is True


# ------------------------------------------------------------------ the lock

def test_the_lock_is_the_companions_own(bridge):
    """A take here must exclude the watcher. Proved by taking it on this
    thread and watching another thread fail to enter resolve_bridge's."""
    entered = threading.Event()

    def watcher():
        # non-blocking take of the SAME lock the watcher's bridge_call uses
        if resolve_bridge._API_LOCK.acquire(blocking=False):
            resolve_bridge._API_LOCK.release()
            entered.set()

    with bridge.lock:
        thread = threading.Thread(target=watcher)
        thread.start()
        thread.join(2.0)
        assert not entered.is_set(), "the cards role did not exclude the watcher"
    thread = threading.Thread(target=watcher)
    thread.start()
    thread.join(2.0)
    assert entered.is_set(), "the lock was not given back"


def test_a_named_take_reads_the_same_as_a_plain_one(bridge):
    with bridge.lock("cards.conform"):
        pass
    with bridge.lock:
        pass
    stats = bridge.stats()
    assert stats["takes"] == 2


def test_the_hold_time_is_measured(bridge):
    with bridge.lock("cards.sweep"):
        time.sleep(0.05)
    stats = bridge.stats()
    assert stats["takes"] == 1
    assert 0.04 <= stats["held_max"] < 2.0
    assert stats["held_max_call"] == "cards.sweep"


def test_the_budget_a_sweep_costs_is_milliseconds(bridge):
    """THE NUMBER THIS PHASE TURNS ON (§3.1). A sweep is three cheap API
    calls under the lock and a library read outside it; a hundred of them
    must cost the watcher nothing it would notice.

    The fake Resolve here answers instantly, so what is being measured is the
    bridge's own overhead -- which is the part this repo owns.
    """
    for _ in range(100):
        with bridge.lock("cards.fingerprint"):
            pass
    stats = bridge.stats()
    assert stats["takes"] == 100
    # The watcher polls every 3 s; a hundred takes must be far inside one tick.
    assert stats["held_total"] < 0.5, stats
    assert stats["held_mean"] < 0.005, stats


def test_a_take_gives_the_lock_back_when_the_body_raises(bridge):
    with pytest.raises(ValueError):
        with bridge.lock("cards.edit"):
            raise ValueError("an edit went wrong")
    assert resolve_bridge._API_LOCK.acquire(blocking=False)
    resolve_bridge._API_LOCK.release()
    assert bridge.stats()["takes"] == 1


def test_a_slow_take_is_logged_with_its_name(bridge, monkeypatch, caplog):
    monkeypatch.setattr(bridge_mod, "SLOW_TAKE_SECONDS", 0.0)
    with caplog.at_level("WARNING", logger="ccsync.cards"):
        with bridge.lock("cards.conform"):
            pass
    assert any("cards.conform" in r.getMessage() for r in caplog.records)


# ----------------------------------------------------------------- the edits

def test_an_edit_is_visible_while_it_runs(bridge):
    assert bridge.stats()["editing"] is None
    bridge.on_edit_start("conform")
    editing = bridge.stats()["editing"]
    assert editing and editing["kind"] == "conform"
    bridge.on_edit_end("conform", ok=True, note="489 cuts")
    assert bridge.stats()["editing"] is None
    assert bridge.stats()["edits"] == 1


def test_on_edit_end_takes_its_arguments_positionally(bridge):
    """The engine calls `on_edit_end(kind, ok, note)` with no keywords
    (`resolve_engine._edit_end`), so the two defaults here are a convenience
    for us and not the shape it uses. Pinned because a signature change that
    only kept the keyword form would fail in a `finally`, after the edit,
    where the exception is swallowed."""
    bridge.on_edit_start("trim")
    bridge.on_edit_end("trim", False, "the timeline changed")
    assert bridge.stats()["editing"] is None


def test_resolve_returning_none_is_a_wait_not_a_failure(monkeypatch):
    """"Resolve is closed" and "Resolve is inside its launch window" are
    ordinary states (CR-68): the engine waits and asks again. Nothing here
    counts them, retries them or degrades on them -- `stats()` is about the
    LOCK, and a bridge that started scoring connections would be a second
    opinion about a thing `resolve_bridge` already knows."""
    bridge = bridge_mod.CardsBridge({}, connect_fn=lambda: None)
    for _ in range(5):
        assert bridge.resolve() is None
    assert bridge.stats()["takes"] == 0
    assert bridge.stats()["edits"] == 0


def test_a_failed_edit_says_so(bridge, caplog):
    with caplog.at_level("WARNING", logger="ccsync.cards"):
        bridge.on_edit_start("move")
        bridge.on_edit_end("move", ok=False, note="no timeline open")
    assert any("no timeline open" in r.getMessage() for r in caplog.records)


# ----------------------------------------------------------------- the sweep

def test_sweep_items_comes_from_the_library(monkeypatch):
    monkeypatch.setattr(
        resolve_bridge, "get_timeline_items",
        lambda allow_cached=False: {"ok": True, "timeline_uid": "TL1", "items": [
            {"media_pool_uid": "m1", "source": "library"}]})
    items = bridge_mod.CardsBridge({}).sweep_items("TL1")
    assert items == [{"media_pool_uid": "m1", "source": "library"}]


def test_another_timelines_items_are_refused(monkeypatch):
    """THE ONE THAT PUTS A CLIP ON THE WRONG CUT (§7c, finding 1). The engine
    maps these rows onto `GetItemListInTrack("video", 1)` POSITIONALLY, for
    the timeline it fingerprinted a moment ago -- and this asks the companion
    for "the current timeline", with the poll cache armed. An editor who
    switched timeline in that window would get every card's name, path and
    transcript from somebody else's cut, and nothing about the result would
    look wrong."""
    monkeypatch.setattr(
        resolve_bridge, "get_timeline_items",
        lambda allow_cached=False: {"ok": True, "timeline_uid": "TL2", "items": [
            {"media_pool_uid": "m1", "source": "library"}]})
    assert bridge_mod.CardsBridge({}).sweep_items("TL1") is None


def test_an_answer_that_cannot_say_which_timeline_is_refused(monkeypatch):
    """An old companion, or a build whose timeline has no unique id. "I do
    not know which cut this is" and "this is your cut" must not be the same
    answer to a caller that is about to index into it."""
    monkeypatch.setattr(
        resolve_bridge, "get_timeline_items",
        lambda allow_cached=False: {"ok": True, "items": [
            {"media_pool_uid": "m1", "source": "library"}]})
    assert bridge_mod.CardsBridge({}).sweep_items("TL1") is None


def test_an_engine_that_names_no_timeline_still_gets_an_answer(monkeypatch):
    """`sweep_items("")` is not a mismatch: there is nothing to disagree
    with, and refusing it would be refusing every caller that has not read a
    uid yet."""
    monkeypatch.setattr(
        resolve_bridge, "get_timeline_items",
        lambda allow_cached=False: {"ok": True, "timeline_uid": "TL9", "items": [
            {"media_pool_uid": "m1", "source": "library"}]})
    assert bridge_mod.CardsBridge({}).sweep_items("") == [
        {"media_pool_uid": "m1", "source": "library"}]


def test_the_injected_seam_answers_for_itself(monkeypatch):
    """`items_fn` takes the uid and is trusted with it -- it is what the
    suite and any future non-library source implement, and re-checking a uid
    it never claimed would refuse everything."""
    seen = []
    bridge = bridge_mod.CardsBridge(
        {}, items_fn=lambda uid: (seen.append(uid) or [{"media_pool_uid": "x"}]))
    assert bridge.sweep_items("TL1") == [{"media_pool_uid": "x"}]
    assert seen == ["TL1"]


def test_an_api_walk_is_refused_rather_than_returned(monkeypatch):
    """None means "ask Resolve yourself". Handing back the API walk would put
    the 11-95 s per-clip property crawl on the sweep's hot path -- slower than
    the engine's own, and holding the lock for all of it."""
    monkeypatch.setattr(
        resolve_bridge, "get_timeline_items",
        lambda allow_cached=False: {"ok": True, "items": [
            {"media_pool_uid": "m1", "source": "api"}]})
    assert bridge_mod.CardsBridge({}).sweep_items("TL1") is None


def test_a_failed_walk_is_none_not_a_traceback(monkeypatch):
    monkeypatch.setattr(resolve_bridge, "get_timeline_items",
                        lambda allow_cached=False: 1 / 0)
    assert bridge_mod.CardsBridge({}).sweep_items("TL1") is None


def test_no_project_is_none(monkeypatch):
    monkeypatch.setattr(
        resolve_bridge, "get_timeline_items",
        lambda allow_cached=False: {"ok": False, "message": "no project open"})
    assert bridge_mod.CardsBridge({}).sweep_items("TL1") is None


def test_the_sweep_does_not_hold_the_api_lock(monkeypatch):
    """Five seconds of a database read is five seconds of frozen tray menu."""
    held = {}

    def walk(allow_cached=False):
        held["locked"] = not resolve_bridge._API_LOCK.acquire(blocking=False)
        if not held["locked"]:
            resolve_bridge._API_LOCK.release()
        return {"ok": True, "items": []}

    monkeypatch.setattr(resolve_bridge, "get_timeline_items", walk)
    bridge_mod.CardsBridge({}).sweep_items("TL1")
    assert held["locked"] is False


# ------------------------------------------------------- the lock, from many
# threads

def test_the_plain_lock_form_is_thread_safe(monkeypatch):
    """`bridge.lock` is ONE object and the engine has three threads that take
    it (the 1 s sweep, the 0.1 s playhead read, an edit). Keeping the inner
    context and the start time on `self` meant the second thread in
    overwrote the first one's: `__exit__` then released a lock it never took
    and timed the take from the wrong instant. The state is thread-local now,
    and this is what says so."""
    import threading

    bridge = bridge_mod.CardsBridge({})
    ready = threading.Barrier(4)
    errors = []

    def take():
        try:
            ready.wait(timeout=5)
            for _ in range(20):
                with bridge.lock:
                    pass
        except Exception as exc:                       # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=take) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert errors == []
    assert all(not t.is_alive() for t in threads)
    assert bridge.stats()["takes"] == 80
    # ...and the lock is free afterwards, which is the half a broken
    # __exit__ would leave you unable to see.
    assert resolve_bridge._API_LOCK.acquire(blocking=False)
    resolve_bridge._API_LOCK.release()


def test_the_plain_form_nests_inside_a_named_one():
    """_API_LOCK is an RLock and a helper may take it inside a caller that
    already has. Stacked per thread, so the inner take does not pop the
    outer one's timing."""
    bridge = bridge_mod.CardsBridge({})
    with bridge.lock("cards.conform"):
        with bridge.lock:
            pass
    assert bridge.stats()["takes"] == 2
    assert resolve_bridge._API_LOCK.acquire(blocking=False)
    resolve_bridge._API_LOCK.release()


# ---------------------------------------------------------------- the contract

def test_the_contract_version_is_declared():
    """The role refuses an engine built against a different one, so this
    number is part of the wire between two repos."""
    assert bridge_mod.CONTRACT_VERSION == 1
    assert bridge_mod.CardsBridge({}).contract_version == 1


def test_the_bridge_satisfies_the_contract(bridge):
    """Every member §7c names, present and callable, on the real object."""
    assert callable(bridge.resolve)
    assert callable(bridge.ready)
    assert callable(bridge.on_edit_start)
    assert callable(bridge.on_edit_end)
    assert callable(bridge.sweep_items)
    assert hasattr(bridge.lock, "__enter__") and hasattr(bridge.lock, "__exit__")
    assert bridge.sweep_items("TL1") == [{"media_pool_uid": "m1",
                                          "source": "library"}]
