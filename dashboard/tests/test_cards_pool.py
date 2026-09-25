"""Two people, two episodes: the pool, the landing page and the slug.

docs/CARDS_TWO_PROJECTS.md phase 1 (2026-09-14). `test_cards_mount.py` still
owns the shim, the gate and the tunnel; this suite owns what the pool added.

The properties defended, each of them a way this goes wrong live:

  * A PATH IS NOT A KEY (CR-90). The slug is minted from an NFC-normalised,
    case-folded path, so a Mac's NFD spelling of an episode and everyone
    else's NFC spelling are ONE episode, not two engines on one folder.
  * ONE DATA DIR PER ENGINE. They used to share `<data>/cards`, where
    `project_pick.doc_save` is a read-merge-write through a fixed `.tmp` with
    no cross-process lock: two engines calling `remember()` at once truncate
    each other.
  * THE CAP IS A SENTENCE, NOT A SILENCE. There is no eviction, because
    `stop()` in the other repo does not stop the three `while True` threads,
    so the third entrant is refused with who is where and what to do.
  * THE LANDING PAGE NEEDS NO ENGINE. It is what a person sees exactly when
    every engine is busy, loading or broken.
  * `/api/root` IS BLOCKED. One click on the drawer's root menu would move
    engine A onto root B and make the pool's key a lie.
  * THE PHONE BREAKS FIRST. The old worker's scope covers the new URLs, so
    `/cards/sw.js` is a kill switch; and the manifest, icon and worker under
    the episode prefix must be reachable with no session or Chrome calls the
    page not installable (CR-100).
"""
from __future__ import annotations

import time
import unicodedata

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, cards, cards_pool
from ccsync_dashboard.app import create_app

from test_cards_mount import (SECRET, fake_src, make_settings,  # noqa: F401
                              make_vault, open_episode)


# ------------------------------------------------------------------ the slug

def test_the_two_spellings_of_a_mac_path_are_one_episode():
    """CR-90: macOS listdir is NFD, the NAS and Windows are NFC, and
    `Matej Simalcik` in the two spellings is two byte strings. A slug minted
    off the raw path would be two engines on one folder, each rewriting the
    other's stores."""
    nfc = unicodedata.normalize("NFC", "X:/Vault/2026/FF5/Matej Šimalčík")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd                                    # the premise
    assert cards_pool.slug_for(nfc) == cards_pool.slug_for(nfd)


def test_the_slug_ignores_case_and_separators_the_way_a_share_does():
    assert (cards_pool.slug_for("X:\\Vault\\FF5\\Civil Defence")
            == cards_pool.slug_for("x:/vault/ff5/civil defence/"))


def test_a_slug_is_url_shaped_even_for_a_root_with_no_ascii_in_it():
    """The readable half is decoration; the digest is what is load-bearing.
    A CJK episode name has no readable half and must still route."""
    slug = cards_pool.slug_for("X:/Vault/2026/FF5/台中無人機")
    assert cards_pool.is_slug(slug), slug
    assert slug != cards_pool.slug_for("X:/Vault/2026/FF5/台北無人機")


def test_two_episodes_do_not_share_a_slug():
    a = cards_pool.slug_for("X:/Vault/FF5/Civil Defence")
    b = cards_pool.slug_for("X:/Vault/FF5/Framing Formosa")
    assert a != b and cards_pool.is_slug(a) and cards_pool.is_slug(b)


def test_junk_in_the_path_is_not_a_slug():
    for junk in ("", "../etc", "a" * 60, "Civil Defence", "x/y"):
        assert cards_pool.is_slug(junk) is False


# -------------------------------------------------------------- the registry

def test_the_vault_scan_finds_episodes_and_not_their_insides(tmp_path):
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    (roots[0] / "Interviewees" / "Enoch" / "Clips").mkdir(parents=True)
    found = cards_pool.episodes(str(vault))
    assert [r["name"] for r in found] == ["Civil Defence", "Framing Formosa"]
    assert [r["show"] for r in found] == ["FF5", "FF5"]
    # ...and NOT the Interviewees folder that has a Clips in it: the walk
    # stops at the first folder that is itself an episode.
    assert all("Interviewees" not in r["root"] for r in found)


