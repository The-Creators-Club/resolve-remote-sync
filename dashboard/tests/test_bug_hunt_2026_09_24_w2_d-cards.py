"""Wave 2 of the 2026-09-24 hunt's fix pass: the d-cards group, chunk 1.

bug-dash-cards-jobs-1..5, logic-cards-1/-2, logic-ytdl-jobs-1. Each test
names the finding it pins and fails on HEAD 4462a2a's code.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import (auth, broll, cards, cards_ai, cards_exec,
                              cards_landing, cards_pool, cards_tunnel, music)
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import jobs as jobs_mod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from test_cards_mount import (SECRET, fake_src, make_settings,  # noqa: F401
                              make_vault, open_episode)


def _settle(entry, timeout=5.0):
    end = time.monotonic() + timeout
    while entry.state == cards_pool.LOADING and time.monotonic() < end:
        time.sleep(0.005)
    return entry


class _Engine:
    """The agent half of an engine: hands out one edit, takes its result
    only if it is the one it handed out (agent.py's own rule)."""

    def __init__(self, root):
        self.root = root
        self.req = None
        self.results = []
        self.states = []
        self.playhead = None
        self.ph_uid = None

    def stop(self):
        pass

    def tick(self):
        pass

    def agent_pending(self, wait):
        if self.req is None:
            self.req = {"id": 12, "kind": "move"}
            return dict(self.req)
        return {}

    def agent_result(self, body):
        self.results.append(body)
        if self.req is None or str(body.get("id")) != str(self.req.get("id")):
            return {"ok": False, "error": "that request is no longer open"}
        self.req = None
        return {"ok": True}

    def agent_state(self, body):
        self.states.append(body)
        return {"ok": True}


def _pool(cap=2):
    return cards_pool.EnginePool(lambda root: (_Engine(root), object()), cap=cap)


def _request(pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        cards_pool=pool, cards_engine=None)))


# ------------------------------------------------ bug-dash-cards-jobs-1