def test_the_scan_reaches_the_live_tree_which_is_four_deep(tmp_path):
    """The default depth is the DEPLOYED shape, not a guess (2026-09-14).

    `DASH_CARDS_VAULT_ROOT` is `/vault` -- the whole `vault_host` share -- and
    the episode `site.toml` names is `/vault/Vault/2026/FF5/Civil Defence`:
    Vault, 2026, FF5, episode. A three-level walk answers an empty list
    there, which is a landing page with nothing on it and nothing to explain
    why. Found before this page was ever deployed; keep it found.
    """
    vault = tmp_path / "vault"
    root = vault / "Vault" / "2026" / "FF5" / "Civil Defence"
    (root / "Interviewees").mkdir(parents=True)
    found = cards_pool.episodes(str(vault))
    assert [r["name"] for r in found] == ["Civil Defence"]
    assert found[0]["show"] == "FF5"


def test_a_vault_that_is_not_there_is_an_empty_list_not_a_raise(tmp_path):
    assert cards_pool.episodes(str(tmp_path / "gone")) == []
    assert cards_pool.episodes("") == []


# ------------------------------------------------------------------ the pool

class FakeEngine:
    def __init__(self, root):
        self.root = root
        self.stopped = False

    def stop(self):
        self.stopped = True

    def fleet_execute(self, *a, **kw):           # the pinned-executor seam
        return {}


def make_pool(cap=2, fail=""):
    built = []

    def build(root):
        if fail and fail in root:
            raise RuntimeError("no postgres")
        engine = FakeEngine(root)
        built.append(engine)
        return engine, object()

    return cards_pool.EnginePool(build, cap=cap), built


def settle(entry, timeout=5.0):
    end = time.monotonic() + timeout
    while entry.state == cards_pool.LOADING and time.monotonic() < end:
        time.sleep(0.005)
    return entry


def test_opening_the_same_episode_twice_is_one_engine():
    pool, built = make_pool()
    first, _ = pool.open("X:/Vault/FF5/Civil Defence")
    settle(first)
    again, refusal = pool.open("X:/Vault/FF5/Civil Defence/")   # same place
    assert refusal == "" and again is first
    assert len(built) == 1


def test_the_third_episode_is_refused_with_who_is_where():
    """No eviction: `stop()` upstream sets a flag the library worker, the
    tokens worker and the translator do not read, so an LRU would leak a
    sweep and a translator per evicted engine. The refusal is the feature."""
    pool, _ = make_pool(cap=2)
    a, _ = pool.open("X:/Vault/FF5/Civil Defence", name="Civil Defence")
    b, _ = pool.open("X:/Vault/FF5/Framing Formosa", name="Framing Formosa")
    settle(a), settle(b)
    pool.note_visit(a.slug, "alex")
    pool.note_visit(b.slug, "ruskin")
    third, refusal = pool.open("X:/Vault/FF6/Repro Rights", name="Repro Rights")
    assert third is None
    assert "2 episodes are already open" in refusal
    assert "Civil Defence (alex)" in refusal
    assert "Framing Formosa (ruskin)" in refusal
    assert "admin" in refusal                       # what to do about it


def test_closing_one_frees_the_seat_and_stops_that_engine():
    pool, built = make_pool(cap=1)
    a, _ = pool.open("X:/Vault/FF5/Civil Defence")
    settle(a)
    assert pool.open("X:/Vault/FF5/Framing Formosa")[0] is None
    assert "closed" in pool.drop(a.slug)
    assert built[0].stopped is True
    b, refusal = pool.open("X:/Vault/FF5/Framing Formosa")
    assert b is not None and refusal == ""


def test_an_episode_that_will_not_build_holds_no_seat():
    """A failed entry must not spend the cap: an episode with a broken
    PostgreSQL would otherwise lock a person out of the one that works."""
    pool, _ = make_pool(cap=1, fail="Broken")
    bad, _ = pool.open("X:/Vault/FF5/Broken")
    settle(bad)
    assert bad.state == cards_pool.FAILED
    good, refusal = pool.open("X:/Vault/FF5/Civil Defence")
    assert good is not None, refusal