def test_a_double_slash_does_not_walk_past_the_gate(tmp_path, fake_src,
                                                    monkeypatch):
    """CPython's parse_request collapses a leading `//`, so the gate saw
    `//api/root` (not blocked) and the handler dispatched `/api/root`."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entry = open_episode(app, roots[0])
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        for tail in ("//api/root", "///api/root/", "/./api/root",
                     "//api/./root", "//api/restart"):
            resp = client.post(f"/cards/p/{entry.slug}{tail}",
                               json={"root": "X:/elsewhere"})
            assert resp.status_code == 200, tail
            assert "error" in resp.json(), (tail, resp.json())
        assert entry.engine.posts == []
        assert entry.engine.restarted is False
        # The agent protocol on a SESSION, one slash deeper, is refused too.
        resp = client.post(f"/cards/p/{entry.slug}//agent/state", json={})
        assert resp.status_code == 404
        # ...and an ordinary page route still reaches the handler.
        entry.engine.audio_path = ""
        assert client.post(f"/cards/p/{entry.slug}/api/plan",
                           json={"rev": 1}).status_code == 200
        assert entry.engine.posts and entry.engine.posts[0][0] == "/api/plan"


def test_the_gate_readings_keep_the_raw_path_and_add_the_handlers():
    readings = cards._gate_readings(("//api/root",))
    assert "//api/root" in readings and "/api/root" in readings
    assert "/agent/" in cards._gate_readings(("/agent/",))


# ------------------------------------------------ bug-dash-cards-jobs-2

def test_a_result_goes_back_to_the_engine_that_handed_the_edit_out(monkeypatch):
    """Laptop in A, phone in B, one account: the result used to follow the
    LAST page request, so B refused it and A declared an applied edit lost."""
    pool = _pool()
    a = _settle(pool.open("X:/Vault/FF5/Repro Rights")[0])
    b = _settle(pool.open("X:/Vault/FF5/Framing Formosa")[0])
    monkeypatch.setattr(cards_tunnel, "_require_fleet_caller",
                        lambda request, conn: "alex")
    request = _request(pool)
    pool.note_visit(a.slug, "alex")
    handed = cards_tunnel.cards_agent_pending(request, wait=0, conn=None)
    assert handed.get("id") == 12
    # The phone's page is served next, and the laptop's navigation was first.
    pool.note_visit(b.slug, "alex")
    out = cards_tunnel.cards_agent_result({"id": 12, "ok": True}, request,
                                          conn=None)
    assert out == {"ok": True}
    assert a.engine.req is None and a.engine.results
    assert b.engine.results == []


def test_a_polling_page_does_not_drag_the_agent_off_the_episode_just_entered():
    pool = _pool()
    a = _settle(pool.open("X:/Vault/FF5/Repro Rights")[0])
    b = _settle(pool.open("X:/Vault/FF5/Framing Formosa")[0])
    pool.note_visit(a.slug, "alex", enter=True)
    for _ in range(3):
        pool.note_visit(b.slug, "alex", enter=False)    # the other page's polls
        pool.note_visit(a.slug, "alex", enter=False)
        assert pool.engine_for("alex") is a.engine
    pool.note_visit(b.slug, "alex", enter=True)         # opened B on purpose
    assert pool.engine_for("alex") is b.engine
    # A page that went quiet on the attached episode lets a live one take it.
    b.page_seen["alex"] = time.time() - cards_pool.WHERE_STALE_SECONDS - 5
    pool.note_visit(a.slug, "alex", enter=False)
    assert pool.engine_for("alex") is a.engine


def test_a_navigation_through_the_dispatcher_is_what_moves_the_agent(tmp_path,
                                                                     fake_src,
                                                                     monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault), cards_engines=2))
    a = open_episode(app, roots[0])
    b = open_episode(app, roots[1])
    pool = app.state.cards_pool
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        client.get(f"/cards/p/{a.slug}/", headers={"Accept": "text/html"})
        assert pool.where("owen") == a.slug
        client.get(f"/cards/p/{b.slug}/api/state",
                   headers={"Accept": "application/json"})
        assert pool.where("owen") == a.slug
        assert "owen" in b.seen                      # the seat is still stamped


# ------------------------------------------------ logic-cards-1

def test_one_of_two_occupants_cannot_close_the_other_ones_episode():
    pool = _pool()
    entry = _settle(pool.open("X:/Vault/FF5/Framing Formosa")[0])
    pool.note_visit(entry.slug, "alex")
    pool.note_visit(entry.slug, "ruskin")
    assert pool.may_close(entry.slug, "ruskin", False) != ""
    assert pool.may_close(entry.slug, "ruskin", True) == ""     # an admin can
    entry.seen["alex"] = time.time() - cards_pool.ACTIVE_SECONDS - 60
    assert pool.may_close(entry.slug, "ruskin", False) == ""    # alex left


def test_the_close_confirm_names_the_other_person_not_the_presser(tmp_path,
                                                                  fake_src,
                                                                  monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entry = open_episode(app, roots[0])
    entry.seen["alex"] = time.time() - 2 * 60
    entry.seen["owen"] = time.time()
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        state = client.get("/cards/state.json").json()
    row = next(r for r in state["episodes"] if r["slug"] == entry.slug)
    assert "alex was last in 2 min ago" in row["close_prompt"]
    assert "owen" not in row["close_prompt"]


# ------------------------------------------------ logic-cards-2

def test_an_idle_agent_poll_does_not_keep_its_editor_in_the_episode(monkeypatch):
    pool = _pool()
    entry = _settle(pool.open("X:/Vault/FF5/Repro Rights")[0])
    pool.note_visit(entry.slug, "alex")
    entry.seen["alex"] = time.time() - 3 * 3600          # left at lunch
    monkeypatch.setattr(cards_tunnel, "_require_fleet_caller",
                        lambda request, conn: "alex")
    request = _request(pool)
    entry.engine.req = {"id": 1}                         # nothing new to hand
    cards_tunnel.cards_agent_pending(request, wait=0, conn=None)
    cards_tunnel.cards_agent_state({"state": None, "playhead": None}, request,
                                   conn=None)            # the heartbeat
    assert entry.occupants() == []
    assert pool.may_close(entry.slug, "ruskin", False) == ""
    # ...but an agent doing WORK is somebody in it.
    cards_tunnel.cards_agent_state({"state": {"cards": []}}, request, conn=None)
    assert entry.occupants() == ["alex"]


def test_a_playhead_moved_in_resolve_counts_as_being_there(monkeypatch):
    pool = _pool()
    entry = _settle(pool.open("X:/Vault/FF5/Repro Rights")[0])
    pool.note_visit(entry.slug, "alex")
    entry.seen["alex"] = time.time() - 3 * 3600
    monkeypatch.setattr(cards_tunnel, "_require_fleet_caller",
                        lambda request, conn: "alex")
    cards_tunnel.cards_agent_state({"state": None, "playhead": 42.0},
                                   _request(pool), conn=None)
    assert entry.occupants() == ["alex"]


# ------------------------------------------------ bug-dash-cards-jobs-4

PREVIOUS = "an-old-session-secret-that-was-rotated-away-0123"


def _run_gate(gate, scope):
    seen = {}

    async def spy(inner, receive, send):
        seen["headers"] = {k.decode(): v.decode() for k, v in inner["headers"]}
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    gate.app = spy
    asyncio.run(gate(scope, receive, send))
    return seen["headers"]


def _gates():
    settings = Settings(db_path=":memory:", session_secret=SECRET,
                        session_secrets_previous=(PREVIOUS,))
    return (("/broll", broll.BrollGate(None, "t" * 32, settings)),
            ("/music", music.MusicGate(None, settings)))


@pytest.mark.parametrize("which", [0, 1])
def test_a_cookie_signed_before_a_rotation_still_names_its_editor(which):
    mount, gate = _gates()[which]
    cookie = auth.make_session_cookie(PREVIOUS, "ruskin")
    scope = {"type": "http", "method": "GET", "path": f"{mount}/api/ingest-batches",
             "root_path": mount,
             "headers": [(b"cookie", f"ccsync_session={cookie}".encode())]}
    assert _run_gate(gate, scope).get("x-ccsync-user") == "ruskin"


@pytest.mark.parametrize("which", [0, 1])
def test_the_gate_takes_the_identity_login_gate_resolved(which):
    mount, gate = _gates()[which]
    old = auth.make_session_cookie(PREVIOUS, "ruskin")
    base = {"type": "http", "method": "GET", "path": f"{mount}/api/ingest-batches",
            "root_path": mount,
            "headers": [(b"cookie", f"ccsync_session={old}".encode())]}
    resolved = dict(base, state={"ccsync_session": ("ruskin", "sid", True)})
    assert _run_gate(gate, resolved).get("x-ccsync-user") == "ruskin"
    # A session login_gate REVOKED names nobody, whatever the signature says.
    revoked = dict(base, state={"ccsync_session": (None, None, False)})
    assert "x-ccsync-user" not in _run_gate(gate, revoked)


# ------------------------------------------------ bug-dash-cards-jobs-5

def _corpus(i):
    return {"role": "user", "content": [{"type": "text", "text": f"part {i}"},
                                        {"type": "text", "text": "go"}]}


def test_the_trim_keeps_every_corpus_part():
    messages = []
    for i in range(4):
        messages += [_corpus(i), {"role": "assistant", "content": f"ok {i}"}]
    for turn in range(60):
        messages += [{"role": "user", "content": f"search {turn}"},
                     {"role": "assistant", "content": f"found {turn}"}]
    out = cards_ai._trimmed(messages)
    assert len(out) == cards_ai.MAX_TURNS * 2
    assert out[:8] == messages[:8]                      # all four parts
    assert out[-1] == messages[-1] and out[8]["content"] == "search 24"
    roles = [m["role"] for m in out]
    assert roles == ["user", "assistant"] * cards_ai.MAX_TURNS
    # Stable: trimming again after one more turn keeps the same prefix, which
    # is what lets the last-part breakpoint hit.
    more = out + [{"role": "user", "content": "x"},
                  {"role": "assistant", "content": "y"}]
    assert cards_ai._trimmed(more)[:8] == messages[:8]


# ------------------------------------------------ bug-dash-cards-jobs-3

def test_a_pinned_job_with_no_open_episode_says_what_it_waits_for(tmp_path):
    conn = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(conn)
    try:
        job_id = dbmod.create_job(conn, "peaks", {"root": "media", "rel_path": "a.mp4",
                                                  "out_root": "vault", "out_rel": "x"},
                                  {"ffmpeg": True}, now=dbmod.utcnow_iso())
        conn.execute("UPDATE jobs SET state=? WHERE id=?",
                     (dbmod.JOB_PINNED, job_id))
        conn.commit()
        executor = cards_exec.PinnedExecutor(
            SimpleNamespace(db_path=str(tmp_path / "jobs.db")), lambda: None)
        cards_exec._note_running(True)
        try:
            assert executor.tick(conn) == []
            answer = jobs_mod.explain(conn, job_id)
            assert answer["reason_code"] == jobs_mod.REASON_PINNED
            assert "no Timeline Cards episode is open" in answer["summary"]
        finally:
            cards_exec._note_running(False)
            cards_exec._NO_ENGINE.clear()
        assert "no Timeline Cards episode" not in jobs_mod.explain(
            conn, job_id)["summary"]
    finally:
        conn.close()


# ------------------------------------------------ logic-ytdl-jobs-1

MEDIA_CAPS = {"ffmpeg": True, "ffprobe": True, "mounts": ["tree", "vault", "media"],
              "idle_seconds": 900, "cpu_count": 8}
MEDIA_INPUTS = {"root": "media", "rel_path": "FF5/a.mp4", "out_root": "vault",
                "out_rel": "Vault/2026/FF5/x"}


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(c)
    yield c
    c.close()


def _machine(conn, editor, name, caps, ago_seconds=0, mode="editor"):
    at = (dbmod.parse_iso(dbmod.utcnow_iso())
          - dt.timedelta(seconds=ago_seconds)).isoformat()
    dbmod.upsert_machine_state(conn, editor, name, None, at, mode=mode)
    dbmod.store_machine_capabilities(conn, editor, name, caps, at)
    conn.execute("UPDATE machine_state SET reported_at=? WHERE editor_username=? "
                 "AND machine=?", (at, editor, name))
    conn.commit()


def _queue(conn, kind):
    job_id = dbmod.create_job(conn, kind, MEDIA_INPUTS,
                              jobs_mod.default_requires(kind, MEDIA_INPUTS),
                              now=dbmod.utcnow_iso())
    conn.commit()
    return job_id


def test_a_machine_in_a_drawer_is_not_a_schedulable_answer(conn):
    _machine(conn, "leso", "MBP", MEDIA_CAPS, ago_seconds=30 * 86400)
    answer = jobs_mod.explain(conn, _queue(conn, "proxy-480p"))
    assert answer["schedulable"] is False
    assert answer["reason_code"] == jobs_mod.REASON_SILENT
    assert answer["transient"] is False
    line = answer["machines"][0]
    assert line["reason"] == jobs_mod.REFUSE_SILENT
    assert "has not reported since" in line["why"]
    assert answer["capable"] == 1               # still hardware that could


def test_a_dead_machines_old_idle_answer_does_not_keep_a_job_transient(conn):
    _machine(conn, "leso", "MBP", dict(MEDIA_CAPS, idle_seconds=3),
             ago_seconds=30 * 86400)
    _machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, ffmpeg=False))
    answer = jobs_mod.explain(conn, _queue(conn, "proxy-480p"))
    assert answer["reason_code"] != jobs_mod.REASON_IDLE_WAIT
    assert answer["transient"] is False


def test_a_silent_machine_cannot_win_the_rank_grace(conn):
    _machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True),
             ago_seconds=2 * 3600)
    _machine(conn, "jsmith", "CPU-PC", dict(MEDIA_CAPS, nvenc=False))
    job_id = _queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "CPU-PC")["offered"] == [job_id]
    # ...and the machine that IS reporting is never judged silent by its own
    # stored row: the claim path reads machine_facts, not the fleet read.
    assert jobs_mod.offers_for_machine(conn, "ruskin", "GPU-PC",
                                       dict(MEDIA_CAPS, nvenc=True))["offered"]


def test_a_live_machine_is_untouched(conn):
    _machine(conn, "jsmith", "CPU-PC", MEDIA_CAPS, ago_seconds=60)
    answer = jobs_mod.explain(conn, _queue(conn, "peaks"))
    assert answer["schedulable"] is True


# ====================================================================
# Chunk 2: bug-dash-cards-jobs-6, logic-ytdl-jobs-6, logic-cards-3/-4/-6/-7/-8
# (logic-cards-5 was already fixed by 5a26e10's picker redesign).
# ====================================================================

import threading  # noqa: E402

from test_cards_mount import fleet_headers  # noqa: E402


@pytest.fixture
def landing2(tmp_path, fake_src, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault), cards_engines=2))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        yield client, app, roots


def _on_the_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


# ------------------------------------------------ bug-dash-cards-jobs-6

def test_open_and_close_walk_the_vault_and_stop_engines_off_the_event_loop(
        landing2, monkeypatch):
    client, app, roots = landing2
    real = cards_pool.episodes
    seen = []

    def spy(vault, *a, **kw):
        seen.append(_on_the_loop())
        return real(vault, *a, **kw)

    monkeypatch.setattr(cards_pool, "episodes", spy)
    monkeypatch.setitem(cards_landing._scan, "at", 0.0)   # the cache lapsed
    slug = cards_pool.slug_for(str(roots[0]))
    resp = client.post("/cards/open", data={"slug": slug}, follow_redirects=False)
    assert resp.status_code == 303 and "refused" not in resp.headers["location"]
    assert seen == [False], "the vault walk ran on the event loop"
    entry = _settle(app.state.cards_pool.get(slug))
    stops = []
    entry.engine.stop = lambda: stops.append(_on_the_loop())
    client.post("/cards/close", data={"slug": slug}, follow_redirects=False)
    assert stops == [False], "engine.stop() ran on the event loop"


# ------------------------------------------------ logic-ytdl-jobs-6

def _two_proxy_machines(conn):
    _machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    _machine(conn, "jsmith", "CPU-PC", dict(MEDIA_CAPS, nvenc=False))


def _second(answer):
    line = next(m for m in answer["machines"] if m.get("rank") == 2)
    return line["why"]


def test_a_forced_job_does_not_tell_the_second_machine_to_wait(conn):
    _two_proxy_machines(conn)
    job_id = dbmod.create_job(conn, "proxy-480p", MEDIA_INPUTS,
                              jobs_mod.default_requires("proxy-480p", MEDIA_INPUTS),
                              now=dbmod.utcnow_iso(), forced=True)
    conn.commit()
    why = _second(jobs_mod.explain(conn, job_id))
    assert "being offered the job now too" in why
    assert "waited" not in why and "by then" not in why


def test_a_job_past_the_grace_is_already_offered_to_everyone(conn):
    _two_proxy_machines(conn)
    old = (dbmod.parse_iso(dbmod.utcnow_iso())
           - dt.timedelta(seconds=jobs_mod.RANK_GRACE_SECONDS + 30)).isoformat()
    job_id = dbmod.create_job(conn, "proxy-480p", MEDIA_INPUTS,
                              jobs_mod.default_requires("proxy-480p", MEDIA_INPUTS),
                              now=old)
    conn.commit()
    assert "being offered the job now too" in _second(jobs_mod.explain(conn, job_id))


def test_a_fresh_job_says_how_long_the_second_machine_waits(conn):
    _two_proxy_machines(conn)
    now = dbmod.utcnow_iso()
    job_id = _queue(conn, "proxy-480p")
    why = _second(jobs_mod.explain(conn, job_id, now=now))
    assert "if nobody ahead of it has taken it by then" in why
    assert "now too" not in why


# ------------------------------------------------ logic-cards-3

def test_opening_a_second_episode_does_not_detach_the_agent_while_it_builds():
    gate = threading.Event()

    def build(root):
        if "Formosa" in root:
            gate.wait(5)
        return _Engine(root), object()

    pool = cards_pool.EnginePool(build, cap=2)
    a = _settle(pool.open("X:/Vault/FF5/Repro Rights")[0])
    pool.note_visit(a.slug, "alex", enter=True)
    b, _ = pool.open("X:/Vault/FF5/Framing Formosa")
    assert b.state == cards_pool.LOADING
    pool.note_visit(b.slug, "alex", enter=True)       # what /cards/open does
    assert pool.engine_for("alex") is a.engine
    assert "alex" in b.seen                            # the seat is still stamped
    gate.set()
    _settle(b)
    pool.note_visit(b.slug, "alex", enter=True)       # entering its page moves it
    assert pool.engine_for("alex") is b.engine


def test_the_landing_page_no_longer_promises_one_episode_per_person(landing2):
    client, _app, _roots = landing2
    page = client.get("/cards/").text
    assert "One episode at a time per person" not in page
    assert "Your Resolve follows the last episode you went into" in " ".join(page.split())


# ------------------------------------------------ logic-cards-4

def test_want_names_the_episode_that_is_not_open_and_offers_its_button(landing2):
    client, _app, roots = landing2
    slug = cards_pool.slug_for(str(roots[1]))
    page = client.get(f"/cards/?want={slug}").text
    assert f'data-want="{slug}"' in page
    banner = page.split('class="cl-want"', 1)[1].split("cl-lede", 1)[0]
    assert "FRAMING FORMOSA IS NOT OPEN" in " ".join(banner.split())
    assert f'name="slug" value="{slug}"' in banner
    # No `want`, no banner.
    assert 'class="cl-want"' not in client.get("/cards/").text


def test_entering_an_episode_page_sets_the_carry_on_cookie(landing2):
    client, app, roots = landing2
    entry = open_episode(app, roots[1])
    resp = client.get(f"/cards/p/{entry.slug}/", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert cards_landing.LAST_COOKIE in resp.headers.get("set-cookie", "")
    assert entry.slug in resp.headers.get("set-cookie", "")
    # A fetch inside the page is not an entry and sets nothing.
    api = client.get(f"/cards/p/{entry.slug}/api/state",
                     headers={"Accept": "application/json"})
    assert cards_landing.LAST_COOKIE not in api.headers.get("set-cookie", "")
    page = client.get("/cards/").text
    assert "CARRY ON WITH FRAMING FORMOSA" in page


def test_the_picker_script_goes_into_the_wanted_episode_when_it_is_ready():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static"
          / "cards_landing.js").read_text(encoding="utf-8")
    assert "data-want" in js and "location.replace(hit.href)" in js


# ------------------------------------------------ logic-cards-6

def test_an_absent_mount_names_its_own_reason_not_the_server_url(tmp_path,
                                                                 fake_src,
                                                                 monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(tmp_path / "no-vault-here")))
    assert app.state.cards_status == cards.ABSENT
    with TestClient(app) as client:
        resp = client.post("/cards/agent/state", json={"state": None},
                           headers=fleet_headers())
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail.startswith("Timeline Cards is not running on this dashboard")
    assert "the vault root is not mounted" in detail
    assert "\u2014" not in detail


# ------------------------------------------------ logic-cards-7

def test_a_build_stuck_on_the_share_gives_up_and_frees_its_seat():
    gate = threading.Event()

    def build(root):
        if "Hung" in root:
            gate.wait(5)
        return _Engine(root), object()

    pool = cards_pool.EnginePool(build, cap=1)
    hung, _ = pool.open("X:/Vault/FF5/Hung")
    assert hung.state == cards_pool.LOADING
    assert hung.as_dict()["opening_seconds"] is not None
    hung.opened_at -= cards_pool.BUILD_DEADLINE_SECONDS + 1
    assert pool.get(hung.slug).state == cards_pool.FAILED
    assert "did not answer" in hung.detail
    other = _settle(pool.open("X:/Vault/FF5/Other")[0])   # the seat is free
    assert other.state == cards_pool.READY
    gate.set()                                            # the share wakes up
    end = time.monotonic() + 5
    while "too late" not in hung.detail and time.monotonic() < end:
        time.sleep(0.005)
    # No seat left by then: it is stopped, never published over the cap.
    assert hung.state == cards_pool.FAILED and "too late" in hung.detail
    assert pool.ready_asgi(hung.slug) is None
    assert len([e for e in pool.entries() if e.state == cards_pool.READY]) == 1


def test_a_slow_build_that_finishes_after_the_deadline_is_still_published():
    gate = threading.Event()

    def build(root):
        gate.wait(5)
        return _Engine(root), object()

    pool = cards_pool.EnginePool(build, cap=2)
    slow, _ = pool.open("X:/Vault/FF5/Slow")
    slow.opened_at -= cards_pool.BUILD_DEADLINE_SECONDS + 1
    assert pool.get(slow.slug).state == cards_pool.FAILED
    gate.set()
    end = time.monotonic() + 5
    while slow.state != cards_pool.READY and time.monotonic() < end:
        time.sleep(0.005)
    assert slow.state == cards_pool.READY


def test_the_landing_row_says_how_long_an_episode_has_been_opening():
    assert cards_landing._opening_phrase(cards_pool.LOADING, 30) == ""
    phrase = cards_landing._opening_phrase(cards_pool.LOADING, 4 * 60 + 5)
    assert phrase.startswith("opening for 4 min")
    assert cards_landing._opening_phrase(cards_pool.READY, 600) == ""


# ------------------------------------------------ logic-cards-8

def test_health_reports_an_agent_that_left_as_not_attached():
    class Gone:
        agent_name = "alex/CREATOR-1"

        def agent_here(self):
            return False

    pool = _pool()
    entry = _settle(pool.open("X:/Vault/FF5/Repro Rights")[0])
    entry.engine = Gone()
    app = SimpleNamespace(state=SimpleNamespace(
        cards_status=cards.MOUNTED, cards_detail="", cards_pool=pool,
        cards_engine=None, settings=SimpleNamespace()))
    out = cards.health_block(app)
    assert out["open"][0]["agent"] is False
    assert out["open"][0]["last_agent"] == "alex/CREATOR-1"
    assert out["agent"] is False
    # An older checkout with no agent_here keeps the old answer.
    entry.engine = SimpleNamespace(agent_name="alex/CREATOR-1")
    assert cards.health_block(app)["open"][0]["agent"] is True


# ================================================= owed round (2026-09-25)
# Items other groups' builders left for d-cards: bug-comp-media-3 (c-media),
# logic-cards-9 (c-resolve), bug-dash-ops-2/-3 (d-ops), ui-copy-6 (d-ui).

# ------------------------------------------------ bug-comp-media-3

def _pinned_paths(tmp_path, stem):
    executor = cards_exec.PinnedExecutor(
        SimpleNamespace(db_path=":memory:",
                        jobs_roots={"media": str(tmp_path / "m"),
                                    "vault": str(tmp_path / "v")}),
        lambda: None)
    return executor._paths({"inputs": {"root": "media", "rel_path": "a/b.mp4",
                                       "out_root": "vault", "out_rel": "cache",
                                       "out_stem": stem}})


@pytest.mark.parametrize("stem", ["..", ".", "Interview 1/2", "/etc/x",
                                  "../../../x", "C:/Windows/Temp/x",
                                  "nul\x00byte", "tab\there"])
def test_a_pinned_out_stem_that_is_not_a_plain_name_is_refused(tmp_path, stem):
    with pytest.raises(cards_exec.ExecutorError, match="plain file name"):
        _pinned_paths(tmp_path, stem)


@pytest.mark.parametrize("stem", ["Q&A: Ruskin", "back\\slash", "C:x",
                                  "Interview (2) - take.1"])
def test_a_name_only_windows_refuses_is_made_by_the_linux_engine(tmp_path, stem):
    # The dashboard's engine is where such a name still gets made; refusing it
    # here as well would leave the job made nowhere.
    assert _pinned_paths(tmp_path, stem)[2] == stem


def test_an_empty_out_stem_still_takes_the_sources_own_name(tmp_path):
    assert _pinned_paths(tmp_path, "  ")[2] == "b"


# ------------------------------------------------ logic-cards-9

def test_the_no_engine_answer_says_it_is_not_attached():
    answer = cards_tunnel._no_engine("owen")
    assert answer["attached"] is False
    # The companion's fallback for a dashboard without the key matches this.
    assert "is not in a Timeline Cards episode" in answer["error"]


def test_the_long_polls_no_engine_answer_says_it_is_not_attached():
    import inspect
    src = inspect.getsource(cards_tunnel)
    assert '{"note": answer.get("error", ""), "attached": False}' in src


# ------------------------------------------------ bug-dash-ops-2 / -3

@pytest.mark.parametrize("which", [0, 1])
def test_two_session_cookies_name_the_last_one_as_login_gate_does(which):
    mount, gate = _gates()[which]
    first = auth.make_session_cookie(SECRET, "alice")
    last = auth.make_session_cookie(SECRET, "bob")
    scope = {"type": "http", "method": "GET", "path": f"{mount}/api/ingest-batches",
             "root_path": mount,
             "headers": [(b"cookie", f"ccsync_session={first}; "
                                     f"ccsync_session={last}".encode())]}
    assert _run_gate(gate, scope).get("x-ccsync-user") == "bob"


@pytest.mark.parametrize("which", [0, 1])
def test_with_the_dashboard_in_scope_the_gate_asks_login_gates_resolver(
        which, monkeypatch):
    mount, gate = _gates()[which]
    asked = []

    def resolver(request):
        asked.append(request)
        return None  # e.g. a session revoked server-side

    monkeypatch.setattr(auth, "get_session_user", resolver)
    cookie = auth.make_session_cookie(SECRET, "alice")
    scope = {"type": "http", "method": "GET", "path": f"{mount}/api/ingest-batches",
             "root_path": mount,
             "app": SimpleNamespace(state=SimpleNamespace(settings=object())),
             "headers": [(b"cookie", f"ccsync_session={cookie}".encode())]}
    assert "x-ccsync-user" not in _run_gate(gate, scope)
    assert asked


# ------------------------------------------------ ui-copy-6

def test_the_cards_sentences_a_page_shows_carry_no_typewriter_dash():
    import inspect
    for sentence in cards.BLOCKED_PATHS.values():
        assert " -- " not in sentence
    assert " -- " not in cards_tunnel._no_engine("x")["error"]
    src = inspect.getsource(cards.CardsDispatch._not_open) + \
        inspect.getsource(cards.CardsDispatch._not_here)
    assert " -- " not in src


@pytest.mark.parametrize("stem", ["C:/Windows/Temp/x", "/etc/cron.d/x", "../../../x",
                                  "Interview 1/2", "..", " . ", "a\x00b", "tab\there",
                                  "del\x7f", "Q&A: Ruskin", "back\slash", "C:x",
                                  "  padded  ", "Interview 3 (wide) - v2.final"])
def test_the_pinned_engine_and_the_submit_check_agree(tmp_path, stem):
    # jobs.out_stem_problem refuses at POST time; the pinned engine must not
    # refuse a job the POST accepted, nor make one it refused.
    submit_refuses = jobs_mod.out_stem_problem(
        dbmod.JOB_KIND_PEAKS, {"out_stem": stem}) is not None
    try:
        _pinned_paths(tmp_path, stem)
        engine_refuses = False
    except cards_exec.ExecutorError:
        engine_refuses = True
    assert engine_refuses == submit_refuses