def test_any_engine_answers_for_the_pinned_executor():
    """A pinned media job's paths are (root name, relative path) pairs
    resolved against the CONTAINER's mounts, so any engine's ffmpeg worker
    can run any job. What matters is that there may be none."""
    pool, _ = make_pool()
    assert pool.any_engine() is None
    entry, _ = pool.open("X:/Vault/FF5/Civil Defence")
    settle(entry)
    assert pool.any_engine() is entry.engine


def test_an_editor_is_in_exactly_one_episode_at_a_time():
    pool, _ = make_pool()
    a, _ = pool.open("X:/Vault/FF5/Civil Defence")
    b, _ = pool.open("X:/Vault/FF5/Framing Formosa")
    settle(a), settle(b)
    pool.note_visit(a.slug, "alex")
    assert pool.engine_for("alex") is a.engine
    pool.note_visit(b.slug, "alex")             # the laptop moved episode
    assert pool.engine_for("alex") is b.engine
    assert pool.engine_for("ruskin") is None
    assert pool.engine_for("") is None


def test_stop_all_stops_every_engine():
    pool, built = make_pool()
    for root in ("X:/Vault/FF5/A", "X:/Vault/FF5/B"):
        settle(pool.open(root)[0])
    pool.stop_all()
    assert [e.stopped for e in built] == [True, True]
    assert pool.entries() == []


# ------------------------------------------------------------ the data dirs

def test_every_engine_gets_its_own_data_dir(tmp_path, fake_src, monkeypatch):
    """They used to share `<data>/cards`, which holds the mirror, the
    picker's memory and the lane keys -- and `project_pick.doc_save` is a
    read-merge-write through a fixed `.tmp` with no cross-process lock."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entries = [open_episode(app, root) for root in roots]
    dirs = [e.engine.built["data_dir"] for e in entries]
    assert dirs[0] != dirs[1]
    assert all(d and str(tmp_path) in d for d in dirs)
    for entry, data in zip(entries, dirs):
        assert data.endswith(entry.slug)


def test_the_boot_root_in_cards_ui_json_is_not_read_any_more(tmp_path, fake_src,
                                                             monkeypatch):
    """It recorded "the root the UI last picked" for a container with one
    engine in it. With a pool it is at best meaningless and at worst a second
    engine on a root that already has one: the URL carries the key now."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    data = tmp_path / "cards"
    data.mkdir()
    (data / "cards_ui.json").write_text('{"root": "%s"}'
                                        % str(roots[1]).replace("\\", "/"),
                                        encoding="utf-8")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entry = open_episode(app, roots[0])
    assert entry.engine.root == str(roots[0])


# --------------------------------------------------------- the landing page

@pytest.fixture
def landing(tmp_path, fake_src, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault), cards_engines=2))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        yield client, app, roots


def test_the_landing_page_draws_with_no_engine_at_all(landing):
    client, app, _ = landing
    assert app.state.cards_pool.entries() == []          # nothing built yet
    page = client.get("/cards/")
    assert page.status_code == 200
    assert "Civil Defence" in page.text
    assert "Framing Formosa" in page.text


def test_opening_an_episode_from_the_page_then_entering_it(landing):
    client, app, roots = landing
    slug = cards_pool.slug_for(str(roots[0]))
    opened = client.post("/cards/open", data={"slug": slug},
                         follow_redirects=False)
    assert opened.status_code == 303
    entry = app.state.cards_pool.get(slug)
    assert entry is not None
    while entry.state == cards_pool.LOADING:
        time.sleep(0.01)
    assert entry.state == cards_pool.READY
    assert client.get(f"/cards/p/{slug}/").status_code == 200


def test_an_episode_that_is_not_open_sends_a_navigation_to_the_landing_page(landing):
    """It never builds an engine in the request path: construction reads an
    episode off a share, and this runs on the event loop."""
    client, app, roots = landing
    slug = cards_pool.slug_for(str(roots[0]))
    resp = client.get(f"/cards/p/{slug}/", follow_redirects=False,
                      headers={"Accept": "text/html"})
    assert resp.status_code == 303
    assert resp.headers["location"].endswith(f"/cards/?want={slug}")
    assert app.state.cards_pool.entries() == []
    # ...and a FETCH gets JSON, never a login-page-shaped surprise.
    api = client.get(f"/cards/p/{slug}/api/state",
                     headers={"Accept": "application/json"})
    assert api.status_code == 409
    assert api.json()["landing"] == "/cards/"


def test_a_flat_page_url_from_before_the_pool_says_where_it_went(landing):
    client, app, _ = landing
    api = client.get("/cards/api/state", headers={"Accept": "application/json"})
    assert api.status_code == 404
    assert "one page per episode" in api.json()["error"]


def test_a_non_admin_cannot_close_an_episode_somebody_else_is_in(landing):
    """security-2 (2026-09-18) replaced "admin only" with "not somebody
    else's". Taking an episode away from whoever is IN it is still the act
    that must not happen by accident."""
    client, app, roots = landing
    entry = open_episode(app, roots[0])
    app.state.cards_pool.note_visit(entry.slug, "owen")
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "jsmith"))
    resp = client.post("/cards/close", data={"slug": entry.slug},
                       follow_redirects=False)
    assert "refused=" in resp.headers["location"]
    assert app.state.cards_pool.get(entry.slug) is not None
    # ...and an admin still can.
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "owen"))
    client.post("/cards/close", data={"slug": entry.slug}, follow_redirects=False)
    assert app.state.cards_pool.get(entry.slug) is None


def test_the_cap_refusal_reaches_the_page(landing, monkeypatch):
    client, app, roots = landing
    app.state.cards_pool.cap = 1
    open_episode(app, roots[0])
    slug = cards_pool.slug_for(str(roots[1]))
    resp = client.post("/cards/open", data={"slug": slug},
                       follow_redirects=False)
    assert "refused=" in resp.headers["location"]
    page = client.get(resp.headers["location"])
    assert "already open" in page.text


# ----------------------------------------------------------- /api/root gone

def test_the_root_switch_is_blocked_inside_the_page(tmp_path, fake_src, monkeypatch):
    """A live route in the drawer. With one engine it WAS the feature; with
    an engine per episode it moves engine A onto root B -- which may already
    have an engine of its own."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entry = open_episode(app, roots[0])
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        for path in (f"/cards/p/{entry.slug}/api/root",
                     f"/cards/p/{entry.slug}/api/root/"):
            resp = client.post(path, json={"root": "X:/elsewhere"})
            assert resp.status_code == 200
            assert "one engine per episode" in resp.json()["error"]
        assert entry.engine.posts == []              # never reached the handler


# --------------------------------------------------------------- the phone

def test_the_flat_service_worker_is_a_kill_switch(landing):
    """Its scope is `/cards/`, which covers every `/cards/p/<slug>/` URL, and
    every navigation in scope goes through the old worker's own shellAnswer:
    a phone whose network verdict is "down" would be served the OLD page over
    the new project URL."""
    client, _, _ = landing
    resp = client.get("/cards/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "unregister()" in resp.text
    assert "addEventListener('fetch'" not in resp.text


def test_the_three_pwa_surfaces_are_open_under_the_episode_prefix(landing):
    """CR-100 and its 2026-09-04 sibling, one prefix deeper. A manifest is
    fetched WITHOUT the session cookie: behind the gate Chrome gets a 303 to
    /login, calls the page not installable, and the worker's periodic update
    fetch installs the login page as its own script."""
    client, app, roots = landing
    entry = open_episode(app, roots[0])
    client.cookies.clear()
    for name in ("sw.js", "manifest.webmanifest", "icon.svg"):
        resp = client.get(f"/cards/p/{entry.slug}/{name}",
                          follow_redirects=False)
        assert resp.status_code != 303, name
        assert "login" not in str(resp.headers.get("location", "")), name


def test_the_flat_manifest_and_icon_stay_open_for_an_older_install(landing):
    client, _, _ = landing
    client.cookies.clear()
    manifest = client.get("/cards/manifest.webmanifest", follow_redirects=False)
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/cards/"
    assert client.get("/cards/icon.svg", follow_redirects=False).status_code == 200


def test_the_open_pattern_never_widens_past_those_three():
    """The pattern is the thing that could quietly open the whole page."""
    from ccsync_dashboard.app import _open_path

    assert _open_path("/cards/p/civil-defence-1234abcd/sw.js") is True
    assert _open_path("/cards/p/civil-defence-1234abcd/api/state") is False
    assert _open_path("/cards/p/civil-defence-1234abcd/") is False
    assert _open_path("/cards/p/../sw.js") is False


def test_reopening_an_episode_serves_the_NEW_engine(landing):
    """A gate cached by slug alone would go on serving the engine that was
    closed -- stopped threads, its own idea of the cut -- for the life of the
    container, and the slug is deliberately stable across a close."""
    client, app, roots = landing
    first = open_episode(app, roots[0])
    assert client.get(f"/cards/p/{first.slug}/api/state").status_code == 200
    app.state.cards_pool.drop(first.slug)
    second = open_episode(app, roots[0])
    assert second.slug == first.slug and second.engine is not first.engine
    second.engine.audio_path = ""
    assert client.post(f"/cards/p/{second.slug}/api/plan",
                       json={"rev": 1}).status_code == 200
    assert second.engine.posts and first.engine is None


def test_an_episode_closed_while_it_was_opening_is_stopped_not_leaked():
    """The builder thread holds a half-built episode; `drop` takes the entry
    out from under it. Published anyway, that is an engine with running
    threads and nothing holding a reference to it -- the shape
    dash-release-jobs-1 cost us once already, one layer down."""
    import threading

    go = threading.Event()
    built = []

    def build(root):
        go.wait(5.0)
        engine = FakeEngine(root)
        built.append(engine)
        return engine, object()

    pool = cards_pool.EnginePool(build, cap=2)
    entry, _ = pool.open("X:/Vault/FF5/Civil Defence")
    assert pool.drop(entry.slug).startswith("closed")
    go.set()
    end = time.monotonic() + 5.0
    while not built and time.monotonic() < end:
        time.sleep(0.005)
    while built[0].stopped is False and time.monotonic() < end:
        time.sleep(0.005)
    assert built[0].stopped is True
    assert pool.entries() == []


# -- the 2026-09-18 hunt: dash-cards-2/-3/-4/-5/-6/-7/-9, security-2 ----------


def _settle(entry, timeout=5.0):
    end = time.monotonic() + timeout
    while entry.state == cards_pool.LOADING and time.monotonic() < end:
        time.sleep(0.005)
    return entry


def test_an_episode_that_failed_to_build_can_be_opened_again():
    """dash-cards-2 / dash-cards-9: `open()` used to be idempotent on the SLUG,
    not on the state, so a FAILED entry was handed back with an empty refusal
    for the life of the container. The landing page drew [ FAILED ], offered
    [ OPEN ], and the click changed nothing: a share that was not up at the
    moment somebody clicked poisoned that episode until the next deploy.

    The old test beside this one (`..._holds_no_seat`) only proved a DIFFERENT
    root could still open, which is why the defect shipped green.
    """
    calls = []

    def build(root):
        calls.append(root)
        if len(calls) == 1:
            raise OSError("the vault share is not up yet")
        return FakeEngine(root), object()

    pool = cards_pool.EnginePool(build, cap=2)
    entry = _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    assert entry.state == cards_pool.FAILED
    # The retry floor is real, so a page somebody keeps clicking cannot start
    # a build a second; the test drives past it rather than sleeping 20 s.
    entry.failed_at = time.time() - cards_pool.RETRY_FLOOR_SECONDS - 1
    again, refusal = pool.open("X:/Vault/FF5/Civil Defence")
    assert refusal == ""
    assert again is not entry
    assert _settle(again).state == cards_pool.READY
    assert len(calls) == 2


def test_a_failed_episode_is_not_rebuilt_on_every_click():
    """dash-cards-2's floor: a build that fails SLOWLY plus a landing page
    somebody keeps pressing is one thread per press."""
    calls = []

    def build(root):
        calls.append(root)
        raise OSError("still not up")

    pool = cards_pool.EnginePool(build, cap=2)
    _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    again, refusal = pool.open("X:/Vault/FF5/Civil Defence")
    assert again is None and "Wait" in refusal
    assert len(calls) == 1


def test_the_cap_refusal_names_a_place_that_exists_and_an_act_that_works():
    """dash-cards-3: the sentence named `Settings > Timeline Cards`, which is
    not a page anywhere in the tree, and told the blocked editor to ask
    somebody to "leave" an episode - which frees nothing, because a seat is
    held by the ENTRY and only `drop()` removes one."""
    pool = cards_pool.EnginePool(lambda root: (FakeEngine(root), object()),
                                 cap=1)
    _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    _entry, refusal = pool.open("X:/Vault/FF5/Talent Gap")
    assert "Settings" not in refusal
    assert "leave it" not in refusal
    assert '"Close"' in refusal  # D8, UI port phase 7


def test_an_editor_can_close_the_episode_they_are_in_and_an_idle_one():
    """security-2: opening was open to every session and closing was
    admin-only with no idle release, so two mistaken opens by one non-admin
    parked the feature until an admin was found."""
    pool = cards_pool.EnginePool(lambda root: (FakeEngine(root), object()),
                                 cap=2)
    entry = _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    assert pool.may_close(entry.slug, "jsmith", False) == ""    # nobody in it
    pool.note_visit(entry.slug, "jsmith")
    assert pool.may_close(entry.slug, "jsmith", False) == ""    # their own
    pool.note_visit(entry.slug, "ruskin")
    assert pool.may_close(entry.slug, "leso", False) != ""      # somebody's
    assert pool.may_close(entry.slug, "leso", True) == ""       # an admin


def test_closing_an_episode_evicts_its_wsgi_gate_and_its_thread_pool():
    """dash-cards-5: `CardsDispatch._gates` had no deletion path, so the
    a2wsgi middleware - and the ThreadPoolExecutor(max_workers=24) it builds
    in its own __init__ - stayed reachable from the mounted dispatcher for the
    life of the container. Closing an episode to free a seat made the thread
    count worse than docs/CARDS_TWO_PROJECTS.md section 12 says it is."""
    class FakeMiddleware:
        def __init__(self):
            self.executor = self
            self.shut = False

        def shutdown(self, wait=True):
            self.shut = True

    asgi = FakeMiddleware()
    pool = cards_pool.EnginePool(lambda root: (FakeEngine(root), asgi), cap=2)
    dispatch = cards.CardsDispatch(pool, lambda app: app)
    pool.set_evict_hook(dispatch.evict)
    entry = _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    dispatch._gates[entry.slug] = (asgi, object())
    pool.drop(entry.slug)
    assert entry.slug not in dispatch._gates
    assert asgi.shut is True


def test_the_flat_data_dir_is_named_rather_than_silently_orphaned(tmp_path,
                                                                  caplog):
    """dash-cards-6: moving the engine's data_dir to `<data>/cards/<slug>`
    orphaned `library_backups` - the safety net for the cut list itself - and
    said nothing. We do not adopt them (which episode they belonged to is not
    recorded anywhere, and guessing wrong writes one episode's pick into
    another); we name both paths once."""
    import logging

    from ccsync_dashboard.settings import Settings

    data = tmp_path / "data"
    (data / "cards" / "library_backups").mkdir(parents=True)
    (data / "cards" / "cards_pick.json").write_text("{}", encoding="utf-8")
    settings = Settings(db_path=str(data / "dashboard.db"),
                        session_secret=SECRET)
    cards._SAID_WHERE.clear()
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.cards"):
        out = cards.data_dir_for(settings, "ep-abcdef01")
    assert out and out.endswith("ep-abcdef01")
    said = "\n".join(r.getMessage() for r in caplog.records)
    assert "library_backups" in said and "cards_pick.json" in said
    assert str(data / "cards") in said


def test_the_kill_switch_leaves_the_dashboards_own_caches_alone():
    """dash-cards-4: CacheStorage is per ORIGIN, so the unfiltered
    `caches.keys()` sweep emptied the dashboard PWA's own `ccsync-<version>`
    precache (the offline page, htmx_errors.js) and `cards-media`, the clips
    an editor deliberately downloaded for an offline session."""
    from ccsync_dashboard import cards_landing

    js = cards_landing.KILL_SW
    assert "unregister()" in js
    body = js[js.index("addEventListener('activate'"):]
    assert "await caches.keys()) await caches.delete(k)" not in body


def test_the_kill_switch_deletes_no_cache_at_all():
    """dash-cards-1: the narrowed sweep was narrowed to nothing. Every page
    this checkout serves - the dead flat one and every live /cards/p/<slug>/
    one - names its shell cache `cards-shell-<one page_version()>` on ONE
    origin, so the prefix filter deleted the live per-episode worker's shell,
    which only `install` can refill. The kill switch cannot tell them apart,
    so it touches CacheStorage not at all."""
    from ccsync_dashboard import cards_landing

    body = cards_landing.KILL_SW
    body = body[body.index("addEventListener('install'"):]
    assert "caches" not in body
    assert "unregister()" in body


def test_the_failed_episode_detail_is_not_another_repos_exception_text():
    """dash-cards-7: this was the one place in the dashboard that rendered
    another repo's exception into a browser. A psycopg OperationalError
    carries host, port, database and user."""
    def build(root):
        raise OSError('connection to server at "192.168.0.102", port 5432, '
                      'user "cards" failed')

    pool = cards_pool.EnginePool(build, cap=2)
    entry = _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    assert entry.state == cards_pool.FAILED
    assert "192.168.0.102" not in entry.detail
    assert "OSError" in entry.detail


# ---------------------------------------------------------------------------
# security-1 (2026-09-18b mediums): the 15-minute idle release measures SERVED
# REQUESTS, so an editor working OFFLINE in Cards was evictable by any other
# signed-in session.
# ---------------------------------------------------------------------------


def test_an_agents_poll_keeps_its_editors_seat_while_their_browser_is_offline():
    """`seen` was stamped only by a request served through the mount, so a
    laptop that went offline mid-session dropped its seat after ACTIVE_SECONDS
    even while its companion agent was still driving Resolve against that
    engine. The agent call is the one liveness signal that survives the
    browser, and the tunnel routes it by verified identity."""
    pool = cards_pool.EnginePool(lambda root: (FakeEngine(root), object()),
                                 cap=2)
    entry = _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    pool.note_visit(entry.slug, "ruskin")
    entry.seen["ruskin"] = time.time() - cards_pool.ACTIVE_SECONDS - 60
    assert entry.occupants() == []
    assert pool.may_close(entry.slug, "leso", False) == ""
    pool.note_agent("Ruskin")            # the identity is case-folded
    assert entry.occupants() == ["ruskin"]
    assert pool.may_close(entry.slug, "leso", False) != ""


def test_note_agent_never_raises_for_an_editor_in_no_episode():
    pool = cards_pool.EnginePool(lambda root: (FakeEngine(root), object()),
                                 cap=2)
    pool.note_agent("nobody")
    pool.note_agent("")


def test_the_row_names_who_was_last_in_and_when():
    """The close stays allowed (CR-285P's wedge), but it is no longer blind:
    the landing row and the confirm both name the last occupant and how long
    ago, which is what tells an idle engine from an offline editor."""
    from ccsync_dashboard import cards_landing

    pool = cards_pool.EnginePool(lambda root: (FakeEngine(root), object()),
                                 cap=2)
    entry = _settle(pool.open("X:/Vault/FF5/Civil Defence")[0])
    pool.note_visit(entry.slug, "ruskin")
    entry.seen["ruskin"] = time.time() - 22 * 60
    who, ago = entry.last_in()
    assert who == "ruskin" and ago is not None and ago > 20 * 60
    assert entry.as_dict()["last_in"] == "ruskin"
    phrase = cards_landing._last_in_phrase(who, ago)
    assert phrase == "ruskin was last in 22 min ago"
    prompt = cards_landing._close_prompt("Civil Defence", phrase)
    assert "Civil Defence" in prompt and "ruskin was last in 22 min ago" in prompt
    assert "-" not in prompt.replace("Close ", "")   # no em dash, no hyphen run
    assert cards_landing._last_in_phrase("", None) == ""


def test_the_landing_page_renders_the_confirm_and_the_last_in_line(landing):
    """security-1: the row flag and the POST gate already agree (both ask
    `may_close`); what was missing is the FACT the presser needs. An episode
    nobody has served a request for in 22 minutes may still be somebody's
    offline session, so the row names them and the button asks first."""
    client, app, roots = landing
    slug = cards_pool.slug_for(str(roots[0]))
    client.post("/cards/open", data={"slug": slug}, follow_redirects=False)
    entry = app.state.cards_pool.get(slug)
    while entry.state == cards_pool.LOADING:
        time.sleep(0.02)
    entry.seen["owen"] = time.time() - 22 * 60
    page = client.get("/cards/")
    assert page.status_code == 200
    assert "owen was last in 22 min ago" in page.text
    assert "confirm(" in page.text
